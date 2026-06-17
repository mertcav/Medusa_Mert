// WBS 13.2.1 — P-01 "Platform Genel Bakış" veri katmanı (seam) + SAF türetme yardımcıları.
//
// ÇEKİRDEK İLKELER:
//  - ALTIN KURAL (BRD §17.7 / FR-IAM-008): L0 platform konsolu YALNIZ toplulaştırılmış metrik/kaynak
//    verisi gösterir; tenant İŞ İÇERİĞİ (çağrı kaydı, transkript, müşteri/PII) GÖSTERİLMEZ. Bu modüldeki
//    tipler ve yer-tutucu veri YAPISAL OLARAK PII/iş-içeriği taşımaz; `assertNoPii` çalışma-anında doğrular.
//  - VENDOR-NEUTRAL (ADR-002): veri kaynağı bir SEAM'dir; gerçek implementasyon 0.4.7 gözlemlenebilirlik
//    omurgası (OTel/Prometheus) + Resource Manager metriklerinden cross-tenant TOPLULAŞTIRILMIŞ veri çeker.
//    Belirli sağlayıcı/SaaS bağlanmaz.
//  - SAF/DETERMİNİSTİK: türetme yardımcıları (rollupHealth/utilizationPct/...) Date.now/rastgelelik
//    içermez → birim-test edilebilir + Python aynası (screens/p01-overview/p01_overview_probe.py).
//  - İŞ MANTIĞI/AUTHZ YOK (SAD §14.4.1 A8): rol→permission kararı YOK; nihai yetki backend'de (12.2.x).

export type Health = "healthy" | "degraded" | "down";
export type Severity = "critical" | "warning" | "info";
export type Region = "uk" | "eu" | "na" | "me";

export type HealthTone = "success" | "warning" | "danger";
export type SeverityTone = "danger" | "warning" | "info";

export interface RegionHealth {
  region: Region;
  health: Health;
  concurrentCalls: number;
  utilizationPct: number;
}

export interface PlatformAlert {
  id: string;
  // i18n anahtarı (screen.p01.alert_catalog.*) — HAM metin değil; locale çağrı yerinde t() ile çözülür.
  key: string;
  severity: Severity;
  sinceMinutes: number;
}

export interface OverviewKpis {
  concurrentCalls: number;
  callsPerSecond: number;
  capacityConcurrent: number; // NFR 10.3 bölgesel eşzamanlılık tavanı
  cpuUtilizationPct: number;
  memoryUtilizationPct: number;
  workerDensity: number; // NFR 10.2 — oturum/worker
  memPerSessionMb: number; // FR-RES-016 — oturum-başı orkestratör belleği (medya hariç)
  activeTenants: number; // yalnız SAYI (kaynak verisi) — tenant iş içeriği değil
}

export interface OverviewCost {
  currency: string;
  platformCostToday: number;
  platformCostMtd: number;
  costPerMinute: number; // observability: cost_per_minute
}

export interface PlatformOverviewSnapshot {
  generatedAt: string; // ISO-8601 (sabit yer tutucu — SSR-stabil, Date.now YOK)
  kpis: OverviewKpis;
  regions: RegionHealth[];
  cost: OverviewCost;
  alerts: PlatformAlert[];
}

// ── saf türetme yardımcıları ────────────────────────────────────────────────────

// Genel platform sağlığı = en-kötü bölge (worst-of rollup). Boş → healthy.
export function rollupHealth(regions: RegionHealth[]): Health {
  if (regions.some((r) => r.health === "down")) return "down";
  if (regions.some((r) => r.health === "degraded")) return "degraded";
  return "healthy";
}

// Kullanım yüzdesi: [0,100]'e kıstırılmış, 1 ondalık. capacity≤0 → 0.
export function utilizationPct(used: number, capacity: number): number {
  if (capacity <= 0) return 0;
  const pct = (used / capacity) * 100;
  return Math.min(100, Math.max(0, Math.round(pct * 10) / 10));
}

// Boş kapasite (negatif olamaz).
export function headroom(used: number, capacity: number): number {
  return Math.max(0, capacity - used);
}

const HEALTH_TONE: Record<Health, HealthTone> = {
  healthy: "success",
  degraded: "warning",
  down: "danger",
};
export function healthTone(h: Health): HealthTone {
  return HEALTH_TONE[h];
}

const SEVERITY_TONE: Record<Severity, SeverityTone> = {
  critical: "danger",
  warning: "warning",
  info: "info",
};
export function severityTone(s: Severity): SeverityTone {
  return SEVERITY_TONE[s];
}

// ── ALTIN KURAL koruması (PII/iş-içeriği sızıntısı) ──────────────────────────────
// Snapshot yapısı içinde tenant iş içeriği/PII'yi çağrıştıran ALAN ADI bulunursa hata fırlatır.
// Bu, P-01'in yalnız toplulaştırılmış metrik göstermesini çalışma-anında garanti eder (BRD §17.7).
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
        throw new Error(`P-01 ALTIN KURAL ihlali: yasak PII/iş-içeriği alanı "${path}.${k}" (BRD §17.7)`);
      }
      assertNoPii((node as Record<string, unknown>)[k], `${path}.${k}`);
    }
  }
}

// ── veri SEAM (yer tutucu) ───────────────────────────────────────────────────────
// Deterministik yer tutucu: cross-tenant TOPLULAŞTIRILMIŞ metrik (PII/iş-içeriği DEĞİL). Gerçek
// implementasyon (F2 §14.1) 0.4.7 gözlemlenebilirlik omurgası + Resource Manager'dan beslenir.
const PLACEHOLDER_SNAPSHOT: PlatformOverviewSnapshot = {
  generatedAt: "2026-06-17T09:00:00.000Z",
  kpis: {
    concurrentCalls: 6240,
    callsPerSecond: 78,
    capacityConcurrent: 10000, // NFR 10.3
    cpuUtilizationPct: 64.0,
    memoryUtilizationPct: 58.0,
    workerDensity: 420, // NFR 10.2 (≥250, stretch ≥500)
    memPerSessionMb: 12.4, // FR-RES-016 (≤15MB)
    activeTenants: 37,
  },
  regions: [
    { region: "eu", health: "healthy", concurrentCalls: 2980, utilizationPct: 62.1 },
    { region: "uk", health: "healthy", concurrentCalls: 1610, utilizationPct: 54.7 },
    { region: "na", health: "degraded", concurrentCalls: 1280, utilizationPct: 71.4 },
    { region: "me", health: "healthy", concurrentCalls: 370, utilizationPct: 33.2 },
  ],
  cost: {
    currency: "USD",
    platformCostToday: 4820.5,
    platformCostMtd: 71640.25,
    costPerMinute: 0.038,
  },
  alerts: [
    { id: "AL-1042", key: "screen.p01.alert_catalog.provider_error", severity: "warning", sinceMinutes: 18 },
    { id: "AL-1043", key: "screen.p01.alert_catalog.region_capacity", severity: "warning", sinceMinutes: 7 },
  ],
};

export async function getPlatformOverview(): Promise<PlatformOverviewSnapshot> {
  const snap = PLACEHOLDER_SNAPSHOT;
  assertNoPii(snap); // ALTIN KURAL: yapısal PII/iş-içeriği yok (BRD §17.7)
  return snap;
}
