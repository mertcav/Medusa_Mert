// @chanteur/platform-app — middleware KARAR ÇEKİRDEĞİ (saf/pure; 13.1.2, SAD §14.4.1).
//
// Bu modül oturum + realm/panel ayrımı + tenant scope kararını SAF bir fonksiyon olarak verir
// (Next/edge API'sinden bağımsız → birim-test edilebilir + Python probe ile birebir aynalanabilir).
//
// İLKE (A8): UI yalnız GÖRSEL kapıdır; bu karar coarse bir UX/yönlendirme kapısıdır
// (kimlik var mı + doğru realm mı + tek tenant'a mı bağlı + doğru panele mi yönlendi).
// NİHAİ yetki (rol→permission, kaynak sahipliği) HER ZAMAN backend'de (12.2.x, SAD §14.4.2).
// Burada rol→izin KARARI YOKTUR.
import type { SessionClaims } from "./session";

export type Action = "next" | "redirect" | "forbid";

export interface RouteGroup {
  prefix: string;
  group: string;
  panel: string;
}

export interface AppPolicy {
  app: string;
  realm: string;
  plane: string;
  tier: string;
  tenantScoped: boolean; // platform-app: false (L0 cross-tenant); tenant-app: true (FR-TEN-002)
  loginPath: string;
  exemptPrefixes: string[]; // oturum gerektirmeyen yollar (login, auth callback)
  routeGroups: RouteGroup[];
}

export interface DecisionInput {
  path: string;
  session: SessionClaims | null;
  now: number; // epoch saniye
  requestedTenant: string | null; // ?tenant= / x-tenant-id ipucu (cross-tenant kurcalama tespiti)
  correlationId: string;
}

export interface Decision {
  action: Action;
  reason: string;
  location?: string; // redirect hedefi
  status?: number; // forbid kodu
  headers: Record<string, string>; // downstream'e (server component/backend) enjekte edilen istek header'ları
}

export function isExempt(policy: AppPolicy, path: string): boolean {
  return policy.exemptPrefixes.some(
    (p) => path === p || path.startsWith(p + "/"),
  );
}

/** Path'i en uzun eşleşen route group prefix'ine çözer (panel ayrımı). */
export function resolveGroup(policy: AppPolicy, path: string): RouteGroup | null {
  let best: RouteGroup | null = null;
  for (const rg of policy.routeGroups) {
    const match =
      rg.prefix === "/" || path === rg.prefix || path.startsWith(rg.prefix + "/");
    if (match && (!best || rg.prefix.length > best.prefix.length)) best = rg;
  }
  return best;
}

/**
 * Fail-closed karar: belirsizlik/eksik oturum → yönlendir veya reddet; ASLA sessizce izin verme.
 * Sıra: exempt → oturum yok → süre doldu → realm/panel ayrımı → tenant scope → panel header'ları.
 */
export function decide(policy: AppPolicy, input: DecisionInput): Decision {
  const baseHeaders: Record<string, string> = {
    "x-app-plane": policy.plane, // düşük kardinalite (0.4.7 label_policy)
    "x-app-tier": policy.tier,
    "x-correlation-id": input.correlationId,
  };

  // A — exempt yollar (login/auth callback): oturumsuz geçer
  if (isExempt(policy, input.path)) {
    return { action: "next", reason: "exempt", headers: baseHeaders };
  }

  // B — oturum yok → login'e yönlendir (?next= ile dönüş); sessiz izin YOK
  if (!input.session) {
    const loc = `${policy.loginPath}?next=${encodeURIComponent(input.path)}`;
    return { action: "redirect", reason: "no_session", location: loc, headers: baseHeaders };
  }

  // C — süresi dolmuş oturum → login
  if (!Number.isFinite(input.session.exp) || input.session.exp <= input.now) {
    const loc = `${policy.loginPath}?next=${encodeURIComponent(input.path)}&reason=expired`;
    return { action: "redirect", reason: "expired_session", location: loc, headers: baseHeaders };
  }

  // D — realm/plane ayrımı: yanlış realm oturumu bu app'e GİREMEZ (panel ayrımı; FR-IAM-008)
  if (input.session.realm !== policy.realm) {
    return { action: "forbid", reason: "realm_mismatch", status: 403, headers: baseHeaders };
  }

  // E — tenant scope
  const scopeHeaders: Record<string, string> = {};
  if (policy.tenantScoped) {
    const tid = input.session.tenant_id;
    if (!tid) {
      return { action: "forbid", reason: "missing_tenant_binding", status: 403, headers: baseHeaders };
    }
    // cross-tenant gezinme reddi (FR-TEN-002): istek tenant ipucu oturum tenant'ından farklı
    if (input.requestedTenant && input.requestedTenant !== tid) {
      return { action: "forbid", reason: "cross_tenant_denied", status: 403, headers: baseHeaders };
    }
    scopeHeaders["x-tenant-scope"] = tid;
  } else {
    // platform realm tenant'a bağlı OLMAMALI (L0 cross-tenant; iş içeriği yok — A5/FR-IAM-008)
    if (input.session.tenant_id) {
      return { action: "forbid", reason: "unexpected_tenant_binding", status: 403, headers: baseHeaders };
    }
  }

  // F — panel ayrımı: path → route group/panel; downstream context header'ları
  const rg = resolveGroup(policy, input.path);
  const panelHeaders: Record<string, string> = rg
    ? { "x-panel": rg.panel, "x-route-group": rg.group }
    : {};

  return {
    action: "next",
    reason: "allow",
    headers: {
      ...baseHeaders,
      ...scopeHeaders,
      ...panelHeaders,
      "x-auth-subject": input.session.sub, // downstream/backend için; metrik label'ı DEĞİL
    },
  };
}
