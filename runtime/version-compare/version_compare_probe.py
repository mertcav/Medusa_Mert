#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
version_compare_probe.py — WBS 14.2.7 Agent sürümleri performans karşılaştırma

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only statik + davranış kapısı.
`runtime/containment-report/` (14.2.3) probe disipliniyle birebir; burada deterministik bir ANALYTICS-PLANE
SÜRÜM KARŞILAŞTIRMA (VERSION COMPARISON) motoru (SAD §4.2 async batch; analytics-ingest consumer) simülatörü
(saf istatistik; random YOK).

KARŞILAŞTIRMA MOTORU — Analytics/Ops Plane'de (SAD §4.2/§171, FR-RES-011) async/non-blocking; 14.2.1 (auto_score,
FR-ANA-001) + 14.2.3 (containment_rate/transfer_rate, FR-ANA-003) + 14.2.4/14.2.5 (critical_rate, FR-ANA-004/008)
tarafından üretilen SÜRÜM-BAŞI agregat metrikleri (OLAP mv_agent_version_perf rollup) tüketir ve AYNI agent'ın
İKİ (veya daha çok) sürümünü (baseline ↔ candidate) metrik-metrik YAN YANA KARŞILAŞTIRIR (SR-ANA-010). Metriği
YENİDEN HESAPLAMAZ — KARŞILAŞTIRIR: işaretli delta + yön-duyarlı iyileşme + İSTATİSTİKSEL ANLAMLILIK + bastırma:
  • Bütünlük (G1):    karşılaştırılan kollar AYNI agent_id + tenant + period + metrik tanımı (apples-to-apples);
                      cross-agent/cross-tenant/cross-period/cross-metric YASAK; baseline≠candidate — BİRİNCİL.
  • Anlamlılık (G3):  improved/regressed YALNIZ |z|≥z_critical VE her iki kol ≥min_sample_n ile; aksi inconclusive
                      (gürültüden yapay kazanan YOK) — İKİNCİL çekirdek.
  • Delta (G2):       delta=candidate−baseline; improvement direction'a göre (higher/lower_is_better); winner tutarlı.
  • Katalog (G4):     metrik metric_catalog + mv_agent_version_perf/fct_qa_evaluation ile BİREBİR (non-circular).
  • İdempotent (G5):  (tenant,agent,baseline,candidate,period,schema) bir kez; duplicate version arm ihlal.
  • Bastırma (G6):    kol örneği < min_sample_n → karşılaştırma yayımlanmaz (insufficient_sample); k-anon + istatistik.
  • İzolasyon (G7):   tek tenant_id + cross-tenant yok + residency (FR-TEN-002/NFR 10.7).
  • PII (G8):         yalnız redaksiyonlu agregat metrik (sufficient stats) + düşük-kardinalite boyut (FR-REC-004).
  • Async (G9):       analytics plane non-blocking; karşılaştırma başarısızlığı canlı çağrıyı etkilemez (FR-RES-011).

KAPSAM AYRIMI: otomatik skor → 14.2.1 · per-call çıkarım → 14.2.2 · oran agregasyonu → 14.2.3 (bu motorun GİRDİSİ;
metriği bu motor YENİDEN HESAPLAMAZ, KARŞILAŞTIRIR) · işaretler → 14.2.4 · kritik → 14.2.5 · MANUEL skor → 14.2.6 ·
dashboard/export → 14.2.8. Burada YALNIZ sürüm-arası karşılaştırma + apples-to-apples bütünlüğü + anlamlılık.

Komutlar:
  validate              version-compare-spec.json'ı invariant'lara + OLAP çapraz-tutarlılığa + config'e karşı doğrular.
  compare <sample>      Deterministik VersionCompareEngine — kollar → pair/metrik delta+z+verdict + HARD kapılar (G1–G9); →çıkış kodu.
  selftest              İyi/kötü spec+sample ile kapıların doğru tetiklendiğini kanıtlar.
  schema                Beklenen spec şeklini özetler.

