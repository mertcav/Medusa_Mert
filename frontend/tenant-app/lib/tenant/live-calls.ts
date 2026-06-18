// WBS 13.4.2 — A-02 "Canlı Çağrılar" (Live Calls) veri katmanı (seam) + SAF türetme yardımcıları
// (L2 — Operasyon / Uygulama Paneli).
//
// ÇEKİRDEK İLKELER:
//  - İÇERİK (BRD §17.5 A-02 "Aktif çağrı izleme" / FR-ANA-012): tenant'ın O ANDA AKTİF çağrılarının
//    GERÇEK ZAMANLI operasyon görünümü. Her çağrı: yön (inbound/outbound), çağrı durumu (ringing/
//    in_progress/on_hold/transferring/wrapup), TUR DURUMU (LISTEN/CAPTURE/THINK/SPEAK — SAD §6.1 turn
//    state machine), atanan agent, süre, CANLI gecikme (e2e + STT/LLM/TTS kırılımı — FR-ANA-006),
//    duygu (sentiment), KRİTİK işaret (FR-ANA-008 otomatik flag) ve insan aktarım talebi.
//  - GERÇEK ZAMANLILIK (FR-ANA-012 / SR-ANA-012 / SR-PERF-007): operasyon ekranı metrik gecikmesi
//    ≤60 sn olmalıdır. Snapshot `dataAgeSeconds` taşır; `staleSnapshot` 60 sn bütçesini aşan veriyi
//    işaretler. Panel periyodik (≤60 sn) yenilenir (`refreshIntervalSec`).
//  - TENANT-SCOPE (FR-TEN-002): A-02 YALNIZ oturum açan tenant'ın KENDİ aktif çağrılarını gösterir.
//    Scope çalışma-anında middleware (13.1.2) + RLS (DB §6.3) ile sabitlenir; UI yalnız görsel kapı
//    (SAD §14.4.1 A8). RBAC view-own (human_agent): `callsAssignedTo` ile modellenir; nihai zorlama backend.
//  - HİJYEN (BRD §17.7 + §17.6 PII redaction): canlı izleme görünümü yalnız OPERASYONEL META veridir
//    (çağrı REFERANSI/durum/gecikme/agent). Ham son-müşteri içeriği (transkript/ses kaydı, ham telefon
//    numarası/callerId, kart/CVV) AGGREGATE LİSTEYE gömülmez — taraf yalnız MASKELENMİŞ etiketle gösterilir
//    (`maskedParty`, zaten redакte). Canlı dinleme/transkript derin aksiyon → A-12 (görsel kapı + backend).
//  - GÜVENLİK (NFR 10.6): sır/credential görünüme KONMAZ (token/apiKey/privateKey/kmsKey).
//  - VENDOR-NEUTRAL (ADR-002): veri kaynağı bir SEAM'dir; gerçek implementasyon (F1 §14.1) Conversation
//    Orchestrator canlı oturum durumu + gözlemlenebilirlik omurgası (0.4.7) telemetrisinden tenant-scope
//    (RLS) beslenir. Belirli telefoni/APM sağlayıcısı bağlanmaz.
//  - SAF/DETERMİNİSTİK: türetme yardımcıları (flaggedCalls/handoffPending/latencyBreaches/staleSnapshot/
//    countByState/...) Date.now/rastgelelik içermez → birim-test edilebilir + Python aynası
//    (screens/a02-live-calls/a02_live_calls_probe.py). Süre/yaş snapshot-göreli (SSR-stabil) verilir.
//  - İŞ MANTIĞI/AUTHZ YOK (SAD §14.4.1 A8): çağrı izleme/dinleme/aktarma aksiyonları görsel kapıdır;
//    nihai yetki + işlem backend'de (12.2.x). Panel yalnız çözümlenmiş canlı görünümü gösterir + anomaliyi işaretler.

export type CallDirection = "inbound" | "outbound";
// Çağrı yaşam döngüsü durumu (operasyon görünümü).
export type CallState = "ringing" | "in_progress" | "on_hold" | "transferring" | "wrapup";
// Tur durumu (SAD §6.1 turn state machine): konuşma turunun anlık fazı.
export type TurnState = "listen" | "capture" | "think" | "speak";
export type CallSentiment = "positive" | "neutral" | "negative";

