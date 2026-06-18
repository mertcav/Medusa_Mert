// WBS 13.4.3 — A-03 "Agent Listesi" (Agent List) veri katmanı (seam) + SAF türetme yardımcıları
// (L2 — Operasyon / Uygulama Paneli).
//
// ÇEKİRDEK İLKELER:
//  - İÇERİK (BRD §17.5 A-03 "Tüm agent'lar ve durumları"): tenant'ın TANIMLI Voice AI agent'larının
//    YÖNETİM/ENVANTER görünümü. Her agent: ad/amaç (FR-AGT-002 tenant config), YAŞAM DÖNGÜSÜ DURUMU
//    (draft/test/staging/production/archived — FR-AGT-005), konuşma modeli (single_prompt/node_flow —
//    FR-AGT-003), diller (FR-AGT-002), aktif/yayınlı sürüm + en son sürüm (FR-AGT-004/006 versiyonlama),
//    otomatik test kapısı sonucu (FR-AGT-010), bağlı numara/kampanya sayısı (FR-AGT-007), varyant işareti
//    (FR-AGT-008) ve org birimi (departman/marka scope).
//  - DURUMLAR (FR-AGT-005): yaşam döngüsü = agent'ın "durumu". DB §5.2 `agent.lifecycle_state` CHECK ile
//    birebir (draft→test→staging→production→archived). Bu A-03 KONFİGÜRASYON/ENVANTER ekranıdır — A-02 gibi
//    GERÇEK ZAMANLI DEĞİL (FR-ANA-012 kapsamı dışı); tazelik bütçesi yoktur.
//  - TENANT-SCOPE (FR-TEN-002): A-03 YALNIZ oturum açan tenant'ın KENDİ agent'larını gösterir. Scope
//    çalışma-anında middleware (13.1.2) + RLS (DB §6.3) ile sabitlenir; UI yalnız görsel kapı (SAD §14.4.1 A8).
//  - HİJYEN (BRD §17.7 + §17.6): agent ENVANTERİ yalnız KONFİGÜRASYON META'sıdır (ad/amaç/durum/sürüm —
//    tenant'ın KENDİ yapılandırması, izinli). Son-müşteri ham içeriği (transkript/ses kaydı/ham numara/
//    müşteri PII/CDR) gömülmez; prompt gövdesi/tool kimlik bilgisi DERİN aksiyon → A-06/A-09 (görsel kapı).
//  - GÜVENLİK (NFR 10.6): sır/credential görünüme KONMAZ (token/apiKey/webhookSecret/privateKey/kmsKey).
//  - VENDOR-NEUTRAL (ADR-002): veri kaynağı bir SEAM'dir; gerçek implementasyon (F1 §14.1) Agent Registry
//    (DB §5.2 `agent` + `agent_version`) + test orkestrasyonundan (FR-AGT-010) tenant-scope (RLS) beslenir.
//    Belirli LLM/STT/TTS sağlayıcısı bağlanmaz.
//  - SAF/DETERMİNİSTİK: türetme yardımcıları (countByLifecycle/pendingChangesAgents/testBlockedAgents/
//    unboundProductionAgents/attentionAgents/...) Date.now/rastgelelik içermez → birim-test edilebilir +
//    Python aynası (screens/a03-agents/a03_agents_probe.py).
//  - İŞ MANTIĞI/AUTHZ YOK (SAD §14.4.1 A8): oluştur/düzenle/yayınla/rollback aksiyonları görsel kapıdır;
//    nihai yetki + işlem backend'de (12.x). Panel yalnız çözümlenmiş envanteri gösterir + sorunu işaretler.

// Yaşam döngüsü durumu (FR-AGT-005 / DB §5.2 agent.lifecycle_state CHECK ile birebir).
export type AgentLifecycle = "draft" | "test" | "staging" | "production" | "archived";
// Konuşma modeli (FR-AGT-003 / DB §5.2 conversation_flow.mode).
export type FlowMode = "single_prompt" | "node_flow";
// Otomatik test kapısı sonucu (FR-AGT-010 — canlıya almadan önce testten geçmeli).
export type TestStatus = "passed" | "failed" | "not_run";

export type StatusTone = "success" | "warning" | "danger" | "neutral" | "info";

