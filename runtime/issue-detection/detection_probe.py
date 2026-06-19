#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
detection_probe.py — WBS 14.2.4 Yanlış bilgi/tool hatası/güvenlik ihlali tespiti

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only statik + davranış kapısı.
`runtime/containment-report/` (14.2.3) / `runtime/qa-eval/` (14.2.1) probe disipliniyle birebir; burada
deterministik bir ANALYTICS-PLANE TESPİT (DETECTION) motoru (SAD §4.2 async batch; analytics-ingest consumer)
simülatörü (saf; random YOK).

TESPİT MOTORU — Analytics/Ops Plane'de (SAD §4.2/§171, FR-RES-011) async/non-blocking; çağrı SONRASI
redaksiyonlu sinyalden (qa.evaluation.v1 + ops.tool.execution.v1 + governance.audit.v1) HER uygun çağrı için
ÜÇ kategorik ikili işaret (flag_misinformation / flag_tool_error / flag_security; FR-ANA-004) deterministik
kurallarla türetir ve OLAP fct_call/fct_qa_evaluation flag_* sütunlarına + call_evaluation.flags JSONB'ye yazar:
  • Recall (G1):     ENJEKTE edilen (etiketli) her pozitif vaka tespit edilir (missed_detection=0, yanlış-negatif yok) — SR-ANA-004 T, BİRİNCİL.
  • Precision (G2):  enjekte-temiz vakada sahte işaret yok (false_positive=0).
  • Tutarlılık (G3): işaret fires ⟺ ≥1 reason_code tetiklendi (boş-reason/yetim reason yok).
  • Sözlük (G4):     kategori {misinformation,tool_error,security_violation} + reason_code kapalı-sözlük + flag_column OLAP fct_call/fct_qa_evaluation BİREBİR (non-circular).
  • Kapsam (G5):     HER uygun çağrı ÜÇ kategoride değerlendirilir (produced==eligible×3; tespit-yok ≠ atlama).
  • İdempotent (G6): (tenant_id,call_id,schema_version) bir kez; at-least-once çift-üretim yapmaz (replay-safe).
  • İzolasyon (G7):  her değerlendirme tek tenant_id + cross-tenant yok + residency (FR-TEN-002/NFR 10.7).
  • PII (G8):        yalnız redaksiyonlu sinyal + düşük-kardinalite boyut; çıktı PII/serbest-metin reason taşımaz (FR-REC-004).
  • Async (G9):      analytics plane non-blocking; tespit başarısızlığı canlı çağrıyı etkilemez (FR-RES-011).

KAPSAM AYRIMI: otomatik SKOR → 14.2.1 · per-call ÇIKARIM → 14.2.2 · containment/transfer ORANI → 14.2.3 ·
KRİTİK işaretleme (flag_critical, FR-ANA-008; bu motorun İŞARETLERİNİ TÜKETİR) → 14.2.5 · MANUEL skor → 14.2.6 ·
sürüm karşılaştırma → 14.2.7 · dashboard/export → 14.2.8. Burada YALNIZ yanlış-bilgi/tool-hata/güvenlik tespiti.

Komutlar:
  validate              detection-spec.json'ı invariant'lara + OLAP/eventstream çapraz-tutarlılığa + config'e karşı doğrular.
  detect <sample>       Deterministik IssueDetectionEngine — çağrı seti → işaret + reason_code + tespit doğruluğu + HARD kapılar (G1–G9); →çıkış kodu.
  selftest              İyi/kötü spec+sample ile kapıların doğru tetiklendiğini kanıtlar.
  schema                Beklenen spec şeklini özetler.

Sunucu/credential GEREKMEZ. detect gerçek motor yerine deterministik simülasyondur (canlıda qa.evaluation.v1 /
ops.tool.execution.v1 / governance.audit.v1 consumer + OLAP fct_call/fct_qa_evaluation + call_evaluation sink,
SAD §4.2/§12.1; ADR-007). Ham ses payload/transkript METNİ/PII DEĞERİ YOK — örnekler yalnız REDAKSİYONLU
sayısal/kategorik sinyal + düşük-kardinalite boyut/kimlik anahtarı ADLARI + enjekte yer-doğrusu etiketi taşır.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "detection-spec.json")
PROFILES_CFG = os.path.join(HERE, "config", "detection-profiles.json")

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
# ISO tarih (period boyutu, ör. 2026-06-01) düşük-kardinalite boyut anahtarıdır — PII DEĞİL.
DATE_RE = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_placeholder(v):
    return isinstance(v, str) and PLACEHOLDER_RE.match(v) is not None


def _pii_value(v):
    """v ham PII DEĞERİ mi (telefon/kart/IBAN/e-posta)? Placeholder ${ENV} ve ISO tarih (period) muaf."""
    return isinstance(v, str) and not _is_placeholder(v) and not DATE_RE.match(v) and bool(PII_VALUE_RE.search(v))


class DetectError(Exception):
    """Geçersiz/eksik tespit girdisi veya bilinmeyen kategori — sessizce kabul yok, reddet (I12)."""


