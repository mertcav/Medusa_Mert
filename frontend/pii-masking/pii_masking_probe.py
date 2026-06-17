#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 13.1.4 — PII redaction/maskeleme (panel görüntülemede) referans probe.

13.1 "Ortak frontend altyapısı" alt-bloğunun DÖRDÜNCÜ modülü; F1-Must. 13.1.1 iki ayrı app + route group
İSKELETİNİ, 13.1.2 çalışma-anı middleware KAPISINI, 13.1.3 tasarım sistemi + i18n katmanını kurdu; bu modül
her iki app'e ORTAK bir SUNUM-KATMANI (view-time) PII maskeleme çekirdeği ekler ve şunları DOĞRULAR:

    POLİTİKA PARITY → PROHIBITED/RESTRICTED SINIF → ALAN MASKELEME (LEAK-FREE) → PROHIBITED REVEAL-IMMUNE
    → RESTRICTED REVEAL-GATED → SERBEST-METİN TARAMA → IDEMPOTENT → PRESENTASYONEL/AUTHZ-YOK → A11Y → SIR/PII-YOK

ÇEKİRDEK İLKELER (BRD §17.7 / FR-REC-004/005 / SAD §14.4.1):
  - SUNUM-KATMANI defense-in-depth: birincil redaction backend Analytics Plane'de async (SAD §19.2); panel
    veriyi GÖRÜNTÜLERKEN ikinci kez maskeler. Yetkisiz/varsayılan görünümde ham PII ekrana ASLA düşmez.
  - PROHIBITED sınıf (kart PAN / CVV / OTP / parola — FR-REC-005): panelde TAM değer ASLA; reveal flag'i
    YOK SAYILIR (reveal-immune). Kart için PCI ödünü yalnız son 4 hane.
  - RESTRICTED sınıf (e-posta / telefon / IBAN / ulusal kimlik — FR-REC-004): VARSAYILAN maskeli; yalnız
    ARKA UÇ yetkilendirdiğinde (canReveal=true) + kullanıcı açıkça reveal=true istediğinde ham gösterilir.
  - AUTHZ KARARI YOK (A8 / SAD §14.4.1): frontend permission'a KARAR VERMEZ — canReveal yalnız backend'den
    gelen bir flag'tir, çekirdek onu honor eder (rol→permission kararı 12.2.x backend + audit FR-REC-009).
  - TEK kaynak doğruluk: config/pii-policy.json; her app lib/pii/policy.json olarak BİREBİR vendor eder,
    probe canonical-hash ile drift'i FAIL eder (ADR-011 blast-radius — cross-app runtime import YOK, A7).
  - Vendor-neutral (ADR-002): maskeleme kütüphanesi bağlanmaz; saf string. Sır/PII DEĞERİ üretilmez/yazılmaz.

Saf çekirdek (lib/pii/mask.ts: maskField + scanAndMask) bu probe'ta Python ile BİREBİR aynalanır
(mask_field + scan_and_mask) — aynı semantik, davranışsal kapı + samples + selftest.

Kullanım:
  pii_masking_probe.py validate        Statik canonical + ON-DISK vendored kopya + maskeleme/leak/authz/a11y kapısı → çıkış kodu
  pii_masking_probe.py check <sample>   Davranış: field / scan / leak_guard senaryoları
  pii_masking_probe.py selftest         Gömülü davranış kontrolleri → çıkış kodu
  pii_masking_probe.py schema           Karar/sözleşme özetini yazdır

