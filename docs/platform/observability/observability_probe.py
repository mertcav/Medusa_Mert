#!/usr/bin/env python3
"""observability_probe.py — Gözlemlenebilirlik omurgası iskelet doğrulayıcı (WBS 0.4.7, →SAD §17, BRD §15).

Amaç: OTel + Prometheus + Grafana + Loki iskeletinin **tasarım-tamlık kapısını** ölçüm-temelli
kapatmak. 0.2.x/0.3.x probe disiplinini (stdlib-only, credential-free, deterministik, kapı→çıkış
kodu) bu sefer bir **konfigürasyon/spec doğrulamasına** uygular — gecikme/density ÖLÇMEZ; iskeletin
BRD §15 / SAD §17 gereksinimlerini eksiksiz kapsadığını ve config'lerin spec ile tutarlı olduğunu
doğrular.

Kapı (HARD → çıkış kodu):
  1. SPEC sağlık: observability-spec.json iyi-biçimli + zorunlu bölümler mevcut.
  2. KAPSAM (coverage): BRD §15 metrik + zaman-damgası (span) + SAD §17.2 alarm kataloğunun TAMAMI
     spec'te mevcut. (Gereksinim referansı bu dosyada SABİT — BRD/SAD'den; kapsam **dairesel değil**.)
  3. KARDİNALİTE invariant'ı: hiçbir metrik forbidden label kullanmaz; yüksek-kardinalite kimlik
     (correlation_id vb.) metric_labels_allowed'da DEĞİL; trace/log zorunlu key'leri tanımlı.
  4. ALARM bütçesi: her alarm detection_budget_s ≤ 120 (NFR 10.1 'alarm ≤2dk'); alerts.yaml `for:` ≤2dk.
  5. ÇAPRAZ-TUTARLILIK: her spec alarmı config/alerts.yaml'da bir `alert:` kuralı; üç pipeline
     (traces/metrics/logs) otel-collector.yaml service.pipelines'da; tüm config dosyaları mevcut;
     grafana dashboard geçerli JSON + zorunlu panolar; sampling.always_sample boş değil.

Vendor-neutral (ADR-002 ruhu): OTel/Prometheus/Grafana/Loki açık standartlardır; spec sağlayıcı seçmez.
YAML config'ler stdlib'de tam parse edilmez → bu probe **hafif satır-tabanlı varlık kontrolü** yapar
(anahtar/isim substring + `for:` süre parse). Tam şema doğrulaması canlı CI'da (0.4.4) promtool/otelcol
validate ile yapılır; bu probe iskelet-tamlık kapısıdır.
"""

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "observability-spec.json")

# ── Gereksinim referansı (SABİT — BRD §15 / SAD §17.2'den). Kapsam bunlara karşı ölçülür. ──

# BRD §15 saklanması gereken teknik metrikler (kanonik liste).
REQUIRED_BRD15_METRICS = [
    "packet loss", "jitter", "codec", "SIP response code", "STT latency",
    "word confidence", "LLM latency", "token kullanımı", "tool latency", "TTS latency",
    "end-to-end response latency", "barge-in sayısı", "silence süresi", "retry/fallback",
    "transfer sonucu", "çağrı sonlandırma nedeni", "provider hata oranı",
    "dakika başı maliyet", "çağrı başına CPU", "çağrı başına bellek",
]

# BRD §15 / SAD §17.1 zaman damgaları (kanonik span listesi).
REQUIRED_SPANS = [
    "call_connected", "first_audio_received", "speech_started", "speech_ended",
    "stt_partial", "stt_final", "llm_request_started", "llm_first_token",
    "tool_request", "tool_response", "tts_request", "tts_first_audio",
    "audio_played", "call_transferred", "call_ended",
]

# SAD §17.2 / BRD §15 kritik alarm kataloğu (kanonik — sad172 ifadesiyle eşlenir).
REQUIRED_ALERTS = [
    "P95 > 1.5sn", "STT hata artışı", "LLM sağlayıcı hata artışı",
    "handoff başarısızlığı", "tool hata artışı", "silent call",
    "consent kontrolü atlama", "bilgi sızıntısı tespiti", "tenant kapasitesi %80",
    "harcama limiti aşımı", "kaynak bütçesi aşımı",
]

MAX_DETECTION_BUDGET_S = 120  # NFR 10.1
REQUIRED_PIPELINES = ["traces", "metrics", "logs"]


# ── Yardımcılar ──────────────────────────────────────────────────────────────

def load_spec(path=SPEC_PATH):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _norm(s):
    return re.sub(r"\s+", " ", s.strip().lower())


