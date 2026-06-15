#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 10.2.5 — İYS/ETK (TR) + PECR/Ofcom (UK) profil parametreleri DAVRANIŞ testi (P1–P12).

selftest probe içi gömülü kontrolleri çalıştırır; bu dosya invariant'ları DIŞARIDAN, bağımsız
fixture'larla doğrular (10.2.x behavior deseniyle birebir). Stdlib-only; sunucu gerektirmez.
"""
import copy
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
sys.path.insert(0, MOD)

import regulatory_profiles_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
G = SPEC["gates"]
RESULTS = []


def case(name, cond):
    RESULTS.append((bool(cond), name))


def req(**kw):
    d = {"request_id": "req-b", "tenant_id": "t-acme", "correlation_id": "corr-b", "profile_id": "PROFILE-TR"}
    d.update(kw)
    return d


def gate(r):
    return P._gate_eval(r, G)[0]


# ── P1 determinizm/tamlık ─────────────────────────────────────────────────────
r1, r2 = P.build(req(), SPEC), P.build(req(), SPEC)
case("P1 determinizm: aynı girdi→aynı çıktı", r1 == r2)
case("P1 terminal: COMPLIANT|VIOLATION", r1["terminal"] in P.TERMINAL)
case("P1 happy TR tam → COMPLIANT", r1["terminal"] == "COMPLIANT")
case("P1 bilinmeyen ülke → incomplete_profile", P.build(req(profile_id=None, country="ZZ"), SPEC)["violations"]["incomplete_profile"] > 0)

# ── P2 İYS zorunlu (TR) ───────────────────────────────────────────────────────
case("P2 TR İYS ok", P.build(req(), SPEC)["obligations"].get("iys_registry") == "ok")
case("P2 drop_iys → iys_registry_missing", P.build(req(), SPEC, inject=["drop_iys"])["violations"]["iys_registry_missing"] > 0)
case("P2 drop_iys → kapı eler", gate(P.build(req(), SPEC, inject=["drop_iys"])) is False)

# ── P3 ETK opt_in + B2B-dahil (TR) ────────────────────────────────────────────
case("P3 TR ETK ok", P.build(req(), SPEC)["obligations"].get("etk_optin_b2b") == "ok")
case("P3 b2b muafiyet aç → etk_b2b_loosened", P.build(req(), SPEC, inject=["etk_b2b_exempt"])["violations"]["etk_b2b_loosened"] > 0)
case("P3 opt_out → etk_b2b_loosened", P.build(req(), SPEC, inject=["tr_optout"])["violations"]["etk_b2b_loosened"] > 0)

# ── P4 PECR soft-opt-in (UK) ──────────────────────────────────────────────────
case("P4 UK PECR ok", P.build(req(profile_id="PROFILE-UK"), SPEC)["obligations"].get("pecr_soft_optin") == "ok")
case("P4 pecr_to_optout → pecr_model_violated", P.build(req(profile_id="PROFILE-UK"), SPEC, inject=["pecr_to_optout"])["violations"]["pecr_model_violated"] > 0)

# ── P5 PECR/Ofcom TPS-CTPS (UK) ───────────────────────────────────────────────
case("P5 UK TPS_CTPS ok", P.build(req(profile_id="PROFILE-UK"), SPEC)["obligations"].get("pecr_tps_ctps") == "ok")
case("P5 drop_tps_ctps → pecr_registry_missing", P.build(req(profile_id="PROFILE-UK"), SPEC, inject=["drop_tps_ctps"])["violations"]["pecr_registry_missing"] > 0)

# ── P6 Ofcom abandoned ≤%3 (UK) ───────────────────────────────────────────────
case("P6 UK abandon ok (≤%3)", P.build(req(profile_id="PROFILE-UK"), SPEC)["obligations"].get("ofcom_abandon") == "ok")
case("P6 raise_abandon → ofcom_abandon_exceeded", P.build(req(profile_id="PROFILE-UK"), SPEC, inject=["raise_abandon"])["violations"]["ofcom_abandon_exceeded"] > 0)

# ── P7 Ofcom CLI (UK) ─────────────────────────────────────────────────────────
case("P7 UK CLI ok", P.build(req(profile_id="PROFILE-UK"), SPEC)["obligations"].get("ofcom_cli") == "ok")
case("P7 drop_cli → ofcom_cli_missing", P.build(req(profile_id="PROFILE-UK"), SPEC, inject=["drop_cli"])["violations"]["ofcom_cli_missing"] > 0)

# ── P8 Ofcom bilgilendirme ≤2sn (UK) ──────────────────────────────────────────
case("P8 UK info ≤2sn ok", P.build(req(profile_id="PROFILE-UK"), SPEC)["obligations"].get("ofcom_info_message") == "ok")
case("P8 drop_info_message → ofcom_info_message_missing", P.build(req(profile_id="PROFILE-UK"), SPEC, inject=["drop_info_message"])["violations"]["ofcom_info_message_missing"] > 0)

# ── P9 düzenleyici köken (provenance) ─────────────────────────────────────────
case("P9 happy provenance var", P.build(req(), SPEC)["violations"]["missing_provenance"] == 0)
case("P9 drop_provenance → missing_provenance", P.build(req(), SPEC, inject=["drop_provenance"])["violations"]["missing_provenance"] > 0)

# ── P10 tüketici sürüklenme denetimi (crosscheck) ─────────────────────────────
cc = P.crosscheck(SPEC)
case("P10 canlı tüketici drift=0", cc["drift_detected"] == 0)
case("P10 TR/UK × 4 modül kontrol (≥16 alan)", cc["checked"] >= 16)
cfg = P._load(P.CONFIG_PATH)
hours_cfg = P._load(os.path.join(P.REPO_ROOT, cfg["consumer_modules"]["calling_hours"]))
t = copy.deepcopy(hours_cfg)
t["profiles"]["PROFILE-TR"]["allowed_window"] = {"start": "06:00", "end": "23:00"}  # pencere drift
case("P10 tampered TR pencere → drift>0", P.crosscheck(SPEC, cfg, consumer_data={"calling_hours": t})["drift_detected"] > 0)
dnc_cfg = P._load(os.path.join(P.REPO_ROOT, cfg["consumer_modules"]["dnc"]))
t2 = copy.deepcopy(dnc_cfg)
t2["profiles"]["PROFILE-UK"]["registry"] = "none"  # UK registry drift
case("P10 tampered UK DNC registry → drift>0", P.crosscheck(SPEC, cfg, consumer_data={"dnc": t2})["drift_detected"] > 0)

# ── P11 tenant override yalnız-sıkılaştırır ───────────────────────────────────
case("P11 threshold tighten ok", P.build(req(tenant_override={"silent_call_threshold": 0.02}), SPEC)["violations"]["override_loosened"] == 0)
case("P11 threshold loosen → override_loosened", P.build(req(tenant_override={"silent_call_threshold": 0.05}), SPEC)["violations"]["override_loosened"] > 0)
case("P11 model tighten ok (UK soft→opt_in)", P.build(req(profile_id="PROFILE-UK", tenant_override={"consent_model": "opt_in"}), SPEC)["violations"]["override_loosened"] == 0)
case("P11 model loosen → override_loosened", P.build(req(tenant_override={"consent_model": "opt_out"}), SPEC)["violations"]["override_loosened"] > 0)
case("P11 b2b tighten ok (UK true→false)", P.build(req(profile_id="PROFILE-UK", tenant_override={"b2b_exemption": False}), SPEC)["violations"]["override_loosened"] == 0)
case("P11 b2b loosen → override_loosened (TR false→true)", P.build(req(tenant_override={"b2b_exemption": True}), SPEC)["violations"]["override_loosened"] > 0)
case("P11 window narrow ok", P.build(req(profile_id="PROFILE-UK", tenant_override={"allowed_window": {"start": "09:00", "end": "19:00"}}), SPEC)["violations"]["override_loosened"] == 0)
case("P11 window widen → override_loosened", P.build(req(profile_id="PROFILE-UK", tenant_override={"allowed_window": {"start": "07:00", "end": "22:00"}}), SPEC)["violations"]["override_loosened"] > 0)
case("P11 weekday subset ok", P.build(req(tenant_override={"allowed_weekdays": [0, 1, 2, 3, 4]}), SPEC)["violations"]["override_loosened"] == 0)
case("P11 weekday widen → override_loosened", P.build(req(tenant_override={"allowed_weekdays": [0, 1, 2, 3, 4, 5, 6]}), SPEC)["violations"]["override_loosened"] > 0)

# ── P12 sır/PII yok + audit + tenant izolasyonu ───────────────────────────────
case("P12 happy audit üretildi", P.build(req(), SPEC)["audit"] is not None)
case("P12 audit ham PII yok", "customer_phone_value" not in str(P.build(req(), SPEC)["audit"]) and "msisdn" not in str(P.build(req(), SPEC)["audit"]))
case("P12 no_audit → missing_audit + kapı eler", P.build(req(), SPEC, inject=["no_audit"])["violations"]["missing_audit"] > 0 and gate(P.build(req(), SPEC, inject=["no_audit"])) is False)
case("P12 cross_tenant inject", P.build(req(), SPEC, inject=["cross_tenant"])["violations"]["cross_tenant"] > 0)
case("P12 bind mismatch → cross_tenant", P.build(req(bind_tenant="t-other"), SPEC)["violations"]["cross_tenant"] > 0)
case("P12 spec/config sızıntısız", P.scan_leaks(open(P.SPEC_PATH, encoding="utf-8").read()) == [] and P.scan_leaks(open(P.CONFIG_PATH, encoding="utf-8").read()) == [])

npass = sum(1 for ok, _ in RESULTS if ok)
for ok, name in RESULTS:
    print(("  ✓ " if ok else "  ✗ ") + name)
print("\nbehavior: %d/%d %s" % (npass, len(RESULTS), "🟢" if npass == len(RESULTS) else "🔴"))
sys.exit(0 if npass == len(RESULTS) else 1)
