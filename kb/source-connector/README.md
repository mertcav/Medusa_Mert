# WBS 6.1.2 — SharePoint/Confluence connector

`F2` · `Should` · →FR-KB-002 · SR-KB-002 · SAD §10.1 · ADR-001/002

Bilgi Tabanı & RAG **offline indeksleme** hattının (SAD §10.1) ikinci aşaması: **kurumsal kaynak
connector'ı**. Kurumsal doküman sistemlerine (**SharePoint, Confluence**, genel DMS) bağlanır, kapsamı
(site/library/space) **change-token DELTA** ile senkronize eder, kaynak izinlerini ACL metadata'ya eşler
ve her dokümanı **6.1.1 FormatExtractor'a devreder** → `NormalizedDocument`. Çıktıyı **6.1.3** tüketir.

```
SharePoint / Confluence / generic
   │ connect() → endpoint allowlist + SSRF + auth (${ENV})
   ▼ list_changes(cursor) → enumerate + DELTA (upsert/deletion/new_cursor)
   ▼ map_acl(native) → classification + acl_ref + source_principals  (→6.1.4 enforce)
   ▼ fetch_content() → bayt ──► (6.1.1 FormatExtractor) ──► NormalizedDocument + kaynak metadata
   │  (6.1.3 chunk→embed→index · 6.1.4 ACL enforce · 6.1.5 TTL)
```

## Dosyalar
| Dosya | Rol |
|-------|-----|
| `source-connector-spec.json` | Kaynak doğruluk: placement (offline, SPI arkası, 6.1.1 devri), spi (EnterpriseSourceConnector + reused FormatExtractor), connectors (sharepoint/confluence/generic), gates, error_taxonomy, residency, pii, invariants S1–S10 |
| `source-connector.md` | Tasarım: mimari konum, SPI, connector eşlemeleri, HARD kapılar, kapsam ayrımı, izlenebilirlik |
| `source_connector_probe.py` | stdlib-only: `validate` / `sync <sample>` / `selftest` / `schema`; gerçek connector adapter'ları + **6.1.1 ayıklama devri** (S5) |
| `config/source-connector-profiles.json` | 3 profil (pilot-default / regulated-tr / enterprise-eu); allowed_connectors + endpoint allowlist + page_size + residency; sır YOK (`${ENV}`) |
| `samples/*.json` | sharepoint-sync / confluence-delta / tenant-isolation (geçer) + degraded (eler) |
| `tests/source_connector_behavior_test.py` | Davranış kapısı T1–T10 |
| `run_live_test.sh` | Statik + sample + (canlı SKIP/not; `${KB_SOURCE_ENDPOINT}`/`${KB_SOURCE_OAUTH_TOKEN}`) |

## Çalıştır
```bash
python3 source_connector_probe.py validate                       # statik spec/config kapısı
python3 source_connector_probe.py selftest                       # iyi/kötü senaryo + her connector
python3 source_connector_probe.py sync samples/sharepoint-sync.json
python3 source_connector_probe.py sync samples/confluence-delta.json
python3 tests/source_connector_behavior_test.py                  # T1–T10
bash run_live_test.sh                                             # statik + sample + canlı SKIP/not
```

## Kapılar (S1–S10)
`S1` connector coverage (≥2, SR-KB-002) · `S2` enumerate+pagination · `S3` incremental delta
(idempotent + tombstone + monoton cursor) · `S4` source ACL mapping (→6.1.4) · `S5` extraction
delegation (6.1.1) · `S6` tenant/kb isolation · `S7` residency + endpoint allowlist + SSRF + no-log ·
`S8` robust + taxonomy + throttle · `S9` sync state/cursor · `S10` scope boundary.

## Notlar
- **Vendor-neutral (ADR-002):** SharePoint/Confluence/generic adapter'ları tek `EnterpriseSourceConnector`
  SPI arkasında; canlıda Microsoft Graph / Confluence REST istemcisi aynı imza arkasına takılır.
- **6.1.1 devri (S5):** ayıklama/normalizasyon/dedup yeniden yazılmaz; `samples/fixtures/` boşsa 6.1.1
  fixture'larına (ör. `policy.docx`) düşülür.
- **Credential-free:** kaynak endpoint + OAuth/token yalnız `${ENV}`; repoya yazılmaz. Snapshot içerikleri
  sentetik (FR-TST-008).
- **Kapsam dışı:** chunk/embed/index → 6.1.3 · ACL enforce → 6.1.4 · TTL/bayatlama → 6.1.5.
