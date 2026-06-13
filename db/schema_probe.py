#!/usr/bin/env python3
# =============================================================================
# schema_probe.py — Tenant/Org/User/Role şema + RLS statik doğrulayıcı (WBS 1.1.1)
# F1 · Must · →BRD §16 (1–4), SAD §13.1, FR-TEN-002, FR-IAM-011, ADR-006 · DB.md §5.1/§6
#
# Amaç: Canlı PostgreSQL gerektirmeden, migration SQL'inin DB.md tasarım
# invariant'larını (tenant_id+RLS, fail-closed, FORCE RLS, global rol izolasyonu,
# UUIDv7 PK, FK indeks, WORM/salt-okunur grant) sağladığını kanıtlamak.
# 0.2.x/0.3.x/0.4.x probe disipliniyle aynı: stdlib-only, credential-free,
# deterministik, kapı→çıkış kodu. Canlı davranış testi: db/run_live_test.sh.
#
# Alt komutlar:
#   validate   migration/seed dosyalarını tasarım invariant'larına karşı doğrular
#   selftest   doğrulayıcı predikatları sentetik geç/kal girdilerle test eder
#   schema     beklenen nesneleri/kontrolleri JSON olarak yazar
# =============================================================================
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MIG = os.path.join(HERE, "migrations")

# Kapsamdaki tablolar (DB.md §4 varlık 1–4 + türevleri)
TENANT_SCOPED = ["organisation_unit", "app_user", "user_role_assignment"]
GLOBAL_TABLES = ["role", "permission_key", "role_permission"]
ALL_TABLES = ["tenant"] + TENANT_SCOPED + GLOBAL_TABLES
RLS_TABLES = ["tenant"] + TENANT_SCOPED  # tenant: Root self-policy
UUIDV7_PK = ["tenant", "organisation_unit", "app_user", "role", "user_role_assignment"]

# Sabit rol kümesi (CLAUDE.md RBAC; FR-IAM-011, ADR-012)
EXPECTED_ROLES = {
    "platform_owner": "L0", "platform_sre": "L0", "platform_billing": "L0",
    "tenant_owner": "L1L2", "tenant_admin": "L1", "security_compliance_officer": "L1",
    "billing_viewer": "L1", "api_developer": "L1L2",
    "operations_manager": "L2", "conversation_designer": "L2",
    "qa_analyst": "L2", "human_agent": "L2",
}

# İzlenebilirlik: tasarım kararı → DB.md'de bulunması gereken kaynak token (non-circular)
TRACE_TOKENS = ["FR-TEN-002", "FR-IAM-011", "FR-IAM-008", "ADR-006", "ADR-012"]


# -----------------------------------------------------------------------------
# Yardımcılar (predikatlar — hem validate hem selftest bunları kullanır)
# -----------------------------------------------------------------------------
def strip_comments(sql):
    """-- satır yorumlarını ve /* */ blok yorumlarını kaldır (basit; string literal
    içinde -- bulunmadığı bu şemada güvenli)."""
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n]*", "", sql)
    return sql


def norm(s):
    return re.sub(r"\s+", " ", s).strip()


def table_body(sql, name):
    """CREATE TABLE <name> ( ... \n); gövdesini döndür (normalize edilmiş)."""
    m = re.search(r"CREATE TABLE %s\s*\((.*?)\n\s*\)\s*;" % re.escape(name),
                  sql, flags=re.DOTALL)
    return norm(m.group(1)) if m else None


def policy_blocks(sql, table):
    """Bir tabloya ait tüm CREATE POLICY ... ; bloklarını döndür."""
    return re.findall(
        r"CREATE POLICY\s+\w+\s+ON\s+%s\b(.*?);" % re.escape(table),
        sql, flags=re.DOTALL)


def fail_closed_ok(sql):
    """Tüm current_setting('app.*') kullanımları iki-argümanlı (fail-closed) mı?
    Bare current_setting('app.x') varsa False (hata fırlatır/fail-open riski)."""
    uses = list(re.finditer(r"current_setting\(\s*'app\.[a-z_]+'\s*(,\s*true\s*)?\)", sql))
    if not uses:
        return False  # En az bir kullanım olmalı (politikalar GUC'a dayanır)
    return all(m.group(1) is not None for m in uses)


