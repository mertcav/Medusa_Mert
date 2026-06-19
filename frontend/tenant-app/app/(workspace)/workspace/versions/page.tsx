// WBS 13.4.17 — L2 ekranı A-17 "Sürüm Geçmişi (agent) + rollback" (gerçek içerik; 13.1.1 iskeletinin yerini alır).
//
// İÇERİK (BRD §17.5 A-17 — "Agent versiyonları ve rollback"): bir agent'ın YAYIN/SÜRÜM GEÇMİŞİ panosu. ÖZET KPI'lar
// (sürüm sayısı / aktif sürüm / yayınlı / en son / bekleyen değişiklik / geri çağrılabilir / test bloklu / açık dikkat),
// SÜRÜM GEÇMİŞİ tablosu (sürüm no + kimliği + aşama + durum + test + yayınlayan + zaman + bağlanan config + rollback
// kökeni — DB §5.2 agent_version WORM), AŞAMA DAĞILIMI (FR-AGT-005) ve ROLLBACK bölümü (FR-AGT-006 — yayınlanan sürüm
// tek işlemle önceki sürüme döndürülür; geri çağrılabilir sürümler + varsayılan hedef). Yalnız SÜRÜM META (snapshot
// JSONB gövdesi gömülmez). TENANT-SCOPE (FR-TEN-002): yalnız oturum açan tenant (middleware 13.1.2 + RLS). RBAC
// (BRD §17.6 A-17): conversation_designer=Yönet · operations_manager=Görüntüle · qa_analyst=— · human_agent=—;
// tenant_owner kural 17.7 ile Yönet. Geri al/promote/yeni-sürüm DERİN AKSİYON (agent:version:manage — API §8.1);
// nihai yetki + tek-işlem rollback + audit backend'de + RLS (WORM append-only DB §6.5). Tüm ETİKET metni i18n'den;
// sürüm no/sayı/tarih ise VERİDİR (locale-duyarlı biçimlenir).
import type { CSSProperties } from "react";
import { getServerLocale } from "@/lib/i18n/server";
import { getCatalog, t, formatNumber, formatDate } from "@/lib/i18n";
import { PageHeader, Card, StatusPill, Alert, Table, Button, EmptyState } from "@/lib/ui/components";
import {
  getAgentVersionView,
  sortedVersions,
  activeVersion,
  latestVersion,
  countByStage,
  publishedVersions,
  versionStatus,
  isActive,
  isRollback,
  rollbackCount,
  recallableVersions,
  previousPublishedVersion,
  canRollback,
  hasPendingChanges,
  failedTestVersions,
  distinguishable,
  duplicateVersionNos,
  duplicateVersionIds,
  missingActiveVersion,
  rollbackRefsResolve,
  openAttentionCount,
  stageTone,
  statusTone,
  testTone,
  STAGE_ORDER,
  type VersionStage,
  type TestStatus,
  type VersionStatus,
  type AgentVersion,
} from "@/lib/tenant/agent-versions";