export type StatusTone = "success" | "warning" | "danger" | "neutral" | "info";

// GERÇEK ZAMANLILIK bütçesi (SR-ANA-012 / SR-PERF-007): operasyon ekranı metrik gecikmesi ≤60 sn.
export const FRESHNESS_BUDGET_SEC = 60;
// CANLI çağrı başına uçtan-uca yanıt gecikmesi hedefi (NFR 10.1 P95 ≤1200ms). Aşan çağrı vurgulanır.
export const LIVE_LATENCY_BUDGET_MS = 1200;

// Tek aktif çağrı. Yalnız OPERASYONEL META — ham içerik DEĞİL. callRef = oturum REFERANSI (içerik değil);
// maskedParty = ZATEN REDAKTE edilmiş gösterim etiketi (ham numara/PII değil).
export interface LiveCall {
  id: string; // canlı çağrı oturumu id (UUID) — REFERANS, içerik değil
  callRef: string; // gösterim referansı (ör. "CALL-8842")
  direction: CallDirection; // inbound/outbound
  state: CallState; // çağrı yaşam döngüsü durumu
  turnState: TurnState; // anlık tur fazı (SAD §6.1)
  agentRef: string; // çağrıyı yürüten agent referansı (UUID/handle)
  agentName: string; // agent görünen adı (tenant kendi yapılandırması — son-müşteri PII değil)
  assignedAgentRef: string | null; // izleyen/atanan insan operatör referansı (view-own scope) | yok
  maskedParty: string; // MASKELENMİŞ taraf etiketi (zaten redакte — ham numara DEĞİL)
  startedAt: string; // ISO-8601 (çağrı başlangıcı)
  durationSec: number; // snapshot-göreli süre (SSR-stabil; Date.now YOK)
  liveLatencyMs: number; // son tur uçtan-uca yanıt gecikmesi (NFR 10.1)
  sttMs: number; // STT kısmı (FR-ANA-006)
  llmMs: number; // LLM kısmı (FR-ANA-006)
  ttsMs: number; // TTS kısmı (FR-ANA-006)
  sentiment: CallSentiment; // duygu (FR-ANA-008 girdisi)
  flagged: boolean; // kritik konuşma otomatik işareti (FR-ANA-008)
  flagReason: string | null; // işaret nedeni (kısa kod/etiket — PII değil) | yok
  handoffRequested: boolean; // insan temsilciye aktarım talebi var mı
}

// Kapasite (atanan eşzamanlılık kotası — FR-RES; L0 P-03/T-09 atar).
export interface CapacityInfo {
  concurrentLimit: number; // atanan eşzamanlı çağrı limiti (0 = tanımsız)
  concurrentActive: number; // şu an aktif eşzamanlı çağrı (fleet — topluluk)
}

export interface LiveSnapshot {
  generatedAt: string; // ISO-8601 (sabit yer tutucu — SSR-stabil, Date.now YOK)
  tenantRef: string; // tenant'ın KENDİ kimliği (L2'de izinli)
  tenantName: string; // tenant org adı (izinli; son-müşteri verisi DEĞİL)
  dataAgeSeconds: number; // verinin yaşı (sn) — gerçek zamanlılık (SR-ANA-012)
  refreshIntervalSec: number; // panel yenileme aralığı (sn) — ≤60 (FR-ANA-012)
  capacity: CapacityInfo;
  calls: LiveCall[]; // görünür aktif çağrı alt-kümesi (capacity.concurrentActive = fleet topluluğu)
}

// ── saf türetme yardımcıları ────────────────────────────────────────────────────

// Belirli durumdaki çağrılar.
export function callsInState(calls: LiveCall[], s: CallState): LiveCall[] {
  return calls.filter((c) => c.state === s);
}

// Durum dağılımı (KPI/breakdown).
export function countByState(calls: LiveCall[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const c of calls) out[c.state] = (out[c.state] ?? 0) + 1;
  return out;
}

