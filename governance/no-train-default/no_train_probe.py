#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
no_train_probe.py — WBS 5.8 "Tenant verisi eğitime kapalı" varsayılanı (no-train)

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only statik + davranış kapısı. `governance/`,
`adapters/` ve `runtime/` modül disipliniyle aynı; burada PLATFORM-GENELİ no-train VARSAYILAN
yönetişim kapısını DETERMİNİSTİK bir karar motoru ile modeller (olay-tetikli, sanal saat, random
YOK; gerçek prompt/transkript/audio YOK — yalnız kayıt defteri durumu + opak referanslar).

GÖREV (FR-LLM-012): tenant verisi bir LLM/STT/TTS sağlayıcısına gönderilmeden ÖNCE, modelin
EĞİTİMİNDE kullanılmasına karşı VARSAYILAN OLARAK kapalıdır (noTrain=true, fail-closed). Bu varsayılan
SESSİZCE gevşetilemez; yalnız AÇIK + maker-checker'lı + denetimli + süreli bir governed training opt-in
(compliance profile izin veriyorsa) eğitime açar — regüle/yasaklı profilde opt-in EZİLİR
(most-restrictive-wins; tenant override yalnız-sıkılaştırır). Ek olarak sağlayıcının no-train YETENEĞİ +
no-log retention (NONE/EPHEMERAL) + bölgesel pin + imzalı DPA doğrulanır; karşılamayan sağlayıcıya
tenant verisi GÖNDERİLMEZ (DENY).

resolveTrainingDisposition() adapter (4.2.4/4.2.x) çağrısı ÖNCESİ no_train değerini + sağlayıcı
uygunluğunu çözer; adapter bu kararı UYGULAR (ADR-001; orchestrator yalnız karara bağımlı). Kayıtlar
WORM/append-only (T10), home-region (residency), tenant-izole (T8); ham prompt/transkript/audio/PII
DEĞERİ saklanmaz (T12).

KAPSAM AYRIMI: gerçek sağlayıcı çağrısında no_train UYGULAMASI → 4.2.4 LlmAdapter (P6) + STT/TTS
adapter; residency/retention zorlama motoru → 4.1.4/1.2.2; alt-işleyen/DPA sözleşme listesi →
0.2.6 contract-dpa-checklist (Ek-A); compliance profile cp.* çözümleme → DPIA; audit_log fiziksel
şeması → 1.1.4; sağlayıcı SEÇİMİ → 0.2.6/0.3.x (vendor-neutral). Burada YALNIZ no-train VARSAYILAN
DISPOSITION + sağlayıcı uygunluk kararı.

Komutlar:
  validate              no-train-spec.json'ı invariant'lara (T1–T12) + config profillerine doğrular.
  simulate <sample>     Deterministik karar motoru — yaşam döngüsü + use olay-akışı → ALLOW/DENY +
                        effective no_train + audit → HARD kapılar (P1–P8) → çıkış kodu.
  selftest              İyi/kötü spec+sample ile kapıların doğru tetiklendiğini kanıtlar.
  schema                Beklenen spec şeklini özetler.

Sunucu/credential GEREKMEZ. Ham PROMPT/transkript/audio veya PII DEĞERİ YOK — yalnız sağlayıcı/opt-in
kimlikleri + opak referanslar + kapsam + sanal zaman.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "no-train-spec.json")
PROFILES_CFG = os.path.join(HERE, "config", "no-train-profiles.json")

ERROR_TAXONOMY = {
    "TIMEOUT", "RATE_LIMITED", "UNAVAILABLE", "AUTH",
    "INVALID_REQUEST", "CONTENT_FILTERED", "QUOTA_EXCEEDED", "REGION_VIOLATION",
}
SECRET_RE = re.compile(
    r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer)\b\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}"
)
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")

PROVIDER_CATEGORIES = {"llm", "stt", "tts"}
DATA_CLASSES = {"prompt", "transcript", "kb_content", "audio"}
OPT_IN_STATE = {"granted", "withdrawn"}
DENY_REASONS = {
    "UNKNOWN_PROVIDER", "PROVIDER_NOT_NO_TRAIN", "PROVIDER_LOGS_DATA",
    "PROVIDER_NO_DPA", "REGION_VIOLATION",
}
FORBIDDEN_RECORD_KEYS = {"raw_prompt", "raw_transcript", "raw_audio", "pii_value", "prompt_text", "message_text"}
ALLOWED_RETENTION = {"NONE", "EPHEMERAL"}
LIFECYCLE_KINDS = {"register_provider", "bind_profile", "grant_opt_in",
                   "revoke_opt_in", "set_override"}


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_placeholder(v):
    return isinstance(v, str) and PLACEHOLDER_RE.match(v) is not None


class NoTrainError(Exception):
    """Yapısal hata / yetki / WORM / sessiz-gevşetme ihlali — sessizce kabul yok, reddet."""


