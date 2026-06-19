# A-11 — Çağrı Kayıtları · WBS 13.4.11

L2 Operasyon / Uygulama Paneli'nin (A-01..A-17) onuncu implemente edilen ekranı. Bir tenant'ın
**çağrı kayıtlarının (CDR) aranabilir/filtrelenebilir envanteri**: kayıt özeti (çağrı · kayıtlı ·
kayıt-kapalı · redaction-bekleyen · yasal-tutma · silinmek-üzere · çift-kanal + açık dikkat), **çağrı
kayıtları** (çağrı · yön · agent · sonuç · süre · kayıt durumu · transkript · saklama · erişim), **sonuç
dağılımı**, **kayıt durumu dağılımı** (filtre boyutu), **saklama & yasal tutma sağlığı** ve **erişim &
redaction sağlığı**. **A-12'den farkı:** A-11 (bu ekran) **arama/filtreleme** — kayıt LİSTESİ + META;
A-12 tek çağrı **detayı/transkript & timeline** (içerik). Bu ekran içerik sunmaz: çağrıyı dinleme/transkripti
görme yetkili kullanıcı için **ayrı aksiyondur** (A-12) ve **her erişim audit edilir** (FR-REC-008/009).
**Gerçek zamanlı değildir** (canlı izleme A-02).

## Kaynak gereksinimler
- **BRD §17.5** A-11 "Çağrı Kayıtları" (ekran tanımı: Kayıt arama/filtreleme).
- **FR-REC-001** — Kayıt politikası tenant/ülke/use-case bazında → `recordingState` + kayıt durumu dağılımı.
- **FR-REC-002** — Ses kaydı tamamen kapatılabilir → `recordingState="disabled"` + `recordingDisabledCalls`.
- **FR-REC-003** — Tek/çift kanallı kayıt → `channels` (0/1/2) + `dualChannelCalls`.
- **FR-REC-004** — Transkript PII redaction → `transcriptState` + `redactionPendingCalls` + erişim sağlığı.
- **FR-REC-005** — Kart/parola/OTP kayıt+transkriptten çıkarılır → erişim sağlığı "kart/OTP gizleme" satırı.
- **FR-REC-006/010** — Saklama otomatik + geri döndürülemez silme → `retentionImminentCalls` + saklama sağlığı.
- **FR-REC-007** — Legal hold → `legalHoldCalls` + `legalHoldConflictCalls` (yasal tutma retention'ı askıya alır).
- **FR-REC-008** — Yetkili kullanıcı dinler/görür → erişim sağlığı (deep action A-12; UI görsel kapı).
- **FR-REC-009** — Kayıt/transkript erişimleri audit edilir → `accessAudited` + `unauditedCalls` (INVARIANT: 0).
- **FR-ANA-002/003** — Containment/transfer outcome → `outcome` + sonuç dağılımı.
- **BRD §17.6** RBAC · **§17.7** hijyen + izolasyon · **FR-TEN-002** tenant scope · **NFR 10.6** sır ·
  **DB §19/§21/§22/§9** call/transcript/recording/retention · **ADR-002** vendor-neutral · **WBS 11.6**
  erişim-audit motoru (erişim doğrulanır, içerik akmaz).

## RBAC (BRD §17.6 — L2 A-11 satırı)
`operations_manager`=**Yönet** · `conversation_designer`=**Görüntüle** · `qa_analyst`=**Görüntüle** ·
`human_agent`=**Görüntüle (kendi)** (yalnız kendisine aktarılan çağrı — BRD §17.7). `tenant_owner` kural 17.7
ile Yönet. UI yalnız görsel kapı; nihai yetki + erişim-audit backend + RLS. Permission-key: `calls:read`.

## Hijyen + güvenlik (ÇEKİRDEK)
A-11 yalnız **ÇAĞRI META** taşır (yön/agent/sonuç/süre/kayıt-transkript-saklama-yasal-tutma-erişim bayrakları/
kanal/sahiplik + agent adı — tenant'ın KENDİ yapılandırması). Son-müşteri **ham ses kaydı byte'ı / transkript
metni / ham numara (e164) / müşteri PII / kart-OTP / nesne-depo URI'si / çağrı özeti GÖMÜLMEZ** (BRD §17.7 +
FR-REC-004/005 + NFR 10.6). İki katman: (1) yapısal `FORBIDDEN_PII_KEYS` + `FORBIDDEN_SECRET_KEYS`,
(2) çalışma-anı `assertNoPii` (her dönüşte tarar → hata). PII redaction + kart/OTP gizleme panel
görüntülemelerinde de uygulanır.

## Dosyalar
- `a11-recordings-spec.json` — kaynak doğruluk + invariant (S1..S8) + referans anahtarlar + placeholder'lar.
- `a11_recordings_probe.py` — stdlib-only probe (`validate`/`check`/`selftest`/`schema`); `lib/tenant/recordings.ts`
  saf yardımcılarının Python aynası.
- `samples/records-{clean,issues}.json` — `$expect` ile sentetik sağlıklı + sorunlu envanter (FR-TST-008).
- `tests/a11_recordings_test.py` — üç kapının çıkış kodu davranış testi.
- `run_live_test.sh` — canlı smoke (next build+start+curl; credential-free).

## Çalıştırma
```
python3 a11_recordings_probe.py selftest    # pozitif/negatif kendi-testleri
python3 a11_recordings_probe.py check       # saf çekirdek + samples
python3 a11_recordings_probe.py validate    # on-disk sayfa + seam + i18n + spec (S1..S8)
python3 a11_recordings_probe.py schema      # görünüm şema özeti
bash run_live_test.sh                       # canlı smoke (opsiyonel; next gerektirir)
```

## Kapsam dışı (bilinçli)
- Gerçek çağrı kaydı besleme (CDR/Call Store — DB §19/§21/§22, RLS tenant-scope) → F1 §14.1.
- Çağrıyı dinleme + transkripti görme + indirme/export submit + erişim-audit yazımı → A-12 + API §6 + WBS 11.6.
- Saklama süresi zorlaması + geri döndürülemez silme + legal-hold uygulaması → retention motoru (DB §9).
- PII redaction + kart/OTP scrub ÜRETİMİ → WBS 11.3/11.4 (FR-REC-004/005); bu ekran yalnız DURUMU yansıtır.
- Vendor-neutral (ADR-002; belirli kayıt/depo/CDR markası bağlanmaz); sır/credential repoya yazılmadı.
