#!/usr/bin/env python3
"""vector_db_eval_probe.py — Vector DB sağlayıcı değerlendirme hattı (WBS 0.2.5, →SAD §12.1).

Amaç: RAG retrieval vektör deposu adaylarını (**pgvector vs OpenSearch** ve diğer adaylar)
**sağlayıcı-nötr (ADR-002)**, ölçüt-tabanlı ve tekrarlanabilir biçimde değerlendirmek. Vektör
deposu STT/TTS/LLM gibi medya hot-path'inde değil; **RAG retrieval** adımındadır (SAD §10.2:
`embed → vector search top-k → rerank → trim → LLM context`). Yine de retrieval gecikmesi turn
bütçesinin bir kalemidir (SAD §20: "RAG retrieval (gerekirse) ~100–200 ms P95; top-k; çoğu turda
atlanır"). Değerlendirmenin birincil boyutları:

- **Retrieval gecikmesi (top-k ANN search, P95):** SAD §20 RAG kalemi → kapı P95 ≤ 200 ms
  (yeşil ≤ 100 ms). Çoğu turda atlanır ama gerektiğinde turn bütçesini (NFR 10.1: P95 ≤ 1.200 ms)
  doğrudan yer.
- **Recall@k (retrieval kalitesi):** ANN yaklaşıklığı ilgili dokümanı düşürmemeli. `retrieved_ids`
  (ANN top-k) ∩ `relevant_ids` (exact-kNN ground-truth) / |relevant|. Kapı **en-kötü sorgu sınıfı**
  üzerinden (factual/semantic/structured — zayıf sınıfı genel ortalama maskelemesin; STT WER / TTS
  MOS / LLM kalite ile aynı disiplin). Düşük recall → anti-hallucination zinciri (FR-KB-007) bozulur.
- **Namespace / tenant izolasyonu (FR-KB-004, FR-TEN-002):** Tenant+agent bazında ayrı namespace;
  bir sorgunun sonucunda **başka tenant'ın / yetkisiz** dokümanı (`forbidden_ids`) ASLA dönmemeli.
  Empirik sızıntı sayısı = 0 zorunlu (knock-out). pgvector için native PostgreSQL RLS (DB.md).
- **Metadata filtreli arama / doküman-ACL (FR-KB-005, FR-KB-006):** Vektör arama + metadata filtre
  (erişim yetkisi, versiyon, kaynak) birlikte; filtreli sorgularda yetkisiz doküman sızıntısı = 0.
- **Residency / no-log (NFR 10.7, FR-KB-010):** Veri tenant home-region'da; hassas dokümanlar dış
  sağlayıcı loglarına gitmez. `residency_pinned` + bölge sunulanlar arasında + `no_external_log`.

Ek (soft/bilgilendirici) ölçütler:
- **Index ops (FR-KB-003/008):** artımlı upsert + silme (versiyonlama + içerik TTL/bayatlama).
- **Hybrid search:** vektör + anahtar-kelime (BM25); yapısal alanlar (telefon/poliçe/referans no)
  için retrieval kalitesini artırır (OpenSearch native; pgvector eklenti/birlikte kullanım).
- **Operasyonel tutarlılık (stack-fit):** pgvector PostgreSQL'i yeniden kullanır (RLS, audit, backup,
  residency, KMS, transactional metadata tutarlılığı) → daha az hareketli parça; OpenSearch ayrı küme.

Tasarım ilkeleri (CLAUDE.md):
- **Vendor-neutral:** Araç hiçbir depoyu **seçmez**; ölçüt-tabanlı sonuç üretir. pgvector ve OpenSearch
  iki meşru adaydır (SAD §8.4); nihai seçim **0.2.6** karar raporunda + uygulama **1.1.7** ile.
- **stdlib-only:** Harici bağımlılık yok (gen_rtm.py / media_latency_probe.py / stt|tts|llm_eval_probe.py
  disiplini).
- **Credential-free self-test:** `selftest` ve `samples/*.json` ile gerçek bağlantı olmadan uçtan uca
  koşar (CI'da). Gerçek ölçüm yalnız dışarıdan örnek JSON ile verilir; sır repoya YAZILMAZ.

Modlar:
  score    — Bir aday örnek JSON'unu (sorgu test seti + config) puanlar → özet + gecikme/recall/izolasyon kapısı.
  compare  — Çok adaylı `score` çıktılarından karşılaştırma matrisi (markdown).
  selftest — Dahili deterministik örnekle gecikme/recall/izolasyon/filtre/residency çekirdeğini doğrular.

Örnek (sample) JSON şeması — `samples/*.json`:
{
  "provider": "vdb-pgvector",
  "config": {
    "engine": "pgvector",
    "index_type": "hnsw",                 # hnsw|ivfflat|... (ANN index)
    "supports_namespace": true,           # tenant+agent namespace (FR-KB-004)
    "rls": true,                          # row-level security (FR-TEN-002, DB.md)
    "metadata_filter": true,              # doküman-ACL/versiyon/kaynak filtresi (FR-KB-005/006)
    "hybrid_search": false,               # vektör + BM25 (soft)
    "incremental_upsert": true,           # artımlı ekleme/güncelleme (FR-KB-003)
    "delete_support": true,               # silme/işaretleme (FR-KB-008, retention)
    "residency_pinned": true,             # veri home-region'da (NFR 10.7)
    "region": "EU", "available_regions": ["EU", "UK", "TR"],
    "no_external_log": true,              # hassas doküman dış sağlayıcı loglarında değil (FR-KB-010)
    "operational_stackfit": "high"        # high|medium|low (bilgilendirici)
  },
  "queries": [
    {
      "id": "q-tr-semantic-001", "query_class": "semantic",   # factual|semantic|structured
      "tenant": "tenantA", "namespace": "tenantA/agent1", "k": 10,
      "latency_ms": 32,                                        # top-k retrieval gecikmesi
      "retrieved_ids": ["d12","d7","d3", ...],                 # ANN top-k DÖNEN sonuç
      "relevant_ids": ["d12","d7","d3", ...],                  # exact-kNN ground-truth (recall paydası)
      "forbidden_ids": ["tenantB-d9"],                         # ASLA dönmemeli (cross-tenant/yetkisiz)
      "filter_applied": true                                   # metadata/ACL filtresi istendi mi
    }, ...
  ]
}
`forbidden_ids` / `relevant_ids` / `filter_applied` opsiyonel; yoksa ilgili metrik atlanır.
"""

