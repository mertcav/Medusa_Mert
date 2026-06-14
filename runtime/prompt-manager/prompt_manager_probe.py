#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prompt_manager_probe.py — WBS 3.2.3 Prompt Manager: versiyonlu sabit system prompt enjeksiyonu

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only statik + davranış kapısı.
`runtime/summarization/` (3.2.2) + `runtime/session-memory/` (3.2.1) disipliniyle aynı; burada
deterministik bir PROMPT MONTAJCISI (SAD §6.2 Prompt Manager) simülatörü (olay-tetikli, sanal saat,
random YOK; gerçek LLM çağrısı YOK — segment montaj + hash MODELİ).

CONVERSATION ORCHESTRATOR (Çekirdek IP, SAD §6) oturum aktöründe THINK durumunda çalışan Prompt Manager:
  • Versiyon:   system prompt çağrı başında YAYIMLANMIŞ versiyona sabitlenir + drift yok + kaydedilir (P1).
  • Değişmez:   montajlanan system segmenti pin'lenmiş gövdeyle birebir (P2 — FR-LLM-006'nın kalbi).
  • Katman:     caller/KB içeriği system rolünde DEĞİL (trust layering — P3).
  • Çit:        düşük-güven override system'e uygulanmaz (yapısal; semantik → 3.3.1 — P4).
  • Sıra:       system önce/en yüksek + sabit precedence (P5).
  • İdempotent: tam bir system segmenti + deterministik (P6).
  • İzolasyon:  {tenant,agent} izole (P7 — RLS 1.1.2).
  • Yayım:      yalnız is_published versiyon + kaydedilir, fail-closed (P8 — FR-LLM-011).

KAPSAM AYRIMI: injection/jailbreak SEMANTİK tespiti → 3.3.1/3.3.2 (motor yalnız yapısal sınır);
prompt editörü/versiyon oluşturma → A-06/API; prompt depolama/WORM → DB 1.1.2; flow node yürütme →
3.2.4; history penceresi/özet → 3.2.1/3.2.2 (tüketilir); LLM routing → SAD §9; PII redaction L7 → 3.3.x.

Komutlar:
  validate              prompt-manager-spec.json'ı invariant'lara (P1–P10) + config profillerine doğrular.
  simulate <sample>     Deterministik Prompt Manager — olay-akışı (pin + segment + assemble + end) →
                        versiyon sabitleme + değişmezlik + katman + çit + montaj + HARD kapılar (P1–P8);
                        →çıkış kodu.
  selftest              İyi/kötü spec+sample ile kapıların doğru tetiklendiğini kanıtlar.
  schema                Beklenen spec şeklini özetler.

Sunucu/credential GEREKMEZ. simulate gerçek LLM/registry/tokenizer yerine deterministik segment montaj
+ hash modelidir (canlı sistemde Go/Rust runtime + gerçek prompt registry, ADR-003/SAD §6.3/DB 1.1.2).
Ham prompt/transkript METNİ/PII DEĞERİ YOK — yalnız rol/kaynak + token (approx_tokens) SAYILARI + opak
içerik HASH'leri + versiyon kimlikleri + sanal zaman + sensitive-işaret sayıları.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "prompt-manager-spec.json")
PROFILES_CFG = os.path.join(HERE, "config", "prompt-manager-profiles.json")

ERROR_TAXONOMY = {
    "TIMEOUT", "RATE_LIMITED", "UNAVAILABLE", "AUTH",
    "INVALID_REQUEST", "CONTENT_FILTERED", "QUOTA_EXCEEDED", "REGION_VIOLATION",
}
SECRET_RE = re.compile(
    r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer)\b\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}"
)
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")

PRECEDENCE = {"system": 0, "policy": 1, "history": 2, "kb_context": 3, "user_turn": 4}
CONTENT_ROLES = {"policy", "history", "kb_context", "user_turn"}
UNTRUSTED_SOURCES = {"caller", "kb_retrieval"}
ROLE_SOURCE = {
    "policy": "policy_registry",
    "history": "session_memory",
    "kb_context": "kb_retrieval",
    "user_turn": "caller",
}
END_STATES = {"normal", "transfer", "error", "abandon"}


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_placeholder(v):
    return isinstance(v, str) and PLACEHOLDER_RE.match(v) is not None


class PromptError(Exception):
    """Geçersiz/desteklenmeyen olay — sessizce kabul yok, reddet (P10)."""


