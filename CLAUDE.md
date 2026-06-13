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
- `docs/RTM.md` — İzlenebilirlik Matrisi (Requirements Traceability Matrix). FR/NFR ↔ SR ↔ Test Case (`TC-<ALAN>-NNN`) ↔ WBS. Tabloları `docs/gen_rtm.py` ile **türetilir** (repo kökünden çalıştır); kaynak değişince yeniden üret.
- `docs/DB.md` — Veri Tabanı Tasarımı (Database Design). BRD §16'daki 28 varlık → PostgreSQL şeması (PK/FK, indeks, **RLS politikaları**), tenancy sınıfı, partition, residency/KMS, WORM audit, retention/legal-hold. SAD §12/§13/§14.4 esas.
- `docs/API.md` — API & Interface Design (ICD). 5 yüzey: L0/L1/L2 panel API + Public Developer API (OpenAPI 3.1) + Adapter SPI (STT/TTS/LLM/Telephony). Ortak konvansiyonlar (RFC 9457 hata, idempotency, pagination, rate limit, `x-required-permission`→permission-key), webhook event kataloğu + imzalama/retry, SPI ortak yetenekler + hata taksonomisi + fallback, real-time turn-event/medya/tool sözleşmeleri. SAD §8.1/§8.2/§14.4 esas.
- `docs/THREAT_MODEL.md` — Tehdit Modeli (STRIDE). Varlık envanteri, güven sınırları (TB-1..9) + DFD, STRIDE tehdit kataloğu (`TM-<S/T/R/I/D/E>-NN`, Likelihood×Impact derecelendirme), güvenlik tasarımı derinleştirme (`SEC-01..20`), LLM/voice-özgü tehditler, önerilen ADR-014..017, FR/SR/SAD izlenebilirlik + test eşlemesi. SAD §14/§24 esas. Yaşayan belge: yeni güven sınırı/dış entegrasyon/veri akışı eklenince güncellenir.
- `docs/DPIA.md` — DPIA şablonu + Compliance Profile parametre seti. Controller(tenant)/processor(RMC) rol ayrımı; DPIA tetik kriterleri (`DPIA-T-NN`) + yüksek-risk için onboarding gate; önceden-doldurulmuş DPIA şablonu (§D1..§D9, [SABİT]/[TENANT] alanlar); config-driven compliance profile modeli (`cp.<alan>.<anahtar>` parametre anahtarları, 8 alan: legal/transparency/outbound/residency/retention/dsr/breach/sector); ülke profilleri `PROFILE-TR/UK/EU/ME` (ME composite → alt-ülke `PROFILE-ME-<kod>`); sektörel overlay'ler; **most-restrictive-wins** çözümleme + tenant override yalnız-sıkılaştırır (audit'li). Değerler **mühendislik varsayılanı**; counsel doğrulamasına tabi. BRD §14, SAD §12.3/§19 esas. Yaşayan belge.
- `docs/build-docx.sh` + `docs/make_reference_docx.py` + `docs/assets/rmc-reference.docx` — `.md` → markalı `.docx` artifact hattı (pandoc). `build-docx.sh` docs/*.md'i otomatik keşfeder (todo_list hariç); `all`/`list`/alt-küme komutları, `--regen-ref`/`--no-toc` bayrakları; çıktı `docs/dist/` (gitignore'da). Markalı reference-doc yoksa `make_reference_docx.py` ile otomatik üretilir (stdlib-only; RMC mavi accent1 `#1F4E79`, header/footer + sayfa no, tr-TR yazım dili).
- `docs/adr/` — **Mimari Karar Kayıtları (ADR)** kaynak doğruluğu. Her ADR ayrı, değişmez `NNNN-kebab-baslik.md` (frontmatter: `adr/title/status/date/iz`); `0000-template.md` şablon. Süreç + durum yaşam döngüsü (`Önerilen`/`Kabul`/`Açık`/`Reddedildi`/`Kullanımdan kaldırıldı`/`Yerini aldı`) `docs/adr/README.md`'de. **ADR-ID monoton artan, numara yeniden kullanılmaz; yayımlanan ADR'nin gövdesi düzenlenmez** — karar değişince yeni ADR + `superseded-by`. İndeks tabloları (README + `SAD.md §22`) `docs/adr/gen_adr_index.py` ile **türetilir** (stdlib-only; `--next`/`--list`/`--check`); kaynak ADR değişince repo kökünden yeniden üret. ADR-001..017 backfill edildi.
- `docs/vendor-eval/` — **Vendor değerlendirme (0.2.x)** kaynak doğruluğu. Sağlayıcı-nötr (ADR-002), ölçüt-tabanlı, tekrarlanabilir eval; 0.2.6 karar raporu çerçeveyi sabitler, **bağlayıcı seçim 0.3.x PoC + DPA imzasında** (provizyonel). `telephony-media-latency.md` (0.2.1 — Twilio/Telnyx/SIP medya streaming gecikmesi: M1 managed-WS/M2 ham-SIP-RTP/M3 CC entegrasyon modları, 8 ölçütlü ağırlıklı rubrik, SAD §20 medya bütçesi kapısı tek-yön P95 ≤100ms / yeşil ≤50ms); `media_latency_probe.py` (stdlib-only ölçüm hattı: minimal RFC6455 WS, `serve`/`probe`/`stats`/`compare`, 8kHz/20ms 50fps frame-RTT + jitter + loss + E-model MOS-vekil + bütçe gate→çıkış kodu); `stt-eval.md` (0.2.2 — STT eval: SttAdapter SPI yüzeyi, 8 ölçütlü rubrik C1 final-gecikme/C2 WER/C3 yapısal-CER knock-out + C4 partial-final/C5 confidence/C6 dil/C7 phrase-boost/C8 8kHz; kapılar final P95 ≤200ms SAD §20 / WER ≤0.15 en-kötü-dil EN+TR / yapısal CER ≤0.05); `stt_eval_probe.py` (stdlib-only: `score`/`compare`/`selftest`; Levenshtein WER/CER TR-duyarlı, final-flush gecikme percentile, partial/final yapı kontrolü FR-STT-002, confidence kapsama+ayrım+ECE kalibrasyon, kapı→çıkış kodu); `tts-eval.md` (0.2.3 — TTS eval: TtsAdapter SPI yüzeyi, 8 ölçütlü rubrik C1 first-byte/C2 barge-in-kesme/C3 MOS/C4 ölü-hava knock-out + C5 telaffuz/C6 ses-tutarlılığı/C7 cache/C8 8kHz; kapılar first-byte P95 ≤200ms SAD §20 / barge-in kesme P95 ≤200ms NFR 10.1/SAD §6.1 / MOS ≥4.0 en-kötü-dil EN+TR / underrun=0); `tts_eval_probe.py` (stdlib-only: `score`/`compare`/`selftest`; TTFB+barge-in percentile, MOS en-kötü-dil, dead-air underrun/RTF FR-RES-009, telaffuz oranı FR-TTS-004, cache-hit ayrımı FR-TTS-010, kapı→çıkış kodu); `llm-eval.md` (0.2.4 — LLM eval: LlmAdapter SPI yüzeyi, 8 ölçütlü rubrik C1 first-token-genel/C2 küçük-tier-first-token/C3 kalite-en-kötü-dil/C4 no-train/C5 bölgesel/C6 stall knock-out + C7 tool-call soft/C8 ≥2-tier-fallback; kapılar TTFT genel P95 ≤400ms SAD §20 / küçük-tier P95 ≤200ms FR-LLM-013 / kalite ≥0.85 en-kötü-dil EN+TR / no-train (FR-LLM-012) + bölgesel endpoint (NFR 10.7) + stall=0 zorunlu); `llm_eval_probe.py` (stdlib-only: `score`/`compare`/`selftest`; TTFT genel+per-tier percentile, kalite en-kötü-dil, küçük-tier payı SR-DEN-005, no-train/no-log + bölgesel uygunluk, inter-token stall FR-LLM-004, tool-call oranı FR-LLM-008, kapı→çıkış kodu); `vector-db-eval.md` (0.2.5 — Vector DB eval **pgvector vs OpenSearch**: VectorDbAdapter yüzeyi, RAG retrieval (medya hot-path değil; SAD §10.2/§20 RAG kalemi), 8 ölçütlü rubrik C1 recall-en-kötü-sınıf/C2 retrieval-gecikme/C3 namespace-izolasyon/C4 metadata-ACL/C5 residency-no-log knock-out + C6 index-ops/C7 hybrid/C8 stack-fit soft; kapılar recall@k ≥0.95 en-kötü sorgu sınıfı / retrieval P95 ≤200ms SAD §20 / cross-tenant+ACL sızıntı=0 FR-KB-004/005+FR-TEN-002 / residency+no-log NFR 10.7+FR-KB-010); `vector_db_eval_probe.py` (stdlib-only: `score`/`compare`/`selftest`; recall@k retrieved∩relevant, retrieval percentile genel+sınıf, forbidden-leak cross-tenant/ACL, residency uygunluk, kapı→çıkış kodu); `vendor-decision.md` (0.2.6 — Vendor karar raporu: 0.2.1–0.2.5 teknik kapı roll-up + ticari/uyumluluk/risk boyutları D1–D5, D3 residency/no-train + D4 DPA/alt-işleyen **knock-out**; **ADR-002 portföy kapısı** = her hot-path kategoride ≥2 farklı geçen aday + fallback BRD §19 1–4; SAD §8.4 hipotezlerinden karar kayıtları, bağlayıcı seçim **provizyonel/BEKLEMEDE** → 0.3.x PoC + DPA); `contract-dpa-checklist.md` (0.2.6 — controller=tenant/processor=RMC/sub-processor=sağlayıcı rol modeli; RMC↔sağlayıcı C-01..12 + tenant↔RMC D-01..12 checklist `cp.*` eşlemeli; **alt-işleyen kayıt Ek-A** iskeleti; sağlayıcıya giden veri kaydı BRD §14.1, →17.2.2); `vendor_decision_probe.py` (stdlib-only: `rollup`/`register`/`selftest`; 0.2.x score/stats JSON → kategori çıkarımı + verdict normalizasyonu top-level/`gate.*` + portföy kapısı→çıkış kodu + Ek-A iskeleti; **yeniden ölçmez, seçmez**); `samples/*.json` illüstratif profiller (`managed-*`/`raw-*` telefoni gecikme, `stt-*` STT, `tts-*` TTS, `llm-*` LLM, `vdb-*` Vector DB test setleri). **Sır/credential repoya yazılmaz** (yalnız `--url`/ortam değişkeni).
- `docs/poc/` — **PoC / Spike (0.3.x)** kaynak doğruluğu. Mimari hipotez doğrulama; 0.2.x ile aynı disiplin (sağlayıcı-nötr ADR-002, stdlib-only, credential-free, sanal-saat deterministik). `e2e-inbound-poc.md` (0.3.1 — uçtan uca tek inbound akış PoC tasarımı: PSTN→SBC→MediaGW→STT→Orchestrator(LLM)→TTS→MediaGW→PSTN; SAD↔PoC mimari eşleme; turn state machine SAD §6.1; SAD §20 gecikme kalemleri **yumuşak** rapor — formal P95 kapısı 0.3.2; 9 HARD invariant kapısı); `e2e_inbound_poc.py` (stdlib-only: `run`/`selftest`/`schema`; SPI adapter seam ADR-001/002, turn state machine LISTEN→CAPTURE→THINK→ACT→SPEAK + barge-in SPEAK→CAPTURE TTS-cancel ≤200ms, STT primary→secondary fallback FR-STT-008, correlation_id+tenant context propagation SAD §13.3, AI disclosure karşılama BRD §14.2, session memory, end-of-utterance→ilk-ses gecikme kırılımı, kapı→çıkış kodu); `samples/inbound-*.json` (sentetik senaryolar FR-TST-008: happy-path/barge-in/stt-fallback). **Sır/credential repoya yazılmaz** (canlı PoC yalnız `--url`/ortam değişkeni). Kapsam ayrımı: gecikme→0.3.2, density→0.3.3, medya-konumu/ADR-009→0.3.4, hot-path dil→0.3.5.
- Sıradaki dokümanlar: 0.3.1 E2E inbound PoC tamam → **0.3.2 gecikme bütçesi ölçümü** (P50/P95/P99, barge-in kesme; yumuşak→hard) + **0.3.3 density** + **0.3.4 ADR-009** + **0.3.5 hot-path dil**, ardından **Faz 1 kod**; 0.2.6 provizyonel seçim + DPA/alt-işleyen (17.2.2) canlı PoC çıktısıyla bağlanır.
- **`.md` source of truth'tur; `.docx` üretilen artifact'tir.** İçeriği `.md`'de değiştir, `.docx`'i build et.

## Yazım kuralları
- Ana metin **Türkçe**, teknik terimler İngilizce (mevcut register'a uy).
- **FR-ID şeması:** `FR-<ALAN>-NNN` (ör. `FR-TEN-001`, `FR-IAM-009`, `FR-RES-016`). Yeni ID'leri
  ilgili alanın sırasından devam ettir; mevcut ID/numaralandırmayı **bozma**.
- **SR-ID şeması (SRS):** `SR-<ALAN>-NNN`; `<ALAN>` kodu BRD FR/NFR alanını yansıtır (ör. `SR-RTC-007`→`FR-RTC-002`).
  NFR alanları: `PERF/DEN/SCAL/AVL/DR/SEC/LOC`. Her SR: kaynak FR/NFR + yöntem (T/A/I/D) + ölçülebilir kabul ölçütü.
- **TC-ID şeması (RTM):** `TC-<ALAN>-NNN`; baz test-case SR ile 1:1 hizalanır (`SR-XXX-NNN ⇒ TC-XXX-NNN`).
  Test türü SR yönteminden (T/D/A/I) devralınır. Bir SR gerekirse `TC-XXX-NNN-a/-b`'ye bölünebilir.
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
