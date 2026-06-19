// WBS 13.4.14 — L2 ekranı A-14 "Analytics & Raporlama" (gerçek içerik; 13.1.1 iskeletinin yerini alır).
//
// İÇERİK (BRD §17.5 A-14 — "Containment, CSAT, AHT vb."): bir DÖNEM boyunca ÇOK ÇAĞRIYI TOPLULAŞTIRAN operasyonel
// analitik panosu. ÖZET KPI'lar (toplam çağrı · containment · transfer · CSAT · AHT · toplam yanıt gecikmesi P95),
// SONUÇ DAĞILIMI (FR-ANA-002 outcome + FR-ANA-003 containment & transfer oranı), KONUŞMA SÜRELERİ (FR-ANA-005 —
// kullanıcı vs agent), YANIT GECİKMESİ (FR-ANA-006 — STT/LLM/TTS ve toplam AYRI), ZAMAN SERİSİ / TREND (FR-ANA-011
// dashboard) ve AGENT SÜRÜMÜ KARŞILAŞTIRMASI (FR-ANA-010). A-14 yalnız TOPLULAŞTIRILMIŞ metrik gösterir (Tier A);
// tek çağrı içeriği/transkript/PII TAŞIMAZ → break-glass gerekmez. Ham ses/ham transkript/transkript metni/ham
// numara (e164)/müşteri PII/kart-OTP/nesne-depo URI'si GÖSTERİLMEZ; ham veri export (FR-ANA-011) görsel kapıdır,
// nihai export + redaction + audit backend'de (analytics:read — API §8.1 GET /analytics/{report}). TENANT-SCOPE
// (FR-TEN-002): yalnız oturum açan tenant (middleware 13.1.2 + RLS). RBAC (BRD §17.6 A-14): operations_manager=Yönet ·
// conversation_designer=Görüntüle · qa_analyst=Görüntüle · human_agent=— (erişim yok). Tüm ETİKET metni i18n'den (t());
// metrik/sayı/tarih ise VERİDİR (locale-duyarlı biçimlenir).
import type { CSSProperties } from "react";
import { getServerLocale } from "@/lib/i18n/server";
import { getCatalog, t, formatNumber, formatDate } from "@/lib/i18n";
import { PageHeader, Card, StatusPill, Alert, Table, Button, EmptyState } from "@/lib/ui/components";
import {
  getAnalyticsView,
  sortedOutcomes,
  sortedLatency,
  totalCalls,
  outcomeCount,
  outcomeRate,
  containmentRate,
  transferRate,
  abandonRate,
  talkTotalSec,
  agentTalkRatio,
  avgCallSec,
  ahtConsistent,
  latencyStage,
  latencyWithinBudget,
  seriesCalls,
  seriesContained,
  dayContainmentRate,
  seriesTrend,
  currentVersion,
  weightedAvgContainment,
  versionContainmentDelta,
  ratioBand,
  ratioTone,
  lowerBetterTone,
  bandTone,
  outcomeTone,
  trendTone,
  type CallOutcome,
  type LatencyStage,
  type TrendDir,
} from "@/lib/tenant/analytics";

