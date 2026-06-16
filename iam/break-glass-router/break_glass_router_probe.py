#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 12.3.5 — BREAK-GLASS TAM-AUDIT ROUTER (AYRI, KISITLI) referans probe.

12. workstream'in (IAM & Erişim) ÜÇ KATMANLI BREAK-GLASS'ın ROUTER/ADMISSION KATMANI ve F2-Must yeteneği.
SAD §14.4.2 ('maker-checker → süreli token → ... Erişim AYRI, KISITLI, TAM-AUDIT'li bir break-glass ROUTER'ı
üzerinden verilir') + BRD §17/§17.7 (altın kural: L0 tenant iş içeriğini varsayılan göremez; içeriğe erişim
üç katmanlı break-glass ile) + FR-IAM-009 (üç katmanlı break-glass) + FR-IAM-008 (L0 iş verisine tasarımca bağlı
değil) + FR-IAM-006/FR-REC-009 (TÜM break-glass erişimi audit) + FR-REC-004 (audit PII'siz) + ADR-011 (Platform
Control Plane internal-only + ayrı router ağaçları/scope) + ADR-013. ALTIN KURAL (BRD §17): L0 tenant iş içeriğini
VARSAYILAN GÖREMEZ — Tier B içeriğine erişim YALNIZ bu AYRI, KISITLI, TAM-AUDIT'li ROUTER'dan geçer. Bu modül
12.3.4'ün ALLOW/HOLD/BLOCK (sanction_decision) kararını + 12.3.2'nin time-boxed TOKEN'ını TÜKETİR; bir
BreakGlassRouterRequest alır → DETERMİNİSTİK, FAIL-CLOSED bir ROUTER ADMISSION kararı verir:

    ADMIT  — istek break-glass handler'a yönlendirilir (AYRI router/plane/scope'ta + KISITLI [sanction=ALLOW +
             geçerli token] + scope-içi + TAM-AUDIT'li).
    REJECT — erişim yönlendirilmez (malformed / router izolasyon ihlali / sanction≠ALLOW / token
             geçersiz·expired·resolved·misbound / scope dışı → fail-closed; HER durumda audit'li).

ÇEKİRDEK:
  (1) C2 AYRI (router izolasyonu) — break-glass router AYRI/EK bir router ağacıdır; YALNIZ internal-only Platform
      Control Plane düzleminde (plane=platform_control_plane + internal_only=true) + dedicated break-glass OAuth
      scope'ta (panel:L0:break_glass; panel:L0/L1/L2'den DISJOINT) mount edilir; yanlış router/plane/scope →
      REJECT (router_isolation_violation=0).
  (2) C3 KISITLI (admission) — istek YALNIZ sanction=ALLOW (12.3.4) + GEÇERLİ time-boxed token (12.3.2) ile ADMIT
      edilir (no standing access); sanction'sız/token'sız ADMIT → unsanctioned_admission=0.
  (3) C4 TAM-AUDIT — break-glass router'dan geçen HER istek (ADMIT/REJECT/malformed) DEĞİŞMEZ (append-only/WORM)
      audit üretir — router'dan hiçbir istek audit'siz geçemez; audit'siz istek → unaudited_request=0.

      BreakGlassRouterRequest ─malformed─► router_isolation ─► restricted_admission ─► token ─► scope ─► full_audit
            ├─ request_id / actor_role(L0) / target_tenant / tier≠B / sanction tanınmaz / router_context yok ──► REJECT (malformed)
            ├─ router_id≠break_glass / plane≠platform_control_plane / internal_only≠true / scope≠break_glass ──► REJECT (router_isolation) [C2]
            ├─ sanction_decision ≠ ALLOW (12.3.4 HOLD/BLOCK) ─────────────────────────────────────────────────► REJECT (not_sanctioned) [C3]
            ├─ token yok / state resolved / access_tick>expires_at ──────────────────────────────────────────► REJECT (token_*) [C5/C8]
            ├─ token misbound (break_glass_id/target_tenant/tier) ───────────────────────────────────────────► REJECT (token_misbound) [C6]
            ├─ scope dışı (resource_type token.scope dışı / non-Tier-B) ─────────────────────────────────────► REJECT (out_of_scope) [C7]
            └─ hepsi geçer ─────────────────────────────────────────────────────────────────────────────────► ADMIT (routed)
      (her karar → DEĞİŞMEZ WORM audit; C4)

Motor DETERMİNİSTİK FAIL-CLOSED (Date.now/random YOK; model_hash sha256; tick=dakika sanal-saat). Her karar
terminal (C1) + kanıt + model bütünlük manifesti (C10); metrik düşük-kardinalite + ham PII/token yok (C11);
model/spec/sample ham içerik/PII/token tutmaz (C12).

Kapsam dışı (bilinçli, başka modül SAHİBİ): Tier B erişim-verme + token ÜRETİMİ → 12.3.2 (token CONSUMED);
regüle tenant onay + DPA → 12.3.4 (sanction_decision CONSUMED); gerekçe kodu + bildirim → 12.3.3; Tier
sınıflandırma + ESCALATE → 12.3.1; panel router topolojisi (L0/L1/L2) → 12.2.2 (RESİPROKAL — break-glass router
AYRI/EK ağaç); rol→permission-key/scope → 12.1.2/12.1.3; WORM audit hash-zinciri → 12.1.8 (CONSUMED). KAYNAK
DOĞRULUK; çelişkide SAD §14.4.2 / BRD §17 / FR-IAM-009 esastır.

Kullanım:
  break_glass_router_probe.py validate          Statik model + spec + 12.3.4/12.3.2/12.2.2/12.1.8/12.1.1 resiprokal → çıkış kodu
  break_glass_router_probe.py check <sample>    Router admission motoru: senaryo(lar) → kapı (C1–C12)
  break_glass_router_probe.py selftest          Gömülü davranış kontrolleri → çıkış kodu
  break_glass_router_probe.py schema            Karar sözleşmesini yazdır

