// WBS 13.2.8 — L0 ekranı P-08 "Sürüm & Dağıtım (Release) Yönetimi" (gerçek içerik; 13.1.1 iskeletinin yerini alır).
//
// İÇERİK (BRD §17.3): platform versiyonlama, feature flag, kademeli yayma (canary/staged rollout).
// FR-AGT-005 (draft/test/staging/production yaşam döngüsü — platform ölçeğinde) · FR-AGT-006 (tek-işlem
// rollback) · FR-IAM-008 (panel-katman rol ayrımı / altın kural) · NFR 10.7 (bölgesel dağıtım).
// ALTIN KURAL (BRD §17.7 / FR-IAM-008): yalnız platform-geneli sürüm/dağıtım/feature-flag METADATASI; tenant
// iş içeriği (çağrı kaydı/transkript/son-müşteri PII) GÖSTERİLMEZ — veri katmanı `assertNoPii` ile garanti eder.
// Feature flag `enabledTenants` toplulaştırılmış SAYIDIR (liste değil). RBAC (BRD §17.6): platform_owner=Yönet +
// platform_sre=Düzenle + platform_billing=erişim yok. UI yalnız görsel kapı; nihai yetki + dağıtım/kademeli
// yayma/rollback/flag zorlaması backend'de (12.2.x; permission-key release:read + release:deploy +
// release:rollback + featureflag:manage, SAD §7 · §14.4.1 A8). Tüm kullanıcı-görünür metin i18n katalogundan (t()).
import type { CSSProperties } from "react";
import { getServerLocale } from "@/lib/i18n/server";
import { getCatalog, t, formatNumber, formatDate, type Locale } from "@/lib/i18n";
import { PageHeader, Card, StatusPill, Alert, Table, EmptyState, Button } from "@/lib/ui/components";
import {
  getReleases,
  releaseStageTone,
  releaseHealthTone,
  rolloutStrategyTone,
  flagStatusTone,
  deploymentOutcomeTone,
  deploymentTypeTone,
  countByStage,
  activeFlagCount,
  failingReleases,
  canaryRisks,
  failedDeployments,
  flagConfigGaps,
  type PlatformRole,
  type ReleaseStage,
  type ReleaseHealth,
  type RolloutStrategy,
  type FlagStatus,
  type DeploymentEventType,
  type DeploymentOutcome,
  type PlatformRelease,
  type FeatureFlag,
  type DeploymentEvent,
} from "@/lib/platform/releases";

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
  const k = (key: string, p?: Record<string, string | number>) => t(cat, `screen.p08.${key}`, p);
  const snap = await getReleases();
  const { releases, flags, events } = snap;

  const num = (n: number) => formatNumber(locale, n);
  const dt = (iso: string) => formatDate(locale, new Date(iso), { dateStyle: "short", timeStyle: "short" });
  const pct = (n: number) => k("pct_value", { pct: num(n) });
  const roleLabel = (r: PlatformRole) => k(`actor_role.${r}`);
  const stageLabel = (s: ReleaseStage) => k(`release_stage.${s}`);
  const healthLabel = (h: ReleaseHealth) => k(`release_health.${h}`);
  const strategyLabel = (s: RolloutStrategy) => k(`rollout_strategy.${s}`);
  const flagStatusLabel = (s: FlagStatus) => k(`flag_status.${s}`);
  const eventTypeLabel = (t2: DeploymentEventType) => k(`deployment_type.${t2}`);
  const outcomeLabel = (o: DeploymentOutcome) => k(`deployment_outcome.${o}`);

  const byStage = countByStage(releases);
  const activeFlags = activeFlagCount(flags);
  const failing = failingReleases(snap);
  const canary = canaryRisks(snap);
  const failedDeploys = failedDeployments(events);
  const flagGaps = flagConfigGaps(flags);

  return (
    <section data-screen="P-08">
      <PageHeader title={k("title")} description={k("subtitle")} code="P-08" />

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
        {/* Dağıtım planlama — UI yalnız görsel kapı; zorlama backend'de (A8). */}
        <Button variant="primary">{k("deploy_action")}</Button>
      </div>

      {/* Özet KPI */}
      <div style={grid()}>
        <Kpi label={k("kpi.releases")} value={num(releases.length)} />
        <Kpi label={k("kpi.in_production")} value={num(byStage.production)} />
        <Kpi label={k("kpi.canaries")} value={num(byStage.canary)} tone={byStage.canary > 0 ? "var(--rmc-warning-fg)" : undefined} />
        <Kpi label={k("kpi.active_flags")} value={num(activeFlags)} />
        <Kpi label={k("kpi.failing")} value={num(failing.length)} tone={failing.length > 0 ? "var(--rmc-danger-fg)" : undefined} />
        <Kpi label={k("kpi.failed_deploys")} value={num(failedDeploys.length)} tone={failedDeploys.length > 0 ? "var(--rmc-danger-fg)" : undefined} />
      </div>

      {/* Dağıtım sağlığı + canary + başarısız dağıtım + flag yapılandırma uyarıları */}
      <div style={{ marginBottom: "var(--rmc-space-2)" }}>
        {failing.length === 0 ? (
          <Alert tone="success">{k("health_ok")}</Alert>
        ) : (
          <Alert tone="danger">{k("health_alert", { count: num(failing.length) })}</Alert>
        )}
      </div>
      <div style={{ marginBottom: "var(--rmc-space-2)" }}>
        {canary.length === 0 ? (
          <Alert tone="success">{k("canary_ok")}</Alert>
        ) : (
          <Alert tone="warning">{k("canary_alert", { count: num(canary.length) })}</Alert>
        )}
      </div>
      <div style={{ marginBottom: "var(--rmc-space-2)" }}>
        {failedDeploys.length === 0 ? (
          <Alert tone="success">{k("deploy_ok")}</Alert>
        ) : (
          <Alert tone="danger">{k("deploy_alert", { count: num(failedDeploys.length) })}</Alert>
        )}
      </div>
      <div style={{ marginBottom: "var(--rmc-space-5)" }}>
        {flagGaps.length === 0 ? (
          <Alert tone="success">{k("flags_ok")}</Alert>
        ) : (
          <Alert tone="warning">{k("flags_alert", { count: num(flagGaps.length) })}</Alert>
        )}
      </div>

      {/* Platform sürümleri (FR-AGT-005 yaşam döngüsü + FR-AGT-006 rollback) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", marginBottom: "var(--rmc-space-3)" }}>{k("section.releases")}</h2>
      <Card>
        {releases.length === 0 ? (
          <EmptyState message={k("no_releases")} />
        ) : (
          <Table caption={k("releases_caption")}>
            <thead>
              <tr style={{ textAlign: "start", borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.version")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.component")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.stage")}</th>
                <th style={{ ...cell, textAlign: "end" }}>{k("col.rollout")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.health")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.region")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.created")}</th>
              </tr>
            </thead>
            <tbody>
              {releases.map((r: PlatformRelease) => (
                <tr key={r.id} style={{ borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                  <td style={cell}>{r.version}</td>
                  <td style={cell}>{r.component}</td>
                  <td style={cell}>
                    <StatusPill tone={releaseStageTone(r.stage)}>{stageLabel(r.stage)}</StatusPill>
                  </td>
                  <td style={{ ...cell, textAlign: "end" }}>{pct(r.rolloutPct)}</td>
                  <td style={cell}>
                    <StatusPill tone={releaseHealthTone(r.health)}>{healthLabel(r.health)}</StatusPill>
                  </td>
                  <td style={cell}>{r.region}</td>
                  <td style={cell}>{dt(r.createdAt)}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      {/* Feature flag'ler (kademeli yayma kontrolü) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.flags")}</h2>
      <Card>
        {flags.length === 0 ? (
          <EmptyState message={k("no_flags")} />
        ) : (
          <Table caption={k("flags_caption")}>
            <thead>
              <tr style={{ textAlign: "start", borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.flag")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.status")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.strategy")}</th>
                <th style={{ ...cell, textAlign: "end" }}>{k("col.rollout")}</th>
                <th style={{ ...cell, textAlign: "end" }}>{k("col.enabled_tenants")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.updated")}</th>
              </tr>
            </thead>
            <tbody>
              {flags.map((f: FeatureFlag) => (
                <tr key={f.id} style={{ borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                  <td style={cell}>{f.key}</td>
                  <td style={cell}>
                    <StatusPill tone={flagStatusTone(f.status)}>{flagStatusLabel(f.status)}</StatusPill>
                  </td>
                  <td style={cell}>
                    <StatusPill tone={rolloutStrategyTone(f.strategy)}>{strategyLabel(f.strategy)}</StatusPill>
                  </td>
                  <td style={{ ...cell, textAlign: "end" }}>{f.strategy === "percentage" ? pct(f.rolloutPct) : "—"}</td>
                  <td style={{ ...cell, textAlign: "end" }}>{num(f.enabledTenants)}</td>
                  <td style={cell}>{dt(f.updatedAt)}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
        <p style={{ color: "var(--rmc-text-muted)", fontSize: "var(--rmc-size-sm)", marginTop: "var(--rmc-space-3)" }}>
          {k("flags_note")}
        </p>
      </Card>

      {/* Dağıtım olayları (promote/rollback/flag değişikliği/canary durdurma) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.events")}</h2>
      <Card>
        {events.length === 0 ? (
          <EmptyState message={k("no_events")} />
        ) : (
          <Table caption={k("events_caption")}>
            <thead>
              <tr style={{ textAlign: "start", borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.time")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.event_type")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.actor")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.target")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.outcome")}</th>
                <th style={{ ...cell, textAlign: "start" }}>{k("col.requirement")}</th>
              </tr>
            </thead>
            <tbody>
              {events.map((ev: DeploymentEvent) => (
                <tr key={ev.id} style={{ borderBottom: "1px solid var(--rmc-border-subtle)" }}>
                  <td style={cell}>{dt(ev.occurredAt)}</td>
                  <td style={cell}>
                    <StatusPill tone={deploymentTypeTone(ev.type)}>{eventTypeLabel(ev.type)}</StatusPill>
                  </td>
                  <td style={cell}>{roleLabel(ev.actorRole)}</td>
                  <td style={cell}>{ev.target}</td>
                  <td style={cell}>
                    <StatusPill tone={deploymentOutcomeTone(ev.outcome)}>{outcomeLabel(ev.outcome)}</StatusPill>
                  </td>
                  <td style={cell}>{ev.mappedFr}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </section>
  );
}
