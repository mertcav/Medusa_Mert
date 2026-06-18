// WBS 13.4.5 — A-05 "Conversation Flow Editor" veri katmanı (seam) + SAF türetme yardımcıları
// (L2 — Operasyon / Uygulama Paneli).
//
// ÇEKİRDEK İLKELER:
//  - İÇERİK (BRD §17.5 A-05 "Conversation Flow Editor"): node/flow tabanlı konuşma SÜRECİNİN (FR-AGT-003)
//    tasarım/doğrulama görünümü. Bir agent'ın KONUŞMA AKIŞI (conversation_flow) = DÜĞÜMLER (start/message/
//    collect/decision/tool/handoff/end) + GEÇİŞLER (edge: kaynak→hedef + koşul etiketi). Görünüm yalnız
//    KONFİGÜRASYON META taşır (düğüm etiketi, tür, prompt/tool REFERANSI, geçiş koşulu etiketi) — prompt
//    GÖVDESİ veya tool kimlik bilgisi GÖMÜLMEZ (derin tasarım → A-06 Prompt / A-09 Tool, görsel kapı).
//  - KONUŞMA MODELİ (FR-AGT-003): single_prompt | node_flow. A-05 node_flow modunda grafiği düzenler; tek-prompt
//    modunda grafik yoktur (sayfa EmptyState gösterir). DB §5.2 `conversation_flow` (mode + graph + version_no).
//  - DOĞRULAMA (akış sağlığı): saf graf doğrulaması — tek giriş düğümü, asılı (dangling) geçiş yok, erişilemez
//    (unreachable) düğüm yok, çıkmaz (dead-end) düğüm yok, düğüm yapılandırması tam, insan aktarımı (handoff)
//    düğümü var. structurallyValid/readyForTest (FR-AGT-010 önkoşulu)/readyForPublish saf kapılardır.
//  - İNSAN AKTARIMI TASARIM GEREĞİ (SAD): akışta en az bir handoff düğümü beklenir (en iyi-uygulama uyarısı).
//  - TENANT-SCOPE (FR-TEN-002): A-05 yalnız oturum açan tenant'ın KENDİ agent'ının akışı. Scope çalışma-anında
//    middleware (13.1.2) + RLS (DB §6.3) ile sabitlenir; UI yalnız görsel kapı (SAD §14.4.1 A8).
//  - HİJYEN (BRD §17.7 + §17.6): yalnız KONFİGÜRASYON META. Son-müşteri ham içeriği (transkript/ses kaydı/
//    ham numara/müşteri PII/CDR) gömülmez; prompt gövdesi/tool sırrı derin aksiyon → A-06/A-09.
//  - GÜVENLİK (NFR 10.6): sır/credential görünüme KONMAZ (token/apiKey/webhookSecret/privateKey/kmsKey).
//  - VENDOR-NEUTRAL (ADR-002): veri kaynağı bir SEAM'dir; gerçek implementasyon (F1 §14.1) Agent Registry
//    (DB §5.2 `agent` + `conversation_flow`) + akış doğrulama servisinden tenant-scope (RLS) beslenir.
//    Belirli LLM/STT/TTS sağlayıcısı bağlanmaz.
//  - SAF/DETERMİNİSTİK: türetme yardımcıları (countByType/reachableNodeIds/unreachableNodes/danglingEdges/
//    deadEndNodes/structurallyValid/readyForPublish/...) Date.now/rastgelelik içermez → birim-test edilebilir +
//    Python aynası (screens/a05-flows/a05_flows_probe.py).
//  - İŞ MANTIĞI/AUTHZ YOK (SAD §14.4.1 A8): düzenle/doğrula/yayınla aksiyonları görsel kapıdır; nihai yetki +
//    işlem backend'de (12.x). Panel yalnız çözümlenmiş akışı gösterir + sağlığı işaretler.
//  - RBAC (BRD §17.6 — L2): conversation_designer=Yönet · operations_manager=Düzenle · qa_analyst=— ·
//    human_agent=— (A-04 ile aynı birincil rol: conversation_designer).

// Düğüm türü (node/flow grafiği — FR-AGT-003).
export type NodeType =
  | "start" // giriş düğümü (akış başlangıcı)
  | "message" // agent konuşur (prompt REFERANSI; gövde değil)
  | "collect" // kullanıcıdan girdi toplar
  | "decision" // koşullu dallanma
  | "tool" // tool/API çağrısı (tool REFERANSI; kimlik bilgisi değil)
  | "handoff" // insan temsilciye aktarım (tasarım gereği)
  | "end"; // görüşme sonu

