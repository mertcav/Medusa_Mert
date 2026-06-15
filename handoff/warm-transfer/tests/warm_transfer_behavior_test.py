#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 9.2 — Warm transfer davranış kapısı (bağımsız, stdlib-only).

FSM yürütücüsünü doğrudan dürter ve SAD §7.3 warm transfer sözleşmesinin
gözlemlenebilir davranışlarını (T1–T7) doğrular. selftest probe'un İÇİNDEN koşar;
bu dosya probe'u DIŞARIDAN modül olarak çağırır (entegrasyon yüzeyi sabit kalsın diye).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import warm_transfer_probe as P  # noqa: E402

DL = P._load(P.SPEC_PATH)["gates"]["consult_deadline_ms"]
TGT = {"type": "QUEUE", "ref": "queue-support", "tenant_id": "t1"}


def _evs(announce=True, consult_code=200, whisper=True, whisper_to="agent",
         bridge=True, ai_exit=True):
    e = [{"kind": "decision", "t": 0}]
    if announce:
        e.append({"kind": "announce", "t": 1000})
    e += [{"kind": "consult", "t": 2000}, {"kind": "consult_ack", "t": 2200, "code": consult_code}]
    if consult_code == 200:
        if whisper:
            e.append({"kind": "whisper", "t": 2500, "to": whisper_to})
        if bridge:
            e.append({"kind": "bridge", "t": 2800})
        if ai_exit:
            e.append({"kind": "ai_exit", "t": 3000})
    return e


def main():
    results = []

    def t(name, cond):
        results.append((bool(cond), name))

    # T1 — Başarılı warm transfer: TRANSFERRED + köprü + AI çıkış + A-leg köprülü (C/W3/W4)
    r = P.run_transfer({"tenant_id": "t1", "target": TGT, "events": _evs(), "correlation_id": "c"}, DL)
    t("T1 başarı TRANSFERRED + köprü kurulu + AI çıktı + A-leg kapanmaz",
      r["terminal"] == "TRANSFERRED" and r["bridge_established"] and r["ai_exited"]
      and not r["a_leg_released"])

    # T2 — Whisper privacy: brifing yalnız temsilciye, müşteri duymaz (W3 / FR-HND-006)
    rok = P.run_transfer({"tenant_id": "t1", "target": TGT, "events": _evs()}, DL)
    rleak = P.run_transfer({"tenant_id": "t1", "target": TGT, "events": _evs(whisper_to="customer")}, DL)
    t("T2 whisper private OK; müşteriye sızınca W3 eler",
      rok["whisper_private"] and rok["violations"]["whisper_leaked"] == 0
      and rleak["violations"]["whisper_leaked"] > 0)

    # T3 — Köprü önce, çıkış sonra: köprüsüz AI çıkışı W4 eler, müşteri ortada (W4)
    r = P.run_transfer({"tenant_id": "t1", "target": TGT, "events": _evs(bridge=False)}, DL)
    t("T3 köprüsüz AI çıkışı → unbridged_exit + FAILED",
      r["violations"]["unbridged_exit"] > 0 and r["terminal"] == "FAILED")

    # T4 — Danışma başarısız → fail-safe: oturum düşmez, müşteri hold'dan geri alınır, fallback (W5)
    r = P.run_transfer({"tenant_id": "t1", "target": TGT, "events": _evs(consult_code=486)}, DL)
    t("T4 danışma meşgul → FAILED + fallback + A-leg korunur + hold'dan geri",
      r["terminal"] == "FAILED" and r["fallback"] and not r["a_leg_released"]
      and not r["customer_on_hold"])

    # T5 — Deadline guard: yanıt yok → hang yok, zaman aşımı → FAILED (W9)
    evs = [e for e in _evs() if e["kind"] not in ("consult_ack", "whisper", "bridge", "ai_exit")]
    r = P.run_transfer({"tenant_id": "t1", "target": TGT, "events": evs}, DL)
    t("T5 deadline → FAILED(DEADLINE), hung=0",
      r["terminal"] == "FAILED" and r["failure_class"] == "DEADLINE"
      and r["violations"]["hung_transfer"] == 0)

    # T6 — Tenant izolasyonu: cross-tenant hedef reddedilir (W10)
    r = P.run_transfer({"tenant_id": "t1", "target": {"type": "AGENT", "ref": "a", "tenant_id": "t2"},
                        "events": _evs()}, DL)
    t("T6 cross-tenant hedef → ihlal + FAILED",
      r["violations"]["cross_tenant_target"] > 0 and r["terminal"] == "FAILED")

    # T7 — Her terminal audit + outcome (W8 / FR-HND-008); blind consult gate eler (W2)
    rs = P.run_transfer({"tenant_id": "t1", "target": TGT, "events": _evs(), "correlation_id": "c"}, DL)
    rf = P.run_transfer({"tenant_id": "t1", "target": TGT, "events": _evs(consult_code=603)}, DL)
    rb = P.run_transfer({"tenant_id": "t1", "target": TGT, "events": _evs(announce=False)}, DL)
    G = P._load(P.SPEC_PATH)["gates"]
    t("T7 audit success+fail üretir; blind consult gate eler (W2)",
      rs["audit"] and rs["audit"]["outcome"] == "success"
      and rf["audit"] and rf["audit"]["outcome"] == "fail"
      and P._gate_eval(rb, G)[0] is False and rb["violations"]["blind_consult"] > 0)

    npass = sum(1 for ok, _ in results if ok)
    for ok, name in results:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print("\nbehavior: %d/%d %s" % (npass, len(results), "🟢" if npass == len(results) else "🔴"))
    return 0 if npass == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
