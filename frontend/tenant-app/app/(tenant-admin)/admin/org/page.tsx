// WBS 13.3.2 — L1 ekranı T-02 "Organizasyon & Yapı" (gerçek içerik; 13.1.1 iskeletinin yerini alır).
//
// İÇERİK (BRD §17.4 / FR-TEN-003): tenant altında marka, departman, ülke ve proje yapıları.
// TENANT-SCOPE (FR-TEN-002): yalnız oturum açan tenant'ın KENDİ org yapısı; scope middleware (13.1.2) + RLS
// (§13) ile sabitlenir. HİJYEN (BRD §17.7 ruhu): yalnız konfigürasyon metadatası; ham son-müşteri içeriği
// (çağrı kaydı/transkript/PII) gömülmez — veri katmanı `assertNoPii` ile garanti eder. RBAC (BRD §17.6):
// tenant_owner=Yönet · tenant_admin=Yönet · diğerleri=erişim yok. UI yalnız görsel kapı; nihai yetki
// backend'de (12.2.x, SAD §14.4.1 A8). Tüm kullanıcı-görünür metin i18n katalogundan (t()).
import type { CSSProperties } from "react";
import { getServerLocale } from "@/lib/i18n/server";
import { getCatalog, t, formatNumber, formatDate } from "@/lib/i18n";
import { PageHeader, Card, StatusPill, Alert, Table, Button, EmptyState } from "@/lib/ui/components";
import {
  getOrgStructure,
  countByType,
  countByStatus,
  projectsForUnit,
  orphanProjects,
  unitStatusTone,
  projectStatusTone,
  type OrgUnit,
  type OrgUnitType,
  type OrgUnitStatus,
  type ProjectStatus,
} from "@/lib/tenant/organization";

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
  return { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "var(--rmc-space-4)", marginBottom: "var(--rmc-space-5)" };
}

const th: CSSProperties = { padding: "var(--rmc-space-2)", textAlign: "start" };
const thEnd: CSSProperties = { padding: "var(--rmc-space-2)", textAlign: "end" };
const td: CSSProperties = { padding: "var(--rmc-space-2)" };
const tdEnd: CSSProperties = { padding: "var(--rmc-space-2)", textAlign: "end" };
const rowBorder: CSSProperties = { borderBottom: "1px solid var(--rmc-border-subtle)" };

