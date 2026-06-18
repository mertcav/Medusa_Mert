// WBS 13.3.7 — T-07 "Faturalandırma & Kullanım" veri katmanı (seam) + SAF türetme yardımcıları
// (L1 — Tenant Admin Console).
//
// ÇEKİRDEK İLKELER:
//  - İÇERİK (BRD §17.4 / FR-BIL-001..007): tenant'ın PLAN (fiyat planı + faturalama modeli + minimum ücret +
//    para birimi), KULLANIM (dakika/saniye bazlı tüketim — FR-BIL-001), MALİYET KIRILIMI (telekom/STT/TTS/LLM/
//    platform ayrı izleme — FR-BIL-002), KOTA & OVERAGE (kullanım kotası + aşım — FR-BIL-004), BÜTÇE ALARMI
//    (kullanım limiti + bütçe eşikleri — FR-BIL-006) ve FATURA AKTARIMI (finans sistemine aktarım durumu —
//    FR-BIL-007) görünümü. Dedicated altyapı ayrı faturalandırma bayrağı (FR-BIL-005).
//  - TENANT-SCOPE (FR-TEN-002): T-07 YALNIZ oturum açan tenant'ın KENDİ plan/kullanım/maliyet görünümünü
//    gösterir; başka tenant'ın faturası erişilmez. Scope çalışma-anında middleware (13.1.2) + RLS (§13) ile
//    sabitlenir; UI yalnız görsel kapı (SAD §14.4.1 A8).
//  - HİJYEN (BRD §17.7): yapı yalnız tenant'ın KENDİ PLAN/KULLANIM TOPLULAŞTIRMASIDIR (plan adı, faturalanan
//    dakika, dönem maliyeti, bütçe eşiği). Ham SON-MÜŞTERİ iş içeriği (çağrı kaydı, transkript, çağrı-bazlı
//    CDR satırı, müşteri PII/numarası) buraya GÖMÜLMEZ — bunlar L2/data-plane'de tutulur. Maliyet/kullanım
//    YALNIZ tenant-bütünü TOPLULAŞTIRMADIR. `assertNoPii` çalışma-anında doğrular.
//  - GÜVENLİK (NFR 10.6): SIR/FİNANSAL credential buraya KONMAZ — ödeme yöntemi token'ı, kart PAN'ı, IBAN/
//    banka hesabı, finans sistemi API credential'ı panele konmaz; yalnız durum + topluluk metrik. Fiyat/maliyet
//    değerleri MÜHENDİSLİK ÖRNEĞİDİR (illüstratif); gerçek rate-card finans/billing motorundan beslenir.
//  - VENDOR-NEUTRAL (ADR-002): veri kaynağı bir SEAM'dir; gerçek implementasyon (F2 §14.1) Billing/Rating
//    motoru + kullanım toplulaştırma (metering) + L0 Platform Faturalandırma (P-05) rate-card'ından
//    tenant-scope (RLS) beslenir. Belirli telekom/STT/TTS/LLM sağlayıcı maliyeti adapter SPI arkasında.
//  - SAF/DETERMİNİSTİK: türetme yardımcıları (budgetRatio/overBudget/quotaOverageMinutes/triggeredAlarms/...)
//    Date.now/rastgelelik içermez → birim-test edilebilir + Python aynası (screens/t07-billing/t07_billing_probe.py).
//  - İŞ MANTIĞI/AUTHZ YOK (SAD §14.4.1 A8): plan değiştirme/bütçe alarmı kaydetme kararı YOK; nihai yetki
//    backend'de (12.2.x) + RLS. Panel yalnız çözümlenmiş plan/kullanım görünümünü gösterir + eşik aşımını işaretler.

export type Currency = "TRY" | "USD" | "EUR" | "GBP"; // plan.currency
export type BillingModel = "per_minute" | "per_second" | "tiered" | "flat"; // FR-BIL-001
export type PlanTier = "pilot" | "standard" | "enterprise" | "dedicated"; // plan.tier
export type CostCategory = "telecom" | "stt" | "tts" | "llm" | "platform"; // FR-BIL-002 (ayrı izleme)
export type InvoiceExportStatus = "synced" | "pending" | "failed" | "not_configured"; // FR-BIL-007

export type StatusTone = "success" | "warning" | "danger" | "neutral" | "info";

// Plan (FR-BIL-003 tenant fiyat planı + FR-BIL-004 minimum ücret + FR-BIL-005 dedicated altyapı).
export interface PlanConfig {
  planName: string; // plan ADI (ör. "Enterprise-Aylık") — son-müşteri verisi DEĞİL
  tier: PlanTier; // pilot/standard/enterprise/dedicated
  billingModel: BillingModel; // FR-BIL-001 (dakika/saniye/tier/sabit)
  currency: Currency; // para birimi
  minimumCharge: number; // FR-BIL-004 minimum ücret (dönem tabanı)
  billingPeriod: string; // dönem etiketi (ör. "monthly")
  dedicatedInfra: boolean; // FR-BIL-005 dedicated altyapı ayrı faturalandırılır
}

