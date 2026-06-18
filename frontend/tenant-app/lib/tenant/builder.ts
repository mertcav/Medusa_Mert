// WBS 13.4.4 — A-04 "Agent Builder (kod yazmadan)" veri katmanı (seam) + SAF türetme yardımcıları
// (L2 — Operasyon / Uygulama Paneli).
//
// ÇEKİRDEK İLKELER:
//  - İÇERİK (BRD §17.5 A-04 "Kod yazmadan agent oluşturma"): tenant kullanıcısının KOD YAZMADAN
//    (configuration-over-coding, FR-AGT-001) bir Voice AI agent'ı oluşturmasını sağlayan REHBERLİ
//    yapılandırma görünümü. Bir TASLAK (draft) agent + onun YAPILANDIRMA ADIMLARI (basics/konuşma
//    modeli/bilgi/tool/ses-model/politika) + başlangıç noktası (boş/şablon/klon) + hazırlık & yayın
//    kapısı. Her adım yalnız KONFİGÜRASYON META taşır (alan sayıları, seçilen mod, dil) — prompt gövdesi
//    veya tool kimlik bilgisi GÖMÜLMEZ (derin tasarım → A-05 Flow / A-06 Prompt / A-09 Tool, görsel kapı).
//  - NO-CODE (FR-AGT-001): builder ham kod istemez; başlangıç noktaları (boş / şablon / mevcut agent'tan
//    klon → segment varyantı FR-AGT-008) + rehberli adımlar + alan tabanlı yapılandırma. Bu bir
//    KONFİGÜRASYON ekranıdır — A-02 gibi GERÇEK ZAMANLI DEĞİL (FR-ANA-012 kapsamı dışı); tazelik bütçesi yok.
//  - ALANLAR (FR-AGT-002): isim/amaç/kişilik/dil/iş kuralları taslak META'sıdır (tenant'ın KENDİ
//    yapılandırması — son-müşteri PII değil); iş kuralları SAYI olarak özetlenir (kural metni gömülmez).
//  - KONUŞMA MODELİ (FR-AGT-003): single_prompt | node_flow seçimi builder'da zorunlu bir adımdır;
//    seçilmemiş (null) ise test'e gönderim bloklanır.
//  - YAŞAM DÖNGÜSÜ (FR-AGT-005): builder çıktısı bir DRAFT'tır; yayın öncesi otomatik test kapısı
//    (FR-AGT-010) geçilmelidir. readyForDraft / readyForTest / readyForPublish saf kapılardır.
//  - GÜVENLİK POLİTİKALARI (FR-AGT-009): builder'da bir zorunlu "politika/guardrail" adımı vardır
//    (global + tenant politikaları agent'a uygulanır).
//  - TENANT-SCOPE (FR-TEN-002): A-04 yalnız oturum açan tenant'ın KENDİ taslağı + şablonları. Scope
//    çalışma-anında middleware (13.1.2) + RLS (DB §6.3) ile sabitlenir; UI yalnız görsel kapı (SAD §14.4.1 A8).
//  - HİJYEN (BRD §17.7 + §17.6): yalnız KONFİGÜRASYON META. Son-müşteri ham içeriği (transkript/ses kaydı/
//    ham numara/müşteri PII/CDR) gömülmez; prompt gövdesi/tool sırrı derin aksiyon → A-05/A-06/A-09.
//  - GÜVENLİK (NFR 10.6): sır/credential görünüme KONMAZ (token/apiKey/webhookSecret/privateKey/kmsKey).
//  - VENDOR-NEUTRAL (ADR-002): veri kaynağı bir SEAM'dir; gerçek implementasyon (F1 §14.1) Agent Registry
//    (DB §5.2 `agent` + `agent_version` + `conversation_flow`) + şablon kütüphanesinden tenant-scope (RLS)
//    beslenir. Belirli LLM/STT/TTS sağlayıcısı bağlanmaz.
//  - SAF/DETERMİNİSTİK: türetme yardımcıları (stepStatus/completedSteps/requiredStepsComplete/
//    completionPercent/readyForTest/blockers/...) Date.now/rastgelelik içermez → birim-test edilebilir +
//    Python aynası (screens/a04-builder/a04_builder_probe.py).
//  - İŞ MANTIĞI/AUTHZ YOK (SAD §14.4.1 A8): kaydet/test'e gönder/yayınla aksiyonları görsel kapıdır;
//    nihai yetki + işlem backend'de (12.x). Panel yalnız çözümlenmiş taslağı gösterir + hazırlığı işaretler.
//  - RBAC (BRD §17.6 — L2): conversation_designer=Yönet · operations_manager=Düzenle · qa_analyst=— ·
//    human_agent=— (A-03'ten fark: BURADA conversation_designer birincil rol).

