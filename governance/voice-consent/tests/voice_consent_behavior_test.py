#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
voice_consent_behavior_test.py — WBS 4.2.6 davranış kapısı (T1–T8)

Deterministik ses klonlama izin/kullanım kaydı karar motorunun (voice_consent_probe) yönetişim
davranışını HARD kapılara (P1–P8) karşı doğrular: onaylı ses, klon izin zorunluluğu, süre/iptal,
kapsam, tenant izolasyonu, kullanım kaydı, audit, maker-checker + WORM. Sunucu/credential GEREKMEZ;
stdlib-only. adapters/ + runtime/ davranış-testi disipliniyle aynı.

Koş: python3 tests/voice_consent_behavior_test.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import voice_consent_probe as P  # noqa: E402

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


print("T1 — yalnız ONAYLI ses kullanılabilir (P1, FR-TTS-006/V1)")
m = sim([P._reg(0), P._grant(10), P._approve(20), P._use(100)])
check(m["allow_total"] == 1 and gates_pass(m), "onaylı klon ses kullanımı → ALLOW")
m = sim([P._reg(0), P._grant(10), P._use(100)])  # onay yok
check(m["deny_by_reason"].get("NOT_APPROVED") == 1, "onaysız ses → DENY NOT_APPROVED")
check(m["unapproved_use_allowed"] == 0 and gates_pass(m), "uygunsuz ALLOW yok → P1 geçer")

print("T2 — klon ses GEÇERLİ izin gerektirir (P2, FR-TTS-007/V2)")
m = sim([P._reg(0), P._approve(20), P._use(100, cref=None)])
check(m["deny_by_reason"].get("NO_CONSENT") == 1, "izinsiz klon ses → DENY NO_CONSENT")
m = sim([P._reg(0), P._approve(20), P._use(100, cref="bilinmeyen")])
check(m["deny_by_reason"].get("UNKNOWN_CONSENT") == 1, "çözülemeyen consent_ref → DENY UNKNOWN_CONSENT")
check(gates_pass(m), "uygunsuz ALLOW yok → P2 geçer")

print("T3 — süre dolumu + geri çekme zorlanır (P3, FR-TTS-007/V3/V4)")
m = sim([P._reg(0), P._grant(10, expires=150), P._approve(20),
         P._use(100, uid="u1"), P._use(200, uid="u2"),
         P._revoke(250), P._use(300, uid="u3")])
check(m["deny_by_reason"].get("CONSENT_EXPIRED") == 1, "süre dolmuş izin → DENY CONSENT_EXPIRED")
check(m["deny_by_reason"].get("CONSENT_WITHDRAWN") == 1, "geri çekilmiş izin → DENY CONSENT_WITHDRAWN")
check(m["use_after_expiry"] == 0 and m["use_after_revoke"] == 0 and gates_pass(m),
      "süre/iptal sonrası kullanım yok → P3 geçer")

print("T4 — izin KAPSAMI (tenant/agent/purpose) zorlanır (P4, FR-TTS-007/V5)")
m = sim([P._reg(0), P._grant(10), P._approve(20),
         P._use(100, uid="u1", agent="a2"), P._use(200, uid="u2", purpose="marketing")])
check(m["deny_by_reason"].get("OUT_OF_SCOPE") == 2, "kapsam dışı agent + purpose → DENY OUT_OF_SCOPE")
check(m["out_of_scope_allowed"] == 0 and gates_pass(m), "kapsam aşımı yok → P4 geçer")

print("T5 — tenant izolasyonu (P5, FR-TEN-002/V6)")
m = sim([P._reg(0), P._grant(10), P._approve(20), P._use(100, tenant="t2")])
check(m["deny_by_reason"].get("CROSS_TENANT") == 1, "başka tenant'tan kullanım → DENY CROSS_TENANT")
check(m["cross_tenant_allowed"] == 0 and gates_pass(m), "cross-tenant sızıntı yok → P5 geçer")

print("T6 — izin verilen her klon kullanımı BİR usage record (P6, FR-TTS-007/V7)")
m = sim([P._reg(0), P._grant(10), P._approve(20),
         P._use(100, uid="u1"), P._use(200, uid="u2"), P._use(300, uid="u3")])
check(m["allowed_cloned_uses"] == 3 and m["usage_records"] == 3, "3 kullanım → 3 usage record")
check(m["missing_usage_record"] == 0 and gates_pass(m), "eksik kayıt yok → P6 geçer")
m = sim([P._reg(0), P._grant(10), P._approve(20), P._use(100)], emit_usage_record=False)
check(m["missing_usage_record"] >= 1 and not gates_pass(m), "kayıt üretilmezse → P6 eler")

print("T7 — tüm yaşam döngüsü + karar denetlenir (P7, FR-IAM-006/V8)")
m = sim([P._reg(0), P._grant(10), P._approve(20), P._revoke(30), P._use(100)])
check(m["unaudited_event"] == 0 and m["audit_events"] == m["expected_audit"],
      "register/grant/approve/revoke + use kararı denetlendi")
check(gates_pass(m), "audit tam → P7 geçer")

print("T8 — maker-checker + WORM + no-PII (P8, V9/V10/V11)")
# maker-checker normalde self-approval'ı reddeder
raised = False
try:
    sim([P._reg(0, by="designer-1"), P._approve(20, by="designer-1")])
except P.VoiceConsentError:
    raised = True
check(raised, "onaylayan=oluşturan → maker-checker reddeder (V9)")
# WORM normalde mutasyonu reddeder
raised = False
try:
    sim([P._reg(0), P._grant(10), {"kind": "mutate_record", "target": "consent", "ref": "c1", "t": 50}])
except P.VoiceConsentError:
    raised = True
check(raised, "consent kaydı mutasyonu → WORM reddeder (V10)")
# kayıtta voiceprint/PII → P8 eler
m = sim([P._reg(0), P._grant(10), P._approve(20),
         {"kind": "use", "use_id": "u1", "voice_id": "v-clone-1", "consent_ref": "c1",
          "tenant_id": "t1", "agent_id": "a1", "purpose": "collections", "t": 100, "voiceprint": "X"}])
check(m["pii_in_record"] >= 1 and not gates_pass(m), "kayıtta voiceprint/biyometrik → P8 eler (V11)")

# ── determinizm
ev = [P._reg(0), P._grant(10), P._approve(20), P._use(100)]
check(P.simulate({"events": ev}, P._pol()) == P.simulate({"events": ev}, P._pol()),
      "determinizm: aynı olay-akışı birebir aynı metrik (random yok)")

passed = sum(1 for ok, _ in results if ok)
total = len(results)
print("\nbehavior: %d/%d PASS" % (passed, total))
sys.exit(0 if passed == total else 1)
