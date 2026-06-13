# DPIA Şablonu ve Compliance Profile Parametre Seti

## Kurumsal Sesli Yapay Zekâ Asistanı Platformu — Enterprise Voice AI Agent Platform

**Data Protection Impact Assessment (DPIA) Template & Compliance Profile Parameter Set**
Multi-Tenant (B2B2B) · Config-Driven · TR · UK · EU · ME

> RMC TECHNOLOGY & CONSULTANCY — rmctech.co.uk

---

## Doküman Bilgileri

| Alan | Değer |
|------|-------|
| Doküman Adı | Enterprise Voice AI Agent Platform — DPIA Şablonu + Compliance Profile Parametre Seti |
| Doküman Tipi | Privacy / Compliance Design (DPIA + CP) |
| Bağlı Doküman | `docs/BRD.md` (Sürüm 2.1) §14, §8.1, §16; `docs/SAD.md` (Sürüm 1.1) §12.3, §14, §19; `docs/DB.md` v1.0; `docs/THREAT_MODEL.md` v1.0 |
| Sürüm | 1.0 |
| Tarih | 13 Haziran 2026 |
| Durum | İncelemeye Hazır — Hukuki doğrulama (counsel) ve ME alt-ülke kararı bekliyor |
| Gizlilik | Gizli — Yalnızca yetkili paydaşlar (hukuk/uyum/güvenlik dağıtımı) |

### Sürüm Geçmişi

| Sürüm | Tarih | Açıklama |
|-------|-------|----------|
| 1.0 | 13.06.2026 | BRD §14.1'in "DPIA şablonu" ve §14.4'ün "compliance profile seçimi" gereksinimlerinin ilk sürümü. (1) Yüksek-riskli işleme için DPIA tetik kriterleri (`DPIA-T-NN`), (2) platforma özel önceden-doldurulmuş DPIA şablonu (§D1..§D9), (3) config-driven compliance profile parametre modeli (`cp.*` parametre anahtarları), (4) TR/UK/EU/ME ülke profilleri (`PROFILE-TR/UK/EU/ME`) parametre değer tabloları, (5) sektörel overlay'ler, (6) profil çözümleme/öncelik motoru, (7) FR/SR/SAD izlenebilirliği ve test eşlemesi. |

---

## İçindekiler

1. Amaç, Kapsam ve Yöntem
2. Roller: Controller / Processor ve DPIA Sorumluluğu
3. DPIA Tetik Kriterleri (ne zaman zorunlu)
4. DPIA Şablonu (§D1..§D9)
5. Compliance Profile — Model ve Parametre Anahtarları (`cp.*`)
6. Ülke Profilleri (TR / UK / EU / ME)
7. Sektörel Uyumluluk Overlay'leri
8. Profil Çözümleme ve Öncelik Motoru
9. Platforma Gömülü Uygulama (enforcement) Noktaları
10. İzlenebilirlik (BRD/FR/SR/SAD ↔ Parametre ↔ Önlem)
11. Doğrulama (test eşlemesi)
12. Açık Kararlar ve Sonraki Adımlar

---

## 1. Amaç, Kapsam ve Yöntem

Bu doküman BRD §14.1'in iki somut çıktısını üretir: (a) **DPIA şablonu** — yüksek riskli kullanım durumlarında devreye alma (onboarding) sürecinin parçası olacak, platforma özel önceden doldurulmuş bir Veri Koruma Etki Değerlendirmesi şablonu; ve (b) BRD §14.4'ün talep ettiği **compliance profile** mekanizmasının **parametre seti** — tenant'ın ülke ve sektörüne göre seçilen, **config-driven** (kod değişikliği gerektirmeyen) bir uyumluluk profili modeli ve TR/UK/EU/ME için somut parametre değerleri.

**Kapsam:** KVKK (TR), UK GDPR + DPA 2018 (UK), EU GDPR + EU AI Act şeffaflık yükümlülüğü (EU) ve Orta Doğu (ME) veri koruma rejimleri kapsamındaki uyumluluk parametreleri; outbound çağrı uygunluğu (consent/DNC/arama saati); veri yerleşimi (residency); saklama (retention); veri sahibi hakları (DSR); ihlal bildirimi; AI şeffaflığı; kayıt rızası; ve sektörel overlay referansları. Mekanizma BRD §16 varlıkları ve SAD §19 Uyumluluk Mimarisi üzerine oturur.

**Kapsam dışı:** Sektörel kontrollerin tam denetim implementasyonu (PCI ödeme akışı Faz 3 — BRD §8.5; sektörel profiller WBS 17.2.5); her ME ülkesinin madde-madde hukuki yorumu (hukuk danışmanı doğrulamasına tabi — §12); BYOK/residency'nin altyapı implementasyonu (WBS 1.2.2, 17.1.3).

