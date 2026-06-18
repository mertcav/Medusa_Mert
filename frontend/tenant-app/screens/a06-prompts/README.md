# A-06 — Prompt Editor (versiyonlama) · WBS 13.4.6

L2 Operasyon / Uygulama Paneli'nin (A-01..A-17) altıncı implemente edilen ekranı. Bir agent system
prompt'unun **sürüm geçmişi ve versiyonlama** görünümü (FR-AGT-004): sürüm özeti (sürüm sayısı · aktif ·
yayınlı · taslak · en-son + bekleyen · test-bloklu · açık dikkat), **sürüm geçmişi** (sürüm no + **ayırt
edici kimlik** · aşama · durum · test · oluşturma · yazar · değişiklik notu · boyut sayısı), aşama dağılımı
ve **geri alma** (rollback: aktif sürüm + geri çağrılabilir önceki yayınlanmış sürümler). **A-05'ten
farkı:** A-05 node/flow grafiğini düzenler/doğrular; A-06 prompt'un **sürüm geçmişini** gösterir. Bu ekran
**konfigürasyon**'dur — **gerçek zamanlı değildir** (FR-ANA-012 kapsamı dışı).

## Kaynak gereksinimler
- **BRD §17.5** A-06 "Prompt Editor" (ekran tanımı: prompt sürüm geçmişi ve versiyonlama).
- **FR-AGT-004** — Prompt ve workflow versiyonlanmalıdır → sürüm geçmişi + versiyonlama.
- **SR-AGT-004** (yöntem **I**) — Her sürüm **ayırt edilebilir** (benzersiz `versionNo` + `versionId`) ve
  **geri çağrılabilir**; **sürüm geçmişi ve sürüm kimliği görüntülenir** (kabul ölçütü).
- **FR-AGT-005** — draft/test/staging/production aşamaları → `stage` + aşama dağılımı.
- **FR-AGT-006** — Tek işlemle önceki sürüme rollback → `recallableVersions`/`canRollback` + geri-al kapısı.
- **FR-AGT-010** — Canlıdan önce otomatik test → `testStatus` + `failedTestVersions`.
- **DB §5.2** — `prompt` (tenant_id/agent_id/version_no/body/is_published) + `agent.active_version_id` ile model.
- **FR-TEN-002** — Tenant scope: yalnız kendi tenant'ın prompt sürümleri (RLS + middleware).
- **BRD §17.6** RBAC · **§17.7** hijyen + PII redaction · **NFR 10.6** sır · **ADR-002** vendor-neutral.

## RBAC (BRD §17.6 — L2)
`conversation_designer`=**Yönet** · `operations_manager`=Düzenle · `qa_analyst`=Görüntüle · `human_agent`=—
(A-05 ile aynı birincil rol; qa_analyst kalite incelemesi için Görüntüle). UI yalnız görsel kapı; nihai
yetki backend'de + RLS. Düzenle/test/yayınla/geri-al derin aksiyondur (A8); prompt gövdesi düzenleme
(editör alanı) client island. Permission-key: `agent:read` + `agent:manage` (SAD §7/§17.2).

## Çekirdek altın kural — hijyen + güvenlik
A-06 yalnız **SÜRÜM META** gösterir (sürüm no · ayırt edici **kimlik** · aşama · durum · test · oluşturma ·
yazar · değişiklik **notu** · boyut **SAYISI**). Bunlar tenant'ın **KENDİ yapılandırmasıdır**
(`author`/`changeNote`/`agentName`/`tenantName` izinli — son-müşteri PII değil; `charCount`/`variableCount`
yalnız **sayı**). Ham son-müşteri içeriği (transkript/ses kaydı, ham numara, müşteri PII, CDR) **gömülmez**;
**prompt GÖVDESİ** panele konmaz — gövde düzenleme (editör alanı) **derin aksiyondur** (client island +
backend). `getPromptView` her dönüşte `assertNoPii` çağırır → `FORBIDDEN_PII_KEYS`
(transcript/recording/msisdn/customer/cdr/...) **ve** `FORBIDDEN_SECRET_KEYS`
(secret/apiKey/webhookSecret/token/privateKey/kmsKey/**promptText/promptBody/body**) taraması → ihlalde hata.

## Versiyonlama (saf türetmeler)
- **sortedVersions** — sürümleri `versionNo` AZALAN sıralar (en yeni üstte; deterministik).
- **activeVersion / latestVersion** — aktif (production) sürüm + en yüksek numaralı sürüm.
- **publishedVersions / draftVersions** — yayınlanmış / yayınlanmamış sürümler.
- **versionStatus** — aktif → `active` · yayınlı (aktif değil) → `published` · aksi → `draft`.
- **recallableVersions / canRollback** — yayınlanmış + aktif olmayan sürümler (FR-AGT-006 rollback hedefi).
- **hasPendingChanges** — aktiften daha yeni sürüm var mı (FR-AGT-004).
- **failedTestVersions** — testten geçemeyen (arşiv hariç) sürümler (FR-AGT-010).
- **duplicateVersionNos / duplicateVersionIds / distinguishable** — SR-AGT-004 ayırt edilebilirlik.
- **missingActiveVersion** — aktif referansı kopuk mu (bütünlük).
- **openAttentionCount** — bütünlük ihlali + başarısız test toplamı.

## Dosyalar
- `app/(workspace)/workspace/prompts/page.tsx` — ekran (RSC, async). Tasarım sistemi + i18n + veri seam.
- `lib/tenant/prompts.ts` — vendor-neutral veri **seam** + saf türetme yardımcıları + `assertNoPii`.
- `lib/i18n/{tr,en}.json` — `screen.a06.*` katalogu (TR/EN parity; design-system canonical + 2 vendored kopya).
- `a06-prompts-spec.json` — kaynak doğruluk + invariant kapısı (S1..S8).
- `a06_prompts_probe.py` — stdlib-only doğrulama (`validate`/`check`/`selftest`/`schema`); TS saf yardımcı Python aynası.
- `samples/prompt-{clean,issues}.json` — illüstratif sürüm geçmişleri (`$expect` ile).
- `tests/a06_prompts_test.py` — probe üç kapısının davranış testi.
- `run_live_test.sh` — canlı smoke (next build + start + curl).

## Çalıştırma
```bash
python3 a06_prompts_probe.py selftest   # pozitif + negatif kendi-testleri
python3 a06_prompts_probe.py check      # saf çekirdek + samples
python3 a06_prompts_probe.py validate   # on-disk invariant (sayfa + seam + i18n + spec)
python3 tests/a06_prompts_test.py       # üç kapı tek komutta
bash run_live_test.sh                   # canlı smoke (opsiyonel; next gerektirir)
```

## Kapsam dışı (bilinçli)
- Gerçek sürüm besleme (Agent Registry DB §5.2 `prompt` + `agent.active_version_id`) → F1 §14.1.
- **Prompt gövdesi düzenleme** (editör alanı, diff görünümü) client island + kaydet/test/yayınla submit + backend zorlama → API dilimleri.
- Tek-işlem rollback submit + backend zorlama (FR-AGT-006) → API dilimleri / A-17.
- Vendor-neutral (ADR-002; LLM/STT/TTS sağlayıcı bağlanmaz); sır/credential repoya yazılmaz.
