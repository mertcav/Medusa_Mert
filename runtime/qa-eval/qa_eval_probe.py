#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qa_eval_probe.py — WBS 14.2.1 Otomatik kalite değerlendirme (tüm çağrılar)

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only statik + davranış kapısı.
`runtime/call-alarms/` (14.1.5) probe disipliniyle birebir; burada deterministik bir ANALYTICS-PLANE
QA/EVAL ENGINE (SAD §164 'QA/Eval Engine'; SAD §4.2 async batch) simülatörü (saf; random YOK).

QA/EVAL ENGINE — Analytics/Ops Plane'de (SAD §4.2/§171, FR-RES-011) async/non-blocking; event stream
(qa.evaluation.v1) üzerinden PII-redaksiyonlu içerikle çalışır, TÜM çağrılara deterministik kalite
skorkartı uygular ve sonucu call_evaluation (DB.md §5.6) + OLAP fct_qa_evaluation ile yayımlar:
  • Kapsam (G1):        her UYGUN tamamlanmış çağrı → tam bir otomatik değerlendirme (%100; FR-ANA-001/SR-ANA-001) — BİRİNCİL.
  • Katalog (G2):       çıktı skor alanları OLAP fct_qa_evaluation auto_score + score_* ile BİREBİR (non-circular).
  • Skor-alanı (G3):    her boyut + composite ∈ [0,1]; ağırlık toplamı=1.0; composite=ağırlıklı toplam (aritmetik).
  • İdempotent (G4):    (tenant_id,call_id,schema_version) daraltılır; at-least-once çift skor üretmez (replay-safe).
  • Async (G5):         analytics plane'de non-blocking; QA başarısızlığı canlı çağrıyı etkilemez (placement).
  • PII (G6):           yalnız redaksiyonlu öznitelik; ham transkript/ses/PII DEĞERİ yok (FR-REC-004).
  • İzolasyon (G7):     her değerlendirme tenant_id taşır + cross-tenant öznitelik yok + residency (FR-TEN-002/NFR 10.7).
  • Uygunluk (G8):      uygun-olmayan statü açık reason_code taşır (sessiz atlama yok) — kapsam bütünlüğü.

KAPSAM AYRIMI: intent/disposition → 14.2.2 · containment/transfer oranı → 14.2.3 · yanlış-bilgi/tool-hata/
güvenlik İŞARETİ → 14.2.4 · kritik işaretleme → 14.2.5 · MANUEL skor+yorum → 14.2.6 · sürüm karşılaştırma →
14.2.7. Burada YALNIZ otomatik skorkart motoru + %100 kapsam disiplini.

Komutlar:
  validate              qa-eval-spec.json'ı invariant'lara + OLAP/eventstream çapraz-tutarlılığa + config'e karşı doğrular.
  evaluate <sample>     Deterministik QaEvalEngine — çağrı seti → üretilen değerlendirme + kapsam + HARD kapılar (G1–G8); →çıkış kodu.
  selftest              İyi/kötü spec+sample ile kapıların doğru tetiklendiğini kanıtlar.
  schema                Beklenen spec şeklini özetler.

Sunucu/credential GEREKMEZ. evaluate gerçek QA/Eval Engine yerine deterministik simülasyondur (canlıda
event stream consumer + redaction pipeline + OLAP sink, SAD §4.2/§12.1; ADR-007). Ham ses payload/transkript
METNİ/PII DEĞERİ YOK — örnekler yalnız REDAKSİYONLU öznitelik + alan/kimlik anahtarı ADLARI taşır.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "qa-eval-spec.json")
PROFILES_CFG = os.path.join(HERE, "config", "qa-eval-profiles.json")
EPS = 1e-9

ERROR_TAXONOMY = {
    "TIMEOUT", "RATE_LIMITED", "UNAVAILABLE", "AUTH",
    "INVALID_REQUEST", "CONTENT_FILTERED", "QUOTA_EXCEEDED", "REGION_VIOLATION",
}
SECRET_RE = re.compile(
    r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer)\b\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}"
)
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")
# Ham PII DEĞER desenleri (öznitelik/skor/çıktıda yasak — FR-REC-004). Yalnız anahtar ADI olmalı.
PII_VALUE_RE = re.compile(
    r"(?:\d[ \-]?){7,}"                                   # ≥7 ardışık rakam (telefon/kart/IBAN)
    r"|[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"  # e-posta
    r"|\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b"                  # IBAN
)


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_placeholder(v):
    return isinstance(v, str) and PLACEHOLDER_RE.match(v) is not None


def _clamp01(x):
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)


class QaEvalError(Exception):
    """Geçersiz/eksik çağrı kaydı veya bilinmeyen statü — sessizce kabul yok, reddet (I10)."""


# ─────────────────────────────────────────────────────────────────────────────
# Deterministik kalite skorkartı (saf aritmetik; random YOK)
# ─────────────────────────────────────────────────────────────────────────────
def score_accuracy(f):
    total = max(0, int(f.get("total_answers", 0)))
    grounded = max(0, int(f.get("grounded_answers", 0)))
    if total <= 0:
        return 1.0                      # faktif iddia yok → yanlışlık yok
    return min(grounded, total) / total


def score_compliance(f, clamp=True):
    s = 1.0
    if not bool(f.get("disclosure_given", False)):
        s -= 0.5                        # AI disclosure verilmedi (BRD §14.2)
    if bool(f.get("consent_required", False)) and not bool(f.get("consent_verified", False)):
        s -= 0.3                        # gerekli consent doğrulanmadı (FR-OUT-001)
    s -= 0.2 * max(0, int(f.get("policy_violations", 0)))
    return _clamp01(s) if clamp else s


def score_helpfulness(f, clamp=True):
    if bool(f.get("resolved", False)):
        base = 1.0
    elif bool(f.get("unresolved_handoff", False)):
        base = 0.6                      # uygun insan aktarımı (kontrollü)
    else:
        base = 0.2                      # çözümsüz, aktarım da yok
    dead = min(0.3, 0.1 * max(0, int(f.get("dead_air_events", 0))))
    bt = max(0, int(f.get("barge_in_total", 0)))
    br = max(0, int(f.get("barge_in_respected", 0)))
    barge_pen = 0.2 * (1.0 - min(1.0, br / bt)) if bt > 0 else 0.0
    s = base - dead - barge_pen
    return _clamp01(s) if clamp else s


DIM_FUNCS = {"accuracy": score_accuracy, "compliance": score_compliance, "helpfulness": score_helpfulness}


