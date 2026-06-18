# A-08 — Knowledge Base · WBS 13.4.8

L2 Operasyon / Uygulama Paneli'nin (A-01..A-17) yedinci implemente edilen ekranı. Bir tenant'ın
agent'larına bağlı **bilgi tabanlarının ve dokümanlarının envanteri** (bilgi kaynağı yükleme/bağlama):
bilgi tabanı özeti (KB · doküman · indeksli · bekleyen · bayat · hassas · kısıtlı + açık dikkat),
**bilgi tabanları** (ad · namespace · bağ [agent | tenant geneli] · doküman · indeksli · bayat · hassas),
**dokümanlar** (ad · KB · kaynak türü · indeks durumu · sürüm · parça **sayısı** · güncellik · erişim ·
hassasiyet), **kaynak türü dağılımı** ve **indeksleme sağlığı**. **A-06'dan farkı:** A-06 prompt sürüm
geçmişini gösterir; A-08 bilgi tabanı envanterini gösterir. Bu ekran **konfigürasyon**'dur — **gerçek
zamanlı değildir** (FR-ANA-012 kapsamı dışı).

## Kaynak gereksinimler
- **BRD §17.5** A-08 "Knowledge Base" (ekran tanımı: bilgi kaynağı yükleme/bağlama).
- **FR-KB-001** — PDF/Word/HTML/metin/CSV/web yüklenebilir → `sourceType` + kaynak türü dağılımı.
- **FR-KB-003** — Otomatik parçalama/indeksleme/versiyonlama → `indexStatus` + `versionNo` + indeks sağlığı.
- **FR-KB-004** — Tenant ve agent bazında farklı bilgi tabanları → `binding` (agent | tenant geneli) + `namespace`.
- **FR-KB-005** — Doküman bazında erişim yetkisi → `accessScope` (tenant | restricted) + `restrictedDocuments`.
- **FR-KB-008** — Güncelliğini yitirmiş içerik işaretleme → `freshness` (fresh | stale) + `staleDocuments`.
- **FR-KB-010** — Hassas doküman sağlayıcı loguna gitmez → `isSensitive` bayrağı + `sensitiveDocuments`.
- **DB §12** — `knowledge_base` (tenant_id/agent_id/name/namespace) + `kb_document` (source_uri/access_scope/
  version_no/content_ttl_at/is_sensitive) + `kb_chunk` ile model. Namespace tenant kapsamında benzersiz.
- **FR-TEN-002** — Tenant scope: yalnız kendi tenant'ın bilgi tabanları (RLS + middleware).
- **BRD §17.6** RBAC · **§17.7** hijyen + PII redaction · **NFR 10.6** sır · **ADR-002** vendor-neutral.

## RBAC (BRD §17.6 — L2)
`conversation_designer`=**Yönet** · `operations_manager`=Düzenle · `qa_analyst`=Görüntüle · `human_agent`=—
(A-06 ile aynı birincil rol; qa_analyst kalite incelemesi için Görüntüle). UI yalnız görsel kapı; nihai
yetki backend'de + RLS. Yükle/bağla/yeniden-indeksle derin aksiyondur (A8); doküman içeriği/ingest pipeline
API dilimi (WBS 6.1.x). Permission-key: `agent:read` + `agent:manage` (SAD §7/§17.2).

## Çekirdek altın kural — hijyen + güvenlik
A-08 yalnız **DOKÜMAN META** gösterir (kaynak türü · indeks durumu · sürüm · parça **SAYISI** · güncellik ·
erişim **seviyesi** · hassasiyet **bayrağı** + KB adı · namespace). Bunlar tenant'ın **KENDİ
yapılandırmasıdır** (`name`/`title`/`namespace` izinli — KURUMSAL doküman/KB adı, son-müşteri PII değil;
`chunkCount`/`versionNo` yalnız **sayı**). Ham son-müşteri içeriği (transkript/ses kaydı, ham numara, müşteri
PII, CDR) **gömülmez**; **doküman İÇERİĞİ / chunk metni / kaynak işaretçisi** panele konmaz — içerik yönetimi
(ingest/yeniden indeksleme) **derin aksiyondur** (API dilimi + backend). `getKbView` her dönüşte `assertNoPii`
çağırır → `FORBIDDEN_PII_KEYS` (transcript/recording/msisdn/customer/cdr/...) **ve** `FORBIDDEN_SECRET_KEYS`
(secret/apiKey/webhookSecret/token/privateKey/kmsKey/**content/chunkContent/sourceUri/embedding**) taraması →
ihlalde hata.

## Saf türetmeler
- **sortedBases / allDocuments** — bilgi tabanlarını kbRef ASC; tüm dokümanları (kbRef, docRef) deterministik düzleştir.
- **countBySourceType / countByIndexStatus** — kaynak türü (FR-KB-001) ve indeks durumu (FR-KB-003) dağılımı.
- **indexedDocuments / pendingIndexDocuments / failedIndexDocuments** — indeks sağlığı (FR-KB-003).
- **staleDocuments** — bayat (FR-KB-008) · **sensitiveDocuments** — hassas (FR-KB-010) · **restrictedDocuments** — kısıtlı (FR-KB-005).
- **agentBoundBases / sharedBases** — agent'a bağlı vs tenant geneli (FR-KB-004).
- **emptyBases** — doküman yok (dikkat) · **duplicateNamespaces** — DB §12 benzersizlik ihlali.
- **openAttentionCount** — bayat + başarısız indeks + boş KB + yinelenen namespace.

## Dosyalar
- `app/(workspace)/workspace/kb/page.tsx` — ekran (RSC, async). Tasarım sistemi + i18n + veri seam.
- `lib/tenant/kb.ts` — vendor-neutral veri **seam** + saf türetme yardımcıları + `assertNoPii`.
- `lib/i18n/{tr,en}.json` — `screen.a08.*` katalogu (TR/EN parity; design-system canonical + 2 vendored kopya).
- `a08-kb-spec.json` — kaynak doğruluk + invariant kapısı (S1..S8).
- `a08_kb_probe.py` — stdlib-only doğrulama (`validate`/`check`/`selftest`/`schema`); TS saf yardımcı Python aynası.
- `samples/kb-{clean,issues}.json` — illüstratif bilgi tabanı envanterleri (`$expect` ile).
- `tests/a08_kb_test.py` — probe üç kapısının davranış testi.
- `run_live_test.sh` — canlı smoke (next build + start + curl).

## Çalıştırma
```bash
python3 a08_kb_probe.py selftest   # pozitif + negatif kendi-testleri
python3 a08_kb_probe.py check      # saf çekirdek + samples
python3 a08_kb_probe.py validate   # on-disk invariant (sayfa + seam + i18n + spec)
python3 tests/a08_kb_test.py       # üç kapı tek komutta
bash run_live_test.sh              # canlı smoke (opsiyonel; next gerektirir)
```

## Kapsam dışı (bilinçli)
- Gerçek envanter besleme (Knowledge Base servisi DB §12 + ingest/index pipeline WBS 6.1.x) → F1 §14.1.
- **Doküman yükleme/bağlama** (ingest connector, SharePoint/Confluence — FR-KB-002) + yeniden indeksleme submit + backend zorlama → API dilimleri.
- Vector search / RAG retrieval (FR-KB-006/007/011) → orchestrator hot-path (WBS 6.2.x); bu ekran kapsamı değildir.
- Vendor-neutral (ADR-002; pgvector/OpenSearch/embedding sağlayıcı bağlanmaz); sır/credential repoya yazılmaz.
