# İş Gereksinimleri Dokümanı (BRD)
## Kurumsal Sesli Yapay Zekâ Asistanı Platformu — Enterprise Voice AI Agent Platform

**Yüksek Hızlı · Düşük Kaynak Tüketimli (High-Density, Lean Runtime)**
STT · LLM · TTS Gerçek Zamanlı Orkestrasyonu
Inbound & Outbound | Multi-Tenant | Vendor-Neutral | Human Handoff

> RMC TECHNOLOGY & CONSULTANCY — rmctech.co.uk

---

## Doküman Bilgileri

| Alan | Değer |
|------|-------|
| Doküman Adı | Kurumsal Sesli Yapay Zekâ Asistanı Platformu — İş Gereksinimleri Dokümanı |
| Doküman Tipi | Business Requirements Document (BRD) |
| Hedef Ürün | Multi-Tenant Enterprise Voice AI Agent Platform |
| Hedef Pazar | Büyük çağrı merkezleri; sigorta, finans, telekom, sağlık, perakende, lojistik, kamu ve hizmet sektörleri |
| Tasarım İlkesi | Vendor-neutral orkestrasyon · gerçek zamanlı · yüksek yoğunluklu / düşük kaynak tüketimli · kesintisiz insan aktarımı |
| Dağıtım Seçenekleri | SaaS · dedicated cloud · private cloud · on-premise / hybrid |
| Sürüm | 2.1 (Panel Mimarisi & RBAC) |
| Tarih | 13 Haziran 2026 |
| Durum | İncelemeye Hazır |
| Gizlilik | Gizli — Yalnızca yetkili paydaşlar |

### Sürüm Geçmişi

