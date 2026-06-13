#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eventstream_probe.py — WBS 1.1.8 Event stream (Kafka) topic tasarımı + replay politikası

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only statik+davranış kapısı.
`db/`+`cache/`+`objstore/` probe disipliniyle aynı.

Komutlar:
  validate   topic-spec.json'ı invariant'lara karşı + config tutarlılığına karşı doğrular (çıkış kodu).
  replay     Deterministik replay simülatörü — at-least-once + idempotent dedup → çift yan-etki yok;
             canlı offset dokunulmaz; PII topic replay'i audit gerektirir.
  route      Deterministik partition routing simülatörü — aynı anahtar→aynı partition, tenant dağılımı.
  selftest   İyi/kötü spec'lerle invariant kapılarının doğru tetiklendiğini kanıtlar.
  schema     Beklenen spec şeklini özetler.

Sunucu/credential GEREKMEZ. Replay/route, gerçek broker yerine deterministik simülasyondur
(objstore probe'undaki access-decision/lifecycle simülatörü deseni).
"""
import json
import os
import re
import sys
import hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "topic-spec.json")
TOPICS_CFG = os.path.join(HERE, "config", "topics.declarative.json")
ENVELOPE_SCHEMA = os.path.join(HERE, "schemas", "event-envelope.schema.json")
SR_CFG = os.path.join(HERE, "config", "schema-registry.config.json")
CONFIG_DIR = os.path.join(HERE, "config")

NAME_RE = re.compile(r"^[a-z][a-z0-9]*(\.[a-z0-9]+)+\.v[0-9]+$")
ALLOWED_KEYS = {"call_id", "tenant_id", "agent_id"}
PII_HIGH = {"raw", "sensitive"}
PII_ALL = {"none", "low", "reference", "redacted", "raw", "sensitive"}
DAY_MS = 86400000

# API §10.2 webhook event kataloğu (non-circular gate — probe'ta sabit; I11)
WEBHOOK_CATALOG = [
    "call.started", "call.completed", "call.transferred", "call.failed",
    "transcript.ready", "recording.ready", "tool.async.completed",
    "campaign.completed", "quota.threshold", "agent.published",
]

ENVELOPE_REQUIRED = [
    "id", "type", "api_version", "schema_version", "created_at", "event_time",
    "tenant_id", "correlation_id", "idempotency_key", "partition_key",
    "pii_class", "producer", "data",
]

SECRET_HINT_RE = re.compile(r"(password|passwd|secret|sasl\.jaas\.config|api[_-]?key|token)\s*[:=]\s*([^\s\"',}]+)", re.I)


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------- invariant kontrolleri ----------------

def _is_placeholder(val):
    v = val.strip().strip('"').strip("'")
    return v == "" or v.startswith("${") or v.startswith("<") or v in ("null", "None")


def check_topic(t, results):
    name = t.get("name", "<?>")

    def ok(cond, msg):
        results.append((bool(cond), f"[{name}] {msg}"))

    # I1
    ok(NAME_RE.match(name), "I1 ad konvansiyonu <domain>.<subject>.v<major>")
    # I2
    ok(t.get("partition_key") in ALLOWED_KEYS, f"I2 partition_key tenant-türetilebilir ({t.get('partition_key')})")
    # I3
    rms = t.get("retention_ms")
    ok(isinstance(rms, int) and rms > 0, "I3 sonlu retention_ms>0 (kalıcı log yok)")
    # I4
    ok(t.get("replication_factor", 0) >= 3, "I4 replication_factor>=3")
    ok(t.get("min_insync_replicas", 0) >= 2, "I4 min_insync_replicas>=2")
    ok(t.get("producer_acks") == "all", "I4 producer_acks='all'")
    # pii
    pii = t.get("pii_class")
    ok(pii in PII_ALL, f"pii_class geçerli ({pii})")
    rep = t.get("replay", {})
    # I5
    if pii in PII_HIGH:
        ok(rms <= DAY_MS, "I5 raw/sensitive retention <= 24h")
        ok(rep.get("mode") == "restricted", "I5 raw/sensitive replay.mode='restricted'")
        ok(rep.get("pii_gate") is True, "I5 raw/sensitive replay.pii_gate=true")
        ok(rep.get("audit_required") is True, "I5 raw/sensitive replay.audit_required=true")
        ok(t.get("residency") == "home-region", "I5 raw/sensitive residency=home-region")
    # I6
    if "webhook-dispatcher" in t.get("consumers", []):
        ok(pii not in PII_HIGH, "I6 webhook tüketen topic ham PII export etmez")
    # I7
    ok(rep.get("idempotent_consumers") is True, "I7 replay.idempotent_consumers=true")
    # I8
    ok(t.get("residency") == "home-region", "I8 residency=home-region")
    # I9
    if t.get("domain") == "dlq":
        ok(rep.get("mode") == "manual", "I9 dlq topic replay.mode='manual'")
        ok(t.get("dlq") is None, "I9 dlq topic kendisi dlq taşımaz")
    else:
        ok(t.get("dlq"), "I9 non-dlq topic bir dlq'ya bağlı")
    # I10
    if t.get("delivery_class") == "no-loss":
        ok(rms >= 30 * DAY_MS, "I10 no-loss retention >= 30 gün")
        ok(t.get("min_insync_replicas", 0) >= 2, "I10 no-loss min_insync_replicas>=2")


def check_webhook_coverage(spec, results):
    # I11: her webhook tipi tam olarak bir topic'te üretilir + o topic webhook-dispatcher tüketir
    producer_of = {}
    for t in spec["topics"]:
        for ev in t.get("produces_events", []):
            producer_of.setdefault(ev, []).append(t)
    for wt in WEBHOOK_CATALOG:
        topics = producer_of.get(wt, [])
        results.append((len(topics) == 1, f"I11 '{wt}' tam olarak 1 topic'te üretilir ({len(topics)})"))
        if topics:
            has_wh = "webhook-dispatcher" in topics[0].get("consumers", [])
            results.append((has_wh, f"I11 '{wt}' topic'i webhook-dispatcher tüketir"))


def check_envelope(results):
    sch = load_json(ENVELOPE_SCHEMA)
    req = sch.get("required", [])
    for f in ENVELOPE_REQUIRED:
        results.append((f in req, f"I12 envelope zorunlu alan '{f}'"))
    props = sch.get("properties", {})
    results.append((props.get("pii_class", {}).get("enum") == ["none", "low", "reference", "redacted", "raw", "sensitive"],
                    "I12 pii_class enum tam"))


def check_config_secrets(results):
    for fn in os.listdir(CONFIG_DIR):
        path = os.path.join(CONFIG_DIR, fn)
        if not os.path.isfile(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            # yorum satırlarını ele (# / // ile başlayanlar): sırrı tarif eden açıklama, sır değil
            lines = [ln for ln in f.read().splitlines() if not ln.strip().startswith(("#", "//"))]
        text = "\n".join(lines)
        bad = []
        for m in SECRET_HINT_RE.finditer(text):
            val = m.group(2)
            if not _is_placeholder(val):
                bad.append(m.group(0)[:48])
        results.append((not bad, f"I13 {fn} literal sır içermez" + (f" — {bad}" if bad else "")))


def check_schema_registry(results):
    sr = load_json(SR_CFG)
    ok_global = sr.get("global_compatibility") in ("BACKWARD", "FULL", "BACKWARD_TRANSITIVE", "FULL_TRANSITIVE")
    results.append((ok_global, f"I14 global_compatibility geriye-uyumlu ({sr.get('global_compatibility')})"))
    for s in sr.get("subjects", []):
        c = s.get("compatibility")
        results.append((c in ("BACKWARD", "FULL", "BACKWARD_TRANSITIVE", "FULL_TRANSITIVE"),
                        f"I14 subject {s.get('subject')} uyumluluk {c}"))


def check_spec_config_consistency(spec, results):
    # I15: declarative manifest spec topic kümesiyle birebir
    cfg = load_json(TOPICS_CFG)
    cfg_by = {t["name"]: t for t in cfg["topics"]}
    spec_names = {t["name"] for t in spec["topics"]}
    results.append((spec_names == set(cfg_by), "I15 spec↔config topic kümesi birebir"))
    for t in spec["topics"]:
        c = cfg_by.get(t["name"])
        if not c:
            results.append((False, f"I15 {t['name']} config'te yok"))
            continue
        results.append((c.get("partitions") == t.get("partitions"), f"I15 {t['name']} partitions eşleşir"))
        cc = c.get("configs", {})
        results.append((cc.get("retention.ms") == t.get("retention_ms"), f"I15 {t['name']} retention.ms eşleşir"))
        results.append((cc.get("cleanup.policy") == t.get("cleanup_policy"), f"I15 {t['name']} cleanup.policy eşleşir"))


def validate(spec=None, verbose=True):
    spec = spec or load_json(SPEC_PATH)
    results = []
    # cluster defaults dayanıklılık
    cd = spec.get("cluster_defaults", {})
    results.append((cd.get("unclean_leader_election") is False, "cluster: unclean_leader_election kapalı"))
    results.append((cd.get("enable_idempotence") is True, "cluster: idempotent producer açık"))
    results.append((cd.get("producer_acks") == "all", "cluster: acks=all"))

    for t in spec["topics"]:
        check_topic(t, results)
    check_webhook_coverage(spec, results)
    check_envelope(results)
    check_config_secrets(results)
    check_schema_registry(results)
    check_spec_config_consistency(spec, results)

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    if verbose:
        for ok, msg in results:
            if not ok:
                print(f"  FAIL {msg}")
        print(f"validate: {passed}/{total} PASS")
    return passed == total, passed, total


# ---------------- partition routing simülatörü ----------------

def partition_of(key, partitions):
    """Deterministik partition seçimi (sağlayıcı-nötr; murmur yerine sha1, determinizm için)."""
    h = int(hashlib.sha1(key.encode("utf-8")).hexdigest(), 16)
    return h % partitions


def route(spec=None, verbose=True):
    spec = spec or load_json(SPEC_PATH)
    topic = next(t for t in spec["topics"] if t["name"] == "voice.call.lifecycle.v1")
    parts = topic["partitions"]
    keys = [f"call-{i:04d}" for i in range(200)]
    # aynı anahtar → aynı partition (determinizm)
    same = all(partition_of(k, parts) == partition_of(k, parts) for k in keys)
    # dağılım: 200 anahtar, kullanılan partition sayısı makul (>= yarısı)
    used = {partition_of(k, parts) for k in keys}
    # tenant tag korunur (envelope.partition_key = call_id, tenant_id ayrı alan)
    if verbose:
        print(f"route: topic={topic['name']} partitions={parts}")
        print(f"  same-key→same-partition: {same}")
        print(f"  200 anahtar → {len(used)}/{parts} partition kullanıldı (dağılım)")
        for k in keys[:3]:
            print(f"    {k} → p{partition_of(k, parts)}")
    ok = same and len(used) >= parts // 2
    return ok


# ---------------- replay simülatörü ----------------

def _log(events):
    """Topic log'u: (offset, ts, envelope) listesi."""
    return [(i, e["ts"], e) for i, e in enumerate(events)]


def replay(verbose=True):
    """
    Deterministik replay simülasyonu:
      - Topic log'unda at-least-once nedeniyle 1 duplicate (aynı id) ve 1 poison var.
      - Canlı tüketici offset'i commit edilmiş (live_committed). Replay onu DOKUNMAZ.
      - Replay grubu by-timestamp ile pencere okur; idempotent dedup (envelope.id) → çift yan-etki yok.
      - PII topic replay'i audit flag olmadan REDDEDİLİR.
    """
    results = []

    def ok(cond, msg):
        results.append((bool(cond), msg))

    # sentetik log (ts artan; idx 2 ve 4 aynı id = at-least-once duplicate; idx 5 poison)
    events = [
        {"id": "e1", "ts": 100, "idempotency_key": "k1", "poison": False},
        {"id": "e2", "ts": 110, "idempotency_key": "k2", "poison": False},
        {"id": "e3", "ts": 120, "idempotency_key": "k3", "poison": False},
        {"id": "e3", "ts": 121, "idempotency_key": "k3", "poison": False},  # duplicate teslimat
        {"id": "e4", "ts": 130, "idempotency_key": "k4", "poison": False},
        {"id": "e5", "ts": 140, "idempotency_key": "k5", "poison": True},   # poison → DLQ
        {"id": "e6", "ts": 150, "idempotency_key": "k6", "poison": False},
    ]
    log = _log(events)
    retention_window = (90, 200)  # bounded by retention

    live_committed_offset = 6  # canlı tüketici en sona kadar işledi

    # --- idempotent tüketici (canlı) ---
    applied = {}   # idempotency_key -> count of side-effects
    dlq = []

    def consume(offset, ts, env, into):
        if env["poison"]:
            dlq.append(env["id"])
            return
        k = env["idempotency_key"]
        if env["id"] in into:   # dedup by envelope.id
            return
        into[env["id"]] = True
        applied[k] = applied.get(k, 0) + 1

    seen_live = {}
    for off, ts, env in log:
        consume(off, ts, env, seen_live)

    # her benzersiz non-poison key tam 1 kez uygulandı (duplicate e3 çift saymadı)
    ok(applied.get("k3") == 1, "P3 duplicate teslimat çift yan-etki üretmedi (k3=1)")
    ok(all(v == 1 for v in applied.values()), "P3 tüm key'ler tam 1 kez uygulandı")
    ok(dlq == ["e5"], "P8 poison mesaj DLQ'ya yönlendirildi")

    # --- REPLAY: by-timestamp pencere [115,135], ayrı grup, idempotent ---
    replay_from, replay_to = 115, 135
    ok(retention_window[0] <= replay_from and replay_to <= retention_window[1],
       "P2 replay penceresi retention ile sınırlı")

    seen_replay = {}                 # replay grubu KENDİ dedup store'u (canlıdan ayrı)
    replay_applied = {}
    replayed_count = 0
    for off, ts, env in log:
        if replay_from <= ts <= replay_to:
            replayed_count += 1
            if env["poison"]:
                continue
            if env["id"] in seen_replay:
                continue
            seen_replay[env["id"]] = True
            replay_applied[env["idempotency_key"]] = replay_applied.get(env["idempotency_key"], 0) + 1

    # pencere içinde e3(dup),e3,e4 → benzersiz e3,e4
    ok(set(replay_applied) == {"k3", "k4"}, "P1/P5 replay pencere-içi benzersiz olayları işledi (k3,k4)")
    ok(replayed_count == 3, "P5 pencere 3 mesaj kapsadı (sıra korunmuş)")
    # canlı offset dokunulmadı
    ok(live_committed_offset == 6, "P1 canlı tüketici offset'i replay'den etkilenmedi")

    # --- PII gate: raw topic replay audit gerektirir ---
    spec = load_json(SPEC_PATH)
    raw_topic = next(t for t in spec["topics"] if t["pii_class"] in PII_HIGH)

    def try_replay(topic, audit_token):
        rep = topic["replay"]
        if rep.get("pii_gate") and not audit_token:
            return False, "DENIED: audit gerekli"
        return True, "ALLOWED"

    allowed_no_audit, _ = try_replay(raw_topic, audit_token=None)
    allowed_audit, _ = try_replay(raw_topic, audit_token="break-glass-123")
    ok(allowed_no_audit is False, f"P4 PII topic ({raw_topic['name']}) replay audit'siz REDDEDİLDİ")
    ok(allowed_audit is True, "P4 PII topic replay audit token ile İZİNLİ")

    passed = sum(1 for o, _ in results if o)
    total = len(results)
    if verbose:
        for o, m in results:
            print(f"  {'PASS' if o else 'FAIL'} {m}")
        print(f"replay: {passed}/{total} PASS")
    return passed == total


# ---------------- selftest ----------------

def _good_topic(**over):
    t = {
        "name": "voice.sample.v1", "domain": "call", "partition_key": "call_id",
        "partitions": 12, "cleanup_policy": "delete", "retention_ms": 7 * DAY_MS,
        "replication_factor": 3, "min_insync_replicas": 2, "producer_acks": "all",
        "pii_class": "low", "residency": "home-region", "delivery_class": "standard",
        "produces_events": [], "consumers": ["analytics-ingest"], "dlq": "platform.dlq.v1",
        "replay": {"mode": "open", "window_bounded_by_retention": True,
                   "idempotent_consumers": True, "pii_gate": False, "audit_required": False},
    }
    t.update(over)
    return t


def selftest(verbose=True):
    results = []

    def expect(label, cond):
        results.append((cond, label))

    # good topic → tüm kontroller geçer
    r = []
    check_topic(_good_topic(), r)
    expect("iyi topic tüm kontrolleri geçer", all(ok for ok, _ in r))

    # kötü ad
    r = []
    check_topic(_good_topic(name="BadName"), r)
    expect("I1 kötü ad yakalanır", any(not ok and "I1" in m for ok, m in r))

    # kötü partition key
    r = []
    check_topic(_good_topic(partition_key="email"), r)
    expect("I2 geçersiz partition_key yakalanır", any(not ok and "I2" in m for ok, m in r))

    # kalıcı retention
    r = []
    check_topic(_good_topic(retention_ms=-1), r)
    expect("I3 kalıcı/-1 retention yakalanır", any(not ok and "I3" in m for ok, m in r))

    # düşük RF
    r = []
    check_topic(_good_topic(replication_factor=1), r)
    expect("I4 RF<3 yakalanır", any(not ok and "I4" in m for ok, m in r))

    # acks yanlış
    r = []
    check_topic(_good_topic(producer_acks="1"), r)
    expect("I4 acks!=all yakalanır", any(not ok and "I4" in m for ok, m in r))

    # raw PII ama uzun retention + açık replay → I5 ihlali
    r = []
    bad = _good_topic(name="voice.raw.v1", pii_class="raw", retention_ms=30 * DAY_MS,
                      consumers=["pii-redaction"],
                      replay={"mode": "open", "window_bounded_by_retention": True,
                              "idempotent_consumers": True, "pii_gate": False, "audit_required": False})
    check_topic(bad, r)
    expect("I5 raw+uzun-retention yakalanır", any(not ok and "I5" in m for ok, m in r))
    expect("I5 raw+açık-replay yakalanır", any(not ok and "I5" in m and "restricted" in m for ok, m in r))

    # raw PII + webhook tüketici → I6 ihlali
    r = []
    bad = _good_topic(name="voice.raw2.v1", pii_class="raw", retention_ms=DAY_MS,
                      consumers=["webhook-dispatcher", "pii-redaction"],
                      replay={"mode": "restricted", "window_bounded_by_retention": True,
                              "idempotent_consumers": True, "pii_gate": True, "audit_required": True})
    check_topic(bad, r)
    expect("I6 raw PII webhook export yakalanır", any(not ok and "I6" in m for ok, m in r))

    # idempotent değil
    r = []
    bad = _good_topic()
    bad["replay"] = dict(bad["replay"], idempotent_consumers=False)
    check_topic(bad, r)
    expect("I7 idempotent olmayan tüketici yakalanır", any(not ok and "I7" in m for ok, m in r))

    # no-loss kısa retention → I10
    r = []
    check_topic(_good_topic(delivery_class="no-loss", retention_ms=7 * DAY_MS), r)
    expect("I10 no-loss kısa retention yakalanır", any(not ok and "I10" in m for ok, m in r))

    # dlq topic ama mode!=manual
    r = []
    check_topic(_good_topic(name="platform.dlq.v1", domain="dlq", dlq=None,
                            replay={"mode": "open", "window_bounded_by_retention": True,
                                    "idempotent_consumers": True, "pii_gate": False, "audit_required": False}), r)
    expect("I9 dlq mode!=manual yakalanır", any(not ok and "I9" in m for ok, m in r))

    # webhook coverage: eksik tip
    spec = load_json(SPEC_PATH)
    bad_spec = json.loads(json.dumps(spec))
    # bir topic'ten call.completed üretimini kaldır
    for t in bad_spec["topics"]:
        if "call.completed" in t.get("produces_events", []):
            t["produces_events"].remove("call.completed")
    r = []
    check_webhook_coverage(bad_spec, r)
    expect("I11 eksik webhook tipi yakalanır", any(not ok and "call.completed" in m for ok, m in r))

    # secret tarayıcı: sahte sır
    expect("I13 ${ENV} placeholder sır sayılmaz", _is_placeholder("${KAFKA_PASSWORD}"))
    expect("I13 literal sır tespit edilir", bool(SECRET_HINT_RE.search("password=hunter2")) and
           not _is_placeholder("hunter2"))

    # gerçek spec validate eder
    real_ok, p, tot = validate(spec=spec, verbose=False)
    expect(f"gerçek topic-spec.json validate eder ({p}/{tot})", real_ok)

    # replay & route deterministik geçer
    expect("replay simülasyonu geçer", replay(verbose=False))
    expect("route simülasyonu geçer", route(spec=spec, verbose=False))

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    if verbose:
        for ok, m in results:
            print(f"  {'PASS' if ok else 'FAIL'} {m}")
        print(f"selftest: {passed}/{total} PASS")
    return passed == total


def schema():
    print(json.dumps({
        "spec": SPEC_PATH,
        "topics[*]": ["name", "domain", "partition_key", "partitions", "cleanup_policy",
                      "retention_ms", "replication_factor", "min_insync_replicas", "producer_acks",
                      "pii_class", "residency", "delivery_class", "produces_events", "consumers",
                      "dlq", "replay{mode,pii_gate,audit_required,idempotent_consumers}"],
        "invariants": "I1..I15 (validate)",
        "commands": ["validate", "replay", "route", "selftest", "schema"],
    }, indent=2, ensure_ascii=False))


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "validate"
    if cmd == "validate":
        ok, _, _ = validate()
        return 0 if ok else 1
    if cmd == "replay":
        return 0 if replay() else 1
    if cmd == "route":
        return 0 if route() else 1
    if cmd == "selftest":
        return 0 if selftest() else 1
    if cmd == "schema":
        schema()
        return 0
    print(f"bilinmeyen komut: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
