// WBS 13.3.1 — T-01 "Tenant Dashboard" veri katmanı (seam) + SAF türetme yardımcıları (L1 — Tenant Admin).
//
// ÇEKİRDEK İLKELER:
//  - TENANT-SCOPE (FR-TEN-002): T-01 YALNIZ oturum açan tenant'ın KENDİ toplulaştırılmış KPI/kullanım/
//    maliyet/kota verisini gösterir; başka tenant'a ait veri erişilmez. Scope çalışma-anında middleware
//    (13.1.2) + RLS (§13) ile sabitlenir; UI yalnız görsel kapı (SAD §14.4.1 A8). tenantRef/tenantName
//    tenant'ın KENDİ kimliğidir (L1'de izinli).
//  - DASHBOARD HİJYENİ (BRD §17.7 ruhu): panel yalnız TOPLULAŞTIRILMIŞ metrik gösterir; ham son-müşteri
//    iş içeriği (çağrı kaydı, transkript, müşteri/PII) panele GÖMÜLMEZ — bunlar L2 ekranlarında
//    (A-11/A-12) ayrıca yetkiyle görülür. Tipler yapısal olarak PII taşımaz; `assertNoPii` çalışma-anında
//    doğrular (sızıntı → hata).
//  - VENDOR-NEUTRAL (ADR-002): veri kaynağı bir SEAM'dir; gerçek implementasyon (F2 §14.1) 0.4.7
//    gözlemlenebilirlik omurgası (OTel/Prometheus) + Billing & Usage + Resource Manager'dan tenant-scope
//    TOPLULAŞTIRILMIŞ veri çeker. Belirli sağlayıcı/SaaS bağlanmaz.
//  - SAF/DETERMİNİSTİK: türetme yardımcıları (utilizationPct/headroom/quotaTone/...) Date.now/rastgelelik
//    içermez → birim-test edilebilir + Python aynası (screens/t01-dashboard/t01_dashboard_probe.py).
//  - İŞ MANTIĞI/AUTHZ YOK (SAD §14.4.1 A8): rol→permission kararı YOK; nihai yetki backend'de (12.2.x) + RLS.

export type Health = "healthy" | "degraded" | "down";
export type Channel = "inbound" | "outbound";
export type QuotaResource = "concurrent_calls" | "cps" | "compute_vcpu" | "compute_memory_gb";

export type HealthTone = "success" | "warning" | "danger";
export type UtilTone = "success" | "warning" | "danger";

// Tenant operasyonel KPI'ları (toplulaştırılmış — son-müşteri içeriği DEĞİL).
export interface TenantKpis {
  callsToday: number;
  callsMtd: number;
  containmentPct: number; // FR-ANA: AI containment (insan aktarımı olmadan tamamlanan)
  avgHandleSeconds: number; // AHT — ortalama görüşme süresi
  csat: number; // 1–5 ölçek
  successRatePct: number; // başarı/çözüm oranı
  activeAgents: number; // aktif agent SAYISI (kaynak verisi)
}

export interface UsageChannel {
  channel: Channel;
  calls: number;
  minutes: number;
}

export interface TenantCost {
  currency: string;
  costToday: number;
  costMtd: number;
  costPerMinute: number;
  budgetMtd: number; // plan bütçesi (FR-BIL-004)
  spentMtd: number; // bütçeye karşı harcanan (FR-BIL-006 bütçe alarmı türetmesi)
}

// L0 tarafından ATANAN kapasite kotası + tenant tüketimi (BRD §17.4 / T-09 ile hizalı).
export interface QuotaLine {
  resource: QuotaResource;
  used: number;
  limit: number;
  unit: string;
}

export interface TenantDashboardSnapshot {
  generatedAt: string; // ISO-8601 (sabit yer tutucu — SSR-stabil, Date.now YOK)
  tenantRef: string; // tenant'ın KENDİ kimliği (L1'de izinli)
  tenantName: string; // tenant org adı = tenant kimliği (izinli; son-müşteri verisi DEĞİL)
  plan: string;
  region: string;
  health: Health;
  kpis: TenantKpis;
  usage: UsageChannel[];
  cost: TenantCost;
  quota: QuotaLine[];
}

// ── saf türetme yardımcıları ────────────────────────────────────────────────────

// Kullanım yüzdesi: [0,100]'e kıstırılmış, 1 ondalık. limit≤0 → 0.
export function utilizationPct(used: number, limit: number): number {
  if (limit <= 0) return 0;
  const pct = (used / limit) * 100;
  return Math.min(100, Math.max(0, Math.round(pct * 10) / 10));
}

// Boş kota (negatif olamaz).
export function headroom(used: number, limit: number): number {
  return Math.max(0, limit - used);
}