from __future__ import annotations

import argparse
import json

# --- Eşikler (mühendislik varsayılanı; 0.3.x PoC'ta doğrulanır) -------------
# SAD §20 gecikme bütçesi — "RAG retrieval (gerekirse) ~100–200 ms (P95). Top-k; çoğu turda atlanır."
RETRIEVAL_P95_BUDGET_MS = 200.0     # kapı (gate) — SAD §20 üst sınır
RETRIEVAL_P95_GREEN_MS = 100.0      # yeşil bant — SAD §20 alt sınır
# Recall@k (0–1; en-kötü sorgu sınıfı). ANN yaklaşıklığı ilgili dokümanı düşürmemeli.
RECALL_MIN = 0.95                   # kapı (yüksek-iyi)
RECALL_GREEN = 0.98                 # yeşil bant
# Sorgu sınıfları (kapı en-kötü-sınıf üzerinden; zayıf sınıfı genel ortalama maskelemesin).
QUERY_CLASSES = ("factual", "semantic", "structured")
# Residency için beklenen bölge kapsamı (NFR 10.7); en az biri + region pinning gerekli.
REQUIRED_REGIONS = ("EU", "UK", "TR")


# ----------------------------------------------------------------------------
# Saf yardımcılar (test edilebilir)
# ----------------------------------------------------------------------------
def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return float("nan")
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    rank = pct / 100.0 * (len(sorted_vals) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = rank - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def _lat_summary(vals: list[float]) -> dict:
    s = sorted(vals)
    return {
        "p50": round(_percentile(s, 50), 2) if s else None,
        "p95": round(_percentile(s, 95), 2) if s else None,
        "p99": round(_percentile(s, 99), 2) if s else None,
        "max": round(s[-1], 2) if s else None,
        "samples": len(s),
    }


def _verdict(measured: float | None, *, green: float, budget: float, lower_is_better: bool) -> str:
    if measured is None:
        return "VERİ-YOK"
    if lower_is_better:
        if measured <= green:
            return "YEŞİL"
        if measured <= budget:
            return "SARI"
        return "KIRMIZI"
    # higher is better (recall): green = üst hedef, budget = alt kapı
    if measured >= green:
        return "YEŞİL"
    if measured >= budget:
        return "SARI"
    return "KIRMIZI"


# ----------------------------------------------------------------------------
# Recall@k (FR-KB-009 / SAD §10.2) — ANN yaklaşıklık kalitesi
# ----------------------------------------------------------------------------
def recall_at_k(retrieved_ids: list, relevant_ids: list) -> float | None:
    """recall@k = |retrieved ∩ relevant| / |relevant|.

    `relevant_ids` = exact-kNN ground-truth (referans). `retrieved_ids` = ANN top-k DÖNEN sonuç.
    ANN'in ilgili dokümanları kaçırma oranını ölçer; düşük recall → anti-hallucination (FR-KB-007)
    zinciri bozulur (agent kaynak bulamaz). Payda boşsa None (ölçülemez).
    """
    rel = set(relevant_ids or [])
    if not rel:
        return None
    ret = set(retrieved_ids or [])
    return len(ret & rel) / len(rel)


def leak_count(retrieved_ids: list, forbidden_ids: list) -> int:
    """Sonuçta dönen YASAK doküman sayısı (cross-tenant / yetkisiz). Sıfır olmalı (FR-KB-004/005)."""
    forb = set(forbidden_ids or [])
    if not forb:
        return 0
    return sum(1 for r in (retrieved_ids or []) if r in forb)


# ----------------------------------------------------------------------------
# Uygunluk kapıları: residency / no-log + namespace + metadata filtre
# ----------------------------------------------------------------------------
def residency_compliance(config: dict, required: tuple[str, ...] = REQUIRED_REGIONS) -> tuple[bool, str, list[str]]:
    """NFR 10.7 + FR-KB-010: residency pinning + bölge sunulanlar arasında + dış log yok."""
    pinned = bool(config.get("residency_pinned", False))
    region = config.get("region")
    available = config.get("available_regions", []) or []
    no_ext_log = bool(config.get("no_external_log", False))
    covered = [r for r in required if r in available]
    region_ok = pinned and region is not None and region in available
    ok = region_ok and no_ext_log
    if not pinned:
        reason = "residency pinning yok (home-region zorlanamaz, NFR 10.7)"
    elif region is None:
        reason = "deponun bölgesi tanımsız (NFR 10.7)"
    elif region not in available:
        reason = f"pin edilen bölge '{region}' sunulan bölgelerde yok {available} (NFR 10.7)"
    elif not no_ext_log:
        reason = "hassas içerik dış sağlayıcı loglarında tutulabilir (no_external_log=false, FR-KB-010)"
    else:
        reason = f"residency '{region}' pin'li + dış log yok; kapsanan beklenen bölgeler: {covered or '—'}"
    return ok, reason, covered


# ----------------------------------------------------------------------------
# Aday puanlama çekirdeği
# ----------------------------------------------------------------------------
def summarize_provider(sample: dict) -> dict:
    """Bir vektör-deposu adayının sorgu test setini puanla → özet + kapı (gate)."""
    config = sample.get("config", {})
    queries = sample.get("queries", [])

    lat_all: list[float] = []
    lat_by_class: dict[str, list[float]] = {}
    recall_by_class: dict[str, list[float]] = {}
    total_leak = 0          # tüm sorgularda cross-tenant/yetkisiz sızıntı
    filtered_queries = 0
    filtered_leak = 0       # filtre uygulanan sorgularda sızıntı (doküman-ACL ihlali)
    leak_queries = 0

    for q in queries:
        qcls = q.get("query_class", "semantic")

        lat = q.get("latency_ms")
        if lat is not None:
            lat_all.append(float(lat))
            lat_by_class.setdefault(qcls, []).append(float(lat))

        rc = recall_at_k(q.get("retrieved_ids", []), q.get("relevant_ids", []))
        if rc is not None:
            recall_by_class.setdefault(qcls, []).append(rc)

        lk = leak_count(q.get("retrieved_ids", []), q.get("forbidden_ids", []))
        total_leak += lk
        if lk > 0:
            leak_queries += 1
        if q.get("filter_applied"):
            filtered_queries += 1
            filtered_leak += lk

    # --- türetilmiş metrikler
    lat_summary = _lat_summary(lat_all)
    latency_by_class = {k: _lat_summary(v) for k, v in lat_by_class.items()}

    recall_by_query_class = {k: round(sum(v) / len(v), 4) for k, v in recall_by_class.items()}
    all_r = [x for v in recall_by_class.values() for x in v]
    recall_overall = round(sum(all_r) / len(all_r), 4) if all_r else None
    # Kapı en-kötü-sınıf üzerinden (zayıf sorgu sınıfını genel ortalama maskelemesin).
    recall_worst = min(recall_by_query_class.values()) if recall_by_query_class else None

    # --- yetenek + uygunluk kapıları
    supports_ns = bool(config.get("supports_namespace", False))
    rls = bool(config.get("rls", False))
    metadata_filter = bool(config.get("metadata_filter", False))
    rs_ok, rs_reason, rs_covered = residency_compliance(config)

    # --- gecikme/recall kapı kararları
    lat_p95 = lat_summary["p95"]
    g_lat = _verdict(lat_p95, green=RETRIEVAL_P95_GREEN_MS, budget=RETRIEVAL_P95_BUDGET_MS,
                     lower_is_better=True)
    g_recall = _verdict(recall_worst, green=RECALL_GREEN, budget=RECALL_MIN, lower_is_better=False)

    # Namespace izolasyonu: yetenek (namespace veya RLS) + empirik sızıntı = 0 (FR-KB-004/FR-TEN-002).
    iso_capable = supports_ns or rls
    iso_pass = iso_capable and total_leak == 0
    if not iso_capable:
        iso_reason = "tenant+agent namespace / RLS yok → mantıksal izolasyon zorlanamaz (FR-KB-004/FR-TEN-002)"
    elif total_leak > 0:
        iso_reason = (f"{leak_queries} sorguda cross-tenant/yetkisiz doküman döndü (toplam {total_leak}) "
                      "→ tenant izolasyon ihlali (FR-TEN-002)")
    else:
        iso_reason = (f"namespace={'evet' if supports_ns else 'hayır'}, RLS={'evet' if rls else 'hayır'}; "
                      "sonuçlarda cross-tenant/yetkisiz sızıntı yok")

    # Metadata filtre / doküman-ACL: yetenek + filtreli sorgularda yetkisiz sızıntı = 0 (FR-KB-005/006).
    filt_pass = metadata_filter and filtered_leak == 0
    if not metadata_filter:
        filt_reason = "metadata/ACL filtreli arama desteklenmiyor (FR-KB-005 doküman-bazlı yetki zorlanamaz)"
    elif filtered_leak > 0:
        filt_reason = (f"filtreli sorgularda {filtered_leak} yetkisiz doküman döndü "
                       "→ doküman-ACL ihlali (FR-KB-005)")
    else:
        filt_reason = (f"metadata/ACL filtreli arama destekli; {filtered_queries} filtreli sorguda "
                       "yetkisiz sızıntı yok")

    # Knock-out kapıları: retrieval-gecikme + recall + namespace-izolasyon + metadata-filtre + residency.
    hard = {
        "retrieval_latency_p95_ms": {"budget": RETRIEVAL_P95_BUDGET_MS, "green": RETRIEVAL_P95_GREEN_MS,
                                     "measured": lat_p95, "verdict": g_lat,
                                     "pass": g_lat in ("YEŞİL", "SARI", "VERİ-YOK")},
        "recall_worst_class": {"min": RECALL_MIN, "green": RECALL_GREEN, "measured": recall_worst,
                               "basis": "en-kötü sorgu sınıfı (factual/semantic/structured)",
                               "verdict": g_recall, "pass": g_recall in ("YEŞİL", "SARI", "VERİ-YOK")},
        "namespace_isolation": {"required": True, "pass": iso_pass, "reason": iso_reason,
                                "leak_total": total_leak, "leak_queries": leak_queries},
        "metadata_filter_acl": {"required": True, "pass": filt_pass, "reason": filt_reason,
                                "filtered_queries": filtered_queries, "filtered_leak": filtered_leak},
        "residency_no_log": {"required": True, "pass": rs_ok, "reason": rs_reason,
                             "covered_regions": rs_covered},
    }
    overall_pass = all(v["pass"] for v in hard.values())

    # Soft/bilgilendirici (knock-out değil; 0.2.6'da bütünsel)
    soft = {
        "incremental_upsert": bool(config.get("incremental_upsert", False)),
        "delete_support": bool(config.get("delete_support", False)),
        "hybrid_search": bool(config.get("hybrid_search", False)),
        "operational_stackfit": config.get("operational_stackfit", "?"),
    }

    # Bütünsel renk: bir kapı KIRMIZI/fail → KIRMIZI; tümü YEŞİL → YEŞİL; arası SARI.
    numeric_verdicts = [g_lat, g_recall]
    compliance_green = iso_pass and filt_pass and rs_ok
    if not overall_pass:
        verdict = "KIRMIZI"
    elif all(v in ("YEŞİL", "VERİ-YOK") for v in numeric_verdicts) and compliance_green:
        verdict = "YEŞİL"
    else:
        verdict = "SARI"

    return {
        "provider": sample.get("provider", "?"),
        "config": config,
        "counts": {
            "queries": len(queries),
            "by_class": {k: len(v) for k, v in lat_by_class.items()},
            "filtered_queries": filtered_queries,
        },
        "retrieval_latency_ms": lat_summary,
        "retrieval_latency_by_class": latency_by_class,
        "recall": {
            "overall": recall_overall, "worst_class": recall_worst,
            "by_query_class": recall_by_query_class,
        },
        "isolation": {"namespace": supports_ns, "rls": rls, "leak_total": total_leak,
                      "leak_queries": leak_queries},
        "metadata_filter": {"supported": metadata_filter, "filtered_queries": filtered_queries,
                            "filtered_leak": filtered_leak},
        "soft": soft,
        "gates": hard,
        "verdict": verdict,
        "pass": overall_pass,
        "iz": ("FR-KB-003/004/005/006/008/009/010/011; FR-TEN-002; FR-RES-004; SAD §10/§12.1/§20; "
               "NFR 10.7; ADR-002"),
    }


# ----------------------------------------------------------------------------
# score
# ----------------------------------------------------------------------------
def cmd_score(args: argparse.Namespace) -> int:
    with open(args.sample, encoding="utf-8") as fh:
        sample = json.load(fh)
    result = summarize_provider(sample)
    out = json.dumps(result, indent=2, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(out + "\n")
        print(f"yazıldı: {args.out}")
    print(out)
    return 0 if result["pass"] else 1


# ----------------------------------------------------------------------------
# compare
# ----------------------------------------------------------------------------
def cmd_compare(args: argparse.Namespace) -> int:
    rows = []
    for path in args.results:
        with open(path, encoding="utf-8") as fh:
            rows.append(json.load(fh))
    badge = {"YEŞİL": "🟢", "SARI": "🟡", "KIRMIZI": "🔴", "VERİ-YOK": "⚪"}
    lines = [
        "| Aday | Motor | Retrieval P95 (ms) | Recall (en-kötü sınıf) | İzolasyon (sızıntı) | Filtre/ACL | Residency | Hybrid | Karar |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        g = r.get("gates", {})
        iso = g.get("namespace_isolation", {})
        iso_txt = "yok" if iso.get("leak_total", 0) == 0 else f"{iso.get('leak_total')} sızıntı"
        iso_mark = "evet" if iso.get("pass") else "HAYIR"
        filt = "evet" if g.get("metadata_filter_acl", {}).get("pass") else "HAYIR"
        rs = "evet" if g.get("residency_no_log", {}).get("pass") else "HAYIR"
        hy = "evet" if r.get("soft", {}).get("hybrid_search") else "hayır"
        lines.append(
            f"| {r.get('provider', '?')} "
            f"| {r.get('config', {}).get('engine', '?')} "
            f"| {r.get('retrieval_latency_ms', {}).get('p95', '-')} "
            f"| {r.get('recall', {}).get('worst_class', '-')} "
            f"| {iso_mark} ({iso_txt}) "
            f"| {filt} | {rs} | {hy} "
            f"| {badge.get(r.get('verdict'), '?')} {r.get('verdict', '?')} |"
        )
    lines.append("")
    lines.append(
        f"> Kapılar: retrieval P95 ≤ {RETRIEVAL_P95_BUDGET_MS:.0f} ms (SAD §20 RAG kalemi, yeşil ≤ "
        f"{RETRIEVAL_P95_GREEN_MS:.0f}); recall@k (en-kötü sınıf) ≥ {RECALL_MIN:.2f} (yeşil ≥ "
        f"{RECALL_GREEN:.2f}); namespace/tenant izolasyon sızıntı = 0 (FR-KB-004/FR-TEN-002); metadata/ACL "
        "filtre + yetkisiz sızıntı = 0 (FR-KB-005); residency pinning + dış log yok (NFR 10.7/FR-KB-010) "
        "zorunlu. Değerler ölçüm koşuluna bağlı; depo seçimi 0.2.6'da bütünsel yapılır (vendor-neutral)."
    )
    table = "\n".join(lines)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(table + "\n")
        print(f"yazıldı: {args.out}")
    print(table)
    return 0


# ----------------------------------------------------------------------------
# selftest — credential'sız çekirdek doğrulama
# ----------------------------------------------------------------------------
def cmd_selftest(args: argparse.Namespace) -> int:
    checks: list[tuple[str, bool, str]] = []

    def chk(name: str, cond: bool, detail: str = "") -> None:
        checks.append((name, cond, detail))

    # percentile
    chk("p95 of 1..100 ≈ 95.05", abs(_percentile(list(range(1, 101)), 95) - 95.05) < 1e-6,
        f"{_percentile(list(range(1, 101)), 95)}")
    # retrieval-gecikme verdict: lower-is-better
    chk("retrieval 40ms → YEŞİL", _verdict(40.0, green=RETRIEVAL_P95_GREEN_MS,
                                           budget=RETRIEVAL_P95_BUDGET_MS, lower_is_better=True) == "YEŞİL")
    chk("retrieval 160ms → SARI", _verdict(160.0, green=RETRIEVAL_P95_GREEN_MS,
                                           budget=RETRIEVAL_P95_BUDGET_MS, lower_is_better=True) == "SARI")
    chk("retrieval 260ms → KIRMIZI", _verdict(260.0, green=RETRIEVAL_P95_GREEN_MS,
                                              budget=RETRIEVAL_P95_BUDGET_MS, lower_is_better=True) == "KIRMIZI")
    # recall verdict: higher-is-better, en-kötü-sınıf
    chk("recall 0.90 < 0.95 → KIRMIZI", _verdict(0.90, green=RECALL_GREEN, budget=RECALL_MIN,
                                                 lower_is_better=False) == "KIRMIZI")
    chk("recall 0.96 → SARI", _verdict(0.96, green=RECALL_GREEN, budget=RECALL_MIN,
                                       lower_is_better=False) == "SARI")
    chk("recall 0.99 → YEŞİL", _verdict(0.99, green=RECALL_GREEN, budget=RECALL_MIN,
                                        lower_is_better=False) == "YEŞİL")

    # recall@k hesabı
    chk("recall@k 4/5 = 0.8", recall_at_k(["a", "b", "c", "d", "z"], ["a", "b", "c", "d", "e"]) == 0.8,
        f"{recall_at_k(['a', 'b', 'c', 'd', 'z'], ['a', 'b', 'c', 'd', 'e'])}")
    chk("recall@k tam isabet = 1.0", recall_at_k(["a", "b", "c"], ["a", "b", "c"]) == 1.0)
    chk("recall@k boş relevant → None", recall_at_k(["a"], []) is None)
    # sızıntı sayımı
    chk("leak: forbidden döndü → 1", leak_count(["a", "x-other"], ["x-other"]) == 1)
    chk("leak: temiz → 0", leak_count(["a", "b"], ["x-other"]) == 0)
    chk("leak: forbidden yok → 0", leak_count(["a"], []) == 0)

    # residency uygunluğu
    chk("residency: EU pin + EU sunulu + no-log → uygun",
        residency_compliance({"residency_pinned": True, "region": "EU",
                              "available_regions": ["EU", "UK"], "no_external_log": True})[0])
    chk("residency: pin yok → uygunsuz",
        not residency_compliance({"residency_pinned": False, "region": "EU",
                                 "available_regions": ["EU"], "no_external_log": True})[0])
    chk("residency: dış log açık → uygunsuz",
        not residency_compliance({"residency_pinned": True, "region": "EU",
                                 "available_regions": ["EU"], "no_external_log": False})[0])

    # uçtan uca: kapı-geçen aday (düşük gecikme, yüksek recall, izolasyon, filtre, residency)
    sample_ok = {
        "provider": "selftest-ok", "config": {
            "engine": "pgvector", "index_type": "hnsw", "supports_namespace": True, "rls": True,
            "metadata_filter": True, "hybrid_search": False, "incremental_upsert": True,
            "delete_support": True, "residency_pinned": True, "region": "EU",
            "available_regions": ["EU", "UK", "TR"], "no_external_log": True,
            "operational_stackfit": "high"},
        "queries": [
            {"id": "q-f1", "query_class": "factual", "tenant": "A", "namespace": "A/a1", "k": 5,
             "latency_ms": 28, "retrieved_ids": ["d1", "d2", "d3", "d4", "d5"],
             "relevant_ids": ["d1", "d2", "d3", "d4", "d5"], "forbidden_ids": ["B-d9"],
             "filter_applied": True},
            {"id": "q-s1", "query_class": "semantic", "tenant": "A", "namespace": "A/a1", "k": 5,
             "latency_ms": 35, "retrieved_ids": ["d1", "d2", "d3", "d4", "d5"],
             "relevant_ids": ["d1", "d2", "d3", "d4", "d5"], "forbidden_ids": ["B-d9"],
             "filter_applied": True},
            {"id": "q-x1", "query_class": "structured", "tenant": "A", "namespace": "A/a1", "k": 5,
             "latency_ms": 42, "retrieved_ids": ["d1", "d2", "d3", "d4", "d5"],
             "relevant_ids": ["d1", "d2", "d3", "d4", "d5"], "forbidden_ids": ["B-d9"],
             "filter_applied": True},
        ],
    }
    res = summarize_provider(sample_ok)
    chk("score: kapı-geçen aday pass", res["pass"], f"verdict={res['verdict']}")
    chk("score: recall en-kötü-sınıf = min(sınıflar)",
        res["recall"]["worst_class"] == min(res["recall"]["by_query_class"].values()))
    chk("score: izolasyon sızıntı yok", res["isolation"]["leak_total"] == 0)
    chk("score: filtreli sorgu sayısı raporlanır", res["metadata_filter"]["filtered_queries"] == 3)

    # uçtan uca: bir sorgu sınıfı recall düşük → en-kötü-sınıf kapısı eler (genel ortalama maskeleyemez)
    sample_weak_class = {
        "provider": "selftest-weak-class", "config": {
            "engine": "pgvector", "supports_namespace": True, "rls": True, "metadata_filter": True,
            "residency_pinned": True, "region": "EU", "available_regions": ["EU"], "no_external_log": True},
        "queries": [
            {"id": "q-f1", "query_class": "factual", "k": 5, "latency_ms": 30,
             "retrieved_ids": ["d1", "d2", "d3", "d4", "d5"], "relevant_ids": ["d1", "d2", "d3", "d4", "d5"]},
            {"id": "q-x1", "query_class": "structured", "k": 5, "latency_ms": 30,
             "retrieved_ids": ["d1", "z", "y", "w", "v"], "relevant_ids": ["d1", "d2", "d3", "d4", "d5"]},
        ],
    }
    res2 = summarize_provider(sample_weak_class)
    chk("score: structured recall 0.2 → KIRMIZI (en-kötü-sınıf eler)",
        res2["verdict"] == "KIRMIZI" and not res2["gates"]["recall_worst_class"]["pass"],
        f"verdict={res2['verdict']}, worst={res2['recall']['worst_class']}")
    chk("score: genel recall kapıyı maskelemez",
        (res2["recall"]["overall"] or 0) > res2["recall"]["worst_class"],
        f"overall={res2['recall']['overall']}, worst={res2['recall']['worst_class']}")

    # uçtan uca: cross-tenant sızıntı → namespace izolasyon kapısı eler (FR-TEN-002)
    sample_leak = {
        "provider": "selftest-leak", "config": {
            "engine": "managed-x", "supports_namespace": True, "rls": False, "metadata_filter": True,
            "residency_pinned": True, "region": "EU", "available_regions": ["EU"], "no_external_log": True},
        "queries": [
            {"id": "q-1", "query_class": "semantic", "tenant": "A", "k": 5, "latency_ms": 40,
             "retrieved_ids": ["d1", "d2", "B-secret"], "relevant_ids": ["d1", "d2"],
             "forbidden_ids": ["B-secret"], "filter_applied": True},
        ],
    }
    res3 = summarize_provider(sample_leak)
    chk("score: cross-tenant sızıntı → izolasyon fail + KIRMIZI",
        not res3["gates"]["namespace_isolation"]["pass"] and res3["verdict"] == "KIRMIZI",
        f"leak={res3['isolation']['leak_total']}")
    chk("score: filtreli sorguda sızıntı → ACL kapısı da fail",
        not res3["gates"]["metadata_filter_acl"]["pass"])

    # uçtan uca: residency yok (US-only) + dış log → uygunluk fail
    sample_noncompliant = {
        "provider": "selftest-noncompliant", "config": {
            "engine": "managed-y", "supports_namespace": False, "rls": False, "metadata_filter": False,
            "residency_pinned": False, "region": "US", "available_regions": ["US"], "no_external_log": False},
        "queries": [
            {"id": "q-1", "query_class": "semantic", "k": 5, "latency_ms": 240,
             "retrieved_ids": ["d1"], "relevant_ids": ["d1"]},
        ],
    }
    res4 = summarize_provider(sample_noncompliant)
    chk("score: residency yok → uygunluk fail",
        not res4["gates"]["residency_no_log"]["pass"])
    chk("score: namespace/RLS yok → izolasyon fail",
        not res4["gates"]["namespace_isolation"]["pass"])
    chk("score: metadata filtre yok → ACL fail",
        not res4["gates"]["metadata_filter_acl"]["pass"])
    chk("score: retrieval 240ms > 200 → gecikme fail (çoklu KIRMIZI)",
        not res4["gates"]["retrieval_latency_p95_ms"]["pass"] and res4["verdict"] == "KIRMIZI")

    passed = sum(1 for _, c, _ in checks if c)
    for name, cond, detail in checks:
        mark = "✅" if cond else "❌"
        print(f"{mark} {name}" + (f"  ({detail})" if detail and not cond else ""))
    print(f"\n{passed}/{len(checks)} kontrol geçti.")
    return 0 if passed == len(checks) else 1


# ----------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Vector DB değerlendirme hattı (WBS 0.2.5)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sc = sub.add_parser("score", help="bir aday sorgu test setini puanla + kapı")
    sc.add_argument("sample", help="aday sorgu test seti JSON")
    sc.add_argument("--out", help="özet JSON dosyası")
    sc.set_defaults(func=cmd_score)

    cp = sub.add_parser("compare", help="çok adaylı karşılaştırma matrisi (markdown)")
    cp.add_argument("results", nargs="+", help="score çıktısı JSON dosyaları")
    cp.add_argument("--out")
    cp.set_defaults(func=cmd_compare)

    st = sub.add_parser("selftest", help="credential'sız çekirdek doğrulama")
    st.set_defaults(func=cmd_selftest)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
