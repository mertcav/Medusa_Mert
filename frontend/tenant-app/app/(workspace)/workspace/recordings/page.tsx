// WBS 13.4.11 — L2 ekranı A-11 "Çağrı Kayıtları" (gerçek içerik; 13.1.1 iskeletinin yerini alır).
//
// İÇERİK (BRD §17.5 A-11 "Çağrı Kayıtları" — "Kayıt arama/filtreleme"): bir tenant'ın çağrı kayıtlarının (CDR —
// DB §19 call) ARANABİLİR/FİLTRELENEBİLİR envanteri. KAYIT ÖZETİ (çağrı · kayıtlı · kayıt-kapalı · redaction-
// bekleyen · yasal-tutma · silinmek-üzere · çift-kanal · açık-dikkat), ÇAĞRI KAYITLARI tablosu (çağrı · yön ·
// agent · sonuç · süre · kayıt durumu FR-REC-001/002/003 · transkript FR-REC-004 · saklama FR-REC-006/007 ·
// erişim FR-REC-009), SONUÇ DAĞILIMI (FR-ANA-002/003), KAYIT DURUMU DAĞILIMI (FR-REC-001/002/003 — filtre boyutu),
// SAKLAMA & YASAL TUTMA SAĞLIĞI (FR-REC-006/007/010) ve ERİŞİM & REDACTION SAĞLIĞI (FR-REC-004/005/008/009).
// Ham ses kaydı BYTE'ı / transkript METNİ / ham numara (e164) / müşteri PII / kart-OTP / nesne-depo URI'si /
// çağrı özeti GÖSTERİLMEZ — yalnız DURUM/BAYRAK + agregat SAYI; çağrıyı dinleme/transkripti görme derin aksiyondur
// (A-12 + FR-REC-008/009 yetki + audit). TENANT-SCOPE (FR-TEN-002): yalnız oturum açan tenant (middleware 13.1.2 +
// RLS). HİJYEN (BRD §17.7 + §17.6 + FR-REC-004/005): yalnız META; ham müşteri içeriği/PII gömülmez. GÜVENLİK
// (NFR 10.6): sır + nesne-depo URI konmaz. RBAC (BRD §17.6 A-11 satırı): operations_manager=Yönet ·
// conversation_designer=Görüntüle · qa_analyst=Görüntüle · human_agent=Görüntüle (kendi). UI yalnız görsel kapı;
// dinle/görüntüle/export + erişim-audit nihai yetki + işlem backend'de (calls:read). Tüm metin i18n'den (t()).
import type { CSSProperties } from "react";
import { getServerLocale } from "@/lib/i18n/server";
import { getCatalog, t, formatNumber, formatDate } from "@/lib/i18n";
import { PageHeader, Card, StatusPill, Alert, Table, Button, EmptyState } from "@/lib/ui/components";
import {
  getCallRecordsView,
  sortedCalls,
  countByDirection,
  countByOutcome,
  countByRecordingState,
  recordedCalls,
  recordingDisabledCalls,
  dualChannelCalls,
  transcriptCalls,
  redactionPendingCalls,
  redactedCalls,
  legalHoldCalls,
  retentionImminentCalls,
  legalHoldConflictCalls,
  unauditedCalls,
  openAttentionCount,
  directionTone,
  outcomeTone,
  recordingTone,
  transcriptTone,
  OUTCOME_ORDER,
  RECORDING_ORDER,
  type CallDirection,
  type CallOutcome,
  type RecordingState,
  type TranscriptState,
  type CallRecord,
} from "@/lib/tenant/recordings";

