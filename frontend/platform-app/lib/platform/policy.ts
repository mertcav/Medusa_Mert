// WBS 13.2.6 — P-06 "Global Politika & Guardrails" veri katmanı (seam) + SAF türetme yardımcıları.
//
// ÇEKİRDEK İLKELER (P-01..P-05 ile aynı disiplin; lib/platform/overview.ts + tenants.ts + resources.ts +
// providers.ts + billing.ts):
//  - ALTIN KURAL (BRD §17.7 / FR-IAM-008): L0 platform konsolu YALNIZ platform-geneli politika/guardrail/
//    model-allowlist + varsayılan compliance-profile metadatası gösterir; tenant İŞ İÇERİĞİ (çağrı kaydı,
//    transkript, son-müşteri/PII) GÖSTERİLMEZ. Tipler YAPISAL OLARAK iş-içeriği/PII taşımaz; `assertNoPii`
//    çalışma-anında doğrular. Profilin uygulandığı tenant SAYISI (toplulaştırılmış) izinlidir; tenant
//    kimliği/listesi/iş içeriği bu ekranda yer almaz.
//  - VENDOR-NEUTRAL (ADR-002): model allowlist girişleri ve guardrail/profile etiketleri SOMUT sağlayıcı/
//    marka bağlamaz (model id'leri nötr: "llm-large-a" gibi). Veri kaynağı bir SEAM'dir. Gerçek
//    implementasyon (F2 §14.1) Policy Engine (SAD §6.2/§9.3 input/output guard) + Model Router allowlist
//    (FR-LLM-001/002/011/012) + Compliance Profile motoru (BRD §14.4 / DPIA `cp.*` most-restrictive-wins).
//  - SAF/DETERMİNİSTİK: türetme yardımcıları (enforcementTone/guardrailTone/modelStatusTone/profileStatusTone/
//    countEnabledGuardrails/mandatoryGuardrailCount/policyGaps/noTrainViolations/countByModelStatus/
//    allowedModelCount/activeProfileCount/coveredTenants) Date.now/rastgelelik içermez → birim-test edilebilir
//    + Python aynası (screens/p06-policy/p06_policy_probe.py).
//  - İŞ MANTIĞI/AUTHZ YOK (SAD §14.4.1 A8): guardrail/model-allowlist/compliance-profile düzenleme aksiyonları
//    UI'da yalnız görsel kapıdır; nihai yetki + zorlama backend'de (12.2.x; permission-key `policy:read` +
//    `policy:guardrail:manage` + `policy:model_allowlist:manage` + `policy:compliance_profile:manage`, SAD §7).
//    RBAC (BRD §17.6): bu ekran `platform_owner`=Yönet + `platform_sre`=Görüntüle + `platform_billing`=erişim yok.

export type Region = "uk" | "eu" | "na" | "me";

// Compliance profile ülke kümesi (DPIA PROFILE-TR/UK/EU/ME ile hizalı; ME composite). Bölgesel altyapı
// "Region"den ayrıdır (compliance ülke-tabanlı, altyapı bölge-tabanlı).
export type Country = "tr" | "uk" | "eu" | "me";

// Guardrail kategorisi (Policy Engine — SAD §6.2/§9.3; hem input hem output guard):
//  - input_guard: prompt-injection/jailbreak kontrolü (FR-LLM-007)
//  - output_guard: model cevabının politika motorundan geçmesi (FR-LLM-009)
//  - system_prompt_lock: system prompt'un konuşma/bilgi tabanı ile değiştirilememesi (FR-LLM-006)
//  - pii_redaction: transkript/çıktı üzerinde PII redaction (FR-REC-004)
//  - anti_hallucination: kaynaksız uydurma engeli, "kontrol ediyorum/aktarıyorum" davranışı (FR-KB-007)
export type GuardrailCategory =
  | "input_guard"
  | "output_guard"
  | "system_prompt_lock"
  | "pii_redaction"
  | "anti_hallucination";

