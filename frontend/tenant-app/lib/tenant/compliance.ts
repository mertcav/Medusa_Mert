// WBS 13.3.6 — T-06 "Compliance & Retention" veri katmanı (seam) + SAF türetme yardımcıları
// (L1 — Tenant Admin Console).
//
// ÇEKİRDEK İLKELER:
//  - İÇERİK (BRD §17.4 / FR-REC-001..010 · FR-OUT-003/006 · DPIA cp.* · NFR 10.7): tenant'ın CONSENT
//    (rıza modeli), KAYIT POLİTİKASI (recording policy + PII redaction + kart/OTP maskeleme), VERİ
//    YERLEŞİMİ (residency / home-region + provider pinning), SAKLAMA SÜRESİ (retention: kayıt/transkript/
//    audit + legal hold), COMPLIANCE PROFILE (ülke profili + sektörel overlay + most-restrictive-wins) ve
//    İYS/DNC (outbound consent registry + do-not-call) konfigürasyonu. Ayrıca DSR (veri sahibi hakları) +
//    ihlal bildirimi + DPIA durumu.
//  - TENANT-SCOPE (FR-TEN-002): T-06 YALNIZ oturum açan tenant'ın KENDİ compliance/retention profilini
//    gösterir/yönetir; başka tenant'ın profili erişilmez. Scope çalışma-anında middleware (13.1.2) + RLS
//    (§13) ile sabitlenir; UI yalnız görsel kapı (SAD §14.4.1 A8).
//  - HİJYEN (BRD §17.7): yapı yalnız tenant'ın KENDİ POLİTİKA/PROFİL KONFİGÜRASYONUDUR (rıza modeli,
//    saklama günleri, residency bayrakları, profil kodu). Ham SON-MÜŞTERİ iş içeriği (çağrı kaydı,
//    transkript, bireysel rıza/DNC kaydı, müşteri PII) buraya GÖMÜLMEZ — bunlar L2/data-plane'de tutulur.
//    `assertNoPii` çalışma-anında doğrular. NOT: profil/policy alan ADLARI politika parametresidir
//    (`recordingPolicy`/`piiRedaction` gibi) — son-müşteri kaydı DEĞİL.
//  - GÜVENLİK (NFR 10.6): SIR buraya KONMAZ — KMS anahtarı, DPA imza materyali, sağlayıcı credential
//    panele konmaz; yalnız politika bayrakları + durum. Compliance değerleri MÜHENDİSLİK VARSAYILANIDIR;
//    counsel (hukuk danışmanı) doğrulamasına tabidir (DPIA §12).
//  - VENDOR-NEUTRAL (ADR-002): veri kaynağı bir SEAM'dir; gerçek implementasyon (F2 §14.1) Compliance
//    Profile çözümleyici (SAD §19) + Consent Engine + Retention motorundan tenant-scope (RLS) beslenir.
//    Belirli ülke/sektör hukuki yorumu bağlanmaz (DPIA §12).
//  - SAF/DETERMİNİSTİK: türetme yardımcıları (disclosureGaps/residencyGaps/loosenOverrides/...) Date.now/
//    rastgelelik içermez → birim-test edilebilir + Python aynası (screens/t06-compliance/t06_compliance_probe.py).
//  - İŞ MANTIĞI/AUTHZ YOK (SAD §14.4.1 A8): profil değiştirme/override onaylama kararı YOK; nihai yetki
//    backend'de (12.2.x) + RLS. MOST-RESTRICTIVE-WINS çözümleme + override yalnız-sıkılaştırır kuralı
//    backend'de zorlanır; panel yalnız çözümlenmiş profili gösterir + gevşeten override'ı AUDIT olarak işaretler.

export type CountryProfile = "PROFILE-TR" | "PROFILE-UK" | "PROFILE-EU" | "PROFILE-ME"; // DPIA §6
export type Regime = "KVKK" | "UK_GDPR" | "EU_GDPR" | "ME"; // cp.legal.regime
export type RecordingConsentModel = "notice" | "explicit_optin" | "all_party"; // cp.transparency.recording_consent_model
export type ChannelMode = "single" | "dual" | "off"; // FR-REC-002/003
export type ConsentModel = "opt_in" | "soft_opt_in" | "opt_out"; // cp.outbound.consent_model
export type HomeRegion = "UK" | "EU" | "NA" | "ME"; // cp.residency.home_region (NFR 10.7)
export type CrossBorderMechanism = "scc" | "adequacy" | "explicit_consent" | "none"; // cp.residency.cross_border_mechanism
export type DpiaStatus = "not_required" | "required" | "in_progress" | "completed"; // DPIA §3 onboarding gate
export type OverrideDirection = "tighten" | "equal" | "loosen"; // most-restrictive-wins: loosen = İHLAL
export type DataSubjectNotice = "high_risk" | "always"; // cp.breach.data_subject_notice

