#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
telephony_adapter_probe.py — WBS 4.2.5 Telephony adapter #1 + #2 (SIP trunk + BYOC)

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only statik + davranış kapısı. `runtime/`,
`telephony/`, `adapters/tts/` ve `adapters/llm/` modül disipliniyle aynı; burada iki SOMUT
TelephonyAdapter implementasyonunu (≥2/kategori — FR-TEL-002) ortak SPI (SAD §8.1 / API §11.5)
arkasına bağlayan DETERMİNİSTİK bir referans adapter sürücüsü (olay-tetikli, sanal saat, random YOK;
gerçek SIP/RTP yığını YOK — sağlayıcı kurulum gecikme profili + çağrı kontrol MODELİ). İki somut adapter:
(#1) managed CPaaS (Media Streams WS, M1 / 2.1.3) + (#2) BYOC SIP trunk (ham SIP+RTP, M2 / 2.1.4).
FR-TEL-002: SIP trunk + BYOC desteği — iki taşıma modu tek SPI arkasında değiştirilebilir (P1).

SPI yüzeyi (API §11.5): dial (outbound — FR-TEL-001/002), answer (inbound), transfer cold/warm/whisper
(SIP REFER — FR-TEL-007), sendDtmf (RFC 2833 / SIP INFO — FR-TEL-006), hangup (neden kodu — FR-TEL-012),
mediaStream (RTP/SRTP 8kHz — FR-RES-008/NFR 10.6), on(ANSWERED/HANGUP/DTMF/AMD — FR-TEL-010).

HARD kapılar: P1 taşıma-nötr normalize (contract_divergence=0); P2 E.164 + caller-ID havuzu; P3 transfer
cold/warm/whisper; P4 DTMF + AMD olayları yüzeye çıkar; P5 ≥2 SPI-uyumlu sağlayıcı/trunk; P6 hangup
standart neden kodu; P7 medya 8kHz + SRTP/TLS + kurulum gecikme bütçesi; P8 metering (SECONDS) +
residency + hata normalizasyonu.

KAPSAM AYRIMI: SBC 2.1.1; managed çerçeve 2.1.3; BYOC SIP/RTP 2.1.4; E.164/caller-ID MOTORU 2.1.5
(bu motor biçim UYGUNLUĞUNU doğrular, normalize MOTORUNU değil); DTMF MOTORU 2.1.6; neden kodu
TAKSONOMİSİ 2.1.7 (hangup neden kodu BURADAN — bu motor eşlemeyi TÜKETİR); retry 2.1.8; AMD MOTORU 2.1.9
(bu motor AMD OLAYINI yüzeye çıkarır); RTP/jitter 2.2.1; codec 2.2.2; edge VAD/barge-in 2.2.3; handoff
8.x; outbound consent 10.2; ortak yetenekler 4.1.2/4.1.6; metering motoru 4.1.3; residency 4.1.4;
telefoni fallback ANAHTARLAMA 4.3.x (≥2 SPI-uyum + ErrorTaxonomy varlığı doğrulanır); telekom SEÇİMİ
0.2.1/0.2.6/0.3.x.

Komutlar:
  validate              telephony-adapter-spec.json'ı invariant'lara (P1–P10) + config sağlayıcı/profillerine doğrular.
  simulate <sample>     Deterministik TelephonyAdapter — çağrı-kontrol olay akışı (dial/answer/media_ready/
                        dtmf/amd/transfer/hangup) → normalize/setup/transfer/dtmf/amd/reason/metering
                        metrikleri → HARD kapılar (P1–P8) → çıkış kodu.
  selftest              İyi/kötü spec+sample ile kapıların doğru tetiklendiğini kanıtlar.
  schema                Beklenen spec şeklini özetler.

Sunucu/credential GEREKMEZ. simulate gerçek SIP/RTP yerine sağlayıcı kurulum gecikme profili (config
providers) + çağrı kontrol MODELİ kullanır (canlı sistemde Go/Rust async runtime + gerçek TelephonyAdapter
+ SBC/trunk, ADR-003/SAD §6.3/§8.1). Ham TELEFON NUMARASI DEĞERİ, çağrı medyası veya PII DEĞERİ YOK —
yalnız sağlayıcı/trunk kimliği + gecikme/çağrı SAYILARI + mod/yön/transfer/neden-kodu kimlikleri +
biçim UYGUNLUK bayrakları + sanal zaman.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "telephony-adapter-spec.json")
PROFILES_CFG = os.path.join(HERE, "config", "telephony-adapter-profiles.json")

ERROR_TAXONOMY = {
    "TIMEOUT", "RATE_LIMITED", "UNAVAILABLE", "AUTH",
    "INVALID_REQUEST", "CONTENT_FILTERED", "QUOTA_EXCEEDED", "REGION_VIOLATION",
}
SECRET_RE = re.compile(
    r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer)\b\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}"
)
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")

REQUIRED_FEATURES = {"dtmf", "amd", "transfer"}
TRANSFER_MODES = {"COLD", "WARM", "WHISPER"}
TRANSFER_TARGETS = {"QUEUE", "SKILL", "AGENT", "NUMBER"}
DTMF_TRANSPORTS = {"rfc2833", "sip_info"}
ALLOWED_RETENTION = {"NONE", "EPHEMERAL"}
DIRECTIONS = {"inbound", "outbound"}
END_REASONS = {"normal", "error"}
SAMPLE_RATE_HZ = 8000


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


class TelephonyError(Exception):
    """Geçersiz/desteklenmeyen olay veya yetki/izolasyon ihlali — sessizce kabul yok, reddet (P10)."""


