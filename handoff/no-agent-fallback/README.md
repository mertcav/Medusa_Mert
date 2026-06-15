# `handoff/no-agent-fallback/` — WBS 9.7 Temsilci yoksa callback/voicemail/ticket

9. workstream'in (İnsan Temsilciye Aktarım) **yedinci** modülü · **F1 · Must** · →**FR-HND-007**.

Temsilci bulunamadığında (temsilci yok / kuyruk dolu / transfer başarısız / hedef çözülemedi / mesai dışı)
müşteriye **çağrıyı asla düşürmeden** ertelenmiş bir hizmet yolu — **callback / voicemail / ticket** — sunar.
SAD §7.3 Human Handoff diyagramının `└─ temsilci yoksa ──► callback / voicemail / ticket (FR-HND-007)`
dalının sahibidir. 9.1/9.2/9.3 fail-safe + 9.5 UNRESOLVED bu modülü **tetikler**; sonuç 9.8'e iletilir.

## Dosyalar
| Yol | Açıklama |
|-----|----------|
| `no-agent-fallback-spec.json` | Makine-okunur **kaynak doğruluk**: durumlar, üç fallback türü, tetik nedenleri, onay, kapılar, invariant K1–K12, izlenebilirlik |
| `no-agent-fallback.md` | Tasarım dokümanı (durum makinesi, üç tür, fail-safe ilkesi, kapsam ayrımı) |
| `no_agent_fallback_probe.py` | Stdlib-only **deterministik fallback sunum/seçim motoru**: `validate`/`run`/`selftest`/`schema` |
| `config/no-agent-fallback-policies.json` | Üç seçenek + uygunluk/önkoşul + onay/AI ifşası + fail-safe son çare (credential-free) |
| `samples/*.json` | 7 pass + 8 degrade senaryo (sentetik, FR-TST-008) |
| `tests/no_agent_fallback_behavior_test.py` | Bağımsız kara-kutu davranış kapısı (K1–K12) |
| `run_live_test.sh` | Tüm statik + davranış kapılarını koşar |

## Hızlı çalıştırma
```bash
cd handoff/no-agent-fallback
./run_live_test.sh                                # tümü
python3 no_agent_fallback_probe.py validate       # statik kapı
python3 no_agent_fallback_probe.py run samples    # senaryolar
python3 no_agent_fallback_probe.py selftest       # gömülü kontroller
```

## Üç fallback türü (FR-HND-007)
1. `callback` — onaylı geri-arama planı (çevirme outbound dialer 10.x'te; **FR-TEL-009/FR-OUT-005**)
2. `voicemail` — inbound müşteri mesajı (**kayıt onayı + AI ifşası** zorunlu, BRD §14.2)
3. `ticket` — asenkron destek kaydı (**daima-mevcut son çare**; 9.6 bağlamından)

## Fail-safe (K8 — "never drop the call", SAD §6)
Müşteri tüm seçenekleri reddetse / yanıt vermese / yakalama başarısız olsa bile, bağlamdan (9.6 `context_ref`)
**oto-ticket** oluşturulur → `SAFE_CLOSE`. Çağrı asla sessiz düşmez. `SAFE_CLOSE` ihlal değil, fail-safe sonuçtur.

## Durum
validate **76/76** 🟢 · selftest **50/50** 🟢 · run **15/15** 🟢 (7 pass + 8 degrade beklendiği gibi
elendi) · behavior **35/35** 🟢. Vendor-neutral (ADR-001/002); sır/credential repoya yazılmaz; müşteri
adı/telefon/voicemail içeriği/ticket gövdesi/OTP tutulmaz (K12). Canlı dialer/ticketing/kayıt testi F1/F2'de
gerçek entegrasyon (10.x/11.x/12.x) + 9.1/9.2/9.3 ile koşar.

Rapor: [`reports/9.7-temsilci-yoksa-callback-voicemail-ticket-raporu.md`](../../reports/9.7-temsilci-yoksa-callback-voicemail-ticket-raporu.md)
