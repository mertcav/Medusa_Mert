// WBS 13.3.4 — L1 ekranı T-04 "Telefon Numarası & SIP/Trunk" (gerçek içerik; 13.1.1 iskeletinin yerini alır).
//
// İÇERİK (BRD §17.4 / FR-TEL-001/002/004/005 · FR-AGT-007): tenant'ın telefon NUMARA HAVUZU (E.164 DID'ler),
// SIP trunk / BYOC bağlantıları ve giden Caller ID yönetimi.
// TENANT-SCOPE (FR-TEN-002): yalnız oturum açan tenant'ın KENDİ telefoni envanteri; scope middleware (13.1.2) +
// RLS (§13) ile sabitlenir. HİJYEN (BRD §17.7 ruhu): yalnız tenant'ın KENDİ telefoni konfigürasyonu; ham son-
// müşteri içeriği (çağrı kaydı/transkript/arayan müşteri numarası/PII) ve SIP trunk sırrı gömülmez — veri
// katmanı `assertNoPii` ile garanti eder. RBAC (BRD §17.6): tenant_owner=Yönet · tenant_admin=Yönet ·
// security_compliance_officer=— · billing_viewer=— · api_developer=Görüntüle. UI yalnız görsel kapı; nihai
// yetki backend'de (12.2.x, SAD §14.4.1 A8). Tüm kullanıcı-görünür metin i18n katalogundan (t()).
import type { CSSProperties } from "react";
import { getServerLocale } from "@/lib/i18n/server";
import { getCatalog, t, formatNumber, formatDate } from "@/lib/i18n";
import { PageHeader, Card, StatusPill, Alert, Table, Button, EmptyState } from "@/lib/ui/components";
import {
  getNumbers,
  countNumberStatus,
  unassignedNumbers,
  invalidTrunkRefs,
  invalidE164Numbers,
  trunkUtilizationPct,
  overCapacityTrunks,
  unverifiedDefaultCallerIds,
  numberStatusTone,
  trunkStateTone,
  trunkTypeTone,
  callerIdStatusTone,
  directionTone,
  utilTone,
  type NumberStatus,
  type NumberDirection,
  type TrunkType,
  type ConnState,
  type CallerIdStatus,
} from "@/lib/tenant/numbers";

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

