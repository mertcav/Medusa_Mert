# A-04 — Agent Builder (kod yazmadan) · WBS 13.4.4

L2 Operasyon / Uygulama Paneli'nin (A-01..A-17) dördüncü ekranı. Tenant kullanıcısının **kod yazmadan**
(configuration over coding — FR-AGT-001) bir Voice AI agent oluşturmasını sağlayan **rehberli yapılandırma**
görünümü: no-code başlangıç noktası (boş / şablon / klon), taslak özeti (tamamlanma · adım · mod · dil · iş
kuralı · test), yapılandırma adımları, hazırlık & yayın kapısı ve şablon kütüphanesi. **A-03'ten farkı:**
A-03 envanter (çok-agent okuma), A-04 **tek taslağı oluşturma/yapılandırma** akışıdır. Bu ekran
**konfigürasyon**'dur — **gerçek zamanlı değildir** (FR-ANA-012 kapsamı dışı; tazelik bütçesi yoktur).

## Kaynak gereksinimler
- **BRD §17.5** A-04 "Kod yazmadan agent oluşturma" (ekran tanımı).
- **FR-AGT-001** — Kod yazmadan agent oluşturma → no-code başlangıç (`startMode`) + rehberli adımlar + şablonlar.
- **FR-AGT-002** — İsim/amaç/kişilik/dil/iş kuralları → `name`/`purpose`/`personality`/`languages`/`businessRulesCount` + `basics` adımı.
- **FR-AGT-003** — Single-prompt + node/flow modeli → `conversationModel` + `conversation_model` adımı (`hasConversationModel`).
- **FR-AGT-005** — Draft/test/staging/production yaşam döngüsü → `lifecycle` + `readyForDraft`.
- **FR-AGT-006** — Yayınlı aktif sürüm + rollback → yayın kapısı (rollback derin aksiyon A-17).
- **FR-AGT-008** — Segment varyantları → `startMode="clone"` + `isVariant`/`baseAgentRef`.
- **FR-AGT-009** — Global/tenant güvenlik politikaları → `policies` (zorunlu) adımı.
- **FR-AGT-010** — Canlıdan önce otomatik test → `testStatus` + `readyForTest`/`readyForPublish`/`blockers`.
- **DB §5.2** — `agent` + `agent_version` + `conversation_flow` ile birebir model.
- **FR-TEN-002** — Tenant scope: yalnız kendi tenant'ın taslağı/şablonları (RLS + middleware).
- **BRD §17.6** RBAC · **§17.7** hijyen + PII redaction · **NFR 10.6** sır · **ADR-002** vendor-neutral.

## RBAC (BRD §17.6 — L2)
`conversation_designer`=**Yönet** · `operations_manager`=Düzenle · `qa_analyst`=— · `human_agent`=—.
**A-03'ten fark:** A-04'te birincil rol `conversation_designer`'dır (A-03'te `operations_manager`). UI yalnız
görsel kapı; nihai yetki backend'de + RLS. Kaydet/test'e gönder/yayınla/rollback derin aksiyondur (A8):
akış/prompt/tool tasarımı → A-05 Flow · A-06 Prompt · A-09 Tool; rollback → A-17. Permission-key:
`agent:read` + `agent:manage` (SAD §7/§17.2).

## Çekirdek altın kural — hijyen + güvenlik
A-04 yalnız **KONFİGÜRASYON META** gösterir (taslak ref · ad/amaç · adım alan SAYILARI · seçilen mod ·
diller · iş kuralı SAYISI · test sonucu). Bunlar tenant'ın **KENDİ yapılandırmasıdır** (`name`/`purpose`/
`tenantName` izinli — son-müşteri PII değil); iş kuralları/prompt **metni gömülmez** (yalnız sayı). Ham
son-müşteri içeriği (transkript/ses kaydı, ham numara, müşteri PII, CDR) **gömülmez**; **prompt gövdesi** ve
**tool kimlik bilgisi derin aksiyondur** → A-05/A-06/A-09 (görsel kapı + backend). `getBuilderView` her
dönüşte `assertNoPii` çağırır → `FORBIDDEN_PII_KEYS` (transcript/recording/msisdn/customer/cdr/...) **ve**
`FORBIDDEN_SECRET_KEYS` (secret/apiKey/webhookSecret/token/privateKey/kmsKey/**promptText/promptBody**)
taraması → ihlalde hata.

## Hazırlık kapıları (saf türetme)
- **readyForDraft** — `basics` adımı tamam (taslak kaydedilebilir; FR-AGT-005).
- **readyForTest** — tüm zorunlu adımlar (`basics`/`conversation_model`/`voice_model`/`policies`) tamam **+**
  konuşma modeli seçili (FR-AGT-003) → otomatik test kapısına gönderilebilir (FR-AGT-010 önkoşulu).
- **readyForPublish** — test'e hazır **+** otomatik test kapısı `passed` (FR-AGT-010 + FR-AGT-006).
- **blockers** — test'e gönderimi bloklayan zorunlu+tamamlanmamış adımlar; konuşma modeli yoksa eklenir.
- **nextStep** — sırada (STEP_ORDER) ilk tamamlanmamış adım (opsiyonel olabilir).
- `knowledge`/`tools` **opsiyoneldir** — zorunlu hazırlığı bloklamaz.

## Dosyalar
- `app/(workspace)/workspace/builder/page.tsx` — ekran (RSC, async). Tasarım sistemi + i18n + veri seam.
- `lib/tenant/builder.ts` — vendor-neutral veri **seam** + saf türetme yardımcıları + `assertNoPii`.
- `lib/i18n/{tr,en}.json` — `screen.a04.*` katalogu (TR/EN parity; design-system canonical + 2 vendored kopya).
- `a04-builder-spec.json` — kaynak doğruluk + invariant kapısı (S1..S8).
- `a04_builder_probe.py` — stdlib-only doğrulama (`validate`/`check`/`selftest`/`schema`); TS saf yardımcı Python aynası.
- `samples/builder-{ready,incomplete}.json` — illüstratif taslaklar (`$expect` ile).
- `tests/a04_builder_test.py` — probe üç kapısının davranış testi.
- `run_live_test.sh` — canlı smoke (next build + start + curl).

## Çalıştırma
```bash
python3 a04_builder_probe.py selftest   # pozitif + negatif kendi-testleri
python3 a04_builder_probe.py check      # saf çekirdek + samples
python3 a04_builder_probe.py validate   # on-disk invariant (sayfa + seam + i18n + spec)
python3 tests/a04_builder_test.py       # üç kapı tek komutta
bash run_live_test.sh                   # canlı smoke (opsiyonel; next gerektirir)
```

## Kapsam dışı (bilinçli)
- Gerçek taslak/şablon besleme (Agent Registry DB §5.2 + şablon kütüphanesi) → F1 §14.1.
- Form etkileşimi (client) + kaydet/test'e gönder/yayınla submit + backend zorlama → ilgili API dilimleri.
- Akış/prompt/tool/ses-model derin tasarımı → A-05 Flow · A-06 Prompt · A-07 Voice & Model · A-09 Tool; rollback → A-17.
- Vendor-neutral (ADR-002; LLM/STT/TTS sağlayıcı bağlanmaz); sır/credential repoya yazılmaz.
