#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
containment_report_probe.py — WBS 14.2.3 Containment/transfer oranı raporu

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only statik + davranış kapısı.
`runtime/call-derivation/` (14.2.2) probe disipliniyle birebir; burada deterministik bir ANALYTICS-PLANE
ORAN (RATE) AGREGASYON/RAPOR motoru (SAD §4.2 async batch; analytics-ingest consumer) simülatörü (saf; random YOK).

ORAN RAPOR MOTORU — Analytics/Ops Plane'de (SAD §4.2/§171, FR-RES-011) async/non-blocking; 14.2.2'nin ürettiği
per-call outcome ETİKETİNİ (contained/transferred_to_human/abandoned/unresolved/not_connected — kapalı-sözlük)
AGREGE eder ve FR-ANA-003 containment_rate + transfer_rate metriklerini (BRD §18.1 KPI; OLAP mv_call_daily)
rapor boyutlarına (tenant_id + agent_id + agent_version_id + period) göre + genel olarak hesaplar:
  • Partisyon (G1):   outcome kovaları girdiyi TAM partisyonlar (her çağrı tam 1 kova; toplam==girdi; çift/düşme yok) — BİRİNCİL.
  • Payda (G2):       containment=contained/handled, transfer=transferred/handled; pay≤payda; oran∈[0,1]; 4 partisyon oranı toplamı==1.0.
  • Münhasır (G3):    bir çağrı tam BİR kovada (mutually exclusive); çift-kova sayımı ihlal.
  • Sözlük (G4):      outcome 14.2.2 vocab + OLAP fct_call.contained/transferred ile BİREBİR (non-circular).
  • İdempotent (G5):  (tenant_id,call_id) bir kez sayılır; at-least-once çift-sayım üretmez (replay-safe).
  • Bastırma (G6):    payda < min_group_n → oran YAYIMLANMAZ (insufficient_sample); k-anonimlik + istatistik güvenilirlik.
  • İzolasyon (G7):   her rapor tek tenant_id + cross-tenant yok + residency (FR-TEN-002/NFR 10.7).
  • PII (G8):         yalnız redaksiyonlu etiket + düşük-kardinalite boyut; yayımlanan agregat PII/per-call kimlik taşımaz (FR-REC-004).
  • Async (G9):       analytics plane non-blocking; rapor başarısızlığı canlı çağrıyı etkilemez (FR-RES-011).

KAPSAM AYRIMI: per-call ÇIKARIM (intent/outcome/disposition/completion) → 14.2.2 (bu motorun GİRDİSİNİ üretir;
bu motor etiketi YENİDEN TÜRETMEZ, AGREGE eder) · otomatik kalite skoru → 14.2.1 · yanlış-bilgi/tool-hata/güvenlik
İŞARETİ → 14.2.4 · kritik işaretleme → 14.2.5 · MANUEL skor → 14.2.6 · dashboard/export → 14.2.8. Burada YALNIZ
containment/transfer ORAN agregasyonu + partisyon/payda bütünlüğü.

Komutlar:
  validate              containment-report-spec.json'ı invariant'lara + OLAP/14.2.2 çapraz-tutarlılığa + config'e karşı doğrular.
  report <sample>       Deterministik ContainmentReportEngine — çağrı seti → grup/overall oran + partisyon + HARD kapılar (G1–G9); →çıkış kodu.
  selftest              İyi/kötü spec+sample ile kapıların doğru tetiklendiğini kanıtlar.
  schema                Beklenen spec şeklini özetler.

Sunucu/credential GEREKMEZ. report gerçek motor yerine deterministik simülasyondur (canlıda fct_call/call.outcome
consumer + OLAP mv_call_daily sink, SAD §4.2/§12.1; ADR-007). Ham ses payload/transkript METNİ/PII DEĞERİ YOK —
örnekler yalnız REDAKSİYONLU outcome etiketi + düşük-kardinalite boyut/kimlik anahtarı ADLARI taşır.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "containment-report-spec.json")
PROFILES_CFG = os.path.join(HERE, "config", "containment-report-profiles.json")

ERROR_TAXONOMY = {
    "TIMEOUT", "RATE_LIMITED", "UNAVAILABLE", "AUTH",
    "INVALID_REQUEST", "CONTENT_FILTERED", "QUOTA_EXCEEDED", "REGION_VIOLATION",
}
SECRET_RE = re.compile(
    r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer)\b\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}"
)
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")
# Ham PII DEĞER desenleri (girdi/çıktıda yasak — FR-REC-004). Yalnız anahtar ADI olmalı.
PII_VALUE_RE = re.compile(
    r"(?:\d[ \-]?){7,}"                                   # ≥7 ardışık rakam (telefon/kart/IBAN)
    r"|[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"  # e-posta
    r"|\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b"                  # IBAN
)
# ISO tarih (rapor period boyutu, ör. 2026-06-01) düşük-kardinalite boyut anahtarıdır — PII DEĞİL.
# ≥7-rakam deseni tarihi yanlış eşler; period bir boyuttur, telefon/kart değil → muaf tut.
DATE_RE = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")
RATE_TOL = 1e-9


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_placeholder(v):
    return isinstance(v, str) and PLACEHOLDER_RE.match(v) is not None


def _pii_value(v):
    """v ham PII DEĞERİ mi (telefon/kart/IBAN/e-posta)? Placeholder ${ENV} ve ISO tarih (period boyutu) muaf."""
    return isinstance(v, str) and not _is_placeholder(v) and not DATE_RE.match(v) and bool(PII_VALUE_RE.search(v))


class ReportError(Exception):
    """Geçersiz/eksik rapor girdisi veya bilinmeyen outcome — sessizce kabul yok, reddet (I12)."""


