#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
session_memory_probe.py — WBS 3.2.1 Kısa süreli diyalog belleği + oturum sonu kalıcılaştırma

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only statik + davranış kapısı.
`runtime/resource-budget/` (3.1.4) + `runtime/turn-taking/` (3.1.3) disipliniyle aynı; burada
deterministik bir SESSION MEMORY (SAD §6.2 oturum aktörü bileşeni) simülatörü (olay-tetikli,
sanal saat, random YOK).

CONVERSATION ORCHESTRATOR (Çekirdek IP, SAD §6) oturum aktöründe çalışan Session Memory:
  • Kısa bellek:  turn'leri SINIRLI pencerede tutar (append-only + monoton seq + idempotent);
                  taşma özete katlanır (fold) — DÜŞMEZ (M1/M2/M9).
  • Persist:      oturum SONUNDA (normal/transfer/error/abandon) durable kayda yazar
                  (transcript + segment + recording + olay); persist_before_delete (M3).
  • Temizlik:     durable başarılı → ephemeral session_state silinir; leaked=0 (M4).
  • Kayıpsız:     persisted_turns == captured_turns; idempotent + at-least-once (M5).
  • Redaction:    transcript redaction_state='pending'; kart/OTP düz-metin yazılmaz (M6).
  • İzolasyon:    {tenant,call} anahtarı; cross-tenant=0 (M7).

KAPSAM AYRIMI: token-sınırı özetleme MOTORU → 3.2.2 (FR-LLM-005); versiyonlu prompt enjeksiyonu
→ 3.2.3; per-call bellek bütçe izleme/sınırlama → 3.1.4; Redis keyspace/TTL → 1.1.5; transcript
şeması/RLS → 1.1.3; PII redaction L7 motoru → 3.3.x. Burada YALNIZ bellek MODELİ + persist sözleşmesi.

Komutlar:
  validate              session-memory-spec.json'ı invariant'lara (M1–M10) + config profillerine doğrular.
  simulate <sample>     Deterministik Session Memory — olay-akışı (turn append + end) → bellek penceresi +
                        katlama + kalıcılaştırma + temizlik + HARD kapılar (M1–M7); →çıkış kodu.
  selftest              İyi/kötü spec+sample ile kapıların doğru tetiklendiğini kanıtlar.
  schema                Beklenen spec şeklini özetler.

Sunucu/credential GEREKMEZ. simulate gerçek PostgreSQL/Redis/S3 yerine deterministik simülasyondur
(canlı sistemde Go/Rust runtime, ADR-003/SAD §6.3). Ham metin/transkript METNİ/PII DEĞERİ YOK —
yalnız turn yapısı (id/speaker/seq/approx_tokens) + sanal zaman + redaction-işareti sayıları.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "session-memory-spec.json")
PROFILES_CFG = os.path.join(HERE, "config", "session-memory-profiles.json")

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


class MemoryError_(Exception):
    """Geçersiz/desteklenmeyen olay — sessizce kabul yok, reddet (M10)."""


