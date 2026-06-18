// WBS 13.3.8 — T-08 "Audit Log (tenant)" veri katmanı (seam) + SAF türetme yardımcıları
// (L1 — Tenant Admin Console).
//
// ÇEKİRDEK İLKELER:
//  - İÇERİK (BRD §17.3/§17.6 / FR-IAM-006 + FR-REC-009): tenant'ın KENDİ kullanıcı/sistem DEĞİŞİKLİK ve
//    ERİŞİM kayıtlarının (audit log) görünümü. Her kayıt: ZAMAN, AKTÖR (realm + tenant-içi kimlik),
//    EYLEM (permission-key biçimi, ör. "user:create"/"transcript:read"), KAYNAK (tip + referans),
//    KATEGORİ, SONUÇ (success/failure/denied), BREAK-GLASS işareti (FR-IAM-009) ve BÜTÜNLÜK (prev/row
//    hash zinciri — ADR-016). Kayıtlar değiştirilemez/WORM (FR-IAM-006; DB §6.5).
//  - TENANT-SCOPE (FR-TEN-002): T-08 YALNIZ oturum açan tenant'ın KENDİ audit kayıtlarını gösterir
//    (audit_log.tenant_id = current tenant). Platform (L0) realm'ı yalnız bu tenant'a yapılmış
//    break-glass erişimi olarak görünür (FR-IAM-009); başka tenant'ın kaydı erişilmez. Scope çalışma-
//    anında middleware (13.1.2) + RLS (DB §6.3) ile sabitlenir; UI yalnız görsel kapı (SAD §14.4.1 A8).
//  - HİJYEN (BRD §17.7 + §17.6 PII redaction): audit kaydı yalnız META veridir (aktör/eylem/kaynak
//    REFERANSI/zaman/bütünlük hash'i). Ham SON-MÜŞTERİ iş içeriği (çağrı kaydı/transkript/ses, müşteri
//    PII/numarası, kart/CVV) audit görünümüne GÖMÜLMEZ — kaynak yalnız UUID/handle ile REFERANS edilir
//    (içerik DEĞİL). `assertNoPii` çalışma-anında doğrular. Aktör kimliği (tenant-içi kullanıcı) L1'de
//    izinlidir; son-müşteri PII değildir.
//  - GÜVENLİK (NFR 10.6): sır/credential audit görünümüne KONMAZ (token/apiKey/privateKey/kmsKey).
//    Bütünlük hash'leri yalnız HEX ÖNEKİDİR (gösterim) — anahtar/sır değildir.
//  - BÜTÜNLÜK/TAMPER-EVIDENCE (ADR-016 / FR-IAM-006): kayıtlar hash zinciriyle bağlanır (her kayıt
//    öncekinin row_hash'ini prev_hash olarak taşır). Panel zincir BAĞLANTISINI doğrular (kriptografik
//    içerik-hash doğrulaması + dış mühürleme backend'de); kopukluk kurcalama kanıtıdır.
//  - VENDOR-NEUTRAL (ADR-002): veri kaynağı bir SEAM'dir; gerçek implementasyon (F2) audit servisi +
//    WORM store + dış mühürleme'den (ADR-016) tenant-scope (RLS) beslenir.
//  - SAF/DETERMİNİSTİK: türetme yardımcıları (chainBreaks/breakGlassEntries/categoryCounts/applyFilter/...)
//    Date.now/rastgelelik içermez → birim-test edilebilir + Python aynası (screens/t08-audit/t08_audit_probe.py).
//  - İŞ MANTIĞI/AUTHZ YOK (SAD §14.4.1 A8): kayıt yazma/silme YOK (WORM); nihai yetki backend'de
//    (12.2.x) + RLS. Panel yalnız çözümlenmiş audit görünümünü gösterir + bütünlük/sonuç anomalisini işaretler.

export type ActorRealm = "tenant" | "platform" | "system"; // platform => L0 (break-glass)
export type AuditCategory = "iam" | "config" | "data_access" | "compliance" | "security" | "break_glass" | "billing";
export type AuditOutcome = "success" | "failure" | "denied";

export type StatusTone = "success" | "warning" | "danger" | "neutral" | "info";

// Tek audit kaydı. Yalnız META — ham içerik DEĞİL. resourceRef = UUID/handle REFERANSI (içerik değil).
export interface AuditEntry {
  id: string; // audit kaydı id (UUID)
  occurredAt: string; // ISO-8601 (olay zamanı)
  actorRealm: ActorRealm; // tenant/platform/system
  actorRef: string; // aktör tenant-içi kimliği (kullanıcı e-postası / sistem bileşeni) — L1'de izinli
  action: string; // permission-key biçimi (ör. "user:create", "transcript:read")
  resourceType: string; // kaynak tipi (ör. "user", "agent", "recording")
  resourceRef: string; // kaynak REFERANSI (UUID/handle) — içerik DEĞİL
  category: AuditCategory; // sınıflandırma
  outcome: AuditOutcome; // success/failure/denied
  breakGlass: boolean; // FR-IAM-009 break-glass erişimi mi
  breakGlassId: string | null; // break_glass_grant referansı (varsa)
  prevHash: string; // önceki kaydın row_hash'i (zincir) — HEX ÖNEKİ
  rowHash: string; // bu kaydın hash'i (bütünlük) — HEX ÖNEKİ
}

