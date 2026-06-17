// WBS 13.2.4 — L0 ekranı P-04 "Sağlayıcı & Entegrasyon Sağlığı" (gerçek içerik; 13.1.1 iskeletinin yerini alır).
//
// İÇERİK (BRD §17.3): STT/TTS/LLM/telekom adapter durumu, fallback/routing varsayılanları, sağlayıcı maliyeti.
// ALTIN KURAL (BRD §17.7 / FR-IAM-008): yalnız sağlayıcı/adapter sağlık + yönlendirme + maliyet metadatası;
// tenant iş içeriği (çağrı kaydı/transkript/son-müşteri PII) GÖSTERİLMEZ — veri katmanı `assertNoPii` ile
// garanti eder. VENDOR-NEUTRAL (ADR-002; BRD §19): kategori başına ≥2 sağlayıcı + fallback; somut marka
// bağlanmaz. RBAC (BRD §17.6): platform_owner=Yönet + platform_sre=Yönet + platform_billing=Görüntüle.
// UI yalnız görsel kapı; nihai yetki + yönlendirme/fallback zorlaması backend'de adapter SPI üzerinden
// (12.2.x; permission-key provider:health:read + provider:routing:manage, SAD §7/§8 · §14.4.1 A8).
// Tüm kullanıcı-görünür metin i18n katalogundan (t()).
import type { CSSProperties } from "react";
import { getServerLocale } from "@/lib/i18n/server";
import { getCatalog, t, formatNumber, formatDate, type Locale } from "@/lib/i18n";
import { PageHeader, Card, StatusPill, Alert, Table, EmptyState, Button } from "@/lib/ui/components";
import {
  getProviders,
  categoryAdapters,
  categoryHealth,
  redundancyOk,
  redundancyRisks,
  isFallbackActive,
  activeFallbackCount,
  openCircuitCount,
  countByHealth,
  aggregateCost,
  healthTone,
  circuitTone,
  errorRateTone,
  type ProviderCategory,
  type HealthState,
  type CircuitState,
  type AdapterRole,
  type CostUnit,
  type Adapter,
} from "@/lib/platform/providers";

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
  const k = (key: string, p?: Record<string, string | number>) => t(cat, `screen.p04.${key}`, p);
  const snap = await getProviders();
  const { categories, adapters } = snap;

  const num = (n: number, opts?: Intl.NumberFormatOptions) => formatNumber(locale, n, opts);
  const money = (n: number) => num(n, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const categoryName = (c: ProviderCategory) => k(`category.${c}`);
  const healthLabel = (h: HealthState) => k(`health.${h}`);
  const circuitLabel = (c: CircuitState) => k(`circuit.${c}`);
  const roleLabel = (r: AdapterRole) => k(`role.${r}`);
  const unitLabel = (u: CostUnit) => k(`unit.${u}`);
  const adapterName = (id: string) => adapters.find((a) => a.id === id)?.name ?? id;

  const counts = countByHealth(adapters);
  const risks = redundancyRisks(snap);
  const totalCost = aggregateCost(categories);

  return (
    <section data-screen="P-04">
      <PageHeader title={k("title")} description={k("subtitle")} code="P-04" />

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
        {/* Yönlendirme aksiyonu — UI yalnız görsel kapı; zorlama adapter SPI'da (A8). */}
        <Button variant="primary">{k("edit_routing_action")}</Button>
      </div>

      {/* Genel sağlık özeti (adapter sağlık sayımı + circuit + fallback + maliyet) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", marginBottom: "var(--rmc-space-3)" }}>{k("section.summary")}</h2>
      <div style={grid()}>
        <Kpi label={k("kpi.healthy")} value={num(counts.healthy)} tone="var(--rmc-success-fg)" />
        <Kpi label={k("kpi.degraded")} value={num(counts.degraded)} tone={counts.degraded > 0 ? "var(--rmc-warning-fg)" : undefined} />
        <Kpi label={k("kpi.down")} value={num(counts.down)} tone={counts.down > 0 ? "var(--rmc-danger-fg)" : undefined} />
        <Kpi label={k("kpi.open_circuits")} value={num(openCircuitCount(adapters))} tone={openCircuitCount(adapters) > 0 ? "var(--rmc-danger-fg)" : undefined} />
        <Kpi label={k("kpi.active_fallbacks")} value={num(activeFallbackCount(snap))} tone={activeFallbackCount(snap) > 0 ? "var(--rmc-warning-fg)" : undefined} />
        <Kpi label={k("kpi.cost_today")} value={money(totalCost.today)} />
        <Kpi label={k("kpi.cost_mtd")} value={money(totalCost.mtd)} />
      </div>

      {/* Dayanıklılık (BRD §19 ≥2 çalışır sağlayıcı kuralı) */}
      <div style={{ marginBottom: "var(--rmc-space-5)" }}>
        {risks.length === 0 ? (
          <Alert tone="success">{k("no_redundancy_risk")}</Alert>
        ) : (
          <Alert tone="danger">{k("redundancy_alert", { count: num(risks.length) })}</Alert>
        )}
      </div>

      {/* Fallback & yönlendirme varsayılanları (kategori başına; SAD §8.3) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", marginBottom: "var(--rmc-space-3)" }}>{k("section.routing")}</h2>
      <Card>
        <Table caption={k("routing_caption")}>
          <thead>
            <tr style={{ textAlign: "start", borderBottom: "1px solid var(--rmc-border-subtle)" }}>
              <th style={{ ...cell, textAlign: "start" }}>{k("col.category")}</th>
              <th style={{ ...cell, textAlign: "start" }}>{k("col.health")}</th>
              <th style={{ ...cell, textAlign: "start" }}>{k("col.primary")}</th>
              <th style={{ ...cell, textAlign: "start" }}>{k("col.fallback_chain")}</th>
              <th style={{ ...cell, textAlign: "start" }}>{k("col.deterministic")}</th>
              <th style={{ ...cell, textAlign: "start" }}>{k("col.redundancy")}</th>
            </tr>
          </thead>
          <tbody>
            {categories.map((c) => {
              const health = categoryHealth(adapters, c.category);
              const fbActive = isFallbackActive(snap, c.category);
              const redOk = redundancyOk(adapters, c.category);
              return (
                <tr key={c.category} style={{ borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                  <td style={cell}>{categoryName(c.category)}</td>
                  <td style={cell}>
                    <StatusPill tone={healthTone(health)}>{healthLabel(health)}</StatusPill>
                  </td>
                  <td style={cell}>
                    <div style={{ display: "flex", alignItems: "center", gap: "var(--rmc-space-2)", flexWrap: "wrap" }}>
                      <span>{adapterName(c.primaryId)}</span>
                      <StatusPill tone={fbActive ? "warning" : "neutral"}>{fbActive ? k("fallback_active_badge") : k("fallback_standby_badge")}</StatusPill>
                    </div>
                  </td>
                  <td style={cell}>{c.fallbackOrder.map(adapterName).join(" → ")}</td>
                  <td style={cell}>{c.deterministicFallback ? k("deterministic_yes") : k("deterministic_no")}</td>
                  <td style={cell}>
                    <StatusPill tone={redOk ? "success" : "danger"}>{redOk ? healthLabel("healthy") : k("col.redundancy")}</StatusPill>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </Table>
      </Card>

      {/* Adapter durumu (sağlık + circuit breaker + hata oranı + p95 gecikme) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.adapters")}</h2>
      <Card>
        {adapters.length === 0 ? (
          <EmptyState message={k("no_adapters")} />
        ) : (
          <Table caption={k("adapters_caption")}>
            <thead>
              <tr style={{ textAlign: "start", borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.adapter")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.category")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.role")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.health")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.circuit")}</th>
                <th style={{ ...cell, textAlign: "end" }}>{k("col.error_rate")}</th>
                <th style={{ ...cell, textAlign: "end" }}>{k("col.latency")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.region")}</th>
              </tr>
            </thead>
            <tbody>
              {adapters.map((a: Adapter) => (
                <tr key={a.id} style={{ borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                  <td style={cell}>{a.name}</td>
                  <td style={cell}>{categoryName(a.category)}</td>
                  <td style={cell}>{roleLabel(a.role)}</td>
                  <td style={cell}>
                    <StatusPill tone={healthTone(a.health)}>{healthLabel(a.health)}</StatusPill>
                  </td>
                  <td style={cell}>
                    <StatusPill tone={circuitTone(a.circuit)}>{circuitLabel(a.circuit)}</StatusPill>
                  </td>
                  <td style={{ ...cell, textAlign: "end" }}>
                    <StatusPill tone={errorRateTone(a.errorRatePct)}>{k("error_rate_value", { pct: num(a.errorRatePct, { maximumFractionDigits: 1 }) })}</StatusPill>
                  </td>
                  <td style={{ ...cell, textAlign: "end" }}>{k("latency_value", { ms: num(a.p95LatencyMs) })}</td>
                  <td style={cell}>{t(cat, `region.${a.region}`)}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      {/* Sağlayıcı maliyeti (kategori başına bugün/MTD + birim maliyet) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.cost")}</h2>
      <Card>
        <Table caption={k("cost_caption")}>
          <thead>
            <tr style={{ textAlign: "start", borderBottom: "1px solid var(--rmc-border-subtle)" }}>
              <th style={{ ...cell, textAlign: "start" }}>{k("col.category")}</th>
              <th style={{ ...cell, textAlign: "end" }}>{k("col.cost_today")}</th>
              <th style={{ ...cell, textAlign: "end" }}>{k("col.cost_mtd")}</th>
              <th style={{ ...cell, textAlign: "end" }}>{k("col.unit_cost")}</th>
            </tr>
          </thead>
          <tbody>
            {categories.map((c) => (
              <tr key={c.category} style={{ borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                <td style={cell}>{categoryName(c.category)}</td>
                <td style={{ ...cell, textAlign: "end" }}>{money(c.cost.today)}</td>
                <td style={{ ...cell, textAlign: "end" }}>{money(c.cost.mtd)}</td>
                <td style={{ ...cell, textAlign: "end" }}>{k("unit_cost_value", { cost: num(c.cost.unitCost, { maximumFractionDigits: 4 }), unit: unitLabel(c.cost.unit) })}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
    </section>
  );
}
