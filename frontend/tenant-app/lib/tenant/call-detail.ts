// WBS 13.4.12 — A-12 "Çağrı Detayı / Transkript & Timeline" veri katmanı (seam) + SAF türetme yardımcıları
// (L2 — Operasyon / Uygulama Paneli).
//
// ÇEKİRDEK İLKELER:
//  - İÇERİK (BRD §17.5 A-12 "Çağrı Detayı / Transkript & Timeline" — "Çağrı zaman çizelgesi, transkript,
//    olaylar"): TEK bir çağrının DETAYI. A-11 (Çağrı Kayıtları) arama/filtreleme + META iken, A-12 seçilen
//    çağrının (a) ÇAĞRI KÜNYESİ (yön/agent/sonuç/süre/kayıt-transkript-saklama-erişim DURUMU — A-11 ile aynı
//    META), (b) OLAY ZAMAN ÇİZELGESİ (DB §23 call_event — BRD §15 zaman damgası taksonomisi + SAD §6.1 turn
//    state machine: call_connected/greeting/recording/kb_lookup/tool_invoked/barge_in/transfer/voicemail/
//    call_ended — yalnız YAPISAL olay; ham içerik DEĞİL) ve (c) TRANSKRİPT (DB §21 transcript_segment —
//    speaker + offset + REDACTION UYGULANMIŞ metin; FR-REC-004/005) görünümünü sunar.
//  - TRANSKRİPT = DERİN AKSİYON (FR-REC-008/009): A-12 transkript İÇERİĞİNİ gösterir AMA yalnız (1) redaction
//    TAMAMLANMIŞ (transcriptState === "redacted" — FR-REC-004) ve (2) erişim AUDIT'li (accessAudited — FR-REC-009)
//    olduğunda. transcriptState === "pending" ise içerik REDACTION BEKLER (gizlenir); accessAudited === false ise
//    erişim ENGELLENİR (auditsiz erişim olmaz). DB §21 notu: transcript_segment.text view/uygulama katmanında
//    MASKELENMİŞ sunulur — A-12 metni ZATEN redaction'lı/maskeli taşır (ham/maskesiz metin YOK).
//  - HİJYEN — İKİ KATMAN (BRD §17.7 + FR-REC-004/005 + NFR 10.6):
//      (1) YAPISAL anahtar guard (assertNoForbiddenKeys): ham kimlik/iş-içeriği (e164/msisdn/telefon/callerId/
//          müşteri/contact/email/dob/kart-PAN/cvv/otp/ssn/iban/ham-transkript-blob/ham-ses) + sır/credential +
//          nesne-depo URI (storageUri/signedUrl/downloadUrl/url/kmsKey/...) alan ADI taşınamaz.
//      (2) İÇERİK redaction guard (assertRedactionClean): TÜM string değerleri (özellikle transkript `text`)
//          ham PII DESENİ (≥7 ardışık rakam → telefon/kart/poliçe/hesap; e-posta; +rakam; kart-bloğu) için
//          taranır. Maskeli içerik yalnız MASK_TOKEN ("[•••]") taşır. Bu invariant FR-REC-004/005'i TEST EDİLEBİLİR
//          kılar (redaction panel görüntülemelerinde de uygulanır — BRD §17.7 son madde).
//  - KAYIT = DERİN AKSİYON: A-12 yalnız kayıt DURUMUNU + kanal sayısını + (görsel) oynatma kapısını gösterir.
//    Ham ses BYTE'ı / nesne-depo URI'si / imzalı-URL panele KONMAZ (NFR 10.6); dinleme yetkili kullanıcı için
//    backend'de audit'li erişimle (API §6 + WBS 11.6) sağlanır.
//  - TENANT-SCOPE (FR-TEN-002): A-12 yalnız oturum açan tenant'ın KENDİ çağrısı. Scope çalışma-anında middleware
//    (13.1.2) + RLS (DB §6.2) ile sabitlenir; UI yalnız görsel kapı.
//  - SAHİPLİK (BRD §17.6 — human_agent "Görüntüle (kendi)"): `own` = bu çağrı oturum açan kullanıcıya aktarıldı mı.
//  - DÜŞÜK GÜVEN (BRD §15 word confidence — DB §21 transcript_segment.confidence): bir QA sinyali (qa_analyst=Yönet);
//    güveni LOW_CONFIDENCE_THRESHOLD altındaki turlar işaretlenir (gözden geçirme adayı). Güvenlik açığı DEĞİL.
//  - VENDOR-NEUTRAL (ADR-002): veri kaynağı bir SEAM'dir; gerçek implementasyon (F1 §14.1) Call Store + Transcript
//    + Event (DB §19/§21/§23) tenant-scope (RLS) + redaction motoru (WBS 11.3/11.4) çıktısıyla beslenir.
//  - SAF/DETERMİNİSTİK: türetmeler Date.now/rastgelelik içermez → birim-test + Python aynası
//    (screens/a12-call-detail/a12_call_detail_probe.py).
//  - İŞ MANTIĞI/AUTHZ YOK (SAD §14.4.1): dinleme/görme/redaction/erişim-audit YAZIMI YOK; nihai yetki + işlem +
//    erişim-audit backend'de (11.6/API §6) + RLS. Panel yalnız çözümlenmiş detayı (redaction'lı) gösterir.
//  - RBAC (BRD §17.6 — L2 A-12 satırı): operations_manager=Yönet · conversation_designer=Görüntüle ·
//    qa_analyst=Yönet · human_agent=Görüntüle (kendi). Permission-key: calls:read.

