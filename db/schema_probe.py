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

# Kapsamdaki tablolar (DB.md §4 varlık 1–4 + türevleri) — WBS 1.1.1
TENANT_SCOPED = ["organisation_unit", "app_user", "user_role_assignment"]
GLOBAL_TABLES = ["role", "permission_key", "role_permission"]
ALL_TABLES = ["tenant"] + TENANT_SCOPED + GLOBAL_TABLES
RLS_TABLES = ["tenant"] + TENANT_SCOPED  # tenant: Root self-policy
UUIDV7_PK = ["tenant", "organisation_unit", "app_user", "role", "user_role_assignment"]

# Agent ve Yapılandırma (DB.md §4 varlık 5–11) — WBS 1.1.2. Hepsi saf tenant-scoped.
AGENT_TABLES = ["agent", "agent_version", "prompt", "conversation_flow",
                "voice_profile", "model_profile", "stt_profile"]
AGENT_WORM = ["agent_version"]  # WORM/append-only (DB.md §6.5, FR-AGT-006)
# İzlenebilirlik: agent-config tasarım kararları → DB.md kaynak token (non-circular)
AGENT_TRACE_TOKENS = ["FR-AGT-001", "FR-AGT-003", "FR-AGT-006", "FR-LLM-012"]

# Çağrı ve Etkileşim (DB.md §4 varlık 19–24) — WBS 1.1.3. Tümü partition'lı,
# saf tenant-scoped. (call_evaluation = varlık 25 → 1.1.4; burada DEĞİL.)
CALL_TABLES = ["call", "call_leg", "transcript", "transcript_segment",
               "recording", "call_event", "tool_execution"]
CALL_WORM = ["tool_execution"]  # WORM/append-only + idempotent (DB.md §6.5/P4, FR-TOOL-009)
# call_id MANTIKSAL FK'dir (partition'lı parent → REFERENCES yok, DB.md §7.2).
CALL_TRACE_TOKENS = ["FR-TEL-012", "FR-TEL-007", "FR-REC-004", "FR-REC-005", "FR-TOOL-009"]

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


def pg_table_body(sql, name):
    """RANGE partition'lı tablonun gövdesini döndür:
    CREATE TABLE <name> ( ... ) PARTITION BY RANGE (created_at);"""
    m = re.search(
        r"CREATE TABLE %s\s*\((.*?)\n\s*\)\s*PARTITION BY RANGE \(created_at\)\s*;"
        % re.escape(name), sql, flags=re.DOTALL)
    return norm(m.group(1)) if m else None


def is_partitioned(sql, name):
    """Tablo RANGE (created_at) ile partition'lı mı?"""
    return pg_table_body(sql, name) is not None


def default_partition_ok(sql, name):
    """Her partition'lı tablo için bir DEFAULT partition (insert güvenlik ağı) var mı?"""
    n = norm(sql)
    return bool(re.search(
        r"CREATE TABLE IF NOT EXISTS %s_default PARTITION OF %s DEFAULT" % (name, name), n))


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


def null_safe_uuid_ok(sql):
    """Tüm current_setting('app.*')::uuid cast'leri NULLIF(...,'') ile sarmalanmış mı?
    Bağlantı havuzunda SET LOCAL sonrası placeholder '' döner; çıplak ''::uuid hata
    fırlatır (fail-error). NULLIF(...,'')::uuid boş string'i NULL'a çevirir → 0 satır
    (gerçek fail-closed). DB.md §6.2. Çıplak (sarmalanmamış) cast OLMAMALI."""
    bare = re.findall(
        r"current_setting\(\s*'app\.[a-z_]+'\s*,\s*true\s*\)\s*::\s*uuid", sql)
    wrapped = re.findall(
        r"NULLIF\(\s*current_setting\(\s*'app\.[a-z_]+'\s*,\s*true\s*\)\s*,\s*''\s*\)\s*::\s*uuid",
        sql)
    return len(bare) == 0 and len(wrapped) >= 1


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


