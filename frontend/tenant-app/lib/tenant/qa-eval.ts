// WBS 13.4.13 — A-13 "QA Değerlendirme" veri katmanı (seam) + SAF türetme yardımcıları
// (L2 — Operasyon / Uygulama Paneli).
//
// ÇEKİRDEK İLKELER:
//  - İÇERİK (BRD §17.5 A-13 "QA Değerlendirme — Otomatik + manuel kalite skorlama"): TEK bir çağrının KALİTE
//    DEĞERLENDİRMESİ. A-12 (Çağrı Detayı) zaman çizelgesi + transkript içeriğini gösterirken, A-13 o çağrının
//    (a) OTOMATİK SKORKARTI (FR-ANA-001 — tüm çağrılar otomatik kalite değerlendirmesine alınır; ağırlıklı
//    boyut skorları compliance/accuracy/resolution/tooling/communication/safety), (b) KRİTİK İŞARETLER
//    (FR-ANA-004 yanlış bilgi/tool hatası/güvenlik ihlali + FR-ANA-008 kritik konuşma otomatik işaretleme),
//    (c) MANUEL DEĞERLENDİRME (FR-ANA-009 — QA ekibi skor + açıklama ekler; otomatik↔manuel kalibrasyon) ve
//    (d) SÜRÜM KARŞILAŞTIRMASI (FR-ANA-010 — agent sürümleri arası performans) görünümünü sunar.
//  - METRİK/SKOR = TIER A (BRD §17.7): A-13 yalnız TÜRETİLMİŞ skor + yapısal işaret + (redaction'lı) QA açıklaması
//    gösterir; transkript İÇERİĞİNİ taşımaz (içerik A-12'de, içerik kapısı + audit'le). İşaret KANITI yapısaldır
//    (tur VEKİL referansı turnRef — ham metin DEĞİL). QA açıklaması (`comment`/`note`) YAZAR tarafından girilir ve
//    redaction'lı tutulur (ham PII deseni içeremez — FR-REC-004/005).
//  - SKORLAMA = DERİN AKSİYON (FR-ANA-009): A-13 manuel skor/açıklama YAZIMINI tetikleyebilir (qa:score) AMA
//    nihai işlem + yetki + audit backend'de (API §8.1 GET/POST /calls/{id}/evaluations). Panel yalnız görsel kapı.
//  - ERİŞİM AUDIT (FR-REC-009): QA çağrı içeriğine eriştiğinde (transkript/kayıt — A-12) erişim audit edilir;
//    A-13 bu sağlık sinyalini yansıtır (accessAudited). Auditsiz erişim danger (accessBlocked).
//  - HİJYEN — İKİ KATMAN (BRD §17.7 + FR-REC-004/005 + NFR 10.6):
//      (1) YAPISAL anahtar guard (assertNoForbiddenKeys): ham kimlik/iş-içeriği (ham ses/ham transkript blob/
//          transkript metni/e164/müşteri/kart-OTP/çağrı özeti) + sır/credential + nesne-depo URI alan ADI taşınamaz.
//          NOT: A-13 transkript metni GÖSTERMEZ → `text`/`transcripttext` YASAK (A-12'den farkı: A-12 `text` izinli).
//      (2) İÇERİK redaction guard (assertRedactionClean): TÜM string değerleri (özellikle QA `comment`/`note`)
//          ham PII DESENİ (≥7 rakam/e-posta/+rakam/kart-bloğu/IBAN) için taranır; maskeli içerik yalnız MASK_TOKEN.
//  - TUTARLILIK (test edilebilirlik): otomatik genel skor SAKLANAN değil TÜRETİLEBİLİR olmalı — autoScore ≈
//    ağırlıklı boyut skoru (autoScoreConsistent); critical bayrağı ≈ kritik-şiddetli işaret varlığı (criticalConsistent).
//    Bu invariant'lar FR-ANA-001/008'i deterministik test eder.
//  - TENANT-SCOPE (FR-TEN-002): A-13 yalnız oturum açan tenant'ın KENDİ çağrısı. Scope middleware (13.1.2) + RLS.
//  - VENDOR-NEUTRAL (ADR-002): veri kaynağı bir SEAM'dir; gerçek implementasyon (F1 §14.1) QA/Analitik motoru
//    (otomatik değerlendirme + kritik işaretleme) + evaluation store (DB tenant-scope RLS) çıktısıyla beslenir.
//  - SAF/DETERMİNİSTİK: türetmeler Date.now/rastgelelik içermez → birim-test + Python aynası
//    (screens/a13-qa-eval/a13_qa_eval_probe.py).
//  - İŞ MANTIĞI/AUTHZ YOK (SAD §14.4.1): skor/açıklama YAZIMI + erişim-audit YAZIMI YOK; nihai yetki + işlem +
//    audit backend'de (API §8.1) + RLS. Panel yalnız çözümlenmiş değerlendirmeyi (redaction'lı) gösterir.
//  - RBAC (BRD §17.6 — L2 A-13 satırı): operations_manager=Yönet · conversation_designer=Görüntüle ·
//    qa_analyst=Yönet · human_agent=— (erişim yok). Permission-key: qa:score (API §8.1) + calls:read (çağrı META).