// Yapılandırma adımı kimliği.
export type StepId =
  | "basics" // isim/amaç/kişilik/dil/iş kuralları (FR-AGT-002)
  | "conversation_model" // single_prompt | node_flow seçimi (FR-AGT-003)
  | "knowledge" // bilgi tabanı bağlama (A-08) — opsiyonel
  | "tools" // tool/API bağlama (A-09) — opsiyonel
  | "voice_model" // ses/model/STT profili (A-07)
  | "policies"; // güvenlik politikaları / guardrail (FR-AGT-009)

// Adım durumu (alan tamamlanmasından TÜRETİLİR).
export type StepStatus = "complete" | "in_progress" | "incomplete";
// Konuşma modeli (FR-AGT-003); null = henüz seçilmedi.
export type ConversationModel = "single_prompt" | "node_flow" | null;
// Başlangıç noktası (no-code): boş / şablon / mevcut agent'tan klon (varyant FR-AGT-008).
export type StartMode = "blank" | "template" | "clone";
// Otomatik test kapısı sonucu (FR-AGT-010).
export type TestStatus = "passed" | "failed" | "not_run";
// Yaşam döngüsü (FR-AGT-005 / DB §5.2 agent.lifecycle_state).
export type AgentLifecycle = "draft" | "test" | "staging" | "production" | "archived";

export type StatusTone = "success" | "warning" | "danger" | "neutral" | "info";

// Tek yapılandırma adımı. Yalnız KONFİGÜRASYON META: alan sayıları (içerik DEĞİL).
export interface BuilderStep {
  id: StepId; // adım kimliği
  required: boolean; // test'e gönderim için zorunlu mu
  fieldsTotal: number; // adımdaki toplam yapılandırma alanı sayısı
  fieldsComplete: number; // tamamlanan alan sayısı (0..fieldsTotal)
}

// Builder'da yapılandırılan TASLAK agent. Yalnız KONFİGÜRASYON META — son-müşteri içeriği DEĞİL.
export interface AgentDraft {
  draftRef: string; // gösterim referansı (ör. "DRAFT-12")
  name: string; // agent adı (tenant config — FR-AGT-002; PII değil)
  purpose: string; // kısa amaç etiketi (tenant config — FR-AGT-002)
  personality: string | null; // kişilik preset etiketi (tenant config — FR-AGT-002) | seçilmedi
  languages: string[]; // diller (FR-AGT-002; ISO kısa kod)
  businessRulesCount: number; // tanımlı iş kuralı SAYISI (FR-AGT-002; kural METNİ gömülmez)
  conversationModel: ConversationModel; // konuşma modeli (FR-AGT-003)
  startMode: StartMode; // başlangıç noktası (no-code FR-AGT-001)
  templateRef: string | null; // şablondan başlandıysa şablon referansı | yok
  baseAgentRef: string | null; // klon ise temel agent referansı (FR-AGT-008) | yok
  isVariant: boolean; // segment varyantı mı (FR-AGT-008)
  lifecycle: AgentLifecycle; // taslak yaşam döngüsü (FR-AGT-005; tipik "draft")
  testStatus: TestStatus; // son otomatik test kapısı sonucu (FR-AGT-010)
  steps: BuilderStep[]; // yapılandırma adımları
}

// No-code başlangıç şablonu (no-code başlangıç noktası — FR-AGT-001).
export interface BuilderTemplate {
  templateRef: string; // şablon referansı
  name: string; // şablon adı (tenant config; PII değil)
  purpose: string; // şablon amacı
  mode: "single_prompt" | "node_flow"; // şablonun konuşma modeli (FR-AGT-003)
  languages: string[]; // şablonun varsayılan dilleri (FR-AGT-002)
}

export interface BuilderView {
  generatedAt: string; // ISO-8601 (sabit yer tutucu — SSR-stabil, Date.now YOK)
  tenantRef: string; // tenant'ın KENDİ kimliği (L2'de izinli)
  tenantName: string; // tenant org adı (izinli; son-müşteri verisi DEĞİL)
  draft: AgentDraft; // yapılandırılan taslak (tenant-scope FR-TEN-002)
  templates: BuilderTemplate[]; // no-code başlangıç şablonları
}

// Adımların görüntüleme/akış sırası.
export const STEP_ORDER: StepId[] = ["basics", "conversation_model", "knowledge", "tools", "voice_model", "policies"];
// Test'e gönderim için ZORUNLU adımlar (knowledge/tools opsiyonel).
export const REQUIRED_STEPS: StepId[] = ["basics", "conversation_model", "voice_model", "policies"];

