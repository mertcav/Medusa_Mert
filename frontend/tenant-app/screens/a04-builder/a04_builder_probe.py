#!/usr/bin/env python3
# WBS 13.4.4 — A-04 "Agent Builder (kod yazmadan)" doğrulama probe'u (stdlib-only, credential-free, deterministik).
#
# Komutlar:
#   validate  — ON-DISK invariant taraması (sayfa + veri seam + i18n + spec; S1..S8)
#   check     — SAF çekirdek senaryo aynası (stepStatus/completedSteps/incompleteRequiredSteps/
#               requiredStepsComplete/completionPercent/fieldsTotal/fieldsComplete/hasConversationModel/
#               readyForDraft/readyForTest/readyForPublish/blockers/nextStep/tone'lar/assertNoPii)
#               + samples/* taslak doğrulaması
#   selftest  — pozitif + negatif kendi-testleri (eksik/bloklu senaryolar beklendiği gibi yakalanır)
#   schema    — taslak şema özeti
#
# Bu probe TS saf yardımcılarının (lib/tenant/builder.ts) Python AYNASIDIR; mantık birebir kopya.
# 0.2.x/0.3.x probe disiplini (sağlayıcı-nötr ADR-002, stdlib-only, sanal-saat) bir UI ekranına taşınır.
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.path.join(HERE, "..", ".."))          # frontend/tenant-app
SPEC_PATH = os.path.join(HERE, "a04-builder-spec.json")
PAGE_PATH = os.path.join(APP, "app", "(workspace)", "workspace", "builder", "page.tsx")
DATA_PATH = os.path.join(APP, "lib", "tenant", "builder.ts")
TR_PATH = os.path.join(APP, "lib", "i18n", "tr.json")
EN_PATH = os.path.join(APP, "lib", "i18n", "en.json")

GREEN, RED = "🟢", "🔴"

STEP_ORDER = ["basics", "conversation_model", "knowledge", "tools", "voice_model", "policies"]
REQUIRED_STEPS = ["basics", "conversation_model", "voice_model", "policies"]

FORBIDDEN_PII_KEYS = ["transcript", "recording", "recordingurl", "audio", "msisdn",
                      "phonenumber", "callerid", "callernumber", "calleenumber", "customer",
                      "customername", "cdr", "cardpan", "cvv", "ssn", "pii"]
FORBIDDEN_SECRET_KEYS = ["secret", "apikey", "apisecret", "clientsecret", "webhooksecret", "token",
                         "bearertoken", "accesstoken", "refreshtoken", "credential",
                         "password", "privatekey", "kmskey", "prompttext", "promptbody"]


def load_json(p):
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_text(p):
    with open(p, "r", encoding="utf-8") as fh:
        return fh.read()


# ── SAF çekirdek aynası (lib/tenant/builder.ts ile birebir) ──────────────────────

def step_status(s):
    if s["fieldsTotal"] > 0 and s["fieldsComplete"] >= s["fieldsTotal"]:
        return "complete"
    if s["fieldsComplete"] <= 0:
        return "incomplete"
    return "in_progress"


def step_by_id(steps, sid):
    for s in steps:
        if s["id"] == sid:
            return s
    return None


def completed_steps(steps):
    return [s for s in steps if step_status(s) == "complete"]


def required_steps(steps):
    return [s for s in steps if s["required"]]


def incomplete_required_steps(steps):
    return [s for s in steps if s["required"] and step_status(s) != "complete"]


def required_steps_complete(steps):
    return len(incomplete_required_steps(steps)) == 0


def completion_percent(steps):
    if not steps:
        return 0
    return round(len(completed_steps(steps)) / len(steps) * 100)


def fields_total(steps):
    return sum(s["fieldsTotal"] for s in steps)


def fields_complete(steps):
    return sum(s["fieldsComplete"] for s in steps)


def has_conversation_model(draft):
    return draft["conversationModel"] is not None


def ready_for_draft(draft):
    b = step_by_id(draft["steps"], "basics")
    return b is not None and step_status(b) == "complete"


def ready_for_test(draft):
    return required_steps_complete(draft["steps"]) and has_conversation_model(draft)


