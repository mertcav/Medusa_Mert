// WBS 13.4.15 — A-15 "Maliyet & Kaynak Tüketimi" veri katmanı (seam) + SAF türetme yardımcıları
// (L2 — Operasyon / Uygulama Paneli).
//
// ÇEKİRDEK İLKELER:
//  - İÇERİK (BRD §17.5 A-15 "Maliyet & Kaynak Tüketimi — Operasyonel maliyet ve çağrı başı kaynak görünümü"):
//    bir DÖNEM boyunca, ÇOK ÇAĞRIYI TOPLULAŞTIRAN operasyonel maliyet + lean-runtime kaynak panosu. A-14 (Analytics)
//    kalite/operasyon metriğini gösterirken, A-15 (a) ÖZET MALİYET KPI'ları (toplam maliyet / çağrı başına maliyet /
//    çözülen çağrı başına maliyet [§18.1 cost per resolved call] / dakika başına maliyet [§18.2]), (b) MALİYET
//    DAĞILIMI — bileşen/sağlayıcı bazında (STT/LLM/TTS/telekom/compute; FR-ANA-007), (c) AGENT bazında maliyet
//    (FR-ANA-007 — çağrı/agent/tenant/sağlayıcı), (d) ÇAĞRI BAŞINA KAYNAK TÜKETİMİ (CPU/bellek/eşzamanlılık;
//    FR-ANA-013), (e) VERİMLİLİK / LEAN-RUNTIME göstergeleri (worker density NFR 10.2 + TTS cache hit FR-TTS-010 +
//    küçük-model tur oranı SR-DEN-005 + scale-to-zero/boşta geri kazanım FR-RES-014; BRD §18.2) ve (f) ZAMAN SERİSİ /
//    TREND sunar; ham veri export (FR-ANA-011) görsel kapısı içerir.
//  - METRİK = TIER A (BRD §17.7): A-15 yalnız TOPLULAŞTIRILMIŞ maliyet/kaynak metriği gösterir; tek çağrı içeriği/
//    transkript/PII TAŞIMAZ. Topluluk istatistiği son-müşteriyi tanımlamaz → break-glass GEREKMEZ (Tier A).
//  - EXPORT = DERİN AKSİYON (FR-ANA-011): A-15 maliyet/kaynak raporu export'unu TETİKLEYEBİLİR (cost:read) AMA
//    nihai export + redaction + yetki + audit backend'de (API §8.1). Panel yalnız görsel kapı (SAD §14.4.1).
//  - HİJYEN — İKİ KATMAN (BRD §17.7 + FR-REC-004/005 + NFR 10.6):
//      (1) YAPISAL anahtar guard (assertNoForbiddenKeys): ham kimlik/iş-içeriği (ham ses/ham transkript blob/
//          transkript metni/tek-çağrı callRef/e164/müşteri/kart-OTP) + sır/credential + nesne-depo URI alan ADI
//          taşınamaz. A-15 topluluk panosudur → yalnız agregat maliyet + per-call kaynak istatistiği + agent config.
//      (2) İÇERİK redaction guard (assertRedactionClean): TÜM string değerleri ham PII DESENİ (≥7 rakam/e-posta/
//          +rakam/kart-bloğu/IBAN) için taranır (FR-REC-004/005). Maliyet/kaynak SAYILARI (number) string değildir →
//          taranmaz; agregat sayıların büyüklüğü redaction'ı tetiklemez.
//  - TUTARLILIK (test edilebilirlik): agregatlar SAKLANAN değil TÜRETİLEBİLİR olmalı —
//    totalCostMinor = Σ bileşen (componentsSumToTotal'a gerek yok, doğrudan türetilir; FR-ANA-007); agent maliyet
//    toplamı = toplam (agentCostReconciles); agent çağrı toplamı = totalCalls (agentCallsReconcile); seri maliyet/
//    çağrı toplamı = dönem (seriesReconcilesCost/Calls; FR-ANA-011); çözülen ≤ toplam (resolvedConsistent). Bu
//    invariant'lar FR-ANA-007/013/011'i deterministik test eder.
//  - PARA BİRİMİ TAM ARİTMETİK: tüm maliyetler MINOR BİRİM (kuruş/cent) TAM SAYI olarak tutulur (amountMinor);
//    Σ bileşen = toplam TAM eşitliktir (float drift yok). Görüntülemede minor/100 → formatCurrency.
//  - TENANT-SCOPE (FR-TEN-002): A-15 yalnız oturum açan tenant'ın KENDİ maliyet/kaynak agregatı. Scope middleware
//    (13.1.2) + RLS (§13). Permission-key: cost:read (SAD §13.3 — operations_manager seti).
//  - VENDOR-NEUTRAL (ADR-002): veri kaynağı bir SEAM'dir; gerçek implementasyon (F1 §14.1) Cost/Resource Meter
//    (SAD §13.3 — per-call CPU/mem/eşzamanlılık → Analytics & Billing) + gözlemlenebilirlik omurgası (0.4.7)
//    çıktısıyla beslenir. Belirli STT/TTS/LLM/telekom sağlayıcı maliyeti adapter SPI (meter()/UsageRecord) arkasında.
//  - SAF/DETERMİNİSTİK: türetmeler Date.now/rastgelelik içermez → birim-test + Python aynası
//    (screens/a15-cost/a15_cost_probe.py).
//  - İŞ MANTIĞI/AUTHZ YOK (SAD §14.4.1): export YAZIMI + audit YOK; nihai yetki + işlem + audit backend'de + RLS.
//    Panel yalnız çözümlenmiş agregatı gösterir.
//  - RBAC (BRD §17.6 — L2 A-15 satırı): operations_manager=Görüntüle · conversation_designer=— · qa_analyst=— ·
//    human_agent=— (erişim yok). tenant_owner kural 17.7 ile Yönet. Permission-key: cost:read (API §8.1).