Determinizm: model_hash sha256 (kanonik JSON, sort_keys); Date.now/random YOK (tick=dakika sanal-saat).
Stdlib-only. Sır/credential (break-glass token DEĞERİ) ve ham içerik (PII değeri) üretilmez/yazılmaz
(fixture sentetik — yalnız rol enum + realm enum + sınıf enum + kaynak adı + router/plane/scope enum +
tier/decision enum + sanction/token_state enum + tick tamsayı + slug kimlik; FR-TST-008).
"""
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "break-glass-router-spec.json")
MODEL_PATH = os.path.join(HERE, "config", "break-glass-router-model.json")
APPROVAL_MODEL_PATH = os.path.join(HERE, "..", "break-glass-tier-b-approval", "config", "tier-b-approval-model.json")
TIER_B_MODEL_PATH = os.path.join(HERE, "..", "break-glass-tier-b", "config", "tier-b-model.json")
ROUTER_TOPO_PATH = os.path.join(HERE, "..", "router-scopes", "config", "router-topology.json")
WORM_MODEL_PATH = os.path.join(HERE, "..", "worm-audit", "config", "worm-audit-model.json")
RBAC_MODEL_PATH = os.path.join(HERE, "..", "rbac-model", "config", "rbac-roles.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

TERMINAL = {"ADMIT", "REJECT"}
SANCTION_ALLOW = "ALLOW"                                           # 12.3.4 terminal — yalnız bu ADMIT'e izin verir
SANCTION_DECISIONS = {"ALLOW", "HOLD", "BLOCK"}                    # 12.3.4 sanction_decision çıktısı
PLATFORM_ROLES = {"platform_owner", "platform_sre", "platform_billing"}
ACTIVE_STATES = {"ACTIVE"}                                        # geçerli token state
RESOLVED_STATES = {"CONSUMED", "REVOKED", "EXPIRED"}              # replay: çözülmüş token
CONTENT_CLASS = "tenant_content"                                  # Tier B yalnız içerik
RULES = ["router_isolation", "restricted_admission", "full_audit", "token_expiry", "token_binding",
         "scope_limited", "replay_safe", "audit_integrity", "model_integrity"]
INVARIANT_IDS = ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10", "C11", "C12"]

# Degrade (inject) — DOĞRU router admission davranışını bozan müdahaleler.
INJECTIONS = {"mount_on_tenant_plane", "wrong_router_scope", "admit_unsanctioned", "admit_without_token",
              "admit_expired_token", "replay_token", "admit_misbound_token", "route_out_of_scope",
              "skip_audit", "leak_pii", "mutate_audit", "model_tamper", "secret_leak"}

VIOLATION_KEYS = [
    "router_isolation_violation", "unsanctioned_admission", "unaudited_request", "expired_token_admission",
    "token_misbinding", "out_of_scope_routing", "token_replay", "audit_pii", "audit_mutable", "model_tampered",
    "missing_evidence", "stuck_state", "secret_or_pii",
]

# ── Sızıntı tarayıcı (C12; 12.3.x deseniyle) — ham içerik/PII/token yasak; rol/realm/sınıf/kaynak/router beyazlanır ──
LEAK_PATTERNS = [
    ("phone_e164", re.compile(r"\+(?!1632)\d{9,15}\b")),
    ("digits_long", re.compile(r"\b\d{7,19}\b")),
    ("secret_kw", re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|bearer|credential|connection[_-]?string)\b\s*[:=]\s*\S")),
    ("privkey", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("pii_field", re.compile(r"(?i)\"(transcript_text_value|recording_audio_value|contact_pii_value|customer_phone_value|card_pan_value|cvv_value|otp_code_value|password_value|customer_name_value|db_password_value|connection_string_value|break_glass_token_value|approval_token_value|token_value|raw_value|pii_value)\"\s*:")),
]
LEAK_ALLOW = re.compile(r"(?i)(555-?01\d\d|\+1632|ITU|reserved|test|example|req-|t-|u-|bg-|rc-|corr-|tok-|prefix|masked|hash|sha256|\[[A-Z0-9_]+\]|\d{4}-\d{2}-\d{2}|_repo|tenant_|platform_|security_compliance|global_reference|break_glass|audit_log|usage_record)")


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def scan_leaks(text):
    """Ham içerik/PII/token tarayıcı. Yorum/tarif satırı + rol/realm/sınıf/kaynak/router adı + slug kimlik eler."""
    hits = []
    for ln, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("#"):
            continue
        for name, pat in LEAK_PATTERNS:
            for m in pat.finditer(line):
                frag = m.group(0)
                window = line[max(0, m.start() - 16):m.end() + 16]
                if '"$comment"' in line or '"description"' in line or '"desc"' in line or '"trace"' in line \
                        or '"note"' in line or '"rule"' in line or '"rationale"' in line.lower() \
                        or line.strip().startswith('"$'):
                    continue
                # pii_field = açık yasak alan-adı işareti (ör. "break_glass_token_value":) → allowlist'i atla
                if name != "pii_field" and (LEAK_ALLOW.search(window) or LEAK_ALLOW.search(frag)):
                    continue
                hits.append((ln, name, frag))
    return hits


# ════════════════════════════════════════════════════════════════════════════
def _canon_hash(obj):
    """Bütünlük manifesti / audit row_hash: sha256(kanonik JSON) — deterministik (sort_keys)."""
    payload = json.dumps(obj, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _model():
    return _load(MODEL_PATH)


def _router_isolation_ok(router_ctx, model):
    """ÇEKİRDEK router izolasyonu (C2): break-glass router AYRI ağaç — internal-only platform plane + dedicated scope.

    DOĞRU değer; degrade (inject) bunu build()'de bozar."""
    if not isinstance(router_ctx, dict):
        return False
    pol = model.get("router_policy", {})
    return (router_ctx.get("router_id") == pol.get("router_id")
            and router_ctx.get("plane") == pol.get("plane")
            and router_ctx.get("internal_only") is True
            and router_ctx.get("oauth_scope") == pol.get("oauth_scope")
            and router_ctx.get("plane") in pol.get("mount_planes", []))


def _token_state(token, access_tick):
    """Token durumu: 'missing' | 'resolved' | 'expired' | 'active' (12.3.2 RESİPROKAL; auto-expiry)."""
    if not isinstance(token, dict):
        return "missing"
    state = token.get("state")
    if state in RESOLVED_STATES:
        return "resolved"
    if state not in ACTIVE_STATES:
        return "missing"                                          # tanınmayan state → fail-closed
    expires_at = token.get("expires_at")
    if expires_at is not None and access_tick is not None and access_tick > expires_at:
        return "expired"                                          # auto-expiry (standing access yok)
    return "active"


def _token_bound(token, break_glass_id, target_tenant_id):
    """Token binding (C6; least-privilege): break_glass_id + target_tenant + tier=B'ye bağlı."""
    if not isinstance(token, dict):
        return False
    return (token.get("break_glass_id", break_glass_id) == break_glass_id
            and token.get("target_tenant_id", target_tenant_id) == target_tenant_id
            and token.get("tier", "B") == "B")


def _in_scope(token, resource_type, data_class):
    """Scope-limited routing (C7): istenen resource_type token.scope içinde + data_class=tenant_content + Tier B."""
    if not isinstance(token, dict):
        return False
    if data_class != CONTENT_CLASS:
        return False                                              # Tier B yalnız içerik
    scope = token.get("scope")
    if isinstance(scope, list):
        return resource_type in scope
    return False