# ─────────────────────────────────────────────────────────────────────────────
# QA/Eval Engine — otomatik kalite değerlendirmesi (deterministik)
# ─────────────────────────────────────────────────────────────────────────────
class QaEvalEngine:
    """SAD §164 QA/Eval Engine. Analytics plane'de async/non-blocking; redaksiyonlu öznitelikten
    deterministik skorkart üretir + %100 kapsam + idempotency + skor-alanı + PII + tenant izolasyon +
    uygunluk disiplinine karşı denetler. Saf; random YOK.

    policy bayrakları buggy bir Engine'i simüle eder (call-alarms deseni):
      evaluate_all       : her uygun çağrıyı değerlendir (kapalı → degraded/uygun çağrı atlanır, G1 kapsam)
      map_output         : tüm skor alanlarını çıktıya yaz (kapalı → bir score alanı düşer, G2 katalog)
      clamp_scores       : skorları [0,1]'e sıkıştır (kapalı → negatif compliance → G3 skor-alanı)
      honor_weights      : rubric ağırlıklarını kullan (kapalı → ağırlık toplamı≠1 → composite drift, G3)
      idempotent         : (tenant,call,ver) daralt (kapalı → çift değerlendirme, G4)
      non_blocking       : analytics plane non-blocking (kapalı → QA çağrıyı bloklar, G5)
      enforce_redaction  : ham PII/transkript özniteliğini reddet (kapalı → transcript_text geçer, G6)
      isolate_tenant     : değerlendirmeye tenant_id ekle (kapalı → tenant_id yok / cross-tenant, G7)
      account_excluded   : uygun-olmayan çağrının reason_code'unu denetle (kapalı → sessiz atlama, G8)
    """

    def __init__(self, spec, profile, context, policy):
        self.spec = spec
        self.context = dict(context or {})
        self.pol = policy

        self.evaluable = set(spec.get("eligibility", {}).get("evaluable_status", []))
        self.excluded = set(spec.get("eligibility", {}).get("excluded_status", []))
        self.reason_codes = set(spec.get("eligibility", {}).get("reason_codes", []))

        rub = spec.get("rubric", {})
        self.dims = rub.get("dimensions", [])
        self.weights = {d["name"]: d["weight"] for d in self.dims}
        self.dim_cols = {d["name"]: d["output_column"] for d in self.dims}
        self.composite_col = rub.get("composite_column", "auto_score")
        self.domain = rub.get("score_domain", [0.0, 1.0])

        oc = spec.get("output_contract", {})
        self.score_fields = list(oc.get("score_fields", []))
        self.identity_fields = list(oc.get("identity_fields", []))

        fp = spec.get("feature_policy", {})
        self.allowed_features = set(fp.get("allowed_feature_keys", []))
        self.forbidden_features = set(fp.get("forbidden_feature_keys", []))

        self.dedup_key = spec.get("idempotency", {}).get("dedup_key", ["tenant_id", "call_id", "schema_version"])
        self.region_pin = profile.get("region")
        self.schema_version = profile.get("schema_version", 1)

        if not self.context.get("tenant_id"):
            raise QaEvalError("değerlendirme bağlamı eksik: tenant_id → INVALID_REQUEST")
        if not self.context.get("region"):
            raise QaEvalError("değerlendirme bağlamı eksik: region → INVALID_REQUEST")

        # sayaçlar (HARD kapı kanıtı)
        self.coverage_gap = 0
        self.catalog_mismatch = 0
        self.score_domain_violations = 0
        self.idempotency_violations = 0
        self.blocking_violations = 0
        self.pii_violations = 0
        self.isolation_violations = 0
        self.eligibility_reason_missing = 0

        self.eligible = 0
        self.produced = 0
        self.degraded = 0
        self.evaluations = []          # üretilen değerlendirme satırları
        self.derived = {}

    # ── redaksiyonlu öznitelik denetimi (G6) ──────────────────────────────────
    def _check_features(self, features):
        if not self.pol.get("enforce_redaction", True):
            return                       # buggy: redaction zorlanmaz
        for k, v in (features or {}).items():
            if k in self.forbidden_features:
                self.pii_violations += 1
            elif k not in self.allowed_features:
                # whitelist dışı anahtar — bilinmeyen öznitelik (potansiyel ham içerik)
                self.pii_violations += 1
            if isinstance(v, str) and not _is_placeholder(v) and PII_VALUE_RE.search(v):
                self.pii_violations += 1   # ham PII DEĞERİ

    # ── tek çağrı → otomatik değerlendirme satırı ──────────────────────────────
    def _score_call(self, call):
        features = call.get("features", {}) or {}
        self._check_features(features)
        degraded = not features or call.get("degraded", False)

        dims = {}
        for d in self.dims:
            fn = DIM_FUNCS[d["name"]]
            if d["name"] == "accuracy":
                val = fn(features)
            else:
                val = fn(features, clamp=self.pol.get("clamp_scores", True))
            dims[d["name"]] = val

        # composite = ağırlıklı toplam
        weights = dict(self.weights)
        if not self.pol.get("honor_weights", True):
            # buggy: ağırlık ölçeklenir (toplam ≠ 1) → composite domain/aritmetik drift
            kk = sorted(weights)[0]
            weights[kk] = weights[kk] + 0.5
        # G3: efektif ağırlık toplamı = 1.0 olmalı (clamp drift'i maskeleyebilir; ağırlık ihlalini doğrudan yakala)
        if abs(sum(weights.values()) - 1.0) > 1e-9:
            self.score_domain_violations += 1
        composite = sum(weights[n] * dims[n] for n in dims)
        if self.pol.get("clamp_scores", True):
            composite = _clamp01(composite)

        # skor-alanı (G3): boyut + composite domain
        lo, hi = self.domain[0], self.domain[1]
        for n, v in dims.items():
            if v < lo - EPS or v > hi + EPS:
                self.score_domain_violations += 1
        if composite < lo - EPS or composite > hi + EPS:
            self.score_domain_violations += 1
        # composite = ağırlıklı toplam (saf aritmetik) — honor_weights AÇIK ve clamp gerekmiyorsa birebir
        if self.pol.get("honor_weights", True):
            expect = sum(self.weights[n] * dims[n] for n in dims)
            if self.pol.get("clamp_scores", True):
                expect = _clamp01(expect)
            if abs(expect - composite) > 1e-9:
                self.score_domain_violations += 1

        row = {self.composite_col: round(composite, 6)}
        for n, v in dims.items():
            row[self.dim_cols[n]] = round(v, 6)

        # katalog (G2): tüm score_fields çıktıda
        if not self.pol.get("map_output", True):
            row.pop(self.score_fields[-1], None)   # buggy: bir score alanı düşür
        for sf in self.score_fields:
            if sf not in row:
                self.catalog_mismatch += 1

        # kimlik + izolasyon (G7)
        row["call_id"] = call.get("call_id")
        row["schema_version"] = self.schema_version
        row["eval_type"] = self.spec.get("output_contract", {}).get("eval_type", "automatic")
        row["degraded"] = bool(degraded)
        if self.pol.get("isolate_tenant", True):
            row["tenant_id"] = self.context.get("tenant_id")
            row["region"] = self.region_pin
        else:
            pass                          # buggy: tenant_id yok (izolasyon ihlali)
        if "tenant_id" not in row:
            self.isolation_violations += 1
        # cross-tenant öznitelik: call'ın tenant'ı bağlamdan farklıysa
        ct = call.get("tenant_id")
        if ct is not None and ct != self.context.get("tenant_id"):
            self.isolation_violations += 1
        # residency: çağrı home-region dışıysa
        cr = call.get("region")
        if cr is not None and self.region_pin is not None and cr != self.region_pin:
            self.isolation_violations += 1

        if degraded:
            self.degraded += 1
        return row

    def run(self, calls):
        # G5 async/non-blocking (placement): QA çağrıyı bloklamaz
        if not self.pol.get("non_blocking", True):
            self.blocking_violations += 1
        if not self.spec.get("placement", {}).get("non_blocking", True):
            self.blocking_violations += 1

        seen = set()
        for call in calls:
            status = call.get("status")
            if status is None:
                raise QaEvalError("çağrı kaydında status eksik → INVALID_REQUEST")
            if status in self.evaluable:
                self.eligible += 1
                # idempotency (G4): (tenant_id, call_id, schema_version)
                key = (self.context.get("tenant_id"), call.get("call_id"), self.schema_version)
                if key in seen:
                    if self.pol.get("idempotent", True):
                        continue          # daraltılır (tek değerlendirme) — ihlal değil
                    else:
                        self.idempotency_violations += 1   # buggy: çift değerlendirme
                seen.add(key)
                # G1 kapsam: evaluate_all kapalıysa degraded/uygun çağrı atlanır
                if not self.pol.get("evaluate_all", True) and (not call.get("features") or call.get("degraded")):
                    continue              # buggy: sessizce atla → coverage_gap
                self.evaluations.append(self._score_call(call))
                self.produced += 1
            elif status in self.excluded:
                # G8 uygunluk: açık reason_code zorunlu (sessiz atlama yok)
                reason = call.get("reason")
                if not self.pol.get("account_excluded", True):
                    self.eligibility_reason_missing += 1   # buggy: sessiz atlama
                elif reason not in self.reason_codes:
                    self.eligibility_reason_missing += 1
            else:
                raise QaEvalError("bilinmeyen çağrı statüsü: %s → INVALID_REQUEST" % status)

        # G1 kapsam: üretilen == uygun
        self.coverage_gap = self.eligible - self.produced if self.eligible >= self.produced else 0

        self.derived["eligible"] = self.eligible
        self.derived["produced"] = self.produced
        self.derived["degraded"] = self.degraded
        self.derived["coverage_ratio"] = (self.produced / self.eligible) if self.eligible else 1.0
        self.derived["dedup_groups"] = len(seen)

    def metrics(self):
        return {
            "coverage_gap": self.coverage_gap,
            "catalog_mismatch": self.catalog_mismatch,
            "score_domain_violations": self.score_domain_violations,
            "idempotency_violations": self.idempotency_violations,
            "blocking_violations": self.blocking_violations,
            "pii_violations": self.pii_violations,
            "isolation_violations": self.isolation_violations,
            "eligibility_reason_missing": self.eligibility_reason_missing,
            "produced": self.produced,
            "eligible": self.eligible,
            "evaluations": list(self.evaluations),
            "derived": dict(self.derived),
        }