// ── saf türetme yardımcıları ────────────────────────────────────────────────────

// Adım durumu: alan tamamlanmasından TÜRETİLİR (deterministik).
export function stepStatus(s: BuilderStep): StepStatus {
  if (s.fieldsTotal > 0 && s.fieldsComplete >= s.fieldsTotal) return "complete";
  if (s.fieldsComplete <= 0) return "incomplete";
  return "in_progress";
}

// Belirli kimlikteki adım | undefined.
export function stepById(steps: BuilderStep[], id: StepId): BuilderStep | undefined {
  return steps.find((s) => s.id === id);
}

// Tamamlanan adımlar.
export function completedSteps(steps: BuilderStep[]): BuilderStep[] {
  return steps.filter((s) => stepStatus(s) === "complete");
}

// Zorunlu adımlar.
export function requiredSteps(steps: BuilderStep[]): BuilderStep[] {
  return steps.filter((s) => s.required);
}

// Zorunlu ama tamamlanmamış adımlar (test'e gönderimi bloklar).
export function incompleteRequiredSteps(steps: BuilderStep[]): BuilderStep[] {
  return steps.filter((s) => s.required && stepStatus(s) !== "complete");
}

// Tüm zorunlu adımlar tamam mı.
export function requiredStepsComplete(steps: BuilderStep[]): boolean {
  return incompleteRequiredSteps(steps).length === 0;
}

// Tamamlanma yüzdesi (tüm adımlar üzerinden, tamsayı).
export function completionPercent(steps: BuilderStep[]): number {
  if (steps.length === 0) return 0;
  return Math.round((completedSteps(steps).length / steps.length) * 100);
}

// Toplam alan sayısı (tüm adımlar).
export function fieldsTotal(steps: BuilderStep[]): number {
  return steps.reduce((acc, s) => acc + s.fieldsTotal, 0);
}
// Tamamlanan alan sayısı (tüm adımlar).
export function fieldsComplete(steps: BuilderStep[]): number {
  return steps.reduce((acc, s) => acc + s.fieldsComplete, 0);
}

// Konuşma modeli seçildi mi (FR-AGT-003).
export function hasConversationModel(draft: AgentDraft): boolean {
  return draft.conversationModel !== null;
}

// TASLAK kaydedilebilir mi: basics adımı tamam (FR-AGT-005 draft).
export function readyForDraft(draft: AgentDraft): boolean {
  const b = stepById(draft.steps, "basics");
  return b !== undefined && stepStatus(b) === "complete";
}

// TEST'e gönderilebilir mi: tüm zorunlu adımlar tamam + konuşma modeli seçili (FR-AGT-010 önkoşulu).
export function readyForTest(draft: AgentDraft): boolean {
  return requiredStepsComplete(draft.steps) && hasConversationModel(draft);
}

// YAYINLANABİLİR mi: test'e hazır + otomatik test kapısı GEÇTİ (FR-AGT-010 + FR-AGT-005 staging→production).
export function readyForPublish(draft: AgentDraft): boolean {
  return readyForTest(draft) && draft.testStatus === "passed";
}

// Test'e gönderimi BLOKLAYAN adım kimlikleri (zorunlu + tamamlanmamış); konuşma modeli yoksa eklenir.
export function blockers(draft: AgentDraft): StepId[] {
  const ids = incompleteRequiredSteps(draft.steps).map((s) => s.id);
  if (!hasConversationModel(draft) && !ids.includes("conversation_model")) ids.push("conversation_model");
  return ids;
}

// Önerilen sonraki adım: sırada tamamlanmamış İLK adım | null.
export function nextStep(draft: AgentDraft): StepId | null {
  for (const id of STEP_ORDER) {
    const s = stepById(draft.steps, id);
    if (s && stepStatus(s) !== "complete") return id;
  }
  return null;
}

// ── ton (renk) eşlemeleri ─────────────────────────────────────────────────────────

const STEP_TONE: Record<StepStatus, StatusTone> = {
  complete: "success",
  in_progress: "warning",
  incomplete: "neutral",
};
export function stepTone(s: StepStatus): StatusTone {
  return STEP_TONE[s];
}

export function modelTone(m: ConversationModel): StatusTone {
  if (m === "node_flow") return "info";
  if (m === "single_prompt") return "neutral";
  return "warning"; // null → seçilmedi
}

const TEST_TONE: Record<TestStatus, StatusTone> = {
  passed: "success",
  failed: "danger",
  not_run: "warning",
};
export function testTone(s: TestStatus): StatusTone {
  return TEST_TONE[s];
}

const START_MODE_TONE: Record<StartMode, StatusTone> = {
  blank: "neutral",
  template: "info",
  clone: "info",
};
export function startModeTone(m: StartMode): StatusTone {
  return START_MODE_TONE[m];
}