function Kpi({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: "danger" | "warning" | "success" }) {
  const valueColor =
    tone === "danger" ? "var(--rmc-danger-fg, #b42318)" : tone === "warning" ? "var(--rmc-warning-fg, #b54708)" : tone === "success" ? "var(--rmc-success-fg, #067647)" : "var(--rmc-text-primary)";
  return (
    <Card>
      <div style={{ color: "var(--rmc-text-muted)", fontSize: "var(--rmc-size-sm)" }}>{label}</div>
      <div style={{ fontSize: "var(--rmc-size-2xl)", fontWeight: 700, color: valueColor }}>{value}</div>
      {hint && <div style={{ color: "var(--rmc-text-muted)", fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-1)" }}>{hint}</div>}
    </Card>
  );
}

function grid(): CSSProperties {
  return { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "var(--rmc-space-4)", marginBottom: "var(--rmc-space-5)" };
}

const th: CSSProperties = { padding: "var(--rmc-space-2)", textAlign: "start" };
const td: CSSProperties = { padding: "var(--rmc-space-2)" };
const thEnd: CSSProperties = { padding: "var(--rmc-space-2)", textAlign: "end" };
const tdEnd: CSSProperties = { padding: "var(--rmc-space-2)", textAlign: "end" };
const rowBorder: CSSProperties = { borderBottom: "1px solid var(--rmc-border-subtle)" };
const muted: CSSProperties = { color: "var(--rmc-text-muted)" };

export default async function Page() {
  const locale = getServerLocale();
  const cat = getCatalog(locale);
  const k = (key: string, p?: Record<string, string | number>) => t(cat, `screen.a11.${key}`, p);
  const view = await getCallRecordsView();

  const calls = sortedCalls(view);
  const directionCounts = countByDirection(view.calls);
  const outcomeCounts = countByOutcome(view.calls);
  const recordingCounts = countByRecordingState(view.calls);
  const recorded = recordedCalls(view.calls);
  const recordingOff = recordingDisabledCalls(view.calls);
  const dualChannel = dualChannelCalls(view.calls);
  const transcripts = transcriptCalls(view.calls);
  const redactionPending = redactionPendingCalls(view.calls);
  const redacted = redactedCalls(view.calls);
  const legalHold = legalHoldCalls(view.calls);
  const retentionDue = retentionImminentCalls(view.calls);
  const legalConflict = legalHoldConflictCalls(view.calls);
  const unaudited = unauditedCalls(view.calls);
  const attention = openAttentionCount(view);

  const totalCalls = view.calls.length;

  const directionName = (d: CallDirection) => k(`direction.${d}`);
  const outcomeName = (o: CallOutcome) => k(`outcome.${o}`);
  const recordingName = (r: RecordingState) => k(`recording.${r}`);
  const transcriptName = (s: TranscriptState) => k(`transcript.${s}`);

  const durationFmt = (sec: number) => k("duration_fmt", { min: formatNumber(locale, Math.floor(sec / 60)), sec: formatNumber(locale, sec % 60) });

  const presentOutcomes = OUTCOME_ORDER.filter((o) => outcomeCounts[o] > 0);
  const presentRecordingStates = RECORDING_ORDER.filter((r) => recordingCounts[r] > 0);

  const retentionCell = (c: CallRecord) => {
    if (c.legalHold && c.retentionImminent) return <StatusPill tone="danger">{k("retention.conflict")}</StatusPill>;
    if (c.legalHold) return <StatusPill tone="info">{k("retention.held")}</StatusPill>;
    if (c.retentionImminent) return <StatusPill tone="warning">{k("retention.due")}</StatusPill>;
    return <span style={muted}>{k("retention.active")}</span>;
  };

  const recordRow = (c: CallRecord) => (
    <tr key={c.callRef} style={rowBorder}>
      <td style={td}>
        <code style={{ fontSize: "var(--rmc-size-xs)" }}>{c.callRef}</code>
        {c.own && <span style={{ color: "var(--rmc-text-muted)", fontSize: "var(--rmc-size-xs)" }}> · {k("own_badge")}</span>}
      </td>
      <td style={td}><StatusPill tone={directionTone(c.direction)}>{directionName(c.direction)}</StatusPill></td>
      <td style={td}><strong>{c.agentName}</strong> <code style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{c.agentRef}</code></td>
      <td style={td}><StatusPill tone={outcomeTone(c.outcome)}>{outcomeName(c.outcome)}</StatusPill></td>
      <td style={tdEnd}>{durationFmt(c.durationSec)}</td>
      <td style={td}>
        <StatusPill tone={recordingTone(c.recordingState)}>{recordingName(c.recordingState)}</StatusPill>
        {c.recordingState === "recorded" && c.channels > 0 && <span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}> · {k("channels_fmt", { n: formatNumber(locale, c.channels) })}</span>}
      </td>
      <td style={td}><StatusPill tone={transcriptTone(c.transcriptState)}>{transcriptName(c.transcriptState)}</StatusPill></td>
      <td style={td}>{retentionCell(c)}</td>
      <td style={td}>{c.accessAudited ? <StatusPill tone="success">{k("access.audited")}</StatusPill> : <StatusPill tone="danger">{k("access.unaudited")}</StatusPill>}</td>
    </tr>
  );

  return (
    <section data-screen="A-11">
      <PageHeader title={k("title")} description={k("subtitle")} code="A-11" />

      <div style={{ marginBottom: "var(--rmc-space-4)" }}>
        <Alert tone="info">{k("scope_note")}</Alert>
      </div>

      <p style={{ ...muted, fontSize: "var(--rmc-size-sm)", marginTop: 0 }}>
        {k("as_of", { time: formatDate(locale, new Date(view.generatedAt), { dateStyle: "medium", timeStyle: "short" }) })}
        {" · "}
        <span>{k("tenant")}: {view.tenantName}</span>
        {" · "}
        <span>{k("calls_label")}: {formatNumber(locale, totalCalls)}</span>
      </p>

      {/* Uyarılar */}
      {legalConflict.length > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="danger">{k("alert.legal_hold_conflict", { count: formatNumber(locale, legalConflict.length) })}</Alert>
        </div>
      )}
      {unaudited.length > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="danger">{k("alert.unaudited_access", { count: formatNumber(locale, unaudited.length) })}</Alert>
        </div>
      )}
      {redactionPending.length > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="warning">{k("alert.redaction_pending", { count: formatNumber(locale, redactionPending.length) })}</Alert>
        </div>
      )}
      {retentionDue.length > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="warning">{k("alert.retention_imminent", { count: formatNumber(locale, retentionDue.length) })}</Alert>
        </div>
      )}
      {recordingOff.length > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="info">{k("alert.recording_disabled", { count: formatNumber(locale, recordingOff.length) })}</Alert>
        </div>
      )}

      {/* Kayıt özeti */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", margin: "var(--rmc-space-2) 0 var(--rmc-space-3)" }}>
        <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: 0 }}>{k("section.summary")}</h2>
        <Button variant="secondary">{k("action.export")}</Button>
      </div>
      <div style={grid()}>
        <Kpi label={k("kpi.calls")} value={formatNumber(locale, totalCalls)} hint={k("kpi.calls_hint", { inbound: formatNumber(locale, directionCounts.inbound), outbound: formatNumber(locale, directionCounts.outbound) })} />
        <Kpi label={k("kpi.recorded")} value={k("ratio", { a: formatNumber(locale, recorded.length), b: formatNumber(locale, totalCalls) })} hint={k("kpi.recorded_hint", { disabled: formatNumber(locale, recordingOff.length) })} />
        <Kpi label={k("kpi.transcripts")} value={formatNumber(locale, transcripts.length)} hint={k("kpi.transcripts_hint", { pending: formatNumber(locale, redactionPending.length) })} tone={redactionPending.length > 0 ? "warning" : undefined} />
        <Kpi label={k("kpi.legal_hold")} value={formatNumber(locale, legalHold.length)} hint={k("kpi.legal_hold_hint")} />
        <Kpi label={k("kpi.retention_due")} value={formatNumber(locale, retentionDue.length)} hint={k("kpi.retention_due_hint")} tone={retentionDue.length > 0 ? "warning" : "success"} />
        <Kpi label={k("kpi.dual_channel")} value={formatNumber(locale, dualChannel.length)} hint={k("kpi.dual_channel_hint")} />
        <Kpi label={k("kpi.redaction")} value={k("ratio", { a: formatNumber(locale, redacted.length), b: formatNumber(locale, transcripts.length) })} hint={k("kpi.redaction_hint")} />
        <Kpi label={k("kpi.attention")} value={formatNumber(locale, attention)} hint={k("kpi.attention_hint")} tone={attention > 0 ? "warning" : "success"} />
      </div>

      {/* Çağrı kayıtları (arama/filtreleme) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.records")}</h2>
      <Card>
        {calls.length === 0 ? (
          <EmptyState message={k("no_records")} />
        ) : (
          <Table caption={k("records_caption")}>
            <thead>
              <tr style={rowBorder}>
                <th style={th}>{k("col.call")}</th>
                <th style={th}>{k("col.direction")}</th>
                <th style={th}>{k("col.agent")}</th>
                <th style={th}>{k("col.outcome")}</th>
                <th style={thEnd}>{k("col.duration")}</th>
                <th style={th}>{k("col.recording")}</th>
                <th style={th}>{k("col.transcript")}</th>
                <th style={th}>{k("col.retention")}</th>
                <th style={th}>{k("col.access")}</th>
              </tr>
            </thead>
            <tbody>{calls.map(recordRow)}</tbody>
          </Table>
        )}
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>{k("records_hint")}</p>

      {/* Sonuç dağılımı (FR-ANA-002/003) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.outcomes")}</h2>
      <Card>
        <Table caption={k("outcomes_caption")}>
          <thead>
            <tr style={rowBorder}>
              <th style={th}>{k("col.outcome")}</th>
              <th style={thEnd}>{k("col.count")}</th>
              <th style={thEnd}>{k("col.share")}</th>
            </tr>
          </thead>
          <tbody>
            {presentOutcomes.map((o) => (
              <tr key={o} style={rowBorder}>
                <td style={td}><StatusPill tone={outcomeTone(o)}>{outcomeName(o)}</StatusPill></td>
                <td style={tdEnd}>{formatNumber(locale, outcomeCounts[o])}</td>
                <td style={tdEnd}>{k("percent", { n: formatNumber(locale, totalCalls > 0 ? Math.round((outcomeCounts[o] / totalCalls) * 100) : 0) })}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>

      {/* Kayıt durumu dağılımı (FR-REC-001/002/003 — filtre boyutu) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.recording_states")}</h2>
      <Card>
        <Table caption={k("recording_states_caption")}>
          <thead>
            <tr style={rowBorder}>
              <th style={th}>{k("col.recording")}</th>
              <th style={thEnd}>{k("col.count")}</th>
              <th style={thEnd}>{k("col.share")}</th>
            </tr>
          </thead>
          <tbody>
            {presentRecordingStates.map((r) => (
              <tr key={r} style={rowBorder}>
                <td style={td}><StatusPill tone={recordingTone(r)}>{recordingName(r)}</StatusPill></td>
                <td style={tdEnd}>{formatNumber(locale, recordingCounts[r])}</td>
                <td style={tdEnd}>{k("percent", { n: formatNumber(locale, totalCalls > 0 ? Math.round((recordingCounts[r] / totalCalls) * 100) : 0) })}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>{k("recording_states_hint")}</p>

      {/* Saklama & yasal tutma sağlığı (FR-REC-006/007/010) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.retention")}</h2>
      <Card>
        <Table caption={k("retention_caption")}>
          <thead>
            <tr style={rowBorder}>
              <th style={th}>{k("col.control")}</th>
              <th style={th}>{k("col.purpose")}</th>
              <th style={thEnd}>{k("col.value")}</th>
            </tr>
          </thead>
          <tbody>
            <tr style={rowBorder}>
              <td style={td}>{k("retention.legal_hold")}</td>
              <td style={td}><span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{k("retention.legal_hold_desc")}</span></td>
              <td style={tdEnd}>{formatNumber(locale, legalHold.length)}</td>
            </tr>
            <tr style={rowBorder}>
              <td style={td}>{k("retention.imminent")}</td>
              <td style={td}><span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{k("retention.imminent_desc")}</span></td>
              <td style={tdEnd}>{retentionDue.length > 0 ? <span style={{ color: "var(--rmc-warning-fg, #b54708)" }}>{formatNumber(locale, retentionDue.length)}</span> : formatNumber(locale, 0)}</td>
            </tr>
            <tr style={rowBorder}>
              <td style={td}>{k("retention.conflict_row")}</td>
              <td style={td}><span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{k("retention.conflict_desc")}</span></td>
              <td style={tdEnd}>{legalConflict.length > 0 ? <span style={{ color: "var(--rmc-danger-fg, #b42318)" }}>{formatNumber(locale, legalConflict.length)}</span> : formatNumber(locale, 0)}</td>
            </tr>
          </tbody>
        </Table>
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>{k("retention_hint")}</p>

      {/* Erişim & redaction sağlığı (FR-REC-004/005/008/009) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.access")}</h2>
      <Card>
        <Table caption={k("access_caption")}>
          <thead>
            <tr style={rowBorder}>
              <th style={th}>{k("col.control")}</th>
              <th style={th}>{k("col.purpose")}</th>
              <th style={thEnd}>{k("col.value")}</th>
            </tr>
          </thead>
          <tbody>
            <tr style={rowBorder}>
              <td style={td}>{k("access.audit")}</td>
              <td style={td}><span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{k("access.audit_desc")}</span></td>
              <td style={tdEnd}>{unaudited.length > 0 ? <span style={{ color: "var(--rmc-danger-fg, #b42318)" }}>{k("ratio", { a: formatNumber(locale, totalCalls - unaudited.length), b: formatNumber(locale, totalCalls) })}</span> : k("ratio", { a: formatNumber(locale, totalCalls), b: formatNumber(locale, totalCalls) })}</td>
            </tr>
            <tr style={rowBorder}>
              <td style={td}>{k("access.redaction")}</td>
              <td style={td}><span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{k("access.redaction_desc")}</span></td>
              <td style={tdEnd}>{redactionPending.length > 0 ? <span style={{ color: "var(--rmc-warning-fg, #b54708)" }}>{k("ratio", { a: formatNumber(locale, redacted.length), b: formatNumber(locale, transcripts.length) })}</span> : k("ratio", { a: formatNumber(locale, redacted.length), b: formatNumber(locale, transcripts.length) })}</td>
            </tr>
            <tr style={rowBorder}>
              <td style={td}>{k("access.scrub")}</td>
              <td style={td}><span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{k("access.scrub_desc")}</span></td>
              <td style={tdEnd}>{k("access.scrub_state")}</td>
            </tr>
          </tbody>
        </Table>
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>{k("access_hint")}</p>
    </section>
  );
}
