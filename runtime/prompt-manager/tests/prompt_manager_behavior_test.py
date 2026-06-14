#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prompt_manager_behavior_test.py — WBS 3.2.3 davranış kapısı (T1–T8)

Deterministik Prompt Manager'ın (prompt_manager_probe.PromptManager) versiyonlu sabit system prompt
enjeksiyon davranışını HARD kapılara (P1–P8) karşı doğrular. Sunucu/credential GEREKMEZ; stdlib-only.
3.2.2 (summarization_behavior_test) + 3.2.1 (session_memory_behavior_test) disipliniyle aynı.

Koş: python3 tests/prompt_manager_behavior_test.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import prompt_manager_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
GATES = SPEC.get("gates", {})
PARAMS = dict(P.DEFAULT_PARAMS)

results = []


def check(ok, label):
    results.append((bool(ok), label))
    print("  %s %s" % ("✓" if ok else "✗", label))


def gates_pass(m):
    return all(ok for ok, _ in P.evaluate(GATES, m))


print("T1 — versiyon sabitleme + kayıt (P1/P8)")
m = P._run([P._pin(0, vid="pv-9", vno=9), P._seg(100, "user_turn", 80), P._asm(200), P._end(300)], PARAMS)
check(m["pinned"] and m["pinned_version_no"] == 9, "yayımlanmış versiyon v9 sabitlendi")
check(m["version_recorded"] and m["version_drift"] == 0, "versiyon kaydedildi + drift=0 (FR-LLM-011)")
check(gates_pass(m), "tüm kapılar geçer")

print("T2 — system değişmezliği: caller/KB system'i değiştiremez (P2)")
m = P._run(P._basic_call(override=True), PARAMS)
check(m["system_mutated"] == 0 and m["system_hash_matches"], "assembled system == pinned gövde (FR-LLM-006)")
check(m["content_in_system_role"] == 0, "caller/KB içeriği system rolünde değil (P3)")
check(gates_pass(m), "tüm kapılar geçer")

print("T3 — override yapısal çit: görülür ama uygulanmaz (P4)")
m = P._run(P._basic_call(override=True), PARAMS)
check(m["override_seen"] >= 1, "düşük-güven override görüldü (injection girişimi)")
check(m["override_applied"] == 0, "override system'e UYGULANMADI (yapısal çit; semantik → 3.3.1)")
check(gates_pass(m), "tüm kapılar geçer")

print("T4 — yetki sırası: system önce/en yüksek (P5)")
m = P._run(P._basic_call(), PARAMS)
check(m["order_violation"] == 0, "system→policy→history→kb→user precedence korunur")
m_bad = P._run(P._basic_call(), PARAMS, system_first=False)
check(m_bad["order_violation"] >= 1 and not gates_pass(m_bad), "system sona konursa P5 eler (yetki inversiyonu)")

print("T5 — yayımlanmış-yalnız + fail-closed (P8)")
ok = P._raises(lambda: P._run([P._pin(0, published=False), P._seg(100, "user_turn", 80), P._asm(200), P._end(300)]))
check(ok, "published_only açık → yayımlanmamış versiyon reddedilir (fail-closed)")
m = P._run([P._pin(0, published=False), P._seg(100, "user_turn", 80), P._asm(200), P._end(300)], PARAMS, published_only=False)
check(m["unpublished_injected"] >= 1 and not gates_pass(m), "published_only kapalı → enjekte edilir, P8 eler")

print("T6 — çağrı-içi versiyon drift reddi (P1)")
ok = P._raises(lambda: P._run([P._pin(0, vid="pv-1"), P._asm(100), P._pin(200, vid="pv-2", shash="sys-h-2"),
                               P._asm(300), P._end(400)]))
check(ok, "stable_version açık → çağrı-içi farklı versiyona repin reddedilir")
m = P._run([P._pin(0, vid="pv-1"), P._asm(100), P._pin(200, vid="pv-2", shash="sys-h-2"), P._asm(300), P._end(400)],
           PARAMS, stable_version=False)
check(m["version_drift"] >= 1 and not gates_pass(m), "stable_version kapalı → drift>0, P1 eler")

print("T7 — tenant/agent izolasyon (P7)")
ok = P._raises(lambda: P._run([P._pin(0), P._seg(100, "user_turn", 80, tenant="t-other"), P._asm(200), P._end(300)]))
check(ok, "izolasyon açık → cross-tenant segment reddedilir")
m = P._run([P._pin(0), P._seg(100, "user_turn", 80, tenant="t-other"), P._asm(200), P._end(300)],
           PARAMS, tenant_isolation=False)
check(m["cross_tenant"] >= 1 and not gates_pass(m), "izolasyon kapalı → cross_tenant>0, P7 eler")

print("T8 — değişmezlik ihlali (mutate) + determinizm (P2/P6)")
m = P._run(P._basic_call(override=True), PARAMS, immutable_system=False)
check(m["system_mutated"] >= 1 and not m["system_hash_matches"], "immutable kapalı → system gövdesi saptı (FR-LLM-006 ihlali)")
check(m["override_applied"] >= 1 and not gates_pass(m), "override system'e uygulandı, P2/P3/P4 eler")
check(P._run(P._basic_call(override=True), PARAMS, immutable_system=False) == m, "determinizm: birebir aynı metrik (random yok)")

passed = sum(1 for ok, _ in results if ok)
total = len(results)
print("\nbehavior: %d/%d PASS" % (passed, total))
sys.exit(0 if passed == total else 1)