def build(sample, spec, inject=None, model=None):
    """Tek BreakGlassRouterRequest senaryosunu yürüt → karar + ihlal sayaçları.

    Motor DOĞRU router admission davranışını hesaplar; inject (degrade) doğru davranışı bozar ve eşleşen ihlal
    sayacını artırır (12.1.x/12.2.x/12.3.x inject deseniyle birebir)."""
    inject = set(inject if inject is not None else sample.get("inject", []))
    model = model if model is not None else _model()

    request_id = sample.get("request_id")
    correlation_id = sample.get("correlation_id", request_id)
    break_glass_id = sample.get("break_glass_id", "bg-%s" % (request_id or "x"))
    actor_role = sample.get("actor_role")
    target_tenant_id = sample.get("target_tenant_id")
    tier = sample.get("tier", "B")
    resource_type = sample.get("resource_type")
    data_class = sample.get("data_class", "tenant_content")
    router_ctx = sample.get("router_context")                     # {router_id, plane, internal_only, oauth_scope}
    sanction_decision = sample.get("sanction_decision")           # 12.3.4 terminal (TÜKETİLİR)
    token = sample.get("token")                                   # 12.3.2 time-boxed token (TÜKETİLİR)
    access_tick = sample.get("access_tick", sample.get("now", 0)) # tick = dakika (Date.now YOK)

    v = {k: 0 for k in VIOLATION_KEYS}
    terminal = None
    note = None
    audit_emitted = True                                          # ÇEKİRDEK: doğru motor HER isteği audit'ler

    # ── C10 model bütünlük manifesti (frozen model) ──
    canonical_model = {
        "frozen": model.get("frozen"),
        "fail_closed": model.get("fail_closed"),
        "tier": model.get("tier"),
        "data_class": model.get("data_class"),
        "router_policy": model.get("router_policy"),
        "admission_policy": model.get("admission_policy"),
        "token_policy": model.get("token_policy"),
        "scope_policy": model.get("scope_policy"),
        "concurrency_policy": model.get("concurrency_policy"),
        "actor_roles": model.get("actor_roles"),
        "audit": model.get("audit"),
    }
    model_hash = _canon_hash(canonical_model)
    if "model_tamper" in inject:
        tampered = json.loads(json.dumps(canonical_model))
        tampered["router_policy"] = dict(tampered["router_policy"])
        tampered["router_policy"]["internal_only"] = False                       # internal-only kapat
        tampered["router_policy"]["oauth_scope"] = "panel:L0"                     # dedicated scope gevşet
        tampered["admission_policy"] = dict(tampered["admission_policy"])
        tampered["admission_policy"]["require_sanction_allow"] = False           # sanction zorunluluğunu kaldır
        tampered["audit"] = dict(tampered["audit"])
        tampered["audit"]["required_for_every_request"] = False                  # tam-audit kapat
        if _canon_hash(tampered) != model_hash:
            v["model_tampered"] += 1

    # ── malformed kapısı (fail-closed) ──
    malformed = (not request_id or actor_role not in PLATFORM_ROLES or not target_tenant_id
                 or tier != "B" or sanction_decision not in SANCTION_DECISIONS
                 or not isinstance(router_ctx, dict))

    isolation_ok = False
    token_st = "missing"
    bound_ok = False
    scope_ok = False
    reject_reason = None

    if malformed:
        terminal, note = "REJECT", "malformed"
    else:
        # ── DOĞRU admission değerlendirmesi (fail-closed sıralı) ──
        isolation_ok = _router_isolation_ok(router_ctx, model)
        token_st = _token_state(token, access_tick)
        bound_ok = _token_bound(token, break_glass_id, target_tenant_id)
        scope_ok = _in_scope(token, resource_type, data_class)
        sanctioned = sanction_decision == SANCTION_ALLOW

        if not isolation_ok:
            reject_reason = "router_isolation"
        elif not sanctioned:
            reject_reason = "not_sanctioned"
        elif token_st == "missing":
            reject_reason = "token_missing"
        elif token_st == "resolved":
            reject_reason = "token_resolved"
        elif token_st == "expired":
            reject_reason = "token_expired"
        elif not bound_ok:
            reject_reason = "token_misbound"
        elif not scope_ok:
            reject_reason = "out_of_scope"

        correct_admit = reject_reason is None
        admit = correct_admit

        # ── degrade: DOĞRU REJECT'i GÜVENSİZ ADMIT'e çevir + eşleşen ihlali artır ──
        if not isolation_ok and ("mount_on_tenant_plane" in inject or "wrong_router_scope" in inject):
            v["router_isolation_violation"] += 1                  # GÜVENSİZ: yanlış router/plane/scope servis edildi
            admit = True
        if not sanctioned and "admit_unsanctioned" in inject:
            v["unsanctioned_admission"] += 1                      # GÜVENSİZ: sanction≠ALLOW iken ADMIT
            admit = True
        if token_st == "missing" and "admit_without_token" in inject:
            v["unsanctioned_admission"] += 1                      # GÜVENSİZ: token'sız ADMIT (standing/sessiz)
            admit = True
        if token_st == "expired" and "admit_expired_token" in inject:
            v["expired_token_admission"] += 1                     # GÜVENSİZ: süresi dolmuş token ile ADMIT
            admit = True
        if token_st == "resolved" and "replay_token" in inject:
            v["token_replay"] += 1                                # GÜVENSİZ: çözülmüş token yeniden kullanıldı
            admit = True
        if not bound_ok and "admit_misbound_token" in inject:
            v["token_misbinding"] += 1                            # GÜVENSİZ: cross-tenant/cross-grant token
            admit = True
        if not scope_ok and "route_out_of_scope" in inject:
            v["out_of_scope_routing"] += 1                        # GÜVENSİZ: scope dışı/non-Tier-B yönlendirme
            admit = True

        if admit and correct_admit:
            terminal, note = "ADMIT", "routed"
        elif admit:
            terminal, note = "ADMIT", "unsafe_admit"
        else:
            terminal, note = "REJECT", reject_reason

    # ── C4 tam-audit: HER istek audit'lenir; degrade skip_audit → audit ATLA (sessiz erişim) ──
    if "skip_audit" in inject:
        audit_emitted = False
    if not audit_emitted:
        v["unaudited_request"] += 1                               # router'dan istek audit'siz geçti (tam-audit ihlali)

    # ── audit kaydı üret (ÇEKİRDEK: HER karar audit'lenir — malformed/reject/admit dahil) ──
    audit_record = _build_audit(
        record_id="aud-%s" % (request_id or "x"), break_glass_id=break_glass_id, correlation_id=correlation_id,
        actor_role=actor_role, actor_realm=model.get("actor_realm", "platform"),
        target_tenant_ref=target_tenant_id, data_class=data_class, resource_type=resource_type, tier=tier,
        router_id=(router_ctx or {}).get("router_id") if isinstance(router_ctx, dict) else None,
        oauth_scope=(router_ctx or {}).get("oauth_scope") if isinstance(router_ctx, dict) else None,
        plane=(router_ctx or {}).get("plane") if isinstance(router_ctx, dict) else None,
        decision=terminal, reject_reason=(note if terminal == "REJECT" else None),
        sanction_decision=sanction_decision, token_state=token_st, occurred_tick=access_tick)
    # ── degrade: audit kaydına ham PII/token sok ──
    if "leak_pii" in inject and audit_emitted:
        audit_record["pii_field_present"] = True                  # sentetik işaret (gerçek PII/token yazılmaz)
        v["audit_pii"] += 1
    # ── C9 audit immutability — emitilen kayıt değiştirilirse row_hash uyumsuz (WORM; 12.1.8 RESİPROKAL) ──
    if "mutate_audit" in inject and audit_emitted:
        audit_record["decision"] = "tampered"                     # hash sonrası alan değişimi
    if audit_emitted:
        recomputed = _canon_hash({k: val for k, val in audit_record.items() if k != "row_hash"})
        if recomputed != audit_record.get("row_hash"):
            v["audit_mutable"] += 1

    # ── C1 stuck state ──
    if terminal not in TERMINAL:
        v["stuck_state"] += 1

    # ── Kanıt (C1) ──
    evidence = _evidence(request_id, correlation_id, break_glass_id, actor_role, target_tenant_id, data_class,
                         resource_type, router_ctx, sanction_decision, token_st, isolation_ok, bound_ok, scope_ok,
                         tier, terminal, note, audit_emitted, model_hash)
    if (not request_id) or (terminal is None):
        v["missing_evidence"] += 1

    return _pack(sample, terminal, note, v, actor_role, target_tenant_id, data_class, resource_type, router_ctx,
                 sanction_decision, token_st, isolation_ok, bound_ok, scope_ok, tier, audit_emitted, audit_record,
                 model_hash, evidence)


def _build_audit(record_id, break_glass_id, correlation_id, actor_role, actor_realm, target_tenant_ref, data_class,
                 resource_type, tier, router_id, oauth_scope, plane, decision, reject_reason, sanction_decision,
                 token_state, occurred_tick):
    """PII/token-free, WORM uyumlu audit kaydı (12.1.8 RESİPROKAL): row_hash = sha256(kanonik içerik).

    token DEĞERİ DEĞİL — yalnız token_state ENUM (ACTIVE/CONSUMED/...) yazılır (FR-REC-004)."""
    rec = {
        "record_id": record_id,
        "break_glass_id": break_glass_id,
        "correlation_id": correlation_id,
        "actor_role": actor_role,
        "actor_realm": actor_realm,
        "target_tenant_ref": target_tenant_ref,
        "data_class": data_class,
        "resource_type": resource_type,
        "tier": tier,
        "router_id": router_id,
        "oauth_scope": oauth_scope,
        "plane": plane,
        "decision": decision,
        "reject_reason": reject_reason,
        "sanction_decision": sanction_decision,
        "token_state": token_state,
        "occurred_tick": occurred_tick,
    }
    rec["row_hash"] = _canon_hash(rec)
    return rec


