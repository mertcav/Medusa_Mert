#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_probe.py — WBS 14.2.8 Dashboard + ham veri export

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only statik + davranış kapısı.
`runtime/version-compare/` (14.2.7) probe disipliniyle birebir; burada deterministik bir ANALYTICS-PLANE
DASHBOARD + HAM VERİ EXPORT (DATA EXPORT) motoru (SAD §4.2 async batch; analytics-ingest/olap-sink consumer)
simülatörü (deterministik sıralama + sha256 checksum; random YOK).

EXPORT MOTORU — Analytics/Ops Plane'de (SAD §4.2/§171, FR-RES-011) async/non-blocking; OLAP rollup/fact tablolarını
(mv_call_daily / mv_usage_daily / mv_agent_version_perf / fct_call — 14.2.1/14.2.2/14.2.3/14.2.4/14.2.5 üretir)
OKUR ve hem dashboard agregatını sunar hem ALTTAKİ redaksiyonlu satırları bir EXPORT DOSYASINA (csv/jsonl/ndjson)
yazar (FR-ANA-011). Metriği YENİDEN HESAPLAMAZ — OKUR + EXPORT eder + dashboard ile UZLAŞTIRIR:
  • Bütünlük (G1):    export satır sayısı == sorgulanan benzersiz satır; düşme=0/hayalet=0; manifest row_count tutarlı;
                      deterministik sıralama + sha256 checksum — BİRİNCİL (SR-ANA-011 'üretilir').
  • Uzlaşma (G2):     export satırlarının yeniden-agregasyonu == dashboard tile değeri (±tol); partition toplamı=1.0
                      — SR-ANA-011 'TUTARLIDIR' çekirdeği.
  • Format (G3):      format ∈ supported; export sütunları kaynağın OLAP sütun/metrik kataloğunda (BİREBİR non-circular).
  • PII (G4):         export YALNIZ redaksiyonlu/agregat sütun (pii_class ∈ {none,low,redacted}); ham transkript/ses/
                      kayıt URI/PII DEĞERİ EXPORT'A GİRMEZ (FR-REC-004/005).
  • Yetki (G5):       export `analytics:read` ister; karar backend'de; platform L0 altın kural — İKİNCİL çekirdek.
  • İzolasyon (G6):   tek tenant_id + cross-tenant yok + residency (FR-TEN-002/NFR 10.7).
  • Audit (G7):       her export → governance.audit.v1 (data_export) WORM izi; SESSİZ export yok; içerik/PII taşımaz.
  • İdempotent (G8):  (tenant,report,source,period,format,schema) bir kez; duplicate export ihlal.
  • Async (G9):       analytics plane non-blocking; export başarısızlığı canlı çağrıyı etkilemez (FR-RES-011).

KAPSAM AYRIMI: otomatik skor → 14.2.1 · per-call çıkarım → 14.2.2 · oran → 14.2.3 · işaretler → 14.2.4 · kritik →
14.2.5 · manuel skor → 14.2.6 · sürüm karşılaştırma → 14.2.7 · maliyet → 14.2.9 · GERÇEK-ZAMANLI op ekranı ≤60s
(FR-ANA-012) → 14.1.6. Burada YALNIZ dashboard agregatı + ham veri export + export-dashboard tutarlılığı.

Komutlar:
  validate              data-export-spec.json'ı invariant'lara + OLAP çapraz-tutarlılığa + config'e karşı doğrular.
  export <sample>       Deterministik DataExportEngine — request → manifest/satır + HARD kapılar (G1–G9); →çıkış kodu.
  selftest              İyi/kötü spec+sample ile kapıların doğru tetiklendiğini kanıtlar.
  schema                Beklenen spec şeklini özetler.

Sunucu/credential GEREKMEZ. export gerçek motor yerine deterministik simülasyondur (canlıda mv_*/fct_* consumer +
nesne-depo export + governance.audit.v1, SAD §4.2/§12.1; ADR-007). Ham ses payload/transkript METNİ/PII DEĞERİ YOK —
örnekler yalnız REDAKSİYONLU agregat/redaksiyonlu satır + düşük-kardinalite boyut/kimlik anahtarı ADLARI taşır.
"""
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "data-export-spec.json")
PROFILES_CFG = os.path.join(HERE, "config", "data-export-profiles.json")

ERROR_TAXONOMY = {
    "TIMEOUT", "RATE_LIMITED", "UNAVAILABLE", "AUTH",
    "INVALID_REQUEST", "CONTENT_FILTERED", "QUOTA_EXCEEDED", "REGION_VIOLATION",
}
SECRET_RE = re.compile(
    r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer)\b\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}"
)
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")
# Ham PII DEĞER desenleri (girdi/çıktıda yasak — FR-REC-004). Yalnız anahtar ADI / agregat sayı olmalı.
PII_VALUE_RE = re.compile(
    r"(?:\d[ \-]?){7,}"                                   # ≥7 ardışık rakam (telefon/kart/IBAN)
    r"|[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"  # e-posta
    r"|\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b"                  # IBAN
)
# ISO tarih/period boyutu (ör. 2026-06 veya 2026-06-01) düşük-kardinalite boyut anahtarıdır — PII DEĞİL.
DATE_RE = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")
TOL = 1e-9
PII_CLASS_ALLOWED = {"none", "low", "redacted"}


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_placeholder(v):
    return isinstance(v, str) and PLACEHOLDER_RE.match(v) is not None


def _pii_value(v):
    """v ham PII DEĞERİ mi (telefon/kart/IBAN/e-posta)? Placeholder ${ENV} ve ISO tarih/period boyutu muaf."""
    return isinstance(v, str) and not _is_placeholder(v) and not DATE_RE.match(v) and bool(PII_VALUE_RE.search(v))


def _load_sibling_spec(*parts):
    cand = os.path.normpath(os.path.join(HERE, "..", "..", *parts))
    if os.path.exists(cand):
        try:
            return _load(cand)
        except Exception:
            return None
    return None


class ExportError(Exception):
    """Geçersiz/eksik export girdisi veya bilinmeyen kaynak/format — sessizce kabul yok, reddet (I12)."""


def _grain_tokens(grain):
    """OLAP rollup grain string'ini ('tenant_id + agent_id + event_date') boyut sütun adlarına çevirir."""
    return {t.strip() for t in str(grain or "").replace("+", " ").split() if t.strip()}


def _olap_source_columns(olap, source):
    """Kaynağın OLAP sütun kataloğunu çözer (non-circular). Döner (col_set | None, pii_by_col, max_pii_class).
    fact_tables → gerçek columns + pii_class; rollups → metrics ∪ grain boyutları (agregat, pii güvenli)."""
    if olap is None:
        return None, {}, None
    for ft in olap.get("fact_tables", []):
        if ft.get("name") == source:
            cols = {c.get("name") for c in ft.get("columns", [])}
            pii = {c.get("name"): c.get("pii_class") for c in ft.get("columns", [])}
            return cols, pii, ft.get("max_pii_class")
    for rl in olap.get("rollups", []):
        if rl.get("name") == source:
            cols = set(rl.get("metrics", [])) | _grain_tokens(rl.get("grain"))
            return cols, {}, "low"
    return None, {}, None


