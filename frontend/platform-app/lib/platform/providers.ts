// WBS 13.2.4 — P-04 "Sağlayıcı & Entegrasyon Sağlığı" veri katmanı (seam) + SAF türetme yardımcıları.
//
// ÇEKİRDEK İLKELER (P-01/P-02/P-03 ile aynı disiplin; lib/platform/overview.ts + tenants.ts + resources.ts):
//  - ALTIN KURAL (BRD §17.7 / FR-IAM-008): L0 platform konsolu YALNIZ sağlayıcı/adapter SAĞLIK ve
//    YÖNLENDİRME metadatası (kategori, rol, sağlık durumu, circuit breaker, hata oranı, p95 gecikme,
//    fallback sırası, kategori maliyeti) gösterir; tenant İŞ İÇERİĞİ (çağrı kaydı, transkript, son-müşteri/
//    PII) GÖSTERİLMEZ. Tipler YAPISAL OLARAK iş-içeriği/PII taşımaz; `assertNoPii` çalışma-anında doğrular.
//    NOT: adapter "name" alanı VENDOR-NÖTR görünen ad (RMC iç etiketi); somut sağlayıcı markası bağlanmaz.
//  - VENDOR-NEUTRAL (ADR-002): kategori başına ≥2 sağlayıcı + fallback (BRD §19). Bu ekran SOMUT sağlayıcı
//    seçmez/markalamaz; veri kaynağı bir SEAM'dir. Gerçek implementasyon (F2 §14.1) Provider Adapter SPI
//    (SAD §8.1: health()/meter() + circuit breaker/fallback SAD §8.2/§8.3) + 0.4.7 gözlemlenebilirlik
//    omurgasından (provider error rate / latency / dakika maliyeti, SAD §17) beslenir.
//  - SAF/DETERMİNİSTİK: türetme yardımcıları (healthTone/circuitTone/errorRateTone/rollupHealth/
//    categoryHealth/redundancyOk/redundancyRisks/isFallbackActive/activeFallbackCount/openCircuitCount/
//    countByHealth/aggregateCost) Date.now/rastgelelik içermez → birim-test edilebilir + Python aynası
//    (screens/p04-providers/p04_providers_probe.py).
//  - İŞ MANTIĞI/AUTHZ YOK (SAD §14.4.1 A8): routing/fallback varsayılanı aksiyonları (yönlendirmeyi düzenle)
//    UI'da yalnız görsel kapıdır; nihai yetki + zorlama backend'de (12.2.x; permission-key `provider:health:read`
//    + `provider:routing:manage`, SAD §7). RBAC (BRD §17.6): bu ekran `platform_owner`=Yönet +
//    `platform_sre`=Yönet + `platform_billing`=Görüntüle.

export type Region = "uk" | "eu" | "na" | "me";

// Hot-path sağlayıcı kategorileri (BRD §17.3: STT/TTS/LLM/telekom adapter durumu). Vendor-nötr.
export type ProviderCategory = "stt" | "tts" | "llm" | "telephony";

// Fallback zincirindeki rol (SAD §8.3: Primary → Secondary → Deterministic flow).
export type AdapterRole = "primary" | "secondary";

// Adapter sağlık durumu (SAD §8.1 health()): healthy=sağlıklı · degraded=kısmi · down=hizmet dışı.
export type HealthState = "healthy" | "degraded" | "down";

// Circuit breaker durumu (SAD §8.2): closed=normal · half_open=deneme · open=kesik (fallback'e yönlendirir).
export type CircuitState = "closed" | "half_open" | "open";

// Kategori maliyet birimi (vendor-nötr; SAD §8.1 meter()): dakika / 1k karakter / 1k token.
export type CostUnit = "minute" | "kchars" | "ktokens";

// StatusPill/Alert ile hizalı ton kümesi.
export type Tone = "success" | "warning" | "info" | "danger" | "neutral";

export interface Adapter {
  id: string;
  category: ProviderCategory;
  role: AdapterRole;
  name: string; // vendor-NÖTR görünen ad (RMC iç etiketi); somut marka DEĞİL
  region: Region;
  health: HealthState; // SAD §8.1 health()
  circuit: CircuitState; // SAD §8.2 circuit breaker
  errorRatePct: number; // SAD §17 provider error rate (yüzde, [0,100])
  p95LatencyMs: number; // SAD §20 medya/zincir bütçesine göre p95 gecikme
}

export interface CategoryCost {
  today: number; // bugünkü sağlayıcı maliyeti (para birimi-nötr gösterim)
  mtd: number; // ay-başından-bugüne (month-to-date)
  unit: CostUnit; // birim (dakika/1k karakter/1k token)
  unitCost: number; // birim başına maliyet
}

// Kategori başına yönlendirme/fallback varsayılanı (SAD §8.3; BRD §19 ≥2 sağlayıcı + kontrollü fallback).
export interface CategoryRouting {
  category: ProviderCategory;
  primaryId: string; // birincil adapter id
  fallbackOrder: string[]; // fallback adapter id sırası (secondary → ...)
  deterministicFallback: boolean; // deterministic flow fallback mevcut mu (FR-LLM-010 / SAD §8.3)
  cost: CategoryCost;
}

