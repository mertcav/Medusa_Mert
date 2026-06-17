// WBS 13.2.3 — L0 ekranı P-03 "Kaynak & Kapasite Yönetimi" (gerçek içerik; 13.1.1 iskeletinin yerini alır).
//
// İÇERİK (BRD §17.3): vCPU/bellek/eşzamanlılık/CPS kotaları, autoscale politikası, scale-to-zero,
// noisy-neighbor koruması. ALTIN KURAL (BRD §17.7 / FR-IAM-008): yalnız kaynak/kapasite metadatası;
// tenant iş içeriği (çağrı kaydı/transkript/son-müşteri PII) GÖSTERİLMEZ — veri katmanı `assertNoPii`
// ile garanti eder. RBAC (BRD §17.6): platform_owner=Yönet + platform_sre=Yönet (billing=erişim yok).
// UI yalnız görsel kapı; nihai yetki + kota/politika zorlaması backend'de Resource Manager Quota
// Service'te (12.2.x, SAD §14.4.1 A8 · §15.2). Tüm kullanıcı-görünür metin i18n katalogundan (t()).
import type { CSSProperties } from "react";
import { getServerLocale } from "@/lib/i18n/server";
import { getCatalog, t, formatNumber, formatDate, type Locale } from "@/lib/i18n";
import { PageHeader, Card, StatusPill, Alert, Table, EmptyState, Button } from "@/lib/ui/components";
import {
  getResources,
  aggregateQuota,
  utilizationPct,
  utilizationTone,
  regionConcurrencyUsed,
  isolationTone,
  scaleStateTone,
  noisyNeighborRisks,
  type Region,
  type Plan,
  type IsolationMode,
  type ScaleToZeroState,
  type QuotaPair,
  type TenantResource,
} from "@/lib/platform/resources";

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <Card>
      <div style={{ color: "var(--rmc-text-muted)", fontSize: "var(--rmc-size-sm)" }}>{label}</div>
      <div style={{ fontSize: "var(--rmc-size-2xl)", fontWeight: 700, color: "var(--rmc-text-primary)" }}>{value}</div>
    </Card>
  );
}

function grid(): CSSProperties {
  return { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "var(--rmc-space-4)", marginBottom: "var(--rmc-space-5)" };
}

const cell: CSSProperties = { padding: "var(--rmc-space-2)" };