def table_rls_ok(sql, table):
    """ENABLE + FORCE ROW LEVEL SECURITY + en az bir POLICY var mı?"""
    n = norm(sql)
    en = ("ALTER TABLE %s ENABLE ROW LEVEL SECURITY" % table) in n
    fo = ("ALTER TABLE %s FORCE ROW LEVEL SECURITY" % table) in n
    pol = len(policy_blocks(sql, table)) >= 1
    return en and fo and pol


def has_with_check(sql, table):
    blocks = policy_blocks(sql, table)
    return all("WITH CHECK" in b for b in blocks) and len(blocks) >= 1


# -----------------------------------------------------------------------------
# validate
# -----------------------------------------------------------------------------
def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def run_validate():
    checks = []

    def add(cid, ok, detail):
        checks.append((cid, bool(ok), detail))

    # Dosya varlığı
    files = {
        "0001u": "0001_extensions_helpers.up.sql",
        "0001d": "0001_extensions_helpers.down.sql",
        "0002u": "0002_tenant_org_iam.up.sql",
        "0002d": "0002_tenant_org_iam.down.sql",
        "0003u": "0003_rls_tenant_org_iam.up.sql",
        "0003d": "0003_rls_tenant_org_iam.down.sql",
    }
    raw = {}
    for k, fn in files.items():
        p = os.path.join(MIG, fn)
        ok = os.path.exists(p)
        add("FILE:%s" % fn, ok, "var" if ok else "EKSİK")
        raw[k] = strip_comments(read(p)) if ok else ""

    seed_p = os.path.join(HERE, "seeds", "roles.sql")
    seed_ok = os.path.exists(seed_p)
    add("FILE:seeds/roles.sql", seed_ok, "var" if seed_ok else "EKSİK")
    seed = strip_comments(read(seed_p)) if seed_ok else ""

    up = raw["0001u"] + "\n" + raw["0002u"] + "\n" + raw["0003u"]
    ddl = raw["0002u"]
    rls = raw["0003u"]
    helpers = raw["0001u"]

    # A. Yardımcılar
    add("A1 gen_uuid_v7 tanımlı", bool(re.search(r"FUNCTION\s+gen_uuid_v7\s*\(", helpers)), "UUIDv7 üreteci")
    add("A2 UUIDv7 sürüm=0x70", ("| 112" in helpers and "& 15" in helpers), "set_byte(...,6,...) v7 nibble")
    add("A3 UUIDv7 variant=0x80", ("| 128" in helpers and "& 63" in helpers), "set_byte(...,8,...) variant")
    add("A4 set_updated_at tanımlı", bool(re.search(r"FUNCTION\s+set_updated_at\s*\(", helpers)), "updated_at trigger fn")
    add("A5 raise_immutable_violation tanımlı", bool(re.search(r"FUNCTION\s+raise_immutable_violation\s*\(", helpers)), "WORM fn (DB.md §6.5)")
    add("A6 app_rw rolü oluşturulur", "CREATE ROLE app_rw" in norm(helpers), "RLS-bypass-etmeyen uygulama rolü")

    # B. Tablolar mevcut
    for t in ALL_TABLES:
        add("B table:%s" % t, table_body(ddl, t) is not None, "CREATE TABLE")

    # C. UUIDv7 PK
    for t in UUIDV7_PK:
        body = table_body(ddl, t) or ""
        add("C pk-uuidv7:%s" % t,
            "id UUID PRIMARY KEY DEFAULT gen_uuid_v7()" in body, "id UUID PK DEFAULT gen_uuid_v7()")
    add("C pk:permission_key", "key TEXT PRIMARY KEY" in (table_body(ddl, "permission_key") or ""), "key PK")
    add("C pk:role_permission",
        "PRIMARY KEY (role_id, perm_key)" in (table_body(ddl, "role_permission") or ""), "kompozit PK")

    # D. Tenant-scoped: tenant_id + FK tenant(id)
    for t in TENANT_SCOPED:
        body = table_body(ddl, t) or ""
        add("D tenant_id:%s" % t,
            ("tenant_id UUID" in body and "REFERENCES tenant(id)" in body),
            "tenant_id UUID REFERENCES tenant(id)")
    add("D notnull:organisation_unit",
        "tenant_id UUID NOT NULL REFERENCES tenant(id)" in (table_body(ddl, "organisation_unit") or ""),
        "org_unit.tenant_id NOT NULL")

    # E. Global tablolarda tenant_id YOK
    for t in GLOBAL_TABLES:
        body = table_body(ddl, t) or ""
        add("E no-tenant_id:%s" % t, "tenant_id" not in body, "global tablo, tenant_id taşımaz")

    # F. RLS: enable+force+policy
    for t in RLS_TABLES:
        add("F rls:%s" % t, table_rls_ok(rls, t), "ENABLE+FORCE+POLICY")

    # G. Global tablolar RLS'e alınmamış
    for t in GLOBAL_TABLES:
        add("G no-rls:%s" % t,
            ("ALTER TABLE %s ENABLE ROW LEVEL SECURITY" % t) not in norm(rls),
            "referans tablo RLS dışı (salt-okunur)")

    # H. Fail-closed (iki-argümanlı current_setting)
    add("H fail-closed", fail_closed_ok(up), "current_setting('app.*', true) — GUC yoksa 0 satır")

    # I. WITH CHECK (cross-tenant write koruması) tenant-scoped politikalarda
    for t in TENANT_SCOPED:
        add("I with-check:%s" % t, has_with_check(rls, t), "WITH CHECK var")
    add("I with-check:tenant", has_with_check(rls, "tenant"), "tenant yazımı platform-only")

    # J. BYPASSRLS / SUPERUSER kullanılmamış (yorum strip sonrası)
    add("J no-bypassrls", ("BYPASSRLS" not in up.upper() and "SUPERUSER" not in up.upper()),
        "uygulama yolunda RLS bypass yok (P2)")

    # K. Global rol tabloları app_rw'ye salt-okunur
    for t in GLOBAL_TABLES:
        n = norm(rls)
        revoked = ("REVOKE ALL ON %s FROM app_rw" % t) in n
        no_write = not re.search(r"GRANT[^;]*\b(INSERT|UPDATE|DELETE)\b[^;]*ON %s\b" % t, n)
        add("K readonly:%s" % t, revoked and no_write, "REVOKE ALL + yalnız GRANT SELECT")

    # L. FK indeksleri
    for idx in ["ix_orgunit_parent", "ix_ura_user", "ix_ura_tenant", "ix_orgunit_tenant", "ix_ura_role"]:
        add("L index:%s" % idx, ("CREATE INDEX %s" % idx) in norm(ddl), "FK/join indeksi")

    # M. Down migration'lar nesneleri düşürür
    for t in ALL_TABLES:
        add("M down-drop:%s" % t, ("DROP TABLE IF EXISTS %s" % t) in norm(raw["0002d"]), "down DROP TABLE")
    add("M down-policy", raw["0003d"].count("DROP POLICY") >= len(RLS_TABLES), "down DROP POLICY")
    add("M down-helpers", ("DROP FUNCTION IF EXISTS gen_uuid_v7()" in raw["0001d"]), "down DROP FUNCTION")

    # N. Seed: 12 rol, doğru seviyeler
    seed_pairs = dict(re.findall(r"\('([a-z_]+)',\s*'(L0|L1|L2|L1L2)'", seed))
    add("N seed-count", len(seed_pairs) == len(EXPECTED_ROLES),
        "%d/%d rol" % (len(seed_pairs), len(EXPECTED_ROLES)))
    add("N seed-roles", seed_pairs == EXPECTED_ROLES,
        "kod↔seviye eşleşmesi" if seed_pairs == EXPECTED_ROLES else
        "uyuşmaz: %s" % {k: v for k, v in seed_pairs.items() if EXPECTED_ROLES.get(k) != v})
    add("N seed-idempotent", "ON CONFLICT" in seed, "ON CONFLICT DO NOTHING")

    # O. İzlenebilirlik: DB.md kaynak token'ları (non-circular)
    dbmd_p = os.path.join(ROOT, "docs", "DB.md")
    dbmd = read(dbmd_p) if os.path.exists(dbmd_p) else ""
    for tok in TRACE_TOKENS:
        add("O trace:%s" % tok, tok in dbmd, "DB.md'de kaynak referans")

    # Rapor
    passed = sum(1 for _, ok, _ in checks if ok)
    total = len(checks)
    failed = [(c, d) for c, ok, d in checks if not ok]
    print("== schema_probe validate — Tenant/Org/User/Role + RLS (WBS 1.1.1) ==")
    for cid, ok, detail in checks:
        print("  %s %s — %s" % ("PASS" if ok else "FAIL", cid, detail))
    print("-" * 60)
    print("%d/%d kontrol geçti" % (passed, total))
    if failed:
        print("KIRMIZI: %d kontrol başarısız" % len(failed))
        return 1
    print("YEŞIL: tüm tasarım invariant'ları sağlandı.")
    return 0


