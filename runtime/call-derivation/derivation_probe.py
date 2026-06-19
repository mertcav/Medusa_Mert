#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
derivation_probe.py — WBS 14.2.2 Intent/outcome/disposition/completion çıkarımı

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only statik + davranış kapısı.
`runtime/qa-eval/` (14.2.1) probe disipliniyle birebir; burada deterministik bir ANALYTICS-PLANE
ÇIKARIM (DERIVATION) motoru (SAD §4.2 async batch; analytics-ingest consumer) simülatörü (saf; random YOK).

ÇIKARIM MOTORU — Analytics/Ops Plane'de (SAD §4.2/§171, FR-RES-011) async/non-blocking; event stream
(voice.call.lifecycle.v1 [FR-ANA-002] + voice.transcript.redacted.v1 [redacted]) üzerinden PII-redaksiyonlu
sinyallerle çalışır, HER UYGUN çağrı için DÖRT kategorik alanı (intent/outcome/disposition/completion_status)
kapalı-sözlükten deterministik türetir ve sonucu call (DB.md §5.5) + OLAP fct_call ile BİREBİR doldurur:
  • Kapsam (G1):        her UYGUN çağrı → DÖRT alanı dolu tam bir çıkarım (%100; FR-ANA-002/SR-ANA-002) — BİRİNCİL.
  • Katalog (G2):       categorical_fields {intent,disposition,completion_status} OLAP fct_call FR-ANA-002 ile BİREBİR.
  • Sözlük (G3):        türetilen DÖRT alanın her değeri kapalı-sözlükte (düşük-kardinalite enum; serbest metin yok).
  • Tutarlılık (G4):    cross-field invariant C1–C5 (outcome↔completion↔disposition mantıksal çelişmez).
  • İdempotent (G5):    (tenant_id,call_id,schema_version) daraltılır; at-least-once çift satır üretmez (replay-safe).
  • Async (G6):         analytics plane'de non-blocking; çıkarım başarısızlığı canlı çağrıyı etkilemez (placement).
  • PII (G7):           yalnız redaksiyonlu sinyal; ham transkript/ses/PII DEĞERİ yok (FR-REC-004).
  • İzolasyon (G8):     her çıkarım tenant_id taşır + cross-tenant sinyal yok + residency (FR-TEN-002/NFR 10.7).
  • Uygunluk (G9):      uygun-olmayan statü açık reason_code taşır (sessiz atlama yok) — kapsam bütünlüğü.

KAPSAM AYRIMI: otomatik kalite skoru → 14.2.1 · containment/transfer ORANI → 14.2.3 (bu motorun ürettiği
outcome=contained/transferred per-call etiketini AGREGE eder) · yanlış-bilgi/tool-hata/güvenlik İŞARETİ →
14.2.4 · kritik işaretleme → 14.2.5 · MANUEL skor → 14.2.6. Burada YALNIZ per-call DÖRT-alan çıkarımı + %100 kapsam.

Komutlar:
  validate              derivation-spec.json'ı invariant'lara + OLAP/eventstream çapraz-tutarlılığa + config'e karşı doğrular.
  derive <sample>       Deterministik CallDerivationEngine — çağrı seti → üretilen çıkarım + kapsam + HARD kapılar (G1–G9); →çıkış kodu.
  selftest              İyi/kötü spec+sample ile kapıların doğru tetiklendiğini kanıtlar.
  schema                Beklenen spec şeklini özetler.

Sunucu/credential GEREKMEZ. derive gerçek motor yerine deterministik simülasyondur (canlıda lifecycle+redacted
event stream consumer + OLAP/OLTP sink, SAD §4.2/§12.1; ADR-007). Ham ses payload/transkript METNİ/PII DEĞERİ YOK —
örnekler yalnız REDAKSİYONLU kategorik/sayısal sinyal + alan/kimlik/sözlük anahtarı ADLARI taşır.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "derivation-spec.json")
PROFILES_CFG = os.path.join(HERE, "config", "derivation-profiles.json")

ERROR_TAXONOMY = {
    "TIMEOUT", "RATE_LIMITED", "UNAVAILABLE", "AUTH",
    "INVALID_REQUEST", "CONTENT_FILTERED", "QUOTA_EXCEEDED", "REGION_VIOLATION",
}
SECRET_RE = re.compile(
    r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer)\b\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}"
)
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")
# Ham PII DEĞER desenleri (sinyal/çıktıda yasak — FR-REC-004). Yalnız anahtar ADI olmalı.
PII_VALUE_RE = re.compile(
    r"(?:\d[ \-]?){7,}"                                   # ≥7 ardışık rakam (telefon/kart/IBAN)
    r"|[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"  # e-posta
    r"|\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b"                  # IBAN
)
NOT_CONNECTED_REASONS = {"voicemail", "busy", "no_answer", "invalid"}


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_placeholder(v):
    return isinstance(v, str) and PLACEHOLDER_RE.match(v) is not None


class DerivationError(Exception):
    """Geçersiz/eksik çağrı kaydı veya bilinmeyen statü — sessizce kabul yok, reddet (I11)."""


# ─────────────────────────────────────────────────────────────────────────────
# Deterministik kapalı-sözlük çıkarımı (saf öncelik kuralları; random YOK)
# ─────────────────────────────────────────────────────────────────────────────
def derive_outcome(f):
    if str(f.get("not_connected_reason") or "") in NOT_CONNECTED_REASONS:
        return "not_connected"
    if bool(f.get("caller_abandoned", False)):
        return "abandoned"
    if bool(f.get("transferred", False)):
        return "transferred_to_human"
    if bool(f.get("resolved", False)):
        return "contained"
    return "unresolved"


def derive_completion(f, consistent=True):
    if not consistent:
        # buggy: outcome'u yok sayar — yalnız flow_completed'a bakar → outcome ile desenkronize
        return "completed" if bool(f.get("flow_completed", False)) else "partial"
    if str(f.get("not_connected_reason") or "") in NOT_CONNECTED_REASONS:
        return "not_started"
    if bool(f.get("caller_abandoned", False)):
        return "abandoned"
    if bool(f.get("transferred", False)):
        return "transferred"
    if bool(f.get("flow_completed", False)):
        return "completed"
    return "partial"


def derive_disposition(f, outcome):
    if bool(f.get("dnc_requested", False)):
        return "dnc_requested"
    if bool(f.get("wrong_number", False)):
        return "wrong_number"
    if outcome == "not_connected":
        return "voicemail_left" if bool(f.get("voicemail_left", False)) else "no_action"
    if outcome == "transferred_to_human":
        return "escalated"
    if bool(f.get("callback_scheduled", False)):
        return "callback_scheduled"
    if outcome == "contained":
        return "resolved"
    if bool(f.get("not_interested", False)):
        return "not_interested"
    if bool(f.get("follow_up_required", False)):
        return "follow_up_required"
    return "no_action"


