# P-06 — Global Politika & Guardrails (WBS 13.2.6)

L0 Platform Admin Console'un altıncı ekranı. **Global güvenlik politikaları** (Policy Engine
guardrail'leri), **model allowlist** ve **varsayılan compliance profilleri**ni gösterir (BRD §17.3).
Bunlar tüm tenant'lara miras kalan **platform varsayılanları**dır. Kaynak doğruluk Policy Engine
(SAD §6.2/§9.3 input/output guard; FR-LLM-006 system prompt kilidi, FR-LLM-007 prompt-injection/jailbreak,
FR-LLM-009 output guard, FR-REC-004 PII redaction, FR-KB-007 anti-hallucination) + Model Router allowlist
(FR-LLM-001/002 çoklu model, FR-LLM-011 versiyon, FR-LLM-012 no-train) + Compliance Profile motoru
(BRD §14.4 / DPIA `cp.*` most-restrictive-wins; FR-IAM-010 regüle tenant onayı).

## Altın kural (BRD §17.7 / FR-IAM-008)
P-06 **yalnız platform-geneli politika/guardrail/model-allowlist + varsayılan compliance-profile
metadatası** gösterir. Tenant **iş içeriği** (çağrı kaydı, transkript, son-müşteri/PII) **gösterilmez**.
Veri katmanı (`lib/platform/policy.ts`) tipleri yapısal olarak iş-içeriği taşımaz ve `assertNoPii`
çalışma-anında doğrular (sızıntı → hata). NOT: `appliedTenants` (profilin uygulandığı tenant **sayısı**)
toplulaştırılmıştır (izinli); tenant kimliği/listesi/iş içeriği bu ekranda yer almaz.

## RBAC (BRD §17.6)
`platform_owner`=**Yönet** · `platform_sre`=**Görüntüle** · `platform_billing`=**erişim yok**. UI yalnız
görsel kapı; nihai yetki + politika **zorlaması** backend Policy Engine'de (12.2.x; permission-key
`policy:read` + `policy:guardrail:manage` + `policy:model_allowlist:manage` +
`policy:compliance_profile:manage`, SAD §7 · §14.4.1 A8). Bu katmanda rol→permission kararı **yok**.

## Bileşenler
- `app/(platform)/policy/page.tsx` — ekran (RSC, async). Tasarım sistemi (`lib/ui`) + i18n (`lib/i18n`) +
  veri seam (`lib/platform/policy`). Tüm metin `screen.p06.*` katalogundan (t()). Bölümler: özet KPI
  (etkin guardrail, izinli model, aktif profil, kapsanan tenant, no-train ihlali, politika boşluğu),
  politika boşluğu + no-train ihlali uyarıları, global güvenlik politikaları (guardrail tablosu: kategori +
  zorlama + durum + zorunluluk + FR), model allowlist (kategori + tier + durum + no-train + versiyon +
  bölge), varsayılan compliance profilleri (ülke + sektör + residency + saklama + tenant onayı + override +
  tenant sayısı + durum).
- `lib/platform/policy.ts` — vendor-neutral veri **seam** + saf türetme yardımcıları
  (`enforcementTone`/`guardrailTone`/`modelStatusTone`/`profileStatusTone`/`countEnabledGuardrails`/
  `mandatoryGuardrailCount`/`policyGaps`/`noTrainViolations`/`countByModelStatus`/`allowedModelCount`/
  `activeProfileCount`/`coveredTenants`) + `assertNoPii` guard. Yer tutucu deterministik snapshot; gerçek
  kaynak F2 §14.1'de Policy Engine + Model Router + Compliance Profile motorundan beslenir.
- `i18n` (`screen.p06.*`) — TR/EN, design-system canonical katalogda; her iki app'e vendored (hash-eşit).

## Türetme / eşikler
- **Guardrail tonu** (`guardrailTone`): zorunlu+kapalı → danger (politika boşluğu) · kapalı → neutral · açık → success.
- **Zorlama tonu** (`enforcementTone`): block/redact → success · flag → warning · off → neutral.
- **Politika boşluğu** (`policyGaps`): zorunlu (`mandatory`) ama kapalı (`disabled`) guardrail'ler (FR-LLM-006/007/009, FR-REC-004).
- **No-train ihlali** (`noTrainViolations`, FR-LLM-012): yasak OLMAYAN ama `noTrainDefault=false` modeller.
- **Model durumu tonu** (`modelStatusTone`): allowed success · restricted warning · blocked neutral (bilinçli yasak).
- **Kapsanan tenant** (`coveredTenants`): tüm profillerin `appliedTenants` toplamı (toplulaştırılmış).

## Doğrulama
```
python3 p06_policy_probe.py validate   # ON-DISK invariant S1..S8
python3 p06_policy_probe.py check      # saf çekirdek senaryo + samples (gap + no-train + sayım)
python3 p06_policy_probe.py selftest   # pozitif/negatif kendi-testi
python3 tests/p06_policy_test.py        # üç kapı çıkış-kodu davranış testi
bash run_live_test.sh                    # canlı smoke (next build+start+curl; credential-free)
```

## Kapsam dışı (sonraki dilimler)
Gerçek Policy Engine / Model Router / Compliance Profile API bağlama (F2 §14.1); guardrail/model-allowlist/
compliance-profile düzenleme form istemci submit + backend zorlama (12.2.x); diğer L0 ekranları P-07..P-09
(13.2.7+); tenant tarafı compliance & retention T-06 (13.3.6); PII maskeleme yardımcıları 13.1.4; canlı
prompt-injection/jailbreak guard davranışı (F1 voice runtime). Vendor-neutral (ADR-002; somut sağlayıcı/
model markası bağlanmaz); sır/credential yok.
