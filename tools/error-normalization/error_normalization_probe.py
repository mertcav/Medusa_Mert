#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 7.1.5 — Hata normalizasyonu (müşteriye teknik detay yok) (SAD §11.1 adım [6] / FR-TOOL-008) referans probe.

    LLM tool call ──► [1] input schema ──► [2] authz ──► [3] policy gate ──► [4] idempotency
                  ──► [5] Integration GW: timeout+retry+circuit breaker (7.1.4)
                  ──► [6] output schema + ERROR NORMALIZATION  ◄── bu motor (error-normalization yarısı)
                  ──► [7] correlation_id audit

Tool Yürütme Hattının (SAD §11.1) SON sunum aşaması. 7.1.4'ün ürettiği yapısal fault_class'ı (ya da bir
adapter API §11.6 ErrorTaxonomy hatasını) alır ve İKİ DİSJONKT yüzeye böler:
  • MÜŞTERİ/arayan — güvenli, teknik-detaysız mesaj (voice: doğal konuşma; api: RFC 9457 Problem);
  • AUDIT/log — ham teknik detay (provider kodu, stack, endpoint, internal mesaj) — müşteriye GİTMEZ.

INVARIANT (SR-TOOL-008): 'Müşteriye dönen mesajda stack/teknik detay yok' (FR-TOOL-008).
  N1 sızıntı=0 · N2 toplam fault eşleme · N3 toplam yerelleştirme · N4 ham izolasyon · N5 RFC 9457 ·
  N6 correlation_id köprü · N7 enterpolasyon yok · N8 retriability tutarlı · N9 determinizm ·
  N10 iç-yapı sızıntısı yok (voice) · N11 sır/PII literal yok · N12 audit eksiksiz.

Kapsam dışı (bilinçli): timeout/retry/breaker → 7.1.4 (fault_class'ı TÜKETİR); output schema → 7.1.1;
authz → 7.1.2; idempotency → 7.1.3; correlation_id audit/trace + audit deposunda PII redaction → 7.1.6;
insan aktarımı orkestrasyonu → FR-HND (yalnız suggest_handoff ÖNERİR). Vendor-neutral (ADR-002).

Kullanım:
  error_normalization_probe.py validate            Statik spec/config/katalog/şema kapısı → çıkış kodu
  error_normalization_probe.py normalize <sample>  Deterministik normalizasyon — istek(ler) → kapı (N1–N12)
  error_normalization_probe.py selftest            Gömülü davranış kontrolleri → çıkış kodu
  error_normalization_probe.py schema              SPI/NormalizedError/kategori sözleşmesini yazdır

Determinizm: saf eşleme; Date.now/gerçek-rastgele YOK. Stdlib-only. Sır/gerçek PII üretilmez (FR-TST-008).
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "error-normalization-spec.json")
CONFIG_PATH = os.path.join(HERE, "config", "error-catalog.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

GATE_IDS = ["N1", "N2", "N3", "N4", "N5", "N6", "N7", "N8", "N9", "N10", "N11", "N12"]

# Retryable-sınıf fault'lar (7.1.4 retryable ∪ gateway-temporary ∪ API §11.6 geçici) — N8 tutarlılık kaynağı.
RETRYABLE_FAULTS = {
    "TIMEOUT", "UPSTREAM_5XX", "CONN_RESET", "CONN_REFUSED", "RATE_LIMITED", "DEADLINE_EXCEEDED",
    "CIRCUIT_OPEN", "RETRY_EXHAUSTED", "UNAVAILABLE", "QUOTA_EXCEEDED",
}

# ── Sızıntı taraması desenleri (N1) ─────────────────────────────────────────────
STACK_RE = re.compile(
    r"(?i)\b(?:traceback|stack ?trace|errno|segfault|nullpointer|panic:)\b"
    r"|\bat [\w.$]+\("                       # "at com.foo.Bar("
    r"|\.(?:py|go|java|js|ts|rb|php|cs|jar|so):\d+"   # File.py:42
)
EXCEPTION_RE = re.compile(r"\b\w+(?:Exception|Error)\b")          # ValueError, NullPointerException (glued)
SQL_RE = re.compile(r"\b(?:SELECT|INSERT|UPDATE|DELETE|DROP|WHERE|JOIN|SQLSTATE|FROM)\b\s+\S")  # büyük harf SQL
PATH_RE = re.compile(r"(?:/(?:usr|home|var|etc|opt|tmp|root|proc)/|[A-Za-z]:\\)"
                     r"|\.(?:py|go|java|js|ts|rb|php|cs|jar|so)\b")
URL_RE = re.compile(r"(?i)\b\w+://|\.(?:internal|svc|local|cluster)\b")
IP_RE = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
HEX_RE = re.compile(r"\b0x[0-9a-fA-F]+\b|\b[0-9a-fA-F]{12,}\b")
UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
CARD_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")
PHONE_RE = re.compile(r"(?<!\w)\+?\d[\d ()\-]{8,}\d(?!\w)")
DIGIT_RE = re.compile(r"\d")

SECRET_RE = re.compile(
    r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer|client[_-]?secret|access[_-]?token)\b"
    r"\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}"
)
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")

