// WBS 13.4.17 — A-17 "Sürüm Geçmişi (agent) + rollback" veri katmanı (seam) + SAF türetme yardımcıları
// (L2 — Operasyon / Uygulama Paneli).
//
// ÇEKİRDEK İLKELER:
//  - İÇERİK (BRD §17.5 A-17 "Sürüm Geçmişi (agent) — Agent versiyonları ve rollback"): bir agent'ın YAYIN/SÜRÜM
//    GEÇMİŞİ görünümü. DB §5.2 `agent_version` (tenant_id, agent_id, version_no, prompt_id/flow_id/voice/model/stt
//    profilleri, snapshot JSONB, published_by, published_at; **WORM/DEĞİŞMEZ** snapshot — FR-AGT-006) +
//    `agent.active_version_id` (production sürüm) ile birebir. Görünüm yalnız SÜRÜM META taşır — sürüm no + ayırt
//    edici SÜRÜM KİMLİĞİ + aşama + durum + test + yayınlayan + yayın zamanı + değişiklik NOTU + bağlanan config
//    SÜRÜM/PROFİL ADLARI (snapshot JSONB GÖVDESİ DEĞİL) + rollback köken işareti.
//  - ROLLBACK / GERİ ALMA (FR-AGT-006 — A-17'nin ÇEKİRDEK gereksinimi): "Yayınlanan sürüm tek işlemle önceki
//    sürüme döndürülebilmelidir." recallableVersions/previousPublishedVersion/canRollback saf kapılardır; geri alma
//    backend'de WORM **append-only** uygulanır (DB §6.5 — rollback = YENİ satır, eski satır korunur). Bir sürümün
//    rollbackOfNo'su, o sürümün hangi önceki sürümü geri yüklediğini gösterir (köken izi).
//  - VERSİYONLAMA / AYIRT EDİLEBİLİRLİK (FR-AGT-004 / DB UNIQUE(tenant,agent,version_no)): her sürüm benzersiz
//    versionNo + versionId; distinguishable bunu deterministik test eder.
//  - AŞAMA (FR-AGT-005): draft | test | staging | production | archived. Aktif (production) sürüm
//    agent.active_version_id ile işaretlenir (DB §5.2).
//  - TEST KAPISI (FR-AGT-010 + FR-TST-005 A-16 gate): canlıya/production'a almadan önce otomatik test → testStatus
//    (passed/failed/not_run). Promotion gate detayı A-16'dadır; A-17 sürüm META'sında test durumunu yansıtır.
//  - TENANT-SCOPE (FR-TEN-002): A-17 yalnız oturum açan tenant'ın KENDİ agent'ının sürümleri. Scope çalışma-anında
//    middleware (13.1.2) + RLS (DB §6.3) ile sabitlenir; UI yalnız görsel kapı.
//  - HİJYEN — İKİ KATMAN (BRD §17.7 + FR-REC-004/005 + NFR 10.6):
//      (1) YAPISAL anahtar guard (assertNoForbiddenKeys): yalnız SÜRÜM META. Son-müşteri ham iş içeriği
//          (transkript/ses kaydı/ham numara/müşteri PII/CDR) + **agent_version snapshot JSONB GÖVDESİ** (snapshot/
//          prompt gövdesi/flow tanımı) + sır/credential + nesne-depo URI alan ADI taşınamaz. NOT:
//          publishedBy/changeNote/agentName tenant'ın KENDİ config'idir (L2'de izinli); promptVersionNo/charCount
//          yalnız SAYI/AD'dır (gövde değil).
//      (2) İÇERİK redaction guard (assertRedactionClean): TÜM string değerleri ham PII DESENİ (≥7 rakam/e-posta/
//          +rakam/kart-bloğu/IBAN) için taranır (FR-REC-004/005). Sürüm no/sayılar (number) string değildir → taranmaz.
//  - VENDOR-NEUTRAL (ADR-002): veri kaynağı bir SEAM'dir; gerçek implementasyon (F1 §14.1) Agent Registry (DB §5.2
//    `agent_version` + `agent.active_version_id`) tenant-scope (RLS) beslenir. Belirli LLM/STT/TTS sağlayıcısı bağlanmaz.
//  - SAF/DETERMİNİSTİK: türetmeler Date.now/rastgelelik içermez → birim-test + Python aynası
//    (screens/a17-versions/a17_versions_probe.py).
//  - İŞ MANTIĞI/AUTHZ YOK (SAD §14.4.1): rollback/promote/yeni-sürüm YAZIMI + audit YOK; nihai yetki + işlem + audit
//    backend'de + RLS. Panel yalnız çözümlenmiş sürüm geçmişini gösterir.
//  - RBAC (BRD §17.6 — L2 A-17 satırı): conversation_designer=Yönet · operations_manager=Görüntüle · qa_analyst=— ·
//    human_agent=— (erişim yok). tenant_owner kural 17.7 ile Yönet. Permission-key: agent:version:manage (API §8.1).

