#!/usr/bin/env python3
# WBS 13.3.4 — T-04 "Telefon Numarası & SIP/Trunk" doğrulama probe'u (stdlib-only, credential-free,
# deterministik).
#
# Komutlar:
#   validate  — ON-DISK invariant taraması (sayfa + veri seam + i18n + spec; S1..S8)
#   check     — SAF çekirdek senaryo aynası (countNumberStatus/unassignedNumbers/invalidTrunkRefs/isValidE164/
#               invalidE164Numbers/trunkUtilizationPct/overCapacityTrunks/unverifiedDefaultCallerIds/tone'lar/
#               assertNoPii) + samples/* snapshot doğrulaması
#   selftest  — pozitif + negatif kendi-testleri (degrade senaryolar beklendiği gibi eler)
#   schema    — snapshot şema özeti
#
# Bu probe TS saf yardımcılarının (lib/tenant/numbers.ts) Python AYNASIDIR; mantık birebir kopya.
# 0.2.x/0.3.x probe disiplini (sağlayıcı-nötr ADR-002, stdlib-only, sanal-saat) bir UI ekranına taşınır.
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.path.join(HERE, "..", ".."))          # frontend/tenant-app
REPO = os.path.abspath(os.path.join(APP, "..", ".."))
SPEC_PATH = os.path.join(HERE, "t04-numbers-spec.json")
PAGE_PATH = os.path.join(APP, "app", "(tenant-admin)", "admin", "numbers", "page.tsx")
DATA_PATH = os.path.join(APP, "lib", "tenant", "numbers.ts")
TR_PATH = os.path.join(APP, "lib", "i18n", "tr.json")
EN_PATH = os.path.join(APP, "lib", "i18n", "en.json")

GREEN, RED = "🟢", "🔴"


def load_json(p):
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_text(p):
    with open(p, "r", encoding="utf-8") as fh:
        return fh.read()


# ── SAF çekirdek aynası (lib/tenant/numbers.ts ile birebir) ───────────────────────

FORBIDDEN_PII_KEYS = ["transcript", "recording", "recordingurl", "audio", "msisdn",
                      "phonenumber", "callerid", "callernumber", "customer", "cardpan",
                      "cvv", "ssn", "pii"]
FORBIDDEN_SECRET_KEYS = ["password", "sippassword", "secret", "token", "authtoken",
                         "credential", "apikey", "privatekey"]

E164_RE = re.compile(r"^\+[1-9]\d{0,14}$")


def count_number_status(numbers):
    out = {"active": 0, "reserved": 0, "porting": 0, "released": 0}
    for n in numbers:
        out[n["status"]] += 1
    return out


def count_number_direction(numbers):
    out = {"inbound": 0, "outbound": 0, "both": 0}
    for n in numbers:
        out[n["direction"]] += 1
    return out


def unassigned_numbers(numbers):
    return [n["id"] for n in numbers
            if n["status"] == "active" and (n["assignedTo"] is None or n["assignedTo"].strip() == "")]


def numbers_for_trunk(numbers, trunk_id):
    return sum(1 for n in numbers if n["trunkRef"] == trunk_id)


def invalid_trunk_refs(numbers, trunks):
    ids = {t["id"] for t in trunks}
    return [n["id"] for n in numbers
            if n["trunkRef"] is not None and n["trunkRef"].strip() != "" and n["trunkRef"] not in ids]


def is_valid_e164(s):
    return bool(E164_RE.match(s))


def invalid_e164_numbers(numbers):
    return [n["id"] for n in numbers if not is_valid_e164(n["e164"])]


def trunk_utilization_pct(trunk):
    if trunk["channels"] <= 0:
        return 0
    pct = (trunk["channelsInUse"] / trunk["channels"]) * 100
    return max(0, min(100, round(pct)))


def over_capacity_trunks(trunks, threshold_pct=90):
    return [t["id"] for t in trunks if trunk_utilization_pct(t) >= threshold_pct]


def unverified_default_caller_ids(caller_ids):
    return [c["id"] for c in caller_ids if c["isDefault"] and c["status"] != "verified"]


def number_status_tone(s):
    return {"active": "success", "reserved": "info", "porting": "warning", "released": "neutral"}[s]


def trunk_state_tone(s):
    return {"connected": "success", "degraded": "warning", "disabled": "neutral", "error": "danger"}[s]


def trunk_type_tone(t):
    return {"sip_trunk": "info", "byoc": "info", "managed": "neutral"}[t]