def ready_for_publish(draft):
    return ready_for_test(draft) and draft["testStatus"] == "passed"


def blockers(draft):
    ids = [s["id"] for s in incomplete_required_steps(draft["steps"])]
    if not has_conversation_model(draft) and "conversation_model" not in ids:
        ids.append("conversation_model")
    return ids


def next_step(draft):
    for sid in STEP_ORDER:
        s = step_by_id(draft["steps"], sid)
        if s and step_status(s) != "complete":
            return sid
    return None


def step_tone(s):
    return {"complete": "success", "in_progress": "warning", "incomplete": "neutral"}[s]


def model_tone(m):
    if m == "node_flow":
        return "info"
    if m == "single_prompt":
        return "neutral"
    return "warning"


def test_tone(s):
    return {"passed": "success", "failed": "danger", "not_run": "warning"}[s]


def start_mode_tone(m):
    return {"blank": "neutral", "template": "info", "clone": "info"}[m]


def ready_tone(b):
    return "success" if b else "warning"


def assert_no_pii(node, path="$"):
    """Yasak PII/iş-içeriği VEYA sır/credential/prompt-gövdesi alan adı bulursa (path) döndürür; yoksa None."""
    if isinstance(node, list):
        for i, v in enumerate(node):
            hit = assert_no_pii(v, f"{path}[{i}]")
            if hit:
                return hit
    elif isinstance(node, dict):
        for k, v in node.items():
            if k.startswith("$"):
                continue
            low = k.lower()
            if low in FORBIDDEN_PII_KEYS or low in FORBIDDEN_SECRET_KEYS:
                return f"{path}.{k}"
            hit = assert_no_pii(v, f"{path}.{k}")
            if hit:
                return hit
    return None


# ── i18n yardımcıları ─────────────────────────────────────────────────────────────

def resolve(cat, dotted):
    cur = cat
    for seg in dotted.split("."):
        if isinstance(cur, dict) and seg in cur:
            cur = cur[seg]
        else:
            return None
    return cur if isinstance(cur, str) else None


def placeholders(s):
    return set(re.findall(r"\{(\w+)\}", s or ""))


def _extract_data_fields(ts):
    """builder.ts interface alan adlarını kaba çıkar (PII/sır-alan-adı taraması için)."""
    return {m: 1 for m in re.findall(r"^\s*(\w+)\s*[?:]", ts, re.M)}


# ── validate ───────────────────────────────────────────────────────────────────────

