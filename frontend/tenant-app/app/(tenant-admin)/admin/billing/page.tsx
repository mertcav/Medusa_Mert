// WBS 13.3.7 — L1 ekranı T-07 "Faturalandırma & Kullanım" (gerçek içerik; 13.1.1 iskeletinin yerini alır).
//
// İÇERİK (BRD §17.4 / FR-BIL-001..007): tenant'ın PLAN (fiyat planı + faturalama modeli + minimum ücret),
// KULLANIM (dakika/saniye bazlı tüketim), MALİYET KIRILIMI (telekom/STT/TTS/LLM/platform ayrı izleme), KOTA &
// OVERAGE (kullanım kotası + aşım), BÜTÇE ALARMI (kullanım limiti + bütçe eşikleri) ve FATURA AKTARIMI (finans
// sistemine aktarım durumu) görünümü. TENANT-SCOPE (FR-TEN-002): yalnız oturum açan tenant'ın KENDİ plan/
// kullanım/maliyet görünümü; scope middleware (13.1.2) + RLS (§13) ile sabitlenir. HİJYEN (BRD §17.7) +
// GÜVENLİK (NFR 10.6): ham son-müşteri içeriği (çağrı kaydı/transkript/çağrı-bazlı CDR/PII) ve SIR (ödeme
// yöntemi/kart/IBAN/finans credential) gömülmez — veri katmanı `assertNoPii` ile garanti eder. Maliyet/kullanım
// YALNIZ tenant-bütünü TOPLULAŞTIRMADIR. RBAC (BRD §17.6): tenant_owner=Yönet · tenant_admin=Görüntüle ·
// security_compliance_officer=— · billing_viewer=Görüntüle · api_developer=—. UI yalnız görsel kapı; nihai
// yetki backend'de (12.2.x, SAD §14.4.1 A8). Fiyat/maliyet değerleri İLLÜSTRATİFTİR (rate-card finans/billing
// motorundan beslenir). Tüm kullanıcı-görünür metin i18n katalogundan (t()).
import type { CSSProperties } from "react";
import { getServerLocale } from "@/lib/i18n/server";
import { getCatalog, t, formatNumber, formatDate, formatCurrency } from "@/lib/i18n";
import { PageHeader, Card, StatusPill, Alert, Table, Button, EmptyState } from "@/lib/ui/components";
import {
  getBilling,
  costTotal,
  costShare,
  budgetRatio,
  overBudget,
  budgetApproaching,
  triggeredAlarms,
  unconfiguredAlarms,
  quotaOverageMinutes,
  overageBlocked,
  usageLimitExceeded,
  costMismatch,
  invalidPlan,
  invoiceExportFailed,
  invoiceExportUnconfigured,
  openWarningCount,
  budgetRatioTone,
  invoiceStatusTone,
  tierTone,
  overageTone,
  alarmTriggeredTone,
  type BillingModel,
  type CostCategory,
  type InvoiceExportStatus,
  type PlanTier,
} from "@/lib/tenant/billing";

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
const tdEnd: CSSProperties = { padding: "var(--rmc-space-2)", textAlign: "end" };
const thEnd: CSSProperties = { padding: "var(--rmc-space-2)", textAlign: "end" };
const rowBorder: CSSProperties = { borderBottom: "1px solid var(--rmc-border-subtle)" };
const muted: CSSProperties = { color: "var(--rmc-text-muted)" };

const COST_ORDER: CostCategory[] = ["telecom", "stt", "tts", "llm", "platform"];

