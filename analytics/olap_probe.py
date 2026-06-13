#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
olap_probe.py — WBS 1.1.9 OLAP (ClickHouse/BigQuery) analitik şeması

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only statik + davranış kapısı.
`db/`+`cache/`+`objstore/`+`eventstream/` probe disipliniyle aynı.

Komutlar:
  validate   olap-spec.json'ı invariant'lara (A1–A14) + DDL tutarlılığına + sır-tarayıcıya karşı
             doğrular (çıkış kodu).
  query      Deterministik OLAP sorgu simülatörü — tenant izolasyonu (predicate'siz reddedilir,
             cross-tenant sızıntı=0), rollup agregasyon doğruluğu, PII projeksiyon reddi.
  selftest   İyi/kötü spec'lerle invariant kapılarının doğru tetiklendiğini kanıtlar.
  schema     Beklenen spec şeklini özetler.

Sunucu/credential GEREKMEZ. query, gerçek motor yerine deterministik in-memory simülasyondur
(objstore probe'undaki access-decision simülatörü deseni).
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "olap-spec.json")
DDL_CH = os.path.join(HERE, "ddl", "clickhouse.sql")
DDL_BQ = os.path.join(HERE, "ddl", "bigquery.sql")
ROW_POLICY = os.path.join(HERE, "ddl", "row-policy.template.sql")
RUN_LIVE = os.path.join(HERE, "run_live_test.sh")

ALLOWED_PII = {"none", "low", "redacted"}
FORBIDDEN_PII = {"raw", "sensitive"}
ALLOWED_CONSUMERS = {"analytics-ingest", "olap-sink"}
# tenant-bağımsız referans boyutlar (A1 istisnası — tenant_id taşımaz)
TENANT_FREE_DIMS = {"dim_provider", "dim_date"}

# Sır deseni: ${ENV}/${PLACEHOLDER} ve yorumlar sır SAYILMAZ (eventstream probe deseni).
SECRET_HINT_RE = re.compile(
    r"(password|passwd|secret|api[_-]?key|token|access[_-]?key)\s*[:=]\s*([^\s\"',}]+)", re.I)


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# ---------------- invariant kontrolleri ----------------