def parse_duration_to_s(text):
    """'1m'/'30s'/'2m'/'1h' → saniye. Bilinmeyen → None."""
    m = re.fullmatch(r"\s*(\d+)\s*([smh])\s*", text)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    return n * {"s": 1, "m": 60, "h": 3600}[unit]


def read_text(rel):
    p = os.path.join(HERE, rel)
    if not os.path.exists(p):
        return None
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


# ── Kontroller ───────────────────────────────────────────────────────────────

def check_spec_health(spec):
    errs = []
    for sect in ("pipelines", "label_policy", "sampling", "spans", "metrics", "alerts", "config_files"):
        if sect not in spec:
            errs.append(f"spec eksik bölüm: {sect}")
    return errs


def check_coverage(spec):
    errs = []
    # Metrikler — brd15 alanlarına göre.
    spec_brd15 = {_norm(m.get("brd15", "")) for m in spec.get("metrics", {}).get("catalog", [])}
    for req in REQUIRED_BRD15_METRICS:
        if _norm(req) not in spec_brd15:
            errs.append(f"BRD §15 metrik kapsanmadı: {req}")
    # Span zaman damgaları.
    spec_spans = set(spec.get("spans", {}).get("timestamps", []))
    for req in REQUIRED_SPANS:
        if req not in spec_spans:
            errs.append(f"BRD §15 span/zaman-damgası kapsanmadı: {req}")
    # Alarmlar — sad172 alanlarına göre.
    spec_alerts = {_norm(a.get("sad172", "")) for a in spec.get("alerts", {}).get("catalog", [])}
    for req in REQUIRED_ALERTS:
        if _norm(req) not in spec_alerts:
            errs.append(f"SAD §17.2 alarm kapsanmadı: {req}")
    return errs


def check_cardinality(spec):
    errs = []
    lp = spec.get("label_policy", {})
    allowed = set(lp.get("metric_labels_allowed", []))
    forbidden = set(lp.get("metric_labels_forbidden", []))
    high_card = set(lp.get("high_cardinality_keys", []))
    # forbidden ∩ allowed = ∅
    bad = allowed & forbidden
    if bad:
        errs.append(f"label_policy çelişki: allowed ∩ forbidden = {sorted(bad)}")
    # yüksek-kardinalite kimlik metrik label'ı OLAMAZ
    leaked = high_card & allowed
    if leaked:
        errs.append(f"yüksek-kardinalite kimlik metrik label'ında: {sorted(leaked)}")
    # her metrik yalnız allowed label kullanır
    for m in spec.get("metrics", {}).get("catalog", []):
        for lbl in m.get("labels", []):
            if lbl in forbidden:
                errs.append(f"metrik {m['name']} forbidden label kullanıyor: {lbl}")
            elif lbl not in allowed:
                errs.append(f"metrik {m['name']} allowed-dışı label: {lbl}")
    # trace/log zorunlu key'leri
    if not lp.get("trace_log_required_keys"):
        errs.append("label_policy.trace_log_required_keys boş (correlation_id+tenant_id beklenir)")
    return errs


def check_alert_budget(spec):
    errs = []
    cap = spec.get("alerts", {}).get("max_detection_budget_s", MAX_DETECTION_BUDGET_S)
    if cap > MAX_DETECTION_BUDGET_S:
        errs.append(f"max_detection_budget_s {cap} > {MAX_DETECTION_BUDGET_S} (NFR 10.1)")
    for a in spec.get("alerts", {}).get("catalog", []):
        b = a.get("detection_budget_s")
        if b is None or b > MAX_DETECTION_BUDGET_S:
            errs.append(f"alarm {a.get('name')} detection_budget_s={b} > {MAX_DETECTION_BUDGET_S}")
    return errs


