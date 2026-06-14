#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tts_fallback_probe.py — WBS 4.3.2 TTS fallback + ses karakteri tutarlılığı

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only statik + davranış kapısı. `adapters/` (4.2.x) ve
4.3.1 stt-fallback disipliniyle aynı; burada TtsAdapter SPI (SAD §8.1 / API §11.3) ARKASINDA ortak FALLBACK
ANAHTARLAMA + SES KARAKTERİ TUTARLILIĞI mantığını sürükleyen DETERMİNİSTİK bir referans switcher (olay-tetikli,
sanal saat, random YOK; gerçek TTS/ses üretimi YOK — sağlayıcı gecikme profili + akış/hata MODELİ). SAD §8.3:
  Primary TTS ──(timeout/error/circuit-open)──► Secondary TTS (eşdeğer ses) ──► Deterministic flow

Görev başlığının İKİ boyutu (FR-TTS-008/009, BRD §19 (4), API §11.3):
  • FAILOVER:        birincil TTS sentezi geçici hata/timeout (circuit-open) verince ikincile geçilir;
                     çağrı kesintisiz sürer (T1 — utterance_lost=0).
  • RESYNTH:         failover'da in-flight sözün KALAN (çalınmamış) metni ikincide yeniden sentezlenir
                     (T2 — unspoken_lost=0); zaten ÇALINMIŞ metin TEKRAR seslendirilmez
                     (resynth_replayed_spoken=0 — kullanıcı baştan tekrar duymaz, kesintiden devam eder).
  • VOICE:           sağlayıcı fallback'inde ikincil, tenant logical voiceId'sine karşılık gelen önceden
                     tanımlı EŞDEĞER fiziksel sesi kullanır (T8 — voice_switch_unmapped=0); voiceId çağrı
                     boyu sabit kalır (voice_inconsistent=0) → SES KARAKTERİ TUTARLI (FR-TTS-009).
  • DETERMINISTIC:   her iki sağlayıcı da düşerse deterministik akışa (insan aktarımı / güvenli degrade)
                     geçilir — ÇAĞRI DÜŞÜRÜLMEZ (T6 — dropped_call=0; "fail soft, never drop the call").
Ek (Must): anahtarlama gecikmesi sınırlı (T3), tek aktif stream + dup-speech yok (T4), ≥2 sağlayıcı +
eşdeğer ses (T5), seçici tetik + hata normalizasyonu (T7), barge-in korunur (T9 — cancel ≤200ms + kesme
sonrası ses yok), histerezis/flap yok + metering + residency (T10).

KAPSAM AYRIMI: TtsAdapter implementasyonu (streaming/pronunciation/cancel) → 4.2.3 (bu motor SARMALAR,
uygulamaz); ortak yetenekler (timeout/retry/backoff/circuit-breaker/health) → 4.1.2 (circuit-open sinyali
TÜKETİLİR); hata normalizasyonu eşlemesi → 4.1.5 (TÜKETİLİR); connection pool → 4.1.6; metering motoru →
4.1.3 (UsageRecord ÜRETİMİ doğrulanır); residency/retention → 4.1.4; TTS cache motoru → 16.1; barge-in
olayı → 2.2.3/3.1.3 (BARGE_IN → cancel TÜKETİLİR); ses klonlama izni → 4.2.6; deterministik akış/insan
aktarımı MOTORU → 8.x handoff + 3.3.x (KARARI üretilir, aktarım akışı değil); TTS sağlayıcı SEÇİMİ →
0.2.3/0.2.6/0.3.x.

Komutlar:
  validate              tts-fallback-spec.json'ı invariant'lara (T1–T11) + config sağlayıcı/profil/eşdeğer-ses'e doğrular.
  simulate <sample>     Deterministik switcher — olay-akışı (start + speak + complete + barge_in +
                        provider_error + end) → failover/resynth/voice/barge-in/deterministic-flow
                        metrikleri → HARD kapılar (T1–T10) → çıkış kodu.
  selftest              İyi/kötü spec+sample ile kapıların doğru tetiklendiğini kanıtlar.
  schema                Beklenen spec şeklini özetler.

Sunucu/credential GEREKMEZ. simulate gerçek TTS yerine sağlayıcı gecikme profili (config providers) +
akış/hata MODELİ kullanır (canlı sistemde Go/Rust async runtime + gerçek TtsAdapter + 4.1.2 circuit
breaker, ADR-003/SAD §6.3/§8.1). Ham SES, sentez METNİ veya PII DEĞERİ YOK — yalnız sağlayıcı kimliği +
gecikme/akış SAYILARI + karakter/süre sayıları + voice kimlikleri + söz/segment kimlikleri + normalize
edilmiş hata sınıfı + sanal zaman.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "tts-fallback-spec.json")
PROFILES_CFG = os.path.join(HERE, "config", "tts-fallback-profiles.json")

ERROR_TAXONOMY = {
    "TIMEOUT", "RATE_LIMITED", "UNAVAILABLE", "AUTH",
    "INVALID_REQUEST", "CONTENT_FILTERED", "QUOTA_EXCEEDED", "REGION_VIOLATION",
}
SECRET_RE = re.compile(
    r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer)\b\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}"
)
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")

REQUIRED_FEATURES = {"streaming", "barge_in_cancel", "pronunciation_dict"}
ALLOWED_RETENTION = {"NONE", "EPHEMERAL"}
FAILOVER_CLASSES = {"TIMEOUT", "RATE_LIMITED", "UNAVAILABLE"}
END_REASONS = {"normal", "transfer", "error", "abandon"}


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_placeholder(v):
    return isinstance(v, str) and PLACEHOLDER_RE.match(v) is not None


def _percentile(values, pct):
    """Lineer-interpolasyonlu yüzdelik (media_latency / tts_eval / stt_fallback probe ile birebir)."""
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


class TtsFallbackError(Exception):
    """Geçersiz/desteklenmeyen olay veya yetki/izolasyon ihlali — sessizce kabul yok, reddet (T11)."""


