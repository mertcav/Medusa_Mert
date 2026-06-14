#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tts_adapter_probe.py — WBS 4.2.3 TTS adapter #1 + #2 (streaming, pronunciation dictionary, cancel)

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only statik + davranış kapısı. `runtime/` ve
`telephony/` modül disipliniyle aynı; burada iki SOMUT TtsAdapter implementasyonunu (≥2/kategori —
FR-TTS-001) ortak SPI (SAD §8.1 / API §11.3) arkasına bağlayan DETERMİNİSTİK bir referans adapter
sürücüsü (olay-tetikli, sanal saat, random YOK; gerçek TTS/ses üretimi YOK — sağlayıcı gecikme profili
+ akış MODELİ). Görev başlığındaki üç boyut:
  • STREAMING:    synthesize() ilk ses paketini akış-önce (no full buffering) düşük gecikmeyle döndürür;
                  first-byte P95 ≤ SAD §20 (200 ms) + full_buffered=0 (P1 — FR-TTS-002/FR-RES-002).
  • PRONUNCIATION:sayı/tarih/para/isim yapısal alanları pronunciation dictionary ile sentezlenir;
                  unhandled_structured=0 (P3 — FR-TTS-004).
  • CANCEL:       cancel(streamId) → akış ANINDA kesilir; cancel→susma P95 ≤ 200 ms + kesme sonrası
                  chunk yok (P2 — FR-TTS-005/FR-RTC-002/NFR 10.1).
Ek (Must): ses karakteri tutarlılığı (P6 — FR-TTS-009), cache statik anons (P7 — FR-TTS-010), 8 kHz +
metering + hata normalizasyonu + no-log/residency (P8 — FR-RES-008/FR-BIL-002/FR-TOOL-008/FR-KB-010).

KAPSAM AYRIMI: TTS fallback ANAHTARLAMA → 4.3.2 (bu motor ≥2 SPI-uyum + eşdeğer-ses HARİTASINI doğrular);
ortak yetenekler (timeout/retry/breaker/health/pool) → 4.1.2/4.1.6 (tüketilir); metering motoru → 4.1.3;
residency/retention → 4.1.4; cache motoru → 16.1 (cache-hit yolu desteklenir); dead-air önleme →
orchestrator (FR-RES-009; süreklilik beslenir); barge-in olayı → 2.2.3/3.1.3 (BARGE_IN → cancel);
ses klonlama izni → 4.2.6 (clonedVoiceConsentRef alanı taşınır); sağlayıcı SEÇİMİ → 0.2.6/0.3.x.

Komutlar:
  validate              tts-adapter-spec.json'ı invariant'lara (P1–P10) + config sağlayıcı/profillerine doğrular.
  simulate <sample>     Deterministik TtsAdapter — olay-akışı (request + chunk + cancel + end) →
                        streaming/pronunciation/cancel/cache/voice/metering metrikleri → HARD kapılar
                        (P1–P8) → çıkış kodu.
  selftest              İyi/kötü spec+sample ile kapıların doğru tetiklendiğini kanıtlar.
  schema                Beklenen spec şeklini özetler.

Sunucu/credential GEREKMEZ. simulate gerçek TTS yerine sağlayıcı gecikme profili (config providers) +
akış MODELİ kullanır (canlı sistemde Go/Rust async runtime + gerçek TtsAdapter, ADR-003/SAD §6.3/§8.1).
Ham SES/audio, sentezlenecek ham METİN veya PII DEĞERİ YOK — yalnız sağlayıcı kimliği + gecikme/akış
SAYILARI + alan TİPLERİ + voice kimlikleri + sanal zaman.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "tts-adapter-spec.json")
PROFILES_CFG = os.path.join(HERE, "config", "tts-adapter-profiles.json")

ERROR_TAXONOMY = {
    "TIMEOUT", "RATE_LIMITED", "UNAVAILABLE", "AUTH",
    "INVALID_REQUEST", "CONTENT_FILTERED", "QUOTA_EXCEEDED", "REGION_VIOLATION",
}
SECRET_RE = re.compile(
    r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer)\b\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}"
)
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")

REQUIRED_FEATURES = {"streaming", "barge_in_cancel", "pronunciation_dict"}
STRUCTURED_FIELDS = {"number", "date", "currency", "name"}
FIELD_TYPES = STRUCTURED_FIELDS | {"general"}
ALLOWED_RETENTION = {"NONE", "EPHEMERAL"}
END_REASONS = {"normal", "cancelled", "error"}


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_placeholder(v):
    return isinstance(v, str) and PLACEHOLDER_RE.match(v) is not None


def _percentile(values, pct):
    """Lineer-interpolasyonlu yüzdelik (media_latency / tts_eval probe ile birebir). values boşsa None."""
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


class TtsError(Exception):
    """Geçersiz/desteklenmeyen olay veya yetki/izolasyon ihlali — sessizce kabul yok, reddet (P10)."""


