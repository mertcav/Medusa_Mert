#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 11.7 — Çağrı özeti üretimi (call-summary) referans probe.

11. workstream'in (Kayıt, Transkript & PII Redaction) ÇAĞRI ÖZETİ ÜRETİMİ modülü ve F1-Must temel
yeteneği. BRD §8.1 adım 9 ('Çağrıyı özetler ve sonuçlandırır') + FR-ANA-002 ('Çağrı sonucu, intent,
disposition ve completion durumu çıkarılmalıdır') + SR-ANA-002 + DB §21 transcript.summary ('çağrı özeti
(BRD §8.1)') + DB §19 call.outcome ('containment/transfer (FR-ANA-002/003)') + SAD §10.1/§10.2 özetleme +
SAD §19.2 (post-processing, async; FR-RES-011)'i sahiplenir. Çağrının görüntülemeye-hazır (PII-güvenli,
redakte) transkriptini (11.4 pii-redaction çıktısı: redaction_state ∈ {redacted, not_required}) +
segmentlerini (11.3) + LLM özetleyici aday özetini ({outcome, intent, disposition, completion, grounded_in,
key_points}) alır → DETERMİNİSTİK, FAIL-CLOSED, ASENKRON bir YAPISAL özet PLANI (kapalı-sözlük alanlar +
dayanaklı anahtar-noktalar) üretir + transcript.summary/call.outcome için terminal karar verir. 11.3+11.4'ün
AŞAĞI AKIŞ TÜKETİCİSİ. Özet bir LLM çıktısıdır; LLM-özgü RİSK HALÜSİNASYON'dur — bu modül özet alanlarının
transkripte DAYANDIĞINI (grounding) zorlar. DETERMİNİSTİK FAIL-CLOSED motor:

  CallSummaryRequest ─tenant─► içerik kapısı ─► PII-güvenli ─► async ─► sözlük ─► dayanak ─► no-leak ─► residency
        │                │            │             │            │         │          │          │
        │   authorized = (upstream_redaction_decision ∈ {REDACTED, NOT_REQUIRED})     │          │
        │      ├─ cross-tenant ────────────────────────────────────────────────────────────────► BLOCK (cross_tenant)          [K12]
        │      ├─ upstream yok/geçersiz ──────────────────────────────────────────────────────► BLOCK (no_upstream)
        │      ├─ içerik yok (upstream ∉ {REDACTED,NOT_REQUIRED}) ───────────────────────────► NO_CONTENT (no summary)         [K6]
        │      ├─ redaction_state=pending (henüz-redakte-edilmemiş kaynak) ─────────────────► BLOCK (premature_summary)        [K4]
        │      ├─ 0 segment (boş transkript) ────────────────────────────────────────────────► NO_SUMMARY (özetlenecek yok)
        │      ├─ sözlük-dışı outcome/disposition/completion/intent / zorunlu eksik ───────► BLOCK (invalid_summary_field)    [K3]
        │      └─ dolu transkript ────────────────────────────────────────────────────────────► SUMMARIZED (dayanaklı yapısal) [K2/K5]

ÇEKİRDEK INVARIANT'lar: K2 dayanak/sadakat (her özet alanı + anahtar-nokta grounded_in ⊆ transkript seq;
dayanaksız=ungrounded_claim=halüsinasyon; BRD §8.1/FR-ANA-002), K3 kapalı sözlük (outcome/disposition/
completion/intent KAPALI; sözlük-dışı=invalid_field→BLOCK; FR-ANA-002/DB §19/FR-OUT-011), K4 PII-güvenli
kaynak (özet YALNIZ redacted/not_required'tan; pending→premature_summary BLOCK; ham PII özette=pii_leak;
FR-REC-004 aşağı akış/BRD §17.7), K5 atlanamaz (bypass=summary_skip; dayanaksızla SUMMARIZED=false_grounding;
malformed→BLOCK, fail-open yok; SR-ANA-002/BRD §15), K6 içerik kapısı (upstream ∉ {REDACTED,NOT_REQUIRED} ⇒
NO_CONTENT; FR-REC-002 aşağı akış — over_capture yasak), K7 residency (home-region; NFR 10.7), K8 asenkron/
hot-path dışı (execution_plane=analytics_async; hot_path=hotpath_violation; FR-RES-011). Her karar
deterministik+terminal (K1) + kanıt (K9) + audit (K10); metrik düşük-kardinalite + HAM PII yok (K11); ham
PII/özet-prose/sır yok + tenant izolasyonu (K12).

Kapsam dışı (bilinçli, başka modül SAHİBİ): içerik/kayıt KARARI + tamamen kapatma → 11.1 (FR-REC-001/002);
kanal/track → 11.2 (FR-REC-003); transkript ÜRETİMİ → 11.3 (FR-REC-008; segment seq TÜKETİLİR); PII
redaction + redacted + access_ready → 11.4 (FR-REC-004; TÜKETİLİR — özet PII-güvenli kaynaktan); kart/parola/
OTP → 11.5 (FR-REC-005); erişim audit + görüntüleme yetkisi → 11.6 (FR-REC-008/009); özet PROSE METİN byte
ÜRETİMİ (LLM özetleyici) + transcript.summary storage yazımı → SAD §10.1/§10.2 + DB §21 (YAPISAL plan +
dayanak/sözlük KARARI verilir, ham özet metni YAZILMAZ); intent SINIFLANDIRMA + QA skorlama + containment
RAPORLAMA → FR-ANA-001/003..013; handoff bağlam paketi (gerçek-zamanlı özet) → 9.6/FR-HND-004 (AYRI); token
özetlemesi (hot-path Session Memory) → FR-LLM-005/FR-RES-010 (AYRI).

Kullanım:
  call_summary_probe.py validate          Statik spec/config/kapsama kapısı → çıkış kodu
  call_summary_probe.py check <sample>     Özet motoru: senaryo(lar)ı çalıştır → kapı (K1–K12)
  call_summary_probe.py selftest           Gömülü davranış kontrolleri → çıkış kodu
  call_summary_probe.py schema             Karar sözleşmesini yazdır