// Maliyet bileşeni / sağlayıcı kategorisi (FR-ANA-007 — sağlayıcı/kategori bazında ayrı izlenir).
export type CostComponentKey = "stt" | "llm" | "tts" | "telephony" | "compute";
// Çağrı başına kaynak metriği (FR-ANA-013 — CPU/bellek; eşzamanlılık worker density olarak verimlilikte).
export type ResourceMetric = "cpuMs" | "memMb";
// Trend yönü (zaman serisi eğilimi).
export type TrendDir = "up" | "down" | "flat";
// Metrik "iyi/uyarı/kötü" bandı (eşiklerden türetilir).
export type MetricBand = "good" | "warn" | "bad";

export type StatusTone = "success" | "warning" | "danger" | "neutral" | "info";

// Varsayılan hedef eşikleri (operasyonel/lean-runtime — mühendislik varsayılanı; gerçek rate-card/SLA finans+SRE'den).
export const DEFAULT_TARGETS = {
  costPerCallMinor: 1200, // çağrı başına maliyet üst hedefi (minor birim; düşük daha iyi)
  cpuMsP95: 250, // çağrı başına CPU P95 bütçesi (ms; düşük daha iyi)
  memMbP95: 15, // çağrı başına bellek P95 bütçesi (MB; ≤15MB FR-RES-016 / NFR 10.2; düşük daha iyi)
  densityMin: 250, // worker başına eş zamanlı oturum alt hedefi (NFR 10.2; yüksek daha iyi)
  densityStretch: 500, // worker density stretch hedefi (NFR 10.2)
  cacheHit: 0.6, // TTS/semantic cache hit hedefi (FR-TTS-010; yüksek daha iyi → maliyet düşer)
  smallModelRatio: 0.5, // küçük-model tur oranı hedefi (SR-DEN-005; yüksek daha iyi → maliyet düşer)
  idleReclaim: 0.6, // scale-to-zero/boşta kaynak geri kazanım hedefi (FR-RES-014; yüksek daha iyi)
} as const;