// Bütçe kullanım yüzdesi: ALT sınır 0, ÜST sınır YOK (aşım görünür kalır — FR-BIL-006). budget≤0 → 0.
export function budgetUsagePct(spent: number, budget: number): number {
  if (budget <= 0) return 0;
  return Math.max(0, Math.round((spent / budget) * 1000) / 10);
}

const HEALTH_TONE: Record<Health, HealthTone> = {
  healthy: "success",
  degraded: "warning",
  down: "danger",
};
export function healthTone(h: Health): HealthTone {
  return HEALTH_TONE[h];
}

// Kullanım tonu (kota/kapasite): ≥90 danger · ≥75 warning · aksi success (P-03 ile hizalı).
export function utilTone(pct: number): UtilTone {
  if (pct >= 90) return "danger";
  if (pct >= 75) return "warning";
  return "success";
}

// Bütçe tonu: ≥100 danger · ≥80 warning · aksi success (FR-BIL-006 bütçe alarmı eşiği).
export function budgetTone(pct: number): UtilTone {
  if (pct >= 100) return "danger";
  if (pct >= 80) return "warning";
  return "success";
}

// Toplam kullanım (kanal kırılımından): çağrı + dakika.
export function aggregateUsage(usage: UsageChannel[]): { calls: number; minutes: number } {
  return usage.reduce(
    (acc, u) => ({ calls: acc.calls + u.calls, minutes: acc.minutes + u.minutes }),
    { calls: 0, minutes: 0 },
  );
}

// En-kötü kota tonu (kotalardan worst-of) — özet sağlık göstergesi.
export function worstQuotaTone(quota: QuotaLine[]): UtilTone {
  let worst: UtilTone = "success";
  for (const q of quota) {
    const tone = utilTone(utilizationPct(q.used, q.limit));
    if (tone === "danger") return "danger";
    if (tone === "warning") worst = "warning";
  }
  return worst;
}

// ── DASHBOARD HİJYENİ koruması (ham PII/iş-içeriği sızıntısı) ─────────────────────
// Snapshot yapısı içinde son-müşteri iş içeriği/PII'yi çağrıştıran ALAN ADI bulunursa hata fırlatır.
// Bu, T-01'in yalnız toplulaştırılmış metrik göstermesini çalışma-anında garanti eder (BRD §17.7 ruhu).
// NOT: tenantName/tenantRef tenant'ın KENDİ kimliğidir → yasak listede DEĞİL (izinli).
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
        throw new Error(`T-01 DASHBOARD HİJYENİ ihlali: yasak PII/iş-içeriği alanı "${path}.${k}" (BRD §17.7)`);
      }
      assertNoPii((node as Record<string, unknown>)[k], `${path}.${k}`);
    }
  }
}

// ── veri SEAM (yer tutucu) ───────────────────────────────────────────────────────
// Deterministik yer tutucu: tek-tenant TOPLULAŞTIRILMIŞ metrik (PII/iş-içeriği DEĞİL). Gerçek
// implementasyon (F2 §14.1) 0.4.7 gözlemlenebilirlik omurgası + Billing & Usage + Resource Manager'dan
// tenant-scope beslenir (RLS ile sabitlenmiş).
const PLACEHOLDER_SNAPSHOT: TenantDashboardSnapshot = {
  generatedAt: "2026-06-17T09:00:00.000Z",
  tenantRef: "TEN-2048",
  tenantName: "Kuzey Sigorta A.Ş.",
  plan: "scale",
  region: "eu",
  health: "healthy",
  kpis: {
    callsToday: 1840,
    callsMtd: 38210,
    containmentPct: 72.5, // FR-ANA containment
    avgHandleSeconds: 184,
    csat: 4.3,
    successRatePct: 88.1,
    activeAgents: 12,
  },
  usage: [
    { channel: "inbound", calls: 1420, minutes: 4380 },
    { channel: "outbound", calls: 420, minutes: 1190 },
  ],
  cost: {
    currency: "EUR",
    costToday: 312.4,
    costMtd: 6840.75,
    costPerMinute: 0.029,
    budgetMtd: 9000.0,
    spentMtd: 6840.75,
  },
  quota: [
    { resource: "concurrent_calls", used: 180, limit: 300, unit: "" },
    { resource: "cps", used: 14, limit: 25, unit: "" },
    { resource: "compute_vcpu", used: 38, limit: 64, unit: "vCPU" },
    { resource: "compute_memory_gb", used: 96, limit: 128, unit: "GB" },
  ],
};

export async function getTenantDashboard(): Promise<TenantDashboardSnapshot> {
  const snap = PLACEHOLDER_SNAPSHOT;
  assertNoPii(snap); // DASHBOARD HİJYENİ: yapısal PII/iş-içeriği yok (BRD §17.7)
  return snap;
}
