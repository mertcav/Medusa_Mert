# T-04 — Telefon Numarası & SIP/Trunk (WBS 13.3.4)

L1 Tenant Admin Console'un dördüncü ekranı (T-01..T-09 serisi). Tenant'ın telefon **numara havuzu**
(E.164 DID'ler), **SIP trunk / BYOC** (Bring Your Own Carrier) bağlantıları ve giden **Caller ID**
yönetimini gösterir ve yönetir (BRD §17.4 / FR-TEL-001/002/004/005 · FR-AGT-007). Numaralar E.164
biçimindedir (FR-TEL-004); telefoni katmanı sağlayıcıdan bağımsızdır (ADR-002).

## Tenant scope (FR-TEN-002) + hijyen (BRD §17.7) + güvenlik (NFR 10.6)
T-04 **yalnız oturum açan tenant'ın KENDİ** telefoni envanterini gösterir/yönetir; scope çalışma-anında
middleware (13.1.2) + RLS (§13) ile sabitlenir. Ekran yalnız tenant'ın **kendi telefoni
konfigürasyonunu** gösterir:
- Ham son-müşteri iş içeriği (çağrı kaydı, transkript, **arayan/çağrılan müşteri numarası**, PII)
  buraya **gömülmez** — `FORBIDDEN_PII_KEYS` + `assertNoPii` ile çalışma-anında garanti.
- SIP trunk **sırrı** (kayıt/registration parolası, auth token, credential) buraya **konmaz** —
  `FORBIDDEN_SECRET_KEYS` + `assertNoPii` ile garanti; yalnız bağlantı durumu + kapasite gösterilir.
  Gizli değerler backend secret store'dadır.
- `tenantRef`/`tenantName` + numara `e164` (tenant'ın **KENDİ** DID'i) + trunk `name` + giden Caller ID
  `e164` tenant'ın **kendi** envanteridir (son-müşteri PII değil → izinli). Yasak liste yalnız
  son-müşteri (arayan) numarası/PII alan adlarıdır (`msisdn`/`callerId`/`callerNumber`/...).

## Bileşenler
- `app/(tenant-admin)/admin/numbers/page.tsx` — ekran (RSC, async). Tasarım sistemi (`lib/ui`) + i18n
  (`lib/i18n`) + veri seam (`lib/tenant/numbers`). Tüm metin `screen.t04.*` katalogundan (t()).
  Bölümler: **Özet** (toplam numara/havuz/trunk/Caller ID) · **SIP Trunk & BYOC** (tür sip_trunk/byoc/
  managed + bölge + yön + kanal kullanım/kapasite + durum) · **Numara Havuzu** (E.164 + yön + bağlı trunk
  + agent/kampanya ataması + durum) · **Caller ID** (sunum numarası + doğrulama + varsayılan). Geçersiz
  trunk referansı / geçersiz E.164 → danger uyarısı; trunk kapasite ≥%90 / doğrulanmamış varsayılan
  Caller ID → warning uyarısı.
- `lib/tenant/numbers.ts` — vendor-neutral veri **seam** + saf türetme yardımcıları
  (`countNumberStatus`/`countNumberDirection`/`unassignedNumbers`/`numbersForTrunk`/`invalidTrunkRefs`/
  `isValidE164`/`invalidE164Numbers`/`trunkUtilizationPct`/`overCapacityTrunks`/
  `unverifiedDefaultCallerIds`/tone'lar) + `assertNoPii` guard (PII **ve** sır). Yer tutucu deterministik
  snapshot; gerçek kaynak F2 §14.1'de Telephony/Number Manager + SBC/trunk envanterinden tenant-scope
  (RLS) beslenir.
- `i18n` (`screen.t04.*`) — TR/EN, design-system canonical katalogda; her iki app'e vendored (hash-eşit).

## RBAC (BRD §17.6)
`tenant_owner`=Yönet · `tenant_admin`=Yönet · `security_compliance_officer`=— · `billing_viewer`=— ·
`api_developer`=Görüntüle. UI yalnız görsel kapı; nihai yetki backend'de (12.2.x, SAD §14.4.1 A8) + RLS.
"Yeni trunk / Numara ekle / Caller ID ekle" aksiyonları görsel kapıdır; numara tahsisi/atama + trunk açma
istemci submit + backend zorlama 12.2.x'te. Bu katmanda numara tahsisi/atama kararı **yok**.

## Doğrulama
```
python3 t04_numbers_probe.py validate   # ON-DISK invariant S1..S8
python3 t04_numbers_probe.py check      # saf çekirdek senaryo + samples
python3 t04_numbers_probe.py selftest   # pozitif/negatif kendi-testi
python3 tests/t04_numbers_test.py       # üç kapı çıkış-kodu davranış testi
bash run_live_test.sh                     # canlı smoke (next build+start+curl; credential-free)
```

## Kapsam dışı (bilinçli)
Gerçek Telephony/Number Manager + SBC/trunk envanteri API bağlama → F2 §14.1; numara tahsisi/atama +
trunk/BYOC yapılandırma istemci submit + backend zorlama → 12.2.x; canlı çağrı/medya (DTMF/transfer) → data
plane (Conversation Orchestrator); diğer L1 ekranları T-05..T-09 → 13.3.5+. Vendor-neutral (ADR-002;
belirli operatör/SaaS bağlanmaz — BYOC dahil); sır/credential repoya yazılmaz.
