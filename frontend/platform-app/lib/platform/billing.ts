// WBS 13.2.5 — P-05 "Platform Faturalandırma & Rate-Card" veri katmanı (seam) + SAF türetme yardımcıları.
//
// ÇEKİRDEK İLKELER (P-01..P-04 ile aynı disiplin; lib/platform/overview.ts + tenants.ts + resources.ts + providers.ts):
//  - ALTIN KURAL (BRD §17.7 / FR-IAM-008): L0 platform konsolu YALNIZ faturalandırma/plan/rate-card metadatası
//    ve TOPLULAŞTIRILMIŞ kullanım (dakika, gelir, sağlayıcı maliyeti, marj) gösterir; tenant İŞ İÇERİĞİ (çağrı
//    kaydı, transkript, son-müşteri/PII) GÖSTERİLMEZ. Tipler YAPISAL OLARAK iş-içeriği/PII taşımaz; `assertNoPii`
//    çalışma-anında doğrular. NOT: tenant ORG ADI tenant kimliğidir (izinli, P-02 ile aynı kural); yasaklanan
//    SON-MÜŞTERİ verisidir.
//  - VENDOR-NEUTRAL (ADR-002): rate-card kategorileri (telephony/stt/tts/llm/platform) ve plan tier'ları SOMUT
//    sağlayıcı/marka bağlamaz; veri kaynağı bir SEAM'dir. Gerçek implementasyon (F2 §14.1 / WBS 15.x) Billing &
//    Usage servisi (FR-BIL-001 dakika/saniye ölçüm + FR-BIL-002 telekom/STT/TTS/LLM/platform ayrı maliyet) +
//    Cost-Resource Meter (SAD §8.1 meter() / §15.2) + 0.4.7 gözlemlenebilirlik omurgasından beslenir.
//  - SAF/DETERMİNİSTİK: türetme yardımcıları (marginPct/marginTone/budgetTone/billingStatusTone/planStatusTone/
//    overageMinutes/rateMarginPct/aggregateUsage/overBudgetTenants/planTenantCount/countByBillingStatus)
//    Date.now/rastgelelik içermez → birim-test edilebilir + Python aynası (screens/p05-billing/p05_billing_probe.py).
//  - İŞ MANTIĞI/AUTHZ YOK (SAD §14.4.1 A8): rate-card/plan düzenleme + finans dışa aktarım (FR-BIL-007) aksiyonları
//    UI'da yalnız görsel kapıdır; nihai yetki + zorlama backend'de (12.2.x; permission-key `billing:read` +
//    `billing:rate_card:manage` + `billing:plan:manage` + `billing:export`, SAD §7). RBAC (BRD §17.6): bu ekran
//    `platform_owner`=Görüntüle + `platform_sre`=erişim yok + `platform_billing`=Yönet.

export type Region = "uk" | "eu" | "na" | "me";

// Rate-card kategorileri (FR-BIL-002: telekom/STT/TTS/LLM/platform maliyeti AYRI izlenir). Vendor-nötr.
export type RateCategory = "telephony" | "stt" | "tts" | "llm" | "platform";

// Birim (FR-BIL-001 dakika/saniye + sağlayıcı birim çeşitliliği; vendor-nötr).
export type CostUnit = "minute" | "kchars" | "ktokens" | "session";

// Plan tier'ı (vendor-nötr; somut ticari marka değil). FR-BIL-003 tenant fiyat planı.
export type PlanTier = "starter" | "growth" | "scale" | "enterprise";

// Plan durumu: active=atanabilir · deprecated=yeni atamaya kapalı (mevcut tenant'lar grandfathered).
export type PlanStatus = "active" | "deprecated";

// Tenant faturalandırma durumu (toplulaştırılmış): current=normal · over_budget=bütçe aşıldı (FR-BIL-006) ·
// suspended=askıda (ödeme/provisioning).
export type BillingStatus = "current" | "over_budget" | "suspended";

// StatusPill/Alert ile hizalı ton kümesi.
export type Tone = "success" | "warning" | "info" | "danger" | "neutral";

// Para birimi (ISO 4217 kodu; vendor-nötr gösterim — formatCurrency ile yerelleştirilir).
export type Currency = "USD" | "EUR" | "GBP" | "TRY";