// Çağrı yönü (DB §19 call.direction).
export type CallDirection = "inbound" | "outbound";
// Çağrı sonucu/outcome (FR-ANA-002/003 + FR-OUT-008 voicemail).
export type CallOutcome = "contained" | "transferred" | "abandoned" | "voicemail" | "failed";
// Kayıt durumu (FR-REC-001/002/003 — recorded | disabled[kapalı] | none[yok]).
export type RecordingState = "recorded" | "disabled" | "none";
// Transkript redaction durumu (FR-REC-004 — DB §21 transcript.redaction_state + none[transkript yok]).
export type TranscriptState = "redacted" | "pending" | "not_required" | "none";
// Konuşmacı (DB §21 transcript_segment.speaker).
export type Speaker = "caller" | "agent" | "human";
// Olay tipi — YAPISAL çağrı olayı (DB §23 call_event.event_type; BRD §15 zaman damgası taksonomisi + SAD §6.1).
export type TimelineEventType =
  | "call_connected" // çağrı bağlandı (SAD §6.1 LISTEN)
  | "greeting" // AI açıklama karşılaması (BRD §14.2 disclosure)
  | "recording_started" // kayıt başladı (FR-REC-001)
  | "kb_lookup" // RAG retrieval (FR-KB)
  | "tool_invoked" // tool/API çağrısı (FR-TOOL — ACT)
  | "barge_in" // barge-in: SPEAK→CAPTURE (ADR-005, SAD §6.1)
  | "transfer_initiated" // insan aktarımı başladı (FR-HND)
  | "transfer_completed" // aktarım tamamlandı (FR-HND)
  | "voicemail" // telesekreter bırakıldı (FR-OUT-008)
  | "recording_stopped" // kayıt durdu (FR-REC)
  | "call_ended"; // çağrı sonu

export type StatusTone = "success" | "warning" | "danger" | "neutral" | "info";

// Güven eşiği (DB §21 confidence; bunun altı QA gözden-geçirme adayı — BRD §15).
export const LOW_CONFIDENCE_THRESHOLD = 0.75;
// Maskeleme jetonu (redaction sonrası gösterilen tek güvenli içerik — FR-REC-004/005).
export const MASK_TOKEN = "[•••]";

// Bir transkript turu (DB §21 transcript_segment; yalnız REDACTION UYGULANMIŞ metin).
export interface TranscriptTurn {
  turnRef: string; // tur VEKİL kimliği (seq vekili; PII DEĞİL)
  speaker: Speaker; // caller | agent | human (DB §21)
  offsetMs: number; // çağrı başlangıcından ofset (ms)
  text: string; // REDACTION UYGULANMIŞ metin — ham PII yok, yalnız MASK_TOKEN (FR-REC-004/005)
  redacted: boolean; // bu turda PII/kart/OTP maskelendi mi (FR-REC-005)
  confidence: number; // word confidence 0..1 (DB §21; BRD §15)
}

// Bir zaman çizelgesi olayı (DB §23 call_event; yalnız YAPISAL — ham içerik DEĞİL).
export interface TimelineEvent {
  eventRef: string; // olay VEKİL kimliği
  type: TimelineEventType; // yapısal olay tipi (DB §23 event_type)
  offsetMs: number; // çağrı başlangıcından ofset (ms)
  detail?: string; // İSTEĞE BAĞLI yapısal etiket (tool/queue adı — tenant config; PII DEĞİL)
}

