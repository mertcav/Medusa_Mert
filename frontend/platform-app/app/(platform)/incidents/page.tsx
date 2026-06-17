// WBS 13.2.9 — L0 ekranı P-09 "Alarm & Incident (SRE)" (gerçek içerik; 13.1.1 iskeletinin yerini alır).
//
// İÇERİK (BRD §17.3 P-09 + §15 + SAD §17.1/§17.2): platform alarmları (kritik alarm kataloğu) + incident
// (SRE) yönetimi. Kritik alarm üretim gecikmesi ≤ 2 dk = 120 sn (NFR 10.1 / SR-PERF-008); incident response
// prosedürü + IR runbook (NFR 10.6 / SR-SEC-008). FR-IAM-008 (panel-katman rol ayrımı / altın kural).
// ALTIN KURAL (BRD §17.7 / FR-IAM-008): yalnız platform-geneli alarm/incident METADATASI; tenant iş içeriği
// (çağrı kaydı/transkript/son-müşteri PII) GÖSTERİLMEZ — veri katmanı `assertNoPii` ile garanti eder.
// `platform_sre` iş içeriği görmez (BRD §17.2). alarm/incident `scope` VENDOR-NÖTR bileşen/bölge (tenant
// kimliği değil); on-call atama ROL'dür (kişi/PII değil). RBAC (BRD §17.6): platform_owner=Yönet +
// platform_sre=Yönet + platform_billing=erişim yok. UI yalnız görsel kapı; nihai yetki + alarm sustur /
// incident ata / onayla / çöz zorlaması backend'de (12.2.x; permission-key alert:read + alert:manage +
// incident:read + incident:manage + incident:acknowledge, SAD §7 · §17.2 · §14.4.1 A8). Tüm kullanıcı-görünür
// metin i18n katalogundan (t()).
import type { CSSProperties } from "react";
import { getServerLocale } from "@/lib/i18n/server";
import { getCatalog, t, formatNumber, formatDate, type Locale } from "@/lib/i18n";
import { PageHeader, Card, StatusPill, Alert, Table, EmptyState, Button } from "@/lib/ui/components";
import {
  getIncidents,
  alarmSeverityTone,
  alarmStateTone,
  alarmSignalTone,
  incidentSeverityTone,
  incidentStatusTone,
  incidentEventTypeTone,
  countBySeverity,
  firingAlarms,
  unacknowledgedAlarms,
  budgetBreaches,
  openIncidents,
  criticalOpenIncidents,
  escalationEvents,
  DETECTION_BUDGET_SEC,
  type PlatformRole,
  type AlarmSeverity,
  type AlarmState,
  type AlarmSignal,
  type IncidentSeverity,
  type IncidentStatus,
  type IncidentEventType,
  type Alarm,
  type Incident,
  type IncidentEvent,
} from "@/lib/platform/incidents";

function Kpi({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <Card>
      <div style={{ color: "var(--rmc-text-muted)", fontSize: "var(--rmc-size-sm)" }}>{label}</div>
      <div style={{ fontSize: "var(--rmc-size-2xl)", fontWeight: 700, color: tone ?? "var(--rmc-text-primary)" }}>{value}</div>
    </Card>
  );
}

function grid(): CSSProperties {
  return { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))", gap: "var(--rmc-space-4)", marginBottom: "var(--rmc-space-5)" };
}

const cell: CSSProperties = { padding: "var(--rmc-space-2)" };

