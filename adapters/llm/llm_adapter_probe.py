#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
llm_adapter_probe.py — WBS 4.2.4 LLM adapter #1 + #2 (streaming token / tool call)

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only statik + davranış kapısı. `runtime/`,
`telephony/` ve `adapters/tts/` modül disipliniyle aynı; burada iki SOMUT LlmAdapter implementasyonunu
(≥2/kategori — FR-LLM-001) ortak SPI (SAD §8.1 / API §11.4) arkasına bağlayan DETERMİNİSTİK bir
referans adapter sürücüsü (olay-tetikli, sanal saat, random YOK; gerçek LLM çıkarımı YOK — sağlayıcı
gecikme profili + akış MODELİ). Görev başlığındaki iki boyut:
  • STREAMING TOKEN: complete() ilk token'ı akış-önce (no full buffering) düşük gecikmeyle döndürür;
                     first-token P95 ≤ SAD §20 (genel 400 ms) + full_buffered=0 (P1 — FR-LLM-004/FR-RES-002)
                     + token-arası süreklilik (token_stall=0 — P3, FR-LLM-004/FR-RES-009).
  • TOOL CALL:       kritik işlem bekleyen tur schema-doğrulamalı ToolCallChunk ile yapılır, serbest
                     metinle DEĞİL; unhandled_tool=0 (P2 — FR-LLM-008).
Ek (Must): model tiering (P4 — FR-LLM-013; küçük-tier first-token sıkı kapı), no-train+no-log+residency
(P6 — FR-LLM-012/FR-KB-010/NFR 10.7), system prompt değişmezliği (P7 — FR-LLM-006), metering + model/
versiyon kaydı + hata normalizasyonu (P8 — FR-BIL-002/FR-LLM-011/FR-TOOL-008).

KAPSAM AYRIMI: model ROUTING/tiering MOTORU (küçük↔büyük seçim) → 5.1/5.2/5.3 (bu motor ≥2 tier SUNUMUNU
+ küçük-tier first-token'ı DOĞRULAR, router KARARINI değil); semantic cache → 5.4; prompt-injection →
3.3.1; policy engine → 3.3.2; LLM fallback ANAHTARLAMA → 4.3.3 (bu motor ≥2 SPI-uyum + ErrorTaxonomy
varlığını doğrular); ortak yetenekler (timeout/retry/breaker/health/pool) → 4.1.2/4.1.6 (tüketilir);
metering motoru → 4.1.3; residency/retention → 4.1.4; sağlayıcı SEÇİMİ → 0.2.6/0.3.x.

Komutlar:
  validate              llm-adapter-spec.json'ı invariant'lara (P1–P10) + config sağlayıcı/profillerine doğrular.
  simulate <sample>     Deterministik LlmAdapter — olay-akışı (request + end) → streaming/tool-call/stall/
                        tiering/metering metrikleri → HARD kapılar (P1–P8) → çıkış kodu.
  selftest              İyi/kötü spec+sample ile kapıların doğru tetiklendiğini kanıtlar.
  schema                Beklenen spec şeklini özetler.

Sunucu/credential GEREKMEZ. simulate gerçek LLM yerine sağlayıcı gecikme profili (config providers) +
akış MODELİ kullanır (canlı sistemde Go/Rust async runtime + gerçek LlmAdapter, ADR-003/SAD §6.3/§8.1).
Ham PROMPT/mesaj METNİ, model çıktısı METNİ veya PII DEĞERİ YOK — yalnız sağlayıcı kimliği + gecikme/
akış/token SAYILARI + model/tier/tool kimlikleri + sanal zaman.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "llm-adapter-spec.json")
PROFILES_CFG = os.path.join(HERE, "config", "llm-adapter-profiles.json")

ERROR_TAXONOMY = {
    "TIMEOUT", "RATE_LIMITED", "UNAVAILABLE", "AUTH",
    "INVALID_REQUEST", "CONTENT_FILTERED", "QUOTA_EXCEEDED", "REGION_VIOLATION",
}
SECRET_RE = re.compile(
    r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer)\b\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}"
)
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")

REQUIRED_FEATURES = {"streaming", "tool_call"}
TIERS = {"small", "big"}
ALLOWED_RETENTION = {"NONE", "EPHEMERAL"}
END_REASONS = {"normal", "error"}


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_placeholder(v):
    return isinstance(v, str) and PLACEHOLDER_RE.match(v) is not None


def _percentile(values, pct):
    """Lineer-interpolasyonlu yüzdelik (media_latency / tts_eval / latency_budget probe ile birebir)."""
    if not values:
        return None
    xs = sorted(values)
    if len(xs) == 1:
        return float(xs[0])
    rank = (pct / 100.0) * (len(xs) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(xs) - 1)
    frac = rank - lo
    return float(xs[lo] + (xs[hi] - xs[lo]) * frac)


class LlmError(Exception):
    """Geçersiz/desteklenmeyen olay veya yetki/izolasyon ihlali — sessizce kabul yok, reddet (P10)."""


