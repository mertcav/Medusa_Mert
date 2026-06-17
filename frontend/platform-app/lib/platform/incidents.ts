// WBS 13.2.9 — P-09 "Alarm & Incident (SRE)" veri katmanı (seam) + SAF türetme yardımcıları.
//
// ÇEKİRDEK İLKELER (P-01..P-08 ile aynı disiplin; lib/platform/overview.ts + tenants.ts + resources.ts +
// providers.ts + billing.ts + policy.ts + audit.ts + releases.ts):
//  - ALTIN KURAL (BRD §17.7 / FR-IAM-008): L0 platform konsolu YALNIZ platform-geneli alarm/incident
//    METADATASI gösterir; tenant İŞ İÇERİĞİ (çağrı kaydı, transkript, son-müşteri/PII) GÖSTERİLMEZ.
//    `platform_sre` iş içeriği görmez (BRD §17.2). Alarm/incident `scope` alanı VENDOR-NÖTR bileşen/bölge
//    (ör. "orchestrator/EU") — tenant kimliği/listesi DEĞİL. Tipler YAPISAL OLARAK iş-içeriği/PII taşımaz;
//    `assertNoPii` çalışma-anında doğrular. On-call atama ROL'dür (kişi/PII değil; FR-IAM-008).
//  - İÇERİK (BRD §17.3 P-09 + §15 + SAD §17.1/§17.2): platform alarmları (kritik alarm kataloğu) + incident
//    (SRE) yönetimi. Kritik alarm üretim gecikmesi ≤ 2 dk = 120 sn (NFR 10.1 / SR-PERF-008); incident
//    response prosedürü + IR runbook (NFR 10.6 / SR-SEC-008).
//  - SAF/DETERMİNİSTİK: türetme yardımcıları (alarmSeverityTone/alarmStateTone/alarmSignalTone/
//    incidentSeverityTone/incidentStatusTone/incidentEventTypeTone/countBySeverity/firingAlarms/
//    unacknowledgedAlarms/budgetBreaches/openIncidents/criticalOpenIncidents/escalationEvents/
//    resolvedIncidents) Date.now/rastgelelik içermez → birim-test edilebilir + Python aynası
//    (screens/p09-incidents/p09_incidents_probe.py).
//  - İŞ MANTIĞI/AUTHZ YOK (SAD §14.4.1 A8): alarm sustur (silence) / incident ata / onayla (acknowledge) /
//    çöz (resolve) aksiyonları UI'da yalnız görsel kapıdır; nihai yetki + zorlama backend'de (12.2.x;
//    permission-key `alert:read` + `alert:manage` + `incident:read` + `incident:manage` +
//    `incident:acknowledge`, SAD §7 · §17.2 `incident:manage`). RBAC (BRD §17.6): bu ekran
//    `platform_owner`=Yönet + `platform_sre`=Yönet + `platform_billing`=erişim yok.

// Aktör / on-call — L0 platform rolü (tenant rolleri tamamen ayrı; FR-IAM-008). KİŞİ DEĞİL (PII yok).
export type PlatformRole = "platform_owner" | "platform_sre" | "platform_billing";

// Alarm önem derecesi (SAD §17.2 kataloğu): critical (kritik) · warning (uyarı) · info (bilgi).
export type AlarmSeverity = "critical" | "warning" | "info";

// Alarm durumu: firing (aktif/tetikleniyor) · pending (eşik aşıldı, doğrulama bekliyor) ·
// acknowledged (onaylandı, üzerinde çalışılıyor) · resolved (çözüldü).
export type AlarmState = "firing" | "pending" | "acknowledged" | "resolved";

// Alarm sinyal sınıfı (BRD §15 kritik alarm kataloğu, VENDOR-NÖTR kategori — somut metrik adı değil):
// latency (gecikme) · error_rate (hata oranı) · capacity (kapasite) · spend (harcama) · resource (kaynak) ·
// security (güvenlik: consent atlama / bilgi sızıntısı).
export type AlarmSignal = "latency" | "error_rate" | "capacity" | "spend" | "resource" | "security";

// Incident önem derecesi (SRE): sev1 (en kritik) · sev2 · sev3.
export type IncidentSeverity = "sev1" | "sev2" | "sev3";

// Incident durumu: open (açık) · acknowledged (onaylandı) · mitigated (hafifletildi) · resolved (çözüldü).
export type IncidentStatus = "open" | "acknowledged" | "mitigated" | "resolved";

