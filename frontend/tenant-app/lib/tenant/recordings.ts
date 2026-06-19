// WBS 13.4.11 — A-11 "Çağrı Kayıtları" veri katmanı (seam) + SAF türetme yardımcıları
// (L2 — Operasyon / Uygulama Paneli).
//
// ÇEKİRDEK İLKELER:
//  - İÇERİK (BRD §17.5 A-11 "Çağrı Kayıtları" — "Kayıt arama/filtreleme"): bir tenant'ın çağrı kayıtlarının
//    (CDR — DB §19 `call`) ARANABİLİR/FİLTRELENEBİLİR envanteri. Görünüm yalnız ÇAĞRI META taşır — yön
//    (inbound/outbound) + agent + sonuç/outcome (FR-ANA-002/003) + süre + KAYIT DURUMU bayrağı (recorded/
//    disabled/none — FR-REC-001/002/003) + TRANSKRİPT redaction DURUMU (redacted/pending/not_required/none —
//    FR-REC-004) + saklama/retention bayrağı (FR-REC-006/010) + yasal-tutma bayrağı (FR-REC-007) + erişim-audit
//    bayrağı (FR-REC-009) + kanal sayısı (FR-REC-003) + sahiplik bayrağı (human_agent kapsamı). Ham ses kaydı
//    BYTE'ı / transkript METNİ / ham numara (e164) / müşteri PII / nesne-depo URI'si / çağrı özeti GÖMÜLMEZ —
//    yalnız DURUM/BAYRAK + agregat SAYI. Çağrıyı DİNLEME / transkripti GÖRME derin aksiyondur (A-12 + API §6 +
//    FR-REC-008/009 yetki + audit).
//  - KAYIT POLİTİKASI (FR-REC-001/002): kayıt tenant/ülke/use-case bazında belirlenir + tamamen kapatılabilir.
//    `recordingState` = recorded (kayıt var) | disabled (kayıt KAPALI — FR-REC-002) | none (kayıt yok/üretilmedi).
//  - TEK/ÇİFT KANAL (FR-REC-003): `channels` = 1 | 2 (kayıtsızda 0). Çift kanal ayrı izlemeyi destekler.
//  - TRANSKRİPT REDACTION (FR-REC-004): `transcriptState` = redacted (PII redaction tamam) | pending (redaction
//    BEKLEMEDE — erişimden önce tamamlanmalı) | not_required | none (transkript yok). INVARIANT: pending
//    transkriptin erişime hazır sayılması bir dikkat kalemidir (redactionPendingCalls — FR-REC-004).
//  - SAKLAMA + YASAL TUTMA (FR-REC-006/007/010): `retentionImminent` = saklama süresi dolmak üzere → geri
//    döndürülemez silinecek (FR-REC-006/010). `legalHold` = yasal tutma → silmeye karşı korunur (FR-REC-007).
//    INVARIANT: yasal tutma retention silmesini ASKIYA ALIR — legalHold && retentionImminent bir ÇELİŞKİDİR
//    (legalHoldConflictCalls — FR-REC-007 ihlali, danger). retentionImminent yalnız !legalHold kayıtlarda sayılır.
//  - ERİŞİM YETKİSİ + AUDIT (FR-REC-008/009): yetkili kullanıcı dinler/görür (FR-REC-008 → A-12); HER kayıt/
//    transkript erişimi audit edilir (FR-REC-009). `accessAudited` = bu kaydın erişim-audit yolu işaretli mi.
//    INVARIANT: accessAudited=false bir GÜVENLİK açığıdır (unauditedCalls — FR-REC-009 ihlali, danger; auditsiz
//    erişim olmamalı). Erişim audit'inin tam motoru WBS 11.6 + DB §27 WORM'dadır; bu bayrak yalnız DURUMU yansıtır.
//  - TENANT-SCOPE (FR-TEN-002): A-11 yalnız oturum açan tenant'ın KENDİ çağrı kayıtları. Scope çalışma-anında
//    middleware (13.1.2) + RLS (DB §6.2) ile sabitlenir; UI yalnız görsel kapı.
//  - SAHİPLİK (BRD §17.6 — human_agent "Görüntüle (kendi)"): `own` = bu çağrı oturum açan kullanıcıya aktarılmış
//    mı (human_agent yalnız KENDİ çağrılarını görür — BRD §17.7). Nihai scope backend + RLS'de; UI görsel kapı.
//  - HİJYEN (BRD §17.7 + §17.6): yalnız ÇAĞRI META. Ham ses kaydı BYTE'ı / transkript METNİ / ham numara (e164) /
//    müşteri PII / kart-OTP / nesne-depo URI'si / çağrı özeti GÖMÜLMEZ. PII redaction + kart/OTP gizleme panel
//    görüntülemelerinde de uygulanır (FR-REC-004/005). NOT: agent `name` tenant'ın KENDİ yapılandırmasıdır
//    (KURUMSAL ad — son-müşteri PII değil); callRef bir VEKİL kimliktir (telefon numarası DEĞİL).
//  - GÜVENLİK (NFR 10.6): sır/credential + nesne-depo URI'si/imzalı-URL görünüme KONMAZ.
//  - VENDOR-NEUTRAL (ADR-002): veri kaynağı bir SEAM'dir; gerçek implementasyon (F1 §14.1) CDR/Call Store
//    (DB §19 `call`/`recording`/`transcript`) tenant-scope (RLS) beslenir. Belirli kayıt/depo sağlayıcısı bağlanmaz.
//  - SAF/DETERMİNİSTİK: türetme yardımcıları Date.now/rastgelelik içermez → birim-test edilebilir + Python aynası
//    (screens/a11-recordings/a11_recordings_probe.py).
//  - İŞ MANTIĞI/AUTHZ YOK (SAD §14.4.1): dinleme/görme/export/legal-hold kararı YOK; nihai yetki + işlem +
//    erişim-audit backend'de (11.6/API §6) + RLS. Panel yalnız çözümlenmiş kayıt envanterini gösterir.
//  - RBAC (BRD §17.6 — L2 A-11 satırı): operations_manager=Yönet · conversation_designer=Görüntüle ·
//    qa_analyst=Görüntüle · human_agent=Görüntüle (kendi). Permission-key: calls:read.

