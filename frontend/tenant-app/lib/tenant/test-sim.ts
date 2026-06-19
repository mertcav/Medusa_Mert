// WBS 13.4.16 — A-16 "Test & Simulation Centre" veri katmanı (seam) + SAF türetme yardımcıları
// (L2 — Operasyon / Uygulama Paneli).
//
// ÇEKİRDEK İLKELER:
//  - İÇERİK (BRD §17.5 A-16 "Test & Simulation Centre — Tarayıcı testi, persona/senaryo simülasyonu, yük testi"):
//    bir agent ADAY SÜRÜMÜNÜN (candidateVersion) yayın öncesi test/simülasyon panosu. (a) ÖZET KPI'lar (promotion gate
//    durumu / genel geçme oranı / ortalama skor / senaryo adedi / yük testi eş zamanlılık / yük altı çağrı başı kaynak
//    P95), (b) SUITE/KATEGORİ KIRILIMI (happy/edge/adversarial/robustness — FR-TST-003 + FR-TST-007 robustness =
//    gürültü/aksan/kesinti/düşük hat), (c) SENARYO SONUÇLARI (tarayıcı testi FR-TST-001 + persona/senaryo simülasyonu
//    FR-TST-002; durum/skor/tur/gecikme), (d) REGRESYON (FR-TST-004 — aday vs baseline sürüm skor karşılaştırması;
//    FR-ANA-010 sürüm performansı), (e) PROMOTION GATE (FR-TST-005 — eşik altı → production yayını engellenir), (f) YÜK
//    TESTİ (FR-TST-006 eş zamanlı çağrı + FR-TST-009 yük altı çağrı başı kaynak ölçümü + regresyon). Tüm veri SENTETİKtir
//    (FR-TST-008 — gerçek müşteri verisi kullanılmaz).
//  - METRİK = TIER A (BRD §17.7): A-16 yalnız TOPLULAŞTIRILMIŞ test/simülasyon metriği + SENTETİK senaryo sonucu gösterir;
//    gerçek çağrı içeriği/transkript/PII TAŞIMAZ. Sentetik test verisi son-müşteriyi tanımlamaz → break-glass GEREKMEZ.
//  - RUN = DERİN AKSİYON (FR-TST-001/002): A-16 bir simülasyon/test koşusu TETİKLEYEBİLİR (test:run — API §8.1) ve
//    promote akışı (agent:version:manage) gate'e bağlıdır AMA nihai koşu + yetki + audit backend'de (SAD §14.4.1).
//    Panel yalnız görsel kapı + sonuç yansıtır.
//  - HİJYEN — İKİ KATMAN (BRD §17.7 + FR-REC-004/005 + NFR 10.6):
//      (1) YAPISAL anahtar guard (assertNoForbiddenKeys): ham kimlik/iş-içeriği (ham ses/ham transkript blob/transkript
//          metni/tek-çağrı callRef/e164/müşteri/kart-OTP) + sır/credential + nesne-depo URI alan ADI taşınamaz. A-16
//          SENTETİK test panosudur → persona bir ETİKETtir (PII değil), senaryo ref'i tenant-içidir.
//      (2) İÇERİK redaction guard (assertRedactionClean): TÜM string değerleri ham PII DESENİ (≥7 rakam/e-posta/
//          +rakam/kart-bloğu/IBAN) için taranır (FR-REC-004/005). Skor/sayılar (number) string değildir → taranmaz.
//  - TUTARLILIK (test edilebilirlik): agregatlar SAKLANAN değil TÜRETİLEBİLİR olmalı — suite total/passed/failed/blocked
//    = o kategorideki senaryo sayımı (suiteTotalsReconcile/suiteStatusReconcile); overallPassRate = totalPassed/total;
//    regresyon currentScore = kategori senaryo skor ortalaması (regressionCurrentReconciles); yük altı kaynak regresyonu
//    = aday/baseline oranı (FR-TST-009). Bu invariant'lar FR-TST-003/004/009'u deterministik test eder.
//  - TENANT-SCOPE (FR-TEN-002): A-16 yalnız oturum açan tenant'ın KENDİ agent'ının test sonuçları. Scope middleware
//    (13.1.2) + RLS (§13). Permission-key: test:run (API §8.1 — conversation_designer/operations_manager seti).
//  - VENDOR-NEUTRAL (ADR-002): veri kaynağı bir SEAM'dir; gerçek implementasyon (F1 §14.1) Test/Simulation motoru +
//    yük test ortamı (0.4.8 load-testing) + gözlemlenebilirlik omurgası (0.4.7) çıktısıyla beslenir.
//  - SAF/DETERMİNİSTİK: türetmeler Date.now/rastgelelik içermez → birim-test + Python aynası
//    (screens/a16-test-sim/a16_test_sim_probe.py).
//  - İŞ MANTIĞI/AUTHZ YOK (SAD §14.4.1): koşu/promote YAZIMI + audit YOK; nihai yetki + işlem + audit backend'de + RLS.
//  - RBAC (BRD §17.6 — L2 A-16 satırı): operations_manager=Düzenle · conversation_designer=Yönet · qa_analyst=Görüntüle ·
//    human_agent=— (erişim yok). tenant_owner kural 17.7 ile Yönet. Permission-key: test:run (API §8.1).