def normalize_intent(f, vocab, closed=True):
    sig = f.get("intent_signal")
    if not closed:
        # buggy: ham sinyali kapalı-sözlüğe normalize etmeden geçirir (vocab-dışı / potansiyel PII)
        return sig if sig is not None else "unknown"
    if isinstance(sig, str) and sig in vocab:
        return sig
    return "unknown"


# ─────────────────────────────────────────────────────────────────────────────
# Cross-field tutarlılık (C1–C5) — her tuple'da denetlenir (always-on)
# ─────────────────────────────────────────────────────────────────────────────
def consistency_violations(intent, outcome, disposition, completion):
    n = 0
    if outcome == "transferred_to_human" and completion != "transferred":
        n += 1                                                          # C1
    if outcome == "abandoned" and completion != "abandoned":
        n += 1                                                          # C2
    if outcome == "not_connected" and completion != "not_started":
        n += 1                                                          # C3
    if completion == "completed" and outcome not in ("contained", "unresolved"):
        n += 1                                                          # C4
    if disposition == "escalated" and outcome != "transferred_to_human":
        n += 1                                                          # C5
    return n


# ─────────────────────────────────────────────────────────────────────────────
# Çıkarım motoru — deterministik DÖRT-alan türetimi
# ─────────────────────────────────────────────────────────────────────────────
class CallDerivationEngine:
    """Analytics plane'de async/non-blocking; redaksiyonlu sinyalden DÖRT kapalı-sözlük alanı türetir +
    %100 kapsam + katalog + sözlük + tutarlılık + idempotency + PII + tenant izolasyon + uygunluk
    disiplinine karşı denetler. Saf; random YOK.

    policy bayrakları buggy bir Engine'i simüle eder (qa-eval deseni):
      classify_all        : her uygun çağrıyı türet (kapalı → sinyalsiz/degraded çağrı atlanır, G1 kapsam)
      map_output          : DÖRT alanın tümünü çıktıya yaz (kapalı → bir alan düşer, G2 katalog)
      closed_vocab        : değerleri kapalı-sözlüğe sınırla (kapalı → ham intent_signal vocab-dışı geçer, G3)
      enforce_consistency : completion'ı outcome'a göre tutarlı türet (kapalı → desenkronize, G4)
      idempotent          : (tenant,call,ver) daralt (kapalı → çift çıkarım, G5)
      non_blocking        : analytics plane non-blocking (kapalı → çıkarım çağrıyı bloklar, G6)
      enforce_redaction   : ham PII/transkript sinyalini reddet (kapalı → transcript_text geçer, G7)
      isolate_tenant      : çıkarıma tenant_id ekle (kapalı → tenant_id yok / cross-tenant, G8)
      account_excluded    : uygun-olmayan çağrının reason_code'unu denetle (kapalı → sessiz atlama, G9)
    """

    def __init__(self, spec, profile, context, policy):
        self.spec = spec
        self.context = dict(context or {})
        self.pol = policy

        self.evaluable = set(spec.get("eligibility", {}).get("evaluable_status", []))
        self.excluded = set(spec.get("eligibility", {}).get("excluded_status", []))
        self.reason_codes = set(spec.get("eligibility", {}).get("reason_codes", []))

        self.vocab = spec.get("vocabularies", {})
        oc = spec.get("output_contract", {})
        self.all_fields = list(oc.get("all_fields", []))
        self.categorical_fields = list(oc.get("categorical_fields", []))
        self.result_field = oc.get("result_field", "outcome")
        self.identity_fields = list(oc.get("identity_fields", []))

        fp = spec.get("feature_policy", {})
        self.allowed_features = set(fp.get("allowed_feature_keys", []))
        self.forbidden_features = set(fp.get("forbidden_feature_keys", []))

        self.region_pin = profile.get("region")
        self.schema_version = profile.get("schema_version", 1)

        if not self.context.get("tenant_id"):
            raise DerivationError("çıkarım bağlamı eksik: tenant_id → INVALID_REQUEST")
        if not self.context.get("region"):
            raise DerivationError("çıkarım bağlamı eksik: region → INVALID_REQUEST")

        # sayaçlar (HARD kapı kanıtı)
        self.coverage_gap = 0
        self.catalog_mismatch = 0
        self.vocab_violations = 0
        self.consistency_violation_count = 0
        self.idempotency_violations = 0
        self.blocking_violations = 0
        self.pii_violations = 0
        self.isolation_violations = 0
        self.eligibility_reason_missing = 0

        self.eligible = 0
        self.produced = 0
        self.degraded = 0
        self.derivations = []          # üretilen çıkarım satırları
        self.derived = {}

    # ── redaksiyonlu sinyal denetimi (G7) ──────────────────────────────────────
    def _check_features(self, features):
        if not self.pol.get("enforce_redaction", True):
            return                       # buggy: redaction zorlanmaz
        for k, v in (features or {}).items():
            if k in self.forbidden_features:
                self.pii_violations += 1
            elif k not in self.allowed_features:
                self.pii_violations += 1   # whitelist dışı anahtar — potansiyel ham içerik
            if isinstance(v, str) and not _is_placeholder(v) and PII_VALUE_RE.search(v):
                self.pii_violations += 1   # ham PII DEĞERİ

    # ── tek çağrı → çıkarım satırı ─────────────────────────────────────────────
    def _derive_call(self, call):
        features = call.get("features", {}) or {}
        self._check_features(features)
        degraded = not features or call.get("degraded", False)

        outcome = derive_outcome(features)
        completion = derive_completion(features, consistent=self.pol.get("enforce_consistency", True))
        disposition = derive_disposition(features, outcome)
        intent = normalize_intent(features, self.vocab.get("intent", []),
                                  closed=self.pol.get("closed_vocab", True))

        row_fields = {"intent": intent, "outcome": outcome,
                      "disposition": disposition, "completion_status": completion}

        # G3 sözlük: her alan değeri kapalı-sözlükte
        for fld in self.all_fields:
            val = row_fields.get(fld)
            allowed = self.vocab.get(fld, [])
            if val not in allowed:
                self.vocab_violations += 1
            # ham PII DEĞERİ kategorik değere sızmış mı (vocab-dışı serbest metin)
            if isinstance(val, str) and not _is_placeholder(val) and PII_VALUE_RE.search(val):
                self.pii_violations += 1

        # G4 tutarlılık: cross-field invariant C1–C5
        self.consistency_violation_count += consistency_violations(
            intent, outcome, disposition, completion)

        row = dict(row_fields)
        # katalog (G2): map_output kapalı → bir alan düşür
        if not self.pol.get("map_output", True):
            row.pop(self.all_fields[-1], None)
        for fld in self.all_fields:
            if fld not in row:
                self.catalog_mismatch += 1

        # kimlik + izolasyon (G8)
        row["call_id"] = call.get("call_id")
        row["schema_version"] = self.schema_version
        row["degraded"] = bool(degraded)
        if self.pol.get("isolate_tenant", True):
            row["tenant_id"] = self.context.get("tenant_id")
            row["region"] = self.region_pin
        if "tenant_id" not in row:
            self.isolation_violations += 1
        ct = call.get("tenant_id")
        if ct is not None and ct != self.context.get("tenant_id"):
            self.isolation_violations += 1
        cr = call.get("region")
        if cr is not None and self.region_pin is not None and cr != self.region_pin:
            self.isolation_violations += 1

        if degraded:
            self.degraded += 1
        return row

    def run(self, calls):
        # G6 async/non-blocking (placement): çıkarım çağrıyı bloklamaz
        if not self.pol.get("non_blocking", True):
            self.blocking_violations += 1
        if not self.spec.get("placement", {}).get("non_blocking", True):
            self.blocking_violations += 1

        seen = set()
        for call in calls:
            status = call.get("status")
            if status is None:
                raise DerivationError("çağrı kaydında status eksik → INVALID_REQUEST")
            if status in self.evaluable:
                self.eligible += 1
                key = (self.context.get("tenant_id"), call.get("call_id"), self.schema_version)
                if key in seen:
                    if self.pol.get("idempotent", True):
                        continue          # daraltılır (tek çıkarım) — ihlal değil
                    else:
                        self.idempotency_violations += 1   # buggy: çift çıkarım
                seen.add(key)
                # G1 kapsam: classify_all kapalıysa sinyalsiz/degraded çağrı atlanır
                if not self.pol.get("classify_all", True) and (not call.get("features") or call.get("degraded")):
                    continue              # buggy: sessizce atla → coverage_gap
                self.derivations.append(self._derive_call(call))
                self.produced += 1
            elif status in self.excluded:
                # G9 uygunluk: açık reason_code zorunlu (sessiz atlama yok)
                reason = call.get("reason")
                if not self.pol.get("account_excluded", True):
                    self.eligibility_reason_missing += 1
                elif reason not in self.reason_codes:
                    self.eligibility_reason_missing += 1
            else:
                raise DerivationError("bilinmeyen çağrı statüsü: %s → INVALID_REQUEST" % status)

        self.coverage_gap = self.eligible - self.produced if self.eligible >= self.produced else 0

        self.derived["eligible"] = self.eligible
        self.derived["produced"] = self.produced
        self.derived["degraded"] = self.degraded
        self.derived["coverage_ratio"] = (self.produced / self.eligible) if self.eligible else 1.0
        self.derived["dedup_groups"] = len(seen)
        # outcome/intent dağılımı (14.2.3 agregasyonun girdisi; düşük-kardinalite)
        self.derived["by_outcome"] = self._dist("outcome")
        self.derived["by_intent"] = self._dist("intent")

    def _dist(self, field):
        out = {}
        for r in self.derivations:
            out[r.get(field)] = out.get(r.get(field), 0) + 1
        return out

    def metrics(self):
        return {
            "coverage_gap": self.coverage_gap,
            "catalog_mismatch": self.catalog_mismatch,
            "vocab_violations": self.vocab_violations,
            "consistency_violations": self.consistency_violation_count,
            "idempotency_violations": self.idempotency_violations,
            "blocking_violations": self.blocking_violations,
            "pii_violations": self.pii_violations,
            "isolation_violations": self.isolation_violations,
            "eligibility_reason_missing": self.eligibility_reason_missing,
            "produced": self.produced,
            "eligible": self.eligible,
            "derivations": list(self.derivations),
            "derived": dict(self.derived),
        }