// Çağrı yönü (DB §19 call.direction — inbound/outbound).
export type CallDirection = "inbound" | "outbound";
// Çağrı sonucu/outcome (FR-ANA-002/003 containment/transfer + FR-OUT-008 voicemail).
export type CallOutcome = "contained" | "transferred" | "abandoned" | "voicemail" | "failed";
// Kayıt durumu (FR-REC-001/002/003 — recorded | disabled[kapalı] | none[yok]).
export type RecordingState = "recorded" | "disabled" | "none";
// Transkript redaction durumu (FR-REC-004 — DB §21 transcript.redaction_state + none[transkript yok]).
export type TranscriptState = "redacted" | "pending" | "not_required" | "none";

export type StatusTone = "success" | "warning" | "danger" | "neutral" | "info";

// Bir çağrı kaydı (A-11 çekirdeği — CDR satırı; yalnız ÇAĞRI META, ham içerik/PII/URI DEĞİL).
export interface CallRecord {
  callRef: string; // çağrı VEKİL kimliği (CDR; telefon numarası DEĞİL)
  direction: CallDirection; // inbound | outbound (DB §19)
  agentRef: string; // çağrıyı karşılayan agent kimliği
  agentName: string; // agent adı (tenant config; son-müşteri PII değil)
  startedAt: string; // ISO-8601 başlangıç (sabit yer tutucu — SSR-stabil; Date.now YOK)
  durationSec: number; // çağrı süresi (saniye)
  outcome: CallOutcome; // çözüm/outcome (FR-ANA-002/003 + FR-OUT-008)
  recordingState: RecordingState; // FR-REC-001/002/003 (yalnız DURUM; ham ses gömülmez)
  channels: 0 | 1 | 2; // FR-REC-003 (tek/çift kanal; kayıtsızda 0)
  transcriptState: TranscriptState; // FR-REC-004 (yalnız DURUM; transkript metni gömülmez)
  retentionImminent: boolean; // FR-REC-006/010 (saklama süresi dolmak üzere → geri döndürülemez silinecek)
  legalHold: boolean; // FR-REC-007 (yasal tutma → silmeye karşı korunur)
  accessAudited: boolean; // FR-REC-009 (erişim-audit yolu işaretli mi — INVARIANT: true olmalı)
  own: boolean; // BRD §17.6/§17.7 (human_agent kapsamı — bu çağrı kullanıcıya aktarıldı mı)
}