# ─────────────────────────────────────────────────────────────────────────────
# Tespit motoru — deterministik kural değerlendirme (saf; random YOK)
# ─────────────────────────────────────────────────────────────────────────────
class IssueDetectionEngine:
    """Analytics plane'de async/non-blocking; redaksiyonlu sinyalden ÜÇ kategorik ikili işaret türetir +
    tespit doğruluğu (recall/precision injected etikete karşı) + tutarlılık + sözlük + kapsam + idempotency +
    tenant izolasyon + PII disiplinine karşı denetler. Saf; random YOK.

    policy bayrakları buggy bir Engine'i simüle eder (14.2.x deseni):
      apply_rules        : sinyalden işaret türet (kapalı → işaret hiç fires olmaz → enjekte pozitifler kaçar, G1 recall)
      overflag           : yalnız tetiklenen reason'da işaret fires (AÇIK/buggy → her kategori körlemesine fires → enjekte-temizde sahte işaret, G2)
      enforce_consistency: işaret ⟺ reason_code (kapalı → işaret fires ama reason boş → G3 tutarlılık)
      detect_all         : HER çağrı ÜÇ kategoride değerlendirilir (kapalı → security kategorisi sessizce atlanır → G5 kapsam açığı)
      closed_taxonomy    : reason kapalı-sözlükte (kapalı → serbest-metin reason → G4)
      idempotent         : (tenant,call,schema) bir kez (kapalı → replay çift-üretim, G6)
      isolate_tenant     : tek-tenant değerlendirme (kapalı → cross-tenant çağrı karışır, G7)
      enforce_redaction  : ham PII/transkript girdisini reddet (kapalı → transcript_text geçer, G8)
      non_blocking       : analytics plane non-blocking (kapalı → tespit canlı çağrıyı bloklar, G9)
    """

    def __init__(self, spec, profile, context, policy):
        self.spec = spec
        self.context = dict(context or {})
        self.pol = policy

        cat = spec.get("categories", {})
        self.cat_set = list(cat.get("set", []))
        self.flag_column = dict(cat.get("flag_column", {}))
        self.reason_codes = {k: list(v) for k, v in cat.get("reason_codes", {}).items()}

        self.rules = list(spec.get("detection_rules", {}).get("rules", []))
        self.label_key = spec.get("ground_truth", {}).get("label_key", "injected")

        elig = spec.get("eligibility", {})
        self.evaluable = set(elig.get("evaluable_statuses", ["completed"]))
        self.excluded = set(elig.get("excluded_statuses", []))

        fp = spec.get("feature_policy", {})
        self.allowed_keys = set(fp.get("allowed_input_keys", []))
        self.forbidden_keys = set(fp.get("forbidden_input_keys", []))

        self.region_pin = profile.get("region")
        self.schema_version = profile.get("schema_version", 1)
        # profil override (eşikleri yalnız daha duyarlı/sıkı yönde değiştirebilir)
        self.threshold_override = dict(profile.get("threshold_override", {}))

        if not self.context.get("tenant_id"):
            raise DetectError("tespit bağlamı eksik: tenant_id → INVALID_REQUEST")
        if not self.context.get("region"):
            raise DetectError("tespit bağlamı eksik: region → INVALID_REQUEST")

        # sayaçlar (HARD kapı kanıtı)
        self.missed_detection = 0
        self.false_positive = 0
        self.consistency_violations = 0
        self.vocab_violations = 0
        self.coverage_gap = 0
        self.idempotency_violations = 0
        self.isolation_violations = 0
        self.pii_violations = 0
        self.blocking_violations = 0

        self.eligible_count = 0       # uygun çağrı (kapsam paydası)
        self.categories_produced = 0  # değerlendirilen kategori (uygun çağrı × kategori)
        self.evaluated = []           # per-call sonuç
        self.flag_totals = {c: 0 for c in self.cat_set}
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

    def _threshold(self, rule):
        thr = rule.get("threshold", 0)
        return self.threshold_override.get(rule.get("reason"), thr)

    def _rule_fires(self, rule, call):
        """Tek tespit kuralı tetikleniyor mu (deterministik eşik)?"""
        sig = rule.get("signal")
        op = rule.get("op")
        if op == "lt" and rule.get("compare_to"):
            # ungrounded_answer: grounded_answers < total_answers (total>0)
            total = call.get(rule["compare_to"], 0) or 0
            grounded = call.get(sig, 0) or 0
            return total > 0 and grounded < total
        val = call.get(sig, 0) or 0
        thr = self._threshold(rule)
        if op == "gt":
            return val > thr
        if op == "ge":
            return val >= thr
        return False

    def _detect_one(self, call):
        """Bir çağrıda ÜÇ kategoride işaret + reason_code üretir (deterministik)."""
        flags = {}
        reasons = {c: [] for c in self.cat_set}
        # detect_all KAPALI → security_violation kategorisini sessizce atla (G5 kapsam açığı)
        cats_to_eval = list(self.cat_set)
        if not self.pol.get("detect_all", True):
            cats_to_eval = [c for c in cats_to_eval if c != "security_violation"]

        fired = {c: [] for c in self.cat_set}
        for rule in self.rules:
            c = rule.get("category")
            if c not in cats_to_eval:
                continue
            if self.pol.get("apply_rules", True) and self._rule_fires(rule, call):
                fired[c].append(rule.get("reason"))

        for c in self.cat_set:
            evaluated = c in cats_to_eval
            if not evaluated:
                # kategori atlandı → kapsam açığı; işaret üretilmez
                continue
            self.categories_produced += 1

            rs = list(dict.fromkeys(fired[c]))  # tekilleştir, sırayı koru
            # closed_taxonomy KAPALI → serbest-metin reason enjekte et (G4)
            if not self.pol.get("closed_taxonomy", True) and rs:
                rs = rs + ["free_text_reason_%s" % c]

            # işaret kararı
            if self.pol.get("overflag", False):
                fires = True                      # buggy: körlemesine fires (sahte işaret)
                if not rs:
                    rs = []                        # boş reason ile fires → tutarsızlık (G3'te yakalanır)
            else:
                fires = len(rs) > 0

            # enforce_consistency KAPALI → fires=true ama reason listesini boşalt (G3)
            if not self.pol.get("enforce_consistency", True) and fires:
                rs = []

            flags[self.flag_column[c]] = bool(fires)
            reasons[c] = rs
            if fires:
                self.flag_totals[c] += 1
        return flags, reasons, cats_to_eval

    def run(self, calls):
        # G9 async/non-blocking (placement): tespit çağrıyı bloklamaz
        if not self.pol.get("non_blocking", True):
            self.blocking_violations += 1
        if not self.spec.get("placement", {}).get("non_blocking", True):
            self.blocking_violations += 1

        seen = set()
        for call in calls:
            if call.get("call_id") is None:
                raise DetectError("çağrı kaydında call_id eksik → INVALID_REQUEST")

            self._check_row(call)

            # G7 izolasyon: cross-tenant + residency
            ct = call.get("tenant_id")
            if ct is not None and self.pol.get("isolate_tenant", True) and ct != self.context.get("tenant_id"):
                self.isolation_violations += 1
                continue              # cross-tenant çağrı değerlendirmeye KARIŞMAZ (izole edilir)
            if ct is not None and not self.pol.get("isolate_tenant", True) and ct != self.context.get("tenant_id"):
                self.isolation_violations += 1   # buggy: karışır (aşağıda değerlendirilir)
            cr = call.get("region")
            if cr is not None and self.region_pin is not None and cr != self.region_pin:
                self.isolation_violations += 1

            # G6 idempotent: (tenant, call_id, schema) bir kez
            key = (self.context.get("tenant_id"), call.get("call_id"), self.schema_version)
            if key in seen:
                if self.pol.get("idempotent", True):
                    continue          # daraltılır (tek değerlendirme) — ihlal değil
                else:
                    self.idempotency_violations += 1   # buggy: çift-üretim (aşağıda tekrar değerlendirilir)
            seen.add(key)

            # uygunluk: yalnız completed değerlendirilir; excluded açık reason ile dışlanır
            status = call.get("status", "completed")
            if status not in self.evaluable:
                # uygun değil → kapsam paydasına girmez; excluded reason taşımalı
                self.evaluated.append({
                    "call_id": call.get("call_id"), "eligible": False,
                    "exclusion_reason": status if status in self.excluded else "unknown_status",
                    "flags": {}, "reason_codes": {}, "injected": call.get(self.label_key),
                })
                continue

            self.eligible_count += 1
            flags, reasons, cats_eval = self._detect_one(call)

            # G3 tutarlılık: işaret fires ⟺ ≥1 reason; reason kategori sözlüğünde
            for c in cats_eval:
                col = self.flag_column[c]
                fires = flags.get(col, False)
                rs = reasons.get(c, [])
                has_reason = len(rs) > 0
                if fires != has_reason:
                    self.consistency_violations += 1
                # G4 reason kapalı-sözlükte mi (yetim/serbest-metin reason)
                for r in rs:
                    if r not in self.reason_codes.get(c, []):
                        self.vocab_violations += 1

            # G1/G2 tespit doğruluğu: motor işareti vs injected yer-doğrusu
            injected = call.get(self.label_key)
            if isinstance(injected, dict):
                for c in self.cat_set:
                    col = self.flag_column[c]
                    truth = bool(injected.get(c, False))
                    got = bool(flags.get(col, False))
                    if c not in cats_eval:
                        # kategori atlandı → injected pozitif ise kaçırıldı (recall) ek olarak kapsam açığı
                        if truth:
                            self.missed_detection += 1
                        continue
                    if truth and not got:
                        self.missed_detection += 1      # yanlış-negatif (G1 BİRİNCİL)
                    if (not truth) and got:
                        self.false_positive += 1        # sahte işaret (G2)

            self.evaluated.append({
                "call_id": call.get("call_id"), "eligible": True,
                "flags": flags, "reason_codes": reasons, "injected": injected,
            })

        # G5 kapsam: HER uygun çağrı ÜÇ kategoride değerlendirilmeli
        expected = self.eligible_count * len(self.cat_set)
        self.coverage_gap = abs(expected - self.categories_produced)

        self.derived["eligible_count"] = self.eligible_count
        self.derived["categories_produced"] = self.categories_produced
        self.derived["expected_categories"] = expected
        self.derived["flag_totals"] = dict(self.flag_totals)
        self.derived["evaluated"] = self.evaluated

    def metrics(self):
        return {
            "missed_detection": self.missed_detection,
            "false_positive": self.false_positive,
            "consistency_violations": self.consistency_violations,
            "vocab_violations": self.vocab_violations,
            "coverage_gap": self.coverage_gap,
            "idempotency_violations": self.idempotency_violations,
            "isolation_violations": self.isolation_violations,
            "pii_violations": self.pii_violations,
            "blocking_violations": self.blocking_violations,
            "derived": dict(self.derived),
        }