def evaluate_call(sample, spec, profile, context, policy):
    calls = sample.get("calls")
    if not isinstance(calls, list):
        raise QaEvalError("çağrı seti (calls) liste değil → INVALID_REQUEST")
    for c in calls:
        if not isinstance(c, dict):
            raise QaEvalError("çağrı kaydı sözlük değil → INVALID_REQUEST")
    eng = QaEvalEngine(spec, profile, context, policy)
    eng.run(calls)
    return eng.metrics()


def evaluate(spec, m):
    """Metrikleri HARD kapılara (G1–G8) karşı değerlendirir. Döner findings[(ok, label)]."""
    g = spec.get("gates", {})
    d = m.get("derived", {})
    F = []
    F.append((m.get("coverage_gap", 0) <= g.get("max_coverage_gap", 0),
              "G1 kapsam açığı %d ≤ %d (üretilen %d / uygun %d = %.3f — FR-ANA-001/SR-ANA-001 %%100) — BİRİNCİL"
              % (m.get("coverage_gap", 0), g.get("max_coverage_gap", 0),
                 d.get("produced", 0), d.get("eligible", 0), d.get("coverage_ratio", 1.0))))
    F.append((m.get("catalog_mismatch", 0) <= g.get("max_catalog_mismatch", 0),
              "G2 katalog uyuşmazlığı %d ≤ %d (çıktı skor alanları OLAP fct_qa_evaluation auto_score+score_* BİREBİR)"
              % (m.get("catalog_mismatch", 0), g.get("max_catalog_mismatch", 0))))
    F.append((m.get("score_domain_violations", 0) <= g.get("max_score_domain_violation", 0),
              "G3 skor-alanı ihlali %d ≤ %d (her boyut+composite ∈ [0,1]; composite=ağırlıklı toplam)"
              % (m.get("score_domain_violations", 0), g.get("max_score_domain_violation", 0))))
    F.append((m.get("idempotency_violations", 0) <= g.get("max_idempotency_violation", 0),
              "G4 idempotency ihlali %d ≤ %d ((tenant,call,ver) daraltılır; replay çift skor üretmez)"
              % (m.get("idempotency_violations", 0), g.get("max_idempotency_violation", 0))))
    F.append((m.get("blocking_violations", 0) <= g.get("max_blocking_violation", 0),
              "G5 blocking ihlali %d ≤ %d (analytics plane non-blocking; QA canlı çağrıyı etkilemez — FR-RES-011)"
              % (m.get("blocking_violations", 0), g.get("max_blocking_violation", 0))))
    F.append((m.get("pii_violations", 0) <= g.get("max_pii_violation", 0),
              "G6 PII ihlali %d ≤ %d (yalnız redaksiyonlu öznitelik; ham transkript/ses/PII DEĞERİ yok — FR-REC-004)"
              % (m.get("pii_violations", 0), g.get("max_pii_violation", 0))))
    F.append((m.get("isolation_violations", 0) <= g.get("max_isolation_violation", 0),
              "G7 izolasyon ihlali %d ≤ %d (her değerlendirme tenant_id + cross-tenant yok + residency — FR-TEN-002/NFR 10.7)"
              % (m.get("isolation_violations", 0), g.get("max_isolation_violation", 0))))
    F.append((m.get("eligibility_reason_missing", 0) <= g.get("max_eligibility_reason_missing", 0),
              "G8 uygunluk reason eksik %d ≤ %d (uygun-olmayan statü açık reason_code taşır — sessiz atlama yok)"
              % (m.get("eligibility_reason_missing", 0), g.get("max_eligibility_reason_missing", 0))))
    return F