# -----------------------------------------------------------------------------
# selftest — predikatları sentetik geç/kal girdilerle doğrula
# -----------------------------------------------------------------------------
def run_selftest():
    results = []

    def check(name, cond):
        results.append((name, bool(cond)))

    # strip_comments BYPASSRLS'i yorumdan siler
    check("strip:comment-bypassrls",
          "BYPASSRLS" not in strip_comments("-- Superuser/BYPASSRLS kullanılmaz\nCREATE ROLE app_rw NOLOGIN;").upper())
    check("strip:block-comment",
          "x" not in strip_comments("/* x */ SELECT 1;"))

    # fail_closed_ok
    good = "USING (tenant_id = current_setting('app.tenant_id', true)::uuid)"
    bad = "USING (tenant_id = current_setting('app.tenant_id')::uuid)"
    check("fail-closed:good", fail_closed_ok(good) is True)
    check("fail-closed:bad", fail_closed_ok(bad) is False)

    # table_body çıkarımı
    sample = ("CREATE TABLE foo (\n  id UUID PRIMARY KEY DEFAULT gen_uuid_v7(),\n"
              "  status TEXT CHECK (status IN ('a','b')),\n  tenant_id UUID NOT NULL REFERENCES tenant(id)\n);")
    body = table_body(sample, "foo")
    check("table_body:found", body is not None)
    check("table_body:has-pk", "id UUID PRIMARY KEY DEFAULT gen_uuid_v7()" in (body or ""))
    check("table_body:has-fk", "REFERENCES tenant(id)" in (body or ""))
    check("table_body:missing", table_body(sample, "bar") is None)

    # table_rls_ok
    rls_good = ("ALTER TABLE foo ENABLE ROW LEVEL SECURITY;\n"
                "ALTER TABLE foo FORCE ROW LEVEL SECURITY;\n"
                "CREATE POLICY p ON foo USING (true) WITH CHECK (true);")
    rls_noforce = ("ALTER TABLE foo ENABLE ROW LEVEL SECURITY;\n"
                   "CREATE POLICY p ON foo USING (true);")
    rls_nopolicy = ("ALTER TABLE foo ENABLE ROW LEVEL SECURITY;\n"
                    "ALTER TABLE foo FORCE ROW LEVEL SECURITY;")
    check("rls:good", table_rls_ok(rls_good, "foo") is True)
    check("rls:no-force", table_rls_ok(rls_noforce, "foo") is False)
    check("rls:no-policy", table_rls_ok(rls_nopolicy, "foo") is False)

    # has_with_check
    check("with-check:good", has_with_check(rls_good, "foo") is True)
    check("with-check:bad", has_with_check(rls_noforce, "foo") is False)

    # policy_blocks sayımı
    check("policy:count", len(policy_blocks(rls_good, "foo")) == 1)

    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    print("== schema_probe selftest ==")
    for name, ok in results:
        print("  %s %s" % ("PASS" if ok else "FAIL", name))
    print("-" * 40)
    print("%d/%d selftest geçti" % (passed, total))
    return 0 if passed == total else 1


