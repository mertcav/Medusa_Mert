// WBS 13.4.10 — A-10 "Outbound Kampanya Yönetimi" veri katmanı (seam) + SAF türetme yardımcıları
// (L2 — Operasyon / Uygulama Paneli).
//
// ÇEKİRDEK İLKELER:
//  - İÇERİK (BRD §17.5 A-10 "Outbound Kampanya Yönetimi" — "Liste, zamanlama, consent/suppression,
//    disposition"): bir tenant'ın OUTBOUND KAMPANYALARININ envanteri + uyum/disposition sağlığı. Görünüm
//    yalnız KAMPANYA META taşır — durum (DB §5.4 campaign.status; FR-OUT-010) + maks. deneme/yeniden-arama
//    aralığı (FR-OUT-005) + script/teklif versiyonu ETİKETİ (FR-OUT-009) + arama-saati yapılandırma BAYRAĞI
//    (FR-OUT-004) + consent ön-kontrol BAYRAĞI (FR-OUT-003) + DNC/suppression BAYRAĞI (FR-OUT-006) + kapasite
//    cap/available (FR-OUT-007) + A/B BAYRAĞI (FR-OUT-012) + AGREGAT kontak SAYILARI + per-disposition SAYILAR
//    (FR-OUT-008/011). Ham müşteri kontağı (e164/numara/ad/CRM kaydı/attributes) GÖMÜLMEZ — yalnız SAYI/BAYRAK.
//  - ÇEKİRDEK HİJYEN (BRD §17.7 + §17.6): A-10'un en kritik kuralı son-müşteri PII'sinin (aranacak numara,
//    müşteri adı, contact attributes, CRM external_ref) panele KONMAMASIDIR. Liste yükleme/CRM çekme derin
//    aksiyondur (API dilimi); ekran yalnız AGREGAT (total/dnc/consentMissing/exhausted) + per-disposition
//    SAYIları gösterir. Çağrı kaydı/transkript/CDR de gömülmez.
//  - CONSENT & SUPPRESSION (FR-OUT-003 + FR-OUT-006, SAD §19.1 Consent Engine): outbound çağrı ÖNCESİ consent
//    ve suppression (DNC/do-not-call) kontrolü zorunludur. `consentCheckEnabled` (FR-OUT-003 consent ön-kontrol)
//    + `suppressionEnabled` (FR-OUT-006 DNC gerçek-zamanlı). INVARIANT: AKTİF (running|paused) bir kampanya bu
//    kapıları devre dışı bırakamaz — consentCheckDisabled/suppressionDisabled birer DANGER dikkat kalemidir.
//  - ARAMA SAATLERİ (FR-OUT-004, FR-TEL-013): ülke/bölge arama saati yapılandırılmalı → `callingHoursConfigured`
//    BAYRAĞI (JSONB gövdesi gömülmez). INVARIANT: AKTİF kampanya arama-saati yapılandırması olmadan çalışamaz
//    (callingHoursMissing — DANGER).
//  - DENEME SINIRI (FR-OUT-005): `maxAttempts` + `retryIntervalMinutes`. Kontak `exhausted` = deneme ≥ maks.
//  - KAPASİTE (FR-OUT-007, SAD §6.5 backpressure): kampanya kapasitesi mevcut agent+trunk kapasitesini AŞAMAZ.
//    INVARIANT: `capacityCap` ≤ `capacityAvailable` — aşımı silent/abandoned çağrı riskidir (capacityExceeded — DANGER).
//  - SCRIPT/TEKLİF VERSİYONU (FR-OUT-009): çağrı bazında script/teklif versiyonu kaydedilir → `scriptVersion`
//    ETİKETİ (gövde gömülmez). AKTİF kampanyada eksik versiyon bir config açığıdır (missingScriptVersion — WARNING).
//  - DISPOSITION (FR-OUT-008 + FR-OUT-011): çağrı başına disposition otomatik oluşturulur; voicemail/meşgul/
//    cevapsız/geçersiz-numara AYRI kaydedilir → `dispositions` AGREGAT sayılar (answered/voicemail/busy/no_answer/
//    invalid_number/failed). Yalnız SAYI; çağrı/numara bazında değil.
//  - A/B TEST (FR-OUT-012, Should): `abTest` BAYRAĞI.
//  - TENANT-SCOPE (FR-TEN-002): A-10 yalnız oturum açan tenant'ın KENDİ kampanya envanteri. Scope çalışma-anında
//    middleware (13.1.2) + RLS (DB §6.2) ile sabitlenir; UI yalnız görsel kapı.
//  - GÜVENLİK (NFR 10.6): sır/credential + script/teklif GÖVDESİ + müşteri PII görünüme KONMAZ.
//  - VENDOR-NEUTRAL (ADR-002): veri kaynağı bir SEAM'dir; gerçek implementasyon (F1 §14.1) Campaign Manager +
//    Consent Engine (SAD §19.1) + CRM connector (FR-OUT-002) tenant-scope (RLS) beslenir. Belirli CRM markası bağlanmaz.
//  - SAF/DETERMİNİSTİK: türetme yardımcıları Date.now/rastgelelik içermez → birim-test edilebilir + Python aynası
//    (screens/a10-campaigns/a10_campaigns_probe.py).
//  - İŞ MANTIĞI/AUTHZ YOK (SAD §14.4.1 A8): kampanya oluşturma/durdurma/liste yükleme/dialer kararı YOK; nihai
//    yetki + işlem backend'de (Campaign Manager + Consent Engine) + RLS. Panel yalnız çözümlenmiş envanteri gösterir.
//  - RBAC (BRD §17.6 — L2 A-10 satırı): operations_manager=Yönet · conversation_designer=Düzenle ·
//    qa_analyst=Görüntüle · human_agent=—.

