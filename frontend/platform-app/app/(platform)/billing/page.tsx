// WBS 13.2.5 — L0 ekranı P-05 "Platform Faturalandırma & Rate-Card" (gerçek içerik; 13.1.1 iskeletinin yerini alır).
//
// İÇERİK (BRD §17.3): plan tanımları, fiyatlandırma (rate-card), kullanım toplulaştırma.
// FR-BIL-001 (dakika ölçümü) · FR-BIL-002 (telekom/STT/TTS/LLM/platform ayrı maliyet) · FR-BIL-003 (fiyat planı) ·
// FR-BIL-004 (minimum/kota/overage) · FR-BIL-006 (bütçe alarmı) · FR-BIL-007 (finans dışa aktarım).
// ALTIN KURAL (BRD §17.7 / FR-IAM-008): yalnız faturalandırma/plan/rate-card + TOPLULAŞTIRILMIŞ kullanım
// metadatası; tenant iş içeriği (çağrı kaydı/transkript/son-müşteri PII) GÖSTERİLMEZ — veri katmanı `assertNoPii`
// ile garanti eder. NOT: tenant org adı tenant kimliğidir (izinli). VENDOR-NEUTRAL (ADR-002): kategori/plan
// adları nötr; somut marka bağlanmaz. RBAC (BRD §17.6): platform_owner=Görüntüle + platform_sre=erişim yok +
// platform_billing=Yönet. UI yalnız görsel kapı; nihai yetki + rate-card/plan/export zorlaması backend'de
// (12.2.x; permission-key billing:read + billing:rate_card:manage + billing:plan:manage + billing:export,
// SAD §7 · §14.4.1 A8). Tüm kullanıcı-görünür metin i18n katalogundan (t()).
import type { CSSProperties } from "react";
import { getServerLocale } from "@/lib/i18n/server";
import { getCatalog, t, formatNumber, formatCurrency, formatDate, type Locale } from "@/lib/i18n";
import { PageHeader, Card, StatusPill, Alert, Table, EmptyState, Button } from "@/lib/ui/components";
import {
  getBilling,
  marginPct,
  marginTone,
  budgetTone,
  billingStatusTone,
  planStatusTone,
  overageMinutes,
  rateMarginPct,
  aggregateUsage,
  overBudgetTenants,
  planName,
  activePlanCount,
  type RateCategory,
  type CostUnit,
  type PlanTier,
  type PlanStatus,
  type BillingStatus,
  type Plan,
  type RateCardEntry,
  type TenantBillingSummary,
} from "@/lib/platform/billing";

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
  const k = (key: string, p?: Record<string, string | number>) => t(cat, `screen.p05.${key}`, p);
  const snap = await getBilling();
  const { rateCard, plans, usage, tenants, currency } = snap;

  const num = (n: number, opts?: Intl.NumberFormatOptions) => formatNumber(locale, n, opts);
  const money = (n: number) => formatCurrency(locale, n, currency);
  const rate = (n: number) => num(n, { minimumFractionDigits: 4, maximumFractionDigits: 4 });
  const pct = (n: number) => num(n, { maximumFractionDigits: 1 });
  const categoryName = (c: RateCategory) => k(`category.${c}`);
  const unitLabel = (u: CostUnit) => k(`unit.${u}`);
  const tierLabel = (tier: PlanTier) => k(`tier.${tier}`);
  const planStatusLabel = (s: PlanStatus) => k(`plan_status.${s}`);
  const billingStatusLabel = (s: BillingStatus) => k(`billing_status.${s}`);

  const usageMargin = marginPct(usage.revenue, usage.providerCost);
  const agg = aggregateUsage(tenants);
  const overBudget = overBudgetTenants(snap);

  return (
    <section data-screen="P-05">
      <PageHeader title={k("title")} description={k("subtitle")} code="P-05" />

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
        {/* Finans dışa aktarım (FR-BIL-007) — UI yalnız görsel kapı; zorlama backend'de (A8). */}
        <Button variant="primary">{k("export_action")}</Button>
      </div>

      {/* Kullanım & gelir özeti (cross-tenant toplulaştırma; FR-BIL-001/002) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", marginBottom: "var(--rmc-space-3)" }}>{k("section.summary")}</h2>
      <div style={grid()}>
        <Kpi label={k("kpi.billed_minutes")} value={num(usage.billedMinutes)} />
        <Kpi label={k("kpi.revenue")} value={money(usage.revenue)} />
        <Kpi label={k("kpi.provider_cost")} value={money(usage.providerCost)} />
        <Kpi label={k("kpi.margin")} value={k("pct_value", { pct: pct(usageMargin) })} tone={`var(--rmc-${marginTone(usageMargin)}-fg)`} />
        <Kpi label={k("kpi.active_plans")} value={num(activePlanCount(plans))} />
        <Kpi label={k("kpi.over_budget")} value={num(overBudget.length)} tone={overBudget.length > 0 ? "var(--rmc-warning-fg)" : undefined} />
      </div>

      {/* Bütçe alarmı (FR-BIL-006: ≥%100 bütçe aşan tenant) */}
      <div style={{ marginBottom: "var(--rmc-space-5)" }}>
        {overBudget.length === 0 ? (
          <Alert tone="success">{k("no_over_budget")}</Alert>
        ) : (
          <Alert tone="warning">{k("over_budget_alert", { count: num(overBudget.length) })}</Alert>
        )}
      </div>

      {/* Rate-card (FR-BIL-002: kategori başına satış birim ücreti + maliyet + marj) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", marginBottom: "var(--rmc-space-3)" }}>{k("section.rate_card")}</h2>
      <Card>
        <Table caption={k("rate_card_caption")}>
          <thead>
            <tr style={{ textAlign: "start", borderBottom: "1px solid var(--rmc-border-subtle)" }}>
              <th style={{ ...cell, textAlign: "start" }}>{k("col.category")}</th>
              <th style={{ ...cell, textAlign: "start" }}>{k("col.unit")}</th>
              <th style={{ ...cell, textAlign: "end" }}>{k("col.unit_rate")}</th>
              <th style={{ ...cell, textAlign: "end" }}>{k("col.unit_cost")}</th>
              <th style={{ ...cell, textAlign: "end" }}>{k("col.margin")}</th>
            </tr>
          </thead>
          <tbody>
            {rateCard.map((e: RateCardEntry) => {
              const m = rateMarginPct(e);
              return (
                <tr key={e.category} style={{ borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                  <td style={cell}>{categoryName(e.category)}</td>
                  <td style={cell}>{unitLabel(e.unit)}</td>
                  <td style={{ ...cell, textAlign: "end" }}>{k("per_unit_value", { amount: rate(e.unitRate), unit: unitLabel(e.unit) })}</td>
                  <td style={{ ...cell, textAlign: "end" }}>{k("per_unit_value", { amount: rate(e.unitCost), unit: unitLabel(e.unit) })}</td>
                  <td style={{ ...cell, textAlign: "end" }}>
                    <StatusPill tone={marginTone(m)}>{k("pct_value", { pct: pct(m) })}</StatusPill>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </Table>
      </Card>

      {/* Plan tanımları (FR-BIL-003/004: taban ücret + dahil kota + overage + bütçe alarmı eşiği) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.plans")}</h2>
      <Card>
        {plans.length === 0 ? (
          <EmptyState message={k("no_plans")} />
        ) : (
          <Table caption={k("plans_caption")}>
            <thead>
              <tr style={{ textAlign: "start", borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.plan")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.tier")}</th>
                <th style={{ ...cell, textAlign: "end" }}>{k("col.monthly_base")}</th>
                <th style={{ ...cell, textAlign: "end" }}>{k("col.included_minutes")}</th>
                <th style={{ ...cell, textAlign: "end" }}>{k("col.overage_rate")}</th>
                <th style={{ ...cell, textAlign: "end" }}>{k("col.budget_alert")}</th>
                <th style={{ ...cell, textAlign: "end" }}>{k("col.active_tenants")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.status")}</th>
              </tr>
            </thead>
            <tbody>
              {plans.map((p: Plan) => (
                <tr key={p.id} style={{ borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                  <td style={cell}>{p.name}</td>
                  <td style={cell}>{tierLabel(p.tier)}</td>
                  <td style={{ ...cell, textAlign: "end" }}>{money(p.monthlyBase)}</td>
                  <td style={{ ...cell, textAlign: "end" }}>{num(p.includedMinutes)}</td>
                  <td style={{ ...cell, textAlign: "end" }}>{k("per_min_value", { amount: money(p.overageRatePerMinute) })}</td>
                  <td style={{ ...cell, textAlign: "end" }}>{k("pct_value", { pct: num(p.budgetAlertThresholdPct) })}</td>
                  <td style={{ ...cell, textAlign: "end" }}>{num(p.activeTenants)}</td>
                  <td style={cell}>
                    <StatusPill tone={planStatusTone(p.status)}>{planStatusLabel(p.status)}</StatusPill>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      {/* Tenant kullanım toplulaştırma (FR-BIL-001/004/006: dakika + overage + bütçe) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.usage")}</h2>
      <Card>
        {tenants.length === 0 ? (
          <EmptyState message={k("no_tenants")} />
        ) : (
          <Table caption={k("usage_caption")}>
            <thead>
              <tr style={{ textAlign: "start", borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.tenant")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.plan")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.region")}</th>
                <th style={{ ...cell, textAlign: "end" }}>{k("col.billed_minutes")}</th>
                <th style={{ ...cell, textAlign: "end" }}>{k("col.overage_minutes")}</th>
                <th style={{ ...cell, textAlign: "end" }}>{k("col.budget_used")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.status")}</th>
              </tr>
            </thead>
            <tbody>
              {tenants.map((tn: TenantBillingSummary) => {
                const over = overageMinutes(tn.billedMinutes, tn.includedMinutes);
                return (
                  <tr key={tn.tenantId} style={{ borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                    <td style={cell}>{tn.tenantName}</td>
                    <td style={cell}>{planName(plans, tn.planId)}</td>
                    <td style={cell}>{t(cat, `region.${tn.region}`)}</td>
                    <td style={{ ...cell, textAlign: "end" }}>{num(tn.billedMinutes)}</td>
                    <td style={{ ...cell, textAlign: "end" }}>{over > 0 ? num(over) : "—"}</td>
                    <td style={{ ...cell, textAlign: "end" }}>
                      <StatusPill tone={budgetTone(tn.budgetUsedPct)}>{k("pct_value", { pct: num(tn.budgetUsedPct) })}</StatusPill>
                    </td>
                    <td style={cell}>
                      <StatusPill tone={billingStatusTone(tn.status)}>{billingStatusLabel(tn.status)}</StatusPill>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        )}
        <p style={{ color: "var(--rmc-text-muted)", fontSize: "var(--rmc-size-sm)", marginTop: "var(--rmc-space-3)" }}>
          {k("usage_total", { minutes: num(agg.billedMinutes), overage: num(agg.overageMinutes) })}
        </p>
      </Card>
    </section>
  );
}