def has_immutable_trigger(sql, table):
    """WORM: BEFORE UPDATE OR DELETE ON <table> ... raise_immutable_violation
    trigger'ı tanımlı mı? (DB.md §6.5 append-only zorlama)."""
    n = norm(sql)
    m = re.search(
        r"CREATE TRIGGER\s+\w+\s+BEFORE UPDATE OR DELETE ON %s\b[^;]*raise_immutable_violation"
        % re.escape(table), n)
    return m is not None


def worm_grant_ok(sql, table):
    """app_rw'ye yalnız INSERT+SELECT verilmiş, UPDATE/DELETE verilmemiş mi?
    (DB.md §6.5 — WORM tablosu grant düzeyi koruması)."""
    n = norm(sql)
    has_si = bool(re.search(
        r"GRANT[^;]*\bSELECT\b[^;]*\bINSERT\b[^;]*ON %s\b[^;]*app_rw" % re.escape(table), n)) or \
        bool(re.search(
        r"GRANT[^;]*\bINSERT\b[^;]*\bSELECT\b[^;]*ON %s\b[^;]*app_rw" % re.escape(table), n))
    no_ud = not re.search(
        r"GRANT[^;]*\b(UPDATE|DELETE)\b[^;]*ON %s\b[^;]*app_rw" % re.escape(table), n)
    return has_si and no_ud