// Kullanım (FR-BIL-001 dakika ve saniye bazında). Yalnız tenant-bütünü TOPLULAŞTIRMA — çağrı-bazlı CDR DEĞİL.
export interface UsageConfig {
  periodLabel: string; // dönem (ör. "2026-06")
  billedMinutes: number; // faturalanan dakika (topluluk)
  billedSeconds: number; // dakika-altı saniye kalanı (FR-BIL-001 saniye granülerliği)
  includedMinutes: number; // plana dahil kota dakikası (FR-BIL-004 kullanım kotası)
  callCount: number; // dönem çağrı adedi (topluluk metadatası — çağrı kaydı DEĞİL)
}

// Maliyet bileşeni (FR-BIL-002): telekom/STT/TTS/LLM/platform AYRI izlenir. amount = dönem maliyeti (para birimi).
export interface CostComponent {
  category: CostCategory; // telecom/stt/tts/llm/platform
  amount: number; // dönem maliyeti
}

// Kota aşımı / overage (FR-BIL-004). overageEnabled=false + kota aşımı => çağrı kısıtlanır (overageBlocked).
export interface OverageConfig {
  overageEnabled: boolean; // kota aşımına izin var mı
  overageRate: number; // aşım birim ücreti (gösterim)
  overageMinutes: number; // faturalanan aşım dakikası (topluluk)
  overageAmount: number; // aşım maliyeti (para birimi)
}

// Bütçe alarmı eşiği (FR-BIL-006). channel = bildirim kanalı ADI (ör. "billing_owner_email") — credential DEĞİL.
export interface BudgetAlarm {
  id: string;
  thresholdPct: number; // bütçe yüzdesi eşiği (ör. 80)
  channel: string; // bildirim kanalı ADI — sır DEĞİL
}

// Bütçe & kullanım limiti (FR-BIL-006). spentAmount = dönem harcaması (tenant-bütünü TOPLULAŞTIRMA).
export interface BudgetConfig {
  budgetAmount: number; // dönem bütçesi (para birimi)
  spentAmount: number; // dönem harcaması (faturalanan)
  usageLimitMinutes: number; // sert kullanım limiti (dakika) — 0 = limit yok
  alarms: BudgetAlarm[]; // bütçe alarm eşikleri
}

// Fatura aktarımı (FR-BIL-007). target = finans sistemi ADI (ör. "ERP-GL") — API credential DEĞİL.
export interface InvoiceExportConfig {
  status: InvoiceExportStatus; // synced/pending/failed/not_configured
  target: string; // finans sistemi ADI — sır DEĞİL
  lastSync: string; // son aktarım zamanı (ISO-8601 / etiket)
}

export interface BillingSnapshot {
  generatedAt: string; // ISO-8601 (sabit yer tutucu — SSR-stabil, Date.now YOK)
  tenantRef: string; // tenant'ın KENDİ kimliği (L1'de izinli)
  tenantName: string; // tenant org adı (izinli; son-müşteri verisi DEĞİL)
  plan: PlanConfig;
  usage: UsageConfig;
  costs: CostComponent[];
  overage: OverageConfig;
  budget: BudgetConfig;
  invoiceExport: InvoiceExportConfig;
}

// Maliyet uzlaşı toleransı: |maliyet bileşen toplamı − harcama| bu eşiği aşarsa uzlaşı boşluğu (FR-BIL-002).
export const COST_RECONCILE_TOLERANCE = 0.5;

// ── saf türetme yardımcıları ────────────────────────────────────────────────────

// Maliyet bileşen toplamı (FR-BIL-002): telekom + STT + TTS + LLM + platform.
export function costTotal(costs: CostComponent[]): number {
  return costs.reduce((acc, c) => acc + c.amount, 0);
}

// Bileşen payı (0..1): kategori maliyeti / toplam. Toplam 0 ise 0.
export function costShare(costs: CostComponent[], category: CostCategory): number {
  const total = costTotal(costs);
  if (total <= 0) return 0;
  const part = costs.filter((c) => c.category === category).reduce((acc, c) => acc + c.amount, 0);
  return part / total;
}

// Bütçe tüketim oranı (FR-BIL-006): harcama / bütçe. Bütçe ≤0 ise 0 (tanımsız bütçe).
export function budgetRatio(b: BudgetConfig): number {
  if (b.budgetAmount <= 0) return 0;
  return b.spentAmount / b.budgetAmount;
}

