// WBS 13.2.3 — P-03 "Kaynak & Kapasite Yönetimi" veri katmanı (seam) + SAF türetme yardımcıları.
//
// ÇEKİRDEK İLKELER (P-01/P-02 ile aynı disiplin; lib/platform/overview.ts + tenants.ts):
//  - ALTIN KURAL (BRD §17.7 / FR-IAM-008): L0 platform konsolu YALNIZ kaynak/kapasite metadatası
//    (tenant org adı, plan, bölge, kota=eşzamanlılık/CPS/vCPU/bellek, izolasyon, scale-to-zero durumu)
//    gösterir; tenant İŞ İÇERİĞİ (çağrı kaydı, transkript, son-müşteri/PII) GÖSTERİLMEZ. Tipler YAPISAL
//    OLARAK iş-içeriği/PII taşımaz; `assertNoPii` çalışma-anında doğrular. NOT: "tenant org adı" tenant
//    kimliğidir (RMC müşterisi), L0'da izinlidir; yasaklanan, tenant'ın SON-MÜŞTERİ verisidir.
//  - VENDOR-NEUTRAL (ADR-002): veri kaynağı bir SEAM'dir; gerçek implementasyon (F2 §14.1) Resource
//    Manager (SAD §15.2: Quota Service · Autoscaler · Scale-to-zero Ctrl · Backpressure Ctrl ·
//    Cost/Resource Meter) + 0.4.7 gözlemlenebilirlik omurgasından beslenir. Belirli sağlayıcı bağlanmaz.
//  - SAF/DETERMİNİSTİK: türetme yardımcıları (utilizationPct/utilizationTone/headroomPct/aggregateQuota/
//    regionConcurrencyUsed/scaleStateTone/isolationTone/noisyNeighborRisks) Date.now/rastgelelik içermez
//    → birim-test edilebilir + Python aynası (screens/p03-resources/p03_resources_probe.py).
//  - İŞ MANTIĞI/AUTHZ YOK (SAD §14.4.1 A8): kota/politika aksiyonları (kotayı düzenle / politikayı düzenle)
//    UI'da yalnız görsel kapıdır; nihai yetki + zorlama backend'de Resource Manager Quota Service'te (12.2.x).
//    RBAC (BRD §17.6): bu ekran `platform_owner`=Yönet + `platform_sre`=Yönet (billing=erişim yok).

export type Region = "uk" | "eu" | "na" | "me";

// Vendor-neutral plan tier'ları (BRD enterprise/dedicated tier diline hizalı; sağlayıcı bağlamaz).
export type Plan = "starter" | "growth" | "enterprise" | "dedicated";

// StatusPill/Alert ile hizalı ton kümesi.
export type Tone = "success" | "warning" | "info" | "danger" | "neutral";

// Noisy-neighbor koruması: rezerve concurrency (izole) vs paylaşımlı havuz (SAD §16.2).
export type IsolationMode = "reserved" | "shared";

// Scale-to-zero kontrolü (FR-RES-007): aktif=trafik var · idle=boşta, sayaç işliyor · scaled_to_zero=sıfıra indi.
export type ScaleToZeroState = "active" | "idle" | "scaled_to_zero";

// Kullanım/kota çifti (eşzamanlılık, CPS, vCPU, bellek). used ≤/> limit olabilir (aşım = breach).
export interface QuotaPair {
  limit: number;
  used: number;
}

export type QuotaField = "concurrency" | "cps" | "vcpu" | "memoryGb";

export interface TenantResource {
  id: string;
  name: string; // tenant org adı (tenant kimliği — L0'da izinli; son-müşteri PII'si DEĞİL)
  plan: Plan;
  region: Region;
  concurrency: QuotaPair; // eş zamanlı çağrı kotası (NFR 10.3 tenant izolasyonu)
  cps: QuotaPair; // saniye başına çağrı (call-per-second) kotası (NFR 10.3)
  vcpu: QuotaPair; // vCPU kotası (FR-RES-016 · SAD §15.2 Quota Service)
  memoryGb: QuotaPair; // bellek (GB) kotası
  reservedConcurrency: number; // rezerve concurrency (noisy-neighbor koruması, SAD §16.2)
  isolation: IsolationMode;
  scaleToZero: ScaleToZeroState; // FR-RES-007
}

