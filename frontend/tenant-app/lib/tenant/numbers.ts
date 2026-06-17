// WBS 13.3.4 — T-04 "Telefon Numarası & SIP/Trunk" veri katmanı (seam) + SAF türetme yardımcıları
// (L1 — Tenant Admin Console).
//
// ÇEKİRDEK İLKELER:
//  - İÇERİK (BRD §17.4 / FR-TEL-001/002/004/005 · FR-AGT-007): tenant'ın telefon NUMARA HAVUZU (E.164
//    DID'ler), SIP trunk / BYOC (Bring Your Own Carrier) bağlantıları ve giden Caller ID yönetimi.
//  - TENANT-SCOPE (FR-TEN-002): T-04 YALNIZ oturum açan tenant'ın KENDİ numaralarını/trunk'larını gösterir/
//    yönetir; başka tenant'ın telefoni envanteri erişilmez. Scope çalışma-anında middleware (13.1.2) + RLS
//    (§13) ile sabitlenir; UI yalnız görsel kapı (SAD §14.4.1 A8).
//  - HİJYEN (BRD §17.7 ruhu): yapı yalnız tenant'ın KENDİ TELEFONİ KONFİGÜRASYONUDUR (sahip olunan DID'ler,
//    trunk ayarları, giden Caller ID). Ham SON-MÜŞTERİ iş içeriği (çağrı kaydı, transkript, ARAYAN/çağrılan
//    müşteri numarası/PII) buraya GÖMÜLMEZ. Tipler yapısal olarak son-müşteri PII taşımaz; `assertNoPii`
//    çalışma-anında doğrular. NOT: `e164` tenant'ın KENDİ sağlanmış numarasıdır (tenantName gibi izinli —
//    son-müşteri PII DEĞİL); yasak liste yalnız SON-MÜŞTERİ içerik/PII alan adlarıdır (msisdn/callerId/...).
//  - GÜVENLİK: SIP trunk SIRRI (kayıt/registration parolası, auth token, IP-ACL kimlik bilgisi) buraya
//    KONMAZ — yalnız bağlantı durumu + kapasite metadatası. Gerçek sır backend secret store'da (NFR 10.6);
//    UI sırrı göstermez.
//  - VENDOR-NEUTRAL (ADR-002): veri kaynağı bir SEAM'dir; gerçek implementasyon (F2 §14.1) Telephony/Number
//    Manager + SBC/trunk envanterinden tenant-scope beslenir. Belirli operatör/SaaS bağlanmaz (BYOC dahil).
//  - SAF/DETERMİNİSTİK: türetme yardımcıları (countNumberStatus/unassignedNumbers/isValidE164/...) Date.now/
//    rastgelelik içermez → birim-test edilebilir + Python aynası (screens/t04-numbers/t04_numbers_probe.py).
//  - İŞ MANTIĞI/AUTHZ YOK (SAD §14.4.1 A8): numara atama/trunk açma kararı YOK; nihai yetki backend'de
//    (12.2.x) + RLS.

export type NumberDirection = "inbound" | "outbound" | "both";
export type NumberStatus = "active" | "reserved" | "porting" | "released";
export type TrunkType = "sip_trunk" | "byoc" | "managed"; // FR-TEL-002 (SIP trunk + BYOC) / managed telephony
export type ConnState = "connected" | "degraded" | "disabled" | "error";
export type CallerIdStatus = "verified" | "pending" | "rejected";

export type StatusTone = "success" | "warning" | "danger" | "neutral" | "info";

// SIP trunk / BYOC bağlantısı (FR-TEL-002). SIR YOK — yalnız durum + kapasite metadatası.
export interface SipTrunk {
  id: string;
  name: string; // tenant konfigürasyon etiketi (izinli)
  type: TrunkType; // sip_trunk | byoc | managed
  state: ConnState;
  region: string; // home/residency bölgesi (NFR 10.7) — kod (ör. eu-west); konum verisi DEĞİL
  inbound: boolean; // gelen PSTN (FR-TEL-001)
  outbound: boolean; // giden PSTN (FR-TEL-001)
  channels: number; // eş zamanlı kanal kapasitesi
  channelsInUse: number; // anlık kullanılan kanal (kapasite kontrolü FR-OUT-007)
}

