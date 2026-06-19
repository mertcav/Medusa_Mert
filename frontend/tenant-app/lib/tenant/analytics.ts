// WBS 13.4.14 — A-14 "Analytics & Raporlama" veri katmanı (seam) + SAF türetme yardımcıları
// (L2 — Operasyon / Uygulama Paneli).
//
// ÇEKİRDEK İLKELER:
//  - İÇERİK (BRD §17.5 A-14 "Analytics & Raporlama — Containment, CSAT, AHT vb."): bir DÖNEM boyunca, ÇOK ÇAĞRIYI
//    TOPLULAŞTIRAN operasyonel analitik panosu. A-13 (QA Değerlendirme) TEK çağrının skorunu gösterirken, A-14
//    (a) ÖZET KPI'lar (containment / CSAT / AHT / toplam çağrı / transfer oranı), (b) SONUÇ DAĞILIMI (FR-ANA-002
//    outcome/disposition + FR-ANA-003 containment & transfer oranı), (c) KONUŞMA SÜRELERİ (FR-ANA-005 — kullanıcı
//    vs agent konuşma süresi), (d) YANIT GECİKMESİ (FR-ANA-006 — STT/LLM/TTS ve toplam AYRI gösterilir),
//    (e) ZAMAN SERİSİ / TREND (FR-ANA-011 dashboard) ve (f) AGENT SÜRÜMÜ KARŞILAŞTIRMASI (FR-ANA-010) sunar;
//    ham veri export (FR-ANA-011) görsel kapısı içerir.
//  - METRİK = TIER A (BRD §17.7): A-14 yalnız TOPLULAŞTIRILMIŞ metrik gösterir; tek çağrı içeriği/transkript/PII
//    TAŞIMAZ. Topluluk istatistiği son-müşteriyi tanımlamaz; bu yüzden break-glass GEREKMEZ (Tier A).
//  - EXPORT = DERİN AKSİYON (FR-ANA-011): A-14 dashboard + ham veri export'unu TETİKLEYEBİLİR (analytics:read) AMA
//    nihai export + redaction + yetki + audit backend'de (API §8.1 GET /analytics/{report}). Panel yalnız görsel kapı.
//  - HİJYEN — İKİ KATMAN (BRD §17.7 + FR-REC-004/005 + NFR 10.6):
//      (1) YAPISAL anahtar guard (assertNoForbiddenKeys): ham kimlik/iş-içeriği (ham ses/ham transkript blob/
//          transkript metni/e164/müşteri/kart-OTP/çağrı özeti) + sır/credential + nesne-depo URI alan ADI taşınamaz.
//          A-14 topluluk panosudur → tek çağrı `callRef`/`text`/`recording` GÖSTERMEZ (yalnız agregat + agent config).
//      (2) İÇERİK redaction guard (assertRedactionClean): TÜM string değerleri ham PII DESENİ (≥7 rakam/e-posta/
//          +rakam/kart-bloğu/IBAN) için taranır (FR-REC-004/005). Agregat sayılar bile ham PII deseni taşıyamaz.
//  - TUTARLILIK (test edilebilirlik): agregatlar SAKLANAN değil TÜRETİLEBİLİR olmalı —
//    containmentRate = contained/total (FR-ANA-003); Σ outcome oranı ≈ 1 (outcomeRatesSumToOne); Σ outcome sayısı =
//    totalCalls (outcomeCountsConsistent); AHT ≈ toplam konuşma/çağrı (ahtConsistent, FR-ANA-005); Σ seri çağrısı =
//    totalCalls (seriesReconciles, FR-ANA-011). Bu invariant'lar FR-ANA-002/003/005/006/011'i deterministik test eder.
//  - TENANT-SCOPE (FR-TEN-002): A-14 yalnız oturum açan tenant'ın KENDİ agregatı. Scope middleware (13.1.2) + RLS.
//  - VENDOR-NEUTRAL (ADR-002): veri kaynağı bir SEAM'dir; gerçek implementasyon (F1 §14.1) gözlemlenebilirlik
//    omurgası (0.4.7) + analitik/aggregation store (DB tenant-scope RLS) çıktısıyla beslenir.
//  - SAF/DETERMİNİSTİK: türetmeler Date.now/rastgelelik içermez → birim-test + Python aynası
//    (screens/a14-analytics/a14_analytics_probe.py).
//  - İŞ MANTIĞI/AUTHZ YOK (SAD §14.4.1): export YAZIMI + audit YOK; nihai yetki + işlem + audit backend'de
//    (API §8.1) + RLS. Panel yalnız çözümlenmiş agregatı gösterir.
//  - RBAC (BRD §17.6 — L2 A-14 satırı): operations_manager=Yönet · conversation_designer=Görüntüle ·
//    qa_analyst=Görüntüle · human_agent=— (erişim yok). Permission-key: analytics:read (API §8.1).