function Kpi({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: "danger" | "warning" | "success" | "info" }) {
  const valueColor =
    tone === "danger" ? "var(--rmc-danger-fg, #b42318)" : tone === "warning" ? "var(--rmc-warning-fg, #b54708)" : tone === "success" ? "var(--rmc-success-fg, #067647)" : tone === "info" ? "var(--rmc-info-fg, #175cd3)" : "var(--rmc-text-primary)";
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

// Ton birleşimini KPI/StatusPill solid tonuna indir (neutral/info → success düş; tip daraltma).
type Solid = "danger" | "warning" | "success";
function solid(tone: ReturnType<typeof ratioTone>): Solid {
  return tone === "neutral" || tone === "info" ? "success" : tone;
}

export default async function Page() {
  const locale = getServerLocale();
  const cat = getCatalog(locale);
  const k = (key: string, p?: Record<string, string | number>) => t(cat, `screen.a14.${key}`, p);
  const view = await getAnalyticsView();
  const tg = view.targets;

  const total = totalCalls(view);
  const outcomes = sortedOutcomes(view);
  const latency = sortedLatency(view);
  const contain = containmentRate(view);
  const transfer = transferRate(view);
  const abandon = abandonRate(view);
  const totalLat = latencyStage(view, "total");
  const withinBudget = latencyWithinBudget(view, tg.latencyP95Ms);
  const ahtOk = ahtConsistent(view);
  const sCalls = seriesCalls(view);
  const sContained = seriesContained(view);
  const containTrend = seriesTrend(view, "contained");
  const csatTrend = seriesTrend(view, "csat");
  const volTrend = seriesTrend(view, "calls");
  const cur = currentVersion(view);
  const avgContain = weightedAvgContainment(view.versions);
  const agentTalk = agentTalkRatio(view.talk);

  const outcomeName = (o: CallOutcome) => k(`outcome.${o}`);
  const stageName = (s: LatencyStage) => k(`stage.${s}`);
  const trendName = (d: TrendDir) => k(`trend.${d}`);
  const trendArrow = (d: TrendDir) => (d === "up" ? "▲" : d === "down" ? "▼" : "▬");

  const pctFmt = (n: number) => k("percent", { n: formatNumber(locale, Math.round(n * 100)) });
  const pct1Fmt = (n: number) => k("percent", { n: formatNumber(locale, Math.round(n * 1000) / 10) });
  const numFmt = (n: number) => formatNumber(locale, n);
  const secFmt = (s: number) => k("duration_fmt", { min: numFmt(Math.floor(s / 60)), sec: numFmt(s % 60) });
  const msFmt = (ms: number) => k("ms", { n: numFmt(ms) });
  const deltaFmt = (n: number) => `${n >= 0 ? "+" : "−"}${k("points", { n: numFmt(Math.abs(Math.round(n * 1000) / 10)) })}`;

  return (
    <section data-screen="A-14">
      <PageHeader title={k("title")} description={k("subtitle")} code="A-14" />

      <div style={{ marginBottom: "var(--rmc-space-4)" }}>
        <Alert tone="info">{k("scope_note")}</Alert>
      </div>

      <p style={{ ...muted, fontSize: "var(--rmc-size-sm)", marginTop: 0 }}>
        {k("as_of", { time: formatDate(locale, new Date(view.generatedAt), { dateStyle: "medium", timeStyle: "short" }) })}
        {" · "}
        <span>{k("tenant")}: {view.tenantName}</span>
        {" · "}
        <span>{k("period")}: <strong>{view.period.label}</strong> <span style={muted}>({formatDate(locale, new Date(view.period.from), { dateStyle: "medium" })} – {formatDate(locale, new Date(view.period.to), { dateStyle: "medium" })})</span></span>
      </p>

      {/* Uyarılar */}
      {!withinBudget && totalLat && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="danger">{k("alert.latency_over", { p95: msFmt(totalLat.p95Ms), budget: msFmt(tg.latencyP95Ms) })}</Alert>
        </div>
      )}
      {ratioBand(contain, tg.containment) === "bad" && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="warning">{k("alert.containment_low", { rate: pctFmt(contain), target: pctFmt(tg.containment) })}</Alert>
        </div>
      )}
      {ratioBand(view.csat, tg.csat) === "bad" && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="warning">{k("alert.csat_low", { csat: pctFmt(view.csat), target: pctFmt(tg.csat) })}</Alert>
        </div>
      )}
      {!ahtOk && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="warning">{k("alert.aht_inconsistent")}</Alert>
        </div>
      )}

      {/* Özet KPI'lar */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", margin: "var(--rmc-space-2) 0 var(--rmc-space-3)" }}>
        <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: 0 }}>{k("section.summary")}</h2>
        <Button variant="secondary">{k("action.export")}</Button>
      </div>
      <div style={grid()}>
        <Kpi label={k("kpi.total_calls")} value={numFmt(total)} hint={k("kpi.total_calls_hint")} tone="info" />
        <Kpi label={k("kpi.containment")} value={pctFmt(contain)} hint={k("kpi.containment_hint", { target: pctFmt(tg.containment) })} tone={solid(ratioTone(contain, tg.containment))} />
        <Kpi label={k("kpi.transfer")} value={pctFmt(transfer)} hint={k("kpi.transfer_hint")} tone="info" />
        <Kpi label={k("kpi.csat")} value={pctFmt(view.csat)} hint={k("kpi.csat_hint", { n: numFmt(view.csatResponses) })} tone={solid(ratioTone(view.csat, tg.csat))} />
        <Kpi label={k("kpi.aht")} value={secFmt(view.ahtSec)} hint={k("kpi.aht_hint", { target: secFmt(tg.ahtSec) })} tone={solid(lowerBetterTone(view.ahtSec, tg.ahtSec))} />
        <Kpi label={k("kpi.latency")} value={totalLat ? msFmt(totalLat.p95Ms) : k("na")} hint={k("kpi.latency_hint", { budget: msFmt(tg.latencyP95Ms) })} tone={solid(lowerBetterTone(totalLat?.p95Ms ?? 0, tg.latencyP95Ms))} />
      </div>

      {/* Sonuç dağılımı (FR-ANA-002/003) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.outcomes")}</h2>
      <Card>
        <Table caption={k("outcomes_caption")}>
          <thead>
            <tr style={rowBorder}>
              <th style={th}>{k("col.outcome")}</th>
              <th style={th}>{k("col.purpose")}</th>
              <th style={thEnd}>{k("col.count")}</th>
              <th style={thEnd}>{k("col.rate")}</th>
            </tr>
          </thead>
          <tbody>
            {outcomes.map((o) => (
              <tr key={o.outcome} style={rowBorder}>
                <td style={td}><StatusPill tone={outcomeTone(o.outcome)}>{outcomeName(o.outcome)}</StatusPill></td>
                <td style={td}><span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{k(`outcome_desc.${o.outcome}`)}</span></td>
                <td style={tdEnd}>{numFmt(o.count)}</td>
                <td style={tdEnd}>{pct1Fmt(outcomeRate(view, o.outcome))}</td>
              </tr>
            ))}
            <tr style={{ borderTop: "2px solid var(--rmc-border-subtle)" }}>
              <td style={td}><strong>{k("total")}</strong></td>
              <td style={td}><span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{k("outcomes_total_desc")}</span></td>
              <td style={tdEnd}><strong>{numFmt(total)}</strong></td>
              <td style={tdEnd}>{pctFmt(1)}</td>
            </tr>
          </tbody>
        </Table>
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>{k("outcomes_hint", { contained: numFmt(outcomeCount(view, "contained")), transfer: pctFmt(transfer), abandon: pctFmt(abandon) })}</p>

      {/* Konuşma süreleri (FR-ANA-005) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.talk")}</h2>
      <Card>
        <Table caption={k("talk_caption")}>
          <thead>
            <tr style={rowBorder}>
              <th style={th}>{k("col.metric")}</th>
              <th style={thEnd}>{k("col.value")}</th>
              <th style={thEnd}>{k("col.share")}</th>
            </tr>
          </thead>
          <tbody>
            {([["user", view.talk.userSec], ["agent", view.talk.agentSec], ["silence", view.talk.silenceSec]] as const).map(([key, sec]) => (
              <tr key={key} style={rowBorder}>
                <td style={td}>{k(`talk.${key}`)}</td>
                <td style={tdEnd}>{secFmt(sec)}</td>
                <td style={tdEnd}>{pct1Fmt(talkTotalSec(view.talk) > 0 ? sec / talkTotalSec(view.talk) : 0)}</td>
              </tr>
            ))}
            <tr style={{ borderTop: "2px solid var(--rmc-border-subtle)" }}>
              <td style={td}><strong>{k("talk.aht")}</strong></td>
              <td style={tdEnd}><strong>{secFmt(Math.round(avgCallSec(view)))}</strong></td>
              <td style={tdEnd}><StatusPill tone={solid(lowerBetterTone(view.ahtSec, tg.ahtSec))}>{secFmt(view.ahtSec)}</StatusPill></td>
            </tr>
          </tbody>
        </Table>
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>{k("talk_hint", { agent: pctFmt(agentTalk) })}</p>

      {/* Yanıt gecikmesi (FR-ANA-006) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.latency")}</h2>
      <Card>
        <Table caption={k("latency_caption")}>
          <thead>
            <tr style={rowBorder}>
              <th style={th}>{k("col.stage")}</th>
              <th style={thEnd}>{k("col.p50")}</th>
              <th style={thEnd}>{k("col.p95")}</th>
            </tr>
          </thead>
          <tbody>
            {latency.map((l) => {
              const isTotal = l.stage === "total";
              return (
                <tr key={l.stage} style={isTotal ? { borderTop: "2px solid var(--rmc-border-subtle)" } : rowBorder}>
                  <td style={td}>{isTotal ? <strong>{stageName(l.stage)}</strong> : stageName(l.stage)}</td>
                  <td style={tdEnd}>{msFmt(l.p50Ms)}</td>
                  <td style={tdEnd}>{isTotal ? <StatusPill tone={solid(lowerBetterTone(l.p95Ms, tg.latencyP95Ms))}>{msFmt(l.p95Ms)}</StatusPill> : msFmt(l.p95Ms)}</td>
                </tr>
              );
            })}
          </tbody>
        </Table>
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>{k("latency_hint", { budget: msFmt(tg.latencyP95Ms) })}</p>

      {/* Zaman serisi / trend (FR-ANA-011) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.trend")}</h2>
      <div style={grid()}>
        <Kpi label={k("trend_kpi.containment")} value={`${trendArrow(containTrend)} ${trendName(containTrend)}`} hint={k("trend_kpi.containment_hint")} tone={trendTone(containTrend) === "danger" ? "danger" : trendTone(containTrend) === "success" ? "success" : "info"} />
        <Kpi label={k("trend_kpi.csat")} value={`${trendArrow(csatTrend)} ${trendName(csatTrend)}`} hint={k("trend_kpi.csat_hint")} tone={trendTone(csatTrend) === "danger" ? "danger" : trendTone(csatTrend) === "success" ? "success" : "info"} />
        <Kpi label={k("trend_kpi.volume")} value={`${trendArrow(volTrend)} ${trendName(volTrend)}`} hint={k("trend_kpi.volume_hint")} tone="info" />
      </div>
      <Card>
        {view.series.length === 0 ? (
          <EmptyState message={k("no_series")} />
        ) : (
          <Table caption={k("trend_caption")}>
            <thead>
              <tr style={rowBorder}>
                <th style={th}>{k("col.date")}</th>
                <th style={thEnd}>{k("col.calls")}</th>
                <th style={thEnd}>{k("col.containment")}</th>
                <th style={thEnd}>{k("col.csat")}</th>
                <th style={thEnd}>{k("col.aht")}</th>
              </tr>
            </thead>
            <tbody>
              {view.series.map((p) => (
                <tr key={p.date} style={rowBorder}>
                  <td style={td}>{formatDate(locale, new Date(p.date), { dateStyle: "medium" })}</td>
                  <td style={tdEnd}>{numFmt(p.calls)}</td>
                  <td style={tdEnd}><StatusPill tone={solid(ratioTone(dayContainmentRate(p), tg.containment))}>{pctFmt(dayContainmentRate(p))}</StatusPill></td>
                  <td style={tdEnd}>{pctFmt(p.csat)}</td>
                  <td style={tdEnd}>{secFmt(p.ahtSec)}</td>
                </tr>
              ))}
              <tr style={{ borderTop: "2px solid var(--rmc-border-subtle)" }}>
                <td style={td}><strong>{k("total")}</strong></td>
                <td style={tdEnd}><strong>{numFmt(sCalls)}</strong></td>
                <td style={tdEnd}>{pctFmt(sCalls > 0 ? sContained / sCalls : 0)}</td>
                <td style={tdEnd}><span style={muted}>—</span></td>
                <td style={tdEnd}><span style={muted}>—</span></td>
              </tr>
            </tbody>
          </Table>
        )}
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>{k("trend_hint")}</p>

      {/* Agent sürümü karşılaştırması (FR-ANA-010) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.versions")}</h2>
      <Card>
        <Table caption={k("versions_caption")}>
          <thead>
            <tr style={rowBorder}>
              <th style={th}>{k("col.version")}</th>
              <th style={thEnd}>{k("col.calls")}</th>
              <th style={thEnd}>{k("col.containment")}</th>
              <th style={thEnd}>{k("col.delta")}</th>
              <th style={thEnd}>{k("col.csat")}</th>
              <th style={thEnd}>{k("col.aht")}</th>
            </tr>
          </thead>
          <tbody>
            {view.versions.map((v) => {
              const d = versionContainmentDelta(v, view.versions);
              return (
                <tr key={v.agentVersion} style={rowBorder}>
                  <td style={td}>
                    <code style={{ fontSize: "var(--rmc-size-xs)" }}>{v.agentVersion}</code>
                    {v.current && <span style={{ color: "var(--rmc-info-fg, #175cd3)", fontSize: "var(--rmc-size-xs)" }}> · {k("current_badge")}</span>}
                  </td>
                  <td style={tdEnd}>{numFmt(v.calls)}</td>
                  <td style={tdEnd}><StatusPill tone={solid(ratioTone(v.containmentRate, tg.containment))}>{pctFmt(v.containmentRate)}</StatusPill></td>
                  <td style={tdEnd}><span style={{ color: d >= 0 ? "var(--rmc-success-fg, #067647)" : "var(--rmc-danger-fg, #b42318)" }}>{deltaFmt(d)}</span></td>
                  <td style={tdEnd}>{pctFmt(v.csat)}</td>
                  <td style={tdEnd}>{secFmt(v.ahtSec)}</td>
                </tr>
              );
            })}
            <tr style={{ borderTop: "2px solid var(--rmc-border-subtle)" }}>
              <td style={td}><strong>{k("versions_avg")}</strong></td>
              <td style={tdEnd}>—</td>
              <td style={tdEnd}><strong>{pctFmt(avgContain)}</strong></td>
              <td style={tdEnd}>—</td>
              <td style={tdEnd}>—</td>
              <td style={tdEnd}>—</td>
            </tr>
          </tbody>
        </Table>
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>
        {cur ? k("versions_hint", { v: cur.agentVersion, delta: deltaFmt(versionContainmentDelta(cur, view.versions)) }) : k("versions_hint_none")}
      </p>
    </section>
  );
}