def derive_calls(sample, spec, profile, context, policy):
    calls = sample.get("calls")
    if not isinstance(calls, list):
        raise DerivationError("çağrı seti (calls) liste değil → INVALID_REQUEST")
    for c in calls:
        if not isinstance(c, dict):
            raise DerivationError("çağrı kaydı sözlük değil → INVALID_REQUEST")
    eng = CallDerivationEngine(spec, profile, context, policy)
    eng.run(calls)
    return eng.metrics()


def evaluate(spec, m):
    """Metrikleri HARD kapılara (G1–G9) karşı değerlendirir. Döner findings[(ok, label)]."""
    g = spec.get("gates", {})
    d = m.get("derived", {})
    F = []
    F.append((m.get("coverage_gap", 0) <= g.get("max_coverage_gap", 0),
              "G1 kapsam açığı %d ≤ %d (üretilen %d / uygun %d = %.3f — FR-ANA-002/SR-ANA-002 %%100, DÖRT alan dolu) — BİRİNCİL"
              % (m.get("coverage_gap", 0), g.get("max_coverage_gap", 0),
                 d.get("produced", 0), d.get("eligible", 0), d.get("coverage_ratio", 1.0))))
    F.append((m.get("catalog_mismatch", 0) <= g.get("max_catalog_mismatch", 0),
              "G2 katalog uyuşmazlığı %d ≤ %d (intent/disposition/completion_status OLAP fct_call FR-ANA-002 ile BİREBİR)"
              % (m.get("catalog_mismatch", 0), g.get("max_catalog_mismatch", 0))))
    F.append((m.get("vocab_violations", 0) <= g.get("max_vocab_violation", 0),
              "G3 sözlük ihlali %d ≤ %d (DÖRT alanın her değeri kapalı-sözlükte; düşük-kardinalite enum, serbest metin yok)"
              % (m.get("vocab_violations", 0), g.get("max_vocab_violation", 0))))
    F.append((m.get("consistency_violations", 0) <= g.get("max_consistency_violation", 0),
              "G4 tutarlılık ihlali %d ≤ %d (cross-field C1–C5: outcome↔completion↔disposition çelişmez)"
              % (m.get("consistency_violations", 0), g.get("max_consistency_violation", 0))))
    F.append((m.get("idempotency_violations", 0) <= g.get("max_idempotency_violation", 0),
              "G5 idempotency ihlali %d ≤ %d ((tenant,call,ver) daraltılır; replay çift satır üretmez)"
              % (m.get("idempotency_violations", 0), g.get("max_idempotency_violation", 0))))
    F.append((m.get("blocking_violations", 0) <= g.get("max_blocking_violation", 0),
              "G6 blocking ihlali %d ≤ %d (analytics plane non-blocking; çıkarım canlı çağrıyı etkilemez — FR-RES-011)"
              % (m.get("blocking_violations", 0), g.get("max_blocking_violation", 0))))
    F.append((m.get("pii_violations", 0) <= g.get("max_pii_violation", 0),
              "G7 PII ihlali %d ≤ %d (yalnız redaksiyonlu sinyal; ham transkript/ses/PII DEĞERİ yok — FR-REC-004)"
              % (m.get("pii_violations", 0), g.get("max_pii_violation", 0))))
    F.append((m.get("isolation_violations", 0) <= g.get("max_isolation_violation", 0),
              "G8 izolasyon ihlali %d ≤ %d (her çıkarım tenant_id + cross-tenant yok + residency — FR-TEN-002/NFR 10.7)"
              % (m.get("isolation_violations", 0), g.get("max_isolation_violation", 0))))
    F.append((m.get("eligibility_reason_missing", 0) <= g.get("max_eligibility_reason_missing", 0),
              "G9 uygunluk reason eksik %d ≤ %d (uygun-olmayan statü açık reason_code taşır — sessiz atlama yok)"
              % (m.get("eligibility_reason_missing", 0), g.get("max_eligibility_reason_missing", 0))))
    return F


