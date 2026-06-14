# Prompt Manager — Versiyonlu Sabit System Prompt Enjeksiyonu (WBS 3.2.3)

> **Faz:** F1 · **Öncelik:** Must · **İz:** FR-LLM-006, FR-AGT-004, FR-LLM-011 · SAD §6.2/§9.3
> Kaynak doğruluk: `docs/SAD.md` (§6.2/§9.3), `docs/BRD.md` (§16 (7), §15), `docs/SRS.md` (SR-LLM-006),
> `docs/DB.md` (§5.2 `prompt`). Çelişkide dokümanlar esastır.

## 1. Amaç ve mimari konum

SAD §6.2 Prompt Manager'ı tanımlar: *"**Versiyonlu system prompt** + flow node'ları enjekte eder.
**System prompt değişmezdir; kullanıcı içeriği prompt'u değiştiremez (FR-LLM-006)**."*

Prompt Manager, Conversation Orchestrator oturum aktöründe (SAD §6.3) **THINK** durumunda (SAD §6.1)
— final transcript sonrası, **LLM Router çağrısından önce** — çalışır: system prompt + konuşma
segmentlerini **yetki-katmanlı** ve **sıralı** bir LLM prompt'una montajlar. İki sorumluluk:

1. **Versiyonlu enjeksiyon (P1/P8, FR-AGT-004/FR-LLM-011):** System prompt çağrı/oturum başında bir
   **yayımlanmış** (`is_published=true`) prompt versiyonuna (`prompt.version_no` — DB 1.1.2) sabitlenir
   (`pin_scope=session_start`) ve çağrı boyunca **drift etmez** — oturum içinde yeni bir versiyon
   yayımlanması **uçuştaki** çağrıyı etkilemez (tutarlılık). Kullanılan versiyon çağrı kaydına yazılır
   (FR-LLM-011 *"kullanılan versiyon çağrı bazında kaydedilir"*).
2. **Değişmezlik (P2/P3/P4, FR-LLM-006):** Montajlanan system segmenti yayımlanmış gövdeyle
   **bayt-bayt** aynıdır. Kullanıcı konuşması (`caller`) veya bilgi tabanı/RAG (`kb_retrieval`) içeriği
   system prompt'u **değiştiremez**: ayrı, **çitlenmiş**, daha düşük yetkili segmentlerde taşınır.

## 2. Kapsam ayrımı (seam'leri tüketir, motorları uygulamaz)

| Konu | Nereye |
|------|--------|
| Prompt-injection/jailbreak **semantik** tespiti | **3.3.1/3.3.2** (FR-LLM-007/009; Prompt Manager yalnız **yapısal** sınır/çit) |
| Prompt **editörü** + versiyon oluşturma/yayımlama | **A-06 Prompt Editor / API** (`POST /agents/{id}/prompts`, FR-AGT-004) |
| Prompt **depolama** + WORM | **DB 1.1.2** (`prompt`, `UNIQUE(tenant,agent,version_no)`, `is_published`) |
| Single-prompt vs node/flow **modeli** + flow node yürütme | **3.2.4** (FR-AGT-003) |
| Konuşma geçmişi **penceresi** + özet (history segmenti) | **3.2.1** (window) + **3.2.2** (rolling summary) — tüketilir |
| LLM tiering / routing / semantic-cache | **SAD §9 LLM Router** |
| Gerçek tokenizer / token sayımı | adapter arkasında (motor `approx_tokens` + opak hash kullanır) |
| PII redaction L7 motoru | **3.3.x** |

Bu görev **yalnız** enjeksiyon/montaj **modelini** + system-prompt değişmezlik **sözleşmesini** +
deterministik bir referans montajcıyı üretir. 3.2.1/3.2.2/3.1.4/3.1.5 ile aynı `runtime/` disiplini:
**vendor-neutral** (ADR-002), **credential-free**, **stdlib-only**, **deterministik** (olay-tetikli,
sanal saat, random YOK; gerçek LLM çağrısı yok — segment montaj + hash modeli).

## 3. Yetki katmanları (trust layering)

Montajlanan prompt SABİT yetki önceliğinde dizilir; **system her zaman ilk/en yüksek**:

| Öncelik | Rol | Kaynak | Güven |
|---------|-----|--------|-------|
| 0 | `system` | `prompt_registry` (pin'lenmiş versiyon) | **EN YÜKSEK — değişmez** |
| 1 | `policy` | `policy_registry` (Policy Engine, BRD §13) | yüksek |
| 2 | `history` | `session_memory` (3.2.1 window + 3.2.2 summary) | orta |
| 3 | `kb_context` | `kb_retrieval` (RAG, FR-KB) | **düşük (çitlenmiş)** |
| 4 | `user_turn` | `caller` (geçerli kullanıcı turn'ü) | **EN DÜŞÜK (çitlenmiş)** |

`untrusted = {caller, kb_retrieval}`. İki yapısal kural:
- **P3 — rol ayrımı:** untrusted içerik **asla** `system` rolüne girmez (`content_in_system_role=0`).
- **P4 — çit:** untrusted içerikteki override/jailbreak ("önceki talimatları yok say", sahte system
  işareti) **yapısal olarak** system'e uygulanmaz (`override_applied=0`). **Semantik** tespit/bloklama
  Policy Engine input guard'ındadır (3.3.1/FR-LLM-007); Prompt Manager sınırı **yapı** ile kurar.

## 4. Değişmezlik modeli (FR-LLM-006'nın kalbi)

`assembled_system_hash == pinned_system_hash` her assemble'de. Untrusted içerik system **gövdesine**
birleştirilmez (`system_mutated=0`). SR-LLM-006 doğrulama yöntemi (T): *"Prompt-override denemesi
system prompt'u değiştirmez."* Naif bir uygulama kullanıcı/KB metnini system mesajına ekleyerek
prompt-injection'a kapı açar — bu motor bunu **yapısal** olarak imkânsız kılar (degraded örnek
`immutable_system=false` ile ihlali kanıtlar: hash sapar + override uygulanır).

Sistem prompt'u **kuratörlüdür** (operatör/designer tasarlar, A-06) — kullanıcı PII'si içermez. Kart/
parola/OTP düz-metin system segmentine **hiç** girmez (caller/KB system'e birleşemediği için yapısal
olarak da imkânsız). Düşük-güven segmentler PII içerebilir; durable kayıt `redaction_state='pending'`
(FR-REC-004, L7 motoru 3.3.x) — prompt montaj katmanı içeriği **yorumlamaz**.

## 5. HARD kapılar (P1–P8)

| Kapı | İnvariant | Metrik ölçütü |
|------|-----------|---------------|
| **P1** | Versiyon sabitleme | `version_drift=0` + `pinned` (FR-AGT-004/FR-LLM-011) |
| **P2** | System değişmezliği | `system_mutated=0` + `assembled==pinned` hash (FR-LLM-006) |
| **P3** | Trust layering | `content_in_system_role=0` |
| **P4** | Override çiti | `override_applied=0` (yapısal; `override_seen` sayılır) |
| **P5** | Yetki sırası | `order_violation=0` (system önce/en yüksek) |
| **P6** | İdempotent/deterministik | `duplicate_system=0` + `out_of_order=0` |
| **P7** | Tenant/agent izolasyon | `cross_tenant=0` (FR-TEN-002 / RLS 1.1.2) |
| **P8** | Yayımlanmış-yalnız + kayıt | `unpublished_injected=0` + `version_recorded` (fail-closed) |

`P9` (komşu seam tüketimi) ve `P10` (residency/ErrorTaxonomy/sır+PII yok) katalog invariant'ları
`validate` ile zorlanır. Yayımlanmamış/eksik versiyon **fail-closed** HATA'dır (kullanıcı içeriğine
**fallback yok**; registry-down → `UNAVAILABLE`, system uydurulmaz — API §11.6).

## 6. Montajcı modeli (referans)

`prompt_manager_probe.py` deterministik bir `PromptManager` simülatörüdür: olay-akışını işler
(`pin` → `segment*` → `assemble` → … → `end`). Gerçek LLM/registry/tokenizer yerine **segment montaj +
opak hash** modeli; canlı sistemde Go/Rust runtime (ADR-003, SAD §6.3) + gerçek prompt registry
(DB 1.1.2, home-region) + LlmAdapter (SAD §9) ile koşar.

```
validate   spec → P1–P10 + config profilleri
simulate   olay-akışı → pin/segment/assemble metrikleri → P1–P8 → çıkış kodu
selftest   iyi/kötü spec+sample negatif kapı kanıtı (izole degrade'ler P2/P3/P4/P5/P1/P7/P8)
schema     beklenen spec şekli
```

## 7. İzlenebilirlik

| Gereksinim | SR | TC | WBS |
|-----------|----|----|-----|
| FR-LLM-006 (system prompt değiştirilemez) | SR-LLM-006 | TC-LLM-006 (T) | **3.2.3** |
| FR-AGT-004 (prompt versiyonlanır) | — (SAD §6.2) | — | 3.2.3 / 1.1.2 |
| FR-LLM-011 (kullanılan versiyon kaydedilir) | — | — | 3.2.3 |
| FR-LLM-007 (injection guard — **sınır**) | SR-LLM-007 | TC-LLM-007 | **3.3.1** |

RTM'de `FR-LLM-006 | SR-LLM-006 | TC-LLM-006 (T) | 3.2.3` zaten eşli — SRS/RTM değişikliği gerekmedi.
ADR-001 (bağımsız Orchestrator), ADR-002 (vendor-neutral), ADR-003 (Go/Rust runtime). Metrikler
gözlemlenebilirliğe (0.4.7) yayılır; `system_prompt_immutable_violations_total` bir **alarm** sinyalidir
(FR-LLM-006 ihlali = güvenlik olayı).
