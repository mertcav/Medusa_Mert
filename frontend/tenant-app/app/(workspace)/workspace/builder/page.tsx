// WBS 13.4.4 — L2 ekranı A-04 "Agent Builder (kod yazmadan)" (gerçek içerik; 13.1.1 iskeletinin yerini alır).
//
// İÇERİK (BRD §17.5 A-04 "Kod yazmadan agent oluşturma"): tenant kullanıcısının KOD YAZMADAN (FR-AGT-001)
// bir Voice AI agent oluşturmasını sağlayan REHBERLİ yapılandırma görünümü. BAŞLANGIÇ NOKTASI (boş/şablon/
// klon — no-code), TASLAK ÖZETİ (tamamlanma/adım/mod/dil/iş kuralı/test), YAPILANDIRMA ADIMLARI (basics
// FR-AGT-002 · konuşma modeli FR-AGT-003 · bilgi A-08 · tool A-09 · ses/model A-07 · politika FR-AGT-009),
// HAZIRLIK & YAYIN kapısı (readyForDraft/readyForTest/readyForPublish — FR-AGT-005/010) ve no-code ŞABLON
// kütüphanesi. Bu ekran KONFİGÜRASYON'dur — A-02 gibi gerçek zamanlı DEĞİL (FR-ANA-012 dışı). TENANT-SCOPE
// (FR-TEN-002): yalnız oturum açan tenant'ın taslağı/şablonları (middleware 13.1.2 + RLS DB §6.3). HİJYEN
// (BRD §17.7 + §17.6): yalnız KONFİGÜRASYON META; ham müşteri içeriği/PII + prompt gövdesi/tool sırrı gömülmez
// (derin tasarım A-05/A-06/A-09, görsel kapı). GÜVENLİK (NFR 10.6): sır konmaz. RBAC (BRD §17.6):
// conversation_designer=Yönet · operations_manager=Düzenle · qa_analyst=— · human_agent=—. UI yalnız görsel
// kapı; kaydet/test'e gönder/yayınla nihai yetki + işlem backend'de. Tüm kullanıcı-görünür metin i18n'den (t()).
import type { CSSProperties } from "react";
import { getServerLocale } from "@/lib/i18n/server";
import { getCatalog, t, formatNumber, formatDate } from "@/lib/i18n";
import { PageHeader, Card, StatusPill, Alert, Table, Button, EmptyState } from "@/lib/ui/components";
import {
  getBuilderView,
  stepStatus,
  stepById,
  completedSteps,
  incompleteRequiredSteps,
  requiredStepsComplete,
  completionPercent,
  fieldsTotal,
  fieldsComplete,
  hasConversationModel,
  readyForDraft,
  readyForTest,
  readyForPublish,
  blockers,
  nextStep,
  stepTone,
  modelTone,
  testTone,
  startModeTone,
  readyTone,
  STEP_ORDER,
  type StepId,
  type StepStatus,
  type ConversationModel,
  type StartMode,
  type TestStatus,
  type BuilderStep,
  type BuilderTemplate,
} from "@/lib/tenant/builder";

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
  const k = (key: string, p?: Record<string, string | number>) => t(cat, `screen.a04.${key}`, p);
  const view = await getBuilderView();
  const { draft, templates } = view;
  const steps = draft.steps;

  const completed = completedSteps(steps);
  const incompleteReq = incompleteRequiredSteps(steps);
  const reqDone = requiredStepsComplete(steps);
  const pct = completionPercent(steps);
  const fTotal = fieldsTotal(steps);
  const fDone = fieldsComplete(steps);
  const canDraft = readyForDraft(draft);
  const canTest = readyForTest(draft);
  const canPublish = readyForPublish(draft);
  const block = blockers(draft);
  const next = nextStep(draft);

  const stepName = (id: StepId) => k(`step.${id}`);
  const stepDesc = (id: StepId) => k(`step_desc.${id}`);
  const statusName = (s: StepStatus) => k(`status.${s}`);
  const modelName = (m: ConversationModel) => k(`model.${m === null ? "none" : m}`);
  const testName = (s: TestStatus) => k(`test.${s}`);
  const startName = (m: StartMode) => k(`start.${m}`);
  const dt = (iso: string) => formatDate(locale, new Date(iso), { dateStyle: "short", timeStyle: "short" });

  // Adım sırasını STEP_ORDER ile sabitle (sahip olunan adımlar üzerinden).
  const orderedSteps = STEP_ORDER.map((id) => stepById(steps, id)).filter((s): s is BuilderStep => s !== undefined);

  const stepRow = (s: BuilderStep) => {
    const st = stepStatus(s);
    const isBlocking = s.required && st !== "complete";
    return (
      <tr key={s.id} style={rowBorder}>
        <td style={td}>
          {stepName(s.id)}
          <br />
          <span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{stepDesc(s.id)}</span>
        </td>
        <td style={td}>{s.required ? <StatusPill tone="info">{k("required.yes")}</StatusPill> : <span style={muted}>{k("required.no")}</span>}</td>
        <td style={td}><StatusPill tone={stepTone(st)}>{statusName(st)}</StatusPill></td>
        <td style={tdEnd}>{k("fields_count", { done: formatNumber(locale, s.fieldsComplete), total: formatNumber(locale, s.fieldsTotal) })}</td>
        <td style={td}>{isBlocking ? <StatusPill tone="danger">{k("flag.blocking")}</StatusPill> : <span style={muted}>{k("dash")}</span>}</td>
      </tr>
    );
  };

  const templateRow = (tpl: BuilderTemplate) => (
    <tr key={tpl.templateRef} style={rowBorder}>
      <td style={td}><code style={muted}>{tpl.templateRef}</code> {tpl.name}</td>
      <td style={td}><span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{tpl.purpose}</span></td>
      <td style={td}><StatusPill tone={modelTone(tpl.mode)}>{modelName(tpl.mode)}</StatusPill></td>
      <td style={td}>{tpl.languages.map((l) => l.toUpperCase()).join(", ")}</td>
      <td style={tdEnd}><Button variant="secondary">{k("action.from_template")}</Button></td>
    </tr>
  );

  const readinessRow = (labelKey: string, hintKey: string, ok: boolean) => (
    <tr style={rowBorder}>
      <td style={td}>
        {k(labelKey)}
        <br />
        <span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{k(hintKey)}</span>
      </td>
      <td style={tdEnd}><StatusPill tone={readyTone(ok)}>{ok ? k("ready.yes") : k("ready.no")}</StatusPill></td>
    </tr>
  );

  return (
    <section data-screen="A-04">
      <PageHeader title={k("title")} description={k("subtitle")} code="A-04" />

      <div style={{ marginBottom: "var(--rmc-space-4)" }}>
        <Alert tone="info">{k("scope_note")}</Alert>
      </div>

      <p style={{ ...muted, fontSize: "var(--rmc-size-sm)", marginTop: 0 }}>
        {k("as_of", { time: formatDate(locale, new Date(view.generatedAt), { dateStyle: "medium", timeStyle: "short" }) })}
        {" · "}
        <span>{k("tenant")}: {view.tenantName}</span>
        {" · "}
        <span>{k("draft_label")}: <code>{draft.draftRef}</code> {draft.name}</span>
      </p>

      {/* Uyarılar */}
      {!hasConversationModel(draft) && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="warning">{k("alert.no_model")}</Alert>
        </div>
      )}
      {!reqDone && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="warning">{k("alert.blockers", { count: formatNumber(locale, incompleteReq.length) })}</Alert>
        </div>
      )}
      {draft.testStatus === "failed" && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="danger">{k("alert.test_failed")}</Alert>
        </div>
      )}
      {canPublish && (
        <div style={{ margin: "var(--rmc-space-2) 0 var(--rmc-space-4)" }}>
          <Alert tone="success">{k("alert.ready_publish")}</Alert>
        </div>
      )}

      {/* Başlangıç noktası (no-code) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", marginBottom: "var(--rmc-space-3)" }}>{k("section.start")}</h2>
      <Card>
        <p style={{ marginTop: 0 }}>
          {k("start.mode_label")}: <StatusPill tone={startModeTone(draft.startMode)}>{startName(draft.startMode)}</StatusPill>
          {draft.startMode === "template" && draft.templateRef && <> {" · "}<span style={muted}>{k("start.from", { name: draft.templateRef })}</span></>}
          {draft.startMode === "clone" && draft.baseAgentRef && <> {" · "}<span style={muted}>{k("start.variant_note", { name: draft.baseAgentRef })}</span></>}
        </p>
        <p style={{ ...muted, fontSize: "var(--rmc-size-sm)", marginBottom: 0 }}>{k("start.hint")}</p>
      </Card>

      {/* Taslak özeti */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.summary")}</h2>
      <div style={grid()}>
        <Kpi label={k("kpi.completion")} value={k("percent", { n: formatNumber(locale, pct) })} hint={k("kpi.completion_hint")} tone={pct === 100 ? "success" : "warning"} />
        <Kpi label={k("kpi.steps")} value={`${formatNumber(locale, completed.length)} / ${formatNumber(locale, steps.length)}`} hint={k("kpi.steps_hint")} />
        <Kpi label={k("kpi.required")} value={formatNumber(locale, incompleteReq.length)} hint={k("kpi.required_hint")} tone={incompleteReq.length > 0 ? "warning" : "success"} />
        <Kpi label={k("kpi.fields")} value={`${formatNumber(locale, fDone)} / ${formatNumber(locale, fTotal)}`} hint={k("kpi.fields_hint")} />
        <Kpi label={k("kpi.model")} value={modelName(draft.conversationModel)} hint={k("kpi.model_hint")} tone={hasConversationModel(draft) ? "success" : "warning"} />
        <Kpi label={k("kpi.languages")} value={draft.languages.map((l) => l.toUpperCase()).join(", ")} hint={k("kpi.languages_hint")} />
        <Kpi label={k("kpi.rules")} value={formatNumber(locale, draft.businessRulesCount)} hint={k("kpi.rules_hint")} />
        <Kpi label={k("kpi.test")} value={testName(draft.testStatus)} hint={k("kpi.test_hint")} tone={draft.testStatus === "passed" ? "success" : draft.testStatus === "failed" ? "danger" : "warning"} />
      </div>

      {/* Yapılandırma adımları */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>
        <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: 0 }}>{k("section.steps")}</h2>
        <Button variant="primary">{k("action.new_blank")}</Button>
      </div>
      <Card>
        <Table caption={k("steps_caption")}>
          <thead>
            <tr style={rowBorder}>
              <th style={th}>{k("col.step")}</th>
              <th style={th}>{k("col.required")}</th>
              <th style={th}>{k("col.status")}</th>
              <th style={thEnd}>{k("col.fields")}</th>
              <th style={th}>{k("col.flag")}</th>
            </tr>
          </thead>
          <tbody>{orderedSteps.map(stepRow)}</tbody>
        </Table>
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-2)" }}>
        {next ? k("next_step", { step: stepName(next) }) : k("all_steps_done")}
      </p>

      {/* Hazırlık & yayın */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.readiness")}</h2>
      <Card>
        <Table caption={k("readiness_caption")}>
          <thead>
            <tr style={rowBorder}>
              <th style={th}>{k("col.gate")}</th>
              <th style={thEnd}>{k("col.ready")}</th>
            </tr>
          </thead>
          <tbody>
            {readinessRow("readiness.draft", "readiness.draft_hint", canDraft)}
            {readinessRow("readiness.test", "readiness.test_hint", canTest)}
            {readinessRow("readiness.publish", "readiness.publish_hint", canPublish)}
          </tbody>
        </Table>
      </Card>
      <div style={{ display: "flex", gap: "var(--rmc-space-3)", margin: "var(--rmc-space-3) 0" }}>
        <Button variant="secondary" disabled={!canTest}>{k("action.submit_test")}</Button>
        <Button variant="primary" disabled={!canPublish}>{k("action.publish")}</Button>
      </div>
      {block.length > 0 ? (
        <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: 0 }}>
          {k("blockers_label")}: {block.map((id) => stepName(id)).join(", ")}
        </p>
      ) : (
        <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: 0 }}>{k("no_blockers")}</p>
      )}
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-1)" }}>{k("readiness_hint")}</p>

      {/* Şablon kütüphanesi (no-code başlangıç) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.templates")}</h2>
      <Card>
        {templates.length === 0 ? (
          <EmptyState message={k("no_templates")} />
        ) : (
          <Table caption={k("templates_caption")}>
            <thead>
              <tr style={rowBorder}>
                <th style={th}>{k("col.template")}</th>
                <th style={th}>{k("col.purpose")}</th>
                <th style={th}>{k("col.mode")}</th>
                <th style={th}>{k("col.languages")}</th>
                <th style={thEnd}>{k("col.action")}</th>
              </tr>
            </thead>
            <tbody>{templates.map(templateRow)}</tbody>
          </Table>
        )}
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>{k("templates_hint")}</p>
    </section>
  );
}