Determinizm: kanonik dayanak sırası (field,seq); Date.now/random YOK. Stdlib-only. Sır/credential ve gerçek
PII (telefon/kart/OTP/parola/ad/adres DEĞERİ / transkript metni / özet prose / ham ses) üretilmez/yazılmaz
(fixture sentetik — yalnız enum + dayanak seq + maskeli token; FR-TST-008).
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "call-summary-spec.json")
CONFIG_PATH = os.path.join(HERE, "config", "call-summary.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

OUTCOMES = ["SUMMARIZED", "NO_SUMMARY", "NO_CONTENT", "BLOCK"]
TERMINAL = {"SUMMARIZED", "NO_SUMMARY", "NO_CONTENT", "BLOCK"}
# Özetin kalıcılaştırıldığı (summary_persisted) terminaller.
SUMMARY_PERSISTED = {"SUMMARIZED"}
RULES = ["grounding_faithfulness", "controlled_vocabulary", "pii_safe_source",
         "mandatory_fail_closed", "content_gate", "residency_honored", "async_offpath"]
BLOCK_REASONS = ["invalid_summary_field", "premature_summary", "cross_tenant", "no_upstream"]
INVARIANT_IDS = ["K1", "K2", "K3", "K4", "K5", "K6", "K7", "K8", "K9", "K10", "K11", "K12"]
UPSTREAM_DECISIONS = {"REDACTED", "NOT_REQUIRED", "NO_CONTENT", "BLOCK"}
ACCESS_READY_UPSTREAM = {"REDACTED", "NOT_REQUIRED"}
ACCEPTED_SOURCE_STATES = {"redacted", "not_required"}
FORBIDDEN_SOURCE_STATES = {"pending"}
REQUIRED_FIELDS = ["outcome", "intent", "disposition", "completion"]
VOCAB_FIELDS = ["outcome", "disposition", "completion", "intent"]
MASK_TOKEN_RE = re.compile(r"^\[[A-Z0-9_]+\]$")

# Degrade (inject) — DOĞRU fail-closed/dayanaklı/PII-güvenli özet davranışını bozan müdahaleler.
INJECTIONS = {"skip_summary", "drop_grounding", "fabricate_field", "false_grounding", "pii_leak",
              "summarize_pending", "persist_when_no_content", "residency_leak", "hotpath_exec",
              "vocab_bypass", "failopen_summary", "cross_tenant", "no_audit"}

VIOLATION_KEYS = [
    "summary_skip", "ungrounded_claim", "false_grounding", "invalid_field", "pii_leak",
    "premature_summary", "over_capture", "residency_violation", "hotpath_violation", "failopen",
    "cross_tenant", "missing_evidence", "missing_audit", "stuck_state", "secret_or_pii",
]

# ── Sızıntı tarayıcı (K12; 11.1/11.2/11.3/11.4 deseniyle) — ham PII (telefon/kart/OTP/...) + özet-prose yasak ──
LEAK_PATTERNS = [
    ("phone_e164", re.compile(r"\+(?!1632)\d{9,15}\b")),
    ("digits_long", re.compile(r"\b\d{7,19}\b")),
    ("secret_kw", re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|token|bearer|credential)\b\s*[:=]\s*\S")),
    ("privkey", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("pii_field", re.compile(r"(?i)\"(customer_phone_value|card_pan_value|cvv_value|otp_code_value|password_value|customer_name_value|address_value|account_number_value|iban_value|raw_value|pii_value|transcript_text|segment_text|summary_text|summary_prose|raw_audio|raw_msisdn)\"\s*:")),
]
# Yapısal kimlik/enum/sayı/maskeli-token beyaz-listelenir.
LEAK_ALLOW = re.compile(r"(?i)(555-?01\d\d|\+1632|ITU|reserved|test|example|req-|call-|ev-|seg-|kp-|camp-|t-|corr-|prefix|masked|last4|\[[A-Z0-9_]+\]|\d{4}-\d{2}-\d{2})")


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def scan_leaks(text):
    """Ham PII / sır / özet-prose tarayıcı. Yorum/tarif satırı + maskeli token + kısa offset eler (11.x deseni)."""
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
    """Config = ana call-summary.json; sample.config_override yapısal alanları geçersiz kılar."""
    cfg = _load(CONFIG_PATH)
    ov = sample.get("config_override", {}) or {}
    for k in ("outcomes", "dispositions", "completions", "intent_catalog", "required_fields",
              "accepted_redaction_states", "forbidden_redaction_states", "execution_plane",
              "forbidden_execution_planes"):
        if k in ov:
            cfg[k] = ov[k]
    return cfg


def _seg_seqs(segments):
    """Transkript segment seq kümesi (dayanak referans evreni)."""
    seqs = set()
    for seg in segments:
        s = seg.get("seq")
        if isinstance(s, int):
            seqs.add(s)
    return seqs


def _grounded(refs, seg_seqs):
    """Dayanak geçerli mi: liste boş değil ∧ her referans seg seq evreninde."""
    if not isinstance(refs, list) or len(refs) == 0:
        return False
    for r in refs:
        if r not in seg_seqs:
            return False
    return True


def build(sample, spec, inject=None, cfg=None):
    """Tek çağrı-özeti senaryosunu yürüt → CallSummaryDecision + ihlal sayaçları.

    Motor DOĞRU fail-closed / dayanaklı / sözlük-içi / PII-güvenli özet davranışını hesaplar; inject (degrade)
    doğru davranışı bozar ve eşleşen ihlal sayacını artırır (11.1/11.2/11.3/11.4 inject deseniyle birebir)."""
    inject = set(inject if inject is not None else sample.get("inject", []))
    cfg = cfg if cfg is not None else _config(sample)

    tenant = sample.get("tenant_id")
    call_id = sample.get("call_id")
    request_id = sample.get("request_id")
    correlation_id = sample.get("correlation_id")
    direction = sample.get("direction")
    upstream = sample.get("upstream_redaction_decision")
    redaction_state = sample.get("redaction_state")
    exec_plane = sample.get("execution_plane", cfg.get("execution_plane", "analytics_async"))
    segments = list(sample.get("segments", []))
    summary = dict(sample.get("summary", {}) or {})
    storage_region = sample.get("storage_region")
    home_region = sample.get("home_region")
    in_region = bool(sample.get("in_region_storage_required", False))

    valid_outcomes = set(cfg.get("outcomes", []))
    valid_disp = set(cfg.get("dispositions", []))
    valid_compl = set(cfg.get("completions", []))
    valid_intent = set(cfg.get("intent_catalog", []))
    required = list(cfg.get("required_fields", REQUIRED_FIELDS))
    forbidden_planes = set(cfg.get("forbidden_execution_planes", ["hot_path"]))

    v = {k: 0 for k in VIOLATION_KEYS}

    plan = None                       # üretilen yapısal özet planı (alanlar + grounded)
    summary_persisted = False
    no_summary_persisted = True       # privacy-safe varsayılan
    content_present = False
    block_reason = None
    authorized = None
    grounded = None
    field_count = 0
    key_point_count = 0
    seg_seqs = _seg_seqs(segments)

    # ── K12 (tenant izolasyonu) ──
    if "cross_tenant" in inject:
        v["cross_tenant"] += 1
    if sample.get("bind_tenant") and sample.get("bind_tenant") != tenant:
        v["cross_tenant"] += 1

    # ── K5 (fail-closed / ATLANAMAZ): bypass → dayanak/sözlük doğrulanmadan SUMMARIZED → summary_skip ──
    if "skip_summary" in inject:
        v["summary_skip"] += 1
        plan = {"outcome": summary.get("outcome"), "intent": summary.get("intent"),
                "disposition": summary.get("disposition"), "completion": summary.get("completion"),
                "key_points": []}
        summary_persisted = True
        no_summary_persisted = False
        content_present = True
        grounded = False
        # dayanak doğrulanmadığından tüm zorunlu alanlar dayanaksız sayılır
        v["ungrounded_claim"] += len(required)
        v["false_grounding"] += 1
        field_count = len(required)
        evidence = _evidence(request_id, upstream, redaction_state, field_count, 0, grounded,
                             no_summary_persisted, storage_region, home_region, direction, None, exec_plane)
        if not request_id:
            v["missing_evidence"] += 1
        audit = None if "no_audit" in inject else _audit(
            "SUMMARIZED", request_id, call_id, direction, upstream, redaction_state, plan,
            field_count, 0, grounded, no_summary_persisted, correlation_id, tenant)
        if "no_audit" in inject:
            v["missing_audit"] += 1
        return _pack(sample, "SUMMARIZED", v, plan, upstream, redaction_state, field_count, 0, grounded,
                     content_present, no_summary_persisted, storage_region, home_region, block_reason,
                     authorized, exec_plane, evidence, audit)

    # cross-tenant fail-closed BLOCK
    if v["cross_tenant"] > 0:
        block_reason = "cross_tenant"

    # ── upstream (11.4 kararı) yok/geçersiz → fail-closed BLOCK no_upstream ──
    if block_reason is None and upstream not in UPSTREAM_DECISIONS:
        block_reason = "no_upstream"

    if block_reason is not None:
        terminal = "BLOCK"
        no_summary_persisted = True
        content_present = False
    else:
        # ── K6 (FR-REC-002 aşağı akış): içerik kapısı — upstream ∉ {REDACTED,NOT_REQUIRED} ⇒ NO_CONTENT ──
        authorized = (upstream in ACCESS_READY_UPSTREAM)
        if not authorized:
            content_present = False
            no_summary_persisted = True
            terminal = "NO_CONTENT"
            if "persist_when_no_content" in inject:
                plan = {"outcome": summary.get("outcome"), "intent": summary.get("intent"),
                        "disposition": summary.get("disposition"), "completion": summary.get("completion"),
                        "key_points": summary.get("key_points", [])}
                field_count = len(required)
                content_present = True
                no_summary_persisted = False           # içerik yokken özet üretmek = over_capture
                v["over_capture"] += 1
        else:
            content_present = True

            # ── K4 PII-güvenli kapı: redaction_state pending ⇒ BLOCK premature_summary ──
            src_state = redaction_state
            if "summarize_pending" in inject:
                src_state = "pending"                  # gate'i atla — pending kaynaktan özet üret
            if src_state in FORBIDDEN_SOURCE_STATES and "summarize_pending" not in inject:
                block_reason = "premature_summary"
                terminal = "BLOCK"
                no_summary_persisted = True
                content_present = False
            elif src_state not in ACCEPTED_SOURCE_STATES and "summarize_pending" not in inject:
                # bilinmeyen redaction_state → fail-closed BLOCK
                block_reason = "premature_summary"
                terminal = "BLOCK"
                no_summary_persisted = True
                content_present = False
            else:
                if "summarize_pending" in inject:
                    v["premature_summary"] += 1        # pending kaynaktan özet üretildi (PII sızma riski)

                # ── K8 asenkron / hot-path dışı ──
                if "hotpath_exec" in inject:
                    exec_plane = "hot_path"
                if exec_plane in forbidden_planes:
                    v["hotpath_violation"] += 1

                # ── boş transkript → NO_SUMMARY (özetlenecek konuşma yok) ──
                if len(segments) == 0:
                    terminal = "NO_SUMMARY"
                    summary_persisted = False
                    no_summary_persisted = True
                else:
                    # ── K3 kapalı-sözlük doğrula ──
                    outcome = summary.get("outcome")
                    disp = summary.get("disposition")
                    compl = summary.get("completion")
                    intent = summary.get("intent")

                    vocab_ok = (outcome in valid_outcomes and disp in valid_disp
                                and compl in valid_compl and intent in valid_intent)
                    missing_required = any(summary.get(f) in (None, "") for f in required)

                    if (not vocab_ok or missing_required) and "vocab_bypass" not in inject:
                        # ── K3: sözlük-dışı/eksik alan → fail-closed BLOCK ──
                        block_reason = "invalid_summary_field"
                        terminal = "BLOCK"
                        no_summary_persisted = True
                        content_present = False
                    else:
                        if (not vocab_ok or missing_required) and "vocab_bypass" in inject:
                            v["invalid_field"] += 1     # sözlük-dışı alanı geçerli kabul = K3 failopen

                        # ── dayanak doğrula (K2) — her zorunlu alan + her anahtar-nokta grounded_in ──
                        gmap = dict(summary.get("grounded_in", {}) or {})
                        if "drop_grounding" in inject:
                            # bir alanın dayanağını boşalt → ungrounded
                            if required:
                                gmap[required[0]] = []
                        key_points = list(summary.get("key_points", []) or [])
                        if "fabricate_field" in inject:
                            # transkriptte olmayan seq'e dayanan uydurma anahtar-nokta ekle
                            bad = max(seg_seqs) + 99 if seg_seqs else 999
                            key_points = key_points + [{"id": "kp-fab", "grounded_in": [bad]}]

                        for f in required:
                            if not _grounded(gmap.get(f, []), seg_seqs):
                                v["ungrounded_claim"] += 1
                        for kp in key_points:
                            if not _grounded(kp.get("grounded_in", []), seg_seqs):
                                v["ungrounded_claim"] += 1

                        field_count = len(required)
                        key_point_count = len(key_points)

                        # ── K4 ham-değer sızıntısı: anahtar-nokta token'ı maskeli değilse pii_leak ──
                        if "pii_leak" in inject and key_points:
                            key_points = [dict(kp) for kp in key_points]
                            key_points[0]["token"] = "9055501" + "9012"   # ham-değer-benzeri (sentetik)
                        for kp in key_points:
                            tok = kp.get("token")
                            if tok is not None and not MASK_TOKEN_RE.match(str(tok)):
                                v["pii_leak"] += 1

                        plan = {
                            "outcome": outcome, "intent": intent, "disposition": disp,
                            "completion": compl, "key_points": key_points,
                        }
                        grounded = (v["ungrounded_claim"] == 0)

                        # ── K5 false_grounding: dayanaksız içerikle SUMMARIZED iddiası ──
                        if "false_grounding" in inject:
                            # dayanağı boz ama yine SUMMARIZED işaretle
                            if required:
                                gmap2 = dict(gmap)
                                gmap2[required[-1]] = []
                                v["ungrounded_claim"] += 1
                                grounded = False
                            v["false_grounding"] += 1

                        summary_persisted = True
                        no_summary_persisted = False
                        terminal = "SUMMARIZED"

                        # ── K5 ÇEKİRDEK: SUMMARIZED iddia edilirken dayanaksız içerik varsa false_grounding ──
                        if grounded is False and v["false_grounding"] == 0:
                            v["false_grounding"] += 1

                        # ── K7 residency ──
                        if "residency_leak" in inject:
                            storage_region = (home_region or "EU") + "-ALT"
                        if in_region and storage_region is not None and storage_region != home_region:
                            v["residency_violation"] += 1

    if block_reason is not None and terminal != "BLOCK":
        terminal = "BLOCK"

    # ── K4 GARANTİ: pending kaynaktan özet üretildiyse (summarize_pending) içerik kalıcılaştı sayılır ──
    if "summarize_pending" in inject and terminal == "SUMMARIZED":
        no_summary_persisted = False

    # ── K6 ÇEKİRDEK GARANTİ: terminal ∉ {SUMMARIZED} ⇒ no_summary_persisted=true ──
    if terminal not in SUMMARY_PERSISTED and not no_summary_persisted:
        v["over_capture"] += 1

    # ── K5: failopen — malformed istek (geçersiz upstream/eksik) sessiz özetlenirse ──
    if "failopen_summary" in inject and terminal != "SUMMARIZED":
        # fail-closed BLOCK/NO_CONTENT'i sessiz SUMMARIZED'a çevirmeye çalış = failopen
        v["failopen"] += 1
        v["over_capture"] += 1

    # ── K1 stuck state ──
    if terminal not in TERMINAL:
        v["stuck_state"] += 1

    # ── Kanıt (K9) ──
    evidence = _evidence(request_id, upstream, redaction_state, field_count, key_point_count, grounded,
                         no_summary_persisted, storage_region, home_region, direction, block_reason, exec_plane)
    if (not request_id) or (terminal is None):
        v["missing_evidence"] += 1

    # ── Audit (K10) ── (ham PII DEĞERİ + özet PROSE YOK — yalnız enum + sayım)
    audit = None
    if "no_audit" in inject:
        v["missing_audit"] += 1
    else:
        audit = _audit(terminal, request_id, call_id, direction, upstream, redaction_state, plan,
                       field_count, key_point_count, grounded, no_summary_persisted, correlation_id, tenant)

    return _pack(sample, terminal, v, plan, upstream, redaction_state, field_count, key_point_count, grounded,
                 content_present, no_summary_persisted, storage_region, home_region, block_reason,
                 authorized, exec_plane, evidence, audit)


def _evidence(request_id, upstream, redaction_state, field_count, key_point_count, grounded,
              no_summary_persisted, storage_region, home_region, direction, block_reason, exec_plane):
    return {
        "request_id": request_id,
        "upstream_redaction_decision": upstream,
        "redaction_state": redaction_state,
        "field_count": field_count,
        "key_point_count": key_point_count,
        "grounded": grounded,
        "no_summary_persisted": no_summary_persisted,
        "storage_region": storage_region,
        "home_region": home_region,
        "direction": direction,
        "block_reason": block_reason,
        "execution_plane": exec_plane,
    }


def _audit(terminal, request_id, call_id, direction, upstream, redaction_state, plan,
           field_count, key_point_count, grounded, no_summary_persisted, correlation_id, tenant):
    p = plan or {}
    return {
        "result": terminal,
        "request_id": request_id,
        "call_id": call_id,
        "direction": direction,
        "upstream_redaction_decision": upstream,
        "redaction_state": redaction_state,
        "outcome": p.get("outcome"),
        "disposition": p.get("disposition"),
        "completion": p.get("completion"),
        "intent": p.get("intent"),
        "field_count": field_count,
        "key_point_count": key_point_count,
        "grounded": grounded,
        "no_summary_persisted": no_summary_persisted,
        "correlation_id": correlation_id,
        "tenant_id": tenant,
    }


def _pack(sample, terminal, v, plan, upstream, redaction_state, field_count, key_point_count, grounded,
          content_present, no_summary_persisted, storage_region, home_region, block_reason,
          authorized, exec_plane, evidence, audit):
    return {
        "name": sample.get("name"),
        "terminal": terminal,
        "resolved": terminal in TERMINAL,
        "plan": plan,
        "summary_persisted": terminal in SUMMARY_PERSISTED and not no_summary_persisted,
        "upstream_redaction_decision": upstream,
        "redaction_state": redaction_state,
        "field_count": field_count,
        "key_point_count": key_point_count,
        "grounded": grounded,
        "content_present": content_present,
        "no_summary_persisted": no_summary_persisted,
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
        "summary_skip": "max_summary_skip",
        "ungrounded_claim": "max_ungrounded_claim",
        "false_grounding": "max_false_grounding",
        "invalid_field": "max_invalid_field",
        "pii_leak": "max_pii_leak",
        "premature_summary": "max_premature_summary",
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
        for key in ("terminal", "block_reason", "field_count", "key_point_count", "grounded",
                    "summary_persisted", "no_summary_persisted"):
            if key in exp_assert and exp_assert[key] != res.get(key):
                mism.append("%s: beklenen=%r gerçek=%r" % (key, exp_assert[key], res.get(key)))

        verdict_ok = (passed and not mism) if expect == "pass" else (not passed)
        all_ok = all_ok and verdict_ok
        icon = "🟢" if verdict_ok else "🔴"
        print("%s %s" % (icon, os.path.basename(p)))
        print("   terminal=%s upstream=%s redaction=%s fields=%s kp=%s grounded=%s no_summary=%s reason=%s"
              % (res["terminal"], res["upstream_redaction_decision"], res["redaction_state"],
                 res["field_count"], res["key_point_count"], res["grounded"],
                 res["no_summary_persisted"], res["block_reason"]))
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
              "block_reasons", "outcomes", "summary_fields", "redaction_states", "execution",
              "authorization", "gates", "observability", "invariants", "no_secrets"):
        chk("spec.%s var" % f, f in spec)
    chk("wbs=11.7", spec.get("wbs") == "11.7")
    chk("phase=F1", spec.get("phase") == "F1")
    chk("priority=Must", spec.get("priority") == "Must")
    chk("placement fail_closed=true", spec.get("placement", {}).get("fail_closed") is True)
    chk("placement async=true (FR-RES-011)", spec.get("placement", {}).get("async") is True)

    # 2) İzlenebilirlik
    tr = spec.get("trace", {})
    chk("FR-ANA-002 izlenir (çağrı sonucu/intent/disposition/completion — ÇEKİRDEK)", "FR-ANA-002" in tr.get("fr", []))
    chk("FR-ANA-003 izlenir (containment/transfer)", "FR-ANA-003" in tr.get("fr", []))
    chk("FR-OUT-011 izlenir (disposition)", "FR-OUT-011" in tr.get("fr", []))
    chk("FR-REC-004 izlenir (PII-güvenli kaynak aşağı akış)", "FR-REC-004" in tr.get("fr", []))
    chk("FR-REC-002 izlenir (içerik kapısı aşağı akış)", "FR-REC-002" in tr.get("fr", []))
    chk("FR-REC-008 izlenir (görüntüleme — 11.6)", "FR-REC-008" in tr.get("fr", []))
    chk("FR-RES-011 izlenir (asenkron analytics plane)", "FR-RES-011" in tr.get("fr", []))
    chk("FR-TEN-002 izlenir (tenant izolasyonu)", "FR-TEN-002" in tr.get("fr", []))
    chk("FR-IAM-006 izlenir (audit)", "FR-IAM-006" in tr.get("fr", []))
    chk("SR-ANA-002 izlenir", "SR-ANA-002" in tr.get("srs", []))
    chk("SR-REC-004 izlenir (PII-güvenli kaynak)", "SR-REC-004" in tr.get("srs", []))
    chk("SR-REC-002 izlenir (no content aşağı akış)", "SR-REC-002" in tr.get("srs", []))
    chk("TC-ANA-002 izlenir", "TC-ANA-002" in tr.get("rtm", []))
    chk("NFR 10.7 izlenir (residency)", "NFR 10.7" in tr.get("nfr", []))
    chk("ADR-001/002/004/007/012 izlenir",
        all(any(a.startswith(x) for a in tr.get("adr", []))
            for x in ("ADR-001", "ADR-002", "ADR-004", "ADR-007", "ADR-012")))
    chk("BRD §8.1 çağrı özeti izlenir", any("§8.1" in s for s in tr.get("brd", [])))
    chk("BRD §9.15 analitik izlenir", any("§9.15" in s for s in tr.get("brd", [])))
    chk("BRD §17.7 PII metrik/log'da yok izlenir", any("§17.7" in s for s in tr.get("brd", [])))
    chk("BRD §15 alarmı izlenir", any("§15" in s for s in tr.get("brd", [])))
    chk("SAD §10.1 özetleme izlenir", any("§10.1" in s for s in tr.get("sad", [])))
    chk("SAD §10.2 Transcript Store izlenir", any("§10.2" in s for s in tr.get("sad", [])))
    chk("SAD §19.2 async izlenir", any("§19.2" in s for s in tr.get("sad", [])))
    chk("DB §21 transcript.summary izlenir", any("§21" in d for d in tr.get("db", [])))
    chk("DB §19 call.outcome izlenir", any("§19" in d for d in tr.get("db", [])))
    chk("11.4 pii-redaction consumes (PII-güvenli kaynak)", any("11.4" in c for c in tr.get("consumes", [])))
    chk("11.3 transcript-build consumes (segment seq)", any("11.3" in c for c in tr.get("consumes", [])))
    chk("11.6 consumed_by (erişim audit/görüntüleme)", any("11.6" in c for c in tr.get("consumed_by", [])))

    # 3) Yedi kural (çekirdek)
    rz = spec["rules"]
    rule_ids = [d["id"] for d in rz.get("list", [])]
    chk("yedi kural tam (grounding/vocab/pii_safe/mandatory/content/residency/async)", set(rule_ids) == set(RULES))
    chk("değerlendirme tenant→content→pii_safe→async→vocab→ground→no_leak→residency",
        rz.get("evaluation") == "tenant_check_then_authorize_content_then_pii_safe_gate_then_check_async_then_validate_vocabulary_then_ground_all_fields_then_no_leak_then_residency_fail_closed_no_summary")
    for d in rz.get("list", []):
        chk("kural %s invariant taşır" % d["id"], d.get("invariant") in INVARIANT_IDS)

    # 4) Karar
    dec = spec["decision"]
    chk("karar default=BLOCK (fail-closed)", dec.get("default") == "BLOCK")
    chk("fail_safe_terminal no_summary", "no_summary" in dec.get("fail_safe_terminal", ""))

    # 5) Sonuçlar + block_reason taksonomisi
    oc = spec["outcomes"]
    chk("terminal sonuçlar SUMMARIZED/NO_SUMMARY/NO_CONTENT/BLOCK", set(oc.get("list", [])) == set(OUTCOMES))
    br = set(spec["block_reasons"].get("list", []))
    chk("block_reason taksonomisi tam (invalid_summary_field/premature_summary/cross_tenant/no_upstream)",
        br == set(BLOCK_REASONS))

    # 5b) summary_fields + redaction_states + execution
    sf = spec["summary_fields"]
    chk("summary_fields required outcome/intent/disposition/completion",
        set(sf.get("required", [])) == set(REQUIRED_FIELDS))
    chk("summary_fields vocabularies outcome/disposition/completion/intent",
        set(sf.get("vocabularies", [])) == set(VOCAB_FIELDS))
    chk("summary_fields key_points groundable", "key_points" in sf.get("groundable", []))
    chk("summary_fields masked_token_pattern bracket-token",
        sf.get("masked_token_pattern") == "^\\[[A-Z0-9_]+\\]$")
    rs = spec["redaction_states"]
    chk("redaction accepted_source {redacted,not_required}", set(rs.get("accepted_source", [])) == ACCEPTED_SOURCE_STATES)
    chk("redaction 'pending' kaynak YASAK", "pending" in rs.get("forbidden_source", []))
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
    for gk in ("max_summary_skip", "max_ungrounded_claim", "max_false_grounding", "max_invalid_field",
               "max_pii_leak", "max_premature_summary", "max_over_capture", "max_residency_violation",
               "max_hotpath_violation", "max_failopen", "max_cross_tenant", "max_missing_evidence",
               "max_missing_audit", "max_stuck_state", "max_secret_or_pii"):
        chk("kapı %s=0" % gk, g.get(gk) == 0)
    chk("require_terminal", g.get("require_terminal") is True)
    chk("require_decision_record", g.get("require_decision_record") is True)

    # 8) Gözlemlenebilirlik — kardinalite disiplini (0.4.7)
    obs = spec["observability"]
    chk("call_summary_decision_total metrik", "call_summary_decision_total" in obs.get("metrics", []))
    chk("call_summary_field_total metrik (kapalı-sözlük dağılım)",
        "call_summary_field_total" in obs.get("metrics", []))
    chk("call_summary_integrity_violation_total metrik (K2/K3/K4/K5/K6/K8 alarm)",
        "call_summary_integrity_violation_total" in obs.get("metrics", []))
    hi = set(obs.get("high_cardinality_trace_only", []))
    lo = set(obs.get("low_cardinality_labels", []))
    chk("request_id/call_id/correlation_id YÜKSEK kard (label değil)",
        "request_id" in hi and "call_id" in hi and "call_id" not in lo)
    chk("result/outcome/disposition/completion DÜŞÜK kard (label uygun)",
        "result" in lo and "outcome" in lo and "disposition" in lo and "completion" in lo)
    chk("alarm ungrounded_claim/pii_leak/summary_skip ≤2dk",
        "ungrounded_claim" in obs.get("alarm", "") or "pii_leak" in obs.get("alarm", ""))

    # 9) İnvariant'lar K1–K12
    inv_ids = [i["id"] for i in spec["invariants"]]
    chk("invariant'lar K1–K12 tam", inv_ids == INVARIANT_IDS)

    # 10) Config dosyası
    cfg_ok = os.path.exists(CONFIG_PATH)
    chk("config/call-summary.json var", cfg_ok)
    if cfg_ok:
        cfg = _load(CONFIG_PATH)
        chk("config outcomes contained/transferred içerir",
            all(o in cfg.get("outcomes", []) for o in ("contained", "transferred")))
        chk("config dispositions resolved içerir", "resolved" in cfg.get("dispositions", []))
        chk("config completions completed/partial/not_completed",
            set(cfg.get("completions", [])) == {"completed", "partial", "not_completed"})
        chk("config intent_catalog 'other' kuyruğu açık", "other" in cfg.get("intent_catalog", []))
        chk("config required_fields outcome/intent/disposition/completion",
            set(cfg.get("required_fields", [])) == set(REQUIRED_FIELDS))
        chk("config accepted_redaction_states {redacted,not_required}",
            set(cfg.get("accepted_redaction_states", [])) == ACCEPTED_SOURCE_STATES)
        chk("config 'pending' accepted DEĞİL", "pending" not in cfg.get("accepted_redaction_states", []))
        chk("config execution_plane=analytics_async", cfg.get("execution_plane") == "analytics_async")
        chk("config hot_path forbidden", "hot_path" in cfg.get("forbidden_execution_planes", []))
        chk("config grounding_required=true", cfg.get("grounding_required") is True)

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
    chk("hiç ham-PII/telefon/kart/OTP/transkript-metni/özet-prose/sır sızıntısı yok (K12)", total_leaks == 0)

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
        # Varsayılan: 11.4 REDACTED + redacted + 2 segment; dayanaklı kapalı-sözlük özet; storage=home(TR).
        d = {
            "request_id": "req-1", "tenant_id": "t-acme", "correlation_id": "corr-1",
            "call_id": "call-1", "direction": "inbound",
            "upstream_redaction_decision": "REDACTED", "redaction_state": "redacted",
            "execution_plane": "analytics_async",
            "in_region_storage_required": True, "storage_region": "TR", "home_region": "TR",
            "segments": [
                {"seq": 1, "speaker": "caller"},
                {"seq": 2, "speaker": "agent"},
            ],
            "summary": {
                "outcome": "contained", "intent": "billing_inquiry",
                "disposition": "resolved", "completion": "completed",
                "grounded_in": {"outcome": [2], "intent": [1], "disposition": [2], "completion": [2]},
                "key_points": [{"id": "kp-1", "grounded_in": [1]}, {"id": "kp-2", "grounded_in": [2]}],
            },
        }
        d.update(kw)
        return d

    # 1) happy — REDACTED + redacted + dayanaklı → SUMMARIZED
    r = build(req(), spec)
    case("happy: SUMMARIZED", r["terminal"] == "SUMMARIZED")
    case("happy: summary_persisted=true", r["summary_persisted"] is True)
    case("happy: field_count=4", r["field_count"] == 4)
    case("happy: key_point_count=2", r["key_point_count"] == 2)
    case("happy: grounded=true", r["grounded"] is True)
    case("happy: no_summary_persisted=false", r["no_summary_persisted"] is False)
    case("happy: plan outcome=contained", r["plan"]["outcome"] == "contained")
    case("happy: ihlal yok", all(x == 0 for x in r["violations"].values()))
    case("happy: audit SUMMARIZED (K10)", r["audit"] is not None and r["audit"]["result"] == "SUMMARIZED")
    case("happy: audit ham PII/prose alanı yok",
         all(k not in json.dumps(r["audit"]) for k in ("summary_text", "summary_prose", "transcript_text")))
    case("happy: kapı geçer", _gate_eval(r, G)[0] is True)

    # 2) determinizm
    r1, r2 = build(req(), spec), build(req(), spec)
    case("determinizm: birebir", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))

    # 3) not_required kaynak → SUMMARIZED (PII yoktu, yine PII-güvenli)
    r = build(req(upstream_redaction_decision="NOT_REQUIRED", redaction_state="not_required"), spec)
    case("not-required-source: SUMMARIZED", r["terminal"] == "SUMMARIZED")
    case("not-required-source: grounded=true", r["grounded"] is True)
    case("not-required-source: kapı geçer", _gate_eval(r, G)[0] is True)

    # 4) K6 içerik kapısı — upstream NO_CONTENT → NO_CONTENT
    r = build(req(upstream_redaction_decision="NO_CONTENT", redaction_state="not_required"), spec)
    case("no-content: NO_CONTENT", r["terminal"] == "NO_CONTENT")
    case("no-content: no_summary_persisted=true", r["no_summary_persisted"] is True)
    case("no-content: summary_persisted=false", r["summary_persisted"] is False)
    case("no-content: kapı geçer (gizlilik-güvenli)", _gate_eval(r, G)[0] is True)
    r = build(req(upstream_redaction_decision="BLOCK", redaction_state="pending"), spec)
    case("no-content-BLOCK: NO_CONTENT + no summary",
         r["terminal"] == "NO_CONTENT" and r["no_summary_persisted"] is True)

    # 5) K4 PII-güvenli kapı — redaction_state=pending → BLOCK premature_summary
    r = build(req(redaction_state="pending"), spec)
    case("pending-source: BLOCK premature_summary",
         r["terminal"] == "BLOCK" and r["block_reason"] == "premature_summary")
    case("pending-source: no summary (fail-closed)", r["no_summary_persisted"] is True)
    case("pending-source: kapı geçer (fail-closed)", _gate_eval(r, G)[0] is True)

    # 6) no_upstream — upstream yok → BLOCK
    r = build(req(upstream_redaction_decision=None), spec)
    case("no-upstream: BLOCK no_upstream", r["terminal"] == "BLOCK" and r["block_reason"] == "no_upstream")
    case("no-upstream: no summary", r["no_summary_persisted"] is True)

    # 7) boş transkript → NO_SUMMARY
    r = build(req(segments=[], summary={"outcome": "abandoned", "intent": "other",
                                        "disposition": "no_action", "completion": "not_completed",
                                        "grounded_in": {}, "key_points": []}), spec)
    case("empty-transcript: NO_SUMMARY", r["terminal"] == "NO_SUMMARY")
    case("empty-transcript: summary_persisted=false", r["summary_persisted"] is False)
    case("empty-transcript: ihlal yok", all(x == 0 for x in r["violations"].values()))
    case("empty-transcript: kapı geçer", _gate_eval(r, G)[0] is True)

    # 8) K3 sözlük-dışı outcome → BLOCK invalid_summary_field
    r = build(req(summary={"outcome": "made_up_outcome", "intent": "billing_inquiry",
                           "disposition": "resolved", "completion": "completed",
                           "grounded_in": {"outcome": [1], "intent": [1], "disposition": [1], "completion": [1]},
                           "key_points": []}), spec)
    case("bad-outcome: BLOCK invalid_summary_field",
         r["terminal"] == "BLOCK" and r["block_reason"] == "invalid_summary_field")
    case("bad-outcome: kapı geçer (fail-closed)", _gate_eval(r, G)[0] is True)

    # 8b) sözlük-dışı intent → BLOCK
    r = build(req(summary={"outcome": "contained", "intent": "unknown_intent_xyz",
                           "disposition": "resolved", "completion": "completed",
                           "grounded_in": {"outcome": [1], "intent": [1], "disposition": [1], "completion": [1]},
                           "key_points": []}), spec)
    case("bad-intent: BLOCK invalid_summary_field",
         r["terminal"] == "BLOCK" and r["block_reason"] == "invalid_summary_field")

    # 8c) zorunlu alan eksik → BLOCK
    r = build(req(summary={"outcome": "contained", "intent": "billing_inquiry", "completion": "completed",
                           "grounded_in": {"outcome": [1], "intent": [1], "completion": [1]},
                           "key_points": []}), spec)
    case("missing-disposition: BLOCK invalid_summary_field",
         r["terminal"] == "BLOCK" and r["block_reason"] == "invalid_summary_field")

    # 9) K5 skip_summary — bypass
    r = build(req(), spec, inject=["skip_summary"])
    case("inject-skip: summary_skip>0", r["violations"]["summary_skip"] > 0)
    case("inject-skip: ungrounded_claim>0", r["violations"]["ungrounded_claim"] > 0)
    case("inject-skip: false_grounding>0", r["violations"]["false_grounding"] > 0)
    case("inject-skip: kapı eler", _gate_eval(r, G)[0] is False)

    # 10) K2 drop_grounding — bir alanın dayanağı boş
    r = build(req(), spec, inject=["drop_grounding"])
    case("inject-drop-grounding: ungrounded_claim>0", r["violations"]["ungrounded_claim"] > 0)
    case("inject-drop-grounding: grounded=false", r["grounded"] is False)
    case("inject-drop-grounding: false_grounding>0 (SUMMARIZED iddia + dayanaksız)",
         r["violations"]["false_grounding"] > 0)
    case("inject-drop-grounding: kapı eler", _gate_eval(r, G)[0] is False)

    # 11) K2 fabricate_field — transkriptte olmayan seq'e dayanan uydurma anahtar-nokta (halüsinasyon)
    r = build(req(), spec, inject=["fabricate_field"])
    case("inject-fabricate: ungrounded_claim>0 (halüsinasyon)", r["violations"]["ungrounded_claim"] > 0)
    case("inject-fabricate: kapı eler", _gate_eval(r, G)[0] is False)

    # 12) K5 false_grounding — dayanaksız içerikle SUMMARIZED iddiası
    r = build(req(), spec, inject=["false_grounding"])
    case("inject-false-grounding: false_grounding>0", r["violations"]["false_grounding"] > 0)
    case("inject-false-grounding: ungrounded_claim>0", r["violations"]["ungrounded_claim"] > 0)
    case("inject-false-grounding: kapı eler", _gate_eval(r, G)[0] is False)

    # 13) K3 vocab_bypass — sözlük-dışı alan geçerli kabul edildi (failopen)
    r = build(req(summary={"outcome": "made_up", "intent": "billing_inquiry",
                           "disposition": "resolved", "completion": "completed",
                           "grounded_in": {"outcome": [1], "intent": [1], "disposition": [1], "completion": [1]},
                           "key_points": []}), spec, inject=["vocab_bypass"])
    case("inject-vocab-bypass: invalid_field>0", r["violations"]["invalid_field"] > 0)
    case("inject-vocab-bypass: kapı eler", _gate_eval(r, G)[0] is False)

    # 14) K4 pii_leak — ham değer anahtar-nokta token'ında
    r = build(req(summary={"outcome": "contained", "intent": "billing_inquiry",
                           "disposition": "resolved", "completion": "completed",
                           "grounded_in": {"outcome": [1], "intent": [1], "disposition": [1], "completion": [1]},
                           "key_points": [{"id": "kp-1", "grounded_in": [1], "token": "[PHONE]"}]}),
              spec, inject=["pii_leak"])
    case("inject-leak: pii_leak>0", r["violations"]["pii_leak"] > 0)
    case("inject-leak: kapı eler", _gate_eval(r, G)[0] is False)

    # 15) K4 summarize_pending — pending kaynaktan özet (PII sızma riski)
    r = build(req(redaction_state="pending"), spec, inject=["summarize_pending"])
    case("inject-summarize-pending: premature_summary>0", r["violations"]["premature_summary"] > 0)
    case("inject-summarize-pending: kapı eler", _gate_eval(r, G)[0] is False)

    # 16) K6 over_capture — içerik yokken özet
    r = build(req(upstream_redaction_decision="NO_CONTENT", redaction_state="not_required"),
              spec, inject=["persist_when_no_content"])
    case("inject-overcapture: over_capture>0", r["violations"]["over_capture"] > 0)
    case("inject-overcapture: kapı eler", _gate_eval(r, G)[0] is False)

    # 17) K7 residency_leak
    r = build(req(), spec, inject=["residency_leak"])
    case("inject-residency: residency_violation>0", r["violations"]["residency_violation"] > 0)
    case("inject-residency: kapı eler", _gate_eval(r, G)[0] is False)
    r = build(req(storage_region="TR"), spec)
    case("residency: storage=home(TR) → ihlal yok", r["violations"]["residency_violation"] == 0)

    # 18) K8 hotpath_exec — hot-path'te yürütme
    r = build(req(), spec, inject=["hotpath_exec"])
    case("inject-hotpath: hotpath_violation>0", r["violations"]["hotpath_violation"] > 0)
    case("inject-hotpath: execution_plane=hot_path", r["execution_plane"] == "hot_path")
    case("inject-hotpath: kapı eler", _gate_eval(r, G)[0] is False)
    r = build(req(execution_plane="hot_path"), spec)
    case("plane=hot_path: hotpath_violation>0", r["violations"]["hotpath_violation"] > 0)

    # 19) K5 failopen_summary — fail-closed terminali sessiz özetlemeye çevirme
    r = build(req(redaction_state="pending"), spec, inject=["failopen_summary"])
    case("inject-failopen: failopen>0", r["violations"]["failopen"] > 0)
    case("inject-failopen: kapı eler", _gate_eval(r, G)[0] is False)

    # 20) K12 cross_tenant
    r = build(req(), spec, inject=["cross_tenant"])
    case("inject-cross-tenant: cross_tenant>0 + BLOCK",
         r["violations"]["cross_tenant"] > 0 and r["terminal"] == "BLOCK")
    r = build(req(bind_tenant="t-other"), spec)
    case("bind-mismatch: cross_tenant>0", r["violations"]["cross_tenant"] > 0)

    # 21) K10 no_audit
    r = build(req(), spec, inject=["no_audit"])
    case("inject-no-audit: missing_audit>0", r["violations"]["missing_audit"] > 0)
    case("inject-no-audit: audit None", r["audit"] is None)

    # 22) K6 GARANTİ — her terminal ∉ {SUMMARIZED} ⇒ no_summary_persisted=true
    for kw in (dict(upstream_redaction_decision="NO_CONTENT", redaction_state="not_required"),
               dict(upstream_redaction_decision="BLOCK", redaction_state="pending"),
               dict(upstream_redaction_decision=None),
               dict(redaction_state="pending"),
               dict(segments=[], summary={"outcome": "abandoned", "intent": "other",
                                          "disposition": "no_action", "completion": "not_completed",
                                          "grounded_in": {}, "key_points": []})):
        rr = build(req(**kw), spec)
        if rr["terminal"] not in SUMMARY_PERSISTED:
            case("K6 garanti: %s → no_summary_persisted=true" % rr["terminal"],
                 rr["no_summary_persisted"] is True)

    # 23) K2 GARANTİ — SUMMARIZED ⇒ grounded=true (ungrounded_claim=0)
    for kw in (dict(), dict(upstream_redaction_decision="NOT_REQUIRED", redaction_state="not_required")):
        rr = build(req(**kw), spec)
        if rr["terminal"] == "SUMMARIZED":
            case("K2 garanti: SUMMARIZED ⇒ grounded (%s)" % rr["grounded"],
                 rr["grounded"] is True and rr["violations"]["ungrounded_claim"] == 0)

    # 24) kanıt (K9) + audit (K10)
    r = build(req(), spec)
    case("evidence: request taşır", r["evidence"]["request_id"] == "req-1")
    case("evidence: upstream/redaction/field_count/grounded taşır",
         all(k in r["evidence"] for k in ("upstream_redaction_decision", "redaction_state",
                                          "field_count", "grounded")))
    case("audit: result/outcome/tenant taşır",
         r["audit"]["result"] == "SUMMARIZED" and r["audit"]["outcome"] == "contained"
         and r["audit"]["tenant_id"] == "t-acme")

    # 25) sızıntı tarayıcı
    case("leak: req-001 kimlik temiz", scan_leaks('{"request_id": "req-001"}') == [])
    case("leak: enum/seq temiz", scan_leaks('{"outcome": "contained", "grounded_in": [1, 2]}') == [])
    case("leak: maskeli token temiz", scan_leaks('{"token": "[PHONE]"}') == [])
    case("leak: summary_text alanı yakalanır", len(scan_leaks('{"summary_text": "x"}')) > 0)
    case("leak: ham uzun rakam (kart/telefon) yakalanır", len(scan_leaks('{"x": "4111111111111111"}')) > 0)

    npass = sum(1 for ok, _ in results if ok)
    for ok, name in results:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print("\nselftest: %d/%d %s" % (npass, len(results), "🟢" if npass == len(results) else "🔴"))
    return 0 if npass == len(results) else 1


# ════════════════════════════════════════════════════════════════════════════
def schema_cmd():
    out = {
        "module": "call-summary (WBS 11.7 — Çağrı özeti üretimi; BRD §8.1 adım 9, FR-ANA-002)",
        "outcomes": OUTCOMES,
        "terminal": sorted(TERMINAL),
        "summary_persisted_terminals": sorted(SUMMARY_PERSISTED),
        "rules": RULES,
        "block_reasons": BLOCK_REASONS,
        "accepted_source_states": sorted(ACCEPTED_SOURCE_STATES),
        "forbidden_source_states": sorted(FORBIDDEN_SOURCE_STATES),
        "required_fields": REQUIRED_FIELDS,
        "vocabulary_fields": VOCAB_FIELDS,
        "decision": "tenant_check ⇒ BLOCK(cross_tenant) → upstream∉{REDACTED,NOT_REQUIRED,NO_CONTENT,BLOCK} "
                    "⇒ BLOCK(no_upstream) → upstream∉{REDACTED,NOT_REQUIRED} ⇒ NO_CONTENT(no_summary) → "
                    "redaction_state=pending ⇒ BLOCK(premature_summary) → plane!=analytics_async ⇒ "
                    "hotpath_violation → 0 segment ⇒ NO_SUMMARY → vocab(outcome/disposition/completion/intent) "
                    "dışı/eksik ⇒ BLOCK(invalid_summary_field) → ground_all_fields(grounded_in ⊆ seq) → "
                    "completeness(ungrounded_claim=0) → no_leak(pii_leak=0) → residency(home_region) ⇒ SUMMARIZED",
        "default": "BLOCK (fail-closed)",
        "fail_safe": "terminal ∉ {SUMMARIZED} ⇒ no_summary_persisted=true ∧ summary_persisted=false (FR-REC-002 aşağı akış)",
        "core_guarantees": [
            "K2 dayanak/sadakat: her özet alanı + anahtar-nokta grounded_in ⊆ transkript seq (ungrounded_claim=0; BRD §8.1/FR-ANA-002)",
            "K3 kapalı sözlük: outcome/disposition/completion/intent kapalı sözlükten; sözlük-dışı ⇒ BLOCK (invalid_field=0)",
            "K4 PII-güvenli kaynak: özet YALNIZ redacted/not_required'tan; pending ⇒ BLOCK premature_summary; ham PII özette yok (pii_leak=0)",
            "K5 SUMMARIZED ⇒ ungrounded_claim=0 (false_grounding=0); özet atlanamaz (summary_skip=0)",
            "K6 upstream ∉ {REDACTED,NOT_REQUIRED} ⇒ no_summary_persisted=true (over_capture=0)",
            "K8 execution_plane=analytics_async (hotpath_violation=0; FR-RES-011)",
        ],
        "request_fields": ["name", "request_id", "tenant_id", "correlation_id", "call_id",
                           "direction(inbound|outbound)",
                           "upstream_redaction_decision(REDACTED|NOT_REQUIRED|NO_CONTENT|BLOCK)",
                           "redaction_state(redacted|not_required|pending)",
                           "execution_plane(analytics_async|hot_path)",
                           "segments[{seq, speaker}]",
                           "summary{outcome, intent, disposition, completion, grounded_in{field:[seq]}, key_points[{id, grounded_in[seq], token?}]}",
                           "in_region_storage_required(bool)", "storage_region", "home_region",
                           "bind_tenant", "config_override{}", "inject[]", "expect", "expected{}"],
        "injections (degrade testi)": sorted(INJECTIONS),
        "decision_fields": ["terminal", "plan{outcome,intent,disposition,completion,key_points}",
                            "summary_persisted", "upstream_redaction_decision", "redaction_state",
                            "field_count", "key_point_count", "grounded", "content_present",
                            "no_summary_persisted", "storage_region", "home_region", "block_reason",
                            "execution_plane", "evidence", "audit"],
        "violations": VIOLATION_KEYS,
        "invariants": INVARIANT_IDS,
        "consumes": "11.4 pii-redaction (REDACTED/NOT_REQUIRED + redaction_state=redacted/not_required + "
                    "access_ready) + 11.3 transcript-build (segment seq) + LLM özetleyici (aday özet "
                    "{outcome,intent,disposition,completion,grounded_in,key_points}; serbest prose KAPALI-"
                    "sözlüğe + dayanağa BAĞLANIR)",
        "consumed_by": "SAD §10.2 Transcript Store + DB §21 transcript.summary (özet PROSE byte üretimi) + "
                       "DB §19 call.outcome + FR-ANA-002/003 (outcome/disposition/completion) + FR-ANA "
                       "QA/analitik + 11.6 (erişim audit/görüntüleme; access_ready) + L2 A-12 panel",
        "trace": "BRD §8.1 (adım 9), FR-ANA-002/003, SR-ANA-002, TC-ANA-002, FR-OUT-011 (disposition), "
                 "FR-REC-004/SR-REC-004 (PII-güvenli kaynak aşağı akış), FR-REC-002/SR-REC-002 (no content "
                 "aşağı akış), FR-REC-008/009 (11.6), FR-RES-011 (async), FR-TEN-002, FR-IAM-006, NFR 10.7, "
                 "BRD §8.1/§9.15/§17.7/§15, SAD §10.1/§10.2/§19.2, DB §21 transcript.summary, DB §19 "
                 "call.outcome, ADR-001/002/004/007/012",
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
            print("kullanım: call_summary_probe.py check <sample.json|dizin>")
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
