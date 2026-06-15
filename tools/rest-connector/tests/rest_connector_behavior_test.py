#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 7.2.1 — REST connector davranış testi (FR-TOOL-001 / SR-TOOL-001).

Probe selftest'inden AYRI, kara-kutu davranış sözleşmelerini doğrular: kanonik istek determinizmi,
status→fault eşleme (7.1.4 taksonomisiyle hizalı), method→operation_class, connection pool reuse,
bağlam taşıma, enjeksiyon reddi, audit no-log, AttemptOutcome'un 7.1.4 SPI seam'ine uygunluğu.
Stdlib-only; gerçek ağ/credential YOK (FR-TST-008).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..")))
import rest_connector_probe as RC  # noqa: E402

FAILS = []
N = 0


def check(cond, msg):
    global N
    N += 1
    if not cond:
        FAILS.append(msg)


def spec(**over):
    s = {
        "connector_id": "bh", "base_url": "https://api.example.com",
        "auth": {"type": "bearer", "ref": "${TOKEN}", "header": "Authorization", "scheme": "Bearer"},
        "default_headers": {"X-Client": "chanteur"},
        "pool": {"max_per_host": 4, "keepalive_ms": 30000, "connect_overhead_ms": 40.0},
        "operations": {
            "read_op": {"method": "GET", "path": "/v1/items/{id}", "timeout_ms": 2000, "accept": "application/json"},
            "write_op": {"method": "POST", "path": "/v1/items", "content_type": "application/json",
                         "success_codes": [200, 201], "timeout_ms": 2000},
            "put_op": {"method": "PUT", "path": "/v1/items/{id}", "success_codes": [200], "timeout_ms": 2000},
        },
    }
    s.update(over)
    return s


def W(status=None, latency=30.0, result="status"):
    w = {"result": result, "latency_ms": latency}
    if status is not None:
        w["status_code"] = status
    return w


def t_request_determinism():
    a = RC.RestConnector(spec()).upstream_call(
        {"call_id": "x", "correlation_id": "c", "operation": "read_op", "path_params": {"id": "7"}, "wire_script": [W(200)]})
    b = RC.RestConnector(spec()).upstream_call(
        {"call_id": "x", "correlation_id": "c", "operation": "read_op", "path_params": {"id": "7"}, "wire_script": [W(200)]})
    check(a == b, "determinizm: aynı girdi → aynı AttemptOutcome")


def t_status_mapping_aligned_with_714():
    # 7.1.4 taksonomisi ile birebir hizalama
    exp = {200: (None, "ok"), 201: (None, "ok"), 500: ("UPSTREAM_5XX", "fault"), 503: ("UPSTREAM_5XX", "fault"),
           429: ("RATE_LIMITED", "fault"), 408: ("TIMEOUT", "fault"), 404: ("NOT_FOUND", "fault"),
           401: ("AUTH_FAILED", "fault"), 403: ("AUTH_FAILED", "fault"), 422: ("SCHEMA_INVALID", "fault"),
           400: ("UPSTREAM_4XX", "fault"), 418: ("UPSTREAM_4XX", "fault")}
    for code, (fc, res) in exp.items():
        o = RC.RestConnector(spec()).upstream_call(
            {"call_id": "c", "correlation_id": "c", "operation": "read_op", "path_params": {"id": "1"},
             "wire_script": [W(code)]})
        check(o["result"] == res and o["fault_class"] == fc, "status %d → %s/%s" % (code, res, fc))
        if fc is not None:
            in_tax = fc in (RC.RETRYABLE_FAULTS | RC.TERMINAL_FAULTS)
            check(in_tax, "fault %s 7.1.4 taksonomisinde" % fc)
            check(o["fault_class"] not in RC.GATEWAY_FAULTS, "connector gateway-fault üretmez (%d)" % code)


def t_method_operation_class():
    c = RC.RestConnector(spec())
    r = c.upstream_call({"call_id": "r", "correlation_id": "c", "operation": "read_op",
                         "path_params": {"id": "1"}, "wire_script": [W(200)]})
    w = c.upstream_call({"call_id": "w", "correlation_id": "c", "operation": "write_op",
                         "body": {}, "wire_script": [W(201)]})
    p = c.upstream_call({"call_id": "p", "correlation_id": "c", "operation": "put_op",
                         "path_params": {"id": "1"}, "wire_script": [W(200)]})
    check(r["operation_class"] == "read", "GET → read")
    check(w["operation_class"] == "write" and p["operation_class"] == "write", "POST/PUT → write")


