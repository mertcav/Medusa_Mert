// WBS 13.4.9 — A-09 "Tool/API Bağlama" veri katmanı (seam) + SAF türetme yardımcıları
// (L2 — Operasyon / Uygulama Paneli).
//
// ÇEKİRDEK İLKELER:
//  - İÇERİK (BRD §17.5 A-09 "Tool/API Bağlama" — "Tanımlı tool'ları agent'a bağlama (kullanım)"): bir
//    tenant'ın AGENT'larına BAĞLI TOOL'larının envanteri. T-05 (L1) entegrasyon/tool/anahtar/webhook'u
//    TANIMLAR (config); A-09 (L2) bu tanımlı tool'ları agent'a BAĞLAR + bağ sağlığını (kullanım) gösterir.
//    Görünüm yalnız TOOL/BAĞ META taşır — protokol (FR-TOOL-001) + erişim seviyesi read/write (FR-TOOL-005)
//    + JSON schema doğrulama bayrağı (FR-TOOL-002) + endpoint allowlist bayrağı (FR-TOOL-012) + müşteri-teyidi
//    bayrağı (FR-TOOL-006) + hassas-işlem bayrağı (FR-TOOL-007) + asenkron bayrağı (FR-TOOL-011) + agent başına
//    YETKİ (grant, FR-TOOL-004) + bağ durumu. Tool ENDPOINT URL'i / JSON schema GÖVDESİ / istek-yanıt PAYLOAD'ı
//    / credential GÖMÜLMEZ — yalnız DURUM/BAYRAK; tool çağırma/bağlama derin aksiyondur (API dilimi + backend).
//  - AGENT BAZINDA YETKİ (FR-TOOL-004): tool yetkileri agent bazında sınırlandırılır. `binding.grant` =
//    bu agent'a verilen erişim seviyesi (read | write). Aynı tool farklı agent'lara farklı grant ile bağlanabilir.
//  - OKUMA/YAZMA AYRI GÜVENLİK (FR-TOOL-005): `tool.accessLevel` = tool'un azami yetenek/güvenlik seviyesi
//    (read | write). INVARIANT: `binding.grant` tool'un accessLevel'ini AŞAMAZ — read-only tool'a write grant
//    verilemez (yetki yükseltme → escalatedBindings dikkat kalemi).
//  - JSON SCHEMA DOĞRULAMA (FR-TOOL-002): tool input/output JSON schema ile doğrulanır → `schemaValidated`
//    bayrağı. Doğrulanmamış tool'un aktif bağı dikkat kalemidir (unvalidatedBindings). Schema GÖVDESİ gömülmez.
//  - MÜŞTERİ TEYİDİ (FR-TOOL-006) + HASSAS İŞLEM (FR-TOOL-007): kritik işlem öncesi müşteri teyidi
//    (`requiresConfirmation`); para/sözleşme/kişisel veri değişikliği hassas-işlemdir (`sensitiveAction`) +
//    ek doğrulama gerektirir. INVARIANT: hassas-işlem tool'u teyit GEREKTİRMELİDİR — sensitiveAction &&
//    !requiresConfirmation bir config açığıdır (unconfirmedSensitiveTools).
//  - ENDPOINT ALLOWLIST (FR-TOOL-012): yalnız onaylı endpoint'e erişilir → `endpointApproved` bayrağı.
//    Onaylanmamış endpoint'li tool'un aktif bağı ENGELLENMELİDİR (unapprovedBindings — danger). URL gömülmez.
//  - ASENKRON WORKFLOW (FR-TOOL-011): uzun süren işlem için asenkron → `async` bayrağı (Should).
//  - TENANT-SCOPE (FR-TEN-002): A-09 yalnız oturum açan tenant'ın KENDİ tool/bağ envanteri. Scope çalışma-
//    anında middleware (13.1.2) + RLS (DB §6.3) ile sabitlenir; UI yalnız görsel kapı.
//  - HİJYEN (BRD §17.7 + §17.6): yalnız TOOL/BAĞ META. Son-müşteri ham içeriği (transkript/ses kaydı/ham
//    numara/müşteri PII/CDR) + tool çağrı PAYLOAD'ı gömülmez. NOT: tool `name`/agent `name` tenant'ın KENDİ
//    yapılandırmasıdır (KURUMSAL ad — son-müşteri PII değil); bindCount/bayraklar yalnız DURUM/SAYIdır.
//  - GÜVENLİK (NFR 10.6): sır/credential + tool ENDPOINT URL'i + JSON schema GÖVDESİ + istek-yanıt PAYLOAD'ı
//    görünüme KONMAZ (token/apiKey/secret/credential/authHeader/endpoint/url/payload/...). Yalnız DURUM/BAYRAK.
//  - VENDOR-NEUTRAL (ADR-002): veri kaynağı bir SEAM'dir; gerçek implementasyon (F1 §14.1) Tool Registry +
//    Integration Gateway (WBS 7.x) tenant-scope (RLS) beslenir. Belirli CRM/ERP/SaaS markası bağlanmaz.
//  - SAF/DETERMİNİSTİK: türetme yardımcıları (allBindings/countByProtocol/escalatedBindings/orphanBindings/
//    unapprovedBindings/...) Date.now/rastgelelik içermez → birim-test edilebilir + Python aynası
//    (screens/a09-tools/a09_tools_probe.py).
//  - İŞ MANTIĞI/AUTHZ YOK (SAD §14.4.1 A8): tool çağırma/bağlama/grant verme kararı YOK; nihai yetki +
//    işlem backend'de (7.x/12.x) + RLS. Panel yalnız çözümlenmiş bağ envanterini gösterir.
//  - RBAC (BRD §17.6 — L2): operations_manager=Düzenle · conversation_designer=Düzenle · qa_analyst=— ·
//    human_agent=— (BRD §17.6 A-09 satırı: her iki birincil rol Düzenle).