# ─────────────────────────────────────────────────────────────────────────────
# LlmAdapter referans sürücüsü (deterministik)
# ─────────────────────────────────────────────────────────────────────────────
class LlmAdapterRuntime:
    """SAD §8.1 / API §11.4 LlmAdapter sürücüsü. Olay-akışını işler:
        request → end
    Her request (complete çağrısı) için sağlayıcı gecikme PROFİLİNDEN (config providers) streaming
    first-token, token-arası süreklilik (stall), tool-call işleme, model tier first-token, no-train/
    no-log/residency uygunluğu, system prompt değişmezliği ve usage metering DETERMİNİSTİK hesaplanır
    (random YOK; sanal saat = event.t).

    Olaylar:
      {kind:'request', req_id, model, model_version, tier∈{small,big}, t, input_tokens, output_tokens,
                       expects_tool?, tool_call?, system_preserved?, no_train?, region_pinned?,
                       data_retention?, provider?, tenant_id?}
      {kind:'end',     req_id, t, reason∈{normal,error}, error_taxonomy?}
    """

    def __init__(self, provider, policy, gates, tenant_id="t-self"):
        self.pv = provider
        self.pol = policy
        self.g = gates
        self.tenant_id = tenant_id

        self.requests = {}              # req_id -> state
        self._last_t = None

        # ölçüm dizileri
        self.first_token_ms = []        # genel first-token (P1)
        self.small_tier_first_token_ms = []   # küçük-tier first-token (P4)
        self.inter_token_ms = []        # token-arası boşluk gözlemleri (P3)

        # sayaçlar / metrikler
        self.requests_total = 0
        self.full_buffered = 0          # akış-önce ihlali: ilk token tüm yanıt bitince (P1)
        self.token_stall = 0            # token-arası boşluk eşik üstü (P3)
        self.critical_total = 0         # kritik işlem bekleyen tur sayısı
        self.tool_calls_ok = 0          # schema-doğrulamalı tool-call (P2)
        self.unhandled_tool = 0         # kritik tur serbest metinle bırakıldı (P2 ihlali)
        self.tool_call_total = 0        # toplam tool-call (soft oran)
        self.tiers_seen = set()         # küçük/büyük tier kapsanması (P4)
        self.small_tier_count = 0       # küçük-tier tur sayısı (SR-DEN-005 raporu)
        self.no_train_violation = 0     # noTrain false veya retention no-log dışı (P6)
        self.region_violation = 0       # bölgesel pin yok (P6)
        self.system_prompt_mutation = 0  # system mesajı değiştirildi (P7)
        self.cross_tenant = 0
        self.usage_records = 0          # UsageRecord sayısı (P8/FR-BIL-002)
        self.model_version_recorded = 0  # model+version kaydedildi (P8/FR-LLM-011)
        self.input_tokens_total = 0
        self.output_tokens_total = 0
        self.errors_seen = 0
        self.errors_normalized = 0
        self.ended = 0

    def _check_time(self, t):
        if not isinstance(t, (int, float)):
            raise LlmError("zaman damgası sayısal değil → INVALID_REQUEST")
        if self._last_t is not None and t < self._last_t:
            if self.pol.get("order_guard", True):
                raise LlmError("out-of-order olay (t geriye) reddedildi → INVALID_REQUEST")
        self._last_t = max(self._last_t if self._last_t is not None else t, t)

    def _check_scope(self, ev):
        tt = ev.get("tenant_id", self.tenant_id)
        if tt != self.tenant_id:
            self.cross_tenant += 1
            if self.pol.get("tenant_isolation", True):
                raise LlmError("cross-tenant erişim reddedildi → AUTH")

    # ── request: complete() çağrısı (P1/P2/P3/P4/P6/P7/P8) ────────────────────
    def request(self, ev):
        self._check_time(ev.get("t"))
        self._check_scope(ev)
        req_id = ev.get("req_id")
        if not isinstance(req_id, str) or not req_id:
            raise LlmError("req_id yok/boş → INVALID_REQUEST")
        if req_id in self.requests:
            raise LlmError("req_id tekrar kullanıldı → INVALID_REQUEST")
        model = ev.get("model")
        if not isinstance(model, str) or not model:
            raise LlmError("model yok/boş → INVALID_REQUEST")
        tier = ev.get("tier", "big")
        if tier not in TIERS:
            raise LlmError("geçersiz tier: %r → INVALID_REQUEST" % tier)
        in_tok = ev.get("input_tokens", 0)
        out_tok = ev.get("output_tokens", 0)
        if not isinstance(in_tok, (int, float)) or in_tok < 0 \
                or not isinstance(out_tok, (int, float)) or out_tok < 0:
            raise LlmError("input/output_tokens sayısal/≥0 değil → INVALID_REQUEST")

        self.requests_total += 1
        self.tiers_seen.add(tier)
        if tier == "small":
            self.small_tier_count += 1
        self.input_tokens_total += int(in_tok)
        self.output_tokens_total += int(out_tok)

        # ── P8: usage metering (FR-BIL-002) + model/versiyon kaydı (FR-LLM-011)
        if self.pol.get("meter", True):
            self.usage_records += 1
        if self.pol.get("record_model_version", True) and ev.get("model_version"):
            self.model_version_recorded += 1

        # ── P6: no-train + no-log + residency
        no_train = ev.get("no_train", True) and self.pol.get("no_train", True)
        retention = ev.get("data_retention", self.pv.get("data_retention", "NONE"))
        if (not no_train) or (retention not in ALLOWED_RETENTION):
            self.no_train_violation += 1
        region_pinned = ev.get("region_pinned", True) and self.pol.get("region_pin", True)
        if not region_pinned:
            self.region_violation += 1

        # ── P7: system prompt değişmezliği (FR-LLM-006)
        system_preserved = ev.get("system_preserved", True) and self.pol.get("system_immutable", True)
        if not system_preserved:
            self.system_prompt_mutation += 1

        # ── P2: tool-call (kritik işlem → schema-doğrulamalı tool-call, serbest metin değil)
        expects_tool = bool(ev.get("expects_tool", False))
        emitted_tool = bool(ev.get("tool_call", False)) and self.pol.get("emit_tool_call", True)
        if emitted_tool:
            self.tool_call_total += 1
        if expects_tool:
            self.critical_total += 1
            if emitted_tool:
                self.tool_calls_ok += 1
            else:
                self.unhandled_tool += 1

        # ── P1: first-token (streaming vs full-buffer) + tier
        if self.pol.get("streaming", True):
            if tier == "small":
                ft = float(self.pv.get("first_token_small_ms", 150))
            else:
                ft = float(self.pv.get("first_token_ms", 280))
        else:
            # BOZUK: tüm yanıt tamponlanır → ilk token ancak üretim bitince (akış-önce ihlali, FR-RES-002)
            ft = float(out_tok) * float(self.pv.get("per_token_gen_ms", 9))
            self.full_buffered += 1
        self.first_token_ms.append(ft)
        if tier == "small":
            self.small_tier_first_token_ms.append(ft)

        # ── P3: token-arası süreklilik (stall yok)
        if self.pol.get("continuity", True):
            itl = float(self.pv.get("inter_token_ms", 32))
        else:
            # BOZUK: token-arası boşluk eşiği aşar → stall → downstream TTS ölü hava
            itl = float(self.pv.get("inter_token_ms_degraded", 260))
        self.inter_token_ms.append(itl)
        if itl > float(self.g.get("stall_threshold_ms", 120)):
            self.token_stall += 1

        self.requests[req_id] = {"start_t": ev.get("t"), "model": model, "tier": tier, "ended": False}

    def end(self, ev):
        req_id = ev.get("req_id")
        req = self.requests.get(req_id)
        if req is None:
            raise LlmError("bilinmeyen req_id end → INVALID_REQUEST")
        if req["ended"]:
            raise LlmError("akış zaten bitti → INVALID_REQUEST")
        reason = ev.get("reason", "normal")
        if reason not in END_REASONS:
            raise LlmError("geçersiz bitiş nedeni: %r → INVALID_REQUEST" % reason)
        if reason == "error":
            self.errors_seen += 1
            tax = ev.get("error_taxonomy")
            if self.pol.get("normalize_errors", True) and tax in ERROR_TAXONOMY:
                self.errors_normalized += 1
        req["ended"] = True
        self.ended += 1

    def metrics(self):
        scenario = []
        if self.first_token_ms:
            scenario.append("streaming" if self.full_buffered == 0 else "full-buffered")
        if self.critical_total:
            scenario.append("tool-call" if self.unhandled_tool == 0 else "free-text-critical")
        if self.token_stall:
            scenario.append("token-stall")
        if len(self.tiers_seen) >= 2:
            scenario.append("multi-tier")
        if self.no_train_violation or self.region_violation:
            scenario.append("residency-violation")
        if self.errors_seen:
            scenario.append("provider-error")
        if not scenario:
            scenario.append("empty")
        ft = self.first_token_ms
        ratio = (self.tool_calls_ok / self.critical_total) if self.critical_total else None
        return {
            "provider_id": self.pv.get("provider_id"),
            "requests_total": self.requests_total,
            "first_token_p95_ms": _percentile(ft, 95),
            "first_token_p50_ms": _percentile(ft, 50),
            "first_token_max_ms": max(ft) if ft else None,
            "full_buffered": self.full_buffered,
            "small_tier_first_token_p95_ms": _percentile(self.small_tier_first_token_ms, 95),
            "small_tier_count": self.small_tier_count,
            "tiers_seen": sorted(self.tiers_seen),
            "small_tier_share": (self.small_tier_count / self.requests_total) if self.requests_total else None,
            "inter_token_p95_ms": _percentile(self.inter_token_ms, 95),
            "token_stall": self.token_stall,
            "critical_total": self.critical_total,
            "tool_calls_ok": self.tool_calls_ok,
            "unhandled_tool": self.unhandled_tool,
            "tool_call_total": self.tool_call_total,
            "tool_call_ratio": ratio,
            "no_train_violation": self.no_train_violation,
            "region_violation": self.region_violation,
            "system_prompt_mutation": self.system_prompt_mutation,
            "cross_tenant": self.cross_tenant,
            "usage_records": self.usage_records,
            "model_version_recorded": self.model_version_recorded,
            "input_tokens_total": self.input_tokens_total,
            "output_tokens_total": self.output_tokens_total,
            "errors_seen": self.errors_seen,
            "errors_normalized": self.errors_normalized,
            "scenario": scenario,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Tam simülasyon (bir sample)
# ─────────────────────────────────────────────────────────────────────────────
def simulate(sample, provider, policy, gates):
    events = sample.get("events")
    if events is None or not isinstance(events, list) or not events:
        raise LlmError("boş/geçersiz olay akışı → INVALID_REQUEST")
    rt = LlmAdapterRuntime(provider, policy, gates,
                           tenant_id=sample.get("tenant_id", "t-self"))
    saw_end = False
    for ev in events:
        if not isinstance(ev, dict):
            raise LlmError("olay sözlük değil → INVALID_REQUEST")
        kind = ev.get("kind")
        if kind == "request":
            rt.request(ev)
        elif kind == "end":
            rt.end(ev)
            saw_end = True
        else:
            raise LlmError("bilinmeyen olay tipi: %r → INVALID_REQUEST" % kind)
    if not saw_end:
        raise LlmError("olay akışında 'end' yok → INVALID_REQUEST")
    return rt.metrics()


def evaluate(gates, m):
    """Metrikleri HARD kapılara (P1–P8 davranışsal) karşı değerlendirir. Döner findings[(ok, label)]."""
    F = []

    # ── P1: streaming first-token + akış-önce
    ft95 = m.get("first_token_p95_ms")
    ft_ok = (ft95 is None or ft95 <= gates.get("first_token_p95_ms", 400)) \
        and m.get("full_buffered", 0) <= gates.get("max_full_buffered", 0)
    F.append((ft_ok,
              "P1 streaming: first_token P95 %s ≤ %d ms + full_buffered %d ≤ %d (akış-önce; FR-LLM-004/SAD §20)"
              % (_fmt(ft95), gates.get("first_token_p95_ms", 400),
                 m.get("full_buffered", 0), gates.get("max_full_buffered", 0))))

    # ── P2: tool-call (kritik işlemde schema-doğrulamalı tool-call)
    F.append((m.get("unhandled_tool", 0) <= gates.get("max_unhandled_tool", 0),
              "P2 tool-call: unhandled_tool %d ≤ %d (kritik %d → tool-call %d; FR-LLM-008)"
              % (m.get("unhandled_tool", 0), gates.get("max_unhandled_tool", 0),
                 m.get("critical_total", 0), m.get("tool_calls_ok", 0))))

    # ── P3: token-arası süreklilik / stall yok
    F.append((m.get("token_stall", 0) <= gates.get("max_token_stall", 0),
              "P3 süreklilik: token_stall %d ≤ %d (inter-token P95 %s ≤ %d ms; FR-LLM-004/FR-RES-009)"
              % (m.get("token_stall", 0), gates.get("max_token_stall", 0),
                 _fmt(m.get("inter_token_p95_ms")), gates.get("stall_threshold_ms", 120))))

    # ── P4: model tiering (küçük-tier first-token sıkı kapı)
    st95 = m.get("small_tier_first_token_p95_ms")
    F.append((st95 is None or st95 <= gates.get("small_tier_first_token_p95_ms", 200),
              "P4 tiering: küçük-tier first_token P95 %s ≤ %d ms (%d küçük-tur, share %s; FR-LLM-013/SR-DEN-005)"
              % (_fmt(st95), gates.get("small_tier_first_token_p95_ms", 200),
                 m.get("small_tier_count", 0), _fmt_share(m.get("small_tier_share")))))

    # ── P6: no-train + no-log + residency
    F.append((m.get("no_train_violation", 0) <= 0 and m.get("region_violation", 0) <= gates.get("max_region_violation", 0),
              "P6 residency: no_train_violation %d + region_violation %d ≤ %d (noTrain+NONE/EPHEMERAL+pin; FR-LLM-012/FR-KB-010/NFR 10.7)"
              % (m.get("no_train_violation", 0), m.get("region_violation", 0),
                 gates.get("max_region_violation", 0))))

    # ── P7: system prompt değişmezliği
    F.append((m.get("system_prompt_mutation", 0) <= gates.get("max_system_prompt_mutation", 0),
              "P7 system prompt: mutation %d ≤ %d (system mesajı user/KB ile değiştirilmedi; FR-LLM-006)"
              % (m.get("system_prompt_mutation", 0), gates.get("max_system_prompt_mutation", 0))))

    # ── P8: metering + model/versiyon kaydı + hata normalizasyonu
    meter_ok = (not gates.get("require_metering", True)) \
        or (m.get("usage_records", 0) == m.get("requests_total", 0))
    mv_ok = (not gates.get("require_model_version_recorded", True)) \
        or (m.get("model_version_recorded", 0) == m.get("requests_total", 0))
    err_ok = (not gates.get("require_error_normalized", True)) \
        or (m.get("errors_normalized", 0) == m.get("errors_seen", 0))
    ten_ok = m.get("cross_tenant", 0) <= gates.get("max_cross_tenant", 0)
    F.append((meter_ok and mv_ok and err_ok and ten_ok,
              "P8 metering+model/ver+taksonomi: usage %d/%d, model_ver %d/%d, err_norm %d/%d, cross_tenant %d "
              "(FR-BIL-002/FR-LLM-011/FR-TOOL-008)"
              % (m.get("usage_records", 0), m.get("requests_total", 0),
                 m.get("model_version_recorded", 0), m.get("requests_total", 0),
                 m.get("errors_normalized", 0), m.get("errors_seen", 0),
                 m.get("cross_tenant", 0))))

    return F


def _fmt(v):
    return "n/a" if v is None else ("%.1f" % v)


def _fmt_share(v):
    return "n/a" if v is None else ("%.0f%%" % (v * 100))


# ─────────────────────────────────────────────────────────────────────────────
# parametre + politika çözümleme
# ─────────────────────────────────────────────────────────────────────────────
def _provider_by_id(cfg, pid):
    for p in cfg.get("providers", []):
        if p.get("provider_id") == pid:
            return p
    raise LlmError("bilinmeyen sağlayıcı: %s" % pid)


def _profile_by_name(cfg, name):
    for p in cfg.get("profiles", []):
        if p.get("name") == name:
            return p
    raise LlmError("bilinmeyen profil: %s" % name)


def _resolve_policy(sample):
    pol = {
        "streaming": True,
        "continuity": True,
        "emit_tool_call": True,
        "no_train": True,
        "region_pin": True,
        "system_immutable": True,
        "meter": True,
        "record_model_version": True,
        "normalize_errors": True,
        "tenant_isolation": True,
        "order_guard": True,
    }
    pol.update(sample.get("policy", {}))
    return pol


def _resolve_provider(sample, cfg):
    if "provider_obj" in sample:
        return sample["provider_obj"]
    pid = sample.get("provider")
    if pid:
        return _provider_by_id(cfg, pid)
    prof = _profile_by_name(cfg, sample.get("profile", cfg.get("default_profile")))
    return _provider_by_id(cfg, prof.get("primary_provider"))


def simulate_cmd(sample_path):
    spec = _load(SPEC_PATH)
    sample = _load(sample_path)
    name = sample.get("name", os.path.basename(sample_path))
    expect = sample.get("expect", "pass")
    gates = spec.get("gates", {})
    policy = _resolve_policy(sample)

    try:
        cfg = _load(PROFILES_CFG)
        provider = _resolve_provider(sample, cfg)
    except LlmError as ex:
        print("simulate[%s]: %s" % (name, ex))
        return 0 if expect == "fail" else 1

    try:
        m = simulate(sample, provider, policy, gates)
    except LlmError as ex:
        print("simulate[%s]: REDDEDİLDİ — %s" % (name, ex))
        return 0 if expect == "fail" else 1

    F = evaluate(gates, m)
    print("simulate[%s] sağlayıcı=%s senaryo=%s | %d request | first-token P50/P95=%s/%s ms | "
          "küçük-tier P95=%s ms | %d kritik→tool-call"
          % (name, m["provider_id"], "+".join(m["scenario"]), m["requests_total"],
             _fmt(m["first_token_p50_ms"]), _fmt(m["first_token_p95_ms"]),
             _fmt(m["small_tier_first_token_p95_ms"]), m["tool_calls_ok"]))
    print("  full_buffered=%d | token_stall=%d | unhandled_tool=%d | tiers=%s (küçük %s) | "
          "no_train_viol=%d | region_viol=%d | sys_mut=%d | usage=%d/%d | model_ver=%d | in/out tok=%d/%d"
          % (m["full_buffered"], m["token_stall"], m["unhandled_tool"], ",".join(m["tiers_seen"]),
             _fmt_share(m["small_tier_share"]), m["no_train_violation"], m["region_violation"],
             m["system_prompt_mutation"], m["usage_records"], m["requests_total"],
             m["model_version_recorded"], m["input_tokens_total"], m["output_tokens_total"]))
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


def _provider_conformant(p):
    feats = set(p.get("features", []))
    tiers = set(p.get("tiers", []))
    return REQUIRED_FEATURES <= feats and p.get("no_train") is True and TIERS <= tiers


def validate():
    spec = _load(SPEC_PATH)
    R = []

    _check(R, spec.get("wbs") == "4.2.4", "spec.wbs == 4.2.4")
    _check(R, spec.get("version"), "spec.version mevcut")

    # ── placement (SPI arkası, orchestrator yalnız SPI'ye bağımlı, THINK, stream-first)
    pl = spec.get("placement", {})
    _check(R, pl.get("behind_spi") is True and pl.get("orchestrator_depends_on_spi_only") is True,
           "LlmAdapter SPI arkası; orchestrator yalnız SPI'ye bağımlı (ADR-001/SAD §8.1)")
    _check(R, pl.get("turn_state") == "THINK", "THINK durumunda (SAD §6.1)")
    _check(R, pl.get("stream_first") is True, "P1 akış-önce (stream-first, FR-RES-002)")
    _check(R, pl.get("event_driven") is True and pl.get("non_blocking") is True,
           "olay-tetikli + bloklamaz")
    _check(R, pl.get("routing_owned_by"), "P9 model routing/tiering 5.1-5.3'te (SAD §9)")

    # ── spi yüzeyi (P2/P5)
    sp = spec.get("spi", {})
    _check(R, "complete" in sp.get("methods", []),
           "SPI complete (SAD §8.1/API §11.4)")
    _check(R, "ToolCallChunk" in sp.get("chunk_types", []) and "TokenChunk" in sp.get("chunk_types", []),
           "P1/P2 LlmChunk = TokenChunk | ToolCallChunk")
    _check(R, set(sp.get("tool_call_chunk_fields", [])) >= {"toolName", "argumentsJson"},
           "P2 ToolCallChunk{toolName, argumentsJson} (schema-doğrulamalı; FR-LLM-008)")
    _check(R, "system" in sp.get("message_roles", []) and "noTrain" in sp.get("llm_request_fields", []),
           "P7/P6 LlmRequest system rolü + noTrain (FR-LLM-006/012)")
    _check(R, set(sp.get("required_features", [])) == REQUIRED_FEATURES,
           "P5 required_features {streaming, tool_call}")

    # ── kapılar
    g = spec.get("gates", {})
    _check(R, g.get("first_token_p95_ms") == 400, "P1 first_token_p95_ms = 400 (SAD §20 LLM genel)")
    _check(R, g.get("first_token_green_ms", 1e9) < g.get("first_token_p95_ms", 0),
           "P1 yeşil bant < kapı (first-token)")
    _check(R, g.get("small_tier_first_token_p95_ms") == 200,
           "P4 small_tier_first_token_p95_ms = 200 (SAD §20 küçük model)")
    _check(R, g.get("small_tier_first_token_green_ms", 1e9) < g.get("small_tier_first_token_p95_ms", 0),
           "P4 yeşil bant < kapı (küçük-tier)")
    _check(R, g.get("small_tier_first_token_p95_ms", 1e9) < g.get("first_token_p95_ms", 0),
           "P4 küçük-tier kapısı < genel kapı (küçük model daha hızlı)")
    _check(R, g.get("stall_threshold_ms", 0) > 0, "P3 stall_threshold_ms > 0")
    _check(R, g.get("max_full_buffered", -1) == 0, "P1 max_full_buffered = 0 (akış-önce)")
    _check(R, g.get("max_unhandled_tool", -1) == 0, "P2 max_unhandled_tool = 0 (FR-LLM-008)")
    _check(R, g.get("max_token_stall", -1) == 0, "P3 max_token_stall = 0")
    _check(R, g.get("max_no_train_violation", -1) == 0, "P6 max_no_train_violation = 0")
    _check(R, g.get("max_region_violation", -1) == 0, "P6 max_region_violation = 0")
    _check(R, g.get("max_system_prompt_mutation", -1) == 0, "P7 max_system_prompt_mutation = 0")
    _check(R, g.get("max_cross_tenant", -1) == 0, "P8 max_cross_tenant = 0")
    _check(R, g.get("min_providers", 0) >= 2, "P5 min_providers ≥ 2 (ADR-002)")
    _check(R, g.get("min_tiers", 0) >= 2, "P4 min_tiers ≥ 2 (küçük/büyük; FR-LLM-013)")
    _check(R, g.get("require_metering") is True, "P8 require_metering (FR-BIL-002)")
    _check(R, g.get("require_model_version_recorded") is True, "P8 require_model_version_recorded (FR-LLM-011)")
    _check(R, g.get("require_error_normalized") is True, "P8 require_error_normalized (FR-TOOL-008)")
    _check(R, set(g.get("required_features", [])) == REQUIRED_FEATURES,
           "gates required_features SPI ile tutarlı")

    # ── fallback (P9 sınır)
    fb = spec.get("fallback", {})
    _check(R, fb.get("min_providers", 0) >= 2 and fb.get("deterministic_flow_on_failure") is True,
           "P9 fallback ≥2 sağlayıcı + deterministic flow (FR-LLM-010)")
    _check(R, fb.get("switching_owned_by") == "4.3.3", "P9 fallback anahtarlama 4.3.3'te")

    # ── metrikler → observability
    me = spec.get("metrics", {})
    emitted = set(me.get("emitted", []))
    _check(R, {"llm_first_token_ms", "llm_token_stall_total", "llm_tool_call_total",
               "llm_input_tokens_total", "llm_output_tokens_total"} <= emitted,
           "metrikler: first_token + stall + tool_call + in/out tokens yayılır")
    _check(R, len(me.get("maps_to_observability", {})) >= 1,
           "metrik observability'ye eşlenir (0.4.7)")

    # ── error taxonomy (P10)
    et = spec.get("error_taxonomy", {})
    mapping = et.get("mapping", {})
    _check(R, len(mapping) >= 5, "P10 hata eşlemesi (≥5)")
    _check(R, all(v in ERROR_TAXONOMY for v in mapping.values()),
           "P10 tüm hedefler API §11.6 ErrorTaxonomy'de")
    _check(R, mapping.get("provider_timeout") == "TIMEOUT"
           and mapping.get("provider_5xx") == "UNAVAILABLE"
           and mapping.get("content_filter") == "CONTENT_FILTERED"
           and mapping.get("region_mismatch") == "REGION_VIOLATION",
           "P10 timeout→TIMEOUT, 5xx→UNAVAILABLE, content→CONTENT_FILTERED, bölge→REGION_VIOLATION")

    # ── residency + pii (P6/P10)
    rs = spec.get("residency", {})
    _check(R, rs.get("region_pin_required") is True, "P6/P10 residency region pin (NFR 10.7)")
    _check(R, rs.get("no_train_required") is True, "P6 no-train zorunlu (FR-LLM-012)")
    _check(R, rs.get("no_log_required") is True
           and set(rs.get("allowed_retention", [])) <= ALLOWED_RETENTION,
           "P6 no-log: data_retention NONE/EPHEMERAL (FR-KB-010)")
    pii = spec.get("pii", {})
    _check(R, pii.get("raw_prompt_in_spec_forbidden") is True
           and pii.get("raw_output_in_spec_forbidden") is True
           and pii.get("pii_value_in_spec_forbidden") is True,
           "P10 ham prompt/çıktı/PII değeri spec'te yasak")

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

    # ── config sağlayıcı + profil doğrulaması (P5)
    if os.path.exists(PROFILES_CFG):
        cfg = _load(PROFILES_CFG)
        provs = cfg.get("providers", [])
        conformant = [p for p in provs if _provider_conformant(p)]
        _check(R, len(conformant) >= g.get("min_providers", 2),
               "P5 ≥%d SPI-uyumlu sağlayıcı (streaming+tool_call + noTrain + ≥2 tier)"
               % g.get("min_providers", 2))
        pids = [p.get("provider_id") for p in provs]
        _check(R, len(pids) == len(set(pids)), "config sağlayıcı ID'leri benzersiz")
        for p in provs:
            _check(R, p.get("data_retention") in ALLOWED_RETENTION,
                   "P6 config %s data_retention NONE/EPHEMERAL" % p.get("provider_id"))
            _check(R, p.get("no_train") is True, "P6 config %s no_train=true" % p.get("provider_id"))
            _check(R, TIERS <= set(p.get("tiers", [])), "P4 config %s ≥2 tier (küçük/büyük)" % p.get("provider_id"))
            _check(R, p.get("first_token_ms", 1e9) <= g.get("first_token_p95_ms", 0),
                   "P1 config %s first_token_ms ≤ genel kapı" % p.get("provider_id"))
            _check(R, p.get("first_token_small_ms", 1e9) <= g.get("small_tier_first_token_p95_ms", 0),
                   "P4 config %s first_token_small_ms ≤ küçük-tier kapı" % p.get("provider_id"))
            _check(R, float(p.get("inter_token_ms", 1e9)) <= g.get("stall_threshold_ms", 0),
                   "P3 config %s inter_token_ms ≤ stall eşiği" % p.get("provider_id"))
        profs = cfg.get("profiles", [])
        _check(R, len(profs) >= 2, "config ≥2 çalıştırma profili")
        for prof in profs:
            _check(R, bool(prof.get("region")), "P10 config %s bölge pini var" % prof.get("name"))
            _check(R, prof.get("primary_provider") in pids and prof.get("fallback_provider") in pids,
                   "P5/P9 config %s primary+fallback geçerli sağlayıcı" % prof.get("name"))
            _check(R, prof.get("primary_provider") != prof.get("fallback_provider"),
                   "P9 config %s primary≠fallback (≥2 sağlayıcı)" % prof.get("name"))

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
PROVIDER_A = {
    "provider_id": "llm-stream-A", "features": ["streaming", "tool_call", "system_prompt"],
    "regions": ["EU", "TR"], "no_train": True, "data_retention": "NONE", "tiers": ["small", "big"],
    "first_token_ms": 280, "first_token_small_ms": 150,
    "inter_token_ms": 32, "inter_token_ms_degraded": 260, "per_token_gen_ms": 9,
}


def _req(t, req_id="r1", model="m-big-1", ver="2026-05", tier="big", in_tok=400, out_tok=80,
         expects_tool=False, tool_call=False, system_preserved=None, no_train=None,
         region_pinned=None, retention=None, provider=None, tenant=None):
    ev = {"kind": "request", "req_id": req_id, "model": model, "model_version": ver, "tier": tier,
          "t": t, "input_tokens": in_tok, "output_tokens": out_tok}
    if expects_tool:
        ev["expects_tool"] = True
    if tool_call:
        ev["tool_call"] = True
    if system_preserved is not None:
        ev["system_preserved"] = system_preserved
    if no_train is not None:
        ev["no_train"] = no_train
    if region_pinned is not None:
        ev["region_pinned"] = region_pinned
    if retention is not None:
        ev["data_retention"] = retention
    if provider:
        ev["provider"] = provider
    if tenant:
        ev["tenant_id"] = tenant
    return ev


def _end(t, req_id="r1", reason="normal", tax=None):
    ev = {"kind": "end", "req_id": req_id, "t": t, "reason": reason}
    if tax is not None:
        ev["error_taxonomy"] = tax
    return ev


def _pol(**over):
    pol = {"streaming": True, "continuity": True, "emit_tool_call": True, "no_train": True,
           "region_pin": True, "system_immutable": True, "meter": True, "record_model_version": True,
           "normalize_errors": True, "tenant_isolation": True, "order_guard": True}
    pol.update(over)
    return pol


def _run(events, provider=None, **pol_over):
    spec = _load(SPEC_PATH)
    return simulate({"events": events}, provider or PROVIDER_A, _pol(**pol_over), spec.get("gates", {}))


def selftest():
    spec = _load(SPEC_PATH)
    gates = spec.get("gates", {})
    cases = []

    def case(ok, label):
        cases.append((bool(ok), label))

    # 0) validate iyi spec+config'te geçer
    case(_validate_obj(_load(SPEC_PATH)) == 0, "validate iyi spec+config'te 0 döndürür")

    # ── happy: streaming + tool-call + tiering + metering (P1–P8) ──────────────────
    mh = simulate({"events": [
        _req(0, req_id="r1", tier="big", in_tok=500, out_tok=90),
        _req(1500, req_id="r2", tier="small", in_tok=200, out_tok=30),
        _req(3000, req_id="r3", tier="big", in_tok=300, out_tok=20, expects_tool=True, tool_call=True),
        _end(900, req_id="r1"), _end(2000, req_id="r2"), _end(3400, req_id="r3"),
    ]}, PROVIDER_A, _pol(), gates)
    case(mh["first_token_p95_ms"] <= 400 and mh["full_buffered"] == 0, "happy: streaming first-token ≤400 + akış-önce (P1)")
    case(mh["unhandled_tool"] == 0 and mh["tool_calls_ok"] == 1, "happy: kritik tur schema-doğrulamalı tool-call (P2)")
    case(mh["token_stall"] == 0, "happy: token-arası süreklilik, stall yok (P3)")
    case(mh["small_tier_first_token_p95_ms"] <= 200 and len(mh["tiers_seen"]) == 2, "happy: ≥2 tier + küçük-tier ≤200 (P4)")
    case(mh["no_train_violation"] == 0 and mh["region_violation"] == 0, "happy: no-train+no-log+residency (P6)")
    case(mh["system_prompt_mutation"] == 0, "happy: system prompt değişmedi (P7)")
    case(mh["usage_records"] == mh["model_version_recorded"] == mh["requests_total"] == 3, "happy: her complete UsageRecord+model/ver (P8)")
    case(all(ok for ok, _ in evaluate(gates, mh)), "happy tüm kapıları geçer")

    # ── determinizm ───────────────────────────────────────────────────────────────
    seq = [_req(0, expects_tool=True, tool_call=True), _end(50)]
    case(_run(seq) == _run(seq), "determinizm: aynı olay-akışı birebir aynı metrik (random yok)")

    # ── ≥2 sağlayıcı: B ile de geçer ───────────────────────────────────────────────
    pb = dict(PROVIDER_A); pb["provider_id"] = "llm-stream-B"; pb["first_token_ms"] = 240
    pb["first_token_small_ms"] = 120; pb["inter_token_ms"] = 28
    mb = _run([_req(0, tier="small"), _req(100, req_id="r2", tier="big", expects_tool=True, tool_call=True),
               _end(80), _end(180, req_id="r2")], provider=pb)
    case(all(ok for ok, _ in evaluate(gates, mb)) and mb["provider_id"] == "llm-stream-B",
         "≥2 sağlayıcı: ikinci adapter (B) de kapıları geçer (FR-LLM-001/ADR-002)")

    # ── degraded-1: streaming kapalı → full buffer → first-token = full gen (P1 eler) ──
    d1 = _run([_req(0, out_tok=90), _end(20)], streaming=False)
    case(d1["full_buffered"] >= 1 and d1["first_token_max_ms"] > 400,
         "degraded(no-stream): tüm yanıt tamponlandı → first-token 90×9=810ms (FR-RES-002 ihlali)")
    case(not all(ok for ok, _ in evaluate(gates, d1)), "degraded(no-stream) P1 eler")

    # ── degraded-2: kritik tur serbest metinle (P2 eler) ────────────────────────────
    d2 = _run([_req(0, expects_tool=True, tool_call=True), _end(50)], emit_tool_call=False)
    case(d2["unhandled_tool"] >= 1 and d2["tool_calls_ok"] == 0,
         "degraded(no-tool): kritik işlem serbest metinle bırakıldı (FR-LLM-008 ihlali)")
    case(not all(ok for ok, _ in evaluate(gates, d2)), "degraded(no-tool) P2 eler")
    # kritik tur ama tool_call beklenmedi → unhandled_tool
    d2b = _run([_req(0, expects_tool=True, tool_call=False), _end(50)])
    case(d2b["unhandled_tool"] >= 1, "degraded(free-text-critical): tool_call yok → unhandled_tool")
    case(not all(ok for ok, _ in evaluate(gates, d2b)), "degraded(free-text-critical) P2 eler")

    # ── degraded-3: token süreklilik kapalı → stall → ölü hava (P3 eler) ─────────────
    d3 = _run([_req(0), _end(50)], continuity=False)
    case(d3["token_stall"] >= 1 and d3["inter_token_p95_ms"] > gates["stall_threshold_ms"],
         "degraded(stall): token-arası boşluk 260ms > 120 eşiği → stall (FR-RES-009 ölü hava)")
    case(not all(ok for ok, _ in evaluate(gates, d3)), "degraded(stall) P3 eler")

    # ── degraded-4: küçük-tier yavaş → küçük-tier kapı eler (P4 eler) ────────────────
    slow_small = dict(PROVIDER_A); slow_small["first_token_small_ms"] = 260
    d4 = _run([_req(0, tier="small"), _end(50)], provider=slow_small)
    case(d4["small_tier_first_token_p95_ms"] > 200, "degraded(slow-small-tier): küçük-tier first-token 260ms > 200")
    case(not all(ok for ok, _ in evaluate(gates, d4)), "degraded(slow-small-tier) P4 eler")

    # ── degraded-5: no-train kapalı (P6 eler) ───────────────────────────────────────
    d5 = _run([_req(0, no_train=False), _end(50)])
    case(d5["no_train_violation"] >= 1, "degraded(no-train-off): noTrain=false → tenant verisi eğitime açık (FR-LLM-012)")
    case(not all(ok for ok, _ in evaluate(gates, d5)), "degraded(no-train-off) P6 eler")
    # retention no-log dışı → P6 eler
    d5b = _run([_req(0, retention="PROVIDER_DEFAULT"), _end(50)])
    case(d5b["no_train_violation"] >= 1, "degraded(no-log-off): retention PROVIDER_DEFAULT → no-log ihlali (FR-KB-010)")
    case(not all(ok for ok, _ in evaluate(gates, d5b)), "degraded(no-log-off) P6 eler")
    # bölgesel pin yok → P6 eler
    d5c = _run([_req(0, region_pinned=False), _end(50)])
    case(d5c["region_violation"] >= 1, "degraded(no-region-pin): bölgesel endpoint yok (NFR 10.7)")
    case(not all(ok for ok, _ in evaluate(gates, d5c)), "degraded(no-region-pin) P6 eler")

    # ── degraded-6: system prompt değiştirildi (P7 eler) ────────────────────────────
    d6 = _run([_req(0, system_preserved=False), _end(50)])
    case(d6["system_prompt_mutation"] >= 1, "degraded(sys-mutation): system mesajı user/KB ile değiştirildi (FR-LLM-006)")
    case(not all(ok for ok, _ in evaluate(gates, d6)), "degraded(sys-mutation) P7 eler")

    # ── degraded-7: metering / model-ver / hata normalizasyonu (P8 eler) ────────────
    d7 = _run([_req(0), _end(50)], meter=False)
    case(d7["usage_records"] == 0 and d7["requests_total"] == 1, "degraded(no-meter): UsageRecord üretilmedi (FR-BIL-002)")
    case(not all(ok for ok, _ in evaluate(gates, d7)), "degraded(no-meter) P8 eler")
    d7b = _run([_req(0), _end(50)], record_model_version=False)
    case(d7b["model_version_recorded"] == 0, "degraded(no-model-ver): model+versiyon kaydedilmedi (FR-LLM-011)")
    case(not all(ok for ok, _ in evaluate(gates, d7b)), "degraded(no-model-ver) P8 eler")
    d7c = _run([_req(0), _end(50, reason="error", tax="raw-provider-503")], normalize_errors=False)
    case(d7c["errors_seen"] == 1 and d7c["errors_normalized"] == 0,
         "degraded(no-norm): sağlayıcı hatası ErrorTaxonomy'ye çevrilmedi (FR-TOOL-008)")
    case(not all(ok for ok, _ in evaluate(gates, d7c)), "degraded(no-norm) P8 eler")
    # hata normalize edilirse geçer
    d7ok = _run([_req(0), _end(50, reason="error", tax="UNAVAILABLE")])
    case(d7ok["errors_normalized"] == 1 and all(ok for ok, _ in evaluate(gates, d7ok)),
         "error-normalized: provider_5xx → UNAVAILABLE (API §11.6) geçer")

    # ── geçersiz olay reddi (P10) ──────────────────────────────────────────────────
    case(_raises(lambda: _run([_end(10)])), "P10 bilinmeyen req_id end → reddedilir")
    case(_raises(lambda: _run([_req(0, tier="huge"), _end(10)])), "P10 geçersiz tier → reddedilir")
    case(_raises(lambda: _run([_req(0)])), "P10 'end' olmadan → reddedilir")
    case(_raises(lambda: _run([_req(0), _req(0)])), "P10 tekrar kullanılan req_id → reddedilir")
    case(_raises(lambda: _run([_req(1000), _end(2000), _req(0, req_id="r2"), _end(5)])), "P10 out-of-order → reddedilir")
    case(_raises(lambda: _run([_req(0), {"kind": "nope", "t": 1}, _end(2)])), "P10 bilinmeyen olay → reddedilir")
    case(_raises(lambda: simulate({"events": []}, PROVIDER_A, _pol(), gates)), "P10 boş olay akışı → reddedilir")
    case(_raises(lambda: _run([_req(0, tenant="t-other"), _end(50)])),
         "P10 cross-tenant (izolasyon açık) → reddedilir")

    # ── validate negatif kapılar ────────────────────────────────────────────────────
    s = json.loads(json.dumps(spec)); s["gates"]["first_token_p95_ms"] = 999
    case(_validate_obj(s) != 0, "P1 first_token_p95_ms≠400 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["small_tier_first_token_p95_ms"] = 999
    case(_validate_obj(s) != 0, "P4 small_tier_first_token_p95_ms≠200 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_full_buffered"] = 1
    case(_validate_obj(s) != 0, "P1 max_full_buffered>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_unhandled_tool"] = 1
    case(_validate_obj(s) != 0, "P2 max_unhandled_tool>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_token_stall"] = 1
    case(_validate_obj(s) != 0, "P3 max_token_stall>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["min_tiers"] = 1
    case(_validate_obj(s) != 0, "P4 min_tiers<2 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_no_train_violation"] = 1
    case(_validate_obj(s) != 0, "P6 max_no_train_violation>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_system_prompt_mutation"] = 1
    case(_validate_obj(s) != 0, "P7 max_system_prompt_mutation>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["min_providers"] = 1
    case(_validate_obj(s) != 0, "P5 min_providers<2 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["require_metering"] = False
    case(_validate_obj(s) != 0, "P8 require_metering=false → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["require_model_version_recorded"] = False
    case(_validate_obj(s) != 0, "P8 require_model_version_recorded=false → validate eler")
    s = json.loads(json.dumps(spec)); s["error_taxonomy"]["mapping"]["x"] = "NOPE"
    case(_validate_obj(s) != 0, "P10 taksonomi-dışı → validate eler")
    s = json.loads(json.dumps(spec)); s["pii"]["pii_value_in_spec_forbidden"] = False
    case(_validate_obj(s) != 0, "P10 pii-değer-yasak kapalı → validate eler")
    s = json.loads(json.dumps(spec)); s["spi"]["required_features"] = ["streaming"]
    case(_validate_obj(s) != 0, "P5 eksik required_features → validate eler")
    s = json.loads(json.dumps(spec)); s["residency"]["no_train_required"] = False
    case(_validate_obj(s) != 0, "P6 no-train zorunluluğu kapalı → validate eler")
    s = json.loads(json.dumps(spec)); s["residency"]["allowed_retention"] = ["PROVIDER_DEFAULT"]
    case(_validate_obj(s) != 0, "P6 no-log dışı retention → validate eler")
    s = json.loads(json.dumps(spec)); s["metrics"]["secret"] = "api_key: AKIAIOSFODNN7EXAMPLE"
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
    except LlmError:
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
    print("""llm-adapter-spec.json beklenen şekli (WBS 4.2.4):
  wbs, version, phase, trace{fr,nfr,sad,adr,api,srs,rtm,vendor_eval,consumes,observability}
  placement{behind_spi=true, orchestrator_depends_on_spi_only=true, turn_state=THINK,
            stream_first=true, event_driven=true, non_blocking=true, routing_owned_by}        (P1,P9)
  spi{methods[complete,...], llm_request_fields[...noTrain], message_roles[...system],
      chunk_types[TokenChunk,ToolCallChunk], tool_call_chunk_fields[toolName,argumentsJson,callId],
      required_features[streaming,tool_call]}                                                  (P2,P5,P7)
  gates{first_token_p95_ms=400, small_tier_first_token_p95_ms=200, stall_threshold_ms,
        max_full_buffered=0, max_unhandled_tool=0, max_token_stall=0, max_no_train_violation=0,
        max_region_violation=0, max_system_prompt_mutation=0, max_cross_tenant=0,
        min_providers=2, min_tiers=2, require_metering=true, require_model_version_recorded=true,
        require_error_normalized=true, tool_call_min_ratio, required_features[...]}             (P1-P8)
  fallback{min_providers=2, deterministic_flow_on_failure=true, switching_owned_by=4.3.3}      (P9)
  metrics{emitted[], maps_to_observability{}}
  error_taxonomy{mapping→API §11.6}                                                            (P10)
  residency{region_pin_required=true, no_train_required=true, no_log_required=true,
            allowed_retention[NONE,EPHEMERAL]}                                                 (P6,P10)
  pii{raw_prompt_in_spec_forbidden, raw_output_in_spec_forbidden, pii_value_in_spec_forbidden} (P10)
  invariants[≥10]{id, desc, trace}

config/llm-adapter-profiles.json: providers[]{provider_id, languages, features
  (⊇streaming,tool_call), regions, no_train(=true), data_retention(NONE/EPHEMERAL),
  tiers(⊇small,big), first_token_ms, first_token_small_ms, inter_token_ms,
  inter_token_ms_degraded, per_token_gen_ms}; profiles[]{name, primary_provider,
  fallback_provider, first_token_target_ms, small_tier_target_ms, region}

simulate sample: {name, provider | provider_obj | profile, tenant_id?, expect, expected?{metrik:değer},
  policy?{streaming, continuity, emit_tool_call, no_train, region_pin, system_immutable,
  meter, record_model_version, normalize_errors, tenant_isolation},
  events[{kind:'request', req_id, model, model_version, tier∈{small,big}, t, input_tokens,
          output_tokens, expects_tool?, tool_call?, system_preserved?, no_train?, region_pinned?,
          data_retention?, provider?} | {kind:'end', req_id, t, reason∈{normal,error}, error_taxonomy?}]}
  — request → end; son olay 'end' olmalı; tier ∈ {small,big}

komutlar: validate | simulate <sample.json> | selftest | schema""")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if cmd == "validate":
        return validate()
    if cmd == "simulate":
        if len(sys.argv) < 3:
            print("kullanım: llm_adapter_probe.py simulate <sample.json>")
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
