// WBS 13.4.8 — A-08 "Knowledge Base" veri katmanı (seam) + SAF türetme yardımcıları
// (L2 — Operasyon / Uygulama Paneli).
//
// ÇEKİRDEK İLKELER:
//  - İÇERİK (BRD §17.5 A-08 "Knowledge Base"): bir tenant'ın agent'larına bağlı BİLGİ TABANLARININ ve
//    DOKÜMANLARININ envanteri (bilgi kaynağı yükleme/bağlama). DB §12 `knowledge_base` (tenant_id,
//    agent_id, name, namespace) + `kb_document` (kb_id, source_uri, access_scope, version_no,
//    content_ttl_at, is_sensitive) + `kb_chunk` ile birebir. Görünüm yalnız DOKÜMAN META taşır —
//    kaynak türü (FR-KB-001) + indeks durumu (FR-KB-003) + sürüm (FR-KB-003) + parça SAYISI + güncellik
//    (FR-KB-008) + erişim kapsamı SEVİYESİ (FR-KB-005) + hassasiyet bayrağı (FR-KB-010). Doküman İÇERİĞİ
//    (kb_chunk.content) + KAYNAK İŞARETÇİSİ (source_uri) + embedding GÖMÜLMEZ; içerik yönetimi (ingest/
//    yeniden indeksleme) derin aksiyondur (API dilimi).
//  - BİLGİ TABANI İZOLASYONU (FR-KB-004): tenant+agent bazında farklı bilgi tabanları. `binding` =
//    agent'a bağlı (agent_id var) | tenant geneli (agent_id NULL → tenant-shared). `namespace` tenant
//    kapsamında BENZERSİZ (DB §12 UNIQUE (tenant_id, namespace)).
//  - İNDEKSLEME/VERSİYONLAMA (FR-KB-003): doküman otomatik parçalanır, indekslenir ve versiyonlanır.
//    indexStatus = indexed | indexing | pending | failed; versionNo yeniden ingest'te artar.
//  - DOKÜMAN BAZINDA ERİŞİM (FR-KB-005): access_scope JSONB → erişim SEVİYESİ etiketi (tenant | restricted).
//    Ham ACL içeriği gömülmez (yalnız seviye).
//  - BAYATLAMA (FR-KB-008): content_ttl_at geçmişse doküman `stale` işaretlenir (güncelliğini yitirmiş).
//  - HASSAS DOKÜMAN (FR-KB-010): is_sensitive → genel model sağlayıcı loglarında tutulmaz. Görünümde
//    yalnız BAYRAK gösterilir (içerik değil).
//  - TENANT-SCOPE (FR-TEN-002): A-08 yalnız oturum açan tenant'ın KENDİ bilgi tabanları. Scope çalışma-
//    anında middleware (13.1.2) + RLS (DB §6.3) ile sabitlenir; UI yalnız görsel kapı.
//  - HİJYEN (BRD §17.7 + §17.6): yalnız DOKÜMAN META. Son-müşteri ham içeriği (transkript/ses kaydı/
//    ham numara/müşteri PII/CDR) gömülmez; DOKÜMAN İÇERİĞİ/CHUNK METNİ/KAYNAK İŞARETÇİSİ (content/
//    chunkContent/sourceUri/embedding) panele konmaz — içerik derin aksiyon (görsel kapı + backend).
//    NOT: name/title/namespace/changeNote tenant'ın KENDİ yapılandırmasıdır (KURUMSAL doküman adı —
//    son-müşteri PII değil); chunkCount yalnız SAYIdır (içerik değil).
//  - GÜVENLİK (NFR 10.6): sır/credential görünüme KONMAZ (token/apiKey/webhookSecret/privateKey/kmsKey).
//  - VENDOR-NEUTRAL (ADR-002): veri kaynağı bir SEAM'dir; gerçek implementasyon (F1 §14.1) Knowledge Base
//    servisi (DB §12 `knowledge_base` + `kb_document` + ingest/index pipeline WBS 6.1.x) tenant-scope (RLS)
//    beslenir. Belirli vektör DB (pgvector/OpenSearch) / embedding sağlayıcısı bağlanmaz.
//  - SAF/DETERMİNİSTİK: türetme yardımcıları (allDocuments/countBySourceType/countByIndexStatus/
//    indexedDocuments/staleDocuments/sensitiveDocuments/emptyBases/duplicateNamespaces/...) Date.now/
//    rastgelelik içermez → birim-test edilebilir + Python aynası (screens/a08-kb/a08_kb_probe.py).
//  - İŞ MANTIĞI/AUTHZ YOK (SAD §14.4.1 A8): yükle/bağla/yeniden-indeksle aksiyonları görsel kapıdır;
//    nihai yetki + işlem backend'de (12.x). Panel yalnız çözümlenmiş envanteri gösterir.
//  - RBAC (BRD §17.6 — L2): conversation_designer=Yönet · operations_manager=Düzenle · qa_analyst=Görüntüle ·
//    human_agent=— (A-06 ile aynı birincil rol: conversation_designer; qa_analyst kalite incelemesi için Görüntüle).