def _evidence(request_id, correlation_id, break_glass_id, actor_role, target_tenant_id, data_class, resource_type,
              router_ctx, sanction_decision, token_state, isolation_ok, bound_ok, scope_ok, tier, terminal, note,
              audit_emitted, model_hash):
    return {
        "request_id": request_id,
        "correlation_id": correlation_id,
        "break_glass_id": break_glass_id,
        "actor_role": actor_role,
        "target_tenant_id": target_tenant_id,
        "data_class": data_class,
        "resource_type": resource_type,
        "router_id": (router_ctx or {}).get("router_id") if isinstance(router_ctx, dict) else None,
        "plane": (router_ctx or {}).get("plane") if isinstance(router_ctx, dict) else None,
        "oauth_scope": (router_ctx or {}).get("oauth_scope") if isinstance(router_ctx, dict) else None,
        "sanction_decision": sanction_decision,
        "token_state": token_state,
        "router_isolation_ok": isolation_ok,
        "token_bound": bound_ok,
        "in_scope": scope_ok,
        "tier": tier,
        "terminal": terminal,
        "note": note,
        "audit_emitted": audit_emitted,
        "model_hash": model_hash,
    }


def _pack(sample, terminal, note, v, actor_role, target_tenant_id, data_class, resource_type, router_ctx,
          sanction_decision, token_state, isolation_ok, bound_ok, scope_ok, tier, audit_emitted, audit_record,
          model_hash, evidence):
    return {
        "name": sample.get("name"),
        "terminal": terminal,
        "resolved": terminal in TERMINAL,
        "note": note,
        "actor_role": actor_role,
        "target_tenant_id": target_tenant_id,
        "data_class": data_class,
        "resource_type": resource_type,
        "router_id": (router_ctx or {}).get("router_id") if isinstance(router_ctx, dict) else None,
        "plane": (router_ctx or {}).get("plane") if isinstance(router_ctx, dict) else None,
        "oauth_scope": (router_ctx or {}).get("oauth_scope") if isinstance(router_ctx, dict) else None,
        "sanction_decision": sanction_decision,
        "token_state": token_state,
        "router_isolation_ok": isolation_ok,
        "token_bound": bound_ok,
        "in_scope": scope_ok,
        "tier": tier,
        "audit_emitted": audit_emitted,
        "audit_record": audit_record,
        "model_hash": model_hash,
        "evidence": evidence,
        "violations": v,
    }


def _gate_eval(result, gates):
    """Tek senaryo sonucunu HARD kapılara vur → (passed, fail_list)."""
    v = result["violations"]
    fails = []
    mapping = {
        "router_isolation_violation": "max_router_isolation_violation",
        "unsanctioned_admission": "max_unsanctioned_admission",
        "unaudited_request": "max_unaudited_request",
        "expired_token_admission": "max_expired_token_admission",
        "token_misbinding": "max_token_misbinding",
        "out_of_scope_routing": "max_out_of_scope_routing",
        "token_replay": "max_token_replay",
        "audit_pii": "max_audit_pii",
        "audit_mutable": "max_audit_mutable",
        "model_tampered": "max_model_tampered",
        "missing_evidence": "max_missing_evidence",
        "stuck_state": "max_stuck_state",
        "secret_or_pii": "max_secret_or_pii",
    }
    for vk, gk in mapping.items():
        limit = gates.get(gk, 0)
        if v.get(vk, 0) > limit:
            fails.append("%s=%d > %s=%d" % (vk, v[vk], gk, limit))
    if gates.get("require_terminal", True) and result["terminal"] not in TERMINAL:
        fails.append("terminal'e ulaşılmadı: %s" % result["terminal"])
    return (len(fails) == 0, fails)


# ════════════════════════════════════════════════════════════════════════════
def check_cmd(arg):
    spec = _load(SPEC_PATH)
    gates = spec["gates"]

    if os.path.isdir(arg):
        paths = sorted(os.path.join(arg, f) for f in os.listdir(arg) if f.endswith(".json"))
    else:
        paths = [arg]

    all_ok = True
    for p in paths:
        sample = _load(p)
        expect = sample.get("expect", "pass")
        res = build(sample, spec)
        with open(p, "r", encoding="utf-8") as fh:
            leaks = scan_leaks(fh.read())
        if leaks:
            res["violations"]["secret_or_pii"] += len(leaks)
        passed, fails = _gate_eval(res, gates)

        exp_assert = sample.get("expected", {})
        mism = []
        for key in ("terminal", "note", "token_state", "router_isolation_ok", "in_scope"):
            if key in exp_assert and exp_assert[key] != res.get(key):
                mism.append("%s: beklenen=%r gerçek=%r" % (key, exp_assert[key], res.get(key)))

        verdict_ok = (passed and not mism) if expect == "pass" else (not passed)
        all_ok = all_ok and verdict_ok
        icon = "🟢" if verdict_ok else "🔴"
        print("%s %s" % (icon, os.path.basename(p)))
        print("   terminal=%s note=%s sanction=%s token_state=%s isolation=%s scope=%s audit=%s"
              % (res["terminal"], res["note"], res["sanction_decision"], res["token_state"],
                 res["router_isolation_ok"], res["in_scope"], res["audit_emitted"]))
        nz = {k: val for k, val in res["violations"].items() if val}
        if nz:
            print("   ihlaller: %s" % nz)
        if expect == "pass" and fails:
            print("   ✗ kapı eler (beklenen geçer): %s" % "; ".join(fails))
        if expect == "fail" and passed:
            print("   ✗ kapı GEÇTİ (beklenen eler — degrade senaryo)")
        if mism and expect == "pass":
            print("   ✗ karar uyuşmazlığı: %s" % "; ".join(mism))
        if expect == "fail" and not passed:
            print("   ✓ beklendiği gibi elendi: %s" % "; ".join(fails[:3]))

    print("\ncheck: %s" % ("🟢 TÜM SENARYOLAR BEKLENDİĞİ GİBİ" if all_ok else "🔴 EN AZ BİR SENARYO BEKLENMEDİK"))
    return 0 if all_ok else 1


