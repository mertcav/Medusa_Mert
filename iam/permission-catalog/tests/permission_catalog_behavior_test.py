#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WBS 12.1.2 — bağımsız davranış testi (G1–G12). Probe motorunu kara-kutu olarak doğrular."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import permission_catalog_probe as P  # noqa: E402

CAT = P._load(P.CATALOG_PATH)
fails = []


def expect(cond, desc):
    print(f"  [{'🟢' if cond else '🔴'}] {desc}")
    if not cond:
        fails.append(desc)


def d(key):
    return P.decide({"key": key}, CAT)


print("=== 12.1.2 permission-catalog davranış testi ===")

# Gramer (G2)
expect(d("calls")["outcome"] == "REJECT", "tek segment → REJECT")
expect(d("calls:")["reason"] == "malformed_key", "trailing colon → malformed")
expect(d("1calls:read")["reason"] == "malformed_key", "rakam-başı segment → malformed")
expect(d("calls:read")["outcome"] == "VALID", "calls:read → VALID")
expect(d("resource:quota:manage")["outcome"] == "VALID", "3-segment key → VALID")

# parsed doğruluğu
p = d("resource:quota:manage")["parsed"]
expect(p["resource"] == "resource" and p["action"] == "manage" and not p["own"], "parsed resource/action/own")

# own disiplini (G5)
expect(d("calls:read:own")["outcome"] == "VALID", "calls:read:own → VALID")
expect(d("livecalls:read:own")["outcome"] == "VALID", "livecalls:read:own → VALID")
expect(d("org:manage:own")["reason"] == "own_not_permitted", "org:manage:own → own_not_permitted")
expect(d("calls:manage:own")["reason"] == "own_not_permitted", "own + action≠read → reject")
expect(d("calls:own:read")["reason"] == "own_misplaced", "own ortada → own_misplaced")

# çözüm
expect(d("calls:delete")["outcome"] == "UNKNOWN", "iyi-biçimli bilinmeyen → UNKNOWN")
expect(d("tenant:provision")["resolved"]["layer"] == "L0", "tenant:provision → L0")
expect(d("transcript:read")["resolved"]["tier"] == "B", "transcript:read → tier B")
expect(d("transcript:read")["resolved"]["content"] is True, "transcript:read → content")
expect(d("analytics:read")["resolved"]["content"] is False, "analytics:read → content değil")

# determinizm (G1) + terminal
expect(d("calls:read") == d("calls:read"), "determinizm: aynı girdi→aynı çıktı")
expect(all(d(k)["outcome"] in P.TERMINAL for k in ["calls:read", "x", "org:manage:own"]), "her çıktı terminal")

# katalog kapsamı: 44 key
expect(len(CAT["keys"]) == 44, f"katalog 44 key (gerçek {len(CAT['keys'])})")

# tüm katalog key'leri kendi kendine VALID (round-trip)
expect(all(d(k)["outcome"] == "VALID" for k in CAT["keys"]), "tüm katalog key'leri VALID (round-trip)")

# statik kapılar (G2–G12) ve selftest
expect(P.validate(verbose=False), "validate() tüm kapılar 🟢")
expect(P.selftest(verbose=False), "selftest() 🟢")

# integrity injection'lar ilgili kapıyı eler
for inj in ["grammar_break", "drop_key", "orphan_key", "own_break", "content_flip", "layer_flip", "catalog_tamper"]:
    t = P._apply_inject(CAT, inj)
    expect(P._integrity_trips(t, inj), f"inject {inj} → kapı eler")

print(f"\n{'🟢 TÜM TESTLER GEÇTİ' if not fails else '🔴 ' + str(len(fails)) + ' BAŞARISIZ'}")
sys.exit(1 if fails else 0)