// Global otomatik ölçekleme + scale-to-zero politikası (SAD §16.1/§16.2, FR-RES-007/013, NFR 10.3).
export interface AutoscalePolicy {
  minWorkers: number;
  maxWorkers: number;
  targetUtilizationPct: number; // HPA hedef kullanımı (SAD §16.1)
  warmPool: number; // cold-start azaltma (FR-RES-013)
  scaleToZeroIdleSeconds: number; // boşta küçültme penceresi (FR-RES-007)
  burstMultiplier: number; // ani trafik çarpanı (NFR 10.3 2x)
}

// Bölge başına kapasite (NFR 10.3: region başına 10.000 eşzamanlı / 100 CPS).
export interface RegionCapacity {
  region: Region;
  concurrencyCapacity: number; // region eş zamanlı tavanı
  cpsCapacity: number; // region CPS tavanı
  activeWorkers: number;
  maxWorkers: number;
}

export interface ResourcesSnapshot {
  generatedAt: string; // ISO-8601 (sabit yer tutucu — SSR-stabil, Date.now YOK)
  autoscale: AutoscalePolicy;
  regions: RegionCapacity[];
  tenants: TenantResource[];
}

// Paylaşımlı izolasyonda bu eşik üstü eş-zamanlı kullanım → noisy-neighbor riski (izlenir).
export const NOISY_NEIGHBOR_UTIL_PCT = 85;

// ── saf türetme yardımcıları ────────────────────────────────────────────────────

// Kullanım yüzdesi: [0,∞)'a izin verir (aşım görünür) ama alt sınır 0; 1 ondalık. limit≤0 → 0.
export function utilizationPct(used: number, limit: number): number {
  if (limit <= 0) return 0;
  const pct = (used / limit) * 100;
  return Math.max(0, Math.round(pct * 10) / 10);
}

// Headroom (kalan kapasite) yüzdesi: 100 - util, [0,100]'e kıstırılmış.
export function headroomPct(used: number, limit: number): number {
  const h = 100 - utilizationPct(used, limit);
  return Math.min(100, Math.max(0, Math.round(h * 10) / 10));
}

// Kullanım tonu: ≥90 danger (kritik) · ≥75 warning (yüksek) · aksi success.
export function utilizationTone(pct: number): Tone {
  if (pct >= 90) return "danger";
  if (pct >= 75) return "warning";
  return "success";
}

const ISOLATION_TONE: Record<IsolationMode, Tone> = {
  reserved: "success", // rezerve = korumalı
  shared: "warning", // paylaşımlı = noisy-neighbor riskine açık
};
export function isolationTone(mode: IsolationMode): Tone {
  return ISOLATION_TONE[mode];
}

const SCALE_STATE_TONE: Record<ScaleToZeroState, Tone> = {
  active: "success",
  idle: "info",
  scaled_to_zero: "neutral",
};
export function scaleStateTone(s: ScaleToZeroState): Tone {
  return SCALE_STATE_TONE[s];
}

// Tüm tenant'lar üzerinde bir kota alanının toplamı (platform kapasite özeti KPI'sı).
export function aggregateQuota(tenants: TenantResource[], field: QuotaField): QuotaPair {
  const acc: QuotaPair = { limit: 0, used: 0 };
  for (const t of tenants) {
    acc.limit += t[field].limit;
    acc.used += t[field].used;
  }
  return acc;
}

// Bir bölgedeki tenant'ların eş zamanlı kullanım toplamı (region kullanım yüzdesi için).
export function regionConcurrencyUsed(tenants: TenantResource[], region: Region): number {
  return tenants
    .filter((t) => t.region === region)
    .reduce((sum, t) => sum + t.concurrency.used, 0);
}

// Noisy-neighbor riski: paylaşımlı izolasyon + eş-zamanlı kullanım ≥ eşik (id listesi).
export function noisyNeighborRisks(tenants: TenantResource[]): string[] {
  return tenants
    .filter(
      (t) =>
        t.isolation === "shared" &&
        utilizationPct(t.concurrency.used, t.concurrency.limit) >= NOISY_NEIGHBOR_UTIL_PCT,
    )
    .map((t) => t.id);
}

