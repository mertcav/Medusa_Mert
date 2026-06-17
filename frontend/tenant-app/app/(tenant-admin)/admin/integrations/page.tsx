// WBS 13.3.5 — L1 ekranı T-05 "Entegrasyon, Tool & API Key/Webhook" (gerçek içerik; 13.1.1 iskeletinin yerini alır).
//
// İÇERİK (BRD §17.4 / FR-TOOL-001..012 · API.md §7 [API key/webhook] · §10 [webhook event]): tenant'ın kurumsal
// sistem ENTEGRASYONLARI (CRM/ERP/ticketing), bunların üstüne tanımlı TOOL'lar (REST/SOAP/GraphQL/webhook),
// programatik erişim için API ANAHTARLARI (S4 Public Developer API) ve giden olay WEBHOOK tanımları.
// TENANT-SCOPE (FR-TEN-002): yalnız oturum açan tenant'ın KENDİ konfigürasyonu; scope middleware (13.1.2) +
// RLS (§13) ile sabitlenir. HİJYEN (BRD §17.7) + GÜVENLİK (NFR 10.6): ham son-müşteri içeriği (çağrı kaydı/
// transkript/PII) ve SIR (API key secret/webhook signing_secret/entegrasyon credential) gömülmez — veri katmanı
// `assertNoPii` ile garanti eder. RBAC (BRD §17.6): tenant_owner=Yönet · tenant_admin=Yönet ·
// security_compliance_officer=Görüntüle · billing_viewer=— · api_developer=Yönet. UI yalnız görsel kapı; nihai
// yetki backend'de (12.2.x, SAD §14.4.1 A8). Tüm kullanıcı-görünür metin i18n katalogundan (t()).
import type { CSSProperties } from "react";
import { getServerLocale } from "@/lib/i18n/server";
import { getCatalog, t, formatNumber, formatDate } from "@/lib/i18n";
import { PageHeader, Card, StatusPill, Alert, Table, Button, EmptyState } from "@/lib/ui/components";
import {
  getIntegrations,
  countIntegrationState,
  invalidIntegrationRefs,
  writeToolsWithoutConfirmation,
  toolsWithoutSchema,
  insecureWebhookUrls,
  failingWebhooks,
  apiKeysByStatus,
  integrationStateTone,
  integrationTypeTone,
  protocolTone,
  toolAccessTone,
  apiKeyStatusTone,
  webhookStatusTone,
  type ConnState,
  type IntegrationType,
  type AuthMethod,
  type ToolProtocol,
  type ToolAccess,
  type ApiKeyStatus,
  type WebhookStatus,
} from "@/lib/tenant/integrations";