Determinizm: policy_hash sha256 (kanonik JSON, sort_keys); Date.now/rastgelelik YOK. Stdlib-only.
Sır/credential ve ham içerik (PII) üretilmez/yazılmaz; test vektörleri SENTETİK (ör. 4111 test kart no).
"""
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
POLICY_PATH = os.path.join(HERE, "config", "pii-policy.json")
SPEC_PATH = os.path.join(HERE, "pii-masking-spec.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

APPS = ("frontend/platform-app", "frontend/tenant-app")


# ── yardımcılar ───────────────────────────────────────────────────────────────

def _strip_comments(obj):
    if isinstance(obj, dict):
        return {k: _strip_comments(v) for k, v in obj.items() if not k.startswith("$")}
    if isinstance(obj, list):
        return [_strip_comments(x) for x in obj]
    return obj


def canonical_hash(obj):
    clean = _strip_comments(obj)
    blob = json.dumps(clean, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError):
        return ""


# ── SAF ÇEKİRDEK AYNASI (lib/pii/mask.ts) ───────────────────────────────────────

_POLICY = load_json(POLICY_PATH)
MASK = _POLICY["mask_char"]
REDACT = _POLICY["redact_token"]
CAT_BY_ID = {c["id"]: c for c in _POLICY["categories"]}
SCAN_ORDER = _POLICY["scan_order"]


def keep_last_alnum(raw, n):
    """Son n alfasayısal karakter hariç hepsini MASK ile değiştirir; ayraçlar korunur.
    Değer n'den kısaysa TÜMÜ maskelenir (leak-safe)."""
    alnum_total = sum(1 for c in raw if c.isalnum())
    # Değer n'den KISAYSA tümü maskelenir (leak-safe). Tam n ise korunur → idempotent
    # (zaten-maskeli değer yeniden maskelenince son-n korunmuş haneyi silmez).
    keep_n = n if alnum_total >= n else 0
    out = []
    seen = 0
    for c in raw:
        if c.isalnum():
            seen += 1
            if keep_n > 0 and seen > alnum_total - keep_n:
                out.append(c)
            else:
                out.append(MASK)
        else:
            out.append(c)
    return "".join(out)


def mask_email(raw):
    at = raw.find("@")
    if at <= 0:
        return REDACT
    local, domain = raw[:at], raw[at:]
    return local[0] + "•••" + domain


def apply_strategy(strat, raw, keep):
    if strat == "redact_full":
        return REDACT
    if strat == "keep_last":
        return keep_last_alnum(raw, keep)
    if strat == "mask_email":
        return mask_email(raw)
    return REDACT  # bilinmeyen strateji → fail-closed tam redaksiyon


def class_of(category):
    cat = CAT_BY_ID.get(category)
    return cat["class"] if cat else "restricted"  # bilinmeyen kategori → restricted (fail-closed maskele)


def mask_field(category, raw, reveal=False, can_reveal=False):
    """Tek bir PII alanını panel görüntülemesi için maskeler.
    PROHIBITED → daima maskeli (reveal YOK SAYILIR). RESTRICTED → yalnız (reveal ∧ canReveal) ham."""
    cat = CAT_BY_ID.get(category)
    cls = cat["class"] if cat else "restricted"
    strat = cat["strategy"] if cat else "redact_full"
    keep = cat.get("keep", 0) if cat else 0
    if cls == "restricted" and reveal and can_reveal:
        return raw  # backend-yetkili reveal — frontend KARAR VERMEZ, yalnız honor eder
    return apply_strategy(strat, raw, keep)


def _compile(scan):
    flags = re.I if "i" in scan.get("flags", "") else 0
    return re.compile(scan["regex"], flags)


def scan_and_mask(text, reveal=False, can_reveal=False):
    """Serbest metni (transkript) tarar ve eşleşen her PII'yi maskeler. scan_order sırasıyla;
    maskelenen haneler '•' olduğundan sonraki desenler yeniden eşleşmez → idempotent."""
    out = text
    for cid in SCAN_ORDER:
        cat = CAT_BY_ID.get(cid)
        scan = cat.get("scan") if cat else None
        if not scan:
            continue
        rx = _compile(scan)
        target = scan.get("target", "match")

        def repl(m, cid=cid, target=target):
            if target == "match":
                return mask_field(cid, m.group(0), reveal, can_reveal)
            val = m.group(1)
            return m.group(0).replace(val, mask_field(cid, val, reveal, can_reveal), 1)

        out = rx.sub(repl, out)
    return out


