# Vector DB (RAG Vektör Deposu) Değerlendirmesi — pgvector vs OpenSearch

| Alan | Değer |
|------|-------|
| **WBS** | 0.2.5 |
| **Faz · Öncelik** | F0 · Should |
| **İz** | SAD §12.1 (depolama seçimleri), §8.4 (vendor eval tablosu: pgvector / OpenSearch), §10 (RAG mimarisi), §20 (gecikme bütçesi — RAG retrieval kalemi); FR-KB-003/004/005/006/008/009/010/011; FR-TEN-002 (tenant izolasyon); FR-RES-004 (semantic cache embedding); NFR 10.7 (residency); ADR-002 (vendor-neutral) |
| **Durum** | v1.0 — ölçüt + metodoloji + harness hazır; **canlı aday ölçümü 0.3.x/1.1.7 PoC'ta** |
| **Tarih** | 2026-06-13 |

> **Sağlayıcı-nötr (ADR-002):** Bu doküman bir vektör deposu **seçmez**. SAD §8.4 **pgvector** (birincil
> öneri) ve **OpenSearch** (ikincil) adaylarını ölçüt + metodoloji üzerinden ele alır; nihai seçim **0.2.6**
> karar raporunda (gecikme + recall + izolasyon + residency + operasyonel maliyet + risk) bütünsel, uygulama
> ise **1.1.7** (vector store namespace) ile yapılır. SAD §21'deki teknoloji önerileri yalnız mimari öneridir;
> bu eval bağlayıcı değildir. Diğer adaylar (managed bulut vektör DB) de aynı kapılardan geçer.

---