// Zorlama eylemi: block (engelle) · redact (maskele) · flag (işaretle/logla) · off (eylem yok).
export type Enforcement = "block" | "redact" | "flag" | "off";

// Guardrail çalışma durumu.
export type GuardrailStatus = "enabled" | "disabled";

// Model kategorisi (vendor-nötr). FR-LLM-001 birden fazla sağlayıcı/model.
export type ModelCategory = "stt" | "tts" | "llm";

// Model tier (FR-LLM-013 tiering); STT/TTS için "na".
export type ModelTier = "small" | "large" | "na";

// Model allowlist durumu: allowed (izinli) · restricted (kısıtlı — onaya bağlı) · blocked (yasak).
export type ModelStatus = "allowed" | "restricted" | "blocked";

// Compliance profile durumu: active (uygulanabilir) · draft (taslak — atamaya kapalı).
export type ProfileStatus = "active" | "draft";

// Vendor-nötr sektör etiketi (compliance overlay; DPIA sektörel overlay).
export type Sector = "general" | "finance" | "health" | "public";

// StatusPill/Alert ile hizalı ton kümesi.
export type Tone = "success" | "warning" | "info" | "danger" | "neutral";

// Global güvenlik politikası (guardrail) — Policy Engine platform varsayılanı.
export interface GuardrailPolicy {
  id: string;
  category: GuardrailCategory;
  enforcement: Enforcement; // etkinken uygulanan eylem
  status: GuardrailStatus;
  mandatory: boolean; // güvenlik için zorunlu; kapatılırsa policy gap (uyarı tetiği)
  mappedFr: string; // izlenebilirlik (FR-LLM-007 vb.) — kod string, çeviri değil
}

// Model allowlist girişi (FR-LLM-001/002/011/012). Vendor-nötr id.
export interface ModelAllowlistEntry {
  id: string; // vendor-nötr model kimliği (somut marka DEĞİL)
  category: ModelCategory;
  tier: ModelTier;
  status: ModelStatus;
  noTrainDefault: boolean; // FR-LLM-012: tenant verisi eğitime varsayılan KAPALI (true = no-train aktif)
  versionPinned: boolean; // FR-LLM-011: model versiyonu sabitlenmiş/kayıtlı
  regions: Region[]; // bölgesel uygunluk (NFR 10.7)
}

// Varsayılan compliance profile (BRD §14.4 / DPIA `cp.*`). Tenant override yalnız-sıkılaştırır.
export interface ComplianceProfileDefault {
  id: string;
  country: Country; // PROFILE-TR/UK/EU/ME (DPIA)
  sector: Sector; // sektörel overlay (vendor-nötr)
  status: ProfileStatus;
  residency: Country; // veri yerleşimi varsayılanı
  retentionDays: number; // varsayılan saklama süresi (gün)
  requireTenantApproval: boolean; // FR-IAM-010: regüle break-glass tenant onayı varsayılanı
  overrideOnlyStricter: boolean; // DPIA most-restrictive-wins: tenant override yalnız sıkılaştırır
  appliedTenants: number; // bu profili kullanan tenant SAYISI (toplulaştırılmış; PII/kimlik değil)
}

export interface PolicySnapshot {
  generatedAt: string; // ISO-8601 (sabit yer tutucu — SSR-stabil, Date.now YOK)
  guardrails: GuardrailPolicy[];
  models: ModelAllowlistEntry[];
  complianceProfiles: ComplianceProfileDefault[];
}

// ── saf türetme yardımcıları ────────────────────────────────────────────────────

// Zorlama tonu: block/redact koruyucu (success) · flag yumuşak (warning) · off eylemsiz (neutral).
const ENFORCEMENT_TONE: Record<Enforcement, Tone> = {
  block: "success",
  redact: "success",
  flag: "warning",
  off: "neutral",
};
export function enforcementTone(e: Enforcement): Tone {
  return ENFORCEMENT_TONE[e];
}

// Guardrail tonu: zorunlu+kapalı → danger (policy gap) · kapalı → neutral · açık → success.
export function guardrailTone(g: GuardrailPolicy): Tone {
  if (g.status === "disabled") return g.mandatory ? "danger" : "neutral";
  return "success";
}

