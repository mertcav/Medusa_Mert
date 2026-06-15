# `outbound/campaign-stop/` — WBS 10.1.7 Kampanya durdurma düğmesi

10. workstream'in (Outbound) Kampanya Yönetimi alt-bloğunun **durdurma kontrolü** modülü ·
**F2 · Must** · →**FR-OUT-010** · SR-OUT-010 (yöntem **D**) · TC-OUT-010.

Çalışan bir outbound kampanyayı **durduran/duraklatan** kontrol düğmesi. `DB.md` `campaign.status`
yaşam döngüsünü (`draft`/`running`/`paused`/`stopped`/`completed`) uygular ve API §A-10
`POST /campaigns/{id}:stop` (`campaign:manage`) kontrol yüzeyinin arkasındadır. **Çekirdek kabul
ölçütü (SR-OUT-010):** durdurma sonrası **dialer admission kapısı kapanır ve yeni çağrı başlatılmaz**;
devam eden çağrılar abruptly düşürülmez (graceful drain, SAD §6).

## Dosyalar
| Yol | Açıklama |
|-----|----------|
| `campaign-stop-spec.json` | Makine-okunur **kaynak doğruluk**: yaşam döngüsü, komutlar, geçiş tablosu, dialer kapısı, yetki, kapılar, invariant C1–C12, izlenebilirlik |
| `campaign-stop.md` | Tasarım dokümanı (durum makinesi, admission kapısı, graceful drain, kapsam ayrımı) |
| `campaign_stop_probe.py` | Stdlib-only **deterministik kampanya kontrol motoru**: `validate`/`run`/`selftest`/`schema` |
| `config/campaign-stop-policies.json` | Geçiş tablosu + yetkili roller + kapı kuralları + drain politikası (credential-free) |
| `samples/*.json` | 9 pass + 7 degrade senaryo (sentetik, FR-TST-008) |
| `tests/campaign_stop_behavior_test.py` | Bağımsız kara-kutu davranış kapısı (C1–C12) |
| `run_live_test.sh` | Tüm statik + davranış kapılarını koşar |

## Hızlı çalıştırma
```bash
cd outbound/campaign-stop
./run_live_test.sh                            # tümü
python3 campaign_stop_probe.py validate       # statik kapı
python3 campaign_stop_probe.py run samples    # senaryolar
python3 campaign_stop_probe.py selftest       # gömülü kontroller
```

## Komutlar ve geçişler (DB.md status CHECK)
- `stop` — kampanyayı **DURDUR** (FR-OUT-010 düğmesi; `running`/`paused`→`stopped`, **TERMİNAL**)
- `pause` — **DURAKLAT** (`running`→`paused`, **resumable**) · `resume` — **SÜRDÜR** (`paused`→`running`)
- `start` — çalıştır (`draft`→`running`) · `complete` — doğal bitiş (`running`→`completed`)

`stop`/`pause`/`complete` → dialer kapısı **KAPALI** (yeni çağrı yok); `start`/`resume` → **AÇIK**.

## Çekirdek invariant (SR-OUT-010, C4)
Durdurma sonrası `dialer_gate=closed` ve `new_calls_admitted_after=0` olmalı — **"durdurma sonrası
yeni çağrı başlatılmaz"**. Kapı kapalıyken yeni çağrı admit edilirse C4 ihlali → kapı eler. Bu modül
kapıyı **ayarlar**; gerçek dialer çevirme (10.1.x) kapıya uyar.

## Durum
validate **82/82** 🟢 · selftest **57/57** 🟢 · run **16/16** 🟢 (9 pass + 7 degrade beklendiği gibi
elendi) · behavior **49/49** 🟢. Vendor-neutral (ADR-001/002/012); sır/credential ve müşteri PII
(ad/telefon/hesap no) repoya yazılmaz (C12). Canlı dialer/audit testi F2'de gerçek entegrasyon
(10.1.x dialer + 12.x audit store) ile koşar.

Rapor: [`reports/10.1.7-kampanya-durdurma-dugmesi-raporu.md`](../../reports/10.1.7-kampanya-durdurma-dugmesi-raporu.md)