# Kart/OTP maskeleme (FR-REC-005 — audit'te de maskele)
OTP_RE = re.compile(r"(?i)\b(?:otp|one[- ]?time|kod|code|pin|cvv|cvc)\b[:\s]*\d{3,8}\b|\b\d{4,8}\b(?=\s*(?:otp|kod|code|pin))")


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _no_meta(d):
    """$ ile başlayan meta anahtarları ($comment vb.) eler."""
    return {k: v for k, v in d.items() if not k.startswith("$")}


def _is_placeholder(v):
    return isinstance(v, str) and PLACEHOLDER_RE.match(v) is not None


# ── Sızıntı tarayıcısı ──────────────────────────────────────────────────────────
def scan_leaks(text, vendor_names, internal_terms, voice=False):
    """Müşteri-görünür metni YASAK desenlere karşı tara (N1; voice ise N10 ek). hit listesi döner."""
    hits = []
    if text is None:
        return hits
    low = text.lower()
    for v in vendor_names:
        if re.search(r"\b" + re.escape(v.lower()) + r"\b", low):
            hits.append(("vendor_name", v))
    if STACK_RE.search(text):
        hits.append(("stack_trace", STACK_RE.search(text).group(0)))
    if EXCEPTION_RE.search(text):
        hits.append(("exception_class", EXCEPTION_RE.search(text).group(0)))
    if SQL_RE.search(text):
        hits.append(("sql_fragment", SQL_RE.search(text).group(0)))
    if PATH_RE.search(text):
        hits.append(("file_path", PATH_RE.search(text).group(0)))
    if URL_RE.search(text):
        hits.append(("internal_url_host", URL_RE.search(text).group(0)))
    if IP_RE.search(text):
        hits.append(("ip_address", IP_RE.search(text).group(0)))
    if UUID_RE.search(text):
        hits.append(("raw_code_hex_uuid", UUID_RE.search(text).group(0)))
    elif HEX_RE.search(text):
        hits.append(("raw_code_hex_uuid", HEX_RE.search(text).group(0)))
    if EMAIL_RE.search(text):
        hits.append(("pii_email", EMAIL_RE.search(text).group(0)))
    if CARD_RE.search(text):
        hits.append(("pii_card", CARD_RE.search(text).group(0)))
    if voice:
        # Voice ek (N10): rakam + iç-yapı terimleri açığa vurulmaz.
        if DIGIT_RE.search(text):
            hits.append(("digit", DIGIT_RE.search(text).group(0)))
        for t in internal_terms:
            if re.search(r"\b" + re.escape(t.lower()) + r"\b", low):
                hits.append(("internal_structure_term", t))
    return hits


def _mask_card_otp(text):
    """FR-REC-005: kart/OTP'yi audit ham metninde de maskele (defense-in-depth)."""
    if not text:
        return text
    text = CARD_RE.sub("[REDACTED-CARD]", text)
    text = OTP_RE.sub("[REDACTED-OTP]", text)
    return text


# ── Normalizasyon motoru (saf eşleme) ───────────────────────────────────────────
class NormalizationError(Exception):
    pass


