#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 11.2 — Tek/çift kanallı kayıt (channel-recording) referans probe.

11. workstream'in (Kayıt, Transkript & PII Redaction) KANAL-YERLEŞİMİ (channel-recording) modülü ve
F1-Must temel yeteneği. FR-REC-003 ('Tek veya çift kanallı kayıt desteklenmelidir') + SR-REC-003 (yöntem
I — kabul: 'Seçilen kanal modu üretilir') + TC-REC-003 + DB §22 recording.channels CHECK IN (1,2) + SAD
§10.2 Recording Pipeline'ı sahiplenir. 11.1 (recording-policy) RECORD kararını + channels attribute'unu
ÜRETTİKTEN SONRA çalışır; bu modül onun AŞAĞI AKIŞ TÜKETİCİSİDİR. Bir DETERMİNİSTİK FAIL-CLOSED motordur:

  ChannelRecordingRequest ─11.1 yetki doğrula─► channels {1,2} doğrula ─► layout çöz ─► bacak→kanal bağla
        │                       │                       │                     │              │
        │   authorized = (upstream_decision==RECORD ∧ ¬upstream_no_media_captured)            │
        │                       │                       │                     │              │
        │      ├─ cross-tenant ──────────────────────────────────────────────► BLOCK (cross_tenant)
        │      ├─ yetkisiz (11.1 RECORD değil) ──────────────────────────────► NO_RECORD (no media)
        │      ├─ channels ∉ {1,2} ──────────────────────────────────────────► BLOCK (invalid_channel_count)
        │      ├─ channels=1 ────────────────────────────────────────────────► MONO (1 track, tüm bacak)
        │      └─ channels=2 ────────────────────────────────────────────────► DUAL (caller↔agent ayrı)

ÇEKİRDEK INVARIANT'lar: K2 kanal modu üretimi (channels∈{1,2} → track sayısı==channels; FR-REC-003), K3
DUAL ayrışma (caller→ch0 ∧ agent/human→ch1 ayrı; karıştırma/yanlış-bağlama/boş-kanal yok), K4 MONO tamlık
(present TÜM bacak tek track'e downmix; bacak düşmez), K5 yalnız-yetkiliyken-kayıt (upstream≠RECORD ⇒
no_media_captured=true; FR-REC-002/SR-REC-002 aşağı akış koruması — over_capture yasak), K6 residency
(home-region), K7 fail-closed geçersiz kanal (sessiz varsayılan kayıt yok), K8 ATLANAMAZ (bypass=
layout_skip=BRD §15 alarmı). Her karar deterministik+terminal (K1) + kanıt (K9) + audit (K10); metrik
düşük-kardinalite + PII yok (K11); sır/PII yok + tenant izolasyonu (K12).

Kapsam dışı (bilinçli, başka modül SAHİBİ): kayıt-başlatma KARARI + channels ÜRETİMİ + consent + tamamen
kapatma → 11.1 (FR-REC-001/002; TÜKETİLİR); kayıt BYTE yazımı/codec/depolama/KMS → SAD §10.2 + DB §8
(layout KARARI verilir, medya YAZILMAZ); transkript → 11.3; PII redaction → 11.4 (FR-REC-004);
kart/parola/OTP → 11.5; erişim audit → 11.6 (FR-REC-009); retention → FR-REC-006; residency UYGULAMASI →
DB §8/SAD §12.1; audit store → 7.1.6/12.x.

Kullanım:
  channel_recording_probe.py validate          Statik spec/config/kapsama kapısı → çıkış kodu
  channel_recording_probe.py check <sample>     Kanal-yerleşimi motoru: senaryo(lar)ı çalıştır → kapı (K1–K12)
  channel_recording_probe.py selftest           Gömülü davranış kontrolleri → çıkış kodu
  channel_recording_probe.py schema             Karar sözleşmesini yazdır

