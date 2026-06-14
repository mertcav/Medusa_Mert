# WBS 6.1.4 — Doküman bazında erişim yetkisi (metadata)

> **Faz** F1 · **Öncelik** Must · **İz** FR-KB-005 (→FR-KB-004/006/010, FR-TEN-002, FR-IAM-006, NFR 10.7)
> **Kaynak doğruluk** `access-control-spec.json`. Çelişkide `docs/BRD.md` / `docs/SAD.md` esastır.

## 1. Amaç ve konum

Bilgi Tabanı & RAG **retrieval** sınırındaki (SAD §10.2, online/hot-path) **erişim ENFORCEMENT** kapısı.
6.1.3 (parse→chunk→embed→index) her chunk'a erişim metadata'sını **taşır** (`classification` + `acl_ref` +
`sensitive` + `redaction_state` — index pipeline C9); 6.1.4 bu metadata'yı **tüketir** ve bir retrieval
isteğinin principal bağlamına göre hangi chunk'ın **dönebileceğine** karar verir.

```
Soru ─► embed ─► vector search (top-k) ─►[ 6.1.4 ACCESS GATE ]─► rerank/trim ─► LLM context (kaynak atıflı)
                       │                          │
              (1) STORE PRE-FİLTRE        (2) AUTHORITATIVE POST-FİLTRE
              namespace+class+ACL         dönen her chunk yeniden karar
              yüklemi push (6.2.1)        (store filtresine güvenilmez)
```

**Chunk/embed/version 6.1.4'te YAPILMAZ** — 6.1.3 IndexPipeline'ın ürettiği `IndexedChunk` **tüketilir**
(referans probe `index_pipeline_probe`'u **import eder**, o da `ingest_connector_probe`'u import eder; kod
tekrarı yok). FR-KB-005'in çekirdek değeri: *"Doküman bazında erişim yetkisi uygulanmalıdır."* SR-KB-005:
*"Doküman bazında erişim yetkisi uygulanır."* → **TC-KB-005 (T): "Yetkisiz dokümandan retrieval sonucu
dönmez."** — bu modülün başlık kanıtı.

**DENY-BY-DEFAULT / fail-closed:** bağlam eksik, ACL eşleşmiyor, classification clearance'ı aşıyor,
namespace uyuşmuyor veya metadata bozuksa chunk **dönmez**.

## 2. Karar bağlamı ve metadata (vendor-neutral, ADR-001/002)

| Girdi | İçerik |
|-------|--------|
| **PrincipalContext** | `tenant_id` (zorunlu), `kb_ids[]` (erişilebilir namespace'ler), `principals[]` (`role:`/`group:`/`agent:`/`user:` token'ları), `clearance` (lattice), `channel_no_log?`, `agent_id?`, `purpose?`. Canlı çağrının agent/oturum bağlamından + RBAC'tan (ADR-012) türetilir. |
| **IndexedChunk** (6.1.3) | `namespace`, `tenant_id`, `kb_id`, `document_id`, `active`, `classification`, `acl_ref`, `sensitive`, `redaction_state`, `content`. |
| **ACL** (`acl_ref` çözülür) | `{default:'deny'/'allow', allow:[token], deny:[token]}`. **deny WINS**. |

Karar **yalnız** bağlam + chunk metadata'sından verilir — **sağlayıcıdan bağımsız** (ADR-001/002). Bu modül
RBAC rol bundle'larını (ADR-012) principal token olarak **tüketir**; permission-builder değildir.

## 3. Karar algoritması (sıralı, fail-closed)

| # | Adım | Reddederse |
|---|------|-----------|
| 1 | Bağlam tam mı (`tenant_id`/`kb_ids`/`principals`/`clearance`) | `MISSING_PRINCIPAL_CONTEXT` |
| 2 | `chunk.tenant_id == ctx.tenant_id` | `CROSS_NAMESPACE` (FR-TEN-002) |
| 3 | `chunk.kb_id ∈ ctx.kb_ids` | `CROSS_NAMESPACE` (FR-KB-004) |
| 4 | `chunk.active` (yalnız aktif sürüm) | `INACTIVE_VERSION` (6.1.3 C8) |
| 5 | `rank(classification) ≤ rank(clearance)` | `CLASSIFICATION_EXCEEDS_CLEARANCE` |
| 6 | ACL çözümleme | `MALFORMED_ACL` / `ACL_REQUIRED` / `ACL_EXPLICIT_DENY` / `ACL_NOT_GRANTED` |
| 7 | `sensitive ⇒ ctx.channel_no_log` | `SENSITIVE_REQUIRES_NO_LOG` (FR-KB-010) |
| 8 | redaction (`pending` → redact/deny) | `REDACTION_PENDING` (deny modu) |