Sunucu/credential GEREKMEZ. compare gerçek motor yerine deterministik simülasyondur (canlıda mv_agent_version_perf
consumer + OLAP sink, SAD §4.2/§12.1; ADR-007). Ham ses payload/transkript METNİ/PII DEĞERİ YOK — örnekler yalnız
REDAKSİYONLU agregat metrik (sufficient stats) + düşük-kardinalite boyut/kimlik anahtarı ADLARI taşır.
"""
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "version-compare-spec.json")
PROFILES_CFG = os.path.join(HERE, "config", "version-compare-profiles.json")

ERROR_TAXONOMY = {
    "TIMEOUT", "RATE_LIMITED", "UNAVAILABLE", "AUTH",
    "INVALID_REQUEST", "CONTENT_FILTERED", "QUOTA_EXCEEDED", "REGION_VIOLATION",
}
SECRET_RE = re.compile(
    r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer)\b\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}"
)
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")
# Ham PII DEĞER desenleri (girdi/çıktıda yasak — FR-REC-004). Yalnız anahtar ADI olmalı.
PII_VALUE_RE = re.compile(
    r"(?:\d[ \-]?){7,}"                                   # ≥7 ardışık rakam (telefon/kart/IBAN)
    r"|[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"  # e-posta
    r"|\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b"                  # IBAN
)
# ISO tarih/period boyutu (ör. 2026-06 veya 2026-06-01) düşük-kardinalite boyut anahtarıdır — PII DEĞİL.
DATE_RE = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")
TOL = 1e-12


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_placeholder(v):
    return isinstance(v, str) and PLACEHOLDER_RE.match(v) is not None


def _pii_value(v):
    """v ham PII DEĞERİ mi (telefon/kart/IBAN/e-posta)? Placeholder ${ENV} ve ISO tarih/period boyutu muaf."""
    return isinstance(v, str) and not _is_placeholder(v) and not DATE_RE.match(v) and bool(PII_VALUE_RE.search(v))


class CompareError(Exception):
    """Geçersiz/eksik karşılaştırma girdisi veya bilinmeyen metrik — sessizce kabul yok, reddet (I12)."""


# ─────────────────────────────────────────────────────────────────────────────
# Sürüm karşılaştırma motoru — deterministik istatistik (saf; random YOK)
# ─────────────────────────────────────────────────────────────────────────────
class VersionCompareEngine:
    """Analytics plane'de async/non-blocking; sürüm-başı agregat metriği KARŞILAŞTIRIR + apples-to-apples bütünlüğü +
    istatistiksel anlamlılık + delta/yön + katalog + idempotency + bastırma + tenant izolasyon + PII disiplinine
    karşı denetler. Saf istatistik; random YOK.

    policy bayrakları buggy bir Engine'i simüle eder (14.2.3 deseni):
      same_agent          : kollar AYNI agent_id (kapalı → cross-agent kol karşılaştırılır, G1)
      same_period         : kollar AYNI period (kapalı → cross-period karşılaştırılır, G1)
      distinct_versions   : baseline ≠ candidate (kapalı → sürüm kendisiyle karşılaştırılır, G1)
      require_significance : improved/regressed yalnız anlamlı+yeterli (kapalı → ham delta işaretinden kazanan ilan, G3)
      correct_direction   : improvement yönü direction'a göre (kapalı → yön yok sayılır, G2)
      idempotent          : (tenant,agent,baseline,candidate,period,schema) bir kez (kapalı → duplicate version arm çift, G5)
      suppress_small      : kol örneği<min_sample_n bastır (kapalı → küçük-örnek kazanan yayımlanır, G6)
      isolate_tenant      : tek-tenant karşılaştırma (kapalı → cross-tenant kol karışır, G7)
      enforce_redaction   : ham PII/transkript girdisini reddet (kapalı → transcript_text geçer, G8)
      non_blocking        : analytics plane non-blocking (kapalı → karşılaştırma canlı çağrıyı bloklar, G9)
    """

    def __init__(self, spec, profile, context, policy):
        self.spec = spec
        self.context = dict(context or {})
        self.pol = policy

        mc = spec.get("metric_catalog", {})
        self.catalog = dict(mc.get("metrics", {}))

        sig = spec.get("significance", {})
        self.zc_map = {float(k): float(v) for k, v in sig.get("z_critical", {}).items()}
        self.confidence = float(profile.get("confidence", sig.get("confidence", 0.95)))
        self.min_sample_n = profile.get("min_sample_n", spec.get("small_sample", {}).get("min_sample_n", 30))
        self.suppressed_verdict = spec.get("small_sample", {}).get("suppressed_verdict", "insufficient_sample")

        vv = spec.get("verdict_vocabulary", {})
        self.significant_verdicts = set(vv.get("significant_verdicts", ["improved", "regressed"]))
        self.winner_of = dict(vv.get("winner_of", {}))

        fp = spec.get("feature_policy", {})
        self.allowed_keys = set(fp.get("allowed_input_keys", []))
        self.forbidden_keys = set(fp.get("forbidden_input_keys", []))

        self.region_pin = profile.get("region")
        self.schema_version = profile.get("schema_version", 1)

        if self.confidence not in self.zc_map:
            raise CompareError("bilinmeyen güven düzeyi: %r (z_critical yok) → INVALID_REQUEST" % self.confidence)
        self.z_crit = self.zc_map[self.confidence]

        if not self.context.get("tenant_id"):
            raise CompareError("karşılaştırma bağlamı eksik: tenant_id → INVALID_REQUEST")
        if not self.context.get("region"):
            raise CompareError("karşılaştırma bağlamı eksik: region → INVALID_REQUEST")

        # sayaçlar (HARD kapı kanıtı)
        self.comparison_integrity_violations = 0
        self.significance_violations = 0
        self.delta_violations = 0
        self.vocab_violations = 0
        self.idempotency_violations = 0
        self.suppression_violations = 0
        self.isolation_violations = 0
        self.pii_violations = 0
        self.blocking_violations = 0

        self.derived = {}

    # ── redaksiyonlu girdi denetimi (G8) ──────────────────────────────────────
    def _check_arm(self, arm):
        if not self.pol.get("enforce_redaction", True):
            return                       # buggy: redaction zorlanmaz
        for k, v in (arm or {}).items():
            if k == "metrics":
                # metrik sözlüğü: yalnız katalog metrik adı + sufficient-stat anahtarı + sayısal değer
                if isinstance(v, dict):
                    for mk, mv in v.items():
                        if _pii_value(mk):
                            self.pii_violations += 1
                        if isinstance(mv, dict):
                            for sk, sv in mv.items():
                                if _pii_value(sk) or _pii_value(sv):
                                    self.pii_violations += 1
                continue
            if k in self.forbidden_keys:
                self.pii_violations += 1
            elif k not in self.allowed_keys:
                self.pii_violations += 1   # whitelist dışı anahtar — potansiyel ham içerik
            if _pii_value(v):
                self.pii_violations += 1   # ham PII DEĞERİ

    # ── tek metrik karşılaştırması ────────────────────────────────────────────
    def _compare_metric(self, metric, base_stats, cand_stats):
        spec_m = self.catalog[metric]
        mtype = spec_m.get("type")
        direction = spec_m.get("direction")

        if mtype == "proportion":
            num1, den1 = float(base_stats["num"]), float(base_stats["den"])
            num2, den2 = float(cand_stats["num"]), float(cand_stats["den"])
            v1 = (num1 / den1) if den1 > 0 else 0.0
            v2 = (num2 / den2) if den2 > 0 else 0.0
            n1, n2 = den1, den2
            # iki-oran z-testi (pooled)
            if den1 > 0 and den2 > 0:
                pooled = (num1 + num2) / (den1 + den2)
                se = math.sqrt(pooled * (1.0 - pooled) * (1.0 / den1 + 1.0 / den2))
            else:
                se = 0.0
        elif mtype == "mean":
            v1 = float(base_stats["mean"])
            v2 = float(cand_stats["mean"])
            var1, var2 = float(base_stats["var"]), float(cand_stats["var"])
            n1, n2 = float(base_stats["n"]), float(cand_stats["n"])
            # büyük-örnek normal yaklaşım
            if n1 > 0 and n2 > 0:
                se = math.sqrt(var1 / n1 + var2 / n2)
            else:
                se = 0.0
        else:
            raise CompareError("metrik %s için bilinmeyen tip %r → INVALID_REQUEST" % (metric, mtype))

        delta = v2 - v1
        z = (delta / se) if se > 0 else 0.0
        significant = abs(z) >= self.z_crit

        # yön-duyarlı iyileşme (G2)
        if self.pol.get("correct_direction", True):
            improvement = delta if direction == "higher_is_better" else -delta
        else:
            improvement = delta          # buggy: yön yok sayılır

        sample_ok = (n1 >= self.min_sample_n) and (n2 >= self.min_sample_n)

        # küçük-örnek bastırma (G6)
        if not sample_ok:
            if self.pol.get("suppress_small", True):
                verdict = self.suppressed_verdict
                winner = "none"
                return self._row(metric, mtype, direction, v1, v2, delta, improvement, z,
                                 significant, sample_ok, verdict, winner)
            else:
                self.suppression_violations += 1   # buggy: küçük-örnek kazanan yayımlanır (aşağıda devam)

        # verdict üretimi (policy'ye göre)
        if self.pol.get("require_significance", True):
            if significant and improvement > TOL:
                verdict = "improved"
            elif significant and improvement < -TOL:
                verdict = "regressed"
            else:
                verdict = "inconclusive"
        else:
            # buggy: ham delta işaretinden kazanan (anlamlılık yok sayılır)
            if improvement > TOL:
                verdict = "improved"
            elif improvement < -TOL:
                verdict = "regressed"
            else:
                verdict = "inconclusive"

        winner = self.winner_of.get(verdict, "none")

        # G3 anlamlılık kapısı: improved/regressed yalnız anlamlı VE yeterli örnek ile
        if verdict in self.significant_verdicts and not (significant and sample_ok):
            self.significance_violations += 1

        # G2 delta/yön tutarlılığı: doğru-yön improvement ile karşılaştır + winner_of tutarlı
        correct_improvement = delta if direction == "higher_is_better" else -delta
        if abs(delta) > TOL and verdict in self.significant_verdicts:
            sign_used = 1 if verdict == "improved" else -1
            if (correct_improvement > 0) != (sign_used > 0):
                self.delta_violations += 1
        if winner != self.winner_of.get(verdict, "none"):
            self.delta_violations += 1

        return self._row(metric, mtype, direction, v1, v2, delta, improvement, z,
                         significant, sample_ok, verdict, winner)

    def _row(self, metric, mtype, direction, v1, v2, delta, improvement, z,
             significant, sample_ok, verdict, winner):
        return {
            "metric": metric, "type": mtype, "direction": direction,
            "baseline_value": round(v1, 6), "candidate_value": round(v2, 6),
            "delta": round(delta, 6), "improvement": round(improvement, 6),
            "z": round(z, 4), "significant": bool(significant), "sample_ok": bool(sample_ok),
            "verdict": verdict, "winner": winner,
            "guardrail": bool(self.catalog.get(metric, {}).get("guardrail", False)),
            "primary": bool(self.catalog.get(metric, {}).get("primary", False)),
        }

    def _recommend(self, metric_rows):
        """SOFT genel öneri (I13): guardrail anlamlı regresyon → keep_baseline; primary anlamlı improved → promote."""
        guardrail_regressed = any(r["guardrail"] and r["verdict"] == "regressed" for r in metric_rows)
        primary_improved = any(r["primary"] and r["verdict"] == "improved" for r in metric_rows)
        if guardrail_regressed:
            return "keep_baseline"
        if primary_improved:
            return "promote_candidate"
        return "inconclusive"

    def run(self, comparison):
        # G9 async/non-blocking (placement): karşılaştırma çağrıyı bloklamaz
        if not self.pol.get("non_blocking", True):
            self.blocking_violations += 1
        if not self.spec.get("placement", {}).get("non_blocking", True):
            self.blocking_violations += 1

        agent_id = comparison.get("agent_id")
        period = comparison.get("period")
        baseline_version = comparison.get("baseline_version")
        arms = comparison.get("arms")
        if not agent_id or not period or not baseline_version:
            raise CompareError("karşılaştırma kimliği eksik (agent_id/period/baseline_version) → INVALID_REQUEST")
        if not isinstance(arms, list) or len(arms) < 2:
            raise CompareError("karşılaştırma ≥2 kol gerektirir → INVALID_REQUEST")

        # kolları indeksle + duplicate version arm (G5) + izolasyon (G7) + apples-to-apples (G1) + PII (G8)
        arm_by_ver = {}
        seen_ver = set()
        excluded_vers = set()       # izolasyon nedeniyle dışlanan sürümler (sessizce düşmez — G7 sayılır)
        for arm in arms:
            if not isinstance(arm, dict):
                raise CompareError("kol kaydı sözlük değil → INVALID_REQUEST")
            ver = arm.get("agent_version_id")
            if ver is None:
                raise CompareError("kolda agent_version_id eksik → INVALID_REQUEST")
            if "metrics" not in arm or not isinstance(arm.get("metrics"), dict):
                raise CompareError("kolda metrics (agregat) eksik → INVALID_REQUEST")

            self._check_arm(arm)

            # G7 izolasyon: cross-tenant + residency
            at = arm.get("tenant_id")
            include = True
            if at is not None and at != self.context.get("tenant_id"):
                self.isolation_violations += 1
                if self.pol.get("isolate_tenant", True):
                    include = False              # cross-tenant kol karışmaz (izole edilir)
                    excluded_vers.add(ver)
            ar = arm.get("region")
            if ar is not None and self.region_pin is not None and ar != self.region_pin:
                self.isolation_violations += 1

            # G1 apples-to-apples: aynı agent + aynı period
            if arm.get("agent_id") is not None and arm.get("agent_id") != agent_id:
                if self.pol.get("same_agent", True):
                    self.comparison_integrity_violations += 1
                else:
                    self.comparison_integrity_violations += 1   # buggy: cross-agent kol yine karşılaştırılır
            if arm.get("period") is not None and arm.get("period") != period:
                if self.pol.get("same_period", True):
                    self.comparison_integrity_violations += 1
                else:
                    self.comparison_integrity_violations += 1   # buggy: cross-period kol yine karşılaştırılır

            # G5 idempotent: aynı sürüm için iki kol
            if ver in seen_ver:
                self.idempotency_violations += 1
                if self.pol.get("idempotent", True):
                    continue                     # daraltılır (ilk kol tutulur)
            seen_ver.add(ver)
            if include:
                arm_by_ver.setdefault(ver, arm)

        if baseline_version not in arm_by_ver:
            raise CompareError("baseline_version (%s) kollarda yok → INVALID_REQUEST" % baseline_version)

        # candidate kümesi
        cands = comparison.get("candidate_versions")
        if cands is None:
            cv = comparison.get("candidate_version")
            cands = [cv] if cv is not None else [v for v in arm_by_ver if v != baseline_version]

        base_arm = arm_by_ver[baseline_version]
        base_metrics = base_arm.get("metrics", {})

        pairs = []
        for cand in sorted(str(c) for c in cands):
            # G1 baseline ≠ candidate
            if cand == baseline_version:
                self.comparison_integrity_violations += 1
                if self.pol.get("distinct_versions", True):
                    continue                     # kendisiyle karşılaştırma atlanır
            if cand not in arm_by_ver:
                if cand in excluded_vers:
                    continue            # cross-tenant/residency ile dışlandı (G7 zaten sayıldı) — sessizce karışmaz
                raise CompareError("candidate_version (%s) kollarda yok → INVALID_REQUEST" % cand)
            cand_arm = arm_by_ver[cand]
            cand_metrics = cand_arm.get("metrics", {})

            metric_rows = []
            # her iki kolda da bulunan metrikleri karşılaştır
            common = [m for m in base_metrics if m in cand_metrics]
            for metric in sorted(common):
                # G4 katalog: metrik kapalı-katalogda mı
                if metric not in self.catalog:
                    self.vocab_violations += 1
                    continue
                metric_rows.append(self._compare_metric(metric, base_metrics[metric], cand_metrics[metric]))
            pairs.append({
                "agent_id": agent_id, "baseline_version": baseline_version,
                "candidate_version": cand, "period": period,
                "metrics": metric_rows,
                "recommendation": self._recommend(metric_rows),
            })

        # özet sayımlar
        all_rows = [r for p in pairs for r in p["metrics"]]
        self.derived["pairs"] = pairs
        self.derived["comparisons"] = len(all_rows)
        self.derived["improved"] = sum(1 for r in all_rows if r["verdict"] == "improved")
        self.derived["regressed"] = sum(1 for r in all_rows if r["verdict"] == "regressed")
        self.derived["inconclusive"] = sum(1 for r in all_rows if r["verdict"] == "inconclusive")
        self.derived["suppressed"] = sum(1 for r in all_rows if r["verdict"] == self.suppressed_verdict)
        self.derived["significant"] = sum(1 for r in all_rows if r["significant"])
        self.derived["pairs_count"] = len(pairs)

    def metrics(self):
        return {
            "comparison_integrity_violations": self.comparison_integrity_violations,
            "significance_violations": self.significance_violations,
            "delta_violations": self.delta_violations,
            "vocab_violations": self.vocab_violations,
            "idempotency_violations": self.idempotency_violations,
            "suppression_violations": self.suppression_violations,
            "isolation_violations": self.isolation_violations,
            "pii_violations": self.pii_violations,
            "blocking_violations": self.blocking_violations,
            "derived": dict(self.derived),
        }


def compare_request(sample, spec, profile, context, policy):
    comparison = sample.get("comparison")
    if not isinstance(comparison, dict):
        raise CompareError("karşılaştırma (comparison) sözlük değil → INVALID_REQUEST")
    eng = VersionCompareEngine(spec, profile, context, policy)
    eng.run(comparison)
    return eng.metrics()


def evaluate(spec, m):
    """Metrikleri HARD kapılara (G1–G9) karşı değerlendirir. Döner findings[(ok, label)]."""
    g = spec.get("gates", {})
    F = []
    F.append((m.get("comparison_integrity_violations", 0) <= g.get("max_comparison_integrity_violation", 0),
              "G1 karşılaştırma bütünlüğü ihlali %d ≤ %d (kollar AYNI agent+tenant+period+metrik; baseline≠candidate — apples-to-apples; FR-ANA-010) — BİRİNCİL"
              % (m.get("comparison_integrity_violations", 0), g.get("max_comparison_integrity_violation", 0))))
    F.append((m.get("significance_violations", 0) <= g.get("max_significance_violation", 0),
              "G3 anlamlılık ihlali %d ≤ %d (improved/regressed yalnız |z|≥z_crit VE her iki kol ≥min_sample_n; gürültüden kazanan YOK) — İKİNCİL"
              % (m.get("significance_violations", 0), g.get("max_significance_violation", 0))))
    F.append((m.get("delta_violations", 0) <= g.get("max_delta_violation", 0),
              "G2 delta/yön ihlali %d ≤ %d (delta=candidate−baseline; improvement direction'a göre; winner tutarlı)"
              % (m.get("delta_violations", 0), g.get("max_delta_violation", 0))))
    F.append((m.get("vocab_violations", 0) <= g.get("max_vocab_violation", 0),
              "G4 katalog ihlali %d ≤ %d (metrik metric_catalog + mv_agent_version_perf/fct_qa_evaluation ile BİREBİR)"
              % (m.get("vocab_violations", 0), g.get("max_vocab_violation", 0))))
    F.append((m.get("idempotency_violations", 0) <= g.get("max_idempotency_violation", 0),
              "G5 idempotency ihlali %d ≤ %d ((tenant,agent,baseline,candidate,period,schema) bir kez; duplicate version arm yok)"
              % (m.get("idempotency_violations", 0), g.get("max_idempotency_violation", 0))))
    F.append((m.get("suppression_violations", 0) <= g.get("max_suppression_violation", 0),
              "G6 bastırma ihlali %d ≤ %d (kol örneği<min_sample_n karşılaştırma yayımlanmaz — k-anon + istatistik güvenilirlik)"
              % (m.get("suppression_violations", 0), g.get("max_suppression_violation", 0))))
    F.append((m.get("isolation_violations", 0) <= g.get("max_isolation_violation", 0),
              "G7 izolasyon ihlali %d ≤ %d (tek tenant_id + cross-tenant yok + residency — FR-TEN-002/NFR 10.7)"
              % (m.get("isolation_violations", 0), g.get("max_isolation_violation", 0))))
    F.append((m.get("pii_violations", 0) <= g.get("max_pii_violation", 0),
              "G8 PII ihlali %d ≤ %d (yalnız redaksiyonlu agregat metrik + düşük-kardinalite boyut; per-call kimlik/PII yok — FR-REC-004)"
              % (m.get("pii_violations", 0), g.get("max_pii_violation", 0))))
    F.append((m.get("blocking_violations", 0) <= g.get("max_blocking_violation", 0),
              "G9 blocking ihlali %d ≤ %d (analytics plane non-blocking; karşılaştırma canlı çağrıyı etkilemez — FR-RES-011)"
              % (m.get("blocking_violations", 0), g.get("max_blocking_violation", 0))))
    return F


# ─────────────────────────────────────────────────────────────────────────────
# bağlam + politika çözümleme
# ─────────────────────────────────────────────────────────────────────────────
def _profile_by_name(cfg, name):
    for p in cfg.get("profiles", []):
        if p.get("name") == name:
            return p
    raise CompareError("bilinmeyen profil: %s" % name)


def _resolve_context(spec, profile, sample):
    ctx = dict(sample.get("context", {}))
    ctx.setdefault("region", profile.get("region"))
    return ctx


def _full_pol():
    return {"same_agent": True, "same_period": True, "distinct_versions": True, "require_significance": True,
            "correct_direction": True, "idempotent": True, "suppress_small": True, "isolate_tenant": True,
            "enforce_redaction": True, "non_blocking": True}


def _resolve_policy(spec, sample):
    pol = _full_pol()
    pol.update(sample.get("policy", {}))
    return pol


def compare_cmd(sample_path):
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
        except CompareError as ex:
            print("compare[%s]: %s" % (name, ex))
            return 0 if expect == "fail" else 1
    context = _resolve_context(spec, profile, sample)
    policy = _resolve_policy(spec, sample)

    try:
        m = compare_request(sample, spec, profile, context, policy)
    except CompareError as ex:
        print("compare[%s]: REDDEDİLDİ — %s" % (name, ex))
        return 0 if expect == "fail" else 1

    F = evaluate(spec, m)
    d = m.get("derived", {})
    print("compare[%s] %d pair, %d metrik karşılaştırma (anlamlı=%d, bastırılan=%d) | bütünlük=%d anlamlılık=%d delta=%d katalog=%d idempotency=%d bastırma=%d izolasyon=%d pii=%d blocking=%d" % (
        name, d.get("pairs_count", 0), d.get("comparisons", 0), d.get("significant", 0), d.get("suppressed", 0),
        m["comparison_integrity_violations"], m["significance_violations"], m["delta_violations"], m["vocab_violations"],
        m["idempotency_violations"], m["suppression_violations"], m["isolation_violations"],
        m["pii_violations"], m["blocking_violations"]))
    print("  özet: improved=%d regressed=%d inconclusive=%d" % (
        d.get("improved", 0), d.get("regressed", 0), d.get("inconclusive", 0)))
    for p in d.get("pairs", []):
        print("    %s: %s → %s [öneri: %s]" % (
            p.get("agent_id"), p.get("baseline_version"), p.get("candidate_version"), p.get("recommendation")))
        for r in p.get("metrics", []):
            print("      %-16s base=%.4f cand=%.4f Δ=%+.4f z=%+.2f sig=%s → %s (winner=%s)" % (
                r["metric"], r["baseline_value"], r["candidate_value"], r["delta"], r["z"],
                "Y" if r["significant"] else "N", r["verdict"], r["winner"]))
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


def _load_sibling_spec(*parts):
    cand = os.path.normpath(os.path.join(HERE, "..", "..", *parts))
    if os.path.exists(cand):
        try:
            return _load(cand)
        except Exception:
            return None
    return None


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

    _check(R, spec.get("wbs") == "14.2.7", "spec.wbs == 14.2.7")
    _check(R, spec.get("version"), "spec.version mevcut")
    _check(R, spec.get("phase") == "F2", "spec.phase == F2")
    _check(R, spec.get("priority") == "Must", "spec.priority == Must (FR-ANA-010)")
    ed = spec.get("eval_doc", {})
    for k in ("fr", "srs", "rtm", "brd", "sad", "db", "olap", "adr", "api", "upstream"):
        _check(R, bool(ed.get(k)), "eval_doc.%s mevcut" % k)
    _check(R, "FR-ANA-010" in ed.get("fr", ""), "eval_doc.fr FR-ANA-010 (sürüm karşılaştırması)")
    _check(R, "SR-ANA-010" in ed.get("srs", ""), "eval_doc.srs SR-ANA-010")

    # ── placement (G9)
    pl = spec.get("placement", {})
    _check(R, pl.get("in_analytics_plane") is True, "G9 motor analytics plane'de (SAD §4.2)")
    _check(R, pl.get("async_batch") is True, "G9 async batch (FR-RES-011)")
    _check(R, pl.get("non_blocking") is True, "G9 non-blocking (karşılaştırma canlı çağrıyı etkilemez)")
    _check(R, pl.get("from_redacted_content") is True, "G8 from_redacted_content (redaksiyonlu agregat)")
    _check(R, pl.get("aggregates_only") is True, "I9 aggregates_only (metriği yeniden hesaplamaz — 14.2.1/14.2.3 üretir)")
    _check(R, pl.get("deterministic") is True, "I10 deterministic (vendor-neutral, random yok)")
    _check(R, pl.get("idempotent") is True, "G5 idempotent")
    _check(R, pl.get("from_trace") is False, "from_trace=false (karşılaştırma agregat üzerinedir)")

    # ── metric_catalog (G4)
    mc = spec.get("metric_catalog", {})
    cat = mc.get("metrics", {})
    _check(R, isinstance(cat, dict) and len(cat) >= 3, "G4 metric_catalog ≥3 metrik")
    for mname, mdef in cat.items():
        _check(R, mdef.get("type") in ("proportion", "mean"), "G4 %s type ∈ {proportion,mean}" % mname)
        _check(R, mdef.get("direction") in ("higher_is_better", "lower_is_better"),
               "G4 %s direction ∈ {higher_is_better,lower_is_better}" % mname)
        _check(R, "guardrail" in mdef, "G4 %s guardrail bayrağı tanımlı" % mname)
    _check(R, "containment_rate" in cat and cat["containment_rate"]["direction"] == "higher_is_better",
           "G4 containment_rate higher_is_better")
    _check(R, "critical_rate" in cat and cat["critical_rate"]["direction"] == "lower_is_better"
           and cat["critical_rate"].get("guardrail") is True,
           "G4 critical_rate lower_is_better + guardrail (regresyon koruması)")
    _check(R, "auto_score" in cat and cat["auto_score"]["type"] == "mean",
           "G4 auto_score type=mean (FR-ANA-001)")
    _check(R, mc.get("proportion_stats") == ["num", "den"], "G4 proportion_stats == [num,den]")
    _check(R, mc.get("mean_stats") == ["mean", "var", "n"], "G4 mean_stats == [mean,var,n]")

    # ── significance (G3 / I11)
    sig = spec.get("significance", {})
    zc = sig.get("z_critical", {})
    _check(R, abs(float(zc.get("0.95", 0)) - 1.96) < 1e-6, "I11 z_critical[0.95] == 1.96")
    _check(R, abs(float(zc.get("0.99", 0)) - 2.576) < 1e-6, "I11 z_critical[0.99] == 2.576")
    _check(R, isinstance(sig.get("confidence"), (int, float)) and str(sig.get("confidence")) in zc,
           "I11 confidence z_critical kataloğunda")
    _check(R, sig.get("two_sided") is True, "I11 two_sided z-testi")
    _check(R, sig.get("mean_uses_normal_approx") is True, "I11 ortalama büyük-örnek normal yaklaşım (beyan)")

    # ── small_sample (G6)
    ss = spec.get("small_sample", {})
    _check(R, isinstance(ss.get("min_sample_n"), int) and ss.get("min_sample_n") >= 2,
           "G6 min_sample_n ≥ 2 (k-anon + istatistik)")
    _check(R, ss.get("suppressed_verdict"), "G6 suppressed_verdict tanımlı")

    # ── verdict_vocabulary (G2/G3)
    vv = spec.get("verdict_vocabulary", {})
    _check(R, set(vv.get("verdicts", [])) == {"improved", "regressed", "inconclusive", "insufficient_sample"},
           "G3 verdicts kapalı-sözlük (4 değer)")
    _check(R, set(vv.get("significant_verdicts", [])) == {"improved", "regressed"},
           "G3 significant_verdicts == {improved,regressed}")
    wof = vv.get("winner_of", {})
    _check(R, wof.get("improved") == "candidate" and wof.get("regressed") == "baseline"
           and wof.get("inconclusive") == "none" and wof.get("insufficient_sample") == "none",
           "G2 winner_of tutarlı (improved→candidate, regressed→baseline, aksi→none)")

    # ── comparison_grain
    cg = spec.get("comparison_grain", {})
    _check(R, cg.get("grain") == ["tenant_id", "agent_id", "agent_version_id", "period"],
           "karşılaştırma grain OLAP mv_agent_version_perf ile hizalı")
    _check(R, cg.get("requires_same_agent") is True, "G1 requires_same_agent (apples-to-apples)")
    _check(R, cg.get("requires_same_period") is True, "G1 requires_same_period (apples-to-apples)")

    # ── recommendation (I13 soft)
    rc = spec.get("recommendation", {})
    _check(R, set(rc.get("values", [])) == {"promote_candidate", "keep_baseline", "inconclusive"},
           "I13 recommendation kapalı-sözlük")
    _check(R, rc.get("soft") is True, "I13 recommendation SOFT (HARD kapı değil)")

    # ── output_contract (G8)
    oc = spec.get("output_contract", {})
    _check(R, {"agent_id", "baseline_version", "candidate_version", "period"} == set(oc.get("pair_fields", [])),
           "output pair_fields == comparison_key boyutları")
    _check(R, {"delta", "z", "significant", "verdict", "winner"} <= set(oc.get("metric_fields", [])),
           "G2/G3 metric_fields delta/z/significant/verdict/winner içerir")
    _check(R, {"tenant_id", "report_id", "schema_version"} <= set(oc.get("identity_fields", [])),
           "G7 identity_fields tenant_id/report_id/schema_version içerir")
    _check(R, any("mv_agent_version_perf" in p for p in oc.get("persists_to", [])),
           "output persists_to mv_agent_version_perf (OLAP rollup)")

    # ── idempotency (G5)
    idem = spec.get("idempotency", {})
    _check(R, idem.get("dedup_key") == ["tenant_id", "agent_id", "baseline_version", "candidate_version", "period", "schema_version"],
           "G5 dedup_key (tenant,agent,baseline,candidate,period,schema)")
    _check(R, idem.get("replay_safe") is True, "G5 replay_safe (1.1.8 P3)")

    # ── feature_policy (G8)
    fp = spec.get("feature_policy", {})
    allowed = set(fp.get("allowed_input_keys", []))
    forb = set(fp.get("forbidden_input_keys", []))
    _check(R, {"agent_id", "agent_version_id", "period", "metrics", "num", "den", "mean", "var", "n"} <= allowed,
           "G8 allowed_input_keys çekirdek + sufficient-stat anahtarları içerir")
    _check(R, {"transcript_text", "audio_payload", "phone_number", "card_number", "call_id"} <= forb,
           "G8 forbidden_input_keys ham transkript/ses/PII/per-call kimlik içerir")
    _check(R, not (allowed & forb), "G8 izinli ile yasak girdi kesişmez")

    # ── isolation (G7)
    iso = spec.get("isolation", {})
    _check(R, iso.get("tenant_id_required") is True, "G7 tenant_id_required")
    _check(R, iso.get("residency") == "home-region", "G7 residency home-region (NFR 10.7)")
    _check(R, iso.get("cross_tenant_forbidden") is True, "G7 cross_tenant_forbidden (FR-TEN-002)")

    # ── OLAP mv_agent_version_perf / fct_qa_evaluation BİREBİR (G4, non-circular)
    olap = _load_sibling_spec("analytics", "olap-spec.json")
    if olap is not None:
        mv = _rollup(olap, "mv_agent_version_perf")
        _check(R, mv is not None, "G4 OLAP rollup mv_agent_version_perf mevcut")
        if mv is not None:
            mvm = set(mv.get("metrics", []))
            _check(R, {"containment_rate", "transfer_rate", "critical_rate"} <= mvm,
                   "G4 mv_agent_version_perf containment/transfer/critical_rate metrikleri (FR-ANA-010)")
            _check(R, "FR-ANA-010" in mv.get("dashboard_fr", []), "G4 mv_agent_version_perf dashboard_fr FR-ANA-010")
            _check(R, "agent_version_id" in (mv.get("grain", "")), "G4 mv_agent_version_perf grain agent_version_id taşır")
            # katalog proportion metrikleri mv ile hizalı (auto_score hariç — fct_qa_evaluation kaynaklı)
            prop_metrics = {k for k, v in cat.items() if v.get("type") == "proportion"}
            _check(R, prop_metrics <= mvm,
                   "G4 katalog oran metrikleri mv_agent_version_perf ile BİREBİR (%s)" % ",".join(sorted(prop_metrics)))
        fq = _fact(olap, "fct_qa_evaluation")
        if fq is not None:
            cols = {c.get("name") for c in fq.get("columns", [])}
            _check(R, "auto_score" in cols and "agent_version_id" in cols,
                   "G4 fct_qa_evaluation auto_score + agent_version_id taşır (A13, FR-ANA-001/010)")

    # ── gates
    g = spec.get("gates", {})
    for gk in ("max_comparison_integrity_violation", "max_significance_violation", "max_delta_violation",
               "max_vocab_violation", "max_idempotency_violation", "max_suppression_violation",
               "max_isolation_violation", "max_pii_violation", "max_blocking_violation"):
        _check(R, g.get(gk, -1) == 0, "gate %s = 0" % gk)

    # ── error taxonomy (I12)
    et = spec.get("error_taxonomy", {}).get("mapping", {})
    _check(R, len(et) >= 3, "I12 hata eşlemesi (≥3)")
    _check(R, all(v in ERROR_TAXONOMY for v in et.values()), "I12 tüm hedefler API §11.6 ErrorTaxonomy'de")
    _check(R, et.get("malformed_comparison") == "INVALID_REQUEST" and et.get("unknown_metric") == "INVALID_REQUEST"
           and et.get("incomparable_arms") == "INVALID_REQUEST" and et.get("region_mismatch") == "REGION_VIOLATION",
           "I12 malformed/unknown_metric/incomparable→INVALID_REQUEST, region→REGION_VIOLATION")

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
            _check(R, isinstance(p.get("min_sample_n"), int) and p.get("min_sample_n") >= 2,
                   "config %s min_sample_n ≥ 2 (k-anon)" % p.get("name"))
            _check(R, str(p.get("confidence")) in spec.get("significance", {}).get("z_critical", {}),
                   "config %s confidence z_critical kataloğunda" % p.get("name"))

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
PROFILE = {"name": "eu-standard", "region": "eu-west-1", "schema_version": 1, "confidence": 0.95, "min_sample_n": 30}


def _arm(ver, cont=None, trans=None, crit=None, score=None, n=1000, agent="ag_support",
         period="2026-06", **extra):
    """Sürüm-başı agregat kol üretir. cont/trans/crit = oran (num=oran*n, den=n); score=(mean,var)."""
    metrics = {}
    if cont is not None:
        metrics["containment_rate"] = {"num": round(cont * n), "den": n}
    if trans is not None:
        metrics["transfer_rate"] = {"num": round(trans * n), "den": n}
    if crit is not None:
        metrics["critical_rate"] = {"num": round(crit * n), "den": n}
    if score is not None:
        mean, var = score
        metrics["auto_score"] = {"mean": mean, "var": var, "n": n}
    arm = {"agent_version_id": ver, "agent_id": agent, "period": period, "metrics": metrics}
    arm.update(extra)
    return arm


def _cmp(baseline, candidate, **kw):
    arms = kw.pop("arms", [baseline, candidate])
    c = {"agent_id": kw.pop("agent_id", "ag_support"), "period": kw.pop("period", "2026-06"),
         "baseline_version": kw.pop("baseline_version", baseline["agent_version_id"]),
         "candidate_version": candidate["agent_version_id"], "arms": arms}
    c.update(kw)
    return c


def _run(comparison, spec, context=None, profile=None, **pol_over):
    pol = _full_pol()
    pol.update(pol_over)
    return compare_request({"comparison": comparison}, spec, dict(profile or PROFILE), context or CONTEXT, pol)


def _raises(fn):
    try:
        fn()
        return False
    except CompareError:
        return True


def _row(m, cand, metric):
    for p in m["derived"]["pairs"]:
        if p["candidate_version"] == cand:
            for r in p["metrics"]:
                if r["metric"] == metric:
                    return r
    return None


def selftest():
    spec = _load(SPEC_PATH)
    cases = []

    def case(ok, label):
        cases.append((bool(ok), label))

    case(_validate_obj(_load(SPEC_PATH)) == 0, "validate iyi spec+config'te 0 döndürür")

    # ── happy: v2 containment belirgin↑ (0.60→0.75, n=1000) anlamlı improved ──
    base = _arm("v1", cont=0.60, trans=0.30, crit=0.03, score=(0.78, 0.04), n=1000)
    cand = _arm("v2", cont=0.75, trans=0.18, crit=0.02, score=(0.85, 0.04), n=1000)
    mh = _run(_cmp(base, cand), spec)
    case(all(mh[k] == 0 for k in (
        "comparison_integrity_violations", "significance_violations", "delta_violations", "vocab_violations",
        "idempotency_violations", "suppression_violations", "isolation_violations",
        "pii_violations", "blocking_violations")), "happy: tüm ihlal sayaçları 0")
    case(all(ok for ok, _ in evaluate(spec, mh)), "happy tüm kapıları geçer")
    r = _row(mh, "v2", "containment_rate")
    case(r["verdict"] == "improved" and r["winner"] == "candidate" and r["significant"],
         "happy: containment 0.60→0.75 anlamlı → improved (winner=candidate)")
    case(abs(r["delta"] - 0.15) < 1e-6, "happy: delta = +0.15 (candidate−baseline)")
    rt = _row(mh, "v2", "transfer_rate")
    case(rt["verdict"] == "improved", "happy: transfer 0.30→0.18 (lower_is_better) anlamlı → improved")
    case(mh["derived"]["pairs"][0]["recommendation"] == "promote_candidate",
         "happy: primary improved + guardrail regresyon yok → promote_candidate (SOFT)")

    # ── determinizm ──
    case(_run(_cmp(base, cand), spec) == _run(_cmp(base, cand), spec),
         "determinizm: aynı stats aynı verdict (random yok)")

    # ── İKİNCİL G3: küçük delta (0.60→0.61, n=1000) anlamlı DEĞİL → inconclusive (gürültü) ──
    noise = _run(_cmp(_arm("v1", cont=0.60, n=1000), _arm("v2", cont=0.61, n=1000)), spec)
    rn = _row(noise, "v2", "containment_rate")
    case(rn["verdict"] == "inconclusive" and not rn["significant"],
         "G3 küçük delta (0.60→0.61) anlamlı DEĞİL → inconclusive (gürültüden kazanan YOK)")
    case(all(ok for ok, _ in evaluate(spec, noise)), "G3 inconclusive YİNE kapıları geçer (doğru davranış)")

    # ── G3 buggy: require_significance KAPALI → ham delta işaretinden kazanan ilan ──
    bug = _run(_cmp(_arm("v1", cont=0.60, n=1000), _arm("v2", cont=0.61, n=1000)), spec, require_significance=False)
    case(bug["significance_violations"] >= 1,
         "require_significance KAPALI: anlamsız delta 'improved' ilan → G3 eler")

    # ── G1 BİRİNCİL: cross-agent kol ──
    xa = _run(_cmp(_arm("v1", cont=0.6, agent="ag_support"), _arm("v2", cont=0.7, agent="ag_sales")), spec)
    case(xa["comparison_integrity_violations"] >= 1, "G1 cross-agent kol → bütünlük eler (apples-to-apples)")

    # ── G1: cross-period kol ──
    xp = _run(_cmp(_arm("v1", cont=0.6, period="2026-06"), _arm("v2", cont=0.7, period="2026-05")), spec)
    case(xp["comparison_integrity_violations"] >= 1, "G1 cross-period kol → bütünlük eler")

    # ── G1: baseline == candidate (self-compare) ──
    selfc = {"agent_id": "ag_support", "period": "2026-06", "baseline_version": "v1",
             "candidate_versions": ["v1"], "arms": [_arm("v1", cont=0.6), _arm("v2", cont=0.7)]}
    ms = _run(selfc, spec)
    case(ms["comparison_integrity_violations"] >= 1, "G1 baseline==candidate (self-compare) → bütünlük eler")

    # ── G2: correct_direction KAPALI → lower_is_better metrikte yön ters ──
    # critical_rate 0.02→0.05 (kötüleşme); yön yok sayılırsa improvement=+delta>0 → 'improved' yanlış
    md = _run(_cmp(_arm("v1", crit=0.02, n=2000), _arm("v2", crit=0.05, n=2000)), spec, correct_direction=False)
    case(md["delta_violations"] >= 1, "correct_direction KAPALI: lower_is_better yön ters → G2 eler")
    # doğru yön: critical 0.02→0.05 anlamlı kötüleşme → regressed (winner=baseline)
    mok = _run(_cmp(_arm("v1", crit=0.02, n=2000), _arm("v2", crit=0.05, n=2000)), spec)
    rc = _row(mok, "v2", "critical_rate")
    case(rc["verdict"] == "regressed" and rc["winner"] == "baseline",
         "doğru yön: critical 0.02→0.05 anlamlı↑ (lower_is_better) → regressed (winner=baseline)")
    case(mok["derived"]["pairs"][0]["recommendation"] == "keep_baseline",
         "guardrail (critical_rate) anlamlı regresyon → keep_baseline (SOFT)")

    # ── G4: bilinmeyen metrik ──
    badm = _arm("v2", cont=0.7)
    badm["metrics"]["made_up_metric"] = {"num": 5, "den": 10}
    base2 = _arm("v1", cont=0.6)
    base2["metrics"]["made_up_metric"] = {"num": 3, "den": 10}
    m4 = _run(_cmp(base2, badm), spec)
    case(m4["vocab_violations"] >= 1, "G4 bilinmeyen metrik → katalog eler (mv_agent_version_perf BİREBİR)")

    # ── G5: duplicate version arm ──
    dup = {"agent_id": "ag_support", "period": "2026-06", "baseline_version": "v1", "candidate_version": "v2",
           "arms": [_arm("v1", cont=0.6), _arm("v2", cont=0.7), _arm("v2", cont=0.65)]}
    m5 = _run(dup, spec, idempotent=False)
    case(m5["idempotency_violations"] >= 1, "idempotent KAPALI: duplicate version arm → G5 eler")
    m5o = _run(dup, spec)
    case(m5o["idempotency_violations"] >= 1, "duplicate version arm → idempotency tespit edilir (AÇIK'ta daraltılır)")

    # ── G6: küçük örnek bastırma ──
    small = _run(_cmp(_arm("v1", cont=0.6, n=10), _arm("v2", cont=0.9, n=12)), spec)
    rs = _row(small, "v2", "containment_rate")
    case(rs["verdict"] == "insufficient_sample" and rs["winner"] == "none",
         "G6 kol örneği(10/12)<min_sample_n(30) → insufficient_sample (bastırılır, sessizce düşmez)")
    case(small["derived"]["suppressed"] >= 1 and all(ok for ok, _ in evaluate(spec, small)),
         "G6 bastırma doğru davranış → kapı geçer (suppressed sayılır)")
    m6b = _run(_cmp(_arm("v1", cont=0.6, n=10), _arm("v2", cont=0.9, n=12)), spec, suppress_small=False)
    case(m6b["suppression_violations"] >= 1, "suppress_small KAPALI: küçük-örnek kazanan yayımlanır → G6 eler (k-anon)")

    # ── G7: cross-tenant + residency ──
    ct = {"agent_id": "ag_support", "period": "2026-06", "baseline_version": "v1", "candidate_version": "v2",
          "arms": [_arm("v1", cont=0.6), _arm("v2", cont=0.7, tenant_id="t_other")]}
    m7 = _run(ct, spec)
    case(m7["isolation_violations"] >= 1, "cross-tenant kol (t_other) → G7 izolasyon eler")
    rd = {"agent_id": "ag_support", "period": "2026-06", "baseline_version": "v1", "candidate_version": "v2",
          "arms": [_arm("v1", cont=0.6), _arm("v2", cont=0.7, region="us-east-1")]}
    case(_run(rd, spec)["isolation_violations"] >= 1, "home-region dışı kol (residency) → G7 eler (NFR 10.7)")

    # ── G8: ham transkript/PII DEĞERİ ──
    leak = _arm("v2", cont=0.7)
    leak["transcript_text"] = "müşteri konuştu"
    m8e = _run(_cmp(_arm("v1", cont=0.6), leak), spec)
    case(m8e["pii_violations"] >= 1, "enforce_redaction AÇIK: transcript_text yasak girdi → G8 eler")
    m8 = _run(_cmp(_arm("v1", cont=0.6), leak), spec, enforce_redaction=False)
    case(m8["pii_violations"] == 0, "enforce_redaction KAPALI: redaction zorlanmaz (denetlenmez)")
    leakv = _arm("v2", cont=0.7, agent="0555 123 4567")
    case(_run(_cmp(_arm("v1", cont=0.6), leakv, agent_id="0555 123 4567"), spec)["pii_violations"] >= 1
         or _run({"agent_id": "0555 123 4567", "period": "2026-06", "baseline_version": "v1",
                  "candidate_version": "v2", "arms": [_arm("v1", cont=0.6, agent="0555 123 4567"),
                  leakv]}, spec)["pii_violations"] >= 1,
         "boyut DEĞERİnde ham telefon → G8 eler")

    # ── G9: non_blocking KAPALI ──
    m9 = _run(_cmp(_arm("v1", cont=0.6), _arm("v2", cont=0.7)), spec, non_blocking=False)
    case(m9["blocking_violations"] >= 1, "non_blocking KAPALI: karşılaştırma çağrıyı bloklar → G9 eler (FR-RES-011)")

    # ── reddetme (I12) ──
    case(_raises(lambda: compare_request({"comparison": "x"}, spec, PROFILE, CONTEXT, _full_pol())),
         "I12 comparison sözlük değil → reddedilir")
    case(_raises(lambda: compare_request({"comparison": {"agent_id": "a", "period": "p", "baseline_version": "v1",
         "arms": [_arm("v1", cont=0.6)]}}, spec, PROFILE, CONTEXT, _full_pol())),
         "I12 <2 kol → reddedilir")
    case(_raises(lambda: VersionCompareEngine(spec, PROFILE, {"region": "eu"}, _full_pol())),
         "I12 bağlam (tenant_id) eksik → reddedilir")
    case(_raises(lambda: VersionCompareEngine(spec, dict(PROFILE, confidence=0.42), CONTEXT, _full_pol())),
         "I12 bilinmeyen confidence (z_critical yok) → reddedilir")

    # ── mean (auto_score) anlamlılık: küçük std → anlamlı ──
    msc = _run(_cmp(_arm("v1", score=(0.78, 0.01), n=1000), _arm("v2", score=(0.85, 0.01), n=1000)), spec)
    rsc = _row(msc, "v2", "auto_score")
    case(rsc["type"] == "mean" and rsc["verdict"] == "improved" and rsc["significant"],
         "mean auto_score 0.78→0.85 (küçük var) anlamlı → improved (normal yaklaşım z)")

    # ── validate negatif kapılar ──
    s = json.loads(json.dumps(spec)); s["metric_catalog"]["metrics"]["critical_rate"]["guardrail"] = False
    case(_validate_obj(s) != 0, "G4 critical_rate guardrail kaldırılır → validate eler")
    s = json.loads(json.dumps(spec)); s["metric_catalog"]["metrics"]["containment_rate"]["direction"] = "lower_is_better"
    case(_validate_obj(s) != 0, "G4 containment_rate higher_is_better'dan sapar → validate eler")
    s = json.loads(json.dumps(spec)); s["significance"]["z_critical"]["0.95"] = 1.0
    case(_validate_obj(s) != 0, "I11 z_critical[0.95]≠1.96 → validate eler")
    s = json.loads(json.dumps(spec)); s["verdict_vocabulary"]["winner_of"]["improved"] = "baseline"
    case(_validate_obj(s) != 0, "G2 winner_of[improved]=baseline (tutarsız) → validate eler")
    s = json.loads(json.dumps(spec)); s["small_sample"]["min_sample_n"] = 1
    case(_validate_obj(s) != 0, "G6 min_sample_n < 2 (k-anon yetersiz) → validate eler")
    s = json.loads(json.dumps(spec)); s["recommendation"]["soft"] = False
    case(_validate_obj(s) != 0, "I13 recommendation.soft=False → validate eler (öneri HARD olamaz)")
    s = json.loads(json.dumps(spec)); s["feature_policy"]["allowed_input_keys"].append("transcript_text")
    case(_validate_obj(s) != 0, "G8 izinli girdiye transcript_text → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_significance_violation"] = 1
    case(_validate_obj(s) != 0, "G3 max_significance_violation>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["error_taxonomy"]["mapping"]["x"] = "NOPE"
    case(_validate_obj(s) != 0, "I12 taksonomi-dışı → validate eler")
    s = json.loads(json.dumps(spec)); s["significance"]["leak"] = "0555 123 4567"
    case(_validate_obj(s) != 0, "I15 spec'te ham PII DEĞERİ (telefon) → validate eler")
    s = json.loads(json.dumps(spec)); s["significance"]["secret"] = "api_key: AKIAIOSFODNN7EXAMPLE"
    case(_validate_obj(s) != 0, "I15 literal secret → validate eler")

    passed = sum(1 for ok, _ in cases if ok)
    total = len(cases)
    for ok, label in cases:
        print("  %s %s" % ("✓" if ok else "✗", label))
    print("selftest: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


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
    print("""version-compare-spec.json beklenen şekli (WBS 14.2.7):
  wbs=14.2.7, version, phase=F2, priority=Must, eval_doc{fr,srs,rtm,brd,sad,db,olap,adr,api,upstream}
  placement{in_analytics_plane, async_batch, non_blocking, from_redacted_content, aggregates_only=true,
            deterministic, idempotent, from_trace=false}                                          (G9,G8)
  metric_catalog{metrics{<name>{type(proportion|mean), direction(higher|lower_is_better), guardrail,
                 primary, source, fr}}, proportion_stats[num,den], mean_stats[mean,var,n]}        (G4)
  significance{confidence, z_critical{0.90,0.95,0.99}, two_sided, large_sample_n,
               mean_uses_normal_approx}                                                            (G3,I11)
  small_sample{min_sample_n, suppressed_verdict}                                                   (G6)
  verdict_vocabulary{verdicts[4], significant_verdicts[improved,regressed], winner_of{}}           (G2,G3)
  comparison_grain{grain[tenant,agent,agent_version,period], comparison_key, requires_same_agent,
                   requires_same_period}                                                           (G1)
  recommendation{values[promote_candidate,keep_baseline,inconclusive], soft=true}                  (I13 SOFT)
  output_contract{pair_fields[4], metric_fields[delta,z,significant,verdict,winner,...],
                  identity_fields[tenant_id,report_id,schema_version], persists_to[mv_agent_version_perf]} (G2,G7,G8)
  idempotency{dedup_key=[tenant,agent,baseline,candidate,period,schema], replay_safe=true}         (G5)
  feature_policy{allowed_input_keys[], forbidden_input_keys[]}                                     (G8)
  isolation{tenant_id_required, residency=home-region, cross_tenant_forbidden}                     (G7)
  gates{max_comparison_integrity_violation=0, max_significance_violation=0, max_delta_violation=0,
        max_vocab_violation=0, max_idempotency_violation=0, max_suppression_violation=0,
        max_isolation_violation=0, max_pii_violation=0, max_blocking_violation=0}                  (G1..G9)
  error_taxonomy{mapping→API §11.6}  pii{...}  invariants[≥15]{id,desc,trace}

config/version-compare-profiles.json: profiles[]{name, region, schema_version, confidence, min_sample_n}

compare sample: {name, profile | profile_obj, expect, expected?{sayaç}, expected_derived?{özet},
  context{tenant_id, region?},
  policy?{same_agent, same_period, distinct_versions, require_significance, correct_direction, idempotent,
          suppress_small, isolate_tenant, enforce_redaction, non_blocking},
  comparison{agent_id, period, baseline_version, candidate_version|candidate_versions[],
             arms[]{agent_version_id, agent_id?, period?, tenant_id?, region?,
                    metrics{<metric>{num,den} | <metric>{mean,var,n}}}}}
  (PII DEĞERİ / ham transkript / per-call kimlik YOK — yalnız redaksiyonlu agregat sufficient stats + boyut ADLARI)

komutlar: validate | compare <sample.json> | selftest | schema""")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if cmd == "validate":
        return validate()
    if cmd == "compare":
        if len(sys.argv) < 3:
            print("kullanım: version_compare_probe.py compare <sample.json>")
            return 2
        return compare_cmd(sys.argv[2])
    if cmd == "selftest":
        return selftest()
    if cmd == "schema":
        return schema()
    print("bilinmeyen komut: %s (validate|compare|selftest|schema)" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main())