// Çağrı yönü (DB §19 call.direction).
export type CallDirection = "inbound" | "outbound";
// Çağrı sonucu/outcome (FR-ANA-002/003 + FR-OUT-008 voicemail).
export type CallOutcome = "contained" | "transferred" | "abandoned" | "voicemail" | "failed";
// Yanıt gecikmesi aşaması (FR-ANA-006 — STT/LLM/TTS + toplam AYRI gösterilir).
export type LatencyStage = "stt" | "llm" | "tts" | "total";
// Trend yönü (zaman serisi eğilimi).
export type TrendDir = "up" | "down" | "flat";
// CSAT/oran bandı (eşiklerden türetilir).
export type MetricBand = "good" | "warn" | "bad";

export type StatusTone = "success" | "warning" | "danger" | "neutral" | "info";

// Varsayılan hedef eşikleri (operasyonel SLA — mühendislik varsayılanı).
export const DEFAULT_TARGETS = {
  containment: 0.7, // containment oranı hedefi (FR-ANA-003)
  csat: 0.85, // CSAT hedefi (0..1)
  ahtSec: 240, // ortalama işlem süresi hedefi (sn; düşük daha iyi)
  latencyP95Ms: 1200, // toplam yanıt gecikmesi P95 bütçesi (NFR 10.1; düşük daha iyi)
} as const;
// Oran "iyi/uyarı/kötü" bandı için hedefe göre uyarı çarpanı (hedefin %90'ı altı = kötü).
export const WARN_RATIO = 0.9;
// Toplam oran / agregat tutarlılık toleransı (yuvarlama payı).
export const RATE_TOLERANCE = 0.01;
// AHT ↔ ortalama konuşma süresi tutarlılık toleransı (sn).
export const AHT_TOLERANCE = 5;
// Trend "düz" eşiği (göreli değişim bu altındaysa flat).
export const TREND_FLAT_EPS = 0.02;
// Maskeleme jetonu (redaction sonrası gösterilen tek güvenli içerik — FR-REC-004/005).
export const MASK_TOKEN = "[•••]";

// Sonuç dağılımı kalemi (FR-ANA-002/003).
export interface OutcomeStat {
  outcome: CallOutcome;
  count: number;
}

// Yanıt gecikmesi aşaması istatistiği (FR-ANA-006 — AYRI gösterilir).
export interface LatencyStat {
  stage: LatencyStage;
  p50Ms: number;
  p95Ms: number;
}

// Konuşma süresi dağılımı (FR-ANA-005 — dönem toplamı, sn).
export interface TalkTime {
  userSec: number; // kullanıcı konuşma süresi toplamı
  agentSec: number; // agent konuşma süresi toplamı
  silenceSec: number; // sessizlik/bekleme toplamı
}

// Zaman serisi noktası (günlük agregat — FR-ANA-011 dashboard).
export interface DayPoint {
  date: string; // ISO-8601 tarih (sabit yer tutucu)
  calls: number; // o günkü çağrı sayısı
  contained: number; // o günkü containment sayısı
  csat: number; // o günkü CSAT (0..1)
  ahtSec: number; // o günkü ortalama işlem süresi
}