# ─────────────────────────────────────────────────────────────────────────────
# TelephonyAdapter referans sürücüsü (deterministik)
# ─────────────────────────────────────────────────────────────────────────────
class TelephonyAdapterRuntime:
    """SAD §8.1 / API §11.5 TelephonyAdapter sürücüsü. Çağrı-kontrol olay akışını işler:
        dial|answer → (media_ready | dtmf | amd | transfer)* → hangup
    Her olay için sağlayıcı kurulum gecikme PROFİLİNDEN (config providers) taşıma-nötr normalize,
    kurulum gecikmesi, E.164/caller-ID uygunluğu, transfer mode/hedef, DTMF/AMD olay yüzeye çıkışı,
    hangup neden kodu, medya 8kHz+SRTP, residency ve usage metering DETERMİNİSTİK hesaplanır
    (random YOK; sanal saat = event.t).

    Olaylar:
      {kind:'dial',       call_id, t, direction='outbound', e164_valid?, caller_id_pool?, secure_transport?,
                          sample_rate_hz?, region_pinned?, trunk?, tenant_id?}
      {kind:'answer',     call_id, t, direction='inbound', e164_valid?, secure_transport?, sample_rate_hz?,
                          region_pinned?, tenant_id?}
      {kind:'media_ready',call_id, t}                                  # medya yolu kuruldu → setup gecikmesi
      {kind:'dtmf',       call_id, t, transport∈{rfc2833,sip_info}}
      {kind:'amd',        call_id, t, result∈{human,machine,unknown}}
      {kind:'transfer',   call_id, t, mode∈{COLD,WARM,WHISPER}, target_type∈{QUEUE,SKILL,AGENT,NUMBER}, ref?}
      {kind:'hangup',     call_id, t, reason_code, reason∈{normal,error}?, error_taxonomy?}
    """

    def __init__(self, provider, policy, gates, error_map=None, failure_reasons=None, tenant_id="t-self"):
        self.pv = provider
        self.pol = policy
        self.g = gates
        self.error_map = error_map or {}
        self.failure_reasons = set(failure_reasons or [])
        self.tenant_id = tenant_id

        self.calls = {}                 # call_id -> state
        self._last_t = None

        # ölçüm dizileri
        self.setup_ms = []              # çağrı kurulum/post-dial gecikme (P7)

        # sayaçlar / metrikler
        self.calls_total = 0
        self.inbound_total = 0
        self.outbound_total = 0
        self.contract_divergence = 0    # taşıma modu orchestrator'a sızdı (P1 ihlali)
        self.invalid_e164 = 0           # E.164 dışı numara (P2)
        self.missing_caller_id_pool = 0  # outbound caller-ID havuzu yok (P2)
        self.transfers_ok = 0           # cold/warm/whisper transfer (P3)
        self.unsupported_transfer = 0   # geçersiz mode/hedef veya desteklenmez (P3 ihlali)
        self.dtmf_events = 0            # DTMF olayı yüzeye çıktı (P4)
        self.amd_events = 0            # AMD olayı yüzeye çıktı (P4)
        self.dropped_event = 0         # DTMF/AMD olayı yutuldu (P4 ihlali)
        self.missing_reason_code = 0   # hangup neden kodu yok (P6)
        self.insecure_media = 0        # düz-metin SIP/RTP (P7 ihlali — NFR 10.6)
        self.non_8khz = 0              # 8kHz dışı medya (P7 ihlali — FR-RES-008)
        self.region_violation = 0      # bölgesel pin yok (P8 — NFR 10.7)
        self.cross_tenant = 0
        self.usage_records = 0         # UsageRecord/CDR sayısı (P8/FR-BIL-002)
        self.call_seconds_total = 0    # toplam çağrı süresi (SECONDS)
        self.transfer_total = 0
        self.errors_seen = 0
        self.errors_normalized = 0
        self.ended = 0
        self.modes_seen = set()        # managed/byoc taşıma modu kapsanması
        self.reason_codes = []         # hangup neden kodları (taksonomi 2.1.7)

    def _check_time(self, t):
        if not isinstance(t, (int, float)):
            raise TelephonyError("zaman damgası sayısal değil → INVALID_REQUEST")
        if self._last_t is not None and t < self._last_t:
            if self.pol.get("order_guard", True):
                raise TelephonyError("out-of-order olay (t geriye) reddedildi → INVALID_REQUEST")
        self._last_t = max(self._last_t if self._last_t is not None else t, t)

    def _check_scope(self, ev):
        tt = ev.get("tenant_id", self.tenant_id)
        if tt != self.tenant_id:
            self.cross_tenant += 1
            if self.pol.get("tenant_isolation", True):
                raise TelephonyError("cross-tenant erişim reddedildi → AUTH")

    def _get_call(self, ev, op):
        call_id = ev.get("call_id")
        if not isinstance(call_id, str) or not call_id:
            raise TelephonyError("call_id yok/boş (%s) → INVALID_REQUEST" % op)
        call = self.calls.get(call_id)
        if call is None:
            raise TelephonyError("bilinmeyen call_id %s (%s) → INVALID_REQUEST" % (call_id, op))
        if call["ended"]:
            raise TelephonyError("çağrı zaten bitti %s (%s) → INVALID_REQUEST" % (call_id, op))
        return call

    # ── dial/answer: çağrı başlatma (P1/P2/P7/P8) ─────────────────────────────
    def _start_call(self, ev, direction):
        self._check_time(ev.get("t"))
        self._check_scope(ev)
        call_id = ev.get("call_id")
        if not isinstance(call_id, str) or not call_id:
            raise TelephonyError("call_id yok/boş → INVALID_REQUEST")
        if call_id in self.calls:
            raise TelephonyError("call_id tekrar kullanıldı → INVALID_REQUEST")

        self.calls_total += 1
        if direction == "inbound":
            self.inbound_total += 1
        else:
            self.outbound_total += 1

        # ── P1: taşıma-nötr normalize (managed/byoc → tek SPI sözleşmesi)
        self.modes_seen.add(self.pv.get("mode", "managed"))
        if not self.pol.get("normalize_contract", True):
            self.contract_divergence += 1

        # ── P2: E.164 biçimi + caller-ID havuzu (outbound)
        e164_ok = ev.get("e164_valid", True) and self.pol.get("validate_e164", True)
        if not e164_ok:
            self.invalid_e164 += 1
        if direction == "outbound" and self.pol.get("require_caller_id_pool", True):
            if not ev.get("caller_id_pool"):
                self.missing_caller_id_pool += 1

        # ── P7: güvenli taşıma + 8kHz native
        secure = ev.get("secure_transport", True) and self.pol.get("require_secure_transport", True)
        if not secure:
            self.insecure_media += 1
        sr = ev.get("sample_rate_hz", SAMPLE_RATE_HZ)
        if sr != SAMPLE_RATE_HZ:
            self.non_8khz += 1

        # ── P8: residency (home-region pin)
        region_pinned = ev.get("region_pinned", True) and self.pol.get("region_pin", True)
        if not region_pinned:
            self.region_violation += 1

        self.calls[call_id] = {
            "start_t": ev.get("t"), "direction": direction, "ended": False, "media_ready": False,
        }

    def dial(self, ev):
        d = ev.get("direction", "outbound")
        if d not in DIRECTIONS:
            raise TelephonyError("geçersiz yön: %r → INVALID_REQUEST" % d)
        self._start_call(ev, d)

    def answer(self, ev):
        d = ev.get("direction", "inbound")
        if d not in DIRECTIONS:
            raise TelephonyError("geçersiz yön: %r → INVALID_REQUEST" % d)
        self._start_call(ev, d)

    # ── media_ready: medya yolu kuruldu → kurulum gecikmesi (P7) ───────────────
    def media_ready(self, ev):
        self._check_time(ev.get("t"))
        self._check_scope(ev)
        call = self._get_call(ev, "media_ready")
        if call["media_ready"]:
            raise TelephonyError("medya zaten kurulu → INVALID_REQUEST")
        call["media_ready"] = True
        if self.pol.get("fast_setup", True):
            setup = float(self.pv.get("media_setup_ms", 720))
        else:
            # BOZUK: yavaş kurulum (SBC/trunk müzakeresi takılı) → post-dial gecikme bütçe aşar
            setup = float(self.pv.get("media_setup_ms_degraded", 2600))
        self.setup_ms.append(setup)

    # ── dtmf / amd: olaylar on(...) ile yüzeye çıkar (P4) ──────────────────────
    def dtmf(self, ev):
        self._check_time(ev.get("t"))
        self._check_scope(ev)
        self._get_call(ev, "dtmf")
        transport = ev.get("transport", "rfc2833")
        if transport not in DTMF_TRANSPORTS:
            raise TelephonyError("geçersiz DTMF taşıma: %r → INVALID_REQUEST" % transport)
        if self.pol.get("surface_events", True):
            self.dtmf_events += 1
        else:
            self.dropped_event += 1

    def amd(self, ev):
        self._check_time(ev.get("t"))
        self._check_scope(ev)
        self._get_call(ev, "amd")
        result = ev.get("result", "human")
        if result not in {"human", "machine", "unknown"}:
            raise TelephonyError("geçersiz AMD sonucu: %r → INVALID_REQUEST" % result)
        if self.pol.get("surface_events", True):
            self.amd_events += 1
        else:
            self.dropped_event += 1

    # ── transfer: cold/warm/whisper (P3) ──────────────────────────────────────
    def transfer(self, ev):
        self._check_time(ev.get("t"))
        self._check_scope(ev)
        self._get_call(ev, "transfer")
        self.transfer_total += 1
        mode = ev.get("mode")
        target_type = ev.get("target_type")
        supported = self.pol.get("support_transfer", True) \
            and mode in TRANSFER_MODES and target_type in TRANSFER_TARGETS \
            and mode in set(self.pv.get("transfer_modes", []))
        if supported:
            self.transfers_ok += 1
        else:
            self.unsupported_transfer += 1

    # ── hangup: neden kodu + metering + hata normalizasyonu (P6/P8) ────────────
    def hangup(self, ev):
        self._check_time(ev.get("t"))
        self._check_scope(ev)
        call = self._get_call(ev, "hangup")
        reason_code = ev.get("reason_code")
        if not reason_code or not self.pol.get("require_reason_code", True):
            self.missing_reason_code += 1
        else:
            self.reason_codes.append(reason_code)

        # ── P8: usage metering (CDR, unit=SECONDS) (FR-BIL-002)
        if self.pol.get("meter", True):
            self.usage_records += 1
            dur = ev.get("t", 0) - call.get("start_t", 0)
            self.call_seconds_total += max(0, int(round(dur / 1000.0)))

        # ── P8: hata normalizasyonu (telekom/SIP hatası → ErrorTaxonomy) (FR-TOOL-008)
        reason = ev.get("reason", "normal")
        if reason not in END_REASONS:
            raise TelephonyError("geçersiz bitiş nedeni: %r → INVALID_REQUEST" % reason)
        is_failure = (reason == "error") or (reason_code in self.failure_reasons)
        if is_failure:
            self.errors_seen += 1
            tax = ev.get("error_taxonomy")
            if self.pol.get("normalize_errors", True) and tax in ERROR_TAXONOMY:
                self.errors_normalized += 1

        call["ended"] = True
        self.ended += 1

    def metrics(self):
        scenario = []
        scenario.append("managed+byoc" if len(self.modes_seen) >= 2 else ("+".join(sorted(self.modes_seen)) or "no-call"))
        if self.contract_divergence:
            scenario.append("contract-divergence")
        if self.transfers_ok:
            scenario.append("transfer")
        if self.dtmf_events:
            scenario.append("dtmf")
        if self.amd_events:
            scenario.append("amd")
        if self.invalid_e164 or self.missing_caller_id_pool:
            scenario.append("numbering-violation")
        if self.insecure_media or self.non_8khz:
            scenario.append("media-violation")
        if self.region_violation:
            scenario.append("residency-violation")
        if self.errors_seen:
            scenario.append("call-failure")
        if len(scenario) == 1 and scenario[0] in ("managed", "byoc", "managed+byoc"):
            scenario.append("happy")
        return {
            "provider_id": self.pv.get("provider_id"),
            "mode": self.pv.get("mode"),
            "modes_seen": sorted(self.modes_seen),
            "calls_total": self.calls_total,
            "inbound_total": self.inbound_total,
            "outbound_total": self.outbound_total,
            "setup_p95_ms": _percentile(self.setup_ms, 95),
            "setup_p50_ms": _percentile(self.setup_ms, 50),
            "setup_max_ms": max(self.setup_ms) if self.setup_ms else None,
            "contract_divergence": self.contract_divergence,
            "invalid_e164": self.invalid_e164,
            "missing_caller_id_pool": self.missing_caller_id_pool,
            "transfers_ok": self.transfers_ok,
            "unsupported_transfer": self.unsupported_transfer,
            "transfer_total": self.transfer_total,
            "dtmf_events": self.dtmf_events,
            "amd_events": self.amd_events,
            "dropped_event": self.dropped_event,
            "missing_reason_code": self.missing_reason_code,
            "insecure_media": self.insecure_media,
            "non_8khz": self.non_8khz,
            "region_violation": self.region_violation,
            "cross_tenant": self.cross_tenant,
            "usage_records": self.usage_records,
            "call_seconds_total": self.call_seconds_total,
            "errors_seen": self.errors_seen,
            "errors_normalized": self.errors_normalized,
            "ended": self.ended,
            "reason_codes": self.reason_codes,
            "scenario": scenario,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Tam simülasyon (bir sample)
# ─────────────────────────────────────────────────────────────────────────────
def simulate(sample, provider, policy, gates, error_map=None, failure_reasons=None):
    events = sample.get("events")
    if events is None or not isinstance(events, list) or not events:
        raise TelephonyError("boş/geçersiz olay akışı → INVALID_REQUEST")
    rt = TelephonyAdapterRuntime(provider, policy, gates, error_map=error_map,
                                 failure_reasons=failure_reasons,
                                 tenant_id=sample.get("tenant_id", "t-self"))
    saw_hangup = False
    for ev in events:
        if not isinstance(ev, dict):
            raise TelephonyError("olay sözlük değil → INVALID_REQUEST")
        kind = ev.get("kind")
        if kind == "dial":
            rt.dial(ev)
        elif kind == "answer":
            rt.answer(ev)
        elif kind == "media_ready":
            rt.media_ready(ev)
        elif kind == "dtmf":
            rt.dtmf(ev)
        elif kind == "amd":
            rt.amd(ev)
        elif kind == "transfer":
            rt.transfer(ev)
        elif kind == "hangup":
            rt.hangup(ev)
            saw_hangup = True
        else:
            raise TelephonyError("bilinmeyen olay tipi: %r → INVALID_REQUEST" % kind)
    if not saw_hangup:
        raise TelephonyError("olay akışında 'hangup' yok → INVALID_REQUEST")
    return rt.metrics()


def evaluate(gates, m):
    """Metrikleri HARD kapılara (P1–P8 davranışsal) karşı değerlendirir. Döner findings[(ok, label)]."""
    F = []

    # ── P1: taşıma-nötr normalize
    F.append((m.get("contract_divergence", 0) <= gates.get("max_contract_divergence", 0),
              "P1 normalize: contract_divergence %d ≤ %d (managed/BYOC → tek SPI sözleşmesi; modlar=%s; ADR-001/SAD §11.5)"
              % (m.get("contract_divergence", 0), gates.get("max_contract_divergence", 0),
                 ",".join(m.get("modes_seen", [])) or "yok")))

    # ── P2: E.164 + caller-ID havuzu
    F.append((m.get("invalid_e164", 0) <= gates.get("max_invalid_e164", 0)
              and m.get("missing_caller_id_pool", 0) <= gates.get("max_missing_caller_id_pool", 0),
              "P2 numbering: invalid_e164 %d + missing_caller_id_pool %d (outbound %d) ≤ 0 (FR-TEL-004/005)"
              % (m.get("invalid_e164", 0), m.get("missing_caller_id_pool", 0), m.get("outbound_total", 0))))

    # ── P3: transfer cold/warm/whisper
    F.append((m.get("unsupported_transfer", 0) <= gates.get("max_unsupported_transfer", 0),
              "P3 transfer: unsupported_transfer %d ≤ %d (cold/warm/whisper; %d transfer→%d ok; FR-TEL-007)"
              % (m.get("unsupported_transfer", 0), gates.get("max_unsupported_transfer", 0),
                 m.get("transfer_total", 0), m.get("transfers_ok", 0))))

    # ── P4: DTMF + AMD olayları yüzeye çıkar
    F.append((m.get("dropped_event", 0) <= gates.get("max_dropped_event", 0),
              "P4 olaylar: dropped_event %d ≤ %d (DTMF %d + AMD %d yüzeye çıktı; FR-TEL-006/010)"
              % (m.get("dropped_event", 0), gates.get("max_dropped_event", 0),
                 m.get("dtmf_events", 0), m.get("amd_events", 0))))

    # ── P6: hangup neden kodu
    F.append((m.get("missing_reason_code", 0) <= gates.get("max_missing_reason_code", 0),
              "P6 neden kodu: missing_reason_code %d ≤ %d (standart kod 2.1.7; FR-TEL-012)"
              % (m.get("missing_reason_code", 0), gates.get("max_missing_reason_code", 0))))

    # ── P7: medya 8kHz + SRTP + kurulum gecikme bütçesi
    su95 = m.get("setup_p95_ms")
    p7_ok = (su95 is None or su95 <= gates.get("setup_p95_ms", 2000)) \
        and m.get("insecure_media", 0) <= gates.get("max_insecure_media", 0) \
        and m.get("non_8khz", 0) <= gates.get("max_non_8khz", 0)
    F.append((p7_ok,
              "P7 medya: setup P95 %s ≤ %d ms + insecure_media %d + non_8khz %d ≤ 0 (8kHz/SRTP; FR-RES-008/NFR 10.6)"
              % (_fmt(su95), gates.get("setup_p95_ms", 2000),
                 m.get("insecure_media", 0), m.get("non_8khz", 0))))

    # ── P8: metering + residency + hata normalizasyonu
    meter_ok = (not gates.get("require_metering", True)) \
        or (m.get("usage_records", 0) == m.get("ended", 0) and m.get("ended", 0) > 0)
    err_ok = (not gates.get("require_error_normalized", True)) \
        or (m.get("errors_normalized", 0) == m.get("errors_seen", 0))
    reg_ok = m.get("region_violation", 0) <= gates.get("max_region_violation", 0)
    ten_ok = m.get("cross_tenant", 0) <= gates.get("max_cross_tenant", 0)
    F.append((meter_ok and err_ok and reg_ok and ten_ok,
              "P8 metering+residency+taksonomi: usage %d/%d (CDR=%ds), region_viol %d, err_norm %d/%d, cross_tenant %d "
              "(FR-BIL-002/NFR 10.7/FR-TOOL-008)"
              % (m.get("usage_records", 0), m.get("ended", 0), m.get("call_seconds_total", 0),
                 m.get("region_violation", 0), m.get("errors_normalized", 0), m.get("errors_seen", 0),
                 m.get("cross_tenant", 0))))

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
    raise TelephonyError("bilinmeyen sağlayıcı: %s" % pid)


def _profile_by_name(cfg, name):
    for p in cfg.get("profiles", []):
        if p.get("name") == name:
            return p
    raise TelephonyError("bilinmeyen profil: %s" % name)


def _resolve_policy(sample):
    pol = {
        "normalize_contract": True,
        "validate_e164": True,
        "require_caller_id_pool": True,
        "support_transfer": True,
        "surface_events": True,
        "require_reason_code": True,
        "require_secure_transport": True,
        "region_pin": True,
        "fast_setup": True,
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
    prof = _profile_by_name(cfg, sample.get("profile", cfg.get("default_profile")))
    return _provider_by_id(cfg, prof.get("primary_provider"))


def _spec_failure_reasons(spec):
    return set(spec.get("error_taxonomy", {}).get("failure_reason_codes", []))


def simulate_cmd(sample_path):
    spec = _load(SPEC_PATH)
    sample = _load(sample_path)
    name = sample.get("name", os.path.basename(sample_path))
    expect = sample.get("expect", "pass")
    gates = spec.get("gates", {})
    policy = _resolve_policy(sample)
    failure_reasons = _spec_failure_reasons(spec)

    try:
        cfg = _load(PROFILES_CFG)
        provider = _resolve_provider(sample, cfg)
    except TelephonyError as ex:
        print("simulate[%s]: %s" % (name, ex))
        return 0 if expect == "fail" else 1

    try:
        m = simulate(sample, provider, policy, gates, failure_reasons=failure_reasons)
    except TelephonyError as ex:
        print("simulate[%s]: REDDEDİLDİ — %s" % (name, ex))
        return 0 if expect == "fail" else 1

    F = evaluate(gates, m)
    print("simulate[%s] sağlayıcı=%s mod=%s senaryo=%s | %d çağrı (in %d/out %d) | setup P50/P95=%s/%s ms | "
          "%d transfer→%d ok | DTMF %d/AMD %d"
          % (name, m["provider_id"], m["mode"], "+".join(m["scenario"]), m["calls_total"],
             m["inbound_total"], m["outbound_total"], _fmt(m["setup_p50_ms"]), _fmt(m["setup_p95_ms"]),
             m["transfer_total"], m["transfers_ok"], m["dtmf_events"], m["amd_events"]))
    print("  contract_div=%d | invalid_e164=%d | missing_pool=%d | unsupported_xfer=%d | dropped_evt=%d | "
          "missing_reason=%d | insecure_media=%d | non_8khz=%d | region_viol=%d | usage=%d/%d (CDR %ds)"
          % (m["contract_divergence"], m["invalid_e164"], m["missing_caller_id_pool"],
             m["unsupported_transfer"], m["dropped_event"], m["missing_reason_code"],
             m["insecure_media"], m["non_8khz"], m["region_violation"],
             m["usage_records"], m["ended"], m["call_seconds_total"]))
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
    modes = set(p.get("transfer_modes", []))
    return REQUIRED_FEATURES <= feats and TRANSFER_MODES <= modes \
        and SAMPLE_RATE_HZ in p.get("sample_rates", []) and p.get("secure_transport") is True \
        and DIRECTIONS <= set(p.get("directions", []))


def validate():
    spec = _load(SPEC_PATH)
    R = []

    _check(R, spec.get("wbs") == "4.2.5", "spec.wbs == 4.2.5")
    _check(R, spec.get("version"), "spec.version mevcut")

    # ── placement (SPI arkası, orchestrator yalnız SPI'ye bağımlı, taşıma-nötr)
    pl = spec.get("placement", {})
    _check(R, pl.get("behind_spi") is True and pl.get("orchestrator_depends_on_spi_only") is True,
           "TelephonyAdapter SPI arkası; orchestrator yalnız SPI'ye bağımlı (ADR-001/SAD §8.1)")
    _check(R, pl.get("scope") == "call_lifecycle", "çağrı yaşam döngüsü kapsamı")
    _check(R, pl.get("transport_neutral") is True, "P1 taşıma-nötr (managed/BYOC tek SPI)")
    _check(R, set(pl.get("transport_modes", [])) == {"managed_cpaas", "byoc_sip_trunk"},
           "P1/P5 iki taşıma modu: managed CPaaS + BYOC SIP trunk (FR-TEL-002)")
    _check(R, pl.get("event_driven") is True and pl.get("non_blocking") is True,
           "olay-tetikli + bloklamaz")

    # ── spi yüzeyi (P1/P3/P4/P5/P6)
    sp = spec.get("spi", {})
    methods = set(sp.get("methods", []))
    _check(R, {"dial", "answer", "transfer", "sendDtmf", "hangup", "mediaStream", "on"} <= methods,
           "SPI dial/answer/transfer/sendDtmf/hangup/mediaStream/on (SAD §8.1/API §11.5)")
    _check(R, set(sp.get("transfer_modes", [])) == TRANSFER_MODES,
           "P3 transfer_modes {COLD,WARM,WHISPER} (FR-TEL-007)")
    _check(R, set(sp.get("transfer_target_types", [])) == TRANSFER_TARGETS,
           "P3 transfer target tipleri {QUEUE,SKILL,AGENT,NUMBER} (FR-HND-003)")
    _check(R, set(sp.get("events", [])) >= {"ANSWERED", "HANGUP", "DTMF", "AMD"},
           "P4 on(...) olayları {ANSWERED,HANGUP,DTMF,AMD} (FR-TEL-010)")
    _check(R, set(sp.get("dtmf_transports", [])) == DTMF_TRANSPORTS,
           "P4 DTMF taşıma {rfc2833,sip_info} (FR-TEL-006)")
    _check(R, set(sp.get("required_features", [])) == REQUIRED_FEATURES,
           "P5 required_features {dtmf, amd, transfer}")
    _check(R, sp.get("required_sample_rate_hz") == SAMPLE_RATE_HZ, "P7 8kHz native (FR-RES-008)")
    _check(R, "callerIdPool" in sp.get("dial_request_fields", []),
           "P2 DialRequest callerIdPool (FR-TEL-005)")

    # ── kapılar
    g = spec.get("gates", {})
    _check(R, g.get("setup_p95_ms", 0) > 0, "P7 setup_p95_ms > 0 (kurulum/post-dial bütçesi)")
    _check(R, g.get("setup_green_ms", 1e9) < g.get("setup_p95_ms", 0),
           "P7 yeşil bant < kapı (setup)")
    _check(R, g.get("max_contract_divergence", -1) == 0, "P1 max_contract_divergence = 0")
    _check(R, g.get("max_invalid_e164", -1) == 0, "P2 max_invalid_e164 = 0 (FR-TEL-004)")
    _check(R, g.get("max_missing_caller_id_pool", -1) == 0, "P2 max_missing_caller_id_pool = 0 (FR-TEL-005)")
    _check(R, g.get("max_unsupported_transfer", -1) == 0, "P3 max_unsupported_transfer = 0 (FR-TEL-007)")
    _check(R, g.get("max_dropped_event", -1) == 0, "P4 max_dropped_event = 0 (FR-TEL-006/010)")
    _check(R, g.get("max_missing_reason_code", -1) == 0, "P6 max_missing_reason_code = 0 (FR-TEL-012)")
    _check(R, g.get("max_insecure_media", -1) == 0, "P7 max_insecure_media = 0 (NFR 10.6)")
    _check(R, g.get("max_non_8khz", -1) == 0, "P7 max_non_8khz = 0 (FR-RES-008)")
    _check(R, g.get("max_region_violation", -1) == 0, "P8 max_region_violation = 0 (NFR 10.7)")
    _check(R, g.get("max_cross_tenant", -1) == 0, "P8 max_cross_tenant = 0 (FR-TEN-002)")
    _check(R, g.get("min_providers", 0) >= 2, "P5 min_providers ≥ 2 (ADR-002; managed+BYOC)")
    _check(R, g.get("require_metering") is True, "P8 require_metering (FR-BIL-002)")
    _check(R, g.get("require_error_normalized") is True, "P8 require_error_normalized (FR-TOOL-008)")
    _check(R, set(g.get("required_features", [])) == REQUIRED_FEATURES,
           "gates required_features SPI ile tutarlı")
    _check(R, set(g.get("required_transfer_modes", [])) == TRANSFER_MODES,
           "gates required_transfer_modes {COLD,WARM,WHISPER}")
    _check(R, g.get("required_sample_rate_hz") == SAMPLE_RATE_HZ, "gates 8kHz tutarlı")

    # ── fallback (P9 sınır)
    fb = spec.get("fallback", {})
    _check(R, fb.get("min_providers", 0) >= 2 and fb.get("secondary_trunk_on_failure") is True,
           "P9 fallback ≥2 sağlayıcı/trunk + secondary (FR-TEL-002)")
    _check(R, fb.get("switching_owned_by") == "4.3.x", "P9 fallback anahtarlama 4.3.x'te")

    # ── metrikler → observability
    me = spec.get("metrics", {})
    emitted = set(me.get("emitted", []))
    _check(R, {"telephony_call_setup_ms", "telephony_transfer_total", "telephony_dtmf_total",
               "telephony_amd_total", "telephony_call_seconds_total", "telephony_hangup_total"} <= emitted,
           "metrikler: setup + transfer + dtmf + amd + call_seconds + hangup yayılır")
    _check(R, len(me.get("maps_to_observability", {})) >= 1,
           "metrik observability'ye eşlenir (0.4.7)")

    # ── error taxonomy (P10)
    et = spec.get("error_taxonomy", {})
    mapping = et.get("mapping", {})
    _check(R, len(mapping) >= 5, "P10 hata eşlemesi (≥5)")
    _check(R, all(v in ERROR_TAXONOMY for v in mapping.values()),
           "P10 tüm hedefler API §11.6 ErrorTaxonomy'de")
    _check(R, mapping.get("sip_408_timeout") == "TIMEOUT"
           and mapping.get("sip_503_5xx") == "UNAVAILABLE"
           and mapping.get("trunk_auth_failure") == "AUTH"
           and mapping.get("region_mismatch") == "REGION_VIOLATION",
           "P10 408→TIMEOUT, 503→UNAVAILABLE, auth→AUTH, bölge→REGION_VIOLATION")
    _check(R, len(et.get("failure_reason_codes", [])) >= 5
           and et.get("reason_code_taxonomy_source", "").startswith("2.1.7"),
           "P6/P8 hata neden kodları 2.1.7 taksonomisinden")

    # ── residency + pii (P7/P8/P10)
    rs = spec.get("residency", {})
    _check(R, rs.get("region_pin_required") is True, "P8 residency region pin (NFR 10.7)")
    _check(R, rs.get("secure_transport_required") is True, "P7 SRTP/TLS zorunlu (NFR 10.6)")
    _check(R, rs.get("no_log_required") is True
           and set(rs.get("allowed_retention", [])) <= ALLOWED_RETENTION,
           "P8 no-log: data_retention NONE/EPHEMERAL")
    pii = spec.get("pii", {})
    _check(R, pii.get("raw_phone_number_in_spec_forbidden") is True
           and pii.get("call_media_in_spec_forbidden") is True
           and pii.get("pii_value_in_spec_forbidden") is True,
           "P10 ham numara/çağrı medyası/PII değeri spec'te yasak")

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
               "P5 ≥%d SPI-uyumlu sağlayıcı (dtmf+amd+transfer + COLD/WARM/WHISPER + 8kHz + SRTP + in/out)"
               % g.get("min_providers", 2))
        # iki taşıma modu (managed + byoc) kapsanmalı (FR-TEL-002)
        cmodes = {p.get("mode") for p in conformant}
        _check(R, {"managed", "byoc"} <= cmodes,
               "P5/FR-TEL-002 uyumlu portföy hem managed CPaaS hem BYOC SIP trunk içerir")
        pids = [p.get("provider_id") for p in provs]
        _check(R, len(pids) == len(set(pids)), "config sağlayıcı ID'leri benzersiz")
        for p in provs:
            _check(R, p.get("data_retention") in ALLOWED_RETENTION,
                   "P8 config %s data_retention NONE/EPHEMERAL" % p.get("provider_id"))
            _check(R, p.get("secure_transport") is True, "P7 config %s SRTP/TLS" % p.get("provider_id"))
            _check(R, SAMPLE_RATE_HZ in p.get("sample_rates", []), "P7 config %s 8kHz" % p.get("provider_id"))
            _check(R, TRANSFER_MODES <= set(p.get("transfer_modes", [])),
                   "P3 config %s cold/warm/whisper" % p.get("provider_id"))
            _check(R, float(p.get("media_setup_ms", 1e9)) <= g.get("setup_p95_ms", 0),
                   "P7 config %s media_setup_ms ≤ kurulum kapısı" % p.get("provider_id"))
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
    "provider_id": "tel-managed-A", "mode": "managed",
    "directions": ["inbound", "outbound"],
    "features": ["dtmf", "amd", "transfer", "srtp", "caller_id_pool"],
    "transfer_modes": ["COLD", "WARM", "WHISPER"],
    "regions": ["EU", "TR"], "sample_rates": [8000], "secure_transport": True,
    "no_train": True, "data_retention": "NONE",
    "media_setup_ms": 720, "media_setup_ms_degraded": 2600,
}
FAILURE_REASONS = {
    "no_answer", "busy", "rejected", "network_failure", "provider_unavailable",
    "timeout", "no_route", "media_failure", "auth_failure", "rate_limited",
    "dropped_mid_call", "blocked_dnc", "blocked_consent_missing", "blocked_capacity",
}


