// WBS 13.4.16 — L2 ekranı A-16 "Test & Simulation Centre" (gerçek içerik; 13.1.1 iskeletinin yerini alır).
//
// İÇERİK (BRD §17.5 A-16 — "Tarayıcı testi, persona/senaryo simülasyonu, yük testi"): bir agent ADAY SÜRÜMÜNÜN yayın
// öncesi test/simülasyon panosu. ÖZET KPI'lar (promotion gate / geçme oranı / ortalama skor / senaryo / yük eş zamanlılığı /
// yük altı kaynak P95), SUITE KIRILIMI (happy/edge/adversarial/robustness — FR-TST-003/007), SENARYO SONUÇLARI
// (tarayıcı testi + persona simülasyonu — FR-TST-001/002), REGRESYON (aday vs baseline — FR-TST-004/FR-ANA-010),
// PROMOTION GATE (FR-TST-005 — eşik altı → production engellenir) ve YÜK TESTİ (FR-TST-006/009). Tüm veri SENTETİK
// (FR-TST-008); gerçek çağrı içeriği/transkript/PII TAŞIMAZ → break-glass gerekmez (Tier A). Koşu/promote derin aksiyon
// (test:run / agent:version:manage — API §8.1); nihai çalıştırma + yetki + audit backend'de. TENANT-SCOPE (FR-TEN-002):
// yalnız oturum açan tenant (middleware 13.1.2 + RLS). RBAC (BRD §17.6 A-16): operations_manager=Düzenle ·
// conversation_designer=Yönet · qa_analyst=Görüntüle · human_agent=—; tenant_owner kural 17.7 ile Yönet. Tüm ETİKET
// metni i18n'den (t()); skor/sayı/tarih ise VERİDİR (locale-duyarlı biçimlenir).
import type { CSSProperties } from "react";
import { getServerLocale } from "@/lib/i18n/server";
import { getCatalog, t, formatNumber, formatDate } from "@/lib/i18n";
import { PageHeader, Card, StatusPill, Alert, Table, Button, EmptyState } from "@/lib/ui/components";
import {
  getTestView,
  sortedSuites,
  sortedRegression,
  suitePassRate,
  totalScenarios,
  passedCount,
  failedCount,
  blockedCount,
  overallPassRate,
  meanScore,
  suiteTotalsReconcile,
  suiteStatusReconcile,
  regressionDelta,
  regressionDetected,
  hasRegression,
  worstRegression,
  regressionTone,
  regressionDir,
  loadConcurrencyMet,
  loadCpuWithinBudget,
  loadMemWithinBudget,
  loadResourceRegression,
  loadSuccessMet,
  gateBlockers,
  gateState,
  gatePasses,
  gatePassRateMet,
  gateScoreMet,
  ratioTone,
  lowerBetterTone,
  statusTone,
  categoryTone,
  gateTone,
  GATE_BLOCKER_ORDER,
  type TestCategory,
  type RunStatus,
  type GateState,
  type TrendDir,
} from "@/lib/tenant/test-sim";

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
  const k = (key: string, p?: Record<string, string | number>) => t(cat, `screen.a16.${key}`, p);
  const view = await getTestView();
  const tg = view.targets;

  const suites = sortedSuites(view);
  const regression = sortedRegression(view);
  const total = totalScenarios(view);
  const passed = passedCount(view);
  const failed = failedCount(view);
  const blocked = blockedCount(view);
  const passRate = overallPassRate(view);
  const score = meanScore(view);
  const blockers = gateBlockers(view);
  const gate = gateState(view);
  const worst = worstRegression(view);
  const load = view.load;

  const categoryName = (c: TestCategory) => k(`category.${c}`);
  const statusName = (s: RunStatus) => k(`status.${s}`);
  const gateName = (g: GateState) => k(`gate_state.${g}`);
  const trendArrow = (d: TrendDir) => (d === "up" ? "▲" : d === "down" ? "▼" : "▬");

  const numFmt = (n: number) => formatNumber(locale, n);
  const num2Fmt = (n: number) => formatNumber(locale, Math.round(n * 100) / 100, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const num1Fmt = (n: number) => formatNumber(locale, Math.round(n * 10) / 10, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const pctFmt = (n: number) => k("percent", { n: numFmt(Math.round(n * 100)) });
  const pct1Fmt = (n: number) => k("percent", { n: numFmt(Math.round(n * 1000) / 10) });
  const msFmt = (ms: number) => k("ms", { n: num1Fmt(ms) });
  const mbFmt = (mb: number) => k("mb", { n: num1Fmt(mb) });
  // İşaretli skor farkı (regresyon deltası — locale-duyarlı; pozitif başına "+", negatif başına "−").
  const deltaFmt = (d: number) => {
    const v = num2Fmt(Math.abs(d));
    return d > 0 ? `+${v}` : d < 0 ? `−${v}` : num2Fmt(0);
  };

  return (
    <section data-screen="A-16">
      <PageHeader title={k("title")} description={k("subtitle")} code="A-16" />

      <div style={{ marginBottom: "var(--rmc-space-4)" }}>
        <Alert tone="info">{k("scope_note")}</Alert>
      </div>

      <p style={{ ...muted, fontSize: "var(--rmc-size-sm)", marginTop: 0 }}>
        {k("as_of", { time: formatDate(locale, new Date(view.generatedAt), { dateStyle: "medium", timeStyle: "short" }) })}
        {" · "}
        <span>{k("tenant")}: {view.tenantName}</span>
        {" · "}
        <span>{k("agent")}: {view.agentName} <code style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{view.agentRef}</code></span>
        {" · "}
        <span>{k("version")}: <strong>{view.candidateVersion}</strong> <span style={muted}>({k("baseline")}: {view.baselineVersion})</span></span>
        {" · "}
        <span>{k("environment")}: {view.environment}</span>
        {view.syntheticData && <> {" · "} <StatusPill tone="info">{k("synthetic")}</StatusPill></>}
      </p>

      {/* Uyarılar */}
      {gate === "blocked" && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="danger">{k("alert.gate_blocked", { count: numFmt(blockers.length) })}</Alert>
        </div>
      )}
      {hasRegression(view) && worst && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="warning">{k("alert.regression", { category: categoryName(worst.category), delta: deltaFmt(regressionDelta(worst)), tol: numFmt(Math.round(tg.regressionTolerance * 100)) })}</Alert>
        </div>
      )}
      {loadResourceRegression(view) && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="danger">{k("alert.load_resource")}</Alert>
        </div>
      )}
      {!loadConcurrencyMet(view) && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="warning">{k("alert.concurrency_low", { achieved: numFmt(load.achievedConcurrency), target: numFmt(load.targetConcurrency) })}</Alert>
        </div>
      )}

      {/* Özet KPI'lar */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", margin: "var(--rmc-space-2) 0 var(--rmc-space-3)" }}>
        <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: 0 }}>{k("section.summary")}</h2>
        <Button variant="secondary">{k("action.run")}</Button>
      </div>
      <div style={grid()}>
        <Kpi label={k("kpi.gate")} value={gateName(gate)} hint={gatePasses(view) ? k("status.pass") : k("status.blocked")} tone={solid(gateTone(gate))} />
        <Kpi label={k("kpi.pass_rate")} value={pctFmt(passRate)} hint={k("kpi.pass_rate_hint", { target: numFmt(Math.round(tg.gateMinPassRate * 100)) })} tone={solid(gatePassRateMet(view) ? "success" : ratioTone(passRate, tg.gateMinPassRate))} />
        <Kpi label={k("kpi.score")} value={num2Fmt(score)} hint={k("kpi.score_hint", { target: num2Fmt(tg.gateMinScore) })} tone={solid(gateScoreMet(view) ? "success" : ratioTone(score, tg.gateMinScore))} />
        <Kpi label={k("kpi.scenarios")} value={numFmt(total)} hint={k("kpi.scenarios_hint", { passed: numFmt(passed), failed: numFmt(failed), blocked: numFmt(blocked) })} tone="info" />
        <Kpi label={k("kpi.concurrency")} value={`${numFmt(load.achievedConcurrency)} / ${numFmt(load.targetConcurrency)}`} hint={k("kpi.concurrency_hint", { target: numFmt(load.targetConcurrency) })} tone={solid(ratioTone(load.achievedConcurrency, load.targetConcurrency))} />
        <Kpi label={k("kpi.resource")} value={mbFmt(load.memMbP95)} hint={k("kpi.resource_hint", { budget: mbFmt(tg.memMbP95Budget) })} tone={solid(lowerBetterTone(load.memMbP95, tg.memMbP95Budget))} />
      </div>

      {/* Suite / kategori kırılımı (FR-TST-003/007) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.suites")}</h2>
      <Card>
        <Table caption={k("suites_caption")}>
          <thead>
            <tr style={rowBorder}>
              <th style={th}>{k("col.category")}</th>
              <th style={th}>{k("col.scenario")}</th>
              <th style={thEnd}>{k("col.total")}</th>
              <th style={thEnd}>{k("col.passed")}</th>
              <th style={thEnd}>{k("col.failed")}</th>
              <th style={thEnd}>{k("col.blocked")}</th>
              <th style={thEnd}>{k("col.pass_rate")}</th>
            </tr>
          </thead>
          <tbody>
            {suites.map((s) => (
              <tr key={s.category} style={rowBorder}>
                <td style={td}><StatusPill tone={categoryTone(s.category)}>{categoryName(s.category)}</StatusPill></td>
                <td style={td}><span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{k(`category_desc.${s.category}`)}</span></td>
                <td style={tdEnd}>{numFmt(s.total)}</td>
                <td style={tdEnd}>{numFmt(s.passed)}</td>
                <td style={tdEnd}>{numFmt(s.failed)}</td>
                <td style={tdEnd}>{numFmt(s.blocked)}</td>
                <td style={tdEnd}><StatusPill tone={solid(ratioTone(suitePassRate(s), tg.gateMinPassRate))}>{pctFmt(suitePassRate(s))}</StatusPill></td>
              </tr>
            ))}
            <tr style={{ borderTop: "2px solid var(--rmc-border-subtle)" }}>
              <td style={td}><strong>{k("total")}</strong></td>
              <td style={td} />
              <td style={tdEnd}><strong>{numFmt(total)}</strong></td>
              <td style={tdEnd}><strong>{numFmt(passed)}</strong></td>
              <td style={tdEnd}><strong>{numFmt(failed)}</strong></td>
              <td style={tdEnd}><strong>{numFmt(blocked)}</strong></td>
              <td style={tdEnd}><strong>{pctFmt(passRate)}</strong></td>
            </tr>
          </tbody>
        </Table>
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>
        {suiteTotalsReconcile(view) && suiteStatusReconcile(view) ? k("suites_hint") : k("alert.gate_blocked", { count: numFmt(blockers.length) })}
      </p>

      {/* Senaryo sonuçları (FR-TST-001/002) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.scenarios")}</h2>
      <Card>
        {view.scenarios.length === 0 ? (
          <EmptyState message={k("no_scenarios")} />
        ) : (
          <Table caption={k("scenarios_caption")}>
            <thead>
              <tr style={rowBorder}>
                <th style={th}>{k("col.scenario")}</th>
                <th style={th}>{k("col.category")}</th>
                <th style={th}>{k("col.persona")}</th>
                <th style={thEnd}>{k("col.status")}</th>
                <th style={thEnd}>{k("col.score")}</th>
                <th style={thEnd}>{k("col.turns")}</th>
                <th style={thEnd}>{k("col.latency")}</th>
              </tr>
            </thead>
            <tbody>
              {view.scenarios.map((s) => (
                <tr key={s.scenarioRef} style={rowBorder}>
                  <td style={td}>{s.name} <code style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{s.scenarioRef}</code></td>
                  <td style={td}><StatusPill tone={categoryTone(s.category)}>{categoryName(s.category)}</StatusPill></td>
                  <td style={td}><span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{s.persona}</span></td>
                  <td style={tdEnd}><StatusPill tone={statusTone(s.status)}>{statusName(s.status)}</StatusPill></td>
                  <td style={tdEnd}>{num2Fmt(s.score)}</td>
                  <td style={tdEnd}>{numFmt(s.turns)}</td>
                  <td style={tdEnd}><StatusPill tone={solid(lowerBetterTone(s.latencyMsP95, tg.latencyMsP95Target))}>{msFmt(s.latencyMsP95)}</StatusPill></td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>{k("scenarios_hint", { target: msFmt(tg.latencyMsP95Target) })}</p>

      {/* Regresyon — aday vs baseline (FR-TST-004 / FR-ANA-010) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.regression")}</h2>
      <Card>
        {regression.length === 0 ? (
          <EmptyState message={k("no_regression_items")} />
        ) : (
          <Table caption={k("regression_caption")}>
            <thead>
              <tr style={rowBorder}>
                <th style={th}>{k("col.category")}</th>
                <th style={thEnd}>{k("col.baseline")}</th>
                <th style={thEnd}>{k("col.current")}</th>
                <th style={thEnd}>{k("col.delta")}</th>
                <th style={thEnd}>{k("col.status")}</th>
              </tr>
            </thead>
            <tbody>
              {regression.map((it) => (
                <tr key={it.category} style={rowBorder}>
                  <td style={td}><StatusPill tone={categoryTone(it.category)}>{categoryName(it.category)}</StatusPill></td>
                  <td style={tdEnd}>{num2Fmt(it.baselineScore)}</td>
                  <td style={tdEnd}>{num2Fmt(it.currentScore)}</td>
                  <td style={tdEnd}>{trendArrow(regressionDir(it))} {deltaFmt(regressionDelta(it))}</td>
                  <td style={tdEnd}><StatusPill tone={solid(regressionTone(it))}>{regressionDetected(it) ? k("trend.down") : regressionDelta(it) < 0 ? k("trend.flat") : k("trend.up")}</StatusPill></td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>
        {hasRegression(view) ? k("regression_hint", { candidate: view.candidateVersion, baseline: view.baselineVersion, tol: numFmt(Math.round(tg.regressionTolerance * 100)) }) : k("regression_ok")}
      </p>

      {/* Promotion gate (FR-TST-005) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.gate")}</h2>
      <Card>
        <div style={{ display: "flex", alignItems: "center", gap: "var(--rmc-space-3)", marginBottom: "var(--rmc-space-2)" }}>
          <StatusPill tone={solid(gateTone(gate))}>{gateName(gate)}</StatusPill>
          <strong>{gatePasses(view) ? k("gate_pass_msg") : k("gate_blocked_msg")}</strong>
        </div>
        {!gatePasses(view) && (
          <>
            <div style={{ ...muted, fontSize: "var(--rmc-size-sm)", marginTop: "var(--rmc-space-2)" }}>{k("gate_blockers_label")}</div>
            <ul style={{ margin: "var(--rmc-space-1) 0 0", paddingInlineStart: "var(--rmc-space-5)" }}>
              {GATE_BLOCKER_ORDER.filter((b) => blockers.includes(b)).map((b) => (
                <li key={b}><StatusPill tone="danger">{k(`blocker.${b}`)}</StatusPill></li>
              ))}
            </ul>
          </>
        )}
      </Card>

      {/* Yük testi (FR-TST-006/009) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.load")}</h2>
      <div style={grid()}>
        <Kpi label={k("load_kpi.concurrency")} value={`${numFmt(load.achievedConcurrency)} / ${numFmt(load.targetConcurrency)}`} hint={k("load_kpi.concurrency_hint", { target: numFmt(load.targetConcurrency) })} tone={solid(ratioTone(load.achievedConcurrency, load.targetConcurrency))} />
        <Kpi label={k("load_kpi.cps")} value={numFmt(load.cps)} hint={k("load_kpi.cps_hint")} tone="info" />
        <Kpi label={k("load_kpi.success")} value={pct1Fmt(load.successRate)} hint={k("load_kpi.success_hint", { target: num1Fmt(tg.successRateTarget * 100) })} tone={solid(loadSuccessMet(view) ? "success" : ratioTone(load.successRate, tg.successRateTarget))} />
        <Kpi label={k("load_kpi.cpu")} value={msFmt(load.cpuMsP95)} hint={k("load_kpi.cpu_hint", { budget: msFmt(tg.cpuMsP95Budget), baseline: msFmt(load.baselineCpuMsP95) })} tone={solid(loadCpuWithinBudget(view) ? "success" : "danger")} />
        <Kpi label={k("load_kpi.mem")} value={mbFmt(load.memMbP95)} hint={k("load_kpi.mem_hint", { budget: mbFmt(tg.memMbP95Budget), baseline: mbFmt(load.baselineMemMbP95) })} tone={solid(loadMemWithinBudget(view) ? "success" : "danger")} />
      </div>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: 0 }}>{k("load_hint", { tol: numFmt(Math.round(tg.loadResourceTolerance * 100)) })}</p>

      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-5)" }}>{k("footnote")}</p>
    </section>
  );
}
