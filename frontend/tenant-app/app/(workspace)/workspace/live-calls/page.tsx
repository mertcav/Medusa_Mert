// WBS 13.4.2 — L2 ekranı A-02 "Canlı Çağrılar" (gerçek içerik; 13.1.1 iskeletinin yerini alır).
//
// İÇERİK (BRD §17.5 A-02 "Aktif çağrı izleme" / FR-ANA-012): tenant'ın O ANDA AKTİF çağrılarının GERÇEK
// ZAMANLI operasyon görünümü. ÖZET (KPI), DURUM dağılımı (çağrı + tur durumu — SAD §6.1), DİKKAT GEREKTİREN
// çağrılar (kritik flag FR-ANA-008 + aktarım talebi + gecikme ihlali NFR 10.1) ve AKTİF ÇAĞRI TABLOSU
// (süre/taraf/yön/agent/durum/tur/canlı gecikme/duygu). GERÇEK ZAMANLILIK (FR-ANA-012/SR-ANA-012): veri
// yaşı ≤60 sn; bayat veri işaretlenir; panel ≤60 sn yenilenir. TENANT-SCOPE (FR-TEN-002): yalnız oturum açan
// tenant'ın aktif çağrıları (middleware 13.1.2 + RLS DB §6.3). HİJYEN (BRD §17.7 + §17.6 PII redaction):
// aggregate liste yalnız OPERASYONEL META — ham transkript/ses kaydı/ham numara/müşteri PII gömülmez; taraf
// MASKELENMİŞ etiketle (canlı dinleme/transkript → A-12, görsel kapı). GÜVENLİK (NFR 10.6): sır konmaz.
// RBAC (BRD §17.6): operations_manager=Yönet · conversation_designer=— · qa_analyst=Görüntüle · human_agent=
// Görüntüle (kendi). UI yalnız görsel kapı; izleme/dinleme/aktarma nihai yetki + işlem backend'de (12.2.x,
// SAD §14.4.1 A8). Tüm kullanıcı-görünür metin i18n katalogundan (t()).
import type { CSSProperties } from "react";
import { getServerLocale } from "@/lib/i18n/server";
import { getCatalog, t, formatNumber, formatDate } from "@/lib/i18n";
import { PageHeader, Card, StatusPill, Alert, Table, Button, EmptyState } from "@/lib/ui/components";
import {
  getLiveCalls,
  countByState,
  countByDirection,
  flaggedCalls,
  handoffPending,
  latencyBreaches,
  attentionCalls,
  concurrencyUtilPct,
  staleSnapshot,
  openAttentionCount,
  stateTone,
  turnTone,
  directionTone,
  sentimentTone,
  latencyTone,
  handoffTone,
  flagTone,
  utilTone,
  FRESHNESS_BUDGET_SEC,
  LIVE_LATENCY_BUDGET_MS,
  type CallState,
  type CallDirection,
  type TurnState,
  type CallSentiment,
  type LiveCall,
} from "@/lib/tenant/live-calls";

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

const STATE_ORDER: CallState[] = ["ringing", "in_progress", "on_hold", "transferring", "wrapup"];

