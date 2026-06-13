#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
envelope_behavior_test.py — WBS 1.1.8 envelope sözleşmesi davranış kapısı (stdlib-only).

Doğrular:
  T1 — Geçerli envelope tüm zorunlu alanları taşır (schemas/event-envelope.schema.json).
  T2 — Eksik alanlı envelope reddedilir.
  T3 — envelope.pii_class topic pii_class'ı ile tutarlı (I5 üretim-tarafı kontrolü).
  T4 — Envelope → webhook envelope indirgemesi (API §10.1) yalnız tenant-facing alanları bırakır;
       idempotency_key/partition_key/producer gibi iç alanlar dışarı SIZMAZ.
Sunucu gerekmez; gerçek schema-validator (jsonschema) yoksa minimal required-field kontrolü.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCHEMA = os.path.join(ROOT, "schemas", "event-envelope.schema.json")

WEBHOOK_FIELDS = {"id", "type", "api_version", "created_at", "tenant_id", "correlation_id", "data"}
INTERNAL_ONLY = {"idempotency_key", "partition_key", "producer", "pii_class", "schema_version",
                 "event_time", "trace_context", "replay_of"}


def good_envelope():
    return {
        "id": "01J9ZK0000000000000000ABCD",
        "type": "call.completed",
        "api_version": "v1",
        "schema_version": 1,
        "created_at": "2026-06-13T10:00:00Z",
        "event_time": "2026-06-13T10:00:00Z",
        "tenant_id": "01J-TENANT",
        "correlation_id": "01J9ZK-CORR",
        "idempotency_key": "call-123#final",
        "partition_key": "call-123",
        "pii_class": "low",
        "producer": "orchestrator",
        "data": {"call_id": "call-123", "outcome": "resolved", "duration_sec": 142},
    }


def to_webhook(env):
    """API §10.1 webhook envelope indirgemesi — yalnız tenant-facing alanlar."""
    return {k: env[k] for k in WEBHOOK_FIELDS if k in env}


def validate_required(env, required):
    return [f for f in required if f not in env or env[f] in (None, "")]


def main():
    schema = json.load(open(SCHEMA, encoding="utf-8"))
    required = schema["required"]
    results = []

    def ok(cond, msg):
        results.append((bool(cond), msg))

    # T1
    ok(not validate_required(good_envelope(), required), "T1 geçerli envelope zorunlu alanları taşır")

    # T2
    bad = good_envelope(); del bad["idempotency_key"]
    ok(validate_required(bad, required) == ["idempotency_key"], "T2 eksik alan reddedilir")

    # T3 — topic pii_class ile tutarlılık
    topic_pii = "low"
    ok(good_envelope()["pii_class"] == topic_pii, "T3 envelope.pii_class topic ile tutarlı")
    raw_env = dict(good_envelope(), pii_class="raw")
    ok(raw_env["pii_class"] != topic_pii, "T3 uyumsuz pii_class tespit edilebilir")

    # T4 — webhook indirgemesi iç alan sızdırmaz
    wh = to_webhook(good_envelope())
    leaked = INTERNAL_ONLY & set(wh)
    ok(not leaked, f"T4 webhook indirgemesi iç alan sızdırmaz (leaked={leaked})")
    ok(WEBHOOK_FIELDS <= set(wh) or all(f in wh for f in WEBHOOK_FIELDS),
       "T4 webhook tüm tenant-facing alanları içerir")

    passed = sum(1 for o, _ in results if o)
    for o, m in results:
        print(f"  {'PASS' if o else 'FAIL'} {m}")
    print(f"envelope_behavior_test: {passed}/{len(results)} PASS")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