// Kaynak türü (FR-KB-001 — PDF/Word/HTML/metin/CSV/web).
export type SourceType = "pdf" | "word" | "html" | "text" | "csv" | "web";
// İndeks durumu (FR-KB-003 — otomatik parçalama/indeksleme).
export type IndexStatus = "indexed" | "indexing" | "pending" | "failed";
// Güncellik (FR-KB-008 — content_ttl bayatlama).
export type Freshness = "fresh" | "stale";
// Doküman bazında erişim seviyesi (FR-KB-005 — access_scope JSONB → seviye etiketi).
export type AccessScope = "tenant" | "restricted";
// Bilgi tabanı bağı (FR-KB-004 — agent'a bağlı | tenant geneli).
export type KbBinding = "agent" | "shared";

export type StatusTone = "success" | "warning" | "danger" | "neutral" | "info";

// Tek doküman (DB §12 `kb_document` satırı). Yalnız DOKÜMAN META — İÇERİK/CHUNK/source_uri DEĞİL.
export interface KbDocument {
  docRef: string; // doküman gösterim kimliği (DB §12 kb_document)
  title: string; // kurumsal doküman adı (tenant config; son-müşteri PII değil)
  sourceType: SourceType; // FR-KB-001 (PDF/Word/HTML/metin/CSV/web)
  indexStatus: IndexStatus; // FR-KB-003 (otomatik indeksleme)
  versionNo: number; // FR-KB-003 (yeniden ingest sürüm üretir; DB §12 version_no)
  chunkCount: number; // parça SAYISI — yalnız SAYI (kb_chunk.content gömülmez)
  freshness: Freshness; // FR-KB-008 (content_ttl_at bayatlama)
  accessScope: AccessScope; // FR-KB-005 (doküman bazında erişim — seviye etiketi)
  isSensitive: boolean; // FR-KB-010 (hassas → sağlayıcı loguna gitmez; yalnız BAYRAK)
  updatedAt: string; // ISO-8601 (doküman META — son güncelleme)
}

// Bir bilgi tabanı (DB §12 `knowledge_base` + dokümanları).
export interface KnowledgeBase {
  kbRef: string; // bilgi tabanı gösterim kimliği (DB §12 knowledge_base)
  name: string; // bilgi tabanı adı (tenant config; PII değil)
  namespace: string; // izolasyon namespace (DB §12 namespace; tenant kapsamında benzersiz — FR-KB-004)
  binding: KbBinding; // agent'a bağlı | tenant geneli (FR-KB-004)
  boundAgentRef: string | null; // bağlı agent (agent_id var) | null → tenant-shared
  documents: KbDocument[]; // dokümanlar (DOKÜMAN META yalnız)
}

export interface KbView {
  generatedAt: string; // ISO-8601 (sabit yer tutucu — SSR-stabil, Date.now YOK)
  tenantRef: string; // tenant'ın KENDİ kimliği (L2'de izinli)
  tenantName: string; // tenant org adı (izinli; son-müşteri verisi DEĞİL)
  knowledgeBases: KnowledgeBase[]; // bilgi tabanı envanteri (tenant-scope FR-TEN-002)
}

// Kaynak türlerinin görüntüleme sırası (FR-KB-001).
export const SOURCE_ORDER: SourceType[] = ["pdf", "word", "html", "text", "csv", "web"];
// İndeks durumlarının görüntüleme sırası (FR-KB-003).
export const INDEX_ORDER: IndexStatus[] = ["indexed", "indexing", "pending", "failed"];

// ── saf türetme yardımcıları ────────────────────────────────────────────────────