// Incident olay tipi (IR akışı): triggered (oluşturuldu) · acknowledged (onaylandı) · escalated (eskale) ·
// mitigated (hafifletildi) · resolved (çözüldü) · note (not).
export type IncidentEventType = "triggered" | "acknowledged" | "escalated" | "mitigated" | "resolved" | "note";

// Dağıtım olayı sonucu sözleşmesiyle hizalı StatusPill/Alert ton kümesi.
export type Tone = "success" | "warning" | "info" | "danger" | "neutral";

// Kritik alarm üretim bütçesi (NFR 10.1 / SR-PERF-008): ≤ 2 dk = 120 sn (SAD §17.2 detection_budget_s).
export const DETECTION_BUDGET_SEC = 120;

// Platform alarmı (BRD §15 / SAD §17.2 kataloğu). name VENDOR-NÖTR alarm kural ADIDIR (kod string —
// çevrilmez; ör. "E2EP95LatencyHigh"). scope VENDOR-NÖTR bileşen/bölge (tenant kimliği DEĞİL).
export interface Alarm {
  id: string;
  name: string; // alarm kural adı (kod string — ör. "E2EP95LatencyHigh", "HandoffFailure")
  severity: AlarmSeverity;
  signal: AlarmSignal;
  scope: string; // vendor-nötr bileşen/bölge (ör. "orchestrator/EU", "media-gateway/global") — tenant kimliği DEĞİL
  state: AlarmState;
  detectionLatencySec: number; // koşul-doğru → alarm-üretildi gecikmesi (NFR 10.1 ≤120s)
  firedAt: string; // ISO-8601 (sabit yer tutucu — SSR-stabil, Date.now YOK)
  mappedReq: string; // izlenebilirlik (BRD §15 / SR-PERF-008 vb.) — kod string
}

// Incident (SRE). title KISA NON-PII etikettir (kod string — ör. "orchestrator-latency-regression").
// assigneeRole ON-CALL ROL'dür (kişi/PII değil; FR-IAM-008). linkedAlarm ilişkili alarm kural adı (kod).
export interface Incident {
  id: string;
  title: string; // kısa non-PII incident etiketi (kod string — çevrilmez)
  severity: IncidentSeverity;
  status: IncidentStatus;
  assigneeRole: PlatformRole; // on-call ROL (kişi/PII DEĞİL)
  linkedAlarm: string; // ilişkili alarm kural adı (kod) veya "—"
  scope: string; // vendor-nötr bileşen/bölge — tenant kimliği DEĞİL
  openedAt: string; // ISO-8601 (sabit yer tutucu)
  mappedReq: string;
}

// Incident olay akışı kaydı — IR işleminin META verisi (tüm işlemler audit edilir; P-07/FR-IAM-006).
export interface IncidentEvent {
  id: string;
  occurredAt: string; // ISO-8601 (sabit yer tutucu)
  type: IncidentEventType;
  actorRole: PlatformRole;
  target: string; // ilgili incident id (kod string)
  mappedReq: string;
}

export interface IncidentSnapshot {
  generatedAt: string; // ISO-8601 (sabit yer tutucu — SSR-stabil, Date.now YOK)
  alarms: Alarm[];
  incidents: Incident[];
  events: IncidentEvent[];
}

// ── saf türetme yardımcıları ────────────────────────────────────────────────────

// Alarm önem tonu: critical danger · warning warning · info info.
const ALARM_SEVERITY_TONE: Record<AlarmSeverity, Tone> = {
  critical: "danger",
  warning: "warning",
  info: "info",
};
export function alarmSeverityTone(s: AlarmSeverity): Tone {
  return ALARM_SEVERITY_TONE[s];
}

// Alarm durum tonu: firing danger (aktif) · pending warning (doğrulama bekliyor) · acknowledged info
// (üzerinde çalışılıyor) · resolved success (çözüldü).
const ALARM_STATE_TONE: Record<AlarmState, Tone> = {
  firing: "danger",
  pending: "warning",
  acknowledged: "info",
  resolved: "success",
};
export function alarmStateTone(s: AlarmState): Tone {
  return ALARM_STATE_TONE[s];
}

// Alarm sinyal tonu: security danger (consent/sızıntı) · error_rate/capacity/spend/resource warning ·
// latency info.
const ALARM_SIGNAL_TONE: Record<AlarmSignal, Tone> = {
  latency: "info",
  error_rate: "warning",
  capacity: "warning",
  spend: "warning",
  resource: "warning",
  security: "danger",
};
export function alarmSignalTone(s: AlarmSignal): Tone {
  return ALARM_SIGNAL_TONE[s];
}