| Sürüm | Tarih | Açıklama |
|-------|-------|----------|
| 1.0 | 13.06.2026 | İlk taslak — temel kapsam ve gereksinimler. |
| 2.0 | 13.06.2026 | Detaylı kapsam; kaynak verimliliği (lean runtime) gereksinimleri, genişletilmiş FR/NFR setleri, mimari ve uyumluluk. |
| 2.1 | 13.06.2026 | Üç katmanlı panel mimarisi (L0 Platform Admin / L1 Tenant Admin / L2 Operasyon) ve RBAC erişim matrisi eklendi; Bölüm 17 yeniden yapılandırıldı; paydaş–panel eşlemesi ve sözlük güncellendi. Yeni gereksinimler: FR-IAM-008 (panel-katman rol ayrımı), FR-IAM-009 (üç katmanlı break-glass), FR-IAM-010 (regüle tenant onay toggle'ı + DPA), FR-IAM-011 (sabit rol bundle + scoped assignment). |

---

## 1. Yönetici Özeti

Bu doküman, kurumsal firmaların telefon çağrılarını insan operatöre yakın doğallıkta karşılayan veya dış arama yapan sesli yapay zekâ asistanlarını (Voice AI Agent) oluşturmasını, yönetmesini, test etmesini ve izlemesini sağlayan kurumsal bir platformun iş gereksinimlerini tanımlar. Platform; telefon altyapısı, konuşma tanıma (STT), büyük dil modeli (LLM) ile diyalog yönetimi, bilgi getirimi (RAG), kurumsal sistem/araç çağrıları ve metinden konuşma (TTS) bileşenlerini gerçek zamanlı olarak orkestra eder.

Ürünün iki temel mandası vardır. Birincisi insan benzeri, doğal ve düşük gecikmeli konuşma deneyimi sunmak; ikincisi ise bunu yüksek yoğunlukta (high-density) ve düşük sistem kaynağı tüketerek, yani düşük çağrı başına maliyetle yapmaktır. Bu nedenle platform yalnızca bir "sesli chatbot" değil, az kaynakla ölçeklenen, kurum sistemlerinde gerçek işlem yapabilen, SLA ile çalışan ve insan temsilcilerle birlikte kullanılan bir iletişim ve yapay zekâ orkestrasyon altyapısıdır.

Mevcut platformların (ör. Retell AI) inbound/outbound çağrı, agent oluşturma, bilgi tabanı, webhook, çağrı aktarımı, simülasyon testi, alarm ve izleme özellikleri pazarın minimum rekabet seviyesi olarak kabul edilmiştir. Bu BRD, bu seviyeyi karşılayan ve kaynak verimliliği ile farklılaşan bir ürünü hedefler.

### 1.1 Çözümün Özeti

| Boyut | Tanım |
|-------|-------|
| Ne yapar | Telefon çağrılarını insan gibi karşılar, anlar, yanıtlar, kurumsal sistemlerde işlem yapar ve gerektiğinde insan temsilciye kesintisiz aktarır. |
| Nasıl çalışır | Bağımsız bir Conversation Orchestrator, STT/LLM/TTS bileşenlerini streaming olarak yönetir; turn-taking, barge-in, policy ve tool çağrılarını koordine eder. |
| Ayırt edici özellik | Yüksek yoğunluklu, düşük kaynak tüketimli çalışma zamanı: çağrı başına düşük CPU/bellek, akıllı model yönlendirme ve önbellekleme ile düşük maliyet. |
| Kimin için | Yüksek hacimli çağrı merkezi işleten kurumsal firmalar ve BPO sağlayıcılar (B2B2B). |
| Konuşlanma | Çok kiracılı (multi-tenant); SaaS, dedicated, private cloud veya hybrid. |

---

## 2. İş Problemi

Büyük çağrı merkezleri aşağıdaki yapısal problemlerle karşılaşır:

| Problem | Etkisi |
|---------|--------|
| Yüksek temsilci maliyeti | Çağrı başına operasyon maliyetinin artması. |
| Yoğun saatlerde kapasite yetersizliği | Uzun bekleme süresi ve terk edilen çağrılar. |
| Standart dışı temsilci performansı | Müşteri deneyiminde tutarsızlık. |
| Yüksek personel devir oranı | Eğitim ve işe alım maliyeti. |
| 7/24 hizmet ihtiyacı | Vardiya ve operasyon maliyeti. |
| Tekrarlayan çağrılar | İnsan kaynağının düşük değerli işlerde kullanılması. |
| Eski IVR sistemleri | Uzun menüler ve düşük müşteri memnuniyeti. |
| Çok sayıda kurumsal sistem | Temsilcinin ekranlar arası geçiş yükü. |
| Örnekleme ile kalite kontrolü | Çağrıların büyük bölümünün denetlenememesi. |
| Outbound kampanyalarda düşük verim | Ulaşılamayan müşteri ve yüksek temsilci zamanı. |
| Çok dilli hizmet ihtiyacı | Farklı dilde temsilci bulma problemi. |
| Mevcut AI çözümlerinin yüksek altyapı maliyeti | GPU/işlem yoğun mimariler ile yüksek çağrı başına maliyet. |

Voice AI platformu bu operasyonların tamamını değil, güvenli ve uygun olan çağrı türlerini otomatikleştirerek insan temsilcilerin karmaşık vakalara odaklanmasını sağlar. Ek olarak, kaynak verimli mimari sayesinde otomasyonun kendisi de rakip çözümlere kıyasla daha düşük maliyetli olmalıdır.

---

## 3. İş Hedefleri

### 3.1 Birincil Hedefler

| ID | Hedef |
|----|-------|
| OBJ-01 | Inbound çağrıların belirlenen oranını insan müdahalesi olmadan tamamlamak (containment). |
| OBJ-02 | Outbound kampanyaları otomatik ve mevzuata uygun biçimde yürütmek. |
| OBJ-03 | Müşteri bekleme süresini ve çağrı terk oranını azaltmak. |
| OBJ-04 | 7/24 esnek ve ölçeklenebilir hizmet sunmak. |
| OBJ-05 | İnsan temsilciye aktarılan çağrılarda konuşma bağlamını korumak. |
| OBJ-06 | Çağrı başına operasyon maliyetini düşürmek. |
| OBJ-07 | CRM, poliçe, ödeme, randevu ve ticket sistemlerinde gerçek işlem yapmak. |
| OBJ-08 | Tüm görüşmelerde standart kalite ve kurumsal dil sağlamak. |
| OBJ-09 | Agent performansını ölçülebilir ve denetlenebilir hale getirmek. |
| OBJ-10 | TTS, STT, LLM ve telekom sağlayıcısı bağımlılığını azaltmak (vendor-neutral). |
| OBJ-11 | Kurumsal güvenlik ve veri yerleşimi gereksinimlerini desteklemek. |
| OBJ-12 | Birden fazla müşteri ve markayı aynı platformda güvenli şekilde yönetmek. |
| OBJ-13 | Birim çağrı başına sistem kaynağı (CPU, bellek, GPU) tüketimini minimize ederek yüksek yoğunluklu ve düşük maliyetli çalışmayı sağlamak. |
| OBJ-14 | Düşük gecikme (sub-second) ile kaynak verimliliği arasındaki dengeyi mimari düzeyde optimize etmek. |

### 3.2 Başarı Hedefleri

İlk üretim sürümü için önerilen hedefler (pilot sonrası sektör/müşteri bazında kesinleştirilecektir):

- Otomatikleştirilebilir çağrılarda containment oranının ≥ %60 olması.
- Otomatikleştirilebilir çağrılarda ilk temas çözüm oranının (FCR) ≥ %70 olması.
- Müşteri konuşmayı bıraktıktan sonra ilk ses yanıtının P50'de ≤ 700 ms, P95'te ≤ 1.200 ms başlaması.
- Platform erişilebilirliğinin (voice runtime) aylık ≥ %99,99 olması.
- Desteklenen dillerde başarılı transkripsiyon oranının ≥ %95 olması.
- Tool/API işlemlerinde teknik başarı oranının ≥ %99 olması.
- Kritik hatalı işlem oranının < %0,1 olması.
- İnsan temsilciye aktarım başarı oranının > %99 olması.
- Çağrı başına altyapı maliyetinin (compute) sektör ortalamasının belirgin altında tutulması ve sürekli ölçülmesi.

Bu değerler nihai SLA değildir; pilot sonrası gerçek çağrı verisiyle doğrulanmalıdır.

---

## 4. Ürün Vizyonu

Kurumsal firmaların; güvenli, denetlenebilir ve kaynak açısından verimli biçimde, insan operatöre yakın doğallıkta konuşan ve gerçek iş süreçlerini tamamlayan sesli yapay zekâ asistanları oluşturmasını sağlayan bağımsız bir iletişim ve yapay zekâ orkestrasyon platformu oluşturmak.

Platformun temel farkı yalnızca doğal ses üretmek değil; çağrının başından sonuna kadar telefon, konuşma, karar, işlem, güvenlik, entegrasyon ve raporlama süreçlerini düşük gecikme ve düşük kaynak tüketimiyle yönetmektir.

---

## 5. Ürün Prensipleri

| Prensip | Açıklama |
|---------|----------|
| Vendor-neutral | TTS, STT, LLM ve telekom sağlayıcıları değiştirilebilir olmalıdır. |
| Real-time first | Tüm kritik bileşenler streaming çalışmalıdır; tam tampona (full buffering) dayanılmamalıdır. |
| Resource-efficient / lean runtime | Çağrı başına CPU, bellek ve GPU tüketimi minimize edilmeli; yüksek yoğunluk (density) hedeflenmelidir. |
| Human handoff by design | İnsan temsilciye aktarım istisna değil, temel özellik olmalıdır. |
| Enterprise security | Tenant izolasyonu, RBAC, SSO, şifreleme ve audit log zorunludur. |
| Configuration over coding | İş birimleri mümkün olduğunca kod yazmadan agent oluşturabilmelidir. |
| Deterministic actions | Para, poliçe, sipariş veya kişisel veri değiştiren işlemler kontrollü workflow ile yürütülmelidir. |
| Observable by default | Her çağrı, model, tool, gecikme ve kaynak tüketimi ölçülebilir olmalıdır. |
| Compliance by design | Onay, kayıt, saklama ve outbound kuralları ürünün içine gömülmelidir. |
| Graceful degradation | Bir AI sağlayıcısı veya kaynak darboğazı oluştuğunda çağrı tamamen çökmemelidir. |
| No deceptive impersonation | Agent insan gibi konuşabilir ancak kendisini gerçek bir insanmış gibi yanlış tanıtmamalıdır. |

---

## 6. Kapsam

### 6.1 Kapsam Dahilinde

**Voice AI Çalışma Zamanı**
- Inbound çağrı karşılama
- Outbound arama
- Gerçek zamanlı ses akışı (streaming)
- Streaming STT ve TTS
- LLM tabanlı konuşma yönetimi
- Turn-taking ve barge-in
- DTMF algılama ve üretme
- Gürültü ve yankı yönetimi
- Sessizlik ve çağrı sonlandırma yönetimi
- Answering machine detection
- Voicemail bırakma
- İnsan temsilciye aktarım

**Agent Yönetimi**
- Agent oluşturma
- Prompt ve konuşma akışı tanımlama
- Voice ve dil seçimi
- Bilgi tabanı bağlama
- Tool ve API tanımlama
- Agent versiyonlama
- Test, yayınlama, ortam yönetimi ve rollback

**Kurumsal Entegrasyon**
- CRM, contact centre, ticketing, ERP
- Ödeme, randevu, poliçe ve hasar sistemleri
- Kimlik doğrulama servisleri
- Webhook, REST/SOAP/GraphQL API, event streaming

**Yönetim ve Analiz**
- Çağrı kayıtları, transkript ve çağrı özeti
- Intent, outcome ve sentiment analizi
- Agent performans raporları ve canlı operasyon ekranı
- Alarm/olay yönetimi, maliyet analizi ve audit kayıtları
- Kaynak tüketimi (CPU/bellek/eşzamanlılık) izleme ve raporlama

### 6.2 İlk Sürüm Dışında
- Tam kapsamlı workforce management
- İnsan temsilci masaüstünün tamamen değiştirilmesi
- CRM/ticketing sisteminin yeniden geliştirilmesi
- Genel amaçlı video avatar
- Sosyal medya chatbot platformu
- Kendi temel LLM modelinin sıfırdan eğitilmesi
- Kamu acil çağrı sistemlerinde kullanım
- İnsan onayı olmadan yüksek riskli kredi, sigorta veya sağlık kararı

---

## 7. Hedef Kullanıcılar ve Paydaşlar

Paydaşlar üç panel katmanına göre konumlandırılır: **L0 — Platform Admin Console** (platform operatörü/RMC, cross-tenant), **L1 — Tenant Admin Console** (kurumsal müşterinin admini, tek tenant) ve **L2 — Operasyon / Uygulama Paneli** (günlük operasyon ekibi, tek tenant). Panel mimarisinin ve rollerin detayı Bölüm 17'dedir.

| Paydaş | İhtiyaç | Panel | RBAC Rolü |
|--------|---------|-------|-----------|
| Kurumsal yönetici | Maliyet, verimlilik ve müşteri deneyimi takibi. | L1+L2 | `tenant_owner` |
| Çağrı merkezi yöneticisi | Agent performansı ve canlı operasyon kontrolü. | L2 | `operations_manager` |
| Operasyon uzmanı | Konuşma akışı oluşturma ve güncelleme. | L2 | `conversation_designer` |
| AI / Prompt uzmanı | Prompt, model ve bilgi tabanı yönetimi. | L2 | `conversation_designer` |
| Sistem yöneticisi | Tenant içi kullanıcı, erişim ve entegrasyon yönetimi. | L1 | `tenant_admin` |
| Bilgi güvenliği ekibi | Güvenlik, audit ve veri yerleşimi kontrolü. | L1 | `security_compliance_officer` |
| Uyum ve hukuk ekibi | Kayıt, onay, saklama ve outbound kuralları. | L1 | `security_compliance_officer` |
| QA ekibi | Çağrı değerlendirme ve hata analizi. | L2 | `qa_analyst` |
| İnsan temsilci | Aktarılan çağrıyı bağlamıyla devralma. | L2 | `human_agent` |
| API geliştiricisi | Kurumsal sistem entegrasyonu. | L1+L2 | `api_developer` |
| Finans ekibi (tenant) | Tenant kullanım, fatura, maliyet ve kaynak verimliliği takibi. | L1 | `billing_viewer` |
| Platform operatörü (RMC) | Çok kiracılı platformun işletimi, kapasite ve kaynak yönetimi. | L0 | `platform_owner`, `platform_sre` |
| Platform finans (RMC) | Platform geneli faturalandırma ve rate-card. | L0 | `platform_billing` |
| Son müşteri | Hızlı, doğal ve doğru telefon hizmeti. | — | — |

---

## 8. Temel İş Senaryoları

### 8.1 Inbound Müşteri Hizmetleri
1. Çağrıyı karşılar.
2. Gerekli AI ve kayıt bilgilendirmesini yapar.
3. Arayan numaradan müşteriyi bulmaya çalışır.
4. Gerekirse ek kimlik doğrulama yapar.
5. Talebi serbest konuşmadan anlar.
6. Bilgi tabanından yanıt verir veya API üzerinden işlem yapar.
7. İşlemi müşteriye teyit ettirir.
8. Sonucu CRM'e kaydeder.
9. Çağrıyı özetler ve sonuçlandırır.
10. Gerektiğinde insan temsilciye aktarır.

### 8.2 Outbound Satış / Bilgilendirme
1. Kampanya listesinden müşteri kaydını alır.
2. Arama izni ve zaman kuralını kontrol eder.
3. Aramayı başlatır.
4. İnsan, voicemail veya geçersiz numara ayrımı yapar.
5. Kimliğini ve arama amacını açıklar.
6. Müşteriyle konuşur.
7. İlgilenme durumuna göre lead'i sınıflandırır.
8. Randevu oluşturur veya temsilciye aktarır.
9. Ret ve opt-out taleplerini anında kaydeder.
10. Kampanya sonucunu CRM'e işler.

> Türkiye'de ticari aramalar için İYS (İleti Yönetim Sistemi) izin kaydı; UK'de otomatik pazarlama çağrıları için önceden ve özellikle bu tür çağrıları kapsayan onay gerekebilir. Ofcom, dialler sistemlerinin sessiz/terk edilmiş çağrı üretmemesini bekler. Bu nedenle outbound modülü basit bir toplu arama fonksiyonu olarak tasarlanamaz.

### 8.3 Randevu Oluşturma
Agent müşteri talebini anlar, uygun zamanları API üzerinden getirir, zamanı teyit eder, randevuyu oluşturur ve SMS/e-posta doğrulaması gönderir.

### 8.4 Sigorta Hasar Bildirimi
Agent müşterinin kimliğini doğrular, olay bilgilerini toplar, zorunlu soruları eksiksiz sorar, claim kaydı oluşturur, referans numarası verir ve riskli durumlarda insan temsilciye aktarır.

### 8.5 Tahsilat Hatırlatma
Agent borç bilgisini doğrular, ödeme seçeneklerini açıklar ve müşteriyi PCI uyumlu ödeme kanalına aktarır. Kart bilgileri normal LLM konuşma akışına, transkripte veya ses kaydına alınmamalıdır; telefon üzerinden ödeme alan operasyonlarda PCI DSS kapsamı ayrıca değerlendirilmelidir.

### 8.6 Teknik Destek
Agent problemi anlar, cihaz/hesap verisini sorgular, kontrollü troubleshooting adımlarını uygular, çözemezse ticket oluşturur veya uzman kuyruğuna aktarır.

### 8.7 Yoğun Çağrı Taşması (Overflow)
İnsan temsilci kuyrukları dolduğunda belirli çağrı türleri Voice AI agent'a yönlendirilir. Agent işlemi tamamlar veya çağrıyı uygun geri arama listesine alır. Bu senaryo, kaynak verimli mimarinin esnek ölçeklenmesini gerektirir.

---

## 9. Fonksiyonel Gereksinimler

Öncelikler MoSCoW yöntemiyle belirlenmiştir: Must (zorunlu), Should (olmalı), Could (olabilir).

### 9.1 Tenant ve Organizasyon Yönetimi

| ID | Gereksinim | Öncelik |
|----|-----------|---------|
| FR-TEN-001 | Platform birden fazla kurumsal müşteriyi tenant bazında yönetmelidir. | Must |
| FR-TEN-002 | Her tenant'ın verisi, konfigürasyonu, çağrısı ve anahtarları mantıksal olarak izole edilmelidir. | Must |
| FR-TEN-003 | Tenant altında marka, departman, ülke ve proje yapıları oluşturulabilmelidir. | Must |
| FR-TEN-004 | Tenant bazında dil, saat dilimi, veri bölgesi ve saklama politikası seçilebilmelidir. | Must |
| FR-TEN-005 | Dedicated tenant ve shared tenant seçenekleri desteklenmelidir. | Should |
| FR-TEN-006 | Tenant bazında kullanım limiti, eş zamanlı çağrı ve CPS kotası tanımlanmalıdır. | Must |
| FR-TEN-007 | Tenant bazında kaynak kotası (vCPU/bellek/eşzamanlılık) tanımlanmalı ve aşımı engellenmelidir. | Must |

> **Panel kapsamı:** Tenant yaşam döngüsü işlemleri — tenant oluşturma/askıya alma/silme, plan atama, kaynak kotası tanımı (FR-TEN-001, FR-TEN-006, FR-TEN-007) — **Platform Admin Console (L0)** üzerinden yürütülür. Tenant içi organizasyon yapısı (marka/departman/ülke/proje, FR-TEN-003) ve tenant'a özel dil/bölge/saklama tercihleri (FR-TEN-004) **Tenant Admin Console (L1)** üzerinden yönetilir. Panel mimarisi Bölüm 17'dedir.

### 9.2 Kullanıcı ve Yetkilendirme (IAM)

| ID | Gereksinim | Öncelik |
|----|-----------|---------|
| FR-IAM-001 | Role-Based Access Control (RBAC) desteklenmelidir. | Must |
| FR-IAM-002 | SAML 2.0 ve OpenID Connect ile kurumsal SSO desteklenmelidir. | Must |
| FR-IAM-003 | Çok faktörlü kimlik doğrulama (MFA) desteklenmelidir. | Must |
| FR-IAM-004 | Agent oluşturma, yayınlama ve canlı çağrı izleme yetkileri ayrılmalıdır. | Must |
| FR-IAM-005 | Kritik değişikliklerde maker-checker / onay mekanizması bulunmalıdır. | Should |
| FR-IAM-006 | Kullanıcı işlemleri değiştirilemez audit log'a kaydedilmelidir. | Must |
| FR-IAM-007 | SCIM üzerinden kullanıcı provisioning desteklenmelidir. | Should |
| FR-IAM-008 | Roller ve erişim, üç panel katmanına (L0 Platform Admin / L1 Tenant Admin / L2 Operasyon) göre ayrı tanımlanmalı; platform rolleri (L0) tenant rollerinden bağımsız olmalı ve tenant'ın iş içeriğine (çağrı kaydı, transkript, müşteri/PII verisi) varsayılan olarak erişememelidir. | Must |
| FR-IAM-009 | Platform tarafından tenant iş içeriğine erişim ancak açık gerekçeli, süreli ve audit'li bir break-glass (acil erişim) mekanizması ile yapılabilmelidir. Break-glass üç katmanlıdır: (A) metrik/log (PII'sız) için break-glass gerekmez; (B) transkript/kayıt/PII için maker-checker (talep eden ≠ onaylayan), time-boxed erişim (varsayılan 60 dk, max 4 saat, otomatik sonlanma, standing access yok), zorunlu gerekçe kodu ve tenant'ın `security_compliance_officer` + `tenant_owner` rollerine anlık bildirim. | Must |
| FR-IAM-010 | Regüle tenant'lar (ör. finans, sağlık) için break-glass Tier B'de "tenant onayı zorunlu" toggle'ı bulunmalı; regulated compliance profile'da varsayılan açık olmalı ve DPA'ya bağlanmalıdır (controller=tenant, processor=RMC). | Must |
| FR-IAM-011 | Roller sabit bir permission bundle olmalı; esneklik, rol atamasının scope filtresiyle (departman/marka/kampanya kapsamı) daraltılmasıyla sağlanmalıdır. Tam custom permission rolleri kapsam dışıdır (yalnız Faz 3, enterprise/dedicated tier, şablonla). | Must |