def cmd_validate():
    checks = []

    def chk(cond, label):
        checks.append((bool(cond), label))

    spec = load_json(SPEC_PATH)
    page = read_text(PAGE_PATH) if os.path.isfile(PAGE_PATH) else ""
    data = read_text(DATA_PATH) if os.path.isfile(DATA_PATH) else ""
    tr = load_json(TR_PATH)
    en = load_json(EN_PATH)

    # S0/S1 — ekran sayfası mevcut + işaretli + iskelet değil
    chk(spec.get("wbs") == "13.4.4", "S0 spec.wbs=13.4.4")
    chk(os.path.isfile(PAGE_PATH), "S1 workspace/builder/page.tsx mevcut")
    chk('data-screen="A-04"' in page, 'S1 data-screen="A-04" işaretli')
    chk("İskelet ekran — A-04" not in page, "S1 iskelet placeholder kaldırıldı")

    # S2 — tasarım sistemi + i18n + veri seam kullanımı
    chk("@/lib/ui/components" in page, "S2 tasarım sistemi (lib/ui) kullanır")
    chk("@/lib/i18n" in page, "S2 i18n (lib/i18n) kullanır")
    chk("@/lib/tenant/builder" in page, "S2 veri seam (lib/tenant/builder) kullanır")
    chk("getServerLocale" in page, "S2 sunucu-tarafı locale müzakeresi")
    for comp in ("PageHeader", "Card", "StatusPill", "Table", "Button"):
        chk(comp in page, f"S2 {comp} komponenti kullanılır")

    # S3 — kullanıcı-görünür metin i18n'den (screen.a04.*); hardcoded TR/EN cümle yok
    chk("screen.a04." in page, "S3 screen.a04.* anahtarları referans alınır")
    jsx_text = re.findall(r">\s*([A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü ]{3,})\s*<", page)
    chk(len(jsx_text) == 0, f"S3 JSX'te hardcoded metin yok (bulunan={jsx_text[:3]})")

    # S4 — veri katmanı son-müşteri-PII-free + sır/prompt-gövdesi-free + HİJYEN/GÜVENLİK guard
    chk(os.path.isfile(DATA_PATH), "S4 lib/tenant/builder.ts mevcut")
    chk("FORBIDDEN_PII_KEYS" in data, "S4 FORBIDDEN_PII_KEYS tanımlı")
    chk("FORBIDDEN_SECRET_KEYS" in data, "S4 FORBIDDEN_SECRET_KEYS tanımlı (NFR 10.6)")
    chk("assertNoPii" in data, "S4 assertNoPii guard tanımlı")
    chk(re.search(r"assertNoPii\(view\)", data) is not None, "S4 getBuilderView assertNoPii çağırır")
    chk("prompttext" in [s.lower() for s in FORBIDDEN_SECRET_KEYS] and "apikey" in [s.lower() for s in FORBIDDEN_SECRET_KEYS], "S4 prompt gövdesi/tool sırrı (promptText/apiKey) yasak (NFR 10.6)")
    chk("transcript" in [s.lower() for s in FORBIDDEN_PII_KEYS] and "cdr" in [s.lower() for s in FORBIDDEN_PII_KEYS], "S4 ham müşteri içeriği (transkript/CDR) yasak (BRD §17.7)")
    leak = assert_no_pii({"data_field_scan": _extract_data_fields(data)})
    chk(leak is None, f"S4 veri seam türlerinde PII/sır alanı yok (sızıntı={leak})")

    # S5 — BRD §17.5 içerik öğeleri + FR-AGT-001/002/003/005/008/009/010 karşılanır
    a04 = tr.get("screen", {}).get("a04", {})
    sec = a04.get("section", {})
    for s in ("start", "summary", "steps", "readiness", "templates"):
        chk(s in sec, f"S5 section.{s} mevcut (BRD §17.5 içerik öğesi)")
    chk("startMode" in data and set(["blank", "template", "clone"]).issubset(a04.get("start", {}).keys()), "S5 no-code başlangıç noktası (FR-AGT-001)")
    chk("businessRulesCount" in data and "personality" in data and "rules" in a04.get("kpi", {}), "S5 isim/amaç/kişilik/dil/iş kuralları (FR-AGT-002)")
    chk("conversationModel" in data and set(["single_prompt", "node_flow", "none"]).issubset(a04.get("model", {}).keys()), "S5 konuşma modeli (FR-AGT-003)")
    chk("readyForDraft" in data and "lifecycle" in data.lower() and "draft" in a04.get("readiness", {}), "S5 yaşam döngüsü / taslak (FR-AGT-005)")
    chk("isVariant" in data and "variant_note" in a04.get("start", {}), "S5 segment varyantı / klon (FR-AGT-008)")
    chk(set(["basics", "conversation_model", "voice_model"]).issubset(a04.get("step", {}).keys()) and "policies" in a04.get("step", {}), "S5 güvenlik politikası adımı (FR-AGT-009)")
    chk("readyForTest" in data and "readyForPublish" in data and set(["passed", "failed", "not_run"]).issubset(a04.get("test", {}).keys()), "S5 otomatik test kapısı / hazırlık (FR-AGT-010)")

    # S6 — referans anahtarlar var + TR↔EN parity + placeholder + boş değer yok
    ref = spec["referenced_keys"]
    missing_tr, missing_en, empty, ph_mismatch = [], [], [], []
    for rk in ref:
        full = f"screen.a04.{rk}"
        vt, ve = resolve(tr, full), resolve(en, full)
        if vt is None:
            missing_tr.append(rk)
        elif not vt.strip():
            empty.append(("tr", rk))
        if ve is None:
            missing_en.append(rk)
        elif not ve.strip():
            empty.append(("en", rk))
        if vt is not None and ve is not None and placeholders(vt) != placeholders(ve):
            ph_mismatch.append(rk)
    chk(not missing_tr, f"S6 TR referans anahtarları tam (eksik={missing_tr})")
    chk(not missing_en, f"S6 EN referans anahtarları tam (eksik={missing_en})")
    chk(not empty, f"S6 boş değer yok (boş={empty})")
    chk(not ph_mismatch, f"S6 TR↔EN placeholder parity (uyumsuz={ph_mismatch})")
    for key, phs in spec.get("placeholders", {}).items():
        vt = resolve(tr, f"screen.a04.{key}")
        chk(vt is not None and placeholders(vt) == set(phs), f"S6 {key} placeholder = {phs}")

    # S7 — saf türetme yardımcıları mevcut + deterministik (Date.now/random yok)
    for fn in ("stepStatus", "stepById", "completedSteps", "requiredSteps", "incompleteRequiredSteps",
               "requiredStepsComplete", "completionPercent", "fieldsTotal", "fieldsComplete",
               "hasConversationModel", "readyForDraft", "readyForTest", "readyForPublish", "blockers",
               "nextStep", "stepTone", "modelTone", "testTone", "startModeTone", "readyTone"):
        chk(fn in data, f"S7 {fn} tanımlı")
    chk("STEP_ORDER" in data and "REQUIRED_STEPS" in data, "S7 STEP_ORDER + REQUIRED_STEPS sabitleri tanımlı")
    chk("Date.now(" not in data and "Math.random(" not in data, "S7 Date.now()/Math.random() çağrısı YOK (deterministik)")

    # S8 — vendor-neutral + sır yok
    forbidden_vendors = ["openai", "anthropic", "datadog.com", "secret=", "splunk", "sumologic", "twilio.com", "telnyx.com"]
    blob = (page + data).lower()
    hit = [v for v in forbidden_vendors if v in blob]
    chk(not hit, f"S8 vendor-neutral + sır/credential yok (bulunan={hit})")

    passed = sum(1 for ok, _ in checks if ok)
    total = len(checks)
    for ok, label in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nvalidate: {passed}/{total} {GREEN if passed == total else RED}")
    return 0 if passed == total else 1


