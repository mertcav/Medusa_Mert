// WBS 13.2.7 — L0 ekranı P-07 "Platform Audit & Güvenlik" (gerçek içerik; 13.1.1 iskeletinin yerini alır).
//
// İÇERİK (BRD §17.3): platform geneli audit log, erişim ve güvenlik olayları.
// FR-IAM-006 (değiştirilemez/WORM audit log) · FR-REC-009 (kayıt/transkript erişimi audit'i) ·
// FR-IAM-008 (panel-katman rol ayrımı / altın kural) · FR-IAM-009 (üç katmanlı break-glass: maker-checker +
// time-box + bildirim) · FR-IAM-010 (regüle tenant onayı) · FR-IAM-005 (maker-checker).
// ALTIN KURAL (BRD §17.7 / FR-IAM-008): yalnız platform-geneli audit/erişim/güvenlik METADATASI; tenant iş
// içeriği (çağrı kaydı/transkript/son-müşteri PII) GÖSTERİLMEZ — veri katmanı `assertNoPii` ile garanti eder.
// tenant kimliği (tenantRef) izinli. RBAC (BRD §17.6): platform_owner=Yönet + platform_sre=Görüntüle +
// platform_billing=erişim yok. UI yalnız görsel kapı; nihai yetki + audit dışa aktarım/break-glass onay
// zorlaması backend'de (12.2.x; permission-key audit:read + audit:export + breakglass:approve, SAD §7 ·
// §14.4.1 A8). Tüm kullanıcı-görünür metin i18n katalogundan (t()).
import type { CSSProperties } from "react";
import { getServerLocale } from "@/lib/i18n/server";
import { getCatalog, t, formatNumber, formatDate, type Locale } from "@/lib/i18n";
import { PageHeader, Card, StatusPill, Alert, Table, EmptyState, Button } from "@/lib/ui/components";
import {
  getAudit,
  auditOutcomeTone,
  breakGlassStatusTone,
  severityTone,
  securityStatusTone,
  wormGaps,
  countActiveBreakGlass,
  pendingApprovals,
  breakGlassComplianceGaps,
  openSecurityEvents,
  criticalOpenEvents,
  type PlatformRole,
  type AuditCategory,
  type AuditOutcome,
  type BreakGlassTier,
  type BreakGlassStatus,
  type SecuritySeverity,
  type SecurityStatus,
  type AuditEntry,
  type BreakGlassSession,
  type SecurityEvent,
} from "@/lib/platform/audit";

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
  const k = (key: string, p?: Record<string, string | number>) => t(cat, `screen.p07.${key}`, p);
  const snap = await getAudit();
  const { auditEntries, breakGlassSessions, securityEvents } = snap;

  const num = (n: number) => formatNumber(locale, n);
  const dt = (iso: string) => formatDate(locale, new Date(iso), { dateStyle: "short", timeStyle: "short" });
  const roleLabel = (r: PlatformRole) => k(`actor_role.${r}`);
  const categoryLabel = (c: AuditCategory) => k(`audit_category.${c}`);
  const outcomeLabel = (o: AuditOutcome) => k(`audit_outcome.${o}`);
  const tierLabel = (tr: BreakGlassTier) => k(`tier.${tr}`);
  const bgStatusLabel = (s: BreakGlassStatus) => k(`break_glass_status.${s}`);
  const severityLabel = (s: SecuritySeverity) => k(`severity.${s}`);
  const secStatusLabel = (s: SecurityStatus) => k(`security_status.${s}`);
  const boolLabel = (b: boolean) => k(b ? "bool.yes" : "bool.no");

  const worm = wormGaps(snap);
  const activeBg = countActiveBreakGlass(breakGlassSessions);
  const pending = pendingApprovals(breakGlassSessions);
  const complianceGaps = breakGlassComplianceGaps(snap);
  const openSec = openSecurityEvents(securityEvents);
  const criticalSec = criticalOpenEvents(securityEvents);

  return (
    <section data-screen="P-07">
      <PageHeader title={k("title")} description={k("subtitle")} code="P-07" />

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
        {/* Audit dışa aktarım — UI yalnız görsel kapı; zorlama backend'de (A8). */}
        <Button variant="primary">{k("export_action")}</Button>
      </div>

      {/* Özet KPI */}
      <div style={grid()}>
        <Kpi label={k("kpi.audit_events")} value={num(auditEntries.length)} />
        <Kpi label={k("kpi.break_glass_active")} value={num(activeBg)} tone={activeBg > 0 ? "var(--rmc-warning-fg)" : undefined} />
        <Kpi label={k("kpi.pending_approvals")} value={num(pending.length)} />
        <Kpi label={k("kpi.open_security")} value={num(openSec.length)} />
        <Kpi label={k("kpi.critical_security")} value={num(criticalSec.length)} tone={criticalSec.length > 0 ? "var(--rmc-danger-fg)" : undefined} />
        <Kpi label={k("kpi.compliance_gaps")} value={num(complianceGaps.length)} tone={complianceGaps.length > 0 ? "var(--rmc-danger-fg)" : undefined} />
      </div>

      {/* Audit integrity (WORM) + break-glass uyum + kritik güvenlik uyarıları */}
      <div style={{ marginBottom: "var(--rmc-space-2)" }}>
        {worm.length === 0 ? (
          <Alert tone="success">{k("worm_ok")}</Alert>
        ) : (
          <Alert tone="danger">{k("worm_alert", { count: num(worm.length) })}</Alert>
        )}
      </div>
      <div style={{ marginBottom: "var(--rmc-space-2)" }}>
        {complianceGaps.length === 0 ? (
          <Alert tone="success">{k("compliance_ok")}</Alert>
        ) : (
          <Alert tone="danger">{k("compliance_alert", { count: num(complianceGaps.length) })}</Alert>
        )}
      </div>
      <div style={{ marginBottom: "var(--rmc-space-5)" }}>
        {criticalSec.length === 0 ? (
          <Alert tone="success">{k("critical_ok")}</Alert>
        ) : (
          <Alert tone="danger">{k("critical_alert", { count: num(criticalSec.length) })}</Alert>
        )}
      </div>

      {/* Platform-geneli audit log (FR-IAM-006 WORM + FR-REC-009 erişim audit'i) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", marginBottom: "var(--rmc-space-3)" }}>{k("section.audit")}</h2>
      <Card>
        {auditEntries.length === 0 ? (
          <EmptyState message={k("no_audit")} />
        ) : (
          <Table caption={k("audit_caption")}>
            <thead>
              <tr style={{ textAlign: "start", borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.time")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.actor")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.action")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.category")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.tenant")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.outcome")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.integrity")}</th>
              </tr>
            </thead>
            <tbody>
              {auditEntries.map((e: AuditEntry) => (
                <tr key={e.id} style={{ borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                  <td style={cell}>{dt(e.occurredAt)}</td>
                  <td style={cell}>{roleLabel(e.actorRole)}</td>
                  <td style={cell}>{e.action}</td>
                  <td style={cell}>{categoryLabel(e.category)}</td>
                  <td style={cell}>{e.tenantRef}</td>
                  <td style={cell}>
                    <StatusPill tone={auditOutcomeTone(e.outcome)}>{outcomeLabel(e.outcome)}</StatusPill>
                  </td>
                  <td style={cell}>
                    <StatusPill tone={e.wormAnchored ? "success" : "danger"}>{boolLabel(e.wormAnchored)}</StatusPill>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      {/* Break-glass erişim oturumları (FR-IAM-009/010 uyum metadatası) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.break_glass")}</h2>
      <Card>
        {breakGlassSessions.length === 0 ? (
          <EmptyState message={k("no_break_glass")} />
        ) : (
          <Table caption={k("break_glass_caption")}>
            <thead>
              <tr style={{ textAlign: "start", borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.tier")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.status")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.tenant")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.reason")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.requested_by")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.approved_by")}</th>
                <th style={{ ...cell, textAlign: "end" }}>{k("col.time_box")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.tenant_approval")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.notified")}</th>
              </tr>
            </thead>
            <tbody>
              {breakGlassSessions.map((s: BreakGlassSession) => (
                <tr key={s.id} style={{ borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                  <td style={cell}>{tierLabel(s.tier)}</td>
                  <td style={cell}>
                    <StatusPill tone={breakGlassStatusTone(s.status)}>{bgStatusLabel(s.status)}</StatusPill>
                  </td>
                  <td style={cell}>{s.tenantRef}</td>
                  <td style={cell}>{s.reasonCode}</td>
                  <td style={cell}>{s.requestedBy}</td>
                  <td style={cell}>{s.approvedBy ?? "—"}</td>
                  <td style={{ ...cell, textAlign: "end" }}>{k("min_value", { remaining: num(s.remainingMin), total: num(s.durationMin) })}</td>
                  <td style={cell}>{s.tenantApprovalRequired ? boolLabel(s.tenantApproved) : k("not_required")}</td>
                  <td style={cell}>{boolLabel(s.notified)}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
        <p style={{ color: "var(--rmc-text-muted)", fontSize: "var(--rmc-size-sm)", marginTop: "var(--rmc-space-3)" }}>
          {k("break_glass_note")}
        </p>
      </Card>

      {/* Platform-geneli güvenlik olayları */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.security")}</h2>
      <Card>
        {securityEvents.length === 0 ? (
          <EmptyState message={k("no_security")} />
        ) : (
          <Table caption={k("security_caption")}>
            <thead>
              <tr style={{ textAlign: "start", borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.time")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.event_type")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.severity")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.status")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.requirement")}</th>
              </tr>
            </thead>
            <tbody>
              {securityEvents.map((ev: SecurityEvent) => (
                <tr key={ev.id} style={{ borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                  <td style={cell}>{dt(ev.occurredAt)}</td>
                  <td style={cell}>{k(`event_type.${ev.type}`)}</td>
                  <td style={cell}>
                    <StatusPill tone={severityTone(ev.severity)}>{severityLabel(ev.severity)}</StatusPill>
                  </td>
                  <td style={cell}>
                    <StatusPill tone={securityStatusTone(ev.status)}>{secStatusLabel(ev.status)}</StatusPill>
                  </td>
                  <td style={cell}>{ev.mappedFr}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </section>
  );
}