> **Panel kapsamı:** RBAC rolleri Bölüm 17.2'de tanımlanır; ekran–panel–rol erişim matrisi Bölüm 17.6'da, izolasyon ve görünürlük kuralları Bölüm 17.7'dedir.

### 9.3 Agent Oluşturma ve Yaşam Döngüsü

| ID | Gereksinim | Öncelik |
|----|-----------|---------|
| FR-AGT-001 | Kullanıcı kod yazmadan Voice AI agent oluşturabilmelidir. | Must |
| FR-AGT-002 | Agent için isim, amaç, kişilik, dil ve iş kuralları tanımlanabilmelidir. | Must |
| FR-AGT-003 | Single-prompt ve node/flow tabanlı konuşma modelleri desteklenmelidir. | Must |
| FR-AGT-004 | Prompt ve workflow versiyonlanmalıdır. | Must |
| FR-AGT-005 | Draft, test, staging ve production ortamları bulunmalıdır. | Must |
| FR-AGT-006 | Yayınlanan sürüm tek işlemle önceki sürüme döndürülebilmelidir (rollback). | Must |
| FR-AGT-007 | Agent'ın aktif olacağı numara, kampanya ve saatler tanımlanmalıdır. | Must |
| FR-AGT-008 | Farklı müşteri segmentleri için aynı agent'ın varyasyonları oluşturulabilmelidir. | Should |
| FR-AGT-009 | Agent davranışına global ve tenant seviyesinde güvenlik politikaları uygulanmalıdır. | Must |
| FR-AGT-010 | Değişiklikler canlıya alınmadan önce otomatik testlerden geçmelidir. | Must |

### 9.4 Telefon ve Çağrı Yönetimi

| ID | Gereksinim | Öncelik |
|----|-----------|---------|
| FR-TEL-001 | Inbound ve outbound PSTN çağrıları desteklenmelidir. | Must |
| FR-TEL-002 | SIP trunk ve BYOC (Bring Your Own Carrier) bağlantısı desteklenmelidir. | Must |
| FR-TEL-003 | Avaya, Genesys, Cisco, Amazon Connect ve benzeri sistemlerle entegrasyon yapılabilmelidir. | Must |
| FR-TEL-004 | E.164 telefon numarası formatı kullanılmalıdır. | Must |
| FR-TEL-005 | Caller ID ve numara havuzu yönetilebilmelidir. | Must |
| FR-TEL-006 | DTMF gönderme ve algılama desteklenmelidir. | Must |
| FR-TEL-007 | Cold, warm ve whisper transfer desteklenmelidir. | Must |
| FR-TEL-008 | Kuyruk, skill ve departman bazlı aktarım yapılabilmelidir. | Must |
| FR-TEL-009 | Çağrı düşmesinde kontrollü retry veya geri arama oluşturulabilmelidir. | Should |
| FR-TEL-010 | Answering machine detection desteklenmelidir. | Must |
| FR-TEL-011 | Voicemail mesajı bırakılabilmelidir. | Should |
| FR-TEL-012 | Çağrı başlangıç ve bitiş nedenleri standart kodlarla kaydedilmelidir. | Must |
| FR-TEL-013 | Outbound arama saatleri ülke ve müşteri bazında sınırlandırılmalıdır. | Must |
| FR-TEL-014 | Do-not-call ve opt-out listeleri gerçek zamanlı kontrol edilmelidir. | Must |
| FR-TEL-015 | Silent / abandoned call oluşumunu önleyici kapasite kontrolü bulunmalıdır. | Must |

> Telefon katmanı sağlayıcıdan bağımsız tasarlanmalıdır. SIP trunk PSTN bağlantısını sağlarken, çift yönlü medya akışı telefon sesi ile gerçek zamanlı AI servisleri arasında (ör. WebSocket üzerinden) taşınabilir.

### 9.5 Gerçek Zamanlı Konuşma Motoru (RTC)

| ID | Gereksinim | Öncelik |
|----|-----------|---------|
| FR-RTC-001 | Ses paketleri streaming olarak işlenmelidir. | Must |
| FR-RTC-002 | Agent, kullanıcının sözünü kesmesini (barge-in) algılayıp konuşmayı durdurmalıdır. | Must |
| FR-RTC-003 | Kullanıcı konuşurken gereksiz ara yanıt vermemelidir. | Must |
| FR-RTC-004 | Sessizlik, tereddüt ve konuşma sonu (endpointing) dinamik algılanmalıdır. | Must |
| FR-RTC-005 | Arka plan gürültüsü ve hat kalitesi düşüşü yönetilmelidir. | Must |
| FR-RTC-006 | Yankı ve agent'ın kendi sesinin tekrar transkribe edilmesi önlenmelidir. | Must |
| FR-RTC-007 | "Evet", "hı hı", "bir dakika" gibi kısa ifadeler doğru yorumlanmalıdır. | Should |
| FR-RTC-008 | Konuşma hızı, ses seviyesi ve bekleme süresi ayarlanabilmelidir. | Must |
| FR-RTC-009 | Sayı, tarih, para, adres ve kodların okunması yerel dile uygun olmalıdır. | Must |
| FR-RTC-010 | Kullanıcı anlaşılmadığında kontrollü tekrar stratejisi uygulanmalıdır. | Must |
| FR-RTC-011 | Belirli sayıda üst üste anlamama durumunda insan temsilciye aktarılabilmelidir. | Must |
| FR-RTC-012 | Dil konuşma sırasında otomatik değiştirilebilmelidir. | Should |
| FR-RTC-013 | VAD/endpointing edge/medya katmanında yapılarak gereksiz STT/LLM çağrıları azaltılmalıdır. | Must |

### 9.6 STT Gereksinimleri

| ID | Gereksinim | Öncelik |
|----|-----------|---------|
| FR-STT-001 | Birden fazla STT sağlayıcısı desteklenmelidir. | Must |
| FR-STT-002 | Streaming partial ve final transcript alınmalıdır. | Must |
| FR-STT-003 | Dil ve lehçe konfigüre edilebilmelidir. | Must |
| FR-STT-004 | Domain-specific vocabulary ve phrase boosting desteklenmelidir. | Must |
| FR-STT-005 | Telefon numarası, plaka, poliçe, referans numarası gibi alanlar optimize edilmelidir. | Must |
| FR-STT-006 | Confidence score üretilmelidir. | Must |
| FR-STT-007 | Düşük confidence durumunda teyit alınmalıdır. | Must |
| FR-STT-008 | STT sağlayıcısı hata verdiğinde fallback yapılmalıdır. | Must |

### 9.7 TTS Gereksinimleri

| ID | Gereksinim | Öncelik |
|----|-----------|---------|
| FR-TTS-001 | Birden fazla TTS sağlayıcısı desteklenmelidir. | Must |
| FR-TTS-002 | TTS ilk ses paketi streaming olarak başlamalıdır (low first-byte). | Must |
| FR-TTS-003 | Dil, aksan, konuşma hızı ve ton seçilebilmelidir. | Must |
| FR-TTS-004 | Sayı, tarih, para birimi ve özel isimler için pronunciation dictionary bulunmalıdır. | Must |
| FR-TTS-005 | TTS çıktısı barge-in sırasında anında kesilebilmelidir. | Must |
| FR-TTS-006 | Onaylı özel veya klonlanmış sesler kullanılabilmelidir. | Should |
| FR-TTS-007 | Ses klonlama için ses sahibinin açık izni ve kullanım kaydı tutulmalıdır. | Must |
| FR-TTS-008 | Bir TTS sağlayıcısı çalışmadığında alternatife geçilmelidir. | Must |
| FR-TTS-009 | Çağrı boyunca ses karakteri tutarlı kalmalıdır. | Must |
| FR-TTS-010 | Statik/standart anonslar (karşılama, onay, IVR ifadeleri) önbelleğe alınıp yeniden sentez maliyetinden kaçınılmalıdır. | Must |

### 9.8 LLM Orkestrasyonu