// Agent sürümü performans kalemi (FR-ANA-010 — sürümler arası karşılaştırma).
export interface VersionStat {
  agentVersion: string;
  calls: number;
  containmentRate: number; // 0..1
  csat: number; // 0..1
  ahtSec: number;
  current: boolean; // aktif/yayında olan sürüm mü
}

// Dönem agregat görünümü (A-14 çekirdeği).
export interface AnalyticsView {
  generatedAt: string; // ISO-8601 (sabit yer tutucu — SSR-stabil, Date.now YOK)
  tenantRef: string; // tenant'ın KENDİ kimliği (L2'de izinli)
  tenantName: string; // tenant org adı (izinli; son-müşteri verisi DEĞİL)
  period: { from: string; to: string; label: string }; // raporlama dönemi
  targets: { containment: number; csat: number; ahtSec: number; latencyP95Ms: number };
  outcomes: OutcomeStat[]; // sonuç dağılımı (FR-ANA-002/003)
  csat: number; // 0..1 dönem CSAT
  csatResponses: number; // CSAT örneklem büyüklüğü
  ahtSec: number; // dönem ortalama işlem süresi
  talk: TalkTime; // konuşma süreleri (FR-ANA-005)
  latency: LatencyStat[]; // yanıt gecikmesi (FR-ANA-006)
  series: DayPoint[]; // zaman serisi (FR-ANA-011)
  versions: VersionStat[]; // agent sürümü karşılaştırması (FR-ANA-010)
}

// Görüntüleme sıraları.
export const DIRECTION_ORDER: CallDirection[] = ["inbound", "outbound"];
export const OUTCOME_ORDER: CallOutcome[] = ["contained", "transferred", "abandoned", "voicemail", "failed"];
export const LATENCY_ORDER: LatencyStage[] = ["stt", "llm", "tts", "total"];
export const BAND_ORDER: MetricBand[] = ["good", "warn", "bad"];

// ── saf türetme yardımcıları ────────────────────────────────────────────────────

// Sonuç dağılımını OUTCOME_ORDER'a göre sırala (deterministik).
export function sortedOutcomes(view: AnalyticsView): OutcomeStat[] {
  return [...view.outcomes].sort((a, b) => OUTCOME_ORDER.indexOf(a.outcome) - OUTCOME_ORDER.indexOf(b.outcome));
}

// Yanıt gecikmesi aşamalarını LATENCY_ORDER'a göre sırala (stt→llm→tts→total).
export function sortedLatency(view: AnalyticsView): LatencyStat[] {
  return [...view.latency].sort((a, b) => LATENCY_ORDER.indexOf(a.stage) - LATENCY_ORDER.indexOf(b.stage));
}

// Toplam çağrı = Σ outcome sayısı (FR-ANA-002).
export function totalCalls(view: AnalyticsView): number {
  return view.outcomes.reduce((a, o) => a + o.count, 0);
}

// Belirli bir outcome'un sayısı (yoksa 0).
export function outcomeCount(view: AnalyticsView, outcome: CallOutcome): number {
  return view.outcomes.find((o) => o.outcome === outcome)?.count ?? 0;
}

// Belirli bir outcome'un oranı = count/total (total=0 ise 0).
export function outcomeRate(view: AnalyticsView, outcome: CallOutcome): number {
  const t = totalCalls(view);
  return t <= 0 ? 0 : outcomeCount(view, outcome) / t;
}

// Containment oranı = contained/total (FR-ANA-003).
export function containmentRate(view: AnalyticsView): number {
  return outcomeRate(view, "contained");
}
// Transfer oranı = transferred/total (FR-ANA-003).
export function transferRate(view: AnalyticsView): number {
  return outcomeRate(view, "transferred");
}
// Terk oranı = abandoned/total.
export function abandonRate(view: AnalyticsView): number {
  return outcomeRate(view, "abandoned");
}