# ─────────────────────────────────────────────────────────────────────────────
# bağlam + politika çözümleme
# ─────────────────────────────────────────────────────────────────────────────
def _profile_by_name(cfg, name):
    for p in cfg.get("profiles", []):
        if p.get("name") == name:
            return p
    raise QaEvalError("bilinmeyen profil: %s" % name)


def _resolve_context(spec, profile, sample):
    ctx = dict(sample.get("context", {}))
    ctx.setdefault("region", profile.get("region"))
    return ctx


def _full_pol():
    return {"evaluate_all": True, "map_output": True, "clamp_scores": True, "honor_weights": True,
            "idempotent": True, "non_blocking": True, "enforce_redaction": True, "isolate_tenant": True,
            "account_excluded": True}


def _resolve_policy(spec, sample):
    pol = _full_pol()
    pol.update(sample.get("policy", {}))
    return pol


def evaluate_cmd(sample_path):
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
        except QaEvalError as ex:
            print("evaluate[%s]: %s" % (name, ex))
            return 0 if expect == "fail" else 1
    context = _resolve_context(spec, profile, sample)
    policy = _resolve_policy(spec, sample)

    try:
        m = evaluate_call(sample, spec, profile, context, policy)
    except QaEvalError as ex:
        print("evaluate[%s]: REDDEDİLDİ — %s" % (name, ex))
        return 0 if expect == "fail" else 1

    F = evaluate(spec, m)
    d = m.get("derived", {})
    print("evaluate[%s] %d çağrı → %d değerlendirme (uygun=%d, degraded=%d) | kapsam=%d katalog=%d skor=%d idempotency=%d blocking=%d pii=%d izolasyon=%d uygunluk=%d" % (
        name, len(sample.get("calls", [])), m["produced"], d.get("eligible", 0), d.get("degraded", 0),
        m["coverage_gap"], m["catalog_mismatch"], m["score_domain_violations"], m["idempotency_violations"],
        m["blocking_violations"], m["pii_violations"], m["isolation_violations"], m["eligibility_reason_missing"]))
    print("  kapsam: üretilen=%d / uygun=%d = %.3f (FR-ANA-001 %%100) | dedup grup=%d" % (
        d.get("produced", 0), d.get("eligible", 0), d.get("coverage_ratio", 1.0), d.get("dedup_groups", 0)))
    for ok, label in F:
        print("  %s %s" % ("✓" if ok else "✗", label))
    gate_ok = all(ok for ok, _ in F) and len(F) > 0

    exp = sample.get("expected", {})
    for k, v in exp.items():
        got = m.get(k)
        match = (got == v)
        print("  %s expected.%s == %r (got %r)" % ("✓" if match else "✗", k, v, got))
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
        if regex.search(obj):
            hits.append((path, obj))
    return hits


def _load_olap_spec():
    """analytics/olap-spec.json (varsa) — fct_qa_evaluation çapraz-tutarlılığı için."""
    cand = os.path.normpath(os.path.join(HERE, "..", "..", "analytics", "olap-spec.json"))
    if os.path.exists(cand):
        try:
            return _load(cand)
        except Exception:
            return None
    return None


def _load_eventstream_spec():
    cand = os.path.normpath(os.path.join(HERE, "..", "..", "eventstream", "topic-spec.json"))
    if os.path.exists(cand):
        try:
            return _load(cand)
        except Exception:
            return None
    return None


def _qa_fact_columns(olap):
    """fct_qa_evaluation sütun adlarını çıkar (non-circular kapsam türetimi)."""
    for ft in olap.get("fact_tables", []):
        if ft.get("name") == "fct_qa_evaluation":
            return [c.get("name") for c in ft.get("columns", [])], ft
    return [], None