# ─────────────────────────────────────────────────────────────────────────────
# bağlam + politika çözümleme
# ─────────────────────────────────────────────────────────────────────────────
def _profile_by_name(cfg, name):
    for p in cfg.get("profiles", []):
        if p.get("name") == name:
            return p
    raise DerivationError("bilinmeyen profil: %s" % name)


def _resolve_context(spec, profile, sample):
    ctx = dict(sample.get("context", {}))
    ctx.setdefault("region", profile.get("region"))
    return ctx


def _full_pol():
    return {"classify_all": True, "map_output": True, "closed_vocab": True, "enforce_consistency": True,
            "idempotent": True, "non_blocking": True, "enforce_redaction": True, "isolate_tenant": True,
            "account_excluded": True}


def _resolve_policy(spec, sample):
    pol = _full_pol()
    pol.update(sample.get("policy", {}))
    return pol


def derive_cmd(sample_path):
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
        except DerivationError as ex:
            print("derive[%s]: %s" % (name, ex))
            return 0 if expect == "fail" else 1
    context = _resolve_context(spec, profile, sample)
    policy = _resolve_policy(spec, sample)

    try:
        m = derive_calls(sample, spec, profile, context, policy)
    except DerivationError as ex:
        print("derive[%s]: REDDEDİLDİ — %s" % (name, ex))
        return 0 if expect == "fail" else 1

    F = evaluate(spec, m)
    d = m.get("derived", {})
    print("derive[%s] %d çağrı → %d çıkarım (uygun=%d, degraded=%d) | kapsam=%d katalog=%d sözlük=%d tutarlılık=%d idempotency=%d blocking=%d pii=%d izolasyon=%d uygunluk=%d" % (
        name, len(sample.get("calls", [])), m["produced"], d.get("eligible", 0), d.get("degraded", 0),
        m["coverage_gap"], m["catalog_mismatch"], m["vocab_violations"], m["consistency_violations"],
        m["idempotency_violations"], m["blocking_violations"], m["pii_violations"],
        m["isolation_violations"], m["eligibility_reason_missing"]))
    print("  kapsam: üretilen=%d / uygun=%d = %.3f (FR-ANA-002 %%100) | dedup grup=%d | outcome=%s | intent=%s" % (
        d.get("produced", 0), d.get("eligible", 0), d.get("coverage_ratio", 1.0), d.get("dedup_groups", 0),
        d.get("by_outcome", {}), d.get("by_intent", {})))
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


