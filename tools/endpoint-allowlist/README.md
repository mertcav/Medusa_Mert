# tools/endpoint-allowlist — WBS 7.2.3 Endpoint allowlist (onaysız endpoint engelleme)

Integration Gateway'in (SAD §11.2) **egress karar gate'i** (FR-TOOL-012: *"Onaylanmamış endpoint'lere
erişim engellenmelidir."*). Tool Yürütme Hattında (SAD §11.1) connector (7.2.1/7.2.2) **kanonik endpoint +
çözülmüş hedef** üretir; bu gate o hedefi tenant-tanımlı **allowlist** ile karşılaştırıp **PERMIT/DENY**
karar verir. **DENY → istek WIRE'a gitmez** (`ENDPOINT_NOT_ALLOWED` terminal; 7.1.4 retry etmez).
[ADR-014](../../docs/adr/0014-zorunlu-egress-kontrol.md) *egress proxy + merkezi allowlist* kararının
uygulama-katmanı karar çekirdeği; SSRF (TM-E-06 / SEC-06) savunması içerir.

## Dosyalar
- `endpoint-allowlist-spec.json` — makine-okunur **kaynak doğruluk** (karar sözleşmesi, SSRF blocklist, A1–A12 invariant, audit).
- `endpoint-allowlist.md` — tasarım dokümanı.
- `endpoint_allowlist_probe.py` — stdlib-only probe: `validate` / `decide <sample>` / `selftest` / `schema`.
- `config/egress-policies.json` — tenant egress policy preset'leri (crm-egress-strict / partner-wildcard / regulated-tight; default-deny).
- `samples/*.json` — sentetik senaryolar (FR-TST-008): permit + her DENY sınıfı + degraded + invalid-policy.
- `tests/endpoint_allowlist_behavior_test.py` — kara-kutu davranış testi.
- `run_live_test.sh` — tüm kapılar + (varsa) canlı egress proxy notu (`${EGRESS_PROXY_ENDPOINT}`).

## Çalıştırma
```bash
python3 endpoint_allowlist_probe.py validate          # statik + sır/PII tarama kapısı → çıkış kodu
python3 endpoint_allowlist_probe.py selftest          # gömülü davranış (29 kontrol)
python3 endpoint_allowlist_probe.py decide samples/deny-ssrf-metadata.json
python3 tests/endpoint_allowlist_behavior_test.py     # davranış (25 kontrol)
./run_live_test.sh                                    # hepsi + canlı not
```

## İnvariant (SR-TOOL-012)
**"Allowlist dışı endpoint çağrısı reddedilir"** — **default-deny** (A1). Üstüne SSRF savunması:
cloud metadata (A2) + özel-ağ/global-olmayan IP (A3) + DNS rebinding (A4) BLOK, allow kuralını **ezer**
(A9 block-overrides-allow). scheme/port allowlist (A5/A6), host etiket-sınırı eşleme (A7; substring yok),
path_prefix segment-sınırı + traversal reddi (A8), determinizm (A10), audit no-log (A11), fail-closed (A12).

## Kapsam dışı
Kanonik endpoint üretimi → 7.2.1/7.2.2 · timeout/retry/breaker → 7.1.4 · ağ-katmanı egress proxy/WAF →
17.1.4 (defense-in-depth) · authz → 7.1.2 (dik boyut) · müşteri hata metni → 7.1.5 · audit zenginleştirme
→ 7.1.6 · allowlist panel CRUD → ileri WBS. Vendor-neutral (ADR-001/002); sır/PII repoya yazılmaz.
