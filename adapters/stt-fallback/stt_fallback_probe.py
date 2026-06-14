#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stt_fallback_probe.py — WBS 4.3.1 STT fallback (hata/timeout → ikincil)

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only statik + davranış kapısı. `adapters/` (4.2.x) ve
`runtime/`/`telephony/` modül disipliniyle aynı; burada SttAdapter SPI (SAD §8.1 / API §11.2) ARKASINDA
ortak FALLBACK ANAHTARLAMA mantığını sürükleyen DETERMİNİSTİK bir referans switcher (olay-tetikli, sanal
saat, random YOK; gerçek STT/ses tanıma YOK — sağlayıcı gecikme profili + akış/hata MODELİ). SAD §8.3:
  Primary STT ──(timeout/error/circuit-open)──► Secondary STT ──► Deterministic flow

Görev başlığındaki çekirdek davranış (FR-STT-008, BRD §19 (4), API §11.2):
  • FAILOVER:        birincil STT akışı geçici hata/timeout (circuit-open) verince ikincile geçilir;
                     çağrı kesintisiz sürer (S1 — utterance_lost=0).
  • AUDIO REPLAY:    failover'da in-flight söz için son ≤replay_window_ms audio ikincile yeniden gönderilir
                     (kısmi audio replay — S2; "mümkünse son N saniye audio yeniden gönderilir").
  • DETERMINISTIC:   her iki sağlayıcı da düşerse deterministik akışa (insan aktarımı / güvenli degrade)
                     geçilir — ÇAĞRI DÜŞÜRÜLMEZ (S6 — dropped_call=0; "fail soft, never drop the call").
Ek (Must): anahtarlama gecikmesi sınırlı (S3), tek aktif stream + dup-final yok (S4), ≥2 sağlayıcı (S5),
seçici tetik + hata normalizasyonu (S7), histerezis/flap yok + metering + residency (S8).

KAPSAM AYRIMI: SttAdapter implementasyonu (streaming/partial/final/confidence/phrase-boost) → 4.2.1/4.2.2
(bu motor SARMALAR, uygulamaz); ortak yetenekler (timeout/retry/backoff/circuit-breaker/health) → 4.1.2
(circuit-open sinyali TÜKETİLİR); hata normalizasyonu eşlemesi → 4.1.5 (TÜKETİLİR); connection pool →
4.1.6; metering motoru → 4.1.3 (UsageRecord ÜRETİMİ doğrulanır); residency/retention → 4.1.4; deterministik
akış/insan aktarımı MOTORU → 8.x handoff + 3.3.x (KARARI üretilir, aktarım akışı değil); STT sağlayıcı
SEÇİMİ → 0.2.2/0.2.6/0.3.x. Referans davranış: 0.3.1 e2e_inbound_poc.py _stt_with_fallback.

Komutlar:
  validate              stt-fallback-spec.json'ı invariant'lara (S1–S10) + config sağlayıcı/profillerine doğrular.
  simulate <sample>     Deterministik switcher — olay-akışı (start + audio + final + provider_error + end) →
                        failover/replay/deterministic-flow metrikleri → HARD kapılar (S1–S8) → çıkış kodu.
  selftest              İyi/kötü spec+sample ile kapıların doğru tetiklendiğini kanıtlar.
  schema                Beklenen spec şeklini özetler.

Sunucu/credential GEREKMEZ. simulate gerçek STT yerine sağlayıcı gecikme profili (config providers) +
akış/hata MODELİ kullanır (canlı sistemde Go/Rust async runtime + gerçek SttAdapter + 4.1.2 circuit
breaker, ADR-003/SAD §6.3/§8.1). Ham AUDIO, transkript METNİ veya PII DEĞERİ YOK — yalnız sağlayıcı
kimliği + gecikme/akış SAYILARI + söz/segment kimlikleri + normalize edilmiş hata sınıfı + sanal zaman.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "stt-fallback-spec.json")
PROFILES_CFG = os.path.join(HERE, "config", "stt-fallback-profiles.json")

ERROR_TAXONOMY = {
    "TIMEOUT", "RATE_LIMITED", "UNAVAILABLE", "AUTH",
    "INVALID_REQUEST", "CONTENT_FILTERED", "QUOTA_EXCEEDED", "REGION_VIOLATION",
}
SECRET_RE = re.compile(
    r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer)\b\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}"
)
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")

REQUIRED_FEATURES = {"streaming"}
ALLOWED_RETENTION = {"NONE", "EPHEMERAL"}
FAILOVER_CLASSES = {"TIMEOUT", "RATE_LIMITED", "UNAVAILABLE"}
END_REASONS = {"normal", "transfer", "error", "abandon"}


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_placeholder(v):
    return isinstance(v, str) and PLACEHOLDER_RE.match(v) is not None


def _percentile(values, pct):
    """Lineer-interpolasyonlu yüzdelik (media_latency / tts_eval / llm_adapter probe ile birebir)."""
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


class SttFallbackError(Exception):
    """Geçersiz/desteklenmeyen olay veya yetki/izolasyon ihlali — sessizce kabul yok, reddet (S10)."""


