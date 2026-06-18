// WBS 13.4.6 — A-06 "Prompt Editor (versiyonlama)" veri katmanı (seam) + SAF türetme yardımcıları
// (L2 — Operasyon / Uygulama Paneli).
//
// ÇEKİRDEK İLKELER:
//  - İÇERİK (BRD §17.5 A-06 "Prompt Editor"): bir agent'ın system prompt'unun SÜRÜM GEÇMİŞİ ve
//    VERSİYONLAMA görünümü (FR-AGT-004). DB §5.2 `prompt` (tenant_id, agent_id, version_no, body,
//    is_published) ile birebir; her sürüm DEĞİŞMEZ (immutable) snapshot. Görünüm yalnız SÜRÜM META
//    taşır — sürüm no + ayırt edici SÜRÜM KİMLİĞİ (SR-AGT-004) + aşama + durum + test + boyut SAYISI
//    (karakter/değişken) + değişiklik NOTU. Prompt GÖVDESİ (body) GÖMÜLMEZ; gövde düzenleme (editör
//    alanı) derin aksiyondur (client island → API dilimi).
//  - VERSİYONLAMA (FR-AGT-004 / SR-AGT-004): her sürüm AYIRT EDİLEBİLİR (benzersiz versionNo + versionId)
//    ve GERİ ÇAĞRILABİLİR. Sürüm geçmişi + sürüm kimliği görüntülenir (SR-AGT-004 kabul ölçütü, yöntem I).
//  - AŞAMA (FR-AGT-005): draft | test | staging | production | archived. Aktif (production) sürüm
//    agent.active_version_id ile işaretlenir (DB §5.2).
//  - GERİ ALMA / ROLLBACK (FR-AGT-006): yayınlanmış (is_published) ve aktif OLMAYAN bir sürüme tek
//    işlemle dönülebilir. recallableVersions/canRollback saf kapılardır; nihai işlem backend'de.
//  - TEST KAPISI (FR-AGT-010): canlıya almadan önce otomatik test → testStatus (passed/failed/not_run).
//  - TENANT-SCOPE (FR-TEN-002): A-06 yalnız oturum açan tenant'ın KENDİ agent'ının prompt sürümleri.
//    Scope çalışma-anında middleware (13.1.2) + RLS (DB §6.3) ile sabitlenir; UI yalnız görsel kapı.
//  - HİJYEN (BRD §17.7 + §17.6): yalnız SÜRÜM META. Son-müşteri ham içeriği (transkript/ses kaydı/
//    ham numara/müşteri PII/CDR) gömülmez; PROMPT GÖVDESİ (promptText/promptBody) panele konmaz —
//    gövde derin aksiyon (görsel kapı + backend).
//  - GÜVENLİK (NFR 10.6): sır/credential görünüme KONMAZ (token/apiKey/webhookSecret/privateKey/kmsKey).
//  - VENDOR-NEUTRAL (ADR-002): veri kaynağı bir SEAM'dir; gerçek implementasyon (F1 §14.1) Agent Registry
//    (DB §5.2 `prompt` + `agent_version` + `agent.active_version_id`) tenant-scope (RLS) beslenir. Belirli
//    LLM/STT/TTS sağlayıcısı bağlanmaz.
//  - SAF/DETERMİNİSTİK: türetme yardımcıları (sortedVersions/activeVersion/latestVersion/countByStage/
//    recallableVersions/canRollback/hasPendingChanges/distinguishable/...) Date.now/rastgelelik içermez →
//    birim-test edilebilir + Python aynası (screens/a06-prompts/a06_prompts_probe.py).
//  - İŞ MANTIĞI/AUTHZ YOK (SAD §14.4.1 A8): düzenle/test/yayınla/geri-al aksiyonları görsel kapıdır;
//    nihai yetki + işlem backend'de (12.x). Panel yalnız çözümlenmiş sürüm geçmişini gösterir.
//  - RBAC (BRD §17.6 — L2): conversation_designer=Yönet · operations_manager=Düzenle · qa_analyst=Görüntüle ·
//    human_agent=— (A-05 ile aynı birincil rol: conversation_designer; qa_analyst kalite incelemesi için Görüntüle).

// Sürüm yaşam döngüsü aşaması (FR-AGT-005 / DB §5.2 agent.lifecycle_state).
export type PromptStage = "draft" | "test" | "staging" | "production" | "archived";
// Otomatik test durumu (FR-AGT-010).
export type TestStatus = "passed" | "failed" | "not_run";
// Türetilen sürüm durumu (rozet).
export type VersionStatus = "active" | "published" | "draft";

