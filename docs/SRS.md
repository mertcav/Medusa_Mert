# Sistem Gereksinimleri Spesifikasyonu (SRS)
## Kurumsal Sesli Yapay Zekâ Asistanı Platformu — Enterprise Voice AI Agent Platform

**Yüksek Hızlı · Düşük Kaynak Tüketimli (High-Density, Lean Runtime)**
STT · LLM · TTS Gerçek Zamanlı Orkestrasyonu
Inbound & Outbound | Multi-Tenant | Vendor-Neutral | Human Handoff

> RMC TECHNOLOGY & CONSULTANCY — rmctech.co.uk

---

## Doküman Bilgileri

| Alan | Değer |
|------|-------|
| Doküman Adı | Kurumsal Sesli Yapay Zekâ Asistanı Platformu — Sistem Gereksinimleri Spesifikasyonu |
| Doküman Tipi | System Requirements Specification (SRS) |
| Hedef Ürün | Multi-Tenant Enterprise Voice AI Agent Platform |
| Kaynak Dokümanlar | `docs/BRD.md` (v2.1) · `docs/SAD.md` (v1.1) |
| Amaç | BRD'deki FR/NFR'leri **doğrulanabilir (testable)** sistem gereksinimlerine indirgemek |
| Sürüm | 1.0 |
| Tarih | 13 Haziran 2026 |
| Durum | İncelemeye Hazır |
| Gizlilik | Gizli — Yalnızca yetkili paydaşlar |

### Sürüm Geçmişi

| Sürüm | Tarih | Açıklama |
|-------|-------|----------|
| 1.0 | 13.06.2026 | İlk sürüm. BRD §9 (FR) ve §10 (NFR) tüm alanları doğrulanabilir sistem gereksinimlerine (`SR-*`) indirildi; her SR için kaynak FR/NFR, doğrulama yöntemi (T/A/I/D) ve ölçülebilir kabul ölçütü tanımlandı. BRD §19 kabul kriterleri SRS doğrulama kapısına bağlandı. WBS 0.1.1. |

---

## İçindekiler

