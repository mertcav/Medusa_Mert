#!/usr/bin/env python3
"""vendor_decision_probe.py — Vendor karar birleştirme hattı (WBS 0.2.6, →SAD §8.1/§8.4, ADR-002).

0.2.x vendor-değerlendirme iş paketinin **kapanış/sentez** adımı. Bu hat **yeniden ölçmez**; 0.2.1–0.2.5
probe'larının ürettiği `score`/`stats` JSON çıktılarını **girdi** alır ve tek karar matrisine birleştirir:

- **rollup:** Her kategori (telekom/STT/TTS/LLM/Vector DB) için aday verdict'lerini normalize eder
  (top-level `verdict`/`pass` ya da telekomdaki `gate.verdict`/`gate.pass`), kategori başına geçen aday
  sayar ve **ADR-002 portföy kapısını** uygular: medya-hot-path kategorilerinin her birinde ≥2 geçen aday
  + farklı sağlayıcı (tek nokta arıza yok) → BRD §19 kabul kriteri 1–4. Markdown matris + çıkış kodu.
- **register:** Adayların `config` bayraklarından **alt-işleyen kayıt iskeleti** (DPA Ek-A) üretir
  (residency/region/no-train/no-log). Sağlayıcı SEÇMEZ; yalnız sunulan girdiyi tabloya döker.
- **selftest:** credential'sız çekirdek doğrulama (kategori çıkarımı, verdict normalizasyonu, portföy kapısı).

İlkeler (CLAUDE.md / ADR-002): **sağlayıcı-nötr** (kapı + birleştirme üretir, seçim yapmaz; bağlayıcı seçim
0.3.x PoC + DPA imzasında), **stdlib-only**, **sır/credential yazılmaz** (gerçek bağlantı yalnız 0.2.x
probe'larında --url/ortam değişkeniyle). Bağlam: `vendor-decision.md`, `contract-dpa-checklist.md`.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

# Medya hot-path kategorileri — ADR-002 portföy kapısına dahil (BRD §19 1–4).
HOT_PATH = ["telephony", "stt", "tts", "llm"]
# Vector DB hot-path değil (Should); ≥2 aday disiplini korunur ama portföy kapısına dahil değil.
ALL_CATEGORIES = HOT_PATH + ["vector_db"]

CATEGORY_LABEL = {
    "telephony": "Telekom",
    "stt": "STT",
    "tts": "TTS",
    "llm": "LLM",
    "vector_db": "Vector DB",
    "unknown": "(bilinmiyor)",
}

# Verdict normalizasyonu: 0.2.x probe'ları YEŞİL/SARI/KIRMIZI üretir.
GREEN, YELLOW, RED = "YEŞİL", "SARI", "KIRMIZI"


def infer_category(path: str, doc: dict) -> str:
    """Kategoriyi JSON `category` alanından ya da dosya adı önekinden çıkar."""
    cat = (doc.get("category") or "").strip().lower()
    if cat in ALL_CATEGORIES:
        return cat
    name = os.path.basename(path).lower()
    # Sırayla en spesifik eşleşme.
    if name.startswith("vdb") or "vector" in name:
        return "vector_db"
    if name.startswith("stt") or "stt" in name:
        return "stt"
    if name.startswith("tts") or "tts" in name:
        return "tts"
    if name.startswith("llm") or "llm" in name:
        return "llm"
    if (name.startswith("tel") or "telephony" in name or "media" in name
            or "cpaas" in name or name.startswith("raw") or name.startswith("managed")):
        return "telephony"
    return "unknown"


def extract_verdict(doc: dict) -> tuple[str | None, bool | None]:
    """Verdict/pass'ı top-level ya da `gate.*` alanından normalize et.

    Score probe'ları (stt/tts/llm/vdb): top-level `verdict`/`pass`.
    Telekom `stats`: `gate.verdict`/`gate.pass`.
    """
    if "pass" in doc or "verdict" in doc:
        return doc.get("verdict"), doc.get("pass")
    gate = doc.get("gate")
    if isinstance(gate, dict):
        return gate.get("verdict"), gate.get("pass")
    return None, None


def provider_name(path: str, doc: dict) -> str:
    return doc.get("provider") or os.path.splitext(os.path.basename(path))[0]


def load_candidates(paths: list[str]) -> list[dict]:
    """JSON dosyalarını yükle → normalize edilmiş aday kayıtları."""
    cands = []
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"uyarı: {path} okunamadı/ayrıştırılamadı ({e}); atlanıyor.", file=sys.stderr)
            continue
        if not isinstance(doc, dict):
            print(f"uyarı: {path} beklenen nesne değil; atlanıyor.", file=sys.stderr)
            continue
        verdict, passed = extract_verdict(doc)
        cands.append({
            "path": path,
            "provider": provider_name(path, doc),
            "category": infer_category(path, doc),
            "verdict": verdict,
            "pass": passed,
            "config": doc.get("config") if isinstance(doc.get("config"), dict) else {},
        })
    return cands


# ----------------------------------------------------------------------------
def evaluate_portfolio(cands: list[dict]) -> dict:
    """ADR-002 portföy kapısı: her hot-path kategoride ≥2 geçen + farklı sağlayıcı."""
    by_cat: dict[str, list[dict]] = {}
    for c in cands:
        by_cat.setdefault(c["category"], []).append(c)

    result = {"categories": {}, "portfolio_green": True, "missing": []}
    for cat in ALL_CATEGORIES:
        items = by_cat.get(cat, [])
        # "geçen" = pass True (verdict KIRMIZI değil). pass None ise verdict'e bak.
        passing = [c for c in items
                   if c["pass"] is True or (c["pass"] is None and c["verdict"] in (GREEN, YELLOW))]
        distinct_providers = {c["provider"] for c in passing}
        cat_ok = len(passing) >= 2 and len(distinct_providers) >= 2
        result["categories"][cat] = {
            "total": len(items),
            "passing": len(passing),
            "distinct_passing_providers": len(distinct_providers),
            "passing_providers": sorted(distinct_providers),
            "gate_pass": cat_ok,
            "hot_path": cat in HOT_PATH,
        }
        if cat in HOT_PATH and not cat_ok:
            result["portfolio_green"] = False
            result["missing"].append(cat)
    # Hot-path kategorisinde hiç girdi yoksa da eksiktir.
    for cat in HOT_PATH:
        if by_cat.get(cat) is None and cat not in result["missing"]:
            result["portfolio_green"] = False
            result["missing"].append(cat)
    return result


def render_rollup_md(cands: list[dict], portfolio: dict) -> str:
    lines = ["# Vendor Karar Matrisi — rollup (WBS 0.2.6)", ""]
    lines.append("> Birleştirilmiş 0.2.x eval kapıları. Sağlayıcı SEÇMEZ; bağlayıcı seçim 0.3.x PoC + DPA.")
    lines.append("")
    # Aday matrisi (kategori sıralı).
    lines.append("## Adaylar")
    lines.append("")
    lines.append("| Kategori | Aday | Verdict | Geçti? | Hot-path |")
    lines.append("|---|---|---|---|---|")
    order = {cat: i for i, cat in enumerate(ALL_CATEGORIES + ["unknown"])}
    for c in sorted(cands, key=lambda x: (order.get(x["category"], 99), x["provider"])):
        passed = c["pass"]
        pmark = "✅" if passed is True else ("❌" if passed is False else "—")
        hp = "evet" if c["category"] in HOT_PATH else "hayır"
        lines.append(f"| {CATEGORY_LABEL.get(c['category'], c['category'])} | {c['provider']} | "
                     f"{c['verdict'] or '—'} | {pmark} | {hp} |")
    lines.append("")
    # Portföy kapısı.
    lines.append("## ADR-002 portföy kapısı (≥2 geçen + farklı sağlayıcı / hot-path)")
    lines.append("")
    lines.append("| Kategori | Aday | Geçen | Farklı sağlayıcı | Kapı | Hot-path |")
    lines.append("|---|---|---|---|---|---|")
    for cat in ALL_CATEGORIES:
        st = portfolio["categories"].get(cat)
        if st is None:
            lines.append(f"| {CATEGORY_LABEL[cat]} | 0 | 0 | 0 | ⚠️ girdi yok | "
                         f"{'evet' if cat in HOT_PATH else 'hayır'} |")
            continue
        gate = "✅ geçer" if st["gate_pass"] else "❌ eksik"
        lines.append(f"| {CATEGORY_LABEL[cat]} | {st['total']} | {st['passing']} | "
                     f"{st['distinct_passing_providers']} | {gate} | "
                     f"{'evet' if st['hot_path'] else 'hayır'} |")
    lines.append("")
    verdict = "🟢 PORTFÖY YEŞİL" if portfolio["portfolio_green"] else "🔴 PORTFÖY EKSİK"
    lines.append(f"**Sonuç:** {verdict}")
    if portfolio["missing"]:
        miss = ", ".join(CATEGORY_LABEL.get(m, m) for m in portfolio["missing"])
        lines.append(f"  · Eksik hot-path kategori(ler): {miss} (her birinde ≥2 farklı geçen aday gerekli)")
    lines.append("")
    return "\n".join(lines)


def cmd_rollup(args) -> int:
    paths = _expand(args.results)
    if not paths:
        print("hata: hiç girdi JSON bulunamadı.", file=sys.stderr)
        return 2
    cands = load_candidates(paths)
    portfolio = evaluate_portfolio(cands)
    md = render_rollup_md(cands, portfolio)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"karar matrisi yazıldı: {args.out}")
    else:
        print(md)
    # Çıkış kodu: portföy yeşilse 0, eksikse 1 (CI/0.4.4 gate).
    return 0 if portfolio["portfolio_green"] else 1


# ----------------------------------------------------------------------------
def _flag(config: dict, *keys, default="—"):
    """config'te verilen anahtarlardan ilk var olanı evet/hayır olarak döndür."""
    for k in keys:
        if k in config:
            v = config[k]
            if isinstance(v, bool):
                return "evet" if v else "hayır"
            return str(v)
    return default