export default async function Page() {
  const locale = getServerLocale();
  const cat = getCatalog(locale);
  const k = (key: string, p?: Record<string, string | number>) => t(cat, `screen.a02.${key}`, p);
  const snap = await getLiveCalls();
  const { calls, capacity } = snap;

  const byState = countByState(calls);
  const byDir = countByDirection(calls);
  const flagged = flaggedCalls(calls);
  const handoff = handoffPending(calls);
  const breaches = new Set(latencyBreaches(calls).map((c) => c.id));
  const attention = attentionCalls(calls);
  const util = concurrencyUtilPct(snap);
  const stale = staleSnapshot(snap);
  const openCount = openAttentionCount(snap);

  const stateName = (s: CallState) => k(`state.${s}`);
  const turnName = (t2: TurnState) => k(`turn.${t2}`);
  const dirName = (d: CallDirection) => k(`direction.${d}`);
  const sentimentName = (s: CallSentiment) => k(`sentiment.${s}`);
  const dt = (iso: string) => formatDate(locale, new Date(iso), { dateStyle: "short", timeStyle: "short" });
  const dur = (sec: number) => k("unit.sec", { n: formatNumber(locale, sec) });
  const ms = (n: number) => k("unit.ms", { n: formatNumber(locale, n) });
  const utilKpiTone = utilTone(util);

  const callRow = (c: LiveCall) => (
    <tr key={c.id} style={rowBorder}>
      <td style={td}>{dt(c.startedAt)}<br /><span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{dur(c.durationSec)}</span></td>
      <td style={td}><code>{c.maskedParty}</code></td>
      <td style={td}><StatusPill tone={directionTone(c.direction)}>{dirName(c.direction)}</StatusPill></td>
      <td style={td}><code style={muted}>{c.agentRef}</code> {c.agentName}</td>
      <td style={td}><StatusPill tone={stateTone(c.state)}>{stateName(c.state)}</StatusPill> <StatusPill tone={turnTone(c.turnState)}>{turnName(c.turnState)}</StatusPill></td>
      <td style={tdEnd}>
        <StatusPill tone={latencyTone(c.liveLatencyMs)}>{ms(c.liveLatencyMs)}</StatusPill>
        <br />
        <span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{k("latency_breakdown", { stt: formatNumber(locale, c.sttMs), llm: formatNumber(locale, c.llmMs), tts: formatNumber(locale, c.ttsMs) })}</span>
      </td>
      <td style={td}><StatusPill tone={sentimentTone(c.sentiment)}>{sentimentName(c.sentiment)}</StatusPill></td>
      <td style={td}>
        {c.flagged && <StatusPill tone={flagTone(true)}>{k("flag.flagged")}</StatusPill>}
        {c.handoffRequested && <> <StatusPill tone={handoffTone(true)}>{k("flag.handoff")}</StatusPill></>}
        {breaches.has(c.id) && <> <StatusPill tone="danger">{k("flag.latency")}</StatusPill></>}
        {!c.flagged && !c.handoffRequested && !breaches.has(c.id) && <span style={muted}>{k("dash")}</span>}
      </td>
    </tr>
  );

  return (
    <section data-screen="A-02">
      <PageHeader title={k("title")} description={k("subtitle")} code="A-02" />

      <div style={{ marginBottom: "var(--rmc-space-4)" }}>
        <Alert tone="info">{k("scope_note")}</Alert>
      </div>

      <p style={{ ...muted, fontSize: "var(--rmc-size-sm)", marginTop: 0 }}>
        {k("as_of", { time: formatDate(locale, new Date(snap.generatedAt), { dateStyle: "medium", timeStyle: "short" }) })}
        {" · "}
        <span>{k("data_age", { n: formatNumber(locale, snap.dataAgeSeconds) })}</span>
        {" · "}
        <span>{k("refresh", { n: formatNumber(locale, snap.refreshIntervalSec) })}</span>
        {" · "}
        <span>{k("tenant")}: {snap.tenantName}</span>
      </p>

      {/* Uyarılar */}
      {stale && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="danger">{k("alert.stale", { n: formatNumber(locale, FRESHNESS_BUDGET_SEC) })}</Alert>
        </div>
      )}
      {breaches.size > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="warning">{k("alert.latency", { count: formatNumber(locale, breaches.size) })}</Alert>
        </div>
      )}
      {flagged.length > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="warning">{k("alert.flagged", { count: formatNumber(locale, flagged.length) })}</Alert>
        </div>
      )}
      {handoff.length > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="info">{k("alert.handoff", { count: formatNumber(locale, handoff.length) })}</Alert>
        </div>
      )}
      {util >= 90 && (
        <div style={{ margin: "var(--rmc-space-2) 0 var(--rmc-space-4)" }}>
          <Alert tone="danger">{k("alert.capacity", { pct: formatNumber(locale, util) })}</Alert>
        </div>
      )}

      {/* Özet */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", marginBottom: "var(--rmc-space-3)" }}>{k("section.summary")}</h2>
      <div style={grid()}>
        <Kpi label={k("kpi.active")} value={formatNumber(locale, capacity.concurrentActive)} hint={k("kpi.active_hint", { shown: formatNumber(locale, calls.length) })} />
        <Kpi label={k("kpi.concurrency")} value={`${formatNumber(locale, util)}%`} hint={k("kpi.concurrency_hint", { limit: formatNumber(locale, capacity.concurrentLimit) })} tone={utilKpiTone === "neutral" ? undefined : (utilKpiTone as "danger" | "warning" | "success")} />
        <Kpi label={k("kpi.inbound")} value={formatNumber(locale, byDir["inbound"] ?? 0)} hint={k("kpi.inbound_hint", { out: formatNumber(locale, byDir["outbound"] ?? 0) })} />
        <Kpi label={k("kpi.flagged")} value={formatNumber(locale, flagged.length)} hint={k("kpi.flagged_hint")} tone={flagged.length > 0 ? "danger" : "success"} />
        <Kpi label={k("kpi.handoff")} value={formatNumber(locale, handoff.length)} hint={k("kpi.handoff_hint")} tone={handoff.length > 0 ? "warning" : "success"} />
        <Kpi label={k("kpi.latency")} value={formatNumber(locale, breaches.size)} hint={k("kpi.latency_hint", { budget: formatNumber(locale, LIVE_LATENCY_BUDGET_MS) })} tone={breaches.size > 0 ? "warning" : "success"} />
        <Kpi label={k("kpi.freshness")} value={stale ? k("kpi.fresh_stale") : k("kpi.fresh_ok")} hint={k("kpi.freshness_hint")} tone={stale ? "danger" : "success"} />
        <Kpi label={k("kpi.attention")} value={formatNumber(locale, openCount)} hint={k("kpi.attention_hint")} tone={openCount > 0 ? "warning" : "success"} />
      </div>

      {/* Durum dağılımı */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.states")}</h2>
      <Card>
        <Table caption={k("states_caption")}>
          <thead>
            <tr style={rowBorder}>
              <th style={th}>{k("col.state")}</th>
              <th style={thEnd}>{k("col.count")}</th>
            </tr>
          </thead>
          <tbody>
            {STATE_ORDER.map((s) => (
              <tr key={s} style={rowBorder}>
                <td style={td}><StatusPill tone={stateTone(s)}>{stateName(s)}</StatusPill></td>
                <td style={tdEnd}>{formatNumber(locale, byState[s] ?? 0)}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-2)" }}>{k("states_hint")}</p>

      {/* Dikkat gerektiren çağrılar */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.attention")}</h2>
      <Card>
        {attention.length === 0 ? (
          <EmptyState message={k("no_attention")} />
        ) : (
          <Table caption={k("attention_caption")}>
            <thead>
              <tr style={rowBorder}>
                <th style={th}>{k("col.started")}</th>
                <th style={th}>{k("col.party")}</th>
                <th style={th}>{k("col.direction")}</th>
                <th style={th}>{k("col.agent")}</th>
                <th style={th}>{k("col.state")}</th>
                <th style={thEnd}>{k("col.latency")}</th>
                <th style={th}>{k("col.sentiment")}</th>
                <th style={th}>{k("col.flags")}</th>
              </tr>
            </thead>
            <tbody>{attention.map(callRow)}</tbody>
          </Table>
        )}
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-2)" }}>{k("attention_hint")}</p>

      {/* Aktif çağrı tablosu */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>
        <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: 0 }}>{k("section.active")}</h2>
        <Button variant="secondary">{k("action.refresh")}</Button>
      </div>
      <Card>
        {calls.length === 0 ? (
          <EmptyState message={k("no_calls")} />
        ) : (
          <Table caption={k("active_caption")}>
            <thead>
              <tr style={rowBorder}>
                <th style={th}>{k("col.started")}</th>
                <th style={th}>{k("col.party")}</th>
                <th style={th}>{k("col.direction")}</th>
                <th style={th}>{k("col.agent")}</th>
                <th style={th}>{k("col.state")}</th>
                <th style={thEnd}>{k("col.latency")}</th>
                <th style={th}>{k("col.sentiment")}</th>
                <th style={th}>{k("col.flags")}</th>
              </tr>
            </thead>
            <tbody>{calls.map(callRow)}</tbody>
          </Table>
        )}
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>{k("active_hint")}</p>
    </section>
  );
}
