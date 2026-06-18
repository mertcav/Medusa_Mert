# A-03 — Agent Listesi (Agent List) · WBS 13.4.3

L2 Operasyon / Uygulama Paneli'nin (A-01..A-17) üçüncü ekranı. Tenant'ın tanımlı Voice AI
agent'larının **yönetim/envanter** görünümü: özet (KPI), yaşam döngüsü dağılımı, dikkat gerektiren
agent'lar ve tüm agent tablosu. **A-02'den farkı:** bu ekran **konfigürasyon/envanter**'dir —
**gerçek zamanlı değildir** (FR-ANA-012 kapsamı dışı; tazelik bütçesi yoktur).

## Kaynak gereksinimler
- **BRD §17.5** A-03 "Tüm agent'lar ve durumları" (ekran tanımı).
- **FR-AGT-005** — Draft/test/staging/production yaşam döngüsü → `lifecycle` ("durumları").
- **FR-AGT-003** — Single-prompt + node/flow konuşma modeli → `mode`.
- **FR-AGT-004 / FR-AGT-006** — Prompt/workflow versiyonlama + yayınlı aktif sürüm/rollback → `activeVersionNo`/`latestVersionNo`/`hasPendingChanges`.
- **FR-AGT-007** — Numara/kampanya bağlama → `boundNumbers`/`boundCampaigns`/`unboundProduction`.
- **FR-AGT-008** — Segment varyantları → `isVariant`/`baseAgentRef`.
- **FR-AGT-010** — Canlıya almadan önce otomatik test → `testStatus`/`testBlocked`.
- **FR-AGT-002** — İsim/amaç/dil (agent config) → `name`/`purpose`/`languages`.
- **DB §5.2** — `agent` (lifecycle_state CHECK) + `agent_version` (WORM) ile birebir model.
- **FR-TEN-002** — Tenant scope: yalnız kendi tenant'ın agent'ları (RLS + middleware).
- **BRD §17.6** RBAC · **§17.7** hijyen + PII redaction · **NFR 10.6** sır · **ADR-002** vendor-neutral.

## RBAC (BRD §17.6 — L2)
`operations_manager`=Yönet · `conversation_designer`=Düzenle · `qa_analyst`=Görüntüle · `human_agent`=—.
UI yalnız görsel kapı; nihai yetki backend'de + RLS. Oluştur/düzenle/yayınla/rollback derin aksiyondur
(A8): → A-04 Builder · A-06 Prompt · A-07 Voice & Model · A-09 Tool · A-17 Sürüm Geçmişi. Permission-key:
`agent:read` + `agent:manage` (SAD §7/§17.2).

## Çekirdek altın kural — hijyen + güvenlik
A-03 envanteri yalnız **KONFİGÜRASYON META** gösterir (agent ref · ad/amaç · durum · mod · diller ·
sürüm · test · bağlantı). Bunlar tenant'ın **KENDİ yapılandırmasıdır** (`name`/`purpose`/`tenantName`
izinli — son-müşteri PII değil). Ham son-müşteri içeriği (transkript/ses kaydı, ham numara, müşteri PII,
CDR) **gömülmez**; prompt gövdesi/tool kimlik bilgisi **derin aksiyondur** → A-06/A-09 (görsel kapı +
backend). `getAgentList` her dönüşte `assertNoPii` çağırır → `FORBIDDEN_PII_KEYS`
(transcript/recording/msisdn/phoneNumber/customer/cdr/...) **ve** `FORBIDDEN_SECRET_KEYS`
(secret/apiKey/webhookSecret/token/privateKey/kmsKey/...) taraması → ihlalde hata.

## Dikkat gerektiren (bloklayan) sorunlar
- **Test bloklu** (FR-AGT-010): staging/production agent otomatik test kapısını geçmemiş.
- **Bağlantısız production** (FR-AGT-007): canlı agent'ın bağlı numarası/kampanyası yok → erişilemez.
- **Aktif sürümsüz production** (FR-AGT-006): production ama yayınlı sürümü yok → tutarsız.
- `attentionAgents` = bu üç kümenin tekilleştirilmiş birleşimi; `openAttentionCount` ayrık agent sayısı.
- **Yayınlanmamış değişiklik** (`hasPendingChanges`, FR-AGT-004/006): en son sürüm > yayınlı sürüm →
  bilgilendirme (info), bloklayıcı değil.

## Dosyalar
- `app/(workspace)/workspace/agents/page.tsx` — ekran (RSC, async). Tasarım sistemi + i18n + veri seam.
- `lib/tenant/agents.ts` — vendor-neutral veri **seam** + saf türetme yardımcıları + `assertNoPii`.
- `lib/i18n/{tr,en}.json` — `screen.a03.*` katalogu (TR/EN parity; design-system canonical + 2 vendored kopya).
- `a03-agents-spec.json` — kaynak doğruluk + invariant kapısı (S1..S8).
- `a03_agents_probe.py` — stdlib-only doğrulama (`validate`/`check`/`selftest`/`schema`); TS saf yardımcı Python aynası.
- `samples/agents-{clean,issues}.json` — illüstratif envanterler (`$expect` ile).
- `tests/a03_agents_test.py` — probe üç kapısının davranış testi.
- `run_live_test.sh` — canlı smoke (next build + start + curl).

## Çalıştırma
```bash
python3 a03_agents_probe.py selftest   # pozitif + negatif kendi-testleri
python3 a03_agents_probe.py check      # saf çekirdek + samples
python3 a03_agents_probe.py validate   # on-disk invariant (sayfa + seam + i18n + spec)
python3 tests/a03_agents_test.py       # üç kapı tek komutta
bash run_live_test.sh                  # canlı smoke (opsiyonel; next gerektirir)
```

## Kapsam dışı (bilinçli)
- Gerçek envanter besleme (Agent Registry DB §5.2 + test orkestrasyonu FR-AGT-010) → F1 §14.1.
- Oluştur/düzenle/yayınla/rollback submit + backend zorlama → A-04/A-06/A-07/A-17 + ilgili API dilimleri.
- Vendor-neutral (ADR-002; LLM/STT/TTS sağlayıcı bağlanmaz); sır/credential repoya yazılmaz.
