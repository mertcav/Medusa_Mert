# WBS 12.1.2 — Permission-key kataloğu (`kaynak:eylem`, `*:own`)

**Faz:** F1 · **Öncelik:** Must · **İz:** SAD §14.4.3 · BRD §17.6/§17.7 → FR-IAM-001 / FR-IAM-011 / FR-IAM-008

permission-key **gramerinin** + **tam kataloğunun** makine-okunur, değişmez (frozen) kaynak doğruluğu +
deterministik, fail-closed key **çözüm motoru**. Bir permission-key string'ini (ör. bir endpoint'in
`x-required-permission` değerini) alır → gramer ayrıştırır → kataloğa çözer → terminal **`VALID | REJECT |
UNKNOWN`** kararı döner.

## Gramer
`kaynak:eylem` (≥2 segment, her segment `[a-z][a-z0-9_]*`); `:own` son eki **yalnız** final segment +
**yalnız** `own_eligible_resources` ({calls, transcript, livecalls}) + `action=read` üzerinde geçerlidir
(BRD §17.7 `human_agent` kuralı). Eylem (action) = `:own` yoksa son segment, varsa sondan ikinci segment.

## Karar motoru
```
key ─grammar─► own_place ─► own_scope ─► resolve ─► {VALID | REJECT | UNKNOWN}
  ├─ 'kaynak:eylem' değil ───────────────────────► REJECT malformed_key
  ├─ ':own' final segment değil ─────────────────► REJECT own_misplaced
  ├─ ':own' var, resource ∉ own_eligible|≠read ──► REJECT own_not_permitted
  ├─ katalogda yok ──────────────────────────────► UNKNOWN unknown_key
  └─ katalogda ──────────────────────────────────► VALID resolved (+layer/panel/tier/content/own)
```

## Çalıştırma
```bash
python3 permission_catalog_probe.py validate     # statik katalog + cross-doc conformance → çıkış kodu
python3 permission_catalog_probe.py check samples # key çözüm motoru senaryoları
python3 permission_catalog_probe.py selftest      # G1–G12 gömülü davranış
python3 permission_catalog_probe.py schema        # karar sözleşmesi
./run_live_test.sh                                # hepsi + bağımsız davranış testi
```

## Kapılar (validate)
- **G2** gramer conformance — her katalog key'i `kaynak:eylem` + action ∈ vocab
- **G3** katalog tamlığı (cross-doc 12.1.1) — RBAC modeli universe + tüm rol bundle key'leri ⊆ katalog
- **G4** orphan yok — her katalog key'i ≥1 katman evreninde
- **G5** `:own` disiplini (BRD §17.7)
- **G6** tier/content tutarlılık (FR-IAM-008; L0 key'i asla content)
- **G7** layer↔panel tutarlılık (universe layer ile)
- **G8** `x-required-permission` conformance (API.md §13 — gerçek dokümandan ayrıştırılır)
- **G10** katalog bütünlük manifesti (`catalog_hash` sha256)

## Dosyalar
```
config/permission-catalog.json     # FROZEN KATALOG: 44 key × metadata (kaynak doğruluk)
permission-catalog-spec.json       # spec: gramer, karar, invariant G1–G12, kapılar
permission_catalog_probe.py        # stdlib-only motor: validate / check / selftest / schema
samples/*.json                     # 19 pass + degrade senaryo (FR-TST-008)
tests/permission_catalog_behavior_test.py
run_live_test.sh
```

## Kapsam ayrımı
rol→bundle (immutable model) → **12.1.1** (bu kataloğu tüketir) · scoped assignment → **12.1.3** ·
backend guard / `x-required-permission` HTTP enforcement → **12.2.x** · break-glass → **12.3.x** ·
WORM audit → **12.1.8** · custom roller → Faz 3. Sır/credential ve ham içerik (PII) repoya yazılmaz.
