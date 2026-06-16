#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 11.2 — Tek/çift kanallı kayıt DAVRANIŞ testi (K1–K12).

selftest probe içi gömülü kontrolleri çalıştırır; bu dosya invariant'ları DIŞARIDAN, bağımsız
fixture'larla doğrular (11.1/10.2.x behavior deseniyle birebir). Stdlib-only; sunucu gerektirmez.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
sys.path.insert(0, MOD)

import channel_recording_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
G = SPEC["gates"]
RESULTS = []


def case(name, cond):
    RESULTS.append((bool(cond), name))


def req(**kw):
    # Varsayılan: 11.1 RECORD + channels=2 (DUAL) + caller+agent bacak; storage=home(TR) → DUAL.
    d = {
        "request_id": "req-b", "tenant_id": "t-acme", "correlation_id": "corr-b", "call_id": "call-b",
        "direction": "inbound", "upstream_decision": "RECORD", "upstream_no_media_captured": False,
        "channels": 2, "media_legs": ["caller", "agent"], "in_region_storage_required": True,
        "storage_region": "TR", "home_region": "TR",
    }
    d.update(kw)
    return d


def gate(r):
    return P._gate_eval(r, G)[0]


def _mismatch(s, r):
    exp = s.get("expected", {})
    for k in ("terminal", "block_reason", "mode", "channels", "track_count",
              "recording_written", "no_media_captured"):
        if k in exp and exp[k] != r.get(k):
            return True
    return False


# ── K1 determinizm/terminal ──────────────────────────────────────────────────
r1, r2 = P.build(req(), SPEC), P.build(req(), SPEC)
case("K1 determinizm: aynı girdi→aynı çıktı", r1 == r2)
case("K1 terminal: MONO|DUAL|NO_RECORD|BLOCK", r1["terminal"] in P.TERMINAL)
case("K1 stuck_state=0", r1["violations"]["stuck_state"] == 0)
case("K1 sağlıklı RECORD+ch2 → DUAL", P.build(req(), SPEC)["terminal"] == "DUAL")

# ── K2 kanal modu üretimi ÇEKİRDEK (FR-REC-003) ──────────────────────────────
case("K2 channels=2 → DUAL (2 track)",
     P.build(req(channels=2), SPEC)["track_count"] == 2)
case("K2 channels=1 → MONO (1 track)",
     P.build(req(channels=1), SPEC)["track_count"] == 1)
case("K2 channels=3 (∉{1,2}) → BLOCK invalid_channel_count",
     P.build(req(channels=3), SPEC)["block_reason"] == "invalid_channel_count")
il = P.build(req(), SPEC, inject=["invalid_channel_count"])
case("K2 inject invalid_channel_count → invalid_layout>0", il["violations"]["invalid_layout"] > 0)
case("K2 inject invalid_channel_count → kapı ELER", gate(il) is False)
case("K2 track sayısı == channels (DUAL)",
     P.build(req(channels=2), SPEC)["track_count"] == 2)

# ── K3 DUAL ayrışma ÇEKİRDEK (FR-REC-003 çift kanal) ─────────────────────────
d = P.build(req(channels=2), SPEC)
case("K3 caller → ch0", d["tracks"][0]["legs"] == ["caller"])
case("K3 agent → ch1", d["tracks"][1]["legs"] == ["agent"])
dh = P.build(req(channels=2, media_legs=["caller", "agent", "human"]), SPEC)
case("K3 human (transfer) → ch1 (agent tarafı)", set(dh["tracks"][1]["legs"]) == {"agent", "human"})
mx = P.build(req(channels=2), SPEC, inject=["mix_in_dual"])
case("K3 inject mix_in_dual → dual_not_separated>0", mx["violations"]["dual_not_separated"] > 0)
case("K3 inject mix_in_dual → kapı ELER", gate(mx) is False)
wb = P.build(req(channels=2), SPEC, inject=["wrong_channel_binding"])
case("K3 inject wrong_channel_binding → binding_error>0", wb["violations"]["binding_error"] > 0)
case("K3 inject wrong_channel_binding → kapı ELER", gate(wb) is False)
ec = P.build(req(channels=2), SPEC, inject=["empty_channel"])
case("K3 inject empty_channel → empty_channel>0", ec["violations"]["empty_channel"] > 0)
case("K3 inject empty_channel → kapı ELER", gate(ec) is False)

# ── K4 MONO tamlık ÇEKİRDEK (FR-REC-003 tek kanal) ───────────────────────────
m3 = P.build(req(channels=1, media_legs=["caller", "agent", "human"]), SPEC)
case("K4 MONO üç bacak tek track'e", set(m3["tracks"][0]["legs"]) == {"caller", "agent", "human"})
case("K4 MONO leg_dropped=0", m3["violations"]["leg_dropped"] == 0)
dl = P.build(req(channels=1, media_legs=["caller", "agent"]), SPEC, inject=["drop_leg_in_mono"])
case("K4 inject drop_leg_in_mono → leg_dropped>0", dl["violations"]["leg_dropped"] > 0)
case("K4 inject drop_leg_in_mono → kapı ELER", gate(dl) is False)