def detect_calls(sample, spec, profile, context, policy):
    calls = sample.get("calls")
    if not isinstance(calls, list):
        raise DetectError("çağrı seti (calls) liste değil → INVALID_REQUEST")
    for c in calls:
        if not isinstance(c, dict):
            raise DetectError("çağrı kaydı sözlük değil → INVALID_REQUEST")
    eng = IssueDetectionEngine(spec, profile, context, policy)
    eng.run(calls)
    return eng.metrics()


def evaluate(spec, m):
    """Metrikleri HARD kapılara (G1–G9) karşı değerlendirir. Döner findings[(ok, label)]."""
    g = spec.get("gates", {})
    F = []
    F.append((m.get("missed_detection", 0) <= g.get("max_missed_detection", 0),
              "G1 kaçan tespit %d ≤ %d (enjekte edilen her pozitif vaka tespit edilir; yanlış-negatif yok — SR-ANA-004 T) — BİRİNCİL"
              % (m.get("missed_detection", 0), g.get("max_missed_detection", 0))))
    F.append((m.get("false_positive", 0) <= g.get("max_false_positive", 0),
              "G2 sahte işaret %d ≤ %d (enjekte-temiz vakada işaret fires olmaz — kesinlik)"
              % (m.get("false_positive", 0), g.get("max_false_positive", 0))))
    F.append((m.get("consistency_violations", 0) <= g.get("max_consistency_violation", 0),
              "G3 tutarlılık ihlali %d ≤ %d (işaret fires ⟺ ≥1 reason_code; boş-reason/yetim reason yok)"
              % (m.get("consistency_violations", 0), g.get("max_consistency_violation", 0))))
    F.append((m.get("vocab_violations", 0) <= g.get("max_vocab_violation", 0),
              "G4 sözlük ihlali %d ≤ %d (kategori + reason_code kapalı-sözlük; flag_column OLAP fct_call/fct_qa_evaluation BİREBİR)"
              % (m.get("vocab_violations", 0), g.get("max_vocab_violation", 0))))
    F.append((m.get("coverage_gap", 0) <= g.get("max_coverage_gap", 0),
              "G5 kapsam açığı %d ≤ %d (HER uygun çağrı ÜÇ kategoride değerlendirilir; üretilen %d / beklenen %d) — tespit-yok ≠ atlama"
              % (m.get("coverage_gap", 0), g.get("max_coverage_gap", 0),
                 m.get("derived", {}).get("categories_produced", 0), m.get("derived", {}).get("expected_categories", 0))))
    F.append((m.get("idempotency_violations", 0) <= g.get("max_idempotency_violation", 0),
              "G6 idempotency ihlali %d ≤ %d ((tenant,call_id,schema) bir kez; replay çift-üretim yapmaz)"
              % (m.get("idempotency_violations", 0), g.get("max_idempotency_violation", 0))))
    F.append((m.get("isolation_violations", 0) <= g.get("max_isolation_violation", 0),
              "G7 izolasyon ihlali %d ≤ %d (tek tenant_id + cross-tenant yok + residency — FR-TEN-002/NFR 10.7)"
              % (m.get("isolation_violations", 0), g.get("max_isolation_violation", 0))))
    F.append((m.get("pii_violations", 0) <= g.get("max_pii_violation", 0),
              "G8 PII ihlali %d ≤ %d (yalnız redaksiyonlu sinyal + düşük-kardinalite boyut; çıktı PII/serbest-metin reason taşımaz — FR-REC-004)"
              % (m.get("pii_violations", 0), g.get("max_pii_violation", 0))))
    F.append((m.get("blocking_violations", 0) <= g.get("max_blocking_violation", 0),
              "G9 blocking ihlali %d ≤ %d (analytics plane non-blocking; tespit canlı çağrıyı etkilemez — FR-RES-011)"
              % (m.get("blocking_violations", 0), g.get("max_blocking_violation", 0))))
    return F


