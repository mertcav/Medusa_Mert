# WBS 9.5 — Kuyruk/skill/departman bazlı hedef seçimi (tasarım)

9. workstream'in (İnsan Temsilciye Aktarım) **beşinci** modülü · **F2 · Must** · →**FR-TEL-008, FR-HND-003**.

SAD §7.3 Human Handoff akış diyagramındaki **`Handoff Manager ──► hedef seçimi (departman/skill/kuyruk)`**
noktasını gerçekler. 9.4 (tetikleyiciler) aktarımın **ne zaman/neden** olacağına karar verir; bu modül
**nereye** (hangi departman/skill grubu/kuyruk) sorusuna karar verir; 9.1/9.2/9.3 (cold/warm/whisper)
mekanizma modülleri seçilen hedefi **taşıma** için tüketir.

## 1. Mimari konum

```
9.4 TransferDecision (reason)                Tenant config (panel CRUD):
   │                                          departman + skill_group + kuyruk envanteri
   ▼                                          + intent→departman + intent→skill + öncelik kuralları
[9.5 Hedef Seçim Motoru] ◄────────────────────────────────────────────────────────────┘
   │  RoutingRequest{intent, language, required_skills[], reason, attributes}
   │
   ├─ SELECTED ──► TargetSelection{department, skill_group, queue, priority, match_quality}
   │                  └─► 9.1/9.2/9.3 (taşıma) + 9.6 (screen-pop bağlamı) + 9.8 (raporlama)
   │
   └─ UNRESOLVED ──► 9.7 temsilci-yok fallback (callback/voicemail/ticket, FR-HND-007)
```

Motor **deterministik** bir karar fonksiyonudur: hot-path turn'ünü bloklamaz, sanal zaman, rastgele
yok. Vendor-neutral (ADR-001/002): kuyruk/skill/departman envanteri CC sağlayıcı bağımsız bir modelde;
canlı CC entegrasyonunda (11.x) aynı seçim sözleşmesi arkasına gerçek skill-based routing motoru takılır.

## 2. Durum makinesi

```
SELECTING ──(kuyruk eşleşti)──────────► SELECTED     (terminal — EMIT hedef → 9.1/9.2/9.3)
     │
     └──(hiç eşleşme + default yok)────► UNRESOLVED   (terminal — fail-safe 9.7'ye yükselt)
```

- **SELECTING:** RoutingRequest yönlendirme kurallarından geçiriliyor (departman→skill→kuyruk + öncelik
  + fallback zinciri).
- **SELECTED** (terminal): geçerli hedef `{department, skill_group, queue}` çözüldü; mekanizma modülüne
  iletildi.
- **UNRESOLVED** (terminal): hiçbir kuyruk eşleşmedi (default dahil) — örn. desteklenmeyen dil / config
  boşluğu → **fail-safe** 9.7'ye yükselir, oturum **düşmez**.

## 3. Üç yönlendirme boyutu (FR-TEL-008)

| Boyut | Anlam | Kaynak |
|-------|-------|--------|
| `department` | İş birimi (billing/tech/sales/general) | `intent → intent_to_department` kuralı (FR-HND-003) |
| `skill_group` | Yetkinlik grubu (dil/domain/tier skill'leri kapsayan) | gerekli skill'leri kapsayan kuyruğun skill grubu |
| `queue` | Fiziksel/mantıksal bekleme kuyruğu | departman + skill_group eşlemesi |

Seçilen hedef **üçünü de** taşır (R3). Skill etiketi formatı `kategori:değer` (`lang:tr`, `domain:billing`,
`tier:premium`) — yapısal, PII değil.

## 4. Sıralı fallback zinciri (R5)

| Tier | Koşul | match_quality |
|------|-------|---------------|
| 1 | Departman içinde skill grubu gerekli skill'leri (**dil dahil**) kapsayan + dili destekleyen kuyruk; **en sıkı** eşleşme (fazladan skill az), high öncelikte `priority_capable` öne | `exact` |
| 2 | exact yoksa: departmanın varsayılan kuyruğu (skill gevşetilir, **dil korunur**) | `department_default` |
| 3 | o da yoksa: tenant genel kuyruğu (catch-all) | `general_fallback` |

Bir default eşleşebilirken **çıkmaza girilmez** (broken_fallback=0). Tüm tier'lar tükenir ve hiçbiri
eşleşmezse (gerçek no-target, örn. desteksiz dil) → **UNRESOLVED → 9.7** (config hatası değil, R10).

> **Skill aşırı-eşleşme (over-match) tasarım kararı:** exact tier'da, gerekli skill'i kapsayan birden
> çok kuyruk varsa **fazladan skill'i en az** olan (en sıkı eşleşme) seçilir. Böylece sıradan bir
> billing talebi, yalnız premium gerektiğinde kullanılması gereken `q-billing-premium-tr` kuyruğunu
> boşa harcamaz. Eşitlikte: high öncelikte `priority_capable`, sonra kuyruk id sırası (deterministik).

## 5. Öncelik (R6)

9.4 reason'ı önceliğe eşlenir: `ANGER`/`POLICY` → **high** (önceliklendirilmiş kuyruk pozisyonu /
`priority_capable` kuyruk tercihi); `USER_REQUEST`/`LOW_CONFIDENCE` → **normal**. Deterministik; aynı
reason → aynı öncelik. Öncelik MÜHENDİSLİK varsayılanı; tenant config'inde ayarlanabilir (BRD §22 açık karar).