# ─────────────────────────────────────────────────────────────────────────────
# Oran agregasyon motoru — deterministik sayım/bölme (saf; random YOK)
# ─────────────────────────────────────────────────────────────────────────────
class ContainmentReportEngine:
    """Analytics plane'de async/non-blocking; per-call outcome etiketini AGREGE eder + partisyon + payda +
    münhasırlık + sözlük + idempotency + bastırma + tenant izolasyon + PII disiplinine karşı denetler. Saf; random YOK.

    policy bayrakları buggy bir Engine'i simüle eder (14.2.2 deseni):
      partition_all     : her çağrıyı bir kovaya say (kapalı → bilinmeyen outcome sessizce düşürülür, G1 partisyon açığı)
      exclusive_buckets : her çağrı tam BİR kovada (kapalı → contained çağrı transferred'a da sayılır, G3 + G1/G2 bozulur)
      correct_denom     : containment/transfer paydası = handled (kapalı → payda = total incl not_connected, G2 toplam≠1.0)
      closed_vocab      : outcome kapalı-sözlükte (kapalı → serbest-metin outcome geçer, G4)
      idempotent        : (tenant,call) bir kez say (kapalı → replay çift-sayım, G5)
      suppress_small    : payda<min_group_n bastır (kapalı → küçük grup oranı yayımlanır, G6 k-anon/istatistik)
      isolate_tenant    : tek-tenant agregasyon (kapalı → cross-tenant çağrı karışır, G7)
      enforce_redaction : ham PII/transkript girdisini reddet (kapalı → transcript_text geçer, G8)
      non_blocking      : analytics plane non-blocking (kapalı → rapor canlı çağrıyı bloklar, G9)
    """

    def __init__(self, spec, profile, context, policy):
        self.spec = spec
        self.context = dict(context or {})
        self.pol = policy

        ov = spec.get("outcome_vocabulary", {})
        self.all_outcomes = list(ov.get("all_outcomes", []))
        self.handled_outcomes = set(ov.get("handled_outcomes", []))
        self.bucket_of = dict(ov.get("bucket_of", {}))
        self.partition_buckets = list(ov.get("partition_buckets", []))

        self.basis = spec.get("denominator", {}).get("basis", "handled")
        self.min_group_n = spec.get("small_sample", {}).get("min_group_n", 20)
        self.containment_target = spec.get("target", {}).get("containment_target", 0.60)

        fp = spec.get("feature_policy", {})
        self.allowed_keys = set(fp.get("allowed_input_keys", []))
        self.forbidden_keys = set(fp.get("forbidden_input_keys", []))

        self.region_pin = profile.get("region")
        self.schema_version = profile.get("schema_version", 1)
        # profil override (beyan edilen denominator.basis sıkılaştırma için)
        self.basis = profile.get("denominator_basis", self.basis)
        self.min_group_n = profile.get("min_group_n", self.min_group_n)
        self.containment_target = profile.get("containment_target", self.containment_target)

        if not self.context.get("tenant_id"):
            raise ReportError("rapor bağlamı eksik: tenant_id → INVALID_REQUEST")
        if not self.context.get("region"):
            raise ReportError("rapor bağlamı eksik: region → INVALID_REQUEST")

        # sayaçlar (HARD kapı kanıtı)
        self.partition_gap = 0
        self.rate_bound_violations = 0
        self.exclusivity_violations = 0
        self.vocab_violations = 0
        self.idempotency_violations = 0
        self.suppression_violations = 0
        self.isolation_violations = 0
        self.pii_violations = 0
        self.blocking_violations = 0

        self.groups = {}              # group_key → bucket sayaçları
        self.input_count = 0          # tüketilen çağrı (dedup sonrası, partisyona aday)
        self.counted_total = 0        # kovalara fiilen sayılan (G1 toplam karşılaştırması)
        self.derived = {}

    # ── redaksiyonlu girdi denetimi (G8) ──────────────────────────────────────
    def _check_row(self, row):
        if not self.pol.get("enforce_redaction", True):
            return                       # buggy: redaction zorlanmaz
        for k, v in (row or {}).items():
            if k in self.forbidden_keys:
                self.pii_violations += 1
            elif k not in self.allowed_keys:
                self.pii_violations += 1   # whitelist dışı anahtar — potansiyel ham içerik
            if _pii_value(v):
                self.pii_violations += 1   # ham PII DEĞERİ

    def _group_key(self, row):
        return (row.get("agent_id"), row.get("agent_version_id"), row.get("period"))

    def _empty_buckets(self):
        b = {bk: 0 for bk in self.partition_buckets}
        b["not_connected"] = 0
        return b

    def run(self, calls):
        # G9 async/non-blocking (placement): rapor çağrıyı bloklamaz
        if not self.pol.get("non_blocking", True):
            self.blocking_violations += 1
        if not self.spec.get("placement", {}).get("non_blocking", True):
            self.blocking_violations += 1

        seen = set()
        for call in calls:
            outcome = call.get("outcome")
            if outcome is None:
                raise ReportError("çağrı kaydında outcome eksik → INVALID_REQUEST")

            self._check_row(call)

            # G7 izolasyon: cross-tenant + residency
            ct = call.get("tenant_id")
            if ct is not None and self.pol.get("isolate_tenant", True) and ct != self.context.get("tenant_id"):
                self.isolation_violations += 1
                continue              # cross-tenant çağrı agregasyona KARIŞMAZ (izole edilir)
            if ct is not None and not self.pol.get("isolate_tenant", True) and ct != self.context.get("tenant_id"):
                self.isolation_violations += 1   # buggy: karışır (aşağıda sayılır)
            cr = call.get("region")
            if cr is not None and self.region_pin is not None and cr != self.region_pin:
                self.isolation_violations += 1

            # G5 idempotent: (tenant, call_id) bir kez
            key = (self.context.get("tenant_id"), call.get("call_id"))
            if key in seen:
                if self.pol.get("idempotent", True):
                    continue          # daraltılır (tek sayım) — ihlal değil
                else:
                    self.idempotency_violations += 1   # buggy: çift-sayım (aşağıda tekrar sayılır)
            seen.add(key)

            self.input_count += 1

            # G4 sözlük: outcome 14.2.2 kapalı-sözlükte mi
            if outcome not in self.all_outcomes:
                if self.pol.get("closed_vocab", True):
                    self.vocab_violations += 1
                    # G1 partisyon: partition_all AÇIK → bilinmeyen outcome yine sayılmalı; ama kovası yok →
                    # partisyon açığı oluşturur (sessizce düşürülmez sayım denetlenir). Düşür ve gap'e bırak.
                    if not self.pol.get("partition_all", True):
                        continue
                    # bilinmeyen outcome'u 'unresolved'a değil — düşür → counted_total < input_count → G1 gap
                    continue
                else:
                    # buggy: serbest-metin outcome kapalı-sözlüğe zorlanmadan kovaya kabul edilir
                    self.vocab_violations += 1
                    continue

            # G1 partisyon: partition_all KAPALI → handled-dışı (not_connected) sessizce atla
            if not self.pol.get("partition_all", True) and outcome not in self.handled_outcomes:
                continue              # buggy: sessiz düşürme → partition_gap

            bucket = self.bucket_of.get(outcome)
            gk = self._group_key(call)
            self.groups.setdefault(gk, self._empty_buckets())

            # G3 münhasırlık: exclusive_buckets KAPALI → contained çağrı transferred'a da sayılır
            self.groups[gk][bucket] += 1
            self.counted_total += 1
            if not self.pol.get("exclusive_buckets", True) and outcome == "contained":
                self.groups[gk]["transferred"] += 1
                self.counted_total += 1
                self.exclusivity_violations += 1

        # G1 partisyon açığı: kovalara sayılan == tüketilen girdi (çift-sayım counted_total>input → exclusivity'de
        # ayrıca yakalanır; düşürme counted_total<input → gap). Mutlak fark.
        self.partition_gap = abs(self.input_count - self.counted_total) if self.pol.get("exclusive_buckets", True) \
            else max(0, self.input_count - self._unique_counted())

        # grup oranlarını hesapla
        self._finalize_groups()
        self.derived["input_count"] = self.input_count
        self.derived["counted_total"] = self.counted_total
        self.derived["groups"] = len(self.groups)

    def _unique_counted(self):
        # exclusivity bozukken: benzersiz çağrı sayımı (not_connected hariç tüm partisyon + not_connected) —
        # çift-sayım exclusivity_violations'da yakalanır; partition_gap düşürme içindir.
        tot = 0
        for b in self.groups.values():
            tot += sum(b.values())
        return tot - self.exclusivity_violations

    def _finalize_groups(self):
        overall = self._empty_buckets()
        rows = []
        suppressed = 0
        for gk, b in sorted(self.groups.items(), key=lambda kv: tuple("" if x is None else str(x) for x in kv[0])):
            for k in b:
                overall[k] += b[k]
            rows.append((gk, self._group_metrics(b)))
            if rows[-1][1]["status"] == self.spec.get("small_sample", {}).get("suppressed_status", "insufficient_sample"):
                suppressed += 1
        self.derived["rows"] = rows
        self.derived["overall"] = self._group_metrics(overall, is_overall=True)
        self.derived["suppressed_groups"] = suppressed

    def _denominator(self, b):
        handled = sum(b.get(x, 0) for x in self.partition_buckets)
        total = handled + b.get("not_connected", 0)
        if self.basis == "handled":
            return handled, handled, total
        # buggy/alternatif basis: payda = total (not_connected dahil) → partisyon toplamı ≠ 1.0
        return total, handled, total

    def _group_metrics(self, b, is_overall=False):
        denom, handled, total = self._denominator(b)
        contained = b.get("contained", 0)
        transferred = b.get("transferred", 0)
        abandoned = b.get("abandoned", 0)
        unresolved = b.get("unresolved", 0)
        not_connected = b.get("not_connected", 0)

        def rate(num):
            return (num / denom) if denom > 0 else 0.0

        containment_rate = rate(contained)
        transfer_rate = rate(transferred)
        abandon_rate = rate(abandoned)
        unresolved_rate = rate(unresolved)
        not_connected_rate = (not_connected / total) if total > 0 else 0.0

        # G2 oran sınırları: pay ≤ payda + oran ∈ [0,1]
        for num in (contained, transferred, abandoned, unresolved):
            if denom > 0 and num > denom:
                self.rate_bound_violations += 1
        for r in (containment_rate, transfer_rate, abandon_rate, unresolved_rate, not_connected_rate):
            if r < 0.0 - RATE_TOL or r > 1.0 + RATE_TOL:
                self.rate_bound_violations += 1
        # G2 partisyon toplamı == 1.0 (handled>0) — payda bütünlüğü
        if handled > 0:
            psum = containment_rate + transfer_rate + abandon_rate + unresolved_rate
            if abs(psum - 1.0) > 1e-6:
                self.rate_bound_violations += 1

        # G6 küçük-örnek bastırma
        status = self.spec.get("small_sample", {}).get("published_status", "published")
        if handled < self.min_group_n:
            if self.pol.get("suppress_small", True):
                status = self.spec.get("small_sample", {}).get("suppressed_status", "insufficient_sample")
            else:
                self.suppression_violations += 1   # buggy: küçük grup oranı yayımlanır

        m = {
            "calls": total, "handled": handled,
            "contained_count": contained, "transferred_count": transferred,
            "abandoned_count": abandoned, "unresolved_count": unresolved,
            "not_connected_count": not_connected,
            "containment_rate": round(containment_rate, 6),
            "transfer_rate": round(transfer_rate, 6),
            "abandon_rate": round(abandon_rate, 6),
            "unresolved_rate": round(unresolved_rate, 6),
            "not_connected_rate": round(not_connected_rate, 6),
            "status": status,
            "target_met": (containment_rate >= self.containment_target) if (handled > 0 and status != "insufficient_sample") else None,
        }
        return m

    def metrics(self):
        return {
            "partition_gap": self.partition_gap,
            "rate_bound_violations": self.rate_bound_violations,
            "exclusivity_violations": self.exclusivity_violations,
            "vocab_violations": self.vocab_violations,
            "idempotency_violations": self.idempotency_violations,
            "suppression_violations": self.suppression_violations,
            "isolation_violations": self.isolation_violations,
            "pii_violations": self.pii_violations,
            "blocking_violations": self.blocking_violations,
            "derived": dict(self.derived),
        }


