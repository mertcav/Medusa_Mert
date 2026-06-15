#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 7.2.5 — CRM/Ticketing/ERP referans entegrasyonu (pilot) (BRD §6.1 / OBJ-07) referans probe.

7.x tool hattının PİLOT KAPSTONU: yeni transport/SPI EKLEMEZ — önceki parçaları SAD §11.1
Tool Yürütme Hattının ([1]→[7]) BİREBİR sırasında ORKESTRE ederek temsilci CRM/Ticketing/ERP
sistemlerine karşı uçtan uca gerçek işlem (read+write) gösterir:

  LLM tool call ─► [1] schema (7.1.1) ─► [2] authz (7.1.2) ─► [3] policy gate {kritik→teyit/step-up}
                ─► [4] idempotency (7.1.3) ─► [5] allowlist (7.2.3) + GW {timeout/retry/breaker, 7.1.4}
                ─► connector.upstream_call (7.2.1/7.2.2) ─► AttemptOutcome
                ─► [6] output schema (7.1.1) + error normalization (7.1.5)
                ─► [7] correlation_id audit (7.1.6) + Tool Execution kaydı (BRD §16/24)

Bu modül ŞUNU SAHİPLENİR: referans tool tanımları (BRD §8 senaryo eşli) + zincir sıralama/fail-closed
kompozisyon + kritik-işlem policy gate bağı (FR-TOOL-006/007) + Tool Execution audit kaydı.

ÇEKİRDEK INVARIANT (SR-TOOL-001 'Her connector tipi başarılı çağrı yapar' + OBJ-07):
pilot paketleri REST (CRM/ticketing) + GraphQL (ticketing) + SOAP (ERP) tiplerinin her birinde
read+write başarılı uçtan-uca çağrı yapar; zincir [1]→[7] fail-closed yürür.

Kapsam dışı (bilinçli, başka modül SAHİBİ): schema motoru→7.1.1; authz motoru→7.1.2; retry/breaker→7.1.4;
kanonik istek/transport→7.2.1/7.2.2; allowlist kararı→7.2.3; idempotency üretimi→7.1.3; müşteri hata
METNİ kataloğu→7.1.5; audit store→7.1.6; async reconcile→7.2.4; kritik-işlem TAM durum makinesi→7.3;
PCI kart akışı→17.2.6.

Kullanım:
  reference_integration_probe.py validate          Statik spec/config/pack/kapsama kapısı → çıkış kodu
  reference_integration_probe.py run <sample>      Zincir-yürütücü: invocation(lar)ı [1]→[7] çalıştır → kapı (R1–R12)
  reference_integration_probe.py selftest          Gömülü davranış kontrolleri → çıkış kodu
  reference_integration_probe.py schema            Zincir/tool-def/sonuç sözleşmesini yazdır