# ─────────────────────────────────────────────────────────────────────────────
# TtsAdapter referans sürücüsü (deterministik)
# ─────────────────────────────────────────────────────────────────────────────
class TtsAdapterRuntime:
    """SAD §8.1 / API §11.3 TtsAdapter sürücüsü. Olay-akışını işler:
        request → (chunk*) → (cancel?) → end
    Her request için sağlayıcı gecikme PROFİLİNDEN (config providers) streaming first-byte, akış
    sürekliliği (RTF/underrun), pronunciation dictionary uygulaması, cancel→susma gecikmesi, cache-hit,
    ses karakteri tutarlılığı ve usage metering DETERMİNİSTİK hesaplanır (random YOK; sanal saat = event.t).

    Olaylar:
      {kind:'request', req_id, voice_id, language, t, text_chars, fields:[{type,chars}], sample_rate_hz?,
                       pronunciation_dict_id?, cached?, provider?, voice_equivalent?, tenant_id?}
      {kind:'cancel',  req_id, t}                       # barge-in: cancel_req_ms = t - request.t
      {kind:'end',     req_id, t, reason∈{normal,cancelled,error}, error_taxonomy?}
    """

    def __init__(self, provider, policy, gates, tenant_id="t-self"):
        self.pv = provider
        self.pol = policy
        self.g = gates
        self.tenant_id = tenant_id

        self.requests = {}              # req_id -> state
        self.call_voice_id = None       # ses karakteri tutarlılığı (P6)
        self._last_t = None

        # ölçüm dizileri
        self.first_byte_ms = []         # cold (gerçek sentez) first-byte
        self.cache_first_byte_ms = []   # cache-hit first-byte (FR-TTS-010)
        self.cancel_latency_ms = []     # cancel→susma (FR-TTS-005)

        # sayaçlar / metrikler
        self.requests_total = 0
        self.full_buffered = 0          # akış-önce ihlali: ilk chunk tüm sentez bitince (P1)
        self.chunk_after_cancel = 0     # kesme sonrası ses çıktı (P2 — talk-over)
        self.structured_total = 0       # sayı/tarih/para/isim alan sayısı
        self.pronunciation_applied = 0  # sözlük uygulanan yapısal alan
        self.unhandled_structured = 0   # sözlüksüz yapısal alan (P3 ihlali)
        self.underrun = 0               # ölü hava (P4)
        self.cache_hits = 0
        self.voice_inconsistent = 0     # voiceId çağrı içinde değişti (P6)
        self.voice_switch_unmapped = 0  # fallback eşdeğer-ses haritasız (P6)
        self.sample_rate_mismatch = 0   # 8 kHz dışı (P8/FR-RES-008)
        self.cross_tenant = 0
        self.usage_records = 0          # UsageRecord (CHARACTERS) sayısı (P8/FR-BIL-002)
        self.chars_total = 0
        self.errors_seen = 0
        self.errors_normalized = 0
        self.ended = 0

    def _check_time(self, t):
        if not isinstance(t, (int, float)):
            raise TtsError("zaman damgası sayısal değil → INVALID_REQUEST")
        if self._last_t is not None and t < self._last_t:
            if self.pol.get("order_guard", True):
                raise TtsError("out-of-order olay (t geriye) reddedildi → INVALID_REQUEST")
        self._last_t = max(self._last_t if self._last_t is not None else t, t)

    def _check_scope(self, ev):
        tt = ev.get("tenant_id", self.tenant_id)
        if tt != self.tenant_id:
            self.cross_tenant += 1
            if self.pol.get("tenant_isolation", True):
                raise TtsError("cross-tenant erişim reddedildi → AUTH")

    # ── request: synthesize() çağrısı (P1/P3/P4/P6/P7/P8) ─────────────────────
    def request(self, ev):
        self._check_time(ev.get("t"))
        self._check_scope(ev)
        req_id = ev.get("req_id")
        if not isinstance(req_id, str) or not req_id:
            raise TtsError("req_id yok/boş → INVALID_REQUEST")
        if req_id in self.requests:
            raise TtsError("req_id tekrar kullanıldı → INVALID_REQUEST")
        voice_id = ev.get("voice_id")
        if not isinstance(voice_id, str) or not voice_id:
            raise TtsError("voice_id yok/boş → INVALID_REQUEST")
        text_chars = ev.get("text_chars", 0)
        if not isinstance(text_chars, (int, float)) or text_chars < 0:
            raise TtsError("text_chars sayısal/≥0 değil → INVALID_REQUEST")
        sr = ev.get("sample_rate_hz", self.g.get("sample_rate_hz", 8000))
        fields = ev.get("fields", [])
        if not isinstance(fields, list):
            raise TtsError("fields liste değil → INVALID_REQUEST")
        cached = bool(ev.get("cached", False)) and self.pol.get("cache_enabled", True)
        dict_present = bool(ev.get("pronunciation_dict_id"))

        self.requests_total += 1
        self.chars_total += int(text_chars)

        # ── P8: sample rate (8 kHz native, FR-RES-008)
        if sr != self.g.get("sample_rate_hz", 8000):
            self.sample_rate_mismatch += 1

        # ── P8: usage metering (FR-BIL-002) — her synthesize bir UsageRecord üretir
        if self.pol.get("meter", True):
            self.usage_records += 1

        # ── P6: ses karakteri tutarlılığı (voiceId çağrı boyu sabit)
        if self.call_voice_id is None:
            self.call_voice_id = voice_id
        elif voice_id != self.call_voice_id:
            if ev.get("voice_equivalent") and self.pol.get("voice_consistency", True):
                # fallback eşdeğer ses ile tutarlılık korunur (haritalı geçiş — 4.3.2)
                self.call_voice_id = voice_id
            else:
                self.voice_inconsistent += 1
                if ev.get("provider") and not ev.get("voice_equivalent"):
                    self.voice_switch_unmapped += 1
                self.call_voice_id = voice_id

        # ── P3: pronunciation dictionary (yapısal alanlar)
        for fld in fields:
            ftype = (fld or {}).get("type", "general")
            if ftype not in FIELD_TYPES:
                raise TtsError("geçersiz alan tipi: %r → INVALID_REQUEST" % ftype)
            if ftype in STRUCTURED_FIELDS:
                self.structured_total += 1
                if dict_present and self.pol.get("apply_pronunciation", True):
                    self.pronunciation_applied += 1
                else:
                    self.unhandled_structured += 1

        # ── P1/P7: first-byte (streaming vs full-buffer vs cache-hit)
        if cached:
            fb = float(self.pv.get("cache_first_byte_ms", 12))
            self.cache_first_byte_ms.append(fb)
            self.cache_hits += 1
        else:
            full_synth_ms = float(text_chars) * float(self.pv.get("per_char_synth_ms", 5))
            if self.pol.get("streaming", True):
                fb = float(self.pv.get("first_byte_ms", 120))
            else:
                # BOZUK: tüm yanıt tamponlanır → ilk ses ancak sentez bitince (akış-önce ihlali, FR-RES-002)
                fb = full_synth_ms
                self.full_buffered += 1
            self.first_byte_ms.append(fb)

            # ── P4: akış sürekliliği / ölü hava (RTF<1)
            rtf = float(self.pv.get("synth_rtf", 0.4)) if self.pol.get("realtime", True) \
                else float(self.pv.get("synth_rtf_degraded", 1.3))
            if rtf >= 1.0:
                self.underrun += 1

        self.requests[req_id] = {"start_t": ev.get("t"), "voice_id": voice_id,
                                 "cancelled": False, "ended": False, "cached": cached}

    # ── cancel: barge-in kesme (P2) ───────────────────────────────────────────
    def cancel(self, ev):
        self._check_time(ev.get("t"))
        req_id = ev.get("req_id")
        req = self.requests.get(req_id)
        if req is None:
            raise TtsError("bilinmeyen req_id cancel → INVALID_REQUEST")
        if req["ended"]:
            raise TtsError("bitmiş akış cancel edilemez → INVALID_REQUEST")
        if self.pol.get("cancel_responsive", True):
            stop_delay = float(self.pv.get("cancel_stop_ms", 70))
        else:
            # BOZUK: cancel'a yanıt yavaş + kesme sonrası ses akmaya devam eder (talk-over)
            stop_delay = float(self.pv.get("cancel_stop_ms_degraded", 380))
            self.chunk_after_cancel += 1
        self.cancel_latency_ms.append(stop_delay)
        req["cancelled"] = True

    def end(self, ev):
        req_id = ev.get("req_id")
        req = self.requests.get(req_id)
        if req is None:
            raise TtsError("bilinmeyen req_id end → INVALID_REQUEST")
        if req["ended"]:
            raise TtsError("akış zaten bitti → INVALID_REQUEST")
        reason = ev.get("reason", "normal")
        if reason not in END_REASONS:
            raise TtsError("geçersiz bitiş nedeni: %r → INVALID_REQUEST" % reason)
        if reason == "error":
            self.errors_seen += 1
            tax = ev.get("error_taxonomy")
            if self.pol.get("normalize_errors", True) and tax in ERROR_TAXONOMY:
                self.errors_normalized += 1
        req["ended"] = True
        self.ended += 1

    def metrics(self):
        scenario = []
        if self.first_byte_ms:
            scenario.append("streaming" if self.full_buffered == 0 else "full-buffered")
        if self.cache_hits:
            scenario.append("cache-hit")
        if self.structured_total:
            scenario.append("pronunciation" if self.unhandled_structured == 0 else "pronunciation-missed")
        if self.cancel_latency_ms:
            scenario.append("barge-in" if self.chunk_after_cancel == 0 else "talk-over")
        if self.voice_inconsistent:
            scenario.append("voice-drift")
        if self.errors_seen:
            scenario.append("provider-error")
        if not scenario:
            scenario.append("empty")
        fb_all = self.first_byte_ms
        return {
            "provider_id": self.pv.get("provider_id"),
            "requests_total": self.requests_total,
            "first_byte_p95_ms": _percentile(fb_all, 95),
            "first_byte_p50_ms": _percentile(fb_all, 50),
            "first_byte_max_ms": max(fb_all) if fb_all else None,
            "full_buffered": self.full_buffered,
            "cancel_p95_ms": _percentile(self.cancel_latency_ms, 95),
            "cancel_p50_ms": _percentile(self.cancel_latency_ms, 50),
            "cancel_max_ms": max(self.cancel_latency_ms) if self.cancel_latency_ms else None,
            "chunk_after_cancel": self.chunk_after_cancel,
            "structured_total": self.structured_total,
            "pronunciation_applied": self.pronunciation_applied,
            "unhandled_structured": self.unhandled_structured,
            "underrun": self.underrun,
            "cache_hits": self.cache_hits,
            "cache_first_byte_p95_ms": _percentile(self.cache_first_byte_ms, 95),
            "cache_first_byte_max_ms": max(self.cache_first_byte_ms) if self.cache_first_byte_ms else None,
            "voice_inconsistent": self.voice_inconsistent,
            "voice_switch_unmapped": self.voice_switch_unmapped,
            "sample_rate_mismatch": self.sample_rate_mismatch,
            "cross_tenant": self.cross_tenant,
            "usage_records": self.usage_records,
            "chars_total": self.chars_total,
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
        raise TtsError("boş/geçersiz olay akışı → INVALID_REQUEST")
    rt = TtsAdapterRuntime(provider, policy, gates,
                           tenant_id=sample.get("tenant_id", "t-self"))
    saw_end = False
    for ev in events:
        if not isinstance(ev, dict):
            raise TtsError("olay sözlük değil → INVALID_REQUEST")
        kind = ev.get("kind")
        if kind == "request":
            rt.request(ev)
        elif kind == "cancel":
            rt.cancel(ev)
        elif kind == "end":
            rt.end(ev)
            saw_end = True
        else:
            raise TtsError("bilinmeyen olay tipi: %r → INVALID_REQUEST" % kind)
    if not saw_end:
        raise TtsError("olay akışında 'end' yok → INVALID_REQUEST")
    return rt.metrics()


def evaluate(gates, m):
    """Metrikleri HARD kapılara (P1–P8 davranışsal) karşı değerlendirir. Döner findings[(ok, label)]."""
    F = []

    # ── P1: streaming first-byte + akış-önce
    fb95 = m.get("first_byte_p95_ms")
    fb_ok = (fb95 is None or fb95 <= gates.get("first_byte_p95_ms", 200)) \
        and m.get("full_buffered", 0) <= gates.get("max_full_buffered", 0)
    F.append((fb_ok,
              "P1 streaming: first_byte P95 %s ≤ %d ms + full_buffered %d ≤ %d (akış-önce; FR-TTS-002/SAD §20)"
              % (_fmt(fb95), gates.get("first_byte_p95_ms", 200),
                 m.get("full_buffered", 0), gates.get("max_full_buffered", 0))))

    # ── P2: barge-in cancel + kesme sonrası chunk yok
    cx95 = m.get("cancel_p95_ms")
    cx_ok = (cx95 is None or cx95 <= gates.get("barge_in_cancel_p95_ms", 200)) \
        and m.get("chunk_after_cancel", 0) <= gates.get("max_chunk_after_cancel", 0)
    F.append((cx_ok,
              "P2 cancel: barge-in P95 %s ≤ %d ms + chunk_after_cancel %d ≤ %d (FR-TTS-005/NFR 10.1)"
              % (_fmt(cx95), gates.get("barge_in_cancel_p95_ms", 200),
                 m.get("chunk_after_cancel", 0), gates.get("max_chunk_after_cancel", 0))))

    # ── P3: pronunciation dictionary
    F.append((m.get("unhandled_structured", 0) <= gates.get("max_unhandled_structured", 0),
              "P3 pronunciation: unhandled_structured %d ≤ %d (yapısal %d → sözlük uygulanan %d; FR-TTS-004)"
              % (m.get("unhandled_structured", 0), gates.get("max_unhandled_structured", 0),
                 m.get("structured_total", 0), m.get("pronunciation_applied", 0))))

    # ── P4: akış sürekliliği / ölü hava
    F.append((m.get("underrun", 0) <= gates.get("max_underrun", 0),
              "P4 süreklilik: underrun %d ≤ %d (RTF<1, ölü hava yok; FR-RES-009)"
              % (m.get("underrun", 0), gates.get("max_underrun", 0))))

    # ── P6: ses karakteri tutarlılığı
    F.append((m.get("voice_inconsistent", 0) <= gates.get("max_voice_inconsistent", 0)
              and m.get("voice_switch_unmapped", 0) <= gates.get("max_voice_switch_unmapped", 0),
              "P6 ses tutarlı: voice_inconsistent %d ≤ %d + voice_switch_unmapped %d ≤ %d (FR-TTS-009)"
              % (m.get("voice_inconsistent", 0), gates.get("max_voice_inconsistent", 0),
                 m.get("voice_switch_unmapped", 0), gates.get("max_voice_switch_unmapped", 0))))

    # ── P7: cache (statik anons) first-byte ~0
    cfb = m.get("cache_first_byte_max_ms")
    F.append((cfb is None or cfb <= gates.get("cache_first_byte_max_ms", 30),
              "P7 cache: cache-hit first-byte max %s ≤ %d ms (%d hit; FR-TTS-010)"
              % (_fmt(cfb), gates.get("cache_first_byte_max_ms", 30), m.get("cache_hits", 0))))

    # ── P8: metering + hata normalizasyonu + 8 kHz
    meter_ok = (not gates.get("require_metering", True)) \
        or (m.get("usage_records", 0) == m.get("requests_total", 0))
    err_ok = (not gates.get("require_error_normalized", True)) \
        or (m.get("errors_normalized", 0) == m.get("errors_seen", 0))
    sr_ok = m.get("sample_rate_mismatch", 0) <= gates.get("max_sample_rate_mismatch", 0)
    ten_ok = m.get("cross_tenant", 0) <= gates.get("max_cross_tenant", 0)
    F.append((meter_ok and err_ok and sr_ok and ten_ok,
              "P8 metering+taksonomi+8kHz: usage %d/%d req, err_norm %d/%d, sr_mismatch %d, cross_tenant %d "
              "(FR-BIL-002/FR-TOOL-008/FR-RES-008)"
              % (m.get("usage_records", 0), m.get("requests_total", 0),
                 m.get("errors_normalized", 0), m.get("errors_seen", 0),
                 m.get("sample_rate_mismatch", 0), m.get("cross_tenant", 0))))

    return F


def _fmt(v):
    return "n/a" if v is None else ("%.1f" % v)


# ─────────────────────────────────────────────────────────────────────────────
# parametre + politika çözümleme
# ─────────────────────────────────────────────────────────────────────────────
def _provider_by_id(cfg, pid):
    for p in cfg.get("providers", []):
        if p.get("provider_id") == pid:
            return p
    raise TtsError("bilinmeyen sağlayıcı: %s" % pid)


def _profile_by_name(cfg, name):
    for p in cfg.get("profiles", []):
        if p.get("name") == name:
            return p
    raise TtsError("bilinmeyen profil: %s" % name)


def _resolve_policy(sample):
    pol = {
        "streaming": True,
        "cancel_responsive": True,
        "apply_pronunciation": True,
        "realtime": True,
        "voice_consistency": True,
        "cache_enabled": True,
        "meter": True,
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
    # profilden primary sağlayıcı
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
    except TtsError as ex:
        print("simulate[%s]: %s" % (name, ex))
        return 0 if expect == "fail" else 1

    try:
        m = simulate(sample, provider, policy, gates)
    except TtsError as ex:
        print("simulate[%s]: REDDEDİLDİ — %s" % (name, ex))
        return 0 if expect == "fail" else 1

    F = evaluate(gates, m)
    print("simulate[%s] sağlayıcı=%s senaryo=%s | %d request | first-byte P50/P95=%s/%s ms | "
          "cancel P95=%s ms | %d cache-hit"
          % (name, m["provider_id"], "+".join(m["scenario"]), m["requests_total"],
             _fmt(m["first_byte_p50_ms"]), _fmt(m["first_byte_p95_ms"]),
             _fmt(m["cancel_p95_ms"]), m["cache_hits"]))
    print("  full_buffered=%d | chunk_after_cancel=%d | yapısal=%d (sözlük=%d/eksik=%d) | underrun=%d | "
          "voice_inconsistent=%d | usage=%d/%d | chars=%d"
          % (m["full_buffered"], m["chunk_after_cancel"], m["structured_total"],
             m["pronunciation_applied"], m["unhandled_structured"], m["underrun"],
             m["voice_inconsistent"], m["usage_records"], m["requests_total"], m["chars_total"]))
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
    srs = set(p.get("sample_rates", []))
    return REQUIRED_FEATURES <= feats and 8000 in srs


def validate():
    spec = _load(SPEC_PATH)
    R = []

    _check(R, spec.get("wbs") == "4.2.3", "spec.wbs == 4.2.3")
    _check(R, spec.get("version"), "spec.version mevcut")

    # ── placement (SPI arkası, orchestrator yalnız SPI'ye bağımlı, SPEAK, stream-first)
    pl = spec.get("placement", {})
    _check(R, pl.get("behind_spi") is True and pl.get("orchestrator_depends_on_spi_only") is True,
           "TtsAdapter SPI arkası; orchestrator yalnız SPI'ye bağımlı (ADR-001/SAD §8.1)")
    _check(R, pl.get("turn_state") == "SPEAK", "SPEAK durumunda (SAD §6.1)")
    _check(R, pl.get("stream_first") is True, "P1 akış-önce (stream-first, FR-RES-002)")
    _check(R, pl.get("event_driven") is True and pl.get("non_blocking") is True,
           "olay-tetikli + bloklamaz")
    _check(R, pl.get("barge_in_event_source"), "P9 barge-in olayı 2.2.3/3.1.3'ten tüketilir")

    # ── spi yüzeyi (P5)
    sp = spec.get("spi", {})
    _check(R, "synthesize" in sp.get("methods", []) and "cancel" in sp.get("methods", []),
           "SPI synthesize + cancel (SAD §8.1/API §11.3)")
    _check(R, "pronunciationDictId" in sp.get("voice_profile_fields", []),
           "P3 VoiceProfile.pronunciationDictId (FR-TTS-004)")
    _check(R, "clonedVoiceConsentRef" in sp.get("voice_profile_fields", []),
           "P9 VoiceProfile.clonedVoiceConsentRef (ses klonlama → 4.2.6)")
    _check(R, "sampleRate" in sp.get("tts_options_fields", [])
           and "firstByteTargetMs" in sp.get("tts_options_fields", []),
           "TtsOptions sampleRate + firstByteTargetMs (8 kHz/SAD §20)")
    _check(R, set(sp.get("required_features", [])) == REQUIRED_FEATURES,
           "P5 required_features {streaming, barge_in_cancel, pronunciation_dict}")

    # ── kapılar
    g = spec.get("gates", {})
    _check(R, g.get("sample_rate_hz") == 8000, "P8 sample_rate_hz = 8000 (FR-RES-008)")
    _check(R, g.get("first_byte_p95_ms") == 200, "P1 first_byte_p95_ms = 200 (SAD §20 üst)")
    _check(R, g.get("first_byte_green_ms", 1e9) < g.get("first_byte_p95_ms", 0),
           "P1 yeşil bant < kapı (first-byte)")
    _check(R, g.get("barge_in_cancel_p95_ms") == 200, "P2 barge_in_cancel_p95_ms = 200 (NFR 10.1)")
    _check(R, g.get("barge_in_cancel_green_ms", 1e9) < g.get("barge_in_cancel_p95_ms", 0),
           "P2 yeşil bant < kapı (barge-in)")
    _check(R, g.get("max_full_buffered", -1) == 0, "P1 max_full_buffered = 0 (akış-önce)")
    _check(R, g.get("max_chunk_after_cancel", -1) == 0, "P2 max_chunk_after_cancel = 0")
    _check(R, g.get("max_unhandled_structured", -1) == 0, "P3 max_unhandled_structured = 0")
    _check(R, g.get("max_underrun", -1) == 0, "P4 max_underrun = 0")
    _check(R, g.get("max_voice_inconsistent", -1) == 0, "P6 max_voice_inconsistent = 0")
    _check(R, g.get("max_voice_switch_unmapped", -1) == 0, "P6 max_voice_switch_unmapped = 0")
    _check(R, g.get("max_sample_rate_mismatch", -1) == 0, "P8 max_sample_rate_mismatch = 0")
    _check(R, g.get("max_cross_tenant", -1) == 0, "P7/P8 max_cross_tenant = 0")
    _check(R, g.get("min_providers", 0) >= 2, "P5 min_providers ≥ 2 (ADR-002)")
    _check(R, g.get("require_metering") is True, "P8 require_metering (FR-BIL-002)")
    _check(R, g.get("require_error_normalized") is True, "P8 require_error_normalized (FR-TOOL-008)")
    _check(R, set(g.get("required_features", [])) == REQUIRED_FEATURES,
           "gates required_features SPI ile tutarlı")
    _check(R, g.get("cache_first_byte_max_ms", 1e9) < g.get("first_byte_p95_ms", 0),
           "P7 cache first-byte eşiği < cold first-byte kapısı")

    # ── fallback (P9 sınır)
    fb = spec.get("fallback", {})
    _check(R, fb.get("min_providers", 0) >= 2 and fb.get("equivalent_voice_required") is True,
           "P9 fallback ≥2 sağlayıcı + eşdeğer ses (FR-TTS-008/009)")
    _check(R, fb.get("switching_owned_by") == "4.3.2", "P9 fallback anahtarlama 4.3.2'de")

    # ── metrikler → observability
    me = spec.get("metrics", {})
    emitted = set(me.get("emitted", []))
    _check(R, {"tts_first_byte_ms", "tts_barge_in_cancel_ms", "tts_underrun_total",
               "tts_pronunciation_applied_total", "tts_cache_hit_total"} <= emitted,
           "metrikler: first_byte + barge_in + underrun + pronunciation + cache yayılır")
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
           and mapping.get("invalid_request") == "INVALID_REQUEST"
           and mapping.get("region_mismatch") == "REGION_VIOLATION",
           "P10 timeout→TIMEOUT, 5xx→UNAVAILABLE, invalid→INVALID_REQUEST, bölge→REGION_VIOLATION")

    # ── residency + pii (P8/P10)
    rs = spec.get("residency", {})
    _check(R, rs.get("region_pin_required") is True, "P8/P10 residency region pin (NFR 10.7)")
    _check(R, rs.get("no_log_required") is True
           and set(rs.get("allowed_retention", [])) <= ALLOWED_RETENTION,
           "P8 no-log: data_retention NONE/EPHEMERAL (FR-KB-010)")
    pii = spec.get("pii", {})
    _check(R, pii.get("raw_audio_in_spec_forbidden") is True
           and pii.get("raw_text_in_spec_forbidden") is True
           and pii.get("pii_value_in_spec_forbidden") is True,
           "P10 ham ses/metin/PII değeri spec'te yasak")

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
               "P5 ≥%d SPI-uyumlu sağlayıcı (streaming+barge_in_cancel+pronunciation_dict + 8 kHz)"
               % g.get("min_providers", 2))
        pids = [p.get("provider_id") for p in provs]
        _check(R, len(pids) == len(set(pids)), "config sağlayıcı ID'leri benzersiz")
        for p in provs:
            _check(R, set(p.get("data_retention", "").split()) <= ALLOWED_RETENTION
                   or p.get("data_retention") in ALLOWED_RETENTION,
                   "P8 config %s data_retention NONE/EPHEMERAL" % p.get("provider_id"))
            _check(R, p.get("first_byte_ms", 1e9) <= g.get("first_byte_p95_ms", 0),
                   "P1 config %s first_byte_ms ≤ kapı" % p.get("provider_id"))
            _check(R, p.get("cancel_stop_ms", 1e9) <= g.get("barge_in_cancel_p95_ms", 0),
                   "P2 config %s cancel_stop_ms ≤ kapı" % p.get("provider_id"))
            _check(R, float(p.get("synth_rtf", 1)) < 1.0,
                   "P4 config %s synth_rtf < 1 (ölü hava yok)" % p.get("provider_id"))
        profs = cfg.get("profiles", [])
        _check(R, len(profs) >= 2, "config ≥2 çalıştırma profili")
        for prof in profs:
            _check(R, bool(prof.get("region")), "P10 config %s bölge pini var" % prof.get("name"))
            _check(R, prof.get("primary_provider") in pids and prof.get("fallback_provider") in pids,
                   "P5/P9 config %s primary+fallback geçerli sağlayıcı" % prof.get("name"))
            _check(R, prof.get("primary_provider") != prof.get("fallback_provider"),
                   "P9 config %s primary≠fallback (≥2 sağlayıcı)" % prof.get("name"))
        _check(R, len(cfg.get("voice_equivalence", {})) >= 1,
               "P6 voice_equivalence haritası var (ses tutarlılığı; FR-TTS-009)")

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
    "provider_id": "tts-stream-A", "features": ["streaming", "barge_in_cancel", "pronunciation_dict", "cache"],
    "sample_rates": [8000, 16000], "data_retention": "NONE",
    "first_byte_ms": 120, "cache_first_byte_ms": 12, "cancel_stop_ms": 70, "cancel_stop_ms_degraded": 380,
    "per_char_synth_ms": 5, "synth_rtf": 0.40, "synth_rtf_degraded": 1.30,
}