// Tool protokolü (FR-TOOL-001 — REST/SOAP/GraphQL/webhook).
export type ToolProtocol = "rest" | "soap" | "graphql" | "webhook";
// Erişim seviyesi (FR-TOOL-005 — okuma/yazma ayrı güvenlik seviyeleri).
export type AccessLevel = "read" | "write";
// Bağ durumu (aktif | devre dışı).
export type BindingStatus = "active" | "disabled";

export type StatusTone = "success" | "warning" | "danger" | "neutral" | "info";

// Bir tool tanımı (T-05'te tanımlı; DB Tool Registry satırı). Yalnız TOOL META — ENDPOINT/SCHEMA/PAYLOAD DEĞİL.
export interface ToolDefinition {
  toolRef: string; // tool gösterim kimliği (Tool Registry)
  name: string; // kurumsal tool adı (tenant config; son-müşteri PII değil)
  protocol: ToolProtocol; // FR-TOOL-001 (REST/SOAP/GraphQL/webhook)
  accessLevel: AccessLevel; // FR-TOOL-005 (read|write — azami yetenek/güvenlik seviyesi)
  schemaValidated: boolean; // FR-TOOL-002 (input/output JSON schema doğrulandı mı — yalnız BAYRAK)
  endpointApproved: boolean; // FR-TOOL-012 (endpoint allowlist'te mi — yalnız BAYRAK; URL gömülmez)
  requiresConfirmation: boolean; // FR-TOOL-006 (kritik işlem öncesi müşteri teyidi)
  sensitiveAction: boolean; // FR-TOOL-007 (para/sözleşme/PII değişikliği → ek doğrulama)
  async: boolean; // FR-TOOL-011 (uzun süren işlem → asenkron workflow)
}

// Bir agent–tool bağı (A-09 çekirdeği — FR-TOOL-004 agent bazında yetki).
export interface AgentToolBinding {
  bindRef: string; // bağ gösterim kimliği
  toolRef: string; // bağlı tool (kataloğa referans)
  grant: AccessLevel; // FR-TOOL-004/005 (bu agent'a verilen erişim seviyesi)
  status: BindingStatus; // aktif | devre dışı
}

// Bir agent ve ona bağlı tool'lar.
export interface AgentBindings {
  agentRef: string; // agent gösterim kimliği
  agentName: string; // agent adı (tenant config; PII değil)
  bindings: AgentToolBinding[]; // agent'a bağlı tool'lar (BAĞ META yalnız)
}

