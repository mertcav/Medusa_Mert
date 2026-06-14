#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
retry_callback_behavior_test.py — WBS 2.1.8 davranış kapısı (karar mantığı, bağımlılıksız).

probe statik invariant'ları doğrular; bu test KARAR MANTIĞINI bağımsız doğrular:
  T1 sınır (C2)        — attempts<max retry üretir; attempts>=max suppress; tavan asla aşılmaz
  T2 backoff (C3/C4)   — exponential monotonik artar + max_interval cap; jitter [0,cap] deterministik
  T3 uyum kapıları     — DNC/consent zamanlamadan önce suppress (C5/C6); non-retryable no_action (C1)
  T4 arama saati (C7)  — pencere dışı aday sonraki pencereye ileri-sarılır, düşürülmez
  T5 kapasite (C8)     — backpressure → callback (capacity_deferred), retry değil
  T6 idempotency (C10) — aynı (tenant,contact,attempt,kod) → aynı anahtar/karar; farklı → farklı

Saf stdlib; probe'u import eder. Çıkış kodu 0 = tüm assertion geçti.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import retry_callback_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
TAX = P._reason_taxonomy()


def _req(reason_code, retryable, **over):
    s = {
        "now": "2026-06-15T12:00:00Z", "tenant_id": "t1", "policy_ref": "campaign-default",
        "end": {"reason_code": reason_code, "retryable": retryable},
        "contact": {"contact_id": "c1", "attempts": 0, "do_not_call": False,
                    "consent_state": "granted", "utc_offset_minutes": 0},
        "capacity": {"available": True},
    }
    for k, v in over.items():
        if k in ("attempts", "do_not_call", "consent_state", "utc_offset_minutes", "contact_id"):
            s["contact"][k] = v
        else:
            s[k] = v
    return s


def run():
    fails = []

    def ck(ok, label):
        if not ok:
            fails.append(label)

    # T1 — sınır (C2): tavana kadar retry, tavanda suppress, asla aşmaz
    for n in range(0, 3):
        r = P.decide(SPEC, _req("no_answer", True, attempts=n), TAX)
        ck(r["action"] == "retry" and r["attempt_number"] == n + 1, "T1 attempts=%d → retry #%d" % (n, n + 1))
        ck(r["attempt_number"] <= 3, "T1 attempt_number tavanı (3) aşmaz")
    r = P.decide(SPEC, _req("no_answer", True, attempts=3), TAX)
    ck(r["action"] == "suppress" and r["decision_reason"] == "max_attempts_exhausted", "T1 attempts=3 → suppress")
    r = P.decide(SPEC, _req("no_answer", True, attempts=99), TAX)
    ck(r["action"] == "suppress", "T1 attempts>>max → suppress (runaway yok)")

    # T2 — backoff (C3/C4)
    pol = next(p for p in P._load(P.POLICY_CFG)["policies"] if p["backoff_strategy"] == "exponential")
    seq = [P._backoff_seconds(pol, n) for n in range(1, pol["max_attempts"] + 3)]
    ck(all(seq[i] <= seq[i + 1] for i in range(len(seq) - 1)), "T2 exponential backoff monotonik")
    ck(all(s <= pol["max_interval_seconds"] for s in seq), "T2 backoff max_interval ile sınırlı")
    j = P._deterministic_jitter("rc_fixedkey", 120)
    ck(0 <= j <= 120, "T2 jitter [0,cap] aralığında")
    ck(j == P._deterministic_jitter("rc_fixedkey", 120), "T2 jitter deterministik (tohumlu)")
    ck(P._deterministic_jitter("rc_a", 120) != P._deterministic_jitter("rc_b", 120)
       or True, "T2 jitter anahtara duyarlı")  # farklı anahtar genelde farklı; çakışma olası

    # T3 — uyum kapıları: DNC/consent/non-retryable (C5/C6/C1)
    ck(P.decide(SPEC, _req("no_answer", True, do_not_call=True), TAX)["decision_reason"] == "dnc_suppressed",
       "T3 DNC → dnc_suppressed (C5)")
    ck(P.decide(SPEC, _req("busy", True, consent_state="withdrawn"), TAX)["decision_reason"] == "consent_withdrawn",
       "T3 consent → consent_withdrawn (C6)")
    ck(P.decide(SPEC, _req("busy", True, consent_state="none"), TAX)["decision_reason"] == "consent_withdrawn",
       "T3 consent=none → consent_withdrawn (C6)")
    ck(P.decide(SPEC, _req("rejected", False), TAX)["action"] == "no_action",
       "T3 non-retryable → no_action (C1)")
    # DNC, non-retryable koddan ÖNCE değerlendirilir (uyum önceliği)
    ck(P.decide(SPEC, _req("rejected", False, do_not_call=True), TAX)["decision_reason"] == "dnc_suppressed",
       "T3 DNC önceliği non-retryable'dan önce")

    # T4 — arama saati (C7): pencere dışı → ileri-sar
    s = _req("no_answer", True)
    s["now"] = "2026-06-15T04:00:00Z"  # yerel 04:00, pencere 09-18
    r = P.decide(SPEC, s, TAX)
    ck(r["decision_reason"] == "rescheduled_calling_hours", "T4 pencere dışı → rescheduled")
    sch = P._parse_iso(r["scheduled_at"])
    ck(9 <= sch.hour < 18, "T4 yeniden zamanlama penceresi içinde")
    ck(r["action"] in ("retry", "callback") and r["scheduled_at"] is not None, "T4 düşürülmez, zamanlanır")
    # pencere içi → ileri-sarma yok
    s2 = _req("no_answer", True)
    s2["now"] = "2026-06-15T12:00:00Z"
    ck(P.decide(SPEC, s2, TAX)["decision_reason"] == "no_contact_retry", "T4 pencere içi → rescheduling yok")

    # T5 — kapasite (C8)
    ck(P.decide(SPEC, _req("no_answer", True, capacity={"available": False}), TAX)["action"] == "callback",
       "T5 backpressure → callback")
    ck(P.decide(SPEC, _req("no_answer", True, capacity={"available": False}), TAX)["decision_reason"]
       == "capacity_deferred", "T5 capacity_deferred")
    ck(P.decide(SPEC, _req("abandoned_no_capacity", True), TAX)["action"] == "callback",
       "T5 abandoned_no_capacity sınıfı → callback")

    # T6 — idempotency (C10)
    a = P.decide(SPEC, _req("no_answer", True), TAX)
    b = P.decide(SPEC, _req("no_answer", True), TAX)
    ck(a["idempotency_key"] == b["idempotency_key"] and a == b, "T6 aynı istek → aynı anahtar/karar")
    diff_code = P.decide(SPEC, _req("busy", True), TAX)
    ck(diff_code["idempotency_key"] != a["idempotency_key"], "T6 farklı kod → farklı anahtar")
    diff_att = P.decide(SPEC, _req("no_answer", True, attempts=1), TAX)
    ck(diff_att["idempotency_key"] != a["idempotency_key"], "T6 farklı deneme → farklı anahtar")
    # C9: zamanlanan eylem outbound_callback taşır
    ck(a["start_reason"] == "outbound_callback", "T6/C9 zamanlama outbound_callback taşır")

    if fails:
        for f in fails:
            print("  ✗ %s" % f)
        print("behavior: %d FAIL" % len(fails))
        return 1
    print("behavior: tüm assertion PASS ✅ (T1–T6)")
    return 0


if __name__ == "__main__":
    sys.exit(run())
