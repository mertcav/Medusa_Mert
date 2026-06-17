// WBS 13.2.6 — L0 ekranı P-06 "Global Politika & Guardrails" (gerçek içerik; 13.1.1 iskeletinin yerini alır).
//
// İÇERİK (BRD §17.3): global güvenlik politikaları, model allowlist, varsayılan compliance profilleri.
// FR-LLM-006 (system prompt kilidi) · FR-LLM-007 (prompt-injection/jailbreak) · FR-LLM-009 (output guard) ·
// FR-LLM-001/002/011/012 (model allowlist + versiyon + no-train) · FR-REC-004 (PII redaction) ·
// FR-KB-007 (anti-hallucination) · FR-IAM-010 (regüle tenant onayı). BRD §14.4 / DPIA `cp.*` compliance profile.
// ALTIN KURAL (BRD §17.7 / FR-IAM-008): yalnız platform-geneli politika/guardrail/model-allowlist + varsayılan
// compliance-profile metadatası; tenant iş içeriği (çağrı kaydı/transkript/son-müşteri PII) GÖSTERİLMEZ —
// veri katmanı `assertNoPii` ile garanti eder. VENDOR-NEUTRAL (ADR-002): model id'leri/etiketler nötr.
// RBAC (BRD §17.6): platform_owner=Yönet + platform_sre=Görüntüle + platform_billing=erişim yok. UI yalnız
// görsel kapı; nihai yetki + politika zorlaması backend Policy Engine'de (12.2.x; permission-key policy:read +
// policy:guardrail:manage + policy:model_allowlist:manage + policy:compliance_profile:manage, SAD §7 · §14.4.1
// A8). Tüm kullanıcı-görünür metin i18n katalogundan (t()).
import type { CSSProperties } from "react";
import { getServerLocale } from "@/lib/i18n/server";
import { getCatalog, t, formatNumber, formatDate, type Locale } from "@/lib/i18n";
import { PageHeader, Card, StatusPill, Alert, Table, EmptyState, Button } from "@/lib/ui/components";
import {
  getPolicy,
  enforcementTone,
  guardrailTone,
  modelStatusTone,
  profileStatusTone,
  countEnabledGuardrails,
  policyGaps,
  noTrainViolations,
  allowedModelCount,
  activeProfileCount,
  coveredTenants,
  type GuardrailCategory,
  type Enforcement,
  type GuardrailStatus,
  type ModelCategory,
  type ModelTier,
  type ModelStatus,
  type ProfileStatus,
  type Sector,
  type Country,
  type GuardrailPolicy,
  type ModelAllowlistEntry,
  type ComplianceProfileDefault,
} from "@/lib/platform/policy";

function Kpi({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <Card>
      <div style={{ color: "var(--rmc-text-muted)", fontSize: "var(--rmc-size-sm)" }}>{label}</div>
      <div style={{ fontSize: "var(--rmc-size-2xl)", fontWeight: 700, color: tone ?? "var(--rmc-text-primary)" }}>{value}</div>
    </Card>
  );
}

function grid(): CSSProperties {
  return { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))", gap: "var(--rmc-space-4)", marginBottom: "var(--rmc-space-5)" };
}

const cell: CSSProperties = { padding: "var(--rmc-space-2)" };