def normalize(req, spec, catalog):
    """NormalizationRequest → NormalizedError (saf; N9 determinizm). spec=kaynak doğruluk, catalog=mesajlar."""
    fault = req.get("fault_class")
    corr = req.get("correlation_id")
    if not corr:
        raise NormalizationError("INVALID_REQUEST: correlation_id zorunlu")
    locale = req.get("locale") or catalog["default_locale"]
    channel = req.get("channel", "voice")

    cats = _no_meta(spec["customer_categories"])
    fault_map = _no_meta(spec["fault_map"])
    vendor_names = catalog["leak_scanner"]["vendor_names"]
    internal_terms = catalog["leak_scanner"]["internal_structure_terms"]

    # N2: toplam eşleme — bilinmeyen fault → UNKNOWN (asla ham passthrough)
    category = fault_map.get(fault, "UNKNOWN")
    cat = cats[category]

    # N3: yerelleştirme — eksik locale → default fallback
    msgs = catalog["messages"]
    loc = locale if locale in msgs else catalog["default_locale"]
    entry = msgs[loc][category]

    voice_msg = entry["voice"]
    title = entry["title"]
    detail = entry["detail"]

    # Tenant özel mesaj override (fail-safe): sızıntı taramasından GEÇMELİ; aksi reddet→katalog fallback
    override_rejected = False
    override = req.get("customer_message_override")
    failsafe = req.get("failsafe", True)
    if override is not None:
        is_voice_surface = (channel == "voice")
        ov_hits = scan_leaks(override, vendor_names, internal_terms, voice=is_voice_surface)
        if ov_hits and failsafe:
            override_rejected = True   # güvenli katalog mesajına düş
        else:
            voice_msg = override       # temiz override (veya failsafe kapalı → kasıtlı degrade testi)

    # N8: retriable_hint kategori-tutarlı (kategori meta) + fault retryable-sınıfı ile uyum
    retriable = bool(cat["retriable_hint"])

    customer = {
        "code": cat["customer_code"],
        "category": category,
        "message": voice_msg if channel == "voice" else title,
        "voice_message": voice_msg,
        "retriable_hint": retriable,
        "suggest_handoff": bool(cat["suggest_handoff"]) and bool(req.get("handoff_available", True)),
        "locale": loc,
        "override_rejected": override_rejected,
    }

    # N5: RFC 9457 Problem (api yüzeyi). type=base+slug (dokümantasyon URI — taranmaz); detail jenerik.
    slug = catalog["rfc9457_type_slugs"][category]
    api_problem = {
        "type": spec["rfc9457"]["type_base"] + slug,
        "title": title,
        "status": int(cat["http_status"]),
        "detail": detail,
        "code": cat["customer_code"],
        "correlation_id": corr,
    }

    # N4/N12: audit — ham teknik detay yalnız burada; kart/OTP maskeli (FR-REC-005); customer_safe=false
    audit = {
        "correlation_id": corr,
        "fault_class": fault,
        "category": category,
        "severity": cat["severity"],
        "provider_code": req.get("provider_code"),
        "internal_message": _mask_card_otp(req.get("internal_message")),
        "endpoint": req.get("endpoint"),
        "tenant_id": req.get("tenant_id"),
        "operation_class": req.get("operation_class"),
        "customer_safe": False,
    }

    # N1: müşteri-görünür metni tara (voice mesajı + RFC 9457 title/detail)
    scan = []
    scan += [("customer.voice_message", h) for h in scan_leaks(voice_msg, vendor_names, internal_terms, voice=True)]
    scan += [("api_problem.title", h) for h in scan_leaks(title, vendor_names, internal_terms, voice=False)]
    scan += [("api_problem.detail", h) for h in scan_leaks(detail, vendor_names, internal_terms, voice=False)]
    leak_scan = {
        "clean": len(scan) == 0,
        "scanned_fields": ["customer.voice_message", "api_problem.title", "api_problem.detail"],
        "hits": [{"field": f, "class": h[0], "match": h[1]} for f, h in scan],
    }

    return {
        "customer": customer,
        "api_problem": api_problem,
        "audit": audit,
        "leak_scan": leak_scan,
    }


