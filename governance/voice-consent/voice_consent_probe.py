#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
voice_consent_probe.py — WBS 4.2.6 Ses klonlama izin + kullanım kaydı (onaylı sesler)

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only statik + davranış kapısı. `adapters/` ve
`runtime/` modül disipliniyle aynı; burada ses klonlama/özel ses YÖNETİŞİM kapısını DETERMİNİSTİK
bir karar motoru ile modeller (olay-tetikli, sanal saat, random YOK; gerçek ses/voiceprint YOK —
yalnız kayıt defteri durumu + opak referanslar). Görev başlığındaki iki boyut:
  • ONAYLI SESLER (FR-TTS-006):  Yalnız status=approved ses kullanılabilir; draft/pending/suspended/
                                 revoked → DENY (V1). Onay maker-checker'lı (V9).
  • İZİN + KULLANIM KAYDI (FR-TTS-007): Klonlanmış ses GEÇERLİ izin (consent) olmadan kullanılamaz
                                 (V2); süre dolumu (V3) / geri çekme (V4) / kapsam (V5) zorlanır;
                                 izin verilen her kullanım tam BİR usage record üretir (V7).

TtsAdapter (4.2.3) synthesize() ÖNCESİ VoiceProfile.clonedVoiceConsentRef'i bu deftere çözer; karar
ALLOW değilse ses ÜRETİLMEZ (ADR-001; orchestrator yalnız karara bağımlı). Kayıtlar WORM/append-only
(V10), home-region (V12), tenant-izole (V6); ham ses/voiceprint/biyometrik/PII DEĞERİ saklanmaz (V11).

KAPSAM AYRIMI: gerçek ses klonlama/sentez → 4.2.3 TtsAdapter (clonedVoiceConsentRef tüketilir);
eşdeğer-ses/karakter tutarlılığı → 4.3.2/FR-TTS-009; ses BİYOMETRİSİ (kimlik doğrulama) → FR-AUTH-006/007
(ayrı modül, burada DEĞER tutulmaz); no-deceptive-impersonation politikası → 3.3.3; audit_log fiziksel
şeması → 1.1.4; retention motoru → 1.2.3; residency zorlama → 1.2.2; sağlayıcı SEÇİMİ → 0.2.6/0.3.x.

Komutlar:
  validate              voice-consent-spec.json'ı invariant'lara (V1–V12) + config profillerine doğrular.
  simulate <sample>     Deterministik karar motoru — yaşam döngüsü + use olay-akışı → ALLOW/DENY +
                        usage record + audit → HARD kapılar (P1–P8) → çıkış kodu.
  selftest              İyi/kötü spec+sample ile kapıların doğru tetiklendiğini kanıtlar.
  schema                Beklenen spec şeklini özetler.

Sunucu/credential GEREKMEZ. Ham SES/audio, voiceprint, biyometrik şablon veya PII DEĞERİ YOK —
yalnız ses/izin kimlikleri + opak referanslar + kapsam + sanal zaman.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "voice-consent-spec.json")
PROFILES_CFG = os.path.join(HERE, "config", "voice-consent-profiles.json")

ERROR_TAXONOMY = {
    "TIMEOUT", "RATE_LIMITED", "UNAVAILABLE", "AUTH",
    "INVALID_REQUEST", "CONTENT_FILTERED", "QUOTA_EXCEEDED", "REGION_VIOLATION",
}
SECRET_RE = re.compile(
    r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer)\b\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}"
)
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")

VOICE_KINDS = {"custom", "cloned"}
VOICE_STATUS = {"draft", "pending", "approved", "suspended", "revoked"}
CONSENT_STATE = {"granted", "withdrawn"}
DENY_REASONS = {
    "UNKNOWN_VOICE", "NOT_APPROVED", "NO_CONSENT", "UNKNOWN_CONSENT",
    "CONSENT_EXPIRED", "CONSENT_WITHDRAWN", "OUT_OF_SCOPE", "CROSS_TENANT",
}
FORBIDDEN_RECORD_KEYS = {"voiceprint", "raw_audio", "biometric_template", "pii_value", "voice_sample_b64"}
ALLOWED_RETENTION = {"NONE", "EPHEMERAL"}
LIFECYCLE_KINDS = {"register_voice", "grant_consent", "approve_voice",
                   "revoke_consent", "suspend_voice", "revoke_voice"}


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_placeholder(v):
    return isinstance(v, str) and PLACEHOLDER_RE.match(v) is not None


class VoiceConsentError(Exception):
    """Yapısal hata / yetki / WORM ihlali — sessizce kabul yok, reddet."""


