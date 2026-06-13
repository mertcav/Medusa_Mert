# İzlenebilirlik Matrisi (Requirements Traceability Matrix — RTM)
## Kurumsal Sesli Yapay Zekâ Asistanı Platformu — Enterprise Voice AI Agent Platform

**FR ↔ SRS ↔ Test Case ↔ WBS dört-yönlü izlenebilirlik**
Inbound & Outbound | Multi-Tenant | Vendor-Neutral | Human Handoff

> RMC TECHNOLOGY & CONSULTANCY — rmctech.co.uk

---

## Doküman Bilgileri

| Alan | Değer |
|------|-------|
| Doküman Adı | Kurumsal Sesli Yapay Zekâ Asistanı Platformu — İzlenebilirlik Matrisi (RTM) |
| Doküman Tipi | Requirements Traceability Matrix (RTM) |
| Hedef Ürün | Multi-Tenant Enterprise Voice AI Agent Platform |
| Kaynak Dokümanlar | `docs/BRD.md` (v2.1) · `docs/SAD.md` (v1.1) · `docs/SRS.md` (v1.0) · `docs/todo_list.md` (WBS) |
| Amaç | Her iş gereksinimini (FR/NFR) sistem gereksinimine (SR), doğrulanabilir test-case'e ve WBS görevine bağlamak; çift yönlü kapsama (coverage) ve boşluk (gap) görünürlüğü sağlamak |
| Sürüm | 1.0 |
| Tarih | 13 Haziran 2026 |
| Durum | İncelemeye Hazır |
| Gizlilik | Gizli — Yalnızca yetkili paydaşlar |

### Sürüm Geçmişi

| Sürüm | Tarih | Açıklama |
|-------|-------|----------|
| 1.0 | 13.06.2026 | İlk sürüm. 193 FR + 7 NFR alanı → 236 SR → 236 baz test-case → 168 WBS görevi dört-yönlü izlenebilirliğe bağlandı. İleri (FR→SR→TC→WBS) ve ters (kapsama/boşluk) yön üretildi; BRD §19 kabul kapısı eşlemesi eklendi. 12 örtük (dolaylı kapsanan) FR ve 1 gerçek WBS boşluğu (FR-TEL-003, CC entegrasyonu) işaretlendi. WBS 0.1.2. |

---

## İçindekiler