// Σ outcome oranı ≈ 1 (FR-ANA-002 tutarlılık invariant'ı; total=0 ise true sayılır boş dönem).
export function outcomeRatesSumToOne(view: AnalyticsView, tol = RATE_TOLERANCE): boolean {
  if (totalCalls(view) <= 0) return true;
  const s = OUTCOME_ORDER.reduce((a, o) => a + outcomeRate(view, o), 0);
  return Math.abs(s - 1) <= tol;
}
// Σ outcome sayısı = totalCalls (yapısal tutarlılık — her zaman doğru olmalı).
export function outcomeCountsConsistent(view: AnalyticsView): boolean {
  return view.outcomes.reduce((a, o) => a + o.count, 0) === totalCalls(view);
}

// Konuşma toplamı (FR-ANA-005).
export function talkTotalSec(t: TalkTime): number {
  return t.userSec + t.agentSec + t.silenceSec;
}
// Agent konuşma payı = agent/(user+agent) (sessizlik hariç; 0 ise 0).
export function agentTalkRatio(t: TalkTime): number {
  const spoken = t.userSec + t.agentSec;
  return spoken <= 0 ? 0 : t.agentSec / spoken;
}
// Çağrı başına ortalama konuşma süresi (FR-ANA-005).
export function avgCallSec(view: AnalyticsView): number {
  const t = totalCalls(view);
  return t <= 0 ? 0 : talkTotalSec(view.talk) / t;
}
// SAKLANAN AHT ≈ çağrı başına konuşma süresi mi (FR-ANA-005 tutarlılık invariant'ı).
export function ahtConsistent(view: AnalyticsView, tol = AHT_TOLERANCE): boolean {
  return Math.abs(view.ahtSec - avgCallSec(view)) <= tol;
}

// Belirli aşamanın gecikme istatistiği (FR-ANA-006).
export function latencyStage(view: AnalyticsView, stage: LatencyStage): LatencyStat | undefined {
  return view.latency.find((l) => l.stage === stage);
}
// Toplam yanıt gecikmesi P95 bütçe içinde mi (NFR 10.1 — düşük daha iyi).
export function latencyWithinBudget(view: AnalyticsView, budgetMs: number = DEFAULT_TARGETS.latencyP95Ms): boolean {
  const total = latencyStage(view, "total");
  return total ? total.p95Ms <= budgetMs : false;
}
// Toplam gecikme ≥ her bileşen (stt/llm/tts) — zincir tutarlılığı (FR-ANA-006; bileşenler zincirin parçası).
export function latencyChainConsistent(view: AnalyticsView): boolean {
  const total = latencyStage(view, "total");
  if (!total) return false;
  const comps: LatencyStage[] = ["stt", "llm", "tts"];
  return comps.every((s) => {
    const c = latencyStage(view, s);
    return c ? total.p95Ms >= c.p95Ms && total.p50Ms >= c.p50Ms : true;
  });
}

// Zaman serisi çağrı toplamı (FR-ANA-011).
export function seriesCalls(view: AnalyticsView): number {
  return view.series.reduce((a, p) => a + p.calls, 0);
}
// Zaman serisi containment toplamı.
export function seriesContained(view: AnalyticsView): number {
  return view.series.reduce((a, p) => a + p.contained, 0);
}
// Seri ÇAĞRI toplamı = dönem totalCalls mi (FR-ANA-011 export bütünlük invariant'ı; boş seri muaf).
export function seriesReconciles(view: AnalyticsView): boolean {
  return view.series.length === 0 || seriesCalls(view) === totalCalls(view);
}
// Bir gün noktasının containment oranı = contained/calls (calls=0 ise 0).
export function dayContainmentRate(p: DayPoint): number {
  return p.calls <= 0 ? 0 : p.contained / p.calls;
}

// Zaman serisi eğilimi (ilk yarı ortalaması vs ikinci yarı ortalaması; deterministik).
export function seriesTrend(view: AnalyticsView, key: "contained" | "csat" | "calls", eps = TREND_FLAT_EPS): TrendDir {
  const xs = view.series;
  if (xs.length < 2) return "flat";
  const valueOf = (p: DayPoint) => (key === "contained" ? dayContainmentRate(p) : key === "csat" ? p.csat : p.calls);
  const mid = Math.floor(xs.length / 2);
  const first = xs.slice(0, mid);
  const second = xs.slice(xs.length - mid);
  const avg = (arr: DayPoint[]) => (arr.length === 0 ? 0 : arr.reduce((a, p) => a + valueOf(p), 0) / arr.length);
  const a = avg(first);
  const b = avg(second);
  if (a === 0) return b > 0 ? "up" : "flat";
  const rel = (b - a) / Math.abs(a);
  if (rel > eps) return "up";
  if (rel < -eps) return "down";
  return "flat";
}

