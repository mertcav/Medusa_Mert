// WBS 13.3.3 — T-03 "Kullanıcı & Rol Yönetimi (RBAC/SSO/SCIM)" veri katmanı (seam) + SAF türetme
// yardımcıları (L1 — Tenant Admin Console).
//
// ÇEKİRDEK İLKELER:
//  - İÇERİK (BRD §17.4 / FR-IAM-001/002/007/011): tenant İÇİ RBAC (kullanıcı–rol atamaları), SSO (SAML 2.0 /
//    OIDC) ve SCIM provisioning ayarları. Roller değişmez (immutable) permission bundle'lardır; esneklik yalnız
//    atama KAPSAM (scope) filtresiyle (departman/marka/kampanya) sağlanır (FR-IAM-011, ADR-012). v1'de custom
//    permission-builder YOK; tam custom roller Faz 3 (enterprise/dedicated).
//  - TENANT-SCOPE (FR-TEN-002): T-03 YALNIZ oturum açan tenant'ın KENDİ kullanıcılarını/rollerini gösterir/
//    yönetir; başka tenant'ın kullanıcısı erişilmez. Scope çalışma-anında middleware (13.1.2) + RLS (§13) ile
//    sabitlenir; UI yalnız görsel kapı (SAD §14.4.1 A8).
//  - HİJYEN (BRD §17.7 ruhu): yapı yalnız KONFİGÜRASYON/KİMLİK metadatasıdır (kullanıcı oturum kimliği, rol
//    atamaları, SSO/SCIM ayarları). Ham SON-MÜŞTERİ iş içeriği (çağrı kaydı, transkript, müşteri/PII) buraya
//    GÖMÜLMEZ. Tipler yapısal olarak son-müşteri PII taşımaz; `assertNoPii` çalışma-anında doğrular (sızıntı →
//    hata). NOT: `principal`/`displayName` tenant'ın KENDİ yönetim kullanıcısının kimliğidir (tenantName gibi
//    izinli — son-müşteri PII DEĞİL); yasak liste yalnız son-müşteri içerik/PII alan adlarıdır.
//  - GÜVENLİK: SSO/SCIM SIRRI (federation metadata sertifikası, SCIM bearer token) buraya KONMAZ — yalnız
//    yapılandırıldı/yapılandırılmadı durumu (`tokenConfigured` bayrağı). Gerçek sır backend secret store'da
//    (NFR 10.6); UI sırrı göstermez.
//  - VENDOR-NEUTRAL (ADR-002): veri kaynağı bir SEAM'dir; gerçek implementasyon (F2 §14.1) IAM/Directory servisi
//    + SSO (SAML/OIDC) + SCIM köprüsünden tenant-scope beslenir. Belirli IdP/SaaS bağlanmaz.
//  - SAF/DETERMİNİSTİK: türetme yardımcıları (countUserStatus/usersForRole/scopedAssignmentCount/...) Date.now/
//    rastgelelik içermez → birim-test edilebilir + Python aynası (screens/t03-users/t03_users_probe.py).
//  - İŞ MANTIĞI/AUTHZ YOK (SAD §14.4.1 A8): rol→permission kararı YOK; nihai yetki backend'de (12.2.x) + RLS.

export type RoleTier = "L1" | "L2" | "L1+L2";
export type UserStatus = "active" | "invited" | "suspended";
export type UserSource = "local" | "sso" | "scim";
export type SsoProtocol = "saml" | "oidc" | "none";
export type ConnState = "connected" | "disabled" | "error";

export type StatusTone = "success" | "warning" | "danger" | "neutral" | "info";

// Tenant rolü (FR-IAM-011): değişmez permission bundle. key = rol kimliği (ör. tenant_admin); tier = panel katmanı.
export interface TenantRole {
  key: string; // sabit rol kimliği (immutable bundle, ADR-012) — identifier, prose değil
  tier: RoleTier;
  immutable: boolean; // v1'de tüm roller true; custom roller Faz 3
}

