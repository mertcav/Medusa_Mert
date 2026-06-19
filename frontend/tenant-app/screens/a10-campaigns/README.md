# A-10 — Outbound Kampanya Yönetimi · WBS 13.4.10

L2 Operasyon / Uygulama Paneli'nin (A-01..A-17) dokuzuncu implemente edilen ekranı. Bir tenant'ın
**outbound kampanyalarının** envanteri + uyum/disposition sağlığı: kampanya özeti (çalışan kampanya ·
kontak · aranabilir · DNC · consent eksik · kapasite · disposition + açık dikkat), **kampanyalar** (kampanya ·
agent · durum · kaynak [yükleme|CRM] · kontak · deneme [maks + aralık] · script versiyonu · A/B), **uyum &
suppression sağlığı** (consent ön-kontrol · DNC/suppression · arama saati · kapasite), **durum dağılımı** ve
**disposition dağılımı**. Bu ekran **konfigürasyon + operasyonel özet**'tir — gerçek zamanlı değildir
(FR-ANA-012 dışı). İlk `F2` (Faz 2) ekranı; outbound modülü BRD §20'ye göre Faz 2 ağırlıklıdır.

## Kaynak gereksinimler
- **BRD §17.5** A-10 "Outbound Kampanya Yönetimi" (ekran tanımı: liste, zamanlama, consent/suppression, disposition).
- **BRD §14.3** Outbound uyumluluğu (consent kaynağı/tarih/kapsam, DNC, izinli saat, max deneme, Caller ID, script/teklif versiyonu).
- **FR-OUT-001** — Kampanya oluşturma + müşteri listesi yükleme → `listSource: upload` + `action.create` + `contacts.total`.
- **FR-OUT-002** — CRM'den dinamik kampanya listesi → `listSource: crm`.
- **FR-OUT-003** — Arama öncesi consent + suppression kontrolü → `consentCheckEnabled` + `consentCheckDisabled` (aktif & kapalı → danger).
- **FR-OUT-004** — Ülke/bölge arama saatleri → `callingHoursConfigured` + `callingHoursMissing` (aktif & yok → danger).
- **FR-OUT-005** — Maksimum deneme + yeniden arama aralığı → `maxAttempts`/`retryIntervalMinutes` + `contacts.exhausted`.
- **FR-OUT-006** — "Bir daha aramayın" (DNC/suppression) → `suppressionEnabled` + `suppressionDisabled` + `contacts.dnc`.
- **FR-OUT-007** — Kampanya kapasitesi agent+trunk kapasitesini aşmamalı → `capacityCap`/`capacityAvailable` + `capacityExceeded` (cap>avail → danger).
- **FR-OUT-008** — Voicemail/meşgul/cevapsız/geçersiz numara ayrı kaydedilir → `dispositions` (per-outcome AGREGAT sayılar).
- **FR-OUT-009** — Kampanya script/teklif versiyonu çağrı bazında kaydedilir → `scriptVersion` (ETİKET) + `missingScriptVersion`.
- **FR-OUT-010** — Kampanya durdurma → `status` (draft/running/paused/stopped/completed) + `action.stop`.
- **FR-OUT-011** — Çağrı başına disposition otomatik → disposition dağılımı (`aggregateDispositions`).
- **FR-OUT-012** — A/B test kampanyaları (Should) → `abTest` + `abTestCampaigns`.
- **DB §5.4** campaign/contact/consent (durum CHECK + DNC + consent append-only) · **SAD §19.1** Consent Engine.
- **FR-TEN-002** — Tenant scope: yalnız kendi tenant'ın kampanya envanteri (RLS + middleware).
- **BRD §17.6** RBAC · **§17.7** hijyen + PII redaction · **NFR 10.6** sır · **ADR-002** vendor-neutral.

## RBAC (BRD §17.6 — L2)
`operations_manager`=**Yönet** · `conversation_designer`=**Düzenle** · `qa_analyst`=**Görüntüle** · `human_agent`=—
(`tenant_owner` kural 17.7 ile Yönet). UI yalnız görsel kapı; nihai yetki backend'de + RLS. Kampanya oluştur/
durdur/liste yükle derin aksiyondur (A8); dialer + Consent Engine çalışma-anı backend (SAD §19.1). Permission-key:
`campaign:manage` (SAD §7) + `agent:read`.

