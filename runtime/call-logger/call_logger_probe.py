#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
call_logger_probe.py — WBS 14.1.4 Yapılandırılmış asenkron + örneklemeli loglama

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only statik + davranış kapısı.
`runtime/call-resource/` (14.1.3) + `runtime/call-metrics/` (14.1.2) + `runtime/call-trace/` (14.1.1)
probe disipliniyle birebir; burada deterministik bir CONVERSATION ORCHESTRATOR STRUCTURED ASYNC SAMPLED
LOGGER (SAD §17.1 'Logs: Yapılandırılmış, örneklemeli, asenkron — FR-RES-012') simülatörü (saf;
örnekleme SABİT hash ile — random YOK).

STRUCTURED ASYNC SAMPLED LOGGER (Çekirdek IP, SAD §6 / §17) — çağrı runtime'ında üretilen yapılandırılmış
(structured JSON) log kayıtlarını gözlemlenebilirlik LOGS hattına yayar:
  • Yapı (G1):         yayılan her kayıt required_body_keys taşır (tenant_id/correlation_id/level/event/ts).
  • Taksonomi (G2):    her kaydın level ∈ levels + kind ∈ kinds — level_violation=0.
  • Örnekleme (G3):    HEAD-BASED (correlation_id tutarlı); logs_always (WARN+/security/audit) HER ZAMAN tutulur.
  • Asenkron (G4):     non-blocking enqueue (hot-path bloklanmaz, SR-RES-012) + garantili kayıt overflow ile kaybolmaz.
  • Kardinalite (G5):  stream label yüksek-kardinalite kimlik taşımaz + yalnız stream_labels_allowed.
  • PII (G6):          stream label'da PII anahtarı yok + gövde DEĞERİNDE ham PII yok (FR-REC-004).
  • Audit (G7):        audit kaydı ASLA örneklenmez + AYRI WORM sink (FR-IAM-006).

KAPSAM AYRIMI: span üretimi + zaman damgası → 14.1.1 · teknik metrik DEĞERLERİ → 14.1.2 · per-call
CPU/bellek → 14.1.3 · metrik/alarm KATALOĞU + collector/Loki guard → 0.4.7 · alarm kuralları → 14.1.5 ·
gerçek zamanlı op ekranı → 14.1.6 · redaction ÜRETİMİ L7 → ileri WBS. Burada YALNIZ log üretim yolu:
yapılandırma + örnekleme + asenkron/bloklamama + stream-label kardinalite + label/gövde PII + audit ayrımı.

Komutlar:
  validate              call-logger-spec.json'ı invariant'lara + 0.4.7 çapraz-tutarlılığa + config'e karşı doğrular.
  emit <sample>         Deterministik StructuredAsyncLogger — log kayıt akışı → yayılan/örneklenen/düşen + HARD kapılar (G1–G7); →çıkış kodu.
  selftest              İyi/kötü spec+sample ile kapıların doğru tetiklendiğini kanıtlar.
  schema                Beklenen spec şeklini özetler.