// Saklama + bütünlük yapılandırması (FR-IAM-006 WORM; ADR-016 dış mühürleme; retention compliance profile).
export interface RetentionInfo {
  retentionDays: number; // audit saklama süresi (gün) — 0 = tanımsız
  wormEnabled: boolean; // append-only / WORM zorlu mu (FR-IAM-006; DB §6.5)
  externalSeal: boolean; // periyodik dış mühürleme açık mı (ADR-016)
  lastSealedAt: string; // son dış mühürleme zamanı (ISO-8601 / etiket)
}

export interface AuditSnapshot {
  generatedAt: string; // ISO-8601 (sabit yer tutucu — SSR-stabil, Date.now YOK)
  tenantRef: string; // tenant'ın KENDİ kimliği (L1'de izinli)
  tenantName: string; // tenant org adı (izinli; son-müşteri verisi DEĞİL)
  windowLabel: string; // görünüm zaman penceresi etiketi (ör. "Son 24 saat")
  totalCount: number; // pencere içindeki toplam kayıt (topluluk; sayfa alt-kümeyi gösterir)
  entries: AuditEntry[]; // ZİNCİR SIRASINDA (occurredAt artan) — bütünlük doğrulaması için
  retention: RetentionInfo;
}

// ── saf türetme yardımcıları ────────────────────────────────────────────────────

// ZİNCİR KOPUKLUKLARI (danger — ADR-016 / FR-IAM-006 tamper-evidence): entries[i].prevHash, bir önceki
// kaydın rowHash'iyle eşleşmiyorsa kopukluk. entries ZİNCİR SIRASINDA (artan) verilmelidir. İlk kayıt
// referans kabul edilir (önceki sayfaya/genesis'e bağlanır — panelde doğrulanmaz). Kopuk kayıt id'leri.
export function chainBreaks(entries: AuditEntry[]): string[] {
  const out: string[] = [];
  for (let i = 1; i < entries.length; i++) {
    if (entries[i].prevHash !== entries[i - 1].rowHash) out.push(entries[i].id);
  }
  return out;
}

// Zincir bütünlüğü sağlam mı (kopukluk yok).
export function chainIntact(entries: AuditEntry[]): boolean {
  return chainBreaks(entries).length === 0;
}

// BREAK-GLASS kayıtları (FR-IAM-009): platform (L0) tenant iş içeriğine erişimi. Vurgulanır.
export function breakGlassEntries(entries: AuditEntry[]): AuditEntry[] {
  return entries.filter((e) => e.breakGlass);
}

// VERİ ERİŞİM kayıtları (FR-REC-009): kayıt/transkript/PII erişimleri ayrı izlenir.
export function dataAccessEntries(entries: AuditEntry[]): AuditEntry[] {
  return entries.filter((e) => e.category === "data_access");
}

// PLATFORM (L0) realm kayıtları: tenant'a dışarıdan (platform) yapılan işlemler — hepsi break-glass olmalı.
export function platformEntries(entries: AuditEntry[]): AuditEntry[] {
  return entries.filter((e) => e.actorRealm === "platform");
}

// PLATFORM ERİŞİMİ BREAK-GLASS'SIZ (danger): platform realm bir kayıt break-glass işaretsiz → kural ihlali
// (FR-IAM-009: platform iş içeriğine yalnız break-glass ile erişebilir). Kopuk kayıt id'leri.
export function platformWithoutBreakGlass(entries: AuditEntry[]): string[] {
  return entries.filter((e) => e.actorRealm === "platform" && !e.breakGlass).map((e) => e.id);
}

// BAŞARISIZ/REDDEDİLEN kayıtlar: outcome !== success.
export function failedEntries(entries: AuditEntry[]): AuditEntry[] {
  return entries.filter((e) => e.outcome !== "success");
}

// REDDEDİLEN (yetkisiz) kayıtlar: outcome === denied (güvenlik anomalisi sinyali).
export function deniedEntries(entries: AuditEntry[]): AuditEntry[] {
  return entries.filter((e) => e.outcome === "denied");
}

// Kategori dağılımı (KPI/breakdown).
export function categoryCounts(entries: AuditEntry[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const e of entries) out[e.category] = (out[e.category] ?? 0) + 1;
  return out;
}

