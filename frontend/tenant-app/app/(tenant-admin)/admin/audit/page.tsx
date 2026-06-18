// WBS 13.3.8 — L1 ekranı T-08 "Audit Log (tenant)" (gerçek içerik; 13.1.1 iskeletinin yerini alır).
//
// İÇERİK (BRD §17.3/§17.6 / FR-IAM-006 + FR-REC-009): tenant'ın KENDİ kullanıcı/sistem DEĞİŞİKLİK ve
// ERİŞİM kayıtları. ÖZET (KPI), BÜTÜNLÜK (WORM + hash zinciri + dış mühürleme — ADR-016), BREAK-GLASS
// erişimleri (FR-IAM-009), KATEGORİ dağılımı ve KAYIT TABLOSU (zaman/aktör/eylem/kaynak/sonuç/bütünlük).
// TENANT-SCOPE (FR-TEN-002): yalnız oturum açan tenant'ın KENDİ audit kayıtları; platform (L0) yalnız
// break-glass erişimi olarak görünür. Scope middleware (13.1.2) + RLS (DB §6.3) ile sabitlenir. HİJYEN
// (BRD §17.7 + §17.6 PII redaction): audit yalnız META veridir — ham çağrı kaydı/transkript/müşteri PII/
// kart audit görünümüne gömülmez; kaynak yalnız REFERANS edilir. GÜVENLİK (NFR 10.6): sır/credential
// konmaz; bütünlük hash'leri yalnız HEX önekidir. RBAC (BRD §17.6): tenant_owner=Yönet · tenant_admin=
// Görüntüle · security_compliance_officer=Yönet · billing_viewer=— · api_developer=—. UI yalnız görsel
// kapı; nihai yetki backend'de (12.2.x, SAD §14.4.1 A8). Kayıtlar değiştirilemez/WORM (FR-IAM-006);
// panelde yazma/silme YOK. Tüm kullanıcı-görünür metin i18n katalogundan (t()).
import type { CSSProperties } from "react";
import { getServerLocale } from "@/lib/i18n/server";
import { getCatalog, t, formatNumber, formatDate } from "@/lib/i18n";
import { PageHeader, Card, StatusPill, Alert, Table, Button, EmptyState } from "@/lib/ui/components";
import {
  getAudit,
  chainBreaks,
  chainIntact,
  breakGlassEntries,
  dataAccessEntries,
  platformEntries,
  platformWithoutBreakGlass,
  deniedEntries,
  failedEntries,
  categoryCounts,
  wormDisabled,
  externalSealDisabled,
  retentionUnset,
  openWarningCount,
  outcomeTone,
  realmTone,
  categoryTone,
  breakGlassTone,
  chainTone,
  wormTone,
  sealTone,
  type AuditCategory,
  type ActorRealm,
  type AuditOutcome,
} from "@/lib/tenant/audit";

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
const thEnd: CSSProperties = { padding: "var(--rmc-space-2)", textAlign: "end" };
const tdEnd: CSSProperties = { padding: "var(--rmc-space-2)", textAlign: "end" };
const rowBorder: CSSProperties = { borderBottom: "1px solid var(--rmc-border-subtle)" };
const muted: CSSProperties = { color: "var(--rmc-text-muted)" };

const CATEGORY_ORDER: AuditCategory[] = ["iam", "config", "data_access", "compliance", "security", "break_glass", "billing"];