def _canonical(rows):
    """Sıralı satırların kanonik serileştirmesi (deterministik checksum girdisi; sort_keys → düzen-bağımsız)."""
    return "\n".join(json.dumps(r, sort_keys=True, ensure_ascii=False, separators=(",", ":")) for r in rows)


# ─────────────────────────────────────────────────────────────────────────────
# Export motoru — deterministik (sıralama + sha256; random YOK)
# ─────────────────────────────────────────────────────────────────────────────
class DataExportEngine:
    """Analytics plane'de async/non-blocking; OLAP rollup/fact'ı OKUR + redaksiyonlu satırı EXPORT eder + dashboard
    ile UZLAŞTIRIR + bütünlük/format/PII/yetki/izolasyon/audit/idempotency/non-blocking disiplinine karşı denetler.
    Deterministik (sıralama + sha256 checksum); random YOK.

    policy bayrakları buggy bir Engine'i simüle eder (14.2.7 deseni):
      preserve_all_rows   : benzersiz satır SESSİZCE düşmez (kapalı → satır düşürülür, G1 bütünlük)
      deterministic_order : satırlar order_by ile kararlı sıralanır (kapalı → sırasız çıktı, G1 — checksum tutarsız)
      reconcile           : export dashboard agregatıyla uzlaştırılır (kapalı → uzlaşma atlanır, mismatch yakalanmaz)
      enforce_schema      : export sütunları kaynak kataloğunda + satır anahtarları bildirilen sütunlarda (kapalı → atlanır)
      enforce_redaction   : ham PII/transkript/forbidden anahtar reddedilir (kapalı → leak taranmaz)
      authorize           : analytics:read + platform L0 yasağı zorlanır (kapalı → yetki kontrolü atlanır)
      isolate_tenant      : tek-tenant export (kapalı → cross-tenant satır karışır; cross-tenant DAİMA G6 sayılır)
      audit               : her export WORM audit izi üretir (kapalı → SESSİZ export, G7)
      idempotent          : (tenant,report,source,period,format,schema) bir kez (kapalı → duplicate export, G8)
      non_blocking        : analytics plane non-blocking (kapalı → export canlı çağrıyı bloklar, G9)
    """

    def __init__(self, spec, profile, context, policy, olap=None):
        self.spec = spec
        self.context = dict(context or {})
        self.pol = policy
        self.olap = olap if olap is not None else _load_sibling_spec("analytics", "olap-spec.json")

        ef = spec.get("export_format", {})
        self.supported_formats = set(ef.get("supported_formats", []))
        self.checksum_algo = ef.get("checksum_algo", "sha256")

        es = spec.get("export_sources", {})
        self.source_catalog = dict(es.get("sources", {}))
        self.max_pii_allowed = set(es.get("max_pii_class_allowed", list(PII_CLASS_ALLOWED)))

        rc = spec.get("reconciliation", {})
        self.tol = float(rc.get("tolerance", 1e-6))
        self.partition_sum_check = bool(rc.get("partition_sum_check", True))

        az = spec.get("authorization", {})
        self.required_permission = az.get("required_permission", "analytics:read")
        self.forbidden_roles = set(az.get("forbidden_roles_illustrative", []))

        fp = spec.get("feature_policy", {})
        self.forbidden_keys = set(fp.get("forbidden_export_keys", []))

        self.region_pin = profile.get("region")
        self.schema_version = profile.get("schema_version", 1)

        if not self.context.get("tenant_id"):
            raise ExportError("export bağlamı eksik: tenant_id → INVALID_REQUEST")
        if not self.context.get("region"):
            raise ExportError("export bağlamı eksik: region → INVALID_REQUEST")

        # sayaçlar (HARD kapı kanıtı)
        self.fidelity_violations = 0
        self.reconciliation_violations = 0
        self.format_violations = 0
        self.pii_violations = 0
        self.authz_violations = 0
        self.isolation_violations = 0
        self.audit_violations = 0
        self.idempotency_violations = 0
        self.blocking_violations = 0

        self.derived = {}

    # ── yetki (G5) ────────────────────────────────────────────────────────────
    def _authorize(self, job):
        actor = job.get("actor", {}) or {}
        role = actor.get("role")
        perms = set(actor.get("permissions", []) or [])
        authorized = (self.required_permission in perms) and (role not in self.forbidden_roles)
        if not authorized:
            # Yetkisiz/platform-L0/eksik-izin export girişimi DAİMA ihlaldir (backend kararı, altın kural).
            self.authz_violations += 1
        return authorized

    # ── redaksiyon/şema/PII denetimi (G3/G4) ──────────────────────────────────
    def _check_columns(self, job, src_cols, pii_by_col):
        columns = list(job.get("columns", []))
        # G4 forbidden anahtar / pii_class
        if self.pol.get("enforce_redaction", True):
            for c in columns:
                if c in self.forbidden_keys:
                    self.pii_violations += 1
                pc = pii_by_col.get(c)
                if pc is not None and pc not in PII_CLASS_ALLOWED:
                    self.pii_violations += 1
        # G3 sütun üyeliği (kaynağın OLAP kataloğunda — BİREBİR non-circular)
        if self.pol.get("enforce_schema", True) and src_cols is not None:
            for c in columns:
                if c not in src_cols:
                    self.format_violations += 1
        return columns

    def _check_rows(self, job, columns):
        """Satır anahtarları bildirilen sütunlarda (G3) + cell DEĞERİnde ham PII yok (G4)."""
        declared = set(columns)
        for r in job.get("rows", []):
            if not isinstance(r, dict):
                raise ExportError("export satırı sözlük değil → INVALID_REQUEST")
            if self.pol.get("enforce_schema", True) and declared:
                for k in r:
                    if k not in declared:
                        self.format_violations += 1
            if self.pol.get("enforce_redaction", True):
                for k, v in r.items():
                    if k in self.forbidden_keys:
                        self.pii_violations += 1
                    if _pii_value(v):
                        self.pii_violations += 1

    # ── izolasyon (G6) ─────────────────────────────────────────────────────────
    def _isolate(self, rows):
        kept = []
        for r in rows:
            rt = r.get("tenant_id")
            include = True
            if rt is not None and rt != self.context.get("tenant_id"):
                self.isolation_violations += 1
                if self.pol.get("isolate_tenant", True):
                    include = False               # cross-tenant satır karışmaz (izole edilir)
            rr = r.get("home_region", r.get("region"))
            if rr is not None and self.region_pin is not None and not _is_placeholder(self.region_pin) and rr != self.region_pin:
                self.isolation_violations += 1
            if include:
                kept.append(r)
        return kept

    # ── bütünlük (G1) ──────────────────────────────────────────────────────────
    def _materialize(self, job, rows):
        order_by = list(job.get("order_by", []))
        dedup_key = list(job.get("dedup_key", []))

        if self.spec.get("row_integrity", {}).get("requires_order_by", True) and not order_by:
            self.fidelity_violations += 1       # deterministik sıra için order_by zorunlu
        if self.spec.get("row_integrity", {}).get("requires_dedup_key", True) and not dedup_key:
            self.fidelity_violations += 1

        # dedup (at-least-once OLAP teslimat çift-satır üretmez — 1.1.8 P3)
        seen = set()
        unique = []
        for r in rows:
            key = tuple(str(r.get(k, "")) for k in dedup_key) if dedup_key else json.dumps(r, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            unique.append(r)

        expected = job.get("expected_row_count")
        expected = len(unique) if expected is None else int(expected)

        exported = list(unique)
        if not self.pol.get("preserve_all_rows", True) and exported:
            exported = exported[:-1]            # buggy: benzersiz satır SESSİZCE düşürülür (G1)

        if self.pol.get("deterministic_order", True) and order_by:
            exported.sort(key=lambda r: tuple(str(r.get(k, "")) for k in order_by))
        elif not self.pol.get("deterministic_order", True):
            self.fidelity_violations += 1       # buggy: sırasız/deterministik-olmayan çıktı → checksum tutarsız

        row_count = len(exported)
        if row_count != expected:
            self.fidelity_violations += 1       # düşme/hayalet → bütünlük ihlali
        checksum = hashlib.sha256(_canonical(exported).encode("utf-8")).hexdigest()
        return exported, row_count, expected, checksum

    # ── uzlaşma (G2) ───────────────────────────────────────────────────────────
    @staticmethod
    def _agg(rows, tile):
        kind = tile.get("agg")
        if kind == "count":
            return float(len(rows))
        if kind == "sum":
            col = tile.get("column")
            return sum(float(r.get(col, 0) or 0) for r in rows)
        if kind == "rate":
            num = sum(float(r.get(tile.get("num_column"), 0) or 0) for r in rows)
            den = sum(float(r.get(tile.get("den_column"), 0) or 0) for r in rows)
            return (num / den) if den > 0 else 0.0
        raise ExportError("bilinmeyen agg %r → INVALID_REQUEST" % kind)

    def _reconcile(self, job, exported):
        dash = job.get("dashboard", {}) or {}
        tiles = dash.get("tiles", []) or []
        recomputed = {}
        if not self.pol.get("reconcile", True):
            return recomputed                   # buggy: uzlaşma atlanır (dashboard mismatch yakalanmaz)
        groups = {}
        for t in tiles:
            got = self._agg(exported, t)
            recomputed[t.get("name")] = got
            want = float(t.get("value"))
            tol = float(t.get("tol", self.tol))
            if abs(got - want) > tol:
                self.reconciliation_violations += 1    # export dashboard'u YENİDEN ÜRETMİYOR (tutarsız)
            grp = t.get("group")
            if grp is not None:
                groups.setdefault(grp, []).append(got)
        if self.partition_sum_check:
            for grp, vals in groups.items():
                if abs(sum(vals) - 1.0) > self.tol:
                    self.reconciliation_violations += 1   # partition toplamı ≠ 1.0
        return recomputed

    # ── audit (G7) ─────────────────────────────────────────────────────────────
    def _audit(self, job, row_count):
        if not self.pol.get("audit", True):
            self.audit_violations += 1          # SESSİZ export (audit izi yok)
            return None
        actor = job.get("actor", {}) or {}
        rec = {
            "tenant_id": self.context.get("tenant_id"),
            "actor_role": actor.get("role"),
            "action_code": self.spec.get("audit", {}).get("action_code", "data_export"),
            "report_id": job.get("report_id"),
            "source": job.get("source"),
            "period": job.get("period"),
            "row_count": row_count,
            "format": job.get("format"),
        }
        # audit izi İÇERİK/PII taşımaz (no_content_in_audit)
        for k, v in rec.items():
            if _pii_value(v) or k in self.forbidden_keys:
                self.audit_violations += 1
        return rec

    def run(self, request):
        # G9 async/non-blocking (placement)
        if not self.pol.get("non_blocking", True):
            self.blocking_violations += 1
        if not self.spec.get("placement", {}).get("non_blocking", True):
            self.blocking_violations += 1

        jobs = request.get("exports")
        if not isinstance(jobs, list) or not jobs:
            raise ExportError("export işi (exports[]) eksik/boş → INVALID_REQUEST")

        seen_export = set()
        results = []
        for job in jobs:
            if not isinstance(job, dict):
                raise ExportError("export işi sözlük değil → INVALID_REQUEST")
            source = job.get("source")
            fmt = job.get("format")
            if not job.get("report_id") or source is None or fmt is None:
                raise ExportError("export kimliği eksik (report_id/source/format) → INVALID_REQUEST")
            if source not in self.source_catalog:
                raise ExportError("bilinmeyen kaynak %r (export_sources dışı) → INVALID_REQUEST" % source)
            if fmt not in self.supported_formats:
                raise ExportError("bilinmeyen format %r (supported_formats dışı) → INVALID_REQUEST" % fmt)

            # G8 idempotency: aynı export bir kez
            ekey = (self.context.get("tenant_id"), job.get("report_id"), source, job.get("period"),
                    fmt, job.get("schema_version", self.schema_version))
            if ekey in seen_export:
                self.idempotency_violations += 1
                if self.pol.get("idempotent", True):
                    continue                    # daraltılır (ilk export tutulur)
            seen_export.add(ekey)

            # G5 yetki
            self._authorize(job)

            # kaynak OLAP sütun kataloğu (non-circular)
            src_cols, pii_by_col, src_max_pii = _olap_source_columns(self.olap, source)
            if src_max_pii is not None and src_max_pii not in self.max_pii_allowed:
                self.pii_violations += 1        # kaynak max_pii_class izinli sınıf dışı (A4)

            columns = self._check_columns(job, src_cols, pii_by_col)
            self._check_rows(job, columns)

            # G6 izolasyon → kalan satırlar
            rows = self._isolate(list(job.get("rows", [])))

            # G1 bütünlük
            exported, row_count, expected, checksum = self._materialize(job, rows)

            # G2 uzlaşma
            recomputed = self._reconcile(job, exported)

            # G7 audit
            audit_rec = self._audit(job, row_count)

            max_pii = "none"
            if src_max_pii in PII_CLASS_ALLOWED:
                max_pii = src_max_pii
            manifest = {
                "report_id": job.get("report_id"), "tenant_id": self.context.get("tenant_id"),
                "source": source, "period": job.get("period"), "format": fmt,
                "schema_version": job.get("schema_version", self.schema_version),
                "row_count": row_count, "checksum": checksum, "max_pii_class": max_pii,
            }
            results.append({
                "manifest": manifest, "row_count": row_count, "expected": expected,
                "reconciled": recomputed, "audit": audit_rec, "columns": columns,
            })

        self.derived["exports"] = results
        self.derived["exports_count"] = len(results)
        self.derived["rows_exported"] = sum(r["row_count"] for r in results)
        self.derived["reconciled_tiles"] = sum(len(r["reconciled"]) for r in results)

    def metrics(self):
        return {
            "fidelity_violations": self.fidelity_violations,
            "reconciliation_violations": self.reconciliation_violations,
            "format_violations": self.format_violations,
            "pii_violations": self.pii_violations,
            "authz_violations": self.authz_violations,
            "isolation_violations": self.isolation_violations,
            "audit_violations": self.audit_violations,
            "idempotency_violations": self.idempotency_violations,
            "blocking_violations": self.blocking_violations,
            "derived": dict(self.derived),
        }


def export_request(sample, spec, profile, context, policy, olap=None):
    request = sample.get("request")
    if not isinstance(request, dict):
        raise ExportError("export isteği (request) sözlük değil → INVALID_REQUEST")
    eng = DataExportEngine(spec, profile, context, policy, olap=olap)
    eng.run(request)
    return eng.metrics()


def evaluate(spec, m):
    """Metrikleri HARD kapılara (G1–G9) karşı değerlendirir. Döner findings[(ok, label)]."""
    g = spec.get("gates", {})
    F = []
    F.append((m.get("fidelity_violations", 0) <= g.get("max_fidelity_violation", 0),
              "G1 export bütünlüğü ihlali %d ≤ %d (satır sayısı==sorgulanan; düşme/hayalet yok; manifest row_count + deterministik sıra/checksum; SR-ANA-011 'üretilir') — BİRİNCİL"
              % (m.get("fidelity_violations", 0), g.get("max_fidelity_violation", 0))))
    F.append((m.get("reconciliation_violations", 0) <= g.get("max_reconciliation_violation", 0),
              "G2 uzlaşma ihlali %d ≤ %d (export satırlarının yeniden-agregasyonu == dashboard tile; partition toplamı=1.0; SR-ANA-011 'TUTARLIDIR')"
              % (m.get("reconciliation_violations", 0), g.get("max_reconciliation_violation", 0))))
    F.append((m.get("format_violations", 0) <= g.get("max_format_violation", 0),
              "G3 format ihlali %d ≤ %d (format ∈ supported; export sütunları kaynağın OLAP kataloğunda — BİREBİR non-circular)"
              % (m.get("format_violations", 0), g.get("max_format_violation", 0))))
    F.append((m.get("pii_violations", 0) <= g.get("max_pii_violation", 0),
              "G4 PII ihlali %d ≤ %d (export YALNIZ redaksiyonlu/agregat sütun pii_class∈{none,low,redacted}; ham transkript/ses/kayıt URI/PII DEĞERİ yok — FR-REC-004/005)"
              % (m.get("pii_violations", 0), g.get("max_pii_violation", 0))))
    F.append((m.get("authz_violations", 0) <= g.get("max_authz_violation", 0),
              "G5 yetki ihlali %d ≤ %d (export analytics:read ister; backend kararı; platform L0 altın kural — FR-IAM-008/011) — İKİNCİL"
              % (m.get("authz_violations", 0), g.get("max_authz_violation", 0))))
    F.append((m.get("isolation_violations", 0) <= g.get("max_isolation_violation", 0),
              "G6 izolasyon ihlali %d ≤ %d (tek tenant_id + cross-tenant yok + residency — FR-TEN-002/NFR 10.7)"
              % (m.get("isolation_violations", 0), g.get("max_isolation_violation", 0))))
    F.append((m.get("audit_violations", 0) <= g.get("max_audit_violation", 0),
              "G7 audit ihlali %d ≤ %d (her export → governance.audit.v1 data_export WORM izi; SESSİZ export yok; içerik/PII taşımaz)"
              % (m.get("audit_violations", 0), g.get("max_audit_violation", 0))))
    F.append((m.get("idempotency_violations", 0) <= g.get("max_idempotency_violation", 0),
              "G8 idempotency ihlali %d ≤ %d ((tenant,report,source,period,format,schema) bir kez; duplicate export yok)"
              % (m.get("idempotency_violations", 0), g.get("max_idempotency_violation", 0))))
    F.append((m.get("blocking_violations", 0) <= g.get("max_blocking_violation", 0),
              "G9 blocking ihlali %d ≤ %d (analytics plane non-blocking; export canlı çağrıyı etkilemez — FR-RES-011)"
              % (m.get("blocking_violations", 0), g.get("max_blocking_violation", 0))))
    return F


# ─────────────────────────────────────────────────────────────────────────────
# bağlam + politika çözümleme
# ─────────────────────────────────────────────────────────────────────────────
def _profile_by_name(cfg, name):
    for p in cfg.get("profiles", []):
        if p.get("name") == name:
            return p
    raise ExportError("bilinmeyen profil: %s" % name)


def _resolve_context(spec, profile, sample):
    ctx = dict(sample.get("context", {}))
    ctx.setdefault("region", profile.get("region"))
    return ctx


def _full_pol():
    return {"preserve_all_rows": True, "deterministic_order": True, "reconcile": True, "enforce_schema": True,
            "enforce_redaction": True, "authorize": True, "isolate_tenant": True, "audit": True,
            "idempotent": True, "non_blocking": True}


def _resolve_policy(spec, sample):
    pol = _full_pol()
    pol.update(sample.get("policy", {}))
    return pol


def export_cmd(sample_path):
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
        except ExportError as ex:
            print("export[%s]: %s" % (name, ex))
            return 0 if expect == "fail" else 1
    context = _resolve_context(spec, profile, sample)
    policy = _resolve_policy(spec, sample)

    try:
        m = export_request(sample, spec, profile, context, policy)
    except ExportError as ex:
        print("export[%s]: REDDEDİLDİ — %s" % (name, ex))
        return 0 if expect == "fail" else 1

    F = evaluate(spec, m)
    d = m.get("derived", {})
    print("export[%s] %d export, %d satır, %d tile uzlaştı | bütünlük=%d uzlaşma=%d format=%d pii=%d yetki=%d izolasyon=%d audit=%d idempotency=%d blocking=%d" % (
        name, d.get("exports_count", 0), d.get("rows_exported", 0), d.get("reconciled_tiles", 0),
        m["fidelity_violations"], m["reconciliation_violations"], m["format_violations"], m["pii_violations"],
        m["authz_violations"], m["isolation_violations"], m["audit_violations"],
        m["idempotency_violations"], m["blocking_violations"]))
    for r in d.get("exports", []):
        man = r["manifest"]
        print("    %s [%s/%s] satır=%d (beklenen=%d) checksum=%s… max_pii=%s" % (
            man["report_id"], man["source"], man["format"], r["row_count"], r["expected"],
            man["checksum"][:12], man["max_pii_class"]))
        for tn, tv in r["reconciled"].items():
            print("      uzlaşma %-22s = %.6f" % (tn, tv))
    for ok, label in F:
        print("  %s %s" % ("✓" if ok else "✗", label))
    gate_ok = all(ok for ok, _ in F) and len(F) > 0

    exp = sample.get("expected", {})
    for k, v in exp.items():
        got = m.get(k)
        match = (got == v)
        print("  %s expected.%s == %r (got %r)" % ("✓" if match else "✗", k, v, got))
        gate_ok = gate_ok and match
    exp_d = sample.get("expected_derived", {})
    for k, v in exp_d.items():
        got = d.get(k)
        match = (got == v)
        print("  %s expected_derived.%s == %r (got %r)" % ("✓" if match else "✗", k, v, got))
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


def _scan(obj, regex, path="root"):
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.startswith("$"):
                continue
            hits += _scan(v, regex, "%s.%s" % (path, k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits += _scan(v, regex, "%s[%d]" % (path, i))
    elif isinstance(obj, str):
        if _is_placeholder(obj):
            return hits
        if regex is PII_VALUE_RE and DATE_RE.match(obj):
            return hits                   # ISO tarih/period boyutu PII değil — muaf
        if regex.search(obj):
            hits.append((path, obj))
    return hits


def _rollup(olap, name):
    for r in olap.get("rollups", []):
        if r.get("name") == name:
            return r
    return None


def _fact(olap, name):
    for ft in olap.get("fact_tables", []):
        if ft.get("name") == name:
            return ft
    return None


def validate():
    spec = _load(SPEC_PATH)
    R = []

    _check(R, spec.get("wbs") == "14.2.8", "spec.wbs == 14.2.8")
    _check(R, spec.get("version"), "spec.version mevcut")
    _check(R, spec.get("phase") == "F2", "spec.phase == F2")
    _check(R, spec.get("priority") == "Must", "spec.priority == Must (FR-ANA-011)")
    ed = spec.get("eval_doc", {})
    for k in ("fr", "srs", "rtm", "brd", "sad", "db", "olap", "adr", "api", "frontend", "upstream"):
        _check(R, bool(ed.get(k)), "eval_doc.%s mevcut" % k)
    _check(R, "FR-ANA-011" in ed.get("fr", ""), "eval_doc.fr FR-ANA-011 (dashboard + ham veri export)")
    _check(R, "SR-ANA-011" in ed.get("srs", ""), "eval_doc.srs SR-ANA-011")

    # ── placement (G9)
    pl = spec.get("placement", {})
    _check(R, pl.get("in_analytics_plane") is True, "G9 motor analytics plane'de (SAD §4.2)")
    _check(R, pl.get("async_batch") is True, "G9 async batch (FR-RES-011)")
    _check(R, pl.get("non_blocking") is True, "G9 non-blocking (export canlı çağrıyı etkilemez)")
    _check(R, pl.get("from_redacted_content") is True, "G4 from_redacted_content (export OLAP redaksiyonlu)")
    _check(R, pl.get("read_only") is True, "I10 read_only (OLAP OKUR)")
    _check(R, pl.get("recomputes_metrics") is False, "I13 recomputes_metrics=false (metriği yeniden hesaplamaz — 14.2.x üretir)")
    _check(R, pl.get("deterministic") is True, "I11 deterministic (sıralama + sha256; random yok)")
    _check(R, pl.get("idempotent") is True, "G8 idempotent")
    _check(R, pl.get("from_trace") is False, "from_trace=false (export agregat/satır üzerinedir)")

    # ── export_format (G1/G3)
    ef = spec.get("export_format", {})
    sf = set(ef.get("supported_formats", []))
    _check(R, {"csv", "jsonl"} <= sf, "G3 supported_formats csv+jsonl içerir")
    _check(R, ef.get("default_format") in sf, "G3 default_format supported_formats'ta")
    _check(R, ef.get("checksum_algo") == "sha256", "G1 checksum_algo == sha256 (deterministik)")
    _check(R, ef.get("deterministic_order") is True, "G1/I3 deterministic_order (kararlı sıra → aynı checksum)")
    _check(R, {"report_id", "row_count", "checksum"} <= set(ef.get("manifest_fields", [])),
           "G1 manifest_fields report_id/row_count/checksum içerir")

    # ── export_sources (G3 / I4 non-circular)
    es = spec.get("export_sources", {})
    srcs = es.get("sources", {})
    _check(R, isinstance(srcs, dict) and len(srcs) >= 2, "G3 export_sources ≥2 kaynak")
    _check(R, set(es.get("max_pii_class_allowed", [])) <= PII_CLASS_ALLOWED,
           "G4 max_pii_class_allowed ⊆ {none,low,redacted}")
    for sn, sd in srcs.items():
        _check(R, sd.get("kind") in ("rollup", "fact"), "G3 %s kind ∈ {rollup,fact}" % sn)

    # ── reconciliation (G2)
    rc = spec.get("reconciliation", {})
    _check(R, {"count", "sum", "rate"} <= set(rc.get("agg_kinds", [])), "G2 agg_kinds count/sum/rate içerir")
    _check(R, isinstance(rc.get("tolerance"), (int, float)) and rc.get("tolerance") >= 0, "G2 tolerance ≥ 0")
    _check(R, rc.get("partition_sum_check") is True, "G2 partition_sum_check (handled paydası toplamı 1.0)")

    # ── authorization (G5)
    az = spec.get("authorization", {})
    _check(R, az.get("required_permission") == "analytics:read", "G5 required_permission == analytics:read (ADR-012)")
    _check(R, az.get("decided_in_backend") is True, "G5 decided_in_backend (yetki kararı backend'de)")
    _check(R, az.get("platform_l0_forbidden") is True, "G5 platform_l0_forbidden (altın kural FR-IAM-008)")
    _check(R, az.get("unauthorized_error") == "AUTH", "G5 unauthorized_error == AUTH")
    _check(R, "human_agent" in set(az.get("forbidden_roles_illustrative", [])),
           "G5 human_agent forbidden (A-14: erişim YOK)")
    _check(R, set(az.get("forbidden_roles_illustrative", [])) & {"platform_owner", "platform_sre"},
           "G5 platform L0 rolleri forbidden_roles'ta (altın kural)")

    # ── audit (G7)
    au = spec.get("audit", {})
    _check(R, au.get("topic") == "governance.audit.v1", "G7 audit topic governance.audit.v1")
    _check(R, au.get("action_code") == "data_export", "G7 action_code data_export")
    _check(R, au.get("no_silent_export") is True, "G7 no_silent_export (audit'siz export yok)")
    _check(R, au.get("no_content_in_audit") is True, "G7 no_content_in_audit (audit içerik/PII taşımaz)")
    _check(R, au.get("append_only_worm") is True, "G7 append_only_worm")

    # ── row_integrity (G1)
    ri = spec.get("row_integrity", {})
    _check(R, ri.get("requires_order_by") is True, "G1 requires_order_by (deterministik sıra)")
    _check(R, ri.get("requires_dedup_key") is True, "G1 requires_dedup_key (benzersizlik)")
    _check(R, ri.get("no_silent_drop") is True, "G1 no_silent_drop")

    # ── feature_policy (G4)
    fp = spec.get("feature_policy", {})
    forb = set(fp.get("forbidden_export_keys", []))
    _check(R, {"transcript_text", "audio_payload", "recording_uri", "phone_number", "card_number"} <= forb,
           "G4 forbidden_export_keys ham transkript/ses/kayıt/PII içerir")
    _check(R, {"human_comment", "comment_text"} <= forb, "G4 forbidden_export_keys serbest-metin yorum içerir")

    # ── isolation (G6)
    iso = spec.get("isolation", {})
    _check(R, iso.get("tenant_id_required") is True, "G6 tenant_id_required")
    _check(R, iso.get("residency") == "home-region", "G6 residency home-region (NFR 10.7)")
    _check(R, iso.get("cross_tenant_forbidden") is True, "G6 cross_tenant_forbidden (FR-TEN-002)")

    # ── idempotency (G8)
    idem = spec.get("idempotency", {})
    _check(R, idem.get("dedup_key") == ["tenant_id", "report_id", "source", "period", "format", "schema_version"],
           "G8 dedup_key (tenant,report,source,period,format,schema)")
    _check(R, idem.get("replay_safe") is True, "G8 replay_safe (1.1.8 P3)")
    _check(R, idem.get("deterministic_content") is True, "I11 deterministic_content (aynı sorgu → aynı checksum)")

    # ── OLAP cross-check (I4 / G3 non-circular)
    olap = _load_sibling_spec("analytics", "olap-spec.json")
    if olap is not None:
        for sn in srcs:
            present = (_rollup(olap, sn) is not None) or (_fact(olap, sn) is not None)
            _check(R, present, "G3 export kaynağı %s OLAP rollups/fact_tables'ta (non-circular)" % sn)
        mvu = _rollup(olap, "mv_usage_daily")
        if mvu is not None:
            _check(R, "FR-ANA-011" in mvu.get("dashboard_fr", []),
                   "I4 mv_usage_daily dashboard_fr FR-ANA-011 (export izlenebilirliği)")
        fc = _fact(olap, "fct_call")
        if fc is not None:
            classes = {c.get("pii_class") for c in fc.get("columns", [])}
            _check(R, classes <= PII_CLASS_ALLOWED,
                   "G4 fct_call sütun pii_class'ları ⊆ {none,low,redacted} (A4 — ham PII OLAP'a yazılmaz)")
            _check(R, fc.get("max_pii_class") in PII_CLASS_ALLOWED, "G4 fct_call max_pii_class izinli sınıfta")

    # ── gates
    g = spec.get("gates", {})
    for gk in ("max_fidelity_violation", "max_reconciliation_violation", "max_format_violation",
               "max_pii_violation", "max_authz_violation", "max_isolation_violation",
               "max_audit_violation", "max_idempotency_violation", "max_blocking_violation"):
        _check(R, g.get(gk, -1) == 0, "gate %s = 0" % gk)

    # ── error taxonomy (I12)
    et = spec.get("error_taxonomy", {}).get("mapping", {})
    _check(R, len(et) >= 3, "I12 hata eşlemesi (≥3)")
    _check(R, all(v in ERROR_TAXONOMY for v in et.values()), "I12 tüm hedefler API §11.6 ErrorTaxonomy'de")
    _check(R, et.get("unknown_source") == "INVALID_REQUEST" and et.get("unauthorized_export") == "AUTH"
           and et.get("cross_tenant") == "AUTH" and et.get("region_mismatch") == "REGION_VIOLATION",
           "I12 unknown_source→INVALID_REQUEST, unauthorized/cross_tenant→AUTH, region→REGION_VIOLATION")

    # ── pii (spec sağlığı, I15)
    _check(R, spec.get("pii", {}).get("raw_payload_in_spec_forbidden") is True, "I15 ham ses payload spec'te yasak")
    _check(R, spec.get("pii", {}).get("transcript_in_spec_forbidden") is True, "I15 transkript spec'te yasak")
    _check(R, spec.get("pii", {}).get("pii_values_in_spec_forbidden") is True, "I15 PII DEĞERİ spec'te yasak")

    # ── invariant kataloğu
    inv_ids = [i.get("id") for i in spec.get("invariants", [])]
    _check(R, len(inv_ids) == len(set(inv_ids)) and len(inv_ids) >= 15, "invariant kataloğu ≥15 + tekil ID")
    _check(R, all(i.get("trace") for i in spec.get("invariants", [])), "her invariant trace taşır")

    # ── literal sır + PII DEĞER taraması (spec + config)
    hits = _scan(spec, SECRET_RE)
    pii_hits = _scan(spec, PII_VALUE_RE)
    if os.path.exists(PROFILES_CFG):
        cfg = _load(PROFILES_CFG)
        hits += _scan(cfg, SECRET_RE)
        pii_hits += _scan(cfg, PII_VALUE_RE)
    _check(R, not hits, "I15 literal sır yok (spec+config)")
    _check(R, not pii_hits, "I15 spec/config'te ham PII DEĞERİ yok (%s)" % (",".join(p for p, _ in pii_hits[:3]) or "-"))

    # ── config profilleri
    if os.path.exists(PROFILES_CFG):
        cfg = _load(PROFILES_CFG)
        profs = cfg.get("profiles", [])
        _check(R, len(profs) >= 2, "config ≥2 profil")
        pnames = [p.get("name") for p in profs]
        _check(R, len(pnames) == len(set(pnames)), "config profil isimleri benzersiz")
        for p in profs:
            _check(R, bool(p.get("region")), "residency config %s bölge pini var" % p.get("name"))
            _check(R, isinstance(p.get("schema_version"), int) and p.get("schema_version") > 0,
                   "config %s schema_version > 0 (idempotency)" % p.get("name"))
            _check(R, p.get("default_format") in sf, "config %s default_format supported" % p.get("name"))

    passed = sum(1 for ok, _ in R if ok)
    total = len(R)
    for ok, label in R:
        if not ok:
            print("  ✗ %s" % label)
    print("validate: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


# ─────────────────────────────────────────────────────────────────────────────
# selftest
# ─────────────────────────────────────────────────────────────────────────────
CONTEXT = {"tenant_id": "t_acme", "region": "eu-west-1", "correlation_id": "corr-acme-001"}
PROFILE = {"name": "eu-standard", "region": "eu-west-1", "schema_version": 1, "default_format": "csv"}
AUTHORIZED = {"role": "operations_manager", "permissions": ["analytics:read"]}


def _rows_daily(n=3, contained=None):
    """mv_call_daily satırları üretir (event_date + calls + contained_calls)."""
    rows = []
    base_calls = [100, 80, 120]
    base_cont = [70, 56, 84] if contained is None else contained
    for i in range(n):
        rows.append({"tenant_id": "t_acme", "event_date": "2026-06-%02d" % (i + 1),
                     "agent_id": "ag_support", "agent_version_id": "v2",
                     "calls": base_calls[i % 3], "contained_calls": base_cont[i % 3],
                     "transferred_calls": base_calls[i % 3] - base_cont[i % 3]})
    return rows


def _job(rows=None, **over):
    rows = _rows_daily() if rows is None else rows
    total_calls = sum(r["calls"] for r in rows)
    total_cont = sum(r["contained_calls"] for r in rows)
    job = {
        "report_id": "rep_daily_001", "source": "mv_call_daily", "format": "csv", "period": "2026-06",
        "schema_version": 1, "actor": dict(AUTHORIZED),
        "columns": ["tenant_id", "event_date", "agent_id", "agent_version_id", "calls", "contained_calls", "transferred_calls"],
        "order_by": ["event_date"], "dedup_key": ["event_date"],
        "dashboard": {"tiles": [
            {"name": "total_calls", "agg": "sum", "column": "calls", "value": total_calls},
            {"name": "days", "agg": "count", "value": len(rows)},
            {"name": "containment_rate", "agg": "rate", "num_column": "contained_calls", "den_column": "calls",
             "value": (total_cont / total_calls) if total_calls else 0.0},
        ]},
        "rows": rows,
    }
    job.update(over)
    return job


def _run(jobs, context=None, profile=None, olap="none", **pol_over):
    pol = _full_pol()
    pol.update(pol_over)
    spec = _load(SPEC_PATH)
    o = None if olap == "none" else olap
    return export_request({"request": {"exports": jobs}}, spec, dict(profile or PROFILE),
                          context or CONTEXT, pol, olap=o)


def _raises(fn):
    try:
        fn()
        return False
    except ExportError:
        return True


def selftest():
    spec = _load(SPEC_PATH)
    cases = []

    def case(ok, label):
        cases.append((bool(ok), label))

    OLAP = _load_sibling_spec("analytics", "olap-spec.json")

    # 1 — happy path: tüm kapı geçer
    m = _run([_job()])
    case(all(ok for ok, _ in evaluate(spec, m)), "happy-path tüm HARD kapı geçer (G1–G9)")
    case(m["derived"]["exports_count"] == 1 and m["derived"]["rows_exported"] == 3,
         "happy-path 1 export, 3 satır")
    case(m["derived"]["reconciled_tiles"] == 3, "happy-path 3 tile uzlaştı")

    # 2 — determinizm: aynı girdi → aynı checksum
    a = _run([_job()])["derived"]["exports"][0]["manifest"]["checksum"]
    b = _run([_job()])["derived"]["exports"][0]["manifest"]["checksum"]
    case(a == b and len(a) == 64, "determinizm: aynı sorgu → aynı sha256 checksum (random yok)")
    # satır sırası değişse de checksum aynı (deterministik sıralama)
    shuffled = list(reversed(_rows_daily()))
    c = _run([_job(rows=shuffled)])["derived"]["exports"][0]["manifest"]["checksum"]
    case(a == c, "deterministik sıralama: girdi sırası farklı → aynı checksum (order_by)")

    # 3 — G1 bütünlük: satır düşürme
    case(_run([_job()], preserve_all_rows=False)["fidelity_violations"] >= 1,
         "G1 preserve_all_rows kapalı: satır düşer → bütünlük eler")
    case(_run([_job()], deterministic_order=False)["fidelity_violations"] >= 1,
         "G1 deterministic_order kapalı: sırasız çıktı → bütünlük eler")
    j = _job(); j["order_by"] = []
    case(_run([j])["fidelity_violations"] >= 1, "G1 order_by yok → bütünlük eler (deterministik sıra)")
    j2 = _job(); j2["dedup_key"] = []
    case(_run([j2])["fidelity_violations"] >= 1, "G1 dedup_key yok → bütünlük eler")
    # expected_row_count mismatch
    j3 = _job(); j3["expected_row_count"] = 5
    case(_run([j3])["fidelity_violations"] >= 1, "G1 sorgulanan(5)≠export(3) → bütünlük eler")

    # 4 — G2 uzlaşma: yanlış tile değeri
    jb = _job(); jb["dashboard"]["tiles"][0]["value"] = 999
    case(_run([jb])["reconciliation_violations"] >= 1,
         "G2 dashboard tile (total_calls=999) export'la uzlaşmıyor → uzlaşma eler")
    case(_run([_job()], reconcile=False)["reconciliation_violations"] == 0,
         "G2 reconcile kapalı: uzlaşma atlanır (mismatch yakalanmaz — risk göstergesi)")
    # partition toplamı ≠ 1.0
    jp = _job()
    jp["dashboard"]["tiles"] = [
        {"name": "contained", "agg": "rate", "num_column": "contained_calls", "den_column": "calls",
         "value": 0.70, "group": "outcome", "tol": 0.01},
        {"name": "transferred", "agg": "rate", "num_column": "transferred_calls", "den_column": "calls",
         "value": 0.30, "group": "outcome", "tol": 0.01},
    ]
    mp = _run([jp])
    case(mp["reconciliation_violations"] == 0, "G2 partition contained+transferred=1.0 → uzlaşır")

    # 5 — G3 format/şema
    case(_raises(lambda: _run([_job(source="bogus")])), "G3 bilinmeyen kaynak → reddedilir")
    case(_raises(lambda: _run([_job(format="xlsx")])), "G3 bilinmeyen format → reddedilir")
    if OLAP is not None:
        jc = _job(); jc["columns"] = jc["columns"] + ["not_a_real_column"]
        case(_run([jc], olap=OLAP)["format_violations"] >= 1,
             "G3 kaynak kataloğunda olmayan sütun → format eler (OLAP non-circular)")
    jx = _job(); jx["rows"][0]["undeclared"] = 1
    case(_run([jx])["format_violations"] >= 1, "G3 bildirilmemiş satır anahtarı → format eler")

    # 6 — G4 PII
    jf = _job(); jf["columns"] = jf["columns"] + ["transcript_text"]
    case(_run([jf])["pii_violations"] >= 1, "G4 transcript_text sütunu → PII eler")
    jv = _job(); jv["rows"][0]["note"] = "+90 532 111 22 33"; jv["columns"].append("note")
    case(_run([jv])["pii_violations"] >= 1, "G4 cell DEĞERİnde ham telefon → PII eler")
    case(_run([_job()], enforce_redaction=False)["pii_violations"] == 0,
         "G4 enforce_redaction kapalı: leak taranmaz (risk göstergesi)")

    # 7 — G5 yetki
    case(_run([_job(actor={"role": "human_agent", "permissions": ["analytics:read"]})])["authz_violations"] >= 1,
         "G5 human_agent (A-14 erişim yok) → yetki eler")
    case(_run([_job(actor={"role": "operations_manager", "permissions": []})])["authz_violations"] >= 1,
         "G5 analytics:read izni yok → yetki eler")
    case(_run([_job(actor={"role": "platform_sre", "permissions": ["analytics:read"]})])["authz_violations"] >= 1,
         "G5 platform L0 (altın kural) → yetki eler")
    case(_run([_job()])["authz_violations"] == 0, "G5 yetkili (operations_manager+analytics:read) → geçer")

    # 8 — G6 izolasyon
    ji = _job(); ji["rows"][0]["tenant_id"] = "t_other"
    case(_run([ji])["isolation_violations"] >= 1, "G6 cross-tenant satır → izolasyon eler")
    jr = _job(); jr["rows"][0]["home_region"] = "us-east-1"
    case(_run([jr])["isolation_violations"] >= 1, "G6 home-region dışı satır → izolasyon eler (NFR 10.7)")

    # 9 — G7 audit
    case(_run([_job()], audit=False)["audit_violations"] >= 1, "G7 audit kapalı: SESSİZ export → audit eler")
    ar = _run([_job()])["derived"]["exports"][0]["audit"]
    case(ar is not None and ar.get("action_code") == "data_export" and "row_count" in ar,
         "G7 audit izi data_export + row_count (kim/ne zaman/hangi rapor)")

    # 10 — G8 idempotency: duplicate export
    case(_run([_job(), _job()], idempotent=False)["idempotency_violations"] >= 1,
         "G8 duplicate export (idempotent kapalı) → idempotency eler")
    case(_run([_job(), _job()])["idempotency_violations"] >= 1,
         "G8 idempotent açık: duplicate yine tespit + daraltılır")

    # 11 — G9 non-blocking + reddetme
    case(_run([_job()], non_blocking=False)["blocking_violations"] >= 1, "G9 non_blocking kapalı → blocking eler")
    case(_raises(lambda: _run([])), "boş exports[] → reddedilir (INVALID_REQUEST)")
    case(_raises(lambda: export_request({"request": {"exports": [{"source": "mv_call_daily"}]}},
                                        spec, dict(PROFILE), CONTEXT, _full_pol())),
         "report_id/format eksik → reddedilir")

    # 12 — bağlam eksik
    case(_raises(lambda: export_request({"request": {"exports": [_job()]}}, spec, dict(PROFILE),
                                        {"region": "eu-west-1"}, _full_pol())),
         "tenant_id bağlamı yok → reddedilir (INVALID_REQUEST)")

    passed = sum(1 for ok, _ in cases if ok)
    total = len(cases)
    for ok, label in cases:
        print("  %s %s" % ("✓" if ok else "✗", label))
    print("selftest: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


def schema():
    print("""data-export-spec.json beklenen şekli (WBS 14.2.8):
  wbs=14.2.8, version, phase=F2, priority=Must,
  eval_doc{fr,srs,rtm,brd,sad,db,olap,adr,api,frontend,upstream}
  placement{in_analytics_plane, async_batch, non_blocking, from_redacted_content, read_only=true,
            recomputes_metrics=false, deterministic, idempotent, from_trace=false}                (G9,G4,I10,I13)
  export_format{supported_formats[csv,jsonl,ndjson], default_format, manifest_fields[],
                checksum_algo=sha256, deterministic_order=true}                                    (G1,G3,I3)
  export_sources{sources{<name>{kind(rollup|fact), fr}}, max_pii_class_allowed[none,low,redacted]} (G3,G4,I4)
  reconciliation{agg_kinds[count,sum,rate], tolerance, partition_sum_check=true}                   (G2)
  authorization{required_permission=analytics:read, decided_in_backend, platform_l0_forbidden,
                unauthorized_error=AUTH, allowed/forbidden_roles_illustrative}                     (G5)
  audit{topic=governance.audit.v1, action_code=data_export, append_only_worm, no_silent_export,
        audit_fields[], no_content_in_audit}                                                       (G7)
  row_integrity{requires_order_by, requires_dedup_key, no_silent_drop}                             (G1)
  feature_policy{forbidden_export_keys[ham transkript/ses/kayıt/PII/serbest-metin]}                (G4)
  isolation{tenant_id_required, residency=home-region, cross_tenant_forbidden}                     (G6)
  idempotency{dedup_key=[tenant,report,source,period,format,schema], replay_safe, deterministic_content} (G8)
  gates{max_*_violation=0 (G1..G9)}  error_taxonomy{mapping→API §11.6}  pii{...}  invariants[≥15]

config/data-export-profiles.json: profiles[]{name, region, schema_version, default_format}

export sample: {name, profile | profile_obj, expect, expected?{sayaç}, expected_derived?{özet},
  context{tenant_id, region?},
  policy?{preserve_all_rows, deterministic_order, reconcile, enforce_schema, enforce_redaction, authorize,
          isolate_tenant, audit, idempotent, non_blocking},
  request{exports[]{report_id, source, format, period, schema_version?, actor{role,permissions[]},
                    columns[], order_by[], dedup_key[], expected_row_count?,
                    dashboard{tiles[]{name, agg(count|sum|rate), value, column?|num_column?+den_column?, group?, tol?}},
                    rows[]{<col>:<value>}}}}
  (PII DEĞERİ / ham transkript / kayıt URI YOK — yalnız OLAP redaksiyonlu/agregat satır + boyut ADLARI)

komutlar: validate | export <sample.json> | selftest | schema""")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if cmd == "validate":
        return validate()
    if cmd == "export":
        if len(sys.argv) < 3:
            print("kullanım: export_probe.py export <sample.json>")
            return 2
        return export_cmd(sys.argv[2])
    if cmd == "selftest":
        return selftest()
    if cmd == "schema":
        return schema()
    print("bilinmeyen komut: %s (validate|export|selftest|schema)" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main())
