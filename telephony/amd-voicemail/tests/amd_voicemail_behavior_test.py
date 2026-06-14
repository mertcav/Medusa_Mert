#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
amd_voicemail_behavior_test.py — WBS 2.1.9 davranış kapısı (algılama+bırakma mantığı, bağımlılıksız).

probe statik invariant'ları doğrular; bu test ALGILAMA/AKSİYON MANTIĞINI bağımsız doğrular:
  T1 sınıflandırma (A1/A2)  — insan/makine net sinyallerde doğru; tek zayıf sinyal makine'ye yetmez
  T2 belirsiz (A3)          — eşik altı güven → unknown → treat_as_human (voicemail bırakılmaz)
  T3 kaynak önceliği        — yüksek-güven CPaaS ipucu kullanılır; düşük-güven → heuristiğe düşer
  T4 voicemail bırak (A4/A7)— makine+bip+uyum+ifşa → left/voicemail_left (billable, bip sonrası)
  T5 uyum kapıları (A5/A6)  — ifşa yok / consent / DNC → not_left_compliance; policy off → not_left_policy_off
  T6 determinizm + sınır    — aynı signals → aynı sonuç (A8); bip yok → not_left_no_beep (A4)

Saf stdlib; probe'u import eder. Çıkış kodu 0 = tüm assertion geçti.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import amd_voicemail_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
TAX = P._reason_taxonomy()


def _c(policy_ref="campaign-voicemail", **sig):
    s = {"cpaas_amd": None, "cpaas_amd_confidence": None, "greeting_duration_ms": 1000,
         "beep_detected": False, "beep_at_ms": None, "silence_after_greeting_ms": 1500}
    s.update(sig)
    return {"now": "2026-06-15T12:00:00Z", "tenant_id": "t1", "policy_ref": policy_ref, "signals": s}


def _d(policy_ref="campaign-voicemail", consent="granted", dnc=False, disclosure=True, **sig):
    base = _c(policy_ref, **sig)
    base["message"] = {"message_ref": "tts:vm-tpl-001", "disclosure_included": disclosure}
    base["contact"] = {"contact_id": "c1", "consent_state": consent, "do_not_call": dnc}
    return base