// Sürüm yaşam döngüsü aşaması (FR-AGT-005 / DB §5.2 agent.lifecycle_state).
export type VersionStage = "draft" | "test" | "staging" | "production" | "archived";
// Otomatik test durumu (FR-AGT-010).
export type TestStatus = "passed" | "failed" | "not_run";
// Türetilen sürüm durumu (rozet).
export type VersionStatus = "active" | "published" | "draft";

export type StatusTone = "success" | "warning" | "danger" | "neutral" | "info";

// Tek agent sürümü (DB §5.2 `agent_version` satırı). Yalnız SÜRÜM META + bağlanan config SÜRÜM/PROFİL ADLARI —
// snapshot JSONB GÖVDESİ DEĞİL.
export interface AgentVersion {
  versionNo: number; // monoton sürüm numarası (DB §5.2 version_no; UNIQUE(tenant,agent,version_no))
  versionId: string; // ayırt edici sürüm kimliği (ör. "AV-7a3c")
  stage: VersionStage; // yaşam döngüsü aşaması (FR-AGT-005)
  isPublished: boolean; // yayınlandı mı (production'a alınmış/alınabilir snapshot)
  testStatus: TestStatus; // otomatik test durumu (FR-AGT-010 / A-16 gate)
  publishedBy: string; // sürümü yayınlayan tenant kullanıcısı (DB published_by; izinli — son-müşteri PII değil)
  publishedAt: string; // ISO-8601 (DB published_at — sürüm META)
  changeNote: string; // değişiklik notu (tenant config; snapshot GÖVDESİ DEĞİL)
  rollbackOfNo: number | null; // ROLLBACK kökeni: bu sürüm hangi ÖNCEKİ sürümü geri yükledi (FR-AGT-006; null=ileri sürüm)
  // bağlanan config — yalnız SÜRÜM/PROFİL ADLARI (snapshot JSONB gömülmez; DB §5.2 FK referansları)
  promptVersionNo: number; // bağlanan prompt sürümü (DB prompt_id → A-06)
  flowVersionNo: number | null; // bağlanan flow sürümü (DB flow_id → A-05; single-prompt agent'ta null)
  voiceProfile: string; // ses profili ADI (DB voice_profile_id → A-07)
  modelProfile: string; // model profili/tier ADI (DB model_profile_id → A-07)
  sttProfile: string; // STT profili ADI (DB stt_profile_id → A-07)
}

// Bir agent'ın sürüm geçmişi (DB §5.2 `agent_version` + `agent.active_version_id`).
export interface AgentVersionHistory {
  agentRef: string; // sürümleri görüntülenen agent referansı (tenant config)
  agentName: string; // agent adı (tenant config; PII değil)
  lifecycleState: VersionStage; // agent.lifecycle_state (FR-AGT-005)
  activeVersionNo: number | null; // aktif (production) sürüm no — agent.active_version_id (FR-AGT-006 rollback kaynağı) | yok
  versions: AgentVersion[]; // sürüm geçmişi (DB agent_version satırları)
}

export interface AgentVersionView {
  generatedAt: string; // ISO-8601 (sabit yer tutucu — SSR-stabil, Date.now YOK)
  tenantRef: string; // tenant'ın KENDİ kimliği (L2'de izinli)
  tenantName: string; // tenant org adı (izinli; son-müşteri verisi DEĞİL)
  agent: AgentVersionHistory; // agent sürüm geçmişi (tenant-scope FR-TEN-002)
}

// Aşamaların görüntüleme sırası (FR-AGT-005 yaşam döngüsü).
export const STAGE_ORDER: VersionStage[] = ["draft", "test", "staging", "production", "archived"];
export const TEST_ORDER: TestStatus[] = ["passed", "failed", "not_run"];
export const STATUS_ORDER: VersionStatus[] = ["active", "published", "draft"];

// ── saf türetme yardımcıları ────────────────────────────────────────────────────