# ─────────────────────────────────────────────────────────────────────────────
# STT fallback switcher referans sürücüsü (deterministik)
# ─────────────────────────────────────────────────────────────────────────────
class SttFallbackRuntime:
    """SAD §8.3 STT fallback switcher. Tek çağrının olay-akışını işler:
        start → (audio* | final | provider_error)* → end
    Aktif (birincil) SttAdapter izlenir; geçici hata/timeout → ikincile geçiş + in-flight söz audio replay;
    her iki sağlayıcı düşerse deterministik akış. Tüm gecikmeler sağlayıcı PROFİLİNDEN deterministik (random
    YOK; sanal saat = event.t).

    Olaylar:
      {kind:'start', t, sample_rate_hz?, tenant_id?}
      {kind:'audio', t, utterance_id, seq?, duration_ms}    # in-flight söz tamponu
      {kind:'final', t, utterance_id, confidence?}          # aktif sağlayıcı final → söz tamamlandı
      {kind:'provider_error', t, utterance_id?, raw_error}  # aktif sağlayıcı hatası → routing kararı
      {kind:'end', t, reason∈{normal,transfer,error,abandon}}
    """

    def __init__(self, primary, secondary, policy, gates, error_taxonomy, tenant_id="t-self"):
        self.primary = primary
        self.secondary = secondary
        self.pol = policy
        self.g = gates
        self.tax_map = (error_taxonomy or {}).get("mapping", {})
        self.tenant_id = tenant_id
        self.replay_window_ms = float(policy.get("replay_window_ms", gates.get("replay_window_ms", 5000)))
        self.failover_classes = set(gates.get("failover_error_classes", list(FAILOVER_CLASSES)))

        self._last_t = None
        self.active = "primary"            # primary | secondary | deterministic | dropped
        self.active_provider = primary
        self.switched = False
        self.segments = 0                  # aktif sağlayıcı stint sayısı (metering)
        self.current_utt = None
        self.inflight = {}                 # utterance_id -> birikmiş in-flight audio_ms (final olmamış)
        self.finalized = set()
        self.sample_rate_hz = 8000

        # ölçüm dizileri
        self.switch_overhead_ms = []
        # sayaçlar / metrikler
        self.audio_chunks = 0
        self.finals_total = 0
        self.failovers = 0                 # gerçekleşen sağlayıcı geçişi (stt_fallback_total)
        self.audio_replayed_ms = 0.0
        self.utterance_lost = 0            # S1
        self.missing_replay = 0            # S2
        self.replay_window_exceeded = 0    # S2
        self.duplicate_final = 0           # S4
        self.concurrent_active_max = 1     # S4
        self.dropped_call = 0              # S6
        self.deterministic_flow_count = 0  # S6
        self.improper_failover = 0         # S7
        self.flap_count = 0                # S8
        self.errors_seen = 0               # S7
        self.errors_normalized = 0         # S7
        self.cross_tenant = 0
        self.sample_rate_mismatch = 0      # S8/FR-RES-008
        self.started = False
        self.ended = False

    # ── ortak guard'lar ───────────────────────────────────────────────────────
    def _check_time(self, t):
        if not isinstance(t, (int, float)):
            raise SttFallbackError("zaman damgası sayısal değil → INVALID_REQUEST")
        if self._last_t is not None and t < self._last_t:
            if self.pol.get("order_guard", True):
                raise SttFallbackError("out-of-order olay (t geriye) reddedildi → INVALID_REQUEST")
        self._last_t = max(self._last_t if self._last_t is not None else t, t)

    def _check_scope(self, ev):
        tt = ev.get("tenant_id", self.tenant_id)
        if tt != self.tenant_id:
            self.cross_tenant += 1
            if self.pol.get("tenant_isolation", True):
                raise SttFallbackError("cross-tenant erişim reddedildi → AUTH")

    def _activate(self, provider):
        """Bir sağlayıcıyı aktif et + metering segmenti aç (S8)."""
        self.active_provider = provider
        if self.pol.get("meter", True):
            self.segments += 1
        else:
            # BOZUK: metering kapalı → UsageRecord üretilmez
            pass

    # ── start ─────────────────────────────────────────────────────────────────
    def start(self, ev):
        self._check_time(ev.get("t"))
        self._check_scope(ev)
        if self.started:
            raise SttFallbackError("start tekrar → INVALID_REQUEST")
        self.started = True
        sr = ev.get("sample_rate_hz", self.g.get("sample_rate_hz", 8000))
        self.sample_rate_hz = sr
        if sr != self.g.get("sample_rate_hz", 8000):
            self.sample_rate_mismatch += 1
        self.active = "primary"
        self.switched = False
        self._activate(self.primary)

    # ── audio: in-flight söz tamponu ──────────────────────────────────────────
    def audio(self, ev):
        self._check_time(ev.get("t"))
        self._check_scope(ev)
        if not self.started:
            raise SttFallbackError("start'tan önce audio → INVALID_REQUEST")
        u = ev.get("utterance_id")
        if not isinstance(u, str) or not u:
            raise SttFallbackError("utterance_id yok/boş → INVALID_REQUEST")
        dur = ev.get("duration_ms")
        if not isinstance(dur, (int, float)) or dur < 0:
            raise SttFallbackError("duration_ms sayısal/≥0 değil → INVALID_REQUEST")
        self.audio_chunks += 1
        self.current_utt = u
        # rolling in-flight tampon: son ≤replay_window_ms (eski audio düşülür)
        self.inflight[u] = min(self.inflight.get(u, 0.0) + float(dur),
                               self.replay_window_ms if self.pol.get("rolling_window", True) else 1e12) \
            if self.pol.get("rolling_window", True) else self.inflight.get(u, 0.0) + float(dur)
        # ham (penceresiz) birikim ayrı izlenir → pencere aşımı tespiti
        self._raw_inflight = getattr(self, "_raw_inflight", {})
        self._raw_inflight[u] = self._raw_inflight.get(u, 0.0) + float(dur)

    # ── final: aktif sağlayıcı bir sözü tamamladı ─────────────────────────────
    def final(self, ev):
        self._check_time(ev.get("t"))
        self._check_scope(ev)
        if self.active in ("deterministic", "dropped"):
            # deterministik akışta STT final beklenmez (güvenli degrade) — yok say
            return
        u = ev.get("utterance_id")
        if not isinstance(u, str) or not u:
            raise SttFallbackError("final utterance_id yok/boş → INVALID_REQUEST")
        if u in self.finalized:
            # aynı söz ikinci kez final → dedup kararı (S4)
            if self.pol.get("dedup", True):
                return  # doğru: çift final bastırılır (replay sonrası tek final)
            self.duplicate_final += 1
            return
        self.finalized.add(u)
        self.finals_total += 1
        self.inflight.pop(u, None)
        if hasattr(self, "_raw_inflight"):
            self._raw_inflight.pop(u, None)

    # ── provider_error: routing kararı (S1/S2/S6/S7) ──────────────────────────
    def provider_error(self, ev):
        self._check_time(ev.get("t"))
        self._check_scope(ev)
        if not self.started:
            raise SttFallbackError("start'tan önce hata → INVALID_REQUEST")
        raw = ev.get("raw_error")
        if raw is None:
            raise SttFallbackError("provider_error raw_error yok → INVALID_REQUEST")
        self.errors_seen += 1
        tax = self._normalize(raw) if self.pol.get("normalize_errors", True) else None
        if tax is not None:
            self.errors_normalized += 1
        eff_tax = tax if tax is not None else "UNAVAILABLE"   # normalize edilmese de routing devam (S7 ayrı eler)
        transient = eff_tax in self.failover_classes

        if self.active in ("deterministic", "dropped"):
            return  # zaten degrade

        if transient:
            if self.pol.get("failover", True):
                self._failover(ev, eff_tax)
            else:
                # BOZUK: failover kapalı → in-flight söz kaybolur, çağrı bozulur (S1 ihlali)
                u = ev.get("utterance_id", self.current_utt)
                if u is not None and u not in self.finalized:
                    self.utterance_lost += 1
        else:
            # geçici OLMAYAN sınıf (AUTH/INVALID_REQUEST/REGION_VIOLATION)
            if not self.pol.get("selective_trigger", True):
                # BOZUK: seçici tetik kapalı → boşuna anahtarlama (S7 ihlali)
                self.improper_failover += 1
                self._failover(ev, eff_tax)
            else:
                # doğru: anahtarlama yok → deterministik akış (güvenli degrade, çağrı düşmez)
                self._route_deterministic(eff_tax)

    def _failover(self, ev, reason):
        u = ev.get("utterance_id", self.current_utt)
        raw_inflight = getattr(self, "_raw_inflight", {})
        inflight_ms = raw_inflight.get(u, 0.0) if u is not None else 0.0
        already_final = (u in self.finalized) if u is not None else False

        if not self.switched:
            target = self.secondary
            replay_time = 0.0
            if inflight_ms > 0 and not already_final:
                if self.pol.get("replay", True):
                    replay_ms = min(inflight_ms, self.replay_window_ms)
                    if inflight_ms > self.replay_window_ms:
                        # söz penceresinden uzun → fazlası replay edilemez (S2 ihlali)
                        self.replay_window_exceeded += 1
                    self.audio_replayed_ms += replay_ms
                    replay_time = replay_ms * float(target.get("replay_rtf", 0.2))
                    # söz ikincide sürer → kaybolmaz (utterance_lost artmaz)
                else:
                    # BOZUK: replay yok → in-flight söz kaybolur (S2/S1 ihlali)
                    self.missing_replay += 1
                    self.utterance_lost += 1
            # single stream: teardown → setup (örtüşme yok)
            if not self.pol.get("single_stream", True):
                self.concurrent_active_max = max(self.concurrent_active_max, 2)
            overhead = float(self.primary.get("teardown_ms", 20)) \
                + float(target.get("setup_ms", 40)) + replay_time
            self.switch_overhead_ms.append(overhead)
            self.failovers += 1
            self.switched = True
            self.active = "secondary"
            self._activate(target)
        else:
            # ikincil de düştü
            if self.pol.get("hysteresis", True):
                # doğru: geri dönme yok → deterministik akış
                self._route_deterministic(reason)
            else:
                # BOZUK: birincile geri salınım (flap; S8 ihlali)
                self.flap_count += 1
                self.switched = False
                self.active = "primary"
                overhead = float(self.secondary.get("teardown_ms", 20)) \
                    + float(self.primary.get("setup_ms", 40))
                self.switch_overhead_ms.append(overhead)
                self._activate(self.primary)

    def _route_deterministic(self, reason):
        if self.active in ("deterministic", "dropped"):
            return
        if self.pol.get("deterministic_flow", True):
            self.deterministic_flow_count += 1
            self.active = "deterministic"
        else:
            # BOZUK: deterministik akış yok → çağrı düşürülür (S6 ihlali)
            self.dropped_call += 1
            self.active = "dropped"

    def _normalize(self, raw):
        if raw in ERROR_TAXONOMY:
            return raw
        return self.tax_map.get(raw)

    def end(self, ev):
        self._check_time(ev.get("t"))
        if self.ended:
            raise SttFallbackError("end tekrar → INVALID_REQUEST")
        reason = ev.get("reason", "normal")
        if reason not in END_REASONS:
            raise SttFallbackError("geçersiz bitiş nedeni: %r → INVALID_REQUEST" % reason)
        self.ended = True

    def metrics(self):
        scenario = []
        if self.failovers:
            scenario.append("failover" if self.utterance_lost == 0 else "utterance-lost")
        if self.audio_replayed_ms > 0:
            scenario.append("audio-replay")
        if self.deterministic_flow_count:
            scenario.append("deterministic-flow")
        if self.dropped_call:
            scenario.append("dropped-call")
        if self.improper_failover:
            scenario.append("improper-failover")
        if self.flap_count:
            scenario.append("flap")
        if not scenario:
            scenario.append("no-failover" if self.finals_total else "empty")
        usage_records = self.segments  # _activate yalnız meter açıkken artırır
        return {
            "primary_id": self.primary.get("provider_id"),
            "secondary_id": self.secondary.get("provider_id"),
            "active_at_end": self.active,
            "audio_chunks": self.audio_chunks,
            "finals_total": self.finals_total,
            "failovers": self.failovers,
            "switch_overhead_p95_ms": _percentile(self.switch_overhead_ms, 95),
            "switch_overhead_p50_ms": _percentile(self.switch_overhead_ms, 50),
            "switch_overhead_max_ms": max(self.switch_overhead_ms) if self.switch_overhead_ms else None,
            "audio_replayed_ms": round(self.audio_replayed_ms, 3),
            "utterance_lost": self.utterance_lost,
            "missing_replay": self.missing_replay,
            "replay_window_exceeded": self.replay_window_exceeded,
            "duplicate_final": self.duplicate_final,
            "concurrent_active_max": self.concurrent_active_max,
            "dropped_call": self.dropped_call,
            "deterministic_flow_count": self.deterministic_flow_count,
            "improper_failover": self.improper_failover,
            "flap_count": self.flap_count,
            "errors_seen": self.errors_seen,
            "errors_normalized": self.errors_normalized,
            "provider_segments": self.segments,
            "usage_records": usage_records,
            "cross_tenant": self.cross_tenant,
            "sample_rate_mismatch": self.sample_rate_mismatch,
            "scenario": scenario,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Tam simülasyon (bir sample)
# ─────────────────────────────────────────────────────────────────────────────
def simulate(sample, primary, secondary, policy, gates, error_taxonomy):
    events = sample.get("events")
    if events is None or not isinstance(events, list) or not events:
        raise SttFallbackError("boş/geçersiz olay akışı → INVALID_REQUEST")
    rt = SttFallbackRuntime(primary, secondary, policy, gates, error_taxonomy,
                            tenant_id=sample.get("tenant_id", "t-self"))
    saw_end = False
    for ev in events:
        if not isinstance(ev, dict):
            raise SttFallbackError("olay sözlük değil → INVALID_REQUEST")
        kind = ev.get("kind")
        if kind == "start":
            rt.start(ev)
        elif kind == "audio":
            rt.audio(ev)
        elif kind == "final":
            rt.final(ev)
        elif kind == "provider_error":
            rt.provider_error(ev)
        elif kind == "end":
            rt.end(ev)
            saw_end = True
        else:
            raise SttFallbackError("bilinmeyen olay tipi: %r → INVALID_REQUEST" % kind)
    if not rt.started:
        raise SttFallbackError("olay akışında 'start' yok → INVALID_REQUEST")
    if not saw_end:
        raise SttFallbackError("olay akışında 'end' yok → INVALID_REQUEST")
    return rt.metrics()


def evaluate(gates, m):
    """Metrikleri HARD kapılara (S1–S8 davranışsal) karşı değerlendirir. Döner findings[(ok, label)]."""
    F = []

    # ── S1: FAILOVER — in-flight söz kaybı yok
    F.append((m.get("utterance_lost", 0) <= gates.get("max_utterance_lost", 0),
              "S1 failover: utterance_lost %d ≤ %d (%d failover; çağrı sürer — FR-STT-008)"
              % (m.get("utterance_lost", 0), gates.get("max_utterance_lost", 0), m.get("failovers", 0))))

    # ── S2: AUDIO REPLAY — in-flight söz replay edildi, pencere aşılmadı
    s2_ok = (m.get("missing_replay", 0) <= gates.get("max_missing_replay", 0)
             and m.get("replay_window_exceeded", 0) <= gates.get("max_replay_window_exceeded", 0))
    F.append((s2_ok,
              "S2 replay: missing_replay %d ≤ %d + window_exceeded %d ≤ %d (%s ms replay; API §11.2)"
              % (m.get("missing_replay", 0), gates.get("max_missing_replay", 0),
                 m.get("replay_window_exceeded", 0), gates.get("max_replay_window_exceeded", 0),
                 _fmt(m.get("audio_replayed_ms")))))

    # ── S3: SWITCH OVERHEAD — sınırlı ölü hava
    so95 = m.get("switch_overhead_p95_ms")
    F.append(((so95 is None or so95 <= gates.get("switch_overhead_p95_ms", 200)),
              "S3 overhead: switch P95 %s ≤ %d ms (sınırlı ölü hava; NFR 10.1/SAD §20)"
              % (_fmt(so95), gates.get("switch_overhead_p95_ms", 200))))

    # ── S4: NO DUPLICATION / SINGLE STREAM
    s4_ok = (m.get("duplicate_final", 0) <= gates.get("max_duplicate_final", 0)
             and m.get("concurrent_active_max", 1) <= gates.get("max_concurrent_active", 1))
    F.append((s4_ok,
              "S4 tek-stream: duplicate_final %d ≤ %d + concurrent_active %d ≤ %d (FR-STT-002)"
              % (m.get("duplicate_final", 0), gates.get("max_duplicate_final", 0),
                 m.get("concurrent_active_max", 1), gates.get("max_concurrent_active", 1))))

    # ── S6: DETERMINISTIC FLOW / NEVER DROP
    F.append((m.get("dropped_call", 0) <= gates.get("max_dropped_call", 0),
              "S6 never-drop: dropped_call %d ≤ %d (%d deterministik akış; BRD §19 (4))"
              % (m.get("dropped_call", 0), gates.get("max_dropped_call", 0),
                 m.get("deterministic_flow_count", 0))))

    # ── S7: SELECTIVE TRIGGER + ERROR NORMALIZED
    norm_ok = (not gates.get("require_error_normalized", True)) \
        or (m.get("errors_normalized", 0) == m.get("errors_seen", 0))
    s7_ok = (m.get("improper_failover", 0) <= gates.get("max_improper_failover", 0)) and norm_ok
    F.append((s7_ok,
              "S7 seçici+normalize: improper_failover %d ≤ %d + err_norm %d/%d (FR-TOOL-008/SAD §8.3)"
              % (m.get("improper_failover", 0), gates.get("max_improper_failover", 0),
                 m.get("errors_normalized", 0), m.get("errors_seen", 0))))

    # ── S8: NO FLAP + METERING + RESIDENCY(8kHz/tenant)
    meter_ok = (not gates.get("require_metering", True)) \
        or (m.get("usage_records", 0) == m.get("provider_segments", 0) and m.get("usage_records", 0) > 0)
    s8_ok = (m.get("flap_count", 0) <= gates.get("max_flap", 0)) and meter_ok \
        and m.get("cross_tenant", 0) <= gates.get("max_cross_tenant", 0) \
        and m.get("sample_rate_mismatch", 0) <= gates.get("max_sample_rate_mismatch", 0)
    F.append((s8_ok,
              "S8 flap+metering+8kHz: flap %d ≤ %d + usage %d/%d seg + cross_tenant %d + sr_mismatch %d "
              "(FR-BIL-002/NFR 10.7)"
              % (m.get("flap_count", 0), gates.get("max_flap", 0),
                 m.get("usage_records", 0), m.get("provider_segments", 0),
                 m.get("cross_tenant", 0), m.get("sample_rate_mismatch", 0))))

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
    raise SttFallbackError("bilinmeyen sağlayıcı: %s" % pid)


def _profile_by_name(cfg, name):
    for p in cfg.get("profiles", []):
        if p.get("name") == name:
            return p
    raise SttFallbackError("bilinmeyen profil: %s" % name)


def _default_policy():
    return {
        "failover": True,
        "replay": True,
        "deterministic_flow": True,
        "selective_trigger": True,
        "single_stream": True,
        "hysteresis": True,
        "dedup": True,
        "meter": True,
        "normalize_errors": True,
        "rolling_window": True,
        "tenant_isolation": True,
        "order_guard": True,
    }


def _resolve_policy(sample):
    pol = _default_policy()
    pol.update(sample.get("policy", {}))
    return pol


def _resolve_providers(sample, cfg):
    if "primary_obj" in sample and "secondary_obj" in sample:
        return sample["primary_obj"], sample["secondary_obj"], sample.get("replay_window_ms")
    prof = _profile_by_name(cfg, sample.get("profile", cfg.get("default_profile")))
    pid = sample.get("primary", prof.get("primary_provider"))
    sid = sample.get("secondary", prof.get("secondary_provider"))
    return (_provider_by_id(cfg, pid), _provider_by_id(cfg, sid), prof.get("replay_window_ms"))


def simulate_cmd(sample_path):
    spec = _load(SPEC_PATH)
    sample = _load(sample_path)
    name = sample.get("name", os.path.basename(sample_path))
    expect = sample.get("expect", "pass")
    gates = spec.get("gates", {})
    policy = _resolve_policy(sample)

    try:
        cfg = _load(PROFILES_CFG)
        primary, secondary, prof_window = _resolve_providers(sample, cfg)
    except SttFallbackError as ex:
        print("simulate[%s]: %s" % (name, ex))
        return 0 if expect == "fail" else 1
    if prof_window is not None and "replay_window_ms" not in policy:
        policy["replay_window_ms"] = prof_window

    try:
        m = simulate(sample, primary, secondary, policy, gates, spec.get("error_taxonomy", {}))
    except SttFallbackError as ex:
        print("simulate[%s]: REDDEDİLDİ — %s" % (name, ex))
        return 0 if expect == "fail" else 1

    F = evaluate(gates, m)
    print("simulate[%s] primary=%s secondary=%s senaryo=%s | %d audio | %d final | %d failover | "
          "switch P95=%s ms | active@end=%s"
          % (name, m["primary_id"], m["secondary_id"], "+".join(m["scenario"]),
             m["audio_chunks"], m["finals_total"], m["failovers"],
             _fmt(m["switch_overhead_p95_ms"]), m["active_at_end"]))
    print("  utterance_lost=%d | missing_replay=%d | window_exceeded=%d | replayed=%s ms | dup_final=%d | "
          "dropped=%d | det_flow=%d | improper=%d | flap=%d | usage=%d/%d seg | err_norm=%d/%d"
          % (m["utterance_lost"], m["missing_replay"], m["replay_window_exceeded"],
             _fmt(m["audio_replayed_ms"]), m["duplicate_final"], m["dropped_call"],
             m["deterministic_flow_count"], m["improper_failover"], m["flap_count"],
             m["usage_records"], m["provider_segments"], m["errors_normalized"], m["errors_seen"]))
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

    _check(R, spec.get("wbs") == "4.3.1", "spec.wbs == 4.3.1")
    _check(R, spec.get("version"), "spec.version mevcut")

    # ── placement
    pl = spec.get("placement", {})
    _check(R, pl.get("behind_spi") is True and pl.get("orchestrator_depends_on_spi_only") is True,
           "SttAdapter SPI arkası; orchestrator yalnız SPI'ye + karara bağımlı (ADR-001/SAD §8.1)")
    _check(R, pl.get("turn_state") == "CAPTURE", "CAPTURE durumunda (SAD §6.1)")
    _check(R, pl.get("stream_first") is True, "S2 akış-önce (stream-first, FR-RES-002)")
    _check(R, pl.get("event_driven") is True and pl.get("non_blocking") is True,
           "olay-tetikli + bloklamaz")
    _check(R, bool(pl.get("circuit_breaker_owned_by")), "S9 circuit breaker 4.1.2'den tüketilir")
    _check(R, bool(pl.get("deterministic_flow_owned_by")), "S9 deterministic flow motoru 8.x/3.3.x")

    # ── spi yüzeyi (S5)
    sp = spec.get("spi", {})
    _check(R, "stream" in sp.get("wraps_methods", []), "SPI stream() sarmalanır (SAD §8.1/API §11.2)")
    _check(R, sp.get("presents_single_logical_stream") is True,
           "S4 orchestrator'a tek mantıksal stream sunulur")
    _check(R, set(sp.get("required_features", [])) == REQUIRED_FEATURES,
           "S5 required_features {streaming}")
    _check(R, "interimResults" in sp.get("stt_options_fields", []),
           "SttOptions interimResults (partial — FR-STT-001)")
    _check(R, "isFinal" in sp.get("transcript_fields", []) and "confidence" in sp.get("transcript_fields", []),
           "Transcript isFinal + confidence (FR-STT-002/006)")

    # ── kapılar
    g = spec.get("gates", {})
    _check(R, g.get("sample_rate_hz") == 8000, "S8 sample_rate_hz = 8000 (FR-RES-008)")
    _check(R, g.get("switch_overhead_p95_ms") == 200, "S3 switch_overhead_p95_ms = 200 (NFR 10.1)")
    _check(R, g.get("switch_overhead_green_ms", 1e9) < g.get("switch_overhead_p95_ms", 0),
           "S3 yeşil bant < kapı (switch overhead)")
    _check(R, g.get("replay_window_ms", 0) > 0, "S2 replay_window_ms > 0 (in-flight tampon üst sınırı)")
    _check(R, g.get("max_utterance_lost", -1) == 0, "S1 max_utterance_lost = 0")
    _check(R, g.get("max_missing_replay", -1) == 0, "S2 max_missing_replay = 0")
    _check(R, g.get("max_replay_window_exceeded", -1) == 0, "S2 max_replay_window_exceeded = 0")
    _check(R, g.get("max_duplicate_final", -1) == 0, "S4 max_duplicate_final = 0")
    _check(R, g.get("max_concurrent_active", -1) == 1, "S4 max_concurrent_active = 1 (tek stream)")
    _check(R, g.get("max_dropped_call", -1) == 0, "S6 max_dropped_call = 0 (never drop)")
    _check(R, g.get("max_improper_failover", -1) == 0, "S7 max_improper_failover = 0 (seçici tetik)")
    _check(R, g.get("max_flap", -1) == 0, "S8 max_flap = 0 (histerezis)")
    _check(R, g.get("max_cross_tenant", -1) == 0, "S8 max_cross_tenant = 0")
    _check(R, g.get("min_providers", 0) >= 2, "S5 min_providers ≥ 2 (ADR-002 / BRD §19 (1))")
    _check(R, g.get("require_deterministic_flow") is True, "S6 require_deterministic_flow")
    _check(R, g.get("require_error_normalized") is True, "S7 require_error_normalized (FR-TOOL-008)")
    _check(R, g.get("require_metering") is True, "S8 require_metering (FR-BIL-002)")
    _check(R, set(g.get("required_features", [])) == REQUIRED_FEATURES,
           "gates required_features SPI ile tutarlı")
    _check(R, set(g.get("failover_error_classes", [])) == FAILOVER_CLASSES,
           "S7 failover_error_classes = {TIMEOUT, UNAVAILABLE, RATE_LIMITED} (yalnız geçici)")

    # ── fallback zinciri (S1/S2/S6)
    fb = spec.get("fallback", {})
    _check(R, fb.get("chain") == ["primary_stt", "secondary_stt", "deterministic_flow"],
           "S1/S6 fallback zinciri primary→secondary→deterministic (SAD §8.3)")
    _check(R, fb.get("min_providers", 0) >= 2 and fb.get("partial_audio_replay") is True,
           "S2/S5 fallback ≥2 sağlayıcı + kısmi audio replay (FR-STT-008/API §11.2)")
    _check(R, fb.get("hysteresis_sticky_secondary") is True, "S8 histerezis (sticky secondary, flap yok)")
    _check(R, fb.get("deterministic_flow_on_total_failure") is True, "S6 her iki düşerse deterministik akış")
    _check(R, fb.get("switching_owned_by", "").startswith("4.3.1"),
           "fallback anahtarlama BU görevde (4.3.1)")

    # ── metrikler → observability
    me = spec.get("metrics", {})
    emitted = set(me.get("emitted", []))
    _check(R, {"stt_fallback_total", "stt_switch_overhead_ms", "stt_audio_replayed_ms",
               "stt_deterministic_flow_total", "stt_final_total"} <= emitted,
           "metrikler: fallback + switch_overhead + audio_replayed + deterministic_flow + final yayılır")
    _check(R, len(me.get("maps_to_observability", {})) >= 1,
           "metrik observability'ye eşlenir (0.4.7)")

    # ── error taxonomy (S7/S10)
    et = spec.get("error_taxonomy", {})
    mapping = et.get("mapping", {})
    _check(R, len(mapping) >= 5, "S10 hata eşlemesi (≥5)")
    _check(R, all(v in ERROR_TAXONOMY for v in mapping.values()),
           "S10 tüm hedefler API §11.6 ErrorTaxonomy'de")
    _check(R, mapping.get("provider_timeout") == "TIMEOUT"
           and mapping.get("provider_5xx") == "UNAVAILABLE"
           and mapping.get("circuit_open") == "UNAVAILABLE"
           and mapping.get("auth_failure") == "AUTH"
           and mapping.get("region_mismatch") == "REGION_VIOLATION",
           "S7/S10 timeout→TIMEOUT, 5xx/circuit→UNAVAILABLE, auth→AUTH, bölge→REGION_VIOLATION")
    _check(R, set(et.get("failover_classes", [])) == FAILOVER_CLASSES
           and set(et.get("non_failover_classes", [])) == {"AUTH", "INVALID_REQUEST", "REGION_VIOLATION"},
           "S7 failover_classes geçici + non_failover_classes geçici-olmayan")

    # ── residency + pii (S8/S10)
    rs = spec.get("residency", {})
    _check(R, rs.get("region_pin_required") is True, "S8 residency region pin (NFR 10.7)")
    _check(R, rs.get("no_log_required") is True
           and set(rs.get("allowed_retention", [])) <= ALLOWED_RETENTION,
           "S8 no-log: data_retention NONE/EPHEMERAL (FR-KB-010)")
    _check(R, rs.get("replay_buffer_ephemeral") is True, "S2 replay tamponu ephemeral (durable değil)")
    pii = spec.get("pii", {})
    _check(R, pii.get("raw_audio_in_spec_forbidden") is True
           and pii.get("transcript_text_in_spec_forbidden") is True
           and pii.get("pii_value_in_spec_forbidden") is True,
           "S10 ham ses/transkript/PII değeri spec'te yasak")

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
    _check(R, not hits, "S10 literal sır yok (spec+config)")

    # ── config sağlayıcı + profil doğrulaması (S5)
    if os.path.exists(PROFILES_CFG):
        cfg = _load(PROFILES_CFG)
        provs = cfg.get("providers", [])
        conformant = [p for p in provs if _provider_conformant(p)]
        _check(R, len(conformant) >= g.get("min_providers", 2),
               "S5 ≥%d SPI-uyumlu sağlayıcı (streaming + 8 kHz)" % g.get("min_providers", 2))
        pids = [p.get("provider_id") for p in provs]
        _check(R, len(pids) == len(set(pids)), "config sağlayıcı ID'leri benzersiz")
        profs = cfg.get("profiles", [])
        _check(R, len(profs) >= 2, "config ≥2 çalıştırma profili")
        for prof in profs:
            _check(R, bool(prof.get("region")), "S8 config %s bölge pini var" % prof.get("name"))
            _check(R, prof.get("primary_provider") in pids and prof.get("secondary_provider") in pids,
                   "S5 config %s primary+secondary geçerli sağlayıcı" % prof.get("name"))
            _check(R, prof.get("primary_provider") != prof.get("secondary_provider"),
                   "S5 config %s primary≠secondary (≥2 sağlayıcı)" % prof.get("name"))
            pp = _provider_by_id(cfg, prof.get("primary_provider"))
            spv = _provider_by_id(cfg, prof.get("secondary_provider"))
            _check(R, _provider_conformant(pp) and _provider_conformant(spv),
                   "S5 config %s primary+secondary SPI-uyumlu" % prof.get("name"))
            _check(R, set(pp.get("data_retention", "").split()) <= ALLOWED_RETENTION
                   and set(spv.get("data_retention", "").split()) <= ALLOWED_RETENTION,
                   "S8 config %s primary+secondary data_retention NONE/EPHEMERAL" % prof.get("name"))

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
    "provider_id": "stt-stream-A", "features": ["streaming", "partial", "confidence"],
    "sample_rates": [8000, 16000], "data_retention": "NONE",
    "final_ms": 130, "setup_ms": 60, "teardown_ms": 20, "replay_rtf": 0.20,
}
PROVIDER_B = {
    "provider_id": "stt-stream-B", "features": ["streaming", "partial", "confidence"],
    "sample_rates": [8000, 16000], "data_retention": "EPHEMERAL",
    "final_ms": 155, "setup_ms": 35, "teardown_ms": 15, "replay_rtf": 0.18,
}