export interface ProvidersSnapshot {
  generatedAt: string; // ISO-8601 (sabit yer tutucu — SSR-stabil, Date.now YOK)
  categories: CategoryRouting[];
  adapters: Adapter[];
}

// Hata oranı eşikleri: ≥%5 danger (kritik) · ≥%1 warning (yüksek) · aksi success.
export const ERROR_RATE_DANGER_PCT = 5;
export const ERROR_RATE_WARNING_PCT = 1;

// BRD §19: kategori başına en az bu kadar çalışır (down olmayan) sağlayıcı → fallback dayanıklılığı.
export const MIN_OPERATIONAL_PROVIDERS = 2;

// ── saf türetme yardımcıları ────────────────────────────────────────────────────

const HEALTH_TONE: Record<HealthState, Tone> = {
  healthy: "success",
  degraded: "warning",
  down: "danger",
};
export function healthTone(s: HealthState): Tone {
  return HEALTH_TONE[s];
}

const CIRCUIT_TONE: Record<CircuitState, Tone> = {
  closed: "success",
  half_open: "warning",
  open: "danger",
};
export function circuitTone(s: CircuitState): Tone {
  return CIRCUIT_TONE[s];
}

// Hata oranı tonu: ≥5 danger · ≥1 warning · aksi success.
export function errorRateTone(pct: number): Tone {
  if (pct >= ERROR_RATE_DANGER_PCT) return "danger";
  if (pct >= ERROR_RATE_WARNING_PCT) return "warning";
  return "success";
}

// Sağlık ciddiyet sırası (worst-of toplulaştırma için): down > degraded > healthy.
const HEALTH_RANK: Record<HealthState, number> = { healthy: 0, degraded: 1, down: 2 };

// Bir sağlık kümesinin en-kötüsü (rollup). Boş küme → healthy (gösterecek adapter yok).
export function rollupHealth(states: HealthState[]): HealthState {
  let worst: HealthState = "healthy";
  for (const s of states) {
    if (HEALTH_RANK[s] > HEALTH_RANK[worst]) worst = s;
  }
  return worst;
}

// Bir kategorinin adapter'ları (snapshot.adapters filtresi).
export function categoryAdapters(adapters: Adapter[], category: ProviderCategory): Adapter[] {
  return adapters.filter((a) => a.category === category);
}

// Kategori sağlığı: o kategorideki adapter'ların worst-of sağlığı.
export function categoryHealth(adapters: Adapter[], category: ProviderCategory): HealthState {
  return rollupHealth(categoryAdapters(adapters, category).map((a) => a.health));
}

// BRD §19 dayanıklılık: kategoride ≥ MIN_OPERATIONAL_PROVIDERS çalışır (down olmayan) sağlayıcı.
export function redundancyOk(adapters: Adapter[], category: ProviderCategory): boolean {
  const operational = categoryAdapters(adapters, category).filter((a) => a.health !== "down").length;
  return operational >= MIN_OPERATIONAL_PROVIDERS;
}

// Dayanıklılık riski taşıyan kategoriler (≥2 çalışır sağlayıcı kuralını karşılamayanlar).
export function redundancyRisks(snap: ProvidersSnapshot): ProviderCategory[] {
  return snap.categories.map((c) => c.category).filter((cat) => !redundancyOk(snap.adapters, cat));
}

// Bir kategoride fallback AKTİF mi: birincil adapter down VEYA circuit açık → trafik secondary'ye gider.
export function isFallbackActive(snap: ProvidersSnapshot, category: ProviderCategory): boolean {
  const routing = snap.categories.find((c) => c.category === category);
  if (!routing) return false;
  const primary = snap.adapters.find((a) => a.id === routing.primaryId);
  if (!primary) return true; // birincil tanımlı ama bulunamıyor → fallback'e düşmüş kabul
  return primary.health === "down" || primary.circuit === "open";
}

// Fallback'in aktif olduğu kategori sayısı (özet KPI).
export function activeFallbackCount(snap: ProvidersSnapshot): number {
  return snap.categories.filter((c) => isFallbackActive(snap, c.category)).length;
}

// Circuit'i açık (kesik) adapter sayısı.
export function openCircuitCount(adapters: Adapter[]): number {
  return adapters.filter((a) => a.circuit === "open").length;
}

// Sağlık durumuna göre adapter sayımı (özet KPI: healthy/degraded/down).
export function countByHealth(adapters: Adapter[]): Record<HealthState, number> {
  const acc: Record<HealthState, number> = { healthy: 0, degraded: 0, down: 0 };
  for (const a of adapters) acc[a.health] += 1;
  return acc;
}