// Sonuç dağılımı.
export function outcomeCounts(entries: AuditEntry[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const e of entries) out[e.outcome] = (out[e.outcome] ?? 0) + 1;
  return out;
}

// WORM KAPALI (danger): append-only/WORM zorlanmıyor → FR-IAM-006 ihlali (audit değiştirilemez olmalı).
export function wormDisabled(r: RetentionInfo): boolean {
  return !r.wormEnabled;
}

// DIŞ MÜHÜRLEME KAPALI (warning): periyodik dış mühürleme yok → tamper-evidence zayıf (ADR-016 önerisi).
export function externalSealDisabled(r: RetentionInfo): boolean {
  return !r.externalSeal;
}

// SAKLAMA TANIMSIZ (warning): retention süresi tanımlı değil (≤0).
export function retentionUnset(r: RetentionInfo): boolean {
  return r.retentionDays <= 0;
}

// Audit görünüm filtresi (FR — aktör/eylem/kategori/realm/sonuç + break-glass + serbest metin). Saf.
export interface AuditFilter {
  realm?: ActorRealm;
  category?: AuditCategory;
  outcome?: AuditOutcome;
  breakGlassOnly?: boolean;
  actorContains?: string; // aktör REFERANSINDA alt-dizi (case-insensitive)
  actionContains?: string; // eylemde alt-dizi (case-insensitive)
}

// Filtreyi uygula (saf, deterministik). Boş filtre => tüm kayıtlar. Sıra korunur (zincir sırası).
export function applyFilter(entries: AuditEntry[], f: AuditFilter): AuditEntry[] {
  return entries.filter((e) => {
    if (f.realm && e.actorRealm !== f.realm) return false;
    if (f.category && e.category !== f.category) return false;
    if (f.outcome && e.outcome !== f.outcome) return false;
    if (f.breakGlassOnly && !e.breakGlass) return false;
    if (f.actorContains && !e.actorRef.toLowerCase().includes(f.actorContains.toLowerCase())) return false;
    if (f.actionContains && !e.action.toLowerCase().includes(f.actionContains.toLowerCase())) return false;
    return true;
  });
}

// Toplam açık uyarı sayısı (KPI): tüm danger + warning türlerinin toplamı.
//   danger : her zincir kopukluğu · her break-glass'sız platform erişimi · WORM kapalı
//   warning: her reddedilen kayıt · saklama tanımsız · dış mühürleme kapalı
export function openWarningCount(snap: AuditSnapshot): number {
  return (
    chainBreaks(snap.entries).length +
    platformWithoutBreakGlass(snap.entries).length +
    (wormDisabled(snap.retention) ? 1 : 0) +
    deniedEntries(snap.entries).length +
    (retentionUnset(snap.retention) ? 1 : 0) +
    (externalSealDisabled(snap.retention) ? 1 : 0)
  );
}

// ── ton (renk) eşlemeleri ─────────────────────────────────────────────────────────

const OUTCOME_TONE: Record<AuditOutcome, StatusTone> = {
  success: "success",
  failure: "danger",
  denied: "warning",
};
export function outcomeTone(o: AuditOutcome): StatusTone {
  return OUTCOME_TONE[o];
}

const REALM_TONE: Record<ActorRealm, StatusTone> = {
  tenant: "neutral",
  platform: "warning", // L0 dışarıdan erişim — dikkat
  system: "info",
};
export function realmTone(r: ActorRealm): StatusTone {
  return REALM_TONE[r];
}

const CATEGORY_TONE: Record<AuditCategory, StatusTone> = {
  iam: "neutral",
  config: "neutral",
  data_access: "info",
  compliance: "info",
  security: "info",
  break_glass: "warning",
  billing: "neutral",
};
export function categoryTone(c: AuditCategory): StatusTone {
  return CATEGORY_TONE[c];
}

// Break-glass satır tonu: var => warning · yok => neutral.
export function breakGlassTone(b: boolean): StatusTone {
  return b ? "warning" : "neutral";
}

// Zincir bütünlük tonu: kopuk => danger · sağlam => success.
export function chainTone(broken: boolean): StatusTone {
  return broken ? "danger" : "success";
}

// WORM tonu: açık => success · kapalı => danger (FR-IAM-006).
export function wormTone(enabled: boolean): StatusTone {
  return enabled ? "success" : "danger";
}

// Dış mühürleme tonu: açık => success · kapalı => warning (ADR-016).
export function sealTone(enabled: boolean): StatusTone {
  return enabled ? "success" : "warning";
}