// Tenant'ın sağlanmış telefon numarası (E.164 DID, FR-TEL-004). e164 tenant'ın KENDİ envanteridir (son-
// müşteri PII DEĞİL). assignedTo = atandığı agent/kampanya referansı (FR-AGT-007); null => havuzda boşta.
export interface PhoneNumber {
  id: string;
  e164: string; // E.164 biçimi (FR-TEL-004) — tenant'ın KENDİ DID'i (izinli)
  label: string | null; // tenant etiketi (izinli)
  direction: NumberDirection; // inbound | outbound | both
  trunkRef: string | null; // bağlı SipTrunk.id (null => atanmamış)
  assignedTo: string | null; // agent/kampanya atama referansı (FR-AGT-007); null => havuz (boşta)
  status: NumberStatus;
}

// Giden Caller ID (FR-TEL-005). Tenant'ın KENDİ sunum numarası (izinli); doğrulama durumu + varsayılan bayrağı.
export interface CallerId {
  id: string;
  e164: string; // giden sunum numarası (tenant'ın KENDİ, izinli)
  label: string | null;
  status: CallerIdStatus; // doğrulama: verified | pending | rejected
  isDefault: boolean; // giden çağrılarda varsayılan sunum
}

export interface NumberSnapshot {
  generatedAt: string; // ISO-8601 (sabit yer tutucu — SSR-stabil, Date.now YOK)
  tenantRef: string; // tenant'ın KENDİ kimliği (L1'de izinli)
  tenantName: string; // tenant org adı (izinli; son-müşteri verisi DEĞİL)
  trunks: SipTrunk[];
  numbers: PhoneNumber[];
  callerIds: CallerId[];
}

// ── saf türetme yardımcıları ────────────────────────────────────────────────────

// Durum bazında numara sayısı.
export function countNumberStatus(numbers: PhoneNumber[]): Record<NumberStatus, number> {
  const out: Record<NumberStatus, number> = { active: 0, reserved: 0, porting: 0, released: 0 };
  for (const n of numbers) out[n.status] += 1;
  return out;
}

// Yön bazında numara sayısı (inbound / outbound / both).
export function countNumberDirection(numbers: PhoneNumber[]): Record<NumberDirection, number> {
  const out: Record<NumberDirection, number> = { inbound: 0, outbound: 0, both: 0 };
  for (const n of numbers) out[n.direction] += 1;
  return out;
}

// HAVUZ: aktif ama hiçbir agent/kampanyaya ATANMAMIŞ numaralar (boşta — FR-AGT-007). id listesi.
export function unassignedNumbers(numbers: PhoneNumber[]): string[] {
  return numbers.filter((n) => n.status === "active" && (n.assignedTo === null || n.assignedTo.trim() === "")).map((n) => n.id);
}

// Bir trunk'a bağlı numara sayısı.
export function numbersForTrunk(numbers: PhoneNumber[], trunkId: string): number {
  return numbers.filter((n) => n.trunkRef === trunkId).length;
}

// HİJYEN/BÜTÜNLÜK: tanımlı OLMAYAN bir trunk'a bağlanmış numaralar (geçersiz trunk referansı). id listesi.
// Boş dönmesi envanter tutarlılığını gösterir; dolu liste trunk referansı düzeltmesi (UI uyarısı) tetikler.
export function invalidTrunkRefs(numbers: PhoneNumber[], trunks: SipTrunk[]): string[] {
  const ids = new Set(trunks.map((tk) => tk.id));
  return numbers.filter((n) => n.trunkRef !== null && n.trunkRef.trim() !== "" && !ids.has(n.trunkRef)).map((n) => n.id);
}

// E.164 doğrulama (FR-TEL-004): "+" + ülke kodu (1-9) + toplam 1..15 hane. Saf; biçim kontrolü (tahsis DEĞİL).
export function isValidE164(s: string): boolean {
  return /^\+[1-9]\d{0,14}$/.test(s);
}

