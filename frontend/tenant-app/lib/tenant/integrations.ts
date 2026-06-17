// WBS 13.3.5 — T-05 "Entegrasyon, Tool & API Key/Webhook" veri katmanı (seam) + SAF türetme yardımcıları
// (L1 — Tenant Admin Console).
//
// ÇEKİRDEK İLKELER:
//  - İÇERİK (BRD §17.4 / FR-TOOL-001..012 · API.md §7 [API key/webhook] · §10 [webhook event]): tenant'ın
//    kurumsal sistem ENTEGRASYONLARI (CRM/ERP/ticketing/custom), bunların üstüne tanımlı TOOL'lar (REST/SOAP/
//    GraphQL/webhook — FR-TOOL-001), programatik erişim için API ANAHTARLARI (S4 Public Developer API) ve giden
//    olay WEBHOOK tanımları (§10).
//  - TENANT-SCOPE (FR-TEN-002): T-05 YALNIZ oturum açan tenant'ın KENDİ entegrasyon/tool/anahtar/webhook
//    konfigürasyonunu gösterir/yönetir; başka tenant'ın envanteri erişilmez. Scope çalışma-anında middleware
//    (13.1.2) + RLS (§13) ile sabitlenir; UI yalnız görsel kapı (SAD §14.4.1 A8).
//  - HİJYEN (BRD §17.7 ruhu): yapı yalnız tenant'ın KENDİ ENTEGRASYON KONFİGÜRASYONUDUR (bağlantı adı/türü,
//    tool tanımı, anahtar metadatası, webhook URL/event aboneliği). Ham SON-MÜŞTERİ iş içeriği (çağrı kaydı,
//    transkript, müşteri PII) buraya GÖMÜLMEZ. Tipler yapısal olarak son-müşteri PII taşımaz; `assertNoPii`
//    çalışma-anında doğrular. NOT: integration `name`, tool `name`, webhook `url`, API key `name`/`scopes`
//    tenant'ın KENDİ konfigürasyonudur (tenantName gibi izinli — son-müşteri PII DEĞİL).
//  - GÜVENLİK (NFR 10.6): SIR buraya KONMAZ — API key `secret` (S4: yalnız bir kez döner, sunucu hash saklar),
//    webhook `signing_secret` (whsec_…; bir kez döner), entegrasyon credential (OAuth client secret / bearer
//    token / parola) panele konmaz; yalnız durum + scope + son-kullanım metadatası. Gerçek sır backend secret
//    store'da; UI sırrı göstermez. `authMethod`/`status` yalnız YÖNTEM/DURUM adıdır — sır DEĞİL.
//  - VENDOR-NEUTRAL (ADR-002): veri kaynağı bir SEAM'dir; gerçek implementasyon (F2 §14.1) Integration Gateway +
//    Tool Registry + API key/webhook servisinden tenant-scope (RLS) beslenir. Belirli CRM/ERP/SaaS markası
//    bağlanmaz.
//  - SAF/DETERMİNİSTİK: türetme yardımcıları (countIntegrationState/invalidIntegrationRefs/isHttpsUrl/...) Date.
//    now/rastgelelik içermez → birim-test edilebilir + Python aynası (screens/t05-integrations/t05_integrations_probe.py).
//  - İŞ MANTIĞI/AUTHZ YOK (SAD §14.4.1 A8): tool çağırma/anahtar oluşturma/webhook gönderme kararı YOK; nihai
//    yetki backend'de (12.2.x) + RLS.

export type IntegrationType = "crm" | "erp" | "ticketing" | "custom"; // CRM/ERP/ticketing/özel (BRD §17.4)
export type AuthMethod = "oauth2" | "api_key" | "basic" | "mtls"; // YALNIZ yöntem adı — SIR DEĞİL (NFR 10.6)
export type ConnState = "connected" | "degraded" | "disabled" | "error";
export type ToolProtocol = "rest" | "soap" | "graphql" | "webhook"; // FR-TOOL-001
export type ToolAccess = "read" | "write"; // okuma/yazma ayrı güvenlik seviyesi (FR-TOOL-005)
export type ApiKeyStatus = "active" | "revoked" | "expired";
export type WebhookStatus = "active" | "disabled" | "failing";

export type StatusTone = "success" | "warning" | "danger" | "neutral" | "info";

// Kurumsal sistem entegrasyonu (CRM/ERP/ticketing/custom). SIR YOK — yalnız durum + yöntem + metadatası.
export interface Integration {
  id: string;
  name: string; // tenant konfigürasyon etiketi (izinli)
  type: IntegrationType; // crm | erp | ticketing | custom
  authMethod: AuthMethod; // YÖNTEM adı (oauth2/api_key/...) — sır DEĞİL
  state: ConnState;
  region: string; // residency bölgesi (NFR 10.7) — kod (ör. eu-west)
  lastSyncAt: string | null; // ISO-8601 son senkron (sabit yer tutucu); null => hiç
}

