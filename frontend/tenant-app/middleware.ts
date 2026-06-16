// @chanteur/tenant-app — L1+L2 middleware (13.1.2: oturum + tenant scope + panel ayrımı).
// SAD §14.4.1 (Frontend route group + middleware) · ADR-011 (L1+L2 birlikte public) · FR-TEN-002/FR-IAM-008.
//
// Bu middleware ÇALIŞMA-ANI kapısıdır (13.1.1'in iskelet yer tutucusunun yerini alır):
//  1) OTURUM: tenant realm oturumu yoksa/expired → login'e yönlendir (?next=).
//  2) REALM/PANEL AYRIMI: platform realm oturumu tenant-app'e GİREMEZ → 403 (FR-IAM-008).
//  3) TENANT SCOPE (FR-TEN-002): oturum tek tenant_id'ye BAĞLI; bağlı değilse → 403; istek tenant
//     ipucu (?tenant=/x-tenant-id) oturum tenant'ından farklıysa cross-tenant gezinme reddi → 403.
//  4) PANEL: /admin/* → L1 (tenant-admin), /workspace/* → L2 (workspace); downstream context header.
//
// NİHAİ YETKİ KARARI HER ZAMAN BACKEND'DE (12.2.x; PostgreSQL RLS ile çift tenant kontrolü §13).
// UI yalnız görsel kapı (A8). Karar mantığı saf çekirdektedir (lib/middleware-core.ts).
import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";
import { APP_REALM, SESSION_COOKIE, parseSessionToken } from "./lib/session";
import { decide, type AppPolicy } from "./lib/middleware-core";

const POLICY: AppPolicy = {
  app: "tenant-app",
  realm: APP_REALM, // "tenant"
  plane: "tenant_application_plane",
  tier: "L1+L2",
  tenantScoped: true, // tek tenant'a bağlı — FR-TEN-002
  loginPath: "/login",
  exemptPrefixes: ["/login", "/api/auth"],
  routeGroups: [
    { prefix: "/admin", group: "(tenant-admin)", panel: "L1" },
    { prefix: "/workspace", group: "(workspace)", panel: "L2" },
  ],
};

export function middleware(req: NextRequest) {
  const path = req.nextUrl.pathname;
  const session = parseSessionToken(req.cookies.get(SESSION_COOKIE)?.value ?? null);
  const requestedTenant =
    req.nextUrl.searchParams.get("tenant") || req.headers.get("x-tenant-id");
  const correlationId = req.headers.get("x-correlation-id") || crypto.randomUUID();
  const now = Math.floor(Date.now() / 1000);

  const d = decide(POLICY, { path, session, now, requestedTenant, correlationId });

  if (d.action === "redirect") {
    const url = req.nextUrl.clone();
    const [p, q] = (d.location as string).split("?");
    url.pathname = p;
    url.search = q ? `?${q}` : "";
    const res = NextResponse.redirect(url);
    res.headers.set("x-mw-reason", d.reason);
    return res;
  }
  if (d.action === "forbid") {
    const res = new NextResponse("Forbidden", { status: d.status ?? 403 });
    res.headers.set("x-mw-reason", d.reason);
    res.headers.set("x-app-plane", POLICY.plane);
    return res;
  }
  // next — downstream'e (server component/backend) tenant scope + panel context header'larını enjekte et
  const requestHeaders = new Headers(req.headers);
  for (const [k, v] of Object.entries(d.headers)) requestHeaders.set(k, v);
  const res = NextResponse.next({ request: { headers: requestHeaders } });
  res.headers.set("x-app-plane", POLICY.plane);
  res.headers.set("x-mw-reason", d.reason);
  return res;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