export interface ToolBindingView {
  generatedAt: string; // ISO-8601 (sabit yer tutucu — SSR-stabil, Date.now YOK)
  tenantRef: string; // tenant'ın KENDİ kimliği (L2'de izinli)
  tenantName: string; // tenant org adı (izinli; son-müşteri verisi DEĞİL)
  tools: ToolDefinition[]; // tenant tool kataloğu (T-05'te tanımlı — tenant-scope FR-TEN-002)
  agents: AgentBindings[]; // agent başına bağlamalar (tenant-scope FR-TEN-002)
}

// Bir bağın tool ile çözümlenmiş düz satırı (orphan bağda tool=null).
export type ResolvedBinding = AgentToolBinding & {
  agentRef: string;
  agentName: string;
  tool: ToolDefinition | null; // kataloğa çözümlenen tool (orphan'da null)
};

// Protokollerin görüntüleme sırası (FR-TOOL-001).
export const PROTOCOL_ORDER: ToolProtocol[] = ["rest", "soap", "graphql", "webhook"];
// Erişim seviyelerinin görüntüleme sırası (FR-TOOL-005).
export const ACCESS_ORDER: AccessLevel[] = ["read", "write"];

// ── saf türetme yardımcıları ────────────────────────────────────────────────────

// Tool kataloğunu toolRef'e göre ARTAN sırala (deterministik, kopya döndürür).
export function sortedTools(view: ToolBindingView): ToolDefinition[] {
  return [...view.tools].sort((a, b) => a.toolRef.localeCompare(b.toolRef));
}

// Agent'ları agentRef'e göre ARTAN sırala (deterministik, kopya döndürür).
export function sortedAgents(view: ToolBindingView): AgentBindings[] {
  return [...view.agents].sort((a, b) => a.agentRef.localeCompare(b.agentRef));
}

// toolRef → ToolDefinition haritası (çözümleme için).
export function toolIndex(view: ToolBindingView): Map<string, ToolDefinition> {
  return new Map(view.tools.map((t) => [t.toolRef, t]));
}

// Tüm bağları (tüm agent'lar) düzleştir + tool'a çözümle; (agentRef, bindRef) ile deterministik sırala.
export function allBindings(view: ToolBindingView): ResolvedBinding[] {
  const idx = toolIndex(view);
  const rows: ResolvedBinding[] = [];
  for (const a of view.agents) {
    for (const b of a.bindings) {
      rows.push({ ...b, agentRef: a.agentRef, agentName: a.agentName, tool: idx.get(b.toolRef) ?? null });
    }
  }
  return rows.sort((x, y) => x.agentRef.localeCompare(y.agentRef) || x.bindRef.localeCompare(y.bindRef));
}

// Protokol başına tool sayısı (tüm protokoller 0'dan başlatılır — FR-TOOL-001).
export function countByProtocol(tools: ToolDefinition[]): Record<ToolProtocol, number> {
  const acc = {} as Record<ToolProtocol, number>;
  for (const p of PROTOCOL_ORDER) acc[p] = 0;
  for (const t of tools) acc[t.protocol] += 1;
  return acc;
}

// Erişim seviyesi başına tool sayısı (read | write — FR-TOOL-005).
export function countByAccessLevel(tools: ToolDefinition[]): Record<AccessLevel, number> {
  const acc = {} as Record<AccessLevel, number>;
  for (const a of ACCESS_ORDER) acc[a] = 0;
  for (const t of tools) acc[t.accessLevel] += 1;
  return acc;
}

// Okuma-seviyesi tool'lar (FR-TOOL-005).
export function readTools(tools: ToolDefinition[]): ToolDefinition[] {
  return tools.filter((t) => t.accessLevel === "read");
}

// Yazma-seviyesi tool'lar (FR-TOOL-005 — daha yüksek güvenlik).
export function writeTools(tools: ToolDefinition[]): ToolDefinition[] {
  return tools.filter((t) => t.accessLevel === "write");
}