def _req(t, req_id="r1", voice="A-tr-f-01", chars=60, fields=None, cached=False,
         dict_id="pd-tr-1", sr=8000, provider=None, equiv=None, tenant=None):
    ev = {"kind": "request", "req_id": req_id, "voice_id": voice, "language": "tr", "t": t,
          "text_chars": chars, "fields": fields or [], "sample_rate_hz": sr}
    if cached:
        ev["cached"] = True
    if dict_id:
        ev["pronunciation_dict_id"] = dict_id
    if provider:
        ev["provider"] = provider
    if equiv is not None:
        ev["voice_equivalent"] = equiv
    if tenant:
        ev["tenant_id"] = tenant
    return ev


def _cancel(t, req_id="r1"):
    return {"kind": "cancel", "req_id": req_id, "t": t}


def _end(t, req_id="r1", reason="normal", tax=None):
    ev = {"kind": "end", "req_id": req_id, "t": t, "reason": reason}
    if tax is not None:
        ev["error_taxonomy"] = tax
    return ev


def _run(events, provider=None, **pol_over):
    spec = _load(SPEC_PATH)
    pol = {"streaming": True, "cancel_responsive": True, "apply_pronunciation": True,
           "realtime": True, "voice_consistency": True, "cache_enabled": True, "meter": True,
           "normalize_errors": True, "tenant_isolation": True, "order_guard": True}
    pol.update(pol_over)
    return simulate({"events": events}, provider or PROVIDER_A, pol, spec.get("gates", {}))