function Kpi({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: "danger" | "warning" | "success" | "info" | "neutral" }) {
  const valueColor =
    tone === "danger" ? "var(--rmc-danger-fg, #b42318)" : tone === "warning" ? "var(--rmc-warning-fg, #b54708)" : tone === "success" ? "var(--rmc-success-fg, #067647)" : tone === "info" ? "var(--rmc-info-fg, #175cd3)" : "var(--rmc-text-primary)";
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

// Ton birleşimini KPI/StatusPill solid tonuna indir (neutral/info → success düş; tip daraltma).
type Solid = "danger" | "warning" | "success";
function solid(tone: ReturnType<typeof stageTone>): Solid {
  return tone === "neutral" || tone === "info" ? "success" : tone;
}

export default async function Page() {
  const locale = getServerLocale();
  const cat = getCatalog(locale);
  const k = (key: string, p?: Record<string, string | number>) => t(cat, `screen.a17.${key}`, p);
  const view = await getAgentVersionView();
  const h = view.agent;

  const versions = sortedVersions(h);
  const active = activeVersion(h);
  const latest = latestVersion(h);
  const stages = countByStage(h);
  const recallable = recallableVersions(h);
  const rollbackTarget = previousPublishedVersion(h);
  const failedTests = failedTestVersions(h);
  const attention = openAttentionCount(h);

  const stageName = (s: VersionStage) => k(`stage.${s}`);
  const testName = (s: TestStatus) => k(`test.${s}`);
  const statusName = (s: VersionStatus) => k(`status.${s}`);
  const verLabel = (v: AgentVersion) => `v${formatNumber(locale, v.versionNo)}`;

  const numFmt = (n: number) => formatNumber(locale, n);
  const dateFmt = (iso: string) => formatDate(locale, new Date(iso), { dateStyle: "medium", timeStyle: "short" });
  const flowLabel = (n: number | null) => (n === null ? k("none") : `v${numFmt(n)}`);

  return (
    <section data-screen="A-17">
      <PageHeader title={k("title")} description={k("subtitle")} code="A-17" />

      <div style={{ marginBottom: "var(--rmc-space-4)" }}>
        <Alert tone="info">{k("scope_note")}</Alert>
      </div>

      <p style={{ ...muted, fontSize: "var(--rmc-size-sm)", marginTop: 0 }}>
        {k("as_of", { time: dateFmt(view.generatedAt) })}
        {" · "}
        <span>{k("tenant")}: {view.tenantName}</span>
        {" · "}
        <span>{k("agent_label")}: {h.agentName} <code style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{h.agentRef}</code></span>
        {" · "}
        <span>{k("lifecycle")}: <StatusPill tone={solid(stageTone(h.lifecycleState))}>{stageName(h.lifecycleState)}</StatusPill></span>
      </p>

      {/* Uyarılar (bütünlük / WORM / test / yayın) */}
      {!distinguishable(h) && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="danger">{k("alert.not_distinguishable", { count: numFmt(duplicateVersionNos(h).length + duplicateVersionIds(h).length) })}</Alert>
        </div>
      )}
      {missingActiveVersion(h) && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="danger">{k("alert.missing_active")}</Alert>
        </div>
      )}
      {!rollbackRefsResolve(h) && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="danger">{k("alert.rollback_ref_broken")}</Alert>
        </div>
      )}
      {failedTests.length > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="warning">{k("alert.test_blocked", { count: numFmt(failedTests.length) })}</Alert>
        </div>
      )}
      {h.activeVersionNo === null && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="warning">{k("alert.no_active")}</Alert>
        </div>
      )}
      {hasPendingChanges(h) && h.activeVersionNo !== null && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="info">{k("alert.pending_changes")}</Alert>
        </div>
      )}

      {/* Özet KPI'lar */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", margin: "var(--rmc-space-2) 0 var(--rmc-space-3)" }}>
        <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: 0 }}>{k("section.summary")}</h2>
        <Button variant="secondary">{k("action.new_version")}</Button>
      </div>
      <div style={grid()}>
        <Kpi label={k("kpi.versions")} value={numFmt(h.versions.length)} hint={k("kpi.versions_hint")} tone="info" />
        <Kpi label={k("kpi.active")} value={active ? verLabel(active) : k("none")} hint={k("kpi.active_hint")} tone={active ? "success" : "warning"} />
        <Kpi label={k("kpi.published")} value={numFmt(publishedVersions(h).length)} hint={k("kpi.published_hint")} tone="info" />
        <Kpi label={k("kpi.latest")} value={latest ? verLabel(latest) : k("none")} hint={k("kpi.latest_hint")} tone="neutral" />
        <Kpi label={k("kpi.recallable")} value={numFmt(recallable.length)} hint={k("kpi.recallable_hint")} tone={canRollback(h) ? "success" : "neutral"} />
        <Kpi label={k("kpi.pending")} value={hasPendingChanges(h) ? k("yes") : k("no")} hint={k("kpi.pending_hint")} tone={hasPendingChanges(h) ? "warning" : "success"} />
        <Kpi label={k("kpi.rollbacks")} value={numFmt(rollbackCount(h))} hint={k("kpi.rollbacks_hint")} tone="neutral" />
        <Kpi label={k("kpi.attention")} value={numFmt(attention)} hint={k("kpi.attention_hint")} tone={attention === 0 ? "success" : "danger"} />
      </div>

      {/* Sürüm geçmişi (DB §5.2 agent_version) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.history")}</h2>
      <Card>
        {versions.length === 0 ? (
          <EmptyState message={k("no_versions")} />
        ) : (
          <Table caption={k("history_caption")}>
            <thead>
              <tr style={rowBorder}>
                <th style={th}>{k("col.version")}</th>
                <th style={th}>{k("col.stage")}</th>
                <th style={th}>{k("col.status")}</th>
                <th style={th}>{k("col.test")}</th>
                <th style={th}>{k("col.config")}</th>
                <th style={th}>{k("col.published_by")}</th>
                <th style={thEnd}>{k("col.published_at")}</th>
                <th style={th}>{k("col.change")}</th>
              </tr>
            </thead>
            <tbody>
              {versions.map((v) => (
                <tr key={v.versionId} style={rowBorder}>
                  <td style={td}>
                    <strong>{verLabel(v)}</strong> <code style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{v.versionId}</code>
                    {isActive(h, v) && <> <StatusPill tone="success">{k("badge.active")}</StatusPill></>}
                    {isRollback(v) && <> <StatusPill tone="warning">{k("badge.rollback", { from: numFmt(v.rollbackOfNo as number) })}</StatusPill></>}
                  </td>
                  <td style={td}><StatusPill tone={solid(stageTone(v.stage))}>{stageName(v.stage)}</StatusPill></td>
                  <td style={td}><StatusPill tone={solid(statusTone(versionStatus(h, v)))}>{statusName(versionStatus(h, v))}</StatusPill></td>
                  <td style={td}><StatusPill tone={solid(testTone(v.testStatus))}>{testName(v.testStatus)}</StatusPill></td>
                  <td style={td}>
                    <span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>
                      {k("config_summary", { prompt: numFmt(v.promptVersionNo), flow: flowLabel(v.flowVersionNo), model: v.modelProfile, voice: v.voiceProfile, stt: v.sttProfile })}
                    </span>
                  </td>
                  <td style={td}>{v.publishedBy}</td>
                  <td style={tdEnd}>{dateFmt(v.publishedAt)}</td>
                  <td style={td}><span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{v.changeNote}</span></td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>{k("history_hint")}</p>

      {/* Aşama dağılımı (FR-AGT-005) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.stages")}</h2>
      <Card>
        <Table caption={k("stages_caption")}>
          <thead>
            <tr style={rowBorder}>
              <th style={th}>{k("col.stage")}</th>
              <th style={th}>{k("col.purpose")}</th>
              <th style={thEnd}>{k("col.count")}</th>
            </tr>
          </thead>
          <tbody>
            {STAGE_ORDER.map((s) => (
              <tr key={s} style={rowBorder}>
                <td style={td}><StatusPill tone={solid(stageTone(s))}>{stageName(s)}</StatusPill></td>
                <td style={td}><span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{k(`stage_desc.${s}`)}</span></td>
                <td style={tdEnd}>{numFmt(stages[s])}</td>
              </tr>
            ))}
            <tr style={{ borderTop: "2px solid var(--rmc-border-subtle)" }}>
              <td style={td}><strong>{k("total")}</strong></td>
              <td style={td} />
              <td style={tdEnd}><strong>{numFmt(h.versions.length)}</strong></td>
            </tr>
          </tbody>
        </Table>
      </Card>

      {/* Rollback / Geri alma (FR-AGT-006) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.rollback")}</h2>
      <Card>
        <div style={{ display: "flex", alignItems: "center", gap: "var(--rmc-space-3)", marginBottom: "var(--rmc-space-2)", flexWrap: "wrap" }}>
          <StatusPill tone={canRollback(h) ? "success" : "warning"}>{canRollback(h) ? k("rollback.eligible") : k("rollback.not_eligible")}</StatusPill>
          <strong>
            {active
              ? k("rollback.active", { version: verLabel(active), id: active.versionId })
              : k("rollback.no_active")}
          </strong>
        </div>
        {active && rollbackTarget && (
          <p style={{ marginTop: 0, marginBottom: "var(--rmc-space-3)" }}>
            {k("rollback.target", { target: verLabel(rollbackTarget), id: rollbackTarget.versionId, note: rollbackTarget.changeNote })}{" "}
            <Button variant="secondary">{k("action.rollback_to", { target: verLabel(rollbackTarget) })}</Button>
          </p>
        )}
        {recallable.length === 0 ? (
          <EmptyState message={k("no_recallable")} />
        ) : (
          <Table caption={k("rollback_caption")}>
            <thead>
              <tr style={rowBorder}>
                <th style={th}>{k("col.version")}</th>
                <th style={th}>{k("col.stage")}</th>
                <th style={th}>{k("col.test")}</th>
                <th style={thEnd}>{k("col.published_at")}</th>
                <th style={th}>{k("col.change")}</th>
                <th style={thEnd}>{k("col.action")}</th>
              </tr>
            </thead>
            <tbody>
              {recallable.map((v) => (
                <tr key={v.versionId} style={rowBorder}>
                  <td style={td}>
                    <strong>{verLabel(v)}</strong> <code style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{v.versionId}</code>
                    {rollbackTarget && v.versionNo === rollbackTarget.versionNo && <> <StatusPill tone="info">{k("badge.default_target")}</StatusPill></>}
                  </td>
                  <td style={td}><StatusPill tone={solid(stageTone(v.stage))}>{stageName(v.stage)}</StatusPill></td>
                  <td style={td}><StatusPill tone={solid(testTone(v.testStatus))}>{testName(v.testStatus)}</StatusPill></td>
                  <td style={tdEnd}>{dateFmt(v.publishedAt)}</td>
                  <td style={td}><span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{v.changeNote}</span></td>
                  <td style={tdEnd}><Button variant="secondary">{k("action.rollback_to", { target: verLabel(v) })}</Button></td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>{k("rollback_hint")}</p>

      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-5)" }}>{k("footnote")}</p>
    </section>
  );
}