// Bilgi tabanlarını kbRef'e göre ARTAN sırala (deterministik, kopya döndürür).
export function sortedBases(view: KbView): KnowledgeBase[] {
  return [...view.knowledgeBases].sort((a, b) => a.kbRef.localeCompare(b.kbRef));
}

// Tüm dokümanları (tüm bilgi tabanları) düzleştir; (kbRef, docRef) ile deterministik sırala.
export function allDocuments(view: KbView): Array<KbDocument & { kbRef: string; kbName: string }> {
  const rows: Array<KbDocument & { kbRef: string; kbName: string }> = [];
  for (const kb of view.knowledgeBases) {
    for (const d of kb.documents) rows.push({ ...d, kbRef: kb.kbRef, kbName: kb.name });
  }
  return rows.sort((a, b) => a.kbRef.localeCompare(b.kbRef) || a.docRef.localeCompare(b.docRef));
}

// Kaynak türü başına doküman sayısı (tüm türler 0'dan başlatılır — FR-KB-001).
export function countBySourceType(docs: KbDocument[]): Record<SourceType, number> {
  const acc = {} as Record<SourceType, number>;
  for (const s of SOURCE_ORDER) acc[s] = 0;
  for (const d of docs) acc[d.sourceType] += 1;
  return acc;
}

// İndeks durumu başına doküman sayısı (tüm durumlar 0'dan başlatılır — FR-KB-003).
export function countByIndexStatus(docs: KbDocument[]): Record<IndexStatus, number> {
  const acc = {} as Record<IndexStatus, number>;
  for (const s of INDEX_ORDER) acc[s] = 0;
  for (const d of docs) acc[d.indexStatus] += 1;
  return acc;
}

// İndekslenmiş (aranabilir) dokümanlar (FR-KB-003).
export function indexedDocuments(docs: KbDocument[]): KbDocument[] {
  return docs.filter((d) => d.indexStatus === "indexed");
}

// İndeks bekleyen (henüz aranamayan) dokümanlar: pending | indexing (FR-KB-003).
export function pendingIndexDocuments(docs: KbDocument[]): KbDocument[] {
  return docs.filter((d) => d.indexStatus === "pending" || d.indexStatus === "indexing");
}

// İndekslemede BAŞARISIZ dokümanlar (FR-KB-003 — dikkat gerektirir).
export function failedIndexDocuments(docs: KbDocument[]): KbDocument[] {
  return docs.filter((d) => d.indexStatus === "failed");
}

// Güncelliğini yitirmiş (bayat) dokümanlar (FR-KB-008).
export function staleDocuments(docs: KbDocument[]): KbDocument[] {
  return docs.filter((d) => d.freshness === "stale");
}

// Hassas dokümanlar (FR-KB-010 — sağlayıcı loguna gitmez; yalnız bayrak).
export function sensitiveDocuments(docs: KbDocument[]): KbDocument[] {
  return docs.filter((d) => d.isSensitive);
}

// Kısıtlı erişimli dokümanlar (FR-KB-005 — doküman bazında erişim).
export function restrictedDocuments(docs: KbDocument[]): KbDocument[] {
  return docs.filter((d) => d.accessScope === "restricted");
}

// Agent'a bağlı bilgi tabanları (FR-KB-004).
export function agentBoundBases(view: KbView): KnowledgeBase[] {
  return view.knowledgeBases.filter((kb) => kb.binding === "agent");
}

// Tenant geneli (shared) bilgi tabanları (FR-KB-004).
export function sharedBases(view: KbView): KnowledgeBase[] {
  return view.knowledgeBases.filter((kb) => kb.binding === "shared");
}

// Boş bilgi tabanları (doküman yok — agent yanıtları için kaynak eksik; dikkat).
export function emptyBases(view: KbView): KnowledgeBase[] {
  return view.knowledgeBases.filter((kb) => kb.documents.length === 0);
}

// Namespace bütünlüğü (DB §12 UNIQUE (tenant_id, namespace)): yinelenen namespace'ler.
export function duplicateNamespaces(view: KbView): string[] {
  const seen = new Set<string>();
  const dup = new Set<string>();
  for (const kb of view.knowledgeBases) {
    if (seen.has(kb.namespace)) dup.add(kb.namespace);
    seen.add(kb.namespace);
  }
  return [...dup].sort();
}

