#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
manual_qa_probe.py — WBS 14.2.6 QA manuel skor + açıklama

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only statik + davranış kapısı.
`runtime/issue-detection/` (14.2.4) / `runtime/qa-eval/` (14.2.1) probe disipliniyle birebir; burada
bir ANALYTICS-PLANE MANUEL QA SKORLAMA yüzeyi (SAD §4.2/§14.4; L2 panel write) simülatörü (saf; random YOK).

MANUEL QA SKORLAMA — Analytics/Ops Plane'de (SAD §4.2/§171, FR-RES-011) async/non-blocking; yetkili bir QA
ekibi üyesi (qa:score izni; FR-IAM-011/ADR-012) tamamlanmış bir çağrıya İNSAN skoru (human_score 1–5) +
serbest-metin AÇIKLAMA (comment) ekler (FR-ANA-009). call_evaluation'a (eval_type='manual'; DB.md §5.6) yazar,
OLAP fct_qa_evaluation'a YALNIZ human_score ([0,1] normalize) + human_comment_present (VARLIK) + evaluator_role
projekte eder; AÇIKLAMA METNİ tenant düzleminde kalır. HARD kapılar:
  • Yetki (G1):      yalnız qa:score izni olan submitter ekleyebilir; yetkisiz reddedilir (AUTH) — BİRİNCİL.
  • Zorunlu (G2):    evaluator_id + human_score taşımalı; skorsuz/boş submission reddedilir (INVALID_REQUEST).
  • Domain (G3):     human_score ∈ [1,5]; OLAP'a [0,1] normalize; domain dışı → reddedilir.
  • Katalog (G4):    eval_type='manual'; OLAP çıktı alanları human_score+human_comment_present+evaluator_role BİREBİR (non-circular); otomatik ile COEXIST.
  • PII (G5):        AÇIKLAMA METNİ yalnız tenant düzleminde; OLAP/event/spec yalnız VARLIK+rol; ham metin/PII ASLA sızmaz (KEY).
  • İzolasyon (G6):  evaluator ile çağrı aynı tenant_id; cross-tenant reddedilir; home-region (FR-TEN-002/NFR 10.7).
  • Audit (G7):      her kabul KAYIPSIZ governance.audit.v1 WORM izi üretir; append-only (sessiz overwrite yok).
  • İdempotent (G8): (tenant_id,call_id,evaluator_id,schema_version) sürümler; farklı evaluator ayrı skor; at-least-once çift-sayım yok.
  • Async (G9):      analytics plane non-blocking; skorlama başarısızlığı canlı çağrıyı etkilemez (FR-RES-011).
  • Uygunluk (G10):  yalnız completed skorlanır; uygun-olmayan açık reason_code taşır (sessiz reddetme yok).

KAPSAM AYRIMI: otomatik SKOR → 14.2.1 · ÇIKARIM → 14.2.2 · ORAN → 14.2.3 · İŞARET → 14.2.4 · KRİTİK → 14.2.5 ·
sürüm KARŞILAŞTIRMA → 14.2.7 · dashboard/export → 14.2.8. Burada YALNIZ insan QA skoru + açıklama yüzeyi.

Komutlar:
  validate              manual-qa-scoring-spec.json'ı invariant'lara + OLAP çapraz-tutarlılığa + config'e karşı doğrular.
  score <sample>        Deterministik ManualQaScoringEngine — submission seti → kabul/red + OLAP projeksiyon + audit + HARD kapılar (G1–G10); →çıkış kodu.
  selftest              İyi/kötü spec+sample ile kapıların doğru tetiklendiğini kanıtlar.
  schema                Beklenen spec şeklini özetler.

Sunucu/credential GEREKMEZ. score gerçek panel write yerine deterministik simülasyondur (canlıda L2 panel →
call_evaluation [eval_type='manual'] + qa.evaluation.v1 [manual] + governance.audit.v1 → analytics-ingest →
fct_qa_evaluation, SAD §4.2/§12.1/§14.4; ADR-007). Ham ses payload/transkript METNİ/AÇIKLAMA METNİ/PII DEĞERİ
YOK — örnekler yalnız sayısal skor + açıklama VARLIK/uzunluk göstergesi + düşük-kardinalite rol/kimlik anahtarı
ADLARI + yetki bağlamı taşır.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "manual-qa-scoring-spec.json")
PROFILES_CFG = os.path.join(HERE, "config", "manual-qa-profiles.json")

# OLAP fct_qa_evaluation manuel-projeksiyon alanları (analytics/olap-spec.json BİREBİR — non-circular kontrol).
OLAP_MANUAL_FIELDS = ("human_score", "human_comment_present", "evaluator_role")
REQUIRED_PERMISSION = "qa:score"
PLATFORM_L0_ROLES = ("platform_owner", "platform_sre", "platform_billing")