export interface CallRecordsView {
  generatedAt: string; // ISO-8601 (sabit yer tutucu — SSR-stabil, Date.now YOK)
  tenantRef: string; // tenant'ın KENDİ kimliği (L2'de izinli)
  tenantName: string; // tenant org adı (izinli; son-müşteri verisi DEĞİL)
  calls: CallRecord[]; // tenant çağrı kayıtları (tenant-scope FR-TEN-002)
}

// Görüntüleme sıraları.
export const DIRECTION_ORDER: CallDirection[] = ["inbound", "outbound"];
export const OUTCOME_ORDER: CallOutcome[] = ["contained", "transferred", "abandoned", "voicemail", "failed"];
export const RECORDING_ORDER: RecordingState[] = ["recorded", "disabled", "none"];
export const TRANSCRIPT_ORDER: TranscriptState[] = ["redacted", "pending", "not_required", "none"];

// ── saf türetme yardımcıları ────────────────────────────────────────────────────

// Çağrı kayıtlarını başlangıç zamanına göre AZALAN (en yeni önce), eşitlikte callRef ASC sırala (deterministik).
export function sortedCalls(view: CallRecordsView): CallRecord[] {
  return [...view.calls].sort((a, b) => b.startedAt.localeCompare(a.startedAt) || a.callRef.localeCompare(b.callRef));
}

// Yön başına çağrı sayısı (tüm yönler 0'dan başlatılır — DB §19).
export function countByDirection(calls: CallRecord[]): Record<CallDirection, number> {
  const acc = {} as Record<CallDirection, number>;
  for (const d of DIRECTION_ORDER) acc[d] = 0;
  for (const c of calls) acc[c.direction] += 1;
  return acc;
}

// Sonuç/outcome başına çağrı sayısı (tüm sonuçlar 0'dan başlatılır — FR-ANA-002/003).
export function countByOutcome(calls: CallRecord[]): Record<CallOutcome, number> {
  const acc = {} as Record<CallOutcome, number>;
  for (const o of OUTCOME_ORDER) acc[o] = 0;
  for (const c of calls) acc[c.outcome] += 1;
  return acc;
}

// Kayıt durumu başına çağrı sayısı (FR-REC-001/002/003).
export function countByRecordingState(calls: CallRecord[]): Record<RecordingState, number> {
  const acc = {} as Record<RecordingState, number>;
  for (const r of RECORDING_ORDER) acc[r] = 0;
  for (const c of calls) acc[c.recordingState] += 1;
  return acc;
}

// Kayıtlı çağrılar (recordingState === "recorded" — FR-REC-001).
export function recordedCalls(calls: CallRecord[]): CallRecord[] {
  return calls.filter((c) => c.recordingState === "recorded");
}

// Ses kaydı KAPALI çağrılar (recordingState === "disabled" — FR-REC-002 ses tamamen kapatılabilir).
export function recordingDisabledCalls(calls: CallRecord[]): CallRecord[] {
  return calls.filter((c) => c.recordingState === "disabled");
}

// Çift kanallı kayıtlar (channels === 2 — FR-REC-003).
export function dualChannelCalls(calls: CallRecord[]): CallRecord[] {
  return calls.filter((c) => c.channels === 2);
}

// Transkripti olan çağrılar (transcriptState !== "none").
export function transcriptCalls(calls: CallRecord[]): CallRecord[] {
  return calls.filter((c) => c.transcriptState !== "none");
}

// PII REDACTION BEKLEYEN transkriptli çağrılar (transcriptState === "pending" — FR-REC-004 dikkat kalemi).
export function redactionPendingCalls(calls: CallRecord[]): CallRecord[] {
  return calls.filter((c) => c.transcriptState === "pending");
}

// Redaction tamamlanmış transkriptli çağrılar (transcriptState === "redacted" — FR-REC-004).
export function redactedCalls(calls: CallRecord[]): CallRecord[] {
  return calls.filter((c) => c.transcriptState === "redacted");
}

// Yasal tutma altındaki kayıtlar (legalHold === true — FR-REC-007).
export function legalHoldCalls(calls: CallRecord[]): CallRecord[] {
  return calls.filter((c) => c.legalHold);
}

// SAKLAMA SÜRESİ DOLMAK ÜZERE kayıtlar (retentionImminent && !legalHold — FR-REC-006/010).
// Yasal tutma retention silmesini askıya aldığından yasal-tutma altındaki kayıt "silinecek" SAYILMAZ.
export function retentionImminentCalls(calls: CallRecord[]): CallRecord[] {
  return calls.filter((c) => c.retentionImminent && !c.legalHold);
}

