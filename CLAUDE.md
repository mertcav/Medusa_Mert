# CLAUDE.md — Enterprise Voice AI Agent Platform (chanteur)

Bu dosya, gelecekteki Claude Code oturumlarının bu repoda tutarlı kalması için projenin
sabitlerini özetler. **Kaynak doğruluk (source of truth) `docs/` altındaki dokümanlardır;**
bir çelişki olursa dokümanları esas al ve bu dosyayı güncelle.

## Ürün
RMC Technology & Consultancy'nin **kurumsal, multi-tenant (B2B2B) Sesli Yapay Zekâ Agent
platformu**. Telefon çağrılarını (inbound/outbound) insan operatöre yakın doğallıkta karşılar,
kurumsal sistemlerde gerçek işlem yapar ve gerektiğinde insan temsilciye kesintisiz aktarır.
Çekirdek: STT · LLM · TTS gerçek zamanlı orkestrasyonu.

## Doküman yapısı (docs-as-code)
- `docs/BRD.md` — İş Gereksinimleri (Business Requirements). İş seviyesi; FR/NFR'ler burada.
- `docs/SAD.md` — Çözüm Mimarisi (Solution Architecture). Teknik tasarım, ADR'ler.
- `docs/SRS.md` — Sistem Gereksinimleri (System Requirements). FR/NFR → doğrulanabilir `SR-*` (yöntem T/A/I/D + kabul ölçütü).
- `docs/build-docx.sh` + `docs/assets/rmc-reference.docx` — `.md` → markalı `.docx` artifact (pandoc).
- Sıradaki dokümanlar: **izlenebilirlik matrisi (0.1.2)** → **DB/API tasarımı** → Faz 1 kod.
- **`.md` source of truth'tur; `.docx` üretilen artifact'tir.** İçeriği `.md`'de değiştir, `.docx`'i build et.

## Yazım kuralları
- Ana metin **Türkçe**, teknik terimler İngilizce (mevcut register'a uy).
- **FR-ID şeması:** `FR-<ALAN>-NNN` (ör. `FR-TEN-001`, `FR-IAM-009`, `FR-RES-016`). Yeni ID'leri
  ilgili alanın sırasından devam ettir; mevcut ID/numaralandırmayı **bozma**.
- **SR-ID şeması (SRS):** `SR-<ALAN>-NNN`; `<ALAN>` kodu BRD FR/NFR alanını yansıtır (ör. `SR-RTC-007`→`FR-RTC-002`).
  NFR alanları: `PERF/DEN/SCAL/AVL/DR/SEC/LOC`. Her SR: kaynak FR/NFR + yöntem (T/A/I/D) + ölçülebilir kabul ölçütü.
- Öncelik: MoSCoW (Must / Should / Could).
- Sürüm artışında: doküman bilgisi + Sürüm Geçmişi tablosu + (varsa) TOC güncellenir.

## Mimari ilkeler (değiştirme, koru)
- **Vendor-neutral:** STT/TTS/LLM/telekom sağlayıcıları adapter SPI arkasında, değiştirilebilir;
  kategori başına ≥2 sağlayıcı + fallback. BRD belirli sağlayıcı seçmez.
- **Lean runtime / high-density:** Gecikme (P95 ≤ 1.2 sn) ve düşük çağrı-başı kaynak birlikte hedef.
  Async/non-blocking, stream-first, model tiering, TTS/semantic cache, scale-to-zero, backpressure.
- **İki düzlemli yığın:**
  - **Data plane** (voice runtime / Conversation Orchestrator): **Go/Rust** (density gerekliliği, ADR-003).
  - **Panel/yönetim düzlemi** (Control & Analytics): **Next.js (App Router) + FastAPI**.
- Çekirdek IP: bağımsız **Conversation Orchestrator** (STT/LLM/TTS doğrudan bağlanmaz, ADR-001).
- Deterministic actions, human handoff by design, observable by default, compliance by design.

## Panel mimarisi (üç katman — BRD §17, SAD §14.4)
- **L0 — Platform Admin Console** (RMC, cross-tenant). Ekranlar P-01..P-09.
  Ayrı, **internal-only** Platform Control Plane olarak deploy edilir (ADR-011).
- **L1 — Tenant Admin Console** (tenant admin, tek tenant). Ekranlar T-01..T-09.
- **L2 — Operasyon / Uygulama Paneli** (günlük operasyon, tek tenant). Ekranlar A-01..A-17.
- L1+L2 birlikte, multi-tenant, public *Tenant Application Plane*.

### Altın kural
**L0 (platform), tenant'ın iş içeriğini (çağrı kaydı, transkript, müşteri/PII) varsayılan olarak
GÖREMEZ** — yalnız metrik/kaynak verisi. İçeriğe erişim yalnız **üç katmanlı break-glass** ile
(FR-IAM-008/009/010):
- Tier A (metrik/log, PII yok): break-glass gerekmez.
- Tier B (transkript/kayıt/PII): maker-checker + time-boxed (60 dk default, max 4 sa, standing access yok)
  + gerekçe kodu + tenant `security_compliance_officer`/`tenant_owner`'a bildirim.
- Regüle tenant (finans/sağlık): "tenant onayı zorunlu" toggle, regulated profile'da default açık, DPA bağlı.

## RBAC rol seti (sabit bundle + scoped assignment — FR-IAM-011, ADR-012)
- **L0:** `platform_owner`, `platform_sre`, `platform_billing`.
- **L1:** `tenant_owner` (L1+L2), `tenant_admin`, `security_compliance_officer`, `billing_viewer`,
  `api_developer` (L1+L2).
- **L2:** `operations_manager`, `conversation_designer`, `qa_analyst`, `human_agent`.
- Roller **immutable permission bundle**; v1'de custom permission-builder YOK. Esneklik = atama
  scope filtresiyle (departman/marka/kampanya). Tam custom roller = Faz 3, enterprise/dedicated, şablonla.
- Permission-key formatı: `kaynak:eylem` (ör. `calls:read`, `campaign:manage`, `tenant:provision`,
  `resource:quota:manage`); `*:own` sahiplikle sınırlı. Yetki kararı **her zaman backend'de**.

## Kısıtlar
- Vendor seçimi yapma (vendor-neutral). Secret/credential üretme veya dosyaya yazma.
- Mevcut FR-ID şemasını/numaralandırmayı ve doküman stilini koru.
- Değişiklik yapmadan önce ilgili `docs/*.md` bölümünü oku; geniş değişikliklerde sürümü artır.