// Yön dağılımı.
export function countByDirection(calls: LiveCall[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const c of calls) out[c.direction] = (out[c.direction] ?? 0) + 1;
  return out;
}

// Tur durumu dağılımı (SAD §6.1).
export function countByTurnState(calls: LiveCall[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const c of calls) out[c.turnState] = (out[c.turnState] ?? 0) + 1;
  return out;
}

// KRİTİK olarak işaretli çağrılar (FR-ANA-008).
export function flaggedCalls(calls: LiveCall[]): LiveCall[] {
  return calls.filter((c) => c.flagged);
}

// İnsan aktarımı bekleyen çağrılar.
export function handoffPending(calls: LiveCall[]): LiveCall[] {
  return calls.filter((c) => c.handoffRequested);
}

// CANLI gecikme bütçesini (NFR 10.1) aşan çağrılar. Eşik parametrik (varsayılan LIVE_LATENCY_BUDGET_MS).
export function latencyBreaches(calls: LiveCall[], budgetMs: number = LIVE_LATENCY_BUDGET_MS): LiveCall[] {
  return calls.filter((c) => c.liveLatencyMs > budgetMs);
}

// Olumsuz duygulu çağrılar (FR-ANA-008 girdisi).
export function negativeSentimentCalls(calls: LiveCall[]): LiveCall[] {
  return calls.filter((c) => c.sentiment === "negative");
}

// VIEW-OWN scope (RBAC — human_agent): yalnız atanmış operatöre ait çağrılar. Nihai zorlama backend (A8).
export function callsAssignedTo(calls: LiveCall[], agentRef: string): LiveCall[] {
  return calls.filter((c) => c.assignedAgentRef === agentRef);
}

// Eşzamanlılık kullanımı (%): aktif / limit, ≤100'e kıstırılmış. Limit tanımsız (≤0) => 0.
export function concurrencyUtilPct(snap: LiveSnapshot): number {
  const { concurrentLimit, concurrentActive } = snap.capacity;
  if (concurrentLimit <= 0) return 0;
  return Math.min(100, Math.round((concurrentActive / concurrentLimit) * 100));
}

// VERİ BAYAT MI (danger — FR-ANA-012 / SR-ANA-012): veri yaşı 60 sn bütçesini aşıyorsa gerçek zamanlılık
// kaybı. Operasyon ekranı için bütünlük kapısı.
export function staleSnapshot(snap: LiveSnapshot): boolean {
  return snap.dataAgeSeconds > FRESHNESS_BUDGET_SEC;
}

// DİKKAT GEREKTİREN çağrılar (flagged ∪ handoff ∪ gecikme ihlali) — sıra korunur, tekilleştirilir.
export function attentionCalls(calls: LiveCall[]): LiveCall[] {
  const breach = new Set(latencyBreaches(calls).map((c) => c.id));
  return calls.filter((c) => c.flagged || c.handoffRequested || breach.has(c.id));
}

// Toplam açık dikkat sayısı (KPI): tüm anomali türlerinin toplamı.
//   her kritik-flag · her aktarım talebi · her gecikme ihlali · veri bayat · kapasite ≥%90
export function openAttentionCount(snap: LiveSnapshot): number {
  return (
    flaggedCalls(snap.calls).length +
    handoffPending(snap.calls).length +
    latencyBreaches(snap.calls).length +
    (staleSnapshot(snap) ? 1 : 0) +
    (concurrencyUtilPct(snap) >= 90 ? 1 : 0)
  );
}

// ── ton (renk) eşlemeleri ─────────────────────────────────────────────────────────

const STATE_TONE: Record<CallState, StatusTone> = {
  ringing: "info",
  in_progress: "success",
  on_hold: "warning",
  transferring: "info",
  wrapup: "neutral",
};
export function stateTone(s: CallState): StatusTone {
  return STATE_TONE[s];
}

const TURN_TONE: Record<TurnState, StatusTone> = {
  listen: "neutral",
  capture: "info",
  think: "info",
  speak: "success",
};
export function turnTone(t: TurnState): StatusTone {
  return TURN_TONE[t];
}

