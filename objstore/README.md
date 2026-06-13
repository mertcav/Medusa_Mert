# objstore/ — Nesne depolama (S3-uyumlu) tenant bucket/prefix + KMS + lifecycle (WBS 1.1.6, Faz 1)

Bu dizin, **SAD §12.1** "Nesne depolama (S3 uyumlu), tenant-bazlı bucket/prefix + KMS" satırının
fiziksel kurulum sözleşmesidir: bucket/prefix stratejisi, at-rest SSE-KMS, lifecycle/retention,
object-lock/legal-hold ve tenant izolasyon invariant'ları. `db/` (PostgreSQL) ve `cache/` (Redis)
disipliniyle birebir aynı desen: **makine-okunur kaynak doğruluk + referans politika şablonları +
statik probe kapısı + (deterministik) davranış simülatörü + canlı davranış testi**, credential-free.

> **Source of truth `storage-spec.json`** (SAD §12.1/§12.3 + DB.md §8/§9'dan türetilir). Çelişkide SAD/DB.md esastır.
> **Vendor-neutral (ADR-002):** S3 API referans yüzeydir; aynı sözleşme bölgesel S3-uyumlu eşdeğerle
> (AWS S3, MinIO, GCS-S3, Azure Blob-S3, Ceph RGW) karşılanabilir. Politika şablonları AWS gramerindedir.
> **Sır/credential repoya YAZILMAZ** — endpoint/anahtar/KMS ARN yalnız `${ENV}`/`${PLACEHOLDER}`.

## Yapı

```
objstore/
  storage-spec.json                       # makine-okunur kaynak doğruluk: bucket stratejisi + 5 data_class + KMS + lifecycle + O1..O11
  policy/
    bucket-policy.template.json           # TLS-only + SSE-KMS zorlama + cross-tenant reddi + object-lock bypass reddi
    public-access-block.json              # O4: dört public-access bayrağı da kapalı
    lifecycle.template.json               # data_class başına transition/expiration kuralı
    iam-tenant-prefix-policy.template.json # tenant runtime yalnız kendi bucket'ı + yalnız tenant CMK
    object-lock-config.template.json      # content bucket WORM (governance) varsayılan retention
  objstore_probe.py                       # stdlib-only kapı (validate/decide/lifecycle/selftest/schema)
  tests/
    objstore_behavior_test.py             # canlı S3-uyumlu davranış kapısı (aws CLI; endpoint yoksa SKIP)
  run_live_test.sh                        # yerel MinIO+aws varsa ayağa kaldırır+test+teardown; yoksa SKIP
```

## Bucket stratejisi — neden per-tenant-per-region?

Her tenant + home-region için **ayrı bucket** (prefix-yalnız değil). Gerekçe:

| | **per-tenant-per-region** (seçilen) | shared bucket + tenant prefix (reddedilen) |
|---|---|---|
| At-rest şifreleme | tenant başına ayrı **KMS CMK** (NFR 10.6) | tek paylaşılan key |
| Geri döndürülemez silme | tenant CMK sürüm imhası = **tenant-geneli crypto-shred** (FR-REC-010) | tenant başına shred mümkün değil |
| Lifecycle / object-lock / residency | tenant başına bağımsız | paylaşılır |
| İzolasyon | bucket-policy + IAM ile yapısal (FR-TEN-002) | yalnız prefix ACL |

Bucket içinde anahtar düzeni: `<data_class>/<YYYY>/<MM>/<DD>/<object_id>` — `object_id` UUIDv7
(DB `recording.id`/`transcript.id` ile hizalı); anahtar **ham PII taşımaz** (P6). DB yalnız
`storage_uri` + metadata + `redaction_state` tutar (DB.md §8).

## data_class + lifecycle özeti (storage-spec.json)

| data_class | prefix | PII | versioning | object-lock | transition | expire | İz |
|------------|--------|-----|-----------|-------------|-----------|--------|----|
| `recording` | `recording/` | evet | açık | governance | 30g→IA | 365g | FR-REC-001/006/007/010 |
| `transcript` | `transcript/` | evet | açık | governance | 30g→IA | 365g | FR-REC-004/005/006/010 |
| `kb_document` | `kb/` | hayır | açık | yok | 90g→IA | yok | FR-KB-003/010 |
| `tts_cache` | `tts-cache/` | hayır | kapalı | yok | — | 30g | FR-RES-003, FR-TTS-010 |
| `export` | `export/` | evet | kapalı | yok | — | 7g | FR-TEN-002, FR-REC-010 |

`tts_cache` 30g expire'ı **WBS 1.1.5** `tts_cache_index` Redis TTL'i (2592000s) ile hizalıdır. Gün
değerleri **mühendislik varsayılanı**; compliance profile (`cp.retention.*`) + `retention_policy` ile
**yalnız sıkılaştırılır** (DPIA most-restrictive-wins). Retention süreleri BRD §22 açık kararıdır.

## İnvariant'lar (probe zorlar — O1..O11)

- **O1** Her bucket tam bir tenant + bir home-region'a bağlı; residency home-region (NFR 10.7).
- **O2** At-rest SSE-KMS + tenant başına CMK; şifresiz/yanlış-key Put reddedilir (NFR 10.6).
- **O3** TLS-only (`aws:SecureTransport=false` reddi; SAD §14.2).
- **O4** Public access tamamen kapalı (dört bayrak da true).
- **O5** Tenant IAM yalnız kendi bucket'ı; platform realm content'i break-glass'sız okuyamaz (altın kural FR-IAM-008).
- **O6** Anahtar tanınan data_class prefix'i ile başlar; ham PII taşımaz (P6).
- **O7** Her data_class lifecycle kuralı taşır; content expiration retention ile hizalı; legal-hold expiration'ı geçersiz kılar (FR-REC-006/007/010).
- **O8** PII/content sınıfları platform realm'e deny-by-default; DB pointer redaction_state.
- **O9** Geri döndürülemez silme = lifecycle expiration + tenant CMK crypto-shredding (FR-REC-010).
- **O10** legal-hold sınıfları versioning + object-lock (governance) WORM; legal-hold ayrı bayrak (FR-REC-007).
- **O11** Repoda literal sır yok — yalnız `${ENV}`/`${PLACEHOLDER}`.

## Kapılar

```bash
# Statik + deterministik davranış kapısı (sunucu gerekmez)
python3 objstore/objstore_probe.py validate    # 63/63 kontrol, çıkış 0
python3 objstore/objstore_probe.py selftest      # 29/29 predikat (access-decision + lifecycle dahil), çıkış 0
python3 objstore/objstore_probe.py schema        # beklenen bucket/data_class/invariant özeti (JSON)

# Tek karar / lifecycle örnekleri
python3 objstore/objstore_probe.py decide --json '{"realm":"platform","bucket_tenant":"T1","action":"Get","tls":true,"key":"transcript/2026/06/13/o","data_class":"transcript"}'
python3 objstore/objstore_probe.py lifecycle --json '{"data_class":"recording","age_days":400,"legal_hold":true}'

# Canlı kapı (CI / S3-uyumlu endpoint) — gerçek policy/lifecycle/object-lock davranışı
bash objstore/run_live_test.sh                  # yerel MinIO+aws ile ayağa kaldırır; yoksa SKIP
```

**Davranış kapısı iki katman:** (1) `objstore_probe.py` içindeki **deterministik simülatör**
(access-decision: bucket-policy + IAM + altın kural mantığı; lifecycle: yaş+legal-hold → eylem) bu
ortamda **çalışır** ve S3 politika semantiğini test eder. (2) `run_live_test.sh` + `objstore_behavior_test.py`
gerçek S3-uyumlu endpoint'te aynı politikaları uygular (MinIO/aws yoksa SKIP).

## Sonraki adımlar / bağlanacak dilimler

- **WBS 1.2.2** Residency zorlama — bucket bölgesel deployment + home-region eşlemesi (NFR 10.7).
- **WBS 1.2.3** Retention motoru — lifecycle expiration + crypto-shred + legal-hold muafiyetini uygular (FR-REC-006/010).
- **WBS 1.2.4** Legal hold — object-lock/legal-hold bayrağını DB `legal_hold` ile bağlar (FR-REC-007).
- **WBS 0.4.5** Secrets/KMS — `${TENANT_KMS_KEY_ARN}`/endpoint/erişim anahtarı enjeksiyonu + BYOK iskeleti.
- **DB.md §5.5/§8** — `recording.storage_uri`/`transcript.storage_uri` bu anahtar düzenine işaret eder.
- **Faz 1 runtime** — orchestrator bu bucket/prefix + SSE-KMS sözleşmesini gerçek S3 istemcisiyle uygular.