1. [Giriş](#1-giriş)
2. [SR-ID Şeması, Doğrulama Yöntemleri ve Öncelik](#2-sr-id-şeması-doğrulama-yöntemleri-ve-öncelik)
3. [Sistem Bağlamı ve Genel Görünüm](#3-sistem-bağlamı-ve-genel-görünüm)
4. [Fonksiyonel Sistem Gereksinimleri](#4-fonksiyonel-sistem-gereksinimleri)
   - 4.1 Tenant & Organizasyon (SR-TEN)
   - 4.2 IAM, RBAC & Break-glass (SR-IAM)
   - 4.3 Agent Yaşam Döngüsü (SR-AGT)
   - 4.4 Telefoni & Çağrı Yönetimi (SR-TEL)
   - 4.5 Gerçek Zamanlı Konuşma Motoru (SR-RTC)
   - 4.6 STT (SR-STT)
   - 4.7 TTS (SR-TTS)
   - 4.8 LLM Orkestrasyonu (SR-LLM)
   - 4.9 Bilgi Tabanı & RAG (SR-KB)
   - 4.10 Tool & Entegrasyon (SR-TOOL)
   - 4.11 Çağrı-içi Kimlik Doğrulama (SR-AUTH)
   - 4.12 İnsan Temsilciye Aktarım (SR-HND)
   - 4.13 Outbound & Kampanya & Consent (SR-OUT)
   - 4.14 Kayıt, Transkript & PII (SR-REC)
   - 4.15 Analitik & Kalite (SR-ANA)
   - 4.16 Test & Simülasyon (SR-TST)
   - 4.17 Faturalama & Kullanım (SR-BIL)
   - 4.18 Kaynak Verimliliği (SR-RES)
5. [Fonksiyonel Olmayan Sistem Gereksinimleri](#5-fonksiyonel-olmayan-sistem-gereksinimleri)
   - 5.1 Performans & Gecikme (SR-PERF)
   - 5.2 Kaynak Verimliliği / Density (SR-DEN)
   - 5.3 Ölçeklenebilirlik (SR-SCAL)
   - 5.4 Kullanılabilirlik (SR-AVL)
   - 5.5 Felaket Kurtarma (SR-DR)
   - 5.6 Güvenlik (SR-SEC)
   - 5.7 Veri Yerleşimi / Residency (SR-LOC)
6. [Arayüz ve Veri Gereksinimleri](#6-arayüz-ve-veri-gereksinimleri)
7. [Doğrulama ve Kabul Kapısı (BRD §19 Eşlemesi)](#7-doğrulama-ve-kabul-kapısı-brd-19-eşlemesi)
8. [İzlenebilirlik Özeti](#8-i̇zlenebilirlik-özeti)
9. [Varsayımlar, Bağımlılıklar ve Açık Kararlar](#9-varsayımlar-bağımlılıklar-ve-açık-kararlar)
10. [Sonuç ve Sonraki Adımlar](#10-sonuç-ve-sonraki-adımlar)

---

## 1. Giriş

### 1.1 Amaç
Bu doküman, BRD'de (v2.1) iş seviyesinde tanımlanan fonksiyonel (FR) ve fonksiyonel olmayan (NFR)
gereksinimleri, mühendislik ve test ekiplerinin doğrudan **doğrulayabileceği (verifiable)** sistem
gereksinimlerine indirir. Her sistem gereksinimi (`SR-*`) tek bir gözlemlenebilir davranışı, ölçülebilir
bir kabul ölçütüyle ve bir doğrulama yöntemiyle ifade eder.

### 1.2 Kapsam
SRS, BRD §9 (tüm FR alt-alanları) ve §10 (tüm NFR alanları) kapsamındaki gereksinimleri ele alır.
Mimari "nasıl" kararları SAD'de (v1.1) tutulur; SRS yalnız doğrulanabilir "ne" beyanını üretir.
Ekran/panel ayrıntıları BRD §17'de, veri varlıkları BRD §16'da; bunlara yalnız referans verilir.

### 1.3 Hedef Kitle
Mimari, backend/data-plane, frontend, QA/test otomasyonu, SRE ve güvenlik/uyumluluk ekipleri;
izlenebilirlik matrisi (WBS 0.1.2) ve test-case kataloğu bu dokümandan türetilir.

### 1.4 Tanımlar ve Kısaltmalar
BRD §23 (Sözlük) esastır. Bu dokümanda ek olarak: **EoU** = end-of-utterance (konuşma sonu);
**SUT** = system under test; **AMD** = answering machine detection; **DNC** = do-not-call.

### 1.5 Referanslar
- `docs/BRD.md` v2.1 — iş gereksinimleri (FR/NFR kaynağı; çelişkide **esastır**).
- `docs/SAD.md` v1.1 — çözüm mimarisi, ADR'ler, gecikme bütçesi (§20).
- `docs/todo_list.md` — WBS; bu doküman görev **0.1.1**'dir.

> **Çelişki kuralı:** Bir SR ile BRD/SAD arasında çelişki olursa BRD/SAD esastır; SR düzeltilir ve
> sürüm geçmişi güncellenir (CLAUDE.md kuralı).

---

## 2. SR-ID Şeması, Doğrulama Yöntemleri ve Öncelik

### 2.1 SR-ID şeması
Sistem gereksinimleri `SR-<ALAN>-NNN` biçiminde numaralandırılır. `<ALAN>` kodu, izlenebilirliği
görünür kılmak için BRD FR/NFR alanlarını birebir yansıtır (ör. `SR-RTC-007` → `FR-RTC-002`).
Numaralandırma alan içinde sıralıdır; **mevcut FR-ID şeması korunur**, SR'ler ayrı bir uzaydadır.

### 2.2 Doğrulama yöntemleri
Her SR'ye bir birincil doğrulama yöntemi atanır:

| Kod | Yöntem | Açıklama |
|-----|--------|----------|
| **T** | Test | Otomatik/manuel test (unit · integration · e2e · load · security). |
| **D** | Demonstration | Çalışan sistemde senaryo gösterimi (canlı/uçtan uca akış). |
| **A** | Analysis | Log/trace/metrik analizi, hesaplama veya model incelemesi. |
| **I** | Inspection | Kod, konfigürasyon, şema veya doküman incelemesi. |

### 2.3 Öncelik
MoSCoW (BRD §9): **Must / Should / Could**. Öncelik kaynak FR/NFR'den devralınır.

### 2.4 Her SR'nin yapısı
`ID | Sistem Gereksinimi (gözlemlenebilir, ölçülebilir) | Kaynak (FR/NFR) | Yöntem | Kabul Ölçütü / Eşik`.
"Kabul Ölçütü" sütunu, bir test-case'in **geçti/kaldı** kararını verebileceği nesnel eşiği içerir.

---

## 3. Sistem Bağlamı ve Genel Görünüm

Sistem, BRD §11 ve SAD §4-5'teki katmanlı mimariyi izler: Telephony Edge/SBC → Real-Time Media
Gateway (VAD/STT/TTS) → **Conversation Orchestrator (çekirdek IP)** → Enterprise Integration Layer;
kesişen servisler: IAM, Tenant Mgmt, Audit, Observability, Analytics, Recording, Billing, Consent,
Compliance, Resource Manager. Üç panel düzlemi (L0/L1/L2) BRD §17 ve SAD §14.4'tedir.

SRS, bu bileşenlerin **dış gözlemlenebilir** davranışını şart koşar; bileşen iç tasarımı SAD'dedir.

---

## 4. Fonksiyonel Sistem Gereksinimleri

### 4.1 Tenant & Organizasyon (SR-TEN) — BRD §9.1

| ID | Sistem Gereksinimi | Kaynak | Yöntem | Kabul Ölçütü / Eşik |
|----|--------------------|--------|--------|---------------------|
| SR-TEN-001 | Platform aynı anda ≥2 tenant'ı bağımsız konfigürasyon ile barındırır; bir tenant'ın çağrı/agent/config işlemleri diğerini etkilemez. | FR-TEN-001 | D | 2 tenant paralel çalışır; biri durdurulduğunda diğeri kesintisiz devam eder. |
| SR-TEN-002 | Tüm tenant-kapsamlı tablolarda `tenant_id` zorunludur; sorgular RLS ile tenant'a kısıtlanır. Cross-tenant okuma/yazma denemesi 0 sonuç döndürür/reddedilir. | FR-TEN-002 | T | Cross-tenant erişim testi (18.9) %100 reddedilir; RLS olmadan tek satır dahi dönmez. |
| SR-TEN-003 | Tenant altında marka/departman/ülke/proje hiyerarşisi oluşturulabilir ve agent/kampanya bu birimlere atanabilir. | FR-TEN-003 | T | Org birimi CRUD başarılı; atanan kaynak yalnız ilgili scope'ta görünür. |
| SR-TEN-004 | Tenant bazında dil, saat dilimi, veri bölgesi ve saklama politikası seçilebilir ve runtime'a uygulanır. | FR-TEN-004 | T | Seçilen bölge/saklama değeri ilgili çağrı verisine yansır (bkz. SR-LOC-001, SR-REC-006). |
| SR-TEN-005 | Tenant `dedicated` veya `shared` modunda sağlanabilir; mod tenant kaydında izlenebilir. | FR-TEN-005 | I | Provisioning her iki modu üretir; izolasyon modeli ADR-006 ile uyumludur. |
| SR-TEN-006 | Tenant bazında eş zamanlı çağrı ve CPS kotası tanımlanır; kota aşıldığında yeni çağrı kontrollü reddedilir. | FR-TEN-006 | T | Kota=N iken (N+1). çağrı reddedilir; ret nedeni kodlanır (bkz. SR-TEL-012). |
| SR-TEN-007 | Tenant kaynak kotası (vCPU/bellek/eşzamanlılık) tanımlanır; aşım engellenir ve alarmlanır. | FR-TEN-007 | T | Yük testinde kota tavanında admission control devreye girer; başka tenant etkilenmez. |

### 4.2 IAM, RBAC & Break-glass (SR-IAM) — BRD §9.2, §17

| ID | Sistem Gereksinimi | Kaynak | Yöntem | Kabul Ölçütü / Eşik |
|----|--------------------|--------|--------|---------------------|
| SR-IAM-001 | Yetki kararı her zaman backend'de RBAC ile verilir; rol→permission-key (`kaynak:eylem`) bundle'ı ile erişim değerlendirilir. | FR-IAM-001, FR-IAM-011 | T | Yetkisiz `permission-key` için API 403; frontend gizlemesi tek başına yeterli sayılmaz. |
| SR-IAM-002 | SAML 2.0 ve OIDC ile kurumsal SSO ile oturum açılabilir. | FR-IAM-002 | T | Her iki protokolle başarılı login; IdP claim'leri oturuma yansır. |
| SR-IAM-003 | Ayrıcalıklı roller için MFA zorunlu kılınabilir. | FR-IAM-003 | T | MFA açıkken faktörsüz erişim reddedilir. |
| SR-IAM-004 | Agent oluşturma, yayınlama ve canlı çağrı izleme yetkileri ayrı permission-key'lerdir. | FR-IAM-004 | I | İzleme yetkisi olan kullanıcı yayın yapamaz; permission kataloğu (12.1.2) ayrımı içerir. |
| SR-IAM-005 | Kritik değişiklikler maker-checker onayı gerektirir (talep eden ≠ onaylayan). | FR-IAM-005 | T | Aynı kullanıcı hem talep hem onay yapamaz; onaysız değişiklik canlıya çıkmaz. |
| SR-IAM-006 | Tüm kullanıcı işlemleri append-only (WORM) audit log'a yazılır; kayıt değiştirilemez/silinemez. | FR-IAM-006 | T | Kayıt güncelleme/silme denemesi reddedilir; bütünlük (hash/zincir) doğrulanır. |
| SR-IAM-007 | SCIM ile kullanıcı provisioning ve IdP grup→rol eşlemesi yapılabilir. | FR-IAM-007 | T | SCIM create/update/deactivate IdP'den senkronize olur. |
| SR-IAM-008 | L0 (platform) rolleri tenant rollerinden bağımsızdır ve tenant iş içeriğine (kayıt/transkript/PII) **varsayılan erişemez**; L0 yalnız metrik/kaynak verisi görür. | FR-IAM-008 | T | L0 kullanıcısı break-glass olmadan transkript/kayıt/PII endpoint'ine eriştiğinde 403. |
| SR-IAM-009 | Tenant iş içeriğine L0 erişimi yalnız üç katmanlı break-glass ile olur: Tier A (metrik/log, PII'siz) break-glass'sız; Tier B maker-checker + time-boxed (default 60 dk, max 4 sa, oto-sonlanma, standing access yok) + zorunlu gerekçe kodu + tenant `security_compliance_officer`+`tenant_owner` bildirimi. | FR-IAM-009 | T | Tier B token süresi dolunca erişim otomatik kapanır; gerekçe kodu zorunlu; bildirim üretilir; tüm erişim audit'te. |
| SR-IAM-010 | Regüle tenant'larda Tier B için `require_tenant_approval` toggle bulunur; regulated profile'da varsayılan açıktır ve DPA'ya bağlanır (controller=tenant, processor=RMC). | FR-IAM-010 | I | Regulated profile'da toggle default=on; onaysız Tier B erişimi başlatılamaz. |
| SR-IAM-011 | Roller immutable permission bundle'dır; esneklik yalnız atama scope filtresiyle (departman/marka/kampanya) sağlanır; v1'de custom permission-builder yoktur. | FR-IAM-011 | I | Custom permission oluşturma arayüzü/uç yoktur; scoped assignment çalışır (bkz. ADR-012). |

### 4.3 Agent Yaşam Döngüsü (SR-AGT) — BRD §9.3

| ID | Sistem Gereksinimi | Kaynak | Yöntem | Kabul Ölçütü / Eşik |
|----|--------------------|--------|--------|---------------------|
| SR-AGT-001 | Kullanıcı kod yazmadan, panel üzerinden çalışır bir agent oluşturabilir. | FR-AGT-001 | D | Kod yazmadan oluşturulan agent test çağrısını tamamlar. |
| SR-AGT-002 | Agent için isim, amaç, kişilik, dil ve iş kuralları tanımlanabilir ve runtime davranışına yansır. | FR-AGT-002 | T | Tanımlanan dil/kişilik çağrıda gözlemlenir. |
| SR-AGT-003 | Single-prompt ve node/flow tabanlı konuşma modelleri çalıştırılabilir. | FR-AGT-003 | T | Her iki model tipi de uçtan uca çağrı yürütür. |
| SR-AGT-004 | Prompt ve workflow versiyonlanır; her sürüm ayırt edilebilir ve geri çağrılabilir. | FR-AGT-004 | I | Sürüm geçmişi ve sürüm kimliği görüntülenir. |
| SR-AGT-005 | Draft/test/staging/production ortamları ayrıdır; bir ortamdaki değişiklik diğerini etkilemez. | FR-AGT-005 | D | Draft değişikliği production çağrısını etkilemez. |
| SR-AGT-006 | Yayınlanan sürüm tek işlemle önceki sürüme döndürülebilir (rollback). | FR-AGT-006 | T | Rollback sonrası canlı agent önceki sürümle davranır; BRD §19 (15) geçer. |
| SR-AGT-007 | Agent'ın aktif olacağı numara, kampanya ve saatler tanımlanır ve uygulanır. | FR-AGT-007 | T | Tanım dışı saat/numara çağrısı agent'a yönlenmez. |
| SR-AGT-008 | Segment bazlı agent varyasyonları oluşturulabilir. | FR-AGT-008 | T | Aynı agent'ın varyasyonu segmente göre seçilir. |
| SR-AGT-009 | Global ve tenant seviyesinde güvenlik politikaları agent davranışına uygulanır (politika her ikisinde de zorlanır). | FR-AGT-009 | T | Global yasak + tenant yasağı her ikisi de bloklanır (bkz. SR-LLM-009). |
| SR-AGT-010 | Değişiklik production'a alınmadan önce otomatik testlerden geçer; eşik altı sonuç yayını engeller. | FR-AGT-010 | T | Eşik altı regression sonucu yayını bloklar (bkz. SR-TST-005). |

### 4.4 Telefoni & Çağrı Yönetimi (SR-TEL) — BRD §9.4

| ID | Sistem Gereksinimi | Kaynak | Yöntem | Kabul Ölçütü / Eşik |
|----|--------------------|--------|--------|---------------------|
| SR-TEL-001 | Inbound ve outbound PSTN çağrıları kurulup sonlandırılabilir. | FR-TEL-001 | D | Her iki yönde çağrı tamamlanır (BRD §19 (5)). |
| SR-TEL-002 | SIP trunk ve BYOC bağlantısı; sağlayıcıdan bağımsız medya akışı (≥2 telephony adapter) desteklenir. | FR-TEL-002 | T | ≥2 sağlayıcı ile çağrı; sağlayıcı değişimi kod değişikliği gerektirmez. |
| SR-TEL-003 | Avaya/Genesys/Cisco/Amazon Connect benzeri CC sistemleriyle entegrasyon yapılabilir. | FR-TEL-003 | D | En az bir CC entegrasyonu uçtan uca doğrulanır. |
| SR-TEL-004 | Tüm telefon numaraları E.164 formatında normalize edilir ve saklanır. | FR-TEL-004 | T | Çeşitli giriş formatları tek E.164 değerine normalize olur. |
| SR-TEL-005 | Caller ID ve numara havuzu yönetilebilir; giden çağrıda doğru Caller ID kullanılır. | FR-TEL-005 | T | Atanan Caller ID çağrıda gözlemlenir. |
| SR-TEL-006 | DTMF gönderme ve algılama (RFC 2833 / SIP INFO) çalışır. | FR-TEL-006 | T | Gönderilen/alınan DTMF basamakları doğru tespit edilir. |
| SR-TEL-007 | Cold, warm ve whisper transfer desteklenir. | FR-TEL-007 | D | Üç transfer tipi de başarıyla tamamlanır (BRD §19 (6) cold+warm). |
| SR-TEL-008 | Kuyruk/skill/departman bazlı aktarım hedefi seçilebilir. | FR-TEL-008 | T | Aktarım doğru kuyruğa/skill grubuna yönlenir. |
| SR-TEL-009 | Çağrı düşmesinde kontrollü retry veya geri arama oluşturulabilir. | FR-TEL-009 | T | Düşme sonrası yapılandırılan retry/callback üretilir, sınır aşılmaz. |
| SR-TEL-010 | Answering machine detection (AMD) yapılabilir. | FR-TEL-010 | T | İnsan/makine ayrımı doğruluğu hedef eşiğin üzerindedir. |
| SR-TEL-011 | Voicemail mesajı bırakılabilir. | FR-TEL-011 | D | AMD=makine senaryosunda voicemail bırakılır. |
| SR-TEL-012 | Çağrı başlangıç/bitiş nedenleri standart taksonomi koduyla kaydedilir. | FR-TEL-012 | I | Her çağrı kaydında standart neden kodu vardır. |
| SR-TEL-013 | Outbound arama saatleri ülke/müşteri bazında sınırlanır; izinli saat dışı arama yapılmaz. | FR-TEL-013 | T | Saat-dışı denemesi engellenir (bkz. SR-OUT-004). |
| SR-TEL-014 | Do-not-call ve opt-out listeleri arama anında gerçek zamanlı kontrol edilir. | FR-TEL-014 | T | DNC'deki numaraya çağrı başlatılmaz; %100 bloklama. |
| SR-TEL-015 | Silent/abandoned call'u önleyici kapasite kontrolü uygulanır. | FR-TEL-015 | T | Kapasite < kampanya hızı iken abandoned oranı yapılandırılan eşik altında kalır (bkz. SR-OUT-007). |

### 4.5 Gerçek Zamanlı Konuşma Motoru (SR-RTC) — BRD §9.5

| ID | Sistem Gereksinimi | Kaynak | Yöntem | Kabul Ölçütü / Eşik |
|----|--------------------|--------|--------|---------------------|
| SR-RTC-001 | Ses paketleri streaming işlenir; tam buffering yapılmaz. | FR-RTC-001, FR-RES-002 | A | Pipeline'da tam-tampon yok; ilk işlem ilk paketlerle başlar. |
| SR-RTC-002 | Barge-in algılanır ve agent TTS'i ≤200 ms içinde durdurulur. | FR-RTC-002 | T | EoU/barge-in→TTS kesme P95 ≤ 200 ms (bkz. SR-PERF-004). |
| SR-RTC-003 | Kullanıcı konuşurken sistem gereksiz ara yanıt vermez. | FR-RTC-003 | T | Kullanıcı konuşurken yanıt başlatılmaz (false-trigger oranı eşik altı). |
| SR-RTC-004 | Sessizlik/tereddüt/konuşma sonu (endpointing) dinamik algılanır. | FR-RTC-004 | T | Endpointing gecikmesi senaryo eşiklerinde; erken/geç kesme oranı sınırlı. |
| SR-RTC-005 | Arka plan gürültüsü ve hat kalitesi düşüşü yönetilir. | FR-RTC-005 | T | Gürültülü test setinde (18.7) WER artışı eşik altında. |
| SR-RTC-006 | Yankı ve agent'ın kendi sesi tekrar transkribe edilmez (echo/self-transcription önleme). | FR-RTC-006 | T | Agent konuşurken kendi sesi STT'ye girmez. |
| SR-RTC-007 | "Evet/hı hı/bir dakika" gibi kısa ifadeler doğru yorumlanır. | FR-RTC-007 | T | Backchannel ifadeleri yanlış turn başlatmaz. |
| SR-RTC-008 | Konuşma hızı, ses seviyesi ve bekleme süresi ayarlanabilir ve uygulanır. | FR-RTC-008 | T | Ayar değişikliği çağrı sesinde gözlemlenir. |
| SR-RTC-009 | Sayı/tarih/para/adres/kod yerel dile uygun okunur. | FR-RTC-009 | T | Yerelleştirme test seti %100 beklenen biçimde okunur. |
| SR-RTC-010 | Anlaşılmadığında kontrollü tekrar stratejisi uygulanır. | FR-RTC-010 | T | N kez anlamama senaryosunda tanımlı strateji çalışır. |
| SR-RTC-011 | Belirli sayıda üst üste anlamamada insan temsilciye aktarılır. | FR-RTC-011 | T | Eşik aşımında handoff tetiklenir (bkz. SR-HND-002). |
| SR-RTC-012 | Konuşma sırasında dil otomatik değiştirilebilir. | FR-RTC-012 | T | Dil değişimi sonrası STT/TTS doğru dilde sürer. |
| SR-RTC-013 | VAD/endpointing edge/medya katmanında yapılır; ölü hava STT/LLM'e gönderilmez. | FR-RTC-013, FR-RES-009 | A | Dead-air sırasında STT/LLM çağrısı üretilmez; çağrı sayısı düşer. |

### 4.6 STT (SR-STT) — BRD §9.6

| ID | Sistem Gereksinimi | Kaynak | Yöntem | Kabul Ölçütü / Eşik |
|----|--------------------|--------|--------|---------------------|
| SR-STT-001 | ≥2 STT sağlayıcısı adapter SPI arkasında desteklenir. | FR-STT-001 | T | İki sağlayıcı ile transkripsiyon (BRD §19 (1)). |
| SR-STT-002 | Streaming partial ve final transcript alınır. | FR-STT-002 | T | Partial'lar akışta gelir; final tek ve kararlıdır. |
| SR-STT-003 | Dil ve lehçe konfigüre edilebilir (en az EN+TR). | FR-STT-003 | T | Seçilen dil/lehçe transkripsiyona uygulanır. |
| SR-STT-004 | Domain-specific vocabulary ve phrase boosting desteklenir. | FR-STT-004 | T | Boost edilen terimlerin tanıma doğruluğu artar (öncesi/sonrası karşılaştırma). |
| SR-STT-005 | Telefon no/plaka/poliçe/referans alanları optimize tanınır. | FR-STT-005 | T | Yapısal alan test setinde karakter hata oranı eşik altında. |
| SR-STT-006 | Her transkript segmenti confidence score üretir. | FR-STT-006 | I | Çıktıda confidence alanı bulunur. |
| SR-STT-007 | Düşük confidence'ta teyit istenir. | FR-STT-007 | T | Confidence < eşik → teyit turu tetiklenir. |
| SR-STT-008 | STT sağlayıcısı hata/timeout verdiğinde ikincile fallback yapılır. | FR-STT-008 | T | Birincil zorla kesildiğinde çağrı ikincil STT ile sürer (BRD §19 (4)). |

### 4.7 TTS (SR-TTS) — BRD §9.7

| ID | Sistem Gereksinimi | Kaynak | Yöntem | Kabul Ölçütü / Eşik |
|----|--------------------|--------|--------|---------------------|
| SR-TTS-001 | ≥2 TTS sağlayıcısı desteklenir. | FR-TTS-001 | T | İki sağlayıcı ile sentez (BRD §19 (2)). |
| SR-TTS-002 | TTS ilk ses paketi streaming başlar (low first-byte). | FR-TTS-002 | T | First-byte gecikmesi gecikme bütçesinde (SAD §20). |
| SR-TTS-003 | Dil/aksan/konuşma hızı/ton seçilebilir. | FR-TTS-003 | T | Seçilen parametreler çıktı sesinde gözlemlenir. |
| SR-TTS-004 | Sayı/tarih/para/özel isim için pronunciation dictionary uygulanır. | FR-TTS-004 | T | Sözlük girdileri beklenen telaffuzu üretir. |
| SR-TTS-005 | TTS çıktısı barge-in'de anında kesilir. | FR-TTS-005 | T | Kesme ≤200 ms (bkz. SR-RTC-002). |
| SR-TTS-006 | Onaylı özel/klonlanmış sesler kullanılabilir. | FR-TTS-006 | D | Onaylı ses seçilip çağrıda kullanılır. |
| SR-TTS-007 | Ses klonlama için ses sahibi açık izni ve kullanım kaydı tutulur. | FR-TTS-007 | I | İzin/onay kaydı olmadan klon ses etkinleştirilemez. |
| SR-TTS-008 | Bir TTS sağlayıcısı çalışmazsa alternatife geçilir. | FR-TTS-008 | T | Birincil kesilince ikincil TTS devreye girer. |
| SR-TTS-009 | Çağrı boyunca ses karakteri tutarlı kalır (fallback'te dahil). | FR-TTS-009 | A | Fallback sonrası ses karakteri tutarlılık kontrolünü geçer. |
| SR-TTS-010 | Statik/standart anonslar önbelleğe alınır; tekrar sentez maliyeti önlenir. | FR-TTS-010, FR-RES-003 | A | Statik anons TTS cache hit ≥ %80 (bkz. SR-DEN-004). |

### 4.8 LLM Orkestrasyonu (SR-LLM) — BRD §9.8

| ID | Sistem Gereksinimi | Kaynak | Yöntem | Kabul Ölçütü / Eşik |
|----|--------------------|--------|--------|---------------------|
| SR-LLM-001 | ≥2 LLM sağlayıcısı ve birden çok model desteklenir. | FR-LLM-001 | T | İki sağlayıcı ile yanıt (BRD §19 (3)). |
| SR-LLM-002 | Tenant/use-case bazında model seçilebilir/override edilebilir. | FR-LLM-002 | T | Override edilen model ilgili çağrılarda kullanılır. |
| SR-LLM-003 | Model routing maliyet/gecikme/dil/risk girdilerine göre yapılır. | FR-LLM-003 | A | Router kararı girdilere göre deterministik/açıklanabilir loglanır. |
| SR-LLM-004 | LLM çağrıları streaming token yanıtı kullanır. | FR-LLM-004 | A | İlk token streaming gelir; tam yanıt beklenmez. |
| SR-LLM-005 | Konuşma geçmişi token sınırına göre özetlenir. | FR-LLM-005, FR-RES-010 | T | Sınır aşımında özetleme tetiklenir; bağlam korunur. |
| SR-LLM-006 | System prompt kullanıcı konuşması veya KB içeriğiyle değiştirilemez. | FR-LLM-006 | T | Prompt-override denemesi system prompt'u değiştirmez. |
| SR-LLM-007 | Prompt injection ve jailbreak kontrolleri uygulanır (input guard). | FR-LLM-007 | T | Injection test seti kritik veri sızdırmaz (BRD §19 (8)). |
| SR-LLM-008 | Kritik işlemler serbest metin yerine schema-doğrulamalı tool çağrılarıyla yapılır. | FR-LLM-008 | T | Schema dışı tool çağrısı reddedilir. |
| SR-LLM-009 | Model cevabı politika motorundan (output guard) geçirilir (BRD §13 yasak işlemler). | FR-LLM-009 | T | Yasak içerik üretimi bloklanır/yeniden yazdırılır. |
| SR-LLM-010 | Model hata verdiğinde fallback model veya deterministic flow kullanılır. | FR-LLM-010 | T | Birincil model kesilince çağrı fallback ile sürer. |
| SR-LLM-011 | Model seçimi + versiyon + token kullanımı çağrı bazında kaydedilir. | FR-LLM-011 | I | Her çağrı kaydında model/versiyon/token alanları bulunur. |
| SR-LLM-012 | Tenant verisinin model eğitiminde kullanımı varsayılan kapalıdır (no-train). | FR-LLM-012 | I | Adapter çağrıları no-train bayrağı/endpoint ile yapılır; default off. |
| SR-LLM-013 | Basit/rutin turlar küçük/hızlı modele yönlenir; büyük model yalnız gerektiğinde (model tiering). | FR-LLM-013, FR-RES-005 | A | Küçük-modelle karşılanan tur oranı ≥ %60 hedef (bkz. SR-DEN-005). |
| SR-LLM-014 | Tekrarlayan, yan-etkisiz sorular için semantic cache LLM çağrısını azaltır; PII cache'lenmez. | FR-LLM-014, FR-RES-004 | T | Cache hit'te LLM çağrılmaz; PII içeren tur cache'e yazılmaz. |

### 4.9 Bilgi Tabanı & RAG (SR-KB) — BRD §9.9

| ID | Sistem Gereksinimi | Kaynak | Yöntem | Kabul Ölçütü / Eşik |
|----|--------------------|--------|--------|---------------------|
| SR-KB-001 | PDF/Word/HTML/metin/CSV/web sayfası yüklenip ingest edilir. | FR-KB-001 | T | Her format başarıyla parse+index edilir. |
| SR-KB-002 | SharePoint/Confluence vb. kurumsal kaynaklara bağlanılabilir. | FR-KB-002 | D | En az bir kurumsal connector senkronize eder. |
| SR-KB-003 | Kaynaklar otomatik parçalanır, indekslenir ve versiyonlanır. | FR-KB-003 | I | Chunk/index üretilir; yeniden ingest sürüm üretir. |
| SR-KB-004 | Tenant ve agent bazında ayrı bilgi tabanı/namespace kullanılır. | FR-KB-004 | T | Bir agent'ın retrieval'i başka agent/tenant namespace'ini görmez. |
| SR-KB-005 | Doküman bazında erişim yetkisi uygulanır. | FR-KB-005 | T | Yetkisiz dokümandan retrieval sonucu dönmez. |
| SR-KB-006 | Yanıtın hangi kaynağa dayandığı (source attribution) izlenebilir. | FR-KB-006 | I | Yanıt kayıtlarında kaynak atfı bulunur. |
| SR-KB-007 | Kaynak bulunamadığında agent bilgi uydurmaz; teyit/aktar/ticket yoluna gider. | FR-KB-007 | T | Kaynaksız soruda halüsinasyon üretilmez; tanımlı fallback davranışı. |
| SR-KB-008 | Güncelliğini yitirmiş içerik otomatik işaretlenir (content TTL). | FR-KB-008 | T | TTL aşan içerik "stale" işaretlenir. |
| SR-KB-009 | Soru-cevap performansı benchmark veri setiyle ölçülür. | FR-KB-009 | T | KB Q&A benchmark skoru hedef eşiğin üzerinde. |
| SR-KB-010 | Hassas dokümanlar genel modellerin sağlayıcı loglarında tutulmaz. | FR-KB-010 | I | Hassas içerik no-retention/no-log adapter yolu ile işlenir. |
| SR-KB-011 | Retrieval top-k + token trimming ile bağlam maliyeti sınırlanır. | FR-KB-011, FR-RES-010 | A | Bağlam token'ı yapılandırılan tavanı aşmaz. |

### 4.10 Tool & Entegrasyon (SR-TOOL) — BRD §9.10

| ID | Sistem Gereksinimi | Kaynak | Yöntem | Kabul Ölçütü / Eşik |
|----|--------------------|--------|--------|---------------------|
| SR-TOOL-001 | REST/SOAP/GraphQL/webhook entegrasyonları desteklenir. | FR-TOOL-001 | T | Her connector tipi başarılı çağrı yapar. |
| SR-TOOL-002 | Tool input/output JSON schema ile doğrulanır. | FR-TOOL-002 | T | Schema dışı veri reddedilir. |
| SR-TOOL-003 | Timeout, retry (backoff+jitter), circuit breaker uygulanır. | FR-TOOL-003 | T | Bağımlılık hatasında devre açılır; kontrolsüz retry yok. |
| SR-TOOL-004 | Tool yetkileri agent bazında sınırlanır. | FR-TOOL-004 | T | Agent scope dışı tool çağıramaz. |
| SR-TOOL-005 | Okuma ve yazma işlemleri ayrı güvenlik seviyelerine sahiptir. | FR-TOOL-005 | I | Yazma yetkisi ayrı permission gerektirir. |
| SR-TOOL-006 | Kritik işlem öncesi müşteri teyidi alınır. | FR-TOOL-006 | T | Teyit alınmadan kritik işlem yürütülmez. |
| SR-TOOL-007 | Para/sözleşme/kişisel veri değişikliğinde ek doğrulama uygulanır. | FR-TOOL-007 | T | Ek doğrulama olmadan işlem reddedilir (bkz. SR-AUTH-003). |
| SR-TOOL-008 | API hatası müşteriye teknik detay vermeden açıklanır. | FR-TOOL-008 | T | Müşteriye dönen mesajda stack/teknik detay yok. |
| SR-TOOL-009 | Idempotency key ile başarısız işlem sonrası duplicate oluşmaz. | FR-TOOL-009 | T | Aynı idempotency key ile tekrar tek işlem üretir. |
| SR-TOOL-010 | Tool çağrıları correlation_id ile izlenir ve audit edilir. | FR-TOOL-010 | A | Her tool çağrısı correlation_id ile trace'lenir. |
| SR-TOOL-011 | Uzun süren işlemler için asenkron workflow (callback/polling) desteklenir. | FR-TOOL-011 | T | Uzun işlem bloklamadan callback/polling ile tamamlanır. |
| SR-TOOL-012 | Onaylanmamış endpoint'lere erişim allowlist ile engellenir. | FR-TOOL-012 | T | Allowlist dışı endpoint çağrısı reddedilir. |

### 4.11 Çağrı-içi Kimlik Doğrulama (SR-AUTH) — BRD §9.11

| ID | Sistem Gereksinimi | Kaynak | Yöntem | Kabul Ölçütü / Eşik |
|----|--------------------|--------|--------|---------------------|
| SR-AUTH-001 | Caller ID tek başına güçlü kimlik kanıtı sayılmaz. | FR-AUTH-001 | I | Hassas işlem yalnız Caller ID ile yetkilendirilmez. |
| SR-AUTH-002 | OTP / müşteri numarası / KBA doğrulama desteklenir. | FR-AUTH-002 | T | Her yöntemle doğrulama tamamlanır. |
| SR-AUTH-003 | Hassas işlem için step-up authentication uygulanır. | FR-AUTH-003 | T | Step-up tamamlanmadan hassas işlem yürütülmez. |
| SR-AUTH-004 | Başarısız doğrulama denemesi sınırlanır. | FR-AUTH-004 | T | N başarısız denemede kilitleme/aktarım tetiklenir. |
| SR-AUTH-005 | Hassas bilgiler sesli olarak tam biçimde tekrarlanmaz. | FR-AUTH-005 | T | Hassas alanlar maskelenerek/parçalı doğrulanır. |
| SR-AUTH-006 | Ses biyometrisi ayrı, opsiyonel modüldür (varsayılan kapalı). | FR-AUTH-006 | I | Modül default off; ayrı etkinleştirme gerekir. |
| SR-AUTH-007 | Voiceprint oluşturma açık onay ve politika gerektirir. | FR-AUTH-007 | I | Onay/politika kaydı olmadan voiceprint üretilmez. |

### 4.12 İnsan Temsilciye Aktarım (SR-HND) — BRD §9.12

| ID | Sistem Gereksinimi | Kaynak | Yöntem | Kabul Ölçütü / Eşik |
|----|--------------------|--------|--------|---------------------|
| SR-HND-001 | Müşteri istediğinde insan temsilciye aktarılır. | FR-HND-001 | D | "Temsilciye bağla" talebi aktarımı tetikler. |
| SR-HND-002 | Düşük confidence/öfke/politika ihlali aktarımı tetikleyebilir. | FR-HND-002 | T | Tetikleyici eşik aşımında handoff başlar. |
| SR-HND-003 | Doğru departman ve skill grubu seçilir. | FR-HND-003 | T | Aktarım doğru skill grubuna ulaşır. |
| SR-HND-004 | Temsilciye görüşme özeti, intent, toplanan alanlar ve auth durumu aktarılır (context package + screen-pop). | FR-HND-004 | D | Temsilci ekranında bağlam paketi görünür (BRD §19 (18)). |
| SR-HND-005 | Müşteri aynı bilgileri tekrar vermek zorunda bırakılmaz. | FR-HND-005 | D | Aktarım sonrası temsilci toplanan veriyi tekrar istemez. |
| SR-HND-006 | Warm transfer sırasında agent temsilciye kısa whisper brifing verebilir. | FR-HND-006 | D | Warm transfer'de whisper brifing iletilir. |
| SR-HND-007 | Temsilci yoksa callback/voicemail/ticket sunulur. | FR-HND-007 | T | Temsilci yok senaryosunda alternatif sunulur. |
| SR-HND-008 | Aktarım başarısı ve bekleme süresi raporlanır. | FR-HND-008 | A | Aktarım başarı oranı ve bekleme süresi metrik olarak üretilir. |

### 4.13 Outbound & Kampanya & Consent (SR-OUT) — BRD §9.13

| ID | Sistem Gereksinimi | Kaynak | Yöntem | Kabul Ölçütü / Eşik |
|----|--------------------|--------|--------|---------------------|
| SR-OUT-001 | Kampanya oluşturma ve müşteri listesi yükleme desteklenir. | FR-OUT-001 | T | Liste yüklenir; kampanya çalıştırılır. |
| SR-OUT-002 | CRM'den dinamik kampanya listesi alınabilir. | FR-OUT-002 | T | CRM sorgusuyla liste dinamik dolar. |
| SR-OUT-003 | Arama öncesi consent ve suppression kontrolü yapılır (amaç/ülke/birey-şirket/kaynak/tarih/kapsam). | FR-OUT-003 | T | Consent yoksa/suppress ise çağrı başlatılmaz (BRD §19 (14)). |
| SR-OUT-004 | Ülke/bölge arama saatleri uygulanır. | FR-OUT-004, FR-TEL-013 | T | İzinli saat dışı arama engellenir. |
| SR-OUT-005 | Maksimum deneme sayısı ve yeniden arama aralığı uygulanır. | FR-OUT-005 | T | Sınır aşan deneme yapılmaz. |
| SR-OUT-006 | "Bir daha aramayın" talebi anında uygulanır. | FR-OUT-006 | T | Opt-out sonrası numara DNC'ye eklenir; tekrar aranmaz. |
| SR-OUT-007 | Kampanya kapasitesi agent+trunk kapasitesini aşmaz (backpressure). | FR-OUT-007 | T | Kapasite üstü arama backpressure ile sınırlanır (bkz. SR-RES-014). |
| SR-OUT-008 | Voicemail/meşgul/cevapsız/geçersiz numara ayrı kaydedilir. | FR-OUT-008 | I | Disposition taksonomisi bu durumları ayırır. |
| SR-OUT-009 | Kampanya script'i ve teklif versiyonu çağrı bazında kaydedilir. | FR-OUT-009 | I | Her çağrı kaydında script/teklif sürümü bulunur. |
| SR-OUT-010 | Kampanya durdurma düğmesi çağrıları derhal durdurur. | FR-OUT-010 | D | Durdurma sonrası yeni çağrı başlatılmaz. |
| SR-OUT-011 | Çağrı başına disposition otomatik oluşturulur. | FR-OUT-011 | A | Her outbound çağrı için disposition üretilir. |
| SR-OUT-012 | A/B test kampanyaları desteklenir. | FR-OUT-012 | T | Varyant dağıtımı ve karşılaştırma yapılır. |

### 4.14 Kayıt, Transkript & PII (SR-REC) — BRD §9.14

| ID | Sistem Gereksinimi | Kaynak | Yöntem | Kabul Ölçütü / Eşik |
|----|--------------------|--------|--------|---------------------|
| SR-REC-001 | Kayıt politikası tenant/ülke/use-case bazında belirlenir. | FR-REC-001 | I | Politika seçimi ilgili çağrılara uygulanır. |
| SR-REC-002 | Ses kaydı tamamen kapatılabilir. | FR-REC-002 | T | Kayıt kapalıyken hiçbir medya saklanmaz. |
| SR-REC-003 | Tek veya çift kanallı kayıt desteklenir. | FR-REC-003 | I | Seçilen kanal modu üretilir. |
| SR-REC-004 | Transkriptte PII redaction uygulanır. | FR-REC-004 | T | PII redaction test seti geçer (BRD §19 (13)). |
| SR-REC-005 | Kart/parola/OTP bilgileri kayıt ve transkriptten çıkarılır. | FR-REC-005 | T | Bu alanlar ne kayıtta ne transkriptte görünür. |
| SR-REC-006 | Saklama süresi otomatik uygulanır. | FR-REC-006 | T | Süre sonu gelen veri için silme tetiklenir. |
| SR-REC-007 | Legal hold desteklenir. | FR-REC-007 | T | Hold'daki veri retention dolsa da silinmez. |
| SR-REC-008 | Yetkili kullanıcı çağrıyı dinleyebilir ve transkripti görebilir. | FR-REC-008 | T | Yetkili erişebilir; yetkisiz 403. |
| SR-REC-009 | Kayıt/transkript erişimleri audit edilir. | FR-REC-009 | A | Her erişim audit log'a düşer. |
| SR-REC-010 | Saklama sonunda veri geri döndürülemez biçimde silinir. | FR-REC-010 | T | Silme sonrası veri hiçbir replikadan kurtarılamaz. |

### 4.15 Analitik & Kalite (SR-ANA) — BRD §9.15

| ID | Sistem Gereksinimi | Kaynak | Yöntem | Kabul Ölçütü / Eşik |
|----|--------------------|--------|--------|---------------------|
| SR-ANA-001 | Tüm çağrılar otomatik kalite değerlendirmesine alınır. | FR-ANA-001 | A | %100 çağrı için QA skoru üretilir. |
| SR-ANA-002 | Çağrı sonucu, intent, disposition ve completion çıkarılır. | FR-ANA-002 | A | Her çağrıda bu alanlar doldurulur. |
| SR-ANA-003 | Containment ve transfer oranı raporlanır. | FR-ANA-003 | A | Rapor doğru oranları gösterir. |
| SR-ANA-004 | Yanlış bilgi/tool hatası/güvenlik ihlali tespit edilir. | FR-ANA-004 | T | Enjekte edilen hata vakaları tespit edilir. |
| SR-ANA-005 | Kullanıcı ve agent konuşma süreleri ölçülür. | FR-ANA-005 | A | Konuşma süresi metriği çağrı başına üretilir. |
| SR-ANA-006 | STT/LLM/TTS ve toplam yanıt gecikmesi ayrı gösterilir. | FR-ANA-006 | A | Dört gecikme bileşeni ayrı raporlanır. |
| SR-ANA-007 | Maliyet çağrı/agent/tenant/sağlayıcı bazında raporlanır. | FR-ANA-007 | A | Maliyet bu dört boyutta ayrıştırılır. |
| SR-ANA-008 | Kritik konuşmalar otomatik işaretlenir. | FR-ANA-008 | T | Kriter karşılayan çağrı flag'lenir. |
| SR-ANA-009 | QA ekibi çağrıya skor ve açıklama ekleyebilir. | FR-ANA-009 | D | Manuel skor/yorum kaydedilir. |
| SR-ANA-010 | Agent sürümleri arasında performans karşılaştırılabilir. | FR-ANA-010 | A | İki sürümün metrikleri yan yana karşılaştırılır. |
| SR-ANA-011 | Dashboard ve ham veri export edilebilir. | FR-ANA-011 | T | Export dosyası üretilir ve tutarlıdır. |
| SR-ANA-012 | Gerçek zamanlı operasyon ekranı bulunur (≤60 sn metrik gecikmesi). | FR-ANA-012 | T | Canlı çağrı ekranı gecikmesi ≤60 sn (bkz. SR-PERF-007). |
| SR-ANA-013 | Çağrı başına kaynak tüketimi (CPU/bellek/eşzamanlılık) raporlanır. | FR-ANA-013 | A | Per-call kaynak metriği üretilir (bkz. SR-DEN-001). |

### 4.16 Test & Simülasyon (SR-TST) — BRD §9.16

| ID | Sistem Gereksinimi | Kaynak | Yöntem | Kabul Ölçütü / Eşik |
|----|--------------------|--------|--------|---------------------|
| SR-TST-001 | Agent telefon çağrısı olmadan tarayıcı üzerinden test edilebilir. | FR-TST-001 | D | Tarayıcı testi gerçek çağrı olmadan tamamlanır. |
| SR-TST-002 | Otomatik persona/senaryo simülasyonu çalıştırılır. | FR-TST-002 | T | Senaryo seti otomatik koşar, sonuç raporlanır. |
| SR-TST-003 | Happy path/edge case/adversarial testler desteklenir. | FR-TST-003 | T | Üç sınıf da test setinde mevcut ve koşulur. |
| SR-TST-004 | Prompt değişikliğinde regression test otomatik çalışır. | FR-TST-004 | T | Prompt değişimi CI'da regression'ı tetikler (BRD §19 (19)). |
| SR-TST-005 | Test sonucu eşik altındaysa production yayını engellenir. | FR-TST-005, FR-AGT-010 | T | Eşik altı skor yayını bloklar. |
| SR-TST-006 | Yük ve eş zamanlı çağrı testi (tasarım kapasitesi) yapılabilir. | FR-TST-006 | T | Tasarım kapasitesinde yük testi tamamlanır (BRD §19 (11)). |
| SR-TST-007 | Gürültü/aksan/kesinti/düşük hat kalitesi test edilebilir. | FR-TST-007 | T | Bozulma test seti koşulur, metrikler raporlanır. |
| SR-TST-008 | Gerçek müşteri verisi olmadan sentetik test verisi üretilir. | FR-TST-008 | I | Test ortamında gerçek PII kullanılmaz. |
| SR-TST-009 | Yük testinde çağrı başına kaynak tüketimi ölçülür ve regresyonu raporlanır. | FR-TST-009 | T | Per-call kaynak regresyonu raporlanır (BRD §19 (21)). |

### 4.17 Faturalama & Kullanım (SR-BIL) — BRD §9.17

| ID | Sistem Gereksinimi | Kaynak | Yöntem | Kabul Ölçütü / Eşik |
|----|--------------------|--------|--------|---------------------|
| SR-BIL-001 | Kullanım dakika ve saniye bazında ölçülür. | FR-BIL-001 | A | Ölçülen süre çağrı süresiyle ±tolerans içinde eşleşir. |
| SR-BIL-002 | Telekom/STT/TTS/LLM/platform maliyeti ayrı izlenir. | FR-BIL-002 | A | Beş maliyet kalemi ayrı kaydedilir. |
| SR-BIL-003 | Tenant bazında fiyat planı tanımlanabilir. | FR-BIL-003 | T | Plan ataması faturalamaya yansır. |
| SR-BIL-004 | Minimum ücret/kota/overage desteklenir. | FR-BIL-004 | T | Kota aşımında overage hesaplanır. |
| SR-BIL-005 | Dedicated altyapı maliyeti ayrıca faturalandırılabilir. | FR-BIL-005 | A | Dedicated maliyet ayrı kalem olarak görünür. |
| SR-BIL-006 | Kullanım limiti ve bütçe alarmı tanımlanabilir. | FR-BIL-006 | T | Limit/bütçe eşiğinde alarm üretilir. |
| SR-BIL-007 | Fatura verileri finans sistemine aktarılabilir. | FR-BIL-007 | T | Export finans sistemi formatında üretilir. |

### 4.18 Kaynak Verimliliği (SR-RES) — BRD §9.18

| ID | Sistem Gereksinimi | Kaynak | Yöntem | Kabul Ölçütü / Eşik |
|----|--------------------|--------|--------|---------------------|
| SR-RES-001 | Çalışma zamanı olay tabanlı/asenkron (non-blocking); thread-per-call kullanılmaz. | FR-RES-001 | I | Mimari/kod incelemesi thread-per-call içermez (ADR-003). |
| SR-RES-002 | Tüm ses/metin işleme streaming; full buffering yapılmaz. | FR-RES-002 | A | Pipeline'da tam-tampon yok (bkz. SR-RTC-001). |
| SR-RES-003 | Statik anonslar için TTS önbelleği kullanılır. | FR-RES-003 | A | TTS cache hit ≥ %80 (bkz. SR-DEN-004). |
| SR-RES-004 | Tekrarlayan sorular için semantic cache LLM çağrısını azaltır. | FR-RES-004 | T | Cache hit'te LLM çağrısı atlanır (bkz. SR-LLM-014). |
| SR-RES-005 | Model tiering uygulanır. | FR-RES-005 | A | Küçük-model tur oranı ≥ %60 hedef (bkz. SR-DEN-005). |
| SR-RES-006 | Sağlayıcı bağlantıları için connection pooling/kalıcı oturum kullanılır. | FR-RES-006 | A | Yük altında bağlantı yeniden kullanımı gözlemlenir. |
| SR-RES-007 | Boşta tenant/worker için scale-to-zero/ölçek küçültme uygulanır. | FR-RES-007 | T | Boşta tenant kaynağı minimuma/sıfıra iner. |
| SR-RES-008 | 8 kHz codec zincirinde gereksiz resample/transcode yapılmaz. | FR-RES-008 | A | Codec zincirinde gereksiz dönüşüm yok. |
| SR-RES-009 | VAD/endpointing ile dead air işlenmez. | FR-RES-009 | A | Dead-air'de STT/LLM çağrısı üretilmez (bkz. SR-RTC-013). |
| SR-RES-010 | Konuşma geçmişi özetleme + retrieval kısıtı ile token tüketimi düşürülür. | FR-RES-010 | A | Token tüketimi yapılandırılan tavanı aşmaz. |
| SR-RES-011 | Analitik/redaction/raporlama gibi non-RT işler batch/async yürütülür. | FR-RES-011 | I | Bu işler hot-path dışında çalışır (ADR-004/007). |
| SR-RES-012 | Loglama sampling + yapılandırılmış asenkron yazımla yapılır. | FR-RES-012 | I | Log yazımı çağrı hot-path'ini bloklamaz. |
| SR-RES-013 | Worker'lar için warm pool tutulur; cold-start azaltılır. | FR-RES-013 | T | Warm pool ile cold-start gecikmesi hedef altında (bkz. SR-SCAL-004). |
| SR-RES-014 | Aşırı yükte backpressure ve graceful degradation devreye girer. | FR-RES-014 | T | Tavan yükte çökme yerine kontrollü ret/sınırlama (bkz. SR-OUT-007). |
| SR-RES-015 | GPU yalnız self-hosted model gerektiğinde kullanılır; aksi CPU/serverless. | FR-RES-015 | I | Varsayılan çıkarım CPU/serverless; GPU yalnız gerekçeli (ADR-010). |
| SR-RES-016 | Çağrı başına kaynak bütçesi (bellek/CPU) tanımlanır ve aşımı izlenir. | FR-RES-016 | T | Per-call bellek hedefi ≤ ~15 MB izlenir; aşım alarmlanır (bkz. SR-DEN-001). |

---

## 5. Fonksiyonel Olmayan Sistem Gereksinimleri

### 5.1 Performans & Gecikme (SR-PERF) — BRD §10.1

| ID | Sistem Gereksinimi | Kaynak | Yöntem | Kabul Ölçütü / Eşik |
|----|--------------------|--------|--------|---------------------|
| SR-PERF-001 | EoU → ilk agent sesi gecikmesi P50 hedefi karşılanır. | NFR 10.1 | T | P50 ≤ 700 ms. |
| SR-PERF-002 | EoU → ilk agent sesi gecikmesi P95 hedefi karşılanır. | NFR 10.1 | T | P95 ≤ 1.200 ms (BRD §19 (10)). |
| SR-PERF-003 | EoU → ilk agent sesi gecikmesi P99 hedefi karşılanır. | NFR 10.1 | T | P99 ≤ 2.000 ms. |
| SR-PERF-004 | Barge-in sonrası TTS kesilme süresi karşılanır. | NFR 10.1 | T | ≤ 200 ms (bkz. SR-RTC-002). |
| SR-PERF-005 | Basit tool çağrısı platform overhead'i sınırlıdır. | NFR 10.1 | T | ≤ 100 ms platform overhead. |
| SR-PERF-006 | Agent konfigürasyon yükleme süresi sınırlıdır. | NFR 10.1 | T | ≤ 500 ms. |
| SR-PERF-007 | Dashboard metrik gecikmesi sınırlıdır. | NFR 10.1 | T | ≤ 60 sn (bkz. SR-ANA-012). |
| SR-PERF-008 | Kritik alarm üretim gecikmesi sınırlıdır. | NFR 10.1 | T | ≤ 2 dk. |

### 5.2 Kaynak Verimliliği / Density (SR-DEN) — BRD §10.2

| ID | Sistem Gereksinimi | Kaynak | Yöntem | Kabul Ölçütü / Eşik |
|----|--------------------|--------|--------|---------------------|
| SR-DEN-001 | Aktif çağrı başına orkestratör belleği (medya tamponları hariç) hedeftedir. | NFR 10.2 | T | ≤ ~15 MB/oturum (yük altında ölçüm). |
| SR-DEN-002 | Referans işçi düğümü (8 vCPU/16 GB) başına eş zamanlı oturum hedefi karşılanır. | NFR 10.2 | T | ≥ 250–500 oturum (medya konumuna göre; BRD §19 (22)). |
| SR-DEN-003 | Steady-state çağrı başına CPU düşüktür; performans (5.1) bozulmaz. | NFR 10.2 | A | CPU/oturum düşük; P95 gecikme korunur. |
| SR-DEN-004 | Statik anons TTS cache hit oranı hedeftedir. | NFR 10.2 | A | ≥ %80 (bkz. SR-TTS-010). |
| SR-DEN-005 | Küçük/hızlı modelle karşılanan tur oranı hedeftedir. | NFR 10.2 | A | ≥ %60 hedef (bkz. SR-LLM-013). |
| SR-DEN-006 | Boşta tenant kaynağı minimuma yakındır. | NFR 10.2 | T | Idle tenant scale-to-zero/minimum (bkz. SR-RES-007). |

> **Birlikte değerlendirme:** SR-DEN optimizasyonları SR-PERF eşiklerini bozmamalıdır (BRD §10.2 notu).
> Yük testi her iki seti aynı koşuda doğrular (bkz. WBS 0.3.2/0.3.3, ADR-009 kararına bağlı).

### 5.3 Ölçeklenebilirlik (SR-SCAL) — BRD §10.3

| ID | Sistem Gereksinimi | Kaynak | Yöntem | Kabul Ölçütü / Eşik |
|----|--------------------|--------|--------|---------------------|
| SR-SCAL-001 | Bölge başına eş zamanlı çağrı hedefi karşılanır (ön hedef). | NFR 10.3 | T | 10.000 eş zamanlı çağrı (ön tasarım hedefi). |
| SR-SCAL-002 | Yeni çağrı başlatma/kabul hızı hedefi karşılanır. | NFR 10.3 | T | 100 CPS. |
| SR-SCAL-003 | Kısa süreli 2x trafik artışı karşılanır. | NFR 10.3 | T | 2x ani artışta hata oranı eşik altında. |
| SR-SCAL-004 | Autoscaling ile yeni worker kapasitesi otomatik devreye alınır. | NFR 10.3 | T | Yük artışında yeni worker hedef sürede hazır (bkz. SR-RES-013). |
| SR-SCAL-005 | Tek tenant concurrency kotası ve noisy-neighbor önleme uygulanır. | NFR 10.3 | T | Bir tenant'ın yükü diğerinin SLA'sını bozmaz. |

### 5.4 Kullanılabilirlik (SR-AVL) — BRD §10.4

| ID | Sistem Gereksinimi | Kaynak | Yöntem | Kabul Ölçütü / Eşik |
|----|--------------------|--------|--------|---------------------|
| SR-AVL-001 | Voice runtime aylık erişilebilirlik hedefini karşılar. | NFR 10.4 | A | %99,99 (aylık). |
| SR-AVL-002 | Telephony edge erişilebilirlik hedefini karşılar. | NFR 10.4 | A | %99,99. |
| SR-AVL-003 | Kritik API gateway erişilebilirlik hedefini karşılar. | NFR 10.4 | A | %99,99. |
| SR-AVL-004 | Yönetim paneli erişilebilirlik hedefini karşılar. | NFR 10.4 | A | %99,9. |
| SR-AVL-005 | Analitik/raporlama erişilebilirlik hedefini karşılar. | NFR 10.4 | A | %99,9. |

### 5.5 Felaket Kurtarma (SR-DR) — BRD §10.5

| ID | Sistem Gereksinimi | Kaynak | Yöntem | Kabul Ölçütü / Eşik |
|----|--------------------|--------|--------|---------------------|
| SR-DR-001 | Tüm stateful servisler multi-AZ çalışır. | NFR 10.5 | I | AZ kaybında servis sürer. |
| SR-DR-002 | Aktif-pasif bölgesel DR ile yeni çağrılar sağlıklı bölgeye failover olur. | NFR 10.5 | T | Bölge arızasında yeni çağrı otomatik yönlenir (BRD §19 (17)). |
| SR-DR-003 | Kritik konfigürasyon RPO hedefi karşılanır. | NFR 10.5 | T | RPO ≤ 5 dk. |
| SR-DR-004 | Analitik veri RPO hedefi karşılanır. | NFR 10.5 | T | RPO ≤ 15 dk. |
| SR-DR-005 | Voice runtime RTO hedefi karşılanır. | NFR 10.5 | T | RTO ≤ 15 dk. |
| SR-DR-006 | Yönetim sistemi RTO hedefi karşılanır. | NFR 10.5 | T | RTO ≤ 4 sa. |
| SR-DR-007 | DR tatbikatı yılda ≥2 kez yürütülür. | NFR 10.5 | I | Yılda en az 2 tatbikat kaydı. |

### 5.6 Güvenlik (SR-SEC) — BRD §10.6

| ID | Sistem Gereksinimi | Kaynak | Yöntem | Kabul Ölçütü / Eşik |
|----|--------------------|--------|--------|---------------------|
| SR-SEC-001 | Aktarımda TLS, medyada SRTP kullanılır. | NFR 10.6 | T | Şifresiz aktarım/medya reddedilir. |
| SR-SEC-002 | Depolama AES-256 (veya eşdeğer) + tenant başına ayrı KMS key ile şifrelenir. | NFR 10.6 | I | Her tenant ayrı key; şifresiz veri yok. |
| SR-SEC-003 | BYOK / müşteri tarafından yönetilen anahtar desteklenir. | NFR 10.6 | T | Tenant kendi anahtarını getirebilir (Faz 3 kapsamı). |
| SR-SEC-004 | WAF/DDoS + rate limiting + IP allowlist + private endpoint uygulanır. | NFR 10.6 | T | Sınır aşan istek bloklanır; private endpoint erişimi dışarıdan kapalı. |
| SR-SEC-005 | SIP saldırılarına karşı SBC korur. | NFR 10.6 | T | SIP saldırı senaryosu SBC'de engellenir. |
| SR-SEC-006 | CI'da SAST/DAST/dependency scan zorunludur ve SBOM üretilir. | NFR 10.6 | I | Tarama geçmeden build ilerlemez; SBOM artifact üretilir. |
| SR-SEC-007 | Audit log bütünlüğü korunur (değiştirilemezlik). | NFR 10.6 | T | Bütünlük doğrulaması başarılı (bkz. SR-IAM-006). |
| SR-SEC-008 | PAM ve incident response prosedürü uygulanır. | NFR 10.6 | I | Ayrıcalıklı erişim PAM üzerinden; IR runbook mevcut. |
| SR-SEC-009 | Düzenli penetration testte açık kritik bulgu kalmaz. | NFR 10.6 | T | Pentest kritik bulgu = 0 (BRD §19 (20)). |

### 5.7 Veri Yerleşimi / Residency (SR-LOC) — BRD §10.7

| ID | Sistem Gereksinimi | Kaynak | Yöntem | Kabul Ölçütü / Eşik |
|----|--------------------|--------|--------|---------------------|
| SR-LOC-001 | Platform en az UK/EU/North America/Middle East bölgesel çalışmayı destekler. | NFR 10.7 | T | Her bölgede tenant verisi o bölgede tutulur. |
| SR-LOC-002 | Her tenant için kayıt/transkript/prompt/KB/analitik/audit/backup ve sağlayıcıya gönderilen içeriğin bölgesi gösterilir. | NFR 10.7 | I | Residency görünümü tüm veri sınıflarını listeler. |
| SR-LOC-003 | Veri seçilen home-region dışına çıkmaz (adapter düzeyinde region selection). | NFR 10.7 | A | Cross-region veri akışı tespit edilmez (bkz. WBS 1.2.2, 4.1.4). |

---

## 6. Arayüz ve Veri Gereksinimleri

- **Adapter SPI (STT/TTS/LLM/Telephony):** Her kategori adapter SPI arkasındadır; ortak yetenekler
  timeout/retry/circuit breaker/health check, usage metering, region selection, hata normalizasyonu
  içerir (SAD §8). Sözleşmeler **0.1.4 API tasarım** dokümanında OpenAPI/SPI olarak detaylandırılır.
- **Panel arayüzleri (L0/L1/L2):** Ekran–panel–rol erişim matrisi BRD §17.6, izolasyon kuralları §17.7;
  backend AuthZ enforcement SAD §14.4.2. SRS, yalnız bu arayüzlerin yetki/izolasyon davranışını
  (SR-IAM-008..011, SR-TEN-002) doğrulanabilir kılar.
- **Veri varlıkları:** Ana varlıklar BRD §16'dadır (Tenant, User, Agent, Call, Transcript, Recording,
  Consent, Usage Record, Audit Log, …). Tüm tenant-kapsamlı varlıklar `tenant_id` taşır ve RLS'e
  tabidir (SR-TEN-002). PK/FK/indeks/RLS detayı **0.1.3 DB tasarım** dokümanında ele alınır.

> Bu bölüm tasarım dokümanlarına (0.1.3/0.1.4) köprüdür; arayüz/veri "nasıl"ı orada, "doğrulanabilir ne"si burada.

---

## 7. Doğrulama ve Kabul Kapısı (BRD §19 Eşlemesi)

BRD §19'daki 22 kabul kriteri, aşağıdaki SR'lerle doğrulanır. Üretim kabulü, ilgili SR test-case'leri
geçtiğinde verilir (Faz 1 inbound altkümesi için WBS Ek A esastır).

| BRD §19 | Kriter (özet) | İlgili SR(ler) |
|---------|---------------|----------------|
| 1 | ≥2 STT | SR-STT-001 |
| 2 | ≥2 TTS | SR-TTS-001 |
| 3 | ≥2 LLM | SR-LLM-001 |
| 4 | Birincil kesintide fallback | SR-STT-008, SR-TTS-008, SR-LLM-010 |
| 5 | Inbound+outbound tamamlanır | SR-TEL-001 |
| 6 | Warm+cold transfer | SR-TEL-007, SR-HND-004 |
| 7 | CRM oku + kontrollü işlem | SR-TOOL-001, SR-TOOL-006 |
| 8 | Prompt injection sızıntı yok | SR-LLM-007 |
| 9 | Tenant izolasyonu | SR-TEN-002 |
| 10 | P95 gecikme | SR-PERF-002 |
| 11 | Tasarım kapasitesinde yük testi | SR-TST-006, SR-SCAL-001 |
| 12 | Retention uygulanır | SR-REC-006, SR-REC-010 |
| 13 | PII redaction | SR-REC-004, SR-REC-005 |
| 14 | Outbound consent/opt-out | SR-OUT-003, SR-OUT-006, SR-TEL-014 |
| 15 | Agent rollback | SR-AGT-006 |
| 16 | Kritik işlemler audit'te | SR-IAM-006, SR-TOOL-010 |
| 17 | DR senaryosu | SR-DR-002 |
| 18 | Temsilciye özet/bağlam | SR-HND-004, SR-HND-005 |
| 19 | Regression production öncesi | SR-TST-004, SR-TST-005 |
| 20 | Pentest kritik bulgu yok | SR-SEC-009 |
| 21 | Yük altında per-call kaynak bütçede | SR-DEN-001, SR-TST-009 |
| 22 | Worker başına density hedefi | SR-DEN-002 |

---

## 8. İzlenebilirlik Özeti

- **Kapsama:** BRD §9'daki tüm FR alt-alanları (TEN, IAM, AGT, TEL, RTC, STT, TTS, LLM, KB, TOOL, AUTH,
  HND, OUT, REC, ANA, TST, BIL, RES) ve §10'daki tüm NFR alanları (PERF, DEN, SCAL, AVL, DR, SEC, LOC)
  bu SRS'te ≥1 doğrulanabilir SR'ye indirilmiştir. Her FR-ID, "Kaynak" sütunundan geri izlenebilir.
- **Tam matris:** FR ↔ SR ↔ test-case ↔ WBS dört-yönlü izlenebilirlik matrisi ayrı bir görevdir
  (**WBS 0.1.2**); bu doküman onun FR↔SR ayağını sağlar.
- **Test-case kataloğu:** "Yöntem" ve "Kabul Ölçütü" sütunları, QA test-case'lerinin doğrudan
  türetileceği nesnel girdilerdir (T/D → otomasyon; A → metrik/trace; I → review checklist).

---

## 9. Varsayımlar, Bağımlılıklar ve Açık Kararlar

- **Density/gecikme eşikleri ön hedeftir:** SR-DEN-001/002 ve SR-SCAL-001 değerleri BRD §10.2/§10.3
  uyarınca ön tasarım hedefidir; **PoC** (WBS 0.3) ve **ADR-009** (medya işleme konumu) ile kesinleşir.
  ADR-009 kararına kadar SR-DEN-002'nin "250 vs 500" alt sınırı açık kabul edilir.
- **Faz bağımlılığı:** Bazı SR'ler Faz 2/3 kapsamındadır (ör. SR-SEC-003 BYOK, SR-AUTH-006 ses
  biyometrisi, SR-OUT-* outbound). Kabul kapısı ilgili fazda uygulanır (WBS faz kapıları).
- **BRD §22 açık kararları:** İlk ülke/sektör, pilot use-case, telekom sağlayıcı, ilk diller, retention
  süreleri, PCI kapsamı ve ilk CC entegrasyonu netleşmeden, bunlara bağlı SR'lerin somut eşik değerleri
  (ör. retention gün sayısı, dil listesi) parametre olarak bırakılmıştır.
- **Vendor-neutral:** Hiçbir SR belirli bir sağlayıcı şart koşmaz; "≥2 sağlayıcı + fallback" davranışı
  şart koşulur (ADR-002).

---

## 10. Sonuç ve Sonraki Adımlar

Bu SRS, BRD'nin iş seviyesi FR/NFR'lerini doğrulanabilir, ölçülebilir ve izlenebilir sistem
gereksinimlerine indirir; her SR bir doğrulama yöntemi ve nesnel kabul ölçütü taşır. Böylece QA
test-case'leri, kabul kapısı ve izlenebilirlik matrisi doğrudan bu dokümandan türetilebilir.

**Sonraki adımlar (WBS):**
1. **0.1.2** — Tam izlenebilirlik matrisi (FR ↔ SR ↔ test-case ↔ WBS).
2. **0.1.3** — Veri tabanı tasarımı (BRD §16 varlıkları; PK/FK/indeks/RLS — SR-TEN-002 zorlaması).
3. **0.1.4** — API & adapter SPI tasarımı (OpenAPI sözleşmeleri — §6'daki arayüz SR'leri).
4. **0.1.5 / 0.3** — Threat model (STRIDE) ve PoC ile SR-DEN/SR-PERF eşiklerinin doğrulanması (ADR-009).

> `.md` source of truth'tur; markalı `.docx` artifact'i **0.1.7** kapsamında `docs/build-docx.sh` ile üretilir.