// ── HİJYEN + GÜVENLİK koruması ─────────────────────────────────────────────────────
// Yapı içinde son-müşteri ham iş içeriği/PII'yi VEYA sır/credential çağrıştıran ALAN ADI bulunursa hata
// fırlatır. Bu, T-08'in yalnız audit META verisini (aktör/eylem/kaynak REFERANSI/bütünlük hash'i) —
// ham çağrı kaydı/transkript/müşteri PII/kart/sır DEĞİL — göstermesini çalışma-anında garanti eder
// (BRD §17.7 + §17.6 PII redaction + NFR 10.6). NOT: aktör kimliği (tenant-içi kullanıcı) audit'in
// amacıdır ve L1'de izinlidir; "actorRef" yasak değildir.
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
        throw new Error(`T-08 HİJYEN ihlali: yasak PII/iş-içeriği alanı "${path}.${k}" (BRD §17.7)`);
      }
      if (FORBIDDEN_SECRET_KEYS.includes(lower)) {
        throw new Error(`T-08 GÜVENLİK ihlali: sır/credential alanı "${path}.${k}" panele konmaz (NFR 10.6)`);
      }
      assertNoPii((node as Record<string, unknown>)[k], `${path}.${k}`);
    }
  }
}

// ── veri SEAM (yer tutucu) ───────────────────────────────────────────────────────
// Deterministik yer tutucu: tek-tenant audit görünümü (KENDİ kullanıcı/sistem değişiklik + erişim
// kayıtları — META yalnız, ham içerik/PII/sır DEĞİL). Kayıtlar ZİNCİR SIRASINDA (occurredAt artan);
// prevHash[i] == rowHash[i-1] (sağlam zincir). Gerçek implementasyon (F2) audit servisi + WORM store +
// dış mühürleme'den (ADR-016) tenant-scope (RLS) beslenir. Hash'ler illüstratif HEX önekidir.
const PLACEHOLDER_SNAPSHOT: AuditSnapshot = {
  generatedAt: "2026-06-18T09:00:00.000Z",
  tenantRef: "TEN-2048",
  tenantName: "Kuzey Sigorta A.Ş.",
  windowLabel: "2026-06-17 → 2026-06-18",
  totalCount: 1487,
  entries: [
    {
      id: "AE-1001",
      occurredAt: "2026-06-17T08:12:00.000Z",
      actorRealm: "tenant",
      actorRef: "owner@kuzeysigorta.example",
      action: "user:create",
      resourceType: "user",
      resourceRef: "USR-3310",
      category: "iam",
      outcome: "success",
      breakGlass: false,
      breakGlassId: null,
      prevHash: "00000000",
      rowHash: "a1b2c3d4",
    },
    {
      id: "AE-1002",
      occurredAt: "2026-06-17T09:40:00.000Z",
      actorRealm: "tenant",
      actorRef: "admin@kuzeysigorta.example",
      action: "agent:publish",
      resourceType: "agent",
      resourceRef: "AGT-77",
      category: "config",
      outcome: "success",
      breakGlass: false,
      breakGlassId: null,
      prevHash: "a1b2c3d4",
      rowHash: "b2c3d4e5",
    },
    {
      id: "AE-1003",
      occurredAt: "2026-06-17T14:05:00.000Z",
      actorRealm: "tenant",
      actorRef: "qa@kuzeysigorta.example",
      action: "role:assign",
      resourceType: "user",
      resourceRef: "USR-3310",
      category: "iam",
      outcome: "denied",
      breakGlass: false,
      breakGlassId: null,
      prevHash: "b2c3d4e5",
      rowHash: "c3d4e5f6",
    },
    {
      id: "AE-1004",
      occurredAt: "2026-06-18T02:18:00.000Z",
      actorRealm: "platform",
      actorRef: "rmc-sre@platform",
      action: "transcript:read",
      resourceType: "recording",
      resourceRef: "REC-90211",
      category: "break_glass",
      outcome: "success",
      breakGlass: true,
      breakGlassId: "BG-5521",
      prevHash: "c3d4e5f6",
      rowHash: "d4e5f6a7",
    },
    {
      id: "AE-1005",
      occurredAt: "2026-06-18T07:55:00.000Z",
      actorRealm: "tenant",
      actorRef: "compliance@kuzeysigorta.example",
      action: "retention:read",
      resourceType: "policy",
      resourceRef: "RET-1",
      category: "compliance",
      outcome: "success",
      breakGlass: false,
      breakGlassId: null,
      prevHash: "d4e5f6a7",
      rowHash: "e5f6a7b8",
    },
  ],
  retention: {
    retentionDays: 2555, // ~7 yıl (illüstratif; compliance profile'dan)
    wormEnabled: true,
    externalSeal: true,
    lastSealedAt: "2026-06-18T06:00:00.000Z",
  },
};

export async function getAudit(): Promise<AuditSnapshot> {
  const snap = PLACEHOLDER_SNAPSHOT;
  assertNoPii(snap); // HİJYEN + GÜVENLİK: yapısal son-müşteri PII / sır yok (BRD §17.7 / NFR 10.6)
  return snap;
}