| ID | Gereksinim | Öncelik |
|----|-----------|---------|
| FR-LLM-001 | Birden fazla LLM sağlayıcısı ve model desteklenmelidir. | Must |
| FR-LLM-002 | Tenant veya use-case bazında model seçilebilmelidir. | Must |
| FR-LLM-003 | Model routing maliyet, gecikme, dil ve risk seviyesine göre yapılabilmelidir. | Must |
| FR-LLM-004 | LLM çağrılarında streaming yanıt kullanılmalıdır. | Must |
| FR-LLM-005 | Konuşma geçmişi token sınırına göre özetlenebilmelidir. | Must |
| FR-LLM-006 | System prompt kullanıcı konuşması veya bilgi tabanı içeriği tarafından değiştirilememelidir. | Must |
| FR-LLM-007 | Prompt injection ve jailbreak kontrolleri uygulanmalıdır. | Must |
| FR-LLM-008 | Kritik işlemler serbest metin yerine schema doğrulamalı tool çağrılarıyla yapılmalıdır. | Must |
| FR-LLM-009 | Model cevabı politika motorundan geçirilmelidir. | Must |
| FR-LLM-010 | Model hata verdiğinde fallback model veya deterministic flow kullanılmalıdır. | Must |
| FR-LLM-011 | Model seçimi ve kullanılan versiyon çağrı bazında kaydedilmelidir. | Must |
| FR-LLM-012 | Tenant verisinin model eğitimi için kullanılması varsayılan olarak kapalı olmalıdır. | Must |
| FR-LLM-013 | Basit/rutin turlar küçük ve hızlı modellere yönlendirilmeli; büyük model yalnızca gerektiğinde kullanılmalıdır (model tiering). | Must |
| FR-LLM-014 | Tekrarlayan sorular için semantic cache ile LLM çağrısından kaçınılabilmelidir. | Should |

### 9.9 Bilgi Tabanı ve RAG

| ID | Gereksinim | Öncelik |
|----|-----------|---------|
| FR-KB-001 | PDF, Word, HTML, metin, CSV ve web sayfası yüklenebilmelidir. | Must |
| FR-KB-002 | SharePoint, Confluence ve kurumsal doküman sistemlerine bağlanabilmelidir. | Should |
| FR-KB-003 | Bilgi kaynakları otomatik parçalanmalı, indekslenmeli ve versiyonlanmalıdır. | Must |
| FR-KB-004 | Tenant ve agent bazında farklı bilgi tabanları kullanılabilmelidir. | Must |
| FR-KB-005 | Doküman bazında erişim yetkisi uygulanmalıdır. | Must |
| FR-KB-006 | Yanıtın hangi kaynağa dayandığı izlenebilmelidir. | Must |
| FR-KB-007 | Kaynak bulunamadığında agent bilgi uydurmamalıdır. | Must |
| FR-KB-008 | Güncelliğini yitirmiş içerik otomatik işaretlenebilmelidir. | Should |
| FR-KB-009 | Soru-cevap performansı benchmark veri setiyle test edilmelidir. | Must |
| FR-KB-010 | Hassas dokümanlar genel modellerin sağlayıcı loglarında tutulmamalıdır. | Must |
| FR-KB-011 | Retrieval sonucu token açısından kısıtlanarak (top-k, trimming) LLM bağlam maliyeti azaltılmalıdır. | Must |

### 9.10 Tool ve İş Süreci Yönetimi

| ID | Gereksinim | Öncelik |
|----|-----------|---------|
| FR-TOOL-001 | REST, SOAP, GraphQL ve webhook entegrasyonları desteklenmelidir. | Must |
| FR-TOOL-002 | Tool input/output verileri JSON schema ile doğrulanmalıdır. | Must |
| FR-TOOL-003 | Timeout, retry, circuit breaker ve idempotency uygulanmalıdır. | Must |
| FR-TOOL-004 | Tool yetkileri agent bazında sınırlandırılmalıdır. | Must |
| FR-TOOL-005 | Okuma ve yazma işlemleri ayrı güvenlik seviyelerine sahip olmalıdır. | Must |
| FR-TOOL-006 | Kritik işlem öncesinde müşteri teyidi alınmalıdır. | Must |
| FR-TOOL-007 | Para, sözleşme veya kişisel veri değişikliği için ek doğrulama uygulanmalıdır. | Must |
| FR-TOOL-008 | API hatası müşteriye teknik detay vermeden açıklanmalıdır. | Must |
| FR-TOOL-009 | Başarısız işlem sonrasında duplicate işlem oluşmamalıdır. | Must |
| FR-TOOL-010 | Tool çağrıları korelasyon ID ile izlenmelidir. | Must |
| FR-TOOL-011 | Uzun süren işlemler için asenkron workflow desteklenmelidir. | Should |
| FR-TOOL-012 | Onaylanmamış endpoint'lere erişim engellenmelidir. | Must |

### 9.11 Kimlik Doğrulama

| ID | Gereksinim | Öncelik |
|----|-----------|---------|
| FR-AUTH-001 | Caller ID yalnız başına güçlü kimlik doğrulama olarak kabul edilmemelidir. | Must |
| FR-AUTH-002 | OTP, müşteri numarası ve knowledge-based verification desteklenmelidir. | Must |
| FR-AUTH-003 | Hassas işlem için step-up authentication uygulanmalıdır. | Must |
| FR-AUTH-004 | Başarısız doğrulama sayısı sınırlandırılmalıdır. | Must |
| FR-AUTH-005 | Hassas bilgiler sesli olarak tam biçimde tekrarlanmamalıdır. | Must |
| FR-AUTH-006 | Ses biyometrisi ayrı ve opsiyonel bir modül olmalıdır. | Should |
| FR-AUTH-007 | Voiceprint oluşturma açık politika ve hukuki değerlendirme gerektirmelidir. | Must |

> Ses verisi bir kişiyi benzersiz tanımak amacıyla kullanıldığında özel kategori biyometrik veri kapsamına girebilir; bu nedenle ses biyometrisi varsayılan değil, ayrı onay ve güvenlik kontrolleri gerektiren bir modül olmalıdır.

### 9.12 İnsan Temsilciye Aktarım

| ID | Gereksinim | Öncelik |
|----|-----------|---------|
| FR-HND-001 | Müşteri istediğinde insan temsilciye aktarım yapılmalıdır. | Must |
| FR-HND-002 | Düşük confidence, müşteri öfkesi veya politika ihlali aktarım tetikleyebilmelidir. | Must |
| FR-HND-003 | Agent doğru departman ve skill grubunu seçmelidir. | Must |
| FR-HND-004 | Temsilciye görüşme özeti ve toplanan bilgiler aktarılmalıdır. | Must |
| FR-HND-005 | Müşteri aynı bilgileri tekrar vermek zorunda bırakılmamalıdır. | Must |
| FR-HND-006 | Warm transfer sırasında agent temsilciye kısa bilgi verebilmelidir. | Must |
| FR-HND-007 | Temsilci bulunamazsa callback, voicemail veya ticket sunulmalıdır. | Must |
| FR-HND-008 | Aktarım başarısı ve bekleme süresi raporlanmalıdır. | Must |

### 9.13 Outbound Kampanya Yönetimi

| ID | Gereksinim | Öncelik |
|----|-----------|---------|
| FR-OUT-001 | Kampanya oluşturma ve müşteri listesi yükleme desteklenmelidir. | Must |
| FR-OUT-002 | CRM'den dinamik kampanya listesi alınabilmelidir. | Must |
| FR-OUT-003 | Arama öncesi consent ve suppression kontrolü yapılmalıdır. | Must |
| FR-OUT-004 | Ülke ve bölgeye göre arama saatleri uygulanmalıdır. | Must |
| FR-OUT-005 | Maksimum deneme sayısı ve yeniden arama aralığı belirlenmelidir. | Must |
| FR-OUT-006 | Müşterinin "bir daha aramayın" talebi anında uygulanmalıdır. | Must |
| FR-OUT-007 | Kampanya kapasitesi mevcut agent ve trunk kapasitesini aşmamalıdır. | Must |
| FR-OUT-008 | Voicemail, meşgul, cevapsız ve geçersiz numara ayrı kaydedilmelidir. | Must |
| FR-OUT-009 | Kampanya script'i ve teklif versiyonu çağrı bazında kaydedilmelidir. | Must |
| FR-OUT-010 | Kampanya durdurma düğmesi bulunmalıdır. | Must |
| FR-OUT-011 | Çağrı başına disposition otomatik oluşturulmalıdır. | Must |
| FR-OUT-012 | A/B test kampanyaları desteklenmelidir. | Should |

### 9.14 Çağrı Kayıtları ve Transkript

| ID | Gereksinim | Öncelik |
|----|-----------|---------|
| FR-REC-001 | Kayıt politikası tenant, ülke ve use-case bazında belirlenmelidir. | Must |
| FR-REC-002 | Ses kaydı tamamen kapatılabilmelidir. | Must |
| FR-REC-003 | Tek veya çift kanallı kayıt desteklenmelidir. | Must |
| FR-REC-004 | Transkript üzerinde PII redaction uygulanmalıdır. | Must |
| FR-REC-005 | Kart, parola ve OTP bilgileri kayıt ve transkriptten çıkarılmalıdır. | Must |
| FR-REC-006 | Saklama süresi otomatik uygulanmalıdır. | Must |
| FR-REC-007 | Legal hold desteği bulunmalıdır. | Should |
| FR-REC-008 | Yetkili kullanıcı çağrıyı dinleyebilmeli ve transkripti görebilmelidir. | Must |
| FR-REC-009 | Kayıt ve transkript erişimleri audit edilmelidir. | Must |
| FR-REC-010 | Saklama süresi sonunda veriler geri döndürülemez biçimde silinmelidir. | Must |

### 9.15 Analitik ve Kalite Yönetimi

| ID | Gereksinim | Öncelik |
|----|-----------|---------|
| FR-ANA-001 | Tüm çağrılar otomatik kalite değerlendirmesine alınmalıdır. | Must |
| FR-ANA-002 | Çağrı sonucu, intent, disposition ve completion durumu çıkarılmalıdır. | Must |
| FR-ANA-003 | Containment ve transfer oranı raporlanmalıdır. | Must |
| FR-ANA-004 | Yanlış bilgi, tool hatası ve güvenlik ihlali tespit edilmelidir. | Must |
| FR-ANA-005 | Kullanıcı ve agent konuşma süreleri ölçülmelidir. | Must |
| FR-ANA-006 | STT, LLM, TTS ve toplam yanıt gecikmesi ayrı gösterilmelidir. | Must |
| FR-ANA-007 | Maliyet çağrı, agent, tenant ve sağlayıcı bazında raporlanmalıdır. | Must |
| FR-ANA-008 | Kritik konuşmalar otomatik işaretlenmelidir. | Must |
| FR-ANA-009 | QA ekibi çağrıya skor ve açıklama ekleyebilmelidir. | Must |
| FR-ANA-010 | Agent sürümleri arasında performans karşılaştırması yapılabilmelidir. | Must |
| FR-ANA-011 | Dashboard ve ham veri export edilebilmelidir. | Must |
| FR-ANA-012 | Gerçek zamanlı operasyon ekranı bulunmalıdır. | Must |
| FR-ANA-013 | Çağrı başına kaynak tüketimi (CPU/bellek/eşzamanlılık) raporlanmalıdır. | Must |

### 9.16 Test ve Simülasyon