// Tenant yönetim kullanıcısı. principal/displayName tenant'ın KENDİ kimliğidir (son-müşteri PII DEĞİL).
export interface TenantUser {
  id: string;
  principal: string; // oturum kimliği / SSO subject (tenant'ın KENDİ yönetim kullanıcısı — izinli)
  displayName: string; // tenant'ın KENDİ kullanıcı adı (izinli)
  roles: string[]; // atanan rol key'leri (TenantRole.key referansı)
  scope: string | null; // atama kapsam filtresi (departman/marka/kampanya); null => tüm tenant (FR-IAM-011)
  source: UserSource; // provisioning kaynağı: local | sso (FR-IAM-002) | scim (FR-IAM-007)
  mfaEnabled: boolean; // çok faktörlü kimlik doğrulama (FR-IAM-003)
  status: UserStatus;
}

// SSO ayarları (FR-IAM-002): SAML 2.0 / OIDC. SIR YOK — yalnız bağlantı durumu + politika bayrakları.
export interface SsoSettings {
  protocol: SsoProtocol;
  state: ConnState;
  idpLabel: string | null; // IdP görünen adı (tenant konfigürasyonu — izinli); sertifika/metadata YOK
  mfaEnforced: boolean; // IdP-seviyesi MFA zorunluluğu (FR-IAM-003)
  jitProvisioning: boolean; // just-in-time kullanıcı oluşturma
  defaultRole: string | null; // SSO ile gelen kullanıcıya varsayılan rol (key); IdP grup→rol eşlemesi
}

// SCIM ayarları (FR-IAM-007): kullanıcı provisioning + IdP grup→rol eşlemesi. SIR YOK (token saklanmaz).
export interface ScimSettings {
  state: ConnState;
  tokenConfigured: boolean; // bearer token YAPILANDIRILDI mı (token DEĞERİ asla burada değil — backend secret store)
  lastSyncAt: string | null; // son senkron ISO-8601 (sabit yer tutucu — Date.now YOK)
  syncedUsers: number; // SCIM ile senkronize kullanıcı sayısı
  groupMappings: number; // IdP grup→rol eşleme sayısı
}

export interface UserRoleSnapshot {
  generatedAt: string; // ISO-8601 (sabit yer tutucu — SSR-stabil, Date.now YOK)
  tenantRef: string; // tenant'ın KENDİ kimliği (L1'de izinli)
  tenantName: string; // tenant org adı (izinli; son-müşteri verisi DEĞİL)
  users: TenantUser[];
  roles: TenantRole[];
  sso: SsoSettings;
  scim: ScimSettings;
}

// ── saf türetme yardımcıları ────────────────────────────────────────────────────

// Durum bazında kullanıcı sayısı.
export function countUserStatus(users: TenantUser[]): Record<UserStatus, number> {
  const out: Record<UserStatus, number> = { active: 0, invited: 0, suspended: 0 };
  for (const u of users) out[u.status] += 1;
  return out;
}

// Provisioning kaynağı bazında kullanıcı sayısı (local / sso / scim).
export function countUserSource(users: TenantUser[]): Record<UserSource, number> {
  const out: Record<UserSource, number> = { local: 0, sso: 0, scim: 0 };
  for (const u of users) out[u.source] += 1;
  return out;
}

// Bir role atanan kullanıcı sayısı.
export function usersForRole(users: TenantUser[], roleKey: string): number {
  return users.filter((u) => u.roles.includes(roleKey)).length;
}

// KAPSAMLI atama sayısı (scope filtresi olan kullanıcılar — FR-IAM-011). scope null/boş => tüm tenant (kapsamsız).
export function scopedAssignmentCount(users: TenantUser[]): number {
  return users.filter((u) => u.scope !== null && u.scope.trim() !== "").length;
}

