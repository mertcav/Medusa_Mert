// WBS 13.4.8 — L2 ekranı A-08 "Knowledge Base" (gerçek içerik; 13.1.1 iskeletinin yerini alır).
//
// İÇERİK (BRD §17.5 A-08 "Knowledge Base"): bir tenant'ın agent'larına bağlı BİLGİ TABANLARININ ve
// DOKÜMANLARININ envanteri (bilgi kaynağı yükleme/bağlama). BİLGİ TABANI ÖZETİ (KB/doküman/indeksli/
// bekleyen/bayat/hassas/kısıtlı + açık dikkat), BİLGİ TABANLARI tablosu (ad/namespace/bağ FR-KB-004 ·
// doküman · indeksli · bayat · hassas), DOKÜMANLAR tablosu (ad/KB · kaynak türü FR-KB-001 · indeks durumu
// FR-KB-003 · sürüm · parça SAYISI · güncellik FR-KB-008 · erişim FR-KB-005 · hassasiyet FR-KB-010),
// KAYNAK TÜRÜ DAĞILIMI (FR-KB-001) ve İNDEKSLEME SAĞLIĞI (FR-KB-003). Doküman İÇERİĞİ/CHUNK METNİ/KAYNAK
// İŞARETÇİSİ gösterilmez — içerik yönetimi (ingest/yeniden indeksleme) derin aksiyondur (API dilimi).
// TENANT-SCOPE (FR-TEN-002): yalnız oturum açan tenant'ın bilgi tabanları (middleware 13.1.2 + RLS DB §6.3).
// HİJYEN (BRD §17.7 + §17.6): yalnız DOKÜMAN META; ham müşteri içeriği/PII + doküman içeriği gömülmez.
// GÜVENLİK (NFR 10.6): sır konmaz. RBAC (BRD §17.6): conversation_designer=Yönet · operations_manager=Düzenle ·
// qa_analyst=Görüntüle · human_agent=—. UI yalnız görsel kapı; yükle/bağla/yeniden-indeksle nihai yetki +
// işlem backend'de. Tüm kullanıcı-görünür metin i18n'den (t()).
import type { CSSProperties } from "react";
import { getServerLocale } from "@/lib/i18n/server";
import { getCatalog, t, formatNumber, formatDate } from "@/lib/i18n";
import { PageHeader, Card, StatusPill, Alert, Table, Button, EmptyState } from "@/lib/ui/components";
import {
  getKbView,
  sortedBases,
  allDocuments,
  countBySourceType,
  countByIndexStatus,
  indexedDocuments,
  pendingIndexDocuments,
  failedIndexDocuments,
  staleDocuments,
  sensitiveDocuments,
  restrictedDocuments,
  agentBoundBases,
  sharedBases,
  emptyBases,
  duplicateNamespaces,
  openAttentionCount,
  sourceTone,
  indexTone,
  freshnessTone,
  accessTone,
  bindingTone,
  SOURCE_ORDER,
  INDEX_ORDER,
  type SourceType,
  type IndexStatus,
  type Freshness,
  type AccessScope,
  type KbBinding,
  type KnowledgeBase,
  type KbDocument,
} from "@/lib/tenant/kb";

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
  const k = (key: string, p?: Record<string, string | number>) => t(cat, `screen.a08.${key}`, p);
  const view = await getKbView();

  const bases = sortedBases(view);
  const docs = allDocuments(view);
  const sourceCounts = countBySourceType(docs);
  const indexCounts = countByIndexStatus(docs);
  const indexed = indexedDocuments(docs);
  const pending = pendingIndexDocuments(docs);
  const failed = failedIndexDocuments(docs);
  const stale = staleDocuments(docs);
  const sensitive = sensitiveDocuments(docs);
  const restricted = restrictedDocuments(docs);
  const agentBound = agentBoundBases(view);
  const shared = sharedBases(view);
  const empties = emptyBases(view);
  const dupNs = duplicateNamespaces(view);
  const attention = openAttentionCount(view);

  const sourceName = (s: SourceType) => k(`source.${s}`);
  const indexName = (s: IndexStatus) => k(`index.${s}`);
  const indexDesc = (s: IndexStatus) => k(`index_desc.${s}`);
  const freshName = (f: Freshness) => k(`freshness.${f}`);
  const accessName = (a: AccessScope) => k(`access.${a}`);
  const bindingName = (b: KbBinding) => k(`binding.${b}`);

  const totalDocs = docs.length;
  const presentSources = SOURCE_ORDER.filter((s) => sourceCounts[s] > 0);

  const baseRow = (kb: KnowledgeBase) => {
    const kbStale = kb.documents.filter((d) => d.freshness === "stale").length;
    const kbSensitive = kb.documents.filter((d) => d.isSensitive).length;
    const kbIndexed = kb.documents.filter((d) => d.indexStatus === "indexed").length;
    return (
      <tr key={kb.kbRef} style={rowBorder}>
        <td style={td}>
          <strong>{kb.name}</strong> <code style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{kb.kbRef}</code>
        </td>
        <td style={td}><code style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{kb.namespace}</code></td>
        <td style={td}>
          <StatusPill tone={bindingTone(kb.binding)}>{bindingName(kb.binding)}</StatusPill>
          {kb.boundAgentRef && <span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}> <code>{kb.boundAgentRef}</code></span>}
        </td>
        <td style={tdEnd}>{formatNumber(locale, kb.documents.length)}</td>
        <td style={tdEnd}>{k("ratio", { a: formatNumber(locale, kbIndexed), b: formatNumber(locale, kb.documents.length) })}</td>
        <td style={tdEnd}>{kbStale > 0 ? <span style={{ color: "var(--rmc-warning-fg, #b54708)" }}>{formatNumber(locale, kbStale)}</span> : formatNumber(locale, 0)}</td>
        <td style={tdEnd}>{kbSensitive > 0 ? <span style={{ color: "var(--rmc-success-fg, #067647)" }}>{formatNumber(locale, kbSensitive)}</span> : formatNumber(locale, 0)}</td>
      </tr>
    );
  };

  const docRow = (d: KbDocument & { kbRef: string; kbName: string }) => (
    <tr key={`${d.kbRef}/${d.docRef}`} style={rowBorder}>
      <td style={td}>
        <strong>{d.title}</strong> <code style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{d.docRef}</code>
      </td>
      <td style={td}><span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{d.kbName}</span></td>
      <td style={td}><StatusPill tone={sourceTone(d.sourceType)}>{sourceName(d.sourceType)}</StatusPill></td>
      <td style={td}><StatusPill tone={indexTone(d.indexStatus)}>{indexName(d.indexStatus)}</StatusPill></td>
      <td style={tdEnd}>v{formatNumber(locale, d.versionNo)}</td>
      <td style={tdEnd}><span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{k("chunks", { n: formatNumber(locale, d.chunkCount) })}</span></td>
      <td style={td}><StatusPill tone={freshnessTone(d.freshness)}>{freshName(d.freshness)}</StatusPill></td>
      <td style={td}><StatusPill tone={accessTone(d.accessScope)}>{accessName(d.accessScope)}</StatusPill></td>
      <td style={td}>{d.isSensitive ? <StatusPill tone="info">{k("sensitive")}</StatusPill> : <span style={muted}>{k("none")}</span>}</td>
    </tr>
  );

  return (
    <section data-screen="A-08">
      <PageHeader title={k("title")} description={k("subtitle")} code="A-08" />

      <div style={{ marginBottom: "var(--rmc-space-4)" }}>
        <Alert tone="info">{k("scope_note")}</Alert>
      </div>

      <p style={{ ...muted, fontSize: "var(--rmc-size-sm)", marginTop: 0 }}>
        {k("as_of", { time: formatDate(locale, new Date(view.generatedAt), { dateStyle: "medium", timeStyle: "short" }) })}
        {" · "}
        <span>{k("tenant")}: {view.tenantName}</span>
        {" · "}
        <span>{k("bases_label")}: {formatNumber(locale, view.knowledgeBases.length)}</span>
      </p>

      {/* Uyarılar */}
      {dupNs.length > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="danger">{k("alert.duplicate_namespace", { count: formatNumber(locale, dupNs.length) })}</Alert>
        </div>
      )}
      {failed.length > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="warning">{k("alert.failed_index", { count: formatNumber(locale, failed.length) })}</Alert>
        </div>
      )}
      {pending.length > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="info">{k("alert.pending_index", { count: formatNumber(locale, pending.length) })}</Alert>
        </div>
      )}
      {stale.length > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="warning">{k("alert.stale_content", { count: formatNumber(locale, stale.length) })}</Alert>
        </div>
      )}
      {empties.length > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="warning">{k("alert.empty_base", { count: formatNumber(locale, empties.length) })}</Alert>
        </div>
      )}
      {sensitive.length > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="info">{k("alert.sensitive_docs", { count: formatNumber(locale, sensitive.length) })}</Alert>
        </div>
      )}

      {/* Bilgi tabanı özeti */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", margin: "var(--rmc-space-2) 0 var(--rmc-space-3)" }}>
        <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: 0 }}>{k("section.summary")}</h2>
        <Button variant="primary">{k("action.upload")}</Button>
      </div>
      <div style={grid()}>
        <Kpi label={k("kpi.bases")} value={formatNumber(locale, view.knowledgeBases.length)} hint={k("kpi.bases_hint", { agent: formatNumber(locale, agentBound.length), shared: formatNumber(locale, shared.length) })} />
        <Kpi label={k("kpi.documents")} value={formatNumber(locale, totalDocs)} hint={k("kpi.documents_hint")} />
        <Kpi label={k("kpi.indexed")} value={k("ratio", { a: formatNumber(locale, indexed.length), b: formatNumber(locale, totalDocs) })} hint={k("kpi.indexed_hint")} tone={indexed.length < totalDocs ? "warning" : "success"} />
        <Kpi label={k("kpi.pending")} value={formatNumber(locale, pending.length)} hint={k("kpi.pending_hint")} tone={pending.length > 0 ? "warning" : "success"} />
        <Kpi label={k("kpi.stale")} value={formatNumber(locale, stale.length)} hint={k("kpi.stale_hint")} tone={stale.length > 0 ? "warning" : "success"} />
        <Kpi label={k("kpi.sensitive")} value={formatNumber(locale, sensitive.length)} hint={k("kpi.sensitive_hint")} />
        <Kpi label={k("kpi.restricted")} value={formatNumber(locale, restricted.length)} hint={k("kpi.restricted_hint")} />
        <Kpi label={k("kpi.attention")} value={formatNumber(locale, attention)} hint={k("kpi.attention_hint")} tone={attention > 0 ? "warning" : "success"} />
      </div>

      {/* Bilgi tabanları (FR-KB-004) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.bases")}</h2>
      <Card>
        {bases.length === 0 ? (
          <EmptyState message={k("no_bases")} />
        ) : (
          <Table caption={k("bases_caption")}>
            <thead>
              <tr style={rowBorder}>
                <th style={th}>{k("col.base")}</th>
                <th style={th}>{k("col.namespace")}</th>
                <th style={th}>{k("col.binding")}</th>
                <th style={thEnd}>{k("col.docs")}</th>
                <th style={thEnd}>{k("col.indexed")}</th>
                <th style={thEnd}>{k("col.stale")}</th>
                <th style={thEnd}>{k("col.sensitive")}</th>
              </tr>
            </thead>
            <tbody>{bases.map(baseRow)}</tbody>
          </Table>
        )}
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>{k("bases_hint")}</p>

      {/* Dokümanlar */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>
        <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: 0 }}>{k("section.documents")}</h2>
        <Button variant="secondary">{k("action.connect")}</Button>
      </div>
      <Card>
        {docs.length === 0 ? (
          <EmptyState message={k("no_documents")} />
        ) : (
          <Table caption={k("documents_caption")}>
            <thead>
              <tr style={rowBorder}>
                <th style={th}>{k("col.document")}</th>
                <th style={th}>{k("col.base")}</th>
                <th style={th}>{k("col.source")}</th>
                <th style={th}>{k("col.status")}</th>
                <th style={thEnd}>{k("col.version")}</th>
                <th style={thEnd}>{k("col.chunks")}</th>
                <th style={th}>{k("col.freshness")}</th>
                <th style={th}>{k("col.access")}</th>
                <th style={th}>{k("col.flag")}</th>
              </tr>
            </thead>
            <tbody>{docs.map(docRow)}</tbody>
          </Table>
        )}
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>{k("documents_hint")}</p>

      {/* Kaynak türü dağılımı (FR-KB-001) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.sources")}</h2>
      <Card>
        <Table caption={k("sources_caption")}>
          <thead>
            <tr style={rowBorder}>
              <th style={th}>{k("col.source")}</th>
              <th style={thEnd}>{k("col.count")}</th>
              <th style={thEnd}>{k("col.share")}</th>
            </tr>
          </thead>
          <tbody>
            {presentSources.map((s) => (
              <tr key={s} style={rowBorder}>
                <td style={td}><StatusPill tone={sourceTone(s)}>{sourceName(s)}</StatusPill></td>
                <td style={tdEnd}>{formatNumber(locale, sourceCounts[s])}</td>
                <td style={tdEnd}>{k("percent", { n: formatNumber(locale, totalDocs > 0 ? Math.round((sourceCounts[s] / totalDocs) * 100) : 0) })}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>

      {/* İndeksleme sağlığı (FR-KB-003) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.index_health")}</h2>
      <Card>
        <Table caption={k("index_caption")}>
          <thead>
            <tr style={rowBorder}>
              <th style={th}>{k("col.status")}</th>
              <th style={th}>{k("col.purpose")}</th>
              <th style={thEnd}>{k("col.count")}</th>
              <th style={thEnd}>{k("col.share")}</th>
            </tr>
          </thead>
          <tbody>
            {INDEX_ORDER.map((s) => (
              <tr key={s} style={rowBorder}>
                <td style={td}><StatusPill tone={indexTone(s)}>{indexName(s)}</StatusPill></td>
                <td style={td}><span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{indexDesc(s)}</span></td>
                <td style={tdEnd}>{formatNumber(locale, indexCounts[s])}</td>
                <td style={tdEnd}>{k("percent", { n: formatNumber(locale, totalDocs > 0 ? Math.round((indexCounts[s] / totalDocs) * 100) : 0) })}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
      <div style={{ display: "flex", gap: "var(--rmc-space-3)", margin: "var(--rmc-space-3) 0" }}>
        <Button variant="secondary" disabled={failed.length === 0 && pending.length === 0}>{k("action.reindex")}</Button>
      </div>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: 0 }}>{k("index_hint")}</p>
    </section>
  );
}