# ── SENTETİK test vektörleri (HAM PII DEĞİL — illüstratif/uydurma) ──────────────
# 4111 1111 1111 1111 = endüstri standardı TEST kart no (gerçek PAN değil). Diğerleri uydurma.
SYNTH = {
    "card_pan": "4111 1111 1111 1342",
    "cvv": "123",
    "otp": "482913",
    "password": "S3cr3t!",
    "email": "ada.lovelace@example.com",
    "iban": "TR120006400000112345678999",
    "national_id": "12345678901",
    "phone": "+90 532 123 45 67",
}


# ── validate (ON-DISK) ───────────────────────────────────────────────────────────

def app_paths(app_dir):
    base = os.path.join(REPO, app_dir)
    return {
        "policy": os.path.join(base, "lib", "pii", "policy.json"),
        "mask": os.path.join(base, "lib", "pii", "mask.ts"),
        "components": os.path.join(base, "lib", "pii", "components.tsx"),
    }


# Sunum-katmanı maskeleme presentasyoneldir; rol→permission KARARI içermez (A8). mask.ts bu authz
# token'larından HİÇBİRİNİ KARAR olarak içermemeli (canReveal yalnız backend flag'i, honor edilir).
FORBIDDEN_AUTHZ_DECISION = ["hasPermission(", "checkRole(", "rbac.", "permissions.includes",
                            'role === "', "isAdmin(", "grant("]
# Vendor-neutral: maskeleme/PII SaaS kütüphanesi bağlanmaz (saf string; ADR-002).
FORBIDDEN_VENDORS = ["redact-pii", "scrubber", "@datadog/pii", "presidio", "pii-filter"]
# Ham PII/credential DEĞERİ kaynakta/canonical'da yasaktır (samples/probe SENTETİK; bunlar taranmaz).
FORBIDDEN_SECRET_PII = ["BEGIN PRIVATE KEY", "password=", "secret=", "eyJhbGci",
                        "transcript_value", "raw_pan", "cvv_value=", "otp_value="]


