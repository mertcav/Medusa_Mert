#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
numbering_probe.py — WBS 2.1.5 E.164 normalizasyonu + Caller ID & numara havuzu yönetimi

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only statik + davranış kapısı.
`telephony/managed-cpaas/`+`telephony/byoc-sip/` probe disipliniyle aynı.

Numaralandırma DÜZLEMİ (medya düzlemi değil):
  • Inbound:  e164 DID → tenant(+agent) deterministik çözüm → 2.1.3/2.1.4 context_binding did_to_tenant_map kaynağı.
  • Outbound: tenant havuzundan Caller ID seçimi (anti-spoof) → API §11.5 DialRequest.callerIdPool/from kaynağı.

Komutlar:
  validate              numbering-spec.json'ı invariant'lara + config havuzuna karşı doğrular (çıkış kodu).
  normalize <sample>    Deterministik E.164 normalize simülatörü — çeşitli giriş biçimi → tek kanonik E.164;
                        idempotency + geçersiz-girdi reddi kontrol (FR-TEL-004); kapı→çıkış kodu.
  select <sample>       Deterministik Caller ID seçim simülatörü — (tenant, callee, kampanya, talep) → seçilen
                        Caller ID; anti-spoof + local-presence + residency + outbound-yetki kontrol (FR-TEL-005).
  resolve <e164>        Inbound DID → tenant(+agent) çözümü (config havuzundan); çapraz-tenant benzersizlik.
  selftest              İyi/kötü spec+sample ile kapıların doğru tetiklendiğini kanıtlar.
  schema                Beklenen spec şeklini özetler.

Sunucu/credential GEREKMEZ. normalize/select gerçek telekom yerine deterministik simülasyondur
(managed-cpaas normalize / byoc normalize / objstore access-decision deseni).
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "numbering-spec.json")
POOL_CFG = os.path.join(HERE, "config", "number-pool.json")

ERROR_TAXONOMY = {
    "TIMEOUT", "RATE_LIMITED", "UNAVAILABLE", "AUTH",
    "INVALID_REQUEST", "CONTENT_FILTERED", "QUOTA_EXCEEDED", "REGION_VIOLATION",
}
DIRECTIONS = {"inbound", "outbound", "both"}
CANONICAL_RE = re.compile(r"^\+[1-9]\d{6,14}$")
# Sır tarayıcı: yorum satırları (sırrı *tarif eden* açıklama ≠ sır) elenir; eventstream/byoc deseni.
SECRET_RE = re.compile(
    r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer)\b\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}"
)
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_placeholder(v):
    return isinstance(v, str) and PLACEHOLDER_RE.match(v) is not None


# ─────────────────────────────────────────────────────────────────────────────
# E.164 normalize çekirdeği (deterministik, idempotent — FR-TEL-004)
# ─────────────────────────────────────────────────────────────────────────────
class NumberError(Exception):
    """Çevrilemeyen/geçersiz numara — sessizce kırpma yok, reddet (N3)."""


def _meta(spec):
    """country_metadata'yı $comment vb. meta-anahtarlardan arındırıp döner."""
    return {k: m for k, m in spec.get("country_metadata", {}).items()
            if not k.startswith("$")}


def _cc_index(meta):
    """ülke kodu (str) → ülke metadata; uzun-eşleşme için kullanılacak."""
    return {m["cc"]: m for m in meta.values() if isinstance(m, dict)}


def _match_cc(e_digits, meta):
    """e_digits (+'sız, sadece haneler) için en uzun ülke kodu eşlemesi. Döner (cc|None, meta|None)."""
    by_cc = _cc_index(meta)
    for ln in (3, 2, 1):
        cand = e_digits[:ln]
        if cand in by_cc:
            return cand, by_cc[cand]
    return None, None


