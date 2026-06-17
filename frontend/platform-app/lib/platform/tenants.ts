// WBS 13.2.2 — P-02 "Tenant Yönetimi & Provisioning" veri katmanı (seam) + SAF türetme yardımcıları.
//
// ÇEKİRDEK İLKELER (P-01 ile aynı disiplin; lib/platform/overview.ts):
//  - ALTIN KURAL (BRD §17.7 / FR-IAM-008): L0 platform konsolu YALNIZ tenant kayıt/kaynak metadatası
//    (tenant org adı, plan, durum, bölge, oluşturma tarihi, kullanıcı SAYISI) gösterir; tenant İŞ İÇERİĞİ
//    (çağrı kaydı, transkript, son-müşteri/PII) GÖSTERİLMEZ. Tipler YAPISAL OLARAK iş-içeriği/PII taşımaz;
//    `assertNoPii` çalışma-anında doğrular. NOT: "tenant org adı" tenant kimliğidir (RMC müşterisi), L0'da
//    izinlidir; yasaklanan, tenant'ın SON-MÜŞTERİ verisidir (FORBIDDEN_PII_KEYS).
//  - VENDOR-NEUTRAL (ADR-002): veri kaynağı bir SEAM'dir; gerçek implementasyon (F2 §14.1) Tenant/Provisioning
//    servisi + Resource Manager + faturalandırma kayıtlarından beslenir. Belirli sağlayıcı/SaaS bağlanmaz.
//  - SAF/DETERMİNİSTİK: türetme yardımcıları (statusTone/countByStatus/lifecycleActions/provisioningProgress)
//    Date.now/rastgelelik içermez → birim-test edilebilir + Python aynası (screens/p02-tenants/p02_tenants_probe.py).
//  - İŞ MANTIĞI/AUTHZ YOK (SAD §14.4.1 A8): provisioning aksiyonları (oluştur/askıya al/sil/plan ata) UI'da
//    yalnız görsel kapıdır; nihai yetki + state geçişi backend'de (12.2.x). RBAC (BRD §17.6): bu ekran
//    yalnız `platform_owner`=Yönet (sre/billing=erişim yok) — kapı backend/middleware'de zorlanır.

export type Region = "uk" | "eu" | "na" | "me";

// Tenant provisioning durum makinesi (lifecycle). deleted = terminal.
export type TenantStatus = "provisioning" | "active" | "suspended" | "deprovisioning" | "deleted";

// Vendor-neutral plan tier'ları (BRD enterprise/dedicated tier diline hizalı; sağlayıcı bağlamaz).
export type Plan = "starter" | "growth" | "enterprise" | "dedicated";

// Provisioning aksiyonları (UI yalnız görsel kapı; backend zorlar).
export type TenantAction = "create" | "suspend" | "resume" | "assign_plan" | "delete";

export type StatusTone = "success" | "warning" | "info" | "danger" | "neutral";

export interface TenantSummary {
  id: string;
  name: string; // tenant org adı (tenant kimliği — L0'da izinli; son-müşteri PII'si DEĞİL)
  plan: Plan;
  status: TenantStatus;
  region: Region;
  createdAt: string; // ISO-8601 (sabit yer tutucu — SSR-stabil, Date.now YOK)
  activeUsers: number; // yalnız SAYI (kaynak verisi) — kullanıcı kimliği/iş içeriği değil
  // provisioning/deprovisioning sürecindeki tenant için adım ilerlemesi (aksi halde tanımsız):
  provisioningStep?: number;
  provisioningTotalSteps?: number;
}

export interface TenantsSnapshot {
  generatedAt: string; // ISO-8601 (sabit yer tutucu — SSR-stabil, Date.now YOK)
  tenants: TenantSummary[];
}

export type StatusCounts = Record<TenantStatus, number>;

// ── saf türetme yardımcıları ────────────────────────────────────────────────────

const STATUS_TONE: Record<TenantStatus, StatusTone> = {
  active: "success",
  suspended: "warning",
  provisioning: "info",
  deprovisioning: "warning",
  deleted: "danger",
};
export function statusTone(s: TenantStatus): StatusTone {
  return STATUS_TONE[s];
}