// Oran "iyi/uyarı/kötü" bandı için hedefe göre uyarı çarpanı (hedefin %90'ı altı/üstü = kötü).
export const WARN_RATIO = 0.9;
// Trend "düz" eşiği (göreli değişim bu altındaysa flat).
export const TREND_FLAT_EPS = 0.02;
// Maskeleme jetonu (redaction sonrası gösterilen tek güvenli içerik — FR-REC-004/005).
export const MASK_TOKEN = "[•••]";

// Maliyet bileşeni kalemi (FR-ANA-007). amountMinor = dönem maliyeti, MINOR birim (kuruş/cent) TAM SAYI.
export interface CostComponent {
  component: CostComponentKey;
  amountMinor: number;
}

// Agent bazında maliyet kalemi (FR-ANA-007 — agent bazında). amountMinor MINOR birim TAM SAYI.
export interface AgentCost {
  agentRef: string; // agent kimliği (tenant-içi; son-müşteri verisi DEĞİL)
  agentName: string; // agent görünen adı (izinli; PII DEĞİL)
  calls: number; // dönemdeki çağrı adedi (topluluk)
  amountMinor: number; // dönem maliyeti (minor)
}

// Çağrı başına kaynak istatistiği (FR-ANA-013 — CPU/bellek; P50/P95 + bütçe).
export interface ResourceStat {
  metric: ResourceMetric; // cpuMs / memMb
  p50: number;
  p95: number;
  budget: number; // bütçe/üst sınır (düşük daha iyi)
}

// Verimlilik / lean-runtime göstergeleri (NFR 10.2 + BRD §18.2 — eşzamanlılık density + cache + tier + idle).
export interface Efficiency {
  density: number; // worker başına eş zamanlı oturum (NFR 10.2 — FR-ANA-013 eşzamanlılık boyutu)
  cacheHitRatio: number; // TTS/semantic cache hit (0..1; FR-TTS-010)
  smallModelTurnRatio: number; // küçük-model tur oranı (0..1; SR-DEN-005)
  idleReclaimRatio: number; // scale-to-zero/boşta kaynak geri kazanım (0..1; FR-RES-014)
}

// Zaman serisi noktası (günlük agregat — FR-ANA-011 dashboard).
export interface DayCost {
  date: string; // ISO-8601 tarih (sabit yer tutucu)
  calls: number; // o günkü çağrı sayısı
  amountMinor: number; // o günkü maliyet (minor)
  cpuMsP95: number; // o günkü çağrı başı CPU P95
  memMbP95: number; // o günkü çağrı başı bellek P95
}

// Dönem agregat görünümü (A-15 çekirdeği).
export interface CostView {
  generatedAt: string; // ISO-8601 (sabit yer tutucu — SSR-stabil, Date.now YOK)
  tenantRef: string; // tenant'ın KENDİ kimliği (L2'de izinli)
  tenantName: string; // tenant org adı (izinli; son-müşteri verisi DEĞİL)
  currency: string; // ISO-4217 para birimi (ör. "TRY")
  period: { from: string; to: string; label: string }; // raporlama dönemi
  targets: {
    costPerCallMinor: number;
    cpuMsP95: number;
    memMbP95: number;
    densityMin: number;
    densityStretch: number;
    cacheHit: number;
    smallModelRatio: number;
    idleReclaim: number;
  };
  totalCalls: number; // dönem çağrı adedi (topluluk)
  resolvedCalls: number; // çözülen (contained/otomasyon) çağrı adedi — cost per resolved call (§18.1)
  billedMinutes: number; // faturalanan dakika (dakika başına maliyet — §18.2)
  components: CostComponent[]; // maliyet dağılımı (FR-ANA-007)
  agents: AgentCost[]; // agent bazında maliyet (FR-ANA-007)
  resources: ResourceStat[]; // çağrı başına kaynak (FR-ANA-013)
  efficiency: Efficiency; // verimlilik / lean-runtime (NFR 10.2 / §18.2)
  series: DayCost[]; // zaman serisi (FR-ANA-011)
}