// Sürümleri versionNo'ya göre AZALAN sırala (en yeni en üstte; deterministik, kopya döndürür).
export function sortedVersions(history: AgentVersionHistory): AgentVersion[] {
  return [...history.versions].sort((a, b) => b.versionNo - a.versionNo);
}

// Belirli numaradaki sürüm | undefined.
export function versionByNo(history: AgentVersionHistory, no: number): AgentVersion | undefined {
  return history.versions.find((v) => v.versionNo === no);
}

// Aktif (production) sürüm | null (activeVersionNo işaret eder).
export function activeVersion(history: AgentVersionHistory): AgentVersion | null {
  if (history.activeVersionNo === null) return null;
  return versionByNo(history, history.activeVersionNo) ?? null;
}

// En son (en yüksek numaralı) sürüm | null.
export function latestVersion(history: AgentVersionHistory): AgentVersion | null {
  if (history.versions.length === 0) return null;
  return history.versions.reduce((acc, v) => (v.versionNo > acc.versionNo ? v : acc));
}

// Aşama başına sürüm sayısı (tüm aşamalar 0'dan başlatılır).
export function countByStage(history: AgentVersionHistory): Record<VersionStage, number> {
  const acc = {} as Record<VersionStage, number>;
  for (const s of STAGE_ORDER) acc[s] = 0;
  for (const v of history.versions) acc[v.stage] += 1;
  return acc;
}

// Yayınlanmış sürümler (production'a alınmış/alınabilir snapshot).
export function publishedVersions(history: AgentVersionHistory): AgentVersion[] {
  return history.versions.filter((v) => v.isPublished);
}

// Taslak (yayınlanmamış) sürümler.
export function draftVersions(history: AgentVersionHistory): AgentVersion[] {
  return history.versions.filter((v) => !v.isPublished);
}

// Bir sürüm aktif (production) mı.
export function isActive(history: AgentVersionHistory, v: AgentVersion): boolean {
  return history.activeVersionNo !== null && v.versionNo === history.activeVersionNo;
}

// Türetilen sürüm durumu: aktif → active · yayınlanmış (aktif değil) → published · aksi → draft.
export function versionStatus(history: AgentVersionHistory, v: AgentVersion): VersionStatus {
  if (isActive(history, v)) return "active";
  if (v.isPublished) return "published";
  return "draft";
}

// Bu sürüm bir ROLLBACK ürünü mü (önceki bir sürümü geri yükledi — FR-AGT-006 / WORM append-only DB §6.5).
export function isRollback(v: AgentVersion): boolean {
  return v.rollbackOfNo !== null;
}

// Rollback ürünü sürüm sayısı (geçmişte kaç kez geri alındı).
export function rollbackCount(history: AgentVersionHistory): number {
  return history.versions.filter((v) => isRollback(v)).length;
}

// ── ROLLBACK kapıları (FR-AGT-006) ───────────────────────────────────────────────

// GERİ ÇAĞRILABİLİR sürümler (FR-AGT-006 rollback hedef adayları): yayınlanmış + aktif OLMAYAN.
export function recallableVersions(history: AgentVersionHistory): AgentVersion[] {
  return history.versions.filter((v) => v.isPublished && !isActive(history, v));
}

// "Önceki sürüm" = tek-işlem rollback'in VARSAYILAN hedefi (FR-AGT-006). Aktiften DAHA DÜŞÜK numaralı en yüksek
// yayınlanmış sürüm; aktiften düşük yoksa en yüksek geri çağrılabilir sürüm | null.
export function previousPublishedVersion(history: AgentVersionHistory): AgentVersion | null {
  const recallable = recallableVersions(history);
  if (recallable.length === 0) return null;
  const active = history.activeVersionNo;
  const below = active === null ? [] : recallable.filter((v) => v.versionNo < active);
  const pool = below.length > 0 ? below : recallable;
  return pool.reduce((acc, v) => (v.versionNo > acc.versionNo ? v : acc));
}

// Geri alınabilir mi (FR-AGT-006): bir aktif sürüm var + geri çağrılabilir (önceki yayınlanmış) sürüm var.
export function canRollback(history: AgentVersionHistory): boolean {
  return history.activeVersionNo !== null && recallableVersions(history).length > 0;
}

// Bekleyen değişiklik var mı (FR-AGT-004): aktif sürümden DAHA YENİ bir sürüm var (henüz canlıda değil).
export function hasPendingChanges(history: AgentVersionHistory): boolean {
  const latest = latestVersion(history);
  if (latest === null) return false;
  if (history.activeVersionNo === null) return true; // hiç yayınlanmamış → bekleyen
  return latest.versionNo > history.activeVersionNo;
}

