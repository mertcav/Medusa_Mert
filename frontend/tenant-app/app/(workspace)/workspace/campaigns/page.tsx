// WBS 13.4.10 — L2 ekranı A-10 "Outbound Kampanya Yönetimi" (gerçek içerik; 13.1.1 iskeletinin yerini alır).
//
// İÇERİK (BRD §17.5 A-10 "Outbound Kampanya Yönetimi" — "Liste, zamanlama, consent/suppression, disposition"):
// bir tenant'ın OUTBOUND KAMPANYALARININ envanteri + uyum/disposition sağlığı. KAMPANYA ÖZETİ (kampanya · kontak ·
// aranabilir · DNC · consent eksik · kapasite · disposition · açık dikkat), KAMPANYALAR tablosu (kampanya · agent ·
// durum FR-OUT-010 · kaynak FR-OUT-001/002 · kontak · deneme FR-OUT-005 · script FR-OUT-009 · A/B FR-OUT-012),
// UYUM & SUPPRESSION SAĞLIĞI tablosu (consent FR-OUT-003 · suppression FR-OUT-006 · arama saati FR-OUT-004 ·
// kapasite FR-OUT-007), DURUM DAĞILIMI (DB §5.4) ve DISPOSITION DAĞILIMI (FR-OUT-008/011). ÇEKİRDEK HİJYEN:
// aranacak ham numara / müşteri PII / contact attributes / CRM kaydı / script gövdesi gösterilmez — yalnız AGREGAT
// SAYI/BAYRAK; liste yükleme/CRM çekme/dialer derin aksiyondur (API dilimi). TENANT-SCOPE (FR-TEN-002): yalnız
// oturum açan tenant (middleware 13.1.2 + RLS). GÜVENLİK (NFR 10.6): sır + script gövdesi konmaz. RBAC (BRD §17.6):
// operations_manager=Yönet · conversation_designer=Düzenle · qa_analyst=Görüntüle · human_agent=—. UI yalnız görsel
// kapı; oluştur/durdur/liste yükle nihai yetki + işlem backend'de (Campaign Manager + Consent Engine SAD §19.1).
// Tüm metin i18n'den (t()).
import type { CSSProperties } from "react";
import { getServerLocale } from "@/lib/i18n/server";
import { getCatalog, t, formatNumber, formatDate } from "@/lib/i18n";
import { PageHeader, Card, StatusPill, Alert, Table, Button, EmptyState } from "@/lib/ui/components";
import {
  getOutboundCampaignView,
  sortedCampaigns,
  countByStatus,
  runningCampaigns,
  activeCampaigns,
  abTestCampaigns,
  aggregateContacts,
  reachableContacts,
  aggregateDispositions,
  totalDispositions,
  consentCheckDisabled,
  suppressionDisabled,
  callingHoursMissing,
  capacityExceeded,
  missingScriptVersion,
  capacityUtilPct,
  openAttentionCount,
  statusTone,
  dispositionTone,
  listSourceTone,
  CAMPAIGN_STATUS_ORDER,
  DISPOSITION_ORDER,
  type Campaign,
  type CampaignStatus,
  type DispositionType,
  type ListSource,
} from "@/lib/tenant/campaigns";

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
  const k = (key: string, p?: Record<string, string | number>) => t(cat, `screen.a10.${key}`, p);
  const view = await getOutboundCampaignView();

  const campaigns = sortedCampaigns(view.campaigns);
  const statusCounts = countByStatus(view.campaigns);
  const running = runningCampaigns(view.campaigns);
  const active = activeCampaigns(view.campaigns);
  const abTests = abTestCampaigns(view.campaigns);
  const contacts = aggregateContacts(view.campaigns);
  const reachable = reachableContacts(view.campaigns);
  const dispoCounts = aggregateDispositions(view.campaigns);
  const dispoTotal = totalDispositions(view.campaigns);
  const consentOff = consentCheckDisabled(view.campaigns);
  const suppressionOff = suppressionDisabled(view.campaigns);
  const hoursMissing = callingHoursMissing(view.campaigns);
  const capExceeded = capacityExceeded(view.campaigns);
  const scriptMissing = missingScriptVersion(view.campaigns);
  const capUtil = capacityUtilPct(view.campaigns);
  const attention = openAttentionCount(view.campaigns);

  const statusName = (s: CampaignStatus) => k(`status.${s}`);
  const dispositionName = (d: DispositionType) => k(`disposition.${d}`);
  const sourceName = (s: ListSource) => k(`source.${s}`);

  const totalCampaigns = view.campaigns.length;
  const presentStatuses = CAMPAIGN_STATUS_ORDER.filter((s) => statusCounts[s] > 0);

  const campaignRow = (c: Campaign) => (
    <tr key={c.campaignRef} style={rowBorder}>
      <td style={td}>
        <strong>{c.name}</strong> <code style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{c.campaignRef}</code>
        {c.abTest && (
          <>
            {" "}
            <StatusPill tone="info">{k("ab_badge")}</StatusPill>
          </>
        )}
      </td>
      <td style={td}>
        <strong>{c.agentName}</strong> <code style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{c.agentRef}</code>
      </td>
      <td style={td}><StatusPill tone={statusTone(c.status)}>{statusName(c.status)}</StatusPill></td>
      <td style={td}><StatusPill tone={listSourceTone(c.listSource)}>{sourceName(c.listSource)}</StatusPill></td>
      <td style={tdEnd}>{formatNumber(locale, c.contacts.total)}</td>
      <td style={tdEnd}>{k("attempts_fmt", { max: formatNumber(locale, c.maxAttempts), retry: formatNumber(locale, c.retryIntervalMinutes) })}</td>
      <td style={td}>{c.scriptVersion.trim() === "" ? <StatusPill tone="warning">{k("script_missing")}</StatusPill> : <code style={{ fontSize: "var(--rmc-size-xs)" }}>{c.scriptVersion}</code>}</td>
    </tr>
  );

  const complianceRow = (c: Campaign) => {
    const overCap = c.capacityCap > c.capacityAvailable;
    return (
      <tr key={c.campaignRef} style={rowBorder}>
        <td style={td}>
          <strong>{c.name}</strong> <code style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{c.campaignRef}</code>
        </td>
        <td style={td}>{c.consentCheckEnabled ? <StatusPill tone="success">{k("on")}</StatusPill> : <StatusPill tone="danger">{k("off")}</StatusPill>}</td>
        <td style={td}>{c.suppressionEnabled ? <StatusPill tone="success">{k("on")}</StatusPill> : <StatusPill tone="danger">{k("off")}</StatusPill>}</td>
        <td style={td}>{c.callingHoursConfigured ? <StatusPill tone="success">{k("configured")}</StatusPill> : <StatusPill tone={c.status === "draft" || c.status === "stopped" || c.status === "completed" ? "warning" : "danger"}>{k("unconfigured")}</StatusPill>}</td>
        <td style={tdEnd}>
          <span style={overCap ? { color: "var(--rmc-danger-fg, #b42318)" } : undefined}>{k("ratio", { a: formatNumber(locale, c.capacityCap), b: formatNumber(locale, c.capacityAvailable) })}</span>
          {overCap && <span style={{ color: "var(--rmc-danger-fg, #b42318)", fontSize: "var(--rmc-size-xs)" }}> {k("over_cap")}</span>}
        </td>
      </tr>
    );
  };

  return (
    <section data-screen="A-10">
      <PageHeader title={k("title")} description={k("subtitle")} code="A-10" />

      <div style={{ marginBottom: "var(--rmc-space-4)" }}>
        <Alert tone="info">{k("scope_note")}</Alert>
      </div>

      <p style={{ ...muted, fontSize: "var(--rmc-size-sm)", marginTop: 0 }}>
        {k("as_of", { time: formatDate(locale, new Date(view.generatedAt), { dateStyle: "medium", timeStyle: "short" }) })}
        {" · "}
        <span>{k("tenant")}: {view.tenantName}</span>
        {" · "}
        <span>{k("campaigns_label")}: {formatNumber(locale, totalCampaigns)}</span>
      </p>

      {/* Uyarılar */}
      {consentOff.length > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="danger">{k("alert.consent_disabled", { count: formatNumber(locale, consentOff.length) })}</Alert>
        </div>
      )}
      {suppressionOff.length > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="danger">{k("alert.suppression_disabled", { count: formatNumber(locale, suppressionOff.length) })}</Alert>
        </div>
      )}
      {hoursMissing.length > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="danger">{k("alert.calling_hours_missing", { count: formatNumber(locale, hoursMissing.length) })}</Alert>
        </div>
      )}
      {capExceeded.length > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="danger">{k("alert.capacity_exceeded", { count: formatNumber(locale, capExceeded.length) })}</Alert>
        </div>
      )}
      {scriptMissing.length > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="warning">{k("alert.missing_script", { count: formatNumber(locale, scriptMissing.length) })}</Alert>
        </div>
      )}

      {/* Kampanya özeti */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", margin: "var(--rmc-space-2) 0 var(--rmc-space-3)" }}>
        <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: 0 }}>{k("section.summary")}</h2>
        <Button variant="primary">{k("action.create")}</Button>
      </div>
      <div style={grid()}>
        <Kpi label={k("kpi.campaigns")} value={k("ratio", { a: formatNumber(locale, running.length), b: formatNumber(locale, totalCampaigns) })} hint={k("kpi.campaigns_hint", { active: formatNumber(locale, active.length) })} />
        <Kpi label={k("kpi.contacts")} value={formatNumber(locale, contacts.total)} hint={k("kpi.contacts_hint", { reachable: formatNumber(locale, reachable) })} />
        <Kpi label={k("kpi.dnc")} value={formatNumber(locale, contacts.dnc)} hint={k("kpi.dnc_hint")} tone={contacts.dnc > 0 ? "warning" : "success"} />
        <Kpi label={k("kpi.consent_missing")} value={formatNumber(locale, contacts.consentMissing)} hint={k("kpi.consent_missing_hint")} tone={contacts.consentMissing > 0 ? "warning" : "success"} />
        <Kpi label={k("kpi.capacity")} value={k("percent", { n: formatNumber(locale, capUtil) })} hint={k("kpi.capacity_hint")} tone={capExceeded.length > 0 ? "warning" : undefined} />
        <Kpi label={k("kpi.dispositions")} value={formatNumber(locale, dispoTotal)} hint={k("kpi.dispositions_hint", { answered: formatNumber(locale, dispoCounts.answered) })} />
        <Kpi label={k("kpi.exhausted")} value={formatNumber(locale, contacts.exhausted)} hint={k("kpi.exhausted_hint")} />
        <Kpi label={k("kpi.attention")} value={formatNumber(locale, attention)} hint={k("kpi.attention_hint")} tone={attention > 0 ? "warning" : "success"} />
      </div>

      {/* Kampanyalar (liste · zamanlama · script) */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>
        <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: 0 }}>{k("section.campaigns")}</h2>
        <Button variant="secondary">{k("action.stop")}</Button>
      </div>
      <Card>
        {campaigns.length === 0 ? (
          <EmptyState message={k("no_campaigns")} />
        ) : (
          <Table caption={k("campaigns_caption")}>
            <thead>
              <tr style={rowBorder}>
                <th style={th}>{k("col.campaign")}</th>
                <th style={th}>{k("col.agent")}</th>
                <th style={th}>{k("col.status")}</th>
                <th style={th}>{k("col.source")}</th>
                <th style={thEnd}>{k("col.contacts")}</th>
                <th style={thEnd}>{k("col.attempts")}</th>
                <th style={th}>{k("col.script")}</th>
              </tr>
            </thead>
            <tbody>{campaigns.map(campaignRow)}</tbody>
          </Table>
        )}
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>{k("campaigns_hint")}</p>

      {/* Uyum & suppression sağlığı (FR-OUT-003/004/006/007) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.compliance")}</h2>
      <Card>
        {campaigns.length === 0 ? (
          <EmptyState message={k("no_campaigns")} />
        ) : (
          <Table caption={k("compliance_caption")}>
            <thead>
              <tr style={rowBorder}>
                <th style={th}>{k("col.campaign")}</th>
                <th style={th}>{k("col.consent")}</th>
                <th style={th}>{k("col.suppression")}</th>
                <th style={th}>{k("col.calling_hours")}</th>
                <th style={thEnd}>{k("col.capacity")}</th>
              </tr>
            </thead>
            <tbody>{campaigns.map(complianceRow)}</tbody>
          </Table>
        )}
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>{k("compliance_hint")}</p>

      {/* Durum dağılımı (DB §5.4; FR-OUT-010) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.status")}</h2>
      <Card>
        <Table caption={k("status_caption")}>
          <thead>
            <tr style={rowBorder}>
              <th style={th}>{k("col.status")}</th>
              <th style={thEnd}>{k("col.count")}</th>
              <th style={thEnd}>{k("col.share")}</th>
            </tr>
          </thead>
          <tbody>
            {presentStatuses.map((s) => (
              <tr key={s} style={rowBorder}>
                <td style={td}><StatusPill tone={statusTone(s)}>{statusName(s)}</StatusPill></td>
                <td style={tdEnd}>{formatNumber(locale, statusCounts[s])}</td>
                <td style={tdEnd}>{k("percent", { n: formatNumber(locale, totalCampaigns > 0 ? Math.round((statusCounts[s] / totalCampaigns) * 100) : 0) })}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>

      {/* Disposition dağılımı (FR-OUT-008/011) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.dispositions")}</h2>
      <Card>
        {dispoTotal === 0 ? (
          <EmptyState message={k("no_dispositions")} />
        ) : (
          <Table caption={k("dispositions_caption")}>
            <thead>
              <tr style={rowBorder}>
                <th style={th}>{k("col.disposition")}</th>
                <th style={thEnd}>{k("col.count")}</th>
                <th style={thEnd}>{k("col.share")}</th>
              </tr>
            </thead>
            <tbody>
              {DISPOSITION_ORDER.map((d) => (
                <tr key={d} style={rowBorder}>
                  <td style={td}><StatusPill tone={dispositionTone(d)}>{dispositionName(d)}</StatusPill></td>
                  <td style={tdEnd}>{formatNumber(locale, dispoCounts[d])}</td>
                  <td style={tdEnd}>{k("percent", { n: formatNumber(locale, dispoTotal > 0 ? Math.round((dispoCounts[d] / dispoTotal) * 100) : 0) })}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>{k("dispositions_hint")}</p>
    </section>
  );
}
