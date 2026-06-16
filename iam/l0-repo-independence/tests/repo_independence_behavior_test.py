#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 12.2.4 — L0 iş verisi repository bağımsızlığı davranış testi (R1–R12; bağımsız).

repo_independence_probe.build() motorunu DOĞRUDAN sürer; invariant'ları (SAD §14.4.2 / DB.md P3 / FR-IAM-008)
bağımsız assertion'larla doğrular. selftest'ten ayrı ikinci bir kanıt katmanıdır (12.1.x/12.2.x deseni).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MOD_DIR = os.path.dirname(HERE)
sys.path.insert(0, MOD_DIR)

import repo_independence_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
G = SPEC["gates"]


def req(**kw):
    d = {
        "request_id": "req-t", "plane": "platform_control_plane", "repository": "resource_quota_repo",
        "table": "usage_record", "db_role": "platform_ro", "grant_present": False,
    }
    d.update(kw)
    return d


def run():
    checks = []

    def ok(name, cond):
        checks.append((bool(cond), name))

    # R1 — determinizm + terminal + kanıt + default-FORBID
    r1 = P.build(req(), SPEC)
    r2 = P.build(req(), SPEC)
    ok("R1 determinizm (birebir)", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))
    ok("R1 terminal PERMIT/FORBID", r1["terminal"] in P.TERMINAL)
    ok("R1 kanıt tam", all(k in r1["evidence"] for k in
                          ("request_id", "plane", "repository", "data_class", "db_role", "model_hash")))
    ok("R1 default FORBID (malformed)", P.build(req(plane="bogus"), SPEC)["terminal"] == "FORBID")

    # R2 — plane separation (deploy izolasyonu)
    rcp = P.build(req(), SPEC, inject=["couple_planes"])
    ok("R2 couple_planes → plane_coupling>0 + kapı eler",
       rcp["violations"]["plane_coupling"] > 0 and P._gate_eval(rcp, G)[0] is False)
    ok("R2 internal_only korunur → plane_coupling=0", P.build(req(), SPEC)["violations"]["plane_coupling"] == 0)

    # R3 — classification coverage (fail-closed)
    ok("R3 bilinmeyen sınıf → FORBID (fail-closed)",
       P.build(req(repository="x_repo", table="x", data_class="bogus"), SPEC)["terminal"] == "FORBID")
    ru = P.build(req(repository="x_repo", table="x", data_class=None), SPEC, inject=["unclassify"])
    ok("R3 unclassify (zorla kabul) → unclassified_binding>0 + kapı eler",
       ru["violations"]["unclassified_binding"] > 0 and P._gate_eval(ru, G)[0] is False)

    # R4 — ÇEKİRDEK wiring bağımsızlığı: platform default forbidden repo wire etmez
    ok("R4 platform transcript_repo (content) → FORBID (wire etmez)",
       P.build(req(repository="transcript_repo", table="transcript"), SPEC)["terminal"] == "FORBID")
    ok("R4 platform agent_repo (config) → FORBID",
       P.build(req(repository="agent_repo", table="agent"), SPEC)["terminal"] == "FORBID")
    rwc = P.build(req(repository="transcript_repo", table="transcript"), SPEC, inject=["wire_content_in_platform"])
    ok("R4 wire_content_in_platform → wired_forbidden_repo>0 + kapı eler",
       rwc["violations"]["wired_forbidden_repo"] > 0 and P._gate_eval(rwc, G)[0] is False)
    rwf = P.build(req(repository="campaign_repo", table="campaign"), SPEC, inject=["wire_config_in_platform"])
    ok("R4 wire_config_in_platform → wired_forbidden_repo>0 + kapı eler",
       rwf["violations"]["wired_forbidden_repo"] > 0 and P._gate_eval(rwf, G)[0] is False)

    # R5 — ÇEKİRDEK grant bağımsızlığı (DB.md P3): platform_ro tenant iş verisi grant'i tutmaz
    ok("R5 platform_ro content grant yok → grant_on_content=0",
       P.build(req(repository="contact_repo", table="contact"), SPEC)["violations"]["grant_on_content"] == 0)
    rgc = P.build(req(repository="contact_repo", table="contact"), SPEC, inject=["grant_content_to_platform"])
    ok("R5 grant_content_to_platform → grant_on_content>0 + kapı eler",
       rgc["violations"]["grant_on_content"] > 0 and P._gate_eval(rgc, G)[0] is False)

    # R6 — ÇEKİRDEK defense in depth: data_reachable ⟺ wiring ∧ grant
    # tek katman regrese (wire) ama grant yok → data_reachable=0 (grant katmanı bağımsız tuttu)
    rw_only = P.build(req(repository="transcript_repo", table="transcript", grant_present=False),
                      SPEC, inject=["wire_content_in_platform"])
    ok("R6 yalnız wire regrese → data_reachable=0 (grant katmanı bağımsız tuttu)",
       rw_only["violations"]["data_reachable"] == 0 and rw_only["violations"]["wired_forbidden_repo"] > 0)
    # iki katman da regrese (wire + grant) → data_reachable>0
    rboth = P.build(req(repository="transcript_repo", table="transcript", grant_present=True),
                    SPEC, inject=["wire_content_in_platform"])
    ok("R6 wire ∧ grant ikisi de regrese → data_reachable>0 + kapı eler",
       rboth["violations"]["data_reachable"] > 0 and P._gate_eval(rboth, G)[0] is False)
    # design-iso pass (kompozisyon doğru reddeder) → tüm core sayaçlar 0
    rdi = P.build(req(repository="recording_repo", table="recording", grant_present=False), SPEC)
    ok("R6 design-iso: FORBID + data_reachable/wired/grant hepsi 0 + kapı geçer",
       rdi["terminal"] == "FORBID" and rdi["violations"]["data_reachable"] == 0
       and rdi["violations"]["wired_forbidden_repo"] == 0 and rdi["violations"]["grant_on_content"] == 0
       and P._gate_eval(rdi, G)[0] is True)

    # R7 — endpoint yüzey bağımsızlığı (API.md)
    rep = P.build(req(repository="transcript_repo", table="transcript"), SPEC, inject=["expose_business_endpoint"])
    ok("R7 expose_business_endpoint → l0_business_endpoint>0 + kapı eler",
       rep["violations"]["l0_business_endpoint"] > 0 and P._gate_eval(rep, G)[0] is False)

    # R8 — break-glass plane ayrımı
    rbd = P.build(req(repository="break_glass_content_repo", table="transcript"), SPEC, inject=["bg_in_default_plane"])
    ok("R8 bg_in_default_plane → bg_in_default>0 + kapı eler",
       rbd["violations"]["bg_in_default"] > 0 and P._gate_eval(rbd, G)[0] is False)

    # R9 — break-glass grant-gated
    bg_valid = dict(plane="break_glass_plane", repository="break_glass_content_repo", table="transcript",
                    db_role="breakglass_ro", grant_gated=True, grant_present=True)
    rbv = P.build(req(**bg_valid), SPEC)
    ok("R9 break_glass content + grant_gated → PERMIT + bg_standing_binding=0",
       rbv["terminal"] == "PERMIT" and rbv["violations"]["bg_standing_binding"] == 0)
    rbs = P.build(req(plane="break_glass_plane", repository="break_glass_content_repo", table="recording",
                      db_role="breakglass_ro", grant_gated=False), SPEC, inject=["bg_standing"])
    ok("R9 bg_standing (grant'sız admit) → bg_standing_binding>0 + kapı eler",
       rbs["violations"]["bg_standing_binding"] > 0 and P._gate_eval(rbs, G)[0] is False)

    # R10 — model bütünlük
    rmt = P.build(req(), SPEC, inject=["model_tamper"])
    ok("R10 model_tamper → model_tampered>0 + kapı eler",
       rmt["violations"]["model_tampered"] > 0 and P._gate_eval(rmt, G)[0] is False)
    ok("R10 model_hash deterministik", P.build(req(), SPEC)["model_hash"] == P.build(req(), SPEC)["model_hash"])

    # R11/R12 — gözlemlenebilirlik kardinalite + sır/PII yok
    ok("R11 repository/table label değil (trace only)",
       "repository" in SPEC["observability"]["high_cardinality_trace_only"]
       and "repository" not in SPEC["observability"]["low_cardinality_labels"])
    ok("R12 repo+tablo+sınıf+plane temiz (leak yok)",
       P.scan_leaks('{"repository":"call_repo","table":"call","data_class":"tenant_content","plane":"platform_control_plane"}') == [])
    ok("R12 PII alanı yakalanır", len(P.scan_leaks('{"contact_pii_value": "x"}')) > 0)
    ok("R12 karar çıktısında ham PII alanı yok",
       all(k not in json.dumps(r1) for k in ("transcript_text_value", "recording_audio_value", "contact_pii_value")))

    npass = sum(1 for c, _ in checks if c)
    for c, name in checks:
        print(("  ✓ " if c else "  ✗ ") + name)
    print("\nbehavior test: %d/%d %s" % (npass, len(checks), "🟢" if npass == len(checks) else "🔴"))
    return 0 if npass == len(checks) else 1


if __name__ == "__main__":
    sys.exit(run())