## 1. Kapsam ve amaç
Vektör deposu adaylarını **RAG retrieval** gerçeğine (top-k ANN arama, tenant+agent izolasyonu, metadata
filtre, residency) sadık, **sağlayıcı-nötr** ve **tekrarlanabilir** bir ölçüt setiyle değerlendirmek.
Vektör deposu STT/TTS/LLM gibi **medya hot-path'inde değildir**; **RAG retrieval** adımındadır (SAD §10.2:
`soru → embed → vector search top-k → rerank (ops.) → trim → LLM context`). Yine de retrieval gecikmesi
turn bütçesinin bir kalemidir (SAD §20: "RAG retrieval (gerekirse) ~100–200 ms P95; top-k; **çoğu turda
atlanır**"). Görev başlığındaki karşılaştırma (pgvector vs OpenSearch) ve birincil boyutlar:

- **Retrieval gecikmesi** (top-k ANN, P95) → **SAD §20** "RAG retrieval ~100–200 ms (P95)" kalemine kapı.
  Çoğu turda atlanır; ama RAG gereken turda uçtan uca gecikme bütçesini (NFR 10.1: P95 ≤ 1.200 ms) yer.
- **Recall@k** (retrieval kalitesi) → ANN yaklaşıklığı ilgili dokümanı düşürmemeli; düşük recall →
  agent kaynak bulamaz → **anti-hallucination** zinciri (FR-KB-007) bozulur. Kapı **en-kötü sorgu sınıfı**
  üzerinden (zayıf sınıfı genel ortalama maskelemesin — STT WER / TTS MOS / LLM kalite ile aynı disiplin).
- **Namespace / tenant izolasyonu** (FR-KB-004, FR-TEN-002) → tenant+agent bazında ayrı namespace; sonuçta
  **başka tenant'ın / yetkisiz** dokümanı asla dönmemeli. pgvector için native PostgreSQL **RLS** (DB.md).
- **Metadata filtreli arama / doküman-ACL** (FR-KB-005, FR-KB-006) → vektör arama + metadata filtre (erişim
  yetkisi, versiyon, kaynak) birlikte; filtreli sorguda yetkisiz doküman sızıntısı sıfır.
- **Residency / no-log** (NFR 10.7, FR-KB-010) → veri tenant home-region'da; hassas dokümanlar dış sağlayıcı
  loglarına gitmez.

Destekleyici (soft): **index ops** (artımlı upsert + silme; FR-KB-003/008 versiyon + içerik TTL), **hybrid
search** (vektör + BM25; yapısal alanlar — telefon/poliçe/referans no — için kalite artışı), **operasyonel
tutarlılık / stack-fit** (pgvector PostgreSQL'i yeniden kullanır → RLS/audit/backup/residency/KMS tek yerde).

Kapsam **dışı** (ilgili ama ayrı görevler): STT/TTS/LLM eval (0.2.2/0.2.3/0.2.4); embedding **modeli**
seçimi (LLM/embedding sağlayıcı — 0.2.4 ile bitişik); rerank **uygulaması** (6.2.1); chunk/index hattı
(6.1.3); semantic cache **uygulaması** (5.4 / FR-RES-004 — embedding deposu olarak vektör DB ile bitişik).
Bu görev **ölçüt + metodoloji + ölçüm hattı** üretir; **canlı aday ölçümü** PoC verisi gerektirir ve
**0.3.x / 1.1.7**'de her aday için alınıp matrise işlenir.

## 2. Ölçülen yüzey (VectorDbAdapter / depo sözleşmesi)
Değerlendirme, SAD §8 **VectorDbAdapter** soyutlamasına göre yapılır — depoya özel biçimler adapter arkasında
normalize edilir (vendor-neutral, ADR-002). Bir adayın eval'a girebilmesi için karşılaması gereken yüzey:

```
upsert(namespace, docs[{id, vector, metadata}])          // artımlı ekleme/güncelleme (FR-KB-003)
delete(namespace, ids[] | filter)                        // silme/işaretleme (FR-KB-008, retention)
search(namespace, queryVector, k, filter?) -> hits[{id, score, metadata}]   // top-k ANN + metadata filtre
  namespace = tenant+agent kapsamı (FR-KB-004); cross-namespace sonuç YOK (FR-TEN-002)
  filter    = doküman-ACL / versiyon / kaynak (FR-KB-005/006); yetkisiz doküman dönMEZ
config { region; residency_pinned; no_external_log; rls; hybrid_search; index_type; ... }
```
Namespace/RLS, metadata filtre, residency pinning + dış-log yok yetenekleri **knock-out** ön koşuludur;
karşılamayan aday ilgili ölçütte sıfır alır. Rerank/trim/cache orchestrator tarafındadır (SAD §10); adapter
tek depoyu temsil eder — eval depo motorunun ANN recall'ını, gecikmesini ve izolasyon/filtre doğruluğunu ölçer.

## 3. Değerlendirme ölçütleri ve ağırlıkları
Recall + izolasyon birincil (RAG güveni + tenant izolasyonu); gecikme ikinci; karar için ağırlıklı rubrik:

| # | Ölçüt | Ağırlık | Nasıl ölçülür | İz |
|---|-------|--------:|----------------|-----|
| C1 | **Recall@k** (en-kötü sorgu sınıfı) | 20% | harness `score` (retrieved ∩ relevant) | FR-KB-009, SAD §10.2 |
| C2 | **Retrieval gecikmesi** (top-k, P95) | 18% | harness → SAD §20 RAG kapısı | SAD §20, NFR 10.1 |
| C3 | **Namespace / tenant izolasyonu** (sızıntı=0) | 15% | harness (forbidden leak) + yetenek (knock-out) | FR-KB-004, FR-TEN-002 |
| C4 | **Metadata filtre / doküman-ACL** (yetkisiz sızıntı=0) | 13% | harness (filtreli leak) + yetenek (knock-out) | FR-KB-005, FR-KB-006 |
| C5 | **Residency / no-log** | 12% | config inceleme (knock-out) | NFR 10.7, FR-KB-010 |
| C6 | **Index ops** (artımlı upsert + silme/versiyon) | 8% | yetenek (soft) | FR-KB-003, FR-KB-008 |
| C7 | **Hybrid search** (vektör + BM25) | 8% | yetenek (soft) | FR-STT-005 (yapısal alan), FR-KB-009 |
| C8 | **Operasyonel tutarlılık / stack-fit** | 6% | yetenek + taksonomi (soft) | SAD §12.1, §13 |

> C1–C2 harness ile **sayısal** ölçülür; C3/C4 yetenek + **empirik sızıntı** (sonuçta yasak doküman); C5
> config uygunluk; C6–C8 yetenek/soft. **Knock-out kapıları:** C1 (recall en-kötü-sınıf), C2 (retrieval
> P95), C3 (izolasyon sızıntı=0), C4 (filtre sızıntı=0), C5 (residency + no-log) — herhangi biri **KIRMIZI/
> fail** ise aday elenir. C6/C7/C8 **soft** (rapora yazılır; 0.2.6'da bütünsel). Operasyonel maliyet/sözleşme
> ağırlığı **0.2.6**'da.

## 4. Metrik tanımları
- **Recall@k** = `|retrieved_ids ∩ relevant_ids| / |relevant_ids|`. `relevant_ids` = **exact-kNN
  ground-truth** (referans, brute-force kosinüs); `retrieved_ids` = ANN'in **dönen** top-k'si. ANN'in ilgili
  dokümanı kaçırma oranını ölçer. Kapı **en-kötü sorgu sınıfı** (factual / semantic / structured) üzerinden;
  yapısal sorgular (telefon/poliçe/ref no) genelde en zorudur — onları genel ortalama maskelememeli.
- **Retrieval gecikmesi** = top-k arama süresi (embed hariç; embed LLM/embedding adapter kalemidir). P50/
  P95/P99 + sorgu sınıfı kırılımı. SAD §20 RAG kalemi: P95 ≤ 200 ms (yeşil ≤ 100). Aynı-bölge co-located
  depo (pgvector PostgreSQL) ağ atlamasını kaldırır → düşük gecikme; ayrı küme (OpenSearch) bir hop ekler.
- **Namespace / tenant izolasyonu** = (yetenek: tenant+agent namespace **veya** RLS) **ve** (empirik:
  sonuçta `forbidden_ids` ∩ `retrieved_ids` = **0**). `forbidden_ids` = başka tenant'ın veya yetkisiz
  dokümanları; biri sonuçta dönerse **tenant izolasyon ihlali** (FR-TEN-002). pgvector RLS satır düzeyinde,
  DB.md politikalarıyla; index-per-tenant (OpenSearch) namespace düzeyinde.
- **Metadata filtre / doküman-ACL** = (yetenek: metadata filtreli arama) **ve** (filtre uygulanan sorgularda
  yetkisiz sızıntı = 0). Doküman bazında erişim yetkisi (FR-KB-005) + kaynak atfı (FR-KB-006) filtre/metadata
  ile zorlanır; filtre recall'ı bozmadan uygulanmalı (pre/post-filter doğruluğu).
- **Residency / no-log** = `residency_pinned=true` **ve** pin'lenen `region` sunulanlar arasında **ve**
  `no_external_log=true`. Veri home-region'da işlenir (NFR 10.7); hassas içerik dış sağlayıcı loglarında
  kalmaz (FR-KB-010). pgvector için native (aynı Postgres bölgesi + KMS); managed dış DB için sözleşmesel.
- **Index ops** = artımlı upsert (FR-KB-003 chunk/index/versiyon) + silme/işaretleme (FR-KB-008 içerik TTL +
  retention/legal-hold). **Hybrid search** = vektör + anahtar-kelime (BM25); yapısal alan retrieval'ı
  güçlendirir. **Operasyonel stack-fit** = depo PostgreSQL/mevcut yığını ne kadar yeniden kullanıyor
  (RLS/audit/backup/residency/KMS/transactional metadata) — daha az hareketli parça = daha düşük operasyon riski.

## 5. Kabul kapıları (gate) — mühendislik varsayılanı
| Ölçüt | Kapı (pass) | Yeşil bant |
|-------|-------------|------------|
| C1 recall@k (en-kötü sorgu sınıfı) | **≥ 0.95** | ≥ 0.98 |
| C2 retrieval P95 | **≤ 200 ms** (SAD §20 üst) | ≤ 100 ms |
| C3 namespace / tenant izolasyon | **sızıntı = 0** (+ namespace/RLS yetenek) | — |
| C4 metadata filtre / doküman-ACL | **yetkisiz sızıntı = 0** (+ filtre yetenek) | — |
| C5 residency / no-log | **uygun** (pinning + bölge + no_external_log) | — |

> Eşikler **mühendislik varsayılanı**; gerçek değerler **0.3.x / 1.1.7 PoC**'ta gerçek embedding + KB Q&A
> benchmark seti (FR-KB-009) ile, tenant+agent namespace altında doğrulanır. `score` kapısı geçilmezse çıkış
> kodu `1` → CI/0.4.4 hattında gate (model/index/embedding değişiminde recall regresyonunu yakalar).

## 6. Ölçüm metodolojisi (harness)
`vector_db_eval_probe.py` (stdlib-only) üç mod sunar:

| Mod | İş |
|-----|----|
| `score` | Bir aday **sorgu test setini** (retrieval gecikme + recall + izolasyon sızıntı + filtre + residency) puanlar: gecikme P50/P95/P99 (genel + sınıf), recall@k en-kötü-sınıf, cross-tenant/yetkisiz sızıntı, residency uygunluk + kapı → çıkış kodu |
| `compare` | Çok adaylı `score` çıktısını markdown karşılaştırma matrisine indirir |
| `selftest` | Credential'sız çekirdek doğrulama (recall@k / leak / residency / percentile / kapı birim kontrolleri) |

**Örnek (sample) şeması:** her aday için bir JSON — `config` (`engine`, `index_type`, `supports_namespace`,
`rls`, `metadata_filter`, `hybrid_search`, `incremental_upsert`, `delete_support`, `residency_pinned`,
`region`, `available_regions`, `no_external_log`, `operational_stackfit`) + `queries[]` (her biri:
`query_class ∈ {factual,semantic,structured}`, `tenant`, `namespace`, `k`, `latency_ms`, `retrieved_ids`,
`relevant_ids`, `forbidden_ids`, `filter_applied`). Detaylı şema `vector_db_eval_probe.py` başlığında.

**Canlı PoC akışı (1.1.7 / 0.3.x):** Adapter, sentetik KB + sorgu setini (FR-TST-002/008 — gerçek müşteri
verisi yok) tenant+agent namespace'e indeksler; her sorgu için `relevant_ids` brute-force exact-kNN ile
(ground-truth) hesaplanır, ANN `retrieved_ids` + `latency_ms` ölçülür; cross-tenant/yetkisiz doküman
`forbidden_ids`'e konur (izolasyon + ACL leak testi); `score` çalıştırılır. Managed dış DB credential'ı
**ortam değişkeni** ile geçilir, **dosyaya yazılmaz**.

## 7. Karşılaştırma matrisi (İLLÜSTRATİF profillerle)
Aşağıdaki tablo `samples/` altındaki **illüstratif** aday profillerinden harness ile üretilmiştir.
**Bunlar gerçek benchmark değildir**; metodolojiyi ve kapıları göstermek içindir. Gerçek değerler 0.3.x/1.1.7
canlı PoC'ta her aday için ölçülüp buraya işlenecektir.

| Aday | Motor | Retrieval P95 (ms) | Recall (en-kötü sınıf) | İzolasyon (sızıntı) | Filtre/ACL | Residency | Hybrid | Karar |
|---|---|---|---|---|---|---|---|---|
| vdb-pgvector | pgvector | 59.55 | 0.9667 | evet (yok) | evet | evet | hayır | 🟡 SARI |
| vdb-opensearch | opensearch | 119.8 | 0.9667 | evet (yok) | evet | evet | evet | 🟡 SARI |
| vdb-managed-degraded | managed-cloud-vdb | 285.6 | 0.35 | HAYIR (1 sızıntı) | HAYIR | HAYIR | hayır | 🔴 KIRMIZI |

> Kapılar: retrieval P95 ≤ 200 ms (SAD §20 RAG kalemi, yeşil ≤ 100); recall@k (en-kötü sınıf) ≥ 0.95
> (yeşil ≥ 0.98); namespace/tenant izolasyon sızıntı = 0 (FR-KB-004/FR-TEN-002); metadata/ACL filtre +
> yetkisiz sızıntı = 0 (FR-KB-005); residency pinning + dış log yok (NFR 10.7/FR-KB-010) zorunlu. Yeniden üret:
> `python3 docs/vendor-eval/vector_db_eval_probe.py score samples/<x>.json --out /tmp/<x>.json` → `compare`.

**Matrisin gösterdiği** (illüstratif): **pgvector** ve **OpenSearch** iki meşru aday — ikisi de tüm knock-out
kapılarını geçer (recall en-kötü-sınıf 0.967 ≥ 0.95 SARI bantta, izolasyon sızıntısı yok, metadata filtre +
residency uygun). Ayrışma **gecikme ve operasyonel** boyutta: **pgvector** aynı Postgres'te co-located → 59 ms
(yeşil bant, ağ atlaması yok) + native RLS + stack-fit yüksek; **OpenSearch** ayrı küme → 120 ms (sarı bant,
bir hop) ama **native hybrid search** + index-per-tenant. **managed-degraded** *her* knock-out kapısında
elenir: yalnız ABD bölgesi (**residency yok → NFR 10.7 ihlali**), **dış log açık** (FR-KB-010 ihlali), **RLS
yok + sonuçta cross-tenant doküman sızıntısı** (FR-TEN-002 ihlali), **filtreli sorguda yetkisiz doküman**
(FR-KB-005 ihlali), **yapısal sorguda recall 0.35** (ANN ilgili dokümanı düşürüyor) + **retrieval 286 ms >
200** (bütçe aşımı) → çoklu KIRMIZI. Recall'ın **en-kötü-sınıf** üzerinden ölçülmesi, factual'ı iyi ama
structured'ı kötü adayı yakalar (genel ortalama maskelemez).

## 8. Bulgular ve öneri (sağlayıcı-nötr)
1. **Recall ve tenant izolasyonu birinci sınıf kapılardır, gecikme değil.** RAG'ın değeri doğru dokümanı
   getirmesidir (FR-KB-009 + anti-hallucination FR-KB-007); ANN recall düşükse agent kaynak bulamaz. Tenant
   izolasyonu ise **güvenlik kapısıdır** — bir sorgunun başka tenant'ın dokümanını döndürmesi (FR-TEN-002
   ihlali) hiçbir gecikme/recall avantajıyla telafi edilmez. İkisi de **knock-out**.
2. **Recall dile/sorgu sınıfına göre bağımsız ölçülmeli:** ANN çoğu factual sorguda güçlüdür; yapısal
   alanlar (telefon/poliçe/ref no — FR-STT-005 bağı) ayrı doğrulanmazsa recall yanıltıcı görünür. Kapı
   **en-kötü-sınıf** üzerinden (STT WER / TTS MOS / LLM kalite ile aynı disiplin). Hybrid search (BM25)
   yapısal recall'ı artırır → OpenSearch'ün native avantajı, pgvector'da eklenti/birlikte kullanım gerekir.
3. **Residency + no-log birer uygunluk kapısıdır** (NFR 10.7 / FR-KB-010): AB/UK/regüle tenant için bunlar
   olmadan depo, gecikme/recall ne olursa olsun **elenir**. **pgvector burada yapısal avantajlıdır:** veri
   zaten tenant home-region PostgreSQL'inde + KMS + RLS; ayrı bir residency/no-log sözleşmesi gerekmez.
   Managed dış vektör DB için bu sözleşmesel ve denetlenmesi gereken bir risktir (DPA → 0.2.6 / 17.2.2).
4. **Operasyonel tutarlılık (stack-fit) F0/F1 için belirleyici olabilir:** pgvector PostgreSQL'i yeniden
   kullanır → RLS, audit, backup/restore (NFR 10.5), residency, KMS, **transactional metadata tutarlılığı**
   (chunk metadata ile vektör aynı işlemde) tek yerde; daha az hareketli parça. OpenSearch ayrı küme →
   ölçek + hybrid search gücü ama ayrı operasyon/HA/residency yükü. SAD §8.4 sıralaması (pgvector birincil,
   OpenSearch ikincil) bu mantıkla tutarlı; eval bunu **bağlamaz**, ölçer.
5. **Gecikme co-location ile düşer:** Aynı bölge/aynı Postgres (pgvector) ağ atlamasını kaldırır; ayrı küme
   bir hop ekler. RAG çoğu turda atlandığı için (SAD §20) gecikme kapısı recall/izolasyondan sonra gelir,
   ama ölçek büyüdükçe (index boyutu, eş zaman) HNSW parametre ayarı (ef_search/M) ile recall↔gecikme dengesi
   PoC'ta nicelenir.
6. **ADR-002 gereği depo soyutlama (VectorDbAdapter) arkasında:** Seçim değişebilir olmalı; pgvector ↔
   OpenSearch geçişi orchestrator'ı etkilememeli (SAD §8). En az bir kapı-geçen aday F1 için yeterli;
   ölçek/hybrid ihtiyacı doğarsa ikinci aday (OpenSearch) devreye girer.
7. **Karar 0.2.6'ya bırakılır** (vendor-neutral): bu görev ölçüt + metodoloji + kapıyı sağladı; sayısal
   sıralama canlı PoC ölçümleri (gerçek embedding + KB benchmark + ölçek) + operasyonel/maliyet gelince netleşir.

## 9. Açık konular / sonraki adımlar
- [ ] Canlı PoC (1.1.7 / 0.3.x): her aday için sentetik KB + sorgu setiyle (FR-TST-002/008) tenant+agent
      namespace'e indeksle; exact-kNN ground-truth ile recall@k (sınıf bazlı), retrieval P95, cross-tenant +
      filtreli ACL leak testini ölç; HNSW/IVFFlat parametre ile recall↔gecikme dengesini nicelendir.
- [ ] KB Q&A benchmark veri seti (FR-KB-009) ile recall'ı uçtan uca (retrieval + rerank + trim) doğrula;
      6.2.5 (KB benchmark) ile çapraz.
- [ ] Ölçek testi: index boyutu (doküman sayısı) × eş zamanlı sorgu altında gecikme/recall + bellek/disk;
      noisy-neighbor (NFR 10.3) ve tenant başına index/namespace maliyeti.
- [ ] Residency / no-log doğrulama: pgvector için RLS + KMS + bölge zorlama (DB.md); managed aday için
      sözleşmesel DPA + alt-işleyen listesi (0.2.6 / 17.2.2).
- [ ] Hybrid search değeri: yapısal alan (telefon/poliçe/ref no — FR-STT-005) sorgularında BM25+vektör
      recall katkısı; pgvector'da eklenti/birlikte kullanım maliyeti vs OpenSearch native.
- [ ] `score` gate'ini 0.4.4 CI hattına bağla (embedding/model/index değişiminde recall regresyonunu yakala).

## 10. İzlenebilirlik
- **Kaynak:** SAD §12.1 (polyglot persistence — "Vektörler (RAG): pgvector / OpenSearch"), §8.4 (vendor eval
  tablosu: pgvector birincil / OpenSearch ikincil), §10 (RAG mimarisi — indeksleme + retrieval), §20 (gecikme
  bütçesi — RAG retrieval ~100–200 ms P95), §13 (tenant izolasyon); ADR-002 (vendor-neutral, ≥2 aday + fallback).
- **FR:** FR-KB-003 (chunk/index/versiyon), FR-KB-004 (tenant+agent namespace), FR-KB-005 (doküman-ACL),
  FR-KB-006 (kaynak atfı), FR-KB-008 (içerik TTL/bayatlama), FR-KB-009 (Q&A benchmark), FR-KB-010 (no-log),
  FR-KB-011 (top-k trim); FR-TEN-002 (tenant izolasyon); FR-RES-004 (semantic cache embedding deposu).
- **NFR:** 10.7 (residency / home-region), 10.1 (P95 ≤ 1.200 ms; RAG retrieval alt-kalemi), 10.5 (backup/HA
  — pgvector Postgres ile birlikte).
- **WBS:** 0.2.5 (bu); girdi → 0.2.6 (karar), 1.1.7 (vector store namespace uygulaması), 6.1.3 (chunk/embed/
  index), 6.2.1 (vector search + rerank), 6.2.5 (KB benchmark), 5.4 (semantic cache embedding deposu).
