// WBS 13.2.2 — L0 ekranı P-02 "Tenant Yönetimi & Provisioning" (gerçek içerik; 13.1.1 iskeletinin yerini alır).
//
// İÇERİK (BRD §17.3): tenant oluşturma/askıya alma/silme, plan atama, durum. ALTIN KURAL (BRD §17.7 /
// FR-IAM-008): yalnız tenant kayıt/kaynak metadatası (org adı/plan/durum/bölge/oluşturma/kullanıcı sayısı);
// tenant iş içeriği (çağrı kaydı/transkript/son-müşteri PII) GÖSTERİLMEZ — veri katmanı `assertNoPii` ile
// garanti eder. RBAC (BRD §17.6): bu ekran yalnız platform_owner=Yönet (sre/billing=erişim yok). UI yalnız
// görsel kapı; nihai yetki + provisioning durum geçişi backend'de (12.2.x, SAD §14.4.1 A8). Tüm kullanıcı-
// görünür metin i18n katalogundan (t()).
import type { CSSProperties } from "react";
import { getServerLocale } from "@/lib/i18n/server";
import { getCatalog, t, formatNumber, formatDate, type Locale } from "@/lib/i18n";
import { PageHeader, Card, StatusPill, Alert, Table, EmptyState, Button } from "@/lib/ui/components";
import {
  getTenants,
  countByStatus,
  statusTone,
  lifecycleActions,
  provisioningProgress,
  type Region,
  type TenantStatus,
  type Plan,
  type TenantSummary,
} from "@/lib/platform/tenants";

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
  const k = (key: string, p?: Record<string, string | number>) => t(cat, `screen.p02.${key}`, p);
  const snap = await getTenants();
  const { tenants } = snap;
  const counts = countByStatus(tenants);
  const regionName = (r: Region) => t(cat, `region.${r}`);
  const statusLabel = (s: TenantStatus) => k(`status.${s}`);
  const planLabel = (p: Plan) => k(`plan.${p}`);
  const inProgress = tenants.filter((tn) => tn.status === "provisioning" || tn.status === "deprovisioning");
  const fmtDate = (iso: string) => formatDate(locale, new Date(iso), { dateStyle: "medium" });

  return (
    <section data-screen="P-02">
      <PageHeader title={k("title")} description={k("subtitle")} code="P-02" />

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
        {/* Provisioning aksiyonu — UI yalnız görsel kapı; oluşturma backend'de yetkilendirilir (A8). */}
        <Button variant="primary">{k("create_action")}</Button>
      </div>

      {/* Özet KPI'ları (durum bazında tenant sayımı — kayıt verisi) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", marginBottom: "var(--rmc-space-3)" }}>{k("section.summary")}</h2>
      <div style={grid()}>
        <Kpi label={k("kpi.total")} value={formatNumber(locale, tenants.length)} />
        <Kpi label={k("kpi.active")} value={formatNumber(locale, counts.active)} />
        <Kpi label={k("kpi.suspended")} value={formatNumber(locale, counts.suspended)} />
        <Kpi label={k("kpi.provisioning")} value={formatNumber(locale, counts.provisioning)} />
      </div>

      {/* Süreçteki provisioning/deprovisioning (adım ilerlemesi) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", marginBottom: "var(--rmc-space-3)" }}>{k("section.provisioning")}</h2>
      <Card>
        {inProgress.length === 0 ? (
          <EmptyState message={k("no_provisioning")} />
        ) : (
          <Table caption={k("provisioning_caption")}>
            <thead>
              <tr style={{ textAlign: "start", borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.tenant")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.status")}</th>
                <th style={{ ...cell, textAlign: "end" }}>{k("col.progress")}</th>
              </tr>
            </thead>
            <tbody>
              {inProgress.map((tn) => (
                <tr key={tn.id} style={{ borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                  <td style={cell}>{tn.name}</td>
                  <td style={cell}>
                    <StatusPill tone={statusTone(tn.status)}>{statusLabel(tn.status)}</StatusPill>
                  </td>
                  <td style={{ ...cell, textAlign: "end" }}>
                    {k("progress_step", { step: tn.provisioningStep ?? 0, total: tn.provisioningTotalSteps ?? 0 })}
                    {" · "}
                    {formatNumber(locale, provisioningProgress(tn.provisioningStep ?? 0, tn.provisioningTotalSteps ?? 0), { maximumFractionDigits: 1 })}%
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      {/* Tenant dizini (oluşturma/askıya alma/silme/plan atama aksiyonları durum makinesinden) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.directory")}</h2>
      <Card>
        {tenants.length === 0 ? (
          <EmptyState message={k("no_tenants")} />
        ) : (
          <Table caption={k("directory_caption")}>
            <thead>
              <tr style={{ textAlign: "start", borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.tenant")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.plan")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.region")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.status")}</th>
                <th style={{ ...cell, textAlign: "end" }}>{k("col.users")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.created")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {tenants.map((tn: TenantSummary) => {
                const actions = lifecycleActions(tn.status);
                return (
                  <tr key={tn.id} style={{ borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                    <td style={cell}>{tn.name}</td>
                    <td style={cell}>{planLabel(tn.plan)}</td>
                    <td style={cell}>{regionName(tn.region)}</td>
                    <td style={cell}>
                      <StatusPill tone={statusTone(tn.status)}>{statusLabel(tn.status)}</StatusPill>
                    </td>
                    <td style={{ ...cell, textAlign: "end" }}>{formatNumber(locale, tn.activeUsers)}</td>
                    <td style={cell}>{fmtDate(tn.createdAt)}</td>
                    <td style={cell}>
                      {actions.length === 0 ? (
                        <span style={{ color: "var(--rmc-text-muted)" }}>{k("no_actions")}</span>
                      ) : (
                        <div style={{ display: "flex", gap: "var(--rmc-space-2)", flexWrap: "wrap" }}>
                          {actions.map((a) => (
                            <Button key={a} variant={a === "delete" ? "danger" : "secondary"}>
                              {k(`action.${a}`)}
                            </Button>
                          ))}
                        </div>
                      )}
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
