#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 11.1 — Kayıt politikası (tenant/ülke/use-case) + tamamen kapatma DAVRANIŞ testi (K1–K12).

selftest probe içi gömülü kontrolleri çalıştırır; bu dosya invariant'ları DIŞARIDAN, bağımsız
fixture'larla doğrular (11.x/10.2.x behavior deseniyle birebir). Stdlib-only; sunucu gerektirmez.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
sys.path.insert(0, MOD)

import recording_policy_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
G = SPEC["gates"]
RESULTS = []


def case(name, cond):
    RESULTS.append((bool(cond), name))


def req(**kw):
    # Varsayılan TR: recording_enabled=true, consent_model=notice, notice çalındı → RECORD.
    d = {
        "request_id": "req-b", "tenant_id": "t-acme", "correlation_id": "corr-b", "call_id": "call-b",
        "country": "TR", "use_case": "sales", "channel": "voice", "direction": "inbound",
        "consent_state": "granted", "all_party_consent": True, "recording_notice_played": True,
        "storage_region": "TR",
    }
    d.update(kw)
    return d


def gate(r):
    return P._gate_eval(r, G)[0]


def _mismatch(s, r):
    exp = s.get("expected", {})
    for k in ("terminal", "block_reason", "recording_allowed", "no_media_captured", "consent_model", "channels"):
        if k in exp and exp[k] != r.get(k):
            return True
    return False


# ── K1 determinizm/terminal ──────────────────────────────────────────────────
r1, r2 = P.build(req(), SPEC), P.build(req(), SPEC)
case("K1 determinizm: aynı girdi→aynı çıktı", r1 == r2)
case("K1 terminal: RECORD|DISABLED|NO_CONSENT|BLOCK", r1["terminal"] in P.TERMINAL)
case("K1 stuck_state=0", r1["violations"]["stuck_state"] == 0)
case("K1 sağlıklı TR → RECORD", P.build(req(), SPEC)["terminal"] == "RECORD")

# ── K2 üç-katman politika çözümü ÇEKİRDEK (FR-REC-001) ────────────────────────
case("K2 ülke TR notice → consent_model=notice", P.build(req(), SPEC)["consent_model"] == "notice")
case("K2 use-case collections sıkılaştırır → explicit_optin",
     P.build(req(use_case="collections"), SPEC)["consent_model"] == "explicit_optin")
case("K2 tenant override en katı → all_party",
     P.build(req(tenant_override={"consent_model": "all_party"}, all_party_consent=True), SPEC)["consent_model"] == "all_party")
iu = P.build(req(use_case="internal_test"), SPEC, inject=["ignore_usecase"])
case("K2 inject ignore_usecase → policy_resolution_error>0", iu["violations"]["policy_resolution_error"] > 0)
case("K2 inject ignore_usecase → yanlış RECORD", iu["terminal"] == "RECORD")
case("K2 inject ignore_usecase → kapı ELER", gate(iu) is False)
it = P.build(req(tenant_override={"recording_enabled": False}), SPEC, inject=["ignore_tenant_override"])
case("K2 inject ignore_tenant_override → policy_resolution_error>0", it["violations"]["policy_resolution_error"] > 0)

# ── K3 tamamen kapatma ÇEKİRDEK (FR-REC-002) ─────────────────────────────────
case("K3 tenant disable → DISABLED",
     P.build(req(tenant_override={"recording_enabled": False}), SPEC)["terminal"] == "DISABLED")
case("K3 tenant disable → no_media_captured=true",
     P.build(req(tenant_override={"recording_enabled": False}), SPEC)["no_media_captured"] is True)
case("K3 use-case disable (legal_privileged) → DISABLED",
     P.build(req(use_case="legal_privileged"), SPEC)["terminal"] == "DISABLED")
rd = P.build(req(tenant_override={"recording_enabled": False}), SPEC, inject=["record_while_disabled"])
case("K3 inject record_while_disabled → recorded_while_disabled>0", rd["violations"]["recorded_while_disabled"] > 0)
case("K3 inject record_while_disabled → kapı ELER", gate(rd) is False)

# ── K4 kayıt-başlatma consent kapısı ÇEKİRDEK ────────────────────────────────
case("K4 notice çalınmadı → NO_CONSENT", P.build(req(recording_notice_played=False), SPEC)["terminal"] == "NO_CONSENT")
case("K4 EU explicit denied → NO_CONSENT",
     P.build(req(country="EU", profile_id="PROFILE-EU", consent_state="denied"), SPEC)["terminal"] == "NO_CONSENT")