def validate():
    spec = _load(SPEC_PATH)
    R = []

    _check(R, spec.get("wbs") == "14.2.1", "spec.wbs == 14.2.1")
    _check(R, spec.get("version"), "spec.version mevcut")
    _check(R, spec.get("phase") == "F2", "spec.phase == F2")
    _check(R, spec.get("priority") == "Must", "spec.priority == Must (FR-ANA-001)")
    ed = spec.get("eval_doc", {})
    for k in ("fr", "srs", "rtm", "brd", "sad", "db", "olap", "eventstream", "adr", "api", "upstream"):
        _check(R, bool(ed.get(k)), "eval_doc.%s mevcut" % k)

    # ── placement (G5)
    pl = spec.get("placement", {})
    _check(R, pl.get("in_analytics_plane") is True, "G5 Engine analytics plane'de (SAD §4.2)")
    _check(R, pl.get("async_batch") is True, "G5 async batch (FR-RES-011)")
    _check(R, pl.get("non_blocking") is True, "G5 non-blocking (QA canlı çağrıyı etkilemez)")
    _check(R, pl.get("from_redacted_content") is True, "G6 from_redacted_content (PII redaction sonrası)")
    _check(R, pl.get("all_calls") is True, "G1 all_calls (FR-ANA-001 tüm çağrılar)")
    _check(R, pl.get("deterministic_rubric") is True, "I9 deterministic_rubric (vendor-neutral)")
    _check(R, pl.get("idempotent") is True, "G4 idempotent")
    _check(R, pl.get("from_trace") is False, "from_trace=false (rubric değerlendirme, trace türetme değil)")

    # ── coverage (G1 / BİRİNCİL)
    cov = spec.get("coverage", {})
    _check(R, cov.get("target") == 1.0, "G1 coverage.target == 1.0 (SR-ANA-001 %100)")
    _check(R, cov.get("degraded_still_counts") is True, "G1 degraded çağrı yine sayılır (sessiz atlama yok)")

    # ── eligibility (G8)
    el = spec.get("eligibility", {})
    _check(R, el.get("evaluable_status") == ["completed"], "G1 evaluable_status == [completed]")
    _check(R, set(el.get("excluded_status", [])) == set(el.get("reason_codes", [])),
           "G8 excluded_status ↔ reason_codes BİREBİR (her uygun-olmayan statünün reason kodu var)")
    _check(R, len(el.get("excluded_status", [])) >= 3, "G8 ≥3 uygun-olmayan statü tanımlı")

    # ── rubric (G3)
    rub = spec.get("rubric", {})
    dims = rub.get("dimensions", [])
    _check(R, rub.get("score_domain") == [0.0, 1.0], "G3 score_domain == [0,1]")
    wsum = sum(d.get("weight", 0) for d in dims)
    _check(R, abs(wsum - 1.0) < 1e-9 and abs(rub.get("weights_sum", 0) - 1.0) < 1e-9,
           "G3 rubric ağırlık toplamı == 1.0 (%.3f)" % wsum)
    _check(R, len(dims) >= 3, "G3 ≥3 skorkart boyutu (accuracy/compliance/helpfulness)")
    dim_names = {d.get("name") for d in dims}
    _check(R, {"accuracy", "compliance", "helpfulness"} <= dim_names, "G3 çekirdek boyutlar mevcut")
    _check(R, all(0.0 <= d.get("weight", -1) <= 1.0 for d in dims), "G3 her ağırlık ∈ [0,1]")
    _check(R, all(d.get("output_column") and d.get("method") and d.get("fr") for d in dims),
           "G3 her boyut output_column/method/fr taşır")
    _check(R, rub.get("composite_column") == "auto_score", "G3 composite_column == auto_score")

    # ── output_contract (G2)
    oc = spec.get("output_contract", {})
    sf = oc.get("score_fields", [])
    _check(R, oc.get("eval_type") == "automatic", "I11 eval_type == automatic (DB.md §5.6)")
    _check(R, set(sf) == ({"auto_score"} | {d["output_column"] for d in dims}),
           "G2 score_fields = auto_score + boyut sütunları (tutarlı)")
    _check(R, {"tenant_id", "call_id", "schema_version"} <= set(oc.get("identity_fields", [])),
           "G7 identity_fields tenant_id/call_id/schema_version içerir")
    _check(R, oc.get("emits_event") == "qa.evaluation.completed", "I4 emits qa.evaluation.completed")

    # ── idempotency (G4)
    idem = spec.get("idempotency", {})
    _check(R, idem.get("dedup_key") == ["tenant_id", "call_id", "schema_version"],
           "G4 dedup_key == (tenant_id, call_id, schema_version)")
    _check(R, idem.get("replay_safe") is True, "G4 replay_safe (1.1.8 P3)")

    # ── feature_policy (G6)
    fp = spec.get("feature_policy", {})
    allowed = set(fp.get("allowed_feature_keys", []))
    forb = set(fp.get("forbidden_feature_keys", []))
    _check(R, {"grounded_answers", "total_answers", "disclosure_given", "resolved"} <= allowed,
           "G6 allowed_feature_keys çekirdek özniteliklerini içerir")
    _check(R, {"transcript_text", "audio_payload", "phone_number", "card_number"} <= forb,
           "G6 forbidden_feature_keys ham transkript/ses/PII anahtarlarını içerir")
    _check(R, not (allowed & forb), "G6 izinli ile yasak öznitelik kesişmez")
    # her boyutun kullandığı öznitelikler izinli listede
    used = set()
    for d in dims:
        used |= set(d.get("features", []))
    _check(R, used <= allowed, "G6 rubric boyut öznitelikleri tümü izinli listede")

    # ── isolation (G7)
    iso = spec.get("isolation", {})
    _check(R, iso.get("tenant_id_required") is True, "G7 tenant_id_required")
    _check(R, iso.get("residency") == "home-region", "G7 residency home-region (NFR 10.7)")
    _check(R, iso.get("cross_tenant_forbidden") is True, "G7 cross_tenant_forbidden (FR-TEN-002)")

    # ── OLAP fct_qa_evaluation BİREBİR (G2, non-circular)
    olap = _load_olap_spec()
    if olap is not None:
        cols, ft = _qa_fact_columns(olap)
        derived_score_fields = {c for c in cols if c == "auto_score" or c.startswith("score_")}
        _check(R, set(sf) == derived_score_fields,
               "G2 score_fields OLAP fct_qa_evaluation auto_score+score_* ile BİREBİR (%s)" % ",".join(sorted(derived_score_fields)))
        for d in dims:
            _check(R, d.get("output_column") in cols,
                   "G2 boyut %s → sütun %s OLAP'ta mevcut" % (d.get("name"), d.get("output_column")))
        if ft is not None:
            _check(R, "FR-ANA-001" in ft.get("fr", []), "G2 OLAP fct_qa_evaluation FR-ANA-001 taşır")

    # ── eventstream qa.evaluation.v1 BİREBİR (I4/I6, non-circular)
    es = _load_eventstream_spec()
    if es is not None:
        qt = None
        for t in es.get("topics", []):
            if t.get("name") == "qa.evaluation.v1":
                qt = t
                break
        _check(R, qt is not None, "I4 eventstream qa.evaluation.v1 topic mevcut")
        if qt is not None:
            _check(R, qt.get("pii_class") == "redacted", "I6 qa.evaluation.v1 pii_class == redacted")
            _check(R, "qa-eval" in qt.get("consumers", []), "I4 qa-eval consumer'ı qa.evaluation.v1'i tüketir")
            _check(R, "FR-ANA-001" in qt.get("fr", []), "I4 qa.evaluation.v1 FR-ANA-001 taşır")
            _check(R, "qa.evaluation.completed" in qt.get("produces_events", []),
                   "I4 qa.evaluation.v1 → qa.evaluation.completed üretir")

    # ── gates
    g = spec.get("gates", {})
    for gk in ("max_coverage_gap", "max_catalog_mismatch", "max_score_domain_violation",
               "max_idempotency_violation", "max_blocking_violation", "max_pii_violation",
               "max_isolation_violation", "max_eligibility_reason_missing"):
        _check(R, g.get(gk, -1) == 0, "gate %s = 0" % gk)

    # ── error taxonomy (I10)
    et = spec.get("error_taxonomy", {}).get("mapping", {})
    _check(R, len(et) >= 3, "I10 hata eşlemesi (≥3)")
    _check(R, all(v in ERROR_TAXONOMY for v in et.values()), "I10 tüm hedefler API §11.6 ErrorTaxonomy'de")
    _check(R, et.get("malformed_call") == "INVALID_REQUEST" and et.get("unknown_status") == "INVALID_REQUEST"
           and et.get("region_mismatch") == "REGION_VIOLATION",
           "I10 malformed/unknown→INVALID_REQUEST, region→REGION_VIOLATION")

    # ── pii (spec sağlığı, I12)
    _check(R, spec.get("pii", {}).get("raw_payload_in_spec_forbidden") is True, "I12 ham ses payload spec'te yasak")
    _check(R, spec.get("pii", {}).get("transcript_in_spec_forbidden") is True, "I12 transkript spec'te yasak")
    _check(R, spec.get("pii", {}).get("pii_values_in_spec_forbidden") is True, "I12 PII DEĞERİ spec'te yasak")

    # ── invariant kataloğu
    inv_ids = [i.get("id") for i in spec.get("invariants", [])]
    _check(R, len(inv_ids) == len(set(inv_ids)) and len(inv_ids) >= 12, "invariant kataloğu ≥12 + tekil ID")
    _check(R, all(i.get("trace") for i in spec.get("invariants", [])), "her invariant trace taşır")

    # ── literal sır + PII DEĞER taraması (spec + config)
    hits = _scan(spec, SECRET_RE)
    pii_hits = _scan(spec, PII_VALUE_RE)
    if os.path.exists(PROFILES_CFG):
        cfg = _load(PROFILES_CFG)
        hits += _scan(cfg, SECRET_RE)
        pii_hits += _scan(cfg, PII_VALUE_RE)
    _check(R, not hits, "I12 literal sır yok (spec+config)")
    _check(R, not pii_hits, "I12 spec/config'te ham PII DEĞERİ yok (%s)" % (",".join(p for p, _ in pii_hits[:3]) or "-"))

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
PROFILE = {"name": "eu-standard", "region": "eu-west-1", "schema_version": 1, "batch_interval_s": 30}