// Model allowlist durumu tonu: allowed success · restricted warning · blocked neutral (bilinçli yasak).
const MODEL_STATUS_TONE: Record<ModelStatus, Tone> = {
  allowed: "success",
  restricted: "warning",
  blocked: "neutral",
};
export function modelStatusTone(s: ModelStatus): Tone {
  return MODEL_STATUS_TONE[s];
}

// Compliance profile durumu tonu: active success · draft neutral.
const PROFILE_STATUS_TONE: Record<ProfileStatus, Tone> = {
  active: "success",
  draft: "neutral",
};
export function profileStatusTone(s: ProfileStatus): Tone {
  return PROFILE_STATUS_TONE[s];
}

// Etkin (enabled) guardrail sayısı.
export function countEnabledGuardrails(guardrails: GuardrailPolicy[]): number {
  return guardrails.filter((g) => g.status === "enabled").length;
}

// Zorunlu (mandatory) guardrail sayısı.
export function mandatoryGuardrailCount(guardrails: GuardrailPolicy[]): number {
  return guardrails.filter((g) => g.mandatory).length;
}

// Policy gap: ZORUNLU ama kapalı guardrail id'leri (güvenlik açığı → danger uyarısı).
export function policyGaps(snap: PolicySnapshot): string[] {
  return snap.guardrails.filter((g) => g.mandatory && g.status === "disabled").map((g) => g.id);
}

// No-train ihlali (FR-LLM-012): yasak OLMAYAN ama no-train varsayılanı KAPALI model id'leri.
// (blocked modeller zaten kullanım dışı olduğundan ihlal sayılmaz.)
export function noTrainViolations(snap: PolicySnapshot): string[] {
  return snap.models.filter((m) => m.status !== "blocked" && !m.noTrainDefault).map((m) => m.id);
}

// Model allowlist durum sayımı (özet KPI: allowed/restricted/blocked).
export function countByModelStatus(models: ModelAllowlistEntry[]): Record<ModelStatus, number> {
  const acc: Record<ModelStatus, number> = { allowed: 0, restricted: 0, blocked: 0 };
  for (const m of models) acc[m.status] += 1;
  return acc;
}

// İzinli (allowed) model sayısı.
export function allowedModelCount(models: ModelAllowlistEntry[]): number {
  return models.filter((m) => m.status === "allowed").length;
}

// Aktif (uygulanabilir) compliance profile sayısı.
export function activeProfileCount(profiles: ComplianceProfileDefault[]): number {
  return profiles.filter((p) => p.status === "active").length;
}

// Compliance profilleri tarafından kapsanan toplam tenant SAYISI (toplulaştırılmış; kimlik/PII değil).
export function coveredTenants(profiles: ComplianceProfileDefault[]): number {
  return profiles.reduce((sum, p) => sum + p.appliedTenants, 0);
}

// ── ALTIN KURAL koruması (iş-içeriği/son-müşteri PII sızıntısı) ───────────────────
// Snapshot yapısı içinde tenant İŞ İÇERİĞİ/SON-MÜŞTERİ PII'sini çağrıştıran ALAN ADI bulunursa hata
// fırlatır. Bu, P-06'nın yalnız platform-geneli politika/guardrail/model-allowlist + varsayılan
// compliance-profile metadatası göstermesini çalışma-anında garanti eder (BRD §17.7).
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
  "iban",
  "pii",
  "email",
  "ssn",
];

export function assertNoPii(node: unknown, path = "$"): void {
  if (node && typeof node === "object") {
    if (Array.isArray(node)) {
      node.forEach((v, i) => assertNoPii(v, `${path}[${i}]`));
      return;
    }
    for (const k of Object.keys(node as Record<string, unknown>)) {
      if (FORBIDDEN_PII_KEYS.includes(k.toLowerCase())) {
        throw new Error(`P-06 ALTIN KURAL ihlali: yasak iş-içeriği/PII alanı "${path}.${k}" (BRD §17.7)`);
      }
      assertNoPii((node as Record<string, unknown>)[k], `${path}.${k}`);
    }
  }
}