# ─────────────────────────────────────────────────────────────────────────────
# TTS fallback switcher referans sürücüsü (deterministik)
# ─────────────────────────────────────────────────────────────────────────────
class TtsFallbackRuntime:
    """SAD §8.3 TTS fallback switcher. Tek çağrının olay-akışını işler:
        start → (speak* | complete | barge_in | provider_error)* → end
    Aktif (birincil) TtsAdapter izlenir; geçici hata/timeout → ikincile geçiş + in-flight sözün KALAN
    metnini EŞDEĞER ses ile yeniden sentezle (çalınmış metni tekrar etme); her iki sağlayıcı düşerse
    deterministik akış. Tüm gecikmeler sağlayıcı PROFİLİNDEN deterministik (random YOK; sanal saat = event.t).

    Olaylar:
      {kind:'start', t, sample_rate_hz?, voice_id?, tenant_id?}        # voice_id = logical voiceId
      {kind:'speak', t, utterance_id, char_len, dur_ms, remaining_chars?, voice_id?, cached?}
      {kind:'complete', t, utterance_id}                               # aktif sağlayıcı sözü tamamladı
      {kind:'barge_in', t, utterance_id?}                              # kullanıcı kesti → cancel
      {kind:'provider_error', t, utterance_id?, raw_error}             # aktif sağlayıcı hatası → routing
      {kind:'end', t, reason∈{normal,transfer,error,abandon}}
    """

    def __init__(self, primary, secondary, policy, gates, error_taxonomy,
                 logical_voice="voice-default", voice_equivalence=None, tenant_id="t-self"):
        self.primary = primary
        self.secondary = secondary
        self.pol = policy
        self.g = gates
        self.tax_map = (error_taxonomy or {}).get("mapping", {})
        self.tenant_id = tenant_id
        self.failover_classes = set(gates.get("failover_error_classes", list(FAILOVER_CLASSES)))

        # ── ses karakteri tutarlılığı (FR-TTS-009) ────────────────────────────────
        self.logical_voice = logical_voice
        equiv = (voice_equivalence or {}).get(logical_voice, {})
        self.primary_voice = equiv.get(primary.get("provider_id"))
        self.secondary_voice = equiv.get(secondary.get("provider_id"))
        # birincilde eşdeğer tanımlı değilse logical'a düş (validate ayrı eler)
        self.effective_voice = self.primary_voice or logical_voice

        self._last_t = None
        self.active = "primary"            # primary | secondary | deterministic | dropped
        self.active_provider = primary
        self.switched = False
        self.segments = 0                  # aktif sağlayıcı stint sayısı (metering)
        self.current_utt = None
        self.spoken_chars = {}             # utterance_id -> çalınmış (seslendirilmiş) karakter
        self.remaining_chars = {}          # utterance_id -> son bilinen çalınmamış kalan karakter
        self.completed = set()
        self.cancelled = set()             # barge-in ile kesilen söz
        self.sample_rate_hz = 8000

        # ölçüm dizileri
        self.switch_overhead_ms = []
        self.barge_in_cancel_ms = []
        # sayaçlar / metrikler
        self.speak_chunks = 0
        self.speak_complete_total = 0
        self.failovers = 0                 # gerçekleşen sağlayıcı geçişi (tts_fallback_total)
        self.resynth_chars_total = 0       # ikincide yeniden sentezlenen kalan karakter (T2)
        self.utterance_lost = 0            # T1
        self.unspoken_lost = 0             # T2 (kalan metin kayboldu)
        self.resynth_replayed_spoken = 0   # T2 (zaten çalınmış metin tekrar seslendirildi)
        self.duplicate_speech = 0          # T4
        self.concurrent_active_max = 1     # T4
        self.chunk_after_cancel = 0        # T9 (barge-in sonrası ses)
        self.dropped_call = 0              # T6
        self.deterministic_flow_count = 0  # T6
        self.improper_failover = 0         # T7
        self.voice_inconsistent = 0        # T8
        self.voice_switch_unmapped = 0     # T8
        self.voice_switches_mapped = 0     # T8 (gözlem)
        self.flap_count = 0                # T10
        self.errors_seen = 0               # T7
        self.errors_normalized = 0         # T7
        self.cross_tenant = 0
        self.sample_rate_mismatch = 0      # T10/FR-RES-008
        self.started = False
        self.ended = False

    # ── ortak guard'lar ───────────────────────────────────────────────────────
    def _check_time(self, t):
        if not isinstance(t, (int, float)):
            raise TtsFallbackError("zaman damgası sayısal değil → INVALID_REQUEST")
        if self._last_t is not None and t < self._last_t:
            if self.pol.get("order_guard", True):
                raise TtsFallbackError("out-of-order olay (t geriye) reddedildi → INVALID_REQUEST")
        self._last_t = max(self._last_t if self._last_t is not None else t, t)

    def _check_scope(self, ev):
        tt = ev.get("tenant_id", self.tenant_id)
        if tt != self.tenant_id:
            self.cross_tenant += 1
            if self.pol.get("tenant_isolation", True):
                raise TtsFallbackError("cross-tenant erişim reddedildi → AUTH")

    def _activate(self, provider):
        """Bir sağlayıcıyı aktif et + metering segmenti aç (T10)."""
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
            raise TtsFallbackError("start tekrar → INVALID_REQUEST")
        self.started = True
        sr = ev.get("sample_rate_hz", self.g.get("sample_rate_hz", 8000))
        self.sample_rate_hz = sr
        if sr != self.g.get("sample_rate_hz", 8000):
            self.sample_rate_mismatch += 1
        lv = ev.get("voice_id")
        if isinstance(lv, str) and lv:
            self.logical_voice = lv  # not: eşdeğer çözümü __init__'te yapıldı (selftest sabit logical)
        self.active = "primary"
        self.switched = False
        self._activate(self.primary)

    # ── speak: in-flight söz seslendirme chunk'ı ──────────────────────────────
    def speak(self, ev):
        self._check_time(ev.get("t"))
        self._check_scope(ev)
        if not self.started:
            raise TtsFallbackError("start'tan önce speak → INVALID_REQUEST")
        if self.active in ("deterministic", "dropped"):
            return  # deterministik akışta TTS seslendirme beklenmez (güvenli degrade)
        u = ev.get("utterance_id")
        if not isinstance(u, str) or not u:
            raise TtsFallbackError("utterance_id yok/boş → INVALID_REQUEST")
        cl = ev.get("char_len")
        if not isinstance(cl, (int, float)) or cl < 0:
            raise TtsFallbackError("char_len sayısal/≥0 değil → INVALID_REQUEST")
        dur = ev.get("dur_ms", 0)
        if not isinstance(dur, (int, float)) or dur < 0:
            raise TtsFallbackError("dur_ms sayısal/≥0 değil → INVALID_REQUEST")

        # barge-in ile kesilmiş söz için chunk → talk-over (T9)
        if u in self.cancelled:
            if self.pol.get("honor_cancel", True):
                return  # doğru: kesme sonrası ses bastırılır (chunk çıkmaz)
            self.chunk_after_cancel += 1
            return

        # ses karakteri tutarlılığı: chunk voice_id'si aktif efektif sesle aynı olmalı (T8)
        vid = ev.get("voice_id")
        if isinstance(vid, str) and vid and vid != self.effective_voice:
            self.voice_inconsistent += 1

        self.speak_chunks += 1
        self.current_utt = u
        self.spoken_chars[u] = self.spoken_chars.get(u, 0) + float(cl)
        if "remaining_chars" in ev:
            rc = ev.get("remaining_chars")
            if not isinstance(rc, (int, float)) or rc < 0:
                raise TtsFallbackError("remaining_chars sayısal/≥0 değil → INVALID_REQUEST")
            self.remaining_chars[u] = float(rc)

    # ── complete: aktif sağlayıcı bir sözü tamamladı ──────────────────────────
    def complete(self, ev):
        self._check_time(ev.get("t"))
        self._check_scope(ev)
        if self.active in ("deterministic", "dropped"):
            return
        u = ev.get("utterance_id")
        if not isinstance(u, str) or not u:
            raise TtsFallbackError("complete utterance_id yok/boş → INVALID_REQUEST")
        if u in self.cancelled:
            return  # kesilen söz tamamlanmaz (barge-in)
        if u in self.completed:
            # aynı söz ikinci kez complete → dedup kararı (T4)
            if self.pol.get("dedup", True):
                return  # doğru: çift seslendirme bastırılır
            self.duplicate_speech += 1
            return
        self.completed.add(u)
        self.speak_complete_total += 1
        self.remaining_chars.pop(u, None)

    # ── barge_in: kullanıcı kesti → cancel ────────────────────────────────────
    def barge_in(self, ev):
        self._check_time(ev.get("t"))
        self._check_scope(ev)
        if not self.started:
            raise TtsFallbackError("start'tan önce barge_in → INVALID_REQUEST")
        if self.active in ("deterministic", "dropped"):
            return
        u = ev.get("utterance_id", self.current_utt)
        if u is None:
            return  # seslendirme yokken barge-in → yok say
        self.cancelled.add(u)
        # cancel→susma gecikmesi aktif sağlayıcı profilinden (deterministik)
        cancel_ms = float(self.active_provider.get("cancel_ms", 70))
        self.barge_in_cancel_ms.append(cancel_ms)

    # ── provider_error: routing kararı (T1/T2/T6/T7/T8) ───────────────────────
    def provider_error(self, ev):
        self._check_time(ev.get("t"))
        self._check_scope(ev)
        if not self.started:
            raise TtsFallbackError("start'tan önce hata → INVALID_REQUEST")
        raw = ev.get("raw_error")
        if raw is None:
            raise TtsFallbackError("provider_error raw_error yok → INVALID_REQUEST")
        self.errors_seen += 1
        tax = self._normalize(raw) if self.pol.get("normalize_errors", True) else None
        if tax is not None:
            self.errors_normalized += 1
        eff_tax = tax if tax is not None else "UNAVAILABLE"   # normalize edilmese de routing devam (T7 ayrı eler)
        transient = eff_tax in self.failover_classes

        if self.active in ("deterministic", "dropped"):
            return  # zaten degrade

        if transient:
            if self.pol.get("failover", True):
                self._failover(ev, eff_tax)
            else:
                # BOZUK: failover kapalı → in-flight söz kaybolur, çağrı bozulur (T1 ihlali)
                u = ev.get("utterance_id", self.current_utt)
                if u is not None and u not in self.completed and u not in self.cancelled:
                    self.utterance_lost += 1
        else:
            # geçici OLMAYAN sınıf (AUTH/INVALID_REQUEST/REGION_VIOLATION)
            if not self.pol.get("selective_trigger", True):
                # BOZUK: seçici tetik kapalı → boşuna anahtarlama (T7 ihlali)
                self.improper_failover += 1
                self._failover(ev, eff_tax)
            else:
                # doğru: anahtarlama yok → deterministik akış (güvenli degrade, çağrı düşmez)
                self._route_deterministic(eff_tax)

    def _failover(self, ev, reason):
        u = ev.get("utterance_id", self.current_utt)
        spoken = self.spoken_chars.get(u, 0.0) if u is not None else 0.0
        remaining = self.remaining_chars.get(u, 0.0) if u is not None else 0.0
        already_done = (u in self.completed or u in self.cancelled) if u is not None else False

        if not self.switched:
            target = self.secondary
            resynth_time = 0.0
            if not already_done and (remaining > 0 or spoken > 0):
                if self.pol.get("resynth", True):
                    # KALAN metni ikincide yeniden sentezle (çalınmış metni tekrar etme)
                    self.resynth_chars_total += remaining
                    resynth_time = remaining * float(target.get("resynth_rtf", 0.2))
                    if not self.pol.get("resume_from_boundary", True):
                        # BOZUK: kesme noktasından devam etmez, baştan sentezler →
                        # zaten çalınmış metin tekrar seslendirilir (T2/T4 ihlali)
                        self.resynth_replayed_spoken += spoken
                        self.duplicate_speech += 1
                    # söz ikincide sürer → kaybolmaz (utterance_lost artmaz)
                else:
                    # BOZUK: resynth yok → kalan metin kaybolur (T2/T1 ihlali)
                    self.unspoken_lost += 1
                    self.utterance_lost += 1
            # ── ses karakteri tutarlılığı: eşdeğer ses (T8/FR-TTS-009) ──────────
            if self.pol.get("preserve_voice", True) and self.secondary_voice:
                self.effective_voice = self.secondary_voice   # eşdeğer → karakter korunur
                self.voice_switches_mapped += 1
            else:
                # BOZUK: eşdeğer ses haritası yok/yok sayıldı → farklı ses → karakter kırılır
                self.voice_switch_unmapped += 1
                self.effective_voice = self.secondary_voice or (target.get("provider_id", "?") + ":default")
            # single stream: teardown → setup (örtüşme yok)
            if not self.pol.get("single_stream", True):
                self.concurrent_active_max = max(self.concurrent_active_max, 2)
            overhead = float(self.primary.get("teardown_ms", 20)) \
                + float(target.get("setup_ms", 40)) + float(target.get("first_byte_ms", 90)) + resynth_time
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
                # BOZUK: birincile geri salınım (flap; T10 ihlali)
                self.flap_count += 1
                self.switched = False
                self.active = "primary"
                if self.primary_voice:
                    self.effective_voice = self.primary_voice
                overhead = float(self.secondary.get("teardown_ms", 20)) \
                    + float(self.primary.get("setup_ms", 40)) + float(self.primary.get("first_byte_ms", 90))
                self.switch_overhead_ms.append(overhead)
                self._activate(self.primary)

    def _route_deterministic(self, reason):
        if self.active in ("deterministic", "dropped"):
            return
        if self.pol.get("deterministic_flow", True):
            self.deterministic_flow_count += 1
            self.active = "deterministic"
        else:
            # BOZUK: deterministik akış yok → çağrı düşürülür (T6 ihlali)
            self.dropped_call += 1
            self.active = "dropped"

    def _normalize(self, raw):
        if raw in ERROR_TAXONOMY:
            return raw
        return self.tax_map.get(raw)

    def end(self, ev):
        self._check_time(ev.get("t"))
        if self.ended:
            raise TtsFallbackError("end tekrar → INVALID_REQUEST")
        reason = ev.get("reason", "normal")
        if reason not in END_REASONS:
            raise TtsFallbackError("geçersiz bitiş nedeni: %r → INVALID_REQUEST" % reason)
        self.ended = True

    def metrics(self):
        scenario = []
        if self.failovers:
            scenario.append("failover" if self.utterance_lost == 0 else "utterance-lost")
        if self.resynth_chars_total > 0:
            scenario.append("resynth")
        if self.voice_switches_mapped:
            scenario.append("voice-mapped")
        if self.voice_switch_unmapped:
            scenario.append("voice-unmapped")
        if self.barge_in_cancel_ms:
            scenario.append("barge-in")
        if self.deterministic_flow_count:
            scenario.append("deterministic-flow")
        if self.dropped_call:
            scenario.append("dropped-call")
        if self.improper_failover:
            scenario.append("improper-failover")
        if self.flap_count:
            scenario.append("flap")
        if not scenario:
            scenario.append("no-failover" if self.speak_complete_total else "empty")
        usage_records = self.segments  # _activate yalnız meter açıkken artırır
        return {
            "primary_id": self.primary.get("provider_id"),
            "secondary_id": self.secondary.get("provider_id"),
            "active_at_end": self.active,
            "logical_voice": self.logical_voice,
            "primary_voice": self.primary_voice,
            "secondary_voice": self.secondary_voice,
            "effective_voice_at_end": self.effective_voice,
            "speak_chunks": self.speak_chunks,
            "speak_complete_total": self.speak_complete_total,
            "failovers": self.failovers,
            "switch_overhead_p95_ms": _percentile(self.switch_overhead_ms, 95),
            "switch_overhead_p50_ms": _percentile(self.switch_overhead_ms, 50),
            "switch_overhead_max_ms": max(self.switch_overhead_ms) if self.switch_overhead_ms else None,
            "barge_in_cancel_p95_ms": _percentile(self.barge_in_cancel_ms, 95),
            "barge_in_cancel_max_ms": max(self.barge_in_cancel_ms) if self.barge_in_cancel_ms else None,
            "resynth_chars_total": round(self.resynth_chars_total, 3),
            "utterance_lost": self.utterance_lost,
            "unspoken_lost": self.unspoken_lost,
            "resynth_replayed_spoken": round(self.resynth_replayed_spoken, 3),
            "duplicate_speech": self.duplicate_speech,
            "concurrent_active_max": self.concurrent_active_max,
            "chunk_after_cancel": self.chunk_after_cancel,
            "dropped_call": self.dropped_call,
            "deterministic_flow_count": self.deterministic_flow_count,
            "improper_failover": self.improper_failover,
            "voice_inconsistent": self.voice_inconsistent,
            "voice_switch_unmapped": self.voice_switch_unmapped,
            "voice_switches_mapped": self.voice_switches_mapped,
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
def simulate(sample, primary, secondary, policy, gates, error_taxonomy,
             logical_voice="voice-default", voice_equivalence=None):
    events = sample.get("events")
    if events is None or not isinstance(events, list) or not events:
        raise TtsFallbackError("boş/geçersiz olay akışı → INVALID_REQUEST")
    rt = TtsFallbackRuntime(primary, secondary, policy, gates, error_taxonomy,
                            logical_voice=logical_voice, voice_equivalence=voice_equivalence,
                            tenant_id=sample.get("tenant_id", "t-self"))
    saw_end = False
    for ev in events:
        if not isinstance(ev, dict):
            raise TtsFallbackError("olay sözlük değil → INVALID_REQUEST")
        kind = ev.get("kind")
        if kind == "start":
            rt.start(ev)
        elif kind == "speak":
            rt.speak(ev)
        elif kind == "complete":
            rt.complete(ev)
        elif kind == "barge_in":
            rt.barge_in(ev)
        elif kind == "provider_error":
            rt.provider_error(ev)
        elif kind == "end":
            rt.end(ev)
            saw_end = True
        else:
            raise TtsFallbackError("bilinmeyen olay tipi: %r → INVALID_REQUEST" % kind)
    if not rt.started:
        raise TtsFallbackError("olay akışında 'start' yok → INVALID_REQUEST")
    if not saw_end:
        raise TtsFallbackError("olay akışında 'end' yok → INVALID_REQUEST")
    return rt.metrics()


def evaluate(gates, m):
    """Metrikleri HARD kapılara (T1–T10 davranışsal) karşı değerlendirir. Döner findings[(ok, label)]."""
    F = []

    # ── T1: FAILOVER — in-flight söz kaybı yok
    F.append((m.get("utterance_lost", 0) <= gates.get("max_utterance_lost", 0),
              "T1 failover: utterance_lost %d ≤ %d (%d failover; çağrı sürer — FR-TTS-008)"
              % (m.get("utterance_lost", 0), gates.get("max_utterance_lost", 0), m.get("failovers", 0))))

    # ── T2: RESYNTH CONTINUATION — kalan metin yeniden sentezlendi, çalınmış tekrar yok
    t2_ok = (m.get("unspoken_lost", 0) <= gates.get("max_unspoken_lost", 0)
             and m.get("resynth_replayed_spoken", 0) <= gates.get("max_resynth_replayed_spoken", 0))
    F.append((t2_ok,
              "T2 resynth: unspoken_lost %d ≤ %d + replayed_spoken %s ≤ %d (%s char resynth; FR-TTS-008/009)"
              % (m.get("unspoken_lost", 0), gates.get("max_unspoken_lost", 0),
                 _fmt(m.get("resynth_replayed_spoken")), gates.get("max_resynth_replayed_spoken", 0),
                 _fmt(m.get("resynth_chars_total")))))

    # ── T3: SWITCH OVERHEAD — sınırlı ölü hava
    so95 = m.get("switch_overhead_p95_ms")
    F.append(((so95 is None or so95 <= gates.get("switch_overhead_p95_ms", 200)),
              "T3 overhead: switch P95 %s ≤ %d ms (sınırlı ölü hava; NFR 10.1/SAD §20)"
              % (_fmt(so95), gates.get("switch_overhead_p95_ms", 200))))

    # ── T4: NO DUPLICATION / SINGLE STREAM
    t4_ok = (m.get("duplicate_speech", 0) <= gates.get("max_duplicate_speech", 0)
             and m.get("concurrent_active_max", 1) <= gates.get("max_concurrent_active", 1))
    F.append((t4_ok,
              "T4 tek-stream: duplicate_speech %d ≤ %d + concurrent_active %d ≤ %d (FR-TTS-002)"
              % (m.get("duplicate_speech", 0), gates.get("max_duplicate_speech", 0),
                 m.get("concurrent_active_max", 1), gates.get("max_concurrent_active", 1))))

    # ── T6: DETERMINISTIC FLOW / NEVER DROP
    F.append((m.get("dropped_call", 0) <= gates.get("max_dropped_call", 0),
              "T6 never-drop: dropped_call %d ≤ %d (%d deterministik akış; BRD §19 (4))"
              % (m.get("dropped_call", 0), gates.get("max_dropped_call", 0),
                 m.get("deterministic_flow_count", 0))))

    # ── T7: SELECTIVE TRIGGER + ERROR NORMALIZED
    norm_ok = (not gates.get("require_error_normalized", True)) \
        or (m.get("errors_normalized", 0) == m.get("errors_seen", 0))
    t7_ok = (m.get("improper_failover", 0) <= gates.get("max_improper_failover", 0)) and norm_ok
    F.append((t7_ok,
              "T7 seçici+normalize: improper_failover %d ≤ %d + err_norm %d/%d (FR-TOOL-008/SAD §8.3)"
              % (m.get("improper_failover", 0), gates.get("max_improper_failover", 0),
                 m.get("errors_normalized", 0), m.get("errors_seen", 0))))

    # ── T8: VOICE CONSISTENCY (FR-TTS-009) — headline
    t8_ok = (m.get("voice_inconsistent", 0) <= gates.get("max_voice_inconsistent", 0)
             and m.get("voice_switch_unmapped", 0) <= gates.get("max_voice_switch_unmapped", 0))
    F.append((t8_ok,
              "T8 ses-tutarlılığı: voice_inconsistent %d ≤ %d + switch_unmapped %d ≤ %d "
              "(%d eşdeğer eşleşme; FR-TTS-009)"
              % (m.get("voice_inconsistent", 0), gates.get("max_voice_inconsistent", 0),
                 m.get("voice_switch_unmapped", 0), gates.get("max_voice_switch_unmapped", 0),
                 m.get("voice_switches_mapped", 0))))

    # ── T9: BARGE-IN PRESERVED — cancel ≤200ms + kesme sonrası ses yok
    bc95 = m.get("barge_in_cancel_p95_ms")
    t9_ok = (bc95 is None or bc95 <= gates.get("barge_in_cancel_p95_ms", 200)) \
        and m.get("chunk_after_cancel", 0) <= gates.get("max_chunk_after_cancel", 0)
    F.append((t9_ok,
              "T9 barge-in: cancel P95 %s ≤ %d ms + chunk_after_cancel %d ≤ %d (FR-TTS-005/NFR 10.1)"
              % (_fmt(bc95), gates.get("barge_in_cancel_p95_ms", 200),
                 m.get("chunk_after_cancel", 0), gates.get("max_chunk_after_cancel", 0))))

    # ── T10: NO FLAP + METERING + RESIDENCY(8kHz/tenant)
    meter_ok = (not gates.get("require_metering", True)) \
        or (m.get("usage_records", 0) == m.get("provider_segments", 0) and m.get("usage_records", 0) > 0)
    t10_ok = (m.get("flap_count", 0) <= gates.get("max_flap", 0)) and meter_ok \
        and m.get("cross_tenant", 0) <= gates.get("max_cross_tenant", 0) \
        and m.get("sample_rate_mismatch", 0) <= gates.get("max_sample_rate_mismatch", 0)
    F.append((t10_ok,
              "T10 flap+metering+8kHz: flap %d ≤ %d + usage %d/%d seg + cross_tenant %d + sr_mismatch %d "
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
    raise TtsFallbackError("bilinmeyen sağlayıcı: %s" % pid)


def _profile_by_name(cfg, name):
    for p in cfg.get("profiles", []):
        if p.get("name") == name:
            return p
    raise TtsFallbackError("bilinmeyen profil: %s" % name)


def _default_policy():
    return {
        "failover": True,
        "resynth": True,
        "resume_from_boundary": True,
        "preserve_voice": True,
        "deterministic_flow": True,
        "selective_trigger": True,
        "single_stream": True,
        "hysteresis": True,
        "dedup": True,
        "honor_cancel": True,
        "meter": True,
        "normalize_errors": True,
        "tenant_isolation": True,
        "order_guard": True,
    }


def _resolve_policy(sample):
    pol = _default_policy()
    pol.update(sample.get("policy", {}))
    return pol


def _resolve_providers(sample, cfg):
    """Döner (primary, secondary, logical_voice, voice_equivalence)."""
    if "primary_obj" in sample and "secondary_obj" in sample:
        return (sample["primary_obj"], sample["secondary_obj"],
                sample.get("voice_id", "voice-default"), sample.get("voice_equivalence", {}))
    prof = _profile_by_name(cfg, sample.get("profile", cfg.get("default_profile")))
    pid = sample.get("primary", prof.get("primary_provider"))
    sid = sample.get("secondary", prof.get("secondary_provider"))
    lv = sample.get("voice_id", prof.get("default_voice", "voice-default"))
    veq = sample.get("voice_equivalence", prof.get("voice_equivalence", {}))
    return (_provider_by_id(cfg, pid), _provider_by_id(cfg, sid), lv, veq)


def simulate_cmd(sample_path):
    spec = _load(SPEC_PATH)
    sample = _load(sample_path)
    name = sample.get("name", os.path.basename(sample_path))
    expect = sample.get("expect", "pass")
    gates = spec.get("gates", {})
    policy = _resolve_policy(sample)

    try:
        cfg = _load(PROFILES_CFG)
        primary, secondary, logical_voice, veq = _resolve_providers(sample, cfg)
    except TtsFallbackError as ex:
        print("simulate[%s]: %s" % (name, ex))
        return 0 if expect == "fail" else 1

    try:
        m = simulate(sample, primary, secondary, policy, gates, spec.get("error_taxonomy", {}),
                     logical_voice=logical_voice, voice_equivalence=veq)
    except TtsFallbackError as ex:
        print("simulate[%s]: REDDEDİLDİ — %s" % (name, ex))
        return 0 if expect == "fail" else 1

    F = evaluate(gates, m)
    print("simulate[%s] primary=%s secondary=%s voice=%s→%s senaryo=%s | %d speak | %d complete | "
          "%d failover | switch P95=%s ms | active@end=%s"
          % (name, m["primary_id"], m["secondary_id"], m["primary_voice"], m["effective_voice_at_end"],
             "+".join(m["scenario"]), m["speak_chunks"], m["speak_complete_total"], m["failovers"],
             _fmt(m["switch_overhead_p95_ms"]), m["active_at_end"]))
    print("  utterance_lost=%d | unspoken_lost=%d | replayed_spoken=%s | resynth=%s char | dup_speech=%d | "
          "voice_inconsistent=%d | voice_unmapped=%d | barge_cancel P95=%s | chunk_after_cancel=%d"
          % (m["utterance_lost"], m["unspoken_lost"], _fmt(m["resynth_replayed_spoken"]),
             _fmt(m["resynth_chars_total"]), m["duplicate_speech"], m["voice_inconsistent"],
             m["voice_switch_unmapped"], _fmt(m["barge_in_cancel_p95_ms"]), m["chunk_after_cancel"]))
    print("  dropped=%d | det_flow=%d | improper=%d | flap=%d | usage=%d/%d seg | err_norm=%d/%d"
          % (m["dropped_call"], m["deterministic_flow_count"], m["improper_failover"], m["flap_count"],
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

    _check(R, spec.get("wbs") == "4.3.2", "spec.wbs == 4.3.2")
    _check(R, spec.get("version"), "spec.version mevcut")

    # ── placement
    pl = spec.get("placement", {})
    _check(R, pl.get("behind_spi") is True and pl.get("orchestrator_depends_on_spi_only") is True,
           "TtsAdapter SPI arkası; orchestrator yalnız SPI'ye + karara bağımlı (ADR-001/SAD §8.1)")
    _check(R, pl.get("turn_state") == "SPEAK", "SPEAK durumunda (SAD §6.1)")
    _check(R, pl.get("stream_first") is True, "akış-önce (stream-first, FR-RES-002)")
    _check(R, pl.get("event_driven") is True and pl.get("non_blocking") is True,
           "olay-tetikli + bloklamaz")
    _check(R, bool(pl.get("circuit_breaker_owned_by")), "T11 circuit breaker 4.1.2'den tüketilir")
    _check(R, bool(pl.get("barge_in_event_source")), "T9 barge-in olayı 2.2.3/3.1.3'ten tüketilir")
    _check(R, bool(pl.get("deterministic_flow_owned_by")), "T11 deterministic flow motoru 8.x/3.3.x")

    # ── spi yüzeyi (T5/T8)
    sp = spec.get("spi", {})
    _check(R, "synthesize" in sp.get("wraps_methods", []) and "cancel" in sp.get("wraps_methods", []),
           "SPI synthesize() + cancel() sarmalanır (SAD §8.1/API §11.3)")
    _check(R, sp.get("presents_single_logical_stream") is True,
           "T4 orchestrator'a tek mantıksal ses akışı sunulur")
    _check(R, sp.get("voice_consistent_across_switch") is True,
           "T8 voiceId anahtarlama boyunca tutarlı (FR-TTS-009)")
    _check(R, set(sp.get("required_features", [])) == REQUIRED_FEATURES,
           "T5 required_features {streaming, barge_in_cancel, pronunciation_dict}")
    _check(R, "voiceId" in sp.get("voice_profile_fields", []),
           "VoiceProfile.voiceId (ses kimliği — FR-TTS-009)")

    # ── kapılar
    g = spec.get("gates", {})
    _check(R, g.get("sample_rate_hz") == 8000, "T10 sample_rate_hz = 8000 (FR-RES-008)")
    _check(R, g.get("switch_overhead_p95_ms") == 200, "T3 switch_overhead_p95_ms = 200 (NFR 10.1)")
    _check(R, g.get("switch_overhead_green_ms", 1e9) < g.get("switch_overhead_p95_ms", 0),
           "T3 yeşil bant < kapı (switch overhead)")
    _check(R, g.get("barge_in_cancel_p95_ms") == 200, "T9 barge_in_cancel_p95_ms = 200 (NFR 10.1/SAD §6.1)")
    _check(R, g.get("barge_in_cancel_green_ms", 1e9) < g.get("barge_in_cancel_p95_ms", 0),
           "T9 yeşil bant < kapı (barge-in cancel)")
    _check(R, g.get("max_utterance_lost", -1) == 0, "T1 max_utterance_lost = 0")
    _check(R, g.get("max_unspoken_lost", -1) == 0, "T2 max_unspoken_lost = 0")
    _check(R, g.get("max_resynth_replayed_spoken", -1) == 0, "T2 max_resynth_replayed_spoken = 0")
    _check(R, g.get("max_duplicate_speech", -1) == 0, "T4 max_duplicate_speech = 0")
    _check(R, g.get("max_concurrent_active", -1) == 1, "T4 max_concurrent_active = 1 (tek stream)")
    _check(R, g.get("max_chunk_after_cancel", -1) == 0, "T9 max_chunk_after_cancel = 0 (talk-over yok)")
    _check(R, g.get("max_dropped_call", -1) == 0, "T6 max_dropped_call = 0 (never drop)")
    _check(R, g.get("max_improper_failover", -1) == 0, "T7 max_improper_failover = 0 (seçici tetik)")
    _check(R, g.get("max_voice_inconsistent", -1) == 0, "T8 max_voice_inconsistent = 0 (FR-TTS-009)")
    _check(R, g.get("max_voice_switch_unmapped", -1) == 0, "T8 max_voice_switch_unmapped = 0 (eşdeğer ses)")
    _check(R, g.get("max_flap", -1) == 0, "T10 max_flap = 0 (histerezis)")
    _check(R, g.get("max_cross_tenant", -1) == 0, "T10 max_cross_tenant = 0")
    _check(R, g.get("min_providers", 0) >= 2, "T5 min_providers ≥ 2 (ADR-002 / BRD §19 (1))")
    _check(R, g.get("require_deterministic_flow") is True, "T6 require_deterministic_flow")
    _check(R, g.get("require_error_normalized") is True, "T7 require_error_normalized (FR-TOOL-008)")
    _check(R, g.get("require_metering") is True, "T10 require_metering (FR-BIL-002)")
    _check(R, g.get("require_equivalent_voice") is True, "T5/T8 require_equivalent_voice (FR-TTS-009)")
    _check(R, set(g.get("required_features", [])) == REQUIRED_FEATURES,
           "gates required_features SPI ile tutarlı")
    _check(R, set(g.get("failover_error_classes", [])) == FAILOVER_CLASSES,
           "T7 failover_error_classes = {TIMEOUT, UNAVAILABLE, RATE_LIMITED} (yalnız geçici)")

    # ── fallback zinciri (T1/T2/T6/T8)
    fb = spec.get("fallback", {})
    _check(R, fb.get("chain") == ["primary_tts", "secondary_tts", "deterministic_flow"],
           "T1/T6 fallback zinciri primary→secondary→deterministic (SAD §8.3)")
    _check(R, fb.get("min_providers", 0) >= 2 and fb.get("resynth_continuation") is True,
           "T2/T5 fallback ≥2 sağlayıcı + resynth continuation (FR-TTS-008)")
    _check(R, fb.get("equivalent_voice_required") is True, "T8 eşdeğer ses zorunlu (FR-TTS-009)")
    _check(R, fb.get("hysteresis_sticky_secondary") is True, "T10 histerezis (sticky secondary, flap yok)")
    _check(R, fb.get("deterministic_flow_on_total_failure") is True, "T6 her iki düşerse deterministik akış")
    _check(R, fb.get("switching_owned_by", "").startswith("4.3.2"),
           "fallback anahtarlama BU görevde (4.3.2)")

    # ── voice_consistency bloğu (T8/FR-TTS-009)
    vc = spec.get("voice_consistency", {})
    _check(R, vc.get("voice_id_stable_within_call") is True,
           "T8 voiceId çağrı boyu sabit (FR-TTS-009)")
    _check(R, vc.get("equivalent_voice_on_fallback") is True,
           "T8 fallback'te eşdeğer ses (FR-TTS-009)")

    # ── metrikler → observability
    me = spec.get("metrics", {})
    emitted = set(me.get("emitted", []))
    _check(R, {"tts_fallback_total", "tts_switch_overhead_ms", "tts_resynth_chars_total",
               "tts_voice_switch_total", "tts_barge_in_cancel_ms", "tts_deterministic_flow_total",
               "tts_speak_complete_total"} <= emitted,
           "metrikler: fallback + switch_overhead + resynth + voice_switch + barge-in + det_flow + complete")
    _check(R, len(me.get("maps_to_observability", {})) >= 1,
           "metrik observability'ye eşlenir (0.4.7)")

    # ── error taxonomy (T7/T11)
    et = spec.get("error_taxonomy", {})
    mapping = et.get("mapping", {})
    _check(R, len(mapping) >= 5, "T11 hata eşlemesi (≥5)")
    _check(R, all(v in ERROR_TAXONOMY for v in mapping.values()),
           "T11 tüm hedefler API §11.6 ErrorTaxonomy'de")
    _check(R, mapping.get("provider_timeout") == "TIMEOUT"
           and mapping.get("provider_5xx") == "UNAVAILABLE"
           and mapping.get("circuit_open") == "UNAVAILABLE"
           and mapping.get("auth_failure") == "AUTH"
           and mapping.get("region_mismatch") == "REGION_VIOLATION",
           "T7/T11 timeout→TIMEOUT, 5xx/circuit→UNAVAILABLE, auth→AUTH, bölge→REGION_VIOLATION")
    _check(R, set(et.get("failover_classes", [])) == FAILOVER_CLASSES
           and set(et.get("non_failover_classes", [])) == {"AUTH", "INVALID_REQUEST", "REGION_VIOLATION"},
           "T7 failover_classes geçici + non_failover_classes geçici-olmayan")

    # ── residency + pii (T10/T11)
    rs = spec.get("residency", {})
    _check(R, rs.get("region_pin_required") is True, "T10 residency region pin (NFR 10.7)")
    _check(R, rs.get("no_log_required") is True
           and set(rs.get("allowed_retention", [])) <= ALLOWED_RETENTION,
           "T10 no-log: data_retention NONE/EPHEMERAL (FR-KB-010)")
    _check(R, rs.get("resynth_buffer_ephemeral") is True, "T2 resynth tamponu ephemeral (durable değil)")
    pii = spec.get("pii", {})
    _check(R, pii.get("raw_audio_in_spec_forbidden") is True
           and pii.get("raw_text_in_spec_forbidden") is True
           and pii.get("pii_value_in_spec_forbidden") is True,
           "T11 ham ses/metin/PII değeri spec'te yasak")

    # ── invariant kataloğu
    inv_ids = [i.get("id") for i in spec.get("invariants", [])]
    _check(R, len(inv_ids) == len(set(inv_ids)) and len(inv_ids) >= 11,
           "invariant kataloğu ≥11 + tekil ID")
    _check(R, all(i.get("trace") for i in spec.get("invariants", [])),
           "her invariant trace taşır")

    # ── literal sır taraması (spec + config)
    hits = _scan_secrets(spec)
    if os.path.exists(PROFILES_CFG):
        hits += _scan_secrets(_load(PROFILES_CFG))
    _check(R, not hits, "T11 literal sır yok (spec+config)")

    # ── config sağlayıcı + profil + eşdeğer-ses doğrulaması (T5/T8)
    if os.path.exists(PROFILES_CFG):
        cfg = _load(PROFILES_CFG)
        provs = cfg.get("providers", [])
        conformant = [p for p in provs if _provider_conformant(p)]
        _check(R, len(conformant) >= g.get("min_providers", 2),
               "T5 ≥%d SPI-uyumlu sağlayıcı (streaming+barge_in_cancel+pronunciation_dict + 8 kHz)"
               % g.get("min_providers", 2))
        pids = [p.get("provider_id") for p in provs]
        _check(R, len(pids) == len(set(pids)), "config sağlayıcı ID'leri benzersiz")
        profs = cfg.get("profiles", [])
        _check(R, len(profs) >= 2, "config ≥2 çalıştırma profili")
        for prof in profs:
            nm = prof.get("name")
            _check(R, bool(prof.get("region")), "T10 config %s bölge pini var" % nm)
            pp_id, sp_id = prof.get("primary_provider"), prof.get("secondary_provider")
            _check(R, pp_id in pids and sp_id in pids,
                   "T5 config %s primary+secondary geçerli sağlayıcı" % nm)
            _check(R, pp_id != sp_id, "T5 config %s primary≠secondary (≥2 sağlayıcı)" % nm)
            pp = _provider_by_id(cfg, pp_id)
            spv = _provider_by_id(cfg, sp_id)
            _check(R, _provider_conformant(pp) and _provider_conformant(spv),
                   "T5 config %s primary+secondary SPI-uyumlu" % nm)
            _check(R, set(pp.get("data_retention", "").split()) <= ALLOWED_RETENTION
                   and set(spv.get("data_retention", "").split()) <= ALLOWED_RETENTION,
                   "T10 config %s primary+secondary data_retention NONE/EPHEMERAL" % nm)
            # ── eşdeğer ses haritası (T8/FR-TTS-009): default_voice primary+secondary'de tanımlı +
            #    fiziksel ses ilgili sağlayıcının voices listesinde
            dv = prof.get("default_voice")
            veq = prof.get("voice_equivalence", {})
            entry = veq.get(dv, {}) if dv else {}
            pv = entry.get(pp_id)
            sv = entry.get(sp_id)
            _check(R, bool(pv) and bool(sv),
                   "T8 config %s default_voice '%s' primary+secondary eşdeğer ses tanımlı (FR-TTS-009)"
                   % (nm, dv))
            _check(R, (pv in pp.get("voices", [])) and (sv in spv.get("voices", [])),
                   "T8 config %s eşdeğer fiziksel ses sağlayıcı voices listesinde" % nm)

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
    "provider_id": "tts-stream-A", "features": ["streaming", "barge_in_cancel", "pronunciation_dict"],
    "sample_rates": [8000, 16000], "data_retention": "NONE", "voices": ["A-tr-f-warm"],
    "setup_ms": 60, "teardown_ms": 20, "first_byte_ms": 90, "cancel_ms": 70, "resynth_rtf": 0.20,
}
PROVIDER_B = {
    "provider_id": "tts-stream-B", "features": ["streaming", "barge_in_cancel", "pronunciation_dict"],
    "sample_rates": [8000, 16000], "data_retention": "EPHEMERAL", "voices": ["B-tr-f-warm"],
    "setup_ms": 35, "teardown_ms": 15, "first_byte_ms": 110, "cancel_ms": 60, "resynth_rtf": 0.18,
}
VOICE_EQUIV = {"voice-tr-warm": {"tts-stream-A": "A-tr-f-warm", "tts-stream-B": "B-tr-f-warm"}}


def _start(t=0, sr=8000, tenant=None, voice="voice-tr-warm"):
    ev = {"kind": "start", "t": t, "sample_rate_hz": sr, "voice_id": voice}
    if tenant:
        ev["tenant_id"] = tenant
    return ev


def _speak(t, u, char_len=40, dur=600, remaining=None, voice=None, cached=None):
    ev = {"kind": "speak", "t": t, "utterance_id": u, "char_len": char_len, "dur_ms": dur}
    if remaining is not None:
        ev["remaining_chars"] = remaining
    if voice is not None:
        ev["voice_id"] = voice
    if cached is not None:
        ev["cached"] = cached
    return ev


def _complete(t, u):
    return {"kind": "complete", "t": t, "utterance_id": u}


def _barge(t, u=None):
    ev = {"kind": "barge_in", "t": t}
    if u is not None:
        ev["utterance_id"] = u
    return ev


def _err(t, raw="provider_timeout", u=None):
    ev = {"kind": "provider_error", "t": t, "raw_error": raw}
    if u is not None:
        ev["utterance_id"] = u
    return ev


def _end(t, reason="normal"):
    return {"kind": "end", "t": t, "reason": reason}


def _run(events, primary=None, secondary=None, voice="voice-tr-warm", veq=None, **pol_over):
    spec = _load(SPEC_PATH)
    pol = _default_policy()
    pol.update(pol_over)
    return simulate({"events": events}, primary or PROVIDER_A, secondary or PROVIDER_B,
                    pol, spec.get("gates", {}), spec.get("error_taxonomy", {}),
                    logical_voice=voice, voice_equivalence=veq if veq is not None else VOICE_EQUIV)


def selftest():
    spec = _load(SPEC_PATH)
    gates = spec.get("gates", {})
    cases = []

    def case(ok, label):
        cases.append((bool(ok), label))

    # 0) validate iyi spec+config'te geçer
    case(_validate_obj(_load(SPEC_PATH)) == 0, "validate iyi spec+config'te 0 döndürür")

    # ── happy: failover + resynth continuation + eşdeğer ses (T1–T10) ──────────────
    mh = _run([
        _start(0),
        _speak(100, "u1", 40, 600, remaining=0), _complete(700, "u1"),
        _speak(2000, "u2", 30, 500, remaining=50),   # in-flight söz, 50 char kalan
        _err(2500, "provider_timeout", "u2"),         # birincil timeout → failover + resynth
        _speak(2900, "u2", 50, 800, remaining=0, voice="B-tr-f-warm"),  # ikincide eşdeğer ses
        _complete(3700, "u2"),
        _end(6000, "normal"),
    ])
    case(mh["failovers"] == 1 and mh["utterance_lost"] == 0, "happy: 1 failover, söz kaybı yok (T1)")
    case(mh["resynth_chars_total"] == 50.0 and mh["unspoken_lost"] == 0
         and mh["resynth_replayed_spoken"] == 0, "happy: 50 char kalan resynth, çalınmış tekrar yok (T2)")
    case(mh["switch_overhead_p95_ms"] is not None and mh["switch_overhead_p95_ms"] <= 200,
         "happy: switch overhead ≤200ms (T3)")
    case(mh["duplicate_speech"] == 0 and mh["concurrent_active_max"] == 1, "happy: dup-speech yok + tek stream (T4)")
    case(mh["dropped_call"] == 0, "happy: çağrı düşmedi (T6)")
    case(mh["improper_failover"] == 0 and mh["errors_normalized"] == mh["errors_seen"] == 1,
         "happy: seçici tetik + normalize (T7)")
    case(mh["voice_inconsistent"] == 0 and mh["voice_switch_unmapped"] == 0
         and mh["voice_switches_mapped"] == 1 and mh["effective_voice_at_end"] == "B-tr-f-warm",
         "happy: eşdeğer ses (A-tr-f-warm→B-tr-f-warm), karakter tutarlı (T8/FR-TTS-009)")
    case(mh["flap_count"] == 0 and mh["usage_records"] == mh["provider_segments"] == 2,
         "happy: flap yok + 2 segment metering (T10)")
    case(all(ok for ok, _ in evaluate(gates, mh)), "happy tüm kapıları geçer")
    case(mh["speak_complete_total"] == 2, "happy: 2 söz tamamlandı (u1 birincil, u2 ikincil)")

    # ── determinizm ───────────────────────────────────────────────────────────────
    ev = [_start(0), _speak(100, "u1", 30, 500, remaining=20), _err(400, "circuit_open", "u1"),
          _speak(700, "u1", 20, 300, voice="B-tr-f-warm"), _complete(1000, "u1"), _end(2000)]
    case(_run(ev) == _run(ev), "determinizm: aynı olay-akışı birebir aynı metrik (random yok)")

    # ── no-failover happy: hatasız çağrı geçer ─────────────────────────────────────
    mn = _run([_start(0), _speak(100, "u1", 40, 600, remaining=0), _complete(700, "u1"), _end(1000)])
    case(mn["failovers"] == 0 and mn["speak_complete_total"] == 1 and all(ok for ok, _ in evaluate(gates, mn)),
         "no-failover: hatasız çağrı tüm kapıları geçer")

    # ── ≥2 sağlayıcı: ikincil farklı (B) + eşdeğer ses ─────────────────────────────
    case(mh["primary_id"] == "tts-stream-A" and mh["secondary_id"] == "tts-stream-B",
         "≥2 sağlayıcı: primary A + secondary B (ADR-002 / BRD §19 (1))")
    case(mh["primary_voice"] == "A-tr-f-warm" and mh["secondary_voice"] == "B-tr-f-warm",
         "eşdeğer ses haritası: A-tr-f-warm ↔ B-tr-f-warm (FR-TTS-009)")

    # ── barge-in: kesme ≤200ms + kesme sonrası ses yok (T9) ────────────────────────
    mbi = _run([_start(0), _speak(100, "u1", 40, 800, remaining=30), _barge(400, "u1"),
                _speak(500, "u1", 30, 400),  # kesme sonrası chunk → bastırılır (honor_cancel)
                _end(2000)])
    case(mbi["barge_in_cancel_p95_ms"] is not None and mbi["barge_in_cancel_p95_ms"] <= 200
         and mbi["chunk_after_cancel"] == 0, "barge-in: cancel ≤200ms + kesme sonrası ses yok (T9)")
    case(all(ok for ok, _ in evaluate(gates, mbi)), "barge-in tüm kapıları geçer")

    # ── barge-in failover SONRASI da çalışır (T9 + ikincil cancel_ms) ──────────────
    mbf = _run([_start(0), _speak(100, "u1", 30, 500, remaining=40), _err(400, "provider_timeout", "u1"),
                _speak(700, "u1", 40, 700, voice="B-tr-f-warm"), _barge(900, "u1"), _end(2000)])
    case(mbf["failovers"] == 1 and mbf["barge_in_cancel_max_ms"] == 60.0,
         "barge-in failover sonrası ikincil sağlayıcıda da kesilir (cancel_ms=60)")
    case(all(ok for ok, _ in evaluate(gates, mbf)), "barge-in-after-failover tüm kapıları geçer")

    # ── both-fail → deterministic flow, çağrı düşmez (T6 geçer) ────────────────────
    mb = _run([
        _start(0), _speak(100, "u1", 30, 500, remaining=20), _err(400, "provider_timeout", "u1"),  # → secondary
        _speak(700, "u1", 20, 300, voice="B-tr-f-warm"), _complete(1000, "u1"),
        _speak(2000, "u2", 30, 500, remaining=20), _err(2300, "provider_5xx", "u2"),  # secondary de düştü
        _end(4000, "transfer"),
    ])
    case(mb["failovers"] == 1 and mb["deterministic_flow_count"] == 1 and mb["dropped_call"] == 0,
         "both-fail: secondary de düşünce deterministik akış, çağrı düşmez (T6)")
    case(all(ok for ok, _ in evaluate(gates, mb)), "both-fail deterministic flow tüm kapıları geçer")

    # ── selective trigger: AUTH failover ETMEZ → deterministic (T7 geçer) ──────────
    ma = _run([_start(0), _speak(100, "u1", 30, 500, remaining=20), _err(400, "auth_failure", "u1"),
               _end(2000, "transfer")])
    case(ma["failovers"] == 0 and ma["improper_failover"] == 0 and ma["deterministic_flow_count"] == 1,
         "selective: AUTH geçici değil → failover yok, deterministik akış (T7)")
    case(all(ok for ok, _ in evaluate(gates, ma)), "selective AUTH tüm kapıları geçer")

    # ── degraded-1: resynth kapalı → kalan metin kaybolur (T1/T2 eler) ─────────────
    d1 = _run([_start(0), _speak(100, "u1", 30, 500, remaining=40),
               _err(700, "provider_timeout", "u1"), _end(3000)], resynth=False)
    case(d1["unspoken_lost"] >= 1 and d1["utterance_lost"] >= 1,
         "degraded(no-resynth): kalan metin yeniden sentezlenmedi → kayıp (FR-TTS-008 ihlali)")
    case(not all(ok for ok, _ in evaluate(gates, d1)), "degraded(no-resynth) T1/T2 eler")

    # ── degraded-2: failover kapalı → söz kaybolur (T1 eler) ───────────────────────
    d2 = _run([_start(0), _speak(100, "u1", 30, 500, remaining=40), _err(400, "provider_timeout", "u1"),
               _end(2000)], failover=False)
    case(d2["failovers"] == 0 and d2["utterance_lost"] >= 1,
         "degraded(no-failover): geçici hatada anahtarlama yok → söz kaybı (T1)")
    case(not all(ok for ok, _ in evaluate(gates, d2)), "degraded(no-failover) T1 eler")

    # ── degraded-3: kesme noktasından devam etmez → çalınmış metin tekrar (T2/T4 eler) ──
    d3 = _run([_start(0), _speak(100, "u1", 35, 600, remaining=40), _err(700, "provider_timeout", "u1"),
               _speak(1000, "u1", 40, 700, voice="B-tr-f-warm"), _complete(1700, "u1"), _end(3000)],
              resume_from_boundary=False)
    case(d3["resynth_replayed_spoken"] >= 35 and d3["duplicate_speech"] >= 1,
         "degraded(no-resume): baştan sentez → zaten çalınmış metin tekrar seslendirildi (T2/T4)")
    case(not all(ok for ok, _ in evaluate(gates, d3)), "degraded(no-resume) T2/T4 eler")

    # ── degraded-4: eşdeğer ses yok sayıldı → karakter kırılır (T8 eler) ────────────
    d4 = _run([_start(0), _speak(100, "u1", 30, 500, remaining=20), _err(400, "provider_timeout", "u1"),
               _speak(700, "u1", 20, 300), _complete(1000, "u1"), _end(2000)], preserve_voice=False)
    case(d4["voice_switch_unmapped"] >= 1, "degraded(no-preserve-voice): fallback'te farklı ses → karakter kırıldı (FR-TTS-009)")
    case(not all(ok for ok, _ in evaluate(gates, d4)), "degraded(no-preserve-voice) T8 eler")

    # ── degraded-5: eşdeğer ses haritası eksik (secondary için) → unmapped (T8 eler) ──
    d5 = _run([_start(0), _speak(100, "u1", 30, 500, remaining=20), _err(400, "provider_timeout", "u1"),
               _speak(700, "u1", 20, 300), _complete(1000, "u1"), _end(2000)],
              veq={"voice-tr-warm": {"tts-stream-A": "A-tr-f-warm"}})  # B eşdeğeri yok
    case(d5["voice_switch_unmapped"] >= 1, "degraded(no-equiv-map): ikincil eşdeğer ses tanımsız → unmapped (T8)")
    case(not all(ok for ok, _ in evaluate(gates, d5)), "degraded(no-equiv-map) T8 eler")

    # ── degraded-6: mid-call voice drift (aynı sağlayıcıda farklı ses) → (T8 eler) ──
    d6 = _run([_start(0), _speak(100, "u1", 30, 500, remaining=0, voice="A-tr-m-other"),  # drift
               _complete(700, "u1"), _end(2000)])
    case(d6["voice_inconsistent"] >= 1, "degraded(voice-drift): mid-call voiceId değişti (FR-TTS-009)")
    case(not all(ok for ok, _ in evaluate(gates, d6)), "degraded(voice-drift) T8 eler")

    # ── degraded-7: barge-in onurlanmadı → kesme sonrası ses (T9 eler) ─────────────
    d7 = _run([_start(0), _speak(100, "u1", 40, 800, remaining=30), _barge(400, "u1"),
               _speak(500, "u1", 30, 400), _end(2000)], honor_cancel=False)
    case(d7["chunk_after_cancel"] >= 1, "degraded(no-honor-cancel): kesme sonrası ses chunk'ı çıktı (talk-over; T9)")
    case(not all(ok for ok, _ in evaluate(gates, d7)), "degraded(no-honor-cancel) T9 eler")

    # ── degraded-8: deterministic flow kapalı → çağrı düşer (T6 eler) ──────────────
    d8 = _run([_start(0), _speak(100, "u1", 30, 500, remaining=20), _err(400, "provider_timeout", "u1"),
               _speak(700, "u1", 20, 300, voice="B-tr-f-warm"), _complete(1000, "u1"),
               _speak(2000, "u2", 30, 500, remaining=20), _err(2300, "provider_5xx", "u2"), _end(4000)],
              deterministic_flow=False)
    case(d8["dropped_call"] >= 1, "degraded(no-det-flow): her iki düşünce çağrı düşürüldü (BRD §19 (4) ihlali)")
    case(not all(ok for ok, _ in evaluate(gates, d8)), "degraded(no-det-flow) T6 eler")

    # ── degraded-9: seçici tetik kapalı → AUTH'ta boşuna failover (T7 eler) ─────────
    d9 = _run([_start(0), _speak(100, "u1", 30, 500, remaining=20), _err(400, "auth_failure", "u1"),
               _speak(700, "u1", 20, 300, voice="B-tr-f-warm"), _complete(1000, "u1"), _end(2000)],
              selective_trigger=False)
    case(d9["improper_failover"] >= 1, "degraded(no-selective): AUTH'ta boşuna anahtarlama (T7)")
    case(not all(ok for ok, _ in evaluate(gates, d9)), "degraded(no-selective) T7 eler")

    # ── degraded-10: histerezis kapalı → flap (T10 eler) ───────────────────────────
    d10 = _run([_start(0), _speak(100, "u1", 30, 500, remaining=20), _err(400, "provider_timeout", "u1"),
                _speak(700, "u1", 20, 300, voice="B-tr-f-warm"), _complete(1000, "u1"),
                _speak(2000, "u2", 30, 500, remaining=20), _err(2300, "provider_timeout", "u2"),
                _complete(2700, "u2"), _end(4000)], hysteresis=False)
    case(d10["flap_count"] >= 1, "degraded(no-hysteresis): secondary hatasında birincile geri salınım (flap; T10)")
    case(not all(ok for ok, _ in evaluate(gates, d10)), "degraded(no-hysteresis) T10 eler")

    # ── degraded-11: dedup kapalı → çift complete (T4 eler) ────────────────────────
    d11 = _run([_start(0), _speak(100, "u1", 40, 600, remaining=0), _complete(700, "u1"),
                _complete(800, "u1"), _end(2000)], dedup=False)
    case(d11["duplicate_speech"] >= 1, "degraded(no-dedup): aynı söz iki complete → duplicate (T4)")
    case(not all(ok for ok, _ in evaluate(gates, d11)), "degraded(no-dedup) T4 eler")

    # ── degraded-12: tek stream kapalı → eşzamanlı çift aktif (T4 eler) ─────────────
    d12 = _run([_start(0), _speak(100, "u1", 30, 500, remaining=20), _err(400, "provider_timeout", "u1"),
                _speak(700, "u1", 20, 300, voice="B-tr-f-warm"), _complete(1000, "u1"), _end(2000)],
               single_stream=False)
    case(d12["concurrent_active_max"] >= 2, "degraded(dual-stream): anahtarlamada eşzamanlı çift aktif (T4)")
    case(not all(ok for ok, _ in evaluate(gates, d12)), "degraded(dual-stream) T4 eler")

    # ── degraded-13: metering kapalı → UsageRecord eksik (T10 eler) ────────────────
    d13 = _run([_start(0), _speak(100, "u1", 40, 600, remaining=0), _complete(700, "u1"), _end(1000)],
               meter=False)
    case(d13["usage_records"] == 0, "degraded(no-meter): UsageRecord üretilmedi (FR-BIL-002)")
    case(not all(ok for ok, _ in evaluate(gates, d13)), "degraded(no-meter) T10 eler")

    # ── degraded-14: hata normalize edilmedi (T7 eler) ─────────────────────────────
    d14 = _run([_start(0), _speak(100, "u1", 30, 500, remaining=20), _err(400, "raw-provider-503", "u1"),
                _speak(700, "u1", 20, 300, voice="B-tr-f-warm"), _complete(1000, "u1"), _end(2000)],
               normalize_errors=False)
    case(d14["errors_seen"] == 1 and d14["errors_normalized"] == 0,
         "degraded(no-norm): sağlayıcı hatası ErrorTaxonomy'ye çevrilmedi (FR-TOOL-008)")
    case(not all(ok for ok, _ in evaluate(gates, d14)), "degraded(no-norm) T7 eler")

    # ── degraded-15: yavaş sağlayıcı (C) → switch overhead kapısı eler (T3) ─────────
    slow = {"provider_id": "tts-stream-C", "features": ["streaming"], "sample_rates": [8000],
            "data_retention": "NONE", "voices": ["C-en-generic"],
            "setup_ms": 260, "teardown_ms": 90, "first_byte_ms": 300, "cancel_ms": 320, "resynth_rtf": 1.10}
    d15 = _run([_start(0), _speak(100, "u1", 50, 900, remaining=60), _err(700, "provider_timeout", "u1"),
                _speak(1100, "u1", 60, 1000), _complete(2100, "u1"), _end(3000)],
               secondary=slow, veq={"voice-tr-warm": {"tts-stream-A": "A-tr-f-warm", "tts-stream-C": "C-x"}})
    case(d15["switch_overhead_max_ms"] is not None and d15["switch_overhead_max_ms"] > 200,
         "degraded(slow-secondary): teardown+setup+first_byte+resynth > 200ms (T3)")
    case(not all(ok for ok, _ in evaluate(gates, d15)), "degraded(slow-secondary) T3 eler")

    # ── degraded-16: yavaş cancel (C) → barge-in kapısı eler (T9) ───────────────────
    d16 = _run([_start(0), _speak(100, "u1", 40, 800, remaining=30), _barge(400, "u1"), _end(2000)],
               primary=slow, veq={"voice-tr-warm": {"tts-stream-C": "C-x", "tts-stream-B": "B-tr-f-warm"}})
    case(d16["barge_in_cancel_max_ms"] is not None and d16["barge_in_cancel_max_ms"] > 200,
         "degraded(slow-cancel): barge-in cancel > 200ms (T9)")
    case(not all(ok for ok, _ in evaluate(gates, d16)), "degraded(slow-cancel) T9 eler")

    # ── degraded-17: 8 kHz dışı sample rate (T10 eler) ─────────────────────────────
    d17 = _run([_start(0, sr=16000), _speak(100, "u1", 40, 600, remaining=0), _complete(700, "u1"), _end(1000)])
    case(d17["sample_rate_mismatch"] >= 1, "degraded(non-8khz): sample_rate≠8000 (FR-RES-008)")
    case(not all(ok for ok, _ in evaluate(gates, d17)), "degraded(non-8khz) T10 eler")

    # ── geçersiz olay reddi (T11) ──────────────────────────────────────────────────
    case(_raises(lambda: _run([_speak(0, "u1", 40, 600), _end(10)])), "T11 start'tan önce speak → reddedilir")
    case(_raises(lambda: _run([_start(0), _speak(10, "u1", 40, 600)])), "T11 'end' olmadan → reddedilir")
    case(_raises(lambda: _run([_speak(0, "u1", 40, 600)])), "T11 'start' olmadan → reddedilir")
    case(_raises(lambda: _run([_start(0), _start(1), _end(2)])), "T11 tekrar start → reddedilir")
    case(_raises(lambda: _run([_start(1000), _speak(0, "u1", 40, 600), _end(2000)])), "T11 out-of-order → reddedilir")
    case(_raises(lambda: _run([_start(0), {"kind": "nope", "t": 1}, _end(2)])), "T11 bilinmeyen olay → reddedilir")
    case(_raises(lambda: simulate({"events": [_start(0), {"kind": "provider_error", "t": 10}, _end(20)]},
                                  PROVIDER_A, PROVIDER_B, _default_policy(), gates,
                                  spec.get("error_taxonomy", {}), voice_equivalence=VOICE_EQUIV)),
         "T11 raw_error'suz provider_error → reddedilir")
    case(_raises(lambda: _run([_start(0), {"kind": "speak", "t": 10, "utterance_id": "u1", "char_len": -3},
                               _end(20)])), "T11 negatif char_len → reddedilir")
    case(_raises(lambda: simulate({"events": []}, PROVIDER_A, PROVIDER_B, _default_policy(), gates,
                                  spec.get("error_taxonomy", {}), voice_equivalence=VOICE_EQUIV)),
         "T11 boş olay akışı → reddedilir")
    case(_raises(lambda: _run([_start(0, tenant="t-other"), _end(50)])),
         "T11 cross-tenant (izolasyon açık) → reddedilir")
    case(_raises(lambda: _run([_start(0), _end(10, reason="weird")])), "T11 geçersiz bitiş nedeni → reddedilir")

    # ── validate negatif kapılar ────────────────────────────────────────────────────
    s = json.loads(json.dumps(spec)); s["gates"]["sample_rate_hz"] = 16000
    case(_validate_obj(s) != 0, "T10 sample_rate_hz≠8000 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["switch_overhead_p95_ms"] = 999
    case(_validate_obj(s) != 0, "T3 switch_overhead_p95_ms≠200 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["barge_in_cancel_p95_ms"] = 999
    case(_validate_obj(s) != 0, "T9 barge_in_cancel_p95_ms≠200 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_utterance_lost"] = 1
    case(_validate_obj(s) != 0, "T1 max_utterance_lost>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_unspoken_lost"] = 1
    case(_validate_obj(s) != 0, "T2 max_unspoken_lost>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_resynth_replayed_spoken"] = 1
    case(_validate_obj(s) != 0, "T2 max_resynth_replayed_spoken>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_duplicate_speech"] = 1
    case(_validate_obj(s) != 0, "T4 max_duplicate_speech>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_concurrent_active"] = 2
    case(_validate_obj(s) != 0, "T4 max_concurrent_active≠1 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_chunk_after_cancel"] = 1
    case(_validate_obj(s) != 0, "T9 max_chunk_after_cancel>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_dropped_call"] = 1
    case(_validate_obj(s) != 0, "T6 max_dropped_call>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_improper_failover"] = 1
    case(_validate_obj(s) != 0, "T7 max_improper_failover>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_voice_inconsistent"] = 1
    case(_validate_obj(s) != 0, "T8 max_voice_inconsistent>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_voice_switch_unmapped"] = 1
    case(_validate_obj(s) != 0, "T8 max_voice_switch_unmapped>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_flap"] = 1
    case(_validate_obj(s) != 0, "T10 max_flap>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["min_providers"] = 1
    case(_validate_obj(s) != 0, "T5 min_providers<2 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["require_equivalent_voice"] = False
    case(_validate_obj(s) != 0, "T5/T8 require_equivalent_voice=false → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["require_deterministic_flow"] = False
    case(_validate_obj(s) != 0, "T6 require_deterministic_flow=false → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["failover_error_classes"] = ["TIMEOUT", "AUTH"]
    case(_validate_obj(s) != 0, "T7 failover_error_classes geçici-olmayan içerir → validate eler")
    s = json.loads(json.dumps(spec)); s["fallback"]["chain"] = ["primary_tts", "secondary_tts"]
    case(_validate_obj(s) != 0, "T6 zincirde deterministic_flow yok → validate eler")
    s = json.loads(json.dumps(spec)); s["fallback"]["equivalent_voice_required"] = False
    case(_validate_obj(s) != 0, "T8 fallback.equivalent_voice_required=false → validate eler")
    s = json.loads(json.dumps(spec)); s["error_taxonomy"]["mapping"]["x"] = "NOPE"
    case(_validate_obj(s) != 0, "T11 taksonomi-dışı → validate eler")
    s = json.loads(json.dumps(spec)); s["pii"]["pii_value_in_spec_forbidden"] = False
    case(_validate_obj(s) != 0, "T11 pii-değer-yasak kapalı → validate eler")
    s = json.loads(json.dumps(spec)); s["residency"]["allowed_retention"] = ["PROVIDER_DEFAULT"]
    case(_validate_obj(s) != 0, "T10 no-log dışı retention → validate eler")
    s = json.loads(json.dumps(spec)); s["spi"]["required_features"] = ["streaming", "x"]
    case(_validate_obj(s) != 0, "T5 fazladan required_features → validate eler")
    s = json.loads(json.dumps(spec)); s["spi"]["voice_consistent_across_switch"] = False
    case(_validate_obj(s) != 0, "T8 voice_consistent_across_switch=false → validate eler")
    s = json.loads(json.dumps(spec)); s["metrics"]["secret"] = "api_key: AKIAIOSFODNN7EXAMPLE"
    case(_validate_obj(s) != 0, "T11 literal secret → validate eler")

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
    except TtsFallbackError:
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
    print("""tts-fallback-spec.json beklenen şekli (WBS 4.3.2):
  wbs, version, phase, trace{fr,nfr,sad,adr,api,brd,srs,rtm,poc,vendor_eval,consumes,observability}
  placement{behind_spi=true, orchestrator_depends_on_spi_only=true, turn_state=SPEAK,
            stream_first=true, event_driven=true, non_blocking=true,
            circuit_breaker_owned_by, barge_in_event_source, deterministic_flow_owned_by}        (T1,T9,T11)
  spi{wraps_methods[synthesize,cancel,...], voice_profile_fields[voiceId,...], required_features
      [streaming,barge_in_cancel,pronunciation_dict], presents_single_logical_stream=true,
      voice_consistent_across_switch=true}                                                       (T4,T5,T8)
  gates{sample_rate_hz=8000, switch_overhead_p95_ms=200, barge_in_cancel_p95_ms=200,
        max_utterance_lost=0, max_unspoken_lost=0, max_resynth_replayed_spoken=0,
        max_duplicate_speech=0, max_concurrent_active=1, max_chunk_after_cancel=0,
        max_dropped_call=0, max_improper_failover=0, max_voice_inconsistent=0,
        max_voice_switch_unmapped=0, max_flap=0, max_cross_tenant=0, min_providers=2,
        require_deterministic_flow=true, require_error_normalized=true, require_metering=true,
        require_equivalent_voice=true, failover_error_classes[TIMEOUT,UNAVAILABLE,RATE_LIMITED]}  (T1-T10)
  fallback{chain[primary_tts,secondary_tts,deterministic_flow], min_providers=2,
           resynth_continuation=true, equivalent_voice_required=true,
           hysteresis_sticky_secondary=true, deterministic_flow_on_total_failure=true,
           switching_owned_by=4.3.2}                                                             (T1,T2,T6,T8)
  voice_consistency{voice_id_stable_within_call=true, equivalent_voice_on_fallback=true,
                    cache_honors_voice_id=true}                                                  (T8/FR-TTS-009)
  metrics{emitted[tts_fallback_total,tts_switch_overhead_ms,tts_resynth_chars_total,
          tts_voice_switch_total,tts_barge_in_cancel_ms,tts_deterministic_flow_total,
          tts_speak_complete_total], maps_to_observability{}}
  error_taxonomy{mapping→API §11.6, failover_classes[...], non_failover_classes[...]}            (T7,T11)
  residency{region_pin_required=true, no_log_required=true, allowed_retention[NONE,EPHEMERAL],
            resynth_buffer_ephemeral=true}                                                       (T10,T11)
  pii{raw_audio_in_spec_forbidden, raw_text_in_spec_forbidden, pii_value_in_spec_forbidden}      (T11)
  invariants[≥11]{id, desc, trace}

config/tts-fallback-profiles.json: providers[]{provider_id, languages, sample_rates(⊇8000),
  features(⊇streaming,barge_in_cancel,pronunciation_dict), regions, data_retention(NONE/EPHEMERAL),
  voices[], setup_ms, teardown_ms, first_byte_ms, cancel_ms, resynth_rtf};
  profiles[]{name, primary_provider, secondary_provider, region, default_voice,
  voice_equivalence{logical_voiceId:{provider_id:physical_voice}}}

simulate sample: {name, profile | primary+secondary | primary_obj+secondary_obj, voice_id?,
  voice_equivalence?, tenant_id?, expect, expected?{metrik:değer}, policy?{failover, resynth,
  resume_from_boundary, preserve_voice, deterministic_flow, selective_trigger, single_stream,
  hysteresis, dedup, honor_cancel, meter, normalize_errors, tenant_isolation},
  events[{kind:'start', t, sample_rate_hz?, voice_id?} |
         {kind:'speak', t, utterance_id, char_len, dur_ms, remaining_chars?, voice_id?, cached?} |
         {kind:'complete', t, utterance_id} | {kind:'barge_in', t, utterance_id?} |
         {kind:'provider_error', t, raw_error, utterance_id?} | {kind:'end', t, reason}]}
  — start → (speak|complete|barge_in|provider_error)* → end; ilk olay 'start', son olay 'end'

komutlar: validate | simulate <sample.json> | selftest | schema""")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if cmd == "validate":
        return validate()
    if cmd == "simulate":
        if len(sys.argv) < 3:
            print("kullanım: tts_fallback_probe.py simulate <sample.json>")
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