// Kampanya durumu (DB §5.4 campaign.status CHECK; FR-OUT-010 durdurma).
export type CampaignStatus = "draft" | "running" | "paused" | "stopped" | "completed";
// Liste kaynağı (FR-OUT-001 manuel yükleme · FR-OUT-002 CRM dinamik).
export type ListSource = "upload" | "crm";
// Disposition türleri (FR-OUT-008 voicemail/meşgul/cevapsız/geçersiz AYRI + FR-OUT-011 çağrı başına otomatik).
export type DispositionType = "answered" | "voicemail" | "busy" | "no_answer" | "invalid_number" | "failed";

export type StatusTone = "success" | "warning" | "danger" | "neutral" | "info";

// Bir kampanyanın AGREGAT kontak sayıları (ham kontak/PII DEĞİL — yalnız SAYI; BRD §17.7).
export interface ContactStats {
  total: number; // yüklenen kontak sayısı (FR-OUT-001/002)
  dnc: number; // do-not-call/suppression listesinde (FR-OUT-006)
  consentMissing: number; // geçerli consent kaydı olmayan (FR-OUT-003)
  exhausted: number; // deneme ≥ maxAttempts (FR-OUT-005)
}

// Bir outbound kampanya (A-10 çekirdeği). Yalnız KAMPANYA META — ham kontak/numara/script gövdesi DEĞİL.
export interface Campaign {
  campaignRef: string; // kampanya gösterim kimliği (Campaign Manager)
  name: string; // kurumsal kampanya adı (tenant config; son-müşteri PII değil)
  agentRef: string; // bağlı agent gösterim kimliği
  agentName: string; // agent adı (tenant config; PII değil)
  status: CampaignStatus; // FR-OUT-010 (draft|running|paused|stopped|completed)
  listSource: ListSource; // FR-OUT-001 (upload) | FR-OUT-002 (crm)
  maxAttempts: number; // FR-OUT-005 (maksimum deneme sayısı)
  retryIntervalMinutes: number; // FR-OUT-005 (yeniden arama aralığı)
  scriptVersion: string; // FR-OUT-009 (script/teklif versiyonu ETİKETİ — gövde gömülmez; boş=eksik)
  callingHoursConfigured: boolean; // FR-OUT-004 (ülke/bölge arama saati yapılandırıldı mı — yalnız BAYRAK)
  consentCheckEnabled: boolean; // FR-OUT-003 (consent ön-kontrol açık mı)
  suppressionEnabled: boolean; // FR-OUT-006 (DNC/suppression gerçek-zamanlı açık mı)
  abTest: boolean; // FR-OUT-012 (A/B test kampanyası — Should)
  capacityCap: number; // FR-OUT-007 (kampanya kapasite üst sınırı)
  capacityAvailable: number; // FR-OUT-007 (mevcut agent+trunk kapasitesi)
  contacts: ContactStats; // AGREGAT kontak sayıları (ham kontak/PII DEĞİL)
  dispositions: Record<DispositionType, number>; // FR-OUT-008/011 per-outcome SAYILAR
}