// Görüntüleme sıraları.
export const COMPONENT_ORDER: CostComponentKey[] = ["stt", "llm", "tts", "telephony", "compute"];
export const RESOURCE_ORDER: ResourceMetric[] = ["cpuMs", "memMb"];
export const BAND_ORDER: MetricBand[] = ["good", "warn", "bad"];
export const TREND_ORDER: TrendDir[] = ["up", "down", "flat"];

// ── saf türetme yardımcıları ────────────────────────────────────────────────────

// Maliyet bileşenlerini COMPONENT_ORDER'a göre sırala (deterministik).
export function sortedComponents(view: CostView): CostComponent[] {
  return [...view.components].sort((a, b) => COMPONENT_ORDER.indexOf(a.component) - COMPONENT_ORDER.indexOf(b.component));
}

// Kaynak metriklerini RESOURCE_ORDER'a göre sırala (cpuMs→memMb).
export function sortedResources(view: CostView): ResourceStat[] {
  return [...view.resources].sort((a, b) => RESOURCE_ORDER.indexOf(a.metric) - RESOURCE_ORDER.indexOf(b.metric));
}

// Toplam maliyet (minor) = Σ bileşen (FR-ANA-007 — sağlayıcı/kategori toplamı).
export function totalCostMinor(view: CostView): number {
  return view.components.reduce((a, c) => a + c.amountMinor, 0);
}

// Belirli bir bileşenin maliyeti (yoksa 0).
export function componentAmount(view: CostView, key: CostComponentKey): number {
  return view.components.find((c) => c.component === key)?.amountMinor ?? 0;
}

// Bir bileşenin payı = amount/total (total=0 ise 0).
export function componentShare(view: CostView, key: CostComponentKey): number {
  const t = totalCostMinor(view);
  return t <= 0 ? 0 : componentAmount(view, key) / t;
}

// En büyük paylı bileşen (maliyet sürücüsü; eşitlikte COMPONENT_ORDER ilk gelen).
export function dominantComponent(view: CostView): CostComponentKey | undefined {
  const sorted = sortedComponents(view);
  let best: CostComponent | undefined;
  for (const c of sorted) {
    if (!best || c.amountMinor > best.amountMinor) best = c;
  }
  return best?.component;
}

// Agent maliyet toplamı (minor).
export function agentTotalMinor(view: CostView): number {
  return view.agents.reduce((a, g) => a + g.amountMinor, 0);
}
// Agent çağrı toplamı.
export function agentCallsTotal(view: CostView): number {
  return view.agents.reduce((a, g) => a + g.calls, 0);
}
// Agent maliyet toplamı = dönem toplamı mı (FR-ANA-007 uzlaşı invariant'ı).
export function agentCostReconciles(view: CostView): boolean {
  return agentTotalMinor(view) === totalCostMinor(view);
}
// Agent çağrı toplamı = dönem totalCalls mi (FR-ANA-007 uzlaşı invariant'ı).
export function agentCallsReconcile(view: CostView): boolean {
  return agentCallsTotal(view) === view.totalCalls;
}
// Bir agent'ın maliyet payı = amount/total.
export function agentCostShare(g: AgentCost, view: CostView): number {
  const t = totalCostMinor(view);
  return t <= 0 ? 0 : g.amountMinor / t;
}
// Bir agent'ın çağrı başına maliyeti (minor; calls=0 ise 0).
export function agentCostPerCallMinor(g: AgentCost): number {
  return g.calls <= 0 ? 0 : g.amountMinor / g.calls;
}

