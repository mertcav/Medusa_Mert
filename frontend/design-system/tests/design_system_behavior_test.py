#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 13.1.3 — Tasarım sistemi + i18n DAVRANIŞ kapısı (saf çekirdek + WCAG + parity).

design_system_probe aynalarını (negotiateLocale / t / contrast_ratio / catalog_violations) bir karar
matrisine karşı sınar. Bağımlılıksız (stdlib); sentetik (PII/credential DEĞERİ yok). i18n çekirdeği
TS lib/i18n/index.ts ile birebir; canlı a11y/i18n e2e (axe/lighthouse, dil değişimi) F1 CI'da.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..")))

import design_system_probe as P  # noqa: E402


def main():
    cases = []

    def ok(label, cond):
        cases.append((bool(cond), label))

    tr = P.load_json(os.path.join(P.I18N_DIR, "tr.json"))
    en = P.load_json(os.path.join(P.I18N_DIR, "en.json"))

    # locale müzakere precedence (query > çerez > Accept-Language > default)
    ok("locale: query kazanır", P.negotiate_locale(query="en", cookie="tr", accept_language="tr") == "en")
    ok("locale: çerez (query yok)", P.negotiate_locale(cookie="tr", accept_language="en") == "tr")
    ok("locale: Accept-Language", P.negotiate_locale(accept_language="en-GB,en;q=0.9") == "en")
    ok("locale: default tr", P.negotiate_locale() == "tr")
    ok("locale: desteklenmeyen → default", P.negotiate_locale(query="zz", cookie="qq") == "tr")

    # çeviri + interpolasyon (TR/EN)
    ok("t: TR save", P.translate(tr, "common.save") == "Kaydet")
    ok("t: EN save", P.translate(en, "common.save") == "Save")
    ok("t: TR nav workspace live_calls", P.translate(tr, "nav.workspace.live_calls") == "Canlı Çağrılar")
    ok("t: EN nav platform overview", P.translate(en, "nav.platform.overview") == "Overview")
    ok("t: interpolasyon", P.translate(en, "common.greeting", {"name": "Mira"}) == "Hello, Mira")
    ok("t: eksik anahtar → kendisi", P.translate(tr, "no.such.key") == "no.such.key")

    # TR↔EN canonical parity temiz
    ok("parity: canonical ihlalsiz", len(P.catalog_violations(tr, en)) == 0)
    # her app vendored katalog da parity temiz
    for app in P.APPS:
        ap = P.app_paths(app)
        v = P.catalog_violations(P.load_json(ap["tr"]), P.load_json(ap["en"]))
        ok(f"parity: {app} ihlalsiz", len(v) == 0)

    # parity ihlal tespiti
    ok("parity: missing_key yakalanır",
       any(k == "missing_key" for k, _ in P.catalog_violations({"a": "x", "b": "y"}, {"a": "x"})))
    ok("parity: placeholder_mismatch yakalanır",
       any(k == "placeholder_mismatch" for k, _ in P.catalog_violations({"g": "{name}"}, {"g": "{ad}"})))
    ok("parity: empty_value yakalanır",
       any(k == "empty_value" for k, _ in P.catalog_violations({"g": " "}, {"g": "x"})))

    # WCAG kontrast (gerçek hesap)
    ok("contrast: siyah/beyaz ≈21", abs(P.contrast_ratio("#000000", "#FFFFFF") - 21.0) < 0.1)
    ok("contrast: RMC mavi üstüne beyaz ≥4.5", P.contrast_ratio("#FFFFFF", "#1F4E79") >= 4.5)
    ok("contrast: açık gri beyaz üstüne <4.5", P.contrast_ratio("#9AA7B8", "#FFFFFF") < 4.5)
    pairs = P.load_json(P.TOKENS_PATH)["contrast_pairs"]
    ok("contrast: tüm token çifti geçer",
       all(P.contrast_ratio(p["fg"], p["bg"]) + 1e-9 >= p["min"] for p in pairs))

    # token/katalog parity (canonical == app vendored hash)
    th = P.canonical_hash(P.load_json(P.TOKENS_PATH))
    for app in P.APPS:
        ok(f"token-hash: {app} == canonical",
           P.canonical_hash(P.load_json(P.app_paths(app)["tokens"])) == th)

    passed = sum(1 for c, _ in cases if c)
    for c, label in cases:
        print(f"  [{'PASS' if c else 'FAIL'}] {label}")
    print(f"\ndavranış: {passed}/{len(cases)} 🟢" if passed == len(cases) else f"\ndavranış: {passed}/{len(cases)} 🔴")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