// Çağrı yönü (DB §19 call.direction).
export type CallDirection = "inbound" | "outbound";
// Çağrı sonucu/outcome (FR-ANA-002/003 + FR-OUT-008 voicemail).
export type CallOutcome = "contained" | "transferred" | "abandoned" | "voicemail" | "failed";

// Otomatik skorkart boyutu (FR-ANA-001 — kalite değerlendirme ekseni).
export type DimensionKey =
  | "compliance" // AI bildirimi/consent/disclosure (BRD §14.2)
  | "accuracy" // bilgi doğruluğu (FR-ANA-004 yanlış bilgi)
  | "resolution" // çözüm/containment (FR-ANA-002/003)
  | "tooling" // tool/API başarısı (FR-ANA-004 tool hatası)
  | "communication" // anlaşılırlık/empati/akış
  | "safety"; // PII/güvenlik (FR-ANA-004 güvenlik ihlali)

// Kritik işaret tipi (FR-ANA-004 + FR-ANA-008).
export type FlagType =
  | "misinformation" // yanlış bilgi verildi (FR-ANA-004)
  | "tool_error" // tool/API hatası (FR-ANA-004)
  | "security_violation" // güvenlik ihlali (FR-ANA-004)
  | "pii_exposure" // PII sızıntısı (FR-REC-004/005 ihlali)
  | "escalation_missed" // gerekli insan aktarımı yapılmadı (FR-HND)
  | "compliance_gap" // AI bildirimi/consent eksik (BRD §14.2)
  | "low_confidence"; // yoğun düşük STT güveni (BRD §15)

// İşaret şiddeti.
export type FlagSeverity = "critical" | "high" | "medium" | "info";
// Manuel değerlendirme yaşam döngüsü (FR-ANA-009).
export type ReviewStatus = "pending" | "in_review" | "scored";
// Manuel QA disposition (skorlama sonucu).
export type Disposition = "approved" | "coaching" | "failed" | "escalated";
// Skor bandı (eşiklerden türetilir).
export type ScoreBand = "pass" | "borderline" | "fail";

export type StatusTone = "success" | "warning" | "danger" | "neutral" | "info";

// Boyut işaret eşiği (bunun altı boyut "zayıf" sayılır — gözden geçirme adayı).
export const DIMENSION_FLAG_THRESHOLD = 0.7;
// Otomatik genel skor band eşikleri (≥pass=pass · ≥fail=borderline · <fail=fail).
export const DEFAULT_THRESHOLDS = { pass: 0.85, fail: 0.6 } as const;
// Kalibrasyon toleransı (otomatik↔manuel skor farkı bu kadar ise "uyumlu" — FR-ANA-009).
export const CALIBRATION_TOLERANCE = 0.1;
// autoScore ↔ ağırlıklı boyut skoru tutarlılık toleransı (yuvarlama payı).
export const AUTO_SCORE_TOLERANCE = 0.02;
// Maskeleme jetonu (redaction sonrası gösterilen tek güvenli içerik — FR-REC-004/005).
export const MASK_TOKEN = "[•••]";

// Bir skorkart boyutu (FR-ANA-001 — otomatik).
export interface ScoreDimension {
  key: DimensionKey;
  score: number; // 0..1 otomatik skor
  weight: number; // 0..1 genel skordaki ağırlık (toplam ≈ 1)
}

// Bir kritik işaret (FR-ANA-004/008; yalnız YAPISAL — ham içerik DEĞİL).
export interface QaFlag {
  flagRef: string; // işaret VEKİL kimliği
  type: FlagType; // FR-ANA-004/008
  severity: FlagSeverity;
  auto: boolean; // otomatik tespit (FR-ANA-008) mı, manuel mi
  turnRef?: string; // İSTEĞE BAĞLI yapısal kanıt referansı (tur VEKİLİ — ham metin DEĞİL)
  resolved: boolean; // QA tarafından kapatıldı/onaylandı mı
  note?: string; // İSTEĞE BAĞLI redaction'lı yapısal not (ham PII içermez)
}