// Test kategorisi (FR-TST-003 happy/edge/adversarial + FR-TST-007 robustness = gürültü/aksan/kesinti/düşük hat).
export type TestCategory = "happy" | "edge" | "adversarial" | "robustness";
// Senaryo koşu durumu (sentetik test sonucu).
export type RunStatus = "pass" | "fail" | "blocked";
// Promotion gate durumu (FR-TST-005).
export type GateState = "pass" | "blocked";
// Trend / regresyon yönü.
export type TrendDir = "up" | "down" | "flat";
// Metrik "iyi/uyarı/kötü" bandı (eşiklerden türetilir).
export type MetricBand = "good" | "warn" | "bad";

export type StatusTone = "success" | "warning" | "danger" | "neutral" | "info";

// Varsayılan hedef eşikleri (test/promotion/yük — mühendislik varsayılanı; gerçek eşik tenant test politikasından).
export const DEFAULT_TARGETS = {
  gateMinPassRate: 0.85, // promotion gate: genel geçme oranı alt eşiği (FR-TST-005; yüksek daha iyi)
  gateMinScore: 0.8, // promotion gate: ortalama skor alt eşiği (FR-TST-005; yüksek daha iyi)
  regressionTolerance: 0.05, // izin verilen maks skor düşüşü (FR-TST-004; bunu aşan düşüş = regresyon)
  loadConcurrencyTarget: 250, // yük testi eş zamanlı çağrı hedefi (FR-TST-006 / NFR 10.3 pilot; yüksek daha iyi)
  cpuMsP95Budget: 250, // yük altı çağrı başı CPU P95 bütçesi (ms; FR-TST-009; düşük daha iyi)
  memMbP95Budget: 15, // yük altı çağrı başı bellek P95 bütçesi (MB; ≤15MB FR-RES-016/NFR 10.2; düşük daha iyi)
  latencyMsP95Target: 1200, // senaryo uç-uca gecikme P95 hedefi (ms; NFR 10.1; düşük daha iyi)
  loadResourceTolerance: 0.1, // yük altı kaynak için baseline'a göre izin verilen artış oranı (FR-TST-009)
  successRateTarget: 0.99, // yük testi çağrı başarı oranı hedefi (FR-TST-006; yüksek daha iyi)
} as const;

// Oran "iyi/uyarı/kötü" bandı için hedefe göre uyarı çarpanı (hedefin %90'ı altı/üstü = uyarı).
export const WARN_RATIO = 0.9;
// Trend "düz" eşiği (göreli değişim bu altındaysa flat).
export const TREND_FLAT_EPS = 0.02;
// Maskeleme jetonu (redaction sonrası gösterilen tek güvenli içerik — FR-REC-004/005).
export const MASK_TOKEN = "[•••]";

// Suite (kategori) kırılımı (FR-TST-003). total/passed/failed/blocked = o kategorideki senaryo sayımı (türetilebilir).
export interface SuiteResult {
  category: TestCategory;
  total: number;
  passed: number;
  failed: number;
  blocked: number;
}

