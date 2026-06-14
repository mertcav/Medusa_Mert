# Per-call Kaynak Bütçesi (~15MB) — İzleme + Sınırlama — `resource-budget`

> **WBS 3.1.4** · `F1` · `Must` · →FR-RES-016 · SAD §6.3/§13/§15.2/§21 · NFR 10.2
> Kaynak doğruluk: `docs/BRD.md` (§10.2 ≤~15MB, §15), `docs/SAD.md` (§13/§15.2/§21),
> `docs/adr/0003-*.md` (lean runtime). Çelişkide dokümanlar esastır.

## 1. Amaç ve kapsam

FR-RES-016: *"Çağrı başına kaynak bütçesi (bellek/CPU) tanımlanmalı ve **aşımı izlenmelidir**."*
Bu görev, Conversation Orchestrator oturum aktöründe (SAD §6.3) çalışan **Resource Budget Guard**'ı +
Resource Manager **Cost/Resource Meter** (SAD §15.2) sözleşmesini tanımlar: her **canlı** çağrının
ayak izini ömrü boyunca **izler** (monitoring) ve aşımda **kontrollü sınırlama** (limiting) uygular —
çökme yerine graceful (FR-RES-014).

**0.3.3 ile ilişki (kritik ayrım):**

| | 0.3.3 density-measurement | **3.1.4 (bu)** per-call kaynak bütçesi |
|---|---|---|
| Ne | **Offline** Monte-Carlo ölçüm | **Runtime** oturum-başı izleme + sınırlama |
| Soru | Bütçe **ulaşılabilir mi?** (fleet ≥250–500 density) | Canlı çağrı bütçeyi **aşarsa ne olur?** |
| Düzlem | Tasarım-zamanı kapasite kanıtı | Çalışma-zamanı enforcement mekanizması |
| Çıktı | density kapısı (NFR 10.2) | bant/azaltma/shed + aşım metriği (FR-RES-016) |

0.3.3 bütçenin **ulaşılabilir** olduğunu kanıtladı; 3.1.4 onu **canlıda zorlar**: 0.3.3'ün bileşen
kompozisyonu (`session_state + dialogue_memory + prompt_context + rag_context + adapter_state +
runtime_overhead`) burada **birebir** kullanılır.

**Kapsam (3.1.4):** oturum-başı runtime izleme + sınırlama sözleşmesi + deterministik Guard simülatörü.
**Kapsam dışı (komşu seam):** density'nin offline ölçümü + fleet kapasite → **0.3.3**; worker düzeyi
backpressure/admission **yeni-çağrı** reddi → **FR-RES-014** (Resource Manager, sistem düzeyi 0.4.8
load-test); özetleme **motoru** implementasyonu → **3.2.x**; native async runtime → SAD §6.3 + F1 kod.

## 2. Bütçe metriği (FR-RES-016 / NFR 10.2 — yetkili)

**oturum-başı orkestratör belleği (medya HARİÇ)** ≤ **~15 MB** + **çağrı-başı CPU** ≤ `cpu_budget_mcore`.

```
footprint = session_state + dialogue_memory + prompt_context + rag_context + adapter_state + runtime_overhead
```

**Medya tamponları (jitter buffer/RTP/ses frame) DAHİL DEĞİLDİR** — SAD §6/§13: *"büyük tamponlar
Media Gateway'de"*. 15 MB bütçesi yalnız bu **medya-hariç** ayak izine uygulanır; bütçe medya işleme
konumundan (ADR-009 hibrit) **bağımsızdır** (invariant **B8**).

## 3. Üç-bantlı izleme + sınırlama merdiveni

```
                    footprint (medya hariç)
   0 ─────────── soft (12MB) ──────────── hard (15MB) ───────────▶
   │     OK            │       WARN          │      BREACH
   │  eylem yok        │  AZALTMA            │  ZORLA-AZALT
   │  (adillik B7)     │  özetle+kırp        │  + grace sonrası
   │                   │  (FR-RES-010)       │  KONTROLLÜ shed (FR-RES-014)
```