# ── K5 yalnız-yetkiliyken-kayıt ÇEKİRDEK (FR-REC-002/SR-REC-002 aşağı akış) ───
for up in ("DISABLED", "NO_CONSENT", "BLOCK"):
    rr = P.build(req(upstream_decision=up, upstream_no_media_captured=True), SPEC)
    case("K5 11.1 %s → NO_RECORD + no media" % up,
         rr["terminal"] == "NO_RECORD" and rr["no_media_captured"] is True and rr["recording_written"] is False)
oc = P.build(req(upstream_decision="DISABLED", upstream_no_media_captured=True), SPEC,
             inject=["record_when_not_authorized"])
case("K5 inject record_when_not_authorized → over_capture>0", oc["violations"]["over_capture"] > 0)
case("K5 inject record_when_not_authorized → kapı ELER", gate(oc) is False)

# ── K6 residency korunur (NFR 10.7) ──────────────────────────────────────────
case("K6 storage=home(TR) → ihlal yok", P.build(req(storage_region="TR"), SPEC)["violations"]["residency_violation"] == 0)
rl = P.build(req(), SPEC, inject=["residency_leak"])
case("K6 inject residency_leak → residency_violation>0", rl["violations"]["residency_violation"] > 0)
case("K6 inject residency_leak → kapı ELER", gate(rl) is False)

# ── K7 fail-closed geçersiz kanal (sessiz varsayılan yok) ────────────────────
iv = P.build(req(channels=3), SPEC)
case("K7 geçersiz kanal → BLOCK invalid_channel_count", iv["terminal"] == "BLOCK" and iv["block_reason"] == "invalid_channel_count")
case("K7 geçersiz kanal → no_media_captured=true", iv["no_media_captured"] is True)
fo = P.build(req(channels=3), SPEC, inject=["failopen_layout"])
case("K7 inject failopen_layout → failopen>0", fo["violations"]["failopen"] > 0)
case("K7 inject failopen_layout → kapı ELER", gate(fo) is False)

# ── K8 fail-closed / ATLANAMAZ ───────────────────────────────────────────────
sk = P.build(req(), SPEC, inject=["skip_layout"])
case("K8 inject skip_layout → layout_skip>0", sk["violations"]["layout_skip"] > 0)
case("K8 inject skip_layout → over-capture (no_media=false)", sk["no_media_captured"] is False)
case("K8 inject skip_layout → kapı ELER", gate(sk) is False)

# ── K9 kanıt ─────────────────────────────────────────────────────────────────
ev = P.build(req(), SPEC)["evidence"]
case("K9 kanıt request taşır", ev["request_id"] == "req-b")
case("K9 kanıt upstream/authorized/tracks taşır",
     all(k in ev for k in ("upstream_decision", "authorized", "tracks")))
case("K9 missing_evidence=0", P.build(req(), SPEC)["violations"]["missing_evidence"] == 0)

# ── K10 audit ────────────────────────────────────────────────────────────────
au = P.build(req(), SPEC)["audit"]
case("K10 audit result/channels/tenant taşır",
     au["result"] == "DUAL" and au["channels"] == 2 and au["tenant_id"] == "t-acme")
na = P.build(req(), SPEC, inject=["no_audit"])
case("K10 inject no_audit → missing_audit>0", na["violations"]["missing_audit"] > 0)
case("K10 inject no_audit → audit None", na["audit"] is None)

# ── K11 audit ham PII taşımaz ────────────────────────────────────────────────
case("K11 audit telefon/ad/ham-ses yok",
     all(k not in json.dumps(au) for k in ("customer_phone_value", "customer_name", "raw_audio")))

# ── K12 sır/PII yok + tenant izolasyonu ──────────────────────────────────────
ct = P.build(req(), SPEC, inject=["cross_tenant"])
case("K12 inject cross_tenant → cross_tenant>0 + BLOCK", ct["violations"]["cross_tenant"] > 0 and ct["terminal"] == "BLOCK")
bm = P.build(req(bind_tenant="t-other"), SPEC)
case("K12 bind mismatch → cross_tenant>0 + kapı ELER", bm["violations"]["cross_tenant"] > 0 and gate(bm) is False)
case("K12 leak: ham telefon yakalanır", len(P.scan_leaks('{"x": "905551234567"}')) > 0)
case("K12 leak: kimlik/enum temiz", P.scan_leaks('{"call_id": "call-001", "mode": "DUAL"}') == [])

# ── Pass/degrade örnek bütünlüğü ─────────────────────────────────────────────
if os.path.isdir(P.SAMPLES_DIR):
    pass_n = fail_n = 0
    for f in sorted(os.listdir(P.SAMPLES_DIR)):
        if not f.endswith(".json"):
            continue
        s = P._load(os.path.join(P.SAMPLES_DIR, f))
        r = P.build(s, SPEC)
        ok = gate(r)
        if s.get("expect", "pass") == "pass":
            pass_n += 1
            case("örnek pass beklenen geçer: %s" % f, ok and not _mismatch(s, r))
        else:
            fail_n += 1
            case("örnek degrade beklenen eler: %s" % f, not ok)
    case("≥11 pass örnek", pass_n >= 11)
    case("≥11 degrade örnek", fail_n >= 11)


npass = sum(1 for ok, _ in RESULTS if ok)
for ok, name in RESULTS:
    print(("  ✓ " if ok else "  ✗ ") + name)
print("\nbehavior: %d/%d %s" % (npass, len(RESULTS), "🟢" if npass == len(RESULTS) else "🔴"))
sys.exit(0 if npass == len(RESULTS) else 1)