// Çağrı başına maliyet (minor) = toplam/totalCalls (totalCalls=0 ise 0).
export function costPerCallMinor(view: CostView): number {
  return view.totalCalls <= 0 ? 0 : totalCostMinor(view) / view.totalCalls;
}
// Çözülen çağrı başına maliyet (minor) = toplam/resolvedCalls (§18.1 cost per resolved call; resolved=0 ise 0).
export function costPerResolvedMinor(view: CostView): number {
  return view.resolvedCalls <= 0 ? 0 : totalCostMinor(view) / view.resolvedCalls;
}
// Dakika başına maliyet (minor) = toplam/billedMinutes (§18.2; billedMinutes=0 ise 0).
export function costPerMinuteMinor(view: CostView): number {
  return view.billedMinutes <= 0 ? 0 : totalCostMinor(view) / view.billedMinutes;
}
// Çözülen ≤ toplam ve >0 mı (yapısal tutarlılık; çözülen-başı maliyet ≥ çağrı-başı maliyet olmalı).
export function resolvedConsistent(view: CostView): boolean {
  return view.resolvedCalls > 0 && view.resolvedCalls <= view.totalCalls;
}

// Belirli kaynak metriğinin istatistiği (FR-ANA-013).
export function resourceStat(view: CostView, metric: ResourceMetric): ResourceStat | undefined {
  return view.resources.find((r) => r.metric === metric);
}
// Bir kaynak metriğinin P95'i bütçe içinde mi (düşük daha iyi).
export function resourceWithinBudget(view: CostView, metric: ResourceMetric): boolean {
  const r = resourceStat(view, metric);
  return r ? r.p95 <= r.budget : false;
}
// Çağrı başına bellek P95 bütçe içinde mi (≤15MB — FR-RES-016 / NFR 10.2).
export function memWithinBudget(view: CostView): boolean {
  return resourceWithinBudget(view, "memMb");
}
// Çağrı başına CPU P95 bütçe içinde mi.
export function cpuWithinBudget(view: CostView): boolean {
  return resourceWithinBudget(view, "cpuMs");
}
// Kaynak P95 ≥ P50 mi — yapısal tutarlılık (percentile monotonluğu; veri hatası yakalanır).
export function resourcePercentilesConsistent(view: CostView): boolean {
  return view.resources.every((r) => r.p95 >= r.p50);
}

// Worker density hedef (≥250 NFR 10.2) içinde mi (eşzamanlılık — FR-ANA-013).
export function densityMeetsTarget(view: CostView, min: number = DEFAULT_TARGETS.densityMin): boolean {
  return view.efficiency.density >= min;
}
// Worker density stretch (≥500 NFR 10.2) hedefini karşılıyor mu.
export function densityMeetsStretch(view: CostView, stretch: number = DEFAULT_TARGETS.densityStretch): boolean {
  return view.efficiency.density >= stretch;
}

// Zaman serisi çağrı toplamı.
export function seriesCalls(view: CostView): number {
  return view.series.reduce((a, p) => a + p.calls, 0);
}
// Zaman serisi maliyet toplamı (minor).
export function seriesCostMinor(view: CostView): number {
  return view.series.reduce((a, p) => a + p.amountMinor, 0);
}
// Seri ÇAĞRI toplamı = dönem totalCalls mi (FR-ANA-011 bütünlük invariant'ı; boş seri muaf).
export function seriesReconcilesCalls(view: CostView): boolean {
  return view.series.length === 0 || seriesCalls(view) === view.totalCalls;
}
// Seri MALİYET toplamı = dönem toplamı mı (FR-ANA-011 bütünlük invariant'ı; boş seri muaf).
export function seriesReconcilesCost(view: CostView): boolean {
  return view.series.length === 0 || seriesCostMinor(view) === totalCostMinor(view);
}
// Bir gün noktasının çağrı başına maliyeti (minor; calls=0 ise 0).
export function dayCostPerCallMinor(p: DayCost): number {
  return p.calls <= 0 ? 0 : p.amountMinor / p.calls;
}