**Yöntem:**
1. **Roller netleştirilir** (§2) — RMC processor, tenant controller; DPIA yasal yükümlülüğü controller'da, platform şablon + destek bilgisi sağlar.
2. **Tetik tanımlanır** (§3) — Hangi işleme türü DPIA'yı zorunlu kılar (`DPIA-T-NN`); onboarding gate.
3. **Şablon önceden doldurulur** (§4) — Platformun bilinen mimarisiyle (DFD, varlıklar, SEC kontrolleri) sabit alanlar doldurulur; tenant'a-özel alanlar boş bırakılır.
4. **Parametreleştirilir** (§5) — Uyumluluk kararları `cp.<alan>.<anahtar>` biçiminde makine-okunur parametrelere indirilir.
5. **Profillenir** (§6–§7) — Ülke ve sektör için parametre değerleri verilir; çözümleme/öncelik kuralı tanımlanır (§8).
6. **Bağlanır** (§9–§11) — Her parametre platformdaki enforcement noktasına ve FR/SR/test'e eşlenir.

> **ID şeması notu:** Bu doküman üç yeni ID ailesi tanıtır: DPIA tetikleri için `DPIA-T-NN`, DPIA şablon bölümleri için `§D<N>`, compliance profile parametreleri için `cp.<alan>.<anahtar>` ve ülke/sektör profilleri için `PROFILE-<KOD>`. Mevcut FR/SR/NFR/ADR numaralandırması **değiştirilmez**; yalnız referans verilir. Bu doküman **yaşayan belgedir**: yeni ülke/sektör/veri akışı eklenince parametre seti ve profiller güncellenir.

---

## 2. Roller: Controller / Processor ve DPIA Sorumluluğu

| Rol | Taraf | Sorumluluk |
|-----|-------|------------|
| **Veri Sorumlusu (Controller)** | **Tenant** (kurumsal müşteri) | İşleme amacı ve hukuki dayanağı belirler; DPIA'yı yürütmek ve onaylamakla yükümlüdür; veri sahibi taleplerinin nihai muhatabıdır. |
| **Veri İşleyen (Processor)** | **RMC** (platform operatörü) | Yalnızca controller talimatıyla işler; DPIA **şablonunu** + destekleyici teknik bilgiyi (DFD, alt-işleyen listesi, güvenlik kontrolleri, residency) sağlar; DPA imzalar; ihlali controller'a gecikmeksizin bildirir. |
| **Alt İşleyen (Sub-processor)** | STT/TTS/LLM/telekom sağlayıcıları | RMC'nin alt-işleyenleri; DPA'da listelenir; "no-train" + region pinning ile sınırlandırılır (FR-LLM-012, NFR 10.7). |

**Sonuç:** DPIA'yı **tenant (controller)** yürütür; ancak platform bunu **devreye alınamaz hale getirecek kadar kolaylaştırır** — yüksek-riskli işleme tespit edilirse onboarding akışı, bu dokümandaki önceden doldurulmuş şablonla DPIA tamamlanana dek bloke edilir (BRD §14.1: *"Yüksek riskli kullanım durumlarında DPIA, devreye alma sürecinin parçası olmalıdır"*). Üç katmanlı break-glass (ADR-013) ve L0'ın iş içeriğine varsayılan erişimsizliği bu controller-processor ayrımının teknik karşılığıdır.

---

## 3. DPIA Tetik Kriterleri (ne zaman zorunlu)

Aşağıdaki kriterlerden **biri** karşılanırsa, tenant/agent için DPIA onboarding'in zorunlu kapısıdır (`require_dpia = true`). Kriterler GDPR Madde 35(3), EDPB WP248 (9 ölçüt) ve KVKK VERBİS/Kurul ilkeleriyle hizalıdır; sesli AI bağlamına uyarlanmıştır.

| ID | Tetik | Gerekçe / Eşik |
|----|-------|----------------|
| `DPIA-T-01` | **Özel nitelikli/hassas veri** işleme (sağlık, finansal hesap, biyometrik) | Sağlık/finans tenant'ı; ses biyometrisi modülü (FR-AUTH-006/007) → her zaman DPIA. |
| `DPIA-T-02` | **Geniş ölçekli** sistematik işleme | Outbound kampanya hacmi veya inbound çağrı hacmi büyük tenant; sistematik müşteri iletişimi. |
| `DPIA-T-03` | **Otomatik karar / profilleme** hukuki/önemli etkiyle | Agent'ın bir tool ile hak/yükümlülük doğuran işlem yapması (BRD §13 kritik işlemler) → insan onayı + DPIA. |
| `DPIA-T-04` | **Yeni teknoloji** — gerçek zamanlı ses + LLM | Sesli AI'nın doğası gereği; AI Act etkileşimli sistem (BRD §14.2). |
| `DPIA-T-05` | **Ses kaydı + transkript** kalıcı saklama | Ham ses + transkript PII içerir; kayıt açık tenant (FR-REC-001/003). |
| `DPIA-T-06` | **Sınır ötesi veri transferi** veya provider'a içerik gönderimi | Home-region dışı işleme; LLM/STT/TTS sağlayıcısına içerik (NFR 10.7, FR-LLM-012). |
| `DPIA-T-07` | **Savunmasız veri sahibi** grupları | Çocuk, hasta, borçlu vb. ile sistematik temas. |
| `DPIA-T-08` | **Ses klonlama / sentetik ses** kullanımı | Onaylı sesler dışı risk; impersonation (FR-TTS-006/007, Policy Engine "no deceptive impersonation"). |

**Karar mantığı:** Onboarding sırasında tenant'ın ülke + sektör + use-case + kayıt/consent + residency seçimleri toplanır; yukarıdaki kriterler değerlendirilip `require_dpia` türetilir. Regüle profil (finans/sağlık) **varsayılan `require_dpia = true`**. Sonuç ve gerekçe Audit Log'a (FR-IAM-006) yazılır.

