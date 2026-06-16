// @chanteur/tenant-app — L1+L2 middleware iskeleti (ADR-011, SAD §14.4.1).
//
// KAPSAM (13.1.1): yalnız iki-app ayrımının frontend iskeleti. Çalışma-anı oturum doğrulama +
// TENANT SCOPE sabitleme (L1/L2 oturumu tek bir tenant_id'ye bağlı; cross-tenant gezinme yok —
// FR-TEN-002) ENFORCEMENT'ı 13.1.2'de (route group + middleware) eklenir. Nihai YETKİ KARARI
// HER ZAMAN backend'dedir (12.2.x; SAD §14.4.1 "UI yalnız görsel kapıdır" — A8). Burada
// hardcoded authz KARARI YOKTUR.
//
// ADR-011: bu app (tenant-admin) [L1] + (workspace) [L2] route group'larını barındırır;
// (platform) [L0] route group BURADA YOKTUR (A3).
import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

export function middleware(_req: NextRequest) {
  // 13.1.2 yer tutucu: oturum (tenant realm) + tenant_scope (tek tenant) + L1/L2 rol guard burada.
  const res = NextResponse.next();
  res.headers.set("x-app-plane", "tenant_application_plane"); // gözlemlenebilirlik (düşük kardinalite)
  return res;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