export type StatusTone = "success" | "warning" | "danger" | "neutral" | "info";

// Tek prompt sürümü (DB §5.2 `prompt` satırı). Yalnız SÜRÜM META — GÖVDE (body) DEĞİL.
export interface PromptVersion {
  versionNo: number; // monoton sürüm numarası (DB §5.2 version_no)
  versionId: string; // ayırt edici sürüm kimliği (SR-AGT-004; ör. "PV-7a3c")
  stage: PromptStage; // yaşam döngüsü aşaması (FR-AGT-005)
  isPublished: boolean; // yayınlandı mı (DB §5.2 is_published)
  testStatus: TestStatus; // otomatik test durumu (FR-AGT-010)
  createdAt: string; // ISO-8601 (sürüm oluşturulma zamanı — sürüm META)
  author: string; // sürümü oluşturan tenant kullanıcısı (izinli; son-müşteri PII değil)
  changeNote: string; // değişiklik notu (tenant config; PROMPT GÖVDESİ DEĞİL)
  charCount: number; // gövde boyutu — yalnız SAYI (gövde gömülmez)
  variableCount: number; // şablon değişkeni sayısı — yalnız SAYI
}

// Bir agent'ın prompt'unun sürüm geçmişi (DB §5.2 `prompt` + `agent.active_version_id`).
export interface PromptHistory {
  promptRef: string; // prompt referansı (DB §5.2 prompt gösterim kimliği)
  agentRef: string; // sürümleri görüntülenen agent referansı (tenant config)
  agentName: string; // agent adı (tenant config; PII değil)
  activeVersionNo: number | null; // aktif (production) sürüm no — agent.active_version_id (FR-AGT-006 rollback hedefi) | yok
  versions: PromptVersion[]; // sürüm geçmişi
}

export interface PromptView {
  generatedAt: string; // ISO-8601 (sabit yer tutucu — SSR-stabil, Date.now YOK)
  tenantRef: string; // tenant'ın KENDİ kimliği (L2'de izinli)
  tenantName: string; // tenant org adı (izinli; son-müşteri verisi DEĞİL)
  prompt: PromptHistory; // prompt sürüm geçmişi (tenant-scope FR-TEN-002)
}

// Aşamaların görüntüleme sırası (FR-AGT-005 yaşam döngüsü).
export const STAGE_ORDER: PromptStage[] = ["draft", "test", "staging", "production", "archived"];

// ── saf türetme yardımcıları ────────────────────────────────────────────────────

// Sürümleri versionNo'ya göre AZALAN sırala (en yeni en üstte; deterministik, kopya döndürür).
export function sortedVersions(history: PromptHistory): PromptVersion[] {
  return [...history.versions].sort((a, b) => b.versionNo - a.versionNo);
}

// Belirli numaradaki sürüm | undefined.
export function versionByNo(history: PromptHistory, no: number): PromptVersion | undefined {
  return history.versions.find((v) => v.versionNo === no);
}

// Aktif (production) sürüm | null (activeVersionNo işaret eder).
export function activeVersion(history: PromptHistory): PromptVersion | null {
  if (history.activeVersionNo === null) return null;
  return versionByNo(history, history.activeVersionNo) ?? null;
}

// En son (en yüksek numaralı) sürüm | null.
export function latestVersion(history: PromptHistory): PromptVersion | null {
  if (history.versions.length === 0) return null;
  return history.versions.reduce((acc, v) => (v.versionNo > acc.versionNo ? v : acc));
}

// Aşama başına sürüm sayısı (tüm aşamalar 0'dan başlatılır).
export function countByStage(history: PromptHistory): Record<PromptStage, number> {
  const acc = {} as Record<PromptStage, number>;
  for (const s of STAGE_ORDER) acc[s] = 0;
  for (const v of history.versions) acc[v.stage] += 1;
  return acc;
}

// Yayınlanmış sürümler (is_published).
export function publishedVersions(history: PromptHistory): PromptVersion[] {
  return history.versions.filter((v) => v.isPublished);
}

// Taslak (yayınlanmamış) sürümler.
export function draftVersions(history: PromptHistory): PromptVersion[] {
  return history.versions.filter((v) => !v.isPublished);
}

// Bir sürüm aktif (production) mı.
export function isActive(history: PromptHistory, v: PromptVersion): boolean {
  return history.activeVersionNo !== null && v.versionNo === history.activeVersionNo;
}