def _start(t=0, sr=8000, tenant=None):
    ev = {"kind": "start", "t": t, "sample_rate_hz": sr}
    if tenant:
        ev["tenant_id"] = tenant
    return ev


def _audio(t, u, dur=300, seq=0):
    return {"kind": "audio", "t": t, "utterance_id": u, "seq": seq, "duration_ms": dur}


def _final(t, u, conf=0.9):
    return {"kind": "final", "t": t, "utterance_id": u, "confidence": conf}


def _err(t, raw="provider_timeout", u=None):
    ev = {"kind": "provider_error", "t": t, "raw_error": raw}
    if u is not None:
        ev["utterance_id"] = u
    return ev


def _end(t, reason="normal"):
    return {"kind": "end", "t": t, "reason": reason}


def _run(events, primary=None, secondary=None, **pol_over):
    spec = _load(SPEC_PATH)
    pol = _default_policy()
    pol.update(pol_over)
    return simulate({"events": events}, primary or PROVIDER_A, secondary or PROVIDER_B,
                    pol, spec.get("gates", {}), spec.get("error_taxonomy", {}))


def selftest():
    spec = _load(SPEC_PATH)
    gates = spec.get("gates", {})
    cases = []

    def case(ok, label):
        cases.append((bool(ok), label))

    # 0) validate iyi spec+config'te geçer
    case(_validate_obj(_load(SPEC_PATH)) == 0, "validate iyi spec+config'te 0 döndürür")

    # ── happy: failover + audio replay → ikincide söz tamamlanır (S1–S8) ──────────
    mh = _run([
        _start(0),
        _audio(100, "u1", 300), _final(500, "u1"),
        _audio(2000, "u2", 400), _audio(2300, "u2", 400),   # in-flight söz
        _err(2700, "provider_timeout", "u2"),               # birincil timeout → failover + replay
        _final(3100, "u2"),                                  # ikincide tamamlandı
        _end(6000, "normal"),
    ])
    case(mh["failovers"] == 1 and mh["utterance_lost"] == 0, "happy: 1 failover, söz kaybı yok (S1)")
    case(mh["audio_replayed_ms"] == 800.0 and mh["missing_replay"] == 0, "happy: 800ms in-flight audio replay (S2)")
    case(mh["switch_overhead_p95_ms"] is not None and mh["switch_overhead_p95_ms"] <= 200, "happy: switch overhead ≤200ms (S3)")
    case(mh["duplicate_final"] == 0 and mh["concurrent_active_max"] == 1, "happy: dup-final yok + tek stream (S4)")
    case(mh["dropped_call"] == 0, "happy: çağrı düşmedi (S6)")
    case(mh["improper_failover"] == 0 and mh["errors_normalized"] == mh["errors_seen"] == 1, "happy: seçici tetik + normalize (S7)")
    case(mh["flap_count"] == 0 and mh["usage_records"] == mh["provider_segments"] == 2, "happy: flap yok + 2 segment metering (S8)")
    case(all(ok for ok, _ in evaluate(gates, mh)), "happy tüm kapıları geçer")
    case(mh["finals_total"] == 2, "happy: 2 söz final (u1 birincil, u2 ikincil)")

    # ── determinizm ───────────────────────────────────────────────────────────────
    ev = [_start(0), _audio(100, "u1", 300), _err(400, "circuit_open", "u1"), _final(800, "u1"), _end(2000)]
    case(_run(ev) == _run(ev), "determinizm: aynı olay-akışı birebir aynı metrik (random yok)")

    # ── no-failover happy: hatasız çağrı geçer ─────────────────────────────────────
    mn = _run([_start(0), _audio(100, "u1", 300), _final(500, "u1"), _end(1000)])
    case(mn["failovers"] == 0 and mn["finals_total"] == 1 and all(ok for ok, _ in evaluate(gates, mn)),
         "no-failover: hatasız çağrı tüm kapıları geçer")

    # ── ≥2 sağlayıcı: ikincil farklı (B) ──────────────────────────────────────────
    case(mh["primary_id"] == "stt-stream-A" and mh["secondary_id"] == "stt-stream-B",
         "≥2 sağlayıcı: primary A + secondary B (ADR-002 / BRD §19 (1))")

    # ── both-fail → deterministic flow, çağrı düşmez (S6 geçer) ────────────────────
    mb = _run([
        _start(0), _audio(100, "u1", 300), _err(400, "provider_timeout", "u1"),  # → secondary
        _final(800, "u1"),
        _audio(2000, "u2", 300), _err(2300, "provider_5xx", "u2"),               # secondary de düştü → deterministic
        _end(4000, "transfer"),
    ])
    case(mb["failovers"] == 1 and mb["deterministic_flow_count"] == 1 and mb["dropped_call"] == 0,
         "both-fail: secondary de düşünce deterministik akış, çağrı düşmez (S6)")
    case(all(ok for ok, _ in evaluate(gates, mb)), "both-fail deterministic flow tüm kapıları geçer")

    # ── selective trigger: AUTH failover ETMEZ → deterministic (S7 geçer) ──────────
    ma = _run([_start(0), _audio(100, "u1", 300), _err(400, "auth_failure", "u1"), _end(2000, "transfer")])
    case(ma["failovers"] == 0 and ma["improper_failover"] == 0 and ma["deterministic_flow_count"] == 1,
         "selective: AUTH geçici değil → failover yok, deterministik akış (S7)")
    case(all(ok for ok, _ in evaluate(gates, ma)), "selective AUTH tüm kapıları geçer")

    # ── degraded-1: replay kapalı → in-flight söz kaybolur (S1/S2 eler) ────────────
    d1 = _run([_start(0), _audio(100, "u1", 300), _audio(400, "u1", 300),
               _err(700, "provider_timeout", "u1"), _end(3000)], replay=False)
    case(d1["missing_replay"] >= 1 and d1["utterance_lost"] >= 1,
         "degraded(no-replay): in-flight söz replay edilmedi → kayıp (FR-STT-008 ihlali)")
    case(not all(ok for ok, _ in evaluate(gates, d1)), "degraded(no-replay) S1/S2 eler")

    # ── degraded-2: failover kapalı → söz kaybolur (S1 eler) ──────────────────────
    d2 = _run([_start(0), _audio(100, "u1", 300), _err(400, "provider_timeout", "u1"), _end(2000)],
              failover=False)
    case(d2["failovers"] == 0 and d2["utterance_lost"] >= 1,
         "degraded(no-failover): geçici hatada anahtarlama yok → söz kaybı (S1)")
    case(not all(ok for ok, _ in evaluate(gates, d2)), "degraded(no-failover) S1 eler")

    # ── degraded-3: deterministic flow kapalı → çağrı düşer (S6 eler) ──────────────
    d3 = _run([_start(0), _audio(100, "u1", 300), _err(400, "provider_timeout", "u1"), _final(800, "u1"),
               _audio(2000, "u2", 300), _err(2300, "provider_5xx", "u2"), _end(4000)],
              deterministic_flow=False)
    case(d3["dropped_call"] >= 1, "degraded(no-det-flow): her iki düşünce çağrı düşürüldü (BRD §19 (4) ihlali)")
    case(not all(ok for ok, _ in evaluate(gates, d3)), "degraded(no-det-flow) S6 eler")

    # ── degraded-4: seçici tetik kapalı → AUTH'ta boşuna failover (S7 eler) ─────────
    d4 = _run([_start(0), _audio(100, "u1", 300), _err(400, "auth_failure", "u1"), _final(800, "u1"), _end(2000)],
              selective_trigger=False)
    case(d4["improper_failover"] >= 1, "degraded(no-selective): AUTH'ta boşuna anahtarlama (S7)")
    case(not all(ok for ok, _ in evaluate(gates, d4)), "degraded(no-selective) S7 eler")

    # ── degraded-5: histerezis kapalı → flap (S8 eler) ─────────────────────────────
    d5 = _run([_start(0), _audio(100, "u1", 300), _err(400, "provider_timeout", "u1"), _final(800, "u1"),
               _audio(2000, "u2", 300), _err(2300, "provider_timeout", "u2"), _final(2700, "u2"), _end(4000)],
              hysteresis=False)
    case(d5["flap_count"] >= 1, "degraded(no-hysteresis): secondary hatasında birincile geri salınım (flap; S8)")
    case(not all(ok for ok, _ in evaluate(gates, d5)), "degraded(no-hysteresis) S8 eler")

    # ── degraded-6: dedup kapalı → çift final (S4 eler) ────────────────────────────
    d6 = _run([_start(0), _audio(100, "u1", 300), _err(400, "provider_timeout", "u1"),
               _final(800, "u1"), _final(900, "u1"), _end(2000)], dedup=False)
    case(d6["duplicate_final"] >= 1, "degraded(no-dedup): aynı söz iki final → duplicate (S4)")
    case(not all(ok for ok, _ in evaluate(gates, d6)), "degraded(no-dedup) S4 eler")

    # ── degraded-7: tek stream kapalı → eşzamanlı çift aktif (S4 eler) ──────────────
    d7 = _run([_start(0), _audio(100, "u1", 300), _err(400, "provider_timeout", "u1"), _final(800, "u1"), _end(2000)],
              single_stream=False)
    case(d7["concurrent_active_max"] >= 2, "degraded(dual-stream): anahtarlamada eşzamanlı çift aktif (S4)")
    case(not all(ok for ok, _ in evaluate(gates, d7)), "degraded(dual-stream) S4 eler")

    # ── degraded-8: metering kapalı → UsageRecord eksik (S8 eler) ──────────────────
    d8 = _run([_start(0), _audio(100, "u1", 300), _final(500, "u1"), _end(1000)], meter=False)
    case(d8["usage_records"] == 0, "degraded(no-meter): UsageRecord üretilmedi (FR-BIL-002)")
    case(not all(ok for ok, _ in evaluate(gates, d8)), "degraded(no-meter) S8 eler")

    # ── degraded-9: hata normalize edilmedi (S7 eler) ──────────────────────────────
    d9 = _run([_start(0), _audio(100, "u1", 300), _err(400, "raw-provider-503", "u1"), _final(800, "u1"), _end(2000)],
              normalize_errors=False)
    case(d9["errors_seen"] == 1 and d9["errors_normalized"] == 0,
         "degraded(no-norm): sağlayıcı hatası ErrorTaxonomy'ye çevrilmedi (FR-TOOL-008)")
    case(not all(ok for ok, _ in evaluate(gates, d9)), "degraded(no-norm) S7 eler")

    # ── degraded-10: yavaş sağlayıcı (C) → switch overhead kapısı eler (S3) ─────────
    slow = {"provider_id": "stt-stream-C", "features": ["streaming"], "sample_rates": [8000],
            "data_retention": "NONE", "final_ms": 240, "setup_ms": 260, "teardown_ms": 90, "replay_rtf": 1.10}
    d10 = _run([_start(0), _audio(100, "u1", 600), _err(700, "provider_timeout", "u1"), _final(1200, "u1"), _end(3000)],
               secondary=slow)
    case(d10["switch_overhead_max_ms"] is not None and d10["switch_overhead_max_ms"] > 200,
         "degraded(slow-secondary): teardown+setup+replay > 200ms (S3)")
    case(not all(ok for ok, _ in evaluate(gates, d10)), "degraded(slow-secondary) S3 eler")

    # ── degraded-11: replay penceresi aşıldı → fazlası kayıp (S2 eler) ──────────────
    d11 = _run([_start(0), _audio(100, "u1", 6000),  # 6s > 5000ms pencere
                _err(6200, "provider_timeout", "u1"), _final(6600, "u1"), _end(9000)],
               rolling_window=False)
    case(d11["replay_window_exceeded"] >= 1, "degraded(long-utterance): in-flight > replay_window → fazlası replay edilemez (S2)")
    case(not all(ok for ok, _ in evaluate(gates, d11)), "degraded(long-utterance) S2 eler")

    # ── degraded-12: 8 kHz dışı sample rate (S8 eler) ──────────────────────────────
    d12 = _run([_start(0, sr=16000), _audio(100, "u1", 300), _final(500, "u1"), _end(1000)])
    case(d12["sample_rate_mismatch"] >= 1, "degraded(non-8khz): sample_rate≠8000 (FR-RES-008)")
    case(not all(ok for ok, _ in evaluate(gates, d12)), "degraded(non-8khz) S8 eler")

    # ── geçersiz olay reddi (S10) ──────────────────────────────────────────────────
    case(_raises(lambda: _run([_audio(0, "u1", 300), _end(10)])), "S10 start'tan önce audio → reddedilir")
    case(_raises(lambda: _run([_start(0), _audio(10, "u1", 300)])), "S10 'end' olmadan → reddedilir")
    case(_raises(lambda: _run([_audio(0, "u1", 300)])), "S10 'start' olmadan → reddedilir")
    case(_raises(lambda: _run([_start(0), _start(1), _end(2)])), "S10 tekrar start → reddedilir")
    case(_raises(lambda: _run([_start(1000), _audio(0, "u1", 300), _end(2000)])), "S10 out-of-order → reddedilir")
    case(_raises(lambda: _run([_start(0), {"kind": "nope", "t": 1}, _end(2)])), "S10 bilinmeyen olay → reddedilir")
    case(_raises(lambda: _run([_start(0), _err(10), _end(20)]) if False else
                 simulate({"events": [_start(0), {"kind": "provider_error", "t": 10}, _end(20)]},
                          PROVIDER_A, PROVIDER_B, _default_policy(), gates, spec.get("error_taxonomy", {}))),
         "S10 raw_error'suz provider_error → reddedilir")
    case(_raises(lambda: simulate({"events": []}, PROVIDER_A, PROVIDER_B, _default_policy(), gates,
                                  spec.get("error_taxonomy", {}))), "S10 boş olay akışı → reddedilir")
    case(_raises(lambda: _run([_start(0, tenant="t-other"), _end(50)])),
         "S10 cross-tenant (izolasyon açık) → reddedilir")
    case(_raises(lambda: _run([_start(0), _end(10, reason="weird")])), "S10 geçersiz bitiş nedeni → reddedilir")

    # ── validate negatif kapılar ────────────────────────────────────────────────────
    s = json.loads(json.dumps(spec)); s["gates"]["sample_rate_hz"] = 16000
    case(_validate_obj(s) != 0, "S8 sample_rate_hz≠8000 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["switch_overhead_p95_ms"] = 999
    case(_validate_obj(s) != 0, "S3 switch_overhead_p95_ms≠200 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_utterance_lost"] = 1
    case(_validate_obj(s) != 0, "S1 max_utterance_lost>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_missing_replay"] = 1
    case(_validate_obj(s) != 0, "S2 max_missing_replay>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_duplicate_final"] = 1
    case(_validate_obj(s) != 0, "S4 max_duplicate_final>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_concurrent_active"] = 2
    case(_validate_obj(s) != 0, "S4 max_concurrent_active≠1 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_dropped_call"] = 1
    case(_validate_obj(s) != 0, "S6 max_dropped_call>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_improper_failover"] = 1
    case(_validate_obj(s) != 0, "S7 max_improper_failover>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_flap"] = 1
    case(_validate_obj(s) != 0, "S8 max_flap>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["min_providers"] = 1
    case(_validate_obj(s) != 0, "S5 min_providers<2 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["require_deterministic_flow"] = False
    case(_validate_obj(s) != 0, "S6 require_deterministic_flow=false → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["failover_error_classes"] = ["TIMEOUT", "AUTH"]
    case(_validate_obj(s) != 0, "S7 failover_error_classes geçici-olmayan içerir → validate eler")
    s = json.loads(json.dumps(spec)); s["fallback"]["chain"] = ["primary_stt", "secondary_stt"]
    case(_validate_obj(s) != 0, "S6 zincirde deterministic_flow yok → validate eler")
    s = json.loads(json.dumps(spec)); s["error_taxonomy"]["mapping"]["x"] = "NOPE"
    case(_validate_obj(s) != 0, "S10 taksonomi-dışı → validate eler")
    s = json.loads(json.dumps(spec)); s["pii"]["pii_value_in_spec_forbidden"] = False
    case(_validate_obj(s) != 0, "S10 pii-değer-yasak kapalı → validate eler")
    s = json.loads(json.dumps(spec)); s["residency"]["allowed_retention"] = ["PROVIDER_DEFAULT"]
    case(_validate_obj(s) != 0, "S8 no-log dışı retention → validate eler")
    s = json.loads(json.dumps(spec)); s["spi"]["required_features"] = ["streaming", "x"]
    case(_validate_obj(s) != 0, "S5 fazladan required_features → validate eler")
    s = json.loads(json.dumps(spec)); s["metrics"]["secret"] = "api_key: AKIAIOSFODNN7EXAMPLE"
    case(_validate_obj(s) != 0, "S10 literal secret → validate eler")

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
    except SttFallbackError:
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
    print("""stt-fallback-spec.json beklenen şekli (WBS 4.3.1):
  wbs, version, phase, trace{fr,nfr,sad,adr,api,brd,srs,rtm,poc,vendor_eval,consumes,observability}
  placement{behind_spi=true, orchestrator_depends_on_spi_only=true, turn_state=CAPTURE,
            stream_first=true, event_driven=true, non_blocking=true,
            circuit_breaker_owned_by, deterministic_flow_owned_by}                              (S1,S9)
  spi{wraps_methods[stream,...], stt_options_fields[...interimResults], transcript_fields[isFinal,
      confidence,...], required_features[streaming], presents_single_logical_stream=true}        (S4,S5)
  gates{sample_rate_hz=8000, switch_overhead_p95_ms=200, replay_window_ms,
        max_utterance_lost=0, max_missing_replay=0, max_replay_window_exceeded=0,
        max_duplicate_final=0, max_concurrent_active=1, max_dropped_call=0,
        max_improper_failover=0, max_flap=0, max_cross_tenant=0, min_providers=2,
        require_deterministic_flow=true, require_error_normalized=true, require_metering=true,
        failover_error_classes[TIMEOUT,UNAVAILABLE,RATE_LIMITED]}                                 (S1-S8)
  fallback{chain[primary_stt,secondary_stt,deterministic_flow], min_providers=2,
           partial_audio_replay=true, hysteresis_sticky_secondary=true,
           deterministic_flow_on_total_failure=true, switching_owned_by=4.3.1}                    (S1,S2,S6)
  metrics{emitted[stt_fallback_total,stt_switch_overhead_ms,stt_audio_replayed_ms,
          stt_deterministic_flow_total,stt_final_total], maps_to_observability{}}
  error_taxonomy{mapping→API §11.6, failover_classes[...], non_failover_classes[...]}            (S7,S10)
  residency{region_pin_required=true, no_log_required=true, allowed_retention[NONE,EPHEMERAL],
            replay_buffer_ephemeral=true}                                                         (S8,S10)
  pii{raw_audio_in_spec_forbidden, transcript_text_in_spec_forbidden, pii_value_in_spec_forbidden} (S10)
  invariants[≥10]{id, desc, trace}

config/stt-fallback-profiles.json: providers[]{provider_id, languages, sample_rates(⊇8000),
  features(⊇streaming), regions, data_retention(NONE/EPHEMERAL), final_ms, setup_ms, teardown_ms,
  replay_rtf}; profiles[]{name, primary_provider, secondary_provider, region, replay_window_ms}

simulate sample: {name, profile | primary+secondary | primary_obj+secondary_obj, tenant_id?, expect,
  expected?{metrik:değer}, policy?{failover, replay, deterministic_flow, selective_trigger,
  single_stream, hysteresis, dedup, meter, normalize_errors, rolling_window, tenant_isolation,
  replay_window_ms},
  events[{kind:'start', t, sample_rate_hz?} | {kind:'audio', t, utterance_id, duration_ms, seq?} |
         {kind:'final', t, utterance_id, confidence?} |
         {kind:'provider_error', t, raw_error, utterance_id?} | {kind:'end', t, reason}]}
  — start → (audio|final|provider_error)* → end; ilk olay 'start', son olay 'end'

komutlar: validate | simulate <sample.json> | selftest | schema""")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if cmd == "validate":
        return validate()
    if cmd == "simulate":
        if len(sys.argv) < 3:
            print("kullanım: stt_fallback_probe.py simulate <sample.json>")
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