// ÇELİŞKİ (FR-REC-007 ihlali — danger): yasal tutma altında AMA retention silmesi için işaretli.
// Yasal tutma retention'ı ASKIYA ALMALIDIR; ikisi birlikte bir config çelişkisidir.
export function legalHoldConflictCalls(calls: CallRecord[]): CallRecord[] {
  return calls.filter((c) => c.legalHold && c.retentionImminent);
}

// AUDITSIZ ERİŞİM (FR-REC-009 ihlali — danger): erişim-audit yolu işaretsiz. Auditsiz erişim olmamalı.
export function unauditedCalls(calls: CallRecord[]): CallRecord[] {
  return calls.filter((c) => !c.accessAudited);
}

// Oturum açan kullanıcıya ait çağrılar (own === true — human_agent kapsamı; BRD §17.6/§17.7).
export function ownCalls(calls: CallRecord[]): CallRecord[] {
  return calls.filter((c) => c.own);
}

// Açık dikkat sayısı: redaction-bekleyen transkript + silinmek-üzere kayıt + yasal-tutma çelişkisi + auditsiz erişim.
export function openAttentionCount(view: CallRecordsView): number {
  return (
    redactionPendingCalls(view.calls).length +
    retentionImminentCalls(view.calls).length +
    legalHoldConflictCalls(view.calls).length +
    unauditedCalls(view.calls).length
  );
}

// ── ton (renk) eşlemeleri ─────────────────────────────────────────────────────────

const DIRECTION_TONE: Record<CallDirection, StatusTone> = {
  inbound: "neutral",
  outbound: "info",
};
export function directionTone(d: CallDirection): StatusTone {
  return DIRECTION_TONE[d];
}

const OUTCOME_TONE: Record<CallOutcome, StatusTone> = {
  contained: "success",
  transferred: "info",
  abandoned: "warning",
  voicemail: "neutral",
  failed: "danger",
};
export function outcomeTone(o: CallOutcome): StatusTone {
  return OUTCOME_TONE[o];
}

const RECORDING_TONE: Record<RecordingState, StatusTone> = {
  recorded: "success",
  disabled: "neutral",
  none: "neutral",
};
export function recordingTone(r: RecordingState): StatusTone {
  return RECORDING_TONE[r];
}

const TRANSCRIPT_TONE: Record<TranscriptState, StatusTone> = {
  redacted: "success",
  pending: "warning", // redaction beklemede → FR-REC-004 dikkat
  not_required: "neutral",
  none: "neutral",
};
export function transcriptTone(t: TranscriptState): StatusTone {
  return TRANSCRIPT_TONE[t];
}

// ── HİJYEN + GÜVENLİK koruması ─────────────────────────────────────────────────────
// Yapı içinde son-müşteri ham iş içeriği/PII'yi VEYA sır/credential/nesne-depo URI'si çağrıştıran ALAN ADI
// bulunursa hata fırlatır. Bu, A-11'in yalnız ÇAĞRI META veriyi (yön/agent/sonuç/süre/kayıt-transkript-saklama-
// yasal-tutma-erişim BAYRAKLARI/kanal/sahiplik + agent adı — tenant'ın KENDİ yapılandırması) — ham ses kaydı/
// transkript metni/ham numara/müşteri PII/kart-OTP/nesne-depo URI'si/çağrı özeti DEĞİL — göstermesini garanti
// eder (BRD §17.7 + §17.6 + FR-REC-004/005 + NFR 10.6).
export const FORBIDDEN_PII_KEYS: readonly string[] = [
  "transcript",
  "transcripttext",
  "redactedtext",
  "recording", // ham ses kaydı (yalnız recordingState BAYRAĞI izinli; bu tam-eşleşme anahtar yasaktır)
  "recordingbytes",
  "audio",
  "audiobytes",
  "segment",
  "segments",
  "summary", // çağrı özeti (DB §21 transcript.summary) — gömülmez
  "text",
  "e164",
  "frome164",
  "toe164",
  "fromnumber",
  "tonumber",
  "msisdn",
  "phonenumber",
  "callerid",
  "callernumber",
  "calleenumber",
  "customer",
  "customername",
  "contact",
  "cardpan",
  "pan",
  "cvv",
  "otp",
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
  "credential",
  "password",
  "privatekey",
  "kmskey",
  "storageuri", // nesne-depo pointer (DB §21/§22 storage_uri) — gömülmez
  "storageurl",
  "objecturi",
  "objectkey",
  "signedurl",
  "downloadurl",
  "url",
  "baseurl",
  "uri",
  "bucket",
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
        throw new Error(`A-11 HİJYEN ihlali: yasak PII/iş-içeriği alanı "${path}.${k}" (BRD §17.7 / FR-REC-004/005)`);
      }
      if (FORBIDDEN_SECRET_KEYS.includes(lower)) {
        throw new Error(`A-11 GÜVENLİK ihlali: sır/credential/nesne-depo URI alanı "${path}.${k}" panele konmaz (NFR 10.6)`);
      }
      assertNoPii((node as Record<string, unknown>)[k], `${path}.${k}`);
    }
  }
}