def deferred_circular_fk_ok(ddl):
    """agent.active_version_id dairesel FK'si CREATE TABLE içinde DEĞİL (deferred),
    ALTER TABLE ile eklenmiş mi? (DB.md §10 dairesel FK)."""
    body = table_body(ddl, "agent") or ""
    inline_fk = bool(re.search(r"active_version_id\s+UUID\s+REFERENCES", body))
    n = norm(ddl)
    altered = bool(re.search(
        r"ALTER TABLE agent ADD CONSTRAINT \w+ FOREIGN KEY \(active_version_id\) "
        r"REFERENCES agent_version\(id\)", n))
    return (not inline_fk) and altered


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
        "0004u": "0004_agent_config.up.sql",
        "0004d": "0004_agent_config.down.sql",
        "0005u": "0005_rls_agent_config.up.sql",
        "0005d": "0005_rls_agent_config.down.sql",
        "0006u": "0006_call_interaction.up.sql",
        "0006d": "0006_call_interaction.down.sql",
        "0007u": "0007_rls_call_interaction.up.sql",
        "0007d": "0007_rls_call_interaction.down.sql",
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

    # H. Fail-closed (iki-argümanlı current_setting + NULLIF boş-string koruması)
    add("H fail-closed", fail_closed_ok(up), "current_setting('app.*', true) — GUC yoksa 0 satır")
    add("H null-safe-uuid", null_safe_uuid_ok(rls),
        "NULLIF(current_setting(...),'')::uuid — havuzda '' fail-error değil 0 satır (DB.md §6.2)")

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

    # =========================================================================
    # WBS 1.1.2 — Agent ve Yapılandırma (DB.md §5.2). 0004 (şema) + 0005 (RLS).
    # =========================================================================
    ddl2 = raw["0004u"]
    rls2 = raw["0005u"]

    # P. Tablolar mevcut + UUIDv7 PK
    for t in AGENT_TABLES:
        body = table_body(ddl2, t)
        add("P table:%s" % t, body is not None, "CREATE TABLE")
        add("P pk-uuidv7:%s" % t,
            "id UUID PRIMARY KEY DEFAULT gen_uuid_v7()" in (body or ""),
            "id UUID PK DEFAULT gen_uuid_v7()")

    # Q. Tenant-scoped: tenant_id NOT NULL + FK tenant(id)
    for t in AGENT_TABLES:
        body = table_body(ddl2, t) or ""
        add("Q tenant_id-notnull:%s" % t,
            ("tenant_id UUID NOT NULL REFERENCES tenant(id)" in body),
            "tenant_id UUID NOT NULL REFERENCES tenant(id)")

    # R. RLS: enable+force+policy + WITH CHECK (her 7 tablo standart izolasyon)
    for t in AGENT_TABLES:
        add("R rls:%s" % t, table_rls_ok(rls2, t), "ENABLE+FORCE+POLICY")
        add("R with-check:%s" % t, has_with_check(rls2, t), "WITH CHECK (cross-tenant write koruması)")

    # S. Fail-closed (iki-argümanlı current_setting + NULLIF) — 0005 politikaları
    add("S fail-closed", fail_closed_ok(rls2), "current_setting('app.*', true) → GUC yoksa 0 satır")
    add("S null-safe-uuid", null_safe_uuid_ok(rls2),
        "NULLIF(current_setting(...),'')::uuid (DB.md §6.2)")

    # T. Dairesel FK: agent.active_version_id inline DEĞİL, ALTER ile eklenmiş
    add("T circular-fk", deferred_circular_fk_ok(ddl2),
        "active_version_id → agent_version(id) ALTER ile (DB.md §10)")

    # U. WORM (agent_version): immutable trigger (0004) + grant INSERT+SELECT (0005)
    for t in AGENT_WORM:
        add("U worm-trigger:%s" % t, has_immutable_trigger(ddl2, t),
            "BEFORE UPDATE OR DELETE → raise_immutable_violation (DB.md §6.5)")
        add("U worm-grant:%s" % t, worm_grant_ok(rls2, t),
            "app_rw yalnız INSERT+SELECT (UPDATE/DELETE yok)")

    # V. İndeksler: GIN flow graph + FK/sorgu indeksleri
    for idx in ["ix_agent_tenant", "ix_agent_orgunit", "ix_agent_state",
                "ix_agent_active_version", "ix_agentver_agent", "ix_prompt_agent",
                "ix_flow_agent", "ix_voiceprofile_tenant", "ix_modelprofile_tenant",
                "ix_sttprofile_tenant"]:
        add("V index:%s" % idx, ("CREATE INDEX %s" % idx) in norm(ddl2), "FK/sorgu indeksi")
    add("V gin:flow-graph",
        bool(re.search(r"CREATE INDEX ix_flow_graph ON conversation_flow USING gin", norm(ddl2))),
        "conversation_flow.graph GIN (DB.md §7.1)")

    # W. Down migration'lar: tablolar + dairesel FK + RLS politikaları düşer
    for t in AGENT_TABLES:
        add("W down-drop:%s" % t,
            ("DROP TABLE IF EXISTS %s" % t) in norm(raw["0004d"]), "down DROP TABLE")
    add("W down-fk", "DROP CONSTRAINT IF EXISTS fk_agent_active_version" in norm(raw["0004d"]),
        "down dairesel FK kaldırma")
    add("W down-policy", raw["0005d"].count("DROP POLICY") >= len(AGENT_TABLES), "down DROP POLICY")

    # X. agent_version'a UPDATE/DELETE grant'i HİÇBİR yerde verilmemiş (WORM bütünlüğü)
    add("X worm-no-write",
        not re.search(r"GRANT[^;]*\b(UPDATE|DELETE)\b[^;]*ON agent_version\b", norm(rls2)),
        "agent_version'a UPDATE/DELETE grant yok")

    # Y. İzlenebilirlik: agent-config kaynak token'ları DB.md'de
    for tok in AGENT_TRACE_TOKENS:
        add("Y trace:%s" % tok, tok in dbmd, "DB.md'de kaynak referans")

    # =========================================================================
    # WBS 1.1.3 — Çağrı ve Etkileşim (DB.md §5.5/§7.2). 0006 (şema) + 0007 (RLS).
    # =========================================================================
    ddl3 = raw["0006u"]
    rls3 = raw["0007u"]

    # Z. Tablolar mevcut + RANGE partition'lı + (id, created_at) PK + UUIDv7 default
    for t in CALL_TABLES:
        body = pg_table_body(ddl3, t)
        add("Z table:%s" % t, body is not None, "CREATE TABLE ... PARTITION BY RANGE (created_at)")
        add("Z partitioned:%s" % t, is_partitioned(ddl3, t), "PARTITION BY RANGE (created_at)")
        add("Z pk-composite:%s" % t,
            "PRIMARY KEY (id, created_at)" in (body or ""),
            "PK partition anahtarını içerir: (id, created_at)")
        add("Z uuidv7:%s" % t,
            "id UUID NOT NULL DEFAULT gen_uuid_v7()" in (body or ""),
            "id UUID NOT NULL DEFAULT gen_uuid_v7()")

    # AA. Tenant-scoped: tenant_id NOT NULL + GERÇEK FK tenant(id)
    for t in CALL_TABLES:
        body = pg_table_body(ddl3, t) or ""
        add("AA tenant_id-notnull:%s" % t,
            "tenant_id UUID NOT NULL REFERENCES tenant(id)" in body,
            "tenant_id UUID NOT NULL REFERENCES tenant(id)")

    # AB. Mantıksal FK: partition'lı parent'a (call/transcript) REFERENCES YOK (DB.md §7.2)
    add("AB logical-fk:call_id", "REFERENCES call(" not in ddl3,
        "call_id mantıksal FK (REFERENCES call yok — partition'lı)")
    add("AB logical-fk:transcript_id", "REFERENCES transcript(" not in ddl3,
        "transcript_id mantıksal FK (REFERENCES transcript yok)")
    # campaign/tool tabloları henüz yok → mantıksal kolon (FK yok)
    add("AB logical-fk:campaign", "REFERENCES campaign(" not in ddl3,
        "campaign_id mantıksal (campaign 1.1.4'te)")
    add("AB logical-fk:tool", "REFERENCES tool(" not in ddl3,
        "tool_id mantıksal (tool tablosu henüz yok)")

    # AC. Gerçek FK'ler call'da: agent / agent_version (normal tablolar)
    call_body = pg_table_body(ddl3, "call") or ""
    add("AC fk:call->agent", "agent_id UUID REFERENCES agent(id)" in call_body, "agent_id gerçek FK")
    add("AC fk:call->agentver",
        "agent_version_id UUID REFERENCES agent_version(id)" in call_body, "agent_version_id gerçek FK")

    # AD. RLS: enable+force+policy + WITH CHECK (her 7 tablo standart izolasyon)
    for t in CALL_TABLES:
        add("AD rls:%s" % t, table_rls_ok(rls3, t), "ENABLE+FORCE+POLICY")
        add("AD with-check:%s" % t, has_with_check(rls3, t), "WITH CHECK (cross-tenant write koruması)")

    # AE. Fail-closed (iki-argümanlı current_setting + NULLIF) — 0007 politikaları
    add("AE fail-closed", fail_closed_ok(rls3), "current_setting('app.*', true) → GUC yoksa 0 satır")
    add("AE null-safe-uuid", null_safe_uuid_ok(rls3),
        "NULLIF(current_setting(...),'')::uuid — havuzda '' fail-error değil 0 satır (DB.md §6.2)")

    # AF. WORM (tool_execution): immutable trigger (0006) + grant INSERT+SELECT (0007)
    for t in CALL_WORM:
        add("AF worm-trigger:%s" % t, has_immutable_trigger(ddl3, t),
            "BEFORE UPDATE OR DELETE → raise_immutable_violation (DB.md §6.5)")
        add("AF worm-grant:%s" % t, worm_grant_ok(rls3, t),
            "app_rw yalnız INSERT+SELECT (UPDATE/DELETE yok)")
    add("AF worm-no-write",
        not re.search(r"GRANT[^;]*\b(UPDATE|DELETE)\b[^;]*ON tool_execution\b", norm(rls3)),
        "tool_execution'a UPDATE/DELETE grant yok")

    # AG. İdempotency: tool_execution UNIQUE (partition anahtarı created_at dahil)
    add("AG idempotency-unique",
        "UNIQUE (tenant_id, idempotency_key, created_at)" in (pg_table_body(ddl3, "tool_execution") or ""),
        "UNIQUE (tenant_id, idempotency_key, created_at) — FR-TOOL-009")

    # AH. DEFAULT partition (insert güvenlik ağı) + aylık partition yardımcısı
    for t in CALL_TABLES:
        add("AH default-part:%s" % t, default_partition_ok(ddl3, t),
            "CREATE TABLE IF NOT EXISTS %s_default PARTITION OF %s DEFAULT" % (t, t))
    add("AH month-helper",
        bool(re.search(r"FUNCTION\s+create_month_partition\s*\(", ddl3)),
        "create_month_partition() aylık partition önceden açma (DB.md §7.2)")

    # AI. İndeksler: tenant-zaman + FK/sorgu + GIN + retention partial
    for idx in ["ix_call_tenant_time", "ix_call_correlation", "ix_call_agent",
                "ix_leg_call", "ix_transcript_call", "ix_tsegment_transcript",
                "ix_recording_call", "ix_event_call", "ix_toolexec_call"]:
        add("AI index:%s" % idx, ("CREATE INDEX %s" % idx) in norm(ddl3), "FK/sorgu indeksi")
    add("AI gin:event-payload",
        bool(re.search(r"CREATE INDEX ix_event_payload ON call_event USING gin", norm(ddl3))),
        "call_event.payload GIN (DB.md §7.1)")
    add("AI partial:recording-retention",
        bool(re.search(r"CREATE INDEX ix_recording_retention ON recording \(retain_until\) WHERE legal_hold = false",
                       norm(ddl3))),
        "retention partial index (DB.md §9)")

    # AJ. Down migration'lar: tablolar + yardımcı + RLS politikaları düşer
    for t in CALL_TABLES:
        add("AJ down-drop:%s" % t,
            ("DROP TABLE IF EXISTS %s" % t) in norm(raw["0006d"]), "down DROP TABLE")
    add("AJ down-helper", "DROP FUNCTION IF EXISTS create_month_partition" in norm(raw["0006d"]),
        "down DROP FUNCTION create_month_partition")
    add("AJ down-policy", raw["0007d"].count("DROP POLICY") >= len(CALL_TABLES), "down DROP POLICY")

    # AK. İzlenebilirlik: çağrı/etkileşim kaynak token'ları DB.md'de
    for tok in CALL_TRACE_TOKENS:
        add("AK trace:%s" % tok, tok in dbmd, "DB.md'de kaynak referans")

    # Rapor
    passed = sum(1 for _, ok, _ in checks if ok)
    total = len(checks)
    failed = [(c, d) for c, ok, d in checks if not ok]
    print("== schema_probe validate — 1.1.1 (Tenant/Org/User/Role) + 1.1.2 (Agent/Config) + 1.1.3 (Çağrı/Etkileşim) + RLS ==")
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

    # has_immutable_trigger (WORM)
    worm_good = ("CREATE TRIGGER trg_x BEFORE UPDATE OR DELETE ON agent_version "
                 "FOR EACH ROW EXECUTE FUNCTION raise_immutable_violation();")
    worm_bad = ("CREATE TRIGGER trg_x BEFORE UPDATE ON agent_version "
                "FOR EACH ROW EXECUTE FUNCTION set_updated_at();")
    check("worm-trigger:good", has_immutable_trigger(worm_good, "agent_version") is True)
    check("worm-trigger:bad", has_immutable_trigger(worm_bad, "agent_version") is False)

    # worm_grant_ok (yalnız INSERT+SELECT)
    g_good = "REVOKE ALL ON agent_version FROM app_rw; GRANT SELECT, INSERT ON agent_version TO app_rw;"
    g_bad = "GRANT SELECT, INSERT, UPDATE, DELETE ON agent_version TO app_rw;"
    check("worm-grant:good", worm_grant_ok(g_good, "agent_version") is True)
    check("worm-grant:bad", worm_grant_ok(g_bad, "agent_version") is False)

    # deferred_circular_fk_ok
    fk_good = ("CREATE TABLE agent (\n  id UUID PRIMARY KEY DEFAULT gen_uuid_v7(),\n"
               "  active_version_id UUID,\n  tenant_id UUID NOT NULL REFERENCES tenant(id)\n);\n"
               "ALTER TABLE agent ADD CONSTRAINT fk_a FOREIGN KEY (active_version_id) "
               "REFERENCES agent_version(id) ON DELETE RESTRICT;")
    fk_bad = ("CREATE TABLE agent (\n  id UUID PRIMARY KEY DEFAULT gen_uuid_v7(),\n"
              "  active_version_id UUID REFERENCES agent_version(id),\n"
              "  tenant_id UUID NOT NULL REFERENCES tenant(id)\n);")
    check("circular-fk:good", deferred_circular_fk_ok(fk_good) is True)
    check("circular-fk:bad-inline", deferred_circular_fk_ok(fk_bad) is False)

    # pg_table_body / is_partitioned (1.1.3 partition'lı tablolar)
    part_good = ("CREATE TABLE call (\n  id UUID NOT NULL DEFAULT gen_uuid_v7(),\n"
                 "  tenant_id UUID NOT NULL REFERENCES tenant(id),\n"
                 "  PRIMARY KEY (id, created_at)\n) PARTITION BY RANGE (created_at);")
    part_plain = ("CREATE TABLE foo (\n  id UUID PRIMARY KEY DEFAULT gen_uuid_v7()\n);")
    pbody = pg_table_body(part_good, "call")
    check("pg_table_body:found", pbody is not None)
    check("pg_table_body:has-pk", "PRIMARY KEY (id, created_at)" in (pbody or ""))
    check("is_partitioned:good", is_partitioned(part_good, "call") is True)
    check("is_partitioned:plain", is_partitioned(part_plain, "foo") is False)
    # düz table_body partition'lı tabloyu yakalamamalı (regex `);` ile biter)
    check("table_body:not-partitioned", table_body(part_good, "call") is None)

    # null_safe_uuid_ok (NULLIF boş-string koruması)
    ns_good = "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    ns_bare = "USING (tenant_id = current_setting('app.tenant_id', true)::uuid)"
    check("null-safe:good", null_safe_uuid_ok(ns_good) is True)
    check("null-safe:bare", null_safe_uuid_ok(ns_bare) is False)
    check("null-safe:none", null_safe_uuid_ok("USING (true)") is False)

    # default_partition_ok
    dp_good = "CREATE TABLE IF NOT EXISTS call_default PARTITION OF call DEFAULT;"
    check("default-part:good", default_partition_ok(dp_good, "call") is True)
    check("default-part:bad", default_partition_ok("CREATE TABLE x();", "call") is False)

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
        "task": "WBS 1.1.1 (Tenant/Org/User/Role) + 1.1.2 (Agent/Config) + 1.1.3 (Çağrı/Etkileşim) PostgreSQL şeması + RLS",
        "source": ["BRD §16 (1–24)", "SAD §13.1", "DB.md §5.1/§5.2/§5.5/§6/§7.2"],
        "tables": ALL_TABLES,
        "tenant_scoped": TENANT_SCOPED,
        "global_tables": GLOBAL_TABLES,
        "rls_tables": RLS_TABLES,
        "uuidv7_pk": UUIDV7_PK,
        "expected_roles": EXPECTED_ROLES,
        "trace_tokens": TRACE_TOKENS,
        "agent_tables": AGENT_TABLES,
        "agent_worm": AGENT_WORM,
        "agent_trace_tokens": AGENT_TRACE_TOKENS,
        "call_tables": CALL_TABLES,
        "call_worm": CALL_WORM,
        "call_partitioned": CALL_TABLES,
        "call_trace_tokens": CALL_TRACE_TOKENS,
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
