# T-08 — Audit Log (tenant) · WBS 13.3.8

L1 Tenant Admin Console'un sekizinci ekranı (T-01..T-09). Tenant'ın **kendi** kullanıcı/sistem
değişiklik ve erişim kayıtlarını (audit log) gösterir: özet (KPI), bütünlük & saklama (WORM + hash
zinciri + dış mühürleme), kategori dağılımı, break-glass erişimleri ve audit kayıt tablosu.

## Kaynak gereksinimler
- **FR-IAM-006** — Kullanıcı işlemleri değiştirilemez (WORM) audit log'a kaydedilmelidir.
- **FR-REC-009** — Kayıt/transkript erişimleri audit edilmelidir (`data_access` kategorisi).
- **FR-IAM-009** — Break-glass: platform (L0) iş içeriğine açık gerekçeli, süreli, audit'li erişim.
- **FR-TEN-002** — Tenant scope: yalnız kendi tenant'ın audit kayıtları (RLS + middleware).
- **ADR-016** — Hash zinciri + dış mühürleme tamper-evidence; **DB §6.5** WORM zorlama.
- **BRD §17.6** RBAC · **§17.7** hijyen + PII redaction · **NFR 10.6** sır.

## RBAC (BRD §17.6)
`tenant_owner`=Yönet · `tenant_admin`=Görüntüle · `security_compliance_officer`=Yönet ·
`billing_viewer`=— · `api_developer`=—. UI yalnız görsel kapı; nihai yetki backend'de (12.2.x) + RLS.
Permission-key: `tenant:audit:read` (SAD §17.2). Kayıtlar **değiştirilemez/WORM** — panelde yazma/silme
**yok**; "Yönet" = dışa aktarma + bütünlük doğrulama + gelişmiş filtre/inceleme.

## Çekirdek altın kural — hijyen + güvenlik
Audit görünümü **yalnız META veridir** (aktör · eylem · kaynak REFERANSI · zaman · bütünlük hash'i).
Ham son-müşteri iş içeriği (çağrı kaydı/transkript/ses, müşteri PII/numarası, kart/CVV) audit görünümüne
**gömülmez**; kaynak yalnız UUID/handle ile referans edilir. `getAudit` her dönüşte `assertNoPii` çağırır
→ `FORBIDDEN_PII_KEYS` (transcript/recording/msisdn/customer/cdr/...) **ve** `FORBIDDEN_SECRET_KEYS`
(secret/apiKey/token/privateKey/kmsKey/...) taraması → ihlalde hata. Bütünlük hash'leri yalnız **HEX
önekidir** — sır değildir. Aktör kimliği (tenant-içi kullanıcı) L1'de izinlidir.

## Dosyalar
- `app/(tenant-admin)/admin/audit/page.tsx` — ekran (RSC, async). Tasarım sistemi + i18n + veri seam.
- `lib/tenant/audit.ts` — vendor-neutral veri **seam** + saf türetme yardımcıları + `assertNoPii`.
- `lib/i18n/{tr,en}.json` — `screen.t08.*` (3 app'e vendored, hash-eşit; TR↔EN parity).
- `t08-audit-spec.json` — S1..S8 invariant + referans anahtar + placeholder.
- `t08_audit_probe.py` — stdlib-only `validate`/`check`/`selftest`/`schema` (TS saf yardımcı Python aynası).
- `samples/audit-{clean,issues}.json` · `tests/t08_audit_test.py` · `run_live_test.sh`.

## Saf türetme yardımcıları (deterministik, Python aynalı)
`chainBreaks` (hash zinciri kopukluğu = tamper-evidence) · `chainIntact` · `breakGlassEntries` ·
`dataAccessEntries` · `platformEntries` · `platformWithoutBreakGlass` (FR-IAM-009 ihlali) ·
`failedEntries` · `deniedEntries` · `categoryCounts` · `outcomeCounts` · `wormDisabled` ·
`externalSealDisabled` · `retentionUnset` · `applyFilter` (realm/kategori/sonuç/break-glass/serbest metin) ·
`openWarningCount`. Tonlar: `outcomeTone`/`realmTone`/`categoryTone`/`breakGlassTone`/`chainTone`/
`wormTone`/`sealTone`.

## Doğrulama
```
python3 t08_audit_probe.py validate    # ON-DISK S1..S8 (67/67)
python3 t08_audit_probe.py check       # saf senaryo + samples (52/52)
python3 t08_audit_probe.py selftest    # pozitif/negatif (22/22)
python3 tests/t08_audit_test.py        # üç kapı çıkış kodu (3/3)
PORT=3209 ./run_live_test.sh           # next build+start+curl (credential-free)
```

## Kapsam dışı (bilinçli)
Gerçek audit servisi + WORM store + dış mühürleme (ADR-016) bağlama → F2; canlı dışa aktarma + gelişmiş
filtre submit + backend zorlama (`tenant:audit:read`) → 12.2.x; kriptografik içerik-hash doğrulaması +
break-glass akışı (maker-checker) → ilgili servisler; platform-geneli audit (P-07) → L0. SRS/RTM
değişmedi (FR-IAM-006/FR-REC-009/FR-IAM-009 mevcut; BRD §17.3 ekran implementasyonu). Sır repoya yazılmadı.