// BÜTÇE AŞIMI (danger): harcama dönem bütçesini geçti (FR-BIL-006).
export function overBudget(b: BudgetConfig): boolean {
  return b.budgetAmount > 0 && b.spentAmount > b.budgetAmount;
}

// BÜTÇE YAKLAŞIYOR (warning): tüketim oranı [0.8, 1.0] aralığında (aşmadan eşiğe yaklaşıyor).
export function budgetApproaching(b: BudgetConfig): boolean {
  const r = budgetRatio(b);
  return r >= 0.8 && r <= 1.0;
}

// TETİKLENEN ALARMLAR: tüketim oranı eşiği (thresholdPct) aşan alarm id'leri (FR-BIL-006). Sıralı.
export function triggeredAlarms(b: BudgetConfig): string[] {
  const pct = budgetRatio(b) * 100;
  return b.alarms.filter((a) => pct >= a.thresholdPct).map((a) => a.id);
}

// ALARM BOŞLUĞU (warning): bütçe tanımlı (>0) ama hiç alarm eşiği yok (FR-BIL-006 yapılandırılmamış).
export function unconfiguredAlarms(b: BudgetConfig): boolean {
  return b.budgetAmount > 0 && b.alarms.length === 0;
}

// KOTA AŞIM DAKİKASI (FR-BIL-004): faturalanan dakika − plana dahil kota (negatif değilse). 0 = aşım yok.
export function quotaOverageMinutes(u: UsageConfig): number {
  const over = u.billedMinutes - u.includedMinutes;
  return over > 0 ? over : 0;
}

// OVERAGE ENGELLENDİ (warning): kota aşıldı ama overage KAPALI → çağrılar limitlenir (FR-BIL-004).
export function overageBlocked(u: UsageConfig, o: OverageConfig): boolean {
  return quotaOverageMinutes(u) > 0 && !o.overageEnabled;
}

// KULLANIM LİMİTİ AŞIMI (danger): sert kullanım limiti tanımlı ve faturalanan dakika aştı (FR-BIL-006).
export function usageLimitExceeded(u: UsageConfig, b: BudgetConfig): boolean {
  return b.usageLimitMinutes > 0 && u.billedMinutes > b.usageLimitMinutes;
}

// MALİYET UZLAŞI BOŞLUĞU (danger): bileşen toplamı ile harcama tutmuyor (FR-BIL-002 ayrı izleme tutarlılığı).
export function costMismatch(snap: BillingSnapshot): boolean {
  return Math.abs(costTotal(snap.costs) - snap.budget.spentAmount) > COST_RECONCILE_TOLERANCE;
}

// PLAN TUTARSIZLIĞI: yanlış konfigürasyon (negatif minimum ücret / boş plan adı). Alan adı listesi.
export function invalidPlan(p: PlanConfig): string[] {
  const out: string[] = [];
  if (p.minimumCharge < 0) out.push("minimum_charge");
  if (p.planName.trim() === "") out.push("plan_name");
  return out;
}

// FATURA AKTARIM HATASI (danger): aktarım başarısız (FR-BIL-007).
export function invoiceExportFailed(e: InvoiceExportConfig): boolean {
  return e.status === "failed";
}

// FATURA AKTARIM YAPILANDIRILMAMIŞ (warning): aktarım hedefi tanımsız (FR-BIL-007).
export function invoiceExportUnconfigured(e: InvoiceExportConfig): boolean {
  return e.status === "not_configured";
}

// Toplam açık uyarı sayısı (KPI): tüm danger + warning türlerinin toplamı.
export function openWarningCount(snap: BillingSnapshot): number {
  return (
    (overBudget(snap.budget) ? 1 : 0) +
    (usageLimitExceeded(snap.usage, snap.budget) ? 1 : 0) +
    (budgetApproaching(snap.budget) ? 1 : 0) +
    (unconfiguredAlarms(snap.budget) ? 1 : 0) +
    (overageBlocked(snap.usage, snap.overage) ? 1 : 0) +
    (costMismatch(snap) ? 1 : 0) +
    (invoiceExportFailed(snap.invoiceExport) ? 1 : 0) +
    (invoiceExportUnconfigured(snap.invoiceExport) ? 1 : 0) +
    invalidPlan(snap.plan).length
  );
}

// ── ton (renk) eşlemeleri ─────────────────────────────────────────────────────────

// Bütçe oranı tonu: >1.0 danger · ≥0.8 warning · aksi success.
export function budgetRatioTone(ratio: number): StatusTone {
  if (ratio > 1.0) return "danger";
  if (ratio >= 0.8) return "warning";
  return "success";
}

const INVOICE_STATUS_TONE: Record<InvoiceExportStatus, StatusTone> = {
  synced: "success",
  pending: "warning",
  failed: "danger",
  not_configured: "neutral",
};
export function invoiceStatusTone(s: InvoiceExportStatus): StatusTone {
  return INVOICE_STATUS_TONE[s];
}