def render_register_md(cands: list[dict]) -> str:
    lines = ["# Alt-İşleyen Kayıt İskeleti — DPA Ek-A (WBS 0.2.6 / 17.2.2)", ""]
    lines.append("> `config` bayraklarından TÜRETİLEN iskelet. Sağlayıcı SEÇMEZ; counsel + ticari bilgiyle")
    lines.append("> doldurulur. Bkz `contract-dpa-checklist.md` §3. (FR-LLM-012 no-train · FR-KB-010 no-log · NFR 10.7 residency)")
    lines.append("")
    lines.append("| Alt-işleyen | Kategori | Bölge | Residency pin | No-train | No-log | Durum |")
    lines.append("|---|---|---|---|---|---|---|")
    order = {cat: i for i, cat in enumerate(ALL_CATEGORIES + ["unknown"])}
    for c in sorted(cands, key=lambda x: (order.get(x["category"], 99), x["provider"])):
        cfg = c["config"]
        region = _flag(cfg, "region", "residency", "home_region")
        res = _flag(cfg, "residency_pinned", "region_pinned", "provider_region_pinning")
        notrain = _flag(cfg, "no_train", "noTrain", "no_train_endpoint")
        nolog = _flag(cfg, "no_external_log", "no_log", "ephemeral")
        # pgvector self-host → alt-işleyen değil (dahili altyapı).
        prov = c["provider"]
        durum = "dahili/altyapı" if "pgvector" in prov.lower() else "aday"
        lines.append(f"| {prov} | {CATEGORY_LABEL.get(c['category'], c['category'])} | {region} | "
                     f"{res} | {notrain} | {nolog} | {durum} |")
    lines.append("")
    lines.append("> Not: `—` = ilgili `config` bayrağı sample'da yok (canlı PoC/sözleşmede doldurulur). "
                 "pgvector self-hosted ise RMC'nin kendi altyapısıdır, alt-işleyen değildir.")
    lines.append("")
    return "\n".join(lines)