export default async function Page() {
  const locale: Locale = getServerLocale();
  const cat = getCatalog(locale);
  const k = (key: string, p?: Record<string, string | number>) => t(cat, `screen.p03.${key}`, p);
  const snap = await getResources();
  const { tenants, regions, autoscale } = snap;

  const num = (n: number, opts?: Intl.NumberFormatOptions) => formatNumber(locale, n, opts);
  const regionName = (r: Region) => t(cat, `region.${r}`);
  const planLabel = (p: Plan) => k(`plan.${p}`);
  const isolationLabel = (m: IsolationMode) => k(`isolation.${m}`);
  const s2zLabel = (s: ScaleToZeroState) => k(`s2z.${s}`);
  const usedOfLimit = (q: QuotaPair) => k("used_of_limit", { used: num(q.used), limit: num(q.limit) });
  const pctText = (used: number, limit: number) => `${num(utilizationPct(used, limit), { maximumFractionDigits: 1 })}%`;

  const risks = noisyNeighborRisks(tenants);

  return (
    <section data-screen="P-03">
      <PageHeader title={k("title")} description={k("subtitle")} code="P-03" />

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
        {/* Politika aksiyonu — UI yalnız görsel kapı; zorlama Resource Manager'da (A8). */}
        <Button variant="primary">{k("edit_policy_action")}</Button>
      </div>

      {/* Platform kapasite özeti (cross-tenant kota toplamı — kaynak verisi) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", marginBottom: "var(--rmc-space-3)" }}>{k("section.capacity")}</h2>
      <div style={grid()}>
        <Kpi label={k("kpi.concurrency")} value={usedOfLimit(aggregateQuota(tenants, "concurrency"))} />
        <Kpi label={k("kpi.cps")} value={usedOfLimit(aggregateQuota(tenants, "cps"))} />
        <Kpi label={k("kpi.vcpu")} value={usedOfLimit(aggregateQuota(tenants, "vcpu"))} />
        <Kpi label={k("kpi.memory")} value={usedOfLimit(aggregateQuota(tenants, "memoryGb"))} />
      </div>

      {/* Noisy-neighbor riski (paylaşımlı izolasyonda yüksek kullanım) */}
      <div style={{ marginBottom: "var(--rmc-space-5)" }}>
        {risks.length === 0 ? (
          <Alert tone="success">{k("no_noisy_neighbor")}</Alert>
        ) : (
          <Alert tone="warning">{k("noisy_neighbor_alert", { count: num(risks.length) })}</Alert>
        )}
      </div>

      {/* Otomatik ölçekleme & scale-to-zero politikası (global) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", marginBottom: "var(--rmc-space-3)" }}>{k("section.autoscale")}</h2>
      <Card>
        <Table caption={k("autoscale.caption")}>
          <tbody>
            <tr style={{ borderBottom: "1px solid var(--rmc-border-subtle)" }}>
              <th style={{ ...cell, textAlign: "start" }} scope="row">{k("autoscale.min_workers")}</th>
              <td style={{ ...cell, textAlign: "end" }}>{num(autoscale.minWorkers)}</td>
            </tr>
            <tr style={{ borderBottom: "1px solid var(--rmc-border-subtle)" }}>
              <th style={{ ...cell, textAlign: "start" }} scope="row">{k("autoscale.max_workers")}</th>
              <td style={{ ...cell, textAlign: "end" }}>{num(autoscale.maxWorkers)}</td>
            </tr>
            <tr style={{ borderBottom: "1px solid var(--rmc-border-subtle)" }}>
              <th style={{ ...cell, textAlign: "start" }} scope="row">{k("autoscale.target_util")}</th>
              <td style={{ ...cell, textAlign: "end" }}>{num(autoscale.targetUtilizationPct)}%</td>
            </tr>
            <tr style={{ borderBottom: "1px solid var(--rmc-border-subtle)" }}>
              <th style={{ ...cell, textAlign: "start" }} scope="row">{k("autoscale.warm_pool")}</th>
              <td style={{ ...cell, textAlign: "end" }}>{num(autoscale.warmPool)}</td>
            </tr>
            <tr style={{ borderBottom: "1px solid var(--rmc-border-subtle)" }}>
              <th style={{ ...cell, textAlign: "start" }} scope="row">{k("autoscale.scale_to_zero_idle")}</th>
              <td style={{ ...cell, textAlign: "end" }}>{k("seconds_value", { seconds: num(autoscale.scaleToZeroIdleSeconds) })}</td>
            </tr>
            <tr>
              <th style={{ ...cell, textAlign: "start" }} scope="row">{k("autoscale.burst")}</th>
              <td style={{ ...cell, textAlign: "end" }}>{k("burst_value", { x: num(autoscale.burstMultiplier) })}</td>
            </tr>
          </tbody>
        </Table>
      </Card>

      {/* Bölge kapasitesi (NFR 10.3: region başına eşzamanlı/CPS tavanı + worker kullanımı) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.regions")}</h2>
      <Card>
        <Table caption={k("regions_caption")}>
          <thead>
            <tr style={{ textAlign: "start", borderBottom: "1px solid var(--rmc-border-subtle)" }}>
              <th style={{ ...cell, textAlign: "start" }}>{k("col.region")}</th>
              <th style={{ ...cell, textAlign: "end" }}>{k("col.capacity")}</th>
              <th style={{ ...cell, textAlign: "end" }}>{k("col.cps_capacity")}</th>
              <th style={{ ...cell, textAlign: "end" }}>{k("col.workers")}</th>
              <th style={{ ...cell, textAlign: "end" }}>{k("col.utilization")}</th>
            </tr>
          </thead>
          <tbody>
            {regions.map((rc) => {
              const used = regionConcurrencyUsed(tenants, rc.region);
              const pct = utilizationPct(used, rc.concurrencyCapacity);
              return (
                <tr key={rc.region} style={{ borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                  <td style={cell}>{regionName(rc.region)}</td>
                  <td style={{ ...cell, textAlign: "end" }}>{num(rc.concurrencyCapacity)}</td>
                  <td style={{ ...cell, textAlign: "end" }}>{num(rc.cpsCapacity)}</td>
                  <td style={{ ...cell, textAlign: "end" }}>{k("used_of_limit", { used: num(rc.activeWorkers), limit: num(rc.maxWorkers) })}</td>
                  <td style={{ ...cell, textAlign: "end" }}>
                    <StatusPill tone={utilizationTone(pct)}>{num(pct, { maximumFractionDigits: 1 })}%</StatusPill>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </Table>
      </Card>

      {/* Tenant kaynak kotaları (eşzamanlılık/CPS/hesaplama kotaları + izolasyon + scale-to-zero) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.quotas")}</h2>
      <Card>
        {tenants.length === 0 ? (
          <EmptyState message={k("no_tenants")} />
        ) : (
          <Table caption={k("quotas_caption")}>
            <thead>
              <tr style={{ textAlign: "start", borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.tenant")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.plan")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.region")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.concurrency")}</th>
                <th style={{ ...cell, textAlign: "end" }}>{k("col.cps")}</th>
                <th style={{ ...cell, textAlign: "end" }}>{k("col.compute")}</th>
                <th style={{ ...cell, textAlign: "end" }}>{k("col.reserved")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.isolation")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.scale_to_zero")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {tenants.map((tn: TenantResource) => {
                const pct = utilizationPct(tn.concurrency.used, tn.concurrency.limit);
                return (
                  <tr key={tn.id} style={{ borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                    <td style={cell}>{tn.name}</td>
                    <td style={cell}>{planLabel(tn.plan)}</td>
                    <td style={cell}>{regionName(tn.region)}</td>
                    <td style={cell}>
                      <div style={{ display: "flex", alignItems: "center", gap: "var(--rmc-space-2)", flexWrap: "wrap" }}>
                        <span>{usedOfLimit(tn.concurrency)}</span>
                        <StatusPill tone={utilizationTone(pct)}>{pctText(tn.concurrency.used, tn.concurrency.limit)}</StatusPill>
                      </div>
                    </td>
                    <td style={{ ...cell, textAlign: "end" }}>{usedOfLimit(tn.cps)}</td>
                    <td style={{ ...cell, textAlign: "end" }}>{k("compute_value", { vcpu: num(tn.vcpu.limit), mem: num(tn.memoryGb.limit) })}</td>
                    <td style={{ ...cell, textAlign: "end" }}>{num(tn.reservedConcurrency)}</td>
                    <td style={cell}>
                      <StatusPill tone={isolationTone(tn.isolation)}>{isolationLabel(tn.isolation)}</StatusPill>
                    </td>
                    <td style={cell}>
                      <StatusPill tone={scaleStateTone(tn.scaleToZero)}>{s2zLabel(tn.scaleToZero)}</StatusPill>
                    </td>
                    <td style={cell}>
                      <Button variant="secondary">{k("action.edit_quota")}</Button>
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
