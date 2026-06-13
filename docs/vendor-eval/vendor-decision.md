# Vendor Karar Raporu — `docs/vendor-eval/vendor-decision.md`

**WBS:** 0.2.6 · **Faz:** F0 · **Öncelik:** Must · **İz:** →SAD §8.1/§8.2/§8.4 (adapter SPI + ≥2 sağlayıcı + önerilen ilk sağlayıcılar); ADR-002 (provider adapter SPI + kategori başına ≥2 sağlayıcı); BRD §14.1 (DPA + alt-işleyen listesi + sağlayıcıya gönderilen veri kaydı); BRD §19 (kabul kriteri 1–4: ≥2/kategori + fallback); NFR 10.7 (residency); FR-LLM-012 / FR-KB-010 (no-train/no-log)
**Tarih:** 2026-06-13 · **Durum:** ✅ Çerçeve + provizyonel öneri tamam (bağlayıcı ticari seçim 0.3.x canlı PoC ölçümü + DPA imzasına bağlı)

> **Bu doküman sağlayıcı seçmez (ADR-002).** 0.2.1–0.2.5 evallerinin **kapı sonuçlarını birleştirir**,
> teknik evallerin kapsamadığı **ticari / uyumluluk / risk** boyutlarını ekler ve kategori başına
> **karar kaydı** üretir. Sayısal kapı girdileri bugün **illüstratif sample**'lardan gelir; bağlayıcı
> seçim **0.3.x PoC** canlı ölçümü (gerçek credential, gerçek bölge) + **DPA/alt-işleyen** hukuki
> imzasıyla netleşir. Çerçeve, hangi adayın geçtiğini değil **nasıl karar verildiğini** sabitler.

---

## 1. Amaç ve kapsam

0.2.x vendor-değerlendirme iş paketinin **kapanış / sentez** adımı. Üç çıktı:

1. **Karar çerçevesi** — kategori başına teknik kapı (0.2.x) + ticari + uyumluluk + risk boyutlarının
   ağırlıklı/knock-out birleştirme modeli.
2. **ADR-002 portföy kapısı** — her kategoride **≥2 aday** tüm knock-out kapılarını geçer + **fallback**
   ilişkisi tanımlıdır (BRD §19 kabul kriteri 1–4). Bu, program seviyesinde tek "yeşil ışık" kapısıdır.