// Zaman serisi eğilimi (ilk yarı ortalaması vs ikinci yarı ortalaması; deterministik).
export function seriesTrend(view: CostView, key: "cost" | "calls" | "cpu" | "mem", eps = TREND_FLAT_EPS): TrendDir {
  const xs = view.series;
  if (xs.length < 2) return "flat";
  const valueOf = (p: DayCost) =>
    key === "cost" ? dayCostPerCallMinor(p) : key === "calls" ? p.calls : key === "cpu" ? p.cpuMsP95 : p.memMbP95;
  const mid = Math.floor(xs.length / 2);
  const first = xs.slice(0, mid);
  const second = xs.slice(xs.length - mid);
  const avg = (arr: DayCost[]) => (arr.length === 0 ? 0 : arr.reduce((a, p) => a + valueOf(p), 0) / arr.length);
  const a = avg(first);
  const b = avg(second);
  if (a === 0) return b > 0 ? "up" : "flat";
  const rel = (b - a) / Math.abs(a);
  if (rel > eps) return "up";
  if (rel < -eps) return "down";
  return "flat";
}

// ── bant + ton (renk) eşlemeleri ────────────────────────────────────────────────────

// "Yüksek daha iyi" oran bandı (density/cache/küçük-model): ≥hedef good · ≥hedef·WARN_RATIO warn · altı bad.
export function ratioBand(value: number, target: number, warnRatio = WARN_RATIO): MetricBand {
  if (value >= target) return "good";
  if (value >= target * warnRatio) return "warn";
  return "bad";
}
// "Düşük daha iyi" metrik bandı (maliyet/CPU/bellek): ≤hedef good · ≤hedef/WARN_RATIO warn · üstü bad.
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

const COMPONENT_TONE: Record<CostComponentKey, StatusTone> = {
  stt: "info",
  llm: "info",
  tts: "info",
  telephony: "neutral",
  compute: "neutral",
};
export function componentTone(c: CostComponentKey): StatusTone {
  return COMPONENT_TONE[c];
}

// Maliyet trend tonu (DÜŞÜK daha iyi → down=iyileşme=success, up=kötüleşme=danger).
const COST_TREND_TONE: Record<TrendDir, StatusTone> = { up: "danger", down: "success", flat: "neutral" };
export function costTrendTone(d: TrendDir): StatusTone {
  return COST_TREND_TONE[d];
}
// Hacim trend tonu (yön bilgisi; nötr/info — hacim artışı iyi/kötü değildir).
const VOLUME_TREND_TONE: Record<TrendDir, StatusTone> = { up: "info", down: "info", flat: "neutral" };
export function volumeTrendTone(d: TrendDir): StatusTone {
  return VOLUME_TREND_TONE[d];
}