function Kpi({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card>
      <div style={{ color: "var(--rmc-text-muted)", fontSize: "var(--rmc-size-sm)" }}>{label}</div>
      <div style={{ fontSize: "var(--rmc-size-2xl)", fontWeight: 700, color: "var(--rmc-text-primary)" }}>{value}</div>
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
  const k = (key: string, p?: Record<string, string | number>) => t(cat, `screen.t05.${key}`, p);
  const snap = await getIntegrations();
  const { integrations, tools, apiKeys, webhooks } = snap;

  const byState = countIntegrationState(integrations);
  const invalidRef = new Set(invalidIntegrationRefs(tools, integrations));
  const writeNoConfirm = new Set(writeToolsWithoutConfirmation(tools));
  const noSchema = new Set(toolsWithoutSchema(tools));
  const insecure = new Set(insecureWebhookUrls(webhooks));
  const failing = new Set(failingWebhooks(webhooks));
  const activeKeys = apiKeysByStatus(apiKeys, "active");

  const integrationTypeName = (t: IntegrationType) => k(`integration_type.${t}`);
  const authName = (a: AuthMethod) => k(`auth.${a}`);
  const stateName = (s: ConnState) => k(`conn.${s}`);
  const protocolName = (p: ToolProtocol) => k(`protocol.${p}`);
  const accessName = (a: ToolAccess) => k(`access.${a}`);
  const apiKeyStatusName = (s: ApiKeyStatus) => k(`key_status.${s}`);
  const webhookStatusName = (s: WebhookStatus) => k(`webhook_status.${s}`);

  const integrationByKey = new Map(integrations.map((i) => [i.id, i] as const));
  const integrationLabel = (id: string) => (integrationByKey.has(id) ? integrationByKey.get(id)!.name : `${id} (?)`);
  const dash = <span style={muted}>—</span>;
  const fmtTime = (iso: string | null) => (iso ? formatDate(locale, new Date(iso), { dateStyle: "short", timeStyle: "short" }) : k("never"));

  return (
    <section data-screen="T-05">
      <PageHeader title={k("title")} description={k("subtitle")} code="T-05" />

      <div style={{ marginBottom: "var(--rmc-space-4)" }}>
        <Alert tone="info">{k("scope_note")}</Alert>
      </div>

      <p style={{ ...muted, fontSize: "var(--rmc-size-sm)", marginTop: 0 }}>
        {k("as_of", { time: formatDate(locale, new Date(snap.generatedAt), { dateStyle: "medium", timeStyle: "short" }) })}
        {" · "}
        <span>{k("tenant")}: {snap.tenantName}</span>
      </p>

      {invalidRef.size > 0 && (
        <div style={{ margin: "var(--rmc-space-3) 0 var(--rmc-space-2)" }}>
          <Alert tone="danger">{k("invalid_ref_alert", { count: formatNumber(locale, invalidRef.size) })}</Alert>
        </div>
      )}
      {insecure.size > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="danger">{k("insecure_webhook_alert", { count: formatNumber(locale, insecure.size) })}</Alert>
        </div>
      )}
      {writeNoConfirm.size > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="warning">{k("write_confirm_alert", { count: formatNumber(locale, writeNoConfirm.size) })}</Alert>
        </div>
      )}
      {noSchema.size > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="warning">{k("no_schema_alert", { count: formatNumber(locale, noSchema.size) })}</Alert>
        </div>
      )}
      {failing.size > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0 var(--rmc-space-4)" }}>
          <Alert tone="warning">{k("failing_webhook_alert", { count: formatNumber(locale, failing.size) })}</Alert>
        </div>
      )}

      {/* Özet */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", marginBottom: "var(--rmc-space-3)" }}>{k("section.summary")}</h2>
      <div style={grid()}>
        <Kpi label={k("kpi.integrations")} value={formatNumber(locale, integrations.length)} hint={k("kpi.integrations_hint", { connected: formatNumber(locale, byState.connected) })} />
        <Kpi label={k("kpi.tools")} value={formatNumber(locale, tools.length)} hint={k("kpi.tools_hint")} />
        <Kpi label={k("kpi.api_keys")} value={formatNumber(locale, apiKeys.length)} hint={k("kpi.api_keys_hint", { active: formatNumber(locale, activeKeys.length) })} />
        <Kpi label={k("kpi.webhooks")} value={formatNumber(locale, webhooks.length)} hint={k("kpi.webhooks_hint")} />
      </div>

      {/* Entegrasyonlar */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>
        <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: 0 }}>{k("section.integrations")}</h2>
        <Button variant="primary">{k("action.new_integration")}</Button>
      </div>
      <Card>
        {integrations.length === 0 ? (
          <EmptyState message={k("no_integrations")} />
        ) : (
          <Table caption={k("integrations_caption")}>
            <thead>
              <tr style={rowBorder}>
                <th style={th}>{k("col.integration")}</th>
                <th style={th}>{k("col.type")}</th>
                <th style={th}>{k("col.auth")}</th>
                <th style={th}>{k("col.region")}</th>
                <th style={th}>{k("col.last_sync")}</th>
                <th style={th}>{k("col.state")}</th>
              </tr>
            </thead>
            <tbody>
              {integrations.map((i) => (
                <tr key={i.id} style={rowBorder}>
                  <td style={td}>{i.name} <code style={muted}>{i.id}</code></td>
                  <td style={td}><StatusPill tone={integrationTypeTone(i.type)}>{integrationTypeName(i.type)}</StatusPill></td>
                  <td style={td}>{authName(i.authMethod)}</td>
                  <td style={td}><code>{i.region}</code></td>
                  <td style={td}>{fmtTime(i.lastSyncAt)}</td>
                  <td style={td}><StatusPill tone={integrationStateTone(i.state)}>{stateName(i.state)}</StatusPill></td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-2)" }}>{k("integrations_hint")}</p>

      {/* Tool'lar */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>
        <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: 0 }}>{k("section.tools")}</h2>
        <Button variant="primary">{k("action.new_tool")}</Button>
      </div>
      <Card>
        {tools.length === 0 ? (
          <EmptyState message={k("no_tools")} />
        ) : (
          <Table caption={k("tools_caption")}>
            <thead>
              <tr style={rowBorder}>
                <th style={th}>{k("col.tool")}</th>
                <th style={th}>{k("col.protocol")}</th>
                <th style={th}>{k("col.access")}</th>
                <th style={th}>{k("col.schema")}</th>
                <th style={th}>{k("col.confirm")}</th>
                <th style={th}>{k("col.integration")}</th>
              </tr>
            </thead>
            <tbody>
              {tools.map((tl) => (
                <tr key={tl.id} style={rowBorder}>
                  <td style={td}>{tl.name} <code style={muted}>{tl.id}</code></td>
                  <td style={td}><StatusPill tone={protocolTone(tl.protocol)}>{protocolName(tl.protocol)}</StatusPill></td>
                  <td style={td}><StatusPill tone={toolAccessTone(tl.access)}>{accessName(tl.access)}</StatusPill></td>
                  <td style={td}>
                    {tl.schemaValidated ? <StatusPill tone="success">{k("yes")}</StatusPill> : <StatusPill tone={noSchema.has(tl.id) ? "warning" : "neutral"}>{k("no")}</StatusPill>}
                  </td>
                  <td style={td}>
                    {tl.access === "write" && !tl.confirmRequired ? (
                      <StatusPill tone="danger">{k("no")}</StatusPill>
                    ) : tl.confirmRequired ? (
                      <StatusPill tone="success">{k("yes")}</StatusPill>
                    ) : (
                      <span style={muted}>{k("no")}</span>
                    )}
                  </td>
                  <td style={td}>
                    {tl.integrationRef ? (
                      <StatusPill tone={invalidRef.has(tl.id) ? "danger" : "neutral"}>{integrationLabel(tl.integrationRef)}</StatusPill>
                    ) : (
                      <StatusPill tone="info">{k("inline_label")}</StatusPill>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-2)" }}>{k("tools_hint")}</p>

      {/* API Anahtarları */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>
        <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: 0 }}>{k("section.api_keys")}</h2>
        <Button variant="primary">{k("action.new_api_key")}</Button>
      </div>
      <Card>
        {apiKeys.length === 0 ? (
          <EmptyState message={k("no_api_keys")} />
        ) : (
          <Table caption={k("api_keys_caption")}>
            <thead>
              <tr style={rowBorder}>
                <th style={th}>{k("col.key")}</th>
                <th style={th}>{k("col.scopes")}</th>
                <th style={th}>{k("col.last_used")}</th>
                <th style={th}>{k("col.status")}</th>
              </tr>
            </thead>
            <tbody>
              {apiKeys.map((key) => (
                <tr key={key.id} style={rowBorder}>
                  <td style={td}>{key.name} <code style={muted}>{key.id}</code></td>
                  <td style={td}>
                    {key.scopes.length === 0 ? dash : key.scopes.map((sc) => (
                      <span key={sc} style={{ marginInlineEnd: "var(--rmc-space-1)" }}><code>{sc}</code></span>
                    ))}
                  </td>
                  <td style={td}>{fmtTime(key.lastUsedAt)}</td>
                  <td style={td}><StatusPill tone={apiKeyStatusTone(key.status)}>{apiKeyStatusName(key.status)}</StatusPill></td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-2)" }}>{k("api_keys_hint")}</p>

      {/* Webhook'lar */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>
        <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: 0 }}>{k("section.webhooks")}</h2>
        <Button variant="secondary">{k("action.new_webhook")}</Button>
      </div>
      <Card>
        {webhooks.length === 0 ? (
          <EmptyState message={k("no_webhooks")} />
        ) : (
          <Table caption={k("webhooks_caption")}>
            <thead>
              <tr style={rowBorder}>
                <th style={th}>{k("col.url")}</th>
                <th style={th}>{k("col.events")}</th>
                <th style={th}>{k("col.last_delivery")}</th>
                <th style={th}>{k("col.status")}</th>
              </tr>
            </thead>
            <tbody>
              {webhooks.map((w) => (
                <tr key={w.id} style={rowBorder}>
                  <td style={td}>
                    <code>{w.url}</code>
                    {insecure.has(w.id) && <span style={{ marginInlineStart: "var(--rmc-space-1)" }}><StatusPill tone="danger">{k("badge.insecure")}</StatusPill></span>}
                  </td>
                  <td style={td}>
                    {w.events.length === 0 ? dash : w.events.map((ev) => (
                      <span key={ev} style={{ marginInlineEnd: "var(--rmc-space-1)" }}><code>{ev}</code></span>
                    ))}
                  </td>
                  <td style={td}>
                    {fmtTime(w.lastDeliveryAt)}
                    {w.lastDeliveryOk === false && <span style={{ marginInlineStart: "var(--rmc-space-1)" }}><StatusPill tone="danger">{k("badge.delivery_failed")}</StatusPill></span>}
                  </td>
                  <td style={td}><StatusPill tone={webhookStatusTone(w.status)}>{webhookStatusName(w.status)}</StatusPill></td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>{k("webhooks_hint")}</p>
    </section>
  );
}