// Rate-card satırı: kategori başına satış birim ücreti + altta yatan sağlayıcı birim maliyeti (marj kaynağı).
export interface RateCardEntry {
  category: RateCategory; // FR-BIL-002 ayrı izlenen maliyet kategorisi
  unit: CostUnit;
  unitRate: number; // platform satış birim ücreti (rate-card)
  unitCost: number; // altta yatan sağlayıcı birim maliyeti (marj = rate - cost)
}

// Plan tanımı (FR-BIL-003 fiyat planı + FR-BIL-004 minimum ücret/kota/overage + FR-BIL-006 bütçe alarmı eşiği).
export interface Plan {
  id: string;
  tier: PlanTier;
  name: string; // vendor-nötr plan etiketi (RMC iç adı); somut ticari marka DEĞİL
  monthlyBase: number; // FR-BIL-004 aylık minimum/taban ücret
  includedMinutes: number; // dahil dakika kotası (FR-BIL-004)
  overageRatePerMinute: number; // FR-BIL-004 kota aşımı (overage) dakika ücreti
  budgetAlertThresholdPct: number; // FR-BIL-006 bütçe alarmı eşiği (yüzde)
  activeTenants: number; // bu plana atanmış tenant SAYISI (toplulaştırılmış; PII değil)
  status: PlanStatus;
}

// Cross-tenant TOPLULAŞTIRILMIŞ kullanım/gelir özeti (MTD). FR-BIL-001 dakika ölçümü + FR-BIL-002 maliyet.
export interface UsageRollup {
  billedMinutes: number; // toplam faturalanan dakika (FR-BIL-001)
  revenue: number; // brüt gelir (ay-başından bugüne)
  providerCost: number; // toplam sağlayıcı maliyeti (FR-BIL-002; telekom+STT+TTS+LLM+platform)
}

// Tenant başına TOPLULAŞTIRILMIŞ faturalandırma özeti — kayıt/kullanım metadatası; SON-MÜŞTERİ PII YOK.
export interface TenantBillingSummary {
  tenantId: string;
  tenantName: string; // tenant org adı = tenant kimliği (izinli; son-müşteri verisi DEĞİL)
  planId: string;
  region: Region;
  billedMinutes: number; // bu tenant'ın faturalanan dakikası (FR-BIL-001)
  includedMinutes: number; // planın dahil kotası (overage hesabı için)
  budgetUsedPct: number; // bütçe kullanım yüzdesi (FR-BIL-006)
  status: BillingStatus;
}

export interface BillingSnapshot {
  generatedAt: string; // ISO-8601 (sabit yer tutucu — SSR-stabil, Date.now YOK)
  currency: Currency;
  rateCard: RateCardEntry[];
  plans: Plan[];
  usage: UsageRollup;
  tenants: TenantBillingSummary[];
}

// Bütçe alarmı eşikleri (FR-BIL-006): ≥%100 danger (aşıldı) · ≥%80 warning (yaklaşıyor) · aksi success.
export const BUDGET_DANGER_PCT = 100;
export const BUDGET_WARNING_PCT = 80;

// Marj eşikleri: ≥%30 success (sağlıklı) · ≥%15 warning (ince) · aksi danger (zarar riski).
export const MARGIN_HEALTHY_PCT = 30;
export const MARGIN_WARNING_PCT = 15;

// ── saf türetme yardımcıları ────────────────────────────────────────────────────

// Brüt marj yüzdesi: (gelir - maliyet) / gelir × 100. Gelir 0 → 0 (tanımsızlığı önler).
export function marginPct(revenue: number, cost: number): number {
  if (revenue <= 0) return 0;
  return ((revenue - cost) / revenue) * 100;
}

// Marj tonu: ≥30 success · ≥15 warning · aksi danger.
export function marginTone(pct: number): Tone {
  if (pct >= MARGIN_HEALTHY_PCT) return "success";
  if (pct >= MARGIN_WARNING_PCT) return "warning";
  return "danger";
}