export interface OutboundCampaignView {
  generatedAt: string; // ISO-8601 (sabit yer tutucu — SSR-stabil, Date.now YOK)
  tenantRef: string; // tenant'ın KENDİ kimliği (L2'de izinli)
  tenantName: string; // tenant org adı (izinli; son-müşteri verisi DEĞİL)
  campaigns: Campaign[]; // tenant kampanya envanteri (tenant-scope FR-TEN-002)
}

// Kampanya durumlarının görüntüleme sırası (DB §5.4; FR-OUT-010).
export const CAMPAIGN_STATUS_ORDER: CampaignStatus[] = ["draft", "running", "paused", "stopped", "completed"];
// Disposition türlerinin görüntüleme sırası (FR-OUT-008/011).
export const DISPOSITION_ORDER: DispositionType[] = ["answered", "voicemail", "busy", "no_answer", "invalid_number", "failed"];
// "Aktif" (gerçekten arama yapan) durumlar — consent/suppression/saat kapıları bunlara uygulanır.
export const ACTIVE_STATUSES: CampaignStatus[] = ["running", "paused"];

// ── saf türetme yardımcıları ────────────────────────────────────────────────────

// Kampanyaları campaignRef'e göre ARTAN sırala (deterministik, kopya döndürür).
export function sortedCampaigns(campaigns: Campaign[]): Campaign[] {
  return [...campaigns].sort((a, b) => a.campaignRef.localeCompare(b.campaignRef));
}

// Bir kampanya AKTİF mi (running|paused — gerçekten arama yapan).
export function isActive(c: Campaign): boolean {
  return ACTIVE_STATUSES.includes(c.status);
}

// Durum başına kampanya sayısı (tüm durumlar 0'dan başlatılır — DB §5.4).
export function countByStatus(campaigns: Campaign[]): Record<CampaignStatus, number> {
  const acc = {} as Record<CampaignStatus, number>;
  for (const s of CAMPAIGN_STATUS_ORDER) acc[s] = 0;
  for (const c of campaigns) acc[c.status] += 1;
  return acc;
}

// Çalışan kampanyalar (status === "running").
export function runningCampaigns(campaigns: Campaign[]): Campaign[] {
  return campaigns.filter((c) => c.status === "running");
}

// Aktif kampanyalar (running | paused).
export function activeCampaigns(campaigns: Campaign[]): Campaign[] {
  return campaigns.filter(isActive);
}

// A/B test kampanyaları (FR-OUT-012).
export function abTestCampaigns(campaigns: Campaign[]): Campaign[] {
  return campaigns.filter((c) => c.abTest);
}

// Tüm kampanyaların AGREGAT kontak sayıları (ham kontak DEĞİL — SAYI toplamı).
export function aggregateContacts(campaigns: Campaign[]): ContactStats {
  const acc: ContactStats = { total: 0, dnc: 0, consentMissing: 0, exhausted: 0 };
  for (const c of campaigns) {
    acc.total += c.contacts.total;
    acc.dnc += c.contacts.dnc;
    acc.consentMissing += c.contacts.consentMissing;
    acc.exhausted += c.contacts.exhausted;
  }
  return acc;
}

// Aranabilir (reachable) kontak sayısı: toplam − DNC − consent eksik (≥0'a kıstırılır).
export function reachableContacts(campaigns: Campaign[]): number {
  const a = aggregateContacts(campaigns);
  return Math.max(0, a.total - a.dnc - a.consentMissing);
}