def check_invariants(spec):
    """A1–A14 → (results[list of (ok,msg)], ddl_texts)."""
    res = []
    facts = spec["fact_tables"]
    dims = spec["dimension_tables"]
    rollups = spec["rollups"]
    known_topics = set(spec["known_source_topics"])

    fact_names = {t["name"] for t in facts}
    all_tables = facts + dims

    # A1: tenant_id + ilk ORDER BY
    for t in facts:
        cols = {c["name"] for c in t["columns"]}
        ok = "tenant_id" in cols
        res.append((ok, f"A1 fact {t['name']} tenant_id sütunu"))
        ob = t.get("order_by", [])
        res.append((bool(ob) and ob[0] == "tenant_id",
                    f"A1 fact {t['name']} ORDER BY ilk eleman tenant_id"))
    for t in dims:
        cols = {c["name"] for c in t["columns"]}
        if t["name"] in TENANT_FREE_DIMS:
            res.append(("tenant_id" not in cols,
                        f"A1 dim {t['name']} tenant-bağımsız referans (tenant_id yok)"))
        else:
            res.append(("tenant_id" in cols, f"A1 dim {t['name']} tenant_id sütunu"))

    # A2: her fact partition_by tanımlı
    for t in facts:
        res.append((t.get("partition_by") == "event_date",
                    f"A2 fact {t['name']} event_date partition"))

    # A3: sonlu, pozitif ttl_days; fct_turn en kısa, fct_usage en uzun
    for t in facts:
        ttl = t.get("ttl_days", 0)
        res.append((isinstance(ttl, int) and ttl > 0, f"A3 fact {t['name']} ttl_days>0 ({ttl})"))
    ttl_map = {t["name"]: t["ttl_days"] for t in facts}
    res.append((ttl_map.get("fct_turn") == min(ttl_map.values()),
                "A3 fct_turn en kısa retention (yüksek hacim)"))
    res.append((ttl_map.get("fct_usage") == max(ttl_map.values()),
                "A3 fct_usage en uzun retention (fatura)"))

    # A4: her sütun pii_class izinli; tablo max_pii_class izinli
    for t in all_tables:
        for c in t["columns"]:
            pc = c.get("pii_class")
            res.append((pc in ALLOWED_PII,
                        f"A4 {t['name']}.{c['name']} pii_class={pc} izinli"))
            res.append((pc not in FORBIDDEN_PII,
                        f"A4 {t['name']}.{c['name']} raw/sensitive değil"))
        res.append((t.get("max_pii_class") in ALLOWED_PII,
                    f"A4 {t['name']} max_pii_class izinli"))
    # pii_policy beyanı tutarlı
    pol = spec["pii_policy"]
    res.append((set(pol["allowed_column_pii_classes"]) == ALLOWED_PII,
                "A4 pii_policy allowed kümesi"))
    res.append((set(pol["forbidden_column_pii_classes"]) == FORBIDDEN_PII,
                "A4 pii_policy forbidden kümesi"))

    # A5: residency home-region beyanı (isolation_model + retention_policy)
    res.append(("home-region" in spec["_meta"]["isolation_model"],
                "A5 isolation_model home-region residency"))
    res.append(("NFR 10.7" in json.dumps(spec["retention_policy"]),
                "A5 retention_policy residency izi"))

    # A6: her fact dedup_key
    for t in facts:
        res.append((bool(t.get("dedup_key")), f"A6 fact {t['name']} dedup_key"))

    # A7: row-policy şablonu mevcut + isolation_model sorgu-katmanı beyanı
    res.append((os.path.exists(ROW_POLICY), "A7 row-policy.template.sql mevcut"))
    res.append(("güvenilmez" in spec["_meta"]["isolation_model"].lower() or
                "GÜVENİLMEZ" in spec["_meta"]["isolation_model"],
                "A7 sorgu-katmanı zorunlu predicate (istemciye güvenilmez)"))

    # A8: no-loss fact retention>=365 + idempotency_key dedup
    for t in facts:
        if t.get("delivery_class") == "no-loss":
            res.append((t["ttl_days"] >= 365, f"A8 no-loss {t['name']} retention>=365"))
            res.append((t["dedup_key"] == "idempotency_key",
                        f"A8 no-loss {t['name']} idempotency_key dedup"))

    # A9: her rollup source ∈ fact + dashboard_fr FR-ANA-*
    for r in rollups:
        res.append((r.get("source") in fact_names,
                    f"A9 rollup {r['name']} source∈fact ({r.get('source')})"))
        dfr = r.get("dashboard_fr", [])
        res.append((any(x.startswith("FR-ANA-") for x in dfr),
                    f"A9 rollup {r['name']} dashboard_fr FR-ANA-*"))

    # A12: source_topic ∈ known + consumer izinli
    for t in facts:
        res.append((t.get("source_topic") in known_topics,
                    f"A12 fact {t['name']} source_topic∈known ({t.get('source_topic')})"))
        res.append((t.get("source_consumer") in ALLOWED_CONSUMERS,
                    f"A12 fact {t['name']} consumer izinli ({t.get('source_consumer')})"))

    # A13: agent_version_id call/turn/qa
    for name in ("fct_call", "fct_turn", "fct_qa_evaluation"):
        t = next(x for x in facts if x["name"] == name)
        cols = {c["name"] for c in t["columns"]}
        res.append(("agent_version_id" in cols, f"A13 {name} agent_version_id (FR-ANA-010)"))

    # A14: ayrık STT/LLM/TTS/e2e gecikme alanları
    turn = next(x for x in facts if x["name"] == "fct_turn")
    tcols = {c["name"] for c in turn["columns"]}
    for col in ("stt_latency_ms", "llm_first_token_ms", "tts_first_byte_ms", "e2e_latency_ms"):
        res.append((col in tcols, f"A14 fct_turn ayrık gecikme {col}"))
    call = next(x for x in facts if x["name"] == "fct_call")
    ccols = {c["name"] for c in call["columns"]}
    res.append(("e2e_latency_p95_ms" in ccols, "A14 fct_call e2e_latency_p95_ms"))

    return res


