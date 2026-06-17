// WBS 13.3.2 — T-02 "Organizasyon & Yapı" veri katmanı (seam) + SAF türetme yardımcıları (L1 — Tenant Admin).
//
// ÇEKİRDEK İLKELER:
//  - İÇERİK (BRD §17.4 / FR-TEN-003): tenant ALTINDA marka, departman, ülke ve proje yapıları. BRD §16
//    "Organisation Unit" = marka/ülke/departman; proje ayrı bir gruplama varlığıdır (org birimine bağlanır).
//  - TENANT-SCOPE (FR-TEN-002): T-02 YALNIZ oturum açan tenant'ın KENDİ organizasyon yapısını gösterir/
//    yönetir; başka tenant'a ait yapı erişilmez. Scope çalışma-anında middleware (13.1.2) + RLS (§13) ile
//    sabitlenir; UI yalnız görsel kapı (SAD §14.4.1 A8). tenantRef/tenantName tenant'ın KENDİ kimliğidir.
//  - RBAC SCOPE BAĞI (FR-IAM-011): bu ekranda tanımlanan marka/departman, rol atamalarının scope filtresine
//    (departman/marka/kampanya) kaynaklık eder → org yapısı IAM scope'unun referans kümesidir.
//  - HİJYEN (BRD §17.7 ruhu): yapı yalnız KONFİGÜRASYON metadatasıdır (org birim adı/kodu/durumu). Ham
//    son-müşteri iş içeriği (çağrı kaydı, transkript, müşteri/PII) buraya GÖMÜLMEZ. Tipler yapısal olarak
//    PII taşımaz; `assertNoPii` çalışma-anında doğrular (sızıntı → hata). NOT: marka/departman/proje adları
//    tenant'ın KENDİ konfigürasyonudur (son-müşteri PII değil) → izinli.
//  - VENDOR-NEUTRAL (ADR-002): veri kaynağı bir SEAM'dir; gerçek implementasyon (F2 §14.1) Tenant/Org servisi
//    + RLS'ten tenant-scope yapıyı çeker. Belirli sağlayıcı/SaaS bağlanmaz.
//  - SAF/DETERMİNİSTİK: türetme yardımcıları (countByType/childrenOf/orphanProjects/...) Date.now/rastgelelik
//    içermez → birim-test edilebilir + Python aynası (screens/t02-organization/t02_organization_probe.py).
//  - İŞ MANTIĞI/AUTHZ YOK (SAD §14.4.1 A8): rol→permission kararı YOK; nihai yetki backend'de (12.2.x) + RLS.

export type OrgUnitType = "brand" | "department" | "country";
export type OrgUnitStatus = "active" | "inactive" | "archived";
export type ProjectStatus = "active" | "paused" | "archived";

export type StatusTone = "success" | "warning" | "neutral";

// Organisation Unit (BRD §16): marka / departman / ülke. Hiyerarşi parentId ile (ör. departman → marka).
export interface OrgUnit {
  id: string; // tenant-scope referans (parentId + proje refleri bununla eşleşir)
  code: string;
  name: string; // tenant'ın KENDİ org birim adı (son-müşteri PII değil)
  type: OrgUnitType;
  parentId: string | null; // hiyerarşi üst birimi (root → null)
  status: OrgUnitStatus;
  userCount: number; // atanan yönetim kullanıcısı SAYISI (kaynak verisi — PII değil)
  agentCount: number; // bağlı agent SAYISI (kaynak verisi)
}

// Proje (FR-TEN-003): marka/departman/ülke yapılarına bağlanan operasyonel gruplama.
export interface Project {
  id: string;
  code: string;
  name: string; // tenant'ın KENDİ proje adı
  brandRef: string | null; // OrgUnit.id (type=brand) — bağlı değilse null
  departmentRef: string | null; // OrgUnit.id (type=department)
  countryRef: string | null; // OrgUnit.id (type=country)
  status: ProjectStatus;
  agentCount: number;
}

export interface OrgStructureSnapshot {
  generatedAt: string; // ISO-8601 (sabit yer tutucu — SSR-stabil, Date.now YOK)
  tenantRef: string; // tenant'ın KENDİ kimliği (L1'de izinli)
  tenantName: string; // tenant org adı = tenant kimliği (izinli; son-müşteri verisi DEĞİL)
  units: OrgUnit[];
  projects: Project[];
}

// ── saf türetme yardımcıları ────────────────────────────────────────────────────

// Tip bazında org birim sayısı.
export function countByType(units: OrgUnit[]): Record<OrgUnitType, number> {
  const out: Record<OrgUnitType, number> = { brand: 0, department: 0, country: 0 };
  for (const u of units) out[u.type] += 1;
  return out;
}

// Durum bazında org birim sayısı.
export function countByStatus(units: OrgUnit[]): Record<OrgUnitStatus, number> {
  const out: Record<OrgUnitStatus, number> = { active: 0, inactive: 0, archived: 0 };
  for (const u of units) out[u.status] += 1;
  return out;
}

const UNIT_TONE: Record<OrgUnitStatus, StatusTone> = {
  active: "success",
  inactive: "warning",
  archived: "neutral",
};
export function unitStatusTone(s: OrgUnitStatus): StatusTone {
  return UNIT_TONE[s];
}