def caller_id_status_tone(s):
    return {"verified": "success", "pending": "warning", "rejected": "danger"}[s]


def direction_tone(d):
    return {"inbound": "info", "outbound": "info", "both": "neutral"}[d]


def util_tone(pct):
    if pct >= 90:
        return "danger"
    if pct >= 75:
        return "warning"
    return "success"


def assert_no_pii(node, path="$"):
    """Yasak PII/iş-içeriği VEYA SIP trunk sırrı alan adı bulursa (path) döndürür; yoksa None."""
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
    chk(spec.get("wbs") == "13.3.4", "S0 spec.wbs=13.3.4")
    chk(os.path.isfile(PAGE_PATH), "S1 admin/numbers/page.tsx mevcut")
    chk('data-screen="T-04"' in page, 'S1 data-screen="T-04" işaretli')
    chk("İskelet ekran — T-04" not in page, "S1 iskelet placeholder kaldırıldı")

    # S2 — tasarım sistemi + i18n + veri seam kullanımı
    chk("@/lib/ui/components" in page, "S2 tasarım sistemi (lib/ui) kullanır")
    chk("@/lib/i18n" in page, "S2 i18n (lib/i18n) kullanır")
    chk("@/lib/tenant/numbers" in page, "S2 veri seam (lib/tenant/numbers) kullanır")
    chk("getServerLocale" in page, "S2 sunucu-tarafı locale müzakeresi")
    for comp in ("PageHeader", "Card", "StatusPill", "Table"):
        chk(comp in page, f"S2 {comp} komponenti kullanılır")

    # S3 — kullanıcı-görünür metin i18n'den (screen.t04.*); hardcoded TR/EN cümle yok
    chk("screen.t04." in page, "S3 screen.t04.* anahtarları referans alınır")
    jsx_text = re.findall(r">\s*([A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü ]{3,})\s*<", page)
    chk(len(jsx_text) == 0, f"S3 JSX'te hardcoded metin yok (bulunan={jsx_text[:3]})")

    # S4 — veri katmanı son-müşteri-PII-free + SIP-trunk-sır-free + HİJYEN/GÜVENLİK guard
    chk(os.path.isfile(DATA_PATH), "S4 lib/tenant/numbers.ts mevcut")
    chk("FORBIDDEN_PII_KEYS" in data, "S4 FORBIDDEN_PII_KEYS tanımlı")
    chk("FORBIDDEN_SECRET_KEYS" in data, "S4 FORBIDDEN_SECRET_KEYS tanımlı (NFR 10.6)")
    chk("assertNoPii" in data, "S4 assertNoPii guard tanımlı")
    chk(re.search(r"assertNoPii\(snap\)", data) is not None, "S4 getNumbers assertNoPii çağırır")
    leak = assert_no_pii({"data_field_scan": _extract_data_fields(data)})
    chk(leak is None, f"S4 veri seam türlerinde PII/sır alanı yok (sızıntı={leak})")

    # S5 — BRD §17.4 üç içerik öğesi (numara havuzu/SIP trunk-BYOC/Caller ID) + E.164 + BYOC + atama karşılanır
    t04 = tr.get("screen", {}).get("t04", {})
    sec = t04.get("section", {})
    chk("numbers" in sec, "S5 numara havuzu → section.numbers")
    chk("trunks" in sec, "S5 SIP trunk/BYOC → section.trunks")
    chk("caller_ids" in sec, "S5 Caller ID → section.caller_ids")
    chk("byoc" in t04.get("trunk_type", {}), "S5 BYOC trunk türü (FR-TEL-002)")
    chk("invalid_e164" in t04.get("badge", {}), "S5 E.164 doğrulama rozeti (FR-TEL-004)")
    chk("pool_label" in t04 and "assignment" in t04.get("col", {}), "S5 numara havuzu/atama (FR-AGT-007)")
    chk("isValidE164" in data and "trunkRef" in data, "S5 veri katmanı E.164 doğrulama + trunk bağlama")

    # S6 — referans anahtarlar var + TR↔EN parity + placeholder + boş değer yok
    ref = spec["referenced_keys"]
    missing_tr, missing_en, empty, ph_mismatch = [], [], [], []
    for rk in ref:
        full = f"screen.t04.{rk}"
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
        vt = resolve(tr, f"screen.t04.{key}")
        chk(vt is not None and placeholders(vt) == set(phs), f"S6 {key} placeholder = {phs}")

    # S7 — saf türetme yardımcıları mevcut + deterministik (Date.now/random yok)
    for fn in ("countNumberStatus", "countNumberDirection", "unassignedNumbers", "numbersForTrunk",
               "invalidTrunkRefs", "isValidE164", "invalidE164Numbers", "trunkUtilizationPct",
               "overCapacityTrunks", "unverifiedDefaultCallerIds", "numberStatusTone", "trunkStateTone",
               "trunkTypeTone", "callerIdStatusTone", "directionTone", "utilTone"):
        chk(fn in data, f"S7 {fn} tanımlı")
    chk("Date.now(" not in data and "Math.random(" not in data, "S7 Date.now()/Math.random() çağrısı YOK (deterministik)")

    # S8 — vendor-neutral + sır yok (somut operatör/SaaS markası + literal sır taraması)
    forbidden_vendors = ["openai", "anthropic", "datadog.com", "api_key", "secret=",
                         "twilio", "telnyx", "vonage", "sinch", "amazon connect", "genesys"]
    blob = (page + data).lower()
    hit = [v for v in forbidden_vendors if v in blob]
    chk(not hit, f"S8 vendor-neutral + sır/credential yok (bulunan={hit})")

    passed = sum(1 for ok, _ in checks if ok)
    total = len(checks)
    for ok, label in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nvalidate: {passed}/{total} {GREEN if passed == total else RED}")
    return 0 if passed == total else 1