export default async function Page() {
  const locale = getServerLocale();
  const cat = getCatalog(locale);
  const k = (key: string, p?: Record<string, string | number>) => t(cat, `screen.t07.${key}`, p);
  const snap = await getBilling();
  const { plan, usage, costs, overage, budget, invoiceExport } = snap;

  const ratio = budgetRatio(budget);
  const over = overBudget(budget);
  const approaching = budgetApproaching(budget);
  const fired = new Set(triggeredAlarms(budget));
  const noAlarms = unconfiguredAlarms(budget);
  const quotaOver = quotaOverageMinutes(usage);
  const blocked = overageBlocked(usage, overage);
  const limitExceeded = usageLimitExceeded(usage, budget);
  const reconcileGap = costMismatch(snap);
  const planGaps = new Set(invalidPlan(plan));
  const exportFailed = invoiceExportFailed(invoiceExport);
  const exportUnconfigured = invoiceExportUnconfigured(invoiceExport);
  const openCount = openWarningCount(snap);
  const total = costTotal(costs);

  const cur = (n: number) => formatCurrency(locale, n, plan.currency);
  const pct = (frac: number) => formatNumber(locale, frac, { style: "percent", maximumFractionDigits: 1 });

  const billingModelName = (m: BillingModel) => k(`billing_model.${m}`);
  const tierName = (tr: PlanTier) => k(`tier.${tr}`);
  const categoryName = (c: CostCategory) => k(`category.${c}`);
  const exportStatusName = (s: InvoiceExportStatus) => k(`export_status.${s}`);

  const yesNo = (b: boolean) => (b ? k("yes") : k("no"));

  return (
    <section data-screen="T-07">
      <PageHeader title={k("title")} description={k("subtitle")} code="T-07" />

      <div style={{ marginBottom: "var(--rmc-space-4)" }}>
        <Alert tone="info">{k("scope_note")}</Alert>
      </div>

      <p style={{ ...muted, fontSize: "var(--rmc-size-sm)", marginTop: 0 }}>
        {k("as_of", { time: formatDate(locale, new Date(snap.generatedAt), { dateStyle: "medium", timeStyle: "short" }) })}
        {" · "}
        <span>{k("tenant")}: {snap.tenantName}</span>
        {" · "}
        <span>{k("period")}: {usage.periodLabel}</span>
      </p>

      {/* Disclaimer: illüstratif fiyat/maliyet — rate-card billing motorundan beslenir */}
      <div style={{ margin: "var(--rmc-space-2) 0 var(--rmc-space-3)" }}>
        <Alert tone="warning">{k("illustrative_note")}</Alert>
      </div>

      {/* Uyarılar */}
      {over && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="danger">{k("over_budget_alert", { ratio: pct(ratio) })}</Alert>
        </div>
      )}
      {limitExceeded && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="danger">{k("usage_limit_alert", { limit: formatNumber(locale, budget.usageLimitMinutes) })}</Alert>
        </div>
      )}
      {reconcileGap && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="danger">{k("reconcile_alert", { components: cur(total), spent: cur(budget.spentAmount) })}</Alert>
        </div>
      )}
      {exportFailed && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="danger">{k("export_failed_alert")}</Alert>
        </div>
      )}
      {planGaps.size > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="danger">{k("plan_invalid_alert", { count: formatNumber(locale, planGaps.size) })}</Alert>
        </div>
      )}
      {approaching && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="warning">{k("approaching_alert", { ratio: pct(ratio) })}</Alert>
        </div>
      )}
      {blocked && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="warning">{k("overage_blocked_alert", { minutes: formatNumber(locale, quotaOver) })}</Alert>
        </div>
      )}
      {noAlarms && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="warning">{k("no_alarms_alert")}</Alert>
        </div>
      )}
      {exportUnconfigured && (
        <div style={{ margin: "var(--rmc-space-2) 0 var(--rmc-space-4)" }}>
          <Alert tone="warning">{k("export_unconfigured_alert")}</Alert>
        </div>
      )}

      {/* Özet */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", marginBottom: "var(--rmc-space-3)" }}>{k("section.summary")}</h2>
      <div style={grid()}>
        <Kpi label={k("kpi.plan")} value={plan.planName} hint={k("kpi.plan_hint", { tier: tierName(plan.tier) })} />
        <Kpi label={k("kpi.usage")} value={k("minutes", { n: formatNumber(locale, usage.billedMinutes) })} hint={k("kpi.usage_hint", { included: formatNumber(locale, usage.includedMinutes) })} tone={quotaOver > 0 ? "warning" : "success"} />
        <Kpi label={k("kpi.cost")} value={cur(total)} hint={k("kpi.cost_hint")} />
        <Kpi label={k("kpi.budget")} value={pct(ratio)} hint={k("kpi.budget_hint", { budget: cur(budget.budgetAmount) })} tone={over ? "danger" : approaching ? "warning" : "success"} />
        <Kpi label={k("kpi.warnings")} value={formatNumber(locale, openCount)} hint={k("kpi.warnings_hint")} tone={openCount > 0 ? "danger" : "success"} />
      </div>

      {/* Plan */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>
        <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: 0 }}>{k("section.plan")}</h2>
        <Button variant="primary">{k("action.change_plan")}</Button>
      </div>
      <Card>
        <Table caption={k("plan_caption")}>
          <tbody>
            <tr style={rowBorder}><td style={td}>{k("field.plan_name")}</td><td style={td}>{planGaps.has("plan_name") ? <StatusPill tone="danger">{k("undefined_label")}</StatusPill> : <StatusPill tone={tierTone(plan.tier)}>{plan.planName}</StatusPill>}</td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.tier")}</td><td style={td}><code>{tierName(plan.tier)}</code></td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.billing_model")} <code style={muted}>FR-BIL-001</code></td><td style={td}><code>{billingModelName(plan.billingModel)}</code></td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.currency")}</td><td style={td}><code>{plan.currency}</code></td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.minimum_charge")} <code style={muted}>FR-BIL-004</code></td><td style={td}>{planGaps.has("minimum_charge") ? <StatusPill tone="danger">{cur(plan.minimumCharge)}</StatusPill> : cur(plan.minimumCharge)}</td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.billing_period")}</td><td style={td}><code>{plan.billingPeriod}</code></td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.dedicated_infra")} <code style={muted}>FR-BIL-005</code></td><td style={td}>{plan.dedicatedInfra ? <StatusPill tone="info">{k("yes")}</StatusPill> : <span style={muted}>{k("no")}</span>}</td></tr>
          </tbody>
        </Table>
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-2)" }}>{k("plan_hint")}</p>

      {/* Kullanım */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.usage")}</h2>
      <Card>
        <Table caption={k("usage_caption")}>
          <tbody>
            <tr style={rowBorder}><td style={td}>{k("field.billed_minutes")} <code style={muted}>FR-BIL-001</code></td><td style={td}>{k("min_sec", { m: formatNumber(locale, usage.billedMinutes), s: formatNumber(locale, usage.billedSeconds) })}</td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.included_minutes")} <code style={muted}>FR-BIL-004</code></td><td style={td}>{k("minutes", { n: formatNumber(locale, usage.includedMinutes) })}</td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.quota_overage")}</td><td style={td}>{quotaOver > 0 ? <StatusPill tone={blocked ? "danger" : "warning"}>{k("minutes", { n: formatNumber(locale, quotaOver) })}</StatusPill> : <StatusPill tone="success">{k("minutes", { n: formatNumber(locale, 0) })}</StatusPill>}</td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.call_count")}</td><td style={td}>{formatNumber(locale, usage.callCount)}</td></tr>
          </tbody>
        </Table>
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-2)" }}>{k("usage_hint")}</p>

      {/* Maliyet Kırılımı (FR-BIL-002) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.cost")}</h2>
      <Card>
        <Table caption={k("cost_caption")}>
          <thead>
            <tr style={rowBorder}>
              <th style={th}>{k("col.category")}</th>
              <th style={thEnd}>{k("col.amount")}</th>
              <th style={thEnd}>{k("col.share")}</th>
            </tr>
          </thead>
          <tbody>
            {COST_ORDER.map((c) => {
              const amount = costs.filter((x) => x.category === c).reduce((acc, x) => acc + x.amount, 0);
              return (
                <tr key={c} style={rowBorder}>
                  <td style={td}>{categoryName(c)}</td>
                  <td style={tdEnd}>{cur(amount)}</td>
                  <td style={tdEnd}>{pct(costShare(costs, c))}</td>
                </tr>
              );
            })}
            <tr>
              <td style={{ ...td, fontWeight: 700 }}>{k("col.total")}</td>
              <td style={{ ...tdEnd, fontWeight: 700 }}>{reconcileGap ? <StatusPill tone="danger">{cur(total)}</StatusPill> : cur(total)}</td>
              <td style={tdEnd}>{pct(1)}</td>
            </tr>
          </tbody>
        </Table>
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-2)" }}>{k("cost_hint")}</p>

      {/* Kota & Overage (FR-BIL-004) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.overage")}</h2>
      <Card>
        <Table caption={k("overage_caption")}>
          <tbody>
            <tr style={rowBorder}><td style={td}>{k("field.overage_enabled")}</td><td style={td}><StatusPill tone={overageTone(overage.overageEnabled)}>{yesNo(overage.overageEnabled)}</StatusPill></td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.overage_rate")}</td><td style={td}>{cur(overage.overageRate)} <span style={muted}>/ {k("unit.minute")}</span></td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.overage_minutes")}</td><td style={td}>{k("minutes", { n: formatNumber(locale, overage.overageMinutes) })}</td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.overage_amount")}</td><td style={td}>{cur(overage.overageAmount)}</td></tr>
            {blocked && (
              <tr style={rowBorder}><td style={td}>{k("field.overage_state")}</td><td style={td}><StatusPill tone="danger">{k("overage_blocked_label")}</StatusPill></td></tr>
            )}
          </tbody>
        </Table>
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-2)" }}>{k("overage_hint")}</p>

      {/* Bütçe & Alarmlar (FR-BIL-006) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.budget")}</h2>
      <Card>
        <Table caption={k("budget_caption")}>
          <tbody>
            <tr style={rowBorder}><td style={td}>{k("field.budget_amount")}</td><td style={td}>{cur(budget.budgetAmount)}</td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.spent_amount")}</td><td style={td}><StatusPill tone={budgetRatioTone(ratio)}>{cur(budget.spentAmount)} · {pct(ratio)}</StatusPill></td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.usage_limit")} <code style={muted}>FR-BIL-006</code></td><td style={td}>{budget.usageLimitMinutes > 0 ? <StatusPill tone={limitExceeded ? "danger" : "neutral"}>{k("minutes", { n: formatNumber(locale, budget.usageLimitMinutes) })}</StatusPill> : <span style={muted}>{k("no_limit")}</span>}</td></tr>
          </tbody>
        </Table>
      </Card>
      <div style={{ marginTop: "var(--rmc-space-3)" }}>
        <Card>
          {budget.alarms.length === 0 ? (
            <EmptyState message={k("no_alarms")} />
          ) : (
            <Table caption={k("alarms_caption")}>
              <thead>
                <tr style={rowBorder}>
                  <th style={th}>{k("col.alarm")}</th>
                  <th style={thEnd}>{k("col.threshold")}</th>
                  <th style={th}>{k("col.channel")}</th>
                  <th style={th}>{k("col.state")}</th>
                </tr>
              </thead>
              <tbody>
                {budget.alarms.map((a) => (
                  <tr key={a.id} style={rowBorder}>
                    <td style={td}><code style={muted}>{a.id}</code></td>
                    <td style={tdEnd}>{pct(a.thresholdPct / 100)}</td>
                    <td style={td}><code>{a.channel}</code></td>
                    <td style={td}><StatusPill tone={alarmTriggeredTone(fired.has(a.id))}>{fired.has(a.id) ? k("alarm_fired") : k("alarm_armed")}</StatusPill></td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card>
      </div>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-2)" }}>{k("budget_hint")}</p>

      {/* Fatura Aktarımı (FR-BIL-007) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.export")}</h2>
      <Card>
        <Table caption={k("export_caption")}>
          <tbody>
            <tr style={rowBorder}><td style={td}>{k("field.export_status")} <code style={muted}>FR-BIL-007</code></td><td style={td}><StatusPill tone={invoiceStatusTone(invoiceExport.status)}>{exportStatusName(invoiceExport.status)}</StatusPill></td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.export_target")}</td><td style={td}><code>{invoiceExport.target}</code></td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.export_last")}</td><td style={td}>{formatDate(locale, new Date(invoiceExport.lastSync), { dateStyle: "medium", timeStyle: "short" })}</td></tr>
          </tbody>
        </Table>
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>{k("export_hint")}</p>
    </section>
  );
}