// Testte BAŞARISIZ sürümler (FR-AGT-010; arşivlenmemiş — dikkat gerektirir).
export function failedTestVersions(history: AgentVersionHistory): AgentVersion[] {
  return history.versions.filter((v) => v.stage !== "archived" && v.testStatus === "failed");
}

// ── bütünlük / WORM invariant'ları ───────────────────────────────────────────────

// Yinelenen versionNo (DB UNIQUE(tenant,agent,version_no) ihlali).
export function duplicateVersionNos(history: AgentVersionHistory): number[] {
  const seen = new Set<number>();
  const dup = new Set<number>();
  for (const v of history.versions) {
    if (seen.has(v.versionNo)) dup.add(v.versionNo);
    seen.add(v.versionNo);
  }
  return [...dup].sort((a, b) => a - b);
}

// Yinelenen versionId (ayırt edilebilirlik ihlali).
export function duplicateVersionIds(history: AgentVersionHistory): string[] {
  const seen = new Set<string>();
  const dup = new Set<string>();
  for (const v of history.versions) {
    if (seen.has(v.versionId)) dup.add(v.versionId);
    seen.add(v.versionId);
  }
  return [...dup].sort();
}

// Her sürüm ayırt edilebilir mi (versionNo + versionId benzersiz).
export function distinguishable(history: AgentVersionHistory): boolean {
  return duplicateVersionNos(history).length === 0 && duplicateVersionIds(history).length === 0;
}

// Bütünlük: activeVersionNo işaret ediyor ama eşleşen sürüm YOK (kopuk referans).
export function missingActiveVersion(history: AgentVersionHistory): boolean {
  return history.activeVersionNo !== null && versionByNo(history, history.activeVersionNo) === undefined;
}

// WORM/rollback köken bütünlüğü: her rollbackOfNo, MEVCUT ve DAHA DÜŞÜK numaralı bir sürümü işaret etmeli
// (append-only — geri alma yalnız önceki bir yayınlanmış sürümü geri yükler; DB §6.5 / FR-AGT-006).
export function rollbackRefsResolve(history: AgentVersionHistory): boolean {
  return history.versions.every((v) => {
    if (v.rollbackOfNo === null) return true;
    if (v.rollbackOfNo >= v.versionNo) return false; // ileriye/kendine rollback olamaz (append-only)
    return versionByNo(history, v.rollbackOfNo) !== undefined;
  });
}

// Açık dikkat sayısı: bütünlük ihlalleri + başarısız test.
export function openAttentionCount(history: AgentVersionHistory): number {
  return (
    duplicateVersionNos(history).length +
    duplicateVersionIds(history).length +
    (missingActiveVersion(history) ? 1 : 0) +
    (rollbackRefsResolve(history) ? 0 : 1) +
    failedTestVersions(history).length
  );
}

// ── ton (renk) eşlemeleri ─────────────────────────────────────────────────────────