// Manuel değerlendirme (FR-ANA-009 — QA ekibi skor + açıklama).
export interface ManualReview {
  status: ReviewStatus; // pending | in_review | scored
  score?: number; // 0..1 manuel skor (yalnız scored)
  reviewerRef?: string; // değerlendiren VEKİL kimliği (ad/PII DEĞİL)
  disposition?: Disposition; // skorlama sonucu
  comment?: string; // REDACTION'LI QA açıklaması (ham PII yok — FR-ANA-009)
  scoredAt?: string; // ISO-8601 (sabit yer tutucu — SSR-stabil; Date.now YOK)
}

// Sürüm karşılaştırması (FR-ANA-010 — agent sürümleri arası performans).
export interface VersionBenchmark {
  agentAvgScore: number; // agent'ın tüm sürüm ortalaması
  versionAvgScore: number; // bu sürümün ortalaması
  sampleSize: number; // bu sürümdeki değerlendirilmiş çağrı sayısı
}

// Tek çağrının QA değerlendirmesi (A-13 çekirdeği).
export interface QaEvaluation {
  callRef: string; // çağrı VEKİL kimliği (telefon numarası DEĞİL)
  direction: CallDirection;
  agentRef: string;
  agentName: string; // agent adı (tenant config; son-müşteri PII değil)
  agentVersion: string; // değerlendirilen agent sürümü (FR-ANA-010)
  outcome: CallOutcome; // FR-ANA-002/003
  startedAt: string; // ISO-8601 (sabit yer tutucu)
  durationSec: number;
  autoScore: number; // 0..1 OTOMATİK genel skor (FR-ANA-001; ≈ ağırlıklı boyut skoru)
  dimensions: ScoreDimension[]; // skorkart boyutları (FR-ANA-001)
  flags: QaFlag[]; // kritik işaretler (FR-ANA-004/008)
  critical: boolean; // FR-ANA-008 kritik konuşma (≈ kritik-şiddetli işaret varlığı)
  review: ManualReview; // FR-ANA-009 manuel değerlendirme
  accessAudited: boolean; // FR-REC-009 (çağrı içeriği erişimi audit'li mi)
}

export interface QaEvaluationView {
  generatedAt: string; // ISO-8601 (sabit yer tutucu — SSR-stabil, Date.now YOK)
  tenantRef: string; // tenant'ın KENDİ kimliği (L2'de izinli)
  tenantName: string; // tenant org adı (izinli; son-müşteri verisi DEĞİL)
  thresholds: { pass: number; fail: number }; // band eşikleri
  evaluation: QaEvaluation; // seçilen çağrının değerlendirmesi (tenant-scope FR-TEN-002)
  benchmark: VersionBenchmark; // FR-ANA-010 sürüm karşılaştırması
}

// Görüntüleme sıraları.
export const DIRECTION_ORDER: CallDirection[] = ["inbound", "outbound"];
export const OUTCOME_ORDER: CallOutcome[] = ["contained", "transferred", "abandoned", "voicemail", "failed"];
export const DIMENSION_ORDER: DimensionKey[] = ["compliance", "accuracy", "resolution", "tooling", "communication", "safety"];
export const FLAG_ORDER: FlagType[] = ["misinformation", "tool_error", "security_violation", "pii_exposure", "escalation_missed", "compliance_gap", "low_confidence"];
export const SEVERITY_ORDER: FlagSeverity[] = ["critical", "high", "medium", "info"];
export const REVIEW_ORDER: ReviewStatus[] = ["pending", "in_review", "scored"];
export const DISPOSITION_ORDER: Disposition[] = ["approved", "coaching", "failed", "escalated"];
export const BAND_ORDER: ScoreBand[] = ["pass", "borderline", "fail"];

// Şiddet sıralama rütbesi (kritik en üstte — deterministik sıralama).
const SEVERITY_RANK: Record<FlagSeverity, number> = { critical: 0, high: 1, medium: 2, info: 3 };

// ── saf türetme yardımcıları ────────────────────────────────────────────────────

