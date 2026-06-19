// WBS 13.4.12 — L2 ekranı A-12 "Çağrı Detayı / Transkript & Timeline" (gerçek içerik; 13.1.1 iskeletinin yerini alır).
//
// İÇERİK (BRD §17.5 A-12 — "Çağrı zaman çizelgesi, transkript, olaylar"): TEK çağrının DETAYI. ÇAĞRI KÜNYESİ
// (yön · agent · sonuç · süre · kayıt durumu FR-REC-001/002/003 · transkript FR-REC-004 · saklama FR-REC-006/007 ·
// erişim FR-REC-009), ÇAĞRI ÖZETİ (8 KPI: süre · tur · olay · araç çağrısı · barge-in · düşük-güven · maskeli ·
// erişim), OLAY ZAMAN ÇİZELGESİ (DB §23 call_event — BRD §15 zaman damgası + SAD §6.1: call_connected/greeting/
// recording/kb_lookup/tool_invoked/barge_in/transfer/voicemail/call_ended — yalnız YAPISAL olay), TRANSKRİPT
// (DB §21 transcript_segment — speaker · offset · REDACTION'LI metin · güven; FR-REC-004/005) ve ERİŞİM &
// REDACTION SAĞLIĞI (FR-REC-004/005/008/009). Transkript İÇERİĞİ yalnız redaction TAMAM (FR-REC-004) + erişim
// AUDIT'li (FR-REC-009) ise gösterilir; redaction beklemede ya da auditsiz ise içerik GİZLENİR (kapı). Ham ses
// BYTE'ı / ham transkript blob'u / ham numara (e164) / müşteri PII / kart-OTP / nesne-depo URI'si GÖSTERİLMEZ;
// PII yalnız MASK_TOKEN ([•••]) olarak görünür (redaction panel görüntülemelerinde de uygulanır — BRD §17.7).
// Kayıt dinleme derin aksiyondur (görsel kapı; ham ses/URI yok — API §6 + WBS 11.6 audit'li). TENANT-SCOPE
// (FR-TEN-002): yalnız oturum açan tenant (middleware 13.1.2 + RLS). RBAC (BRD §17.6 A-12 satırı):
// operations_manager=Yönet · conversation_designer=Görüntüle · qa_analyst=Yönet · human_agent=Görüntüle (kendi).
// UI yalnız görsel kapı; dinle/görüntüle/export + erişim-audit nihai yetki + işlem backend'de (calls:read).
// Tüm metin i18n'den (t()); transkript İÇERİĞİ ise ÇAĞRI VERİSİDİR (agent adı gibi — locale-agnostik, redaction'lı).
import type { CSSProperties } from "react";
import { getServerLocale } from "@/lib/i18n/server";
import { getCatalog, t, formatNumber, formatDate } from "@/lib/i18n";
import { PageHeader, Card, StatusPill, Alert, Table, Button, EmptyState } from "@/lib/ui/components";
import {
  getCallDetailView,
  sortedEvents,
  sortedTurns,
  countBySpeaker,
  toolEvents,
  bargeInEvents,
  transferEvents,
  maskedTurns,
  lowConfidenceTurns,
  transcriptViewable,
  redactionPending,
  transcriptAbsent,
  accessBlocked,
  recordingPlayable,
  directionTone,
  outcomeTone,
  recordingTone,
  transcriptTone,
  speakerTone,
  eventTone,
  type CallDirection,
  type CallOutcome,
  type RecordingState,
  type TranscriptState,
  type Speaker,
  type TimelineEventType,
} from "@/lib/tenant/call-detail";

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
  const k = (key: string, p?: Record<string, string | number>) => t(cat, `screen.a12.${key}`, p);
  const view = await getCallDetailView();
  const call = view.call;

  const events = sortedEvents(call);
  const turns = sortedTurns(call);
  const speakerCounts = countBySpeaker(call.turns);
  const tools = toolEvents(call.events);
  const barges = bargeInEvents(call.events);
  const transfers = transferEvents(call.events);
  const masked = maskedTurns(call.turns);
  const lowConf = lowConfidenceTurns(call.turns);
  const viewable = transcriptViewable(call);
  const redactionWait = redactionPending(call);
  const absent = transcriptAbsent(call);
  const blocked = accessBlocked(call);
  const playable = recordingPlayable(call);

  const directionName = (d: CallDirection) => k(`direction.${d}`);
  const outcomeName = (o: CallOutcome) => k(`outcome.${o}`);
  const recordingName = (r: RecordingState) => k(`recording.${r}`);
  const transcriptName = (s: TranscriptState) => k(`transcript.${s}`);
  const speakerName = (s: Speaker) => k(`speaker.${s}`);
  const eventName = (e: TimelineEventType) => k(`event.${e}`);

  const durationFmt = (sec: number) => k("duration_fmt", { min: formatNumber(locale, Math.floor(sec / 60)), sec: formatNumber(locale, sec % 60) });
  const offsetFmt = (ms: number) => {
    const total = Math.floor(ms / 1000);
    return k("offset_fmt", { min: formatNumber(locale, Math.floor(total / 60)), sec: formatNumber(locale, total % 60) });
  };
  const confFmt = (c: number) => k("percent", { n: formatNumber(locale, Math.round(c * 100)) });

  const retentionCell = () => {
    if (call.legalHold && call.retentionImminent) return <StatusPill tone="danger">{k("retention.conflict")}</StatusPill>;
    if (call.legalHold) return <StatusPill tone="info">{k("retention.held")}</StatusPill>;
    if (call.retentionImminent) return <StatusPill tone="warning">{k("retention.due")}</StatusPill>;
    return <span style={muted}>{k("retention.active")}</span>;
  };

  return (
    <section data-screen="A-12">
      <PageHeader title={k("title")} description={k("subtitle")} code="A-12" />

      <div style={{ marginBottom: "var(--rmc-space-4)" }}>
        <Alert tone="info">{k("scope_note")}</Alert>
      </div>

      <p style={{ ...muted, fontSize: "var(--rmc-size-sm)", marginTop: 0 }}>
        {k("as_of", { time: formatDate(locale, new Date(view.generatedAt), { dateStyle: "medium", timeStyle: "short" }) })}
        {" · "}
        <span>{k("tenant")}: {view.tenantName}</span>
        {" · "}
        <span>{k("call_label")}: <code style={{ fontSize: "var(--rmc-size-xs)" }}>{call.callRef}</code></span>
        {call.own && <span> · {k("own_badge")}</span>}
      </p>

      {/* Uyarılar */}
      {blocked && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="danger">{k("alert.access_blocked")}</Alert>
        </div>
      )}
      {redactionWait && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="warning">{k("alert.redaction_pending")}</Alert>
        </div>
      )}
      {call.recordingState === "disabled" && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="info">{k("alert.recording_disabled")}</Alert>
        </div>
      )}
      {lowConf.length > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="info">{k("alert.low_confidence", { count: formatNumber(locale, lowConf.length) })}</Alert>
        </div>
      )}

      {/* Çağrı özeti (KPI) */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", margin: "var(--rmc-space-2) 0 var(--rmc-space-3)" }}>
        <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: 0 }}>{k("section.summary")}</h2>
        <Button variant="secondary">{k("action.export")}</Button>
      </div>
      <div style={grid()}>
        <Kpi label={k("kpi.duration")} value={durationFmt(call.durationSec)} hint={k("kpi.duration_hint", { outcome: outcomeName(call.outcome) })} />
        <Kpi label={k("kpi.turns")} value={formatNumber(locale, call.turns.length)} hint={k("kpi.turns_hint", { caller: formatNumber(locale, speakerCounts.caller), agent: formatNumber(locale, speakerCounts.agent) })} />
        <Kpi label={k("kpi.events")} value={formatNumber(locale, call.events.length)} hint={k("kpi.events_hint")} />
        <Kpi label={k("kpi.tools")} value={formatNumber(locale, tools.length)} hint={k("kpi.tools_hint")} />
        <Kpi label={k("kpi.barge_in")} value={formatNumber(locale, barges.length)} hint={k("kpi.barge_in_hint")} />
        <Kpi label={k("kpi.low_confidence")} value={formatNumber(locale, lowConf.length)} hint={k("kpi.low_confidence_hint")} tone={lowConf.length > 0 ? "warning" : "success"} />
        <Kpi label={k("kpi.masked")} value={formatNumber(locale, masked.length)} hint={k("kpi.masked_hint")} />
        <Kpi label={k("kpi.access")} value={call.accessAudited ? k("access.audited") : k("access.unaudited")} hint={k("kpi.access_hint")} tone={call.accessAudited ? "success" : "danger"} />
      </div>

      {/* Çağrı künyesi (META) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.meta")}</h2>
      <Card>
        <Table caption={k("meta_caption")}>
          <thead>
            <tr style={rowBorder}>
              <th style={th}>{k("col.field")}</th>
              <th style={th}>{k("col.value")}</th>
            </tr>
          </thead>
          <tbody>
            <tr style={rowBorder}>
              <td style={td}>{k("meta.direction")}</td>
              <td style={td}><StatusPill tone={directionTone(call.direction)}>{directionName(call.direction)}</StatusPill></td>
            </tr>
            <tr style={rowBorder}>
              <td style={td}>{k("meta.agent")}</td>
              <td style={td}><strong>{call.agentName}</strong> <code style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{call.agentRef}</code></td>
            </tr>
            <tr style={rowBorder}>
              <td style={td}>{k("meta.outcome")}</td>
              <td style={td}><StatusPill tone={outcomeTone(call.outcome)}>{outcomeName(call.outcome)}</StatusPill></td>
            </tr>
            <tr style={rowBorder}>
              <td style={td}>{k("meta.duration")}</td>
              <td style={td}>{durationFmt(call.durationSec)}</td>
            </tr>
            <tr style={rowBorder}>
              <td style={td}>{k("meta.recording")}</td>
              <td style={td}>
                <StatusPill tone={recordingTone(call.recordingState)}>{recordingName(call.recordingState)}</StatusPill>
                {call.recordingState === "recorded" && call.channels > 0 && <span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}> · {k("channels_fmt", { n: formatNumber(locale, call.channels) })}</span>}
                {playable && <span style={{ marginInlineStart: "var(--rmc-space-2)" }}><Button variant="secondary">{k("action.play")}</Button></span>}
              </td>
            </tr>
            <tr style={rowBorder}>
              <td style={td}>{k("meta.transcript")}</td>
              <td style={td}><StatusPill tone={transcriptTone(call.transcriptState)}>{transcriptName(call.transcriptState)}</StatusPill></td>
            </tr>
            <tr style={rowBorder}>
              <td style={td}>{k("meta.retention")}</td>
              <td style={td}>{retentionCell()}</td>
            </tr>
            <tr style={rowBorder}>
              <td style={td}>{k("meta.access")}</td>
              <td style={td}>{call.accessAudited ? <StatusPill tone="success">{k("access.audited")}</StatusPill> : <StatusPill tone="danger">{k("access.unaudited")}</StatusPill>}</td>
            </tr>
          </tbody>
        </Table>
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>{k("meta_hint")}</p>

      {/* Olay zaman çizelgesi (DB §23 + BRD §15 + SAD §6.1) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.timeline")}</h2>
      <Card>
        {events.length === 0 ? (
          <EmptyState message={k("no_events")} />
        ) : (
          <Table caption={k("timeline_caption")}>
            <thead>
              <tr style={rowBorder}>
                <th style={thEnd}>{k("col.time")}</th>
                <th style={th}>{k("col.event")}</th>
                <th style={th}>{k("col.detail")}</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => (
                <tr key={e.eventRef} style={rowBorder}>
                  <td style={tdEnd}><code style={{ fontSize: "var(--rmc-size-xs)" }}>{offsetFmt(e.offsetMs)}</code></td>
                  <td style={td}><StatusPill tone={eventTone(e.type)}>{eventName(e.type)}</StatusPill></td>
                  <td style={td}>{e.detail ? <code style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{e.detail}</code> : <span style={muted}>—</span>}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>{k("timeline_hint")}</p>

      {/* Transkript (DB §21 — yalnız redaction tamam + erişim audit'li ise içerik; aksi halde kapı) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.transcript")}</h2>
      <Card>
        {blocked ? (
          <EmptyState message={k("transcript_gated.access")} />
        ) : redactionWait ? (
          <EmptyState message={k("transcript_gated.redaction")} />
        ) : absent ? (
          <EmptyState message={k("transcript_gated.absent")} />
        ) : !viewable || turns.length === 0 ? (
          <EmptyState message={k("no_turns")} />
        ) : (
          <Table caption={k("transcript_caption")}>
            <thead>
              <tr style={rowBorder}>
                <th style={thEnd}>{k("col.time")}</th>
                <th style={th}>{k("col.speaker")}</th>
                <th style={th}>{k("col.utterance")}</th>
                <th style={thEnd}>{k("col.confidence")}</th>
              </tr>
            </thead>
            <tbody>
              {turns.map((tn) => (
                <tr key={tn.turnRef} style={rowBorder}>
                  <td style={tdEnd}><code style={{ fontSize: "var(--rmc-size-xs)" }}>{offsetFmt(tn.offsetMs)}</code></td>
                  <td style={td}><StatusPill tone={speakerTone(tn.speaker)}>{speakerName(tn.speaker)}</StatusPill></td>
                  <td style={td}>
                    {tn.text}
                    {tn.redacted && <span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}> · {k("masked_badge")}</span>}
                  </td>
                  <td style={tdEnd}>{tn.confidence < 0.75 ? <span style={{ color: "var(--rmc-warning-fg, #b54708)" }}>{confFmt(tn.confidence)}</span> : confFmt(tn.confidence)}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>{k("transcript_hint")}</p>

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
              <td style={tdEnd}>{call.accessAudited ? <StatusPill tone="success">{k("access.audited")}</StatusPill> : <span style={{ color: "var(--rmc-danger-fg, #b42318)" }}>{k("access.unaudited")}</span>}</td>
            </tr>
            <tr style={rowBorder}>
              <td style={td}>{k("access.redaction")}</td>
              <td style={td}><span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{k("access.redaction_desc")}</span></td>
              <td style={tdEnd}>{redactionWait ? <span style={{ color: "var(--rmc-warning-fg, #b54708)" }}>{transcriptName(call.transcriptState)}</span> : transcriptName(call.transcriptState)}</td>
            </tr>
            <tr style={rowBorder}>
              <td style={td}>{k("access.scrub")}</td>
              <td style={td}><span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{k("access.scrub_desc")}</span></td>
              <td style={tdEnd}>{k("access.masked_fmt", { n: formatNumber(locale, masked.length) })}</td>
            </tr>
            <tr style={rowBorder}>
              <td style={td}>{k("access.recording")}</td>
              <td style={td}><span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{k("access.recording_desc")}</span></td>
              <td style={tdEnd}>{k("access.recording_gate")}</td>
            </tr>
            <tr style={rowBorder}>
              <td style={td}>{k("access.transfer")}</td>
              <td style={td}><span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{k("access.transfer_desc")}</span></td>
              <td style={tdEnd}>{formatNumber(locale, transfers.length)}</td>
            </tr>
          </tbody>
        </Table>
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>{k("access_hint")}</p>
    </section>
  );
}
