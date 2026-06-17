# T-05 — Entegrasyon, Tool & API Key/Webhook (WBS 13.3.5)

L1 Tenant Admin Console'un beşinci ekranı (T-01..T-09 serisi). Tenant'ın kurumsal sistem
**entegrasyonlarını** (CRM/ERP/ticketing/custom), bunların üstüne tanımlı **tool'ları** (REST/SOAP/
GraphQL/webhook), programatik erişim için **API anahtarlarını** (S4 Public Developer API) ve giden olay
**webhook** tanımlarını gösterir ve yönetir (BRD §17.4 / FR-TOOL-001..012 · API.md §7 [API key/webhook] ·
§10 [webhook event + imzalama]). Entegrasyon katmanı sağlayıcıdan bağımsızdır (ADR-002).

## Tenant scope (FR-TEN-002) + hijyen (BRD §17.7) + güvenlik (NFR 10.6)
T-05 **yalnız oturum açan tenant'ın KENDİ** entegrasyon/tool/anahtar/webhook konfigürasyonunu gösterir/
yönetir; scope çalışma-anında middleware (13.1.2) + RLS (§13) ile sabitlenir:
- Ham son-müşteri iş içeriği (çağrı kaydı, transkript, müşteri PII) buraya **gömülmez** —
  `FORBIDDEN_PII_KEYS` + `assertNoPii` ile çalışma-anında garanti.
- **SIR** (API key `secret`, webhook `signing_secret`, entegrasyon credential / OAuth client secret /
  bearer token / parola) buraya **konmaz** — `FORBIDDEN_SECRET_KEYS` + `assertNoPii` ile garanti. Sır
  yalnız oluşturmada bir kez döner (API.md §7.2); sunucu yalnız hash saklar. Ekran yalnız durum + scope +
  son-kullanım metadatası gösterir.
- `tenantRef`/`tenantName` + integration/tool/key `name` + webhook `url` + key `scopes` + abone event'ler
  tenant'ın **KENDİ** konfigürasyonudur (son-müşteri PII / sır değil → izinli). `authMethod`/`status`
  yalnız **yöntem/durum** adıdır — sır değil.

## Bileşenler
- `app/(tenant-admin)/admin/integrations/page.tsx` — ekran (RSC, async). Tasarım sistemi (`lib/ui`) + i18n
  (`lib/i18n`) + veri seam (`lib/tenant/integrations`). Tüm metin `screen.t05.*` katalogundan (t()).
  Bölümler: **Özet** (entegrasyon/tool/API anahtarı/webhook sayısı) · **Entegrasyonlar** (tür crm/erp/
  ticketing/custom + kimlik doğrulama yöntemi + bölge + son senkron + durum) · **Tool'lar** (protokol
  REST/SOAP/GraphQL/webhook + okuma/yazma + schema doğrulaması + müşteri teyidi + bağlı entegrasyon) ·
  **API Anahtarları** (ad + scope + son kullanım + durum; secret YOK) · **Webhook'lar** (URL + abone
  event'ler + son teslimat + durum; signing_secret YOK). Geçersiz entegrasyon referansı / HTTPS olmayan
  webhook → danger uyarısı; yazma-teyitsiz tool (FR-TOOL-006/007) / schemasız tool (FR-TOOL-002) /
  başarısız webhook → warning uyarısı.
- `lib/tenant/integrations.ts` — vendor-neutral veri **seam** + saf türetme yardımcıları
  (`countIntegrationState`/`countIntegrationType`/`toolsForIntegration`/`invalidIntegrationRefs`/
  `writeToolsWithoutConfirmation`/`toolsWithoutSchema`/`isHttpsUrl`/`insecureWebhookUrls`/
  `failingWebhooks`/`apiKeysByStatus`/tone'lar) + `assertNoPii` guard (PII **ve** sır). Yer tutucu
  deterministik snapshot; gerçek kaynak F2 §14.1'de Integration Gateway + Tool Registry + API key/webhook
  servisinden tenant-scope (RLS) beslenir.
- `i18n` (`screen.t05.*`) — TR/EN, design-system canonical katalogda; her iki app'e vendored (hash-eşit).

## RBAC (BRD §17.6)
`tenant_owner`=Yönet · `tenant_admin`=Yönet · `security_compliance_officer`=Görüntüle · `billing_viewer`=— ·
`api_developer`=Yönet. UI yalnız görsel kapı; nihai yetki backend'de (12.2.x, SAD §14.4.1 A8) + RLS.
"Yeni entegrasyon / tool / API anahtarı / webhook" aksiyonları görsel kapıdır; oluşturma/rotasyon/iptal
istemci submit + backend zorlama 12.2.x'te. Bu katmanda tool çağırma/anahtar oluşturma/webhook gönderme
kararı **yok**.

## Doğrulama
```
python3 t05_integrations_probe.py validate   # ON-DISK invariant S1..S8
python3 t05_integrations_probe.py check      # saf çekirdek senaryo + samples
python3 t05_integrations_probe.py selftest   # pozitif/negatif kendi-testi
python3 tests/t05_integrations_test.py       # üç kapı çıkış-kodu davranış testi
bash run_live_test.sh                          # canlı smoke (next build+start+curl; credential-free)
```

## Kapsam dışı (bilinçli)
Gerçek Integration Gateway + Tool Registry + API key/webhook servisi API bağlama → F2 §14.1; entegrasyon/
tool/anahtar/webhook oluşturma/rotasyon/iptal istemci submit + backend zorlama + tool çağırma izni
(FR-TOOL-004) → 12.2.x; canlı tool çalıştırma + webhook teslimat/retry → data plane (Integration Gateway);
diğer L1 ekranları T-06..T-09 → 13.3.6+; tool'un agent'a bağlanması (kullanım) → L2 A-09. Vendor-neutral
(ADR-002; belirli CRM/ERP/SaaS markası bağlanmaz); sır/credential repoya yazılmaz.
