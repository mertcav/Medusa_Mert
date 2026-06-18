// WBS 13.3.9 — T-09 "Kaynak Kotası Görünümü" veri katmanı (seam) + SAF türetme yardımcıları
// (L1 — Tenant Admin Console).
//
// ÇEKİRDEK İLKELER:
//  - İÇERİK (BRD §17.3 T-09 / FR-TEN-006 + FR-TEN-007): tenant'ın L0 (Platform Admin Console, P-03)
//    TARAFINDAN ATANAN kapasite kotasını ve tüketimini YALNIZCA OKUR. FR-TEN-006 → eş zamanlı çağrı +
//    CPS + kullanım limiti kotası; FR-TEN-007 → kaynak kotası (vCPU/bellek/eşzamanlılık) + aşım zorlaması.
//    Ek bağlam: izolasyon modu (reserved/shared, SAD §16.2 noisy-neighbor), rezerve eşzamanlılık, burst
//    çarpanı (NFR 10.3 2x), scale-to-zero durumu (FR-RES-007).
//  - SALT-OKUNUR (BRD §17.3 / §17.5): T-09 yalnız GÖRÜNÜM'dür. Kota DEĞİŞTİRME (tanım/atama) yalnız L0
//    Platform Admin Console'da (P-03; FR-TEN-006/007 panel kapsamı BRD §9.x notu) yapılır; tenant burada
//    DÜZENLEME YAPAMAZ. RBAC (BRD §17.6): tenant_owner=Görüntüle · tenant_admin=Görüntüle ·
//    security_compliance_officer=— · billing_viewer=Görüntüle · api_developer=—. UI yalnız görsel kapı;
//    nihai yetki + kota ZORLAMASI backend Resource Manager Quota Service'te (SAD §15.2, 12.2.x).
//  - TENANT-SCOPE (FR-TEN-002): T-09 YALNIZ oturum açan tenant'ın KENDİ atanan kotasını/tüketimini gösterir;
//    başka tenant'ın kotası erişilmez. Scope çalışma-anında middleware (13.1.2) + RLS (§13) ile sabitlenir.
//  - HİJYEN (BRD §17.7): yapı yalnız tenant-bütünü KAPASİTE/KAYNAK metadatasıdır (atanan kota, tüketim,
//    izolasyon). Ham son-müşteri iş içeriği (çağrı kaydı, transkript, müşteri PII/numarası) buraya GÖMÜLMEZ.
//    `assertNoPii` çalışma-anında doğrular.
//  - GÜVENLİK (NFR 10.6): SIR/credential buraya KONMAZ. Kota/kapasite değerleri MÜHENDİSLİK ÖRNEĞİDİR
//    (illüstratif); gerçek değerler Resource Manager Quota Service'ten (SAD §15.2) + 0.4.7 gözlemlenebilirlik
//    omurgasından tenant-scope (RLS) beslenir.
//  - VENDOR-NEUTRAL (ADR-002): veri kaynağı bir SEAM'dir; gerçek implementasyon (F2 §14.1) Resource Manager
//    (Quota Service · Autoscaler · Scale-to-zero Ctrl · Backpressure Ctrl · Cost/Resource Meter) +
//    L0 P-03'ten ATANAN kota + gözlemlenebilirlik omurgasından TÜKETİM ölçümü ile dolar. Sağlayıcı bağlamaz.
//  - SAF/DETERMİNİSTİK: türetme yardımcıları (utilizationPct/headroom/utilTone/breached/breachedResources/
//    nearLimitResources/enforcementGaps/worstTone/openWarningCount/...) Date.now/rastgelelik içermez →
//    birim-test edilebilir + Python aynası (screens/t09-quota/t09_quota_probe.py).
//  - İŞ MANTIĞI/AUTHZ YOK (SAD §14.4.1 A8): kota düzenleme/atama kararı YOK; panel yalnız çözümlenmiş
//    atanan kota + tüketim görünümünü gösterir + aşım/enforcement boşluğunu işaretler.

// Kaynak türleri (T-01 dashboard QuotaResource ile hizalı + kullanım limiti eklenmiş):
//   concurrent_calls  → eş zamanlı çağrı kotası   (FR-TEN-006 + FR-TEN-007 eşzamanlılık)
//   cps               → saniye başına çağrı (CPS)  (FR-TEN-006)
//   compute_vcpu      → vCPU kotası                (FR-TEN-007)
//   compute_memory_gb → bellek (GB) kotası         (FR-TEN-007)
//   usage_minutes     → dönem kullanım limiti (dk) (FR-TEN-006 kullanım limiti)
export type QuotaResource =
  | "concurrent_calls"
  | "cps"
  | "compute_vcpu"
  | "compute_memory_gb"
  | "usage_minutes";

