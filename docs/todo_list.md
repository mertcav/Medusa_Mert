# Proje Görev Listesi — Work Breakdown Structure (WBS)
## Enterprise Voice AI Agent Platform (chanteur)

> Kaynak: `docs/BRD.md` (v2.1) · `docs/SAD.md` (v1.1). Çelişkide dokümanlar esastır.
> Bu dosya yaşayan bir belgedir; görev tamamlandıkça kutu işaretlenir ve durum güncellenir.

### Nasıl okunur (lejant)
- **WBS ID:** Hiyerarşik numara (ör. `3.2.1`). Üst seviye = workstream/epic, alt seviye = görev/alt-görev.
- **Faz:** `F0` (Temel/Foundation), `F1` (Core Voice Runtime & Pilot), `F2` (Enterprise Contact Centre), `F3` (Hyperscale & Regüle).
- **Öncelik:** MoSCoW — `Must` / `Should` / `Could`.
- **İz:** İlgili BRD FR/NFR/ADR referansı (izlenebilirlik).
- `[ ]` açık · `[~]` devam ediyor · `[x]` tamamlandı · `[!]` bloke/karar bekliyor.

### Faz kapıları (üst seviye plan)
| Faz | Hedef | Çıkış kapısı (gate) |
|-----|-------|----------------------|
| F0 | Proje, doküman, ortam, CI/CD, vendor eval, PoC | PoC gecikme+density doğrulandı (NFR 10.1/10.2); ADR-009 kararı verildi |
| F1 | Inbound core voice runtime + pilot (100–250 eş zamanlı) | BRD §19 kabul kriterleri (inbound altküme) geçti; 1 pilot müşteri canlı |
| F2 | Multi-tenant enterprise contact centre + outbound (1.000–3.000) | SSO/SCIM, outbound consent, CC entegrasyonu, dedicated/residency |
| F3 | Hyperscale active-active (10.000+), PCI, regüle modüller | Multi-region active-active, PCI ödeme, BYOK, marketplace |

### Açık kararlar (bunlar netleşmeden bağımlı görevler bloke)
- `[x]` **ADR-009** — Medya işleme edge'de mi merkezde mi? (density/gecikme dengesi) → **Kabul: hibrit** (edge VAD/endpointing+barge-in per ADR-005 + ayrı/eş-konumsuz medya katmanı). 0.3.4 deneyiyle kapatıldı.
- `[!]` **ADR-010** — Self-hosted LLM + GPU kapsamı → F3.
- `[!]` BRD §22 açık kararları (ilk ülke/sektör, pilot use-case, telekom sağlayıcı, ilk diller, retention süreleri, PCI kapsamı, ilk CC entegrasyonu).

---

## 0. Program Yönetimi & Temel Altyapı (Foundation)

### 0.1 Doküman ve gereksinim hattı
- [x] **0.1.1** SRS (System Requirements Specification) yaz — FR/NFR'leri test edilebilir sistem gereksinimlerine indir — `F0` · `Must` · →BRD §24 · ⇒ `docs/SRS.md` v1.0 (236 SR, 193/193 FR + NFR 10.1–10.7 kapsandı)
- [x] **0.1.2** Tam izlenebilirlik matrisi (FR ↔ SRS ↔ test case ↔ WBS) oluştur — `F0` · `Must` · ⇒ `docs/RTM.md` v1.0 (193 FR + 7 NFR → 236 SR → 236 TC → 168 WBS; FR→SR %100, FR→WBS %93,8; üretici `docs/gen_rtm.py`)
- [x] **0.1.3** Veri Tabanı tasarım dokümanı (BRD §16 varlıkları: PK/FK, indeks, RLS politikaları) — `F0` · `Must` · →BRD §16 · ⇒ `docs/DB.md` v1.0 (28 varlık → tablo + PK/FK + indeks + RLS; tenancy sınıfı, partition, residency/KMS, WORM audit, retention/legal-hold)
- [x] **0.1.4** API tasarım dokümanı (OpenAPI sözleşmeleri + adapter SPI sözleşmeleri) — `F0` · `Must` · →SAD §8.1, §14.4 · ⇒ `docs/API.md` v1.0 (5 yüzey: L0/L1/L2 + Public Developer API OpenAPI 3.1 + Adapter SPI; ortak konvansiyonlar RFC 9457/idempotency/pagination; webhook event kataloğu + imzalama/retry; STT/TTS/LLM/Telephony SPI + ortak yetenekler + hata taksonomisi + fallback; permission-key→endpoint eşlemesi; YAML/JSON örnekleri parse-doğrulandı)
- [x] **0.1.5** Threat model (STRIDE) ve güvenlik tasarım derinleştirme — `F0` · `Must` · →SAD §24 · ⇒ `docs/THREAT_MODEL.md` v1.0 (14 varlık + 9 güven sınırı TB-1..9 + DFD; STRIDE kataloğu TM-S/T/R/I/D/E ~45 tehdit, Likelihood×Impact derecelendirme; 20 güvenlik kontrol derinleştirme SEC-01..20; LLM/voice-özgü tehditler OWASP LLM Top-10 hizalı; önerilen ADR-014..017; FR/SR/SAD izlenebilirlik + test eşlemesi)
- [x] **0.1.6** DPIA şablonu + compliance profile parametre seti (TR/UK/EU/ME) — `F0` · `Must` · →BRD §14 · ⇒ `docs/DPIA.md` v1.0 (controller/processor rol ayrımı; DPIA tetik kriterleri DPIA-T-01..08 + onboarding gate; önceden-doldurulmuş DPIA şablonu §D1..§D9; config-driven compliance profile parametre modeli `cp.*` 8 alan; PROFILE-TR/UK/EU/ME ülke profilleri + ME composite/alt-ülke notu; sektörel overlay PCI/FCA/HIPAA/NHS/SOC2/ISO/DORA/NIS2; most-restrictive-wins çözümleme motoru; enforcement noktaları + FR/SR/SAD izlenebilirlik + test eşlemesi; tüm FR/SR/TC çapraz-referansları doğrulandı)
- [x] **0.1.7** `.docx` üretim hattı (pandoc + branded reference-doc) operasyonelleştir — `F0` · `Should` · →docs/build-docx.sh · ⇒ `build-docx.sh` (8 dokümanı otomatik keşfeder/üretir: `all`/`list`/alt-küme, `--regen-ref`/`--no-toc`, pandoc kontrolü + özet) + `docs/make_reference_docx.py` (RMC markalı reference-doc üreteci: accent1 `#1F4E79`, header/footer+sayfa no, tr-TR; stdlib-only) + `docs/assets/rmc-reference.docx` üretildi; 8/8 doküman uyarısız üretildi, çıktı XML doğrulandı
- [x] **0.1.8** ADR kayıt süreci ve repo'da ADR klasörü disiplinini kur — `F0` · `Should` · ⇒ `docs/adr/` (süreç+disiplin): `README.md` (ne zaman ADR, `ADR-NNNN` numaralandırma, durum yaşam döngüsü, oluşturma akışı), `0000-template.md` (MADR-uyarlı TR şablon: bağlam→sürücüler→seçenekler→karar→sonuçlar→izlenebilirlik), `gen_adr_index.py` (stdlib-only üreteç: `--next`/`--list`/`--check`; README + `SAD.md §22` indeks tablolarını işaretçiler arası türetir), ADR-001..017 backfill (SAD §22'deki 13 + THREAT_MODEL ADR-014..017); `SAD §22` türetilen indekse çevrildi, CLAUDE.md doküman yapısı + THREAT_MODEL atfı güncellendi; `--check` 17/17 güncel