1. [Giriş](#1-giriş)
2. [Kimlik Şemaları ve Test-Case Türetme Kuralı](#2-kimlik-şemaları-ve-test-case-türetme-kuralı)
3. [Kapsama Özeti (Coverage Dashboard)](#3-kapsama-özeti-coverage-dashboard)
4. [İleri Matris — FR → SR → Test Case → WBS](#4-i̇leri-matris--fr--sr--test-case--wbs)
5. [NFR Matrisi — NFR → SR → Test Case → WBS](#5-nfr-matrisi--nfr--sr--test-case--wbs)
6. [Ters İzlenebilirlik ve Boşluk Analizi](#6-ters-i̇zlenebilirlik-ve-boşluk-analizi)
7. [Kabul Kapısı Eşlemesi (BRD §19 → SR → TC → WBS)](#7-kabul-kapısı-eşlemesi-brd-19--sr--tc--wbs)
8. [Bakım Kuralı ve Üretim Yöntemi](#8-bakım-kuralı-ve-üretim-yöntemi)
9. [Sonuç ve Sonraki Adımlar](#9-sonuç-ve-sonraki-adımlar)

---

## 1. Giriş

### 1.1 Amaç
Bu doküman, BRD'deki (v2.1) iş gereksinimlerinin (FR/NFR) **eksiksiz ve çift yönlü** izlenebilirliğini
sağlar: her gereksinim → bir sistem gereksinimine (SR, `docs/SRS.md`), her SR → doğrulanabilir bir
test-case'e, her gereksinim → bir veya daha çok WBS görevine (`docs/todo_list.md`) bağlanır. Amaç,
"hangi gereksinim nasıl doğrulanıyor ve hangi görevle inşa ediliyor?" sorusunu tek bakışta
yanıtlamak ve kapsanmayan (orphan) gereksinim/test/görev bırakmamaktır.

### 1.2 Kapsam
Matris, BRD §9'daki tüm 193 FR'yi ve §10'daki 7 NFR alanını kapsar. SR tarafı SRS v1.0'dan,
test-case tarafı SR'lerin doğrulama yöntemi + kabul ölçütünden türetilir; WBS tarafı todo_list.md
görev izlerinden (`→FR-*` / `→NFR *`) çıkarılır.

### 1.3 Çelişki kuralı
Bir satır ile kaynak doküman arasında çelişki olursa **BRD/SAD esastır**; ardından SRS, sonra bu
matris düzeltilir ve sürüm geçmişi güncellenir (CLAUDE.md kuralı). FR-ID/SR-ID şeması **bozulmaz**.

### 1.4 Referanslar
- `docs/BRD.md` v2.1 — FR/NFR kaynağı (çelişkide esastır).
- `docs/SAD.md` v1.1 — mimari, ADR'ler.
- `docs/SRS.md` v1.0 — SR'ler (FR↔SR ayağının kaynağı).
- `docs/todo_list.md` — WBS; bu doküman görev **0.1.2**'dir.

---

## 2. Kimlik Şemaları ve Test-Case Türetme Kuralı

### 2.1 Mevcut şemalar (değiştirilmez)
- **FR-ID:** `FR-<ALAN>-NNN` (BRD). 193 FR, 18 alan.
- **SR-ID:** `SR-<ALAN>-NNN` (SRS). `<ALAN>` kaynak FR/NFR alanını yansıtır. 236 SR.
- **NFR:** `NFR 10.1..10.7` (BRD §10): PERF/DEN/SCAL/AVL/DR/SEC/LOC.
- **WBS-ID:** Hiyerarşik numara (`0.1.2`, `12.3.2`) — todo_list.md.

### 2.2 Test-Case ID şeması (bu dokümanla tanımlanır)
`TC-<ALAN>-NNN`. **Baz kural:** her SR, en az bir test-case üretir ve baz test-case ID'si ilgili
SR ile birebir hizalanır: `SR-XXX-NNN ⇒ TC-XXX-NNN`. Böylece SR ↔ TC izlenebilirliği numara
düzeyinde görünürdür. QA, gerektiğinde bir SR'yi birden çok somut test-case'e (`TC-XXX-NNN-a/-b`)
bölebilir; bu matris **baz (kapsama) test-case** düzeyini tutar.

### 2.3 Test türü, SR doğrulama yönteminden devralınır
| SR Yöntemi | TC Türü | Otomasyon / Kanıt |
|-----------|---------|-------------------|
| **T** (Test) | unit · integration · e2e · load · security | Otomatik test paketi (CI). |
| **D** (Demonstration) | senaryo/e2e demo | Çalışan sistemde gösterim kaydı. |
| **A** (Analysis) | metrik/trace/log analizi | Gözlemlenebilirlik panosu / hesap. |
| **I** (Inspection) | kod/konfig/şema/doküman review | Review checklist + kanıt linki. |

### 2.4 Öncelik
MoSCoW kaynak FR/NFR'den devralınır. Bu görev (0.1.2) `Must`; matris **tüm** önceliklerdeki
gereksinimleri izler (faz/öncelik kırılımı WBS'te tutulur).

---

## 3. Kapsama Özeti (Coverage Dashboard)

| Metrik | Değer | Not |
|--------|-------|-----|
| Toplam FR (BRD §9) | **193** | 18 alan |
| Toplam NFR alanı (BRD §10) | **7** | PERF/DEN/SCAL/AVL/DR/SEC/LOC |
| Toplam SR (SRS v1.0) | **236** | FR+NFR doğrulanabilir indirgemesi |
| Toplam baz Test-Case | **236** | SR ile 1:1 baz hizalama (§2.2) |
| SR atıfı olan WBS görevi | **168** | `→FR-*` / `→NFR *` izli görevler |
| **SR'siz FR (orphan)** | **0** | Tüm FR'ler ≥1 SR'ye iner ✔ |
| Doğrudan WBS atıfı olan FR | **181 / 193** | %93,8 |
| Örtük (dolaylı kapsanan) FR | **12** | Bkz. §6.2 — kapsayan görev belirtildi |
| **Gerçek WBS boşluğu** | **1** | FR-TEL-003 (CC entegrasyonu) — yeni görev gerekli |
| BRD §19 kabul kriteri eşlemesi | **22 / 22** | Tümü SR+TC'ye bağlı ✔ |

> **Yorum:** FR→SR kapsaması **%100** (orphan yok). FR→WBS kapsaması %93,8 doğrudan; kalan 12 FR
> mevcut bir görev tarafından örtük kapsanır (§6.2'de kapsayan WBS belirtilir). Tek **gerçek boşluk**
> FR-TEL-003'tür (contact center entegrasyonu): SR-TEL-003 mevcut ancak ayrı bir WBS görevi yok.

---

## 4. İleri Matris — FR → SR → Test Case → WBS

Her satır bir FR'yi, onu doğrulayan SR'leri, türetilen baz test-case'leri (parantezde SR yöntemi)
ve gereksinimi inşa eden WBS görev(ler)ini gösterir. `*(örtük)*` = FR doğrudan atıfla değil,
belirtilen görev tarafından dolaylı kapsanır (bkz. §6.2). Bir FR birden çok alanın SR'sinde
kaynak olabilir (ör. `FR-RES-010` → `SR-LLM-005`, `SR-KB-011`); bu satırlarda hepsi listelenir.

<!-- BEGIN-AUTOGEN: bu bölüm docs/BRD.md+SRS.md+todo_list.md'ten türetilir -->

#### FR-IAM-* — IAM, RBAC & Break-glass

| FR-ID | SR-ID(ler) | Test Case (yöntem) | WBS Görev(leri) |
|-------|------------|--------------------|-----------------|
| FR-IAM-008 | SR-IAM-008 | TC-IAM-008 (T) | 12.2.4 |
| FR-IAM-009 | SR-IAM-009 | TC-IAM-009 (T) | 12.3.1, 12.3.2, 12.3.3 |
| FR-IAM-010 | SR-IAM-010 | TC-IAM-010 (I) | 12.3.4 |
| FR-IAM-011 | SR-IAM-001, SR-IAM-011 | TC-IAM-001 (T), TC-IAM-011 (I) | 12.1.1, 12.1.3 |
| FR-IAM-001 | SR-IAM-001 | TC-IAM-001 (T) | 12.1.1 |
| FR-IAM-002 | SR-IAM-002 | TC-IAM-002 (T) | 12.1.4 |
| FR-IAM-003 | SR-IAM-003 | TC-IAM-003 (T) | 12.1.5 |
| FR-IAM-004 | SR-IAM-004 | TC-IAM-004 (I) | 12.1.1, 12.1.2 *(örtük)* |
| FR-IAM-005 | SR-IAM-005 | TC-IAM-005 (T) | 12.1.7 |
| FR-IAM-006 | SR-IAM-006 | TC-IAM-006 (T) | 12.1.8 |
| FR-IAM-007 | SR-IAM-007 | TC-IAM-007 (T) | 12.1.6 |

#### FR-TEN-* — Tenant & Organizasyon

| FR-ID | SR-ID(ler) | Test Case (yöntem) | WBS Görev(leri) |
|-------|------------|--------------------|-----------------|
| FR-TEN-001 | SR-TEN-001 | TC-TEN-001 (D) | 12.4.1 |
| FR-TEN-002 | SR-TEN-002 | TC-TEN-002 (T) | 1.2.1, 12.2.3 |
| FR-TEN-003 | SR-TEN-003 | TC-TEN-003 (T) | 12.4.3 |
| FR-TEN-004 | SR-TEN-004 | TC-TEN-004 (T) | 12.4.4 |
| FR-TEN-005 | SR-TEN-005 | TC-TEN-005 (I) | 12.4.2 |
| FR-TEN-006 | SR-TEN-006 | TC-TEN-006 (T) | 16.2 |
| FR-TEN-007 | SR-TEN-007 | TC-TEN-007 (T) | 16.2 |

#### FR-AGT-* — Agent Yaşam Döngüsü

| FR-ID | SR-ID(ler) | Test Case (yöntem) | WBS Görev(leri) |
|-------|------------|--------------------|-----------------|
| FR-AGT-001 | SR-AGT-001 | TC-AGT-001 (D) | 13.4.4 |
| FR-AGT-002 | SR-AGT-002 | TC-AGT-002 (T) | 13.4.7 |
| FR-AGT-003 | SR-AGT-003 | TC-AGT-003 (T) | 3.2.4, 13.4.5 |
| FR-AGT-004 | SR-AGT-004 | TC-AGT-004 (I) | 13.4.6 |
| FR-AGT-005 | SR-AGT-005 | TC-AGT-005 (D) | 0.4.6, 20.1 |
| FR-AGT-006 | SR-AGT-006 | TC-AGT-006 (T) | 13.4.17, 20.1 |
| FR-AGT-007 | SR-AGT-007 | TC-AGT-007 (T) | 13.4.4, 20.1 *(örtük)* |
| FR-AGT-008 | SR-AGT-008 | TC-AGT-008 (T) | 20.2 |
| FR-AGT-009 | SR-AGT-009 | TC-AGT-009 (T) | 3.3.5 |
| FR-AGT-010 | SR-AGT-010, SR-TST-005 | TC-AGT-010 (T), TC-TST-005 (T) | 18.4 |

#### FR-TEL-* — Telefoni & Çağrı Yönetimi

| FR-ID | SR-ID(ler) | Test Case (yöntem) | WBS Görev(leri) |
|-------|------------|--------------------|-----------------|
| FR-TEL-001 | SR-TEL-001 | TC-TEL-001 (D) | 2.1.2 |
| FR-TEL-002 | SR-TEL-002 | TC-TEL-002 (T) | 2.1.1, 2.1.3, 2.1.4, 4.2.5 |
| FR-TEL-003 | SR-TEL-003 | TC-TEL-003 (D) | — (YENİ GÖREV) *(örtük)* |
| FR-TEL-004 | SR-TEL-004 | TC-TEL-004 (T) | 2.1.5 |
| FR-TEL-005 | SR-TEL-005 | TC-TEL-005 (T) | 2.1.5 |
| FR-TEL-006 | SR-TEL-006 | TC-TEL-006 (T) | 2.1.6 |
| FR-TEL-007 | SR-TEL-007 | TC-TEL-007 (D) | 9.1, 9.2, 9.3 |
| FR-TEL-008 | SR-TEL-008 | TC-TEL-008 (T) | 9.5 |
| FR-TEL-009 | SR-TEL-009 | TC-TEL-009 (T) | 2.1.8 |
| FR-TEL-010 | SR-TEL-010 | TC-TEL-010 (T) | 2.1.9 |
| FR-TEL-011 | SR-TEL-011 | TC-TEL-011 (D) | 2.1.9 |
| FR-TEL-012 | SR-TEL-012 | TC-TEL-012 (I) | 2.1.7 |
| FR-TEL-013 | SR-TEL-013, SR-OUT-004 | TC-TEL-013 (T), TC-OUT-004 (T) | 10.2.3 |
| FR-TEL-014 | SR-TEL-014 | TC-TEL-014 (T) | 10.2.2 |
| FR-TEL-015 | SR-TEL-015 | TC-TEL-015 (T) | 10.2.4 |

#### FR-RTC-* — Gerçek Zamanlı Konuşma Motoru

| FR-ID | SR-ID(ler) | Test Case (yöntem) | WBS Görev(leri) |
|-------|------------|--------------------|-----------------|
| FR-RTC-001 | SR-RTC-001 | TC-RTC-001 (A) | 2.2.1 |
| FR-RTC-002 | SR-RTC-002 | TC-RTC-002 (T) | 2.2.7, 3.1.3 |
| FR-RTC-003 | SR-RTC-003 | TC-RTC-003 (T) | 3.1.3 |
| FR-RTC-004 | SR-RTC-004 | TC-RTC-004 (T) | 2.2.3 |
| FR-RTC-005 | SR-RTC-005 | TC-RTC-005 (T) | 2.2.4 |
| FR-RTC-006 | SR-RTC-006 | TC-RTC-006 (T) | 2.2.4 |
| FR-RTC-007 | SR-RTC-007 | TC-RTC-007 (T) | 3.1.3, 2.2.3 *(örtük)* |
| FR-RTC-008 | SR-RTC-008 | TC-RTC-008 (T) | 2.2.8 |
| FR-RTC-009 | SR-RTC-009 | TC-RTC-009 (T) | 3.4.1 |
| FR-RTC-010 | SR-RTC-010 | TC-RTC-010 (T) | 3.3.6 |
| FR-RTC-011 | SR-RTC-011 | TC-RTC-011 (T) | 3.3.6 |
| FR-RTC-012 | SR-RTC-012 | TC-RTC-012 (T) | 3.4.2 |
| FR-RTC-013 | SR-RTC-013 | TC-RTC-013 (A) | 2.2.3 |

#### FR-STT-* — STT

| FR-ID | SR-ID(ler) | Test Case (yöntem) | WBS Görev(leri) |
|-------|------------|--------------------|-----------------|
| FR-STT-001 | SR-STT-001 | TC-STT-001 (T) | 0.2.2, 4.2.1 |
| FR-STT-002 | SR-STT-002 | TC-STT-002 (T) | 2.2.5 |
| FR-STT-003 | SR-STT-003 | TC-STT-003 (T) | 4.2.1 *(örtük)* |
| FR-STT-004 | SR-STT-004 | TC-STT-004 (T) | 4.2.1 |
| FR-STT-005 | SR-STT-005 | TC-STT-005 (T) | 4.2.2 |
| FR-STT-006 | SR-STT-006 | TC-STT-006 (I) | 4.2.1 |
| FR-STT-007 | SR-STT-007 | TC-STT-007 (T) | 3.3.6, 4.2.1 *(örtük)* |
| FR-STT-008 | SR-STT-008 | TC-STT-008 (T) | 4.3.1 |

#### FR-TTS-* — TTS

| FR-ID | SR-ID(ler) | Test Case (yöntem) | WBS Görev(leri) |
|-------|------------|--------------------|-----------------|
| FR-TTS-001 | SR-TTS-001 | TC-TTS-001 (T) | 0.2.3, 4.2.3 |
| FR-TTS-002 | SR-TTS-002 | TC-TTS-002 (T) | 0.2.3 |
| FR-TTS-003 | SR-TTS-003 | TC-TTS-003 (T) | 4.2.3, 13.4.7 *(örtük)* |
| FR-TTS-004 | SR-TTS-004 | TC-TTS-004 (T) | 4.2.3 |
| FR-TTS-005 | SR-TTS-005 | TC-TTS-005 (T) | 4.2.3 |
| FR-TTS-006 | SR-TTS-006 | TC-TTS-006 (D) | 4.2.6 |
| FR-TTS-007 | SR-TTS-007 | TC-TTS-007 (I) | 4.2.6 |
| FR-TTS-008 | SR-TTS-008 | TC-TTS-008 (T) | 4.3.2 |
| FR-TTS-009 | SR-TTS-009 | TC-TTS-009 (A) | 4.3.2 |
| FR-TTS-010 | SR-TTS-010 | TC-TTS-010 (A) | 16.1 *(örtük)* |

#### FR-LLM-* — LLM Orkestrasyonu

| FR-ID | SR-ID(ler) | Test Case (yöntem) | WBS Görev(leri) |
|-------|------------|--------------------|-----------------|
| FR-LLM-001 | SR-LLM-001 | TC-LLM-001 (T) | 0.2.4, 4.2.4 |
| FR-LLM-002 | SR-LLM-002 | TC-LLM-002 (T) | 5.5 |
| FR-LLM-003 | SR-LLM-003 | TC-LLM-003 (A) | 5.1 |
| FR-LLM-004 | SR-LLM-004 | TC-LLM-004 (A) | 4.2.4 |
| FR-LLM-005 | SR-LLM-005 | TC-LLM-005 (T) | 3.2.2 |
| FR-LLM-006 | SR-LLM-006 | TC-LLM-006 (T) | 3.2.3 |
| FR-LLM-007 | SR-LLM-007 | TC-LLM-007 (T) | 3.3.1 |
| FR-LLM-008 | SR-LLM-008 | TC-LLM-008 (T) | 5.6 |
| FR-LLM-009 | SR-LLM-009 | TC-LLM-009 (T) | 3.3.2 |
| FR-LLM-010 | SR-LLM-010 | TC-LLM-010 (T) | 4.3.3 |
| FR-LLM-011 | SR-LLM-011 | TC-LLM-011 (I) | 5.7 |
| FR-LLM-012 | SR-LLM-012 | TC-LLM-012 (I) | 0.2.4, 5.8 |
| FR-LLM-013 | SR-LLM-013 | TC-LLM-013 (A) | 5.2 |
| FR-LLM-014 | SR-LLM-014 | TC-LLM-014 (T) | 5.4 |

#### FR-KB-* — Bilgi Tabanı & RAG

| FR-ID | SR-ID(ler) | Test Case (yöntem) | WBS Görev(leri) |
|-------|------------|--------------------|-----------------|
| FR-KB-001 | SR-KB-001 | TC-KB-001 (T) | 6.1.1 |
| FR-KB-002 | SR-KB-002 | TC-KB-002 (D) | 6.1.2 |
| FR-KB-003 | SR-KB-003 | TC-KB-003 (I) | 6.1.3 |
| FR-KB-004 | SR-KB-004 | TC-KB-004 (T) | 1.1.7 |
| FR-KB-005 | SR-KB-005 | TC-KB-005 (T) | 6.1.4 |
| FR-KB-006 | SR-KB-006 | TC-KB-006 (I) | 6.2.3 |
| FR-KB-007 | SR-KB-007 | TC-KB-007 (T) | 3.3.4 |
| FR-KB-008 | SR-KB-008 | TC-KB-008 (T) | 6.1.5 |
| FR-KB-009 | SR-KB-009 | TC-KB-009 (T) | 6.2.5 |
| FR-KB-010 | SR-KB-010 | TC-KB-010 (I) | 6.2.4 |
| FR-KB-011 | SR-KB-011 | TC-KB-011 (A) | 6.2.2 |

#### FR-TOOL-* — Tool & Entegrasyon

| FR-ID | SR-ID(ler) | Test Case (yöntem) | WBS Görev(leri) |
|-------|------------|--------------------|-----------------|
| FR-TOOL-001 | SR-TOOL-001 | TC-TOOL-001 (T) | 7.2.1, 7.2.2 |
| FR-TOOL-002 | SR-TOOL-002 | TC-TOOL-002 (T) | 7.1.1 |
| FR-TOOL-003 | SR-TOOL-003 | TC-TOOL-003 (T) | 7.1.4 |
| FR-TOOL-004 | SR-TOOL-004 | TC-TOOL-004 (T) | 7.1.2 |
| FR-TOOL-005 | SR-TOOL-005 | TC-TOOL-005 (I) | 7.1.2 |
| FR-TOOL-006 | SR-TOOL-006 | TC-TOOL-006 (T) | 7.3.2 |
| FR-TOOL-007 | SR-TOOL-007 | TC-TOOL-007 (T) | 7.3.2 |
| FR-TOOL-008 | SR-TOOL-008 | TC-TOOL-008 (T) | 7.1.5 |
| FR-TOOL-009 | SR-TOOL-009 | TC-TOOL-009 (T) | 7.1.3 |
| FR-TOOL-010 | SR-TOOL-010 | TC-TOOL-010 (A) | 7.1.6 |
| FR-TOOL-011 | SR-TOOL-011 | TC-TOOL-011 (T) | 7.2.4 |
| FR-TOOL-012 | SR-TOOL-012 | TC-TOOL-012 (T) | 7.2.3 |

#### FR-AUTH-* — Çağrı-içi Kimlik Doğrulama

| FR-ID | SR-ID(ler) | Test Case (yöntem) | WBS Görev(leri) |
|-------|------------|--------------------|-----------------|
| FR-AUTH-001 | SR-AUTH-001 | TC-AUTH-001 (I) | 8.1 |
| FR-AUTH-002 | SR-AUTH-002 | TC-AUTH-002 (T) | 8.2 |
| FR-AUTH-003 | SR-AUTH-003 | TC-AUTH-003 (T) | 8.3 |
| FR-AUTH-004 | SR-AUTH-004 | TC-AUTH-004 (T) | 8.4 |
| FR-AUTH-005 | SR-AUTH-005 | TC-AUTH-005 (T) | 8.5 |
| FR-AUTH-006 | SR-AUTH-006 | TC-AUTH-006 (I) | 8.6 |
| FR-AUTH-007 | SR-AUTH-007 | TC-AUTH-007 (I) | 8.6 |

#### FR-HND-* — İnsan Temsilciye Aktarım

| FR-ID | SR-ID(ler) | Test Case (yöntem) | WBS Görev(leri) |
|-------|------------|--------------------|-----------------|
| FR-HND-001 | SR-HND-001 | TC-HND-001 (D) | 9.4 |
| FR-HND-002 | SR-HND-002 | TC-HND-002 (T) | 9.4 |
| FR-HND-003 | SR-HND-003 | TC-HND-003 (T) | 9.5 |
| FR-HND-004 | SR-HND-004 | TC-HND-004 (D) | 9.6 |
| FR-HND-005 | SR-HND-005 | TC-HND-005 (D) | 9.6 |
| FR-HND-006 | SR-HND-006 | TC-HND-006 (D) | 9.2 |
| FR-HND-007 | SR-HND-007 | TC-HND-007 (T) | 9.7 |
| FR-HND-008 | SR-HND-008 | TC-HND-008 (A) | 9.8 |

#### FR-OUT-* — Outbound & Kampanya & Consent

| FR-ID | SR-ID(ler) | Test Case (yöntem) | WBS Görev(leri) |
|-------|------------|--------------------|-----------------|
| FR-OUT-001 | SR-OUT-001 | TC-OUT-001 (T) | 10.1.1 |
| FR-OUT-002 | SR-OUT-002 | TC-OUT-002 (T) | 10.1.2 |
| FR-OUT-003 | SR-OUT-003 | TC-OUT-003 (T) | 10.2.1 |
| FR-OUT-004 | SR-OUT-004 | TC-OUT-004 (T) | 10.2.3 |
| FR-OUT-005 | SR-OUT-005 | TC-OUT-005 (T) | 10.1.3 |
| FR-OUT-006 | SR-OUT-006 | TC-OUT-006 (T) | 10.2.2 |
| FR-OUT-007 | SR-OUT-007 | TC-OUT-007 (T) | 10.2.6 |
| FR-OUT-008 | SR-OUT-008 | TC-OUT-008 (I) | 10.1.5 |
| FR-OUT-009 | SR-OUT-009 | TC-OUT-009 (I) | 10.1.6 |
| FR-OUT-010 | SR-OUT-010 | TC-OUT-010 (D) | 10.1.7 |
| FR-OUT-011 | SR-OUT-011 | TC-OUT-011 (A) | 10.1.5 |
| FR-OUT-012 | SR-OUT-012 | TC-OUT-012 (T) | 10.1.8 |

#### FR-REC-* — Kayıt, Transkript & PII

| FR-ID | SR-ID(ler) | Test Case (yöntem) | WBS Görev(leri) |
|-------|------------|--------------------|-----------------|
| FR-REC-001 | SR-REC-001 | TC-REC-001 (I) | 11.1 |
| FR-REC-002 | SR-REC-002 | TC-REC-002 (T) | 11.1 |
| FR-REC-003 | SR-REC-003 | TC-REC-003 (I) | 11.2 |
| FR-REC-004 | SR-REC-004 | TC-REC-004 (T) | 11.4 |
| FR-REC-005 | SR-REC-005 | TC-REC-005 (T) | 11.5 |
| FR-REC-006 | SR-REC-006 | TC-REC-006 (T) | 1.2.3 |
| FR-REC-007 | SR-REC-007 | TC-REC-007 (T) | 1.2.4 |
| FR-REC-008 | SR-REC-008 | TC-REC-008 (T) | 13.4.11, 13.4.12, 11.6 *(örtük)* |
| FR-REC-009 | SR-REC-009 | TC-REC-009 (A) | 11.6 |
| FR-REC-010 | SR-REC-010 | TC-REC-010 (T) | 1.2.3 |

#### FR-ANA-* — Analitik & Kalite

| FR-ID | SR-ID(ler) | Test Case (yöntem) | WBS Görev(leri) |
|-------|------------|--------------------|-----------------|
| FR-ANA-001 | SR-ANA-001 | TC-ANA-001 (A) | 14.2.1 |
| FR-ANA-002 | SR-ANA-002 | TC-ANA-002 (A) | 14.2.2 |
| FR-ANA-003 | SR-ANA-003 | TC-ANA-003 (A) | 14.2.3 |
| FR-ANA-004 | SR-ANA-004 | TC-ANA-004 (T) | 14.2.4 |
| FR-ANA-005 | SR-ANA-005 | TC-ANA-005 (A) | 14.2.2, 14.1.2 *(örtük)* |
| FR-ANA-006 | SR-ANA-006 | TC-ANA-006 (A) | 14.1.2 *(örtük)* |
| FR-ANA-007 | SR-ANA-007 | TC-ANA-007 (A) | 14.2.9 |
| FR-ANA-008 | SR-ANA-008 | TC-ANA-008 (T) | 14.2.5 |
| FR-ANA-009 | SR-ANA-009 | TC-ANA-009 (D) | 14.2.6 |
| FR-ANA-010 | SR-ANA-010 | TC-ANA-010 (A) | 14.2.7 |
| FR-ANA-011 | SR-ANA-011 | TC-ANA-011 (T) | 14.2.8 |
| FR-ANA-012 | SR-ANA-012 | TC-ANA-012 (T) | 13.4.2, 14.1.6 |
| FR-ANA-013 | SR-ANA-013 | TC-ANA-013 (A) | 13.4.15, 14.1.3 |

#### FR-TST-* — Test & Simülasyon

| FR-ID | SR-ID(ler) | Test Case (yöntem) | WBS Görev(leri) |
|-------|------------|--------------------|-----------------|
| FR-TST-001 | SR-TST-001 | TC-TST-001 (D) | 18.1 |
| FR-TST-002 | SR-TST-002 | TC-TST-002 (T) | 18.2 |
| FR-TST-003 | SR-TST-003 | TC-TST-003 (T) | 18.2 |
| FR-TST-004 | SR-TST-004 | TC-TST-004 (T) | 18.4 |
| FR-TST-005 | SR-TST-005 | TC-TST-005 (T) | 18.4 |
| FR-TST-006 | SR-TST-006 | TC-TST-006 (T) | 0.4.8, 18.5 |
| FR-TST-007 | SR-TST-007 | TC-TST-007 (T) | 18.7 |
| FR-TST-008 | SR-TST-008 | TC-TST-008 (I) | 18.3 |
| FR-TST-009 | SR-TST-009 | TC-TST-009 (T) | 18.6 |

#### FR-BIL-* — Faturalama & Kullanım

| FR-ID | SR-ID(ler) | Test Case (yöntem) | WBS Görev(leri) |
|-------|------------|--------------------|-----------------|
| FR-BIL-001 | SR-BIL-001 | TC-BIL-001 (A) | 15.1 |
| FR-BIL-002 | SR-BIL-002 | TC-BIL-002 (A) | 4.1.3, 15.2 |
| FR-BIL-003 | SR-BIL-003 | TC-BIL-003 (T) | 15.3 |
| FR-BIL-004 | SR-BIL-004 | TC-BIL-004 (T) | 15.4 |
| FR-BIL-005 | SR-BIL-005 | TC-BIL-005 (A) | 15.6 |
| FR-BIL-006 | SR-BIL-006 | TC-BIL-006 (T) | 15.5 |
| FR-BIL-007 | SR-BIL-007 | TC-BIL-007 (T) | 15.7 |

#### FR-RES-* — Kaynak Verimliliği

| FR-ID | SR-ID(ler) | Test Case (yöntem) | WBS Görev(leri) |
|-------|------------|--------------------|-----------------|
| FR-RES-001 | SR-RES-001 | TC-RES-001 (I) | 3.1.1 |
| FR-RES-002 | SR-RTC-001, SR-RES-002 | TC-RTC-001 (A), TC-RES-002 (A) | 2.2.1, 3.1.1 *(örtük)* |
| FR-RES-003 | SR-TTS-010, SR-RES-003 | TC-TTS-010 (A), TC-RES-003 (A) | 16.1 |
| FR-RES-004 | SR-LLM-014, SR-RES-004 | TC-LLM-014 (T), TC-RES-004 (T) | 5.4 |
| FR-RES-005 | SR-LLM-013, SR-RES-005 | TC-LLM-013 (A), TC-RES-005 (A) | 5.3 |
| FR-RES-006 | SR-RES-006 | TC-RES-006 (A) | 4.1.6 |
| FR-RES-007 | SR-RES-007 | TC-RES-007 (T) | 16.4 |
| FR-RES-008 | SR-RES-008 | TC-RES-008 (A) | 2.2.2 |
| FR-RES-009 | SR-RTC-013, SR-RES-009 | TC-RTC-013 (A), TC-RES-009 (A) | 2.2.6 |
| FR-RES-010 | SR-LLM-005, SR-KB-011, SR-RES-010 | TC-LLM-005 (T), TC-KB-011 (A), TC-RES-010 (A) | 3.2.2, 6.2.2 |
| FR-RES-011 | SR-RES-011 | TC-RES-011 (I) | 16.7 |
| FR-RES-012 | SR-RES-012 | TC-RES-012 (I) | 14.1.4 |
| FR-RES-013 | SR-RES-013 | TC-RES-013 (T) | 16.3 |
| FR-RES-014 | SR-RES-014 | TC-RES-014 (T) | 16.5 |
| FR-RES-015 | SR-RES-015 | TC-RES-015 (I) | 16.9 |
| FR-RES-016 | SR-RES-016 | TC-RES-016 (T) | 3.1.4 |

<!-- END-AUTOGEN forward FR -->

---

## 5. NFR Matrisi — NFR → SR → Test Case → WBS

NFR'ler (BRD §10) alan başına gruplanır. WBS atfı NFR düzeyindedir (görev izleri `→NFR 10.x`).
Eşik değerleri SRS §5'te ve ilgili SR'nin kabul ölçütünde tutulur.


#### NFR 10.1 — Performans & Gecikme

**İlgili WBS görevleri:** 0.1.1, 0.3.2, 2.2.7, 14.1.5, 18.10

| NFR | SR-ID | Test Case (yöntem) |
|-----|-------|--------------------|
| NFR 10.1 | SR-PERF-001 | TC-PERF-001 (T) |
| NFR 10.1 | SR-PERF-002 | TC-PERF-002 (T) |
| NFR 10.1 | SR-PERF-003 | TC-PERF-003 (T) |
| NFR 10.1 | SR-PERF-004 | TC-PERF-004 (T) |
| NFR 10.1 | SR-PERF-005 | TC-PERF-005 (T) |
| NFR 10.1 | SR-PERF-006 | TC-PERF-006 (T) |
| NFR 10.1 | SR-PERF-007 | TC-PERF-007 (T) |
| NFR 10.1 | SR-PERF-008 | TC-PERF-008 (T) |

#### NFR 10.2 — Kaynak Verimliliği / Density

**İlgili WBS görevleri:** 0.3.3, 5.3

| NFR | SR-ID | Test Case (yöntem) |
|-----|-------|--------------------|
| NFR 10.2 | SR-DEN-001 | TC-DEN-001 (T) |
| NFR 10.2 | SR-DEN-002 | TC-DEN-002 (T) |
| NFR 10.2 | SR-DEN-003 | TC-DEN-003 (A) |
| NFR 10.2 | SR-DEN-004 | TC-DEN-004 (A) |
| NFR 10.2 | SR-DEN-005 | TC-DEN-005 (A) |
| NFR 10.2 | SR-DEN-006 | TC-DEN-006 (T) |

#### NFR 10.3 — Ölçeklenebilirlik

**İlgili WBS görevleri:** 16.3, 16.8, 19.5

| NFR | SR-ID | Test Case (yöntem) |
|-----|-------|--------------------|
| NFR 10.3 | SR-SCAL-001 | TC-SCAL-001 (T) |
| NFR 10.3 | SR-SCAL-002 | TC-SCAL-002 (T) |
| NFR 10.3 | SR-SCAL-003 | TC-SCAL-003 (T) |
| NFR 10.3 | SR-SCAL-004 | TC-SCAL-004 (T) |
| NFR 10.3 | SR-SCAL-005 | TC-SCAL-005 (T) |

#### NFR 10.4 — Kullanılabilirlik

**İlgili WBS görevleri:** 19.6

| NFR | SR-ID | Test Case (yöntem) |
|-----|-------|--------------------|
| NFR 10.4 | SR-AVL-001 | TC-AVL-001 (A) |
| NFR 10.4 | SR-AVL-002 | TC-AVL-002 (A) |
| NFR 10.4 | SR-AVL-003 | TC-AVL-003 (A) |
| NFR 10.4 | SR-AVL-004 | TC-AVL-004 (A) |
| NFR 10.4 | SR-AVL-005 | TC-AVL-005 (A) |

#### NFR 10.5 — Felaket Kurtarma

**İlgili WBS görevleri:** 1.2.5, 19.1, 19.2, 19.3, 19.4

| NFR | SR-ID | Test Case (yöntem) |
|-----|-------|--------------------|
| NFR 10.5 | SR-DR-001 | TC-DR-001 (I) |
| NFR 10.5 | SR-DR-002 | TC-DR-002 (T) |
| NFR 10.5 | SR-DR-003 | TC-DR-003 (T) |
| NFR 10.5 | SR-DR-004 | TC-DR-004 (T) |
| NFR 10.5 | SR-DR-005 | TC-DR-005 (T) |
| NFR 10.5 | SR-DR-006 | TC-DR-006 (T) |
| NFR 10.5 | SR-DR-007 | TC-DR-007 (I) |

#### NFR 10.6 — Güvenlik

**İlgili WBS görevleri:** 0.4.2, 0.4.4, 0.4.5, 2.1.1, 17.1.1, 17.1.2, 17.1.3, 17.1.4, 17.1.5, 17.1.6

| NFR | SR-ID | Test Case (yöntem) |
|-----|-------|--------------------|
| NFR 10.6 | SR-SEC-001 | TC-SEC-001 (T) |
| NFR 10.6 | SR-SEC-002 | TC-SEC-002 (I) |
| NFR 10.6 | SR-SEC-003 | TC-SEC-003 (T) |
| NFR 10.6 | SR-SEC-004 | TC-SEC-004 (T) |
| NFR 10.6 | SR-SEC-005 | TC-SEC-005 (T) |
| NFR 10.6 | SR-SEC-006 | TC-SEC-006 (I) |
| NFR 10.6 | SR-SEC-007 | TC-SEC-007 (T) |
| NFR 10.6 | SR-SEC-008 | TC-SEC-008 (I) |
| NFR 10.6 | SR-SEC-009 | TC-SEC-009 (T) |

#### NFR 10.7 — Veri Yerleşimi / Residency

**İlgili WBS görevleri:** 1.2.2, 4.1.4

| NFR | SR-ID | Test Case (yöntem) |
|-----|-------|--------------------|
| NFR 10.7 | SR-LOC-001 | TC-LOC-001 (T) |
| NFR 10.7 | SR-LOC-002 | TC-LOC-002 (I) |
| NFR 10.7 | SR-LOC-003 | TC-LOC-003 (A) |

---

## 6. Ters İzlenebilirlik ve Boşluk Analizi

### 6.1 SR → FR ters kontrolü (orphan SR yok)
236 SR'nin tamamı, "Kaynak" sütununda en az bir FR veya NFR'ye geri izlenir (SRS §8). Kaynaksız
(orphan) SR **bulunmamaktadır**. İkincil kaynaklı SR'ler (ör. `SR-RTC-001` → `FR-RTC-001` + `FR-RES-002`)
§4'te her iki FR satırında da görünür; böylece kaynak verimliliği FR'leri (FR-RES-*) hem kendi
alanında hem ilgili davranış SR'sinde izlenir.

### 6.2 FR → WBS boşlukları (doğrudan atfı olmayan 12 FR)
Aşağıdaki FR'ler için todo_list.md'de doğrudan `→FR-*` izi yoktur; ancak biri hariç tümü mevcut bir
görev tarafından **örtük** kapsanır. Bakım sırasında ilgili WBS satırına `→FR-*` izi eklenmesi önerilir.

| FR-ID | SR-ID | Önerilen / kapsayan WBS | Not |
|-------|-------|--------------------------|-----|
| FR-IAM-004 | SR-IAM-004 | 12.1.1, 12.1.2 | RBAC + permission-key kataloğu ayrımı; ayrı görev gerekmez |
| FR-AGT-007 | SR-AGT-007 | 13.4.4, 20.1 | Agent Builder kapsam/numara/saat alanları + yaşam döngüsü |
| FR-TEL-003 | SR-TEL-003 | — (YENİ GÖREV) | CC (Avaya/Genesys/Cisco/Amazon Connect) entegrasyonu için ayrı WBS görevi YOK → eklenmeli (öner: 2.1.10, F2) |
| FR-RTC-007 | SR-RTC-007 | 3.1.3, 2.2.3 | Turn-taking + endpointing içinde backchannel yorumu |
| FR-STT-003 | SR-STT-003 | 4.2.1 | STT adapter dil/lehçe konfigürasyonu |
| FR-STT-007 | SR-STT-007 | 3.3.6, 4.2.1 | Düşük confidence → kontrollü teyit turu |
| FR-TTS-003 | SR-TTS-003 | 4.2.3, 13.4.7 | TTS adapter + Voice/Model ayarları |
| FR-TTS-010 | SR-TTS-010 | 16.1 | TTS cache (16.1 yalnız FR-RES-003 atıfı veriyor; FR-TTS-010 atıfı eklenmeli) |
| FR-REC-008 | SR-REC-008 | 13.4.11, 13.4.12, 11.6 | Kayıt/transkript ekranları + erişim audit |
| FR-ANA-005 | SR-ANA-005 | 14.2.2, 14.1.2 | Konuşma süresi metriği analitik kapsamında |
| FR-ANA-006 | SR-ANA-006 | 14.1.2 | STT/LLM/TTS gecikme bileşenleri teknik metriklerde |
| FR-RES-002 | SR-RTC-001, SR-RES-002 | 2.2.1, 3.1.1 | Streaming pipeline (SR-RTC-001 üzerinden full-buffering yok) |

> **Aksiyon:** (1) **FR-TEL-003** için yeni WBS görevi açılmalı (öneri `2.1.10` veya §9 altında CC
> entegrasyonu, `F2`). (2) Diğer 11 FR için kapsayan WBS satırına `→FR-*` izi eklenerek doğrudan
> kapsama %100'e çıkarılmalı (FR-ID şeması korunarak).

### 6.3 WBS → FR (FR atfı olmayan görevler)
Foundation/altyapı görevlerinin bir kısmı (ör. `0.4.*` platform engineering, `19.*` HA/DR, `17.1.*`
güvenlik altyapısı) doğrudan bir FR'ye değil NFR'ye veya BRD/SAD bölümüne bağlıdır; bunlar **boşluk
değildir**, NFR matrisi (§5) ve WBS iz sütunu üzerinden izlenir.

---

## 7. Kabul Kapısı Eşlemesi (BRD §19 → SR → TC → WBS)

BRD §19'daki 22 üretim kabul kriteri, doğrulayan SR'lere, baz test-case'lere ve ilgili WBS
görevlerine bağlanır (Faz 1 inbound altkümesi için WBS Ek A esastır).

| BRD §19 | Kriter (özet) | SR(ler) | Test Case(ler) | WBS (Ek A) |
|---------|---------------|---------|----------------|------------|
| 1 | ≥2 STT | SR-STT-001 | TC-STT-001 | 0.2.2, 4.2.1 |
| 2 | ≥2 TTS | SR-TTS-001 | TC-TTS-001 | 0.2.3, 4.2.3 |
| 3 | ≥2 LLM | SR-LLM-001 | TC-LLM-001 | 0.2.4, 4.2.4 |
| 4 | Birincil kesintide fallback | SR-STT-008, SR-TTS-008, SR-LLM-010 | TC-STT-008, TC-TTS-008, TC-LLM-010 | 4.3.1, 4.3.2, 4.3.3 |
| 5 | Inbound+outbound tamamlanır | SR-TEL-001 | TC-TEL-001 | 2.1.2 |
| 6 | Warm+cold transfer | SR-TEL-007, SR-HND-004 | TC-TEL-007, TC-HND-004 | 9.1, 9.2, 9.3, 9.6 |
| 7 | CRM oku + kontrollü işlem | SR-TOOL-001, SR-TOOL-006 | TC-TOOL-001, TC-TOOL-006 | 7.2.1, 7.2.2, 7.3.2 |
| 8 | Prompt injection sızıntı yok | SR-LLM-007 | TC-LLM-007 | 3.3.1 |
| 9 | Tenant izolasyonu | SR-TEN-002 | TC-TEN-002 | 1.2.1, 12.2.3 |
| 10 | P95 gecikme | SR-PERF-002 | TC-PERF-002 | §0.3 / §18 / §19 |
| 11 | Tasarım kapasitesinde yük testi | SR-TST-006, SR-SCAL-001 | TC-TST-006, TC-SCAL-001 | 0.4.8, 18.5 |
| 12 | Retention uygulanır | SR-REC-006, SR-REC-010 | TC-REC-006, TC-REC-010 | 1.2.3 |
| 13 | PII redaction | SR-REC-004, SR-REC-005 | TC-REC-004, TC-REC-005 | 11.4, 11.5 |
| 14 | Outbound consent/opt-out | SR-OUT-003, SR-OUT-006, SR-TEL-014 | TC-OUT-003, TC-OUT-006, TC-TEL-014 | 10.2.1, 10.2.2 |
| 15 | Agent rollback | SR-AGT-006 | TC-AGT-006 | 13.4.17, 20.1 |
| 16 | Kritik işlemler audit'te | SR-IAM-006, SR-TOOL-010 | TC-IAM-006, TC-TOOL-010 | 12.1.8, 7.1.6 |
| 17 | DR senaryosu | SR-DR-002 | TC-DR-002 | §0.3 / §18 / §19 |
| 18 | Temsilciye özet/bağlam | SR-HND-004, SR-HND-005 | TC-HND-004, TC-HND-005 | 9.6 |
| 19 | Regression production öncesi | SR-TST-004, SR-TST-005 | TC-TST-004, TC-TST-005 | 18.4 |
| 20 | Pentest kritik bulgu yok | SR-SEC-009 | TC-SEC-009 | §0.3 / §18 / §19 |
| 21 | Yük altında per-call kaynak bütçede | SR-DEN-001, SR-TST-009 | TC-DEN-001, TC-TST-009 | 18.6 |
| 22 | Worker başına density hedefi | SR-DEN-002 | TC-DEN-002 | §0.3 / §18 / §19 |

---

## 8. Bakım Kuralı ve Üretim Yöntemi

- Bu matrisin **ileri/NFR/boşluk/kapsama** tabloları, kaynak dokümanlardan (`BRD.md`, `SRS.md`,
  `todo_list.md`) **türetilir**; elle düzenlenmez. Kaynak değişince yeniden üretilir.
- **Üretim:** `docs/gen_rtm.py` (repo'da) — FR'leri BRD'den, SR↔FR'yi SRS "Kaynak" sütunundan,
  WBS↔FR'yi todo_list iz referanslarından parse eder; kapsama/boşluk istatistiklerini hesaplar.
- Yeni FR → önce BRD, sonra SRS (SR), sonra WBS güncellenir; ardından matris yeniden üretilir.
- Her görev PR'ında WBS ID + ilgili FR/SR referansı verilir (todo_list Ek C).
- Faz kapısı geçişinde bu matris + WBS gözden geçirilir (todo_list Ek C).
- `.md` source of truth'tur; markalı `.docx` artifact'i **0.1.7** kapsamında `build-docx.sh` ile üretilir.

---

## 9. Sonuç ve Sonraki Adımlar

Bu RTM, 193 FR ve 7 NFR alanını 236 SR, 236 baz test-case ve 168 WBS görevine dört-yönlü bağlar;
FR→SR kapsaması %100 (orphan yok), FR→WBS doğrudan kapsaması %93,8'dir. Kalan 12 FR örtük kapsanır
ve tek gerçek boşluk (FR-TEL-003, CC entegrasyonu) işaretlenmiştir. QA test-case kataloğu, kabul
kapısı ve WBS faz gözden geçirmeleri doğrudan bu matristen beslenir.

**Sonraki adımlar (WBS):**
1. **0.1.2 takibi** — FR-TEL-003 için yeni WBS görevi; 11 örtük FR'ye doğrudan `→FR-*` izi ekle.
2. **0.1.3** — Veri tabanı tasarımı (BRD §16; SR-TEN-002 RLS zorlaması).
3. **0.1.4** — API & adapter SPI tasarımı (OpenAPI; §6 arayüz SR'leri).
4. QA — bu matristen baz test-case kataloğunu (`TC-*`) somut test paketlerine indir.

> `.md` source of truth'tur; `.docx` üretilen artifact'tir (0.1.7).
