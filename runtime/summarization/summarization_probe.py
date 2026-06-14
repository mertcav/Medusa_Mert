#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
summarization_probe.py — WBS 3.2.2 Token sınırına göre konuşma geçmişi özetleme

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only statik + davranış kapısı.
`runtime/session-memory/` (3.2.1) + `runtime/resource-budget/` (3.1.4) disipliniyle aynı; burada
deterministik bir ÖZETLEME MOTORU (SAD §6.2 Session Memory'nin özetleme alt-fonksiyonu) simülatörü
(olay-tetikli, sanal saat, random YOK; gerçek LLM çağrısı YOK — token-muhasebe + sıkıştırma MODELİ).

CONVERSATION ORCHESTRATOR (Çekirdek IP, SAD §6) oturum aktöründe çalışan Summarization Engine:
  • Tetik:     history token'ı (özet+pencere) tavanı aşınca özetleme tetiklenir; altında değil (S1).
  • Azaltma:   tetik sonunda özet+pencere ≤ history_token_budget (token tüketimi düşer — S2/FR-RES-010).
  • Yuvarlanan:özet summary_token_cap'i aşmaz (re-compress; sınırsız büyüme yok — S3).
  • Koruma:    katlanan her turn özete girer + salient coverage_floor üstünde (özet≠kırpma — S4).
  • Sıcak yol: özetleme yanıt turunu bloklamaz (asenkron, küçük tier — S5/NFR 10.1).
  • İdempotent:aynı batch iki kez özetlenmez; deterministik (S6).
  • İzolasyon: {tenant,call} izole + adapter no-train/bölgesel (S7).
  • Redaction: kart/OTP düz-metin özete girmez; durable redaction_state='pending' (S8).

KAPSAM AYRIMI: pencere/append/fold-tetiği/oturum-sonu persist → 3.2.1 (bu motor hook'una bağlanır);
LLM tiering/routing/semantic-cache → SAD §9 LLM Router (küçük tier'ı SPI ile kullanır); RAG top-k
trimming → RAG Client SAD §10.2; versiyonlu prompt → 3.2.3; per-call bütçe → 3.1.4; PII redaction
L7 → 3.3.x. Burada YALNIZ özetleme MODELİ + token-bütçe sözleşmesi.

Komutlar:
  validate              summarization-spec.json'ı invariant'lara (S1–S10) + config profillerine doğrular.
  simulate <sample>     Deterministik Summarization Engine — olay-akışı (turn append + end) → token
                        bütçe + tetik + sıkıştırma + coverage + HARD kapılar (S1–S8); →çıkış kodu.
  selftest              İyi/kötü spec+sample ile kapıların doğru tetiklendiğini kanıtlar.
  schema                Beklenen spec şeklini özetler.

Sunucu/credential GEREKMEZ. simulate gerçek LLM/tokenizer yerine deterministik token-muhasebe +
sıkıştırma modelidir (canlı sistemde Go/Rust runtime + gerçek LlmAdapter, ADR-003/SAD §6.3/§9).
Ham metin/transkript METNİ/PII DEĞERİ YOK — yalnız token (approx_tokens) + salient-birim (salient_units)
SAYILARI + sanal zaman + redaction-işareti sayıları.
"""
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "summarization-spec.json")
PROFILES_CFG = os.path.join(HERE, "config", "summarization-profiles.json")

ERROR_TAXONOMY = {
    "TIMEOUT", "RATE_LIMITED", "UNAVAILABLE", "AUTH",
    "INVALID_REQUEST", "CONTENT_FILTERED", "QUOTA_EXCEEDED", "REGION_VIOLATION",
}
SECRET_RE = re.compile(
    r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer)\b\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}"
)
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")

SPEAKERS = {"caller", "agent", "human"}
END_STATES = {"normal", "transfer", "error", "abandon"}


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_placeholder(v):
    return isinstance(v, str) and PLACEHOLDER_RE.match(v) is not None


class SummarizeError(Exception):
    """Geçersiz/desteklenmeyen olay — sessizce kabul yok, reddet (S10)."""


# ─────────────────────────────────────────────────────────────────────────────
# Summarization Engine — token-sınırı konuşma geçmişi özetleme (deterministik)
# ─────────────────────────────────────────────────────────────────────────────
class SummarizationEngine:
    """SAD §6.2 Session Memory özetleme motoru. Olay-akışını işler: turn append + end. history
    token'ı (rolling_summary + aktif pencere) history_token_budget'ı aşınca en eski turn'leri (FIFO)
    YUVARLANAN bir özete SIKIŞTIRIR (küçük tier, asenkron) — KIRPMAZ. Özet summary_token_cap'te
    sınırlı (re-compress). Olay-tetikli; sanal saat (event.t) — random YOK.

    Olaylar:
      {kind:'turn', turn_id, speaker, t, approx_tokens, salient_units?, sensitive_tokens?, tenant_id?}
      {kind:'end', t, reason∈end_states}
    """

    def __init__(self, params, policy):
        self.B = float(params.get("history_token_budget", 3000))   # geçmiş token tavanı
        self.C = float(params.get("summary_token_cap", 600))       # yuvarlanan özet tavanı
        self.coverage_floor = float(params.get("coverage_floor", 0.9))
        self.cr = float(params.get("compression_ratio", 0.2))
        self.ret = float(params.get("summary_retention", 0.95))
        self.recompress_ret = float(params.get("recompress_retention", 0.9))
        self.lat_budget = float(params.get("summarize_latency_budget_ms", 200))
        self.tier_ft = float(params.get("tier_first_token_ms", 150))
        self.per_tok_ms = float(params.get("per_token_ms", 0.1))
        self.tenant_id = params.get("tenant_id", "t-self")
        self.pol = policy

        # pencere + özet durumu
        self.window = []                # aktif pencere (turn dict'leri)
        self.window_tokens = 0.0
        self.window_salient = 0.0
        self.summary_tokens = 0.0       # yuvarlanan özet token'ı
        self.summary_salient = 0.0      # özette korunan salient
        self.peak_summary_tokens = 0.0
        self.seen_turn_ids = set()
        self.next_seq = 0
        self._last_t = None

        # sayaçlar / metrikler
        self.captured_turns = 0
        self.total_salient = 0.0
        self.total_tokens = 0.0
        self.folded_turns = 0           # pencereden çıkarılıp katlanan turn
        self.summarized_turns = 0       # özete fiilen GİREN turn (uncovered = folded - summarized)
        self.uncovered_fold = 0         # katlandı ama özete girmedi (truncate/drop — bug)
        self.summarize_ops = 0          # özetleme tetik sayısı
        self.recompress_events = 0      # yuvarlanan özet re-compress sayısı
        self.summary_overflow = 0.0     # özet cap'i aştı (sınırsız — bug)
        self.spurious_summarize = 0     # tavan altında özetleme (bug)
        self.budget_exceeded_after = 0  # tetik sonrası hâlâ tavan üstü (bug)
        self.tokens_saved = 0.0         # düşürülen toplam token (FR-RES-010 kanıtı)
        self.duplicate_turn = 0
        self.out_of_order = 0
        self.double_summarize = 0       # aynı turn iki kez özetlendi (bug)
        self.cross_tenant = 0
        self.sensitive_seen = 0
        self.sensitive_cleartext_summarized = 0
        self.blocking_summarize = 0     # özetleme turu blokladı (bug)
        self.summarize_latency_max = 0.0
        self.turn_latency_added = 0.0   # sıcak yola eklenen gecikme (bloklarsa)
        self.summarized_turn_ids = set()
        self.redaction_state = None
        self.ended = False
        self.end_reason = None

    def _history_tokens(self):
        return self.summary_tokens + self.window_tokens

    # ── turn ekleme: append + tetik kontrolü ──────────────────────────────────
    def append_turn(self, ev):
        if self.ended:
            raise SummarizeError("bitmiş oturuma turn eklenemez → INVALID_REQUEST")
        tid = ev.get("turn_id")
        if not isinstance(tid, str) or not tid:
            raise SummarizeError("turn_id yok/boş → INVALID_REQUEST")
        sp = ev.get("speaker")
        if sp not in SPEAKERS:
            raise SummarizeError("geçersiz speaker: %r → INVALID_REQUEST" % sp)
        t = ev.get("t")
        if not isinstance(t, (int, float)):
            raise SummarizeError("turn zaman damgası sayısal değil → INVALID_REQUEST")
        approx = ev.get("approx_tokens")
        if not isinstance(approx, (int, float)) or approx < 0:
            raise SummarizeError("approx_tokens sayısal/≥0 değil → INVALID_REQUEST")
        salient = ev.get("salient_units", 1)
        if not isinstance(salient, (int, float)) or salient < 0:
            raise SummarizeError("salient_units sayısal/≥0 değil → INVALID_REQUEST")
        sens = ev.get("sensitive_tokens", 0)
        if not isinstance(sens, int) or sens < 0:
            raise SummarizeError("sensitive_tokens int/≥0 değil → INVALID_REQUEST")

        # ── cross-tenant (S7)
        turn_tenant = ev.get("tenant_id", self.tenant_id)
        if turn_tenant != self.tenant_id:
            if self.pol.get("tenant_isolation", True):
                self.cross_tenant += 1
                raise SummarizeError("cross-tenant turn reddedildi → AUTH")
            else:
                self.cross_tenant += 1

        # ── idempotent append (S6): aynı turn_id ikinci kez → atla
        if tid in self.seen_turn_ids:
            if self.pol.get("dedupe", True):
                self.duplicate_turn += 1
                return
            else:
                self.duplicate_turn += 1   # dedupe kapalı → çift sayım kanıtı (aşağıda işlenir)

        # ── monoton sıra (S6)
        if self._last_t is not None and t < self._last_t:
            if self.pol.get("order_guard", True):
                self.out_of_order += 1
                raise SummarizeError("out-of-order turn (t geriye) reddedildi → INVALID_REQUEST")
            else:
                self.out_of_order += 1
        self._last_t = max(self._last_t if self._last_t is not None else t, t)

        self.seen_turn_ids.add(tid)
        seq = self.next_seq
        self.next_seq += 1
        self.captured_turns += 1
        self.total_salient += salient
        self.total_tokens += approx
        if sens > 0:
            self.sensitive_seen += sens

        self.window.append({"turn_id": tid, "speaker": sp, "seq": seq,
                            "approx_tokens": float(approx), "salient_units": float(salient),
                            "sensitive_tokens": sens})
        self.window_tokens += approx
        self.window_salient += salient

        # ── eager (bozuk): tavan altında bile özetle → spurious (S1 eler)
        if self.pol.get("eager_summarize", False) and self._history_tokens() <= self.B and self.window:
            self.spurious_summarize += 1
            self._fold_batch([self.window.pop(0)])

        # ── tetik (S1/S2): tavan aşılınca en eskiyi katla, tavan altına in
        self._enforce_budget()

    def _enforce_budget(self):
        """history token'ı tavanı aşarsa en eski turn'leri özete katla (S1/S2). Motor kapalıysa
        (bozuk) hiç katlamaz → budget_exceeded_after artar (S2 eler)."""
        if not self.pol.get("summarize", True):
            if self._history_tokens() > self.B:
                self.budget_exceeded_after += 1
            return
        # en az 1 turn pencerede kalsın
        while self._history_tokens() > self.B and len(self.window) > 1:
            self._fold_batch([self.window.pop(0)])
        if self._history_tokens() > self.B:
            # tek turn + özet hâlâ tavan üstü (bütçe yanlış boyutlanmış) → kayıt
            self.budget_exceeded_after += 1

    def _fold_batch(self, batch):
        """Bir turn batch'ini YUVARLANAN özete SIKIŞTIR (S3/S4) — KIRPMA değil. Truncate politikası
        (bozuk) içeriği düşürür → uncovered_fold + coverage düşer (S4 eler)."""
        n = len(batch)
        btok = sum(x["approx_tokens"] for x in batch)
        bsal = sum(x["salient_units"] for x in batch)
        bsens = sum(x["sensitive_tokens"] for x in batch)
        bids = [x["turn_id"] for x in batch]

        self.folded_turns += n
        self.window_tokens -= btok
        self.window_salient -= bsal
        pre_history = self.summary_tokens + self.window_tokens + btok  # batch çıkmadan önceki

        # idempotent: aynı turn iki kez özetlenirse (dedupe kapalı) → double_summarize
        for bid in bids:
            if bid in self.summarized_turn_ids:
                self.double_summarize += 1
            self.summarized_turn_ids.add(bid)

        if self.pol.get("truncate_instead", False):
            # BOZUK: özetleme yerine düşür → katlanan turn özete GİRMEZ (S4 eler)
            self.uncovered_fold += n
            self.summarize_ops += 1
            self.tokens_saved += btok   # token düşer ama bilgi kaybolur
            return

        # ── özetleme (sıkıştırma): batch özete katkı verir
        self.summarized_turns += n
        # kart/OTP düz-metin özete girer mi? (strip kapalıysa bug — S8)
        if not self.pol.get("strip_card_otp", True) and bsens > 0:
            self.sensitive_cleartext_summarized += bsens

        contribution = math.ceil(btok * self.cr)
        raw = self.summary_tokens + contribution
        if raw > self.C:
            if self.pol.get("bound_summary", True):
                # özyinelemeli re-compress: özet+katkıyı cap'e sıkıştır (S3). Re-compress
                # TOKEN'ı sıkıştırır; salient FACT'leri korur (yuvarlanan özetin amacı) —
                # coverage kaybı yalnız tek-seferlik turn→özet çıkarımından (summary_retention),
                # özyineleme derinliğinden DEĞİL. Böylece S4 floor re-compress'e dayanıklı.
                self.recompress_events += 1
                self.summary_tokens = float(self.C)
            else:
                # BOZUK: sınırsız büyür (S3 eler)
                self.summary_tokens = float(raw)
        else:
            self.summary_tokens = float(raw)
        # salient: katlanan turn'ün korunan bilgisi (tek-seferlik çıkarım retention'ı)
        self.summary_salient += bsal * self.ret

        self.peak_summary_tokens = max(self.peak_summary_tokens, self.summary_tokens)
        if self.peak_summary_tokens > self.C:
            self.summary_overflow = max(self.summary_overflow, self.peak_summary_tokens - self.C)

        # token tasarrufu (FR-RES-010): batch'in penceredeki ham boyutu - özete katkısı
        self.tokens_saved += max(0.0, btok - contribution)
        post_history = self.summary_tokens + self.window_tokens
        # pre/post bilgilendirici; ana kapı budget_exceeded_after

        self.summarize_ops += 1

        # ── gecikme (S5): küçük tier ilk-token + token başına; off-path
        lat = self.tier_ft + math.ceil(btok * self.per_tok_ms)
        self.summarize_latency_max = max(self.summarize_latency_max, lat)
        if self.pol.get("blocks_turn", False):
            self.blocking_summarize += 1
            self.turn_latency_added += lat

    def coverage(self):
        if self.total_salient <= 0:
            return 1.0
        kept = self.window_salient + self.summary_salient
        return max(0.0, min(1.0, kept / self.total_salient))

    # ── oturum sonu (özet 3.2.1 tarafından durable'a yazılır; burada redaction işareti) ──
    def end(self, ev):
        if self.ended:
            raise SummarizeError("oturum zaten bitti → INVALID_REQUEST")
        reason = ev.get("reason", "normal")
        if reason not in END_STATES:
            raise SummarizeError("geçersiz bitiş nedeni: %r → INVALID_REQUEST" % reason)
        self.ended = True
        self.end_reason = reason
        # durable özet (session_summary → transcript.summary, 3.2.1 persist) redaction_state
        self.redaction_state = self.pol.get("redaction_state", "pending")

    def metrics(self):
        scenario = []
        if self.summarize_ops > 0 and not self.pol.get("truncate_instead", False):
            scenario.append("summarize")
        if self.pol.get("truncate_instead", False) and self.folded_turns > 0:
            scenario.append("truncate")
        if self.recompress_events > 0:
            scenario.append("recompress")
        if self.duplicate_turn > 0:
            scenario.append("dedupe")
        if self.sensitive_seen > 0:
            scenario.append("sensitive")
        if not scenario:
            scenario.append("under-budget")
        return {
            "captured_turns": self.captured_turns,
            "total_tokens": round(self.total_tokens, 2),
            "history_tokens_final": round(self._history_tokens(), 2),
            "history_token_budget": self.B,
            "window_turns_final": len(self.window),
            "window_tokens_final": round(self.window_tokens, 2),
            "summary_tokens_final": round(self.summary_tokens, 2),
            "summary_token_cap": self.C,
            "peak_summary_tokens": round(self.peak_summary_tokens, 2),
            "summary_overflow": round(self.summary_overflow, 2),
            "folded_turns": self.folded_turns,
            "summarized_turns": self.summarized_turns,
            "uncovered_fold": self.uncovered_fold,
            "summarize_ops": self.summarize_ops,
            "recompress_events": self.recompress_events,
            "spurious_summarize": self.spurious_summarize,
            "budget_exceeded_after": self.budget_exceeded_after,
            "tokens_saved": round(self.tokens_saved, 2),
            "coverage": round(self.coverage(), 4),
            "coverage_floor": self.coverage_floor,
            "duplicate_turn": self.duplicate_turn,
            "out_of_order": self.out_of_order,
            "double_summarize": self.double_summarize,
            "cross_tenant": self.cross_tenant,
            "sensitive_seen": self.sensitive_seen,
            "sensitive_cleartext_summarized": self.sensitive_cleartext_summarized,
            "blocking_summarize": self.blocking_summarize,
            "summarize_latency_max": round(self.summarize_latency_max, 2),
            "summarize_latency_budget": self.lat_budget,
            "turn_latency_added": round(self.turn_latency_added, 2),
            "redaction_state": self.redaction_state,
            "end_reason": self.end_reason,
            "scenario": scenario,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Tam simülasyon (bir sample)
# ─────────────────────────────────────────────────────────────────────────────
def simulate(sample, params, policy):
    events = sample.get("events")
    if events is None:
        raise SummarizeError("boş olay akışı")
    if not isinstance(events, list):
        raise SummarizeError("events liste değil → INVALID_REQUEST")
    if not events:
        raise SummarizeError("boş olay akışı")
    p = dict(params)
    p["tenant_id"] = sample.get("tenant_id", params.get("tenant_id", "t-self"))
    e = SummarizationEngine(p, policy)
    saw_end = False
    for ev in events:
        if not isinstance(ev, dict):
            raise SummarizeError("olay sözlük değil → INVALID_REQUEST")
        kind = ev.get("kind")
        if kind == "turn":
            e.append_turn(ev)
        elif kind == "end":
            e.end(ev)
            saw_end = True
        else:
            raise SummarizeError("bilinmeyen olay tipi: %r → INVALID_REQUEST" % kind)
    if not saw_end:
        raise SummarizeError("olay akışında 'end' yok → INVALID_REQUEST")
    return e.metrics()


def evaluate(gates, m):
    """Metrikleri HARD kapılara (S1–S8) karşı değerlendirir. Döner findings[(ok, label)]."""
    F = []
    sc = set(m.get("scenario", []))

    # ── S1: tetik doğruluğu (spurious yok)
    F.append((m.get("spurious_summarize", 0) <= gates.get("max_spurious_summarize", 0),
              "S1 tetik: spurious_summarize %d ≤ %d (yalnız tavan aşımında — SR-LLM-005)"
              % (m.get("spurious_summarize", 0), gates.get("max_spurious_summarize", 0))))

    # ── S2: token azaltma (tavan aşılmaz)
    F.append((m.get("budget_exceeded_after", 0) <= gates.get("max_budget_exceeded_after", 0)
              and m.get("history_tokens_final", 0) <= m.get("history_token_budget", gates.get("history_token_budget", 3000)) + 1e-6,
              "S2 azaltma: history %.0f ≤ tavan %.0f, budget_exceeded_after %d ≤ %d (FR-RES-010/SR-RES-010)"
              % (m.get("history_tokens_final", 0), m.get("history_token_budget", 0),
                 m.get("budget_exceeded_after", 0), gates.get("max_budget_exceeded_after", 0))))

    # ── S3: sınırlı yuvarlanan özet
    F.append((m.get("summary_overflow", 0) <= gates.get("max_summary_overflow", 0)
              and m.get("peak_summary_tokens", 0) <= m.get("summary_token_cap", gates.get("summary_token_cap", 600)) + 1e-6,
              "S3 sınırlı özet: peak %.0f ≤ cap %.0f, overflow %.0f ≤ %d (re-compress %d kez)"
              % (m.get("peak_summary_tokens", 0), m.get("summary_token_cap", 0),
                 m.get("summary_overflow", 0), gates.get("max_summary_overflow", 0),
                 m.get("recompress_events", 0))))

    # ── S4: özet ≠ kırpma (coverage)
    cov_ok = (m.get("uncovered_fold", 0) <= gates.get("max_uncovered_fold", 0)
              and m.get("coverage", 0) >= m.get("coverage_floor", gates.get("coverage_floor", 0.9)) - 1e-9
              and m.get("summarized_turns", 0) == m.get("folded_turns", -1))
    F.append((cov_ok,
              "S4 özet≠kırpma: uncovered_fold %d ≤ %d, coverage %.3f ≥ %.2f, summarized %d == folded %d (SR-LLM-005)"
              % (m.get("uncovered_fold", 0), gates.get("max_uncovered_fold", 0),
                 m.get("coverage", 0), m.get("coverage_floor", 0.9),
                 m.get("summarized_turns", 0), m.get("folded_turns", 0))))

    # ── S5: sıcak yol (bloklamaz + gecikme bütçesi)
    F.append((m.get("blocking_summarize", 0) <= gates.get("max_blocking_summarize", 0)
              and m.get("summarize_latency_max", 0) <= m.get("summarize_latency_budget", gates.get("summarize_latency_budget_ms", 200)) + 1e-6,
              "S5 sıcak yol: blocking %d ≤ %d, özetleme-gecikme %.0fms ≤ %.0fms (asenkron, küçük tier — NFR 10.1)"
              % (m.get("blocking_summarize", 0), gates.get("max_blocking_summarize", 0),
                 m.get("summarize_latency_max", 0), m.get("summarize_latency_budget", 200))))

    # ── S6: idempotent/deterministik
    F.append((m.get("double_summarize", 0) <= gates.get("max_double_summarize", 0)
              and m.get("out_of_order", 0) == 0,
              "S6 idempotent: double_summarize %d ≤ %d, out_of_order %d (deterministik)"
              % (m.get("double_summarize", 0), gates.get("max_double_summarize", 0),
                 m.get("out_of_order", 0))))

    # ── S7: tenant izolasyon
    F.append((m.get("cross_tenant", 0) <= gates.get("max_cross_tenant", 0),
              "S7 izolasyon: cross_tenant %d ≤ %d ({tenant,call} + adapter no-train/bölgesel — FR-TEN-002/FR-LLM-012)"
              % (m.get("cross_tenant", 0), gates.get("max_cross_tenant", 0))))

    # ── S8: redaction sınırı (kart/OTP özete girmez + pending)
    F.append((m.get("sensitive_cleartext_summarized", 0) <= gates.get("max_sensitive_cleartext_summarized", 0)
              and (m.get("redaction_state") in (None, "pending", "not_required")),
              "S8 redaction: kart/OTP düz-metin özete %d ≤ %d + durable redaction_state=%r (FR-REC-004/005)"
              % (m.get("sensitive_cleartext_summarized", 0),
                 gates.get("max_sensitive_cleartext_summarized", 0), m.get("redaction_state"))))

    return F


# ─────────────────────────────────────────────────────────────────────────────
# parametre + politika çözümleme
# ─────────────────────────────────────────────────────────────────────────────
def _profile_by_name(cfg, name):
    for p in cfg.get("profiles", []):
        if p.get("name") == name:
            return p
    raise SummarizeError("bilinmeyen profil: %s" % name)


def _params_from(spec, profile):
    tm = dict(spec.get("token_model", {}))
    lat = dict(spec.get("latency", {}))
    out = {
        "history_token_budget": tm.get("history_token_budget", 3000),
        "summary_token_cap": tm.get("summary_token_cap", 600),
        "coverage_floor": tm.get("coverage_floor", 0.9),
        "compression_ratio": tm.get("compression_ratio", 0.2),
        "summary_retention": tm.get("summary_retention", 0.95),
        "recompress_retention": tm.get("recompress_retention", 0.9),
        "summarize_latency_budget_ms": lat.get("summarize_latency_budget_ms", 200),
        "tier_first_token_ms": lat.get("tier_first_token_ms", 150),
        "per_token_ms": lat.get("per_token_ms", 0.1),
    }
    for k in ("history_token_budget", "summary_token_cap", "coverage_floor",
              "compression_ratio", "summary_retention"):
        if k in profile:
            out[k] = profile[k]
    return out


def _resolve_policy(spec, profile, sample):
    pol = {
        "summarize": True,
        "bound_summary": True,
        "truncate_instead": False,
        "eager_summarize": False,
        "dedupe": True,
        "order_guard": True,
        "tenant_isolation": True,
        "strip_card_otp": True,
        "blocks_turn": False,
        "redaction_state": spec.get("pii", {}).get("durable_redaction_state", "pending"),
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
        except SummarizeError as ex:
            print("simulate[%s]: %s" % (name, ex))
            return 0 if expect == "fail" else 1
    params = _params_from(spec, profile)
    policy = _resolve_policy(spec, profile, sample)
    gates = spec.get("gates", {})

    try:
        m = simulate(sample, params, policy)
    except SummarizeError as ex:
        print("simulate[%s]: REDDEDİLDİ — %s" % (name, ex))
        return 0 if expect == "fail" else 1

    F = evaluate(gates, m)
    print("simulate[%s] senaryo=%s | %d turn (%.0f token) → pencere %d (%.0f tok) + özet %.0f/%.0f tok | "
          "tetik %d (re-compress %d) | tasarruf %.0f tok | coverage %.3f"
          % (name, "+".join(m["scenario"]), m["captured_turns"], m["total_tokens"],
             m["window_turns_final"], m["window_tokens_final"], m["summary_tokens_final"],
             m["summary_token_cap"], m["summarize_ops"], m["recompress_events"],
             m["tokens_saved"], m["coverage"]))
    print("  history-final %.0f/%.0f tok | folded %d (özete giren %d, kapsanmayan %d) | "
          "spurious=%d | bütçe-aşımı-sonrası=%d | blocking=%d (gecikme %.0fms) | cross_tenant=%d | sensitive=%d (özete %d)"
          % (m["history_tokens_final"], m["history_token_budget"], m["folded_turns"],
             m["summarized_turns"], m["uncovered_fold"], m["spurious_summarize"],
             m["budget_exceeded_after"], m["blocking_summarize"], m["summarize_latency_max"],
             m["cross_tenant"], m["sensitive_seen"], m["sensitive_cleartext_summarized"]))
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

    _check(R, spec.get("wbs") == "3.2.2", "spec.wbs == 3.2.2")
    _check(R, spec.get("version"), "spec.version mevcut")

    # ── placement (orchestrator oturum aktörü, off-hot-path, küçük tier)
    pl = spec.get("placement", {})
    _check(R, pl.get("in_orchestrator") is True and pl.get("in_session_actor") is True,
           "özetleme motoru orchestrator oturum aktöründe (SAD §6.2/§6.3)")
    _check(R, pl.get("event_driven") is True and pl.get("non_blocking") is True,
           "S5 olay-tetikli + bloklamaz")
    _check(R, pl.get("runs_between_turns") is True and pl.get("off_hot_path") is True,
           "S5 turlar arasında / sıcak yol dışı (NFR 10.1)")
    _check(R, pl.get("summarizer_tier") == "small",
           "S5 özetleyici küçük tier (SAD §9/ADR-008)")
    _check(R, pl.get("plugs_into_hook"),
           "S9 3.2.1 summarization_hook'una bağlanır (seam tüketir)")

    # ── token_model (S1/S2/S3/S4)
    tm = spec.get("token_model", {})
    _check(R, isinstance(tm.get("history_token_budget"), (int, float)) and tm["history_token_budget"] > 0,
           "S2 history_token_budget > 0 (token tavanı)")
    _check(R, isinstance(tm.get("summary_token_cap"), (int, float)) and tm["summary_token_cap"] > 0,
           "S3 summary_token_cap > 0 (özet tavanı)")
    _check(R, tm.get("summary_token_cap", 0) < tm.get("history_token_budget", 0),
           "S3 summary_token_cap < history_token_budget (özet payı geçmiş payından küçük)")
    _check(R, 0 < tm.get("coverage_floor", 0) <= 1, "S4 0 < coverage_floor ≤ 1")
    _check(R, 0 < tm.get("compression_ratio", 0) < 1, "S2 0 < compression_ratio < 1 (sıkıştırma)")
    _check(R, 0 < tm.get("summary_retention", 0) <= 1, "S4 0 < summary_retention ≤ 1 (bilgi koruma)")
    _check(R, set(tm.get("speakers", [])) == SPEAKERS, "speaker kümesi {caller,agent,human}")

    # ── trigger (S1)
    tr = spec.get("trigger", {})
    _check(R, tr.get("trigger_on") == "history_tokens_over_budget",
           "S1 tetik = history token tavan aşımı (SR-LLM-005)")
    _check(R, tr.get("no_spurious_under_budget") is True, "S1 tavan altında spurious özetleme yok")
    _check(R, tr.get("keep_at_least_one_turn") is True, "S1 en az 1 turn pencerede kalır")

    # ── reduction (S2)
    rd = spec.get("reduction", {})
    _check(R, rd.get("history_within_budget_after_trigger") is True,
           "S2 tetik sonrası history ≤ tavan (FR-RES-010/SR-RES-010)")

    # ── rolling_summary (S3)
    rs = spec.get("rolling_summary", {})
    _check(R, rs.get("bounded") is True and rs.get("recompress_on_cap") is True,
           "S3 yuvarlanan özet sınırlı + cap'te re-compress")
    _check(R, rs.get("durable_record_is_source_of_truth") is True,
           "S3 kaynak doğruluk durable kayıt (özet değil; 3.2.1 M5)")

    # ── coverage (S4)
    cv = spec.get("coverage", {})
    _check(R, cv.get("summarize_not_truncate") is True,
           "S4 özet ≠ kırpma (FR-LLM-005)")
    _check(R, cv.get("every_folded_turn_summarized") is True,
           "S4 katlanan her turn özete girer (uncovered_fold=0)")
    _check(R, 0 < cv.get("coverage_floor", 0) <= 1, "S4 coverage_floor (0,1]")

    # ── latency (S5)
    la = spec.get("latency", {})
    _check(R, la.get("summarize_blocks_turn") is False,
           "S5 özetleme turu bloklamaz (asenkron)")
    _check(R, la.get("summarizer_uses_small_tier") is True,
           "S5 özetleyici küçük tier (ADR-008)")
    _check(R, la.get("summarize_latency_budget_ms", 0) > 0, "S5 özetleme gecikme bütçesi > 0")

    # ── kapılar
    g = spec.get("gates", {})
    _check(R, g.get("history_token_budget") == tm.get("history_token_budget"),
           "gates history_token_budget token_model ile tutarlı")
    _check(R, g.get("summary_token_cap") == tm.get("summary_token_cap"),
           "gates summary_token_cap token_model ile tutarlı")
    _check(R, g.get("max_spurious_summarize", -1) == 0, "S1 max_spurious_summarize = 0")
    _check(R, g.get("max_budget_exceeded_after", -1) == 0, "S2 max_budget_exceeded_after = 0")
    _check(R, g.get("max_summary_overflow", -1) == 0, "S3 max_summary_overflow = 0")
    _check(R, g.get("max_uncovered_fold", -1) == 0, "S4 max_uncovered_fold = 0")
    _check(R, g.get("max_blocking_summarize", -1) == 0, "S5 max_blocking_summarize = 0")
    _check(R, g.get("max_double_summarize", -1) == 0, "S6 max_double_summarize = 0")
    _check(R, g.get("max_cross_tenant", -1) == 0, "S7 max_cross_tenant = 0")
    _check(R, g.get("max_sensitive_cleartext_summarized", -1) == 0,
           "S8 max_sensitive_cleartext_summarized = 0")

    # ── metrikler → observability
    me = spec.get("metrics", {})
    emitted = set(me.get("emitted", []))
    _check(R, {"summarization_total", "summarization_tokens_saved", "summarization_coverage_ratio"} <= emitted,
           "metrikler: total + tokens_saved + coverage yayılır")
    _check(R, len(me.get("maps_to_observability", {})) >= 1,
           "metrik observability'ye eşlenir (0.4.7)")

    # ── error taxonomy (S10)
    et = spec.get("error_taxonomy", {})
    mapping = et.get("mapping", {})
    _check(R, len(mapping) >= 4, "S10 hata eşlemesi (≥4)")
    _check(R, all(v in ERROR_TAXONOMY for v in mapping.values()),
           "S10 tüm hedefler API §11.6 ErrorTaxonomy'de")
    _check(R, mapping.get("invalid_turn") == "INVALID_REQUEST"
           and mapping.get("summarizer_unavailable") == "UNAVAILABLE"
           and mapping.get("cross_tenant_access") == "AUTH"
           and mapping.get("region_mismatch") == "REGION_VIOLATION",
           "S10 bozuk-turn→INVALID, özetleyici-down→UNAVAILABLE, cross-tenant→AUTH, bölge→REGION_VIOLATION")

    # ── residency + pii (S7/S8/S10)
    _check(R, spec.get("residency", {}).get("region_pin_required") is True, "S10 residency region pin")
    _check(R, spec.get("residency", {}).get("no_train_required") is True,
           "S7 özetleyici no-train (FR-LLM-012)")
    _check(R, spec.get("pii", {}).get("raw_transcript_text_in_spec_forbidden") is True,
           "S10 ham transkript metni spec'te yasak")
    _check(R, spec.get("pii", {}).get("pii_value_in_spec_forbidden") is True,
           "S10 PII değeri spec'te yasak")
    _check(R, spec.get("pii", {}).get("card_otp_cleartext_in_summary_forbidden") is True,
           "S8 kart/OTP düz-metin özete yasak")

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

    # ── config profilleri doğrulaması
    if os.path.exists(PROFILES_CFG):
        cfg = _load(PROFILES_CFG)
        profs = cfg.get("profiles", [])
        _check(R, len(profs) >= 2, "config ≥2 özetleme profili")
        names = [p.get("name") for p in profs]
        _check(R, len(names) == len(set(names)), "config profil isimleri benzersiz")
        for p in profs:
            _check(R, bool(p.get("region")), "S10 config %s bölge pini var" % p.get("name"))
            _check(R, p.get("history_token_budget", 0) > 0,
                   "S2 config %s history_token_budget > 0" % p.get("name"))
            _check(R, p.get("summary_token_cap", 0) > 0,
                   "S3 config %s summary_token_cap > 0" % p.get("name"))
            _check(R, p.get("summary_token_cap", 1e9) < p.get("history_token_budget", 0),
                   "S3 config %s summary_token_cap < history_token_budget" % p.get("name"))

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
    "history_token_budget": 1000, "summary_token_cap": 200, "coverage_floor": 0.9,
    "compression_ratio": 0.2, "summary_retention": 0.95, "recompress_retention": 0.9,
    "summarize_latency_budget_ms": 200, "tier_first_token_ms": 150, "per_token_ms": 0.1,
    "tenant_id": "t-self",
}


def _turn(t, tid, speaker="caller", tokens=100, salient=1, sensitive=0, tenant=None):
    ev = {"kind": "turn", "turn_id": tid, "speaker": speaker, "t": t,
          "approx_tokens": tokens, "salient_units": salient}
    if sensitive:
        ev["sensitive_tokens"] = sensitive
    if tenant:
        ev["tenant_id"] = tenant
    return ev


def _end(t, reason="normal"):
    return {"kind": "end", "t": t, "reason": reason}


def _run(events, params=None, **pol_over):
    pol = {"summarize": True, "bound_summary": True, "truncate_instead": False,
           "eager_summarize": False, "dedupe": True, "order_guard": True,
           "tenant_isolation": True, "strip_card_otp": True, "blocks_turn": False,
           "redaction_state": "pending"}
    pol.update(pol_over)
    return simulate({"events": events}, params or DEFAULT_PARAMS, pol)


def selftest():
    spec = _load(SPEC_PATH)
    gates = spec.get("gates", {})
    cases = []

    def case(ok, label):
        cases.append((bool(ok), label))

    # 0) validate iyi spec+config'te geçer
    case(_validate_obj(_load(SPEC_PATH)) == 0, "validate iyi spec+config'te 0 döndürür")

    # ── under-budget: kısa çağrı, tavan altında → özetleme YOK (S1) ───────────────
    short = [_turn(0, "u1"), _turn(1000, "a1", "agent"), _turn(2000, "u2"), _end(3000)]
    mu = _run(short)
    case(mu["summarize_ops"] == 0 and mu["folded_turns"] == 0, "under-budget: 300 tok ≤ 1000 → özetleme yok")
    case(mu["spurious_summarize"] == 0 and "under-budget" in mu["scenario"], "under-budget: spurious=0 (S1)")
    case(all(ok for ok, _ in evaluate(gates, mu)), "under-budget tüm kapıları geçer")

    # ── triggered: tavan aşılır → özetleme tetiklenir, history ≤ tavan (S1/S2) ─────
    long_ev = [_turn(i * 100, "t%d" % i, "caller" if i % 2 == 0 else "agent", tokens=200) for i in range(12)]
    long_ev.append(_end(5000))
    mt = _run(long_ev)
    case(mt["summarize_ops"] >= 1 and mt["folded_turns"] >= 1, "triggered: 2400 tok > 1000 → özetleme tetiklendi")
    case(mt["history_tokens_final"] <= 1000 and mt["budget_exceeded_after"] == 0, "triggered: history ≤ tavan (S2/FR-RES-010)")
    case(mt["tokens_saved"] > 0, "triggered: token tasarrufu > 0 (FR-RES-010 kanıtı)")
    case("summarize" in mt["scenario"] and all(ok for ok, _ in evaluate(gates, mt)), "triggered tüm kapıları geçer")

    # ── bounded rolling summary: çok uzun çağrı → re-compress, özet ≤ cap (S3) ─────
    very_long = [_turn(i * 100, "v%d" % i, "caller" if i % 2 == 0 else "agent", tokens=200) for i in range(40)]
    very_long.append(_end(9000))
    mb = _run(very_long)
    case(mb["peak_summary_tokens"] <= 200 and mb["summary_overflow"] == 0, "bounded: özet ≤ cap 200 (re-compress)")
    case(mb["recompress_events"] >= 1, "bounded: re-compress tetiklendi (yuvarlanan özet S3)")
    case(all(ok for ok, _ in evaluate(gates, mb)), "bounded tüm kapıları geçer")

    # ── coverage: özetleme bilgiyi korur (özet ≠ kırpma) (S4) ──────────────────────
    case(mt["summarized_turns"] == mt["folded_turns"] and mt["uncovered_fold"] == 0,
         "coverage: katlanan her turn özete girer (uncovered=0)")
    case(mt["coverage"] >= 0.9, "coverage: salient ≥ floor 0.9 (bağlam korunur — SR-LLM-005)")

    # ── latency off-path: özetleme yanıt turunu bloklamaz (S5) ─────────────────────
    case(mt["blocking_summarize"] == 0 and mt["turn_latency_added"] == 0, "latency: blocking=0 (asenkron, off-path)")
    case(mt["summarize_latency_max"] <= 200, "latency: özetleme gecikme ≤ budget 200ms (küçük tier)")

    # ── sensitive: kart/OTP işareti → özete düz-metin GİRMEZ (S8) ──────────────────
    sens_ev = [_turn(i * 100, "s%d" % i, "caller", tokens=200, sensitive=(2 if i == 0 else 0)) for i in range(12)]
    sens_ev.append(_end(5000))
    ms = _run(sens_ev)
    case(ms["sensitive_seen"] == 2 and ms["sensitive_cleartext_summarized"] == 0,
         "sensitive: kart/OTP görüldü ama özete düz-metin=0 (S8)")
    case(all(ok for ok, _ in evaluate(gates, ms)), "sensitive tüm kapıları geçer")

    # ── determinizm ───────────────────────────────────────────────────────────────
    case(_run(very_long) == mb, "determinizm: aynı olay-akışı birebir aynı metrik (random yok)")

    # ── degraded-1: motor kapalı → tavan aşılır kalır (S2 eler) ────────────────────
    d1 = _run(long_ev, summarize=False)
    case(d1["budget_exceeded_after"] >= 1 and d1["history_tokens_final"] > 1000,
         "degraded(no-engine): history tavanı aşar (S2 eler)")
    case(not all(ok for ok, _ in evaluate(gates, d1)), "degraded(no-engine) S2 eler")

    # ── degraded-2: truncate (kırpma) → katlanan turn özete girmez (S4 eler) ───────
    d2 = _run(long_ev, truncate_instead=True)
    case(d2["uncovered_fold"] >= 1 and d2["coverage"] < 0.9,
         "degraded(truncate): uncovered_fold>0 + coverage<floor (kırpma=bilgi kaybı)")
    case(not all(ok for ok, _ in evaluate(gates, d2)), "degraded(truncate) S4 eler")

    # ── degraded-3: sınırsız özet → cap aşılır (S3 eler) ───────────────────────────
    d3 = _run(very_long, bound_summary=False)
    case(d3["summary_overflow"] > 0 and d3["peak_summary_tokens"] > 200,
         "degraded(unbounded): özet cap'i aşar (S3 eler)")
    case(not all(ok for ok, _ in evaluate(gates, d3)), "degraded(unbounded) S3 eler")

    # ── degraded-4: eager → tavan altında özetleme (S1 eler) ───────────────────────
    d4 = _run(short, eager_summarize=True)
    case(d4["spurious_summarize"] >= 1, "degraded(eager): tavan altında özetleme (spurious>0)")
    case(not all(ok for ok, _ in evaluate(gates, d4)), "degraded(eager) S1 eler")

    # ── degraded-5: bloklayan özetleme → sıcak yola eklenir (S5 eler) ──────────────
    d5 = _run(long_ev, blocks_turn=True)
    case(d5["blocking_summarize"] >= 1 and d5["turn_latency_added"] > 0,
         "degraded(blocking): özetleme turu bloklar (sıcak yola gecikme)")
    case(not all(ok for ok, _ in evaluate(gates, d5)), "degraded(blocking) S5 eler")

    # ── degraded-6: kart/OTP strip kapalı → özete düz-metin (S8 eler) ──────────────
    d6 = _run(sens_ev, strip_card_otp=False)
    case(d6["sensitive_cleartext_summarized"] >= 1, "degraded(no-strip): kart/OTP özete düz-metin girdi")
    case(not all(ok for ok, _ in evaluate(gates, d6)), "degraded(no-strip) S8 eler")

    # ── degraded-7: cross-tenant turn → izolasyon ihlali (S7 eler) ─────────────────
    d7 = _run([_turn(0, "u1"), _turn(1000, "x1", tenant="t-other"), _end(2000)],
              tenant_isolation=False)
    case(d7["cross_tenant"] >= 1, "degraded(cross-tenant): yabancı tenant turn'ü sızdı")
    case(not all(ok for ok, _ in evaluate(gates, d7)), "degraded(cross-tenant) S7 eler")

    # ── geçersiz olay reddi (S10) ─────────────────────────────────────────────────
    case(_raises(lambda: _run([_turn(0, "u1", speaker="robot"), _end(1000)])), "S10 geçersiz speaker → reddedilir")
    case(_raises(lambda: _run([{"kind": "turn", "speaker": "caller", "t": 0, "approx_tokens": 5}, _end(1000)])),
         "S10 turn_id yok → reddedilir")
    case(_raises(lambda: _run([{"kind": "turn", "turn_id": "u1", "speaker": "caller", "t": 0}, _end(1000)])),
         "S10 approx_tokens yok → reddedilir")
    case(_raises(lambda: _run([_turn(0, "u1", tokens=10)])), "S10 'end' olmadan → reddedilir")
    case(_raises(lambda: _run([_turn(1000, "u1"), _turn(0, "u2"), _end(2000)])), "S10 out-of-order → reddedilir")
    case(_raises(lambda: _run([_turn(0, "u1"), {"kind": "nope", "t": 1}, _end(2000)])), "S10 bilinmeyen olay → reddedilir")
    case(_raises(lambda: simulate({"events": []}, DEFAULT_PARAMS, {})), "S10 boş olay akışı → reddedilir")
    case(_raises(lambda: _run([_turn(0, "u1"), _turn(1000, "x1", tenant="t-other"), _end(2000)])),
         "S10 cross-tenant (izolasyon açık) → reddedilir")

    # ── validate negatif kapılar ─────────────────────────────────────────────────
    s = json.loads(json.dumps(spec)); s["token_model"]["history_token_budget"] = 0
    case(_validate_obj(s) != 0, "S2 history_token_budget=0 → validate eler")
    s = json.loads(json.dumps(spec)); s["token_model"]["summary_token_cap"] = s["token_model"]["history_token_budget"] + 1
    case(_validate_obj(s) != 0, "S3 summary_token_cap ≥ budget → validate eler")
    s = json.loads(json.dumps(spec)); s["token_model"]["compression_ratio"] = 1.5
    case(_validate_obj(s) != 0, "S2 compression_ratio ≥ 1 → validate eler")
    s = json.loads(json.dumps(spec)); s["coverage"]["summarize_not_truncate"] = False
    case(_validate_obj(s) != 0, "S4 summarize_not_truncate=false → validate eler")
    s = json.loads(json.dumps(spec)); s["rolling_summary"]["recompress_on_cap"] = False
    case(_validate_obj(s) != 0, "S3 recompress_on_cap=false → validate eler")
    s = json.loads(json.dumps(spec)); s["latency"]["summarize_blocks_turn"] = True
    case(_validate_obj(s) != 0, "S5 summarize_blocks_turn=true → validate eler")
    s = json.loads(json.dumps(spec)); s["latency"]["summarizer_uses_small_tier"] = False
    case(_validate_obj(s) != 0, "S5 summarizer_uses_small_tier=false → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_budget_exceeded_after"] = 1
    case(_validate_obj(s) != 0, "S2 max_budget_exceeded_after>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_uncovered_fold"] = 1
    case(_validate_obj(s) != 0, "S4 max_uncovered_fold>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_summary_overflow"] = 1
    case(_validate_obj(s) != 0, "S3 max_summary_overflow>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_cross_tenant"] = 1
    case(_validate_obj(s) != 0, "S7 max_cross_tenant>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["residency"]["no_train_required"] = False
    case(_validate_obj(s) != 0, "S7 no_train_required=false → validate eler")
    s = json.loads(json.dumps(spec)); s["error_taxonomy"]["mapping"]["x"] = "NOPE"
    case(_validate_obj(s) != 0, "S10 taksonomi-dışı → validate eler")
    s = json.loads(json.dumps(spec)); s["pii"]["pii_value_in_spec_forbidden"] = False
    case(_validate_obj(s) != 0, "S10 pii-değer-yasak kapalı → validate eler")
    s = json.loads(json.dumps(spec)); s["token_model"]["secret"] = "api_key: AKIAIOSFODNN7EXAMPLE"
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
    except SummarizeError:
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
    print("""summarization-spec.json beklenen şekli (WBS 3.2.2):
  wbs, version, phase, trace{fr,nfr,sad,adr,api,srs,rtm,brd,consumes,observability}
  placement{in_orchestrator=true, in_session_actor=true, event_driven=true, non_blocking=true,
            runs_between_turns=true, off_hot_path=true, summarizer_tier=small,
            plugs_into_hook(3.2.1)}                                                  (S5,S9)
  token_model{history_token_budget>0, summary_token_cap>0 (<budget), coverage_floor(0,1],
              0<compression_ratio<1, 0<summary_retention≤1, speakers[caller,agent,human]} (S1-S4)
  trigger{trigger_on=history_tokens_over_budget, no_spurious_under_budget=true,
          keep_at_least_one_turn=true}                                              (S1)
  reduction{history_within_budget_after_trigger=true}                               (S2)
  rolling_summary{bounded=true, recompress_on_cap=true,
                  durable_record_is_source_of_truth=true}                           (S3)
  coverage{summarize_not_truncate=true, every_folded_turn_summarized=true, coverage_floor} (S4)
  latency{summarize_blocks_turn=false, summarizer_uses_small_tier=true,
          summarize_latency_budget_ms>0}                                            (S5)
  gates{history_token_budget, summary_token_cap, max_spurious_summarize=0,
        max_budget_exceeded_after=0, max_summary_overflow=0, max_uncovered_fold=0,
        max_blocking_summarize=0, max_double_summarize=0, max_cross_tenant=0,
        max_sensitive_cleartext_summarized=0}                                       (S1-S8)
  metrics{emitted[], maps_to_observability{}}
  error_taxonomy{mapping→API §11.6}                                                 (S10)
  residency{region_pin_required=true, no_train_required=true}                       (S7,S10)
  pii{raw_transcript_text_in_spec_forbidden, pii_value_in_spec_forbidden,
      card_otp_cleartext_in_summary_forbidden, durable_redaction_state=pending}     (S8,S10)
  invariants[≥10]{id, desc, trace}

config/summarization-profiles.json: profiles[]{name, deployment, history_token_budget,
  summary_token_cap, coverage_floor, compression_ratio?, summary_retention?, region}

simulate sample: {name, profile | profile_obj, tenant_id?, expect, expected?{metrik:değer},
  policy?{summarize, bound_summary, truncate_instead, eager_summarize, dedupe, order_guard,
  tenant_isolation, strip_card_otp, blocks_turn},
  events[{kind:'turn', turn_id, speaker, t, approx_tokens, salient_units?, sensitive_tokens?,
         tenant_id?} | {kind:'end', t, reason}]}  — son olay 'end' olmalı

komutlar: validate | simulate <sample.json> | selftest | schema""")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if cmd == "validate":
        return validate()
    if cmd == "simulate":
        if len(sys.argv) < 3:
            print("kullanım: summarization_probe.py simulate <sample.json>")
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