// Bütçe kullanım tonu (FR-BIL-006): ≥100 danger · ≥80 warning · aksi success.
export function budgetTone(pct: number): Tone {
  if (pct >= BUDGET_DANGER_PCT) return "danger";
  if (pct >= BUDGET_WARNING_PCT) return "warning";
  return "success";
}

const BILLING_STATUS_TONE: Record<BillingStatus, Tone> = {
  current: "success",
  over_budget: "warning",
  suspended: "danger",
};
export function billingStatusTone(s: BillingStatus): Tone {
  return BILLING_STATUS_TONE[s];
}

const PLAN_STATUS_TONE: Record<PlanStatus, Tone> = {
  active: "success",
  deprecated: "neutral",
};
export function planStatusTone(s: PlanStatus): Tone {
  return PLAN_STATUS_TONE[s];
}

// Kota aşımı dakikası (FR-BIL-004 overage): max(0, faturalanan - dahil). Negatif (kota altı) → 0.
export function overageMinutes(billed: number, included: number): number {
  return Math.max(0, billed - included);
}

// Rate-card satır marjı: (satış - maliyet) / satış × 100. Satış 0 → 0.
export function rateMarginPct(e: RateCardEntry): number {
  return marginPct(e.unitRate, e.unitCost);
}

// Cross-tenant toplulaştırma: faturalanan dakika + overage dakika toplamı (FR-BIL-001/004).
export function aggregateUsage(tenants: TenantBillingSummary[]): {
  billedMinutes: number;
  overageMinutes: number;
} {
  return tenants.reduce(
    (acc, t) => ({
      billedMinutes: acc.billedMinutes + t.billedMinutes,
      overageMinutes: acc.overageMinutes + overageMinutes(t.billedMinutes, t.includedMinutes),
    }),
    { billedMinutes: 0, overageMinutes: 0 },
  );
}

// Bütçesi aşılmış tenant id'leri (FR-BIL-006: budgetUsedPct ≥ %100). Özet/uyarı için.
export function overBudgetTenants(snap: BillingSnapshot): string[] {
  return snap.tenants.filter((t) => t.budgetUsedPct >= BUDGET_DANGER_PCT).map((t) => t.tenantId);
}

// Bir plana atanmış tenant sayısı (plan tanımındaki toplulaştırılmış sayım — kayıt SAYISI, PII değil).
export function planTenantCount(plans: Plan[], planId: string): number {
  return plans.find((p) => p.id === planId)?.activeTenants ?? 0;
}

// Faturalandırma durumuna göre tenant sayımı (özet KPI: current/over_budget/suspended).
export function countByBillingStatus(tenants: TenantBillingSummary[]): Record<BillingStatus, number> {
  const acc: Record<BillingStatus, number> = { current: 0, over_budget: 0, suspended: 0 };
  for (const t of tenants) acc[t.status] += 1;
  return acc;
}

// Aktif (atanabilir) plan sayısı.
export function activePlanCount(plans: Plan[]): number {
  return plans.filter((p) => p.status === "active").length;
}

// Plan adı çözümleme (id → görünen ad); bulunamazsa id döner.
export function planName(plans: Plan[], planId: string): string {
  return plans.find((p) => p.id === planId)?.name ?? planId;
}

// ── ALTIN KURAL koruması (iş-içeriği/son-müşteri PII sızıntısı) ───────────────────
// Snapshot yapısı içinde tenant İŞ İÇERİĞİ/SON-MÜŞTERİ PII'sini çağrıştıran ALAN ADI bulunursa hata
// fırlatır. Bu, P-05'in yalnız faturalandırma/plan/rate-card + TOPLULAŞTIRILMIŞ kullanım metadatası
// göstermesini çalışma-anında garanti eder (BRD §17.7). NOT: tenant "tenantName" (org adı) tenant
// kimliğidir (izinli); listede değildir. Yasaklanan SON-MÜŞTERİ verisidir.
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
  "iban",
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
        throw new Error(`P-05 ALTIN KURAL ihlali: yasak iş-içeriği/PII alanı "${path}.${k}" (BRD §17.7)`);
      }
      assertNoPii((node as Record<string, unknown>)[k], `${path}.${k}`);
    }
  }
}

