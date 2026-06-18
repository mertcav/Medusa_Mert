// WBS 13.3.6 — L1 ekranı T-06 "Compliance & Retention" (gerçek içerik; 13.1.1 iskeletinin yerini alır).
//
// İÇERİK (BRD §17.4 / FR-REC-001..010 · FR-OUT-003/006 · DPIA cp.* · NFR 10.7): tenant'ın CONSENT (rıza
// modeli), KAYIT POLİTİKASI (recording policy + PII redaction + kart/OTP maskeleme), VERİ YERLEŞİMİ
// (residency), SAKLAMA SÜRESİ (retention + legal hold), COMPLIANCE PROFILE (ülke profili + sektörel overlay +
// most-restrictive-wins) ve İYS/DNC (outbound consent registry + do-not-call). Ayrıca DSR + ihlal bildirimi +
// DPIA durumu + tenant override'ları. TENANT-SCOPE (FR-TEN-002): yalnız oturum açan tenant'ın KENDİ profili;
// scope middleware (13.1.2) + RLS (§13) ile sabitlenir. HİJYEN (BRD §17.7) + GÜVENLİK (NFR 10.6): ham
// son-müşteri içeriği (çağrı kaydı/transkript/bireysel rıza-DNC kaydı/PII) ve SIR (KMS/credential) gömülmez —
// veri katmanı `assertNoPii` ile garanti eder. RBAC (BRD §17.6): tenant_owner=Yönet · tenant_admin=Görüntüle ·
// security_compliance_officer=Yönet · billing_viewer=— · api_developer=—. UI yalnız görsel kapı; nihai yetki
// backend'de (12.2.x, SAD §14.4.1 A8). Değerler MÜHENDİSLİK VARSAYILANIDIR; counsel doğrulamasına tabi (DPIA
// §12). Tüm kullanıcı-görünür metin i18n katalogundan (t()).
import type { CSSProperties } from "react";
import { getServerLocale } from "@/lib/i18n/server";
import { getCatalog, t, formatNumber, formatDate } from "@/lib/i18n";
import { PageHeader, Card, StatusPill, Alert, Table, Button, EmptyState } from "@/lib/ui/components";
import {
  getCompliance,
  disclosureGaps,
  recordingGaps,
  residencyGaps,
  outboundGaps,
  loosenOverrides,
  invalidRetention,
  dpiaPending,
  openWarningCount,
  dpiaStatusTone,
  overrideDirectionTone,
  crossBorderTone,
  consentModelTone,
  channelModeTone,
  requiredFlagTone,
  guardFlagTone,
  type ChannelMode,
  type ConsentModel,
  type RecordingConsentModel,
  type CrossBorderMechanism,
  type DpiaStatus,
  type OverrideDirection,
  type HomeRegion,
  type DataSubjectNotice,
} from "@/lib/tenant/compliance";

