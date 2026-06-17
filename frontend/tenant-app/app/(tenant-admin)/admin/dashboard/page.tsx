// WBS 13.3.1 — L1 ekranı T-01 "Tenant Dashboard" (gerçek içerik; 13.1.1 iskeletinin yerini alır).
//
// İÇERİK (BRD §17.4): tenant KPI'ları, kullanım, maliyet, atanan kaynak kotası tüketimi.
// TENANT-SCOPE (FR-TEN-002): yalnız oturum açan tenant'ın KENDİ toplulaştırılmış verisi; scope
// middleware (13.1.2) + RLS (§13) ile sabitlenir. DASHBOARD HİJYENİ (BRD §17.7 ruhu): yalnız
// toplulaştırılmış metrik; ham son-müşteri içeriği (çağrı kaydı/transkript/PII) gömülmez — veri katmanı
// `assertNoPii` ile garanti eder. RBAC (BRD §17.6): tenant_owner=Yönet · tenant_admin/
// security_compliance_officer/billing_viewer=Görüntüle · api_developer=erişim yok. UI yalnız görsel kapı;
// nihai yetki backend'de (12.2.x, SAD §14.4.1 A8). Tüm kullanıcı-görünür metin i18n katalogundan (t()).
import type { CSSProperties } from "react";
import { getServerLocale } from "@/lib/i18n/server";
import { getCatalog, t, formatNumber, formatCurrency, formatDate, type Locale } from "@/lib/i18n";
import { PageHeader, Card, StatusPill, Alert, Table, EmptyState } from "@/lib/ui/components";
import {
  getTenantDashboard,
  utilizationPct,
  headroom,
  budgetUsagePct,
  aggregateUsage,
  healthTone,
  utilTone,
  budgetTone,
  type Channel,
  type QuotaResource,
} from "@/lib/tenant/dashboard";

