// WBS 13.4.13 — L2 ekranı A-13 "QA Değerlendirme" (gerçek içerik; 13.1.1 iskeletinin yerini alır).
//
// İÇERİK (BRD §17.5 A-13 — "Otomatik + manuel kalite skorlama"): TEK çağrının KALİTE DEĞERLENDİRMESİ.
// DEĞERLENDİRME ÖZETİ (6 KPI: otomatik skor · band · kritik işaret · açık işaret · manuel inceleme · kalibrasyon),
// OTOMATİK SKORKART (FR-ANA-001 — ağırlıklı boyutlar compliance/accuracy/resolution/tooling/communication/safety;
// genel skor ≈ ağırlıklı boyut skoru), KRİTİK İŞARETLER (FR-ANA-004 yanlış bilgi/tool hatası/güvenlik ihlali +
// FR-ANA-008 kritik konuşma otomatik işaretleme; yapısal kanıt referansı turnRef — ham metin DEĞİL), MANUEL
// DEĞERLENDİRME (FR-ANA-009 — QA skor + disposition + REDACTION'LI açıklama; otomatik↔manuel kalibrasyon) ve
// SÜRÜM KARŞILAŞTIRMASI (FR-ANA-010 — agent sürümleri arası performans). A-13 METRİK/SKOR gösterir (Tier A);
// transkript İÇERİĞİNİ TAŞIMAZ (içerik A-12'de, içerik kapısı + audit'le). Ham ses/ham transkript blob/transkript
// metni/ham numara (e164)/müşteri PII/kart-OTP/nesne-depo URI'si GÖSTERİLMEZ; PII yalnız MASK_TOKEN ([•••]).
// QA açıklaması (comment/note) YAZAR girdisidir ve redaction'lı tutulur (BRD §17.7). TENANT-SCOPE (FR-TEN-002):
// yalnız oturum açan tenant (middleware 13.1.2 + RLS). RBAC (BRD §17.6 A-13 satırı): operations_manager=Yönet ·
// conversation_designer=Görüntüle · qa_analyst=Yönet · human_agent=— (erişim yok). UI yalnız görsel kapı;
// skor/açıklama yazımı + erişim-audit nihai yetki + işlem backend'de (qa:score — API §8.1 /calls/{id}/evaluations).
// Tüm metin i18n'den (t()); skor/işaret/açıklama ise ÇAĞRI VERİSİDİR (agent adı gibi — locale-agnostik, redaction'lı).
import type { CSSProperties } from "react";
import { getServerLocale } from "@/lib/i18n/server";
import { getCatalog, t, formatNumber, formatDate } from "@/lib/i18n";
import { PageHeader, Card, StatusPill, Alert, Table, Button, EmptyState } from "@/lib/ui/components";
import {
  getQaEvaluationView,
  sortedDimensions,
  sortedFlags,
  flaggedDimensions,
  criticalFlags,
  openFlags,
  autoFlags,
  scoreBand,
  needsReview,
  reviewComplete,
  reviewPending,
  calibrationDelta,
  calibrationAgreement,
  accessBlocked,
  versionDelta,
  scoreTone,
  bandTone,
  severityTone,
  reviewTone,
  dispositionTone,
  outcomeTone,
  directionTone,
  type CallDirection,
  type CallOutcome,
  type DimensionKey,
  type FlagType,
  type FlagSeverity,
  type ReviewStatus,
  type Disposition,
  type ScoreBand,
} from "@/lib/tenant/qa-eval";