# ════════════════════════════════════════════════════════════════════════════
def validate():
    checks = []

    def chk(name, ok, detail=""):
        checks.append((name, ok, detail))

    spec = _load(SPEC_PATH)

    # 1) Üst-düzey alanlar
    for f in ("wbs", "phase", "priority", "trace", "placement", "rules", "decision",
              "outcomes", "model", "enforcement", "gates", "observability", "invariants", "no_secrets"):
        chk("spec.%s var" % f, f in spec)
    chk("wbs=12.3.5", spec.get("wbs") == "12.3.5")
    chk("phase=F2", spec.get("phase") == "F2")
    chk("priority=Must", spec.get("priority") == "Must")
    chk("placement fail_closed=true", spec.get("placement", {}).get("fail_closed") is True)

    # 2) İzlenebilirlik
    tr = spec.get("trace", {})
    chk("FR-IAM-009 izlenir (üç katmanlı break-glass — ÇEKİRDEK)", "FR-IAM-009" in tr.get("fr", []))
    chk("FR-IAM-008 izlenir (L0 iş verisi izolasyon)", "FR-IAM-008" in tr.get("fr", []))
    chk("FR-IAM-006 izlenir (tüm işlemler audit)", "FR-IAM-006" in tr.get("fr", []))
    chk("FR-REC-009 izlenir (erişim audit)", "FR-REC-009" in tr.get("fr", []))
    chk("FR-REC-004 izlenir (audit PII'siz)", "FR-REC-004" in tr.get("fr", []))
    chk("SR-IAM-009 izlenir", "SR-IAM-009" in tr.get("srs", []))
    chk("TC-IAM-009 izlenir", "TC-IAM-009" in tr.get("rtm", []))
    chk("SAD §14.4.2 ayrı/kısıtlı/tam-audit router izlenir (ÇEKİRDEK)",
        any("§14.4.2" in s for s in tr.get("sad", [])))
    chk("BRD §17 izlenir (altın kural; içeriğe erişim break-glass ile)", any("§17" in s for s in tr.get("brd", [])))
    chk("ADR-011 izlenir (Platform Control Plane internal-only + ayrı router/scope)",
        any(a.startswith("ADR-011") for a in tr.get("adr", [])))
    chk("ADR-013 izlenir (üç katmanlı break-glass)", any(a.startswith("ADR-013") for a in tr.get("adr", [])))
    chk("12.3.4 tier-b-approval TÜKETİLİR (sanction_decision RESİPROKAL)",
        any("12.3.4" in s for s in tr.get("consumes", [])))
    chk("12.3.2 tier-b TÜKETİLİR (time-boxed token RESİPROKAL)",
        any("12.3.2" in s for s in tr.get("consumes", [])))
    chk("12.2.2 router-scopes TÜKETİLİR (platform plane + scope_disjoint RESİPROKAL)",
        any("12.2.2" in s for s in tr.get("consumes", [])))
    chk("12.1.8 worm-audit TÜKETİLİR (WORM audit RESİPROKAL)",
        any("12.1.8" in s for s in tr.get("consumes", [])))

    # 3) Dokuz kural (çekirdek)
    rz = spec["rules"]
    rule_ids = [d["id"] for d in rz.get("list", [])]
    chk("dokuz kural tam", set(rule_ids) == set(RULES))
    chk("değerlendirme malformed→router_isolation→restricted_admission→token→scope→full_audit",
        rz.get("evaluation") == "malformed_then_router_isolation_then_restricted_admission_then_token_then_scope_then_full_audit")
    for d in rz.get("list", []):
        chk("kural %s invariant taşır" % d["id"], d.get("invariant") in INVARIANT_IDS)

    # 4) Karar
    dec = spec["decision"]
    chk("karar default=REJECT (fail-closed)", dec.get("default") == "REJECT")
    chk("fail_safe no access", "no access" in dec.get("fail_safe_terminal", "").lower()
        or "erişim" in dec.get("fail_safe_terminal", "").lower())

    # 5) Sonuçlar
    oc = spec["outcomes"]
    chk("terminal sonuçlar ADMIT/REJECT", set(oc.get("list", [])) == TERMINAL)

    # 6) Enforcement — router izolasyonu + kısıtlı admission + tam-audit
    en = spec["enforcement"]
    chk("router_isolation AYRI ağaç + internal-only platform plane + dedicated break-glass scope",
        ("internal-only" in en.get("router_isolation", "").lower() or "internal_only" in en.get("router_isolation", "").lower())
        and "panel:L0:break_glass" in en.get("router_isolation", "")
        and "platform_control_plane" in en.get("router_isolation", ""))
    chk("restricted_admission sanction=ALLOW + geçerli token + no standing access",
        "ALLOW" in en.get("restricted_admission", "")
        and "token" in en.get("restricted_admission", "").lower()
        and ("standing" in en.get("restricted_admission", "").lower()))
    chk("full_audit HER istek WORM (12.1.8 RESİPROKAL)",
        ("her istek" in en.get("full_audit", "").lower() or "HER istek" in en.get("full_audit", ""))
        and "WORM" in en.get("full_audit", "").upper() and "12.1.8" in en.get("full_audit", ""))

    # 7) Model alanları
    md = spec["model"]
    chk("model tier=B", md.get("tier") == "B")
    chk("model data_class=tenant_content", md.get("data_class") == "tenant_content")
    chk("model router_id=break_glass", md.get("router_id") == "break_glass")
    chk("model plane=platform_control_plane + internal_only", md.get("plane") == "platform_control_plane" and md.get("internal_only") is True)
    chk("model oauth_scope=panel:L0:break_glass", md.get("oauth_scope") == "panel:L0:break_glass")
    chk("model sanction_allow_value=ALLOW", md.get("sanction_allow_value") == "ALLOW")
    chk("model actor_roles = L0 platform rolleri", set(md.get("actor_roles", [])) == PLATFORM_ROLES)

    # 8) Kapılar — tüm sıfır-eşik ihlal kapıları
    g = spec["gates"]
    for gk in ("max_router_isolation_violation", "max_unsanctioned_admission", "max_unaudited_request",
               "max_expired_token_admission", "max_token_misbinding", "max_out_of_scope_routing",
               "max_token_replay", "max_audit_pii", "max_audit_mutable", "max_model_tampered",
               "max_missing_evidence", "max_stuck_state", "max_secret_or_pii"):
        chk("kapı %s=0" % gk, g.get(gk) == 0)
    chk("require_terminal", g.get("require_terminal") is True)

    # 9) Gözlemlenebilirlik — kardinalite disiplini (0.4.7)
    obs = spec["observability"]
    chk("l0_break_glass_router_total metrik", "l0_break_glass_router_total" in obs.get("metrics", []))
    chk("break_glass_router_violation_total metrik (alarm)", "break_glass_router_violation_total" in obs.get("metrics", []))
    hi = set(obs.get("high_cardinality_trace_only", []))
    lo = set(obs.get("low_cardinality_labels", []))
    chk("break_glass_id/target_tenant_id YÜKSEK kard (label değil)",
        "break_glass_id" in hi and "break_glass_id" not in lo and "target_tenant_id" in hi)
    chk("actor_role/decision/result/plane DÜŞÜK kard",
        all(x in lo for x in ("actor_role", "decision", "result", "plane")))
    chk("alarm unsanctioned_admission/router_isolation_violation/unaudited_request ≤2dk",
        any(x in obs.get("alarm", "") for x in ("unsanctioned_admission", "router_isolation_violation", "unaudited_request")))

    # 10) İnvariant'lar C1–C12
    inv_ids = [i["id"] for i in spec["invariants"]]
    chk("invariant'lar C1–C12 tam", inv_ids == INVARIANT_IDS)

    # 11) Model dosyası + içsel tutarlılık (SAD §14.4.2 / FR-IAM-009)
    mm_ok = os.path.exists(MODEL_PATH)
    chk("config/break-glass-router-model.json var", mm_ok)
    if mm_ok:
        mm = _model()
        chk("model frozen=true", mm.get("frozen") is True)
        chk("model fail_closed=true", mm.get("fail_closed") is True)
        chk("model tier=B + data_class=tenant_content",
            mm.get("tier") == "B" and mm.get("data_class") == "tenant_content")
        rp = mm.get("router_policy", {})
        chk("model router_policy router_id=break_glass + plane=platform_control_plane + internal_only + dedicated scope",
            rp.get("router_id") == "break_glass" and rp.get("plane") == "platform_control_plane"
            and rp.get("internal_only") is True and rp.get("oauth_scope") == "panel:L0:break_glass")
        chk("model router_policy scope_disjoint_from panel:L0/L1/L2 + mount yalnız platform_control_plane",
            set(rp.get("scope_disjoint_from", [])) == {"panel:L0", "panel:L1", "panel:L2"}
            and rp.get("mount_planes", []) == ["platform_control_plane"]
            and rp.get("separate_router_tree") is True)
        ap = mm.get("admission_policy", {})
        chk("model admission_policy require_sanction_allow + require_valid_token + no_standing_access + sanction=ALLOW",
            ap.get("require_sanction_allow") is True and ap.get("require_valid_token") is True
            and ap.get("no_standing_access") is True and ap.get("sanction_allow_value") == "ALLOW")
        tp = mm.get("token_policy", {})
        chk("model token_policy active=ACTIVE + resolved=CONSUMED/REVOKED/EXPIRED + binding",
            set(tp.get("active_states", [])) == ACTIVE_STATES
            and set(tp.get("resolved_states", [])) == RESOLVED_STATES
            and tp.get("bind_break_glass_id") is True and tp.get("bind_target_tenant") is True
            and tp.get("bind_tier_b") is True and tp.get("bind_scope") is True)
        sp = mm.get("scope_policy", {})
        chk("model scope_policy tier_b_only + content_class=tenant_content",
            sp.get("confine_to_token_scope") is True and sp.get("tier_b_only") is True
            and sp.get("content_class") == "tenant_content")
        chk("model audit required_for_every_request=true + worm=true + no_raw_token=true + no_raw_pii=true",
            mm.get("audit", {}).get("required_for_every_request") is True
            and mm.get("audit", {}).get("worm") is True
            and mm.get("audit", {}).get("no_raw_token") is True
            and mm.get("audit", {}).get("no_raw_pii") is True)
        chk("model audit record token_state (DEĞER değil enum) + router_id + decision alanları; HAM token alanı YOK",
            all(f in mm.get("audit", {}).get("record_fields", []) for f in ("token_state", "router_id", "decision", "break_glass_id"))
            and "token_value" not in mm.get("audit", {}).get("record_fields", []))
        chk("model concurrency resolved_states = CONSUMED/REVOKED/EXPIRED (replay-safe)",
            set(mm.get("concurrency_policy", {}).get("resolved_states", [])) == RESOLVED_STATES)
        chk("model actor_roles = L0 platform rolleri", set(mm.get("actor_roles", [])) == PLATFORM_ROLES)
        chk("model terminal ADMIT/REJECT + default REJECT",
            set(mm.get("terminal", [])) == TERMINAL and mm.get("default") == "REJECT")

    # 12) 12.3.4 RESİPROKAL — sanction_decision TÜKETİLİR
    ap_ok = os.path.exists(APPROVAL_MODEL_PATH)
    chk("12.3.4 ../break-glass-tier-b-approval/config/tier-b-approval-model.json var (sanction_decision — TÜKETİLİR)", ap_ok)
    if ap_ok:
        apm = _load(APPROVAL_MODEL_PATH)
        chk("12.3.4 terminal ALLOW üretir (bu router yalnız ALLOW'da ADMIT; sanction_decision RESİPROKAL)",
            SANCTION_ALLOW in apm.get("terminal", []))
        chk("12.3.4 tier=B + data_class=tenant_content = bu modül (RESİPROKAL)",
            apm.get("tier") == "B" and apm.get("data_class") == "tenant_content")

    # 13) 12.3.2 RESİPROKAL — time-boxed token TÜKETİLİR
    tb_ok = os.path.exists(TIER_B_MODEL_PATH)
    chk("12.3.2 ../break-glass-tier-b/config/tier-b-model.json var (time-boxed token — TÜKETİLİR)", tb_ok)
    if tb_ok:
        tb = _load(TIER_B_MODEL_PATH)
        chk("12.3.2 timebox default 60 / max 240 / auto_expiry / no_standing (RESİPROKAL token doğrulama)",
            tb.get("timebox_policy", {}).get("default_ttl_minutes") == 60
            and tb.get("timebox_policy", {}).get("max_ttl_minutes") == 240
            and tb.get("timebox_policy", {}).get("auto_expiry") is True
            and tb.get("timebox_policy", {}).get("no_standing_access") is True)
        chk("12.3.2 concurrency resolved_states = CONSUMED/REVOKED/EXPIRED (RESİPROKAL replay-safe)",
            set(tb.get("concurrency_policy", {}).get("resolved_states", [])) == RESOLVED_STATES)
        chk("12.3.2 token_binding bind_target_tenant + bind_tier_b + bind_scope (RESİPROKAL)",
            tb.get("token_binding", {}).get("bind_target_tenant") is True
            and tb.get("token_binding", {}).get("bind_tier_b") is True
            and tb.get("token_binding", {}).get("bind_scope") is True)

    # 14) 12.2.2 RESİPROKAL — break-glass router AYRI/EK dördüncü ağaç (platform plane + scope_disjoint)
    rt_ok = os.path.exists(ROUTER_TOPO_PATH)
    chk("12.2.2 ../router-scopes/config/router-topology.json var (router topolojisi — TÜKETİLİR)", rt_ok)
    if rt_ok and mm_ok:
        rt = _load(ROUTER_TOPO_PATH)
        pcp = rt.get("planes", {}).get("platform_control_plane", {})
        chk("12.2.2 platform_control_plane internal_only=true (break-glass router AYNI internal-only düzlemde RESİPROKAL)",
            pcp.get("internal_only") is True and pcp.get("public") is False)
        chk("12.2.2 scope_disjoint=true (break-glass scope panel:L0:break_glass disjoint RESİPROKAL)",
            rt.get("scope_disjoint") is True)
        chk("12.2.2 L0 ağacı platform_control_plane'de (break-glass router AYRI/EK dördüncü ağaç aynı düzlemde)",
            rt.get("router_trees", {}).get("L0", {}).get("plane") == "platform_control_plane"
            and _model().get("router_policy", {}).get("plane") == "platform_control_plane")

    # 15) 12.1.8 RESİPROKAL — WORM audit (append-only + hash-zincir)
    wm_ok = os.path.exists(WORM_MODEL_PATH)
    chk("12.1.8 ../worm-audit/config/worm-audit-model.json var (WORM audit — TÜKETİLİR)", wm_ok)
    if wm_ok:
        wm = _load(WORM_MODEL_PATH)
        chk("12.1.8 worm_policy append_only=true (RESİPROKAL audit immutability)",
            wm.get("worm_policy", {}).get("append_only") is True)
        chk("12.1.8 integrity_policy hash_chain + sha256 (RESİPROKAL row_hash)",
            wm.get("integrity_policy", {}).get("hash_chain") is True
            and wm.get("integrity_policy", {}).get("hash_algo") == "sha256")

    # 16) 12.1.1 RESİPROKAL — L0 platform aktör rolleri
    rb_ok = os.path.exists(RBAC_MODEL_PATH)
    chk("12.1.1 ../rbac-model/config/rbac-roles.json var (L0 aktör rolleri — TÜKETİLİR)", rb_ok)
    if rb_ok:
        rbac = _load(RBAC_MODEL_PATH)
        roles = rbac.get("roles", {})
        chk("12.1.1 L0 platform aktör rolleri (owner/sre/billing) mevcut + platform realm (RESİPROKAL)",
            all(role in roles for role in PLATFORM_ROLES)
            and all(roles.get(role, {}).get("realm") == "platform" for role in PLATFORM_ROLES))

    # 17) Sır/PII/token tarayıcı — spec + model + samples
    scan_files = [SPEC_PATH, MODEL_PATH] + (
        [os.path.join(SAMPLES_DIR, f) for f in os.listdir(SAMPLES_DIR) if f.endswith(".json")]
        if os.path.isdir(SAMPLES_DIR) else [])
    total_leaks = 0
    for p in scan_files:
        if not os.path.exists(p):
            continue
        with open(p, "r", encoding="utf-8") as fh:
            hits = scan_leaks(fh.read())
        if hits:
            total_leaks += len(hits)
            chk("sızıntı yok: %s" % os.path.basename(p), False, str(hits[:2]))
    chk("hiç ham-içerik/PII/token sızıntısı yok (C12)", total_leaks == 0)

    # 18) Samples — ≥1 pass + ≥1 fail
    if os.path.isdir(SAMPLES_DIR):
        sample_files = sorted(f for f in os.listdir(SAMPLES_DIR) if f.endswith(".json"))
        chk("≥1 pass + ≥1 fail örnek (degrade ispatı)", _has_both(sample_files))

    npass = sum(1 for _, ok, _ in checks if ok)
    for name, ok, detail in checks:
        line = ("  ✓ " if ok else "  ✗ ") + name
        if not ok and detail:
            line += "  → " + detail
        print(line)
    total = len(checks)
    print("\nvalidate: %d/%d %s" % (npass, total, "🟢" if npass == total else "🔴"))
    return 0 if npass == total else 1