// Incident önem tonu: sev1 danger · sev2 warning · sev3 info.
const INCIDENT_SEVERITY_TONE: Record<IncidentSeverity, Tone> = {
  sev1: "danger",
  sev2: "warning",
  sev3: "info",
};
export function incidentSeverityTone(s: IncidentSeverity): Tone {
  return INCIDENT_SEVERITY_TONE[s];
}

// Incident durum tonu: open danger · acknowledged warning · mitigated info · resolved success.
const INCIDENT_STATUS_TONE: Record<IncidentStatus, Tone> = {
  open: "danger",
  acknowledged: "warning",
  mitigated: "info",
  resolved: "success",
};
export function incidentStatusTone(s: IncidentStatus): Tone {
  return INCIDENT_STATUS_TONE[s];
}

// Incident olay tipi tonu: triggered danger · escalated warning · acknowledged/mitigated info ·
// resolved success · note neutral.
const INCIDENT_EVENT_TYPE_TONE: Record<IncidentEventType, Tone> = {
  triggered: "danger",
  acknowledged: "info",
  escalated: "warning",
  mitigated: "info",
  resolved: "success",
  note: "neutral",
};
export function incidentEventTypeTone(t: IncidentEventType): Tone {
  return INCIDENT_EVENT_TYPE_TONE[t];
}

// Alarm önem-derecesi sayımı (özet KPI).
export function countBySeverity(alarms: Alarm[]): Record<AlarmSeverity, number> {
  const acc: Record<AlarmSeverity, number> = { critical: 0, warning: 0, info: 0 };
  for (const a of alarms) acc[a.severity] += 1;
  return acc;
}

// Aktif (firing) alarm id'leri — anlık dağıtım/operasyon riski.
export function firingAlarms(snap: IncidentSnapshot): string[] {
  return snap.alarms.filter((a) => a.state === "firing").map((a) => a.id);
}

// Onay bekleyen alarmlar (state in {firing, pending}) — henüz acknowledge edilmemiş; SRE müdahalesi gerekir.
export function unacknowledgedAlarms(alarms: Alarm[]): string[] {
  return alarms.filter((a) => a.state === "firing" || a.state === "pending").map((a) => a.id);
}

// Bütçe aşan alarmlar (NFR 10.1 / SR-PERF-008): üretim gecikmesi > 120 sn — kritik alarm ≤2dk hedefi ihlali.
export function budgetBreaches(alarms: Alarm[]): string[] {
  return alarms.filter((a) => a.detectionLatencySec > DETECTION_BUDGET_SEC).map((a) => a.id);
}

// Açık incident'ler (status != resolved) — devam eden IR.
export function openIncidents(incidents: Incident[]): string[] {
  return incidents.filter((i) => i.status !== "resolved").map((i) => i.id);
}

// Kritik açık incident'ler (severity in {sev1, sev2} & status != resolved) — öncelikli müdahale.
export function criticalOpenIncidents(incidents: Incident[]): string[] {
  return incidents
    .filter((i) => (i.severity === "sev1" || i.severity === "sev2") && i.status !== "resolved")
    .map((i) => i.id);
}

// Eskalasyon olayları (type == escalated) — IR runbook eskalasyon adımı (NFR 10.6).
export function escalationEvents(events: IncidentEvent[]): string[] {
  return events.filter((e) => e.type === "escalated").map((e) => e.id);
}

// Çözülen incident'ler (status == resolved) — bilgi amaçlı.
export function resolvedIncidents(incidents: Incident[]): string[] {
  return incidents.filter((i) => i.status === "resolved").map((i) => i.id);
}

// ── ALTIN KURAL koruması (iş-içeriği/son-müşteri PII sızıntısı) ───────────────────
// Snapshot yapısı içinde tenant İŞ İÇERİĞİ/SON-MÜŞTERİ PII'sini çağrıştıran ALAN ADI bulunursa hata
// fırlatır. Bu, P-09'un yalnız platform-geneli alarm/incident METADATASI göstermesini çalışma-anında
// garanti eder (BRD §17.7). scope alanı VENDOR-NÖTR bileşen/bölge (tenant kimliği değil) olduğundan
// listede değildir; on-call atama ROL'dür (kişi/e-posta değil).
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
  "iban",
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
        throw new Error(`P-09 ALTIN KURAL ihlali: yasak iş-içeriği/PII alanı "${path}.${k}" (BRD §17.7)`);
      }
      assertNoPii((node as Record<string, unknown>)[k], `${path}.${k}`);
    }
  }
}

