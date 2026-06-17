// WBS 13.3.3 — L1 ekranı T-03 "Kullanıcı & Rol Yönetimi (RBAC/SSO/SCIM)" (gerçek içerik; 13.1.1 iskeletinin
// yerini alır).
//
// İÇERİK (BRD §17.4 / FR-IAM-001/002/007/011): tenant İÇİ RBAC (kullanıcı–rol atamaları, immutable bundle +
// scope filtresi), SSO (SAML 2.0 / OIDC) ve SCIM provisioning ayarları.
// TENANT-SCOPE (FR-TEN-002): yalnız oturum açan tenant'ın KENDİ kullanıcı/rolleri; scope middleware (13.1.2) +
// RLS (§13) ile sabitlenir. HİJYEN (BRD §17.7 ruhu): yalnız kimlik + RBAC/SSO/SCIM konfigürasyon metadatası; ham
// son-müşteri içeriği (çağrı kaydı/transkript/PII) ve SSO/SCIM sırrı gömülmez — veri katmanı `assertNoPii` ile
// garanti eder. RBAC (BRD §17.6): tenant_owner=Yönet · tenant_admin=Yönet · security_compliance_officer=Görüntüle
// · billing_viewer=— · api_developer=—. UI yalnız görsel kapı; nihai yetki backend'de (12.2.x, SAD §14.4.1 A8).
// Tüm kullanıcı-görünür metin i18n katalogundan (t()).
import type { CSSProperties, ReactNode } from "react";
import { getServerLocale } from "@/lib/i18n/server";
import { getCatalog, t, formatNumber, formatDate } from "@/lib/i18n";
import { PageHeader, Card, StatusPill, Alert, Table, Button, EmptyState } from "@/lib/ui/components";
import {
  getUserRoles,
  countUserStatus,
  usersForRole,
  scopedAssignmentCount,
  usersMissingMfa,
  invalidRoleRefs,
  userStatusTone,
  sourceTone,
  connStateTone,
  roleTierTone,
  mfaTone,
  type UserStatus,
  type UserSource,
  type RoleTier,
  type ConnState,
  type SsoProtocol,
} from "@/lib/tenant/users";

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
const thEnd: CSSProperties = { padding: "var(--rmc-space-2)", textAlign: "end" };
const td: CSSProperties = { padding: "var(--rmc-space-2)" };
const tdEnd: CSSProperties = { padding: "var(--rmc-space-2)", textAlign: "end" };
const rowBorder: CSSProperties = { borderBottom: "1px solid var(--rmc-border-subtle)" };

function KvRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: "var(--rmc-space-3)", padding: "var(--rmc-space-2) 0", borderBottom: "1px solid var(--rmc-border-subtle)" }}>
      <span style={{ color: "var(--rmc-text-muted)", fontSize: "var(--rmc-size-sm)" }}>{label}</span>
      <span style={{ textAlign: "end" }}>{children}</span>
    </div>
  );
}