// ── veri SEAM (yer tutucu) ───────────────────────────────────────────────────────
// Deterministik yer tutucu: platform-geneli guardrail/model-allowlist + varsayılan compliance-profile
// metadatası (iş-içeriği/PII DEĞİL). Model id'leri VENDOR-NÖTR (somut marka değil; ADR-002). Gerçek
// implementasyon (F2 §14.1) Policy Engine (SAD §6.2/§9.3) + Model Router allowlist (FR-LLM-001/002/011/012) +
// Compliance Profile motoru (BRD §14.4 / DPIA `cp.*`) ile beslenir. Varsayılan profilde tüm zorunlu
// guardrail'ler açık + tüm aktif model no-train (sağlıklı taban); ihlal senaryoları samples/* altında.
const PLACEHOLDER_SNAPSHOT: PolicySnapshot = {
  generatedAt: "2026-06-17T09:00:00.000Z",
  guardrails: [
    { id: "g-input", category: "input_guard", enforcement: "block", status: "enabled", mandatory: true, mappedFr: "FR-LLM-007" },
    { id: "g-output", category: "output_guard", enforcement: "block", status: "enabled", mandatory: true, mappedFr: "FR-LLM-009" },
    { id: "g-sysprompt", category: "system_prompt_lock", enforcement: "block", status: "enabled", mandatory: true, mappedFr: "FR-LLM-006" },
    { id: "g-pii", category: "pii_redaction", enforcement: "redact", status: "enabled", mandatory: true, mappedFr: "FR-REC-004" },
    { id: "g-halluc", category: "anti_hallucination", enforcement: "flag", status: "enabled", mandatory: false, mappedFr: "FR-KB-007" },
  ],
  models: [
    { id: "llm-large-a", category: "llm", tier: "large", status: "allowed", noTrainDefault: true, versionPinned: true, regions: ["uk", "eu", "na", "me"] },
    { id: "llm-small-a", category: "llm", tier: "small", status: "allowed", noTrainDefault: true, versionPinned: true, regions: ["uk", "eu", "na", "me"] },
    { id: "llm-large-b", category: "llm", tier: "large", status: "restricted", noTrainDefault: true, versionPinned: false, regions: ["eu", "me"] },
    { id: "stt-a", category: "stt", tier: "na", status: "allowed", noTrainDefault: true, versionPinned: true, regions: ["uk", "eu", "na", "me"] },
    { id: "tts-a", category: "tts", tier: "na", status: "allowed", noTrainDefault: true, versionPinned: true, regions: ["uk", "eu", "na", "me"] },
    { id: "llm-legacy-x", category: "llm", tier: "large", status: "blocked", noTrainDefault: true, versionPinned: false, regions: [] },
  ],
  complianceProfiles: [
    { id: "profile-tr", country: "tr", sector: "finance", status: "active", residency: "tr", retentionDays: 3650, requireTenantApproval: true, overrideOnlyStricter: true, appliedTenants: 6 },
    { id: "profile-uk", country: "uk", sector: "general", status: "active", residency: "uk", retentionDays: 2555, requireTenantApproval: false, overrideOnlyStricter: true, appliedTenants: 4 },
    { id: "profile-eu", country: "eu", sector: "health", status: "active", residency: "eu", retentionDays: 3650, requireTenantApproval: true, overrideOnlyStricter: true, appliedTenants: 3 },
    { id: "profile-me", country: "me", sector: "general", status: "draft", residency: "me", retentionDays: 1825, requireTenantApproval: false, overrideOnlyStricter: true, appliedTenants: 0 },
  ],
};

export async function getPolicy(): Promise<PolicySnapshot> {
  const snap = PLACEHOLDER_SNAPSHOT;
  assertNoPii(snap); // ALTIN KURAL: yapısal iş-içeriği/son-müşteri PII yok (BRD §17.7)
  return snap;
}
