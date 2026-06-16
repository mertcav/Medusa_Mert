// @chanteur/tenant-app — oturum (session) okuma katmanı (13.1.2, SAD §14.4.1, FR-TEN-002/FR-IAM-008).
//
// VENDOR-NEUTRAL (ADR-002): belirli bir auth sağlayıcısına bağlanmaz. Oturum, tenant auth realm'inin
// (TENANT_AUTH_ISSUER — OIDC/SAML; platform realm'inden AYRI, FR-IAM-008) yayınladığı bir oturum
// token'ında (JWT-benzeri) taşınır. Bu katman token'ın YALNIZ claim payload'ını okur
// (realm/sub/exp/tenant_id) ve YAPISAL geçerlilik kontrolü yapar — UX kapısı için. KRİPTOGRAFİK
// imza/issuer doğrulaması auth realm + backend'dedir (12.2.x, SAD §14.4.1 "UI yalnız görsel kapı" — A8).
//
// TENANT SCOPE (FR-TEN-002): L1/L2 oturumu tek bir tenant_id'ye bağlıdır; cross-tenant gezinme yok.
// SIR/CREDENTIAL YOK: çerez ADI sır değildir; gerçek token değeri yalnız çalışma-anı isteğinde gelir.

export const APP_REALM = "tenant" as const;

export const SESSION_COOKIE =
  process.env.TENANT_SESSION_COOKIE || "__chanteur_tenant_session";

export interface SessionClaims {
  sub: string; // opaque kullanıcı kimliği (PII değil; metrik label'ı OLMAZ)
  realm: string; // "tenant" beklenir
  tenant_id: string | null; // tenant realm: ZORUNLU (tek tenant'a bağlı — FR-TEN-002)
  exp: number; // epoch saniye
}

function b64urlDecode(input: string): string | null {
  try {
    const pad = input.length % 4 === 0 ? "" : "=".repeat(4 - (input.length % 4));
    const b64 = input.replace(/-/g, "+").replace(/_/g, "/") + pad;
    return atob(b64);
  } catch {
    return null;
  }
}

/**
 * Oturum token'ından claim'leri çıkarır (YALNIZ payload; imza doğrulanmaz — backend doğrular, A8).
 * Yapısal olarak geçersizse null → çağıran fail-closed davranır.
 */
export function parseSessionToken(token: string | undefined | null): SessionClaims | null {
  if (!token) return null;
  const parts = token.split(".");
  const payloadRaw = parts.length === 3 ? parts[1] : parts.length === 1 ? token : null;
  if (!payloadRaw) return null;
  const json = b64urlDecode(payloadRaw);
  if (!json) return null;
  let claims: unknown;
  try {
    claims = JSON.parse(json);
  } catch {
    return null;
  }
  if (!claims || typeof claims !== "object") return null;
  const c = claims as Record<string, unknown>;
  if (typeof c.sub !== "string" || !c.sub) return null;
  if (typeof c.realm !== "string" || !c.realm) return null;
  if (typeof c.exp !== "number" || !Number.isFinite(c.exp)) return null;
  const tenant_id =
    typeof c.tenant_id === "string" && c.tenant_id ? c.tenant_id : null;
  return { sub: c.sub, realm: c.realm, tenant_id, exp: c.exp };
}