// Açık dikkat sayısı: bayat doküman + başarısız indeks + boş bilgi tabanı + yinelenen namespace.
export function openAttentionCount(view: KbView): number {
  const docs = allDocuments(view);
  return (
    staleDocuments(docs).length +
    failedIndexDocuments(docs).length +
    emptyBases(view).length +
    duplicateNamespaces(view).length
  );
}

// ── ton (renk) eşlemeleri ─────────────────────────────────────────────────────────

const SOURCE_TONE: Record<SourceType, StatusTone> = {
  pdf: "neutral",
  word: "neutral",
  html: "neutral",
  text: "neutral",
  csv: "neutral",
  web: "info",
};
export function sourceTone(s: SourceType): StatusTone {
  return SOURCE_TONE[s];
}

const INDEX_TONE: Record<IndexStatus, StatusTone> = {
  indexed: "success",
  indexing: "info",
  pending: "warning",
  failed: "danger",
};
export function indexTone(s: IndexStatus): StatusTone {
  return INDEX_TONE[s];
}

const FRESHNESS_TONE: Record<Freshness, StatusTone> = {
  fresh: "success",
  stale: "warning",
};
export function freshnessTone(f: Freshness): StatusTone {
  return FRESHNESS_TONE[f];
}

const ACCESS_TONE: Record<AccessScope, StatusTone> = {
  tenant: "neutral",
  restricted: "info",
};
export function accessTone(a: AccessScope): StatusTone {
  return ACCESS_TONE[a];
}

const BINDING_TONE: Record<KbBinding, StatusTone> = {
  agent: "info",
  shared: "neutral",
};
export function bindingTone(b: KbBinding): StatusTone {
  return BINDING_TONE[b];
}

// ── HİJYEN + GÜVENLİK koruması ─────────────────────────────────────────────────────
// Yapı içinde son-müşteri ham iş içeriği/PII'yi VEYA sır/credential/DOKÜMAN İÇERİĞİ çağrıştıran ALAN ADI
// bulunursa hata fırlatır. Bu, A-08'in yalnız DOKÜMAN META veriyi (kaynak türü/indeks durumu/sürüm/parça
// SAYISI/güncellik/erişim seviyesi/hassasiyet bayrağı + KB adı/namespace — tenant'ın KENDİ yapılandırması) —
// ham transkript/ses kaydı/ham numara/müşteri PII/CDR + DOKÜMAN İÇERİĞİ/CHUNK METNİ/KAYNAK İŞARETÇİSİ DEĞİL —
// göstermesini çalışma-anında garanti eder (BRD §17.7 + §17.6 + NFR 10.6).
// NOT: name/title/namespace tenant'ın KENDİ yapılandırmasıdır (KURUMSAL doküman/KB adı; L2'de izinli);
// chunkCount/versionNo yalnız SAYIdır (içerik değil).
export const FORBIDDEN_PII_KEYS: readonly string[] = [
  "transcript",
  "recording",
  "recordingurl",
  "audio",
  "msisdn",
  "phonenumber",
  "callerid",
  "callernumber",
  "calleenumber",
  "customer",
  "customername",
  "cdr",
  "cardpan",
  "cvv",
  "ssn",
  "pii",
];

export const FORBIDDEN_SECRET_KEYS: readonly string[] = [
  "secret",
  "apikey",
  "apisecret",
  "clientsecret",
  "webhooksecret",
  "token",
  "bearertoken",
  "accesstoken",
  "refreshtoken",
  "credential",
  "password",
  "privatekey",
  "kmskey",
  "content", // kb_chunk.content — doküman/chunk İÇERİĞİ panele konmaz (yalnız chunkCount)
  "chunkcontent",
  "chunktext",
  "documentbody",
  "documenttext",
  "rawtext",
  "sourceuri", // DB §12 kb_document.source_uri — nesne depo işaretçisi gömülmez
  "sourceurl",
  "embedding", // vektör gömme — panele konmaz
];

export function assertNoPii(node: unknown, path = "$"): void {
  if (node && typeof node === "object") {
    if (Array.isArray(node)) {
      node.forEach((v, i) => assertNoPii(v, `${path}[${i}]`));
      return;
    }
    for (const k of Object.keys(node as Record<string, unknown>)) {
      const lower = k.toLowerCase();
      if (FORBIDDEN_PII_KEYS.includes(lower)) {
        throw new Error(`A-08 HİJYEN ihlali: yasak PII/iş-içeriği alanı "${path}.${k}" (BRD §17.7)`);
      }
      if (FORBIDDEN_SECRET_KEYS.includes(lower)) {
        throw new Error(`A-08 GÜVENLİK ihlali: sır/credential/doküman-içeriği alanı "${path}.${k}" panele konmaz (NFR 10.6)`);
      }
      assertNoPii((node as Record<string, unknown>)[k], `${path}.${k}`);
    }
  }
}

