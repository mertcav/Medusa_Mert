# A-09 — Tool/API Bağlama · WBS 13.4.9

L2 Operasyon / Uygulama Paneli'nin (A-01..A-17) sekizinci implemente edilen ekranı. Bir tenant'ın
**tanımlı tool'larının agent'lara bağlanması (kullanımı)**: bağlama özeti (tool · agent · aktif bağ ·
yazma yetkisi · teyit · hassas · async + açık dikkat), **agent başına bağlar** (agent · tool · protokol ·
grant [okuma|yazma] · teyit · durum), **tool kataloğu** (tool · protokol · erişim · schema doğrulama ·
endpoint allowlist · teyit · hassas · async · bağ sayısı), **protokol dağılımı** ve **güvenlik & uyum
sağlığı**. **T-05'ten farkı:** T-05 (L1) tool/entegrasyon/anahtar/webhook'u **tanımlar** (config); A-09 (L2)
tanımlı tool'ları agent'a **bağlar** + bağ sağlığını (kullanım) gösterir. Bu ekran **konfigürasyon**'dur —
**gerçek zamanlı değildir**.

## Kaynak gereksinimler
- **BRD §17.5** A-09 "Tool/API Bağlama" (ekran tanımı: tanımlı tool'ları agent'a bağlama (kullanım)).
- **FR-TOOL-001** — REST/SOAP/GraphQL/webhook entegrasyonları → `protocol` + protokol dağılımı.
- **FR-TOOL-002** — Tool input/output JSON schema ile doğrulanır → `schemaValidated` + `unvalidatedBindings`.
- **FR-TOOL-004** — Tool yetkileri agent bazında sınırlandırılır → `binding.grant` (agent başına okuma/yazma).
- **FR-TOOL-005** — Okuma/yazma ayrı güvenlik seviyeleri → `accessLevel` + `escalatedBindings` (read tool'a write grant ihlali).
- **FR-TOOL-006** — Kritik işlem öncesi müşteri teyidi → `requiresConfirmation` + `confirmationTools`.
- **FR-TOOL-007** — Para/sözleşme/PII değişikliği ek doğrulama → `sensitiveAction` + `sensitiveWriteBindings` + `unconfirmedSensitiveTools`.
- **FR-TOOL-011** — Uzun süren işlem asenkron workflow → `async` bayrağı (Should).
- **FR-TOOL-012** — Onaylanmamış endpoint'lere erişim engellenir → `endpointApproved` + `unapprovedBindings`.
- **API §7** — `POST /agents/{id}/tools:bind` (`tool:bind` permission); tool bağlama yüzeyi.
- **FR-TEN-002** — Tenant scope: yalnız kendi tenant'ın tool/bağ envanteri (RLS + middleware).
- **BRD §17.6** RBAC · **§17.7** hijyen + PII redaction · **NFR 10.6** sır · **ADR-002** vendor-neutral.

## RBAC (BRD §17.6 — L2)
`operations_manager`=**Düzenle** · `conversation_designer`=**Düzenle** · `qa_analyst`=— · `human_agent`=—
(BRD §17.6 A-09 satırı: her iki birincil rol Düzenle; `tenant_owner` kural 17.7 ile Yönet). UI yalnız
görsel kapı; nihai yetki backend'de + RLS. Bağla/çöz/grant ver derin aksiyondur (A8); tool çağırma/Integration
Gateway API dilimi (WBS 7.x). Permission-key: `tool:bind` (API §7) + `agent:read` (SAD §7/§17.2).

## Çekirdek altın kural — hijyen + güvenlik
A-09 yalnız **TOOL/BAĞ META** gösterir (protokol · erişim **seviyesi** · schema/endpoint/teyit/hassas/async
**bayrakları** · grant · durum + tool/agent adı). Bunlar tenant'ın **KENDİ yapılandırmasıdır** (tool `name`/
agent `name` izinli — KURUMSAL ad, son-müşteri PII değil; bayraklar yalnız **durum**). Ham son-müşteri içeriği
(transkript/ses kaydı, ham numara, müşteri PII, CDR) **gömülmez**; **tool ENDPOINT URL'i / JSON schema GÖVDESİ
/ istek-yanıt PAYLOAD'ı / credential** panele konmaz — tool çağırma/bağlama **derin aksiyondur** (API dilimi +
backend). `getToolBindingView` her dönüşte `assertNoPii` çağırır → `FORBIDDEN_PII_KEYS`
(transcript/recording/msisdn/customer/cdr/...) **ve** `FORBIDDEN_SECRET_KEYS`
(secret/apiKey/token/credential/**endpoint/url/payload/schemaBody/jsonSchema**) taraması → ihlalde hata.

## Saf türetmeler
- **sortedTools / sortedAgents / allBindings** — tool'ları toolRef ASC; agent'ları agentRef ASC; tüm bağları (agentRef, bindRef) deterministik düzleştir + tool'a çözümle.
- **countByProtocol / countByAccessLevel** — protokol (FR-TOOL-001) ve erişim seviyesi (FR-TOOL-005) dağılımı.
- **readTools / writeTools** — okuma/yazma ayrımı (FR-TOOL-005).
- **unvalidatedTools / unvalidatedBindings** — JSON schema yok (FR-TOOL-002).
- **unapprovedTools / unapprovedBindings** — endpoint allowlist dışı (FR-TOOL-012; aktif bağ → danger).
- **escalatedBindings** — read tool'a write grant (FR-TOOL-005 yetki yükseltme) · **orphanBindings** — tool katalogda yok (bütünlük).
- **confirmationTools / sensitiveTools / unconfirmedSensitiveTools** — teyit (FR-TOOL-006) + hassas (FR-TOOL-007) + config açığı.
- **asyncTools** — asenkron workflow (FR-TOOL-011) · **sensitiveWriteBindings** — hassas yazma çağrısı (ek doğrulama).
- **openAttentionCount** — onaysız endpoint + doğrulanmamış schema + yetki yükseltme + orphan + teyitsiz hassas.

## Dosyalar
- `app/(workspace)/workspace/tools/page.tsx` — ekran (RSC, async). Tasarım sistemi + i18n + veri seam.
- `lib/tenant/tools.ts` — vendor-neutral veri **seam** + saf türetme yardımcıları + `assertNoPii`.
- `lib/i18n/{tr,en}.json` — `screen.a09.*` katalogu (TR/EN parity).
- `a09-tools-spec.json` — kaynak doğruluk + invariant kapısı (S1..S8).
- `a09_tools_probe.py` — stdlib-only doğrulama (`validate`/`check`/`selftest`/`schema`); TS saf yardımcı Python aynası.
- `samples/tools-{clean,issues}.json` — illüstratif tool/bağ envanterleri (`$expect` ile).
- `tests/a09_tools_test.py` — probe üç kapısının davranış testi.
- `run_live_test.sh` — canlı smoke (next build + start + curl).

## Çalıştırma
```bash
python3 a09_tools_probe.py selftest   # pozitif + negatif kendi-testleri
python3 a09_tools_probe.py check      # saf çekirdek + samples
python3 a09_tools_probe.py validate   # on-disk invariant (sayfa + seam + i18n + spec)
python3 tests/a09_tools_test.py       # üç kapı tek komutta
bash run_live_test.sh                 # canlı smoke (opsiyonel; next gerektirir)
```

## Kapsam dışı (bilinçli)
- Gerçek tool/bağ besleme (Tool Registry + Integration Gateway WBS 7.x) → F1 §14.1.
- **Tool çağırma/bağlama submit** (POST /agents/{id}/tools:bind — API §7) + backend zorlama → API dilimleri.
- Çalışma-anı zorlama: timeout/retry/circuit breaker/idempotency (FR-TOOL-003/009) + korelasyon ID (FR-TOOL-010) + hata normalizasyonu (FR-TOOL-008) → orchestrator + Integration Gateway (WBS 7.1.x).
- Tool tanımı/endpoint allowlist yönetimi (FR-TOOL-012 config) → T-05 (L1; WBS 13.3.5) + WBS 7.2.3.
- Vendor-neutral (ADR-002; belirli CRM/ERP/SaaS markası bağlanmaz); sır/credential repoya yazılmaz.