case("K4 US all_party bir taraf yok → NO_CONSENT",
     P.build(req(country="US", profile_id="PROFILE-US-CALL", all_party_consent=False), SPEC)["terminal"] == "NO_CONSENT")
rc = P.build(req(country="EU", profile_id="PROFILE-EU", consent_state="denied"), SPEC, inject=["record_without_consent"])
case("K4 inject record_without_consent → recorded_without_consent>0", rc["violations"]["recorded_without_consent"] > 0)
case("K4 inject record_without_consent → kapı ELER", gate(rc) is False)
lc = P.build(req(country="US", profile_id="PROFILE-US-CALL", all_party_consent=False), SPEC, inject=["loosen_consent_model"])
case("K4 inject loosen_consent_model → consent_model_loosened>0", lc["violations"]["consent_model_loosened"] > 0)
case("K4 inject loosen_consent_model → kapı ELER", gate(lc) is False)

# ── K5 kapalıyken medya yok ÇEKİRDEK (SR-REC-002) ────────────────────────────
for kw, label in ((dict(recording_notice_played=False), "NO_CONSENT"),
                  (dict(tenant_override={"recording_enabled": False}), "DISABLED"),
                  (dict(country="ZZ"), "BLOCK")):
    rr = P.build(req(**kw), SPEC)
    case("K5 %s → no_media_captured=true" % label, rr["terminal"] != "RECORD" and rr["no_media_captured"] is True)
mb = P.build(req(country="ZZ"), SPEC, inject=["record_on_block"])
case("K5 inject record_on_block → media_when_off>0", mb["violations"]["media_when_off"] > 0)
case("K5 inject record_on_block → kapı ELER", gate(mb) is False)

# ── K6 residency korunur (NFR 10.7) ──────────────────────────────────────────
case("K6 TR storage=home(TR) → ihlal yok", P.build(req(storage_region="TR"), SPEC)["violations"]["residency_violation"] == 0)
rl = P.build(req(), SPEC, inject=["residency_leak"])
case("K6 inject residency_leak → residency_violation>0", rl["violations"]["residency_violation"] > 0)
case("K6 inject residency_leak → kapı ELER", gate(rl) is False)

# ── K7 fail-closed bilinmeyen profil (privacy-safe NO-RECORD) ────────────────
zz = P.build(req(country="ZZ"), SPEC)
case("K7 bilinmeyen ülke → BLOCK unknown_profile", zz["terminal"] == "BLOCK" and zz["block_reason"] == "unknown_profile")
case("K7 bilinmeyen ülke → no_media_captured=true", zz["no_media_captured"] is True)
fo = P.build(req(country="ZZ"), SPEC, inject=["failopen_profile"])
case("K7 inject failopen_profile → failopen>0", fo["violations"]["failopen"] > 0)
case("K7 inject failopen_profile → kapı ELER", gate(fo) is False)

# ── K8 fail-closed / ATLANAMAZ ───────────────────────────────────────────────
sk = P.build(req(), SPEC, inject=["skip_policy"])
case("K8 inject skip_policy → policy_skip>0", sk["violations"]["policy_skip"] > 0)
case("K8 inject skip_policy → over-capture (no_media=false)", sk["no_media_captured"] is False)
case("K8 inject skip_policy → kapı ELER", gate(sk) is False)

# ── K9 kanıt ─────────────────────────────────────────────────────────────────
ev = P.build(req(), SPEC)["evidence"]
case("K9 kanıt request taşır", ev["request_id"] == "req-b")
case("K9 kanıt effective/consent_gate/no_media taşır",
     all(k in ev for k in ("effective", "consent_gate_ok", "no_media_captured")))
case("K9 missing_evidence=0", P.build(req(), SPEC)["violations"]["missing_evidence"] == 0)

# ── K10 audit ────────────────────────────────────────────────────────────────
au = P.build(req(), SPEC)["audit"]
case("K10 audit result/country/tenant taşır",
     au["result"] == "RECORD" and au["country"] == "TR" and au["tenant_id"] == "t-acme")
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
case("K12 leak: kimlik/enum temiz", P.scan_leaks('{"call_id": "call-001", "consent_model": "notice"}') == [])

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
    case("≥12 pass örnek", pass_n >= 12)
    case("≥11 degrade örnek", fail_n >= 11)


npass = sum(1 for ok, _ in RESULTS if ok)
for ok, name in RESULTS:
    print(("  ✓ " if ok else "  ✗ ") + name)
print("\nbehavior: %d/%d %s" % (npass, len(RESULTS), "🟢" if npass == len(RESULTS) else "🔴"))
sys.exit(0 if npass == len(RESULTS) else 1)