// Noisy-neighbor koruması: rezerve kapasite (izole) vs paylaşımlı havuz (SAD §16.2; P-03 ile hizalı).
export type IsolationMode = "reserved" | "shared";

// Scale-to-zero kontrolü (FR-RES-007): aktif=trafik var · idle=boşta sayaç işliyor · scaled_to_zero=sıfıra indi.
export type ScaleToZeroState = "active" | "idle" | "scaled_to_zero";

export type StatusTone = "success" | "warning" | "danger" | "neutral" | "info";

// Atanan kota satırı + tüketim. used > limit => aşım (breach). enforced=true => aşım backend'de engellenir
// (FR-TEN-007 "aşımı engellenmelidir"); enforced=false => zorlama boşluğu (riskli, işaretlenir).
export interface QuotaLine {
  resource: QuotaResource;
  used: number; // güncel/dönem tüketimi (gözlemlenebilirlik omurgasından)
  limit: number; // L0 tarafından ATANAN kota
  enforced: boolean; // FR-TEN-007: aşım backend'de engelleniyor mu
}

export interface QuotaSnapshot {
  generatedAt: string; // ISO-8601 (sabit yer tutucu — SSR-stabil, Date.now YOK)
  tenantRef: string; // tenant'ın KENDİ kimliği (L1'de izinli)
  tenantName: string; // tenant org adı (izinli; son-müşteri verisi DEĞİL)
  plan: string; // plan ADI (vendor-neutral; ör. "enterprise")
  region: string; // birincil bölge (residency bağlamı)
  isolation: IsolationMode; // reserved/shared (SAD §16.2)
  reservedConcurrency: number; // rezerve eş zamanlı çağrı (noisy-neighbor koruması)
  burstMultiplier: number; // ani trafik çarpanı (NFR 10.3 2x)
  scaleToZero: ScaleToZeroState; // FR-RES-007
  lines: QuotaLine[]; // atanan kota + tüketim (FR-TEN-006/007)
}

// Bu yüzde üstü tüketim "limite yakın" (warning) sayılır; ≥100 = aşım (danger). P-03/T-01 ile hizalı.
export const NEAR_LIMIT_PCT = 75;
// "Sert kaynak" kümesi: FR-TEN-007 gereği aşımı ZORUNLU engellenmeli; bu kaynaklarda enforced=false boşluktur.
export const HARD_ENFORCED_RESOURCES: readonly QuotaResource[] = [
  "concurrent_calls",
  "cps",
  "compute_vcpu",
  "compute_memory_gb",
];

// ── saf türetme yardımcıları ────────────────────────────────────────────────────

// Kullanım yüzdesi: ALT sınır 0; ÜST sınır YOK (aşım görünür kalır — P-03 ile hizalı); 1 ondalık. limit≤0 → 0.
export function utilizationPct(used: number, limit: number): number {
  if (limit <= 0) return 0;
  const pct = (used / limit) * 100;
  return Math.max(0, Math.round(pct * 10) / 10);
}

// Boş/kalan kapasite (negatif olamaz).
export function headroom(used: number, limit: number): number {
  return Math.max(0, limit - used);
}

// Kullanım tonu (kota/kapasite): ≥90 danger · ≥75 warning · aksi success (P-03/T-01 ile hizalı).
export function utilTone(pct: number): StatusTone {
  if (pct >= 90) return "danger";
  if (pct >= NEAR_LIMIT_PCT) return "warning";
  return "success";
}

// AŞIM (breach): tüketim atanan kotayı geçti (FR-TEN-007 — normalde enforced ile engellenir, görünür kalır).
export function breached(l: QuotaLine): boolean {
  return l.limit > 0 && l.used > l.limit;
}

// Aşan kaynakların listesi (sıralı — alarm + işaretleme).
export function breachedResources(lines: QuotaLine[]): QuotaResource[] {
  return lines.filter(breached).map((l) => l.resource);
}

// LİMİTE YAKIN (warning): tüketim eşiğe ulaştı ama aşmadı (NEAR_LIMIT_PCT ≤ util ≤ 100).
export function nearLimit(l: QuotaLine): boolean {
  const pct = utilizationPct(l.used, l.limit);
  return pct >= NEAR_LIMIT_PCT && pct <= 100;
}

export function nearLimitResources(lines: QuotaLine[]): QuotaResource[] {
  return lines.filter(nearLimit).map((l) => l.resource);
}

// ZORLAMA BOŞLUĞU (warning): sert kaynak ama enforced=false → aşım engellenmiyor (FR-TEN-007 ihlali riski).
export function enforcementGaps(lines: QuotaLine[]): QuotaResource[] {
  return lines
    .filter((l) => HARD_ENFORCED_RESOURCES.includes(l.resource) && !l.enforced)
    .map((l) => l.resource);
}