// GÜVENLİK: MFA'sı OLMAYAN AKTİF kullanıcılar (FR-IAM-003). Kullanıcı id listesi (UI uyarısı tetikler).
export function usersMissingMfa(users: TenantUser[]): string[] {
  return users.filter((u) => u.status === "active" && !u.mfaEnabled).map((u) => u.id);
}

// HİJYEN/BÜTÜNLÜK: tanımlı OLMAYAN bir role atanmış kullanıcılar (geçersiz rol referansı). Kullanıcı id listesi.
// Boş dönmesi RBAC tutarlılığını gösterir; dolu liste rol referansı düzeltmesi (UI uyarısı) tetikler.
export function invalidRoleRefs(users: TenantUser[], roles: TenantRole[]): string[] {
  const keys = new Set(roles.map((r) => r.key));
  const out: string[] = [];
  for (const u of users) {
    if (u.roles.some((rk) => !keys.has(rk))) out.push(u.id);
  }
  return out;
}

// ── ton (renk) eşlemeleri ─────────────────────────────────────────────────────────

const USER_STATUS_TONE: Record<UserStatus, StatusTone> = {
  active: "success",
  invited: "warning",
  suspended: "danger",
};
export function userStatusTone(s: UserStatus): StatusTone {
  return USER_STATUS_TONE[s];
}

const SOURCE_TONE: Record<UserSource, StatusTone> = {
  local: "neutral",
  sso: "info",
  scim: "info",
};
export function sourceTone(s: UserSource): StatusTone {
  return SOURCE_TONE[s];
}

const CONN_TONE: Record<ConnState, StatusTone> = {
  connected: "success",
  disabled: "neutral",
  error: "danger",
};
export function connStateTone(s: ConnState): StatusTone {
  return CONN_TONE[s];
}

const TIER_TONE: Record<RoleTier, StatusTone> = {
  L1: "info",
  L2: "neutral",
  "L1+L2": "info",
};
export function roleTierTone(t: RoleTier): StatusTone {
  return TIER_TONE[t];
}

export function mfaTone(enabled: boolean): StatusTone {
  return enabled ? "success" : "warning";
}

// ── HİJYEN koruması (ham son-müşteri PII/iş-içeriği sızıntısı) ─────────────────────
// Yapı içinde son-müşteri iş içeriği/PII'yi çağrıştıran ALAN ADI bulunursa hata fırlatır. Bu, T-03'ün yalnız
// yönetim kimliği + RBAC/SSO/SCIM konfigürasyonu göstermesini çalışma-anında garanti eder (BRD §17.7 ruhu).
// NOT: tenantName/tenantRef + kullanıcı principal/displayName + idpLabel tenant'ın KENDİ konfigürasyonudur →
// yasak listede DEĞİL (izinli). Yasak liste yalnız SON-MÜŞTERİ PII/çağrı içeriği alan adlarıdır.
export const FORBIDDEN_PII_KEYS: readonly string[] = [
  "transcript",
  "recording",
  "recordingurl",
  "audio",
  "msisdn",
  "phonenumber",
  "callerid",
  "customer",
  "cardpan",
  "cvv",
  "ssn",
  "pii",
];

// GÜVENLİK ek koruması: SSO/SCIM SIRRI alan adı (sertifika/token değeri) buraya konmamalı (NFR 10.6).
export const FORBIDDEN_SECRET_KEYS: readonly string[] = [
  "token",
  "bearertoken",
  "secret",
  "clientsecret",
  "privatekey",
  "certificate",
  "metadataxml",
];

export function assertNoPii(node: unknown, path = "$"): void {
  if (node && typeof node === "object") {
    if (Array.isArray(node)) {
      node.forEach((v, i) => assertNoPii(v, `${path}[${i}]`));
      return;
    }
    for (const k of Object.keys(node as Record<string, unknown>)) {
      const lower = k.toLowerCase();
      if (FORBIDDEN_PII_KEYS.includes(lower)) {
        throw new Error(`T-03 HİJYEN ihlali: yasak PII/iş-içeriği alanı "${path}.${k}" (BRD §17.7)`);
      }
      if (FORBIDDEN_SECRET_KEYS.includes(lower)) {
        throw new Error(`T-03 GÜVENLİK ihlali: SSO/SCIM sırrı alanı "${path}.${k}" panele konmaz (NFR 10.6)`);
      }
      assertNoPii((node as Record<string, unknown>)[k], `${path}.${k}`);
    }
  }
}