// BÜTÜNLÜK: E.164 biçimine uymayan numaralar (FR-TEL-004 ihlali). id listesi → UI uyarısı.
export function invalidE164Numbers(numbers: PhoneNumber[]): string[] {
  return numbers.filter((n) => !isValidE164(n.e164)).map((n) => n.id);
}

// Trunk kanal kullanım yüzdesi (channelsInUse/channels), [0,100] kıstırma. channels<=0 => 0.
export function trunkUtilizationPct(trunk: SipTrunk): number {
  if (trunk.channels <= 0) return 0;
  const pct = (trunk.channelsInUse / trunk.channels) * 100;
  return Math.max(0, Math.min(100, Math.round(pct)));
}

// KAPASITE: kullanımı eşiği aşan trunk'lar (FR-OUT-007 / FR-TEL-015 kapasite kontrolü). Varsayılan ≥90%. id listesi.
export function overCapacityTrunks(trunks: SipTrunk[], thresholdPct = 90): string[] {
  return trunks.filter((tk) => trunkUtilizationPct(tk) >= thresholdPct).map((tk) => tk.id);
}

// Varsayılan işaretli ama DOĞRULANMAMIŞ Caller ID'ler (FR-TEL-005). id listesi → UI uyarısı (giden sunum riski).
export function unverifiedDefaultCallerIds(callerIds: CallerId[]): string[] {
  return callerIds.filter((c) => c.isDefault && c.status !== "verified").map((c) => c.id);
}

// ── ton (renk) eşlemeleri ─────────────────────────────────────────────────────────

const NUMBER_STATUS_TONE: Record<NumberStatus, StatusTone> = {
  active: "success",
  reserved: "info",
  porting: "warning",
  released: "neutral",
};
export function numberStatusTone(s: NumberStatus): StatusTone {
  return NUMBER_STATUS_TONE[s];
}

const TRUNK_STATE_TONE: Record<ConnState, StatusTone> = {
  connected: "success",
  degraded: "warning",
  disabled: "neutral",
  error: "danger",
};
export function trunkStateTone(s: ConnState): StatusTone {
  return TRUNK_STATE_TONE[s];
}

const TRUNK_TYPE_TONE: Record<TrunkType, StatusTone> = {
  sip_trunk: "info",
  byoc: "info",
  managed: "neutral",
};
export function trunkTypeTone(t: TrunkType): StatusTone {
  return TRUNK_TYPE_TONE[t];
}

const CALLER_ID_TONE: Record<CallerIdStatus, StatusTone> = {
  verified: "success",
  pending: "warning",
  rejected: "danger",
};
export function callerIdStatusTone(s: CallerIdStatus): StatusTone {
  return CALLER_ID_TONE[s];
}

const DIRECTION_TONE: Record<NumberDirection, StatusTone> = {
  inbound: "info",
  outbound: "info",
  both: "neutral",
};
export function directionTone(d: NumberDirection): StatusTone {
  return DIRECTION_TONE[d];
}

// Kullanım yüzdesi tonu (≥90 danger / ≥75 warning / aksi success).
export function utilTone(pct: number): StatusTone {
  if (pct >= 90) return "danger";
  if (pct >= 75) return "warning";
  return "success";
}

// ── HİJYEN koruması (ham son-müşteri PII/iş-içeriği sızıntısı) ─────────────────────
// Yapı içinde son-müşteri iş içeriği/PII'yi çağrıştıran ALAN ADI bulunursa hata fırlatır. Bu, T-04'ün yalnız
// tenant'ın KENDİ telefoni konfigürasyonunu göstermesini çalışma-anında garanti eder (BRD §17.7 ruhu).
// NOT: tenantName/tenantRef + numara `e164` + trunk `name` tenant'ın KENDİ envanteridir → yasak listede
// DEĞİL (izinli). Yasak liste yalnız SON-MÜŞTERİ (arayan/çağrılan) PII/çağrı içeriği alan adlarıdır.
export const FORBIDDEN_PII_KEYS: readonly string[] = [
  "transcript",
  "recording",
  "recordingurl",
  "audio",
  "msisdn",
  "phonenumber",
  "callerid", // son-müşteri (arayan) kimliği — tenant'ın KENDİ giden Caller ID'si `e164` ile taşınır
  "callernumber",
  "customer",
  "cardpan",
  "cvv",
  "ssn",
  "pii",
];

