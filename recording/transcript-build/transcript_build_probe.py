#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 11.3 — Transkript üretimi + timeline (transcript-build) referans probe.

11. workstream'in (Kayıt, Transkript & PII Redaction) TRANSKRİPT ÜRETİMİ (transcript-build) modülü ve
F1-Must temel yeteneği. BRD §8.1 (Inbound Müşteri Hizmetleri akışı: çağrıyı karşıla→anla→işle→teyit→
özetle+sonuçlandır) + FR-REC-008 ('Yetkili kullanıcı çağrıyı dinleyebilmeli ve transkripti görebilmelidir')
+ DB §21 transcript/transcript_segment + DB §23 call_event + SAD §10.2 Transcript Store'u sahiplenir.
Çağrının canlı STT FINAL transcript turn'lerini + sistem olaylarını alır → DETERMİNİSTİK, ZAMAN-SIRALI,
KONUŞMACI-ATFLI transkript + BİRLEŞİK TIMELINE üretir. 11.1 içerik kararının + 11.2 kanal yerleşiminin
AŞAĞI AKIŞ TÜKETİCİSİ; üretilen transkript redaction_state=pending ile 11.4/11.5/11.6'ya AKTARILIR
(REDACTION YAPMAZ). DETERMİNİSTİK FAIL-CLOSED motor:

  TranscriptBuildRequest ─tenant doğrula─► içerik kapısı ─► sırala+seq ─► konuşmacı atfı ─► timeline ─► redaction pending
        │                       │               │              │               │              │
        │   authorized = (upstream_decision == RECORD)          │               │              │
        │      ├─ cross-tenant ──────────────────────────────────────────────► BLOCK (cross_tenant)        [K12]
        │      ├─ upstream yok/geçersiz ─────────────────────────────────────► BLOCK (no_upstream)
        │      ├─ yetkisiz (11.1 RECORD değil) ──────────────────────────────► NO_TRANSCRIPT (no content)  [K5]
        │      ├─ malformed turn (turn_id yok) ──────────────────────────────► BLOCK (invalid_turn_stream)  [K8]
        │      └─ yetkili ───────────────────────────────────────────────────► TRANSCRIPT (seq+atıf+timeline)

ÇEKİRDEK INVARIANT'lar: K2 zaman-sıralı (started_ms monoton + seq 1..N bitişik; BRD §8.1), K3 konuşmacı
atfı (speaker ∈ {caller,agent,human}; DUAL kanal tutarlı), K4 tamlık (her final turn → 1 segment; timeline
TÜM segment+olay), K5 içerik kapısı (upstream≠RECORD ⇒ no_content_persisted=true; FR-REC-002 aşağı akış —
over_capture yasak), K6 residency (home-region), K7 redaction devri (redaction_state pending/not_required;
ASLA 'redacted' — premature_redaction yasak), K8 ATLANAMAZ (bypass=assembly_skip; malformed→BLOCK, fail-open
yok). Her karar deterministik+terminal (K1) + kanıt (K9) + audit (K10); metrik düşük-kardinalite + PII yok
(K11); ham transkript metni/sır/PII yok + tenant izolasyonu (K12).

Kapsam dışı (bilinçli, başka modül SAHİBİ): içerik/kayıt KARARI + consent + tamamen kapatma → 11.1
(upstream_decision TÜKETİLİR); kanal/track yerleşimi → 11.2 (channels + konuşmacı-kanal TÜKETİLİR); ham
transkript METİN byte üretimi (STT) + nesne depo yazımı → SAD §6.1/§10.2 + DB §21 (SIRALAMA/ATIF/TIMELINE
KARARI verilir, ham metin YAZILMAZ); PII redaction → 11.4 (redaction_state=pending TAŞINIR); kart/parola/OTP
→ 11.5; erişim audit + görüntüleme yetkisi → 11.6 (FR-REC-008/009); çağrı özeti → özetleyici (summary TAŞINIR).

Kullanım:
  transcript_build_probe.py validate          Statik spec/config/kapsama kapısı → çıkış kodu
  transcript_build_probe.py check <sample>     Transkript-üretim motoru: senaryo(lar)ı çalıştır → kapı (K1–K12)
  transcript_build_probe.py selftest           Gömülü davranış kontrolleri → çıkış kodu
  transcript_build_probe.py schema             Karar sözleşmesini yazdır