// Tüm kategoriler üzerinde maliyet toplamı (today + mtd). Birim heterojen olduğundan unitCost toplanmaz.
export function aggregateCost(categories: CategoryRouting[]): { today: number; mtd: number } {
  return categories.reduce(
    (acc, c) => ({ today: acc.today + c.cost.today, mtd: acc.mtd + c.cost.mtd }),
    { today: 0, mtd: 0 },
  );
}

// ── ALTIN KURAL koruması (iş-içeriği/son-müşteri PII sızıntısı) ───────────────────
// Snapshot yapısı içinde tenant İŞ İÇERİĞİ/SON-MÜŞTERİ PII'sini çağrıştıran ALAN ADI bulunursa hata
// fırlatır. Bu, P-04'ün yalnız sağlayıcı/adapter sağlık+yönlendirme metadatası göstermesini çalışma-anında
// garanti eder (BRD §17.7). NOT: adapter "name" alanı vendor-nötr iç etikettir (izinli); listede değildir.
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
        throw new Error(`P-04 ALTIN KURAL ihlali: yasak iş-içeriği/PII alanı "${path}.${k}" (BRD §17.7)`);
      }
      assertNoPii((node as Record<string, unknown>)[k], `${path}.${k}`);
    }
  }
}

// ── veri SEAM (yer tutucu) ───────────────────────────────────────────────────────
// Deterministik yer tutucu: sağlayıcı/adapter sağlık + yönlendirme + maliyet metadatası (iş-içeriği/PII
// DEĞİL). Adapter adları VENDOR-NÖTR (somut marka değil; BRD §19/ADR-002). Gerçek implementasyon (F2 §14.1)
// Provider Adapter SPI health()/meter() (SAD §8.1) + 0.4.7 gözlemlenebilirlik omurgasından beslenir.
const PLACEHOLDER_SNAPSHOT: ProvidersSnapshot = {
  generatedAt: "2026-06-17T09:00:00.000Z",
  categories: [
    { category: "telephony", primaryId: "telephony-a", fallbackOrder: ["telephony-b"], deterministicFallback: false, cost: { today: 412.5, mtd: 8920.0, unit: "minute", unitCost: 0.011 } },
    { category: "stt", primaryId: "stt-a", fallbackOrder: ["stt-b"], deterministicFallback: false, cost: { today: 286.2, mtd: 6140.0, unit: "minute", unitCost: 0.0072 } },
    { category: "tts", primaryId: "tts-a", fallbackOrder: ["tts-b"], deterministicFallback: false, cost: { today: 318.9, mtd: 6730.0, unit: "kchars", unitCost: 0.015 } },
    { category: "llm", primaryId: "llm-a", fallbackOrder: ["llm-b", "llm-small"], deterministicFallback: true, cost: { today: 524.1, mtd: 11240.0, unit: "ktokens", unitCost: 0.0026 } },
  ],
  adapters: [
    { id: "telephony-a", category: "telephony", role: "primary", name: "Telekom Sağlayıcı A", region: "eu", health: "healthy", circuit: "closed", errorRatePct: 0.2, p95LatencyMs: 48 },
    { id: "telephony-b", category: "telephony", role: "secondary", name: "Telekom Sağlayıcı B", region: "eu", health: "healthy", circuit: "closed", errorRatePct: 0.4, p95LatencyMs: 61 },
    { id: "stt-a", category: "stt", role: "primary", name: "STT Sağlayıcı A", region: "eu", health: "healthy", circuit: "closed", errorRatePct: 0.6, p95LatencyMs: 180 },
    { id: "stt-b", category: "stt", role: "secondary", name: "STT Sağlayıcı B", region: "uk", health: "healthy", circuit: "closed", errorRatePct: 0.9, p95LatencyMs: 210 },
    { id: "tts-a", category: "tts", role: "primary", name: "TTS Sağlayıcı A", region: "eu", health: "degraded", circuit: "half_open", errorRatePct: 2.4, p95LatencyMs: 240 },
    { id: "tts-b", category: "tts", role: "secondary", name: "TTS Sağlayıcı B", region: "eu", health: "healthy", circuit: "closed", errorRatePct: 0.5, p95LatencyMs: 190 },
    { id: "llm-a", category: "llm", role: "primary", name: "LLM Sağlayıcı A (büyük)", region: "eu", health: "down", circuit: "open", errorRatePct: 14.8, p95LatencyMs: 980 },
    { id: "llm-b", category: "llm", role: "secondary", name: "LLM Sağlayıcı B (büyük)", region: "eu", health: "healthy", circuit: "closed", errorRatePct: 0.7, p95LatencyMs: 360 },
    { id: "llm-small", category: "llm", role: "secondary", name: "LLM Sağlayıcı C (küçük/hızlı)", region: "eu", health: "healthy", circuit: "closed", errorRatePct: 0.3, p95LatencyMs: 150 },
  ],
};

export async function getProviders(): Promise<ProvidersSnapshot> {
  const snap = PLACEHOLDER_SNAPSHOT;
  assertNoPii(snap); // ALTIN KURAL: yapısal iş-içeriği/son-müşteri PII yok (BRD §17.7)
  return snap;
}