const STAGE_TONE: Record<VersionStage, StatusTone> = {
  draft: "neutral",
  test: "info",
  staging: "warning",
  production: "success",
  archived: "neutral",
};
export function stageTone(s: VersionStage): StatusTone {
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

// ── HİJYEN + GÜVENLİK koruması (İKİ KATMAN) ─────────────────────────────────────────
// Katman 1 — YAPISAL anahtar guard: son-müşteri ham iş içeriği/PII + agent_version snapshot JSONB GÖVDESİ +
// sır/credential/nesne-depo URI çağrıştıran ALAN ADI bulunursa hata fırlatır. A-17 yalnız SÜRÜM META gösterir
// (sürüm no/kimliği/aşama/durum/test/yayınlayan/zaman/değişiklik notu/bağlanan config AD/SAYISI) — ham transkript/
// ses kaydı/ham numara/müşteri PII + snapshot GÖVDESİ DEĞİL (BRD §17.7 + NFR 10.6).
export const FORBIDDEN_PII_KEYS: readonly string[] = [
  "transcript",
  "transcripttext",
  "rawtext",
  "utterance",
  "recording",
  "recordingurl",
  "recordingbytes",
  "audio",
  "audiobytes",
  "summary",
  "e164",
  "frome164",
  "toe164",
  "msisdn",
  "phonenumber",
  "callerid",
  "callernumber",
  "calleenumber",
  "customer",
  "customername",
  "contact",
  "contactname",
  "email",
  "dob",
  "birthdate",
  "cdr",
  "cardpan",
  "pan",
  "cvv",
  "otp",
  "ssn",
  "iban",
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
  "snapshot", // DB §5.2 agent_version.snapshot — config GÖVDESİ panele konmaz (yalnız sürüm/profil AD/SAYISI)
  "prompttext", // prompt GÖVDESİ A-06'da bile gömülmez; A-17 yalnız sürüm AD'ı taşır
  "promptbody",
  "flowdefinition",
  "flowbody",
  "body",
  "storageuri", // nesne-depo pointer — gömülmez
  "storageurl",
  "objecturi",
  "objectkey",
  "signedurl",
  "downloadurl",
  "url",
  "baseurl",
  "uri",
  "bucket",
];

// Katman 2 — İÇERİK redaction desenleri: maskesiz ham PII izi. STRING değerler taranır (sayılar değil — sürüm no/
// boyut büyüklüğü redaction'ı tetiklemez).
export const RAW_PII_PATTERNS: readonly RegExp[] = [
  /\d{7,}/, // ≥7 ardışık rakam: telefon/kart/poliçe/hesap numarası
  /\+\d{6,}/, // +90... biçimli ham telefon
  /\d{4}[\s-]\d{4}[\s-]\d{4}/, // kart bloğu (4-4-4...)
  /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/, // e-posta
  /\bTR\d{2}[\s]?\d/, // IBAN (TR + 2 rakam)
];

// YAPISAL anahtar guard: yasak alan ADI bulursa hata fırlatır.
export function assertNoForbiddenKeys(node: unknown, path = "$"): void {
  if (node && typeof node === "object") {
    if (Array.isArray(node)) {
      node.forEach((v, i) => assertNoForbiddenKeys(v, `${path}[${i}]`));
      return;
    }
    for (const k of Object.keys(node as Record<string, unknown>)) {
      if (k.startsWith("$")) continue; // sample meta ($comment/$expect) hariç
      const lower = k.toLowerCase();
      if (FORBIDDEN_PII_KEYS.includes(lower)) {
        throw new Error(`A-17 HİJYEN ihlali: yasak PII/iş-içeriği alanı "${path}.${k}" (BRD §17.7 / FR-REC-004/005)`);
      }
      if (FORBIDDEN_SECRET_KEYS.includes(lower)) {
        throw new Error(`A-17 GÜVENLİK ihlali: sır/credential/snapshot-gövdesi/nesne-depo URI alanı "${path}.${k}" panele konmaz (NFR 10.6)`);
      }
      assertNoForbiddenKeys((node as Record<string, unknown>)[k], `${path}.${k}`);
    }
  }
}

// İÇERİK redaction guard: herhangi bir string değerde ham PII DESENİ bulursa hata fırlatır (FR-REC-004/005).
export function assertRedactionClean(node: unknown, path = "$"): void {
  if (typeof node === "string") {
    for (const re of RAW_PII_PATTERNS) {
      if (re.test(node)) {
        throw new Error(`A-17 REDACTION ihlali: maskesiz ham PII deseni "${path}" (FR-REC-004/005; sürüm META panosunda ham PII bulunamaz)`);
      }
    }
    return;
  }
  if (node && typeof node === "object") {
    if (Array.isArray(node)) {
      node.forEach((v, i) => assertRedactionClean(v, `${path}[${i}]`));
      return;
    }
    for (const k of Object.keys(node as Record<string, unknown>)) {
      if (k.startsWith("$")) continue; // sample meta ($comment/$expect) hariç
      assertRedactionClean((node as Record<string, unknown>)[k], `${path}.${k}`);
    }
  }
}

// İki katmanı birlikte uygular (HİJYEN + GÜVENLİK + REDACTION).
export function assertSafe(view: unknown): void {
  assertNoForbiddenKeys(view);
  assertRedactionClean(view);
}

// ── veri SEAM (yer tutucu) ───────────────────────────────────────────────────────
// Deterministik yer tutucu: tek-tenant agent sürüm geçmişi (SÜRÜM META yalnız — ham içerik/PII/sır/snapshot
// gövdesi DEĞİL). Gerçek implementasyon (F1 §14.1) Agent Registry (DB §5.2 `agent_version` +
// `agent.active_version_id`) tenant-scope (RLS) beslenir. Bu örnek: v6 aktif (production); v7 test'i geçen
// bekleyen sürüm; v5/v4/v3 önceki yayınlanmış (geri çağrılabilir → rollback hedefleri, varsayılan v5); v4 bir
// rollback ürünü (v2'yi geri yükledi — WORM append-only DB §6.5); v2/v1 arşiv taslak. Her sürüm ayırt edilebilir.
const PLACEHOLDER_VIEW: AgentVersionView = {
  generatedAt: "2026-06-18T09:00:00.000Z",
  tenantRef: "TEN-2048",
  tenantName: "Kuzey Sigorta A.Ş.",
  agent: {
    agentRef: "AGT-117",
    agentName: "Poliçe Yenileme Asistanı",
    lifecycleState: "production",
    activeVersionNo: 6,
    versions: [
      { versionNo: 7, versionId: "AV-7f1a", stage: "test", isPublished: false, testStatus: "passed", publishedBy: "Derya Kaya", publishedAt: "2026-06-17T14:20:00.000Z", changeNote: "İade politikası adımı eklendi", rollbackOfNo: null, promptVersionNo: 8, flowVersionNo: 4, voiceProfile: "tr-Premium-Kadın", modelProfile: "Büyük tier (kalite)", sttProfile: "tr-8kHz-telefon" },
      { versionNo: 6, versionId: "AV-6c2b", stage: "production", isPublished: true, testStatus: "passed", publishedBy: "Derya Kaya", publishedAt: "2026-06-10T09:05:00.000Z", changeNote: "Karşılama ve yapay zekâ bildirimi netleştirildi", rollbackOfNo: null, promptVersionNo: 7, flowVersionNo: 4, voiceProfile: "tr-Premium-Kadın", modelProfile: "Büyük tier (kalite)", sttProfile: "tr-8kHz-telefon" },
      { versionNo: 5, versionId: "AV-5a9d", stage: "archived", isPublished: true, testStatus: "passed", publishedBy: "Mert Aydın", publishedAt: "2026-05-28T16:40:00.000Z", changeNote: "Model tier küçük→büyük güncellendi", rollbackOfNo: null, promptVersionNo: 6, flowVersionNo: 3, voiceProfile: "tr-Premium-Kadın", modelProfile: "Büyük tier (kalite)", sttProfile: "tr-8kHz-telefon" },
      { versionNo: 4, versionId: "AV-4b7e", stage: "archived", isPublished: true, testStatus: "passed", publishedBy: "Mert Aydın", publishedAt: "2026-05-12T11:15:00.000Z", changeNote: "v2 yapılandırmasına geri alındı (regresyon sonrası)", rollbackOfNo: 2, promptVersionNo: 4, flowVersionNo: 2, voiceProfile: "tr-Standart-Kadın", modelProfile: "Küçük tier (hız)", sttProfile: "tr-8kHz-telefon" },
      { versionNo: 3, versionId: "AV-3d4c", stage: "archived", isPublished: true, testStatus: "passed", publishedBy: "Derya Kaya", publishedAt: "2026-04-30T08:00:00.000Z", changeNote: "Flow tabanlı modele geçildi", rollbackOfNo: null, promptVersionNo: 5, flowVersionNo: 3, voiceProfile: "tr-Standart-Kadın", modelProfile: "Küçük tier (hız)", sttProfile: "tr-8kHz-telefon" },
      { versionNo: 2, versionId: "AV-2e8f", stage: "archived", isPublished: false, testStatus: "passed", publishedBy: "Derya Kaya", publishedAt: "2026-04-22T10:30:00.000Z", changeNote: "İlk taslak revizyonu", rollbackOfNo: null, promptVersionNo: 2, flowVersionNo: null, voiceProfile: "tr-Standart-Kadın", modelProfile: "Küçük tier (hız)", sttProfile: "tr-8kHz-telefon" },
      { versionNo: 1, versionId: "AV-1a3b", stage: "archived", isPublished: false, testStatus: "not_run", publishedBy: "Derya Kaya", publishedAt: "2026-04-15T13:00:00.000Z", changeNote: "İlk sürüm", rollbackOfNo: null, promptVersionNo: 1, flowVersionNo: null, voiceProfile: "tr-Standart-Kadın", modelProfile: "Küçük tier (hız)", sttProfile: "tr-8kHz-telefon" },
    ],
  },
};

export async function getAgentVersionView(): Promise<AgentVersionView> {
  const view = PLACEHOLDER_VIEW;
  assertSafe(view); // HİJYEN + GÜVENLİK + REDACTION: yapısal PII/sır/snapshot-gövdesi/URI yok + içerik maskesiz ham PII deseni yok
  return view;
}