Determinizm: sanal saat (at_ms); Date.now/gerçek-rastgele YOK. Stdlib-only.
Sır/credential ve gerçek PII değeri üretilmez/yazılmaz (fixture'lar sentetik — FR-TST-008; host'lar example.com).
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "reference-integration-spec.json")
CONFIG_PATH = os.path.join(HERE, "config", "reference-packs.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

# ── Fault taksonomisi (7.1.4/7.2.1 ile hizalı) + zincir-üretimi gate fault'ları ─────
RETRYABLE_FAULTS = {"TIMEOUT", "UPSTREAM_5XX", "CONN_RESET", "CONN_REFUSED", "RATE_LIMITED", "DEADLINE_EXCEEDED"}
TERMINAL_FAULTS = {"UPSTREAM_4XX", "SCHEMA_INVALID", "AUTH_FAILED", "NOT_FOUND"}
GW_FAULTS = {"CIRCUIT_OPEN", "RETRY_EXHAUSTED"}  # 7.1.4 üretir; connector değil
DISPATCH_FAULTS = RETRYABLE_FAULTS | TERMINAL_FAULTS | GW_FAULTS
# Zincirin (pre-dispatch) ürettiği kararlar:
GATE_FAULTS = {"IDEMPOTENCY_REQUIRED", "ENDPOINT_NOT_ALLOWED", "CONFIRMATION_REQUIRED"}

READ_SCOPE_RE = re.compile(r"^[a-z][a-z0-9_]*:read(:[a-z0-9_]+)?$")
WRITE_SCOPE_RE = re.compile(r"^[a-z][a-z0-9_]*:write(:[a-z0-9_]+)?$")
SCOPE_RE = re.compile(r"^[a-z][a-z0-9_]*:(read|write)(:[a-z0-9_]+)?$")
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")
CONNECTOR_TYPES = {"rest", "graphql", "soap", "webhook"}

INVARIANT_IDS = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10", "R11", "R12"]
ERROR_CLASSES = {"UNKNOWN_PACK", "UNKNOWN_TOOL", "INVALID_TOOL_DEF", "INVALID_INVOCATION",
                 "LITERAL_SECRET_IN_CONFIG", "NON_MONOTONIC_CLOCK", "INTERNAL_ERROR"}

# fault → müşteri kategorisi (7.1.5 ile hizalı; DELEGE)
FAULT_TO_CATEGORY = {
    "TIMEOUT": "TEMPORARY", "UPSTREAM_5XX": "TEMPORARY", "CONN_RESET": "TEMPORARY",
    "CONN_REFUSED": "TEMPORARY", "DEADLINE_EXCEEDED": "TEMPORARY", "CIRCUIT_OPEN": "TEMPORARY",
    "RETRY_EXHAUSTED": "TEMPORARY",
    "RATE_LIMITED": "BUSY",
    "UPSTREAM_4XX": "CANNOT_COMPLETE", "SCHEMA_INVALID": "CANNOT_COMPLETE",
    "IDEMPOTENCY_REQUIRED": "CANNOT_COMPLETE", "INTERNAL_ERROR": "CANNOT_COMPLETE",
    "NOT_FOUND": "NOT_FOUND",
    "AUTH_FAILED": "NOT_PERMITTED", "ENDPOINT_NOT_ALLOWED": "NOT_PERMITTED",
}

# Güvenli (teknik-detaysız) müşteri mesajları (tr-TR; tam katalog/locale → 7.1.5)
SAFE_MSG = {
    "TEMPORARY": "Şu anda işlemi tamamlayamadım, lütfen biraz sonra tekrar deneyelim.",
    "BUSY": "Sistem şu anda yoğun, kısa süre sonra tekrar deneyebiliriz.",
    "CANNOT_COMPLETE": "Bu işlemi şu anda tamamlayamıyorum.",
    "NOT_FOUND": "Aradığınız kaydı bulamadım.",
    "NOT_PERMITTED": "Bu işlem için gerekli yetkilendirme bulunmuyor.",
    "UNKNOWN": "Beklenmeyen bir durum oluştu.",
    "CONFIRMATION": "Devam etmeden önce onayınızı almam gerekiyor.",
}

# ── Sızıntı tarayıcı (R7/R8; 7.1.5 deseniyle) — müşteri mesajı / audit'te teknik detay/PII yasak ─
LEAK_PATTERNS = [
    ("status_code", re.compile(r"\b[45]\d\d\b")),
    ("ip", re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")),
    ("url", re.compile(r"https?://|\.example\.com|/graphql|/soap/")),
    ("path", re.compile(r"/(?:var|usr|etc|opt|home)/|[a-z0-9_]+\.(?:py|java|go|rb|js|sql)\b")),
    ("hex_uuid", re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}\b", re.I)),
    ("long_hex", re.compile(r"\b[0-9a-f]{16,}\b", re.I)),
    ("stack", re.compile(r"(?i)\b(exception|traceback|stacktrace|stack trace|nullpointer|segfault|panic)\b")),
    ("sql", re.compile(r"(?i)\b(select\s+\*|from\s+\w+\s+where|sqlstate|ora-\d|pg::|psycopg)\b")),
    ("fault_token", re.compile(r"\b(UPSTREAM_[45]XX|CONN_RE(SET|FUSED)|CIRCUIT_OPEN|RETRY_EXHAUSTED|SCHEMA_INVALID)\b")),
    ("vendor", re.compile(r"(?i)\b(salesforce|zendesk|servicenow|sap\s|hubspot|jira|nginx|apache|tomcat|openssl)\b")),
]
PII_PATTERNS = [
    ("email", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")),
    ("long_digits", re.compile(r"\b\d{6,}\b")),          # kart/telefon/poliçe
    ("secret", re.compile(r"(?i)\b(bearer\s+\S+|password|client[_-]?secret|api[_-]?key\s*[:=])")),
]


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _strip_meta(d):
    """Meta anahtarlarını ($comment/trace/desc) iterasyondan ele (eventstream/7.1.5 deseni)."""
    if isinstance(d, dict):
        return {k: v for k, v in d.items() if not k.startswith("$") and k not in ("trace", "$comment")}
    return d


def _scan(text, patterns):
    hits = []
    if not isinstance(text, str):
        text = json.dumps(text, ensure_ascii=False)
    for name, rx in patterns:
        if rx.search(text):
            hits.append(name)
    return hits


# ════════════════════════════════════════════════════════════════════════════
#  Zincir-yürütücü (SAD §11.1 [1]→[7]) — referans entegrasyon kompozisyonu
# ════════════════════════════════════════════════════════════════════════════
class ChainError(Exception):
    def __init__(self, error_class, msg=""):
        super().__init__("%s: %s" % (error_class, msg))
        self.error_class = error_class


def _tool_def(spec, tool_id):
    for pack_name, pack in _strip_meta(spec["packs"]).items():
        tools = pack.get("tools", {})
        if tool_id in tools:
            td = dict(tools[tool_id])
            td["_pack"] = pack_name
            td["_connector_type"] = pack["connector_type"]
            return td
    return None


def execute_chain(spec, inv):
    """Tek invocation'ı zincir [1]→[7] boyunca yürütür → ToolExecutionResult.

    inv alanları: call_id, correlation_id, tenant_id, tool, granted_scopes[],
      schema_valid(bool, default True), confirmation(bool), step_up(bool),
      idempotency_key(str|null), allowlist('PERMIT'|'DENY'|None→fail-closed DENY),
      attempt{result: ok|fault|accepted, fault_class?, status_code?, retryable?, result_ref?},
      at_ms, unsafe_customer_message(degraded), unsafe_audit_detail(degraded).
    """
    tid = inv.get("tool")
    td = _tool_def(spec, tid)
    if td is None:
        raise ChainError("UNKNOWN_TOOL", str(tid))
    for f in ("call_id", "correlation_id", "tenant_id"):
        if not inv.get(f):
            raise ChainError("INVALID_INVOCATION", "eksik %s" % f)

    op_class = td["operation_class"]
    verdicts = []        # [(step_id, verdict)] — düşük kardinalite (R8)
    status = None
    fault_class = None

    def step(sid, ok):
        verdicts.append((sid, "pass" if ok else "fail"))

    # [1] input schema (FR-TOOL-002; 7.1.1) — fail-closed yalnız açıkça False
    schema_valid = inv.get("schema_valid", True)
    step("input_schema", bool(schema_valid))
    if not schema_valid:
        status, fault_class = "rejected", "SCHEMA_INVALID"

    # [2] authorization (FR-TOOL-004/005; 7.1.2) — required_scope ⊆ granted; write→write-seviye
    if status is None:
        granted = set(inv.get("granted_scopes", []))
        need = td["required_scope"]
        ok = need in granted
        step("authorization", ok)
        if not ok:
            status, fault_class = "rejected", "AUTH_FAILED"

    # [3] policy gate (FR-TOOL-006/007) — kritik → teyit ∧ step-up ZORUNLU (bağ; tam FSM 7.3)
    if status is None:
        if td.get("critical"):
            ok = bool(inv.get("confirmation")) and bool(inv.get("step_up"))
            step("policy_gate", ok)
            if not ok:
                status, fault_class = "blocked", "CONFIRMATION_REQUIRED"
        else:
            step("policy_gate", True)

    # [4] idempotency (FR-TOOL-009; 7.1.3) — write → key VARLIĞI ZORUNLU
    if status is None:
        if op_class == "write":
            ok = bool(inv.get("idempotency_key"))
            step("idempotency", ok)
            if not ok:
                status, fault_class = "rejected", "IDEMPOTENCY_REQUIRED"
        else:
            step("idempotency", True)

    # [5a] allowlist (FR-TOOL-012; 7.2.3) — fail-closed: PERMIT değilse DENY
    if status is None:
        decision = inv.get("allowlist")
        ok = (decision == "PERMIT")
        step("allowlist", ok)
        if not ok:
            status, fault_class = "rejected", "ENDPOINT_NOT_ALLOWED"

    # [5b] dispatch (FR-TOOL-001/003; 7.1.4 + 7.2.1/7.2.2 → AttemptOutcome)
    result_ref = None
    if status is None:
        attempt = inv.get("attempt")
        if not isinstance(attempt, dict) or "result" not in attempt:
            step("dispatch", False)             # fail-closed: AttemptOutcome yok
            status, fault_class = "failed", "INTERNAL_ERROR"
        else:
            r = attempt["result"]
            if r == "ok":
                step("dispatch", True)
                status = "committed" if op_class == "write" else "succeeded"
                result_ref = attempt.get("result_ref")
            elif r == "accepted":               # async kabul (7.2.4) — non-blocking
                step("dispatch", True)
                status = "pending"
                result_ref = attempt.get("result_ref")
            elif r == "fault":
                step("dispatch", False)
                status = "failed"
                fault_class = attempt.get("fault_class") or "INTERNAL_ERROR"
            else:
                step("dispatch", False)
                status, fault_class = "failed", "INTERNAL_ERROR"

    # [6] output schema + error normalization (FR-TOOL-008; 7.1.5 DELEGE)
    customer_category = None
    customer_message = None
    if status == "blocked":
        customer_message = SAFE_MSG["CONFIRMATION"]
    elif status in ("rejected", "failed"):
        customer_category = FAULT_TO_CATEGORY.get(fault_class, "UNKNOWN")
        # degraded: failsafe KAPALI → ham/kirli mesaj geçirilir (R7 tarayıcı yakalamalı)
        if inv.get("unsafe_customer_message"):
            customer_message = inv["unsafe_customer_message"]
        else:
            customer_message = SAFE_MSG.get(customer_category, SAFE_MSG["UNKNOWN"])
    verdicts.append(("output_norm", "pass"))

    # [7] correlation_id audit + Tool Execution kaydı (FR-TOOL-010; BRD §16/24; no-log)
    tool_execution_recorded = (status == "committed")
    audit = {
        "correlation_id": inv["correlation_id"],
        "tenant_id": inv["tenant_id"],
        "tool_id": tid,
        "pack": td["_pack"],
        "connector_type": td["_connector_type"],
        "operation_class": op_class,
        "critical": bool(td.get("critical")),
        "step_verdicts": verdicts,
        "status": status,
        "fault_class": fault_class,
        "customer_category": customer_category,
        "idempotency_present": bool(inv.get("idempotency_key")),
        "tool_execution_recorded": tool_execution_recorded,
        "result_ref": result_ref,
        "no_log": True,
    }
    if inv.get("unsafe_audit_detail"):          # degraded: ham PII/secret audit'e sızar (R8 yakalamalı)
        audit["_unsafe"] = inv["unsafe_audit_detail"]
    verdicts.append(("audit", "pass"))

    return {
        "call_id": inv["call_id"],
        "tool_id": tid,
        "pack": td["_pack"],
        "connector_type": td["_connector_type"],
        "operation_class": op_class,
        "critical": bool(td.get("critical")),
        "async_tool": bool(td.get("async")),
        "status": status,
        "fault_class": fault_class,
        "customer_category": customer_category,
        "customer_message": customer_message,
        "tool_execution_recorded": tool_execution_recorded,
        "result_ref": result_ref,
        "audit": audit,
    }


# ════════════════════════════════════════════════════════════════════════════
#  run <sample> — zincir + kapı (R1–R12)
# ════════════════════════════════════════════════════════════════════════════
def _check_result_gates(res):
    """Sonuç-başı invariant kapıları (her invocation için)."""
    fails = []
    # R7 — müşteri mesajında teknik detay / PII sızıntısı yok
    if res["customer_message"]:
        hits = _scan(res["customer_message"], LEAK_PATTERNS) + _scan(res["customer_message"], PII_PATTERNS)
        if hits:
            fails.append("R7 sızıntı (customer_message): %s" % ",".join(hits))
    # R8 — audit no-log: PII/secret yok
    audit_blob = json.dumps(res["audit"], ensure_ascii=False)
    a_hits = _scan(audit_blob, PII_PATTERNS)
    # audit'te secret-anahtar/bearer/email/uzun-rakam yasak; status_code/url zaten audit'te yok
    if a_hits:
        fails.append("R8 audit no-log sızıntı: %s" % ",".join(a_hits))
    # R5 — write+committed/pending → idempotency_key VARdı (kayıt için)
    if res["operation_class"] == "write" and res["status"] in ("committed", "pending"):
        if not res["audit"]["idempotency_present"]:
            fails.append("R5 write dispatch idempotency_key olmadan ilerledi")
    # R9 — committed write → tool_execution kaydı
    if res["status"] == "committed" and not res["tool_execution_recorded"]:
        fails.append("R9 committed write tool_execution üretmedi")
    if res["status"] != "committed" and res["tool_execution_recorded"]:
        fails.append("R9 committed-olmayan sonuç tool_execution üretti")
    # R4 — kritik tool yalnız committed/pending ise teyit/step-up geçmiş olmalı (blocked değilse)
    if res["critical"] and res["status"] in ("committed", "pending"):
        pg = dict(res["audit"]["step_verdicts"]).get("policy_gate")
        if pg != "pass":
            fails.append("R4 kritik tool policy_gate geçmeden dispatch oldu")
    # R3 — rejected+AUTH_FAILED veya rejected genel → dispatch verdict YOK (kısa devre)
    sv = dict(res["audit"]["step_verdicts"])
    if res["status"] in ("rejected", "blocked") and "dispatch" in sv:
        fails.append("R1 pre-dispatch red sonrası dispatch çalıştı (kısa-devre ihlali)")
    return fails


def run_cmd(path):
    spec = _load(SPEC_PATH)
    sample = _load(path)
    name = sample.get("name", os.path.basename(path))
    invs = sample.get("invocations", [])
    expect = sample.get("expect", {})
    expect_fail = bool(sample.get("expect_gate_fail"))
    print("▶ %s" % name)
    if sample.get("$comment"):
        print("  %s" % sample["$comment"])

    all_fails = []
    results = {}
    last_ms = -1
    for inv in invs:
        # determinizm/monoton saat
        ms = inv.get("at_ms", 0)
        if ms < last_ms:
            print("  ⚠ NON_MONOTONIC_CLOCK at_ms=%s < %s" % (ms, last_ms))
        last_ms = ms
        try:
            res = execute_chain(spec, inv)
        except ChainError as e:
            print("  ✗ %s → ChainError %s" % (inv.get("call_id"), e.error_class))
            all_fails.append("%s ChainError %s" % (inv.get("call_id"), e.error_class))
            continue
        results[res["call_id"]] = res
        gate_fails = _check_result_gates(res)
        all_fails += ["%s: %s" % (res["call_id"], f) for f in gate_fails]
        mark = "✓" if not gate_fails else "✗"
        print("  %s %s [%s/%s/%s] → status=%s fault=%s cat=%s%s%s"
              % (mark, res["call_id"], res["pack"], res["connector_type"], res["operation_class"],
                 res["status"], res["fault_class"], res["customer_category"],
                 " TE✓" if res["tool_execution_recorded"] else "",
                 (" GATE:" + ";".join(gate_fails)) if gate_fails else ""))
        # beklenen değerler
        exp = expect.get(res["call_id"])
        if exp:
            for k, v in exp.items():
                got = res.get(k)
                if got != v:
                    all_fails.append("%s beklenen %s=%r ama %r" % (res["call_id"], k, v, got))
                    print("      ✗ beklenen %s=%r ama %r" % (k, v, got))

    # determinizm (R10): ikinci kez çalıştır, birebir aynı mı
    for inv in invs:
        try:
            r2 = execute_chain(spec, inv)
        except ChainError:
            continue
        cid = r2["call_id"]
        if cid in results and json.dumps(r2, sort_keys=True, ensure_ascii=False) != json.dumps(results[cid], sort_keys=True, ensure_ascii=False):
            all_fails.append("R10 determinizm ihlali: %s" % cid)

    if expect_fail:
        if all_fails:
            print("  ✓ BEKLENEN ELEME (degraded): %d kapı tetiklendi → %s" % (len(all_fails), all_fails[0]))
            return 0
        print("  ✗ degraded sample geçmemeliydi ama tüm kapılar geçti")
        return 1
    if all_fails:
        print("  🔴 %d kapı eler" % len(all_fails))
        for f in all_fails:
            print("     - %s" % f)
        return 1
    print("  🟢 GEÇTİ (%d invocation)" % len(invs))
    return 0


# ════════════════════════════════════════════════════════════════════════════
#  validate — statik spec/config/pack/kapsama kapısı
# ════════════════════════════════════════════════════════════════════════════
def validate():
    spec = _load(SPEC_PATH)
    cfg = _load(CONFIG_PATH)
    checks = []

    def ck(cond, label):
        checks.append((bool(cond), label))

    ck(spec.get("wbs") == "7.2.5", "spec.wbs == 7.2.5")
    ck(spec.get("phase") == "F1", "spec.phase == F1")
    ck("FR-TOOL-001" in spec["trace"]["fr"], "trace FR-TOOL-001")
    ck("SR-TOOL-001" in spec["trace"]["srs"], "trace SR-TOOL-001")

    packs = _strip_meta(spec["packs"])
    ck(len(packs) >= 3, "≥3 pilot paket (CRM/ticketing/ERP)")
    ck({"crm", "ticketing", "erp"} <= set(packs), "crm+ticketing+erp paketleri var")

    # tool tanımı bütünlüğü
    all_tools = {}
    conn_types_seen = set()
    rw_by_type = {}  # connector_type -> {"read":bool,"write":bool}
    for pname, pack in packs.items():
        ct = pack.get("connector_type")
        ck(ct in CONNECTOR_TYPES, "%s connector_type geçerli (%s)" % (pname, ct))
        conn_types_seen.add(ct)
        rw_by_type.setdefault(ct, {"read": False, "write": False})
        tools = pack.get("tools", {})
        ck(len(tools) >= 1, "%s ≥1 tool" % pname)
        for tid, td in tools.items():
            all_tools[tid] = (pname, td)
            ck(td.get("operation"), "%s.operation var" % tid)
            ck(td.get("operation_class") in ("read", "write"), "%s.operation_class read|write" % tid)
            ck(SCOPE_RE.match(td.get("required_scope", "")), "%s.required_scope kaynak:eylem (%s)" % (tid, td.get("required_scope")))
            ck(bool(td.get("endpoint")), "%s.endpoint var" % tid)
            # write → idempotent=true; required_scope write-seviye
            if td.get("operation_class") == "write":
                ck(td.get("idempotent") is True, "%s write → idempotent=true" % tid)
                ck(WRITE_SCOPE_RE.match(td.get("required_scope", "")), "%s write → write-seviye scope" % tid)
                rw_by_type[ct]["write"] = True
            else:
                ck(READ_SCOPE_RE.match(td.get("required_scope", "")), "%s read → read-seviye scope" % tid)
                rw_by_type[ct]["read"] = True
            # critical → write
            if td.get("critical"):
                ck(td.get("operation_class") == "write", "%s critical → write" % tid)
            # endpoint host example.com (R11)
            ck("example.com" in td.get("endpoint", ""), "%s endpoint example.com (sentetik)" % tid)

    # R2 — connector-tipi kapsama: rest+graphql+soap; her tipte read+write
    ck({"rest", "graphql", "soap"} <= conn_types_seen, "R2 REST+GraphQL+SOAP connector tipleri kapsanır")
    for ct, rw in rw_by_type.items():
        ck(rw["read"] and rw["write"], "R2 %s tipinde read+write tool var" % ct)

    # config ↔ spec hizalama + sır kapısı (R11)
    cfg_packs = _strip_meta(cfg["packs"])
    for pname, p in cfg_packs.items():
        ck(pname in packs, "config paket %s spec'te var" % pname)
        ck(p.get("connector_type") == packs[pname]["connector_type"], "%s connector_type config↔spec" % pname)
        # auth.ref yalnız ${ENV}
        ref = (p.get("auth") or {}).get("ref")
        if (p.get("auth") or {}).get("type") not in (None, "none"):
            ck(ref and PLACEHOLDER_RE.match(ref), "%s auth.ref ${ENV} placeholder (%s)" % (pname, ref))
        # config.tools ⊆ spec pack tools
        for t in p.get("tools", []):
            ck(t in packs[pname]["tools"], "config tool %s spec pack'te var" % t)

    # fault → kategori kapsama (DELEGE 7.1.5)
    fmap = spec["fault_to_category"]["map"]
    for f in (DISPATCH_FAULTS | {"IDEMPOTENCY_REQUIRED", "ENDPOINT_NOT_ALLOWED"}):
        ck(f in fmap, "fault_to_category kapsar %s" % f)
        ck(fmap.get(f) == FAULT_TO_CATEGORY.get(f), "fault_to_category[%s] probe ile hizalı" % f)

    # invariant + statuses bütünlüğü
    inv_ids = [i["id"] for i in spec["invariants"]]
    ck(inv_ids == INVARIANT_IDS, "invariants R1–R12 tam ve sıralı")
    ck(set(spec["result_statuses"]["values"]) == {"succeeded", "committed", "pending", "rejected", "blocked", "failed"},
       "result_statuses tam")
    ck(spec["audit"].get("no_log") is True, "audit no_log=true")

    # literal sır taraması (spec + config — yorum/placeholder hariç)
    blob = json.dumps(spec, ensure_ascii=False) + json.dumps(cfg, ensure_ascii=False)
    # placeholder'ları çıkar, sonra şüpheli token ara
    stripped = re.sub(r"\$\{[A-Z0-9_]+\}", "", blob)
    secret_like = re.findall(r"(?i)(?:bearer\s+|sk-)[A-Za-z0-9/\+_\-]{20,}", stripped)
    ck(not secret_like, "literal sır yok (spec+config)")

    npass = sum(1 for ok, _ in checks if ok)
    ntot = len(checks)
    for ok, label in checks:
        if not ok:
            print("  ✗ %s" % label)
    print("validate: %d/%d 🟢" % (npass, ntot) if npass == ntot else "validate: %d/%d 🔴" % (npass, ntot))
    return 0 if npass == ntot else 1


# ════════════════════════════════════════════════════════════════════════════
#  selftest — gömülü davranış (R1–R12)
# ════════════════════════════════════════════════════════════════════════════
def _spec():
    return _load(SPEC_PATH)


def _base_inv(**over):
    inv = {"call_id": "c1", "correlation_id": "corr-1", "tenant_id": "t-1",
           "granted_scopes": [], "at_ms": 0}
    inv.update(over)
    return inv


def selftest():
    spec = _spec()
    results = []

    def t(name, cond):
        results.append((bool(cond), name))

    # 1. CRM read happy → succeeded (REST read)
    r = execute_chain(spec, _base_inv(tool="crm.get_customer", granted_scopes=["crm:read"],
                                      allowlist="PERMIT", attempt={"result": "ok"}))
    t("CRM read ok → succeeded", r["status"] == "succeeded" and r["connector_type"] == "rest")
    t("read başarısı tool_execution üretmez", not r["tool_execution_recorded"])

    # 2. CRM write committed → tool_execution (REST write)
    r = execute_chain(spec, _base_inv(tool="crm.create_case", granted_scopes=["crm:write"],
                                      idempotency_key="idem-1", allowlist="PERMIT",
                                      attempt={"result": "ok", "result_ref": "case://ref-7788"}))
    t("CRM write ok → committed", r["status"] == "committed")
    t("committed write → tool_execution kaydı", r["tool_execution_recorded"])
    t("result_ref taşınır", r["result_ref"] == "case://ref-7788")

    # 3. Ticketing GraphQL write committed (GraphQL coverage)
    r = execute_chain(spec, _base_inv(tool="ticketing.create_ticket", granted_scopes=["ticketing:write"],
                                      idempotency_key="idem-2", allowlist="PERMIT", attempt={"result": "ok"}))
    t("Ticketing GraphQL write → committed", r["status"] == "committed" and r["connector_type"] == "graphql")

    # 4. ERP SOAP read (SOAP coverage)
    r = execute_chain(spec, _base_inv(tool="erp.get_order", granted_scopes=["erp:read"],
                                      allowlist="PERMIT", attempt={"result": "ok"}))
    t("ERP SOAP read → succeeded", r["status"] == "succeeded" and r["connector_type"] == "soap")

    # 5. Async ERP appointment → pending, non-blocking (7.2.4)
    r = execute_chain(spec, _base_inv(tool="erp.create_appointment", granted_scopes=["erp:write"],
                                      idempotency_key="idem-3", allowlist="PERMIT",
                                      attempt={"result": "accepted", "result_ref": "exec://ap-1"}))
    t("async tool accepted → pending", r["status"] == "pending" and r["async_tool"])

    # 6. R3 authz — write tool, yalnız read scope → rejected AUTH_FAILED, dispatch YOK
    r = execute_chain(spec, _base_inv(tool="crm.create_case", granted_scopes=["crm:read"],
                                      idempotency_key="idem-4", allowlist="PERMIT", attempt={"result": "ok"}))
    t("R3 yetersiz scope → rejected AUTH_FAILED", r["status"] == "rejected" and r["fault_class"] == "AUTH_FAILED")
    t("R3 red → dispatch kısa-devre", "dispatch" not in dict(r["audit"]["step_verdicts"]))
    t("R3 AUTH_FAILED → müşteri NOT_PERMITTED", r["customer_category"] == "NOT_PERMITTED")

    # 7. R4 kritik op — teyit/step-up yok → blocked
    r = execute_chain(spec, _base_inv(tool="crm.update_contact", granted_scopes=["crm:write:pii"],
                                      idempotency_key="idem-5", allowlist="PERMIT", attempt={"result": "ok"}))
    t("R4 kritik+teyitsiz → blocked", r["status"] == "blocked" and r["fault_class"] == "CONFIRMATION_REQUIRED")
    t("R4 blocked → dispatch yok", "dispatch" not in dict(r["audit"]["step_verdicts"]))

    # 7b. R4 kritik op — teyit+step-up → committed
    r = execute_chain(spec, _base_inv(tool="crm.update_contact", granted_scopes=["crm:write:pii"],
                                      confirmation=True, step_up=True, idempotency_key="idem-6",
                                      allowlist="PERMIT", attempt={"result": "ok"}))
    t("R4 kritik+teyit+stepup → committed", r["status"] == "committed")

    # 7c. kritik op — yalnız teyit (step-up yok) → blocked
    r = execute_chain(spec, _base_inv(tool="erp.post_payment_adjustment", granted_scopes=["erp:write:finance"],
                                      confirmation=True, step_up=False, idempotency_key="idem-7",
                                      allowlist="PERMIT", attempt={"result": "ok"}))
    t("R4 para op step-up eksik → blocked", r["status"] == "blocked")

    # 8. R5 write — idempotency yok → rejected
    r = execute_chain(spec, _base_inv(tool="crm.create_case", granted_scopes=["crm:write"],
                                      allowlist="PERMIT", attempt={"result": "ok"}))
    t("R5 idempotency yok → rejected", r["status"] == "rejected" and r["fault_class"] == "IDEMPOTENCY_REQUIRED")

    # 9. R6 allowlist DENY → rejected, dispatch yok
    r = execute_chain(spec, _base_inv(tool="crm.get_customer", granted_scopes=["crm:read"],
                                      allowlist="DENY", attempt={"result": "ok"}))
    t("R6 allowlist DENY → rejected", r["status"] == "rejected" and r["fault_class"] == "ENDPOINT_NOT_ALLOWED")
    t("R6 DENY → müşteri NOT_PERMITTED", r["customer_category"] == "NOT_PERMITTED")

    # 9b. R1 fail-closed — allowlist kararı yok → DENY
    r = execute_chain(spec, _base_inv(tool="crm.get_customer", granted_scopes=["crm:read"],
                                      attempt={"result": "ok"}))
    t("R1 allowlist eksik → fail-closed rejected", r["status"] == "rejected")

    # 10. dispatch fault UPSTREAM_5XX → failed + müşteri TEMPORARY, teknik detay yok
    r = execute_chain(spec, _base_inv(tool="crm.get_customer", granted_scopes=["crm:read"],
                                      allowlist="PERMIT", attempt={"result": "fault", "fault_class": "UPSTREAM_5XX"}))
    t("UPSTREAM_5XX → failed TEMPORARY", r["status"] == "failed" and r["customer_category"] == "TEMPORARY")
    t("R7 customer_message sızıntısız", not (_scan(r["customer_message"], LEAK_PATTERNS) + _scan(r["customer_message"], PII_PATTERNS)))

    # 10b. NOT_FOUND → failed NOT_FOUND
    r = execute_chain(spec, _base_inv(tool="erp.get_order", granted_scopes=["erp:read"],
                                      allowlist="PERMIT", attempt={"result": "fault", "fault_class": "NOT_FOUND"}))
    t("NOT_FOUND → müşteri NOT_FOUND", r["customer_category"] == "NOT_FOUND")

    # 11. R7 sızıntı tarayıcı — kirli mesaj yakalanır
    r = execute_chain(spec, _base_inv(tool="crm.get_customer", granted_scopes=["crm:read"],
                                      allowlist="PERMIT",
                                      attempt={"result": "fault", "fault_class": "UPSTREAM_5XX"},
                                      unsafe_customer_message="NullPointerException at crm.example.com 503"))
    t("R7 kirli mesaj → tarayıcı tetiklenir", bool(_scan(r["customer_message"], LEAK_PATTERNS)))

    # 12. R8 audit — temiz audit'te PII yok
    r = execute_chain(spec, _base_inv(tool="crm.create_case", granted_scopes=["crm:write"],
                                      idempotency_key="idem-8", allowlist="PERMIT", attempt={"result": "ok"}))
    t("R8 temiz audit PII'siz", not _scan(json.dumps(r["audit"], ensure_ascii=False), PII_PATTERNS))
    # 12b. R8 kirli audit yakalanır
    r2 = execute_chain(spec, _base_inv(tool="crm.create_case", granted_scopes=["crm:write"],
                                       idempotency_key="idem-9", allowlist="PERMIT", attempt={"result": "ok"},
                                       unsafe_audit_detail="caller email john.doe@example.com card 4111111111111111"))
    t("R8 kirli audit → tarayıcı tetiklenir", bool(_scan(json.dumps(r2["audit"], ensure_ascii=False), PII_PATTERNS)))

    # 13. R10 determinizm
    a = execute_chain(spec, _base_inv(tool="crm.create_case", granted_scopes=["crm:write"],
                                      idempotency_key="idem-d", allowlist="PERMIT", attempt={"result": "ok"}))
    b = execute_chain(spec, _base_inv(tool="crm.create_case", granted_scopes=["crm:write"],
                                      idempotency_key="idem-d", allowlist="PERMIT", attempt={"result": "ok"}))
    t("R10 determinizm birebir", json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True))

    # 14. schema_invalid → rejected, kısa-devre
    r = execute_chain(spec, _base_inv(tool="crm.get_customer", granted_scopes=["crm:read"],
                                      schema_valid=False, allowlist="PERMIT", attempt={"result": "ok"}))
    t("schema_invalid → rejected", r["status"] == "rejected" and r["fault_class"] == "SCHEMA_INVALID")
    t("schema red → authz çalışmaz (kısa-devre)", "authorization" not in dict(r["audit"]["step_verdicts"]))

    # 15. unknown tool → ChainError
    try:
        execute_chain(spec, _base_inv(tool="crm.nonexistent"))
        t("unknown tool → ChainError", False)
    except ChainError as e:
        t("unknown tool → ChainError UNKNOWN_TOOL", e.error_class == "UNKNOWN_TOOL")

    # 16. R2 connector-tipi kapsama (spec)
    packs = _strip_meta(spec["packs"])
    cts = {p["connector_type"] for p in packs.values()}
    t("R2 REST+GraphQL+SOAP kapsanır", {"rest", "graphql", "soap"} <= cts)

    npass = sum(1 for ok, _ in results if ok)
    for ok, name in results:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print("selftest: %d/%d %s" % (npass, len(results), "🟢" if npass == len(results) else "🔴"))
    return 0 if npass == len(results) else 1


# ════════════════════════════════════════════════════════════════════════════
def schema_cmd():
    out = {
        "module": "reference-integration (WBS 7.2.5)",
        "chain_steps": ["input_schema(7.1.1)", "authorization(7.1.2)", "policy_gate(7.3 bağ)",
                        "idempotency(7.1.3)", "allowlist(7.2.3)", "dispatch(7.1.4+7.2.1/7.2.2)",
                        "output_norm(7.1.5)", "audit(7.1.6+ToolExecution)"],
        "tool_def_fields": ["operation", "operation_class", "critical", "idempotent", "async",
                            "required_scope", "endpoint", "scenario"],
        "invocation_fields": ["call_id", "correlation_id", "tenant_id", "tool", "granted_scopes",
                              "schema_valid", "confirmation", "step_up", "idempotency_key",
                              "allowlist", "attempt", "at_ms"],
        "attempt_fields": ["result(ok|fault|accepted)", "fault_class", "status_code", "retryable", "result_ref"],
        "result_statuses": ["succeeded", "committed", "pending", "rejected", "blocked", "failed"],
        "fault_to_category": FAULT_TO_CATEGORY,
        "invariants": INVARIANT_IDS,
        "trace": "SAD §11.1/§11.2/§11.3, BRD §6.1/§8, OBJ-07, FR-TOOL-001..012, ADR-001/002",
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd = argv[1]
    if cmd == "validate":
        return validate()
    if cmd == "run":
        if len(argv) < 3:
            print("kullanım: reference_integration_probe.py run <sample.json>")
            return 2
        return run_cmd(argv[2])
    if cmd == "selftest":
        return selftest()
    if cmd == "schema":
        return schema_cmd()
    print("bilinmeyen komut: %s" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
