#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 9.4 — Transfer tetikleyiciler davranış kapısı (T1–T9).

Probe'un selftest'inden BAĞIMSIZ, kara-kutu davranış kontrolleri: tetik motorunun
karar sözleşmesini (FR-HND-001/002) doğrudan doğrular. Stdlib-only, bağımlılıksız.
Çalıştırma: python3 tests/transfer_triggers_behavior_test.py  → çıkış kodu.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import transfer_triggers_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)


def _sig(kind, t, turn, **kw):
    d = {"kind": kind, "t": t, "turn": turn}
    d.update(kw)
    return d


def _end(t):
    return {"kind": "end", "t": t}


def run():
    cases = []

    def check(name, cond):
        cases.append((bool(cond), name))

    # T1 — her senaryo terminal'e ulaşır (TRIGGERED|NO_HANDOFF)
    for sg in ([_sig("user_request", 1000, 1), _end(2000)],
               [_sig("confidence", 1000, 1, score=0.95), _end(2000)]):
        r = P.evaluate({"tenant_id": "t", "signals": sg}, SPEC)
        check("T1 terminal: %s" % r["terminal"], r["terminal"] in P.TERMINAL)

    # T2 — kullanıcı isteği daima onurlandırılır; yüksek confidence bastıramaz
    r = P.evaluate({"tenant_id": "t", "signals": [
        _sig("confidence", 1000, 1, score=0.99), _sig("user_request", 2000, 2), _end(3000)]}, SPEC)
    check("T2 user-request TRIGGERED yüksek-conf'a rağmen",
          r["triggered"] and r["primary_reason"] == "USER_REQUEST")

    # T3 — tek geçici düşük-conf TETİKLEMEZ; sürdürülen tetikler
    r1 = P.evaluate({"tenant_id": "t", "signals": [
        _sig("confidence", 1000, 1, score=0.2), _sig("confidence", 2000, 2, score=0.95), _end(3000)]}, SPEC)
    r2 = P.evaluate({"tenant_id": "t", "signals": [
        _sig("confidence", 1000, 1, score=0.2), _sig("confidence", 2000, 2, score=0.2), _end(3000)]}, SPEC)
    check("T3 transient lowconf NO_HANDOFF", not r1["triggered"])
    check("T3 sustained lowconf TRIGGERED", r2["triggered"] and r2["primary_reason"] == "LOW_CONFIDENCE")

    # T4 — tek hafif öfke tetiklemez; sürdürülen öfke tetikler
    r1 = P.evaluate({"tenant_id": "t", "signals": [
        _sig("sentiment", 1000, 1, anger=0.9), _sig("sentiment", 2000, 2, anger=0.2), _end(3000)]}, SPEC)
    r2 = P.evaluate({"tenant_id": "t", "signals": [
        _sig("sentiment", 1000, 1, anger=0.8), _sig("sentiment", 2000, 2, anger=0.9), _end(3000)]}, SPEC)
    check("T4 transient anger NO_HANDOFF", not r1["triggered"])
    check("T4 sustained anger TRIGGERED", r2["triggered"] and r2["primary_reason"] == "ANGER")

    # T5 — politika tetikler, agent confidence bastıramaz
    r = P.evaluate({"tenant_id": "t", "signals": [
        _sig("confidence", 1000, 1, score=0.97), _sig("policy", 2000, 2, rule="rule-out-of-scope"), _end(3000)]}, SPEC)
    check("T5 policy TRIGGERED", r["triggered"] and r["primary_reason"] == "POLICY")

    # T6 — çoklu tetik öncelik: USER_REQUEST > POLICY > ANGER > LOW_CONFIDENCE
    r = P.evaluate({"tenant_id": "t", "signals": [
        _sig("policy", 1000, 1, rule="r"), _sig("user_request", 1000, 1), _end(2000)]}, SPEC)
    check("T6 same-turn user>policy primary=USER_REQUEST", r["primary_reason"] == "USER_REQUEST")
    check("T6 contributing iki reason kaydedildi", set(r["contributing"]) == {"USER_REQUEST", "POLICY"})

    # T7 — sağlıklı konuşma uydurma handoff üretmez
    r = P.evaluate({"tenant_id": "t", "signals": [
        _sig("confidence", 1000, 1, score=0.9), _sig("sentiment", 1000, 1, anger=0.1),
        _sig("confidence", 2000, 2, score=0.92), _end(3000)]}, SPEC)
    check("T7 healthy NO_HANDOFF", r["terminal"] == "NO_HANDOFF" and not r["triggered"])

    # T8 — ilk-niteleyen LATCH; sonraki tetik ikinci karar üretmez
    r = P.evaluate({"tenant_id": "t", "signals": [
        _sig("sentiment", 1000, 1, anger=0.8), _sig("sentiment", 2000, 2, anger=0.9),
        _sig("user_request", 3000, 3), _end(4000)]}, SPEC)
    check("T8 LATCH primary=ANGER (ilk niteleyen)", r["primary_reason"] == "ANGER")
    check("T8 duplicate_decision=0", r["violations"]["duplicate_decision"] == 0)

    # T9 — her tetik kanıt + reason taşır
    r = P.evaluate({"tenant_id": "t", "signals": [
        _sig("confidence", 1000, 1, score=0.2), _sig("confidence", 2000, 2, score=0.2), _end(3000)]}, SPEC)
    check("T9 evidence score+run taşır", r["evidence"] is not None and "score" in r["evidence"])
    check("T9 audit primary_reason taşır", r["audit"]["primary_reason"] == "LOW_CONFIDENCE")

    npass = sum(1 for ok, _ in cases if ok)
    for ok, name in cases:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print("\nbehavior: %d/%d %s" % (npass, len(cases), "🟢" if npass == len(cases) else "🔴"))
    return 0 if npass == len(cases) else 1


if __name__ == "__main__":
    sys.exit(run())
