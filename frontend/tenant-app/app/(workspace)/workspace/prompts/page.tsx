// WBS 13.4.6 — L2 ekranı A-06 "Prompt Editor (versiyonlama)" (gerçek içerik; 13.1.1 iskeletinin yerini alır).
//
// İÇERİK (BRD §17.5 A-06 "Prompt Editor"): bir agent system prompt'unun SÜRÜM GEÇMİŞİ ve versiyonlama
// görünümü (FR-AGT-004). SÜRÜM ÖZETİ (sürüm sayısı/aktif/yayınlı/taslak/en-son + bekleyen/test-bloklu/
// dikkat), SÜRÜM GEÇMİŞİ tablosu (sürüm no + AYIRT EDİCİ KİMLİK SR-AGT-004 · aşama FR-AGT-005 · durum ·
// test FR-AGT-010 · oluşturma · yazar · değişiklik notu · boyut SAYISI · işaret), AŞAMA DAĞILIMI ve GERİ ALMA
// (rollback FR-AGT-006: aktif sürüm + geri çağrılabilir sürümler). Prompt GÖVDESİ gösterilmez — gövde
// düzenleme (editör alanı) derin aksiyondur (client island → API dilimi). TENANT-SCOPE (FR-TEN-002):
// yalnız oturum açan tenant'ın agent'ının prompt sürümleri (middleware 13.1.2 + RLS DB §6.3). HİJYEN
// (BRD §17.7 + §17.6): yalnız SÜRÜM META; ham müşteri içeriği/PII + prompt gövdesi gömülmez. GÜVENLİK
// (NFR 10.6): sır konmaz. RBAC (BRD §17.6): conversation_designer=Yönet · operations_manager=Düzenle ·
// qa_analyst=Görüntüle · human_agent=—. UI yalnız görsel kapı; düzenle/test/yayınla/geri-al nihai yetki +
// işlem backend'de. Tüm kullanıcı-görünür metin i18n'den (t()).
import type { CSSProperties } from "react";
import { getServerLocale } from "@/lib/i18n/server";
import { getCatalog, t, formatNumber, formatDate } from "@/lib/i18n";
import { PageHeader, Card, StatusPill, Alert, Table, Button, EmptyState } from "@/lib/ui/components";
import {
  getPromptView,
  sortedVersions,
  activeVersion,
  latestVersion,
  countByStage,
  publishedVersions,
  draftVersions,
  recallableVersions,
  canRollback,
  hasPendingChanges,
  failedTestVersions,
  duplicateVersionNos,
  duplicateVersionIds,
  distinguishable,
  missingActiveVersion,
  openAttentionCount,
  versionStatus,
  stageTone,
  statusTone,
  testTone,
  STAGE_ORDER,
  type PromptStage,
  type TestStatus,
  type VersionStatus,
  type PromptVersion,
} from "@/lib/tenant/prompts";

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
  const k = (key: string, p?: Record<string, string | number>) => t(cat, `screen.a06.${key}`, p);
  const view = await getPromptView();
  const { prompt } = view;

  const versions = sortedVersions(prompt);
  const active = activeVersion(prompt);
  const latest = latestVersion(prompt);
  const stageCounts = countByStage(prompt);
  const published = publishedVersions(prompt);
  const drafts = draftVersions(prompt);
  const recallable = recallableVersions(prompt);
  const rollbackOk = canRollback(prompt);
  const pending = hasPendingChanges(prompt);
  const failed = failedTestVersions(prompt);
  const dupNos = duplicateVersionNos(prompt);
  const dupIds = duplicateVersionIds(prompt);
  const isDistinguishable = distinguishable(prompt);
  const missingActive = missingActiveVersion(prompt);
  const attention = openAttentionCount(prompt);

  const stageName = (s: PromptStage) => k(`stage.${s}`);
  const stageDesc = (s: PromptStage) => k(`stage_desc.${s}`);
  const statusName = (s: VersionStatus) => k(`status.${s}`);
  const testName = (s: TestStatus) => k(`test.${s}`);

  const totalVersions = prompt.versions.length;
  const presentStages = STAGE_ORDER.filter((s) => stageCounts[s] > 0);

  const versionRow = (v: PromptVersion) => {
    const st = versionStatus(prompt, v);
    return (
      <tr key={v.versionId} style={rowBorder}>
        <td style={td}>
          <strong>v{formatNumber(locale, v.versionNo)}</strong> <code style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{v.versionId}</code>
        </td>
        <td style={td}><StatusPill tone={stageTone(v.stage)}>{stageName(v.stage)}</StatusPill></td>
        <td style={td}><StatusPill tone={statusTone(st)}>{statusName(st)}</StatusPill></td>
        <td style={td}><StatusPill tone={testTone(v.testStatus)}>{testName(v.testStatus)}</StatusPill></td>
        <td style={td}><span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{formatDate(locale, new Date(v.createdAt), { dateStyle: "medium", timeStyle: "short" })}</span></td>
        <td style={td}>{v.author}</td>
        <td style={td}><span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{v.changeNote}</span></td>
        <td style={tdEnd}><span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{k("size", { chars: formatNumber(locale, v.charCount), vars: formatNumber(locale, v.variableCount) })}</span></td>
      </tr>
    );
  };

  const recallRow = (v: PromptVersion) => (
    <tr key={v.versionId} style={rowBorder}>
      <td style={td}>
        <strong>v{formatNumber(locale, v.versionNo)}</strong> <code style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{v.versionId}</code>
      </td>
      <td style={td}><StatusPill tone={stageTone(v.stage)}>{stageName(v.stage)}</StatusPill></td>
      <td style={td}><span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{formatDate(locale, new Date(v.createdAt), { dateStyle: "medium" })}</span></td>
      <td style={tdEnd}><Button variant="secondary">{k("action.rollback_to")}</Button></td>
    </tr>
  );

  return (
    <section data-screen="A-06">
      <PageHeader title={k("title")} description={k("subtitle")} code="A-06" />

      <div style={{ marginBottom: "var(--rmc-space-4)" }}>
        <Alert tone="info">{k("scope_note")}</Alert>
      </div>

      <p style={{ ...muted, fontSize: "var(--rmc-size-sm)", marginTop: 0 }}>
        {k("as_of", { time: formatDate(locale, new Date(view.generatedAt), { dateStyle: "medium", timeStyle: "short" }) })}
        {" · "}
        <span>{k("tenant")}: {view.tenantName}</span>
        {" · "}
        <span>{k("agent_label")}: <code>{prompt.agentRef}</code> {prompt.agentName}</span>
        {" · "}
        <span>{k("prompt_label")}: <code>{prompt.promptRef}</code></span>
      </p>

      {/* Uyarılar */}
      {!isDistinguishable && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="danger">{k("alert.not_distinguishable", { count: formatNumber(locale, dupNos.length + dupIds.length) })}</Alert>
        </div>
      )}
      {missingActive && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="danger">{k("alert.missing_active")}</Alert>
        </div>
      )}
      {failed.length > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="warning">{k("alert.test_blocked", { count: formatNumber(locale, failed.length) })}</Alert>
        </div>
      )}
      {active === null && !missingActive && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="warning">{k("alert.no_active")}</Alert>
        </div>
      )}
      {pending && active !== null && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="info">{k("alert.pending_changes")}</Alert>
        </div>
      )}

      {/* Sürüm özeti */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", margin: "var(--rmc-space-2) 0 var(--rmc-space-3)" }}>
        <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: 0 }}>{k("section.summary")}</h2>
        <Button variant="primary">{k("action.new_version")}</Button>
      </div>
      <div style={grid()}>
        <Kpi label={k("kpi.versions")} value={formatNumber(locale, totalVersions)} hint={k("kpi.versions_hint")} />
        <Kpi label={k("kpi.active")} value={active ? `v${formatNumber(locale, active.versionNo)}` : k("none")} hint={k("kpi.active_hint")} tone={active ? "success" : "warning"} />
        <Kpi label={k("kpi.published")} value={formatNumber(locale, published.length)} hint={k("kpi.published_hint")} />
        <Kpi label={k("kpi.draft")} value={formatNumber(locale, drafts.length)} hint={k("kpi.draft_hint")} />
        <Kpi label={k("kpi.latest")} value={latest ? `v${formatNumber(locale, latest.versionNo)}` : k("none")} hint={k("kpi.latest_hint")} />
        <Kpi label={k("kpi.pending")} value={pending ? k("yes") : k("no")} hint={k("kpi.pending_hint")} tone={pending ? "warning" : "success"} />
        <Kpi label={k("kpi.test_blocked")} value={formatNumber(locale, failed.length)} hint={k("kpi.test_blocked_hint")} tone={failed.length > 0 ? "danger" : "success"} />
        <Kpi label={k("kpi.attention")} value={formatNumber(locale, attention)} hint={k("kpi.attention_hint")} tone={attention > 0 ? "warning" : "success"} />
      </div>

      {/* Sürüm geçmişi (SR-AGT-004) */}
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
                <th style={th}>{k("col.created")}</th>
                <th style={th}>{k("col.author")}</th>
                <th style={th}>{k("col.change")}</th>
                <th style={thEnd}>{k("col.size")}</th>
              </tr>
            </thead>
            <tbody>{versions.map(versionRow)}</tbody>
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
              <th style={thEnd}>{k("col.share")}</th>
            </tr>
          </thead>
          <tbody>
            {presentStages.map((s) => (
              <tr key={s} style={rowBorder}>
                <td style={td}><StatusPill tone={stageTone(s)}>{stageName(s)}</StatusPill></td>
                <td style={td}><span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{stageDesc(s)}</span></td>
                <td style={tdEnd}>{formatNumber(locale, stageCounts[s])}</td>
                <td style={tdEnd}>{k("percent", { n: formatNumber(locale, totalVersions > 0 ? Math.round((stageCounts[s] / totalVersions) * 100) : 0) })}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>

      {/* Geri alma (FR-AGT-006) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.rollback")}</h2>
      <div style={{ marginBottom: "var(--rmc-space-3)" }}>
        <Alert tone={active ? "success" : "warning"}>
          {active ? k("rollback.active", { version: `v${formatNumber(locale, active.versionNo)}`, id: active.versionId }) : k("rollback.no_active")}
        </Alert>
      </div>
      <Card>
        {recallable.length === 0 ? (
          <EmptyState message={k("no_recallable")} />
        ) : (
          <Table caption={k("rollback_caption")}>
            <thead>
              <tr style={rowBorder}>
                <th style={th}>{k("col.version")}</th>
                <th style={th}>{k("col.stage")}</th>
                <th style={th}>{k("col.created")}</th>
                <th style={thEnd}>{k("col.action")}</th>
              </tr>
            </thead>
            <tbody>{recallable.map(recallRow)}</tbody>
          </Table>
        )}
      </Card>
      <div style={{ display: "flex", gap: "var(--rmc-space-3)", margin: "var(--rmc-space-3) 0" }}>
        <Button variant="secondary" disabled={!rollbackOk}>{k("action.rollback")}</Button>
      </div>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: 0 }}>{k("rollback_hint")}</p>
    </section>
  );
}