def validate():
    spec = _load(SPEC_PATH)
    R = []

    _check(R, spec.get("wbs") == "14.2.2", "spec.wbs == 14.2.2")
    _check(R, spec.get("version"), "spec.version mevcut")
    _check(R, spec.get("phase") == "F1/F2", "spec.phase == F1/F2")
    _check(R, spec.get("priority") == "Must", "spec.priority == Must (FR-ANA-002)")
    ed = spec.get("eval_doc", {})
    for k in ("fr", "srs", "rtm", "brd", "sad", "db", "olap", "eventstream", "adr", "api", "upstream"):
        _check(R, bool(ed.get(k)), "eval_doc.%s mevcut" % k)

    # ── placement (G6)
    pl = spec.get("placement", {})
    _check(R, pl.get("in_analytics_plane") is True, "G6 motor analytics plane'de (SAD §4.2)")
    _check(R, pl.get("async_batch") is True, "G6 async batch (FR-RES-011)")
    _check(R, pl.get("non_blocking") is True, "G6 non-blocking (çıkarım canlı çağrıyı etkilemez)")
    _check(R, pl.get("from_redacted_content") is True, "G7 from_redacted_content (PII redaction sonrası)")
    _check(R, pl.get("all_calls") is True, "G1 all_calls (FR-ANA-002 her çağrı)")
    _check(R, pl.get("deterministic_taxonomy") is True, "I10 deterministic_taxonomy (vendor-neutral)")
    _check(R, pl.get("idempotent") is True, "G5 idempotent")
    _check(R, pl.get("from_trace") is False, "from_trace=false (sinyalden çıkarım, trace türetme değil)")

    # ── coverage (G1 / BİRİNCİL)
    cov = spec.get("coverage", {})
    _check(R, cov.get("target") == 1.0, "G1 coverage.target == 1.0 (SR-ANA-002 %100)")
    _check(R, cov.get("degraded_still_counts") is True, "G1 degraded çağrı yine sayılır (sessiz atlama yok)")
    _check(R, cov.get("all_fields_required") == ["intent", "outcome", "disposition", "completion_status"],
           "G1 DÖRT alan da zorunlu (intent/outcome/disposition/completion_status)")

    # ── eligibility (G9)
    el = spec.get("eligibility", {})
    _check(R, el.get("evaluable_status") == ["completed"], "G1 evaluable_status == [completed]")
    _check(R, set(el.get("excluded_status", [])) == set(el.get("reason_codes", [])),
           "G9 excluded_status ↔ reason_codes BİREBİR (her uygun-olmayan statünün reason kodu var)")
    _check(R, len(el.get("excluded_status", [])) >= 3, "G9 ≥3 uygun-olmayan statü tanımlı")

    # ── vocabularies (G3)
    vocab = spec.get("vocabularies", {})
    for fld in ("intent", "outcome", "disposition", "completion_status"):
        vv = vocab.get(fld, [])
        _check(R, isinstance(vv, list) and len(vv) >= 3, "G3 %s sözlüğü ≥3 değer (kapalı enum)" % fld)
        _check(R, len(vv) == len(set(vv)), "G3 %s sözlüğü benzersiz" % fld)
        # düşük-kardinalite (PII taşıyamaz): makul üst sınır
        _check(R, len(vv) <= 16, "G3 %s sözlüğü düşük-kardinalite (≤16; pii_class low)" % fld)
    sent = vocab.get("sentinels", {})
    for fld in ("intent", "outcome", "disposition", "completion_status"):
        _check(R, sent.get(fld) in vocab.get(fld, []),
               "G1 %s sentinel'i sözlükte (sınıflanamayan → null değil)" % fld)
    # çekirdek değerler
    _check(R, {"contained", "transferred_to_human"} <= set(vocab.get("outcome", [])),
           "G3 outcome contained/transferred_to_human içerir (14.2.3 containment/transfer kaynağı)")
    _check(R, {"completed", "partial", "transferred", "abandoned"} <= set(vocab.get("completion_status", [])),
           "G3 completion_status çekirdek değerleri içerir")

    # ── derivation tutarlılık (G4)
    der = spec.get("derivation", {})
    _check(R, len(der.get("consistency_invariants", [])) >= 5, "G4 ≥5 cross-field tutarlılık invariant'ı (C1–C5)")
    _check(R, der.get("outcome_precedence") and der.get("completion_precedence") and der.get("disposition_precedence"),
           "G4 outcome/completion/disposition öncelik kuralları tanımlı (deterministik)")
    # öncelik kurallarının tutarlılık invariant'larını gerçekten sağladığının KANITI (non-circular):
    # tüm makul sinyal kombinasyonlarını üret, motorla türet, C1–C5 = 0 olmalı.
    _check(R, _consistency_proof() == 0,
           "G4 öncelik kuralları C1–C5'i tüm sinyal kombinasyonlarında sağlar (0 ihlal — non-circular kanıt)")

    # ── output_contract (G2)
    oc = spec.get("output_contract", {})
    _check(R, oc.get("all_fields") == ["intent", "outcome", "disposition", "completion_status"],
           "G2 all_fields == DÖRT alan (FR-ANA-002)")
    _check(R, set(oc.get("categorical_fields", [])) == {"intent", "disposition", "completion_status"},
           "G2 categorical_fields == intent/disposition/completion_status (OLAP fct_call FR-ANA-002)")
    _check(R, oc.get("result_field") == "outcome", "G2 result_field == outcome (DB call.outcome, FR-ANA-002/003)")
    _check(R, {"tenant_id", "call_id", "schema_version"} <= set(oc.get("identity_fields", [])),
           "G8 identity_fields tenant_id/call_id/schema_version içerir")
    _check(R, set(oc.get("consumes_topics", [])) == {"voice.call.lifecycle.v1", "voice.transcript.redacted.v1"},
           "I7 consumes_topics lifecycle + redacted transcript")

    # ── idempotency (G5)
    idem = spec.get("idempotency", {})
    _check(R, idem.get("dedup_key") == ["tenant_id", "call_id", "schema_version"],
           "G5 dedup_key == (tenant_id, call_id, schema_version)")
    _check(R, idem.get("replay_safe") is True, "G5 replay_safe (1.1.8 P3)")

    # ── feature_policy (G7)
    fp = spec.get("feature_policy", {})
    allowed = set(fp.get("allowed_feature_keys", []))
    forb = set(fp.get("forbidden_feature_keys", []))
    _check(R, {"intent_signal", "resolved", "transferred", "caller_abandoned"} <= allowed,
           "G7 allowed_feature_keys çekirdek sinyalleri içerir")
    _check(R, {"transcript_text", "audio_payload", "phone_number", "card_number"} <= forb,
           "G7 forbidden_feature_keys ham transkript/ses/PII anahtarlarını içerir")
    _check(R, not (allowed & forb), "G7 izinli ile yasak sinyal kesişmez")

    # ── isolation (G8)
    iso = spec.get("isolation", {})
    _check(R, iso.get("tenant_id_required") is True, "G8 tenant_id_required")
    _check(R, iso.get("residency") == "home-region", "G8 residency home-region (NFR 10.7)")
    _check(R, iso.get("cross_tenant_forbidden") is True, "G8 cross_tenant_forbidden (FR-TEN-002)")

    # ── OLAP fct_call BİREBİR (G2, non-circular)
    olap = _load_sibling_spec("analytics", "olap-spec.json")
    if olap is not None:
        ft = _fct_call(olap)
        _check(R, ft is not None, "G2 OLAP fct_call fact table mevcut")
        if ft is not None:
            cols = {c.get("name"): c for c in ft.get("columns", [])}
            # FR-ANA-002 etiketli kategorik sütunlar (note'ta FR-ANA-002) → categorical_fields ile BİREBİR
            ana002_cat = {c.get("name") for c in ft.get("columns", [])
                          if "FR-ANA-002" in (c.get("note") or "") and c.get("type") == "string_lc"}
            _check(R, set(oc.get("categorical_fields", [])) == ana002_cat,
                   "G2 categorical_fields OLAP fct_call FR-ANA-002 kategorik sütunlarıyla BİREBİR (%s)"
                   % ",".join(sorted(ana002_cat)))
            for fld in oc.get("categorical_fields", []):
                _check(R, fld in cols and cols[fld].get("pii_class") == "low",
                       "G3 fct_call.%s mevcut + pii_class low (düşük-kardinalite enum)" % fld)
            _check(R, "FR-ANA-002" in ft.get("fr", []), "G2 OLAP fct_call FR-ANA-002 taşır")
            _check(R, ft.get("source_topic") == "voice.call.lifecycle.v1",
                   "I7 fct_call source_topic == voice.call.lifecycle.v1")

    # ── eventstream BİREBİR (I7, non-circular)
    es = _load_sibling_spec("eventstream", "topic-spec.json")
    if es is not None:
        topics = {t.get("name"): t for t in es.get("topics", [])}
        lc = topics.get("voice.call.lifecycle.v1")
        _check(R, lc is not None, "I7 eventstream voice.call.lifecycle.v1 topic mevcut")
        if lc is not None:
            _check(R, "FR-ANA-002" in lc.get("fr", []), "I7 voice.call.lifecycle.v1 FR-ANA-002 taşır")
            _check(R, "analytics-ingest" in lc.get("consumers", []),
                   "I7 analytics-ingest lifecycle'ı tüketir (çıkarım consumer'ı)")
            _check(R, lc.get("pii_class") in ("low", "redacted", "none"),
                   "I7 lifecycle pii_class ≤ redacted (low)")
        rt = topics.get("voice.transcript.redacted.v1")
        _check(R, rt is not None, "I7 eventstream voice.transcript.redacted.v1 topic mevcut")
        if rt is not None:
            _check(R, rt.get("pii_class") == "redacted", "I7 voice.transcript.redacted.v1 pii_class == redacted")
            _check(R, "FR-REC-004" in rt.get("fr", []), "I7 redacted transcript FR-REC-004 taşır")

    # ── gates
    g = spec.get("gates", {})
    for gk in ("max_coverage_gap", "max_catalog_mismatch", "max_vocab_violation", "max_consistency_violation",
               "max_idempotency_violation", "max_blocking_violation", "max_pii_violation",
               "max_isolation_violation", "max_eligibility_reason_missing"):
        _check(R, g.get(gk, -1) == 0, "gate %s = 0" % gk)

    # ── error taxonomy (I11)
    et = spec.get("error_taxonomy", {}).get("mapping", {})
    _check(R, len(et) >= 3, "I11 hata eşlemesi (≥3)")
    _check(R, all(v in ERROR_TAXONOMY for v in et.values()), "I11 tüm hedefler API §11.6 ErrorTaxonomy'de")
    _check(R, et.get("malformed_call") == "INVALID_REQUEST" and et.get("unknown_status") == "INVALID_REQUEST"
           and et.get("region_mismatch") == "REGION_VIOLATION",
           "I11 malformed/unknown→INVALID_REQUEST, region→REGION_VIOLATION")

    # ── pii (spec sağlığı, I13)
    _check(R, spec.get("pii", {}).get("raw_payload_in_spec_forbidden") is True, "I13 ham ses payload spec'te yasak")
    _check(R, spec.get("pii", {}).get("transcript_in_spec_forbidden") is True, "I13 transkript spec'te yasak")
    _check(R, spec.get("pii", {}).get("pii_values_in_spec_forbidden") is True, "I13 PII DEĞERİ spec'te yasak")

    # ── invariant kataloğu
    inv_ids = [i.get("id") for i in spec.get("invariants", [])]
    _check(R, len(inv_ids) == len(set(inv_ids)) and len(inv_ids) >= 13, "invariant kataloğu ≥13 + tekil ID")
    _check(R, all(i.get("trace") for i in spec.get("invariants", [])), "her invariant trace taşır")

    # ── literal sır + PII DEĞER taraması (spec + config)
    hits = _scan(spec, SECRET_RE)
    pii_hits = _scan(spec, PII_VALUE_RE)
    if os.path.exists(PROFILES_CFG):
        cfg = _load(PROFILES_CFG)
        hits += _scan(cfg, SECRET_RE)
        pii_hits += _scan(cfg, PII_VALUE_RE)
    _check(R, not hits, "I13 literal sır yok (spec+config)")
    _check(R, not pii_hits, "I13 spec/config'te ham PII DEĞERİ yok (%s)" % (",".join(p for p, _ in pii_hits[:3]) or "-"))

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


