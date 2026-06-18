// WBS 13.4.3 — L2 ekranı A-03 "Agent Listesi" (gerçek içerik; 13.1.1 iskeletinin yerini alır).
//
// İÇERİK (BRD §17.5 A-03 "Tüm agent'lar ve durumları"): tenant'ın tanımlı Voice AI agent'larının YÖNETİM/
// ENVANTER görünümü. ÖZET (KPI), YAŞAM DÖNGÜSÜ dağılımı (draft/test/staging/production/archived — FR-AGT-005),
// DİKKAT GEREKTİREN agent'lar (test bloklu FR-AGT-010 ∪ bağlantısız production FR-AGT-007 ∪ aktif sürümsüz
// production FR-AGT-006) ve TÜM AGENT TABLOSU (ad/amaç · durum · mod FR-AGT-003 · diller FR-AGT-002 ·
// sürüm/yayın FR-AGT-004/006 · test kapısı · bağlantı · güncelleme). Bu ekran KONFİGÜRASYON/ENVANTER'dir —
// A-02 gibi gerçek zamanlı DEĞİL (FR-ANA-012 dışı). TENANT-SCOPE (FR-TEN-002): yalnız oturum açan tenant'ın
// agent'ları (middleware 13.1.2 + RLS DB §6.3). HİJYEN (BRD §17.7 + §17.6): yalnız KONFİGÜRASYON META;
// ham müşteri içeriği/PII gömülmez; prompt gövdesi/tool sırrı derin aksiyon (A-06/A-09, görsel kapı).
// GÜVENLİK (NFR 10.6): sır konmaz. RBAC (BRD §17.6): operations_manager=Yönet · conversation_designer=
// Düzenle · qa_analyst=Görüntüle · human_agent=—. UI yalnız görsel kapı; oluştur/düzenle/yayınla/rollback
// nihai yetki + işlem backend'de. Tüm kullanıcı-görünür metin i18n katalogundan (t()).
import type { CSSProperties } from "react";
import { getServerLocale } from "@/lib/i18n/server";
import { getCatalog, t, formatNumber, formatDate } from "@/lib/i18n";
import { PageHeader, Card, StatusPill, Alert, Table, Button, EmptyState } from "@/lib/ui/components";
import {
  getAgentList,
  countByLifecycle,
  countByMode,
  productionAgents,
  inDevelopmentAgents,
  hasPendingChanges,
  pendingChangesAgents,
  testBlocked,
  testBlockedAgents,
  unboundProduction,
  unboundProductionAgents,
  missingActiveVersion,
  missingActiveVersionAgents,
  variantAgents,
  distinctLanguages,
  attentionAgents,
  openAttentionCount,
  lifecycleTone,
  modeTone,
  testTone,
  pendingTone,
  variantTone,
  LIFECYCLE_ORDER,
  type AgentLifecycle,
  type FlowMode,
  type TestStatus,
  type AgentSummary,
} from "@/lib/tenant/agents";

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