def _dial(t, call_id="c1", direction="outbound", e164_valid=None, caller_id_pool="pool-1",
          secure=None, sr=None, region_pinned=None, tenant=None):
    ev = {"kind": "dial", "call_id": call_id, "t": t, "direction": direction}
    if caller_id_pool is not None:
        ev["caller_id_pool"] = caller_id_pool
    if e164_valid is not None:
        ev["e164_valid"] = e164_valid
    if secure is not None:
        ev["secure_transport"] = secure
    if sr is not None:
        ev["sample_rate_hz"] = sr
    if region_pinned is not None:
        ev["region_pinned"] = region_pinned
    if tenant:
        ev["tenant_id"] = tenant
    return ev


def _answer(t, call_id="c1", e164_valid=None, secure=None, sr=None, region_pinned=None, tenant=None):
    ev = {"kind": "answer", "call_id": call_id, "t": t, "direction": "inbound"}
    if e164_valid is not None:
        ev["e164_valid"] = e164_valid
    if secure is not None:
        ev["secure_transport"] = secure
    if sr is not None:
        ev["sample_rate_hz"] = sr
    if region_pinned is not None:
        ev["region_pinned"] = region_pinned
    if tenant:
        ev["tenant_id"] = tenant
    return ev


def _media(t, call_id="c1"):
    return {"kind": "media_ready", "call_id": call_id, "t": t}