// Durum bazında tenant sayımı (özet KPI). Tüm durumlar 0 ile başlar.
export function countByStatus(tenants: TenantSummary[]): StatusCounts {
  const counts: StatusCounts = {
    provisioning: 0,
    active: 0,
    suspended: 0,
    deprovisioning: 0,
    deleted: 0,
  };
  for (const t of tenants) counts[t.status] += 1;
  return counts;
}

// Provisioning durum makinesi: bir durumda hangi aksiyonlar UI'da SUNULUR (görsel kapı; backend zorlar).
//  provisioning/deprovisioning → süreç devam ediyor, aksiyon yok.
//  active   → askıya al / plan ata / sil
//  suspended → devam ettir / plan ata / sil
//  deleted  → terminal, aksiyon yok.
const LIFECYCLE_ACTIONS: Record<TenantStatus, TenantAction[]> = {
  provisioning: [],
  active: ["suspend", "assign_plan", "delete"],
  suspended: ["resume", "assign_plan", "delete"],
  deprovisioning: [],
  deleted: [],
};
export function lifecycleActions(status: TenantStatus): TenantAction[] {
  return LIFECYCLE_ACTIONS[status];
}

// Terminal durum (artık geçiş yok).
export function isTerminal(status: TenantStatus): boolean {
  return status === "deleted";
}

// Provisioning ilerleme yüzdesi: [0,100]'e kıstırılmış, 1 ondalık. total≤0 → 0.
export function provisioningProgress(step: number, total: number): number {
  if (total <= 0) return 0;
  const pct = (step / total) * 100;
  return Math.min(100, Math.max(0, Math.round(pct * 10) / 10));
}

// ── ALTIN KURAL koruması (iş-içeriği/son-müşteri PII sızıntısı) ───────────────────
// Snapshot yapısı içinde tenant İŞ İÇERİĞİ/SON-MÜŞTERİ PII'sini çağrıştıran ALAN ADI bulunursa hata
// fırlatır. Bu, P-02'nin yalnız tenant kayıt/kaynak metadatası göstermesini çalışma-anında garanti eder
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
        throw new Error(`P-02 ALTIN KURAL ihlali: yasak iş-içeriği/PII alanı "${path}.${k}" (BRD §17.7)`);
      }
      assertNoPii((node as Record<string, unknown>)[k], `${path}.${k}`);
    }
  }
}

// ── veri SEAM (yer tutucu) ───────────────────────────────────────────────────────
// Deterministik yer tutucu: tenant kayıt/kaynak metadatası (iş-içeriği/PII DEĞİL). Gerçek implementasyon
// (F2 §14.1) Tenant/Provisioning servisi + Resource Manager + faturalandırmadan beslenir.
const PLACEHOLDER_SNAPSHOT: TenantsSnapshot = {
  generatedAt: "2026-06-17T09:00:00.000Z",
  tenants: [
    { id: "tn_acme", name: "Acme Finans A.Ş.", plan: "enterprise", status: "active", region: "eu", createdAt: "2025-11-02T10:00:00.000Z", activeUsers: 184 },
    { id: "tn_globex", name: "Globex Telekom", plan: "dedicated", status: "active", region: "uk", createdAt: "2025-09-14T08:30:00.000Z", activeUsers: 412 },
    { id: "tn_initech", name: "Initech Sigorta", plan: "growth", status: "suspended", region: "eu", createdAt: "2026-01-21T13:15:00.000Z", activeUsers: 47 },
    { id: "tn_umbrella", name: "Umbrella Sağlık", plan: "enterprise", status: "provisioning", region: "na", createdAt: "2026-06-16T16:45:00.000Z", activeUsers: 0, provisioningStep: 3, provisioningTotalSteps: 6 },
    { id: "tn_hooli", name: "Hooli Perakende", plan: "starter", status: "provisioning", region: "me", createdAt: "2026-06-17T07:05:00.000Z", activeUsers: 0, provisioningStep: 1, provisioningTotalSteps: 6 },
    { id: "tn_soylent", name: "Soylent Lojistik", plan: "growth", status: "deprovisioning", region: "eu", createdAt: "2024-12-03T09:00:00.000Z", activeUsers: 12, provisioningStep: 2, provisioningTotalSteps: 4 },
  ],
};

export async function getTenants(): Promise<TenantsSnapshot> {
  const snap = PLACEHOLDER_SNAPSHOT;
  assertNoPii(snap); // ALTIN KURAL: yapısal iş-içeriği/son-müşteri PII yok (BRD §17.7)
  return snap;
}
