# P-09 — Alarm & Incident (SRE) (WBS 13.2.9)

L0 Platform Admin Console'un dokuzuncu (ve son) ekranı. **Platform alarmları** (kritik alarm kataloğu,
BRD §15 / SAD §17.2) ve **incident (SRE) yönetimi** gösterir (BRD §17.3 P-09). Kaynak doğruluk 0.4.7
gözlemlenebilirlik omurgası (alarm kuralları, SAD §17.2 detection_budget_s ≤120s) + incident yönetim/on-call
servisidir. Kritik alarm üretim gecikmesi ≤ 2 dk = 120 sn (NFR 10.1 / SR-PERF-008); incident response
prosedürü + IR runbook (NFR 10.6 / SR-SEC-008).

## Altın kural (BRD §17.7 / FR-IAM-008)
P-09 **yalnız platform-geneli alarm/incident metadatası** gösterir. Tenant **iş içeriği** (çağrı kaydı,
transkript, son-müşteri/PII) **gösterilmez**; `platform_sre` iş içeriği görmez (BRD §17.2). Veri katmanı
(`lib/platform/incidents.ts`) tipleri yapısal olarak iş-içeriği taşımaz ve `assertNoPii` çalışma-anında
doğrular (sızıntı → hata). NOT: alarm/incident `scope` alanı **vendor-nötr bileşen/bölgedir** (ör.
`orchestrator/EU`) — tenant kimliği/listesi değildir. On-call `assigneeRole` bir **ROL'dür** (kişi/PII değil).

## RBAC (BRD §17.6)
`platform_owner`=**Yönet** · `platform_sre`=**Yönet** · `platform_billing`=**erişim yok**. UI yalnız görsel
kapı; nihai yetki + alarm sustur / incident ata / onayla (acknowledge) / çöz **zorlaması** backend'de
(12.2.x; permission-key `alert:read` + `alert:manage` + `incident:read` + `incident:manage` +
`incident:acknowledge`, SAD §7 · §17.2 `incident:manage` · §14.4.1 A8). Bu katmanda rol→permission kararı
**yok**. Tüm alarm/incident işlemleri audit edilir (P-07).

## Bileşenler
- `app/(platform)/incidents/page.tsx` — ekran (RSC, async). Tasarım sistemi (`lib/ui`) + i18n (`lib/i18n`) +
  veri seam (`lib/platform/incidents`). Tüm metin `screen.p09.*` katalogundan (t()). Bölümler: özet KPI
  (toplam alarm, aktif firing, açık incident, kritik açık incident, onay bekleyen alarm, bütçe aşan alarm),
  aktif alarm + bütçe ihlali + kritik açık incident + eskalasyon uyarıları, platform alarmları (kural adı +
  önem + sinyal + kapsam + durum + üretim gecikmesi + tetiklenme), incident'ler (etiket + önem + durum +
  on-call rolü + ilişkili alarm + kapsam + açılış), incident olay akışı (zaman + tip + aktör + hedef +
  gereksinim).
- `lib/platform/incidents.ts` — vendor-neutral veri **seam** + saf türetme yardımcıları (`alarmSeverityTone`/
  `alarmStateTone`/`alarmSignalTone`/`incidentSeverityTone`/`incidentStatusTone`/`incidentEventTypeTone`/
  `countBySeverity`/`firingAlarms`/`unacknowledgedAlarms`/`budgetBreaches`/`openIncidents`/
  `criticalOpenIncidents`/`escalationEvents`/`resolvedIncidents`) + `DETECTION_BUDGET_SEC` (120, NFR 10.1) +
  `assertNoPii` guard. Yer tutucu deterministik snapshot; gerçek kaynak F2 §14.1'de gözlemlenebilirlik
  omurgası + incident/on-call servisinden beslenir. Alarm/bileşen adları vendor-nötr (ADR-002).
- `i18n` (`screen.p09.*`) — TR/EN, design-system canonical katalogda; her iki app'e vendored (hash-eşit).

## Türetme / eşikler
- **Alarm durum tonu** (`alarmStateTone`): firing danger · pending warning · acknowledged info · resolved success.
- **Alarm sinyal tonu** (`alarmSignalTone`): security danger · error_rate/capacity/spend/resource warning ·
  latency info.
- **Aktif alarm** (`firingAlarms`): `state=firing` — anlık operasyon riski (BRD §15).
- **Onay bekleyen alarm** (`unacknowledgedAlarms`): `state in {firing, pending}` — SRE müdahalesi gerekir.
- **Bütçe aşan alarm** (`budgetBreaches`, NFR 10.1 / SR-PERF-008): `detectionLatencySec > 120` — kritik alarm
  ≤ 2 dk hedefi ihlali.
- **Açık incident** (`openIncidents`): `status != resolved`.
- **Kritik açık incident** (`criticalOpenIncidents`, NFR 10.6): `severity in {sev1, sev2}` & açık — öncelikli
  müdahale.
- **Eskalasyon** (`escalationEvents`): `type=escalated` — IR runbook eskalasyon adımı.

## Doğrulama
```
python3 p09_incidents_probe.py validate   # ON-DISK invariant S1..S8
python3 p09_incidents_probe.py check      # saf çekirdek senaryo + samples (alarm + bütçe + incident + eskalasyon)
python3 p09_incidents_probe.py selftest   # pozitif/negatif kendi-testi
python3 tests/p09_incidents_test.py        # üç kapı çıkış-kodu davranış testi
bash run_live_test.sh                       # canlı smoke (next build+start+curl; credential-free)
```

## Kapsam dışı (sonraki dilimler)
Gerçek gözlemlenebilirlik omurgası alarm kuralı + incident/on-call servisi API bağlama (F2 §14.1); alarm
sustur / incident ata / onayla / çöz form istemci submit + backend zorlama (12.2.x); alarm kuralı CRUD +
eşik yapılandırma (0.4.7 observability-spec.json kaynak doğruluk). P-09 L0 Platform Admin Console'un son
ekranıdır; L1 (T-01..T-09) ve L2 (A-01..A-17) ekran implementasyonları 13.3/13.4'tedir. Vendor-neutral
(ADR-002; somut sağlayıcı/APM/on-call-SaaS markası bağlanmaz); sır/credential yok.