def _dtmf(t, call_id="c1", transport="rfc2833"):
    return {"kind": "dtmf", "call_id": call_id, "t": t, "transport": transport}


def _amd(t, call_id="c1", result="human"):
    return {"kind": "amd", "call_id": call_id, "t": t, "result": result}


def _xfer(t, call_id="c1", mode="WARM", target_type="AGENT", ref="agt-1"):
    return {"kind": "transfer", "call_id": call_id, "t": t, "mode": mode,
            "target_type": target_type, "ref": ref}


def _hangup(t, call_id="c1", reason_code="completed_caller_hangup", reason="normal", tax=None):
    ev = {"kind": "hangup", "call_id": call_id, "t": t, "reason_code": reason_code, "reason": reason}
    if tax is not None:
        ev["error_taxonomy"] = tax
    return ev


def _pol(**over):
    pol = {"normalize_contract": True, "validate_e164": True, "require_caller_id_pool": True,
           "support_transfer": True, "surface_events": True, "require_reason_code": True,
           "require_secure_transport": True, "region_pin": True, "fast_setup": True,
           "meter": True, "normalize_errors": True, "tenant_isolation": True, "order_guard": True}
    pol.update(over)
    return pol


def _run(events, provider=None, **pol_over):
    spec = _load(SPEC_PATH)
    return simulate({"events": events}, provider or PROVIDER_A, _pol(**pol_over),
                    spec.get("gates", {}), failure_reasons=FAILURE_REASONS)


