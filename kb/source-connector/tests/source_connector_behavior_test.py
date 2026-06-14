#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""source_connector_behavior_test.py — WBS 6.1.2 davranış kapısı (T1–T10).

Bağımlılıksız (stdlib-only). Probe'un SyncEngine + connector adapter'larını (SharePoint/Confluence/
generic) sürer ve FR-KB-002 / S1–S10 davranışlarını assert eder. selftest'i tamamlar; CI'da koşar.
6.1.1 FormatExtractor devri (S5) gerçek ayıklayıcılarla doğrulanır.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import source_connector_probe as P  # noqa: E402

_passed = 0
_failed = 0


def check(cond, msg):
    global _passed, _failed
    if cond:
        _passed += 1
    else:
        _failed += 1
        print("  ✗ %s" % msg)


def run(scn, eng=None):
    eng = eng or P._engine()
    res, meta = P.run_scenario(scn, eng)
    gates = {s: o for s, o, _ in P.evaluate_gates(scn, res, meta, eng)}
    return res, meta, gates, eng


# T1 — FR-KB-002 / SR-KB-002: SharePoint connector en az bir dokümanı senkronize eder (S1).
def t1_sharepoint_syncs():
    scn = {"connector": "sharepoint", "tenant_id": "t-1", "kb_id": "kb-1", "scope": "site:s",
           "endpoint": "https://x.sharepoint.com", "region": "home",
           "source": [P._sp_item("a", "text", {"inline_text": "kurumsal politika metni"}, scope="organization")],
           "runs": [{"cursor": None}]}
    res, _, gates, _ = run(scn)
    check(res[0]["counts"]["synced"] == 1, "T1: SharePoint 1 doküman senkronize")
    check(res[0]["items"][0]["source_system"] == "sharepoint", "T1: source_system=sharepoint")
    check(all(gates.values()), "T1: tüm kapılar geçer")


# T2 — Confluence connector da aynı SPI arkasında senkronize eder (S1, ≥2 connector).
def t2_confluence_syncs():
    scn = {"connector": "confluence", "tenant_id": "t-1", "kb_id": "kb-1", "scope": "space:S",
           "endpoint": "https://x.atlassian.net", "region": "home",
           "source": [P._cf_item("a", "html", {"inline_text": "<html><body><p>wiki sayfa icerigi</p></body></html>"})],
           "runs": [{"cursor": None}]}
    res, _, gates, _ = run(scn)
    check(res[0]["counts"]["synced"] == 1 and res[0]["items"][0]["source_system"] == "confluence",
          "T2: Confluence senkronize")
    check(all(gates.values()), "T2: kapılar geçer")


# T3 — Delta idempotency (S3): aynı cursor mutasyonsuz → 0 değişiklik.
def t3_delta_idempotent():
    scn = {"connector": "sharepoint", "tenant_id": "t-1", "kb_id": "kb-1", "scope": "s",
           "endpoint": "https://x.sharepoint.com", "region": "home",
           "source": [P._sp_item("a", "text", {"inline_text": "icerik"}, scope="organization"),
                      P._sp_item("b", "text", {"inline_text": "icerik2"}, version=2, scope="organization")],
           "runs": [{"cursor": None}, {"cursor": "prev"}]}
    res, _, gates, _ = run(scn)
    check(res[0]["counts"]["synced"] == 2, "T3: run0 full=2")
    check(res[1]["counts"]["synced"] == 0 and res[1]["cursor_out"] == res[0]["cursor_out"],
          "T3: run1 idempotent noop")
    check(all(gates.values()), "T3: kapılar geçer")


# T4 — ACL mapping (S4): SharePoint sharingScope → classification eşlemesi.
def t4_acl_mapping():
    scn = {"connector": "sharepoint", "tenant_id": "t-1", "kb_id": "kb-1", "scope": "s",
           "endpoint": "https://x.sharepoint.com", "region": "home",
           "source": [
               P._sp_item("pub", "text", {"inline_text": "acik"}, version=1, scope="anonymous", principals=()),
               P._sp_item("org", "text", {"inline_text": "ic"}, version=2, scope="organization", principals=()),
               P._sp_item("spec", "text", {"inline_text": "ozel"}, version=3, scope="specific",
                          principals=("group:Legal",)),
           ], "runs": [{"cursor": None}]}
    res, _, gates, _ = run(scn)
    by = {i["external_id"]: i for i in res[0]["items"]}
    check(by["pub"]["classification"] == "public", "T4: anonymous→public")
    check(by["org"]["classification"] == "internal", "T4: organization→internal")
    check(by["spec"]["classification"] == "confidential" and "group:Legal" in by["spec"]["source_principals"],
          "T4: specific→confidential + principal")
    check(all(gates.values()), "T4: kapılar geçer")


# T5 — Extraction delegation (S5): 6.1.1 FormatExtractor gerçek docx fixture'ını ayıklar.
def t5_extraction_delegation():
    scn = {"connector": "sharepoint", "tenant_id": "t-1", "kb_id": "kb-1", "scope": "s",
           "endpoint": "https://x.sharepoint.com", "region": "home",
           "source": [P._sp_item("doc", "docx", {"fixture": "policy.docx"}, scope="organization")],
           "runs": [{"cursor": None}]}
    res, _, gates, _ = run(scn)
    d = res[0]["items"][0]
    check(d["status"] == "synced" and d["content_hash"], "T5: docx ayıklandı + content_hash")
    check(any(b["type"] == "table_row" for b in d["blocks"]), "T5: docx tablo yapısı (6.1.1 devri)")
    check(d["redaction_state"] == "pending" and d["no_log"], "T5: redaction pending + no_log devralındı")
    check(all(gates.values()), "T5: kapılar geçer")