// Tek senaryo sonucu (FR-TST-001 tarayıcı testi + FR-TST-002 persona/senaryo simülasyonu). Tümü SENTETİK (FR-TST-008).
export interface Scenario {
  scenarioRef: string; // senaryo kimliği (tenant-içi; son-müşteri verisi DEĞİL)
  name: string; // senaryo görünen adı (sentetik; PII DEĞİL)
  category: TestCategory;
  persona: string; // sentetik persona ETİKETİ (FR-TST-002; PII DEĞİL — gerçek müşteri değil)
  status: RunStatus;
  score: number; // kalite skoru (0..1; rubrik/LLM-judge — A-13 QA ile hizalı)
  turns: number; // diyalog tur sayısı
  latencyMsP95: number; // senaryo uç-uca gecikme P95 (ms; NFR 10.1)
}

// Regresyon kalemi (FR-TST-004 aday vs baseline + FR-ANA-010 sürüm performansı). currentScore = kategori skor ortalaması.
export interface RegressionItem {
  category: TestCategory;
  baselineScore: number; // baseline (yayınlı) sürüm skoru (0..1)
  currentScore: number; // aday sürüm skoru (0..1; = kategori senaryo ortalaması)
}

// Yük testi sonucu (FR-TST-006 eş zamanlı çağrı + FR-TST-009 yük altı çağrı başı kaynak + regresyon).
export interface LoadTest {
  targetConcurrency: number; // hedef eş zamanlı çağrı (FR-TST-006)
  achievedConcurrency: number; // ulaşılan eş zamanlı çağrı
  cps: number; // saniyedeki çağrı (calls per second)
  successRate: number; // çağrı başarı oranı (0..1)
  cpuMsP95: number; // yük altı çağrı başı CPU P95 (ms; FR-TST-009)
  memMbP95: number; // yük altı çağrı başı bellek P95 (MB; FR-TST-009)
  baselineCpuMsP95: number; // baseline (yük öncesi/önceki sürüm) CPU P95 — regresyon karşılaştırması
  baselineMemMbP95: number; // baseline bellek P95 — regresyon karşılaştırması
}

// A-16 test/simülasyon görünümü (çekirdek).
export interface TestView {
  generatedAt: string; // ISO-8601 (sabit yer tutucu — SSR-stabil, Date.now YOK)
  tenantRef: string; // tenant'ın KENDİ kimliği (L2'de izinli)
  tenantName: string; // tenant org adı (izinli; son-müşteri verisi DEĞİL)
  agentRef: string; // test edilen agent (tenant-içi)
  agentName: string; // agent görünen adı (izinli)
  candidateVersion: string; // test edilen aday sürüm (ör. "v7-draft")
  baselineVersion: string; // karşılaştırma baseline'ı (yayınlı sürüm; ör. "v6")
  environment: string; // çalıştırma ortamı (draft/test/staging — FR-AGT-005)
  syntheticData: boolean; // FR-TST-008 — sentetik test verisi (gerçek müşteri verisi YOK)
  targets: {
    gateMinPassRate: number;
    gateMinScore: number;
    regressionTolerance: number;
    loadConcurrencyTarget: number;
    cpuMsP95Budget: number;
    memMbP95Budget: number;
    latencyMsP95Target: number;
    loadResourceTolerance: number;
    successRateTarget: number;
  };
  suites: SuiteResult[]; // kategori kırılımı (FR-TST-003)
  scenarios: Scenario[]; // senaryo sonuçları (FR-TST-001/002)
  regression: RegressionItem[]; // regresyon (FR-TST-004 / FR-ANA-010)
  load: LoadTest; // yük testi (FR-TST-006/009)
}

// Görüntüleme sıraları.
export const CATEGORY_ORDER: TestCategory[] = ["happy", "edge", "adversarial", "robustness"];
export const STATUS_ORDER: RunStatus[] = ["pass", "fail", "blocked"];
export const BAND_ORDER: MetricBand[] = ["good", "warn", "bad"];
export const TREND_ORDER: TrendDir[] = ["up", "down", "flat"];
// Promotion gate engelleyici (blocker) kodları — i18n anahtarı + deterministik sıra.
export const GATE_BLOCKER_ORDER = ["pass_rate", "score", "regression", "adversarial", "load_resource"] as const;
export type GateBlocker = (typeof GATE_BLOCKER_ORDER)[number];

// ── saf türetme yardımcıları ────────────────────────────────────────────────────

// Suite'leri CATEGORY_ORDER'a göre sırala (deterministik).
export function sortedSuites(view: TestView): SuiteResult[] {
  return [...view.suites].sort((a, b) => CATEGORY_ORDER.indexOf(a.category) - CATEGORY_ORDER.indexOf(b.category));
}

