#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 7.2.2 — SOAP/GraphQL/webhook connector'lar (SAD §11.2 Integration Gateway / FR-TOOL-001) referans probe.

    LLM tool call ──► [1] input schema ──► [2] authz ──► [3] policy gate ──► [4] idempotency
                  ──► [5] Integration GW {timeout+retry+breaker SARAR} ─► connector.upstream_call(req)  ◄── bu modül
                  ──► [6] output schema + error normalization ──► [7] correlation_id audit

7.2.1 (rest-connector) REST/HTTP dilimini uyguladı ve AYNI SPI seam'inin (7.1.4'ün ilan ettiği
'upstream_call(req) → AttemptOutcome') SOAP/GraphQL/webhook dilimlerini bu modüle BIRAKTI. Bu modül o üç
protokol mapper'ı ekler — AYNI AttemptOutcome, AYNI fault_taxonomy (7.1.4 hizalı), farklı protokol semantiği:
  • bildirimsel ConnectorSpec (protocol ∈ {soap,graphql,webhook}) + Invocation alır, kanonik istek KURAR (C1);
  • vendor-neutral WIRE SPI üzerinden yürütür (C12; referans deterministik wire_script — gerçek ağ/credential YOK);
  • protokol-yanıtını → 7.1.4'ün TÜKETTİĞİ AttemptOutcome'a EŞLER: status → fault_class (C2), op → operation_class (C3);
  • RETRY/BREAKER ORKESTRE ETMEZ (C4 — o 7.1.4); yalnız TEK denemenin sonucunu üretir;
  • sır+imza yalnız referansla (C5), audit no-log (C6), connection pooling FR-RES-006 (C7), bağlam taşıma (C8),
    determinizm (C9), enjeksiyon güvenli (C10), kanonik endpoint kimliği (C11);
  • PROTOKOL-FARKINDA FAULT TESPİTİ (C13 — 7.2.1 REST'in ötesindeki EK DEĞER):
      SOAP  : <soap:Fault> rolü (Sender→terminal / Receiver→retryable) HTTP status'u EZER;
      GraphQL: HTTP 200 + errors[] → FAULT (extensions.code → fault_class);
      webhook: HMAC imza ZORUNLU (imzasız teslimat reddedilir).

INVARIANT (SR-TOOL-001 kabul ölçütü): 'Her connector tipi başarılı çağrı yapar'.

Kapsam dışı (bilinçli): timeout/retry/breaker ORKESTRASYONU → 7.1.4 (FR-TOOL-003); allowlist → 7.2.3 (FR-TOOL-012);
REST dilimi → 7.2.1; input/output schema → 7.1.1; authz → 7.1.2; idempotency ÜRETİMİ → 7.1.3 (connector key'i
VARSA iletir); MÜŞTERİYE hata metni → 7.1.5; correlation_id audit zenginleştirme → 7.1.6; async workflow → 7.2.4.

Kullanım:
  protocol_connector_probe.py validate          Statik spec/config/şema kapısı → çıkış kodu
  protocol_connector_probe.py call <sample>     Deterministik çağrı(lar) — istek kur + wire + eşle → kapı (C1–C13)
  protocol_connector_probe.py selftest          Gömülü davranış kontrolleri → çıkış kodu
  protocol_connector_probe.py schema            SPI/AttemptOutcome/karar sözleşmesini yazdır

Determinizm: sanal saat (at_ms); Date.now/gerçek-rastgele YOK. Stdlib-only.
Sır/credential/imza ve gerçek PII değeri üretilmez/yazılmaz (fixture'lar sentetik — FR-TST-008; host'lar example.com).
"""
import json
import os
import re
import sys
import urllib.parse
from xml.sax.saxutils import escape as xml_escape

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "soap-graphql-webhook-spec.json")
CONFIG_PATH = os.path.join(HERE, "config", "connector-profiles.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

# ── Fault taksonomisi (7.1.4 integration-gw ile BİREBİR hizalı; C2) ─────────────
RETRYABLE_FAULTS = {"TIMEOUT", "UPSTREAM_5XX", "CONN_RESET", "CONN_REFUSED", "RATE_LIMITED", "DEADLINE_EXCEEDED"}
TERMINAL_FAULTS = {"UPSTREAM_4XX", "SCHEMA_INVALID", "AUTH_FAILED", "NOT_FOUND"}
GATEWAY_FAULTS = {"CIRCUIT_OPEN", "RETRY_EXHAUSTED"}  # connector ASLA üretmez (7.1.4'e ait)
EMITTABLE_FAULTS = RETRYABLE_FAULTS | TERMINAL_FAULTS

GATE_IDS = ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10", "C11", "C12", "C13"]

ERROR_CLASSES = {
    "MISSING_CONNECTOR_CONFIG", "INVALID_CONNECTOR_SPEC", "UNKNOWN_OPERATION", "MISSING_PATH_PARAM",
    "LITERAL_SECRET_IN_SPEC", "MISSING_SIGNING_CONFIG", "INJECTION_REJECTED", "INVALID_INVOCATION",
    "NON_MONOTONIC_CLOCK", "UNSUPPORTED_PROTOCOL", "INTERNAL_ERROR",
}

PROTOCOLS = {"soap", "graphql", "webhook"}

# Transport status → fault_class (özel kodlar; aksi 4xx/5xx bant) — 7.2.1 ile AYNI
STATUS_FAULT = {408: "TIMEOUT", 429: "RATE_LIMITED", 401: "AUTH_FAILED", 403: "AUTH_FAILED",
                404: "NOT_FOUND", 422: "SCHEMA_INVALID"}
WIRE_FAULT = {"timeout": "TIMEOUT", "conn_reset": "CONN_RESET", "conn_refused": "CONN_REFUSED"}

# SOAP fault rolü → fault_class (C13)
SOAP_SENDER_ROLES = {"Sender", "Client"}
SOAP_RECEIVER_ROLES = {"Receiver", "Server"}
SOAP_SENDER_FAULT = "UPSTREAM_4XX"      # terminal
SOAP_RECEIVER_FAULT = "UPSTREAM_5XX"    # retryable
SOAP_UNKNOWN_ROLE_FAULT = "UPSTREAM_4XX"  # bilinmeyen rol → güvenli terminal (kör retry yok)

# GraphQL errors[].extensions.code → fault_class (C13)
GRAPHQL_CODE_FAULT = {
    "UNAUTHENTICATED": "AUTH_FAILED", "FORBIDDEN": "AUTH_FAILED",
    "BAD_USER_INPUT": "SCHEMA_INVALID", "GRAPHQL_VALIDATION_FAILED": "SCHEMA_INVALID",
    "GRAPHQL_PARSE_FAILED": "SCHEMA_INVALID", "INTERNAL_SERVER_ERROR": "UPSTREAM_5XX",
    "RATE_LIMITED": "RATE_LIMITED", "THROTTLED": "RATE_LIMITED",
}
GRAPHQL_UNKNOWN_CODE_FAULT = "UPSTREAM_4XX"  # bilinmeyen kod → güvenli terminal

PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")
LITERAL_SECRET_RE = re.compile(r"(?i)(?:bearer\s+|sk[-_]|tok[-_]|key[-_]|secret[-_])?[A-Za-z0-9/\+_\-]{20,}")
SECRET_KEY_RE = re.compile(r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer|client[_-]?secret|access[_-]?token|signing[_-]?key|hmac[_-]?key)\b"
                           r"\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}")
CREDIT_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,16}\b")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")  # CRLF dahil kontrol karakterleri (C10)
TEMPLATE_RE = re.compile(r"\{([A-Za-z0-9_]+)\}")

READ_METHODS = {"GET", "HEAD", "OPTIONS"}


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


# ── Protocol connector (vendor-neutral transport SPI gerçeklemesi) ───────────────
class ProtocolConnector:
    """Bir ConnectorSpec için upstream_call(invocation) → AttemptOutcome.

    protocol ∈ {soap, graphql, webhook}; AYNI SPI/AttemptOutcome (7.2.1 ile), farklı protokol mapper.
    Connection pool durumu (C7/FR-RES-006) instance ömrü boyunca kalıcıdır. RETRY/BREAKER YOK (C4 — 7.1.4).
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
        for k in ("connector_id", "protocol", "base_url", "operations"):
            if k not in spec:
                raise ConnectorError("INVALID_CONNECTOR_SPEC", "eksik alan: %s" % k)
        if spec["protocol"] not in PROTOCOLS:
            raise ConnectorError("UNSUPPORTED_PROTOCOL", "protocol: %s" % spec["protocol"])
        if not isinstance(spec["operations"], dict) or not spec["operations"]:
            raise ConnectorError("INVALID_CONNECTOR_SPEC", "operations boş")
        scheme = urllib.parse.urlsplit(spec["base_url"]).scheme
        if scheme not in ("http", "https"):
            raise ConnectorError("INVALID_CONNECTOR_SPEC", "base_url scheme http/https olmalı")
        # C5: literal sır taraması — auth.ref + signing.ref placeholder olmalı
        auth = spec.get("auth") or {}
        if auth.get("type", "none") != "none":
            if not _is_placeholder(auth.get("ref", "")):
                raise ConnectorError("LITERAL_SECRET_IN_SPEC", "auth.ref placeholder ${ENV} olmalı")
        signing = spec.get("signing") or {}
        if signing:
            if not _is_placeholder(signing.get("ref", "")):
                raise ConnectorError("LITERAL_SECRET_IN_SPEC", "signing.ref placeholder ${ENV} olmalı")
        for hk, hv in (spec.get("default_headers") or {}).items():
            if isinstance(hv, str) and not _is_placeholder(hv) and LITERAL_SECRET_RE.fullmatch(hv.strip()):
                raise ConnectorError("LITERAL_SECRET_IN_SPEC", "default_headers.%s literal sır şüphesi" % hk)
        # webhook: imza yapılandırması ZORUNLU (C13)
        if spec["protocol"] == "webhook" and not signing.get("ref"):
            raise ConnectorError("MISSING_SIGNING_CONFIG", "webhook signing.ref zorunlu (HMAC)")
        # operation yapısal doğrulama (protokole göre)
        for opn, op in spec["operations"].items():
            self._validate_operation(opn, op)

    def _validate_operation(self, opn, op):
        proto = self.spec["protocol"]
        if proto == "soap":
            if "soap_action" not in op:
                raise ConnectorError("INVALID_CONNECTOR_SPEC", "soap operation %s soap_action eksik" % opn)
            se = op.get("side_effect", "write")
            if se not in ("read", "write"):
                raise ConnectorError("INVALID_CONNECTOR_SPEC", "soap operation %s side_effect read|write" % opn)
        elif proto == "graphql":
            if op.get("op_type") not in ("query", "mutation"):
                raise ConnectorError("INVALID_CONNECTOR_SPEC", "graphql operation %s op_type query|mutation" % opn)
        elif proto == "webhook":
            if "event_type" not in op:
                raise ConnectorError("INVALID_CONNECTOR_SPEC", "webhook operation %s event_type eksik" % opn)

    def _pool_cfg(self):
        p = self.spec.get("pool") or {}
        return (int(p.get("max_per_host", 8)), int(p.get("keepalive_ms", 30000)),
                float(p.get("connect_overhead_ms", 40.0)))

    @staticmethod
    def _check_injection(value, where):
        if isinstance(value, str) and CTRL_RE.search(value):
            raise ConnectorError("INJECTION_REJECTED", "%s kontrol karakteri (CRLF)" % where)

    # — operation_class (C3) —
    def _operation_class(self, op):
        proto = self.spec["protocol"]
        if proto == "soap":
            return op.get("side_effect", "write")
        if proto == "graphql":
            return "read" if op.get("op_type") == "query" else "write"
        return "write"  # webhook teslimatı daima write

    def _bind_path(self, op, inv):
        """path-template'i path_params ile bağla (C10 enjeksiyon + MISSING_PATH_PARAM). bound_path döner."""
        proto = self.spec["protocol"]
        default_path = {"soap": "", "graphql": "/graphql", "webhook": "/"}[proto]
        path_tpl = op.get("path", default_path)
        params = inv.get("path_params") or {}
        needed = set(TEMPLATE_RE.findall(path_tpl))
        for name in needed:
            if name not in params:
                raise ConnectorError("MISSING_PATH_PARAM", "path param yok: %s" % name)
        bound = path_tpl
        for name in needed:
            val = str(params[name])
            self._check_injection(val, "path_param %s" % name)
            bound = bound.replace("{%s}" % name, urllib.parse.quote(val, safe=""))
        return path_tpl, bound

    def _protocol_op_tag(self, op):
        """endpoint kimliğine eklenen düşük-kardinalite protokol etiketi (C11)."""
        proto = self.spec["protocol"]
        if proto == "soap":
            return "soapAction=%s" % op["soap_action"]
        if proto == "graphql":
            return "op=%s" % op.get("operation_name", "anonymous")
        return "event=%s" % op["event_type"]

    def _build_request(self, op, inv):
        """Kanonik istek kur (C1/C8/C10/C11). request_meta + endpoint + protocol_op döner. method daima POST."""
        method = "POST"  # SOAP/GraphQL/webhook hepsi HTTP POST
        path_tpl, bound_path = self._bind_path(op, inv)
        # endpoint kimliği: interpolesiz template + protokol etiketi (C11)
        endpoint = "%s %s%s [%s]" % (method, self.spec["base_url"].rstrip("/"), path_tpl, self._protocol_op_tag(op))
        url = self.spec["base_url"].rstrip("/") + bound_path
        op_class = self._operation_class(op)

        header_names = []
        for hk in sorted((self.spec.get("default_headers") or {}).keys()):
            header_names.append(hk)
        # auth (C5 sır referansla)
        auth = self.spec.get("auth") or {}
        if auth.get("type", "none") != "none":
            self._check_injection(auth.get("header", ""), "auth header")
            header_names.append(auth.get("header", "Authorization"))
        # protokole özgü content/header
        proto = self.spec["protocol"]
        if proto == "soap":
            self._check_injection(op["soap_action"], "soap_action")
            header_names += ["Content-Type", "SOAPAction"]
            self._render_soap_body(op, inv.get("args") or {})  # XML-escape + CTRL reddi (C10); gövde audit'lenmez
        elif proto == "graphql":
            header_names.append("Content-Type")
            self._build_graphql_payload(op, inv.get("args") or {})  # variables parametreli (C10)
        elif proto == "webhook":
            header_names.append("Content-Type")
            signing = self.spec.get("signing") or {}
            sig_header = signing.get("header", "X-Signature")
            self._check_injection(sig_header, "signature header")
            header_names += [sig_header, "X-Webhook-Timestamp"]
        signed = (proto == "webhook")
        # C8: correlation_id daima; idempotency_key VARSA write'ta
        corr = inv.get("correlation_id", "")
        self._check_injection(corr, "correlation_id")
        header_names.append("X-Correlation-Id")
        idempotency_forwarded = False
        idem = inv.get("idempotency_key")
        if idem and op_class == "write":
            self._check_injection(str(idem), "idempotency_key")
            header_names.append("Idempotency-Key")
            idempotency_forwarded = True
        return {
            "method": method, "url": url, "endpoint": endpoint, "operation_class": op_class,
            "header_names": sorted(set(header_names)), "idempotency_forwarded": idempotency_forwarded,
            "signed": signed, "protocol_op": self._protocol_op_tag(op),
        }

    # — protokol gövde kurucuları (C10 enjeksiyon-güvenli; gövde audit'lenmez) —
    def _render_soap_body(self, op, args):
        """SOAP gövdesini XML-escape ederek render et (C10). İç kullanım/test; audit'e GİTMEZ."""
        parts = []
        for k in sorted(args.keys()):
            v = args[k]
            sval = str(v)
            self._check_injection(sval, "soap arg %s" % k)  # CTRL/CRLF reddi
            parts.append("<%s>%s</%s>" % (k, xml_escape(sval), k))  # <>& kaçışlanır → tag enjeksiyonu nötr
        return "<soapenv:Body><%s>%s</%s></soapenv:Body>" % (op["soap_action"].split("/")[-1],
                                                             "".join(parts), op["soap_action"].split("/")[-1])

    def _build_graphql_payload(self, op, args):
        """GraphQL isteğini {query, variables, operationName} olarak kur (C10). variables PARAMETRELİ —
        kullanıcı değeri query string'e enterpole EDİLMEZ → yapısal enjeksiyon-güvenli. İç/test; audit'lenmez."""
        for k, v in args.items():
            self._check_injection(str(v), "graphql var %s" % k)  # CTRL/CRLF reddi (header güvenliği)
        query = op.get("query") or ("%s { __typename }" % op.get("op_type", "query"))
        return {"query": query, "variables": dict(args), "operationName": op.get("operation_name")}

    def _pool_decision(self, url):
        """Pool reuse/cold kararı (C7). pooled bool + connect_overhead döner. (7.2.1 ile AYNI.)"""
        sp = urllib.parse.urlsplit(url)
        key = "%s://%s" % (sp.scheme, sp.netloc)
        max_per_host, keepalive_ms, connect_overhead = self._pool_cfg()
        ent = self._pool.get(key)
        warm = ent is not None and (self.clock_ms - ent["last_used_ms"]) <= keepalive_ms and ent["count"] >= 1
        if warm:
            ent["last_used_ms"] = self.clock_ms
            return True, 0.0, key
        cnt = (ent["count"] if ent else 0)
        self._pool[key] = {"last_used_ms": self.clock_ms, "count": min(max_per_host, cnt + 1)}
        return False, connect_overhead, key

    @staticmethod
    def _map_status(status_code, success_codes):
        """Transport HTTP status → (ok|fault, fault_class) (C2). 7.2.1 ile AYNI."""
        is_success = (200 <= status_code <= 299) if success_codes is None else (status_code in success_codes)
        if is_success:
            return "ok", None
        if status_code in STATUS_FAULT:
            return "fault", STATUS_FAULT[status_code]
        if 500 <= status_code <= 599:
            return "fault", "UPSTREAM_5XX"
        if 400 <= status_code <= 499:
            return "fault", "UPSTREAM_4XX"
        return "fault", "UPSTREAM_4XX"  # 1xx/3xx beklenmeyen → güvenli terminal

    def _classify(self, op, status_code, wire, success_codes):
        """PROTOKOL-FARKINDA fault tespiti (C13) + transport eşleme (C2). (disp, fault_class) döner."""
        proto = self.spec["protocol"]
        if proto == "soap":
            sf = wire.get("soap_fault")
            if sf:  # rol HTTP status'u EZER (C13)
                role = sf.get("role", "")
                if role in SOAP_SENDER_ROLES:
                    return "fault", SOAP_SENDER_FAULT
                if role in SOAP_RECEIVER_ROLES:
                    return "fault", SOAP_RECEIVER_FAULT
                return "fault", SOAP_UNKNOWN_ROLE_FAULT
            return self._map_status(status_code, success_codes)
        if proto == "graphql":
            errs = wire.get("graphql_errors")
            is_success = (200 <= status_code <= 299) if success_codes is None else (status_code in success_codes)
            if is_success:
                if errs:  # HTTP 200 + errors[] → FAULT (C13)
                    code = (errs[0] or {}).get("code", "")
                    return "fault", GRAPHQL_CODE_FAULT.get(code, GRAPHQL_UNKNOWN_CODE_FAULT)
                return "ok", None
            return self._map_status(status_code, success_codes)  # transport-seviyesi hata (GraphQL katmanından önce)
        # webhook → REST-benzeri transport eşleme (override yok)
        return self._map_status(status_code, success_codes)

    def upstream_call(self, inv):
        """Tek denemeyi yürüt → AttemptOutcome (7.1.4'ün tükettiği SPI şekli)."""
        if not isinstance(inv, dict) or "operation" not in inv or "call_id" not in inv:
            raise ConnectorError("INVALID_INVOCATION", "operation/call_id eksik")
        opn = inv["operation"]
        op = self.spec["operations"].get(opn)
        if op is None:
            raise ConnectorError("UNKNOWN_OPERATION", "operation yok: %s" % opn)
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

        pooled, connect_overhead, _key = self._pool_decision(req["url"])  # C7

        # wire (C12 — vendor-neutral seam; referans wire_script)
        script = inv.get("wire_script") or []
        wire = script[0] if script else {"result": "status", "status_code": 200, "latency_ms": 30.0}
        wresult = wire.get("result", "status")
        wlat = float(wire.get("latency_ms", 30.0))
        total_latency = connect_overhead + wlat

        status_code = None
        if wresult in ("ok", "status"):
            status_code = int(wire.get("status_code", 200))
            disp, fault_class = self._classify(op, status_code, wire, success_codes)
        elif wresult in WIRE_FAULT:
            disp, fault_class = "fault", WIRE_FAULT[wresult]
        else:
            disp, fault_class = "fault", "CONN_RESET"  # bilinmeyen wire → güvenli retryable

        # per-attempt TIMEOUT deadline (connect+transfer > timeout) — gecikme kesilir (7.2.1 ile AYNI)
        timed_out = False
        if not (disp == "fault" and fault_class == "TIMEOUT"):
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
            "fault_class": fault_class, "status_code": status_code, "protocol": self.spec["protocol"],
            "operation_class": req["operation_class"], "endpoint": req["endpoint"],
            "retryable": retryable, "pooled": pooled, "timed_out": timed_out,
            "request_meta": {"method": req["method"], "header_names": req["header_names"],
                             "idempotency_forwarded": req["idempotency_forwarded"], "signed": req["signed"],
                             "protocol_op": req["protocol_op"]},
        }
        self._audit(inv.get("correlation_id", ""), outcome)
        return outcome

    def _audit(self, corr, o):
        rec = {
            "correlation_id": corr, "endpoint": o["endpoint"], "protocol": o["protocol"],
            "method": o["request_meta"]["method"], "operation_class": o["operation_class"],
            "status_code": o["status_code"], "fault_class": o["fault_class"], "pooled": o["pooled"],
            "signed": o["request_meta"]["signed"], "no_log": True,
        }
        if not self.redact_audit:
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
        conn = ProtocolConnector(spec, redact_audit=redact)
    except ConnectorError as e:
        return {"error_class": e.error_class, "outcomes": [], "conn": None}
    outcomes = []
    for inv in sample.get("invocations", []):
        try:
            o = conn.upstream_call(inv)
        except ConnectorError as e:
            return {"error_class": e.error_class, "outcomes": outcomes, "conn": conn}
        if not redact:
            op = spec["operations"].get(inv["operation"])
            conn.audit[-1]["raw_url"] = conn._build_request(op, inv)["url"] if op else ""
        outcomes.append(o)
    return {"error_class": None, "outcomes": outcomes, "conn": conn}