# tipik bir QA batch'i: 3 uygun + 2 uygun-olmayan (reason'lı). Uygun çağrılar farklı kalite profillerinde.
CALLS = [
    {"call_id": "c1", "status": "completed", "features": {
        "disclosure_given": True, "consent_required": True, "consent_verified": True, "policy_violations": 0,
        "grounded_answers": 10, "total_answers": 10, "resolved": True,
        "dead_air_events": 0, "barge_in_respected": 2, "barge_in_total": 2}},
    {"call_id": "c2", "status": "completed", "features": {
        "disclosure_given": True, "consent_required": False, "consent_verified": False, "policy_violations": 1,
        "grounded_answers": 6, "total_answers": 10, "resolved": False, "unresolved_handoff": True,
        "dead_air_events": 1, "barge_in_respected": 1, "barge_in_total": 2}},
    {"call_id": "c3", "status": "completed", "features": {}},   # öznitelik yok → degraded ama YİNE değerlendirilir
    {"call_id": "c4", "status": "abandoned_pre_connect", "reason": "abandoned_pre_connect"},
    {"call_id": "c5", "status": "test_call", "reason": "test_call"},
]


def _run(calls, spec, context=None, profile=None, **pol_over):
    pol = _full_pol()
    pol.update(pol_over)
    return evaluate_call({"calls": calls}, spec, profile or PROFILE, context or CONTEXT, pol)


def _raises(fn):
    try:
        fn()
        return False
    except QaEvalError:
        return True