export default async function Page() {
  const locale = getServerLocale();
  const cat = getCatalog(locale);
  const k = (key: string, p?: Record<string, string | number>) => t(cat, `screen.t03.${key}`, p);
  const snap = await getUserRoles();
  const { users, roles, sso, scim } = snap;

  const byStatus = countUserStatus(users);
  const scoped = scopedAssignmentCount(users);
  const missingMfa = usersMissingMfa(users);
  const invalid = new Set(invalidRoleRefs(users, roles));

  const yesNo = (b: boolean) => (b ? k("yes") : k("no"));
  const statusName = (s: UserStatus) => k(`status_label.${s}`);
  const sourceName = (s: UserSource) => k(`source.${s}`);
  const tierName = (tr: RoleTier) => k(`tier.${tr}`);
  const connName = (s: ConnState) => k(`conn.${s}`);
  const protocolName = (p: SsoProtocol) => k(`protocol.${p}`);
  const roleByKey = new Map(roles.map((r) => [r.key, r] as const));
  const roleLabel = (key: string) => (roleByKey.has(key) ? key : `${key} (?)`);

  return (
    <section data-screen="T-03">
      <PageHeader title={k("title")} description={k("subtitle")} code="T-03" />

      <div style={{ marginBottom: "var(--rmc-space-4)" }}>
        <Alert tone="info">{k("scope_note")}</Alert>
      </div>

      <p style={{ color: "var(--rmc-text-muted)", fontSize: "var(--rmc-size-sm)", marginTop: 0 }}>
        {k("as_of", { time: formatDate(locale, new Date(snap.generatedAt), { dateStyle: "medium", timeStyle: "short" }) })}
        {" · "}
        <span>{k("tenant")}: {snap.tenantName}</span>
      </p>

      {missingMfa.length > 0 && (
        <div style={{ margin: "var(--rmc-space-3) 0 var(--rmc-space-2)" }}>
          <Alert tone="warning">{k("mfa_alert", { count: formatNumber(locale, missingMfa.length) })}</Alert>
        </div>
      )}
      {invalid.size > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0 var(--rmc-space-4)" }}>
          <Alert tone="danger">{k("invalid_alert", { count: formatNumber(locale, invalid.size) })}</Alert>
        </div>
      )}

      {/* Özet */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", marginBottom: "var(--rmc-space-3)" }}>{k("section.summary")}</h2>
      <div style={grid()}>
        <Kpi label={k("kpi.users")} value={formatNumber(locale, users.length)} />
        <Kpi label={k("kpi.active_users")} value={formatNumber(locale, byStatus.active)} hint={k("kpi.active_users_hint", { total: formatNumber(locale, users.length) })} />
        <Kpi label={k("kpi.roles")} value={formatNumber(locale, roles.length)} hint={k("kpi.roles_hint")} />
        <Kpi label={k("kpi.scoped")} value={formatNumber(locale, scoped)} hint={k("kpi.scoped_hint")} />
      </div>

      {/* Kullanıcılar */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>
        <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: 0 }}>{k("section.users")}</h2>
        <Button variant="primary">{k("action.new_user")}</Button>
      </div>
      <Card>
        {users.length === 0 ? (
          <EmptyState message={k("no_users")} />
        ) : (
          <Table caption={k("users_caption")}>
            <thead>
              <tr style={rowBorder}>
                <th style={th}>{k("col.user")}</th>
                <th style={th}>{k("col.principal")}</th>
                <th style={th}>{k("col.roles")}</th>
                <th style={th}>{k("col.scope")}</th>
                <th style={th}>{k("col.source")}</th>
                <th style={th}>{k("col.mfa")}</th>
                <th style={th}>{k("col.status")}</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} style={rowBorder}>
                  <td style={td}>{u.displayName}</td>
                  <td style={td}><code>{u.principal}</code></td>
                  <td style={td}>
                    {u.roles.map((rk) => (
                      <span key={rk} style={{ marginInlineEnd: "var(--rmc-space-1)" }}>
                        <StatusPill tone={!roleByKey.has(rk) ? "danger" : "neutral"}>
                          <code>{roleLabel(rk)}</code>
                        </StatusPill>
                      </span>
                    ))}
                  </td>
                  <td style={td}>{u.scope ? <code>{u.scope}</code> : <span style={{ color: "var(--rmc-text-muted)" }}>{k("scope_all")}</span>}</td>
                  <td style={td}><StatusPill tone={sourceTone(u.source)}>{sourceName(u.source)}</StatusPill></td>
                  <td style={td}><StatusPill tone={mfaTone(u.mfaEnabled)}>{yesNo(u.mfaEnabled)}</StatusPill></td>
                  <td style={td}><StatusPill tone={userStatusTone(u.status)}>{statusName(u.status)}</StatusPill></td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <p style={{ color: "var(--rmc-text-muted)", fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-2)" }}>{k("scope_hint")}</p>

      {/* Roller */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.roles")}</h2>
      <Card>
        {roles.length === 0 ? (
          <EmptyState message={k("no_roles")} />
        ) : (
          <Table caption={k("roles_caption")}>
            <thead>
              <tr style={rowBorder}>
                <th style={th}>{k("col.role")}</th>
                <th style={th}>{k("col.tier")}</th>
                <th style={thEnd}>{k("col.assigned")}</th>
                <th style={th}>{k("col.kind")}</th>
              </tr>
            </thead>
            <tbody>
              {roles.map((r) => (
                <tr key={r.key} style={rowBorder}>
                  <td style={td}><code>{r.key}</code></td>
                  <td style={td}><StatusPill tone={roleTierTone(r.tier)}>{tierName(r.tier)}</StatusPill></td>
                  <td style={tdEnd}>{formatNumber(locale, usersForRole(users, r.key))}</td>
                  <td style={td}>
                    {r.immutable ? <StatusPill tone="neutral">{k("role_immutable")}</StatusPill> : <StatusPill tone="info">{k("role_custom")}</StatusPill>}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <p style={{ color: "var(--rmc-text-muted)", fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-2)" }}>{k("roles_hint")}</p>

      {/* SSO + SCIM */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.federation")}</h2>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "var(--rmc-space-4)" }}>
        {/* SSO */}
        <Card>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "var(--rmc-space-2)" }}>
            <h3 style={{ margin: 0, fontSize: "var(--rmc-size-lg)" }}>{k("sso.heading")}</h3>
            <StatusPill tone={connStateTone(sso.state)}>{connName(sso.state)}</StatusPill>
          </div>
          <KvRow label={k("sso.protocol")}>{protocolName(sso.protocol)}</KvRow>
          <KvRow label={k("sso.idp")}>{sso.idpLabel ?? "—"}</KvRow>
          <KvRow label={k("sso.mfa_enforced")}><StatusPill tone={mfaTone(sso.mfaEnforced)}>{yesNo(sso.mfaEnforced)}</StatusPill></KvRow>
          <KvRow label={k("sso.jit")}>{yesNo(sso.jitProvisioning)}</KvRow>
          <KvRow label={k("sso.default_role")}>{sso.defaultRole ? <code>{roleLabel(sso.defaultRole)}</code> : "—"}</KvRow>
          <div style={{ marginTop: "var(--rmc-space-3)" }}>
            <Button variant="secondary">{k("action.configure_sso")}</Button>
          </div>
        </Card>
        {/* SCIM */}
        <Card>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "var(--rmc-space-2)" }}>
            <h3 style={{ margin: 0, fontSize: "var(--rmc-size-lg)" }}>{k("scim.heading")}</h3>
            <StatusPill tone={connStateTone(scim.state)}>{connName(scim.state)}</StatusPill>
          </div>
          <KvRow label={k("scim.token")}><StatusPill tone={scim.tokenConfigured ? "success" : "warning"}>{scim.tokenConfigured ? k("scim.token_set") : k("scim.token_unset")}</StatusPill></KvRow>
          <KvRow label={k("scim.last_sync")}>{scim.lastSyncAt ? formatDate(locale, new Date(scim.lastSyncAt), { dateStyle: "medium", timeStyle: "short" }) : "—"}</KvRow>
          <KvRow label={k("scim.synced_users")}>{formatNumber(locale, scim.syncedUsers)}</KvRow>
          <KvRow label={k("scim.group_mappings")}>{formatNumber(locale, scim.groupMappings)}</KvRow>
          <div style={{ marginTop: "var(--rmc-space-3)" }}>
            <Button variant="secondary">{k("action.configure_scim")}</Button>
          </div>
        </Card>
      </div>
      <p style={{ color: "var(--rmc-text-muted)", fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>{k("federation_hint")}</p>
    </section>
  );
}