// JSON schema doğrulanmamış tool'lar (FR-TOOL-002 — input/output şema yok).
export function unvalidatedTools(tools: ToolDefinition[]): ToolDefinition[] {
  return tools.filter((t) => !t.schemaValidated);
}

// Endpoint allowlist'te OLMAYAN tool'lar (FR-TOOL-012 — onaylanmamış endpoint).
export function unapprovedTools(tools: ToolDefinition[]): ToolDefinition[] {
  return tools.filter((t) => !t.endpointApproved);
}

// Müşteri teyidi gerektiren tool'lar (FR-TOOL-006).
export function confirmationTools(tools: ToolDefinition[]): ToolDefinition[] {
  return tools.filter((t) => t.requiresConfirmation);
}

// Hassas-işlem tool'ları (FR-TOOL-007 — para/sözleşme/PII).
export function sensitiveTools(tools: ToolDefinition[]): ToolDefinition[] {
  return tools.filter((t) => t.sensitiveAction);
}

// Asenkron workflow tool'ları (FR-TOOL-011).
export function asyncTools(tools: ToolDefinition[]): ToolDefinition[] {
  return tools.filter((t) => t.async);
}

// CONFIG AÇIĞI: hassas-işlem ama müşteri teyidi YOK (FR-TOOL-006/007 ihlali). sensitiveAction && !requiresConfirmation.
export function unconfirmedSensitiveTools(tools: ToolDefinition[]): ToolDefinition[] {
  return tools.filter((t) => t.sensitiveAction && !t.requiresConfirmation);
}

// Bir tool'a kaç bağ işaret ediyor (kataloğa çözümlenen; orphan dahil sayılmaz).
export function bindingCountForTool(view: ToolBindingView, toolRef: string): number {
  return allBindings(view).filter((b) => b.toolRef === toolRef).length;
}

// Aktif bağlar (status === "active").
export function activeBindings(view: ToolBindingView): ResolvedBinding[] {
  return allBindings(view).filter((b) => b.status === "active");
}

// Devre dışı bağlar (status === "disabled").
export function disabledBindings(view: ToolBindingView): ResolvedBinding[] {
  return allBindings(view).filter((b) => b.status === "disabled");
}

// Yazma yetkisi (grant === "write") verilmiş bağlar (FR-TOOL-004/005).
export function writeGrantBindings(view: ToolBindingView): ResolvedBinding[] {
  return allBindings(view).filter((b) => b.grant === "write");
}

// YETKİ YÜKSELTME (FR-TOOL-005 ihlali): grant=write ama tool accessLevel=read. read-only tool'a write verilemez.
export function escalatedBindings(view: ToolBindingView): ResolvedBinding[] {
  return allBindings(view).filter((b) => b.tool !== null && b.grant === "write" && b.tool.accessLevel === "read");
}

// ORPHAN bağ (bütünlük ihlali): tool kataloğda yok (toolRef çözümlenmiyor).
export function orphanBindings(view: ToolBindingView): ResolvedBinding[] {
  return allBindings(view).filter((b) => b.tool === null);
}

// ONAYLANMAMIŞ ENDPOINT (FR-TOOL-012 — danger): AKTİF bağ + tool endpointApproved=false. Erişim engellenmeli.
export function unapprovedBindings(view: ToolBindingView): ResolvedBinding[] {
  return allBindings(view).filter((b) => b.status === "active" && b.tool !== null && !b.tool.endpointApproved);
}

// ŞEMA DOĞRULANMAMIŞ (FR-TOOL-002 — warning): AKTİF bağ + tool schemaValidated=false.
export function unvalidatedBindings(view: ToolBindingView): ResolvedBinding[] {
  return allBindings(view).filter((b) => b.status === "active" && b.tool !== null && !b.tool.schemaValidated);
}

// HASSAS YAZMA bağı (FR-TOOL-007 — info): AKTİF write bağ + tool sensitiveAction=true (ek doğrulama gerekir).
export function sensitiveWriteBindings(view: ToolBindingView): ResolvedBinding[] {
  return allBindings(view).filter((b) => b.status === "active" && b.grant === "write" && b.tool !== null && b.tool.sensitiveAction);
}

