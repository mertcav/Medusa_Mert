#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 13.1.3 — Tasarım sistemi / komponent kütüphanesi + i18n (TR/EN) referans probe.

13.1 "Ortak frontend altyapısı" alt-bloğunun ÜÇÜNCÜ modülü; F1-Must. 13.1.1 iki ayrı app + route group
İSKELETİNİ, 13.1.2 çalışma-anı middleware KAPISINI kurdu; bu modül her iki app'e ORTAK bir tasarım sistemi
(design token + erişilebilir komponent kütüphanesi) + i18n (TR/EN) katmanı ekler ve şunları DOĞRULAR:

    TOKEN PARITY → i18n KATALOG PARITY (TR↔EN) → WCAG KONTRAST → A11Y → LOCALE-AGNOSTİK KOMPONENT →
    HTML lang/dir → LOCALE MÜZAKERE SÖZLEŞMESİ → globals↔token TUTARLILIK → SIR/PII YOK

ÇEKİRDEK İLKELER:
  - TEK kaynak doğruluk: design-system/config/design-tokens.json + design-system/i18n/{tr,en}.json.
    Her app (platform-app + tenant-app) bunların BİREBİR kopyasını vendor eder; probe canonical-hash ile
    eşitliği zorlar (drift = FAIL). ADR-011 blast-radius: çekirdek runtime cross-app import YOK (A7) —
    tasarım sistemi presentasyonel/güvenlik-dışı; senkron probe ile garanti edilir.
  - Komponentler PRESENTASYONEL + locale-AGNOSTİK (i18n import ETMEZ; metin prop ile gelir) → hardcoded
    TR/EN cümle YOK. Yerelleştirme yalnız çağrı yerinde t() ile (layout'lar t() kullanır — dead-code değil).
  - İŞ MANTIĞI/AUTHZ YOK (SAD §14.4.1 A8): UI yalnız görsel kapı; rol→permission kararı YOK (12.2.x backend).
  - WCAG 2.1: kontrast oranları DETERMİNİSTİK hesaplanır (sRGB→lineer→bağıl parlaklık), metin ≥4.5 /
    UI ≥3.0 kapılı; focus-visible + skip-link + visually-hidden + prefers-reduced-motion.
  - Vendor-neutral (ADR-002): i18n SaaS/kütüphane bağlanmaz (Intl stdlib). Sır/PII/credential üretilmez.

Saf çekirdek (lib/i18n/index.ts: negotiateLocale + t) bu probe'ta Python ile BİREBİR aynalanır
(negotiate_locale + translate) — aynı semantik, davranışsal kapı + samples + selftest.

Kullanım:
  design_system_probe.py validate        Statik canonical + ON-DISK app vendored kopya + kontrast + a11y kapısı → çıkış kodu
  design_system_probe.py check <sample>   Davranış: locale müzakere / çeviri+interpolasyon / kontrast / parity senaryoları
  design_system_probe.py selftest         Gömülü davranış kontrolleri → çıkış kodu
  design_system_probe.py schema           Karar/sözleşme özetini yazdır

Determinizm: token_hash/catalog_hash sha256 (kanonik JSON, sort_keys); Date.now/rastgelelik YOK. Stdlib-only.
Sır/credential ve ham içerik (PII) üretilmez/yazılmaz.
"""
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
TOKENS_PATH = os.path.join(HERE, "config", "design-tokens.json")
I18N_DIR = os.path.join(HERE, "i18n")
SPEC_PATH = os.path.join(HERE, "design-system-spec.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

APPS = ("frontend/platform-app", "frontend/tenant-app")
PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


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


# ── SAF ÇEKİRDEK AYNASI (lib/i18n/index.ts) ─────────────────────────────────────

def negotiate_locale(query=None, cookie=None, accept_language=None,
                     supported=("tr", "en"), default="tr"):
    """negotiateLocale TS ile birebir: ?lang query > çerez > Accept-Language > default."""
    def is_loc(x):
        return x in supported
    if is_loc(query):
        return query
    if is_loc(cookie):
        return cookie
    al = (accept_language or "").lower()
    for part in al.split(","):
        tag = part.split(";")[0].strip()[:2]
        if is_loc(tag):
            return tag
    return default


def resolve_path(catalog, key):
    cur = catalog
    for seg in key.split("."):
        if isinstance(cur, dict) and seg in cur:
            cur = cur[seg]
        else:
            return None
    return cur if isinstance(cur, str) else None


def translate(catalog, key, params=None):
    """t() TS ile birebir: dotted path + {placeholder} interpolasyon; eksik anahtar → anahtarın kendisi."""
    raw = resolve_path(catalog, key)
    if raw is None:
        return key
    if not params:
        return raw
    def repl(m):
        name = m.group(1)
        return str(params[name]) if name in params else m.group(0)
    return PLACEHOLDER_RE.sub(repl, raw)


# ── WCAG 2.1 KONTRAST (deterministik) ───────────────────────────────────────────

def _channel_lin(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def rel_luminance(hex_color):
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return 0.2126 * _channel_lin(r) + 0.7152 * _channel_lin(g) + 0.0722 * _channel_lin(b)


def contrast_ratio(fg, bg):
    l1, l2 = rel_luminance(fg), rel_luminance(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


# ── i18n katalog analiz ──────────────────────────────────────────────────────────

def leaf_keys(catalog, prefix=""):
    """Tüm string yaprak anahtarlarını dotted-path olarak döndürür ($ ile başlayan meta hariç)."""
    out = {}
    for k, v in catalog.items():
        if k.startswith("$"):
            continue
        path = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(leaf_keys(v, path))
        elif isinstance(v, str):
            out[path] = v
    return out


def catalog_violations(tr_cat, en_cat):
    """TR↔EN parity ihlalleri: eksik/fazla anahtar, placeholder uyuşmazlığı, boş değer."""
    tr_leaves = leaf_keys(tr_cat)
    en_leaves = leaf_keys(en_cat)
    viol = []
    missing_in_en = sorted(set(tr_leaves) - set(en_leaves))
    missing_in_tr = sorted(set(en_leaves) - set(tr_leaves))
    for k in missing_in_en:
        viol.append(("missing_key", f"{k} TR'de var EN'de yok"))
    for k in missing_in_tr:
        viol.append(("missing_key", f"{k} EN'de var TR'de yok"))
    for k in sorted(set(tr_leaves) & set(en_leaves)):
        if not tr_leaves[k].strip():
            viol.append(("empty_value", f"{k} TR boş"))
        if not en_leaves[k].strip():
            viol.append(("empty_value", f"{k} EN boş"))
        ptr = set(PLACEHOLDER_RE.findall(tr_leaves[k]))
        pen = set(PLACEHOLDER_RE.findall(en_leaves[k]))
        if ptr != pen:
            viol.append(("placeholder_mismatch", f"{k} {sorted(ptr)} ≠ {sorted(pen)}"))
    return viol


# ── validate (ON-DISK) ───────────────────────────────────────────────────────────

def app_paths(app_dir):
    base = os.path.join(REPO, app_dir)
    return {
        "tokens": os.path.join(base, "lib", "ui", "design-tokens.json"),
        "components": os.path.join(base, "lib", "ui", "components.tsx"),
        "tokens_ts": os.path.join(base, "lib", "ui", "tokens.ts"),
        "i18n_index": os.path.join(base, "lib", "i18n", "index.ts"),
        "i18n_server": os.path.join(base, "lib", "i18n", "server.ts"),
        "tr": os.path.join(base, "lib", "i18n", "tr.json"),
        "en": os.path.join(base, "lib", "i18n", "en.json"),
        "globals": os.path.join(base, "app", "globals.css"),
        "root_layout": os.path.join(base, "app", "layout.tsx"),
    }


GROUP_LAYOUTS = [
    "frontend/platform-app/app/(platform)/layout.tsx",
    "frontend/tenant-app/app/(tenant-admin)/layout.tsx",
    "frontend/tenant-app/app/(workspace)/layout.tsx",
]

# Vendor-neutral: belirli i18n SaaS/kütüphane bağlanmaz (Intl stdlib). (D12)
FORBIDDEN_I18N_VENDORS = ["i18next", "react-intl", "formatjs", "next-intl", "lingui", "polyglot"]
# Sır/PII token'ları (D12)
FORBIDDEN_SECRET_PII = ["BEGIN PRIVATE KEY", "password=", "secret=", "eyJhbGci",
                        "transcript_value", "card_pan", "cvv_value"]


def cmd_validate():
    canonical_tokens = load_json(TOKENS_PATH)
    canonical_tr = load_json(os.path.join(I18N_DIR, "tr.json"))
    canonical_en = load_json(os.path.join(I18N_DIR, "en.json"))
    token_hash = canonical_hash(canonical_tokens)
    tr_hash = canonical_hash(canonical_tr)
    en_hash = canonical_hash(canonical_en)
    checks = []

    def chk(cond, label):
        checks.append((bool(cond), label))

    # D1 — canonical varlığı + frozen + her app vendored kopya mevcut
    chk(canonical_tokens.get("frozen") is True, "D1 canonical tokens frozen")
    chk(canonical_tokens.get("wbs") == "13.1.3", "D1 canonical tokens.wbs=13.1.3")
    spec = load_json(SPEC_PATH)
    chk(spec.get("wbs") == "13.1.3", "D1 spec.wbs=13.1.3")
    for app in APPS:
        p = app_paths(app)
        for name in ("tokens", "tr", "en", "components", "tokens_ts", "i18n_index", "i18n_server", "globals"):
            chk(os.path.isfile(p[name]), f"D1 {app}/{name} mevcut")

    # D2 — token parity (app vendored == canonical hash)
    for app in APPS:
        ah = canonical_hash(load_json(app_paths(app)["tokens"]))
        chk(ah == token_hash, f"D2 {app} design-tokens.json canonical-hash eşit")

    # D3 — i18n katalog parity (app vendored == canonical hash, tr+en)
    for app in APPS:
        p = app_paths(app)
        chk(canonical_hash(load_json(p["tr"])) == tr_hash, f"D3 {app} tr.json canonical-hash eşit")
        chk(canonical_hash(load_json(p["en"])) == en_hash, f"D3 {app} en.json canonical-hash eşit")

    # D4/D5 — TR↔EN key-set + placeholder parity + boş değer yok (canonical + her app)
    viol_can = catalog_violations(canonical_tr, canonical_en)
    chk(len(viol_can) == 0, f"D4/D5 canonical TR↔EN parity (ihlal={len(viol_can)})")
    if viol_can:
        for kind, msg in viol_can[:8]:
            chk(False, f"     · {kind}: {msg}")
    for app in APPS:
        p = app_paths(app)
        v = catalog_violations(load_json(p["tr"]), load_json(p["en"]))
        chk(len(v) == 0, f"D4/D5 {app} TR↔EN parity (ihlal={len(v)})")

    # D6 — WCAG kontrast: her contrast_pair min eşiğini karşılar
    pairs = canonical_tokens["contrast_pairs"]
    fails = []
    for pr in pairs:
        ratio = contrast_ratio(pr["fg"], pr["bg"])
        if ratio + 1e-9 < pr["min"]:
            fails.append((pr["id"], round(ratio, 2), pr["min"]))
    chk(len(fails) == 0, f"D6 kontrast {len(pairs)} çift WCAG geçer (eler={fails})")
    chk(len(pairs) >= 12, f"D6 ≥12 kontrast çifti tanımlı ({len(pairs)})")

    # D7 — a11y temelleri (globals.css + components.tsx)
    for app in APPS:
        g = read_text(app_paths(app)["globals"])
        chk(":focus-visible" in g, f"D7 {app} globals :focus-visible (WCAG 2.4.7)")
        chk(".rmc-visually-hidden" in g, f"D7 {app} globals .rmc-visually-hidden")
        chk(".rmc-skip-link" in g, f"D7 {app} globals .rmc-skip-link")
        chk("prefers-reduced-motion" in g, f"D7 {app} globals prefers-reduced-motion")
        c = read_text(app_paths(app)["components"])
        chk("SkipLink" in c and "VisuallyHidden" in c, f"D7 {app} SkipLink + VisuallyHidden komponenti")
        chk('role="status"' in c or "role={role}" in c, f"D7 {app} status/alert role")
        chk("aria-label" in c, f"D7 {app} aria-label desteği (etkileşimli AD)")

    # D8 — komponentler locale-AGNOSTİK (i18n import YOK) + layout'lar t() KULLANIR
    for app in APPS:
        c = read_text(app_paths(app)["components"])
        chk("lib/i18n" not in c and "from \"./i18n" not in c,
            f"D8 {app} components i18n import ETMEZ (locale-agnostik)")
    for ly in GROUP_LAYOUTS:
        txt = read_text(os.path.join(REPO, ly))
        chk("t(cat," in txt and "@/lib/i18n" in txt, f"D8 layout {os.path.basename(os.path.dirname(ly))} t() kullanır")
    for app in APPS:
        rl = read_text(app_paths(app)["root_layout"])
        chk("t(cat," in rl, f"D8 {app} root layout t() kullanır (dead-code değil)")

    # D9 — html lang/dir wired + globals import
    for app in APPS:
        rl = read_text(app_paths(app)["root_layout"])
        chk("lang={locale}" in rl and "dir={dir(locale)}" in rl, f"D9 {app} <html lang/dir> müzakereyle")
        chk('import "./globals.css"' in rl, f"D9 {app} globals.css import")
        chk("SkipLink" in rl, f"D9 {app} SkipLink (a11y) bağlı")

    # D10 — locale müzakere sözleşmesi (index.ts)
    for app in APPS:
        idx = read_text(app_paths(app)["i18n_index"])
        chk("negotiateLocale" in idx, f"D10 {app} negotiateLocale")
        chk('DEFAULT_LOCALE: Locale = "tr"' in idx, f"D10 {app} DEFAULT_LOCALE=tr")
        chk('["tr", "en"]' in idx, f"D10 {app} SUPPORTED tr+en")
        chk("formatDate" in idx and "formatNumber" in idx and "formatCurrency" in idx,
            f"D10 {app} Intl format (tarih/sayı/para — FR-TTS-004 panel karşılığı)")
        chk('"ltr" | "rtl"' in idx, f"D10 {app} dir(ltr/rtl) — RTL-hazır")

    # D11 — globals.css ↔ token tutarlılık (brand primary + temel değişkenler)
    primary = canonical_tokens["color"]["brand_primary"]
    for app in APPS:
        g = read_text(app_paths(app)["globals"])
        chk(primary in g, f"D11 {app} globals brand primary {primary} ile hizalı")
        chk("--rmc-brand-primary:" in g and "--rmc-space-4:" in g and "--rmc-radius-md:" in g,
            f"D11 {app} globals temel token değişkenleri yayımlar")

    # D12 — sır/PII yok + vendor-neutral (i18n SaaS yok)
    scan_files = []
    for app in APPS:
        p = app_paths(app)
        scan_files += [p["components"], p["tokens_ts"], p["i18n_index"], p["i18n_server"],
                       p["tr"], p["en"], p["tokens"], p["globals"]]
    # NOT: spec/probe'un KENDİSİ taranmaz — D12 yasaklı vendor/PII adlarını forbids listesinde MEŞRU
    # olarak ADLANDIRIR (yasaklamak için); taranan yüzey app KAYNAK + canonical token/katalog içeriğidir.
    scan_files += [TOKENS_PATH, os.path.join(I18N_DIR, "tr.json"), os.path.join(I18N_DIR, "en.json")]
    blob = "\n".join(read_text(f) for f in scan_files)
    vend = [v for v in FORBIDDEN_I18N_VENDORS if v in blob]
    chk(len(vend) == 0, f"D12 i18n SaaS/kütüphane bağlanmaz [{vend}]")
    sec = [s for s in FORBIDDEN_SECRET_PII if s in blob]
    chk(len(sec) == 0, f"D12 sır/PII token YOK [{sec}]")

    passed = sum(1 for ok, _ in checks if ok)
    total = len(checks)
    for ok, label in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nvalidate: {passed}/{total} 🟢" if passed == total else f"\nvalidate: {passed}/{total} 🔴")
    print(f"token_hash = {token_hash}")
    print(f"tr_hash    = {tr_hash}")
    print(f"en_hash    = {en_hash}")
    return 0 if passed == total else 1


# ── check (samples) ─────────────────────────────────────────────────────────────

def evaluate_sample(scn):
    """Davranış senaryosu değerlendirir: kind ∈ {locale, translate, contrast, parity}."""
    kind = scn.get("kind")
    notes = []
    if kind == "locale":
        got = negotiate_locale(scn.get("query"), scn.get("cookie"), scn.get("accept_language"))
        ok = got == scn.get("expect_locale")
        if not ok:
            notes.append(f"locale={got} ≠ beklenen {scn.get('expect_locale')}")
        return {"ok": ok, "detail": f"locale={got}", "notes": notes}
    if kind == "translate":
        loc = scn["locale"]
        cat = load_json(os.path.join(I18N_DIR, f"{loc}.json"))
        got = translate(cat, scn["key"], scn.get("params"))
        ok = got == scn.get("expect_text")
        if not ok:
            notes.append(f"text={got!r} ≠ beklenen {scn.get('expect_text')!r}")
        return {"ok": ok, "detail": f"text={got!r}", "notes": notes}
    if kind == "contrast":
        ratio = contrast_ratio(scn["fg"], scn["bg"])
        passes = ratio + 1e-9 >= scn["min"]
        ok = passes == scn.get("expect_pass")
        if not ok:
            notes.append(f"ratio={round(ratio,2)} passes={passes} ≠ beklenen {scn.get('expect_pass')}")
        return {"ok": ok, "detail": f"ratio={round(ratio,2)} min={scn['min']} passes={passes}", "notes": notes}
    if kind == "parity":
        viol = catalog_violations(scn["tr"], scn["en"])
        kinds = sorted({k for k, _ in viol})
        ok_flag = (len(viol) == 0)
        ok = ok_flag == scn.get("expect_ok")
        if scn.get("expect_violation") and scn.get("expect_violation") not in kinds:
            ok = False
            notes.append(f"beklenen ihlal {scn.get('expect_violation')} yok; bulunan={kinds}")
        if not ok and not notes:
            notes.append(f"ok={ok_flag} ≠ beklenen {scn.get('expect_ok')}; ihlal={kinds}")
        return {"ok": ok, "detail": f"violations={kinds}", "notes": notes}
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

    tr = load_json(os.path.join(I18N_DIR, "tr.json"))
    en = load_json(os.path.join(I18N_DIR, "en.json"))

    # 1–4 locale müzakere precedence
    expect("01 query önceliği (?lang=en, çerez tr) → en",
           negotiate_locale(query="en", cookie="tr", accept_language="tr") == "en")
    expect("02 çerez (query yok) → tr", negotiate_locale(query=None, cookie="tr", accept_language="en-GB") == "tr")
    expect("03 Accept-Language (query/çerez yok) → en",
           negotiate_locale(query=None, cookie=None, accept_language="en-GB,en;q=0.9") == "en")
    expect("04 hiçbiri → default tr", negotiate_locale() == "tr")
    expect("05 desteklenmeyen query (fr) düşer → çerez en", negotiate_locale(query="fr", cookie="en") == "en")
    expect("06 desteklenmeyen tümü → default tr",
           negotiate_locale(query="de", cookie="es", accept_language="fr-FR") == "tr")

    # 7–10 çeviri + interpolasyon
    expect("07 TR düz anahtar", translate(tr, "common.save") == "Kaydet")
    expect("08 EN düz anahtar", translate(en, "common.save") == "Save")
    expect("09 TR interpolasyon", translate(tr, "common.greeting", {"name": "Ada"}) == "Merhaba, Ada")
    expect("10 EN interpolasyon çoklu", translate(en, "a11y.page_of", {"page": 2, "total": 5}) == "Page 2 of 5")
    expect("11 eksik anahtar → anahtarın kendisi", translate(tr, "yok.bir.anahtar") == "yok.bir.anahtar")
    expect("12 fazla param yok-sayılır", translate(tr, "common.save", {"x": "1"}) == "Kaydet")

    # 13 TR↔EN canonical parity temiz
    expect("13 canonical TR↔EN parity ihlalsiz", len(catalog_violations(tr, en)) == 0)

    # 14–17 kontrast (gerçek hesap)
    expect("14 siyah/beyaz ≈ 21:1", abs(contrast_ratio("#000000", "#FFFFFF") - 21.0) < 0.1)
    expect("15 beyaz/beyaz = 1:1", abs(contrast_ratio("#FFFFFF", "#FFFFFF") - 1.0) < 0.001)
    expect("16 RMC mavi üstüne beyaz ≥4.5", contrast_ratio("#FFFFFF", "#1F4E79") >= 4.5)
    expect("17 simetrik (fg/bg sırası önemsiz)",
           abs(contrast_ratio("#1A202C", "#FFFFFF") - contrast_ratio("#FFFFFF", "#1A202C")) < 1e-9)

    # 18 tüm tanımlı contrast_pair geçer (canonical)
    pairs = load_json(TOKENS_PATH)["contrast_pairs"]
    expect("18 tüm contrast_pair WCAG geçer",
           all(contrast_ratio(p["fg"], p["bg"]) + 1e-9 >= p["min"] for p in pairs))

    # 19 parity ihlal tespiti: eksik anahtar
    expect("19 eksik anahtar ihlali yakalanır",
           any(k == "missing_key" for k, _ in catalog_violations({"a": "x", "b": "y"}, {"a": "x"})))
    # 20 placeholder uyuşmazlığı
    expect("20 placeholder uyuşmazlığı yakalanır",
           any(k == "placeholder_mismatch" for k, _ in
               catalog_violations({"g": "Merhaba {name}"}, {"g": "Hello {ad}"})))
    # 21 boş değer
    expect("21 boş değer ihlali yakalanır",
           any(k == "empty_value" for k, _ in catalog_violations({"g": ""}, {"g": "x"})))

    # 22 determinizm: hash tekrarlanabilir
    expect("22 token_hash deterministik",
           canonical_hash(load_json(TOKENS_PATH)) == canonical_hash(load_json(TOKENS_PATH)))

    # 23 leaf_keys $ meta atlar
    expect("23 leaf_keys $meta atlar", "$comment" not in leaf_keys(tr) and "common.save" in leaf_keys(tr))

    passed = sum(1 for ok, _ in results if ok)
    for ok, label in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nselftest: {passed}/{len(results)} 🟢" if passed == len(results) else f"\nselftest: {passed}/{len(results)} 🔴")
    return 0 if passed == len(results) else 1


# ── schema ───────────────────────────────────────────────────────────────────

def cmd_schema():
    print(json.dumps({
        "wbs": "13.1.3",
        "behavior_kinds": {
            "locale": "{kind:locale, query?, cookie?, accept_language?, expect_locale}",
            "translate": "{kind:translate, locale, key, params?, expect_text}",
            "contrast": "{kind:contrast, fg, bg, min, expect_pass}",
            "parity": "{kind:parity, tr:{...}, en:{...}, expect_ok, expect_violation?}",
        },
        "invariants": ["D1 dosya/canonical", "D2 token parity", "D3 i18n parity", "D4 key-set parity",
                       "D5 placeholder+boş", "D6 WCAG kontrast", "D7 a11y", "D8 locale-agnostik komponent",
                       "D9 html lang/dir", "D10 müzakere sözleşmesi", "D11 globals↔token", "D12 sır/PII+vendor"],
        "default": "FAIL (fail-closed)",
        "trace": "SAD §14.4.1, FR-TEN-004, BRD §16 (TR/EN/residency), WCAG 2.1, ADR-002/ADR-011",
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