def _basic_call(fields=None):
    return [_req(0, fields=fields or [{"type": "general", "chars": 60}]),
            _cancel(40), _end(50, reason="cancelled")]


def selftest():
    spec = _load(SPEC_PATH)
    gates = spec.get("gates", {})
    cases = []

    def case(ok, label):
        cases.append((bool(ok), label))

    # 0) validate iyi spec+config'te geçer
    case(_validate_obj(_load(SPEC_PATH)) == 0, "validate iyi spec+config'te 0 döndürür")

    # ── happy: streaming + pronunciation + cancel + cache (P1–P8) ──────────────────
    fields = [{"type": "number", "chars": 11}, {"type": "currency", "chars": 8},
              {"type": "date", "chars": 10}, {"type": "name", "chars": 12}]
    mh = simulate({"events": [
        _req(0, req_id="r1", chars=60, fields=fields),
        _req(200, req_id="r2", chars=20, cached=True, fields=[{"type": "general", "chars": 20}]),
        _cancel(240, req_id="r2"),
        _end(260, req_id="r1"), _end(270, req_id="r2", reason="cancelled"),
    ]}, PROVIDER_A, _pol(), gates)
    case(mh["first_byte_p95_ms"] <= 200 and mh["full_buffered"] == 0, "happy: streaming first-byte ≤200 + akış-önce (P1)")
    case(mh["cancel_p95_ms"] <= 200 and mh["chunk_after_cancel"] == 0, "happy: cancel ≤200 + kesme sonrası yok (P2)")
    case(mh["structured_total"] == 4 and mh["unhandled_structured"] == 0, "happy: 4 yapısal alan sözlükle (P3)")
    case(mh["underrun"] == 0, "happy: ölü hava yok (P4)")
    case(mh["cache_hits"] == 1 and mh["cache_first_byte_max_ms"] <= 30, "happy: cache-hit first-byte ~0 (P7)")
    case(mh["usage_records"] == mh["requests_total"] == 2, "happy: her synthesize UsageRecord (P8)")
    case(all(ok for ok, _ in evaluate(gates, mh)), "happy tüm kapıları geçer")

    # ── determinizm ───────────────────────────────────────────────────────────────
    md = simulate({"events": [_req(0, req_id="r1", chars=60, fields=fields), _cancel(40), _end(50, reason="cancelled")]},
                  PROVIDER_A, _pol(), gates)
    md2 = simulate({"events": [_req(0, req_id="r1", chars=60, fields=fields), _cancel(40), _end(50, reason="cancelled")]},
                   PROVIDER_A, _pol(), gates)
    case(md == md2, "determinizm: aynı olay-akışı birebir aynı metrik (random yok)")

    # ── ≥2 sağlayıcı: B ile de geçer ───────────────────────────────────────────────
    pb = dict(PROVIDER_A); pb["provider_id"] = "tts-stream-B"; pb["first_byte_ms"] = 95; pb["cancel_stop_ms"] = 55
    mb = _run([_req(0, voice="B-tr-f-07"), _cancel(40), _end(50, reason="cancelled")], provider=pb)
    case(all(ok for ok, _ in evaluate(gates, mb)) and mb["provider_id"] == "tts-stream-B",
         "≥2 sağlayıcı: ikinci adapter (B) de kapıları geçer (FR-TTS-001/ADR-002)")

    # ── degraded-1: streaming kapalı → full buffer → first-byte = full synth (P1 eler) ──
    d1 = _run([_req(0, chars=60), _end(20)], streaming=False)
    case(d1["full_buffered"] >= 1 and d1["first_byte_max_ms"] > 200,
         "degraded(no-stream): tüm yanıt tamponlandı → first-byte 60×5=300ms (FR-RES-002 ihlali)")
    case(not all(ok for ok, _ in evaluate(gates, d1)), "degraded(no-stream) P1 eler")

    # ── degraded-2: cancel yanıtsız → kesme sonrası ses (P2 eler) ───────────────────
    d2 = _run([_req(0), _cancel(40), _end(50, reason="cancelled")], cancel_responsive=False)
    case(d2["chunk_after_cancel"] >= 1 and d2["cancel_max_ms"] > 200,
         "degraded(slow-cancel): cancel→susma 380ms + kesme sonrası ses (talk-over)")
    case(not all(ok for ok, _ in evaluate(gates, d2)), "degraded(slow-cancel) P2 eler")

    # ── degraded-3: pronunciation kapalı → yapısal alan sözlüksüz (P3 eler) ──────────
    d3 = _run([_req(0, fields=[{"type": "number", "chars": 11}, {"type": "currency", "chars": 8}]),
               _end(60)], apply_pronunciation=False)
    case(d3["unhandled_structured"] >= 2 and d3["pronunciation_applied"] == 0,
         "degraded(no-dict): sayı/para alanı sözlüksüz sentezlendi (FR-TTS-004 ihlali)")
    case(not all(ok for ok, _ in evaluate(gates, d3)), "degraded(no-dict) P3 eler")

    # ── degraded-3b: dict_id yok → yapısal alan eksik (P3 eler) ─────────────────────
    d3b = _run([_req(0, dict_id=None, fields=[{"type": "name", "chars": 12}]), _end(60)])
    case(d3b["unhandled_structured"] >= 1, "degraded(no-dict-id): pronunciationDictId yok → yapısal alan eksik")
    case(not all(ok for ok, _ in evaluate(gates, d3b)), "degraded(no-dict-id) P3 eler")

    # ── degraded-4: realtime kapalı → underrun → ölü hava (P4 eler) ──────────────────
    d4 = _run([_req(0, chars=60), _end(60)], realtime=False)
    case(d4["underrun"] >= 1, "degraded(slow-synth): RTF≥1 → tampon boşaldı → ölü hava (FR-RES-009)")
    case(not all(ok for ok, _ in evaluate(gates, d4)), "degraded(slow-synth) P4 eler")

    # ── degraded-5: ses karakteri tutarsız (P6 eler) ────────────────────────────────
    d5 = _run([_req(0, req_id="r1", voice="A-tr-f-01"), _end(50, req_id="r1"),
               _req(100, req_id="r2", voice="A-tr-m-02", provider="tts-stream-B"), _end(150, req_id="r2")])
    case(d5["voice_inconsistent"] >= 1 and d5["voice_switch_unmapped"] >= 1,
         "degraded(voice-drift): voiceId çağrı içinde değişti + haritasız sağlayıcı geçişi (FR-TTS-009)")
    case(not all(ok for ok, _ in evaluate(gates, d5)), "degraded(voice-drift) P6 eler")

    # ── voice fallback eşdeğer-ses ile tutarlı kalır (P6 geçer) ──────────────────────
    d5ok = _run([_req(0, req_id="r1", voice="A-tr-f-01"), _end(50, req_id="r1"),
                 _req(100, req_id="r2", voice="B-tr-f-07", provider="tts-stream-B", equiv=True), _end(150, req_id="r2")])
    case(d5ok["voice_inconsistent"] == 0 and all(ok for ok, _ in evaluate(gates, d5ok)),
         "voice-equivalent: haritalı eşdeğer ses ile tutarlılık korunur (4.3.2 sınır)")

    # ── degraded-6: metering kapalı → UsageRecord eksik (P8 eler) ────────────────────
    d6 = _run([_req(0), _end(50)], meter=False)
    case(d6["usage_records"] == 0 and d6["requests_total"] == 1, "degraded(no-meter): UsageRecord üretilmedi (FR-BIL-002)")
    case(not all(ok for ok, _ in evaluate(gates, d6)), "degraded(no-meter) P8 eler")

    # ── degraded-7: hata normalize edilmedi (P8 eler) ───────────────────────────────
    d7 = _run([_req(0), _end(50, reason="error", tax="raw-provider-503")], normalize_errors=False)
    case(d7["errors_seen"] == 1 and d7["errors_normalized"] == 0,
         "degraded(no-norm): sağlayıcı hatası ErrorTaxonomy'ye çevrilmedi (FR-TOOL-008)")
    case(not all(ok for ok, _ in evaluate(gates, d7)), "degraded(no-norm) P8 eler")
    # hata normalize edilirse geçer
    d7ok = _run([_req(0), _end(50, reason="error", tax="UNAVAILABLE")])
    case(d7ok["errors_normalized"] == 1 and all(ok for ok, _ in evaluate(gates, d7ok)),
         "error-normalized: provider_5xx → UNAVAILABLE (API §11.6) geçer")

    # ── degraded-8: 8 kHz dışı sample rate (P8 eler) ────────────────────────────────
    d8 = _run([_req(0, sr=16000), _end(50)])
    case(d8["sample_rate_mismatch"] >= 1, "degraded(non-8khz): sample_rate≠8000 (FR-RES-008)")
    case(not all(ok for ok, _ in evaluate(gates, d8)), "degraded(non-8khz) P8 eler")

    # ── geçersiz olay reddi (P10) ──────────────────────────────────────────────────
    case(_raises(lambda: _run([_cancel(0), _end(10)])), "P10 bilinmeyen req_id cancel → reddedilir")
    case(_raises(lambda: _run([_req(0, fields=[{"type": "robot", "chars": 5}]), _end(10)])),
         "P10 geçersiz alan tipi → reddedilir")
    case(_raises(lambda: _run([_req(0)])), "P10 'end' olmadan → reddedilir")
    case(_raises(lambda: _run([_req(0), _req(0)])), "P10 tekrar kullanılan req_id → reddedilir")
    case(_raises(lambda: _run([_req(1000), _cancel(0), _end(2000)])), "P10 out-of-order → reddedilir")
    case(_raises(lambda: _run([_req(0), {"kind": "nope", "t": 1}, _end(2)])), "P10 bilinmeyen olay → reddedilir")
    case(_raises(lambda: simulate({"events": []}, PROVIDER_A, _pol(), gates)), "P10 boş olay akışı → reddedilir")
    case(_raises(lambda: _run([_req(0, tenant="t-other"), _end(50)])),
         "P10 cross-tenant (izolasyon açık) → reddedilir")

    # ── validate negatif kapılar ────────────────────────────────────────────────────
    s = json.loads(json.dumps(spec)); s["gates"]["sample_rate_hz"] = 16000
    case(_validate_obj(s) != 0, "P8 sample_rate_hz≠8000 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["first_byte_p95_ms"] = 999
    case(_validate_obj(s) != 0, "P1 first_byte_p95_ms≠200 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_full_buffered"] = 1
    case(_validate_obj(s) != 0, "P1 max_full_buffered>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_chunk_after_cancel"] = 1
    case(_validate_obj(s) != 0, "P2 max_chunk_after_cancel>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_unhandled_structured"] = 1
    case(_validate_obj(s) != 0, "P3 max_unhandled_structured>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_underrun"] = 1
    case(_validate_obj(s) != 0, "P4 max_underrun>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["min_providers"] = 1
    case(_validate_obj(s) != 0, "P5 min_providers<2 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["require_metering"] = False
    case(_validate_obj(s) != 0, "P8 require_metering=false → validate eler")
    s = json.loads(json.dumps(spec)); s["error_taxonomy"]["mapping"]["x"] = "NOPE"
    case(_validate_obj(s) != 0, "P10 taksonomi-dışı → validate eler")
    s = json.loads(json.dumps(spec)); s["pii"]["pii_value_in_spec_forbidden"] = False
    case(_validate_obj(s) != 0, "P10 pii-değer-yasak kapalı → validate eler")
    s = json.loads(json.dumps(spec)); s["spi"]["required_features"] = ["streaming"]
    case(_validate_obj(s) != 0, "P5 eksik required_features → validate eler")
    s = json.loads(json.dumps(spec)); s["residency"]["allowed_retention"] = ["PROVIDER_DEFAULT"]
    case(_validate_obj(s) != 0, "P8 no-log dışı retention → validate eler")
    s = json.loads(json.dumps(spec)); s["metrics"]["secret"] = "api_key: AKIAIOSFODNN7EXAMPLE"
    case(_validate_obj(s) != 0, "P10 literal secret → validate eler")

    passed = sum(1 for ok, _ in cases if ok)
    total = len(cases)
    for ok, label in cases:
        print("  %s %s" % ("✓" if ok else "✗", label))
    print("selftest: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


def _pol(**over):
    pol = {"streaming": True, "cancel_responsive": True, "apply_pronunciation": True,
           "realtime": True, "voice_consistency": True, "cache_enabled": True, "meter": True,
           "normalize_errors": True, "tenant_isolation": True, "order_guard": True}
    pol.update(over)
    return pol


def _raises(fn):
    try:
        fn()
        return False
    except TtsError:
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
    print("""tts-adapter-spec.json beklenen şekli (WBS 4.2.3):
  wbs, version, phase, trace{fr,nfr,sad,adr,api,srs,rtm,vendor_eval,consumes,observability}
  placement{behind_spi=true, orchestrator_depends_on_spi_only=true, turn_state=SPEAK,
            stream_first=true, event_driven=true, non_blocking=true, barge_in_event_source}   (P1,P9)
  spi{methods[synthesize,cancel,...], voice_profile_fields[...pronunciationDictId,clonedVoiceConsentRef],
      tts_options_fields[sampleRate,firstByteTargetMs], required_features[streaming,barge_in_cancel,
      pronunciation_dict]}                                                                       (P3,P5)
  gates{sample_rate_hz=8000, first_byte_p95_ms=200, barge_in_cancel_p95_ms=200,
        cache_first_byte_max_ms, max_full_buffered=0, max_chunk_after_cancel=0,
        max_unhandled_structured=0, max_underrun=0, max_voice_inconsistent=0,
        max_voice_switch_unmapped=0, max_sample_rate_mismatch=0, max_cross_tenant=0,
        min_providers=2, require_metering=true, require_error_normalized=true,
        required_features[...]}                                                                  (P1-P8)
  fallback{min_providers=2, equivalent_voice_required=true, switching_owned_by=4.3.2}           (P9)
  metrics{emitted[], maps_to_observability{}}
  error_taxonomy{mapping→API §11.6}                                                              (P10)
  residency{region_pin_required=true, no_log_required=true, allowed_retention[NONE,EPHEMERAL]}   (P8,P10)
  pii{raw_audio_in_spec_forbidden, raw_text_in_spec_forbidden, pii_value_in_spec_forbidden}      (P10)
  invariants[≥10]{id, desc, trace}

config/tts-adapter-profiles.json: providers[]{provider_id, languages, sample_rates(⊇8000), features
  (⊇streaming,barge_in_cancel,pronunciation_dict), regions, data_retention(NONE/EPHEMERAL),
  first_byte_ms, cache_first_byte_ms, cancel_stop_ms, cancel_stop_ms_degraded, per_char_synth_ms,
  synth_rtf, synth_rtf_degraded}; profiles[]{name, primary_provider, fallback_provider,
  first_byte_target_ms, region}; voice_equivalence{}

simulate sample: {name, provider | provider_obj | profile, tenant_id?, expect, expected?{metrik:değer},
  policy?{streaming, cancel_responsive, apply_pronunciation, realtime, voice_consistency,
  cache_enabled, meter, normalize_errors, tenant_isolation},
  events[{kind:'request', req_id, voice_id, language, t, text_chars, fields[{type,chars}],
          sample_rate_hz?, pronunciation_dict_id?, cached?, provider?, voice_equivalent?} |
         {kind:'cancel', req_id, t} | {kind:'end', req_id, t, reason, error_taxonomy?}]}
  — request → (cancel?) → end; son olay 'end' olmalı; field.type ∈ {general,number,date,currency,name}

komutlar: validate | simulate <sample.json> | selftest | schema""")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if cmd == "validate":
        return validate()
    if cmd == "simulate":
        if len(sys.argv) < 3:
            print("kullanım: tts_adapter_probe.py simulate <sample.json>")
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
