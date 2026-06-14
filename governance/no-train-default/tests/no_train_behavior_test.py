#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
no_train_behavior_test.py — WBS 5.8 davranış kapısı (T1–T12)

Deterministik no-train varsayılan disposition karar motorunun (no_train_probe) yönetişim davranışını
HARD kapılara (P1–P8) karşı doğrular: varsayılan no-train, sağlayıcı uygunluğu, sessiz-gevşetme yok,
süre/iptal, kapsam, tenant izolasyonu, profil en-kısıtlayıcı, audit/WORM, maker-checker + no-PII.
Sunucu/credential GEREKMEZ; stdlib-only. governance/ + adapters/ davranış-testi disipliniyle aynı.

Koş: python3 tests/no_train_behavior_test.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import no_train_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
GATES = SPEC.get("gates", {})

results = []


def check(ok, label):
    results.append((bool(ok), label))
    print("  %s %s" % ("✓" if ok else "✗", label))


def gates_pass(m):
    return all(ok for ok, _ in P.evaluate(GATES, m))


def sim(events, **pol):
    return P.simulate({"events": events}, P._pol(**pol))


print("T1 — VARSAYILAN no-train: opt-in'siz akış eğitime kapalı (P1, FR-LLM-012)")
m = sim([P._prov(0), P._bind(10), P._use(100, uid="u1"), P._use(200, uid="u2")])
check(m["no_train_uses"] == 2 and m["training_enabled_uses"] == 0, "opt-in'siz 2 use → effective no-train")
check(m["train_without_optin"] == 0 and gates_pass(m), "uygunsuz eğitim yok → P1 geçer")
m = sim([P._prov(0), P._bind(10), P._use(100)], enforce_no_train_default=False)
check(m["train_without_optin"] >= 1 and not gates_pass(m), "varsayılan zorlanmazsa → P1 eler")

print("T2 — SAĞLAYICI UYGUNLUĞU: no-train + no-log + bölge (P2, FR-LLM-012/FR-KB-010/NFR 10.7)")
m = sim([P._prov(0, no_train=False), P._bind(10), P._use(100)])
check(m["deny_by_reason"].get("PROVIDER_NOT_NO_TRAIN") == 1, "no-train yeteneksiz → DENY")
m = sim([P._prov(0, retention=["PROVIDER_DEFAULT"]), P._bind(10), P._use(100)])
check(m["deny_by_reason"].get("PROVIDER_LOGS_DATA") == 1, "log'layan retention → DENY")
m = sim([P._prov(0, regions=["us-east"]), P._bind(10, region="eu-west"), P._use(100)])
check(m["deny_by_reason"].get("REGION_VIOLATION") == 1 and gates_pass(m), "bölge dışı → DENY + P2 geçer")

print("T3 — SESSİZ GEVŞETME YOK: override yalnız-sıkılaştırır (P1, T3)")
raised = False
try:
    sim([P._prov(0), P._bind(10), {"kind": "set_override", "tenant_id": "t1", "no_train": False, "t": 30}])
except P.NoTrainError:
    raised = True
check(raised, "no-train gevşeten override → REDDEDİLİR (raise)")
m = sim([P._prov(0), P._bind(10, forbid=False), P._grant(20),
         {"kind": "set_override", "tenant_id": "t1", "no_train": True, "t": 30}, P._use(100, ref="o1")])
check(m["no_train_uses"] == 1 and m["training_enabled_uses"] == 0,
      "tightening override → geçerli opt-in olsa bile no-train")

print("T4 — OPT-IN MAKER-CHECKER (P8, ADR-012)")
raised = False
try:
    sim([P._prov(0), P._bind(10), P._grant(20, gby="x", aby="x")])
except P.NoTrainError:
    raised = True
check(raised, "opt-in onaylayan=oluşturan → maker-checker reddeder")

print("T5/T6 — OPT-IN süre dolumu + geri çekme → güvenli no-train (P3)")
m = sim([P._prov(0), P._bind(10), P._grant(20, expires=150), P._use(300, ref="o1")])
check(m["no_train_uses"] == 1 and m["training_after_expiry"] == 0, "süre dolmuş opt-in → no-train")
m = sim([P._prov(0), P._bind(10), P._grant(20), P._revoke(30), P._use(100, ref="o1")])
check(m["no_train_uses"] == 1 and m["training_after_revoke"] == 0, "geri çekilmiş opt-in → no-train")
m = sim([P._prov(0), P._bind(10), P._grant(20, expires=150),
         P._use(300, uid="u1", ref="o1"), P._revoke(350), P._use(400, uid="u2", ref="o1")],
        honor_expiry=False, honor_revocation=False)