# ── Kapı denetimi (N1–N12) ──────────────────────────────────────────────────────
def check_gates(req, out, spec):
    lines = []
    ok = True

    def gate(cond, gid, msg):
        nonlocal ok
        mark = "🟢" if cond else "🔴"
        lines.append("  %s %s — %s" % (mark, gid, msg))
        if not cond:
            ok = False

    cats = _no_meta(spec["customer_categories"])
    fault_map = _no_meta(spec["fault_map"])

    cust = out["customer"]
    ap = out["api_problem"]
    aud = out["audit"]
    ls = out["leak_scan"]

    # N1: müşteri-görünür sızıntı=0
    gate(ls["clean"], "N1", "müşteri-görünür metin sızıntısız (hits=%d)" % len(ls["hits"]))

    # N2: toplam eşleme — bilinmeyen → UNKNOWN
    expected_cat = fault_map.get(req.get("fault_class"), "UNKNOWN")
    gate(cust["category"] == expected_cat, "N2", "fault→category eşleme (%s→%s)" % (req.get("fault_class"), cust["category"]))

    # N3: mesaj boş değil
    gate(bool(cust["voice_message"]) and bool(ap["title"]) and bool(ap["detail"]), "N3", "yerelleştirilmiş mesaj boş değil (locale=%s)" % cust["locale"])

    # N4: ham detay müşteri/api yüzeyinde YOK
    raw_vals = [req.get("provider_code"), req.get("endpoint"), req.get("tenant_id")]
    surface = " ".join([str(cust["voice_message"]), str(ap["title"]), str(ap["detail"])])
    raw_leak = any(rv and str(rv) in surface for rv in raw_vals)
    # internal_message ham parçası yüzeyde mi (ilk anlamlı token)
    im = req.get("internal_message") or ""
    im_tok = next((t for t in re.findall(r"[A-Za-z0-9_]{6,}", im)), None)
    if im_tok and im_tok.lower() in surface.lower():
        raw_leak = True
    gate(not raw_leak, "N4", "ham detay (provider_code/endpoint/tenant_id/internal_message) yüzeyde yok")

    # N5: RFC 9457 uyumu
    rfc = spec["rfc9457"]
    n5 = (all(k in ap for k in rfc["required_fields"])
          and ap["status"] == cats[cust["category"]]["http_status"]
          and ap["type"].startswith(rfc["type_base"]))
    gate(n5, "N5", "RFC 9457 Problem (type/title/status=%s/code/correlation_id)" % ap["status"])

    # N6: correlation_id köprü (audit + api) + voice'ta gömülü değil
    n6 = (aud["correlation_id"] == req.get("correlation_id")
          and ap["correlation_id"] == req.get("correlation_id")
          and (req.get("correlation_id") or "") not in str(cust["voice_message"]))
    gate(n6, "N6", "correlation_id audit+api'de, voice metninde gömülü değil")

    # N7: enterpolasyon yok — voice mesajı katalogdaki sabit şablonlardan biri (override hariç/temiz)
    cat_voices = {m[cust["category"]]["voice"] for m in spec_catalog_messages().values()}
    n7 = cust["override_rejected"] or (cust["voice_message"] in cat_voices) or req.get("customer_message_override") is not None
    gate(n7, "N7", "müşteri mesajı statik katalog şablonu (enterpolasyon yok)")

    # N8: retriability tutarlı
    is_retryable_fault = req.get("fault_class") in RETRYABLE_FAULTS
    expect_retr = cust["category"] in ("TEMPORARY", "BUSY")
    n8 = (cust["retriable_hint"] == expect_retr) and (expect_retr == is_retryable_fault or cust["category"] == "UNKNOWN")
    gate(n8, "N8", "retriable_hint=%s fault retryable-sınıfı ile tutarlı" % cust["retriable_hint"])

    # N10: voice iç-yapı/rakam sızıntısı yok (N1 voice taraması zaten kapsıyor; ayrıca raporla)
    voice_hits = [h for h in ls["hits"] if h["field"] == "customer.voice_message" and h["class"] in ("digit", "internal_structure_term")]
    gate(len(voice_hits) == 0, "N10", "voice mesajı iç-yapı/rakam açığa vurmaz")

    # N12: audit eksiksiz + customer_safe=false
    n12 = (aud["customer_safe"] is False and aud["fault_class"] == req.get("fault_class")
           and aud["category"] == cust["category"] and aud["severity"] and aud["correlation_id"])
    gate(n12, "N12", "audit eksiksiz (fault+category+severity+corr, customer_safe=false)")

    return ok, lines


_CATALOG_CACHE = None


def spec_catalog_messages():
    global _CATALOG_CACHE
    if _CATALOG_CACHE is None:
        _CATALOG_CACHE = _load(CONFIG_PATH)["messages"]
    return _CATALOG_CACHE