export type StatusTone = "success" | "warning" | "danger" | "neutral" | "info";

// Compliance profile (çözümlenmiş): ülke profili + sektörel overlay'ler + çözümleme stratejisi (DPIA §6/§7).
export interface ProfileConfig {
  countryProfile: CountryProfile; // PROFILE-TR/UK/EU/ME (DPIA §6)
  regime: Regime; // cp.legal.regime
  sectorOverlays: string[]; // cp.sector.profiles (PCI/FCA/HIPAA/...) — overlay ADI (sır DEĞİL)
  lawfulBasisDefault: string; // cp.legal.lawful_basis_default (öneri; counsel teyit eder)
  dpaRequired: boolean; // cp.legal.dpa_required
}

// Kayıt politikası (FR-REC-001/002/003/004/005). Ham kayıt/transkript DEĞİL — yalnız politika bayrakları.
export interface RecordingPolicyConfig {
  channelMode: ChannelMode; // off => kayıt kapalı (FR-REC-002); single/dual (FR-REC-003)
  recordingConsentModel: RecordingConsentModel; // notice/explicit_optin/all_party (cp.transparency)
  piiRedaction: boolean; // transkript PII redaction (FR-REC-004)
  cardOtpMasking: boolean; // kart/parola/OTP çıkarma (FR-REC-005)
}

// Şeffaflık & AI/kayıt bildirimi (cp.transparency.*, BRD §14.2). required = profil zorunlu kılıyor;
// configured = tenant açılış metninde yapılandırmış.
export interface TransparencyConfig {
  aiDisclosureRequired: boolean; // cp.transparency.ai_disclosure_required
  aiDisclosureConfigured: boolean; // tenant açılış turunda yapılandırdı mı
  recordingNoticeRequired: boolean; // cp.transparency.recording_notice_required
  recordingNoticeConfigured: boolean;
  noDeceptiveImpersonation: boolean; // cp.transparency.no_deceptive_impersonation (sabit true)
}

// Veri yerleşimi / residency (cp.residency.*, NFR 10.7, SAD §12.3).
export interface ResidencyConfig {
  homeRegion: HomeRegion; // cp.residency.home_region
  inRegionStorageRequired: boolean; // cp.residency.in_region_storage_required
  providerRegionPinning: boolean; // cp.residency.provider_region_pinning (adapter region selection)
  crossBorderMechanism: CrossBorderMechanism; // cp.residency.cross_border_mechanism
}

// Saklama (cp.retention.*, FR-REC-006/007/010). Gün cinsinden; legalHoldActive = aktif legal hold sayısı.
export interface RetentionConfig {
  recordingDays: number; // cp.retention.recording_days
  transcriptDays: number; // cp.retention.transcript_days
  auditDays: number; // cp.retention.audit_days (≥ yasal asgari)
  legalHoldSupported: boolean; // cp.retention.legal_hold_supported (FR-REC-007)
  legalHoldActive: number; // aktif legal hold sayısı (silmeyi geçersiz kılar) — adet metadatası
}

// Outbound uygunluğu / İYS/DNC (cp.outbound.*, FR-OUT-003/004/006). Bireysel DNC kaydı DEĞİL — yalnız
// kaynak/kayıt ADI ve politika.
export interface OutboundConfig {
  consentModel: ConsentModel; // cp.outbound.consent_model
  consentRegistry: string; // cp.outbound.consent_registry (IYS / TPS-CTPS / "none") — kayıt ADI
  dncLists: string[]; // cp.outbound.dnc_lists — kaynak ADLARI (IYS_ret/...) — birey numarası DEĞİL
  callingHoursLocal: string; // cp.outbound.calling_hours_local (ör. "09:00–20:00")
  cliPresentationRequired: boolean; // cp.outbound.cli_presentation_required
  b2bExemption: boolean; // cp.outbound.b2b_exemption
}