export default async function Page() {
  const locale = getServerLocale();
  const cat = getCatalog(locale);
  const k = (key: string, p?: Record<string, string | number>) => t(cat, `screen.a03.${key}`, p);
  const view = await getAgentList();
  const { agents } = view;

  const byLifecycle = countByLifecycle(agents);
  const byMode = countByMode(agents);
  const prod = productionAgents(agents);
  const dev = inDevelopmentAgents(agents);
  const pending = pendingChangesAgents(agents);
  const blocked = testBlockedAgents(agents);
  const unbound = unboundProductionAgents(agents);
  const missingVer = missingActiveVersionAgents(agents);
  const variants = variantAgents(agents);
  const attention = attentionAgents(agents);
  const langs = distinctLanguages(agents);
  const openCount = openAttentionCount(view);

  const lifecycleName = (s: AgentLifecycle) => k(`lifecycle.${s}`);
  const modeName = (m: FlowMode) => k(`mode.${m}`);
  const testName = (s: TestStatus) => k(`test.${s}`);
  const dt = (iso: string) => formatDate(locale, new Date(iso), { dateStyle: "short", timeStyle: "short" });

  const versionCell = (a: AgentSummary) => {
    const active = a.activeVersionNo === null ? k("version.none") : k("version.v", { n: formatNumber(locale, a.activeVersionNo) });
    return (
      <>
        <span>{k("version.active")}: {active}</span>
        <br />
        <span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{k("version.latest", { n: formatNumber(locale, a.latestVersionNo) })}</span>
        {hasPendingChanges(a) && <> <StatusPill tone={pendingTone(true)}>{k("flag.pending")}</StatusPill></>}
      </>
    );
  };

  const bindingCell = (a: AgentSummary) => (
    <>
      <span>{k("binding.numbers", { n: formatNumber(locale, a.boundNumbers) })}</span>
      <br />
      <span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{k("binding.campaigns", { n: formatNumber(locale, a.boundCampaigns) })}</span>
    </>
  );

  const agentRow = (a: AgentSummary) => (
    <tr key={a.id} style={rowBorder}>
      <td style={td}>
        <code style={muted}>{a.agentRef}</code> {a.name}
        {a.isVariant && <> <StatusPill tone={variantTone(true)}>{k("flag.variant")}</StatusPill></>}
        <br />
        <span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{a.purpose}{a.orgUnit ? ` · ${a.orgUnit}` : ""}</span>
      </td>
      <td style={td}><StatusPill tone={lifecycleTone(a.lifecycle)}>{lifecycleName(a.lifecycle)}</StatusPill></td>
      <td style={td}><StatusPill tone={modeTone(a.mode)}>{modeName(a.mode)}</StatusPill></td>
      <td style={td}>{a.languages.map((l) => l.toUpperCase()).join(", ")}</td>
      <td style={td}>{versionCell(a)}</td>
      <td style={td}><StatusPill tone={testTone(a.testStatus)}>{testName(a.testStatus)}</StatusPill></td>
      <td style={tdEnd}>{bindingCell(a)}</td>
      <td style={td}><span style={{ fontSize: "var(--rmc-size-xs)" }}>{dt(a.updatedAt)}</span></td>
      <td style={td}>
        {testBlocked(a) && <StatusPill tone="danger">{k("flag.test")}</StatusPill>}
        {unboundProduction(a) && <> <StatusPill tone="warning">{k("flag.unbound")}</StatusPill></>}
        {missingActiveVersion(a) && <> <StatusPill tone="danger">{k("flag.no_version")}</StatusPill></>}
        {!testBlocked(a) && !unboundProduction(a) && !missingActiveVersion(a) && <span style={muted}>{k("dash")}</span>}
      </td>
    </tr>
  );

  const tableHead = (
    <thead>
      <tr style={rowBorder}>
        <th style={th}>{k("col.agent")}</th>
        <th style={th}>{k("col.lifecycle")}</th>
        <th style={th}>{k("col.mode")}</th>
        <th style={th}>{k("col.languages")}</th>
        <th style={th}>{k("col.version")}</th>
        <th style={th}>{k("col.tests")}</th>
        <th style={thEnd}>{k("col.bindings")}</th>
        <th style={th}>{k("col.updated")}</th>
        <th style={th}>{k("col.flags")}</th>
      </tr>
    </thead>
  );

  return (
    <section data-screen="A-03">
      <PageHeader title={k("title")} description={k("subtitle")} code="A-03" />

      <div style={{ marginBottom: "var(--rmc-space-4)" }}>
        <Alert tone="info">{k("scope_note")}</Alert>
      </div>

      <p style={{ ...muted, fontSize: "var(--rmc-size-sm)", marginTop: 0 }}>
        {k("as_of", { time: formatDate(locale, new Date(view.generatedAt), { dateStyle: "medium", timeStyle: "short" }) })}
        {" · "}
        <span>{k("tenant")}: {view.tenantName}</span>
        {" · "}
        <span>{k("languages_note", { langs: langs.map((l) => l.toUpperCase()).join(", ") })}</span>
      </p>

      {/* Uyarılar */}
      {blocked.length > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="danger">{k("alert.test", { count: formatNumber(locale, blocked.length) })}</Alert>
        </div>
      )}
      {missingVer.length > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="danger">{k("alert.no_version", { count: formatNumber(locale, missingVer.length) })}</Alert>
        </div>
      )}
      {unbound.length > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="warning">{k("alert.unbound", { count: formatNumber(locale, unbound.length) })}</Alert>
        </div>
      )}
      {pending.length > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0 var(--rmc-space-4)" }}>
          <Alert tone="info">{k("alert.pending", { count: formatNumber(locale, pending.length) })}</Alert>
        </div>
      )}

      {/* Özet */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", marginBottom: "var(--rmc-space-3)" }}>{k("section.summary")}</h2>
      <div style={grid()}>
        <Kpi label={k("kpi.total")} value={formatNumber(locale, agents.length)} hint={k("kpi.total_hint")} />
        <Kpi label={k("kpi.production")} value={formatNumber(locale, prod.length)} hint={k("kpi.production_hint")} tone="success" />
        <Kpi label={k("kpi.development")} value={formatNumber(locale, dev.length)} hint={k("kpi.development_hint")} />
        <Kpi label={k("kpi.pending")} value={formatNumber(locale, pending.length)} hint={k("kpi.pending_hint")} tone={pending.length > 0 ? "warning" : "success"} />
        <Kpi label={k("kpi.test")} value={formatNumber(locale, blocked.length)} hint={k("kpi.test_hint")} tone={blocked.length > 0 ? "danger" : "success"} />
        <Kpi label={k("kpi.unbound")} value={formatNumber(locale, unbound.length)} hint={k("kpi.unbound_hint")} tone={unbound.length > 0 ? "warning" : "success"} />
        <Kpi label={k("kpi.variants")} value={formatNumber(locale, variants.length)} hint={k("kpi.variants_hint")} />
        <Kpi label={k("kpi.attention")} value={formatNumber(locale, openCount)} hint={k("kpi.attention_hint")} tone={openCount > 0 ? "warning" : "success"} />
      </div>

      {/* Yaşam döngüsü dağılımı */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.lifecycle")}</h2>
      <Card>
        <Table caption={k("lifecycle_caption")}>
          <thead>
            <tr style={rowBorder}>
              <th style={th}>{k("col.lifecycle")}</th>
              <th style={thEnd}>{k("col.count")}</th>
            </tr>
          </thead>
          <tbody>
            {LIFECYCLE_ORDER.map((s) => (
              <tr key={s} style={rowBorder}>
                <td style={td}><StatusPill tone={lifecycleTone(s)}>{lifecycleName(s)}</StatusPill></td>
                <td style={tdEnd}>{formatNumber(locale, byLifecycle[s] ?? 0)}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-2)" }}>
        {k("mode_hint", { single: formatNumber(locale, byMode["single_prompt"] ?? 0), flow: formatNumber(locale, byMode["node_flow"] ?? 0) })}
      </p>

      {/* Dikkat gerektiren agent'lar */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.attention")}</h2>
      <Card>
        {attention.length === 0 ? (
          <EmptyState message={k("no_attention")} />
        ) : (
          <Table caption={k("attention_caption")}>
            {tableHead}
            <tbody>{attention.map(agentRow)}</tbody>
          </Table>
        )}
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-2)" }}>{k("attention_hint")}</p>

      {/* Tüm agent'lar */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>
        <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: 0 }}>{k("section.all")}</h2>
        <Button variant="primary">{k("action.new")}</Button>
      </div>
      <Card>
        {agents.length === 0 ? (
          <EmptyState message={k("no_agents")} />
        ) : (
          <Table caption={k("all_caption")}>
            {tableHead}
            <tbody>{agents.map(agentRow)}</tbody>
          </Table>
        )}
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>{k("all_hint")}</p>
    </section>
  );
}