const DIRECTION_TONE: Record<CallDirection, StatusTone> = {
  inbound: "info",
  outbound: "neutral",
};
export function directionTone(d: CallDirection): StatusTone {
  return DIRECTION_TONE[d];
}

const SENTIMENT_TONE: Record<CallSentiment, StatusTone> = {
  positive: "success",
  neutral: "neutral",
  negative: "danger",
};
export function sentimentTone(s: CallSentiment): StatusTone {
  return SENTIMENT_TONE[s];
}

// Gecikme tonu: > bütçe => danger · > bütçe*0.75 => warning · değilse success.
export function latencyTone(ms: number, budgetMs: number = LIVE_LATENCY_BUDGET_MS): StatusTone {
  if (ms > budgetMs) return "danger";
  if (ms > budgetMs * 0.75) return "warning";
  return "success";
}

// Aktarım tonu: talep var => warning · yok => neutral.
export function handoffTone(b: boolean): StatusTone {
  return b ? "warning" : "neutral";
}

// Kritik işaret tonu: var => danger · yok => neutral.
export function flagTone(b: boolean): StatusTone {
  return b ? "danger" : "neutral";
}

// Kapasite kullanım tonu: ≥%90 danger · ≥%75 warning · değilse success.
export function utilTone(pct: number): StatusTone {
  if (pct >= 90) return "danger";
  if (pct >= 75) return "warning";
  return "success";
}

// Gerçek zamanlılık (tazelik) tonu: bayat => danger · taze => success.
export function freshnessTone(stale: boolean): StatusTone {
  return stale ? "danger" : "success";
}

// ── HİJYEN + GÜVENLİK koruması ─────────────────────────────────────────────────────
// Yapı içinde son-müşteri ham iş içeriği/PII'yi VEYA sır/credential çağrıştıran ALAN ADI bulunursa hata
// fırlatır. Bu, A-02'nin yalnız OPERASYONEL META veriyi (çağrı referansı/durum/gecikme/agent + MASKELENMİŞ
// taraf) — ham transkript/ses kaydı/ham telefon numarası/müşteri PII/kart/sır DEĞİL — göstermesini çalışma-
// anında garanti eder (BRD §17.7 + §17.6 PII redaction + NFR 10.6). NOT: agentName/tenantName tenant'ın
// KENDİ yapılandırmasıdır (L2'de izinli); `maskedParty` zaten redакte gösterim etiketidir (ham değil).
export const FORBIDDEN_PII_KEYS: readonly string[] = [
  "transcript",
  "recording",
  "recordingurl",
  "audio",
  "msisdn",
  "phonenumber",
  "callerid",
  "callernumber",
  "calleenumber",
  "customer",
  "customername",
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
        throw new Error(`A-02 HİJYEN ihlali: yasak PII/iş-içeriği alanı "${path}.${k}" (BRD §17.7)`);
      }
      if (FORBIDDEN_SECRET_KEYS.includes(lower)) {
        throw new Error(`A-02 GÜVENLİK ihlali: sır/credential alanı "${path}.${k}" panele konmaz (NFR 10.6)`);
      }
      assertNoPii((node as Record<string, unknown>)[k], `${path}.${k}`);
    }
  }
}

