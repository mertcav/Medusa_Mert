#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 7.2.2 — SOAP/GraphQL/webhook connector davranış testi (FR-TOOL-001 / SR-TOOL-001).

Probe selftest'inden AYRI, kara-kutu davranış sözleşmelerini doğrular: kanonik istek determinizmi,
transport status→fault eşleme (7.1.4 hizalı), PROTOKOL-FARKINDA fault tespiti (C13 — SOAP rol / GraphQL
errors[] / webhook imza), operation_class, connection pool reuse, bağlam taşıma, enjeksiyon reddi,
audit no-log, AttemptOutcome'un 7.1.4 SPI seam'ine + 7.2.1 ile AYNI şekle uygunluğu.
Stdlib-only; gerçek ağ/credential YOK (FR-TST-008).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..")))
import protocol_connector_probe as PC  # noqa: E402

FAILS = []
N = 0


def check(cond, msg):
    global N
    N += 1
    if not cond:
        FAILS.append(msg)


def soap(**over):
    s = {
        "connector_id": "bh-soap", "protocol": "soap", "base_url": "https://erp.example.com",
        "auth": {"type": "basic", "ref": "${B}", "header": "Authorization"},
        "pool": {"max_per_host": 4, "keepalive_ms": 30000, "connect_overhead_ms": 40.0},
        "operations": {
            "Read": {"soap_action": "urn:x/Read", "path": "/soap", "side_effect": "read", "timeout_ms": 2000},
            "Write": {"soap_action": "urn:x/Write", "path": "/soap", "side_effect": "write", "timeout_ms": 2000},
        },
    }
    s.update(over)
    return s


def gql(**over):
    s = {
        "connector_id": "bh-gql", "protocol": "graphql", "base_url": "https://api.example.com",
        "auth": {"type": "bearer", "ref": "${T}", "header": "Authorization", "scheme": "Bearer"},
        "pool": {"max_per_host": 4, "keepalive_ms": 30000, "connect_overhead_ms": 40.0},
        "operations": {
            "Q": {"op_type": "query", "operation_name": "Q", "path": "/graphql",
                  "query": "query Q($id:ID!){ x(id:$id){ y } }", "timeout_ms": 2000},
            "M": {"op_type": "mutation", "operation_name": "M", "path": "/graphql", "timeout_ms": 2000},
        },
    }
    s.update(over)
    return s


def wh(**over):
    s = {
        "connector_id": "bh-wh", "protocol": "webhook", "base_url": "https://hooks.example.com",
        "signing": {"ref": "${K}", "header": "X-Signature", "algo": "hmac-sha256"},
        "pool": {"max_per_host": 4, "keepalive_ms": 30000, "connect_overhead_ms": 40.0},
        "operations": {"E": {"event_type": "e.t", "path": "/events", "success_codes": [200, 202, 204], "timeout_ms": 2000}},
    }
    s.update(over)
    return s


def W(status=None, latency=30.0, result="status", **extra):
    w = {"result": result, "latency_ms": latency}
    if status is not None:
        w["status_code"] = status
    w.update(extra)
    return w


def t_determinism_all_protocols():
    for spec, op, args in [(soap(), "Read", {"a": "1"}), (gql(), "Q", {"id": "1"}), (wh(), "E", {"x": "1"})]:
        a = PC.ProtocolConnector(spec).upstream_call(
            {"call_id": "x", "correlation_id": "c", "operation": op, "args": args, "wire_script": [W(200)]})
        b = PC.ProtocolConnector(spec).upstream_call(
            {"call_id": "x", "correlation_id": "c", "operation": op, "args": args, "wire_script": [W(200)]})
        check(a == b, "determinizm: %s" % a["protocol"])


def t_soap_fault_role_overrides_status():
    # AYNI HTTP 500, farklı rol → farklı retryability (C13)
    s = PC.ProtocolConnector(soap()).upstream_call(
        {"call_id": "s", "correlation_id": "c", "operation": "Read", "args": {"a": "1"},
         "wire_script": [W(500, soap_fault={"role": "Sender"})]})
    r = PC.ProtocolConnector(soap()).upstream_call(
        {"call_id": "r", "correlation_id": "c", "operation": "Read", "args": {"a": "1"},
         "wire_script": [W(500, soap_fault={"role": "Receiver"})]})
    check(s["fault_class"] == "UPSTREAM_4XX" and s["retryable"] is False, "SOAP Sender 500 → terminal")
    check(r["fault_class"] == "UPSTREAM_5XX" and r["retryable"] is True, "SOAP Receiver 500 → retryable")
    # soap_fault yoksa transport status geçerli
    n = PC.ProtocolConnector(soap()).upstream_call(
        {"call_id": "n", "correlation_id": "c", "operation": "Read", "args": {"a": "1"}, "wire_script": [W(503)]})
    check(n["fault_class"] == "UPSTREAM_5XX", "SOAP fault'suz 503 → transport eşleme")