// ── veri SEAM (yer tutucu) ───────────────────────────────────────────────────────
// Deterministik yer tutucu: tek-tenant bilgi tabanı envanteri (DOKÜMAN META yalnız — ham içerik/PII/sır/
// doküman-içeriği DEĞİL). Gerçek implementasyon (F1 §14.1) Knowledge Base servisi (DB §12 `knowledge_base` +
// `kb_document` + ingest/index pipeline WBS 6.1.x) tenant-scope (RLS) beslenir. Bu örnek: KB-1 agent'a bağlı
// (4 doküman; biri bayat); KB-2 tenant geneli (hassas + bekleyen + başarısız indeks); KB-3 boş (kaynak eksik).
const PLACEHOLDER_VIEW: KbView = {
  generatedAt: "2026-06-18T09:00:00.000Z",
  tenantRef: "TEN-2048",
  tenantName: "Kuzey Sigorta A.Ş.",
  knowledgeBases: [
    {
      kbRef: "KB-01",
      name: "Poliçe Bilgi Tabanı",
      namespace: "ten2048/policy",
      binding: "agent",
      boundAgentRef: "AGT-117",
      documents: [
        { docRef: "DOC-01", title: "Poliçe Yenileme Prosedürü", sourceType: "pdf", indexStatus: "indexed", versionNo: 3, chunkCount: 42, freshness: "fresh", accessScope: "tenant", isSensitive: false, updatedAt: "2026-06-14T10:20:00.000Z" },
        { docRef: "DOC-02", title: "İade ve İptal Politikası", sourceType: "word", indexStatus: "indexed", versionNo: 2, chunkCount: 28, freshness: "fresh", accessScope: "tenant", isSensitive: false, updatedAt: "2026-06-10T09:05:00.000Z" },
        { docRef: "DOC-03", title: "Fiyat Listesi 2026", sourceType: "csv", indexStatus: "indexing", versionNo: 1, chunkCount: 0, freshness: "fresh", accessScope: "restricted", isSensitive: false, updatedAt: "2026-06-17T16:40:00.000Z" },
        { docRef: "DOC-04", title: "Eski Kampanya SSS", sourceType: "html", indexStatus: "indexed", versionNo: 5, chunkCount: 15, freshness: "stale", accessScope: "tenant", isSensitive: false, updatedAt: "2026-03-22T11:15:00.000Z" },
      ],
    },
    {
      kbRef: "KB-02",
      name: "Kurumsal Politikalar",
      namespace: "ten2048/corp",
      binding: "shared",
      boundAgentRef: null,
      documents: [
        { docRef: "DOC-05", title: "KVKK Aydınlatma Metni", sourceType: "pdf", indexStatus: "indexed", versionNo: 1, chunkCount: 12, freshness: "fresh", accessScope: "restricted", isSensitive: true, updatedAt: "2026-05-30T08:00:00.000Z" },
        { docRef: "DOC-06", title: "Çalışan El Kitabı", sourceType: "pdf", indexStatus: "pending", versionNo: 1, chunkCount: 0, freshness: "fresh", accessScope: "tenant", isSensitive: false, updatedAt: "2026-06-18T07:30:00.000Z" },
        { docRef: "DOC-07", title: "Destek Web SSS", sourceType: "web", indexStatus: "failed", versionNo: 2, chunkCount: 0, freshness: "fresh", accessScope: "tenant", isSensitive: false, updatedAt: "2026-06-16T13:00:00.000Z" },
      ],
    },
    {
      kbRef: "KB-03",
      name: "Teknik Dokümanlar",
      namespace: "ten2048/tech",
      binding: "shared",
      boundAgentRef: null,
      documents: [],
    },
  ],
};

export async function getKbView(): Promise<KbView> {
  const view = PLACEHOLDER_VIEW;
  assertNoPii(view); // HİJYEN + GÜVENLİK: yapısal son-müşteri PII / sır / doküman-içeriği yok (BRD §17.7 / NFR 10.6)
  return view;
}