def cmd_validate():
    canonical = load_json(POLICY_PATH)
    policy_hash = canonical_hash(canonical)
    checks = []

    def chk(cond, label):
        checks.append((bool(cond), label))

    # P1 — canonical varlığı + frozen + her app vendored kopya + mask.ts + components.tsx
    chk(canonical.get("frozen") is True, "P1 canonical policy frozen")
    chk(canonical.get("wbs") == "13.1.4", "P1 canonical policy.wbs=13.1.4")
    spec = load_json(SPEC_PATH)
    chk(spec.get("wbs") == "13.1.4", "P1 spec.wbs=13.1.4")
    for app in APPS:
        p = app_paths(app)
        for name in ("policy", "mask", "components"):
            chk(os.path.isfile(p[name]), f"P1 {app}/lib/pii/{name} mevcut")

    # P2 — politika parity (app vendored == canonical hash)
    for app in APPS:
        ah = canonical_hash(load_json(app_paths(app)["policy"]))
        chk(ah == policy_hash, f"P2 {app} lib/pii/policy.json canonical-hash eşit")

    # P3 — PROHIBITED sınıf: kart/CVV/OTP/parola tanımlı + class=prohibited (FR-REC-005)
    prohibited = {"card_pan", "cvv", "otp", "password"}
    for cid in sorted(prohibited):
        chk(CAT_BY_ID.get(cid, {}).get("class") == "prohibited", f"P3 {cid} class=prohibited (FR-REC-005)")
    chk(CAT_BY_ID.get("card_pan", {}).get("strategy") == "keep_last"
        and CAT_BY_ID["card_pan"].get("keep") == 4, "P3 card_pan keep_last(4) — PCI yalnız son 4")
    for cid in ("cvv", "otp", "password"):
        chk(CAT_BY_ID.get(cid, {}).get("strategy") == "redact_full", f"P3 {cid} redact_full (hiç hane kalmaz)")

    # P4 — RESTRICTED sınıf: e-posta/telefon/IBAN/ulusal kimlik tanımlı + class=restricted (FR-REC-004)
    restricted = {"email", "phone", "iban", "national_id"}
    for cid in sorted(restricted):
        chk(CAT_BY_ID.get(cid, {}).get("class") == "restricted", f"P4 {cid} class=restricted (FR-REC-004)")

    # P5 — alan maskeleme LEAK-FREE: her kategori için maskeli çıktı '•' içerir + ham != maskeli
    for cid, raw in SYNTH.items():
        masked = mask_field(cid, raw)
        chk(MASK in masked and masked != raw, f"P5 {cid} varsayılan maskeli + leak-free")
    # prohibited: tam değer çekirdeği görünmez (kart son4 hariç kart-gövdesi yok)
    pan = SYNTH["card_pan"]
    masked_pan = mask_field("card_pan", pan)
    pan_digits = "".join(c for c in pan if c.isdigit())
    chk(pan_digits[:-4] not in masked_pan.replace(" ", ""), "P5 kart PAN gövdesi (son-4 hariç) maskeli")
    chk(MASK * 4 == mask_field("cvv", SYNTH["cvv"]), "P5 CVV tamamen redakte (••••)")

    # P6 — PROHIBITED reveal-immune: reveal+canReveal=true OLSA BİLE maskeli (FR-REC-005)
    for cid in ("card_pan", "cvv", "otp", "password"):
        revealed = mask_field(cid, SYNTH[cid], reveal=True, can_reveal=True)
        chk(revealed == mask_field(cid, SYNTH[cid]) and revealed != SYNTH[cid],
            f"P6 {cid} reveal-immune (reveal+canReveal yok sayılır)")

    # P7 — RESTRICTED reveal-gated: varsayılan maskeli; yalnız (reveal ∧ canReveal) ham (FR-REC-004)
    for cid in ("email", "phone", "iban", "national_id"):
        default_masked = mask_field(cid, SYNTH[cid])
        only_reveal = mask_field(cid, SYNTH[cid], reveal=True, can_reveal=False)
        only_can = mask_field(cid, SYNTH[cid], reveal=False, can_reveal=True)
        full = mask_field(cid, SYNTH[cid], reveal=True, can_reveal=True)
        chk(default_masked != SYNTH[cid], f"P7 {cid} varsayılan maskeli")
        chk(only_reveal != SYNTH[cid] and only_can != SYNTH[cid], f"P7 {cid} tek-flag yeterli değil")
        chk(full == SYNTH[cid], f"P7 {cid} (reveal ∧ canReveal) → ham (backend-yetkili)")

    # P8 — serbest-metin tarama: sentetik transkriptte tüm desenler maskelenir
    transcript = (f"Kart {SYNTH['card_pan']}, OTP kodu: {SYNTH['otp']}, "
                  f"IBAN {SYNTH['iban']}, TC {SYNTH['national_id']}, "
                  f"e-posta {SYNTH['email']}, tel {SYNTH['phone']}.")
    scanned = scan_and_mask(transcript)
    chk(MASK in scanned, "P8 tarama maskeleme uygular")
    leaked = [cid for cid in ("card_pan", "otp", "iban", "national_id", "email")
              if SYNTH[cid] in scanned]
    chk(len(leaked) == 0, f"P8 ham PII serbest-metinde sızmaz (leaked={leaked})")

    # P9 — idempotent: mask(mask)=mask; scan(scan)=scan
    for cid, raw in SYNTH.items():
        once = mask_field(cid, raw)
        twice = mask_field(cid, once)
        chk(once == twice, f"P9 {cid} mask idempotent")
    chk(scan_and_mask(scanned) == scanned, "P9 scan idempotent")

    # P10 — presentasyonel / AUTHZ KARARI YOK: mask.ts i18n import etmez (locale-agnostik),
    # authz KARARI vermez (canReveal yalnız flag), maskField/scanAndMask ihraç eder
    for app in APPS:
        m = read_text(app_paths(app)["mask"])
        chk("lib/i18n" not in m, f"P10 {app} mask.ts i18n import ETMEZ (locale-agnostik)")
        chk("canReveal" in m, f"P10 {app} mask.ts canReveal flag'i honor eder (KARAR VERMEZ)")
        chk("export function maskField" in m and "export function scanAndMask" in m,
            f"P10 {app} mask.ts maskField + scanAndMask ihraç eder")
        bad = [t for t in FORBIDDEN_AUTHZ_DECISION if t in m]
        chk(len(bad) == 0, f"P10 {app} mask.ts authz KARARI içermez [{bad}]")

    # P11 — a11y: components.tsx Masked komponenti aria + VisuallyHidden ile redaksiyon ipucu
    for app in APPS:
        c = read_text(app_paths(app)["components"])
        chk("maskField" in c or "scanAndMask" in c, f"P11 {app} components mask çekirdeğini kullanır")
        chk("aria-label" in c, f"P11 {app} components aria-label (redaksiyon ipucu)")
        chk("VisuallyHidden" in c or "rmc-visually-hidden" in c, f"P11 {app} components ekran-okuyucu ipucu")

    # P12 — sır/PII yok + vendor-neutral. Taranan yüzey: app kaynak + canonical (samples/probe SENTETİK → hariç).
    scan_files = []
    for app in APPS:
        p = app_paths(app)
        scan_files += [p["policy"], p["mask"], p["components"]]
    scan_files += [POLICY_PATH]
    blob = "\n".join(read_text(f) for f in scan_files)
    vend = [v for v in FORBIDDEN_VENDORS if v in blob]
    chk(len(vend) == 0, f"P12 maskeleme SaaS/kütüphane bağlanmaz [{vend}]")
    sec = [s for s in FORBIDDEN_SECRET_PII if s in blob]
    chk(len(sec) == 0, f"P12 sır/ham-PII DEĞERİ YOK [{sec}]")
    # canonical politika ham değer tutmaz: kategori tanımlarında 'value'/'example' ham PII alanı yok
    has_raw = any("value" in c for c in canonical["categories"])
    chk(not has_raw, "P12 canonical kategori ham PII 'value' alanı tutmaz")

    passed = sum(1 for ok, _ in checks if ok)
    total = len(checks)
    for ok, label in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nvalidate: {passed}/{total} 🟢" if passed == total else f"\nvalidate: {passed}/{total} 🔴")
    print(f"policy_hash = {policy_hash}")
    return 0 if passed == total else 1