export default async function Page() {
  const locale: Locale = getServerLocale();
  const cat = getCatalog(locale);
  const k = (key: string, p?: Record<string, string | number>) => t(cat, `screen.p09.${key}`, p);
  const snap = await getIncidents();
  const { alarms, incidents, events } = snap;

  const num = (n: number) => formatNumber(locale, n);
  const dt = (iso: string) => formatDate(locale, new Date(iso), { dateStyle: "short", timeStyle: "short" });
  const secs = (n: number) => k("sec_value", { sec: num(n) });
  const roleLabel = (r: PlatformRole) => k(`actor_role.${r}`);
  const severityLabel = (s: AlarmSeverity) => k(`alarm_severity.${s}`);
  const stateLabel = (s: AlarmState) => k(`alarm_state.${s}`);
  const signalLabel = (s: AlarmSignal) => k(`alarm_signal.${s}`);
  const incSeverityLabel = (s: IncidentSeverity) => k(`incident_severity.${s}`);
  const incStatusLabel = (s: IncidentStatus) => k(`incident_status.${s}`);
  const eventTypeLabel = (tp: IncidentEventType) => k(`incident_event_type.${tp}`);

  const bySeverity = countBySeverity(alarms);
  const firing = firingAlarms(snap);
  const unacked = unacknowledgedAlarms(alarms);
  const breaches = budgetBreaches(alarms);
  const open = openIncidents(incidents);
  const criticalOpen = criticalOpenIncidents(incidents);
  const escalations = escalationEvents(events);

  return (
    <section data-screen="P-09">
      <PageHeader title={k("title")} description={k("subtitle")} code="P-09" />

      <div style={{ marginBottom: "var(--rmc-space-3)" }}>
        <Alert tone="info">{k("manage_only_note")}</Alert>
      </div>
      <div style={{ marginBottom: "var(--rmc-space-4)" }}>
        <Alert tone="warning">{k("backend_authz_note")}</Alert>
      </div>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "var(--rmc-space-3)", flexWrap: "wrap", marginBottom: "var(--rmc-space-4)" }}>
        <p style={{ color: "var(--rmc-text-muted)", fontSize: "var(--rmc-size-sm)", margin: 0 }}>
          {k("as_of", { time: formatDate(locale, new Date(snap.generatedAt), { dateStyle: "medium", timeStyle: "short" }) })}
        </p>
        {/* Incident oluştur — UI yalnız görsel kapı; zorlama backend'de (A8). */}
        <Button variant="primary">{k("declare_action")}</Button>
      </div>

      {/* Özet KPI */}
      <div style={grid()}>
        <Kpi label={k("kpi.alarms")} value={num(alarms.length)} />
        <Kpi label={k("kpi.firing")} value={num(firing.length)} tone={firing.length > 0 ? "var(--rmc-danger-fg)" : undefined} />
        <Kpi label={k("kpi.open_incidents")} value={num(open.length)} tone={open.length > 0 ? "var(--rmc-warning-fg)" : undefined} />
        <Kpi label={k("kpi.critical_open")} value={num(criticalOpen.length)} tone={criticalOpen.length > 0 ? "var(--rmc-danger-fg)" : undefined} />
        <Kpi label={k("kpi.unacknowledged")} value={num(unacked.length)} tone={unacked.length > 0 ? "var(--rmc-warning-fg)" : undefined} />
        <Kpi label={k("kpi.budget_breaches")} value={num(breaches.length)} tone={breaches.length > 0 ? "var(--rmc-danger-fg)" : undefined} />
      </div>

      {/* Aktif alarm + bütçe ihlali + kritik açık incident + eskalasyon uyarıları */}
      <div style={{ marginBottom: "var(--rmc-space-2)" }}>
        {firing.length === 0 ? (
          <Alert tone="success">{k("firing_ok")}</Alert>
        ) : (
          <Alert tone="danger">{k("firing_alert", { count: num(firing.length) })}</Alert>
        )}
      </div>
      <div style={{ marginBottom: "var(--rmc-space-2)" }}>
        {breaches.length === 0 ? (
          <Alert tone="success">{k("budget_ok", { budget: num(DETECTION_BUDGET_SEC) })}</Alert>
        ) : (
          <Alert tone="danger">{k("budget_alert", { count: num(breaches.length), budget: num(DETECTION_BUDGET_SEC) })}</Alert>
        )}
      </div>
      <div style={{ marginBottom: "var(--rmc-space-2)" }}>
        {criticalOpen.length === 0 ? (
          <Alert tone="success">{k("critical_ok")}</Alert>
        ) : (
          <Alert tone="danger">{k("critical_alert", { count: num(criticalOpen.length) })}</Alert>
        )}
      </div>
      <div style={{ marginBottom: "var(--rmc-space-5)" }}>
        {escalations.length === 0 ? (
          <Alert tone="success">{k("escalation_ok")}</Alert>
        ) : (
          <Alert tone="warning">{k("escalation_alert", { count: num(escalations.length) })}</Alert>
        )}
      </div>

      {/* Platform alarmları (BRD §15 / SAD §17.2 kataloğu) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", marginBottom: "var(--rmc-space-3)" }}>{k("section.alarms")}</h2>
      <Card>
        {alarms.length === 0 ? (
          <EmptyState message={k("no_alarms")} />
        ) : (
          <Table caption={k("alarms_caption")}>
            <thead>
              <tr style={{ textAlign: "start", borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.alarm")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.severity")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.signal")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.scope")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.state")}</th>
                <th style={{ ...cell, textAlign: "end" }}>{k("col.detection")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.fired")}</th>
              </tr>
            </thead>
            <tbody>
              {alarms.map((a: Alarm) => (
                <tr key={a.id} style={{ borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                  <td style={cell}>{a.name}</td>
                  <td style={cell}>
                    <StatusPill tone={alarmSeverityTone(a.severity)}>{severityLabel(a.severity)}</StatusPill>
                  </td>
                  <td style={cell}>
                    <StatusPill tone={alarmSignalTone(a.signal)}>{signalLabel(a.signal)}</StatusPill>
                  </td>
                  <td style={cell}>{a.scope}</td>
                  <td style={cell}>
                    <StatusPill tone={alarmStateTone(a.state)}>{stateLabel(a.state)}</StatusPill>
                  </td>
                  <td style={{ ...cell, textAlign: "end", color: a.detectionLatencySec > DETECTION_BUDGET_SEC ? "var(--rmc-danger-fg)" : undefined }}>{secs(a.detectionLatencySec)}</td>
                  <td style={cell}>{dt(a.firedAt)}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
        <p style={{ color: "var(--rmc-text-muted)", fontSize: "var(--rmc-size-sm)", marginTop: "var(--rmc-space-3)" }}>
          {k("alarms_note", { budget: num(DETECTION_BUDGET_SEC) })}
        </p>
      </Card>

      {/* Incident'ler (SRE) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.incidents")}</h2>
      <Card>
        {incidents.length === 0 ? (
          <EmptyState message={k("no_incidents")} />
        ) : (
          <Table caption={k("incidents_caption")}>
            <thead>
              <tr style={{ textAlign: "start", borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.incident")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.severity")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.status")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.assignee")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.linked_alarm")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.scope")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.opened")}</th>
              </tr>
            </thead>
            <tbody>
              {incidents.map((i: Incident) => (
                <tr key={i.id} style={{ borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                  <td style={cell}>{i.title}</td>
                  <td style={cell}>
                    <StatusPill tone={incidentSeverityTone(i.severity)}>{incSeverityLabel(i.severity)}</StatusPill>
                  </td>
                  <td style={cell}>
                    <StatusPill tone={incidentStatusTone(i.status)}>{incStatusLabel(i.status)}</StatusPill>
                  </td>
                  <td style={cell}>{roleLabel(i.assigneeRole)}</td>
                  <td style={cell}>{i.linkedAlarm}</td>
                  <td style={cell}>{i.scope}</td>
                  <td style={cell}>{dt(i.openedAt)}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
        <p style={{ color: "var(--rmc-text-muted)", fontSize: "var(--rmc-size-sm)", marginTop: "var(--rmc-space-3)" }}>
          {k("incidents_note")}
        </p>
      </Card>

      {/* Incident olay akışı (IR timeline: triggered/acknowledged/escalated/mitigated/resolved) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.events")}</h2>
      <Card>
        {events.length === 0 ? (
          <EmptyState message={k("no_events")} />
        ) : (
          <Table caption={k("events_caption")}>
            <thead>
              <tr style={{ textAlign: "start", borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.time")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.event_type")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.actor")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.target")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.requirement")}</th>
              </tr>
            </thead>
            <tbody>
              {events.map((ev: IncidentEvent) => (
                <tr key={ev.id} style={{ borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                  <td style={cell}>{dt(ev.occurredAt)}</td>
                  <td style={cell}>
                    <StatusPill tone={incidentEventTypeTone(ev.type)}>{eventTypeLabel(ev.type)}</StatusPill>
                  </td>
                  <td style={cell}>{roleLabel(ev.actorRole)}</td>
                  <td style={cell}>{ev.target}</td>
                  <td style={cell}>{ev.mappedReq}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </section>
  );
}
