// WBS 13.2.1 — L0 ekranı P-01 "Platform Genel Bakış" (gerçek içerik; 13.1.1 iskeletinin yerini alır).
//
// İÇERİK (BRD §17.3): cross-tenant sağlık, toplam eşzamanlı çağrı, kaynak kullanımı (CPU/bellek/density),
// platform maliyeti. ALTIN KURAL (BRD §17.7 / FR-IAM-008): yalnız TOPLULAŞTIRILMIŞ metrik/kaynak verisi;
// tenant iş içeriği (çağrı kaydı/transkript/PII) GÖSTERİLMEZ — veri katmanı `assertNoPii` ile garanti eder.
// RBAC (BRD §17.2): platform_owner=Yönet · platform_sre/platform_billing=Görüntüle. UI yalnız görsel kapı;
// nihai yetki backend'de (12.2.x, SAD §14.4.1 A8). Tüm kullanıcı-görünür metin i18n katalogundan (t()).
import type { CSSProperties } from "react";
import { getServerLocale } from "@/lib/i18n/server";
import { getCatalog, t, formatNumber, formatCurrency, formatDate, type Locale } from "@/lib/i18n";
import { PageHeader, Card, StatusPill, Alert, Table, EmptyState } from "@/lib/ui/components";
import {
  getPlatformOverview,
  rollupHealth,
  headroom,
  healthTone,
  severityTone,
  type Region,
} from "@/lib/platform/overview";

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