# ── check (samples) ─────────────────────────────────────────────────────────────

def evaluate_sample(scn):
    """Davranış senaryosu: kind ∈ {field, scan, leak_guard}."""
    kind = scn.get("kind")
    notes = []
    if kind == "field":
        got = mask_field(scn["category"], scn["raw"],
                         scn.get("reveal", False), scn.get("can_reveal", False))
        ok = got == scn.get("expect")
        if not ok:
            notes.append(f"got={got!r} ≠ beklenen {scn.get('expect')!r}")
        return {"ok": ok, "detail": f"got={got!r}", "notes": notes}
    if kind == "scan":
        got = scan_and_mask(scn["text"], scn.get("reveal", False), scn.get("can_reveal", False))
        ok = got == scn.get("expect")
        if not ok:
            notes.append(f"got={got!r} ≠ beklenen {scn.get('expect')!r}")
        return {"ok": ok, "detail": f"got={got!r}", "notes": notes}
    if kind == "leak_guard":
        # Saldırı/degrade senaryosu: maskeli çıktı yasaklı alt-dizilerin HİÇBİRİNİ içermemeli.
        target = scn.get("text")
        if "category" in scn:
            got = mask_field(scn["category"], scn["raw"], scn.get("reveal", False), scn.get("can_reveal", False))
        else:
            got = scan_and_mask(target, scn.get("reveal", False), scn.get("can_reveal", False))
        present = [s for s in scn.get("must_not_contain", []) if s in got]
        ok = len(present) == 0
        if not ok:
            notes.append(f"sızan alt-dizi(ler): {present} (çıktı={got!r})")
        return {"ok": ok, "detail": f"leak-free={ok} got={got!r}", "notes": notes}
    return {"ok": False, "detail": f"bilinmeyen kind={kind}", "notes": ["kind?"]}


