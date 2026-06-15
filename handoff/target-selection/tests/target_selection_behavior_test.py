#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 9.5 — Hedef seçimi davranış kapısı (R1–R10).

Probe'un selftest'inden BAĞIMSIZ, kara-kutu davranış kontrolleri: hedef seçim motorunun
karar sözleşmesini (FR-TEL-008/FR-HND-003) doğrudan doğrular. Stdlib-only, bağımlılıksız.
Çalıştırma: python3 tests/target_selection_behavior_test.py  → çıkış kodu.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import target_selection_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)


def _req(**kw):
    d = {"tenant_id": "t", "correlation_id": "c"}
    d.update(kw)
    return d


def run():
    cases = []

    def check(name, cond):
        cases.append((bool(cond), name))

    # R1 — her istek terminal'e ulaşır (SELECTED|UNRESOLVED)
    for rq in (_req(intent="billing_dispute", language="tr", reason="USER_REQUEST"),
               _req(intent="billing_dispute", language="de", reason="USER_REQUEST")):
        r = P.select(rq, SPEC)
        check("R1 terminal: %s" % r["terminal"], r["terminal"] in P.TERMINAL)

    # R2 — intent doğru departmana eşlenir
    r = P.select(_req(intent="tech_support", language="tr", reason="USER_REQUEST"), SPEC)
    check("R2 tech_support→tech departmanı", r["department"] == "tech")
    r = P.select(_req(intent="payment", language="tr", reason="USER_REQUEST"), SPEC)
    check("R2 payment→billing departmanı", r["department"] == "billing")

    # R3 — SELECTED hedef üç boyutu da taşır (department/skill_group/queue)
    r = P.select(_req(intent="billing_dispute", language="tr", reason="USER_REQUEST"), SPEC)
    check("R3 üç boyut dolu", all(r[d] for d in ("department", "skill_group", "queue")))
    check("R3 missing_dimension=0", r["violations"]["missing_dimension"] == 0)

    # R4 — exact seçilen kuyruğun skill grubu gerekli skill'leri (dil dahil) kapsar
    r = P.select(_req(intent="billing_dispute", language="tr", reason="USER_REQUEST"), SPEC)
    cfg = P._load(P.CONFIG_PATH)
    sg_skills = set(cfg["skill_groups"][r["skill_group"]])
    check("R4 seçilen kuyruk lang:tr+domain:billing kapsar",
          {"lang:tr", "domain:billing"} <= sg_skills)
    check("R4 mis_skill=0", r["violations"]["mis_skill"] == 0)

    # R5 — fallback zinciri: exact yoksa department_default; o da yoksa general
    r = P.select(_req(intent="tech_support", language="en", reason="USER_REQUEST"), SPEC)
    check("R5 exact yok→department_default", r["match_quality"] == "department_default")
    r = P.select(_req(intent="unknown_intent", language="tr", reason="USER_REQUEST"), SPEC)
    check("R5 eşleşme yok→general_fallback", r["match_quality"] == "general_fallback")
    check("R5 broken_fallback=0", r["violations"]["broken_fallback"] == 0)

    # R6 — reason→öncelik: ANGER/POLICY high, diğerleri normal; high priority_capable tercih
    r_high = P.select(_req(intent="tech_support", language="tr", reason="ANGER"), SPEC)
    r_norm = P.select(_req(intent="tech_support", language="tr", reason="LOW_CONFIDENCE"), SPEC)
    check("R6 ANGER→high + priority_capable kuyruk (q-tech-z)",
          r_high["priority"] == "high" and r_high["queue"] == "q-tech-z")
    check("R6 LOW_CONFIDENCE→normal", r_norm["priority"] == "normal")
    check("R6 priority_ignored=0", r_high["violations"]["priority_ignored"] == 0)

    # R7 — seçilen kuyruk bu tenant config'inde; cross-tenant yok
    own = {q["id"] for q in cfg["queues"] if isinstance(q, dict)}
    r = P.select(_req(intent="sales_inquiry", language="tr", reason="USER_REQUEST"), SPEC)
    check("R7 seçilen kuyruk tenant envanterinde", r["queue"] in own)
    check("R7 cross_tenant_target=0", r["violations"]["cross_tenant_target"] == 0)

    # R8 — her SELECTED hedef kanıt taşır (match_quality + fallback_tried + required_skills)
    r = P.select(_req(intent="billing_dispute", language="tr", reason="USER_REQUEST"), SPEC)
    check("R8 evidence match_quality taşır", r["evidence"]["match_quality"] == "exact")
    check("R8 evidence fallback_tried taşır", "exact" in r["evidence"]["fallback_tried"])
    check("R8 missing_evidence=0", r["violations"]["missing_evidence"] == 0)

    # R9 — her karar audit'e yazılır (department/queue/correlation_id/tenant)
    r = P.select(_req(intent="billing_dispute", language="tr", reason="USER_REQUEST"), SPEC)
    check("R9 audit queue taşır", r["audit"] is not None and r["audit"]["queue"] == "q-billing-tr")
    check("R9 audit tenant taşır", r["audit"]["tenant_id"] == "t")

    # R10 — UNRESOLVED fail-safe 9.7'ye yükselir; oturum düşmez (terminal üretilir)
    r = P.select(_req(intent="billing_dispute", language="de", reason="USER_REQUEST"), SPEC)
    check("R10 desteksiz dil→UNRESOLVED", r["terminal"] == "UNRESOLVED")
    check("R10 audit escalated_to=9.7", r["audit"]["escalated_to"] == "9.7")
    check("R10 broken_fallback=0 (gerçek no-target)", r["violations"]["broken_fallback"] == 0)

    npass = sum(1 for ok, _ in cases if ok)
    for ok, name in cases:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print("\nbehavior: %d/%d %s" % (npass, len(cases), "🟢" if npass == len(cases) else "🔴"))
    return 0 if npass == len(cases) else 1


if __name__ == "__main__":
    sys.exit(run())