def _has_both(sample_files):
    have_pass = have_fail = False
    for f in sample_files:
        s = _load(os.path.join(SAMPLES_DIR, f))
        if s.get("expect", "pass") == "pass":
            have_pass = True
        else:
            have_fail = True
    return have_pass and have_fail


# ════════════════════════════════════════════════════════════════════════════
def selftest():
    results = []

    def case(name, cond):
        results.append((bool(cond), name))

    spec = _load(SPEC_PATH)
    G = spec["gates"]

    def rctx(**kw):
        d = {"router_id": "break_glass", "plane": "platform_control_plane",
             "internal_only": True, "oauth_scope": "panel:L0:break_glass"}
        d.update(kw)
        return d

    def tok(**kw):
        d = {"break_glass_id": "bg-1", "target_tenant_id": "t-acme", "tier": "B",
             "scope": ["transcript"], "granted_at": 100, "expires_at": 160, "state": "ACTIVE"}
        d.update(kw)
        return d

    def ev(**kw):
        # Varsayılan: platform_owner, transcript, dedicated break-glass router/plane/scope, sanction=ALLOW,
        # geçerli ACTIVE token (bound + scope kapsar + unexpired) → ADMIT (routed) + audit.
        d = {
            "request_id": "req-1", "correlation_id": "corr-1", "break_glass_id": "bg-1",
            "actor_role": "platform_owner", "target_tenant_id": "t-acme", "tier": "B",
            "resource_type": "transcript", "data_class": "tenant_content",
            "router_context": rctx(), "sanction_decision": "ALLOW", "token": tok(), "access_tick": 120,
        }
        d.update(kw)
        return d

    # 1) happy — ayrı router + sanction=ALLOW + geçerli token + scope-içi → ADMIT, ihlal yok
    r = build(ev(), spec)
    case("happy: ADMIT (ayrı router + sanction=ALLOW + geçerli token + scope-içi)", r["terminal"] == "ADMIT" and r["note"] == "routed")
    case("happy: router_isolation_ok=True", r["router_isolation_ok"] is True)
    case("happy: token_state=active + in_scope=True", r["token_state"] == "active" and r["in_scope"] is True)
    case("happy: audit_emitted=True + row_hash var (WORM)",
         r["audit_emitted"] is True and r["audit_record"].get("row_hash") is not None)
    case("happy: break_glass_id audit'te + token_state enum (DEĞER değil)",
         r["audit_record"].get("break_glass_id") is not None and r["audit_record"].get("token_state") == "active")
    case("happy: model_hash var (C10)", r["model_hash"] is not None)
    case("happy: ihlal yok", all(x == 0 for x in r["violations"].values()))
    case("happy: kapı geçer", _gate_eval(r, G)[0] is True)

    # 2) determinizm
    r1, r2 = build(ev(), spec), build(ev(), spec)
    case("determinizm: birebir", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))
    case("model_hash deterministik", r1["model_hash"] == r2["model_hash"])

    # 3) C2 ÇEKİRDEK router izolasyonu — yanlış plane/scope → REJECT; degrade → router_isolation_violation
    rtenant = build(ev(router_context=rctx(plane="tenant_application_plane")), spec)
    case("isolation: tenant düzleminde → REJECT (router_isolation)",
         rtenant["terminal"] == "REJECT" and rtenant["note"] == "router_isolation")
    case("isolation: doğru → router_isolation_violation=0 + kapı geçer",
         rtenant["violations"]["router_isolation_violation"] == 0 and _gate_eval(rtenant, G)[0] is True)
    rscope = build(ev(router_context=rctx(oauth_scope="panel:L0")), spec)
    case("isolation: yanlış scope (panel:L0) → REJECT (router_isolation)",
         rscope["terminal"] == "REJECT" and rscope["note"] == "router_isolation")
    rmount = build(ev(router_context=rctx(plane="tenant_application_plane")), spec, inject=["mount_on_tenant_plane"])
    case("isolation degrade: mount_on_tenant_plane → router_isolation_violation>0 + ADMIT + kapı eler",
         rmount["violations"]["router_isolation_violation"] > 0 and rmount["terminal"] == "ADMIT"
         and _gate_eval(rmount, G)[0] is False)
    rwscope = build(ev(router_context=rctx(oauth_scope="panel:L1")), spec, inject=["wrong_router_scope"])
    case("isolation degrade: wrong_router_scope → router_isolation_violation>0 + kapı eler",
         rwscope["violations"]["router_isolation_violation"] > 0 and _gate_eval(rwscope, G)[0] is False)

    # 4) C3 ÇEKİRDEK kısıtlı admission — sanction≠ALLOW / token yok → REJECT; degrade → unsanctioned_admission
    rhold = build(ev(sanction_decision="HOLD"), spec)
    case("admission: sanction=HOLD → REJECT (not_sanctioned)",
         rhold["terminal"] == "REJECT" and rhold["note"] == "not_sanctioned")
    rblock = build(ev(sanction_decision="BLOCK"), spec)
    case("admission: sanction=BLOCK → REJECT + audit'li (her istek)",
         rblock["terminal"] == "REJECT" and rblock["audit_emitted"] is True)
    rnotok = build(ev(token=None), spec)
    case("admission: token yok → REJECT (token_missing)",
         rnotok["terminal"] == "REJECT" and rnotok["note"] == "token_missing")
    runsanc = build(ev(sanction_decision="HOLD"), spec, inject=["admit_unsanctioned"])
    case("admission degrade: admit_unsanctioned → ADMIT + unsanctioned_admission>0 + kapı eler",
         runsanc["terminal"] == "ADMIT" and runsanc["violations"]["unsanctioned_admission"] > 0
         and _gate_eval(runsanc, G)[0] is False)
    rnotoken = build(ev(token=None), spec, inject=["admit_without_token"])
    case("admission degrade: admit_without_token → ADMIT + unsanctioned_admission>0 + kapı eler",
         rnotoken["terminal"] == "ADMIT" and rnotoken["violations"]["unsanctioned_admission"] > 0
         and _gate_eval(rnotoken, G)[0] is False)

    # 5) C4 ÇEKİRDEK tam-audit — her istek audit'li; degrade skip_audit → unaudited_request
    case("audit: REJECT de audit'lenir (her break-glass router isteği)", rhold["audit_emitted"] is True)
    rskip = build(ev(), spec, inject=["skip_audit"])
    case("audit degrade: skip_audit → unaudited_request>0 + audit_emitted=False + kapı eler",
         rskip["violations"]["unaudited_request"] > 0 and rskip["audit_emitted"] is False
         and _gate_eval(rskip, G)[0] is False)

    # 6) C5 token expiry — access_tick>expires_at → REJECT; degrade → expired_token_admission
    rexp = build(ev(access_tick=200), spec)  # expires_at=160
    case("expiry: access_tick>expires_at → REJECT (token_expired)",
         rexp["terminal"] == "REJECT" and rexp["note"] == "token_expired" and rexp["token_state"] == "expired")
    rexpadm = build(ev(access_tick=200), spec, inject=["admit_expired_token"])
    case("expiry degrade: admit_expired_token → ADMIT + expired_token_admission>0 + kapı eler",
         rexpadm["terminal"] == "ADMIT" and rexpadm["violations"]["expired_token_admission"] > 0
         and _gate_eval(rexpadm, G)[0] is False)

    # 7) C6 token binding — cross-tenant token → REJECT; degrade → token_misbinding
    rmis = build(ev(token=tok(target_tenant_id="t-other")), spec)
    case("binding: cross-tenant token → REJECT (token_misbound)",
         rmis["terminal"] == "REJECT" and rmis["note"] == "token_misbound")
    rmisadm = build(ev(token=tok(break_glass_id="bg-other")), spec, inject=["admit_misbound_token"])
    case("binding degrade: admit_misbound_token → ADMIT + token_misbinding>0 + kapı eler",
         rmisadm["terminal"] == "ADMIT" and rmisadm["violations"]["token_misbinding"] > 0
         and _gate_eval(rmisadm, G)[0] is False)

    # 8) C7 scope-limited — scope dışı resource → REJECT; degrade → out_of_scope_routing
    roos = build(ev(resource_type="recording"), spec)  # token.scope=[transcript]
    case("scope: scope dışı resource → REJECT (out_of_scope)",
         roos["terminal"] == "REJECT" and roos["note"] == "out_of_scope" and roos["in_scope"] is False)
    roosadm = build(ev(resource_type="recording"), spec, inject=["route_out_of_scope"])
    case("scope degrade: route_out_of_scope → ADMIT + out_of_scope_routing>0 + kapı eler",
         roosadm["terminal"] == "ADMIT" and roosadm["violations"]["out_of_scope_routing"] > 0
         and _gate_eval(roosadm, G)[0] is False)
    rnoncontent = build(ev(data_class="tenant_metric"), spec)
    case("scope: non-Tier-B (tenant_metric) → REJECT (out_of_scope; Tier B yalnız içerik)",
         rnoncontent["terminal"] == "REJECT" and rnoncontent["note"] == "out_of_scope")

    # 9) C8 replay-safe — çözülmüş token → REJECT; degrade → token_replay
    rres = build(ev(token=tok(state="CONSUMED")), spec)
    case("replay: CONSUMED token → REJECT (token_resolved)",
         rres["terminal"] == "REJECT" and rres["note"] == "token_resolved" and rres["token_state"] == "resolved")
    rrep = build(ev(token=tok(state="REVOKED")), spec, inject=["replay_token"])
    case("replay degrade: replay_token → ADMIT + token_replay>0 + kapı eler",
         rrep["terminal"] == "ADMIT" and rrep["violations"]["token_replay"] > 0
         and _gate_eval(rrep, G)[0] is False)

    # 10) C9 audit immutability + PII-free
    rleak = build(ev(), spec, inject=["leak_pii"])
    case("audit degrade: leak_pii → audit_pii>0 + kapı eler",
         rleak["violations"]["audit_pii"] > 0 and _gate_eval(rleak, G)[0] is False)
    rmut = build(ev(), spec, inject=["mutate_audit"])
    case("audit degrade: mutate_audit → audit_mutable>0 (WORM ihlali) + kapı eler",
         rmut["violations"]["audit_mutable"] > 0 and _gate_eval(rmut, G)[0] is False)

    # 11) C10 model integrity
    rtam = build(ev(), spec, inject=["model_tamper"])
    case("model degrade: model_tamper → model_tampered>0 + kapı eler",
         rtam["violations"]["model_tampered"] > 0 and _gate_eval(rtam, G)[0] is False)

    # 12) C1 malformed → REJECT (fail-closed) + audit'li
    rmal = build(ev(actor_role="tenant_owner"), spec)  # L0 değil
    case("malformed: actor L0 değil → REJECT (malformed) + audit'li",
         rmal["terminal"] == "REJECT" and rmal["note"] == "malformed" and rmal["audit_emitted"] is True)
    rtier = build(ev(tier="A"), spec)
    case("malformed: tier≠B → REJECT (malformed)", rtier["terminal"] == "REJECT" and rtier["note"] == "malformed")
    rnoctx = build(ev(router_context=None), spec)
    case("malformed: router_context yok → REJECT (malformed)",
         rnoctx["terminal"] == "REJECT" and rnoctx["note"] == "malformed")

    # 13) C12 sızıntı tarayıcı
    case("scan_leaks temiz metinde 0", len(scan_leaks('{"actor_role":"platform_owner","router_id":"break_glass"}')) == 0)

    npass = sum(1 for ok, _ in results if ok)
    for ok, name in results:
        print(("  ✓ " if ok else "  ✗ ") + name)
    total = len(results)
    print("\nselftest: %d/%d %s" % (npass, total, "🟢" if npass == total else "🔴"))
    return 0 if npass == total else 1