// ── veri SEAM (yer tutucu) ───────────────────────────────────────────────────────
// Deterministik yer tutucu: tek-tenant çağrı kayıtları (ÇAĞRI META yalnız — ham ses/transkript/numara/URI DEĞİL).
// Gerçek implementasyon (F1 §14.1) CDR/Call Store (DB §19 call + §21 transcript + §22 recording) tenant-scope
// (RLS) beslenir. Bu örnek: 6 çağrı (inbound/outbound karışık; biri kayıt-kapalı [FR-REC-002]; biri redaction-
// bekleyen transkript [FR-REC-004]; biri saklama-süresi-dolan [FR-REC-006/010]; biri yasal-tutma [FR-REC-007]).
const PLACEHOLDER_VIEW: CallRecordsView = {
  generatedAt: "2026-06-18T09:00:00.000Z",
  tenantRef: "TEN-2048",
  tenantName: "Kuzey Sigorta A.Ş.",
  calls: [
    { callRef: "CALL-1006", direction: "inbound", agentRef: "AGT-117", agentName: "Sigorta Asistanı", startedAt: "2026-06-18T08:55:00.000Z", durationSec: 214, outcome: "contained", recordingState: "recorded", channels: 2, transcriptState: "redacted", retentionImminent: false, legalHold: false, accessAudited: true, own: false },
    { callRef: "CALL-1005", direction: "inbound", agentRef: "AGT-117", agentName: "Sigorta Asistanı", startedAt: "2026-06-18T08:40:00.000Z", durationSec: 98, outcome: "transferred", recordingState: "recorded", channels: 2, transcriptState: "pending", retentionImminent: false, legalHold: false, accessAudited: true, own: true }, // redaction bekliyor → dikkat (FR-REC-004)
    { callRef: "CALL-1004", direction: "outbound", agentRef: "AGT-204", agentName: "Tahsilat Botu", startedAt: "2026-06-18T08:25:00.000Z", durationSec: 0, outcome: "voicemail", recordingState: "none", channels: 0, transcriptState: "none", retentionImminent: false, legalHold: false, accessAudited: true, own: false },
    { callRef: "CALL-1003", direction: "outbound", agentRef: "AGT-204", agentName: "Tahsilat Botu", startedAt: "2026-06-18T08:10:00.000Z", durationSec: 152, outcome: "contained", recordingState: "disabled", channels: 0, transcriptState: "not_required", retentionImminent: false, legalHold: false, accessAudited: true, own: false }, // kayıt kapalı (FR-REC-002)
    { callRef: "CALL-1002", direction: "inbound", agentRef: "AGT-309", agentName: "Bilgi Botu", startedAt: "2026-06-18T07:50:00.000Z", durationSec: 67, outcome: "abandoned", recordingState: "recorded", channels: 1, transcriptState: "redacted", retentionImminent: true, legalHold: false, accessAudited: true, own: false }, // saklama süresi doluyor (FR-REC-006/010)
    { callRef: "CALL-1001", direction: "inbound", agentRef: "AGT-117", agentName: "Sigorta Asistanı", startedAt: "2026-06-18T07:30:00.000Z", durationSec: 333, outcome: "transferred", recordingState: "recorded", channels: 2, transcriptState: "redacted", retentionImminent: false, legalHold: true, accessAudited: true, own: false }, // yasal tutma (FR-REC-007)
  ],
};

export async function getCallRecordsView(): Promise<CallRecordsView> {
  const view = PLACEHOLDER_VIEW;
  assertNoPii(view); // HİJYEN + GÜVENLİK: yapısal son-müşteri PII / sır / nesne-depo URI yok (BRD §17.7 / FR-REC-004/005 / NFR 10.6)
  return view;
}