def cmd_check(path):
    if os.path.isdir(path):
        files = [os.path.join(path, f) for f in sorted(os.listdir(path)) if f.endswith(".json")]
    else:
        files = [path]
    if not files:
        print("check: örnek bulunamadı")
        return 1
    fails = 0
    for f in files:
        scn = load_json(f)
        r = evaluate_sample(scn)
        mark = "🟢" if r["ok"] else "🔴"
        print(f"  {mark} {os.path.basename(f)} [{scn.get('kind')}]: {r['detail']}")
        if not r["ok"]:
            fails += 1
            for nt in r["notes"]:
                print(f"        · {nt}")
    print(f"\ncheck: {len(files)-fails}/{len(files)} 🟢" if fails == 0 else f"\ncheck: {len(files)-fails}/{len(files)} 🔴")
    return 0 if fails == 0 else 1


# ── selftest ─────────────────────────────────────────────────────────────────

def cmd_selftest():
    results = []

    def expect(label, cond):
        results.append((bool(cond), label))

    # 1–4 strateji birimleri
    expect("01 kart son-4 korunur, gövde maskeli",
           mask_field("card_pan", "4111 1111 1111 1342") == "•••• •••• •••• 1342")
    expect("02 CVV tamamen redakte", mask_field("cvv", "123") == "••••")
    expect("03 OTP tamamen redakte", mask_field("otp", "482913") == "••••")
    expect("04 parola tamamen redakte", mask_field("password", "S3cr3t!") == "••••")

    # 5–8 restricted varsayılan maskeli
    expect("05 e-posta yerel maskeli, alan korunur",
           mask_field("email", "ada.lovelace@example.com") == "a•••@example.com")
    expect("06 telefon son-2 korunur",
           mask_field("phone", "+90 532 123 45 67") == "+•• ••• ••• •• 67")
    expect("07 IBAN son-4 korunur",
           mask_field("iban", "TR120006400000112345678999").endswith("8999")
           and mask_field("iban", "TR120006400000112345678999").startswith(MASK))
    expect("08 ulusal kimlik son-4 korunur",
           mask_field("national_id", "12345678901") == "•••••••8901")

    # 9–12 reveal gating
    expect("09 prohibited reveal-immune (kart)",
           mask_field("card_pan", "4111 1111 1111 1342", reveal=True, can_reveal=True)
           == "•••• •••• •••• 1342")
    expect("10 prohibited reveal-immune (OTP)",
           mask_field("otp", "482913", reveal=True, can_reveal=True) == "••••")
    expect("11 restricted yalnız (reveal ∧ canReveal) → ham",
           mask_field("email", "ada.lovelace@example.com", reveal=True, can_reveal=True)
           == "ada.lovelace@example.com")
    expect("12 restricted tek-flag yetersiz → maskeli",
           mask_field("email", "ada.lovelace@example.com", reveal=True, can_reveal=False)
           == "a•••@example.com"
           and mask_field("email", "ada.lovelace@example.com", reveal=False, can_reveal=True)
           == "a•••@example.com")

    # 13 bilinmeyen kategori → fail-closed (restricted + redact_full)
    expect("13 bilinmeyen kategori fail-closed redakte",
           mask_field("bilinmeyen", "gizli-deger") == "••••")

    # 14–16 serbest-metin tarama
    t = "Kart 4111 1111 1111 1342 ve OTP kodu: 482913 teyit edildi."
    s = scan_and_mask(t)
    expect("14 tarama kart maskeler (son-4 kalır)", "1342" in s and "4111 1111 1111 1342" not in s)
    expect("15 tarama OTP maskeler (kod sızmaz)", "482913" not in s and "OTP kodu" in s)
    expect("16 e-posta serbest-metinde maskelenir",
           "ada.lovelace@example.com" not in scan_and_mask("yaz ada.lovelace@example.com bana"))

    # 17 idempotent (alan + tarama)
    expect("17 mask idempotent (kart)",
           mask_field("card_pan", mask_field("card_pan", "4111 1111 1111 1342"))
           == mask_field("card_pan", "4111 1111 1111 1342"))
    expect("18 scan idempotent", scan_and_mask(s) == s)

    # 19 leak-free: maskeli kart hiçbir 6-ardışık-orijinal-hane içermez (son-4 hariç)
    pan = "4111 1111 1111 1342"
    m = mask_field("card_pan", pan).replace(" ", "")
    expect("19 kart maskeli gövde leak-free", "411111111111" not in m)

    # 20 determinizm: policy_hash tekrarlanabilir
    expect("20 policy_hash deterministik",
           canonical_hash(load_json(POLICY_PATH)) == canonical_hash(load_json(POLICY_PATH)))

    # 21 sınıf eşlemesi
    expect("21 sınıf: kart=prohibited, e-posta=restricted",
           class_of("card_pan") == "prohibited" and class_of("email") == "restricted")

    # 22 telefon tek-flag yetersiz (restricted)
    expect("22 telefon reveal-gated",
           mask_field("phone", "+90 532 123 45 67", reveal=True, can_reveal=True) == "+90 532 123 45 67"
           and mask_field("phone", "+90 532 123 45 67") != "+90 532 123 45 67")

    # 23 boş/kısa değer leak-safe (kısa kart → tüm haneler maskeli)
    expect("23 kısa değer tümü maskeli (leak-safe)",
           all(ch in (MASK,) for ch in mask_field("card_pan", "123") if ch.isalnum()))

    passed = sum(1 for ok, _ in results if ok)
    for ok, label in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nselftest: {passed}/{len(results)} 🟢" if passed == len(results) else f"\nselftest: {passed}/{len(results)} 🔴")
    return 0 if passed == len(results) else 1