# ── kapı denetimi (C1–C13) ───────────────────────────────────────────────────────
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
        want_retry = (o["fault_class"] in RETRYABLE_FAULTS) if o["fault_class"] else False
        if o["retryable"] != want_retry:
            ok = False
            lines.append("  ✗ C2 retryable bayrağı tutarsız (%s)" % o["call_id"])

    # C3: operation_class read/write
    for o in outcomes:
        if o["operation_class"] not in ("read", "write"):
            ok = False
            lines.append("  ✗ C3 operation_class %r (%s)" % (o["operation_class"], o["call_id"]))

    # C11: endpoint interpolesiz template (interpole path_param/arg değeri sızmamalı)
    for inv in sample.get("invocations", []):
        o = by_id.get(inv["call_id"])
        if not o:
            continue
        leak_vals = list((inv.get("path_params") or {}).values()) + list((inv.get("args") or {}).values())
        for pv in leak_vals:
            pv = str(pv)
            if len(pv) >= 5 and pv in o["endpoint"]:
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
        print("  [%s] %s op=%s → result=%s status=%s fault=%s retryable=%s pooled=%s signed=%s lat=%.0fms idem=%s" % (
            o["call_id"], o["endpoint"], o["operation_class"], o["result"], o["status_code"],
            o["fault_class"], o["retryable"], o["pooled"], o["request_meta"]["signed"], o["latency_ms"],
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

    expect(spec.get("wbs") == "7.2.2", "spec.wbs 7.2.2")
    expect("FR-TOOL-001" in spec["trace"]["fr"], "trace FR-TOOL-001")
    expect("SR-TOOL-001" in spec["trace"]["srs"], "trace SR-TOOL-001")
    expect("FR-RES-006" in spec["trace"]["fr"], "trace FR-RES-006 (connection pooling)")
    expect([inv["id"] for inv in spec["invariants"]] == GATE_IDS, "invariants C1–C13 sırası")
    expect(set(spec["spi"]["protocols"]) == PROTOCOLS, "spi protocols soap/graphql/webhook")

    # fault taksonomi 7.1.4 ile hizalama (C2)
    al = spec["fault_taxonomy_alignment"]
    expect(set(al["retryable"]) == RETRYABLE_FAULTS, "retryable taksonomi spec↔kod (7.1.4 hizalı)")
    expect(set(al["terminal"]) == TERMINAL_FAULTS, "terminal taksonomi spec↔kod (7.1.4 hizalı)")
    expect(set(al["connector_never_emits"]) == GATEWAY_FAULTS, "connector gateway-fault üretmez")
    expect(set(spec["error_taxonomy"]["classes"]) == ERROR_CLASSES, "error taksonomi spec↔kod")
    # transport status→fault eşleme spec↔kod
    sm = spec["status_to_fault"]["map"]
    for code, want in (("408", "TIMEOUT"), ("429", "RATE_LIMITED"), ("401", "AUTH_FAILED"),
                       ("404", "NOT_FOUND"), ("422", "SCHEMA_INVALID")):
        expect(sm.get(code) == want, "status_to_fault %s=%s" % (code, want))
    # protocol_override spec↔kod (C13)
    po = spec["protocol_override"]
    expect(set(po["soap"]["sender_roles"]) == SOAP_SENDER_ROLES, "soap sender_roles spec↔kod")
    expect(set(po["soap"]["receiver_roles"]) == SOAP_RECEIVER_ROLES, "soap receiver_roles spec↔kod")
    expect(po["soap"]["sender_fault_class"] == SOAP_SENDER_FAULT, "soap sender→UPSTREAM_4XX")
    expect(po["soap"]["receiver_fault_class"] == SOAP_RECEIVER_FAULT, "soap receiver→UPSTREAM_5XX")
    expect(po["graphql"]["code_map"] == GRAPHQL_CODE_FAULT, "graphql code_map spec↔kod")
    expect(po["graphql"]["unknown_code_fault_class"] == GRAPHQL_UNKNOWN_CODE_FAULT, "graphql unknown→terminal")
    expect(po["webhook"]["signature_required"] is True, "webhook imza zorunlu")

    # her profil geçerli connector spec'e dönüşür
    for pname, prof in cfg["profiles"].items():
        try:
            ProtocolConnector(_strip_meta(prof))
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

    # her sample kapısı geçer (degraded KASITLI eler)
    for f in sorted(os.listdir(SAMPLES_DIR)):
        if not f.endswith(".json"):
            continue
        sample = _load(os.path.join(SAMPLES_DIR, f))
        run = _run_sample(sample)
        ok, _ = _check_gates(sample, run)
        if sample.get("expect_degraded"):
            expect(not ok, "degraded sample KIRMIZI olmalı: %s" % f)
        else:
            expect(ok, "sample kapısı: %s" % f)

    print("validate: %d kontrol başarısız" % len(fails))
    for m in fails:
        print("  ✗ %s" % m)
    return 0 if not fails else 1


# ── selftest (gömülü davranış) ───────────────────────────────────────────────────
def _soap_spec(**over):
    s = {
        "connector_id": "t-soap", "protocol": "soap", "base_url": "https://erp.example.com",
        "auth": {"type": "basic", "ref": "${ERP_BASIC}", "header": "Authorization"},
        "default_headers": {"X-Client": "chanteur"},
        "pool": {"max_per_host": 4, "keepalive_ms": 30000, "connect_overhead_ms": 40.0},
        "operations": {
            "GetBalance": {"soap_action": "urn:erp/GetBalance", "path": "/soap/v1", "side_effect": "read", "timeout_ms": 2000},
            "PostPayment": {"soap_action": "urn:erp/PostPayment", "path": "/soap/v1", "side_effect": "write", "timeout_ms": 2000},
        },
    }
    s.update(over)
    return s


def _graphql_spec(**over):
    s = {
        "connector_id": "t-gql", "protocol": "graphql", "base_url": "https://api.example.com",
        "auth": {"type": "bearer", "ref": "${GQL_TOKEN}", "header": "Authorization", "scheme": "Bearer"},
        "pool": {"max_per_host": 4, "keepalive_ms": 30000, "connect_overhead_ms": 40.0},
        "operations": {
            "GetUser": {"op_type": "query", "operation_name": "GetUser", "path": "/graphql", "timeout_ms": 2000},
            "CreateOrder": {"op_type": "mutation", "operation_name": "CreateOrder", "path": "/graphql", "timeout_ms": 2000},
        },
    }
    s.update(over)
    return s


def _webhook_spec(**over):
    s = {
        "connector_id": "t-wh", "protocol": "webhook", "base_url": "https://hooks.example.com",
        "signing": {"ref": "${WH_SIGNING_KEY}", "header": "X-Signature", "algo": "hmac-sha256"},
        "pool": {"max_per_host": 4, "keepalive_ms": 30000, "connect_overhead_ms": 40.0},
        "operations": {
            "call_completed": {"event_type": "call.completed", "path": "/events", "success_codes": [200, 202, 204], "timeout_ms": 2000},
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

    def W(status=None, latency=30.0, result="status", **extra):
        w = {"result": result, "latency_ms": latency}
        if status is not None:
            w["status_code"] = status
        w.update(extra)
        return w

    # ── C1/C9: determinizm ──
    a = ProtocolConnector(_soap_spec()).upstream_call(
        {"call_id": "a", "correlation_id": "x", "operation": "GetBalance", "args": {"acct": "1"}, "wire_script": [W(200)]})
    b = ProtocolConnector(_soap_spec()).upstream_call(
        {"call_id": "a", "correlation_id": "x", "operation": "GetBalance", "args": {"acct": "1"}, "wire_script": [W(200)]})
    expect(a == b, "C1 determinizm birebir (SOAP)")

    # ── SOAP: HTTP 200 ok; method POST; side_effect→operation_class ──
    expect(a["result"] == "ok" and a["protocol"] == "soap" and a["operation_class"] == "read", "SOAP 200 ok + read")
    cw = ProtocolConnector(_soap_spec())
    ow = cw.upstream_call({"call_id": "w", "correlation_id": "x", "operation": "PostPayment",
                           "args": {"amt": "10"}, "wire_script": [W(200)]})
    expect(ow["operation_class"] == "write", "C3 SOAP side_effect write")

    # ── C13 SOAP: Sender fault (HTTP 500) → TERMINAL; Receiver fault → RETRYABLE ──
    cs = ProtocolConnector(_soap_spec())
    osd = cs.upstream_call({"call_id": "s", "correlation_id": "x", "operation": "GetBalance", "args": {"acct": "1"},
                            "wire_script": [W(500, soap_fault={"role": "Sender", "code": "InvalidRequest"})]})
    expect(osd["fault_class"] == "UPSTREAM_4XX" and osd["retryable"] is False,
           "C13 SOAP Sender fault (HTTP 500) → TERMINAL (retry futile)")
    cr = ProtocolConnector(_soap_spec())
    ord_ = cr.upstream_call({"call_id": "r", "correlation_id": "x", "operation": "GetBalance", "args": {"acct": "1"},
                             "wire_script": [W(500, soap_fault={"role": "Receiver", "code": "ServerBusy"})]})
    expect(ord_["fault_class"] == "UPSTREAM_5XX" and ord_["retryable"] is True,
           "C13 SOAP Receiver fault (HTTP 500) → RETRYABLE")
    # bilinmeyen rol → güvenli terminal
    cu = ProtocolConnector(_soap_spec())
    ou = cu.upstream_call({"call_id": "u", "correlation_id": "x", "operation": "GetBalance", "args": {"acct": "1"},
                           "wire_script": [W(500, soap_fault={"role": "Weird"})]})
    expect(ou["fault_class"] == "UPSTREAM_4XX", "C13 SOAP bilinmeyen rol → güvenli terminal")

    # ── C10 SOAP: gövde XML-escape (tag enjeksiyonu nötr) ──
    body = ProtocolConnector(_soap_spec())._render_soap_body(
        {"soap_action": "urn:erp/GetBalance"}, {"acct": "<inject>evil</inject>"})
    expect("<inject>" not in body and "&lt;inject&gt;" in body, "C10 SOAP gövde XML-escape (tag nötr)")

    # ── GraphQL: query→read, HTTP 200 no errors → ok ──
    cg = ProtocolConnector(_graphql_spec())
    og = cg.upstream_call({"call_id": "g", "correlation_id": "x", "operation": "GetUser",
                           "args": {"id": "1"}, "wire_script": [W(200, has_data=True)]})
    expect(og["result"] == "ok" and og["operation_class"] == "read" and og["protocol"] == "graphql",
           "GraphQL query 200 no-errors → ok + read")
    cm = ProtocolConnector(_graphql_spec())
    om = cm.upstream_call({"call_id": "m", "correlation_id": "x", "operation": "CreateOrder",
                           "args": {"sku": "A"}, "wire_script": [W(200, has_data=True)]})
    expect(om["operation_class"] == "write", "C3 GraphQL mutation → write")

    # ── C13 GraphQL: HTTP 200 + errors[] → FAULT (kod eşleme) ──
    gcases = [("UNAUTHENTICATED", "AUTH_FAILED", False), ("FORBIDDEN", "AUTH_FAILED", False),
              ("BAD_USER_INPUT", "SCHEMA_INVALID", False), ("INTERNAL_SERVER_ERROR", "UPSTREAM_5XX", True),
              ("THROTTLED", "RATE_LIMITED", True), ("MYSTERY_CODE", "UPSTREAM_4XX", False)]
    for code, fc, rt in gcases:
        c = ProtocolConnector(_graphql_spec())
        o = c.upstream_call({"call_id": "e", "correlation_id": "x", "operation": "GetUser", "args": {"id": "1"},
                             "wire_script": [W(200, graphql_errors=[{"code": code}])]})
        expect(o["result"] == "fault" and o["fault_class"] == fc and o["retryable"] == rt,
               "C13 GraphQL 200+errors[%s] → %s/retry=%s" % (code, fc, rt))

    # ── C10 GraphQL: variables parametreli (kullanıcı değeri query string'e enterpole edilmez) ──
    payload = ProtocolConnector(_graphql_spec())._build_graphql_payload(
        {"op_type": "query", "operation_name": "GetUser", "query": "query GetUser($id:ID!){ user(id:$id){ name } }"},
        {"id": "1) OR 1=1 --"})
    expect("OR 1=1" not in payload["query"] and payload["variables"]["id"] == "1) OR 1=1 --",
           "C10 GraphQL variables parametreli (query'ye enterpolasyon yok)")

    # ── Webhook: imza zorunlu; teslimat 2xx ok; daima write + signed ──
    cwh = ProtocolConnector(_webhook_spec())
    owh = cwh.upstream_call({"call_id": "wh", "correlation_id": "x", "operation": "call_completed",
                             "idempotency_key": "evt-1", "args": {"call_id": "C-1"}, "wire_script": [W(202)]})
    expect(owh["result"] == "ok" and owh["operation_class"] == "write" and owh["request_meta"]["signed"] is True,
           "Webhook 202 ok + write + signed")
    expect(owh["request_meta"]["idempotency_forwarded"] is True, "C8 webhook write+key → idempotency header")

    # ── C13 Webhook: imza yapılandırması yoksa → MISSING_SIGNING_CONFIG ──
    try:
        ProtocolConnector(_webhook_spec(signing={}))
        expect(False, "C13 webhook imzasız reddedilmeli")
    except ConnectorError as e:
        expect(e.error_class == "MISSING_SIGNING_CONFIG", "C13 MISSING_SIGNING_CONFIG")

    # ── C2: webhook transport status eşleme (REST-benzeri) ──
    for code, fc, rt in [(503, "UPSTREAM_5XX", True), (429, "RATE_LIMITED", True), (404, "NOT_FOUND", False),
                         (401, "AUTH_FAILED", False), (400, "UPSTREAM_4XX", False)]:
        c = ProtocolConnector(_webhook_spec())
        o = c.upstream_call({"call_id": "c", "correlation_id": "x", "operation": "call_completed",
                             "args": {}, "wire_script": [W(code)]})
        expect(o["result"] == "fault" and o["fault_class"] == fc and o["retryable"] == rt,
               "C2 webhook status %d → %s/retry=%s" % (code, fc, rt))

    # ── C2b: wire-seviyesi faultlar (tüm protokoller) ──
    for wr, fc in (("timeout", "TIMEOUT"), ("conn_reset", "CONN_RESET"), ("conn_refused", "CONN_REFUSED")):
        c = ProtocolConnector(_graphql_spec())
        o = c.upstream_call({"call_id": "c", "correlation_id": "x", "operation": "GetUser", "args": {"id": "1"},
                             "wire_script": [{"result": wr, "latency_ms": 10}]})
        expect(o["result"] == "fault" and o["fault_class"] == fc and o["retryable"] is True, "C2b wire %s → %s" % (wr, fc))

    # ── C4: AttemptOutcome SPI şekli — retry/breaker alanı YOK ──
    expect("attempts" not in og and "breaker_state" not in og, "C4 connector retry/breaker orkestre etmez")
    expect({"result", "latency_ms", "fault_class", "protocol"}.issubset(og.keys()), "C4 SPI çekirdek alanları")

    # ── C5: literal sır spec'te → reddedilir (auth + signing) ──
    try:
        ProtocolConnector(_graphql_spec(auth={"type": "bearer", "ref": "sk-live-ABCD1234ABCD1234ABCD", "header": "Authorization"}))
        expect(False, "C5 literal auth sırrı reddedilmeli")
    except ConnectorError as e:
        expect(e.error_class == "LITERAL_SECRET_IN_SPEC", "C5 LITERAL_SECRET_IN_SPEC (auth)")
    try:
        ProtocolConnector(_webhook_spec(signing={"ref": "whsec-ABCD1234ABCD1234ABCD", "header": "X-Signature"}))
        expect(False, "C5 literal signing sırrı reddedilmeli")
    except ConnectorError as e:
        expect(e.error_class == "LITERAL_SECRET_IN_SPEC", "C5 LITERAL_SECRET_IN_SPEC (signing)")

    # ── C6: audit no-log — args/query/secret/imza yok, no_log işaretli ──
    c = ProtocolConnector(_soap_spec())
    c.upstream_call({"call_id": "q", "correlation_id": "corr-1", "operation": "GetBalance",
                     "args": {"acct": "SENSITIVE-9999"}, "wire_script": [W(200)]})
    blob = json.dumps(c.audit)
    expect("SENSITIVE-9999" not in blob and "?" not in blob, "C6 audit'te ham arg yok")
    expect(c.audit[0]["no_log"] is True and c.audit[0]["correlation_id"] == "corr-1", "C6 no_log + correlation_id")
    expect(c.audit[0]["protocol"] == "soap" and "signed" in c.audit[0], "C6 audit protocol+signed alanı")

    # ── C7: connection pooling — cold→warm ──
    c = ProtocolConnector(_graphql_spec())
    p1 = c.upstream_call({"call_id": "1", "correlation_id": "x", "operation": "GetUser", "args": {"id": "1"},
                          "at_ms": 0, "wire_script": [W(200, latency=30, has_data=True)]})
    p2 = c.upstream_call({"call_id": "2", "correlation_id": "x", "operation": "GetUser", "args": {"id": "2"},
                          "at_ms": 100, "wire_script": [W(200, latency=30, has_data=True)]})
    expect(p1["pooled"] is False and p1["latency_ms"] == 70.0, "C7 ilk çağrı cold (+40ms connect)")
    expect(p2["pooled"] is True and p2["latency_ms"] == 30.0, "C7 ikinci çağrı warm (connect 0)")

    # ── C9: timeout deadline ──
    c = ProtocolConnector(_graphql_spec())
    ot = c.upstream_call({"call_id": "t", "correlation_id": "x", "operation": "GetUser", "args": {"id": "1"},
                          "wire_script": [W(200, latency=5000, has_data=True)]})
    expect(ot["fault_class"] == "TIMEOUT" and ot["timed_out"] is True and ot["latency_ms"] == 2000.0,
           "C9 timeout deadline kesimi")

    # ── C10: header enjeksiyonu — CRLF correlation_id → INJECTION_REJECTED ──
    c = ProtocolConnector(_soap_spec())
    try:
        c.upstream_call({"call_id": "i", "correlation_id": "x\r\nEvil: 1", "operation": "GetBalance",
                         "args": {"acct": "1"}, "wire_script": [W(200)]})
        expect(False, "C10 CRLF reddedilmeli")
    except ConnectorError as e:
        expect(e.error_class == "INJECTION_REJECTED", "C10 INJECTION_REJECTED (correlation_id)")
    expect(len(c.audit) == 0, "C10 reddedilen istek WIRE'a gitmez (audit boş)")

    # ── C11: endpoint interpolesiz (soapAction etiketi var, interpole arg yok) ──
    c = ProtocolConnector(_soap_spec())
    oe = c.upstream_call({"call_id": "e", "correlation_id": "x", "operation": "GetBalance",
                          "args": {"acct": "SENSITIVE-CUSTOMER-12345"}, "wire_script": [W(200)]})
    expect("soapAction=urn:erp/GetBalance" in oe["endpoint"] and "SENSITIVE-CUSTOMER-12345" not in oe["endpoint"],
           "C11 endpoint düşük-kardinalite (interpole arg sızmaz)")

    # ── UNKNOWN_OPERATION + UNSUPPORTED_PROTOCOL + NON_MONOTONIC_CLOCK ──
    c = ProtocolConnector(_soap_spec())
    try:
        c.upstream_call({"call_id": "x", "correlation_id": "x", "operation": "nope", "wire_script": [W(200)]})
        expect(False, "UNKNOWN_OPERATION bekleniyor")
    except ConnectorError as e:
        expect(e.error_class == "UNKNOWN_OPERATION", "UNKNOWN_OPERATION")
    try:
        ProtocolConnector(_soap_spec(protocol="ftp"))
        expect(False, "UNSUPPORTED_PROTOCOL bekleniyor")
    except ConnectorError as e:
        expect(e.error_class == "UNSUPPORTED_PROTOCOL", "UNSUPPORTED_PROTOCOL")
    c = ProtocolConnector(_soap_spec())
    c.upstream_call({"call_id": "1", "correlation_id": "x", "operation": "GetBalance", "args": {"acct": "1"},
                     "at_ms": 100, "wire_script": [W(200)]})
    try:
        c.upstream_call({"call_id": "2", "correlation_id": "x", "operation": "GetBalance", "args": {"acct": "1"},
                         "at_ms": 50, "wire_script": [W(200)]})
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
        "protocols": spec["spi"]["protocols"],
        "attempt_outcome_fields": spec["spi"]["attempt_outcome_fields"],
        "connector_spec_fields": spec["spi"]["connector_spec_fields"],
        "invocation_fields": spec["spi"]["invocation_fields"],
        "status_to_fault": spec["status_to_fault"]["map"],
        "wire_to_fault": spec["status_to_fault"]["wire_map"],
        "protocol_override": {"soap": spec["protocol_override"]["soap"],
                              "graphql_code_map": spec["protocol_override"]["graphql"]["code_map"],
                              "webhook_signature_required": spec["protocol_override"]["webhook"]["signature_required"]},
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
            print("kullanım: protocol_connector_probe.py call <sample.json>")
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
