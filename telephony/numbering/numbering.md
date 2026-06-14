# Numaralandırma Düzlemi — E.164 + Caller ID & Numara Havuzu (WBS 2.1.5)

> **Faz:** F1 · **Öncelik:** Must · **İz:** FR-TEL-004 (E.164), FR-TEL-005 (Caller ID & numara havuzu)
> **Kaynak doğruluk:** `numbering-spec.json`. Çelişkide **BRD/SAD/DB/API esastır.**
> Vendor-neutral (ADR-002), credential-free, stdlib-only — `telephony/managed-cpaas/` (2.1.3) +
> `telephony/byoc-sip/` (2.1.4) probe disipliniyle birebir aynı.

## 1. Kapsam ve mimari konum

Bu dilim telefoni **numaralandırma düzlemini** (numbering plane) tanımlar — **medya düzlemi
değil**. Medya/SIP/RTP normalizasyonu 2.1.3 (M1 managed CPaaS) ve 2.1.4 (M2 BYOC SIP) tarafından
ele alınır. Numaralandırma düzlemi bu iki adaptörü **besler**:

```
                    ┌──────────────────────────────────────────┐
   INBOUND          │   Numaralandırma Düzlemi (2.1.5)          │       OUTBOUND
   PSTN ──DID──►    │                                          │   ◄── Caller ID seçimi
                    │  e164 normalize (FR-TEL-004)             │
   ┌────────────┐   │  numara havuzu (FR-TEL-005, DB §14)      │   ┌─────────────────┐
   │ DID→tenant │◄──┤   • global benzersiz e164 (FR-TEN-002)   ├──►│ callerIdPool/from│
   │  +agent    │   │   • yön: inbound/outbound/both           │   │ (API §11.5)     │
   └─────┬──────┘   │   • bölge pini (NFR 10.7)                │   └────────┬────────┘
         │          └──────────────────────────────────────────┘            │
         ▼                                                                    ▼
  2.1.3/2.1.4 context_binding                                       TelephonyAdapter.dial()
  did_to_tenant_map (SAD §13.3)                                     (FR-TEL-001/002)
```

- **Inbound:** Gelen DID (çağrılan numara) E.164'e normalize edilir, ardından havuzdan
  **tenant + agent**'a deterministik çözülür. Bu çözüm, 2.1.3/2.1.4'teki
  `context_binding.tenant_resolution = did_to_tenant_map`'in kaynağıdır (SAD §13.3).
- **Outbound:** Çağıran tenant'ın havuzundan, çağrılan numaraya (callee) ve kampanyaya göre
  bir **Caller ID** seçilir; `TelephonyAdapter.dial(DialRequest{from, callerIdPool})` (API §11.5)
  bu değeri kullanır (FR-TEL-005, BRD §737 "kullanılacak Caller ID").

## 2. E.164 normalizasyonu (FR-TEL-004, SR-TEL-004)

Tüm telefon numaraları **kanonik E.164** biçiminde normalize edilir ve saklanır
(`+` + 7..15 hane, `^\+[1-9]\d{6,14}$`). DB §14 `phone_number.e164` bu biçimi şart koşar.

**Normalize çekirdeği** (deterministik, idempotent — vendor-neutral minimal; canlı sistemde tam
metadata kütüphanesi adaptörde):

1. Biçim karakterleri (boşluk, tire, parantez, nokta) atılır.
2. `+` ile başlıyorsa → zaten uluslararası (CC+NSN).
3. Değilse `default_region` bağlamı kullanılır:
   - **IDD öneki** (`00`, NANP `011`) → uluslararası önek soyulur.
   - **Trunk öneki** (TR/GB/DE `0`, NANP `1`) → soyulur, ülke kodu eklenir.
   - **Trunk'suz ulusal** numara (NSN uzunluğu metadata aralığında) → ülke kodu eklenir.
   - Zaten ülke kodu içeriyorsa → olduğu gibi.
4. **Doğrulama:** ≤15 hane + ülke metadata NSN aralığı. Uymuyorsa **sessizce kırpılmaz,
   reddedilir** (N3 → `INVALID_REQUEST`).

> **NANP inceliği:** `1` hem trunk öneki hem ülke kodudur. `1 202 555 0143` ve `202 555 0143`
> aynı `+12025550143`'e çözülür; çekirdek bu çakışmayı NSN uzunluğuyla ayırır (T4 testi).

**İdempotency (N2):** `normalize(normalize(x)) == normalize(x)` — havuza yazılan her değer
zaten kanoniktir; tekrar normalize değişiklik üretmez.

## 3. Numara havuzu (FR-TEL-005, DB §14)

| Özellik | Kural | İz |
|---------|-------|----|
| Kapsam | tenant-scoped (RLS) | DB §6.2 |
| **e164 benzersizliği** | **global** — bir numara tam bir tenant'a (DB §14 `UNIQUE(e164)`) | N4, FR-TEN-002 |
| Yön | `inbound` / `outbound` / `both` | DB §14 `direction` |
| Bölge pini | zorunlu, home-region'a hizalı | N7, NFR 10.7 |
| Inbound yönlendirme | `phone_number.agent_id` → agent | N5, DB §14 |