// ── veri SEAM (yer tutucu) ───────────────────────────────────────────────────────
// Deterministik yer tutucu: tek-tenant CANLI çağrı görünümü (OPERASYONEL META yalnız — ham içerik/PII/sır
// DEĞİL). Taraf MASKELENMİŞ; süre/yaş snapshot-göreli (SSR-stabil). Gerçek implementasyon (F1 §14.1)
// Conversation Orchestrator canlı oturum durumu + gözlemlenebilirlik omurgası (0.4.7) telemetrisinden
// tenant-scope (RLS) beslenir.
const PLACEHOLDER_SNAPSHOT: LiveSnapshot = {
  generatedAt: "2026-06-18T09:00:00.000Z",
  tenantRef: "TEN-2048",
  tenantName: "Kuzey Sigorta A.Ş.",
  dataAgeSeconds: 8,
  refreshIntervalSec: 15,
  capacity: { concurrentLimit: 250, concurrentActive: 142 },
  calls: [
    {
      id: "LC-7001",
      callRef: "CALL-8842",
      direction: "inbound",
      state: "in_progress",
      turnState: "speak",
      agentRef: "AGT-77",
      agentName: "Hasar Karşılama",
      assignedAgentRef: null,
      maskedParty: "+90 5•• ••• ••42",
      startedAt: "2026-06-18T08:58:30.000Z",
      durationSec: 90,
      liveLatencyMs: 740,
      sttMs: 160,
      llmMs: 380,
      ttsMs: 200,
      sentiment: "neutral",
      flagged: false,
      flagReason: null,
      handoffRequested: false,
    },
    {
      id: "LC-7002",
      callRef: "CALL-8843",
      direction: "inbound",
      state: "in_progress",
      turnState: "think",
      agentRef: "AGT-77",
      agentName: "Hasar Karşılama",
      assignedAgentRef: null,
      maskedParty: "+90 5•• ••• ••11",
      startedAt: "2026-06-18T08:57:10.000Z",
      durationSec: 170,
      liveLatencyMs: 1320,
      sttMs: 210,
      llmMs: 880,
      ttsMs: 230,
      sentiment: "negative",
      flagged: true,
      flagReason: "low_confidence",
      handoffRequested: false,
    },
    {
      id: "LC-7003",
      callRef: "CALL-8844",
      direction: "outbound",
      state: "transferring",
      turnState: "listen",
      agentRef: "AGT-90",
      agentName: "Tahsilat Hatırlatma",
      assignedAgentRef: "OP-501",
      maskedParty: "+90 5•• ••• ••07",
      startedAt: "2026-06-18T08:56:00.000Z",
      durationSec: 240,
      liveLatencyMs: 620,
      sttMs: 150,
      llmMs: 300,
      ttsMs: 170,
      sentiment: "neutral",
      flagged: false,
      flagReason: null,
      handoffRequested: true,
    },
    {
      id: "LC-7004",
      callRef: "CALL-8845",
      direction: "inbound",
      state: "on_hold",
      turnState: "capture",
      agentRef: "AGT-77",
      agentName: "Hasar Karşılama",
      assignedAgentRef: null,
      maskedParty: "+90 5•• ••• ••63",
      startedAt: "2026-06-18T08:59:05.000Z",
      durationSec: 55,
      liveLatencyMs: 540,
      sttMs: 140,
      llmMs: 260,
      ttsMs: 140,
      sentiment: "positive",
      flagged: false,
      flagReason: null,
      handoffRequested: false,
    },
    {
      id: "LC-7005",
      callRef: "CALL-8846",
      direction: "inbound",
      state: "ringing",
      turnState: "listen",
      agentRef: "AGT-77",
      agentName: "Hasar Karşılama",
      assignedAgentRef: null,
      maskedParty: "+90 5•• ••• ••28",
      startedAt: "2026-06-18T08:59:55.000Z",
      durationSec: 3,
      liveLatencyMs: 0,
      sttMs: 0,
      llmMs: 0,
      ttsMs: 0,
      sentiment: "neutral",
      flagged: false,
      flagReason: null,
      handoffRequested: false,
    },
    {
      id: "LC-7006",
      callRef: "CALL-8847",
      direction: "outbound",
      state: "wrapup",
      turnState: "listen",
      agentRef: "AGT-90",
      agentName: "Tahsilat Hatırlatma",
      assignedAgentRef: "OP-502",
      maskedParty: "+90 5•• ••• ••84",
      startedAt: "2026-06-18T08:54:20.000Z",
      durationSec: 320,
      liveLatencyMs: 700,
      sttMs: 160,
      llmMs: 360,
      ttsMs: 180,
      sentiment: "positive",
      flagged: false,
      flagReason: null,
      handoffRequested: false,
    },
  ],
};

export async function getLiveCalls(): Promise<LiveSnapshot> {
  const snap = PLACEHOLDER_SNAPSHOT;
  assertNoPii(snap); // HİJYEN + GÜVENLİK: yapısal son-müşteri PII / sır yok (BRD §17.7 / NFR 10.6)
  return snap;
}
