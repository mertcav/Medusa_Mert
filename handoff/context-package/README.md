# `handoff/context-package/` — WBS 9.6 Bağlam paketi + screen-pop

9. workstream'in (İnsan Temsilciye Aktarım) **altıncı** modülü · **F1 · Must** · →**FR-HND-004, FR-HND-005**.

Aktarım anında temsilciye gösterilecek **bağlam paketini** derler ve teslim eder: **özet + intent +
toplanan alanlar + auth durumu**. SAD §7.3'teki `Orchestrator (transfer kararı) │ bağlam paketi` noktası
ve "Bağlam paketi CC'ye hem ekran-pop (screen-pop) verisi (CTI/CRM üzerinden) hem de transkript özeti
olarak iletilir (FR-HND-004/005)" cümlesinin sahibidir. Paket, 9.5'in seçtiği hedefe teslim edilir;
9.1/9.2/9.3 mekanizma modülleri (warm/whisper whisper brifing dahil) bu paketi **tüketir**.

## Dosyalar
| Yol | Açıklama |
|-----|----------|
| `context-package-spec.json` | Makine-okunur **kaynak doğruluk**: durumlar, dört bileşen, redaction, teslim, kapılar, invariant P1–P12, izlenebilirlik |
| `context-package.md` | Tasarım dokümanı (durum makinesi, dört bileşen, redaction/PII minimizasyonu, fail-safe, kapsam ayrımı) |
| `context_package_probe.py` | Stdlib-only **deterministik paket derleyici/teslim motoru**: `validate`/`run`/`selftest`/`schema` |
| `config/context-package-policies.json` | Dört zorunlu bileşen + redaction (auth_secret_fields/maskeleme) + teslim kanalları (credential-free) |
| `samples/*.json` | 6 pass + 7 degrade senaryo (sentetik, FR-TST-008) |
| `tests/context_package_behavior_test.py` | Bağımsız kara-kutu davranış kapısı (P1–P12) |
| `run_live_test.sh` | Tüm statik + davranış kapılarını koşar |

## Hızlı çalıştırma
```bash
cd handoff/context-package
./run_live_test.sh                               # tümü
python3 context_package_probe.py validate        # statik kapı
python3 context_package_probe.py run samples     # senaryolar
python3 context_package_probe.py selftest        # gömülü kontroller
```

## Dört zorunlu bileşen (FR-HND-004)
1. `summary` — görüşme özeti (referans token, ham transkript değil)
2. `intent` — müşteri niyeti
3. `collected_fields` — oturumda toplanan alanlar (**FR-HND-005**: tekrar-sormama)
4. `auth_status` — kimlik doğrulama durumu `{level, methods, step_up}` (ham sır **yok**)

## Redaction (PII minimizasyonu, FR-AUTH-005)
- Hassas alanlar screen-pop'a **maskeli** (son-4, ör. `****-4321`)
- `auth_status` **yalnız-statü** — OTP kodu / parola / KBA cevabı / tam PAN pakete **girmez**

## Fail-safe (P8)
Screen-pop (CTI/CRM) yoksa transfer **düşmez** → `DEGRADED`: verbal(whisper)/transkript özeti fallback
bağlam (özet+intent) sağlanır, oturum korunur. `DEGRADED` ihlal değil, fail-safe sonuçtur.

## Durum
validate **73/73** 🟢 · selftest **42/42** 🟢 · run **13/13** 🟢 (6 pass + 7 degrade beklendiği gibi
elendi) · behavior **27/27** 🟢. Vendor-neutral (ADR-001/002); sır/credential repoya yazılmaz; müşteri
adı/telefon/hesap no tam değeri/ham transkript/OTP tutulmaz (P12). Canlı screen-pop testi F1/F2'de gerçek
CTI/CRM + 9.1/9.2/9.3 ile koşar.

Rapor: [`reports/9.6-baglam-paketi-screen-pop-raporu.md`](../../reports/9.6-baglam-paketi-screen-pop-raporu.md)
