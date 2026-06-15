#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 7.1.5 — Sızıntı tarayıcısı + müşteri/audit ayrımı davranış testi (T1–T6).

Probe selftest'ten BAĞIMSIZ; sızıntı tarayıcısının (N1/N10) ve müşteri↔audit disjonksiyonunun (N4)
köşe durumlarını izole eder. Stdlib-only; gerçek PII/secret kullanmaz (sentetik — FR-TST-008).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import error_normalization_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
CAT = P._load(P.CONFIG_PATH)
VN = CAT["leak_scanner"]["vendor_names"]
IT = CAT["leak_scanner"]["internal_structure_terms"]

results = []


def check(cond, name):
    results.append((bool(cond), name))


def req(**kw):
    base = {"fault_class": "TIMEOUT", "correlation_id": "01JBEHTEST00001", "locale": "en-US", "channel": "voice"}
    base.update(kw)
    return base


# T1 — Tarayıcı bilinen kirli desen sınıflarını yakalar (her sınıf en az bir hit)
def t1():
    cases = {
        "vendor_name": "the deepgram call failed",
        "stack_trace": "Traceback (most recent call last)",
        "exception_class": "got a ValueError here",
        "sql_fragment": "ran SELECT id FROM accounts",
        "file_path": "see /var/log/app and main.go",
        "internal_url_host": "posted to https://x.example then failed",
        "ip_address": "host 192.168.1.9 down",
        "pii_email": "mailed jane@corp.test",
        "pii_card": "card 4111 1111 1111 1111",
    }
    for cls, txt in cases.items():
        hits = P.scan_leaks(txt, VN, IT, voice=False)
        check(any(h[0] == cls for h in hits), "T1 %s yakalanır" % cls)


# T2 — Temiz müşteri cümleleri yanlış-pozitif vermez (tüm katalog voice + örnek cümleler)
def t2():
    clean = [
        "I can connect you with an agent.",
        "Let's try again in a moment.",
        "We can go over the details again together.",
    ]
    for loc in CAT["supported_locales"]:
        for c in P._no_meta(SPEC["customer_categories"]):
            clean.append(CAT["messages"][loc][c]["voice"])
    for c in clean:
        check(not P.scan_leaks(c, VN, IT, voice=True), "T2 temiz: %r" % c[:40])


# T3 — Voice ek (N10): rakam + iç-yapı terimi voice'ta yakalanır, title/detail'de yakalanmaz
def t3():
    txt = "we will retry the gateway in 5 seconds"
    voice_hits = P.scan_leaks(txt, VN, IT, voice=True)
    nonvoice_hits = P.scan_leaks(txt, VN, IT, voice=False)
    check(any(h[0] == "digit" for h in voice_hits), "T3 voice rakam yakalar")
    check(any(h[0] == "internal_structure_term" for h in voice_hits), "T3 voice iç-yapı yakalar")
    check(not any(h[0] in ("digit", "internal_structure_term") for h in nonvoice_hits), "T3 non-voice rakam/iç-yapı yoksayar")


# T4 — Müşteri↔audit disjonksiyonu (N4): ham detay yalnız audit; müşteri/api temiz
def t4():
    o = P.normalize(req(fault_class="UPSTREAM_5XX", provider_code="TELNYX-911",
                        endpoint="https://crm.internal.svc", tenant_id="t-77",
                        internal_message="ConnectionError at db.py:5 from 10.0.0.1"), SPEC, CAT)
    surface = " ".join([o["customer"]["voice_message"], o["api_problem"]["title"], o["api_problem"]["detail"]])
    check("TELNYX-911" not in surface and "telnyx" not in surface.lower(), "T4 provider_code yüzeyde yok")
    check("internal.svc" not in surface and "10.0.0.1" not in surface, "T4 endpoint/IP yüzeyde yok")
    check(o["audit"]["provider_code"] == "TELNYX-911", "T4 provider_code audit'te")
    check(o["audit"]["customer_safe"] is False, "T4 audit customer_safe=false")
    check(o["leak_scan"]["clean"], "T4 üretilen yüzey temiz")


# T5 — FR-REC-005: kart/OTP audit internal_message'ta da maskelenir
def t5():
    o = P.normalize(req(fault_class="UPSTREAM_4XX",
                        internal_message="pan 4111 1111 1111 1111 and OTP code 482913"), SPEC, CAT)
    im = o["audit"]["internal_message"]
    check("4111 1111 1111 1111" not in im, "T5 kart maskeli")
    check("[REDACTED-CARD]" in im, "T5 kart placeholder")
    check("482913" not in im, "T5 OTP maskeli")


# T6 — RFC 9457 type alanı (URI) ve correlation_id YAPISAL — sızıntı kapsamı dışı; detail jenerik
def t6():
    o = P.normalize(req(fault_class="NOT_FOUND", channel="api"), SPEC, CAT)
    check(o["api_problem"]["type"].startswith("https://errors.rmcvoice.io/"), "T6 type dokümantasyon URI")
    # detail jenerik: internal_message hiç verilmedi → audit None, detail sabit katalog
    check(o["api_problem"]["detail"] == CAT["messages"]["en-US"]["NOT_FOUND"]["detail"], "T6 detail jenerik katalog")
    check(o["api_problem"]["correlation_id"] == "01JBEHTEST00001", "T6 correlation_id yapısal alan")


for fn in (t1, t2, t3, t4, t5, t6):
    fn()

npass = sum(1 for ok, _ in results if ok)
for ok, name in results:
    print("  %s %s" % ("🟢" if ok else "🔴", name))
print("behavior: %d/%d" % (npass, len(results)))
sys.exit(0 if npass == len(results) else 1)