// ── veri SEAM (yer tutucu) ───────────────────────────────────────────────────────
// Deterministik yer tutucu: platform-geneli alarm/incident METADATASI (iş-içeriği/PII DEĞİL).
// Gerçek implementasyon (F2 §14.1) 0.4.7 gözlemlenebilirlik omurgası (alarm kuralları SAD §17.2) +
// incident yönetim/on-call servisi ile beslenir. Alarm adları SAD §17.2 kataloğundan (kod string);
// scope VENDOR-NÖTR bileşen/bölge (ADR-002). Varsayılan profilde alarmlar bütçe içinde + açık incident
// kontrol altında (sağlıklı taban); ihlal/risk senaryoları samples/* altında.
const PLACEHOLDER_SNAPSHOT: IncidentSnapshot = {
  generatedAt: "2026-06-17T09:00:00.000Z",
  alarms: [
    { id: "al-1", name: "E2EP95LatencyHigh", severity: "critical", signal: "latency", scope: "orchestrator/EU", state: "acknowledged", detectionLatencySec: 45, firedAt: "2026-06-17T08:40:00.000Z", mappedReq: "BRD §15 / SR-PERF-008" },
    { id: "al-2", name: "TenantCapacity80", severity: "warning", signal: "capacity", scope: "voice-runtime/global", state: "firing", detectionLatencySec: 30, firedAt: "2026-06-17T08:50:00.000Z", mappedReq: "BRD §15" },
    { id: "al-3", name: "LLMProviderErrorRateHigh", severity: "critical", signal: "error_rate", scope: "orchestrator/NA", state: "resolved", detectionLatencySec: 60, firedAt: "2026-06-17T07:10:00.000Z", mappedReq: "BRD §15" },
    { id: "al-4", name: "ResourceBudgetExceeded", severity: "warning", signal: "resource", scope: "voice-runtime/UK", state: "pending", detectionLatencySec: 90, firedAt: "2026-06-17T08:55:00.000Z", mappedReq: "BRD §15 / SR-RES-016" },
    { id: "al-5", name: "ConsentSkipDetected", severity: "critical", signal: "security", scope: "policy-engine/global", state: "resolved", detectionLatencySec: 20, firedAt: "2026-06-16T22:00:00.000Z", mappedReq: "BRD §15 / FR-CMP-003" },
  ],
  incidents: [
    { id: "in-1", title: "orchestrator-latency-regression", severity: "sev2", status: "acknowledged", assigneeRole: "platform_sre", linkedAlarm: "E2EP95LatencyHigh", scope: "orchestrator/EU", openedAt: "2026-06-17T08:42:00.000Z", mappedReq: "NFR 10.6 / SR-SEC-008" },
    { id: "in-2", title: "llm-provider-error-burst", severity: "sev3", status: "resolved", assigneeRole: "platform_sre", linkedAlarm: "LLMProviderErrorRateHigh", scope: "orchestrator/NA", openedAt: "2026-06-17T07:12:00.000Z", mappedReq: "NFR 10.6" },
    { id: "in-3", title: "consent-guard-review", severity: "sev2", status: "resolved", assigneeRole: "platform_owner", linkedAlarm: "ConsentSkipDetected", scope: "policy-engine/global", openedAt: "2026-06-16T22:05:00.000Z", mappedReq: "NFR 10.6 / FR-CMP-003" },
  ],
  events: [
    { id: "ev-1", occurredAt: "2026-06-17T08:42:00.000Z", type: "triggered", actorRole: "platform_sre", target: "in-1", mappedReq: "NFR 10.6" },
    { id: "ev-2", occurredAt: "2026-06-17T08:45:00.000Z", type: "acknowledged", actorRole: "platform_sre", target: "in-1", mappedReq: "NFR 10.6" },
    { id: "ev-3", occurredAt: "2026-06-17T07:30:00.000Z", type: "resolved", actorRole: "platform_sre", target: "in-2", mappedReq: "NFR 10.6" },
    { id: "ev-4", occurredAt: "2026-06-16T22:20:00.000Z", type: "escalated", actorRole: "platform_owner", target: "in-3", mappedReq: "NFR 10.6" },
    { id: "ev-5", occurredAt: "2026-06-16T22:40:00.000Z", type: "resolved", actorRole: "platform_owner", target: "in-3", mappedReq: "NFR 10.6" },
  ],
};

export async function getIncidents(): Promise<IncidentSnapshot> {
  const snap = PLACEHOLDER_SNAPSHOT;
  assertNoPii(snap); // ALTIN KURAL: yapısal iş-içeriği/son-müşteri PII yok (BRD §17.7)
  return snap;
}