### 0.2 Vendor değerlendirme (PoC'li)
- [x] **0.2.1** Telekom sağlayıcı eval (Twilio/Telnyx/SIP) — medya streaming gecikmesi — `F0` · `Must` · →ADR-002 · ⇒ `docs/vendor-eval/` (sağlayıcı-nötr eval hattı): `telephony-media-latency.md` (3 entegrasyon modu M1 managed-WS/M2 ham-SIP-RTP/M3 CC; 8 ölçütlü ağırlıklı rubrik, C1 taşıma gecikmesi knock-out kapısı; SAD §20 medya bütçesi tek-yön P95 ≤100ms / yeşil ≤50ms) + `media_latency_probe.py` (stdlib-only; minimal RFC6455 WS; `serve`/`probe`/`stats`/`compare`; 8kHz/20ms 50fps frame-RTT, jitter, loss, E-model MOS-vekil, bütçe gate→exit kodu) + `samples/` (illüstratif profiller, ≥2 managed aday). Self-test+senaryo+stats+compare doğrulandı; nihai seçim → 0.2.6 (vendor-neutral)
- [x] **0.2.2** STT eval (≥2 sağlayıcı): streaming partial/final, confidence, dil (EN+TR), 8kHz — `F0` · `Must` · →FR-STT-001 · ⇒ `docs/vendor-eval/` (sağlayıcı-nötr STT eval): `stt-eval.md` (SttAdapter SPI yüzeyi; 8 ölçütlü ağırlıklı rubrik C1 final-gecikme/C2 WER/C3 yapısal-CER knock-out kapıları + C4 partial-final/C5 confidence/C6 dil/C7 phrase-boost/C8 8kHz-residency-no-train; metrik tanımları WER en-kötü-dil EN+TR + CER yapısal alan; kapılar final P95 ≤200ms SAD §20 / WER ≤0.15 / CER ≤0.05) + `stt_eval_probe.py` (stdlib-only; `score`/`compare`/`selftest`; Levenshtein WER/CER TR-duyarlı küçük harf, final-flush gecikme P50/P95/P99, partial/final yapı kontrolü FR-STT-002, confidence kapsama+ayrım+ECE kalibrasyon FR-STT-006/007, kapı→çıkış kodu) + `samples/stt-cloud-A/B/C-degraded.json` (illüstratif ≥2 aday + 1 elenen profil). 17/17 selftest + 3 sağlayıcı score + compare doğrulandı; A→SARI(pass), B/C→KIRMIZI(fail) kapı elemesi gösterildi; nihai seçim → 0.2.6 (vendor-neutral)
- [x] **0.2.3** TTS eval (≥2 sağlayıcı): first-byte gecikme, barge-in kesme, ses kalitesi — `F0` · `Must` · →FR-TTS-001/002 · ⇒ `docs/vendor-eval/` (sağlayıcı-nötr TTS eval): `tts-eval.md` (TtsAdapter SPI yüzeyi; 8 ölçütlü ağırlıklı rubrik C1 first-byte/C2 barge-in-kesme/C3 MOS/C4 ölü-hava knock-out kapıları + C5 telaffuz/C6 ses-tutarlılığı/C7 cache/C8 8kHz-residency-no-train; metrik tanımları MOS en-kötü-dil EN+TR + barge-in cancel→stop + dead-air underrun/RTF; kapılar first-byte P95 ≤200ms SAD §20 / barge-in P95 ≤200ms NFR 10.1 / MOS ≥4.0 en-kötü-dil / underrun=0) + `tts_eval_probe.py` (stdlib-only; `score`/`compare`/`selftest`; TTFB/barge-in P50/P95/P99 percentile, MOS en-kötü-dil FR-TTS-001/003, dead-air underrun+RTF FR-RES-009, telaffuz oranı FR-TTS-004, cache-hit ayrımı FR-TTS-010, kapı→çıkış kodu) + `samples/tts-cloud-A/B/C-degraded.json` (illüstratif ≥2 aday + 1 elenen profil). 19/19 selftest + 3 sağlayıcı score + compare doğrulandı; A→SARI(pass), B→KIRMIZI(TR MOS 3.6 en-kötü-dil eler), C→KIRMIZI(TTFB 342ms + barge-in 393ms + ölü hava) kapı elemesi gösterildi; nihai seçim → 0.2.6 (vendor-neutral)
- [x] **0.2.4** LLM eval (≥2 sağlayıcı + küçük/büyük tier): first-token, "no-train" endpoint, bölgesel — `F0` · `Must` · →FR-LLM-001/012 · ⇒ `docs/vendor-eval/` (sağlayıcı-nötr LLM eval): `llm-eval.md` (LlmAdapter SPI yüzeyi; 8 ölçütlü ağırlıklı rubrik C1 first-token-genel/C2 küçük-tier-first-token/C3 kalite-en-kötü-dil/C4 no-train/C5 bölgesel/C6 stall knock-out kapıları + C7 tool-call soft + C8 ≥2-tier/fallback; metrik tanımları TTFT genel+küçük/büyük tier ayrı, kalite en-kötü-dil EN+TR, no-train=noTrain+NONE/EPHEMERAL, bölgesel=region pinning, stall=inter-token boşluk; kapılar TTFT genel P95 ≤400ms SAD §20 / küçük-tier P95 ≤200ms FR-LLM-013 / kalite ≥0.85 en-kötü-dil / no-train+bölgesel+stall=0 zorunlu) + `llm_eval_probe.py` (stdlib-only; `score`/`compare`/`selftest`; TTFT genel+per-tier P50/P95/P99, kalite en-kötü-dil, küçük-tier payı raporu SR-DEN-005, no-train/no-log + bölgesel uygunluk, inter-token stall FR-LLM-004, tool-call oranı FR-LLM-008, kapı→çıkış kodu) + `samples/llm-cloud-A/B/C-degraded.json` (illüstratif ≥2 aday + 1 elenen profil). 27/27 selftest + 3 sağlayıcı score + compare doğrulandı; A→SARI(pass), B→KIRMIZI(TR kalite 0.815 en-kötü-dil eler), C→KIRMIZI(bölgesel yok + no-train kapalı + TTFT 511ms + stall) kapı elemesi gösterildi; nihai seçim → 0.2.6 (vendor-neutral)
- [x] **0.2.5** Vector DB eval (pgvector vs OpenSearch) — `F0` · `Should` · →SAD §12.1 · ⇒ `docs/vendor-eval/` (sağlayıcı-nötr Vector DB eval): `vector-db-eval.md` (VectorDbAdapter yüzeyi; RAG retrieval — medya hot-path değil, SAD §10.2/§20 RAG kalemi; 8 ölçütlü ağırlıklı rubrik C1 recall-en-kötü-sorgu-sınıfı/C2 retrieval-gecikme/C3 namespace-tenant-izolasyon/C4 metadata-ACL-filtre/C5 residency-no-log knock-out kapıları + C6 index-ops/C7 hybrid-search/C8 operasyonel-stack-fit soft; metrik tanımları recall@k=retrieved∩relevant exact-kNN ground-truth en-kötü sorgu sınıfı + cross-tenant/ACL forbidden-leak + residency pinning+no-log; kapılar recall@k ≥0.95 en-kötü sınıf / retrieval P95 ≤200ms SAD §20 / cross-tenant+ACL sızıntı=0 FR-KB-004/005+FR-TEN-002 / residency+no-log NFR 10.7+FR-KB-010) + `vector_db_eval_probe.py` (stdlib-only; `score`/`compare`/`selftest`; recall@k retrieved∩relevant, retrieval P50/P95/P99 genel+sınıf, forbidden-leak cross-tenant/filtreli-ACL, residency uygunluk, kapı→çıkış kodu) + `samples/vdb-pgvector/opensearch/managed-degraded.json` (illüstratif ≥2 aday + 1 elenen profil). 28/28 selftest + 3 aday score + compare doğrulandı; pgvector→SARI(pass, 60ms yeşil-gecikme+native RLS) ve OpenSearch→SARI(pass, 120ms+native hybrid) iki meşru aday geçti, managed-degraded→KIRMIZI (residency yok + dış log + cross-tenant sızıntı + ACL ihlali + structured recall 0.35 + retrieval 286ms) çoklu kapı elemesi gösterildi; nihai seçim → 0.2.6 (vendor-neutral)
- [x] **0.2.6** Vendor karar raporu + sözleşme/DPA/alt-işleyen listesi taslağı — `F0` · `Must` · →SAD §8.1/§8.4, ADR-002, BRD §14.1/§19 · ⇒ `docs/vendor-eval/` (0.2.x sentez/kapanış): `vendor-decision.md` (sağlayıcı-nötr karar çerçevesi: 0.2.1–0.2.5 teknik kapı roll-up + ticari/uyumluluk/risk boyutları D1–D5, D3 residency/no-train + D4 DPA/alt-işleyen **knock-out**; ADR-002 **portföy kapısı** = her hot-path kategoride ≥2 farklı geçen aday + fallback BRD §19 1–4; SAD §8.4 hipotezlerinden karar kayıtları — bağlayıcı seçim **provizyonel/BEKLEMEDE**, 0.3.x PoC + DPA imzasına bağlı) + `contract-dpa-checklist.md` (controller=tenant/processor=RMC/sub-processor=sağlayıcı rol modeli; RMC↔sağlayıcı C-01..12 + tenant↔RMC D-01..12 checklist `cp.*` eşlemeli; **alt-işleyen kayıt Ek-A** iskeleti; sağlayıcıya giden veri kaydı BRD §14.1) + `vendor_decision_probe.py` (stdlib-only; `rollup`/`register`/`selftest`; 0.2.x score/stats JSON → kategori çıkarımı + verdict normalizasyonu top-level/`gate.*` + portföy kapısı→çıkış kodu; Ek-A iskeleti config bayraklarından; **yeniden ölçmez, seçmez**). 16/16 selftest + uçtan uca rollup (illüstratif set: telekom 3 geçer ✅ + STT/TTS/LLM her biri 1 geçen → 🔴 portföy eksik kapı elemesi gösterildi, B adayları kasıtlı KIRMIZI) + register doğrulandı; nihai seçim **0.3.x'e** ertelendi (vendor-neutral)