// ── veri SEAM (yer tutucu) ───────────────────────────────────────────────────────
// Deterministik yer tutucu: faturalandırma/plan/rate-card + toplulaştırılmış kullanım metadatası (iş-içeriği/PII
// DEĞİL). Kategori/plan adları VENDOR-NÖTR (somut marka değil; ADR-002). Gerçek implementasyon (F2 §14.1 / WBS 15.x)
// Billing & Usage servisi (FR-BIL-001/002) + Cost-Resource Meter (SAD §8.1/§15.2) + 0.4.7 gözlemlenebilirlik
// omurgasından beslenir. NOT: plan.activeTenants platform-geneli sayımdır; alttaki tenant listesi en yüksek
// kullanımlı tenant'ların özetidir (ikisi bağımsız toplulaştırma).
const PLACEHOLDER_SNAPSHOT: BillingSnapshot = {
  generatedAt: "2026-06-17T09:00:00.000Z",
  currency: "USD",
  rateCard: [
    { category: "telephony", unit: "minute", unitRate: 0.025, unitCost: 0.011 },
    { category: "stt", unit: "minute", unitRate: 0.018, unitCost: 0.0072 },
    { category: "tts", unit: "kchars", unitRate: 0.04, unitCost: 0.015 },
    { category: "llm", unit: "ktokens", unitRate: 0.008, unitCost: 0.0026 },
    { category: "platform", unit: "minute", unitRate: 0.02, unitCost: 0.005 },
  ],
  plans: [
    { id: "starter", tier: "starter", name: "Başlangıç", monthlyBase: 99.0, includedMinutes: 1000, overageRatePerMinute: 0.12, budgetAlertThresholdPct: 80, activeTenants: 8, status: "active" },
    { id: "growth", tier: "growth", name: "Büyüme", monthlyBase: 499.0, includedMinutes: 7500, overageRatePerMinute: 0.1, budgetAlertThresholdPct: 85, activeTenants: 5, status: "active" },
    { id: "scale", tier: "scale", name: "Ölçek", monthlyBase: 1999.0, includedMinutes: 40000, overageRatePerMinute: 0.08, budgetAlertThresholdPct: 90, activeTenants: 3, status: "active" },
    { id: "enterprise", tier: "enterprise", name: "Kurumsal", monthlyBase: 7500.0, includedMinutes: 150000, overageRatePerMinute: 0.06, budgetAlertThresholdPct: 90, activeTenants: 2, status: "active" },
    { id: "starter-legacy", tier: "starter", name: "Başlangıç (eski)", monthlyBase: 79.0, includedMinutes: 800, overageRatePerMinute: 0.14, budgetAlertThresholdPct: 80, activeTenants: 1, status: "deprecated" },
  ],
  usage: { billedMinutes: 176640, revenue: 24850.0, providerCost: 9320.0 },
  tenants: [
    { tenantId: "t-001", tenantName: "Kuzey Bank A.Ş.", planId: "growth", region: "eu", billedMinutes: 8200, includedMinutes: 7500, budgetUsedPct: 76, status: "current" },
    { tenantId: "t-002", tenantName: "Meridyen Sigorta", planId: "scale", region: "uk", billedMinutes: 38000, includedMinutes: 40000, budgetUsedPct: 64, status: "current" },
    { tenantId: "t-003", tenantName: "Atlas Perakende", planId: "starter", region: "eu", billedMinutes: 1340, includedMinutes: 1000, budgetUsedPct: 104, status: "over_budget" },
    { tenantId: "t-004", tenantName: "Doğu Lojistik", planId: "enterprise", region: "me", billedMinutes: 120000, includedMinutes: 150000, budgetUsedPct: 58, status: "current" },
    { tenantId: "t-005", tenantName: "Vega Telekom", planId: "growth", region: "na", billedMinutes: 9100, includedMinutes: 7500, budgetUsedPct: 92, status: "current" },
  ],
};

export async function getBilling(): Promise<BillingSnapshot> {
  const snap = PLACEHOLDER_SNAPSHOT;
  assertNoPii(snap); // ALTIN KURAL: yapısal iş-içeriği/son-müşteri PII yok (BRD §17.7)
  return snap;
}