// Tek çağrının detayı (A-12 çekirdeği — künye META + olaylar + transkript).
export interface CallDetail {
  callRef: string; // çağrı VEKİL kimliği (telefon numarası DEĞİL)
  direction: CallDirection;
  agentRef: string;
  agentName: string; // agent adı (tenant config; son-müşteri PII değil)
  startedAt: string; // ISO-8601 (sabit yer tutucu — SSR-stabil; Date.now YOK)
  durationSec: number;
  outcome: CallOutcome; // FR-ANA-002/003 + FR-OUT-008
  recordingState: RecordingState; // FR-REC-001/002/003 (yalnız DURUM; ham ses gömülmez)
  channels: 0 | 1 | 2; // FR-REC-003 (kayıtsızda 0)
  transcriptState: TranscriptState; // FR-REC-004 (içerik kapısı: yalnız "redacted" görüntülenir)
  retentionImminent: boolean; // FR-REC-006/010
  legalHold: boolean; // FR-REC-007 (retention'ı askıya alır)
  accessAudited: boolean; // FR-REC-009 (erişim-audit yolu işaretli mi — INVARIANT: true; false ise erişim engellenir)
  own: boolean; // BRD §17.6/§17.7 (human_agent kapsamı)
  events: TimelineEvent[]; // DB §23 (yapısal olaylar)
  turns: TranscriptTurn[]; // DB §21 (redaction'lı transkript turları)
}

export interface CallDetailView {
  generatedAt: string; // ISO-8601 (sabit yer tutucu — SSR-stabil, Date.now YOK)
  tenantRef: string; // tenant'ın KENDİ kimliği (L2'de izinli)
  tenantName: string; // tenant org adı (izinli; son-müşteri verisi DEĞİL)
  call: CallDetail; // seçilen çağrının detayı (tenant-scope FR-TEN-002)
}

// Görüntüleme sıraları.
export const DIRECTION_ORDER: CallDirection[] = ["inbound", "outbound"];
export const OUTCOME_ORDER: CallOutcome[] = ["contained", "transferred", "abandoned", "voicemail", "failed"];
export const RECORDING_ORDER: RecordingState[] = ["recorded", "disabled", "none"];
export const TRANSCRIPT_ORDER: TranscriptState[] = ["redacted", "pending", "not_required", "none"];
export const SPEAKER_ORDER: Speaker[] = ["caller", "agent", "human"];
export const EVENT_ORDER: TimelineEventType[] = [
  "call_connected",
  "greeting",
  "recording_started",
  "kb_lookup",
  "tool_invoked",
  "barge_in",
  "transfer_initiated",
  "transfer_completed",
  "voicemail",
  "recording_stopped",
  "call_ended",
];

// ── saf türetme yardımcıları ────────────────────────────────────────────────────

// Olayları ofsete göre ARTAN sırala (eşitlikte eventRef ASC — deterministik).
export function sortedEvents(call: CallDetail): TimelineEvent[] {
  return [...call.events].sort((a, b) => a.offsetMs - b.offsetMs || a.eventRef.localeCompare(b.eventRef));
}

// Transkript turlarını ofsete göre ARTAN sırala (eşitlikte turnRef ASC — deterministik).
export function sortedTurns(call: CallDetail): TranscriptTurn[] {
  return [...call.turns].sort((a, b) => a.offsetMs - b.offsetMs || a.turnRef.localeCompare(b.turnRef));
}

// Olay tipi başına sayı (tüm tipler 0'dan başlatılır — DB §23).
export function countByEventType(events: TimelineEvent[]): Record<TimelineEventType, number> {
  const acc = {} as Record<TimelineEventType, number>;
  for (const t of EVENT_ORDER) acc[t] = 0;
  for (const e of events) acc[e.type] += 1;
  return acc;
}

// Konuşmacı başına tur sayısı (tüm konuşmacılar 0'dan başlatılır — DB §21).
export function countBySpeaker(turns: TranscriptTurn[]): Record<Speaker, number> {
  const acc = {} as Record<Speaker, number>;
  for (const s of SPEAKER_ORDER) acc[s] = 0;
  for (const t of turns) acc[t.speaker] += 1;
  return acc;
}