def check_cross_consistency(spec):
    errs = []
    cf = spec.get("config_files", {})
    # tüm config dosyaları mevcut ($comment vb. meta anahtarları atla)
    for key, rel in cf.items():
        if key.startswith("$") or not isinstance(rel, str):
            continue
        if read_text(rel) is None:
            errs.append(f"config dosyası eksik: {key} → {rel}")

    # alerts.yaml: her spec alarmı bir `alert:` kuralı + `for:` ≤120s
    alerts_txt = read_text(cf.get("alerts", "")) or ""
    rule_names = set(re.findall(r"-\s*alert:\s*([A-Za-z0-9_]+)", alerts_txt))
    for a in spec.get("alerts", {}).get("catalog", []):
        nm = a.get("name")
        if nm not in rule_names:
            errs.append(f"spec alarmı alerts.yaml'da kural değil: {nm}")
    for dur in re.findall(r"\n\s*for:\s*([0-9]+[smh])", alerts_txt):
        s = parse_duration_to_s(dur)
        if s is None or s > MAX_DETECTION_BUDGET_S:
            errs.append(f"alerts.yaml `for: {dur}` > {MAX_DETECTION_BUDGET_S}s")

    # otel-collector.yaml: üç pipeline service.pipelines altında
    otel_txt = read_text(cf.get("otel_collector", "")) or ""
    pipe_block = otel_txt.split("pipelines:", 1)[-1] if "pipelines:" in otel_txt else ""
    for pl in REQUIRED_PIPELINES:
        if not re.search(rf"\n\s+{pl}:", pipe_block):
            errs.append(f"otel-collector.yaml service.pipelines'da eksik: {pl}")

    # grafana dashboard: geçerli JSON + zorunlu panolar (refresh ≤60sn)
    gtxt = read_text(cf.get("grafana_dashboard_voice_runtime", ""))
    if gtxt is not None:
        try:
            dash = json.loads(gtxt)
            if not dash.get("panels"):
                errs.append("grafana dashboard panel içermiyor")
            refresh = parse_duration_to_s(dash.get("refresh", "")) if isinstance(dash.get("refresh"), str) else None
            if refresh is None or refresh > spec.get("dashboards", {}).get("freshness_budget_s", 60):
                errs.append(f"grafana refresh '{dash.get('refresh')}' > {spec.get('dashboards',{}).get('freshness_budget_s',60)}s (FR-ANA-012)")
        except json.JSONDecodeError as e:
            errs.append(f"grafana dashboard geçersiz JSON: {e}")

    # sampling.always_sample boş olamaz ('measure everything cheaply' + kritik olayları kaybetme)
    if not spec.get("sampling", {}).get("always_sample"):
        errs.append("sampling.always_sample boş (hata/yavaş/kritik olaylar kaybedilir)")

    return errs


def run_all_checks(spec):
    groups = [
        ("spec-health", check_spec_health(spec)),
        ("coverage", check_coverage(spec)),
        ("cardinality", check_cardinality(spec)),
        ("alert-budget", check_alert_budget(spec)),
        ("cross-consistency", check_cross_consistency(spec)),
    ]
    return groups


# ── CLI komutları ────────────────────────────────────────────────────────────

def cmd_validate(args):
    spec = load_spec(args.spec)
    groups = run_all_checks(spec)
    total_err = sum(len(e) for _, e in groups)
    print("# Gözlemlenebilirlik omurgası iskelet doğrulaması (WBS 0.4.7)\n")
    for name, errs in groups:
        mark = "🟢" if not errs else "🔴"
        print(f"{mark} {name}: {'GEÇTİ' if not errs else str(len(errs)) + ' hata'}")
        for e in errs:
            print(f"    - {e}")
    nm = spec.get("metrics", {}).get("catalog", [])
    na = spec.get("alerts", {}).get("catalog", [])
    ns = spec.get("spans", {}).get("timestamps", [])
    print(f"\nKapsam: {len(nm)} metrik, {len(ns)} span, {len(na)} alarm.")
    verdict = "🟢 KAPI GEÇTİ" if total_err == 0 else f"🔴 KAPI ELENDİ ({total_err} hata)"
    print(f"\n{verdict}")
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump({"groups": {n: e for n, e in groups}, "errors": total_err,
                       "pass": total_err == 0}, f, ensure_ascii=False, indent=2)
    return 0 if total_err == 0 else 1


def cmd_coverage(args):
    spec = load_spec(args.spec)
    print("# Kapsam matrisi (gereksinim → spec)\n")
    print(f"BRD §15 metrik: {len(REQUIRED_BRD15_METRICS)} gerekli")
    print(f"BRD §15 span : {len(REQUIRED_SPANS)} gerekli")
    print(f"SAD §17.2 alarm: {len(REQUIRED_ALERTS)} gerekli")
    errs = check_coverage(spec)
    if not errs:
        print("\n🟢 TÜM gereksinimler kapsandı.")
        return 0
    print(f"\n🔴 {len(errs)} kapsam boşluğu:")
    for e in errs:
        print(f"    - {e}")
    return 1