// Türetilen sürüm durumu: aktif → active · yayınlanmış (aktif değil) → published · aksi → draft.
export function versionStatus(history: PromptHistory, v: PromptVersion): VersionStatus {
  if (isActive(history, v)) return "active";
  if (v.isPublished) return "published";
  return "draft";
}

// GERİ ÇAĞRILABİLİR sürümler (FR-AGT-006 rollback): yayınlanmış + aktif OLMAYAN.
export function recallableVersions(history: PromptHistory): PromptVersion[] {
  return history.versions.filter((v) => v.isPublished && !isActive(history, v));
}

// Geri alınabilir mi: bir aktif sürüm var + geri çağrılabilir (önceki yayınlanmış) sürüm var.
export function canRollback(history: PromptHistory): boolean {
  return history.activeVersionNo !== null && recallableVersions(history).length > 0;
}

// Bekleyen değişiklik var mı (FR-AGT-004): aktif sürümden DAHA YENİ bir sürüm var (henüz canlıda değil).
export function hasPendingChanges(history: PromptHistory): boolean {
  const latest = latestVersion(history);
  if (latest === null) return false;
  if (history.activeVersionNo === null) return true; // hiç yayınlanmamış → bekleyen
  return latest.versionNo > history.activeVersionNo;
}

// Testte BAŞARISIZ sürümler (FR-AGT-010; arşivlenmemiş — dikkat gerektirir).
export function failedTestVersions(history: PromptHistory): PromptVersion[] {
  return history.versions.filter((v) => v.stage !== "archived" && v.testStatus === "failed");
}

// SR-AGT-004 "ayırt edilebilir": yinelenen versionNo (kimlik bütünlüğü ihlali).
export function duplicateVersionNos(history: PromptHistory): number[] {
  const seen = new Set<number>();
  const dup = new Set<number>();
  for (const v of history.versions) {
    if (seen.has(v.versionNo)) dup.add(v.versionNo);
    seen.add(v.versionNo);
  }
  return [...dup].sort((a, b) => a - b);
}

// SR-AGT-004 "ayırt edilebilir": yinelenen versionId.
export function duplicateVersionIds(history: PromptHistory): string[] {
  const seen = new Set<string>();
  const dup = new Set<string>();
  for (const v of history.versions) {
    if (seen.has(v.versionId)) dup.add(v.versionId);
    seen.add(v.versionId);
  }
  return [...dup].sort();
}

// Her sürüm ayırt edilebilir mi (versionNo + versionId benzersiz — SR-AGT-004).
export function distinguishable(history: PromptHistory): boolean {
  return duplicateVersionNos(history).length === 0 && duplicateVersionIds(history).length === 0;
}

// Bütünlük: activeVersionNo işaret ediyor ama eşleşen sürüm YOK (kopuk referans).
export function missingActiveVersion(history: PromptHistory): boolean {
  return history.activeVersionNo !== null && versionByNo(history, history.activeVersionNo) === undefined;
}

// Açık dikkat sayısı: bütünlük ihlalleri + başarısız test.
export function openAttentionCount(history: PromptHistory): number {
  return (
    duplicateVersionNos(history).length +
    duplicateVersionIds(history).length +
    (missingActiveVersion(history) ? 1 : 0) +
    failedTestVersions(history).length
  );
}

// ── ton (renk) eşlemeleri ─────────────────────────────────────────────────────────

const STAGE_TONE: Record<PromptStage, StatusTone> = {
  draft: "neutral",
  test: "info",
  staging: "warning",
  production: "success",
  archived: "neutral",
};
export function stageTone(s: PromptStage): StatusTone {
  return STAGE_TONE[s];
}

const STATUS_TONE: Record<VersionStatus, StatusTone> = {
  active: "success",
  published: "info",
  draft: "warning",
};
export function statusTone(s: VersionStatus): StatusTone {
  return STATUS_TONE[s];
}

const TEST_TONE: Record<TestStatus, StatusTone> = {
  passed: "success",
  failed: "danger",
  not_run: "warning",
};
export function testTone(t: TestStatus): StatusTone {
  return TEST_TONE[t];
}