# ── check ────────────────────────────────────────────────────────────────────────

def _step(sid, required=True, total=1, done=1):
    return {"id": sid, "required": required, "fieldsTotal": total, "fieldsComplete": done}


def _draft(model="node_flow", test="not_run", lifecycle="draft", start="template",
           template="TPL-1", base=None, variant=False, steps=None):
    if steps is None:
        steps = [
            _step("basics", True, 5, 5),
            _step("conversation_model", True, 1, 1),
            _step("knowledge", False, 3, 2),
            _step("tools", False, 2, 0),
            _step("voice_model", True, 3, 3),
            _step("policies", True, 4, 4),
        ]
    return {"draftRef": "DRAFT-1", "name": "Agent", "purpose": "p", "personality": "warm",
            "languages": ["tr", "en"], "businessRulesCount": 3, "conversationModel": model,
            "startMode": start, "templateRef": template, "baseAgentRef": base, "isVariant": variant,
            "lifecycle": lifecycle, "testStatus": test, "steps": steps}


def cmd_check():
    checks = []

    def chk(cond, label):
        checks.append((bool(cond), label))

    steps = [
        _step("basics", True, 5, 5),       # complete
        _step("conversation_model", True, 1, 1),  # complete
        _step("knowledge", False, 3, 2),   # in_progress (opsiyonel)
        _step("tools", False, 2, 0),       # incomplete (opsiyonel)
        _step("voice_model", True, 3, 2),  # in_progress (zorunlu) → bloklar
        _step("policies", True, 4, 0),     # incomplete (zorunlu) → bloklar
    ]
    chk(step_status(_step("x", total=3, done=3)) == "complete", "stepStatus complete")
    chk(step_status(_step("x", total=3, done=1)) == "in_progress", "stepStatus in_progress")
    chk(step_status(_step("x", total=3, done=0)) == "incomplete", "stepStatus incomplete")
    chk([s["id"] for s in completed_steps(steps)] == ["basics", "conversation_model"], "completedSteps")
    chk([s["id"] for s in required_steps(steps)] == ["basics", "conversation_model", "voice_model", "policies"], "requiredSteps")
    chk([s["id"] for s in incomplete_required_steps(steps)] == ["voice_model", "policies"], "incompleteRequiredSteps")
    chk(required_steps_complete(steps) is False, "requiredStepsComplete=False")
    chk(completion_percent(steps) == 33, "completionPercent=33 (2/6)")
    chk(fields_total(steps) == 18, "fieldsTotal=18")
    chk(fields_complete(steps) == 10, "fieldsComplete=10")

    draft = _draft(steps=steps, model="node_flow", test="not_run")
    chk(has_conversation_model(draft) is True, "hasConversationModel=True")
    chk(ready_for_draft(draft) is True, "readyForDraft=True (basics tam)")
    chk(ready_for_test(draft) is False, "readyForTest=False (zorunlu eksik)")
    chk(ready_for_publish(draft) is False, "readyForPublish=False")
    chk(blockers(draft) == ["voice_model", "policies"], "blockers=[voice_model,policies]")
    chk(next_step(draft) == "knowledge", "nextStep=knowledge (sırada ilk tamamlanmamış)")

    # tam taslak → test'e hazır; testi geçince yayına hazır
    full = _draft(model="single_prompt", test="passed")
    chk(ready_for_test(full) is True, "readyForTest=True (tüm zorunlu + model)")
    chk(ready_for_publish(full) is True, "readyForPublish=True (test passed)")
    chk(blockers(full) == [], "blockers=[] (tam)")
    chk(next_step(full) == "knowledge", "nextStep=knowledge (opsiyonel ilk eksik)")

    # model yoksa test'e hazır değil + blockers'a eklenir
    no_model = _draft(model=None, test="not_run",
                      steps=[_step("basics", True, 1, 1), _step("conversation_model", True, 1, 0),
                             _step("voice_model", True, 1, 1), _step("policies", True, 1, 1)])
    chk(ready_for_test(no_model) is False, "readyForTest=False (model yok)")
    chk(blockers(no_model) == ["conversation_model"], "blockers=[conversation_model]")

    # tone eşlemeleri
    chk(step_tone("complete") == "success" and step_tone("in_progress") == "warning" and step_tone("incomplete") == "neutral", "stepTone")
    chk(model_tone("node_flow") == "info" and model_tone("single_prompt") == "neutral" and model_tone(None) == "warning", "modelTone")
    chk(test_tone("passed") == "success" and test_tone("failed") == "danger" and test_tone("not_run") == "warning", "testTone")
    chk(start_mode_tone("template") == "info" and start_mode_tone("clone") == "info" and start_mode_tone("blank") == "neutral", "startModeTone")
    chk(ready_tone(True) == "success" and ready_tone(False) == "warning", "readyTone")

    # assertNoPii — konfigürasyon META İZİNLİ, ham içerik + sır + prompt-gövdesi YASAK
    chk(assert_no_pii({"a": _draft()}) is None, "assertNoPii konfigürasyon META İZİNLİ")
    chk(assert_no_pii({"x": {"transcript": "..."}}) == "$.x.transcript", "assertNoPii ham transcript yakalar")
    chk(assert_no_pii({"x": {"apiKey": "k"}}) == "$.x.apiKey", "assertNoPii tool sırrı yakalar (NFR 10.6)")
    chk(assert_no_pii({"x": {"promptText": "..."}}) == "$.x.promptText", "assertNoPii prompt gövdesi yakalar (A-06 derin)")

    # samples doğrulaması
    for name in ("builder-ready.json", "builder-incomplete.json"):
        snp = load_json(os.path.join(HERE, "samples", name))
        exp = snp.get("$expect", {})
        d = snp["draft"]
        st = d["steps"]
        chk(completion_percent(st) == exp.get("completion"), f"{name} completion={exp.get('completion')}")
        chk(len(completed_steps(st)) == exp.get("completed_steps"), f"{name} completed_steps={exp.get('completed_steps')}")
        chk(len(incomplete_required_steps(st)) == exp.get("incomplete_required"), f"{name} incomplete_required={exp.get('incomplete_required')}")
        chk(ready_for_draft(d) == exp.get("ready_draft"), f"{name} ready_draft={exp.get('ready_draft')}")
        chk(ready_for_test(d) == exp.get("ready_test"), f"{name} ready_test={exp.get('ready_test')}")
        chk(ready_for_publish(d) == exp.get("ready_publish"), f"{name} ready_publish={exp.get('ready_publish')}")
        chk(blockers(d) == exp.get("blockers"), f"{name} blockers={exp.get('blockers')}")
        chk(next_step(d) == exp.get("next_step"), f"{name} next_step={exp.get('next_step')}")
        chk(len(snp.get("templates", [])) == exp.get("templates"), f"{name} templates={exp.get('templates')}")
        chk(assert_no_pii(snp) is None, f"{name} PII/sır-free (HİJYEN+GÜVENLİK)")

    passed = sum(1 for ok, _ in checks if ok)
    total = len(checks)
    for ok, label in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\ncheck: {passed}/{total} {GREEN if passed == total else RED}")
    return 0 if passed == total else 1