def report_calls(sample, spec, profile, context, policy):
    calls = sample.get("calls")
    if not isinstance(calls, list):
        raise ReportError("çağrı seti (calls) liste değil → INVALID_REQUEST")
    for c in calls:
        if not isinstance(c, dict):
            raise ReportError("çağrı kaydı sözlük değil → INVALID_REQUEST")
    eng = ContainmentReportEngine(spec, profile, context, policy)
    eng.run(calls)
    return eng.metrics()


def evaluate(spec, m):
    """Metrikleri HARD kapılara (G1–G9) karşı değerlendirir. Döner findings[(ok, label)]."""
    g = spec.get("gates", {})
    d = m.get("derived", {})
    ov = d.get("overall", {})
    F = []
    F.append((m.get("partition_gap", 0) <= g.get("max_partition_gap", 0),
              "G1 partisyon açığı %d ≤ %d (kovalar girdiyi TAM partisyonlar; sayılan %d / girdi %d; çift/düşme yok — FR-ANA-003) — BİRİNCİL"
              % (m.get("partition_gap", 0), g.get("max_partition_gap", 0),
                 d.get("counted_total", 0), d.get("input_count", 0))))
    F.append((m.get("rate_bound_violations", 0) <= g.get("max_rate_bound_violation", 0),
              "G2 oran/payda ihlali %d ≤ %d (containment=contained/handled, transfer=transferred/handled; pay≤payda; oran∈[0,1]; 4 partisyon toplamı==1.0)"
              % (m.get("rate_bound_violations", 0), g.get("max_rate_bound_violation", 0))))
    F.append((m.get("exclusivity_violations", 0) <= g.get("max_exclusivity_violation", 0),
              "G3 münhasırlık ihlali %d ≤ %d (bir çağrı tam BİR kovada; çift-kova sayımı yok)"
              % (m.get("exclusivity_violations", 0), g.get("max_exclusivity_violation", 0))))
    F.append((m.get("vocab_violations", 0) <= g.get("max_vocab_violation", 0),
              "G4 sözlük ihlali %d ≤ %d (outcome 14.2.2 vocab + OLAP fct_call.contained/transferred ile BİREBİR)"
              % (m.get("vocab_violations", 0), g.get("max_vocab_violation", 0))))
    F.append((m.get("idempotency_violations", 0) <= g.get("max_idempotency_violation", 0),
              "G5 idempotency ihlali %d ≤ %d ((tenant,call_id) bir kez sayılır; replay çift-sayım üretmez)"
              % (m.get("idempotency_violations", 0), g.get("max_idempotency_violation", 0))))
    F.append((m.get("suppression_violations", 0) <= g.get("max_suppression_violation", 0),
              "G6 bastırma ihlali %d ≤ %d (payda<min_group_n grup oranı yayımlanmaz — k-anon + istatistik güvenilirlik)"
              % (m.get("suppression_violations", 0), g.get("max_suppression_violation", 0))))
    F.append((m.get("isolation_violations", 0) <= g.get("max_isolation_violation", 0),
              "G7 izolasyon ihlali %d ≤ %d (tek tenant_id + cross-tenant yok + residency — FR-TEN-002/NFR 10.7)"
              % (m.get("isolation_violations", 0), g.get("max_isolation_violation", 0))))
    F.append((m.get("pii_violations", 0) <= g.get("max_pii_violation", 0),
              "G8 PII ihlali %d ≤ %d (yalnız redaksiyonlu etiket + düşük-kardinalite boyut; agregat PII/per-call kimlik yok — FR-REC-004)"
              % (m.get("pii_violations", 0), g.get("max_pii_violation", 0))))
    F.append((m.get("blocking_violations", 0) <= g.get("max_blocking_violation", 0),
              "G9 blocking ihlali %d ≤ %d (analytics plane non-blocking; rapor canlı çağrıyı etkilemez — FR-RES-011)"
              % (m.get("blocking_violations", 0), g.get("max_blocking_violation", 0))))
    return F