// Tek agent envanter kaydı. Yalnız KONFİGÜRASYON META — son-müşteri içeriği DEĞİL.
// name/purpose tenant'ın KENDİ yapılandırmasıdır (L2'de izinli); ham müşteri PII değildir.
export interface AgentSummary {
  id: string; // agent kayıt id (UUID) — REFERANS
  agentRef: string; // gösterim referansı (ör. "AGT-77")
  name: string; // agent adı (tenant config — FR-AGT-002; son-müşteri PII değil)
  purpose: string; // kısa amaç etiketi (tenant config — FR-AGT-002)
  lifecycle: AgentLifecycle; // yaşam döngüsü "durumu" (FR-AGT-005)
  mode: FlowMode; // konuşma modeli (FR-AGT-003)
  languages: string[]; // desteklenen diller (FR-AGT-002; ISO kısa kod, ör. "tr"/"en")
  orgUnit: string | null; // departman/marka scope (organisation_unit) | yok
  activeVersionNo: number | null; // YAYINLI (production) sürüm no (FR-AGT-006) | hiç yayınlanmadı
  latestVersionNo: number; // en son (taslak dahil) sürüm no (FR-AGT-004)
  publishedAt: string | null; // aktif sürüm yayın zamanı (ISO-8601) | yok
  updatedAt: string; // son konfigürasyon değişikliği (ISO-8601)
  boundNumbers: number; // bağlı numara sayısı (FR-AGT-007)
  boundCampaigns: number; // bağlı kampanya sayısı (FR-AGT-007)
  testStatus: TestStatus; // son otomatik test kapısı sonucu (FR-AGT-010)
  isVariant: boolean; // segment varyantı mı (FR-AGT-008)
  baseAgentRef: string | null; // varyant ise temel agent referansı | yok
}

export interface AgentListView {
  generatedAt: string; // ISO-8601 (sabit yer tutucu — SSR-stabil, Date.now YOK)
  tenantRef: string; // tenant'ın KENDİ kimliği (L2'de izinli)
  tenantName: string; // tenant org adı (izinli; son-müşteri verisi DEĞİL)
  agents: AgentSummary[]; // tenant'ın agent envanteri (tenant-scope FR-TEN-002)
}

// Yaşam döngüsü görüntüleme sırası (envanter/dağılım).
export const LIFECYCLE_ORDER: AgentLifecycle[] = ["draft", "test", "staging", "production", "archived"];
// "Geliştirmede" sayılan durumlar (production/archived dışı).
export const IN_DEVELOPMENT: AgentLifecycle[] = ["draft", "test", "staging"];

// ── saf türetme yardımcıları ────────────────────────────────────────────────────

// Belirli yaşam döngüsündeki agent'lar.
export function agentsInLifecycle(agents: AgentSummary[], state: AgentLifecycle): AgentSummary[] {
  return agents.filter((a) => a.lifecycle === state);
}

// Yaşam döngüsü dağılımı (KPI/breakdown).
export function countByLifecycle(agents: AgentSummary[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const a of agents) out[a.lifecycle] = (out[a.lifecycle] ?? 0) + 1;
  return out;
}

// Konuşma modeli dağılımı (FR-AGT-003).
export function countByMode(agents: AgentSummary[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const a of agents) out[a.mode] = (out[a.mode] ?? 0) + 1;
  return out;
}

// Production (canlı) agent'lar.
export function productionAgents(agents: AgentSummary[]): AgentSummary[] {
  return agents.filter((a) => a.lifecycle === "production");
}

// Geliştirmede (draft/test/staging) agent'lar.
export function inDevelopmentAgents(agents: AgentSummary[]): AgentSummary[] {
  return agents.filter((a) => IN_DEVELOPMENT.includes(a.lifecycle));
}

// YAYINLANMAMIŞ DEĞİŞİKLİK var mı (FR-AGT-004/006): en son sürüm > yayınlı sürüm => drift.
export function hasPendingChanges(a: AgentSummary): boolean {
  return a.latestVersionNo > (a.activeVersionNo ?? 0);
}
export function pendingChangesAgents(agents: AgentSummary[]): AgentSummary[] {
  return agents.filter(hasPendingChanges);
}

// TEST KAPISI BLOKLU (FR-AGT-010): staging/production agent'ın otomatik testleri geçmiş DEĞİL.
// Canlıya/yayına alınmadan önce testten geçmesi gerekir → geçmeyen yayın durumu bir SORUNDUR.
export function testBlocked(a: AgentSummary): boolean {
  return (a.lifecycle === "staging" || a.lifecycle === "production") && a.testStatus !== "passed";
}
export function testBlockedAgents(agents: AgentSummary[]): AgentSummary[] {
  return agents.filter(testBlocked);
}

// BAĞLANTISIZ PRODUCTION (FR-AGT-007): canlı agent'ın bağlı numarası VE kampanyası yok => erişilemez (misconfig).
export function unboundProduction(a: AgentSummary): boolean {
  return a.lifecycle === "production" && a.boundNumbers === 0 && a.boundCampaigns === 0;
}
export function unboundProductionAgents(agents: AgentSummary[]): AgentSummary[] {
  return agents.filter(unboundProduction);
}