# ── normalize komutu ────────────────────────────────────────────────────────────
def normalize_cmd(path):
    spec = _load(SPEC_PATH)
    catalog = _load(CONFIG_PATH)
    sample = _load(path)
    reqs = sample["requests"] if "requests" in sample else [sample]
    name = sample.get("name", os.path.basename(path))
    print("== normalize: %s ==" % name)
    all_ok = True
    for req in reqs:
        try:
            out = normalize(req, spec, catalog)
        except NormalizationError as e:
            print("  [%s] HATA: %s" % (req.get("correlation_id", "?"), e))
            all_ok = False
            continue
        c = out["customer"]
        print("  [%s] fault=%s → cat=%s code=%s retr=%s handoff=%s ovr_rej=%s status=%d clean=%s" % (
            req.get("correlation_id"), req.get("fault_class"), c["category"], c["code"],
            c["retriable_hint"], c["suggest_handoff"], c["override_rejected"],
            out["api_problem"]["status"], out["leak_scan"]["clean"]))
        print("      voice: %s" % c["voice_message"])
        if out["leak_scan"]["hits"]:
            for h in out["leak_scan"]["hits"]:
                print("      ⚠ sızıntı %s/%s: %r" % (h["field"], h["class"], h["match"]))
        ok, lines = check_gates(req, out, spec)
        for ln in lines:
            print(ln)
        all_ok = all_ok and ok
    print("KAPI: %s" % ("🟢 GEÇTI" if all_ok else "🔴 ELENDI"))
    return 0 if all_ok else 1


# ── validate (statik kapı) ──────────────────────────────────────────────────────
def validate():
    fails = []

    def expect(c, m):
        if not c:
            fails.append(m)

    spec = _load(SPEC_PATH)
    catalog = _load(CONFIG_PATH)

    expect(spec.get("wbs") == "7.1.5", "spec.wbs 7.1.5")
    expect("FR-TOOL-008" in spec["trace"]["fr"], "trace FR-TOOL-008")
    expect("SR-TOOL-008" in spec["trace"]["srs"], "trace SR-TOOL-008")
    expect([inv["id"] for inv in spec["invariants"]] == GATE_IDS, "invariants N1–N12 sırası")

    cats = _no_meta(spec["customer_categories"])
    fault_map = _no_meta(spec["fault_map"])
    msgs = catalog["messages"]
    locales = catalog["supported_locales"]
    vendor_names = catalog["leak_scanner"]["vendor_names"]
    internal_terms = catalog["leak_scanner"]["internal_structure_terms"]

    # N2 toplam eşleme: her bildirilen fault_class kategoriye eşli + her hedef kategori tanımlı
    declared = set(spec["fault_input_surfaces"]["gw_fault_taxonomy_7_1_4"]) | set(spec["fault_input_surfaces"]["api_error_taxonomy_11_6"])
    for f in declared:
        expect(f in fault_map, "fault_map kapsar: %s" % f)
    for f, c in fault_map.items():
        expect(c in cats, "fault_map hedef kategori geçerli: %s→%s" % (f, c))
    expect(set(fault_map.values()) <= set(cats.keys()), "tüm hedef kategoriler tanımlı")
    expect("UNKNOWN" in cats, "UNKNOWN güvenli fallback kategori var")

    # N3 toplam yerelleştirme: her (locale × category) için voice/title/detail dolu
    for loc in locales:
        expect(loc in msgs, "locale kataloğu var: %s" % loc)
        for cat in cats:
            e = msgs.get(loc, {}).get(cat)
            expect(e and e.get("voice") and e.get("title") and e.get("detail"),
                   "mesaj dolu: %s/%s" % (loc, cat))
    expect(catalog["default_locale"] in msgs, "default_locale kataloğu var")

    # rfc9457 slug her kategori için
    for cat in cats:
        expect(cat in catalog["rfc9457_type_slugs"], "rfc9457 slug: %s" % cat)
    for k in spec["rfc9457"]["required_fields"]:
        expect(k in ["type", "title", "status", "code", "correlation_id"], "rfc9457 required alan bilinen: %s" % k)

    # N1/N10 KRİTİK: katalogdaki HER müşteri-görünür mesaj sızıntı taramasından temiz geçer
    for loc in locales:
        for cat in cats:
            e = msgs[loc][cat]
            vh = scan_leaks(e["voice"], vendor_names, internal_terms, voice=True)
            expect(not vh, "voice temiz %s/%s: %s" % (loc, cat, vh[:1]))
            th = scan_leaks(e["title"], vendor_names, internal_terms, voice=False)
            expect(not th, "title temiz %s/%s: %s" % (loc, cat, th[:1]))
            dh = scan_leaks(e["detail"], vendor_names, internal_terms, voice=False)
            expect(not dh, "detail temiz %s/%s: %s" % (loc, cat, dh[:1]))

    # N11 sır/PII literal taraması (spec/config/samples)
    scan_paths = [SPEC_PATH, CONFIG_PATH] + [os.path.join(SAMPLES_DIR, f)
                                             for f in sorted(os.listdir(SAMPLES_DIR)) if f.endswith(".json")]
    for sp in scan_paths:
        with open(sp, "r", encoding="utf-8") as f:
            txt = f.read()
        for ln in txt.splitlines():
            s = ln.strip()
            if s.startswith("//") or s.startswith("#") or '"$comment"' in s:
                continue
            if SECRET_RE.search(ln):
                fails.append("sır sızıntısı: %s" % os.path.basename(sp))
                break
        for em in EMAIL_RE.findall(txt):
            if not em.endswith("example.com"):
                fails.append("e-posta PII: %s (%s)" % (os.path.basename(sp), em))

    # her sample kapısı: 'expect_fail' işaretliler 🔴, diğerleri 🟢
    for f in sorted(os.listdir(SAMPLES_DIR)):
        if not f.endswith(".json"):
            continue
        sample = _load(os.path.join(SAMPLES_DIR, f))
        reqs = sample["requests"] if "requests" in sample else [sample]
        sample_ok = True
        for req in reqs:
            try:
                out = normalize(req, spec, catalog)
                ok, _ = check_gates(req, out, spec)
            except NormalizationError:
                ok = False
            sample_ok = sample_ok and ok
        if sample.get("expect_fail"):
            expect(not sample_ok, "degraded sample BEKLENEN ELEME: %s" % f)
        else:
            expect(sample_ok, "sample kapısı: %s" % f)

    print("validate: %d kontrol başarısız" % len(fails))
    for m in fails:
        print("  ✗ %s" % m)
    return 0 if not fails else 1


