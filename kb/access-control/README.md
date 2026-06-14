# kb/access-control — WBS 6.1.4 Doküman bazında erişim yetkisi (FR-KB-005)

Bilgi Tabanı & RAG **retrieval** sınırındaki (SAD §10.2) **erişim ENFORCEMENT** kapısı. 6.1.3'ün her chunk'a
taşıdığı erişim metadata'sını (`classification`/`acl_ref`/`sensitive`/`redaction_state`) **tüketir** ve bir
retrieval isteğinin principal bağlamına göre hangi chunk'ın **dönebileceğine** karar verir. **DENY-BY-DEFAULT /
fail-closed.** SR-KB-005/TC-KB-005 başlık kanıtı: *"Yetkisiz dokümandan retrieval sonucu dönmez."*

## Dosyalar
- `access-control-spec.json` — **kaynak doğruluk** (principal/ACL/karar sözleşmesi, G1–G10, taksonomi, iz).
- `access-control.md` — tasarım (algoritma, iki uygulama noktası, kapılar, kapsam sınırı).
- `access_control_probe.py` — stdlib-only referans probe: `validate` / `enforce <sample>` / `selftest` / `schema`.
- `config/access-control-profiles.json` — karar profilleri (pilot/regulated-tr/enterprise-eu + degraded negatif).
- `samples/*.json` — senaryolar (happy-multi-principal / tenant-isolation / classification-redaction /
  active-version / degraded-open negatif). Sentetik (FR-TST-008).
- `tests/access_control_behavior_test.py` — bağımsız davranış testleri (T1–T12, regresyon kapısı).
- `run_live_test.sh` — statik + sample kapısı (credential-free); canlı store yalnız `${KB_VECTOR_DSN}` varsa not.

## Çalıştırma
```bash
python3 access_control_probe.py validate          # statik spec/config/şema kapısı
python3 access_control_probe.py enforce samples/access-happy-multi-principal.json
python3 access_control_probe.py selftest          # gömülü davranış kontrolleri
python3 access_control_probe.py schema            # sözleşmeleri yazdır
./run_live_test.sh                                # hepsi + (varsa) canlı not
```

## İlkeler
- **Vendor-neutral (ADR-001/002):** karar policy + doküman metadata'sına dayanır, sağlayıcıya değil.
- **Defense-in-depth:** (1) store pre-filtre yüklemi (6.2.1'e push); (2) authoritative post-filtre (her chunk
  yeniden karar). Pre-filtre post-filtreye göre **sound+complete** (G8).
- **6.1.3'ü tüketir:** `index_pipeline_probe` import edilir (o da `ingest_connector_probe`'u) — kod tekrarı yok.
- **Determinizm:** sanal saat + tohumlu (Date.now/rastgele yok). **Sır/credential ve gerçek PII repoya yazılmaz.**

## Kapsam dışı
chunk/embed/version → 6.1.3 · namespace yazım izolasyonu → 6.1.3 C5/1.1.7 RLS · retrieval/rerank/top-k →
6.2.1 · token-trim → 6.2.2 · retrieval no-log → 6.2.4 · panel/break-glass content erişimi (Tier A/B, L0
altın kural) → FR-IAM-008/009/010 (AYRI yüzey).
