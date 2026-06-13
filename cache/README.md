# cache/ — Redis keyspace + TTL politikaları (WBS 1.1.5, Faz 1 implementasyon)

Bu dizin, **SAD §12.1** "Cache" deposunun (session memory · semantic cache index · TTS cache
index) fiziksel kurulum sözleşmesidir: keyspace tasarımı, TTL politikaları, eviction/persistence
ve tenant izolasyon invariant'ları. `db/` dizinindeki PostgreSQL disipliniyle birebir aynı desen:
**makine-okunur kaynak doğruluk + referans config + statik probe kapısı + canlı davranış testi**,
credential-free.

> **Source of truth `keyspace-spec.json`** (SAD §12.1/§15.1'den türetilir). Çelişkide SAD/BRD esastır.
> **Vendor-neutral (ADR-002 ruhu):** Redis, SAD §12.1 "Cache" yeteneği için referanstır; aynı
> sözleşme bölgesel eşdeğerle (Valkey/KeyDB/ElastiCache/MemoryDB) karşılanabilir.
> **Sır/credential repoya YAZILMAZ** — parola yalnız `${ENV}`/aclfile, TLS sertifikaları deployment'tan.

## Yapı

```
cache/
  keyspace-spec.json              # makine-okunur kaynak doğruluk: 2 pool + 4 keyspace + TTL + invariant I1..I9
  config/
    redis-session.conf            # SESSION pool: noeviction, persistence yok, protected-mode
    redis-cache.conf              # CACHE pool: volatile-lru, persistence yok, protected-mode
    users.acl.example             # ACL şablonu (parola ${ENV}; default user kapalı; en-az-yetki SEC-15)
  redis_probe.py                  # stdlib-only statik kapı (validate/selftest/schema)
  tests/
    cache_behavior_test.py        # minimal RESP istemcisi ile canlı davranış kapısı (stdlib-only)
  run_live_test.sh                # redis-server varsa 2 örnek başlatır+test+teardown; yoksa SKIP
```

## İki pool, neden ayrı?

`session` ve `cache` pool'ları **çelişen eviction politikaları** taşıdığı için ayrılır:

| | **session** (oturum belleği) | **cache** (semantic + TTS index) |
|---|---|---|
| maxmemory-policy | `noeviction` | `volatile-lru` |
| Eviction | **YOK** — aktif çağrı mid-call düşürülemez | TTL'li anahtar baskı altında düşürülür |
| Doluyken yazım | **OOM ile reddedilir** (sessiz kayıp yok) → graceful shed | en az kullanılan TTL'li anahtar evict |
| PII | taşıyabilir (ephemeral) | **taşımaz** (TM-I-09/SEC-15) |
| Persistence | yok (`save ""` + `appendonly no`) | yok |
| Kapasite yönetimi | admission control / backpressure (FR-RES-014) | eviction |

Cache miss yalnız maliyet/gecikme artışıdır (doğruluk kaybı değil) → düşürülebilir. Oturum
durumunun kaybı = çağrı başarısızlığı → asla sessizce düşürülmez.

## Keyspace + TTL özeti (keyspace-spec.json)

| Keyspace | Anahtar deseni | TTL (varsayılan) | Pool | PII | İz |
|----------|----------------|------------------|------|-----|----|
| `session_state` | `{t:<tenant_id>}:sess:<call_id>:state` | idle 1800s, hard cap 14400s (sliding) | session | evet | FR-RES-016/010 |
| `session_summary` | `{t:<tenant_id>}:sess:<call_id>:summary` | idle 1800s, hard cap 14400s | session | evet | FR-RES-010 |
| `semantic_cache` | `{t:<tenant_id>}:sem:<agent_id>:<hash>` | 86400s (24h) | cache | hayır | FR-RES-004, FR-LLM-014 |
| `tts_cache_index` | `{t:<tenant_id>}:tts:<voice_profile_id>:<hash>` | 2592000s (30g) | cache | hayır | FR-RES-003, FR-TTS-010 |

TTL'ler **mühendislik varsayılanıdır**; compliance profile (`cp.retention.*`) ile **yalnız
sıkılaştırılabilir** (DPIA most-restrictive-wins).

## İnvariant'lar (probe zorlar — I1..I9)

- **I1** Her anahtar tenant hash-tag `{t:<tenant_id>}` ile başlar (cross-tenant namespace izolasyonu; SEC-15, TM-I-01/09). Cluster'da hash-tag tenant anahtarlarını aynı slota toplar.
- **I2/I3** Her keyspace TTL'li; `0 < ttl_seconds <= max_ttl_seconds`, sonlu (kalıcı/-1 anahtar yok).
- **I4** PII yalnız `session` pool'da; `cache` pool `pii=false` (PII cache'lenmez — TM-I-09).
- **I5** `session`: noeviction + must_not_evict + delete_on_call_end; `cache`: volatile-lru + evictable.
- **I6** Serbest-metin bileşeni hash'li (ham PII/metin anahtara yazılmaz).
- **I7** Tüm keyspace residency = home-region (NFR 10.7).
- **I8/I9** Pool config mevcut + maxmemory-policy spec ile tutarlı; persistence kapalı; protected-mode; literal sır yok.

## Kapılar

```bash
# Statik kapı (sunucu gerekmez) — spec + config invariant doğrulaması
python3 cache/redis_probe.py validate     # 52/52 kontrol, çıkış 0
python3 cache/redis_probe.py selftest      # 23/23 predikat, çıkış 0
python3 cache/redis_probe.py schema        # beklenen pool/keyspace/invariant özeti (JSON)

# Canlı kapı (CI / redis-server) — gerçek TTL/eviction/izolasyon davranışı
bash cache/run_live_test.sh                # 2 örnek başlatır + 13 assertion; redis yoksa SKIP
```

`cache_behavior_test.py` (canlı) doğrular: pool politikalarının runtime'a yüklenmesi; her
anahtarın TTL'li yazılması + kalıcı anahtar olmaması; tenant namespace izolasyonu (SCAN sızıntısı
yok); `delete_on_call_end`; TTL expiry'nin gerçekten silmesi; **cache pool'un baskı altında evict
etmesi** vs **session pool'un noeviction ile yazımı OOM ile reddetmesi** (sessiz kayıp yok).

## Sonraki adımlar / bağlanacak dilimler

- **WBS 1.2.2** Residency zorlama — Redis bölgesel deployment + home-region eşlemesi (NFR 10.7).
- **WBS 0.4.5** Secrets (Vault/KMS) — `users.acl.example` parolaları + TLS sertifikaları enjekte edilir.
- **WBS 1.1.7** Vector store — semantic cache embedding hash'i RAG retrieval ile hizalanır.
- **WBS 0.4.7** Gözlemlenebilirlik — cache hit oranı (TTS ≥%80, semantic) + session bellek bütçesi metrikleri (BRD §15).
- **Faz 1 runtime (0.3.5 sonrası)** — orchestrator bu keyspace sözleşmesini gerçek istemciyle uygular; TTL/namespace burada sabit.
