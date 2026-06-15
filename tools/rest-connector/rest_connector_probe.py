#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 7.2.1 — REST connector (SAD §11.2 Integration Gateway / FR-TOOL-001) referans probe.

    LLM tool call ──► [1] input schema ──► [2] authz ──► [3] policy gate ──► [4] idempotency
                  ──► [5] Integration GW {timeout+retry+breaker SARAR} ─► REST connector.upstream_call(req)  ◄── bu modül
                  ──► [6] output schema + error normalization ──► [7] correlation_id audit

7.1.4 (integration-gw) dayanıklılık motoru bir SPI noktası ilan etti: 'upstream_call(req) → AttemptOutcome;
referans deterministik attempts_script; canlıda gerçek REST/SOAP/GraphQL transport + connection pool (FR-RES-006)
AYNI imza arkasına'. Bu modül o seam'in REST/HTTP dilimini (FR-TOOL-001) uygular:
  • bildirimsel RestConnectorSpec + RestInvocation alır, kanonik HTTP isteği KURAR (C1; template binding);
  • vendor-neutral WIRE SPI üzerinden yürütür (C12; referans deterministik wire_script — gerçek ağ/credential YOK);
  • HTTP yanıtını → 7.1.4'ün TÜKETTİĞİ AttemptOutcome'a EŞLER: status → fault_class (C2), method → operation_class (C3);
  • RETRY/BREAKER ORKESTRE ETMEZ (C4 — o 7.1.4); yalnız TEK denemenin sonucunu üretir;
  • sır yalnız referansla (C5), audit no-log (C6), connection pooling FR-RES-006 (C7), bağlam taşıma (C8),
    determinizm (C9), enjeksiyon güvenli (C10), kanonik endpoint kimliği (C11).

INVARIANT (SR-TOOL-001 kabul ölçütü): 'REST connector başarılı çağrı yapar' + status→fault eşleme 7.1.4 ile hizalı.

