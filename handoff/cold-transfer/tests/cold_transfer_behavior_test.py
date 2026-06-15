#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 9.1 — Cold transfer davranış kapısı (bağımsız, stdlib-only).

FSM yürütücüsünü doğrudan dürter ve SAD §7.3 cold transfer sözleşmesinin
gözlemlenebilir davranışlarını (T1–T6) doğrular. selftest probe'un İÇİNDEN koşar;
bu dosya probe'u DIŞARIDAN modül olarak çağırır (entegrasyon yüzeyi sabit kalsın diye).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import cold_transfer_probe as P  # noqa: E402

DL = P._load(P.SPEC_PATH)["gates"]["refer_deadline_ms"]
TGT = {"type": "QUEUE", "ref": "queue-support", "tenant_id": "t1"}


def _evs(announce=True, ack=202, final_code=200, final_t=4000):
    e = [{"kind": "decision", "t": 0}]
    if announce:
        e.append({"kind": "announce", "t": 1000})
    e += [{"kind": "refer", "t": 1200}, {"kind": "refer_ack", "t": 1400, "code": ack}]
    if ack == 202:
        e.append({"kind": "notify", "t": final_t, "code": final_code, "final": True})
    return e


def main():
    results = []

    def t(name, cond):
        results.append((bool(cond), name))

    # T1 — Başarılı cold transfer: TRANSFERRED + A-leg serbest + fire-and-forget (C3/C5)
    r = P.run_transfer({"tenant_id": "t1", "target": TGT, "events": _evs(), "correlation_id": "c"}, DL)
    t("T1 başarı TRANSFERRED + A-leg serbest + köprü yok",
      r["terminal"] == "TRANSFERRED" and r["a_leg_released"] and not r["bridged"])

    # T2 — REFER reddi → fail-safe: oturum düşmez, fallback (C4 / FR-HND-007)
    r = P.run_transfer({"tenant_id": "t1", "target": TGT, "events": _evs(ack=486)}, DL)
    t("T2 REFER reddi → FAILED + fallback + A-leg korunur",
      r["terminal"] == "FAILED" and r["fallback"] and not r["a_leg_released"])

    # T3 — Deadline guard: hang yok, zaman aşımı → FAILED (C8)
    r = P.run_transfer({"tenant_id": "t1", "target": TGT, "events": _evs(final_t=1200 + DL + 3000)}, DL)
    t("T3 deadline → FAILED(DEADLINE), hung=0",
      r["terminal"] == "FAILED" and r["failure_class"] == "DEADLINE" and r["violations"]["hung_transfer"] == 0)

    # T4 — Tenant izolasyonu: cross-tenant hedef reddedilir (C9)
    r = P.run_transfer({"tenant_id": "t1", "target": {"type": "AGENT", "ref": "a", "tenant_id": "t2"},
                        "events": _evs()}, DL)
    t("T4 cross-tenant hedef → ihlal + FAILED",
      r["violations"]["cross_tenant_target"] > 0 and r["terminal"] == "FAILED")

    # T5 — Her terminal audit üretir + outcome (C7 / FR-HND-008)
    rs = P.run_transfer({"tenant_id": "t1", "target": TGT, "events": _evs(), "correlation_id": "c"}, DL)
    rf = P.run_transfer({"tenant_id": "t1", "target": TGT, "events": _evs(ack=603)}, DL)
    t("T5 başarı+başarısızlık ikisi de audit/outcome üretir",
      rs["audit"] and rs["audit"]["outcome"] == "success" and rf["audit"] and rf["audit"]["outcome"] == "fail")

    # T6 — Blind REFER yakalanır (C2): anonssuz aktarım gate'i eler
    r = P.run_transfer({"tenant_id": "t1", "target": TGT, "events": _evs(announce=False)}, DL)
    G = P._load(P.SPEC_PATH)["gates"]
    t("T6 blind REFER → gate eler (C2)", P._gate_eval(r, G)[0] is False and r["violations"]["blind_refer"] > 0)

    npass = sum(1 for ok, _ in results if ok)
    for ok, name in results:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print("\nbehavior: %d/%d %s" % (npass, len(results), "🟢" if npass == len(results) else "🔴"))
    return 0 if npass == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
