#!/usr/bin/env python3
"""
objstore_probe.py — WBS 1.1.6 Nesne depolama (S3-uyumlu) statik + davranış kapısı (stdlib-only).

`storage-spec.json` (source of truth) + `policy/*.json` referans politika şablonlarının tasarım
invariant'larını (O1..O11) kod gerektirmeden doğrular. Ayrıca canlı S3 sunucusu OLMADAN, S3
politika/lifecycle semantiğini deterministik olarak modelleyen iki simülatör sunar:
  - access-decision: bucket-policy + IAM prefix-policy + altın kural mantığını uygular (ALLOW/DENY).
  - lifecycle: data_class + obje yaşı + legal-hold → depolama eylemi (none/transition/expire-shred/retained).

Komutlar:
  validate    storage-spec + policy şablonu invariant kapısı (kontrol özeti; kapı→çıkış kodu)
  decide      tek erişim isteğini değerlendir (--json '<req>') → ALLOW/DENY + gerekçe
  lifecycle   tek lifecycle adımını değerlendir (--json '<req>') → eylem
  selftest    gömülü iyi/bozuk fixture'larla predikat + simülatör testleri (çıkış kodu)
  schema      beklenen nesneler/sözleşme özeti (JSON)

Canlı S3 davranış kapısı: tests/objstore_behavior_test.py + run_live_test.sh (endpoint varsa).
Sır/credential repoya yazılmaz; bu probe yalnız repodaki dosyaları okur.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "storage-spec.json")

# Anahtarda ham PII/serbest-metin işareti (hash'siz) — yasak bileşenler (O6, P6).
RAW_PII_TOKENS = ("<phone", "<msisdn", "<email", "<text>", "<name", "<query>", "<utterance", "<caller")
# Repoda literal sır taraması (O11). Placeholder ${...} ya da yorum içermeyen olası anahtar materyali.
SECRET_LITERAL_RE = re.compile(
    r"(AKIA[0-9A-Z]{16}|aws_secret_access_key\s*=\s*\S|-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)
CONTENT_CLASSES = {"recording", "transcript", "kb_document", "export"}


# --------------------------------------------------------------------------- #
# Yardımcılar
# --------------------------------------------------------------------------- #
def load_spec(path=SPEC_PATH):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def has_literal_secret(path):
    with open(path, "r", encoding="utf-8") as fh:
        return bool(SECRET_LITERAL_RE.search(fh.read()))


def _statements(policy):
    s = policy.get("Statement", [])
    return s if isinstance(s, list) else [s]


def _sids(policy):
    return {st.get("Sid") for st in _statements(policy)}


# --------------------------------------------------------------------------- #
# Çekirdek invariant değerlendiricileri (selftest bunları doğrudan çağırır)
# --------------------------------------------------------------------------- #
def key_has_dataclass_prefix(key, data_classes):
    """O6: anahtar tanınan bir data_class prefix'i ile başlar."""
    prefixes = [dc["prefix"] for dc in data_classes]
    return any(key.startswith(p) for p in prefixes)


def key_no_raw_pii(key):
    """O6/P6: anahtar ham PII/serbest-metin token'ı taşımaz."""
    return not any(tok in key for tok in RAW_PII_TOKENS)


def lifecycle_complete(dc):
    """O7: her data_class'ın transition VEYA expiration kuralı var."""
    return (dc.get("transition_days") is not None) or (dc.get("expire_days") is not None)


def content_class_locked(dc):
    """O10: legal_hold_capable content sınıfı versioning + object-lock(governance) taşır."""
    if dc.get("legal_hold_capable"):
        return dc.get("versioning") is True and dc.get("object_lock") == "governance"
    return True


def pii_is_content(dc):
    """O8: pii=true olan data_class content_class olarak işaretli (platform deny-by-default kapsamı)."""
    if dc.get("pii"):
        return dc.get("content_class") is True
    return True