export function callerTurns(turns: TranscriptTurn[]): TranscriptTurn[] {
  return turns.filter((t) => t.speaker === "caller");
}
export function agentTurns(turns: TranscriptTurn[]): TranscriptTurn[] {
  return turns.filter((t) => t.speaker === "agent");
}
export function humanTurns(turns: TranscriptTurn[]): TranscriptTurn[] {
  return turns.filter((t) => t.speaker === "human");
}

// Tool/API çağrısı olayları (FR-TOOL — ACT).
export function toolEvents(events: TimelineEvent[]): TimelineEvent[] {
  return events.filter((e) => e.type === "tool_invoked");
}
// RAG retrieval olayları (FR-KB).
export function kbEvents(events: TimelineEvent[]): TimelineEvent[] {
  return events.filter((e) => e.type === "kb_lookup");
}
// Barge-in olayları (ADR-005, SAD §6.1).
export function bargeInEvents(events: TimelineEvent[]): TimelineEvent[] {
  return events.filter((e) => e.type === "barge_in");
}
// Aktarım olayları (initiated || completed — FR-HND).
export function transferEvents(events: TimelineEvent[]): TimelineEvent[] {
  return events.filter((e) => e.type === "transfer_initiated" || e.type === "transfer_completed");
}

// PII/kart/OTP maskelenmiş turlar (FR-REC-005 — redaction uygulandı).
export function maskedTurns(turns: TranscriptTurn[]): TranscriptTurn[] {
  return turns.filter((t) => t.redacted);
}

// DÜŞÜK GÜVEN turları (confidence < eşik — QA gözden-geçirme adayı; BRD §15). Güvenlik açığı DEĞİL.
export function lowConfidenceTurns(turns: TranscriptTurn[], threshold = LOW_CONFIDENCE_THRESHOLD): TranscriptTurn[] {
  return turns.filter((t) => t.confidence < threshold);
}

// İçerik KAPISI (FR-REC-004/008/009): transkript yalnız redaction TAMAM + erişim AUDIT'li ise görüntülenir.
export function transcriptViewable(call: CallDetail): boolean {
  return call.transcriptState === "redacted" && call.accessAudited;
}
// Redaction BEKLEMEDE (FR-REC-004 — içerik gizlenir; erişimden önce tamamlanmalı).
export function redactionPending(call: CallDetail): boolean {
  return call.transcriptState === "pending";
}
// Transkript YOK (none) ya da GEREKLİ DEĞİL (not_required).
export function transcriptAbsent(call: CallDetail): boolean {
  return call.transcriptState === "none" || call.transcriptState === "not_required";
}
// ERİŞİM ENGELLİ (FR-REC-009 ihlali — danger): erişim-audit yolu işaretsiz; auditsiz erişim olmaz.
export function accessBlocked(call: CallDetail): boolean {
  return !call.accessAudited;
}
// KAYIT oynatılabilir mi (yalnız DURUM kapısı — recorded; ham ses/URI panele KONMAZ — NFR 10.6).
export function recordingPlayable(call: CallDetail): boolean {
  return call.recordingState === "recorded";
}

// ── ton (renk) eşlemeleri ─────────────────────────────────────────────────────────

const DIRECTION_TONE: Record<CallDirection, StatusTone> = { inbound: "neutral", outbound: "info" };
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

const RECORDING_TONE: Record<RecordingState, StatusTone> = { recorded: "success", disabled: "neutral", none: "neutral" };
export function recordingTone(r: RecordingState): StatusTone {
  return RECORDING_TONE[r];
}

const TRANSCRIPT_TONE: Record<TranscriptState, StatusTone> = {
  redacted: "success",
  pending: "warning", // redaction beklemede → FR-REC-004 içerik gizli
  not_required: "neutral",
  none: "neutral",
};
export function transcriptTone(s: TranscriptState): StatusTone {
  return TRANSCRIPT_TONE[s];
}

const SPEAKER_TONE: Record<Speaker, StatusTone> = { caller: "neutral", agent: "info", human: "success" };
export function speakerTone(s: Speaker): StatusTone {
  return SPEAKER_TONE[s];
}

const EVENT_TONE: Record<TimelineEventType, StatusTone> = {
  call_connected: "neutral",
  greeting: "info",
  recording_started: "neutral",
  kb_lookup: "info",
  tool_invoked: "info",
  barge_in: "warning",
  transfer_initiated: "warning",
  transfer_completed: "success",
  voicemail: "neutral",
  recording_stopped: "neutral",
  call_ended: "neutral",
};
export function eventTone(t: TimelineEventType): StatusTone {
  return EVENT_TONE[t];
}

