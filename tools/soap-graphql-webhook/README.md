# tools/soap-graphql-webhook — WBS 7.2.2 SOAP/GraphQL/webhook connector'lar

Integration Gateway'in (SAD §11.2) **SOAP / GraphQL / webhook dilimleri** (FR-TOOL-001). 7.2.1
(rest-connector) AYNI transport SPI seam'inin (`upstream_call(req)→AttemptOutcome`) REST gerçeklemesini
yaptı ve SOAP/GraphQL/webhook'u bu modüle bıraktı (*"AYNI SPI, farklı protokol mapper"*). Üç protokol
de bildirimsel bir `ConnectorSpec` + `Invocation` alır, kanonik istek kurar, vendor-neutral wire SPI
üzerinden yürütür ve yanıtı **7.1.4'ün tükettiği `AttemptOutcome`**'a eşler. **Retry/breaker orkestre
etmez** (o 7.1.4).

**Ek değer (C13 — protokol-farkında fault tespiti):** transport HTTP status tek başına yanıltıcı olabilir:
- **SOAP** — HTTP 500 naif olarak `UPSTREAM_5XX` (retryable) görünür; ama `<soap:Fault>` rolü **Sender**
  ise istemci hatasıdır → **TERMINAL** (retry futile); **Receiver** ise → retryable. Rol status'u ezer.
- **GraphQL** — HTTP 200 naif olarak ok görünür; ama gövdedeki `errors[]` → **FAULT**
  (`extensions.code` → fault_class).
- **Webhook** — HMAC imza **zorunlu** (imzasız teslimat reddedilir); status REST-benzeri eşlenir.

## Dosyalar
- `soap-graphql-webhook-spec.json` — makine-okunur **kaynak doğruluk** (SPI, status→fault + protocol_override, C1–C13, audit).
- `soap-graphql-webhook.md` — tasarım dokümanı.
- `protocol_connector_probe.py` — stdlib-only probe: `validate` / `call <sample>` / `selftest` / `schema`.
- `config/connector-profiles.json` — connector spec preset'leri (soap/graphql/webhook; auth+signing yalnız `${ENV}`).
- `samples/*.json` — sentetik senaryolar (FR-TST-008).
- `tests/protocol_connector_behavior_test.py` — kara-kutu davranış testi.
- `run_live_test.sh` — tüm kapılar + canlı transport notu (`${SGW_CONNECTOR_ENDPOINT}`).

## Çalıştırma
```bash
python3 protocol_connector_probe.py validate      # statik kapı → çıkış kodu
python3 protocol_connector_probe.py selftest       # gömülü davranış (43 kontrol)
python3 protocol_connector_probe.py call samples/soap-sender-fault.json
python3 tests/protocol_connector_behavior_test.py  # davranış (38 kontrol)
./run_live_test.sh                                 # hepsi + canlı not
```

## İnvariant (SR-TOOL-001)
**"Her connector tipi başarılı çağrı yapar"** + status→fault eşleme 7.1.4 taksonomisiyle hizalı
(2xx→ok · 408/429/5xx→retryable · 401/403/404/422/4xx→terminal) + protokol-farkında fault tespiti (C13).
C5 (sır+imza referansla) · C6 (audit no-log) · C7 (connection pooling FR-RES-006) · C10 (enjeksiyon reddi:
header CRLF + SOAP XML-escape + GraphQL parametreli variables) · C11 (kanonik endpoint).

## Vendor-neutrallik & güvenlik
Wire bir SPI noktası (ADR-001/002); referans deterministik `wire_script`, canlıda gerçek protokol client +
keep-alive pool AYNI imza arkasına. **Sır/credential/imza-anahtarı ve gerçek PII repoya yazılmaz**
(auth.ref/signing.ref yalnız `${ENV}`; host'lar `example.com`). Kapsam dışı: timeout/retry/breaker→7.1.4,
allowlist→7.2.3, REST→7.2.1, schema→7.1.1, authz→7.1.2, idempotency üretimi→7.1.3, müşteri hata metni→7.1.5,
audit zenginleştirme→7.1.6, async→7.2.4.