export default async function Page() {
  const locale = getServerLocale();
  const cat = getCatalog(locale);
  const k = (key: string, p?: Record<string, string | number>) => t(cat, `screen.p01.${key}`, p);
  const snap = await getPlatformOverview();
  const { kpis, regions, cost, alerts } = snap;
  const overall = rollupHealth(regions);
  const regionName = (r: Region) => t(cat, `region.${r}`);

  return (
    <section data-screen="P-01">
      <PageHeader title={k("title")} description={k("subtitle")} code="P-01" />

      <div style={{ marginBottom: "var(--rmc-space-5)" }}>
        <Alert tone="info">{k("view_only_note")}</Alert>
      </div>

      <p style={{ color: "var(--rmc-text-muted)", fontSize: "var(--rmc-size-sm)", marginTop: 0 }}>
        {k("as_of", { time: formatDate(locale, new Date(snap.generatedAt), { dateStyle: "medium", timeStyle: "short" }) })}
        {" · "}
        <span>{k("kpi.active_tenants")}: {formatNumber(locale, kpis.activeTenants)}</span>
      </p>

      {/* Cross-tenant genel sağlık */}
      <div style={{ display: "flex", alignItems: "center", gap: "var(--rmc-space-3)", margin: "var(--rmc-space-3) 0 var(--rmc-space-5)" }}>
        <strong style={{ fontSize: "var(--rmc-size-lg)" }}>{k("health.overall")}:</strong>
        <StatusPill tone={healthTone(overall)}>{k(`health.${overall}`)}</StatusPill>
      </div>

      {/* Eşzamanlılık & kapasite */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", marginBottom: "var(--rmc-space-3)" }}>{k("section.capacity")}</h2>
      <div style={grid()}>
        <Kpi label={k("kpi.concurrent_calls")} value={formatNumber(locale, kpis.concurrentCalls)} />
        <Kpi label={k("kpi.cps")} value={formatNumber(locale, kpis.callsPerSecond)} />
        <Kpi label={k("kpi.capacity")} value={formatNumber(locale, kpis.capacityConcurrent)} />
        <Kpi label={k("kpi.headroom")} value={formatNumber(locale, headroom(kpis.concurrentCalls, kpis.capacityConcurrent))} />
      </div>

      {/* Kaynak kullanımı (CPU/bellek/density) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", marginBottom: "var(--rmc-space-3)" }}>{k("section.resources")}</h2>
      <div style={grid()}>
        <Kpi label={k("kpi.cpu")} value={fmtPct(locale, kpis.cpuUtilizationPct)} />
        <Kpi label={k("kpi.memory")} value={fmtPct(locale, kpis.memoryUtilizationPct)} />
        <Kpi label={k("kpi.density")} value={formatNumber(locale, kpis.workerDensity)} hint={k("kpi.density_hint")} />
        <Kpi label={k("kpi.mem_per_session")} value={`${formatNumber(locale, kpis.memPerSessionMb, { maximumFractionDigits: 1 })} MB`} hint={k("kpi.mem_per_session_hint")} />
      </div>

      {/* Platform maliyeti */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", marginBottom: "var(--rmc-space-3)" }}>{k("section.cost")}</h2>
      <div style={grid()}>
        <Kpi label={k("kpi.cost_today")} value={formatCurrency(locale, cost.platformCostToday, cost.currency)} />
        <Kpi label={k("kpi.cost_mtd")} value={formatCurrency(locale, cost.platformCostMtd, cost.currency)} />
        <Kpi label={k("kpi.cost_per_minute")} value={formatCurrency(locale, cost.costPerMinute, cost.currency)} />
      </div>

      {/* Bölge sağlığı (cross-tenant) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", marginBottom: "var(--rmc-space-3)" }}>{k("section.regions")}</h2>
      <Card>
        <Table caption={k("regions_caption")}>
          <thead>
            <tr style={{ textAlign: "start", borderBottom: "1px solid var(--rmc-border-subtle)" }}>
              <th style={{ padding: "var(--rmc-space-2)", textAlign: "start" }}>{k("col.region")}</th>
              <th style={{ padding: "var(--rmc-space-2)", textAlign: "start" }}>{k("col.health")}</th>
              <th style={{ padding: "var(--rmc-space-2)", textAlign: "end" }}>{k("col.concurrent")}</th>
              <th style={{ padding: "var(--rmc-space-2)", textAlign: "end" }}>{k("col.utilization")}</th>
            </tr>
          </thead>
          <tbody>
            {regions.map((r) => (
              <tr key={r.region} style={{ borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                <td style={{ padding: "var(--rmc-space-2)" }}>{regionName(r.region)}</td>
                <td style={{ padding: "var(--rmc-space-2)" }}>
                  <StatusPill tone={healthTone(r.health)}>{k(`health.${r.health}`)}</StatusPill>
                </td>
                <td style={{ padding: "var(--rmc-space-2)", textAlign: "end" }}>{formatNumber(locale, r.concurrentCalls)}</td>
                <td style={{ padding: "var(--rmc-space-2)", textAlign: "end" }}>{fmtPct(locale, r.utilizationPct)}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>

      {/* Aktif platform alarmları (yalnız metrik) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.alerts")}</h2>
      <Card>
        {alerts.length === 0 ? (
          <EmptyState message={k("no_alerts")} />
        ) : (
          <Table caption={k("alerts_caption")}>
            <thead>
              <tr style={{ borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                <th style={{ padding: "var(--rmc-space-2)", textAlign: "start" }}>{k("col.alert")}</th>
                <th style={{ padding: "var(--rmc-space-2)", textAlign: "start" }}>{k("col.severity")}</th>
                <th style={{ padding: "var(--rmc-space-2)", textAlign: "end" }}>{k("col.since")}</th>
              </tr>
            </thead>
            <tbody>
              {alerts.map((a) => (
                <tr key={a.id} style={{ borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                  <td style={{ padding: "var(--rmc-space-2)" }}>{t(cat, a.key)}</td>
                  <td style={{ padding: "var(--rmc-space-2)" }}>
                    <StatusPill tone={severityTone(a.severity)}>{k(`severity.${a.severity}`)}</StatusPill>
                  </td>
                  <td style={{ padding: "var(--rmc-space-2)", textAlign: "end" }}>{k("alert.since_minutes", { minutes: a.sinceMinutes })}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </section>
  );
}