def selftest():
    spec = _load(SPEC_PATH)
    gates = spec.get("gates", {})
    cases = []

    def case(ok, label):
        cases.append((bool(ok), label))

    # 0) validate iyi spec+config'te geçer
    case(_validate_obj(_load(SPEC_PATH)) == 0, "validate iyi spec+config'te 0 döndürür")

    # ── happy: inbound answer + media + dtmf + amd + transfer + hangup (P1–P8) ──────
    mh = simulate({"events": [
        _answer(0, call_id="c1"), _media(700, call_id="c1"),
        _dtmf(1200, call_id="c1"), _amd(1300, call_id="c1", result="human"),
        _xfer(2000, call_id="c1", mode="WARM", target_type="AGENT"),
        _hangup(3000, call_id="c1", reason_code="transfer_to_human"),
        _dial(3500, call_id="c2", direction="outbound", caller_id_pool="pool-1"),
        _media(4100, call_id="c2"), _hangup(9000, call_id="c2", reason_code="completed_agent_hangup"),
    ]}, PROVIDER_A, _pol(), gates, failure_reasons=FAILURE_REASONS)
    case(mh["contract_divergence"] == 0, "happy: taşıma-nötr normalize, divergence yok (P1)")
    case(mh["invalid_e164"] == 0 and mh["missing_caller_id_pool"] == 0, "happy: E.164 + caller-ID havuzu (P2)")
    case(mh["unsupported_transfer"] == 0 and mh["transfers_ok"] == 1, "happy: warm transfer desteklendi (P3)")
    case(mh["dropped_event"] == 0 and mh["dtmf_events"] == 1 and mh["amd_events"] == 1, "happy: DTMF+AMD yüzeye çıktı (P4)")
    case(mh["missing_reason_code"] == 0, "happy: hangup standart neden kodu (P6)")
    case(mh["setup_p95_ms"] <= gates["setup_p95_ms"] and mh["insecure_media"] == 0 and mh["non_8khz"] == 0,
         "happy: 8kHz + SRTP + kurulum bütçe içinde (P7)")
    case(mh["usage_records"] == mh["ended"] == 2 and mh["region_violation"] == 0, "happy: her çağrı UsageRecord + residency (P8)")
    case(all(ok for ok, _ in evaluate(gates, mh)), "happy tüm kapıları geçer")

    # ── determinizm ───────────────────────────────────────────────────────────────
    seq = [_answer(0), _media(700), _xfer(1000), _hangup(2000, reason_code="transfer_to_human")]
    case(_run(seq) == _run(seq), "determinizm: aynı olay-akışı birebir aynı metrik (random yok)")

    # ── ≥2 sağlayıcı: BYOC trunk (B) ile de geçer ───────────────────────────────────
    pb = dict(PROVIDER_A); pb["provider_id"] = "tel-byoc-B"; pb["mode"] = "byoc"
    pb["data_retention"] = "EPHEMERAL"; pb["media_setup_ms"] = 540
    mb = _run([_answer(0), _media(540), _dtmf(900), _hangup(2000)], provider=pb)
    case(all(ok for ok, _ in evaluate(gates, mb)) and mb["provider_id"] == "tel-byoc-B" and mb["mode"] == "byoc",
         "≥2 sağlayıcı: ikinci adapter (BYOC SIP trunk B) de kapıları geçer (FR-TEL-002/ADR-002)")

    # ── degraded-1: taşıma modu sızdı → contract divergence (P1 eler) ────────────────
    d1 = _run([_answer(0), _media(700), _hangup(2000)], normalize_contract=False)
    case(d1["contract_divergence"] >= 1, "degraded(contract): managed/BYOC biçimi orchestrator'a sızdı (ADR-001 ihlali)")
    case(not all(ok for ok, _ in evaluate(gates, d1)), "degraded(contract) P1 eler")

    # ── degraded-2: E.164 dışı numara + caller-ID havuzu yok (P2 eler) ───────────────
    d2 = _run([_dial(0, e164_valid=False), _media(700), _hangup(2000)])
    case(d2["invalid_e164"] >= 1, "degraded(e164): E.164 dışı numara (FR-TEL-004 ihlali)")
    case(not all(ok for ok, _ in evaluate(gates, d2)), "degraded(e164) P2 eler")
    d2b = _run([_dial(0, caller_id_pool=None), _media(700), _hangup(2000)])
    case(d2b["missing_caller_id_pool"] >= 1, "degraded(no-pool): outbound caller-ID havuzu yok (FR-TEL-005 ihlali)")
    case(not all(ok for ok, _ in evaluate(gates, d2b)), "degraded(no-pool) P2 eler")

    # ── degraded-3: geçersiz transfer mode (P3 eler) ────────────────────────────────
    d3 = _run([_answer(0), _media(700), _xfer(1000, mode="BLIND", target_type="AGENT"), _hangup(2000)])
    case(d3["unsupported_transfer"] >= 1, "degraded(xfer): geçersiz transfer mode (cold/warm/whisper dışı; FR-TEL-007)")
    case(not all(ok for ok, _ in evaluate(gates, d3)), "degraded(xfer) P3 eler")
    d3b = _run([_answer(0), _media(700), _xfer(1000), _hangup(2000)], support_transfer=False)
    case(d3b["unsupported_transfer"] >= 1, "degraded(xfer-off): transfer desteklenmedi (FR-TEL-007)")
    case(not all(ok for ok, _ in evaluate(gates, d3b)), "degraded(xfer-off) P3 eler")

    # ── degraded-4: DTMF/AMD olayı yutuldu (P4 eler) ────────────────────────────────
    d4 = _run([_answer(0), _media(700), _dtmf(900), _amd(1000), _hangup(2000)], surface_events=False)
    case(d4["dropped_event"] >= 1 and d4["dtmf_events"] == 0, "degraded(drop): DTMF/AMD olayı yüzeye çıkmadı (FR-TEL-006/010)")
    case(not all(ok for ok, _ in evaluate(gates, d4)), "degraded(drop) P4 eler")

    # ── degraded-5: hangup neden kodu yok (P6 eler) ─────────────────────────────────
    d5 = _run([_answer(0), _media(700), _hangup(2000, reason_code=None)])
    case(d5["missing_reason_code"] >= 1, "degraded(no-reason): hangup neden kodu yok (FR-TEL-012)")
    case(not all(ok for ok, _ in evaluate(gates, d5)), "degraded(no-reason) P6 eler")

    # ── degraded-6: yavaş kurulum + güvensiz + non-8khz (P7 eler) ────────────────────
    d6 = _run([_answer(0), _media(2600), _hangup(4000)], fast_setup=False)
    case(d6["setup_max_ms"] > gates["setup_p95_ms"], "degraded(slow-setup): kurulum 2600ms > 2000 bütçe (SAD §20)")
    case(not all(ok for ok, _ in evaluate(gates, d6)), "degraded(slow-setup) P7 eler")
    d6b = _run([_answer(0, secure=False), _media(700), _hangup(2000)])
    case(d6b["insecure_media"] >= 1, "degraded(insecure): düz-metin SIP/RTP (NFR 10.6 ihlali)")
    case(not all(ok for ok, _ in evaluate(gates, d6b)), "degraded(insecure) P7 eler")
    d6c = _run([_answer(0, sr=16000), _media(700), _hangup(2000)])
    case(d6c["non_8khz"] >= 1, "degraded(non-8khz): 8kHz dışı medya (FR-RES-008 ihlali)")
    case(not all(ok for ok, _ in evaluate(gates, d6c)), "degraded(non-8khz) P7 eler")

    # ── degraded-7: metering yok / residency / hata normalizasyonu (P8 eler) ─────────
    d7 = _run([_answer(0), _media(700), _hangup(2000)], meter=False)
    case(d7["usage_records"] == 0 and d7["ended"] == 1, "degraded(no-meter): UsageRecord/CDR üretilmedi (FR-BIL-002)")
    case(not all(ok for ok, _ in evaluate(gates, d7)), "degraded(no-meter) P8 eler")
    d7b = _run([_answer(0, region_pinned=False), _media(700), _hangup(2000)])
    case(d7b["region_violation"] >= 1, "degraded(no-region-pin): home-region trunk yok (NFR 10.7)")
    case(not all(ok for ok, _ in evaluate(gates, d7b)), "degraded(no-region-pin) P8 eler")
    d7c = _run([_dial(0), _media(700), _hangup(2000, reason_code="provider_unavailable", reason="error", tax="raw-sip-503")],
               normalize_errors=False)
    case(d7c["errors_seen"] == 1 and d7c["errors_normalized"] == 0,
         "degraded(no-norm): SIP hatası ErrorTaxonomy'ye çevrilmedi (FR-TOOL-008)")
    case(not all(ok for ok, _ in evaluate(gates, d7c)), "degraded(no-norm) P8 eler")
    # hata normalize edilirse geçer
    d7ok = _run([_dial(0), _media(700), _hangup(2000, reason_code="provider_unavailable", reason="error", tax="UNAVAILABLE")])
    case(d7ok["errors_normalized"] == 1 and all(ok for ok, _ in evaluate(gates, d7ok)),
         "error-normalized: provider_unavailable → UNAVAILABLE (API §11.6) geçer")

    # ── geçersiz olay reddi (P10) ──────────────────────────────────────────────────
    case(_raises(lambda: _run([_media(10), _hangup(20)])), "P10 bilinmeyen call_id media → reddedilir")
    case(_raises(lambda: _run([_dial(0, direction="sideways"), _hangup(10)])), "P10 geçersiz yön → reddedilir")
    case(_raises(lambda: _run([_dtmf(0, transport="bad"), _hangup(10)])), "P10 geçersiz DTMF taşıma → reddedilir")
    case(_raises(lambda: _run([_answer(0), _media(100)])), "P10 'hangup' olmadan → reddedilir")
    case(_raises(lambda: _run([_answer(0), _answer(0)])), "P10 tekrar kullanılan call_id → reddedilir")
    case(_raises(lambda: _run([_answer(0), _hangup(2000), _hangup(3000)])), "P10 bitmiş çağrıda hangup → reddedilir")
    case(_raises(lambda: _run([_answer(1000), _media(1100), _hangup(2000), _answer(0, call_id="c2"), _hangup(5)])),
         "P10 out-of-order → reddedilir")
    case(_raises(lambda: _run([_answer(0), {"kind": "nope", "t": 1}, _hangup(2)])), "P10 bilinmeyen olay → reddedilir")
    case(_raises(lambda: simulate({"events": []}, PROVIDER_A, _pol(), gates, failure_reasons=FAILURE_REASONS)),
         "P10 boş olay akışı → reddedilir")
    case(_raises(lambda: _run([_answer(0, tenant="t-other"), _hangup(50)])),
         "P10 cross-tenant (izolasyon açık) → reddedilir")

    # ── validate negatif kapılar ────────────────────────────────────────────────────
    s = json.loads(json.dumps(spec)); s["gates"]["max_contract_divergence"] = 1
    case(_validate_obj(s) != 0, "P1 max_contract_divergence>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_invalid_e164"] = 1
    case(_validate_obj(s) != 0, "P2 max_invalid_e164>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_unsupported_transfer"] = 1
    case(_validate_obj(s) != 0, "P3 max_unsupported_transfer>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_dropped_event"] = 1
    case(_validate_obj(s) != 0, "P4 max_dropped_event>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_missing_reason_code"] = 1
    case(_validate_obj(s) != 0, "P6 max_missing_reason_code>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_insecure_media"] = 1
    case(_validate_obj(s) != 0, "P7 max_insecure_media>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_non_8khz"] = 1
    case(_validate_obj(s) != 0, "P7 max_non_8khz>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["min_providers"] = 1
    case(_validate_obj(s) != 0, "P5 min_providers<2 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["require_metering"] = False
    case(_validate_obj(s) != 0, "P8 require_metering=false → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["require_error_normalized"] = False
    case(_validate_obj(s) != 0, "P8 require_error_normalized=false → validate eler")
    s = json.loads(json.dumps(spec)); s["spi"]["required_features"] = ["dtmf"]
    case(_validate_obj(s) != 0, "P5 eksik required_features → validate eler")
    s = json.loads(json.dumps(spec)); s["spi"]["transfer_modes"] = ["COLD", "WARM"]
    case(_validate_obj(s) != 0, "P3 eksik transfer mode (whisper yok) → validate eler")
    s = json.loads(json.dumps(spec)); s["error_taxonomy"]["mapping"]["x"] = "NOPE"
    case(_validate_obj(s) != 0, "P10 taksonomi-dışı → validate eler")
    s = json.loads(json.dumps(spec)); s["residency"]["secure_transport_required"] = False
    case(_validate_obj(s) != 0, "P7 SRTP zorunluluğu kapalı → validate eler")
    s = json.loads(json.dumps(spec)); s["pii"]["pii_value_in_spec_forbidden"] = False
    case(_validate_obj(s) != 0, "P10 pii-değer-yasak kapalı → validate eler")
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
    except TelephonyError:
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
    print("""telephony-adapter-spec.json beklenen şekli (WBS 4.2.5):
  wbs, version, phase, trace{fr,nfr,sad,adr,api,srs,rtm,vendor_eval,consumes,observability}
  placement{behind_spi=true, orchestrator_depends_on_spi_only=true, scope=call_lifecycle,
            transport_neutral=true, transport_modes[managed_cpaas,byoc_sip_trunk],
            event_driven=true, non_blocking=true}                                            (P1,P5,P9)
  spi{methods[dial,answer,transfer,sendDtmf,hangup,mediaStream,on,...],
      dial_request_fields[...callerIdPool], transfer_modes[COLD,WARM,WHISPER],
      transfer_target_types[QUEUE,SKILL,AGENT,NUMBER], events[ANSWERED,HANGUP,DTMF,AMD],
      dtmf_transports[rfc2833,sip_info], required_features[dtmf,amd,transfer],
      required_sample_rate_hz=8000}                                                          (P2,P3,P4,P5,P7)
  gates{setup_p95_ms, setup_green_ms, max_contract_divergence=0, max_invalid_e164=0,
        max_missing_caller_id_pool=0, max_unsupported_transfer=0, max_dropped_event=0,
        max_missing_reason_code=0, max_insecure_media=0, max_non_8khz=0, max_region_violation=0,
        max_cross_tenant=0, min_providers=2, require_metering=true, require_error_normalized=true,
        required_features[...], required_transfer_modes[...], required_sample_rate_hz=8000}    (P1-P8)
  fallback{min_providers=2, secondary_trunk_on_failure=true, switching_owned_by=4.3.x}        (P9)
  metrics{emitted[], maps_to_observability{}}
  error_taxonomy{mapping→API §11.6, failure_reason_codes[], reason_code_taxonomy_source=2.1.7} (P6,P8,P10)
  residency{region_pin_required=true, secure_transport_required=true, no_log_required=true,
            allowed_retention[NONE,EPHEMERAL]}                                               (P7,P8,P10)
  pii{raw_phone_number_in_spec_forbidden, call_media_in_spec_forbidden, pii_value_in_spec_forbidden} (P10)
  invariants[≥10]{id, desc, trace}

config/telephony-adapter-profiles.json: providers[]{provider_id, mode(managed/byoc),
  directions(⊇inbound,outbound), features(⊇dtmf,amd,transfer), transfer_modes(⊇COLD,WARM,WHISPER),
  dtmf_transports, regions, sample_rates(∋8000), secure_transport(=true), no_train, data_retention
  (NONE/EPHEMERAL), media_setup_ms, media_setup_ms_degraded}; profiles[]{name, primary_provider,
  fallback_provider, setup_target_ms, region}

simulate sample: {name, provider | provider_obj | profile, tenant_id?, expect, expected?{metrik:değer},
  policy?{normalize_contract, validate_e164, require_caller_id_pool, support_transfer, surface_events,
  require_reason_code, require_secure_transport, region_pin, fast_setup, meter, normalize_errors,
  tenant_isolation}, events[{kind:'dial'|'answer', call_id, t, direction, e164_valid?, caller_id_pool?,
  secure_transport?, sample_rate_hz?, region_pinned?} | {kind:'media_ready', call_id, t} |
  {kind:'dtmf', call_id, t, transport} | {kind:'amd', call_id, t, result} | {kind:'transfer', call_id, t,
  mode, target_type, ref?} | {kind:'hangup', call_id, t, reason_code, reason?, error_taxonomy?}]}
  — dial|answer → (media_ready|dtmf|amd|transfer)* → hangup; akışta ≥1 'hangup' olmalı

komutlar: validate | simulate <sample.json> | selftest | schema""")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if cmd == "validate":
        return validate()
    if cmd == "simulate":
        if len(sys.argv) < 3:
            print("kullanım: telephony_adapter_probe.py simulate <sample.json>")
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