// En-kötü kota tonu (worst-of) — özet sağlık göstergesi.
export function worstTone(lines: QuotaLine[]): StatusTone {
  let worst: StatusTone = "success";
  for (const l of lines) {
    const tone = utilTone(utilizationPct(l.used, l.limit));
    if (tone === "danger") return "danger";
    if (tone === "warning") worst = "warning";
  }
  return worst;
}

// Toplam açık uyarı sayısı (KPI): aşan kaynak + zorlama boşluğu + limite-yakın kaynak sayıları toplamı.
export function openWarningCount(snap: QuotaSnapshot): number {
  return (
    breachedResources(snap.lines).length +
    enforcementGaps(snap.lines).length +
    nearLimitResources(snap.lines).length
  );
}

// ── ton (renk) eşlemeleri ─────────────────────────────────────────────────────────

const ISOLATION_TONE: Record<IsolationMode, StatusTone> = {
  reserved: "success", // rezerve = korumalı
  shared: "warning", // paylaşımlı = noisy-neighbor riskine açık
};
export function isolationTone(mode: IsolationMode): StatusTone {
  return ISOLATION_TONE[mode];
}

const SCALE_STATE_TONE: Record<ScaleToZeroState, StatusTone> = {
  active: "success",
  idle: "info",
  scaled_to_zero: "neutral",
};
export function scaleStateTone(s: ScaleToZeroState): StatusTone {
  return SCALE_STATE_TONE[s];
}

// Zorlama tonu: enforced => success (aşım engelli) · değilse warning (boşluk).
export function enforcedTone(enforced: boolean): StatusTone {
  return enforced ? "success" : "warning";
}

// ── HİJYEN + GÜVENLİK koruması ─────────────────────────────────────────────────────
// Yapı içinde son-müşteri iş içeriği/PII'yi VEYA sır/credential çağrıştıran ALAN ADI bulunursa hata
// fırlatır. Bu, T-09'un yalnız tenant'ın KENDİ atanan kota/kapasite metadatasını (son-müşteri içeriği/PII
// VEYA sır DEĞİL) göstermesini çalışma-anında garanti eder (BRD §17.7 + NFR 10.6). NOT: tenantName/tenantRef
// tenant'ın KENDİ kimliğidir → yasak listede DEĞİL (izinli).
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
        throw new Error(`T-09 HİJYEN ihlali: yasak PII/iş-içeriği alanı "${path}.${k}" (BRD §17.7)`);
      }
      if (FORBIDDEN_SECRET_KEYS.includes(lower)) {
        throw new Error(`T-09 GÜVENLİK ihlali: sır/credential alanı "${path}.${k}" panele konmaz (NFR 10.6)`);
      }
      assertNoPii((node as Record<string, unknown>)[k], `${path}.${k}`);
    }
  }
}

// ── veri SEAM (yer tutucu) ───────────────────────────────────────────────────────
// Deterministik yer tutucu: tek-tenant ATANAN kota + tüketim görünümü (son-müşteri içeriği/PII/sır DEĞİL).
// Gerçek implementasyon (F2 §14.1) Resource Manager Quota Service (SAD §15.2) ATANAN kota + 0.4.7
// gözlemlenebilirlik omurgasından TÜKETİM ölçümü ile tenant-scope (RLS) dolar. Kota değerleri İLLÜSTRATİFTİR.
const PLACEHOLDER_SNAPSHOT: QuotaSnapshot = {
  generatedAt: "2026-06-18T09:00:00.000Z",
  tenantRef: "TEN-2048",
  tenantName: "Kuzey Sigorta A.Ş.",
  plan: "enterprise",
  region: "eu",
  isolation: "reserved",
  reservedConcurrency: 800,
  burstMultiplier: 2,
  scaleToZero: "active",
  lines: [
    { resource: "concurrent_calls", used: 1090, limit: 1200, enforced: true },
    { resource: "cps", used: 19, limit: 24, enforced: true },
    { resource: "compute_vcpu", used: 51, limit: 64, enforced: true },
    { resource: "compute_memory_gb", used: 96, limit: 128, enforced: true },
    { resource: "usage_minutes", used: 48230, limit: 60000, enforced: true },
  ],
};

export async function getQuota(): Promise<QuotaSnapshot> {
  const snap = PLACEHOLDER_SNAPSHOT;
  assertNoPii(snap); // HİJYEN + GÜVENLİK: yapısal son-müşteri PII / sır yok (BRD §17.7 / NFR 10.6)
  return snap;
}