def run_schema():
    print(json.dumps({
        "task": "WBS 1.1.1 — PostgreSQL şeması: Tenant, Org Unit, User, Role (+ RLS)",
        "source": ["BRD §16 (1–4)", "SAD §13.1", "DB.md §5.1/§6"],
        "tables": ALL_TABLES,
        "tenant_scoped": TENANT_SCOPED,
        "global_tables": GLOBAL_TABLES,
        "rls_tables": RLS_TABLES,
        "uuidv7_pk": UUIDV7_PK,
        "expected_roles": EXPECTED_ROLES,
        "trace_tokens": TRACE_TOKENS,
        "session_contract": {
            "tenant_realm": "SET LOCAL app.tenant_id = '<uuid>'",
            "platform_realm": "SET LOCAL app.platform = 'on'",
            "fail_closed": "current_setting('app.tenant_id', true) — GUC yoksa NULL → 0 satır",
        },
        "gates": ["validate", "selftest", "live: db/run_live_test.sh"],
    }, ensure_ascii=False, indent=2))
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if cmd == "validate":
        sys.exit(run_validate())
    elif cmd == "selftest":
        sys.exit(run_selftest())
    elif cmd == "schema":
        sys.exit(run_schema())
    else:
        print("kullanım: schema_probe.py [validate|selftest|schema]")
        sys.exit(2)


if __name__ == "__main__":
    main()
