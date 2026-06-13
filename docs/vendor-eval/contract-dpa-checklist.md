# Sözleşme / DPA / Alt-İşleyen Listesi — Taslak

**WBS:** 0.2.6 (+ ileri 17.2.2) · **Faz:** F0 · **Öncelik:** Must · **İz:** →BRD §14.1 (DPA + alt-işleyen
listesi + sağlayıcıya gönderilen veri kaydı + ihlal bildirimi); DPIA §2 (controller/processor/sub-processor
rol ayrımı) + §5 (`cp.*` parametreleri); NFR 10.7 (residency); FR-LLM-012 (no-train) / FR-KB-010 (no-log);
FR-IAM-010 (regüle tenant onay toggle ↔ DPA); SAD §8.2 (adapter region/retention control) / §19 (uyumluluk)
**Tarih:** 2026-06-13 · **Durum:** ✅ Şablon/checklist taslağı (somut sağlayıcı doldurması 0.3.x seçimi + counsel doğrulaması sonrası)

> **Hukuki not:** Bu, mühendislik **şablonu/checklist**'idir — hukuki tavsiye değildir. Maddeler
> production öncesi tenant'ın/RMC'nin **hukuk danışmanı (counsel)** tarafından doğrulanmalıdır
> (DPIA §12 açık karar). Değerler `cp.*` parametre **şablonuyla** hizalı; gerçek sayılar (retention,
> bildirim süresi) ülke/sektör profiline ve BRD §22 açık kararlarına bağlıdır.

---

## 1. Rol modeli (kim kimin nesi)

B2B2B'de (DPIA §2):

| Rol | Taraf | Yükümlülük |
|-----|-------|-----------|
| **Controller** | **Tenant** (müşteri kurum) | İşleme amacı + hukuki dayanağı belirler; veri sahiplerine karşı sorumlu. |
| **Processor** | **RMC Technology & Consultancy** | Yalnız controller talimatıyla işler; DPA imzalar; alt-işleyen kullanımını controller'a bildirir; ihlali gecikmeksizin controller'a bildirir; DPIA destek bilgisi (DFD, alt-işleyen listesi, kontroller) sağlar. |
| **Sub-processor** | **STT / TTS / LLM / Telekom (+ managed DB) sağlayıcıları** | RMC'nin alt-işleyenleri; **DPA Ek-A**'da listelenir; **no-train + region pinning** ile sınırlandırılır (FR-LLM-012, NFR 10.7). |

İki sözleşme katmanı: **(A)** Tenant ↔ RMC **DPA** (controller↔processor) ve **(B)** RMC ↔ Sağlayıcı
**alt-işleyen sözleşmesi** (processor↔sub-processor). Bu doküman ikisinin de checklist'ini içerir.

## 2. RMC ↔ Sağlayıcı (alt-işleyen) sözleşme checklist'i

Her aday sağlayıcı için imzadan **önce** doğrulanması gereken maddeler. `cp.*` enforcement'ı ile eşlenir.

| # | Madde | Neden / İz | `cp.*` / FR | Zorunluluk |
|---|-------|-----------|-------------|-----------|
| C-01 | **No-train:** tenant verisi model eğitimine/fine-tune'a kullanılmaz | FR-LLM-012; LLM eval D4=no-train kapısı | `cp.legal.*`; FR-LLM-012 | **Must** (knock-out) |
| C-02 | **No-log / ephemeral:** istek/yanıt sağlayıcı tarafında kalıcı loglanmaz (NONE/EPHEMERAL) | FR-KB-010; hassas doküman/PII | FR-KB-010 | **Must** (knock-out) |
| C-03 | **Region pinning / residency:** işleme home-region'da; bölge dışına çıkmaz | NFR 10.7; SAD §8.2 region selection | `cp.residency.provider_region_pinning` | **Must** (knock-out) |
| C-04 | **Sınır-ötesi transfer mekanizması:** gerekiyorsa SCC / adequacy / explicit consent | DPIA §D3 | `cp.residency.cross_border_mechanism` | Must (transfer varsa) |
| C-05 | **Veri silme / dönüş:** sözleşme bitiminde geri-döndürülemez silme + silme kanıtı | FR-REC-006/010; retention | `cp.retention.*` | Must |
| C-06 | **İhlal bildirimi:** sağlayıcı, ihlali RMC'ye ≤ taahhüt süre içinde bildirir | BRD §14.1; incident chain | `cp.breach.authority_deadline_hours` (geri-hesap) | **Must** |
| C-07 | **Alt-işleyen şeffaflığı:** sağlayıcının kendi alt-işleyenleri + değişiklik bildirimi | DPIA §4 (yeni alt-işleyen tetik) | — | Should |
| C-08 | **Denetim hakları:** audit / sertifika (SOC2/ISO 27001/27701) sağlama | §17.2.5 sektörel | `cp.sector.profiles` | Should |
| C-09 | **SLA / uptime:** taahhüt + kredi; voice-hot-path için bölgesel kullanılabilirlik | NFR 10.4; karar D5 | — | Must (hot-path) |
| C-10 | **Güvenlik kontrolleri:** transit/at-rest şifreleme; erişim kontrolü | NFR 10.6; THREAT_MODEL SEC-* | — | Must |
| C-11 | **Veri kullanım sınırı:** veri yalnız hizmeti sağlamak için; ikincil kullanım yok | BRD §14.1; controller talimatı | — | Must |
| C-12 | **Çıkış / taşınabilirlik:** vendor lock-in azaltma; veri export | karar D5 (lock-in) | `cp.dsr.portability_supported` | Should |