# ─────────────────────────────────────────────────────────────────────────────
# Prompt Manager — versiyonlu sabit system prompt enjeksiyonu (deterministik)
# ─────────────────────────────────────────────────────────────────────────────
class PromptManager:
    """SAD §6.2 Prompt Manager. Olay-akışını işler: pin + segment + assemble + end. Çağrı başında bir
    YAYIMLANMIŞ prompt versiyonunu sabitler (system_hash); her assemble'de system segmentini pin'lenmiş
    gövdeyle BİREBİR montajlar (KIRPMAZ/DEĞİŞTİRMEZ) + düşük-güven (caller/KB) segmentlerini AYRI,
    çitlenmiş, daha düşük yetkili rollere yerleştirir. Olay-tetikli; sanal saat (event.t) — random YOK.

    Olaylar:
      {kind:'pin', version_id, version_no, published, system_hash, system_tokens, t, tenant_id?, agent_id?}
      {kind:'segment', role, t, approx_tokens, content_hash?, contains_override?, sensitive_tokens?,
                       source?, tenant_id?}
      {kind:'assemble', t}
      {kind:'end', t, reason∈end_states}
    """

    def __init__(self, params, policy):
        self.system_token_budget = float(params.get("system_token_budget", 1200))
        self.total_budget = float(params.get("total_prompt_token_budget", 6000))
        self.tenant_id = params.get("tenant_id", "t-self")
        self.agent_id = params.get("agent_id", "a-self")
        self.pol = policy

        # pin durumu
        self.pinned = None              # {version_id, version_no, published, system_hash, system_tokens}
        self.version_recorded = False
        self.segments = []              # içerik segmentleri
        self._last_t = None

        # sayaçlar / metrikler
        self.assemble_ops = 0
        self.version_drift = 0          # çağrı içi farklı versiyona repin (bug)
        self.system_mutated = 0         # system segmenti pin'lenmiş gövdeden saptı (FR-LLM-006 ihlali)
        self.content_in_system_role = 0 # caller/KB içeriği system rolüne girdi (bug)
        self.override_seen = 0          # düşük-güven segmentte override işareti
        self.override_applied = 0       # override system'e uygulandı (bug)
        self.order_violation = 0        # yetki sırası bozuldu (bug)
        self.duplicate_system = 0       # birden çok system segmenti (bug)
        self.unpublished_injected = 0   # yayımlanmamış versiyon enjekte edildi (bug)
        self.cross_tenant = 0
        self.out_of_order = 0
        self.sensitive_seen = 0
        self.sensitive_in_system = 0
        self.assembled_system_hash = None
        self.total_prompt_tokens_max = 0.0
        self.over_total_budget = 0
        self.system_over_budget = 0
        self.ended = False
        self.end_reason = None

    # ── tenant/agent + sıra ortak kontrol ─────────────────────────────────────
    def _check_scope(self, ev):
        tt = ev.get("tenant_id", self.tenant_id)
        at = ev.get("agent_id", self.agent_id)
        if tt != self.tenant_id or at != self.agent_id:
            if self.pol.get("tenant_isolation", True):
                self.cross_tenant += 1
                raise PromptError("cross-tenant/agent erişim reddedildi → AUTH")
            else:
                self.cross_tenant += 1

    def _check_time(self, t):
        if not isinstance(t, (int, float)):
            raise PromptError("zaman damgası sayısal değil → INVALID_REQUEST")
        if self._last_t is not None and t < self._last_t:
            if self.pol.get("order_guard", True):
                self.out_of_order += 1
                raise PromptError("out-of-order olay (t geriye) reddedildi → INVALID_REQUEST")
            else:
                self.out_of_order += 1
        self._last_t = max(self._last_t if self._last_t is not None else t, t)

    # ── pin: versiyon sabitleme (P1/P8) ───────────────────────────────────────
    def pin(self, ev):
        if self.ended:
            raise PromptError("bitmiş oturuma pin yapılamaz → INVALID_REQUEST")
        self._check_time(ev.get("t"))
        self._check_scope(ev)
        vid = ev.get("version_id")
        vno = ev.get("version_no")
        if not isinstance(vid, str) or not vid:
            raise PromptError("version_id yok/boş → INVALID_REQUEST")
        if not isinstance(vno, int) or vno <= 0:
            raise PromptError("version_no pozitif int değil → INVALID_REQUEST")
        published = ev.get("published", True)
        if not isinstance(published, bool):
            raise PromptError("published bool değil → INVALID_REQUEST")
        shash = ev.get("system_hash")
        if not isinstance(shash, str) or not shash:
            raise PromptError("system_hash yok/boş → INVALID_REQUEST")
        stok = ev.get("system_tokens", 0)
        if not isinstance(stok, (int, float)) or stok < 0:
            raise PromptError("system_tokens sayısal/≥0 değil → INVALID_REQUEST")

        # yayımlanmamış versiyon (P8): yayım zorunluysa reddet (fail-closed), değilse enjekte ed → bug
        if not published:
            if self.pol.get("published_only", True):
                raise PromptError("yayımlanmamış prompt versiyonu reddedildi (fail-closed) → INVALID_REQUEST")
            else:
                self.unpublished_injected += 1

        if self.pinned is not None:
            if self.pinned["version_id"] == vid:
                return  # idempotent re-pin (aynı versiyon)
            # farklı versiyona çağrı-içi repin
            if self.pol.get("stable_version", True):
                raise PromptError("çağrı içi versiyon repin reddedildi (drift yok) → INVALID_REQUEST")
            else:
                self.version_drift += 1
                self.pinned = {"version_id": vid, "version_no": vno, "published": published,
                               "system_hash": shash, "system_tokens": float(stok)}
                if self.pol.get("record_version", True):
                    self.version_recorded = True
                return

        self.pinned = {"version_id": vid, "version_no": vno, "published": published,
                       "system_hash": shash, "system_tokens": float(stok)}
        if self.pol.get("record_version", True):
            self.version_recorded = True
        if stok > self.system_token_budget:
            self.system_over_budget += 1

    # ── segment: düşük-yetkili içerik (P3/P6) ─────────────────────────────────
    def segment(self, ev):
        if self.ended:
            raise PromptError("bitmiş oturuma segment eklenemez → INVALID_REQUEST")
        self._check_time(ev.get("t"))
        self._check_scope(ev)
        role = ev.get("role")
        if role == "system":
            # içerik segmenti system rolü TALEP EDEMEZ — system yalnız registry/pin kaynaklı (P3/P6)
            raise PromptError("içerik segmenti role=system talep edemez → INVALID_REQUEST")
        if role not in CONTENT_ROLES:
            raise PromptError("geçersiz segment rolü: %r → INVALID_REQUEST" % role)
        approx = ev.get("approx_tokens")
        if not isinstance(approx, (int, float)) or approx < 0:
            raise PromptError("approx_tokens sayısal/≥0 değil → INVALID_REQUEST")
        override = bool(ev.get("contains_override", False))
        sens = ev.get("sensitive_tokens", 0)
        if not isinstance(sens, int) or sens < 0:
            raise PromptError("sensitive_tokens int/≥0 değil → INVALID_REQUEST")
        source = ev.get("source", ROLE_SOURCE[role])

        seg = {"role": role, "source": source, "approx_tokens": float(approx),
               "content_hash": ev.get("content_hash", "h-%s" % role),
               "contains_override": override, "sensitive_tokens": sens,
               "untrusted": source in UNTRUSTED_SOURCES}
        self.segments.append(seg)
        if sens > 0:
            self.sensitive_seen += sens
        if override and seg["untrusted"]:
            self.override_seen += 1

    # ── assemble: system + segment montajı (P2/P3/P4/P5/P6) ───────────────────
    def assemble(self, ev):
        if self.ended:
            raise PromptError("bitmiş oturumda assemble yapılamaz → INVALID_REQUEST")
        self._check_time(ev.get("t"))
        if self.pinned is None:
            # system prompt yok → fail-closed (kullanıcı içeriğine fallback YOK)
            raise PromptError("pin'lenmiş system prompt yok → INVALID_REQUEST (fail-closed)")
        self.assemble_ops += 1

        pinned_hash = self.pinned["system_hash"]
        untrusted = [s for s in self.segments if s["untrusted"]]

        # ── P2: system segmenti pin'lenmiş gövdeyle birebir mi?
        if not self.pol.get("immutable_system", True):
            # BOZUK: caller/KB içeriği system gövdesine BİRLEŞTİRİLİR → hash sapar (FR-LLM-006 ihlali)
            self.assembled_system_hash = pinned_hash + "+mutated"
            self.system_mutated += 1
            for s in untrusted:
                self.content_in_system_role += 1
                if s["contains_override"]:
                    self.override_applied += 1
                if s["sensitive_tokens"] > 0:
                    self.sensitive_in_system += s["sensitive_tokens"]
        else:
            self.assembled_system_hash = pinned_hash

        # ── P3: trust layering kapalı → düşük-güven içerik system ROLÜNE konur (gövde sabit ama rol ihlali)
        if not self.pol.get("trust_layering", True):
            for s in untrusted:
                self.content_in_system_role += 1
                if s["sensitive_tokens"] > 0:
                    self.sensitive_in_system += s["sensitive_tokens"]

        # ── P4: çit kapalı → düşük-güven override system'e UYGULANIR
        if not self.pol.get("fence_untrusted", True):
            for s in untrusted:
                if s["contains_override"]:
                    self.override_applied += 1

        # ── P5/P6: montaj sırası + tek system segmenti
        seq, viol = self._assemble_order()
        self.order_violation += viol

        # ── token muhasebesi (informatif)
        total = self.pinned["system_tokens"] + sum(s["approx_tokens"] for s in self.segments)
        self.total_prompt_tokens_max = max(self.total_prompt_tokens_max, total)
        if total > self.total_budget:
            self.over_total_budget += 1

    def _assemble_order(self):
        others = list(self.segments)
        if self.pol.get("ordered_assembly", True):
            others.sort(key=lambda s: PRECEDENCE[s["role"]])
        sysseg = {"role": "system"}
        if self.pol.get("system_first", True):
            seq = [sysseg] + others
        else:
            # BOZUK: system en sona konur → yetki inversiyonu (P5 eler)
            seq = others + [sysseg]
        prev = -1
        viol = 0
        for s in seq:
            p = PRECEDENCE[s["role"]]
            if p < prev:
                viol += 1
            prev = max(prev, p)
        return seq, viol

    def end(self, ev):
        if self.ended:
            raise PromptError("oturum zaten bitti → INVALID_REQUEST")
        reason = ev.get("reason", "normal")
        if reason not in END_STATES:
            raise PromptError("geçersiz bitiş nedeni: %r → INVALID_REQUEST" % reason)
        self.ended = True
        self.end_reason = reason

    def metrics(self):
        scenario = []
        if self.pinned is not None:
            scenario.append("pinned")
        if self.assemble_ops > 0:
            scenario.append("assemble")
        if self.override_seen > 0:
            scenario.append("override-fenced" if self.override_applied == 0 else "override-applied")
        if any(s["source"] == "kb_retrieval" for s in self.segments):
            scenario.append("kb-context")
        if self.system_mutated > 0:
            scenario.append("system-mutated")
        if self.unpublished_injected > 0:
            scenario.append("unpublished")
        if not scenario:
            scenario.append("empty")
        sys_match = (self.assembled_system_hash is None
                     or (self.pinned is not None
                         and self.assembled_system_hash == self.pinned["system_hash"]))
        return {
            "pinned": self.pinned is not None,
            "pinned_version_no": (self.pinned or {}).get("version_no"),
            "pinned_version_id": (self.pinned or {}).get("version_id"),
            "published": (self.pinned or {}).get("published"),
            "version_recorded": self.version_recorded,
            "version_drift": self.version_drift,
            "assemble_ops": self.assemble_ops,
            "segments_count": len(self.segments),
            "pinned_system_hash": (self.pinned or {}).get("system_hash"),
            "assembled_system_hash": self.assembled_system_hash,
            "system_hash_matches": sys_match,
            "system_mutated": self.system_mutated,
            "content_in_system_role": self.content_in_system_role,
            "override_seen": self.override_seen,
            "override_applied": self.override_applied,
            "order_violation": self.order_violation,
            "duplicate_system": self.duplicate_system,
            "unpublished_injected": self.unpublished_injected,
            "cross_tenant": self.cross_tenant,
            "out_of_order": self.out_of_order,
            "sensitive_seen": self.sensitive_seen,
            "sensitive_in_system": self.sensitive_in_system,
            "system_tokens": (self.pinned or {}).get("system_tokens", 0),
            "system_token_budget": self.system_token_budget,
            "system_over_budget": self.system_over_budget,
            "total_prompt_tokens": round(self.total_prompt_tokens_max, 2),
            "total_prompt_token_budget": self.total_budget,
            "over_total_budget": self.over_total_budget,
            "end_reason": self.end_reason,
            "scenario": scenario,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Tam simülasyon (bir sample)
# ─────────────────────────────────────────────────────────────────────────────
def simulate(sample, params, policy):
    events = sample.get("events")
    if events is None or not isinstance(events, list) or not events:
        raise PromptError("boş/geçersiz olay akışı → INVALID_REQUEST")
    p = dict(params)
    p["tenant_id"] = sample.get("tenant_id", params.get("tenant_id", "t-self"))
    p["agent_id"] = sample.get("agent_id", params.get("agent_id", "a-self"))
    pm = PromptManager(p, policy)
    saw_end = False
    for ev in events:
        if not isinstance(ev, dict):
            raise PromptError("olay sözlük değil → INVALID_REQUEST")
        kind = ev.get("kind")
        if kind == "pin":
            pm.pin(ev)
        elif kind == "segment":
            pm.segment(ev)
        elif kind == "assemble":
            pm.assemble(ev)
        elif kind == "end":
            pm.end(ev)
            saw_end = True
        else:
            raise PromptError("bilinmeyen olay tipi: %r → INVALID_REQUEST" % kind)
    if not saw_end:
        raise PromptError("olay akışında 'end' yok → INVALID_REQUEST")
    return pm.metrics()


def evaluate(gates, m):
    """Metrikleri HARD kapılara (P1–P8) karşı değerlendirir. Döner findings[(ok, label)]."""
    F = []

    # ── P1: versiyon sabitleme + drift yok
    F.append((m.get("version_drift", 0) <= gates.get("max_version_drift", 0)
              and m.get("pinned", False) is True,
              "P1 versiyon sabit: pinned=%s, version_drift %d ≤ %d (FR-AGT-004/FR-LLM-011)"
              % (m.get("pinned"), m.get("version_drift", 0), gates.get("max_version_drift", 0))))

    # ── P2: system değişmezliği (FR-LLM-006'nın kalbi)
    F.append((m.get("system_mutated", 0) <= gates.get("max_system_mutated", 0)
              and m.get("system_hash_matches", False) is True,
              "P2 değişmez: system_mutated %d ≤ %d, hash_matches=%s (FR-LLM-006 — caller/KB system'i değiştiremez)"
              % (m.get("system_mutated", 0), gates.get("max_system_mutated", 0),
                 m.get("system_hash_matches"))))

    # ── P3: trust layering
    F.append((m.get("content_in_system_role", 0) <= gates.get("max_content_in_system_role", 0),
              "P3 katman: content_in_system_role %d ≤ %d (caller/KB system rolünde değil)"
              % (m.get("content_in_system_role", 0), gates.get("max_content_in_system_role", 0))))

    # ── P4: override çit (yapısal)
    F.append((m.get("override_applied", 0) <= gates.get("max_override_applied", 0),
              "P4 çit: override_applied %d ≤ %d (override görüldü %d → system'e uygulanmadı; semantik → 3.3.1)"
              % (m.get("override_applied", 0), gates.get("max_override_applied", 0),
                 m.get("override_seen", 0))))

    # ── P5: yetki sırası
    F.append((m.get("order_violation", 0) <= gates.get("max_order_violation", 0),
              "P5 sıra: order_violation %d ≤ %d (system önce/en yüksek)"
              % (m.get("order_violation", 0), gates.get("max_order_violation", 0))))

    # ── P6: tek system segmenti + deterministik
    F.append((m.get("duplicate_system", 0) <= gates.get("max_duplicate_system", 0)
              and m.get("out_of_order", 0) == 0,
              "P6 idempotent: duplicate_system %d ≤ %d, out_of_order %d (deterministik)"
              % (m.get("duplicate_system", 0), gates.get("max_duplicate_system", 0),
                 m.get("out_of_order", 0))))

    # ── P7: tenant/agent izolasyon
    F.append((m.get("cross_tenant", 0) <= gates.get("max_cross_tenant", 0),
              "P7 izolasyon: cross_tenant %d ≤ %d ({tenant,agent} — FR-TEN-002/RLS 1.1.2)"
              % (m.get("cross_tenant", 0), gates.get("max_cross_tenant", 0))))

    # ── P8: yayımlanmış-yalnız + kaydedilir
    rec_ok = (not gates.get("require_version_recorded", True)) or (m.get("version_recorded", False) is True)
    F.append((m.get("unpublished_injected", 0) <= gates.get("max_unpublished_injected", 0) and rec_ok,
              "P8 yayım: unpublished_injected %d ≤ %d + version_recorded=%s (fail-closed; FR-LLM-011)"
              % (m.get("unpublished_injected", 0), gates.get("max_unpublished_injected", 0),
                 m.get("version_recorded"))))

    return F


# ─────────────────────────────────────────────────────────────────────────────
# parametre + politika çözümleme
# ─────────────────────────────────────────────────────────────────────────────
def _profile_by_name(cfg, name):
    for p in cfg.get("profiles", []):
        if p.get("name") == name:
            return p
    raise PromptError("bilinmeyen profil: %s" % name)


def _params_from(spec, profile):
    pm = dict(spec.get("prompt_model", {}))
    out = {
        "system_token_budget": pm.get("system_token_budget", 1200),
        "total_prompt_token_budget": pm.get("total_prompt_token_budget", 6000),
    }
    for k in ("system_token_budget", "total_prompt_token_budget"):
        if k in profile:
            out[k] = profile[k]
    return out


def _resolve_policy(spec, profile, sample):
    pol = {
        "immutable_system": True,
        "trust_layering": True,
        "fence_untrusted": True,
        "ordered_assembly": True,
        "system_first": True,
        "published_only": True,
        "stable_version": True,
        "record_version": True,
        "tenant_isolation": True,
        "order_guard": True,
    }
    pol.update(sample.get("policy", {}))
    return pol


def simulate_cmd(sample_path):
    spec = _load(SPEC_PATH)
    sample = _load(sample_path)
    name = sample.get("name", os.path.basename(sample_path))
    expect = sample.get("expect", "pass")

    if "profile_obj" in sample:
        profile = sample["profile_obj"]
    else:
        cfg = _load(PROFILES_CFG)
        try:
            profile = _profile_by_name(cfg, sample.get("profile", cfg.get("default_profile")))
        except PromptError as ex:
            print("simulate[%s]: %s" % (name, ex))
            return 0 if expect == "fail" else 1
    params = _params_from(spec, profile)
    policy = _resolve_policy(spec, profile, sample)
    gates = spec.get("gates", {})

    try:
        m = simulate(sample, params, policy)
    except PromptError as ex:
        print("simulate[%s]: REDDEDİLDİ — %s" % (name, ex))
        return 0 if expect == "fail" else 1

    F = evaluate(gates, m)
    print("simulate[%s] senaryo=%s | versiyon v%s (%s) recorded=%s | %d segment → %d assemble | "
          "system %s tok | toplam %s/%s tok"
          % (name, "+".join(m["scenario"]), m["pinned_version_no"], m["pinned_version_id"],
             m["version_recorded"], m["segments_count"], m["assemble_ops"],
             m["system_tokens"], m["total_prompt_tokens"], m["total_prompt_token_budget"]))
    print("  system_mutated=%d (hash_matches=%s) | content_in_system=%d | override görülen=%d/uygulanan=%d | "
          "order_violation=%d | drift=%d | unpublished=%d | cross_tenant=%d"
          % (m["system_mutated"], m["system_hash_matches"], m["content_in_system_role"],
             m["override_seen"], m["override_applied"], m["order_violation"],
             m["version_drift"], m["unpublished_injected"], m["cross_tenant"]))
    for ok, label in F:
        print("  %s %s" % ("✓" if ok else "✗", label))
    gate_ok = all(ok for ok, _ in F) and len(F) > 0

    exp = sample.get("expected", {})
    for k, v in exp.items():
        got = m.get(k)
        match = (got == v)
        print("  %s expected.%s == %r (got %r)" % ("✓" if match else "✗", k, v, got))
        gate_ok = gate_ok and match
    print("  kapı: %d/%d %s" % (sum(1 for ok, _ in F if ok), len(F),
                                 "🟢 GEÇTİ" if gate_ok else "🔴 ELENDİ"))
    if expect == "fail":
        return 0 if not gate_ok else 1
    return 0 if gate_ok else 1


# ─────────────────────────────────────────────────────────────────────────────
# validate
# ─────────────────────────────────────────────────────────────────────────────
def _check(results, ok, label):
    results.append((bool(ok), label))


def _scan_secrets(obj, path="root"):
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.startswith("$"):
                continue
            hits += _scan_secrets(v, "%s.%s" % (path, k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits += _scan_secrets(v, "%s[%d]" % (path, i))
    elif isinstance(obj, str):
        if _is_placeholder(obj):
            return hits
        if SECRET_RE.search(obj):
            hits.append((path, obj))
    return hits


def validate():
    spec = _load(SPEC_PATH)
    R = []

    _check(R, spec.get("wbs") == "3.2.3", "spec.wbs == 3.2.3")
    _check(R, spec.get("version"), "spec.version mevcut")

    # ── placement (orchestrator oturum aktörü, THINK, session_start pin)
    pl = spec.get("placement", {})
    _check(R, pl.get("in_orchestrator") is True and pl.get("in_session_actor") is True,
           "Prompt Manager orchestrator oturum aktöründe (SAD §6.2/§6.3)")
    _check(R, pl.get("turn_state") == "THINK", "THINK durumunda (LLM çağrısından önce)")
    _check(R, pl.get("event_driven") is True and pl.get("non_blocking") is True,
           "olay-tetikli + bloklamaz")
    _check(R, pl.get("pin_scope") == "session_start",
           "P1 versiyon çağrı/oturum başında sabitlenir (drift yok)")
    _check(R, pl.get("consumes_history_from"), "P9 history 3.2.1+3.2.2'den tüketilir")

    # ── prompt_model (P3/P5)
    pm = spec.get("prompt_model", {})
    _check(R, set(pm.get("roles", [])) == set(PRECEDENCE.keys()),
           "roller {system,policy,history,kb_context,user_turn}")
    _check(R, pm.get("precedence", {}) == PRECEDENCE,
           "P5 precedence system(0)→policy(1)→history(2)→kb_context(3)→user_turn(4)")
    _check(R, set(pm.get("untrusted_sources", [])) == UNTRUSTED_SOURCES,
           "P3 untrusted kaynaklar {caller, kb_retrieval}")
    _check(R, pm.get("system_source") == "prompt_registry",
           "P2 system segmenti registry kaynaklı (pin)")
    _check(R, isinstance(pm.get("system_token_budget"), (int, float)) and pm["system_token_budget"] > 0,
           "system_token_budget > 0")
    _check(R, pm.get("system_token_budget", 0) < pm.get("total_prompt_token_budget", 0),
           "system_token_budget < total_prompt_token_budget")

    # ── versioning (P1/P8)
    vs = spec.get("versioning", {})
    _check(R, vs.get("pin_required") is True, "P1 pin zorunlu")
    _check(R, vs.get("stable_within_call") is True and vs.get("no_mid_call_drift") is True,
           "P1 çağrı içi versiyon sabit (drift yok)")
    _check(R, vs.get("version_recorded") is True, "P8 kullanılan versiyon kaydedilir (FR-LLM-011)")

    # ── immutability (P2/P3/P4)
    im = spec.get("immutability", {})
    _check(R, im.get("system_byte_stable") is True,
           "P2 system segmenti bayt-bayt sabit (FR-LLM-006)")
    _check(R, im.get("trust_layering") is True and im.get("untrusted_in_system_forbidden") is True,
           "P3 trust layering: caller/KB system rolünde yasak")
    _check(R, im.get("override_structurally_fenced") is True,
           "P4 override yapısal çit (semantik → 3.3.1)")
    _check(R, im.get("no_fallback_to_user_content") is True,
           "P8 kullanıcı içeriğine fallback yok (fail-closed)")

    # ── assembly (P5/P6)
    asm = spec.get("assembly", {})
    _check(R, asm.get("ordered_by_precedence") is True and asm.get("system_first") is True,
           "P5 sıralı montaj + system önce")
    _check(R, asm.get("single_system_segment") is True, "P6 tam bir system segmenti")
    _check(R, asm.get("deterministic") is True, "P6 deterministik montaj")

    # ── kapılar
    g = spec.get("gates", {})
    _check(R, g.get("system_token_budget") == pm.get("system_token_budget"),
           "gates system_token_budget prompt_model ile tutarlı")
    _check(R, g.get("total_prompt_token_budget") == pm.get("total_prompt_token_budget"),
           "gates total_prompt_token_budget prompt_model ile tutarlı")
    _check(R, g.get("require_published") is True, "P8 require_published=true")
    _check(R, g.get("require_version_recorded") is True, "P8 require_version_recorded=true")
    _check(R, g.get("max_version_drift", -1) == 0, "P1 max_version_drift = 0")
    _check(R, g.get("max_system_mutated", -1) == 0, "P2 max_system_mutated = 0")
    _check(R, g.get("max_content_in_system_role", -1) == 0, "P3 max_content_in_system_role = 0")
    _check(R, g.get("max_override_applied", -1) == 0, "P4 max_override_applied = 0")
    _check(R, g.get("max_order_violation", -1) == 0, "P5 max_order_violation = 0")
    _check(R, g.get("max_duplicate_system", -1) == 0, "P6 max_duplicate_system = 0")
    _check(R, g.get("max_cross_tenant", -1) == 0, "P7 max_cross_tenant = 0")
    _check(R, g.get("max_unpublished_injected", -1) == 0, "P8 max_unpublished_injected = 0")

    # ── metrikler → observability
    me = spec.get("metrics", {})
    emitted = set(me.get("emitted", []))
    _check(R, {"prompt_assembly_total", "system_prompt_immutable_violations_total",
               "prompt_override_blocked_total"} <= emitted,
           "metrikler: assembly + immutable_violations + override_blocked yayılır")
    _check(R, len(me.get("maps_to_observability", {})) >= 1,
           "metrik observability'ye eşlenir (0.4.7)")

    # ── error taxonomy (P10)
    et = spec.get("error_taxonomy", {})
    mapping = et.get("mapping", {})
    _check(R, len(mapping) >= 4, "P10 hata eşlemesi (≥4)")
    _check(R, all(v in ERROR_TAXONOMY for v in mapping.values()),
           "P10 tüm hedefler API §11.6 ErrorTaxonomy'de")
    _check(R, mapping.get("invalid_segment") == "INVALID_REQUEST"
           and mapping.get("unpublished_version") == "INVALID_REQUEST"
           and mapping.get("registry_unavailable") == "UNAVAILABLE"
           and mapping.get("cross_tenant_access") == "AUTH"
           and mapping.get("region_mismatch") == "REGION_VIOLATION",
           "P10 bozuk-segment/yayımsız→INVALID, registry-down→UNAVAILABLE, cross-tenant→AUTH, bölge→REGION_VIOLATION")

    # ── residency + pii (P7/P8/P10)
    _check(R, spec.get("residency", {}).get("region_pin_required") is True, "P10 residency region pin")
    _check(R, spec.get("residency", {}).get("version_recorded_home_region") is True,
           "P8 versiyon home-region'da kaydedilir (FR-LLM-011/NFR 10.7)")
    _check(R, spec.get("pii", {}).get("raw_prompt_text_in_spec_forbidden") is True,
           "P10 ham prompt metni spec'te yasak")
    _check(R, spec.get("pii", {}).get("pii_value_in_spec_forbidden") is True,
           "P10 PII değeri spec'te yasak")
    _check(R, spec.get("pii", {}).get("card_otp_cleartext_in_system_forbidden") is True,
           "P2 kart/OTP düz-metin system'e yasak")

    # ── invariant kataloğu
    inv_ids = [i.get("id") for i in spec.get("invariants", [])]
    _check(R, len(inv_ids) == len(set(inv_ids)) and len(inv_ids) >= 10,
           "invariant kataloğu ≥10 + tekil ID")
    _check(R, all(i.get("trace") for i in spec.get("invariants", [])),
           "her invariant trace taşır")

    # ── literal sır taraması (spec + config)
    hits = _scan_secrets(spec)
    if os.path.exists(PROFILES_CFG):
        hits += _scan_secrets(_load(PROFILES_CFG))
    _check(R, not hits, "P10 literal sır yok (spec+config)")

    # ── config profilleri doğrulaması
    if os.path.exists(PROFILES_CFG):
        cfg = _load(PROFILES_CFG)
        profs = cfg.get("profiles", [])
        _check(R, len(profs) >= 2, "config ≥2 prompt profili")
        names = [p.get("name") for p in profs]
        _check(R, len(names) == len(set(names)), "config profil isimleri benzersiz")
        for p in profs:
            _check(R, bool(p.get("region")), "P10 config %s bölge pini var" % p.get("name"))
            _check(R, p.get("system_token_budget", 0) > 0,
                   "config %s system_token_budget > 0" % p.get("name"))
            _check(R, p.get("system_token_budget", 1e9) < p.get("total_prompt_token_budget", 0),
                   "config %s system_token_budget < total_prompt_token_budget" % p.get("name"))

    passed = sum(1 for ok, _ in R if ok)
    total = len(R)
    for ok, label in R:
        if not ok:
            print("  ✗ %s" % label)
    print("validate: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


# ─────────────────────────────────────────────────────────────────────────────
# selftest yardımcıları
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_PARAMS = {
    "system_token_budget": 1200, "total_prompt_token_budget": 6000,
    "tenant_id": "t-self", "agent_id": "a-self",
}


def _pin(t, vid="pv-1", vno=1, published=True, shash="sys-h-1", stokens=400, tenant=None, agent=None):
    ev = {"kind": "pin", "version_id": vid, "version_no": vno, "published": published,
          "system_hash": shash, "system_tokens": stokens, "t": t}
    if tenant:
        ev["tenant_id"] = tenant
    if agent:
        ev["agent_id"] = agent
    return ev


def _seg(t, role="user_turn", tokens=80, override=False, sensitive=0, source=None, tenant=None):
    ev = {"kind": "segment", "role": role, "t": t, "approx_tokens": tokens}
    if override:
        ev["contains_override"] = True
    if sensitive:
        ev["sensitive_tokens"] = sensitive
    if source:
        ev["source"] = source
    if tenant:
        ev["tenant_id"] = tenant
    return ev


def _asm(t):
    return {"kind": "assemble", "t": t}


def _end(t, reason="normal"):
    return {"kind": "end", "t": t, "reason": reason}


def _run(events, params=None, **pol_over):
    pol = {"immutable_system": True, "trust_layering": True, "fence_untrusted": True,
           "ordered_assembly": True, "system_first": True, "published_only": True,
           "stable_version": True, "record_version": True, "tenant_isolation": True,
           "order_guard": True}
    pol.update(pol_over)
    return simulate({"events": events}, params or DEFAULT_PARAMS, pol)


def _basic_call(override=False, sensitive=0):
    return [_pin(0), _seg(100, "policy", 60), _seg(200, "history", 200),
            _seg(300, "kb_context", 150, override=override, sensitive=sensitive),
            _seg(400, "user_turn", 80, override=override), _asm(500), _end(600)]


def selftest():
    spec = _load(SPEC_PATH)
    gates = spec.get("gates", {})
    cases = []

    def case(ok, label):
        cases.append((bool(ok), label))

    # 0) validate iyi spec+config'te geçer
    case(_validate_obj(_load(SPEC_PATH)) == 0, "validate iyi spec+config'te 0 döndürür")

    # ── happy: versiyon sabit + system değişmez + katmanlı (P1–P8) ────────────────
    mh = _run(_basic_call())
    case(mh["pinned"] and mh["version_recorded"] and mh["version_drift"] == 0, "happy: versiyon sabit + kayıtlı (P1)")
    case(mh["system_mutated"] == 0 and mh["system_hash_matches"], "happy: system değişmez (P2)")
    case(mh["content_in_system_role"] == 0, "happy: caller/KB system rolünde değil (P3)")
    case(mh["order_violation"] == 0, "happy: yetki sırası korunur (P5)")
    case(all(ok for ok, _ in evaluate(gates, mh)), "happy tüm kapıları geçer")

    # ── override-fenced: kullanıcı/KB override görülür ama uygulanmaz (P4) ─────────
    mo = _run(_basic_call(override=True))
    case(mo["override_seen"] >= 1 and mo["override_applied"] == 0,
         "override-fenced: override görüldü ama system'e uygulanmadı (P4)")
    case(mo["system_mutated"] == 0 and mo["system_hash_matches"], "override-fenced: system yine değişmez (P2)")
    case(all(ok for ok, _ in evaluate(gates, mo)), "override-fenced tüm kapıları geçer")

    # ── determinizm ───────────────────────────────────────────────────────────────
    case(_run(_basic_call(override=True)) == mo, "determinizm: aynı olay-akışı birebir aynı metrik (random yok)")

    # ── sensitive: kart/OTP işareti düşük-güven segmentte → system'e girmez (P2) ───
    ms = _run(_basic_call(sensitive=2))
    case(ms["sensitive_seen"] == 2 and ms["sensitive_in_system"] == 0,
         "sensitive: kart/OTP düşük-güven segmentte, system'e 0 (P2)")
    case(all(ok for ok, _ in evaluate(gates, ms)), "sensitive tüm kapıları geçer")

    # ── degraded-1: immutable_system kapalı → system gövdesi saptı (P2 eler) ───────
    d1 = _run(_basic_call(override=True), immutable_system=False)
    case(d1["system_mutated"] >= 1 and not d1["system_hash_matches"],
         "degraded(mutated): caller/KB system'e birleşti (FR-LLM-006 ihlali)")
    case(d1["content_in_system_role"] >= 1 and d1["override_applied"] >= 1,
         "degraded(mutated): override system'e uygulandı")
    case(not all(ok for ok, _ in evaluate(gates, d1)), "degraded(mutated) P2/P3/P4 eler")

    # ── degraded-2: trust_layering kapalı → düşük-güven system rolünde (P3 eler) ───
    d2 = _run(_basic_call(), trust_layering=False)
    case(d2["content_in_system_role"] >= 1 and d2["system_mutated"] == 0,
         "degraded(no-layering): caller/KB system rolünde ama gövde sabit (P3 izole)")
    case(not all(ok for ok, _ in evaluate(gates, d2)), "degraded(no-layering) P3 eler")

    # ── degraded-3: fence kapalı → override uygulanır (P4 eler, P2/P3 sağlam) ──────
    d3 = _run(_basic_call(override=True), fence_untrusted=False)
    case(d3["override_applied"] >= 1 and d3["system_mutated"] == 0 and d3["content_in_system_role"] == 0,
         "degraded(no-fence): override uygulandı ama gövde+rol sağlam (P4 izole)")
    case(not all(ok for ok, _ in evaluate(gates, d3)), "degraded(no-fence) P4 eler")

    # ── degraded-4: system_first kapalı → yetki inversiyonu (P5 eler) ─────────────
    d4 = _run(_basic_call(), system_first=False)
    case(d4["order_violation"] >= 1, "degraded(no-system-first): system sona kondu (yetki inversiyonu)")
    case(not all(ok for ok, _ in evaluate(gates, d4)), "degraded(no-system-first) P5 eler")

    # ── degraded-5: yayımlanmamış versiyon enjekte (P8 eler) ──────────────────────
    d5 = _run([_pin(0, published=False), _seg(100, "user_turn", 80), _asm(200), _end(300)],
              published_only=False)
    case(d5["unpublished_injected"] >= 1, "degraded(unpublished): yayımlanmamış versiyon enjekte edildi")
    case(not all(ok for ok, _ in evaluate(gates, d5)), "degraded(unpublished) P8 eler")

    # ── degraded-6: versiyon kaydedilmedi → FR-LLM-011 ihlali (P8 eler) ───────────
    d6 = _run(_basic_call(), record_version=False)
    case(d6["version_recorded"] is False, "degraded(no-record): kullanılan versiyon kaydedilmedi")
    case(not all(ok for ok, _ in evaluate(gates, d6)), "degraded(no-record) P8 eler")

    # ── degraded-7: çağrı-içi versiyon drift (P1 eler) ────────────────────────────
    d7 = _run([_pin(0, vid="pv-1", vno=1), _seg(100, "user_turn", 80), _asm(200),
               _pin(300, vid="pv-2", vno=2, shash="sys-h-2"), _asm(400), _end(500)],
              stable_version=False)
    case(d7["version_drift"] >= 1, "degraded(drift): çağrı içi farklı versiyona repin")
    case(not all(ok for ok, _ in evaluate(gates, d7)), "degraded(drift) P1 eler")

    # ── degraded-8: cross-tenant prompt çekme (P7 eler) ───────────────────────────
    d8 = _run([_pin(0), _seg(100, "user_turn", 80, tenant="t-other"), _asm(200), _end(300)],
              tenant_isolation=False)
    case(d8["cross_tenant"] >= 1, "degraded(cross-tenant): yabancı tenant segmenti sızdı")
    case(not all(ok for ok, _ in evaluate(gates, d8)), "degraded(cross-tenant) P7 eler")

    # ── geçersiz olay reddi (P10) ─────────────────────────────────────────────────
    case(_raises(lambda: _run([_pin(0), {"kind": "segment", "role": "system", "t": 100,
                                          "approx_tokens": 50}, _asm(200), _end(300)])),
         "P10 içerik segmenti role=system → reddedilir")
    case(_raises(lambda: _run([_pin(0), _seg(100, "robot", 50), _asm(200), _end(300)])),
         "P10 geçersiz segment rolü → reddedilir")
    case(_raises(lambda: _run([_seg(0, "user_turn", 80), _asm(100), _end(200)])),
         "P10 pin'siz assemble → reddedilir (fail-closed)")
    case(_raises(lambda: _run([_pin(0, published=False), _asm(100), _end(200)])),
         "P10 yayımlanmamış versiyon (published_only) → reddedilir")
    case(_raises(lambda: _run([_pin(0), _pin(100, vid="pv-2", shash="sys-h-2"), _asm(200), _end(300)])),
         "P10 çağrı-içi repin (stable_version) → reddedilir")
    case(_raises(lambda: _run([_pin(0), _seg(100, "user_turn", 80)])),
         "P10 'end' olmadan → reddedilir")
    case(_raises(lambda: _run([_pin(1000), _seg(0, "user_turn", 80), _asm(2000), _end(3000)])),
         "P10 out-of-order → reddedilir")
    case(_raises(lambda: _run([_pin(0), {"kind": "nope", "t": 1}, _end(2000)])),
         "P10 bilinmeyen olay → reddedilir")
    case(_raises(lambda: simulate({"events": []}, DEFAULT_PARAMS, {})), "P10 boş olay akışı → reddedilir")
    case(_raises(lambda: _run([_pin(0), _seg(100, "user_turn", 80, tenant="t-other"), _asm(200), _end(300)])),
         "P10 cross-tenant (izolasyon açık) → reddedilir")

    # ── validate negatif kapılar ─────────────────────────────────────────────────
    s = json.loads(json.dumps(spec)); s["prompt_model"]["system_token_budget"] = 0
    case(_validate_obj(s) != 0, "system_token_budget=0 → validate eler")
    s = json.loads(json.dumps(spec)); s["prompt_model"]["system_token_budget"] = s["prompt_model"]["total_prompt_token_budget"] + 1
    case(_validate_obj(s) != 0, "system_token_budget ≥ total → validate eler")
    s = json.loads(json.dumps(spec)); s["immutability"]["system_byte_stable"] = False
    case(_validate_obj(s) != 0, "P2 system_byte_stable=false → validate eler")
    s = json.loads(json.dumps(spec)); s["immutability"]["untrusted_in_system_forbidden"] = False
    case(_validate_obj(s) != 0, "P3 untrusted_in_system_forbidden=false → validate eler")
    s = json.loads(json.dumps(spec)); s["immutability"]["override_structurally_fenced"] = False
    case(_validate_obj(s) != 0, "P4 override_structurally_fenced=false → validate eler")
    s = json.loads(json.dumps(spec)); s["assembly"]["system_first"] = False
    case(_validate_obj(s) != 0, "P5 system_first=false → validate eler")
    s = json.loads(json.dumps(spec)); s["versioning"]["version_recorded"] = False
    case(_validate_obj(s) != 0, "P8 version_recorded=false → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_system_mutated"] = 1
    case(_validate_obj(s) != 0, "P2 max_system_mutated>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_content_in_system_role"] = 1
    case(_validate_obj(s) != 0, "P3 max_content_in_system_role>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_override_applied"] = 1
    case(_validate_obj(s) != 0, "P4 max_override_applied>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_version_drift"] = 1
    case(_validate_obj(s) != 0, "P1 max_version_drift>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_cross_tenant"] = 1
    case(_validate_obj(s) != 0, "P7 max_cross_tenant>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["require_published"] = False
    case(_validate_obj(s) != 0, "P8 require_published=false → validate eler")
    s = json.loads(json.dumps(spec)); s["error_taxonomy"]["mapping"]["x"] = "NOPE"
    case(_validate_obj(s) != 0, "P10 taksonomi-dışı → validate eler")
    s = json.loads(json.dumps(spec)); s["pii"]["pii_value_in_spec_forbidden"] = False
    case(_validate_obj(s) != 0, "P10 pii-değer-yasak kapalı → validate eler")
    s = json.loads(json.dumps(spec)); s["prompt_model"]["secret"] = "api_key: AKIAIOSFODNN7EXAMPLE"
    case(_validate_obj(s) != 0, "P10 literal secret → validate eler")

    passed = sum(1 for ok, _ in cases if ok)
    total = len(cases)
    for ok, label in cases:
        print("  %s %s" % ("✓" if ok else "✗", label))
    print("selftest: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


def _raises(fn):
    try:
        fn()
        return False
    except PromptError:
        return True


def _validate_obj(spec_obj):
    import io
    import contextlib
    tmp = os.path.join(HERE, ".._tmp_spec.json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(spec_obj, f)
    global SPEC_PATH
    orig = SPEC_PATH
    SPEC_PATH = tmp
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            rc = validate()
    finally:
        SPEC_PATH = orig
        os.remove(tmp)
    return rc


def schema():
    print("""prompt-manager-spec.json beklenen şekli (WBS 3.2.3):
  wbs, version, phase, trace{fr,nfr,sad,adr,api,srs,rtm,db,brd,consumes,observability}
  placement{in_orchestrator=true, in_session_actor=true, turn_state=THINK, event_driven=true,
            non_blocking=true, pin_scope=session_start, consumes_history_from(3.2.1+3.2.2)}  (P1,P9)
  prompt_model{roles[system,policy,history,kb_context,user_turn], precedence{...},
               untrusted_sources[caller,kb_retrieval], system_source=prompt_registry,
               system_token_budget>0, total_prompt_token_budget(>system)}                   (P2-P5)
  versioning{pin_required=true, stable_within_call=true, version_recorded=true,
             no_mid_call_drift=true}                                                          (P1,P8)
  immutability{system_byte_stable=true, trust_layering=true, untrusted_in_system_forbidden=true,
               override_structurally_fenced=true, no_fallback_to_user_content=true}          (P2-P4)
  assembly{ordered_by_precedence=true, system_first=true, single_system_segment=true,
           deterministic=true}                                                                (P5,P6)
  gates{system_token_budget, total_prompt_token_budget, require_published=true,
        require_version_recorded=true, max_version_drift=0, max_system_mutated=0,
        max_content_in_system_role=0, max_override_applied=0, max_order_violation=0,
        max_duplicate_system=0, max_cross_tenant=0, max_unpublished_injected=0}              (P1-P8)
  metrics{emitted[], maps_to_observability{}}
  error_taxonomy{mapping→API §11.6}                                                          (P10)
  residency{region_pin_required=true, version_recorded_home_region=true}                     (P8,P10)
  pii{raw_prompt_text_in_spec_forbidden, pii_value_in_spec_forbidden,
      card_otp_cleartext_in_system_forbidden, durable_redaction_state=pending}              (P2,P10)
  invariants[≥10]{id, desc, trace}

config/prompt-manager-profiles.json: profiles[]{name, deployment, system_token_budget,
  total_prompt_token_budget, region}

simulate sample: {name, profile | profile_obj, tenant_id?, agent_id?, expect, expected?{metrik:değer},
  policy?{immutable_system, trust_layering, fence_untrusted, ordered_assembly, system_first,
  published_only, stable_version, record_version, tenant_isolation},
  events[{kind:'pin', version_id, version_no, published, system_hash, system_tokens, t} |
         {kind:'segment', role, t, approx_tokens, content_hash?, contains_override?,
          sensitive_tokens?, source?} | {kind:'assemble', t} | {kind:'end', t, reason}]}
  — pin → (segment*) → assemble → ... → end; son olay 'end' olmalı

komutlar: validate | simulate <sample.json> | selftest | schema""")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if cmd == "validate":
        return validate()
    if cmd == "simulate":
        if len(sys.argv) < 3:
            print("kullanım: prompt_manager_probe.py simulate <sample.json>")
            return 2
        return simulate_cmd(sys.argv[2])
    if cmd == "selftest":
        return selftest()
    if cmd == "schema":
        return schema()
    print("bilinmeyen komut: %s (validate|simulate|selftest|schema)" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main())