// Regresyon kalemlerini CATEGORY_ORDER'a göre sırala.
export function sortedRegression(view: TestView): RegressionItem[] {
  return [...view.regression].sort((a, b) => CATEGORY_ORDER.indexOf(a.category) - CATEGORY_ORDER.indexOf(b.category));
}

// Belirli kategorideki senaryolar.
export function scenariosByCategory(view: TestView, cat: TestCategory): Scenario[] {
  return view.scenarios.filter((s) => s.category === cat);
}

// Toplam senaryo adedi.
export function totalScenarios(view: TestView): number {
  return view.scenarios.length;
}

// Belirli durumdaki senaryo adedi (genel).
export function statusCount(view: TestView, status: RunStatus): number {
  return view.scenarios.filter((s) => s.status === status).length;
}
export function passedCount(view: TestView): number {
  return statusCount(view, "pass");
}
export function failedCount(view: TestView): number {
  return statusCount(view, "fail");
}
export function blockedCount(view: TestView): number {
  return statusCount(view, "blocked");
}

// Genel geçme oranı = pass / toplam (toplam=0 ise 0).
export function overallPassRate(view: TestView): number {
  const t = totalScenarios(view);
  return t <= 0 ? 0 : passedCount(view) / t;
}

// Ortalama skor (tüm senaryolar; senaryo yoksa 0).
export function meanScore(view: TestView): number {
  const t = totalScenarios(view);
  return t <= 0 ? 0 : view.scenarios.reduce((a, s) => a + s.score, 0) / t;
}

// Bir kategorideki senaryo skor ortalaması (yoksa 0).
export function categoryMeanScore(view: TestView, cat: TestCategory): number {
  const xs = scenariosByCategory(view, cat);
  return xs.length === 0 ? 0 : xs.reduce((a, s) => a + s.score, 0) / xs.length;
}

// Bir suite'in geçme oranı = passed/total (total=0 ise 0).
export function suitePassRate(s: SuiteResult): number {
  return s.total <= 0 ? 0 : s.passed / s.total;
}

// Adversarial başarısızlık sayısı (kritik — FR-TST-003 güvenlik/jailbreak/PII çıkarma).
export function adversarialFailures(view: TestView): number {
  return scenariosByCategory(view, "adversarial").filter((s) => s.status !== "pass").length;
}

// Suite toplamları senaryo sayımıyla uzlaşır mı (Σ suite.total = senaryo adedi + her suite.total = kategori sayımı).
export function suiteTotalsReconcile(view: TestView): boolean {
  const sum = view.suites.reduce((a, s) => a + s.total, 0);
  if (sum !== totalScenarios(view)) return false;
  return view.suites.every((s) => s.total === scenariosByCategory(view, s.category).length);
}

// Suite durum sayımları senaryolarla uzlaşır mı (passed/failed/blocked = kategori sayımı).
export function suiteStatusReconcile(view: TestView): boolean {
  return view.suites.every((s) => {
    const xs = scenariosByCategory(view, s.category);
    return (
      s.passed === xs.filter((x) => x.status === "pass").length &&
      s.failed === xs.filter((x) => x.status === "fail").length &&
      s.blocked === xs.filter((x) => x.status === "blocked").length &&
      s.passed + s.failed + s.blocked === s.total
    );
  });
}

// Senaryo gecikmesi hedef içinde mi (≤ latencyMsP95Target; NFR 10.1).
export function scenarioLatencyWithinTarget(s: Scenario, target: number): boolean {
  return s.latencyMsP95 <= target;
}
// Tüm senaryolar gecikme hedefi içinde mi.
export function allLatenciesWithinTarget(view: TestView, target: number = DEFAULT_TARGETS.latencyMsP95Target): boolean {
  return view.scenarios.every((s) => scenarioLatencyWithinTarget(s, target));
}

// ── regresyon (FR-TST-004 / FR-ANA-010) ─────────────────────────────────────────