# ════════════════════════════════════════════════════════════════════════════
def schema_cmd():
    out = {
        "wbs": "12.3.5",
        "title": "Break-glass tam-audit router (ayrı, kısıtlı)",
        "terminal": sorted(TERMINAL),
        "default": "REJECT (fail-closed)",
        "event_fields": ["name", "request_id", "correlation_id", "break_glass_id",
                         "actor_role(platform_owner|platform_sre|platform_billing)", "target_tenant_id", "tier(B)",
                         "resource_type", "data_class(tenant_content)",
                         "router_context{router_id(break_glass),plane(platform_control_plane),internal_only(bool),oauth_scope(panel:L0:break_glass)}",
                         "sanction_decision(ALLOW|HOLD|BLOCK — 12.3.4 terminal)",
                         "token{break_glass_id,target_tenant_id,tier,scope[],granted_at,expires_at,state(ACTIVE|CONSUMED|REVOKED|EXPIRED)} — 12.3.2",
                         "access_tick(tick=dakika)", "inject[]", "expect", "expected{}"],
        "injections (degrade testi)": sorted(INJECTIONS),
        "decision_fields": ["terminal(ADMIT|REJECT)", "note", "actor_role", "target_tenant_id", "data_class",
                            "resource_type", "router_id", "plane", "oauth_scope", "sanction_decision", "token_state",
                            "router_isolation_ok", "token_bound", "in_scope", "tier", "audit_emitted", "audit_record",
                            "model_hash", "evidence"],
        "violations": VIOLATION_KEYS,
        "invariants": INVARIANT_IDS,
        "model": "config/break-glass-router-model.json (frozen — router_policy[router_id=break_glass + "
                 "plane=platform_control_plane + internal_only + oauth_scope=panel:L0:break_glass + scope_disjoint + "
                 "mount_planes] + admission_policy[require_sanction_allow + require_valid_token + no_standing_access] + "
                 "token_policy[active/resolved_states + binding] + scope_policy[tier_b_only + content_class] + "
                 "concurrency_policy[replay-safe] + audit[WORM,PII/token-free] + actor_roles)",
        "consumes": "12.3.4 tier-b-approval (sanction_decision ALLOW/HOLD/BLOCK — yalnız ALLOW ADMIT RESİPROKAL); "
                    "12.3.2 tier-b (time-boxed token [60/240/auto-expiry/no-standing] + binding + resolved_states "
                    "RESİPROKAL); 12.2.2 router-scopes (platform plane internal_only + scope_disjoint — AYRI/EK ağaç "
                    "RESİPROKAL); 12.1.8 worm-audit (append-only/WORM + hash-zincir RESİPROKAL); 12.1.1 rbac-model "
                    "(L0 aktör rolleri); SAD §14.4.2 + BRD §17 + FR-IAM-009 (kaynak doğruluk)",
        "consumed_by": "1.x F1/F2 kod (FastAPI break-glass router: ayrı router ağacı + internal-only Platform Control "
                       "Plane mount + dedicated break-glass OAuth scope + admission + scope-limited routing + WORM "
                       "audit yazımı); 0.4.7 gözlemlenebilirlik",
        "trace": "SAD §14.4.2, FR-IAM-009, FR-IAM-008, FR-IAM-006, FR-REC-009, FR-REC-004, FR-TEN-002, BRD §17, "
                 "ADR-011, ADR-013, 12.3.4, 12.3.2, 12.2.2, 12.1.8, 12.1.1",
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd = argv[1]
    if cmd == "validate":
        return validate()
    if cmd == "check":
        if len(argv) < 3:
            print("kullanım: break_glass_router_probe.py check <sample.json|dizin>")
            return 2
        return check_cmd(argv[2])
    if cmd == "selftest":
        return selftest()
    if cmd == "schema":
        return schema_cmd()
    print("bilinmeyen komut: %s" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