function Kpi({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: "danger" | "success" }) {
  const valueColor = tone === "danger" ? "var(--rmc-danger-fg, #b42318)" : tone === "success" ? "var(--rmc-success-fg, #067647)" : "var(--rmc-text-primary)";
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
const rowBorder: CSSProperties = { borderBottom: "1px solid var(--rmc-border-subtle)" };
const muted: CSSProperties = { color: "var(--rmc-text-muted)" };

export default async function Page() {
  const locale = getServerLocale();
  const cat = getCatalog(locale);
  const k = (key: string, p?: Record<string, string | number>) => t(cat, `screen.t06.${key}`, p);
  const snap = await getCompliance();
  const { profile, recordingPolicy, transparency, residency, retention, outbound, dsr, breach, dpia, overrides } = snap;

  const discGaps = new Set(disclosureGaps(transparency));
  const recGaps = new Set(recordingGaps(recordingPolicy));
  const resGaps = new Set(residencyGaps(residency));
  const outGaps = new Set(outboundGaps(outbound));
  const loosen = new Set(loosenOverrides(overrides));
  const invRet = new Set(invalidRetention(retention));
  const dpiaOpen = dpiaPending(dpia);
  const openCount = openWarningCount(snap);

  const channelName = (m: ChannelMode) => k(`channel.${m}`);
  const recConsentName = (m: RecordingConsentModel) => k(`rec_consent.${m}`);
  const consentName = (m: ConsentModel) => k(`consent.${m}`);
  const crossBorderName = (m: CrossBorderMechanism) => k(`cross_border.${m}`);
  const dpiaName = (s: DpiaStatus) => k(`dpia_status.${s}`);
  const dirName = (d: OverrideDirection) => k(`direction.${d}`);
  const regionName = (r: HomeRegion) => k(`region.${r}`);
  const noticeName = (n: DataSubjectNotice) => k(`ds_notice.${n}`);

  const yesNo = (b: boolean) => (b ? k("yes") : k("no"));
  const flagPill = (on: boolean, okLabel?: string, badLabel?: string) => (
    <StatusPill tone={guardFlagTone(on)}>{on ? (okLabel ?? k("yes")) : (badLabel ?? k("no"))}</StatusPill>
  );
  const requiredPill = (required: boolean, satisfied: boolean) => (
    <StatusPill tone={requiredFlagTone(required, satisfied)}>
      {!required ? k("not_required") : satisfied ? k("configured") : k("missing")}
    </StatusPill>
  );
  const days = (n: number, bad: boolean) => (
    <StatusPill tone={bad ? "danger" : "neutral"}>{k("days", { n: formatNumber(locale, n) })}</StatusPill>
  );

  return (
    <section data-screen="T-06">
      <PageHeader title={k("title")} description={k("subtitle")} code="T-06" />

      <div style={{ marginBottom: "var(--rmc-space-4)" }}>
        <Alert tone="info">{k("scope_note")}</Alert>
      </div>

      <p style={{ ...muted, fontSize: "var(--rmc-size-sm)", marginTop: 0 }}>
        {k("as_of", { time: formatDate(locale, new Date(snap.generatedAt), { dateStyle: "medium", timeStyle: "short" }) })}
        {" · "}
        <span>{k("tenant")}: {snap.tenantName}</span>
      </p>

      {/* Disclaimer: mühendislik varsayılanı / counsel doğrulaması (DPIA §12) */}
      <div style={{ margin: "var(--rmc-space-2) 0 var(--rmc-space-3)" }}>
        <Alert tone="warning">{k("counsel_note")}</Alert>
      </div>

      {/* Uyarılar */}
      {loosen.size > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="danger">{k("loosen_alert", { count: formatNumber(locale, loosen.size) })}</Alert>
        </div>
      )}
      {discGaps.size > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="danger">{k("disclosure_alert", { count: formatNumber(locale, discGaps.size) })}</Alert>
        </div>
      )}
      {resGaps.size > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="danger">{k("residency_alert", { count: formatNumber(locale, resGaps.size) })}</Alert>
        </div>
      )}
      {invRet.size > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="danger">{k("retention_alert", { count: formatNumber(locale, invRet.size) })}</Alert>
        </div>
      )}
      {recGaps.size > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="warning">{k("recording_alert", { count: formatNumber(locale, recGaps.size) })}</Alert>
        </div>
      )}
      {outGaps.size > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="warning">{k("outbound_alert", { count: formatNumber(locale, outGaps.size) })}</Alert>
        </div>
      )}
      {dpiaOpen && (
        <div style={{ margin: "var(--rmc-space-2) 0 var(--rmc-space-4)" }}>
          <Alert tone="warning">{k("dpia_alert", { status: dpiaName(dpia.status) })}</Alert>
        </div>
      )}

      {/* Özet */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", marginBottom: "var(--rmc-space-3)" }}>{k("section.summary")}</h2>
      <div style={grid()}>
        <Kpi label={k("kpi.profile")} value={profile.countryProfile} hint={k("kpi.profile_hint", { regime: profile.regime })} />
        <Kpi label={k("kpi.recording")} value={retention.recordingDays > 0 ? k("days", { n: formatNumber(locale, retention.recordingDays) }) : "—"} hint={k("kpi.recording_hint")} />
        <Kpi label={k("kpi.residency")} value={regionName(residency.homeRegion)} hint={k("kpi.residency_hint")} />
        <Kpi label={k("kpi.dpia")} value={dpiaName(dpia.status)} hint={k("kpi.dpia_hint")} tone={dpiaOpen ? "danger" : "success"} />
        <Kpi label={k("kpi.warnings")} value={formatNumber(locale, openCount)} hint={k("kpi.warnings_hint")} tone={openCount > 0 ? "danger" : "success"} />
      </div>

      {/* Compliance Profile */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>
        <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: 0 }}>{k("section.profile")}</h2>
        <Button variant="primary">{k("action.edit_profile")}</Button>
      </div>
      <Card>
        <Table caption={k("profile_caption")}>
          <tbody>
            <tr style={rowBorder}><td style={td}>{k("field.country_profile")}</td><td style={td}><StatusPill tone="info">{profile.countryProfile}</StatusPill></td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.regime")}</td><td style={td}><code>{profile.regime}</code></td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.sector_overlays")}</td><td style={td}>{profile.sectorOverlays.length === 0 ? <span style={muted}>{k("none")}</span> : profile.sectorOverlays.map((s) => <span key={s} style={{ marginInlineEnd: "var(--rmc-space-1)" }}><StatusPill tone="info">{s}</StatusPill></span>)}</td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.lawful_basis")}</td><td style={td}><code>{profile.lawfulBasisDefault}</code></td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.dpa_required")}</td><td style={td}>{flagPill(profile.dpaRequired)}</td></tr>
          </tbody>
        </Table>
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-2)" }}>{k("profile_hint")}</p>

      {/* Kayıt Politikası */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.recording")}</h2>
      <Card>
        <Table caption={k("recording_caption")}>
          <tbody>
            <tr style={rowBorder}><td style={td}>{k("field.channel_mode")}</td><td style={td}><StatusPill tone={channelModeTone(recordingPolicy.channelMode)}>{channelName(recordingPolicy.channelMode)}</StatusPill></td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.rec_consent")}</td><td style={td}><code>{recConsentName(recordingPolicy.recordingConsentModel)}</code></td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.pii_redaction")} <code style={muted}>FR-REC-004</code></td><td style={td}>{recGaps.has("pii_redaction") ? <StatusPill tone="danger">{k("no")}</StatusPill> : flagPill(recordingPolicy.piiRedaction)}</td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.card_otp")} <code style={muted}>FR-REC-005</code></td><td style={td}>{recGaps.has("card_otp") ? <StatusPill tone="danger">{k("no")}</StatusPill> : flagPill(recordingPolicy.cardOtpMasking)}</td></tr>
          </tbody>
        </Table>
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-2)" }}>{k("recording_hint")}</p>

      {/* Şeffaflık & Bildirim */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.transparency")}</h2>
      <Card>
        <Table caption={k("transparency_caption")}>
          <tbody>
            <tr style={rowBorder}><td style={td}>{k("field.ai_disclosure")}</td><td style={td}>{requiredPill(transparency.aiDisclosureRequired, transparency.aiDisclosureConfigured)}</td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.recording_notice")}</td><td style={td}>{requiredPill(transparency.recordingNoticeRequired, transparency.recordingNoticeConfigured)}</td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.no_impersonation")}</td><td style={td}>{flagPill(transparency.noDeceptiveImpersonation)}</td></tr>
          </tbody>
        </Table>
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-2)" }}>{k("transparency_hint")}</p>

      {/* Veri Yerleşimi */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.residency")}</h2>
      <Card>
        <Table caption={k("residency_caption")}>
          <tbody>
            <tr style={rowBorder}><td style={td}>{k("field.home_region")}</td><td style={td}><StatusPill tone="info">{regionName(residency.homeRegion)}</StatusPill></td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.in_region")}</td><td style={td}>{flagPill(residency.inRegionStorageRequired)}</td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.provider_pinning")} <code style={muted}>NFR 10.7</code></td><td style={td}>{resGaps.has("provider_pinning") ? <StatusPill tone="danger">{k("no")}</StatusPill> : flagPill(residency.providerRegionPinning)}</td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.cross_border")}</td><td style={td}><StatusPill tone={resGaps.has("cross_border") ? "danger" : crossBorderTone(residency.crossBorderMechanism)}>{crossBorderName(residency.crossBorderMechanism)}</StatusPill></td></tr>
          </tbody>
        </Table>
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-2)" }}>{k("residency_hint")}</p>

      {/* Saklama */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.retention")}</h2>
      <Card>
        <Table caption={k("retention_caption")}>
          <thead>
            <tr style={rowBorder}>
              <th style={th}>{k("col.data_class")}</th>
              <th style={th}>{k("col.retention")}</th>
            </tr>
          </thead>
          <tbody>
            <tr style={rowBorder}><td style={td}>{k("data_class.recording")}</td><td style={td}>{days(retention.recordingDays, invRet.has("recording"))}</td></tr>
            <tr style={rowBorder}><td style={td}>{k("data_class.transcript")}</td><td style={td}>{days(retention.transcriptDays, invRet.has("transcript"))}</td></tr>
            <tr style={rowBorder}><td style={td}>{k("data_class.audit")} <code style={muted}>{k("badge.worm")}</code></td><td style={td}>{days(retention.auditDays, invRet.has("audit"))}</td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.legal_hold")} <code style={muted}>FR-REC-007</code></td><td style={td}>{retention.legalHoldSupported ? <StatusPill tone="success">{k("legal_hold_active", { n: formatNumber(locale, retention.legalHoldActive) })}</StatusPill> : <StatusPill tone="neutral">{k("no")}</StatusPill>}</td></tr>
          </tbody>
        </Table>
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-2)" }}>{k("retention_hint")}</p>

      {/* Outbound / İYS / DNC */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.outbound")}</h2>
      <Card>
        <Table caption={k("outbound_caption")}>
          <tbody>
            <tr style={rowBorder}><td style={td}>{k("field.consent_model")} <code style={muted}>FR-OUT-003</code></td><td style={td}><StatusPill tone={consentModelTone(outbound.consentModel)}>{consentName(outbound.consentModel)}</StatusPill></td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.consent_registry")}</td><td style={td}>{outGaps.has("consent_registry") ? <StatusPill tone="danger">{k("undefined_label")}</StatusPill> : <StatusPill tone="success"><code>{outbound.consentRegistry}</code></StatusPill>}</td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.dnc_lists")} <code style={muted}>FR-OUT-006</code></td><td style={td}>{outGaps.has("dnc") ? <StatusPill tone="danger">{k("undefined_label")}</StatusPill> : outbound.dncLists.map((d) => <span key={d} style={{ marginInlineEnd: "var(--rmc-space-1)" }}><code>{d}</code></span>)}</td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.calling_hours")} <code style={muted}>FR-OUT-004</code></td><td style={td}><code>{outbound.callingHoursLocal}</code></td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.cli_required")}</td><td style={td}>{flagPill(outbound.cliPresentationRequired)}</td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.b2b_exemption")}</td><td style={td}>{yesNo(outbound.b2bExemption)}</td></tr>
          </tbody>
        </Table>
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-2)" }}>{k("outbound_hint")}</p>

      {/* DSR + İhlal Bildirimi */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.dsr")}</h2>
      <Card>
        <Table caption={k("dsr_caption")}>
          <tbody>
            <tr style={rowBorder}><td style={td}>{k("field.access_sla")}</td><td style={td}>{k("days", { n: formatNumber(locale, dsr.accessSlaDays) })}</td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.erasure_sla")} <code style={muted}>FR-REC-010</code></td><td style={td}>{k("days", { n: formatNumber(locale, dsr.erasureSlaDays) })}</td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.rectification")}</td><td style={td}>{flagPill(dsr.rectificationSupported)}</td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.portability")}</td><td style={td}>{flagPill(dsr.portabilitySupported)}</td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.breach_authority")}</td><td style={td}><code>{breach.authority}</code></td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.breach_deadline")}</td><td style={td}>{k("hours", { n: formatNumber(locale, breach.authorityDeadlineHours) })}</td></tr>
            <tr style={rowBorder}><td style={td}>{k("field.ds_notice")}</td><td style={td}><code>{noticeName(breach.dataSubjectNotice)}</code></td></tr>
          </tbody>
        </Table>
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-2)" }}>{k("dsr_hint")}</p>

      {/* Tenant Override'ları */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.overrides")}</h2>
      <Card>
        {overrides.length === 0 ? (
          <EmptyState message={k("no_overrides")} />
        ) : (
          <Table caption={k("overrides_caption")}>
            <thead>
              <tr style={rowBorder}>
                <th style={th}>{k("col.parameter")}</th>
                <th style={th}>{k("col.baseline")}</th>
                <th style={th}>{k("col.value")}</th>
                <th style={th}>{k("col.direction")}</th>
              </tr>
            </thead>
            <tbody>
              {overrides.map((o) => (
                <tr key={o.id} style={rowBorder}>
                  <td style={td}><code>{o.key}</code> <code style={muted}>{o.id}</code></td>
                  <td style={td}><code style={muted}>{o.baseline}</code></td>
                  <td style={td}><code>{o.value}</code></td>
                  <td style={td}><StatusPill tone={overrideDirectionTone(o.direction)}>{dirName(o.direction)}{loosen.has(o.id) ? ` · ${k("badge.violation")}` : ""}</StatusPill></td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>{k("overrides_hint")}</p>
    </section>
  );
}