def normalize_e164(raw, default_region, meta):
    """Çeşitli giriş biçimini tek kanonik E.164'e indirger. Geçersizse NumberError.
    default_region: ülke kodu anahtarı (TR/GB/DE/US) — '+'siz/ulusal girdiler için bağlam."""
    if not isinstance(raw, str) or not raw.strip():
        raise NumberError("boş/geçersiz girdi")
    s = raw.strip()
    has_plus = s.startswith("+")
    digits = "".join(ch for ch in s if ch.isdigit())
    if not digits:
        raise NumberError("hane yok")

    reg = meta.get(default_region) if default_region else None

    if has_plus:
        e = digits  # zaten uluslararası (CC+NSN)
    else:
        idd_default = "00"
        reg_idd = reg.get("idd") if reg else None
        trunk = reg.get("trunk", "") if reg else ""
        if digits.startswith(idd_default) and not (trunk == "0"):
            # '00' uluslararası önek (TR/GB/DE trunk '0' iken '00' yine de IDD; '0'+'0' ulusal değil)
            e = digits[2:]
        elif digits.startswith(idd_default) and trunk == "0":
            # ülke trunk '0': '00xxx' ulusal '0'+'0xxx' değil — '00' IDD olarak yorumla
            e = digits[2:]
        elif reg_idd and reg_idd != "00" and digits.startswith(reg_idd):
            # NANP '011' gibi farklı IDD
            e = digits[len(reg_idd):]
        elif reg:
            cc = reg["cc"]
            nmin, nmax = reg["nsn_min"], reg["nsn_max"]
            if trunk and digits.startswith(trunk) and nmin <= len(digits) - len(trunk) <= nmax:
                e = cc + digits[len(trunk):]            # ulusal (trunk'lı) → CC ekle
            elif nmin <= len(digits) <= nmax:
                e = cc + digits                          # ulusal (trunk'sız) → CC ekle
            elif digits.startswith(cc) and nmin <= len(digits) - len(cc) <= nmax:
                e = digits                               # zaten CC içeriyor
            else:
                raise NumberError("ulusal numara uzunluğu metadata'ya uymuyor (region=%s)" % default_region)
        else:
            raise NumberError("bağlam yok: '+' yok, default_region yok, IDD yok")

    if len(e) > 15:
        raise NumberError(">15 hane (E.164 üst sınırı)")
    out = "+" + e
    if not CANONICAL_RE.match(out):
        raise NumberError("kanonik E.164 biçimi değil: %s" % out)
    # ülke kodu biliniyorsa NSN uzunluğunu doğrula (fazla/eksik hane reddi)
    cc, regmeta = _match_cc(e, meta)
    if regmeta:
        nsn = e[len(cc):]
        if not (regmeta["nsn_min"] <= len(nsn) <= regmeta["nsn_max"]):
            raise NumberError("NSN uzunluğu ülke aralığı dışı (cc=%s nsn=%d)" % (cc, len(nsn)))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# validate
# ─────────────────────────────────────────────────────────────────────────────
def _check(results, ok, label):
    results.append((bool(ok), label))