def cmd_register(args) -> int:
    paths = _expand(args.results)
    if not paths:
        print("hata: hiç girdi JSON bulunamadı.", file=sys.stderr)
        return 2
    cands = load_candidates(paths)
    md = render_register_md(cands)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"alt-işleyen kayıt iskeleti yazıldı: {args.out}")
    else:
        print(md)
    return 0


def _expand(patterns: list[str]) -> list[str]:
    """Glob + dosya listesi düzleştir (kabuk genişletmese de çalışsın)."""
    out: list[str] = []
    for pat in patterns:
        if os.path.isfile(pat):
            out.append(pat)
        else:
            out.extend(sorted(glob.glob(pat)))
    # Tekrarları koru-sıra ile çıkar.
    seen, uniq = set(), []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


# ----------------------------------------------------------------------------
def cmd_selftest(args) -> int:
    checks: list[tuple[str, bool, str]] = []

    def chk(name: str, cond: bool, detail: str = "") -> None:
        checks.append((name, bool(cond), detail))

    # --- Kategori çıkarımı ---
    chk("kategori: dosya adı 'stt-cloud-A.json' → stt",
        infer_category("samples/stt-cloud-A.json", {}) == "stt")
    chk("kategori: 'vdb-pgvector.json' → vector_db",
        infer_category("vdb-pgvector.json", {}) == "vector_db")
    chk("kategori: 'managed-cpaas-ws-A.json' → telephony",
        infer_category("managed-cpaas-ws-A.json", {}) == "telephony")
    chk("kategori: JSON 'category' alanı dosya adını ezer",
        infer_category("rastgele.json", {"category": "llm"}) == "llm")
    chk("kategori: eşleşmeyen → unknown",
        infer_category("foobar.json", {}) == "unknown")

    # --- Verdict normalizasyonu (top-level vs gate) ---
    v1, p1 = extract_verdict({"verdict": "SARI", "pass": True})
    chk("verdict: top-level okunur", v1 == "SARI" and p1 is True)
    v2, p2 = extract_verdict({"gate": {"verdict": "YEŞİL", "pass": True}})
    chk("verdict: gate.* (telekom) okunur", v2 == "YEŞİL" and p2 is True)
    v3, p3 = extract_verdict({"foo": 1})
    chk("verdict: yoksa (None, None)", v3 is None and p3 is None)

    # --- Portföy kapısı: tam set, her hot-path'te ≥2 farklı geçen ---
    def cand(prov, cat, passed, verdict="SARI", cfg=None):
        return {"path": f"{prov}.json", "provider": prov, "category": cat,
                "verdict": verdict, "pass": passed, "config": cfg or {}}

    full = []
    for cat in HOT_PATH:
        full.append(cand(f"{cat}-A", cat, True))
        full.append(cand(f"{cat}-B", cat, True))
    full.append(cand("vdb-pgvector", "vector_db", True))
    full.append(cand("vdb-opensearch", "vector_db", True))
    port = evaluate_portfolio(full)
    chk("portföy: her hot-path'te 2 farklı geçen → YEŞİL", port["portfolio_green"] is True)

    # --- Tek aday → kapı eksik ---
    one = [cand("stt-A", "stt", True)]
    port1 = evaluate_portfolio(one)
    chk("portföy: stt'de tek aday → kapı eksik",
        port1["portfolio_green"] is False and "stt" in port1["missing"])

    # --- İki kayıt ama aynı sağlayıcı → tek nokta arıza, geçmez ---
    same = [cand("stt-A", "stt", True), cand("stt-A", "stt", True)]
    # diğer hot-path'leri doldur ki sadece bu kategori test edilsin
    for cat in ["telephony", "tts", "llm"]:
        same += [cand(f"{cat}-A", cat, True), cand(f"{cat}-B", cat, True)]
    same += [cand("vdb-x", "vector_db", True), cand("vdb-y", "vector_db", True)]
    port_same = evaluate_portfolio(same)
    chk("portföy: aynı sağlayıcı 2 kez → farklı-sağlayıcı kuralı eler",
        port_same["portfolio_green"] is False and "stt" in port_same["missing"])

    # --- KIRMIZI aday geçeni saymaz ---
    redmix = []
    for cat in HOT_PATH:
        redmix.append(cand(f"{cat}-A", cat, True))
        redmix.append(cand(f"{cat}-B", cat, False, verdict="KIRMIZI"))
    redmix += [cand("vdb-a", "vector_db", True), cand("vdb-b", "vector_db", True)]
    port_red = evaluate_portfolio(redmix)
    chk("portföy: KIRMIZI aday geçen sayılmaz → her hot-path 1 geçen → eksik",
        port_red["portfolio_green"] is False and set(port_red["missing"]) == set(HOT_PATH))

    # --- pass None ama verdict YEŞİL → geçen sayılır (telekom stats davranışı) ---
    nonepass = [cand("tel-A", "telephony", None, verdict="YEŞİL"),
                cand("tel-B", "telephony", None, verdict="SARI")]
    for cat in ["stt", "tts", "llm"]:
        nonepass += [cand(f"{cat}-A", cat, True), cand(f"{cat}-B", cat, True)]
    nonepass += [cand("vdb-a", "vector_db", True), cand("vdb-b", "vector_db", True)]
    port_none = evaluate_portfolio(nonepass)
    chk("portföy: pass=None + verdict YEŞİL/SARI → geçen sayılır",
        port_none["portfolio_green"] is True)

    # --- register flag türetimi ---
    reg = render_register_md([cand("p", "llm", True, cfg={"region": "EU", "no_train": True,
                                                          "no_external_log": True})])
    chk("register: config bayrakları tabloya yansır",
        "EU" in reg and "evet" in reg and "DPA Ek-A" in reg)
    reg2 = render_register_md([cand("pgvector", "vector_db", True, cfg={})])
    chk("register: pgvector → 'dahili/altyapı' (alt-işleyen değil)", "dahili/altyapı" in reg2)

    # --- rollup markdown üretimi (uçtan uca) ---
    md = render_rollup_md(full, port)
    chk("rollup: markdown matris + portföy yeşil üretir",
        "PORTFÖY YEŞİL" in md and "ADR-002 portföy kapısı" in md)

    passed = sum(1 for _, c, _ in checks if c)
    for name, cond, detail in checks:
        mark = "✅" if cond else "❌"
        print(f"{mark} {name}" + (f"  ({detail})" if detail and not cond else ""))
    print(f"\n{passed}/{len(checks)} kontrol geçti.")
    return 0 if passed == len(checks) else 1


# ----------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Vendor karar birleştirme hattı (WBS 0.2.6)")
    sub = p.add_subparsers(dest="cmd", required=True)

    rl = sub.add_parser("rollup", help="0.2.x score/stats JSON'larını birleştir + ADR-002 portföy kapısı")
    rl.add_argument("results", nargs="+", help="0.2.x score/stats çıktısı JSON dosyaları (glob destekli)")
    rl.add_argument("--out", help="karar matrisi markdown dosyası")
    rl.set_defaults(func=cmd_rollup)

    rg = sub.add_parser("register", help="alt-işleyen kayıt iskeleti (DPA Ek-A) üret")
    rg.add_argument("results", nargs="+", help="aday score JSON dosyaları (glob destekli)")
    rg.add_argument("--out")
    rg.set_defaults(func=cmd_register)

    st = sub.add_parser("selftest", help="credential'sız çekirdek doğrulama")
    st.set_defaults(func=cmd_selftest)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