Sunucu/credential GEREKMEZ. emit gerçek async runtime yerine deterministik simülasyondur (canlı sistemde
Go/Rust + bounded ring buffer + non-blocking enqueue + OpenTelemetry/Loki, ADR-003/SAD §11/§17.1). Ham ses
payload'ı/transkript/PII DEĞERİ YOK — örnekler yalnız log SİNYALİ + kimlik/etiket anahtarı ADLARI taşır.
"""
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "call-logger-spec.json")
PROFILES_CFG = os.path.join(HERE, "config", "call-logger-profiles.json")

ERROR_TAXONOMY = {
    "TIMEOUT", "RATE_LIMITED", "UNAVAILABLE", "AUTH",
    "INVALID_REQUEST", "CONTENT_FILTERED", "QUOTA_EXCEEDED", "REGION_VIOLATION",
}
SECRET_RE = re.compile(
    r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer)\b\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}"
)
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")

# Gövde DEĞERİ redaction L7 (FR-REC-004): ham PII DEĞER desenleri. correlation_id/call_id/trace_id
# KİMLİK (PII değil) — bunlar ardışık ≥7 rakam içermez (örn. corr-acme-001), yanlış-pozitif olmaz.
PII_VALUE_RE = re.compile(
    r"(?:\d[ \-]?){7,}"                                  # ≥7 ardışık rakam (telefon/kart/IBAN)
    r"|[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"  # e-posta
    r"|\b(?:\d[ \-]?){13,19}\b"                          # kart bloğu
    r"|\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b"                 # IBAN
)


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_placeholder(v):
    return isinstance(v, str) and PLACEHOLDER_RE.match(v) is not None


class LoggerError(Exception):
    """Geçersiz/eksik kayıt demeti veya bilinmeyen level/kind — sessizce kabul yok, reddet (G10)."""


def _sample_fraction(key):
    """correlation_id → sabit [0,1) kesir (tutarlı head-based örnekleme; deterministik, random YOK)."""
    h = hashlib.sha256(str(key).encode("utf-8")).hexdigest()[:8]
    return (int(h, 16) % 10000) / 10000.0


# ─────────────────────────────────────────────────────────────────────────────
# Structured Async Sampled Logger — yapılandırılmış asenkron örneklemeli log üretimi (deterministik)
# ─────────────────────────────────────────────────────────────────────────────
class StructuredAsyncLogger:
    """SAD §17.1 'Logs:' Structured Async Sampled Logger. Çağrı runtime'ında üretilen log kayıtlarını
    yapılandırır (structured) + HEAD-BASED örnekler (logs_always her zaman) + ASENKRON/non-blocking
    tampona yazar (overflow → sampleable düşer, garantili korunur) + stream-label kardinalite + label/
    gövde PII + audit ayrımı disiplinine karşı denetler. Saf; örnekleme SABİT hash; random YOK.

    policy bayrakları buggy Logger'ı simüle eder (call-resource deseni):
      structure_keys     : required gövde anahtarlarını ekle (kapalı → tenant_id gövdeden düşer, G1)
      conform_levels     : bilinmeyen level/kind reddet/normalize (kapalı → bilinmeyen taksonomi geçer, G2)
      honor_always       : logs_always her zaman tut (kapalı → WARN/security/audit örneklemeyle düşebilir, G3)
      non_blocking       : asenkron non-blocking yazım (kapalı → senkron yazım hot-path'i bloklar, G4)
      enforce_cardinality: kimliği stream label yapma (kapalı → correlation_id stream label, G5)
      enforce_labels     : yalnız izinli stream label (kapalı → sınırsız stream label, G5)
      enforce_pii        : PII anahtarını stream label'dan çıkar (kapalı → phone_number stream label, G6)
      redact_body        : gövde DEĞERİNİ redakte et (kapalı → ham PII DEĞERİ gövdede kalır, G6)
      separate_audit     : audit → ayrı WORM + asla örnekleme (kapalı → audit telemetri sink'e + örneklenir, G7)
    """

    def __init__(self, spec, context, policy):
        self.spec = spec
        self.context = dict(context or {})
        self.pol = policy

        rm = spec.get("record_model", {})
        self.levels = set(rm.get("levels", []))
        self.kinds = set(rm.get("kinds", []))

        st = spec.get("structured", {})
        self.required_body_keys = list(st.get("required_body_keys", []))

        sm = spec.get("sampling", {})
        self.base_rate = sm.get("base_rate", 0.2)
        self.always_levels = set(sm.get("always_levels", []))
        self.always_kinds = set(sm.get("always_kinds", []))
        self.consistent_key = sm.get("consistent_key", "correlation_id")

        ab = spec.get("async_buffer", {})
        self.queue_capacity = ab.get("queue_capacity", 256)

        slp = spec.get("stream_label_policy", {})
        self.stream_labels_allowed = set(slp.get("stream_labels_allowed", []))
        self.high_card = set(slp.get("high_cardinality_keys", []))
        self.pii_keys = set(slp.get("pii_forbidden_keys", []))

        au = spec.get("audit", {})
        self.telemetry_sink = au.get("telemetry_sink", "loki")
        self.worm_sink = au.get("worm_sink", "worm-audit")

        # ingress kimliği (gövde + stream label DEĞER kaynağı)
        if not self.context.get("tenant_id"):
            raise LoggerError("emisyon bağlamı eksik: tenant_id → INVALID_REQUEST")
        if not self.context.get("correlation_id"):
            raise LoggerError("emisyon bağlamı eksik: correlation_id → INVALID_REQUEST")

        self.emitted = []   # yayılan (kept) kayıtlar [{level,kind,event,sink,labels{},body{}}]
        self.structure_missing = 0
        self.level_violations = 0
        self.sampling_violations = 0
        self.blocking_violations = 0
        self.overflow_violations = 0
        self.cardinality_violations = 0
        self.label_violations = 0
        self.pii_violations = 0
        self.redaction_violations = 0
        self.audit_violations = 0
        self.records_in = 0
        self.sampled_out = 0
        self.dropped_overflow = 0
        self.audit_count = 0
        self.derived = {}

    # ── logs_always sınıfı (garantili: WARN+/security/audit) ──────────────────
    def _is_always(self, rec):
        return (rec.get("level") in self.always_levels) or (rec.get("kind") in self.always_kinds)

    # ── stream label inşası (DÜŞÜK kardinalite) ───────────────────────────────
    def _stream_labels(self, rec):
        out = {}
        src = dict(self.context)
        src["level"] = rec.get("level")
        for k in self.stream_labels_allowed:
            v = src.get(k)
            if v is not None:
                out[k] = v
        # buggy: kimliği STREAM LABEL yap (G5) — yüksek-kardinalite kaçağı
        if not self.pol.get("enforce_cardinality", True):
            out["correlation_id"] = self.context.get("correlation_id")
        # buggy: PII anahtarını STREAM LABEL yap (G6) — DEĞER yok, yalnız anahtar adı
        if not self.pol.get("enforce_pii", True):
            out["phone_number"] = "<redacted>"
        # buggy: izinsiz (yüksek-kardinalite/PII olmayan) stream label (G5 label)
        if not self.pol.get("enforce_labels", True):
            out["unbounded_dim"] = "x"
        return out

    # ── yapılandırılmış gövde inşası (kimlik + güvenli alanlar; redaction L7) ──
    def _body(self, rec):
        body = {
            "correlation_id": self.context.get("correlation_id"),
            "trace_id": self.context.get("trace_id"),
            "event": rec.get("event"),
            "level": rec.get("level"),
            "ts": rec.get("ts", "T"),
        }
        if self.context.get("call_id"):
            body["call_id"] = self.context.get("call_id")
        # required gövde anahtarları (yapılandırılmış)
        if self.pol.get("structure_keys", True):
            body["tenant_id"] = self.context.get("tenant_id")
        # güvenli yapılandırılmış alanlar (redaction L7)
        for k, v in (rec.get("fields") or {}).items():
            if self.pol.get("redact_body", True) and isinstance(v, str) and PII_VALUE_RE.search(v):
                body[k] = "[REDACTED]"      # doğru: ham PII DEĞERİ redakte edilir
            else:
                body[k] = v                  # buggy: redact_body kapalı → ham DEĞER kalır (G6)
        return body

    def _check_record_emit(self, rec, sink):
        """Yayılan tek kaydı yapı/kardinalite/label/PII/gövde-redaction'a karşı denetler."""
        labels = self._stream_labels(rec)
        body = self._body(rec)
        self.emitted.append({"level": rec.get("level"), "kind": rec.get("kind"),
                             "event": rec.get("event"), "sink": sink,
                             "labels": labels, "body": body})

        # ── G1 yapı: required gövde anahtarları ───────────────────────────────
        for k in self.required_body_keys:
            if body.get(k) is None:
                self.structure_missing += 1

        # ── G5 kardinalite + label ────────────────────────────────────────────
        for k in labels.keys():
            if k in self.high_card:
                self.cardinality_violations += 1
            if k in self.pii_keys:
                self.pii_violations += 1            # ── G6 PII (label) ──
            elif k not in self.stream_labels_allowed:
                self.label_violations += 1

        # ── G6 gövde redaction: ham PII DEĞERİ ───────────────────────────────
        for k, v in body.items():
            if k in ("correlation_id", "call_id", "trace_id"):
                continue                            # kimlik (PII değil)
            if isinstance(v, str) and PII_VALUE_RE.search(v):
                self.redaction_violations += 1

    # ── tam çağrı log akışı ────────────────────────────────────────────────────
    def run(self, records):
        # 0) taksonomi (G2) — bilinmeyen level/kind
        for rec in records:
            self.records_in += 1
            lvl_ok = rec.get("level") in self.levels
            knd_ok = rec.get("kind") in self.kinds
            if not (lvl_ok and knd_ok):
                if self.pol.get("conform_levels", True):
                    # doğru Logger reddeder → bu kayıt yayılmaz; ama eksik girdi reddi run-öncesi
                    raise LoggerError("bilinmeyen level/kind (%s/%s) → INVALID_REQUEST"
                                      % (rec.get("level"), rec.get("kind")))
                else:
                    self.level_violations += 1       # buggy: bilinmeyen taksonomi geçer (G2)

        # 1) head-based örnekleme kararı (tutarlı; correlation_id)
        frac = _sample_fraction(self.context.get(self.consistent_key, "x"))
        call_sampled_in = frac < self.base_rate
        self.derived["sample_fraction"] = round(frac, 4)
        self.derived["base_rate"] = self.base_rate
        self.derived["call_sampled_in"] = call_sampled_in

        # 2) tutma kararı (kept) + audit ayrımı
        kept = []           # [(rec, sink)]
        for rec in records:
            is_always = self._is_always(rec)
            is_audit = (rec.get("kind") == "audit")

            # audit ayrımı (G7): doğru Logger audit'i ASLA örneklemez + AYRI WORM sink
            if is_audit and self.pol.get("separate_audit", True):
                self.audit_count += 1
                kept.append((rec, self.worm_sink))
                continue
            if is_audit and not self.pol.get("separate_audit", True):
                # buggy: audit telemetri sink'e + örnekleme/garantisizlik → audit_violation
                self.audit_violations += 1
                self.audit_count += 1
                # buggy yolda audit normal telemetry gibi davranır (örneklenebilir)
                if call_sampled_in:
                    kept.append((rec, self.telemetry_sink))
                else:
                    self.sampled_out += 1
                continue

            # logs_always (WARN+/security/audit): her zaman tut — örnekleme kararından bağımsız
            if is_always:
                if self.pol.get("honor_always", True):
                    kept.append((rec, self.telemetry_sink))
                else:
                    # buggy: always onurlandırılmaz → örnekleme kararına tabi (G3)
                    if call_sampled_in:
                        kept.append((rec, self.telemetry_sink))
                    else:
                        self.sampling_violations += 1   # logs_always örneklemeyle DÜŞTÜ
                        self.sampled_out += 1
                continue

            # normal telemetry: head-based örneklenir
            if call_sampled_in:
                kept.append((rec, self.telemetry_sink))
            else:
                self.sampled_out += 1

        # 3) ASENKRON / non-blocking yazım + bounded buffer overflow (G4)
        if not self.pol.get("non_blocking", True):
            # buggy: senkron yazım → her kayıt hot-path'i bloklar
            self.blocking_violations += len(kept)

        # overflow: buffer dolarsa SAMPLEABLE önce düşer; GARANTİLİ asla düşmez
        if len(kept) > self.queue_capacity:
            over = len(kept) - self.queue_capacity
            # sampleable = normal telemetry (logs_always/audit DEĞİL); önce onları düşür
            guaranteed_idx = [i for i, (r, s) in enumerate(kept)
                              if self._is_always(r) or r.get("kind") == "audit"]
            sampleable_idx = [i for i, (r, s) in enumerate(kept)
                              if i not in set(guaranteed_idx)]
            drop_idx = set(sampleable_idx[:over])
            self.dropped_overflow += len(drop_idx)
            still_over = over - len(drop_idx)
            if still_over > 0:
                # garantili kayıt overflow ile düşmek zorunda kaldı → G4 ihlali
                self.overflow_violations += still_over
                self.dropped_overflow += still_over
                for i in guaranteed_idx[:still_over]:
                    drop_idx.add(i)
            kept = [kv for i, kv in enumerate(kept) if i not in drop_idx]

        # 4) kalan kept kayıtları YAY + denetle (yapı/kardinalite/label/PII/redaction)
        for rec, sink in kept:
            self._check_record_emit(rec, sink)

        self.derived["records_in"] = self.records_in
        self.derived["emitted"] = len(self.emitted)
        self.derived["sampled_out"] = self.sampled_out
        self.derived["dropped_overflow"] = self.dropped_overflow
        self.derived["audit_count"] = self.audit_count
        self.derived["worm_sink_records"] = sum(1 for e in self.emitted if e["sink"] == self.worm_sink)
        self.derived["telemetry_sink_records"] = sum(1 for e in self.emitted if e["sink"] == self.telemetry_sink)

    def metrics(self):
        return {
            "records_in": self.records_in,
            "emitted": len(self.emitted),
            "structure_missing": self.structure_missing,
            "level_violations": self.level_violations,
            "sampling_violations": self.sampling_violations,
            "blocking_violations": self.blocking_violations,
            "overflow_violations": self.overflow_violations,
            "cardinality_violations": self.cardinality_violations,
            "label_violations": self.label_violations,
            "pii_violations": self.pii_violations,
            "redaction_violations": self.redaction_violations,
            "audit_violations": self.audit_violations,
            "sampled_out": self.sampled_out,
            "dropped_overflow": self.dropped_overflow,
            "derived": dict(self.derived),
        }


def emit_call(sample, spec, context, policy):
    records = sample.get("records")
    if not isinstance(records, list) or not records:
        raise LoggerError("kayıt akışı (records) liste değil veya boş → INVALID_REQUEST")
    for rec in records:
        if not isinstance(rec, dict):
            raise LoggerError("kayıt (record) sözlük değil → INVALID_REQUEST")
        for k in spec.get("record_model", {}).get("required_record_keys", []):
            if k not in rec:
                raise LoggerError("kayıtta zorunlu anahtar eksik: %s → INVALID_REQUEST" % k)
    lg = StructuredAsyncLogger(spec, context, policy)
    # async_buffer override (örnek başına queue_capacity)
    ab_over = sample.get("async_buffer", {})
    if "queue_capacity" in ab_over:
        lg.queue_capacity = ab_over["queue_capacity"]
    # sampling override (örnek başına base_rate — deterministik senaryo)
    sm_over = sample.get("sampling", {})
    if "base_rate" in sm_over:
        lg.base_rate = sm_over["base_rate"]
    lg.run(records)
    return lg.metrics()


def evaluate(spec, m):
    """Metrikleri HARD kapılara (G1–G7) karşı değerlendirir. Döner findings[(ok, label)]."""
    g = spec.get("gates", {})
    d = m.get("derived", {})
    F = []
    F.append((m.get("structure_missing", 0) <= g.get("max_structure_missing", 0),
              "G1 yapı eksik %d ≤ %d (yayılan her kayıt required_body_keys taşır — SAD §17.1/FR-RES-012)"
              % (m.get("structure_missing", 0), g.get("max_structure_missing", 0))))
    F.append((m.get("level_violations", 0) <= g.get("max_level_violation", 0),
              "G2 taksonomi ihlali %d ≤ %d (level∈levels + kind∈kinds — SAD §17.1)"
              % (m.get("level_violations", 0), g.get("max_level_violation", 0))))
    F.append((m.get("sampling_violations", 0) <= g.get("max_sampling_violation", 0),
              "G3 örnekleme ihlali %d ≤ %d (logs_always WARN+/security/audit örneklemeyle DÜŞMEZ; sampled_out=%d — FR-RES-012)"
              % (m.get("sampling_violations", 0), g.get("max_sampling_violation", 0), m.get("sampled_out", 0))))
    F.append((m.get("blocking_violations", 0) <= g.get("max_blocking_violation", 0)
              and m.get("overflow_violations", 0) <= g.get("max_overflow_violation", 0),
              "G4 asenkron ihlali blocking=%d overflow=%d ≤ 0 (non-blocking; hot-path bloklanmaz + garantili kayıt overflow ile kaybolmaz — SR-RES-012)"
              % (m.get("blocking_violations", 0), m.get("overflow_violations", 0))))
    F.append((m.get("cardinality_violations", 0) <= g.get("max_cardinality_violation", 0)
              and m.get("label_violations", 0) <= g.get("max_label_violation", 0),
              "G5 stream-label ihlali kardinalite=%d label=%d ≤ 0 (kimlik gövde alanı + yalnız allowed — Loki 0.4.7)"
              % (m.get("cardinality_violations", 0), m.get("label_violations", 0))))
    F.append((m.get("pii_violations", 0) <= g.get("max_pii_violation", 0)
              and m.get("redaction_violations", 0) <= g.get("max_redaction_violation", 0),
              "G6 PII ihlali label=%d gövde-redaction=%d ≤ 0 (PII label yok + gövde ham PII yok — FR-REC-004)"
              % (m.get("pii_violations", 0), m.get("redaction_violations", 0))))
    F.append((m.get("audit_violations", 0) <= g.get("max_audit_violation", 0),
              "G7 audit ihlali %d ≤ %d (audit ASLA örneklenmez + AYRI WORM sink: worm=%s telemetri=%s — FR-IAM-006/0.4.7)"
              % (m.get("audit_violations", 0), g.get("max_audit_violation", 0),
                 d.get("worm_sink_records"), d.get("telemetry_sink_records"))))
    return F


# ─────────────────────────────────────────────────────────────────────────────
# bağlam + politika çözümleme
# ─────────────────────────────────────────────────────────────────────────────
def _profile_by_name(cfg, name):
    for p in cfg.get("profiles", []):
        if p.get("name") == name:
            return p
    raise LoggerError("bilinmeyen profil: %s" % name)


def _resolve_context(spec, profile, sample):
    ctx = dict(sample.get("context", {}))
    ctx.setdefault("region", profile.get("region"))
    ctx.setdefault("service", profile.get("service", "orchestrator"))
    return ctx


def _resolve_policy(spec, sample):
    pol = {
        "structure_keys": True,
        "conform_levels": True,
        "honor_always": True,
        "non_blocking": True,
        "enforce_cardinality": True,
        "enforce_labels": True,
        "enforce_pii": True,
        "redact_body": True,
        "separate_audit": True,
    }
    pol.update(sample.get("policy", {}))
    return pol


def emit_cmd(sample_path):
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
        except LoggerError as ex:
            print("emit[%s]: %s" % (name, ex))
            return 0 if expect == "fail" else 1
    context = _resolve_context(spec, profile, sample)
    policy = _resolve_policy(spec, sample)

    try:
        m = emit_call(sample, spec, context, policy)
    except LoggerError as ex:
        print("emit[%s]: REDDEDİLDİ — %s" % (name, ex))
        return 0 if expect == "fail" else 1

    F = evaluate(spec, m)
    d = m.get("derived", {})
    print("emit[%s] %d giriş → %d yayıldı | yapı=%d taksonomi=%d örnekleme=%d blocking=%d overflow=%d kardinalite=%d label=%d pii=%d redaction=%d audit=%d" % (
        name, m["records_in"], m["emitted"], m["structure_missing"], m["level_violations"],
        m["sampling_violations"], m["blocking_violations"], m["overflow_violations"],
        m["cardinality_violations"], m["label_violations"], m["pii_violations"],
        m["redaction_violations"], m["audit_violations"]))
    print("  örnekleme: frac=%s < base_rate=%s → çağrı sampled_in=%s | sampled_out=%d | overflow_drop=%d | audit=%d (worm=%s telemetri=%s)" % (
        d.get("sample_fraction"), d.get("base_rate"), d.get("call_sampled_in"),
        d.get("sampled_out"), d.get("dropped_overflow"), d.get("audit_count"),
        d.get("worm_sink_records"), d.get("telemetry_sink_records")))
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


def _scan_secrets(obj, path="root"):
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.startswith("$"):
                continue
            hits += _scan_secrets(v, "%s.%s" % (path, k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits += _scan_secrets(v, "%s[%d]" % (path, i))
    elif isinstance(obj, str):
        if _is_placeholder(obj):
            return hits
        if SECRET_RE.search(obj):
            hits.append((path, obj))
    return hits


def _load_observability_spec():
    """0.4.7 observability-spec.json (varsa) — çapraz-tutarlılık için."""
    cand = os.path.normpath(os.path.join(HERE, "..", "..", "docs", "platform", "observability",
                                          "observability-spec.json"))
    if os.path.exists(cand):
        try:
            return _load(cand)
        except Exception:
            return None
    return None


def validate():
    spec = _load(SPEC_PATH)
    R = []

    _check(R, spec.get("wbs") == "14.1.4", "spec.wbs == 14.1.4")
    _check(R, spec.get("version"), "spec.version mevcut")
    _check(R, spec.get("phase") == "F1", "spec.phase == F1")
    _check(R, spec.get("priority") == "Should", "spec.priority == Should (BRD FR-RES-012)")

    # ── G8: placement (orchestrator emisyon, structured, async, head-based, audit ayrı)
    pl = spec.get("placement", {})
    _check(R, pl.get("in_orchestrator") is True, "G8 Logger orchestrator içinde")
    _check(R, pl.get("emission_path") is True, "G8 emisyon yolunda")
    _check(R, pl.get("structured") is True, "G8 yapılandırılmış (structured)")
    _check(R, pl.get("async_non_blocking") is True, "G8 asenkron + non-blocking (SR-RES-012)")
    _check(R, pl.get("sampling_strategy") == "head-based", "G8 head-based örnekleme")
    _check(R, pl.get("audit_separate_worm_sink") is True, "G8 audit AYRI WORM sink")
    _check(R, pl.get("from_trace") is False, "G8 from_trace=false (log üretimi, trace türetme değil)")

    # ── record_model
    rm = spec.get("record_model", {})
    levels = rm.get("levels", [])
    kinds = rm.get("kinds", [])
    _check(R, set(levels) == {"DEBUG", "INFO", "WARN", "ERROR", "FATAL"},
           "G2 levels = DEBUG/INFO/WARN/ERROR/FATAL")
    _check(R, set(kinds) == {"telemetry", "security", "audit"},
           "G2 kinds = telemetry/security/audit")
    _check(R, set(rm.get("required_record_keys", [])) == {"level", "event", "kind"},
           "G2 required_record_keys = level/event/kind")

    # ── structured (G1)
    st = spec.get("structured", {})
    rbk = st.get("required_body_keys", [])
    _check(R, {"tenant_id", "correlation_id", "level", "event", "ts"} <= set(rbk),
           "G1 required_body_keys ⊇ tenant_id/correlation_id/level/event/ts")
    _check(R, {"correlation_id", "call_id", "trace_id"} <= set(st.get("body_identity_keys", [])),
           "G1 body_identity_keys = correlation_id/call_id/trace_id (gövde, stream label değil)")

    # ── sampling (G3 / 0.4.7 birebir)
    sm = spec.get("sampling", {})
    _check(R, sm.get("base_rate") == 0.2, "G3 base_rate = 0.2 (0.4.7 logs_base_rate)")
    _check(R, sm.get("always_classes") == ["level>=WARN", "security_event", "audit"],
           "G3 always_classes = level>=WARN/security_event/audit (0.4.7 logs_always)")
    _check(R, set(sm.get("always_levels", [])) == {"WARN", "ERROR", "FATAL"},
           "G3 always_levels = WARN/ERROR/FATAL")
    _check(R, set(sm.get("always_kinds", [])) == {"security", "audit"},
           "G3 always_kinds = security/audit")
    _check(R, sm.get("consistent_key") == "correlation_id", "G3 tutarlı örnekleme anahtarı correlation_id")

    # ── async_buffer (G4)
    ab = spec.get("async_buffer", {})
    _check(R, ab.get("non_blocking") is True, "G4 non_blocking (hot-path bloklanmaz, SR-RES-012)")
    _check(R, isinstance(ab.get("queue_capacity"), int) and ab.get("queue_capacity") > 0,
           "G4 queue_capacity > 0 (bounded ring buffer)")
    _check(R, ab.get("overflow_policy") == "drop_sampleable_first",
           "G4 overflow_policy = drop_sampleable_first (garantili korunur)")
    _check(R, ab.get("guaranteed_classes") == ["level>=WARN", "security_event", "audit"],
           "G4 guaranteed_classes = logs_always (overflow ile düşmez)")

    # ── stream_label_policy (G5/G6; 0.4.7 hizalı)
    slp = spec.get("stream_label_policy", {})
    allowed = set(slp.get("stream_labels_allowed", []))
    high = set(slp.get("high_cardinality_keys", []))
    pii = set(slp.get("pii_forbidden_keys", []))
    _check(R, allowed == {"tenant_id", "region", "service", "level"},
           "G5 stream_labels_allowed = tenant_id/region/service/level (Loki düşük-kardinalite)")
    _check(R, {"correlation_id", "call_id", "customer_id", "session_id"} <= high,
           "G5 high_cardinality_keys çekirdek kimlikleri içerir")
    _check(R, {"phone_number", "token", "transcript_text", "audio_payload"} <= pii,
           "G6 pii_forbidden_keys çekirdek PII anahtarlarını içerir")
    _check(R, not (allowed & high), "G5 izinli stream label ile yüksek-kardinalite kesişmez")
    _check(R, not (allowed & pii), "G6 izinli stream label ile PII kesişmez")

    # ── redaction (G6)
    rd = spec.get("redaction", {})
    _check(R, set(rd.get("identity_allowed_in_body", [])) >= {"correlation_id", "call_id", "trace_id"},
           "G6 kimlik gövdede izinli (correlation_id/call_id/trace_id; PII değil)")
    _check(R, len(rd.get("body_value_forbidden_patterns", [])) >= 3,
           "G6 gövde DEĞER yasak desenleri (≥3: digit-run/email/card/iban)")

    # ── audit (G7)
    au = spec.get("audit", {})
    _check(R, au.get("never_sampled") is True, "G7 audit ASLA örneklenmez (FR-IAM-006/0.4.7)")
    _check(R, au.get("separate_worm_sink") is True, "G7 audit AYRI WORM sink")
    _check(R, au.get("worm_sink") and au.get("telemetry_sink")
           and au.get("worm_sink") != au.get("telemetry_sink"),
           "G7 worm_sink ≠ telemetry_sink (audit ayrımı)")

    # ── 0.4.7 observability-spec ile BİREBİR (G9)
    obs = _load_observability_spec()
    if obs is not None:
        osm = obs.get("sampling", {})
        _check(R, osm.get("logs_base_rate") == sm.get("base_rate"),
               "G9 0.4.7 sampling.logs_base_rate (%s) base_rate ile birebir" % osm.get("logs_base_rate"))
        _check(R, osm.get("logs_always") == sm.get("always_classes"),
               "G9 0.4.7 sampling.logs_always always_classes ile birebir")
        note = osm.get("note", "")
        _check(R, ("audit" in note.lower()) and ("örneklenmez" in note.lower()),
               "G9 0.4.7 sampling.note audit ASLA örneklenmez teyit eder (audit.never_sampled)")
        olp = obs.get("label_policy", {})
        _check(R, set(olp.get("high_cardinality_keys", [])) == high,
               "G9 high_cardinality_keys 0.4.7 label_policy ile birebir")
        _check(R, set(olp.get("trace_log_required_keys", [])) <= set(rbk),
               "G9 0.4.7 trace_log_required_keys ⊆ required_body_keys (tenant_id/correlation_id)")
        # 0.4.7 pipelines.logs kaynağı = Yapılandırılmış asenkron logger (FR-RES-012)
        logs_src = obs.get("pipelines", {}).get("logs", {}).get("source", "")
        _check(R, "FR-RES-012" in logs_src or "asenkron" in logs_src.lower(),
               "G9 0.4.7 pipelines.logs kaynağı Yapılandırılmış asenkron logger (FR-RES-012)")

    # ── gates
    g = spec.get("gates", {})
    for gk in ("max_structure_missing", "max_level_violation", "max_sampling_violation",
               "max_blocking_violation", "max_overflow_violation", "max_cardinality_violation",
               "max_label_violation", "max_pii_violation", "max_redaction_violation",
               "max_audit_violation"):
        _check(R, g.get(gk, -1) == 0, "gate %s = 0" % gk)

    # ── error taxonomy (G10)
    et = spec.get("error_taxonomy", {})
    mapping = et.get("mapping", {})
    _check(R, len(mapping) >= 3, "G10 hata eşlemesi (≥3)")
    _check(R, all(v in ERROR_TAXONOMY for v in mapping.values()),
           "G10 tüm hedefler API §11.6 ErrorTaxonomy'de")
    _check(R, mapping.get("malformed_record") == "INVALID_REQUEST"
           and mapping.get("unknown_level") == "INVALID_REQUEST"
           and mapping.get("region_mismatch") == "REGION_VIOLATION",
           "G10 malformed/unknown→INVALID_REQUEST, region→REGION_VIOLATION")

    # ── pii (spec sağlığı, G10)
    _check(R, spec.get("pii", {}).get("raw_payload_in_spec_forbidden") is True,
           "G10 ham ses payload spec'te yasak")
    _check(R, spec.get("pii", {}).get("transcript_in_spec_forbidden") is True,
           "G10 transkript spec'te yasak")
    _check(R, spec.get("pii", {}).get("pii_values_in_spec_forbidden") is True,
           "G10 PII DEĞERİ spec'te yasak")

    # ── invariant kataloğu
    inv_ids = [i.get("id") for i in spec.get("invariants", [])]
    _check(R, len(inv_ids) == len(set(inv_ids)) and len(inv_ids) >= 10,
           "invariant kataloğu ≥10 + tekil ID")
    _check(R, all(i.get("trace") for i in spec.get("invariants", [])),
           "her invariant trace taşır")

    # ── literal sır + PII DEĞER taraması (spec + config)
    hits = _scan_secrets(spec)
    if os.path.exists(PROFILES_CFG):
        hits += _scan_secrets(_load(PROFILES_CFG))
    _check(R, not hits, "G10 literal sır yok (spec+config)")
    # spec/config gövde DEĞER PII taraması (yalnız anahtar adı olmalı, DEĞER değil)
    pii_hits = _scan_pii_values(spec)
    if os.path.exists(PROFILES_CFG):
        pii_hits += _scan_pii_values(_load(PROFILES_CFG))
    _check(R, not pii_hits, "G10 spec/config'te ham PII DEĞERİ yok (%s)" % (",".join(p for p, _ in pii_hits[:3]) or "-"))

    # ── config profilleri doğrulaması
    if os.path.exists(PROFILES_CFG):
        cfg = _load(PROFILES_CFG)
        profs = cfg.get("profiles", [])
        _check(R, len(profs) >= 2, "config ≥2 profil")
        pnames = [p.get("name") for p in profs]
        _check(R, len(pnames) == len(set(pnames)), "config profil isimleri benzersiz")
        for p in profs:
            _check(R, bool(p.get("region")), "residency config %s bölge pini var" % p.get("name"))

    passed = sum(1 for ok, _ in R if ok)
    total = len(R)
    for ok, label in R:
        if not ok:
            print("  ✗ %s" % label)
    print("validate: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


def _scan_pii_values(obj, path="root"):
    """spec/config'te ham PII DEĞERİ (telefon/email/...) tara — yalnız anahtar ADI olmalı."""
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.startswith("$"):
                continue
            hits += _scan_pii_values(v, "%s.%s" % (path, k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits += _scan_pii_values(v, "%s[%d]" % (path, i))
    elif isinstance(obj, str):
        if _is_placeholder(obj):
            return hits
        if PII_VALUE_RE.search(obj):
            hits.append((path, obj))
    return hits


# ─────────────────────────────────────────────────────────────────────────────
# selftest yardımcıları
# ─────────────────────────────────────────────────────────────────────────────
CONTEXT = {
    "tenant_id": "t_acme", "org_unit": "ou_support", "agent_id": "ag_inbound",
    "region": "eu-west-1", "service": "orchestrator",
    "correlation_id": "corr-acme-001", "trace_id": "tr-acme-001",
}

# tipik bir çağrının log kayıtları: çoğu normal telemetry (INFO/DEBUG) + birkaç garantili
# (WARN/ERROR/security/audit). PII DEĞERİ YOK — yalnız güvenli yapılandırılmış alanlar.
RECORDS = [
    {"level": "INFO", "kind": "telemetry", "event": "call_connected", "ts": "t0", "fields": {"sip_code": "200"}},
    {"level": "DEBUG", "kind": "telemetry", "event": "stt_partial", "ts": "t1", "fields": {"seq": 3}},
    {"level": "INFO", "kind": "telemetry", "event": "llm_first_token", "ts": "t2", "fields": {"tier": "small"}},
    {"level": "WARN", "kind": "telemetry", "event": "stt_retry", "ts": "t3", "fields": {"attempt": 2}},
    {"level": "ERROR", "kind": "telemetry", "event": "tool_error", "ts": "t4", "fields": {"tool": "crm_lookup"}},
    {"level": "INFO", "kind": "security", "event": "consent_skip_blocked", "ts": "t5", "fields": {"reason": "no_consent"}},
    {"level": "INFO", "kind": "audit", "event": "human_transfer", "ts": "t6", "fields": {"target": "queue_billing"}},
    {"level": "INFO", "kind": "telemetry", "event": "call_ended", "ts": "t7", "fields": {"outcome": "resolved"}},
]


def _full_pol():
    return {"structure_keys": True, "conform_levels": True, "honor_always": True,
            "non_blocking": True, "enforce_cardinality": True, "enforce_labels": True,
            "enforce_pii": True, "redact_body": True, "separate_audit": True}


def _run(records, spec, context=None, base_rate=None, queue_capacity=None, **pol_over):
    pol = _full_pol()
    pol.update(pol_over)
    sample = {"records": records}
    if base_rate is not None:
        sample["sampling"] = {"base_rate": base_rate}
    if queue_capacity is not None:
        sample["async_buffer"] = {"queue_capacity": queue_capacity}
    return emit_call(sample, spec, context or CONTEXT, pol)


def _raises(fn):
    try:
        fn()
        return False
    except LoggerError:
        return True


def selftest():
    spec = _load(SPEC_PATH)
    cases = []

    def case(ok, label):
        cases.append((bool(ok), label))

    # 0) validate iyi spec+config'te geçer
    case(_validate_obj(_load(SPEC_PATH)) == 0, "validate iyi spec+config'te 0 döndürür")

    # ── happy (sampled-in): base_rate=1.0 → tüm çağrı tutulur, tüm kapılar geçer ──
    mh = _run(RECORDS, spec, base_rate=1.0)
    case(mh["structure_missing"] == 0, "happy: yapı tam (G1)")
    case(mh["level_violations"] == 0, "happy: taksonomi uyumlu (G2)")
    case(mh["sampling_violations"] == 0, "happy: logs_always korunur (G3)")
    case(mh["blocking_violations"] == 0 and mh["overflow_violations"] == 0, "happy: non-blocking + overflow yok (G4)")
    case(mh["cardinality_violations"] == 0 and mh["label_violations"] == 0, "happy: stream-label disiplinli (G5)")
    case(mh["pii_violations"] == 0 and mh["redaction_violations"] == 0, "happy: PII/redaction temiz (G6)")
    case(mh["audit_violations"] == 0, "happy: audit ayrımı (G7)")
    case(all(ok for ok, _ in evaluate(spec, mh)), "happy tüm kapıları geçer")
    d = mh["derived"]
    case(d["call_sampled_in"] is True, "happy: base_rate=1.0 → çağrı sampled_in")
    case(mh["emitted"] == 8 and mh["sampled_out"] == 0, "happy: 8 kayıt yayıldı, 0 örneklendi (sampled-in)")
    case(d["worm_sink_records"] == 1, "happy: 1 audit kaydı WORM sink'e")
    case(d["telemetry_sink_records"] == 7, "happy: 7 kayıt telemetri sink'e")

    # ── sampled-out: base_rate=0.0 → çağrı düşer ama logs_always KORUNUR ──────
    ms = _run(RECORDS, spec, base_rate=0.0)
    case(ms["derived"]["call_sampled_in"] is False, "sampled: base_rate=0.0 → çağrı sampled_out")
    case(ms["sampling_violations"] == 0, "sampled: logs_always örneklemeyle düşmedi (G3 geçer)")
    # garantili: 2 normal-değil-telemetry WARN/ERROR + 1 security + 1 audit = 4 tutulur; 4 normal düşer
    case(ms["emitted"] == 4, "sampled: yalnız 4 garantili (WARN/ERROR/security/audit) yayıldı")
    case(ms["sampled_out"] == 4, "sampled: 4 normal INFO/DEBUG örneklendi (düştü)")
    case(all(ok for ok, _ in evaluate(spec, ms)), "sampled-out çağrı yine tüm kapıları geçer (volume↓, kayıp yok)")

    # ── tutarlılık: aynı correlation_id aynı karar (head-based) ────────────────
    f1 = ms["derived"]["sample_fraction"]
    ms2 = _run(RECORDS, spec, base_rate=0.0)
    case(ms2["derived"]["sample_fraction"] == f1, "tutarlı: aynı correlation_id aynı sample_fraction")

    # ── G1 yapı: structure_keys KAPALI → tenant_id gövdeden düşer ─────────────
    m1 = _run(RECORDS, spec, base_rate=1.0, structure_keys=False)
    case(m1["structure_missing"] >= 1, "yapı KAPALI: tenant_id gövdeden düşer → G1 eler")

    # ── G2 taksonomi: bilinmeyen level (conform_levels KAPALI) → geçer-ihlal ──
    badrec = json.loads(json.dumps(RECORDS))
    badrec[1]["level"] = "VERBOSE"   # bilinmeyen level
    m2 = _run(badrec, spec, base_rate=1.0, conform_levels=False)
    case(m2["level_violations"] >= 1, "taksonomi KAPALI: bilinmeyen level VERBOSE geçer → G2 eler")
    # conform_levels AÇIK → bilinmeyen level REDDEDİLİR
    case(_raises(lambda: _run(badrec, spec, base_rate=1.0)),
         "taksonomi AÇIK: bilinmeyen level → reddedilir (G10)")

    # ── G3 örnekleme: honor_always KAPALI + sampled-out → WARN/audit düşer ────
    m3 = _run(RECORDS, spec, base_rate=0.0, honor_always=False)
    case(m3["sampling_violations"] >= 1, "örnekleme KAPALI: logs_always sampled-out'ta düşer → G3 eler")

    # ── G4 asenkron: non_blocking KAPALI → senkron yazım hot-path'i bloklar ───
    m4 = _run(RECORDS, spec, base_rate=1.0, non_blocking=False)
    case(m4["blocking_violations"] >= 1, "non_blocking KAPALI: senkron yazım → G4 eler (hot-path bloklanır)")
    # overflow: küçük buffer + sampled-in → sampleable düşer (garantili korunur → geçer)
    m4o = _run(RECORDS, spec, base_rate=1.0, queue_capacity=5)
    case(m4o["dropped_overflow"] >= 1 and m4o["overflow_violations"] == 0,
         "overflow: küçük buffer → sampleable düşer, garantili korunur (G4 geçer)")
    # overflow garantili kaybı: buffer garantili sayısından (4) küçük → garantili düşmek zorunda → eler
    m4g = _run(RECORDS, spec, base_rate=1.0, queue_capacity=2)
    case(m4g["overflow_violations"] >= 1, "overflow: buffer < garantili → garantili kayıp → G4 eler")

    # ── G5 kardinalite/label ──────────────────────────────────────────────────
    m5c = _run(RECORDS, spec, base_rate=1.0, enforce_cardinality=False)
    case(m5c["cardinality_violations"] >= 1, "cardinality KAPALI: correlation_id stream label → G5 eler")
    m5l = _run(RECORDS, spec, base_rate=1.0, enforce_labels=False)
    case(m5l["label_violations"] >= 1, "label KAPALI: sınırsız stream label → G5 eler")

    # ── G6 PII label + gövde redaction ────────────────────────────────────────
    m6p = _run(RECORDS, spec, base_rate=1.0, enforce_pii=False)
    case(m6p["pii_violations"] >= 1, "pii KAPALI: phone_number stream label → G6 eler")
    leakrec = json.loads(json.dumps(RECORDS))
    leakrec[0]["fields"]["note"] = "ara 05551234567"   # ham telefon DEĞERİ gövdede
    m6r_ok = _run(leakrec, spec, base_rate=1.0)         # redact_body AÇIK → redakte → temiz
    case(m6r_ok["redaction_violations"] == 0, "redaction AÇIK: gövde ham PII redakte edilir → G6 geçer")
    m6r = _run(leakrec, spec, base_rate=1.0, redact_body=False)
    case(m6r["redaction_violations"] >= 1, "redaction KAPALI: ham telefon gövdede → G6 eler")
    # kimlik (correlation_id) yanlış-pozitif yapmaz
    case(mh["redaction_violations"] == 0, "kimlik (correlation_id/trace_id) PII yanlış-pozitif değil")

    # ── G7 audit ayrımı ───────────────────────────────────────────────────────
    m7 = _run(RECORDS, spec, base_rate=1.0, separate_audit=False)
    case(m7["audit_violations"] >= 1, "separate_audit KAPALI: audit telemetri sink + örneklenir → G7 eler")
    # sampled-out + separate_audit KAPALI → audit kaybolur (ihlal + sampled_out artar)
    m7s = _run(RECORDS, spec, base_rate=0.0, separate_audit=False)
    case(m7s["audit_violations"] >= 1, "separate_audit KAPALI + sampled-out: audit örneklenir/kaybolur → G7 eler")

    # ── reddetme (G10) ─────────────────────────────────────────────────────────
    case(_raises(lambda: emit_call({"records": []}, spec, CONTEXT, _full_pol())),
         "G10 boş records → reddedilir")
    case(_raises(lambda: emit_call({"records": [{"level": "INFO"}]}, spec, CONTEXT, _full_pol())),
         "G10 kayıtta event/kind eksik → reddedilir")
    case(_raises(lambda: StructuredAsyncLogger(spec, {"tenant_id": "t"}, _full_pol())),
         "G10 emisyon bağlamı (correlation_id) eksik → reddedilir")

    # ── determinizm ────────────────────────────────────────────────────────────
    a = _run(RECORDS, spec, base_rate=1.0)
    b = _run(RECORDS, spec, base_rate=1.0)
    case(a == b, "determinizm: aynı akış aynı sonucu verir (saf; sabit hash)")

    # ── validate negatif kapılar ─────────────────────────────────────────────
    s = json.loads(json.dumps(spec)); s["sampling"]["base_rate"] = 0.5
    case(_validate_obj(s) != 0, "G3/G9 base_rate 0.4.7 logs_base_rate'ten sapar (0.5) → validate eler")
    s = json.loads(json.dumps(spec)); s["sampling"]["always_classes"] = ["audit"]
    case(_validate_obj(s) != 0, "G3/G9 always_classes 0.4.7 logs_always'ten sapar → validate eler")
    s = json.loads(json.dumps(spec)); s["audit"]["never_sampled"] = False
    case(_validate_obj(s) != 0, "G7 audit.never_sampled kapalı → validate eler")
    s = json.loads(json.dumps(spec)); s["audit"]["worm_sink"] = s["audit"]["telemetry_sink"]
    case(_validate_obj(s) != 0, "G7 worm_sink == telemetry_sink → validate eler")
    s = json.loads(json.dumps(spec)); s["stream_label_policy"]["stream_labels_allowed"].append("correlation_id")
    case(_validate_obj(s) != 0, "G5 izinli stream label'a correlation_id eklenirse kesişim → validate eler")
    s = json.loads(json.dumps(spec)); s["structured"]["required_body_keys"] = ["level", "event", "ts"]
    case(_validate_obj(s) != 0, "G1/G9 required_body_keys'ten correlation_id düşerse (0.4.7 ⊆) → validate eler")
    s = json.loads(json.dumps(spec)); s["async_buffer"]["non_blocking"] = False
    case(_validate_obj(s) != 0, "G4 async_buffer.non_blocking kapalı → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_sampling_violation"] = 1
    case(_validate_obj(s) != 0, "G3 max_sampling_violation>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["error_taxonomy"]["mapping"]["x"] = "NOPE"
    case(_validate_obj(s) != 0, "G10 taksonomi-dışı → validate eler")
    s = json.loads(json.dumps(spec)); s["pii"]["pii_values_in_spec_forbidden"] = False
    case(_validate_obj(s) != 0, "G10 pii_values_in_spec_forbidden kapalı → validate eler")
    s = json.loads(json.dumps(spec)); s["record_model"]["leak_phone"] = "0555 123 4567"
    case(_validate_obj(s) != 0, "G10 spec'te ham PII DEĞERİ (telefon) → validate eler")
    s = json.loads(json.dumps(spec)); s["record_model"]["leak"] = "api_key: AKIAIOSFODNN7EXAMPLE"
    case(_validate_obj(s) != 0, "G10 literal secret → validate eler")

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
    print("""call-logger-spec.json beklenen şekli (WBS 14.1.4):
  wbs=14.1.4, version, phase=F1, priority=Should, logger_doc{fr,nfr,sad,adr,api,srs,rtm,brd,observability}
  placement{in_orchestrator, emission_path, structured=true, async_non_blocking=true,
            sampling_strategy=head-based, audit_separate_worm_sink=true, from_trace=false}     (G8)
  record_model{levels[5], kinds[telemetry/security/audit], required_record_keys[level/event/kind]} (G2)
  structured{required_body_keys[tenant_id/correlation_id/level/event/ts], body_identity_keys}    (G1)
  sampling{base_rate=0.2, always_classes[level>=WARN/security_event/audit], always_levels,
           always_kinds, consistent_key=correlation_id}  (0.4.7 logs_base_rate/logs_always)      (G3,G9)
  async_buffer{non_blocking=true, queue_capacity, overflow_policy=drop_sampleable_first,
               guaranteed_classes}  (SR-RES-012)                                                 (G4)
  stream_label_policy{stream_labels_allowed[tenant_id/region/service/level], high_cardinality_keys,
                      pii_forbidden_keys}  (Loki düşük-kardinalite, 0.4.7)                        (G5,G6)
  redaction{body_value_forbidden_patterns, identity_allowed_in_body}  (FR-REC-004)               (G6)
  audit{never_sampled=true, separate_worm_sink=true, worm_sink, telemetry_sink}  (FR-IAM-006)    (G7)
  gates{max_structure_missing=0, max_level_violation=0, max_sampling_violation=0,
        max_blocking_violation=0, max_overflow_violation=0, max_cardinality_violation=0,
        max_label_violation=0, max_pii_violation=0, max_redaction_violation=0,
        max_audit_violation=0}                                                                   (G1..G7)
  metrics_emitted{emitted[]}
  error_taxonomy{mapping→API §11.6 (malformed/unknown→INVALID_REQUEST, region→REGION_VIOLATION)}
  pii{raw_payload/transcript/pii_values_in_spec_forbidden}                                       (G10)
  invariants[≥10]{id, desc, trace}

config/call-logger-profiles.json: profiles[]{name, region, service, ...}

emit sample: {name, profile | profile_obj, expect, expected?{metrik:değer},
  context{tenant_id, correlation_id, region?, service?, agent_id?, trace_id?, call_id?},
  sampling?{base_rate}, async_buffer?{queue_capacity},
  policy?{structure_keys, conform_levels, honor_always, non_blocking, enforce_cardinality,
          enforce_labels, enforce_pii, redact_body, separate_audit},
  records[]{level, kind, event, ts?, fields?{güvenli yapılandırılmış alanlar}}}
  (PII DEĞERİ YOK — yalnız log sinyali + etiket/kimlik anahtarı ADLARI)

komutlar: validate | emit <sample.json> | selftest | schema""")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if cmd == "validate":
        return validate()
    if cmd == "emit":
        if len(sys.argv) < 3:
            print("kullanım: call_logger_probe.py emit <sample.json>")
            return 2
        return emit_cmd(sys.argv[2])
    if cmd == "selftest":
        return selftest()
    if cmd == "schema":
        return schema()
    print("bilinmeyen komut: %s (validate|emit|selftest|schema)" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main())
