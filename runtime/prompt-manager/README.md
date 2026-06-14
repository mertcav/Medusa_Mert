# runtime/prompt-manager — WBS 3.2.3 Prompt Manager: versiyonlu sabit system prompt enjeksiyonu

Conversation Orchestrator (Çekirdek IP, SAD §6) oturum aktöründe (SAD §6.3) **THINK** durumunda çalışan
**Prompt Manager** alt bileşeni (SAD §6.2: *"Versiyonlu system prompt + flow node'ları enjekte eder;
System prompt değişmezdir; kullanıcı içeriği prompt'u değiştiremez — FR-LLM-006"*).

## Sorumluluk

İki çekirdek görev:

1. **Versiyonlu enjeksiyon** — system prompt çağrı başında bir **yayımlanmış** (`is_published`) prompt
   **versiyonuna** (`prompt.version_no` — DB 1.1.2 prompt tablosu, FR-AGT-004) **sabitlenir** (pin) ve
   çağrı boyunca **drift etmez**; kullanılan versiyon çağrı kaydına yazılır (FR-LLM-011).
2. **Değişmezlik (immutability)** — enjekte edilen system segmenti yayımlanmış gövdeyle **bayt-bayt**
   aynıdır; kullanıcı konuşması (`caller`) veya bilgi tabanı/RAG (`kb_retrieval`) içeriği system
   prompt'u **değiştiremez** (FR-LLM-006). Düşük-güven içerik **ayrı, çitlenmiş**, daha düşük yetkili
   segmentlerde taşınır; **asla** system rolüne sızdırılmaz.

## HARD kapılar (P1–P8)

| Kapı | İnvariant | Ölçüt |
|------|-----------|-------|
| **P1** | Versiyon sabitleme | `version_drift=0` + `pinned` (çağrı başı pin, drift yok — FR-AGT-004/FR-LLM-011) |
| **P2** | System değişmezliği | `system_mutated=0` + `assembled==pinned` hash (**FR-LLM-006'nın kalbi**) |
| **P3** | Trust layering | `content_in_system_role=0` (caller/KB system rolünde değil) |
| **P4** | Override çiti | `override_applied=0` (yapısal; semantik tespit → 3.3.1/FR-LLM-007) |
| **P5** | Yetki sırası | `order_violation=0` (system önce/en yüksek) |
| **P6** | İdempotent/deterministik | `duplicate_system=0` + `out_of_order=0` |
| **P7** | Tenant/agent izolasyon | `cross_tenant=0` (FR-TEN-002 / RLS 1.1.2) |
| **P8** | Yayımlanmış-yalnız + kayıt | `unpublished_injected=0` + `version_recorded` (fail-closed; FR-LLM-011) |

## Yetki katmanları (precedence)

```
system(0)  ← registry kaynaklı SABİT system prompt (en yüksek yetki, DEĞİŞMEZ — pin)
policy(1)  ← Policy Engine kuralları (deterministik, BRD §13)
history(2) ← session memory (3.2.1 window + 3.2.2 rolling summary)   ┐ TÜKETİLİR
kb_context(3) ← RAG retrieval (FR-KB; ÇİTLENMİŞ, düşük güven)         │ (üretilmez)
user_turn(4)  ← geçerli kullanıcı turn'ü (caller; EN DÜŞÜK güven)     ┘
```

`untrusted = {caller, kb_retrieval}`: içerikleri **asla** system rolüne girmez (P3) + içlerindeki
override/talimat **yapısal** olarak system'e uygulanmaz (P4).

## Dosyalar

```
prompt-manager-spec.json               # kaynak doğruluk (P1–P10 invariant)
prompt-manager.md                      # tasarım dokümanı
prompt_manager_probe.py                # validate / simulate / selftest / schema (deterministik)
config/prompt-manager-profiles.json    # 3 profil (pilot / enterprise-rich / high-density)
samples/
  pm-happy-path.json                   # versiyon pin + katmanlı montaj
  pm-version-pinned.json               # çok turlu çağrı, aynı versiyon (drift=0)
  pm-override-fenced.json              # injection girişimi çitlenir → system değişmez
  pm-kb-sensitive-fenced.json          # hassas içerik düşük-güven segmentte, system'e girmez
  pm-degraded.json                     # bilinçli bozuk: caller/KB system'e birleşir → P2/P3/P4 eler
tests/prompt_manager_behavior_test.py  # T1–T8 davranış kapısı
run_live_test.sh                       # statik + sample (+ canlı NOT)
```

## Çalıştırma

```bash
python3 prompt_manager_probe.py validate          # spec → P1–P10 + config
python3 prompt_manager_probe.py selftest          # iyi/kötü spec+sample negatif kapı kanıtı
python3 prompt_manager_probe.py simulate samples/pm-override-fenced.json
python3 tests/prompt_manager_behavior_test.py     # T1–T8
bash run_live_test.sh                             # hepsi + canlı NOT/SKIP
```

## Kapsam ayrımı (seam'leri tüketir, motorları uygulamaz)

| Konu | Nereye |
|------|--------|
| Prompt-injection/jailbreak **semantik** tespiti (input/output guard) | **3.3.1 / 3.3.2** (FR-LLM-007/009; bu motor yalnız **yapısal** sınır) |
| Prompt **editörü** + versiyon oluşturma/yayımlama | **A-06 Prompt Editor / API** (`POST /agents/{id}/prompts`, FR-AGT-004) |
| Prompt **depolama** + WORM değişmezliği | **DB 1.1.2** (`prompt` tablosu, `UNIQUE(tenant,agent,version_no)`) |
| Single-prompt vs node/flow **modeli** + flow node yürütme | **3.2.4** (FR-AGT-003) |
| Konuşma geçmişi **penceresi** + özet (history segmenti) | **3.2.1** (window) + **3.2.2** (rolling summary) — tüketilir |
| LLM tiering / routing / semantic-cache | **SAD §9 LLM Router** |
| Gerçek tokenizer / token sayımı | adapter arkasında (motor `approx_tokens` + opak hash kullanır) |
| PII redaction L7 motoru | **3.3.x** |

Vendor-neutral (ADR-002); deterministik (olay-tetikli, sanal saat, **random YOK**; gerçek LLM çağrısı
yok — segment montaj + hash **modeli**). Sır/credential, ham prompt/transkript **metni** ve PII
**değeri** repoya **yazılmadı** — yalnız rol/kaynak + token + opak hash + versiyon kimlikleri + sanal zaman.

```
İz: FR-LLM-006 → SR-LLM-006 → TC-LLM-006 (RTM'de WBS=3.2.3 zaten eşli) + FR-AGT-004 + FR-LLM-011 + FR-LLM-007 (sınır).
```