# ── selftest ────────────────────────────────────────────────────────────────────

def cmd_selftest():
    results = []

    def expect(cond, label):
        results.append((bool(cond), label))

    # pozitif (yayına hazır taslak)
    ready = _draft(model="node_flow", test="passed")
    expect(required_steps_complete(ready["steps"]) is True, "pos zorunlu adımlar tam")
    expect(ready_for_draft(ready) is True, "pos taslak hazır")
    expect(ready_for_test(ready) is True, "pos test'e hazır")
    expect(ready_for_publish(ready) is True, "pos yayına hazır")
    expect(blockers(ready) == [], "pos blocker yok")
    expect(completion_percent(ready["steps"]) == 67, "pos completion=67 (4/6, knowledge+tools opsiyonel eksik)")

    # negatif (eksik/bloklu taslak beklendiği gibi yakalanır)
    bad = _draft(model=None, test="failed",
                 steps=[_step("basics", True, 4, 4),           # complete
                        _step("conversation_model", True, 1, 0),  # eksik (model yok)
                        _step("knowledge", False, 2, 0),       # opsiyonel eksik
                        _step("tools", False, 2, 1),           # opsiyonel devam
                        _step("voice_model", True, 3, 1),      # zorunlu eksik
                        _step("policies", True, 2, 2)])        # complete
    expect(ready_for_draft(bad) is True, "neg basics tam → taslak hazır")
    expect(ready_for_test(bad) is False, "neg test'e hazır değil (model+voice eksik)")
    expect(ready_for_publish(bad) is False, "neg yayına hazır değil (test failed)")
    expect(blockers(bad) == ["conversation_model", "voice_model"], "neg blockers=[conversation_model,voice_model]")
    expect(next_step(bad) == "conversation_model", "neg nextStep=conversation_model")
    expect([s["id"] for s in incomplete_required_steps(bad["steps"])] == ["conversation_model", "voice_model"], "neg incompleteRequired")

    # sınır: model seçili ama conversation_model adımı tamam değilse → yine test'e hazır değil
    edge = _draft(model="single_prompt",
                  steps=[_step("basics", True, 1, 1), _step("conversation_model", True, 1, 0),
                         _step("voice_model", True, 1, 1), _step("policies", True, 1, 1)])
    expect(ready_for_test(edge) is False, "sınır model seçili ama adım eksik → hazır değil")
    expect(blockers(edge) == ["conversation_model"], "sınır blockers=[conversation_model] (tekilleştirildi)")

    # sınır: opsiyonel adımlar zorunluyu etkilemez
    opt = _draft(model="node_flow",
                 steps=[_step("basics", True, 1, 1), _step("conversation_model", True, 1, 1),
                        _step("knowledge", False, 3, 0), _step("tools", False, 2, 0),
                        _step("voice_model", True, 1, 1), _step("policies", True, 1, 1)])
    expect(ready_for_test(opt) is True, "sınır opsiyonel eksik → test'e hazır (zorunlu tam)")
    expect(blockers(opt) == [], "sınır opsiyonel eksik blocker değil")

    # completion sınırları
    expect(completion_percent([]) == 0, "sınır boş adım → 0%")
    expect(completion_percent([_step("a", True, 0, 0)]) == 0, "sınır fieldsTotal=0 → incomplete (complete değil)")

    # assertNoPii pozitif/negatif
    expect(assert_no_pii({"a": {"b": 1}}) is None, "pos no-pii")
    expect(assert_no_pii({"x": {"callerNumber": "1"}}) is not None, "neg callerNumber yakalanır")
    expect(assert_no_pii({"s": [{"webhookSecret": "x"}]}) is not None, "neg webhookSecret yakalanır")
    expect(assert_no_pii({"x": {"promptBody": "..."}}) is not None, "neg promptBody yakalanır (A-06 derin)")
    expect(assert_no_pii({"x": {"cdr": {}}}) is not None, "neg cdr yakalanır")

    # tone sınır
    expect(model_tone(None) == "warning", "neg model seçilmedi → warning")
    expect(test_tone("failed") == "danger", "neg test failed → danger")

    # placeholder ayrıştırma
    expect(placeholders("{done} / {total} alan") == {"done", "total"}, "placeholder parse")

    # spec referans anahtarları tutarlı
    spec = load_json(SPEC_PATH)
    expect(len(spec["referenced_keys"]) >= 90, "spec ≥90 referans anahtar")
    expect(spec["step_ids"] == STEP_ORDER, "spec step_ids = STEP_ORDER")
    expect(spec["required_steps"] == REQUIRED_STEPS, "spec required_steps = REQUIRED_STEPS")

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    for ok, label in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nselftest: {passed}/{total} {GREEN if passed == total else RED}")
    return 0 if passed == total else 1


