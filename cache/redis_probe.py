#!/usr/bin/env python3
"""
redis_probe.py — WBS 1.1.5 Redis keyspace + TTL politikaları statik kapısı (stdlib-only).

`keyspace-spec.json` (source of truth) + `config/*.conf` referans konfigürasyonlarının
tasarım invariant'larını (I1..I9) kod gerektirmeden doğrular. Canlı Redis GEREKTİRMEZ
(davranış kapısı: tests/cache_behavior_test.py + run_live_test.sh).

Komutlar:
  validate   keyspace-spec + config invariant kapısı (kontrol özeti; kapı→çıkış kodu)
  selftest   gömülü iyi/bozuk fixture'larla predikat testleri (çıkış kodu)
  schema     beklenen nesneler/sözleşme özeti (JSON)

Sır/credential repoya yazılmaz; bu probe yalnız repodaki dosyaları okur.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "keyspace-spec.json")

TENANT_HASHTAG_RE = re.compile(r"^\{t:<tenant_id>\}:")
# Anahtar deseninde ham PII/serbest-metin işareti (hash'siz) — yasak bileşenler.
RAW_PII_TOKENS = ("<phone", "<msisdn", "<email", "<text>", "<name", "<query>", "<utterance")
SECRET_LITERAL_RE = re.compile(r"^(requirepass|masterauth)\s+(?!\$\{)\S", re.IGNORECASE)


# --------------------------------------------------------------------------- #
# Yardımcılar
# --------------------------------------------------------------------------- #
def load_spec(path=SPEC_PATH):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def parse_conf(path):
    """redis.conf → {directive: [values...]} (son değer kazanır da erişilebilir)."""
    directives = {}
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            parts = s.split(None, 1)
            key = parts[0].lower()
            val = parts[1] if len(parts) > 1 else ""
            directives.setdefault(key, []).append(val)
    return directives


def conf_last(directives, key):
    vals = directives.get(key.lower())
    return vals[-1] if vals else None


def has_literal_secret(path):
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            s = line.strip()
            if s.startswith("#"):
                continue
            if SECRET_LITERAL_RE.match(s):
                return True
    return False


# --------------------------------------------------------------------------- #
# Çekirdek invariant değerlendiricileri (selftest bunları doğrudan çağırır)
# --------------------------------------------------------------------------- #
def key_is_tenant_namespaced(pattern):
    """I1: anahtar deseni tenant hash-tag ile başlar."""
    return bool(TENANT_HASHTAG_RE.match(pattern))


def ttl_bounded(ks):
    """I2+I3: pozitif, sonlu TTL ve ttl<=max_ttl."""
    t = ks.get("ttl_seconds")
    m = ks.get("max_ttl_seconds")
    if not isinstance(t, int) or not isinstance(m, int):
        return False
    if t <= 0 or m <= 0:
        return False
    return t <= m


def pii_only_in_session(ks):
    """I4: cache pool keyspace'i PII taşımaz."""
    if ks.get("pool") == "cache":
        return ks.get("pii") is False
    return True  # session pool PII taşıyabilir


def eviction_class_consistent(ks):
    """I5: session=noeviction/must_not_evict/delete_on_call_end; cache=volatile-lru/evictable."""
    if ks.get("pool") == "session":
        return (
            ks.get("eviction_class") == "noeviction"
            and ks.get("must_not_evict") is True
            and ks.get("evictable") is False
            and ks.get("delete_on_call_end") is True
        )
    if ks.get("pool") == "cache":
        return (
            ks.get("eviction_class") == "volatile-lru"
            and ks.get("must_not_evict") is False
            and ks.get("evictable") is True
        )
    return False


def free_text_hashed(ks):
    """I6: serbest-metin bileşenli anahtar hash'li; desende ham PII token'ı yok."""
    pattern = ks.get("key_pattern", "")
    if any(tok in pattern for tok in RAW_PII_TOKENS):
        return False
    if ks.get("free_text_component"):
        return ks.get("free_text_hashed") is True
    return True


def residency_home_region(ks):
    """I7."""
    return ks.get("residency") == "home-region"