| ID | Gereksinim | Öncelik |
|----|-----------|---------|
| FR-TST-001 | Agent telefon çağrısı olmadan tarayıcı üzerinden test edilebilmelidir. | Must |
| FR-TST-002 | Otomatik persona ve senaryo simülasyonu çalıştırılmalıdır. | Must |
| FR-TST-003 | Happy path, edge case ve adversarial testler desteklenmelidir. | Must |
| FR-TST-004 | Prompt değişikliğinde regression test otomatik çalışmalıdır. | Must |
| FR-TST-005 | Test sonucu belirlenen seviyenin altındaysa production yayını engellenmelidir. | Must |
| FR-TST-006 | Yük ve eş zamanlı çağrı testi yapılabilmelidir. | Must |
| FR-TST-007 | Gürültü, aksan, kesinti ve düşük hat kalitesi test edilebilmelidir. | Should |
| FR-TST-008 | Gerçek müşteri verisi kullanılmadan sentetik test verisi oluşturulabilmelidir. | Must |
| FR-TST-009 | Yük testi sırasında çağrı başına kaynak tüketimi ölçülmeli ve regresyonu raporlanmalıdır. | Must |

### 9.17 Faturalama ve Kullanım

| ID | Gereksinim | Öncelik |
|----|-----------|---------|
| FR-BIL-001 | Kullanım dakika ve saniye bazında ölçülmelidir. | Must |
| FR-BIL-002 | Telekom, STT, TTS, LLM ve platform maliyeti ayrı izlenmelidir. | Must |
| FR-BIL-003 | Tenant bazında fiyat planı tanımlanabilmelidir. | Must |
| FR-BIL-004 | Minimum ücret, kullanım kotası ve overage desteklenmelidir. | Must |
| FR-BIL-005 | Dedicated altyapı maliyetleri ayrıca faturalandırılabilmelidir. | Should |
| FR-BIL-006 | Kullanım limiti ve bütçe alarmı tanımlanabilmelidir. | Must |
| FR-BIL-007 | Fatura verileri finans sistemine aktarılabilmelidir. | Must |

### 9.18 Kaynak Verimliliği ve Performans Optimizasyonu

Bu bölüm, platformun "hızlı ama düşük kaynak tüketimli" mandasını fonksiyonel gereksinimlere dönüştürür. Amaç, düşük gecikmeyi korurken çağrı başına CPU, bellek ve GPU maliyetini minimize etmektir.

| ID | Gereksinim | Öncelik |
|----|-----------|---------|
| FR-RES-001 | Çalışma zamanı olay tabanlı / asenkron (non-blocking) olmalı; thread-per-call modeli kullanılmamalıdır. | Must |
| FR-RES-002 | Tüm ses/metin işleme streaming olmalı; tam tampona alma (full buffering) yapılmamalıdır. | Must |
| FR-RES-003 | Statik anonslar için TTS önbelleği (cache) kullanılmalı; tekrar sentez engellenmelidir. | Must |
| FR-RES-004 | Tekrarlayan niyet/sorular için semantic cache ile LLM çağrısı azaltılmalıdır. | Should |
| FR-RES-005 | Model tiering ile basit turlar küçük/hızlı modele, karmaşık turlar büyük modele yönlendirilmelidir. | Must |
| FR-RES-006 | Sağlayıcı bağlantıları için connection pooling ve kalıcı oturumlar kullanılmalıdır. | Must |
| FR-RES-007 | Boşta (idle) tenant/worker için otomatik ölçek küçültme veya scale-to-zero uygulanmalıdır. | Must |
| FR-RES-008 | Telefoni codec ve örnekleme (8 kHz) zincirinde gereksiz resampling/transcoding önlenmelidir. | Must |
| FR-RES-009 | VAD/endpointing ile ölü hava (dead air) işlenmeyerek STT/LLM yükü azaltılmalıdır. | Must |
| FR-RES-010 | Konuşma geçmişi özetlenerek ve retrieval kısıtlanarak token tüketimi düşürülmelidir. | Must |
| FR-RES-011 | Analitik, transkripsiyon sonrası işleme ve raporlama gibi gerçek zamanlı olmayan işler batch/asenkron yürütülmelidir. | Must |
| FR-RES-012 | Loglama örnekleme (sampling) ve yapılandırılmış asenkron yazımla yapılmalıdır. | Should |
| FR-RES-013 | Worker'lar için warm pool tutularak cold-start gecikmesi ve kaynak israfı azaltılmalıdır. | Should |
| FR-RES-014 | Aşırı yükte backpressure ve graceful degradation devreye girmeli; kaynak çökmesi yerine kontrollü sınırlama yapılmalıdır. | Must |
| FR-RES-015 | GPU yalnızca self-hosted model gerektiğinde kullanılmalı; mümkünse CPU/serverless çıkarım tercih edilmelidir. | Should |
| FR-RES-016 | Çağrı başına kaynak bütçesi (bellek/CPU) tanımlanmalı ve aşımı izlenmelidir. | Must |

---

## 10. Fonksiyonel Olmayan Gereksinimler

### 10.1 Performans ve Gecikme

| Metrik | Hedef |
|--------|-------|
| End-of-utterance → ilk agent sesi (P50) | ≤ 700 ms |
| End-of-utterance → ilk agent sesi (P95) | ≤ 1.200 ms |
| End-of-utterance → ilk agent sesi (P99) | ≤ 2.000 ms |
| Barge-in sonrası TTS kesilme | ≤ 200 ms |
| Basit tool çağrısı platform overhead | ≤ 100 ms |
| Agent konfigürasyon yükleme | ≤ 500 ms |
| Dashboard metrik gecikmesi | ≤ 60 saniye |
| Kritik alarm üretimi | ≤ 2 dakika |

> Bir saniyeyi aşan sürekli gecikmeler, ürünün insan benzeri konuşma hedefi açısından rekabetçi olmayacaktır.

### 10.2 Kaynak Verimliliği (Lean Runtime)

Aşağıdaki hedefler, düşük kaynak tüketimini ölçülebilir kılar. Değerler ön tasarım hedefidir ve medya işlemenin nerede yapıldığına (edge/merkez) göre değişir; pilot ile doğrulanmalıdır.

| Metrik | Ön Hedef |
|--------|----------|
| Aktif çağrı başına orkestratör bellek tüketimi (medya tamponları hariç) | ≤ ~15 MB / oturum |
| Referans işçi düğümü (8 vCPU / 16 GB) başına eş zamanlı oturum | ≥ 250–500 (medya işleme konumuna göre) |
| Steady-state çağrı başına CPU | Düşük; çekirdek paylaşımlı |
| Statik anons TTS cache hit oranı | ≥ %80 |
| Küçük/hızlı modelle karşılanan tur oranı (model tiering) | ≥ %60 hedef |
| Semantic cache ile LLM'siz karşılanan tekrar sorular | Ölçülüp artırılmalı |
| Boşta tenant için kaynak tüketimi | Scale-to-zero / minimuma yakın |
| Çağrı başına altyapı (compute) maliyeti | Sürekli ölçülüp düşürülmeli |

> Performans hedefi (10.1) ile kaynak hedefi (10.2) birlikte değerlendirilmelidir: optimizasyonlar gecikmeyi bozmadan kaynağı azaltmalıdır.

### 10.3 Ölçeklenebilirlik
- Region başına 10.000 eş zamanlı çağrı (ön hedef).
- Saniyede 100 yeni çağrı başlatma/kabul (100 CPS).
- Kısa süreli 2x trafik artışını karşılayabilme.
- Tek tenant için ayrılmış concurrency kotası ve noisy-neighbor önleme.
- Yeni worker kapasitesinin otomatik devreye alınması (autoscaling).

> Bu sayılar ön tasarım değerleridir; gerçek trunk, ülke, codec ve sağlayıcı limitleriyle kapasite planlaması yapılmalıdır.

### 10.4 Kullanılabilirlik

| Bileşen | Aylık Hedef |
|---------|-------------|
| Yönetim paneli | %99,9 |
| Voice runtime | %99,99 |
| Telephony edge | %99,99 |
| Kritik API gateway | %99,99 |
| Analytics ve raporlama | %99,9 |

### 10.5 Felaket Kurtarma (DR)

| Gereksinim | Hedef |
|-----------|-------|
| Çoklu availability zone | Zorunlu |
| Aktif-pasif bölgesel DR | İlk kurumsal sürüm |
| Aktif-aktif bölgesel çalışma | İleri sürüm |
| Kritik konfigürasyon RPO | ≤ 5 dakika |
| Analitik veri RPO | ≤ 15 dakika |
| Voice runtime RTO | ≤ 15 dakika |
| Yönetim sistemi RTO | ≤ 4 saat |
| Yıllık DR testi | En az 2 kez |

> Aktif çağrıların bölge arızasında tamamen korunması her telekom senaryosunda mümkün olmayabilir; ancak yeni çağrılar otomatik olarak sağlıklı bölgeye yönlendirilmelidir.

### 10.6 Güvenlik
- TLS ile aktarım şifrelemesi; depolamada AES-256 veya eşdeğer
- Tenant bazında ayrı encryption key; BYOK ve müşteri tarafından yönetilen anahtar
- Secrets manager kullanımı; ağ segmentasyonu
- WAF ve DDoS koruması; SIP saldırılarına karşı SBC
- Rate limiting, IP allowlist, private endpoint
- Düzenli penetration test; SAST, DAST ve dependency scanning
- SBOM üretimi; audit log bütünlüğü
- Privileged access management; incident response prosedürü

### 10.7 Veri Yerleşimi
Platform en azından UK, European Union, North America ve Middle East bölgesel çalışma modellerini desteklemelidir. Her tenant için ses kaydı, transkript, prompt, bilgi tabanı, analitik verisi, audit log, backup ve LLM/STT sağlayıcısına gönderilen içeriğin hangi bölgede tutulduğu gösterilmelidir.

---

## 11. Yüksek Seviyeli Mantıksal Mimari

Mimarinin çekirdeği bağımsız bir Conversation Orchestrator'dır. STT, TTS veya LLM'in doğrudan telefon katmanına bağlanması; sağlayıcı bağımlılığına, kontrol kaybına, düşük gözlemlenebilirliğe ve kaynak israfına yol açar.

```
PSTN / SIP / Contact Centre
   │
   ▼
Telephony Edge / SBC / Call Control
   │
   ▼
Real-Time Media Gateway
   ├── Voice Activity Detection (edge)
   ├── Noise / Echo Processing
   ├── Streaming STT
   └── Streaming TTS  (+ TTS cache)
   │
   ▼
Conversation Orchestrator   ← çekirdek (lean, asenkron)
   ├── Turn Manager
   ├── Session Memory
   ├── Policy Engine
   ├── LLM Router (model tiering + semantic cache)
   ├── Prompt Manager
   ├── RAG / Knowledge Layer
   ├── Tool Executor
   └── Human Handoff Manager
   │
   ▼
Enterprise Integration Layer
   ├── CRM / Contact Centre / ERP
   ├── Ticketing / Payment / Appointment
   └── Customer Databases

Cross-Cutting Services:
IAM · Tenant Mgmt · Audit · Observability · Analytics
Recording · Billing · Consent · Compliance · Config
Resource Manager (quota · autoscale · backpressure)
```