# ─────────────────────────────────────────────────────────────────────────────
# bağlam + politika çözümleme
# ─────────────────────────────────────────────────────────────────────────────
def _profile_by_name(cfg, name):
    for p in cfg.get("profiles", []):
        if p.get("name") == name:
            return p
    raise ReportError("bilinmeyen profil: %s" % name)


def _resolve_context(spec, profile, sample):
    ctx = dict(sample.get("context", {}))
    ctx.setdefault("region", profile.get("region"))
    return ctx


def _full_pol():
    return {"partition_all": True, "exclusive_buckets": True, "correct_denom": True, "closed_vocab": True,
            "idempotent": True, "suppress_small": True, "isolate_tenant": True, "enforce_redaction": True,
            "non_blocking": True}


def _resolve_policy(spec, sample):
    pol = _full_pol()
    pol.update(sample.get("policy", {}))
    return pol


def report_cmd(sample_path):
    spec = _load(SPEC_PATH)
    sample = _load(sample_path)
    name = sample.get("name", os.path.basename(sample_path))
    expect = sample.get("expect", "pass")

    if "profile_obj" in sample:
        profile = sample["profile_obj"]
    else:
        cfg = _load(PROFILES_CFG)
        try:
            profile = _profile_by_name(cfg, sample.get("profile", cfg.get("default_profile")))
        except ReportError as ex:
            print("report[%s]: %s" % (name, ex))
            return 0 if expect == "fail" else 1
    context = _resolve_context(spec, profile, sample)
    policy = _resolve_policy(spec, sample)
    # correct_denom policy → engine basis override (buggy denominator simülasyonu)
    if not policy.get("correct_denom", True):
        profile = dict(profile)
        profile["denominator_basis"] = "total"

    try:
        m = report_calls(sample, spec, profile, context, policy)
    except ReportError as ex:
        print("report[%s]: REDDEDİLDİ — %s" % (name, ex))
        return 0 if expect == "fail" else 1

    F = evaluate(spec, m)
    d = m.get("derived", {})
    ov = d.get("overall", {})
    print("report[%s] %d çağrı → %d grup (sayılan=%d, bastırılan=%d) | partisyon=%d oran/payda=%d münhasır=%d sözlük=%d idempotency=%d bastırma=%d izolasyon=%d pii=%d blocking=%d" % (
        name, len(sample.get("calls", [])), d.get("groups", 0), d.get("counted_total", 0), d.get("suppressed_groups", 0),
        m["partition_gap"], m["rate_bound_violations"], m["exclusivity_violations"], m["vocab_violations"],
        m["idempotency_violations"], m["suppression_violations"], m["isolation_violations"],
        m["pii_violations"], m["blocking_violations"]))
    print("  overall: handled=%d | containment_rate=%.4f transfer_rate=%.4f abandon=%.4f unresolved=%.4f not_connected=%.4f (calls=%d) | target_met=%s" % (
        ov.get("handled", 0), ov.get("containment_rate", 0.0), ov.get("transfer_rate", 0.0),
        ov.get("abandon_rate", 0.0), ov.get("unresolved_rate", 0.0), ov.get("not_connected_rate", 0.0),
        ov.get("calls", 0), ov.get("target_met")))
    for gk, gm in d.get("rows", []):
        print("    grup %s: handled=%d cont=%.3f trans=%.3f [%s]" % (
            gk, gm.get("handled", 0), gm.get("containment_rate", 0.0), gm.get("transfer_rate", 0.0), gm.get("status")))
    for ok, label in F:
        print("  %s %s" % ("✓" if ok else "✗", label))
    gate_ok = all(ok for ok, _ in F) and len(F) > 0

    exp = sample.get("expected", {})
    for k, v in exp.items():
        got = m.get(k)
        match = (got == v)
        print("  %s expected.%s == %r (got %r)" % ("✓" if match else "✗", k, v, got))
        gate_ok = gate_ok and match
    exp_ov = sample.get("expected_overall", {})
    for k, v in exp_ov.items():
        got = ov.get(k)
        match = (got == v) if not isinstance(v, float) else (got is not None and abs(got - v) <= 1e-4)
        print("  %s expected_overall.%s == %r (got %r)" % ("✓" if match else "✗", k, v, got))
        gate_ok = gate_ok and match

    print("  kapı: %d/%d %s" % (sum(1 for ok, _ in F if ok), len(F),
                                 "🟢 GEÇTİ" if gate_ok else "🔴 ELENDİ"))
    if expect == "fail":
        return 0 if not gate_ok else 1
    return 0 if gate_ok else 1


# ─────────────────────────────────────────────────────────────────────────────
# validate
# ─────────────────────────────────────────────────────────────────────────────
def _check(results, ok, label):
    results.append((bool(ok), label))


