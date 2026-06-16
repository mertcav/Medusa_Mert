#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 13.1.2 — Route-group middleware DAVRANIŞ kapısı (saf çekirdek decision matrisi).

route_middleware_probe.decide()/evaluate_request() aynasını bir karar matrisine karşı sınar
(oturum/realm/tenant-scope/panel/context). Bağımlılıksız (stdlib); sentetik (PII/token DEĞERİ yok).
Karar mantığı TS lib/middleware-core.ts ile birebir; canlı middleware e2e testi F1 CI'da (next start).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..")))

import route_middleware_probe as P  # noqa: E402


def case(label, app, path, session, now, requested_tenant, want_action, want_reason, want_headers=None):
    pol = P.policy_from_config(app)
    d = P.decide(pol, {"path": path, "session": session, "now": now,
                       "requested_tenant": requested_tenant, "correlation_id": "cid"})
    ok = d["action"] == want_action and d["reason"] == want_reason
    notes = []
    if not ok:
        notes.append(f"action={d['action']}/reason={d['reason']} ≠ {want_action}/{want_reason}")
    for k, v in (want_headers or {}).items():
        got = d["headers"].get(k)
        if got != v:
            ok = False
            notes.append(f"header {k}={got} ≠ {v}")
    return ok, label, notes


VALID_T = {"sub": "u", "realm": "tenant", "tenant_id": "t-1", "exp": 1000}
VALID_P = {"sub": "p", "realm": "platform", "tenant_id": None, "exp": 1000}
NOW = 500


def main():
    cases = [
        # T1 — OTURUM kapısı
        case("T1a oturumsuz → redirect/no_session", "tenant-app", "/admin/users", None, NOW, None, "redirect", "no_session"),
        case("T1b exempt /login → next/exempt", "tenant-app", "/login", None, NOW, None, "next", "exempt"),
        case("T1c exempt /api/auth/callback → next/exempt", "tenant-app", "/api/auth/callback", None, NOW, None, "next", "exempt"),
        case("T1d expired → redirect/expired_session", "tenant-app", "/admin/users",
             {"sub": "u", "realm": "tenant", "tenant_id": "t-1", "exp": 100}, NOW, None, "redirect", "expired_session"),
        # T2 — REALM/PANEL ayrımı (FR-IAM-008)
        case("T2a platform oturumu tenant-app → forbid/realm_mismatch", "tenant-app", "/workspace/qa", VALID_P, NOW, None, "forbid", "realm_mismatch"),
        case("T2b tenant oturumu platform-app → forbid/realm_mismatch", "platform-app", "/overview", VALID_T, NOW, None, "forbid", "realm_mismatch"),
        # T3 — TENANT SCOPE (FR-TEN-002)
        case("T3a tenant_id'siz tenant oturumu → forbid/missing_tenant_binding", "tenant-app", "/admin/org",
             {"sub": "u", "realm": "tenant", "tenant_id": None, "exp": 1000}, NOW, None, "forbid", "missing_tenant_binding"),
        case("T3b cross-tenant ?tenant=t-2 → forbid/cross_tenant_denied", "tenant-app", "/workspace/call", VALID_T, NOW, "t-2", "forbid", "cross_tenant_denied"),
        case("T3c aynı tenant ipucu → next/allow", "tenant-app", "/workspace/call", VALID_T, NOW, "t-1", "next", "allow"),
        case("T3d platform tenant_id taşıyor → forbid/unexpected_tenant_binding", "platform-app", "/tenants",
             {"sub": "p", "realm": "platform", "tenant_id": "t-x", "exp": 1000}, NOW, None, "forbid", "unexpected_tenant_binding"),
        # T4 — PANEL mapping + CONTEXT propagasyonu
        case("T4a L1 → panel/route-group/tenant-scope header", "tenant-app", "/admin/users", VALID_T, NOW, None, "next", "allow",
             {"x-panel": "L1", "x-route-group": "(tenant-admin)", "x-tenant-scope": "t-1", "x-app-tier": "L1+L2"}),
        case("T4b L2 → panel header", "tenant-app", "/workspace/live-calls", VALID_T, NOW, None, "next", "allow",
             {"x-panel": "L2", "x-route-group": "(workspace)", "x-app-plane": "tenant_application_plane"}),
        case("T4c L0 → panel header + tenant-scope YOK", "platform-app", "/overview", VALID_P, NOW, None, "next", "allow",
             {"x-panel": "L0", "x-route-group": "(platform)", "x-app-tier": "L0"}),
    ]
    # T4c ek: platform allow'da x-tenant-scope header bulunmamalı
    pol = P.policy_from_config("platform-app")
    d = P.decide(pol, {"path": "/overview", "session": VALID_P, "now": NOW, "requested_tenant": None, "correlation_id": "c"})
    cases.append((("x-tenant-scope" not in d["headers"]), "T4d platform allow'da x-tenant-scope YOK", []))

    passed = 0
    for ok, label, notes in cases:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        for n in notes:
            print(f"        · {n}")
        if ok:
            passed += 1
    print(f"\nbehavior: {passed}/{len(cases)} 🟢" if passed == len(cases) else f"\nbehavior: {passed}/{len(cases)} 🔴")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