> **Knock-out maddeler (C-01, C-02, C-03, C-06, C-09-hot-path):** karşılanmazsa aday `vendor-decision.md`
> D3/D4 knock-out'una takılır — ticari avantaj telafi etmez.

## 3. Alt-işleyen kayıt iskeleti (DPA **Ek-A**)

Tenant'a yayımlanan + DPA'ya eklenen alt-işleyen listesi. `vendor_decision_probe.py register` bunun
**iskeletini** aday `config` bayraklarından otomatik üretir (sonra counsel + ticari bilgiyle doldurulur).

| Alt-işleyen | Kategori | İşlenen veri | Bölge(ler) | No-train | No-log | Transfer mek. | DPA/sertifika | Durum |
|-------------|----------|--------------|------------|----------|--------|---------------|---------------|--------|
| `<sağlayıcı>` | STT | ses/transkript | `<region>` | evet/hayır | evet/hayır | SCC/adequacy/— | SOC2/ISO/— | aday/onaylı |
| `<sağlayıcı>` | TTS | metin→ses | `<region>` | evet | evet | — | — | aday |
| `<sağlayıcı>` | LLM | prompt/yanıt | `<region>` | evet | evet | — | — | aday |
| `<sağlayıcı>` | Telekom | medya/sinyalleşme | `<region>` | n/a | evet | — | — | aday |
| pgvector (self-host) | Vector DB | KB embedding | home-region | n/a (alt-işleyen değil) | yapısal | yok | — | dahili |

> **pgvector self-hosted ise alt-işleyen değildir** (RMC'nin kendi altyapısı) → Ek-A'da "dahili/altyapı"
> olarak işaretlenir; managed dış vektör DB seçilirse **alt-işleyen** satırına geçer.

## 4. Sağlayıcıya gönderilen veri kaydı (BRD §14.1)

"Model sağlayıcılarına aktarılan verilerin kaydı" gereksinimi (BRD §14.1) → her adapter çağrısında
**ne gönderildiği** denetlenebilir olmalı. Tasarım kancası (uygulama 4.1.x adapter SPI):

| Alan | Açıklama | İz |
|------|----------|-----|
| `provider` / `category` | Hangi alt-işleyen | DPA Ek-A |
| `data_class` | gönderilen veri sınıfı (ses/metin/embedding/PII-redacted) | FR-REC-004/005 |
| `region` | işleme bölgesi | NFR 10.7 |
| `no_train` / `retention` | eğitim-dışı + sağlayıcı saklama politikası | FR-LLM-012, FR-KB-010 |
| `correlation_id` / `tenant_id` | izlenebilirlik + tenant scope | SAD §13.3, FR-TEN-002 |

Bu kayıt, DSR/silme (`cp.dsr.*`) ve ihlal kapsam tespitinde (`cp.breach.*`) kullanılır.

## 5. Tenant ↔ RMC DPA checklist'i (controller ↔ processor)

| # | Madde | İz |
|---|-------|-----|
| D-01 | İşleme konusu/süresi/niteliği/amacı + veri kategorileri + veri sahibi sınıfları | BRD §14.1 |
| D-02 | Controller talimatı dışında işleme yok; talimat dışı durum bildirimi | DPIA §2 |
| D-03 | Alt-işleyen genel/özel izni + **Ek-A liste** + değişiklik bildirim süresi + itiraz hakkı | §3 (Ek-A) |
| D-04 | Residency taahhüdü (home-region) + sınır-ötesi mekanizma | NFR 10.7; `cp.residency.*` |
| D-05 | Retention + geri-döndürülemez silme + legal hold | `cp.retention.*`; FR-REC-006/007/010 |
| D-06 | DSR desteği (erişim/düzeltme/silme/taşınabilirlik) + SLA | `cp.dsr.*`; WBS 17.2.1 |
| D-07 | İhlal bildirimi: RMC→controller gecikmesiz; controller→makam süresi | `cp.breach.*` |
| D-08 | Güvenlik kontrolleri (TLS/SRTP, KMS per-tenant, RLS, WORM audit, PII redaction) | NFR 10.6; THREAT_MODEL |
| D-09 | **Regüle tenant break-glass onayı** (`require_tenant_approval`) DPA'ya bağlı | **FR-IAM-010** |
| D-10 | Denetim/inceleme hakkı + sertifikalar (SOC2/ISO 27001/27701) | §17.2.5 |
| D-11 | Sözleşme sonu: veri dönüş/silme + kanıt | FR-REC-010 |
| D-12 | AI şeffaflık + kayıt rızası yükümlülük paylaşımı (controller bildirimi) | `cp.transparency.*`; BRD §14.2 |

## 6. Açık konular / sonraki adım

- Somut sağlayıcı adları + gerçek değerler **0.3.x seçimi** sonrası doldurulur (vendor-neutral kısıt).
- **Counsel doğrulaması** (DPIA §12): ülke/sektör profiline göre madde değerleri (özellikle C-06/D-07
  bildirim süreleri, C-04/D-04 transfer mekanizması).
- Ek-A alt-işleyen listesinin **tenant'a yayımlanması** + değişiklik bildirim akışı (panel; T-06 Compliance).
- WBS **17.2.2** (DPA + alt-işleyen listesi + sağlayıcıya gönderilen veri kaydı) implementasyonu bu
  taslağı esas alır; F2 fazında panelleştirilir.