def t_pool_reuse():
    c = RC.RestConnector(spec())
    a = c.upstream_call({"call_id": "1", "correlation_id": "c", "operation": "read_op", "path_params": {"id": "1"},
                         "at_ms": 0, "wire_script": [W(200, latency=30)]})
    b = c.upstream_call({"call_id": "2", "correlation_id": "c", "operation": "read_op", "path_params": {"id": "2"},
                         "at_ms": 50, "wire_script": [W(200, latency=30)]})
    check(a["pooled"] is False and a["latency_ms"] == 70.0, "ilk çağrı cold (+connect)")
    check(b["pooled"] is True and b["latency_ms"] == 30.0, "ikinci çağrı warm (reuse, connect yok)")


def t_idempotency_forward():
    c = RC.RestConnector(spec())
    w = c.upstream_call({"call_id": "w", "correlation_id": "c", "operation": "write_op", "idempotency_key": "k1",
                         "body": {}, "wire_script": [W(201)]})
    r = c.upstream_call({"call_id": "r", "correlation_id": "c", "operation": "read_op", "path_params": {"id": "1"},
                         "idempotency_key": "k2", "wire_script": [W(200)]})
    check(w["request_meta"]["idempotency_forwarded"] is True, "write+key → idempotency header iletilir")
    check(r["request_meta"]["idempotency_forwarded"] is False, "read → idempotency iletilmez (yan-etkisiz)")


def t_injection_rejected():
    c = RC.RestConnector(spec())
    try:
        c.upstream_call({"call_id": "i", "correlation_id": "c", "operation": "read_op",
                         "path_params": {"id": "1\r\nX: y"}, "wire_script": [W(200)]})
        check(False, "CRLF reddedilmeli")
    except RC.ConnectorError as e:
        check(e.error_class == "INJECTION_REJECTED", "CRLF → INJECTION_REJECTED")
    check(len(c.audit) == 0, "reddedilen istek WIRE'a gitmez (audit boş)")


def t_audit_no_log():
    c = RC.RestConnector(spec())
    c.upstream_call({"call_id": "q", "correlation_id": "corr-9", "operation": "read_op", "path_params": {"id": "SECRET-77"},
                     "query_params": {"q": "lookup-xyz"}, "wire_script": [W(200)]})
    blob = json.dumps(c.audit)
    check("SECRET-77" not in blob and "lookup-xyz" not in blob and "?" not in blob, "audit'te ham değer/query yok")
    check(c.audit[0]["no_log"] is True and c.audit[0]["correlation_id"] == "corr-9", "no_log + correlation_id var")
    check("{id}" in c.audit[0]["endpoint"], "audit endpoint interpolesiz template")


def t_literal_secret_rejected():
    try:
        RC.RestConnector(spec(auth={"type": "bearer", "ref": "AKIA-LIVE-1234567890ABCDEF", "header": "Authorization"}))
        check(False, "literal sır reddedilmeli")
    except RC.ConnectorError as e:
        check(e.error_class == "LITERAL_SECRET_IN_SPEC", "literal sır → LITERAL_SECRET_IN_SPEC")


def t_spi_shape_for_714():
    # AttemptOutcome 7.1.4'ün tükettiği çekirdek alanları taşımalı; retry/breaker alanı taşımamalı
    o = RC.RestConnector(spec()).upstream_call(
        {"call_id": "s", "correlation_id": "c", "operation": "read_op", "path_params": {"id": "1"}, "wire_script": [W(503)]})
    check({"result", "latency_ms", "fault_class"}.issubset(o.keys()), "SPI çekirdek alanları (result/latency/fault)")
    check("attempts" not in o and "breaker_state_after" not in o, "connector retry/breaker orkestre etmez (C4)")
    check(o["retryable"] is True, "retryable bayrağı 7.1.4 kararına yardımcı")


def main():
    for fn in [t_request_determinism, t_status_mapping_aligned_with_714, t_method_operation_class, t_pool_reuse,
               t_idempotency_forward, t_injection_rejected, t_audit_no_log, t_literal_secret_rejected,
               t_spi_shape_for_714]:
        fn()
    print("behavior: %d kontrol, %d başarısız" % (N, len(FAILS)))
    for m in FAILS:
        print("  ✗ %s" % m)
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