// Açık dikkat sayısı: onaylanmamış endpoint bağı + şema-doğrulanmamış bağ + yetki-yükseltme bağı +
// orphan bağ + teyitsiz hassas tool (config açığı).
export function openAttentionCount(view: ToolBindingView): number {
  return (
    unapprovedBindings(view).length +
    unvalidatedBindings(view).length +
    escalatedBindings(view).length +
    orphanBindings(view).length +
    unconfirmedSensitiveTools(view.tools).length
  );
}

// ── ton (renk) eşlemeleri ─────────────────────────────────────────────────────────

const PROTOCOL_TONE: Record<ToolProtocol, StatusTone> = {
  rest: "neutral",
  soap: "neutral",
  graphql: "neutral",
  webhook: "info",
};
export function protocolTone(p: ToolProtocol): StatusTone {
  return PROTOCOL_TONE[p];
}

const ACCESS_TONE: Record<AccessLevel, StatusTone> = {
  read: "neutral",
  write: "warning", // yazma daha yüksek güvenlik (FR-TOOL-005)
};
export function accessTone(a: AccessLevel): StatusTone {
  return ACCESS_TONE[a];
}

const STATUS_TONE: Record<BindingStatus, StatusTone> = {
  active: "success",
  disabled: "neutral",
};
export function statusTone(s: BindingStatus): StatusTone {
  return STATUS_TONE[s];
}

// Bayrak tonu: olumlu durum (true) → success; eksik (false) → warning/danger çağıran karar verir.
export function boolTone(ok: boolean): StatusTone {
  return ok ? "success" : "danger";
}

// ── HİJYEN + GÜVENLİK koruması ─────────────────────────────────────────────────────
// Yapı içinde son-müşteri ham iş içeriği/PII'yi VEYA sır/credential/tool ENDPOINT/SCHEMA/PAYLOAD çağrıştıran
// ALAN ADI bulunursa hata fırlatır. Bu, A-09'un yalnız TOOL/BAĞ META veriyi (protokol/erişim seviyesi/schema
// doğrulama bayrağı/endpoint allowlist bayrağı/teyit bayrağı/hassas bayrağı/async bayrağı/grant/durum + tool/
// agent adı — tenant'ın KENDİ yapılandırması) — ham transkript/ses kaydı/ham numara/müşteri PII/CDR + tool
// ENDPOINT URL'i/JSON schema GÖVDESİ/istek-yanıt PAYLOAD'ı/credential DEĞİL — göstermesini garanti eder
// (BRD §17.7 + §17.6 + NFR 10.6).
export const FORBIDDEN_PII_KEYS: readonly string[] = [
  "transcript",
  "recording",
  "recordingurl",
  "audio",
  "msisdn",
  "phonenumber",
  "callerid",
  "callernumber",
  "calleenumber",
  "customer",
  "customername",
  "cdr",
  "cardpan",
  "cvv",
  "ssn",
  "pii",
];

export const FORBIDDEN_SECRET_KEYS: readonly string[] = [
  "secret",
  "apikey",
  "apisecret",
  "clientsecret",
  "webhooksecret",
  "signingsecret",
  "token",
  "bearertoken",
  "accesstoken",
  "refreshtoken",
  "credential",
  "password",
  "privatekey",
  "kmskey",
  "authheader", // Authorization header — sır
  "endpoint", // tool endpoint URL — gömülmez (yalnız endpointApproved BAYRAĞI; FR-TOOL-012)
  "endpointurl",
  "url",
  "baseurl",
  "webhookurl",
  "uri",
  "payload", // tool çağrı istek/yanıt gövdesi — gömülmez
  "requestbody",
  "responsebody",
  "schemabody", // JSON schema GÖVDESİ — gömülmez (yalnız schemaValidated BAYRAĞI; FR-TOOL-002)
  "jsonschema",
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
        throw new Error(`A-09 HİJYEN ihlali: yasak PII/iş-içeriği alanı "${path}.${k}" (BRD §17.7)`);
      }
      if (FORBIDDEN_SECRET_KEYS.includes(lower)) {
        throw new Error(`A-09 GÜVENLİK ihlali: sır/credential/endpoint/schema/payload alanı "${path}.${k}" panele konmaz (NFR 10.6)`);
      }
      assertNoPii((node as Record<string, unknown>)[k], `${path}.${k}`);
    }
  }
}