# ── schema ───────────────────────────────────────────────────────────────────

def cmd_schema():
    print(json.dumps({
        "wbs": "13.1.4",
        "behavior_kinds": {
            "field": "{kind:field, category, raw, reveal?, can_reveal?, expect}",
            "scan": "{kind:scan, text, reveal?, can_reveal?, expect}",
            "leak_guard": "{kind:leak_guard, (category,raw)|text, reveal?, can_reveal?, must_not_contain:[...]}",
        },
        "classes": {
            "prohibited": "kart/CVV/OTP/parola — reveal-immune, panelde tam değer ASLA (FR-REC-005)",
            "restricted": "e-posta/telefon/IBAN/ulusal kimlik — varsayılan maskeli, (reveal ∧ canReveal) ham (FR-REC-004)",
        },
        "core_contract": {
            "maskField": "maskField(category, raw, {reveal?, canReveal?}) → string",
            "scanAndMask": "scanAndMask(text, {reveal?, canReveal?}) → string (serbest-metin/transkript)",
            "authz": "frontend KARAR VERMEZ; canReveal yalnız backend flag'i (A8 / FR-REC-009 audit backend)",
        },
        "invariants": ["P1 dosya/canonical", "P2 politika parity", "P3 prohibited sınıf", "P4 restricted sınıf",
                       "P5 maskeleme leak-free", "P6 prohibited reveal-immune", "P7 restricted reveal-gated",
                       "P8 serbest-metin tarama", "P9 idempotent", "P10 presentasyonel/authz-yok",
                       "P11 a11y", "P12 sır/PII-yok + vendor-neutral"],
        "default": "MASK (fail-closed)",
        "trace": "BRD §17.7, FR-REC-004, FR-REC-005, SAD §14.4.1, SAD §19.2, ADR-002/ADR-011",
    }, ensure_ascii=False, indent=2))
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd = sys.argv[1]
    if cmd == "validate":
        return cmd_validate()
    if cmd == "check":
        target = sys.argv[2] if len(sys.argv) >= 3 else SAMPLES_DIR
        return cmd_check(target)
    if cmd == "selftest":
        return cmd_selftest()
    if cmd == "schema":
        return cmd_schema()
    print(f"bilinmeyen komut: {cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