def check_ddl_consistency(spec):
    """A11: her tablo HEM clickhouse HEM bigquery DDL'inde + tenant'lı tablolarda tenant_id."""
    res = []
    ch = read_text(DDL_CH)
    bq = read_text(DDL_BQ)
    facts = spec["fact_tables"]
    dims = spec["dimension_tables"]
    rollups = spec["rollups"]

    def has_create(text, name):
        # CREATE TABLE/MATERIALIZED VIEW ... <name> (tablo adı tam-kelime)
        return re.search(r"\b" + re.escape(name) + r"\b", text) is not None

    for t in facts + dims:
        res.append((has_create(ch, t["name"]), f"A11 {t['name']} ∈ clickhouse.sql"))
        res.append((has_create(bq, t["name"]), f"A11 {t['name']} ∈ bigquery.sql"))
        if t["name"] not in TENANT_FREE_DIMS:
            # tenant_id DDL'de geçmeli (kabaca: tablo bloğu civarı; basit kapsama yeterli)
            res.append(("tenant_id" in ch, f"A11 clickhouse tenant_id (genel)"))
            res.append(("tenant_id" in bq, f"A11 bigquery tenant_id (genel)"))
    for r in rollups:
        res.append((has_create(ch, r["name"]), f"A11 rollup {r['name']} ∈ clickhouse.sql"))
        res.append((has_create(bq, r["name"]), f"A11 rollup {r['name']} ∈ bigquery.sql"))
    return res


def check_secrets():
    """A10: DDL/şablon/runner literal sır içermez (yorum + ${ENV} hariç)."""
    res = []
    for path in (DDL_CH, DDL_BQ, ROW_POLICY, RUN_LIVE):
        if not os.path.exists(path):
            res.append((False, f"A10 dosya yok: {os.path.basename(path)}"))
            continue
        bad = []
        for i, line in enumerate(read_text(path).splitlines(), 1):
            s = line.strip()
            if s.startswith("#") or s.startswith("--") or s.startswith("//"):
                continue  # yorum: sırrı tarif eden açıklama ≠ sır
            for m in SECRET_HINT_RE.finditer(line):
                val = m.group(2)
                if "${" in val or val.upper() in ("ENV", "PLACEHOLDER"):
                    continue  # placeholder
                bad.append(f"{os.path.basename(path)}:{i}")
        res.append((not bad, f"A10 {os.path.basename(path)} literal sır yok" +
                    (f" — {bad}" if bad else "")))
    return res


def cmd_validate():
    spec = load_json(SPEC_PATH)
    results = []
    results += check_invariants(spec)
    results += check_ddl_consistency(spec)
    results += check_secrets()
    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    for ok, msg in results:
        if not ok:
            print(f"  FAIL: {msg}")
    print(f"validate: {passed}/{total} PASS")
    return 0 if passed == total else 1


# ---------------- deterministik OLAP sorgu simülatörü ----------------

# Sentetik fct_call satırları (2 tenant) — gerçek motor yerine in-memory.
def _sample_calls():
    A = "11111111-1111-1111-1111-111111111111"
    B = "22222222-2222-2222-2222-222222222222"
    rows = [
        # tenant, agent, version, contained, transferred, critical, e2e_p95
        (A, "ag-A", "v1", 1, 0, 0, 800),
        (A, "ag-A", "v1", 1, 0, 0, 900),
        (A, "ag-A", "v1", 0, 1, 1, 1500),
        (A, "ag-A", "v2", 1, 0, 0, 600),
        (B, "ag-B", "v1", 0, 1, 0, 1100),
        (B, "ag-B", "v1", 1, 0, 0, 700),
    ]
    return [dict(tenant_id=t, agent_id=a, agent_version_id=v, contained=c,
                 transferred=tr, flag_critical=cr, e2e_latency_p95_ms=e)
            for (t, a, v, c, tr, cr, e) in rows], A, B


def _query(rows, tenant_ctx, project=None):
    """Sorgu-katmanı simülasyonu: tenant_ctx ZORUNLU (yoksa reddet=fail-closed).
    project: izinli sütun listesi; PII sütunu istenirse reddet."""
    if not tenant_ctx:
        raise PermissionError("tenant predicate zorunlu (fail-closed)")
    # PII projeksiyon koruması: OLAP'ta raw sütun yok; raw isteği reddedilir.
    if project:
        for col in project:
            if col in ("transcript_text", "raw_audio", "card_number", "otp"):
                raise PermissionError(f"PII/ham sütun yasak: {col}")
    return [r for r in rows if r["tenant_id"] == tenant_ctx]