export default async function Page() {
  const locale: Locale = getServerLocale();
  const cat = getCatalog(locale);
  const k = (key: string, p?: Record<string, string | number>) => t(cat, `screen.p06.${key}`, p);
  const snap = await getPolicy();
  const { guardrails, models, complianceProfiles } = snap;

  const num = (n: number) => formatNumber(locale, n);
  const guardrailCategoryName = (c: GuardrailCategory) => k(`guardrail_category.${c}`);
  const enforcementLabel = (e: Enforcement) => k(`enforcement.${e}`);
  const guardrailStatusLabel = (s: GuardrailStatus) => k(`guardrail_status.${s}`);
  const modelCategoryName = (c: ModelCategory) => k(`model_category.${c}`);
  const modelTierLabel = (tier: ModelTier) => k(`model_tier.${tier}`);
  const modelStatusLabel = (s: ModelStatus) => k(`model_status.${s}`);
  const profileStatusLabel = (s: ProfileStatus) => k(`profile_status.${s}`);
  const sectorLabel = (s: Sector) => k(`sector.${s}`);
  const countryLabel = (c: Country) => k(`country.${c}`);
  const boolLabel = (b: boolean) => k(b ? "bool.yes" : "bool.no");

  const enabled = countEnabledGuardrails(guardrails);
  const gaps = policyGaps(snap);
  const noTrain = noTrainViolations(snap);
  const covered = coveredTenants(complianceProfiles);

  return (
    <section data-screen="P-06">
      <PageHeader title={k("title")} description={k("subtitle")} code="P-06" />

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
        {/* Politika düzenle — UI yalnız görsel kapı; zorlama backend Policy Engine'de (A8). */}
        <Button variant="primary">{k("manage_action")}</Button>
      </div>

      {/* Özet KPI */}
      <div style={grid()}>
        <Kpi label={k("kpi.active_guardrails")} value={`${num(enabled)} / ${num(guardrails.length)}`} />
        <Kpi label={k("kpi.allowed_models")} value={num(allowedModelCount(models))} />
        <Kpi label={k("kpi.active_profiles")} value={num(activeProfileCount(complianceProfiles))} />
        <Kpi label={k("kpi.covered_tenants")} value={num(covered)} />
        <Kpi label={k("kpi.no_train_violations")} value={num(noTrain.length)} tone={noTrain.length > 0 ? "var(--rmc-danger-fg)" : undefined} />
        <Kpi label={k("kpi.policy_gaps")} value={num(gaps.length)} tone={gaps.length > 0 ? "var(--rmc-danger-fg)" : undefined} />
      </div>

      {/* Politika boşluğu (zorunlu+kapalı guardrail) + no-train ihlali (FR-LLM-012) uyarıları */}
      <div style={{ marginBottom: "var(--rmc-space-2)" }}>
        {gaps.length === 0 ? (
          <Alert tone="success">{k("no_policy_gap")}</Alert>
        ) : (
          <Alert tone="danger">{k("policy_gap_alert", { count: num(gaps.length) })}</Alert>
        )}
      </div>
      <div style={{ marginBottom: "var(--rmc-space-5)" }}>
        {noTrain.length === 0 ? (
          <Alert tone="success">{k("no_train_ok")}</Alert>
        ) : (
          <Alert tone="danger">{k("no_train_alert", { count: num(noTrain.length) })}</Alert>
        )}
      </div>

      {/* Global güvenlik politikaları (Policy Engine guardrail'leri) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", marginBottom: "var(--rmc-space-3)" }}>{k("section.security")}</h2>
      <Card>
        {guardrails.length === 0 ? (
          <EmptyState message={k("no_guardrails")} />
        ) : (
          <Table caption={k("guardrails_caption")}>
            <thead>
              <tr style={{ textAlign: "start", borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.policy")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.enforcement")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.status")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.mandatory")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.requirement")}</th>
              </tr>
            </thead>
            <tbody>
              {guardrails.map((g: GuardrailPolicy) => (
                <tr key={g.id} style={{ borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                  <td style={cell}>{guardrailCategoryName(g.category)}</td>
                  <td style={cell}>
                    <StatusPill tone={enforcementTone(g.enforcement)}>{enforcementLabel(g.enforcement)}</StatusPill>
                  </td>
                  <td style={cell}>
                    <StatusPill tone={guardrailTone(g)}>{guardrailStatusLabel(g.status)}</StatusPill>
                  </td>
                  <td style={cell}>{boolLabel(g.mandatory)}</td>
                  <td style={cell}>{g.mappedFr}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      {/* Model allowlist (FR-LLM-001/002/011/012) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.models")}</h2>
      <Card>
        {models.length === 0 ? (
          <EmptyState message={k("no_models")} />
        ) : (
          <Table caption={k("models_caption")}>
            <thead>
              <tr style={{ textAlign: "start", borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.model")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.category")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.tier")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.status")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.no_train")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.version_pinned")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.regions")}</th>
              </tr>
            </thead>
            <tbody>
              {models.map((m: ModelAllowlistEntry) => (
                <tr key={m.id} style={{ borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                  <td style={cell}>{m.id}</td>
                  <td style={cell}>{modelCategoryName(m.category)}</td>
                  <td style={cell}>{modelTierLabel(m.tier)}</td>
                  <td style={cell}>
                    <StatusPill tone={modelStatusTone(m.status)}>{modelStatusLabel(m.status)}</StatusPill>
                  </td>
                  <td style={cell}>{boolLabel(m.noTrainDefault)}</td>
                  <td style={cell}>{boolLabel(m.versionPinned)}</td>
                  <td style={cell}>{m.regions.length > 0 ? m.regions.map((r) => t(cat, `region.${r}`)).join(", ") : "—"}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      {/* Varsayılan compliance profilleri (BRD §14.4 / DPIA cp.*) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.compliance")}</h2>
      <Card>
        {complianceProfiles.length === 0 ? (
          <EmptyState message={k("no_profiles")} />
        ) : (
          <Table caption={k("profiles_caption")}>
            <thead>
              <tr style={{ textAlign: "start", borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.profile")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.country")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.sector")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.residency")}</th>
                <th style={{ ...cell, textAlign: "end" }}>{k("col.retention")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.tenant_approval")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.override")}</th>
                <th style={{ ...cell, textAlign: "end" }}>{k("col.tenants")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.status")}</th>
              </tr>
            </thead>
            <tbody>
              {complianceProfiles.map((p: ComplianceProfileDefault) => (
                <tr key={p.id} style={{ borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                  <td style={cell}>{p.id}</td>
                  <td style={cell}>{countryLabel(p.country)}</td>
                  <td style={cell}>{sectorLabel(p.sector)}</td>
                  <td style={cell}>{countryLabel(p.residency)}</td>
                  <td style={{ ...cell, textAlign: "end" }}>{k("days_value", { days: num(p.retentionDays) })}</td>
                  <td style={cell}>{boolLabel(p.requireTenantApproval)}</td>
                  <td style={cell}>{boolLabel(p.overrideOnlyStricter)}</td>
                  <td style={{ ...cell, textAlign: "end" }}>{num(p.appliedTenants)}</td>
                  <td style={cell}>
                    <StatusPill tone={profileStatusTone(p.status)}>{profileStatusLabel(p.status)}</StatusPill>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
        <p style={{ color: "var(--rmc-text-muted)", fontSize: "var(--rmc-size-sm)", marginTop: "var(--rmc-space-3)" }}>
          {k("profiles_total", { profiles: num(covered) })}
        </p>
      </Card>
    </section>
  );
}