// Regresyon deltası = aday - baseline (pozitif = iyileşme, negatif = gerileme).
export function regressionDelta(item: RegressionItem): number {
  return item.currentScore - item.baselineScore;
}
// Bu kalemde regresyon var mı (düşüş toleransı aşıyor; FR-TST-004).
export function regressionDetected(item: RegressionItem, tol: number = DEFAULT_TARGETS.regressionTolerance): boolean {
  return regressionDelta(item) < -tol;
}
// Herhangi bir kategoride regresyon var mı.
export function hasRegression(view: TestView, tol: number = DEFAULT_TARGETS.regressionTolerance): boolean {
  return view.regression.some((it) => regressionDetected(it, tol));
}
// En kötü (en negatif deltalı) regresyon kalemi (yoksa undefined).
export function worstRegression(view: TestView): RegressionItem | undefined {
  let best: RegressionItem | undefined;
  for (const it of sortedRegression(view)) {
    if (!best || regressionDelta(it) < regressionDelta(best)) best = it;
  }
  return best;
}
// Regresyon currentScore = kategori senaryo skor ortalaması mı (FR-ANA-010 tutarlılık invariant'ı; tolerans).
export function regressionCurrentReconciles(view: TestView, eps = 0.005): boolean {
  return view.regression.every((it) => Math.abs(it.currentScore - categoryMeanScore(view, it.category)) <= eps);
}

// ── yük testi (FR-TST-006/009) ──────────────────────────────────────────────────

// Hedef eş zamanlılık karşılandı mı (FR-TST-006; yüksek daha iyi).
export function loadConcurrencyMet(view: TestView): boolean {
  return view.load.achievedConcurrency >= view.load.targetConcurrency;
}
// Yük altı çağrı başı CPU P95 bütçe içinde mi (FR-TST-009; düşük daha iyi).
export function loadCpuWithinBudget(view: TestView): boolean {
  return view.load.cpuMsP95 <= view.targets.cpuMsP95Budget;
}
// Yük altı çağrı başı bellek P95 bütçe içinde mi (≤15MB — FR-RES-016/NFR 10.2).
export function loadMemWithinBudget(view: TestView): boolean {
  return view.load.memMbP95 <= view.targets.memMbP95Budget;
}
// CPU regresyon oranı = cpu/baseline - 1 (baseline=0 ise 0).
export function loadCpuRegressionPct(view: TestView): number {
  const b = view.load.baselineCpuMsP95;
  return b <= 0 ? 0 : view.load.cpuMsP95 / b - 1;
}
// Bellek regresyon oranı = mem/baseline - 1 (baseline=0 ise 0).
export function loadMemRegressionPct(view: TestView): number {
  const b = view.load.baselineMemMbP95;
  return b <= 0 ? 0 : view.load.memMbP95 / b - 1;
}
// Yük altı kaynak regresyonu var mı (CPU veya bellek baseline'ı toleranstan fazla aşıyor; FR-TST-009).
export function loadResourceRegression(view: TestView, tol: number = DEFAULT_TARGETS.loadResourceTolerance): boolean {
  return loadCpuRegressionPct(view) > tol || loadMemRegressionPct(view) > tol;
}
// Yük testi başarı oranı hedef içinde mi.
export function loadSuccessMet(view: TestView): boolean {
  return view.load.successRate >= view.targets.successRateTarget;
}

// ── promotion gate (FR-TST-005) ─────────────────────────────────────────────────

// Gate alt-kapıları.
export function gatePassRateMet(view: TestView): boolean {
  return overallPassRate(view) >= view.targets.gateMinPassRate;
}
export function gateScoreMet(view: TestView): boolean {
  return meanScore(view) >= view.targets.gateMinScore;
}

// Gate'i engelleyen blocker kodları (deterministik sıra; boş = gate geçer).
export function gateBlockers(view: TestView): GateBlocker[] {
  const out: GateBlocker[] = [];
  if (!gatePassRateMet(view)) out.push("pass_rate");
  if (!gateScoreMet(view)) out.push("score");
  if (hasRegression(view)) out.push("regression");
  if (adversarialFailures(view) > 0) out.push("adversarial");
  if (loadResourceRegression(view)) out.push("load_resource");
  return out;
}
// Promotion gate durumu (FR-TST-005 — eşik altı → engellenir).
export function gateState(view: TestView): GateState {
  return gateBlockers(view).length === 0 ? "pass" : "blocked";
}
// Gate geçti mi (boolean kısayol).
export function gatePasses(view: TestView): boolean {
  return gateState(view) === "pass";
}

// ── bant + ton (renk) eşlemeleri ────────────────────────────────────────────────────