// GÜVENLİK ek koruması: SIP trunk SIRRI alan adı (kayıt parolası/auth token/credential) buraya konmamalı (NFR 10.6).
export const FORBIDDEN_SECRET_KEYS: readonly string[] = [
  "password",
  "sippassword",
  "secret",
  "token",
  "authtoken",
  "credential",
  "apikey",
  "privatekey",
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
        throw new Error(`T-04 HİJYEN ihlali: yasak PII/iş-içeriği alanı "${path}.${k}" (BRD §17.7)`);
      }
      if (FORBIDDEN_SECRET_KEYS.includes(lower)) {
        throw new Error(`T-04 GÜVENLİK ihlali: SIP trunk sırrı alanı "${path}.${k}" panele konmaz (NFR 10.6)`);
      }
      assertNoPii((node as Record<string, unknown>)[k], `${path}.${k}`);
    }
  }
}

// ── veri SEAM (yer tutucu) ───────────────────────────────────────────────────────
// Deterministik yer tutucu: tek-tenant telefoni konfigürasyonu (KENDİ DID havuzu + trunk/BYOC + giden Caller
// ID — son-müşteri PII/iş-içeriği DEĞİL, trunk SIRRI DEĞİL). Gerçek implementasyon (F2 §14.1) Telephony/Number
// Manager + SBC/trunk envanterinden tenant-scope (RLS) beslenir.
const PLACEHOLDER_SNAPSHOT: NumberSnapshot = {
  generatedAt: "2026-06-17T09:00:00.000Z",
  tenantRef: "TEN-2048",
  tenantName: "Kuzey Sigorta A.Ş.",
  trunks: [
    { id: "TRK-01", name: "Birincil SIP Trunk", type: "sip_trunk", state: "connected", region: "eu-west", inbound: true, outbound: true, channels: 200, channelsInUse: 96 },
    { id: "TRK-02", name: "Operatör BYOC (Yedek)", type: "byoc", state: "connected", region: "eu-west", inbound: true, outbound: true, channels: 100, channelsInUse: 92 },
    { id: "TRK-03", name: "Managed Telefoni (Pilot)", type: "managed", state: "degraded", region: "eu-central", inbound: true, outbound: false, channels: 50, channelsInUse: 8 },
  ],
  numbers: [
    { id: "N-001", e164: "+902123456789", label: "Çağrı Merkezi Ana Hat", direction: "inbound", trunkRef: "TRK-01", assignedTo: "AGT-SUPPORT", status: "active" },
    { id: "N-002", e164: "+908502222222", label: "Destek (Ücretsiz)", direction: "inbound", trunkRef: "TRK-01", assignedTo: "AGT-SUPPORT", status: "active" },
    { id: "N-003", e164: "+902129990000", label: "Tahsilat Giden", direction: "outbound", trunkRef: "TRK-02", assignedTo: "CMP-COLLECT", status: "active" },
    { id: "N-004", e164: "+902123334455", label: "Havuz — Boşta", direction: "both", trunkRef: "TRK-01", assignedTo: null, status: "active" },
    { id: "N-005", e164: "+443069990000", label: "UK Inbound (Porting)", direction: "inbound", trunkRef: "TRK-03", assignedTo: null, status: "porting" },
    { id: "N-006", e164: "+902120001122", label: "Rezerve", direction: "both", trunkRef: null, assignedTo: null, status: "reserved" },
  ],
  callerIds: [
    { id: "CID-01", e164: "+902123456789", label: "Kurumsal Ana Hat", status: "verified", isDefault: true },
    { id: "CID-02", e164: "+908502222222", label: "Destek Hattı", status: "verified", isDefault: false },
    { id: "CID-03", e164: "+902129990000", label: "Tahsilat Sunum", status: "pending", isDefault: false },
  ],
};

export async function getNumbers(): Promise<NumberSnapshot> {
  const snap = PLACEHOLDER_SNAPSHOT;
  assertNoPii(snap); // HİJYEN + GÜVENLİK: yapısal son-müşteri PII / trunk sırrı yok (BRD §17.7 / NFR 10.6)
  return snap;
}