# ── selftest (gömülü davranış) ──────────────────────────────────────────────────
def _req(**kw):
    base = {"fault_class": "TIMEOUT", "correlation_id": "01JTESTCORR0000", "locale": "en-US", "channel": "voice"}
    base.update(kw)
    return base


def selftest():
    spec = _load(SPEC_PATH)
    catalog = _load(CONFIG_PATH)
    vn = catalog["leak_scanner"]["vendor_names"]
    it = catalog["leak_scanner"]["internal_structure_terms"]
    checks = []

    def chk(cond, msg):
        checks.append((bool(cond), msg))

    # 1 retryable → TEMPORARY + retriable_hint
    o = normalize(_req(fault_class="TIMEOUT"), spec, catalog)
    chk(o["customer"]["category"] == "TEMPORARY" and o["customer"]["retriable_hint"], "TIMEOUT→TEMPORARY+retr")

    # 2 RATE_LIMITED/QUOTA → BUSY
    chk(normalize(_req(fault_class="RATE_LIMITED"), spec, catalog)["customer"]["category"] == "BUSY", "RATE_LIMITED→BUSY")
    chk(normalize(_req(fault_class="QUOTA_EXCEEDED"), spec, catalog)["customer"]["category"] == "BUSY", "QUOTA_EXCEEDED→BUSY")

    # 3 terminal → CANNOT_COMPLETE, retriable_hint False
    o = normalize(_req(fault_class="UPSTREAM_4XX"), spec, catalog)
    chk(o["customer"]["category"] == "CANNOT_COMPLETE" and not o["customer"]["retriable_hint"], "UPSTREAM_4XX→CANNOT_COMPLETE")

    # 4 AUTH/REGION → JENERİK NOT_PERMITTED (neden açılmaz)
    oa = normalize(_req(fault_class="AUTH"), spec, catalog)
    orr = normalize(_req(fault_class="REGION_VIOLATION"), spec, catalog)
    chk(oa["customer"]["category"] == "NOT_PERMITTED" and orr["customer"]["category"] == "NOT_PERMITTED", "AUTH+REGION→NOT_PERMITTED jenerik")
    chk("region" not in oa["customer"]["voice_message"].lower() and "residency" not in orr["customer"]["voice_message"].lower(), "residency/region müşteriye sızmaz")

    # 5 N2 bilinmeyen fault → UNKNOWN (asla ham)
    o = normalize(_req(fault_class="WEIRD_NEW_FAULT_XYZ"), spec, catalog)
    chk(o["customer"]["category"] == "UNKNOWN" and "WEIRD" not in o["customer"]["voice_message"], "bilinmeyen→UNKNOWN, ham yok")

    # 6 N4 ham detay yüzeyde YOK — nasty internal_message
    nasty = "Traceback: NullPointerException at com.twilio.Api(Api.java:42) https://10.0.0.5/internal SELECT * FROM users; card 4111 1111 1111 1111"
    o = normalize(_req(fault_class="UPSTREAM_5XX", provider_code="TW-50012", endpoint="https://api.internal.svc/crm",
                       internal_message=nasty, tenant_id="t-abc"), spec, catalog)
    surface = o["customer"]["voice_message"] + o["api_problem"]["title"] + o["api_problem"]["detail"]
    chk("twilio" not in surface.lower() and "Traceback" not in surface and "10.0.0.5" not in surface, "ham detay yüzeyde yok")
    chk(o["leak_scan"]["clean"], "üretilen yüzey sızıntı taramasından temiz")
    chk(o["audit"]["provider_code"] == "TW-50012", "provider_code audit'te korunur")
    chk("[REDACTED-CARD]" in o["audit"]["internal_message"], "kart audit'te maskeli (FR-REC-005)")

    # 7 N7 enterpolasyon yok — voice mesajı katalog sabiti
    o = normalize(_req(fault_class="TIMEOUT"), spec, catalog)
    chk(o["customer"]["voice_message"] == catalog["messages"]["en-US"]["TEMPORARY"]["voice"], "voice=katalog sabiti")

    # 8 N3 locale fallback — desteklenmeyen locale → default
    o = normalize(_req(fault_class="TIMEOUT", locale="de-DE"), spec, catalog)
    chk(o["customer"]["locale"] == catalog["default_locale"] and o["customer"]["voice_message"], "desteklenmeyen locale→default")

    # 9 tr-TR yerelleştirme
    o = normalize(_req(fault_class="TIMEOUT", locale="tr-TR"), spec, catalog)
    chk(o["customer"]["voice_message"] == catalog["messages"]["tr-TR"]["TEMPORARY"]["voice"], "tr-TR mesajı")

    # 10 N9 determinizm
    a = normalize(_req(fault_class="UPSTREAM_4XX", provider_code="X1"), spec, catalog)
    b = normalize(_req(fault_class="UPSTREAM_4XX", provider_code="X1"), spec, catalog)
    chk(json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True), "determinizm aynı girdi→aynı çıktı")

    # 11 N5 RFC 9457 — status kategori http_status
    o = normalize(_req(fault_class="NOT_FOUND", channel="api"), spec, catalog)
    chk(o["api_problem"]["status"] == 404 and o["api_problem"]["type"].endswith("not-found"), "RFC9457 NOT_FOUND 404")
    chk(o["api_problem"]["correlation_id"] == "01JTESTCORR0000", "RFC9457 correlation_id")

    # 12 N10 voice'ta rakam/iç-yapı yok (tüm katalog)
    voice_clean = True
    for loc in catalog["supported_locales"]:
        for cat in _no_meta(spec["customer_categories"]):
            if scan_leaks(catalog["messages"][loc][cat]["voice"], vn, it, voice=True):
                voice_clean = False
    chk(voice_clean, "tüm voice mesajları rakam/iç-yapı içermez")

    # 13 sızıntı tarayıcısı GERÇEK — bilinen kirli metin yakalanır
    dirty = "Call to twilio failed: NullPointerException at Foo.java:9, see https://x.internal 10.1.2.3"
    chk(len(scan_leaks(dirty, vn, it, voice=False)) >= 3, "tarayıcı kirli metni yakalar (vendor+stack+url+ip)")
    chk(not scan_leaks("I can connect you with an agent.", vn, it, voice=True), "temiz cümle yanlış-pozitif vermez")

    # 14 override fail-safe: kirli tenant override reddedilir, güvenli katalog mesajı kalır
    o = normalize(_req(fault_class="TIMEOUT", customer_message_override="Error: twilio 500 at api.py:3"), spec, catalog)
    chk(o["customer"]["override_rejected"] and o["leak_scan"]["clean"], "kirli override reddedilir→güvenli fallback")
    # temiz override kabul
    clean_ov = "We hit a snag completing that. Let me try another way."
    o2 = normalize(_req(fault_class="TIMEOUT", customer_message_override=clean_ov), spec, catalog)
    chk(not o2["customer"]["override_rejected"] and o2["customer"]["voice_message"] == clean_ov, "temiz override kabul edilir")

    # 15 N12 audit customer_safe=false + eksiksiz
    o = normalize(_req(fault_class="AUTH_FAILED", provider_code="P", endpoint="e", tenant_id="t"), spec, catalog)
    a = o["audit"]
    chk(a["customer_safe"] is False and a["fault_class"] == "AUTH_FAILED" and a["severity"] == "high", "audit eksiksiz customer_safe=false")

    # 16 N8 retriable_hint kategori ile birebir
    fmap = _no_meta(spec["fault_map"])
    ok8 = all(normalize(_req(fault_class=f), spec, catalog)["customer"]["retriable_hint"]
              == (fmap[f] in ("TEMPORARY", "BUSY")) for f in fmap)
    chk(ok8, "retriable_hint tüm fault'larda kategori-tutarlı")

    # 17 handoff_available=False → suggest_handoff False
    o = normalize(_req(fault_class="TIMEOUT", handoff_available=False), spec, catalog)
    chk(not o["customer"]["suggest_handoff"], "handoff_available=False → öneri yok")

    npass = sum(1 for c, _ in checks if c)
    for c, m in checks:
        print("  %s %s" % ("🟢" if c else "🔴", m))
    print("selftest: %d/%d" % (npass, len(checks)))
    return 0 if npass == len(checks) else 1