# --------------------------------------------------------------------------- #
# access-decision simülatörü (bucket-policy + IAM + altın kural mantığı)
# --------------------------------------------------------------------------- #
def decide_access(req, data_classes=None):
    """
    İstek alanları:
      realm: 'tenant' | 'platform'
      principal_tenant: <tenant_id>      (realm=tenant için)
      bucket_tenant: <tenant_id>         (bucket'ın bağlı olduğu tenant)
      action: 'Get' | 'Put' | 'Delete' | 'List'
      tls: bool
      sse_kms_key / bucket_cmk: Put için şifreleme anahtarı eşleşmesi
      key: obje anahtarı (data_class çıkarımı)
      data_class: opsiyonel (yoksa key prefix'inden)
      break_glass: bool (platform Tier B)
      object_locked: bool (object-lock/legal-hold aktif)
    Dönüş: (decision 'ALLOW'/'DENY', reason)
    """
    dcs = data_classes if data_classes is not None else load_spec()["data_classes"]
    action = req.get("action")
    key = req.get("key", "")
    data_class = req.get("data_class")
    if data_class is None:
        for dc in dcs:
            if key.startswith(dc["prefix"]):
                data_class = dc["id"]
                break

    # O3 — TLS-only
    if not req.get("tls", False):
        return "DENY", "O3: TLS olmayan istek (aws:SecureTransport=false)"

    # O2 — Put yalnız tenant CMK ile
    if action == "Put":
        if req.get("sse_kms_key") != req.get("bucket_cmk"):
            return "DENY", "O2: SSE-KMS eksik/yanlış CMK (tenant.kms_key_ref değil)"

    # O5/O1 — cross-tenant erişim reddi
    if req.get("realm") == "tenant":
        if req.get("principal_tenant") != req.get("bucket_tenant"):
            return "DENY", "O5: cross-tenant erişim (principal_tenant != bucket_tenant; FR-TEN-002)"
        # O8/O10 — runtime content silmez
        if action == "Delete":
            return "DENY", "O8: tenant runtime obje silemez (silme = retention motoru + crypto-shred)"
        return "ALLOW", "tenant kendi bucket'ında izinli işlem"

    # realm == platform — altın kural (FR-IAM-008)
    if req.get("realm") == "platform":
        is_content = data_class in CONTENT_CLASSES
        if is_content and not req.get("break_glass", False):
            return "DENY", "O5/O8: platform realm content sınıfını break-glass'sız göremez (altın kural FR-IAM-008)"
        if req.get("break_glass", False):
            # Tier B salt-okunur
            if action in ("Put", "Delete"):
                return "DENY", "FR-IAM-009: break-glass SALT-OKUNUR (Put/Delete yok)"
            if req.get("object_locked") and action == "Delete":
                return "DENY", "O10: object-lock/legal-hold silme reddi (FR-REC-007)"
            return "ALLOW", "platform break-glass Tier B salt-okunur erişim (audit'li)"
        # content olmayan (metrik/kaynak) → platform görebilir
        return "ALLOW", "platform metrik/kaynak verisi (content değil)"

    return "DENY", "tanımsız realm"


# --------------------------------------------------------------------------- #
# lifecycle simülatörü
# --------------------------------------------------------------------------- #
def lifecycle_action(dc, age_days, legal_hold=False):
    """
    data_class + obje yaşı (gün) + legal_hold → eylem:
      'retained'         legal-hold/object-lock → expire'dan muaf (FR-REC-007)
      'expire-shred'     yaş >= expire_days → lifecycle expire + crypto-shred (FR-REC-010)
      'transition'       yaş >= transition_days → soğuk katman
      'none'             henüz eylem yok
    """
    expire = dc.get("expire_days")
    transition = dc.get("transition_days")
    if expire is not None and age_days >= expire:
        if legal_hold and dc.get("legal_hold_capable"):
            return "retained"
        return "expire-shred"
    if transition is not None and age_days >= transition:
        return "transition"
    return "none"