# --------------------------------------------------------------------------- #
# validate
# --------------------------------------------------------------------------- #
def validate(spec=None, verbose=True):
    if spec is None:
        spec = load_spec()
    checks = []  # (ok, etiket)

    def chk(ok, label):
        checks.append((bool(ok), label))

    pools = spec.get("pools", {})
    keyspaces = spec.get("keyspaces", [])

    chk(len(keyspaces) >= 4, "keyspace sayısı >= 4 (session_state/summary + semantic + tts)")
    pool_ids = set(pools.keys())
    chk(pool_ids == {"session", "cache"}, "pool kümesi == {session, cache}")

    # Pool config dosyaları + maxmemory-policy tutarlılığı (I8, I9)
    conf_cache = {}
    for pid, pool in pools.items():
        cf = os.path.join(HERE, pool.get("config_file", ""))
        exists = os.path.isfile(cf)
        chk(exists, f"pool '{pid}' config_file mevcut ({pool.get('config_file')})")
        if not exists:
            continue
        d = parse_conf(cf)
        conf_cache[pid] = d
        chk(
            conf_last(d, "maxmemory-policy") == pool.get("maxmemory_policy"),
            f"pool '{pid}' maxmemory-policy '{pool.get('maxmemory_policy')}' (config ile tutarlı)",
        )
        # I9: persistence kapalı
        chk(conf_last(d, "save") == '""', f"pool '{pid}' save \"\" (persistence kapalı)")
        chk(conf_last(d, "appendonly") == "no", f"pool '{pid}' appendonly no")
        chk(conf_last(d, "protected-mode") == "yes", f"pool '{pid}' protected-mode yes")
        chk(not has_literal_secret(cf), f"pool '{pid}' config literal sır içermiyor")

    # ACL örneği literal sır içermez
    acl = os.path.join(HERE, "config", "users.acl.example")
    if os.path.isfile(acl):
        with open(acl, encoding="utf-8") as fh:
            acl_txt = fh.read()
        chk(">${" in acl_txt, "ACL örneği parolaları ${ENV} placeholder ile (literal değil)")
        chk("user default off" in acl_txt, "ACL örneği default kullanıcıyı kapatır")

    # Keyspace invariant'ları (I1..I7)
    for ks in keyspaces:
        kid = ks.get("id", "?")
        chk(ks.get("pool") in pool_ids, f"[{kid}] pool tanımlı ({ks.get('pool')})")
        chk(key_is_tenant_namespaced(ks.get("key_pattern", "")), f"[{kid}] I1 tenant hash-tag prefix")
        chk(ttl_bounded(ks), f"[{kid}] I2/I3 TTL pozitif+sonlu+(ttl<=max)")
        chk(pii_only_in_session(ks), f"[{kid}] I4 PII yalnız session pool'da")
        chk(eviction_class_consistent(ks), f"[{kid}] I5 eviction sınıfı pool ile tutarlı")
        chk(free_text_hashed(ks), f"[{kid}] I6 serbest-metin hash'li / ham PII yok")
        chk(residency_home_region(ks), f"[{kid}] I7 residency=home-region")
        chk(bool(ks.get("fr")), f"[{kid}] FR izlenebilirlik mevcut")

    # Beklenen keyspace id'leri kapsanmış
    ids = {k.get("id") for k in keyspaces}
    for need in ("session_state", "session_summary", "semantic_cache", "tts_cache_index"):
        chk(need in ids, f"keyspace '{need}' tanımlı")

    passed = sum(1 for ok, _ in checks if ok)
    total = len(checks)
    if verbose:
        for ok, label in checks:
            print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        print(f"\nvalidate: {passed}/{total} kontrol geçti")
    return passed, total, checks


# --------------------------------------------------------------------------- #
# selftest — iyi/bozuk fixture predikatları
# --------------------------------------------------------------------------- #
def _good_session_ks():
    return {
        "id": "session_state", "pool": "session",
        "key_pattern": "{t:<tenant_id>}:sess:<call_id>:state",
        "ttl_seconds": 1800, "max_ttl_seconds": 14400, "pii": True,
        "eviction_class": "noeviction", "must_not_evict": True, "evictable": False,
        "delete_on_call_end": True, "free_text_component": False, "residency": "home-region",
    }