check(m["training_after_expiry"] >= 1 and m["training_after_revoke"] >= 1 and not gates_pass(m),
      "honor kapatılırsa süre/iptal sonrası eğitim → P3 eler")

print("T7 — OPT-IN KAPSAMI (tenant/data_class) (P4)")
m = sim([P._prov(0), P._bind(10),
         P._grant(20, scope={"tenants": ["t1"], "data_classes": ["transcript"]}),
         P._use(100, ref="o1", dc="prompt")])
check(m["no_train_uses"] == 1 and m["out_of_scope_training"] == 0, "kapsam dışı data_class → no-train")
m = sim([P._prov(0), P._bind(10),
         P._grant(20, scope={"tenants": ["t1"], "data_classes": ["transcript"]}),
         P._use(100, ref="o1", dc="prompt")], enforce_scope=False)
check(m["out_of_scope_training"] >= 1 and not gates_pass(m), "kapsam zorlanmazsa → P4 eler")

print("T8 — TENANT İZOLASYONU (P5, FR-TEN-002)")
m = sim([P._prov(0), P._bind(10, tenant="t1"), P._bind(11, tenant="t2"),
         P._grant(20, tenant="t1"), P._use(100, ref="o1", tenant="t2")])
check(m["no_train_uses"] == 1 and m["cross_tenant_training"] == 0, "cross-tenant opt-in → no-train")

print("T9 — PROFİL EN-KISITLAYICI: regüle profil opt-in'i ezer (P6, DPIA §D3)")
m = sim([P._prov(0), P._bind(10, forbid=True), P._grant(20), P._use(100, ref="o1")])
check(m["no_train_uses"] == 1 and m["training_enabled_uses"] == 0 and m["forbidden_profile_training"] == 0,
      "yasaklı profil + geçerli opt-in → no-train (most-restrictive)")
m = sim([P._prov(0), P._bind(10, forbid=True), P._grant(20), P._use(100, ref="o1")],
        enforce_profile_restriction=False)
check(m["forbidden_profile_training"] >= 1 and not gates_pass(m), "profil ezme kapatılırsa → P6 eler")

print("T10 — DENETİM + WORM (P7, FR-IAM-006/FR-REC-009)")
m = sim([P._prov(0), P._bind(10), P._grant(20), P._revoke(30), P._use(100, ref="o1")])
check(m["unaudited_event"] == 0 and m["audit_events"] == m["expected_audit"], "tüm olay + karar denetlendi")
raised = False
try:
    sim([P._prov(0), P._grant(20), {"kind": "mutate_record", "target": "opt_in", "ref": "o1", "t": 50}])
except P.NoTrainError:
    raised = True
check(raised, "opt-in kaydı mutasyonu → WORM reddeder")

print("T11 — ALT-İŞLEYEN/DPA (P2, BRD §14.1)")
m = sim([P._prov(0, dpa=False), P._bind(10), P._use(100)])
check(m["deny_by_reason"].get("PROVIDER_NO_DPA") == 1 and gates_pass(m), "DPA'sız sağlayıcı → DENY + P2 geçer")

print("T12 — PII/İÇERİK YOK (P8, TM-I-09)")
m = sim([P._prov(0), P._bind(10),
         {"kind": "use", "use_id": "u1", "tenant_id": "t1", "provider_id": "prov-llm-A",
          "data_class": "prompt", "t": 100, "raw_prompt": "X"}])
check(m["pii_in_record"] >= 1 and not gates_pass(m), "kayıtta ham prompt/PII → P8 eler")

# ── determinizm
ev = [P._prov(0), P._bind(10), P._grant(20), P._use(100, ref="o1")]
check(P.simulate({"events": ev}, P._pol()) == P.simulate({"events": ev}, P._pol()),
      "determinizm: aynı olay-akışı birebir aynı metrik (random yok)")

passed = sum(1 for ok, _ in results if ok)
total = len(results)
print("\nbehavior: %d/%d PASS" % (passed, total))
sys.exit(0 if passed == total else 1)