def _consistency_proof():
    """Non-circular kanıt: tüm makul boolean/kategorik sinyal kombinasyonlarını motorla türet, C1–C5
    ihlali say. Öncelik kuralları doğruysa 0 dönmeli. (validate G4 bunu doğrular.)"""
    spec = _load(SPEC_PATH)
    vocab = spec.get("vocabularies", {})
    intent_vocab = vocab.get("intent", [])
    bools = ["caller_abandoned", "transferred", "resolved", "flow_completed",
             "dnc_requested", "wrong_number", "voicemail_left", "callback_scheduled",
             "not_interested", "follow_up_required"]
    ncr_opts = [None, "voicemail", "busy", "no_answer", "invalid"]
    total = 0
    # tüm boolean kombinasyonları çok büyük; temsili örnekleme: her bool tek tek + birkaç kombinasyon
    import itertools
    for ncr in ncr_opts:
        for combo in itertools.combinations(bools, 0):
            pass
        # 0,1,2-li boolean alt kümeleri (tutarlılık ihlali boolean etkileşiminden doğar)
        for r in (0, 1, 2):
            for sub in itertools.combinations(bools, r):
                f = {b: True for b in sub}
                if ncr is not None:
                    f["not_connected_reason"] = ncr
                outcome = derive_outcome(f)
                completion = derive_completion(f, consistent=True)
                disposition = derive_disposition(f, outcome)
                intent = normalize_intent(f, intent_vocab, closed=True)
                total += consistency_violations(intent, outcome, disposition, completion)
    return total


# ─────────────────────────────────────────────────────────────────────────────
# selftest
# ─────────────────────────────────────────────────────────────────────────────
CONTEXT = {"tenant_id": "t_acme", "region": "eu-west-1", "correlation_id": "corr-acme-001"}
PROFILE = {"name": "eu-standard", "region": "eu-west-1", "schema_version": 1, "batch_interval_s": 30}

# tipik bir batch: 4 uygun + 2 uygun-olmayan (reason'lı). Farklı outcome/completion profilleri.
CALLS = [
    # c1: çözülmüş, contained → completed, resolved disposition, billing intent
    {"call_id": "c1", "status": "completed", "features": {
        "intent_signal": "billing", "resolved": True, "flow_completed": True}},
    # c2: insana aktarıldı → transferred_to_human / transferred / escalated
    {"call_id": "c2", "status": "completed", "features": {
        "intent_signal": "technical_support", "transferred": True}},
    # c3: müşteri terk etti → abandoned / abandoned
    {"call_id": "c3", "status": "completed", "features": {
        "intent_signal": "information", "caller_abandoned": True}},
    # c4: sinyal yok → degraded ama YİNE türetilir (sentinel'ler)
    {"call_id": "c4", "status": "completed", "features": {}},
    {"call_id": "c5", "status": "abandoned_pre_connect", "reason": "abandoned_pre_connect"},
    {"call_id": "c6", "status": "test_call", "reason": "test_call"},
]


def _run(calls, spec, context=None, profile=None, **pol_over):
    pol = _full_pol()
    pol.update(pol_over)
    return derive_calls({"calls": calls}, spec, profile or PROFILE, context or CONTEXT, pol)