// Veri sahibi hakları / DSR (cp.dsr.*, BRD §14.1).
export interface DsrConfig {
  accessSlaDays: number; // cp.dsr.access_sla_days
  erasureSlaDays: number; // cp.dsr.erasure_sla_days
  rectificationSupported: boolean; // cp.dsr.rectification_supported
  portabilitySupported: boolean; // cp.dsr.portability_supported
}

// İhlal bildirimi (cp.breach.*, BRD §14.1).
export interface BreachConfig {
  authority: string; // cp.breach.authority (KVKK/ICO/...) — makam ADI
  authorityDeadlineHours: number; // cp.breach.authority_deadline_hours
  dataSubjectNotice: DataSubjectNotice; // cp.breach.data_subject_notice
}

// DPIA durumu (DPIA §3 onboarding gate).
export interface DpiaConfig {
  status: DpiaStatus; // not_required/required/in_progress/completed
  triggers: string[]; // tetiklenen DPIA-T-NN kodları (DPIA §3) — kod ADI
}

// Tenant override (most-restrictive-wins): tenant yalnız SIKILAŞTIRABİLİR; gevşeten override AUDIT ihlalidir
// (CLAUDE.md / DPIA §8). direction backend çözümleyicinin sınıflandırmasıdır; panel gevşeteni işaretler.
export interface ComplianceOverride {
  id: string;
  key: string; // cp.* parametre yolu (ör. cp.retention.recording_days) — izinli
  baseline: string; // profil tabanı (gösterim değeri)
  value: string; // tenant override değeri (gösterim değeri)
  direction: OverrideDirection; // tighten/equal/loosen (backend çözümleyici sınıflandırması)
}

export interface ComplianceSnapshot {
  generatedAt: string; // ISO-8601 (sabit yer tutucu — SSR-stabil, Date.now YOK)
  tenantRef: string; // tenant'ın KENDİ kimliği (L1'de izinli)
  tenantName: string; // tenant org adı (izinli; son-müşteri verisi DEĞİL)
  profile: ProfileConfig;
  recordingPolicy: RecordingPolicyConfig;
  transparency: TransparencyConfig;
  residency: ResidencyConfig;
  retention: RetentionConfig;
  outbound: OutboundConfig;
  dsr: DsrConfig;
  breach: BreachConfig;
  dpia: DpiaConfig;
  overrides: ComplianceOverride[];
}

// ── saf türetme yardımcıları ────────────────────────────────────────────────────

// ŞEFFAFLIK BOŞLUKLARI: profil zorunlu kıldığı halde tenant yapılandırmamış bildirimler (BRD §14.2). Anahtar
// listesi: "ai_disclosure" ve/veya "recording_notice" → UI danger uyarısı.
export function disclosureGaps(t: TransparencyConfig): string[] {
  const out: string[] = [];
  if (t.aiDisclosureRequired && !t.aiDisclosureConfigured) out.push("ai_disclosure");
  if (t.recordingNoticeRequired && !t.recordingNoticeConfigured) out.push("recording_notice");
  return out;
}

// KAYIT HİJYEN BOŞLUKLARI: kayıt AÇIK olduğu halde eksik koruma. Anahtar listesi: "pii_redaction"
// (FR-REC-004) ve/veya "card_otp" (FR-REC-005) → UI warning uyarısı. Kayıt kapalıysa (off) boş.
export function recordingGaps(r: RecordingPolicyConfig): string[] {
  const out: string[] = [];
  if (r.channelMode === "off") return out;
  if (!r.piiRedaction) out.push("pii_redaction");
  if (!r.cardOtpMasking) out.push("card_otp");
  return out;
}

// RESIDENCY BOŞLUKLARI (NFR 10.7): in-region zorunlu ama provider pinning kapalı ("provider_pinning"); VEYA
// sınır-ötesi (in-region zorunlu DEĞİL) ama transfer mekanizması yok ("cross_border"). UI danger uyarısı.
export function residencyGaps(res: ResidencyConfig): string[] {
  const out: string[] = [];
  if (res.inRegionStorageRequired && !res.providerRegionPinning) out.push("provider_pinning");
  if (!res.inRegionStorageRequired && res.crossBorderMechanism === "none") out.push("cross_border");
  return out;
}