// Tool/iş süreci tanımı (FR-TOOL-001/002/004/005/006/007). access write => yazma (ek güvenlik); confirmRequired
// kritik işlem teyidi (FR-TOOL-006/007); schemaValidated JSON schema doğrulaması (FR-TOOL-002).
export interface ToolDef {
  id: string;
  name: string; // tenant konfigürasyon etiketi (izinli)
  protocol: ToolProtocol; // rest | soap | graphql | webhook (FR-TOOL-001)
  access: ToolAccess; // read | write (FR-TOOL-005)
  schemaValidated: boolean; // I/O JSON schema doğrulaması (FR-TOOL-002)
  confirmRequired: boolean; // kritik işlem öncesi müşteri teyidi (FR-TOOL-006/007)
  integrationRef: string | null; // bağlı Integration.id (null => bağımsız/inline)
  enabled: boolean; // tool aktif mi
}

// Programatik erişim için API anahtarı (S4 Public Developer API). SIR YOK — `secret` yalnız oluşturmada bir kez
// döner (API.md §7.2), burada saklanmaz/gösterilmez. Yalnız metadata (ad/scope/durum/son-kullanım).
export interface ApiKey {
  id: string;
  name: string; // tenant etiketi (izinli)
  scopes: string[]; // permission-key listesi (izinli — sır DEĞİL)
  status: ApiKeyStatus; // active | revoked | expired
  createdAt: string; // ISO-8601 (sabit yer tutucu)
  lastUsedAt: string | null; // ISO-8601 son kullanım; null => hiç
}

// Giden olay webhook tanımı (§10). HTTPS zorunlu. SIR YOK — `signing_secret` (whsec_…) yalnız oluşturmada bir
// kez döner (API.md §7.2/§10.1), burada saklanmaz/gösterilmez. Yalnız URL + event aboneliği + teslimat durumu.
export interface Webhook {
  id: string;
  url: string; // HTTPS endpoint (tenant'ın KENDİ sistemi — izinli)
  events: string[]; // abone olunan event tipleri (§10.2 — izinli)
  status: WebhookStatus; // active | disabled | failing
  lastDeliveryAt: string | null; // ISO-8601 son teslimat denemesi; null => hiç
  lastDeliveryOk: boolean | null; // son teslimat sonucu; null => hiç
}

export interface IntegrationSnapshot {
  generatedAt: string; // ISO-8601 (sabit yer tutucu — SSR-stabil, Date.now YOK)
  tenantRef: string; // tenant'ın KENDİ kimliği (L1'de izinli)
  tenantName: string; // tenant org adı (izinli; son-müşteri verisi DEĞİL)
  integrations: Integration[];
  tools: ToolDef[];
  apiKeys: ApiKey[];
  webhooks: Webhook[];
}

// ── saf türetme yardımcıları ────────────────────────────────────────────────────

// Durum bazında entegrasyon sayısı.
export function countIntegrationState(integrations: Integration[]): Record<ConnState, number> {
  const out: Record<ConnState, number> = { connected: 0, degraded: 0, disabled: 0, error: 0 };
  for (const i of integrations) out[i.state] += 1;
  return out;
}

// Tür bazında entegrasyon sayısı (crm/erp/ticketing/custom).
export function countIntegrationType(integrations: Integration[]): Record<IntegrationType, number> {
  const out: Record<IntegrationType, number> = { crm: 0, erp: 0, ticketing: 0, custom: 0 };
  for (const i of integrations) out[i.type] += 1;
  return out;
}

// Bir entegrasyona bağlı tool sayısı.
export function toolsForIntegration(tools: ToolDef[], integrationId: string): number {
  return tools.filter((t) => t.integrationRef === integrationId).length;
}

// HİJYEN/BÜTÜNLÜK: tanımlı OLMAYAN bir entegrasyona bağlanmış tool'lar (geçersiz entegrasyon referansı).
// Boş dönmesi envanter tutarlılığını gösterir; dolu liste referans düzeltmesi (UI uyarısı) tetikler.
export function invalidIntegrationRefs(tools: ToolDef[], integrations: Integration[]): string[] {
  const ids = new Set(integrations.map((i) => i.id));
  return tools.filter((t) => t.integrationRef !== null && t.integrationRef.trim() !== "" && !ids.has(t.integrationRef)).map((t) => t.id);
}

// GÜVENLİK: YAZMA yetkili ama müşteri teyidi GEREKTİRMEYEN tool'lar (FR-TOOL-006/007 ihlali riski). id listesi.
export function writeToolsWithoutConfirmation(tools: ToolDef[]): string[] {
  return tools.filter((t) => t.enabled && t.access === "write" && !t.confirmRequired).map((t) => t.id);
}

