# A-13 — QA Değerlendirme · WBS 13.4.13

L2 Operasyon / Uygulama Paneli'nin (A-01..A-17) **on ikinci** implemente edilen ekranı. TEK bir çağrının
**kalite değerlendirmesini** sunar: **değerlendirme özeti** (otomatik skor · band · kritik işaret · açık işaret ·
manuel inceleme · kalibrasyon), **otomatik skorkart** (FR-ANA-001 — ağırlıklı boyutlar
compliance/accuracy/resolution/tooling/communication/safety), **kritik işaretler** (FR-ANA-004/008 —
yanlış bilgi / tool hatası / güvenlik ihlali / PII sızıntısı / aktarım kaçırma / uyumluluk eksiği / düşük güven),
**manuel değerlendirme** (FR-ANA-009 — QA skor + disposition + redaction'lı açıklama; otomatik↔manuel kalibrasyon)
ve **sürüm karşılaştırması** (FR-ANA-010). **A-12'den farkı:** A-12 çağrı zaman çizelgesi + transkript İÇERİĞİNİ
(redaction + erişim audit kapısıyla) gösterir; **A-13 o çağrının türetilmiş SKOR + İŞARET + (redaction'lı) QA
açıklamasını** gösterir — transkript metnini TAŞIMAZ.

## Tutarlılık invariant'ları (ÇEKİRDEK — test edilebilirlik)
Otomatik skor SAKLANAN değil **TÜRETİLEBİLİR**:
- **`autoScoreConsistent`** (FR-ANA-001): saklanan `autoScore` ≈ ağırlıklı boyut skoru (`weightedAutoScore`;
  `|autoScore − Σ(score·weight)/Σweight| ≤ 0.02`).
- **`criticalConsistent`** (FR-ANA-008): `critical` bayrağı ≈ kritik-şiddetli işaret varlığı (`criticalFlags`).
- **`needsReview`** (FR-ANA-008): kritik konuşma VEYA açık kritik işaret VEYA fail band → manuel inceleme **zorunlu**.
- **`calibrationAgreement`** (FR-ANA-009): `|autoScore − manualScore| ≤ 0.1` (skorlanmamışsa N/A).

## Hijyen + güvenlik — İKİ KATMAN
A-13 skor/işaret/açıklama gösterdiği için **iki katmanlı** guard uygular (`assertSafe`):
1. **Yapısal anahtar** (`assertNoForbiddenKeys`): ham kimlik/iş-içeriği (ham ses, ham transkript blob, **transkript
   metni `text`**, e164/numara, müşteri PII, değerlendiren ADI, kart-OTP, çağrı özeti) + sır/credential + nesne-depo
   URI alan **ADI** taşınamaz (`FORBIDDEN_PII_KEYS` + `FORBIDDEN_SECRET_KEYS` — BRD §17.7 + NFR 10.6). **A-12'den
   farkı:** A-12 redaction'lı tur `text`ini gösterdiği için izin veriyordu; **A-13 `text` YASAK** (içerik göstermez).
   QA açıklaması `comment`/`note` İZİNLİDİR (redaction'lı).
2. **İçerik redaction** (`assertRedactionClean`): hiçbir string değer (özellikle QA `comment`/`note`) ham PII
   **DESENİ** (≥7 ardışık rakam; e-posta; `+`rakam; kart-bloğu; IBAN) taşıyamaz (`RAW_PII_PATTERNS` — FR-REC-004/005).
   PII yalnız **MASK_TOKEN `[•••]`** olarak görünür.

İşaret KANITI **yapısaldır** (tur VEKİL referansı `turnRef` — ham metin DEĞİL). Skorlama **derin aksiyondur**
(`qa:score` — API §8.1 `GET/POST /calls/{id}/evaluations`); skor/açıklama yazımı + erişim-audit backend'de (FR-REC-009).

## Kaynak gereksinimler
- **BRD §17.5** A-13 "QA Değerlendirme — Otomatik + manuel kalite skorlama".
- **FR-ANA-001** tüm çağrılar otomatik kalite değerlendirmesine alınır (otomatik skorkart).
- **FR-ANA-002/003** outcome/containment (resolution boyutu) · **FR-ANA-004** yanlış bilgi/tool hatası/güvenlik
  ihlali tespiti (kritik işaretler) · **FR-ANA-008** kritik konuşma otomatik işaretleme · **FR-ANA-009** QA skor +
  açıklama (manuel değerlendirme + kalibrasyon) · **FR-ANA-010** agent sürümleri arası performans karşılaştırması.
- **FR-REC-004/005** PII/kart-OTP redaction (QA açıklaması redaction'lı) · **FR-REC-009** erişim audit (erişim sağlığı).
- **BRD §14.2** AI bildirimi/consent (compliance boyutu) · **BRD §15** word confidence (düşük güven işareti) ·
  **FR-HND** insan aktarımı (escalation_missed) · **FR-TOOL** tool çağrısı (tooling/tool_error).
- **API §8.1** `GET/POST /calls/{id}/evaluations` (qa:score) · **BRD §17.6** RBAC · **§17.7** hijyen ·
  **FR-TEN-002** tenant scope · **NFR 10.6** sır · **ADR-002** vendor-neutral.

## RBAC (BRD §17.6 — L2 A-13 satırı)
`operations_manager`=**Yönet** · `conversation_designer`=**Görüntüle** · `qa_analyst`=**Yönet** · `human_agent`=**—**
(erişim YOK). A-12'ye göre tek fark: human_agent A-12'de Görüntüle (kendi), A-13'te erişimi yok. `tenant_owner` kural
17.7 ile Yönet. UI yalnız görsel kapı; nihai yetki + skor/açıklama yazımı + erişim-audit backend + RLS. Permission-key:
`qa:score` (+ `calls:read` çağrı META).

## Dosyalar
- `a13-qa-eval-spec.json` — kaynak doğruluk + invariant (S1..S8) + referans anahtarlar + placeholder'lar + eşikler.
- `a13_qa_eval_probe.py` — stdlib-only probe (`validate`/`check`/`selftest`/`schema`); `lib/tenant/qa-eval.ts`
  saf yardımcılarının Python aynası.
- `samples/eval-{clean,flagged}.json` — `$expect` ile sentetik sağlıklı + kritik-işaretli değerlendirme (FR-TST-008).
- `tests/a13_qa_eval_test.py` — üç kapının çıkış kodu davranış testi.
- `run_live_test.sh` — canlı smoke (next build+start+curl; credential-free).

## Çalıştırma
```
python3 a13_qa_eval_probe.py selftest    # pozitif/negatif kendi-testleri (skor tutarlılık/kritik/kalibrasyon + İKİ KATMAN guard)
python3 a13_qa_eval_probe.py check       # saf çekirdek + samples
python3 a13_qa_eval_probe.py validate    # on-disk sayfa + seam + i18n + spec (S1..S8)
python3 a13_qa_eval_probe.py schema      # görünüm şema özeti
bash run_live_test.sh                     # canlı smoke (opsiyonel; next gerektirir)
```

## Kapsam dışı (bilinçli)
- Otomatik kalite değerlendirme ÜRETİMİ (skorlama/işaretleme motoru — FR-ANA-001/004/008) → F1 §14.1; bu ekran yalnız
  motorun SONUCUNU yansıtır.
- Manuel skor/açıklama + disposition YAZIMI + erişim-audit → API §8.1 `POST /calls/{id}/evaluations` (görsel kapı).
- Transkript İÇERİĞİ (redaction'lı tur metni) → A-12 (içerik kapısı + erişim audit'le); A-13 yalnız `turnRef` vekili taşır.
- Çoklu çağrı QA kuyruğu/örnekleme + agent/dönem bazında QA panosu → A-14 Analytics (FR-ANA-003/011).
- `/workspace/qa/[callRef]` dinamik routing + çağrı seçimi → F1 (bu dilim tek temsili değerlendirmeyi besler).
- Vendor-neutral (ADR-002; belirli QA/analitik/STT markası bağlanmaz); sır/credential repoya yazılmadı.