# ─────────────────────────────────────────────────────────────────────────────
# Ses klonlama izin/kullanım kaydı karar motoru (deterministik)
# ─────────────────────────────────────────────────────────────────────────────
class VoiceConsentRegistry:
    """Yaşam döngüsü olaylarından kayıt defteri durumu kurar, her 'use' olayını
    ALLOW/DENY'e DETERMİNİSTİK karar bağlar (random YOK; sanal saat = event.t).

    Olaylar:
      {kind:'register_voice', voice_id, voice_kind∈{custom,cloned}, tenant_id, created_by, owner_subject_ref?, t}
      {kind:'grant_consent',  consent_id, voice_id, subject_ref, tenant_id, scope{tenants,agents,purposes},
                              evidence_ref, granted_by, expires_at, t}
      {kind:'approve_voice',  voice_id, approved_by, t}
      {kind:'revoke_consent', consent_id, t, revoked_by?}
      {kind:'suspend_voice',  voice_id, t}    {kind:'revoke_voice', voice_id, t}
      {kind:'use',  use_id, voice_id, consent_ref?, tenant_id, agent_id, purpose, t, seconds?, call_ref?}
      {kind:'mutate_record', target∈{consent,usage}, ref, t}   # WORM: reddedilmeli (V10)
    """

    def __init__(self, policy):
        self.pol = policy
        self.voices = {}            # voice_id -> {kind, tenant_id, status, created_by}
        self.consents = {}          # consent_id -> {voice_id, tenant_id, scope, expires_at, state, granted_at}
        self._last_t = None

        # kayıtlar
        self.usage_records = []     # append-only
        self.audit_events = 0
        self.expected_audit = 0     # her lifecycle + use kararı bir audit gerektirir

        # sayaçlar / kapı metrikleri
        self.use_total = 0
        self.allow_total = 0
        self.deny_total = 0
        self.deny_by_reason = {}
        self.allowed_cloned_uses = 0
        # ihlal sayaçları (yalnız POLİTİKA gevşetildiğinde uygunsuz ALLOW olur)
        self.unapproved_use_allowed = 0
        self.cloned_without_consent_allowed = 0
        self.use_after_expiry = 0
        self.use_after_revoke = 0
        self.out_of_scope_allowed = 0
        self.cross_tenant_allowed = 0
        self.self_approval = 0
        self.mutable_records = 0
        self.pii_in_record = 0
        self.region_violation = 0
        self.consents_active = 0

    # ── yardımcılar ───────────────────────────────────────────────────────────
    def _check_time(self, t):
        if not isinstance(t, (int, float)):
            raise VoiceConsentError("zaman damgası sayısal değil → INVALID_REQUEST")
        if self._last_t is not None and t < self._last_t:
            if self.pol.get("order_guard", True):
                raise VoiceConsentError("out-of-order olay (t geriye) reddedildi → INVALID_REQUEST")
        self._last_t = max(self._last_t if self._last_t is not None else t, t)

    def _scan_pii(self, ev):
        for k in ev.keys():
            if k in FORBIDDEN_RECORD_KEYS:
                self.pii_in_record += 1

    def _audit(self):
        self.expected_audit += 1
        if self.pol.get("audit", True):
            self.audit_events += 1

    # ── yaşam döngüsü ───────────────────────────────────────────────────────────
    def register_voice(self, ev):
        self._check_time(ev.get("t"))
        self._scan_pii(ev)
        vid = ev.get("voice_id")
        if not isinstance(vid, str) or not vid:
            raise VoiceConsentError("voice_id yok/boş → INVALID_REQUEST")
        if vid in self.voices:
            raise VoiceConsentError("voice_id tekrar kayıt → INVALID_REQUEST")
        kind = ev.get("voice_kind")
        if kind not in VOICE_KINDS:
            raise VoiceConsentError("geçersiz voice_kind: %r → INVALID_REQUEST" % kind)
        tenant = ev.get("tenant_id")
        if not isinstance(tenant, str) or not tenant:
            raise VoiceConsentError("tenant_id yok/boş → INVALID_REQUEST")
        self.voices[vid] = {
            "kind": kind, "tenant_id": tenant, "status": "pending",
            "created_by": ev.get("created_by"),
        }
        self._audit()

    def grant_consent(self, ev):
        self._check_time(ev.get("t"))
        self._scan_pii(ev)
        cid = ev.get("consent_id")
        if not isinstance(cid, str) or not cid:
            raise VoiceConsentError("consent_id yok/boş → INVALID_REQUEST")
        if cid in self.consents:
            # WORM: var olan consent mutasyonu değil; tekrar grant yeni id olmalı
            raise VoiceConsentError("consent_id tekrar kullanıldı (WORM) → INVALID_REQUEST")
        vid = ev.get("voice_id")
        v = self.voices.get(vid)
        if v is None:
            raise VoiceConsentError("bilinmeyen voice_id consent → INVALID_REQUEST")
        # ham ses/voiceprint değil opak ref zorunlu (V11)
        if not ev.get("subject_ref") or not ev.get("evidence_ref"):
            raise VoiceConsentError("subject_ref + evidence_ref (opak) zorunlu → INVALID_REQUEST")
        scope = ev.get("scope", {})
        if not isinstance(scope, dict):
            raise VoiceConsentError("scope sözlük değil → INVALID_REQUEST")
        self.consents[cid] = {
            "voice_id": vid,
            "tenant_id": ev.get("tenant_id", v["tenant_id"]),
            "scope": scope,
            "expires_at": ev.get("expires_at"),
            "state": "granted",
            "granted_at": ev.get("t"),
        }
        self.consents_active += 1
        self._audit()

    def approve_voice(self, ev):
        self._check_time(ev.get("t"))
        vid = ev.get("voice_id")
        v = self.voices.get(vid)
        if v is None:
            raise VoiceConsentError("bilinmeyen voice_id approve → INVALID_REQUEST")
        approved_by = ev.get("approved_by")
        if not approved_by:
            raise VoiceConsentError("approved_by zorunlu → INVALID_REQUEST")
        # V9: maker-checker — onaylayan ≠ oluşturan
        if approved_by == v.get("created_by"):
            if self.pol.get("maker_checker", True):
                raise VoiceConsentError("self-approval reddedildi (maker-checker) → AUTH")
            self.self_approval += 1
        v["status"] = "approved"
        self._audit()

    def revoke_consent(self, ev):
        self._check_time(ev.get("t"))
        cid = ev.get("consent_id")
        c = self.consents.get(cid)
        if c is None:
            raise VoiceConsentError("bilinmeyen consent_id revoke → INVALID_REQUEST")
        # WORM: durum geçişi (granted→withdrawn); mutasyon değil yeni DURUM
        c["state"] = "withdrawn"
        c["withdrawn_at"] = ev.get("t")
        if self.consents_active > 0:
            self.consents_active -= 1
        self._audit()

    def suspend_voice(self, ev):
        self._check_time(ev.get("t"))
        v = self.voices.get(ev.get("voice_id"))
        if v is None:
            raise VoiceConsentError("bilinmeyen voice_id suspend → INVALID_REQUEST")
        v["status"] = "suspended"
        self._audit()

    def revoke_voice(self, ev):
        self._check_time(ev.get("t"))
        v = self.voices.get(ev.get("voice_id"))
        if v is None:
            raise VoiceConsentError("bilinmeyen voice_id revoke → INVALID_REQUEST")
        v["status"] = "revoked"
        self._audit()

    def mutate_record(self, ev):
        # V10: WORM — consent/usage kaydı mutasyonu reddedilir
        self._check_time(ev.get("t"))
        if self.pol.get("worm", True):
            raise VoiceConsentError("WORM kayıt mutasyonu reddedildi → INVALID_REQUEST")
        self.mutable_records += 1
        self._audit()

    # ── karar: resolveVoiceUse (V1–V7) ──────────────────────────────────────────
    def use(self, ev):
        self._check_time(ev.get("t"))
        self._scan_pii(ev)
        use_id = ev.get("use_id")
        if not isinstance(use_id, str) or not use_id:
            raise VoiceConsentError("use_id yok/boş → INVALID_REQUEST")
        vid = ev.get("voice_id")
        use_tenant = ev.get("tenant_id")
        if not isinstance(use_tenant, str) or not use_tenant:
            raise VoiceConsentError("use.tenant_id yok/boş → INVALID_REQUEST")
        purpose = ev.get("purpose")
        agent_id = ev.get("agent_id")
        t = ev.get("t")
        self.use_total += 1

        decision, reason = self._decide(ev, vid, use_tenant, agent_id, purpose, t)

        if decision == "ALLOW":
            self.allow_total += 1
            v = self.voices.get(vid)
            if v and v["kind"] in set(self.pol.get("consent_required_for", ["cloned"])):
                self.allowed_cloned_uses += 1
                if self.pol.get("emit_usage_record", True):
                    self.usage_records.append({
                        "usage_id": use_id, "voice_id": vid,
                        "consent_id": ev.get("consent_ref"), "tenant_id": use_tenant,
                        "agent_id": agent_id, "purpose": purpose,
                        "call_ref": ev.get("call_ref"), "used_at": t,
                        "seconds": ev.get("seconds", 0),
                    })
        else:
            self.deny_total += 1
            self.deny_by_reason[reason] = self.deny_by_reason.get(reason, 0) + 1
        # her kullanım kararı denetlenir (V8)
        self._audit()
        return decision, reason

    def _decide(self, ev, vid, use_tenant, agent_id, purpose, t):
        consent_required = set(self.pol.get("consent_required_for", ["cloned"]))
        v = self.voices.get(vid)
        if v is None:
            return "DENY", "UNKNOWN_VOICE"

        # V6: tenant izolasyonu (ses sahibi tenant)
        if v["tenant_id"] != use_tenant:
            if self.pol.get("tenant_isolation", True):
                return "DENY", "CROSS_TENANT"
            self.cross_tenant_allowed += 1

        # V1: onaylı ses
        if v["status"] not in {"approved"}:
            if self.pol.get("enforce_approval", True):
                return "DENY", "NOT_APPROVED"
            self.unapproved_use_allowed += 1

        # V2–V5: klon ise izin zorunlu
        if v["kind"] in consent_required:
            cref = ev.get("consent_ref")
            c = self.consents.get(cref) if cref else None
            if c is None:
                if self.pol.get("require_consent_for_cloned", True):
                    return "DENY", ("UNKNOWN_CONSENT" if cref else "NO_CONSENT")
                self.cloned_without_consent_allowed += 1
                return "ALLOW", None  # gevşek: izinsiz klon (ihlal sayıldı)
            # consent bu sese ait + aynı tenant
            if c["voice_id"] != vid or c["tenant_id"] != use_tenant:
                if self.pol.get("tenant_isolation", True):
                    return "DENY", "CROSS_TENANT"
                self.cross_tenant_allowed += 1
            # V4: geri çekme
            if c["state"] == "withdrawn":
                if self.pol.get("honor_revocation", True):
                    return "DENY", "CONSENT_WITHDRAWN"
                self.use_after_revoke += 1
            # V3: süre dolumu
            exp = c.get("expires_at")
            if exp is not None and isinstance(t, (int, float)) and t > exp:
                if self.pol.get("honor_expiry", True):
                    return "DENY", "CONSENT_EXPIRED"
                self.use_after_expiry += 1
            # V5: kapsam (tenant/agent/purpose)
            if not self._in_scope(c.get("scope", {}), use_tenant, agent_id, purpose):
                if self.pol.get("enforce_scope", True):
                    return "DENY", "OUT_OF_SCOPE"
                self.out_of_scope_allowed += 1
        return "ALLOW", None

    def _in_scope(self, scope, tenant, agent, purpose):
        wc = "*"
        def covered(dim, val):
            allowed = scope.get(dim)
            if allowed is None:
                return False  # kapsam belirtilmemiş dimension → kapsam dışı (fail-closed)
            return wc in allowed or val in allowed
        return covered("tenants", tenant) and covered("agents", agent) and covered("purposes", purpose)

    def metrics(self):
        scenario = []
        if self.allow_total:
            scenario.append("allow")
        if self.deny_total:
            scenario.append("deny:" + "+".join(sorted(self.deny_by_reason)))
        if self.unapproved_use_allowed or self.cloned_without_consent_allowed \
                or self.use_after_expiry or self.use_after_revoke \
                or self.out_of_scope_allowed or self.cross_tenant_allowed:
            scenario.append("improper-allow")
        if self.mutable_records:
            scenario.append("mutated")
        if self.pii_in_record:
            scenario.append("pii")
        if not scenario:
            scenario.append("empty")
        missing_usage = self.allowed_cloned_uses - len(self.usage_records)
        return {
            "use_total": self.use_total,
            "allow_total": self.allow_total,
            "deny_total": self.deny_total,
            "deny_by_reason": self.deny_by_reason,
            "allowed_cloned_uses": self.allowed_cloned_uses,
            "usage_records": len(self.usage_records),
            "missing_usage_record": max(0, missing_usage),
            "audit_events": self.audit_events,
            "expected_audit": self.expected_audit,
            "unaudited_event": max(0, self.expected_audit - self.audit_events),
            "consents_active": self.consents_active,
            "unapproved_use_allowed": self.unapproved_use_allowed,
            "cloned_without_consent_allowed": self.cloned_without_consent_allowed,
            "use_after_expiry": self.use_after_expiry,
            "use_after_revoke": self.use_after_revoke,
            "out_of_scope_allowed": self.out_of_scope_allowed,
            "cross_tenant_allowed": self.cross_tenant_allowed,
            "self_approval": self.self_approval,
            "mutable_records": self.mutable_records,
            "pii_in_record": self.pii_in_record,
            "region_violation": self.region_violation,
            "scenario": scenario,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Tam simülasyon (bir sample)
# ─────────────────────────────────────────────────────────────────────────────
DISPATCH = {
    "register_voice": "register_voice", "grant_consent": "grant_consent",
    "approve_voice": "approve_voice", "revoke_consent": "revoke_consent",
    "suspend_voice": "suspend_voice", "revoke_voice": "revoke_voice",
    "mutate_record": "mutate_record", "use": "use",
}


def simulate(sample, policy):
    events = sample.get("events")
    if events is None or not isinstance(events, list) or not events:
        raise VoiceConsentError("boş/geçersiz olay akışı → INVALID_REQUEST")
    rt = VoiceConsentRegistry(policy)
    for ev in events:
        if not isinstance(ev, dict):
            raise VoiceConsentError("olay sözlük değil → INVALID_REQUEST")
        kind = ev.get("kind")
        meth = DISPATCH.get(kind)
        if meth is None:
            raise VoiceConsentError("bilinmeyen olay tipi: %r → INVALID_REQUEST" % kind)
        getattr(rt, meth)(ev)
    return rt.metrics()


def evaluate(gates, m):
    """Metrikleri HARD kapılara (P1–P8) karşı değerlendirir. Döner findings[(ok, label)]."""
    F = []

    # ── P1 (V1): onaylı ses
    F.append((m.get("unapproved_use_allowed", 0) <= gates.get("max_unapproved_use", 0),
              "P1 onaylı-ses: unapproved_use_allowed %d ≤ %d (yalnız approved kullanılır; FR-TTS-006)"
              % (m.get("unapproved_use_allowed", 0), gates.get("max_unapproved_use", 0))))

    # ── P2 (V2): klon → izin zorunlu
    F.append((m.get("cloned_without_consent_allowed", 0) <= gates.get("max_cloned_without_consent", 0),
              "P2 izin-zorunlu: cloned_without_consent_allowed %d ≤ %d (FR-TTS-007)"
              % (m.get("cloned_without_consent_allowed", 0), gates.get("max_cloned_without_consent", 0))))

    # ── P3 (V3/V4): süre dolumu + geri çekme
    F.append((m.get("use_after_expiry", 0) <= gates.get("max_use_after_expiry", 0)
              and m.get("use_after_revoke", 0) <= gates.get("max_use_after_revoke", 0),
              "P3 süre/iptal: use_after_expiry %d ≤ %d + use_after_revoke %d ≤ %d (FR-TTS-007)"
              % (m.get("use_after_expiry", 0), gates.get("max_use_after_expiry", 0),
                 m.get("use_after_revoke", 0), gates.get("max_use_after_revoke", 0))))

    # ── P4 (V5): kapsam
    F.append((m.get("out_of_scope_allowed", 0) <= gates.get("max_out_of_scope", 0),
              "P4 kapsam: out_of_scope_allowed %d ≤ %d (tenant/agent/purpose; FR-TTS-007)"
              % (m.get("out_of_scope_allowed", 0), gates.get("max_out_of_scope", 0))))

    # ── P5 (V6): tenant izolasyonu
    F.append((m.get("cross_tenant_allowed", 0) <= gates.get("max_cross_tenant", 0),
              "P5 tenant-izolasyon: cross_tenant_allowed %d ≤ %d (FR-TEN-002)"
              % (m.get("cross_tenant_allowed", 0), gates.get("max_cross_tenant", 0))))

    # ── P6 (V7): usage record bütünlüğü
    rec_ok = (not gates.get("require_usage_record", True)) \
        or m.get("missing_usage_record", 0) <= gates.get("max_missing_usage_record", 0)
    F.append((rec_ok,
              "P6 kullanım-kaydı: missing_usage_record %d ≤ %d (izin verilen %d klon kullanım → %d kayıt; FR-TTS-007)"
              % (m.get("missing_usage_record", 0), gates.get("max_missing_usage_record", 0),
                 m.get("allowed_cloned_uses", 0), m.get("usage_records", 0))))

    # ── P7 (V8): audit bütünlüğü
    aud_ok = (not gates.get("require_audit", True)) \
        or m.get("unaudited_event", 0) <= gates.get("max_unaudited_event", 0)
    F.append((aud_ok,
              "P7 audit: unaudited_event %d ≤ %d (%d/%d olay denetlendi; FR-IAM-006/FR-REC-009)"
              % (m.get("unaudited_event", 0), gates.get("max_unaudited_event", 0),
                 m.get("audit_events", 0), m.get("expected_audit", 0))))

    # ── P8 (V9/V10/V11): maker-checker + WORM + no-PII
    mc_ok = (not gates.get("require_maker_checker", True)) \
        or m.get("self_approval", 0) <= gates.get("max_self_approval", 0)
    worm_ok = m.get("mutable_records", 0) <= gates.get("max_mutable_record", 0)
    pii_ok = m.get("pii_in_record", 0) <= gates.get("max_pii_in_record", 0)
    F.append((mc_ok and worm_ok and pii_ok,
              "P8 maker-checker+WORM+no-PII: self_approval %d + mutable_records %d + pii_in_record %d (FR-TTS-006/FR-REC-009/TM-S-07)"
              % (m.get("self_approval", 0), m.get("mutable_records", 0), m.get("pii_in_record", 0))))

    return F


# ─────────────────────────────────────────────────────────────────────────────
# politika çözümleme
# ─────────────────────────────────────────────────────────────────────────────
def _default_policy():
    return {
        "enforce_approval": True,
        "require_consent_for_cloned": True,
        "honor_expiry": True,
        "honor_revocation": True,
        "enforce_scope": True,
        "tenant_isolation": True,
        "emit_usage_record": True,
        "audit": True,
        "maker_checker": True,
        "worm": True,
        "order_guard": True,
        "consent_required_for": ["cloned"],
    }


def _resolve_policy(sample):
    pol = _default_policy()
    pol.update(sample.get("policy", {}))
    return pol


def simulate_cmd(sample_path):
    spec = _load(SPEC_PATH)
    sample = _load(sample_path)
    name = sample.get("name", os.path.basename(sample_path))
    expect = sample.get("expect", "pass")
    gates = spec.get("gates", {})
    policy = _resolve_policy(sample)

    try:
        m = simulate(sample, policy)
    except VoiceConsentError as ex:
        print("simulate[%s]: REDDEDİLDİ — %s" % (name, ex))
        return 0 if expect == "fail" else 1

    F = evaluate(gates, m)
    print("simulate[%s] senaryo=%s | %d use → %d ALLOW / %d DENY %s | %d usage record | %d/%d denetlendi"
          % (name, "+".join(m["scenario"]), m["use_total"], m["allow_total"], m["deny_total"],
             dict(m["deny_by_reason"]) if m["deny_by_reason"] else "", m["usage_records"],
             m["audit_events"], m["expected_audit"]))
    print("  improper-allow: unapproved=%d cloned-no-consent=%d after-expiry=%d after-revoke=%d out-of-scope=%d cross-tenant=%d | self-approval=%d mutated=%d pii=%d"
          % (m["unapproved_use_allowed"], m["cloned_without_consent_allowed"], m["use_after_expiry"],
             m["use_after_revoke"], m["out_of_scope_allowed"], m["cross_tenant_allowed"],
             m["self_approval"], m["mutable_records"], m["pii_in_record"]))
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

    _check(R, spec.get("wbs") == "4.2.6", "spec.wbs == 4.2.6")
    _check(R, spec.get("version"), "spec.version mevcut")

    tr = spec.get("trace", {})
    _check(R, "FR-TTS-006" in tr.get("fr", []) and "FR-TTS-007" in tr.get("fr", []),
           "trace FR-TTS-006 + FR-TTS-007 (görev izi)")
    _check(R, "FR-TEN-002" in tr.get("fr", []), "trace FR-TEN-002 (tenant izolasyon)")
    _check(R, "FR-IAM-006" in tr.get("fr", []), "trace FR-IAM-006 (audit)")

    # ── placement
    pl = spec.get("placement", {})
    _check(R, pl.get("consulted_before_synthesis") is True,
           "synthesize ÖNCESİ danışılır (4.2.3 voice resolution gate)")
    _check(R, pl.get("orchestrator_depends_on_decision_only") is True,
           "orchestrator yalnız karara bağımlı (ADR-001)")
    _check(R, pl.get("media_path") is False, "medya hot-path'i DEĞİL (SAD §20 bütçesi dışı)")
    _check(R, "clonedVoiceConsentRef" in (pl.get("consumed_by_spi") or ""),
           "clonedVoiceConsentRef ile 4.2.3'ten tüketilir (API §11.3)")

    # ── spi
    sp = spec.get("spi", {})
    _check(R, set(sp.get("voice_kinds", [])) == VOICE_KINDS, "voice_kinds {custom, cloned}")
    _check(R, sp.get("consent_required_for") == ["cloned"], "consent yalnız klon ses için (FR-TTS-007)")
    _check(R, sp.get("usable_status") == ["approved"], "yalnız approved kullanılabilir (FR-TTS-006)")
    _check(R, set(sp.get("voice_status", [])) == VOICE_STATUS, "voice_status yaşam döngüsü tam")
    _check(R, set(sp.get("consent_state", [])) == CONSENT_STATE, "consent_state {granted, withdrawn}")
    _check(R, set(sp.get("deny_reasons", [])) == DENY_REASONS, "deny_reasons kataloğu tam")
    _check(R, {"tenants", "agents", "purposes"} == set(sp.get("scope_dimensions", [])),
           "scope_dimensions {tenants, agents, purposes} (FR-TTS-007 kapsam)")
    _check(R, {"consent_id", "voice_id", "subject_ref", "expires_at", "state"}
           <= set(sp.get("consent_record_fields", [])),
           "consent_record alanları (subject_ref/expires_at/state)")
    _check(R, {"usage_id", "voice_id", "consent_id", "used_at"} <= set(sp.get("usage_record_fields", [])),
           "usage_record alanları (FR-TTS-007 kullanım kaydı)")

    # ── kapılar
    g = spec.get("gates", {})
    for k in ("max_unapproved_use", "max_cloned_without_consent", "max_use_after_expiry",
              "max_use_after_revoke", "max_out_of_scope", "max_cross_tenant",
              "max_missing_usage_record", "max_unaudited_event", "max_self_approval",
              "max_mutable_record", "max_pii_in_record"):
        _check(R, g.get(k, -1) == 0, "kapı %s = 0" % k)
    _check(R, g.get("require_usage_record") is True, "P6 require_usage_record (FR-TTS-007)")
    _check(R, g.get("require_audit") is True, "P7 require_audit (FR-IAM-006)")
    _check(R, g.get("require_maker_checker") is True, "P8 require_maker_checker (ADR-012)")
    _check(R, g.get("consent_required_for") == ["cloned"], "kapı consent_required_for = [cloned]")

    # ── metrikler → observability
    me = spec.get("metrics", {})
    emitted = set(me.get("emitted", []))
    _check(R, {"voice_usage_total", "voice_consent_denied_total", "voice_consent_active"} <= emitted,
           "metrikler: usage + denied + active yayılır")
    hc = set(me.get("high_cardinality_forbidden_as_label", []))
    _check(R, {"consent_id", "voice_id", "subject_ref"} <= hc,
           "yüksek-kardinalite kimlikler metrik label OLAMAZ (0.4.7 kardinalite disiplini)")
    _check(R, len(me.get("maps_to_observability", {})) >= 1, "metrik observability'ye eşlenir (0.4.7)")

    # ── error taxonomy
    et = spec.get("error_taxonomy", {})
    mapping = et.get("mapping", {})
    _check(R, len(mapping) >= 5, "hata eşlemesi (≥5)")
    _check(R, all(v in ERROR_TAXONOMY for v in mapping.values()),
           "tüm hedefler API §11.6 ErrorTaxonomy'de")
    _check(R, mapping.get("NO_CONSENT") == "CONTENT_FILTERED"
           and mapping.get("CROSS_TENANT") == "AUTH"
           and mapping.get("region_mismatch") == "REGION_VIOLATION",
           "NO_CONSENT→CONTENT_FILTERED, CROSS_TENANT→AUTH, bölge→REGION_VIOLATION")
    _check(R, set(mapping.keys()) - {"region_mismatch"} <= DENY_REASONS,
           "eşleme anahtarları deny_reasons kataloğunda")

    # ── residency + pii
    rs = spec.get("residency", {})
    _check(R, rs.get("region_pin_required") is True, "residency region pin (NFR 10.7)")
    _check(R, rs.get("no_log_required") is True
           and set(rs.get("allowed_retention", [])) <= ALLOWED_RETENTION,
           "no-log: retention NONE/EPHEMERAL (FR-KB-010)")
    pii = spec.get("pii", {})
    _check(R, pii.get("raw_voiceprint_in_record_forbidden") is True
           and pii.get("biometric_template_in_record_forbidden") is True
           and pii.get("pii_value_in_record_forbidden") is True
           and pii.get("only_opaque_refs") is True,
           "V11 ham voiceprint/biyometrik/PII değeri yasak; yalnız opak ref")
    _check(R, set(spec.get("forbidden_record_keys", [])) == FORBIDDEN_RECORD_KEYS,
           "forbidden_record_keys kataloğu probe ile tutarlı")

    # ── retention
    rt2 = spec.get("retention", {})
    _check(R, "WORM" in (rt2.get("consent_record") or "") or "append-only" in (rt2.get("consent_record") or ""),
           "consent record WORM/append-only (V10)")

    # ── invariant kataloğu
    inv_ids = [i.get("id") for i in spec.get("invariants", [])]
    _check(R, len(inv_ids) == len(set(inv_ids)) and len(inv_ids) >= 12,
           "invariant kataloğu ≥12 + tekil ID")
    _check(R, all(i.get("trace") for i in spec.get("invariants", [])),
           "her invariant trace taşır")

    # ── literal sır taraması
    hits = _scan_secrets(spec)
    if os.path.exists(PROFILES_CFG):
        hits += _scan_secrets(_load(PROFILES_CFG))
    _check(R, not hits, "literal sır yok (spec+config)")

    # ── config profil doğrulaması
    if os.path.exists(PROFILES_CFG):
        cfg = _load(PROFILES_CFG)
        profs = cfg.get("profiles", [])
        _check(R, len(profs) >= 2, "config ≥2 çalıştırma profili")
        names = [p.get("name") for p in profs]
        _check(R, len(names) == len(set(names)), "config profil adları benzersiz")
        for prof in profs:
            _check(R, bool(prof.get("region")), "config %s bölge pini var (NFR 10.7)" % prof.get("name"))
            _check(R, prof.get("consent_record_retention") in ALLOWED_RETENTION,
                   "config %s consent retention NONE/EPHEMERAL" % prof.get("name"))
            _check(R, prof.get("usage_record_retention") in ALLOWED_RETENTION,
                   "config %s usage retention NONE/EPHEMERAL" % prof.get("name"))
            _check(R, prof.get("maker_checker") is True,
                   "config %s maker_checker açık (ADR-012)" % prof.get("name"))
            _check(R, prof.get("tenant_isolation") is True,
                   "config %s tenant_isolation açık (FR-TEN-002)" % prof.get("name"))
            _check(R, prof.get("audit") is True, "config %s audit açık (FR-IAM-006)" % prof.get("name"))
        cd = cfg.get("consent_defaults", {})
        _check(R, cd.get("consent_required_for") == ["cloned"],
               "config consent_defaults consent_required_for = [cloned]")
        _check(R, cfg.get("default_profile") in names, "default_profile geçerli")

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
def _pol(**over):
    pol = _default_policy()
    pol.update(over)
    return pol


def _raises(fn):
    try:
        fn()
        return False
    except VoiceConsentError:
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


# olay kurucuları (selftest)
def _reg(t, vid="v-clone-1", kind="cloned", tenant="t1", by="designer-1"):
    return {"kind": "register_voice", "voice_id": vid, "voice_kind": kind,
            "tenant_id": tenant, "created_by": by, "t": t}


def _grant(t, cid="c1", vid="v-clone-1", tenant="t1", expires=10000,
           scope=None, by="compliance-1"):
    return {"kind": "grant_consent", "consent_id": cid, "voice_id": vid, "tenant_id": tenant,
            "subject_ref": "subj://ref-%s" % cid, "evidence_ref": "ev://ref-%s" % cid,
            "scope": scope or {"tenants": ["t1"], "agents": ["a1"], "purposes": ["collections"]},
            "granted_by": by, "expires_at": expires, "t": t}


def _approve(t, vid="v-clone-1", by="approver-1"):
    return {"kind": "approve_voice", "voice_id": vid, "approved_by": by, "t": t}


def _use(t, uid="u1", vid="v-clone-1", cref="c1", tenant="t1", agent="a1",
         purpose="collections", seconds=12):
    ev = {"kind": "use", "use_id": uid, "voice_id": vid, "tenant_id": tenant,
          "agent_id": agent, "purpose": purpose, "t": t, "seconds": seconds}
    if cref is not None:
        ev["consent_ref"] = cref
    return ev


def selftest():
    spec = _load(SPEC_PATH)
    gates = spec.get("gates", {})
    cases = []

    def case(ok, label):
        cases.append((bool(ok), label))

    # 0) validate iyi spec+config'te geçer
    case(_validate_obj(_load(SPEC_PATH)) == 0, "validate iyi spec+config'te 0 döndürür")

    # ── happy: kayıt → izin → onay(farklı approver) → kapsam içi kullanım → ALLOW + usage record
    mh = simulate({"events": [
        _reg(0), _grant(10), _approve(20),
        _use(100, uid="u1"), _use(200, uid="u2"),
    ]}, _pol())
    case(mh["allow_total"] == 2 and mh["deny_total"] == 0, "happy: kapsam içi 2 kullanım → ALLOW")
    case(mh["usage_records"] == 2 and mh["missing_usage_record"] == 0,
         "happy: her klon kullanımı bir usage record (P6/V7)")
    case(mh["unaudited_event"] == 0 and mh["audit_events"] == mh["expected_audit"],
         "happy: tüm olay + karar denetlendi (P7/V8)")
    case(all(ok for ok, _ in evaluate(gates, mh)), "happy tüm kapıları geçer (P1–P8)")

    # ── custom ses: izin gerekmez, onaylıysa kullanılabilir
    mc = simulate({"events": [
        _reg(0, vid="v-cust-1", kind="custom"), _approve(10, vid="v-cust-1"),
        _use(100, uid="u1", vid="v-cust-1", cref=None, purpose="support", agent="a9"),
    ]}, _pol())
    case(mc["allow_total"] == 1 and mc["usage_records"] == 0,
         "custom: onaylı özel ses izinsiz kullanılır, usage record klon-özel (FR-TTS-006)")
    case(all(ok for ok, _ in evaluate(gates, mc)), "custom tüm kapıları geçer")

    # ── determinizm
    ev = [_reg(0), _grant(10), _approve(20), _use(100)]
    case(simulate({"events": ev}, _pol()) == simulate({"events": ev}, _pol()),
         "determinizm: aynı olay-akışı birebir aynı metrik (random yok)")

    # ── DENY: onaysız ses (V1)
    m1 = simulate({"events": [_reg(0), _grant(10), _use(100)]}, _pol())  # onay yok
    case(m1["deny_total"] == 1 and m1["deny_by_reason"].get("NOT_APPROVED") == 1,
         "DENY: onaysız ses → NOT_APPROVED (V1)")
    case(m1["unapproved_use_allowed"] == 0 and all(ok for ok, _ in evaluate(gates, m1)),
         "onaysız ses DENY edildi → P1 geçer (uygunsuz allow yok)")

    # ── DENY: klon izinsiz (V2)
    m2 = simulate({"events": [_reg(0), _approve(20), _use(100, cref=None)]}, _pol())
    case(m2["deny_by_reason"].get("NO_CONSENT") == 1, "DENY: klon izinsiz → NO_CONSENT (V2)")
    case(all(ok for ok, _ in evaluate(gates, m2)), "klon izinsiz DENY → P2 geçer")

    # ── DENY: süre dolumu (V3) + geri çekme (V4)
    m3 = simulate({"events": [
        _reg(0), _grant(10, expires=150), _approve(20),
        _use(100, uid="u1"),     # geçerli
        _use(200, uid="u2"),     # süre dolmuş (t>150)
        _revoke(250),            # geri çek
        _use(300, uid="u3"),     # geri çekilmiş
    ]}, _pol())
    case(m3["deny_by_reason"].get("CONSENT_EXPIRED") == 1, "DENY: süre dolmuş izin → CONSENT_EXPIRED (V3)")
    case(m3["deny_by_reason"].get("CONSENT_WITHDRAWN") == 1, "DENY: geri çekilmiş izin → CONSENT_WITHDRAWN (V4)")
    case(m3["allow_total"] == 1 and m3["use_after_expiry"] == 0 and m3["use_after_revoke"] == 0
         and all(ok for ok, _ in evaluate(gates, m3)), "süre/iptal zorlandı → P3 geçer")

    # ── DENY: kapsam dışı (V5) — agent + purpose
    m4 = simulate({"events": [
        _reg(0), _grant(10), _approve(20),
        _use(100, uid="u1", agent="a2"),                 # kapsam dışı agent
        _use(200, uid="u2", purpose="marketing"),        # kapsam dışı purpose
    ]}, _pol())
    case(m4["deny_by_reason"].get("OUT_OF_SCOPE") == 2 and m4["out_of_scope_allowed"] == 0,
         "DENY: kapsam dışı agent/purpose → OUT_OF_SCOPE (V5)")
    case(all(ok for ok, _ in evaluate(gates, m4)), "kapsam zorlandı → P4 geçer")

    # ── DENY: cross-tenant (V6) — ses t1, kullanım t2
    m5 = simulate({"events": [
        _reg(0), _grant(10), _approve(20),
        _use(100, uid="u1", tenant="t2"),
    ]}, _pol())
    case(m5["deny_by_reason"].get("CROSS_TENANT") == 1 and m5["cross_tenant_allowed"] == 0,
         "DENY: başka tenant'tan kullanım → CROSS_TENANT (V6)")
    case(all(ok for ok, _ in evaluate(gates, m5)), "tenant izolasyonu zorlandı → P5 geçer")

    # ── wildcard kapsam geçer
    mw = simulate({"events": [
        _reg(0), _grant(10, scope={"tenants": ["t1"], "agents": ["*"], "purposes": ["*"]}), _approve(20),
        _use(100, uid="u1", agent="a-any", purpose="any"),
    ]}, _pol())
    case(mw["allow_total"] == 1 and all(ok for ok, _ in evaluate(gates, mw)),
         "wildcard kapsam (agents:*, purposes:*) → ALLOW")

    # ── DEGRADED: enforce_approval kapalı → onaysız ses kullanıldı (P1 eler)
    dg1 = simulate({"events": [_reg(0), _grant(10), _use(100)]},
                   _pol(enforce_approval=False))
    case(dg1["unapproved_use_allowed"] >= 1 and not all(ok for ok, _ in evaluate(gates, dg1)),
         "degraded(no-approval): onaysız ses kullanıldı → P1 eler (FR-TTS-006)")

    # ── DEGRADED: require_consent_for_cloned kapalı → izinsiz klon (P2 eler)
    dg2 = simulate({"events": [_reg(0), _approve(20), _use(100, cref=None)]},
                   _pol(require_consent_for_cloned=False))
    case(dg2["cloned_without_consent_allowed"] >= 1 and not all(ok for ok, _ in evaluate(gates, dg2)),
         "degraded(no-consent-enf): izinsiz klon ses → P2 eler (FR-TTS-007)")

    # ── DEGRADED: honor_expiry/revocation kapalı → süre sonrası/iptal sonrası kullanım (P3 eler)
    dg3 = simulate({"events": [
        _reg(0), _grant(10, expires=150), _approve(20),
        _use(200, uid="u1"),               # süre dolmuş ama izin verildi
        _revoke(250), _use(300, uid="u2"),  # iptal sonrası ama izin verildi
    ]}, _pol(honor_expiry=False, honor_revocation=False))
    case(dg3["use_after_expiry"] >= 1 and dg3["use_after_revoke"] >= 1
         and not all(ok for ok, _ in evaluate(gates, dg3)),
         "degraded(no-expiry/revoke): süre/iptal sonrası kullanım → P3 eler")

    # ── DEGRADED: enforce_scope kapalı → kapsam dışı kullanım (P4 eler)
    dg4 = simulate({"events": [_reg(0), _grant(10), _approve(20), _use(100, purpose="marketing")]},
                   _pol(enforce_scope=False))
    case(dg4["out_of_scope_allowed"] >= 1 and not all(ok for ok, _ in evaluate(gates, dg4)),
         "degraded(no-scope): kapsam dışı kullanım → P4 eler")

    # ── DEGRADED: tenant_isolation kapalı → cross-tenant (P5 eler)
    dg5 = simulate({"events": [_reg(0), _grant(10), _approve(20), _use(100, tenant="t2")]},
                   _pol(tenant_isolation=False))
    case(dg5["cross_tenant_allowed"] >= 1 and not all(ok for ok, _ in evaluate(gates, dg5)),
         "degraded(no-isolation): cross-tenant kullanım → P5 eler (FR-TEN-002)")

    # ── DEGRADED: emit_usage_record kapalı → kullanım kaydı eksik (P6 eler)
    dg6 = simulate({"events": [_reg(0), _grant(10), _approve(20), _use(100)]},
                   _pol(emit_usage_record=False))
    case(dg6["missing_usage_record"] >= 1 and not all(ok for ok, _ in evaluate(gates, dg6)),
         "degraded(no-usage-record): izin verildi ama kayıt yok → P6 eler (FR-TTS-007)")

    # ── DEGRADED: audit kapalı → denetlenmemiş olay (P7 eler)
    dg7 = simulate({"events": [_reg(0), _grant(10), _approve(20), _use(100)]},
                   _pol(audit=False))
    case(dg7["unaudited_event"] >= 1 and not all(ok for ok, _ in evaluate(gates, dg7)),
         "degraded(no-audit): yaşam döngüsü/karar denetlenmedi → P7 eler (FR-IAM-006)")

    # ── DEGRADED: maker_checker kapalı + self-approval → P8 eler
    dg8 = simulate({"events": [_reg(0, by="designer-1"), _grant(10),
                               _approve(20, by="designer-1"), _use(100)]},
                   _pol(maker_checker=False))
    case(dg8["self_approval"] >= 1 and not all(ok for ok, _ in evaluate(gates, dg8)),
         "degraded(self-approval): onaylayan=oluşturan → P8 eler (V9)")

    # ── DEGRADED: WORM kapalı + mutate_record → P8 eler
    dg9 = simulate({"events": [_reg(0), _grant(10), _approve(20),
                               {"kind": "mutate_record", "target": "consent", "ref": "c1", "t": 50},
                               _use(100)]},
                   _pol(worm=False))
    case(dg9["mutable_records"] >= 1 and not all(ok for ok, _ in evaluate(gates, dg9)),
         "degraded(no-worm): consent kaydı mutasyonu → P8 eler (V10)")

    # ── DEGRADED: PII/voiceprint kayıtta → P8 eler
    dgp = simulate({"events": [_reg(0), _grant(10), _approve(20),
                               {"kind": "use", "use_id": "u1", "voice_id": "v-clone-1", "consent_ref": "c1",
                                "tenant_id": "t1", "agent_id": "a1", "purpose": "collections", "t": 100,
                                "voiceprint": "FORBIDDEN"}]},
                   _pol())
    case(dgp["pii_in_record"] >= 1 and not all(ok for ok, _ in evaluate(gates, dgp)),
         "degraded(pii): kayıtta voiceprint/biyometrik → P8 eler (V11)")

    # ── maker-checker normalde self-approval'ı REDDEDER (raise)
    case(_raises(lambda: simulate({"events": [_reg(0, by="x"), _approve(20, by="x")]}, _pol())),
         "maker-checker açık: self-approval reddedilir (raise)")

    # ── WORM normalde mutasyonu REDDEDER (raise)
    case(_raises(lambda: simulate({"events": [_reg(0), _grant(10),
                                              {"kind": "mutate_record", "target": "consent", "ref": "c1", "t": 50}]},
                                  _pol())),
         "WORM açık: kayıt mutasyonu reddedilir (raise)")

    # ── geçersiz olay / yapısal red (bilinmeyen voice → DENY UNKNOWN_VOICE, raise değil)
    mu = simulate({"events": [_use(0, vid="nope")]}, _pol())
    case(mu["deny_by_reason"].get("UNKNOWN_VOICE") == 1, "bilinmeyen voice → UNKNOWN_VOICE DENY")
    case(_raises(lambda: simulate({"events": [_reg(0), _reg(0)]}, _pol())),
         "tekrar voice kaydı → reddedilir")
    case(_raises(lambda: simulate({"events": [_reg(0), _grant(10, cid="c1"), _grant(20, cid="c1")]}, _pol())),
         "tekrar consent_id (WORM) → reddedilir")
    case(_raises(lambda: simulate({"events": [_reg(0), {"kind": "grant_consent", "consent_id": "c1",
                                                        "voice_id": "v-clone-1", "tenant_id": "t1",
                                                        "scope": {}, "t": 10}]}, _pol())),
         "subject_ref/evidence_ref yok → reddedilir (V11)")
    case(_raises(lambda: simulate({"events": [{"kind": "register_voice", "voice_id": "v", "voice_kind": "deepfake",
                                               "tenant_id": "t1", "t": 0}]}, _pol())),
         "geçersiz voice_kind → reddedilir")
    case(_raises(lambda: simulate({"events": [_reg(1000), _grant(0)]}, _pol())),
         "out-of-order olay → reddedilir")
    case(_raises(lambda: simulate({"events": [{"kind": "nope", "t": 0}]}, _pol())),
         "bilinmeyen olay tipi → reddedilir")
    case(_raises(lambda: simulate({"events": []}, _pol())), "boş olay akışı → reddedilir")

    # ── validate negatif kapılar
    s = json.loads(json.dumps(spec)); s["gates"]["max_cloned_without_consent"] = 1
    case(_validate_obj(s) != 0, "P2 max_cloned_without_consent>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_use_after_revoke"] = 1
    case(_validate_obj(s) != 0, "P3 max_use_after_revoke>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_cross_tenant"] = 1
    case(_validate_obj(s) != 0, "P5 max_cross_tenant>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["require_usage_record"] = False
    case(_validate_obj(s) != 0, "P6 require_usage_record=false → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["require_audit"] = False
    case(_validate_obj(s) != 0, "P7 require_audit=false → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["require_maker_checker"] = False
    case(_validate_obj(s) != 0, "P8 require_maker_checker=false → validate eler")
    s = json.loads(json.dumps(spec)); s["spi"]["consent_required_for"] = []
    case(_validate_obj(s) != 0, "consent_required_for≠[cloned] → validate eler")
    s = json.loads(json.dumps(spec)); s["spi"]["usable_status"] = ["pending"]
    case(_validate_obj(s) != 0, "usable_status≠[approved] → validate eler")
    s = json.loads(json.dumps(spec)); s["pii"]["pii_value_in_record_forbidden"] = False
    case(_validate_obj(s) != 0, "P8 PII-değer-yasak kapalı → validate eler")
    s = json.loads(json.dumps(spec)); s["error_taxonomy"]["mapping"]["NO_CONSENT"] = "NOPE"
    case(_validate_obj(s) != 0, "taksonomi-dışı eşleme → validate eler")
    s = json.loads(json.dumps(spec)); s["residency"]["allowed_retention"] = ["PROVIDER_DEFAULT"]
    case(_validate_obj(s) != 0, "no-log dışı retention → validate eler")
    s = json.loads(json.dumps(spec)); s["metrics"]["secret"] = "api_key: AKIAIOSFODNN7EXAMPLE"
    case(_validate_obj(s) != 0, "literal secret → validate eler")

    passed = sum(1 for ok, _ in cases if ok)
    total = len(cases)
    for ok, label in cases:
        print("  %s %s" % ("✓" if ok else "✗", label))
    print("selftest: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


def _revoke(t, cid="c1"):
    return {"kind": "revoke_consent", "consent_id": cid, "t": t}


def schema():
    print("""voice-consent-spec.json beklenen şekli (WBS 4.2.6):
  wbs, version, phase, trace{fr[FR-TTS-006/007,FR-TEN-002,FR-IAM-006,...], nfr, sad, adr, api, srs, rtm,
       brd, threat_model, dpia, consumes, consumed_by, observability}
  placement{consulted_before_synthesis=true, orchestrator_depends_on_decision_only=true,
            media_path=false, consumed_by_spi(clonedVoiceConsentRef → 4.2.3)}
  spi{decision(resolveVoiceUse), lifecycle_methods[register/grant/approve/revoke/suspend],
      voice_kinds[custom,cloned], consent_required_for[cloned], usable_status[approved],
      voice_status[draft,pending,approved,suspended,revoked], consent_state[granted,withdrawn],
      deny_reasons[...], consent_record_fields[...], usage_record_fields[...],
      scope_dimensions[tenants,agents,purposes], scope_wildcard}
  gates{max_unapproved_use=0, max_cloned_without_consent=0, max_use_after_expiry=0,
        max_use_after_revoke=0, max_out_of_scope=0, max_cross_tenant=0, require_usage_record=true,
        max_missing_usage_record=0, require_audit=true, max_unaudited_event=0,
        require_maker_checker=true, max_self_approval=0, max_mutable_record=0, max_pii_in_record=0,
        consent_required_for[cloned]}                                                       (P1-P8)
  metrics{emitted[], high_cardinality_forbidden_as_label[consent_id,voice_id,subject_ref,...],
          maps_to_observability{}}
  error_taxonomy{mapping(deny_reason → API §11.6)}
  residency{region_pin_required=true, no_log_required=true, allowed_retention[NONE,EPHEMERAL]}
  retention{consent_record(WORM/append-only), usage_record(no-loss)}
  pii{raw_voiceprint/biometric_template/pii_value_in_record_forbidden=true, only_opaque_refs=true}
  forbidden_record_keys[voiceprint,raw_audio,biometric_template,pii_value,voice_sample_b64]
  invariants[≥12 V1..V12]{id, desc, trace}

config/voice-consent-profiles.json: default_profile, consent_defaults{consent_required_for[cloned],
  maker_checker, scope_dimensions, scope_wildcard, default_consent_ttl_days};
  profiles[]{name, region, consent_record_retention(NONE/EPHEMERAL), usage_record_retention,
  maker_checker=true, tenant_isolation=true, audit=true}; evidence_store(${ENV})

simulate sample: {name, expect, expected?{metrik:değer}, policy?{enforce_approval,
  require_consent_for_cloned, honor_expiry, honor_revocation, enforce_scope, tenant_isolation,
  emit_usage_record, audit, maker_checker, worm, consent_required_for},
  events[
    {kind:'register_voice', voice_id, voice_kind, tenant_id, created_by, t} |
    {kind:'grant_consent', consent_id, voice_id, subject_ref, evidence_ref, tenant_id, scope, expires_at, granted_by, t} |
    {kind:'approve_voice', voice_id, approved_by, t} |
    {kind:'revoke_consent', consent_id, t} | {kind:'suspend_voice'|'revoke_voice', voice_id, t} |
    {kind:'use', use_id, voice_id, consent_ref?, tenant_id, agent_id, purpose, seconds?, call_ref?, t} |
    {kind:'mutate_record', target, ref, t}  (WORM → reddedilir)]}

komutlar: validate | simulate <sample.json> | selftest | schema""")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if cmd == "validate":
        return validate()
    if cmd == "simulate":
        if len(sys.argv) < 3:
            print("kullanım: voice_consent_probe.py simulate <sample.json>")
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