def _extract_data_fields(ts):
    """numbers.ts interface alan adlarını kaba çıkar (PII/sır-alan-adı taraması için)."""
    return {m: 1 for m in re.findall(r"^\s*(\w+)\s*[?:]", ts, re.M)}


# ── check ────────────────────────────────────────────────────────────────────────

def cmd_check():
    checks = []

    def chk(cond, label):
        checks.append((bool(cond), label))

    trunks = [
        {"id": "TRK-1", "type": "sip_trunk", "state": "connected", "channels": 100, "channelsInUse": 95},
        {"id": "TRK-2", "type": "byoc", "state": "degraded", "channels": 50, "channelsInUse": 20},
        {"id": "TRK-3", "type": "managed", "state": "connected", "channels": 0, "channelsInUse": 0},
    ]
    numbers = [
        {"id": "N1", "e164": "+902123456789", "direction": "inbound", "trunkRef": "TRK-1", "assignedTo": "AGT-1", "status": "active"},
        {"id": "N2", "e164": "+908502222222", "direction": "outbound", "trunkRef": "TRK-2", "assignedTo": None, "status": "active"},
        {"id": "N3", "e164": "+443069990000", "direction": "both", "trunkRef": "TRK-9", "assignedTo": None, "status": "porting"},  # geçersiz trunk
        {"id": "N4", "e164": "00902120001122", "direction": "both", "trunkRef": None, "assignedTo": None, "status": "active"},  # geçersiz E.164
        {"id": "N5", "e164": "+902129990000", "direction": "outbound", "trunkRef": "TRK-1", "assignedTo": "CMP-1", "status": "reserved"},
    ]
    caller_ids = [
        {"id": "C1", "status": "verified", "isDefault": True},
        {"id": "C2", "status": "pending", "isDefault": False},
        {"id": "C3", "status": "pending", "isDefault": True},  # varsayılan ama doğrulanmamış
    ]

    chk(count_number_status(numbers) == {"active": 3, "reserved": 1, "porting": 1, "released": 0}, "countNumberStatus")
    chk(count_number_direction(numbers) == {"inbound": 1, "outbound": 2, "both": 2}, "countNumberDirection")
    chk(unassigned_numbers(numbers) == ["N2", "N4"], "unassignedNumbers=[N2,N4] (aktif+atanmamış)")
    chk(numbers_for_trunk(numbers, "TRK-1") == 2, "numbersForTrunk TRK-1=2")
    chk(invalid_trunk_refs(numbers, trunks) == ["N3"], "invalidTrunkRefs=[N3] (TRK-9)")
    chk(is_valid_e164("+902123456789") and not is_valid_e164("00902120001122") and not is_valid_e164("+0123"), "isValidE164")
    chk(invalid_e164_numbers(numbers) == ["N4"], "invalidE164Numbers=[N4]")
    chk(trunk_utilization_pct(trunks[0]) == 95, "trunkUtilizationPct TRK-1=95")
    chk(trunk_utilization_pct(trunks[2]) == 0, "trunkUtilizationPct channels=0 → 0")
    chk(over_capacity_trunks(trunks) == ["TRK-1"], "overCapacityTrunks=[TRK-1] (≥90)")
    chk(unverified_default_caller_ids(caller_ids) == ["C3"], "unverifiedDefaultCallerIds=[C3]")
    # tone eşlemeleri
    chk(number_status_tone("active") == "success" and number_status_tone("porting") == "warning" and number_status_tone("released") == "neutral", "numberStatusTone")
    chk(trunk_state_tone("connected") == "success" and trunk_state_tone("degraded") == "warning" and trunk_state_tone("error") == "danger", "trunkStateTone")
    chk(trunk_type_tone("sip_trunk") == "info" and trunk_type_tone("byoc") == "info" and trunk_type_tone("managed") == "neutral", "trunkTypeTone")
    chk(caller_id_status_tone("verified") == "success" and caller_id_status_tone("pending") == "warning" and caller_id_status_tone("rejected") == "danger", "callerIdStatusTone")
    chk(direction_tone("inbound") == "info" and direction_tone("both") == "neutral", "directionTone")
    chk(util_tone(95) == "danger" and util_tone(80) == "warning" and util_tone(40) == "success", "utilTone")
    # assertNoPii — kendi envanter İZİNLİ, son-müşteri PII + SIP trunk sırrı YASAK
    chk(assert_no_pii({"numbers": [{"e164": "+902123456789", "label": "Ana Hat"}]}) is None, "assertNoPii kendi e164 İZİNLİ")
    chk(assert_no_pii({"tenantName": "Acme", "trunks": [{"name": "Birincil"}]}) is None, "assertNoPii tenant/trunk adı İZİNLİ")
    chk(assert_no_pii({"call": {"transcript": "x"}}) == "$.call.transcript", "assertNoPii transcript yakalar")
    chk(assert_no_pii({"msisdn": "x"}) == "$.msisdn", "assertNoPii msisdn (son-müşteri) yakalar")
    chk(assert_no_pii({"trunk": {"sipPassword": "x"}}) == "$.trunk.sipPassword", "assertNoPii SIP parolası yakalar (NFR 10.6)")
    chk(assert_no_pii({"trunk": {"authToken": "x"}}) == "$.trunk.authToken", "assertNoPii auth token yakalar")

    # samples doğrulaması
    for name in ("numbers-clean.json", "numbers-issues.json"):
        snap = load_json(os.path.join(HERE, "samples", name))
        exp = snap.get("$expect", {})
        cs = count_number_status(snap["numbers"])
        chk(cs["active"] == exp.get("active_numbers"), f"{name} active_numbers={exp.get('active_numbers')}")
        chk(unassigned_numbers(snap["numbers"]) == exp.get("pool"), f"{name} pool={exp.get('pool')}")
        chk(invalid_trunk_refs(snap["numbers"], snap["trunks"]) == exp.get("invalid_trunks"), f"{name} invalid_trunks={exp.get('invalid_trunks')}")
        chk(invalid_e164_numbers(snap["numbers"]) == exp.get("invalid_e164"), f"{name} invalid_e164={exp.get('invalid_e164')}")
        chk(over_capacity_trunks(snap["trunks"]) == exp.get("over_capacity"), f"{name} over_capacity={exp.get('over_capacity')}")
        chk(unverified_default_caller_ids(snap["callerIds"]) == exp.get("unverified_default"), f"{name} unverified_default={exp.get('unverified_default')}")
        chk(assert_no_pii(snap) is None, f"{name} PII/sır-free (HİJYEN+GÜVENLİK)")

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

    trunks = [{"id": "T1", "type": "sip_trunk", "state": "connected", "channels": 10, "channelsInUse": 1}]
    numbers = [{"id": "A", "e164": "+15551234567", "direction": "inbound", "trunkRef": "T1", "assignedTo": "AGT", "status": "active"}]
    # pozitif
    expect(count_number_status(numbers) == {"active": 1, "reserved": 0, "porting": 0, "released": 0}, "pos countNumberStatus")
    expect(count_number_direction(numbers) == {"inbound": 1, "outbound": 0, "both": 0}, "pos countNumberDirection")
    expect(unassigned_numbers(numbers) == [], "pos havuz boş (atanmış)")
    expect(numbers_for_trunk(numbers, "T1") == 1, "pos numbersForTrunk")
    expect(invalid_trunk_refs(numbers, trunks) == [], "pos invalid trunk boş")
    expect(invalid_e164_numbers(numbers) == [], "pos invalid e164 boş")
    expect(over_capacity_trunks(trunks) == [], "pos over-capacity boş")
    expect(unverified_default_caller_ids([{"id": "C", "status": "verified", "isDefault": True}]) == [], "pos doğrulanmış varsayılan OK")
    expect(assert_no_pii({"a": {"b": 1}}) is None, "pos no-pii")
    # negatif (degrade beklendiği gibi yakalanır)
    expect(is_valid_e164("+1") is True and is_valid_e164("+") is False, "neg E.164 sınır")
    expect(is_valid_e164("+1234567890123456") is False, "neg E.164 >15 hane elenir")
    expect(invalid_e164_numbers([{"id": "Z", "e164": "0850", "direction": "both", "trunkRef": None, "assignedTo": None, "status": "active"}]) == ["Z"], "neg geçersiz E.164 yakalanır")
    expect(invalid_trunk_refs([{"id": "Z", "trunkRef": "ghost"}], trunks) == ["Z"], "neg geçersiz trunk yakalanır")
    expect(unassigned_numbers([{"id": "Z", "status": "active", "assignedTo": "  ", "e164": "+1", "direction": "both", "trunkRef": None}]) == ["Z"], "neg boşluk-atama havuz sayılır")
    expect(over_capacity_trunks([{"id": "Z", "channels": 10, "channelsInUse": 9}]) == ["Z"], "neg %90 eşik yakalanır")
    expect(unverified_default_caller_ids([{"id": "Z", "status": "pending", "isDefault": True}]) == ["Z"], "neg doğrulanmamış varsayılan yakalanır")
    expect(assert_no_pii({"x": {"recording": "u"}}) is not None, "neg recording yakalanır")
    expect(assert_no_pii({"callerId": "x"}) is not None, "neg son-müşteri callerId yakalanır")
    expect(assert_no_pii({"settings": [{"credential": "x"}]}) is not None, "neg trunk credential yakalanır")
    expect(util_tone(90) == "danger", "neg %90 util → danger")
    expect(number_status_tone("reserved") == "info", "neg rezerve → info")
    # placeholder ayrıştırma
    expect(placeholders("As of: {time}") == {"time"}, "placeholder parse")
    # spec referans anahtarları tutarlı
    spec = load_json(SPEC_PATH)
    expect(len(spec["referenced_keys"]) >= 55, "spec ≥55 referans anahtar")

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    for ok, label in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nselftest: {passed}/{total} {GREEN if passed == total else RED}")
    return 0 if passed == total else 1


