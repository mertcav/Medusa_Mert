#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
session_memory_behavior_test.py — WBS 3.2.1 davranış kapısı (T1–T8)

Session Memory'nin oturum-içi bellek + oturum-sonu kalıcılaştırma davranışını uçtan uca doğrular
(bağımlılıksız, stdlib-only). `runtime/resource-budget/tests/` (3.1.4) deseniyle birebir.

  T1 happy           pencere içinde → persist + temizlik, kayıp/kaçak yok
  T2 windowed-fold   taşma özete katlanır, TÜM turn kalıcılaşır (kayıpsız M5/M9)
  T3 idempotent      aynı turn_id → tek kayıt (M2)
  T4 retry           durable geçici down → at-least-once retry, kayıpsız (M5)
  T5 end-states      normal/transfer/error/abandon → her bitişte persist (M3)
  T6 redaction       kart/OTP düz-metin durable'a yazılmaz (M6); strip kapalı kanıtlar
  T7 cleanup-order   persist_before_delete; temizlik kapalı → kaçak (M4)
  T8 determinizm+reddet  aynı giriş birebir; geçersiz olay reddi (M10)
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import session_memory_probe as P  # noqa: E402

PARAMS = {"window_max_turns": 6, "token_soft_limit": 100000, "tenant_id": "t-self"}
GATES = P._load(P.SPEC_PATH)["gates"]


def turn(t, tid, speaker="caller", tokens=10, sensitive=0, tenant=None):
    ev = {"kind": "turn", "turn_id": tid, "speaker": speaker, "t": t, "approx_tokens": tokens}
    if sensitive:
        ev["sensitive_tokens"] = sensitive
    if tenant:
        ev["tenant_id"] = tenant
    return ev


def end(t, reason="normal"):
    return {"kind": "end", "t": t, "reason": reason}


def run(events, params=None, **pol):
    policy = {"bound": True, "dedupe": True, "order_guard": True, "persist": True,
              "cleanup": True, "tenant_isolation": True, "strip_card_otp": True,
              "delete_before_persist": False, "redaction_state": "pending",
              "persist_transient_failures": 0}
    policy.update(pol)
    return P.simulate({"events": events}, params or PARAMS, policy)


def gates_pass(m):
    return all(ok for ok, _ in P.evaluate(GATES, m))