// ── HİJYEN + GÜVENLİK koruması (İKİ KATMAN) ─────────────────────────────────────────
// Katman 1 — YAPISAL anahtar guard: ham kimlik/iş-içeriği + sır/credential + nesne-depo URI çağrıştıran ALAN ADI
// bulunursa hata fırlatır. NOT: A-12 transkript İÇERİĞİNİ (REDACTION UYGULANMIŞ `text`) gösterdiğinden `text`
// İZİNLİDİR — ama ham transkript blob'u (transcriptText/rawText) + ham ses + ham kimlik YASAKTIR.
export const FORBIDDEN_PII_KEYS: readonly string[] = [
  "transcripttext", // ham/maskesiz transkript blob'u (yalnız tur `text` REDACTION'lı izinli)
  "rawtext",
  "recording", // ham ses kaydı (yalnız recordingState BAYRAĞI izinli)
  "recordingbytes",
  "audio",
  "audiobytes",
  "summary", // çağrı özeti (DB §21 transcript.summary) — A-12 sunmaz
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
  "contactname",
  "email",
  "dob",
  "birthdate",
  "cardpan",
  "pan",
  "cvv",
  "otp",
  "ssn",
  "iban",
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

// Katman 2 — İÇERİK redaction desenleri: maskesiz ham PII (telefon/kart/poliçe/hesap/e-posta/IBAN) izi.
// Redaction sonrası içerik yalnız MASK_TOKEN taşır; bu desenler hiçbir string değerde GÖRÜNMEMELİDİR.
export const RAW_PII_PATTERNS: readonly RegExp[] = [
  /\d{7,}/, // ≥7 ardışık rakam: telefon/kart/poliçe/hesap numarası
  /\+\d{6,}/, // +90... biçimli ham telefon
  /\d{4}[\s-]\d{4}[\s-]\d{4}/, // kart bloğu (4-4-4...)
  /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/, // e-posta
  /\bTR\d{2}[\s]?\d/, // IBAN (TR + 2 rakam)
];

// YAPISAL anahtar guard: yasak alan ADI bulursa hata fırlatır.
export function assertNoForbiddenKeys(node: unknown, path = "$"): void {
  if (node && typeof node === "object") {
    if (Array.isArray(node)) {
      node.forEach((v, i) => assertNoForbiddenKeys(v, `${path}[${i}]`));
      return;
    }
    for (const k of Object.keys(node as Record<string, unknown>)) {
      const lower = k.toLowerCase();
      if (FORBIDDEN_PII_KEYS.includes(lower)) {
        throw new Error(`A-12 HİJYEN ihlali: yasak PII/iş-içeriği alanı "${path}.${k}" (BRD §17.7 / FR-REC-004/005)`);
      }
      if (FORBIDDEN_SECRET_KEYS.includes(lower)) {
        throw new Error(`A-12 GÜVENLİK ihlali: sır/credential/nesne-depo URI alanı "${path}.${k}" panele konmaz (NFR 10.6)`);
      }
      assertNoForbiddenKeys((node as Record<string, unknown>)[k], `${path}.${k}`);
    }
  }
}

// İÇERİK redaction guard: herhangi bir string değerde ham PII DESENİ bulursa hata fırlatır (FR-REC-004/005).
export function assertRedactionClean(node: unknown, path = "$"): void {
  if (typeof node === "string") {
    for (const re of RAW_PII_PATTERNS) {
      if (re.test(node)) {
        throw new Error(`A-12 REDACTION ihlali: maskesiz ham PII deseni "${path}" (FR-REC-004/005; redaction panel görüntülemelerinde de uygulanır)`);
      }
    }
    return;
  }
  if (node && typeof node === "object") {
    if (Array.isArray(node)) {
      node.forEach((v, i) => assertRedactionClean(v, `${path}[${i}]`));
      return;
    }
    for (const k of Object.keys(node as Record<string, unknown>)) {
      if (k.startsWith("$")) continue; // sample meta ($comment/$expect) hariç
      assertRedactionClean((node as Record<string, unknown>)[k], `${path}.${k}`);
    }
  }
}

// İki katmanı birlikte uygular (HİJYEN + GÜVENLİK + REDACTION).
export function assertSafe(view: unknown): void {
  assertNoForbiddenKeys(view);
  assertRedactionClean(view);
}

// ── veri SEAM (yer tutucu) ───────────────────────────────────────────────────────
// Deterministik yer tutucu: TEK çağrı detayı (künye META + yapısal olaylar + REDACTION'lı transkript).
// Gerçek implementasyon (F1 §14.1) Call Store + Transcript + Event (DB §19/§21/§23) tenant-scope (RLS) +
// redaction motoru (WBS 11.3/11.4) çıktısıyla beslenir; routing /workspace/call/[callRef] F1 kapsamı.
// Bu örnek: sağlıklı, görüntülenebilir bir inbound çağrı (redaction tamam + erişim audit'li); PII yalnız maskeli.
const PLACEHOLDER_VIEW: CallDetailView = {
  generatedAt: "2026-06-18T09:00:00.000Z",
  tenantRef: "TEN-2048",
  tenantName: "Kuzey Sigorta A.Ş.",
  call: {
    callRef: "CALL-1006",
    direction: "inbound",
    agentRef: "AGT-117",
    agentName: "Sigorta Asistanı",
    startedAt: "2026-06-18T08:55:00.000Z",
    durationSec: 214,
    outcome: "contained",
    recordingState: "recorded",
    channels: 2,
    transcriptState: "redacted",
    retentionImminent: false,
    legalHold: false,
    accessAudited: true,
    own: false,
    events: [
      { eventRef: "EV-01", type: "call_connected", offsetMs: 0 },
      { eventRef: "EV-02", type: "greeting", offsetMs: 1500 },
      { eventRef: "EV-03", type: "recording_started", offsetMs: 1600 },
      { eventRef: "EV-04", type: "kb_lookup", offsetMs: 42000, detail: "police_kapsami" },
      { eventRef: "EV-05", type: "tool_invoked", offsetMs: 58000, detail: "police.durum_sorgu" },
      { eventRef: "EV-06", type: "barge_in", offsetMs: 96000 },
      { eventRef: "EV-07", type: "recording_stopped", offsetMs: 212500 },
      { eventRef: "EV-08", type: "call_ended", offsetMs: 214000 },
    ],
    turns: [
      { turnRef: "T-01", speaker: "agent", offsetMs: 1500, text: "Merhaba, ben Kuzey Sigorta yapay zekâ asistanıyım; görüşmemiz kayıt altına alınmaktadır. Size nasıl yardımcı olabilirim?", redacted: false, confidence: 0.99 },
      { turnRef: "T-02", speaker: "caller", offsetMs: 8000, text: "Poliçemin durumunu öğrenmek istiyorum.", redacted: false, confidence: 0.94 },
      { turnRef: "T-03", speaker: "agent", offsetMs: 11000, text: "Tabii, kimliğinizi doğrulamak için doğum tarihinizi alabilir miyim?", redacted: false, confidence: 0.98 },
      { turnRef: "T-04", speaker: "caller", offsetMs: 15000, text: "Doğum tarihim [•••].", redacted: true, confidence: 0.62 },
      { turnRef: "T-05", speaker: "agent", offsetMs: 19000, text: "Teşekkürler. Poliçe numarası [•••] ile biten kaydınız aktif görünüyor.", redacted: true, confidence: 0.97 },
      { turnRef: "T-06", speaker: "caller", offsetMs: 28000, text: "Peki primimi kartla ödeyebilir miyim?", redacted: false, confidence: 0.9 },
      { turnRef: "T-07", speaker: "agent", offsetMs: 32000, text: "Elbette; güvenliğiniz için kart bilgileri sistemde gizlenmektedir.", redacted: false, confidence: 0.96 },
      { turnRef: "T-08", speaker: "caller", offsetMs: 96000, text: "Aslında şimdilik vazgeçtim, teşekkürler.", redacted: false, confidence: 0.88 },
      { turnRef: "T-09", speaker: "agent", offsetMs: 100000, text: "Rica ederim, iyi günler dilerim.", redacted: false, confidence: 0.99 },
    ],
  },
};

export async function getCallDetailView(): Promise<CallDetailView> {
  const view = PLACEHOLDER_VIEW;
  assertSafe(view); // HİJYEN + GÜVENLİK + REDACTION: yapısal PII/sır/URI yok + içerik maskesiz ham PII deseni yok
  return view;
}