def cmd_schema():
    print(json.dumps({
        "BuilderView": {
            "generatedAt": "ISO-8601 string (sabit yer tutucu)",
            "tenantRef": "str (tenant KENDİ kimliği — izinli)",
            "tenantName": "str (tenant org adı — izinli)",
            "draft": {
                "draftRef": "str (gösterim referansı)",
                "name": "str (tenant config — FR-AGT-002; PII değil)", "purpose": "str (tenant config)",
                "personality": "str|null (kişilik preset — FR-AGT-002)", "languages": "str[] (FR-AGT-002)",
                "businessRulesCount": "int (iş kuralı SAYISI — kural metni gömülmez)",
                "conversationModel": "single_prompt|node_flow|null (FR-AGT-003)",
                "startMode": "blank|template|clone (no-code başlangıç — FR-AGT-001)",
                "templateRef": "str|null", "baseAgentRef": "str|null (klon/varyant — FR-AGT-008)",
                "isVariant": "bool (FR-AGT-008)", "lifecycle": "draft|test|staging|production|archived (FR-AGT-005)",
                "testStatus": "passed|failed|not_run (FR-AGT-010)",
                "steps": [{"id": "basics|conversation_model|knowledge|tools|voice_model|policies",
                           "required": "bool", "fieldsTotal": "int", "fieldsComplete": "int (0..fieldsTotal)"}]
            },
            "templates": [{"templateRef": "str", "name": "str", "purpose": "str",
                           "mode": "single_prompt|node_flow", "languages": "str[]"}]
        },
        "step_ids": STEP_ORDER,
        "required_steps": REQUIRED_STEPS,
        "hijyen": "A-04 yalnız KONFİGÜRASYON META gösterir (taslak ad/amaç/adım alan sayıları/mod — tenant'ın KENDİ yapılandırması). FORBIDDEN_PII_KEYS dışı son-müşteri ham içeriği (transkript/kayıt/ham numara/CDR/müşteri) YOK (BRD §17.7 + §17.6); FORBIDDEN_SECRET_KEYS dışı sır/credential + PROMPT GÖVDESİ (apiKey/webhookSecret/token/promptText/...) YOK (NFR 10.6); assertNoPii çalışma-anında doğrular. Akış/prompt/tool tasarımı derin aksiyon → A-05/A-06/A-09 (görsel kapı). KONFİGÜRASYON ekranı — gerçek zamanlı DEĞİL (FR-ANA-012 dışı)."
    }, ensure_ascii=False, indent=2))
    return 0


def main():
    cmds = {"validate": cmd_validate, "check": cmd_check, "selftest": cmd_selftest, "schema": cmd_schema}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("kullanım: a04_builder_probe.py {validate|check|selftest|schema}")
        return 2
    return cmds[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