Determinizm: kanonik sıralama (started_ms,turn_id) + seq atama; Date.now/random YOK. Stdlib-only. Sır/
credential ve gerçek PII (ham transkript metni/telefon/ham ses) üretilmez/yazılmaz (fixture sentetik —
FR-TST-008).
"""
import json
import os
import re
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "transcript-build-spec.json")
CONFIG_PATH = os.path.join(HERE, "config", "transcript-build.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

OUTCOMES = ["TRANSCRIPT", "NO_TRANSCRIPT", "BLOCK"]
TERMINAL = {"TRANSCRIPT", "NO_TRANSCRIPT", "BLOCK"}
BUILT = {"TRANSCRIPT"}                      # içerik kalıcılaştırılan terminal
RULES = ["persist_only_when_authorized", "chronological_order", "speaker_attribution",
         "completeness", "redaction_handoff", "residency_honored"]
BLOCK_REASONS = ["invalid_turn_stream", "cross_tenant", "no_upstream"]
INVARIANT_IDS = ["K1", "K2", "K3", "K4", "K5", "K6", "K7", "K8", "K9", "K10", "K11", "K12"]
VALID_SPEAKERS = ["caller", "agent", "human"]
VALID_CHANNELS = [1, 2]
UPSTREAM_DECISIONS = {"RECORD", "DISABLED", "NO_CONSENT", "BLOCK"}
PRODUCIBLE_REDACTION = {"pending", "not_required"}

# Degrade (inject) — DOĞRU fail-closed/sıralama-atıf-tamlık davranışını bozan müdahaleler.
INJECTIONS = {"skip_assembly", "reorder_segments", "seq_gap", "drop_turn", "duplicate_turn",
              "strip_speaker", "misattribute_speaker", "drop_event", "persist_when_not_authorized",
              "premature_redaction", "residency_leak", "failopen_assembly", "cross_tenant", "no_audit"}

VIOLATION_KEYS = [
    "assembly_skip", "ordering_violation", "missing_speaker", "speaker_mismatch",
    "turn_dropped", "turn_duplicated", "event_dropped", "over_capture",
    "premature_redaction", "residency_violation", "failopen", "cross_tenant",
    "missing_evidence", "missing_audit", "stuck_state", "secret_or_pii",
]

# ── Sızıntı tarayıcı (K12; 11.1/11.2 deseniyle) — ham transkript metni/telefon/hesap no/OTP/ham ses yasak ──
LEAK_PATTERNS = [
    ("phone_e164", re.compile(r"\+(?!1632)\d{9,15}\b")),
    ("phone_long", re.compile(r"\b\d{9,15}\b")),
    ("secret_kw", re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|token|bearer|credential)\b\s*[:=]\s*\S")),
    ("privkey", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("pii_field", re.compile(r"(?i)\"(transcript_text|segment_text|customer_name|customer_phone_value|account_number_value|raw_audio|otp_code_value|password_value|raw_value|raw_msisdn)\"\s*:")),
]
# Yapısal kimlik/enum/sayı beyaz-listelenir.
LEAK_ALLOW = re.compile(r"(?i)(555-?01\d\d|\+1632|ITU|reserved|test|example|req-|call-|turn-|ev-|camp-|t-|corr-|prefix|masked|last4|\d{4}-\d{2}-\d{2})")


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
    """Config = ana transcript-build.json; sample.config_override yapısal alanları geçersiz kılar."""
    cfg = _load(CONFIG_PATH)
    ov = sample.get("config_override", {}) or {}
    for k in ("channel_side", "valid_speakers", "order_key", "producible_redaction_states"):
        if k in ov:
            if isinstance(ov[k], dict) and isinstance(cfg.get(k), dict):
                cfg.setdefault(k, {}).update(ov[k])
            else:
                cfg[k] = ov[k]
    return cfg


def _build_segments(finals, channels, channel_side, inject, v):
    """Final turn'lerden zaman-sıralı, konuşmacı-atflı segment listesi kur; ihlalleri say.

    Kanonik sıra: (started_ms, turn_id). seq 1..N bitişik. inject (degrade) doğru sırayı/atfı/tamlığı bozar
    ve eşleşen ihlali artırır."""
    segs = []
    for t in finals:
        spk = t.get("speaker")
        ch = t.get("channel")
        if ch is None:
            ch = channel_side.get(spk, 0) if channels == 2 else 0
        segs.append({
            "turn_id": t.get("turn_id"),
            "speaker": spk,
            "started_ms": t.get("start_ms"),
            "end_ms": t.get("end_ms"),
            "confidence": t.get("confidence"),
            "channel": ch,
            "redaction_required": bool(t.get("redaction_required", False)),
            "kind": "final",
        })

    # ── K2 kanonik deterministik sıra (started_ms, turn_id) ──
    if "reorder_segments" in inject:
        segs = list(reversed(sorted(segs, key=lambda s: ((s["started_ms"] if s["started_ms"] is not None else 0), str(s["turn_id"])))))
    else:
        segs.sort(key=lambda s: ((s["started_ms"] if s["started_ms"] is not None else 0), str(s["turn_id"])))

    # ── K4 tamlık ihlal enjeksiyonları ──
    if "drop_turn" in inject and len(segs) > 1:
        segs = segs[:-1]                                    # bir final turn düşer → konuşmanın yarısı kaybolur
    if "duplicate_turn" in inject and segs:
        segs = segs + [dict(segs[-1])]                      # aynı turn iki kez

    # ── K3 atıf ihlal enjeksiyonları ──
    if "strip_speaker" in inject and segs:
        segs[0] = dict(segs[0])
        segs[0]["speaker"] = None                           # atıfsız segment
    if "misattribute_speaker" in inject and segs:
        segs[0] = dict(segs[0])
        cur = channel_side.get(segs[0]["speaker"], 0)
        segs[0]["channel"] = 1 - cur                        # konuşmacı yanlış kanala atfedildi (DUAL)

    # ── seq 1..N ata ──
    for i, s in enumerate(segs):
        s["seq"] = i + 1
    if "seq_gap" in inject and segs:
        segs[-1]["seq"] = segs[-1]["seq"] + 5               # seq bitişik değil → eksik/atlanmış seq

    # ── K2 sıralama doğrulama: started_ms monoton artan + seq bitişik ──
    prev = None
    for s in segs:
        st = s.get("started_ms")
        if prev is not None and st is not None and st < prev:
            v["ordering_violation"] += 1
        if st is not None:
            prev = st
    seqs = [s["seq"] for s in segs]
    if seqs != list(range(1, len(segs) + 1)):
        v["ordering_violation"] += 1

    # ── K3 konuşmacı atfı doğrulama ──
    for s in segs:
        spk = s.get("speaker")
        if spk not in VALID_SPEAKERS:
            v["missing_speaker"] += 1
        elif channels == 2 and s.get("channel") is not None and s["channel"] != channel_side.get(spk):
            v["speaker_mismatch"] += 1

    # ── K4 tamlık doğrulama: her final turn → tam bir segment (düşmez/çoğalmaz) ──
    expected_ids = [t.get("turn_id") for t in finals]
    seg_ids = [s["turn_id"] for s in segs]
    seg_set = set(seg_ids)
    for tid in expected_ids:
        if tid not in seg_set:
            v["turn_dropped"] += 1
    for tid, c in Counter(seg_ids).items():
        if c > 1:
            v["turn_duplicated"] += 1

    return segs


def _build_timeline(segs, system_events, inject, v):
    """Segmentleri + sistem olaylarını zaman-sıralı tek timeline'a birleştir; ihlalleri say (K4 tamlık)."""
    items = [{"kind": "segment", "ref": s["turn_id"], "at_ms": s.get("started_ms"),
              "speaker": s.get("speaker"), "seq": s.get("seq")} for s in segs]
    sys_items = [{"kind": "event", "ref": e.get("event_id"), "at_ms": e.get("at_ms"),
                  "event_type": e.get("event_type")} for e in system_events]
    if "drop_event" in inject and sys_items:
        sys_items = sys_items[:-1]                          # bir sistem olayı timeline'dan düşer
    items = items + sys_items

    # ── zaman-sıralı birleştir (deterministik; eşitlikte event önce) ──
    if "reorder_segments" not in inject:
        items.sort(key=lambda x: ((x["at_ms"] if x["at_ms"] is not None else 0),
                                   0 if x["kind"] == "event" else 1))

    # ── K4 tamlık: TÜM segment + TÜM sistem olayı timeline'da ──
    seg_refs = {s["turn_id"] for s in segs}
    ev_refs = {e.get("event_id") for e in system_events}
    tl_seg = {x["ref"] for x in items if x["kind"] == "segment"}
    tl_ev = {x["ref"] for x in items if x["kind"] == "event"}
    if tl_seg != seg_refs:
        v["event_dropped"] += 1
    if tl_ev != ev_refs:
        v["event_dropped"] += 1

    # ── timeline zaman-sıralı (monoton) ──
    prev = None
    for x in items:
        at = x.get("at_ms")
        if prev is not None and at is not None and at < prev:
            v["ordering_violation"] += 1
        if at is not None:
            prev = at
    return items