# ─────────────────────────────────────────────────────────────────────────────
# bağlam + politika çözümleme
# ─────────────────────────────────────────────────────────────────────────────
def _profile_by_name(cfg, name):
    for p in cfg.get("profiles", []):
        if p.get("name") == name:
            return p
    raise DetectError("bilinmeyen profil: %s" % name)


def _resolve_context(spec, profile, sample):
    ctx = dict(sample.get("context", {}))
    ctx.setdefault("region", profile.get("region"))
    return ctx


def _full_pol():
    return {"apply_rules": True, "overflag": False, "enforce_consistency": True, "detect_all": True,
            "closed_taxonomy": True, "idempotent": True, "isolate_tenant": True, "enforce_redaction": True,
            "non_blocking": True}


def _resolve_policy(spec, sample):
    pol = _full_pol()
    pol.update(sample.get("policy", {}))
    return pol


def detect_cmd(sample_path):
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
        except DetectError as ex:
            print("detect[%s]: %s" % (name, ex))
            return 0 if expect == "fail" else 1
    context = _resolve_context(spec, profile, sample)
    policy = _resolve_policy(spec, sample)

    try:
        m = detect_calls(sample, spec, profile, context, policy)
    except DetectError as ex:
        print("detect[%s]: REDDEDİLDİ — %s" % (name, ex))
        return 0 if expect == "fail" else 1

    F = evaluate(spec, m)
    d = m.get("derived", {})
    ft = d.get("flag_totals", {})
    print("detect[%s] %d çağrı → uygun=%d (kategori üretilen=%d/beklenen=%d) | kaçan=%d sahte=%d tutarlılık=%d sözlük=%d kapsam=%d idempotency=%d izolasyon=%d pii=%d blocking=%d" % (
        name, len(sample.get("calls", [])), d.get("eligible_count", 0), d.get("categories_produced", 0),
        d.get("expected_categories", 0), m["missed_detection"], m["false_positive"], m["consistency_violations"],
        m["vocab_violations"], m["coverage_gap"], m["idempotency_violations"], m["isolation_violations"],
        m["pii_violations"], m["blocking_violations"]))
    print("  işaret toplamları: misinformation=%d tool_error=%d security_violation=%d" % (
        ft.get("misinformation", 0), ft.get("tool_error", 0), ft.get("security_violation", 0)))
    for row in d.get("evaluated", []):
        if not row.get("eligible", True):
            print("    çağrı %s: UYGUN DEĞİL [%s]" % (row.get("call_id"), row.get("exclusion_reason")))
            continue
        fired = [c for c, rs in (row.get("reason_codes") or {}).items() if rs]
        print("    çağrı %s: %s" % (row.get("call_id"), ("işaret: " + ", ".join(
            "%s(%s)" % (c, "|".join(row["reason_codes"][c])) for c in fired)) if fired else "temiz (işaret yok)"))
    for ok, label in F:
        print("  %s %s" % ("✓" if ok else "✗", label))
    gate_ok = all(ok for ok, _ in F) and len(F) > 0

    exp = sample.get("expected", {})
    for k, v in exp.items():
        got = m.get(k)
        match = (got == v)
        print("  %s expected.%s == %r (got %r)" % ("✓" if match else "✗", k, v, got))
        gate_ok = gate_ok and match
    exp_ft = sample.get("expected_flag_totals", {})
    for k, v in exp_ft.items():
        got = ft.get(k)
        match = (got == v)
        print("  %s expected_flag_totals.%s == %r (got %r)" % ("✓" if match else "✗", k, v, got))
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


def _fact(olap, name):
    for ft in olap.get("fact_tables", []):
        if ft.get("name") == name:
            return ft
    return None


def _topic(es, name):
    for t in es.get("topics", []):
        if t.get("name") == name:
            return t
    return None