# ─────────────────────────────────────────────────────────────────────────────
# No-train varsayılan disposition karar motoru (deterministik)
# ─────────────────────────────────────────────────────────────────────────────
class NoTrainRegistry:
    """Yaşam döngüsü olaylarından kayıt defteri durumu kurar, her 'use' (sağlayıcıya gönderim)
    olayını ALLOW/DENY + effective_no_train'e DETERMİNİSTİK karar bağlar (random YOK;
    sanal saat = event.t). VARSAYILAN no_train=true; eğitim YALNIZ geçerli governed opt-in +
    izinli profil + uygun sağlayıcı ile açılır.

    Olaylar:
      {kind:'register_provider', provider_id, category∈{llm,stt,tts}, no_train_capable,
                                 allowed_retention[..], region_pin_capable, regions[..], dpa_signed,
                                 subprocessor_ref?, t}
      {kind:'bind_profile', tenant_id, profile, region, requires_no_train, forbid_training_opt_in, t}
      {kind:'grant_opt_in', opt_in_id, tenant_id, data_class, scope{tenants,data_classes},
                            evidence_ref, granted_by, approved_by, expires_at, t}
      {kind:'revoke_opt_in', opt_in_id, t}
      {kind:'set_override', tenant_id, no_train(bool), reason?, t}   # loosening (false) reddedilir
      {kind:'use', use_id, tenant_id, provider_id, data_class, opt_in_ref?, t, call_ref?}
      {kind:'mutate_record', target∈{opt_in,provider}, ref, t}   # WORM: reddedilmeli (T10)
    """

    def __init__(self, policy):
        self.pol = policy
        self.providers = {}     # provider_id -> {...}
        self.profiles = {}      # tenant_id -> {region, requires_no_train, forbid_training_opt_in}
        self.opt_ins = {}       # opt_in_id -> {tenant_id, data_class, scope, expires_at, state}
        self.overrides = {}     # tenant_id -> {"no_train": bool}  (yalnız-sıkılaştırır)
        self._last_t = None

        self.audit_events = 0
        self.expected_audit = 0

        # sayaçlar / kapı metrikleri
        self.use_total = 0
        self.no_train_uses = 0          # effective_no_train=true (varsayılan; beklenen yol)
        self.training_enabled_uses = 0  # effective_no_train=false (governed, meşru opt-in)
        self.deny_total = 0
        self.deny_by_reason = {}
        self.opt_ins_active = 0

        # ihlal sayaçları (yalnız POLİTİKA gevşetildiğinde >0 olur)
        self.train_without_optin = 0
        self.loosening_override = 0
        self.non_no_train_provider = 0
        self.logging_provider = 0
        self.no_dpa_provider = 0
        self.region_violation = 0
        self.training_after_expiry = 0
        self.training_after_revoke = 0
        self.out_of_scope_training = 0
        self.cross_tenant_training = 0
        self.forbidden_profile_training = 0
        self.self_approval = 0
        self.mutable_records = 0
        self.pii_in_record = 0

    # ── yardımcılar ───────────────────────────────────────────────────────────
    def _check_time(self, t):
        if not isinstance(t, (int, float)):
            raise NoTrainError("zaman damgası sayısal değil → INVALID_REQUEST")
        if self._last_t is not None and t < self._last_t:
            if self.pol.get("order_guard", True):
                raise NoTrainError("out-of-order olay (t geriye) reddedildi → INVALID_REQUEST")
        self._last_t = max(self._last_t if self._last_t is not None else t, t)

    def _scan_pii(self, ev):
        for k in ev.keys():
            if k in FORBIDDEN_RECORD_KEYS:
                self.pii_in_record += 1

    def _audit(self):
        self.expected_audit += 1
        if self.pol.get("audit", True):
            self.audit_events += 1

    def _profile(self, tenant):
        # bağlı profil yoksa PLATFORM varsayılanı: no-train zorunlu, opt-in yasak (fail-closed)
        return self.profiles.get(tenant, {
            "region": None, "requires_no_train": True, "forbid_training_opt_in": True,
        })

    # ── yaşam döngüsü ───────────────────────────────────────────────────────────
    def register_provider(self, ev):
        self._check_time(ev.get("t"))
        self._scan_pii(ev)
        pid = ev.get("provider_id")
        if not isinstance(pid, str) or not pid:
            raise NoTrainError("provider_id yok/boş → INVALID_REQUEST")
        if pid in self.providers:
            raise NoTrainError("provider_id tekrar kayıt → INVALID_REQUEST")
        cat = ev.get("category")
        if cat not in PROVIDER_CATEGORIES:
            raise NoTrainError("geçersiz category: %r → INVALID_REQUEST" % cat)
        ret = ev.get("allowed_retention", [])
        if not isinstance(ret, list):
            raise NoTrainError("allowed_retention liste değil → INVALID_REQUEST")
        self.providers[pid] = {
            "category": cat,
            "no_train_capable": bool(ev.get("no_train_capable", False)),
            "allowed_retention": ret,
            "region_pin_capable": bool(ev.get("region_pin_capable", False)),
            "regions": ev.get("regions", []),
            "dpa_signed": bool(ev.get("dpa_signed", False)),
            "subprocessor_ref": ev.get("subprocessor_ref"),
        }
        self._audit()

    def bind_profile(self, ev):
        self._check_time(ev.get("t"))
        tenant = ev.get("tenant_id")
        if not isinstance(tenant, str) or not tenant:
            raise NoTrainError("tenant_id yok/boş → INVALID_REQUEST")
        self.profiles[tenant] = {
            "region": ev.get("region"),
            "requires_no_train": bool(ev.get("requires_no_train", True)),
            "forbid_training_opt_in": bool(ev.get("forbid_training_opt_in", False)),
            "profile": ev.get("profile"),
        }
        self._audit()

    def grant_opt_in(self, ev):
        self._check_time(ev.get("t"))
        self._scan_pii(ev)
        oid = ev.get("opt_in_id")
        if not isinstance(oid, str) or not oid:
            raise NoTrainError("opt_in_id yok/boş → INVALID_REQUEST")
        if oid in self.opt_ins:
            raise NoTrainError("opt_in_id tekrar kullanıldı (WORM) → INVALID_REQUEST")
        tenant = ev.get("tenant_id")
        if not isinstance(tenant, str) or not tenant:
            raise NoTrainError("opt-in tenant_id yok/boş → INVALID_REQUEST")
        dc = ev.get("data_class")
        if dc not in DATA_CLASSES:
            raise NoTrainError("geçersiz data_class: %r → INVALID_REQUEST" % dc)
        # AÇIK governed opt-in: maker-checker + opak evidence_ref zorunlu (T4)
        granted_by = ev.get("granted_by")
        approved_by = ev.get("approved_by")
        if not granted_by or not approved_by:
            raise NoTrainError("granted_by + approved_by zorunlu (maker-checker) → INVALID_REQUEST")
        if not ev.get("evidence_ref"):
            raise NoTrainError("evidence_ref (opak) zorunlu → INVALID_REQUEST")
        if approved_by == granted_by:
            if self.pol.get("maker_checker", True):
                raise NoTrainError("opt-in self-approval reddedildi (maker-checker) → AUTH")
            self.self_approval += 1
        scope = ev.get("scope", {})
        if not isinstance(scope, dict):
            raise NoTrainError("scope sözlük değil → INVALID_REQUEST")
        self.opt_ins[oid] = {
            "tenant_id": tenant, "data_class": dc, "scope": scope,
            "expires_at": ev.get("expires_at"), "state": "granted",
        }
        self.opt_ins_active += 1
        self._audit()

    def revoke_opt_in(self, ev):
        self._check_time(ev.get("t"))
        oid = ev.get("opt_in_id")
        o = self.opt_ins.get(oid)
        if o is None:
            raise NoTrainError("bilinmeyen opt_in_id revoke → INVALID_REQUEST")
        o["state"] = "withdrawn"     # WORM: yeni DURUM, mutasyon değil
        o["withdrawn_at"] = ev.get("t")
        if self.opt_ins_active > 0:
            self.opt_ins_active -= 1
        self._audit()

    def set_override(self, ev):
        # T3: override yalnız-sıkılaştırır. no_train=true (tightening) kabul; false (loosening) reddedilir.
        self._check_time(ev.get("t"))
        tenant = ev.get("tenant_id")
        if not isinstance(tenant, str) or not tenant:
            raise NoTrainError("override tenant_id yok/boş → INVALID_REQUEST")
        nt = ev.get("no_train")
        if nt is True:
            self.overrides[tenant] = {"no_train": True}   # sıkılaştırma: her zaman no-train
            self._audit()
            return
        if nt is False:
            if self.pol.get("reject_loosening_override", True):
                raise NoTrainError("no-train gevşeten override reddedildi (yalnız-sıkılaştırır) → AUTH")
            self.overrides[tenant] = {"no_train": False}
            self.loosening_override += 1
            self._audit()
            return
        raise NoTrainError("override no_train bool değil → INVALID_REQUEST")

    def mutate_record(self, ev):
        # T10: WORM — opt-in/provider kaydı mutasyonu reddedilir
        self._check_time(ev.get("t"))
        if self.pol.get("worm", True):
            raise NoTrainError("WORM kayıt mutasyonu reddedildi → INVALID_REQUEST")
        self.mutable_records += 1
        self._audit()

    # ── karar: resolveTrainingDisposition (T1–T12) ──────────────────────────────
    def use(self, ev):
        self._check_time(ev.get("t"))
        self._scan_pii(ev)
        use_id = ev.get("use_id")
        if not isinstance(use_id, str) or not use_id:
            raise NoTrainError("use_id yok/boş → INVALID_REQUEST")
        tenant = ev.get("tenant_id")
        if not isinstance(tenant, str) or not tenant:
            raise NoTrainError("use.tenant_id yok/boş → INVALID_REQUEST")
        dc = ev.get("data_class")
        if dc not in DATA_CLASSES:
            raise NoTrainError("use.data_class geçersiz: %r → INVALID_REQUEST" % dc)
        self.use_total += 1

        decision, reason, eff_no_train = self._decide(ev, tenant, dc)

        if decision == "ALLOW":
            if eff_no_train:
                self.no_train_uses += 1
            else:
                self.training_enabled_uses += 1
        else:
            self.deny_total += 1
            self.deny_by_reason[reason] = self.deny_by_reason.get(reason, 0) + 1
        self._audit()
        return decision, reason, eff_no_train

    def _decide(self, ev, tenant, dc):
        pid = ev.get("provider_id")
        p = self.providers.get(pid)
        if p is None:
            return "DENY", "UNKNOWN_PROVIDER", True
        prof = self._profile(tenant)

        # ── T2: sağlayıcı no-train YETENEKLİ + no-log retention (NONE/EPHEMERAL)
        if self.pol.get("require_no_train_capable_provider", True):
            if not p["no_train_capable"]:
                return "DENY", "PROVIDER_NOT_NO_TRAIN", True
            ret = set(p["allowed_retention"])
            if not ret or not ret <= ALLOWED_RETENTION:
                return "DENY", "PROVIDER_LOGS_DATA", True
        else:
            if not p["no_train_capable"]:
                self.non_no_train_provider += 1
            ret = set(p["allowed_retention"])
            if not ret or not ret <= ALLOWED_RETENTION:
                self.logging_provider += 1

        # ── T11: alt-işleyen/DPA
        if self.pol.get("require_dpa", True):
            if not p["dpa_signed"]:
                return "DENY", "PROVIDER_NO_DPA", True
        elif not p["dpa_signed"]:
            self.no_dpa_provider += 1

        # ── NFR 10.7: bölgesel pin (sağlayıcı home-region'a hizmet etmeli)
        home = prof.get("region")
        if home is not None and home not in (p.get("regions") or []):
            if self.pol.get("region_pin", True):
                return "DENY", "REGION_VIOLATION", True
            self.region_violation += 1

        # ── effective no_train çözümü (VARSAYILAN = true)
        # tenant tightening override → her zaman no-train (override yalnız-sıkılaştırır, T3)
        ov = self.overrides.get(tenant)
        if ov is not None and ov.get("no_train") is True:
            return "ALLOW", None, True
        loosened = ov is not None and ov.get("no_train") is False  # yalnız degraded'da olur

        ref = ev.get("opt_in_ref")
        if not ref:
            # opt-in YOK → varsayılan no-train (en sık yol)
            if loosened:
                self.loosening_override += 1
                return "ALLOW", None, False
            if self.pol.get("enforce_no_train_default", True):
                return "ALLOW", None, True
            # degraded: varsayılan zorlanmıyor → opt-in'siz eğitim açıldı
            self.train_without_optin += 1
            return "ALLOW", None, False

        # opt_in_ref taşıyor → AÇIK governed opt-in çözümü
        o = self.opt_ins.get(ref)
        if o is None:
            # bilinmeyen ref → güvenli varsayılana düş (eğitim açılmaz)
            return "ALLOW", None, True

        status = self._classify_opt_in(o, tenant, dc, ev.get("t"))

        if status == "valid":
            if prof.get("forbid_training_opt_in"):
                if self.pol.get("enforce_profile_restriction", True):
                    return "ALLOW", None, True       # most-restrictive: profil ezer (doğru)
                self.forbidden_profile_training += 1
                return "ALLOW", None, False
            return "ALLOW", None, False              # meşru governed eğitim
        if status == "expired":
            if self.pol.get("honor_expiry", True):
                return "ALLOW", None, True
            self.training_after_expiry += 1
            return "ALLOW", None, False
        if status == "revoked":
            if self.pol.get("honor_revocation", True):
                return "ALLOW", None, True
            self.training_after_revoke += 1
            return "ALLOW", None, False
        if status == "out_of_scope":
            if self.pol.get("enforce_scope", True):
                return "ALLOW", None, True
            self.out_of_scope_training += 1
            return "ALLOW", None, False
        if status == "cross_tenant":
            if self.pol.get("tenant_isolation", True):
                return "ALLOW", None, True
            self.cross_tenant_training += 1
            return "ALLOW", None, False
        return "ALLOW", None, True

    def _classify_opt_in(self, o, tenant, dc, t):
        # tenant izolasyonu önce (T8)
        if o["tenant_id"] != tenant:
            return "cross_tenant"
        if o["state"] == "withdrawn":
            return "revoked"
        exp = o.get("expires_at")
        if exp is not None and isinstance(t, (int, float)) and t > exp:
            return "expired"
        if not self._in_scope(o.get("scope", {}), tenant, dc):
            return "out_of_scope"
        return "valid"

    def _in_scope(self, scope, tenant, dc):
        wc = "*"
        def covered(dim, val):
            allowed = scope.get(dim)
            if allowed is None:
                return False  # belirtilmemiş dimension → kapsam dışı (fail-closed)
            return wc in allowed or val in allowed
        return covered("tenants", tenant) and covered("data_classes", dc)

    def metrics(self):
        scenario = []
        if self.no_train_uses:
            scenario.append("no-train")
        if self.training_enabled_uses:
            scenario.append("governed-opt-in")
        if self.deny_total:
            scenario.append("deny:" + "+".join(sorted(self.deny_by_reason)))
        if (self.train_without_optin or self.loosening_override or self.non_no_train_provider
                or self.logging_provider or self.no_dpa_provider or self.training_after_expiry
                or self.training_after_revoke or self.out_of_scope_training
                or self.cross_tenant_training or self.forbidden_profile_training
                or self.region_violation):
            scenario.append("improper-train")
        if self.mutable_records:
            scenario.append("mutated")
        if self.pii_in_record:
            scenario.append("pii")
        if not scenario:
            scenario.append("empty")
        return {
            "use_total": self.use_total,
            "no_train_uses": self.no_train_uses,
            "training_enabled_uses": self.training_enabled_uses,
            "deny_total": self.deny_total,
            "deny_by_reason": self.deny_by_reason,
            "opt_ins_active": self.opt_ins_active,
            "audit_events": self.audit_events,
            "expected_audit": self.expected_audit,
            "unaudited_event": max(0, self.expected_audit - self.audit_events),
            "train_without_optin": self.train_without_optin,
            "loosening_override": self.loosening_override,
            "non_no_train_provider": self.non_no_train_provider,
            "logging_provider": self.logging_provider,
            "no_dpa_provider": self.no_dpa_provider,
            "region_violation": self.region_violation,
            "training_after_expiry": self.training_after_expiry,
            "training_after_revoke": self.training_after_revoke,
            "out_of_scope_training": self.out_of_scope_training,
            "cross_tenant_training": self.cross_tenant_training,
            "forbidden_profile_training": self.forbidden_profile_training,
            "self_approval": self.self_approval,
            "mutable_records": self.mutable_records,
            "pii_in_record": self.pii_in_record,
            "scenario": scenario,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Tam simülasyon (bir sample)
# ─────────────────────────────────────────────────────────────────────────────
DISPATCH = {
    "register_provider": "register_provider", "bind_profile": "bind_profile",
    "grant_opt_in": "grant_opt_in", "revoke_opt_in": "revoke_opt_in",
    "set_override": "set_override", "mutate_record": "mutate_record", "use": "use",
}


def simulate(sample, policy):
    events = sample.get("events")
    if events is None or not isinstance(events, list) or not events:
        raise NoTrainError("boş/geçersiz olay akışı → INVALID_REQUEST")
    rt = NoTrainRegistry(policy)
    for ev in events:
        if not isinstance(ev, dict):
            raise NoTrainError("olay sözlük değil → INVALID_REQUEST")
        kind = ev.get("kind")
        meth = DISPATCH.get(kind)
        if meth is None:
            raise NoTrainError("bilinmeyen olay tipi: %r → INVALID_REQUEST" % kind)
        getattr(rt, meth)(ev)
    return rt.metrics()


def evaluate(gates, m):
    """Metrikleri HARD kapılara (P1–P8) karşı değerlendirir. Döner findings[(ok, label)]."""
    F = []

    # ── P1 (T1/T3): varsayılan no-train + sessiz gevşetme yok
    F.append((m.get("train_without_optin", 0) <= gates.get("max_train_without_optin", 0)
              and m.get("loosening_override", 0) <= gates.get("max_loosening_override", 0),
              "P1 varsayılan-no-train: train_without_optin %d ≤ %d + loosening_override %d ≤ %d (FR-LLM-012)"
              % (m.get("train_without_optin", 0), gates.get("max_train_without_optin", 0),
                 m.get("loosening_override", 0), gates.get("max_loosening_override", 0))))

    # ── P2 (T2/T11/NFR10.7): sağlayıcı uygunluğu (no-train + no-log + DPA + region)
    F.append((m.get("non_no_train_provider", 0) <= gates.get("max_non_no_train_provider", 0)
              and m.get("logging_provider", 0) <= gates.get("max_logging_provider", 0)
              and m.get("no_dpa_provider", 0) <= gates.get("max_no_dpa_provider", 0)
              and m.get("region_violation", 0) <= gates.get("max_region_violation", 0),
              "P2 sağlayıcı-uygunluk: non_no_train %d + logging %d + no_dpa %d + region %d (FR-LLM-012/FR-KB-010/BRD §14.1/NFR 10.7)"
              % (m.get("non_no_train_provider", 0), m.get("logging_provider", 0),
                 m.get("no_dpa_provider", 0), m.get("region_violation", 0))))

    # ── P3 (T5/T6): opt-in süre dolumu + geri çekme
    F.append((m.get("training_after_expiry", 0) <= gates.get("max_training_after_expiry", 0)
              and m.get("training_after_revoke", 0) <= gates.get("max_training_after_revoke", 0),
              "P3 süre/iptal: training_after_expiry %d ≤ %d + training_after_revoke %d ≤ %d (FR-LLM-012)"
              % (m.get("training_after_expiry", 0), gates.get("max_training_after_expiry", 0),
                 m.get("training_after_revoke", 0), gates.get("max_training_after_revoke", 0))))

    # ── P4 (T7): opt-in kapsamı
    F.append((m.get("out_of_scope_training", 0) <= gates.get("max_out_of_scope_training", 0),
              "P4 kapsam: out_of_scope_training %d ≤ %d (tenant/data_class; FR-LLM-012)"
              % (m.get("out_of_scope_training", 0), gates.get("max_out_of_scope_training", 0))))

    # ── P5 (T8): tenant izolasyonu
    F.append((m.get("cross_tenant_training", 0) <= gates.get("max_cross_tenant_training", 0),
              "P5 tenant-izolasyon: cross_tenant_training %d ≤ %d (FR-TEN-002)"
              % (m.get("cross_tenant_training", 0), gates.get("max_cross_tenant_training", 0))))

    # ── P6 (T9): profil en-kısıtlayıcı
    F.append((m.get("forbidden_profile_training", 0) <= gates.get("max_forbidden_profile_training", 0),
              "P6 profil-en-kısıtlayıcı: forbidden_profile_training %d ≤ %d (regüle profil ezer; DPIA §D3/SAD §19)"
              % (m.get("forbidden_profile_training", 0), gates.get("max_forbidden_profile_training", 0))))

    # ── P7 (T10): audit + WORM
    aud_ok = (not gates.get("require_audit", True)) \
        or m.get("unaudited_event", 0) <= gates.get("max_unaudited_event", 0)
    worm_ok = m.get("mutable_records", 0) <= gates.get("max_mutable_record", 0)
    F.append((aud_ok and worm_ok,
              "P7 audit+WORM: unaudited_event %d ≤ %d + mutable_records %d ≤ %d (%d/%d denetlendi; FR-IAM-006/FR-REC-009)"
              % (m.get("unaudited_event", 0), gates.get("max_unaudited_event", 0),
                 m.get("mutable_records", 0), gates.get("max_mutable_record", 0),
                 m.get("audit_events", 0), m.get("expected_audit", 0))))

    # ── P8 (T4/T12): maker-checker + no-PII
    mc_ok = (not gates.get("require_maker_checker", True)) \
        or m.get("self_approval", 0) <= gates.get("max_self_approval", 0)
    pii_ok = m.get("pii_in_record", 0) <= gates.get("max_pii_in_record", 0)
    F.append((mc_ok and pii_ok,
              "P8 maker-checker+no-PII: self_approval %d + pii_in_record %d (FR-LLM-012/ADR-012/TM-I-09)"
              % (m.get("self_approval", 0), m.get("pii_in_record", 0))))

    return F


# ─────────────────────────────────────────────────────────────────────────────
# politika çözümleme
# ─────────────────────────────────────────────────────────────────────────────
def _default_policy():
    return {
        "enforce_no_train_default": True,
        "require_no_train_capable_provider": True,
        "require_dpa": True,
        "region_pin": True,
        "honor_expiry": True,
        "honor_revocation": True,
        "enforce_scope": True,
        "tenant_isolation": True,
        "enforce_profile_restriction": True,
        "reject_loosening_override": True,
        "maker_checker": True,
        "audit": True,
        "worm": True,
        "order_guard": True,
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
    except NoTrainError as ex:
        print("simulate[%s]: REDDEDİLDİ — %s" % (name, ex))
        return 0 if expect == "fail" else 1

    F = evaluate(gates, m)
    print("simulate[%s] senaryo=%s | %d use → %d no-train / %d governed-opt-in / %d DENY %s | %d/%d denetlendi"
          % (name, "+".join(m["scenario"]), m["use_total"], m["no_train_uses"],
             m["training_enabled_uses"], m["deny_total"],
             dict(m["deny_by_reason"]) if m["deny_by_reason"] else "",
             m["audit_events"], m["expected_audit"]))
    print("  improper-train: no-optin=%d loosening=%d non-no-train-provider=%d logging=%d no-dpa=%d region=%d after-expiry=%d after-revoke=%d out-of-scope=%d cross-tenant=%d forbidden-profile=%d | self-approval=%d mutated=%d pii=%d"
          % (m["train_without_optin"], m["loosening_override"], m["non_no_train_provider"],
             m["logging_provider"], m["no_dpa_provider"], m["region_violation"],
             m["training_after_expiry"], m["training_after_revoke"], m["out_of_scope_training"],
             m["cross_tenant_training"], m["forbidden_profile_training"],
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

    _check(R, spec.get("wbs") == "5.8", "spec.wbs == 5.8")
    _check(R, spec.get("version"), "spec.version mevcut")

    tr = spec.get("trace", {})
    _check(R, "FR-LLM-012" in tr.get("fr", []), "trace FR-LLM-012 (görev izi)")
    _check(R, "FR-KB-010" in tr.get("fr", []), "trace FR-KB-010 (no-log)")
    _check(R, "FR-TEN-002" in tr.get("fr", []), "trace FR-TEN-002 (tenant izolasyon)")
    _check(R, "FR-IAM-006" in tr.get("fr", []), "trace FR-IAM-006 (audit)")
    _check(R, "NFR 10.7" in tr.get("nfr", []), "trace NFR 10.7 (residency/region pin)")
    _check(R, "SR-LLM-012" in tr.get("srs", []), "trace SR-LLM-012")
    _check(R, any("5.8" in x for x in tr.get("rtm", [])), "trace RTM 5.8 ↔ FR-LLM-012")

    # ── placement
    pl = spec.get("placement", {})
    _check(R, pl.get("consulted_before_provider_send") is True,
           "sağlayıcıya gönderim ÖNCESİ danışılır (4.2.4/4.2.x disposition gate)")
    _check(R, pl.get("orchestrator_depends_on_decision_only") is True,
           "orchestrator yalnız karara bağımlı (ADR-001)")
    _check(R, pl.get("media_path") is False, "medya hot-path'i DEĞİL (SAD §20 bütçesi dışı)")
    _check(R, "noTrain" in (pl.get("consumed_by_spi") or ""),
           "noTrain ile 4.2.4 LlmAdapter'a beslenir (API §11.1/§11.4)")

    # ── spi
    sp = spec.get("spi", {})
    _check(R, set(sp.get("provider_categories", [])) == PROVIDER_CATEGORIES,
           "provider_categories {llm, stt, tts}")
    _check(R, set(sp.get("data_classes", [])) == DATA_CLASSES, "data_classes kataloğu tam")
    _check(R, sp.get("default_no_train") is True, "default_no_train = true (FR-LLM-012)")
    _check(R, set(sp.get("opt_in_state", [])) == OPT_IN_STATE, "opt_in_state {granted, withdrawn}")
    _check(R, set(sp.get("deny_reasons", [])) == DENY_REASONS, "deny_reasons kataloğu tam")
    _check(R, {"tenants", "data_classes"} == set(sp.get("scope_dimensions", [])),
           "scope_dimensions {tenants, data_classes}")
    _check(R, {"opt_in_id", "tenant_id", "data_class", "expires_at", "state", "approved_by"}
           <= set(sp.get("opt_in_record_fields", [])),
           "opt_in_record alanları (expires_at/state/approved_by — maker-checker)")
    _check(R, {"provider_id", "no_train_capable", "allowed_retention", "dpa_signed", "regions"}
           <= set(sp.get("provider_record_fields", [])),
           "provider_record alanları (no_train_capable/allowed_retention/dpa_signed/regions)")

    # ── kapılar
    g = spec.get("gates", {})
    for k in ("max_train_without_optin", "max_loosening_override", "max_non_no_train_provider",
              "max_logging_provider", "max_no_dpa_provider", "max_region_violation",
              "max_training_after_expiry", "max_training_after_revoke", "max_out_of_scope_training",
              "max_cross_tenant_training", "max_forbidden_profile_training", "max_self_approval",
              "max_mutable_record", "max_pii_in_record", "max_unaudited_event"):
        _check(R, g.get(k, -1) == 0, "kapı %s = 0" % k)
    _check(R, g.get("require_audit") is True, "P7 require_audit (FR-IAM-006)")
    _check(R, g.get("require_maker_checker") is True, "P8 require_maker_checker (ADR-012)")
    _check(R, g.get("require_default_no_train") is True, "P1 require_default_no_train (FR-LLM-012)")
    _check(R, g.get("default_no_train") is True, "kapı default_no_train = true")

    # ── metrikler → observability
    me = spec.get("metrics", {})
    emitted = set(me.get("emitted", []))
    _check(R, {"no_train_use_total", "training_enabled_use_total", "no_train_denied_total"} <= emitted,
           "metrikler: no-train + training-enabled + denied yayılır")
    hc = set(me.get("high_cardinality_forbidden_as_label", []))
    _check(R, {"opt_in_id", "subprocessor_ref", "evidence_ref"} <= hc,
           "yüksek-kardinalite kimlikler metrik label OLAMAZ (0.4.7 kardinalite disiplini)")
    _check(R, len(me.get("maps_to_observability", {})) >= 1, "metrik observability'ye eşlenir (0.4.7)")

    # ── error taxonomy
    et = spec.get("error_taxonomy", {})
    mapping = et.get("mapping", {})
    _check(R, len(mapping) >= 4, "hata eşlemesi (≥4)")
    _check(R, all(v in ERROR_TAXONOMY for v in mapping.values()),
           "tüm hedefler API §11.6 ErrorTaxonomy'de")
    _check(R, mapping.get("PROVIDER_NOT_NO_TRAIN") == "CONTENT_FILTERED"
           and mapping.get("PROVIDER_NO_DPA") == "AUTH"
           and mapping.get("REGION_VIOLATION") == "REGION_VIOLATION",
           "PROVIDER_NOT_NO_TRAIN→CONTENT_FILTERED, no-DPA→AUTH, bölge→REGION_VIOLATION")
    _check(R, set(mapping.keys()) <= DENY_REASONS, "eşleme anahtarları deny_reasons kataloğunda")

    # ── residency + pii
    rs = spec.get("residency", {})
    _check(R, rs.get("region_pin_required") is True, "residency region pin (NFR 10.7)")
    _check(R, rs.get("no_train_required") is True, "no-train zorunlu (FR-LLM-012)")
    _check(R, rs.get("no_log_required") is True
           and set(rs.get("allowed_retention", [])) <= ALLOWED_RETENTION,
           "no-log: retention NONE/EPHEMERAL (FR-KB-010)")
    pii = spec.get("pii", {})
    _check(R, pii.get("raw_prompt_in_record_forbidden") is True
           and pii.get("raw_transcript_in_record_forbidden") is True
           and pii.get("pii_value_in_record_forbidden") is True
           and pii.get("only_opaque_refs") is True,
           "T12 ham prompt/transkript/PII değeri yasak; yalnız opak ref")
    _check(R, set(spec.get("forbidden_record_keys", [])) == FORBIDDEN_RECORD_KEYS,
           "forbidden_record_keys kataloğu probe ile tutarlı")

    # ── retention
    rt2 = spec.get("retention", {})
    _check(R, "WORM" in (rt2.get("opt_in_record") or "") or "append-only" in (rt2.get("opt_in_record") or ""),
           "opt-in record WORM/append-only (T10)")

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
            _check(R, prof.get("requires_no_train") is True,
                   "config %s requires_no_train açık (FR-LLM-012 varsayılan)" % prof.get("name"))
            _check(R, prof.get("provider_retention") in ALLOWED_RETENTION,
                   "config %s provider_retention NONE/EPHEMERAL (FR-KB-010)" % prof.get("name"))
            _check(R, prof.get("require_dpa") is True,
                   "config %s require_dpa açık (BRD §14.1)" % prof.get("name"))
            _check(R, prof.get("maker_checker") is True,
                   "config %s maker_checker açık (ADR-012)" % prof.get("name"))
            _check(R, prof.get("tenant_isolation") is True,
                   "config %s tenant_isolation açık (FR-TEN-002)" % prof.get("name"))
            _check(R, prof.get("audit") is True, "config %s audit açık (FR-IAM-006)" % prof.get("name"))
            _check(R, isinstance(prof.get("forbid_training_opt_in"), bool),
                   "config %s forbid_training_opt_in tanımlı" % prof.get("name"))
        nd = cfg.get("no_train_defaults", {})
        _check(R, nd.get("default_no_train") is True,
               "config no_train_defaults default_no_train = true")
        _check(R, nd.get("override_tightens_only") is True,
               "config override yalnız-sıkılaştırır (T3)")
        _check(R, cfg.get("default_profile") in names, "default_profile geçerli")
        # en az bir regüle profil opt-in'i yasaklamalı (most-restrictive gösterimi)
        _check(R, any(p.get("forbid_training_opt_in") is True for p in profs),
               "≥1 profil forbid_training_opt_in=true (regüle; most-restrictive)")

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
    except NoTrainError:
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
def _prov(t, pid="prov-llm-A", cat="llm", no_train=True, retention=None,
          region_pin=True, regions=None, dpa=True):
    return {"kind": "register_provider", "provider_id": pid, "category": cat,
            "no_train_capable": no_train, "allowed_retention": retention or ["NONE"],
            "region_pin_capable": region_pin, "regions": regions or ["eu-west"],
            "dpa_signed": dpa, "subprocessor_ref": "sub://anon/%s" % pid, "t": t}


def _bind(t, tenant="t1", profile="pilot", region="eu-west",
          requires_no_train=True, forbid=False):
    return {"kind": "bind_profile", "tenant_id": tenant, "profile": profile, "region": region,
            "requires_no_train": requires_no_train, "forbid_training_opt_in": forbid, "t": t}


def _grant(t, oid="o1", tenant="t1", dc="prompt", scope=None, expires=10000,
           gby="designer-1", aby="approver-2"):
    return {"kind": "grant_opt_in", "opt_in_id": oid, "tenant_id": tenant, "data_class": dc,
            "scope": scope or {"tenants": ["t1"], "data_classes": ["prompt"]},
            "evidence_ref": "ev://opt-in/%s" % oid, "granted_by": gby, "approved_by": aby,
            "expires_at": expires, "t": t}


def _use(t, uid="u1", tenant="t1", pid="prov-llm-A", dc="prompt", ref=None):
    ev = {"kind": "use", "use_id": uid, "tenant_id": tenant, "provider_id": pid,
          "data_class": dc, "call_ref": "call://anon/%s" % uid, "t": t}
    if ref is not None:
        ev["opt_in_ref"] = ref
    return ev


def _revoke(t, oid="o1"):
    return {"kind": "revoke_opt_in", "opt_in_id": oid, "t": t}


def selftest():
    spec = _load(SPEC_PATH)
    gates = spec.get("gates", {})
    cases = []

    def case(ok, label):
        cases.append((bool(ok), label))

    # 0) validate iyi spec+config'te geçer
    case(_validate_obj(_load(SPEC_PATH)) == 0, "validate iyi spec+config'te 0 döndürür")

    # ── happy (varsayılan no-train): provider + profil → opt-in'siz use → ALLOW + no-train
    mh = simulate({"events": [
        _prov(0), _bind(10), _use(100, uid="u1"), _use(200, uid="u2"),
    ]}, _pol())
    case(mh["no_train_uses"] == 2 and mh["training_enabled_uses"] == 0 and mh["deny_total"] == 0,
         "happy: opt-in'siz 2 use → effective no-train (T1 varsayılan)")
    case(mh["unaudited_event"] == 0 and mh["audit_events"] == mh["expected_audit"],
         "happy: tüm olay + karar denetlendi (P7/T10)")
    case(all(ok for ok, _ in evaluate(gates, mh)), "happy tüm kapıları geçer (P1–P8)")

    # ── governed opt-in: geçerli + profil izinli → effective_no_train=false (meşru)
    mg = simulate({"events": [
        _prov(0), _bind(10, forbid=False), _grant(20), _use(100, ref="o1"),
    ]}, _pol())
    case(mg["training_enabled_uses"] == 1 and mg["no_train_uses"] == 0,
         "governed: geçerli opt-in + izinli profil → eğitim açık (meşru)")
    case(all(ok for ok, _ in evaluate(gates, mg)), "governed opt-in tüm kapıları geçer")

    # ── determinizm
    ev = [_prov(0), _bind(10), _grant(20), _use(100, ref="o1")]
    case(simulate({"events": ev}, _pol()) == simulate({"events": ev}, _pol()),
         "determinizm: aynı olay-akışı birebir aynı metrik (random yok)")

    # ── DENY: bilinmeyen sağlayıcı
    m0 = simulate({"events": [_bind(10), _use(100, pid="nope")]}, _pol())
    case(m0["deny_by_reason"].get("UNKNOWN_PROVIDER") == 1, "bilinmeyen sağlayıcı → UNKNOWN_PROVIDER DENY")

    # ── DENY: no-train yeteneksiz sağlayıcı (T2)
    m1 = simulate({"events": [_prov(0, no_train=False), _bind(10), _use(100)]}, _pol())
    case(m1["deny_by_reason"].get("PROVIDER_NOT_NO_TRAIN") == 1 and m1["non_no_train_provider"] == 0,
         "DENY: no-train yeteneksiz sağlayıcı → PROVIDER_NOT_NO_TRAIN (T2)")
    case(all(ok for ok, _ in evaluate(gates, m1)), "no-train yeteneksiz reddedildi → P2 geçer")

    # ── DENY: log'layan sağlayıcı (retention NONE/EPHEMERAL değil) (T2)
    m2 = simulate({"events": [_prov(0, retention=["PROVIDER_DEFAULT"]), _bind(10), _use(100)]}, _pol())
    case(m2["deny_by_reason"].get("PROVIDER_LOGS_DATA") == 1, "DENY: log'layan sağlayıcı → PROVIDER_LOGS_DATA (T2)")
    case(all(ok for ok, _ in evaluate(gates, m2)), "log'layan sağlayıcı reddedildi → P2 geçer")

    # ── DENY: DPA'sız sağlayıcı (T11)
    m3 = simulate({"events": [_prov(0, dpa=False), _bind(10), _use(100)]}, _pol())
    case(m3["deny_by_reason"].get("PROVIDER_NO_DPA") == 1 and m3["no_dpa_provider"] == 0,
         "DENY: DPA'sız sağlayıcı → PROVIDER_NO_DPA (T11)")
    case(all(ok for ok, _ in evaluate(gates, m3)), "DPA'sız reddedildi → P2 geçer")

    # ── DENY: bölge uyumsuz sağlayıcı (NFR 10.7)
    m4 = simulate({"events": [_prov(0, regions=["us-east"]), _bind(10, region="eu-west"), _use(100)]}, _pol())
    case(m4["deny_by_reason"].get("REGION_VIOLATION") == 1 and m4["region_violation"] == 0,
         "DENY: bölge dışı sağlayıcı → REGION_VIOLATION (NFR 10.7)")
    case(all(ok for ok, _ in evaluate(gates, m4)), "bölge pin zorlandı → P2 geçer")

    # ── profil yasaklıyorsa geçerli opt-in EZİLİR → no-train (T9)
    mf = simulate({"events": [_prov(0), _bind(10, forbid=True), _grant(20), _use(100, ref="o1")]}, _pol())
    case(mf["training_enabled_uses"] == 0 and mf["no_train_uses"] == 1 and mf["forbidden_profile_training"] == 0,
         "profil yasaklı: geçerli opt-in ezildi → no-train (T9 most-restrictive)")
    case(all(ok for ok, _ in evaluate(gates, mf)), "regüle profil ezdi → P6 geçer")

    # ── süre dolmuş / geri çekilmiş / kapsam dışı / cross-tenant opt-in → no-train (güvenli)
    me = simulate({"events": [_prov(0), _bind(10), _grant(20, expires=150), _use(300, ref="o1")]}, _pol())
    case(me["no_train_uses"] == 1 and me["training_enabled_uses"] == 0 and me["training_after_expiry"] == 0,
         "süre dolmuş opt-in → güvenli no-train (T5)")
    mr = simulate({"events": [_prov(0), _bind(10), _grant(20), _revoke(30), _use(100, ref="o1")]}, _pol())
    case(mr["no_train_uses"] == 1 and mr["training_after_revoke"] == 0,
         "geri çekilmiş opt-in → güvenli no-train (T6)")
    ms = simulate({"events": [_prov(0), _bind(10),
                              _grant(20, scope={"tenants": ["t1"], "data_classes": ["transcript"]}),
                              _use(100, ref="o1", dc="prompt")]}, _pol())
    case(ms["no_train_uses"] == 1 and ms["out_of_scope_training"] == 0,
         "kapsam dışı (data_class) opt-in → güvenli no-train (T7)")
    mx = simulate({"events": [_prov(0), _bind(10, tenant="t1"), _bind(11, tenant="t2"),
                              _grant(20, tenant="t1"), _use(100, ref="o1", tenant="t2")]}, _pol())
    case(mx["no_train_uses"] == 1 and mx["cross_tenant_training"] == 0,
         "cross-tenant opt-in → güvenli no-train (T8)")

    # ── override yalnız-sıkılaştırır: tightening kabul → her zaman no-train (geçerli opt-in'i bile ezer)
    mo = simulate({"events": [_prov(0), _bind(10, forbid=False), _grant(20),
                              {"kind": "set_override", "tenant_id": "t1", "no_train": True, "t": 30},
                              _use(100, ref="o1")]}, _pol())
    case(mo["no_train_uses"] == 1 and mo["training_enabled_uses"] == 0,
         "tightening override → opt-in olsa bile no-train (T3 yalnız-sıkılaştırır)")
    # loosening override normalde REDDEDİLİR (raise)
    case(_raises(lambda: simulate({"events": [_prov(0), _bind(10),
                                              {"kind": "set_override", "tenant_id": "t1", "no_train": False, "t": 30}]},
                                  _pol())),
         "loosening override reddedilir (raise, T3)")

    # ── DEGRADED: enforce_no_train_default kapalı → opt-in'siz eğitim açıldı (P1 eler)
    dg1 = simulate({"events": [_prov(0), _bind(10), _use(100)]}, _pol(enforce_no_train_default=False))
    case(dg1["train_without_optin"] >= 1 and not all(ok for ok, _ in evaluate(gates, dg1)),
         "degraded(no-default): opt-in'siz eğitim → P1 eler (FR-LLM-012)")

    # ── DEGRADED: reject_loosening_override kapalı → gevşeten override kabul (P1 eler)
    dg2 = simulate({"events": [_prov(0), _bind(10),
                               {"kind": "set_override", "tenant_id": "t1", "no_train": False, "t": 30},
                               _use(100)]},
                   _pol(reject_loosening_override=False))
    case(dg2["loosening_override"] >= 1 and not all(ok for ok, _ in evaluate(gates, dg2)),
         "degraded(loosening): gevşeten override + use → P1 eler (T3)")

    # ── DEGRADED: provider yeteneği zorlanmıyor → log'layan/no-train'siz sağlayıcı kullanıldı (P2 eler)
    dg3 = simulate({"events": [_prov(0, no_train=False, retention=["PROVIDER_DEFAULT"]), _bind(10), _use(100)]},
                   _pol(require_no_train_capable_provider=False))
    case(dg3["non_no_train_provider"] >= 1 and dg3["logging_provider"] >= 1
         and not all(ok for ok, _ in evaluate(gates, dg3)),
         "degraded(provider): no-train'siz+log'layan sağlayıcı kullanıldı → P2 eler (T2)")

    # ── DEGRADED: require_dpa kapalı → DPA'sız sağlayıcıya veri (P2 eler)
    dg4 = simulate({"events": [_prov(0, dpa=False), _bind(10), _use(100)]}, _pol(require_dpa=False))
    case(dg4["no_dpa_provider"] >= 1 and not all(ok for ok, _ in evaluate(gates, dg4)),
         "degraded(no-dpa): DPA'sız sağlayıcıya veri → P2 eler (T11)")

    # ── DEGRADED: honor_expiry/revocation kapalı → süre/iptal sonrası eğitim (P3 eler)
    dg5 = simulate({"events": [_prov(0), _bind(10), _grant(20, expires=150),
                               _use(300, uid="u1", ref="o1"), _revoke(350), _use(400, uid="u2", ref="o1")]},
                   _pol(honor_expiry=False, honor_revocation=False))
    case(dg5["training_after_expiry"] >= 1 and dg5["training_after_revoke"] >= 1
         and not all(ok for ok, _ in evaluate(gates, dg5)),
         "degraded(no-expiry/revoke): süre/iptal sonrası eğitim → P3 eler")

    # ── DEGRADED: enforce_scope kapalı → kapsam dışı eğitim (P4 eler)
    dg6 = simulate({"events": [_prov(0), _bind(10),
                               _grant(20, scope={"tenants": ["t1"], "data_classes": ["transcript"]}),
                               _use(100, ref="o1", dc="prompt")]},
                   _pol(enforce_scope=False))
    case(dg6["out_of_scope_training"] >= 1 and not all(ok for ok, _ in evaluate(gates, dg6)),
         "degraded(no-scope): kapsam dışı eğitim → P4 eler (T7)")

    # ── DEGRADED: tenant_isolation kapalı → cross-tenant eğitim (P5 eler)
    dg7 = simulate({"events": [_prov(0), _bind(10, tenant="t1"), _bind(11, tenant="t2"),
                               _grant(20, tenant="t1"), _use(100, ref="o1", tenant="t2")]},
                   _pol(tenant_isolation=False))
    case(dg7["cross_tenant_training"] >= 1 and not all(ok for ok, _ in evaluate(gates, dg7)),
         "degraded(no-isolation): cross-tenant eğitim → P5 eler (FR-TEN-002)")

    # ── DEGRADED: enforce_profile_restriction kapalı → yasaklı profilde eğitim (P6 eler)
    dg8 = simulate({"events": [_prov(0), _bind(10, forbid=True), _grant(20), _use(100, ref="o1")]},
                   _pol(enforce_profile_restriction=False))
    case(dg8["forbidden_profile_training"] >= 1 and not all(ok for ok, _ in evaluate(gates, dg8)),
         "degraded(no-profile-restrict): regüle profilde eğitim → P6 eler (T9)")

    # ── DEGRADED: audit kapalı → denetlenmemiş olay (P7 eler)
    dg9 = simulate({"events": [_prov(0), _bind(10), _use(100)]}, _pol(audit=False))
    case(dg9["unaudited_event"] >= 1 and not all(ok for ok, _ in evaluate(gates, dg9)),
         "degraded(no-audit): yaşam döngüsü/karar denetlenmedi → P7 eler (FR-IAM-006)")

    # ── DEGRADED: maker_checker kapalı + self-approval → P8 eler
    dg10 = simulate({"events": [_prov(0), _bind(10),
                                _grant(20, gby="x", aby="x"), _use(100, ref="o1")]},
                    _pol(maker_checker=False))
    case(dg10["self_approval"] >= 1 and not all(ok for ok, _ in evaluate(gates, dg10)),
         "degraded(self-approval): opt-in onaylayan=oluşturan → P8 eler (T4)")

    # ── DEGRADED: WORM kapalı + mutate_record → P7 eler
    dg11 = simulate({"events": [_prov(0), _bind(10), _grant(20),
                                {"kind": "mutate_record", "target": "opt_in", "ref": "o1", "t": 50},
                                _use(100, ref="o1")]},
                    _pol(worm=False))
    case(dg11["mutable_records"] >= 1 and not all(ok for ok, _ in evaluate(gates, dg11)),
         "degraded(no-worm): opt-in kaydı mutasyonu → P7 eler (T10)")

    # ── DEGRADED: PII/ham içerik kayıtta → P8 eler
    dgp = simulate({"events": [_prov(0), _bind(10),
                               {"kind": "use", "use_id": "u1", "tenant_id": "t1", "provider_id": "prov-llm-A",
                                "data_class": "prompt", "t": 100, "raw_prompt": "FORBIDDEN"}]}, _pol())
    case(dgp["pii_in_record"] >= 1 and not all(ok for ok, _ in evaluate(gates, dgp)),
         "degraded(pii): kayıtta ham prompt/PII → P8 eler (T12)")

    # ── maker-checker normalde self-approval'ı REDDEDER (raise)
    case(_raises(lambda: simulate({"events": [_prov(0), _bind(10), _grant(20, gby="x", aby="x")]}, _pol())),
         "maker-checker açık: opt-in self-approval reddedilir (raise)")

    # ── WORM normalde mutasyonu REDDEDER (raise)
    case(_raises(lambda: simulate({"events": [_prov(0), _grant(20),
                                              {"kind": "mutate_record", "target": "opt_in", "ref": "o1", "t": 50}]},
                                  _pol())),
         "WORM açık: kayıt mutasyonu reddedilir (raise)")

    # ── yapısal redler
    case(_raises(lambda: simulate({"events": [_prov(0), _prov(0)]}, _pol())),
         "tekrar provider kaydı → reddedilir")
    case(_raises(lambda: simulate({"events": [_prov(0), _grant(20, oid="o1"), _grant(30, oid="o1")]}, _pol())),
         "tekrar opt_in_id (WORM) → reddedilir")
    case(_raises(lambda: simulate({"events": [_prov(0), {"kind": "grant_opt_in", "opt_in_id": "o1",
                                                         "tenant_id": "t1", "data_class": "prompt",
                                                         "scope": {}, "granted_by": "a", "approved_by": "b",
                                                         "t": 20}]}, _pol())),
         "evidence_ref yok → reddedilir (T12 opak ref)")
    case(_raises(lambda: simulate({"events": [{"kind": "register_provider", "provider_id": "p",
                                               "category": "vision", "allowed_retention": ["NONE"], "t": 0}]}, _pol())),
         "geçersiz category → reddedilir")
    case(_raises(lambda: simulate({"events": [_prov(0), _use(100, dc="biometric")]}, _pol())),
         "geçersiz data_class → reddedilir")
    case(_raises(lambda: simulate({"events": [_prov(1000), _bind(0)]}, _pol())),
         "out-of-order olay → reddedilir")
    case(_raises(lambda: simulate({"events": [{"kind": "nope", "t": 0}]}, _pol())),
         "bilinmeyen olay tipi → reddedilir")
    case(_raises(lambda: simulate({"events": []}, _pol())), "boş olay akışı → reddedilir")

    # ── validate negatif kapılar
    s = json.loads(json.dumps(spec)); s["gates"]["max_train_without_optin"] = 1
    case(_validate_obj(s) != 0, "P1 max_train_without_optin>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_loosening_override"] = 1
    case(_validate_obj(s) != 0, "P1 max_loosening_override>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_non_no_train_provider"] = 1
    case(_validate_obj(s) != 0, "P2 max_non_no_train_provider>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_cross_tenant_training"] = 1
    case(_validate_obj(s) != 0, "P5 max_cross_tenant_training>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_forbidden_profile_training"] = 1
    case(_validate_obj(s) != 0, "P6 max_forbidden_profile_training>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["require_default_no_train"] = False
    case(_validate_obj(s) != 0, "P1 require_default_no_train=false → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["require_maker_checker"] = False
    case(_validate_obj(s) != 0, "P8 require_maker_checker=false → validate eler")
    s = json.loads(json.dumps(spec)); s["spi"]["default_no_train"] = False
    case(_validate_obj(s) != 0, "spi default_no_train=false → validate eler")
    s = json.loads(json.dumps(spec)); s["residency"]["no_train_required"] = False
    case(_validate_obj(s) != 0, "residency no_train_required=false → validate eler")
    s = json.loads(json.dumps(spec)); s["residency"]["allowed_retention"] = ["PROVIDER_DEFAULT"]
    case(_validate_obj(s) != 0, "no-log dışı retention → validate eler")
    s = json.loads(json.dumps(spec)); s["pii"]["pii_value_in_record_forbidden"] = False
    case(_validate_obj(s) != 0, "T12 PII-değer-yasak kapalı → validate eler")
    s = json.loads(json.dumps(spec)); s["error_taxonomy"]["mapping"]["PROVIDER_NO_DPA"] = "NOPE"
    case(_validate_obj(s) != 0, "taksonomi-dışı eşleme → validate eler")
    s = json.loads(json.dumps(spec)); s["metrics"]["secret"] = "api_key: AKIAIOSFODNN7EXAMPLE"
    case(_validate_obj(s) != 0, "literal secret → validate eler")

    passed = sum(1 for ok, _ in cases if ok)
    total = len(cases)
    for ok, label in cases:
        print("  %s %s" % ("✓" if ok else "✗", label))
    print("selftest: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


def schema():
    print("""no-train-spec.json beklenen şekli (WBS 5.8):
  wbs, version, phase, trace{fr[FR-LLM-012,FR-KB-010,FR-TEN-002,FR-IAM-006,FR-REC-009], nfr[NFR 10.7],
       sad, adr, api, srs[SR-LLM-012], rtm[5.8↔FR-LLM-012], brd, dpia, threat_model, vendor_eval,
       consumes, consumed_by, observability}
  placement{consulted_before_provider_send=true, orchestrator_depends_on_decision_only=true,
            media_path=false, consumed_by_spi(noTrain → 4.2.4 LlmAdapter + STT/TTS)}
  spi{decision(resolveTrainingDisposition), lifecycle_methods[registerProvider/bindProfile/
      grantTrainingOptIn/revokeTrainingOptIn/setNoTrainOverride], provider_categories[llm,stt,tts],
      data_classes[prompt,transcript,kb_content,audio], default_no_train=true,
      opt_in_state[granted,withdrawn], deny_reasons[...], opt_in_record_fields[...],
      provider_record_fields[...], scope_dimensions[tenants,data_classes], scope_wildcard}
  gates{max_train_without_optin=0, max_loosening_override=0, max_non_no_train_provider=0,
        max_logging_provider=0, max_no_dpa_provider=0, max_region_violation=0,
        max_training_after_expiry=0, max_training_after_revoke=0, max_out_of_scope_training=0,
        max_cross_tenant_training=0, max_forbidden_profile_training=0, max_self_approval=0,
        max_mutable_record=0, max_pii_in_record=0, require_audit=true, max_unaudited_event=0,
        require_maker_checker=true, require_default_no_train=true, default_no_train=true}   (P1-P8)
  metrics{emitted[], high_cardinality_forbidden_as_label[opt_in_id,subprocessor_ref,...],
          maps_to_observability{}}
  error_taxonomy{mapping(deny_reason → API §11.6)}
  residency{region_pin_required=true, no_train_required=true, no_log_required=true,
            allowed_retention[NONE,EPHEMERAL]}
  retention{opt_in_record(WORM/append-only), provider_record(alt-işleyen Ek-A)}
  pii{raw_prompt/raw_transcript/raw_audio/pii_value_in_record_forbidden=true, only_opaque_refs=true}
  forbidden_record_keys[raw_prompt,raw_transcript,raw_audio,pii_value,prompt_text,message_text]
  invariants[≥12 T1..T12]{id, desc, trace}

config/no-train-profiles.json: default_profile, no_train_defaults{default_no_train=true,
  override_tightens_only=true, scope_dimensions[tenants,data_classes], scope_wildcard,
  default_opt_in_ttl_days}; profiles[]{name, region, requires_no_train=true,
  provider_retention(NONE/EPHEMERAL), require_dpa=true, forbid_training_opt_in(bool),
  maker_checker=true, tenant_isolation=true, audit=true}; dpa_registry(${ENV})

simulate sample: {name, expect, expected?{metrik:değer}, policy?{enforce_no_train_default,
  require_no_train_capable_provider, require_dpa, region_pin, honor_expiry, honor_revocation,
  enforce_scope, tenant_isolation, enforce_profile_restriction, reject_loosening_override,
  maker_checker, audit, worm},
  events[
    {kind:'register_provider', provider_id, category, no_train_capable, allowed_retention,
       region_pin_capable, regions, dpa_signed, subprocessor_ref?, t} |
    {kind:'bind_profile', tenant_id, profile, region, requires_no_train, forbid_training_opt_in, t} |
    {kind:'grant_opt_in', opt_in_id, tenant_id, data_class, scope, evidence_ref, granted_by,
       approved_by, expires_at, t} |
    {kind:'revoke_opt_in', opt_in_id, t} | {kind:'set_override', tenant_id, no_train, t} |
    {kind:'use', use_id, tenant_id, provider_id, data_class, opt_in_ref?, call_ref?, t} |
    {kind:'mutate_record', target, ref, t}  (WORM → reddedilir)]}

komutlar: validate | simulate <sample.json> | selftest | schema""")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if cmd == "validate":
        return validate()
    if cmd == "simulate":
        if len(sys.argv) < 3:
            print("kullanım: no_train_probe.py simulate <sample.json>")
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
