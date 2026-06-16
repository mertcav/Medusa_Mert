#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WBS 13.1.1 — iki-app frontend ayrımı bağımsız davranış testi (A1–A12). Stdlib-only."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, MOD)
import frontend_apps_probe as P  # noqa: E402

REPO = P.REPO
results = []


def check(cond, label):
    results.append((bool(cond), label))


# A2 — iki ayrı app projesi (on-disk, gerçek)
check(P.app_is_separate_project("frontend/platform-app"), "A2 platform-app ayrı proje")
check(P.app_is_separate_project("frontend/tenant-app"), "A2 tenant-app ayrı proje")

# A3 — route group ayrımı (on-disk)
check(P.list_route_groups("frontend/platform-app") == ["(platform)"], "A3 platform-app yalnız (platform)")
check(sorted(P.list_route_groups("frontend/tenant-app")) == ["(tenant-admin)", "(workspace)"],
      "A3 tenant-app (tenant-admin)+(workspace)")

# A4 — ekran sayıları (on-disk)
check(len(P.list_screens("frontend/platform-app", "(platform)")) == 9, "A4 L0 9 ekran")
check(len(P.list_screens("frontend/tenant-app", "(tenant-admin)")) == 9, "A4 L1 9 ekran")
check(len(P.list_screens("frontend/tenant-app", "(workspace)")) == 17, "A4 L2 17 ekran")

# A5 — ÇEKİRDEK: platform-app'te yasak tenant iş verisi route'u YOK (on-disk recursive)
segs = P.all_route_segments("frontend/platform-app")
forbidden = {"live-calls", "recordings", "call", "transcript", "qa", "kb", "flows", "prompts",
             "campaigns", "agents", "builder", "voice", "tools"}
check(len(segs & forbidden) == 0, "A5 platform-app'te yasak route YOK (ÇEKİRDEK)")
# pozitif kontrol: bu iş verisi route'ları tenant-app (workspace) içinde VAR (doğru konum)
tn_segs = P.all_route_segments("frontend/tenant-app")
workspace_business = {"live-calls", "recordings", "call", "qa", "kb", "flows", "prompts",
                      "campaigns", "agents", "builder", "voice", "tools"}
check(workspace_business.issubset(tn_segs), "A5 iş verisi route'ları tenant-app'te mevcut (doğru konum)")

# A6 — deploy izolasyonu (topoloji)
topo = P.load_json(P.TOPOLOGY_PATH)
check(topo["apps"]["platform-app"]["public"] is False, "A6 platform-app public değil")
check(topo["apps"]["tenant-app"]["public"] is True, "A6 tenant-app public")
check(topo["apps"]["platform-app"]["auth_realm"] != topo["apps"]["tenant-app"]["auth_realm"],
      "A6 ayrı auth realm")

# A7 — cross-app import yok (on-disk)
check(len(P.scan_cross_app_import("frontend/platform-app", "@chanteur/tenant-app", "tenant-app")) == 0,
      "A7 platform-app cross-import yok")
check(len(P.scan_cross_app_import("frontend/tenant-app", "@chanteur/platform-app", "platform-app")) == 0,
      "A7 tenant-app cross-import yok")

# A8 — frontend hardcoded authz yok
check(len(P.scan_frontend_authz("frontend/platform-app")) == 0, "A8 platform-app hardcoded authz yok")
check(len(P.scan_frontend_authz("frontend/tenant-app")) == 0, "A8 tenant-app hardcoded authz yok")

# A10 — manifest bütünlüğü (determinizm)
check(P.canonical_hash(topo) == P.canonical_hash(P.load_json(P.TOPOLOGY_PATH)), "A10 topology_hash deterministik")

# A12 — .env.example gerçek değer yok
check(len(P.scan_env_example_has_value("frontend/platform-app")) == 0, "A12 platform .env.example boş RHS")
check(len(P.scan_env_example_has_value("frontend/tenant-app")) == 0, "A12 tenant .env.example boş RHS")

# karar motoru terminal'liği (A1)
r = P.evaluate_topology({"apps": []})
check(r["terminal"] == "FAIL", "A1 fail-closed boş istek → FAIL")

passed = sum(1 for ok, _ in results if ok)
for ok, label in results:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
print(f"\nbehavior: {passed}/{len(results)} 🟢" if passed == len(results) else f"\nbehavior: {passed}/{len(results)} 🔴")
sys.exit(0 if passed == len(results) else 1)
