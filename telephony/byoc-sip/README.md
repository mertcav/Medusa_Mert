# `telephony/byoc-sip/` — SIP trunk / BYOC desteği (WBS 2.1.4)

Telefoni soyutlamasının (SAD §7.2) **M2 — Ham SIP trunk + RTP (BYOC, Bring Your Own Carrier)** modunun
fiziksel sözleşmesi: kendi SBC'mizin sonlandırdığı SIP sinyalleşme + SDP müzakere + RTP medyanın,
orchestrator'ın gördüğü **tek** sözleşmeye (API §12.1, `TelephonyAdapter` SPI BYOC modu) **normalize**
edilmesi. Bu sözleşme **2.1.3 managed-cpaas (M1) ile birebir aynıdır** — orchestrator M1/M2 farkını görmez
(ADR-001/ADR-002). `db/`+`cache/`+`objstore/`+`eventstream/`+`managed-cpaas/` disipliniyle aynı:
**vendor-neutral (ADR-002)**, **credential-free**, statik probe + deterministik SIP/SDP/RTP normalize
simülatörü + opsiyonel canlı kapı.

> **Kaynak doğruluk:** `byoc-spec.json` (makine-okunur). Çelişkide o, üstünde SAD §7.2/§12.1, API §11.5/§12.1, BRD esastır.

## Dosyalar

| Dosya | İçerik |
|-------|--------|
| `byoc-spec.json` | **Kaynak doğruluk:** medya profili (G.711) + transport (SIPS/SRTP) + auth + bağlam bağlama (DID→tenant) + normalize sözleşmesi (2.1.3 ile aynı) + SIP diyalog SM + SDP müzakere + ≥2 trunk eşlemesi + fallback (çapraz-mod M1) + barge-in + DTMF (RFC2833/INFO) + transfer (REFER) + reconnect + hata taksonomisi + invariant I1–I15 |
| `byoc-sip.md` | Tasarım: mimari konum, SPI bağlama, SIP/SDP/RTP→normalize kalbi, güvenlik/bağlam, SIP diyalog SM, barge-in, dayanıklılık, residency/PII, izlenebilirlik |
| `byoc_probe.py` | stdlib-only kapı: `validate` / `normalize <sample>` (deterministik SIP/SDP/RTP normalize sim.) / `selftest` / `schema` |
| `config/trunks.json` | BYOC trunk bağlantı profilleri (spec türevi; SBC peer/secret/region yalnız `${ENV}`; fallback sırası + çapraz-mod M1) |
| `samples/inbound-happy-path.json` | Primary trunk inbound: INVITE→180→answer→RTP→DTMF(RFC2833)→BYE + egress (FR-TST-008) |
| `samples/barge-in.json` | Secondary trunk: 183 early-media (meşru RTP) + SIP INFO DTMF + `rtp_playout_stop` 25 ms ≤200 ms (ADR-002 simetri) |
| `samples/degraded.json` | Bilinçli ELENEN: düz-metin sinyalleşme + RTP-before-answer + wideband G722 + eksik bağlam + bölge uyumsuz + 260 ms barge-in |
| `tests/sdp_rtp_behavior_test.py` | SDP codec müzakere + G.711/RTP çerçeveleme aritmetiği (T1–T5) |
| `run_live_test.sh` | Statik kapı + sample normalize; `${BYOC_SBC_HOST}` varsa canlı not, yoksa SKIP |

## Çalıştırma

```bash
python3 telephony/byoc-sip/byoc_probe.py validate                                  # 73/73 PASS (çıkış 0)
python3 telephony/byoc-sip/byoc_probe.py selftest                                   # 22/22 PASS
python3 telephony/byoc-sip/byoc_probe.py normalize telephony/byoc-sip/samples/inbound-happy-path.json
python3 telephony/byoc-sip/tests/sdp_rtp_behavior_test.py                           # 9/9 PASS
bash    telephony/byoc-sip/run_live_test.sh                                         # canlı (varsa) / SKIP
```

## Özet kararlar

- **Normalize kalbi:** BYOC SIP diyalog olayları (`answer→start`, `rtp→media`, `dtmf→dtmf`, `bye→stop`)
  **2.1.3 ile aynı** tek sözleşmeye indirgenir; egress `play_audio→rtp_out`, `barge_in_clear→rtp_playout_stop`.
  Orchestrator yalnız SPI'ye bağlı (ADR-001); yeni trunk = bir eşleme tablosu + profil (ADR-002, ≥2 trunk
  + çapraz-mod M1 fallback).
- **Güvenlik:** SIPS/TLS sinyalleşme + SRTP medya zorunlu (I1, SBC önde) + medya öncesi peer auth (I2;
  digest/IP-ACL/mTLS) + tenant/correlation/call bağlam bağlama her olaya (I3; DID→tenant, FR-TEN-002).
- **Medya:** 8 kHz G.711 μ-law/A-law 20 ms/50 fps, no-transcode (I4, FR-RES-008); SDP yalnız narrowband
  seçer, ortak codec yoksa **REDDET** (488), transcode yok (I15).
- **SIP diyalog:** RTP medya 200 OK (ANSWERED) öncesi reddedilir — **tek istisna 183 early media** (I9);
  geçişler yalnız `valid_transitions`.
- **Barge-in:** `rtp_playout_stop` ile agent sesi ≤200 ms kesilir (I5, FR-RTC-002, NFR 10.1); hibrit
  topoloji (edge barge-in, ADR-005/ADR-009) — M2 ekstra bulut sıçraması olmadığından overhead düşük.
- **DTMF:** RFC 2833 (telephone-event pt=101) **veya** SIP INFO → normalize `dtmf` (I12, FR-TEL-006).
- **Dayanıklılık:** SIP yanıt kodu→ortak `ErrorTaxonomy` (API §11.6) + fallback + sonlu re-INVITE penceresi
  + CSeq takibi (I8/I13).
- **Residency/PII:** trunk/SBC bölge home-region pin (I11, NFR 10.7); ham ses/PII spec/config'te yok (I14).

**Sır/credential repoya yazılmadı** — SBC peer/SIP URI/secret yalnız `${ENV}`. Vendor-neutral (ADR-002).
Canlı medya RTT/jitter ölçümü tek ölçüm hattına (`vendor-eval/media_latency_probe.py`, 0.2.1 M2) devredilir;
SBC kurulumu **2.1.1**, SIP App Server (call setup/teardown/routing) **2.1.2**, CC entegrasyonu (M3) F2.