3. **Karar kayıtları** — SAD §8.4'teki "önerilen ilk sağlayıcı" hipotezlerinin eval rubrikleriyle
   doğrulanıp/ayarlanmış hali; bağlayıcı seçim **provizyonel** (PoC + DPA'ya bağlı).

Sözleşme/DPA/alt-işleyen tarafı ayrı belgede: [`contract-dpa-checklist.md`](contract-dpa-checklist.md)
(BRD §14.1, WBS 17.2.2). Birleştirme/raporlama hattı: [`vendor_decision_probe.py`](vendor_decision_probe.py).

## 2. Başlangıç durumu (analiz)

- **SAD §8.4** kategori başına bir "ilk öneri" + "ikincil/fallback" verir, açıkça **"vendor eval'a tabi
  (ADR-002)"** notuyla. 0.2.6 bu tabloyu **bağlamaz**; eval kapılarıyla doğrular ve karar kaydına çevirir.
- **0.2.1–0.2.5** her biri: stdlib-only `score`/`compare`/`selftest` harness + knock-out kapıları +
  `{provider, verdict (YEŞİL/SARI/KIRMIZI), pass, gates, iz}` ortak JSON sözleşmesi + "nihai seçim →
  0.2.6" ertelemesi üretti. 0.2.6'nın işi bu beş JSON akışını **tek karar matrisine** toplamak.
- **Teknik evaller şunu kapsamaz:** birim maliyet, sözleşmesel residency/no-train garantisi, DPA
  imzalanabilirliği + alt-işleyen listeleme, SLA/uptime taahhüdü, vendor lock-in, fallback ikizinin
  varlığı. 0.2.6 bu boşlukları **D2–D5 boyutlarıyla** doldurur.
- Repoda birleştirici karar dokümanı/harness **yoktu**; eklenen budur.

## 3. Karar boyutları (per kategori)

| Boyut | Ad | Kaynak | Tip | Knock-out? |
|------|-----|--------|-----|-----------|
| **D1** | Teknik kapı (eval verdict roll-up) | 0.2.1–0.2.5 `score`/`stats` çıktısı | YEŞİL/SARI/KIRMIZI | Evet — KIRMIZI eler |
| **D2** | Birim maliyet | rate-card (dk / 1k karakter / 1k token), tier, cache etkisi | ₺/birim | Hayır (ağırlıklı) |
| **D3** | Residency & no-train/no-log | NFR 10.7, FR-LLM-012, FR-KB-010; adapter region selection | uygun/uygunsuz | **Evet** — uygunsuz eler |
| **D4** | DPA & alt-işleyen uygunluğu | BRD §14.1; DPA imza + Ek-A listeleme + breach SLA + audit hakkı | uygun/uygunsuz | **Evet** — uygunsuz eler |
| **D5** | Operasyonel olgunluk & risk | SLA/uptime, bölge kapsama, lock-in, fallback ikizi | düşük/orta/yüksek risk | Hayır (ağırlıklı) |

**Birleştirme kuralı (most-restrictive-wins):**
1. **Knock-out önce:** D1=KIRMIZI **veya** D3=uygunsuz **veya** D4=uygunsuz → aday **elenir** (D2/D5 telafi etmez).
   Bu, 0.2.x'teki "en-kötü-X kapısı genel ortalamayı maskeleyemez" disiplininin program seviyesine taşınmasıdır.
2. **Knock-out'u geçenler arasında** ağırlıklı sıralama: D1 %40 · D2 %25 · D5 %20 · (D3/D4 zaten geçildi, +%15 "yeşil" bonusu: tüm bölgeler kapsanıyor + sözleşmesel garanti net).
3. **Portföy kapısı:** kategoride sıralama sonrası **≥2 aday** knock-out'ları geçmiş olmalı; geçen en iyi = **birincil**, ikinci = **fallback** (FR-STT-008/FR-TTS-008/FR-LLM-010/FR-TEL-002 fallback ikizi).

> **Neden D3/D4 knock-out?** B2B2B'de controller=tenant, processor=RMC, sağlayıcı=alt-işleyen (DPIA §2).
> Residency veya no-train sözleşmesel olarak garanti edilemeyen ya da DPA'ya alt-işleyen olarak
> bağlanamayan bir sağlayıcı, gecikme/maliyet ne kadar iyi olursa olsun **kullanılamaz** — uyumluluk
> hard-constraint'tir, optimizasyon değil.

## 4. Teknik kapı (D1) roll-up — kategori ↔ 0.2.x eval

| Kategori | Eval (WBS) | Harness | Knock-out kapıları (özet) | ≥2 aday geçti mi? |
|---|---|---|---|---|
| Telekom | 0.2.1 | `media_latency_probe.py stats` | tek-yön P95 ≤100ms (yeşil ≤50) | İllüstratif: M1/M2 geçer |
| STT | 0.2.2 | `stt_eval_probe.py score` | final P95 ≤200ms · WER ≤0.15 (en-kötü-dil EN+TR) · yapısal CER ≤0.05 | İllüstratif: A geçer, B/C eler |
| TTS | 0.2.3 | `tts_eval_probe.py score` | first-byte P95 ≤200ms · barge-in P95 ≤200ms · MOS ≥4.0 (en-kötü-dil) · underrun=0 | İllüstratif: A geçer, B/C eler |
| LLM | 0.2.4 | `llm_eval_probe.py score` | TTFT genel P95 ≤400 / küçük-tier ≤200ms · kalite ≥0.85 (en-kötü-dil) · no-train + bölgesel + stall=0 | İllüstratif: A geçer, B/C eler |
| Vector DB | 0.2.5 | `vector_db_eval_probe.py score` | recall@k ≥0.95 (en-kötü sınıf) · retrieval P95 ≤200ms · cross-tenant+ACL sızıntı=0 · residency+no-log | İllüstratif: pgvector + OpenSearch geçer |

D1 verdict, ilgili probe'un `verdict` (veya telekomda `gate.verdict`) alanından **otomatik** alınır;
`vendor_decision_probe.py rollup` bu JSON'ları birleştirir ve portföy kapısını uygular (§7).

## 5. Karar kayıtları (provizyonel — SAD §8.4 hipotezi + eval doğrulaması)

> Aşağıdaki "birincil / fallback" sütunları SAD §8.4'ün **başlangıç hipotezidir** ve burada
> **bağlanmaz**. Eval kapıları (D1) illüstratif sample'larda doğrulandı; D2–D5 ve bağlayıcı seçim
> 0.3.x PoC + DPA imzasına ertelendi (`KARAR: BEKLEMEDE` placeholder). Gerçek sağlayıcı adı yazılması
> CLAUDE.md vendor-neutral kısıtı gereği **0.3.x'e bırakılmıştır**.

| Kategori | SAD §8.4 birincil hipotezi | SAD §8.4 fallback hipotezi | D1 (illüstratif) | D3 residency | D4 DPA/alt-işleyen | Karar |
|---|---|---|---|---|---|---|
| Telekom | managed CPaaS (Media Streams) | ikinci CPaaS / SIP trunk (BYOC) | 🟢/🟡 ≥2 geçer | bölge pinning gerekli | DPA + Ek-A | **BEKLEMEDE** (PoC+DPA) |
| STT | düşük-gecikme streaming sağlayıcı | bulut STT #2 (Google/Azure sınıfı) | 🟡 A geçer | no-log + bölge | DPA + Ek-A | **BEKLEMEDE** |
| TTS | kalite veya gecikme öncelikli sağlayıcı | bulut TTS #2 | 🟡 A geçer | no-log + bölge | DPA + Ek-A | **BEKLEMEDE** |
| LLM (büyük) | bölgesel + no-train endpoint sağlayıcı | ikinci sağlayıcı (bölgesel endpoint) | 🟡 A geçer | **bölgesel zorunlu** | DPA + Ek-A | **BEKLEMEDE** |
| LLM (küçük/hızlı) | küçük/hızlı tier | self-hosted (Faz 3, ADR-010) | küçük-tier ≤200ms | bölgesel | DPA + Ek-A | **BEKLEMEDE** |
| Vector DB | PostgreSQL + pgvector (co-located) | OpenSearch | 🟡 ikisi de geçer | pgvector yapısal avantaj | pgvector: alt-işleyen yok (self-host) | **BEKLEMEDE** (pgvector eğilimli) |

**Yapısal not (Vector DB):** pgvector home-region Postgres'inde co-located → **dış alt-işleyen
gerekmez**, residency/no-log yapısal (D3/D4 yapısal yeşil). Managed dış vektör DB → alt-işleyen +
DPA + residency sözleşmesel risk. Bu, SAD §8.4 sıralamasıyla (pgvector birincil) tutarlı; yine de
0.2.5 disiplini gereği OpenSearch meşru fallback olarak korunur.

## 6. ADR-002 portföy kapısı (program seviyesi yeşil ışık)

Faz 1'e (F1 core voice runtime) geçiş için **her medya-hot-path kategorisinde** (telekom/STT/TTS/LLM)
aşağıdaki koşul gereklidir (BRD §19 kabul kriteri 1–4):

```
KATEGORİ_GEÇTİ(k)  ⇔  |{ aday a ∈ k : D1(a)≠KIRMIZI ∧ D3(a)=uygun ∧ D4(a)=uygun }| ≥ 2
                       ∧  birincil ile fallback farklı sağlayıcı (tek nokta arıza yok)
PORTFÖY_YEŞİL      ⇔  ∀ k ∈ {telekom, stt, tts, llm} : KATEGORİ_GEÇTİ(k)
```

Vector DB hot-path değildir (Should); portföy kapısına dahil değil ama ≥2 aday disiplini korunur
(pgvector + OpenSearch). `vendor_decision_probe.py rollup` bu kapıyı makine-okunur uygular →
çıkış kodu (CI/0.4.4 gate).

## 7. Birleştirme hattı — `vendor_decision_probe.py`

stdlib-only; 0.2.x probe'larının `score`/`stats` JSON çıktısını **girdi** alır (yeniden ölçmez):

```bash
# 1) Self-test (credential'sız): kategori çıkarımı, verdict normalizasyonu, portföy kapısı
python3 docs/vendor-eval/vendor_decision_probe.py selftest

# 2) Tüm kategori score JSON'larını birleştir → karar matrisi + ADR-002 portföy kapısı
python3 docs/vendor-eval/vendor_decision_probe.py rollup /tmp/tel-*.json /tmp/stt-*.json \
    /tmp/tts-*.json /tmp/llm-*.json /tmp/vdb-*.json --out /tmp/decision-matrix.md

# 3) Alt-işleyen kayıt iskeleti (DPA Ek-A) üret — girdilerdeki config bayraklarından
python3 docs/vendor-eval/vendor_decision_probe.py register /tmp/*.json --out /tmp/subprocessors.md
```

- `rollup`: dosya adı önekinden (tel/media, stt, tts, llm, vdb) **veya** JSON içindeki `category`
  alanından kategori çıkarır; verdict/pass'ı top-level ya da `gate.*` alanından **normalize** eder;
  kategori başına geçen aday sayar; **portföy kapısını** uygular. Çıkış kodu: yeşil `0`, eksik `1`.
- `register`: her adayın `config`'inden residency/region/no-log/no-train bayraklarını yansıtarak
  **alt-işleyen kayıt iskeleti** (DPA Ek-A; bkz [`contract-dpa-checklist.md`](contract-dpa-checklist.md))
  üretir. **Sağlayıcı seçmez**; yalnız sunulan girdiyi tabloya döker.
- **Sır/credential yazılmaz**; gerçek bağlantı yalnız 0.2.x probe'larında `--url`/ortam değişkeniyle.

## 8. Bulgular (sağlayıcı-nötr — bağlayıcı seçim PoC+DPA'da)

- **Çerçeve kurudur, seçim değil:** 0.2.6 *nasıl* karar verileceğini sabitler (knock-out → ağırlıklı →
  portföy kapısı). Bağlayıcı sağlayıcı seçimi illüstratif sample üzerinde **yapılamaz**; 0.3.x canlı
  ölçüm + DPA imzasına bağlıdır. Bu, "vendor-neutral" kısıtını ihlal etmeden görevi tamamlar.
- **Uyumluluk hard-constraint'tir:** D3 (residency/no-train) ve D4 (DPA/alt-işleyen) knock-out — bir
  sağlayıcı gecikme/maliyette ne kadar iyi olursa olsun, bölgesel endpoint/no-train sözleşmesel garanti
  veremiyor ya da alt-işleyen olarak DPA'ya bağlanamıyorsa **kullanılamaz**.
- **Her kategoride ≥2 + fallback** zorunlu (ADR-002 / BRD §19); portföy kapısı tek noktada başarısızlığı
  (aynı sağlayıcı hem birincil hem fallback) reddeder.
- **pgvector yapısal avantajlı** (co-located → alt-işleyen yok, residency/no-log yapısal); managed dış
  DB sözleşmesel risk taşır. OpenSearch meşru fallback.

## 9. Açık konular / sonraki adım

- **0.3.x PoC:** illüstratif sample'ları gerçek credential + gerçek bölge ölçümüyle değiştir; `rollup`'a
  besle; D2 (gerçek rate-card) + D5 (SLA/uptime) doldur; karar kayıtlarındaki `BEKLEMEDE`'yi karara çevir.
- **DPA/alt-işleyen (17.2.2):** [`contract-dpa-checklist.md`](contract-dpa-checklist.md) şablonunu seçilen
  sağlayıcılarla doldur; counsel doğrulaması (DPIA §12); Ek-A alt-işleyen listesi tenant'a yayımla.
- `rollup` portföy kapısını **0.4.4 CI**'a bağla (sağlayıcı/sürüm değişiminde regresyon kapısı).
- SAD §8.4 güncellemesi: bağlayıcı seçim sonrası tabloya "seçildi/eval tarihi" sütunu (ayrı PR, kanıtla).

## 10. İzlenebilirlik

| Karar boyutu / kapı | Kaynak |
|---|---|
| ≥2 sağlayıcı/kategori + fallback | ADR-002; BRD §19 (1–4); SAD §8.1/§8.2; FR-STT-008/FR-TTS-008/FR-LLM-010/FR-TEL-002 |
| Önerilen ilk sağlayıcı hipotezi | SAD §8.4 |
| D3 residency / no-train | NFR 10.7; FR-LLM-012; FR-KB-010; SAD §12.3/§19; `cp.residency.*` (DPIA §5.4) |
| D4 DPA / alt-işleyen | BRD §14.1; DPIA §2 (controller/processor/sub-processor); `cp.legal.dpa_required` |
| Teknik kapı (D1) per kategori | 0.2.1 (SAD §20) / 0.2.2 (FR-STT-*) / 0.2.3 (FR-TTS-*) / 0.2.4 (FR-LLM-*) / 0.2.5 (FR-KB-*) |