function Kpi({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: "danger" | "warning" | "success" | "info" }) {
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

// Skor tonunu KPI/StatusPill ton birleşimine indir (neutral → info düş; tip daraltma).
type Solid = "danger" | "warning" | "success";
function solid(tone: ReturnType<typeof scoreTone>): Solid {
  return tone === "neutral" || tone === "info" ? "success" : tone;
}

export default async function Page() {
  const locale = getServerLocale();
  const cat = getCatalog(locale);
  const k = (key: string, p?: Record<string, string | number>) => t(cat, `screen.a13.${key}`, p);
  const view = await getQaEvaluationView();
  const ev = view.evaluation;
  const thr = view.thresholds;

  const dims = sortedDimensions(ev);
  const flags = sortedFlags(ev);
  const weakDims = flaggedDimensions(ev.dimensions);
  const crit = criticalFlags(ev.flags);
  const open = openFlags(ev.flags);
  const autos = autoFlags(ev.flags);
  const band = scoreBand(ev.autoScore, thr);
  const mustReview = needsReview(ev, thr);
  const reviewed = reviewComplete(ev);
  const pending = reviewPending(ev);
  const blocked = accessBlocked(ev);
  const calDelta = calibrationDelta(ev);
  const calAgree = calibrationAgreement(ev);
  const vDelta = versionDelta(view.benchmark);

  const directionName = (d: CallDirection) => k(`direction.${d}`);
  const outcomeName = (o: CallOutcome) => k(`outcome.${o}`);
  const dimensionName = (d: DimensionKey) => k(`dimension.${d}`);
  const flagName = (f: FlagType) => k(`flag.${f}`);
  const severityName = (s: FlagSeverity) => k(`severity.${s}`);
  const reviewName = (s: ReviewStatus) => k(`review_status.${s}`);
  const dispositionName = (d: Disposition) => k(`disposition.${d}`);
  const bandName = (b: ScoreBand) => k(`band.${b}`);

  const durationFmt = (sec: number) => k("duration_fmt", { min: formatNumber(locale, Math.floor(sec / 60)), sec: formatNumber(locale, sec % 60) });
  const pctFmt = (n: number) => k("percent", { n: formatNumber(locale, Math.round(n * 100)) });
  const deltaFmt = (n: number) => `${n >= 0 ? "+" : "−"}${k("points", { n: formatNumber(locale, Math.abs(Math.round(n * 100))) })}`;

  return (
    <section data-screen="A-13">
      <PageHeader title={k("title")} description={k("subtitle")} code="A-13" />

      <div style={{ marginBottom: "var(--rmc-space-4)" }}>
        <Alert tone="info">{k("scope_note")}</Alert>
      </div>

      <p style={{ ...muted, fontSize: "var(--rmc-size-sm)", marginTop: 0 }}>
        {k("as_of", { time: formatDate(locale, new Date(view.generatedAt), { dateStyle: "medium", timeStyle: "short" }) })}
        {" · "}
        <span>{k("tenant")}: {view.tenantName}</span>
        {" · "}
        <span>{k("call_label")}: <code style={{ fontSize: "var(--rmc-size-xs)" }}>{ev.callRef}</code></span>
        {" · "}
        <span>{k("agent_label")}: <strong>{ev.agentName}</strong> <code style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{ev.agentVersion}</code></span>
        {" · "}
        <span>{k("meta.direction")}: <StatusPill tone={directionTone(ev.direction)}>{directionName(ev.direction)}</StatusPill></span>
        {" · "}
        <span>{k("meta.outcome")}: <StatusPill tone={outcomeTone(ev.outcome)}>{outcomeName(ev.outcome)}</StatusPill></span>
        {" · "}
        <span>{k("meta.duration")}: {durationFmt(ev.durationSec)}</span>
      </p>

      {/* Uyarılar */}
      {blocked && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="danger">{k("alert.access_blocked")}</Alert>
        </div>
      )}
      {ev.critical && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="danger">{k("alert.critical", { count: formatNumber(locale, crit.length) })}</Alert>
        </div>
      )}
      {mustReview && pending && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="warning">{k("alert.needs_review")}</Alert>
        </div>
      )}
      {reviewed && calAgree === false && (
        <div style={{ margin: "var(--rmc-space-2) 0" }}>
          <Alert tone="warning">{k("alert.calibration_gap", { delta: pctFmt(calDelta ?? 0) })}</Alert>
        </div>
      )}

      {/* Değerlendirme özeti (KPI) */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", margin: "var(--rmc-space-2) 0 var(--rmc-space-3)" }}>
        <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: 0 }}>{k("section.summary")}</h2>
        <Button variant="secondary">{k("action.export")}</Button>
      </div>
      <div style={grid()}>
        <Kpi label={k("kpi.auto_score")} value={pctFmt(ev.autoScore)} hint={k("kpi.auto_score_hint")} tone={solid(scoreTone(ev.autoScore, thr))} />
        <Kpi label={k("kpi.band")} value={bandName(band)} hint={k("kpi.band_hint", { pass: pctFmt(thr.pass), fail: pctFmt(thr.fail) })} tone={solid(bandTone(band))} />
        <Kpi label={k("kpi.critical")} value={formatNumber(locale, crit.length)} hint={k("kpi.critical_hint")} tone={crit.length > 0 ? "danger" : "success"} />
        <Kpi label={k("kpi.open_flags")} value={formatNumber(locale, open.length)} hint={k("kpi.open_flags_hint", { auto: formatNumber(locale, autos.length) })} tone={open.length > 0 ? "warning" : "success"} />
        <Kpi label={k("kpi.review")} value={reviewName(ev.review.status)} hint={k("kpi.review_hint")} tone={reviewed ? "success" : mustReview ? "warning" : "info"} />
        <Kpi label={k("kpi.calibration")} value={calDelta === null ? k("calibration.na") : deltaFmt(ev.autoScore - (ev.review.score ?? 0))} hint={k("kpi.calibration_hint", { tol: pctFmt(0.1) })} tone={calAgree === null ? "info" : calAgree ? "success" : "warning"} />
      </div>

      {/* Otomatik skorkart (FR-ANA-001) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.scorecard")}</h2>
      <Card>
        <Table caption={k("scorecard_caption")}>
          <thead>
            <tr style={rowBorder}>
              <th style={th}>{k("col.dimension")}</th>
              <th style={th}>{k("col.purpose")}</th>
              <th style={thEnd}>{k("col.weight")}</th>
              <th style={thEnd}>{k("col.score")}</th>
            </tr>
          </thead>
          <tbody>
            {dims.map((d) => {
              const weak = d.score < 0.7;
              return (
                <tr key={d.key} style={rowBorder}>
                  <td style={td}><strong>{dimensionName(d.key)}</strong></td>
                  <td style={td}><span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{k(`dimension_desc.${d.key}`)}</span></td>
                  <td style={tdEnd}>{pctFmt(d.weight)}</td>
                  <td style={tdEnd}>
                    <StatusPill tone={solid(scoreTone(d.score, thr))}>{pctFmt(d.score)}</StatusPill>
                    {weak && <span style={{ color: "var(--rmc-warning-fg, #b54708)", fontSize: "var(--rmc-size-xs)" }}> · {k("weak_badge")}</span>}
                  </td>
                </tr>
              );
            })}
            <tr style={{ borderTop: "2px solid var(--rmc-border-subtle)" }}>
              <td style={td}><strong>{k("overall")}</strong></td>
              <td style={td}><span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{k("overall_desc")}</span></td>
              <td style={tdEnd}>{pctFmt(1)}</td>
              <td style={tdEnd}><StatusPill tone={solid(scoreTone(ev.autoScore, thr))}>{pctFmt(ev.autoScore)}</StatusPill></td>
            </tr>
          </tbody>
        </Table>
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>{k("scorecard_hint", { weak: formatNumber(locale, weakDims.length) })}</p>

      {/* Kritik işaretler (FR-ANA-004/008) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.flags")}</h2>
      <Card>
        {flags.length === 0 ? (
          <EmptyState message={k("no_flags")} />
        ) : (
          <Table caption={k("flags_caption")}>
            <thead>
              <tr style={rowBorder}>
                <th style={th}>{k("col.flag")}</th>
                <th style={th}>{k("col.severity")}</th>
                <th style={th}>{k("col.source")}</th>
                <th style={th}>{k("col.evidence")}</th>
                <th style={th}>{k("col.status")}</th>
              </tr>
            </thead>
            <tbody>
              {flags.map((f) => (
                <tr key={f.flagRef} style={rowBorder}>
                  <td style={td}>
                    <strong>{flagName(f.type)}</strong>
                    {f.note && <div style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{f.note}</div>}
                  </td>
                  <td style={td}><StatusPill tone={severityTone(f.severity)}>{severityName(f.severity)}</StatusPill></td>
                  <td style={td}><span style={{ ...muted, fontSize: "var(--rmc-size-xs)" }}>{f.auto ? k("source.auto") : k("source.manual")}</span></td>
                  <td style={td}>{f.turnRef ? <code style={{ fontSize: "var(--rmc-size-xs)" }}>{f.turnRef}</code> : <span style={muted}>—</span>}</td>
                  <td style={td}>{f.resolved ? <StatusPill tone="success">{k("flag_state.resolved")}</StatusPill> : <StatusPill tone="warning">{k("flag_state.open")}</StatusPill>}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>{k("flags_hint")}</p>

      {/* Manuel değerlendirme (FR-ANA-009) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.review")}</h2>
      <Card>
        <Table caption={k("review_caption")}>
          <thead>
            <tr style={rowBorder}>
              <th style={th}>{k("col.field")}</th>
              <th style={th}>{k("col.value")}</th>
            </tr>
          </thead>
          <tbody>
            <tr style={rowBorder}>
              <td style={td}>{k("review.status")}</td>
              <td style={td}><StatusPill tone={reviewTone(ev.review.status)}>{reviewName(ev.review.status)}</StatusPill></td>
            </tr>
            <tr style={rowBorder}>
              <td style={td}>{k("review.score")}</td>
              <td style={td}>{reviewed && typeof ev.review.score === "number" ? <StatusPill tone={solid(scoreTone(ev.review.score, thr))}>{pctFmt(ev.review.score)}</StatusPill> : <span style={muted}>{k("calibration.na")}</span>}</td>
            </tr>
            <tr style={rowBorder}>
              <td style={td}>{k("review.disposition")}</td>
              <td style={td}>{ev.review.disposition ? <StatusPill tone={dispositionTone(ev.review.disposition)}>{dispositionName(ev.review.disposition)}</StatusPill> : <span style={muted}>—</span>}</td>
            </tr>
            <tr style={rowBorder}>
              <td style={td}>{k("review.reviewer")}</td>
              <td style={td}>{ev.review.reviewerRef ? <code style={{ fontSize: "var(--rmc-size-xs)" }}>{ev.review.reviewerRef}</code> : <span style={muted}>—</span>}</td>
            </tr>
            <tr style={rowBorder}>
              <td style={td}>{k("review.calibration")}</td>
              <td style={td}>{calAgree === null ? <span style={muted}>{k("calibration.na")}</span> : calAgree ? <StatusPill tone="success">{k("calibration.agree", { delta: pctFmt(calDelta ?? 0) })}</StatusPill> : <StatusPill tone="warning">{k("calibration.gap", { delta: pctFmt(calDelta ?? 0) })}</StatusPill>}</td>
            </tr>
            <tr style={rowBorder}>
              <td style={td}>{k("review.comment")}</td>
              <td style={td}>{ev.review.comment ? ev.review.comment : <span style={muted}>—</span>}</td>
            </tr>
          </tbody>
        </Table>
        <div style={{ display: "flex", gap: "var(--rmc-space-2)", marginTop: "var(--rmc-space-3)" }}>
          <Button variant="primary">{reviewed ? k("action.rescore") : k("action.score")}</Button>
          {!reviewed && <Button variant="secondary">{k("action.assign")}</Button>}
        </div>
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>{k("review_hint")}</p>

      {/* Sürüm karşılaştırması (FR-ANA-010) */}
      <h2 style={{ fontSize: "var(--rmc-size-xl)", margin: "var(--rmc-space-5) 0 var(--rmc-space-3)" }}>{k("section.benchmark")}</h2>
      <Card>
        <Table caption={k("benchmark_caption")}>
          <thead>
            <tr style={rowBorder}>
              <th style={th}>{k("col.metric")}</th>
              <th style={thEnd}>{k("col.value")}</th>
            </tr>
          </thead>
          <tbody>
            <tr style={rowBorder}>
              <td style={td}>{k("benchmark.version", { v: ev.agentVersion })}</td>
              <td style={tdEnd}><StatusPill tone={solid(scoreTone(view.benchmark.versionAvgScore, thr))}>{pctFmt(view.benchmark.versionAvgScore)}</StatusPill></td>
            </tr>
            <tr style={rowBorder}>
              <td style={td}>{k("benchmark.agent")}</td>
              <td style={tdEnd}>{pctFmt(view.benchmark.agentAvgScore)}</td>
            </tr>
            <tr style={rowBorder}>
              <td style={td}>{k("benchmark.delta")}</td>
              <td style={tdEnd}><span style={{ color: vDelta >= 0 ? "var(--rmc-success-fg, #067647)" : "var(--rmc-danger-fg, #b42318)" }}>{deltaFmt(vDelta)}</span></td>
            </tr>
            <tr style={rowBorder}>
              <td style={td}>{k("benchmark.sample")}</td>
              <td style={tdEnd}>{k("benchmark.sample_fmt", { n: formatNumber(locale, view.benchmark.sampleSize) })}</td>
            </tr>
          </tbody>
        </Table>
      </Card>
      <p style={{ ...muted, fontSize: "var(--rmc-size-xs)", marginTop: "var(--rmc-space-3)" }}>{k("benchmark_hint")}</p>
    </section>
  );
}