export default async function Page() {
  const locale = getServerLocale();
  const cat = getCatalog(locale);
  const k = (key: string, p?: Record<string, string | number>) => t(cat, `screen.t04.${key}`, p);
  const snap = await getNumbers();
  const { trunks, numbers, callerIds } = snap;

  const byStatus = countNumberStatus(numbers);
  const pool = unassignedNumbers(numbers);
  const invalidTrunk = new Set(invalidTrunkRefs(numbers, trunks));
  const invalidE164 = new Set(invalidE164Numbers(numbers));
  const overCap = new Set(overCapacityTrunks(trunks));
  const unverifiedDefault = new Set(unverifiedDefaultCallerIds(callerIds));

  const statusName = (s: NumberStatus) => k(`status_label.${s}`);
  const directionName = (d: NumberDirection) => k(`direction.${d}`);
  const trunkTypeName = (tp: TrunkType) => k(`trunk_type.${tp}`);
  const connName = (s: ConnState) => k(`conn.${s}`);
  const callerIdName = (s: CallerIdStatus) => k(`caller_status.${s}`);
  const trunkByKey = new Map(trunks.map((tk) => [tk.id, tk] as const));
  const trunkLabel = (id: string) => (trunkByKey.has(id) ? trunkByKey.get(id)!.name : `${id} (?)`);
  const yesNo = (b: boolean) => (b ? k("yes") : k("no"));

  return (
    <section data-screen="T-04">
      <PageHeader title={k("title")} description={k("subtitle")} code="T-04" />

      <div style={{ marginBottom: "var(--rmc-space-4)" }}>
        <Alert tone="info">{k("scope_note")}</Alert>
      </div>

      <p style={{ color: "var(--rmc-text-muted)", fontSize: "var(--rmc-size-sm)", marginTop: 0 }}>
        {k("as_of", { time: formatDate(locale, new Date(snap.generatedAt), { dateStyle: "medium", timeStyle: "short" }) })}
        {" · "}
        <span>{k("tenant")}: {snap.tenantName}</span>
      </p>

      {invalidTrunk.size > 0 && (
        <div style={{ margin: "var(--rmc-space-3) 0 var(--rmc-space-2)" }}>
          <Alert tone="danger">{k("invalid_trunk_alert", { count: formatNumber(locale, invalidTrunk.size) })}</Alert>
        </div>
      )}
      {invalidE164.size > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="danger">{k("invalid_e164_alert", { count: formatNumber(locale, invalidE164.size) })}</Alert>
        </div>
      )}
      {overCap.size > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="warning">{k("capacity_alert", { count: formatNumber(locale, overCap.size) })}</Alert>
        </div>
      )}
      {unverifiedDefault.size > 0 && (
        <div style={{ margin: "var(--rmc-space-2) 0 var(--rmc-space-4)" }}>
          <Alert tone="warning">{k("caller_alert", { count: formatNumber(locale, unverifiedDefault.size) })}</Alert>
        </div>
      )}

      {/* Özet */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", marginBottom: "var(--rmc-space-3)" }}>{k("section.summary")}</h2>
      <div style={grid()}>
        <Kpi label={k("kpi.numbers")} value={formatNumber(locale, numbers.length)} hint={k("kpi.numbers_hint", { active: formatNumber(locale, byStatus.active) })} />
        <Kpi label={k("kpi.pool")} value={formatNumber(locale, pool.length)} hint={k("kpi.pool_hint")} />
        <Kpi label={k("kpi.trunks")} value={formatNumber(locale, trunks.length)} hint={k("kpi.trunks_hint")} />
        <Kpi label={k("kpi.caller_ids")} value={formatNumber(locale, callerIds.length)} hint={k("kpi.caller_ids_hint")} />
      </div>

      {/* SIP Trunk & BYOC */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>
        <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: 0 }}>{k("section.trunks")}</h2>
        <Button variant="primary">{k("action.new_trunk")}</Button>
      </div>
      <Card>
        {trunks.length === 0 ? (
          <EmptyState message={k("no_trunks")} />
        ) : (
          <Table caption={k("trunks_caption")}>
            <thead>
              <tr style={rowBorder}>
                <th style={th}>{k("col.trunk")}</th>
                <th style={th}>{k("col.type")}</th>
                <th style={th}>{k("col.region")}</th>
                <th style={th}>{k("col.flow")}</th>
                <th style={thEnd}>{k("col.channels")}</th>
                <th style={th}>{k("col.state")}</th>
              </tr>
            </thead>
            <tbody>
              {trunks.map((tk) => {
                const util = trunkUtilizationPct(tk);
                return (
                  <tr key={tk.id} style={rowBorder}>
                    <td style={td}>{tk.name} <code style={{ color: "var(--rmc-text-muted)" }}>{tk.id}</code></td>
                    <td style={td}><StatusPill tone={trunkTypeTone(tk.type)}>{trunkTypeName(tk.type)}</StatusPill></td>
                    <td style={td}><code>{tk.region}</code></td>
                    <td style={td}>
                      {tk.inbound && <span style={{ marginInlineEnd: "var(--rmc-space-1)" }}><StatusPill tone="info">{k("flow.in")}</StatusPill></span>}
                      {tk.outbound && <StatusPill tone="info">{k("flow.out")}</StatusPill>}
                      {!tk.inbound && !tk.outbound && <span style={{ color: "var(--rmc-text-muted)" }}>—</span>}
                    </td>
                    <td style={tdEnd}>
                      {formatNumber(locale, tk.channelsInUse)} / {formatNumber(locale, tk.channels)}{" "}
                      <StatusPill tone={utilTone(util)}>{k("util_pct", { pct: formatNumber(locale, util) })}</StatusPill>
                    </td>
                    <td style={td}><StatusPill tone={trunkStateTone(tk.state)}>{connName(tk.state)}</StatusPill></td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        )}
      </Card>
      <p style={{ color: "var(--rmc-text-muted)", fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-2)" }}>{k("trunks_hint")}</p>

      {/* Numara Havuzu */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>
        <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: 0 }}>{k("section.numbers")}</h2>
        <Button variant="primary">{k("action.new_number")}</Button>
      </div>
      <Card>
        {numbers.length === 0 ? (
          <EmptyState message={k("no_numbers")} />
        ) : (
          <Table caption={k("numbers_caption")}>
            <thead>
              <tr style={rowBorder}>
                <th style={th}>{k("col.number")}</th>
                <th style={th}>{k("col.label")}</th>
                <th style={th}>{k("col.direction")}</th>
                <th style={th}>{k("col.trunk")}</th>
                <th style={th}>{k("col.assignment")}</th>
                <th style={th}>{k("col.status")}</th>
              </tr>
            </thead>
            <tbody>
              {numbers.map((n) => (
                <tr key={n.id} style={rowBorder}>
                  <td style={td}>
                    <code>{n.e164}</code>
                    {invalidE164.has(n.id) && <span style={{ marginInlineStart: "var(--rmc-space-1)" }}><StatusPill tone="danger">{k("badge.invalid_e164")}</StatusPill></span>}
                  </td>
                  <td style={td}>{n.label ?? <span style={{ color: "var(--rmc-text-muted)" }}>—</span>}</td>
                  <td style={td}><StatusPill tone={directionTone(n.direction)}>{directionName(n.direction)}</StatusPill></td>
                  <td style={td}>
                    {n.trunkRef ? (
                      <StatusPill tone={invalidTrunk.has(n.id) ? "danger" : "neutral"}>{trunkLabel(n.trunkRef)}</StatusPill>
                    ) : (
                      <span style={{ color: "var(--rmc-text-muted)" }}>—</span>
                    )}
                  </td>
                  <td style={td}>{n.assignedTo ? <code>{n.assignedTo}</code> : <StatusPill tone="info">{k("pool_label")}</StatusPill>}</td>
                  <td style={td}><StatusPill tone={numberStatusTone(n.status)}>{statusName(n.status)}</StatusPill></td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <p style={{ color: "var(--rmc-text-muted)", fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-2)" }}>{k("numbers_hint")}</p>

      {/* Caller ID */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>
        <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: 0 }}>{k("section.caller_ids")}</h2>
        <Button variant="secondary">{k("action.new_caller_id")}</Button>
      </div>
      <Card>
        {callerIds.length === 0 ? (
          <EmptyState message={k("no_caller_ids")} />
        ) : (
          <Table caption={k("caller_ids_caption")}>
            <thead>
              <tr style={rowBorder}>
                <th style={th}>{k("col.number")}</th>
                <th style={th}>{k("col.label")}</th>
                <th style={th}>{k("col.verification")}</th>
                <th style={th}>{k("col.default")}</th>
              </tr>
            </thead>
            <tbody>
              {callerIds.map((c) => (
                <tr key={c.id} style={rowBorder}>
                  <td style={td}><code>{c.e164}</code></td>
                  <td style={td}>{c.label ?? <span style={{ color: "var(--rmc-text-muted)" }}>—</span>}</td>
                  <td style={td}><StatusPill tone={callerIdStatusTone(c.status)}>{callerIdName(c.status)}</StatusPill></td>
                  <td style={td}>
                    {c.isDefault ? (
                      <StatusPill tone={unverifiedDefault.has(c.id) ? "danger" : "success"}>{k("default_yes")}</StatusPill>
                    ) : (
                      <span style={{ color: "var(--rmc-text-muted)" }}>{yesNo(false)}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <p style={{ color: "var(--rmc-text-muted)", fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>{k("caller_ids_hint")}</p>
    </section>
  );
}