// AKTİF SÜRÜMSÜZ PRODUCTION (FR-AGT-006): production ama yayınlı sürümü yok => tutarsız/misconfig.
export function missingActiveVersion(a: AgentSummary): boolean {
  return a.lifecycle === "production" && a.activeVersionNo === null;
}
export function missingActiveVersionAgents(agents: AgentSummary[]): AgentSummary[] {
  return agents.filter(missingActiveVersion);
}

// Segment varyantları (FR-AGT-008).
export function variantAgents(agents: AgentSummary[]): AgentSummary[] {
  return agents.filter((a) => a.isVariant);
}

// Envanterdeki ayrık dil kümesi (sıralı — diller FR-AGT-002).
export function distinctLanguages(agents: AgentSummary[]): string[] {
  const set = new Set<string>();
  for (const a of agents) for (const l of a.languages) set.add(l);
  return Array.from(set).sort();
}

// DİKKAT GEREKTİREN agent'lar (BLOKLAYAN sorunlar — sıra korunur, tekilleştirilir):
//   test bloklu (FR-AGT-010) ∪ bağlantısız production (FR-AGT-007) ∪ aktif sürümsüz production (FR-AGT-006).
export function attentionAgents(agents: AgentSummary[]): AgentSummary[] {
  return agents.filter((a) => testBlocked(a) || unboundProduction(a) || missingActiveVersion(a));
}

// Toplam açık dikkat sayısı (KPI): dikkat gerektiren AYRIK agent sayısı.
export function openAttentionCount(view: AgentListView): number {
  return attentionAgents(view.agents).length;
}

// ── ton (renk) eşlemeleri ─────────────────────────────────────────────────────────

const LIFECYCLE_TONE: Record<AgentLifecycle, StatusTone> = {
  draft: "neutral",
  test: "info",
  staging: "warning",
  production: "success",
  archived: "neutral",
};
export function lifecycleTone(s: AgentLifecycle): StatusTone {
  return LIFECYCLE_TONE[s];
}

const MODE_TONE: Record<FlowMode, StatusTone> = {
  single_prompt: "neutral",
  node_flow: "info",
};
export function modeTone(m: FlowMode): StatusTone {
  return MODE_TONE[m];
}

const TEST_TONE: Record<TestStatus, StatusTone> = {
  passed: "success",
  failed: "danger",
  not_run: "warning",
};
export function testTone(s: TestStatus): StatusTone {
  return TEST_TONE[s];
}

// Yayınlanmamış değişiklik tonu: var => warning · yok => neutral.
export function pendingTone(b: boolean): StatusTone {
  return b ? "warning" : "neutral";
}

// Varyant tonu: varyant => info · temel => neutral.
export function variantTone(b: boolean): StatusTone {
  return b ? "info" : "neutral";
}

// ── HİJYEN + GÜVENLİK koruması ─────────────────────────────────────────────────────
// Yapı içinde son-müşteri ham iş içeriği/PII'yi VEYA sır/credential çağrıştıran ALAN ADI bulunursa hata
// fırlatır. Bu, A-03'ün yalnız KONFİGÜRASYON META veriyi (agent ad/amaç/durum/sürüm — tenant'ın KENDİ
// yapılandırması) — ham transkript/ses kaydı/ham numara/müşteri PII/CDR + prompt gövdesi/tool sırrı DEĞİL —
// göstermesini çalışma-anında garanti eder (BRD §17.7 + §17.6 + NFR 10.6). NOT: name/purpose/tenantName
// tenant'ın KENDİ yapılandırmasıdır (L2'de izinli).
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
  "token",
  "bearertoken",
  "accesstoken",
  "refreshtoken",
  "credential",
  "password",
  "privatekey",
  "kmskey",
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
        throw new Error(`A-03 HİJYEN ihlali: yasak PII/iş-içeriği alanı "${path}.${k}" (BRD §17.7)`);
      }
      if (FORBIDDEN_SECRET_KEYS.includes(lower)) {
        throw new Error(`A-03 GÜVENLİK ihlali: sır/credential alanı "${path}.${k}" panele konmaz (NFR 10.6)`);
      }
      assertNoPii((node as Record<string, unknown>)[k], `${path}.${k}`);
    }
  }
}