function Kpi({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card>
      <div style={{ color: "var(--rmc-text-muted)", fontSize: "var(--rmc-size-sm)" }}>{label}</div>
      <div style={{ fontSize: "var(--rmc-size-2xl)", fontWeight: 700, color: "var(--rmc-text-primary)" }}>{value}</div>
      {hint && <div style={{ color: "var(--rmc-text-muted)", fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-1)" }}>{hint}</div>}
    </Card>
  );
}

function grid(): CSSProperties {
  return { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "var(--rmc-space-4)", marginBottom: "var(--rmc-space-5)" };
}

function fmtPct(locale: Locale, pct: number): string {
  return `${formatNumber(locale, pct, { maximumFractionDigits: 1 })}%`;
}

function fmtDuration(locale: Locale, seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${formatNumber(locale, m)}:${String(s).padStart(2, "0")}`;
}

export default async function Page() {
  const locale = getServerLocale();
  const cat = getCatalog(locale);
  const k = (key: string, p?: Record<string, string | number>) => t(cat, `screen.t01.${key}`, p);
  const snap = await getTenantDashboard();
  const { kpis, usage, cost, quota } = snap;
  const totals = aggregateUsage(usage);
  const budgetPct = budgetUsagePct(cost.spentMtd, cost.budgetMtd);
  const overBudget = budgetPct >= 100;
  const channelName = (c: Channel) => k(`channel.${c}`);
  const resourceName = (r: QuotaResource) => k(`resource.${r}`);

  return (
    <section data-screen="T-01">
      <PageHeader title={k("title")} description={k("subtitle")} code="T-01" />

      <div style={{ marginBottom: "var(--rmc-space-5)" }}>
        <Alert tone="info">{k("scope_note")}</Alert>
      </div>

      <p style={{ color: "var(--rmc-text-muted)", fontSize: "var(--rmc-size-sm)", marginTop: 0 }}>
        {k("as_of", { time: formatDate(locale, new Date(snap.generatedAt), { dateStyle: "medium", timeStyle: "short" }) })}
        {" · "}
        <span>{k("tenant")}: {snap.tenantName}</span>
        {" · "}
        <span>{k("plan_label")}: {k(`plan.${snap.plan}`)}</span>
        {" · "}
        <span>{k("region")}: {t(cat, `region.${snap.region}`)}</span>
      </p>

      {/* Genel tenant sağlığı */}
      <div style={{ display: "flex", alignItems: "center", gap: "var(--rmc-space-3)", margin: "var(--rmc-space-3) 0 var(--rmc-space-5)" }}>
        <strong style={{ fontSize: "var(--rmc-size-lg)" }}>{k("health.overall")}:</strong>
        <StatusPill tone={healthTone(snap.health)}>{k(`health.${snap.health}`)}</StatusPill>
      </div>

      {/* Tenant KPI'ları */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", marginBottom: "var(--rmc-space-3)" }}>{k("section.kpis")}</h2>
      <div style={grid()}>
        <Kpi label={k("kpi.calls_today")} value={formatNumber(locale, kpis.callsToday)} hint={k("kpi.calls_mtd_hint", { count: formatNumber(locale, kpis.callsMtd) })} />
        <Kpi label={k("kpi.containment")} value={fmtPct(locale, kpis.containmentPct)} hint={k("kpi.containment_hint")} />
        <Kpi label={k("kpi.aht")} value={fmtDuration(locale, kpis.avgHandleSeconds)} hint={k("kpi.aht_hint")} />
        <Kpi label={k("kpi.csat")} value={formatNumber(locale, kpis.csat, { maximumFractionDigits: 1 })} hint={k("kpi.csat_hint")} />
        <Kpi label={k("kpi.success_rate")} value={fmtPct(locale, kpis.successRatePct)} />
        <Kpi label={k("kpi.active_agents")} value={formatNumber(locale, kpis.activeAgents)} />
      </div>

      {/* Kullanım (kanal kırılımı) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", marginBottom: "var(--rmc-space-3)" }}>{k("section.usage")}</h2>
      <div style={grid()}>
        <Kpi label={k("usage.total_calls")} value={formatNumber(locale, totals.calls)} />
        <Kpi label={k("usage.total_minutes")} value={formatNumber(locale, totals.minutes)} hint={k("usage.minutes_hint")} />
      </div>
      <Card>
        <Table caption={k("usage_caption")}>
          <thead>
            <tr style={{ textAlign: "start", borderBottom: "1px solid var(--rmc-border-subtle)" }}>
              <th style={{ padding: "var(--rmc-space-2)", textAlign: "start" }}>{k("col.channel")}</th>
              <th style={{ padding: "var(--rmc-space-2)", textAlign: "end" }}>{k("col.calls")}</th>
              <th style={{ padding: "var(--rmc-space-2)", textAlign: "end" }}>{k("col.minutes")}</th>
            </tr>
          </thead>
          <tbody>
            {usage.map((u) => (
              <tr key={u.channel} style={{ borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                <td style={{ padding: "var(--rmc-space-2)" }}>{channelName(u.channel)}</td>
                <td style={{ padding: "var(--rmc-space-2)", textAlign: "end" }}>{formatNumber(locale, u.calls)}</td>
                <td style={{ padding: "var(--rmc-space-2)", textAlign: "end" }}>{formatNumber(locale, u.minutes)}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>

      {/* Maliyet & bütçe */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.cost")}</h2>
      {overBudget && (
        <div style={{ marginBottom: "var(--rmc-space-4)" }}>
          <Alert tone="danger">{k("budget_alert", { pct: fmtPct(locale, budgetPct) })}</Alert>
        </div>
      )}
      <div style={grid()}>
        <Kpi label={k("kpi.cost_today")} value={formatCurrency(locale, cost.costToday, cost.currency)} />
        <Kpi label={k("kpi.cost_mtd")} value={formatCurrency(locale, cost.costMtd, cost.currency)} />
        <Kpi label={k("kpi.cost_per_minute")} value={formatCurrency(locale, cost.costPerMinute, cost.currency)} />
      </div>
      <Card>
        <div style={{ display: "flex", alignItems: "center", gap: "var(--rmc-space-3)" }}>
          <strong>{k("kpi.budget")}:</strong>
          <span>{formatCurrency(locale, cost.spentMtd, cost.currency)} / {formatCurrency(locale, cost.budgetMtd, cost.currency)}</span>
          <StatusPill tone={budgetTone(budgetPct)}>{fmtPct(locale, budgetPct)}</StatusPill>
        </div>
      </Card>

      {/* Atanan kaynak kotası tüketimi (L0 tarafından atanan) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.quota")}</h2>
      <Card>
        {quota.length === 0 ? (
          <EmptyState message={k("no_quota")} />
        ) : (
          <Table caption={k("quota_caption")}>
            <thead>
              <tr style={{ textAlign: "start", borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                <th style={{ padding: "var(--rmc-space-2)", textAlign: "start" }}>{k("col.resource")}</th>
                <th style={{ padding: "var(--rmc-space-2)", textAlign: "end" }}>{k("col.used")}</th>
                <th style={{ padding: "var(--rmc-space-2)", textAlign: "end" }}>{k("col.limit")}</th>
                <th style={{ padding: "var(--rmc-space-2)", textAlign: "end" }}>{k("col.headroom")}</th>
                <th style={{ padding: "var(--rmc-space-2)", textAlign: "start" }}>{k("col.utilization")}</th>
              </tr>
            </thead>
            <tbody>
              {quota.map((q) => {
                const pct = utilizationPct(q.used, q.limit);
                const unit = q.unit ? ` ${q.unit}` : "";
                return (
                  <tr key={q.resource} style={{ borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                    <td style={{ padding: "var(--rmc-space-2)" }}>{resourceName(q.resource)}</td>
                    <td style={{ padding: "var(--rmc-space-2)", textAlign: "end" }}>{formatNumber(locale, q.used)}{unit}</td>
                    <td style={{ padding: "var(--rmc-space-2)", textAlign: "end" }}>{formatNumber(locale, q.limit)}{unit}</td>
                    <td style={{ padding: "var(--rmc-space-2)", textAlign: "end" }}>{formatNumber(locale, headroom(q.used, q.limit))}{unit}</td>
                    <td style={{ padding: "var(--rmc-space-2)" }}>
                      <StatusPill tone={utilTone(pct)}>{fmtPct(locale, pct)}</StatusPill>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        )}
      </Card>
    </section>
  );
}