> Resource Manager katmanı, kaynak verimliliği prensibini işletim düzeyinde uygular: tenant kotaları, autoscaling, scale-to-zero, backpressure ve çağrı başına kaynak bütçesi.

---

## 12. Sağlayıcı Soyutlama Gereksinimi

Platform aşağıdaki kategorilerde provider adapter yapısı kullanmalıdır. BRD belirli bir sağlayıcı seçmez; seçim Solution Architecture ve vendor değerlendirme aşamasında yapılır.

| Kategori | Örnek Seçenekler |
|----------|------------------|
| Telekom | Twilio, Telnyx, Vonage, Sinch, operatör SIP trunk |
| STT | Deepgram, Google, Azure, AWS, OpenAI, Speechmatics |
| TTS | ElevenLabs, Azure, Google, AWS, OpenAI, Cartesia |
| LLM | OpenAI, Anthropic, Google, Azure OpenAI, AWS Bedrock, self-hosted |
| Vector DB | OpenSearch, PostgreSQL/pgvector, Pinecone, Weaviate |
| Contact Centre | Genesys, Avaya, Cisco, Amazon Connect, NICE |
| Observability | OpenTelemetry, Prometheus, Grafana, Datadog, Splunk |

Her adapter ortak fonksiyonları sağlamalıdır: bağlantı ve authentication, timeout, retry, circuit breaker, health check, usage metering, cost calculation, region selection, data retention control, fallback ve provider-specific error normalization.

---

## 13. Konuşma Güvenliği ve Davranış Kuralları

Agent aşağıdaki konularda serbest karar vermemelidir:
- Kredi veya sigorta uygunluk kararı
- Sağlık teşhisi
- Hukuki tavsiye
- Sözleşme iptali
- Yüksek tutarlı ödeme
- Müşteri iletişim bilgilerinin değiştirilmesi
- Banka hesabı değişikliği
- Hassas kişisel veri açıklanması
- Limit üstü iade veya ödeme kararı

Bu işlemler için: (1) kimlik doğrulama yapılmalı, (2) kurallı workflow çalıştırılmalı, (3) işlem müşteriye özetlenmeli, (4) açık teyit alınmalı, (5) gerekirse insan onayı alınmalı, (6) işlem sonucu audit log'a yazılmalıdır.

Agent bilmediği bir durumda uydurma cevap vermek yerine; bilgiyi kontrol ettiğini söylemeli, alternatif kaynağı sorgulamalı, insan temsilciye aktarmalı veya ticket oluşturmalıdır.

---

## 14. Hukuk ve Uyumluluk Gereksinimleri

### 14.1 Veri Koruma (KVKK / UK GDPR)
Platform şu yetkinlikleri desteklemelidir: işleme amacı ve hukuki dayanak tanımı, data minimisation, saklama süreleri, veri sahibi erişim talepleri, düzeltme ve silme süreçleri, model sağlayıcılarına aktarılan verilerin kaydı, uluslararası veri transferi kontrolü, Data Processing Agreement, alt işleyen listesi, DPIA şablonu ve veri ihlali bildirim süreci. Yüksek riskli kullanım durumlarında DPIA, devreye alma sürecinin parçası olmalıdır.

### 14.2 AI Olduğunu Açıklama (Transparency)
Agent çağrı başında, ülke/sektör/kayıt durumuna göre değiştirilebilir bir açıklama yapabilmelidir (örn. yapay zekâ destekli asistan olduğunu ve görüşmenin kaydedilebileceğini bildiren bir metin). AB AI Act kapsamındaki şeffaflık yükümlülükleri 2 Ağustos 2026'da uygulanmaya başlayacaktır; etkileşimli AI sistemlerinde kişilerin bir makineyle iletiştiği bildirilmelidir. AB müşterilerine hizmet verilecekse bu özellik baştan desteklenmelidir.

### 14.3 Outbound Uyumluluğu
Outbound çağrı öncesinde şu kurallar çalıştırılmalıdır: arama amacı, ülke/ülke kodu, müşterinin birey/şirket olması, consent kaynağı, consent tarihi ve kapsamı, do-not-call kaydı, izin verilen saat, son arama tarihi, maksimum deneme sayısı, kullanılacak Caller ID, kampanya/teklif versiyonu ve zorunlu açılış metni. Türkiye için İYS izin kaydı ve ETK; UK için ilgili PECR/Ofcom kuralları dikkate alınmalıdır.

### 14.4 Sektörel Uyumluluk
Platform kullanım senaryosuna göre PCI DSS, FCA kuralları, HIPAA, NHS DSP Toolkit, SOC 2, ISO 27001, ISO 27701, DORA, NIS2 ve kurumsal kayıt saklama politikalarına hazırlanmalıdır. Tümü her müşteri için zorunlu değildir; tenant'ın ülke ve sektörüne göre compliance profile seçilmelidir.

---

## 15. İzlenebilirlik ve Gözlemlenebilirlik

Her çağrı için tekil bir `correlation_id` oluşturulmalı ve şu zaman damgaları ölçülmelidir: call connected, first audio received, speech started/ended, STT partial/final, LLM request started / first token, tool request/response, TTS request / first audio, audio played, call transferred, call ended.

Saklanması gereken teknik metrikler: packet loss, jitter, codec, SIP response code, STT latency, word confidence, LLM latency, token kullanımı, tool latency, TTS latency, end-to-end response latency, barge-in sayısı, silence süresi, retry/fallback, transfer sonucu, çağrı sonlandırma nedeni, provider hata oranı, dakika başı maliyet ve çağrı başına kaynak tüketimi (CPU/bellek).

Kritik alarm örnekleri: P95 yanıt gecikmesinin 1,5 sn aşması, STT hata oranı artışı, bir LLM sağlayıcısında hata artışı, insan aktarımının başarısız olması, tool hata oranı artışı, silent call oluşması, consent kontrolünün atlanması, bilgi sızıntısı tespiti, tenant kapasitesinin %80'e ulaşması, harcama limitinin aşılması ve kaynak kullanımının bütçe eşiğini aşması.

---

## 16. Veri Modeli — Ana Varlıklar

| Varlık | Açıklama |
|--------|----------|
| Tenant | Kurumsal müşteri. |
| Organisation Unit | Marka, ülke veya departman. |
| User | Yönetim paneli kullanıcısı. |
| Role | Yetki grubu. |
| Agent | Voice AI agent tanımı. |
| Agent Version | Agent'ın değişmez sürümü. |
| Prompt | Sistem ve görev talimatları. |
| Conversation Flow | Node/state tabanlı süreç. |
| Voice Profile | TTS ve konuşma ayarları. |
| Model Profile | LLM ayarları (model tiering dahil). |
| STT Profile | Transkripsiyon ayarları. |
| Knowledge Base | Bilgi kaynakları. |
| Tool | Kurumsal sistem fonksiyonu. |
| Phone Number | Inbound/outbound numara. |
| SIP Trunk | Telefon bağlantısı. |
| Campaign | Outbound kampanya. |
| Contact | Aranacak müşteri. |
| Consent | İzin kaydı. |
| Call | Çağrı üst kaydı. |
| Call Leg | Transfer dahil çağrı bacağı. |
| Transcript | Konuşma metni. |
| Recording | Ses kaydı. |
| Event | Gerçek zamanlı çağrı olayı. |
| Tool Execution | API işlem kaydı. |
| Call Evaluation | Otomatik/manuel QA sonucu. |
| Usage Record | Maliyet, kullanım ve kaynak verisi. |
| Audit Log | Kullanıcı/sistem değişiklik kaydı. |
| Incident | Operasyon olayı. |

---

## 17. Yönetim Ekranları ve Panel Mimarisi

Platform, B2B2B modeline uygun olarak üç ayrı panel katmanına bölünür. Her panel kendi erişim sınırına, varsayılan görünürlük politikasına ve kullanıcı kitlesine sahiptir. Bu bölüm panelleri, rolleri (RBAC), her paneldeki ekranları ve ekran–panel–rol erişim matrisini tanımlar.

### 17.1 Panel Mimarisi (üç katman)

Platform üç ayrı panel katmanından oluşur. Her panel ayrı bir erişim sınırına ve varsayılan görünürlük politikasına sahiptir.

| Katman | Panel | Sahibi / Kullanıcı | Kapsam |
|--------|-------|--------------------|--------|
| L0 | Platform Admin Console | Platform operatörü (RMC) | Cross-tenant: kapasite, kaynak kotaları, sağlayıcı sağlığı, platform faturalandırma, global politika |
| L1 | Tenant Admin Console | Kurumsal müşterinin admini | Tek tenant: organizasyon, kullanıcı/rol, entegrasyon, compliance, tenant faturalandırma |
| L2 | Operasyon / Uygulama Paneli | Operasyon ekibi (günlük kullanıcılar) | Tek tenant: agent tasarımı, canlı operasyon, kampanya, analitik, QA |

**Temel ilke:** L0 (platform) varsayılan olarak tenant'ın iş içeriğini (çağrı kaydı, transkript, müşteri verisi) göremez; yalnızca operasyonel/teknik metrik ve kaynak verisi görür. İçeriğe erişim ancak açık, kayıtlı (audit'li) ve süreli destek izni (**break-glass**) ile mümkün olur (FR-IAM-009).

### 17.2 Rol Tanımları (RBAC)

| Rol | Katman | Sorumluluk |
|-----|--------|------------|
| `platform_owner` | L0 | Tüm platform kontrolü; tenant yaşam döngüsü, global politika |
| `platform_sre` | L0 | Kapasite, kaynak, sağlayıcı sağlığı, release, incident (iş içeriği görmez) |
| `platform_billing` | L0 | Platform geneli faturalandırma ve rate-card |
| `tenant_owner` | L1+L2 | Tenant'ın tüm kontrolü (admin + uygulama) |
| `tenant_admin` | L1 | Kullanıcı/rol, entegrasyon, numara/SIP, konfigürasyon |
| `security_compliance_officer` | L1 | Compliance, retention, consent, audit, PII erişim kontrolü |
| `billing_viewer` | L1 | Tenant kullanım, fatura ve maliyet görünümü |
| `operations_manager` | L2 | Canlı operasyon, kampanya, tüm agent'lar, analitik (supervisor) |
| `conversation_designer` | L2 | Agent builder, flow/prompt, knowledge base, test/sim |
| `qa_analyst` | L2 | Çağrı kayıtları, transkript, QA skorlama, analitik (okuma) |
| `human_agent` | L2 | Aktarılan çağrıyı bağlamıyla devralma (yalnız kendi çağrıları) |
| `api_developer` | L1+L2 | API key/webhook, tool tanımı, sandbox |

Roller tenant bazında atanır; bir kullanıcı birden fazla role sahip olabilir. Platform rolleri (L0) tenant rollerinden tamamen ayrıdır (FR-IAM-008).

