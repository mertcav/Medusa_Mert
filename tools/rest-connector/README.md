# tools/rest-connector — WBS 7.2.1 REST connector

Integration Gateway'in (SAD §11.2) **REST/HTTP dilimi** (FR-TOOL-001). Tool Yürütme Hattının (SAD §11.1)
adım [5] dayanıklılık motorunun (7.1.4) **SARDIĞI** gerçek upstream transport'un REST gerçeklemesi:
bildirimsel bir `RestConnectorSpec` + `RestInvocation` alır, kanonik HTTP isteği kurar, vendor-neutral wire
SPI üzerinden yürütür ve yanıtı **7.1.4'ün tükettiği `AttemptOutcome`**'a eşler (status→fault_class,
method→operation_class). **Retry/breaker orkestre etmez** (o 7.1.4).

## Dosyalar
- `rest-connector-spec.json` — makine-okunur **kaynak doğruluk** (SPI, status→fault eşleme, C1–C12 invariant, audit).
- `rest-connector.md` — tasarım dokümanı.
- `rest_connector_probe.py` — stdlib-only probe: `validate` / `call <sample>` / `selftest` / `schema`.
- `config/rest-connector-profiles.json` — connector spec preset'leri (crm/ticketing/readonly; auth yalnız `${ENV}`).
- `samples/rest-*.json` — sentetik senaryolar (FR-TST-008).
- `tests/rest_connector_behavior_test.py` — kara-kutu davranış testi.
- `run_live_test.sh` — tüm kapılar + canlı transport notu (`${REST_CONNECTOR_ENDPOINT}`).

## Çalıştırma
```bash
python3 rest_connector_probe.py validate     # statik kapı → çıkış kodu
python3 rest_connector_probe.py selftest      # gömülü davranış (37 kontrol)
python3 rest_connector_probe.py call samples/rest-get-ok.json
python3 tests/rest_connector_behavior_test.py # davranış (48 kontrol)
./run_live_test.sh                            # hepsi + canlı not
```

## İnvariant (SR-TOOL-001)
**"REST connector başarılı çağrı yapar"** + status→fault eşleme 7.1.4 taksonomisiyle hizalı:
2xx→ok · 408/429/5xx→retryable · 401/403/404/422/4xx→terminal. C5 (sır referansla) · C6 (audit no-log) ·
C7 (connection pooling FR-RES-006) · C10 (enjeksiyon reddi) · C11 (kanonik endpoint).

## Vendor-neutrallik & güvenlik
Wire bir SPI noktası (ADR-001/002); referans deterministik `wire_script`, canlıda gerçek HTTP client +
keep-alive pool AYNI imza arkasına. **Sır/credential ve gerçek PII repoya yazılmaz** (auth yalnız `${ENV}`;
host'lar `example.com`). Kapsam dışı: timeout/retry/breaker→7.1.4, allowlist→7.2.3, SOAP/GraphQL/webhook→7.2.2,
schema→7.1.1, authz→7.1.2, idempotency üretimi→7.1.3, müşteri hata metni→7.1.5, audit zenginleştirme→7.1.6.