// ── HİJYEN + GÜVENLİK koruması (İKİ KATMAN) ─────────────────────────────────────────
// Katman 1 — YAPISAL anahtar guard: ham kimlik/iş-içeriği + sır/credential + nesne-depo URI çağrıştıran ALAN ADI
// bulunursa hata fırlatır. A-15 topluluk panosudur → tek çağrı içeriği (`text`/`transcript`/`recording`/`callRef`)
// taşımaz; yalnız agregat maliyet + per-call kaynak istatistiği + agent config.
export const FORBIDDEN_PII_KEYS: readonly string[] = [
  "callref", // A-15 tek çağrı kimliği taşımaz (topluluk panosu)
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

// Katman 2 — İÇERİK redaction desenleri: maskesiz ham PII izi. STRING değerler taranır (sayılar değil — agregat
// maliyet/kaynak sayılarının büyüklüğü redaction'ı tetiklemez); tek güvenli maskeli içerik MASK_TOKEN'dır.
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
        throw new Error(`A-15 HİJYEN ihlali: yasak PII/iş-içeriği alanı "${path}.${k}" (BRD §17.7 / FR-REC-004/005)`);
      }
      if (FORBIDDEN_SECRET_KEYS.includes(lower)) {
        throw new Error(`A-15 GÜVENLİK ihlali: sır/credential/nesne-depo URI alanı "${path}.${k}" panele konmaz (NFR 10.6)`);
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
        throw new Error(`A-15 REDACTION ihlali: maskesiz ham PII deseni "${path}" (FR-REC-004/005; agregat panoda ham PII bulunamaz)`);
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
// Deterministik yer tutucu: bir dönem maliyet + kaynak agregatı (bileşen dağılımı + agent kırılımı + çağrı başına
// CPU/bellek + verimlilik + zaman serisi). Gerçek implementasyon (F1 §14.1) Cost/Resource Meter (SAD §13.3) +
// gözlemlenebilirlik omurgası (0.4.7) + analitik/billing store (DB tenant-scope RLS) çıktısıyla beslenir. Bu örnek:
// sağlıklı bir 7 günlük dönem (çağrı başına maliyet bütçe içinde + bellek ≤15MB + density ≥500 stretch + cache iyi).
// Tek çağrı içeriği/PII YOK; yalnız agregat. Maliyet değerleri MÜHENDİSLİK ÖRNEĞİDİR (illüstratif).
const PLACEHOLDER_VIEW: CostView = {
  generatedAt: "2026-06-18T09:00:00.000Z",
  tenantRef: "TEN-2048",
  tenantName: "Kuzey Sigorta A.Ş.",
  currency: "TRY",
  period: { from: "2026-06-11", to: "2026-06-17", label: "Son 7 gün" },
  targets: { ...DEFAULT_TARGETS },
  totalCalls: 7600,
  resolvedCalls: 5400,
  billedMinutes: 22450,
  components: [
    { component: "stt", amountMinor: 1560000 },
    { component: "llm", amountMinor: 3150000 },
    { component: "tts", amountMinor: 1320000 },
    { component: "telephony", amountMinor: 2010000 },
    { component: "compute", amountMinor: 700000 },
  ],
  agents: [
    { agentRef: "AG-CALL", agentName: "Tahsilat Asistanı", calls: 4200, amountMinor: 4830000 },
    { agentRef: "AG-APPT", agentName: "Randevu Botu", calls: 2400, amountMinor: 2510000 },
    { agentRef: "AG-INFO", agentName: "Bilgi Hattı", calls: 1000, amountMinor: 1400000 },
  ],
  resources: [
    { metric: "cpuMs", p50: 95, p95: 180, budget: 250 },
    { metric: "memMb", p50: 9, p95: 13.4, budget: 15 },
  ],
  efficiency: { density: 540, cacheHitRatio: 0.64, smallModelTurnRatio: 0.58, idleReclaimRatio: 0.72 },
  series: [
    { date: "2026-06-11", calls: 1080, amountMinor: 1242000, cpuMsP95: 175, memMbP95: 13.2 },
    { date: "2026-06-12", calls: 1120, amountMinor: 1288000, cpuMsP95: 178, memMbP95: 13.4 },
    { date: "2026-06-13", calls: 940, amountMinor: 1081000, cpuMsP95: 180, memMbP95: 13.1 },
    { date: "2026-06-14", calls: 760, amountMinor: 874000, cpuMsP95: 176, memMbP95: 12.9 },
    { date: "2026-06-15", calls: 1210, amountMinor: 1391000, cpuMsP95: 182, memMbP95: 13.5 },
    { date: "2026-06-16", calls: 1190, amountMinor: 1369000, cpuMsP95: 179, memMbP95: 13.3 },
    { date: "2026-06-17", calls: 1300, amountMinor: 1495000, cpuMsP95: 180, memMbP95: 13.4 },
  ],
};

export async function getCostView(): Promise<CostView> {
  const view = PLACEHOLDER_VIEW;
  assertSafe(view); // HİJYEN + GÜVENLİK + REDACTION: yapısal PII/sır/URI yok + içerik maskesiz ham PII deseni yok
  return view;
}