// ── veri SEAM (yer tutucu) ───────────────────────────────────────────────────────
// Deterministik yer tutucu: tek-tenant kullanıcı/rol/SSO/SCIM konfigürasyonu (KİMLİK + RBAC metadatası — son-
// müşteri PII/iş-içeriği DEĞİL, SSO/SCIM SIRRI DEĞİL). Gerçek implementasyon (F2 §14.1) IAM/Directory servisi +
// SSO/SCIM köprüsünden tenant-scope (RLS) beslenir.
const PLACEHOLDER_SNAPSHOT: UserRoleSnapshot = {
  generatedAt: "2026-06-17T09:00:00.000Z",
  tenantRef: "TEN-2048",
  tenantName: "Kuzey Sigorta A.Ş.",
  users: [
    { id: "U-001", principal: "owner@kuzey.example", displayName: "Aslı Demir", roles: ["tenant_owner"], scope: null, source: "local", mfaEnabled: true, status: "active" },
    { id: "U-002", principal: "admin@kuzey.example", displayName: "Mert Yılmaz", roles: ["tenant_admin"], scope: null, source: "sso", mfaEnabled: true, status: "active" },
    { id: "U-003", principal: "sco@kuzey.example", displayName: "Elif Kaya", roles: ["security_compliance_officer"], scope: null, source: "sso", mfaEnabled: true, status: "active" },
    { id: "U-004", principal: "ops.retail@kuzey.example", displayName: "Can Öz", roles: ["operations_manager"], scope: "BR-RETAIL", source: "scim", mfaEnabled: true, status: "active" },
    { id: "U-005", principal: "qa@kuzey.example", displayName: "Deniz Ak", roles: ["qa_analyst"], scope: "DP-SUPPORT", source: "scim", mfaEnabled: false, status: "active" },
    { id: "U-006", principal: "designer@kuzey.example", displayName: "Naz Çelik", roles: ["conversation_designer"], scope: null, source: "local", mfaEnabled: true, status: "invited" },
    { id: "U-007", principal: "dev@kuzey.example", displayName: "Burak Şen", roles: ["api_developer"], scope: null, source: "local", mfaEnabled: false, status: "suspended" },
  ],
  roles: [
    { key: "tenant_owner", tier: "L1+L2", immutable: true },
    { key: "tenant_admin", tier: "L1", immutable: true },
    { key: "security_compliance_officer", tier: "L1", immutable: true },
    { key: "billing_viewer", tier: "L1", immutable: true },
    { key: "api_developer", tier: "L1+L2", immutable: true },
    { key: "operations_manager", tier: "L2", immutable: true },
    { key: "conversation_designer", tier: "L2", immutable: true },
    { key: "qa_analyst", tier: "L2", immutable: true },
    { key: "human_agent", tier: "L2", immutable: true },
  ],
  sso: {
    protocol: "oidc",
    state: "connected",
    idpLabel: "Kuzey Kurumsal Dizin",
    mfaEnforced: true,
    jitProvisioning: true,
    defaultRole: "human_agent",
  },
  scim: {
    state: "connected",
    tokenConfigured: true,
    lastSyncAt: "2026-06-17T06:30:00.000Z",
    syncedUsers: 2,
    groupMappings: 4,
  },
};

export async function getUserRoles(): Promise<UserRoleSnapshot> {
  const snap = PLACEHOLDER_SNAPSHOT;
  assertNoPii(snap); // HİJYEN + GÜVENLİK: yapısal son-müşteri PII / SSO-SCIM sırrı yok (BRD §17.7 / NFR 10.6)
  return snap;
}