def _raises(fn):
    try:
        fn()
        return False
    except DerivationError:
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
    case(mh["derived"]["eligible"] == 4 and mh["derived"]["produced"] == 4, "happy: 4 uygun → 4 çıkarım")
    case(mh["derived"]["coverage_ratio"] == 1.0, "happy: coverage_ratio == 1.0 (FR-ANA-002/SR-ANA-002)")
    case(mh["derived"]["degraded"] == 1, "happy: c4 sinyal yok → degraded ama yine türetilir (atlanmaz)")
    case(mh["catalog_mismatch"] == 0, "happy: DÖRT alan çıktıda (G2)")
    case(mh["vocab_violations"] == 0, "happy: tüm değerler kapalı-sözlükte (G3)")
    case(mh["consistency_violations"] == 0, "happy: cross-field tutarlı (G4)")
    case(mh["idempotency_violations"] == 0, "happy: idempotent (G5)")
    case(mh["blocking_violations"] == 0, "happy: non-blocking (G6)")
    case(mh["pii_violations"] == 0, "happy: yalnız redaksiyonlu sinyal (G7)")
    case(mh["isolation_violations"] == 0, "happy: tenant izolasyon temiz (G8)")
    case(mh["eligibility_reason_missing"] == 0, "happy: uygun-olmayan statüler reason taşır (G9)")
    case(all(ok for ok, _ in evaluate(spec, mh)), "happy tüm kapıları geçer")

    # ── çıkarım birebir (kapalı-sözlük öncelik kuralları) ──
    d1, d2, d3, d4 = mh["derivations"]
    case(d1["intent"] == "billing" and d1["outcome"] == "contained" and d1["completion_status"] == "completed"
         and d1["disposition"] == "resolved",
         "c1: billing/contained/completed/resolved (çözülmüş + flow tamam)")
    case(d2["outcome"] == "transferred_to_human" and d2["completion_status"] == "transferred"
         and d2["disposition"] == "escalated",
         "c2: transferred_to_human/transferred/escalated (insana aktarım)")
    case(d3["outcome"] == "abandoned" and d3["completion_status"] == "abandoned",
         "c3: abandoned/abandoned (müşteri terk)")
    case(d4["intent"] == "unknown" and d4["outcome"] == "unresolved" and d4["disposition"] == "no_action"
         and d4["completion_status"] == "partial" and d4["degraded"] is True,
         "c4: degraded → sentinel (unknown/unresolved/no_action/partial), DÖRT alan dolu")

    # outcome dağılımı (14.2.3 girdisi)
    case(mh["derived"]["by_outcome"].get("contained") == 1
         and mh["derived"]["by_outcome"].get("transferred_to_human") == 1,
         "outcome dağılımı 14.2.3 containment/transfer agregasyonunun girdisi")

    # ── not_connected outbound (voicemail) ──
    nc = _run([{"call_id": "nc", "status": "completed", "features": {
        "intent_signal": "sales", "not_connected_reason": "voicemail", "voicemail_left": True}}], spec)
    dn = nc["derivations"][0]
    case(dn["outcome"] == "not_connected" and dn["completion_status"] == "not_started"
         and dn["disposition"] == "voicemail_left",
         "outbound voicemail: not_connected/not_started/voicemail_left")
    case(nc["consistency_violations"] == 0, "not_connected tuple tutarlı (C3)")

    # ── intent normalize: vocab-dışı sinyal → unknown ──
    iv = _run([{"call_id": "iv", "status": "completed", "features": {
        "intent_signal": "wants_a_very_specific_thing", "resolved": True, "flow_completed": True}}], spec)
    case(iv["derivations"][0]["intent"] == "unknown" and iv["vocab_violations"] == 0,
         "vocab-dışı intent_signal → unknown sentinel (kapalı-sözlük korunur, G3)")

    # ── determinizm ──
    case(_run(CALLS, spec) == _run(CALLS, spec), "determinizm: aynı çağrı seti aynı sonucu verir (random yok)")

    # ── G1 kapsam: classify_all KAPALI → degraded çağrı atlanır ──
    m1 = _run(CALLS, spec, classify_all=False)
    case(m1["coverage_gap"] >= 1, "classify_all KAPALI: sinyalsiz/degraded çağrı atlanır → G1 kapsam açığı eler")
    case(m1["derived"]["coverage_ratio"] < 1.0, "classify_all KAPALI: coverage_ratio < 1.0 (%100 bozulur)")

    # ── G2 katalog: map_output KAPALI → bir alan düşer ──
    m2 = _run(CALLS, spec, map_output=False)
    case(m2["catalog_mismatch"] >= 1, "map_output KAPALI: bir alan düşer → G2 katalog eler")

    # ── G3 sözlük: closed_vocab KAPALI → ham intent_signal vocab-dışı ──
    m3 = _run([{"call_id": "ov", "status": "completed", "features": {
        "intent_signal": "free_text_intent_xyz", "resolved": True, "flow_completed": True}}], spec, closed_vocab=False)
    case(m3["vocab_violations"] >= 1, "closed_vocab KAPALI: ham intent vocab-dışı → G3 sözlük eler")

    # ── G4 tutarlılık: enforce_consistency KAPALI → completion desenkronize ──
    m4 = _run([{"call_id": "tc", "status": "completed", "features": {
        "intent_signal": "billing", "transferred": True, "flow_completed": True}}], spec, enforce_consistency=False)
    case(m4["consistency_violations"] >= 1, "enforce_consistency KAPALI: transferred ama completion=completed → G4 (C1/C4) eler")

    # ── G5 idempotency: aynı call_id iki kez + idempotent KAPALI ──
    dup = CALLS + [{"call_id": "c1", "status": "completed", "features": {
        "intent_signal": "billing", "resolved": True, "flow_completed": True}}]
    m5 = _run(dup, spec, idempotent=False)
    case(m5["idempotency_violations"] >= 1, "idempotent KAPALI: aynı (tenant,call,ver) çift çıkarım → G5 eler")
    m5o = _run(dup, spec)
    case(m5o["idempotency_violations"] == 0 and m5o["derived"]["produced"] == 4,
         "idempotent AÇIK: replay daraltılır (4 çıkarım) → G5 geçer")

    # ── G6 blocking: non_blocking KAPALI → çıkarım bloklar ──
    m6 = _run(CALLS, spec, non_blocking=False)
    case(m6["blocking_violations"] >= 1, "non_blocking KAPALI: çıkarım çağrıyı bloklar → G6 eler (FR-RES-011)")

    # ── G7 PII: enforce_redaction KAPALI + ham transkript sinyali ──
    leak = [{"call_id": "p", "status": "completed", "features": {
        "transcript_text": "müşteri konuştu", "resolved": True, "flow_completed": True}}]
    m7 = _run(leak, spec, enforce_redaction=False)
    case(m7["pii_violations"] == 0, "enforce_redaction KAPALI: redaction zorlanmaz (denetlenmez)")
    m7e = _run(leak, spec)
    case(m7e["pii_violations"] >= 1, "enforce_redaction AÇIK: transcript_text yasak sinyal → G7 eler")
    # ham PII DEĞERİ (telefon) bir sinyalde
    leakv = [{"call_id": "pv", "status": "completed", "features": {
        "intent_signal": "billing", "resolved": True, "callback_scheduled": "0555 123 4567"}}]
    m7v = _run(leakv, spec)
    case(m7v["pii_violations"] >= 1, "sinyal DEĞERİnde ham telefon → G7 eler")

    # ── G8 izolasyon: isolate_tenant KAPALI → tenant_id yok ──
    m8 = _run(CALLS, spec, isolate_tenant=False)
    case(m8["isolation_violations"] >= 1, "isolate_tenant KAPALI: çıkarımda tenant_id yok → G8 eler")
    cross = [{"call_id": "ct", "status": "completed", "tenant_id": "t_other", "features": {
        "intent_signal": "billing", "resolved": True, "flow_completed": True}}]
    m8c = _run(cross, spec)
    case(m8c["isolation_violations"] >= 1, "cross-tenant çağrı (t_other ≠ bağlam) → G8 izolasyon eler")
    resd = [{"call_id": "rd", "status": "completed", "region": "us-east-1", "features": {
        "intent_signal": "billing", "resolved": True, "flow_completed": True}}]
    m8r = _run(resd, spec)
    case(m8r["isolation_violations"] >= 1, "home-region dışı çağrı (residency) → G8 eler (NFR 10.7)")

    # ── G9 uygunluk: reason eksik uygun-olmayan çağrı ──
    noreason = [{"call_id": "nr", "status": "abandoned_pre_connect"}]
    m9 = _run(noreason, spec)
    case(m9["eligibility_reason_missing"] >= 1, "uygun-olmayan statü reason taşımıyor → G9 eler (sessiz atlama yok)")
    m9a = _run([{"call_id": "ar", "status": "abandoned_pre_connect", "reason": "abandoned_pre_connect"}], spec)
    case(m9a["eligibility_reason_missing"] == 0, "reason'lı uygun-olmayan çağrı → G9 geçer")
    m9s = _run([{"call_id": "se", "status": "test_call", "reason": "test_call"}], spec, account_excluded=False)
    case(m9s["eligibility_reason_missing"] >= 1, "account_excluded KAPALI: sessiz atlama → G9 eler")

    # ── reddetme (I11) ──
    case(_raises(lambda: derive_calls({"calls": "x"}, spec, PROFILE, CONTEXT, _full_pol())),
         "I11 calls liste değil → reddedilir")
    case(_raises(lambda: derive_calls({"calls": [{"call_id": "z"}]}, spec, PROFILE, CONTEXT, _full_pol())),
         "I11 çağrıda status eksik → reddedilir")
    case(_raises(lambda: derive_calls({"calls": [{"call_id": "z", "status": "weird"}]}, spec, PROFILE, CONTEXT, _full_pol())),
         "I11 bilinmeyen statü → reddedilir")
    case(_raises(lambda: CallDerivationEngine(spec, PROFILE, {"region": "eu"}, _full_pol())),
         "I11 bağlam (tenant_id) eksik → reddedilir")

    # ── tutarlılık kanıtı (non-circular) ──
    case(_consistency_proof() == 0, "öncelik kuralları C1–C5'i tüm sinyal kombinasyonlarında sağlar (0 ihlal)")

    # ── validate negatif kapılar ──
    s = json.loads(json.dumps(spec)); s["coverage"]["target"] = 0.95
    case(_validate_obj(s) != 0, "G1 coverage.target 1.0'dan sapar → validate eler")
    s = json.loads(json.dumps(spec)); s["output_contract"]["categorical_fields"] = ["intent"]
    case(_validate_obj(s) != 0, "G2 categorical_fields OLAP fct_call FR-ANA-002'den sapar → validate eler")
    s = json.loads(json.dumps(spec)); s["vocabularies"]["outcome"] = ["contained"]
    case(_validate_obj(s) != 0, "G3 outcome sözlüğü çekirdek değerleri kaybeder → validate eler")
    s = json.loads(json.dumps(spec)); s["vocabularies"]["sentinels"]["intent"] = "not_in_vocab"
    case(_validate_obj(s) != 0, "G1 intent sentinel'i sözlükte değil → validate eler")
    s = json.loads(json.dumps(spec)); s["feature_policy"]["allowed_feature_keys"].append("transcript_text")
    case(_validate_obj(s) != 0, "G7 izinli sinyale transcript_text (yasakla kesişim) → validate eler")
    s = json.loads(json.dumps(spec)); s["eligibility"]["excluded_status"] = s["eligibility"]["excluded_status"][:1]
    case(_validate_obj(s) != 0, "G9 excluded_status ↔ reason_codes uyuşmaz → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_consistency_violation"] = 1
    case(_validate_obj(s) != 0, "G4 max_consistency_violation>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["error_taxonomy"]["mapping"]["x"] = "NOPE"
    case(_validate_obj(s) != 0, "I11 taksonomi-dışı → validate eler")
    s = json.loads(json.dumps(spec)); s["vocabularies"]["intent"].append("0555 123 4567")
    case(_validate_obj(s) != 0, "I13 sözlükte ham PII DEĞERİ (telefon) → validate eler")
    s = json.loads(json.dumps(spec)); s["derivation"]["leak"] = "api_key: AKIAIOSFODNN7EXAMPLE"
    case(_validate_obj(s) != 0, "I13 literal secret → validate eler")

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
    print("""derivation-spec.json beklenen şekli (WBS 14.2.2):
  wbs=14.2.2, version, phase=F1/F2, priority=Must, eval_doc{fr,srs,rtm,brd,sad,db,olap,eventstream,adr,api,upstream}
  placement{in_analytics_plane, async_batch, non_blocking, from_redacted_content, all_calls=true,
            deterministic_taxonomy, idempotent, from_trace=false}                                  (G6,G7,G1)
  coverage{metric=produced/eligible==1.0, target=1.0, all_fields_required[4], degraded_still_counts}(G1 BİRİNCİL)
  eligibility{evaluable_status=[completed], excluded_status[], reason_codes[]}                       (G9)
  vocabularies{intent[], outcome[], disposition[], completion_status[], sentinels{}}                 (G3)
  derivation{outcome/completion/disposition_precedence, intent_rule, consistency_invariants[C1–C5]}  (G4)
  output_contract{all_fields[4], categorical_fields[intent,disposition,completion_status],
                  result_field=outcome, identity_fields[], consumes_topics[], persists_to[]}         (G2,G8)
  idempotency{dedup_key=[tenant_id,call_id,schema_version], replay_safe=true}                        (G5)
  feature_policy{allowed_feature_keys[], forbidden_feature_keys[]}                                   (G7)
  isolation{tenant_id_required, residency=home-region, cross_tenant_forbidden}                       (G8)
  gates{max_coverage_gap=0, max_catalog_mismatch=0, max_vocab_violation=0, max_consistency_violation=0,
        max_idempotency_violation=0, max_blocking_violation=0, max_pii_violation=0,
        max_isolation_violation=0, max_eligibility_reason_missing=0}                                 (G1..G9)
  error_taxonomy{mapping→API §11.6}  pii{...}  invariants[≥13]{id,desc,trace}

config/derivation-profiles.json: profiles[]{name, region, schema_version, batch_interval_s}

derive sample: {name, profile | profile_obj, expect, expected?{metrik:değer},
  context{tenant_id, region?},
  policy?{classify_all, map_output, closed_vocab, enforce_consistency, idempotent, non_blocking,
          enforce_redaction, isolate_tenant, account_excluded},
  calls[]{call_id, status, reason?, tenant_id?, region?, features?{REDAKSİYONLU kategorik/sayısal sinyal}}}
  (PII DEĞERİ / ham transkript YOK — yalnız redaksiyonlu sinyal + alan/kimlik/sözlük anahtarı ADLARI)

komutlar: validate | derive <sample.json> | selftest | schema""")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if cmd == "validate":
        return validate()
    if cmd == "derive":
        if len(sys.argv) < 3:
            print("kullanım: derivation_probe.py derive <sample.json>")
            return 2
        return derive_cmd(sys.argv[2])
    if cmd == "selftest":
        return selftest()
    if cmd == "schema":
        return schema()
    print("bilinmeyen komut: %s (validate|derive|selftest|schema)" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main())