// Disposition başına AGREGAT sayı (tüm türler 0'dan başlatılır — FR-OUT-008/011).
export function aggregateDispositions(campaigns: Campaign[]): Record<DispositionType, number> {
  const acc = {} as Record<DispositionType, number>;
  for (const d of DISPOSITION_ORDER) acc[d] = 0;
  for (const c of campaigns) for (const d of DISPOSITION_ORDER) acc[d] += c.dispositions[d] ?? 0;
  return acc;
}

// Toplam disposition sayısı (tüm türler toplamı).
export function totalDispositions(campaigns: Campaign[]): number {
  const agg = aggregateDispositions(campaigns);
  return DISPOSITION_ORDER.reduce((s, d) => s + agg[d], 0);
}

// CONSENT KAPISI KAPALI (FR-OUT-003 ihlali — danger): AKTİF kampanya + consent ön-kontrol devre dışı.
export function consentCheckDisabled(campaigns: Campaign[]): Campaign[] {
  return campaigns.filter((c) => isActive(c) && !c.consentCheckEnabled);
}

// SUPPRESSION KAPISI KAPALI (FR-OUT-006 ihlali — danger): AKTİF kampanya + DNC/suppression devre dışı.
export function suppressionDisabled(campaigns: Campaign[]): Campaign[] {
  return campaigns.filter((c) => isActive(c) && !c.suppressionEnabled);
}

// ARAMA SAATİ EKSİK (FR-OUT-004 ihlali — danger): AKTİF kampanya + arama-saati yapılandırması yok.
export function callingHoursMissing(campaigns: Campaign[]): Campaign[] {
  return campaigns.filter((c) => isActive(c) && !c.callingHoursConfigured);
}

// KAPASİTE AŞIMI (FR-OUT-007 ihlali — danger): capacityCap > capacityAvailable (durumdan bağımsız config açığı).
export function capacityExceeded(campaigns: Campaign[]): Campaign[] {
  return campaigns.filter((c) => c.capacityCap > c.capacityAvailable);
}

// SCRIPT/TEKLİF VERSİYONU EKSİK (FR-OUT-009 — warning): AKTİF kampanya + scriptVersion boş.
export function missingScriptVersion(campaigns: Campaign[]): Campaign[] {
  return campaigns.filter((c) => isActive(c) && c.scriptVersion.trim() === "");
}

// Aktif kampanyaların agregat kapasite kullanım yüzdesi (cap/available; available=0 ise 0).
export function capacityUtilPct(campaigns: Campaign[]): number {
  const act = activeCampaigns(campaigns);
  const cap = act.reduce((s, c) => s + c.capacityCap, 0);
  const avail = act.reduce((s, c) => s + c.capacityAvailable, 0);
  return avail > 0 ? Math.round((cap / avail) * 100) : 0;
}

// Açık dikkat sayısı: consent kapalı + suppression kapalı + arama saati eksik + kapasite aşımı + script eksik.
export function openAttentionCount(campaigns: Campaign[]): number {
  return (
    consentCheckDisabled(campaigns).length +
    suppressionDisabled(campaigns).length +
    callingHoursMissing(campaigns).length +
    capacityExceeded(campaigns).length +
    missingScriptVersion(campaigns).length
  );
}

// ── ton (renk) eşlemeleri ─────────────────────────────────────────────────────────

const STATUS_TONE: Record<CampaignStatus, StatusTone> = {
  draft: "neutral",
  running: "success",
  paused: "warning",
  stopped: "neutral",
  completed: "info",
};
export function statusTone(s: CampaignStatus): StatusTone {
  return STATUS_TONE[s];
}

const DISPOSITION_TONE: Record<DispositionType, StatusTone> = {
  answered: "success",
  voicemail: "info",
  busy: "warning",
  no_answer: "warning",
  invalid_number: "danger",
  failed: "danger",
};
export function dispositionTone(d: DispositionType): StatusTone {
  return DISPOSITION_TONE[d];
}

const LIST_SOURCE_TONE: Record<ListSource, StatusTone> = {
  upload: "neutral",
  crm: "info",
};
export function listSourceTone(s: ListSource): StatusTone {
  return LIST_SOURCE_TONE[s];
}

