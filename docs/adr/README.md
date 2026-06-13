# Mimari Karar Kayıtları (ADR) — Süreç ve Disiplin

> **Kapsam:** Bu klasör (`docs/adr/`) platformun **mimari karar kayıtlarının (Architecture
> Decision Records)** kaynak doğruluğudur (source of truth). Her ADR, _bağlam → seçenekler →
> karar → sonuçlar_ olarak **bağımsız ve değişmez (immutable)** bir kayıttır.
> `docs/SAD.md §22` bu klasörün **türetilen özet indeksidir**, yeni kayıt yeri değildir.

ADR nedir: tek, mimari açıdan önemli bir kararı; verildiği andaki bağlam, değerlendirilen
seçenekler ve kabul edilen sonuçlarla birlikte dondurarak kaydeden kısa bir belgedir. Amaç,
"bu neden böyle?" sorusunu aylar/yıllar sonra **arkeoloji yapmadan** yanıtlayabilmektir.

## 1. Ne zaman ADR açılır?
Bir karar **mimari açıdan önemli** ise ADR gerektirir. Pratik tetikleyiciler:
- Bir **NFR**'yi (gecikme, density, güvenlik, residency, maliyet) doğrudan etkileyen yapısal seçim.
- **Vendor-neutrality**, plane ayrımı, tenancy/izolasyon, veri yerleşimi veya güven sınırı kararı.
- Geri alması **pahalı** olan ya da birden çok bileşeni bağlayan teknoloji/yaklaşım seçimi.
- BRD §22 / SAD'daki bir **açık kararın** (open decision) sonuçlanması.
- Yeni güven sınırı, dış entegrasyon veya veri akışı eklenmesi (THREAT_MODEL ile birlikte).

Rutin, tersine çevrilebilir, lokal kararlar ADR gerektirmez — kod/PR açıklaması yeterlidir.

## 2. Numaralandırma ve dosya adı disiplini
- **ADR-ID:** `ADR-NNNN` (sıfır dolgulu 4 hane), **monoton artan**; numara asla yeniden kullanılmaz.
  Mevcut son numara `gen_adr_index.py` ile bulunur: `python3 docs/adr/gen_adr_index.py --next`.
- **Dosya adı:** `NNNN-kebab-baslik.md` (ör. `0001-bagimsiz-conversation-orchestrator.md`).
  `0000-template.md` şablondur, ADR değildir (indekse girmez).
- Bir ADR yayımlandıktan sonra **dosyası/numarası değişmez**. Karar değişirse **yeni** ADR açılır
  ve eskisi `superseded-by` ile işaretlenir (aşağıya bkz.).

