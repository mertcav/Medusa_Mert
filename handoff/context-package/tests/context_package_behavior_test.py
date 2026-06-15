#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 9.6 — Bağlam paketi + screen-pop davranış kapısı (P1–P12).

Probe'un selftest'inden BAĞIMSIZ, kara-kutu davranış kontrolleri: bağlam paketi derleyicisinin
teslim sözleşmesini (FR-HND-004/FR-HND-005) doğrudan doğrular. Stdlib-only, bağımlılıksız.
Çalıştırma: python3 tests/context_package_behavior_test.py  → çıkış kodu.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import context_package_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)


def _ctx(**kw):
    d = {
        "tenant_id": "t", "correlation_id": "c", "call_id": "call-x",
        "target": {"department": "billing", "skill_group": "sg-billing-tr",
                   "queue": "q-billing-tr", "deliver_to": "q-billing-tr", "match_quality": "exact"},
        "session": {
            "summary": "s-ref", "intent": "billing_dispute",
            "collected_fields": [
                {"name": "order_id", "sensitive": False, "value_token": "tok-o"},
                {"name": "account_number", "sensitive": True, "masked_value": "****-4321"},
            ],
            "auth": {"level": "verified", "methods": ["otp"], "step_up": "completed",
                     "secrets_present_in_session": ["otp_code"]},
        },
    }
    d.update(kw)
    return d


def run():
    cases = []

    def check(name, cond):
        cases.append((bool(cond), name))

    # P1 — her bağlam terminal'e ulaşır (DELIVERED|DEGRADED)
    for sp in (True, False):
        r = P.build(_ctx(screen_pop_available=sp), SPEC)
        check("P1 terminal: %s" % r["terminal"], r["terminal"] in P.TERMINAL)

    # P2 — dört zorunlu bileşen pakette
    r = P.build(_ctx(), SPEC)
    check("P2 dört bileşen (summary/intent/collected_fields/auth_status)",
          set(r["components"]) == set(P.COMPONENTS))
    check("P2 missing_component=0", r["violations"]["missing_component"] == 0)

    # P3 — oturumda toplanan tüm alanlar pakette (tekrar-sormama)
    r = P.build(_ctx(), SPEC)
    check("P3 collected_field_count=2 (tüm alanlar)", r["collected_field_count"] == 2)
    check("P3 missing_collected_field=0", r["violations"]["missing_collected_field"] == 0)

    # P4 — auth_status yalnız-statü; ham OTP/sır pakette yok
    r = P.build(_ctx(), SPEC)
    check("P4 auth_status'ta otp_code yok", "otp_code" not in r["package"]["auth_status"])
    check("P4 auth_status level/methods/step_up taşır",
          set(r["package"]["auth_status"].keys()) >= {"level", "methods", "step_up"})
    check("P4 auth_secret_leak=0", r["violations"]["auth_secret_leak"] == 0)

    # P5 — hassas alan maskeli (account_number masked=true)
    r = P.build(_ctx(), SPEC)
    acct = [f for f in r["package"]["collected_fields"] if f["name"] == "account_number"][0]
    check("P5 account_number masked=true", acct.get("masked") is True)
    check("P5 unmasked_sensitive=0", r["violations"]["unmasked_sensitive"] == 0)

    # P6 — paket 9.5'in seçtiği hedefe teslim
    r = P.build(_ctx(), SPEC)
    check("P6 deliver_to=q-billing-tr (9.5 hedefi)", r["delivered_to"] == "q-billing-tr")
    check("P6 mis_delivery=0", r["violations"]["mis_delivery"] == 0)

    # P7 — paket bu tenant'ın oturumundan/hedefinden; cross-tenant yok
    r = P.build(_ctx(), SPEC)
    check("P7 cross_tenant=0", r["violations"]["cross_tenant"] == 0)
    r = P.build(_ctx(), SPEC, inject=["cross_tenant"])
    check("P7 inject cross_tenant yakalanır", r["violations"]["cross_tenant"] > 0)

    # P8 — screen-pop yoksa fail-safe DEGRADED + fallback bağlam, oturum düşmez
    r = P.build(_ctx(screen_pop_available=False), SPEC)
    check("P8 screen-pop yok→DEGRADED", r["terminal"] == "DEGRADED")
    check("P8 fallback_context özet+intent taşır",
          r["fallback_context"]["summary"] == "s-ref" and r["fallback_context"]["intent"] == "billing_dispute")
    check("P8 DEGRADED ihlal değil (fail-safe geçerli)",
          all(v == 0 for v in r["violations"].values()))

    # P9 — her paket kanıt taşır (bileşen listesi + redaction + hedef kuyruk)
    r = P.build(_ctx(), SPEC)
    check("P9 evidence components_delivered taşır", set(r["evidence"]["components_delivered"]) == set(P.COMPONENTS))
    check("P9 evidence redactions account_number taşır", "account_number" in r["evidence"]["redactions"])
    check("P9 evidence target_queue taşır", r["evidence"]["target_queue"] == "q-billing-tr")
    check("P9 missing_evidence=0", r["violations"]["missing_evidence"] == 0)

    # P10 — her teslim audit'e yazılır
    r = P.build(_ctx(), SPEC)
    check("P10 audit delivered_to taşır", r["audit"] is not None and r["audit"]["delivered_to"] == "q-billing-tr")
    check("P10 audit tenant taşır", r["audit"]["tenant_id"] == "t")
    check("P10 audit redaction_count taşır", r["audit"]["redaction_count"] == 1)

    # P11/P12 — sızıntı tarayıcı: yapısal/maskeli temiz, ham PII/OTP yakalanır
    check("P12 maskeli token temiz", P.scan_leaks('{"masked_value": "****-4321"}') == [])
    check("P12 ham OTP alanı yakalanır", len(P.scan_leaks('{"otp_code_value": "123456"}')) > 0)

    npass = sum(1 for ok, _ in cases if ok)
    for ok, name in cases:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print("\nbehavior: %d/%d %s" % (npass, len(cases), "🟢" if npass == len(cases) else "🔴"))
    return 0 if npass == len(cases) else 1


if __name__ == "__main__":
    sys.exit(run())