- **OK** (≤ soft): eylem yok. Sağlıklı oturuma müdahale **edilmez** (adillik, **B7**).
- **WARN** (soft < x ≤ hard): **azaltma** — özetleme (FR-RES-010) `dialogue_memory`'yi + RAG kırpma
  `rag_context`'i `summarize_factor` oranında küçültür → ayak izi bütçeye döner, oturum **kesintisiz**
  (kullanıcıya görünmez). Azaltma ayak izini **gerçekten** düşürmeli (**B5**).
- **BREACH** (x > hard): **zorla-azalt**; ayak izi `grace_samples` ardışık örnek boyunca hâlâ hard
  üstündeyse **kontrollü shed**: oturum graceful sonlandırılır veya insan temsilciye **aktarılır**
  (handoff) — **çökme/OOM-kill DEĞİL**, sessiz veri kaybı **DEĞİL** (**B2/B3**).
- **CPU** bandı simetrik (`cpu_soft`/`cpu_budget`); CPU **özetlenemez** → CPU BREACH grace sonrası
  doğrudan kontrollü shed'e yükselir.

**İzleme (B4):** her oturum örneklenir; her hard-aşımı **tespit + kaydedilir/yayılır** (BRD §15
"çağrı başına kaynak tüketimi (CPU/bellek)" → observability 0.4.7 + **aşım alarmlanır**). Hiçbir aşım
tespitsiz kalmaz (`missed_breach = 0`).

## 4. HARD kapılar (B-serisi)

| Kapı | Eşik | Anlam | İz |
|------|------|-------|-----|
| **B1** | `mem_budget ≤ 15` + `soft < hard` + `cpu_budget > 0` | bütçe tanımlı | FR-RES-016, NFR 10.2 |
| **B2** | `unbounded_overshoot = 0` | her aşım azaltma **veya** kontrollü shed ile sınırlanır | FR-RES-014 |
| **B3** | `uncontrolled_oom = 0` ∧ shed graceful | sınırlama **graceful** (çökme/OOM yasak) | FR-RES-014 |
| **B4** | `missed_breach = 0` | her aşım izlenir + yayılır | FR-RES-016 |
| **B5** | `mitigation_ineffective = 0` | özetleme ayak izini gerçekten düşürür | FR-RES-010 |
| **B6** | non-blocking | izleme sıcak yola gecikme eklemez | NFR 10.1, FR-RES-001 |
| **B7** | `spurious_action = 0` | sağlıklı oturuna müdahale yok (adillik) | FR-RES-014 |
| **B8** | `media_in_budget = false` | 15MB bütçe medyayı hariç tutar | SAD §6/§13, ADR-009 |
| **B9** | metrikler → 0.4.7 | per-call bellek/CPU/breach yayılır; call_id label değil | BRD §15, SAD §17 |
| **B10** | taksonomi/residency/sır | hata→API §11.6; home-region; sır/PII/ham payload yok | API §11.6, NFR 10.7 |

B1/B6/B8/B9/B10 spec'te `validate` ile; B2/B3/B4/B5/B7/B8 oturum-akışında `simulate` ile zorlanır.

## 5. Guard modeli (deterministik, örnek-tetikli)

Bir **örnek (sample-point)** = oturumun sanal zaman `t`'de **ulaşacağı** bileşen seviyeleri (azaltma
**öncesi** TALEP). Guard talebi bantlar ve gerekirse azaltarak **ZORLANAN (enforced)** ayak izini
üretir:

1. `demand = Σ components_mb` (medya hariç).
2. Bant: OK/WARN/BREACH.
3. WARN/BREACH + `mitigate` → `dialogue_memory`/`rag_context` `× (1 − summarize_factor)` → `enforced`.
4. `enforced > hard` (veya `cpu > cpu_budget`) ardışık `grace_samples` → **kontrollü shed**.
5. İzleme: her aşım tespit + yayılır (izleme kapalıysa `missed_breach`).