def _good_cache_ks():
    return {
        "id": "semantic_cache", "pool": "cache",
        "key_pattern": "{t:<tenant_id>}:sem:<agent_id>:<intent_or_embedding_hash>",
        "ttl_seconds": 86400, "max_ttl_seconds": 86400, "pii": False,
        "eviction_class": "volatile-lru", "must_not_evict": False, "evictable": True,
        "delete_on_call_end": False, "free_text_component": True, "free_text_hashed": True,
        "residency": "home-region",
    }


def selftest(verbose=True):
    results = []

    def expect(name, cond):
        results.append((name, bool(cond)))

    g_sess, g_cache = _good_session_ks(), _good_cache_ks()

    # I1 tenant namespace
    expect("I1 iyi session anahtarı namespaced", key_is_tenant_namespaced(g_sess["key_pattern"]))
    expect("I1 prefix'siz anahtar reddedilir", not key_is_tenant_namespaced("sess:<call_id>:state"))
    expect("I1 yanlış prefix reddedilir", not key_is_tenant_namespaced("<tenant_id>:sess:x"))

    # I2/I3 TTL sınırları
    expect("I2 iyi TTL geçer", ttl_bounded(g_cache))
    expect("I2 sonsuz/-1 TTL reddedilir", not ttl_bounded({**g_cache, "ttl_seconds": -1, "max_ttl_seconds": -1}))
    expect("I2 sıfır TTL reddedilir", not ttl_bounded({**g_cache, "ttl_seconds": 0}))
    expect("I3 ttl>max reddedilir", not ttl_bounded({**g_cache, "ttl_seconds": 99999, "max_ttl_seconds": 100}))
    expect("I2 string TTL reddedilir", not ttl_bounded({**g_cache, "ttl_seconds": "86400"}))

    # I4 PII yalnız session
    expect("I4 cache pii=false geçer", pii_only_in_session(g_cache))
    expect("I4 cache pii=true reddedilir", not pii_only_in_session({**g_cache, "pii": True}))
    expect("I4 session pii=true geçer", pii_only_in_session(g_sess))

    # I5 eviction sınıfı
    expect("I5 iyi session geçer", eviction_class_consistent(g_sess))
    expect("I5 iyi cache geçer", eviction_class_consistent(g_cache))
    expect("I5 session evictable reddedilir",
           not eviction_class_consistent({**g_sess, "evictable": True, "eviction_class": "volatile-lru"}))
    expect("I5 session delete_on_call_end yoksa reddedilir",
           not eviction_class_consistent({**g_sess, "delete_on_call_end": False}))
    expect("I5 cache noeviction reddedilir",
           not eviction_class_consistent({**g_cache, "eviction_class": "noeviction"}))

    # I6 serbest-metin hash
    expect("I6 hash'li cache anahtarı geçer", free_text_hashed(g_cache))
    expect("I6 hash'siz serbest-metin reddedilir", not free_text_hashed({**g_cache, "free_text_hashed": False}))
    expect("I6 ham PII token'lı desen reddedilir",
           not free_text_hashed({**g_cache, "key_pattern": "{t:<tenant_id>}:sem:<phone>"}))
    expect("I6 serbest-metinsiz session geçer", free_text_hashed(g_sess))

    # I7 residency
    expect("I7 home-region geçer", residency_home_region(g_cache))
    expect("I7 yanlış bölge reddedilir", not residency_home_region({**g_cache, "residency": "us-east"}))

    # Gerçek spec dosyası validate'ten temiz geçmeli
    p, t, _ = validate(verbose=False)
    expect("gerçek keyspace-spec.json validate temiz", p == t and t > 0)

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
        "wbs": "1.1.5",
        "pools": {pid: {
            "maxmemory_policy": p["maxmemory_policy"],
            "persistence": p["persistence"],
            "config_file": p["config_file"],
        } for pid, p in spec["pools"].items()},
        "keyspaces": [{
            "id": k["id"], "pool": k["pool"], "key_pattern": k["key_pattern"],
            "ttl_seconds": k["ttl_seconds"], "max_ttl_seconds": k["max_ttl_seconds"],
            "pii": k["pii"], "eviction_class": k["eviction_class"],
        } for k in spec["keyspaces"]],
        "invariants": spec["invariants"],
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return out


# --------------------------------------------------------------------------- #
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
    print(f"bilinmeyen komut: {cmd} (validate|selftest|schema)", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