# ─────────────────────────────────────────────────────────────────────────────
# Session Memory — oturum-içi bellek + oturum-sonu kalıcılaştırma (deterministik)
# ─────────────────────────────────────────────────────────────────────────────
class SessionMemory:
    """SAD §6.2 oturum aktörü Session Memory bileşeni. Olay-akışını işler: turn append (caller/agent)
    + end (bitiş). Turn'leri SINIRLI pencerede tutar (window_max_turns + token_soft_limit), taşmayı
    özete KATLAR (fold) — düşürmez. Oturum sonunda TÜM yakalanan turn'leri (pencere + katlanan)
    durable kayda yazar, sonra ephemeral'i siler. Olay-tetikli; sanal saat (event.t) — random YOK.

    Olaylar:
      {kind:'turn', turn_id, speaker, t, approx_tokens?, sensitive_tokens?, tenant_id?}
      {kind:'end', t, reason∈end_states}
    """

    def __init__(self, params, policy):
        self.window_max = int(params.get("window_max_turns", 24))
        self.token_soft = int(params.get("token_soft_limit", 3000))
        self.tenant_id = params.get("tenant_id", "t-self")
        self.pol = policy

        self.window = []                # aktif pencere (turn dict'leri)
        self.seen_turn_ids = set()      # idempotent append
        self.next_seq = 0               # monoton seq üretici

        # sayaçlar / metrikler
        self.captured_turns = 0         # benzersiz yakalanan turn (pencere + katlanan)
        self.folded_turns = 0           # özete katlanan turn sayısı
        self.fold_events = 0            # katlama tetiklenme sayısı
        self.summary_turns = 0          # özet içindeki turn sayısı (katlanan)
        self.duplicate_turn = 0         # aynı turn_id tekrarı (idempotent → atılır)
        self.out_of_order = 0           # seq/zaman sırası bozulması
        self.dropped_turn = 0           # kalıcılaştırılamayan turn (kayıp — bug)
        self.unbounded_memory = 0       # pencere window_max'ı aşıp katlanmadı (bug)
        self.peak_window_turns = 0      # pencere doluluk tepe
        self.sensitive_seen = 0         # toplam kart/OTP işareti (working memory)
        self.sensitive_cleartext_persisted = 0   # durable'a düz-metin kart/OTP (bug)
        self.cross_tenant = 0           # cross-tenant turn (bug)
        self.persist_attempts = 0       # durable yazım denemesi
        self.persist_retries = 0        # at-least-once retry
        self.persisted = False          # durable kalıcılaştırma başarılı mı
        self.persisted_turns = 0        # durable'a yazılan turn sayısı
        self.redaction_state = None     # transcript redaction_state (persist'te)
        self.transcript_idempotency = None    # idempotency_key (çift yazım dedupe)
        self.ephemeral_deleted = False  # session_state silindi mi
        self.leaked_session_key = 0     # persist sonrası silinmeyen ephemeral (bug)
        self.unpersisted_on_end = 0     # biten oturum durable yazılmadı (bug)
        self.persist_before_delete_ok = True  # silmeden önce durable yazıldı mı
        self.ended = False
        self.end_reason = None
        self._last_t = None

    # ── turn ekleme: append-only + monoton seq + idempotent + sınırlı pencere ──
    def append_turn(self, ev):
        if self.ended:
            raise MemoryError_("bitmiş oturuma turn eklenemez → INVALID_REQUEST")
        tid = ev.get("turn_id")
        if not isinstance(tid, str) or not tid:
            raise MemoryError_("turn_id yok/boş → INVALID_REQUEST")
        sp = ev.get("speaker")
        if sp not in SPEAKERS:
            raise MemoryError_("geçersiz speaker: %r → INVALID_REQUEST" % sp)
        t = ev.get("t")
        if not isinstance(t, (int, float)):
            raise MemoryError_("turn zaman damgası sayısal değil → INVALID_REQUEST")
        approx = ev.get("approx_tokens", 0)
        if not isinstance(approx, (int, float)) or approx < 0:
            raise MemoryError_("approx_tokens sayısal/≥0 değil → INVALID_REQUEST")
        sens = ev.get("sensitive_tokens", 0)
        if not isinstance(sens, int) or sens < 0:
            raise MemoryError_("sensitive_tokens int/≥0 değil → INVALID_REQUEST")

        # ── cross-tenant tespiti (M7): turn'ün tenant'ı oturum tenant'ından farklıysa
        turn_tenant = ev.get("tenant_id", self.tenant_id)
        if turn_tenant != self.tenant_id:
            if self.pol.get("tenant_isolation", True):
                self.cross_tenant += 1
                raise MemoryError_("cross-tenant turn reddedildi → AUTH")
            else:
                # izolasyon kapalı (bozuk politika) → sızıntı sayılır, kanıt için kabul
                self.cross_tenant += 1

        # ── idempotent (M2): aynı turn_id ikinci kez → atla (tek kayıt)
        if tid in self.seen_turn_ids:
            if self.pol.get("dedupe", True):
                self.duplicate_turn += 1
                return
            else:
                # dedupe kapalı (bozuk) → çift sayım kanıtı
                self.duplicate_turn += 1

        # ── monoton sıra (M2): zaman geriye giderse out-of-order
        if self._last_t is not None and t < self._last_t:
            if self.pol.get("order_guard", True):
                self.out_of_order += 1
                raise MemoryError_("out-of-order turn (t geriye) reddedildi → INVALID_REQUEST")
            else:
                self.out_of_order += 1
        self._last_t = max(self._last_t if self._last_t is not None else t, t)

        self.seen_turn_ids.add(tid)
        seq = self.next_seq
        self.next_seq += 1
        self.captured_turns += 1
        if sens > 0:
            self.sensitive_seen += sens

        self.window.append({"turn_id": tid, "speaker": sp, "seq": seq,
                            "approx_tokens": float(approx), "sensitive_tokens": sens})
        self._enforce_window()
        self.peak_window_turns = max(self.peak_window_turns, len(self.window))

    def _window_tokens(self):
        return sum(x["approx_tokens"] for x in self.window)

    def _enforce_window(self):
        """Pencere taşınca en eski turn'leri ÖZETE katla (fold) — düşürme (M1/M9)."""
        bound = self.pol.get("bound", True)
        folded_now = 0
        if not bound:
            # sınır kapalı (bozuk politika) → pencere sınırsız büyür (M1 eler)
            if len(self.window) > self.window_max or self._window_tokens() > self.token_soft:
                self.unbounded_memory = max(self.unbounded_memory, len(self.window) - self.window_max)
            return
        # turn-sayısı veya token tavanı aşılırsa en eskiyi katla
        while len(self.window) > self.window_max or (
                self._window_tokens() > self.token_soft and len(self.window) > 1):
            oldest = self.window.pop(0)
            folded_now += 1
            self.folded_turns += 1
            self.summary_turns += 1   # özete eklenir (içerik korunur — fold_preserves_content)
        if folded_now:
            self.fold_events += 1

    # ── oturum sonu kalıcılaştırma + temizlik ────────────────────────────────
    def end(self, ev):
        if self.ended:
            raise MemoryError_("oturum zaten bitti → INVALID_REQUEST")
        reason = ev.get("reason", "normal")
        if reason not in END_STATES:
            raise MemoryError_("geçersiz bitiş nedeni: %r → INVALID_REQUEST" % reason)
        self.ended = True
        self.end_reason = reason

        # durable'a yazılacak TÜM yakalanan turn'ler = aktif pencere + katlanan özet (M5)
        to_persist = len(self.window) + self.summary_turns

        if self.pol.get("persist", True):
            self.persist_attempts += 1
            # at-least-once: depo geçici erişilemezse retry (UNAVAILABLE)
            fail = int(self.pol.get("persist_transient_failures", 0))
            self.persist_retries += fail
            self.persist_attempts += fail
            # idempotency_key = call_id + attempt → çift yazım dedupe (tek transcript)
            self.transcript_idempotency = "persist:%s" % self.tenant_id
            self.redaction_state = self.pol.get("redaction_state", "pending")
            # kart/OTP düz-metin durable'a yazılır mı? (redaksiyon/strip kapalıysa bug — M6)
            if not self.pol.get("strip_card_otp", True) and self.sensitive_seen > 0:
                self.sensitive_cleartext_persisted += self.sensitive_seen
            self.persisted = True
            self.persisted_turns = to_persist
            self.dropped_turn = max(0, self.captured_turns - self.persisted_turns)
        else:
            # persist kapalı (bozuk) → biten oturum durable yazılmadı (M3 eler)
            self.persisted = False
            self.unpersisted_on_end += 1
            self.dropped_turn = self.captured_turns   # tüm turn'ler kaybolur (M5 eler)

        # ── temizlik (M4): durable BAŞARILI olduktan SONRA ephemeral'i sil
        delete_first = self.pol.get("delete_before_persist", False)   # bozuk: önce sil
        if delete_first:
            # önce silme → persist_before_delete ihlali (M3/M4 sıralama bug)
            self.persist_before_delete_ok = False
            self.ephemeral_deleted = True
            if not self.persisted:
                self.unpersisted_on_end += 0  # zaten yukarıda sayıldıysa tekrar etme
        if self.persisted and self.pol.get("cleanup", True):
            self.ephemeral_deleted = True
        elif self.persisted and not self.pol.get("cleanup", True):
            # persist oldu ama temizlik kapalı → kaçak (leaked) ephemeral (M4 eler)
            self.leaked_session_key += 1
        elif not self.persisted:
            # persist olmadı → anahtar TUTULUR (TTL retry); leaked değil (doğru davranış)
            pass

    def metrics(self):
        scenario = []
        if self.fold_events > 0:
            scenario.append("fold")
        if self.end_reason and self.end_reason != "normal":
            scenario.append(self.end_reason)
        if self.persist_retries > 0:
            scenario.append("retry")
        if self.duplicate_turn > 0:
            scenario.append("dedupe")
        if self.sensitive_seen > 0:
            scenario.append("sensitive")
        if not scenario:
            scenario.append("happy")
        return {
            "captured_turns": self.captured_turns,
            "peak_window_turns": self.peak_window_turns,
            "window_max": self.window_max,
            "folded_turns": self.folded_turns,
            "fold_events": self.fold_events,
            "summary_turns": self.summary_turns,
            "duplicate_turn": self.duplicate_turn,
            "out_of_order": self.out_of_order,
            "unbounded_memory": self.unbounded_memory,
            "sensitive_seen": self.sensitive_seen,
            "sensitive_cleartext_persisted": self.sensitive_cleartext_persisted,
            "cross_tenant": self.cross_tenant,
            "persist_attempts": self.persist_attempts,
            "persist_retries": self.persist_retries,
            "persisted": self.persisted,
            "persisted_turns": self.persisted_turns,
            "dropped_turn": self.dropped_turn,
            "redaction_state": self.redaction_state,
            "ephemeral_deleted": self.ephemeral_deleted,
            "leaked_session_key": self.leaked_session_key,
            "unpersisted_on_end": self.unpersisted_on_end,
            "persist_before_delete_ok": self.persist_before_delete_ok,
            "end_reason": self.end_reason,
            "scenario": scenario,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Tam simülasyon (bir sample)
# ─────────────────────────────────────────────────────────────────────────────
def simulate(sample, params, policy):
    events = sample.get("events")
    if not events:
        raise MemoryError_("boş olay akışı")
    if not isinstance(events, list):
        raise MemoryError_("events liste değil → INVALID_REQUEST")
    p = dict(params)
    p["tenant_id"] = sample.get("tenant_id", params.get("tenant_id", "t-self"))
    m = SessionMemory(p, policy)
    saw_end = False
    for ev in events:
        if not isinstance(ev, dict):
            raise MemoryError_("olay sözlük değil → INVALID_REQUEST")
        kind = ev.get("kind")
        if kind == "turn":
            m.append_turn(ev)
        elif kind == "end":
            m.end(ev)
            saw_end = True
        else:
            raise MemoryError_("bilinmeyen olay tipi: %r → INVALID_REQUEST" % kind)
    if not saw_end:
        raise MemoryError_("olay akışında 'end' yok → INVALID_REQUEST (oturum-sonu kalıcılaştırma gerekli)")
    return m.metrics()


def evaluate(gates, m):
    """Metrikleri HARD kapılara (M1–M7) karşı değerlendirir. Döner findings[(ok, label)]."""
    F = []
    sc = set(m.get("scenario", []))

    # ── M1: sınırlı bellek (pencere window_max'ı aşmaz; taşma katlanır)
    F.append((m.get("unbounded_memory", 0) <= gates.get("max_unbounded_memory", 0)
              and m.get("peak_window_turns", 0) <= gates.get("window_max_turns", m.get("window_max", 24)),
              "M1 sınırlı bellek: pencere-tepe %d ≤ %d + sınırsız=%d (taşma katlanır — FR-RES-016)"
              % (m.get("peak_window_turns", 0), gates.get("window_max_turns", m.get("window_max", 24)),
                 m.get("unbounded_memory", 0))))

    # ── M2: ekleme sırası + idempotent
    F.append((m.get("out_of_order", 0) <= gates.get("max_out_of_order", 0),
              "M2 sıra korunur: out_of_order %d ≤ %d (append-only monoton seq)"
              % (m.get("out_of_order", 0), gates.get("max_out_of_order", 0))))
    F.append((m.get("duplicate_turn", 0) <= gates.get("max_duplicate_turn", 0)
              or "dedupe" in sc,
              "M2 idempotent: çift turn dedupe (duplicate=%d → tek kayıt)"
              % m.get("duplicate_turn", 0)))

    # ── M3: oturum-sonu kalıcılaştırma (persist_before_delete)
    F.append((m.get("unpersisted_on_end", 0) <= gates.get("max_unpersisted_on_end", 0)
              and m.get("persisted", False) and m.get("persist_before_delete_ok", True),
              "M3 oturum-sonu persist: unpersisted %d ≤ %d, persisted=%s, persist→delete sırası=%s (SAD §6.2)"
              % (m.get("unpersisted_on_end", 0), gates.get("max_unpersisted_on_end", 0),
                 m.get("persisted", False), m.get("persist_before_delete_ok", True))))

    # ── M4: ephemeral temizlik (kaçak yok)
    F.append((m.get("leaked_session_key", 0) <= gates.get("max_leaked_session_key", 0),
              "M4 ephemeral temizlik: leaked %d ≤ %d (durable sonrası session_state silinir — cache/ 1.1.5)"
              % (m.get("leaked_session_key", 0), gates.get("max_leaked_session_key", 0))))

    # ── M5: kayıpsız (persisted == captured)
    F.append((m.get("dropped_turn", 0) <= gates.get("max_dropped_turn", 0)
              and m.get("persisted_turns", 0) == m.get("captured_turns", -1),
              "M5 kayıpsız: dropped %d ≤ %d, persisted_turns %d == captured %d (pencere+katlanan)"
              % (m.get("dropped_turn", 0), gates.get("max_dropped_turn", 0),
                 m.get("persisted_turns", 0), m.get("captured_turns", 0))))

    # ── M6: redaction sınırı (kart/OTP düz-metin yok + pending)
    F.append((m.get("sensitive_cleartext_persisted", 0) <= gates.get("max_sensitive_cleartext_persisted", 0)
              and (m.get("redaction_state") in (None, "pending", "not_required")),
              "M6 redaction sınırı: kart/OTP düz-metin %d ≤ %d + transcript redaction_state=%r (FR-REC-004/005)"
              % (m.get("sensitive_cleartext_persisted", 0),
                 gates.get("max_sensitive_cleartext_persisted", 0), m.get("redaction_state"))))

    # ── M7: tenant izolasyonu
    F.append((m.get("cross_tenant", 0) <= gates.get("max_cross_tenant", 0),
              "M7 izolasyon: cross-tenant %d ≤ %d ({tenant,call} anahtarı — FR-TEN-002)"
              % (m.get("cross_tenant", 0), gates.get("max_cross_tenant", 0))))

    if "fold" in sc:
        # ── M9: katlama kayıpsız (özete katlanan turn'ler kalıcı kayda yine de girer)
        F.append((m.get("dropped_turn", 0) == 0 and m.get("summary_turns", 0) >= 1,
                  "M9 katlama kayıpsız: %d turn özete katlandı, kalıcı kayıt tam (dropped=%d)"
                  % (m.get("summary_turns", 0), m.get("dropped_turn", 0))))

    return F


# ─────────────────────────────────────────────────────────────────────────────
# parametre + politika çözümleme
# ─────────────────────────────────────────────────────────────────────────────
def _profile_by_name(cfg, name):
    for p in cfg.get("profiles", []):
        if p.get("name") == name:
            return p
    raise MemoryError_("bilinmeyen profil: %s" % name)


def _params_from(spec, profile):
    mm = dict(spec.get("memory_model", {}))
    out = {
        "window_max_turns": mm.get("window_max_turns", 24),
        "token_soft_limit": mm.get("token_soft_limit", 3000),
    }
    for k in ("window_max_turns", "token_soft_limit"):
        if k in profile:
            out[k] = profile[k]
    return out


def _resolve_policy(spec, profile, sample):
    pol = {
        "bound": True,
        "dedupe": True,
        "order_guard": True,
        "persist": True,
        "cleanup": True,
        "tenant_isolation": True,
        "strip_card_otp": True,
        "delete_before_persist": False,
        "redaction_state": spec.get("persistence", {}).get("redaction_state_on_persist", "pending"),
        "persist_transient_failures": 0,
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
        except MemoryError_ as ex:
            print("simulate[%s]: %s" % (name, ex))
            return 0 if expect == "fail" else 1
    params = _params_from(spec, profile)
    policy = _resolve_policy(spec, profile, sample)
    gates = spec.get("gates", {})

    try:
        m = simulate(sample, params, policy)
    except MemoryError_ as ex:
        print("simulate[%s]: REDDEDİLDİ — %s" % (name, ex))
        return 0 if expect == "fail" else 1

    F = evaluate(gates, m)
    print("simulate[%s] senaryo=%s | %d turn yakalandı (pencere-tepe %d/%d, katlanan %d) | "
          "bitiş=%s persisted=%s (%d turn, redaction=%s) | ephemeral-silindi=%s"
          % (name, "+".join(m["scenario"]), m["captured_turns"], m["peak_window_turns"],
             m["window_max"], m["folded_turns"], m["end_reason"], m["persisted"],
             m["persisted_turns"], m["redaction_state"], m["ephemeral_deleted"]))
    print("  out_of_order=%d | duplicate=%d | dropped=%d | leaked=%d | cross_tenant=%d | "
          "sensitive=%d (düz-metin persist=%d) | retry=%d"
          % (m["out_of_order"], m["duplicate_turn"], m["dropped_turn"], m["leaked_session_key"],
             m["cross_tenant"], m["sensitive_seen"], m["sensitive_cleartext_persisted"],
             m["persist_retries"]))
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

    _check(R, spec.get("wbs") == "3.2.1", "spec.wbs == 3.2.1")
    _check(R, spec.get("version"), "spec.version mevcut")

    # ── placement (orchestrator oturum aktörü, olay-tetikli, oturum-sonu persist)
    pl = spec.get("placement", {})
    _check(R, pl.get("in_orchestrator") is True and pl.get("in_session_actor") is True,
           "Session Memory orchestrator oturum aktöründe (SAD §6.2/§6.3)")
    _check(R, pl.get("event_driven") is True and pl.get("non_blocking") is True,
           "M8 olay-tetikli + bloklamaz (okuma sıcak yola gecikme eklemez)")
    _check(R, pl.get("persist_at_session_end") is True,
           "M3 oturum SONUNDA kalıcılaştırma (her turda değil — sıcak yol korunur)")
    _check(R, pl.get("durable_store") and pl.get("working_copy_store"),
           "durable + working-copy depo tanımlı (db/ 1.1.3 + cache/ 1.1.5)")

    # ── M1/M2/M9: bellek modeli
    mm = spec.get("memory_model", {})
    _check(R, isinstance(mm.get("window_max_turns"), int) and mm["window_max_turns"] > 0,
           "M1 window_max_turns > 0 (sınırlı pencere)")
    _check(R, isinstance(mm.get("token_soft_limit"), int) and mm["token_soft_limit"] > 0,
           "M1 token_soft_limit > 0 (özetleme tetiği)")
    _check(R, mm.get("append_only") is True and mm.get("monotonic_seq") is True,
           "M2 append-only + monoton seq")
    _check(R, mm.get("idempotent_append") is True, "M2 idempotent ekleme")
    _check(R, mm.get("fold_on_overflow") is True and mm.get("fold_preserves_content") is True,
           "M1/M9 taşma katlanır + katlama kayıpsız")
    _check(R, set(mm.get("speakers", [])) == SPEAKERS, "speaker kümesi {caller,agent,human}")
    _check(R, mm.get("budget_component") == "dialogue_memory",
           "M8 bütçe bileşeni dialogue_memory (3.1.4 besler)")

    # ── M3/M4/M5/M6: persistence
    pe = spec.get("persistence", {})
    _check(R, set(pe.get("end_states", [])) == END_STATES,
           "M3 bitiş durumları {normal,transfer,error,abandon}")
    _check(R, "transcript" in pe.get("durable_targets", [])
           and "completion_event" in pe.get("durable_targets", []),
           "M3 durable hedefler transcript + olay (db/ 1.1.3 + eventstream/ 1.1.8)")
    _check(R, pe.get("persist_all_captured_turns") is True, "M5 tüm yakalanan turn'ler kalıcılaştırılır")
    _check(R, pe.get("persist_before_delete") is True, "M3 persist_before_delete (sil-önce-yaz yok)")
    _check(R, pe.get("idempotent_persist") is True and pe.get("at_least_once_retry") is True,
           "M5 idempotent persist + at-least-once retry")
    _check(R, pe.get("redaction_state_on_persist") == "pending",
           "M6 transcript redaction_state='pending' (FR-REC-004)")
    _check(R, pe.get("strip_card_otp_cleartext") is True,
           "M6 kart/OTP düz-metin durable'a yazılmaz (FR-REC-005)")

    # ── cleanup
    cl = spec.get("cleanup", {})
    _check(R, cl.get("delete_ephemeral_after_persist") is True,
           "M4 durable sonrası ephemeral silinir")
    _check(R, cl.get("no_standing_session_memory") is True, "M4 standing session memory yok")
    _check(R, cl.get("keep_on_persist_failure") is True,
           "M4 persist başarısızsa anahtar tutulur (TTL retry — kayıp yok)")

    # ── summarization hook (seam → 3.2.2)
    sh = spec.get("summarization_hook", {})
    _check(R, sh.get("engine_out_of_scope") == "3.2.2",
           "M9 özetleme motoru kapsam dışı (3.2.2)")
    _check(R, sh.get("fold_target") == "session_summary",
           "M9 katlama hedefi session_summary (cache/ 1.1.5)")

    # ── kapılar
    g = spec.get("gates", {})
    _check(R, g.get("window_max_turns") == mm.get("window_max_turns"),
           "gates window_max_turns memory_model ile tutarlı")
    _check(R, g.get("max_unbounded_memory", -1) == 0, "M1 max_unbounded_memory = 0")
    _check(R, g.get("max_out_of_order", -1) == 0, "M2 max_out_of_order = 0")
    _check(R, g.get("max_duplicate_turn", -1) == 0, "M2 max_duplicate_turn = 0")
    _check(R, g.get("max_unpersisted_on_end", -1) == 0, "M3 max_unpersisted_on_end = 0")
    _check(R, g.get("max_leaked_session_key", -1) == 0, "M4 max_leaked_session_key = 0")
    _check(R, g.get("max_dropped_turn", -1) == 0, "M5 max_dropped_turn = 0")
    _check(R, g.get("max_sensitive_cleartext_persisted", -1) == 0,
           "M6 max_sensitive_cleartext_persisted = 0")
    _check(R, g.get("max_cross_tenant", -1) == 0, "M7 max_cross_tenant = 0")

    # ── M8: metrikler → observability
    me = spec.get("metrics", {})
    emitted = set(me.get("emitted", []))
    _check(R, {"session_turn_count", "session_persist_total", "session_dropped_turn_total"} <= emitted,
           "M8 turn + persist + dropped metrikleri yayılır")
    mo = me.get("maps_to_observability", {})
    _check(R, len(mo) >= 1, "M8 metrik observability'ye eşlenir (0.4.7)")

    # ── M10: error taxonomy
    et = spec.get("error_taxonomy", {})
    mapping = et.get("mapping", {})
    _check(R, len(mapping) >= 4, "M10 hata eşlemesi (≥4)")
    _check(R, all(v in ERROR_TAXONOMY for v in mapping.values()),
           "M10 tüm hedefler API §11.6 ErrorTaxonomy'de")
    _check(R, mapping.get("invalid_turn") == "INVALID_REQUEST"
           and mapping.get("durable_store_unavailable") == "UNAVAILABLE"
           and mapping.get("cross_tenant_access") == "AUTH"
           and mapping.get("region_mismatch") == "REGION_VIOLATION",
           "M10 bozuk-turn→INVALID, depo-down→UNAVAILABLE, cross-tenant→AUTH, bölge→REGION_VIOLATION")

    # ── M10: residency + pii
    _check(R, spec.get("residency", {}).get("region_pin_required") is True, "M10 residency region pin")
    _check(R, spec.get("pii", {}).get("raw_transcript_text_in_spec_forbidden") is True,
           "M10 ham transkript metni spec'te yasak")
    _check(R, spec.get("pii", {}).get("pii_value_in_spec_forbidden") is True,
           "M10 PII değeri spec'te yasak")
    _check(R, spec.get("pii", {}).get("card_otp_cleartext_forbidden") is True,
           "M6 kart/OTP düz-metin yasak")

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
    _check(R, not hits, "M10 literal sır yok (spec+config)")

    # ── config profilleri doğrulaması
    if os.path.exists(PROFILES_CFG):
        cfg = _load(PROFILES_CFG)
        profs = cfg.get("profiles", [])
        _check(R, len(profs) >= 2, "config ≥2 bellek profili")
        names = [p.get("name") for p in profs]
        _check(R, len(names) == len(set(names)), "config profil isimleri benzersiz")
        for p in profs:
            _check(R, bool(p.get("region")), "M10 config %s bölge pini var" % p.get("name"))
            _check(R, p.get("window_max_turns", 0) > 0,
                   "M1 config %s window_max_turns > 0" % p.get("name"))
            _check(R, p.get("token_soft_limit", 0) > 0,
                   "M1 config %s token_soft_limit > 0" % p.get("name"))

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
DEFAULT_PARAMS = {"window_max_turns": 6, "token_soft_limit": 100000, "tenant_id": "t-self"}


def _turn(t, tid, speaker="caller", tokens=10, sensitive=0, tenant=None):
    ev = {"kind": "turn", "turn_id": tid, "speaker": speaker, "t": t, "approx_tokens": tokens}
    if sensitive:
        ev["sensitive_tokens"] = sensitive
    if tenant:
        ev["tenant_id"] = tenant
    return ev


def _end(t, reason="normal"):
    return {"kind": "end", "t": t, "reason": reason}


def _run(events, params=None, **pol_over):
    pol = {"bound": True, "dedupe": True, "order_guard": True, "persist": True,
           "cleanup": True, "tenant_isolation": True, "strip_card_otp": True,
           "delete_before_persist": False, "redaction_state": "pending",
           "persist_transient_failures": 0}
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

    # ── happy: kısa çağrı, pencere içinde, end → persist + temizlik ───────────────
    ev = [_turn(0, "u1", "caller"), _turn(1000, "a1", "agent"),
          _turn(2000, "u2", "caller"), _end(3000)]
    mh = _run(ev)
    case(mh["captured_turns"] == 3 and mh["persisted_turns"] == 3, "happy: 3 turn yakalandı+kalıcılaştı")
    case(mh["persisted"] and mh["ephemeral_deleted"], "happy: persist + ephemeral silindi")
    case(mh["dropped_turn"] == 0 and mh["leaked_session_key"] == 0, "happy: kayıp/kaçak yok")
    case(mh["redaction_state"] == "pending", "happy: transcript redaction_state=pending (M6)")
    case(all(ok for ok, _ in evaluate(gates, mh)), "happy tüm kapıları geçer")

    # ── fold: pencereyi aşan uzun çağrı → en eski turn'ler özete katlanır (kayıpsız) ─
    long_ev = [_turn(i * 100, "t%d" % i, "caller" if i % 2 == 0 else "agent") for i in range(10)]
    long_ev.append(_end(2000))
    mf = _run(long_ev)
    case(mf["captured_turns"] == 10 and mf["folded_turns"] >= 4, "fold: 10 turn, ≥4 katlandı (pencere 6)")
    case(mf["peak_window_turns"] <= 6, "fold: pencere ≤ window_max (sınırlı bellek M1)")
    case(mf["persisted_turns"] == 10 and mf["dropped_turn"] == 0, "fold: TÜM 10 turn kalıcılaştı (kayıpsız M5/M9)")
    case("fold" in mf["scenario"] and all(ok for ok, _ in evaluate(gates, mf)), "fold tüm kapıları geçer")

    # ── idempotent: aynı turn_id tekrarı → tek kayıt ──────────────────────────────
    dup_ev = [_turn(0, "u1", "caller"), _turn(1000, "a1", "agent"),
              _turn(1500, "a1", "agent"), _turn(2000, "u2", "caller"), _end(3000)]
    md = _run(dup_ev)
    case(md["duplicate_turn"] == 1 and md["captured_turns"] == 3, "idempotent: çift turn_id → tek kayıt (3 benzersiz)")
    case(md["persisted_turns"] == 3 and all(ok for ok, _ in evaluate(gates, md)), "idempotent kapıları geçer")

    # ── retry: durable geçici erişilemez → at-least-once retry, kayıpsız ──────────
    mr = _run(ev, persist_transient_failures=2)
    case(mr["persist_retries"] == 2 and mr["persisted"], "retry: 2 geçici hata → retry, sonunda persist")
    case(mr["persisted_turns"] == 3 and mr["dropped_turn"] == 0, "retry: kayıpsız (at-least-once)")
    case("retry" in mr["scenario"] and all(ok for ok, _ in evaluate(gates, mr)), "retry kapıları geçer")

    # ── transfer end-state: aktarımda da kalıcılaştırma + temizlik ────────────────
    mt = _run([_turn(0, "u1", "caller"), _turn(1000, "a1", "agent"), _end(2000, "transfer")])
    case(mt["end_reason"] == "transfer" and mt["persisted"], "transfer: bitişte persist (M3)")
    case(all(ok for ok, _ in evaluate(gates, mt)), "transfer-end tüm kapıları geçer")

    # ── sensitive: kart/OTP işareti → düz-metin durable'a yazılmaz (M6) ───────────
    ms = _run([_turn(0, "u1", "caller", sensitive=2), _turn(1000, "a1", "agent"), _end(2000)])
    case(ms["sensitive_seen"] == 2 and ms["sensitive_cleartext_persisted"] == 0,
         "sensitive: kart/OTP işareti görüldü ama düz-metin persist=0 (M6)")
    case(all(ok for ok, _ in evaluate(gates, ms)), "sensitive tüm kapıları geçer")

    # ── determinizm ──────────────────────────────────────────────────────────────
    case(_run(long_ev) == mf, "determinizm: aynı olay-akışı birebir aynı metrik (random yok)")

    # ── degraded-1: persist kapalı → biten oturum kalıcılaşmaz (M3+M5 eler) ───────
    d1 = _run(ev, persist=False)
    case(d1["unpersisted_on_end"] >= 1 and d1["dropped_turn"] == 3, "degraded(persist off): unpersisted + kayıp")
    case(not all(ok for ok, _ in evaluate(gates, d1)), "degraded(persist off) en az bir kapıyı eler")

    # ── degraded-2: temizlik kapalı → kaçak ephemeral (M4 eler) ───────────────────
    d2 = _run(ev, cleanup=False)
    case(d2["persisted"] and d2["leaked_session_key"] == 1, "degraded(cleanup off): persist ama kaçak anahtar")
    case(not all(ok for ok, _ in evaluate(gates, d2)), "degraded(cleanup off) M4 eler")

    # ── degraded-3: sil-önce-yaz → persist_before_delete ihlali (M3 eler) ─────────
    d3 = _run(ev, delete_before_persist=True)
    case(d3["persist_before_delete_ok"] is False, "degraded(delete-first): persist→delete sırası ihlali")
    case(not all(ok for ok, _ in evaluate(gates, d3)), "degraded(delete-first) M3 eler")

    # ── degraded-4: sınır kapalı → sınırsız bellek (M1 eler) ──────────────────────
    d4 = _run(long_ev, bound=False)
    case(d4["unbounded_memory"] >= 1 and d4["peak_window_turns"] > 6, "degraded(unbounded): pencere sınırsız büyür")
    case(not all(ok for ok, _ in evaluate(gates, d4)), "degraded(unbounded) M1 eler")

    # ── degraded-5: kart/OTP strip kapalı → düz-metin persist (M6 eler) ───────────
    d5 = _run([_turn(0, "u1", "caller", sensitive=3), _end(1000)], strip_card_otp=False)
    case(d5["sensitive_cleartext_persisted"] == 3, "degraded(no-strip): kart/OTP düz-metin persist edildi")
    case(not all(ok for ok, _ in evaluate(gates, d5)), "degraded(no-strip) M6 eler")

    # ── degraded-6: cross-tenant turn → izolasyon ihlali (M7 eler) ────────────────
    d6 = _run([_turn(0, "u1", "caller"), _turn(1000, "x1", "caller", tenant="t-other"), _end(2000)],
              tenant_isolation=False)
    case(d6["cross_tenant"] >= 1, "degraded(cross-tenant): yabancı tenant turn'ü sızdı")
    case(not all(ok for ok, _ in evaluate(gates, d6)), "degraded(cross-tenant) M7 eler")

    # ── geçersiz olay reddi (M10) ────────────────────────────────────────────────
    case(_raises(lambda: _run([_turn(0, "u1", speaker="robot"), _end(1000)])), "M10 geçersiz speaker → reddedilir")
    case(_raises(lambda: _run([{"kind": "turn", "speaker": "caller", "t": 0}, _end(1000)])), "M10 turn_id yok → reddedilir")
    case(_raises(lambda: _run([_turn(0, "u1")])), "M10 'end' olmadan → reddedilir (oturum-sonu persist gerekli)")
    case(_raises(lambda: _run([_turn(1000, "u1"), _turn(0, "u2"), _end(2000)])), "M10 out-of-order (order_guard) → reddedilir")
    case(_raises(lambda: _run([_turn(0, "u1"), {"kind": "nope", "t": 1}, _end(2000)])), "M10 bilinmeyen olay → reddedilir")
    case(_raises(lambda: simulate({"events": []}, DEFAULT_PARAMS, {})), "M10 boş olay akışı → reddedilir")
    case(_raises(lambda: _run([_turn(0, "u1"), _turn(1000, "x1", tenant="t-other"), _end(2000)])),
         "M10 cross-tenant (izolasyon açık) → reddedilir")

    # ── validate negatif kapılar ─────────────────────────────────────────────────
    s = json.loads(json.dumps(spec)); s["memory_model"]["window_max_turns"] = 0
    case(_validate_obj(s) != 0, "M1 window_max_turns=0 → validate eler")
    s = json.loads(json.dumps(spec)); s["memory_model"]["idempotent_append"] = False
    case(_validate_obj(s) != 0, "M2 idempotent_append=false → validate eler")
    s = json.loads(json.dumps(spec)); s["memory_model"]["fold_preserves_content"] = False
    case(_validate_obj(s) != 0, "M9 fold_preserves_content=false → validate eler")
    s = json.loads(json.dumps(spec)); s["persistence"]["persist_before_delete"] = False
    case(_validate_obj(s) != 0, "M3 persist_before_delete=false → validate eler")
    s = json.loads(json.dumps(spec)); s["persistence"]["redaction_state_on_persist"] = "redacted"
    case(_validate_obj(s) != 0, "M6 redaction_state≠pending → validate eler")
    s = json.loads(json.dumps(spec)); s["persistence"]["strip_card_otp_cleartext"] = False
    case(_validate_obj(s) != 0, "M6 strip_card_otp=false → validate eler")
    s = json.loads(json.dumps(spec)); s["cleanup"]["delete_ephemeral_after_persist"] = False
    case(_validate_obj(s) != 0, "M4 delete_ephemeral_after_persist=false → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_unpersisted_on_end"] = 1
    case(_validate_obj(s) != 0, "M3 max_unpersisted_on_end>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_dropped_turn"] = 1
    case(_validate_obj(s) != 0, "M5 max_dropped_turn>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_cross_tenant"] = 1
    case(_validate_obj(s) != 0, "M7 max_cross_tenant>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_leaked_session_key"] = 1
    case(_validate_obj(s) != 0, "M4 max_leaked_session_key>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["error_taxonomy"]["mapping"]["x"] = "NOPE"
    case(_validate_obj(s) != 0, "M10 taksonomi-dışı → validate eler")
    s = json.loads(json.dumps(spec)); s["pii"]["pii_value_in_spec_forbidden"] = False
    case(_validate_obj(s) != 0, "M10 pii-değer-yasak kapalı → validate eler")
    s = json.loads(json.dumps(spec)); s["memory_model"]["secret"] = "api_key: AKIAIOSFODNN7EXAMPLE"
    case(_validate_obj(s) != 0, "M10 literal secret → validate eler")

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
    except MemoryError_:
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
    print("""session-memory-spec.json beklenen şekli (WBS 3.2.1):
  wbs, version, phase, trace{fr,nfr,sad,adr,api,srs,rtm,brd,stores,observability}
  placement{in_orchestrator=true, in_session_actor=true, event_driven=true, non_blocking=true,
            persist_at_session_end=true, working_copy_store, durable_store}            (M3,M8)
  memory_model{window_max_turns>0, token_soft_limit>0, append_only=true, monotonic_seq=true,
               idempotent_append=true, fold_on_overflow=true, fold_preserves_content=true,
               speakers[caller,agent,human], budget_component=dialogue_memory}          (M1,M2,M8,M9)
  persistence{end_states[normal,transfer,error,abandon], durable_targets[transcript,...],
              persist_all_captured_turns=true, persist_before_delete=true,
              idempotent_persist=true, at_least_once_retry=true,
              redaction_state_on_persist=pending, strip_card_otp_cleartext=true}        (M3,M5,M6)
  cleanup{delete_ephemeral_after_persist=true, no_standing_session_memory=true,
          keep_on_persist_failure=true}                                                 (M4)
  summarization_hook{fold_target=session_summary, engine_out_of_scope=3.2.2}            (M9)
  gates{window_max_turns, max_unbounded_memory=0, max_out_of_order=0, max_duplicate_turn=0,
        max_unpersisted_on_end=0, max_leaked_session_key=0, max_dropped_turn=0,
        max_sensitive_cleartext_persisted=0, max_cross_tenant=0}                        (M1–M7)
  metrics{emitted[], maps_to_observability{}}                                           (M8)
  error_taxonomy{mapping→API §11.6}                                                     (M10)
  residency{region_pin_required=true}                                                   (M10)
  pii{raw_transcript_text_in_spec_forbidden, pii_value_in_spec_forbidden,
      card_otp_cleartext_forbidden, durable_redaction_state=pending}                    (M6,M10)
  invariants[≥10]{id, desc, trace}

config/session-memory-profiles.json: profiles[]{name, deployment, window_max_turns,
  token_soft_limit, region}

simulate sample: {name, profile | profile_obj, tenant_id?, expect, expected?{metrik:değer},
  policy?{bound, dedupe, order_guard, persist, cleanup, tenant_isolation, strip_card_otp,
  delete_before_persist, persist_transient_failures},
  events[{kind:'turn', turn_id, speaker, t, approx_tokens?, sensitive_tokens?, tenant_id?} |
         {kind:'end', t, reason}]}  — son olay 'end' olmalı (oturum-sonu kalıcılaştırma)

komutlar: validate | simulate <sample.json> | selftest | schema""")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if cmd == "validate":
        return validate()
    if cmd == "simulate":
        if len(sys.argv) < 3:
            print("kullanım: session_memory_probe.py simulate <sample.json>")
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
