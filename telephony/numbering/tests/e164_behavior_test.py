#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
e164_behavior_test.py — WBS 2.1.5 E.164 + Caller ID davranış kapısı (T1–T6)

stdlib-only, bağımsız. numbering_probe.py çekirdeğini doğrudan çağırır (sunucu gerekmez).
managed-cpaas/framing_behavior_test.py + byoc/sdp_rtp_behavior_test.py deseni.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import numbering_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
META = P._meta(SPEC)


def _run():
    results = []

    def check(ok, label):
        results.append((bool(ok), label))

    # T1 — kanonik E.164 regex sınırları (≤15 hane, +[1-9]…)
    rx = P.CANONICAL_RE
    check(bool(rx.match("+12025550143")), "T1 geçerli E.164 eşleşir")
    check(not rx.match("12025550143"), "T1 '+' yoksa eşleşmez")
    check(not rx.match("+0123456789"), "T1 '+0' ile başlayamaz")
    check(not rx.match("+1234567890123456"), "T1 >15 hane eşleşmez")

    # T2 — biçim temizliği: boşluk/tire/parantez/nokta idempotent kanonik üretir
    a = P.normalize_e164("+90 (212) 345-67-89", "TR", META)
    b = P.normalize_e164("+902123456789", "TR", META)
    check(a == b == "+902123456789", "T2 biçim temizliği tek kanonik değer üretir")

    # T3 — IDD vs trunk ayrımı: '00 44…' (IDD) ile '0…' (trunk) farklı yorumlanır
    intl = P.normalize_e164("00 44 1632 960123", "TR", META)   # IDD → +44
    natl = P.normalize_e164("0 532 000 00 00", "TR", META)     # trunk → +90 (10 hane)
    check(intl == "+441632960123", "T3 '00'+CC IDD olarak çözülür")
    check(natl == "+905320000000", "T3 tek '0' trunk olarak çözülür (+90)")

    # T4 — NANP '1' trunk == ülke kodu çakışmasının doğru çözümü
    with_trunk = P.normalize_e164("1 202 555 0143", "US", META)
    without = P.normalize_e164("202 555 0143", "US", META)
    check(with_trunk == without == "+12025550143", "T4 NANP '1' trunk/CC çakışması doğru çözülür")

    # T5 — NSN uzunluk doğrulaması: fazla/eksik hane reddedilir (sessiz kırpma yok)
    def rejects(raw, reg):
        try:
            P.normalize_e164(raw, reg, META)
            return False
        except P.NumberError:
            return True
    check(rejects("+90212345", "TR"), "T5 kısa NSN reddi")
    check(rejects("+9021234567890", "TR"), "T5 uzun NSN reddi")

    # T6 — Caller ID seçimi anti-spoof + local-presence (deterministik)
    pool = {
        "default_region": "GB", "home_region": "uk-london",
        "numbers": [
            {"e164": "+441632960123", "direction": "both", "region": "uk-london", "caller_id_capable": True, "campaign_ids": []},
            {"e164": "+12025550143", "direction": "outbound", "region": "uk-london", "caller_id_capable": True, "campaign_ids": []},
        ],
    }
    uk, _ = P.select_caller_id(SPEC, pool, "+447700900999", home_region="uk-london")
    us, _ = P.select_caller_id(SPEC, pool, "+12025550199", home_region="uk-london")
    check(uk["e164"] == "+441632960123" and us["e164"] == "+12025550143",
          "T6 local-presence callee cc'ye göre doğru caller id")
    spoof = False
    try:
        P.select_caller_id(SPEC, pool, "+447700900999", requested="+15005550000")
    except P.NumberError:
        spoof = True
    check(spoof, "T6 havuz-dışı caller id talebi reddedilir (anti-spoof)")

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    for ok, label in results:
        print("  %s %s" % ("✓" if ok else "✗", label))
    print("e164_behavior_test: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(_run())