// Hazırlık tonu: hazır → success · değil → warning.
export function readyTone(b: boolean): StatusTone {
  return b ? "success" : "warning";
}

// ── HİJYEN + GÜVENLİK koruması ─────────────────────────────────────────────────────
// Yapı içinde son-müşteri ham iş içeriği/PII'yi VEYA sır/credential çağrıştıran ALAN ADI bulunursa hata
// fırlatır. Bu, A-04'ün yalnız KONFİGÜRASYON META veriyi (taslak ad/amaç/adım alan sayıları/mod — tenant'ın
// KENDİ yapılandırması) — ham transkript/ses kaydı/ham numara/müşteri PII/CDR + prompt gövdesi/tool sırrı
// DEĞİL — göstermesini çalışma-anında garanti eder (BRD §17.7 + §17.6 + NFR 10.6). NOT: name/purpose/
// tenantName tenant'ın KENDİ yapılandırmasıdır (L2'de izinli).
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
  "prompttext", // prompt gövdesi derin tasarım (A-06) — builder META'sına gömülmez
  "promptbody",
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
        throw new Error(`A-04 HİJYEN ihlali: yasak PII/iş-içeriği alanı "${path}.${k}" (BRD §17.7)`);
      }
      if (FORBIDDEN_SECRET_KEYS.includes(lower)) {
        throw new Error(`A-04 GÜVENLİK ihlali: sır/credential/prompt-gövdesi alanı "${path}.${k}" panele konmaz (NFR 10.6)`);
      }
      assertNoPii((node as Record<string, unknown>)[k], `${path}.${k}`);
    }
  }
}

// ── veri SEAM (yer tutucu) ───────────────────────────────────────────────────────
// Deterministik yer tutucu: tek-tenant builder taslağı + no-code şablon kütüphanesi (KONFİGÜRASYON META
// yalnız — ham içerik/PII/sır/prompt-gövdesi DEĞİL). Gerçek implementasyon (F1 §14.1) Agent Registry
// (DB §5.2 `agent` + `agent_version` + `conversation_flow`) + şablon kütüphanesinden tenant-scope (RLS) beslenir.
const PLACEHOLDER_VIEW: BuilderView = {
  generatedAt: "2026-06-18T09:00:00.000Z",
  tenantRef: "TEN-2048",
  tenantName: "Kuzey Sigorta A.Ş.",
  draft: {
    draftRef: "DRAFT-31",
    name: "Poliçe Yenileme Asistanı",
    purpose: "Inbound poliçe yenileme bilgilendirme ve yönlendirme",
    personality: "professional_warm",
    languages: ["tr", "en"],
    businessRulesCount: 6,
    conversationModel: "node_flow",
    startMode: "template",
    templateRef: "TPL-INS-01",
    baseAgentRef: null,
    isVariant: false,
    lifecycle: "draft",
    testStatus: "not_run",
    steps: [
      { id: "basics", required: true, fieldsTotal: 5, fieldsComplete: 5 },
      { id: "conversation_model", required: true, fieldsTotal: 1, fieldsComplete: 1 },
      { id: "knowledge", required: false, fieldsTotal: 3, fieldsComplete: 2 },
      { id: "tools", required: false, fieldsTotal: 2, fieldsComplete: 0 },
      { id: "voice_model", required: true, fieldsTotal: 3, fieldsComplete: 2 },
      { id: "policies", required: true, fieldsTotal: 4, fieldsComplete: 0 },
    ],
  },
  templates: [
    { templateRef: "TPL-INS-01", name: "Sigorta — Poliçe Yenileme", purpose: "Inbound poliçe yenileme akışı", mode: "node_flow", languages: ["tr", "en"] },
    { templateRef: "TPL-COL-02", name: "Tahsilat — Ödeme Hatırlatma", purpose: "Outbound ödeme hatırlatma + consent", mode: "single_prompt", languages: ["tr"] },
    { templateRef: "TPL-SUP-03", name: "Destek — Seviye 1 Sorun Giderme", purpose: "Inbound L1 teknik destek", mode: "node_flow", languages: ["tr", "en"] },
    { templateRef: "TPL-APP-04", name: "Randevu — Oluşturma ve Teyit", purpose: "Inbound randevu oluşturma", mode: "single_prompt", languages: ["tr"] },
  ],
};

export async function getBuilderView(): Promise<BuilderView> {
  const view = PLACEHOLDER_VIEW;
  assertNoPii(view); // HİJYEN + GÜVENLİK: yapısal son-müşteri PII / sır / prompt-gövdesi yok (BRD §17.7 / NFR 10.6)
  return view;
}