// Bayrak tonu: olumlu durum (true) → success; eksik (false) → çağıran karar verir.
export function boolTone(ok: boolean): StatusTone {
  return ok ? "success" : "danger";
}

// ── HİJYEN + GÜVENLİK koruması ─────────────────────────────────────────────────────
// Yapı içinde son-müşteri ham iş içeriği/PII'yi (aranacak numara/müşteri adı/contact attributes/CRM external_ref/
// transkript/kayıt/CDR) VEYA sır/credential/script GÖVDESİ çağrıştıran ALAN ADI bulunursa hata fırlatır. Bu,
// A-10'un yalnız KAMPANYA META veriyi (durum/deneme/script-versiyonu ETİKETİ/arama-saati BAYRAĞI/consent BAYRAĞI/
// suppression BAYRAĞI/kapasite/A-B BAYRAĞI + AGREGAT kontak SAYILARI + per-disposition SAYILAR + kampanya/agent adı —
// tenant'ın KENDİ yapılandırması) — ham müşteri kontağı/numara/PII/CDR + script GÖVDESİ DEĞİL — göstermesini
// garanti eder (BRD §17.7 + §17.6 + NFR 10.6).
export const FORBIDDEN_PII_KEYS: readonly string[] = [
  "transcript",
  "recording",
  "recordingurl",
  "audio",
  "msisdn",
  "phonenumber",
  "e164", // aranacak ham numara — GÖMÜLMEZ (ÇEKİRDEK A-10 kuralı)
  "dialednumber",
  "callerid",
  "callernumber",
  "calleenumber",
  "customer",
  "customername",
  "contactname",
  "attributes", // contact.attributes JSONB (müşteri PII; DB §5.4) — GÖMÜLMEZ
  "externalref", // contact.external_ref (CRM kaydı; FR-OUT-002) — GÖMÜLMEZ
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
  "signingsecret",
  "token",
  "bearertoken",
  "accesstoken",
  "refreshtoken",
  "credential",
  "password",
  "privatekey",
  "kmskey",
  "authheader",
  "scriptbody", // script/teklif GÖVDESİ — gömülmez (yalnız scriptVersion ETİKETİ; FR-OUT-009)
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
        throw new Error(`A-10 HİJYEN ihlali: yasak PII/müşteri-kontağı alanı "${path}.${k}" (BRD §17.7)`);
      }
      if (FORBIDDEN_SECRET_KEYS.includes(lower)) {
        throw new Error(`A-10 GÜVENLİK ihlali: sır/credential/script-gövdesi alanı "${path}.${k}" panele konmaz (NFR 10.6)`);
      }
      assertNoPii((node as Record<string, unknown>)[k], `${path}.${k}`);
    }
  }
}