// ── veri SEAM (yer tutucu) ───────────────────────────────────────────────────────
// Deterministik yer tutucu: tek-tenant tool/bağ envanteri (TOOL/BAĞ META yalnız — ham içerik/PII/sır/endpoint/
// schema/payload DEĞİL). Gerçek implementasyon (F1 §14.1) Tool Registry + Integration Gateway (WBS 7.x) tenant-
// scope (RLS) beslenir. Bu örnek: 6 tool (read/write karışık; biri şema-doğrulanmamış; biri endpoint-onaysız;
// biri teyitsiz-hassas) + 3 agent (biri yetki-yükseltme + biri orphan bağ taşır) → birkaç dikkat kalemi.
const PLACEHOLDER_VIEW: ToolBindingView = {
  generatedAt: "2026-06-18T09:00:00.000Z",
  tenantRef: "TEN-2048",
  tenantName: "Kuzey Sigorta A.Ş.",
  tools: [
    { toolRef: "TOOL-01", name: "Poliçe Sorgulama", protocol: "rest", accessLevel: "read", schemaValidated: true, endpointApproved: true, requiresConfirmation: false, sensitiveAction: false, async: false },
    { toolRef: "TOOL-02", name: "Ödeme Tahsilat", protocol: "rest", accessLevel: "write", schemaValidated: true, endpointApproved: true, requiresConfirmation: true, sensitiveAction: true, async: false },
    { toolRef: "TOOL-03", name: "Talep Oluşturma", protocol: "soap", accessLevel: "write", schemaValidated: true, endpointApproved: true, requiresConfirmation: true, sensitiveAction: false, async: false },
    { toolRef: "TOOL-04", name: "Stok Sorgu (GraphQL)", protocol: "graphql", accessLevel: "read", schemaValidated: false, endpointApproved: true, requiresConfirmation: false, sensitiveAction: false, async: false },
    { toolRef: "TOOL-05", name: "Belge Üretim Webhook", protocol: "webhook", accessLevel: "write", schemaValidated: true, endpointApproved: false, requiresConfirmation: true, sensitiveAction: false, async: true },
    { toolRef: "TOOL-06", name: "Sözleşme Güncelle", protocol: "rest", accessLevel: "write", schemaValidated: true, endpointApproved: true, requiresConfirmation: false, sensitiveAction: true, async: false },
  ],
  agents: [
    {
      agentRef: "AGT-117",
      agentName: "Sigorta Asistanı",
      bindings: [
        { bindRef: "BND-01", toolRef: "TOOL-01", grant: "read", status: "active" },
        { bindRef: "BND-02", toolRef: "TOOL-02", grant: "write", status: "active" },
        { bindRef: "BND-03", toolRef: "TOOL-04", grant: "read", status: "active" }, // şema-doğrulanmamış → warning
      ],
    },
    {
      agentRef: "AGT-204",
      agentName: "Tahsilat Botu",
      bindings: [
        { bindRef: "BND-04", toolRef: "TOOL-02", grant: "write", status: "active" },
        { bindRef: "BND-05", toolRef: "TOOL-05", grant: "write", status: "active" }, // endpoint-onaysız → danger
        { bindRef: "BND-06", toolRef: "TOOL-01", grant: "write", status: "active" }, // yetki-yükseltme (tool read) → danger
      ],
    },
    {
      agentRef: "AGT-309",
      agentName: "Bilgi Botu",
      bindings: [
        { bindRef: "BND-07", toolRef: "TOOL-99", grant: "read", status: "active" }, // orphan (katalogda yok) → danger
      ],
    },
  ],
};

export async function getToolBindingView(): Promise<ToolBindingView> {
  const view = PLACEHOLDER_VIEW;
  assertNoPii(view); // HİJYEN + GÜVENLİK: yapısal son-müşteri PII / sır / endpoint / schema / payload yok (BRD §17.7 / NFR 10.6)
  return view;
}