// Boyutları DIMENSION_ORDER'a göre sırala (deterministik).
export function sortedDimensions(ev: QaEvaluation): ScoreDimension[] {
  return [...ev.dimensions].sort((a, b) => DIMENSION_ORDER.indexOf(a.key) - DIMENSION_ORDER.indexOf(b.key));
}

// İşaretleri şiddete göre (kritik→info), eşitlikte flagRef ASC sırala (deterministik).
export function sortedFlags(ev: QaEvaluation): QaFlag[] {
  return [...ev.flags].sort((a, b) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity] || a.flagRef.localeCompare(b.flagRef));
}

// Ağırlıklı otomatik genel skor: Σ(score·weight)/Σweight (FR-ANA-001). Σweight=0 ise 0.
export function weightedAutoScore(dimensions: ScoreDimension[]): number {
  const wsum = dimensions.reduce((a, d) => a + d.weight, 0);
  if (wsum <= 0) return 0;
  return dimensions.reduce((a, d) => a + d.score * d.weight, 0) / wsum;
}

// Boyut ağırlıkları toplamı (≈1 beklenir — invariant doğrulaması için).
export function weightSum(dimensions: ScoreDimension[]): number {
  return dimensions.reduce((a, d) => a + d.weight, 0);
}

// SAKLANAN autoScore ≈ TÜRETİLEN ağırlıklı skor mu (FR-ANA-001 tutarlılık invariant'ı).
export function autoScoreConsistent(ev: QaEvaluation, tol = AUTO_SCORE_TOLERANCE): boolean {
  return Math.abs(ev.autoScore - weightedAutoScore(ev.dimensions)) <= tol;
}

// Skor bandı (eşiklerden türetilir): ≥pass=pass · ≥fail=borderline · <fail=fail.
export function scoreBand(score: number, thresholds: { pass: number; fail: number }): ScoreBand {
  if (score >= thresholds.pass) return "pass";
  if (score >= thresholds.fail) return "borderline";
  return "fail";
}

// Eşik altı (zayıf) boyutlar — gözden geçirme adayı.
export function flaggedDimensions(dimensions: ScoreDimension[], threshold = DIMENSION_FLAG_THRESHOLD): ScoreDimension[] {
  return dimensions.filter((d) => d.score < threshold);
}

// Kritik-şiddetli işaretler (FR-ANA-004/008).
export function criticalFlags(flags: QaFlag[]): QaFlag[] {
  return flags.filter((f) => f.severity === "critical");
}
// Açık (kapatılmamış) işaretler.
export function openFlags(flags: QaFlag[]): QaFlag[] {
  return flags.filter((f) => !f.resolved);
}
// Açık kritik işaretler (FR-ANA-008 — manuel incelemeyi zorunlu kılan).
export function openCriticalFlags(flags: QaFlag[]): QaFlag[] {
  return flags.filter((f) => f.severity === "critical" && !f.resolved);
}
// Otomatik tespit edilen işaretler (FR-ANA-008).
export function autoFlags(flags: QaFlag[]): QaFlag[] {
  return flags.filter((f) => f.auto);
}

// İşaret tipi başına sayı (tüm tipler 0'dan başlatılır — FR-ANA-004).
export function countByFlagType(flags: QaFlag[]): Record<FlagType, number> {
  const acc = {} as Record<FlagType, number>;
  for (const t of FLAG_ORDER) acc[t] = 0;
  for (const f of flags) acc[f.type] += 1;
  return acc;
}
// Şiddet başına sayı (tüm şiddetler 0'dan başlatılır).
export function countBySeverity(flags: QaFlag[]): Record<FlagSeverity, number> {
  const acc = {} as Record<FlagSeverity, number>;
  for (const s of SEVERITY_ORDER) acc[s] = 0;
  for (const f of flags) acc[f.severity] += 1;
  return acc;
}

// SAKLANAN critical bayrağı ≈ kritik-şiddetli işaret varlığı (FR-ANA-008 tutarlılık invariant'ı).
export function criticalConsistent(ev: QaEvaluation): boolean {
  return ev.critical === criticalFlags(ev.flags).length > 0;
}

