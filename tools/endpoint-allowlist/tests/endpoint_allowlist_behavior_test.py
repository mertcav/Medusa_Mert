#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 7.2.3 — Endpoint allowlist davranış testi (FR-TOOL-012 / SR-TOOL-012).

Probe selftest'inden AYRI, kara-kutu karar sözleşmelerini doğrular: default-deny (A1), SSRF blok
(metadata/private/rebinding A2–A4), block-overrides-allow (A9), scheme/port/host/path semantiği
(A5–A8), fail-closed (A12), audit no-log (A11), determinizm (A10), ENDPOINT_NOT_ALLOWED terminal fault.
Stdlib-only; gerçek DNS/ağ YOK (FR-TST-008).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..")))
import endpoint_allowlist_probe as EA  # noqa: E402

FAILS = []
N = 0


def check(cond, msg):
    global N
    N += 1
    if not cond:
        FAILS.append(msg)


def policy(**over):
    p = {
        "tenant_id": "t-1", "default_action": "deny",
        "schemes_allowed": ["https"], "ports_allowed": [443],
        "block_metadata": True, "block_private_networks": True,
        "allow": [
            {"connector_id": "crm", "scheme": "https", "host": "crm.example.com", "port": 443, "path_prefix": "/v1/"},
            {"scheme": "https", "host": "*.partner.example.com", "port": 443},
        ],
    }
    p.update(over)
    return p


def req(host, scheme="https", port=443, path="/v1/x", ips=None, tenant="t-1", conn="crm"):
    return {
        "call_id": "c", "correlation_id": "k", "tenant_id": tenant, "connector_id": conn, "method": "GET",
        "endpoint": "GET %s://%s%s" % (scheme, host, path),
        "target": {"scheme": scheme, "host": host, "port": port, "path": path},
        "resolved_ips": ["203.0.113.5"] if ips is None else ips,
    }


def decide(p, r):
    return EA.EgressGate(p).decide(r)


# T1 — default-deny: allowlist dışı host reddedilir (SR-TOOL-012 çekirdek)
d = decide(policy(), req("nope.attacker.net", path="/x", ips=["203.0.113.9"]))
check(d["decision"] == "deny" and d["reason_code"] == "UNLISTED_ENDPOINT", "T1 unlisted → deny")
check(d["fault_class"] == "ENDPOINT_NOT_ALLOWED", "T1 deny → ENDPOINT_NOT_ALLOWED terminal")

# T1b — onaylı host → permit
d = decide(policy(), req("crm.example.com", path="/v1/c/C-1"))
check(d["decision"] == "permit" and d["matched_rule"] == 0, "T1b onaylı host → permit")

# T2 — SSRF metadata blok (allow EZİLİR — A9)
d = decide(policy(), req("crm.example.com", path="/v1/x", ips=["169.254.169.254"]))
check(d["reason_code"] == "METADATA_BLOCKED", "T2 metadata IP → block (allow ezilir)")

# T3 — SSRF private IP literal
d = decide(policy(), req("10.0.0.5", path="/x", ips=["10.0.0.5"]))
check(d["reason_code"] == "PRIVATE_NETWORK_BLOCKED", "T3 private IP literal → block")

# T4 — DNS rebinding: onaylı host iç IP'ye çözülür
d = decide(policy(), req("crm.example.com", path="/v1/x", ips=["192.168.0.9"]))
check(d["reason_code"] == "DNS_REBINDING_BLOCKED", "T4 rebinding → block")
# çok-IP biri iç
d = decide(policy(), req("crm.example.com", path="/v1/x", ips=["203.0.113.5", "10.1.1.1"]))
check(d["reason_code"] == "DNS_REBINDING_BLOCKED", "T4b çok-IP biri iç → block")

# T5 — scheme/port
check(decide(policy(), req("crm.example.com", scheme="http"))["reason_code"] == "SCHEME_BLOCKED", "T5 http block")
check(decide(policy(), req("crm.example.com", scheme="file", path="/etc/passwd"))["reason_code"] == "SCHEME_BLOCKED", "T5b file block")
check(decide(policy(), req("crm.example.com", port=8080))["reason_code"] == "PORT_BLOCKED", "T5c port block")

# T6 — host etiket-sınırı semantiği (A7)
check(decide(policy(), req("api.partner.example.com", path="/x", ips=["203.0.113.5"]))["decision"] == "permit", "T6 wildcard subdomain")
check(decide(policy(), req("partner.example.com", path="/x", ips=["203.0.113.5"]))["decision"] == "deny", "T6b wildcard apex deny")
check(decide(policy(), req("crm.example.com.evil.net", path="/v1/x", ips=["203.0.113.5"]))["reason_code"] == "UNLISTED_ENDPOINT", "T6c substring confusion deny")

# T7 — path_prefix + traversal (A8)
check(decide(policy(), req("crm.example.com", path="/admin"))["reason_code"] == "PATH_NOT_ALLOWED", "T7 path_prefix dışı")
check(decide(policy(), req("crm.example.com", path="/v1/../admin"))["reason_code"] == "MALFORMED_TARGET", "T7b traversal malformed")
check(decide(policy(), req("crm.example.com", path="/v1extra/x"))["reason_code"] == "PATH_NOT_ALLOWED", "T7c segment-sınırı")

# T8 — fail-closed (A12)
check(decide(policy(), req("crm.example.com", port=None))["reason_code"] == "MALFORMED_TARGET", "T8 port yok → malformed")
check(decide(policy(), req("2130706433", path="/v1/x", ips=[]))["reason_code"] == "MALFORMED_TARGET", "T8b decimal IP obfuscation → malformed")
check(decide(policy(), req("crm.example.com", ips=[]))["reason_code"] == "MALFORMED_TARGET", "T8c DNS adı resolved_ips yok → malformed")
r = req("crm.example.com"); r["target"]["host"] = "crm.example.com\r\nX: 1"
check(decide(policy(), r)["reason_code"] == "MALFORMED_TARGET", "T8d CRLF host → malformed")

# T9 — tenant mismatch
check(decide(policy(), req("crm.example.com", path="/v1/x", tenant="t-X"))["reason_code"] == "POLICY_TENANT_MISMATCH", "T9 tenant mismatch")

# T10 — audit no-log (A11): endpoint KANONİK template (interpolesiz), interpole değer yalnız target.path'te
g = EA.EgressGate(policy())
r10 = req("crm.example.com", path="/v1/customers/C-SECRET-42")
r10["endpoint"] = "GET https://crm.example.com/v1/customers/{customer_id}"
g.decide(r10)
blob = json.dumps(g.audit, ensure_ascii=False)
check("C-SECRET-42" not in blob and "203.0.113.5" not in blob, "T10 audit interpole değer/IP sızmaz")
check(g.audit[0]["no_log"] is True, "T10b no_log işaretli")

# T11 — determinizm (A10)
a = decide(policy(), req("crm.example.com", path="/v1/x"))
b = decide(policy(), req("crm.example.com", path="/v1/x"))
check(json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True), "T11 determinizm")

# T12 — INVALID_POLICY (default-deny zorunlu)
try:
    EA.EgressGate(policy(default_action="allow"))
    check(False, "T12 default allow reddedilmeli")
except EA.PolicyError:
    check(True, "T12 default allow → PolicyError")

print("behavior: %d kontrol, %d başarısız" % (N, len(FAILS)))
for m in FAILS:
    print("  ✗ %s" % m)
sys.exit(0 if not FAILS else 1)