**Global benzersizlik neden kritik?** İki tenant aynı DID'e sahip olamaz; aksi halde inbound
DID→tenant çözümü çok-anlamlı olur ve **çapraz-tenant sızıntı** doğar (FR-TEN-002). `validate`
config havuzunda bu çakışmayı statik olarak yakalar; `resolve` çalışma-anında >1 eşleşmeyi N4
ihlali olarak reddeder.

## 4. Caller ID seçimi (FR-TEL-005, BRD §737)

Outbound çağrıda Caller ID **deterministik** seçilir:

1. **Talep edilen** Caller ID varsa → havuz **ve** outbound-yetki doğrulanır.
   Havuz-dışı/non-outbound ise **REDDEDİLİR** (anti-spoof, N6).
2. **Kampanya pin'i** varsa → adaylar bu kampanyaya bağlı numaralarla daraltılır.
3. **Local-presence** → callee ülke koduyla eşleşen numara tercih edilir (yanıt oranı + uyum).
4. **Varsayılan** → kalan adaylar içinde `e164`-sıralı kararlı ilk.

### Anti-spoof (N6, FR-AUTH-001 ruhu)

Caller ID güçlü kimlik kanıtı değildir (FR-AUTH-001). Platform **yalnız tenant'ın sahip olduğu
numarayı** sunabilir; keyfî bir numarayı Caller ID olarak sunma engellenir (THREAT_MODEL TM-S
spoofing). Bu, hem talep-edilen hem seçilen numara için zorlanır.

### CLI sunumu ve compliance (N9)

Geçerli CLI sunumu varsayılandır. **Gizleme (withhold)** yalnızca compliance profili izin
veriyorsa mümkündür (`cp.outbound.cli_presentation`, DPIA.md; en-kısıtlayıcı kazanır). Arama
saatleri (`cp.outbound.calling_hours`, FR-TEL-013) ve DNC/opt-out (`cp.outbound.dnc`,
FR-TEL-014) bu sözleşmenin sağladığı Caller ID kaynağını **tüketen** ayrı dilimlerdir.

## 5. Hata taksonomisi (N10, API §11.6)

| Numaralandırma hatası | ErrorTaxonomy |
|------------------------|---------------|
| `e164_unparseable` / `e164_too_long` | `INVALID_REQUEST` |
| `caller_id_not_in_pool` / `caller_id_not_outbound` | `INVALID_REQUEST` |
| `did_unresolved` | `INVALID_REQUEST` |
| `region_mismatch` | `REGION_VIOLATION` |

## 6. Residency & PII

- **Residency (N7):** Havuz numarasının bölge pini home-region'a hizalı; outbound seçimde
  uyumsuzluk `REGION_VIOLATION` (NFR 10.7).
- **PII (N11):** Telefon numarası kişisel veridir. Bu spec/config **yalnız tenant'ın kendi havuz
  numaralarını** (illüstratif ayrılmış aralıklar) tutar; **müşteri (callee) numarası saklanmaz** —
  o `contact` varlığına ve oturum bağlamına aittir. Panelde numaralar maskeli görünebilir.

## 7. İnvariant'lar (N1–N11)

`numbering-spec.json#invariants` kaynağıdır. Her biri `validate` ve/veya `normalize`/`select`
simülatörü tarafından zorlanır; `selftest` her invariant için negatif kanıt üretir (kötü
spec/sample → kapı eler).

## 8. Doğrulama (probe)

```
python3 numbering_probe.py validate              # spec + config havuzu invariant kapısı
python3 numbering_probe.py normalize samples/normalize-valid.json
python3 numbering_probe.py select    samples/caller-id-local-presence.json
python3 numbering_probe.py resolve   "+908500000123"   # inbound DID → tenant+agent
python3 numbering_probe.py selftest              # iyi/kötü kanıt
python3 tests/e164_behavior_test.py              # T1–T6 davranış
```

Sonuçlar: **validate 45/45 · selftest 32/32 · e164_behavior 12/12** 🟢; 5 sample beklendiği gibi
(normalize-valid/caller-id-local-presence/caller-id-campaign 🟢 · caller-id-spoof anti-spoof
reddi 🟢 · normalize-degraded bilinçli 🔴).

## 9. Kapsam ayrımı (bilinçli dışarıda)

- **Medya/SIP/RTP normalize** → 2.1.3 (M1), 2.1.4 (M2).
- **SBC / SIP App Server** → 2.1.1 / 2.1.2 (DID routing'in sinyalleşme tarafı).
- **DTMF / neden kodları** → 2.1.6 / 2.1.7.
- **Outbound consent / arama saatleri / DNC zorlaması** → FR-TEL-013/014 (ayrı dilim); burada
  yalnız Caller ID **kaynağı** + compliance bağlama noktası verilir.
- **phone_number tablosu fiziksel migration'ı** → DB §14 (varlık 14); bu dilim sözleşme/şema
  illüstrasyonudur, canlı havuz DB'dedir.
- **Tam E.164 metadata kütüphanesi** (tüm dünya numara planları) → canlı adaptör; burada
  minimal deterministik çekirdek (TR/GB/DE/US, residency profilleriyle hizalı).