def cmd_schema():
    print(json.dumps({
        "NumberSnapshot": {
            "generatedAt": "ISO-8601 string (sabit yer tutucu)",
            "tenantRef": "str (tenant KENDİ kimliği — izinli)",
            "tenantName": "str (tenant org adı — izinli)",
            "trunks": [{"id": "str", "name": "str (tenant etiketi — izinli)", "type": "sip_trunk|byoc|managed",
                        "state": "connected|degraded|disabled|error", "region": "str (home/residency kodu)",
                        "inbound": "bool", "outbound": "bool", "channels": "int", "channelsInUse": "int"}],
            "numbers": [{"id": "str", "e164": "str (E.164 — tenant KENDİ DID'i, izinli)", "label": "str|null",
                         "direction": "inbound|outbound|both", "trunkRef": "str|null (SipTrunk.id)",
                         "assignedTo": "str|null (agent/kampanya; null=havuz)", "status": "active|reserved|porting|released"}],
            "callerIds": [{"id": "str", "e164": "str (giden sunum — tenant KENDİ, izinli)", "label": "str|null",
                           "status": "verified|pending|rejected", "isDefault": "bool"}]
        },
        "hijyen": "FORBIDDEN_PII_KEYS dışı son-müşteri alanı yok (BRD §17.7); FORBIDDEN_SECRET_KEYS dışı SIP trunk sırrı yok (NFR 10.6); assertNoPii çalışma-anında doğrular. e164/name/label + tenant kimliği tenant'ın KENDİ envanteridir → izinli."
    }, ensure_ascii=False, indent=2))
    return 0


def main():
    cmds = {"validate": cmd_validate, "check": cmd_check, "selftest": cmd_selftest, "schema": cmd_schema}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("kullanım: t04_numbers_probe.py {validate|check|selftest|schema}")
        return 2
    return cmds[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