### 0.3 PoC / Spike (mimari doğrulama)
- [x] **0.3.1** Uçtan uca tek inbound akış PoC (telefon→STT→LLM→TTS→telefon) — `F0` · `Must` · →SAD §25 · ⇒ `docs/poc/` (sağlayıcı-nötr E2E spike): `e2e-inbound-poc.md` (tasarım: PSTN→SBC→MediaGW→STT→Orchestrator(LLM)→TTS→MediaGW→PSTN akışı; SAD↔PoC mimari eşleme; turn state machine LISTEN→CAPTURE→THINK→ACT→SPEAK + barge-in; SAD §20 gecikme bütçesi kalemleri; 9 HARD invariant kapısı; kapsam ayrımı 0.3.2 gecikme/0.3.3 density/0.3.4 ADR-009/0.3.5 hot-path) + `e2e_inbound_poc.py` (stdlib-only; `run`/`selftest`/`schema`; SPI adapter seam ADR-001/002, sanal saat deterministik, edge VAD/endpointing+barge-in, STT primary→secondary fallback FR-STT-008, correlation_id+tenant context propagation SAD §13.3, AI disclosure karşılama BRD §14.2, session memory kalıcılaştırma, end-of-utterance→ilk-ses gecikme kırılımı, kapı→çıkış kodu) + `samples/inbound-happy-path/barge-in/stt-fallback.json` (sentetik senaryolar FR-TST-008) + `README.md`. 21/21 selftest + 3 senaryo uçtan uca 🟢 GEÇTİ (happy P50≈578ms/P95≈669ms illüstratif, ≤1200ms yeşil); gecikme **yumuşak** (formal P95 kapısı 0.3.2). Vendor seçmez; canlı PoC'ta aynı SPI'ye gerçek adapter takılır
- [x] **0.3.2** Gecikme bütçesi ölçümü (P50/P95/P99, barge-in kesme) — `F0` · `Must` · →NFR 10.1, SAD §20 · ⇒ `docs/poc/` (0.3.1'in **yumuşak** gecikmesini **HARD** kapıya çevirir): `latency-budget.md` (end-of-utterance→ilk ses metriği SAD §20 tam zincir endpointing dahil; lognormal bileşen modeli median+p95; tier/cache/rag/tool tur-mix; NFR 10.1 HARD kapı e2e P50≤700/P95≤1200/P99≤2000 + barge-in P95≤200 + tool overhead P95≤100; bileşen-içi SAD §20 bant yumuşak flag; bileşen atfı/headroom) + `latency_budget_probe.py` (stdlib-only; `measure`/`compare`/`selftest`/`schema`; tohumlu Monte-Carlo deterministik örnekleme, lognormal(p50,p95) kalibrasyon, P50/P95/P99 lineer-interp percentile 0.3.1 ile aynı, uç-uca + barge-in + tool dağılımları, bileşen atfı pay%/headroom, kapı→çıkış kodu) + `samples/latency-green-baseline/tail-heavy/red-degraded.json` (illüstratif profiller FR-TST-008). selftest GEÇTİ 11 grup/20 kontrol (lognormal median/p95 kalibrasyon ±%4, kapı geçer/eler, determinizm birebir, atıf payları≈%100, küçük-tier↑→P95↓); green→🟢 (P50 632/P95 863/P99 968ms, barge 149ms — tümü geçer), tail-heavy→🔴 (P50 695 geçer ama **P95 1242 eler** — kuyruk riski, median-bakışı yetersiz), red-degraded→🔴 (P50/P95/P99+barge-in+tool hepsi eler). Bulgu: bütçe **dar** — green'de bile ~%36 LLM first-token + ~%22 endpointing → 0.3.4 (medya konumu/ADR-009) + 0.3.5 (hot-path runtime) girdisi. Vendor-neutral; canlı PoC'ta aynı profil yapısı gerçek telemetri ile doldurulur
- [x] **0.3.3** Density ölçümü (oturum/worker, ~15MB/oturum) — `F0` · `Must` · →NFR 10.2, ADR-003 · ⇒ `docs/poc/` (0.3.2'nin disiplinini density'ye taşır — NFR 10.2'yi HARD kapıya çevirir): `density-measurement.md` (metrik: oturum-başı orkestratör belleği **medya HARİÇ** ≤15MB FR-RES-016 + worker density = **bellek ∩ CPU** kapasitesi ≥250–500; lognormal bileşen modeli median+p95 — session/dialogue/prompt/rag/adapter/runtime; mean-packing CLT-kapı + p95-packing muhafazakar; medya eş-konumu **duyarlılık** girdisi → 0.3.4/ADR-009; NFR 10.2 HARD kapı bütçe P95≤15MB + density≥250, stretch ≥500 yumuşak) + `density_probe.py` (stdlib-only; `measure`/`compare`/`selftest`/`schema`; Monte-Carlo tohumlu deterministik, `LogNormalComponent`+`percentile` 0.3.2 ile birebir, medya draw'ları **ayrı RNG stream** → bütçe medya konumundan bağımsız, bileşen atfı pay%, kapı→çıkış kodu) + `samples/density-green-baseline/media-colocated/red-degraded.json` (illüstratif profiller FR-TST-008). selftest 13/13 GEÇTİ (kalibrasyon/kapı/determinizm/medya-hariç invariant'ı/uzun-oturum↑→bellek↑); green→🟢 (P95 13.9MB ≤15, density 552 ≥500 stretch dahil, bottleneck=CPU), media-colocated→🟢 (bütçe değişmez 13.9MB ama density 552→355 → ≥250 geçer 500 ıskalar), red-degraded→🔴 (özetsiz geçmiş+thread-per-call → bütçe 35.5MB + density 158 ikisi de eler — ADR-003 ihlali). Bulgu: **density CPU-bağlı** (16GB worker'da 15MB bütçe ~1300 oturuma yer verir, tavanı CPU koyar) → 0.3.5 hot-path Go/Rust girdisi; medya konumu density'yi ~%35 keser → 0.3.4/ADR-009 girdisi. Vendor-neutral; canlı PoC'ta (0.3.5) aynı profil gerçek RSS/heap+CPU telemetri ile dolar
- [x] **0.3.4** Medya işleme konumu deneyi (edge vs merkez) → **ADR-009 kararı** — `F0` · `Must` · →ADR-009 · ⇒ `docs/poc/` (0.3.2 gecikme + 0.3.3 density HARD kapılarını tek karar deneyinde birleştirir): `media-placement.md` (edge/merkez/hibrit topolojileri; topolojiye-bağlı yalnız medya/ağ kalemi + barge-in kesme + medya eş-konumu değişir, `rest_of_chain` sabit; birleşik NFR 10.1+10.2 kapısı; ölçülen latency/bargein/density + beyan ops/cost/residency ağırlıklı karar matrisi toplam 1.0) + `media_placement_probe.py` (stdlib-only; `evaluate`/`compare`/`selftest`/`schema`; `LogNormalComponent`+`percentile` 0.3.1/0.3.2/0.3.3 ile birebir, tohumlu Monte-Carlo, e2e+barge-in+density birleşik kapı→çıkış kodu, HARD-geçen adaylar arası ADR-009 önerisi) + `samples/media-{edge,central,hybrid}.json` (illüstratif FR-TST-008). 12/12 selftest + 3 topoloji evaluate + compare doğrulandı: **merkez 🔴 barge-in P95≈266ms eler** (ADR-005'i doğrular) + density 554→354; **edge 🟢 geçer ama ops/cost/residency cezası** (skor 0.486); **hibrit 🟢 her iki kapı + en yüksek skor 0.605 → ADR-009 ÖNERİSİ**. **ADR-009 `Açık`→`Kabul` (hibrit)**; ADR indeks + SAD §6.4/§23 güncellendi. Vendor/dil-nötr; canlı PoC (0.3.5) aynı profil yapısını gerçek telemetri ile doldurur
- [?] **0.3.5** Hot-path dil doğrulaması (Go/Rust async runtime) — `F0` · `Must` · →ADR-003

### 0.4 Mühendislik altyapısı (platform engineering)
- [?] **0.4.1** Mono/poly-repo stratejisi + repo yapısı (data plane / control plane ayrı) — `F0` · `Must` · →ADR-004
- [?] **0.4.2** IaC (Terraform) — bölge, ağ (VPC/segmentasyon), private endpoint — `F0` · `Must` · →NFR 10.6
- [?] **0.4.3** Kubernetes cluster(lar) + namespace stratejisi — `F0` · `Must` · →SAD §16.1
- [?] **0.4.4** CI/CD hattı (build/test/lint/SAST/DAST/dependency scan/SBOM) — `F0` · `Must` · →NFR 10.6
- [?] **0.4.5** Secrets yönetimi (Vault/KMS) + BYOK iskeleti — `F0` · `Must` · →NFR 10.6
- [?] **0.4.6** Ortam matrisi: draft/test/staging/production — `F0` · `Must` · →FR-AGT-005
- [x] **0.4.7** Gözlemlenebilirlik omurgası (OTel + Prometheus + Grafana + Loki) iskeleti — `F0` · `Must` · →SAD §17 · ⇒ `docs/platform/observability/` (vendor-neutral, credential-free iskelet): `observability-spec.json` (makine-okunur kaynak doğruluk: 20 metrik BRD §15 + 15 span + 11 alarm SAD §17.2 + label/kardinalite politikası + sampling + 3 pipeline) + `observability-backbone.md` (tasarım: tek-giriş/üç-sinyal/çok-çıkış mimari, span modeli SAD §17.1, kardinalite disiplini, alarm kataloğu, izlenebilirlik) + `observability_probe.py` (stdlib-only doğrulayıcı: `validate`/`coverage`/`selftest`/`schema`; kapsam + kardinalite + alarm bütçesi ≤2dk NFR 10.1 + çapraz-tutarlılık → çıkış kodu) + `config/` (otel-collector.yaml tail-sampling+tenant-context+PII/kardinalite guard; prometheus.yml; alerts.yaml 11 kural `for:`≤2dk; loki.yaml multi-tenant; grafana voice-runtime panosu refresh≤60sn FR-ANA-012) + README. selftest 11/11 + validate 5 kapı 🟢 (çıkış 0) + coverage BRD §15/SAD §17.2 %100; bugfix: `$comment` meta-anahtarı dosya sanma → atla. F1 §14.1 temeli (vendor-neutral)
- [x] **0.4.8** Yük/performans test ortamı (call generator/synthetic load) — `F0` · `Should` · →FR-TST-006 · ⇒ `docs/platform/load-testing/` (vendor/dil-nötr, credential-free, sentetik FR-TST-008): `load-test-harness.md` (tasarım: sentetik çağrı üreteci↔SUT mimari eşleme; Little yasası kapasite + Poisson geliş + ramp/soak/burst profil; autoscale/warm pool FR-RES-013 + admission/backpressure FR-RES-014 graceful red; tıkanma f(util) yük-altı gecikme/bellek bozulma modeli; 6 HARD kapı; senaryolar) + `load_test_probe.py` (stdlib-only kesikli-zaman simülasyon `run`/`compare`/`selftest`/`schema`; tohumlu Poisson geliş + autoscale gecikmesi + admission muhasebeli red + yük-altı e2e gecikme [0.3.2 base × f(util)] + yük-altı çağrı-başı bellek [0.3.3 base × büyüme]; `LogNormalComponent`+`percentile` 0.3.2/0.3.3 ile birebir; kapı→çıkış kodu) + `scenarios/load-{pilot,enterprise,hyperscale,burst-2x,overload-degraded}.json` (illüstratif Faz hedefleri BRD §20). selftest 12/12 🟢 (Little/Poisson kalibrasyon, green hard_pass, red 6-kapı elemesi, determinizm, kapasite↑→red↓, congestion↑→gecikme↑); 4 senaryo 🟢 (hyperscale 100 CPS×10.000 steady: headroom %41.6, soak red %0, yük-altı P95 988ms, bellek P95 14.4MB, util 0.80 — **FR-TST-006/§19(11) karşılanabilir**) + burst-2x 🟢 (2x ani trafik warm pool+autoscale ile red %0 emildi, NFR 10.3) + degrade 🔴 (yetersiz workers_max + admission≥1.0 + yüksek tıkanma → 6/6 kapı eler). Bugfix/bulgu: 2x burst **mutlak region tavanında emilemez** (graceful shed) → 2x absorpsiyon `workers_max≥2×steady` kapasite planlaması girdisi (BRD §10.3); hyperscale steady tavan, burst absorpsiyonu izole `load-burst-2x`. İskelet kapısı; canlı yük testi F1 §18.5/§18.6'da gerçek trunk+telemetri ile dolar

---

## 1. Veri Mimarisi & Persistence

### 1.1 Şema ve depolar
- [x] **1.1.1** PostgreSQL şeması: Tenant, Org Unit, User, Role (+ RLS) — `F1` · `Must` · →BRD §16, SAD §13.1 · ⇒ `db/` (DB.md §5.1 tasarımının ilk fiziksel dilimi; araç-nötr SQL migration'lar, credential-free): `migrations/0001_extensions_helpers` (citext/pgcrypto + **`gen_uuid_v7()`** RFC 9562 UUIDv7 üreteci DB.md §3 + `set_updated_at`/`raise_immutable_violation` + **`app_rw`** RLS-bypass-etmeyen uygulama rolü DB.md §6.1) + `migrations/0002_tenant_org_iam` (7 tablo: tenant/organisation_unit/app_user/role/permission_key/role_permission/user_role_assignment; UUIDv7 PK, FK `ON DELETE RESTRICT`, FK indeksleri; sağlamlaştırma: app_user realm↔tenant_id CHECK FR-IAM-008 + platform e-posta partial-unique) + `migrations/0003_rls_tenant_org_iam` (**ENABLE+FORCE RLS** + politikalar: org_unit standart izolasyon, tenant Root self+platform-only-write FR-TEN-001, app_user/user_role_assignment karışık desen DB.md §6.3; **fail-closed** `current_setting('app.*',true)`; **WITH CHECK** cross-tenant write koruması; global rol tabloları RLS-dışı + app_rw'ye REVOKE ALL/GRANT SELECT) + `seeds/roles.sql` (12 sabit rol FR-IAM-011/ADR-012, idempotent) + `tests/rls_isolation.sql`+`run_live_test.sh` (canlı RLS davranış kapısı, CI/sunucu varsa; yoksa SKIP) + `schema_probe.py` (stdlib-only statik kapı: `validate`/`selftest`/`schema`). selftest 14/14 🟢 + validate **72/72** 🟢 (UUIDv7 sürüm/variant bitleri, tenant_id+RLS, fail-closed, WITH CHECK, BYPASSRLS-yok, global salt-okunur, FK indeks, down-drop, seed eşlemesi, DB.md izlenebilirlik). Canlı RLS testi F1 §0.4.4/§12.2.3'te gerçek sunucuyla koşar (DB.md §10). Vendor-neutral; her up/down ileri-yönlü+idempotent
- [x] **1.1.2** Agent, Agent Version, Prompt, Conversation Flow, Voice/Model/STT Profile şeması — `F1` · `Must` · →BRD §16 (5–11), SAD §13.1 · ⇒ `db/` (DB.md §5.2 tasarımının ikinci fiziksel dilimi; 1.1.1 deseniyle birebir, araç-nötr migration, credential-free): `migrations/0004_agent_config` (7 tablo: agent/agent_version/prompt/conversation_flow/voice_profile/model_profile/stt_profile; UUIDv7 PK, tenant_id NOT NULL FK `ON DELETE RESTRICT`, FK indeksleri, conversation_flow.graph **GIN**; **dairesel FK** agent.active_version_id→agent_version inline değil **ALTER** ile DB.md §10; **agent_version WORM** §6.5/FR-AGT-006: BEFORE UPDATE OR DELETE → raise_immutable_violation trigger) + `migrations/0005_rls_agent_config` (7 tablo saf tenant-scoped → **ENABLE+FORCE RLS** + standart `tenant_isolation` USING+WITH CHECK fail-closed; mutable config app_rw CRUD; **agent_version WORM grant** REVOKE ALL + yalnız GRANT SELECT,INSERT — UPDATE/DELETE yok) + `tests/agent_config_isolation.sql` (canlı RLS+WORM kapısı: izolasyon, cross-tenant write reddi, dairesel FK çözümü, agent_version UPDATE/DELETE reddi, platform realm iş-config görmez = altın kural; fail-closed için GUC **NULL** reset — `''::uuid` hata fırlatır) + `run_live_test.sh`/`schema_probe.py` genişletildi. selftest **20/20** 🟢 + validate **140/140** 🟢 (1.1.1 72 korundu + 1.1.2 68 eklendi: tablo/UUIDv7 PK, tenant_id NOT NULL, RLS+WITH CHECK, fail-closed, dairesel-FK-deferred, WORM trigger+grant, GIN, FK indeks, down-drop+FK-drop+policy, agent_version'a hiç UPDATE/DELETE grant yok, DB.md izlenebilirlik FR-AGT-001/003/006+FR-LLM-012). Canlı RLS+WORM testi F1 §0.4.4/§12.2.3'te gerçek sunucuyla koşar. Vendor-neutral; her up/down ileri-yönlü+idempotent
- [x] **1.1.3** Call, Call Leg, Transcript, Recording, Event, Tool Execution şeması — `F1` · `Must` · →BRD §16 (19–24), SAD §13.1 · ⇒ `db/` (DB.md §5.5/§7.2 tasarımının üçüncü fiziksel dilimi; yüksek hacim / partition'lı; 1.1.1/1.1.2 deseniyle birebir, araç-nötr migration, credential-free): `migrations/0006_call_interaction` (7 tablo: call/call_leg/transcript/transcript_segment/recording/call_event/tool_execution; tümü **RANGE (created_at) partition'lı** + `(id, created_at)` kompozit PK + UUIDv7 default; tenant_id NOT NULL **gerçek FK**, call→agent/agent_version gerçek FK; **call_id/transcript_id mantıksal FK** — partition'lı parent'a REFERENCES yok DB.md §7.2; campaign_id/tool_id mantıksal — tablolar 1.1.4'te, FK sonra ALTER; her tablo **DEFAULT partition** [insert güvenlik ağı] + **`create_month_partition()`** aylık yardımcı DB.md §7.2; **tool_execution WORM** §6.5/P4: BEFORE UPDATE OR DELETE trigger + idempotency UNIQUE (tenant_id, idempotency_key, created_at) FR-TOOL-009; call_event payload **GIN**, recording retention **partial index** WHERE legal_hold=false) + `migrations/0007_rls_call_interaction` (7 tablo saf tenant-scoped → **ENABLE+FORCE RLS** + standart `tenant_isolation` USING+WITH CHECK; mutable 6 tablo app_rw CRUD; **tool_execution WORM grant** REVOKE ALL + yalnız INSERT+SELECT) + `tests/call_interaction_isolation.sql` (canlı RLS+WORM+**partition** kapısı: izolasyon, partition routing `tableoid`→`call_p202606`, cross-tenant write reddi, idempotency duplicate reddi, tool_execution UPDATE/DELETE reddi, mutable call UPDATE geçer, platform realm transcript görmez = altın kural) + `run_live_test.sh`/`schema_probe.py` genişletildi. selftest **30/30** 🟢 + validate **240/240** 🟢 + **canlı PostgreSQL 16 ile uçtan uca 🟢** (3 test dosyası, up→test→down, re-runnable). **Bugfix (çapraz, güvenlik):** fail-closed politikalar `current_setting(...)::uuid` çıplak cast'ti; bağlantı havuzunda `SET LOCAL` sonrası placeholder **boş-string'e (`''`) döner, NULL değil** → çıplak `''::uuid` *hata* fırlatır (fail-error, fail-closed değil). Tüm politikalar **`NULLIF(current_setting(...),'')::uuid`** ile sertleştirildi (0003/0005/0007 + DB.md §6.2/§6.3/§6.4); havuz-unutulmuş-scope artık 0 satır (gerçek fail-closed), canlı doğrulandı. 1.1.1/1.1.2 canlı testleri ilk kez gerçek sunucuda koşturuldu (önce hep SKIP'ti) + GUC '' reset bug'ı düzeltildi. Vendor-neutral; her up/down ileri-yönlü; partition yönetimi operasyonel (DB.md §7.2)
- [x] **1.1.4** Campaign, Contact, Consent, Usage Record, Call Evaluation, Audit Log, Incident şeması — `F2` · `Must` · →BRD §16 (16–18, 25–28), SAD §13.1 · ⇒ `db/` (DB.md §5.4/§5.6 tasarımının dördüncü fiziksel dilimi; BRD §16'nın **28 varlığını tamamlar**; 1.1.1–1.1.3 deseniyle birebir, araç-nötr migration, credential-free): `migrations/0008_outbound_ops_governance` (7 tablo: campaign/contact/consent/call_evaluation [non-partition] + usage_record/audit_log [**RANGE created_at partition'lı** + `(id,created_at)` PK + UUIDv7 + DEFAULT partition]; tenant_id NOT NULL gerçek FK [saf tenant-scoped 5], tenant_id **NULL'lanabilir** [karışık audit_log/incident]; **audit_log FK YOK** [WORM bağımsızlık DB.md §5.6 — tenant_id/actor_user_id/break_glass_id plain UUID]; call_id mantıksal FK [partition'lı call'a REFERENCES yok §7.2]; **consent + audit_log WORM** §6.5/P4: BEFORE UPDATE OR DELETE → raise_immutable_violation trigger; **gecikmeli FK kapatma** — 0006'da mantıksal bırakılan `call.campaign_id` artık **`ALTER TABLE call ADD CONSTRAINT fk_call_campaign`** gerçek FK [partition'lı call→normal campaign, PG destekler]; contact DNC partial index, consent son-durum index) + `migrations/0009_rls_outbound_ops_governance` (5 standart `tenant_isolation` USING+WITH CHECK fail-closed + **2 karışık `tenant_or_platform`** [audit_log/incident: `tenant_id = NULLIF(...) OR (tenant_id IS NULL AND app.platform='on')` — tenant kendi satırı, platform realm yalnız tenant_id IS NULL → **altın kural** DB.md §6.3]; mutable 5 tablo app_rw CRUD; **consent/audit_log WORM grant** REVOKE ALL + yalnız INSERT+SELECT) + `tests/outbound_ops_governance_isolation.sql` (canlı RLS+WORM+partition+**karışık-politika** kapısı: fail-closed, izolasyon, partition routing `usage_record_p202606`/`audit_log_p202606`, yeni call→campaign FK reddi, cross-tenant write reddi, consent UPDATE + audit_log DELETE WORM reddi, mutable incident UPDATE geçer, tenant sahte-platform write reddi, platform realm yalnız platform satırı görür + tenant-spesifik yazamaz) + `run_live_test.sh`/`schema_probe.py` genişletildi. selftest **33/33** 🟢 + validate **327/327** 🟢 (240 korundu + 87 eklendi) + **canlı PostgreSQL 16.14 ile uçtan uca 🟢** (4 test dosyası, up→test→down, re-runnable, exit 0; 11/11 assertion). Yeni desenler: karışık platform+tenant RLS (`mixed_policy_ok` predikatı) + gecikmeli FK kapatma. Kapsam dışı (bilinçli): `break_glass_grant` + Tier B `break_glass_read` ek politikası → IAM/break-glass dilimi (1.1.3 deseniyle tutarlı). Vendor-neutral; her up/down ileri-yönlü; partition yönetimi operasyonel (DB.md §7.2)
- [ ] **1.1.5** Redis (session memory, semantic/TTS cache index) kurulum + TTL politikaları — `F1` · `Must` · →SAD §12.1
- [ ] **1.1.6** Nesne depolama (S3-uyumlu) tenant-bazlı bucket/prefix + KMS + lifecycle — `F1` · `Must` · →SAD §12.1
- [ ] **1.1.7** Vector store (pgvector/OpenSearch) namespace (tenant+agent) — `F1` · `Must` · →FR-KB-004
- [ ] **1.1.8** Event stream (Kafka) topic tasarımı + replay politikası — `F1` · `Must` · →ADR-007
- [ ] **1.1.9** OLAP (ClickHouse/BigQuery) analitik şeması — `F2` · `Must` · →SAD §12.1

### 1.2 Veri yönetişimi
- [ ] **1.2.1** Row-level security politikaları (her tablo `tenant_id`) — `F1` · `Must` · →FR-TEN-002
- [ ] **1.2.2** Veri yerleşimi (residency): home-region eşlemesi + bölge zorlama — `F2` · `Must` · →NFR 10.7
- [ ] **1.2.3** Retention motoru (otomatik saklama + geri döndürülemez silme) — `F1` · `Must` · →FR-REC-006/010
- [ ] **1.2.4** Legal hold mekanizması — `F2` · `Should` · →FR-REC-007
- [ ] **1.2.5** Backup/restore + RPO doğrulama (config ≤5dk, analitik ≤15dk) — `F2` · `Must` · →NFR 10.5

---

## 2. Telefoni & Gerçek Zamanlı Medya

### 2.1 Telephony edge / çağrı kontrolü
- [ ] **2.1.1** SBC kurulumu (SIP güvenlik, topoloji gizleme, DDoS/SIP saldırı) — `F1` · `Must` · →NFR 10.6, FR-TEL-002
- [ ] **2.1.2** SIP App Server (call setup/teardown, routing) — `F1` · `Must` · →FR-TEL-001
- [ ] **2.1.3** Managed CPaaS entegrasyonu (Media Streams/WebSocket) — `F1` · `Must` · →FR-TEL-002
- [ ] **2.1.4** SIP trunk / BYOC desteği — `F2` · `Must` · →FR-TEL-002
- [ ] **2.1.5** E.164 normalizasyonu + Caller ID & numara havuzu yönetimi — `F1` · `Must` · →FR-TEL-004/005
- [ ] **2.1.6** DTMF algılama/üretme (RFC 2833 / SIP INFO) — `F1` · `Must` · →FR-TEL-006
- [ ] **2.1.7** Çağrı başlangıç/bitiş neden kodları (standart taksonomi) — `F1` · `Must` · →FR-TEL-012
- [ ] **2.1.8** Çağrı düşmesinde kontrollü retry/geri arama — `F2` · `Should` · →FR-TEL-009
- [ ] **2.1.9** Answering machine detection + voicemail bırakma — `F2` · `Must` · →FR-TEL-010/011

### 2.2 Real-time media gateway
- [ ] **2.2.1** RTP/medya sonlandırma + jitter buffer — `F1` · `Must` · →FR-RTC-001
- [ ] **2.2.2** Codec yönetimi (8kHz), gereksiz resample/transcode önleme — `F1` · `Must` · →FR-RES-008
- [ ] **2.2.3** Edge VAD / endpointing (dinamik) — `F1` · `Must` · →FR-RTC-004/013, ADR-005
- [ ] **2.2.4** Gürültü/echo işleme + agent kendi sesini tekrar transkribe etmeme — `F1` · `Must` · →FR-RTC-005/006
- [ ] **2.2.5** Streaming STT connector (gateway↔orchestrator) — `F1` · `Must` · →FR-STT-002
- [ ] **2.2.6** Streaming TTS connector + ölü hava işlememe (dead air) — `F1` · `Must` · →FR-RES-009
- [ ] **2.2.7** Barge-in olay üretimi + TTS kesme (≤200ms) — `F1` · `Must` · →FR-RTC-002, NFR 10.1
- [ ] **2.2.8** Konuşma hızı/ses seviyesi/bekleme ayarları — `F1` · `Must` · →FR-RTC-008

---

## 3. Conversation Orchestrator (Çekirdek IP)

### 3.1 Çekirdek runtime
- [ ] **3.1.1** Asenkron olay döngüsü + oturum = hafif task modeli (thread-per-call yok) — `F1` · `Must` · →FR-RES-001, ADR-003
- [ ] **3.1.2** Turn state machine (LISTEN→CAPTURE→THINK→ACT→SPEAK) — `F1` · `Must` · →SAD §6.1
- [ ] **3.1.3** Turn-taking + barge-in koordinasyonu — `F1` · `Must` · →FR-RTC-002/003
- [ ] **3.1.4** Per-call kaynak bütçesi (~15MB) izleme + sınırlama — `F1` · `Must` · →FR-RES-016
- [ ] **3.1.5** correlation_id + tenant context propagation (her olay/log/trace) — `F1` · `Must` · →SAD §13.3, §17.1

### 3.2 Session memory & prompt
- [ ] **3.2.1** Kısa süreli diyalog belleği + oturum sonu kalıcılaştırma — `F1` · `Must` · →SAD §6.2
- [ ] **3.2.2** Token sınırına göre konuşma geçmişi özetleme — `F1` · `Must` · →FR-LLM-005, FR-RES-010
- [ ] **3.2.3** Prompt Manager: versiyonlu sabit system prompt enjeksiyonu — `F1` · `Must` · →FR-LLM-006
- [ ] **3.2.4** Single-prompt + node/flow konuşma modelleri çalıştırma — `F1` · `Must` · →FR-AGT-003

### 3.3 Policy engine
- [ ] **3.3.1** Input guard: prompt-injection/jailbreak tespiti — `F1` · `Must` · →FR-LLM-007
- [ ] **3.3.2** Output guard: yanıt politika denetimi (BRD §13 yasak işlemler) — `F1` · `Must` · →FR-LLM-009
- [ ] **3.3.3** "No deceptive impersonation" + AI bildirimi zorlama — `F1` · `Must` · →BRD §5, §14.2
- [ ] **3.3.4** Anti-hallucination kuralları (kaynak yoksa uydurma yok → teyit/aktar/ticket) — `F1` · `Must` · →FR-KB-007
- [ ] **3.3.5** Global + tenant seviyesinde politika uygulama — `F1` · `Must` · →FR-AGT-009
- [ ] **3.3.6** Kontrollü tekrar stratejisi + N anlamama → handoff — `F1` · `Must` · →FR-RTC-010/011

### 3.4 Yerelleştirme / okuma
- [ ] **3.4.1** Sayı/tarih/para/adres/kod yerel okuma normalizasyonu — `F1` · `Must` · →FR-RTC-009
- [ ] **3.4.2** Konuşma sırasında dil değişimi — `F2` · `Should` · →FR-RTC-012

---

## 4. Sağlayıcı Soyutlama Katmanı (Adapters)

### 4.1 SPI ve ortak yetenekler
- [ ] **4.1.1** Adapter SPI tanımı (STT/TTS/LLM/Telephony) — `F1` · `Must` · →SAD §8.1
- [ ] **4.1.2** Ortak: timeout, retry (backoff+jitter), circuit breaker, health check — `F1` · `Must` · →SAD §8.2
- [ ] **4.1.3** Usage metering + cost calculation (her adapter) — `F1` · `Must` · →FR-BIL-002
- [ ] **4.1.4** Region selection + data retention control (adapter düzeyi) — `F2` · `Must` · →NFR 10.7
- [ ] **4.1.5** Provider-specific error normalization (ortak hata taksonomisi) — `F1` · `Must` · →SAD §8.2
- [ ] **4.1.6** Connection pooling + kalıcı oturumlar — `F1` · `Must` · →FR-RES-006

### 4.2 Somut adapter'lar (≥2/kategori)
- [ ] **4.2.1** STT adapter #1 + #2 (partial/final, confidence, phrase boosting) — `F1` · `Must` · →FR-STT-001/004/006
- [ ] **4.2.2** STT alan optimizasyonu (telefon no/plaka/poliçe/referans) — `F1` · `Must` · →FR-STT-005
- [ ] **4.2.3** TTS adapter #1 + #2 (streaming, pronunciation dictionary, cancel) — `F1` · `Must` · →FR-TTS-001/004/005
- [ ] **4.2.4** LLM adapter #1 + #2 (streaming token/tool call) — `F1` · `Must` · →FR-LLM-001/004
- [ ] **4.2.5** Telephony adapter #1 + #2 — `F1`/`F2` · `Must` · →FR-TEL-002
- [ ] **4.2.6** Ses klonlama izin + kullanım kaydı (onaylı sesler) — `F2` · `Should`/`Must` · →FR-TTS-006/007

### 4.3 Fallback ve degradation
- [ ] **4.3.1** STT fallback (hata/timeout → ikincil) — `F1` · `Must` · →FR-STT-008
- [ ] **4.3.2** TTS fallback + ses karakteri tutarlılığı — `F1` · `Must` · →FR-TTS-008/009
- [ ] **4.3.3** LLM fallback (fallback model / deterministic flow) — `F1` · `Must` · →FR-LLM-010
- [ ] **4.3.4** Birincil kesintide kontrollü fallback uçtan uca testi — `F1` · `Must` · →BRD §19 (4)

---

## 5. LLM Orkestrasyonu (Router · Tiering · Cache)

- [ ] **5.1** LLM Router iskeleti (cost/latency/dil/risk girdileri) — `F1` · `Must` · →FR-LLM-003
- [ ] **5.2** Tur sınıflandırıcı (rutin/karmaşık/riskli) — `F2` · `Must` · →FR-LLM-013
- [ ] **5.3** Model tiering (küçük/büyük) + ≥%60 küçük-model tur hedefi — `F2` · `Must` · →FR-RES-005, NFR 10.2
- [ ] **5.4** Semantic cache (embedding; yan-etkisiz turlar; PII cache'lenmez) — `F2` · `Should` · →FR-LLM-014, FR-RES-004
- [ ] **5.5** Tenant/use-case model override — `F2` · `Must` · →FR-LLM-002
- [ ] **5.6** Schema-validated tool çağrısı zorlaması (serbest metin yerine) — `F1` · `Must` · →FR-LLM-008
- [ ] **5.7** Model+versiyon+token kullanımını çağrı bazında kaydet — `F1` · `Must` · →FR-LLM-011
- [ ] **5.8** "Tenant verisi eğitime kapalı" varsayılanı (no-train) — `F1` · `Must` · →FR-LLM-012

---

## 6. Bilgi Tabanı & RAG

### 6.1 İndeksleme (offline)
- [ ] **6.1.1** Ingest connector: PDF/Word/HTML/metin/CSV/web — `F1` · `Must` · →FR-KB-001
- [ ] **6.1.2** SharePoint/Confluence connector — `F2` · `Should` · →FR-KB-002
- [ ] **6.1.3** Parse→chunk→embed→index + versiyonlama — `F1` · `Must` · →FR-KB-003
- [ ] **6.1.4** Doküman bazında erişim yetkisi (metadata) — `F1` · `Must` · →FR-KB-005
- [ ] **6.1.5** Bayatlama/işaretleme (content TTL) — `F2` · `Should` · →FR-KB-008

### 6.2 Retrieval (online)
- [ ] **6.2.1** Vector search (top-k) + opsiyonel rerank — `F1` · `Must` · →SAD §10.2
- [ ] **6.2.2** Token trimming (bağlam maliyeti sınırı) — `F1` · `Must` · →FR-KB-011, FR-RES-010
- [ ] **6.2.3** Kaynak atfı (yanıt hangi kaynağa dayalı) — `F1` · `Must` · →FR-KB-006
- [ ] **6.2.4** Hassas doküman → sağlayıcı loglarına gitmeme — `F1` · `Must` · →FR-KB-010
- [ ] **6.2.5** KB Q&A benchmark veri seti + test — `F2` · `Must` · →FR-KB-009

---

## 7. Tool & Kurumsal Entegrasyon

### 7.1 Tool yürütme hattı
- [ ] **7.1.1** Tool input/output JSON schema doğrulama — `F1` · `Must` · →FR-TOOL-002
- [ ] **7.1.2** Tool authorization (agent scope, read/write seviyesi) — `F1` · `Must` · →FR-TOOL-004/005
- [ ] **7.1.3** Idempotency key (duplicate işlem önleme) — `F1` · `Must` · →FR-TOOL-009
- [ ] **7.1.4** Timeout/retry/circuit breaker (Integration GW) — `F1` · `Must` · →FR-TOOL-003
- [ ] **7.1.5** Hata normalizasyonu (müşteriye teknik detay yok) — `F1` · `Must` · →FR-TOOL-008
- [ ] **7.1.6** correlation_id ile tool izleme + audit — `F1` · `Must` · →FR-TOOL-010

### 7.2 Integration Gateway
- [ ] **7.2.1** REST connector — `F1` · `Must` · →FR-TOOL-001
- [ ] **7.2.2** SOAP/GraphQL/webhook connector'lar — `F2` · `Must` · →FR-TOOL-001
- [ ] **7.2.3** Endpoint allowlist (onaysız endpoint engelleme) — `F1` · `Must` · →FR-TOOL-012
- [ ] **7.2.4** Asenkron uzun-işlem workflow (callback/polling) — `F2` · `Should` · →FR-TOOL-011
- [ ] **7.2.5** CRM/Ticketing/ERP referans entegrasyonu (pilot) — `F1` · `Must` · →BRD §6.1

### 7.3 Deterministic workflow engine
- [ ] **7.3.1** Kritik işlem workflow durum makinesi (auth→kural→özet→teyit→onay→audit) — `F1` · `Must` · →BRD §13
- [ ] **7.3.2** Kritik işlem öncesi müşteri teyidi + ek doğrulama — `F1` · `Must` · →FR-TOOL-006/007

---

## 8. Çağrı İçi Kimlik Doğrulama

- [ ] **8.1** Caller ID zayıf-sinyal eşleştirme (tek başına yetersiz) — `F1` · `Must` · →FR-AUTH-001
- [ ] **8.2** OTP / müşteri no / KBA doğrulama — `F1` · `Must` · →FR-AUTH-002
- [ ] **8.3** Step-up authentication (hassas işlem) — `F1` · `Must` · →FR-AUTH-003
- [ ] **8.4** Başarısız deneme limiti — `F1` · `Must` · →FR-AUTH-004
- [ ] **8.5** Hassas bilgi sesli tam tekrar etmeme — `F1` · `Must` · →FR-AUTH-005
- [ ] **8.6** Ses biyometrisi (opsiyonel ayrı modül, açık onay + politika) — `F3` · `Should` · →FR-AUTH-006/007

---

## 9. İnsan Temsilciye Aktarım (Handoff)

- [ ] **9.1** Cold transfer (SIP REFER) — `F1` · `Must` · →FR-TEL-007
- [ ] **9.2** Warm transfer (köprüleme + whisper brifing) — `F1` · `Must` · →FR-TEL-007, FR-HND-006
- [ ] **9.3** Whisper transfer — `F2` · `Must` · →FR-TEL-007
- [ ] **9.4** Transfer tetikleyiciler (kullanıcı isteği, düşük confidence, öfke, politika) — `F1` · `Must` · →FR-HND-001/002
- [ ] **9.5** Kuyruk/skill/departman bazlı hedef seçimi — `F2` · `Must` · →FR-TEL-008, FR-HND-003
- [ ] **9.6** Bağlam paketi (özet + intent + toplanan alanlar + auth durumu) + screen-pop — `F1` · `Must` · →FR-HND-004/005
- [ ] **9.7** Temsilci yoksa callback/voicemail/ticket — `F1` · `Must` · →FR-HND-007
- [ ] **9.8** Aktarım başarısı + bekleme süresi raporlama — `F2` · `Must` · →FR-HND-008

---

## 10. Outbound & Kampanya & Consent

### 10.1 Kampanya yönetimi
- [ ] **10.1.1** Kampanya oluşturma + müşteri listesi yükleme — `F2` · `Must` · →FR-OUT-001
- [ ] **10.1.2** CRM'den dinamik liste alma — `F2` · `Must` · →FR-OUT-002
- [ ] **10.1.3** Max deneme + yeniden arama aralığı — `F2` · `Must` · →FR-OUT-005
- [ ] **10.1.4** İnsan/voicemail/geçersiz numara ayrımı — `F2` · `Must` · →BRD §8.2
- [ ] **10.1.5** Disposition (otomatik) + voicemail/meşgul/cevapsız kayıt — `F2` · `Must` · →FR-OUT-008/011
- [ ] **10.1.6** Kampanya script/teklif versiyonu çağrı bazında kayıt — `F2` · `Must` · →FR-OUT-009
- [ ] **10.1.7** Kampanya durdurma düğmesi — `F2` · `Must` · →FR-OUT-010
- [ ] **10.1.8** A/B test kampanyaları — `F2` · `Should` · →FR-OUT-012

### 10.2 Consent & uyumluluk motoru
- [ ] **10.2.1** Consent Engine ön-kontrol (amaç/ülke/birey-şirket/kaynak/tarih/kapsam) — `F2` · `Must` · →FR-OUT-003, §14.3
- [ ] **10.2.2** Do-not-call / suppression gerçek zamanlı kontrol — `F2` · `Must` · →FR-TEL-014, FR-OUT-006
- [ ] **10.2.3** Ülke/bölge arama saati kuralları — `F2` · `Must` · →FR-TEL-013, FR-OUT-004
- [ ] **10.2.4** Silent/abandoned call önleme (kapasite kontrolü) — `F2` · `Must` · →FR-TEL-015
- [ ] **10.2.5** İYS/ETK (TR) + PECR/Ofcom (UK) profil parametreleri — `F2` · `Must` · →§14.3
- [ ] **10.2.6** Kampanya kapasitesi ≤ agent+trunk kapasitesi (backpressure entegrasyonu) — `F2` · `Must` · →FR-OUT-007

---

## 11. Kayıt, Transkript & PII Redaction

- [ ] **11.1** Kayıt politikası (tenant/ülke/use-case) + tamamen kapatma — `F1` · `Must` · →FR-REC-001/002
- [ ] **11.2** Tek/çift kanallı kayıt — `F1` · `Must` · →FR-REC-003
- [ ] **11.3** Transkript üretimi + timeline — `F1` · `Must` · →BRD §8.1
- [ ] **11.4** PII redaction pipeline (async) — `F1` · `Must` · →FR-REC-004
- [ ] **11.5** Kart/parola/OTP kayıt+transkriptten çıkarma — `F1` · `Must` · →FR-REC-005
- [ ] **11.6** Kayıt/transkript erişim audit'i — `F1` · `Must` · →FR-REC-009
- [ ] **11.7** Çağrı özeti üretimi — `F1` · `Must` · →BRD §8.1

---

## 12. IAM, RBAC & Panel Backend (AuthZ)

### 12.1 IAM çekirdeği
- [ ] **12.1.1** RBAC modeli (rol→permission-key bundle, immutable) — `F1` · `Must` · →FR-IAM-001, FR-IAM-011
- [ ] **12.1.2** Permission-key kataloğu (`kaynak:eylem`, `*:own`) — `F1` · `Must` · →SAD §14.4.3
- [ ] **12.1.3** Scoped assignment (rol + departman/marka/kampanya filtresi) — `F2` · `Must` · →FR-IAM-011, ADR-012
- [ ] **12.1.4** SSO: SAML 2.0 + OIDC — `F2` · `Must` · →FR-IAM-002
- [ ] **12.1.5** MFA — `F1` · `Must` · →FR-IAM-003
- [ ] **12.1.6** SCIM provisioning + IdP grup→rol eşleme — `F2` · `Should` · →FR-IAM-007, SAD §14.4.4
- [ ] **12.1.7** Maker-checker onay akışı — `F2` · `Should` · →FR-IAM-005
- [ ] **12.1.8** Append-only (WORM) audit log + bütünlük — `F1` · `Must` · →FR-IAM-006

### 12.2 Panel AuthZ enforcement
- [ ] **12.2.1** Backend guard: panel + rol + tenant scope (FastAPI dependency) — `F1` · `Must` · →SAD §14.4.2
- [ ] **12.2.2** L0/L1/L2 ayrı router ağaçları + ayrı OAuth scope — `F1` · `Must` · →SAD §14.4.2
- [ ] **12.2.3** Tenant scope + RLS çift kontrol — `F1` · `Must` · →FR-TEN-002
- [ ] **12.2.4** L0 iş verisi repository bağımsızlığı (tasarımsal izolasyon) — `F1` · `Must` · →FR-IAM-008

### 12.3 Break-glass (üç katmanlı)
- [ ] **12.3.1** Tier A (metrik/log, PII yok) — break-glass'sız L0 + audit — `F1` · `Must` · →FR-IAM-009
- [ ] **12.3.2** Tier B: maker-checker + time-boxed token (60dk default, max 4sa, auto-expiry) — `F2` · `Must` · →FR-IAM-009
- [ ] **12.3.3** Tier B: gerekçe kodu + tenant security_compliance_officer/tenant_owner bildirimi — `F2` · `Must` · →FR-IAM-009
- [ ] **12.3.4** Regüle tenant `require_tenant_approval` toggle + DPA bağı — `F2` · `Must` · →FR-IAM-010
- [ ] **12.3.5** Break-glass tam-audit router (ayrı, kısıtlı) — `F2` · `Must` · →SAD §14.4.2

### 12.4 Tenant & organizasyon yönetimi
- [ ] **12.4.1** Tenant CRUD + provisioning (L0) — `F1` · `Must` · →FR-TEN-001
- [ ] **12.4.2** Dedicated vs shared tenant — `F2` · `Should` · →FR-TEN-005
- [ ] **12.4.3** Org yapısı (marka/departman/ülke/proje) (L1) — `F1` · `Must` · →FR-TEN-003
- [ ] **12.4.4** Tenant dil/saat dilimi/bölge/saklama tercihi (L1) — `F1` · `Must` · →FR-TEN-004

---

## 13. Frontend Panelleri (L0 / L1 / L2)

### 13.1 Ortak frontend altyapısı
- [ ] **13.1.1** İki ayrı Next.js app: `platform-app` (L0, internal-only) + `tenant-app` (L1+L2) — `F1` · `Must` · →ADR-011
- [ ] **13.1.2** Route group + middleware (oturum + tenant scope + panel ayrımı) — `F1` · `Must` · →SAD §14.4.1
- [ ] **13.1.3** Tasarım sistemi / komponent kütüphanesi + i18n (TR/EN) — `F1` · `Must`
- [ ] **13.1.4** PII redaction/maskeleme panel görüntülemede — `F1` · `Must` · →BRD §17.7

### 13.2 L0 — Platform Admin Console (P-01..P-09)
- [ ] **13.2.1** P-01 Platform Genel Bakış — `F2` · `Must`
- [ ] **13.2.2** P-02 Tenant Yönetimi & Provisioning — `F2` · `Must`
- [ ] **13.2.3** P-03 Kaynak & Kapasite Yönetimi — `F2` · `Must` · →Resource Manager
- [ ] **13.2.4** P-04 Sağlayıcı & Entegrasyon Sağlığı — `F2` · `Must`
- [ ] **13.2.5** P-05 Platform Faturalandırma & Rate-Card — `F2` · `Must`
- [ ] **13.2.6** P-06 Global Politika & Guardrails — `F2` · `Must`
- [ ] **13.2.7** P-07 Platform Audit & Güvenlik — `F2` · `Must`
- [ ] **13.2.8** P-08 Sürüm & Dağıtım (Release) Yönetimi — `F2` · `Should`
- [ ] **13.2.9** P-09 Alarm & Incident (SRE) — `F2` · `Must`

### 13.3 L1 — Tenant Admin Console (T-01..T-09)
- [ ] **13.3.1** T-01 Tenant Dashboard — `F2` · `Must`
- [ ] **13.3.2** T-02 Organizasyon & Yapı — `F2` · `Must`
- [ ] **13.3.3** T-03 Kullanıcı & Rol Yönetimi (RBAC/SSO/SCIM) — `F2` · `Must`
- [ ] **13.3.4** T-04 Telefon Numarası & SIP/Trunk — `F2` · `Must`
- [ ] **13.3.5** T-05 Entegrasyon, Tool & API Key/Webhook — `F2` · `Must`
- [ ] **13.3.6** T-06 Compliance & Retention — `F2` · `Must`
- [ ] **13.3.7** T-07 Faturalandırma & Kullanım — `F2` · `Must`
- [ ] **13.3.8** T-08 Audit Log (tenant) — `F2` · `Must`
- [ ] **13.3.9** T-09 Kaynak Kotası Görünümü — `F2` · `Must`

### 13.4 L2 — Operasyon / Uygulama Paneli (A-01..A-17)
- [ ] **13.4.1** A-01 Operasyon Dashboard — `F1` · `Must`
- [ ] **13.4.2** A-02 Canlı Çağrılar — `F1` · `Must` · →FR-ANA-012
- [ ] **13.4.3** A-03 Agent Listesi — `F1` · `Must`
- [ ] **13.4.4** A-04 Agent Builder (kod yazmadan) — `F1` · `Must` · →FR-AGT-001
- [ ] **13.4.5** A-05 Conversation Flow Editor — `F1` · `Must` · →FR-AGT-003
- [ ] **13.4.6** A-06 Prompt Editor (versiyonlama) — `F1` · `Must` · →FR-AGT-004
- [ ] **13.4.7** A-07 Voice & Model Ayarları (tiering) — `F1` · `Must` · →FR-AGT-002
- [ ] **13.4.8** A-08 Knowledge Base — `F1` · `Must`
- [ ] **13.4.9** A-09 Tool/API Bağlama — `F1` · `Must`
- [ ] **13.4.10** A-10 Outbound Kampanya Yönetimi — `F2` · `Must`
- [ ] **13.4.11** A-11 Çağrı Kayıtları — `F1` · `Must`
- [ ] **13.4.12** A-12 Çağrı Detayı / Transkript & Timeline — `F1` · `Must`
- [ ] **13.4.13** A-13 QA Değerlendirme — `F2` · `Must`
- [ ] **13.4.14** A-14 Analytics & Raporlama — `F1`/`F2` · `Must`
- [ ] **13.4.15** A-15 Maliyet & Kaynak Tüketimi — `F2` · `Must` · →FR-ANA-013
- [ ] **13.4.16** A-16 Test & Simulation Centre — `F1` · `Must`
- [ ] **13.4.17** A-17 Sürüm Geçmişi (agent) + rollback — `F1` · `Must` · →FR-AGT-006

---

## 14. Analitik, QA & Gözlemlenebilirlik

### 14.1 Gözlemlenebilirlik
- [ ] **14.1.1** Çağrı trace span'leri (BRD §15 tüm zaman damgaları) — `F1` · `Must` · →SAD §17.1
- [ ] **14.1.2** Teknik metrikler (packet loss/jitter/STT-LLM-TTS latency/token/...) — `F1` · `Must` · →BRD §15
- [ ] **14.1.3** Per-call CPU/bellek/eşzamanlılık ölçümü — `F1` · `Must` · →FR-ANA-013
- [ ] **14.1.4** Yapılandırılmış asenkron + örneklemeli loglama — `F1` · `Should` · →FR-RES-012
- [ ] **14.1.5** Alarm kuralları (BRD §15) + ≤2dk üretim — `F1` · `Must` · →NFR 10.1
- [ ] **14.1.6** Gerçek zamanlı operasyon ekranı (≤60sn gecikme) — `F1` · `Must` · →FR-ANA-012

### 14.2 Analitik & kalite
- [ ] **14.2.1** Otomatik kalite değerlendirme (tüm çağrılar) — `F2` · `Must` · →FR-ANA-001
- [ ] **14.2.2** Intent/outcome/disposition/completion çıkarımı — `F1`/`F2` · `Must` · →FR-ANA-002
- [ ] **14.2.3** Containment/transfer oranı raporu — `F1` · `Must` · →FR-ANA-003
- [ ] **14.2.4** Yanlış bilgi/tool hatası/güvenlik ihlali tespiti — `F2` · `Must` · →FR-ANA-004
- [ ] **14.2.5** Kritik konuşma otomatik işaretleme — `F2` · `Must` · →FR-ANA-008
- [ ] **14.2.6** QA manuel skor + açıklama — `F2` · `Must` · →FR-ANA-009
- [ ] **14.2.7** Agent sürümleri performans karşılaştırma — `F2` · `Must` · →FR-ANA-010
- [ ] **14.2.8** Dashboard + ham veri export — `F2` · `Must` · →FR-ANA-011
- [ ] **14.2.9** Maliyet raporu (çağrı/agent/tenant/sağlayıcı) — `F2` · `Must` · →FR-ANA-007

---

## 15. Faturalama & Kullanım

- [ ] **15.1** Dakika/saniye bazlı kullanım ölçümü — `F2` · `Must` · →FR-BIL-001
- [ ] **15.2** Telekom/STT/TTS/LLM/platform maliyeti ayrı izleme — `F2` · `Must` · →FR-BIL-002
- [ ] **15.3** Tenant fiyat planı tanımı — `F2` · `Must` · →FR-BIL-003
- [ ] **15.4** Minimum ücret/kota/overage — `F2` · `Must` · →FR-BIL-004
- [ ] **15.5** Kullanım limiti + bütçe alarmı — `F2` · `Must` · →FR-BIL-006
- [ ] **15.6** Dedicated altyapı maliyeti ayrı faturalandırma — `F3` · `Should` · →FR-BIL-005
- [ ] **15.7** Fatura verisi finans sistemine aktarım — `F2` · `Must` · →FR-BIL-007

---

## 16. Kaynak Verimliliği & Resource Manager

- [ ] **16.1** TTS cache (statik anonslar, hit ≥%80) — `F1` · `Must` · →FR-RES-003
- [ ] **16.2** Quota Service (tenant concurrency/CPS/vCPU/bellek) — `F1`/`F2` · `Must` · →FR-TEN-006/007
- [ ] **16.3** Autoscaler + warm pool (cold-start azaltma) — `F2` · `Must` · →FR-RES-013, NFR 10.3
- [ ] **16.4** Scale-to-zero (boşta tenant/worker) — `F2` · `Must` · →FR-RES-007
- [ ] **16.5** Backpressure / admission control (graceful degradation) — `F1`/`F2` · `Must` · →FR-RES-014
- [ ] **16.6** Cost/Resource Meter → Analytics & Billing — `F2` · `Must` · →SAD §15.2
- [ ] **16.7** Non-RT işleri batch/async (analitik/redaction/raporlama) — `F1` · `Must` · →FR-RES-011
- [ ] **16.8** Noisy-neighbor önleme (fair scheduling) — `F2` · `Must` · →NFR 10.3
- [ ] **16.9** GPU yalnız self-hosted gerekince (aksi CPU/serverless) — `F3` · `Should` · →FR-RES-015, ADR-010

---

## 17. Güvenlik & Uyumluluk

### 17.1 Güvenlik
- [ ] **17.1.1** TLS her yerde + SRTP medya — `F1` · `Must` · →NFR 10.6
- [ ] **17.1.2** Depolama AES-256 + tenant başına KMS key — `F1` · `Must` · →NFR 10.6
- [ ] **17.1.3** BYOK / customer-managed keys — `F3` · `Should` · →NFR 10.6
- [ ] **17.1.4** WAF/DDoS + rate limiting + IP allowlist + private endpoint — `F1` · `Must` · →NFR 10.6
- [ ] **17.1.5** SAST/DAST/dependency scan/SBOM (CI'da zorunlu) — `F0`/`F1` · `Must` · →NFR 10.6
- [ ] **17.1.6** PAM + incident response prosedürü — `F2` · `Must` · →NFR 10.6
- [ ] **17.1.7** Düzenli penetration test (kritik bulgu yok kapısı) — `F1` · `Must` · →BRD §19 (20)

### 17.2 Uyumluluk
- [ ] **17.2.1** Veri sahibi hakları (erişim/düzeltme/silme) akışları — `F2` · `Must` · →§14.1
- [ ] **17.2.2** DPA + alt-işleyen listesi + sağlayıcıya gönderilen veri kaydı — `F2` · `Must` · →§14.1
- [ ] **17.2.3** AI şeffaflık bildirimi (yapılandırılabilir; EU AI Act 02.08.2026) — `F1` · `Must` · →§14.2
- [ ] **17.2.4** Country compliance profiles (TR/UK/EU/ME) parametre motoru — `F2` · `Must` · →§14.4
- [ ] **17.2.5** Sektörel profiller: PCI/FCA/HIPAA/NHS/SOC2/ISO27001-27701/DORA/NIS2 — `F3` · `Must` · →§14.4
- [ ] **17.2.6** PCI ödeme akışı (kart verisi LLM/transkript/kayıt dışı; DTMF masking/aktarım) — `F3` · `Must` · →BRD §8.5

---

## 18. Test, Simülasyon & NFR Doğrulama

- [ ] **18.1** Tarayıcı üzerinden agent testi (telefon olmadan) — `F1` · `Must` · →FR-TST-001
- [ ] **18.2** Persona/senaryo simülasyonu (happy/edge/adversarial) — `F1` · `Must` · →FR-TST-002/003
- [ ] **18.3** Sentetik test verisi üretimi (gerçek müşteri verisi yok) — `F1` · `Must` · →FR-TST-008
- [ ] **18.4** Prompt değişiminde otomatik regression + yayın engelleme — `F1` · `Must` · →FR-TST-004/005, FR-AGT-010
- [ ] **18.5** Yük + eş zamanlı çağrı testi (tasarım kapasitesi) — `F1`/`F2` · `Must` · →FR-TST-006
- [ ] **18.6** Yük altında per-call kaynak ölçümü + regresyon raporu — `F1` · `Must` · →FR-TST-009
- [ ] **18.7** Gürültü/aksan/kesinti/düşük hat kalitesi test seti — `F2` · `Should` · →FR-TST-007
- [ ] **18.8** Prompt injection / veri sızıntısı güvenlik testi — `F1` · `Must` · →BRD §19 (8)
- [ ] **18.9** Tenant izolasyon testi (cross-tenant erişim yok) — `F1` · `Must` · →BRD §19 (9)
- [ ] **18.10** Gecikme P95 hedef doğrulama — `F1` · `Must` · →BRD §19 (10), NFR 10.1
- [ ] **18.11** PII redaction testleri — `F1` · `Must` · →BRD §19 (13)
- [ ] **18.12** Outbound consent/opt-out doğrulama testi — `F2` · `Must` · →BRD §19 (14)

---

## 19. HA/DR & Çoklu Bölge

- [ ] **19.1** Multi-AZ (tüm stateful servisler) — `F1` · `Must` · →NFR 10.5
- [ ] **19.2** Active-passive bölgesel DR + yeni çağrı failover — `F2` · `Must` · →NFR 10.5
- [ ] **19.3** RTO doğrulama (voice ≤15dk, yönetim ≤4sa) — `F2` · `Must` · →NFR 10.5
- [ ] **19.4** DR tatbikatı (yılda ≥2) süreci — `F2` · `Must` · →NFR 10.5
- [ ] **19.5** Active-active multi-region (10.000+) — `F3` · `Must` · →NFR 10.3, BRD §20
- [ ] **19.6** Uptime SLA izleme (voice/telephony/API %99,99) — `F2` · `Must` · →NFR 10.4

---

## 20. Dağıtım, Sürümleme & Operasyon

- [ ] **20.1** Agent yaşam döngüsü: draft/test/staging/production + rollback — `F1` · `Must` · →FR-AGT-005/006
- [ ] **20.2** Agent varyasyonları (segment bazlı) — `F2` · `Should` · →FR-AGT-008
- [ ] **20.3** Feature flag + kademeli yayma (release) — `F2` · `Should` · →P-08
- [ ] **20.4** On-premise / hybrid dağıtım paketi — `F3` · `Could` · →BRD §20
- [ ] **20.5** Marketplace & partner ekosistemi — `F3` · `Could` · →BRD §20
- [ ] **20.6** Runbook'lar + on-call + incident yönetimi (P-09) — `F2` · `Must` · →BRD §15

---

## Ek A — Faz 1 kabul kapısı (BRD §19 inbound altküme)
- [ ] ≥2 STT, ≥2 TTS, ≥2 LLM sağlayıcı + fallback (→4.2/4.3)
- [ ] Inbound çağrı uçtan uca tamamlanır (→2/3)
- [ ] Warm + cold transfer çalışır (→9)
- [ ] Agent CRM'den okur, kontrollü işlem yapar (→7)
- [ ] Prompt injection veri sızdırmaz (→18.8)
- [ ] Tenant izolasyonu doğrulanır (→18.9)
- [ ] P95 gecikme hedefte (→18.10)
- [ ] PII redaction geçer (→18.11)
- [ ] Agent rollback (→20.1)
- [ ] Kritik işlemler audit'te (→12.1.8)
- [ ] Yük altında per-call kaynak bütçede + density hedefi (→18.6, 0.3.3)
- [ ] Pentest kritik bulgu yok (→17.1.7)

## Ek B — Bağımlılık notları (kritik sıra)
1. `0.x` (Foundation + PoC + ADR-009) → her şeyin önkoşulu.
2. `1.1` (şema) → `3` (orchestrator) ve `12` (IAM) önkoşulu.
3. `4` (adapters) → `3`, `5`, `6` için gerekli.
4. `2` (media) + `3` (orchestrator) + `4` (adapters) → ilk uçtan uca akış (F1 çekirdek).
5. `12.2/12.3` (panel AuthZ + break-glass) → `13` (frontend panelleri) önkoşulu.
6. `16` (Resource Manager) → `10.2.6` (outbound kapasite) ve F2 density hedefleri.
7. `10` (outbound) F2; `17.2.5/17.2.6` (PCI/sektörel) F3.

## Ek C — Bakım
- Her görev için PR'da WBS ID referansı verilir.
- Faz kapısı geçişinde bu dosya + izlenebilirlik matrisi (0.1.2) gözden geçirilir.
- Yeni gereksinim → önce BRD/SAD güncellenir, sonra buraya görev eklenir (FR-ID şeması korunur).
