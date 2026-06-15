#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 7.2.3 — Endpoint allowlist (onaysız endpoint engelleme; SAD §11.2 Integration Gateway / FR-TOOL-012) referans probe.

    LLM tool call ──► [1] input schema ──► [2] authz ──► [3] policy gate ──► [4] idempotency
                  ──► [EGRESS GATE: connector kanonik endpoint+target ÜRETİR → allowlist KARAR]  ◄── bu modül
                  ──► PERMIT ? [5] Integration GW {timeout+retry+breaker} ─► connector.upstream_call(req)
                            : DENY  short-circuit (ENDPOINT_NOT_ALLOWED — WIRE'a gitmez)
                  ──► [6] output schema + error normalization ──► [7] correlation_id audit

ADR-014 (Zorunlu egress kontrol katmanı — egress proxy + merkezi allowlist) UYGULAMA-KATMANI karar çekirdeği.
Connector (7.2.1 REST / 7.2.2 SOAP/GraphQL/webhook) bir KANONİK endpoint + çözülmüş target üretir; bu gate o
hedefi tenant-tanımlı allowlist ile karşılaştırıp PERMIT/DENY KARAR verir:
  • default-deny (A1): eşleşen allow kuralı yoksa DENY — SR-TOOL-012 'Allowlist dışı endpoint çağrısı reddedilir';
  • SSRF savunması (TM-E-06): cloud metadata (A2) + RFC1918/loopback/link-local/ULA özel ağ (A3) BLOK;
  • DNS rebinding (A4): allowlist'li host iç IP'ye çözülürse host-allow BYPASS ETMEZ;
  • block-overrides-allow / most-restrictive-wins (A9): hiçbir allow kuralı iç IP'ye/yasak scheme'e izin veremez;
  • scheme/port allowlist (A5/A6), host etiket-sınırı eşleme (A7), path_prefix segment-sınırı (A8);
  • determinizm (A10), audit no-log (A11), fail-closed (A12 — bozuk/çözülemeyen hedef → DENY, ASLA permit).

DENY → gate-seviyesi TERMINAL fault ENDPOINT_NOT_ALLOWED (7.1.4 retry ETMEZ); 7.1.5 müşteriye teknik-detaysız
NOT_PERMITTED'e çevirir. INVARIANT (SR-TOOL-012): 'Allowlist dışı endpoint çağrısı reddedilir.'

Kapsam dışı (bilinçli): kanonik endpoint/target ÜRETİMİ → 7.2.1/7.2.2; timeout/retry/breaker → 7.1.4; ağ-katmanı
egress proxy / IP allowlist / WAF → 17.1.4 (defense-in-depth, AYNI mantık); input/output schema → 7.1.1; tool
authz/scope → 7.1.2 (DİK boyut); idempotency → 7.1.3; MÜŞTERİYE hata metni → 7.1.5; audit zenginleştirme → 7.1.6;
allowlist L1 panel CRUD yönetimi → ileri panel WBS; gerçek DNS çözümleme → canlı resolver (referans: resolved_ips).

Kullanım:
  endpoint_allowlist_probe.py validate          Statik spec/config/şema + sır/PII tarama kapısı → çıkış kodu
  endpoint_allowlist_probe.py decide <sample>   Deterministik egress kararı(ları) — PERMIT/DENY + reason → kapı (A1–A12)
  endpoint_allowlist_probe.py selftest          Gömülü davranış kontrolleri → çıkış kodu
  endpoint_allowlist_probe.py schema            Policy/Request/Decision sözleşmesini yazdır

Determinizm: saf karar; Date.now/gerçek-rastgele YOK. Stdlib-only.
Sır/credential ve gerçek PII değeri üretilmez/yazılmaz (fixture'lar sentetik — FR-TST-008; host'lar example.com).
"""
import ipaddress
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "endpoint-allowlist-spec.json")
CONFIG_PATH = os.path.join(HERE, "config", "egress-policies.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

GATE_IDS = ["A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10", "A11", "A12"]

PERMIT_REASON = "ALLOWED"
DENY_REASONS = {
    "UNLISTED_ENDPOINT", "SCHEME_BLOCKED", "PORT_BLOCKED", "PRIVATE_NETWORK_BLOCKED",
    "METADATA_BLOCKED", "DNS_REBINDING_BLOCKED", "PATH_NOT_ALLOWED", "MALFORMED_TARGET",
    "POLICY_TENANT_MISMATCH",
}
DENY_FAULT = "ENDPOINT_NOT_ALLOWED"  # gate-seviyesi terminal (7.1.4 retry etmez)

# Cloud metadata özel-kasa (A2) — host adı ∨ IP literal
METADATA_IPS = {"169.254.169.254", "fd00:ec2::254", "100.100.200.200"}
METADATA_HOSTS = {"metadata.google.internal", "metadata", "instance-data",
                  "metadata.goog", "169.254.169.254"}

# RFC5737/RFC3849 belgeleme aralıkları — fixture'larda gerçek PUBLIC IP yerine kullanılır (sentetik; FR-TST-008).
# SSRF güvenliği is_global TABANLI: doküman aralıkları HARİÇ, global-olmayan her IP 'private' sayılır (blok).
DOC_RANGES = [ipaddress.ip_network(c) for c in
              ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24", "2001:db8::/32")]

CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")  # CRLF/kontrol karakteri (A12 fail-closed)
DNS_LABEL_RE = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)$")
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")

# sır/PII tarama (validate; kardeş modüllerle hizalı)
SECRET_KEY_RE = re.compile(r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer|client[_-]?secret|access[_-]?token)\b"
                           r"\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}")
CREDIT_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,16}\b")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _strip_meta(d):
    return {k: v for k, v in d.items() if not k.startswith("$")}


# ── IP / host kanonikleştirme ────────────────────────────────────────────────────
def classify_ip(ipstr):
    """IP literal → 'metadata' | 'private' | 'public' | None(parse edilemez)."""
    try:
        ip = ipaddress.ip_address(ipstr)
    except ValueError:
        return None
    # IPv4-mapped IPv6 → altta yatan v4'ü değerlendir (::ffff:127.0.0.1 vb.)
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if str(ip) in METADATA_IPS:
        return "metadata"
    if any(ip in r for r in DOC_RANGES):
        return "public"  # belgeleme placeholder (gerçek public IP yerine — fixture)
    if ip.is_global:
        return "public"
    # global-olmayan: is_private/loopback/link-local/ULA/reserved/multicast/CGN(100.64/10) → blok
    return "private"


def host_kind(host):
    """Normalize edilmiş host → ('ip', host) | ('name', None) | ('malformed', None).

    IP literal doğrudan; decimal/octal/hex obfuscation (ör. '2130706433', '0x7f000001')
    KASITLI 'malformed' (fail-closed A12 — obfuscation'ı permit'e taşımayız)."""
    h = host.strip("[]")  # bracketed IPv6
    try:
        ipaddress.ip_address(h)
        return ("ip", h)
    except ValueError:
        pass
    if h.isdigit() or re.match(r"^0[xXbBoO]", h):
        return ("malformed", None)  # decimal/hex/octal IP obfuscation → reddet
    if len(h) <= 253 and h.count(".") <= 126 and all(DNS_LABEL_RE.match(lbl) for lbl in h.split(".") if lbl != "") and h.strip("."):
        return ("name", None)
    return ("malformed", None)


def host_match(rule_host, host):
    """Etiket-sınırı eşleme (A7): exact (case-insensitive) ∨ '*.suffix' (apex hariç, substring YOK)."""
    rh = rule_host.rstrip(".").lower()
    if rh.startswith("*."):
        suffix = rh[1:]  # '.example.com'
        return host.endswith(suffix) and len(host) > len(suffix)
    return host == rh


def path_under(path, prefix):
    """A8 segment-sınırı: path, prefix ile '/' sınırında başlar mı."""
    if not prefix:
        return True
    p = prefix.rstrip("/")
    return path == p or path == p + "/" or path.startswith(p + "/")


def normalize_path(path):
    """'..' segmenti içeren path → None (MALFORMED A8/A12); aksi kanonik path."""
    if not path:
        return "/"
    segs = path.split("/")
    if ".." in segs:
        return None
    out = [s for s in segs if s not in ("", ".")]
    return "/" + "/".join(out)


# ── Egress karar gate'i ──────────────────────────────────────────────────────────
class PolicyError(Exception):
    def __init__(self, reason=""):
        super().__init__(reason)
        self.reason = reason


class EgressGate:
    """Bir EgressPolicy için decide(request) → AllowlistDecision. SAF karar (A10); audit no-log (A11)."""

    def __init__(self, policy, enforce_ssrf=True):
        self.policy = policy
        # enforce_ssrf: degraded fixture False'a çevirip SSRF-floor gate'i sınar (policy toggle'dan BAĞIMSIZ kapı kanıtı)
        self.enforce_ssrf = enforce_ssrf
        self.audit = []
        self._validate_policy()

    def _validate_policy(self):
        p = self.policy
        if p.get("default_action", "deny") != "deny":
            raise PolicyError("INVALID_POLICY: default_action 'deny' olmalı (FR-TOOL-012 default-deny)")
        if not isinstance(p.get("allow", []), list):
            raise PolicyError("INVALID_POLICY: allow liste olmalı")
        for i, r in enumerate(p.get("allow", [])):
            if "host" not in r or "scheme" not in r:
                raise PolicyError("INVALID_POLICY: allow[%d] host/scheme eksik" % i)

    def _block_metadata(self):
        return bool(self.policy.get("block_metadata", True)) and self.enforce_ssrf

    def _block_private(self):
        return bool(self.policy.get("block_private_networks", True)) and self.enforce_ssrf

    def _record(self, req, decision, reason, matched, endpoint):
        rec = {
            "correlation_id": req.get("correlation_id", ""),
            "endpoint": endpoint,           # kanonik template (düşük kardinalite — A11)
            "decision": decision,
            "reason_code": reason,
            "matched_rule": matched,
            "no_log": True,
        }
        self.audit.append(rec)
        return {
            "decision": decision,
            "reason_code": reason,
            "matched_rule": matched,
            "endpoint": endpoint,
            "fault_class": None if decision == "permit" else DENY_FAULT,
            "no_log": True,
        }

    def _deny(self, req, reason, endpoint):
        return self._record(req, "deny", reason, None, endpoint)

    def _permit(self, req, idx, endpoint):
        return self._record(req, "permit", PERMIT_REASON, idx, endpoint)

    def _match_allow(self, connector_id, scheme, host, port, path):
        """('permit', idx) | ('path', None) | ('unlisted', None)."""
        host_seen = False
        for i, r in enumerate(self.policy.get("allow", [])):
            if r.get("connector_id") and connector_id and r["connector_id"] != connector_id:
                continue
            if r.get("scheme", "https").lower() != scheme:
                continue
            if not host_match(r["host"], host):
                continue
            if "port" in r and r["port"] != port:
                continue
            host_seen = True  # host/scheme/port eşleşti — path_prefix dışında uygun
            if path_under(path, r.get("path_prefix", "")):
                return ("permit", i)
        return ("path", None) if host_seen else ("unlisted", None)

    def decide(self, req):
        target = req.get("target") or {}
        scheme = str(target.get("scheme") or "").lower()
        host_raw = str(target.get("host") or "")
        port = target.get("port")
        path = str(target.get("path") or "/")
        endpoint = req.get("endpoint") or ("%s %s://%s<path>" % (req.get("method", "?"), scheme, host_raw))

        # A12 fail-closed: kontrol karakteri / eksik alan
        if CTRL_RE.search(host_raw) or CTRL_RE.search(path) or CTRL_RE.search(scheme):
            return self._deny(req, "MALFORMED_TARGET", endpoint)
        if not host_raw or not scheme or port is None:
            return self._deny(req, "MALFORMED_TARGET", endpoint)

        # Tenant scope — policy tenant'ı request tenant'ı ile eşleşmeli
        if self.policy.get("tenant_id") and req.get("tenant_id") and req["tenant_id"] != self.policy["tenant_id"]:
            return self._deny(req, "POLICY_TENANT_MISMATCH", endpoint)

        host = host_raw.rstrip(".").lower()
        kind, _ = host_kind(host)
        if kind == "malformed":
            return self._deny(req, "MALFORMED_TARGET", endpoint)

        # A2 metadata host adı (IP'den önce — adla erişim de bloklanır)
        if self._block_metadata() and host.strip("[]") in METADATA_HOSTS:
            return self._deny(req, "METADATA_BLOCKED", endpoint)

        # SSRF'e karşı değerlendirilecek IP kümesi
        if kind == "ip":
            ips = [host.strip("[]")]
        else:  # DNS adı → resolved_ips zorunlu (yoksa fail-closed)
            ips = list(req.get("resolved_ips") or [])
            if not ips:
                return self._deny(req, "MALFORMED_TARGET", endpoint)

        classes = []
        for ip in ips:
            c = classify_ip(ip)
            if c is None:
                return self._deny(req, "MALFORMED_TARGET", endpoint)  # çözülemeyen IP → fail-closed
            classes.append(c)

        # A2/A3/A4/A9 — block-overrides-allow (allow kuralından ÖNCE)
        if self._block_metadata() and "metadata" in classes:
            return self._deny(req, "METADATA_BLOCKED", endpoint)
        if self._block_private() and "private" in classes:
            reason = "PRIVATE_NETWORK_BLOCKED" if kind == "ip" else "DNS_REBINDING_BLOCKED"
            return self._deny(req, reason, endpoint)

        # A5 scheme
        schemes = [s.lower() for s in self.policy.get("schemes_allowed", ["https"])]
        if scheme not in schemes:
            return self._deny(req, "SCHEME_BLOCKED", endpoint)
        # A6 port
        if port not in self.policy.get("ports_allowed", [443]):
            return self._deny(req, "PORT_BLOCKED", endpoint)

        # A8 path normalize / traversal
        norm = normalize_path(path)
        if norm is None:
            return self._deny(req, "MALFORMED_TARGET", endpoint)

        # A1/A7/A8 allow eşleme
        status, idx = self._match_allow(req.get("connector_id"), scheme, host, port, norm)
        if status == "permit":
            return self._permit(req, idx, endpoint)
        if status == "path":
            return self._deny(req, "PATH_NOT_ALLOWED", endpoint)
        return self._deny(req, "UNLISTED_ENDPOINT", endpoint)


# ── sample yürütme + kapı ─────────────────────────────────────────────────────────
def _policy_for(sample, cfg):
    if "policy" in sample:
        return _strip_meta(sample["policy"])
    pname = sample["profile"]
    return _strip_meta(cfg["profiles"][pname])


def _run_sample(sample, cfg):
    policy = _policy_for(sample, cfg)
    gate = EgressGate(policy, enforce_ssrf=sample.get("enforce_ssrf", True))
    out = {}
    for req in sample.get("requests", []):
        out[req["call_id"]] = gate.decide(req)
    return gate, out


def _internal_target(req):
    """Policy'den BAĞIMSIZ güvenlik tabanı: hedef metadata/private IP'ye dokunuyor mu (A2/A3 floor)."""
    target = req.get("target") or {}
    host = str(target.get("host") or "").strip("[]").rstrip(".").lower()
    if host in METADATA_HOSTS:
        return True
    kind, _ = host_kind(host)
    ips = [host] if kind == "ip" else list(req.get("resolved_ips") or [])
    for ip in ips:
        if classify_ip(ip) in ("metadata", "private"):
            return True
    return False


def _forbidden_tokens(req):
    """A11 — audit'te ASLA görünmemesi gereken değerler: interpole path SEGMENTİ (template'te OLMAYAN),
    resolved IP, query değeri. Statik path segmenti (endpoint template'inde geçen) yasak DEĞİL."""
    toks = set()
    target = req.get("target") or {}
    endpoint = str(req.get("endpoint") or "")
    for seg in str(target.get("path") or "").split("/"):
        if seg and seg not in endpoint:   # yalnız interpole/template-dışı değer (ör. 'C-1001')
            toks.add(seg)
    host = str(target.get("host") or "").strip("[]")
    for ip in (req.get("resolved_ips") or []):
        if str(ip) != host:   # host IP-literal ise endpoint'te zaten var (düşük kardinalite kimlik, leak DEĞİL)
            toks.add(str(ip))
    for v in (req.get("query") or {}).values():
        toks.add(str(v))
    return {t for t in toks if t and len(t) >= 4}


def _check_gates(sample, gate, results):
    fails = []
    policy = None
    for cid, dec in results.items():
        req = next(r for r in sample["requests"] if r["call_id"] == cid)
        exp = (sample.get("expect") or {}).get(cid)
        # beklenen karar/reason
        if exp:
            if dec["decision"] != exp.get("decision"):
                fails.append("%s: decision %s != %s" % (cid, dec["decision"], exp.get("decision")))
            if "reason_code" in exp and dec["reason_code"] != exp["reason_code"]:
                fails.append("%s: reason %s != %s" % (cid, dec["reason_code"], exp["reason_code"]))
        # G-SSRF floor (A2/A3/A9 — policy toggle'dan BAĞIMSIZ): iç hedef → MUTLAKA deny
        if _internal_target(req) and dec["decision"] != "deny":
            fails.append("%s: SSRF-floor — iç hedef PERMIT edildi (A9 ihlali)" % cid)
        # G-default-deny (A1): permit yalnız reason ALLOWED + matched_rule var
        if dec["decision"] == "permit" and (dec["reason_code"] != PERMIT_REASON or dec["matched_rule"] is None):
            fails.append("%s: permit ama ALLOWED/matched_rule tutarsız" % cid)
        # deny → ENDPOINT_NOT_ALLOWED terminal fault
        if dec["decision"] == "deny" and dec["fault_class"] != DENY_FAULT:
            fails.append("%s: deny fault_class %s != %s" % (cid, dec["fault_class"], DENY_FAULT))
        if dec["reason_code"] not in (DENY_REASONS | {PERMIT_REASON}):
            fails.append("%s: bilinmeyen reason_code %s" % (cid, dec["reason_code"]))
    # A11 audit no-log — yasak token taraması
    blob = json.dumps(gate.audit, ensure_ascii=False)
    for req in sample["requests"]:
        for tok in _forbidden_tokens(req):
            if tok in blob:
                fails.append("%s: A11 audit'te yasak değer (%s)" % (req["call_id"], tok))
    # A10 determinizm — yeniden çalıştır, birebir aynı
    gate2, results2 = _run_sample(sample, _CFG)
    if json.dumps(results, sort_keys=True) != json.dumps(results2, sort_keys=True):
        fails.append("A10 determinizm ihlali")
    return (len(fails) == 0), fails


_CFG = None


def decide_cmd(sample_path):
    global _CFG
    _CFG = _load(CONFIG_PATH)
    sample = _load(sample_path)
    try:
        gate, results = _run_sample(sample, _CFG)
    except (PolicyError, KeyError) as e:
        if sample.get("expect_invalid_policy"):
            print("✓ %s — INVALID_POLICY beklendi: %s" % (os.path.basename(sample_path), e))
            return 0
        print("✗ policy/sample hatası: %s" % e)
        return 1
    ok, fails = _check_gates(sample, gate, results)
    degraded = sample.get("expect_degraded", False)
    print("decide: %s" % sample.get("name", os.path.basename(sample_path)))
    for cid, dec in results.items():
        print("  %-10s → %-6s %-24s rule=%s" % (cid, dec["decision"], dec["reason_code"], dec["matched_rule"]))
    if degraded:
        status = "🔴 (beklenen eleme — degraded)" if not ok else "BEKLENMEDİK YEŞİL"
        print("kapı: %s" % status)
        for m in fails:
            print("  · %s" % m)
        return 0 if not ok else 1
    print("kapı: %s" % ("🟢" if ok else "🔴"))
    for m in fails:
        print("  ✗ %s" % m)
    return 0 if ok else 1


# ── validate (statik) ─────────────────────────────────────────────────────────────
def validate():
    global _CFG
    fails = []

    def expect(c, m):
        if not c:
            fails.append(m)

    spec = _load(SPEC_PATH)
    cfg = _load(CONFIG_PATH)
    _CFG = cfg

    expect(spec.get("wbs") == "7.2.3", "spec.wbs 7.2.3")
    expect("FR-TOOL-012" in spec["trace"]["fr"], "trace FR-TOOL-012")
    expect("SR-TOOL-012" in spec["trace"]["srs"], "trace SR-TOOL-012")
    expect("TC-TOOL-012" in spec["trace"]["rtm"], "trace TC-TOOL-012")
    expect([inv["id"] for inv in spec["invariants"]] == GATE_IDS, "invariants A1–A12 sırası")
    dc = spec["decision_contract"]
    expect(set(dc["deny_reasons"]) == DENY_REASONS, "deny_reasons spec↔kod")
    expect(dc["permit_reason"] == PERMIT_REASON, "permit_reason spec↔kod")
    expect(dc["deny_fault_class"] == DENY_FAULT, "deny_fault_class spec↔kod")
    expect(spec["fault_alignment"]["gate_terminal_fault"] == DENY_FAULT, "fault_alignment terminal fault")
    expect(spec["fault_alignment"]["retryable"] is False, "ENDPOINT_NOT_ALLOWED retry edilmez")

    # her profil geçerli policy'ye dönüşür (default-deny zorunlu)
    for pname, prof in cfg["profiles"].items():
        try:
            EgressGate(_strip_meta(prof))
        except PolicyError as e:
            fails.append("profil %s geçersiz policy (%s)" % (pname, e.reason))

    # sır/PII taraması (spec/config/samples)
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
        if sample.get("expect_invalid_policy"):
            try:
                _run_sample(sample, cfg)
                fails.append("INVALID_POLICY bekleniyordu: %s" % f)
            except (PolicyError, KeyError):
                pass
            continue
        gate, results = _run_sample(sample, cfg)
        ok, _ = _check_gates(sample, gate, results)
        if sample.get("expect_degraded"):
            expect(not ok, "degraded sample KIRMIZI olmalı: %s" % f)
        else:
            expect(ok, "sample kapısı: %s" % f)

    print("validate: %d kontrol başarısız" % len(fails))
    for m in fails:
        print("  ✗ %s" % m)
    return 0 if not fails else 1


# ── selftest (gömülü davranış) ─────────────────────────────────────────────────────
def _policy(**over):
    p = {
        "tenant_id": "t-1",
        "default_action": "deny",
        "schemes_allowed": ["https"],
        "ports_allowed": [443],
        "block_metadata": True,
        "block_private_networks": True,
        "allow": [
            {"connector_id": "crm-rest", "scheme": "https", "host": "crm.example.com", "port": 443, "path_prefix": "/v1/"},
            {"scheme": "https", "host": "*.partner.example.com", "port": 443},
        ],
    }
    p.update(over)
    return p


def _req(host, **over):
    r = {
        "call_id": "c", "correlation_id": "corr-1", "tenant_id": "t-1", "connector_id": "crm-rest",
        "method": "GET", "endpoint": "GET https://%s/v1/customers/{id}" % host,
        "target": {"scheme": "https", "host": host, "port": 443, "path": "/v1/customers/C-1001"},
        "resolved_ips": ["203.0.113.10"],
    }
    r.update(over)
    if "target" in over:
        r["target"] = over["target"]
    return r


def selftest():
    fails = []
    n = 0

    def expect(c, m):
        nonlocal n
        n += 1
        if not c:
            fails.append(m)

    g = EgressGate(_policy())

    # A1 default-deny — allowlist dışı host (SR-TOOL-012 kabul ölçütü)
    d = g.decide(_req("unknown.attacker.net",
                      target={"scheme": "https", "host": "unknown.attacker.net", "port": 443, "path": "/x"},
                      resolved_ips=["203.0.113.50"]))
    expect(d["decision"] == "deny" and d["reason_code"] == "UNLISTED_ENDPOINT", "A1 unlisted → deny")
    expect(d["fault_class"] == DENY_FAULT, "A1 deny → ENDPOINT_NOT_ALLOWED")

    # A1 permit — allowlist'li exact host, public IP
    d = g.decide(_req("crm.example.com"))
    expect(d["decision"] == "permit" and d["reason_code"] == PERMIT_REASON and d["matched_rule"] == 0, "A1 permit exact")

    # A7 wildcard — *.partner.example.com
    d = g.decide(_req("api.partner.example.com",
                      target={"scheme": "https", "host": "api.partner.example.com", "port": 443, "path": "/anything"},
                      resolved_ips=["203.0.113.20"]))
    expect(d["decision"] == "permit" and d["matched_rule"] == 1, "A7 wildcard subdomain permit")
    # A7 apex wildcard EŞLEŞMEZ
    d = g.decide(_req("partner.example.com",
                      target={"scheme": "https", "host": "partner.example.com", "port": 443, "path": "/x"},
                      resolved_ips=["203.0.113.20"]))
    expect(d["decision"] == "deny", "A7 wildcard apex eşleşmez → deny")
    # A7 substring confusion EŞLEŞMEZ
    d = g.decide(_req("crm.example.com.attacker.net",
                      target={"scheme": "https", "host": "crm.example.com.attacker.net", "port": 443, "path": "/v1/x"},
                      resolved_ips=["203.0.113.30"]))
    expect(d["decision"] == "deny" and d["reason_code"] == "UNLISTED_ENDPOINT", "A7 substring confusion → deny")

    # A2 metadata IP — allowlist'li hostmuş gibi davransa bile (rebinding→metadata)
    d = g.decide(_req("crm.example.com", resolved_ips=["169.254.169.254"]))
    expect(d["decision"] == "deny" and d["reason_code"] == "METADATA_BLOCKED", "A2 metadata IP block (allow EZİLİR)")
    # A2 metadata host adı
    d = g.decide(_req("metadata.google.internal",
                      target={"scheme": "https", "host": "metadata.google.internal", "port": 443, "path": "/x"},
                      resolved_ips=["10.0.0.9"]))
    expect(d["decision"] == "deny" and d["reason_code"] == "METADATA_BLOCKED", "A2 metadata host adı block")

    # A3 private IP literal host
    d = g.decide(_req("192.168.1.10",
                      target={"scheme": "https", "host": "192.168.1.10", "port": 443, "path": "/x"}))
    expect(d["decision"] == "deny" and d["reason_code"] == "PRIVATE_NETWORK_BLOCKED", "A3 private IP literal block")
    # A3 loopback
    d = g.decide(_req("127.0.0.1", target={"scheme": "https", "host": "127.0.0.1", "port": 443, "path": "/x"}))
    expect(d["reason_code"] == "PRIVATE_NETWORK_BLOCKED", "A3 loopback block")

    # A4 DNS rebinding — allowlist'li host iç IP'ye çözülür
    d = g.decide(_req("crm.example.com", resolved_ips=["10.5.5.5"]))
    expect(d["decision"] == "deny" and d["reason_code"] == "DNS_REBINDING_BLOCKED", "A4 rebinding block")
    # A4 çok-IP: biri iç → blok
    d = g.decide(_req("crm.example.com", resolved_ips=["203.0.113.10", "172.16.0.4"]))
    expect(d["reason_code"] == "DNS_REBINDING_BLOCKED", "A4 çok-IP biri iç → blok")

    # A5 scheme
    d = g.decide(_req("crm.example.com",
                      target={"scheme": "http", "host": "crm.example.com", "port": 443, "path": "/v1/x"}))
    expect(d["reason_code"] == "SCHEME_BLOCKED", "A5 http blok (https-only)")
    d = g.decide(_req("crm.example.com",
                      target={"scheme": "file", "host": "crm.example.com", "port": 443, "path": "/etc/passwd"}))
    expect(d["reason_code"] == "SCHEME_BLOCKED", "A5 file:// blok")

    # A6 port
    d = g.decide(_req("crm.example.com",
                      target={"scheme": "https", "host": "crm.example.com", "port": 8080, "path": "/v1/x"}))
    expect(d["reason_code"] == "PORT_BLOCKED", "A6 port blok")

    # A8 path_prefix — /admin /v1/ altında değil
    d = g.decide(_req("crm.example.com",
                      target={"scheme": "https", "host": "crm.example.com", "port": 443, "path": "/admin/secrets"}))
    expect(d["decision"] == "deny" and d["reason_code"] == "PATH_NOT_ALLOWED", "A8 path_prefix dışı → PATH_NOT_ALLOWED")
    # A8 traversal
    d = g.decide(_req("crm.example.com",
                      target={"scheme": "https", "host": "crm.example.com", "port": 443, "path": "/v1/../admin"}))
    expect(d["reason_code"] == "MALFORMED_TARGET", "A8 traversal → MALFORMED_TARGET")
    # A8 segment-sınırı: /v1x prefix /v1/ ile eşleşmez
    d = g.decide(_req("crm.example.com",
                      target={"scheme": "https", "host": "crm.example.com", "port": 443, "path": "/v1extra/x"}))
    expect(d["reason_code"] == "PATH_NOT_ALLOWED", "A8 /v1extra segment-sınırı eşleşmez")

    # A9 block-overrides-allow — toggle açıkken iç IP allow'u ezer (yukarıda A2/A4 zaten)
    # A12 fail-closed — bozuk hedef
    d = g.decide(_req("crm.example.com",
                      target={"scheme": "https", "host": "crm.example.com", "port": None, "path": "/v1/x"}))
    expect(d["reason_code"] == "MALFORMED_TARGET", "A12 port yok → MALFORMED")
    d = g.decide(_req("crm.example.com",
                      target={"scheme": "https", "host": "crm.example.com\r\nEvil: 1", "port": 443, "path": "/v1/x"}))
    expect(d["reason_code"] == "MALFORMED_TARGET", "A12 host CRLF → MALFORMED")
    # decimal IP obfuscation → malformed (permit'e taşınmaz)
    d = g.decide(_req("2130706433",
                      target={"scheme": "https", "host": "2130706433", "port": 443, "path": "/v1/x"}))
    expect(d["reason_code"] == "MALFORMED_TARGET", "A12 decimal IP obfuscation → MALFORMED")
    # DNS adı ama resolved_ips yok → fail-closed
    d = g.decide(_req("crm.example.com", resolved_ips=[]))
    expect(d["reason_code"] == "MALFORMED_TARGET", "A12 resolved_ips yok → MALFORMED (fail-closed)")

    # tenant mismatch
    d = g.decide(_req("crm.example.com", tenant_id="t-OTHER"))
    expect(d["reason_code"] == "POLICY_TENANT_MISMATCH", "tenant mismatch → deny")

    # A11 audit no-log — interpole path / resolved IP audit'te yok
    g2 = EgressGate(_policy())
    g2.decide(_req("crm.example.com"))
    blob = json.dumps(g2.audit, ensure_ascii=False)
    expect("C-1001" not in blob and "203.0.113.10" not in blob and "/v1/customers/C-1001" not in blob,
           "A11 audit'te interpole değer/IP yok")
    expect(g2.audit[0]["no_log"] is True and "{id}" in g2.audit[0]["endpoint"], "A11 endpoint template + no_log")

    # A10 determinizm
    e1 = EgressGate(_policy()).decide(_req("crm.example.com"))
    e2 = EgressGate(_policy()).decide(_req("crm.example.com"))
    expect(json.dumps(e1, sort_keys=True) == json.dumps(e2, sort_keys=True), "A10 determinizm")

    # INVALID_POLICY — default_action allow reddedilir
    try:
        EgressGate(_policy(default_action="allow"))
        expect(False, "INVALID_POLICY beklendi (default allow)")
    except PolicyError:
        expect(True, "INVALID_POLICY default allow reddedildi")

    # SSRF-floor kapı kanıtı — enforce_ssrf=False (degraded) iç IP'yi PERMIT eder → floor YAKALAR
    gx = EgressGate(_policy(block_private_networks=False, block_metadata=False), enforce_ssrf=False)
    dperm = gx.decide(_req("crm.example.com", resolved_ips=["169.254.169.254"]))
    expect(dperm["decision"] == "permit", "degraded: SSRF kapalı → iç IP PERMIT (kasıtlı)")
    sample_like = {"requests": [_req("crm.example.com", resolved_ips=["169.254.169.254"])], "expect": {}}
    expect(_internal_target(sample_like["requests"][0]) is True, "SSRF-floor: iç hedef tespit edilir")

    print("selftest: %d kontrol, %d başarısız" % (n, len(fails)))
    for m in fails:
        print("  ✗ %s" % m)
    return 0 if not fails else 1


def schema_cmd():
    spec = _load(SPEC_PATH)
    dc = spec["decision_contract"]
    print(json.dumps({
        "wbs": spec["wbs"],
        "policy_fields": dc["policy_fields"],
        "allow_rule_fields": dc["allow_rule_fields"],
        "request_fields": dc["request_fields"],
        "target_fields": dc["target_fields"],
        "decision_fields": dc["decision_fields"],
        "permit_reason": PERMIT_REASON,
        "deny_reasons": sorted(DENY_REASONS),
        "deny_fault_class": DENY_FAULT,
        "invariants": [i["id"] for i in spec["invariants"]],
        "default_action": "deny",
    }, ensure_ascii=False, indent=2))
    return 0


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd = argv[1]
    if cmd == "validate":
        return validate()
    if cmd == "decide":
        if len(argv) < 3:
            print("kullanım: endpoint_allowlist_probe.py decide <sample.json>")
            return 2
        return decide_cmd(argv[2])
    if cmd == "selftest":
        return selftest()
    if cmd == "schema":
        return schema_cmd()
    print("bilinmeyen komut: %s" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