// ── HİJYEN + GÜVENLİK koruması ─────────────────────────────────────────────────────
// Yapı içinde son-müşteri ham iş içeriği/PII'yi VEYA sır/credential/PROMPT GÖVDESİ çağrıştıran ALAN ADI
// bulunursa hata fırlatır. Bu, A-06'nın yalnız SÜRÜM META veriyi (sürüm no/kimliği/aşama/durum/test/boyut
// sayısı/değişiklik notu — tenant'ın KENDİ yapılandırması) — ham transkript/ses kaydı/ham numara/müşteri
// PII/CDR + PROMPT GÖVDESİ DEĞİL — göstermesini çalışma-anında garanti eder (BRD §17.7 + §17.6 + NFR 10.6).
// NOT: changeNote/author/agentName/tenantName tenant'ın KENDİ yapılandırmasıdır (L2'de izinli);
// charCount/variableCount yalnız SAYIdır (gövde değil).
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
  "prompttext", // prompt GÖVDESİ panele konmaz; gövde düzenleme derin aksiyon (client island)
  "promptbody",
  "body", // DB §5.2 prompt.body — sürüm META görünümüne gömülmez (yalnız charCount)
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
        throw new Error(`A-06 HİJYEN ihlali: yasak PII/iş-içeriği alanı "${path}.${k}" (BRD §17.7)`);
      }
      if (FORBIDDEN_SECRET_KEYS.includes(lower)) {
        throw new Error(`A-06 GÜVENLİK ihlali: sır/credential/prompt-gövdesi alanı "${path}.${k}" panele konmaz (NFR 10.6)`);
      }
      assertNoPii((node as Record<string, unknown>)[k], `${path}.${k}`);
    }
  }
}

// ── veri SEAM (yer tutucu) ───────────────────────────────────────────────────────
// Deterministik yer tutucu: tek-tenant agent prompt sürüm geçmişi (SÜRÜM META yalnız — ham içerik/PII/sır/
// prompt-gövdesi DEĞİL). Gerçek implementasyon (F1 §14.1) Agent Registry (DB §5.2 `prompt` +
// `agent.active_version_id`) tenant-scope (RLS) beslenir. Bu örnek: v5 aktif (production); v6 test'i geçen
// bekleyen sürüm; v4/v3 önceki yayınlanmış (geri çağrılabilir); v2/v1 arşiv. Her sürüm ayırt edilebilir.
const PLACEHOLDER_VIEW: PromptView = {
  generatedAt: "2026-06-18T09:00:00.000Z",
  tenantRef: "TEN-2048",
  tenantName: "Kuzey Sigorta A.Ş.",
  prompt: {
    promptRef: "PROMPT-31",
    agentRef: "AGT-117",
    agentName: "Poliçe Yenileme Asistanı",
    activeVersionNo: 5,
    versions: [
      { versionNo: 6, versionId: "PV-6f1a", stage: "test", isPublished: false, testStatus: "passed", createdAt: "2026-06-17T14:20:00.000Z", author: "Derya Kaya", changeNote: "İade politikası ifadesi güncellendi", charCount: 2480, variableCount: 7 },
      { versionNo: 5, versionId: "PV-5c2b", stage: "production", isPublished: true, testStatus: "passed", createdAt: "2026-06-10T09:05:00.000Z", author: "Derya Kaya", changeNote: "Karşılama ve yapay zekâ bildirimi netleştirildi", charCount: 2410, variableCount: 7 },
      { versionNo: 4, versionId: "PV-4a9d", stage: "archived", isPublished: true, testStatus: "passed", createdAt: "2026-05-28T16:40:00.000Z", author: "Mert Aydın", changeNote: "Yenileme adımı eklendi", charCount: 2210, variableCount: 6 },
      { versionNo: 3, versionId: "PV-3b7e", stage: "archived", isPublished: true, testStatus: "passed", createdAt: "2026-05-12T11:15:00.000Z", author: "Mert Aydın", changeNote: "Dil tonu kurumsal hale getirildi", charCount: 2050, variableCount: 5 },
      { versionNo: 2, versionId: "PV-2d4c", stage: "archived", isPublished: false, testStatus: "passed", createdAt: "2026-04-30T08:00:00.000Z", author: "Derya Kaya", changeNote: "İlk taslak revizyonu", charCount: 1870, variableCount: 4 },
      { versionNo: 1, versionId: "PV-1e8f", stage: "archived", isPublished: false, testStatus: "not_run", createdAt: "2026-04-22T10:30:00.000Z", author: "Derya Kaya", changeNote: "İlk sürüm", charCount: 1600, variableCount: 3 },
    ],
  },
};

export async function getPromptView(): Promise<PromptView> {
  const view = PLACEHOLDER_VIEW;
  assertNoPii(view); // HİJYEN + GÜVENLİK: yapısal son-müşteri PII / sır / prompt-gövdesi yok (BRD §17.7 / NFR 10.6)
  return view;
}