def t_graphql_errors_override_200():
    exp = {"UNAUTHENTICATED": ("AUTH_FAILED", False), "FORBIDDEN": ("AUTH_FAILED", False),
           "BAD_USER_INPUT": ("SCHEMA_INVALID", False), "GRAPHQL_VALIDATION_FAILED": ("SCHEMA_INVALID", False),
           "INTERNAL_SERVER_ERROR": ("UPSTREAM_5XX", True), "RATE_LIMITED": ("RATE_LIMITED", True),
           "THROTTLED": ("RATE_LIMITED", True), "WAT": ("UPSTREAM_4XX", False)}
    for code, (fc, rt) in exp.items():
        o = PC.ProtocolConnector(gql()).upstream_call(
            {"call_id": "e", "correlation_id": "c", "operation": "Q", "args": {"id": "1"},
             "wire_script": [W(200, graphql_errors=[{"code": code}])]})
        check(o["result"] == "fault" and o["fault_class"] == fc and o["retryable"] == rt,
              "GraphQL 200+errors[%s] → %s/retry=%s" % (code, fc, rt))
    # 200 + data, errors yok → ok
    ok = PC.ProtocolConnector(gql()).upstream_call(
        {"call_id": "o", "correlation_id": "c", "operation": "Q", "args": {"id": "1"},
         "wire_script": [W(200, has_data=True)]})
    check(ok["result"] == "ok" and ok["fault_class"] is None, "GraphQL 200 no-errors → ok")


def t_operation_class():
    sr = PC.ProtocolConnector(soap()).upstream_call(
        {"call_id": "a", "correlation_id": "c", "operation": "Read", "args": {}, "wire_script": [W(200)]})
    sw = PC.ProtocolConnector(soap()).upstream_call(
        {"call_id": "b", "correlation_id": "c", "operation": "Write", "args": {}, "wire_script": [W(200)]})
    gq = PC.ProtocolConnector(gql()).upstream_call(
        {"call_id": "c", "correlation_id": "c", "operation": "Q", "args": {"id": "1"}, "wire_script": [W(200, has_data=True)]})
    gm = PC.ProtocolConnector(gql()).upstream_call(
        {"call_id": "d", "correlation_id": "c", "operation": "M", "args": {}, "wire_script": [W(200, has_data=True)]})
    we = PC.ProtocolConnector(wh()).upstream_call(
        {"call_id": "e", "correlation_id": "c", "operation": "E", "args": {}, "wire_script": [W(202)]})
    check(sr["operation_class"] == "read" and sw["operation_class"] == "write", "SOAP side_effect read/write")
    check(gq["operation_class"] == "read" and gm["operation_class"] == "write", "GraphQL query/mutation → read/write")
    check(we["operation_class"] == "write", "webhook → write")


def t_webhook_signing_required():
    try:
        PC.ProtocolConnector(wh(signing={}))
        check(False, "imzasız webhook reddedilmeli")
    except PC.ConnectorError as e:
        check(e.error_class == "MISSING_SIGNING_CONFIG", "webhook imzasız → MISSING_SIGNING_CONFIG")
    o = PC.ProtocolConnector(wh()).upstream_call(
        {"call_id": "w", "correlation_id": "c", "operation": "E", "args": {}, "wire_script": [W(202)]})
    check(o["request_meta"]["signed"] is True, "webhook teslimat signed=true")


def t_pool_reuse():
    c = PC.ProtocolConnector(gql())
    a = c.upstream_call({"call_id": "1", "correlation_id": "c", "operation": "Q", "args": {"id": "1"},
                         "at_ms": 0, "wire_script": [W(200, latency=30, has_data=True)]})
    b = c.upstream_call({"call_id": "2", "correlation_id": "c", "operation": "Q", "args": {"id": "2"},
                         "at_ms": 50, "wire_script": [W(200, latency=30, has_data=True)]})
    check(a["pooled"] is False and a["latency_ms"] == 70.0, "ilk çağrı cold (+connect)")
    check(b["pooled"] is True and b["latency_ms"] == 30.0, "ikinci çağrı warm (reuse)")