// Aktif/yayında olan agent sürümü (FR-ANA-010; yoksa undefined).
export function currentVersion(view: AnalyticsView): VersionStat | undefined {
  return view.versions.find((v) => v.current);
}
// Tüm sürümlerin çağrı-ağırlıklı ortalama containment'ı (FR-ANA-010 referans çizgisi).
export function weightedAvgContainment(versions: VersionStat[]): number {
  const calls = versions.reduce((a, v) => a + v.calls, 0);
  if (calls <= 0) return 0;
  return versions.reduce((a, v) => a + v.containmentRate * v.calls, 0) / calls;
}
// Bir sürümün containment deltası: sürüm − ağırlıklı agent ortalaması (FR-ANA-010; +iyileşme/−gerileme).
export function versionContainmentDelta(v: VersionStat, versions: VersionStat[]): number {
  return v.containmentRate - weightedAvgContainment(versions);
}

// ── bant + ton (renk) eşlemeleri ────────────────────────────────────────────────────

// "Yüksek daha iyi" oran bandı (containment/csat): ≥hedef good · ≥hedef·WARN_RATIO warn · altı bad.
export function ratioBand(value: number, target: number, warnRatio = WARN_RATIO): MetricBand {
  if (value >= target) return "good";
  if (value >= target * warnRatio) return "warn";
  return "bad";
}
// "Düşük daha iyi" metrik bandı (AHT/gecikme): ≤hedef good · ≤hedef/WARN_RATIO warn · üstü bad.
export function lowerBetterBand(value: number, target: number, warnRatio = WARN_RATIO): MetricBand {
  if (value <= target) return "good";
  if (value <= target / warnRatio) return "warn";
  return "bad";
}

const BAND_TONE: Record<MetricBand, StatusTone> = { good: "success", warn: "warning", bad: "danger" };
export function bandTone(b: MetricBand): StatusTone {
  return BAND_TONE[b];
}
// Oran metriğini doğrudan tona çevir (yüksek daha iyi).
export function ratioTone(value: number, target: number): StatusTone {
  return bandTone(ratioBand(value, target));
}
// Düşük-daha-iyi metriğini doğrudan tona çevir.
export function lowerBetterTone(value: number, target: number): StatusTone {
  return bandTone(lowerBetterBand(value, target));
}

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

const TREND_TONE: Record<TrendDir, StatusTone> = { up: "success", down: "danger", flat: "neutral" };
export function trendTone(d: TrendDir): StatusTone {
  return TREND_TONE[d];
}

