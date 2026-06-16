#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 11.4 — PII redaction pipeline (async) (pii-redaction) referans probe.

11. workstream'in (Kayıt, Transkript & PII Redaction) PII REDACTION PIPELINE modülü ve F1-Must temel
yeteneği. FR-REC-004 ('Transkript üzerinde PII redaction uygulanmalıdır') + SR-REC-004 + TC-REC-004 +
DB §21 transcript.redaction_state (pending/redacted/not_required) + SAD §10.2 PII Redaction + SAD §19.2
('PII redaction pipeline (Analytics Plane, async)'; FR-RES-011)'i sahiplenir. Çağrının ÜRETİLMİŞ
transkriptini (11.3 transcript-build: segmentler + redaction_state ∈ {pending,not_required}) + sezilen
PII span'lerini (kategori + segment-içi offset; HAM DEĞER YOK) alır → DETERMİNİSTİK, FAIL-CLOSED, ASENKRON
bir redaction PLANI (her span için maskeleme direktifi) üretir + redaction_state pending→redacted geçişini
yönetir. 11.3'ün AŞAĞI AKIŞ TÜKETİCİSİ; kart/parola/OTP gizli-değer kategorilerini MASKELER + 11.5'e
DEVREDER (FR-REC-005). DETERMİNİSTİK FAIL-CLOSED motor:

  PiiRedactionRequest ─tenant─► içerik kapısı ─► input_state ─► async ─► maskele ─► no-leak ─► state pending→redacted
        │                │            │             │           │          │           │
        │   authorized = (upstream_transcript_decision == TRANSCRIPT)       │           │
        │      ├─ cross-tenant ──────────────────────────────────────────────────────► BLOCK (cross_tenant)          [K12]
        │      ├─ upstream yok/geçersiz ─────────────────────────────────────────────► BLOCK (no_upstream)
        │      ├─ içerik yok (upstream != TRANSCRIPT) ──────────────────────────────► NO_CONTENT (no content)         [K6]
        │      ├─ redacted girdi / not_required+span / malformed span ──────────────► BLOCK (invalid_redaction_input) [K5]
        │      ├─ not_required ∧ span yok ──────────────────────────────────────────► NOT_REQUIRED (maskeleme gerekmez)
        │      └─ pending ───────────────────────────────────────────────────────────► REDACTED (tüm span maskeli)   [K2/K3]

ÇEKİRDEK INVARIANT'lar: K2 redaction tamlığı (her PII span maskeleme direktifi alır; unredacted_pii=0;
FR-REC-004), K3 durum geçişi (pending→redacted yalnız tüm span maskeliyken; residüel PII ile redacted=
false_redacted; geri-düşme=state_regression), K4 ham PII sızıntısı yok (plan/audit/metrik yalnız maskeli
token+kategori+offset; ham değer=pii_leak; BRD §17.7), K5 atlanamaz (bypass=redaction_skip; pending
access-ready değil; malformed→BLOCK, fail-open yok), K6 içerik kapısı (upstream != TRANSCRIPT ⇒ NO_CONTENT;
FR-REC-002 aşağı akış — over_capture yasak), K7 residency (home-region), K8 asenkron/hot-path dışı
(execution_plane=analytics_async; hot_path=hotpath_violation; FR-RES-011). Her karar deterministik+terminal
(K1) + kanıt (K9) + audit (K10); metrik düşük-kardinalite + HAM PII yok (K11); ham PII/sır yok + tenant
izolasyonu (K12).

Kapsam dışı (bilinçli, başka modül SAHİBİ): içerik/kayıt KARARI + tamamen kapatma → 11.1 (FR-REC-001/002);
kanal/track → 11.2 (FR-REC-003); transkript ÜRETİMİ + redaction_state=pending işareti → 11.3 (TÜKETİLİR);
KART/PAROLA/OTP gizli-değer DEDEKSİYON KURALLARI + KAYITTAN çıkarma → 11.5 (FR-REC-005; transkript span'leri
MASKELENİR + DEVREDİLİR); PII DEDEKSİYON (NER/regex span) → STT/PII-dedektör (sezilen span TÜKETİLİR); ham
metin byte maskeleme UYGULAMASI + storage_uri → SAD §10.2 + DB §21 (PLAN + state KARARI verilir, ham metin
YAZILMAZ); erişim audit + görüntüleme yetkisi → 11.6 (FR-REC-008/009); retention/silme → FR-REC-006/007/010.

Kullanım:
  pii_redaction_probe.py validate          Statik spec/config/kapsama kapısı → çıkış kodu
  pii_redaction_probe.py check <sample>     Redaction motoru: senaryo(lar)ı çalıştır → kapı (K1–K12)
  pii_redaction_probe.py selftest           Gömülü davranış kontrolleri → çıkış kodu
  pii_redaction_probe.py schema             Karar sözleşmesini yazdır