def _scan_secrets(obj, path="root"):
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.startswith("$"):
                continue
            hits += _scan_secrets(v, "%s.%s" % (path, k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits += _scan_secrets(v, "%s[%d]" % (path, i))
    elif isinstance(obj, str):
        if _is_placeholder(obj):
            return hits
        if SECRET_RE.search(obj):
            hits.append((path, obj))
    return hits


def validate():
    spec = _load(SPEC_PATH)
    R = []

    _check(R, spec.get("wbs") == "2.1.5", "spec.wbs == 2.1.5")
    _check(R, spec.get("version"), "spec.version mevcut")

    # ── N1/N2/N3: E.164 sözleşmesi
    e = spec.get("e164", {})
    _check(R, e.get("plus_prefix") == "+", "N1 '+' öneki")
    _check(R, e.get("max_digits") == 15, "N1 max 15 hane")
    _check(R, e.get("canonical_regex"), "N1 kanonik regex tanımlı")
    _check(R, e.get("idempotent") is True, "N2 idempotent bayrağı")
    _check(R, e.get("reject_on_invalid") is True, "N3 geçersiz girdi reddi")

    # ── country metadata sağlığı
    meta_all = spec.get("country_metadata", {})
    meta = {k: m for k, m in meta_all.items() if not k.startswith("$")}
    _check(R, len(meta) >= 3, "country_metadata ≥3 ülke")
    for k, m in meta.items():
        _check(R, m.get("cc") and isinstance(m.get("nsn_min"), int) and isinstance(m.get("nsn_max"), int)
               and m["nsn_min"] <= m["nsn_max"],
               "country %s metadata (cc/nsn aralığı) tutarlı" % k)
    # cc'ler benzersiz
    ccs = [m["cc"] for m in meta.values()]
    _check(R, len(ccs) == len(set(ccs)), "ülke kodları benzersiz")

    # ── canonical_regex gerçekten E.164 örneklerini doğru sınıflıyor mu (self-tutarlılık)
    rx = re.compile(e.get("canonical_regex", "x^"))
    _check(R, bool(rx.match("+12025550143")) and not rx.match("12025550143")
           and not rx.match("+0123") and not rx.match("+"),
           "N1 canonical_regex E.164 örneklerini doğru ayırır")

    # ── N4/N5: numara havuzu sözleşmesi
    npn = spec.get("number_pool", {})
    _check(R, npn.get("global_uniqueness") is True, "N4 e164 global benzersiz")
    _check(R, set(npn.get("directions", [])) == DIRECTIONS, "havuz yön kümesi {inbound,outbound,both}")
    _check(R, npn.get("region_pin_required") is True, "N7 havuz bölge pini zorunlu")
    _check(R, npn.get("inbound_routing") == "did_to_agent", "N5 inbound DID→agent yönlendirme")

    # ── N6/N8/N9: caller id politikası
    ci = spec.get("caller_id", {})
    _check(R, ci.get("must_belong_to_tenant_pool") is True, "N6 caller id havuza ait olmalı (anti-spoof)")
    _check(R, ci.get("must_be_outbound_capable") is True, "N6 caller id outbound-yetkili olmalı")
    _check(R, "local_presence" in ci and ci.get("local_presence") is True, "N8 local-presence stratejisi")
    pres = ci.get("presentation", {})
    _check(R, pres.get("default") == "present"
           and pres.get("withhold_allowed_only_if_compliance") is True
           and pres.get("cp_key") == "cp.outbound.cli_presentation",
           "N9 CLI sunumu + compliance-bağlı gizleme")

    # ── N10: error taxonomy
    et = spec.get("error_taxonomy", {})
    mapping = et.get("mapping", {})
    _check(R, len(mapping) >= 4, "N10 hata eşlemesi (≥4)")
    _check(R, all(v in ERROR_TAXONOMY for v in mapping.values()),
           "N10 tüm hedefler API §11.6 ErrorTaxonomy'de")
    _check(R, mapping.get("caller_id_not_in_pool") == "INVALID_REQUEST"
           and mapping.get("region_mismatch") == "REGION_VIOLATION",
           "N10 spoof→INVALID_REQUEST, bölge→REGION_VIOLATION")

    # ── N7/N11: residency + pii
    _check(R, spec.get("residency", {}).get("region_pin_required") is True, "N7 residency region pin")
    _check(R, spec.get("pii", {}).get("customer_numbers_in_spec_forbidden") is True,
           "N11 müşteri numarası spec'te yasak")

    # ── invariant kataloğu
    inv_ids = [i.get("id") for i in spec.get("invariants", [])]
    _check(R, len(inv_ids) == len(set(inv_ids)) and len(inv_ids) >= 11,
           "invariant kataloğu ≥11 + tekil ID")
    _check(R, all(i.get("trace") for i in spec.get("invariants", [])),
           "her invariant trace taşır")

    # ── N11: literal sır taraması (spec + config)
    hits = _scan_secrets(spec)
    if os.path.exists(POOL_CFG):
        hits += _scan_secrets(_load(POOL_CFG))
    _check(R, not hits, "N11 literal sır yok (spec+config)")

    # ── config havuzu doğrulaması (N1/N4/N6/N7)
    if os.path.exists(POOL_CFG):
        cfg = _load(POOL_CFG)
        default_region = cfg.get("default_region")
        _check(R, default_region in meta, "config default_region metadata'da")
        seen = {}            # e164 → tenant (N4 global benzersizlik)
        all_ok_e164 = True
        for pool in cfg.get("pools", []):
            tn = pool.get("tenant")
            for num in pool.get("numbers", []):
                ev = num.get("e164", "")
                # N1: havuzdaki her numara zaten kanonik E.164
                try:
                    canon = normalize_e164(ev, default_region, meta)
                except NumberError:
                    canon = None
                if canon != ev or not CANONICAL_RE.match(ev or ""):
                    all_ok_e164 = False
                # N4: global benzersizlik (çapraz-tenant çakışma yok)
                if ev in seen and seen[ev] != tn:
                    _check(R, False, "N4 %s iki tenant'a ait (%s, %s)" % (ev, seen[ev], tn))
                seen[ev] = tn
                # yön + bölge + caller-id yeteneği
                _check(R, num.get("direction") in DIRECTIONS, "config %s yön geçerli" % ev)
                _check(R, bool(num.get("region")), "N7 config %s bölge pini var" % ev)
                if num.get("direction") == "inbound" and num.get("caller_id_capable"):
                    _check(R, False, "N6 %s inbound-only ama caller_id_capable işaretli" % ev)
        _check(R, all_ok_e164, "N1 config havuz numaraları kanonik E.164 (idempotent)")
        _check(R, len(seen) == sum(len(p.get("numbers", [])) for p in cfg.get("pools", [])),
               "N4 config havuzunda e164 global benzersiz")

    passed = sum(1 for ok, _ in R if ok)
    total = len(R)
    for ok, label in R:
        if not ok:
            print("  ✗ %s" % label)
    print("validate: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


# ─────────────────────────────────────────────────────────────────────────────
# normalize — deterministik E.164 normalize simülatörü (FR-TEL-004)
# ─────────────────────────────────────────────────────────────────────────────
def normalize_sequence(spec, sample):
    """sample.cases[] üzerinden normalize'i çalıştırır + idempotency kontrol.
    Döner findings=[(ok,label),...]."""
    meta = _meta(spec)
    F = []
    for c in sample.get("cases", []):
        raw = c.get("input")
        region = c.get("default_region", sample.get("default_region"))
        want = c.get("expected")          # kanonik beklenen (reddedilecekse null)
        should_reject = c.get("reject", False)
        try:
            got = normalize_e164(raw, region, meta)
        except NumberError as ex:
            if should_reject:
                F.append((True, "N3 '%s' reddedildi (%s)" % (raw, ex)))
            else:
                F.append((False, "'%s' beklenmedik şekilde reddedildi (%s)" % (raw, ex)))
            continue
        if should_reject:
            F.append((False, "N3 '%s' reddedilmeliydi ama '%s' üretti" % (raw, got)))
            continue
        # N1: kanonik biçim
        ok_canon = bool(CANONICAL_RE.match(got))
        # beklenen eşleşme
        ok_want = (got == want) if want is not None else True
        # N2: idempotency
        again = normalize_e164(got, region, meta)
        ok_idem = (again == got)
        ok = ok_canon and ok_want and ok_idem
        detail = "'%s'→'%s'" % (raw, got)
        if want is not None and not ok_want:
            detail += " (beklenen '%s')" % want
        if not ok_idem:
            detail += " (idempotent değil: '%s')" % again
        F.append((ok, "N1/N2 %s" % detail))
    return F


def normalize_cmd(sample_path):
    spec = _load(SPEC_PATH)
    sample = _load(sample_path)
    name = sample.get("name", os.path.basename(sample_path))
    F = normalize_sequence(spec, sample)
    passed = sum(1 for ok, _ in F if ok)
    total = len(F)
    print("normalize[%s] case=%d" % (name, total))
    for ok, label in F:
        print("  %s %s" % ("✓" if ok else "✗", label))
    gate_ok = (passed == total)
    print("  kapı: %d/%d %s" % (passed, total, "🟢 GEÇTİ" if gate_ok else "🔴 ELENDİ"))
    expect = sample.get("expect", "pass")
    if expect == "fail":
        return 0 if not gate_ok else 1
    return 0 if gate_ok else 1


# ─────────────────────────────────────────────────────────────────────────────
# select — deterministik Caller ID seçim simülatörü (FR-TEL-005, BRD §737)
# ─────────────────────────────────────────────────────────────────────────────
def _pool_for_tenant(cfg, tenant):
    for p in cfg.get("pools", []):
        if p.get("tenant") == tenant:
            return p
    raise NumberError("bilinmeyen tenant: %s" % tenant)


def select_caller_id(spec, pool, callee_e164, campaign=None, requested=None, home_region=None):
    """Deterministik Caller ID seçimi + invariant değerlendirmesi.
    Döner (chosen|None, findings)."""
    meta = _meta(spec)
    F = []
    numbers = pool.get("numbers", [])
    # outbound-yetkili adaylar (N6)
    cands = [n for n in numbers
             if n.get("direction") in ("outbound", "both") and n.get("caller_id_capable")]

    # (1) talep edilen caller id — anti-spoof (N6)
    if requested:
        # talep edilen değeri kanonikleştir
        try:
            req = normalize_e164(requested, _default_region(spec, pool), meta)
        except NumberError:
            req = requested
        match = [n for n in cands if n.get("e164") == req]
        if not match:
            raise NumberError("talep edilen Caller ID havuzda/outbound değil — spoof reddi: %s" % requested)
        chosen = match[0]
        F.append((True, "N6 talep edilen caller id havuzda+outbound: %s" % req))
    else:
        # (2) kampanya pin'i
        if campaign:
            pinned = [n for n in cands if campaign in n.get("campaign_ids", [])]
            if pinned:
                cands = pinned
                F.append((True, "N8 kampanya pin uygulandı (%s, %d aday)" % (campaign, len(cands))))
        if not cands:
            raise NumberError("uygun outbound Caller ID yok (havuz boş/uyumsuz)")
        # (3) local-presence: callee ülke kodu ile eşleşen numara tercih
        try:
            callee_canon = normalize_e164(callee_e164, _default_region(spec, pool), meta)
        except NumberError as ex:
            raise NumberError("callee normalize edilemedi: %s" % ex)
        callee_cc, _ = _match_cc(callee_canon[1:], meta)
        local = [n for n in cands if _match_cc(n["e164"][1:], meta)[0] == callee_cc]
        chosen_set = local or cands
        if local:
            F.append((True, "N8 local-presence: callee cc=%s ile eşleşen %d numara" % (callee_cc, len(local))))
        else:
            F.append((True, "N8 local-presence yok → havuz varsayılanı"))
        # (4) deterministik: e164-sıralı ilk
        chosen = sorted(chosen_set, key=lambda n: n["e164"])[0]

    # ── seçilen numara invariant'ları
    F.append((chosen.get("direction") in ("outbound", "both"), "N6 seçilen numara outbound-yetkili"))
    F.append((chosen.get("caller_id_capable") is True, "N6 seçilen numara caller_id_capable"))
    F.append((bool(chosen.get("region")), "N7 seçilen numara bölge pini var"))
    if home_region:
        F.append((chosen.get("region") == home_region,
                  "N7 caller id bölge=home_region (%s)" % home_region))
    # N9 CLI sunumu (gizleme yalnız compliance izniyle)
    presentation = pool.get("cli_presentation", "present")
    compliance_allows_withhold = pool.get("compliance_allows_withhold", False)
    F.append((presentation == "present" or compliance_allows_withhold,
              "N9 CLI sunumu geçerli (withhold yalnız compliance ile)"))
    return chosen, F


def _default_region(spec, pool):
    return pool.get("default_region") or spec.get("default_region") or "GB"


def select_cmd(sample_path):
    spec = _load(SPEC_PATH)
    sample = _load(sample_path)
    name = sample.get("name", os.path.basename(sample_path))
    # havuz: sample inline pool verebilir, yoksa config'ten tenant ile
    if "pool" in sample:
        pool = sample["pool"]
    else:
        cfg = _load(POOL_CFG)
        pool = _pool_for_tenant(cfg, sample["tenant"])
        pool = dict(pool)
        pool.setdefault("default_region", cfg.get("default_region"))
    expect = sample.get("expect", "pass")
    try:
        chosen, F = select_caller_id(
            spec, pool, sample["callee"],
            campaign=sample.get("campaign"),
            requested=sample.get("requested_caller_id"),
            home_region=sample.get("home_region"),
        )
    except NumberError as ex:
        print("select[%s]: REDDEDİLDİ — %s" % (name, ex))
        return 0 if expect == "fail" else 1
    passed = sum(1 for ok, _ in F if ok)
    total = len(F)
    print("select[%s] callee=%s → caller_id=%s" % (name, sample["callee"], chosen["e164"]))
    for ok, label in F:
        print("  %s %s" % ("✓" if ok else "✗", label))
    want = sample.get("expected_caller_id")
    ok_want = (chosen["e164"] == want) if want else True
    if want and not ok_want:
        print("  ✗ beklenen caller id %s, seçilen %s" % (want, chosen["e164"]))
    gate_ok = (passed == total) and ok_want
    print("  kapı: %d/%d %s" % (passed, total, "🟢 GEÇTİ" if gate_ok else "🔴 ELENDİ"))
    if expect == "fail":
        return 0 if not gate_ok else 1
    return 0 if gate_ok else 1


# ─────────────────────────────────────────────────────────────────────────────
# resolve — inbound DID → tenant(+agent) (config havuzundan; N5)
# ─────────────────────────────────────────────────────────────────────────────
def resolve_cmd(did):
    spec = _load(SPEC_PATH)
    cfg = _load(POOL_CFG)
    meta = _meta(spec)
    try:
        canon = normalize_e164(did, cfg.get("default_region"), meta)
    except NumberError as ex:
        print("resolve[%s]: normalize edilemedi — %s (→ INVALID_REQUEST)" % (did, ex))
        return 1
    matches = []
    for pool in cfg.get("pools", []):
        for num in pool.get("numbers", []):
            if num.get("e164") == canon and num.get("direction") in ("inbound", "both"):
                matches.append((pool.get("tenant"), num.get("agent_id"), num.get("region")))
    if len(matches) == 0:
        print("resolve[%s] = %s: çözülemedi (inbound havuzda yok → INVALID_REQUEST)" % (did, canon))
        return 1
    if len(matches) > 1:
        print("resolve[%s] = %s: çapraz-tenant ÇAKIŞMA (%d eşleşme) — N4 ihlali!" % (did, canon, len(matches)))
        return 1
    tn, ag, rg = matches[0]
    print("resolve[%s] = %s → tenant=%s agent=%s region=%s (N5 deterministik)" % (did, canon, tn, ag, rg))
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# selftest
# ─────────────────────────────────────────────────────────────────────────────
def selftest():
    spec = _load(SPEC_PATH)
    meta = _meta(spec)
    cases = []

    def case(ok, label):
        cases.append((bool(ok), label))

    # 1) validate iyi spec+config'te geçer
    case(validate_silent() == 0, "validate iyi spec+config'te 0 döndürür")

    # ── E.164 normalize doğruluk (FR-TEL-004) ───────────────────────────────────
    # 2) TR ulusal (trunk'lı) → +90...
    case(normalize_e164("0212 345 67 89", "TR", meta) == "+902123456789", "TR ulusal '0...' → +90")
    # 3) TR boşluk/tire temizliği idempotent
    case(normalize_e164("+90 (212) 345-67-89", "TR", meta) == "+902123456789", "TR biçimli '+' → kanonik")
    case(normalize_e164("+902123456789", "TR", meta) == "+902123456789", "TR zaten kanonik idempotent")
    # 4) TR '00' IDD → uluslararası
    case(normalize_e164("00 44 1632 960123", "TR", meta) == "+441632960123", "TR'den '00' IDD → +44")
    # 5) GB ulusal '0...' → +44
    case(normalize_e164("01632 960123", "GB", meta) == "+441632960123", "GB ulusal '0...' → +44")
    # 6) US ulusal 10 hane → +1
    case(normalize_e164("(202) 555-0143", "US", meta) == "+12025550143", "US 10-hane → +1")
    # 7) US trunk '1' + 10 hane → +1 (NANP)
    case(normalize_e164("1 202 555 0143", "US", meta) == "+12025550143", "US '1'+10 hane → +1")
    # 8) US '011' IDD → uluslararası
    case(normalize_e164("011 44 1632 960123", "US", meta) == "+441632960123", "US '011' IDD → +44")
    # 9) idempotency: normalize(normalize(x))==normalize(x) (N2)
    once = normalize_e164("0212 345 67 89", "TR", meta)
    case(normalize_e164(once, "TR", meta) == once, "N2 idempotent (TR)")

    # ── geçersiz girdi reddi (N3) ────────────────────────────────────────────────
    def rejects(raw, region):
        try:
            normalize_e164(raw, region, meta)
            return False
        except NumberError:
            return True
    case(rejects("", "TR"), "N3 boş girdi reddi")
    case(rejects("abc", "TR"), "N3 hanesiz girdi reddi")
    case(rejects("+1234567890123456", "US"), "N3 >15 hane reddi")
    case(rejects("123", "TR"), "N3 çok kısa ulusal reddi")
    case(rejects("0212 345", "TR"), "N3 eksik haneli TR ulusal reddi")
    # 10) '+'lı ama NSN ülke aralığı dışı → reddet
    case(rejects("+90212345", "TR"), "N3 '+90' kısa NSN reddi")

    # ── Caller ID seçimi (FR-TEL-005, BRD §737) ─────────────────────────────────
    uk_pool = {
        "tenant": "t-uk", "default_region": "GB", "home_region": "uk-london",
        "numbers": [
            {"e164": "+441632960123", "direction": "both", "region": "uk-london", "caller_id_capable": True, "agent_id": "a1", "campaign_ids": []},
            {"e164": "+447700900123", "direction": "outbound", "region": "uk-london", "caller_id_capable": True, "campaign_ids": ["winback"]},
            {"e164": "+12025550143", "direction": "outbound", "region": "uk-london", "caller_id_capable": True, "campaign_ids": []},
            {"e164": "+441632960900", "direction": "inbound", "region": "uk-london", "caller_id_capable": False, "agent_id": "a2", "campaign_ids": []},
        ],
    }
    # 11) local-presence: UK callee → UK numara (e164-sıralı ilk)
    chosen, F = select_caller_id(spec, uk_pool, "+447700900999", home_region="uk-london")
    case(chosen["e164"] == "+441632960123" and all(ok for ok, _ in F),
         "N8 UK callee → UK caller id (local-presence)")
    # 12) US callee → US numara (local-presence)
    chosen, F = select_caller_id(spec, uk_pool, "+12025550199", home_region="uk-london")
    case(chosen["e164"] == "+12025550143", "N8 US callee → US caller id (local-presence)")
    # 13) kampanya pin
    chosen, F = select_caller_id(spec, uk_pool, "+447700900999", campaign="winback", home_region="uk-london")
    case(chosen["e164"] == "+447700900123", "N8 kampanya pin → pinli caller id")
    # 14) inbound-only numara asla caller id seçilmez (N6)
    chosen, F = select_caller_id(spec, uk_pool, "+447700900999", home_region="uk-london")
    case(chosen["e164"] != "+441632960900", "N6 inbound-only numara caller id olmaz")
    # 15) anti-spoof: talep edilen numara havuzda değil → reddet
    spoof = False
    try:
        select_caller_id(spec, uk_pool, "+447700900999", requested="+15005550000")
    except NumberError:
        spoof = True
    case(spoof, "N6 havuz-dışı caller id talebi reddedilir (anti-spoof)")
    # 16) talep edilen numara havuzda+outbound → kabul
    chosen, F = select_caller_id(spec, uk_pool, "+447700900999", requested="+447700900123")
    case(chosen["e164"] == "+447700900123", "N6 havuzdaki outbound caller id talebi kabul")
    # 17) talep edilen numara inbound-only → reddet (anti-spoof)
    spoof2 = False
    try:
        select_caller_id(spec, uk_pool, "+447700900999", requested="+441632960900")
    except NumberError:
        spoof2 = True
    case(spoof2, "N6 inbound-only numara talebi reddedilir (anti-spoof)")
    # 18) deterministik: aynı girdi → aynı çıktı
    c1, _ = select_caller_id(spec, uk_pool, "+447700900111", home_region="uk-london")
    c2, _ = select_caller_id(spec, uk_pool, "+447700900111", home_region="uk-london")
    case(c1["e164"] == c2["e164"], "N8 seçim deterministik (kararlı)")
    # 19) N9: CLI gizleme compliance olmadan reddedilir
    wh_pool = dict(uk_pool); wh_pool["cli_presentation"] = "withhold"; wh_pool["compliance_allows_withhold"] = False
    _, F = select_caller_id(spec, wh_pool, "+447700900999", home_region="uk-london")
    case(any((not ok) and "CLI sunumu" in lbl for ok, lbl in F), "N9 compliance'sız withhold → bulgu")
    # 20) N9: CLI gizleme compliance ile geçer
    wh2 = dict(uk_pool); wh2["cli_presentation"] = "withhold"; wh2["compliance_allows_withhold"] = True
    _, F = select_caller_id(spec, wh2, "+447700900999", home_region="uk-london")
    case(all(ok for ok, _ in F), "N9 compliance'lı withhold → geçer")
    # 21) N7: bölge uyumsuz home_region → bulgu
    _, F = select_caller_id(spec, uk_pool, "+447700900999", home_region="eu-frankfurt")
    case(any((not ok) and "home_region" in lbl for ok, lbl in F), "N7 caller id bölge ≠ home_region → bulgu")

    # ── validate negatif kapılar ─────────────────────────────────────────────────
    # 22) e164 global benzersiz değil (config çakışma) → validate eler
    case(_validate_with_pool(spec, _dup_pool_cfg()) != 0, "N4 çapraz-tenant e164 çakışma → validate eler")
    # 23) bozuk spec: caller id havuz şartı kapalı → N6 eler
    s = json.loads(json.dumps(spec)); s["caller_id"]["must_belong_to_tenant_pool"] = False
    case(_validate_obj(s) != 0, "N6 havuz şartı kapalı → validate eler")
    # 24) bozuk spec: max_digits != 15 → N1 eler
    s = json.loads(json.dumps(spec)); s["e164"]["max_digits"] = 20
    case(_validate_obj(s) != 0, "N1 max_digits!=15 → validate eler")
    # 25) bozuk spec: taksonomi-dışı hedef → N10 eler
    s = json.loads(json.dumps(spec)); s["error_taxonomy"]["mapping"]["x"] = "NOPE"
    case(_validate_obj(s) != 0, "N10 taksonomi-dışı → validate eler")
    # 26) bozuk spec: literal secret → N11 eler
    s = json.loads(json.dumps(spec)); s["number_pool"]["secret"] = "api_key: AKIAIOSFODNN7EXAMPLE"
    case(_validate_obj(s) != 0, "N11 literal secret → validate eler")

    passed = sum(1 for ok, _ in cases if ok)
    total = len(cases)
    for ok, label in cases:
        print("  %s %s" % ("✓" if ok else "✗", label))
    print("selftest: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


# ── selftest yardımcıları ───────────────────────────────────────────────────────
def validate_silent():
    return _validate_obj(_load(SPEC_PATH))


def _validate_obj(spec_obj):
    import io
    import contextlib
    tmp = os.path.join(HERE, ".._tmp_spec.json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(spec_obj, f)
    global SPEC_PATH
    orig = SPEC_PATH
    SPEC_PATH = tmp
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            rc = validate()
    finally:
        SPEC_PATH = orig
        os.remove(tmp)
    return rc


def _dup_pool_cfg():
    """N4 ihlali: aynı e164 iki tenant'ta."""
    return {
        "default_region": "GB",
        "pools": [
            {"tenant": "t-a", "numbers": [{"e164": "+441632960123", "direction": "both", "region": "uk-london", "caller_id_capable": True}]},
            {"tenant": "t-b", "numbers": [{"e164": "+441632960123", "direction": "both", "region": "uk-london", "caller_id_capable": True}]},
        ],
    }


def _validate_with_pool(spec_obj, pool_cfg):
    """validate'i geçici pool config ile koşar (selftest N4)."""
    import io
    import contextlib
    tmp = os.path.join(HERE, ".._tmp_pool.json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(pool_cfg, f)
    global POOL_CFG
    orig = POOL_CFG
    POOL_CFG = tmp
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            rc = validate()
    finally:
        POOL_CFG = orig
        os.remove(tmp)
    return rc


def schema():
    print("""numbering-spec.json beklenen şekli (WBS 2.1.5):
  wbs, version, phase, trace{fr,nfr,sad,adr,api,db,srs,brd}
  e164{plus_prefix='+', max_digits=15, min_digits, canonical_regex, strip_chars[],
       idd_prefixes{default='00',nanp='011'}, idempotent=true, reject_on_invalid=true}   (N1,N2,N3)
  country_metadata{TR/GB/DE/US{cc, trunk, nsn_min, nsn_max, idd}}                         (normalize çekirdeği)
  number_pool{scope='tenant', global_uniqueness=true, directions[inbound,outbound,both],
              region_pin_required=true, inbound_routing='did_to_agent'}                   (N4,N5,N7)
  caller_id{must_belong_to_tenant_pool=true, must_be_outbound_capable=true,
            selection_strategy, local_presence=true, campaign_binding=true,
            presentation{default='present', withhold_allowed_only_if_compliance, cp_key}} (N6,N8,N9)
  compliance{cp_keys[cp.outbound.*], valid_cli_required=true}                             (BRD §737)
  error_taxonomy{mapping→API §11.6}                                                       (N10)
  residency{region_pin_required=true}                                                     (N7)
  pii{customer_numbers_in_spec_forbidden=true, pool_numbers_are_illustrative=true}        (N11)
  invariants[≥11]{id, desc, trace}

config/number-pool.json: default_region + pools[]{tenant, home_region,
  numbers[]{e164(kanonik), direction, region, caller_id_capable, agent_id?, campaign_ids[]}}

komutlar: validate | normalize <sample.json> | select <sample.json> | resolve <e164> | selftest | schema""")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if cmd == "validate":
        return validate()
    if cmd == "normalize":
        if len(sys.argv) < 3:
            print("kullanım: numbering_probe.py normalize <sample.json>")
            return 2
        return normalize_cmd(sys.argv[2])
    if cmd == "select":
        if len(sys.argv) < 3:
            print("kullanım: numbering_probe.py select <sample.json>")
            return 2
        return select_cmd(sys.argv[2])
    if cmd == "resolve":
        if len(sys.argv) < 3:
            print("kullanım: numbering_probe.py resolve <e164>")
            return 2
        return resolve_cmd(sys.argv[2])
    if cmd == "selftest":
        return selftest()
    if cmd == "schema":
        return schema()
    print("bilinmeyen komut: %s (validate|normalize|select|resolve|selftest|schema)" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main())