// ── HİJYEN + GÜVENLİK koruması (İKİ KATMAN) ─────────────────────────────────────────
// Katman 1 — YAPISAL anahtar guard: ham kimlik/iş-içeriği + sır/credential + nesne-depo URI çağrıştıran ALAN ADI
// bulunursa hata fırlatır. A-14 topluluk panosudur → tek çağrı içeriği (`text`/`transcript`/`recording`/`callRef`)
// taşımaz; yalnız agregat + agent config.
export const FORBIDDEN_PII_KEYS: readonly string[] = [
  "callref", // A-14 tek çağrı kimliği taşımaz (topluluk panosu)
  "text",
  "transcripttext",
  "rawtext",
  "transcript",
  "utterance",
  "recording",
  "recordingbytes",
  "audio",
  "audiobytes",
  "summary",
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

// Katman 2 — İÇERİK redaction desenleri: maskesiz ham PII izi. Agregat sayılar bile bu desenleri taşıyamaz
// (FR-REC-004/005); tek güvenli maskeli içerik MASK_TOKEN'dır.
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
        throw new Error(`A-14 HİJYEN ihlali: yasak PII/iş-içeriği alanı "${path}.${k}" (BRD §17.7 / FR-REC-004/005)`);
      }
      if (FORBIDDEN_SECRET_KEYS.includes(lower)) {
        throw new Error(`A-14 GÜVENLİK ihlali: sır/credential/nesne-depo URI alanı "${path}.${k}" panele konmaz (NFR 10.6)`);
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
        throw new Error(`A-14 REDACTION ihlali: maskesiz ham PII deseni "${path}" (FR-REC-004/005; agregat panoda ham PII bulunamaz)`);
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
// Deterministik yer tutucu: bir dönem agregatı (sonuç dağılımı + CSAT + AHT + konuşma süreleri + yanıt gecikmesi +
// zaman serisi + sürüm karşılaştırması). Gerçek implementasyon (F1 §14.1) gözlemlenebilirlik omurgası (0.4.7) +
// analitik/aggregation store (DB tenant-scope RLS) çıktısıyla beslenir. Bu örnek: sağlıklı bir 7 günlük dönem
// (containment hedef üstü + CSAT iyi + gecikme bütçe içinde). Tek çağrı içeriği/PII YOK; yalnız agregat.
const PLACEHOLDER_VIEW: AnalyticsView = {
  generatedAt: "2026-06-18T09:00:00.000Z",
  tenantRef: "TEN-2048",
  tenantName: "Kuzey Sigorta A.Ş.",
  period: { from: "2026-06-11", to: "2026-06-17", label: "Son 7 gün" },
  targets: { containment: DEFAULT_TARGETS.containment, csat: DEFAULT_TARGETS.csat, ahtSec: DEFAULT_TARGETS.ahtSec, latencyP95Ms: DEFAULT_TARGETS.latencyP95Ms },
  outcomes: [
    { outcome: "contained", count: 5400 },
    { outcome: "transferred", count: 1500 },
    { outcome: "abandoned", count: 420 },
    { outcome: "voicemail", count: 180 },
    { outcome: "failed", count: 100 },
  ],
  csat: 0.88,
  csatResponses: 4120,
  ahtSec: 196,
  talk: { userSec: 612000, agentSec: 735000, silenceSec: 168400 },
  latency: [
    { stage: "stt", p50Ms: 180, p95Ms: 320 },
    { stage: "llm", p50Ms: 240, p95Ms: 520 },
    { stage: "tts", p50Ms: 150, p95Ms: 280 },
    { stage: "total", p50Ms: 620, p95Ms: 1080 },
  ],
  series: [
    { date: "2026-06-11", calls: 1080, contained: 745, csat: 0.86, ahtSec: 201 },
    { date: "2026-06-12", calls: 1120, contained: 781, csat: 0.87, ahtSec: 198 },
    { date: "2026-06-13", calls: 940, contained: 668, csat: 0.88, ahtSec: 195 },
    { date: "2026-06-14", calls: 760, contained: 547, csat: 0.89, ahtSec: 192 },
    { date: "2026-06-15", calls: 1210, contained: 872, csat: 0.88, ahtSec: 197 },
    { date: "2026-06-16", calls: 1190, contained: 869, csat: 0.9, ahtSec: 193 },
    { date: "2026-06-17", calls: 1300, contained: 918, csat: 0.9, ahtSec: 190 },
  ],
  versions: [
    { agentVersion: "v7", calls: 4200, containmentRate: 0.78, csat: 0.9, ahtSec: 190, current: true },
    { agentVersion: "v6", calls: 2400, containmentRate: 0.72, csat: 0.86, ahtSec: 205, current: false },
    { agentVersion: "v5", calls: 1000, containmentRate: 0.68, csat: 0.84, ahtSec: 214, current: false },
  ],
};

export async function getAnalyticsView(): Promise<AnalyticsView> {
  const view = PLACEHOLDER_VIEW;
  assertSafe(view); // HİJYEN + GÜVENLİK + REDACTION: yapısal PII/sır/URI yok + içerik maskesiz ham PII deseni yok
  return view;
}
