# `eventstream/` — Event stream (Kafka) topic tasarımı + replay politikası (WBS 1.1.8)

SAD §12.1 "Event stream" yeteneğinin (ADR-007) fiziksel sözleşmesi: topic tasarımı, envelope,
dayanıklılık/teslimat semantiği ve **replay politikası**. `db/`+`cache/`+`objstore/` disipliniyle aynı:
**araç-nötr** (ADR-002), **credential-free**, statik probe + opsiyonel canlı kapı.

> **Kaynak doğruluk:** `topic-spec.json` (makine-okunur). Çelişkide o, üstünde ADR-007/SAD/BRD esastır.

## Dosyalar

| Dosya | İçerik |
|-------|--------|
| `topic-spec.json` | **Kaynak doğruluk:** 13 topic + envelope sözleşmesi + cluster_defaults + global_replay_policy (P1–P8) + 12 consumer group + invariant I1–I15 |
| `eventstream-topics.md` | Tasarım: mimari konum, topic ilkeleri, PII tiering, replay politikası, izolasyon, izlenebilirlik |
| `eventstream_probe.py` | stdlib-only kapı: `validate` / `replay` (deterministik replay sim.) / `route` (partition sim.) / `selftest` / `schema` |
| `schemas/event-envelope.schema.json` | Ortak envelope JSON Schema (API §10.1 webhook envelope'unun üst kümesi) |
| `config/topics.declarative.json` | Sağlayıcı-nötr declarative topic provisioning manifesti (spec türevi, I15) |
| `config/acl.template.json` | Least-privilege ACL şablonu (`${ENV}` principal; ham PII'ye tek consumer) |
| `config/cluster-defaults.properties` | Broker/producer/consumer dayanıklılık varsayılanları (RF=3/isr=2/acks=all/idempotent) |
| `config/schema-registry.config.json` | Şema uyumluluk politikası (BACKWARD/FULL; kırıcı değişim → yeni `.vN`) |
| `tests/envelope_behavior_test.py` | Envelope zorunlu-alan + pii_class tutarlılık + webhook indirgemesi kapısı (T1–T4) |
| `run_live_test.sh` | Statik kapı + (Kafka CLI + `${KAFKA_BOOTSTRAP_SERVERS}` varsa) canlı topic uygula/doğrula; yoksa SKIP |

## Çalıştırma

```bash
python3 eventstream/eventstream_probe.py validate    # 236/236 PASS (çıkış 0)
python3 eventstream/eventstream_probe.py selftest    # 18/18 PASS
python3 eventstream/eventstream_probe.py replay      # 9/9 PASS (P1–P8)
python3 eventstream/eventstream_probe.py route       # partition routing
python3 eventstream/tests/envelope_behavior_test.py  # 6/6 PASS
bash    eventstream/run_live_test.sh                  # canlı (varsa) / SKIP
```

## Özet kararlar

- **13 topic**, domain-odaklı, `<domain>.<subject>.v<major>`; anahtar `call_id`/`tenant_id` (tenant-türetilebilir).
- **Dayanıklılık:** RF=3 + `min.insync.replicas=2` + `acks=all` + idempotent producer + unclean-leader kapalı.
- **Teslimat:** at-least-once + idempotent tüketici (envelope.id) → exactly-once *etki* uygulama katmanında.
- **PII tiering:** `transcript.raw` (24s, kısıtlı) → redaction → `transcript.redacted` (30g); ham PII webhook'a sızmaz.
- **no-loss:** `billing.usage` / `governance.audit` (retention ≥30g, idempotent agregasyon).
- **Replay:** ayrı geçici grup (canlı offset dokunulmaz) + retention-sınırlı pencere + tiered rehydrate +
  PII gate (audit) + DLQ manuel replay.
- **İzolasyon:** per-region cluster (residency) + ACL (least-privilege) + envelope tenant_id + downstream RLS.

**Sır/credential repoya yazılmadı** — bootstrap/SASL/TLS yalnız `${ENV}`. Vendor-neutral (ADR-002).