**Sabit rol seti + scope filtresi (FR-IAM-011):** Roller değişmez (immutable) permission bundle'lardır; v1'de custom permission-builder yoktur (combinatorial explosion, test ve güvenlik riski). Esneklik, rol *atamasının* bir scope filtresiyle daraltılmasıyla sağlanır — ör. bir `operations_manager` yalnız belirli departman/marka/kampanya kapsamına atanabilir. Tam custom permission rolleri Faz 3'te, yalnız enterprise/dedicated tier için ve şablonla sunulur. Bu yaklaşım "Configuration over coding" ilkesini güvenlikten taviz vermeden karşılar.

### 17.3 Platform Admin Console — Ekranlar (L0)

| ID | Ekran | Açıklama |
|----|-------|----------|
| P-01 | Platform Genel Bakış | Cross-tenant sağlık, toplam eşzamanlı çağrı, kaynak kullanımı (CPU/bellek/density), platform maliyeti |
| P-02 | Tenant Yönetimi & Provisioning | Tenant oluşturma/askıya alma/silme, plan atama, durum |
| P-03 | Kaynak & Kapasite Yönetimi | vCPU/bellek/eşzamanlılık/CPS kotaları, autoscale politikası, scale-to-zero, noisy-neighbor koruması |
| P-04 | Sağlayıcı & Entegrasyon Sağlığı | STT/TTS/LLM/telekom adapter durumu, fallback/routing varsayılanları, sağlayıcı maliyeti |
| P-05 | Platform Faturalandırma & Rate-Card | Plan tanımları, fiyatlandırma, kullanım toplulaştırma |
| P-06 | Global Politika & Guardrails | Global güvenlik politikaları, model allowlist, varsayılan compliance profilleri |
| P-07 | Platform Audit & Güvenlik | Platform geneli audit log, erişim ve güvenlik olayları |
| P-08 | Sürüm & Dağıtım (Release) Yönetimi | Platform versiyonlama, feature flag, kademeli yayma |
| P-09 | Alarm & Incident (SRE) | Platform alarmları ve incident yönetimi |

### 17.4 Tenant Admin Console — Ekranlar (L1)

| ID | Ekran | Açıklama |
|----|-------|----------|
| T-01 | Tenant Dashboard | Tenant KPI'ları, kullanım, maliyet, atanan kaynak kotası tüketimi |
| T-02 | Organizasyon & Yapı | Marka, departman, ülke, proje yapıları |
| T-03 | Kullanıcı & Rol Yönetimi | Tenant içi RBAC, SSO (SAML/OIDC) ve SCIM ayarları |
| T-04 | Telefon Numarası & SIP/Trunk | Numara havuzu, SIP trunk/BYOC, Caller ID |
| T-05 | Entegrasyon, Tool & API Key/Webhook | CRM/ticketing/ERP bağlantıları, credential, webhook tanımları |
| T-06 | Compliance & Retention | Consent, kayıt politikası, veri yerleşimi, saklama süresi, compliance profile, İYS/DNC |
| T-07 | Faturalandırma & Kullanım (tenant) | Plan, kota, overage, bütçe alarmı |
| T-08 | Audit Log (tenant kapsamı) | Tenant kullanıcı/sistem değişiklik kaydı |
| T-09 | Kaynak Kotası Görünümü | L0 tarafından atanan kapasite ve tüketimin okunması |

### 17.5 Operasyon / Uygulama Paneli — Ekranlar (L2)

| ID | Ekran | Açıklama |
|----|-------|----------|
| A-01 | Operasyon Dashboard | Canlı operasyon göstergeleri |
| A-02 | Canlı Çağrılar | Aktif çağrı izleme |
| A-03 | Agent Listesi | Tüm agent'lar ve durumları |
| A-04 | Agent Builder | Kod yazmadan agent oluşturma |
| A-05 | Conversation Flow Editor | Node/flow tabanlı süreç tasarımı |
| A-06 | Prompt Editor | Single-prompt tasarımı ve versiyonlama |
| A-07 | Voice & Model Ayarları | Agent bazında ses/model/STT profili (model tiering dahil) |
| A-08 | Knowledge Base | Bilgi kaynağı yükleme/bağlama |
| A-09 | Tool/API Bağlama | Tanımlı tool'ları agent'a bağlama (kullanım) |
| A-10 | Outbound Kampanya Yönetimi | Liste, zamanlama, consent/suppression, disposition |
| A-11 | Çağrı Kayıtları | Kayıt arama/filtreleme |
| A-12 | Çağrı Detayı / Transkript & Timeline | Çağrı zaman çizelgesi, transkript, olaylar |
| A-13 | QA Değerlendirme | Otomatik + manuel kalite skorlama |
| A-14 | Analytics & Raporlama | Containment, CSAT, AHT vb. |
| A-15 | Maliyet & Kaynak Tüketimi | Operasyonel maliyet ve çağrı başı kaynak görünümü |
| A-16 | Test & Simulation Centre | Tarayıcı testi, persona/senaryo simülasyonu, yük testi |
| A-17 | Sürüm Geçmişi (agent) | Agent versiyonları ve rollback |

### 17.6 Ekran–Panel–Rol Erişim Matrisi

Erişim seviyeleri: **Yönet** (tam) · **Düzenle** · **Görüntüle** · **—** (erişim yok).

**Platform (L0)**

| Ekran | `platform_owner` | `platform_sre` | `platform_billing` |
|-------|------------------|----------------|--------------------|
| P-01 Genel Bakış | Yönet | Görüntüle | Görüntüle |
| P-02 Tenant Provisioning | Yönet | — | — |
| P-03 Kaynak & Kapasite | Yönet | Yönet | — |
| P-04 Sağlayıcı Sağlığı | Yönet | Yönet | Görüntüle |
| P-05 Platform Faturalandırma | Görüntüle | — | Yönet |
| P-06 Global Politika | Yönet | Görüntüle | — |
| P-07 Platform Audit | Yönet | Görüntüle | — |
| P-08 Release Yönetimi | Yönet | Düzenle | — |
| P-09 Alarm & Incident | Yönet | Yönet | — |

**Tenant Admin (L1)**

| Ekran | `tenant_owner` | `tenant_admin` | `security_compliance_officer` | `billing_viewer` | `api_developer` |
|-------|----------------|----------------|-------------------------------|------------------|-----------------|
| T-01 Dashboard | Yönet | Görüntüle | Görüntüle | Görüntüle | — |
| T-02 Organizasyon | Yönet | Yönet | — | — | — |
| T-03 Kullanıcı & Rol | Yönet | Yönet | Görüntüle | — | — |
| T-04 Numara & SIP | Yönet | Yönet | — | — | Görüntüle |
| T-05 Entegrasyon/API Key | Yönet | Yönet | Görüntüle | — | Yönet |
| T-06 Compliance & Retention | Yönet | Görüntüle | Yönet | — | — |
| T-07 Faturalandırma | Yönet | Görüntüle | — | Görüntüle | — |
| T-08 Audit Log | Yönet | Görüntüle | Yönet | — | — |
| T-09 Kaynak Kotası | Görüntüle | Görüntüle | — | Görüntüle | — |

**Operasyon / Uygulama (L2)**

| Ekran | `operations_manager` | `conversation_designer` | `qa_analyst` | `human_agent` |
|-------|----------------------|-------------------------|--------------|---------------|
| A-01 Op. Dashboard | Yönet | Görüntüle | Görüntüle | — |
| A-02 Canlı Çağrılar | Yönet | — | Görüntüle | Görüntüle (kendi) |
| A-03 Agent Listesi | Yönet | Düzenle | Görüntüle | — |
| A-04 Agent Builder | Düzenle | Yönet | — | — |
| A-05 Flow Editor | Düzenle | Yönet | — | — |
| A-06 Prompt Editor | Düzenle | Yönet | — | — |
| A-07 Voice & Model | Düzenle | Yönet | — | — |
| A-08 Knowledge Base | Düzenle | Yönet | Görüntüle | — |
| A-09 Tool Bağlama | Düzenle | Düzenle | — | — |
| A-10 Outbound Kampanya | Yönet | Düzenle | Görüntüle | — |
| A-11 Çağrı Kayıtları | Yönet | Görüntüle | Görüntüle | Görüntüle (kendi) |
| A-12 Çağrı Detayı/Transkript | Yönet | Görüntüle | Yönet | Görüntüle (kendi) |
| A-13 QA Değerlendirme | Yönet | Görüntüle | Yönet | — |
| A-14 Analytics | Yönet | Görüntüle | Görüntüle | — |
| A-15 Maliyet & Kaynak | Görüntüle | — | — | — |
| A-16 Test & Simülasyon | Düzenle | Yönet | Görüntüle | — |
| A-17 Sürüm Geçmişi | Görüntüle | Yönet | — | — |

> **Not:** `tenant_owner`, L2'deki tüm ekranlarda Yönet yetkisine sahiptir (matrise ayrıca eklenmemiştir; kural 17.7'de belirtilir).

### 17.7 Erişim, İzolasyon ve Görünürlük Kuralları

- Platform rolleri (L0) tenant'ın iş içeriğini (çağrı kaydı, transkript, müşteri/PII verisi) varsayılan olarak göremez; yalnızca metrik/kaynak verisi görür (FR-IAM-008).
- İçeriğe platform tarafından erişim **üç katmanlı break-glass** ile yönetilir (FR-IAM-009, FR-IAM-010):
  - **Tier A — metrik/log (PII yok):** Break-glass gerekmez; normal L0 erişimi + audit.
  - **Tier B — transkript/kayıt/PII:** Maker-checker zorunlu (bir RMC kişisi talep eder, başka biri onaylar) + time-boxed (varsayılan 60 dk, max 4 saat, otomatik sonlanma, **standing access yok**) + zorunlu gerekçe kodu + tenant'ın `security_compliance_officer` ve `tenant_owner` rollerine anlık bildirim.
  - **Regüle tenant'lar (finans/sağlık):** Tier B'de "tenant onayı zorunlu" toggle'ı; regulated compliance profile'da varsayılan açık. B2B2B'de veri controller'ı tenant, RMC processor'dür; bu kontrol DPA'ya bağlanır.
- Her tenant verisi diğer tenant'lardan izole edilir; panel oturumu tek tenant kapsamına bağlıdır (FR-TEN-002 ile uyumlu).
- `tenant_owner`, kendi tenant'ında L1 ve L2 ekranlarının tamamında Yönet yetkisine sahiptir.
- `human_agent` yalnızca kendisine aktarılan çağrının bağlamını görür.
- Kritik değişiklikler (FR-IAM-005 maker-checker) ilgili panelde onay akışından geçer.
- Tüm panel erişimleri ve hassas görüntülemeler audit log'a yazılır (FR-IAM-006, FR-REC-009).
- PII redaction ve kart/OTP gizleme kuralları (FR-REC-004/005) panel görüntülemelerinde de uygulanır.

---

## 18. KPI'lar

### 18.1 İş KPI'ları