const TIER_TONE: Record<PlanTier, StatusTone> = {
  pilot: "neutral",
  standard: "neutral",
  enterprise: "info",
  dedicated: "info",
};
export function tierTone(t: PlanTier): StatusTone {
  return TIER_TONE[t];
}

// Overage tonu: açık => info (aşıma izin) · kapalı => neutral.
export function overageTone(enabled: boolean): StatusTone {
  return enabled ? "info" : "neutral";
}

// Alarm satır tonu: tetiklendi => warning · aksi neutral.
export function alarmTriggeredTone(triggered: boolean): StatusTone {
  return triggered ? "warning" : "neutral";
}

// ── HİJYEN + GÜVENLİK koruması ─────────────────────────────────────────────────────
// Yapı içinde son-müşteri iş içeriği/PII'yi VEYA sır/finansal credential çağrıştıran ALAN ADI bulunursa hata
// fırlatır. Bu, T-07'nin yalnız tenant'ın KENDİ plan/kullanım TOPLULAŞTIRMASINI (çağrı-bazlı CDR/PII/ödeme
// credential'ı DEĞİL) göstermesini çalışma-anında garanti eder (BRD §17.7 + NFR 10.6).
export const FORBIDDEN_PII_KEYS: readonly string[] = [
  "transcript",
  "recording",
  "recordingurl",
  "audio",
  "msisdn",
  "phonenumber",
  "callerid",
  "callernumber",
  "customer",
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
  "token",
  "bearertoken",
  "accesstoken",
  "refreshtoken",
  "credential",
  "password",
  "privatekey",
  "kmskey",
  "iban",
  "bankaccount",
  "paymentmethod",
  "paymenttoken",
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
        throw new Error(`T-07 HİJYEN ihlali: yasak PII/iş-içeriği alanı "${path}.${k}" (BRD §17.7)`);
      }
      if (FORBIDDEN_SECRET_KEYS.includes(lower)) {
        throw new Error(`T-07 GÜVENLİK ihlali: sır/finansal credential alanı "${path}.${k}" panele konmaz (NFR 10.6)`);
      }
      assertNoPii((node as Record<string, unknown>)[k], `${path}.${k}`);
    }
  }
}

// ── veri SEAM (yer tutucu) ───────────────────────────────────────────────────────
// Deterministik yer tutucu: tek-tenant plan/kullanım/maliyet görünümü (KENDİ plan + dönem kullanım
// topluluğu + maliyet kırılımı + bütçe alarmı + fatura aktarım durumu — son-müşteri CDR/PII DEĞİL, ödeme
// SIR'ı DEĞİL). Gerçek implementasyon (F2 §14.1) Billing/Rating motoru + metering (kullanım toplulaştırma) +
// L0 P-05 rate-card'ından tenant-scope (RLS) beslenir. Fiyat/maliyet değerleri İLLÜSTRATİFTİR.
const PLACEHOLDER_SNAPSHOT: BillingSnapshot = {
  generatedAt: "2026-06-18T09:00:00.000Z",
  tenantRef: "TEN-2048",
  tenantName: "Kuzey Sigorta A.Ş.",
  plan: {
    planName: "Enterprise-Aylık",
    tier: "enterprise",
    billingModel: "per_minute",
    currency: "TRY",
    minimumCharge: 5000,
    billingPeriod: "monthly",
    dedicatedInfra: true,
  },
  usage: {
    periodLabel: "2026-06",
    billedMinutes: 48230,
    billedSeconds: 40,
    includedMinutes: 50000,
    callCount: 12840,
  },
  costs: [
    { category: "telecom", amount: 18200 },
    { category: "stt", amount: 6400 },
    { category: "tts", amount: 5900 },
    { category: "llm", amount: 9800 },
    { category: "platform", amount: 4500 },
  ],
  overage: {
    overageEnabled: true,
    overageRate: 1.2,
    overageMinutes: 0,
    overageAmount: 0,
  },
  budget: {
    budgetAmount: 60000,
    spentAmount: 44800,
    usageLimitMinutes: 60000,
    alarms: [
      { id: "AL-1", thresholdPct: 80, channel: "billing_owner_email" },
      { id: "AL-2", thresholdPct: 100, channel: "finance_webhook" },
    ],
  },
  invoiceExport: {
    status: "synced",
    target: "ERP-GL",
    lastSync: "2026-06-01T02:00:00.000Z",
  },
};

export async function getBilling(): Promise<BillingSnapshot> {
  const snap = PLACEHOLDER_SNAPSHOT;
  assertNoPii(snap); // HİJYEN + GÜVENLİK: yapısal son-müşteri PII / ödeme sırrı yok (BRD §17.7 / NFR 10.6)
  return snap;
}
