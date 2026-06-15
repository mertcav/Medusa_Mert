#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 7.1.4 — Integration GW (timeout/retry/circuit breaker) davranış testi (FR-TOOL-003 / SR-TOOL-003).

Probe'un selftest'inden AYRI, kara-kutu davranış sözleşmelerini doğrular: timeout retry'ı tetikler,
kontrolsüz retry yoktur, terminal/write-no-idem retry edilmez, devre açılır/kurtarır, endpoint izolasyonu,
determinizm, audit no-log. Stdlib-only; gerçek ağ/credential YOK.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..")))
import integration_gw_probe as GW  # noqa: E402

FAILS = []
N = 0


def check(cond, msg):
    global N
    N += 1
    if not cond:
        FAILS.append(msg)


def pol(**kw):
    base = {
        "timeout_ms": 500, "max_attempts": 3, "base_backoff_ms": 50, "backoff_multiplier": 2.0,
        "max_backoff_ms": 2000, "jitter": "full", "retry_writes_require_idempotency": True,
        "breaker": {"failure_threshold": 3, "window_size": 10, "min_calls": 4, "rate_threshold": 0.5,
                    "cooldown_ms": 5000, "half_open_max_probes": 1, "half_open_success_to_close": 1},
    }
    base.update(kw)
    return base


F5 = {"result": "fault", "fault_class": "UPSTREAM_5XX", "latency_ms": 25}
OK = {"result": "ok", "latency_ms": 30}
TO = {"result": "timeout"}


def t_bounded_retry():
    gw = GW.IntegrationGateway(pol(max_attempts=2), seed=1)
    r = gw.call({"call_id": "c", "endpoint": "e", "operation_class": "read", "attempts_script": [F5, F5, F5, F5]})
    check(r["attempts"] == 2, "bounded retry max_attempts=2 → attempts 2")
    check(r["status"] == "failed", "tüm transient → failed")


def t_timeout_triggers_retry():
    gw = GW.IntegrationGateway(pol(), seed=1)
    r = gw.call({"call_id": "c", "endpoint": "e", "operation_class": "read", "attempts_script": [TO, OK]})
    check(r["status"] == "success" and r["timed_out_attempts"] == 1, "timeout retry'ı tetikler, sonra başarı")


def t_terminal_not_retried():
    gw = GW.IntegrationGateway(pol(), seed=1)
    r = gw.call({"call_id": "c", "endpoint": "e", "operation_class": "read",
                 "attempts_script": [{"result": "fault", "fault_class": "AUTH_FAILED", "latency_ms": 5}, OK]})
    check(r["attempts"] == 1 and r["fault_class"] == "AUTH_FAILED", "terminal fault retry edilmez")


def t_write_idempotency_gate():
    gw = GW.IntegrationGateway(pol(), seed=1)
    r_no = gw.call({"call_id": "w", "endpoint": "e", "operation_class": "write", "attempts_script": [F5, OK]})
    check(r_no["attempts"] == 1, "write no-idem retry edilmez (duplicate önleme)")
    gw2 = GW.IntegrationGateway(pol(), seed=1)
    r_yes = gw2.call({"call_id": "w", "endpoint": "e", "operation_class": "write", "idempotency_key": "k",
                      "attempts_script": [F5, OK]})
    check(r_yes["attempts"] == 2 and r_yes["status"] == "success", "write idem retry edilir")


def t_breaker_opens_and_fails_fast():
    gw = GW.IntegrationGateway(pol(max_attempts=1), seed=1)
    for i in range(3):
        gw.call({"call_id": "c%d" % i, "endpoint": "dep", "operation_class": "read", "attempts_script": [F5]})
    check(gw.breakers["dep"].state == GW.STATE_OPEN, "3 ardışık hata → OPEN")
    r = gw.call({"call_id": "sc", "endpoint": "dep", "operation_class": "read", "attempts_script": [OK]})
    check(r["short_circuited"] and r["attempts"] == 0 and r["fault_class"] == "CIRCUIT_OPEN",
          "OPEN → fail-fast (upstream'e değmez)")


def t_breaker_recovers():
    bcfg = {"failure_threshold": 2, "window_size": 10, "min_calls": 4, "rate_threshold": 0.9,
            "cooldown_ms": 1000, "half_open_max_probes": 1, "half_open_success_to_close": 1}
    gw = GW.IntegrationGateway(pol(max_attempts=1, breaker=bcfg), seed=1)
    gw.call({"call_id": "f1", "endpoint": "d", "operation_class": "read", "at_ms": 0, "attempts_script": [F5]})
    gw.call({"call_id": "f2", "endpoint": "d", "operation_class": "read", "attempts_script": [F5]})
    r = gw.call({"call_id": "p", "endpoint": "d", "operation_class": "read", "at_ms": 3000, "attempts_script": [OK]})
    check(not r["short_circuited"] and gw.breakers["d"].state == GW.STATE_CLOSED,
          "cooldown sonrası HALF_OPEN probe başarısı → CLOSED")


def t_endpoint_isolation():
    gw = GW.IntegrationGateway(pol(max_attempts=1, breaker={"failure_threshold": 2, "window_size": 10,
            "min_calls": 4, "rate_threshold": 0.9, "cooldown_ms": 5000, "half_open_max_probes": 1,
            "half_open_success_to_close": 1}), seed=1)
    gw.call({"call_id": "a0", "endpoint": "bad", "operation_class": "read", "attempts_script": [F5]})
    gw.call({"call_id": "a1", "endpoint": "bad", "operation_class": "read", "attempts_script": [F5]})
    r = gw.call({"call_id": "g", "endpoint": "good", "operation_class": "read", "attempts_script": [OK]})
    check(gw.breakers["bad"].state == GW.STATE_OPEN and r["status"] == "success",
          "bir endpoint OPEN sağlıklı endpoint'i etkilemez")


def t_determinism():
    def run(seed):
        g = GW.IntegrationGateway(pol(jitter="full"), seed=seed)
        return g.call({"call_id": "c", "endpoint": "e", "operation_class": "read",
                       "attempts_script": [F5, F5, OK]})["total_latency_ms"]
    check(run(13) == run(13), "aynı seed → birebir aynı")
    check(run(13) != run(99), "farklı seed → farklı jitter")


def t_audit_no_log():
    gw = GW.IntegrationGateway(pol(), seed=1)
    gw.call({"call_id": "c", "correlation_id": "corr-9", "endpoint": "e", "operation_class": "read",
             "attempts_script": [OK]})
    blob = repr(gw.audit)
    check("attempts_script" not in blob and all(a.get("no_log") for a in gw.audit) and "corr-9" in blob,
          "audit no-log + correlation_id taşır")


def main():
    for fn in [t_bounded_retry, t_timeout_triggers_retry, t_terminal_not_retried, t_write_idempotency_gate,
               t_breaker_opens_and_fails_fast, t_breaker_recovers, t_endpoint_isolation, t_determinism,
               t_audit_no_log]:
        fn()
    print("behavior test: %d kontrol, %d başarısız" % (N, len(FAILS)))
    for m in FAILS:
        print("  ✗ %s" % m)
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