def cmd_schema(args):
    print(json.dumps({
        "spec_file": "observability-spec.json",
        "required_sections": ["pipelines", "label_policy", "sampling", "spans", "metrics", "alerts", "config_files"],
        "gate": {
            "coverage": "BRD §15 metrik+span + SAD §17.2 alarm = %100",
            "cardinality": "metrik label ⊆ allowed; high-card ∉ allowed",
            "alert_budget_s": MAX_DETECTION_BUDGET_S,
            "cross_consistency": "spec alarm↔alerts.yaml; 3 pipeline↔otel; config dosyaları mevcut; grafana JSON+refresh≤60s",
        },
        "required_pipelines": REQUIRED_PIPELINES,
        "required_brd15_metrics": REQUIRED_BRD15_METRICS,
        "required_spans": REQUIRED_SPANS,
        "required_alerts": REQUIRED_ALERTS,
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_selftest(args):
    """Kapı/invariant/determinizm — credential'sız. Pozitif (gerçek spec geçer) + negatif (kasıtlı ihlaller yakalanır)."""
    import copy
    passed = failed = 0

    def ok(cond, msg):
        nonlocal passed, failed
        if cond:
            passed += 1
        else:
            failed += 1
            print(f"  ✗ {msg}")

    spec = load_spec()

    # 1. Gerçek iskelet TÜM kapılardan geçer.
    groups = run_all_checks(spec)
    ok(all(not e for _, e in groups), "gerçek iskelet tüm kapılardan geçmeli")

    # 2. Kapsam: metrik silinince yakalanır.
    s2 = copy.deepcopy(spec)
    s2["metrics"]["catalog"] = s2["metrics"]["catalog"][:-3]
    ok(len(check_coverage(s2)) >= 3, "eksik metrik → kapsam hatası")

    # 3. Kapsam: span silinince yakalanır.
    s3 = copy.deepcopy(spec)
    s3["spans"]["timestamps"] = s3["spans"]["timestamps"][:-2]
    ok(len(check_coverage(s3)) >= 2, "eksik span → kapsam hatası")

    # 4. Kapsam: alarm silinince yakalanır.
    s4 = copy.deepcopy(spec)
    s4["alerts"]["catalog"] = s4["alerts"]["catalog"][:-1]
    ok(len(check_coverage(s4)) >= 1, "eksik alarm → kapsam hatası")

    # 5. Kardinalite: metrik forbidden label kullanınca yakalanır.
    s5 = copy.deepcopy(spec)
    s5["metrics"]["catalog"][0]["labels"].append("correlation_id")
    ok(any("forbidden" in e or "allowed-dışı" in e for e in check_cardinality(s5)),
       "metrikte correlation_id → kardinalite hatası")

    # 6. Kardinalite: high-card key allowed'a sızınca yakalanır.
    s6 = copy.deepcopy(spec)
    s6["label_policy"]["metric_labels_allowed"].append("call_id")
    ok(any("yüksek-kardinalite" in e for e in check_cardinality(s6)),
       "high-card key allowed → kardinalite hatası")

    # 7. Alarm bütçesi: >120s yakalanır.
    s7 = copy.deepcopy(spec)
    s7["alerts"]["catalog"][0]["detection_budget_s"] = 300
    ok(len(check_alert_budget(s7)) >= 1, "detection_budget 300s → bütçe hatası")

    # 8. Süre parse'ı.
    ok(parse_duration_to_s("2m") == 120 and parse_duration_to_s("30s") == 30
       and parse_duration_to_s("1h") == 3600 and parse_duration_to_s("x") is None,
       "süre parse doğru")

    # 9. Çapraz: gerçek alerts.yaml her spec alarmını içerir.
    ok(not check_cross_consistency(spec), "çapraz-tutarlılık gerçek dosyalarla geçer")

    # 10. Determinizm: aynı spec → aynı sonuç.
    ok([e for _, e in run_all_checks(spec)] == [e for _, e in run_all_checks(load_spec())],
       "determinizm: tekrarlı çalıştırma aynı")

    # 11. Spec sağlık: bölüm silinince yakalanır.
    s11 = copy.deepcopy(spec)
    del s11["sampling"]
    ok(len(check_spec_health(s11)) >= 1, "eksik bölüm → spec-health hatası")

    total = passed + failed
    print(f"\nselftest: {passed}/{total} geçti")
    return 0 if failed == 0 else 1


def main(argv=None):
    p = argparse.ArgumentParser(description="Gözlemlenebilirlik omurgası iskelet doğrulayıcı (WBS 0.4.7, →SAD §17)")
    sub = p.add_subparsers(dest="cmd", required=True)

    pv = sub.add_parser("validate", help="Spec + config iskeletini tüm kapılara karşı doğrula")
    pv.add_argument("--spec", default=SPEC_PATH)
    pv.add_argument("--json-out", help="sonuç JSON çıktısı")
    pv.set_defaults(func=cmd_validate)

    pc = sub.add_parser("coverage", help="BRD §15 / SAD §17.2 kapsam matrisi")
    pc.add_argument("--spec", default=SPEC_PATH)
    pc.set_defaults(func=cmd_coverage)

    ps = sub.add_parser("schema", help="Spec şemasını + kapı tanımını yaz")
    ps.set_defaults(func=cmd_schema)

    pt = sub.add_parser("selftest", help="Kapı/invariant/determinizm (credential'sız)")
    pt.set_defaults(func=cmd_selftest)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