// ── ALTIN KURAL koruması (iş-içeriği/son-müşteri PII sızıntısı) ───────────────────
// Snapshot yapısı içinde tenant İŞ İÇERİĞİ/SON-MÜŞTERİ PII'sini çağrıştıran ALAN ADI bulunursa hata
// fırlatır. Bu, P-03'ün yalnız kaynak/kapasite metadatası göstermesini çalışma-anında garanti eder
// (BRD §17.7). NOT: tenant org "name" alanı tenant kimliğidir (izinli); listede yasak değildir.
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
        throw new Error(`P-03 ALTIN KURAL ihlali: yasak iş-içeriği/PII alanı "${path}.${k}" (BRD §17.7)`);
      }
      assertNoPii((node as Record<string, unknown>)[k], `${path}.${k}`);
    }
  }
}

// ── veri SEAM (yer tutucu) ───────────────────────────────────────────────────────
// Deterministik yer tutucu: kaynak/kapasite metadatası (iş-içeriği/PII DEĞİL). Gerçek implementasyon
// (F2 §14.1) Resource Manager (SAD §15.2) + 0.4.7 gözlemlenebilirlik omurgasından beslenir.
const PLACEHOLDER_SNAPSHOT: ResourcesSnapshot = {
  generatedAt: "2026-06-17T09:00:00.000Z",
  autoscale: {
    minWorkers: 4,
    maxWorkers: 240,
    targetUtilizationPct: 70,
    warmPool: 12,
    scaleToZeroIdleSeconds: 900,
    burstMultiplier: 2,
  },
  regions: [
    { region: "eu", concurrencyCapacity: 10000, cpsCapacity: 100, activeWorkers: 96, maxWorkers: 240 },
    { region: "uk", concurrencyCapacity: 10000, cpsCapacity: 100, activeWorkers: 72, maxWorkers: 240 },
    { region: "na", concurrencyCapacity: 10000, cpsCapacity: 100, activeWorkers: 18, maxWorkers: 200 },
    { region: "me", concurrencyCapacity: 6000, cpsCapacity: 60, activeWorkers: 6, maxWorkers: 120 },
  ],
  tenants: [
    { id: "tn_acme", name: "Acme Finans A.Ş.", plan: "enterprise", region: "eu", concurrency: { limit: 1200, used: 1090 }, cps: { limit: 24, used: 19 }, vcpu: { limit: 64, used: 51 }, memoryGb: { limit: 128, used: 96 }, reservedConcurrency: 800, isolation: "reserved", scaleToZero: "active" },
    { id: "tn_globex", name: "Globex Telekom", plan: "dedicated", region: "uk", concurrency: { limit: 3000, used: 1840 }, cps: { limit: 60, used: 31 }, vcpu: { limit: 160, used: 88 }, memoryGb: { limit: 320, used: 171 }, reservedConcurrency: 3000, isolation: "reserved", scaleToZero: "active" },
    { id: "tn_initech", name: "Initech Sigorta", plan: "growth", region: "eu", concurrency: { limit: 400, used: 372 }, cps: { limit: 10, used: 9 }, vcpu: { limit: 24, used: 21 }, memoryGb: { limit: 48, used: 41 }, reservedConcurrency: 0, isolation: "shared", scaleToZero: "active" },
    { id: "tn_hooli", name: "Hooli Perakende", plan: "starter", region: "me", concurrency: { limit: 150, used: 0 }, cps: { limit: 5, used: 0 }, vcpu: { limit: 8, used: 0 }, memoryGb: { limit: 16, used: 0 }, reservedConcurrency: 0, isolation: "shared", scaleToZero: "scaled_to_zero" },
    { id: "tn_umbrella", name: "Umbrella Sağlık", plan: "enterprise", region: "na", concurrency: { limit: 800, used: 60 }, cps: { limit: 16, used: 2 }, vcpu: { limit: 48, used: 7 }, memoryGb: { limit: 96, used: 12 }, reservedConcurrency: 400, isolation: "reserved", scaleToZero: "idle" },
    { id: "tn_soylent", name: "Soylent Lojistik", plan: "growth", region: "eu", concurrency: { limit: 300, used: 96 }, cps: { limit: 8, used: 3 }, vcpu: { limit: 16, used: 6 }, memoryGb: { limit: 32, used: 11 }, reservedConcurrency: 0, isolation: "shared", scaleToZero: "active" },
  ],
};

export async function getResources(): Promise<ResourcesSnapshot> {
  const snap = PLACEHOLDER_SNAPSHOT;
  assertNoPii(snap); // ALTIN KURAL: yapısal iş-içeriği/son-müşteri PII yok (BRD §17.7)
  return snap;
}