// ── veri SEAM (yer tutucu) ───────────────────────────────────────────────────────
// Deterministik yer tutucu: tek-tenant agent envanteri (KONFİGÜRASYON META yalnız — ham içerik/PII/sır
// DEĞİL). Gerçek implementasyon (F1 §14.1) Agent Registry (DB §5.2 `agent` + `agent_version`) + test
// orkestrasyonundan (FR-AGT-010) tenant-scope (RLS) beslenir.
const PLACEHOLDER_VIEW: AgentListView = {
  generatedAt: "2026-06-18T09:00:00.000Z",
  tenantRef: "TEN-2048",
  tenantName: "Kuzey Sigorta A.Ş.",
  agents: [
    {
      id: "AG-7001",
      agentRef: "AGT-77",
      name: "Hasar Karşılama",
      purpose: "Inbound hasar ilk kayıt ve yönlendirme",
      lifecycle: "production",
      mode: "node_flow",
      languages: ["tr", "en"],
      orgUnit: "Hasar Operasyon",
      activeVersionNo: 12,
      latestVersionNo: 13,
      publishedAt: "2026-06-10T07:30:00.000Z",
      updatedAt: "2026-06-17T14:05:00.000Z",
      boundNumbers: 3,
      boundCampaigns: 0,
      testStatus: "passed",
      isVariant: false,
      baseAgentRef: null,
    },
    {
      id: "AG-7002",
      agentRef: "AGT-90",
      name: "Tahsilat Hatırlatma",
      purpose: "Outbound ödeme hatırlatma ve consent",
      lifecycle: "production",
      mode: "single_prompt",
      languages: ["tr"],
      orgUnit: "Tahsilat",
      activeVersionNo: 5,
      latestVersionNo: 5,
      publishedAt: "2026-06-12T09:00:00.000Z",
      updatedAt: "2026-06-12T09:00:00.000Z",
      boundNumbers: 1,
      boundCampaigns: 2,
      testStatus: "failed",
      isVariant: false,
      baseAgentRef: null,
    },
    {
      id: "AG-7003",
      agentRef: "AGT-104",
      name: "Hasar Karşılama — Kurumsal",
      purpose: "Kurumsal segment hasar karşılama varyantı",
      lifecycle: "staging",
      mode: "node_flow",
      languages: ["tr", "en"],
      orgUnit: "Hasar Operasyon",
      activeVersionNo: 2,
      latestVersionNo: 4,
      publishedAt: "2026-06-09T11:00:00.000Z",
      updatedAt: "2026-06-16T16:40:00.000Z",
      boundNumbers: 0,
      boundCampaigns: 0,
      testStatus: "passed",
      isVariant: true,
      baseAgentRef: "AGT-77",
    },
    {
      id: "AG-7004",
      agentRef: "AGT-118",
      name: "Randevu Asistanı",
      purpose: "Inbound randevu oluşturma ve teyit",
      lifecycle: "test",
      mode: "single_prompt",
      languages: ["tr"],
      orgUnit: "Müşteri Hizmetleri",
      activeVersionNo: null,
      latestVersionNo: 3,
      publishedAt: null,
      updatedAt: "2026-06-18T08:10:00.000Z",
      boundNumbers: 0,
      boundCampaigns: 0,
      testStatus: "not_run",
      isVariant: false,
      baseAgentRef: null,
    },
    {
      id: "AG-7005",
      agentRef: "AGT-131",
      name: "Teknik Destek L1",
      purpose: "Inbound seviye-1 sorun giderme",
      lifecycle: "draft",
      mode: "node_flow",
      languages: ["tr", "en"],
      orgUnit: "Destek",
      activeVersionNo: null,
      latestVersionNo: 1,
      publishedAt: null,
      updatedAt: "2026-06-15T10:25:00.000Z",
      boundNumbers: 0,
      boundCampaigns: 0,
      testStatus: "not_run",
      isVariant: false,
      baseAgentRef: null,
    },
    {
      id: "AG-7006",
      agentRef: "AGT-140",
      name: "Anket Geri Arama",
      purpose: "Outbound memnuniyet anketi (emekli)",
      lifecycle: "archived",
      mode: "single_prompt",
      languages: ["tr"],
      orgUnit: "Pazarlama",
      activeVersionNo: 8,
      latestVersionNo: 8,
      publishedAt: "2026-03-01T08:00:00.000Z",
      updatedAt: "2026-05-20T12:00:00.000Z",
      boundNumbers: 0,
      boundCampaigns: 0,
      testStatus: "passed",
      isVariant: false,
      baseAgentRef: null,
    },
  ],
};

export async function getAgentList(): Promise<AgentListView> {
  const view = PLACEHOLDER_VIEW;
  assertNoPii(view); // HİJYEN + GÜVENLİK: yapısal son-müşteri PII / sır yok (BRD §17.7 / NFR 10.6)
  return view;
}