def selftest():
    spec = _load(SPEC_PATH)
    cases = []

    def case(ok, label):
        cases.append((bool(ok), label))

    case(_validate_obj(_load(SPEC_PATH)) == 0, "validate iyi spec+config'te 0 döndürür")

    # ── happy: tüm kapılar geçer ──
    mh = _run(CALLS, spec)
    case(mh["coverage_gap"] == 0, "happy: kapsam tam — üretilen==uygun (G1 %100)")
    case(mh["derived"]["eligible"] == 3 and mh["derived"]["produced"] == 3, "happy: 3 uygun → 3 değerlendirme")
    case(mh["derived"]["coverage_ratio"] == 1.0, "happy: coverage_ratio == 1.0 (FR-ANA-001/SR-ANA-001)")
    case(mh["derived"]["degraded"] == 1, "happy: c3 öznitelik yok → degraded ama yine sayılır (atlanmaz)")
    case(mh["catalog_mismatch"] == 0, "happy: çıktı skor alanları OLAP ile BİREBİR (G2)")
    case(mh["score_domain_violations"] == 0, "happy: skorlar [0,1] + composite=ağırlıklı toplam (G3)")
    case(mh["idempotency_violations"] == 0, "happy: idempotent (G4)")
    case(mh["blocking_violations"] == 0, "happy: non-blocking (G5)")
    case(mh["pii_violations"] == 0, "happy: yalnız redaksiyonlu öznitelik (G6)")
    case(mh["isolation_violations"] == 0, "happy: tenant izolasyon temiz (G7)")
    case(mh["eligibility_reason_missing"] == 0, "happy: uygun-olmayan statüler reason taşır (G8)")
    case(all(ok for ok, _ in evaluate(spec, mh)), "happy tüm kapıları geçer")

    # ── skor aritmetiği (G3 elle-hesap birebir) ──
    # c1: accuracy=10/10=1.0; compliance=1.0 (disclosure+consent ok, 0 violation); helpfulness=1.0 (resolved, 0 dead, barge 2/2)
    #     auto=0.35·1+0.35·1+0.30·1=1.0
    ev1 = mh["evaluations"][0]
    case(abs(ev1["score_accuracy"] - 1.0) < 1e-9, "c1 accuracy = 10/10 = 1.0 (groundedness)")
    case(abs(ev1["score_compliance"] - 1.0) < 1e-9, "c1 compliance = 1.0 (disclosure+consent, 0 ihlal)")
    case(abs(ev1["score_helpfulness"] - 1.0) < 1e-9, "c1 helpfulness = 1.0 (resolved, dead=0, barge 2/2)")
    case(abs(ev1["auto_score"] - 1.0) < 1e-9, "c1 auto_score = 0.35+0.35+0.30 = 1.0 (ağırlıklı toplam)")
    # c2: accuracy=6/10=0.6; compliance=1.0-0.2·1=0.8 (consent_required false → ceza yok);
    #     helpfulness: handoff base 0.6 - dead 0.1·1=0.1 - barge 0.2·(1-1/2)=0.1 → 0.4
    #     auto=0.35·0.6+0.35·0.8+0.30·0.4=0.21+0.28+0.12=0.61
    ev2 = mh["evaluations"][1]
    case(abs(ev2["score_accuracy"] - 0.6) < 1e-9, "c2 accuracy = 6/10 = 0.6")
    case(abs(ev2["score_compliance"] - 0.8) < 1e-9, "c2 compliance = 1.0 - 0.2·1 = 0.8 (1 policy ihlali)")
    case(abs(ev2["score_helpfulness"] - 0.4) < 1e-9, "c2 helpfulness = 0.6 - 0.1 - 0.1 = 0.4 (handoff, dead, barge)")
    case(abs(ev2["auto_score"] - 0.61) < 1e-9, "c2 auto_score = 0.21+0.28+0.12 = 0.61 (ağırlıklı toplam)")
    # c3 degraded: accuracy=1.0 (total=0), compliance=0.5 (yalnız disclosure cezası -0.5), helpfulness=0.2 (çözümsüz)
    ev3 = mh["evaluations"][2]
    case(abs(ev3["score_accuracy"] - 1.0) < 1e-9 and abs(ev3["score_compliance"] - 0.5) < 1e-9,
         "c3 degraded: accuracy=1.0 (total=0), compliance=0.5 (disclosure yok -0.5)")
    case(ev3["degraded"] is True, "c3 degraded=true işaretli")

    # ── determinizm ──
    case(_run(CALLS, spec) == _run(CALLS, spec), "determinizm: aynı çağrı seti aynı sonucu verir (random yok)")

    # ── G1 kapsam: evaluate_all KAPALI → degraded çağrı atlanır ──
    m1 = _run(CALLS, spec, evaluate_all=False)
    case(m1["coverage_gap"] >= 1, "evaluate_all KAPALI: degraded/uygun çağrı atlanır → G1 kapsam açığı eler")
    case(m1["derived"]["coverage_ratio"] < 1.0, "evaluate_all KAPALI: coverage_ratio < 1.0 (%100 bozulur)")

    # ── G2 katalog: map_output KAPALI → bir score alanı düşer ──
    m2 = _run(CALLS, spec, map_output=False)
    case(m2["catalog_mismatch"] >= 1, "map_output KAPALI: score alanı düşer → G2 katalog eler")

    # ── G3 skor-alanı: clamp_scores KAPALI → negatif compliance ──
    badc = [{"call_id": "x", "status": "completed", "features": {
        "disclosure_given": False, "policy_violations": 5, "grounded_answers": 0, "total_answers": 1, "resolved": False}}]
    m3 = _run(badc, spec, clamp_scores=False)
    case(m3["score_domain_violations"] >= 1, "clamp_scores KAPALI: compliance < 0 (1-0.5-1.0) → G3 skor-alanı eler")
    # honor_weights KAPALI → ağırlık toplamı≠1 → composite drift/domain
    m3w = _run(CALLS, spec, honor_weights=False)
    case(m3w["score_domain_violations"] >= 1, "honor_weights KAPALI: ağırlık toplamı≠1 → composite drift → G3 eler")

    # ── G4 idempotency: aynı call_id iki kez + idempotent KAPALI ──
    dup = CALLS + [{"call_id": "c1", "status": "completed", "features": {
        "disclosure_given": True, "grounded_answers": 5, "total_answers": 5, "resolved": True}}]
    m4 = _run(dup, spec, idempotent=False)
    case(m4["idempotency_violations"] >= 1, "idempotent KAPALI: aynı (tenant,call,ver) çift değerlendirme → G4 eler")
    m4o = _run(dup, spec)
    case(m4o["idempotency_violations"] == 0 and m4o["derived"]["produced"] == 3,
         "idempotent AÇIK: replay daraltılır (3 değerlendirme) → G4 geçer")

    # ── G5 blocking: non_blocking KAPALI → QA bloklar ──
    m5 = _run(CALLS, spec, non_blocking=False)
    case(m5["blocking_violations"] >= 1, "non_blocking KAPALI: QA çağrıyı bloklar → G5 eler (FR-RES-011)")

    # ── G6 PII: enforce_redaction KAPALI + ham transkript özniteliği ──
    leak = [{"call_id": "p", "status": "completed", "features": {
        "transcript_text": "müşteri konuştu", "grounded_answers": 1, "total_answers": 1, "resolved": True,
        "disclosure_given": True}}]
    m6 = _run(leak, spec, enforce_redaction=False)
    case(m6["pii_violations"] == 0, "enforce_redaction KAPALI: redaction zorlanmaz (denetlenmez)")
    m6e = _run(leak, spec)
    case(m6e["pii_violations"] >= 1, "enforce_redaction AÇIK: transcript_text yasak öznitelik → G6 eler")
    # ham PII DEĞERİ (telefon) bir öznitelikte
    leakv = [{"call_id": "pv", "status": "completed", "features": {
        "grounded_answers": 1, "total_answers": 1, "resolved": True, "disclosure_given": True,
        "consent_verified": "0555 123 4567"}}]
    m6v = _run(leakv, spec)
    case(m6v["pii_violations"] >= 1, "öznitelik DEĞERİnde ham telefon → G6 eler")

    # ── G7 izolasyon: isolate_tenant KAPALI → tenant_id yok ──
    m7 = _run(CALLS, spec, isolate_tenant=False)
    case(m7["isolation_violations"] >= 1, "isolate_tenant KAPALI: değerlendirmede tenant_id yok → G7 eler")
    # cross-tenant öznitelik
    cross = [{"call_id": "ct", "status": "completed", "tenant_id": "t_other", "features": {
        "grounded_answers": 1, "total_answers": 1, "resolved": True, "disclosure_given": True}}]
    m7c = _run(cross, spec)
    case(m7c["isolation_violations"] >= 1, "cross-tenant çağrı (t_other ≠ bağlam) → G7 izolasyon eler")
    # residency: home-region dışı
    resd = [{"call_id": "rd", "status": "completed", "region": "us-east-1", "features": {
        "grounded_answers": 1, "total_answers": 1, "resolved": True, "disclosure_given": True}}]
    m7r = _run(resd, spec)
    case(m7r["isolation_violations"] >= 1, "home-region dışı çağrı (residency) → G7 eler (NFR 10.7)")

    # ── G8 uygunluk: reason eksik uygun-olmayan çağrı ──
    noreason = [{"call_id": "nr", "status": "abandoned_pre_connect"}]   # reason yok
    m8 = _run(noreason, spec)
    case(m8["eligibility_reason_missing"] >= 1, "uygun-olmayan statü reason taşımıyor → G8 eler (sessiz atlama yok)")
    m8a = _run([{"call_id": "ar", "status": "abandoned_pre_connect", "reason": "abandoned_pre_connect"}], spec)
    case(m8a["eligibility_reason_missing"] == 0, "reason'lı uygun-olmayan çağrı → G8 geçer")
    # account_excluded KAPALI → sessiz atlama
    m8s = _run([{"call_id": "se", "status": "test_call", "reason": "test_call"}], spec, account_excluded=False)
    case(m8s["eligibility_reason_missing"] >= 1, "account_excluded KAPALI: sessiz atlama → G8 eler")

    # ── reddetme (I10) ──
    case(_raises(lambda: evaluate_call({"calls": "x"}, spec, PROFILE, CONTEXT, _full_pol())),
         "I10 calls liste değil → reddedilir")
    case(_raises(lambda: evaluate_call({"calls": [{"call_id": "z"}]}, spec, PROFILE, CONTEXT, _full_pol())),
         "I10 çağrıda status eksik → reddedilir")
    case(_raises(lambda: evaluate_call({"calls": [{"call_id": "z", "status": "weird"}]}, spec, PROFILE, CONTEXT, _full_pol())),
         "I10 bilinmeyen statü → reddedilir")
    case(_raises(lambda: QaEvalEngine(spec, PROFILE, {"region": "eu"}, _full_pol())),
         "I10 bağlam (tenant_id) eksik → reddedilir")

    # ── validate negatif kapılar ──
    s = json.loads(json.dumps(spec)); s["coverage"]["target"] = 0.95
    case(_validate_obj(s) != 0, "G1 coverage.target 1.0'dan sapar → validate eler")
    s = json.loads(json.dumps(spec)); s["rubric"]["dimensions"][0]["weight"] = 0.5
    case(_validate_obj(s) != 0, "G3 ağırlık toplamı ≠ 1.0 → validate eler")
    s = json.loads(json.dumps(spec)); s["output_contract"]["score_fields"] = ["auto_score"]
    case(_validate_obj(s) != 0, "G2 score_fields OLAP fct_qa_evaluation'dan sapar → validate eler")
    s = json.loads(json.dumps(spec)); s["feature_policy"]["allowed_feature_keys"].append("transcript_text")
    case(_validate_obj(s) != 0, "G6 izinli özniteliğe transcript_text (yasakla kesişim) → validate eler")
    s = json.loads(json.dumps(spec)); s["eligibility"]["excluded_status"] = s["eligibility"]["excluded_status"][:1]
    case(_validate_obj(s) != 0, "G8 excluded_status ↔ reason_codes uyuşmaz → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_coverage_gap"] = 1
    case(_validate_obj(s) != 0, "G1 max_coverage_gap>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["error_taxonomy"]["mapping"]["x"] = "NOPE"
    case(_validate_obj(s) != 0, "I10 taksonomi-dışı → validate eler")
    s = json.loads(json.dumps(spec)); s["output_contract"]["eval_type"] = "manual"
    case(_validate_obj(s) != 0, "I11 eval_type manual (otomatik değil) → validate eler")
    s = json.loads(json.dumps(spec)); s["rubric"]["dimensions"][0]["leak_phone"] = "0555 123 4567"
    case(_validate_obj(s) != 0, "I12 spec'te ham PII DEĞERİ (telefon) → validate eler")
    s = json.loads(json.dumps(spec)); s["rubric"]["dimensions"][0]["leak"] = "api_key: AKIAIOSFODNN7EXAMPLE"
    case(_validate_obj(s) != 0, "I12 literal secret → validate eler")

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
    print("""qa-eval-spec.json beklenen şekli (WBS 14.2.1):
  wbs=14.2.1, version, phase=F2, priority=Must, eval_doc{fr,srs,rtm,brd,sad,db,olap,eventstream,adr,api,upstream}
  placement{in_analytics_plane, async_batch, non_blocking, from_redacted_content, all_calls=true,
            deterministic_rubric, idempotent, from_trace=false}                                   (G5,G6,G1)
  coverage{metric=produced/eligible==1.0, target=1.0, degraded_still_counts=true}                 (G1 BİRİNCİL)
  eligibility{evaluable_status=[completed], excluded_status[], reason_codes[]}                     (G8)
  rubric{score_domain=[0,1], weights_sum=1.0, composite_column=auto_score,
         dimensions[]{name, weight, output_column, method, features, fr}}                          (G3)
  output_contract{eval_type=automatic, score_fields[auto_score+score_*], identity_fields[],
                  emits_event=qa.evaluation.completed, persists_to[]}                              (G2,G7)
  idempotency{dedup_key=[tenant_id,call_id,schema_version], replay_safe=true}                      (G4)
  feature_policy{allowed_feature_keys[], forbidden_feature_keys[]}                                 (G6)
  isolation{tenant_id_required, residency=home-region, cross_tenant_forbidden}                     (G7)
  gates{max_coverage_gap=0, max_catalog_mismatch=0, max_score_domain_violation=0,
        max_idempotency_violation=0, max_blocking_violation=0, max_pii_violation=0,
        max_isolation_violation=0, max_eligibility_reason_missing=0}                               (G1..G8)
  error_taxonomy{mapping→API §11.6 (malformed/unknown→INVALID_REQUEST, region→REGION_VIOLATION)}   (I10)
  pii{raw_payload/transcript/pii_values_in_spec_forbidden}                                         (I12)
  invariants[≥12]{id, desc, trace}

config/qa-eval-profiles.json: profiles[]{name, region, schema_version, batch_interval_s}

evaluate sample: {name, profile | profile_obj, expect, expected?{metrik:değer},
  context{tenant_id, region?},
  policy?{evaluate_all, map_output, clamp_scores, honor_weights, idempotent, non_blocking,
          enforce_redaction, isolate_tenant, account_excluded},
  calls[]{call_id, status, reason?, tenant_id?, region?, features?{REDAKSİYONLU sayısal/kategorik}}}
  (PII DEĞERİ / ham transkript YOK — yalnız redaksiyonlu öznitelik + alan/kimlik anahtarı ADLARI)

komutlar: validate | evaluate <sample.json> | selftest | schema""")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if cmd == "validate":
        return validate()
    if cmd == "evaluate":
        if len(sys.argv) < 3:
            print("kullanım: qa_eval_probe.py evaluate <sample.json>")
            return 2
        return evaluate_cmd(sys.argv[2])
    if cmd == "selftest":
        return selftest()
    if cmd == "schema":
        return schema()
    print("bilinmeyen komut: %s (validate|evaluate|selftest|schema)" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main())
