// @chanteur/platform-app — oturum (session) okuma katmanı (13.1.2, SAD §14.4.1, FR-IAM-008).
//
// VENDOR-NEUTRAL (ADR-002): belirli bir auth sağlayıcısına bağlanmaz. Oturum, auth realm'inin
// (PLATFORM_AUTH_ISSUER — OIDC/SAML) yayınladığı bir oturum token'ında (JWT-benzeri) taşınır.
// Bu katman token'ın YALNIZ claim payload'ını okur (realm/sub/exp/tenant_id) ve YAPISAL geçerlilik
// kontrolü yapar — UX kapısı için. KRİPTOGRAFİK imza/issuer doğrulaması auth realm + backend'dedir
// (12.2.x, SAD §14.4.1: "UI yalnız görsel kapıdır; yetki kararı her zaman backend'de" — A8).
// Edge'de JWKS ile imza doğrulaması F2'de eklenebilir (seam burada).
//
// SIR/CREDENTIAL YOK: çerez ADI bir sır değildir; gerçek token değeri yalnız çalışma-anı isteğinde gelir.

export const APP_REALM = "platform" as const;

// Çerez adı deploy ortamından (${ENV}); makul varsayılan. (Ad sır değildir.)
export const SESSION_COOKIE =
  process.env.PLATFORM_SESSION_COOKIE || "__chanteur_platform_session";

export interface SessionClaims {
  sub: string; // opaque kullanıcı kimliği (PII değil; metrik label'ı OLMAZ — yalnız downstream header/trace)
  realm: string; // "platform" beklenir (yanlış realm → panel ayrımı ihlali)
  tenant_id: string | null; // platform realm: null (L0 cross-tenant; tek tenant'a bağlı DEĞİL)
  exp: number; // epoch saniye (süre dolumu kontrolü)
}

function b64urlDecode(input: string): string | null {
  try {
    const pad = input.length % 4 === 0 ? "" : "=".repeat(4 - (input.length % 4));
    const b64 = input.replace(/-/g, "+").replace(/_/g, "/") + pad;
    // atob edge runtime'da global olarak mevcut.
    return atob(b64);
  } catch {
    return null;
  }
}

/**
 * Oturum token'ından claim'leri çıkarır (YALNIZ payload; imza doğrulanmaz — backend doğrular, A8).
 * Yapısal olarak geçersizse null döner → çağıran fail-closed davranır (oturum yok say).
 */
export function parseSessionToken(token: string | undefined | null): SessionClaims | null {
  if (!token) return null;
  const parts = token.split(".");
  // JWT (header.payload.signature) → payload; ya da düz base64url payload (test/opaque).
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