def t_idempotency_forward():
    w = PC.ProtocolConnector(gql()).upstream_call(
        {"call_id": "w", "correlation_id": "c", "operation": "M", "idempotency_key": "k", "args": {},
         "wire_script": [W(200, has_data=True)]})
    r = PC.ProtocolConnector(gql()).upstream_call(
        {"call_id": "r", "correlation_id": "c", "operation": "Q", "idempotency_key": "k", "args": {"id": "1"},
         "wire_script": [W(200, has_data=True)]})
    check(w["request_meta"]["idempotency_forwarded"] is True, "mutation+key → idempotency iletilir")
    check(r["request_meta"]["idempotency_forwarded"] is False, "query → idempotency iletilmez")


def t_injection_safety():
    # CRLF header → reddedilir
    c = PC.ProtocolConnector(soap())
    try:
        c.upstream_call({"call_id": "i", "correlation_id": "c\r\nX: y", "operation": "Read", "args": {"a": "1"},
                         "wire_script": [W(200)]})
        check(False, "CRLF reddedilmeli")
    except PC.ConnectorError as e:
        check(e.error_class == "INJECTION_REJECTED", "CRLF → INJECTION_REJECTED")
    check(len(c.audit) == 0, "reddedilen istek WIRE'a gitmez")
    # SOAP gövde XML-escape
    body = PC.ProtocolConnector(soap())._render_soap_body({"soap_action": "urn:x/Read"}, {"f": "</a><b>x"})
    check("</a><b>" not in body and "&lt;/a&gt;" in body, "SOAP gövde XML-escape (tag nötr)")
    # GraphQL variables parametreli
    p = PC.ProtocolConnector(gql())._build_graphql_payload(
        {"op_type": "query", "operation_name": "Q", "query": "query Q($id:ID!){ x(id:$id){ y } }"}, {"id": "evil) OR 1=1"})
    check("OR 1=1" not in p["query"] and p["variables"]["id"] == "evil) OR 1=1", "GraphQL variables parametreli")


def t_audit_no_log():
    c = PC.ProtocolConnector(soap())
    c.upstream_call({"call_id": "q", "correlation_id": "corr-9", "operation": "Read", "args": {"a": "SECRET-77"},
                     "query_params": {"q": "lookup-xyz"}, "wire_script": [W(200)]})
    blob = json.dumps(c.audit)
    check("SECRET-77" not in blob and "lookup-xyz" not in blob and "?" not in blob, "audit'te ham değer/query yok")
    check(c.audit[0]["no_log"] is True and c.audit[0]["correlation_id"] == "corr-9", "no_log + correlation_id")
    check(c.audit[0]["protocol"] == "soap" and "signed" in c.audit[0], "audit protocol+signed alanı")


def t_literal_secret_rejected():
    try:
        PC.ProtocolConnector(gql(auth={"type": "bearer", "ref": "AKIA-LIVE-1234567890ABCDEF", "header": "Authorization"}))
        check(False, "literal auth sırrı reddedilmeli")
    except PC.ConnectorError as e:
        check(e.error_class == "LITERAL_SECRET_IN_SPEC", "literal auth sırrı → LITERAL_SECRET_IN_SPEC")
    try:
        PC.ProtocolConnector(wh(signing={"ref": "whsec-1234567890ABCDEF1234", "header": "X-Signature"}))
        check(False, "literal signing sırrı reddedilmeli")
    except PC.ConnectorError as e:
        check(e.error_class == "LITERAL_SECRET_IN_SPEC", "literal signing sırrı → LITERAL_SECRET_IN_SPEC")


def t_spi_shape_for_714():
    o = PC.ProtocolConnector(gql()).upstream_call(
        {"call_id": "s", "correlation_id": "c", "operation": "Q", "args": {"id": "1"}, "wire_script": [W(503)]})
    check({"result", "latency_ms", "fault_class", "protocol", "operation_class", "endpoint", "retryable"}.issubset(o.keys()),
          "SPI çekirdek alanları (7.2.1 ile AYNI + protocol)")
    check("attempts" not in o and "breaker_state_after" not in o, "connector retry/breaker orkestre etmez (C4)")
    check(o["retryable"] is True, "retryable bayrağı 7.1.4 kararına yardımcı")
    check(o["fault_class"] in (PC.RETRYABLE_FAULTS | PC.TERMINAL_FAULTS), "fault 7.1.4 taksonomisinde")
    check(o["fault_class"] not in PC.GATEWAY_FAULTS, "connector gateway-fault üretmez")


def main():
    for fn in [t_determinism_all_protocols, t_soap_fault_role_overrides_status, t_graphql_errors_override_200,
               t_operation_class, t_webhook_signing_required, t_pool_reuse, t_idempotency_forward,
               t_injection_safety, t_audit_no_log, t_literal_secret_rejected, t_spi_shape_for_714]:
        fn()
    print("behavior: %d kontrol, %d başarısız" % (N, len(FAILS)))
    for m in FAILS:
        print("  ✗ %s" % m)
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