// Konuşma modeli (FR-AGT-003 / DB §5.2 conversation_flow.mode).
export type FlowMode = "single_prompt" | "node_flow";
// Akış doğrulama durumu (türetilir).
export type FlowValidity = "valid" | "warnings" | "invalid";

export type StatusTone = "success" | "warning" | "danger" | "neutral" | "info";

// Tek akış düğümü. Yalnız KONFİGÜRASYON META: etiket/tür/REFERANS (içerik DEĞİL).
export interface FlowNode {
  id: string; // düğüm kimliği (ör. "N1")
  type: NodeType; // düğüm türü
  label: string; // düğüm etiketi (tenant config — FR-AGT-002; PII değil)
  promptRef: string | null; // prompt REFERANSI (gövde A-06'da; gömülmez) | yok
  toolRef: string | null; // tool REFERANSI (kimlik bilgisi A-09'da; gömülmez) | yok
  configComplete: boolean; // düğüm yapılandırması tam mı
}

// Tek geçiş (edge). Koşul yalnız ETİKET (intent/yanıt etiketi — tenant config).
export interface FlowEdge {
  from: string; // kaynak düğüm kimliği
  to: string; // hedef düğüm kimliği
  condition: string | null; // geçiş koşulu ETİKETİ (tenant config) | koşulsuz
}

// Bir agent'ın konuşma akışı (DB §5.2 conversation_flow). Yalnız KONFİGÜRASYON META.
export interface ConversationFlow {
  flowRef: string; // gösterim referansı (ör. "FLOW-12")
  mode: FlowMode; // konuşma modeli (FR-AGT-003)
  versionNo: number; // akış sürüm numarası (DB §5.2 version_no)
  nodes: FlowNode[]; // düğümler (node_flow modunda)
  edges: FlowEdge[]; // geçişler
}

export interface FlowView {
  generatedAt: string; // ISO-8601 (sabit yer tutucu — SSR-stabil, Date.now YOK)
  tenantRef: string; // tenant'ın KENDİ kimliği (L2'de izinli)
  tenantName: string; // tenant org adı (izinli; son-müşteri verisi DEĞİL)
  agentRef: string; // akışı düzenlenen agent referansı (tenant config)
  agentName: string; // agent adı (tenant config; PII değil)
  flow: ConversationFlow; // konuşma akışı (tenant-scope FR-TEN-002)
}

// Düğüm türlerinin görüntüleme sırası.
export const NODE_TYPE_ORDER: NodeType[] = ["start", "message", "collect", "decision", "tool", "handoff", "end"];
// Giriş düğümü türü.
export const ENTRY_NODE_TYPE: NodeType = "start";
// Çıkış-uçlu (terminal) düğüm türleri: giden geçişi olmaması MEŞRUDUR (çıkmaz sayılmaz).
export const TERMINAL_NODE_TYPES: NodeType[] = ["handoff", "end"];

// ── saf türetme yardımcıları ────────────────────────────────────────────────────

// node_flow modu mu (grafik doğrulaması yalnız bu modda anlamlı).
export function isNodeFlow(flow: ConversationFlow): boolean {
  return flow.mode === "node_flow";
}

// Belirli kimlikteki düğüm | undefined.
export function nodeById(nodes: FlowNode[], id: string): FlowNode | undefined {
  return nodes.find((n) => n.id === id);
}

// Düğüm kimlikleri kümesi.
export function nodeIdSet(nodes: FlowNode[]): Set<string> {
  return new Set(nodes.map((n) => n.id));
}

// Tür başına düğüm sayısı (tüm türler 0'dan başlatılır).
export function countByType(nodes: FlowNode[]): Record<NodeType, number> {
  const acc = {} as Record<NodeType, number>;
  for (const t of NODE_TYPE_ORDER) acc[t] = 0;
  for (const n of nodes) acc[n.type] += 1;
  return acc;
}

// Giriş düğümleri (tür === start).
export function entryNodes(nodes: FlowNode[]): FlowNode[] {
  return nodes.filter((n) => n.type === ENTRY_NODE_TYPE);
}

// Tam olarak tek giriş düğümü var mı.
export function hasSingleEntry(flow: ConversationFlow): boolean {
  return entryNodes(flow.nodes).length === 1;
}

// Bir düğümün giden GEÇERLİ geçişleri (hedef düğüm mevcut).
export function outgoingEdges(flow: ConversationFlow, nodeId: string): FlowEdge[] {
  const ids = nodeIdSet(flow.nodes);
  return flow.edges.filter((e) => e.from === nodeId && ids.has(e.to));
}