def main():
    R = []

    def chk(ok, label):
        R.append((bool(ok), label))

    # ── T1 happy: pencere içinde → persist + temizlik ────────────────────────────
    m = run([turn(0, "t1", "agent"), turn(1000, "t2", "caller"), turn(2000, "t3", "agent"), end(3000)])
    chk(m["captured_turns"] == 3 and m["persisted_turns"] == 3, "T1 happy: 3 turn yakalandı+kalıcılaştı")
    chk(m["dropped_turn"] == 0 and m["leaked_session_key"] == 0, "T1 happy: kayıp/kaçak yok")
    chk(m["persisted"] and m["ephemeral_deleted"] and m["redaction_state"] == "pending",
        "T1 happy: persist + temizlik + redaction=pending")
    chk(gates_pass(m), "T1 happy tüm kapıları geçer")

    # ── T2 windowed-fold: taşma katlanır, kayıpsız ───────────────────────────────
    long_ev = [turn(i * 100, "t%d" % i, "caller" if i % 2 else "agent") for i in range(10)]
    long_ev.append(end(2000))
    m = run(long_ev)
    chk(m["captured_turns"] == 10 and m["folded_turns"] == 4, "T2 fold: 10 turn, 4 katlandı (pencere 6)")
    chk(m["peak_window_turns"] <= 6, "T2 fold: pencere ≤ window_max (sınırlı bellek M1)")
    chk(m["persisted_turns"] == 10 and m["dropped_turn"] == 0, "T2 fold: TÜM 10 turn kalıcılaştı (M5/M9)")
    chk("fold" in m["scenario"] and gates_pass(m), "T2 fold tüm kapıları geçer")

    # ── T3 idempotent: aynı turn_id → tek kayıt ──────────────────────────────────
    m = run([turn(0, "t1", "agent"), turn(1000, "t2", "caller"),
             turn(1400, "t2", "caller"), turn(2000, "t3", "agent"), end(3000)])
    chk(m["duplicate_turn"] == 1 and m["captured_turns"] == 3, "T3 idempotent: çift turn_id → 3 benzersiz")
    chk(m["persisted_turns"] == 3 and gates_pass(m), "T3 idempotent kapıları geçer")

    # ── T4 retry: durable geçici down → at-least-once, kayıpsız ───────────────────
    base = [turn(0, "t1", "agent"), turn(1000, "t2", "caller"), end(2000)]
    m = run(base, persist_transient_failures=3)
    chk(m["persist_retries"] == 3 and m["persisted"], "T4 retry: 3 geçici hata → sonunda persist")
    chk(m["persisted_turns"] == 2 and m["dropped_turn"] == 0, "T4 retry: kayıpsız (at-least-once M5)")
    chk(gates_pass(m), "T4 retry tüm kapıları geçer")

    # ── T5 end-states: normal/transfer/error/abandon → her bitişte persist ───────
    for reason in ("normal", "transfer", "error", "abandon"):
        mr = run([turn(0, "t1", "agent"), turn(1000, "t2", "caller"), end(2000, reason)])
        chk(mr["persisted"] and mr["unpersisted_on_end"] == 0 and gates_pass(mr),
            "T5 end=%s: bitişte persist (M3)" % reason)

    # ── T6 redaction: kart/OTP düz-metin yazılmaz; strip kapalı kanıtlar ─────────
    m = run([turn(0, "t1", "caller", sensitive=2), turn(1000, "t2", "agent"), end(2000)])
    chk(m["sensitive_seen"] == 2 and m["sensitive_cleartext_persisted"] == 0,
        "T6 redaction: kart/OTP işareti görüldü, düz-metin persist=0 (M6)")
    chk(gates_pass(m), "T6 redaction tüm kapıları geçer")
    mbad = run([turn(0, "t1", "caller", sensitive=2), end(1000)], strip_card_otp=False)
    chk(mbad["sensitive_cleartext_persisted"] == 2 and not gates_pass(mbad),
        "T6 strip kapalı: düz-metin persist → M6 eler")

    # ── T7 cleanup-order: persist_before_delete; temizlik kapalı → kaçak ─────────
    m = run(base)
    chk(m["persist_before_delete_ok"] and m["ephemeral_deleted"], "T7 persist→delete sırası doğru")
    mleak = run(base, cleanup=False)
    chk(mleak["persisted"] and mleak["leaked_session_key"] == 1, "T7 temizlik kapalı: kaçak ephemeral")
    chk(not gates_pass(mleak), "T7 temizlik kapalı M4 eler")
    mdel = run(base, delete_before_persist=True)
    chk(mdel["persist_before_delete_ok"] is False and not gates_pass(mdel),
        "T7 sil-önce-yaz: persist_before_delete ihlali → M3 eler")

    # ── T8 determinizm + geçersiz olay reddi (M10) ───────────────────────────────
    chk(run(long_ev) == run(long_ev), "T8 determinizm: aynı olay-akışı birebir aynı metrik")
    rej = 0
    for bad in ([turn(0, "t1", speaker="robot"), end(1000)],
                [{"kind": "turn", "speaker": "caller", "t": 0}, end(1000)],
                [turn(0, "t1")],
                [turn(1000, "t1"), turn(0, "t2"), end(2000)],
                []):
        try:
            run(bad) if bad else P.simulate({"events": []}, PARAMS, {})
        except P.MemoryError_:
            rej += 1
    chk(rej == 5, "T8 geçersiz olay (speaker/turn_id/end-yok/out-of-order/boş) reddedilir")

    passed = sum(1 for ok, _ in R if ok)
    total = len(R)
    for ok, label in R:
        print("  %s %s" % ("✓" if ok else "✗", label))
    print("session_memory_behavior_test: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