def validate():
    spec = _load(SPEC_PATH)
    R = []

    _check(R, spec.get("wbs") == "14.2.4", "spec.wbs == 14.2.4")
    _check(R, spec.get("version"), "spec.version mevcut")
    _check(R, spec.get("phase") == "F2", "spec.phase == F2")
    _check(R, spec.get("priority") == "Must", "spec.priority == Must (FR-ANA-004)")
    ed = spec.get("eval_doc", {})
    for k in ("fr", "srs", "rtm", "brd", "sad", "db", "olap", "eventstream", "adr", "api", "upstream", "downstream"):
        _check(R, bool(ed.get(k)), "eval_doc.%s mevcut" % k)
    _check(R, "FR-ANA-004" in ed.get("fr", ""), "eval_doc.fr FR-ANA-004")
    _check(R, "T" in ed.get("srs", "") and "SR-ANA-004" in ed.get("srs", ""), "eval_doc.srs SR-ANA-004 yöntem T")

    # ── placement (G9)
    pl = spec.get("placement", {})
    _check(R, pl.get("in_analytics_plane") is True, "G9 motor analytics plane'de (SAD §4.2)")
    _check(R, pl.get("async_batch") is True, "G9 async batch (FR-RES-011)")
    _check(R, pl.get("non_blocking") is True, "G9 non-blocking (tespit canlı çağrıyı etkilemez)")
    _check(R, pl.get("from_redacted_content") is True, "G8 from_redacted_content (redaksiyonlu sinyal)")
    _check(R, pl.get("all_calls") is True, "G5 all_calls (her uygun çağrı değerlendirilir)")
    _check(R, pl.get("deterministic") is True, "I10 deterministic (vendor-neutral, random yok)")
    _check(R, pl.get("idempotent") is True, "G6 idempotent")
    _check(R, pl.get("from_trace") is False, "from_trace=false (kategorik karar, trace türetme değil)")

    # ── categories (G4)
    cat = spec.get("categories", {})
    cset = cat.get("set", [])
    _check(R, set(cset) == {"misinformation", "tool_error", "security_violation"},
           "G4 kategori kümesi == {misinformation, tool_error, security_violation} (FR-ANA-004)")
    _check(R, len(cset) == 3 and len(cset) == len(set(cset)), "G4 üç kategori, benzersiz")
    fc = cat.get("flag_column", {})
    _check(R, fc.get("misinformation") == "flag_misinformation"
           and fc.get("tool_error") == "flag_tool_error"
           and fc.get("security_violation") == "flag_security",
           "G4 flag_column → OLAP fct_call flag_* eşlemesi (BİREBİR)")
    rc = cat.get("reason_codes", {})
    _check(R, set(rc.keys()) == set(cset), "G4 her kategori reason_code kümesine sahip")
    for c in cset:
        _check(R, isinstance(rc.get(c), list) and len(rc[c]) >= 1 and len(rc[c]) == len(set(rc[c])),
               "G4 %s reason_code listesi ≥1 + benzersiz" % c)

    # ── detection_rules (I11)
    dr = spec.get("detection_rules", {}).get("rules", [])
    _check(R, len(dr) >= 9, "I11 ≥9 tespit kuralı (kategori×reason)")
    rule_reasons = {}
    for rule in dr:
        c = rule.get("category")
        _check(R, c in cset, "I11 kural kategori kapalı-küme (%s)" % c)
        _check(R, rule.get("reason") in rc.get(c, []),
               "I11 kural reason '%s' kategori %s sözlüğünde" % (rule.get("reason"), c))
        _check(R, rule.get("signal") and rule.get("op") in ("gt", "ge", "lt"),
               "I11 kural signal + op (gt/ge/lt) tanımlı")
        rule_reasons.setdefault(c, set()).add(rule.get("reason"))
    for c in cset:
        _check(R, rule_reasons.get(c, set()) == set(rc.get(c, [])),
               "I11 %s reason_code'larının HEPSİ bir kurala eşli (kapsam)" % c)

    # ── ground_truth (I1/I2 BİRİNCİL)
    gt = spec.get("ground_truth", {})
    _check(R, gt.get("label_key") == "injected", "I1 ground_truth.label_key == injected")
    _check(R, set(gt.get("labels", [])) == set(cset), "I1 injected etiketleri == kategori kümesi")
    _check(R, gt.get("missed_detection_is_false_negative") is True, "I1 missed_detection = yanlış-negatif")
    _check(R, "recall" in gt.get("primary_gate", "").lower() or "missed" in gt.get("primary_gate", "").lower(),
           "I1 primary_gate recall/missed_detection (SR-ANA-004 T)")

    # ── eligibility / coverage (G5)
    el = spec.get("eligibility", {})
    _check(R, "completed" in el.get("evaluable_statuses", []), "G5 evaluable=completed")
    _check(R, el.get("exclusion_reason_required") is True, "G5 dışlama açık reason taşır (sessiz filtre yok)")
    cov = spec.get("coverage", {})
    _check(R, cov.get("categories_per_call") == 3, "G5 categories_per_call == 3")
    _check(R, cov.get("produced_equals_eligible_times_categories") is True, "G5 produced == eligible × 3")

    # ── consistency (G3)
    cons = spec.get("consistency", {})
    _check(R, cons.get("flag_iff_reason") is True, "G3 flag ⟺ reason_code")
    _check(R, cons.get("reason_in_category_vocab") is True, "G3 reason kategori sözlüğünde")

    # ── output_contract (G4/G8)
    oc = spec.get("output_contract", {})
    _check(R, set(oc.get("flag_fields", [])) == {"flag_misinformation", "flag_tool_error", "flag_security"},
           "G4 flag_fields == OLAP flag_* sütunları (FR-ANA-004)")
    _check(R, {"tenant_id", "call_id", "schema_version"} <= set(oc.get("identity_fields", [])),
           "G7 identity_fields tenant_id/call_id/schema_version içerir")
    _check(R, oc.get("emits") == "qa.evaluation.completed", "output emits qa.evaluation.completed")
    _check(R, any("call_evaluation" in p for p in oc.get("persists_to", [])),
           "output persists_to call_evaluation.flags (DB.md §5.6)")
    _check(R, any("fct_call" in p for p in oc.get("persists_to", [])),
           "output persists_to fct_call flag_* (OLAP)")

    # ── idempotency (G6)
    idem = spec.get("idempotency", {})
    _check(R, idem.get("dedup_key") == ["tenant_id", "call_id", "schema_version"],
           "G6 dedup_key == (tenant_id, call_id, schema_version)")
    _check(R, idem.get("replay_safe") is True, "G6 replay_safe (1.1.8 P3)")

    # ── feature_policy (G8)
    fp = spec.get("feature_policy", {})
    allowed = set(fp.get("allowed_input_keys", []))
    forb = set(fp.get("forbidden_input_keys", []))
    _check(R, {"call_id", "grounded_answers", "total_answers", "tool_errors", "policy_violations"} <= allowed,
           "G8 allowed_input_keys çekirdek sinyalleri içerir")
    _check(R, {"transcript_text", "audio_payload", "phone_number", "card_number"} <= forb,
           "G8 forbidden_input_keys ham transkript/ses/PII anahtarlarını içerir")
    _check(R, not (allowed & forb), "G8 izinli ile yasak girdi kesişmez")
    # tüm tespit sinyalleri whitelist'te
    for rule in dr:
        _check(R, rule.get("signal") in allowed, "G8 kural sinyali '%s' whitelist'te" % rule.get("signal"))
        if rule.get("compare_to"):
            _check(R, rule.get("compare_to") in allowed, "G8 kural compare_to '%s' whitelist'te" % rule.get("compare_to"))

    # ── isolation (G7)
    iso = spec.get("isolation", {})
    _check(R, iso.get("tenant_id_required") is True, "G7 tenant_id_required")
    _check(R, iso.get("residency") == "home-region", "G7 residency home-region (NFR 10.7)")
    _check(R, iso.get("cross_tenant_forbidden") is True, "G7 cross_tenant_forbidden (FR-TEN-002)")

    # ── OLAP fct_call/fct_qa_evaluation flag_* BİREBİR (G4, non-circular)
    olap = _load_sibling_spec("analytics", "olap-spec.json")
    if olap is not None:
        for tname in ("fct_call", "fct_qa_evaluation"):
            ftab = _fact(olap, tname)
            _check(R, ftab is not None, "G4 OLAP %s fact table mevcut" % tname)
            if ftab is not None:
                cols = {c.get("name"): c for c in ftab.get("columns", [])}
                for col in ("flag_misinformation", "flag_tool_error", "flag_security"):
                    _check(R, col in cols and "FR-ANA-004" in (cols[col].get("note") or "")
                           and cols[col].get("pii_class") == "low",
                           "G4 %s.%s mevcut + FR-ANA-004 + pii_class low" % (tname, col))
                _check(R, "FR-ANA-004" in ftab.get("fr", []), "G4 OLAP %s FR-ANA-004 taşır" % tname)

    # ── eventstream topic BİREBİR (G4/G8, non-circular)
    es = _load_sibling_spec("eventstream", "topic-spec.json")
    if es is not None:
        qa = _topic(es, "qa.evaluation.v1")
        _check(R, qa is not None, "eventstream qa.evaluation.v1 topic mevcut")
        if qa is not None:
            _check(R, "FR-ANA-004" in qa.get("fr", []), "G4 qa.evaluation.v1 FR-ANA-004 taşır")
            _check(R, qa.get("pii_class") == "redacted", "G8 qa.evaluation.v1 pii_class redacted")
            _check(R, "analytics-ingest" in qa.get("consumers", []), "qa.evaluation.v1 analytics-ingest consumer")
        tool = _topic(es, "ops.tool.execution.v1")
        _check(R, tool is not None and "FR-TOOL-009" in tool.get("fr", []),
               "ops.tool.execution.v1 tool status kaynağı (FR-TOOL-009)")
        _check(R, _topic(es, "governance.audit.v1") is not None,
               "governance.audit.v1 güvenlik/policy olayları kaynağı")

    # ── 14.2.1 qa-eval feature whitelist hizası (G8, non-circular)
    qae = _load_sibling_spec("runtime", "qa-eval", "qa-eval-spec.json")
    if qae is not None:
        qa_allowed = set(qae.get("feature_policy", {}).get("allowed_feature_keys",
                         qae.get("feature_policy", {}).get("allowed_input_keys", [])))
        # 14.2.1 ile paylaşılan sinyaller bu motorda da izinli olmalı (tutarlı redaksiyon sözleşmesi)
        shared = {"grounded_answers", "total_answers", "tool_calls", "tool_errors", "policy_violations"}
        _check(R, shared <= qa_allowed, "14.2.1 qa-eval whitelist paylaşılan sinyalleri içerir")
        _check(R, shared <= allowed, "G8 paylaşılan sinyaller bu motorda da izinli (14.2.1 ile tutarlı)")

    # ── gates
    g = spec.get("gates", {})
    for gk in ("max_missed_detection", "max_false_positive", "max_consistency_violation", "max_vocab_violation",
               "max_coverage_gap", "max_idempotency_violation", "max_isolation_violation",
               "max_pii_violation", "max_blocking_violation"):
        _check(R, g.get(gk, -1) == 0, "gate %s = 0" % gk)

    # ── error taxonomy (I12)
    et = spec.get("error_taxonomy", {}).get("mapping", {})
    _check(R, len(et) >= 3, "I12 hata eşlemesi (≥3)")
    _check(R, all(v in ERROR_TAXONOMY for v in et.values()), "I12 tüm hedefler API §11.6 ErrorTaxonomy'de")
    _check(R, et.get("malformed_call") == "INVALID_REQUEST" and et.get("unknown_category") == "INVALID_REQUEST"
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
PROFILE = {"name": "eu-standard", "region": "eu-west-1", "schema_version": 1}


def _clean(cid, **sig):
    """Tespit sinyali olmayan temiz çağrı (injected hepsi false)."""
    r = {"call_id": cid, "agent_id": "ag1", "agent_version_id": "v1", "period": "2026-06-01",
         "grounded_answers": 3, "total_answers": 3, "tool_calls": 2, "tool_errors": 0, "tool_timeouts": 0,
         "provider_errors": 0, "kb_contradictions": 0, "unverified_commitments": 0,
         "pii_disclosure_events": 0, "prompt_injection_detected": 0, "jailbreak_detected": 0,
         "unauthorized_actions": 0, "policy_violations": 0,
         "injected": {"misinformation": False, "tool_error": False, "security_violation": False}}
    r.update(sig)
    return r


def _inject(cid, category, **sig):
    """Belirli kategoride hata enjekte edilmiş çağrı (injected[cat]=true + tetikleyici sinyal)."""
    r = _clean(cid)
    r["injected"] = {"misinformation": False, "tool_error": False, "security_violation": False}
    r["injected"][category] = True
    if category == "misinformation":
        r["grounded_answers"] = 2; r["total_answers"] = 3   # ungrounded_answer
    elif category == "tool_error":
        r["tool_errors"] = 1                                 # tool_call_failed
    elif category == "security_violation":
        r["policy_violations"] = 1                           # policy_violation
    r.update(sig)
    return r


def _run(calls, spec, context=None, profile=None, **pol_over):
    pol = _full_pol()
    pol.update(pol_over)
    return detect_calls({"calls": calls}, spec, dict(profile or PROFILE), context or CONTEXT, pol)


def _raises(fn):
    try:
        fn()
        return False
    except DetectError:
        return True


def selftest():
    spec = _load(SPEC_PATH)
    cases = []

    def case(ok, label):
        cases.append((bool(ok), label))

    case(_validate_obj(_load(SPEC_PATH)) == 0, "validate iyi spec+config'te 0 döndürür")

    # ── happy: 3 enjekte (her kategoride 1) + 2 temiz → hepsi doğru tespit ──
    calls = [_inject("m1", "misinformation"), _inject("t1", "tool_error"),
             _inject("s1", "security_violation"), _clean("c1"), _clean("c2")]
    mh = _run(calls, spec)
    case(all(mh[k] == 0 for k in (
        "missed_detection", "false_positive", "consistency_violations", "vocab_violations",
        "coverage_gap", "idempotency_violations", "isolation_violations",
        "pii_violations", "blocking_violations")), "happy: tüm ihlal sayaçları 0")
    case(all(ok for ok, _ in evaluate(spec, mh)), "happy tüm kapıları geçer")
    ft = mh["derived"]["flag_totals"]
    case(ft["misinformation"] == 1 and ft["tool_error"] == 1 and ft["security_violation"] == 1,
         "happy: her kategoride 1 işaret (3 enjekte tespit edildi)")
    case(mh["derived"]["eligible_count"] == 5 and mh["derived"]["categories_produced"] == 15,
         "happy: 5 uygun çağrı × 3 kategori = 15 değerlendirme (kapsam tam)")

    # ── determinizm ──
    case(_run(calls, spec) == _run(calls, spec), "determinizm: aynı sinyal aynı işaret (random yok)")

    # ── G1 recall (BİRİNCİL): apply_rules KAPALI → enjekte pozitifler kaçar ──
    m1 = _run(calls, spec, apply_rules=False)
    case(m1["missed_detection"] == 3, "G1 apply_rules KAPALI: 3 enjekte pozitif kaçar → missed_detection=3 eler")
    case(not all(ok for ok, _ in evaluate(spec, m1)), "G1 kaçan tespit → kapı ELENİR (BİRİNCİL)")

    # ── G1 her reason_code'un kendi enjeksiyonunu tespit ettiği ──
    for cat, sig in (("misinformation", {"kb_contradictions": 1}), ("misinformation", {"unverified_commitments": 1}),
                     ("tool_error", {"tool_timeouts": 1}), ("tool_error", {"provider_errors": 1}),
                     ("security_violation", {"pii_disclosure_events": 1}),
                     ("security_violation", {"prompt_injection_detected": 1}),
                     ("security_violation", {"jailbreak_detected": 1}),
                     ("security_violation", {"unauthorized_actions": 1})):
        c = _clean("x")
        c["injected"][cat] = True
        # ungrounded'ı temizle ki yalnız hedef sinyal tetiklesin
        c.update({"grounded_answers": 3, "total_answers": 3, "tool_errors": 0, "policy_violations": 0})
        c.update(sig)
        mm = _run([c], spec)
        case(mm["missed_detection"] == 0 and mm["derived"]["flag_totals"][cat] == 1,
             "G1 %s sinyali %s → tespit edilir (recall)" % (cat, list(sig.keys())[0]))

    # ── G2 precision: overflag → enjekte-temizde sahte işaret ──
    m2 = _run([_clean("c1"), _clean("c2")], spec, overflag=True)
    case(m2["false_positive"] >= 1, "G2 overflag: enjekte-temiz vakada işaret fires → false_positive eler")

    # ── G3 tutarlılık: enforce_consistency KAPALI → fires ama reason boş ──
    m3 = _run([_inject("m1", "misinformation")], spec, enforce_consistency=False)
    case(m3["consistency_violations"] >= 1, "G3 enforce_consistency KAPALI: fires ama reason boş → tutarsızlık eler")

    # ── G4 sözlük: closed_taxonomy KAPALI → serbest-metin reason ──
    m4 = _run([_inject("m1", "misinformation")], spec, closed_taxonomy=False)
    case(m4["vocab_violations"] >= 1, "G4 closed_taxonomy KAPALI: serbest-metin reason → sözlük eler")

    # ── G5 kapsam: detect_all KAPALI → security kategorisi atlanır ──
    m5 = _run([_clean("c1"), _clean("c2")], spec, detect_all=False)
    case(m5["coverage_gap"] >= 1, "G5 detect_all KAPALI: security kategorisi atlanır → kapsam açığı eler")
    case(m5["derived"]["categories_produced"] == 4, "G5 detect_all KAPALI: 2 çağrı × 2 kategori = 4 (security atlandı)")
    # security enjeksiyonu atlanırsa hem kapsam hem recall eler
    m5b = _run([_inject("s1", "security_violation")], spec, detect_all=False)
    case(m5b["missed_detection"] >= 1 and m5b["coverage_gap"] >= 1,
         "G5 security enjeksiyonu atlanırsa hem missed_detection hem coverage_gap")

    # ── G6 idempotency: replay (aynı call_id) ──
    dup = [_inject("m1", "misinformation"), _inject("m1", "misinformation")]
    m6 = _run(dup, spec, idempotent=False)
    case(m6["idempotency_violations"] >= 1, "G6 idempotent KAPALI: aynı (tenant,call,schema) çift-üretim → eler")
    m6o = _run(dup, spec)
    case(m6o["idempotency_violations"] == 0 and m6o["derived"]["eligible_count"] == 1,
         "G6 idempotent AÇIK: replay daraltılır (1 değerlendirme) → geçer")

    # ── G7 izolasyon: cross-tenant + residency ──
    cross = [_inject("m1", "misinformation")]
    ct = _clean("ct"); ct["tenant_id"] = "t_other"
    m7 = _run(cross + [ct], spec)
    case(m7["isolation_violations"] >= 1 and m7["derived"]["eligible_count"] == 1,
         "G7 cross-tenant çağrı (t_other) → izolasyon eler + değerlendirmeye karışmaz")
    rd = _clean("rd"); rd["region"] = "us-east-1"
    m7r = _run([_inject("m1", "misinformation"), rd], spec)
    case(m7r["isolation_violations"] >= 1, "G7 home-region dışı çağrı (residency) → eler (NFR 10.7)")

    # ── G8 PII: ham transkript / PII DEĞERİ girdi ──
    leak = _clean("p"); leak["transcript_text"] = "müşteri konuştu"
    m8 = _run([leak], spec, enforce_redaction=False)
    case(m8["pii_violations"] == 0, "G8 enforce_redaction KAPALI: redaction zorlanmaz (denetlenmez)")
    m8e = _run([leak], spec)
    case(m8e["pii_violations"] >= 1, "G8 enforce_redaction AÇIK: transcript_text yasak girdi → eler")
    leakv = _clean("pv"); leakv["agent_id"] = "0555 123 4567"
    m8v = _run([leakv], spec)
    case(m8v["pii_violations"] >= 1, "G8 boyut DEĞERİnde ham telefon → eler")

    # ── G9 blocking: non_blocking KAPALI ──
    m9 = _run([_clean("c1")], spec, non_blocking=False)
    case(m9["blocking_violations"] >= 1, "G9 non_blocking KAPALI: tespit çağrıyı bloklar → eler (FR-RES-011)")

    # ── uygunluk: in_progress dışlanır (kapsam paydasına girmez) ──
    ip = _clean("ip"); ip["status"] = "in_progress"
    mip = _run([_inject("m1", "misinformation"), ip], spec)
    case(mip["derived"]["eligible_count"] == 1 and mip["coverage_gap"] == 0,
         "uygunluk: in_progress dışlanır (eligible=1, kapsam korunur)")
    excl = [r for r in mip["derived"]["evaluated"] if not r["eligible"]]
    case(len(excl) == 1 and excl[0]["exclusion_reason"] == "in_progress",
         "uygunluk: dışlanan çağrı açık reason taşır (sessiz filtre yok)")

    # ── reddetme (I12) ──
    case(_raises(lambda: detect_calls({"calls": "x"}, spec, PROFILE, CONTEXT, _full_pol())),
         "I12 calls liste değil → reddedilir")
    case(_raises(lambda: detect_calls({"calls": [{"agent_id": "ag1"}]}, spec, PROFILE, CONTEXT, _full_pol())),
         "I12 çağrıda call_id eksik → reddedilir")
    case(_raises(lambda: IssueDetectionEngine(spec, PROFILE, {"region": "eu"}, _full_pol())),
         "I12 bağlam (tenant_id) eksik → reddedilir")

    # ── validate negatif kapılar ──
    s = json.loads(json.dumps(spec)); s["categories"]["set"] = ["misinformation", "tool_error"]
    case(_validate_obj(s) != 0, "G4 kategori kümesi 3'ten sapar → validate eler")
    s = json.loads(json.dumps(spec)); s["categories"]["flag_column"]["misinformation"] = "flag_wrong"
    case(_validate_obj(s) != 0, "G4 flag_column OLAP'tan sapar → validate eler")
    s = json.loads(json.dumps(spec)); s["coverage"]["categories_per_call"] = 2
    case(_validate_obj(s) != 0, "G5 categories_per_call != 3 → validate eler")
    s = json.loads(json.dumps(spec)); s["ground_truth"]["label_key"] = "foo"
    case(_validate_obj(s) != 0, "I1 ground_truth.label_key != injected → validate eler")
    s = json.loads(json.dumps(spec)); s["feature_policy"]["allowed_input_keys"].append("transcript_text")
    case(_validate_obj(s) != 0, "G8 izinli girdiye transcript_text → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_missed_detection"] = 1
    case(_validate_obj(s) != 0, "G1 max_missed_detection>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["detection_rules"]["rules"] = s["detection_rules"]["rules"][:3]
    case(_validate_obj(s) != 0, "I11 kural sayısı <9 / reason kapsamı eksik → validate eler")
    s = json.loads(json.dumps(spec)); s["error_taxonomy"]["mapping"]["x"] = "NOPE"
    case(_validate_obj(s) != 0, "I12 taksonomi-dışı → validate eler")
    s = json.loads(json.dumps(spec)); s["categories"]["leak"] = "0555 123 4567"
    case(_validate_obj(s) != 0, "I15 spec'te ham PII DEĞERİ (telefon) → validate eler")
    s = json.loads(json.dumps(spec)); s["categories"]["secret"] = "api_key: AKIAIOSFODNN7EXAMPLE"
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
    print("""detection-spec.json beklenen şekli (WBS 14.2.4):
  wbs=14.2.4, version, phase=F2, priority=Must, eval_doc{fr,srs,rtm,brd,sad,db,olap,eventstream,adr,api,upstream,downstream}
  placement{in_analytics_plane, async_batch, non_blocking, from_redacted_content, all_calls=true,
            deterministic, idempotent, from_trace=false}                                          (G9,G8,G5)
  categories{set[misinformation,tool_error,security_violation], flag_column{→OLAP flag_*},
             reason_codes{kategori→kapalı-sözlük}}                                                 (G4)
  detection_rules{rules[≥9]{category, reason, signal, op(gt/ge/lt), threshold|compare_to}}         (I11)
  ground_truth{label_key=injected, labels[3], primary_gate=recall}                                 (I1,I2 BİRİNCİL)
  eligibility{evaluable_statuses[completed], excluded_statuses, exclusion_reason_required}         (G5)
  coverage{categories_per_call=3, produced_equals_eligible_times_categories}                       (G5)
  consistency{flag_iff_reason, reason_in_category_vocab}                                           (G3)
  output_contract{flag_fields[flag_misinformation,flag_tool_error,flag_security], identity_fields,
                  emits=qa.evaluation.completed, persists_to[fct_call,fct_qa_evaluation,call_evaluation]} (G4,G7)
  idempotency{dedup_key=[tenant_id,call_id,schema_version], replay_safe}                            (G6)
  feature_policy{allowed_input_keys[], forbidden_input_keys[]}                                      (G8)
  isolation{tenant_id_required, residency=home-region, cross_tenant_forbidden}                      (G7)
  gates{max_missed_detection=0(BİRİNCİL), max_false_positive=0, max_consistency_violation=0,
        max_vocab_violation=0, max_coverage_gap=0, max_idempotency_violation=0,
        max_isolation_violation=0, max_pii_violation=0, max_blocking_violation=0}                   (G1..G9)
  error_taxonomy{mapping→API §11.6}  pii{...}  invariants[≥15]{id,desc,trace}

config/detection-profiles.json: profiles[]{name, region, schema_version, threshold_override?}

detect sample: {name, profile | profile_obj, expect, expected?{metrik}, expected_flag_totals?{kategori},
  context{tenant_id, region?},
  policy?{apply_rules, overflag, enforce_consistency, detect_all, closed_taxonomy, idempotent,
          isolate_tenant, enforce_redaction, non_blocking},
  calls[]{call_id, agent_id?, agent_version_id?, period?, tenant_id?, region?, status?,
          <redaksiyonlu sinyaller: grounded_answers/total_answers/kb_contradictions/unverified_commitments/
           tool_calls/tool_errors/tool_timeouts/provider_errors/pii_disclosure_events/prompt_injection_detected/
           jailbreak_detected/unauthorized_actions/policy_violations>,
          injected?{misinformation, tool_error, security_violation}}}
  (PII DEĞERİ / ham transkript YOK — yalnız redaksiyonlu sayısal/kategorik sinyal + düşük-kardinalite boyut/kimlik ADLARI)

komutlar: validate | detect <sample.json> | selftest | schema""")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if cmd == "validate":
        return validate()
    if cmd == "detect":
        if len(sys.argv) < 3:
            print("kullanım: detection_probe.py detect <sample.json>")
            return 2
        return detect_cmd(sys.argv[2])
    if cmd == "selftest":
        return selftest()
    if cmd == "schema":
        return schema()
    print("bilinmeyen komut: %s (validate|detect|selftest|schema)" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main())
