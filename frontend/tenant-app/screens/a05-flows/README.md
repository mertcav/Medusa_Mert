# A-05 — Conversation Flow Editor · WBS 13.4.5

L2 Operasyon / Uygulama Paneli'nin (A-01..A-17) beşinci implemente edilen ekranı. Bir agent'ın **node/flow
tabanlı konuşma sürecini** (FR-AGT-003) tasarlama/doğrulama görünümü: akış özeti (düğüm · geçiş · mod · sürüm
+ erişilemez · asılı · çıkmaz · geçerlilik), doğrulama & sağlık kapısı, düğüm türü dağılımı, düğümler ve
geçişler. **A-04'ten farkı:** A-04 tek taslağı **oluşturma** (no-code) akışıdır, A-05 var olan akışın
**node/flow grafiğini** düzenler/doğrular. Bu ekran **konfigürasyon**'dur — **gerçek zamanlı değildir**
(FR-ANA-012 kapsamı dışı; tazelik bütçesi yoktur).

## Kaynak gereksinimler
- **BRD §17.5** A-05 "Conversation Flow Editor" (ekran tanımı: node/flow tabanlı süreç tasarımı).
- **FR-AGT-003** — Single-prompt + node/flow konuşma modeli → `mode` + düğüm/geçiş grafiği (`isNodeFlow`).
- **FR-AGT-010** — Canlıdan önce otomatik test → doğrulama kapısı + `readyForTest`/`readyForPublish`.
- **DB §5.2** — `conversation_flow` (mode + graph + version_no) ile birebir model.
- **SAD §6.1** — Turn state machine (LISTEN/CAPTURE/THINK/SPEAK) → düğüm türü davranışı + handoff tasarım gereği.
- **FR-TEN-002** — Tenant scope: yalnız kendi tenant'ın agent akışı (RLS + middleware).
- **BRD §17.6** RBAC · **§17.7** hijyen + PII redaction · **NFR 10.6** sır · **ADR-002** vendor-neutral.

## RBAC (BRD §17.6 — L2)
`conversation_designer`=**Yönet** · `operations_manager`=Düzenle · `qa_analyst`=— · `human_agent`=—
(A-04 ile aynı birincil rol). UI yalnız görsel kapı; nihai yetki backend'de + RLS. Düzenle/doğrula/yayınla
derin aksiyondur (A8): prompt gövdesi → A-06 Prompt · tool kimlik bilgisi → A-09 Tool. Permission-key:
`agent:read` + `agent:manage` (SAD §7/§17.2).

## Çekirdek altın kural — hijyen + güvenlik
A-05 yalnız **KONFİGÜRASYON META** gösterir (düğüm etiketi · tür · prompt/tool **REFERANSI** · geçiş koşulu
ETİKETİ · sürüm). Bunlar tenant'ın **KENDİ yapılandırmasıdır** (`label`/`agentName`/`tenantName` izinli —
son-müşteri PII değil). Ham son-müşteri içeriği (transkript/ses kaydı, ham numara, müşteri PII, CDR)
**gömülmez**; **prompt gövdesi** ve **tool kimlik bilgisi derin aksiyondur** → A-06/A-09 (görsel kapı +
backend). `getFlowView` her dönüşte `assertNoPii` çağırır → `FORBIDDEN_PII_KEYS`
(transcript/recording/msisdn/customer/cdr/...) **ve** `FORBIDDEN_SECRET_KEYS`
(secret/apiKey/webhookSecret/token/privateKey/kmsKey/**promptText/promptBody**) taraması → ihlalde hata.

## Akış doğrulama (saf graf türetmeleri)
- **hasSingleEntry** — akışta tam olarak bir `start` düğümü olmalı.
- **danglingEdges** — kaynağı/hedefi mevcut olmayan geçişler (asılı).
- **reachableNodeIds / unreachableNodes** — girişten BFS ile erişilebilirlik (deterministik).
- **deadEndNodes** — terminal olmayan (`handoff`/`end` dışı) + giden geçerli geçişi olmayan düğümler.
- **nodesMissingConfig** — yapılandırması tamamlanmamış düğümler.
- **hasHandoff** — insan aktarımı düğümü (tasarım gereği — SAD).
- **structurallyValid** — tek giriş ∧ asılı yok ∧ erişilemez yok ∧ çıkmaz yok.
- **readyForTest** — yapısal geçerli ∧ tüm düğüm yapılandırması tam (FR-AGT-010 önkoşulu).
- **readyForPublish** — test'e hazır ∧ insan aktarımı var.
- **flowValidity** — yapısal hata → `invalid` · eksik config/handoff → `warnings` · aksi → `valid`.
- Tek-prompt modunda grafik yoktur → sayfa `EmptyState` gösterir (FR-AGT-003).

## Dosyalar
- `app/(workspace)/workspace/flows/page.tsx` — ekran (RSC, async). Tasarım sistemi + i18n + veri seam.
- `lib/tenant/flows.ts` — vendor-neutral veri **seam** + saf türetme yardımcıları + `assertNoPii`.
- `lib/i18n/{tr,en}.json` — `screen.a05.*` katalogu (TR/EN parity; design-system canonical + 2 vendored kopya).
- `a05-flows-spec.json` — kaynak doğruluk + invariant kapısı (S1..S8).
- `a05_flows_probe.py` — stdlib-only doğrulama (`validate`/`check`/`selftest`/`schema`); TS saf yardımcı Python aynası.
- `samples/flow-{valid,issues}.json` — illüstratif akışlar (`$expect` ile).
- `tests/a05_flows_test.py` — probe üç kapısının davranış testi.
- `run_live_test.sh` — canlı smoke (next build + start + curl).

## Çalıştırma
```bash
python3 a05_flows_probe.py selftest   # pozitif + negatif kendi-testleri
python3 a05_flows_probe.py check      # saf çekirdek + samples
python3 a05_flows_probe.py validate   # on-disk invariant (sayfa + seam + i18n + spec)
python3 tests/a05_flows_test.py       # üç kapı tek komutta
bash run_live_test.sh                 # canlı smoke (opsiyonel; next gerektirir)
```

## Kapsam dışı (bilinçli)
- Gerçek akış besleme (Agent Registry DB §5.2 `conversation_flow` + akış doğrulama servisi) → F1 §14.1.
- Grafik düzenleme (sürükle-bırak client island) + düzenle/doğrula/yayınla submit + backend zorlama → API dilimleri.
- Prompt gövdesi → A-06 Prompt · ses/model → A-07 · tool kimlik bilgisi → A-09 Tool; rollback → A-17.
- Vendor-neutral (ADR-002; LLM/STT/TTS sağlayıcı bağlanmaz); sır/credential repoya yazılmaz.