// OUTBOUND/İYS-DNC BOŞLUKLARI (FR-OUT-003/006): rıza gerektiren modelde (opt_in/soft_opt_in) izin kaydı yok
// ("consent_registry") ve/veya DNC kaynağı tanımsız ("dnc"). UI warning uyarısı. opt_out modelinde boş.
export function outboundGaps(o: OutboundConfig): string[] {
  const out: string[] = [];
  const needsConsent = o.consentModel === "opt_in" || o.consentModel === "soft_opt_in";
  if (!needsConsent) return out;
  if (o.consentRegistry.trim() === "" || o.consentRegistry.toLowerCase() === "none") out.push("consent_registry");
  if (o.dncLists.length === 0) out.push("dnc");
  return out;
}

// MOST-RESTRICTIVE-WINS İHLALİ: tabanı GEVŞETEN override'lar (CLAUDE.md / DPIA §8 — override yalnız
// sıkılaştırır). id listesi → UI danger uyarısı (audit'li). tighten/equal izinli.
export function loosenOverrides(overrides: ComplianceOverride[]): string[] {
  return overrides.filter((o) => o.direction === "loosen").map((o) => o.id);
}

// SAKLAMA TUTARSIZLIĞI: pozitif-olmayan (≤0) saklama günleri (yanlış konfigürasyon). Alan adı listesi.
export function invalidRetention(r: RetentionConfig): string[] {
  const out: string[] = [];
  if (r.recordingDays <= 0) out.push("recording");
  if (r.transcriptDays <= 0) out.push("transcript");
  if (r.auditDays <= 0) out.push("audit");
  return out;
}

// DPIA AÇIK KAPISI: onboarding gate tamamlanmamış (required/in_progress) → UI uyarısı (DPIA §3).
export function dpiaPending(d: DpiaConfig): boolean {
  return d.status === "required" || d.status === "in_progress";
}

// Toplam açık uyarı sayısı (KPI): tüm boşluk + ihlal türlerinin toplamı + DPIA bekliyorsa +1.
export function openWarningCount(snap: ComplianceSnapshot): number {
  return (
    disclosureGaps(snap.transparency).length +
    recordingGaps(snap.recordingPolicy).length +
    residencyGaps(snap.residency).length +
    outboundGaps(snap.outbound).length +
    loosenOverrides(snap.overrides).length +
    invalidRetention(snap.retention).length +
    (dpiaPending(snap.dpia) ? 1 : 0)
  );
}

// ── ton (renk) eşlemeleri ─────────────────────────────────────────────────────────

const DPIA_STATUS_TONE: Record<DpiaStatus, StatusTone> = {
  not_required: "neutral",
  required: "danger",
  in_progress: "warning",
  completed: "success",
};
export function dpiaStatusTone(s: DpiaStatus): StatusTone {
  return DPIA_STATUS_TONE[s];
}

const OVERRIDE_DIRECTION_TONE: Record<OverrideDirection, StatusTone> = {
  tighten: "success",
  equal: "neutral",
  loosen: "danger",
};
export function overrideDirectionTone(d: OverrideDirection): StatusTone {
  return OVERRIDE_DIRECTION_TONE[d];
}

const CROSS_BORDER_TONE: Record<CrossBorderMechanism, StatusTone> = {
  scc: "success",
  adequacy: "success",
  explicit_consent: "warning",
  none: "neutral",
};
export function crossBorderTone(m: CrossBorderMechanism): StatusTone {
  return CROSS_BORDER_TONE[m];
}

const CONSENT_MODEL_TONE: Record<ConsentModel, StatusTone> = {
  opt_in: "success",
  soft_opt_in: "info",
  opt_out: "warning",
};
export function consentModelTone(m: ConsentModel): StatusTone {
  return CONSENT_MODEL_TONE[m];
}

const CHANNEL_MODE_TONE: Record<ChannelMode, StatusTone> = {
  off: "neutral",
  single: "info",
  dual: "info",
};
export function channelModeTone(m: ChannelMode): StatusTone {
  return CHANNEL_MODE_TONE[m];
}

// Zorunlu+yapılandırılmış => success; zorunlu ama eksik => danger; zorunlu değil => neutral.
export function requiredFlagTone(required: boolean, satisfied: boolean): StatusTone {
  if (!required) return "neutral";
  return satisfied ? "success" : "danger";
}

// Bayrak (true=success/false=danger) — koruma bayrakları için (redaction/masking/pinning).
export function guardFlagTone(on: boolean): StatusTone {
  return on ? "success" : "danger";
}