const PROJECT_TONE: Record<ProjectStatus, StatusTone> = {
  active: "success",
  paused: "warning",
  archived: "neutral",
};
export function projectStatusTone(s: ProjectStatus): StatusTone {
  return PROJECT_TONE[s];
}

// Bir üst birimin doğrudan alt birimleri (hiyerarşi). parentId eşleşmesi.
export function childrenOf(units: OrgUnit[], parentId: string): OrgUnit[] {
  return units.filter((u) => u.parentId === parentId);
}

// Kök birimler (üst birimi olmayan).
export function rootUnits(units: OrgUnit[]): OrgUnit[] {
  return units.filter((u) => u.parentId === null);
}

// Bir org birimine bağlı proje sayısı (herhangi bir ref alanı eşleşir).
export function projectsForUnit(projects: Project[], unitId: string): number {
  return projects.filter(
    (p) => p.brandRef === unitId || p.departmentRef === unitId || p.countryRef === unitId,
  ).length;
}

// HİJYEN/BÜTÜNLÜK: mevcut OLMAYAN org birimine referans veren projeler (öksüz referans). Proje id listesi.
// Boş dönmesi yapı tutarlılığını gösterir; dolu liste yapı düzeltmesi (UI uyarısı) tetikler.
export function orphanProjects(projects: Project[], units: OrgUnit[]): string[] {
  const ids = new Set(units.map((u) => u.id));
  const out: string[] = [];
  for (const p of projects) {
    const refs = [p.brandRef, p.departmentRef, p.countryRef].filter((r): r is string => r !== null);
    if (refs.some((r) => !ids.has(r))) out.push(p.id);
  }
  return out;
}

// ── HİJYEN koruması (ham PII/iş-içeriği sızıntısı) ────────────────────────────────
// Org yapısı içinde son-müşteri iş içeriği/PII'yi çağrıştıran ALAN ADI bulunursa hata fırlatır.
// Bu, T-02'nin yalnız konfigürasyon metadatası göstermesini çalışma-anında garanti eder (BRD §17.7 ruhu).
// NOT: tenantName/tenantRef + org birim/proje "name"/"code" alanları tenant'ın KENDİ konfigürasyonudur →
// yasak listede DEĞİL (izinli). Yasak liste yalnız son-müşteri PII/çağrı içeriği alan adlarıdır.
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
        throw new Error(`T-02 HİJYEN ihlali: yasak PII/iş-içeriği alanı "${path}.${k}" (BRD §17.7)`);
      }
      assertNoPii((node as Record<string, unknown>)[k], `${path}.${k}`);
    }
  }
}

// ── veri SEAM (yer tutucu) ───────────────────────────────────────────────────────
// Deterministik yer tutucu: tek-tenant org yapısı (KONFİGÜRASYON metadatası — PII/iş-içeriği DEĞİL). Gerçek
// implementasyon (F2 §14.1) Tenant/Org servisi + RLS'ten tenant-scope beslenir.
const PLACEHOLDER_SNAPSHOT: OrgStructureSnapshot = {
  generatedAt: "2026-06-17T09:00:00.000Z",
  tenantRef: "TEN-2048",
  tenantName: "Kuzey Sigorta A.Ş.",
  units: [
    { id: "BR-RETAIL", code: "BR-RETAIL", name: "Perakende", type: "brand", parentId: null, status: "active", userCount: 14, agentCount: 6 },
    { id: "BR-CORP", code: "BR-CORP", name: "Kurumsal", type: "brand", parentId: null, status: "active", userCount: 9, agentCount: 4 },
    { id: "DP-SALES", code: "DP-SALES", name: "Satış", type: "department", parentId: "BR-RETAIL", status: "active", userCount: 8, agentCount: 3 },
    { id: "DP-SUPPORT", code: "DP-SUPPORT", name: "Destek", type: "department", parentId: "BR-RETAIL", status: "active", userCount: 11, agentCount: 5 },
    { id: "DP-COLLECT", code: "DP-COLLECT", name: "Tahsilat", type: "department", parentId: "BR-CORP", status: "inactive", userCount: 4, agentCount: 1 },
    { id: "CN-TR", code: "CN-TR", name: "Türkiye", type: "country", parentId: null, status: "active", userCount: 22, agentCount: 9 },
    { id: "CN-DE", code: "CN-DE", name: "Almanya", type: "country", parentId: null, status: "active", userCount: 6, agentCount: 2 },
  ],
  projects: [
    { id: "PRJ-INB", code: "PRJ-INB", name: "Gelen Çağrı Karşılama", brandRef: "BR-RETAIL", departmentRef: "DP-SUPPORT", countryRef: "CN-TR", status: "active", agentCount: 4 },
    { id: "PRJ-OUT", code: "PRJ-OUT", name: "Tahsilat Kampanyası", brandRef: "BR-CORP", departmentRef: "DP-COLLECT", countryRef: "CN-TR", status: "paused", agentCount: 2 },
    { id: "PRJ-DE", code: "PRJ-DE", name: "DE Destek Pilotu", brandRef: "BR-RETAIL", departmentRef: "DP-SUPPORT", countryRef: "CN-DE", status: "active", agentCount: 2 },
  ],
};

export async function getOrgStructure(): Promise<OrgStructureSnapshot> {
  const snap = PLACEHOLDER_SNAPSHOT;
  assertNoPii(snap); // HİJYEN: yapısal PII/iş-içeriği yok (BRD §17.7)
  return snap;
}