def run():
    fails = []

    def ck(ok, label):
        if not ok:
            fails.append(label)

    # T1 — sınıflandırma (A1/A2)
    ck(P.classify(SPEC, _c(greeting_duration_ms=850, silence_after_greeting_ms=1800))["amd_class"] == "human",
       "T1 kısa karşılama+duraklama → human")
    ck(P.classify(SPEC, _c(greeting_duration_ms=4200, beep_detected=True, beep_at_ms=4400,
                           silence_after_greeting_ms=200))["amd_class"] == "machine",
       "T1 uzun karşılama+bip+kısa sessizlik → machine")
    ck(P.classify(SPEC, _c(beep_detected=True, greeting_duration_ms=1000,
                           silence_after_greeting_ms=1500))["amd_class"] != "machine",
       "T1/A2 tek bip (0.45<0.80) tek başına machine değil (aşırı-iddia yok)")

    # T2 — belirsiz (A3)
    r = P.classify(SPEC, _c(greeting_duration_ms=2500, silence_after_greeting_ms=700))
    ck(r["amd_class"] == "unknown", "T2 orta sinyaller → unknown")
    ck(r["resolved_party"] == "human" and r["amd_decision"] == "proceed_human", "T2/A3 unknown → treat_as_human")
    ck(r["unknown_fallback_applied"] is True, "T2 unknown_fallback_applied bayrağı")

    # T3 — kaynak önceliği
    r = P.classify(SPEC, _c(cpaas_amd="machine", cpaas_amd_confidence=0.95, greeting_duration_ms=1000))
    ck(r["amd_class"] == "machine" and r["signal_source"] == "cpaas_amd", "T3 yüksek-güven CPaaS → machine (cpaas)")
    r = P.classify(SPEC, _c(cpaas_amd="machine", cpaas_amd_confidence=0.40, greeting_duration_ms=1000,
                            silence_after_greeting_ms=1500))
    ck(r["signal_source"] == "media_heuristic", "T3 düşük-güven CPaaS → heuristiğe düşer")

    # T4 — voicemail bırak (A4/A7)
    r = P.drop(SPEC, _d(greeting_duration_ms=4200, beep_detected=True, beep_at_ms=4400,
                        silence_after_greeting_ms=200), TAX)
    ck(r["voicemail_outcome"] == "left" and r["reason_code"] == "voicemail_left", "T4 makine+bip+uyum → left/voicemail_left")
    ck(r["billable"] is True, "T4/A7 voicemail_left billable=true (2.1.7)")
    ck(r["message_started_after_beep"] is True, "T4/A4 mesaj bip sonrası başlar")

    # T5 — uyum kapıları (A5/A6) + policy off
    base_sig = dict(greeting_duration_ms=4200, beep_detected=True, beep_at_ms=4400, silence_after_greeting_ms=200)
    ck(P.drop(SPEC, _d(disclosure=False, **base_sig), TAX)["voicemail_outcome"] == "not_left_compliance",
       "T5/A5 ifşa yok → not_left_compliance")
    ck(P.drop(SPEC, _d(consent="withdrawn", **base_sig), TAX)["voicemail_outcome"] == "not_left_compliance",
       "T5/A6 consent withdrawn → not_left_compliance")
    ck(P.drop(SPEC, _d(consent="none", **base_sig), TAX)["voicemail_outcome"] == "not_left_compliance",
       "T5/A6 consent none → not_left_compliance")
    ck(P.drop(SPEC, _d(dnc=True, **base_sig), TAX)["voicemail_outcome"] == "not_left_compliance",
       "T5/A6 DNC → not_left_compliance")
    off = _d(policy_ref="detect-only", cpaas_amd="machine", cpaas_amd_confidence=0.95, **base_sig)
    ck(P.drop(SPEC, off, TAX)["voicemail_outcome"] == "not_left_policy_off", "T5/G1 policy off → not_left_policy_off")
    # uyum-engellenen bırakma reason_code = voicemail_machine_detected (retryable → 2.1.8)
    rc = P.drop(SPEC, _d(consent="withdrawn", **base_sig), TAX)["reason_code"]
    ck(rc == "voicemail_machine_detected" and TAX[rc]["retryable"] is True, "T5/A7 bırakılmadı → voicemail_machine_detected (retryable)")

    # T6 — determinizm + bip sınırı (A8/A4)
    a = P.classify(SPEC, _c(greeting_duration_ms=4200, beep_detected=True, beep_at_ms=4400))
    b = P.classify(SPEC, _c(greeting_duration_ms=4200, beep_detected=True, beep_at_ms=4400))
    ck(a == b, "T6/A8 aynı signals → aynı sonuç (deterministik)")
    # makine (CPaaS) ama bip yok → not_left_no_beep
    nb = _d(cpaas_amd="machine", cpaas_amd_confidence=0.95, greeting_duration_ms=4200,
            beep_detected=False, silence_after_greeting_ms=200)
    rnb = P.drop(SPEC, nb, TAX)
    ck(rnb["voicemail_outcome"] == "not_left_no_beep" and rnb["billable"] is False, "T6/A4 bip yok → not_left_no_beep (billable=false)")
    # bip max_beep_wait_ms'i aşarsa da geçersiz (beep_required)
    late = _d(cpaas_amd="machine", cpaas_amd_confidence=0.95, greeting_duration_ms=4200,
              beep_detected=True, beep_at_ms=99999, silence_after_greeting_ms=200)
    ck(P.drop(SPEC, late, TAX)["voicemail_outcome"] == "not_left_no_beep", "T6/A4 bip max_beep_wait sonrası → not_left_no_beep")

    if fails:
        for f in fails:
            print("  ✗ %s" % f)
        print("behavior: %d FAIL" % len(fails))
        return 1
    print("behavior: tüm assertion PASS ✅ (T1–T6)")
    return 0


if __name__ == "__main__":
    sys.exit(run())