def _scan(obj, regex, path="root"):
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.startswith("$"):
                continue
            hits += _scan(v, regex, "%s.%s" % (path, k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits += _scan(v, regex, "%s[%d]" % (path, i))
    elif isinstance(obj, str):
        if _is_placeholder(obj):
            return hits
        if regex is PII_VALUE_RE and DATE_RE.match(obj):
            return hits                   # ISO tarih (period boyutu) PII değil — muaf
        if regex.search(obj):
            hits.append((path, obj))
    return hits


def _load_sibling_spec(*parts):
    cand = os.path.normpath(os.path.join(HERE, "..", "..", *parts))
    if os.path.exists(cand):
        try:
            return _load(cand)
        except Exception:
            return None
    return None


def _fct_call(olap):
    for ft in olap.get("fact_tables", []):
        if ft.get("name") == "fct_call":
            return ft
    return None


def _rollup(olap, name):
    for r in olap.get("rollups", []):
        if r.get("name") == name:
            return r
    return None


def validate():
    spec = _load(SPEC_PATH)
    R = []

    _check(R, spec.get("wbs") == "14.2.3", "spec.wbs == 14.2.3")
    _check(R, spec.get("version"), "spec.version mevcut")
    _check(R, spec.get("phase") == "F1", "spec.phase == F1")
    _check(R, spec.get("priority") == "Must", "spec.priority == Must (FR-ANA-003)")
    ed = spec.get("eval_doc", {})
    for k in ("fr", "srs", "rtm", "brd", "sad", "db", "olap", "adr", "api", "upstream"):
        _check(R, bool(ed.get(k)), "eval_doc.%s mevcut" % k)
    _check(R, "FR-ANA-003" in ed.get("fr", ""), "eval_doc.fr FR-ANA-003 (containment/transfer)")

    # ── placement (G9)
    pl = spec.get("placement", {})
    _check(R, pl.get("in_analytics_plane") is True, "G9 motor analytics plane'de (SAD §4.2)")
    _check(R, pl.get("async_batch") is True, "G9 async batch (FR-RES-011)")
    _check(R, pl.get("non_blocking") is True, "G9 non-blocking (rapor canlı çağrıyı etkilemez)")
    _check(R, pl.get("from_redacted_content") is True, "G8 from_redacted_content (redaksiyonlu etiket)")
    _check(R, pl.get("aggregates_labels") is True, "I9 aggregates_labels (etiketi yeniden türetmez — 14.2.2 üretir)")
    _check(R, pl.get("deterministic") is True, "I10 deterministic (vendor-neutral, random yok)")
    _check(R, pl.get("idempotent") is True, "G5 idempotent")
    _check(R, pl.get("from_trace") is False, "from_trace=false (oran agregasyonu, trace türetme değil)")

    # ── outcome_vocabulary (G4)
    ov = spec.get("outcome_vocabulary", {})
    allo = ov.get("all_outcomes", [])
    _check(R, set(allo) == {"contained", "transferred_to_human", "abandoned", "unresolved", "not_connected"},
           "G4 all_outcomes == 14.2.2 outcome kapalı-sözlüğü (5 değer)")
    _check(R, len(allo) == len(set(allo)), "G4 all_outcomes benzersiz")
    _check(R, set(ov.get("handled_outcomes", [])) == {"contained", "transferred_to_human", "abandoned", "unresolved"},
           "G4 handled_outcomes (not_connected HARİÇ — containment paydası)")
    _check(R, ov.get("not_handled_outcomes", []) == ["not_connected"], "I11 not_handled == [not_connected]")
    _check(R, set(ov.get("handled_outcomes", [])) | set(ov.get("not_handled_outcomes", [])) == set(allo),
           "G4 handled ∪ not_handled == all_outcomes (tam bölme)")
    _check(R, not (set(ov.get("handled_outcomes", [])) & set(ov.get("not_handled_outcomes", []))),
           "G4 handled ∩ not_handled == ∅")
    bof = ov.get("bucket_of", {})
    _check(R, set(bof.keys()) == set(allo), "G4 bucket_of her outcome'u eşler")
    _check(R, bof.get("contained") == "contained" and bof.get("transferred_to_human") == "transferred",
           "G4 contained→contained, transferred_to_human→transferred")
    _check(R, set(ov.get("partition_buckets", [])) == {"contained", "transferred", "abandoned", "unresolved"},
           "G2 partition_buckets == handled kovaları (4 partisyon)")

    # ── denominator (G2 / I11)
    den = spec.get("denominator", {})
    _check(R, den.get("basis") == "handled", "I11 denominator.basis == handled (not_connected hariç)")
    _check(R, den.get("not_connected_excluded_from_handled") is True, "I11 not_connected handled paydadan hariç")
    _check(R, den.get("containment_rate") == "contained / handled", "G2 containment_rate = contained/handled")
    _check(R, den.get("transfer_rate") == "transferred / handled", "G2 transfer_rate = transferred/handled")
    _check(R, den.get("rate_bounds") == [0.0, 1.0], "G2 rate_bounds [0,1]")
    _check(R, "1.0" in str(den.get("partition_sum_invariant", "")), "G2 partition_sum_invariant toplam==1.0")

    # ── report_grain
    rg = spec.get("report_grain", {})
    _check(R, rg.get("grain") == ["tenant_id", "agent_id", "agent_version_id", "period"],
           "rapor grain OLAP mv_call_daily ile hizalı")
    _check(R, rg.get("group_key") == ["agent_id", "agent_version_id", "period"], "group_key tanımlı")
    _check(R, rg.get("produces_overall") is True, "overall rollup üretilir")

    # ── small_sample (G6)
    ss = spec.get("small_sample", {})
    _check(R, isinstance(ss.get("min_group_n"), int) and ss.get("min_group_n") >= 2,
           "G6 min_group_n ≥ 2 (k-anon + istatistik)")
    _check(R, ss.get("suppressed_status") and ss.get("published_status"), "G6 bastırma/yayım statüleri tanımlı")

    # ── target (I13 soft)
    tg = spec.get("target", {})
    _check(R, isinstance(tg.get("containment_target"), (int, float)) and 0.0 < tg.get("containment_target") < 1.0,
           "I13 containment_target ∈ (0,1) (BRD §3.2.1 %60)")
    _check(R, tg.get("soft") is True, "I13 target SOFT (HARD kapı değil)")

    # ── output_contract (G8)
    oc = spec.get("output_contract", {})
    _check(R, set(oc.get("group_fields", [])) == {"agent_id", "agent_version_id", "period"},
           "output group_fields == group_key")
    _check(R, {"containment_rate", "transfer_rate"} <= set(oc.get("metric_fields", [])),
           "G2 metric_fields containment_rate/transfer_rate içerir (FR-ANA-003)")
    _check(R, {"tenant_id", "report_id", "schema_version"} <= set(oc.get("identity_fields", [])),
           "G7 identity_fields tenant_id/report_id/schema_version içerir")
    _check(R, any("mv_call_daily" in p for p in oc.get("persists_to", [])),
           "output persists_to mv_call_daily (OLAP rollup)")

    # ── idempotency (G5)
    idem = spec.get("idempotency", {})
    _check(R, idem.get("dedup_key") == ["tenant_id", "call_id"], "G5 dedup_key == (tenant_id, call_id)")
    _check(R, idem.get("replay_safe") is True, "G5 replay_safe (1.1.8 P3)")

    # ── feature_policy (G8)
    fp = spec.get("feature_policy", {})
    allowed = set(fp.get("allowed_input_keys", []))
    forb = set(fp.get("forbidden_input_keys", []))
    _check(R, {"call_id", "outcome", "agent_id", "agent_version_id", "period"} <= allowed,
           "G8 allowed_input_keys çekirdek alanları içerir")
    _check(R, {"transcript_text", "audio_payload", "phone_number", "card_number"} <= forb,
           "G8 forbidden_input_keys ham transkript/ses/PII anahtarlarını içerir")
    _check(R, not (allowed & forb), "G8 izinli ile yasak girdi kesişmez")

    # ── isolation (G7)
    iso = spec.get("isolation", {})
    _check(R, iso.get("tenant_id_required") is True, "G7 tenant_id_required")
    _check(R, iso.get("residency") == "home-region", "G7 residency home-region (NFR 10.7)")
    _check(R, iso.get("cross_tenant_forbidden") is True, "G7 cross_tenant_forbidden (FR-TEN-002)")

    # ── 14.2.2 derivation BİREBİR (G4, non-circular)
    der = _load_sibling_spec("runtime", "call-derivation", "derivation-spec.json")
    if der is not None:
        dvocab = der.get("vocabularies", {}).get("outcome", [])
        _check(R, set(dvocab) == set(allo),
               "G4 outcome 14.2.2 derivation-spec.json vocabularies.outcome ile BİREBİR (%s)" % ",".join(sorted(dvocab)))
        _check(R, der.get("output_contract", {}).get("result_field") == "outcome",
               "G4 14.2.2 result_field == outcome (bu motorun agregasyon kaynağı)")

    # ── OLAP fct_call/mv_call_daily BİREBİR (G4, non-circular)
    olap = _load_sibling_spec("analytics", "olap-spec.json")
    if olap is not None:
        ft = _fct_call(olap)
        _check(R, ft is not None, "G4 OLAP fct_call fact table mevcut")
        if ft is not None:
            cols = {c.get("name"): c for c in ft.get("columns", [])}
            for col in ("contained", "transferred"):
                _check(R, col in cols and "FR-ANA-003" in (cols[col].get("note") or "")
                       and cols[col].get("pii_class") == "low",
                       "G4 fct_call.%s mevcut + FR-ANA-003 + pii_class low (boolean materyalizasyonu)" % col)
            _check(R, "FR-ANA-003" in ft.get("fr", []), "G4 OLAP fct_call FR-ANA-003 taşır")
        mv = _rollup(olap, "mv_call_daily")
        _check(R, mv is not None, "G2 OLAP rollup mv_call_daily mevcut")
        if mv is not None:
            _check(R, {"containment_rate", "transfer_rate"} <= set(mv.get("metrics", [])),
                   "G2 mv_call_daily containment_rate/transfer_rate metrikleri (FR-ANA-003)")
            _check(R, {"contained_calls", "transferred_calls", "calls"} <= set(mv.get("metrics", [])),
                   "G1 mv_call_daily contained_calls/transferred_calls/calls (sayım kaynağı)")
            _check(R, "FR-ANA-003" in mv.get("dashboard_fr", []), "G2 mv_call_daily dashboard_fr FR-ANA-003")
            _check(R, mv.get("source") == "fct_call", "mv_call_daily source == fct_call")

    # ── gates
    g = spec.get("gates", {})
    for gk in ("max_partition_gap", "max_rate_bound_violation", "max_exclusivity_violation", "max_vocab_violation",
               "max_idempotency_violation", "max_suppression_violation", "max_isolation_violation",
               "max_pii_violation", "max_blocking_violation"):
        _check(R, g.get(gk, -1) == 0, "gate %s = 0" % gk)

    # ── error taxonomy (I12)
    et = spec.get("error_taxonomy", {}).get("mapping", {})
    _check(R, len(et) >= 3, "I12 hata eşlemesi (≥3)")
    _check(R, all(v in ERROR_TAXONOMY for v in et.values()), "I12 tüm hedefler API §11.6 ErrorTaxonomy'de")
    _check(R, et.get("malformed_report") == "INVALID_REQUEST" and et.get("unknown_outcome") == "INVALID_REQUEST"
           and et.get("region_mismatch") == "REGION_VIOLATION",
           "I12 malformed/unknown→INVALID_REQUEST, region→REGION_VIOLATION")

    # ── pii (spec sağlığı, I15)
    _check(R, spec.get("pii", {}).get("raw_payload_in_spec_forbidden") is True, "I15 ham ses payload spec'te yasak")
    _check(R, spec.get("pii", {}).get("transcript_in_spec_forbidden") is True, "I15 transkript spec'te yasak")
    _check(R, spec.get("pii", {}).get("pii_values_in_spec_forbidden") is True, "I15 PII DEĞERİ spec'te yasak")

    # ── invariant kataloğu
    inv_ids = [i.get("id") for i in spec.get("invariants", [])]
    _check(R, len(inv_ids) == len(set(inv_ids)) and len(inv_ids) >= 15, "invariant kataloğu ≥15 + tekil ID")
    _check(R, all(i.get("trace") for i in spec.get("invariants", [])), "her invariant trace taşır")

    # ── literal sır + PII DEĞER taraması (spec + config)
    hits = _scan(spec, SECRET_RE)
    pii_hits = _scan(spec, PII_VALUE_RE)
    if os.path.exists(PROFILES_CFG):
        cfg = _load(PROFILES_CFG)
        hits += _scan(cfg, SECRET_RE)
        pii_hits += _scan(cfg, PII_VALUE_RE)
    _check(R, not hits, "I15 literal sır yok (spec+config)")
    _check(R, not pii_hits, "I15 spec/config'te ham PII DEĞERİ yok (%s)" % (",".join(p for p, _ in pii_hits[:3]) or "-"))

    # ── config profilleri
    if os.path.exists(PROFILES_CFG):
        cfg = _load(PROFILES_CFG)
        profs = cfg.get("profiles", [])
        _check(R, len(profs) >= 2, "config ≥2 profil")
        pnames = [p.get("name") for p in profs]
        _check(R, len(pnames) == len(set(pnames)), "config profil isimleri benzersiz")
        for p in profs:
            _check(R, bool(p.get("region")), "residency config %s bölge pini var" % p.get("name"))
            _check(R, isinstance(p.get("schema_version"), int) and p.get("schema_version") > 0,
                   "config %s schema_version > 0 (idempotency)" % p.get("name"))
            _check(R, isinstance(p.get("min_group_n"), int) and p.get("min_group_n") >= 2,
                   "config %s min_group_n ≥ 2 (k-anon)" % p.get("name"))

    passed = sum(1 for ok, _ in R if ok)
    total = len(R)
    for ok, label in R:
        if not ok:
            print("  ✗ %s" % label)
    print("validate: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


# ─────────────────────────────────────────────────────────────────────────────
# selftest
# ─────────────────────────────────────────────────────────────────────────────
CONTEXT = {"tenant_id": "t_acme", "region": "eu-west-1", "correlation_id": "corr-acme-001"}
PROFILE = {"name": "eu-standard", "region": "eu-west-1", "schema_version": 1, "min_group_n": 4,
           "containment_target": 0.60}


def _calls(spec_n_contained, n_transferred, n_abandoned, n_unresolved, n_not_connected,
           agent="ag1", ver="v1", period="2026-06-01", start=0):
    """Tek grupta verilen outcome dağılımına sahip çağrı seti üretir (deterministik call_id)."""
    rows = []
    i = start
    plan = (["contained"] * spec_n_contained + ["transferred_to_human"] * n_transferred
            + ["abandoned"] * n_abandoned + ["unresolved"] * n_unresolved
            + ["not_connected"] * n_not_connected)
    for oc in plan:
        rows.append({"call_id": "c%d" % i, "outcome": oc, "agent_id": agent,
                     "agent_version_id": ver, "period": period})
        i += 1
    return rows


def _run(calls, spec, context=None, profile=None, **pol_over):
    pol = _full_pol()
    pol.update(pol_over)
    prof = dict(profile or PROFILE)
    if not pol.get("correct_denom", True):
        prof["denominator_basis"] = "total"
    return report_calls({"calls": calls}, spec, prof, context or CONTEXT, pol)


def _raises(fn):
    try:
        fn()
        return False
    except ReportError:
        return True


def selftest():
    spec = _load(SPEC_PATH)
    cases = []

    def case(ok, label):
        cases.append((bool(ok), label))

    case(_validate_obj(_load(SPEC_PATH)) == 0, "validate iyi spec+config'te 0 döndürür")

    # ── happy: 6 contained + 3 transferred + 1 abandoned + 0 unresolved + 2 not_connected (handled=10) ──
    calls = _calls(6, 3, 1, 0, 2)
    mh = _run(calls, spec)
    ov = mh["derived"]["overall"]
    case(all(m[k] == 0 for m in [mh] for k in (
        "partition_gap", "rate_bound_violations", "exclusivity_violations", "vocab_violations",
        "idempotency_violations", "suppression_violations", "isolation_violations",
        "pii_violations", "blocking_violations")), "happy: tüm ihlal sayaçları 0")
    case(all(ok for ok, _ in evaluate(spec, mh)), "happy tüm kapıları geçer")
    case(ov["handled"] == 10 and ov["calls"] == 12, "happy: handled=10 (not_connected hariç), calls=12")
    case(abs(ov["containment_rate"] - 0.6) < 1e-9, "happy: containment_rate = 6/10 = 0.60")
    case(abs(ov["transfer_rate"] - 0.3) < 1e-9, "happy: transfer_rate = 3/10 = 0.30")
    case(abs(ov["not_connected_rate"] - (2 / 12)) < 1e-6, "happy: not_connected_rate = 2/12 (total payda)")
    # partisyon toplamı == 1.0
    psum = ov["containment_rate"] + ov["transfer_rate"] + ov["abandon_rate"] + ov["unresolved_rate"]
    case(abs(psum - 1.0) < 1e-9, "happy: 4 partisyon oranı toplamı == 1.0 (payda bütünlüğü)")
    case(ov["target_met"] is True, "happy: containment 0.60 ≥ hedef 0.60 → target_met (SOFT)")

    # ── G1 partisyon: counted == input ──
    case(mh["derived"]["counted_total"] == mh["derived"]["input_count"] == 12,
         "G1 sayılan == girdi == 12 (partisyon tam; düşme/çift yok)")

    # ── determinizm ──
    case(_run(calls, spec) == _run(calls, spec), "determinizm: aynı çağrı seti aynı oran (random yok)")

    # ── çok-grup: agent_version karşılaştırması (FR-ANA-010 girdisi) ──
    multi = _calls(8, 2, 0, 0, 0, ver="v1", start=0) + _calls(4, 6, 0, 0, 0, ver="v2", start=100)
    mm = _run(multi, spec)
    case(mm["derived"]["groups"] == 2, "çok-grup: 2 agent_version grubu")
    rows = {gk: gm for gk, gm in mm["derived"]["rows"]}
    v1 = rows[("ag1", "v1", "2026-06-01")]
    v2 = rows[("ag1", "v2", "2026-06-01")]
    case(abs(v1["containment_rate"] - 0.8) < 1e-9 and abs(v2["containment_rate"] - 0.4) < 1e-9,
         "çok-grup: v1 containment 0.80 > v2 0.40 (sürüm karşılaştırması)")
    case(abs(mm["derived"]["overall"]["containment_rate"] - 0.6) < 1e-9,
         "çok-grup: overall containment = 12/20 = 0.60 (grup toplamı)")

    # ── G1 partition_all KAPALI → bilinmeyen/handled-dışı düşürülür ──
    m1 = _run(_calls(5, 0, 0, 0, 3, agent="ag1", ver="v1"), spec, partition_all=False)
    case(m1["partition_gap"] >= 1, "partition_all KAPALI: not_connected sessizce düşürülür → G1 partisyon açığı eler")

    # ── G2 correct_denom KAPALI → payda=total → partisyon toplamı ≠ 1.0 ──
    m2 = _run(_calls(6, 2, 1, 1, 4), spec, correct_denom=False)
    case(m2["rate_bound_violations"] >= 1, "correct_denom KAPALI: payda=total (not_connected dahil) → partisyon toplamı ≠1.0 → G2 eler")
    ov2 = m2["derived"]["overall"]
    case(abs(ov2["containment_rate"] - (6 / 14)) < 1e-4, "correct_denom KAPALI: containment 6/14 (yanlış payda yapay düşer)")

    # ── G3 exclusive_buckets KAPALI → contained çift sayılır ──
    m3 = _run(_calls(5, 1, 0, 0, 0), spec, exclusive_buckets=False)
    case(m3["exclusivity_violations"] >= 1, "exclusive_buckets KAPALI: contained transferred'a da sayılır → G3 eler")

    # ── G4 closed_vocab: bilinmeyen outcome ──
    bad = [{"call_id": "x", "outcome": "made_up_outcome", "agent_id": "ag1", "agent_version_id": "v1", "period": "p"}]
    m4 = _run(_calls(5, 0, 0, 0, 0) + bad, spec)
    case(m4["vocab_violations"] >= 1, "bilinmeyen outcome → G4 sözlük eler (14.2.2 vocab BİREBİR)")

    # ── G5 idempotency: replay (aynı call_id) ──
    dup = _calls(5, 0, 0, 0, 0) + [{"call_id": "c0", "outcome": "contained", "agent_id": "ag1",
                                    "agent_version_id": "v1", "period": "2026-06-01"}]
    m5 = _run(dup, spec, idempotent=False)
    case(m5["idempotency_violations"] >= 1, "idempotent KAPALI: aynı (tenant,call_id) çift-sayım → G5 eler")
    m5o = _run(dup, spec)
    case(m5o["idempotency_violations"] == 0 and m5o["derived"]["input_count"] == 5,
         "idempotent AÇIK: replay daraltılır (5 sayım) → G5 geçer")

    # ── G6 küçük-örnek bastırma ──
    small = _calls(2, 1, 0, 0, 0)        # handled=3 < min_group_n=4
    m6 = _run(small, spec)
    g6row = m6["derived"]["rows"][0][1]
    case(g6row["status"] == "insufficient_sample" and m6["derived"]["suppressed_groups"] == 1,
         "G6 handled<min_group_n → insufficient_sample (bastırılır, sessizce düşmez)")
    case(g6row["target_met"] is None, "G6 bastırılan grupta target_met yayımlanmaz (None)")
    m6b = _run(small, spec, suppress_small=False)
    case(m6b["suppression_violations"] >= 1, "suppress_small KAPALI: küçük grup oranı yayımlanır → G6 eler (k-anon)")

    # ── G7 izolasyon: cross-tenant + residency ──
    cross = _calls(5, 0, 0, 0, 0) + [{"call_id": "ct", "outcome": "contained", "tenant_id": "t_other",
                                      "agent_id": "ag1", "agent_version_id": "v1", "period": "2026-06-01"}]
    m7 = _run(cross, spec)
    case(m7["isolation_violations"] >= 1, "cross-tenant çağrı (t_other) → G7 izolasyon eler")
    case(m7["derived"]["input_count"] == 5, "cross-tenant çağrı agregasyona KARIŞMAZ (izole edilir)")
    resd = _calls(5, 0, 0, 0, 0) + [{"call_id": "rd", "outcome": "contained", "region": "us-east-1",
                                     "agent_id": "ag1", "agent_version_id": "v1", "period": "2026-06-01"}]
    m7r = _run(resd, spec)
    case(m7r["isolation_violations"] >= 1, "home-region dışı çağrı (residency) → G7 eler (NFR 10.7)")

    # ── G8 PII: ham transkript/PII DEĞERİ girdi ──
    leak = [{"call_id": "p", "outcome": "contained", "agent_id": "ag1", "agent_version_id": "v1",
             "period": "p", "transcript_text": "müşteri konuştu"}]
    m8 = _run(_calls(5, 0, 0, 0, 0) + leak, spec, enforce_redaction=False)
    case(m8["pii_violations"] == 0, "enforce_redaction KAPALI: redaction zorlanmaz (denetlenmez)")
    m8e = _run(_calls(5, 0, 0, 0, 0) + leak, spec)
    case(m8e["pii_violations"] >= 1, "enforce_redaction AÇIK: transcript_text yasak girdi → G8 eler")
    leakv = [{"call_id": "pv", "outcome": "contained", "agent_id": "0555 123 4567",
              "agent_version_id": "v1", "period": "p"}]
    m8v = _run(_calls(5, 0, 0, 0, 0) + leakv, spec)
    case(m8v["pii_violations"] >= 1, "boyut DEĞERİnde ham telefon → G8 eler")

    # ── G9 blocking: non_blocking KAPALI ──
    m9 = _run(_calls(5, 0, 0, 0, 0), spec, non_blocking=False)
    case(m9["blocking_violations"] >= 1, "non_blocking KAPALI: rapor çağrıyı bloklar → G9 eler (FR-RES-011)")

    # ── reddetme (I12) ──
    case(_raises(lambda: report_calls({"calls": "x"}, spec, PROFILE, CONTEXT, _full_pol())),
         "I12 calls liste değil → reddedilir")
    case(_raises(lambda: report_calls({"calls": [{"call_id": "z"}]}, spec, PROFILE, CONTEXT, _full_pol())),
         "I12 çağrıda outcome eksik → reddedilir")
    case(_raises(lambda: ContainmentReportEngine(spec, PROFILE, {"region": "eu"}, _full_pol())),
         "I12 bağlam (tenant_id) eksik → reddedilir")

    # ── containment hedef altı → target_met False ama kapı GEÇER (target SOFT, I13) ──
    low = _calls(2, 6, 1, 1, 0)          # containment 2/10 = 0.20 < 0.60
    ml = _run(low, spec)
    case(ml["derived"]["overall"]["target_met"] is False, "containment 0.20 < hedef → target_met False")
    case(all(ok for ok, _ in evaluate(spec, ml)), "I13 target altı YİNE kapıları geçer (target SOFT, hesap doğru)")

    # ── validate negatif kapılar ──
    s = json.loads(json.dumps(spec)); s["denominator"]["basis"] = "total"
    case(_validate_obj(s) != 0, "I11 denominator.basis total'a sapar → validate eler")
    s = json.loads(json.dumps(spec)); s["outcome_vocabulary"]["all_outcomes"] = ["contained", "transferred_to_human"]
    case(_validate_obj(s) != 0, "G4 all_outcomes 14.2.2 vocab'tan sapar → validate eler")
    s = json.loads(json.dumps(spec)); s["outcome_vocabulary"]["handled_outcomes"].append("not_connected")
    case(_validate_obj(s) != 0, "G4 handled'a not_connected eklenir (handled∩not_handled≠∅) → validate eler")
    s = json.loads(json.dumps(spec)); s["small_sample"]["min_group_n"] = 1
    case(_validate_obj(s) != 0, "G6 min_group_n < 2 (k-anon yetersiz) → validate eler")
    s = json.loads(json.dumps(spec)); s["target"]["soft"] = False
    case(_validate_obj(s) != 0, "I13 target.soft=False → validate eler (target HARD olamaz)")
    s = json.loads(json.dumps(spec)); s["feature_policy"]["allowed_input_keys"].append("transcript_text")
    case(_validate_obj(s) != 0, "G8 izinli girdiye transcript_text → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_rate_bound_violation"] = 1
    case(_validate_obj(s) != 0, "G2 max_rate_bound_violation>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["error_taxonomy"]["mapping"]["x"] = "NOPE"
    case(_validate_obj(s) != 0, "I12 taksonomi-dışı → validate eler")
    s = json.loads(json.dumps(spec)); s["denominator"]["leak"] = "0555 123 4567"
    case(_validate_obj(s) != 0, "I15 spec'te ham PII DEĞERİ (telefon) → validate eler")
    s = json.loads(json.dumps(spec)); s["denominator"]["secret"] = "api_key: AKIAIOSFODNN7EXAMPLE"
    case(_validate_obj(s) != 0, "I15 literal secret → validate eler")

    passed = sum(1 for ok, _ in cases if ok)
    total = len(cases)
    for ok, label in cases:
        print("  %s %s" % ("✓" if ok else "✗", label))
    print("selftest: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


def _validate_obj(spec_obj):
    import io
    import contextlib
    tmp = os.path.join(HERE, ".._tmp_spec.json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(spec_obj, f)
    global SPEC_PATH
    orig = SPEC_PATH
    SPEC_PATH = tmp
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            rc = validate()
    finally:
        SPEC_PATH = orig
        os.remove(tmp)
    return rc


def schema():
    print("""containment-report-spec.json beklenen şekli (WBS 14.2.3):
  wbs=14.2.3, version, phase=F1, priority=Must, eval_doc{fr,srs,rtm,brd,sad,db,olap,adr,api,upstream}
  placement{in_analytics_plane, async_batch, non_blocking, from_redacted_content, aggregates_labels=true,
            deterministic, idempotent, from_trace=false}                                          (G9,G8)
  outcome_vocabulary{all_outcomes[5], handled_outcomes[4], not_handled_outcomes=[not_connected],
                     bucket_of{}, partition_buckets[4]}                                            (G4,G2)
  denominator{basis=handled, containment_rate=contained/handled, transfer_rate=transferred/handled,
              partition_sum_invariant(==1.0), not_connected_excluded_from_handled, rate_bounds[0,1]} (G2,I11)
  report_grain{grain[tenant,agent,agent_version,period], group_key[3], produces_overall}
  small_sample{min_group_n, suppressed_status, published_status}                                   (G6)
  target{containment_target(0.60), soft=true}                                                      (I13 SOFT)
  output_contract{group_fields[3], metric_fields[containment_rate,transfer_rate,...],
                  identity_fields[tenant_id,report_id,schema_version], persists_to[mv_call_daily]}  (G2,G7,G8)
  idempotency{dedup_key=[tenant_id,call_id], replay_safe=true}                                      (G5)
  feature_policy{allowed_input_keys[], forbidden_input_keys[]}                                      (G8)
  isolation{tenant_id_required, residency=home-region, cross_tenant_forbidden}                      (G7)
  gates{max_partition_gap=0, max_rate_bound_violation=0, max_exclusivity_violation=0, max_vocab_violation=0,
        max_idempotency_violation=0, max_suppression_violation=0, max_isolation_violation=0,
        max_pii_violation=0, max_blocking_violation=0}                                              (G1..G9)
  error_taxonomy{mapping→API §11.6}  pii{...}  invariants[≥15]{id,desc,trace}

config/containment-report-profiles.json: profiles[]{name, region, schema_version, min_group_n, containment_target}

report sample: {name, profile | profile_obj, expect, expected?{metrik}, expected_overall?{oran},
  context{tenant_id, region?},
  policy?{partition_all, exclusive_buckets, correct_denom, closed_vocab, idempotent, suppress_small,
          isolate_tenant, enforce_redaction, non_blocking},
  calls[]{call_id, outcome(14.2.2 etiketi), agent_id?, agent_version_id?, period?, tenant_id?, region?}}
  (PII DEĞERİ / ham transkript YOK — yalnız redaksiyonlu outcome etiketi + düşük-kardinalite boyut/kimlik ADLARI)

komutlar: validate | report <sample.json> | selftest | schema""")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if cmd == "validate":
        return validate()
    if cmd == "report":
        if len(sys.argv) < 3:
            print("kullanım: containment_report_probe.py report <sample.json>")
            return 2
        return report_cmd(sys.argv[2])
    if cmd == "selftest":
        return selftest()
    if cmd == "schema":
        return schema()
    print("bilinmeyen komut: %s (validate|report|selftest|schema)" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main())