# T6 — SSRF guard (S7): loopback host reddedilir, 0 synced.
def t6_ssrf_guard():
    scn = {"connector": "generic", "tenant_id": "t-1", "kb_id": "kb-1", "scope": "c",
           "endpoint": "http://10.0.0.5/internal", "region": "home",
           "source": [{"id": "g", "format": "text", "content": {"inline_text": "x"}, "version": 1,
                       "uri": "http://10.0.0.5/g", "acl": {"visibility": "internal"}}],
           "runs": [{"cursor": None}]}
    eng = P._engine(allowed_source_hosts=["10.0.0.5"])
    res, _, gates, _ = run(scn, eng)
    check(res[0]["status"] == "sync_error" and res[0]["error_class"] == "SSRF_BLOCKED",
          "T6: özel IP SSRF_BLOCKED")
    check(all(gates.values()), "T6: kapı geçer (0 synced sızıntı yok)")


# T7 — Tenant isolation (S6): farklı tenant aynı içerik → ayrı doc, sızıntı yok.
def t7_tenant_isolation():
    eng = P._engine()
    a = {"connector": "sharepoint", "tenant_id": "t-a", "kb_id": "kb-1", "scope": "s",
         "endpoint": "https://x.sharepoint.com", "region": "home",
         "source": [P._sp_item("d", "text", {"inline_text": "ayni icerik"}, scope="organization")],
         "runs": [{"cursor": None}]}
    b = json.loads(json.dumps(a)); b["tenant_id"] = "t-b"
    ra, _ = P.run_scenario(a, eng)
    rb, _ = P.run_scenario(b, eng)
    da, db = ra[0]["items"][0], rb[0]["items"][0]
    check(da["tenant_id"] == "t-a" and db["tenant_id"] == "t-b", "T7: her doc kendi tenant'ı")
    check(da["content_hash"] == db["content_hash"] and db.get("duplicate_of") is None,
          "T7: izole dedup uzayı (cross-tenant DUP yok)")


# T8 — Robustness (S8): bir öğe throttle olsa da diğerleri senkronlanır + retryable doğru.
def t8_robust_throttle():
    scn = {"connector": "sharepoint", "tenant_id": "t-1", "kb_id": "kb-1", "scope": "s",
           "endpoint": "https://x.sharepoint.com", "region": "home",
           "source": [
               P._sp_item("ok", "text", {"inline_text": "iyi metin"}, version=1, scope="organization"),
               P._sp_item("bad", "text", {"inline_text": "x"}, version=2, fault="TIMEOUT"),
           ], "runs": [{"cursor": None}]}
    res, _, gates, _ = run(scn)
    by = {i["external_id"]: i for i in res[0]["items"]}
    check(by["ok"]["status"] == "synced", "T8: iyi öğe synced (batch dayanıklı)")
    check(by["bad"]["error_class"] == "TIMEOUT" and by["bad"]["retryable"] is True, "T8: TIMEOUT retryable")
    check(all(gates.values()), "T8: kapılar geçer")


# T9 — Cursor persistence + counts reconcile (S9).
def t9_cursor_state():
    scn = {"connector": "confluence", "tenant_id": "t-1", "kb_id": "kb-1", "scope": "s",
           "endpoint": "https://x.atlassian.net", "region": "home",
           "source": [P._cf_item("a", "text", {"inline_text": "sayfa"}, version=1)],
           "runs": [{"cursor": None}, {"cursor": "prev", "bump": ["a"]}]}
    res, _, gates, _ = run(scn)
    check(res[1]["cursor_out"] > res[0]["cursor_out"], "T9: cursor bump sonrası ilerler")
    for r in res:
        c = r["counts"]
        check(c["total"] == c["synced"] + c["deleted"] + c["failed"], "T9: counts mutabakatı")
    check(all(gates.values()), "T9: kapılar geçer")


# T10 — Scope boundary (S10): embedding/vektör/erişim-kararı/credential alanı yok.
def t10_scope_boundary():
    scn = {"connector": "sharepoint", "tenant_id": "t-1", "kb_id": "kb-1", "scope": "s",
           "endpoint": "https://x.sharepoint.com", "region": "home",
           "source": [P._sp_item("a", "csv", {"inline_text": "k,v\n1,2\n"}, scope="organization")],
           "runs": [{"cursor": None}]}
    res, _, gates, _ = run(scn)
    d = res[0]["items"][0]
    forbidden = ("embedding", "vector", "chunk_ids", "index_id", "access_granted", "access_denied",
                 "token", "secret", "oauth_token")
    check(not any(k in d for k in forbidden), "T10: kapsam-dışı/credential alan yok")
    check(all(gates.values()), "T10: kapılar geçer")


def main():
    for fn in [t1_sharepoint_syncs, t2_confluence_syncs, t3_delta_idempotent, t4_acl_mapping,
               t5_extraction_delegation, t6_ssrf_guard, t7_tenant_isolation, t8_robust_throttle,
               t9_cursor_state, t10_scope_boundary]:
        fn()
    print("behavior: %d geçti, %d başarısız" % (_passed, _failed))
    if _failed == 0:
        print("OK 🟢 behavior %d/%d" % (_passed, _passed))
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
