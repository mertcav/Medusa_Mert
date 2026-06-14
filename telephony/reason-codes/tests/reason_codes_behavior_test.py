#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
reason_codes_behavior_test.py — WBS 2.1.7 davranış kapısı (taksonomi mantığı, bağımlılıksız).

probe statik invariant'ları doğrular; bu test taksonomi MANTIĞINI bağımsız doğrular:
  T1 kategori kapanışı     — her bitiş kodu kapalı enum kümelerinde
  T2 status↔event eşlemesi — terminal_status ↔ event_type birebir
  T3 retryable disiplini   — normal/transfer asla retryable; geçici/temassız retryable
  T4 compliance disiplini  — compliance kodları faturalanmaz + blocked
  T5 sinyal çözümü         — SIP/Q.850/CPaaS/internal örnekleri doğru kanonik koda gider
  T6 fallback davranışı    — eşlenmeyen sinyal 'unknown'a düşer ve flag'lenir (R4)

Saf stdlib; probe'u import eder. Çıkış kodu 0 = tüm assertion geçti.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import reason_codes_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
ENDS = P._end_codes(SPEC)
ENUMS = SPEC["enums"]


def run():
    fails = []

    def ck(ok, label):
        if not ok:
            fails.append(label)

    # T1 — kategori/enum kapanışı
    for n, a in ENDS.items():
        ck(a["category"] in ENUMS["category"], "T1 %s category kapalı küme" % n)
        ck(a["terminal_status"] in ENUMS["terminal_status"], "T1 %s status kapalı küme" % n)
        ck(a["outcome"] in ENUMS["outcome"], "T1 %s outcome kapalı küme" % n)

    # T2 — status ↔ event_type birebir
    expect_ev = {"completed": "call.completed", "transferred": "call.transferred", "failed": "call.failed"}
    for n, a in ENDS.items():
        ck(a["event_type"] == expect_ev[a["terminal_status"]], "T2 %s status↔event" % n)

    # T3 — retryable disiplini
    for n, a in ENDS.items():
        if a["category"] == "normal":
            ck(a["retryable"] is False, "T3 normal %s retryable=false" % n)
    # geçici/temassız örnekleri retryable
    for n in ("no_answer", "busy", "timeout", "network_failure", "dropped_mid_call", "abandoned_no_capacity"):
        ck(ENDS[n]["retryable"] is True, "T3 %s retryable=true" % n)

    # T4 — compliance disiplini (R5/R6)
    comp = [n for n, a in ENDS.items() if a["category"] == "compliance"]
    ck(len(comp) >= 3, "T4 ≥3 compliance kodu")
    for n in comp:
        ck(ENDS[n]["billable"] is False, "T4 %s faturalanmaz" % n)
        ck(ENDS[n]["outcome"] == "blocked", "T4 %s blocked" % n)
    ck(ENDS["blocked_dnc"]["retryable"] is False, "T4 dnc kalıcı engel")
    ck(ENDS["blocked_time_window"]["retryable"] is True, "T4 time_window yeniden zamanla")

    # T5 — sinyal çözümü (4 kaynak)
    samples = [
        ("sip", "BYE", "completed_caller_hangup"),
        ("sip", "503", "provider_unavailable"),
        ("sip", "401", "auth_failure"),
        ("q850", "16", "completed_caller_hangup"),
        ("q850", "19", "no_answer"),
        ("q850", "102", "timeout"),
        ("cpaas", "busy", "busy"),
        ("cpaas", "FAILED", "provider_unavailable"),
        ("internal", "goal_fulfilled", "completed_goal_fulfilled"),
        ("internal", "outside_hours", "blocked_time_window"),
    ]
    for src, code, expect in samples:
        got, fb = P.resolve_signal(SPEC, src, code)
        ck(got == expect and fb is False, "T5 %s/%s → %s (got %s)" % (src, code, expect, got))

    # T6 — fallback (R4)
    for src, code in (("sip", "699"), ("q850", "999"), ("internal", "made_up_event"), ("bogus", "x")):
        got, fb = P.resolve_signal(SPEC, src, code)
        ck(got == "unknown" and fb is True, "T6 %s/%s → unknown+flag" % (src, code))
    # classify fallback flag yayılır
    c = P.classify(SPEC, "sip", "699")
    ck(c["is_fallback"] is True and c["reason_code"] == "unknown", "T6 classify fallback flag yayılır")

    total = 0
    # toplam assertion sayısı için kabaca: yeniden saymak yerine fails ile raporla
    if fails:
        for f in fails:
            print("  ✗ %s" % f)
        print("behavior: %d FAIL" % len(fails))
        return 1
    print("behavior: tüm assertion PASS ✅ (T1–T6)")
    return 0


if __name__ == "__main__":
    sys.exit(run())
