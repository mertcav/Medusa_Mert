#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
resource_budget_behavior_test.py — WBS 3.1.4 davranış kapısı (T1–T8)

Guard'ın oturum-başı izleme + sınırlama davranışını uçtan uca doğrular (bağımlılıksız, stdlib-only).
`runtime/turn-taking/tests/turn_taking_behavior_test.py` (3.1.3) deseniyle birebir.

  T1 healthy             ≤soft → eylem yok (adillik)
  T2 warn-mitigated      WARN → özetleme bütçeye döndürür, shed yok (B5)
  T3 breach-shed         azaltma yetmez → grace sonrası kontrollü graceful shed (B2/B3)
  T4 monitoring          her aşım tespit + yayılır; izleme kapalı → tespitsiz (B4)
  T5 media-excluded      yüksek medya bütçeye girmez (B8)
  T6 cpu-breach          CPU aşımı özetlenemez → kontrollü shed
  T7 fairness            spurious eylem yok; bozuk politika spurious'u kanıtlar (B7)
  T8 determinizm+reddet  aynı giriş birebir; geçersiz örnek reddi (B10)
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import resource_budget_probe as P  # noqa: E402

BUDGET = {"mem_budget_mb": 15.0, "soft_threshold_mb": 12.0,
          "cpu_budget_mcore": 100.0, "cpu_soft_mcore": 80.0, "grace_samples": 2}
GATES = P._load(P.SPEC_PATH)["gates"]


def base(dialogue, **extra):
    c = dict(session_state=1.2, dialogue_memory=dialogue, prompt_context=1.4,
             adapter_state=1.4, runtime_overhead=0.9)
    c.update(extra)
    return c


def pt(t, comps, media=None, cpu=None):
    s = {"t": t, "components_mb": comps}
    if media is not None:
        s["media_mb"] = media
    if cpu is not None:
        s["cpu_mcore"] = cpu
    return s


def run(points, **pol):
    policy = {"enforce": True, "monitor": True, "mitigate": True,
              "spurious": False, "on_breach": "shed", "summarize_factor": 0.45}
    policy.update(pol)
    return P.simulate({"samples": points}, BUDGET, policy)


def gates_pass(m):
    return all(ok for ok, _ in P.evaluate(GATES, m))


def main():
    R = []

    def chk(ok, label):
        R.append((bool(ok), label))

    # ── T1 healthy: ≤soft → eylem yok (adillik) ──────────────────────────────────
    m = run([pt(0, base(2.0)), pt(6000, base(4.0)), pt(12000, base(5.0))])
    chk(m["breach_samples"] == 0 and m["mitigation_applied"] == 0, "T1 healthy: aşım/azaltma yok")
    chk(m["spurious_action"] == 0 and "healthy" in m["scenario"], "T1 healthy: spurious yok, senaryo=healthy")
    chk(gates_pass(m), "T1 healthy tüm kapıları geçer")

    # ── T2 warn-mitigated: özetleme bütçeye döndürür ─────────────────────────────
    m = run([pt(0, base(4.0)), pt(9000, base(7.0, rag_context=1.5)), pt(18000, base(7.0, rag_context=1.5))])
    chk(m["mitigation_applied"] == 2 and m["mitigation_effective"] == 2, "T2 warn: azaltma etkili")
    chk(m["breach_samples"] == 0 and m["shed_count"] == 0, "T2 warn: breach/shed önlendi")
    chk(m["peak_enforced_mb"] < m["peak_demand_mb"], "T2 warn: zorlanan < talep (özetleme küçülttü)")
    chk(gates_pass(m), "T2 warn-mitigated tüm kapıları geçer")

    # ── T3 breach-shed: graceful kontrollü shed ──────────────────────────────────
    big = base(22.0, rag_context=8.0)
    m = run([pt(0, base(4.0)), pt(7000, big), pt(14000, big), pt(21000, big)])
    chk(m["shed_count"] == 1 and m["shed_graceful"] is True, "T3 breach: 1 graceful kontrollü shed")
    chk(m["uncontrolled_oom"] == 0 and m["unbounded_overshoot"] == 0, "T3 breach: kontrolsüz OOM/aşım yok (B2/B3)")
    chk(m["breach_detected"] >= 2, "T3 breach: aşım tespit edildi")
    chk(gates_pass(m), "T3 breach-shed graceful sınırlama kapıları geçer")

    # ── T4 monitoring: aşım tespit/yayılır; izleme kapalı → tespitsiz (B4) ────────
    chk(m["missed_breach"] == 0 and m["breach_detected"] == m["breach_samples"],
        "T4 izleme açık: her aşım tespit (missed=0)")
    moff = run([pt(0, base(4.0)), pt(7000, big), pt(14000, big), pt(21000, big)], monitor=False)
    chk(moff["missed_breach"] >= 1 and moff["breach_detected"] == 0, "T4 izleme kapalı: tespitsiz aşım")
    chk(not gates_pass(moff), "T4 izleme kapalı B4 eler")

    # ── T5 media-excluded: medya bütçeye girmez (B8) ─────────────────────────────
    m = run([pt(0, base(4.0), media=10.0), pt(6000, base(5.0), media=12.0)])
    chk(m["media_excluded_mb"] == 12.0, "T5 media: 12MB medya izlendi")
    chk(m["peak_enforced_mb"] <= 12.0 and m["breach_samples"] == 0, "T5 media: bütçe ayak izi medyasız ≤soft")
    chk(gates_pass(m), "T5 media-excluded tüm kapıları geçer")

    # ── T6 cpu-breach: CPU özetlenemez → kontrollü shed ──────────────────────────
    m = run([pt(0, base(4.0), cpu=60), pt(7000, base(4.0), cpu=140),
             pt(14000, base(4.0), cpu=140), pt(21000, base(4.0), cpu=140)])
    chk(m["breach_samples"] >= 2 and m["shed_count"] == 1, "T6 cpu: CPU aşımı → kontrollü shed")
    chk(m["uncontrolled_oom"] == 0 and gates_pass(m), "T6 cpu-breach graceful kapıları geçer")

    # ── T7 fairness: spurious yok; bozuk politika spurious'u kanıtlar (B7) ────────
    healthy = [pt(0, base(2.0)), pt(6000, base(4.0)), pt(12000, base(5.0))]
    chk(run(healthy)["spurious_action"] == 0, "T7 adillik: sağlıklı oturuma müdahale yok")
    msp = run(healthy, spurious=True)
    chk(msp["spurious_action"] >= 1 and not gates_pass(msp), "T7 bozuk: spurious eylem B7 eler")

    # ── T8 determinizm + geçersiz örnek reddi (B10) ──────────────────────────────
    chk(run([pt(0, base(4.0)), pt(7000, big), pt(14000, big), pt(21000, big)])
        == run([pt(14000, big), pt(0, base(4.0)), pt(7000, big), pt(21000, big)]),
        "T8 determinizm: karışık t birebir aynı metrik (random yok)")
    rej = 0
    for bad in ([{"t": 0, "components_mb": {"nope": 1.0}}],
                [{"components_mb": base(4.0)}],
                [{"t": 0, "components_mb": {}}],
                []):
        try:
            P.simulate({"samples": bad}, BUDGET, {})
        except P.BudgetError:
            rej += 1
    chk(rej == 4, "T8 geçersiz örnek (bilinmeyen bileşen/zaman damgasız/boş/akış) reddedilir")

    passed = sum(1 for ok, _ in R if ok)
    total = len(R)
    for ok, label in R:
        print("  %s %s" % ("✓" if ok else "✗", label))
    print("resource_budget_behavior_test: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
