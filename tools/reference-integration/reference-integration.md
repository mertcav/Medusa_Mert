# Referans Entegrasyon (pilot) — CRM / Ticketing / ERP (WBS 7.2.5)

> Kaynak doğruluk: `reference-integration-spec.json`. Çelişkide **BRD/SAD esastır**.
> İz: BRD §6.1 (CRM, contact centre, ticketing, ERP) · OBJ-07 · SAD §11.1/§11.2/§11.3 · FR-TOOL-001..012.

## Amaç ve kapsam

7.x **tool hattının pilot kapstonu**. Yeni bir transport/SPI **eklemez**; daha önce kurulan parçaları
SAD §11.1 **Tool Yürütme Hattının** ([1]→[7]) birebir sırasında **orkestre ederek** temsilci (pilot)
CRM/Ticketing/ERP sistemlerine karşı **uçtan uca gerçek işlem** (read + write) gösterir.

Bu modülün **sahiplendiği** dört şey:
1. **Referans entegrasyon paketleri** (`crm` / `ticketing` / `erp`) + agent-çağrılabilir **referans tool
   tanımları** — her biri BRD §8 iş senaryosuna eşli.
2. **Zincir sıralama + fail-closed kompozisyon** — adımlar sıra ile; ilk eleyen kapı kısa-devre yapar
   (downstream yan-etki yok); eksik/bilinmeyen karar → fail-closed **RED** (default-allow yok).
3. **Kritik-işlem policy gate bağı** (FR-TOOL-006/007) — para/sözleşme/PII değişikliği → müşteri teyidi
   ∧ step-up **zorunlu**. (Tam teyit/onay durum makinesi → 7.3.)
4. **Tool Execution audit kaydı** (BRD §16 varlık 24 / DB.md §5.5 WORM).

## Zincir (SAD §11.1) — kim sahibi, bu modül ne yapar

| Adım | İş | Sahip | Bu modül |
|------|----|-------|----------|
| [1] input schema | FR-TOOL-002 | 7.1.1 | `schema_valid` kararını tüketir; False → `rejected/SCHEMA_INVALID` |
| [2] authorization | FR-TOOL-004/005 | 7.1.2 | `granted_scopes` tüketir; `required_scope ⊆ granted`, write→write-seviye; değilse `rejected/AUTH_FAILED` |
| [3] policy gate | FR-TOOL-006/007 | 7.3 (bağ burada) | `critical` → `confirmation ∧ step_up`; değilse `blocked/CONFIRMATION_REQUIRED` |
| [4] idempotency | FR-TOOL-009 | 7.1.3 | write → `idempotency_key` varlığı zorunlu; yoksa `rejected/IDEMPOTENCY_REQUIRED` |
| [5a] allowlist | FR-TOOL-012 | 7.2.3 | PERMIT değilse `rejected/ENDPOINT_NOT_ALLOWED` (fail-closed) |
| [5b] dispatch | FR-TOOL-001/003 | 7.1.4 + 7.2.1/7.2.2 | `AttemptOutcome` tüketir → ok=`committed/succeeded`, accepted=`pending`, fault=`failed` |
| [6] output norm | FR-TOOL-008 | 7.1.1 + 7.1.5 | fault → müşteri kategorisi (DELEGE 7.1.5); teknik detay sızdırmaz |
| [7] audit | FR-TOOL-010 | 7.1.6 (kayıt burada) | correlation_id audit + Tool Execution kaydı (no-log) |

## Pilot paketleri (referans/illüstratif — host'lar example.com)

- **CRM (REST · 7.2.1)** — `get_customer`/`list_cases` (read), `create_case` (§8.4 claim→referans no),
  `log_call_outcome` (§8.1 adım 8), `update_contact` (**kritik** PII, FR-TOOL-007).
- **Ticketing (GraphQL · 7.2.2)** — `get_ticket` (read), `create_ticket` (§8.6), `add_comment`.
- **ERP (SOAP · 7.2.2)** — `get_order`/`get_invoice` (read), `create_appointment` (§8.3, **async**→7.2.4),
  `post_payment_adjustment` (**kritik** para, FR-TOOL-007; kart akışı 17.2.6 PCI).

Bu üç paket REST + GraphQL + SOAP connector tiplerinin **her birinde read+write** başarılı uçtan-uca
çağrı gösterir → **SR-TOOL-001** kabul ölçütü ("Her connector tipi başarılı çağrı yapar") + OBJ-07.

## Çekirdek invariant (SR-TOOL-001 + OBJ-07)

> *Pilot paketleri REST/GraphQL/SOAP tiplerinin her birinde başarılı uçtan-uca çağrı yapar ve
> Tool Yürütme Hattını [1]→[7] **fail-closed** yürütür.*

R1 fail-closed zincir · R2 connector-tipi kapsama · R3 read/write authz · R4 kritik policy gate ·
R5 write idempotency · R6 allowlist · R7 müşteriye teknik-detay sızmaz · R8 audit no-log ·
R9 Tool Execution kaydı · R10 determinizm · R11 pilot dürüstlüğü (vendor-neutral, sentetik) ·
R12 vendor-neutral kompozisyon.

## Kapsam dışı (bilinçli — başka modül sahibi)

schema motoru→7.1.1 · authz motoru→7.1.2 · retry/breaker→7.1.4 · kanonik istek/transport→7.2.1/7.2.2 ·
allowlist kararı→7.2.3 · idempotency üretimi→7.1.3 · müşteri hata **metni** kataloğu→7.1.5 · audit
store→7.1.6 · async reconcile→7.2.4 · kritik-işlem **tam** durum makinesi→7.3 · PCI kart akışı→17.2.6.

Vendor-neutral (ADR-001/002): pilot referans/illüstratif; **bağlayıcı vendor seçimi yok** (BRD §22 açık
karar). Sır/credential yalnız `${ENV}`; gerçek PII repoya yazılmaz.