export default async function Page() {
  const locale = getServerLocale();
  const cat = getCatalog(locale);
  const k = (key: string, p?: Record<string, string | number>) => t(cat, `screen.t08.${key}`, p);
  const snap = await getAudit();
  const { entries, retention } = snap;

  const breaks = new Set(chainBreaks(entries));
  const intact = chainIntact(entries);
  const bg = breakGlassEntries(entries);
  const dataAccess = dataAccessEntries(entries);
  const platform = platformEntries(entries);
  const platformLeak = new Set(platformWithoutBreakGlass(entries));
  const denied = deniedEntries(entries);
  const failed = failedEntries(entries);
  const counts = categoryCounts(entries);
  const wormOff = wormDisabled(retention);
  const sealOff = externalSealDisabled(retention);
  const retUnset = retentionUnset(retention);
  const openCount = openWarningCount(snap);

  const categoryName = (c: AuditCategory) => k(`category.${c}`);
  const realmName = (r: ActorRealm) => k(`realm.${r}`);
  const outcomeName = (o: AuditOutcome) => k(`outcome.${o}`);
  const dt = (iso: string) => formatDate(locale, new Date(iso), { dateStyle: "short", timeStyle: "short" });

  // Tabloda en yeni üstte (zincir doğrulaması artan sırada yapıldı; gösterim ters).
  const rows = [...entries].reverse();

  return (
    <section data-screen="T-08">
      <PageHeader title={k("title")} description={k("subtitle")} code="T-08" />

      <div style={{ marginBottom: "var(--rmc-space-4)" }}>
        <Alert tone="info">{k("scope_note")}</Alert>
      </div>

      <p style={{ ...muted, fontSize: "var(--rmc-size-sm)", marginTop: 0 }}>
        {k("as_of", { time: formatDate(locale, new Date(snap.generatedAt), { dateStyle: "medium", timeStyle: "short" }) })}
        {" · "}
        <span>{k("tenant")}: {snap.tenantName}</span>
        {" · "}
        <span>{k("window")}: {snap.windowLabel}</span>
      </p>

      {/* Uyarılar */}
      {breaks.size > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="danger">{k("chain_broken_alert", { count: formatNumber(locale, breaks.size) })}</Alert>
        </div>
      )}
      {platformLeak.size > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="danger">{k("platform_no_bg_alert", { count: formatNumber(locale, platformLeak.size) })}</Alert>
        </div>
      )}
      {wormOff && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="danger">{k("worm_off_alert")}</Alert>
        </div>
      )}
      {denied.length > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="warning">{k("denied_alert", { count: formatNumber(locale, denied.length) })}</Alert>
        </div>
      )}
      {retUnset && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="warning">{k("retention_unset_alert")}</Alert>
        </div>
      )}
      {sealOff && (
        <div style={{ margin: "var(--rmc-space-2) 0 var(--rmc-space-4)" }}>
          <Alert tone="warning">{k("seal_off_alert")}</Alert>
        </div>
      )}

      {/* Özet */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", marginBottom: "var(--rmc-space-3)" }}>{k("section.summary")}</h2>
      <div style={grid()}>
        <Kpi label={k("kpi.total")} value={formatNumber(locale, snap.totalCount)} hint={k("kpi.total_hint", { shown: formatNumber(locale, entries.length) })} />
        <Kpi label={k("kpi.integrity")} value={intact ? k("kpi.integrity_ok") : k("kpi.integrity_broken")} hint={k("kpi.integrity_hint")} tone={intact ? "success" : "danger"} />
        <Kpi label={k("kpi.breakglass")} value={formatNumber(locale, bg.length)} hint={k("kpi.breakglass_hint")} tone={bg.length > 0 ? "warning" : "success"} />
        <Kpi label={k("kpi.data_access")} value={formatNumber(locale, dataAccess.length)} hint={k("kpi.data_access_hint")} />
        <Kpi label={k("kpi.failed")} value={formatNumber(locale, failed.length)} hint={k("kpi.failed_hint")} tone={failed.length > 0 ? "warning" : "success"} />
        <Kpi label={k("kpi.warnings")} value={formatNumber(locale, openCount)} hint={k("kpi.warnings_hint")} tone={openCount > 0 ? "danger" : "success"} />
      </div>

      {/* Bütünlük & Saklama (FR-IAM-006 / ADR-016) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.integrity")}</h2>
      <Card>
        <Table caption={k("integrity_caption")}>
          <tbody>
            <tr style={rowBorder}><td style={td}>{k("field.chain")} <code style={muted}>ADR-016</code></td><td style={td}><StatusPill tone={chainTone(!intact)}>{intact ? k("chain_intact") : k("chain_broken")}</StatusPill></td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.worm")} <code style={muted}>FR-IAM-006</code></td><td style={td}><StatusPill tone={wormTone(retention.wormEnabled)}>{retention.wormEnabled ? k("yes") : k("no")}</StatusPill></td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.external_seal")} <code style={muted}>ADR-016</code></td><td style={td}><StatusPill tone={sealTone(retention.externalSeal)}>{retention.externalSeal ? k("yes") : k("no")}</StatusPill></td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.last_sealed")}</td><td style={td}>{retention.externalSeal ? dt(retention.lastSealedAt) : <span style={muted}>{k("dash")}</span>}</td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.retention")}</td><td style={td}>{retUnset ? <StatusPill tone="warning">{k("retention_unset_label")}</StatusPill> : k("days", { n: formatNumber(locale, retention.retentionDays) })}</td></tr>
          </tbody>
        </Table>
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-2)" }}>{k("integrity_hint")}</p>

      {/* Kategori dağılımı */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.categories")}</h2>
      <Card>
        <Table caption={k("categories_caption")}>
          <thead>
            <tr style={rowBorder}>
              <th style={th}>{k("col.category")}</th>
              <th style={thEnd}>{k("col.count")}</th>
            </tr>
          </thead>
          <tbody>
            {CATEGORY_ORDER.map((c) => (
              <tr key={c} style={rowBorder}>
                <td style={td}><StatusPill tone={categoryTone(c)}>{categoryName(c)}</StatusPill></td>
                <td style={tdEnd}>{formatNumber(locale, counts[c] ?? 0)}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>

      {/* Break-glass erişimleri (FR-IAM-009) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.breakglass")}</h2>
      <Card>
        {bg.length === 0 ? (
          <EmptyState message={k("no_breakglass")} />
        ) : (
          <Table caption={k("breakglass_caption")}>
            <thead>
              <tr style={rowBorder}>
                <th style={th}>{k("col.time")}</th>
                <th style={th}>{k("col.actor")}</th>
                <th style={th}>{k("col.action")}</th>
                <th style={th}>{k("col.grant")}</th>
              </tr>
            </thead>
            <tbody>
              {bg.map((e) => (
                <tr key={e.id} style={rowBorder}>
                  <td style={td}>{dt(e.occurredAt)}</td>
                  <td style={td}><StatusPill tone={realmTone(e.actorRealm)}>{realmName(e.actorRealm)}</StatusPill> <code>{e.actorRef}</code></td>
                  <td style={td}><code>{e.action}</code></td>
                  <td style={td}><code>{e.breakGlassId ?? k("dash")}</code></td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-2)" }}>{k("breakglass_hint")}</p>

      {/* Kayıt tablosu */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>
        <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: 0 }}>{k("section.entries")}</h2>
        <Button variant="secondary">{k("action.export")}</Button>
      </div>
      <Card>
        {rows.length === 0 ? (
          <EmptyState message={k("no_entries")} />
        ) : (
          <Table caption={k("entries_caption")}>
            <thead>
              <tr style={rowBorder}>
                <th style={th}>{k("col.time")}</th>
                <th style={th}>{k("col.actor")}</th>
                <th style={th}>{k("col.action")}</th>
                <th style={th}>{k("col.resource")}</th>
                <th style={th}>{k("col.category")}</th>
                <th style={th}>{k("col.outcome")}</th>
                <th style={th}>{k("col.integrity")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((e) => (
                <tr key={e.id} style={rowBorder}>
                  <td style={td}>{dt(e.occurredAt)}</td>
                  <td style={td}><StatusPill tone={realmTone(e.actorRealm)}>{realmName(e.actorRealm)}</StatusPill> <code>{e.actorRef}</code>{e.breakGlass && <> <StatusPill tone={breakGlassTone(true)}>{k("breakglass_tag")}</StatusPill></>}</td>
                  <td style={td}><code>{e.action}</code></td>
                  <td style={td}><code style={muted}>{e.resourceType}</code> <code>{e.resourceRef}</code></td>
                  <td style={td}><StatusPill tone={categoryTone(e.category)}>{categoryName(e.category)}</StatusPill></td>
                  <td style={td}><StatusPill tone={outcomeTone(e.outcome)}>{outcomeName(e.outcome)}</StatusPill></td>
                  <td style={td}>{breaks.has(e.id) ? <StatusPill tone="danger">{k("chain_broken")}</StatusPill> : platformLeak.has(e.id) ? <StatusPill tone="danger">{k("platform_no_bg_label")}</StatusPill> : <code style={muted}>{e.rowHash}</code>}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>{k("entries_hint")}</p>
    </section>
  );
}