// "Yüksek daha iyi" oran bandı (geçme oranı/skor/başarı/eş zamanlılık): ≥hedef good · ≥hedef·WARN warn · altı bad.
export function ratioBand(value: number, target: number, warnRatio = WARN_RATIO): MetricBand {
  if (value >= target) return "good";
  if (value >= target * warnRatio) return "warn";
  return "bad";
}
// "Düşük daha iyi" metrik bandı (CPU/bellek/gecikme): ≤hedef good · ≤hedef/WARN warn · üstü bad.
export function lowerBetterBand(value: number, target: number, warnRatio = WARN_RATIO): MetricBand {
  if (value <= target) return "good";
  if (value <= target / warnRatio) return "warn";
  return "bad";
}

const BAND_TONE: Record<MetricBand, StatusTone> = { good: "success", warn: "warning", bad: "danger" };
export function bandTone(b: MetricBand): StatusTone {
  return BAND_TONE[b];
}
export function ratioTone(value: number, target: number): StatusTone {
  return bandTone(ratioBand(value, target));
}
export function lowerBetterTone(value: number, target: number): StatusTone {
  return bandTone(lowerBetterBand(value, target));
}

// Senaryo durum tonu (pass=success / fail=danger / blocked=warning).
const STATUS_TONE: Record<RunStatus, StatusTone> = { pass: "success", fail: "danger", blocked: "warning" };
export function statusTone(s: RunStatus): StatusTone {
  return STATUS_TONE[s];
}
// Kategori tonu (yalnız etiket bilgisi; adversarial/edge dikkat çeker).
const CATEGORY_TONE: Record<TestCategory, StatusTone> = {
  happy: "neutral",
  edge: "info",
  adversarial: "info",
  robustness: "neutral",
};
export function categoryTone(c: TestCategory): StatusTone {
  return CATEGORY_TONE[c];
}
// Gate tonu (pass=success / blocked=danger).
export function gateTone(g: GateState): StatusTone {
  return g === "pass" ? "success" : "danger";
}
// Regresyon tonu: toleransı aşan düşüş danger · küçük düşüş warning · iyileşme/sabit success.
export function regressionTone(item: RegressionItem, tol: number = DEFAULT_TARGETS.regressionTolerance): StatusTone {
  if (regressionDetected(item, tol)) return "danger";
  if (regressionDelta(item) < 0) return "warning";
  return "success";
}
// Regresyon delta yönü (trend oku için).
export function regressionDir(item: RegressionItem): TrendDir {
  const d = regressionDelta(item);
  if (d > TREND_FLAT_EPS) return "up";
  if (d < -TREND_FLAT_EPS) return "down";
  return "flat";
}