// Asılı (dangling) geçişler: kaynak veya hedef düğümü mevcut DEĞİL.
export function danglingEdges(flow: ConversationFlow): FlowEdge[] {
  const ids = nodeIdSet(flow.nodes);
  return flow.edges.filter((e) => !ids.has(e.from) || !ids.has(e.to));
}

// Tek geçiş asılı mı (kaynak/hedef eksik).
export function isDanglingEdge(flow: ConversationFlow, edge: FlowEdge): boolean {
  const ids = nodeIdSet(flow.nodes);
  return !ids.has(edge.from) || !ids.has(edge.to);
}

// Giriş düğümlerinden erişilebilir düğüm kimlikleri (deterministik BFS; yalnız geçerli geçişler).
export function reachableNodeIds(flow: ConversationFlow): Set<string> {
  const ids = nodeIdSet(flow.nodes);
  const adj = new Map<string, string[]>();
  for (const e of flow.edges) {
    if (ids.has(e.from) && ids.has(e.to)) {
      const list = adj.get(e.from);
      if (list) list.push(e.to);
      else adj.set(e.from, [e.to]);
    }
  }
  const seen = new Set<string>();
  const queue: string[] = [];
  for (const n of entryNodes(flow.nodes)) {
    if (!seen.has(n.id)) {
      seen.add(n.id);
      queue.push(n.id);
    }
  }
  while (queue.length > 0) {
    const cur = queue.shift() as string;
    for (const nxt of adj.get(cur) ?? []) {
      if (!seen.has(nxt)) {
        seen.add(nxt);
        queue.push(nxt);
      }
    }
  }
  return seen;
}

// Erişilemez düğümler (giriş düğümlerinden ulaşılamayan).
export function unreachableNodes(flow: ConversationFlow): FlowNode[] {
  const r = reachableNodeIds(flow);
  return flow.nodes.filter((n) => !r.has(n.id));
}

// Çıkmaz (dead-end) düğümler: terminal OLMAYAN + giden geçerli geçişi olmayan.
export function deadEndNodes(flow: ConversationFlow): FlowNode[] {
  return flow.nodes.filter((n) => !TERMINAL_NODE_TYPES.includes(n.type) && outgoingEdges(flow, n.id).length === 0);
}

// Yapılandırması tamamlanmamış düğümler.
export function nodesMissingConfig(flow: ConversationFlow): FlowNode[] {
  return flow.nodes.filter((n) => !n.configComplete);
}

// Akışta insan aktarımı düğümü var mı (tasarım gereği — SAD).
export function hasHandoff(flow: ConversationFlow): boolean {
  return flow.nodes.some((n) => n.type === "handoff");
}

// YAPISAL OLARAK geçerli mi: tek giriş + asılı yok + erişilemez yok + çıkmaz yok.
export function structurallyValid(flow: ConversationFlow): boolean {
  return (
    hasSingleEntry(flow) &&
    danglingEdges(flow).length === 0 &&
    unreachableNodes(flow).length === 0 &&
    deadEndNodes(flow).length === 0
  );
}

// TEST'e hazır mı: yapısal geçerli + tüm düğüm yapılandırması tam (FR-AGT-010 önkoşulu).
export function readyForTest(flow: ConversationFlow): boolean {
  return structurallyValid(flow) && nodesMissingConfig(flow).length === 0;
}

// YAYINLANABİLİR mi: test'e hazır + insan aktarımı düğümü var (tasarım gereği).
export function readyForPublish(flow: ConversationFlow): boolean {
  return readyForTest(flow) && hasHandoff(flow);
}

// Akış doğrulama durumu (rozet): yapısal hata → invalid · eksik config/handoff → warnings · aksi → valid.
export function flowValidity(flow: ConversationFlow): FlowValidity {
  if (!structurallyValid(flow)) return "invalid";
  if (nodesMissingConfig(flow).length > 0 || !hasHandoff(flow)) return "warnings";
  return "valid";
}

// ── ton (renk) eşlemeleri ─────────────────────────────────────────────────────────

const NODE_TYPE_TONE: Record<NodeType, StatusTone> = {
  start: "info",
  message: "neutral",
  collect: "neutral",
  decision: "info",
  tool: "info",
  handoff: "warning",
  end: "neutral",
};
export function nodeTypeTone(t: NodeType): StatusTone {
  return NODE_TYPE_TONE[t];
}

const VALIDITY_TONE: Record<FlowValidity, StatusTone> = {
  valid: "success",
  warnings: "warning",
  invalid: "danger",
};
export function validityTone(v: FlowValidity): StatusTone {
  return VALIDITY_TONE[v];
}