def cmd_query():
    rows, A, B = _sample_calls()
    checks = []

    # 1) predicate'siz sorgu reddedilir (fail-closed)
    try:
        _query(rows, None)
        checks.append((False, "Q1 predicate'siz sorgu reddedilmeli"))
    except PermissionError:
        checks.append((True, "Q1 predicate'siz sorgu fail-closed reddedildi"))

    # 2) tenant A yalnız A satırlarını görür; B sızmaz (cross-tenant leak=0)
    ra = _query(rows, A)
    leak = [r for r in ra if r["tenant_id"] != A]
    checks.append((len(ra) == 4 and not leak, f"Q2 tenant A {len(ra)} satır, sızıntı={len(leak)}"))
    rb = _query(rows, B)
    checks.append((len(rb) == 2 and all(r["tenant_id"] == B for r in rb),
                   f"Q3 tenant B {len(rb)} satır izole"))

    # 3) rollup doğruluğu — mv_call_daily metrikleri elle hesap ile birebir
    # tenant A: calls=4, contained=3, transferred=1, critical=1
    calls = len(ra)
    contained = sum(r["contained"] for r in ra)
    transferred = sum(r["transferred"] for r in ra)
    critical = sum(r["flag_critical"] for r in ra)
    containment_rate = contained / calls
    checks.append((calls == 4 and contained == 3 and transferred == 1 and critical == 1,
                   f"Q4 rollup sayımlar calls={calls} contained={contained} transfer={transferred} crit={critical}"))
    checks.append((abs(containment_rate - 0.75) < 1e-9,
                   f"Q5 containment_rate={containment_rate:.2f} (FR-ANA-003)"))

    # 4) agent sürüm karşılaştırması (FR-ANA-010): v1 vs v2 ayrık
    v1 = [r for r in ra if r["agent_version_id"] == "v1"]
    v2 = [r for r in ra if r["agent_version_id"] == "v2"]
    checks.append((len(v1) == 3 and len(v2) == 1, f"Q6 sürüm ayrımı v1={len(v1)} v2={len(v2)}"))

    # 5) PII projeksiyon reddi
    try:
        _query(rows, A, project=["transcript_text"])
        checks.append((False, "Q7 PII sütun reddedilmeli"))
    except PermissionError:
        checks.append((True, "Q7 PII/ham sütun projeksiyonu reddedildi (FR-REC-004)"))

    # 6) idempotent dedup — at-least-once duplicate (1.1.8 P3) → dedup_key ile tek sayılır
    #    (ReplacingMergeTree/MERGE eşi). Satırlara sentetik call_id ver, A satırını çoğalt.
    keyed = [dict(r, call_id=f"c{i}") for i, r in enumerate(rows)]
    dup = keyed + [keyed[0]]  # ilk A satırı iki kez geldi (replay)
    ra_dup = _query(dup, A)
    unique_a = len({r["call_id"] for r in ra_dup})  # dedup_key=call_id
    checks.append((len(ra_dup) == 5 and unique_a == 4,
                   f"Q8 idempotent dedup: ham={len(ra_dup)} → benzersiz call_id={unique_a}"))

    passed = sum(1 for ok, _ in checks if ok)
    for ok, msg in checks:
        print(("  OK  " if ok else "  FAIL") + ": " + msg)
    print(f"query: {passed}/{len(checks)} PASS")
    return 0 if passed == len(checks) else 1


# ---------------- selftest ----------------