Determinizm: kanonik direktif sırası (seq,start); Date.now/random YOK. Stdlib-only. Sır/credential ve
gerçek PII (telefon/kart/OTP/parola/ad/adres DEĞERİ / transkript metni / ham ses) üretilmez/yazılmaz
(fixture sentetik — yalnız kategori enum + offset + maskeli token; FR-TST-008).
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "pii-redaction-spec.json")
CONFIG_PATH = os.path.join(HERE, "config", "pii-redaction.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

OUTCOMES = ["REDACTED", "NOT_REQUIRED", "NO_CONTENT", "BLOCK"]
TERMINAL = {"REDACTED", "NOT_REQUIRED", "NO_CONTENT", "BLOCK"}
# İçeriğin görüntülemeye-hazır (access_ready) olduğu terminaller (temiz/redaksiyonlu içerik).
ACCESS_READY = {"REDACTED", "NOT_REQUIRED"}
RULES = ["redaction_completeness", "state_transition", "no_raw_pii",
         "mandatory_fail_closed", "content_gate", "residency_honored", "async_offpath"]
BLOCK_REASONS = ["invalid_redaction_input", "cross_tenant", "no_upstream"]
INVARIANT_IDS = ["K1", "K2", "K3", "K4", "K5", "K6", "K7", "K8", "K9", "K10", "K11", "K12"]
UPSTREAM_DECISIONS = {"TRANSCRIPT", "NO_TRANSCRIPT", "BLOCK"}
ACCEPTED_INPUT = {"pending", "not_required"}
PRODUCIBLE_OUTPUT = {"redacted", "not_required"}
FORBIDDEN_INPUT = {"redacted"}
MASK_TOKEN_RE = re.compile(r"^\[[A-Z0-9_]+\]$")

# Degrade (inject) — DOĞRU fail-closed/tamlık/sızıntısız redaction davranışını bozan müdahaleler.
INJECTIONS = {"skip_redaction", "leave_span", "false_redacted", "state_regression", "pii_leak",
              "persist_when_no_content", "residency_leak", "hotpath_exec", "failopen_redaction",
              "cross_tenant", "no_audit"}

VIOLATION_KEYS = [
    "redaction_skip", "unredacted_pii", "false_redacted", "state_regression", "pii_leak",
    "over_capture", "residency_violation", "hotpath_violation", "failopen", "cross_tenant",
    "missing_evidence", "missing_audit", "stuck_state", "secret_or_pii",
]

# ── Sızıntı tarayıcı (K12; 11.1/11.2/11.3 deseniyle) — ham PII (telefon/kart/OTP/...) yasak ──
LEAK_PATTERNS = [
    ("phone_e164", re.compile(r"\+(?!1632)\d{9,15}\b")),
    ("digits_long", re.compile(r"\b\d{7,19}\b")),
    ("secret_kw", re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|token|bearer|credential)\b\s*[:=]\s*\S")),
    ("privkey", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("pii_field", re.compile(r"(?i)\"(customer_phone_value|card_pan_value|cvv_value|otp_code_value|password_value|customer_name_value|address_value|account_number_value|iban_value|raw_value|pii_value|transcript_text|segment_text|raw_audio|raw_msisdn)\"\s*:")),
]
# Yapısal kimlik/enum/sayı/maskeli-token beyaz-listelenir.
LEAK_ALLOW = re.compile(r"(?i)(555-?01\d\d|\+1632|ITU|reserved|test|example|req-|call-|ev-|seg-|camp-|t-|corr-|prefix|masked|last4|\[[A-Z0-9_]+\]|\d{4}-\d{2}-\d{2})")


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def scan_leaks(text):
    """Ham PII / sır tarayıcı. Yorum/tarif satırı + maskeli token + kısa offset eler (11.x deseni)."""
    hits = []
    for ln, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("#"):
            continue
        for name, pat in LEAK_PATTERNS:
            for m in pat.finditer(line):
                frag = m.group(0)
                window = line[max(0, m.start() - 14):m.end() + 14]
                if '"$comment"' in line or '"desc"' in line or '"trace"' in line or '"rule"' in line:
                    continue
                if LEAK_ALLOW.search(window) or LEAK_ALLOW.search(frag):
                    continue
                hits.append((ln, name, frag))
    return hits


# ════════════════════════════════════════════════════════════════════════════
def _config(sample):
    """Config = ana pii-redaction.json; sample.config_override yapısal alanları geçersiz kılar."""
    cfg = _load(CONFIG_PATH)
    ov = sample.get("config_override", {}) or {}
    for k in ("pii_categories", "accepted_input_states", "producible_output_states",
              "forbidden_input_states", "execution_plane", "forbidden_execution_planes"):
        if k in ov:
            if isinstance(ov[k], dict) and isinstance(cfg.get(k), dict):
                cfg.setdefault(k, {}).update(ov[k])
            else:
                cfg[k] = ov[k]
    return cfg


def _collect_spans(segments):
    """Tüm segmentlerin sezilen PII span'lerini düz listeye topla (kanonik (seq,start) sıra)."""
    spans = []
    for seg in segments:
        seq = seg.get("seq")
        for sp in seg.get("pii_spans", []) or []:
            spans.append({
                "seq": seq,
                "category": sp.get("category"),
                "start": sp.get("start"),
                "length": sp.get("length"),
            })
    spans.sort(key=lambda s: ((s["seq"] if s["seq"] is not None else 0),
                              (s["start"] if s["start"] is not None else 0),
                              str(s["category"])))
    return spans


def _span_malformed(sp, categories):
    """Span malformed mı: kategori eksik/bilinmeyen, offset tamsayı değil."""
    if sp.get("category") not in categories:
        return True
    if not isinstance(sp.get("start"), int) or not isinstance(sp.get("length"), int):
        return True
    if sp.get("start") < 0 or sp.get("length") <= 0:
        return True
    return False


def build(sample, spec, inject=None, cfg=None):
    """Tek PII-redaction senaryosunu yürüt → PiiRedactionDecision + ihlal sayaçları.

    Motor DOĞRU fail-closed / tamlık / sızıntısız redaction davranışını hesaplar; inject (degrade) doğru
    davranışı bozar ve eşleşen ihlal sayacını artırır (11.1/11.2/11.3 inject deseniyle birebir)."""
    inject = set(inject if inject is not None else sample.get("inject", []))
    cfg = cfg if cfg is not None else _config(sample)

    tenant = sample.get("tenant_id")
    call_id = sample.get("call_id")
    request_id = sample.get("request_id")
    correlation_id = sample.get("correlation_id")
    direction = sample.get("direction")
    upstream = sample.get("upstream_transcript_decision")
    state_in = sample.get("redaction_state_in")
    exec_plane = sample.get("execution_plane", cfg.get("execution_plane", "analytics_async"))
    segments = list(sample.get("segments", []))
    storage_region = sample.get("storage_region")
    home_region = sample.get("home_region")
    in_region = bool(sample.get("in_region_storage_required", False))

    categories = cfg.get("pii_categories", {})
    forbidden_planes = set(cfg.get("forbidden_execution_planes", ["hot_path"]))

    v = {k: 0 for k in VIOLATION_KEYS}

    directives = None
    state_out = None
    access_ready = False
    content_present = False           # upstream içerik üretti mi
    no_content_persisted = True       # privacy-safe varsayılan
    block_reason = None
    authorized = None

    spans = _collect_spans(segments)
    span_count = len(spans)
    masked_count = 0

    # ── K12 (tenant izolasyonu) ──
    if "cross_tenant" in inject:
        v["cross_tenant"] += 1
    if sample.get("bind_tenant") and sample.get("bind_tenant") != tenant:
        v["cross_tenant"] += 1

    # ── K5 (fail-closed / ATLANAMAZ): bypass → maskeleme yapmadan redacted işaretle → redaction_skip ──
    if "skip_redaction" in inject:
        v["redaction_skip"] += 1
        state_out = "redacted"
        directives = []                                       # maskeleme yapılmadı
        access_ready = True
        content_present = True
        no_content_persisted = False
        v["unredacted_pii"] += span_count                     # tüm span maskesiz kaldı
        if span_count > 0:
            v["false_redacted"] += 1                          # residüel PII varken redacted
        evidence = _evidence(request_id, upstream, state_in, state_out, span_count, 0, access_ready,
                             no_content_persisted, storage_region, home_region, direction, None, exec_plane)
        if not request_id:
            v["missing_evidence"] += 1
        audit = None if "no_audit" in inject else _audit(
            "REDACTED", request_id, call_id, direction, state_in, state_out, span_count, 0,
            access_ready, no_content_persisted, correlation_id, tenant)
        if "no_audit" in inject:
            v["missing_audit"] += 1
        return _pack(sample, "REDACTED", v, directives, state_in, state_out, span_count, 0, access_ready,
                     content_present, no_content_persisted, storage_region, home_region, block_reason,
                     authorized, exec_plane, evidence, audit)

    # cross-tenant fail-closed BLOCK
    if v["cross_tenant"] > 0:
        block_reason = "cross_tenant"

    # ── upstream (11.3 kararı) yok/geçersiz → fail-closed BLOCK no_upstream ──
    if block_reason is None and upstream not in UPSTREAM_DECISIONS:
        block_reason = "no_upstream"

    if block_reason is not None:
        terminal = "BLOCK"
        no_content_persisted = True
        content_present = False
    else:
        # ── K6 (FR-REC-002 aşağı akış): içerik kapısı — upstream != TRANSCRIPT ⇒ NO_CONTENT ──
        authorized = (upstream == "TRANSCRIPT")
        if not authorized:
            content_present = False
            no_content_persisted = True
            terminal = "NO_CONTENT"
            if "persist_when_no_content" in inject:
                directives = [{"seq": s["seq"], "category": s["category"], "start": s["start"],
                               "length": s["length"], "masked_token": _mask(s["category"], categories),
                               "delegated_to": _deleg(s["category"], categories)} for s in spans]
                masked_count = len(directives)
                content_present = True
                no_content_persisted = False                  # içerik yokken redaction üretmek = over_capture
                v["over_capture"] += 1
        else:
            content_present = True
            # ── K8 asenkron / hot-path dışı ──
            if "hotpath_exec" in inject:
                exec_plane = "hot_path"
            if exec_plane in forbidden_planes:
                v["hotpath_violation"] += 1

            # ── redaction_state_in doğrula ──
            malformed = any(_span_malformed(
                {"category": s["category"], "start": s["start"], "length": s["length"]}, categories)
                for s in spans)

            if state_in in FORBIDDEN_INPUT:
                # 11.3 'redacted' üretmez; çift-redaction → fail-closed BLOCK
                block_reason = "invalid_redaction_input"
                terminal = "BLOCK"
                no_content_persisted = True
                content_present = False
            elif state_in == "not_required" and span_count > 0:
                # not_required ama PII span var → tutarsız → BLOCK
                block_reason = "invalid_redaction_input"
                terminal = "BLOCK"
                no_content_persisted = True
                content_present = False
            elif state_in not in ACCEPTED_INPUT:
                block_reason = "invalid_redaction_input"
                terminal = "BLOCK"
                no_content_persisted = True
                content_present = False
            elif malformed and "failopen_redaction" not in inject:
                # ── K5: malformed span → fail-closed BLOCK ──
                block_reason = "invalid_redaction_input"
                terminal = "BLOCK"
                no_content_persisted = True
                content_present = False
            elif state_in == "not_required":
                # span yok + not_required → maskeleme gerekmez (pass-through)
                terminal = "NOT_REQUIRED"
                state_out = "not_required"
                directives = []
                access_ready = True
                no_content_persisted = False
            else:
                # ── state_in == pending → maskeleme uygula (K2) ──
                if malformed and "failopen_redaction" in inject:
                    v["failopen"] += 1                        # malformed span'de sessiz redacted = K5 fail-open
                directives = []
                for s in spans:
                    directives.append({
                        "seq": s["seq"], "category": s["category"], "start": s["start"],
                        "length": s["length"], "masked_token": _mask(s["category"], categories),
                        "delegated_to": _deleg(s["category"], categories),
                    })
                # ── K2 leave_span: bir span maskelenmeden bırakılır ──
                if "leave_span" in inject and directives:
                    directives = directives[:-1]
                # ── K4 pii_leak: bir direktife HAM PII değeri sızdırılır (masked_token bozulur) ──
                if "pii_leak" in inject and directives:
                    directives[0] = dict(directives[0])
                    directives[0]["masked_token"] = "9055501" + "9012"   # ham-değer-benzeri (sentetik)

                masked_count = sum(1 for d in directives if MASK_TOKEN_RE.match(str(d.get("masked_token", ""))))

                # ── K2 tamlık: her span maskeleme direktifi almalı ──
                masked_keys = {(d["seq"], d["start"], d["category"]) for d in directives
                               if MASK_TOKEN_RE.match(str(d.get("masked_token", "")))}
                for s in spans:
                    if (s["seq"], s["start"], s["category"]) not in masked_keys:
                        v["unredacted_pii"] += 1

                # ── K4 ham-değer sızıntısı: masked_token bracket-token deseni dışında ──
                for d in directives:
                    if not MASK_TOKEN_RE.match(str(d.get("masked_token", ""))):
                        v["pii_leak"] += 1

                # ── K3 durum geçişi: pending→redacted (tüm span maskeliyse) ──
                state_out = "redacted"
                if "state_regression" in inject:
                    state_out = "pending"                     # redacted→pending geri-düşme
                    v["state_regression"] += 1
                if "false_redacted" in inject:
                    # residüel PII bırak ama redacted işaretle
                    if directives:
                        directives = directives[:-1]
                        v["unredacted_pii"] += 1
                    state_out = "redacted"

                access_ready = (state_out == "redacted")
                no_content_persisted = False
                terminal = "REDACTED"

                # ── K3 ÇEKİRDEK: redacted iddia edilirken residüel PII varsa false_redacted ──
                if state_out == "redacted" and v["unredacted_pii"] > 0:
                    v["false_redacted"] += 1

                # ── K6 residency ──
                if "residency_leak" in inject:
                    storage_region = (home_region or "EU") + "-ALT"
                if in_region and storage_region is not None and storage_region != home_region:
                    v["residency_violation"] += 1

    if block_reason is not None and terminal != "BLOCK":
        terminal = "BLOCK"

    # ── K5 ÇEKİRDEK GARANTİ: access_ready ⇒ redaction_state_out ∈ {redacted, not_required} ──
    if access_ready and state_out not in PRODUCIBLE_OUTPUT:
        v["false_redacted"] += 1

    # ── K6 ÇEKİRDEK GARANTİ: terminal ∉ {REDACTED,NOT_REQUIRED} ⇒ no_content_persisted=true ──
    if terminal not in ACCESS_READY and not no_content_persisted:
        v["over_capture"] += 1

    # ── K1 stuck state ──
    if terminal not in TERMINAL:
        v["stuck_state"] += 1

    dcount = len(directives) if directives else 0

    # ── Kanıt (K9) ──
    evidence = _evidence(request_id, upstream, state_in, state_out, span_count, masked_count, access_ready,
                         no_content_persisted, storage_region, home_region, direction, block_reason, exec_plane)
    if (not request_id) or (terminal is None):
        v["missing_evidence"] += 1

    # ── Audit (K10) ── (ham PII DEĞERİ YOK — yalnız kategori sayımı/maskeli token)
    audit = None
    if "no_audit" in inject:
        v["missing_audit"] += 1
    else:
        audit = _audit(terminal, request_id, call_id, direction, state_in, state_out, span_count,
                       masked_count, access_ready, no_content_persisted, correlation_id, tenant)

    return _pack(sample, terminal, v, directives, state_in, state_out, span_count, masked_count, access_ready,
                 content_present, no_content_persisted, storage_region, home_region, block_reason,
                 authorized, exec_plane, evidence, audit)


def _mask(category, categories):
    spec = categories.get(category, {})
    return spec.get("masked_token", "[REDACTED]")


def _deleg(category, categories):
    return categories.get(category, {}).get("delegated_to")


def _evidence(request_id, upstream, state_in, state_out, span_count, masked_count, access_ready,
              no_content_persisted, storage_region, home_region, direction, block_reason, exec_plane):
    return {
        "request_id": request_id,
        "upstream_transcript_decision": upstream,
        "redaction_state_in": state_in,
        "redaction_state_out": state_out,
        "pii_span_count": span_count,
        "masked_count": masked_count,
        "access_ready": access_ready,
        "no_content_persisted": no_content_persisted,
        "storage_region": storage_region,
        "home_region": home_region,
        "direction": direction,
        "block_reason": block_reason,
        "execution_plane": exec_plane,
    }


def _audit(terminal, request_id, call_id, direction, state_in, state_out, span_count, masked_count,
           access_ready, no_content_persisted, correlation_id, tenant):
    return {
        "result": terminal,
        "request_id": request_id,
        "call_id": call_id,
        "direction": direction,
        "redaction_state_in": state_in,
        "redaction_state_out": state_out,
        "pii_span_count": span_count,
        "masked_count": masked_count,
        "access_ready": access_ready,
        "no_content_persisted": no_content_persisted,
        "correlation_id": correlation_id,
        "tenant_id": tenant,
    }


def _pack(sample, terminal, v, directives, state_in, state_out, span_count, masked_count, access_ready,
          content_present, no_content_persisted, storage_region, home_region, block_reason,
          authorized, exec_plane, evidence, audit):
    return {
        "name": sample.get("name"),
        "terminal": terminal,
        "resolved": terminal in TERMINAL,
        "directives": directives,
        "directive_count": len(directives) if directives else 0,
        "redaction_state_in": state_in,
        "redaction_state_out": state_out,
        "pii_span_count": span_count,
        "masked_count": masked_count,
        "access_ready": access_ready,
        "content_present": content_present,
        "no_content_persisted": no_content_persisted,
        "storage_region": storage_region,
        "home_region": home_region,
        "block_reason": block_reason,
        "authorized": authorized,
        "execution_plane": exec_plane,
        "evidence": evidence,
        "audit": audit,
        "violations": v,
    }


def _gate_eval(result, gates):
    """Tek senaryo sonucunu HARD kapılara vur → (passed, fail_list)."""
    v = result["violations"]
    fails = []
    mapping = {
        "redaction_skip": "max_redaction_skip",
        "unredacted_pii": "max_unredacted_pii",
        "false_redacted": "max_false_redacted",
        "state_regression": "max_state_regression",
        "pii_leak": "max_pii_leak",
        "over_capture": "max_over_capture",
        "residency_violation": "max_residency_violation",
        "hotpath_violation": "max_hotpath_violation",
        "failopen": "max_failopen",
        "cross_tenant": "max_cross_tenant",
        "missing_evidence": "max_missing_evidence",
        "missing_audit": "max_missing_audit",
        "stuck_state": "max_stuck_state",
        "secret_or_pii": "max_secret_or_pii",
    }
    for vk, gk in mapping.items():
        limit = gates.get(gk, 0)
        if v.get(vk, 0) > limit:
            fails.append("%s=%d > %s=%d" % (vk, v[vk], gk, limit))
    if gates.get("require_terminal", True) and result["terminal"] not in TERMINAL:
        fails.append("terminal'e ulaşılmadı: %s" % result["terminal"])
    if gates.get("require_decision_record", True) and result["audit"] is None:
        fails.append("karar/audit kaydı üretilmedi (K10)")
    return (len(fails) == 0, fails)


# ════════════════════════════════════════════════════════════════════════════
def check_cmd(arg):
    spec = _load(SPEC_PATH)
    gates = spec["gates"]

    if os.path.isdir(arg):
        paths = sorted(os.path.join(arg, f) for f in os.listdir(arg) if f.endswith(".json"))
    else:
        paths = [arg]

    all_ok = True
    for p in paths:
        sample = _load(p)
        expect = sample.get("expect", "pass")
        res = build(sample, spec)
        with open(p, "r", encoding="utf-8") as fh:
            leaks = scan_leaks(fh.read())
        if leaks:
            res["violations"]["secret_or_pii"] += len(leaks)
        passed, fails = _gate_eval(res, gates)

        exp_assert = sample.get("expected", {})
        mism = []
        for key in ("terminal", "block_reason", "redaction_state_out", "directive_count",
                    "pii_span_count", "masked_count", "access_ready", "no_content_persisted"):
            if key in exp_assert and exp_assert[key] != res.get(key):
                mism.append("%s: beklenen=%r gerçek=%r" % (key, exp_assert[key], res.get(key)))

        verdict_ok = (passed and not mism) if expect == "pass" else (not passed)
        all_ok = all_ok and verdict_ok
        icon = "🟢" if verdict_ok else "🔴"
        print("%s %s" % (icon, os.path.basename(p)))
        print("   terminal=%s state_in=%s state_out=%s spans=%s masked=%s access=%s no_content=%s reason=%s"
              % (res["terminal"], res["redaction_state_in"], res["redaction_state_out"],
                 res["pii_span_count"], res["masked_count"], res["access_ready"],
                 res["no_content_persisted"], res["block_reason"]))
        nz = {k: val for k, val in res["violations"].items() if val}
        if nz:
            print("   ihlaller: %s" % nz)
        if expect == "pass" and fails:
            print("   ✗ kapı eler (beklenen geçer): %s" % "; ".join(fails))
        if expect == "fail" and passed:
            print("   ✗ kapı GEÇTİ (beklenen eler — degrade senaryo)")
        if mism and expect == "pass":
            print("   ✗ karar uyuşmazlığı: %s" % "; ".join(mism))
        if expect == "fail" and not passed:
            print("   ✓ beklendiği gibi elendi: %s" % "; ".join(fails[:3]))

    print("\ncheck: %s" % ("🟢 TÜM SENARYOLAR BEKLENDİĞİ GİBİ" if all_ok else "🔴 EN AZ BİR SENARYO BEKLENMEDİK"))
    return 0 if all_ok else 1


# ════════════════════════════════════════════════════════════════════════════
def validate():
    checks = []

    def chk(name, ok, detail=""):
        checks.append((name, ok, detail))

    spec = _load(SPEC_PATH)

    # 1) Üst-düzey alanlar
    for f in ("wbs", "phase", "priority", "trace", "placement", "rules", "decision",
              "block_reasons", "outcomes", "pii_categories", "redaction_states", "execution",
              "authorization", "gates", "observability", "invariants", "no_secrets"):
        chk("spec.%s var" % f, f in spec)
    chk("wbs=11.4", spec.get("wbs") == "11.4")
    chk("phase=F1", spec.get("phase") == "F1")
    chk("priority=Must", spec.get("priority") == "Must")
    chk("placement fail_closed=true", spec.get("placement", {}).get("fail_closed") is True)
    chk("placement async=true (FR-RES-011)", spec.get("placement", {}).get("async") is True)

    # 2) İzlenebilirlik
    tr = spec.get("trace", {})
    chk("FR-REC-004 izlenir (PII redaction — ÇEKİRDEK)", "FR-REC-004" in tr.get("fr", []))
    chk("FR-REC-005 izlenir (kart/parola/OTP → 11.5 devir)", "FR-REC-005" in tr.get("fr", []))
    chk("FR-REC-002 izlenir (içerik kapısı aşağı akış)", "FR-REC-002" in tr.get("fr", []))
    chk("FR-REC-008 izlenir (görüntüleme — 11.6)", "FR-REC-008" in tr.get("fr", []))
    chk("FR-REC-009 izlenir (erişim audit — 11.6)", "FR-REC-009" in tr.get("fr", []))
    chk("FR-RES-011 izlenir (asenkron analytics plane)", "FR-RES-011" in tr.get("fr", []))
    chk("FR-TEN-002 izlenir (tenant izolasyonu)", "FR-TEN-002" in tr.get("fr", []))
    chk("FR-IAM-006 izlenir (audit)", "FR-IAM-006" in tr.get("fr", []))
    chk("SR-REC-004 izlenir", "SR-REC-004" in tr.get("srs", []))
    chk("SR-REC-005 izlenir", "SR-REC-005" in tr.get("srs", []))
    chk("SR-REC-002 izlenir (no content aşağı akış)", "SR-REC-002" in tr.get("srs", []))
    chk("TC-REC-004 izlenir", "TC-REC-004" in tr.get("rtm", []))
    chk("NFR 10.7 izlenir (residency)", "NFR 10.7" in tr.get("nfr", []))
    chk("ADR-001/002/004/007/012 izlenir",
        all(any(a.startswith(x) for a in tr.get("adr", []))
            for x in ("ADR-001", "ADR-002", "ADR-004", "ADR-007", "ADR-012")))
    chk("SAD §10.2 PII Redaction izlenir", any("§10.2" in s for s in tr.get("sad", [])))
    chk("SAD §19.2 async pipeline izlenir", any("§19.2" in s for s in tr.get("sad", [])))
    chk("DB §21 redaction_state izlenir", any("§21" in d for d in tr.get("db", [])))
    chk("BRD §9.14 redaction izlenir", any("§9.14" in s for s in tr.get("brd", [])))
    chk("BRD §17.7 PII metrik/log'da yok izlenir", any("§17.7" in s for s in tr.get("brd", [])))
    chk("BRD §15 gizlilik alarmı izlenir", any("§15" in s for s in tr.get("brd", [])))
    chk("11.3 transcript-build consumes (transkript+pending)", any("11.3" in c for c in tr.get("consumes", [])))
    chk("11.5 consumed_by (secret kategori devri)", any("11.5" in c for c in tr.get("consumed_by", [])))
    chk("11.6 consumed_by (erişim audit/görüntüleme)", any("11.6" in c for c in tr.get("consumed_by", [])))

    # 3) Yedi kural (çekirdek)
    rz = spec["rules"]
    rule_ids = [d["id"] for d in rz.get("list", [])]
    chk("yedi kural tam (completeness/state/no_pii/mandatory/content/residency/async)", set(rule_ids) == set(RULES))
    chk("değerlendirme tenant_check_then_authorize_content_then_validate_input_state_then_check_async_then_mask_all_spans_then_no_leak_then_state_pending_to_redacted_fail_closed_no_content",
        rz.get("evaluation") == "tenant_check_then_authorize_content_then_validate_input_state_then_check_async_then_mask_all_spans_then_no_leak_then_state_pending_to_redacted_fail_closed_no_content")
    for d in rz.get("list", []):
        chk("kural %s invariant taşır" % d["id"], d.get("invariant") in INVARIANT_IDS)

    # 4) Karar
    dec = spec["decision"]
    chk("karar default=BLOCK (fail-closed)", dec.get("default") == "BLOCK")
    chk("fail_safe_terminal no_content", "no_content" in dec.get("fail_safe_terminal", ""))

    # 5) Sonuçlar + block_reason taksonomisi
    oc = spec["outcomes"]
    chk("terminal sonuçlar REDACTED/NOT_REQUIRED/NO_CONTENT/BLOCK", set(oc.get("list", [])) == set(OUTCOMES))
    br = set(spec["block_reasons"].get("list", []))
    chk("block_reason taksonomisi tam (invalid_redaction_input/cross_tenant/no_upstream)", br == set(BLOCK_REASONS))

    # 5b) pii_categories + redaction_states + execution
    pc = spec["pii_categories"]
    chk("pii_categories general phone/email içerir",
        all(c in pc.get("general", []) for c in ("phone", "email")))
    chk("pii_categories secret_delegated_to_11_5 card_pan/otp/password içerir",
        all(c in pc.get("secret_delegated_to_11_5", []) for c in ("card_pan", "otp", "password")))
    chk("pii_categories masked_token_pattern bracket-token", pc.get("masked_token_pattern") == "^\\[[A-Z0-9_]+\\]$")
    rs = spec["redaction_states"]
    chk("redaction accepted_input {pending,not_required}", set(rs.get("accepted_input", [])) == ACCEPTED_INPUT)
    chk("redaction producible_output {redacted,not_required}", set(rs.get("producible_output", [])) == PRODUCIBLE_OUTPUT)
    chk("redaction 'redacted' girdi YASAK", "redacted" in rs.get("forbidden_input", []))
    ex = spec["execution"]
    chk("execution plane=analytics_async (FR-RES-011)", ex.get("plane") == "analytics_async")
    chk("execution hot_path YASAK", "hot_path" in ex.get("forbidden_plane", []))
    chk("execution hot_path_excluded=true", ex.get("hot_path_excluded") is True)

    # 6) Yetki — transcript:read görüntüleme + otomatik async gate
    az = spec["authorization"]
    chk("view_permission=transcript:read (FR-REC-008)", az.get("view_permission") == "transcript:read")
    chk("per_call_check otomatik async gate", "automatic_async_gate" in az.get("per_call_check", ""))
    chk("karar backend'de", az.get("decision_at") == "backend")

    # 7) Kapılar — tüm sıfır-eşik ihlal kapıları
    g = spec["gates"]
    for gk in ("max_redaction_skip", "max_unredacted_pii", "max_false_redacted", "max_state_regression",
               "max_pii_leak", "max_over_capture", "max_residency_violation", "max_hotpath_violation",
               "max_failopen", "max_cross_tenant", "max_missing_evidence", "max_missing_audit",
               "max_stuck_state", "max_secret_or_pii"):
        chk("kapı %s=0" % gk, g.get(gk) == 0)
    chk("require_terminal", g.get("require_terminal") is True)
    chk("require_decision_record", g.get("require_decision_record") is True)

    # 8) Gözlemlenebilirlik — kardinalite disiplini (0.4.7)
    obs = spec["observability"]
    chk("pii_redaction_decision_total metrik", "pii_redaction_decision_total" in obs.get("metrics", []))
    chk("pii_redaction_masked_total metrik (kategori sayım)",
        "pii_redaction_masked_total" in obs.get("metrics", []))
    chk("pii_redaction_integrity_violation_total metrik (K2/K3/K4/K5/K6/K8 alarm)",
        "pii_redaction_integrity_violation_total" in obs.get("metrics", []))
    hi = set(obs.get("high_cardinality_trace_only", []))
    lo = set(obs.get("low_cardinality_labels", []))
    chk("request_id/call_id/correlation_id YÜKSEK kard (label değil)",
        "request_id" in hi and "call_id" in hi and "call_id" not in lo)
    chk("result/category/direction DÜŞÜK kard (label uygun)",
        "result" in lo and "category" in lo and "direction" in lo)
    chk("alarm unredacted_pii/pii_leak/redaction_skip ≤2dk",
        "unredacted_pii" in obs.get("alarm", "") or "pii_leak" in obs.get("alarm", ""))

    # 9) İnvariant'lar K1–K12
    inv_ids = [i["id"] for i in spec["invariants"]]
    chk("invariant'lar K1–K12 tam", inv_ids == INVARIANT_IDS)

    # 10) Config dosyası
    cfg_ok = os.path.exists(CONFIG_PATH)
    chk("config/pii-redaction.json var", cfg_ok)
    if cfg_ok:
        cfg = _load(CONFIG_PATH)
        cats = cfg.get("pii_categories", {})
        chk("config pii_categories phone→[PHONE]", cats.get("phone", {}).get("masked_token") == "[PHONE]")
        chk("config card_pan owner=11.5 (devir)", cats.get("card_pan", {}).get("owner") == "11.5")
        chk("config card_pan delegated_to=11.5", cats.get("card_pan", {}).get("delegated_to") == "11.5")
        chk("config tüm masked_token bracket-token deseni",
            all(MASK_TOKEN_RE.match(c.get("masked_token", "")) for c in cats.values()))
        chk("config accepted_input_states {pending,not_required}",
            set(cfg.get("accepted_input_states", [])) == ACCEPTED_INPUT)
        chk("config producible_output_states {redacted,not_required}",
            set(cfg.get("producible_output_states", [])) == PRODUCIBLE_OUTPUT)
        chk("config 'redacted' accepted_input DEĞİL", "redacted" not in cfg.get("accepted_input_states", []))
        chk("config execution_plane=analytics_async", cfg.get("execution_plane") == "analytics_async")
        chk("config hot_path forbidden", "hot_path" in cfg.get("forbidden_execution_planes", []))

    # 11) Sır/PII tarayıcı — spec + config + samples
    scan_files = [SPEC_PATH, CONFIG_PATH] + (
        [os.path.join(SAMPLES_DIR, f) for f in os.listdir(SAMPLES_DIR) if f.endswith(".json")]
        if os.path.isdir(SAMPLES_DIR) else [])
    total_leaks = 0
    for p in scan_files:
        if not os.path.exists(p):
            continue
        with open(p, "r", encoding="utf-8") as fh:
            hits = scan_leaks(fh.read())
        if hits:
            total_leaks += len(hits)
            chk("sızıntı yok: %s" % os.path.basename(p), False, str(hits[:2]))
    chk("hiç ham-PII/telefon/kart/OTP/transkript-metni/sır sızıntısı yok (K12)", total_leaks == 0)

    # 12) Samples — ≥1 pass + ≥1 fail (degrade ispatı)
    if os.path.isdir(SAMPLES_DIR):
        sample_files = sorted(f for f in os.listdir(SAMPLES_DIR) if f.endswith(".json"))
        chk("≥1 pass + ≥1 fail örnek (degrade ispatı)", _has_both(sample_files))

    npass = sum(1 for _, ok, _ in checks if ok)
    for name, ok, detail in checks:
        line = ("  ✓ " if ok else "  ✗ ") + name
        if not ok and detail:
            line += "  → " + detail
        print(line)
    total = len(checks)
    print("\nvalidate: %d/%d %s" % (npass, total, "🟢" if npass == total else "🔴"))
    return 0 if npass == total else 1


def _has_both(sample_files):
    have_pass = have_fail = False
    for f in sample_files:
        s = _load(os.path.join(SAMPLES_DIR, f))
        if s.get("expect", "pass") == "pass":
            have_pass = True
        else:
            have_fail = True
    return have_pass and have_fail


# ════════════════════════════════════════════════════════════════════════════
def selftest():
    results = []

    def case(name, cond):
        results.append((bool(cond), name))

    spec = _load(SPEC_PATH)
    G = spec["gates"]

    def req(**kw):
        # Varsayılan: 11.3 TRANSCRIPT + pending + 2 segment (phone + email span); storage=home(TR).
        d = {
            "request_id": "req-1", "tenant_id": "t-acme", "correlation_id": "corr-1",
            "call_id": "call-1", "direction": "inbound",
            "upstream_transcript_decision": "TRANSCRIPT", "redaction_state_in": "pending",
            "execution_plane": "analytics_async",
            "in_region_storage_required": True, "storage_region": "TR", "home_region": "TR",
            "segments": [
                {"seq": 1, "speaker": "caller", "pii_spans": [{"category": "phone", "start": 10, "length": 11}]},
                {"seq": 2, "speaker": "agent", "pii_spans": [{"category": "email", "start": 5, "length": 18}]},
            ],
        }
        d.update(kw)
        return d

    # 1) happy — pending + 2 span → REDACTED
    r = build(req(), spec)
    case("happy: REDACTED", r["terminal"] == "REDACTED")
    case("happy: state_out=redacted", r["redaction_state_out"] == "redacted")
    case("happy: 2 span → 2 direktif", r["directive_count"] == 2)
    case("happy: masked_count=2", r["masked_count"] == 2)
    case("happy: access_ready=true", r["access_ready"] is True)
    case("happy: no_content_persisted=false", r["no_content_persisted"] is False)
    case("happy: tüm masked_token bracket-token",
         all(MASK_TOKEN_RE.match(d["masked_token"]) for d in r["directives"]))
    case("happy: ihlal yok", all(x == 0 for x in r["violations"].values()))
    case("happy: audit REDACTED (K10)", r["audit"] is not None and r["audit"]["result"] == "REDACTED")
    case("happy: kapı geçer", _gate_eval(r, G)[0] is True)

    # 2) determinizm
    r1, r2 = build(req(), spec), build(req(), spec)
    case("determinizm: birebir", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))
    # direktifler kanonik (seq,start) sıralı
    rin = build(req(segments=[
        {"seq": 2, "speaker": "agent", "pii_spans": [{"category": "email", "start": 5, "length": 18}]},
        {"seq": 1, "speaker": "caller", "pii_spans": [{"category": "phone", "start": 10, "length": 11}]},
    ]), spec)
    case("kanonik sıra: direktif (seq,start) artan", [d["seq"] for d in rin["directives"]] == [1, 2])

    # 3) secret kategori → maskelenir + 11.5'e devredilir
    r = build(req(segments=[
        {"seq": 1, "speaker": "caller", "pii_spans": [{"category": "card_pan", "start": 3, "length": 16}]},
        {"seq": 1, "speaker": "caller", "pii_spans": [{"category": "otp", "start": 20, "length": 6}]},
    ]), spec)
    case("secret: REDACTED", r["terminal"] == "REDACTED")
    case("secret: card_pan/otp maskelendi", r["masked_count"] == 2 and all(x == 0 for x in r["violations"].values()))
    case("secret: delegated_to=11.5", all(d["delegated_to"] == "11.5" for d in r["directives"]))

    # 4) NOT_REQUIRED — not_required + span yok → pass-through
    r = build(req(redaction_state_in="not_required", segments=[
        {"seq": 1, "speaker": "caller", "pii_spans": []},
    ]), spec)
    case("not-required: NOT_REQUIRED", r["terminal"] == "NOT_REQUIRED")
    case("not-required: state_out=not_required", r["redaction_state_out"] == "not_required")
    case("not-required: 0 direktif", r["directive_count"] == 0)
    case("not-required: access_ready=true", r["access_ready"] is True)
    case("not-required: kapı geçer", _gate_eval(r, G)[0] is True)

    # 4b) not_required ama span var → tutarsız → BLOCK
    r = build(req(redaction_state_in="not_required"), spec)
    case("not-required+span: BLOCK invalid_redaction_input",
         r["terminal"] == "BLOCK" and r["block_reason"] == "invalid_redaction_input")

    # 5) pending + 0 span → REDACTED 0 direktif (pipeline çalıştı, temiz)
    r = build(req(segments=[{"seq": 1, "speaker": "caller", "pii_spans": []}]), spec)
    case("pending-0span: REDACTED 0 direktif", r["terminal"] == "REDACTED" and r["directive_count"] == 0)
    case("pending-0span: state_out=redacted", r["redaction_state_out"] == "redacted")
    case("pending-0span: ihlal yok", all(x == 0 for x in r["violations"].values()))

    # 6) K6 içerik kapısı — upstream NO_TRANSCRIPT → NO_CONTENT
    r = build(req(upstream_transcript_decision="NO_TRANSCRIPT"), spec)
    case("no-content: NO_CONTENT", r["terminal"] == "NO_CONTENT")
    case("no-content: no_content_persisted=true", r["no_content_persisted"] is True)
    case("no-content: access_ready=false", r["access_ready"] is False)
    case("no-content: 0 direktif", r["directive_count"] == 0)
    case("no-content: kapı geçer (gizlilik-güvenli)", _gate_eval(r, G)[0] is True)
    for up in ("BLOCK",):
        rr = build(req(upstream_transcript_decision=up), spec)
        case("no-content-%s: NO_CONTENT + no content" % up,
             rr["terminal"] == "NO_CONTENT" and rr["no_content_persisted"] is True)

    # 7) no_upstream — upstream yok → BLOCK
    r = build(req(upstream_transcript_decision=None), spec)
    case("no-upstream: BLOCK no_upstream", r["terminal"] == "BLOCK" and r["block_reason"] == "no_upstream")
    case("no-upstream: no content", r["no_content_persisted"] is True)

    # 8) redacted girdi → BLOCK invalid_redaction_input (11.3 'redacted' üretmez)
    r = build(req(redaction_state_in="redacted"), spec)
    case("redacted-input: BLOCK invalid_redaction_input",
         r["terminal"] == "BLOCK" and r["block_reason"] == "invalid_redaction_input")
    case("redacted-input: no content (fail-closed)", r["no_content_persisted"] is True)

    # 9) malformed span → BLOCK invalid_redaction_input
    r = build(req(segments=[{"seq": 1, "speaker": "caller", "pii_spans": [{"category": "unknown_cat", "start": 1, "length": 2}]}]), spec)
    case("malformed-cat: BLOCK invalid_redaction_input",
         r["terminal"] == "BLOCK" and r["block_reason"] == "invalid_redaction_input")
    case("malformed-cat: kapı geçer (fail-closed)", _gate_eval(r, G)[0] is True)

    # 10) K5 skip_redaction — bypass
    r = build(req(), spec, inject=["skip_redaction"])
    case("inject-skip: redaction_skip>0", r["violations"]["redaction_skip"] > 0)
    case("inject-skip: unredacted_pii>0", r["violations"]["unredacted_pii"] > 0)
    case("inject-skip: false_redacted>0", r["violations"]["false_redacted"] > 0)
    case("inject-skip: kapı eler", _gate_eval(r, G)[0] is False)

    # 11) K2 leave_span — bir span maskesiz
    r = build(req(), spec, inject=["leave_span"])
    case("inject-leave: unredacted_pii>0", r["violations"]["unredacted_pii"] > 0)
    case("inject-leave: false_redacted>0 (redacted iddia + residüel)", r["violations"]["false_redacted"] > 0)
    case("inject-leave: kapı eler", _gate_eval(r, G)[0] is False)

    # 12) K3 false_redacted — residüel PII varken redacted
    r = build(req(), spec, inject=["false_redacted"])
    case("inject-false-redacted: unredacted_pii>0", r["violations"]["unredacted_pii"] > 0)
    case("inject-false-redacted: false_redacted>0", r["violations"]["false_redacted"] > 0)
    case("inject-false-redacted: state_out=redacted (yalan)", r["redaction_state_out"] == "redacted")
    case("inject-false-redacted: kapı eler", _gate_eval(r, G)[0] is False)

    # 13) K3 state_regression — redacted→pending geri-düşme
    r = build(req(), spec, inject=["state_regression"])
    case("inject-regression: state_regression>0", r["violations"]["state_regression"] > 0)
    case("inject-regression: state_out=pending", r["redaction_state_out"] == "pending")
    case("inject-regression: false_redacted>0 (access_ready ihlali) veya regression", r["violations"]["state_regression"] > 0)
    case("inject-regression: kapı eler", _gate_eval(r, G)[0] is False)

    # 14) K4 pii_leak — ham değer planda
    r = build(req(), spec, inject=["pii_leak"])
    case("inject-leak: pii_leak>0", r["violations"]["pii_leak"] > 0)
    case("inject-leak: kapı eler", _gate_eval(r, G)[0] is False)

    # 15) K6 over_capture — içerik yokken redaction
    r = build(req(upstream_transcript_decision="NO_TRANSCRIPT"), spec, inject=["persist_when_no_content"])
    case("inject-overcapture: over_capture>0", r["violations"]["over_capture"] > 0)
    case("inject-overcapture: kapı eler", _gate_eval(r, G)[0] is False)

    # 16) K7 residency_leak
    r = build(req(), spec, inject=["residency_leak"])
    case("inject-residency: residency_violation>0", r["violations"]["residency_violation"] > 0)
    case("inject-residency: kapı eler", _gate_eval(r, G)[0] is False)
    r = build(req(storage_region="TR"), spec)
    case("residency: storage=home(TR) → ihlal yok", r["violations"]["residency_violation"] == 0)

    # 17) K8 hotpath_exec — hot-path'te yürütme
    r = build(req(), spec, inject=["hotpath_exec"])
    case("inject-hotpath: hotpath_violation>0", r["violations"]["hotpath_violation"] > 0)
    case("inject-hotpath: execution_plane=hot_path", r["execution_plane"] == "hot_path")
    case("inject-hotpath: kapı eler", _gate_eval(r, G)[0] is False)
    r = build(req(execution_plane="hot_path"), spec)
    case("plane=hot_path: hotpath_violation>0", r["violations"]["hotpath_violation"] > 0)

    # 18) K5 failopen_redaction — malformed span'de sessiz redacted
    r = build(req(segments=[{"seq": 1, "speaker": "caller", "pii_spans": [{"category": "unknown_cat", "start": 1, "length": 2}]}]),
              spec, inject=["failopen_redaction"])
    case("inject-failopen: failopen>0", r["violations"]["failopen"] > 0)
    case("inject-failopen: kapı eler", _gate_eval(r, G)[0] is False)

    # 19) K12 cross_tenant
    r = build(req(), spec, inject=["cross_tenant"])
    case("inject-cross-tenant: cross_tenant>0 + BLOCK",
         r["violations"]["cross_tenant"] > 0 and r["terminal"] == "BLOCK")
    r = build(req(bind_tenant="t-other"), spec)
    case("bind-mismatch: cross_tenant>0", r["violations"]["cross_tenant"] > 0)

    # 20) K10 no_audit
    r = build(req(), spec, inject=["no_audit"])
    case("inject-no-audit: missing_audit>0", r["violations"]["missing_audit"] > 0)
    case("inject-no-audit: audit None", r["audit"] is None)

    # 21) K6 GARANTİ — her terminal ∉ {REDACTED,NOT_REQUIRED} ⇒ no_content_persisted=true
    for kw in (dict(upstream_transcript_decision="NO_TRANSCRIPT"),
               dict(upstream_transcript_decision="BLOCK"),
               dict(upstream_transcript_decision=None),
               dict(redaction_state_in="redacted")):
        rr = build(req(**kw), spec)
        if rr["terminal"] not in ACCESS_READY:
            case("K6 garanti: %s → no_content_persisted=true" % rr["terminal"],
                 rr["no_content_persisted"] is True)

    # 22) K5 GARANTİ — access_ready ⇒ state_out ∈ {redacted, not_required}
    for kw in (dict(), dict(redaction_state_in="not_required", segments=[{"seq": 1, "pii_spans": []}])):
        rr = build(req(**kw), spec)
        if rr["access_ready"]:
            case("K5 garanti: access_ready ⇒ state_out üretilebilir (%s)" % rr["redaction_state_out"],
                 rr["redaction_state_out"] in PRODUCIBLE_OUTPUT)

    # 23) kanıt (K9) + audit (K10)
    r = build(req(), spec)
    case("evidence: request taşır", r["evidence"]["request_id"] == "req-1")
    case("evidence: upstream/state_in/state_out/span_count/masked_count taşır",
         all(k in r["evidence"] for k in ("upstream_transcript_decision", "redaction_state_in",
                                          "redaction_state_out", "pii_span_count", "masked_count")))
    case("audit: result/span_count/tenant taşır",
         r["audit"]["result"] == "REDACTED" and r["audit"]["pii_span_count"] == 2 and r["audit"]["tenant_id"] == "t-acme")
    case("audit: ham PII değeri alanı yok",
         all(k not in json.dumps(r["audit"]) for k in ("customer_phone_value", "card_pan_value", "otp_code_value", "transcript_text")))

    # 24) sızıntı tarayıcı
    case("leak: req-001 kimlik temiz", scan_leaks('{"request_id": "req-001"}') == [])
    case("leak: kategori/enum/offset temiz", scan_leaks('{"category": "phone", "start": 10, "length": 11}') == [])
    case("leak: maskeli token temiz", scan_leaks('{"masked_token": "[PHONE]"}') == [])
    case("leak: card_pan_value alanı yakalanır", len(scan_leaks('{"card_pan_value": "x"}')) > 0)
    case("leak: ham uzun rakam (kart/telefon) yakalanır", len(scan_leaks('{"x": "4111111111111111"}')) > 0)

    npass = sum(1 for ok, _ in results if ok)
    for ok, name in results:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print("\nselftest: %d/%d %s" % (npass, len(results), "🟢" if npass == len(results) else "🔴"))
    return 0 if npass == len(results) else 1


# ════════════════════════════════════════════════════════════════════════════
def schema_cmd():
    out = {
        "module": "pii-redaction (WBS 11.4 — PII redaction pipeline (async); FR-REC-004)",
        "outcomes": OUTCOMES,
        "terminal": sorted(TERMINAL),
        "access_ready_terminals": sorted(ACCESS_READY),
        "rules": RULES,
        "block_reasons": BLOCK_REASONS,
        "accepted_input_states": sorted(ACCEPTED_INPUT),
        "producible_output_states": sorted(PRODUCIBLE_OUTPUT),
        "forbidden_input_states": sorted(FORBIDDEN_INPUT),
        "decision": "tenant_check ⇒ BLOCK(cross_tenant) → upstream∉{TRANSCRIPT,NO_TRANSCRIPT,BLOCK} ⇒ "
                    "BLOCK(no_upstream) → upstream!=TRANSCRIPT ⇒ NO_CONTENT(no_content) → state_in=redacted "
                    "⇒ BLOCK(invalid_redaction_input) → not_required∧span ⇒ BLOCK(invalid_redaction_input) "
                    "→ malformed_span ⇒ BLOCK(invalid_redaction_input) → plane!=analytics_async ⇒ "
                    "hotpath_violation → mask_all_spans(seq,start) → completeness(unredacted_pii=0) → "
                    "no_leak(pii_leak=0) → state pending→redacted(residüel PII yok) → residency(home_region) "
                    "⇒ REDACTED | NOT_REQUIRED",
        "default": "BLOCK (fail-closed)",
        "fail_safe": "terminal ∉ {REDACTED,NOT_REQUIRED} ⇒ no_content_persisted=true ∧ access_ready=false (FR-REC-002 aşağı akış)",
        "core_guarantees": [
            "K2 redaction tamlığı: her PII span maskeleme direktifi alır (unredacted_pii=0)",
            "K3 durum geçişi: redacted ⇒ unredacted_pii=0 (false_redacted=0); geri-düşme yok (state_regression=0)",
            "K4 ham PII yok: plan/audit/metrik yalnız maskeli token+kategori+offset (pii_leak=0)",
            "K5 access_ready ⇒ state_out ∈ {redacted, not_required}; redaction atlanamaz (redaction_skip=0)",
            "K6 upstream != TRANSCRIPT ⇒ no_content_persisted=true (over_capture=0)",
            "K8 execution_plane=analytics_async (hotpath_violation=0; FR-RES-011)",
        ],
        "request_fields": ["name", "request_id", "tenant_id", "correlation_id", "call_id",
                           "direction(inbound|outbound)",
                           "upstream_transcript_decision(TRANSCRIPT|NO_TRANSCRIPT|BLOCK)",
                           "redaction_state_in(pending|not_required)",
                           "execution_plane(analytics_async|hot_path)",
                           "segments[{seq, speaker, pii_spans[{category, start, length}]}]",
                           "in_region_storage_required(bool)", "storage_region", "home_region",
                           "bind_tenant", "config_override{}", "inject[]", "expect", "expected{}"],
        "injections (degrade testi)": sorted(INJECTIONS),
        "decision_fields": ["terminal", "directives[{seq,category,start,length,masked_token,delegated_to}]",
                            "directive_count", "redaction_state_in", "redaction_state_out", "pii_span_count",
                            "masked_count", "access_ready", "content_present", "no_content_persisted",
                            "storage_region", "home_region", "block_reason", "execution_plane",
                            "evidence", "audit"],
        "violations": VIOLATION_KEYS,
        "invariants": INVARIANT_IDS,
        "pii_categories_general": ["phone", "email", "national_id", "iban", "account_number",
                                   "person_name", "address", "dob", "plate"],
        "pii_categories_secret_delegated_to_11_5": ["card_pan", "cvv", "otp", "password"],
        "consumes": "11.3 transcript-build (ÜRETİLMİŞ transkript + redaction_state_in=pending/not_required "
                    "+ upstream_transcript_decision) + STT/PII-dedektör (sezilen span {category,start,length}; "
                    "HAM DEĞER YOK)",
        "consumed_by": "SAD §10.2 Transcript Store + DB §21 (redaction PLANI + redaction_state=redacted; ham "
                       "metin byte maskeleme) + 11.5 (secret kategori delegated_to=11.5) + 11.6 (erişim "
                       "audit/görüntüleme; access_ready) + L2 A-12/A-13 panel (maskeli sunum)",
        "trace": "FR-REC-004, SR-REC-004, TC-REC-004, FR-REC-005 (11.5 devir), FR-REC-002/SR-REC-002 "
                 "(11.3/11.1 aşağı akış), FR-REC-008/009 (11.6), FR-RES-011 (async), FR-TEN-002, FR-IAM-006, "
                 "NFR 10.7, BRD §9.14/§15/§17.7, SAD §10.2 PII Redaction, SAD §19.2, DB §21 redaction_state, "
                 "ADR-001/002/004/007/012",
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd = argv[1]
    if cmd == "validate":
        return validate()
    if cmd == "check":
        if len(argv) < 3:
            print("kullanım: pii_redaction_probe.py check <sample.json|dizin>")
            return 2
        return check_cmd(argv[2])
    if cmd == "selftest":
        return selftest()
    if cmd == "schema":
        return schema_cmd()
    print("bilinmeyen komut: %s" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