## Çekirdek altın kural — hijyen + güvenlik
A-10'un en kritik kuralı son-müşteri PII'sinin panele **konmamasıdır**. Ekran yalnız **KAMPANYA META** gösterir
(durum · deneme · script-versiyonu **etiketi** · arama-saati/consent/suppression/A-B **bayrakları** · kapasite +
**AGREGAT kontak sayıları** [total/dnc/consentMissing/exhausted] + **per-disposition sayılar** + kampanya/agent
adı). Bunlar tenant'ın **KENDİ yapılandırmasıdır** (kampanya/agent adı izinli — kurumsal ad, son-müşteri PII
değil). **Aranacak ham numara (e164) / müşteri adı / contact attributes (JSONB) / CRM external_ref / transkript /
ses kaydı / CDR gömülmez**; **script/teklif GÖVDESİ / credential** panele konmaz — liste yükleme/CRM çekme/dialer
**derin aksiyondur** (API dilimi + Consent Engine backend). `getOutboundCampaignView` her dönüşte `assertNoPii`
çağırır → `FORBIDDEN_PII_KEYS` (e164/msisdn/phoneNumber/customer/attributes/externalRef/cdr/transcript/...) **ve**
`FORBIDDEN_SECRET_KEYS` (secret/apiKey/token/credential/**scriptBody**) taraması → ihlalde hata.

## Saf türetmeler
- **sortedCampaigns / countByStatus** — campaignRef ASC; durum (DB §5.4) dağılımı.
- **runningCampaigns / activeCampaigns** — çalışan; aktif (running|paused — consent/suppression/saat kapıları bunlara uygulanır).
- **aggregateContacts / reachableContacts** — agregat kontak sayıları; aranabilir = total − dnc − consentMissing (≥0).
- **aggregateDispositions / totalDispositions** — per-outcome AGREGAT sayılar (FR-OUT-008/011).
- **consentCheckDisabled** (FR-OUT-003) · **suppressionDisabled** (FR-OUT-006) · **callingHoursMissing** (FR-OUT-004) — aktif kampanyada kapalı kapı → danger.
- **capacityExceeded** (FR-OUT-007) — cap>avail (durumdan bağımsız config açığı) · **missingScriptVersion** (FR-OUT-009) — aktif & script boş.
- **capacityUtilPct / abTestCampaigns** — aktif kapasite kullanımı; A/B test (FR-OUT-012).
- **openAttentionCount** — consent kapalı + suppression kapalı + arama saati eksik + kapasite aşımı + script eksik.

## Dosyalar
- `app/(workspace)/workspace/campaigns/page.tsx` — ekran (RSC, async). Tasarım sistemi + i18n + veri seam.
- `lib/tenant/campaigns.ts` — vendor-neutral veri **seam** + saf türetme yardımcıları + `assertNoPii`.
- `lib/i18n/{tr,en}.json` — `screen.a10.*` katalogu (TR/EN parity; design-system canonical → her iki app'e vendored, hash-eşit).
- `a10-campaigns-spec.json` — kaynak doğruluk + invariant kapısı (S1..S8).
- `a10_campaigns_probe.py` — stdlib-only doğrulama (`validate`/`check`/`selftest`/`schema`); TS saf yardımcı Python aynası.
- `samples/campaigns-{clean,issues}.json` — illüstratif kampanya envanterleri (`$expect` ile).
- `tests/a10_campaigns_test.py` — probe üç kapısının davranış testi.
- `run_live_test.sh` — canlı smoke (next build + start + curl).

## Çalıştırma
```bash
python3 a10_campaigns_probe.py selftest   # pozitif + negatif kendi-testleri
python3 a10_campaigns_probe.py check      # saf çekirdek + samples
python3 a10_campaigns_probe.py validate   # on-disk invariant (sayfa + seam + i18n + spec)
python3 tests/a10_campaigns_test.py       # üç kapı tek komutta
bash run_live_test.sh                     # canlı smoke (opsiyonel; next gerektirir)
```

## Kapsam dışı (bilinçli)
- Gerçek kampanya/kontak/consent besleme (Campaign Manager + Consent Engine SAD §19.1 + CRM connector FR-OUT-002) → F1/F2 §14.1.
- **Kampanya oluştur/durdur/liste yükle submit** + backend zorlama + dialer hız/backpressure (FR-OUT-007, SAD §6.5) → API dilimleri.
- Outbound çağrı öncesi zorunlu Consent Engine kontrolü (consent/suppression/saat/kapasite/Caller ID/zorunlu açılış metni) çalışma-anı zorlaması → orchestrator + Consent Engine (SAD §19.1).
- Çağrı/numara bazında disposition detayı + kayıt/transkript → A-11 (Çağrı Kayıtları) / A-12 (Çağrı Detayı).
- Vendor-neutral (ADR-002; belirli CRM/telekom markası bağlanmaz); sır/credential repoya yazılmaz.