# --------------------------------------------------------------------------- #
# validate
# --------------------------------------------------------------------------- #
def validate(spec=None, verbose=True):
    if spec is None:
        spec = load_spec()
    checks = []

    def chk(ok, label):
        checks.append((bool(ok), label))

    dcs = spec.get("data_classes", [])
    strat = spec.get("bucket_strategy", {})
    enc = spec.get("encryption", {})

    # O1 — bucket stratejisi
    chk(strat.get("model") == "per-tenant-per-region", "O1 bucket modeli per-tenant-per-region")
    chk("home_region" in strat.get("region_binding", "") or "home-region" in strat.get("region_binding", ""),
        "O1 residency home-region (region_binding)")
    chk("<data_class>" in strat.get("key_layout", ""), "O6 key_layout data_class prefix taşır")
    chk("object_id" in strat.get("key_layout", "") or "<object_id>" in strat.get("key_layout", ""),
        "O6 key_layout object_id (ham PII değil)")

    # O2 — şifreleme
    chk("SSE-KMS" in enc.get("at_rest", ""), "O2 at-rest SSE-KMS")
    chk("tenant" in enc.get("at_rest", "").lower(), "O2 tenant başına CMK")
    chk("TLS" in enc.get("in_transit", ""), "O3 in-transit TLS")
    chk("crypto" in enc.get("crypto_shredding", "").lower(), "O9 crypto-shredding tanımlı")

    # data_class invariant'ları
    ids = {dc["id"] for dc in dcs}
    chk(len(dcs) >= 5, "data_class sayısı >= 5")
    for need in ("recording", "transcript", "kb_document", "tts_cache", "export"):
        chk(need in ids, f"data_class '{need}' tanımlı")
    for dc in dcs:
        i = dc.get("id", "?")
        chk(key_has_dataclass_prefix(dc.get("prefix", ""), dcs), f"[{i}] O6 prefix tanınır")
        chk(key_no_raw_pii(dc.get("prefix", "")), f"[{i}] O6 prefix ham PII içermez")
        chk(lifecycle_complete(dc), f"[{i}] O7 lifecycle kuralı (transition/expire) var")
        chk(content_class_locked(dc), f"[{i}] O10 legal-hold sınıfı versioning+object-lock")
        chk(pii_is_content(dc), f"[{i}] O8 pii→content_class")
        chk(bool(dc.get("fr")), f"[{i}] FR izlenebilirlik mevcut")

    # Politika şablonları (O2/O3/O4/O5/O7/O10/O11)
    pol = spec.get("policy_templates", {})
    bp_path = os.path.join(HERE, pol.get("bucket_policy", ""))
    if os.path.isfile(bp_path):
        bp = load_json(bp_path)
        sids = _sids(bp)
        chk("DenyInsecureTransport" in sids, "O3 bucket-policy DenyInsecureTransport")
        chk("DenyUnEncryptedObjectUploads" in sids, "O2 bucket-policy DenyUnEncryptedObjectUploads")
        chk("DenyWrongKMSKey" in sids, "O2 bucket-policy DenyWrongKMSKey")
        chk("DenyNonTenantPrincipal" in sids, "O5 bucket-policy DenyNonTenantPrincipal")
        chk("DenyObjectLockBypass" in sids, "O10 bucket-policy DenyObjectLockBypass")
        chk(not has_literal_secret(bp_path), "O11 bucket-policy literal sır içermez")
    else:
        chk(False, "bucket-policy şablonu mevcut")

    pab_path = os.path.join(HERE, pol.get("public_access_block", ""))
    if os.path.isfile(pab_path):
        pab = load_json(pab_path)
        chk(all(pab.get(k) is True for k in
                ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets")),
            "O4 public-access-block dört bayrak da true")
    else:
        chk(False, "public-access-block şablonu mevcut")

    lc_path = os.path.join(HERE, pol.get("lifecycle", ""))
    if os.path.isfile(lc_path):
        lc = load_json(lc_path)
        rule_prefixes = {r.get("Filter", {}).get("Prefix") for r in lc.get("Rules", [])}
        for dc in dcs:
            chk(dc.get("prefix") in rule_prefixes, f"O7 lifecycle kuralı '{dc['id']}' prefix'i kapsar")
    else:
        chk(False, "lifecycle şablonu mevcut")

    iam_path = os.path.join(HERE, pol.get("iam_tenant_prefix_policy", ""))
    if os.path.isfile(iam_path):
        iam = load_json(iam_path)
        sids = _sids(iam)
        chk("TenantBucketRW" in sids, "O5 IAM TenantBucketRW (yalnız kendi bucket)")
        chk("TenantCmkUseOnly" in sids, "O2 IAM TenantCmkUseOnly (yalnız tenant CMK)")
        txt = json.dumps(iam)
        chk("${BUCKET}" in txt, "O5 IAM yalnız ${BUCKET} kaynağı (cross-tenant yok)")
        chk(not has_literal_secret(iam_path), "O11 IAM literal sır içermez")
    else:
        chk(False, "IAM prefix policy şablonu mevcut")

    ol_path = os.path.join(HERE, pol.get("object_lock_config", ""))
    if os.path.isfile(ol_path):
        ol = load_json(ol_path)
        chk(ol.get("ObjectLockEnabled") == "Enabled", "O10 object-lock config Enabled")
        chk(ol.get("Rule", {}).get("DefaultRetention", {}).get("Mode") == "GOVERNANCE",
            "O10 object-lock GOVERNANCE retention")
    else:
        chk(False, "object-lock config şablonu mevcut")

    # invariant listesi mevcut
    chk(len(spec.get("invariants", [])) >= 11, "O1..O11 invariant listesi mevcut (>=11)")

    passed = sum(1 for ok, _ in checks if ok)
    total = len(checks)
    if verbose:
        for ok, label in checks:
            print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        print(f"\nvalidate: {passed}/{total} kontrol geçti")
    return passed, total, checks


# --------------------------------------------------------------------------- #
# selftest
# --------------------------------------------------------------------------- #
def selftest(verbose=True):
    spec = load_spec()
    dcs = spec["data_classes"]
    rec = next(d for d in dcs if d["id"] == "recording")
    tts = next(d for d in dcs if d["id"] == "tts_cache")
    results = []

    def expect(name, cond):
        results.append((name, bool(cond)))

    # O6 anahtar predikatları
    expect("O6 tanınan prefix geçer", key_has_dataclass_prefix("recording/2026/06/13/x", dcs))
    expect("O6 tanınmayan prefix reddedilir", not key_has_dataclass_prefix("random/x", dcs))
    expect("O6 ham PII token reddedilir", not key_no_raw_pii("recording/<phone>/x"))
    expect("O6 temiz anahtar geçer", key_no_raw_pii("recording/2026/06/13/uuid"))

    # O7/O10/O8 data_class predikatları
    expect("O7 recording lifecycle tam", lifecycle_complete(rec))
    expect("O7 lifecycle'sız reddedilir",
           not lifecycle_complete({"transition_days": None, "expire_days": None}))
    expect("O10 recording versioning+lock", content_class_locked(rec))
    expect("O10 legal-hold lock'suz reddedilir",
           not content_class_locked({"legal_hold_capable": True, "versioning": False, "object_lock": "none"}))
    expect("O10 cache lock gerekmez", content_class_locked(tts))
    expect("O8 pii content olmalı", pii_is_content(rec))
    expect("O8 pii non-content reddedilir",
           not pii_is_content({"pii": True, "content_class": False}))

    # access-decision simülatörü
    base = {"realm": "tenant", "principal_tenant": "T1", "bucket_tenant": "T1",
            "tls": True, "key": "recording/2026/06/13/o", "data_class": "recording"}
    expect("decide: tenant kendi bucket Get ALLOW", decide_access({**base, "action": "Get"}, dcs)[0] == "ALLOW")
    expect("decide: cross-tenant DENY",
           decide_access({**base, "action": "Get", "bucket_tenant": "T2"}, dcs)[0] == "DENY")
    expect("decide: TLS yok DENY", decide_access({**base, "action": "Get", "tls": False}, dcs)[0] == "DENY")
    expect("decide: Put doğru CMK ALLOW",
           decide_access({**base, "action": "Put", "sse_kms_key": "K1", "bucket_cmk": "K1"}, dcs)[0] == "ALLOW")
    expect("decide: Put yanlış CMK DENY",
           decide_access({**base, "action": "Put", "sse_kms_key": "KX", "bucket_cmk": "K1"}, dcs)[0] == "DENY")
    expect("decide: Put şifresiz DENY",
           decide_access({**base, "action": "Put", "bucket_cmk": "K1"}, dcs)[0] == "DENY")
    expect("decide: tenant runtime Delete DENY", decide_access({**base, "action": "Delete"}, dcs)[0] == "DENY")
    # platform altın kural
    plat = {"realm": "platform", "bucket_tenant": "T1", "tls": True,
            "key": "transcript/2026/06/13/o", "data_class": "transcript"}
    expect("decide: platform content break-glass'sız DENY",
           decide_access({**plat, "action": "Get"}, dcs)[0] == "DENY")
    expect("decide: platform break-glass salt-okunur ALLOW",
           decide_access({**plat, "action": "Get", "break_glass": True}, dcs)[0] == "ALLOW")
    expect("decide: platform break-glass Put DENY",
           decide_access({**plat, "action": "Put", "break_glass": True, "sse_kms_key": "K1", "bucket_cmk": "K1"}, dcs)[0] == "DENY")
    expect("decide: platform metrik (non-content) ALLOW",
           decide_access({"realm": "platform", "bucket_tenant": "T1", "tls": True,
                          "key": "tts-cache/o", "data_class": "tts_cache", "action": "Get"}, dcs)[0] == "ALLOW")

    # lifecycle simülatörü
    expect("lifecycle: recording 10g none", lifecycle_action(rec, 10) == "none")
    expect("lifecycle: recording 40g transition", lifecycle_action(rec, 40) == "transition")
    expect("lifecycle: recording 400g expire-shred", lifecycle_action(rec, 400) == "expire-shred")
    expect("lifecycle: recording 400g legal-hold retained", lifecycle_action(rec, 400, legal_hold=True) == "retained")
    expect("lifecycle: tts 40g expire-shred", lifecycle_action(tts, 40) == "expire-shred")
    expect("lifecycle: tts legal-hold yok → expire (capable değil)",
           lifecycle_action(tts, 40, legal_hold=True) == "expire-shred")

    # Gerçek spec validate'ten temiz geçmeli
    p, t, _ = validate(verbose=False)
    expect("gerçek storage-spec.json validate temiz", p == t and t > 0)

    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    if verbose:
        for name, ok in results:
            print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        print(f"\nselftest: {passed}/{total} predikat geçti")
    return passed, total


# --------------------------------------------------------------------------- #
# schema
# --------------------------------------------------------------------------- #
def schema():
    spec = load_spec()
    out = {
        "wbs": "1.1.6",
        "bucket_strategy": {
            "model": spec["bucket_strategy"]["model"],
            "key_layout": spec["bucket_strategy"]["key_layout"],
        },
        "encryption": {k: spec["encryption"][k] for k in ("at_rest", "in_transit") if k in spec["encryption"]},
        "data_classes": [{
            "id": d["id"], "prefix": d["prefix"], "pii": d["pii"],
            "object_lock": d["object_lock"], "transition_days": d["transition_days"],
            "expire_days": d["expire_days"],
        } for d in spec["data_classes"]],
        "invariants": spec["invariants"],
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return out


# --------------------------------------------------------------------------- #
def _read_req(argv):
    if "--json" in argv:
        return json.loads(argv[argv.index("--json") + 1])
    raise SystemExit("--json '<request>' gerekli")


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "validate"
    if cmd == "validate":
        p, t, _ = validate()
        return 0 if p == t else 1
    if cmd == "selftest":
        p, t = selftest()
        return 0 if p == t else 1
    if cmd == "schema":
        schema()
        return 0
    if cmd == "decide":
        d, reason = decide_access(_read_req(argv))
        print(json.dumps({"decision": d, "reason": reason}, ensure_ascii=False))
        return 0 if d == "ALLOW" else 1
    if cmd == "lifecycle":
        req = _read_req(argv)
        dc = next(d for d in load_spec()["data_classes"] if d["id"] == req["data_class"])
        act = lifecycle_action(dc, req["age_days"], req.get("legal_hold", False))
        print(json.dumps({"action": act}, ensure_ascii=False))
        return 0
    print(f"bilinmeyen komut: {cmd} (validate|decide|lifecycle|selftest|schema)", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