## 6. Çekirdek invariant'lar (R1–R11) — hepsi 0-ihlal HARD kapı

| # | İlke | İhlal sayacı |
|---|------|--------------|
| R1 | Seçim tamlığı/determinizm (terminal'e ulaşır; aynı girdi→aynı çıktı) | `stuck_state=0` |
| **R2** | **Doğru departman** (FR-HND-003) — intent→tenant kuralı | `wrong_department=0` |
| **R3** | **Üç boyut** (FR-TEL-008) — department+skill_group+queue | `missing_dimension=0` |
| **R4** | **Skill eşleşmesi** — exact kuyruk gerekli skill'i (dil dahil) kapsar | `mis_skill=0` |
| **R5** | **Sıralı fallback** fail-safe — default varken çıkmaza girmez | `broken_fallback=0` |
| R6 | Öncelik — reason→öncelik deterministik, high priority_capable tercih | `priority_ignored=0` |
| **R7** | **Tenant izolasyonu** (FR-TEN-002) — hedef bu tenant config'inden | `cross_tenant_target=0` |
| R8 | Her hedef kanıt taşır (match_quality + fallback_tried + skill'ler) | `missing_evidence=0` |
| R9 | Her karar audit'e yazılır (FR-IAM-006) | `missing_audit=0` |
| R10 | Fail-safe yükseltme — UNRESOLVED → 9.7; oturum düşmez | (terminal + escalation yapısal) |
| R11 | Sır/PII yok — müşteri adı/telefon/transkript tutulmaz | `secret_or_pii=0` |

## 7. Kapsam ayrımı (bilinçli, başka modül sahibi)

| Konu | Sahip |
|------|-------|
| Aktarım **mekanizması** (SIP REFER / köprü+whisper / konferans) | 9.1 / 9.2 / 9.3 (hedefi **tüketir**) |
| Aktarım **tetikleme** kararı (ne zaman/neden) | 9.4 (reason'ı **tüketir**, üretmez) |
| Bağlam paketi (özet+intent+alanlar+auth) + screen-pop | 9.6 (hedef departman/skill bağlamını tüketir) |
| Temsilci-yok callback/voicemail/ticket motoru | 9.7 (UNRESOLVED'i **yükseltir**) |
| Aktarım başarısı + bekleme raporlama | 9.8 (kuyruk/skill dağılımını tüketir) |
| Intent/niyet **üretimi** | NLU / diyalog (3.x) — intent'i **tüketir** |
| Dil tespiti **üretimi** | STT (4.x, FR-STT-005) — dil kodunu **tüketir** |
| Kuyruk/skill/departman envanteri **CRUD** | Tenant admin paneli (L1 / A-* ekranlar) — config'i **tüketir** |
| Canlı temsilci uygunluk/atama | CC entegrasyonu (11.x) — hedef seçer, atamayı CC yapar |
| Audit **store** | 7.1.6 / 12.1.8 |

## 8. Doğrulama

`validate` (statik) · `selftest` (gömülü motor invariant'ları) · `run samples` (6 pass + 6 degrade) ·
`tests/…behavior_test.py` (R1–R10 kara-kutu). Canlı CC skill-based routing testi **F2**'de gerçek
CC entegrasyonu + 9.1/9.2/9.3 ile koşar.