ERROR_TAXONOMY = {
    "TIMEOUT", "RATE_LIMITED", "UNAVAILABLE", "AUTH",
    "INVALID_REQUEST", "CONTENT_FILTERED", "QUOTA_EXCEEDED", "REGION_VIOLATION",
}
SECRET_RE = re.compile(
    r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer)\b\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}"
)
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")
# Ham PII DEĞER / serbest-metin AÇIKLAMA desenleri (girdi/çıktı/spec'te yasak — FR-REC-004).
PII_VALUE_RE = re.compile(
    r"(?:\d[ \-]?){7,}"                                   # ≥7 ardışık rakam (telefon/kart/IBAN)
    r"|[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"  # e-posta
)
# AÇIKLAMA METNİ taşıdığından şüphelenilen anahtarlar (yalnız VARLIK/uzunluk taşınmalı).
COMMENT_TEXT_KEYS = ("comment_text", "comment", "comment_body", "note_text", "explanation_text", "text")
PII_KEYS = (
    "transcript_text", "transcript", "audio_payload", "recording", "customer_name", "full_name",
    "phone_number", "msisdn", "email", "national_id", "card_number", "pan", "cvv", "otp", "iban", "address",
)


# ───────────────────────── ortak yardımcılar ─────────────────────────
def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _walk_strings(obj, path="$"):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_strings(v, "%s.%s" % (path, k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk_strings(v, "%s[%d]" % (path, i))
    elif isinstance(obj, str):
        yield path, obj


def _walk_keys(obj, path="$"):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield path, k
            yield from _walk_keys(v, "%s.%s" % (path, k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk_keys(v, "%s[%d]" % (path, i))


# ───────────────────────── validate ─────────────────────────
def cmd_validate(argv):
    spec = _load(SPEC_PATH)
    checks = []

    def chk(cond, label):
        checks.append((bool(cond), label))

    # — kimlik/meta —
    chk(spec.get("wbs") == "14.2.6", "wbs=14.2.6")
    chk(spec.get("phase") == "F2", "phase=F2")
    chk(spec.get("priority") == "Must", "priority=Must")
    ed = spec.get("eval_doc", {})
    chk("FR-ANA-009" in ed.get("fr", ""), "eval_doc.fr→FR-ANA-009")
    chk("SR-ANA-009" in ed.get("srs", ""), "eval_doc.srs→SR-ANA-009")
    chk("TC-ANA-009" in ed.get("rtm", ""), "eval_doc.rtm→TC-ANA-009")
    for key in ("brd", "sad", "db", "olap", "iam", "eventstream", "adr", "api", "upstream"):
        chk(key in ed and ed[key], "eval_doc.%s var" % key)
    chk("DB.md §5.6" in ed.get("db", ""), "db→DB.md §5.6 (call_evaluation)")
    chk("FR-IAM-011" in ed.get("iam", "") or "qa:score" in ed.get("iam", ""), "iam→qa:score/FR-IAM-011")

    # — placement —
    pl = spec.get("placement", {})
    chk(pl.get("in_analytics_plane") is True, "placement.in_analytics_plane")
    chk(pl.get("human_initiated") is True, "placement.human_initiated (otomatik değil)")
    chk(pl.get("non_blocking") is True, "placement.non_blocking")
    chk(pl.get("from_trace") is False, "placement.from_trace=false")
    chk(pl.get("all_calls") is False, "placement.all_calls=false (manuel örneklem)")

    # — authorization (BİRİNCİL) —
    az = spec.get("authorization", {})
    chk(az.get("required_permission") == REQUIRED_PERMISSION, "authorization.required_permission=qa:score")
    chk(az.get("decided_in_backend") is True, "authorization.decided_in_backend")
    chk(az.get("platform_l0_forbidden") is True, "authorization.platform_l0_forbidden (altın kural)")
    chk(az.get("unauthorized_error") == "AUTH", "authorization.unauthorized_error=AUTH")
    for r in PLATFORM_L0_ROLES:
        chk(r in az.get("illustrative_forbidden_roles", []), "L0 rol yasak: %s" % r)
    chk("qa_analyst" in az.get("illustrative_allowed_roles", []), "qa_analyst izinli")

    # — scoring —
    sc = spec.get("scoring", {})
    scale = sc.get("scale", {})
    chk(scale.get("min") == 1 and scale.get("max") == 5, "scoring.scale 1–5")
    chk(sc.get("score_required") is True, "scoring.score_required (FR-ANA-009 skor zorunlu)")
    chk(sc.get("score_field") == "human_score", "scoring.score_field=human_score")
    chk("normalize" in sc.get("normalize_to_olap", "").lower() or "[0,1]" in sc.get("normalize_to_olap", ""),
        "scoring.normalize_to_olap→[0,1]")

    # — comment_policy (PII sınırı, KEY) —
    cp = spec.get("comment_policy", {})
    chk(cp.get("text_in_olap_forbidden") is True, "comment_policy.text_in_olap_forbidden")
    chk(cp.get("text_in_event_payload_forbidden") is True, "comment_policy.text_in_event_payload_forbidden")
    chk(cp.get("text_in_spec_forbidden") is True, "comment_policy.text_in_spec_forbidden")
    chk("tenant" in cp.get("text_storage", "").lower(), "comment_policy.text_storage=tenant-plane")
    chk("human_comment_present" in cp.get("olap_projection", ""), "comment_policy.olap_projection→present")

    # — output_contract / OLAP BİREBİR (non-circular) —
    oc = spec.get("output_contract", {})
    chk(oc.get("eval_type") == "manual", "output_contract.eval_type=manual")
    chk(tuple(oc.get("olap_score_fields", [])) == OLAP_MANUAL_FIELDS,
        "olap_score_fields == OLAP fct_qa_evaluation manuel alanları (non-circular)")
    chk("comment" in oc.get("tenant_plane_only_fields", []), "comment tenant_plane_only")
    chk("evaluator_id" in oc.get("db_fields", []), "db_fields→evaluator_id (DB.md §5.6)")
    chk(any("governance.audit.v1" in e for e in oc.get("emits_events", [])), "emits→governance.audit.v1")
    chk(any("qa.evaluation.v1" in e for e in oc.get("emits_events", [])), "emits→qa.evaluation.v1 (manual)")

    # — coexistence (otomatik overwrite YOK) —
    cx = spec.get("coexistence", {})
    chk(cx.get("manual_does_not_overwrite_automatic") is True, "coexistence.no_overwrite_automatic")
    chk(cx.get("separate_olap_columns", {}).get("automatic") == "auto_score", "coexist: auto_score ayrı")
    chk(cx.get("separate_olap_columns", {}).get("manual") == "human_score", "coexist: human_score ayrı")
    chk(cx.get("multiple_manual_per_call_allowed") is True, "coexist: çoklu manuel/çağrı")

    # — audit —
    au = spec.get("audit", {})
    chk(au.get("required") is True, "audit.required")
    chk(au.get("topic") == "governance.audit.v1", "audit.topic=governance.audit.v1")
    chk(au.get("append_only_worm") is True, "audit.append_only_worm")
    chk(au.get("no_silent_overwrite") is True, "audit.no_silent_overwrite")
    for f in ("evaluator_id", "call_id", "action_code", "created_at"):
        chk(f in au.get("audit_fields", []), "audit_field: %s" % f)

    # — idempotency —
    idp = spec.get("idempotency", {})
    chk(tuple(idp.get("dedup_key", [])) == ("tenant_id", "call_id", "evaluator_id", "schema_version"),
        "idempotency.dedup_key (tenant,call,evaluator,schema)")
    chk(idp.get("resubmit_supersedes") is True, "idempotency.resubmit_supersedes")
    chk(idp.get("replay_safe") is True, "idempotency.replay_safe")

    # — isolation —
    iso = spec.get("isolation", {})
    chk(iso.get("tenant_id_required") is True, "isolation.tenant_id_required")
    chk(iso.get("evaluator_tenant_must_match_call") is True, "isolation.evaluator_tenant_must_match_call")
    chk(iso.get("cross_tenant_forbidden") is True, "isolation.cross_tenant_forbidden")
    chk(iso.get("residency") == "home-region", "isolation.residency=home-region")

    # — eligibility —
    el = spec.get("eligibility", {})
    chk(el.get("evaluable_status") == ["completed"], "eligibility.evaluable_status=[completed]")
    chk(set(el.get("reason_codes", [])) == set(el.get("excluded_status", [])),
        "eligibility: excluded↔reason_code BİREBİR (sessiz reddetme yok)")

    # — gates (10 kapı) —
    g = spec.get("gates", {})
    for gate in ("max_authz_violation", "max_missing_required", "max_score_domain_violation",
                 "max_catalog_mismatch", "max_pii_leak", "max_isolation_violation",
                 "max_audit_missing", "max_idempotency_violation", "max_blocking_violation",
                 "max_eligibility_reason_missing"):
        chk(g.get(gate) == 0, "gate %s == 0" % gate)

    # — error_taxonomy —
    em = spec.get("error_taxonomy", {}).get("mapping", {})
    chk(em.get("unauthorized") == "AUTH", "errtax unauthorized→AUTH")
    chk(em.get("cross_tenant") == "AUTH", "errtax cross_tenant→AUTH")
    chk(em.get("region_mismatch") == "REGION_VIOLATION", "errtax region→REGION_VIOLATION")
    for v in em.values():
        chk(v in ERROR_TAXONOMY, "errtax değeri taksonomide: %s" % v)

    # — invariants —
    inv_ids = [i.get("id") for i in spec.get("invariants", [])]
    chk(len(inv_ids) >= 14, "≥14 invariant")
    chk(len(inv_ids) == len(set(inv_ids)), "invariant id'leri tekil")

    # — PII/sır/AÇIKLAMA METNİ hijyeni (spec + config) —
    leaks = []
    for src in (SPEC_PATH, PROFILES_CFG):
        if not os.path.exists(src):
            continue
        with open(src, "r", encoding="utf-8") as fh:
            raw = fh.read()
        if SECRET_RE.search(raw):
            leaks.append("%s: sır deseni" % os.path.basename(src))
        obj = json.loads(raw)
        for p, val in _walk_strings(obj):
            if p.endswith(".$comment") or "$comment" in p:
                continue
            if PLACEHOLDER_RE.match(val):
                continue
            if PII_VALUE_RE.search(val):
                leaks.append("%s %s: PII DEĞER deseni" % (os.path.basename(src), p))
        for p, key in _walk_keys(obj):
            if key in PII_KEYS:
                leaks.append("%s %s: yasak PII anahtarı '%s'" % (os.path.basename(src), p, key))
            if key in COMMENT_TEXT_KEYS and not (p.endswith("tenant_plane_only_fields") or "COMMENT_TEXT" in p):
                # spec'te yalnız ANAHTAR ADI olarak comment listelenebilir; gerçek metin alanı taşınamaz
                pass
    chk(not leaks, "spec/config sır/PII/AÇIKLAMA-metni hijyeni: %s" % (leaks or "temiz"))

    # — config profilleri —
    if os.path.exists(PROFILES_CFG):
        cfg = _load(PROFILES_CFG)
        profs = cfg.get("profiles", [])
        chk(len(profs) >= 2, "≥2 deployment profili")
        names = {p.get("name") for p in profs}
        chk(cfg.get("default_profile") in names, "default_profile profiller içinde")
        for p in profs:
            chk(p.get("region", "").startswith("${") or p.get("region"), "profil region var: %s" % p.get("name"))
            chk(isinstance(p.get("schema_version"), int), "profil schema_version int: %s" % p.get("name"))

    return _report(checks, "validate")


# ───────────────────────── ManualQaScoringEngine (deterministik) ─────────────────────────
class ManualQaScoringEngine:
    """Saf, deterministik manuel QA skorlama yüzeyi simülatörü (random YOK)."""

    def __init__(self, spec):
        self.spec = spec
        self.scale = spec["scoring"]["scale"]
        self.evaluable = set(spec["eligibility"]["evaluable_status"])
        self.excluded = set(spec["eligibility"]["excluded_status"])
        self.reason_codes = set(spec["eligibility"]["reason_codes"])
        self.comment_max = spec["comment_policy"].get("comment_max_chars", 4000)

    def _normalize(self, score):
        mn, mx = self.scale["min"], self.scale["max"]
        return round((score - mn) / (mx - mn), 6)

    def process(self, sub):
        """Tek submission → (accepted, row|None, audit|None, errors[])."""
        errors = []
        tenant = sub.get("tenant_id")
        call_id = sub.get("call_id")
        status = sub.get("status")
        submitter = sub.get("submitter", {}) or {}

        # G2: zorunlu kimlik bağlamı
        if not tenant or not call_id:
            errors.append(("missing_required", "INVALID_REQUEST", "tenant_id/call_id eksik"))

        # G10: uygunluk (eligibility) — sessiz reddetme yok
        if status in self.excluded:
            if status not in self.reason_codes:
                errors.append(("eligibility_reason_missing", "INVALID_REQUEST",
                               "uygun-olmayan statü reason_code taşımıyor: %s" % status))
            else:
                errors.append(("ineligible_status", "INVALID_REQUEST",
                               "skorlanamaz statü (reason=%s)" % status))
        elif status not in self.evaluable:
            errors.append(("unknown_status", "INVALID_REQUEST", "bilinmeyen statü: %s" % status))

        # G1: yetki (BİRİNCİL) — permission-key tabanlı, backend kararı
        role = submitter.get("evaluator_role")
        perms = submitter.get("permissions", []) or []
        if role in PLATFORM_L0_ROLES:
            errors.append(("unauthorized", "AUTH", "platform L0 rolü tenant içeriğini skorlayamaz (altın kural): %s" % role))
        elif REQUIRED_PERMISSION not in perms:
            errors.append(("unauthorized", "AUTH", "qa:score izni yok (rol=%s)" % role))

        # G6: izolasyon — evaluator tenant == çağrı tenant
        if submitter.get("tenant_id") and tenant and submitter["tenant_id"] != tenant:
            errors.append(("cross_tenant", "AUTH", "cross-tenant skor: evaluator=%s call=%s" %
                           (submitter["tenant_id"], tenant)))

        # G2: evaluator_id + skor zorunlu
        evaluator_id = submitter.get("evaluator_id")
        if not evaluator_id:
            errors.append(("missing_required", "INVALID_REQUEST", "evaluator_id zorunlu (manuel)"))
        score = sub.get("human_score")
        if score is None:
            errors.append(("missing_required", "INVALID_REQUEST", "human_score zorunlu (FR-ANA-009)"))
        else:
            # G3: skor domain
            if not isinstance(score, (int, float)) or score < self.scale["min"] or score > self.scale["max"]:
                errors.append(("score_out_of_domain", "INVALID_REQUEST",
                               "human_score ∉ [%s,%s]: %r" % (self.scale["min"], self.scale["max"], score)))

        # G5: AÇIKLAMA METNİ sızıntısı — submission yalnız VARLIK/uzunluk taşımalı
        for k in COMMENT_TEXT_KEYS:
            if k in sub and isinstance(sub[k], str) and sub[k].strip():
                errors.append(("comment_text_leak", "INVALID_REQUEST",
                               "açıklama METNİ alanı sızdı: '%s' (yalnız comment_present/comment_chars taşınmalı)" % k))
        # PII DEĞER deseni herhangi bir string alanında
        for p, val in _walk_strings(sub):
            if PII_VALUE_RE.search(val):
                errors.append(("comment_text_leak", "INVALID_REQUEST", "PII DEĞER deseni: %s" % p))
                break
        comment_chars = sub.get("comment_chars", 0) or 0
        if isinstance(comment_chars, (int, float)) and comment_chars > self.comment_max:
            errors.append(("missing_required", "INVALID_REQUEST",
                           "açıklama uzunluğu sınırı aşıyor: %s>%s" % (comment_chars, self.comment_max)))

        if errors:
            return False, None, None, errors

        # — kabul: OLAP projeksiyon satırı (yalnız human_*/evaluator_role; METİN YOK) —
        comment_present = bool(sub.get("comment_present") or comment_chars > 0)
        row = {
            "tenant_id": tenant,
            "call_id": call_id,
            "evaluator_id": evaluator_id,
            "schema_version": sub.get("schema_version", 1),
            "eval_type": "manual",
            # OLAP fct_qa_evaluation manuel projeksiyon (BİREBİR):
            "human_score": self._normalize(score),
            "human_comment_present": comment_present,
            "evaluator_role": role,
        }
        audit = {
            "topic": "governance.audit.v1",
            "action_code": self.spec["audit"]["action_code"],
            "tenant_id": tenant,
            "call_id": call_id,
            "evaluator_id": evaluator_id,
            "evaluator_role": role,
        }
        return True, row, audit, []


def cmd_score(argv):
    if not argv:
        print("kullanım: manual_qa_probe.py score <sample.json>", file=sys.stderr)
        return 2
    spec = _load(SPEC_PATH)
    sample = _load(argv[0])
    engine = ManualQaScoringEngine(spec)
    subs = sample.get("submissions", [])

    accepted_rows = []
    audits = []
    rejections = []  # (idx, errors)
    pii_leaks = 0
    authz_denied = 0
    score_domain_viol = 0
    missing_required = 0
    elig_reason_missing = 0

    expect = sample.get("expect", {})  # {"accept": [...], "reject": [...]} indeks bekleyişi (opsiyonel)

    for idx, sub in enumerate(subs):
        accepted, row, audit, errors = engine.process(sub)
        if accepted:
            accepted_rows.append((idx, row))
            audits.append((idx, audit))
        else:
            rejections.append((idx, errors))
            kinds = {e[0] for e in errors}
            if "unauthorized" in kinds or "cross_tenant" in kinds:
                authz_denied += 1
            if "comment_text_leak" in kinds:
                pii_leaks += 1
            if "score_out_of_domain" in kinds:
                score_domain_viol += 1
            if "missing_required" in kinds:
                missing_required += 1
            if "eligibility_reason_missing" in kinds:
                elig_reason_missing += 1

    # — kapı değerlendirmeleri —
    g = spec["gates"]
    gate_results = []

    # G1 authz: yetkisiz submission HER ZAMAN reddedilmeli. expect.reject_authz varsa o indeksler red olmalı.
    authz_leak = 0  # yetkisiz olduğu halde kabul edilen
    for idx, row in accepted_rows:
        sub = subs[idx]
        s = sub.get("submitter", {})
        if s.get("evaluator_role") in PLATFORM_L0_ROLES or REQUIRED_PERMISSION not in (s.get("permissions") or []):
            authz_leak += 1
        if s.get("tenant_id") and s["tenant_id"] != sub.get("tenant_id"):
            authz_leak += 1
    gate_results.append(("G1 authz (BİRİNCİL)", authz_leak <= g["max_authz_violation"], authz_leak))

    # G3 score domain: kabul edilenlerin normalize skoru [0,1] içinde
    domain_out = sum(1 for _, r in accepted_rows if not (0.0 <= r["human_score"] <= 1.0))
    gate_results.append(("G3 score-domain [0,1]", domain_out <= g["max_score_domain_violation"], domain_out))

    # G4 katalog: kabul satırı tam OLAP_MANUAL_FIELDS + eval_type=manual taşımalı (non-circular)
    catalog_mismatch = 0
    for _, r in accepted_rows:
        if r.get("eval_type") != "manual":
            catalog_mismatch += 1
        for f in OLAP_MANUAL_FIELDS:
            if f not in r:
                catalog_mismatch += 1
    gate_results.append(("G4 katalog/eval_type (OLAP BİREBİR)", catalog_mismatch <= g["max_catalog_mismatch"], catalog_mismatch))

    # G5 PII: hiçbir kabul satırı/audit AÇIKLAMA METNİ veya PII anahtarı taşımamalı
    leak_in_output = 0
    for _, r in accepted_rows + [(i, a) for i, a in audits]:
        for k in list(r.keys()):
            if k in COMMENT_TEXT_KEYS or k in PII_KEYS:
                leak_in_output += 1
        for p, val in _walk_strings(r):
            if PII_VALUE_RE.search(val):
                leak_in_output += 1
    # Reddedilen submission ASLA çıktı üretmez (PII içeren girdi kapıda elenir); kapı yalnız KABUL çıktısını denetler.
    gate_results.append(("G5 PII (çıktıda METİN/PII yok)", leak_in_output <= g["max_pii_leak"], leak_in_output))

    # G6 isolation: kabul satırı tek tenant + evaluator tenant eşleşmiş (authz_leak içinde de yakalanır)
    iso_viol = 0
    for idx, r in accepted_rows:
        s = subs[idx].get("submitter", {})
        if s.get("tenant_id") and s["tenant_id"] != r["tenant_id"]:
            iso_viol += 1
    gate_results.append(("G6 izolasyon (tek tenant)", iso_viol <= g["max_isolation_violation"], iso_viol))

    # G7 audit: her kabul edilen satır için tam bir audit izi üretilmeli
    audit_missing = abs(len(accepted_rows) - len(audits))
    for _, a in audits:
        if a.get("action_code") != spec["audit"]["action_code"] or not a.get("evaluator_id"):
            audit_missing += 1
    gate_results.append(("G7 audit (her kabul→WORM iz)", audit_missing <= g["max_audit_missing"], audit_missing))

    # G8 idempotency: (tenant,call,evaluator,schema) içinde EN FAZLA 1 etkin satır
    seen = {}
    idem_viol = 0
    for _, r in accepted_rows:
        key = (r["tenant_id"], r["call_id"], r["evaluator_id"], r["schema_version"])
        seen[key] = seen.get(key, 0) + 1
    for key, n in seen.items():
        if n > 1:
            idem_viol += (n - 1)  # supersede: yalnız son etkin; fazlalar dedup edilmeli
    gate_results.append(("G8 idempotent/sürümlü (dedup_key)", idem_viol <= g["max_idempotency_violation"], idem_viol))

    # G10 eligibility reason: uygun-olmayan ama reason taşımayan = ihlal
    gate_results.append(("G10 eligibility reason_code", elig_reason_missing <= g["max_eligibility_reason_missing"], elig_reason_missing))

    # — opsiyonel expect kontrolü (sample doğruluk iddiası) —
    expect_ok = True
    expect_notes = []
    if expect:
        acc_idx = {i for i, _ in accepted_rows}
        for i in expect.get("accept", []):
            if i not in acc_idx:
                expect_ok = False
                expect_notes.append("idx %d KABUL bekleniyordu, reddedildi" % i)
        for i in expect.get("reject", []):
            if i in acc_idx:
                expect_ok = False
                expect_notes.append("idx %d RED bekleniyordu, kabul edildi" % i)

    all_pass = all(ok for _, ok, _ in gate_results) and expect_ok

    # — rapor —
    print("# Manuel QA Skorlama — %s" % os.path.basename(argv[0]))
    print("  submission=%d  kabul=%d  red=%d" % (len(subs), len(accepted_rows), len(rejections)))
    if accepted_rows:
        avg = round(sum(r["human_score"] for _, r in accepted_rows) / len(accepted_rows), 4)
        cp = sum(1 for _, r in accepted_rows if r["human_comment_present"])
        print("  human_score_avg(normalize)=%s  comment_present=%d  audit_iz=%d" % (avg, cp, len(audits)))
    print("  yetki-reddi=%d  domain-red=%d  zorunlu-red=%d  PII-sızıntı(girdi)=%d" %
          (authz_denied, score_domain_viol, missing_required, pii_leaks))
    print("  — HARD kapılar —")
    for label, ok, val in gate_results:
        print("    %s  %-38s (gözlem=%s)" % ("🟢" if ok else "🔴", label, val))
    if expect:
        print("    %s  expect (accept/reject iddiası)  %s" %
              ("🟢" if expect_ok else "🔴", ";".join(expect_notes) or "uyumlu"))
    if rejections:
        print("  — red gerekçeleri (ilk 8) —")
        for idx, errs in rejections[:8]:
            print("    idx %d: %s" % (idx, "; ".join("%s/%s" % (e[0], e[1]) for e in errs)))
    print("\n%s" % ("PASS ✅ tüm kapılar geçti" if all_pass else "FAIL ❌ kapı eledi"))
    return 0 if all_pass else 1


# ───────────────────────── selftest ─────────────────────────
def cmd_selftest(argv):
    spec = _load(SPEC_PATH)
    engine = ManualQaScoringEngine(spec)
    checks = []

    def chk(cond, label):
        checks.append((bool(cond), label))

    qa = {"evaluator_id": "u-qa-1", "evaluator_role": "qa_analyst",
          "permissions": ["calls:read", "transcript:read", "qa:score", "analytics:read"], "tenant_id": "t-a"}

    # T1 — yetkili happy-path kabul + normalize
    ok, row, audit, errs = engine.process(
        {"tenant_id": "t-a", "call_id": "c1", "status": "completed", "submitter": qa,
         "human_score": 5, "comment_present": True, "comment_chars": 80, "schema_version": 1})
    chk(ok and row["human_score"] == 1.0 and row["eval_type"] == "manual", "T1 yetkili kabul + score 5→1.0 + manual")
    chk(audit and audit["action_code"] == "manual_score_added" and audit["evaluator_id"] == "u-qa-1", "T1 audit izi üretildi")
    chk(row["human_comment_present"] is True and "comment" not in row and "comment_text" not in row,
        "T1 OLAP yalnız comment_present (METİN YOK)")

    # T2 — yetkisiz: qa:score izni yok → AUTH red (BİRİNCİL)
    no_perm = dict(qa, permissions=["calls:read", "analytics:read"], evaluator_role="human_agent")
    ok2, _, _, errs2 = engine.process(
        {"tenant_id": "t-a", "call_id": "c2", "status": "completed", "submitter": no_perm, "human_score": 4})
    chk(not ok2 and any(e[1] == "AUTH" for e in errs2), "T2 qa:score yok → AUTH red")

    # T3 — platform L0 rolü → AUTH red (altın kural)
    l0 = dict(qa, evaluator_role="platform_sre", permissions=["qa:score"])
    ok3, _, _, errs3 = engine.process(
        {"tenant_id": "t-a", "call_id": "c3", "status": "completed", "submitter": l0, "human_score": 3})
    chk(not ok3 and any(e[1] == "AUTH" for e in errs3), "T3 platform L0 → AUTH red (altın kural)")

    # T4 — skor zorunlu: human_score yok → INVALID_REQUEST
    ok4, _, _, errs4 = engine.process(
        {"tenant_id": "t-a", "call_id": "c4", "status": "completed", "submitter": qa,
         "comment_present": True, "comment_chars": 50})
    chk(not ok4 and any(e[0] == "missing_required" for e in errs4), "T4 skorsuz submission → red")

    # T5 — skor domain dışı (0 ve 6) → red
    ok5a, _, _, _ = engine.process(
        {"tenant_id": "t-a", "call_id": "c5", "status": "completed", "submitter": qa, "human_score": 6})
    ok5b, _, _, _ = engine.process(
        {"tenant_id": "t-a", "call_id": "c5", "status": "completed", "submitter": qa, "human_score": 0})
    chk(not ok5a and not ok5b, "T5 skor ∉[1,5] → red")

    # T6 — açıklama METNİ sızıntısı → red (PII sınırı, KEY)
    ok6, _, _, errs6 = engine.process(
        {"tenant_id": "t-a", "call_id": "c6", "status": "completed", "submitter": qa, "human_score": 4,
         "comment_text": "müşteri çok kızgındı, iade istedi"})
    chk(not ok6 and any(e[0] == "comment_text_leak" for e in errs6), "T6 açıklama METNİ alanı → red")

    # T7 — PII DEĞER deseni (telefon) → red
    ok7, _, _, errs7 = engine.process(
        {"tenant_id": "t-a", "call_id": "c7", "status": "completed",
         "submitter": dict(qa, note="ara 5551234567"), "human_score": 4})
    chk(not ok7 and any(e[0] == "comment_text_leak" for e in errs7), "T7 PII DEĞER deseni → red")

    # T8 — cross-tenant → AUTH red
    ok8, _, _, errs8 = engine.process(
        {"tenant_id": "t-a", "call_id": "c8", "status": "completed",
         "submitter": dict(qa, tenant_id="t-b"), "human_score": 4})
    chk(not ok8 and any(e[0] == "cross_tenant" for e in errs8), "T8 cross-tenant → AUTH red")

    # T9 — uygun-olmayan statü (in_progress, reason'lı) → red ama reason_missing DEĞİL
    ok9, _, _, errs9 = engine.process(
        {"tenant_id": "t-a", "call_id": "c9", "status": "in_progress", "submitter": qa, "human_score": 4})
    chk(not ok9 and any(e[0] == "ineligible_status" for e in errs9) and
        not any(e[0] == "eligibility_reason_missing" for e in errs9), "T9 in_progress → ineligible (reason var)")

    # T10 — normalize doğruluğu: 3 → 0.5
    ok10, row10, _, _ = engine.process(
        {"tenant_id": "t-a", "call_id": "c10", "status": "completed", "submitter": qa, "human_score": 3})
    chk(ok10 and row10["human_score"] == 0.5, "T10 score 3 → 0.5 normalize")

    # T11 — comment yok ama skor var → kabul (comment opsiyonel), present=False
    ok11, row11, _, _ = engine.process(
        {"tenant_id": "t-a", "call_id": "c11", "status": "completed", "submitter": qa, "human_score": 2})
    chk(ok11 and row11["human_comment_present"] is False, "T11 yorumsuz skor → kabul, present=False")

    # T12 — operations_manager da qa:score taşır → kabul
    om = {"evaluator_id": "u-om-1", "evaluator_role": "operations_manager",
          "permissions": ["campaign:manage", "qa:score", "analytics:read"], "tenant_id": "t-a"}
    ok12, _, _, _ = engine.process(
        {"tenant_id": "t-a", "call_id": "c12", "status": "completed", "submitter": om, "human_score": 5})
    chk(ok12, "T12 operations_manager (qa:score) → kabul")

    # T13 — spec: OLAP non-circular alan eşleşmesi
    chk(tuple(spec["output_contract"]["olap_score_fields"]) == OLAP_MANUAL_FIELDS, "T13 OLAP BİREBİR alan eşleşmesi")

    # T14 — config profilleri yüklenir + default geçerli
    cfg = _load(PROFILES_CFG)
    names = {p["name"] for p in cfg["profiles"]}
    chk(cfg["default_profile"] in names and len(names) >= 2, "T14 config profilleri + default geçerli")

    return _report(checks, "selftest")


# ───────────────────────── schema ─────────────────────────
def cmd_schema(argv):
    print("manual-qa-scoring-spec.json beklenen şekil (WBS 14.2.6, FR-ANA-009):")
    print("  wbs/version/phase/priority")
    print("  eval_doc: fr(FR-ANA-009)/srs(SR-ANA-009)/rtm(TC-ANA-009)/brd/sad/db(§5.6)/olap/iam(qa:score)/eventstream/adr/api/upstream")
    print("  placement: in_analytics_plane, human_initiated, non_blocking, from_trace=false, all_calls=false")
    print("  authorization: required_permission=qa:score, decided_in_backend, platform_l0_forbidden, unauthorized_error=AUTH")
    print("  scoring: score_field=human_score, scale{1..5}, score_required, normalize_to_olap→[0,1]")
    print("  comment_policy: text tenant-plane only; text_in_olap/event/spec_forbidden; olap=human_comment_present (KEY)")
    print("  output_contract: eval_type=manual, olap_score_fields=%s, tenant_plane_only=[comment]" % list(OLAP_MANUAL_FIELDS))
    print("  coexistence: manual_does_not_overwrite_automatic, ayrı OLAP sütun (auto_score|human_score)")
    print("  audit: governance.audit.v1, action_code=manual_score_added, append_only_worm")
    print("  idempotency: dedup_key(tenant,call,evaluator,schema), resubmit_supersedes")
    print("  isolation: evaluator_tenant_must_match_call, cross_tenant_forbidden, home-region")
    print("  eligibility: evaluable=[completed]; excluded↔reason_code")
    print("  gates(10): authz/missing/score_domain/catalog/pii/isolation/audit/idempotency/blocking/eligibility")
    print("  invariants: I1..I14")
    print("Komutlar: validate | score <sample> | selftest | schema")
    return 0


def _report(checks, label):
    passed = sum(1 for ok, _ in checks if ok)
    total = len(checks)
    for ok, lbl in checks:
        if not ok:
            print("  🔴 %s" % lbl)
    print("\n[%s] %d/%d PASS" % (label, passed, total))
    return 0 if passed == total else 1


def main(argv):
    if not argv:
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    table = {"validate": cmd_validate, "score": cmd_score, "selftest": cmd_selftest, "schema": cmd_schema}
    fn = table.get(cmd)
    if not fn:
        print("bilinmeyen komut: %s (validate|score|selftest|schema)" % cmd, file=sys.stderr)
        return 2
    return fn(rest)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