def build(sample, spec, inject=None, cfg=None):
    """Tek transkript-üretim senaryosunu yürüt → TranscriptBuildDecision + ihlal sayaçları.

    Motor DOĞRU fail-closed / sıralama-atıf-tamlık davranışını hesaplar; inject (degrade) doğru davranışı
    bozar ve eşleşen ihlal sayacını artırır (11.1/11.2 inject deseniyle birebir)."""
    inject = set(inject if inject is not None else sample.get("inject", []))
    cfg = cfg if cfg is not None else _config(sample)

    tenant = sample.get("tenant_id")
    call_id = sample.get("call_id")
    request_id = sample.get("request_id")
    correlation_id = sample.get("correlation_id")
    direction = sample.get("direction")
    upstream = sample.get("upstream_decision")               # 11.1: RECORD/DISABLED/NO_CONSENT/BLOCK
    channels = sample.get("channels", 2)                     # 11.2 channels attribute
    turn_events = list(sample.get("turn_events", []))
    system_events = list(sample.get("system_events", []))
    storage_region = sample.get("storage_region")
    home_region = sample.get("home_region")
    in_region = bool(sample.get("in_region_storage_required", False))

    channel_side = cfg.get("channel_side", {})
    valid_speakers = cfg.get("valid_speakers", VALID_SPEAKERS)

    v = {k: 0 for k in VIOLATION_KEYS}

    segments = None
    timeline = None
    redaction_state = None
    content_persisted = False
    no_content_persisted = True              # privacy-safe varsayılan: içerik yok
    block_reason = None
    authorized = None

    finals = [t for t in turn_events if t.get("kind", "final") == "final"]
    redaction_required = bool(sample.get("redaction_required", False)) or any(
        bool(t.get("redaction_required", False)) for t in finals)

    # ── K12 (tenant izolasyonu): transkript yalnız aynı tenant'a bağlanır ──
    if "cross_tenant" in inject:
        v["cross_tenant"] += 1
    if sample.get("bind_tenant") and sample.get("bind_tenant") != tenant:
        v["cross_tenant"] += 1

    # ── K8 (fail-closed / ATLANAMAZ): bypass → sıralama/atıf çözmeden içerik kalıcılaştır → assembly_skip ──
    if "skip_assembly" in inject:
        v["assembly_skip"] += 1
        content_persisted = True
        no_content_persisted = False                       # üretim çözülmeden içerik = bütünlük ihlali
        segments = []                                      # ham/çözülmemiş; sıralı segment yok
        timeline = []
        redaction_state = "pending"
        terminal = "TRANSCRIPT"
        evidence = _evidence(request_id, upstream, None, channels, 0, 0, redaction_state,
                             content_persisted, no_content_persisted, storage_region, home_region,
                             direction, None)
        if not request_id:
            v["missing_evidence"] += 1
        audit = None if "no_audit" in inject else _audit(
            terminal, request_id, call_id, direction, 0, 0, redaction_state, content_persisted,
            no_content_persisted, correlation_id, tenant)
        if "no_audit" in inject:
            v["missing_audit"] += 1
        return _pack(sample, terminal, v, channels, segments, timeline, authorized, redaction_state,
                     content_persisted, no_content_persisted, storage_region, home_region, block_reason,
                     evidence, audit)

    # cross-tenant fail-closed BLOCK
    if v["cross_tenant"] > 0:
        block_reason = "cross_tenant"

    # ── upstream (11.1 kararı) yok/geçersiz → fail-closed BLOCK no_upstream ──
    if block_reason is None and upstream not in UPSTREAM_DECISIONS:
        block_reason = "no_upstream"

    if block_reason is not None:
        terminal = "BLOCK"
        no_content_persisted = True
        content_persisted = False
    else:
        # ── K5 (FR-REC-002 aşağı akış): içerik YALNIZ 11.1 RECORD dediğinde kalıcılaştırılır ──
        authorized = (upstream == "RECORD")
        if not authorized:
            terminal = "NO_TRANSCRIPT"
            no_content_persisted = True
            content_persisted = False
            if "persist_when_not_authorized" in inject:
                content_persisted = True
                no_content_persisted = False               # yetkisizken içerik = over_capture
                v["over_capture"] += 1
                segments = _build_segments(finals, channels, channel_side, inject, v)
                timeline = _build_timeline(segments, system_events, inject, v)
        else:
            # ── K8: malformed turn stream (final turn'de turn_id yok) → fail-closed BLOCK ──
            malformed = any(not t.get("turn_id") for t in finals)
            if malformed and "failopen_assembly" not in inject:
                block_reason = "invalid_turn_stream"
                terminal = "BLOCK"
                no_content_persisted = True
                content_persisted = False
            else:
                if malformed and "failopen_assembly" in inject:
                    v["failopen"] += 1                     # malformed turn'de sessiz içerik = K8 fail-open
                # ── K2 sırala+seq → K3 atıf → K4 timeline ──
                segments = _build_segments(finals, channels, channel_side, inject, v)
                timeline = _build_timeline(segments, system_events, inject, v)
                content_persisted = True
                no_content_persisted = False
                terminal = "TRANSCRIPT"
                # ── K7 redaction devri: pending (gerekli) / not_required; ASLA 'redacted' ──
                redaction_state = "pending" if redaction_required else "not_required"
                if "premature_redaction" in inject:
                    redaction_state = "redacted"           # bu modülün ÜRETEMEYECEĞİ durum
                if redaction_state not in PRODUCIBLE_REDACTION:
                    v["premature_redaction"] += 1
                # ── K6 residency: in_region ise storage_region == home_region ──
                if "residency_leak" in inject:
                    storage_region = (home_region or "EU") + "-ALT"
                if in_region and storage_region is not None and storage_region != home_region:
                    v["residency_violation"] += 1

    if block_reason is not None and terminal != "BLOCK":
        terminal = "BLOCK"

    # ── K5 ÇEKİRDEK GARANTİ: terminal ∉ {TRANSCRIPT} ⇒ no_content_persisted = true ──
    if terminal not in BUILT and not no_content_persisted:
        v["over_capture"] += 1

    # ── K1 stuck state ──
    if terminal not in TERMINAL:
        v["stuck_state"] += 1

    seg_count = len(segments) if segments else 0
    tl_count = len(timeline) if timeline else 0

    # ── Kanıt (K9) ──
    evidence = _evidence(request_id, upstream, authorized, channels, seg_count, tl_count, redaction_state,
                         content_persisted, no_content_persisted, storage_region, home_region, direction,
                         block_reason)
    if (not request_id) or (terminal is None):
        v["missing_evidence"] += 1

    # ── Audit (K10) ── (ham TRANSKRİPT metni/PII YOK — yalnız yapısal kimlik/enum/sayı)
    audit = None
    if "no_audit" in inject:
        v["missing_audit"] += 1
    else:
        audit = _audit(terminal, request_id, call_id, direction, seg_count, tl_count, redaction_state,
                       content_persisted, no_content_persisted, correlation_id, tenant)

    return _pack(sample, terminal, v, channels, segments, timeline, authorized, redaction_state,
                 content_persisted, no_content_persisted, storage_region, home_region, block_reason,
                 evidence, audit)