// MANUEL inceleme ZORUNLU mu (FR-ANA-008): kritik konuşma VEYA açık kritik işaret VEYA otomatik skor fail bandı.
export function needsReview(ev: QaEvaluation, thresholds: { pass: number; fail: number } = DEFAULT_THRESHOLDS): boolean {
  return ev.critical || openCriticalFlags(ev.flags).length > 0 || scoreBand(ev.autoScore, thresholds) === "fail";
}
// Manuel inceleme TAMAM mı (FR-ANA-009 — skor girilmiş).
export function reviewComplete(ev: QaEvaluation): boolean {
  return ev.review.status === "scored" && typeof ev.review.score === "number";
}
// Manuel inceleme BEKLEMEDE mi.
export function reviewPending(ev: QaEvaluation): boolean {
  return ev.review.status === "pending" || ev.review.status === "in_review";
}

// Otomatik↔manuel kalibrasyon farkı (yalnız skorlanmışsa; aksi halde null — FR-ANA-009).
export function calibrationDelta(ev: QaEvaluation): number | null {
  if (!reviewComplete(ev) || typeof ev.review.score !== "number") return null;
  return Math.abs(ev.autoScore - ev.review.score);
}
// Otomatik↔manuel UYUMLU mu (fark ≤ tolerans; skorlanmamışsa null — FR-ANA-009).
export function calibrationAgreement(ev: QaEvaluation, tol = CALIBRATION_TOLERANCE): boolean | null {
  const d = calibrationDelta(ev);
  return d === null ? null : d <= tol;
}

// ERİŞİM ENGELLİ (FR-REC-009 ihlali — danger): çağrı içeriği erişimi audit'siz.
export function accessBlocked(ev: QaEvaluation): boolean {
  return !ev.accessAudited;
}

// Sürüm performans deltası (FR-ANA-010): bu sürüm − agent ortalaması (+iyileşme / −gerileme).
export function versionDelta(b: VersionBenchmark): number {
  return b.versionAvgScore - b.agentAvgScore;
}

// ── ton (renk) eşlemeleri ─────────────────────────────────────────────────────────

const DIRECTION_TONE: Record<CallDirection, StatusTone> = { inbound: "neutral", outbound: "info" };
export function directionTone(d: CallDirection): StatusTone {
  return DIRECTION_TONE[d];
}

const OUTCOME_TONE: Record<CallOutcome, StatusTone> = {
  contained: "success",
  transferred: "info",
  abandoned: "warning",
  voicemail: "neutral",
  failed: "danger",
};
export function outcomeTone(o: CallOutcome): StatusTone {
  return OUTCOME_TONE[o];
}

// Skor bandı tonu.
const BAND_TONE: Record<ScoreBand, StatusTone> = { pass: "success", borderline: "warning", fail: "danger" };
export function bandTone(b: ScoreBand): StatusTone {
  return BAND_TONE[b];
}
// Bir skoru doğrudan tona çevir (band üzerinden).
export function scoreTone(score: number, thresholds: { pass: number; fail: number } = DEFAULT_THRESHOLDS): StatusTone {
  return bandTone(scoreBand(score, thresholds));
}

const SEVERITY_TONE: Record<FlagSeverity, StatusTone> = { critical: "danger", high: "warning", medium: "warning", info: "info" };
export function severityTone(s: FlagSeverity): StatusTone {
  return SEVERITY_TONE[s];
}

const REVIEW_TONE: Record<ReviewStatus, StatusTone> = { pending: "warning", in_review: "info", scored: "success" };
export function reviewTone(s: ReviewStatus): StatusTone {
  return REVIEW_TONE[s];
}

const DISPOSITION_TONE: Record<Disposition, StatusTone> = { approved: "success", coaching: "warning", failed: "danger", escalated: "warning" };
export function dispositionTone(d: Disposition): StatusTone {
  return DISPOSITION_TONE[d];
}