// ── veri SEAM (yer tutucu) ───────────────────────────────────────────────────────
// Deterministik yer tutucu: tek-tenant kampanya envanteri (KAMPANYA META yalnız — ham kontak/numara/PII/script
// gövdesi DEĞİL). Gerçek implementasyon (F1 §14.1) Campaign Manager + Consent Engine (SAD §19.1) + CRM connector
// (FR-OUT-002) tenant-scope (RLS) beslenir. Bu örnek: 5 kampanya (running/paused/completed/draft) — biri consent
// kapalı (FR-OUT-003), biri suppression+arama-saati kapalı+kapasite aşımı+script eksik (FR-OUT-006/004/007/009),
// biri A/B test (FR-OUT-012), biri draft kapasite aşımı → birkaç dikkat kalemi.
const PLACEHOLDER_VIEW: OutboundCampaignView = {
  generatedAt: "2026-06-19T09:00:00.000Z",
  tenantRef: "TEN-2048",
  tenantName: "Kuzey Sigorta A.Ş.",
  campaigns: [
    {
      campaignRef: "CMP-01",
      name: "Poliçe Yenileme Hatırlatma",
      agentRef: "AGT-117",
      agentName: "Sigorta Asistanı",
      status: "running",
      listSource: "crm",
      maxAttempts: 3,
      retryIntervalMinutes: 240,
      scriptVersion: "v3.2",
      callingHoursConfigured: true,
      consentCheckEnabled: true,
      suppressionEnabled: true,
      abTest: false,
      capacityCap: 20,
      capacityAvailable: 40,
      contacts: { total: 1200, dnc: 45, consentMissing: 0, exhausted: 120 },
      dispositions: { answered: 420, voicemail: 180, busy: 90, no_answer: 150, invalid_number: 24, failed: 16 },
    },
    {
      campaignRef: "CMP-02",
      name: "Çapraz Satış — Konut",
      agentRef: "AGT-204",
      agentName: "Satış Botu",
      status: "running",
      listSource: "upload",
      maxAttempts: 2,
      retryIntervalMinutes: 1440,
      scriptVersion: "v1.0",
      callingHoursConfigured: true,
      consentCheckEnabled: false, // FR-OUT-003 ihlali → danger
      suppressionEnabled: true,
      abTest: true, // FR-OUT-012
      capacityCap: 10,
      capacityAvailable: 20,
      contacts: { total: 500, dnc: 12, consentMissing: 60, exhausted: 30 },
      dispositions: { answered: 90, voicemail: 40, busy: 20, no_answer: 35, invalid_number: 8, failed: 4 },
    },
    {
      campaignRef: "CMP-03",
      name: "Memnuniyet Anketi",
      agentRef: "AGT-309",
      agentName: "Anket Botu",
      status: "paused",
      listSource: "upload",
      maxAttempts: 4,
      retryIntervalMinutes: 720,
      scriptVersion: "", // FR-OUT-009 eksik → warning
      callingHoursConfigured: false, // FR-OUT-004 ihlali → danger
      consentCheckEnabled: true,
      suppressionEnabled: false, // FR-OUT-006 ihlali → danger
      abTest: false,
      capacityCap: 30,
      capacityAvailable: 20, // FR-OUT-007 ihlali (cap>avail) → danger
      contacts: { total: 800, dnc: 20, consentMissing: 0, exhausted: 0 },
      dispositions: { answered: 0, voicemail: 0, busy: 0, no_answer: 0, invalid_number: 0, failed: 0 },
    },
    {
      campaignRef: "CMP-04",
      name: "Geç Ödeme Bilgilendirme",
      agentRef: "AGT-204",
      agentName: "Tahsilat Botu",
      status: "completed",
      listSource: "crm",
      maxAttempts: 3,
      retryIntervalMinutes: 360,
      scriptVersion: "v2.1",
      callingHoursConfigured: true,
      consentCheckEnabled: true,
      suppressionEnabled: true,
      abTest: false,
      capacityCap: 0,
      capacityAvailable: 20,
      contacts: { total: 640, dnc: 30, consentMissing: 0, exhausted: 600 },
      dispositions: { answered: 300, voicemail: 120, busy: 60, no_answer: 110, invalid_number: 30, failed: 20 },
    },
    {
      campaignRef: "CMP-05",
      name: "Yeni Ürün Tanıtımı (Taslak)",
      agentRef: "AGT-117",
      agentName: "Sigorta Asistanı",
      status: "draft",
      listSource: "upload",
      maxAttempts: 3,
      retryIntervalMinutes: 480,
      scriptVersion: "v0.1",
      callingHoursConfigured: false, // taslak → aktif değil; arama-saati uyarısı saymaz
      consentCheckEnabled: false, // taslak → aktif değil; consent uyarısı saymaz
      suppressionEnabled: false,
      abTest: false,
      capacityCap: 100,
      capacityAvailable: 20, // FR-OUT-007 (durumdan bağımsız config açığı) → danger
      contacts: { total: 0, dnc: 0, consentMissing: 0, exhausted: 0 },
      dispositions: { answered: 0, voicemail: 0, busy: 0, no_answer: 0, invalid_number: 0, failed: 0 },
    },
  ],
};

export async function getOutboundCampaignView(): Promise<OutboundCampaignView> {
  const view = PLACEHOLDER_VIEW;
  assertNoPii(view); // HİJYEN + GÜVENLİK: yapısal son-müşteri PII / sır / script gövdesi yok (BRD §17.7 / NFR 10.6)
  return view;
}