Determinizm: layout çözümü + bacak→kanal bağlama; Date.now/random YOK. Stdlib-only. Sır/credential ve
gerçek PII (müşteri adı/telefon/ham ses) üretilmez/yazılmaz (fixture sentetik — FR-TST-008).
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "channel-recording-spec.json")
CONFIG_PATH = os.path.join(HERE, "config", "channel-recording.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

OUTCOMES = ["MONO", "DUAL", "NO_RECORD", "BLOCK"]
TERMINAL = {"MONO", "DUAL", "NO_RECORD", "BLOCK"}
RECORDED = {"MONO", "DUAL"}
RULES = ["record_only_when_authorized", "channel_count_honored", "dual_separation",
         "mono_completeness", "residency_honored"]
BLOCK_REASONS = ["invalid_channel_count", "cross_tenant", "no_upstream"]
INVARIANT_IDS = ["K1", "K2", "K3", "K4", "K5", "K6", "K7", "K8", "K9", "K10", "K11", "K12"]
VALID_CHANNELS = [1, 2]
UPSTREAM_DECISIONS = {"RECORD", "DISABLED", "NO_CONSENT", "BLOCK"}

# Degrade (inject) — DOĞRU fail-closed/kanal-ayrışma davranışını bozan müdahaleler.
INJECTIONS = {"skip_layout", "record_when_not_authorized", "mix_in_dual", "wrong_channel_binding",
              "drop_leg_in_mono", "empty_channel", "invalid_channel_count", "failopen_layout",
              "residency_leak", "cross_tenant", "no_audit"}

VIOLATION_KEYS = [
    "layout_skip", "invalid_layout", "dual_not_separated", "binding_error", "leg_dropped",
    "empty_channel", "over_capture", "residency_violation", "failopen", "cross_tenant",
    "missing_evidence", "missing_audit", "stuck_state", "secret_or_pii",
]

# ── Sızıntı tarayıcı (K12; 11.1/10.2.x deseniyle) — müşteri adı/telefon/hesap no/OTP/ham ses yasak ──
LEAK_PATTERNS = [
    ("phone_e164", re.compile(r"\+(?!1632)\d{9,15}\b")),
    ("phone_long", re.compile(r"\b\d{9,15}\b")),
    ("secret_kw", re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|token|bearer|credential)\b\s*[:=]\s*\S")),
    ("privkey", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("pii_field", re.compile(r"(?i)\"(customer_name|customer_phone_value|account_number_value|transcript_text|raw_audio|otp_code_value|password_value|raw_value|raw_msisdn)\"\s*:")),
]
# Yapısal kimlik/enum/sayı beyaz-listelenir.
LEAK_ALLOW = re.compile(r"(?i)(555-?01\d\d|\+1632|ITU|reserved|test|example|req-|call-|camp-|t-|corr-|prefix|masked|last4|\d{4}-\d{2}-\d{2})")


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def scan_leaks(text):
    """Ham PII / sır tarayıcı. Yorum/tarif satırı eler (11.x deseni)."""
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
    """Config = ana channel-recording.json; sample.config_override yapısal alanları geçersiz kılar."""
    cfg = _load(CONFIG_PATH)
    ov = sample.get("config_override", {}) or {}
    for k in ("channel_side", "valid_channels", "layouts"):
        if k in ov:
            if isinstance(ov[k], dict) and isinstance(cfg.get(k), dict):
                cfg.setdefault(k, {}).update(ov[k])
            else:
                cfg[k] = ov[k]
    return cfg


def _build_tracks(mode, present_legs, channel_side, inject, v):
    """Kanal yerleşimini kur ve bacakları kanallara bağla; bağlama ihlallerini say.

    MONO: tüm present bacak tek track (ch0). DUAL: caller→ch0, agent/human→ch1 (channel_side).
    inject (degrade) doğru bağlamayı bozar ve eşleşen ihlali artırır."""
    if mode == "MONO":
        track_legs = list(present_legs)
        if "drop_leg_in_mono" in inject and len(track_legs) > 1:
            track_legs = track_legs[:-1]            # bir bacağı düşür → konuşmanın yarısı kaybolur
        tracks = [{"channel": 0, "legs": track_legs}]
        # ── K4 tamlık: present TÜM bacak tek track'te ──
        if set(track_legs) != set(present_legs):
            v["leg_dropped"] += 1
        if present_legs and not track_legs:
            v["empty_channel"] += 1
        return tracks

    # ── DUAL ──
    side = dict(channel_side)
    if "wrong_channel_binding" in inject:
        side = {k: (1 - sv) for k, sv in channel_side.items()}   # ch0↔ch1 takas
    if "mix_in_dual" in inject:
        ch0 = list(present_legs)                    # iki konuşmacıyı tek kanala karıştır
        ch1 = []
    elif "empty_channel" in inject:
        ch0 = [l for l in present_legs if channel_side.get(l) == 0]
        ch1 = []                                    # ch1 tahsis ama bacak bağlanmadı → sessiz kanal
    else:
        ch0 = [l for l in present_legs if side.get(l, 0) == 0]
        ch1 = [l for l in present_legs if side.get(l, 1) == 1]
    tracks = [{"channel": 0, "legs": ch0}, {"channel": 1, "legs": ch1}]

    # ── K3 bağlama doğruluğu: bacak KANONİK kanalına bağlanmalı (caller=0, agent/human=1) ──
    for leg in present_legs:
        expected = channel_side.get(leg)
        placed = 0 if leg in ch0 else (1 if leg in ch1 else None)
        if expected is not None and placed is not None and placed != expected:
            v["binding_error"] += 1
    # ── K3 ayrışma: bir kanal iki KONUŞMACI TARAFINI karıştıramaz ──
    if {channel_side.get(l) for l in ch0} >= {0, 1}:
        v["dual_not_separated"] += 1
    if {channel_side.get(l) for l in ch1} >= {0, 1}:
        v["dual_not_separated"] += 1
    # ── present bacak hiçbir kanala bağlanmadı → bacak kaybı ──
    if set(ch0) | set(ch1) != set(present_legs):
        v["leg_dropped"] += 1
    # ── K3 boş kanal: tarafı present ama kanal boş ──
    if not ch0 and any(channel_side.get(l) == 0 for l in present_legs):
        v["empty_channel"] += 1
    if not ch1 and any(channel_side.get(l) == 1 for l in present_legs):
        v["empty_channel"] += 1
    return tracks


def build(sample, spec, inject=None, cfg=None):
    """Tek kanal-yerleşimi senaryosunu yürüt → ChannelRecordingDecision + ihlal sayaçları.

    Motor DOĞRU fail-closed / kanal-ayrışma davranışını hesaplar; inject (degrade) doğru davranışı bozar
    ve eşleşen ihlal sayacını artırır (11.1/10.2.x inject deseniyle birebir)."""
    inject = set(inject if inject is not None else sample.get("inject", []))
    cfg = cfg if cfg is not None else _config(sample)

    tenant = sample.get("tenant_id")
    call_id = sample.get("call_id")
    request_id = sample.get("request_id")
    correlation_id = sample.get("correlation_id")
    direction = sample.get("direction")
    upstream = sample.get("upstream_decision")               # 11.1: RECORD/DISABLED/NO_CONSENT/BLOCK
    upstream_no_media = bool(sample.get("upstream_no_media_captured", upstream != "RECORD"))
    channels = sample.get("channels")                        # 1 / 2 (11.1 channels attribute)
    present_legs = list(sample.get("media_legs", []))
    storage_region = sample.get("storage_region")
    home_region = sample.get("home_region")
    in_region = bool(sample.get("in_region_storage_required", False))

    channel_side = cfg.get("channel_side", {})
    valid_channels = cfg.get("valid_channels", VALID_CHANNELS)

    v = {k: 0 for k in VIOLATION_KEYS}

    mode = None
    tracks = None
    no_media_captured = True             # privacy-safe varsayılan: medya yok
    recording_written = False
    block_reason = None
    authorized = None

    # ── K12 (tenant izolasyonu): kayıt oturumu yalnız aynı tenant'a bağlanır ──
    if "cross_tenant" in inject:
        v["cross_tenant"] += 1
    if sample.get("bind_tenant") and sample.get("bind_tenant") != tenant:
        v["cross_tenant"] += 1

    # ── K8 (fail-closed / ATLANAMAZ): bypass → layout çözmeden kayıt → layout_skip ──
    if "skip_layout" in inject:
        v["layout_skip"] += 1
        mode = "MONO"
        recording_written = True
        no_media_captured = False        # layout çözülmeden kayıt = over-capture
        tracks = [{"channel": 0, "legs": present_legs}]
        terminal = "MONO"
        evidence = _evidence(request_id, upstream, None, None, mode, tracks, no_media_captured,
                             recording_written, storage_region, home_region, direction, None)
        if not request_id:
            v["missing_evidence"] += 1
        audit = None if "no_audit" in inject else _audit(terminal, request_id, call_id, direction,
                                                         None, mode, recording_written, no_media_captured,
                                                         correlation_id, tenant)
        if "no_audit" in inject:
            v["missing_audit"] += 1
        return _pack(sample, terminal, v, mode, channels, tracks, authorized, no_media_captured,
                     recording_written, storage_region, home_region, block_reason, evidence, audit)

    # ── invalid_channel_count inject: kanal sayısını geçersiz kıl ──
    if "invalid_channel_count" in inject:
        channels = 3

    # cross-tenant fail-closed BLOCK
    if v["cross_tenant"] > 0:
        block_reason = "cross_tenant"

    # ── upstream (11.1 kararı) yok/geçersiz → fail-closed BLOCK no_upstream ──
    if block_reason is None and upstream not in UPSTREAM_DECISIONS:
        block_reason = "no_upstream"

    if block_reason is not None:
        terminal = "BLOCK"
        no_media_captured = True
        recording_written = False
    else:
        # ── K5 (FR-REC-002/SR-REC-002 aşağı akış): yalnız 11.1 RECORD dediğinde kayıt ──
        authorized = (upstream == "RECORD") and (not upstream_no_media)
        if not authorized:
            terminal = "NO_RECORD"
            no_media_captured = True
            recording_written = False
            if "record_when_not_authorized" in inject:
                recording_written = True
                no_media_captured = False        # yetkisizken kayıt = over_capture
                v["over_capture"] += 1
                tracks = [{"channel": 0, "legs": present_legs}]
        else:
            # ── K2/K7: channels {1,2} doğrula ──
            if channels not in valid_channels:
                if "failopen_layout" in inject:
                    v["failopen"] += 1               # geçersiz kanalda sessiz varsayılan kayıt = K7 fail-open
                    mode = "MONO"
                    channels = 1
                    tracks = _build_tracks("MONO", present_legs, channel_side, inject, v)
                    recording_written = True
                    no_media_captured = False
                    terminal = "MONO"
                else:
                    block_reason = "invalid_channel_count"
                    terminal = "BLOCK"
                    no_media_captured = True
                    if "invalid_channel_count" in inject:
                        v["invalid_layout"] += 1     # geçersiz kanalda kayıt = invalid_layout
                        recording_written = True
                        no_media_captured = False
                        tracks = [{"channel": 0, "legs": present_legs}]
            else:
                # ── K2 layout çöz: channels=1 ⇒ MONO/1 track, channels=2 ⇒ DUAL/2 track ──
                mode = "MONO" if channels == 1 else "DUAL"
                tracks = _build_tracks(mode, present_legs, channel_side, inject, v)
                recording_written = True
                no_media_captured = False
                terminal = mode
                # ── K2 track sayısı == channels ──
                if len(tracks) != channels:
                    v["invalid_layout"] += 1
                # ── K6 residency: in_region ise storage_region == home_region ──
                if "residency_leak" in inject:
                    storage_region = (home_region or "EU") + "-ALT"     # home-region dışına çıkar
                if in_region and storage_region is not None and storage_region != home_region:
                    v["residency_violation"] += 1

    if block_reason is not None and terminal != "BLOCK":
        terminal = "BLOCK"

    # ── K5 ÇEKİRDEK GARANTİ: terminal ∉ {MONO,DUAL} ⇒ no_media_captured = true ──
    if terminal not in RECORDED and not no_media_captured:
        v["over_capture"] += 1

    # ── K1 stuck state ──
    if terminal not in TERMINAL:
        v["stuck_state"] += 1

    # ── Kanıt (K9) ──
    evidence = _evidence(request_id, upstream, authorized, channels, mode, tracks, no_media_captured,
                         recording_written, storage_region, home_region, direction, block_reason)
    if (not request_id) or (terminal is None):
        v["missing_evidence"] += 1

    # ── Audit (K10) ── (ham PII YOK — yalnız yapısal kimlik/enum/sayı)
    audit = None
    if "no_audit" in inject:
        v["missing_audit"] += 1
    else:
        audit = _audit(terminal, request_id, call_id, direction, channels, mode, recording_written,
                       no_media_captured, correlation_id, tenant)

    return _pack(sample, terminal, v, mode, channels, tracks, authorized, no_media_captured,
                 recording_written, storage_region, home_region, block_reason, evidence, audit)


def _evidence(request_id, upstream, authorized, channels, mode, tracks, no_media_captured,
              recording_written, storage_region, home_region, direction, block_reason):
    return {
        "request_id": request_id,
        "upstream_decision": upstream,
        "authorized": authorized,
        "channels": channels,
        "mode": mode,
        "tracks": tracks,
        "no_media_captured": no_media_captured,
        "recording_written": recording_written,
        "storage_region": storage_region,
        "home_region": home_region,
        "direction": direction,
        "block_reason": block_reason,
    }


def _audit(terminal, request_id, call_id, direction, channels, mode, recording_written,
           no_media_captured, correlation_id, tenant):
    return {
        "result": terminal,
        "request_id": request_id,
        "call_id": call_id,
        "direction": direction,
        "channels": channels,
        "mode": mode,
        "recording_written": recording_written,
        "no_media_captured": no_media_captured,
        "correlation_id": correlation_id,
        "tenant_id": tenant,
    }


def _pack(sample, terminal, v, mode, channels, tracks, authorized, no_media_captured,
          recording_written, storage_region, home_region, block_reason, evidence, audit):
    return {
        "name": sample.get("name"),
        "terminal": terminal,
        "resolved": terminal in TERMINAL,
        "mode": mode,
        "channels": channels,
        "tracks": tracks,
        "track_count": len(tracks) if tracks else 0,
        "authorized": authorized,
        "recording_written": recording_written,
        "no_media_captured": no_media_captured,
        "storage_region": storage_region,
        "home_region": home_region,
        "block_reason": block_reason,
        "evidence": evidence,
        "audit": audit,
        "violations": v,
    }


def _gate_eval(result, gates):
    """Tek senaryo sonucunu HARD kapılara vur → (passed, fail_list)."""
    v = result["violations"]
    fails = []
    mapping = {
        "layout_skip": "max_layout_skip",
        "invalid_layout": "max_invalid_layout",
        "dual_not_separated": "max_dual_not_separated",
        "binding_error": "max_binding_error",
        "leg_dropped": "max_leg_dropped",
        "empty_channel": "max_empty_channel",
        "over_capture": "max_over_capture",
        "residency_violation": "max_residency_violation",
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
        for key in ("terminal", "block_reason", "mode", "channels", "track_count",
                    "recording_written", "no_media_captured"):
            if key in exp_assert and exp_assert[key] != res.get(key):
                mism.append("%s: beklenen=%r gerçek=%r" % (key, exp_assert[key], res.get(key)))

        verdict_ok = (passed and not mism) if expect == "pass" else (not passed)
        all_ok = all_ok and verdict_ok
        icon = "🟢" if verdict_ok else "🔴"
        print("%s %s" % (icon, os.path.basename(p)))
        print("   terminal=%s mode=%s channels=%s tracks=%s reason=%s recording_written=%s no_media=%s"
              % (res["terminal"], res["mode"], res["channels"], res["track_count"],
                 res["block_reason"], res["recording_written"], res["no_media_captured"]))
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
              "block_reasons", "outcomes", "layouts", "authorization", "gates",
              "observability", "invariants", "no_secrets"):
        chk("spec.%s var" % f, f in spec)
    chk("wbs=11.2", spec.get("wbs") == "11.2")
    chk("phase=F1", spec.get("phase") == "F1")
    chk("priority=Must", spec.get("priority") == "Must")
    chk("placement fail_closed=true", spec.get("placement", {}).get("fail_closed") is True)

    # 2) İzlenebilirlik
    tr = spec.get("trace", {})
    chk("FR-REC-003 izlenir (tek/çift kanal)", "FR-REC-003" in tr.get("fr", []))
    chk("FR-REC-002 izlenir (tamamen kapatma aşağı akış)", "FR-REC-002" in tr.get("fr", []))
    chk("FR-REC-001 izlenir (11.1 RECORD kararı)", "FR-REC-001" in tr.get("fr", []))
    chk("FR-REC-004 izlenir (PII metrikte yok)", "FR-REC-004" in tr.get("fr", []))
    chk("FR-IAM-006 izlenir (audit)", "FR-IAM-006" in tr.get("fr", []))
    chk("FR-TEN-002 izlenir (tenant izolasyonu)", "FR-TEN-002" in tr.get("fr", []))
    chk("SR-REC-003 izlenir", "SR-REC-003" in tr.get("srs", []))
    chk("SR-REC-002 izlenir (no media aşağı akış)", "SR-REC-002" in tr.get("srs", []))
    chk("TC-REC-003 izlenir", "TC-REC-003" in tr.get("rtm", []))
    chk("NFR 10.7 izlenir (residency)", "NFR 10.7" in tr.get("nfr", []))
    chk("ADR-001/002/012 izlenir",
        any("ADR-001" in a for a in tr.get("adr", []))
        and any("ADR-002" in a for a in tr.get("adr", []))
        and any("ADR-012" in a for a in tr.get("adr", [])))
    chk("SAD §10.2 Recording Pipeline izlenir", any("§10.2" in s for s in tr.get("sad", [])))
    chk("DB §22 recording.channels izlenir", any("§22" in d for d in tr.get("db", [])))
    chk("BRD §9.14 FR-REC izlenir", any("§9.14" in s for s in tr.get("brd", [])))
    chk("BRD §15 gizlilik alarmı izlenir", any("§15" in s for s in tr.get("brd", [])))
    chk("11.1 recording-policy consumes (channels)", any("11.1" in c for c in tr.get("consumes", [])))

    # 3) Beş kural (FR-REC-003 çekirdek)
    rz = spec["rules"]
    rule_ids = [d["id"] for d in rz.get("list", [])]
    chk("beş kural tam (authorize/channel-count/dual-sep/mono-complete/residency)", set(rule_ids) == set(RULES))
    chk("değerlendirme authorize_then_validate_channels_then_resolve_layout_then_bind_legs_fail_closed_no_record",
        rz.get("evaluation") == "authorize_then_validate_channels_then_resolve_layout_then_bind_legs_fail_closed_no_record")
    for d in rz.get("list", []):
        chk("kural %s invariant taşır" % d["id"], d.get("invariant") in INVARIANT_IDS)

    # 4) Karar
    dec = spec["decision"]
    chk("karar default=BLOCK (fail-closed)", dec.get("default") == "BLOCK")
    chk("fail_safe_terminal no_record", "no_record" in dec.get("fail_safe_terminal", ""))

    # 5) Sonuçlar + block_reason taksonomisi
    oc = spec["outcomes"]
    chk("terminal sonuçlar MONO/DUAL/NO_RECORD/BLOCK", set(oc.get("list", [])) == set(OUTCOMES))
    br = set(spec["block_reasons"].get("list", []))
    chk("block_reason taksonomisi tam (invalid_channel_count/cross_tenant/no_upstream)", br == set(BLOCK_REASONS))

    # 5b) Layouts — mono/dual + valid_channels + channel_side
    ly = spec["layouts"]
    chk("layout mono channels=1 (1 track)", ly.get("mono", {}).get("channels") == 1 and ly.get("mono", {}).get("tracks") == 1)
    chk("layout dual channels=2 (2 track)", ly.get("dual", {}).get("channels") == 2 and ly.get("dual", {}).get("tracks") == 2)
    chk("layout dual caller→ch0", ly.get("dual", {}).get("ch0") == ["caller"])
    chk("layout dual agent/human→ch1", ly.get("dual", {}).get("ch1") == ["agent", "human"])
    chk("layout valid_channels {1,2}", set(ly.get("valid_channels", [])) == set(VALID_CHANNELS))

    # 6) Yetki — recording:policy:manage, per-call otomatik gate
    az = spec["authorization"]
    chk("policy_permission=recording:policy:manage", az.get("policy_permission") == "recording:policy:manage")
    chk("per_call_check otomatik gate", "automatic_gate" in az.get("per_call_check", ""))
    chk("karar backend'de", az.get("decision_at") == "backend")

    # 7) Kapılar — tüm sıfır-eşik ihlal kapıları
    g = spec["gates"]
    for gk in ("max_layout_skip", "max_invalid_layout", "max_dual_not_separated", "max_binding_error",
               "max_leg_dropped", "max_empty_channel", "max_over_capture", "max_residency_violation",
               "max_failopen", "max_cross_tenant", "max_missing_evidence", "max_missing_audit",
               "max_stuck_state", "max_secret_or_pii"):
        chk("kapı %s=0" % gk, g.get(gk) == 0)
    chk("require_terminal", g.get("require_terminal") is True)
    chk("require_decision_record", g.get("require_decision_record") is True)

    # 8) Gözlemlenebilirlik — kardinalite disiplini (0.4.7)
    obs = spec["observability"]
    chk("channel_recording_decision_total metrik", "channel_recording_decision_total" in obs.get("metrics", []))
    chk("channel_recording_norecord_total metrik (FR-REC-002 aşağı akış)",
        "channel_recording_norecord_total" in obs.get("metrics", []))
    chk("channel_recording_privacy_violation_total metrik (K3/K4/K5/K8 alarm)",
        "channel_recording_privacy_violation_total" in obs.get("metrics", []))
    hi = set(obs.get("high_cardinality_trace_only", []))
    lo = set(obs.get("low_cardinality_labels", []))
    chk("request_id/call_id YÜKSEK kard (label değil)",
        "request_id" in hi and "call_id" in hi and "call_id" not in lo)
    chk("mode/direction DÜŞÜK kard (label uygun)", "mode" in lo and "direction" in lo)
    chk("alarm over_capture/dual_not_separated ≤2dk",
        "over_capture" in obs.get("alarm", "") or "dual_not_separated" in obs.get("alarm", ""))

    # 9) İnvariant'lar K1–K12
    inv_ids = [i["id"] for i in spec["invariants"]]
    chk("invariant'lar K1–K12 tam", inv_ids == INVARIANT_IDS)

    # 10) Config dosyası
    cfg_ok = os.path.exists(CONFIG_PATH)
    chk("config/channel-recording.json var", cfg_ok)
    if cfg_ok:
        cfg = _load(CONFIG_PATH)
        cs = cfg.get("channel_side", {})
        chk("config channel_side caller=0", cs.get("caller") == 0)
        chk("config channel_side agent=1 ∧ human=1", cs.get("agent") == 1 and cs.get("human") == 1)
        chk("config valid_channels {1,2}", set(cfg.get("valid_channels", [])) == set(VALID_CHANNELS))
        chk("config layouts mono+dual", "mono" in cfg.get("layouts", {}) and "dual" in cfg.get("layouts", {}))
        chk("config mono 1 track / dual 2 track",
            len(cfg["layouts"]["mono"]["tracks"]) == 1 and len(cfg["layouts"]["dual"]["tracks"]) == 2)

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
    chk("hiç müşteri-PII/telefon/hesap-no/ham-ses/sır sızıntısı yok (K12)", total_leaks == 0)

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
        # Varsayılan: 11.1 RECORD + channels=2 (DUAL) + caller+agent bacak; storage=home(TR) → DUAL.
        d = {
            "request_id": "req-1", "tenant_id": "t-acme", "correlation_id": "corr-1",
            "call_id": "call-1", "direction": "inbound", "upstream_decision": "RECORD",
            "upstream_no_media_captured": False, "channels": 2,
            "media_legs": ["caller", "agent"], "in_region_storage_required": True,
            "storage_region": "TR", "home_region": "TR",
        }
        d.update(kw)
        return d

    # 1) happy — RECORD + channels=2 → DUAL (caller↔agent ayrı)
    r = build(req(), spec)
    case("happy: DUAL", r["terminal"] == "DUAL")
    case("happy: mode=DUAL", r["mode"] == "DUAL")
    case("happy: track sayısı=2", r["track_count"] == 2)
    case("happy: recording_written=true", r["recording_written"] is True)
    case("happy: no_media_captured=false (kayıt var)", r["no_media_captured"] is False)
    case("happy: ch0=caller", r["tracks"][0]["legs"] == ["caller"])
    case("happy: ch1=agent", r["tracks"][1]["legs"] == ["agent"])
    case("happy: ihlal yok", all(x == 0 for x in r["violations"].values()))
    case("happy: audit DUAL (K10)", r["audit"] is not None and r["audit"]["result"] == "DUAL")
    case("happy: kapı geçer", _gate_eval(r, G)[0] is True)

    # 2) determinizm
    r1, r2 = build(req(), spec), build(req(), spec)
    case("determinizm: birebir", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))

    # 3) K2 MONO — channels=1 → MONO (tek track, tüm bacak)
    r = build(req(channels=1), spec)
    case("mono: MONO", r["terminal"] == "MONO")
    case("mono: track sayısı=1", r["track_count"] == 1)
    case("mono: tek track tüm bacak", set(r["tracks"][0]["legs"]) == {"caller", "agent"})
    case("mono: ihlal yok", all(x == 0 for x in r["violations"].values()))
    case("mono: kapı geçer", _gate_eval(r, G)[0] is True)

    # 3b) K4 MONO — üç bacak (caller+agent+human) tek track'e
    r = build(req(channels=1, media_legs=["caller", "agent", "human"]), spec)
    case("mono-3leg: tüm üç bacak tek track", set(r["tracks"][0]["legs"]) == {"caller", "agent", "human"})
    case("mono-3leg: leg_dropped=0", r["violations"]["leg_dropped"] == 0)

    # 3c) K3 DUAL — human bacağı agent tarafına (ch1)
    r = build(req(channels=2, media_legs=["caller", "agent", "human"]), spec)
    case("dual-human: ch1=agent+human", set(r["tracks"][1]["legs"]) == {"agent", "human"})
    case("dual-human: ch0=caller", r["tracks"][0]["legs"] == ["caller"])
    case("dual-human: ihlal yok", all(x == 0 for x in r["violations"].values()))

    # 4) K5 — 11.1 DISABLED → NO_RECORD (no media)
    r = build(req(upstream_decision="DISABLED", upstream_no_media_captured=True), spec)
    case("upstream-disabled: NO_RECORD", r["terminal"] == "NO_RECORD")
    case("upstream-disabled: no_media_captured=true", r["no_media_captured"] is True)
    case("upstream-disabled: recording_written=false", r["recording_written"] is False)
    case("upstream-disabled: kapı geçer (gizlilik-güvenli)", _gate_eval(r, G)[0] is True)

    # 4b) K5 — 11.1 NO_CONSENT / BLOCK → NO_RECORD
    for up in ("NO_CONSENT", "BLOCK"):
        rr = build(req(upstream_decision=up, upstream_no_media_captured=True), spec)
        case("upstream-%s: NO_RECORD + no media" % up,
             rr["terminal"] == "NO_RECORD" and rr["no_media_captured"] is True)

    # 5) K2/K7 — channels=3 (geçersiz) → BLOCK invalid_channel_count (no media)
    r = build(req(channels=3), spec)
    case("invalid-channels: BLOCK invalid_channel_count",
         r["terminal"] == "BLOCK" and r["block_reason"] == "invalid_channel_count")
    case("invalid-channels: no_media_captured=true", r["no_media_captured"] is True)
    case("invalid-channels: kapı geçer (fail-closed)", _gate_eval(r, G)[0] is True)

    # 6) no_upstream — upstream alanı yok → BLOCK no_upstream
    r = build(req(upstream_decision=None), spec)
    case("no-upstream: BLOCK no_upstream", r["terminal"] == "BLOCK" and r["block_reason"] == "no_upstream")
    case("no-upstream: no media", r["no_media_captured"] is True)

    # 7) K8 skip_layout — bypass: layout çözmeden kayıt
    r = build(req(), spec, inject=["skip_layout"])
    case("inject-skip: layout_skip>0", r["violations"]["layout_skip"] > 0)
    case("inject-skip: no_media_captured=false (over-capture)", r["no_media_captured"] is False)
    case("inject-skip: kapı eler", _gate_eval(r, G)[0] is False)

    # 8) K5 record_when_not_authorized — 11.1 DISABLED ama kayıt yazılır
    r = build(req(upstream_decision="DISABLED", upstream_no_media_captured=True), spec,
              inject=["record_when_not_authorized"])
    case("inject-overcapture: over_capture>0", r["violations"]["over_capture"] > 0)
    case("inject-overcapture: no_media_captured=false", r["no_media_captured"] is False)
    case("inject-overcapture: kapı eler", _gate_eval(r, G)[0] is False)

    # 9) K3 mix_in_dual — iki konuşmacı tek kanala
    r = build(req(channels=2), spec, inject=["mix_in_dual"])
    case("inject-mix: dual_not_separated>0", r["violations"]["dual_not_separated"] > 0)
    case("inject-mix: kapı eler", _gate_eval(r, G)[0] is False)

    # 10) K3 wrong_channel_binding — caller↔agent kanal takası
    r = build(req(channels=2), spec, inject=["wrong_channel_binding"])
    case("inject-binding: binding_error>0", r["violations"]["binding_error"] > 0)
    case("inject-binding: kapı eler", _gate_eval(r, G)[0] is False)

    # 11) K4 drop_leg_in_mono — tek kanalda bir bacak düşer
    r = build(req(channels=1, media_legs=["caller", "agent"]), spec, inject=["drop_leg_in_mono"])
    case("inject-droplet: leg_dropped>0", r["violations"]["leg_dropped"] > 0)
    case("inject-droplet: kapı eler", _gate_eval(r, G)[0] is False)

    # 12) K3 empty_channel — DUAL'da ch1 boş (agent bağlanmadı)
    r = build(req(channels=2, media_legs=["caller", "agent"]), spec, inject=["empty_channel"])
    case("inject-empty: empty_channel>0", r["violations"]["empty_channel"] > 0)
    case("inject-empty: kapı eler", _gate_eval(r, G)[0] is False)

    # 13) K7 failopen_layout — geçersiz kanalda sessiz varsayılan kayıt
    r = build(req(channels=3), spec, inject=["failopen_layout"])
    case("inject-failopen: failopen>0", r["violations"]["failopen"] > 0)
    case("inject-failopen: kapı eler", _gate_eval(r, G)[0] is False)

    # 14) K2 invalid_channel_count inject — geçersiz kanalda kayıt
    r = build(req(), spec, inject=["invalid_channel_count"])
    case("inject-invalid: invalid_layout>0", r["violations"]["invalid_layout"] > 0)
    case("inject-invalid: kapı eler", _gate_eval(r, G)[0] is False)

    # 15) K6 residency_leak — kayıt home-region dışına yazılır
    r = build(req(), spec, inject=["residency_leak"])
    case("inject-residency: residency_violation>0", r["violations"]["residency_violation"] > 0)
    case("inject-residency: kapı eler", _gate_eval(r, G)[0] is False)
    # doğru residency (no inject): storage=home(TR) → ihlal yok
    r = build(req(storage_region="TR"), spec)
    case("residency: storage=home(TR) → ihlal yok", r["violations"]["residency_violation"] == 0)

    # 16) K12 cross_tenant
    r = build(req(), spec, inject=["cross_tenant"])
    case("inject-cross-tenant: cross_tenant>0 + BLOCK",
         r["violations"]["cross_tenant"] > 0 and r["terminal"] == "BLOCK")
    r = build(req(bind_tenant="t-other"), spec)
    case("bind-mismatch: cross_tenant>0", r["violations"]["cross_tenant"] > 0)

    # 17) K10 no_audit
    r = build(req(), spec, inject=["no_audit"])
    case("inject-no-audit: missing_audit>0", r["violations"]["missing_audit"] > 0)
    case("inject-no-audit: audit None", r["audit"] is None)

    # 18) K5 GARANTİ — her terminal ∉ {MONO,DUAL} ⇒ no_media_captured=true
    for kw in (dict(upstream_decision="DISABLED", upstream_no_media_captured=True),  # NO_RECORD
               dict(upstream_decision="NO_CONSENT", upstream_no_media_captured=True),  # NO_RECORD
               dict(channels=3),                                                      # BLOCK
               dict(upstream_decision=None)):                                         # BLOCK
        rr = build(req(**kw), spec)
        if rr["terminal"] not in RECORDED:
            case("K5 garanti: %s → no_media_captured=true" % rr["terminal"], rr["no_media_captured"] is True)

    # 19) kanıt (K9) + audit (K10)
    r = build(req(), spec)
    case("evidence: request taşır", r["evidence"]["request_id"] == "req-1")
    case("evidence: upstream/authorized/tracks taşır",
         all(k in r["evidence"] for k in ("upstream_decision", "authorized", "tracks")))
    case("audit: result/channels/tenant taşır",
         r["audit"]["result"] == "DUAL" and r["audit"]["channels"] == 2 and r["audit"]["tenant_id"] == "t-acme")
    case("audit: telefon/ad/ham-ses alanı yok",
         all(k not in json.dumps(r["audit"]) for k in ("customer_phone_value", "customer_name", "raw_audio")))

    # 20) sızıntı tarayıcı
    case("leak: req-001 kimlik temiz", scan_leaks('{"request_id": "req-001"}') == [])
    case("leak: enum/sayı temiz", scan_leaks('{"mode": "DUAL", "channels": 2}') == [])
    case("leak: customer_phone_value alanı yakalanır", len(scan_leaks('{"customer_phone_value": "x"}')) > 0)
    case("leak: raw_audio alanı yakalanır", len(scan_leaks('{"raw_audio": "x"}')) > 0)
    case("leak: ham uzun telefon yakalanır", len(scan_leaks('{"x": "905551234567"}')) > 0)

    npass = sum(1 for ok, _ in results if ok)
    for ok, name in results:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print("\nselftest: %d/%d %s" % (npass, len(results), "🟢" if npass == len(results) else "🔴"))
    return 0 if npass == len(results) else 1


# ════════════════════════════════════════════════════════════════════════════
def schema_cmd():
    out = {
        "module": "channel-recording (WBS 11.2 — FR-REC-003 tek/çift kanallı kayıt)",
        "outcomes": OUTCOMES,
        "terminal": sorted(TERMINAL),
        "recorded": sorted(RECORDED),
        "rules": RULES,
        "block_reasons": BLOCK_REASONS,
        "valid_channels": VALID_CHANNELS,
        "decision": "tenant_check ⇒ BLOCK(cross_tenant) → authorize(upstream==RECORD ∧ ¬no_media) fail ⇒ "
                    "NO_RECORD(no_media) → channels∉{1,2} ⇒ BLOCK(invalid_channel_count) → "
                    "channels==1 ⇒ MONO(1 track, all legs) | channels==2 ⇒ DUAL(2 track, caller↔agent ayrı) "
                    "→ residency(home_region)",
        "default": "BLOCK (fail-closed)",
        "fail_safe": "terminal ∉ {MONO,DUAL} ⇒ no_media_captured = true (FR-REC-002/SR-REC-002 aşağı akış)",
        "layouts": {"MONO": "channels=1, 1 track, tüm bacak downmix",
                    "DUAL": "channels=2, 2 track, caller→ch0, agent/human→ch1"},
        "channel_side": {"caller": 0, "agent": 1, "human": 1},
        "request_fields": ["name", "request_id", "tenant_id", "correlation_id", "call_id",
                           "direction(inbound|outbound)", "upstream_decision(RECORD|DISABLED|NO_CONSENT|BLOCK)",
                           "upstream_no_media_captured(bool)", "channels(1|2)",
                           "media_legs[caller|agent|human]", "in_region_storage_required(bool)",
                           "storage_region", "home_region", "bind_tenant", "config_override{}",
                           "inject[]", "expect", "expected{}"],
        "injections (degrade testi)": sorted(INJECTIONS),
        "decision_fields": ["terminal", "mode", "channels", "tracks", "track_count", "authorized",
                            "recording_written", "no_media_captured", "storage_region", "home_region",
                            "block_reason", "evidence", "audit"],
        "violations": VIOLATION_KEYS,
        "invariants": INVARIANT_IDS,
        "consumes": "11.1 recording-policy (upstream_decision RECORD + channels attribute + home/storage region)",
        "consumed_by": "SAD §10.2 Recording Pipeline (MONO/DUAL track planı → byte yazımı + storage_uri)",
        "trace": "FR-REC-003, SR-REC-003, TC-REC-003, FR-REC-001/002 (11.1), FR-REC-004, FR-IAM-006, "
                 "FR-TEN-002, NFR 10.7, BRD §9.14, BRD §15, SAD §10.2 Recording Pipeline, DB §22 "
                 "recording.channels, ADR-001/002/012",
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
            print("kullanım: channel_recording_probe.py check <sample.json|dizin>")
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