// ── HİJYEN + GÜVENLİK koruması (İKİ KATMAN) ─────────────────────────────────────────
// Katman 1 — YAPISAL anahtar guard: ham kimlik/iş-içeriği + sır/credential + nesne-depo URI çağrıştıran ALAN ADI
// bulunursa hata fırlatır. A-13 transkript metni GÖSTERMEZ → `text`/`transcripttext`/`rawtext` YASAK (A-12'den
// farkı: A-12 redaction'lı tur `text`ini gösterdiği için izin veriyordu; A-13 yalnız skor/işaret/açıklama gösterir).
export const FORBIDDEN_PII_KEYS: readonly string[] = [
  "text", // tur/ifade metni — A-13 transkript İÇERİĞİ göstermez (yalnız skor/işaret/açıklama)
  "transcripttext",
  "rawtext",
  "transcript",
  "utterance",
  "recording", // ham ses kaydı
  "recordingbytes",
  "audio",
  "audiobytes",
  "summary", // çağrı özeti (DB §21 transcript.summary)
  "e164",
  "frome164",
  "toe164",
  "fromnumber",
  "tonumber",
  "msisdn",
  "phonenumber",
  "callerid",
  "callernumber",
  "calleenumber",
  "customer",
  "customername",
  "reviewername", // değerlendiren ADI — yalnız reviewerRef (vekil) izinli
  "contact",
  "contactname",
  "email",
  "dob",
  "birthdate",
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
  "token",
  "bearertoken",
  "accesstoken",
  "credential",
  "password",
  "privatekey",
  "kmskey",
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

// Katman 2 — İÇERİK redaction desenleri: maskesiz ham PII izi. QA `comment`/`note` yazar girdisidir ve
// redaction'lı tutulur; bu desenler hiçbir string değerde GÖRÜNMEMELİDİR (FR-REC-004/005).
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
        throw new Error(`A-13 HİJYEN ihlali: yasak PII/iş-içeriği alanı "${path}.${k}" (BRD §17.7 / FR-REC-004/005)`);
      }
      if (FORBIDDEN_SECRET_KEYS.includes(lower)) {
        throw new Error(`A-13 GÜVENLİK ihlali: sır/credential/nesne-depo URI alanı "${path}.${k}" panele konmaz (NFR 10.6)`);
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
        throw new Error(`A-13 REDACTION ihlali: maskesiz ham PII deseni "${path}" (FR-REC-004/005; QA açıklaması redaction'lı tutulur)`);
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
// Deterministik yer tutucu: TEK çağrı QA değerlendirmesi (otomatik skorkart + kritik işaret + manuel inceleme +
// sürüm karşılaştırması). Gerçek implementasyon (F1 §14.1) QA/Analitik motoru (FR-ANA-001 otomatik değerlendirme +
// FR-ANA-004/008 kritik işaretleme) + evaluation store (DB tenant-scope RLS) çıktısıyla beslenir; routing
// /workspace/qa/[callRef] F1 kapsamı. Bu örnek: sağlıklı, kalibre edilmiş bir inbound çağrı (otomatik yüksek skor +
// 1 info işaret + manuel skor uyumlu). PII yalnız maskeli; transkript metni YOK (içerik A-12'de).
const PLACEHOLDER_VIEW: QaEvaluationView = {
  generatedAt: "2026-06-18T09:00:00.000Z",
  tenantRef: "TEN-2048",
  tenantName: "Kuzey Sigorta A.Ş.",
  thresholds: { pass: DEFAULT_THRESHOLDS.pass, fail: DEFAULT_THRESHOLDS.fail },
  evaluation: {
    callRef: "CALL-1006",
    direction: "inbound",
    agentRef: "AGT-117",
    agentName: "Sigorta Asistanı",
    agentVersion: "v7",
    outcome: "contained",
    startedAt: "2026-06-18T08:55:00.000Z",
    durationSec: 214,
    autoScore: 0.92,
    dimensions: [
      { key: "compliance", score: 0.95, weight: 0.2 },
      { key: "accuracy", score: 0.92, weight: 0.2 },
      { key: "resolution", score: 0.9, weight: 0.2 },
      { key: "tooling", score: 0.88, weight: 0.15 },
      { key: "communication", score: 0.9, weight: 0.1 },
      { key: "safety", score: 0.94, weight: 0.15 },
    ],
    flags: [
      { flagRef: "FL-01", type: "low_confidence", severity: "info", auto: true, turnRef: "T-04", resolved: false, note: "kimlik doğrulama turunda STT güveni eşik altı" },
    ],
    critical: false,
    review: {
      status: "scored",
      score: 0.88,
      reviewerRef: "USR-QA-009",
      disposition: "approved",
      comment: "Karşılama ve KVKK bildirimi eksiksiz; kimlik doğrulama akıcı, kart bilgisi istenmedi. Düşük güven turu manuel teyit edildi, sorun yok.",
      scoredAt: "2026-06-18T10:15:00.000Z",
    },
    accessAudited: true,
  },
  benchmark: { agentAvgScore: 0.87, versionAvgScore: 0.9, sampleSize: 1240 },
};

export async function getQaEvaluationView(): Promise<QaEvaluationView> {
  const view = PLACEHOLDER_VIEW;
  assertSafe(view); // HİJYEN + GÜVENLİK + REDACTION: yapısal PII/sır/URI yok + içerik maskesiz ham PII deseni yok
  return view;
}