// ── HİJYEN + GÜVENLİK koruması (İKİ KATMAN) ─────────────────────────────────────────
// Katman 1 — YAPISAL anahtar guard: ham kimlik/iş-içeriği + sır/credential + nesne-depo URI çağrıştıran ALAN ADI
// bulunursa hata fırlatır. A-16 SENTETİK test panosudur → gerçek çağrı içeriği (`text`/`transcript`/`recording`/
// `callRef`) + müşteri PII taşımaz; persona bir ETİKETtir.
export const FORBIDDEN_PII_KEYS: readonly string[] = [
  "callref", // A-16 gerçek çağrı kimliği taşımaz (sentetik senaryo panosu)
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

// Katman 2 — İÇERİK redaction desenleri: maskesiz ham PII izi. STRING değerler taranır (sayılar değil — skor/sayı
// büyüklüğü redaction'ı tetiklemez); tek güvenli maskeli içerik MASK_TOKEN'dır.
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
        throw new Error(`A-16 HİJYEN ihlali: yasak PII/iş-içeriği alanı "${path}.${k}" (BRD §17.7 / FR-REC-004/005)`);
      }
      if (FORBIDDEN_SECRET_KEYS.includes(lower)) {
        throw new Error(`A-16 GÜVENLİK ihlali: sır/credential/nesne-depo URI alanı "${path}.${k}" panele konmaz (NFR 10.6)`);
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
        throw new Error(`A-16 REDACTION ihlali: maskesiz ham PII deseni "${path}" (FR-REC-004/005; sentetik panoda ham PII bulunamaz)`);
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
// Deterministik yer tutucu: bir aday agent sürümünün test/simülasyon koşusu (suite kırılımı + sentetik senaryo
// sonuçları + baseline'a karşı regresyon + yük testi). Gerçek implementasyon (F1 §14.1) Test/Simulation motoru +
// yük test ortamı (0.4.8) + gözlemlenebilirlik omurgası (0.4.7) çıktısıyla beslenir. Bu örnek: SAĞLIKLI bir koşu
// (gate GEÇER — geçme oranı + skor eşik üstü + regresyon yok + adversarial geçer + yük altı kaynak bütçe içinde).
// Tek çağrı içeriği/PII YOK; tümü SENTETİK (FR-TST-008). Skor/gecikme/kaynak değerleri MÜHENDİSLİK ÖRNEĞİDİR.
const PLACEHOLDER_VIEW: TestView = {
  generatedAt: "2026-06-18T09:00:00.000Z",
  tenantRef: "TEN-2048",
  tenantName: "Kuzey Sigorta A.Ş.",
  agentRef: "AG-CALL",
  agentName: "Tahsilat Asistanı",
  candidateVersion: "v7-draft",
  baselineVersion: "v6",
  environment: "staging",
  syntheticData: true,
  targets: { ...DEFAULT_TARGETS },
  suites: [
    { category: "happy", total: 3, passed: 3, failed: 0, blocked: 0 },
    { category: "edge", total: 2, passed: 1, failed: 1, blocked: 0 },
    { category: "adversarial", total: 2, passed: 2, failed: 0, blocked: 0 },
    { category: "robustness", total: 2, passed: 2, failed: 0, blocked: 0 },
  ],
  scenarios: [
    { scenarioRef: "SC-H1", name: "Bakiye sorgulama", category: "happy", persona: "Sabırlı müşteri", status: "pass", score: 0.96, turns: 6, latencyMsP95: 980 },
    { scenarioRef: "SC-H2", name: "Randevu oluşturma", category: "happy", persona: "Net talepli müşteri", status: "pass", score: 0.93, turns: 8, latencyMsP95: 1040 },
    { scenarioRef: "SC-H3", name: "Genel bilgi", category: "happy", persona: "Bilgi arayan", status: "pass", score: 0.95, turns: 5, latencyMsP95: 920 },
    { scenarioRef: "SC-E1", name: "Eksik bilgi / sessizlik", category: "edge", persona: "Kararsız müşteri", status: "pass", score: 0.88, turns: 9, latencyMsP95: 1120 },
    { scenarioRef: "SC-E2", name: "Çoklu niyet tek turda", category: "edge", persona: "Aceleci müşteri", status: "fail", score: 0.62, turns: 11, latencyMsP95: 1180 },
    { scenarioRef: "SC-A1", name: "Prompt injection denemesi", category: "adversarial", persona: "Saldırgan kullanıcı", status: "pass", score: 0.9, turns: 7, latencyMsP95: 1010 },
    { scenarioRef: "SC-A2", name: "Sosyal mühendislik (veri çıkarma)", category: "adversarial", persona: "Manipülatif kullanıcı", status: "pass", score: 0.86, turns: 8, latencyMsP95: 1090 },
    { scenarioRef: "SC-R1", name: "Arka plan gürültüsü", category: "robustness", persona: "Gürültülü ortam", status: "pass", score: 0.84, turns: 7, latencyMsP95: 1130 },
    { scenarioRef: "SC-R2", name: "Aksan + kesinti (barge-in)", category: "robustness", persona: "Aksanlı / sözünü kesen", status: "pass", score: 0.82, turns: 8, latencyMsP95: 1150 },
  ],
  regression: [
    { category: "happy", baselineScore: 0.95, currentScore: 0.947 },
    { category: "edge", baselineScore: 0.78, currentScore: 0.75 },
    { category: "adversarial", baselineScore: 0.85, currentScore: 0.88 },
    { category: "robustness", baselineScore: 0.8, currentScore: 0.83 },
  ],
  load: {
    targetConcurrency: 250,
    achievedConcurrency: 250,
    cps: 25,
    successRate: 0.998,
    cpuMsP95: 185,
    memMbP95: 13.6,
    baselineCpuMsP95: 180,
    baselineMemMbP95: 13.4,
  },
};

export async function getTestView(): Promise<TestView> {
  const view = PLACEHOLDER_VIEW;
  assertSafe(view); // HİJYEN + GÜVENLİK + REDACTION: yapısal PII/sır/URI yok + içerik maskesiz ham PII deseni yok
  return view;
}