Kapsam dışı (bilinçli): timeout/retry/breaker ORKESTRASYONU → 7.1.4 (FR-TOOL-003); allowlist → 7.2.3 (FR-TOOL-012);
SOAP/GraphQL/webhook → 7.2.2; input/output schema → 7.1.1; authz → 7.1.2; idempotency ÜRETİMİ → 7.1.3 (connector
key'i VARSA iletir); MÜŞTERİYE hata metni → 7.1.5; correlation_id audit zenginleştirme → 7.1.6; async workflow → 7.2.4.

Kullanım:
  rest_connector_probe.py validate            Statik spec/config/şema kapısı → çıkış kodu
  rest_connector_probe.py call <sample>       Deterministik REST çağrı(lar)ı — istek kur + wire + eşle → kapı (C1–C12)
  rest_connector_probe.py selftest            Gömülü davranış kontrolleri → çıkış kodu
  rest_connector_probe.py schema              SPI/AttemptOutcome/karar sözleşmesini yazdır

Determinizm: sanal saat (at_ms); Date.now/gerçek-rastgele YOK. Stdlib-only.
Sır/credential ve gerçek PII değeri üretilmez/yazılmaz (fixture'lar sentetik — FR-TST-008; host'lar example.com).
"""
import json
import os
import re
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "rest-connector-spec.json")
CONFIG_PATH = os.path.join(HERE, "config", "rest-connector-profiles.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

# ── Fault taksonomisi (7.1.4 integration-gw ile BİREBİR hizalı; C2) ─────────────
RETRYABLE_FAULTS = {"TIMEOUT", "UPSTREAM_5XX", "CONN_RESET", "CONN_REFUSED", "RATE_LIMITED", "DEADLINE_EXCEEDED"}
TERMINAL_FAULTS = {"UPSTREAM_4XX", "SCHEMA_INVALID", "AUTH_FAILED", "NOT_FOUND"}
GATEWAY_FAULTS = {"CIRCUIT_OPEN", "RETRY_EXHAUSTED"}  # connector ASLA üretmez (7.1.4'e ait)
EMITTABLE_FAULTS = RETRYABLE_FAULTS | TERMINAL_FAULTS

GATE_IDS = ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10", "C11", "C12"]

ERROR_CLASSES = {
    "MISSING_CONNECTOR_CONFIG", "INVALID_CONNECTOR_SPEC", "UNKNOWN_OPERATION", "MISSING_PATH_PARAM",
    "LITERAL_SECRET_IN_SPEC", "INJECTION_REJECTED", "INVALID_INVOCATION", "NON_MONOTONIC_CLOCK", "INTERNAL_ERROR",
}

READ_METHODS = {"GET", "HEAD", "OPTIONS"}
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Status → fault_class eşlemesi (özel kodlar; aksi 4xx/5xx bant)
STATUS_FAULT = {408: "TIMEOUT", 429: "RATE_LIMITED", 401: "AUTH_FAILED", 403: "AUTH_FAILED",
                404: "NOT_FOUND", 422: "SCHEMA_INVALID"}
WIRE_FAULT = {"timeout": "TIMEOUT", "conn_reset": "CONN_RESET", "conn_refused": "CONN_REFUSED"}

PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")
# Literal sır şüphesi: uzun token benzeri değer (placeholder DEĞİL)
LITERAL_SECRET_RE = re.compile(r"(?i)(?:bearer\s+|sk[-_]|tok[-_]|key[-_]|secret[-_])?[A-Za-z0-9/\+_\-]{20,}")
SECRET_KEY_RE = re.compile(r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer|client[_-]?secret|access[_-]?token)\b"
                           r"\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}")
CREDIT_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,16}\b")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")  # CRLF dahil kontrol karakterleri (C10)
TEMPLATE_RE = re.compile(r"\{([A-Za-z0-9_]+)\}")


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_placeholder(v):
    return isinstance(v, str) and PLACEHOLDER_RE.match(v) is not None


def _strip_meta(d):
    return {k: v for k, v in d.items() if not k.startswith("$")}


class ConnectorError(Exception):
    def __init__(self, error_class, reason=""):
        super().__init__(reason)
        self.error_class = error_class
        self.reason = reason


# ── REST connector (vendor-neutral transport SPI gerçeklemesi) ───────────────────
class RestConnector:
    """Bir RestConnectorSpec için upstream_call(invocation) → AttemptOutcome.

    Connection pool durumu (C7/FR-RES-006) instance ömrü boyunca kalıcıdır → ardışık
    çağrılar aynı host'a warm-reuse olur. RETRY/BREAKER YOK (C4 — 7.1.4).
    """

    def __init__(self, spec, redact_audit=True):
        self.spec = spec
        self.redact_audit = redact_audit  # default True; degraded fixture False'a çevirip C6 gate'i sınar
        self.audit = []
        self.clock_ms = 0
        self._pool = {}  # pool_key -> {"last_used_ms": int, "count": int}
        self._validate_spec()

    # — spec doğrulama (C5 literal sır + yapı) —
    def _validate_spec(self):
        spec = self.spec
        for k in ("connector_id", "base_url", "operations"):
            if k not in spec:
                raise ConnectorError("INVALID_CONNECTOR_SPEC", "eksik alan: %s" % k)
        if not isinstance(spec["operations"], dict) or not spec["operations"]:
            raise ConnectorError("INVALID_CONNECTOR_SPEC", "operations boş")
        scheme = urllib.parse.urlsplit(spec["base_url"]).scheme
        if scheme not in ("http", "https"):
            raise ConnectorError("INVALID_CONNECTOR_SPEC", "base_url scheme http/https olmalı")
        # C5: literal sır taraması — auth.ref ve default_headers değerleri placeholder olmalı
        auth = spec.get("auth") or {}
        if auth.get("type", "none") != "none":
            ref = auth.get("ref", "")
            if not _is_placeholder(ref):
                raise ConnectorError("LITERAL_SECRET_IN_SPEC", "auth.ref placeholder ${ENV} olmalı")
        for hk, hv in (spec.get("default_headers") or {}).items():
            if isinstance(hv, str) and not _is_placeholder(hv) and LITERAL_SECRET_RE.fullmatch(hv.strip()):
                raise ConnectorError("LITERAL_SECRET_IN_SPEC", "default_headers.%s literal sır şüphesi" % hk)
        for opn, op in spec["operations"].items():
            if "method" not in op or "path" not in op:
                raise ConnectorError("INVALID_CONNECTOR_SPEC", "operation %s method/path eksik" % opn)
            if op["method"].upper() not in READ_METHODS | WRITE_METHODS:
                raise ConnectorError("INVALID_CONNECTOR_SPEC", "operation %s bilinmeyen method" % opn)

    def _pool_cfg(self):
        p = self.spec.get("pool") or {}
        return (int(p.get("max_per_host", 8)), int(p.get("keepalive_ms", 30000)),
                float(p.get("connect_overhead_ms", 40.0)))

    @staticmethod
    def _operation_class(method):
        return "read" if method in READ_METHODS else "write"

    @staticmethod
    def _check_injection(value, where):
        if isinstance(value, str) and CTRL_RE.search(value):
            raise ConnectorError("INJECTION_REJECTED", "%s kontrol karakteri (CRLF)" % where)

    def _build_request(self, op, inv):
        """Kanonik HTTP isteği kur (C1/C8/C10/C11). request_meta + endpoint döner."""
        method = op["method"].upper()
        path_tpl = op["path"]
        # endpoint kimliği: interpolesiz template (C11)
        endpoint = "%s %s%s" % (method, self.spec["base_url"].rstrip("/"), path_tpl)
        # path param binding (C10 enjeksiyon + MISSING_PATH_PARAM)
        params = inv.get("path_params") or {}
        needed = set(TEMPLATE_RE.findall(path_tpl))
        for name in needed:
            if name not in params:
                raise ConnectorError("MISSING_PATH_PARAM", "path param yok: %s" % name)
        bound_path = path_tpl
        for name in needed:
            val = str(params[name])
            self._check_injection(val, "path_param %s" % name)
            bound_path = bound_path.replace("{%s}" % name, urllib.parse.quote(val, safe=""))
        url = self.spec["base_url"].rstrip("/") + bound_path
        # query (C10; sıralı → determinizm C1/C9)
        qp = dict(op.get("query") or {})
        qp.update(inv.get("query_params") or {})
        for qk, qv in qp.items():
            self._check_injection(str(qv), "query %s" % qk)
        if qp:
            url += "?" + urllib.parse.urlencode(sorted(qp.items()))
        # headers (C5 sır referansla + C8 bağlam taşıma)
        header_names = []
        idempotency_forwarded = False
        # default headers (placeholder sır → <ref:ENV> sentinel; gerçek değer çözülmez/loglanmaz)
        for hk in sorted((self.spec.get("default_headers") or {}).keys()):
            header_names.append(hk)
        auth = self.spec.get("auth") or {}
        if auth.get("type", "none") != "none":
            self._check_injection(auth.get("header", ""), "auth header")
            header_names.append(auth.get("header", "Authorization"))
        if op.get("content_type") and method in WRITE_METHODS:
            header_names.append("Content-Type")
        if op.get("accept"):
            header_names.append("Accept")
        # C8: correlation_id daima; idempotency_key VARSA write'ta
        corr = inv.get("correlation_id", "")
        self._check_injection(corr, "correlation_id")
        header_names.append("X-Correlation-Id")
        op_class = self._operation_class(method)
        idem = inv.get("idempotency_key")
        if idem and op_class == "write":
            self._check_injection(str(idem), "idempotency_key")
            header_names.append("Idempotency-Key")
            idempotency_forwarded = True
        return {
            "method": method, "url": url, "endpoint": endpoint, "operation_class": op_class,
            "header_names": sorted(set(header_names)), "idempotency_forwarded": idempotency_forwarded,
        }

    def _pool_decision(self, url, timeout_ms):
        """Pool reuse/cold kararı (C7). pooled bool + connect_overhead döner."""
        sp = urllib.parse.urlsplit(url)
        key = "%s://%s" % (sp.scheme, sp.netloc)
        max_per_host, keepalive_ms, connect_overhead = self._pool_cfg()
        ent = self._pool.get(key)
        warm = ent is not None and (self.clock_ms - ent["last_used_ms"]) <= keepalive_ms and ent["count"] >= 1
        if warm:
            ent["last_used_ms"] = self.clock_ms
            return True, 0.0, key
        # cold connect (TLS handshake) — yeni bağlantı; max_per_host kapasitesi
        cnt = (ent["count"] if ent else 0)
        self._pool[key] = {"last_used_ms": self.clock_ms, "count": min(max_per_host, cnt + 1)}
        return False, connect_overhead, key

    @staticmethod
    def _map_status(status_code, success_codes):
        """HTTP status → (ok|fault, fault_class) (C2)."""
        is_success = (200 <= status_code <= 299) if success_codes is None else (status_code in success_codes)
        if is_success:
            return "ok", None
        if status_code in STATUS_FAULT:
            return "fault", STATUS_FAULT[status_code]
        if 500 <= status_code <= 599:
            return "fault", "UPSTREAM_5XX"
        if 400 <= status_code <= 499:
            return "fault", "UPSTREAM_4XX"
        # 1xx/3xx beklenmeyen → terminal generic 4xx-benzeri (güvenli taraf)
        return "fault", "UPSTREAM_4XX"

    def upstream_call(self, inv):
        """Tek REST denemesini yürüt → AttemptOutcome (7.1.4'ün tükettiği SPI şekli)."""
        if not isinstance(inv, dict) or "operation" not in inv or "call_id" not in inv:
            raise ConnectorError("INVALID_INVOCATION", "operation/call_id eksik")
        opn = inv["operation"]
        op = self.spec["operations"].get(opn)
        if op is None:
            raise ConnectorError("UNKNOWN_OPERATION", "operation yok: %s" % opn)
        # sanal saat
        if "at_ms" in inv:
            at = int(inv["at_ms"])
            if at < self.clock_ms:
                raise ConnectorError("NON_MONOTONIC_CLOCK", "at_ms < clock_ms")
            self.clock_ms = at

        req = self._build_request(op, inv)  # C1/C8/C10/C11 (enjeksiyon burada reddedilebilir)
        timeout_ms = float(op.get("timeout_ms", self.spec.get("default_timeout_ms", 2000)))
        success_codes = op.get("success_codes")
        if success_codes is not None:
            success_codes = set(success_codes)

        # pool kararı (C7)
        pooled, connect_overhead, _key = self._pool_decision(req["url"], timeout_ms)

        # wire (C12 — vendor-neutral seam; referans wire_script)
        script = inv.get("wire_script") or []
        wire = script[0] if script else {"result": "status", "status_code": 200, "latency_ms": 30.0}
        wresult = wire.get("result", "status")
        wlat = float(wire.get("latency_ms", 30.0))
        total_latency = connect_overhead + wlat

        status_code = None
        if wresult in ("ok", "status"):
            status_code = int(wire.get("status_code", 200))
            disp, fault_class = self._map_status(status_code, success_codes)
        elif wresult in WIRE_FAULT:
            disp, fault_class = "fault", WIRE_FAULT[wresult]
        else:
            disp, fault_class = "fault", "CONN_RESET"  # bilinmeyen wire → güvenli retryable

        # per-attempt TIMEOUT deadline (connect+transfer > timeout) — gecikme kesilir
        timed_out = False
        if disp != "fault" or fault_class not in ("TIMEOUT",):
            if total_latency > timeout_ms:
                disp, fault_class, timed_out = "fault", "TIMEOUT", True
                total_latency = timeout_ms
        else:
            total_latency = min(total_latency, timeout_ms)
            timed_out = True

        result = "ok" if disp == "ok" else "fault"
        retryable = (fault_class in RETRYABLE_FAULTS) if fault_class else False
        outcome = {
            "call_id": inv["call_id"], "result": result, "latency_ms": round(total_latency, 3),
            "fault_class": fault_class, "status_code": status_code,
            "operation_class": req["operation_class"], "endpoint": req["endpoint"],
            "retryable": retryable, "pooled": pooled, "timed_out": timed_out,
            "request_meta": {"method": req["method"], "header_names": req["header_names"],
                             "idempotency_forwarded": req["idempotency_forwarded"]},
        }
        self._audit(inv.get("correlation_id", ""), outcome)
        return outcome

    def _audit(self, corr, o):
        rec = {
            "correlation_id": corr, "endpoint": o["endpoint"], "method": o["request_meta"]["method"],
            "operation_class": o["operation_class"], "status_code": o["status_code"],
            "fault_class": o["fault_class"], "pooled": o["pooled"], "no_log": True,
        }
        if not self.redact_audit:
            # degraded knob: redaksiyon kapalı → ham istek meta'sı (query/header değerleri) audit'e sızar.
            # default True; bu yalnız C6 no-log gate'inin GERÇEK kapı olduğunu degraded fixture'da göstermek için.
            rec["raw_url"] = o.get("_raw_url_for_degraded", "")
        self.audit.append(rec)


# ── sample yürütme ───────────────────────────────────────────────────────────────
def _resolve_spec(sample):
    if "connector" in sample:
        return _strip_meta(sample["connector"])
    cfg = _load(CONFIG_PATH)
    prof = sample.get("profile")
    if prof and prof in cfg["profiles"]:
        return _strip_meta(cfg["profiles"][prof])
    return None


def _run_sample(sample):
    spec = _resolve_spec(sample)
    if spec is None:
        return {"error_class": "MISSING_CONNECTOR_CONFIG", "outcomes": [], "conn": None}
    redact = sample.get("redact_audit", True)
    try:
        conn = RestConnector(spec, redact_audit=redact)
    except ConnectorError as e:
        return {"error_class": e.error_class, "outcomes": [], "conn": None}
    outcomes = []
    for inv in sample.get("invocations", []):
        try:
            o = conn.upstream_call(inv)
        except ConnectorError as e:
            return {"error_class": e.error_class, "outcomes": outcomes, "conn": conn}
        # degraded: ham url'i audit'e taşımak için (yalnız redact=False fixture)
        if not redact:
            conn.audit[-1]["raw_url"] = conn._build_request(spec["operations"][inv["operation"]], inv)["url"] \
                if inv["operation"] in spec["operations"] else ""
        outcomes.append(o)
    return {"error_class": None, "outcomes": outcomes, "conn": conn}


# ── kapı denetimi (C1–C12) ───────────────────────────────────────────────────────
def _check_gates(sample, run):
    lines = []
    ok = True
    if run["error_class"]:
        expect_err = sample.get("expect_error_class")
        if expect_err == run["error_class"]:
            lines.append("  ✓ beklenen hata: %s" % run["error_class"])
            return True, lines
        lines.append("  ✗ hata: %s (beklenen %s)" % (run["error_class"], expect_err))
        return False, lines

    outcomes = run["outcomes"]
    by_id = {o["call_id"]: o for o in outcomes}

    # C2: emitted fault_class ∈ retryable∪terminal; connector gateway-fault üretmez
    for o in outcomes:
        if o["fault_class"] is not None and o["fault_class"] not in EMITTABLE_FAULTS:
            ok = False
            lines.append("  ✗ C2 emitlenemez fault_class %r (%s)" % (o["fault_class"], o["call_id"]))
        if o["fault_class"] in GATEWAY_FAULTS:
            ok = False
            lines.append("  ✗ C2 connector gateway-fault üretti %r (%s)" % (o["fault_class"], o["call_id"]))
    # C2 tutarlılık: retryable bayrağı taksonomi ile uyumlu
    for o in outcomes:
        want_retry = (o["fault_class"] in RETRYABLE_FAULTS) if o["fault_class"] else False
        if o["retryable"] != want_retry:
            ok = False
            lines.append("  ✗ C2 retryable bayrağı tutarsız (%s)" % o["call_id"])

    # C3: operation_class read/write
    for o in outcomes:
        if o["operation_class"] not in ("read", "write"):
            ok = False
            lines.append("  ✗ C3 operation_class %r (%s)" % (o["operation_class"], o["call_id"]))

    # C11: endpoint interpolesiz template (interpole path_param değeri sızmamalı)
    for inv in sample.get("invocations", []):
        o = by_id.get(inv["call_id"])
        if not o:
            continue
        for pv in (inv.get("path_params") or {}).values():
            pv = str(pv)
            if len(pv) >= 3 and pv in o["endpoint"]:
                ok = False
                lines.append("  ✗ C11 interpole değer endpoint'e sızdı (%s)" % inv["call_id"])

    # sample-bazlı beklentiler
    exp = sample.get("expect", {})
    for cid, want in exp.items():
        o = by_id.get(cid)
        if o is None:
            ok = False
            lines.append("  ✗ beklenen çağrı yok: %s" % cid)
            continue
        for k, v in want.items():
            got = o.get(k)
            if isinstance(v, dict) and isinstance(got, dict):
                for kk, vv in v.items():
                    g2 = got.get(kk)
                    if g2 != vv:
                        ok = False
                        lines.append("  ✗ %s.%s.%s = %r (beklenen %r)" % (cid, k, kk, g2, vv))
                    else:
                        lines.append("  ✓ %s.%s.%s = %r" % (cid, k, kk, vv))
            elif got != v:
                ok = False
                lines.append("  ✗ %s.%s = %r (beklenen %r)" % (cid, k, got, v))
            else:
                lines.append("  ✓ %s.%s = %r" % (cid, k, v))

    # C6/C5: audit no-log — secret/PII/raw query yok
    if run["conn"] is not None:
        blob = json.dumps(run["conn"].audit, ensure_ascii=False)
        leaks = []
        if SECRET_KEY_RE.search(blob):
            leaks.append("secret")
        if CREDIT_CARD_RE.search(blob):
            leaks.append("kart")
        for em in EMAIL_RE.findall(blob):
            if not em.endswith("example.com"):
                leaks.append("email:%s" % em)
        # query string '?' audit'te olmamalı (ham url sızıntısı işareti)
        if '"raw_url"' in blob or "?" in blob:
            leaks.append("raw_url/query")
        if leaks:
            ok = False
            lines.append("  ✗ C6 audit no-log ihlali: %s" % ", ".join(leaks))
        if not all(a.get("no_log") for a in run["conn"].audit):
            ok = False
            lines.append("  ✗ C6 audit no_log işareti eksik")

    return ok, lines


def call_cmd(path):
    sample = _load(path)
    run = _run_sample(sample)
    name = sample.get("name", os.path.basename(path))
    print("== call: %s ==" % name)
    for o in run["outcomes"]:
        print("  [%s] %s op=%s → result=%s status=%s fault=%s retryable=%s pooled=%s lat=%.0fms idem=%s" % (
            o["call_id"], o["endpoint"], o["operation_class"], o["result"], o["status_code"],
            o["fault_class"], o["retryable"], o["pooled"], o["latency_ms"],
            o["request_meta"]["idempotency_forwarded"]))
    if run["error_class"]:
        print("  error_class: %s" % run["error_class"])
    ok, lines = _check_gates(sample, run)
    for ln in lines:
        print(ln)
    print("KAPI: %s" % ("🟢 GEÇTI" if ok else "🔴 ELENDI"))
    return 0 if ok else 1


# ── validate (statik kapı) ───────────────────────────────────────────────────────
def validate():
    fails = []

    def expect(c, m):
        if not c:
            fails.append(m)

    spec = _load(SPEC_PATH)
    cfg = _load(CONFIG_PATH)

    expect(spec.get("wbs") == "7.2.1", "spec.wbs 7.2.1")
    expect("FR-TOOL-001" in spec["trace"]["fr"], "trace FR-TOOL-001")
    expect("SR-TOOL-001" in spec["trace"]["srs"], "trace SR-TOOL-001")
    expect("FR-RES-006" in spec["trace"]["fr"], "trace FR-RES-006 (connection pooling)")
    expect([inv["id"] for inv in spec["invariants"]] == GATE_IDS, "invariants C1–C12 sırası")

    # fault taksonomi 7.1.4 ile hizalama (C2)
    al = spec["fault_taxonomy_alignment"]
    expect(set(al["retryable"]) == RETRYABLE_FAULTS, "retryable taksonomi spec↔kod (7.1.4 hizalı)")
    expect(set(al["terminal"]) == TERMINAL_FAULTS, "terminal taksonomi spec↔kod (7.1.4 hizalı)")
    expect(set(al["connector_never_emits"]) == GATEWAY_FAULTS, "connector gateway-fault üretmez")
    expect(set(spec["error_taxonomy"]["classes"]) == ERROR_CLASSES, "error taksonomi spec↔kod")
    # status→fault eşleme spec↔kod
    sm = spec["status_to_fault"]["map"]
    for code, want in (("408", "TIMEOUT"), ("429", "RATE_LIMITED"), ("401", "AUTH_FAILED"),
                       ("404", "NOT_FOUND"), ("422", "SCHEMA_INVALID")):
        expect(sm.get(code) == want, "status_to_fault %s=%s" % (code, want))

    # her profil geçerli connector spec'e dönüşür
    for pname, prof in cfg["profiles"].items():
        try:
            RestConnector(_strip_meta(prof))
        except ConnectorError as e:
            fails.append("profil %s geçerli connector değil (%s)" % (pname, e.error_class))

    # sır/PII taraması (spec/config/samples) — placeholder hariç literal sır yok
    scan_paths = [SPEC_PATH, CONFIG_PATH] + [os.path.join(SAMPLES_DIR, f)
                                             for f in sorted(os.listdir(SAMPLES_DIR)) if f.endswith(".json")]
    for sp in scan_paths:
        with open(sp, "r", encoding="utf-8") as f:
            txt = f.read()
        if SECRET_KEY_RE.search(txt):
            fails.append("sır sızıntısı: %s" % os.path.basename(sp))
        if CREDIT_CARD_RE.search(txt):
            fails.append("kart no: %s" % os.path.basename(sp))
        for em in EMAIL_RE.findall(txt):
            if not em.endswith("example.com"):
                fails.append("e-posta PII: %s (%s)" % (os.path.basename(sp), em))

    # her sample kapısı geçer
    for f in sorted(os.listdir(SAMPLES_DIR)):
        if not f.endswith(".json"):
            continue
        sample = _load(os.path.join(SAMPLES_DIR, f))
        run = _run_sample(sample)
        ok, _ = _check_gates(sample, run)
        # degraded fixture'ları KASITLI eler (expect_degraded)
        if sample.get("expect_degraded"):
            expect(not ok, "degraded sample KIRMIZI olmalı: %s" % f)
        else:
            expect(ok, "sample kapısı: %s" % f)

    print("validate: %d kontrol başarısız" % len(fails))
    for m in fails:
        print("  ✗ %s" % m)
    return 0 if not fails else 1


# ── selftest (gömülü davranış) ───────────────────────────────────────────────────
def _spec(**over):
    s = {
        "connector_id": "test-rest", "base_url": "https://api.example.com",
        "auth": {"type": "bearer", "ref": "${TEST_TOKEN}", "header": "Authorization", "scheme": "Bearer"},
        "default_headers": {"X-Client": "chanteur"},
        "pool": {"max_per_host": 4, "keepalive_ms": 30000, "connect_overhead_ms": 40.0},
        "operations": {
            "get_customer": {"method": "GET", "path": "/v1/customers/{id}", "timeout_ms": 2000, "accept": "application/json"},
            "create_ticket": {"method": "POST", "path": "/v1/tickets", "timeout_ms": 2000,
                              "content_type": "application/json", "success_codes": [200, 201]},
        },
    }
    s.update(over)
    return s


def selftest():
    fails = []
    n = 0

    def expect(c, m):
        nonlocal n
        n += 1
        if not c:
            fails.append(m)

    def W(status=None, latency=30.0, result="status"):
        w = {"result": result, "latency_ms": latency}
        if status is not None:
            w["status_code"] = status
        return w

    # C1: determinizm — aynı girdi iki kez aynı outcome
    c1a = RestConnector(_spec())
    o1 = c1a.upstream_call({"call_id": "a", "correlation_id": "x", "operation": "get_customer",
                            "path_params": {"id": "42"}, "wire_script": [W(200)]})
    c1b = RestConnector(_spec())
    o2 = c1b.upstream_call({"call_id": "a", "correlation_id": "x", "operation": "get_customer",
                            "path_params": {"id": "42"}, "wire_script": [W(200)]})
    expect(o1 == o2, "C1 determinizm birebir")
    expect(o1["result"] == "ok" and o1["status_code"] == 200, "C1 200 → ok")

    # C2: status → fault_class eşlemeleri
    cases = [(503, "fault", "UPSTREAM_5XX", True), (500, "fault", "UPSTREAM_5XX", True),
             (429, "fault", "RATE_LIMITED", True), (408, "fault", "TIMEOUT", True),
             (404, "fault", "NOT_FOUND", False), (401, "fault", "AUTH_FAILED", False),
             (403, "fault", "AUTH_FAILED", False), (422, "fault", "SCHEMA_INVALID", False),
             (400, "fault", "UPSTREAM_4XX", False), (200, "ok", None, False), (204, "ok", None, False)]
    for code, res, fc, rt in cases:
        c = RestConnector(_spec())
        o = c.upstream_call({"call_id": "c", "correlation_id": "x", "operation": "get_customer",
                             "path_params": {"id": "1"}, "wire_script": [W(code)]})
        expect(o["result"] == res and o["fault_class"] == fc and o["retryable"] == rt,
               "C2 status %d → %s/%s/retry=%s" % (code, res, fc, rt))

    # C2b: wire-seviyesi (HTTP'siz) faultlar
    for wr, fc in (("timeout", "TIMEOUT"), ("conn_reset", "CONN_RESET"), ("conn_refused", "CONN_REFUSED")):
        c = RestConnector(_spec())
        o = c.upstream_call({"call_id": "c", "correlation_id": "x", "operation": "get_customer",
                             "path_params": {"id": "1"}, "wire_script": [{"result": wr, "latency_ms": 10}]})
        expect(o["result"] == "fault" and o["fault_class"] == fc and o["retryable"] is True,
               "C2b wire %s → %s" % (wr, fc))

    # C3: method → operation_class
    c = RestConnector(_spec())
    og = c.upstream_call({"call_id": "g", "correlation_id": "x", "operation": "get_customer",
                          "path_params": {"id": "1"}, "wire_script": [W(200)]})
    op = c.upstream_call({"call_id": "p", "correlation_id": "x", "operation": "create_ticket",
                          "body": {"t": 1}, "wire_script": [W(201)]})
    expect(og["operation_class"] == "read", "C3 GET → read")
    expect(op["operation_class"] == "write", "C3 POST → write")

    # C4: AttemptOutcome SPI şekli — retry/breaker alanı YOK; tek deneme
    expect("attempts" not in og and "breaker_state" not in og, "C4 connector retry/breaker orkestre etmez")
    expect(set(["result", "latency_ms", "fault_class"]).issubset(og.keys()), "C4 SPI çekirdek alanları")

    # C5: literal sır spec'te → reddedilir
    try:
        RestConnector(_spec(auth={"type": "bearer", "ref": "sk-live-ABCD1234ABCD1234ABCD", "header": "Authorization"}))
        expect(False, "C5 literal sır reddedilmeli")
    except ConnectorError as e:
        expect(e.error_class == "LITERAL_SECRET_IN_SPEC", "C5 LITERAL_SECRET_IN_SPEC")

    # C6: audit no-log — query değeri/secret yok, no_log işaretli
    c = RestConnector(_spec())
    c.upstream_call({"call_id": "q", "correlation_id": "corr-1", "operation": "get_customer",
                     "path_params": {"id": "999"}, "query_params": {"q": "secret-value"},
                     "wire_script": [W(200)]})
    blob = json.dumps(c.audit)
    expect("secret-value" not in blob and "?" not in blob and "999" not in blob, "C6 audit'te ham query/değer yok")
    expect(c.audit[0]["no_log"] is True and c.audit[0]["correlation_id"] == "corr-1", "C6 no_log + correlation_id")

    # C7: connection pooling — ilk cold, ikinci warm (aynı host)
    c = RestConnector(_spec())
    a = c.upstream_call({"call_id": "1", "correlation_id": "x", "operation": "get_customer",
                         "path_params": {"id": "1"}, "at_ms": 0, "wire_script": [W(200, latency=30)]})
    b = c.upstream_call({"call_id": "2", "correlation_id": "x", "operation": "get_customer",
                         "path_params": {"id": "2"}, "at_ms": 100, "wire_script": [W(200, latency=30)]})
    expect(a["pooled"] is False and b["pooled"] is True, "C7 cold→warm pool")
    expect(a["latency_ms"] == 70.0 and b["latency_ms"] == 30.0, "C7 cold connect overhead 40ms, warm 0")
    # keepalive aşımı → tekrar cold
    d = c.upstream_call({"call_id": "3", "correlation_id": "x", "operation": "get_customer",
                         "path_params": {"id": "3"}, "at_ms": 100000, "wire_script": [W(200, latency=30)]})
    expect(d["pooled"] is False, "C7 keepalive aşımı → cold")

    # C8: bağlam taşıma — correlation header daima; idempotency yalnız write+key
    c = RestConnector(_spec())
    ow = c.upstream_call({"call_id": "w", "correlation_id": "x", "operation": "create_ticket",
                          "idempotency_key": "idem-1", "body": {"t": 1}, "wire_script": [W(201)]})
    expect(ow["request_meta"]["idempotency_forwarded"] is True, "C8 write+key → idempotency header")
    expect("X-Correlation-Id" in ow["request_meta"]["header_names"], "C8 correlation header daima")
    orr = c.upstream_call({"call_id": "r", "correlation_id": "x", "operation": "get_customer",
                           "path_params": {"id": "1"}, "idempotency_key": "idem-2", "wire_script": [W(200)]})
    expect(orr["request_meta"]["idempotency_forwarded"] is False, "C8 read → idempotency header iletilmez")

    # C9: timeout deadline — connect+transfer > timeout → TIMEOUT, latency kesilir
    c = RestConnector(_spec())
    ot = c.upstream_call({"call_id": "t", "correlation_id": "x", "operation": "get_customer",
                          "path_params": {"id": "1"}, "wire_script": [W(200, latency=5000)]})
    expect(ot["fault_class"] == "TIMEOUT" and ot["timed_out"] is True and ot["latency_ms"] == 2000.0,
           "C9/timeout deadline kesimi")

    # C10: enjeksiyon — CRLF path/query/header → INJECTION_REJECTED
    for inj_field in ("path", "query", "corr"):
        c = RestConnector(_spec())
        inv = {"call_id": "i", "correlation_id": "x", "operation": "get_customer",
               "path_params": {"id": "1"}, "wire_script": [W(200)]}
        if inj_field == "path":
            inv["path_params"] = {"id": "1\r\nX-Inject: y"}
        elif inj_field == "query":
            inv["query_params"] = {"q": "a\r\nEvil: 1"}
        else:
            inv["correlation_id"] = "x\r\nEvil: 1"
        try:
            c.upstream_call(inv)
            expect(False, "C10 enjeksiyon reddedilmeli (%s)" % inj_field)
        except ConnectorError as e:
            expect(e.error_class == "INJECTION_REJECTED", "C10 INJECTION_REJECTED (%s)" % inj_field)

    # C11: endpoint interpolesiz template — interpole id endpoint'te yok
    c = RestConnector(_spec())
    oe = c.upstream_call({"call_id": "e", "correlation_id": "x", "operation": "get_customer",
                          "path_params": {"id": "SENSITIVE-CUSTOMER-12345"}, "wire_script": [W(200)]})
    expect("{id}" in oe["endpoint"] and "SENSITIVE-CUSTOMER-12345" not in oe["endpoint"],
           "C11 endpoint template (interpole değer sızmaz)")

    # MISSING_PATH_PARAM + UNKNOWN_OPERATION
    c = RestConnector(_spec())
    try:
        c.upstream_call({"call_id": "m", "correlation_id": "x", "operation": "get_customer", "wire_script": [W(200)]})
        expect(False, "MISSING_PATH_PARAM bekleniyor")
    except ConnectorError as e:
        expect(e.error_class == "MISSING_PATH_PARAM", "MISSING_PATH_PARAM")
    try:
        c.upstream_call({"call_id": "u", "correlation_id": "x", "operation": "nope", "wire_script": [W(200)]})
        expect(False, "UNKNOWN_OPERATION bekleniyor")
    except ConnectorError as e:
        expect(e.error_class == "UNKNOWN_OPERATION", "UNKNOWN_OPERATION")

    # NON_MONOTONIC_CLOCK
    c = RestConnector(_spec())
    c.upstream_call({"call_id": "1", "correlation_id": "x", "operation": "get_customer",
                     "path_params": {"id": "1"}, "at_ms": 100, "wire_script": [W(200)]})
    try:
        c.upstream_call({"call_id": "2", "correlation_id": "x", "operation": "get_customer",
                         "path_params": {"id": "1"}, "at_ms": 50, "wire_script": [W(200)]})
        expect(False, "NON_MONOTONIC_CLOCK bekleniyor")
    except ConnectorError as e:
        expect(e.error_class == "NON_MONOTONIC_CLOCK", "NON_MONOTONIC_CLOCK")

    print("selftest: %d kontrol, %d başarısız" % (n, len(fails)))
    for m in fails:
        print("  ✗ %s" % m)
    return 0 if not fails else 1


def schema_cmd():
    spec = _load(SPEC_PATH)
    print(json.dumps({
        "wbs": spec["wbs"], "spi": spec["spi"]["transport_method"],
        "attempt_outcome_fields": spec["spi"]["attempt_outcome_fields"],
        "connector_spec_fields": spec["spi"]["connector_spec_fields"],
        "invocation_fields": spec["spi"]["invocation_fields"],
        "status_to_fault": spec["status_to_fault"]["map"],
        "wire_to_fault": spec["status_to_fault"]["wire_map"],
        "operation_class_map": spec["placement"]["operation_class_map"],
        "invariants": [i["id"] for i in spec["invariants"]],
        "error_classes": sorted(ERROR_CLASSES),
    }, ensure_ascii=False, indent=2))
    return 0


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd = argv[1]
    if cmd == "validate":
        return validate()
    if cmd == "call":
        if len(argv) < 3:
            print("kullanım: rest_connector_probe.py call <sample.json>")
            return 2
        return call_cmd(argv[2])
    if cmd == "selftest":
        return selftest()
    if cmd == "schema":
        return schema_cmd()
    print("bilinmeyen komut: %s" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