| KPI | Açıklama |
|-----|----------|
| Containment rate | İnsan temsilciye aktarılmadan tamamlanan çağrı oranı. |
| Automation rate | Tam/kısmi otomasyona alınan çağrı oranı. |
| First contact resolution | İlk çağrıda sonuçlanan işlemler. |
| Average handling time | Ortalama çağrı süresi. |
| Cost per resolved call | Çözülen çağrı başına maliyet. |
| Transfer rate | İnsan temsilciye aktarılan çağrı oranı. |
| Abandonment rate | Müşteri tarafından terk edilen çağrılar. |
| Conversion rate | Outbound satış/randevu başarısı. |
| Opt-out rate | Aranmak istemeyen müşteri oranı. |
| Customer satisfaction | Çağrı sonrası memnuniyet. |
| Repeat call rate | Aynı konu için tekrar arama oranı. |

### 18.2 Teknik ve Verimlilik KPI'ları
- P50/P95/P99 yanıt gecikmesi
- STT doğruluk göstergesi
- TTS first-byte süresi
- LLM first-token süresi
- Tool başarı oranı; transfer başarı oranı
- Provider fallback oranı; çağrı düşme oranı
- Uptime; error rate
- Hallucination rate; policy violation rate
- Kritik yanlış işlem oranı
- Dakika başı toplam maliyet
- Çağrı başına CPU/bellek tüketimi
- İşçi düğümü başına eş zamanlı oturum (density)
- TTS cache hit oranı; küçük-model tur oranı
- Boşta kaynak tüketimi / scale-to-zero etkinliği

---

## 19. Kabul Kriterleri

Platformun kurumsal production kullanıma hazır kabul edilmesi için:
1. En az iki STT sağlayıcısıyla çalışmalıdır.
2. En az iki TTS sağlayıcısıyla çalışmalıdır.
3. En az iki LLM sağlayıcısıyla çalışmalıdır.
4. Birincil sağlayıcı kesildiğinde kontrollü fallback gerçekleşmelidir.
5. Inbound ve outbound çağrı tamamlanmalıdır.
6. Warm ve cold transfer başarıyla çalışmalıdır.
7. Agent CRM'den veri okuyup kontrollü işlem yapmalıdır.
8. Prompt injection testleri kritik veri sızıntısı üretmemelidir.
9. Tenant'lar arasında veri erişimi mümkün olmamalıdır.
10. P95 yanıt gecikmesi hedef sınırlar içinde olmalıdır.
11. Tasarım kapasitesinde yük testi tamamlanmalıdır.
12. Çağrı kaydı ve transkript retention politikası uygulanmalıdır.
13. PII redaction testleri geçilmelidir.
14. Outbound consent ve opt-out kontrolleri doğrulanmalıdır.
15. Agent sürümü rollback edilebilmelidir.
16. Tüm kritik işlemler audit log'da görünmelidir.
17. DR senaryosu test edilmelidir.
18. İnsan temsilciye özet ve bağlam aktarılmalıdır.
19. Otomatik regression testleri production yayını öncesinde çalışmalıdır.
20. Güvenlik penetration testinde açık kritik bulgu kalmamalıdır.
21. Yük altında çağrı başına kaynak tüketimi hedef bütçe içinde kalmalıdır.
22. İşçi düğümü başına eş zamanlı oturum yoğunluğu hedefi karşılanmalıdır.

---

## 20. Fazlandırma

### Faz 1 — Core Voice Runtime ve Pilot
- Inbound çağrı; tek telekom sağlayıcısı
- İki STT/TTS/LLM adapter'ı
- Agent builder; single prompt ve temel flow
- Barge-in ve turn-taking; VAD edge'de
- Knowledge base; REST API tools
- Cold/warm transfer; kayıt ve transkript
- Temel analytics; RBAC; audit log
- Lean runtime temel optimizasyonları (streaming, TTS cache, asenkron işleme)
- Bir pilot müşteri; 100–250 eş zamanlı çağrı

### Faz 2 — Enterprise Contact Centre
- Multi-tenant mimari; SSO ve SCIM
- Genesys/Avaya/Cisco entegrasyonu
- Outbound campaign manager; consent ve suppression engine
- Gelişmiş QA; simulation testing
- Provider routing ve fallback; model tiering + semantic cache
- Dedicated deployment; data residency
- Resource Manager (kota, autoscale, scale-to-zero)
- 1.000–3.000 eş zamanlı çağrı

### Faz 3 — Hyperscale ve Regüle Sektörler
- Multi-region active-active; 10.000+ eş zamanlı çağrı
- PCI uyumlu ödeme akışı
- Finans, sigorta ve sağlık modülleri
- Customer-managed encryption keys; private connectivity
- Advanced policy engine; automatic agent optimisation
- Marketplace ve partner ekosistemi
- On-premise / hybrid deployment

---

## 21. Temel Riskler

| Risk | Etki | Önlem |
|------|------|-------|
| Yüksek konuşma gecikmesi | Yapay ve rahatsız edici deneyim | Streaming mimari, bölgesel edge, model routing. |
| STT yanlış anlaması | Yanlış işlem | Confidence kontrolü ve teyit. |
| LLM hallucination | Yanlış bilgi | RAG, policy engine, deterministic workflow. |
| Provider bağımlılığı | Fiyat ve kesinti riski | Adapter ve fallback yapısı. |
| API işleminin iki kez yapılması | Finansal/operasyonel hata | Idempotency key. |
| İnsan aktarımının başarısız olması | Müşteri kaybı | Çoklu transfer yolu ve callback. |
| Tenant veri sızıntısı | Kritik güvenlik ihlali | Güçlü izolasyon ve test. |
| Outbound izin ihlali | Ceza ve itibar kaybı | Consent engine; İYS/PECR kontrolü. |
| Ses klonunun kötüye kullanımı | Dolandırıcılık ve itibar riski | Onay, watermark ve kullanım kontrolü. |
| Ölçek büyüdükçe maliyet artışı | Düşük kârlılık | Model routing, cache ve kaynak verimliliği; maliyet dashboard'u. |
| Yüksek kaynak tüketimi / düşük yoğunluk | Yüksek çağrı başı maliyet | Lean runtime, density hedefleri, autoscale/scale-to-zero. |
| Prompt değişikliğinin davranışı bozması | Production hatası | Versiyonlama ve regression test. |
| Çok ülkede mevzuat | Operasyonel karmaşıklık | Country compliance profiles. |
| Müşterinin AI'ı insan sanması | Güven ve mevzuat riski | Açık AI bildirimi. |
| Gürültülü telefon hatları | Düşük doğruluk | Noise processing ve özel test seti. |

---

## 22. Açık Kararlar

Solution Architecture aşamasında kesinleştirilmelidir:
1. İlk hedef ülke ve sektör
2. İlk pilot use-case
3. Beklenen eş zamanlı çağrı sayısı
4. Inbound/outbound trafik oranı
5. Ana telekom sağlayıcısı
6. SIP trunk mı, managed telephony mi
7. İlk desteklenecek diller
8. Private cloud / SaaS önceliği
9. Kayıt ve transkript saklama süreleri
10. Müşteriye özel ses kullanımı
11. PCI kapsamına girilip girilmeyeceği
12. İlk contact-centre entegrasyonu
13. İnsan temsilci desktop entegrasyonu
14. SaaS fiyatlandırma modeli
15. İlk sürümün AI disclosure politikası
16. LLM sağlayıcılarına veri gönderim politikası
17. Model loglarının tamamen kapatılması gereği
18. Agent'ın yapabileceği maksimum işlem risk seviyesi
19. Medya işlemenin edge'de mi merkezde mi yapılacağı (kaynak/gecikme dengesi)
20. Self-hosted model ve GPU kullanımının kapsamı

---

## 23. Sözlük

| Terim | Açıklama |
|-------|----------|
| STT / TTS / LLM | Speech-to-Text / Text-to-Speech / Large Language Model. |
| Orchestrator | STT, LLM, TTS ve tool'ları gerçek zamanlı koordine eden çekirdek katman. |
| Barge-in | Kullanıcının ajan konuşurken araya girip kesebilmesi. |
| VAD / Endpointing | Konuşma var/yok ve konuşma sonu tespiti. |
| Containment | Çağrının insana devredilmeden AI ile tamamlanması. |
| Handoff / Transfer | Çağrının insan temsilciye aktarımı (cold/warm/whisper). |
| RAG | Retrieval-Augmented Generation — bilgi tabanına dayalı yanıt üretimi. |
| Model tiering / routing | Tur karmaşıklığına göre küçük/büyük model seçimi. |
| Semantic cache | Anlamca benzer sorulara LLM çağırmadan yanıt önbelleği. |
| Density | Birim donanım başına eş zamanlı çağrı/oturum sayısı. |
| Scale-to-zero | Boşta kaynakların sıfıra yakın indirilmesi. |
| Backpressure | Aşırı yükte kontrollü sınırlama mekanizması. |
| CPS | Calls Per Second — saniyedeki çağrı sayısı. |
| BYOC / BYOK | Bring Your Own Carrier / Key. |
| İYS / ETK | İleti Yönetim Sistemi / Elektronik Ticaret Kanunu (Türkiye). |
| KVKK / GDPR | Kişisel veri koruma mevzuatı (TR / UK-EU). |
| DTMF | Telefon tuş tonu. |
| RPO / RTO | Recovery Point / Time Objective. |
| Panel (L0/L1/L2) | Üç katmanlı panel mimarisi: L0 Platform Admin Console (cross-tenant), L1 Tenant Admin Console (tek tenant yönetimi), L2 Operasyon / Uygulama Paneli (günlük operasyon). |
| Break-glass | Platformun tenant iş içeriğine yalnızca açık gerekçeli, süreli ve audit'li acil erişim mekanizması ile ulaşması. |
| RBAC rol | Rol Tabanlı Erişim Kontrolünde panel katmanına göre tanımlı yetki grubu (ör. `platform_owner`, `tenant_admin`, `operations_manager`); bkz. Bölüm 17.2. |

---

## 24. BRD Sonucu ve Sonraki Adımlar

Ürünün çekirdeği beş katmandan oluşur: (1) telephony ve real-time media, (2) conversation orchestration, (3) LLM/STT/TTS/RAG soyutlama, (4) enterprise tool ve workflow, (5) security/compliance/analytics/operations.

En kritik mimari karar, TTS–STT–LLM servislerini doğrudan birbirine bağlamak yerine bunların üzerinde bağımsız bir Conversation Orchestrator geliştirmektir. Ürünün asıl fikrî mülkiyeti ve rekabet avantajı burada olacaktır: turn-taking, context management, provider routing, tool execution, policy enforcement, human handoff, latency optimisation, kaynak verimliliği, testing, observability ve failure recovery.

Kaynak verimliliği (lean runtime) bu BRD'de birinci sınıf bir gereksinim olarak ele alınmıştır; düşük gecikme ile düşük çağrı başı maliyetin birlikte sağlanması ürünün ticari farklılaşmasının temelidir.

Bir sonraki doğru doküman, bu BRD'ye bağlı **Solution Architecture Document (SAD)**, ardından **System Requirements Specification (SRS)** ve ayrıntılı veri tabanı/API tasarımıdır.