// BÜTÜNLÜK: JSON schema doğrulaması OLMAYAN tool'lar (FR-TOOL-002 ihlali). id listesi → UI uyarısı.
export function toolsWithoutSchema(tools: ToolDef[]): string[] {
  return tools.filter((t) => t.enabled && !t.schemaValidated).map((t) => t.id);
}

// HTTPS URL doğrulaması (§10: webhook HTTPS zorunlu). Saf; biçim kontrolü.
export function isHttpsUrl(s: string): boolean {
  return /^https:\/\/[^\s]+$/i.test(s.trim());
}

// GÜVENLİK: HTTPS olmayan webhook URL'leri (§10 ihlali — şifresiz teslimat riski). id listesi → UI uyarısı.
export function insecureWebhookUrls(webhooks: Webhook[]): string[] {
  return webhooks.filter((w) => !isHttpsUrl(w.url)).map((w) => w.id);
}

// İŞLETİM: başarısız teslimat durumundaki webhook'lar (§10.1 — kalıcı başarısızlıkta disabled + alarm). id listesi.
export function failingWebhooks(webhooks: Webhook[]): string[] {
  return webhooks.filter((w) => w.status === "failing" || w.lastDeliveryOk === false).map((w) => w.id);
}

// Durum bazında API anahtarı id listeleri.
export function apiKeysByStatus(apiKeys: ApiKey[], status: ApiKeyStatus): string[] {
  return apiKeys.filter((k) => k.status === status).map((k) => k.id);
}

// ── ton (renk) eşlemeleri ─────────────────────────────────────────────────────────

const INTEGRATION_STATE_TONE: Record<ConnState, StatusTone> = {
  connected: "success",
  degraded: "warning",
  disabled: "neutral",
  error: "danger",
};
export function integrationStateTone(s: ConnState): StatusTone {
  return INTEGRATION_STATE_TONE[s];
}

const INTEGRATION_TYPE_TONE: Record<IntegrationType, StatusTone> = {
  crm: "info",
  erp: "info",
  ticketing: "info",
  custom: "neutral",
};
export function integrationTypeTone(t: IntegrationType): StatusTone {
  return INTEGRATION_TYPE_TONE[t];
}

const PROTOCOL_TONE: Record<ToolProtocol, StatusTone> = {
  rest: "info",
  soap: "neutral",
  graphql: "info",
  webhook: "neutral",
};
export function protocolTone(p: ToolProtocol): StatusTone {
  return PROTOCOL_TONE[p];
}

// Yazma daha yüksek risk → warning; okuma → info (FR-TOOL-005).
const ACCESS_TONE: Record<ToolAccess, StatusTone> = {
  read: "info",
  write: "warning",
};
export function toolAccessTone(a: ToolAccess): StatusTone {
  return ACCESS_TONE[a];
}

const API_KEY_STATUS_TONE: Record<ApiKeyStatus, StatusTone> = {
  active: "success",
  revoked: "neutral",
  expired: "danger",
};
export function apiKeyStatusTone(s: ApiKeyStatus): StatusTone {
  return API_KEY_STATUS_TONE[s];
}

const WEBHOOK_STATUS_TONE: Record<WebhookStatus, StatusTone> = {
  active: "success",
  disabled: "neutral",
  failing: "danger",
};
export function webhookStatusTone(s: WebhookStatus): StatusTone {
  return WEBHOOK_STATUS_TONE[s];
}

// ── HİJYEN + GÜVENLİK koruması ─────────────────────────────────────────────────────
// Yapı içinde son-müşteri iş içeriği/PII'yi VEYA entegrasyon/anahtar/webhook SIRRINI çağrıştıran ALAN ADI
// bulunursa hata fırlatır. Bu, T-05'in yalnız tenant'ın KENDİ entegrasyon konfigürasyonunu (sır DEĞİL)
// göstermesini çalışma-anında garanti eder (BRD §17.7 + NFR 10.6).
// NOT: tenantName/tenantRef + integration/tool/key `name` + webhook `url` + key `scopes` tenant'ın KENDİ
// konfigürasyonudur → yasak listede DEĞİL (izinli).
export const FORBIDDEN_PII_KEYS: readonly string[] = [
  "transcript",
  "recording",
  "recordingurl",
  "audio",
  "msisdn",
  "phonenumber",
  "callerid",
  "callernumber",
  "customer",
  "cardpan",
  "cvv",
  "ssn",
  "pii",
];

