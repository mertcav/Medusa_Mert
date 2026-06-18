// WBS 13.4.5 — L2 ekranı A-05 "Conversation Flow Editor" (gerçek içerik; 13.1.1 iskeletinin yerini alır).
//
// İÇERİK (BRD §17.5 A-05 "Conversation Flow Editor"): node/flow tabanlı konuşma SÜRECİNİN (FR-AGT-003)
// tasarım/doğrulama görünümü. AKIŞ ÖZETİ (düğüm/geçiş/mod/sürüm + erişilemez/asılı/çıkmaz/geçerlilik),
// DOĞRULAMA & SAĞLIK kapısı (tek giriş · asılı geçiş yok · erişilemez yok · çıkmaz yok · yapılandırma tam ·
// insan aktarımı — readyForTest/readyForPublish FR-AGT-010), DÜĞÜM TÜRÜ DAĞILIMI, DÜĞÜMLER ve GEÇİŞLER.
// Bu ekran KONFİGÜRASYON'dur — A-02 gibi gerçek zamanlı DEĞİL (FR-ANA-012 dışı). TENANT-SCOPE (FR-TEN-002):
// yalnız oturum açan tenant'ın agent'ının akışı (middleware 13.1.2 + RLS DB §6.3). HİJYEN (BRD §17.7 + §17.6):
// yalnız KONFİGÜRASYON META; ham müşteri içeriği/PII + prompt gövdesi/tool sırrı gömülmez (derin tasarım
// A-06/A-09, görsel kapı). GÜVENLİK (NFR 10.6): sır konmaz. RBAC (BRD §17.6): conversation_designer=Yönet ·
// operations_manager=Düzenle · qa_analyst=— · human_agent=—. UI yalnız görsel kapı; düzenle/doğrula/yayınla
// nihai yetki + işlem backend'de. Tüm kullanıcı-görünür metin i18n'den (t()).
import type { CSSProperties } from "react";
import { getServerLocale } from "@/lib/i18n/server";
import { getCatalog, t, formatNumber, formatDate } from "@/lib/i18n";
import { PageHeader, Card, StatusPill, Alert, Table, Button, EmptyState } from "@/lib/ui/components";
import {
  getFlowView,
  isNodeFlow,
  countByType,
  outgoingEdges,
  danglingEdges,
  isDanglingEdge,
  unreachableNodes,
  deadEndNodes,
  nodesMissingConfig,
  hasSingleEntry,
  hasHandoff,
  structurallyValid,
  readyForTest,
  readyForPublish,
  flowValidity,
  nodeTypeTone,
  validityTone,
  modeTone,
  readyTone,
  NODE_TYPE_ORDER,
  type NodeType,
  type FlowMode,
  type FlowValidity,
  type FlowNode,
  type FlowEdge,
} from "@/lib/tenant/flows";

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
  const k = (key: string, p?: Record<string, string | number>) => t(cat, `screen.a05.${key}`, p);
  const view = await getFlowView();
  const { flow } = view;
  const nodeFlow = isNodeFlow(flow);

  const typeCounts = countByType(flow.nodes);
  const dangling = danglingEdges(flow);
  const unreachable = unreachableNodes(flow);
  const deadEnds = deadEndNodes(flow);
  const missingConfig = nodesMissingConfig(flow);
  const singleEntry = hasSingleEntry(flow);
  const handoff = hasHandoff(flow);
  const valid = structurallyValid(flow);
  const canTest = readyForTest(flow);
  const canPublish = readyForPublish(flow);
  const validity = flowValidity(flow);

  const nodeName = (ty: NodeType) => k(`node.${ty}`);
  const nodeDesc = (ty: NodeType) => k(`node_desc.${ty}`);
  const modeName = (m: FlowMode) => k(`mode.${m}`);
  const validityName = (v: FlowValidity) => k(`validity.${v}`);
  const unreachableIds = new Set(unreachable.map((n) => n.id));
  const deadEndIds = new Set(deadEnds.map((n) => n.id));

  const nodeRow = (n: FlowNode) => {
    const out = outgoingEdges(flow, n.id).length;
    const isUnreach = unreachableIds.has(n.id);
    const isDead = deadEndIds.has(n.id);
    const binding = n.promptRef
      ? k("binding.prompt", { ref: n.promptRef })
      : n.toolRef
        ? k("binding.tool", { ref: n.toolRef })
        : k("binding.none");
    return (
      <tr key={n.id} style={rowBorder}>
        <td style={td}>
          <code style={muted}>{n.id}</code> {n.label}
        </td>
        <td style={td}><StatusPill tone={nodeTypeTone(n.type)}>{nodeName(n.type)}</StatusPill></td>
        <td style={td}><span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{binding}</span></td>
        <td style={tdEnd}>{formatNumber(locale, out)}</td>
        <td style={td}>{n.configComplete ? <StatusPill tone="success">{k("config.complete")}</StatusPill> : <StatusPill tone="warning">{k("config.incomplete")}</StatusPill>}</td>
        <td style={td}>
          {isUnreach ? (
            <StatusPill tone="danger">{k("flag.unreachable")}</StatusPill>
          ) : isDead ? (
            <StatusPill tone="danger">{k("flag.dead_end")}</StatusPill>
          ) : (
            <span style={muted}>{k("flag.ok")}</span>
          )}
        </td>
      </tr>
    );
  };

  const edgeRow = (e: FlowEdge, i: number) => {
    const bad = isDanglingEdge(flow, e);
    return (
      <tr key={`${e.from}-${e.to}-${i}`} style={rowBorder}>
        <td style={td}><code style={muted}>{e.from}</code></td>
        <td style={td}><code style={muted}>{e.to}</code></td>
        <td style={td}>{e.condition ? e.condition : <span style={muted}>{k("condition.none")}</span>}</td>
        <td style={td}>{bad ? <StatusPill tone="danger">{k("flag.dangling")}</StatusPill> : <StatusPill tone="success">{k("edge.valid")}</StatusPill>}</td>
      </tr>
    );
  };

  const gateRow = (labelKey: string, hintKey: string, ok: boolean) => (
    <tr style={rowBorder}>
      <td style={td}>
        {k(labelKey)}
        <br />
        <span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{k(hintKey)}</span>
      </td>
      <td style={tdEnd}><StatusPill tone={readyTone(ok)}>{ok ? k("ready.yes") : k("ready.no")}</StatusPill></td>
    </tr>
  );

  // Yalnız mevcut (count>0) düğüm türleri, sıralı.
  const presentTypes = NODE_TYPE_ORDER.filter((ty) => typeCounts[ty] > 0);
  const totalNodes = flow.nodes.length;

  return (
    <section data-screen="A-05">
      <PageHeader title={k("title")} description={k("subtitle")} code="A-05" />

      <div style={{ marginBottom: "var(--rmc-space-4)" }}>
        <Alert tone="info">{k("scope_note")}</Alert>
      </div>

      <p style={{ ...muted, fontSize: "var(--rmc-size-sm)", marginTop: 0 }}>
        {k("as_of", { time: formatDate(locale, new Date(view.generatedAt), { dateStyle: "medium", timeStyle: "short" }) })}
        {" · "}
        <span>{k("tenant")}: {view.tenantName}</span>
        {" · "}
        <span>{k("agent_label")}: <code>{view.agentRef}</code> {view.agentName}</span>
        {" · "}
        <span>{k("flow_label")}: <code>{flow.flowRef}</code> v{formatNumber(locale, flow.versionNo)}</span>
      </p>

      {!nodeFlow ? (
        // Tek-prompt modu: node grafiği yok (FR-AGT-003).
        <>
          <div style={{ margin: "var(--rmc-space-2) 0 var(--rmc-space-4)" }}>
            <Alert tone="info">{k("alert.single_prompt")}</Alert>
          </div>
          <Card>
            <EmptyState message={k("no_nodes")} />
          </Card>
        </>
      ) : (
        <>
          {/* Uyarılar */}
          {validity === "invalid" && (
            <div style={{ margin: "var(--rmc-space-2) 0" }}>
              <Alert tone="danger">{k("alert.invalid", { count: formatNumber(locale, dangling.length + unreachable.length + deadEnds.length + (singleEntry ? 0 : 1)) })}</Alert>
            </div>
          )}
          {valid && missingConfig.length > 0 && (
            <div style={{ margin: "var(--rmc-space-2) 0" }}>
              <Alert tone="warning">{k("alert.missing_config", { count: formatNumber(locale, missingConfig.length) })}</Alert>
            </div>
          )}
          {valid && !handoff && (
            <div style={{ margin: "var(--rmc-space-2) 0" }}>
              <Alert tone="warning">{k("alert.no_handoff")}</Alert>
            </div>
          )}
          {canPublish && (
            <div style={{ margin: "var(--rmc-space-2) 0 var(--rmc-space-4)" }}>
              <Alert tone="success">{k("alert.ready_publish")}</Alert>
            </div>
          )}

          {/* Akış özeti */}
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", margin: "var(--rmc-space-2) 0 var(--rmc-space-3)" }}>
            <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: 0 }}>{k("section.summary")}</h2>
            <Button variant="primary">{k("action.open_editor")}</Button>
          </div>
          <div style={grid()}>
            <Kpi label={k("kpi.nodes")} value={formatNumber(locale, totalNodes)} hint={k("kpi.nodes_hint")} />
            <Kpi label={k("kpi.edges")} value={formatNumber(locale, flow.edges.length)} hint={k("kpi.edges_hint")} />
            <Kpi label={k("kpi.mode")} value={modeName(flow.mode)} hint={k("kpi.mode_hint")} />
            <Kpi label={k("kpi.version")} value={formatNumber(locale, flow.versionNo)} hint={k("kpi.version_hint")} />
            <Kpi label={k("kpi.unreachable")} value={formatNumber(locale, unreachable.length)} hint={k("kpi.unreachable_hint")} tone={unreachable.length > 0 ? "danger" : "success"} />
            <Kpi label={k("kpi.dangling")} value={formatNumber(locale, dangling.length)} hint={k("kpi.dangling_hint")} tone={dangling.length > 0 ? "danger" : "success"} />
            <Kpi label={k("kpi.dead_end")} value={formatNumber(locale, deadEnds.length)} hint={k("kpi.dead_end_hint")} tone={deadEnds.length > 0 ? "danger" : "success"} />
            <Kpi label={k("kpi.validity")} value={validityName(validity)} hint={k("kpi.validity_hint")} tone={validity === "valid" ? "success" : validity === "warnings" ? "warning" : "danger"} />
          </div>

          {/* Doğrulama & sağlık */}
          <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.validation")}</h2>
          <Card>
            <Table caption={k("validation_caption")}>
              <thead>
                <tr style={rowBorder}>
                  <th style={th}>{k("col.gate")}</th>
                  <th style={thEnd}>{k("col.ready")}</th>
                </tr>
              </thead>
              <tbody>
                {gateRow("gate.single_entry", "gate.single_entry_hint", singleEntry)}
                {gateRow("gate.no_dangling", "gate.no_dangling_hint", dangling.length === 0)}
                {gateRow("gate.no_unreachable", "gate.no_unreachable_hint", unreachable.length === 0)}
                {gateRow("gate.no_dead_end", "gate.no_dead_end_hint", deadEnds.length === 0)}
                {gateRow("gate.config_complete", "gate.config_complete_hint", missingConfig.length === 0)}
                {gateRow("gate.has_handoff", "gate.has_handoff_hint", handoff)}
              </tbody>
            </Table>
          </Card>
          <div style={{ display: "flex", gap: "var(--rmc-space-3)", margin: "var(--rmc-space-3) 0" }}>
            <Button variant="secondary" disabled={!canTest}>{k("action.run_test")}</Button>
            <Button variant="primary" disabled={!canPublish}>{k("action.publish")}</Button>
          </div>
          <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: 0 }}>{k("validation_hint")}</p>

          {/* Düğüm türü dağılımı */}
          <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.node_types")}</h2>
          <Card>
            <Table caption={k("node_types_caption")}>
              <thead>
                <tr style={rowBorder}>
                  <th style={th}>{k("col.type")}</th>
                  <th style={th}>{k("col.purpose")}</th>
                  <th style={thEnd}>{k("col.count")}</th>
                  <th style={thEnd}>{k("col.share")}</th>
                </tr>
              </thead>
              <tbody>
                {presentTypes.map((ty) => (
                  <tr key={ty} style={rowBorder}>
                    <td style={td}><StatusPill tone={nodeTypeTone(ty)}>{nodeName(ty)}</StatusPill></td>
                    <td style={td}><span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{nodeDesc(ty)}</span></td>
                    <td style={tdEnd}>{formatNumber(locale, typeCounts[ty])}</td>
                    <td style={tdEnd}>{k("percent", { n: formatNumber(locale, totalNodes > 0 ? Math.round((typeCounts[ty] / totalNodes) * 100) : 0) })}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Card>

          {/* Düğümler */}
          <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.nodes")}</h2>
          <Card>
            {flow.nodes.length === 0 ? (
              <EmptyState message={k("no_nodes")} />
            ) : (
              <Table caption={k("nodes_caption")}>
                <thead>
                  <tr style={rowBorder}>
                    <th style={th}>{k("col.node")}</th>
                    <th style={th}>{k("col.type")}</th>
                    <th style={th}>{k("col.binding")}</th>
                    <th style={thEnd}>{k("col.outgoing")}</th>
                    <th style={th}>{k("col.config")}</th>
                    <th style={th}>{k("col.flag")}</th>
                  </tr>
                </thead>
                <tbody>{flow.nodes.map(nodeRow)}</tbody>
              </Table>
            )}
          </Card>

          {/* Geçişler */}
          <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.transitions")}</h2>
          <Card>
            {flow.edges.length === 0 ? (
              <EmptyState message={k("no_edges")} />
            ) : (
              <Table caption={k("transitions_caption")}>
                <thead>
                  <tr style={rowBorder}>
                    <th style={th}>{k("col.from")}</th>
                    <th style={th}>{k("col.to")}</th>
                    <th style={th}>{k("col.condition")}</th>
                    <th style={th}>{k("col.valid")}</th>
                  </tr>
                </thead>
                <tbody>{flow.edges.map(edgeRow)}</tbody>
              </Table>
            )}
          </Card>
          <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>{k("editor_hint")}</p>
        </>
      )}
    </section>
  );
}