def _evidence(request_id, upstream, authorized, channels, seg_count, tl_count, redaction_state,
              content_persisted, no_content_persisted, storage_region, home_region, direction,
              block_reason):
    return {
        "request_id": request_id,
        "upstream_decision": upstream,
        "authorized": authorized,
        "channels": channels,
        "segment_count": seg_count,
        "timeline_count": tl_count,
        "redaction_state": redaction_state,
        "content_persisted": content_persisted,
        "no_content_persisted": no_content_persisted,
        "storage_region": storage_region,
        "home_region": home_region,
        "direction": direction,
        "block_reason": block_reason,
    }


def _audit(terminal, request_id, call_id, direction, seg_count, tl_count, redaction_state,
           content_persisted, no_content_persisted, correlation_id, tenant):
    return {
        "result": terminal,
        "request_id": request_id,
        "call_id": call_id,
        "direction": direction,
        "segment_count": seg_count,
        "timeline_count": tl_count,
        "redaction_state": redaction_state,
        "content_persisted": content_persisted,
        "no_content_persisted": no_content_persisted,
        "correlation_id": correlation_id,
        "tenant_id": tenant,
    }


def _pack(sample, terminal, v, channels, segments, timeline, authorized, redaction_state,
          content_persisted, no_content_persisted, storage_region, home_region, block_reason,
          evidence, audit):
    return {
        "name": sample.get("name"),
        "terminal": terminal,
        "resolved": terminal in TERMINAL,
        "channels": channels,
        "segments": segments,
        "timeline": timeline,
        "segment_count": len(segments) if segments else 0,
        "timeline_count": len(timeline) if timeline else 0,
        "authorized": authorized,
        "redaction_state": redaction_state,
        "content_persisted": content_persisted,
        "no_content_persisted": no_content_persisted,
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
        "assembly_skip": "max_assembly_skip",
        "ordering_violation": "max_ordering_violation",
        "missing_speaker": "max_missing_speaker",
        "speaker_mismatch": "max_speaker_mismatch",
        "turn_dropped": "max_turn_dropped",
        "turn_duplicated": "max_turn_duplicated",
        "event_dropped": "max_event_dropped",
        "over_capture": "max_over_capture",
        "premature_redaction": "max_premature_redaction",
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
        for key in ("terminal", "block_reason", "segment_count", "timeline_count",
                    "redaction_state", "content_persisted", "no_content_persisted"):
            if key in exp_assert and exp_assert[key] != res.get(key):
                mism.append("%s: beklenen=%r gerçek=%r" % (key, exp_assert[key], res.get(key)))

        verdict_ok = (passed and not mism) if expect == "pass" else (not passed)
        all_ok = all_ok and verdict_ok
        icon = "🟢" if verdict_ok else "🔴"
        print("%s %s" % (icon, os.path.basename(p)))
        print("   terminal=%s seg=%s timeline=%s reason=%s redaction=%s content=%s no_content=%s"
              % (res["terminal"], res["segment_count"], res["timeline_count"], res["block_reason"],
                 res["redaction_state"], res["content_persisted"], res["no_content_persisted"]))
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
              "block_reasons", "outcomes", "speakers", "timeline", "redaction_states",
              "authorization", "gates", "observability", "invariants", "no_secrets"):
        chk("spec.%s var" % f, f in spec)
    chk("wbs=11.3", spec.get("wbs") == "11.3")
    chk("phase=F1", spec.get("phase") == "F1")
    chk("priority=Must", spec.get("priority") == "Must")
    chk("placement fail_closed=true", spec.get("placement", {}).get("fail_closed") is True)

    # 2) İzlenebilirlik
    tr = spec.get("trace", {})
    chk("FR-REC-008 izlenir (transkripti görebilme)", "FR-REC-008" in tr.get("fr", []))
    chk("FR-REC-002 izlenir (tamamen kapatma aşağı akış)", "FR-REC-002" in tr.get("fr", []))
    chk("FR-REC-001 izlenir (11.1 içerik kararı)", "FR-REC-001" in tr.get("fr", []))
    chk("FR-REC-003 izlenir (11.2 kanal/konuşmacı)", "FR-REC-003" in tr.get("fr", []))
    chk("FR-REC-004 izlenir (redaction aşağı akış)", "FR-REC-004" in tr.get("fr", []))
    chk("FR-REC-005 izlenir (kart/parola/OTP aşağı akış)", "FR-REC-005" in tr.get("fr", []))
    chk("FR-IAM-006 izlenir (audit)", "FR-IAM-006" in tr.get("fr", []))
    chk("FR-TEN-002 izlenir (tenant izolasyonu)", "FR-TEN-002" in tr.get("fr", []))
    chk("FR-RES-011 izlenir (asenkron analytics plane)", "FR-RES-011" in tr.get("fr", []))
    chk("SR-REC-008 izlenir", "SR-REC-008" in tr.get("srs", []))
    chk("SR-REC-002 izlenir (no content aşağı akış)", "SR-REC-002" in tr.get("srs", []))
    chk("TC-REC-008 izlenir", "TC-REC-008" in tr.get("rtm", []))
    chk("NFR 10.7 izlenir (residency)", "NFR 10.7" in tr.get("nfr", []))
    chk("ADR-001/002/012 izlenir",
        any("ADR-001" in a for a in tr.get("adr", []))
        and any("ADR-002" in a for a in tr.get("adr", []))
        and any("ADR-012" in a for a in tr.get("adr", [])))
    chk("SAD §10.2 Transcript Store izlenir", any("§10.2" in s for s in tr.get("sad", [])))
    chk("SAD §6.1 turn state machine izlenir", any("§6.1" in s for s in tr.get("sad", [])))
    chk("DB §21 transcript/segment izlenir", any("§21" in d for d in tr.get("db", [])))
    chk("DB §23 call_event izlenir", any("§23" in d for d in tr.get("db", [])))
    chk("BRD §8.1 inbound akış izlenir", any("§8.1" in s for s in tr.get("brd", [])))
    chk("BRD §15 gizlilik/bütünlük alarmı izlenir", any("§15" in s for s in tr.get("brd", [])))
    chk("11.1 recording-policy consumes (içerik kapısı)", any("11.1" in c for c in tr.get("consumes", [])))
    chk("11.2 channel-recording consumes (kanal/konuşmacı)", any("11.2" in c for c in tr.get("consumes", [])))
    chk("11.4 redaction consumed_by (redaction_state=pending)", any("11.4" in c for c in tr.get("consumed_by", [])))

    # 3) Altı kural (çekirdek)
    rz = spec["rules"]
    rule_ids = [d["id"] for d in rz.get("list", [])]
    chk("altı kural tam (persist/order/attribute/complete/redaction/residency)", set(rule_ids) == set(RULES))
    chk("değerlendirme tenant_check_then_authorize_content_then_order_then_attribute_then_merge_timeline_then_redaction_pending_fail_closed_no_content",
        rz.get("evaluation") == "tenant_check_then_authorize_content_then_order_then_attribute_then_merge_timeline_then_redaction_pending_fail_closed_no_content")
    for d in rz.get("list", []):
        chk("kural %s invariant taşır" % d["id"], d.get("invariant") in INVARIANT_IDS)

    # 4) Karar
    dec = spec["decision"]
    chk("karar default=BLOCK (fail-closed)", dec.get("default") == "BLOCK")
    chk("fail_safe_terminal no_transcript", "no_transcript" in dec.get("fail_safe_terminal", ""))

    # 5) Sonuçlar + block_reason taksonomisi
    oc = spec["outcomes"]
    chk("terminal sonuçlar TRANSCRIPT/NO_TRANSCRIPT/BLOCK", set(oc.get("list", [])) == set(OUTCOMES))
    br = set(spec["block_reasons"].get("list", []))
    chk("block_reason taksonomisi tam (invalid_turn_stream/cross_tenant/no_upstream)", br == set(BLOCK_REASONS))

    # 5b) Speakers + timeline + redaction_states
    sp = spec["speakers"]
    chk("speakers valid {caller,agent,human}", set(sp.get("valid", [])) == set(VALID_SPEAKERS))
    chk("speakers channel_side caller=0", sp.get("channel_side", {}).get("caller") == 0)
    chk("speakers channel_side agent=1 ∧ human=1",
        sp.get("channel_side", {}).get("agent") == 1 and sp.get("channel_side", {}).get("human") == 1)
    tl = spec["timeline"]
    chk("timeline item_kinds {segment,event}", set(tl.get("item_kinds", [])) == {"segment", "event"})
    chk("timeline event_types call_start/transfer/call_end içerir",
        all(e in tl.get("event_types", []) for e in ("call_start", "transfer", "call_end")))
    rs = spec["redaction_states"]
    chk("redaction producible {pending,not_required}", set(rs.get("producible", [])) == PRODUCIBLE_REDACTION)
    chk("redaction 'redacted' yasak (bu modül üretmez)", "redacted" in rs.get("forbidden_here", []))

    # 6) Yetki — transcript:read görüntüleme + otomatik async gate
    az = spec["authorization"]
    chk("view_permission=transcript:read (FR-REC-008)", az.get("view_permission") == "transcript:read")
    chk("per_call_check otomatik async gate", "automatic_async_gate" in az.get("per_call_check", ""))
    chk("karar backend'de", az.get("decision_at") == "backend")

    # 7) Kapılar — tüm sıfır-eşik ihlal kapıları
    g = spec["gates"]
    for gk in ("max_assembly_skip", "max_ordering_violation", "max_missing_speaker", "max_speaker_mismatch",
               "max_turn_dropped", "max_turn_duplicated", "max_event_dropped", "max_over_capture",
               "max_premature_redaction", "max_residency_violation", "max_failopen", "max_cross_tenant",
               "max_missing_evidence", "max_missing_audit", "max_stuck_state", "max_secret_or_pii"):
        chk("kapı %s=0" % gk, g.get(gk) == 0)
    chk("require_terminal", g.get("require_terminal") is True)
    chk("require_decision_record", g.get("require_decision_record") is True)

    # 8) Gözlemlenebilirlik — kardinalite disiplini (0.4.7)
    obs = spec["observability"]
    chk("transcript_build_decision_total metrik", "transcript_build_decision_total" in obs.get("metrics", []))
    chk("transcript_build_notranscript_total metrik (FR-REC-002 aşağı akış)",
        "transcript_build_notranscript_total" in obs.get("metrics", []))
    chk("transcript_build_integrity_violation_total metrik (K2/K3/K4/K5/K7/K8 alarm)",
        "transcript_build_integrity_violation_total" in obs.get("metrics", []))
    hi = set(obs.get("high_cardinality_trace_only", []))
    lo = set(obs.get("low_cardinality_labels", []))
    chk("request_id/call_id/turn_id YÜKSEK kard (label değil)",
        "request_id" in hi and "call_id" in hi and "turn_id" in hi and "call_id" not in lo)
    chk("result/direction DÜŞÜK kard (label uygun)", "result" in lo and "direction" in lo)
    chk("alarm over_capture/ordering_violation ≤2dk",
        "over_capture" in obs.get("alarm", "") or "ordering_violation" in obs.get("alarm", ""))

    # 9) İnvariant'lar K1–K12
    inv_ids = [i["id"] for i in spec["invariants"]]
    chk("invariant'lar K1–K12 tam", inv_ids == INVARIANT_IDS)

    # 10) Config dosyası
    cfg_ok = os.path.exists(CONFIG_PATH)
    chk("config/transcript-build.json var", cfg_ok)
    if cfg_ok:
        cfg = _load(CONFIG_PATH)
        chk("config valid_speakers {caller,agent,human}", set(cfg.get("valid_speakers", [])) == set(VALID_SPEAKERS))
        cs = cfg.get("channel_side", {})
        chk("config channel_side caller=0 (11.2 ile)", cs.get("caller") == 0)
        chk("config channel_side agent=1 ∧ human=1", cs.get("agent") == 1 and cs.get("human") == 1)
        chk("config order_key (started_ms,turn_id)", cfg.get("order_key") == ["started_ms", "turn_id"])
        chk("config producible_redaction_states {pending,not_required}",
            set(cfg.get("producible_redaction_states", [])) == PRODUCIBLE_REDACTION)
        chk("config 'redacted' producible DEĞİL", "redacted" not in cfg.get("producible_redaction_states", []))

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
    chk("hiç ham-transkript/telefon/hesap-no/ham-ses/sır sızıntısı yok (K12)", total_leaks == 0)

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
        # Varsayılan: 11.1 RECORD + channels=2 (DUAL) + 3 final turn + 3 sistem olay; storage=home(TR).
        d = {
            "request_id": "req-1", "tenant_id": "t-acme", "correlation_id": "corr-1",
            "call_id": "call-1", "direction": "inbound", "upstream_decision": "RECORD",
            "channels": 2, "in_region_storage_required": True, "storage_region": "TR", "home_region": "TR",
            "turn_events": [
                {"turn_id": "turn-1", "speaker": "caller", "start_ms": 1000, "end_ms": 2000, "kind": "final", "confidence": 0.95},
                {"turn_id": "turn-2", "speaker": "agent", "start_ms": 2500, "end_ms": 4000, "kind": "final", "confidence": 0.97},
                {"turn_id": "turn-3", "speaker": "caller", "start_ms": 4500, "end_ms": 5200, "kind": "final", "confidence": 0.93},
            ],
            "system_events": [
                {"event_id": "ev-1", "event_type": "call_start", "at_ms": 0},
                {"event_id": "ev-2", "event_type": "ai_disclosure", "at_ms": 200},
                {"event_id": "ev-3", "event_type": "call_end", "at_ms": 6000},
            ],
        }
        d.update(kw)
        return d

    # 1) happy — RECORD + 3 turn → TRANSCRIPT
    r = build(req(), spec)
    case("happy: TRANSCRIPT", r["terminal"] == "TRANSCRIPT")
    case("happy: segment_count=3", r["segment_count"] == 3)
    case("happy: timeline=3 seg + 3 olay=6", r["timeline_count"] == 6)
    case("happy: content_persisted=true", r["content_persisted"] is True)
    case("happy: no_content_persisted=false", r["no_content_persisted"] is False)
    case("happy: redaction_state=not_required", r["redaction_state"] == "not_required")
    case("happy: seq 1..3 bitişik", [s["seq"] for s in r["segments"]] == [1, 2, 3])
    case("happy: started_ms monoton artan",
         [s["started_ms"] for s in r["segments"]] == [1000, 2500, 4500])
    case("happy: konuşmacı atfı geçerli",
         all(s["speaker"] in VALID_SPEAKERS for s in r["segments"]))
    case("happy: ihlal yok", all(x == 0 for x in r["violations"].values()))
    case("happy: audit TRANSCRIPT (K10)", r["audit"] is not None and r["audit"]["result"] == "TRANSCRIPT")
    case("happy: kapı geçer", _gate_eval(r, G)[0] is True)

    # 1b) timeline zaman-sıralı (segment ⊕ olay birleşik)
    ats = [x["at_ms"] for x in r["timeline"]]
    case("happy: timeline monoton (0,200,1000,2500,4500,6000)", ats == sorted(ats))

    # 2) determinizm
    r1, r2 = build(req(), spec), build(req(), spec)
    case("determinizm: birebir", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))

    # 2b) girdi sırasız gelse de kanonik sıralanır
    rin = req(turn_events=[
        {"turn_id": "turn-3", "speaker": "caller", "start_ms": 4500, "kind": "final"},
        {"turn_id": "turn-1", "speaker": "caller", "start_ms": 1000, "kind": "final"},
        {"turn_id": "turn-2", "speaker": "agent", "start_ms": 2500, "kind": "final"},
    ])
    r = build(rin, spec)
    case("sırasız girdi: kanonik sıralı çıkış (1000,2500,4500)",
         [s["started_ms"] for s in r["segments"]] == [1000, 2500, 4500])
    case("sırasız girdi: ordering_violation=0", r["violations"]["ordering_violation"] == 0)

    # 3) MONO (channels=1) — atıf yine geçerli
    r = build(req(channels=1), spec)
    case("mono: TRANSCRIPT", r["terminal"] == "TRANSCRIPT")
    case("mono: ihlal yok", all(x == 0 for x in r["violations"].values()))

    # 3b) human (transfer) konuşmacısı geçerli
    r = build(req(turn_events=[
        {"turn_id": "turn-1", "speaker": "caller", "start_ms": 1000, "kind": "final"},
        {"turn_id": "turn-2", "speaker": "human", "start_ms": 2000, "kind": "final"},
    ], system_events=[{"event_id": "ev-1", "event_type": "transfer", "at_ms": 1500}]), spec)
    case("human-transfer: atıf geçerli + ihlal yok",
         r["terminal"] == "TRANSCRIPT" and all(x == 0 for x in r["violations"].values()))

    # 3c) boş çağrı (0 final turn) → TRANSCRIPT, 0 segment, timeline=olaylar
    r = build(req(turn_events=[]), spec)
    case("bos-cagri: TRANSCRIPT 0 segment", r["terminal"] == "TRANSCRIPT" and r["segment_count"] == 0)
    case("bos-cagri: timeline=3 olay", r["timeline_count"] == 3)
    case("bos-cagri: redaction_state not_required", r["redaction_state"] == "not_required")
    case("bos-cagri: ihlal yok", all(x == 0 for x in r["violations"].values()))

    # 4) K5 — 11.1 DISABLED → NO_TRANSCRIPT (no content)
    r = build(req(upstream_decision="DISABLED"), spec)
    case("upstream-disabled: NO_TRANSCRIPT", r["terminal"] == "NO_TRANSCRIPT")
    case("upstream-disabled: no_content_persisted=true", r["no_content_persisted"] is True)
    case("upstream-disabled: content_persisted=false", r["content_persisted"] is False)
    case("upstream-disabled: segment_count=0", r["segment_count"] == 0)
    case("upstream-disabled: kapı geçer (gizlilik-güvenli)", _gate_eval(r, G)[0] is True)

    # 4b) K5 — NO_CONSENT / BLOCK → NO_TRANSCRIPT
    for up in ("NO_CONSENT", "BLOCK"):
        rr = build(req(upstream_decision=up), spec)
        case("upstream-%s: NO_TRANSCRIPT + no content" % up,
             rr["terminal"] == "NO_TRANSCRIPT" and rr["no_content_persisted"] is True)

    # 5) redaction_required → pending
    r = build(req(redaction_required=True), spec)
    case("redaction-required: redaction_state=pending", r["redaction_state"] == "pending")
    case("redaction-required: kapı geçer", _gate_eval(r, G)[0] is True)
    # turn-bazlı redaction_required
    r = build(req(turn_events=[{"turn_id": "turn-1", "speaker": "caller", "start_ms": 1000, "kind": "final", "redaction_required": True}]), spec)
    case("redaction-turn: redaction_state=pending", r["redaction_state"] == "pending")

    # 6) no_upstream — upstream yok → BLOCK no_upstream
    r = build(req(upstream_decision=None), spec)
    case("no-upstream: BLOCK no_upstream", r["terminal"] == "BLOCK" and r["block_reason"] == "no_upstream")
    case("no-upstream: no content", r["no_content_persisted"] is True)

    # 7) K8 malformed turn (turn_id yok) → BLOCK invalid_turn_stream
    r = build(req(turn_events=[{"speaker": "caller", "start_ms": 1000, "kind": "final"}]), spec)
    case("malformed: BLOCK invalid_turn_stream",
         r["terminal"] == "BLOCK" and r["block_reason"] == "invalid_turn_stream")
    case("malformed: no content", r["no_content_persisted"] is True)
    case("malformed: kapı geçer (fail-closed)", _gate_eval(r, G)[0] is True)

    # 8) K8 skip_assembly — bypass: çözmeden içerik kalıcılaştır
    r = build(req(), spec, inject=["skip_assembly"])
    case("inject-skip: assembly_skip>0", r["violations"]["assembly_skip"] > 0)
    case("inject-skip: content_persisted=true (over)", r["content_persisted"] is True)
    case("inject-skip: kapı eler", _gate_eval(r, G)[0] is False)

    # 8b) K8 failopen_assembly — malformed turn'de sessiz içerik
    r = build(req(turn_events=[{"speaker": "caller", "start_ms": 1000, "kind": "final"}]), spec,
              inject=["failopen_assembly"])
    case("inject-failopen: failopen>0", r["violations"]["failopen"] > 0)
    case("inject-failopen: kapı eler", _gate_eval(r, G)[0] is False)

    # 9) K5 persist_when_not_authorized — DISABLED ama içerik kalıcılaştır
    r = build(req(upstream_decision="DISABLED"), spec, inject=["persist_when_not_authorized"])
    case("inject-overcapture: over_capture>0", r["violations"]["over_capture"] > 0)
    case("inject-overcapture: content_persisted=true", r["content_persisted"] is True)
    case("inject-overcapture: kapı eler", _gate_eval(r, G)[0] is False)

    # 10) K2 reorder_segments — kronoloji bozulması
    r = build(req(), spec, inject=["reorder_segments"])
    case("inject-reorder: ordering_violation>0", r["violations"]["ordering_violation"] > 0)
    case("inject-reorder: kapı eler", _gate_eval(r, G)[0] is False)

    # 10b) K2 seq_gap — seq bitişik değil
    r = build(req(), spec, inject=["seq_gap"])
    case("inject-seqgap: ordering_violation>0", r["violations"]["ordering_violation"] > 0)
    case("inject-seqgap: kapı eler", _gate_eval(r, G)[0] is False)

    # 11) K3 strip_speaker — atıfsız segment
    r = build(req(), spec, inject=["strip_speaker"])
    case("inject-strip: missing_speaker>0", r["violations"]["missing_speaker"] > 0)
    case("inject-strip: kapı eler", _gate_eval(r, G)[0] is False)

    # 11b) K3 misattribute_speaker — DUAL'da yanlış kanal atfı
    r = build(req(channels=2), spec, inject=["misattribute_speaker"])
    case("inject-misattr: speaker_mismatch>0", r["violations"]["speaker_mismatch"] > 0)
    case("inject-misattr: kapı eler", _gate_eval(r, G)[0] is False)

    # 12) K4 drop_turn — final turn düşer
    r = build(req(), spec, inject=["drop_turn"])
    case("inject-drop: turn_dropped>0", r["violations"]["turn_dropped"] > 0)
    case("inject-drop: kapı eler", _gate_eval(r, G)[0] is False)

    # 12b) K4 duplicate_turn — turn çoğalır
    r = build(req(), spec, inject=["duplicate_turn"])
    case("inject-dup: turn_duplicated>0", r["violations"]["turn_duplicated"] > 0)
    case("inject-dup: kapı eler", _gate_eval(r, G)[0] is False)

    # 12c) K4 drop_event — sistem olayı timeline'dan düşer
    r = build(req(), spec, inject=["drop_event"])
    case("inject-dropevent: event_dropped>0", r["violations"]["event_dropped"] > 0)
    case("inject-dropevent: kapı eler", _gate_eval(r, G)[0] is False)

    # 13) K7 premature_redaction — bu modül 'redacted' yayar
    r = build(req(), spec, inject=["premature_redaction"])
    case("inject-premature: premature_redaction>0", r["violations"]["premature_redaction"] > 0)
    case("inject-premature: redaction_state=redacted", r["redaction_state"] == "redacted")
    case("inject-premature: kapı eler", _gate_eval(r, G)[0] is False)

    # 14) K6 residency_leak — home-region dışı
    r = build(req(), spec, inject=["residency_leak"])
    case("inject-residency: residency_violation>0", r["violations"]["residency_violation"] > 0)
    case("inject-residency: kapı eler", _gate_eval(r, G)[0] is False)
    r = build(req(storage_region="TR"), spec)
    case("residency: storage=home(TR) → ihlal yok", r["violations"]["residency_violation"] == 0)

    # 15) K12 cross_tenant
    r = build(req(), spec, inject=["cross_tenant"])
    case("inject-cross-tenant: cross_tenant>0 + BLOCK",
         r["violations"]["cross_tenant"] > 0 and r["terminal"] == "BLOCK")
    r = build(req(bind_tenant="t-other"), spec)
    case("bind-mismatch: cross_tenant>0", r["violations"]["cross_tenant"] > 0)

    # 16) K10 no_audit
    r = build(req(), spec, inject=["no_audit"])
    case("inject-no-audit: missing_audit>0", r["violations"]["missing_audit"] > 0)
    case("inject-no-audit: audit None", r["audit"] is None)

    # 17) K5 GARANTİ — her terminal ∉ {TRANSCRIPT} ⇒ no_content_persisted=true
    for kw in (dict(upstream_decision="DISABLED"), dict(upstream_decision="NO_CONSENT"),
               dict(upstream_decision=None),
               dict(turn_events=[{"speaker": "caller", "start_ms": 1, "kind": "final"}])):
        rr = build(req(**kw), spec)
        if rr["terminal"] not in BUILT:
            case("K5 garanti: %s → no_content_persisted=true" % rr["terminal"],
                 rr["no_content_persisted"] is True)

    # 18) kanıt (K9) + audit (K10)
    r = build(req(), spec)
    case("evidence: request taşır", r["evidence"]["request_id"] == "req-1")
    case("evidence: upstream/authorized/segment_count/redaction_state taşır",
         all(k in r["evidence"] for k in ("upstream_decision", "authorized", "segment_count", "redaction_state")))
    case("audit: result/segment_count/tenant taşır",
         r["audit"]["result"] == "TRANSCRIPT" and r["audit"]["segment_count"] == 3 and r["audit"]["tenant_id"] == "t-acme")
    case("audit: ham transkript metni/telefon/ham-ses alanı yok",
         all(k not in json.dumps(r["audit"]) for k in ("transcript_text", "segment_text", "customer_phone_value", "raw_audio")))

    # 19) sızıntı tarayıcı
    case("leak: req-001 kimlik temiz", scan_leaks('{"request_id": "req-001"}') == [])
    case("leak: turn/enum/sayı temiz", scan_leaks('{"turn_id": "turn-001", "speaker": "caller", "seq": 2}') == [])
    case("leak: transcript_text alanı yakalanır", len(scan_leaks('{"transcript_text": "x"}')) > 0)
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
        "module": "transcript-build (WBS 11.3 — Transkript üretimi + timeline; BRD §8.1)",
        "outcomes": OUTCOMES,
        "terminal": sorted(TERMINAL),
        "built": sorted(BUILT),
        "rules": RULES,
        "block_reasons": BLOCK_REASONS,
        "valid_speakers": VALID_SPEAKERS,
        "valid_channels": VALID_CHANNELS,
        "decision": "tenant_check ⇒ BLOCK(cross_tenant) → upstream∉decisions ⇒ BLOCK(no_upstream) → "
                    "upstream!=RECORD ⇒ NO_TRANSCRIPT(no_content) → malformed_turn ⇒ BLOCK(invalid_turn_stream) "
                    "→ order(started_ms,turn_id)+seq → attribute(speaker∈{caller,agent,human}, DUAL kanal "
                    "tutarlı) → merge_timeline(segment⊕event) → redaction_state(pending|not_required) → "
                    "residency(home_region) ⇒ TRANSCRIPT",
        "default": "BLOCK (fail-closed)",
        "fail_safe": "terminal ∉ {TRANSCRIPT} ⇒ no_content_persisted = true (FR-REC-002 aşağı akış)",
        "producible_redaction_states": sorted(PRODUCIBLE_REDACTION),
        "forbidden_redaction_state_here": "redacted (11.4/11.5 üretir; premature_redaction K7)",
        "channel_side": {"caller": 0, "agent": 1, "human": 1},
        "request_fields": ["name", "request_id", "tenant_id", "correlation_id", "call_id",
                           "direction(inbound|outbound)", "upstream_decision(RECORD|DISABLED|NO_CONSENT|BLOCK)",
                           "channels(1|2)",
                           "turn_events[{turn_id, speaker(caller|agent|human), start_ms, end_ms, kind:final, confidence, channel?, redaction_required?}]",
                           "system_events[{event_id, event_type, at_ms}]", "redaction_required(bool)",
                           "in_region_storage_required(bool)", "storage_region", "home_region",
                           "bind_tenant", "config_override{}", "inject[]", "expect", "expected{}"],
        "injections (degrade testi)": sorted(INJECTIONS),
        "decision_fields": ["terminal", "channels", "segments", "timeline", "segment_count", "timeline_count",
                            "authorized", "redaction_state", "content_persisted", "no_content_persisted",
                            "storage_region", "home_region", "block_reason", "evidence", "audit"],
        "violations": VIOLATION_KEYS,
        "invariants": INVARIANT_IDS,
        "consumes": "11.1 recording-policy (upstream_decision içerik kapısı) + 11.2 channel-recording "
                    "(channels + konuşmacı-kanal) + SAD §6.1/§8.2 turn-event akışı (final transcript turn'ler)",
        "consumed_by": "SAD §10.2 Transcript Store + DB §21 (segment/timeline + storage_uri) + 11.4 redaction "
                       "(redaction_state=pending) + 11.6 erişim audit/görüntüleme + L2 A-12 panel",
        "trace": "BRD §8.1, FR-REC-008, SR-REC-008, TC-REC-008, FR-REC-001/002 (11.1), FR-REC-003 (11.2), "
                 "FR-REC-004/005, FR-IAM-006, FR-TEN-002, FR-RES-011, NFR 10.7, BRD §15, SAD §6.1, "
                 "SAD §10.2 Transcript Store, DB §21 transcript/segment, DB §23 call_event, ADR-001/002/012",
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
            print("kullanım: transcript_build_probe.py check <sample.json|dizin>")
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