// GÜVENLİK: API key / webhook / entegrasyon SIRRI alan adı (NFR 10.6 / API.md §7.2: secret yalnız bir kez döner).
export const FORBIDDEN_SECRET_KEYS: readonly string[] = [
  "secret",
  "apikey",
  "apisecret",
  "signingsecret",
  "clientsecret",
  "token",
  "bearertoken",
  "accesstoken",
  "refreshtoken",
  "credential",
  "password",
  "privatekey",
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
        throw new Error(`T-05 HİJYEN ihlali: yasak PII/iş-içeriği alanı "${path}.${k}" (BRD §17.7)`);
      }
      if (FORBIDDEN_SECRET_KEYS.includes(lower)) {
        throw new Error(`T-05 GÜVENLİK ihlali: entegrasyon/anahtar/webhook sırrı alanı "${path}.${k}" panele konmaz (NFR 10.6)`);
      }
      assertNoPii((node as Record<string, unknown>)[k], `${path}.${k}`);
    }
  }
}

// ── veri SEAM (yer tutucu) ───────────────────────────────────────────────────────
// Deterministik yer tutucu: tek-tenant entegrasyon konfigürasyonu (KENDİ CRM/ERP/ticketing bağlantıları +
// tool tanımları + API anahtar metadatası + webhook tanımları — son-müşteri PII/iş-içeriği DEĞİL, SIR DEĞİL).
// Gerçek implementasyon (F2 §14.1) Integration Gateway + Tool Registry + API key/webhook servisinden
// tenant-scope (RLS) beslenir.
const PLACEHOLDER_SNAPSHOT: IntegrationSnapshot = {
  generatedAt: "2026-06-17T09:00:00.000Z",
  tenantRef: "TEN-2048",
  tenantName: "Kuzey Sigorta A.Ş.",
  integrations: [
    { id: "INT-CRM", name: "Kurumsal CRM", type: "crm", authMethod: "oauth2", state: "connected", region: "eu-west", lastSyncAt: "2026-06-17T08:55:00.000Z" },
    { id: "INT-ERP", name: "Finans ERP", type: "erp", authMethod: "mtls", state: "connected", region: "eu-west", lastSyncAt: "2026-06-17T08:40:00.000Z" },
    { id: "INT-TKT", name: "Destek Ticketing", type: "ticketing", authMethod: "api_key", state: "degraded", region: "eu-central", lastSyncAt: "2026-06-17T06:10:00.000Z" },
  ],
  tools: [
    { id: "TL-01", name: "Müşteri Sorgula", protocol: "rest", access: "read", schemaValidated: true, confirmRequired: false, integrationRef: "INT-CRM", enabled: true },
    { id: "TL-02", name: "Poliçe Oluştur", protocol: "rest", access: "write", schemaValidated: true, confirmRequired: true, integrationRef: "INT-ERP", enabled: true },
    { id: "TL-03", name: "Ticket Aç", protocol: "graphql", access: "write", schemaValidated: true, confirmRequired: true, integrationRef: "INT-TKT", enabled: true },
    { id: "TL-04", name: "Bakiye Sorgula", protocol: "soap", access: "read", schemaValidated: true, confirmRequired: false, integrationRef: "INT-ERP", enabled: true },
  ],
  apiKeys: [
    { id: "KEY-01", name: "Üretim Entegrasyonu", scopes: ["calls:read", "agents:read"], status: "active", createdAt: "2026-05-01T10:00:00.000Z", lastUsedAt: "2026-06-17T08:50:00.000Z" },
    { id: "KEY-02", name: "Webhook Tüketici", scopes: ["webhooks:read"], status: "active", createdAt: "2026-04-12T10:00:00.000Z", lastUsedAt: "2026-06-16T22:00:00.000Z" },
    { id: "KEY-03", name: "Eski Sandbox", scopes: ["calls:read"], status: "revoked", createdAt: "2026-01-10T10:00:00.000Z", lastUsedAt: "2026-02-01T09:00:00.000Z" },
  ],
  webhooks: [
    { id: "WH-01", url: "https://erp.kuzey.example/hooks/calls", events: ["call.completed", "call.failed"], status: "active", lastDeliveryAt: "2026-06-17T08:58:00.000Z", lastDeliveryOk: true },
    { id: "WH-02", url: "https://crm.kuzey.example/webhook", events: ["transcript.ready"], status: "active", lastDeliveryAt: "2026-06-17T08:30:00.000Z", lastDeliveryOk: true },
  ],
};

export async function getIntegrations(): Promise<IntegrationSnapshot> {
  const snap = PLACEHOLDER_SNAPSHOT;
  assertNoPii(snap); // HİJYEN + GÜVENLİK: yapısal son-müşteri PII / entegrasyon-anahtar-webhook sırrı yok (BRD §17.7 / NFR 10.6)
  return snap;
}