// ── HİJYEN + GÜVENLİK koruması ─────────────────────────────────────────────────────
// Yapı içinde son-müşteri iş içeriği/PII'yi VEYA sır/credential çağrıştıran ALAN ADI bulunursa hata fırlatır.
// Bu, T-06'nın yalnız tenant'ın KENDİ politika/profil konfigürasyonunu (PII/sır DEĞİL) göstermesini
// çalışma-anında garanti eder (BRD §17.7 + NFR 10.6). NOT: profil alan adları politika parametresidir
// (`recordingPolicy`/`piiRedaction` exact-match "recording"/"pii" DEĞİL → izinli).
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
  "cardpan",
  "cvv",
  "ssn",
  "pii",
];

export const FORBIDDEN_SECRET_KEYS: readonly string[] = [
  "secret",
  "apikey",
  "apisecret",
  "signingsecret",
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
        throw new Error(`T-06 HİJYEN ihlali: yasak PII/iş-içeriği alanı "${path}.${k}" (BRD §17.7)`);
      }
      if (FORBIDDEN_SECRET_KEYS.includes(lower)) {
        throw new Error(`T-06 GÜVENLİK ihlali: sır/credential alanı "${path}.${k}" panele konmaz (NFR 10.6)`);
      }
      assertNoPii((node as Record<string, unknown>)[k], `${path}.${k}`);
    }
  }
}

// ── veri SEAM (yer tutucu) ───────────────────────────────────────────────────────
// Deterministik yer tutucu: tek-tenant compliance/retention profili (KENDİ ülke profili + sektörel overlay +
// kayıt/residency/saklama/consent politikası — son-müşteri PII/iş-içeriği DEĞİL, SIR DEĞİL). Gerçek
// implementasyon (F2 §14.1) Compliance Profile çözümleyici (SAD §19) + Consent Engine + Retention motorundan
// tenant-scope (RLS) beslenir. Değerler MÜHENDİSLİK VARSAYILANIDIR; counsel doğrulamasına tabi (DPIA §12).
const PLACEHOLDER_SNAPSHOT: ComplianceSnapshot = {
  generatedAt: "2026-06-18T09:00:00.000Z",
  tenantRef: "TEN-2048",
  tenantName: "Kuzey Sigorta A.Ş.",
  profile: {
    countryProfile: "PROFILE-TR",
    regime: "KVKK",
    sectorOverlays: ["FCA-benzeri-finans"],
    lawfulBasisDefault: "explicit_consent",
    dpaRequired: true,
  },
  recordingPolicy: {
    channelMode: "dual",
    recordingConsentModel: "notice",
    piiRedaction: true,
    cardOtpMasking: true,
  },
  transparency: {
    aiDisclosureRequired: true,
    aiDisclosureConfigured: true,
    recordingNoticeRequired: true,
    recordingNoticeConfigured: true,
    noDeceptiveImpersonation: true,
  },
  residency: {
    homeRegion: "EU",
    inRegionStorageRequired: true,
    providerRegionPinning: true,
    crossBorderMechanism: "scc",
  },
  retention: {
    recordingDays: 180,
    transcriptDays: 365,
    auditDays: 730,
    legalHoldSupported: true,
    legalHoldActive: 2,
  },
  outbound: {
    consentModel: "opt_in",
    consentRegistry: "IYS",
    dncLists: ["IYS_ret"],
    callingHoursLocal: "09:00–20:00",
    cliPresentationRequired: true,
    b2bExemption: false,
  },
  dsr: {
    accessSlaDays: 30,
    erasureSlaDays: 30,
    rectificationSupported: true,
    portabilitySupported: true,
  },
  breach: {
    authority: "KVKK",
    authorityDeadlineHours: 72,
    dataSubjectNotice: "high_risk",
  },
  dpia: {
    status: "completed",
    triggers: ["DPIA-T-04", "DPIA-T-05"],
  },
  overrides: [
    { id: "OV-1", key: "cp.retention.recording_days", baseline: "365", value: "180", direction: "tighten" },
    { id: "OV-2", key: "cp.outbound.calling_hours_local", baseline: "08:00–21:00", value: "09:00–20:00", direction: "tighten" },
  ],
};

export async function getCompliance(): Promise<ComplianceSnapshot> {
  const snap = PLACEHOLDER_SNAPSHOT;
  assertNoPii(snap); // HİJYEN + GÜVENLİK: yapısal son-müşteri PII / sır yok (BRD §17.7 / NFR 10.6)
  return snap;
}