## 3. Durum (status) yaşam döngüsü
| Durum | Anlamı |
|-------|--------|
| `Önerilen` | Taslak; tartışmaya açık, henüz bağlayıcı değil. |
| `Kabul` | Karar yürürlükte; uygulama bunu esas alır. |
| `Açık` | Karar bilinçli olarak **ertelendi**; bir PoC/eval/paydaş çıktısına bağlı (kriter ADR'de yazılır). |
| `Reddedildi` | Önerildi, kabul edilmedi (gerekçe kayıtta kalır — silinmez). |
| `Kullanımdan kaldırıldı` | Artık geçerli değil; yerine yeni karar yok. |
| `Yerini aldı: ADR-XXXX` | Başka bir ADR ile değiştirildi (`superseded-by` doldurulur). |

İzin verilen geçişler: `Önerilen → Kabul/Reddedildi/Açık`, `Açık → Kabul/Reddedildi`,
`Kabul → Kullanımdan kaldırıldı/Yerini aldı`. Kabul edilmiş bir ADR'nin **gövdesi düzenlenmez**;
yalnız `status` ve `superseded-by` alanları güncellenir, gerisi yeni ADR'de ele alınır.

## 4. Yeni ADR oluşturma akışı
1. **Numara al:** `python3 docs/adr/gen_adr_index.py --next` → bir sonraki `ADR-NNNN`.
2. **Dosya oluştur:** `0000-template.md`'i `NNNN-kebab-baslik.md` olarak kopyala, frontmatter'ı doldur.
3. **Yaz:** Bağlam, karar sürücüleri, ≥2 değerlendirilen seçenek, karar, sonuçlar (olumlu+ödünleşim),
   izlenebilirlik (FR/NFR/SR/WBS). Yazım kuralları: ana metin **Türkçe**, teknik terimler İngilizce.
4. **İndeksi üret:** `python3 docs/adr/gen_adr_index.py` (repo kökünden) → bu README'deki indeks
   tablosunu ve `docs/SAD.md §22` özetini yeniden türetir.
5. **Doğrula:** `python3 docs/adr/gen_adr_index.py --check` (CI/pre-commit'te de çalışır).
6. **PR:** PR açıklamasında ADR-ID + ilgili WBS ID verilir. İlgili dokümanı (SAD/THREAT_MODEL/…)
   ADR'ye atıfla güncelle.

## 5. Araç (`gen_adr_index.py`)
`gen_rtm.py` ile aynı disiplinde, **stdlib-only** bir üreteç. Komutlar (repo kökünden):
- `python3 docs/adr/gen_adr_index.py` — tüm ADR frontmatter'larını okuyup
  (a) bu README'deki, (b) `docs/SAD.md §22`'deki indeks tablolarını işaretçiler arasında **yeniden üretir**.
- `--check` — diskteki indeks güncel mi doğrular (üretir ama yazmaz; tutarsızsa non-zero exit).
- `--next` — bir sonraki boş `ADR-NNNN` numarasını yazdırır.
- `--list` — ADR-ID · durum · başlık özetini yazdırır.

Kaynak (ADR `.md` dosyaları) değişince indeks yeniden üretilir; indeks **elle düzenlenmez**.

## 6. İlişkili belgeler
- `docs/SAD.md §22` — ADR özet indeksi (buradan türetilir) + §23 BRD açık kararlarına yanıtlar.
- `docs/THREAT_MODEL.md` — güvenlik kaynaklı ADR önerileri (ADR-014..017) buraya formelleştirilir.
- `CLAUDE.md` — doküman yapısı ve sabitler.

---

<!-- ADR-INDEX:BEGIN (gen_adr_index.py tarafından üretilir — elle düzenleme) -->

_Bu tablo `docs/adr/gen_adr_index.py` ile türetilir — elle düzenlemeyin. Her kaydın tam metni ilgili `docs/adr/*.md` dosyasındadır._

| ADR | Karar | Durum | İz |
|-----|-------|-------|-----|
| [ADR-001](0001-bagimsiz-conversation-orchestrator.md) | Bağımsız Conversation Orchestrator (STT/LLM/TTS doğrudan bağlanmaz) | 🟢 Kabul | BRD §11, §24; SAD §6; FR-RTC-*, FR-LLM-* |
| [ADR-002](0002-provider-adapter-spi.md) | Provider Adapter SPI + kategori başına ≥2 sağlayıcı | 🟢 Kabul | BRD §19; SAD §8.1, §8.2; FR-STT-008, FR-TTS-008, FR-LLM-010, FR-TEL-002 |
| [ADR-003](0003-hot-path-async-dusuk-bellekli-dil.md) | Hot path'te async, düşük-bellekli dil (Go/Rust) | 🟡 Önerilen | NFR 10.1, NFR 10.2; SAD §21; FR-RES-001, FR-RES-016 |
| [ADR-004](0004-plane-ayrimi.md) | Data / Control / Analytics plane ayrımı | 🟢 Kabul | SAD §4.2; FR-RES-011 |
| [ADR-005](0005-edge-vad-endpointing.md) | Edge VAD / endpointing | 🟢 Kabul | FR-RTC-013, FR-RTC-004, FR-RES-009; NFR 10.1 |
| [ADR-006](0006-tenant-izolasyonu-rls-dedicated.md) | Tenant izolasyonu — shared (RLS) + dedicated opsiyon | 🟢 Kabul | FR-TEN-002, FR-TEN-005; SAD §13.1; DB.md (RLS) |
| [ADR-007](0007-async-event-pipeline-kafka.md) | Async event pipeline (Kafka) ile post-processing | 🟢 Kabul | FR-RES-011; SAD §12.1; WBS 1.1.8 |
| [ADR-008](0008-model-tiering-semantic-cache.md) | Model tiering + semantic cache zorunlu | 🟢 Kabul | NFR 10.2; FR-RES-005, FR-LLM-014, FR-RES-004 |
| [ADR-009](0009-medya-isleme-konumu.md) | Medya işleme konumu (edge vs merkez) | 🟠 Açık | SAD §23; NFR 10.1, NFR 10.2; ADR-003, ADR-005 |
| [ADR-010](0010-self-hosted-llm-gpu.md) | Self-hosted LLM + GPU kapsamı | 🟠 Açık | FR-RES-015; SAD §23; NFR 10.2 |
| [ADR-011](0011-iki-duzlemli-panel-dagitimi.md) | İki düzlemli panel dağıtımı (L0 ayrı internal-only; L1+L2 birlikte public) | 🟢 Kabul | SAD §14.4.1; BRD §17.7; FR-IAM-008 |
| [ADR-012](0012-sabit-rol-bundle-scoped-assignment.md) | Sabit rol bundle + scoped assignment; custom roller Faz 3 | 🟢 Kabul | FR-IAM-011; SAD §14.4.3 |
| [ADR-013](0013-uc-katmanli-break-glass.md) | Üç katmanlı break-glass + regüle tenant onay toggle'ı | 🟢 Kabul | FR-IAM-009, FR-IAM-010; SAD §14.4.2; DPIA.md |
| [ADR-014](0014-zorunlu-egress-kontrol.md) | Zorunlu egress kontrol katmanı (egress proxy + allowlist) | 🟡 Önerilen | THREAT_MODEL.md §10 (TM-E-06, TM-I-04); NFR 10.6 |
| [ADR-015](0015-prompt-injection-savunma-mimarisi.md) | Prompt-injection savunma mimarisi (katmanlı) | 🟡 Önerilen | THREAT_MODEL.md §10 (TM-T-02b, TM-I-05); FR-LLM-007, FR-LLM-009 |
| [ADR-016](0016-audit-log-tamper-evidence.md) | Audit log tamper-evidence yöntemi (hash zinciri + dış mühürleme) | 🟡 Önerilen | THREAT_MODEL.md §10 (TM-T-03); FR-IAM-006 |
| [ADR-017](0017-phishing-resistant-mfa.md) | Phishing-resistant MFA zorunluluğu (WebAuthn/FIDO2) | 🟡 Önerilen | THREAT_MODEL.md §10 (TM-S-03, TM-E-05); FR-IAM-003 |

<!-- ADR-INDEX:END -->