export default async function Page() {
  const locale = getServerLocale();
  const cat = getCatalog(locale);
  const k = (key: string, p?: Record<string, string | number>) => t(cat, `screen.t02.${key}`, p);
  const snap = await getOrgStructure();
  const { units, projects } = snap;

  const byType = countByType(units);
  const byStatus = countByStatus(units);
  const orphans = new Set(orphanProjects(projects, units));

  const typeName = (ty: OrgUnitType) => k(`type.${ty}`);
  const unitStatusName = (s: OrgUnitStatus) => k(`unit_status.${s}`);
  const projectStatusName = (s: ProjectStatus) => k(`project_status.${s}`);
  const unitById = new Map(units.map((u) => [u.id, u] as const));
  const refName = (id: string | null) => (id && unitById.has(id) ? unitById.get(id)!.name : id ?? "—");
  const parentName = (u: OrgUnit) => (u.parentId ? refName(u.parentId) : "—");

  return (
    <section data-screen="T-02">
      <PageHeader title={k("title")} description={k("subtitle")} code="T-02" />

      <div style={{ marginBottom: "var(--rmc-space-4)" }}>
        <Alert tone="info">{k("scope_note")}</Alert>
      </div>

      <p style={{ color: "var(--rmc-text-muted)", fontSize: "var(--rmc-size-sm)", marginTop: 0 }}>
        {k("as_of", { time: formatDate(locale, new Date(snap.generatedAt), { dateStyle: "medium", timeStyle: "short" }) })}
        {" · "}
        <span>{k("tenant")}: {snap.tenantName}</span>
      </p>

      {orphans.size > 0 && (
        <div style={{ margin: "var(--rmc-space-3) 0 var(--rmc-space-4)" }}>
          <Alert tone="warning">{k("orphan_alert", { count: formatNumber(locale, orphans.size) })}</Alert>
        </div>
      )}

      {/* Özet */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", marginBottom: "var(--rmc-space-3)" }}>{k("section.summary")}</h2>
      <div style={grid()}>
        <Kpi label={k("kpi.brands")} value={formatNumber(locale, byType.brand)} />
        <Kpi label={k("kpi.departments")} value={formatNumber(locale, byType.department)} />
        <Kpi label={k("kpi.countries")} value={formatNumber(locale, byType.country)} />
        <Kpi label={k("kpi.projects")} value={formatNumber(locale, projects.length)} />
        <Kpi label={k("kpi.active_units")} value={formatNumber(locale, byStatus.active)} hint={k("kpi.active_units_hint", { total: formatNumber(locale, units.length) })} />
      </div>

      {/* Organizasyon birimleri (marka / departman / ülke) */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>
        <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: 0 }}>{k("section.units")}</h2>
        <Button variant="primary">{k("action.new_unit")}</Button>
      </div>
      <Card>
        {units.length === 0 ? (
          <EmptyState message={k("no_units")} />
        ) : (
          <Table caption={k("units_caption")}>
            <thead>
              <tr style={rowBorder}>
                <th style={th}>{k("col.code")}</th>
                <th style={th}>{k("col.name")}</th>
                <th style={th}>{k("col.type")}</th>
                <th style={th}>{k("col.parent")}</th>
                <th style={thEnd}>{k("col.users")}</th>
                <th style={thEnd}>{k("col.agents")}</th>
                <th style={thEnd}>{k("col.projects")}</th>
                <th style={th}>{k("col.status")}</th>
              </tr>
            </thead>
            <tbody>
              {units.map((u) => (
                <tr key={u.id} style={rowBorder}>
                  <td style={td}><code>{u.code}</code></td>
                  <td style={td}>{u.name}</td>
                  <td style={td}>{typeName(u.type)}</td>
                  <td style={td}>{parentName(u)}</td>
                  <td style={tdEnd}>{formatNumber(locale, u.userCount)}</td>
                  <td style={tdEnd}>{formatNumber(locale, u.agentCount)}</td>
                  <td style={tdEnd}>{formatNumber(locale, projectsForUnit(projects, u.id))}</td>
                  <td style={td}>
                    <StatusPill tone={unitStatusTone(u.status)}>{unitStatusName(u.status)}</StatusPill>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <p style={{ color: "var(--rmc-text-muted)", fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-2)" }}>{k("scope_hint")}</p>

      {/* Projeler */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>
        <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: 0 }}>{k("section.projects")}</h2>
        <Button variant="primary">{k("action.new_project")}</Button>
      </div>
      <Card>
        {projects.length === 0 ? (
          <EmptyState message={k("no_projects")} />
        ) : (
          <Table caption={k("projects_caption")}>
            <thead>
              <tr style={rowBorder}>
                <th style={th}>{k("col.code")}</th>
                <th style={th}>{k("col.name")}</th>
                <th style={th}>{k("col.brand")}</th>
                <th style={th}>{k("col.department")}</th>
                <th style={th}>{k("col.country")}</th>
                <th style={thEnd}>{k("col.agents")}</th>
                <th style={th}>{k("col.status")}</th>
              </tr>
            </thead>
            <tbody>
              {projects.map((p) => (
                <tr key={p.id} style={rowBorder}>
                  <td style={td}>
                    <code>{p.code}</code>
                    {orphans.has(p.id) && <> <StatusPill tone="warning">{k("orphan_badge")}</StatusPill></>}
                  </td>
                  <td style={td}>{p.name}</td>
                  <td style={td}>{refName(p.brandRef)}</td>
                  <td style={td}>{refName(p.departmentRef)}</td>
                  <td style={td}>{refName(p.countryRef)}</td>
                  <td style={tdEnd}>{formatNumber(locale, p.agentCount)}</td>
                  <td style={td}>
                    <StatusPill tone={projectStatusTone(p.status)}>{projectStatusName(p.status)}</StatusPill>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </section>
  );
}