**Determinizm:** olay-tetikli, sanal saat (`sample.t`); **random YOK** → aynı örnek-akışı birebir aynı
metrik (CI). Percentile yöntemi 0.3.1/0.3.2/0.3.3/3.1.3 ile **birebir** lineer interpolasyon.

> **Neden simülasyon?** 0.2.x/0.3.x/3.1.x hattının disiplini: **vendor-neutral** (ADR-002),
> **stdlib-only**, **credential-free**, **tekrarlanabilir**. Gerçek RSS/heap+CPU ölçümü çalışan
> hot-path kodu (Go/Rust, ADR-003) ve canlı yük gerektirir. **Mimari/yöntem değeri** sahte sayılarda
> değil, **kapı mantığının** (bant geçişi, azaltma etkisi, kontrollü shed, izleme kapsamı, medya
> hariçliği) doğru ve canlı ölçümle **değişmeden** kullanılabilir olmasındadır. Canlı runtime'da aynı
> profil yapısı gerçek profiler telemetrisiyle doldurulur; **kapı kodu değişmez**.

## 6. Senaryolar (`samples/*.json`)

| Sample | Ne gösterir | Sonuç |
|--------|-------------|-------|
| `budget-happy-path` | ≤soft → eylem yok (adillik) | 🟢 |
| `budget-warn-mitigated` | WARN → özetleme bütçeye döndürür (B5) | 🟢 |
| `budget-breach-shed` | azaltma yetmez → kontrollü graceful shed (B2/B3) | 🟢 |
| `budget-media-excluded` | yüksek medya bütçeye girmez (B8) | 🟢 |
| `budget-degraded` | sınırlama+izleme kapalı → B2/B4 eler (bilinçli) | 🔴 (beklenen) |

## 7. İzlenebilirlik

- **FR:** FR-RES-016 (per-call bütçe + aşım izleme — birincil) · FR-RES-014 (graceful sınırlama) ·
  FR-RES-010 (özetleme azaltma kaldıracı) · FR-RES-001 (non-blocking) · FR-ANA-013 (per-call metrik
  raporu) · FR-TEN-002 (tenant kota bağlamı).
- **NFR:** 10.2 (≤~15MB density) · 10.1 (izleme gecikme eklemez) · 10.7 (residency).
- **SAD:** §6.3 (oturum aktörü) · §13 (oturum durumu küçük, medya/ham veri ayrı) · §15.2 (Resource
  Manager Cost/Resource Meter + Backpressure) · §21 (lean runtime mandası).
- **ADR:** 003 (lean runtime — bütçenin mimari gerekçesi) · 008 (model tiering/cache — bellek
  kaldıracı) · 009 (medya konumu — bütçe medya-bağımsız).
- **SR/TC:** SR-RES-016 → TC-RES-016 (RTM'de zaten eşli; SRS/RTM değişikliği gerekmedi). İlişkili:
  SR-RES-014, SR-RES-010, SR-DEN-001, SR-ANA-013.
- **Observability (0.4.7):** `per_call_memory_mb`/`per_call_cpu_mcore` → mevcut kaynak metrikleri;
  `budget_breach_total`/`budget_mitigation_total`/`budget_shed_total` → önerilen eklemeler. Yüksek
  kardinalite (`call_id`) metrik label'ı **olmaz** (yalnız trace/exemplar).

## 8. Komutlar

```bash
python3 resource_budget_probe.py validate            # spec + config statik kapı (B1–B10)
python3 resource_budget_probe.py simulate <sample>   # oturum-akışı → bant/azaltma/shed + kapı
python3 resource_budget_probe.py selftest            # iyi/kötü kanıt
python3 resource_budget_probe.py schema              # beklenen spec şekli
./run_live_test.sh                                   # statik + sample (+ canlı NOT, ORCHESTRATOR_URL)
```

Vendor-neutral (ADR-002); sır/credential, ham ses payload'ı, transkript ve PII repoya yazılmaz —
örnekler yalnız bileşen boyutu (MB/mcore) + sanal zaman taşır.
