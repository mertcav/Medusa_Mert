#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 9.7 — Temsilci yoksa callback/voicemail/ticket davranış kapısı (K1–K12).

Probe'un selftest'inden BAĞIMSIZ, kara-kutu davranış kontrolleri: fallback sunum/seçim motorunun
sözleşmesini (FR-HND-007) doğrudan doğrular. Stdlib-only, bağımlılıksız.
Çalıştırma: python3 tests/no_agent_fallback_behavior_test.py  → çıkış kodu.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import no_agent_fallback_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)


def _req(**kw):
    d = {
        "tenant_id": "t", "correlation_id": "c", "call_id": "call-x",
        "reason": "no_agent_available",
        "consent": {"callback": True, "recording": True},
        "ai_disclosure": True,
        "business_hours": True,
        "channel_availability": {"callback": True, "voicemail": True, "ticket": True},
        "callback_window": "window-morning",
        "context_ref": "ctx-call-x",
        "customer_choice": "callback",
    }
    d.update(kw)
    return d


def run():
    cases = []

    def check(name, cond):
        cases.append((bool(cond), name))

    # K1 — her istek terminal'e ulaşır (FULFILLED|SAFE_CLOSE)
    for ch in ("callback", "voicemail", "ticket", "decline"):
        r = P.build(_req(customer_choice=ch), SPEC)
        check("K1 terminal (%s): %s" % (ch, r["terminal"]), r["terminal"] in P.TERMINAL)

    # K2 — temsilci yokken daima en az bir alternatif sunulur
    r = P.build(_req(), SPEC)
    check("K2 en az bir seçenek sunuldu", r["offered_count"] >= 1)
    check("K2 no_offer=0", r["violations"]["no_offer"] == 0)
    r = P.build(_req(), SPEC, inject=["no_offer"])
    check("K2 inject no_offer yakalanır", r["violations"]["no_offer"] > 0)

    # K3 — son çare (ticket) daima uygun; callback/voicemail kapalı olsa bile
    r = P.build(_req(channel_availability={"callback": False, "voicemail": False, "ticket": True},
                     customer_choice="ticket"), SPEC)
    check("K3 ticket son çare uygun kümede", "ticket" in r["eligible"])
    check("K3 empty_eligible=0", r["violations"]["empty_eligible"] == 0)
    r = P.build(_req(channel_availability={"callback": False, "voicemail": False, "ticket": True},
                     customer_choice="ticket"), SPEC, inject=["drop_last_resort"])
    check("K3 inject drop_last_resort → empty_eligible yakalanır", r["violations"]["empty_eligible"] > 0)

    # K4 — karşılanan seçenek uygun olmalı
    r = P.build(_req(), SPEC)
    check("K4 unmet_prerequisite=0", r["violations"]["unmet_prerequisite"] == 0)
    r = P.build(_req(channel_availability={"callback": False, "voicemail": True, "ticket": True},
                     customer_choice="callback"), SPEC, inject=["unmet_prerequisite"])
    check("K4 inject unmet_prerequisite yakalanır", r["violations"]["unmet_prerequisite"] > 0)

    # K5 — onay + AI ifşası; onaysız/ifşasız kayıt yok
    r = P.build(_req(customer_choice="voicemail"), SPEC)
    check("K5 voicemail onaylı+ifşalı: missing_consent=0", r["violations"]["missing_consent"] == 0)
    check("K5 voicemail onaylı+ifşalı: no_disclosure=0", r["violations"]["no_disclosure"] == 0)
    r = P.build(_req(customer_choice="voicemail"), SPEC, inject=["skip_consent"])
    check("K5 inject skip_consent → missing_consent yakalanır", r["violations"]["missing_consent"] > 0)
    check("K5 inject skip_consent → no_disclosure yakalanır", r["violations"]["no_disclosure"] > 0)

    # K6 — geçerli no-agent tetiği; agent_available fallback tetiklemez
    r = P.build(_req(), SPEC)
    check("K6 geçerli neden: invalid_trigger=0", r["violations"]["invalid_trigger"] == 0)
    r = P.build(_req(reason="agent_available"), SPEC)
    check("K6 agent_available → invalid_trigger yakalanır", r["violations"]["invalid_trigger"] > 0)

    # K7 — tenant izolasyonu; cross-tenant yok
    r = P.build(_req(), SPEC)
    check("K7 cross_tenant=0", r["violations"]["cross_tenant"] == 0)
    r = P.build(_req(), SPEC, inject=["cross_tenant"])
    check("K7 inject cross_tenant yakalanır", r["violations"]["cross_tenant"] > 0)

    # K8 — fail-safe minimum: red → oto-ticket, asla sessiz düşme
    r = P.build(_req(customer_choice="decline"), SPEC)
    check("K8 decline → SAFE_CLOSE", r["terminal"] == "SAFE_CLOSE")
    check("K8 decline → oto-ticket (failsafe)", r["failsafe"] is True and r["outcome_type"] == "ticket")
    check("K8 decline ihlal değil (fail-safe geçerli)", all(v == 0 for v in r["violations"].values()))
    r = P.build(_req(customer_choice="decline"), SPEC, inject=["silent_drop"])
    check("K8 inject silent_drop yakalanır", r["violations"]["silent_drop"] > 0)
    check("K8 silent_drop → oto-ticket yok", r["outcome_type"] is None)

    # K9 — her fallback kanıt taşır (neden + sunulan + seçilen + referans)
    r = P.build(_req(), SPEC)
    check("K9 evidence reason taşır", r["evidence"]["reason"] == "no_agent_available")
    check("K9 evidence offered_options taşır", len(r["evidence"]["offered_options"]) >= 1)
    check("K9 evidence reference_id taşır", r["evidence"]["reference_id"] is not None)
    check("K9 missing_evidence=0", r["violations"]["missing_evidence"] == 0)

    # K10 — her sonuç audit'e yazılır
    r = P.build(_req(), SPEC)
    check("K10 audit type taşır", r["audit"] is not None and r["audit"]["type"] == "callback")
    check("K10 audit tenant taşır", r["audit"]["tenant_id"] == "t")
    check("K10 audit reason taşır", r["audit"]["reason"] == "no_agent_available")
    r = P.build(_req(), SPEC, inject=["no_audit"])
    check("K10 inject no_audit → missing_audit", r["violations"]["missing_audit"] > 0)

    # K11/K12 — sızıntı tarayıcı: yapısal/referans temiz, ham PII/telefon yakalanır
    check("K12 cb-001 referans temiz", P.scan_leaks('{"reference_id": "cb-001"}') == [])
    check("K12 ham telefon alanı yakalanır", len(P.scan_leaks('{"customer_phone_value": "x"}')) > 0)

    npass = sum(1 for ok, _ in cases if ok)
    for ok, name in cases:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print("\nbehavior: %d/%d %s" % (npass, len(cases), "🟢" if npass == len(cases) else "🔴"))
    return 0 if npass == len(cases) else 1


if __name__ == "__main__":
    sys.exit(run())
