// WBS 13.4.15 — L2 ekranı A-15 "Maliyet & Kaynak Tüketimi" (gerçek içerik; 13.1.1 iskeletinin yerini alır).
//
// İÇERİK (BRD §17.5 A-15 — "Operasyonel maliyet ve çağrı başı kaynak görünümü"): bir DÖNEM boyunca ÇOK ÇAĞRIYI
// TOPLULAŞTIRAN operasyonel maliyet + lean-runtime kaynak panosu. ÖZET KPI'lar (toplam maliyet · çağrı başına maliyet ·
// çözülen çağrı başına maliyet §18.1 · dakika başına maliyet §18.2 · çağrı başı CPU/bellek P95 · worker density),
// MALİYET DAĞILIMI (FR-ANA-007 — STT/LLM/TTS/telekom/compute bileşen/sağlayıcı bazında), AGENT BAZINDA maliyet
// (FR-ANA-007), ÇAĞRI BAŞINA KAYNAK TÜKETİMİ (FR-ANA-013 — CPU/bellek/eşzamanlılık), VERİMLİLİK / LEAN-RUNTIME
// (NFR 10.2 density + FR-TTS-010 cache + SR-DEN-005 küçük-model + FR-RES-014 idle; BRD §18.2) ve ZAMAN SERİSİ / TREND
// (FR-ANA-011). A-15 yalnız TOPLULAŞTIRILMIŞ maliyet/kaynak metriği gösterir (Tier A); tek çağrı içeriği/transkript/PII
// TAŞIMAZ → break-glass gerekmez. Ham ses/ham transkript/transkript metni/ham numara (e164)/müşteri PII/kart-OTP/
// nesne-depo URI'si GÖSTERİLMEZ; ham veri export (FR-ANA-011) görsel kapıdır, nihai export + redaction + audit
// backend'de (cost:read — API §8.1). TENANT-SCOPE (FR-TEN-002): yalnız oturum açan tenant (middleware 13.1.2 + RLS).
// RBAC (BRD §17.6 A-15): operations_manager=Görüntüle · conversation_designer=— · qa_analyst=— · human_agent=—;
// tenant_owner kural 17.7 ile Yönet. Tüm ETİKET metni i18n'den (t()); maliyet/sayı/tarih ise VERİDİR (locale-duyarlı
// biçimlenir — formatCurrency/formatNumber/formatDate).
import type { CSSProperties } from "react";
import { getServerLocale } from "@/lib/i18n/server";
import { getCatalog, t, formatNumber, formatCurrency, formatDate } from "@/lib/i18n";
import { PageHeader, Card, StatusPill, Alert, Table, Button, EmptyState } from "@/lib/ui/components";
import {
  getCostView,
  sortedComponents,
  sortedResources,
  totalCostMinor,
  componentShare,
  dominantComponent,
  agentCostShare,
  agentCostPerCallMinor,
  agentCostReconciles,
  agentCallsReconcile,
  costPerCallMinor,
  costPerResolvedMinor,
  costPerMinuteMinor,
  resourceStat,
  resourceWithinBudget,
  memWithinBudget,
  cpuWithinBudget,
  densityMeetsTarget,
  densityMeetsStretch,
  seriesCalls,
  seriesCostMinor,
  dayCostPerCallMinor,
  seriesTrend,
  lowerBetterBand,
  ratioBand,
  bandTone,
  lowerBetterTone,
  ratioTone,
  componentTone,
  costTrendTone,
  volumeTrendTone,
  type CostComponentKey,
  type ResourceMetric,
  type TrendDir,
} from "@/lib/tenant/cost";

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
  const k = (key: string, p?: Record<string, string | number>) => t(cat, `screen.a15.${key}`, p);
  const view = await getCostView();
  const tg = view.targets;

  const totalMinor = totalCostMinor(view);
  const perCall = costPerCallMinor(view);
  const perResolved = costPerResolvedMinor(view);
  const perMinute = costPerMinuteMinor(view);
  const components = sortedComponents(view);
  const resources = sortedResources(view);
  const cpu = resourceStat(view, "cpuMs");
  const mem = resourceStat(view, "memMb");
  const eff = view.efficiency;
  const dominant = dominantComponent(view);
  const costTrend = seriesTrend(view, "cost");
  const volTrend = seriesTrend(view, "calls");
  const memTrend = seriesTrend(view, "mem");
  const sCalls = seriesCalls(view);
  const sCost = seriesCostMinor(view);

  const componentName = (c: CostComponentKey) => k(`component.${c}`);
  const metricName = (m: ResourceMetric) => k(`metric.${m}`);
  const trendName = (d: TrendDir) => k(`trend.${d}`);
  const trendArrow = (d: TrendDir) => (d === "up" ? "▲" : d === "down" ? "▼" : "▬");

  const curFmt = (minor: number) => formatCurrency(locale, minor / 100, view.currency);
  const numFmt = (n: number) => formatNumber(locale, n);
  const num1Fmt = (n: number) => formatNumber(locale, Math.round(n * 10) / 10, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const pctFmt = (n: number) => k("percent", { n: numFmt(Math.round(n * 100)) });
  const pct1Fmt = (n: number) => k("percent", { n: numFmt(Math.round(n * 1000) / 10) });
  const msFmt = (ms: number) => k("ms", { n: num1Fmt(ms) });
  const mbFmt = (mb: number) => k("mb", { n: num1Fmt(mb) });

  const perCallBand = lowerBetterBand(perCall, tg.costPerCallMinor);

  return (
    <section data-screen="A-15">
      <PageHeader title={k("title")} description={k("subtitle")} code="A-15" />

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
      {perCallBand === "bad" && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="warning">{k("alert.cost_over", { cost: curFmt(perCall), target: curFmt(tg.costPerCallMinor) })}</Alert>
        </div>
      )}
      {!memWithinBudget(view) && mem && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="danger">{k("alert.mem_over", { mem: mbFmt(mem.p95), budget: mbFmt(mem.budget) })}</Alert>
        </div>
      )}
      {!cpuWithinBudget(view) && cpu && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="warning">{k("alert.cpu_over", { cpu: msFmt(cpu.p95), budget: msFmt(cpu.budget) })}</Alert>
        </div>
      )}
      {!densityMeetsTarget(view) && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="warning">{k("alert.density_low", { density: numFmt(eff.density), target: numFmt(tg.densityMin) })}</Alert>
        </div>
      )}

      {/* Özet KPI'lar */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", margin: "var(--rmc-space-2) 0 var(--rmc-space-3)" }}>
        <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: 0 }}>{k("section.summary")}</h2>
        <Button variant="secondary">{k("action.export")}</Button>
      </div>
      <div style={grid()}>
        <Kpi label={k("kpi.total_cost")} value={curFmt(totalMinor)} hint={k("kpi.total_cost_hint", { calls: numFmt(view.totalCalls) })} tone="info" />
        <Kpi label={k("kpi.per_call")} value={curFmt(perCall)} hint={k("kpi.per_call_hint", { target: curFmt(tg.costPerCallMinor) })} tone={solid(lowerBetterTone(perCall, tg.costPerCallMinor))} />
        <Kpi label={k("kpi.per_resolved")} value={curFmt(perResolved)} hint={k("kpi.per_resolved_hint", { resolved: numFmt(view.resolvedCalls) })} tone="info" />
        <Kpi label={k("kpi.per_minute")} value={curFmt(perMinute)} hint={k("kpi.per_minute_hint", { minutes: numFmt(view.billedMinutes) })} tone="info" />
        <Kpi label={k("kpi.cpu")} value={cpu ? msFmt(cpu.p95) : k("na")} hint={k("kpi.cpu_hint", { budget: msFmt(tg.cpuMsP95) })} tone={solid(lowerBetterTone(cpu?.p95 ?? 0, tg.cpuMsP95))} />
        <Kpi label={k("kpi.mem")} value={mem ? mbFmt(mem.p95) : k("na")} hint={k("kpi.mem_hint", { budget: mbFmt(tg.memMbP95) })} tone={solid(lowerBetterTone(mem?.p95 ?? 0, tg.memMbP95))} />
        <Kpi label={k("kpi.density")} value={numFmt(eff.density)} hint={k("kpi.density_hint", { min: numFmt(tg.densityMin), stretch: numFmt(tg.densityStretch) })} tone={solid(ratioTone(eff.density, tg.densityMin))} />
      </div>

      {/* Maliyet dağılımı — bileşen/sağlayıcı bazında (FR-ANA-007) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.components")}</h2>
      <Card>
        <Table caption={k("components_caption")}>
          <thead>
            <tr style={rowBorder}>
              <th style={th}>{k("col.component")}</th>
              <th style={th}>{k("col.purpose")}</th>
              <th style={thEnd}>{k("col.amount")}</th>
              <th style={thEnd}>{k("col.share")}</th>
            </tr>
          </thead>
          <tbody>
            {components.map((c) => (
              <tr key={c.component} style={rowBorder}>
                <td style={td}><StatusPill tone={componentTone(c.component)}>{componentName(c.component)}</StatusPill></td>
                <td style={td}><span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{k(`component_desc.${c.component}`)}</span></td>
                <td style={tdEnd}>{curFmt(c.amountMinor)}</td>
                <td style={tdEnd}>{pct1Fmt(componentShare(view, c.component))}</td>
              </tr>
            ))}
            <tr style={{ borderTop: "2px solid var(--rmc-border-subtle)" }}>
              <td style={td}><strong>{k("total")}</strong></td>
              <td style={td}><span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{k("components_total_desc")}</span></td>
              <td style={tdEnd}><strong>{curFmt(totalMinor)}</strong></td>
              <td style={tdEnd}>{pctFmt(1)}</td>
            </tr>
          </tbody>
        </Table>
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>
        {dominant ? k("components_hint", { driver: componentName(dominant), share: pctFmt(componentShare(view, dominant)) }) : k("components_hint_none")}
      </p>

      {/* Agent bazında maliyet (FR-ANA-007) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.agents")}</h2>
      <Card>
        {view.agents.length === 0 ? (
          <EmptyState message={k("no_agents")} />
        ) : (
          <Table caption={k("agents_caption")}>
            <thead>
              <tr style={rowBorder}>
                <th style={th}>{k("col.agent")}</th>
                <th style={thEnd}>{k("col.calls")}</th>
                <th style={thEnd}>{k("col.amount")}</th>
                <th style={thEnd}>{k("col.share")}</th>
                <th style={thEnd}>{k("col.per_call")}</th>
              </tr>
            </thead>
            <tbody>
              {view.agents.map((g) => (
                <tr key={g.agentRef} style={rowBorder}>
                  <td style={td}>{g.agentName} <code style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{g.agentRef}</code></td>
                  <td style={tdEnd}>{numFmt(g.calls)}</td>
                  <td style={tdEnd}>{curFmt(g.amountMinor)}</td>
                  <td style={tdEnd}>{pct1Fmt(agentCostShare(g, view))}</td>
                  <td style={tdEnd}>{curFmt(agentCostPerCallMinor(g))}</td>
                </tr>
              ))}
              <tr style={{ borderTop: "2px solid var(--rmc-border-subtle)" }}>
                <td style={td}><strong>{k("total")}</strong></td>
                <td style={tdEnd}><strong>{numFmt(view.totalCalls)}</strong></td>
                <td style={tdEnd}><strong>{curFmt(totalMinor)}</strong></td>
                <td style={tdEnd}>{pctFmt(1)}</td>
                <td style={tdEnd}>{curFmt(perCall)}</td>
              </tr>
            </tbody>
          </Table>
        )}
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>
        {agentCostReconciles(view) && agentCallsReconcile(view) ? k("agents_hint_ok") : k("agents_hint_mismatch")}
      </p>

      {/* Çağrı başına kaynak tüketimi (FR-ANA-013) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.resources")}</h2>
      <Card>
        <Table caption={k("resources_caption")}>
          <thead>
            <tr style={rowBorder}>
              <th style={th}>{k("col.metric")}</th>
              <th style={thEnd}>{k("col.p50")}</th>
              <th style={thEnd}>{k("col.p95")}</th>
              <th style={thEnd}>{k("col.budget")}</th>
              <th style={thEnd}>{k("col.status")}</th>
            </tr>
          </thead>
          <tbody>
            {resources.map((r) => {
              const within = resourceWithinBudget(view, r.metric);
              const fmt = r.metric === "memMb" ? mbFmt : msFmt;
              return (
                <tr key={r.metric} style={rowBorder}>
                  <td style={td}>{metricName(r.metric)}</td>
                  <td style={tdEnd}>{fmt(r.p50)}</td>
                  <td style={tdEnd}>{fmt(r.p95)}</td>
                  <td style={tdEnd}>{fmt(r.budget)}</td>
                  <td style={tdEnd}><StatusPill tone={within ? "success" : "danger"}>{within ? k("status.within") : k("status.over")}</StatusPill></td>
                </tr>
              );
            })}
            <tr style={{ borderTop: "2px solid var(--rmc-border-subtle)" }}>
              <td style={td}>{k("metric.concurrency")}</td>
              <td style={tdEnd}><span style={muted}>—</span></td>
              <td style={tdEnd}>{numFmt(eff.density)}</td>
              <td style={tdEnd}>≥{numFmt(tg.densityMin)}</td>
              <td style={tdEnd}><StatusPill tone={solid(ratioTone(eff.density, tg.densityMin))}>{densityMeetsTarget(view) ? k("status.within") : k("status.over")}</StatusPill></td>
            </tr>
          </tbody>
        </Table>
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>{k("resources_hint", { budget: mbFmt(tg.memMbP95) })}</p>

      {/* Verimlilik / lean-runtime göstergeleri (NFR 10.2 / BRD §18.2) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.efficiency")}</h2>
      <div style={grid()}>
        <Kpi label={k("eff.density")} value={numFmt(eff.density)} hint={densityMeetsStretch(view) ? k("eff.density_stretch", { stretch: numFmt(tg.densityStretch) }) : k("eff.density_min", { min: numFmt(tg.densityMin) })} tone={solid(ratioTone(eff.density, tg.densityMin))} />
        <Kpi label={k("eff.cache")} value={pctFmt(eff.cacheHitRatio)} hint={k("eff.cache_hint", { target: pctFmt(tg.cacheHit) })} tone={solid(ratioTone(eff.cacheHitRatio, tg.cacheHit))} />
        <Kpi label={k("eff.small_model")} value={pctFmt(eff.smallModelTurnRatio)} hint={k("eff.small_model_hint", { target: pctFmt(tg.smallModelRatio) })} tone={solid(ratioTone(eff.smallModelTurnRatio, tg.smallModelRatio))} />
        <Kpi label={k("eff.idle")} value={pctFmt(eff.idleReclaimRatio)} hint={k("eff.idle_hint", { target: pctFmt(tg.idleReclaim) })} tone={solid(ratioTone(eff.idleReclaimRatio, tg.idleReclaim))} />
      </div>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: 0 }}>{k("efficiency_hint")}</p>

      {/* Zaman serisi / trend (FR-ANA-011) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.trend")}</h2>
      <div style={grid()}>
        <Kpi label={k("trend_kpi.cost")} value={`${trendArrow(costTrend)} ${trendName(costTrend)}`} hint={k("trend_kpi.cost_hint")} tone={costTrendTone(costTrend) === "danger" ? "danger" : costTrendTone(costTrend) === "success" ? "success" : "info"} />
        <Kpi label={k("trend_kpi.mem")} value={`${trendArrow(memTrend)} ${trendName(memTrend)}`} hint={k("trend_kpi.mem_hint")} tone={costTrendTone(memTrend) === "danger" ? "danger" : costTrendTone(memTrend) === "success" ? "success" : "info"} />
        <Kpi label={k("trend_kpi.volume")} value={`${trendArrow(volTrend)} ${trendName(volTrend)}`} hint={k("trend_kpi.volume_hint")} tone={volumeTrendTone(volTrend) === "danger" ? "danger" : "info"} />
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
                <th style={thEnd}>{k("col.amount")}</th>
                <th style={thEnd}>{k("col.per_call")}</th>
                <th style={thEnd}>{k("col.cpu")}</th>
                <th style={thEnd}>{k("col.mem")}</th>
              </tr>
            </thead>
            <tbody>
              {view.series.map((p) => (
                <tr key={p.date} style={rowBorder}>
                  <td style={td}>{formatDate(locale, new Date(p.date), { dateStyle: "medium" })}</td>
                  <td style={tdEnd}>{numFmt(p.calls)}</td>
                  <td style={tdEnd}>{curFmt(p.amountMinor)}</td>
                  <td style={tdEnd}>{curFmt(dayCostPerCallMinor(p))}</td>
                  <td style={tdEnd}>{msFmt(p.cpuMsP95)}</td>
                  <td style={tdEnd}><StatusPill tone={bandTone(lowerBetterBand(p.memMbP95, tg.memMbP95))}>{mbFmt(p.memMbP95)}</StatusPill></td>
                </tr>
              ))}
              <tr style={{ borderTop: "2px solid var(--rmc-border-subtle)" }}>
                <td style={td}><strong>{k("total")}</strong></td>
                <td style={tdEnd}><strong>{numFmt(sCalls)}</strong></td>
                <td style={tdEnd}><strong>{curFmt(sCost)}</strong></td>
                <td style={tdEnd}>{curFmt(sCalls > 0 ? sCost / sCalls : 0)}</td>
                <td style={tdEnd}><span style={muted}>—</span></td>
                <td style={tdEnd}><span style={muted}>—</span></td>
              </tr>
            </tbody>
          </Table>
        )}
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>{k("trend_hint")}</p>

      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-5)" }}>{k("footnote")}</p>
    </section>
  );
}
