// WBS 13.4.9 — L2 ekranı A-09 "Tool/API Bağlama" (gerçek içerik; 13.1.1 iskeletinin yerini alır).
//
// İÇERİK (BRD §17.5 A-09 "Tool/API Bağlama" — "Tanımlı tool'ları agent'a bağlama (kullanım)"): bir tenant'ın
// AGENT'larına BAĞLI TOOL'larının envanteri. T-05 (L1) tool'u TANIMLAR; A-09 (L2) tanımlı tool'ları agent'a
// BAĞLAR + bağ sağlığını gösterir. BAĞLAMA ÖZETİ (tool · agent · aktif bağ · yazma yetkisi · teyit · hassas ·
// async + açık dikkat), AGENT BAŞINA BAĞLAR tablosu (agent · tool · protokol FR-TOOL-001 · grant FR-TOOL-004 ·
// erişim FR-TOOL-005 · teyit FR-TOOL-006 · durum), TOOL KATALOĞU tablosu (tool · protokol · erişim · schema
// FR-TOOL-002 · endpoint FR-TOOL-012 · teyit FR-TOOL-006 · hassas FR-TOOL-007 · async FR-TOOL-011 · bağ),
// PROTOKOL DAĞILIMI (FR-TOOL-001) ve GÜVENLİK & UYUM SAĞLIĞI (schema/endpoint/erişim/teyit). Tool ENDPOINT URL'i /
// JSON schema GÖVDESİ / istek-yanıt PAYLOAD'ı / credential gösterilmez — yalnız DURUM/BAYRAK; tool çağırma/bağlama
// derin aksiyondur (API dilimi). TENANT-SCOPE (FR-TEN-002): yalnız oturum açan tenant (middleware 13.1.2 + RLS).
// HİJYEN (BRD §17.7 + §17.6): yalnız META; ham müşteri içeriği/PII + payload gömülmez. GÜVENLİK (NFR 10.6): sır
// konmaz. RBAC (BRD §17.6): operations_manager=Düzenle · conversation_designer=Düzenle · qa_analyst=— ·
// human_agent=—. UI yalnız görsel kapı; bağla/çöz/grant nihai yetki + işlem backend'de. Tüm metin i18n'den (t()).
import type { CSSProperties } from "react";
import { getServerLocale } from "@/lib/i18n/server";
import { getCatalog, t, formatNumber, formatDate } from "@/lib/i18n";
import { PageHeader, Card, StatusPill, Alert, Table, Button, EmptyState } from "@/lib/ui/components";
import {
  getToolBindingView,
  sortedTools,
  allBindings,
  countByProtocol,
  countByAccessLevel,
  readTools,
  writeTools,
  unvalidatedTools,
  unapprovedTools,
  confirmationTools,
  sensitiveTools,
  asyncTools,
  unconfirmedSensitiveTools,
  bindingCountForTool,
  activeBindings,
  disabledBindings,
  writeGrantBindings,
  escalatedBindings,
  orphanBindings,
  unapprovedBindings,
  unvalidatedBindings,
  sensitiveWriteBindings,
  openAttentionCount,
  protocolTone,
  accessTone,
  statusTone,
  PROTOCOL_ORDER,
  type ToolProtocol,
  type AccessLevel,
  type BindingStatus,
  type ToolDefinition,
  type ResolvedBinding,
} from "@/lib/tenant/tools";

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
  const k = (key: string, p?: Record<string, string | number>) => t(cat, `screen.a09.${key}`, p);
  const view = await getToolBindingView();

  const tools = sortedTools(view);
  const bindings = allBindings(view);
  const protocolCounts = countByProtocol(view.tools);
  const accessCounts = countByAccessLevel(view.tools);
  const reads = readTools(view.tools);
  const writes = writeTools(view.tools);
  const unvalidated = unvalidatedTools(view.tools);
  const unapprovedT = unapprovedTools(view.tools);
  const confirms = confirmationTools(view.tools);
  const sensitive = sensitiveTools(view.tools);
  const asyncs = asyncTools(view.tools);
  const unconfirmedSensitive = unconfirmedSensitiveTools(view.tools);
  const active = activeBindings(view);
  const disabled = disabledBindings(view);
  const writeGrants = writeGrantBindings(view);
  const escalated = escalatedBindings(view);
  const orphans = orphanBindings(view);
  const unapprovedB = unapprovedBindings(view);
  const unvalidatedB = unvalidatedBindings(view);
  const sensitiveWrite = sensitiveWriteBindings(view);
  const attention = openAttentionCount(view);

  const protocolName = (p: ToolProtocol) => k(`protocol.${p}`);
  const accessName = (a: AccessLevel) => k(`access.${a}`);
  const statusName = (s: BindingStatus) => k(`status.${s}`);

  const totalTools = view.tools.length;
  const presentProtocols = PROTOCOL_ORDER.filter((p) => protocolCounts[p] > 0);

  const bindingRow = (b: ResolvedBinding) => {
    const isEscalated = b.tool !== null && b.grant === "write" && b.tool.accessLevel === "read";
    const isOrphan = b.tool === null;
    const isUnapproved = b.status === "active" && b.tool !== null && !b.tool.endpointApproved;
    return (
      <tr key={`${b.agentRef}/${b.bindRef}`} style={rowBorder}>
        <td style={td}>
          <strong>{b.agentName}</strong> <code style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{b.agentRef}</code>
        </td>
        <td style={td}>
          {b.tool ? <strong>{b.tool.name}</strong> : <span style={{ color: "var(--rmc-danger-fg, #b42318)" }}>{k("orphan")}</span>}{" "}
          <code style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{b.toolRef}</code>
        </td>
        <td style={td}>{b.tool ? <StatusPill tone={protocolTone(b.tool.protocol)}>{protocolName(b.tool.protocol)}</StatusPill> : <span style={muted}>{k("none")}</span>}</td>
        <td style={td}>
          <StatusPill tone={isEscalated ? "danger" : accessTone(b.grant)}>{accessName(b.grant)}</StatusPill>
          {isEscalated && <span style={{ color: "var(--rmc-danger-fg, #b42318)", fontSize: "var(--rmc-size-xs)" }}> {k("escalated")}</span>}
        </td>
        <td style={td}>{b.tool ? (b.tool.requiresConfirmation ? <StatusPill tone="success">{k("yes")}</StatusPill> : <span style={muted}>{k("no")}</span>) : <span style={muted}>{k("none")}</span>}</td>
        <td style={td}>
          {isOrphan ? <StatusPill tone="danger">{k("orphan")}</StatusPill> : isUnapproved ? <StatusPill tone="danger">{k("blocked")}</StatusPill> : <StatusPill tone={statusTone(b.status)}>{statusName(b.status)}</StatusPill>}
        </td>
      </tr>
    );
  };

  const toolRow = (tool: ToolDefinition) => {
    const binds = bindingCountForTool(view, tool.toolRef);
    return (
      <tr key={tool.toolRef} style={rowBorder}>
        <td style={td}>
          <strong>{tool.name}</strong> <code style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{tool.toolRef}</code>
        </td>
        <td style={td}><StatusPill tone={protocolTone(tool.protocol)}>{protocolName(tool.protocol)}</StatusPill></td>
        <td style={td}><StatusPill tone={accessTone(tool.accessLevel)}>{accessName(tool.accessLevel)}</StatusPill></td>
        <td style={td}>{tool.schemaValidated ? <StatusPill tone="success">{k("yes")}</StatusPill> : <StatusPill tone="warning">{k("no")}</StatusPill>}</td>
        <td style={td}>{tool.endpointApproved ? <StatusPill tone="success">{k("yes")}</StatusPill> : <StatusPill tone="danger">{k("no")}</StatusPill>}</td>
        <td style={td}>{tool.sensitiveAction && !tool.requiresConfirmation ? <StatusPill tone="danger">{k("no")}</StatusPill> : tool.requiresConfirmation ? <StatusPill tone="info">{k("yes")}</StatusPill> : <span style={muted}>{k("no")}</span>}</td>
        <td style={td}>{tool.sensitiveAction ? <StatusPill tone="warning">{k("yes")}</StatusPill> : <span style={muted}>{k("no")}</span>}</td>
        <td style={td}>{tool.async ? <StatusPill tone="info">{k("yes")}</StatusPill> : <span style={muted}>{k("no")}</span>}</td>
        <td style={tdEnd}>{formatNumber(locale, binds)}</td>
      </tr>
    );
  };

  return (
    <section data-screen="A-09">
      <PageHeader title={k("title")} description={k("subtitle")} code="A-09" />

      <div style={{ marginBottom: "var(--rmc-space-4)" }}>
        <Alert tone="info">{k("scope_note")}</Alert>
      </div>

      <p style={{ ...muted, fontSize: "var(--rmc-size-sm)", marginTop: 0 }}>
        {k("as_of", { time: formatDate(locale, new Date(view.generatedAt), { dateStyle: "medium", timeStyle: "short" }) })}
        {" · "}
        <span>{k("tenant")}: {view.tenantName}</span>
        {" · "}
        <span>{k("tools_label")}: {formatNumber(locale, totalTools)}</span>
      </p>

      {/* Uyarılar */}
      {orphans.length > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="danger">{k("alert.orphan_binding", { count: formatNumber(locale, orphans.length) })}</Alert>
        </div>
      )}
      {unapprovedB.length > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="danger">{k("alert.unapproved_endpoint", { count: formatNumber(locale, unapprovedB.length) })}</Alert>
        </div>
      )}
      {escalated.length > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="danger">{k("alert.escalated_grant", { count: formatNumber(locale, escalated.length) })}</Alert>
        </div>
      )}
      {unvalidatedB.length > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="warning">{k("alert.unvalidated_schema", { count: formatNumber(locale, unvalidatedB.length) })}</Alert>
        </div>
      )}
      {unconfirmedSensitive.length > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="warning">{k("alert.unconfirmed_sensitive", { count: formatNumber(locale, unconfirmedSensitive.length) })}</Alert>
        </div>
      )}
      {sensitiveWrite.length > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="info">{k("alert.sensitive_write", { count: formatNumber(locale, sensitiveWrite.length) })}</Alert>
        </div>
      )}

      {/* Bağlama özeti */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", margin: "var(--rmc-space-2) 0 var(--rmc-space-3)" }}>
        <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: 0 }}>{k("section.summary")}</h2>
        <Button variant="primary">{k("action.bind")}</Button>
      </div>
      <div style={grid()}>
        <Kpi label={k("kpi.tools")} value={formatNumber(locale, totalTools)} hint={k("kpi.tools_hint", { read: formatNumber(locale, reads.length), write: formatNumber(locale, writes.length) })} />
        <Kpi label={k("kpi.agents")} value={formatNumber(locale, view.agents.length)} hint={k("kpi.agents_hint")} />
        <Kpi label={k("kpi.bindings")} value={k("ratio", { a: formatNumber(locale, active.length), b: formatNumber(locale, bindings.length) })} hint={k("kpi.bindings_hint", { disabled: formatNumber(locale, disabled.length) })} />
        <Kpi label={k("kpi.write_grants")} value={formatNumber(locale, writeGrants.length)} hint={k("kpi.write_grants_hint")} tone={writeGrants.length > 0 ? "warning" : "success"} />
        <Kpi label={k("kpi.confirmation")} value={formatNumber(locale, confirms.length)} hint={k("kpi.confirmation_hint")} />
        <Kpi label={k("kpi.sensitive")} value={formatNumber(locale, sensitive.length)} hint={k("kpi.sensitive_hint")} />
        <Kpi label={k("kpi.async")} value={formatNumber(locale, asyncs.length)} hint={k("kpi.async_hint")} />
        <Kpi label={k("kpi.attention")} value={formatNumber(locale, attention)} hint={k("kpi.attention_hint")} tone={attention > 0 ? "warning" : "success"} />
      </div>

      {/* Agent başına bağlar (FR-TOOL-004) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.bindings")}</h2>
      <Card>
        {bindings.length === 0 ? (
          <EmptyState message={k("no_bindings")} />
        ) : (
          <Table caption={k("bindings_caption")}>
            <thead>
              <tr style={rowBorder}>
                <th style={th}>{k("col.agent")}</th>
                <th style={th}>{k("col.tool")}</th>
                <th style={th}>{k("col.protocol")}</th>
                <th style={th}>{k("col.grant")}</th>
                <th style={th}>{k("col.confirmation")}</th>
                <th style={th}>{k("col.status")}</th>
              </tr>
            </thead>
            <tbody>{bindings.map(bindingRow)}</tbody>
          </Table>
        )}
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>{k("bindings_hint")}</p>

      {/* Tool kataloğu */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>
        <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: 0 }}>{k("section.catalog")}</h2>
        <Button variant="secondary">{k("action.manage")}</Button>
      </div>
      <Card>
        {tools.length === 0 ? (
          <EmptyState message={k("no_tools")} />
        ) : (
          <Table caption={k("catalog_caption")}>
            <thead>
              <tr style={rowBorder}>
                <th style={th}>{k("col.tool")}</th>
                <th style={th}>{k("col.protocol")}</th>
                <th style={th}>{k("col.access")}</th>
                <th style={th}>{k("col.schema")}</th>
                <th style={th}>{k("col.endpoint")}</th>
                <th style={th}>{k("col.confirmation")}</th>
                <th style={th}>{k("col.sensitive")}</th>
                <th style={th}>{k("col.async")}</th>
                <th style={thEnd}>{k("col.bindings")}</th>
              </tr>
            </thead>
            <tbody>{tools.map(toolRow)}</tbody>
          </Table>
        )}
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>{k("catalog_hint")}</p>

      {/* Protokol dağılımı (FR-TOOL-001) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.protocols")}</h2>
      <Card>
        <Table caption={k("protocols_caption")}>
          <thead>
            <tr style={rowBorder}>
              <th style={th}>{k("col.protocol")}</th>
              <th style={thEnd}>{k("col.count")}</th>
              <th style={thEnd}>{k("col.share")}</th>
            </tr>
          </thead>
          <tbody>
            {presentProtocols.map((p) => (
              <tr key={p} style={rowBorder}>
                <td style={td}><StatusPill tone={protocolTone(p)}>{protocolName(p)}</StatusPill></td>
                <td style={tdEnd}>{formatNumber(locale, protocolCounts[p])}</td>
                <td style={tdEnd}>{k("percent", { n: formatNumber(locale, totalTools > 0 ? Math.round((protocolCounts[p] / totalTools) * 100) : 0) })}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>

      {/* Güvenlik & uyum sağlığı (FR-TOOL-002/005/006/012) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.health")}</h2>
      <Card>
        <Table caption={k("health_caption")}>
          <thead>
            <tr style={rowBorder}>
              <th style={th}>{k("col.control")}</th>
              <th style={th}>{k("col.purpose")}</th>
              <th style={thEnd}>{k("col.value")}</th>
            </tr>
          </thead>
          <tbody>
            <tr style={rowBorder}>
              <td style={td}>{k("health.schema")}</td>
              <td style={td}><span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{k("health.schema_desc")}</span></td>
              <td style={tdEnd}>{unvalidated.length > 0 ? <span style={{ color: "var(--rmc-warning-fg, #b54708)" }}>{k("ratio", { a: formatNumber(locale, totalTools - unvalidated.length), b: formatNumber(locale, totalTools) })}</span> : k("ratio", { a: formatNumber(locale, totalTools), b: formatNumber(locale, totalTools) })}</td>
            </tr>
            <tr style={rowBorder}>
              <td style={td}>{k("health.endpoint")}</td>
              <td style={td}><span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{k("health.endpoint_desc")}</span></td>
              <td style={tdEnd}>{unapprovedT.length > 0 ? <span style={{ color: "var(--rmc-danger-fg, #b42318)" }}>{k("ratio", { a: formatNumber(locale, totalTools - unapprovedT.length), b: formatNumber(locale, totalTools) })}</span> : k("ratio", { a: formatNumber(locale, totalTools), b: formatNumber(locale, totalTools) })}</td>
            </tr>
            <tr style={rowBorder}>
              <td style={td}>{k("health.access_split")}</td>
              <td style={td}><span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{k("health.access_split_desc")}</span></td>
              <td style={tdEnd}>{k("read_write", { read: formatNumber(locale, accessCounts.read), write: formatNumber(locale, accessCounts.write) })}</td>
            </tr>
            <tr style={rowBorder}>
              <td style={td}>{k("health.confirmation")}</td>
              <td style={td}><span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{k("health.confirmation_desc")}</span></td>
              <td style={tdEnd}>{unconfirmedSensitive.length > 0 ? <span style={{ color: "var(--rmc-warning-fg, #b54708)" }}>{k("ratio", { a: formatNumber(locale, sensitive.length - unconfirmedSensitive.length), b: formatNumber(locale, sensitive.length) })}</span> : k("ratio", { a: formatNumber(locale, sensitive.length), b: formatNumber(locale, sensitive.length) })}</td>
            </tr>
          </tbody>
        </Table>
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>{k("health_hint")}</p>
    </section>
  );
}