Sonuç: **`ALLOWED`** · **`ALLOWED_REDACTED`** (8'de maskelendi). Lattice: `public < internal < confidential <
restricted`; bilinmeyen sınıf → rank yüksek → fail-closed deny. Karar **ucuz** (metadata-only; embedding/ağ
yok) → hot-path gecikme bütçesine (SAD §20) anlamlı ek yüklemez.

## 4. İki uygulama noktası (defense-in-depth)

1. **STORE PRE-FİLTRE** — `predicate(ctx) = {namespaces, classification_in, acl_tokens, active}` vector
   search query'sine push edilir (6.2.1; vendor-eval 0.2.5 C4 metadata-ACL + 1.1.7 RLS). Yetkisiz aday
   **hiç çekilmez** (performans + sızıntı önleme).
2. **AUTHORITATIVE POST-FİLTRE** — dönen her chunk **karar algoritmasından yeniden** geçer; store filtresine
   **asla güvenilmez**.

**G8 PARİTE:** pre-filtre post-filtreye göre **SOUND** (admit ettiği her chunk namespace+classification+ACL
boyutunu da geçer — yetkisiz admit etmez) + **COMPLETE** (kararın `ALLOW`/`ALLOWED_REDACTED` verdiği her
chunk admit edilir — yetkili düşürülmez). `sensitive`/redaction içerik-bağımlı → yalnız post-filtrede.

## 5. Redaction & audit

- **redaction_state** (6.1.3 C9 taşıdı): `not_required`/`applied` → içerik döner; `pending` → `redact`
  modunda dönmeden önce **deterministik maskeleme** (uzun rakam → `[REDACTED-NUM]`, e-posta →
  `[REDACTED-EMAIL]`) + `ALLOWED_REDACTED`, `deny` modunda `REDACTION_PENDING`. **Ham hassas PII asla
  maskelenmeden dönmez** (fail-closed).
- **Audit (G9):** her karar (allow+deny) yapısal kayıt üretir `{ts, tenant_id, kb_id, document_id, chunk_id,
  decision, reason, classification, sensitive, principal_digest}`. **Ham içerik / ham PII / token ham değeri
  YAZILMAZ** (`principal_digest` sha256; BRD §17.7/FR-REC-004; 0.4.7 kardinalite/PII label politikası).

## 6. HARD kapılar (G1–G10)

| # | Kapı | Özet |
|---|------|------|
| G1 | Fail-closed / deny-by-default | yetkisiz dokümandan sonuç dönmez (SR-KB-005); bağlam eksik → deny |
| G2 | Namespace isolation | cross-tenant/cross-kb dönen chunk=0 (FR-TEN-002/FR-KB-004) |
| G3 | Classification lattice | classification>clearance → deny (monoton) |
| G4 | ACL deny-wins + default-deny | explicit deny allow'u ezer; eşleşme yok → default deny |
| G5 | Sensitive no-log | sensitive yalnız no-log kanal (FR-KB-010) |
| G6 | Redaction enforced | pending → redact-or-deny; ham hassas PII maskelenmeden dönmez |
| G7 | Active-only | yalnız aktif sürüm döner; supersede sızmaz (6.1.3 C8) |
| G8 | Prefilter parity | store pre-filtre sound+complete (post-filtre authoritative) |
| G9 | Decision auditable | yapısal reason + audit; ham içerik/PII audit'e girmez |
| G10 | Robust + scope boundary | bozuk metadata fail-closed deny (crash yok); kapsam sınırı |

## 7. Karar taksonomisi

**ALLOW:** `ALLOWED` · `ALLOWED_REDACTED`.
**DENY:** `MISSING_PRINCIPAL_CONTEXT` · `CROSS_NAMESPACE` · `INACTIVE_VERSION` ·
`CLASSIFICATION_EXCEEDS_CLEARANCE` · `ACL_REQUIRED` · `ACL_NOT_GRANTED` · `ACL_EXPLICIT_DENY` ·
`MALFORMED_ACL` · `SENSITIVE_REQUIRES_NO_LOG` · `REDACTION_PENDING`. Deterministik + müşteriye sızmaz.

## 8. Kapsam sınırı (bilinçli, G10)

| Konu | Nereye |
|------|--------|
| Chunk / embed / versiyonlama | **6.1.3** (TÜKETİR, yeniden yapmaz) |
| Namespace **yazım** izolasyonu | **6.1.3 C5** / **1.1.7** RLS (6.1.4 okuma-zamanı katman ekler) |
| Retrieval / rerank / top-k | **6.2.1** (pre-filtre yüklemini tüketir) |
| Token-trim (bağlam bütçesi) | **6.2.2** (yalnız yetkili chunk girer) |
| Retrieval no-log | **6.2.4** |
| Panel/insan operatör content erişimi (Tier A/B break-glass, L0 altın kural) | **FR-IAM-008/009/010** (AYRI yüzey) |

## 9. Determinizm & güvenlik

- Sanal saat (`Date.now`/rastgele **yok**); chunk'lar 6.1.3 IndexPipeline'dan türetilir → tekrarlanabilir kapı.
- Karar her zaman **backend'de** (CLAUDE.md RBAC kuralı); istemci kararına güvenilmez.
- Sır/credential ve gerçek PII değeri **üretilmez/yazılmaz** (fixture içerikleri sentetik — FR-TST-008);
  store DSN/anahtar yalnız `${ENV}`. Chunk içeriği runtime'da PII içerebilir (meşru) → sensitive no-log
  kapısı + redaction ile korunur; audit'e ham içerik/PII yazılmaz.

## 10. İzlenebilirlik

FR-KB-005 ↔ SR-KB-005 ↔ TC-KB-005 (RTM) zaten eşli — SRS/RTM değişmedi. Gözlemlenebilirlik (0.4.7):
`kb_access_decisions_total{decision,reason}` / `kb_access_denied_total{reason}` /
`kb_access_redacted_total` / `kb_access_sensitive_total{channel}` (tenant_id/doc_id/kb_id/principal yüksek
kardinalite → yalnız trace/exemplar/audit; PII label **yasak**, BRD §15/§17.7).
