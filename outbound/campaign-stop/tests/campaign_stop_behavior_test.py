#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 10.1.7 — Kampanya durdurma düğmesi davranış kapısı (C1–C12).

Probe'un selftest'inden BAĞIMSIZ, kara-kutu davranış kontrolleri: kampanya kontrol durum
makinesinin + dialer admission kapısının sözleşmesini (FR-OUT-010 / SR-OUT-010) doğrudan doğrular.
Stdlib-only, bağımlılıksız. Çalıştırma: python3 tests/campaign_stop_behavior_test.py → çıkış kodu.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import campaign_stop_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)


def _req(**kw):
    d = {
        "tenant_id": "t", "correlation_id": "c", "campaign_id": "camp-x",
        "actor_role": "operations_manager",
        "command": "stop",
        "current_status": "running",
        "in_flight_calls": 3,
        "idempotency_key": "idem-x",
    }
    d.update(kw)
    return d


def run():
    cases = []

    def check(name, cond):
        cases.append((bool(cond), name))

    # C1 — her komut terminal sonuca ulaşır (APPLIED|NOOP|DENIED), stuck yok
    for cur, cmd in (("running", "stop"), ("stopped", "stop"), ("running", "pause"),
                     ("paused", "resume"), ("stopped", "resume"), ("running", "complete")):
        r = P.build(_req(current_status=cur, command=cmd, in_flight_calls=0), SPEC)
        check("C1 terminal (%s|%s): %s" % (cur, cmd, r["terminal"]), r["terminal"] in P.TERMINAL)
        check("C1 stuck_state=0 (%s|%s)" % (cur, cmd), r["violations"]["stuck_state"] == 0)

    # C2 — yetki: yetkili uygular, yetkisiz reddedilir
    r = P.build(_req(), SPEC)
    check("C2 yetkili APPLIED", r["terminal"] == "APPLIED" and r["violations"]["unauthorized"] == 0)
    r = P.build(_req(actor_role="human_agent"), SPEC)
    check("C2 yetkisiz DENIED (durum değişmez)", r["terminal"] == "DENIED" and r["to_status"] == "running")
    check("C2 yetkisiz reddetme ihlal değil", all(v == 0 for v in r["violations"].values()))
    r = P.build(_req(actor_role="human_agent"), SPEC, inject=["skip_auth"])
    check("C2 inject skip_auth → unauthorized yakalanır", r["violations"]["unauthorized"] > 0)

    # C3/C8 — geçerli geçiş; stop terminal / pause resumable
    r = P.build(_req(current_status="paused", command="resume", in_flight_calls=0), SPEC)
    check("C8 pause resumable: paused→running", r["to_status"] == "running" and r["terminal"] == "APPLIED")
    r = P.build(_req(current_status="stopped", command="resume", in_flight_calls=0), SPEC)
    check("C8 stop terminal: stopped+resume DENIED", r["terminal"] == "DENIED" and r["to_status"] == "stopped")
    check("C3 geçersiz geçiş ihlal değil (doğru reddetme)", r["violations"]["invalid_transition"] == 0)
    r = P.build(_req(current_status="stopped", command="resume", in_flight_calls=0), SPEC,
                inject=["invalid_transition"])
    check("C3 inject invalid_transition yakalanır", r["violations"]["invalid_transition"] > 0)

    # C4 — SR-OUT-010 ÇEKİRDEK: stop/pause sonrası yeni çağrı başlatılmaz
    for cmd in ("stop", "pause", "complete"):
        r = P.build(_req(command=cmd, in_flight_calls=0), SPEC)
        check("C4 %s → kapı kapalı" % cmd, r["dialer_gate"] == "closed")
        check("C4 %s → yeni çağrı=0" % cmd, r["new_calls_admitted_after"] == 0)
    r = P.build(_req(), SPEC, inject=["new_call_after_stop"])
    check("C4 inject new_call_after_stop yakalanır", r["violations"]["new_call_after_stop"] > 0)
    check("C4 kapı kapalıyken yeni çağrı=1 (ihlal)", r["new_calls_admitted_after"] == 1)
    # start/resume → kapı açılır (yeni çağrı admit edilebilir, ihlal değil)
    r = P.build(_req(current_status="paused", command="resume", in_flight_calls=0), SPEC)
    check("C4 resume → kapı açık", r["dialer_gate"] == "open")

    # C5 — in-flight graceful drain (SAD §6 never-drop)
    r = P.build(_req(in_flight_calls=5), SPEC)
    check("C5 stop → in-flight drain (düşürülmez)", r["inflight_disposition"] == "drain")
    check("C5 hard_drop_inflight=0", r["violations"]["hard_drop_inflight"] == 0)
    r = P.build(_req(in_flight_calls=5), SPEC, inject=["hard_drop_inflight"])
    check("C5 inject hard_drop_inflight yakalanır", r["violations"]["hard_drop_inflight"] > 0)
    check("C5 force_drop disposition", r["inflight_disposition"] == "force_drop")

    # C6 — idempotency: tekrar stop yan-etkisiz NOOP
    r = P.build(_req(current_status="stopped", in_flight_calls=0), SPEC)
    check("C6 stopped+stop → NOOP", r["terminal"] == "NOOP")
    check("C6 not_idempotent=0", r["violations"]["not_idempotent"] == 0)
    r = P.build(_req(current_status="stopped", in_flight_calls=0), SPEC, inject=["not_idempotent"])
    check("C6 inject not_idempotent yakalanır", r["violations"]["not_idempotent"] > 0)

    # C7 — tenant izolasyonu
    r = P.build(_req(), SPEC)
    check("C7 cross_tenant=0", r["violations"]["cross_tenant"] == 0)
    r = P.build(_req(), SPEC, inject=["cross_tenant"])
    check("C7 inject cross_tenant yakalanır", r["violations"]["cross_tenant"] > 0)
    r = P.build(_req(bind_tenant="t-other"), SPEC)
    check("C7 bind_tenant uyuşmazlığı yakalanır", r["violations"]["cross_tenant"] > 0)

    # C9 — kanıt: command + from→to + actor + kapı + idempotency
    r = P.build(_req(), SPEC)
    check("C9 evidence command taşır", r["evidence"]["command"] == "stop")
    check("C9 evidence from→to taşır", r["evidence"]["from_status"] == "running" and r["evidence"]["to_status"] == "stopped")
    check("C9 evidence dialer_gate taşır", r["evidence"]["dialer_gate"] == "closed")
    check("C9 missing_evidence=0", r["violations"]["missing_evidence"] == 0)

    # C10 — audit: her sonuç (APPLIED/NOOP/DENIED) audit'lenir
    for cur, cmd, exp in (("running", "stop", "APPLIED"), ("stopped", "stop", "NOOP"),
                          ("stopped", "resume", "DENIED")):
        r = P.build(_req(current_status=cur, command=cmd, in_flight_calls=0), SPEC)
        check("C10 audit (%s)=%s" % (exp, r["audit"] is not None),
              r["audit"] is not None and r["audit"]["result"] == exp)
    r = P.build(_req(), SPEC, inject=["no_audit"])
    check("C10 inject no_audit → missing_audit", r["violations"]["missing_audit"] > 0)

    # C11/C12 — sızıntı tarayıcı: yapısal/kimlik temiz, ham PII/telefon yakalanır
    check("C12 camp-001 kimlik temiz", P.scan_leaks('{"campaign_id": "camp-001"}') == [])
    check("C12 ham telefon alanı yakalanır", len(P.scan_leaks('{"customer_phone_value": "x"}')) > 0)

    npass = sum(1 for ok, _ in cases if ok)
    for ok, name in cases:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print("\nbehavior: %d/%d %s" % (npass, len(cases), "🟢" if npass == len(cases) else "🔴"))
    return 0 if npass == len(cases) else 1


if __name__ == "__main__":
    sys.exit(run())
