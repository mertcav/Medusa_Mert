#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 9.3 — Whisper transfer davranış kapısı (bağımsız, stdlib-only).

FSM yürütücüsünü doğrudan dürter ve SAD §7.3 whisper transfer sözleşmesinin
gözlemlenebilir davranışlarını (T1–T8) doğrular. selftest probe'un İÇİNDEN koşar;
bu dosya probe'u DIŞARIDAN modül olarak çağırır (entegrasyon yüzeyi sabit kalsın diye).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import whisper_transfer_probe as P  # noqa: E402

DL = P._load(P.SPEC_PATH)["gates"]["join_deadline_ms"]
TGT = {"type": "QUEUE", "ref": "queue-support", "tenant_id": "t1"}


def _evs(announce=True, join_code=200, whisper=True, whisper_to="agent",
         ai_exit=True, hold=False):
    e = [{"kind": "decision", "t": 0}]
    if announce:
        e.append({"kind": "announce", "t": 1000})
    if hold:
        e.append({"kind": "hold", "t": 1200})
    e += [{"kind": "agent_join", "t": 2000}, {"kind": "join_ack", "t": 2200, "code": join_code}]
    if join_code == 200:
        if whisper:
            e.append({"kind": "whisper", "t": 2800, "to": whisper_to})
        if ai_exit:
            e.append({"kind": "ai_exit", "t": 3200})
    return e


def main():
    results = []

    def t(name, cond):
        results.append((bool(cond), name))

    # T1 — Başarılı whisper transfer: HANDED_OFF + temsilci mevcut + AI çıkış + müşteri canlı (H4/H7)
    r = P.run_transfer({"tenant_id": "t1", "target": TGT, "events": _evs(), "correlation_id": "c"}, DL)
    t("T1 başarı HANDED_OFF + temsilci mevcut + AI çıktı + müşteri canlı",
      r["terminal"] == "HANDED_OFF" and r["agent_joined"] and r["ai_exited"]
      and r["customer_live"])

    # T2 — Whisper privacy: brifing yalnız temsilciye, müşteri (canlı) duymaz (H3 / FR-HND-006)
    rok = P.run_transfer({"tenant_id": "t1", "target": TGT, "events": _evs()}, DL)
    rleak = P.run_transfer({"tenant_id": "t1", "target": TGT, "events": _evs(whisper_to="customer")}, DL)
    t("T2 whisper private OK; müşteriye sızınca H3 eler",
      rok["whisper_private"] and rok["violations"]["whisper_leaked"] == 0
      and rleak["violations"]["whisper_leaked"] > 0)

    # T3 — No-hold (warm'dan ayrım): müşteri hold'a alınırsa H4 eler (H4)
    rok = P.run_transfer({"tenant_id": "t1", "target": TGT, "events": _evs()}, DL)
    rhold = P.run_transfer({"tenant_id": "t1", "target": TGT, "events": _evs(hold=True)}, DL)
    G = P._load(P.SPEC_PATH)["gates"]
    t("T3 müşteri canlı OK; hold edilince H4 eler (no-hold)",
      rok["customer_live"] and rok["violations"]["customer_held"] == 0
      and rhold["violations"]["customer_held"] > 0 and P._gate_eval(rhold, G)[0] is False)

    # T4 — Premature exit: temsilci mevcut değilken AI çıkışı H7 eler, müşteri ortada (H7)
    evs = [{"kind": "decision", "t": 0}, {"kind": "announce", "t": 1000},
           {"kind": "agent_join", "t": 2000}, {"kind": "ai_exit", "t": 2400}]
    r = P.run_transfer({"tenant_id": "t1", "target": TGT, "events": evs}, DL)
    t("T4 temsilci-yokken AI çıkışı → premature_exit + FAILED",
      r["violations"]["premature_exit"] > 0 and r["terminal"] == "FAILED")

    # T5 — Temsilci katılımı başarısız → fail-safe: oturum düşmez, müşteri canlı korunur, fallback (H5)
    r = P.run_transfer({"tenant_id": "t1", "target": TGT, "events": _evs(join_code=486)}, DL)
    t("T5 temsilci meşgul → FAILED + fallback + müşteri canlı korunur",
      r["terminal"] == "FAILED" and r["fallback"] and r["customer_session_preserved"]
      and r["customer_live"])

    # T6 — Deadline guard: yanıt yok → hang yok, zaman aşımı → FAILED (H9)
    evs = [e for e in _evs() if e["kind"] not in ("join_ack", "whisper", "ai_exit")]
    r = P.run_transfer({"tenant_id": "t1", "target": TGT, "events": evs}, DL)
    t("T6 deadline → FAILED(DEADLINE), hung=0",
      r["terminal"] == "FAILED" and r["failure_class"] == "DEADLINE"
      and r["violations"]["hung_transfer"] == 0)

    # T7 — Tenant izolasyonu: cross-tenant hedef reddedilir (H10)
    r = P.run_transfer({"tenant_id": "t1", "target": {"type": "AGENT", "ref": "a", "tenant_id": "t2"},
                        "events": _evs()}, DL)
    t("T7 cross-tenant hedef → ihlal + FAILED",
      r["violations"]["cross_tenant_target"] > 0 and r["terminal"] == "FAILED")

    # T8 — Her terminal audit + outcome (H11 / FR-HND-008); blind join gate eler (H2)
    rs = P.run_transfer({"tenant_id": "t1", "target": TGT, "events": _evs(), "correlation_id": "c"}, DL)
    rf = P.run_transfer({"tenant_id": "t1", "target": TGT, "events": _evs(join_code=603)}, DL)
    rb = P.run_transfer({"tenant_id": "t1", "target": TGT, "events": _evs(announce=False)}, DL)
    t("T8 audit success+fail üretir; blind join gate eler (H2)",
      rs["audit"] and rs["audit"]["outcome"] == "success"
      and rf["audit"] and rf["audit"]["outcome"] == "fail"
      and P._gate_eval(rb, G)[0] is False and rb["violations"]["blind_join"] > 0)

    npass = sum(1 for ok, _ in results if ok)
    for ok, name in results:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print("\nbehavior: %d/%d %s" % (npass, len(results), "🟢" if npass == len(results) else "🔴"))
    return 0 if npass == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