# ── schema ──────────────────────────────────────────────────────────────────────
def schema():
    spec = _load(SPEC_PATH)
    print("# WBS 7.1.5 — Hata normalizasyonu (SAD §11.1 [6] / FR-TOOL-008) sözleşmeleri\n")
    print("Akış: fault_class (7.1.4 ∪ API §11.6) → [kategori eşleme + statik katalog + sızıntı taraması] → NormalizedError\n")
    print("NormalizationRequest: {%s}" % ", ".join(spec["spi"]["request_fields"]))
    print("İki DİSJONKT yüzey:")
    print("  customer (müşteri/arayan): {%s}" % ", ".join(spec["spi"]["customer_fields"]))
    print("  api_problem (RFC 9457): {%s}" % ", ".join(spec["spi"]["api_problem_fields"]))
    print("  audit (yalnız log — customer_safe=false): {%s}\n" % ", ".join(spec["spi"]["audit_fields"]))
    print("Müşteri kategorileri (ham fault'ları daraltır):")
    for c, v in _no_meta(spec["customer_categories"]).items():
        print("  %-16s code=%-15s status=%d retr=%s handoff=%s sev=%s" % (
            c, v["customer_code"], v["http_status"], v["retriable_hint"], v["suggest_handoff"], v["severity"]))
    print("\nfault_class → category eşlemesi (toplam; bilinmeyen→UNKNOWN):")
    for f, c in _no_meta(spec["fault_map"]).items():
        print("  %-18s → %s" % (f, c))
    print("\nSızıntı sınıfları (N1; müşteri-görünür metinde hit=0): %s" % ", ".join(spec["leak_taxonomy"]["forbidden_classes"]))
    print("Voice ek yasak (N10): %s" % ", ".join(spec["leak_taxonomy"]["voice_extra_forbidden"]))
    print("\nKapılar (N1–N12):")
    for inv in spec["invariants"]:
        print("  %s — %s" % (inv["id"], inv["desc"][:94]))
    return 0


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd = argv[1]
    if cmd == "validate":
        return validate()
    if cmd == "selftest":
        return selftest()
    if cmd == "schema":
        return schema()
    if cmd == "normalize":
        if len(argv) < 3:
            print("kullanım: error_normalization_probe.py normalize <sample.json>")
            return 2
        return normalize_cmd(argv[2])
    print("bilinmeyen komut: %s" % cmd)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
