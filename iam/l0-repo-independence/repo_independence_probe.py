#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 12.2.4 — L0 iş verisi repository bağımsızlığı (tasarımsal/design-time izolasyon) referans probe.

12. workstream'in (IAM & Erişim) TASARIM-ZAMANI L0⟂tenant İZOLASYON modülü ve F1-Must yeteneği. SAD §14.4.2
('Platform endpoint'leri TASARIM GEREĞİ tenant iş verisi [call/transcript/PII] repository'lerine BAĞLI
DEĞİLDİR; erişim yalnız break-glass akışıyla açılır') + DB.md P3 ('Platform [L0] rolleri tenant iş verisi
tablolarına REPOSITORY/GRANT düzeyinde bağlı DEĞİLDİR') + FR-IAM-008'i sahiplenir. 12.2.1 (HTTP guard) ve
12.2.3 (RLS) ÇALIŞMA-ANI kararlarından ÖNCEKİ katman: L0⟂tenant izolasyonu KOMPOZİSYON (wiring) ve DB GRANT
seviyesinde tasarımca DIŞLANIR — çalışma-anı guard regrese olsa bile L0 kodu tenant iş verisine ULAŞAMAZ.

İKİ BAĞIMSIZ TASARIM KATMANI (defense in depth, P2):

    (A) WIRING — platform_control_plane (L0, internal-only, ADR-011) kompozisyon kökü tenant_content/
        tenant_config repo'su WIRE ETMEZ; yalnız platform + tenant_metric + global_reference.
    (B) GRANT  — L0'ın bağlandığı platform_ro DB rolü tenant iş verisi tablolarında GRANT TUTMAZ (DB.md P3).

  data_reachable ⟺ wired_forbidden_repo ∧ grant_present  (AND; iki BAĞIMSIZ tasarım katmanı → tek katman
  regresyonu [yanlış wire VEYA stray grant] veriyi AÇMAZ; diğer katman bağımsız kapatır)

  Üçüncü çalışma-anı backstop: 12.2.3 RLS (CONSUMED) — platform realm tenant_scoped satırları break-glass'sız
  göremez (R7 platform_overreach=0). Design-time bağımsızlık + çalışma-anı RLS = üçlü savunma.

  RepoBindingRequest ─malformed─► plane sep. ─► classification ─► wiring ─► grant ─► reachability ─► endpoint/bg
        │              │             │              │              │         │            │              │
        │   ├─ request_id/plane/data_class+table/db_role eksik|geçersiz ───────────────► FORBID (malformed)
        │   ├─ platform default deploy_isolation kaybı ──────────────────────────────► plane_coupling  [R2]
        │   ├─ data_class bilinmiyor → fail-closed; zorla kabul ─────────────────────► unclassified_binding [R3]
        │   ├─ admit (platform: ¬forbidden; break_glass: content ∧ grant_gated; tenant: tenant-sınıf)
        │   ├─ platform_default ∧ forbidden ∧ admit ────────────────────────────────► wired_forbidden_repo [R4]
        │   ├─ platform_role ∧ forbidden ∧ grant_present ───────────────────────────► grant_on_content   [R5]
        │   └─ data_reachable = wired_forbidden_repo ∧ grant_present ────────────────► (R6 ÇEKİRDEK)

ÇEKİRDEK: (1) R4 WIRING BAĞIMSIZLIĞI (SAD §14.4.2) — L0 default plane tenant iş verisi repo'su wire etmez
(wired_forbidden_repo=0); (2) R5 GRANT BAĞIMSIZLIĞI (DB.md P3) — platform_ro tenant iş verisi tablosunda grant
tutmaz (grant_on_content=0); (3) R6 BİRLEŞİK DEFENSE IN DEPTH — tenant iş verisi L0'dan ANCAK her iki katman
regrese olursa erişilebilir (data_reachable=0); (4) R7 ENDPOINT YÜZEY BAĞIMSIZLIĞI (API.md) — L0 OpenAPI iş-
verisi endpoint'i yok (l0_business_endpoint=0); (5) R8 BREAK-GLASS AYRIMI — content repo yalnız ayrı break_
glass_plane'de (bg_in_default=0); (6) R9 BREAK-GLASS GRANT-GATED (time-boxed; 12.3.x) — content admission
geçerli grant gerektirir (bg_standing_binding=0). Motor DETERMİNİSTİK FAIL-CLOSED (Date.now/random YOK;
model_hash sha256). Her karar terminal (R1) + kanıt + model bütünlük manifesti (R10); metrik düşük-kardinalite +
ham PII yok (R11); model/spec/sample ham içerik/PII/credential tutmaz (R12).

Kapsam dışı (bilinçli, başka modül SAHİBİ): HTTP enforce_tenant_scope (çalışma-anı) → 12.2.1; RLS çalışma-anı
zorlama → 12.2.3 (TÜKETİLİR/backstop); rol→permission-key/scope → 12.1.1/12.1.3; ayrı router/scope → 12.2.2;
break-glass AKIŞI (maker-checker+bildirim+grant yaşam döngüsü) → 12.3.x; WORM audit → 12.1.8; repo/grant CI →
0.4.4. KAYNAK DOĞRULUK; çelişkide SAD §14.4.2 / DB.md P3 / FR-IAM-008 esastır.

Kullanım:
  repo_independence_probe.py validate          Statik model + spec + 12.2.1/12.2.3 resiprokal bağlantı → çıkış kodu
  repo_independence_probe.py check <sample>     Repo bağımsızlık karar motoru: senaryo(lar) → kapı (R1–R12)
  repo_independence_probe.py selftest           Gömülü davranış kontrolleri → çıkış kodu
  repo_independence_probe.py schema             Karar sözleşmesini yazdır

Determinizm: model_hash sha256 (kanonik JSON, sort_keys); Date.now/random YOK. Stdlib-only. Sır/credential ve
ham içerik (PII değeri) üretilmez/yazılmaz (fixture sentetik — yalnız repository adı + tablo adı + veri-sınıfı +
plane + db_role enum + yapısal request kimlik [slug]; FR-TST-008).
"""
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "repo-independence-spec.json")
MODEL_PATH = os.path.join(HERE, "config", "repo-independence-model.json")
GUARD_MODEL_PATH = os.path.join(HERE, "..", "backend-guard", "config", "guard-model.json")
RLS_MODEL_PATH = os.path.join(HERE, "..", "rls-double-check", "config", "rls-model.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

TERMINAL = {"PERMIT", "FORBID"}
DATA_CLASSES = ["tenant_content", "tenant_config", "tenant_metric", "platform", "global_reference"]
FORBIDDEN_CLASSES = {"tenant_content", "tenant_config"}
ALLOWED_PLATFORM_CLASSES = {"platform", "tenant_metric", "global_reference"}
PLANES = ["platform_control_plane", "tenant_application_plane", "break_glass_plane"]
DB_ROLES = ["platform_ro", "app_rw", "breakglass_ro"]
PLATFORM_ROLES = {"platform_ro", "platform_rw"}
RULES = ["plane_separation", "classification_coverage", "wiring_independence", "grant_independence",
         "defense_in_depth_reachability", "endpoint_surface_independence", "break_glass_plane_separation",
         "break_glass_grant_gated", "model_integrity"]
INVARIANT_IDS = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10", "R11", "R12"]

# Degrade (inject) — DOĞRU design-time repository bağımsızlığını bozan müdahaleler.
INJECTIONS = {"wire_content_in_platform", "wire_config_in_platform", "grant_content_to_platform",
              "expose_business_endpoint", "bg_in_default_plane", "bg_standing", "couple_planes",
              "unclassify", "model_tamper", "secret_leak"}

VIOLATION_KEYS = [
    "data_reachable", "wired_forbidden_repo", "grant_on_content", "l0_business_endpoint",
    "bg_in_default", "bg_standing_binding", "plane_coupling", "unclassified_binding",
    "model_tampered", "missing_evidence", "stuck_state", "secret_or_pii",
]

# ── Sızıntı tarayıcı (R12; 12.1.x/12.2.x deseniyle) — ham içerik/PII/sır yasak; repo/tablo/sınıf/plane/rol/kimlik beyazlanır ──
LEAK_PATTERNS = [
    ("phone_e164", re.compile(r"\+(?!1632)\d{9,15}\b")),
    ("digits_long", re.compile(r"\b\d{7,19}\b")),
    ("secret_kw", re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|bearer|credential|connection[_-]?string)\b\s*[:=]\s*\S")),
    ("privkey", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("pii_field", re.compile(r"(?i)\"(transcript_text_value|recording_audio_value|contact_pii_value|customer_phone_value|card_pan_value|cvv_value|otp_code_value|password_value|customer_name_value|db_password_value|connection_string_value|raw_value|pii_value)\"\s*:")),
]
LEAK_ALLOW = re.compile(r"(?i)(555-?01\d\d|\+1632|ITU|reserved|test|example|req-|t-|u-|corr-|bg-|prefix|masked|hash|sha256|\[[A-Z0-9_]+\]|\d{4}-\d{2}-\d{2}|_repo|tenant_|platform_|global_reference|break_glass)")


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def scan_leaks(text):
    """Ham içerik/PII/sır tarayıcı. Yorum/tarif satırı + repo/tablo/sınıf/plane/rol adı + slug kimlik eler (12.2.x deseni)."""
    hits = []
    for ln, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("#"):
            continue
        for name, pat in LEAK_PATTERNS:
            for m in pat.finditer(line):
                frag = m.group(0)
                window = line[max(0, m.start() - 16):m.end() + 16]
                if '"$comment"' in line or '"description"' in line or '"desc"' in line or '"trace"' in line \
                        or '"note"' in line or '"rule"' in line or '"rationale"' in line.lower() \
                        or line.strip().startswith('"$'):
                    continue
                if LEAK_ALLOW.search(window) or LEAK_ALLOW.search(frag):
                    continue
                hits.append((ln, name, frag))
    return hits


# ════════════════════════════════════════════════════════════════════════════
def _canon_hash(obj):
    """Model bütünlük manifesti: sha256(kanonik JSON) — deterministik (sort_keys)."""
    payload = json.dumps(obj, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _model():
    return _load(MODEL_PATH)


def _classify(sample, model):
    """Veri-sınıfını çöz: sample.data_class verilirse onu; yoksa table_class_of[table]; yoksa None (bilinmeyen → fail-closed)."""
    dc = sample.get("data_class")
    if dc is None:
        dc = model.get("table_class_of", {}).get(sample.get("table"))
    return dc


def build(sample, spec, inject=None, model=None):
    """Tek RepoBindingRequest senaryosunu yürüt → RepoBindingDecision + ihlal sayaçları.

    Motor DOĞRU design-time repository bağımsızlığını hesaplar; inject (degrade) doğru davranışı bozar ve
    eşleşen ihlal sayacını artırır (12.1.x/12.2.x inject deseniyle birebir)."""
    inject = set(inject if inject is not None else sample.get("inject", []))
    model = model if model is not None else _model()

    request_id = sample.get("request_id")
    plane = sample.get("plane")
    repository = sample.get("repository")
    table = sample.get("table")
    db_role = sample.get("db_role")
    grant_present = bool(sample.get("grant_present", False))
    grant_gated = bool(sample.get("grant_gated", False))
    endpoint_exposed = bool(sample.get("endpoint_exposed", False))
    via_break_glass = bool(sample.get("via_break_glass", False))
    # deploy_isolation: platform default için internal_only beklenir; sample override edebilir
    deploy_isolation = sample.get("deploy_isolation",
                                  "internal_only" if plane == "platform_control_plane" else "public")

    data_class = _classify(sample, model)

    v = {k: 0 for k in VIOLATION_KEYS}
    terminal = None
    note = None
    admit = False

    # ── R10 model bütünlük manifesti (frozen model) ──
    canonical_model = {
        "frozen": model.get("frozen"),
        "fail_closed": model.get("fail_closed"),
        "planes": model.get("planes"),
        "data_classes": model.get("data_classes"),
        "table_class_of": model.get("table_class_of"),
        "repositories": model.get("repositories"),
        "db_roles": model.get("db_roles"),
        "break_glass": model.get("break_glass"),
    }
    model_hash = _canon_hash(canonical_model)
    if "model_tamper" in inject:
        tampered = json.loads(json.dumps(canonical_model))
        tampered["data_classes"] = dict(tampered["data_classes"])
        tampered["data_classes"]["forbidden_for_platform"] = []          # forbidden sınıfı boşalt (tahrifat)
        tampered["break_glass"] = dict(tampered["break_glass"])
        tampered["break_glass"]["grant_gated"] = False                   # break-glass grant-gated kaldır (tahrifat)
        if _canon_hash(tampered) != model_hash:
            v["model_tampered"] += 1

    # ── malformed kapısı (fail-closed) ──
    known_class = data_class in DATA_CLASSES
    malformed = (not request_id or plane not in PLANES or db_role not in DB_ROLES
                 or (data_class is None and "unclassify" not in inject))

    if malformed:
        terminal, note, admit = "FORBID", "malformed", False
    else:
        is_platform_default = (plane == "platform_control_plane")
        is_breakglass_plane = (plane == "break_glass_plane")
        is_tenant_plane = (plane == "tenant_application_plane")
        is_forbidden = data_class in FORBIDDEN_CLASSES
        is_content = (data_class == "tenant_content")
        platform_role = db_role in PLATFORM_ROLES

        # ── R2 plane separation (deploy izolasyonu) ──
        if "couple_planes" in inject:
            deploy_isolation = "public"
        if is_platform_default and deploy_isolation != "internal_only":
            v["plane_coupling"] += 1

        # ── R3 classification coverage (fail-closed) ──
        if not known_class:
            # bilinmeyen sınıf → fail-closed FORBID; ancak unclassify degrade zorla kabul ettirir (fail-open)
            if "unclassify" in inject:
                admit = True                                             # fail-open (degrade)
                v["unclassified_binding"] += 1
                note = "unclassified"
            else:
                admit = False
                note = "unclassified_fail_closed"
        else:
            # ── correct admission (design-time kompozisyon kararı) ──
            if is_platform_default:
                admit = data_class in ALLOWED_PLATFORM_CLASSES           # forbidden-sınıf → FORBID (R4)
            elif is_breakglass_plane:
                admit = is_content and grant_gated                       # content YALNIZ geçerli grant (R9)
            elif is_tenant_plane:
                admit = data_class in (FORBIDDEN_CLASSES | {"tenant_metric", "global_reference"})
            else:
                admit = False

            # ── degrade: wiring bağımsızlığını boz (platform default forbidden repo admit) ──
            if ("wire_content_in_platform" in inject or "wire_config_in_platform" in inject) \
                    and is_platform_default and is_forbidden:
                admit = True                                             # kompozisyon kapısı bypass (R4)
            # ── degrade: break-glass content standing (grant'sız admit) ──
            if "bg_standing" in inject and is_breakglass_plane and is_content and not grant_gated:
                admit = True                                             # time-box/grant atlandı (R9)

        # ── degrade: stray grant (platform_ro tenant iş verisi grant'i) ──
        if "grant_content_to_platform" in inject and platform_role and is_forbidden:
            grant_present = True
        # ── degrade: L0 OpenAPI iş-verisi endpoint exposed ──
        if "expose_business_endpoint" in inject and is_platform_default and is_forbidden:
            endpoint_exposed = True
        # ── degrade: break-glass content repo default L0 plane'inde ──
        if "bg_in_default_plane" in inject:
            via_break_glass = True
            is_platform_default = True                                   # default plane'e konuldu

        terminal = "PERMIT" if admit else "FORBID"

        # ── R4 WIRING bağımsızlığı: platform default forbidden-sınıf admit ──
        if is_platform_default and is_forbidden and admit:
            v["wired_forbidden_repo"] += 1

        # ── R5 GRANT bağımsızlığı (DB.md P3): platform_ro forbidden tabloda grant ──
        if platform_role and is_forbidden and grant_present:
            v["grant_on_content"] += 1

        # ── R6 ÇEKİRDEK birleşik reachability: data_reachable ⟺ wiring ∧ grant ──
        if v["wired_forbidden_repo"] > 0 and grant_present:
            v["data_reachable"] += 1

        # ── R7 endpoint yüzey bağımsızlığı ──
        if is_platform_default and is_forbidden and endpoint_exposed:
            v["l0_business_endpoint"] += 1

        # ── R8 break-glass plane ayrımı: content repo default L0'da ──
        bg_repo = (repository == model.get("break_glass", {}).get("repo")) or via_break_glass
        if bg_repo and is_content and is_platform_default:
            v["bg_in_default"] += 1

        # ── R9 break-glass grant-gated: break_glass_plane content grant'sız admit ──
        if is_breakglass_plane and is_content and admit and not grant_gated:
            v["bg_standing_binding"] += 1

    # ── R1 stuck state ──
    if terminal not in TERMINAL:
        v["stuck_state"] += 1

    # ── Kanıt (R1) ──
    evidence = _evidence(request_id, plane, repository, table, data_class, db_role, grant_present,
                         grant_gated, endpoint_exposed, deploy_isolation, terminal, note, model_hash)
    if (not request_id) or (terminal is None):
        v["missing_evidence"] += 1

    return _pack(sample, terminal, admit, v, note, plane, repository, table, data_class, db_role,
                 grant_present, grant_gated, model_hash, evidence)


def _evidence(request_id, plane, repository, table, data_class, db_role, grant_present, grant_gated,
              endpoint_exposed, deploy_isolation, terminal, note, model_hash):
    return {
        "request_id": request_id,
        "plane": plane,
        "repository": repository,
        "table": table,
        "data_class": data_class,
        "db_role": db_role,
        "grant_present": grant_present,
        "grant_gated": grant_gated,
        "endpoint_exposed": endpoint_exposed,
        "deploy_isolation": deploy_isolation,
        "terminal": terminal,
        "note": note,
        "model_hash": model_hash,
    }


def _pack(sample, terminal, admit, v, note, plane, repository, table, data_class, db_role,
          grant_present, grant_gated, model_hash, evidence):
    return {
        "name": sample.get("name"),
        "terminal": terminal,
        "resolved": terminal in TERMINAL,
        "admit": admit,
        "note": note,
        "plane": plane,
        "repository": repository,
        "table": table,
        "data_class": data_class,
        "db_role": db_role,
        "grant_present": grant_present,
        "grant_gated": grant_gated,
        "model_hash": model_hash,
        "evidence": evidence,
        "violations": v,
    }


def _gate_eval(result, gates):
    """Tek senaryo sonucunu HARD kapılara vur → (passed, fail_list)."""
    v = result["violations"]
    fails = []
    mapping = {
        "data_reachable": "max_data_reachable",
        "wired_forbidden_repo": "max_wired_forbidden_repo",
        "grant_on_content": "max_grant_on_content",
        "l0_business_endpoint": "max_l0_business_endpoint",
        "bg_in_default": "max_bg_in_default",
        "bg_standing_binding": "max_bg_standing_binding",
        "plane_coupling": "max_plane_coupling",
        "unclassified_binding": "max_unclassified_binding",
        "model_tampered": "max_model_tampered",
        "missing_evidence": "max_missing_evidence",
        "stuck_state": "max_stuck_state",
        "secret_or_pii": "max_secret_or_pii",
    }
    for vk, gk in mapping.items():
        limit = gates.get(gk, 0)
        if v.get(vk, 0) > limit:
            fails.append("%s=%d > %s=%d" % (vk, v[vk], gk, limit))
    if gates.get("require_terminal", True) and result["terminal"] not in TERMINAL:
        fails.append("terminal'e ulaşılmadı: %s" % result["terminal"])
    return (len(fails) == 0, fails)


# ════════════════════════════════════════════════════════════════════════════
def check_cmd(arg):
    spec = _load(SPEC_PATH)
    gates = spec["gates"]

    if os.path.isdir(arg):
        paths = sorted(os.path.join(arg, f) for f in os.listdir(arg) if f.endswith(".json"))
    else:
        paths = [arg]

    all_ok = True
    for p in paths:
        sample = _load(p)
        expect = sample.get("expect", "pass")
        res = build(sample, spec)
        with open(p, "r", encoding="utf-8") as fh:
            leaks = scan_leaks(fh.read())
        if leaks:
            res["violations"]["secret_or_pii"] += len(leaks)
        passed, fails = _gate_eval(res, gates)

        exp_assert = sample.get("expected", {})
        mism = []
        for key in ("terminal", "admit", "note"):
            if key in exp_assert and exp_assert[key] != res.get(key):
                mism.append("%s: beklenen=%r gerçek=%r" % (key, exp_assert[key], res.get(key)))

        verdict_ok = (passed and not mism) if expect == "pass" else (not passed)
        all_ok = all_ok and verdict_ok
        icon = "🟢" if verdict_ok else "🔴"
        print("%s %s" % (icon, os.path.basename(p)))
        print("   terminal=%s admit=%s plane=%s class=%s role=%s grant=%s note=%s"
              % (res["terminal"], res["admit"], res["plane"], res["data_class"], res["db_role"],
                 res["grant_present"], res["note"]))
        nz = {k: val for k, val in res["violations"].items() if val}
        if nz:
            print("   ihlaller: %s" % nz)
        if expect == "pass" and fails:
            print("   ✗ kapı eler (beklenen geçer): %s" % "; ".join(fails))
        if expect == "fail" and passed:
            print("   ✗ kapı GEÇTİ (beklenen eler — degrade senaryo)")
        if mism and expect == "pass":
            print("   ✗ karar uyuşmazlığı: %s" % "; ".join(mism))
        if expect == "fail" and not passed:
            print("   ✓ beklendiği gibi elendi: %s" % "; ".join(fails[:3]))

    print("\ncheck: %s" % ("🟢 TÜM SENARYOLAR BEKLENDİĞİ GİBİ" if all_ok else "🔴 EN AZ BİR SENARYO BEKLENMEDİK"))
    return 0 if all_ok else 1


# ════════════════════════════════════════════════════════════════════════════
def validate():
    checks = []

    def chk(name, ok, detail=""):
        checks.append((name, ok, detail))

    spec = _load(SPEC_PATH)

    # 1) Üst-düzey alanlar
    for f in ("wbs", "phase", "priority", "trace", "placement", "rules", "decision",
              "outcomes", "model", "enforcement", "gates", "observability", "invariants", "no_secrets"):
        chk("spec.%s var" % f, f in spec)
    chk("wbs=12.2.4", spec.get("wbs") == "12.2.4")
    chk("phase=F1", spec.get("phase") == "F1")
    chk("priority=Must", spec.get("priority") == "Must")
    chk("placement fail_closed=true", spec.get("placement", {}).get("fail_closed") is True)
    chk("placement decision_at=design-time", "design-time" in spec.get("placement", {}).get("decision_at", ""))

    # 2) İzlenebilirlik
    tr = spec.get("trace", {})
    chk("FR-IAM-008 izlenir (L0 ⟂ tenant — ÇEKİRDEK)", "FR-IAM-008" in tr.get("fr", []))
    chk("FR-TEN-002 izlenir (tenant izolasyonu)", "FR-TEN-002" in tr.get("fr", []))
    chk("SAD §14.4.2 design-time repo bağımsızlığı izlenir", any("§14.4.2" in s for s in tr.get("sad", [])))
    chk("ADR-011 izlenir (iki düzlemli panel)", any(a.startswith("ADR-011") for a in tr.get("adr", [])))
    chk("12.2.1 backend-guard TÜKETİLİR (l0_business_data delegasyon — resiprokal)",
        any("12.2.1" in s for s in tr.get("consumes", [])))
    chk("12.2.3 RLS TÜKETİLİR (çalışma-anı backstop — resiprokal)",
        any("12.2.3" in s for s in tr.get("consumes", [])))

    # 3) Dokuz kural (çekirdek)
    rz = spec["rules"]
    rule_ids = [d["id"] for d in rz.get("list", [])]
    chk("dokuz kural tam", set(rule_ids) == set(RULES))
    chk("değerlendirme malformed→plane→class→wiring→grant→reachability→endpoint/bg",
        rz.get("evaluation") == "malformed_then_plane_separation_then_classification_coverage_then_wiring_independence_then_grant_independence_then_combined_reachability_then_endpoint_and_break_glass")
    for d in rz.get("list", []):
        chk("kural %s invariant taşır" % d["id"], d.get("invariant") in INVARIANT_IDS)

    # 4) Karar
    dec = spec["decision"]
    chk("karar default=FORBID (fail-closed)", dec.get("default") == "FORBID")
    chk("fail_safe no binding", "no binding" in dec.get("fail_safe_terminal", "").lower())

    # 5) Sonuçlar
    oc = spec["outcomes"]
    chk("terminal sonuçlar PERMIT/FORBID", set(oc.get("list", [])) == TERMINAL)

    # 6) Enforcement — iki katman + birleşim + backstop
    en = spec["enforcement"]
    chk("wiring_layer platform_control_plane + tenant_content/tenant_config wire etmez",
        "platform_control_plane" in en.get("wiring_layer", "") and "tenant_content" in en.get("wiring_layer", ""))
    chk("grant_layer platform_ro + GRANT TUTMAZ (DB.md P3)",
        "platform_ro" in en.get("grant_layer", "") and "GRANT" in en.get("grant_layer", ""))
    chk("combine data_reachable ⟺ wired_forbidden_repo ∧ grant_present",
        "wired_forbidden_repo" in en.get("combine", "") and "grant_present" in en.get("combine", ""))
    chk("rls_backstop 12.2.3 (çalışma-anı)", "12.2.3" in en.get("rls_backstop", ""))
    chk("endpoint_surface L0 OpenAPI iş-verisi endpoint yok (API.md)",
        "OpenAPI" in en.get("endpoint_surface", "") and "/calls" in en.get("endpoint_surface", ""))
    chk("decision_at design-time", en.get("decision_at") == "design-time")

    # 7) Model alanları
    md = spec["model"]
    chk("data_classes tam (5)", set(md.get("data_classes", [])) == set(DATA_CLASSES))
    chk("planes tam (3)", set(md.get("planes", [])) == set(PLANES))
    chk("forbidden_for_platform = tenant_content ∪ tenant_config",
        set(md.get("forbidden_for_platform", [])) == FORBIDDEN_CLASSES)
    chk("allowed_for_platform = platform/tenant_metric/global_reference",
        set(md.get("allowed_for_platform", [])) == ALLOWED_PLATFORM_CLASSES)
    chk("db_roles platform_ro/app_rw/breakglass_ro", set(md.get("db_roles", [])) == set(DB_ROLES))

    # 8) Kapılar — tüm sıfır-eşik ihlal kapıları
    g = spec["gates"]
    for gk in ("max_data_reachable", "max_wired_forbidden_repo", "max_grant_on_content",
               "max_l0_business_endpoint", "max_bg_in_default", "max_bg_standing_binding",
               "max_plane_coupling", "max_unclassified_binding", "max_model_tampered",
               "max_missing_evidence", "max_stuck_state", "max_secret_or_pii"):
        chk("kapı %s=0" % gk, g.get(gk) == 0)
    chk("require_terminal", g.get("require_terminal") is True)

    # 9) Gözlemlenebilirlik — kardinalite disiplini (0.4.7)
    obs = spec["observability"]
    chk("repo_binding_decision_total metrik", "repo_binding_decision_total" in obs.get("metrics", []))
    chk("repo_independence_violation_total metrik (alarm)", "repo_independence_violation_total" in obs.get("metrics", []))
    hi = set(obs.get("high_cardinality_trace_only", []))
    lo = set(obs.get("low_cardinality_labels", []))
    chk("repository/table YÜKSEK kard (label değil)",
        "repository" in hi and "table" in hi and "repository" not in lo and "table" not in lo)
    chk("plane/data_class/db_role/result DÜŞÜK kard",
        all(x in lo for x in ("plane", "data_class", "db_role", "result")))
    chk("alarm data_reachable/wired_forbidden_repo/grant_on_content ≤2dk",
        any(x in obs.get("alarm", "") for x in ("data_reachable", "wired_forbidden_repo", "grant_on_content")))

    # 10) İnvariant'lar R1–R12
    inv_ids = [i["id"] for i in spec["invariants"]]
    chk("invariant'lar R1–R12 tam", inv_ids == INVARIANT_IDS)

    # 11) Model dosyası + içsel tutarlılık (SAD §14.4.2 / DB.md P3)
    mm_ok = os.path.exists(MODEL_PATH)
    chk("config/repo-independence-model.json var", mm_ok)
    if mm_ok:
        mm = _model()
        chk("model frozen=true", mm.get("frozen") is True)
        chk("model fail_closed=true", mm.get("fail_closed") is True)
        chk("model forbidden_for_platform = tenant_content ∪ tenant_config",
            set(mm.get("data_classes", {}).get("forbidden_for_platform", [])) == FORBIDDEN_CLASSES)
        chk("model allowed_for_platform = platform/tenant_metric/global_reference",
            set(mm.get("data_classes", {}).get("allowed_for_platform", [])) == ALLOWED_PLATFORM_CLASSES)
        chk("model 3 plane (platform/tenant/break_glass)",
            set(k for k in mm.get("planes", {}).keys() if not k.startswith("$")) == set(PLANES))
        chk("model platform_control_plane internal_only (ADR-011)",
            mm.get("planes", {}).get("platform_control_plane", {}).get("deploy_isolation") == "internal_only")
        chk("model break_glass_plane grant_gated + time_boxed",
            mm.get("planes", {}).get("break_glass_plane", {}).get("grant_gated") is True
            and mm.get("planes", {}).get("break_glass_plane", {}).get("time_boxed") is True)
        tco = mm.get("table_class_of", {})
        chk("model table_class_of ≥37 varlık (BRD §16)", len(tco) >= 37)
        chk("model tenant_content içerir transcript/recording/contact/call",
            all(tco.get(t) == "tenant_content" for t in ("transcript", "recording", "contact", "call")))
        chk("model usage_record = tenant_metric (L0 metrik/kaynak)", tco.get("usage_record") == "tenant_metric")
        chk("model tenant/audit_log/break_glass_grant = platform",
            all(tco.get(t) == "platform" for t in ("tenant", "audit_log", "break_glass_grant")))
        chk("model role/permission_key = global_reference",
            tco.get("role") == "global_reference" and tco.get("permission_key") == "global_reference")
        # platform repo'ları forbidden-sınıf wire etmez (içsel tutarlılık)
        repos = mm.get("repositories", {})
        pf_repos = [r for r, d in repos.items() if isinstance(d, dict)
                    and d.get("plane") == "platform_control_plane"]
        chk("model platform_control_plane repo'ları forbidden-sınıf wire etmez",
            all(repos[r].get("data_class") in ALLOWED_PLATFORM_CLASSES for r in pf_repos))
        chk("model break_glass_content_repo break_glass_plane'de + grant_gated",
            repos.get("break_glass_content_repo", {}).get("plane") == "break_glass_plane"
            and repos.get("break_glass_content_repo", {}).get("grant_gated") is True)
        chk("model platform_ro grants_on_forbidden=false (DB.md P3)",
            mm.get("db_roles", {}).get("platform_ro", {}).get("grants_on_forbidden") is False)
        # break-glass content tabloları 12.2.3 ile resiprokal
        chk("model break_glass.content_tables = transcript/transcript_segment/recording/contact",
            set(mm.get("break_glass", {}).get("content_tables", []))
            == {"transcript", "transcript_segment", "recording", "contact"})

    # 12) 12.2.1 RESİPROKAL bağlantı — guard-model l0_business_data.delegated_to → 12.2.4
    gm_ok = os.path.exists(GUARD_MODEL_PATH)
    chk("12.2.1 ../backend-guard/config/guard-model.json var (TÜKETİLİR)", gm_ok)
    if gm_ok:
        gm = _load(GUARD_MODEL_PATH)
        l0bd = gm.get("l0_business_data", {})
        chk("12.2.1 l0_business_data.default_access=denied", l0bd.get("default_access") == "denied")
        chk("12.2.1 l0_business_data.delegated_to → 12.2.4 (resiprokal)",
            any("12.2.4" in s for s in l0bd.get("delegated_to", [])))

    # 13) 12.2.3 RESİPROKAL bağlantı — RLS backstop + break_glass.tables eşleşmesi
    rm_ok = os.path.exists(RLS_MODEL_PATH)
    chk("12.2.3 ../rls-double-check/config/rls-model.json var (RLS backstop — TÜKETİLİR)", rm_ok)
    if rm_ok and mm_ok:
        rm = _load(RLS_MODEL_PATH)
        chk("12.2.3 break_glass.tables = bu modül break_glass.content_tables (resiprokal)",
            set(rm.get("break_glass", {}).get("tables", []))
            == set(_model().get("break_glass", {}).get("content_tables", [])))

    # 14) Sır/PII tarayıcı — spec + model + samples
    scan_files = [SPEC_PATH, MODEL_PATH] + (
        [os.path.join(SAMPLES_DIR, f) for f in os.listdir(SAMPLES_DIR) if f.endswith(".json")]
        if os.path.isdir(SAMPLES_DIR) else [])
    total_leaks = 0
    for p in scan_files:
        if not os.path.exists(p):
            continue
        with open(p, "r", encoding="utf-8") as fh:
            hits = scan_leaks(fh.read())
        if hits:
            total_leaks += len(hits)
            chk("sızıntı yok: %s" % os.path.basename(p), False, str(hits[:2]))
    chk("hiç ham-içerik/PII/sır sızıntısı yok (R12)", total_leaks == 0)

    # 15) Samples — ≥1 pass + ≥1 fail
    if os.path.isdir(SAMPLES_DIR):
        sample_files = sorted(f for f in os.listdir(SAMPLES_DIR) if f.endswith(".json"))
        chk("≥1 pass + ≥1 fail örnek (degrade ispatı)", _has_both(sample_files))

    npass = sum(1 for _, ok, _ in checks if ok)
    for name, ok, detail in checks:
        line = ("  ✓ " if ok else "  ✗ ") + name
        if not ok and detail:
            line += "  → " + detail
        print(line)
    total = len(checks)
    print("\nvalidate: %d/%d %s" % (npass, total, "🟢" if npass == total else "🔴"))
    return 0 if npass == total else 1


def _has_both(sample_files):
    have_pass = have_fail = False
    for f in sample_files:
        s = _load(os.path.join(SAMPLES_DIR, f))
        if s.get("expect", "pass") == "pass":
            have_pass = True
        else:
            have_fail = True
    return have_pass and have_fail


# ════════════════════════════════════════════════════════════════════════════
def selftest():
    results = []

    def case(name, cond):
        results.append((bool(cond), name))

    spec = _load(SPEC_PATH)
    G = spec["gates"]

    def req(**kw):
        # Varsayılan: platform plane, resource_quota_repo (tenant_metric usage_record), platform_ro, grant yok → PERMIT.
        d = {
            "request_id": "req-1", "plane": "platform_control_plane", "repository": "resource_quota_repo",
            "table": "usage_record", "db_role": "platform_ro", "grant_present": False,
        }
        d.update(kw)
        return d

    # 1) happy — platform metrik repo → PERMIT, ihlal yok
    r = build(req(), spec)
    case("happy: PERMIT (platform metrik repo)", r["terminal"] == "PERMIT")
    case("happy: model_hash var (R10)", r["model_hash"] is not None)
    case("happy: ihlal yok", all(x == 0 for x in r["violations"].values()))
    case("happy: kapı geçer", _gate_eval(r, G)[0] is True)

    # 2) determinizm
    r1, r2 = build(req(), spec), build(req(), spec)
    case("determinizm: birebir", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))
    case("model_hash deterministik", r1["model_hash"] == r2["model_hash"])

    # 3) platform allowed sınıfları → PERMIT
    case("platform tenant repo (provisioning) PERMIT",
         build(req(repository="tenant_provisioning_repo", table="tenant"), spec)["terminal"] == "PERMIT")
    case("platform reference repo (role) PERMIT",
         build(req(repository="reference_repo", table="role"), spec)["terminal"] == "PERMIT")
    case("platform audit repo (audit_log) PERMIT",
         build(req(repository="platform_audit_repo", table="audit_log"), spec)["terminal"] == "PERMIT")

    # 4) R4 ÇEKİRDEK — platform default tenant_content repo → FORBID (tasarım izolasyonu); ihlal yok
    r = build(req(repository="transcript_repo", table="transcript"), spec)
    case("design-iso: platform transcript_repo → FORBID (wire etmez)", r["terminal"] == "FORBID")
    case("design-iso: wired_forbidden_repo=0 (doğru reddetti) + kapı geçer",
         r["violations"]["wired_forbidden_repo"] == 0 and _gate_eval(r, G)[0] is True)
    # tenant_config de forbidden
    case("design-iso: platform agent_repo (config) → FORBID",
         build(req(repository="agent_repo", table="agent"), spec)["terminal"] == "FORBID")

    # 5) R6 DEFENSE IN DEPTH — wiring regrese (wire content) ama grant yok → data_reachable=0
    r = build(req(repository="transcript_repo", table="transcript", grant_present=False),
              spec, inject=["wire_content_in_platform"])
    case("defense-in-depth: wire bug ama grant yok → wired_forbidden_repo>0 fakat data_reachable=0",
         r["violations"]["wired_forbidden_repo"] > 0 and r["violations"]["data_reachable"] == 0)
    # iki katman da regrese (wire + grant) → data_reachable>0
    r = build(req(repository="transcript_repo", table="transcript", grant_present=True),
              spec, inject=["wire_content_in_platform"])
    case("defense-in-depth: wire+grant ikisi de regrese → data_reachable>0 + kapı eler",
         r["violations"]["data_reachable"] > 0 and _gate_eval(r, G)[0] is False)

    # 6) tenant plane → tenant_content/config repo PERMIT (meşru)
    case("tenant plane call_repo (content) PERMIT",
         build(req(plane="tenant_application_plane", repository="call_repo", table="call", db_role="app_rw"),
               spec)["terminal"] == "PERMIT")
    case("tenant plane agent_repo (config) PERMIT",
         build(req(plane="tenant_application_plane", repository="agent_repo", table="agent", db_role="app_rw"),
               spec)["terminal"] == "PERMIT")

    # 7) R9 break-glass plane content + grant_gated → PERMIT (Tier B meşru)
    r = build(req(plane="break_glass_plane", repository="break_glass_content_repo", table="transcript",
                  db_role="breakglass_ro", grant_gated=True), spec)
    case("break-glass-valid: content + grant_gated → PERMIT", r["terminal"] == "PERMIT")
    case("break-glass-valid: bg_standing_binding=0 + ihlal yok",
         r["violations"]["bg_standing_binding"] == 0 and _gate_eval(r, G)[0] is True)
    # grant_gated yok → FORBID (correct)
    case("break-glass-nogrant: grant_gated yok → FORBID",
         build(req(plane="break_glass_plane", repository="break_glass_content_repo", table="transcript",
                   db_role="breakglass_ro", grant_gated=False), spec)["terminal"] == "FORBID")

    # ── DEGRADE (inject) — hepsi kapıyı ELEMELİ ──

    # 8) wire_content_in_platform (+ grant) → wired_forbidden_repo + data_reachable
    r = build(req(repository="recording_repo", table="recording", grant_present=True),
              spec, inject=["wire_content_in_platform"])
    case("wire-content: wired_forbidden_repo>0 + data_reachable>0 + kapı eler",
         r["violations"]["wired_forbidden_repo"] > 0 and r["violations"]["data_reachable"] > 0
         and _gate_eval(r, G)[0] is False)

    # 9) wire_config_in_platform → wired_forbidden_repo
    r = build(req(repository="campaign_repo", table="campaign"), spec, inject=["wire_config_in_platform"])
    case("wire-config: wired_forbidden_repo>0 + kapı eler",
         r["violations"]["wired_forbidden_repo"] > 0 and _gate_eval(r, G)[0] is False)

    # 10) grant_content_to_platform → grant_on_content (DB.md P3)
    r = build(req(repository="contact_repo", table="contact"), spec, inject=["grant_content_to_platform"])
    case("grant-content: grant_on_content>0 + kapı eler",
         r["violations"]["grant_on_content"] > 0 and _gate_eval(r, G)[0] is False)

    # 11) expose_business_endpoint → l0_business_endpoint
    r = build(req(repository="transcript_repo", table="transcript"), spec, inject=["expose_business_endpoint"])
    case("expose-endpoint: l0_business_endpoint>0 + kapı eler",
         r["violations"]["l0_business_endpoint"] > 0 and _gate_eval(r, G)[0] is False)

    # 12) bg_in_default_plane → bg_in_default
    r = build(req(repository="break_glass_content_repo", table="transcript"), spec, inject=["bg_in_default_plane"])
    case("bg-in-default: bg_in_default>0 + kapı eler",
         r["violations"]["bg_in_default"] > 0 and _gate_eval(r, G)[0] is False)

    # 13) bg_standing → bg_standing_binding
    r = build(req(plane="break_glass_plane", repository="break_glass_content_repo", table="transcript",
                  db_role="breakglass_ro", grant_gated=False), spec, inject=["bg_standing"])
    case("bg-standing: bg_standing_binding>0 + kapı eler",
         r["violations"]["bg_standing_binding"] > 0 and _gate_eval(r, G)[0] is False)

    # 14) couple_planes → plane_coupling
    r = build(req(), spec, inject=["couple_planes"])
    case("couple-planes: plane_coupling>0 + kapı eler",
         r["violations"]["plane_coupling"] > 0 and _gate_eval(r, G)[0] is False)

    # 15) unclassify → unclassified_binding (fail-open)
    r = build(req(repository="mystery_repo", table="mystery_table", data_class=None), spec, inject=["unclassify"])
    case("unclassify: unclassified_binding>0 + kapı eler",
         r["violations"]["unclassified_binding"] > 0 and _gate_eval(r, G)[0] is False)
    # bilinmeyen sınıf inject'siz → FORBID (fail-closed)
    case("unclassified fail-closed: bilinmeyen sınıf → FORBID",
         build(req(repository="mystery_repo", table="mystery_table", data_class="bogus"), spec)["terminal"] == "FORBID")

    # 16) model_tamper → model_tampered
    r = build(req(), spec, inject=["model_tamper"])
    case("model-tamper: model_tampered>0 + kapı eler",
         r["violations"]["model_tampered"] > 0 and _gate_eval(r, G)[0] is False)

    # 17) malformed → FORBID
    case("malformed-noreq: FORBID", build(req(request_id=None), spec)["note"] == "malformed")
    case("malformed-noplane: FORBID", build(req(plane="bogus"), spec)["note"] == "malformed")
    case("malformed-norole: FORBID", build(req(db_role="bogus"), spec)["note"] == "malformed")

    # 18) evidence + leak
    r = build(req(), spec)
    case("evidence: request+plane+repo+class+role+model_hash taşır",
         all(k in r["evidence"] for k in ("request_id", "plane", "repository", "data_class", "db_role", "model_hash")))
    case("evidence: ham PII alanı yok",
         all(k not in json.dumps(r) for k in ("transcript_text_value", "recording_audio_value", "contact_pii_value")))
    case("leak: repo+tablo+sınıf+plane temiz",
         scan_leaks('{"repository":"transcript_repo","table":"transcript","data_class":"tenant_content","plane":"platform_control_plane"}') == [])
    case("leak: transcript_text_value alanı yakalanır", len(scan_leaks('{"transcript_text_value": "x"}')) > 0)

    npass = sum(1 for ok, _ in results if ok)
    for ok, name in results:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print("\nselftest: %d/%d %s" % (npass, len(results), "🟢" if npass == len(results) else "🔴"))
    return 0 if npass == len(results) else 1


# ════════════════════════════════════════════════════════════════════════════
def schema_cmd():
    out = {
        "module": "l0-repo-independence (WBS 12.2.4 — L0 iş verisi repository bağımsızlığı; design-time izolasyon; SAD §14.4.2, DB.md P3, FR-IAM-008)",
        "outcomes": sorted(TERMINAL),
        "terminal": sorted(TERMINAL),
        "rules": RULES,
        "data_classes": DATA_CLASSES,
        "forbidden_for_platform": sorted(FORBIDDEN_CLASSES),
        "allowed_for_platform": sorted(ALLOWED_PLATFORM_CLASSES),
        "planes": PLANES,
        "db_roles": DB_ROLES,
        "decision": "malformed ⇒ FORBID(malformed) → platform default deploy_isolation kaybı ⇒ plane_coupling → "
                    "data_class bilinmiyor ⇒ fail-closed FORBID; zorla kabul ⇒ unclassified_binding → "
                    "admit (platform: ¬forbidden; break_glass: content ∧ grant_gated; tenant: tenant-sınıf) → "
                    "terminal = PERMIT if admit else FORBID → platform_default ∧ forbidden ∧ admit ⇒ wired_forbidden_repo → "
                    "platform_role ∧ forbidden ∧ grant_present ⇒ grant_on_content → "
                    "data_reachable = wired_forbidden_repo ∧ grant_present (ÇEKİRDEK AND)",
        "default": "FORBID (fail-closed)",
        "fail_safe": "terminal=FORBID ⇒ binding deploy edilmez; malformed/bilinmeyen-sınıf/forbidden-platform ⇒ FORBID; data_reachable ⟺ wired_forbidden_repo ∧ grant_present",
        "core_guarantees": [
            "R4 wiring bağımsızlığı: platform_control_plane (L0) tenant_content/tenant_config repo'su WIRE ETMEZ; forbidden-sınıf platform admit → wired_forbidden_repo=0 (SAD §14.4.2)",
            "R5 grant bağımsızlığı: platform_ro tenant iş verisi tablolarında GRANT TUTMAZ; stray grant → grant_on_content=0 (DB.md P3)",
            "R6 birleşik defense-in-depth: data_reachable ⟺ wired_forbidden_repo ∧ grant_present; tek katman regresyonu veriyi açmaz; üçüncü backstop 12.2.3 RLS; data_reachable=0 (FR-IAM-008, P2)",
            "R7 endpoint yüzey bağımsızlığı: L0 OpenAPI iş-verisi endpoint'i (GET /calls, /transcripts) yok; l0_business_endpoint=0 (API.md)",
            "R8 break-glass plane ayrımı: content repo yalnız ayrı break_glass_plane'de, default L0'da değil; bg_in_default=0 (DB.md §6.4)",
            "R9 break-glass grant-gated: content admission geçerli grant gerektirir (time-boxed; standing yok); bg_standing_binding=0 (FR-IAM-009)",
        ],
        "request_fields": ["name", "request_id", "plane(platform_control_plane|tenant_application_plane|break_glass_plane)",
                           "repository", "table", "data_class(tenant_content|tenant_config|tenant_metric|platform|global_reference)",
                           "db_role(platform_ro|app_rw|breakglass_ro)", "grant_present(bool)", "grant_gated(bool)",
                           "endpoint_exposed(bool)", "deploy_isolation(internal_only|public)", "via_break_glass(bool)",
                           "inject[]", "expect", "expected{}"],
        "injections (degrade testi)": sorted(INJECTIONS),
        "decision_fields": ["terminal(PERMIT|FORBID)", "admit", "note", "plane", "repository", "table",
                            "data_class", "db_role", "grant_present", "grant_gated", "model_hash", "evidence"],
        "violations": VIOLATION_KEYS,
        "invariants": INVARIANT_IDS,
        "model": "config/repo-independence-model.json (frozen — planes[3] + data_classes[forbidden=tenant_content∪tenant_config] "
                 "+ table_class_of[37] + repositories[kayıt defteri] + db_roles[platform_ro grant'siz] + break_glass[ayrı plane])",
        "consumes": "12.2.1 backend-guard guard-model.json (l0_business_data.delegated_to=12.2.4 — RESİPROKAL); "
                    "12.2.3 rls-double-check rls-model.json (RLS çalışma-anı backstop; break_glass.tables RESİPROKAL); "
                    "SAD §14.4.2 + DB.md P3 (kaynak doğruluk)",
        "consumed_by": "12.3.x break-glass (plane ayrımı + grant-gated); 1.x F1 kod (FastAPI kompozisyon + GRANT/REVOKE "
                       "DDL + L0 OpenAPI); 0.4.4 repo/grant bağımsızlık CI; 0.4.7 gözlemlenebilirlik",
        "trace": "FR-IAM-008, SAD §14.4.2, DB.md P3, ADR-011, API.md, 12.2.1, 12.2.3",
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd = argv[1]
    if cmd == "validate":
        return validate()
    if cmd == "check":
        if len(argv) < 3:
            print("kullanım: repo_independence_probe.py check <sample.json|dizin>")
            return 2
        return check_cmd(argv[2])
    if cmd == "selftest":
        return selftest()
    if cmd == "schema":
        return schema_cmd()
    print("bilinmeyen komut: %s" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