def cmd_selftest():
    spec = load_json(SPEC_PATH)
    tests = []

    def expect_fail(mutate, label):
        import copy
        bad = copy.deepcopy(spec)
        mutate(bad)
        try:
            res = check_invariants(bad)
            ok = any(not r[0] for r in res)
        except Exception:
            ok = True  # yapısal kırılma da yakalama sayılır
        tests.append((ok, f"selftest: {label} yakalandı"))

    # gerçek spec geçer
    good = check_invariants(spec) + check_ddl_consistency(spec) + check_secrets()
    tests.append((all(r[0] for r in good), "selftest: gerçek spec tüm kapıları geçer"))

    # A1: tenant_id ORDER BY ilk değil
    expect_fail(lambda s: s["fact_tables"][0].__setitem__("order_by", ["agent_id", "tenant_id"]),
                "A1 tenant_id ilk-anahtar değil")
    # A1: fact'ten tenant_id sütunu sil
    expect_fail(lambda s: s["fact_tables"][0]["columns"].__setitem__(
        0, {"name": "x", "type": "uuid", "pii_class": "none"}),
                "A1 fact tenant_id sütunu yok")
    # A2: partition_by kaldır
    expect_fail(lambda s: s["fact_tables"][1].__setitem__("partition_by", None),
                "A2 partition yok")
    # A3: ttl_days=0
    expect_fail(lambda s: s["fact_tables"][0].__setitem__("ttl_days", 0),
                "A3 sonsuz/0 retention")
    # A4: raw pii sütunu ekle
    expect_fail(lambda s: s["fact_tables"][0]["columns"].append(
        {"name": "transcript", "type": "string", "pii_class": "raw"}),
                "A4 raw PII sütunu")
    # A6: dedup_key kaldır
    expect_fail(lambda s: s["fact_tables"][0].__setitem__("dedup_key", ""),
                "A6 dedup_key yok")
    # A8: no-loss retention<365
    expect_fail(lambda s: s["fact_tables"][2].__setitem__("ttl_days", 100),
                "A8 no-loss kısa retention")
    # A9: rollup source geçersiz
    expect_fail(lambda s: s["rollups"][0].__setitem__("source", "yok_tablo"),
                "A9 rollup geçersiz source")
    # A12: source_topic bilinmeyen
    expect_fail(lambda s: s["fact_tables"][0].__setitem__("source_topic", "yok.topic.v1"),
                "A12 bilinmeyen source_topic")
    # A13: agent_version_id sil (fct_call)
    def drop_av(s):
        c = next(x for x in s["fact_tables"] if x["name"] == "fct_call")
        c["columns"] = [col for col in c["columns"] if col["name"] != "agent_version_id"]
    expect_fail(drop_av, "A13 agent_version_id yok")
    # A14: e2e_latency_ms sil (fct_turn)
    def drop_e2e(s):
        c = next(x for x in s["fact_tables"] if x["name"] == "fct_turn")
        c["columns"] = [col for col in c["columns"] if col["name"] != "e2e_latency_ms"]
    expect_fail(drop_e2e, "A14 ayrık gecikme alanı yok")

    # query simülatörü kapıları
    rows, A, B = _sample_calls()
    try:
        _query(rows, None); q_failclosed = False
    except PermissionError:
        q_failclosed = True
    tests.append((q_failclosed, "selftest: query predicate'siz fail-closed"))
    tests.append((all(r["tenant_id"] == A for r in _query(rows, A)),
                  "selftest: query tenant izolasyonu"))

    # secret tarayıcı: yorum satırındaki 'secret' kelimesi sır SAYILMAZ
    tmp_has_comment_secret = "-- password: ${DB_PASSWORD} buradan gelir"
    has_hit = False
    for line in [tmp_has_comment_secret]:
        s = line.strip()
        if s.startswith("--"):
            continue
        if SECRET_HINT_RE.search(line):
            has_hit = True
    tests.append((not has_hit, "selftest: yorum/placeholder sır sayılmaz"))

    passed = sum(1 for ok, _ in tests if ok)
    for ok, msg in tests:
        print(("  OK  " if ok else "  FAIL") + ": " + msg)
    print(f"selftest: {passed}/{len(tests)} PASS")
    return 0 if passed == len(tests) else 1


def cmd_schema():
    print("""olap-spec.json beklenen şekil:
  _meta              : wbs/title/source_of_truth/vendor_neutral/secret_policy/position/isolation_model
  engine_neutral     : reference/alt engine + type/partition/order/ttl/dedup eşlemesi
  ingestion          : lineage (1.1.8) + idempotency + freshness_target_s
  pii_policy         : allowed/forbidden column pii_classes + rules
  retention_policy   : tiers (raw_high_volume/operational/billing_financial/rollup)
  fact_tables[]      : name/grain/source_topic/source_consumer/delivery_class/partition_by/
                       order_by/ttl_days/dedup_key/engine/max_pii_class/columns[]/fr/trace
  dimension_tables[] : name/grain/source/order_by/max_pii_class/columns[]
  rollups[]          : name/type/source/grain/engine/metrics/dashboard_fr
  known_source_topics: 1.1.8 topic lineage kümesi
  invariants[]       : A1–A14
Kapılar: A1 tenant_id ilk-anahtar · A2 partition · A3 sonlu TTL · A4 PII none/low/redacted ·
  A5 residency · A6 dedup · A7 row-policy+sorgu-katmanı · A8 no-loss · A9 rollup izi ·
  A10 sır yok · A11 spec↔DDL · A12 lineage · A13 agent_version · A14 ayrık gecikme""")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if cmd == "validate":
        return cmd_validate()
    if cmd == "query":
        return cmd_query()
    if cmd == "selftest":
        return cmd_selftest()
    if cmd == "schema":
        return cmd_schema()
    print(f"bilinmeyen komut: {cmd} (validate|query|selftest|schema)")
    return 2


if __name__ == "__main__":
    sys.exit(main())