export function modeTone(m: FlowMode): StatusTone {
  return m === "node_flow" ? "info" : "neutral";
}

// Hazırlık/kapı tonu: tamam → success · değil → warning.
export function readyTone(b: boolean): StatusTone {
  return b ? "success" : "warning";
}

// ── HİJYEN + GÜVENLİK koruması ─────────────────────────────────────────────────────
// Yapı içinde son-müşteri ham iş içeriği/PII'yi VEYA sır/credential/prompt-gövdesi çağrıştıran ALAN ADI
// bulunursa hata fırlatır. Bu, A-05'in yalnız KONFİGÜRASYON META veriyi (düğüm etiketi/tür/REFERANS/geçiş
// koşulu — tenant'ın KENDİ yapılandırması) — ham transkript/ses kaydı/ham numara/müşteri PII/CDR + prompt
// gövdesi/tool sırrı DEĞİL — göstermesini çalışma-anında garanti eder (BRD §17.7 + §17.6 + NFR 10.6).
// NOT: label/name/tenantName/agentName tenant'ın KENDİ yapılandırmasıdır (L2'de izinli).
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
  "prompttext", // prompt gövdesi derin tasarım (A-06) — akış META'sına gömülmez
  "promptbody",
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
        throw new Error(`A-05 HİJYEN ihlali: yasak PII/iş-içeriği alanı "${path}.${k}" (BRD §17.7)`);
      }
      if (FORBIDDEN_SECRET_KEYS.includes(lower)) {
        throw new Error(`A-05 GÜVENLİK ihlali: sır/credential/prompt-gövdesi alanı "${path}.${k}" panele konmaz (NFR 10.6)`);
      }
      assertNoPii((node as Record<string, unknown>)[k], `${path}.${k}`);
    }
  }
}

// ── veri SEAM (yer tutucu) ───────────────────────────────────────────────────────
// Deterministik yer tutucu: tek-tenant agent konuşma akışı (KONFİGÜRASYON META yalnız — ham içerik/PII/sır/
// prompt-gövdesi DEĞİL). Gerçek implementasyon (F1 §14.1) Agent Registry (DB §5.2 `agent` + `conversation_flow`)
// + akış doğrulama servisinden tenant-scope (RLS) beslenir. Bu örnek akış YAPISAL OLARAK geçerli + yayına hazır.
const PLACEHOLDER_VIEW: FlowView = {
  generatedAt: "2026-06-18T09:00:00.000Z",
  tenantRef: "TEN-2048",
  tenantName: "Kuzey Sigorta A.Ş.",
  agentRef: "AGT-117",
  agentName: "Poliçe Yenileme Asistanı",
  flow: {
    flowRef: "FLOW-31",
    mode: "node_flow",
    versionNo: 4,
    nodes: [
      { id: "N1", type: "start", label: "Başlangıç", promptRef: null, toolRef: null, configComplete: true },
      { id: "N2", type: "message", label: "Karşılama ve yapay zekâ bildirimi", promptRef: "PROMPT-01", toolRef: null, configComplete: true },
      { id: "N3", type: "collect", label: "Poliçe numarası al", promptRef: "PROMPT-02", toolRef: null, configComplete: true },
      { id: "N4", type: "decision", label: "Poliçe bulundu mu?", promptRef: null, toolRef: null, configComplete: true },
      { id: "N5", type: "message", label: "Yenileme detaylarını sun", promptRef: "PROMPT-04", toolRef: null, configComplete: true },
      { id: "N6", type: "tool", label: "Ödeme bağlantısı oluştur", promptRef: null, toolRef: "TOOL-PAY", configComplete: true },
      { id: "N7", type: "handoff", label: "Temsilciye aktar", promptRef: null, toolRef: null, configComplete: true },
      { id: "N8", type: "end", label: "Görüşme sonu", promptRef: null, toolRef: null, configComplete: true },
    ],
    edges: [
      { from: "N1", to: "N2", condition: null },
      { from: "N2", to: "N3", condition: null },
      { from: "N3", to: "N4", condition: null },
      { from: "N4", to: "N5", condition: "bulundu" },
      { from: "N4", to: "N7", condition: "bulunamadı" },
      { from: "N5", to: "N6", condition: null },
      { from: "N6", to: "N8", condition: null },
      { from: "N7", to: "N8", condition: null },
    ],
  },
};

export async function getFlowView(): Promise<FlowView> {
  const view = PLACEHOLDER_VIEW;
  assertNoPii(view); // HİJYEN + GÜVENLİK: yapısal son-müşteri PII / sır / prompt-gövdesi yok (BRD §17.7 / NFR 10.6)
  return view;
}