---

## 4. DPIA Şablonu (§D1..§D9)

Şablon **iki tip alan** içerir: **[SABİT]** — platform mimarisinden önceden doldurulur, tenant değiştirmez; **[TENANT]** — controller (tenant) onboarding'de doldurur. Şablon panelde (T-06 Compliance & Retention) rehberli form olarak sunulur; çıktısı versiyonlanır ve Audit Log'a bağlanır.

### §D1 — Kapak, Sahiplik ve Onay
- [TENANT] Veri sorumlusu (tenant tüzel kişi), DPO/irtibat kişisi, sektör, hedef ülke(ler).
- [SABİT] Veri işleyen: RMC Technology & Consultancy; alt-işleyen listesi (DPA Ek-A'dan).
- [TENANT] DPIA sahibi, gözden geçirme tarihi, onay (DPO/yönetim imzası).
- [SABİT] Seçili compliance profile: `PROFILE-<ülke>` (+ sektörel overlay) — §6/§7.

### §D2 — İşlemenin Tanımı (nature, scope, context, purpose)
- [TENANT] İşleme amacı ve **hukuki dayanak** (`cp.legal.lawful_basis_default` öneri olarak; controller teyit eder).
- [TENANT] Use-case (inbound destek / outbound kampanya / kimlik doğrulama), beklenen çağrı hacmi, veri sahibi grupları.
- [SABİT] Veri kategorileri (BRD §16 varlıklarından türetilir): Çağrı meta verisi, Ses kaydı, Transkript, Müşteri irtibat verisi (Contact), Consent kaydı, Tool Execution (kurumsal işlem), Usage Record. Özel nitelikli veri varsa işaretlenir.
- [SABİT] Saklama süreleri: `cp.retention.*` (§5) — kayıt/transkript/audit ayrı.

### §D3 — Veri Akışı ve Varlık Eşlemesi (DFD)
- [SABİT] Veri akış diyagramı ve güven sınırları `docs/THREAT_MODEL.md` §3 (TB-1..TB-9, DFD) referans alınır.
- [SABİT] Sağlayıcıya (STT/TTS/LLM/telekom) giden veri akışı + "no-train" + region pinning notu (FR-LLM-012, FR-KB-010, NFR 10.7).
- [SABİT] PII redaction noktası (Analytics Plane, async — FR-REC-004/005); kart/parola/OTP kayıt+transkriptten çıkarılır.

### §D4 — Zorunluluk ve Orantılılık (necessity & proportionality)
- [TENANT] İşleme amaca uygun, gerekli ve orantılı mı? Daha az müdahaleci alternatif değerlendirmesi.
- [SABİT] Data minimisation kontrolleri: token trimming (FR-KB-011), hassas doküman provider loglarına gitmez (FR-KB-010), kayıt tamamen kapatılabilir (FR-REC-002).
- [TENANT] Saklama gerekçesi; varsayılan muhafazakâr retention (SAD §23) üzerine tenant gerekçeli değişiklik.

### §D5 — Danışma (consultation)
- [TENANT] Veri sahiplerine bilgilendirme yöntemi: çağrı başı AI + kayıt bildirimi (`cp.transparency.*`, FR — BRD §14.2).
- [TENANT] İç paydaş/DPO danışması; gerekirse denetim makamına ön danışma (yüksek artık risk).

### §D6 — Risklerin Tanımlanması (risks to rights & freedoms)
- [SABİT] Aday risk kataloğu `docs/THREAT_MODEL.md` STRIDE tehditlerinden privacy-ilişkili olanlarla beslenir: cross-tenant sızıntı, transkript/kayıt ifşası, break-glass kötüye kullanımı, prompt-injection ile veri sızdırma, fazla saklama.
- [TENANT] Her risk için Likelihood × Severity (THREAT_MODEL §5 ölçeği ile uyumlu).

### §D7 — Önlemler (measures to mitigate risk)
- [SABİT] Platform kontrolleri → THREAT_MODEL `SEC-01..SEC-20` ve FR'ler: RLS + tenant/KMS izolasyonu, WORM audit, üç katmanlı break-glass (ADR-013), PII redaction, retention + geri-döndürülemez silme (FR-REC-006/010), residency pinning, AI şeffaflık bildirimi, Consent Engine ön-kontrol.
- [TENANT] Tenant tarafı kontroller (erişim yönetimi, eğitim, sözleşmeler).

### §D8 — Kalıntı Risk ve Karar
- [TENANT] Önlem sonrası kalıntı risk seviyesi; kabul / ek önlem / makam danışması kararı.
- [SABİT] Kalıntı risk "yüksek" ise onboarding bloke; çözülene dek tenant production'a geçemez.

### §D9 — Gözden Geçirme Döngüsü
- [TENANT] DPIA gözden geçirme tetikleyicileri: use-case/sektör/ülke/residency değişimi, yeni alt-işleyen, ihlal, periyodik (≥ yılda 1).
- [SABİT] Tetikleyici olaylar panelde uyarı üretir (T-06); DPIA "yaşayan belge" olarak versiyonlanır.

---

## 5. Compliance Profile — Model ve Parametre Anahtarları (`cp.*`)

**Model:** Bir compliance profile, makine-okunur **parametre anahtarı → değer** kümesidir. Profil **veri** olarak saklanır (BRD §16 Tenant'a bağlı; SAD §19), kod değildir — yeni ülke/kural eklemek konfigürasyon işidir. Tenant'a etkin profil = **ülke profili** ⊕ **sektörel overlay** ⊕ **tenant override** (çözümleme §8).

Parametre anahtarı biçimi: **`cp.<alan>.<anahtar>`**. Aşağıda alanlar ve anahtarlar, anlam/tip ve enforcement noktasıyla listelenir.

### 5.1 Hukuki Rejim ve Veri Koruma (`cp.legal.*`)

| Anahtar | Tip | Anlam | Enforcement |
|---------|-----|-------|-------------|
| `cp.legal.regime` | enum | Geçerli veri koruma rejimi (KVKK / UK_GDPR / EU_GDPR / ME_*) | DPIA §D1, DSR akışları |
| `cp.legal.lawful_basis_default` | enum | Önerilen hukuki dayanak (consent / legitimate_interest / contract) | DPIA §D2 (öneri) |
| `cp.legal.controller_role` | enum | Tenant=controller (sabit) | §2 |
| `cp.legal.require_dpia_default` | bool | Profil için DPIA varsayılan zorunluluğu | §3 onboarding gate |
| `cp.legal.dpa_required` | bool | DPA imzası zorunlu | Onboarding |

### 5.2 Şeffaflık ve AI/Kayıt Bildirimi (`cp.transparency.*`)

| Anahtar | Tip | Anlam | Enforcement |
|---------|-----|-------|-------------|
| `cp.transparency.ai_disclosure_required` | bool | Çağrı başı "yapay zekâ" bildirimi zorunlu | Agent açılış metni (BRD §14.2, SAD §19.3) |
| `cp.transparency.ai_disclosure_timing` | enum | `call_start` (sabit varsayılan) | Orchestrator açılış turu |
| `cp.transparency.recording_notice_required` | bool | Kayıt bildirimi zorunlu | Açılış metni |
| `cp.transparency.recording_consent_model` | enum | `notice` / `explicit_optin` / `all_party` | Kayıt başlatma kapısı (FR-REC-001) |
| `cp.transparency.no_deceptive_impersonation` | bool | İnsan taklidi yasağı (sabit `true`) | Policy Engine (BRD §5) |

### 5.3 Outbound Uygunluğu (`cp.outbound.*`) — Consent Engine girdileri (SAD §19.1)

| Anahtar | Tip | Anlam | Enforcement |
|---------|-----|-------|-------------|
| `cp.outbound.consent_model` | enum | `opt_in` / `soft_opt_in` / `opt_out` | Consent Engine ön-kontrol (FR-OUT-003) |
| `cp.outbound.consent_registry` | enum | Ulusal izin/ret kaydı (İYS / TPS-CTPS / yok / ...) | Consent Engine (BRD §14.3) |
| `cp.outbound.dnc_lists` | liste | Uygulanacak do-not-call/suppression kaynakları | Gerçek zamanlı DNC (FR-TEL-014, FR-OUT-006) |
| `cp.outbound.calling_hours_local` | aralık | İzin verilen yerel arama saatleri | Arama saati kuralı (FR-TEL-013, FR-OUT-004) |
| `cp.outbound.cli_presentation_required` | bool | Geçerli/aranabilir Caller ID zorunlu | Numara yönetimi (FR-TEL-004/005) |
| `cp.outbound.silent_call_threshold` | sayı/oran | Silent/abandoned call üst sınırı | Kapasite kontrolü (FR-TEL-015) |
| `cp.outbound.b2b_exemption` | bool | Kurumsal (B2B) muafiyeti uygulanır mı | Consent Engine birey/şirket dalı |

### 5.4 Veri Yerleşimi / Residency (`cp.residency.*`) — SAD §12.3, NFR 10.7

| Anahtar | Tip | Anlam | Enforcement |
|---------|-----|-------|-------------|
| `cp.residency.home_region` | enum | UK / EU / NA / ME (tenant home region) | Tüm depolar + provider region |
| `cp.residency.in_region_storage_required` | bool | Kayıt/transkript/prompt/KB/audit/backup home-region'da | DB.md residency, S3/KMS |
| `cp.residency.provider_region_pinning` | bool | Adapter region selection zorunlu | Adapter SPI (FR — NFR 10.7) |
| `cp.residency.cross_border_mechanism` | enum | SCC / adequacy / explicit_consent / none | Sınır ötesi transfer kaydı (DPIA §D3) |

### 5.5 Saklama (`cp.retention.*`) — FR-REC-006/007/010

| Anahtar | Tip | Anlam | Enforcement |
|---------|-----|-------|-------------|
| `cp.retention.recording_days` | sayı | Ses kaydı saklama (gün) | Retention motoru → geri-döndürülemez silme |
| `cp.retention.transcript_days` | sayı | Transkript saklama (gün) | Retention motoru |
| `cp.retention.audit_days` | sayı | Audit log saklama (gün, ≥ yasal asgari) | WORM audit |
| `cp.retention.legal_hold_supported` | bool | Legal hold geçersiz kılar | FR-REC-007 |
| `cp.retention.pii_redaction_required` | bool | Kalıcı saklama öncesi redaction | FR-REC-004/005 |

### 5.6 Veri Sahibi Hakları / DSR (`cp.dsr.*`) — BRD §14.1

| Anahtar | Tip | Anlam | Enforcement |
|---------|-----|-------|-------------|
| `cp.dsr.access_sla_days` | sayı | Erişim talebi yanıt süresi | DSR akışı (WBS 17.2.1) |
| `cp.dsr.erasure_sla_days` | sayı | Silme talebi süresi | Retention/silme motoru |
| `cp.dsr.rectification_supported` | bool | Düzeltme hakkı akışı | Panel |
| `cp.dsr.portability_supported` | bool | Taşınabilirlik (export) | Ham veri export |

### 5.7 İhlal Bildirimi (`cp.breach.*`) — BRD §14.1

| Anahtar | Tip | Anlam | Enforcement |
|---------|-----|-------|-------------|
| `cp.breach.authority` | enum | Yetkili makam (KVKK / ICO / lead SA / ME makamı) | Incident response (WBS 17.1.6) |
| `cp.breach.authority_deadline_hours` | sayı | Makama bildirim süresi | Incident runbook |
| `cp.breach.data_subject_notice` | enum | Bireye bildirim koşulu (`high_risk` / `always`) | Incident runbook |

### 5.8 Sektörel Overlay Bayrağı (`cp.sector.*`) — §7

| Anahtar | Tip | Anlam | Enforcement |
|---------|-----|-------|-------------|
| `cp.sector.profiles` | liste | Etkin sektörel overlay'ler (PCI/FCA/HIPAA/...) | §7; ek kontrol ve gate'ler |
| `cp.sector.pci_in_scope` | bool | Kart verisi akışı var (PCI) | Ödeme kanalı dışlama (BRD §8.5) |

---

## 6. Ülke Profilleri (TR / UK / EU / ME)

> **Not (hukuki):** Aşağıdaki değerler **mühendislik varsayılanları**dır; production öncesi tenant'ın hukuk danışmanı (counsel) tarafından doğrulanmalıdır (§12 açık karar). Değerler parametre **şablonu**dur; gerçek sayılar (özellikle retention) BRD §22'deki "retention süreleri" açık kararına bağlıdır ve muhafazakâr başlangıçla (SAD §23) konur.

### 6.1 `PROFILE-TR` — Türkiye (KVKK)

| Parametre | Değer | Not |
|-----------|-------|-----|
| `cp.legal.regime` | `KVKK` | 6698 sayılı Kanun |
| `cp.legal.lawful_basis_default` | `explicit_consent` / `legitimate_interest` | Use-case'e göre; açık rıza outbound pazarlama için |
| `cp.transparency.ai_disclosure_required` | `true` | İyi uygulama; impersonation yasağı |
| `cp.transparency.recording_consent_model` | `notice` (+ aydınlatma) | KVKK aydınlatma yükümlülüğü |
| `cp.outbound.consent_model` | `opt_in` | ETK ticari elektronik ileti onayı |
| `cp.outbound.consent_registry` | `IYS` | İleti Yönetim Sistemi izin kaydı (BRD §14.3) |
| `cp.outbound.dnc_lists` | `[IYS_ret]` | İYS ret kayıtları |
| `cp.outbound.calling_hours_local` | `09:00–20:00 (yerel)` | Muhafazakâr varsayılan; counsel teyidi |
| `cp.outbound.b2b_exemption` | `false` | ETK B2B dahil değerlendirilir |
| `cp.residency.home_region` | `EU` veya `ME`/yerel | TR için bölge kararı açık (§12) |
| `cp.residency.cross_border_mechanism` | `explicit_consent` / `commitment` | KVKK yurt dışı aktarım rejimi |
| `cp.dsr.access_sla_days` | `30` | KVKK başvuru süresi |
| `cp.breach.authority` | `KVKK` | Kurul |
| `cp.breach.authority_deadline_hours` | `72` | "En kısa sürede" — 72s muhafazakâr |
| `cp.breach.data_subject_notice` | `high_risk` | İlgili kişiye bildirim |

### 6.2 `PROFILE-UK` — Birleşik Krallık (UK GDPR + DPA 2018 + PECR)

| Parametre | Değer | Not |
|-----------|-------|-----|
| `cp.legal.regime` | `UK_GDPR` | + Data Protection Act 2018 |
| `cp.legal.lawful_basis_default` | `legitimate_interest` / `consent` | Use-case'e göre |
| `cp.transparency.ai_disclosure_required` | `true` | Şeffaflık; impersonation yasağı |
| `cp.transparency.recording_consent_model` | `notice` | Tek-taraf bildirim yeterli (iş amaçlı) |
| `cp.outbound.consent_model` | `soft_opt_in` | PECR; mevcut müşteri istisnası |
| `cp.outbound.consent_registry` | `TPS_CTPS` | (C)TPS taraması (BRD §14.3 PECR/Ofcom) |
| `cp.outbound.dnc_lists` | `[TPS, CTPS, tenant_suppression]` | Ofcom kuralları |
| `cp.outbound.calling_hours_local` | `08:00–21:00 (yerel)` | Ofcom iyi uygulama; counsel teyidi |
| `cp.outbound.silent_call_threshold` | Ofcom limiti | Silent/abandoned call kuralı |
| `cp.outbound.cli_presentation_required` | `true` | Ofcom CLI zorunluluğu |
| `cp.residency.home_region` | `UK` | UK bölgesi |
| `cp.residency.cross_border_mechanism` | `adequacy` / `UK_SCC (IDTA)` | UK adequacy / IDTA |
| `cp.dsr.access_sla_days` | `30` (1 ay) | UK GDPR |
| `cp.breach.authority` | `ICO` | Information Commissioner's Office |
| `cp.breach.authority_deadline_hours` | `72` | UK GDPR Art. 33 |
| `cp.breach.data_subject_notice` | `high_risk` | Art. 34 |

### 6.3 `PROFILE-EU` — Avrupa Birliği (EU GDPR + EU AI Act)

| Parametre | Değer | Not |
|-----------|-------|-----|
| `cp.legal.regime` | `EU_GDPR` | + üye devlet özel kuralları (overlay) |
| `cp.legal.lawful_basis_default` | `legitimate_interest` / `consent` | Use-case'e göre |
| `cp.transparency.ai_disclosure_required` | `true` (**zorunlu**) | **EU AI Act şeffaflık — 02.08.2026** (BRD §14.2): makineyle etkileşim bildirimi |
| `cp.transparency.ai_disclosure_timing` | `call_start` | Etkileşim başında |
| `cp.transparency.recording_consent_model` | `notice` / üye devlete göre | Bazı üye devletlerde all-party rıza (overlay) |
| `cp.outbound.consent_model` | `opt_in` (genel) | ePrivacy; üye devlet farkı overlay |
| `cp.outbound.consent_registry` | `per_member_state` | Robinson list vb. (ülkeye göre) |
| `cp.outbound.calling_hours_local` | üye devlete göre | Overlay |
| `cp.residency.home_region` | `EU` | AB bölgesi |
| `cp.residency.cross_border_mechanism` | `adequacy` / `SCC` | Üçüncü ülke aktarımı |
| `cp.dsr.access_sla_days` | `30` (1 ay) | GDPR Art. 12 |
| `cp.breach.authority` | `lead_SA` | One-stop-shop; lead supervisory authority |
| `cp.breach.authority_deadline_hours` | `72` | GDPR Art. 33 |
| `cp.breach.data_subject_notice` | `high_risk` | Art. 34 |

### 6.4 `PROFILE-ME` — Orta Doğu (composite)

> **Önemli:** "ME" tek bir rejim değildir; ülkeye göre ayrışır (UAE PDPL + DIFC DP Law + ADGM; KSA PDPL; Qatar PDPPL; Bahrain PDPL; vb.). Bu profil bir **şablon ve varsayılan** sağlar; etkin tenant için **alt-ülke profili** (`PROFILE-ME-AE`, `PROFILE-ME-SA`, …) seçilmelidir (§12 açık karar). Aşağıdaki değerler muhafazakâr ortak payda + UAE/KSA referansıdır ve counsel doğrulamasına tabidir.

| Parametre | Değer (varsayılan/şablon) | Not |
|-----------|---------------------------|-----|
| `cp.legal.regime` | `ME_PDPL` (alt-ülke ile ezilir) | UAE/KSA/Qatar/Bahrain PDPL aileleri |
| `cp.legal.lawful_basis_default` | `consent` | ME rejimlerinde rıza ağırlıklı; muhafazakâr |
| `cp.transparency.ai_disclosure_required` | `true` | İyi uygulama; impersonation yasağı |
| `cp.transparency.recording_consent_model` | `explicit_optin` | Muhafazakâr varsayılan |
| `cp.outbound.consent_model` | `opt_in` | Muhafazakâr; alt-ülke TRA/CITC kuralları |
| `cp.outbound.consent_registry` | `national_dnc (varsa)` | UAE TDRA / KSA CITC DNC; alt-ülke |
| `cp.outbound.calling_hours_local` | `09:00–18:00 (yerel)` | Muhafazakâr; counsel teyidi |
| `cp.residency.home_region` | `ME` | Yerel veri ikametine eğilim (data localization) |
| `cp.residency.in_region_storage_required` | `true` | Bazı ME rejimleri yerelleştirme ister |
| `cp.residency.cross_border_mechanism` | `explicit_consent` / `adequacy(varsa)` | Alt-ülke transfer rejimi |
| `cp.dsr.access_sla_days` | `30` | Alt-ülke ile ezilir |
| `cp.breach.authority` | `alt-ülke makamı` | UAE Data Office / KSA SDAIA vb. |
| `cp.breach.authority_deadline_hours` | `72` (muhafazakâr) | Alt-ülke ile ezilir |
| `cp.breach.data_subject_notice` | `high_risk` | Alt-ülke ile ezilir |

---

## 7. Sektörel Uyumluluk Overlay'leri

Sektörel profiller, ülke profilinin **üzerine** eklenen ve genelde **daha sıkı** kontrol/gate getiren overlay'lerdir (`cp.sector.profiles`). Tam implementasyon Faz 3'tür (WBS 17.2.5/17.2.6); burada parametre bağı ve etki tanımlanır. Çakışmada **en sıkı kazanır** (§8).

| Overlay | Tetikleyen sektör | Başlıca ek parametre/etki | Faz |
|---------|-------------------|---------------------------|-----|
| **PCI DSS** | Ödeme/kart | `cp.sector.pci_in_scope=true` → kart verisi LLM/transkript/kayıt **dışı**; DTMF masking / PCI kanala aktarım (BRD §8.5) | F3 |
| **FCA** | UK finans | Çağrı kaydı saklama uzatma; uygunluk/iletişim kuralları; `cp.retention.recording_days` ↑ | F3 |
| **HIPAA** | ABD sağlık | PHI işleme; BAA; şifreleme + erişim audit sıkılaştırma | F3 |
| **NHS DSP Toolkit** | UK sağlık | DSP Toolkit kontrolleri; residency UK | F3 |
| **SOC 2 / ISO 27001 / ISO 27701** | Genel kurumsal | Kontrol çerçevesi kanıtı; audit kapsamı | F2/F3 |
| **DORA** | EU finans | Operasyonel dayanıklılık, ICT risk, olay raporlama | F3 |
| **NIS2** | EU kritik sektör | Güvenlik tedbiri + olay bildirim yükümlülüğü | F3 |

`cp.sector.pci_in_scope=true` iken DPIA tetik `DPIA-T-01` zorunlu olur ve PCI ödeme akışı (BRD §8.5) devreye girene dek ilgili tool/akış bloke edilebilir.

---

## 8. Profil Çözümleme ve Öncelik Motoru

Tenant'a **etkin** parametre değeri şu sırayla çözülür (sonraki öncekini ezer; **kısıt sıkılaştıran** override'lar serbest, **gevşeten** override'lar yalnız gerekçeli ve audit'li):

```
Etkin değer(cp.X)  =  resolve(
    1. PLATFORM_DEFAULT(cp.X)          // global muhafazakâr taban
    2. ⊕ PROFILE-<ülke>(cp.X)          // ülke profili (§6)
    3. ⊕ PROFILE-ME-<alt-ülke>(cp.X)   // (ME ise) alt-ülke
    4. ⊕ SECTOR_OVERLAY[](cp.X)        // sektörel (§7), birden çok olabilir
    5. ⊕ TENANT_OVERRIDE(cp.X)         // tenant'a özel (sınırlı, audit'li)
)
```

**Çözümleme kuralları:**
- **En sıkı kazanır (most-restrictive-wins):** Sayısal kısıtlarda (arama saati penceresi, retention asgarisi, SLA) ve boolean gate'lerde, daha koruyucu değer seçilir. Örn. `calling_hours` kesişimi alınır; `require_dpia` herhangi bir katmanda `true` ise `true`.
- **Tenant override yalnız sıkılaştırabilir** (varsayılan). Gevşetme (ör. retention kısaltma yasal asgarinin altına) **engellenir**; izinli istisnalar maker-checker + gerekçe + Audit Log gerektirir (FR-IAM-005/006).
- **Çok-ülke tenant:** Çağrı bazında veri sahibinin/numaranın ülkesine göre ilgili profil seçilir (Consent Engine + residency çağrı-zamanı çözümü).
- **Çözüm kaydı:** Etkin profilin hangi katmanlardan türediği (provenance) Audit Log'a yazılır; panelde (T-06) gösterilir.

---

## 9. Platforma Gömülü Uygulama (enforcement) Noktaları

Parametreler "rapor" değil, **çalışan kontrol** girdileridir. Eşleme:

| Parametre alanı | Enforcement bileşeni | Referans |
|-----------------|----------------------|----------|
| `cp.transparency.*` | Orchestrator açılış turu + Policy Engine | SAD §19.3, BRD §14.2 |
| `cp.outbound.*` | **Consent Engine** ön-kontrol (dial öncesi) | SAD §19.1, FR-OUT-003/004, FR-TEL-013/014/015 |
| `cp.residency.*` | Depolar (S3/KMS/DB) + Adapter region selection | SAD §12.3, NFR 10.7, DB.md |
| `cp.retention.*` | Retention motoru + WORM audit | FR-REC-006/007/010 |
| `cp.dsr.*` | Veri sahibi hakları akışları (panel) | BRD §14.1, WBS 17.2.1 |
| `cp.breach.*` | Incident response runbook | WBS 17.1.6, BRD §15 |
| `cp.legal.require_dpia_default` | Onboarding gate (DPIA tamamlanmadan production yok) | §3, BRD §14.1 |
| `cp.sector.*` | Sektörel kontroller + PCI kanal dışlama | BRD §8.5, WBS 17.2.5/6 |

**Panel:** Profil seçimi ve değerleri **T-06 Compliance & Retention** (L1) ekranında yönetilir; her veri türünün residency'si T-06/T-09'da gösterilir (NFR 10.7). Global politika ve guardrails L0 **P-06**'da; platform genel default'ları buradan.

---

## 10. İzlenebilirlik (BRD/FR/SR/SAD ↔ Parametre ↔ Önlem)

| Kaynak gereksinim | Parametre/Bölüm | Önlem / FR | SR (SRS) |
|-------------------|------------------|------------|----------|
| BRD §14.1 (DPIA, DSR, DPA, alt-işleyen, ihlal) | §3, §4, §5.6, §5.7 | DPIA gate, DSR akışı, Incident | SR-SEC-*, SR-REC-006 |
| BRD §14.2 (AI/şeffaflık, AI Act 02.08.2026) | `cp.transparency.*` | Açılış turu, Policy Engine | SR-LLM-006/009 |
| BRD §14.3 (outbound uyum, İYS/PECR) | `cp.outbound.*` | Consent Engine | SR-OUT-003/004/006, SR-TEL-013/014/015 |
| BRD §14.4 (sektörel + compliance profile seçimi) | §5, §6, §7, §8 | Profil motoru | SR-SEC-* |
| BRD §8.5 (PCI kart verisi dışlama) | `cp.sector.pci_in_scope` | DTMF masking/aktarım | (F3) |
| SAD §12.3 / NFR 10.7 (residency) | `cp.residency.*` | Region pinning, KMS | SR-LOC-001/002/003 |
| FR-REC-006/007/010 (retention/legal hold/silme) | `cp.retention.*` | Retention motoru | SR-REC-006/007/010 |
| FR-LLM-012 / FR-KB-010 (no-train, provider log) | §D3, `cp.residency.provider_region_pinning` | Adapter region + no-train | SR-LLM-012 |
| FR-IAM-005/006 (maker-checker, WORM audit) | §8 override kuralı, §3 | Override audit | SR-IAM-005/006 |
| FR-IAM-009/010 + ADR-013 (break-glass, regüle onay) | §2 controller-processor | Üç katmanlı break-glass | SR-IAM-009/010 |

**Yeni ADR önerisi (opsiyonel):** Compliance profile motorunun **config-driven, most-restrictive-wins, tenant-override-yalnız-sıkılaştırır** tasarımı bir mimari karar olarak kayda alınabilir. THREAT_MODEL ADR-014..017 önerilerinin ardından **ADR-018 — "Config-driven compliance profile resolution"** olarak açılması önerilir (numaralandırma çakışmasını önlemek için ADR kayıt sürecinde — WBS 0.1.8 — kesinleştirilir).

---

## 11. Doğrulama (test eşlemesi)

| Test alanı | Doğrulanan | İlgili TC/WBS |
|------------|-----------|----------------|
| Outbound consent/opt-out | Consent Engine her `cp.outbound.*` profiliyle dial'ı doğru bloke/izin verir | TC-OUT-003/006, WBS 18.12, 10.2 |
| Arama saati | Yerel pencere dışı arama engellenir (TR/UK/EU/ME) | TC-TEL-013, WBS 10.2.3 |
| Residency | Home-region dışına kayıt/transkript/provider içeriği gitmez | TC-LOC-001/002, WBS 18.9 (izolasyon), 1.2.2 |
| Retention/silme | Süre sonunda geri-döndürülemez silme; legal hold geçersiz kılar | TC-REC-006/007/010, WBS 1.2.3/1.2.4 |
| AI şeffaflık | EU profili çağrı başı bildirimi zorunlu üretir | TC-LLM-006, WBS 17.2.3 |
| DPIA gate | `require_dpia=true` tenant DPIA tamamlanmadan production'a geçemez | Onboarding test, §3 |
| Profil çözümleme | most-restrictive-wins; tenant override yalnız sıkılaştırır + audit'li | Birim test (resolver), §8 |
| PII redaction | Kalıcı saklama öncesi kart/parola/OTP çıkarılır | TC-REC-004/005, WBS 11.4/11.5, 18.11 |

---

## 12. Açık Kararlar ve Sonraki Adımlar

| # | Açık karar | Bağımlılık |
|---|-----------|------------|
| 1 | **Hukuki doğrulama:** Tüm `PROFILE-*` değerleri (özellikle calling_hours, consent_model, breach deadline) ülke counsel'i ile teyit edilmeli. | Production öncesi zorunlu |
| 2 | **ME alt-ülke seçimi:** İlk hedef ME ülkesi (UAE/KSA/Qatar/...) ve buna bağlı `PROFILE-ME-<kod>` netleşmeli; data localization gereksinimi residency mimarisini etkiler. | BRD §22 (ilk ülke), SAD §12.3 |
| 3 | **Retention varsayılanları:** `cp.retention.*` gün değerleri BRD §22 "retention süreleri" açık kararına bağlı; şimdilik muhafazakâr şablon. | BRD §22, FR-REC-006 |
| 4 | **TR home-region:** TR tenant'ları için EU mi yerel ME/TR bölgesi mi (data localization beklentisi) kararı. | SAD §12.3, NFR 10.7 |
| 5 | **ADR-018 numarası:** Compliance profile resolution ADR'ı, THREAT_MODEL'in önerdiği ADR-014..017 ile birlikte ADR kayıt sürecinde (WBS 0.1.8) kesinleştirilmeli. | WBS 0.1.8 |
| 6 | **Sektörel overlay derinliği:** PCI/FCA/HIPAA/DORA/NIS2 tam kontrol haritası Faz 3'te (WBS 17.2.5/6) detaylandırılacak. | F3 |

**Sonraki doküman (sıradaki WBS):** 0.1.7 `.docx` üretim hattı operasyonelleştirme → Faz 1 kod. Bu doküman `docs/build-docx.sh` ile markalı `.docx`'e dönüştürülecek (`.md` source of truth).
