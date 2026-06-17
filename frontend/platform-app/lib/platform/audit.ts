// WBS 13.2.7 — P-07 "Platform Audit & Güvenlik" veri katmanı (seam) + SAF türetme yardımcıları.
//
// ÇEKİRDEK İLKELER (P-01..P-06 ile aynı disiplin; lib/platform/overview.ts + tenants.ts + resources.ts +
// providers.ts + billing.ts + policy.ts):
//  - ALTIN KURAL (BRD §17.7 / FR-IAM-008): L0 platform konsolu YALNIZ platform-geneli audit/erişim/güvenlik
//    METADATASI gösterir; tenant İŞ İÇERİĞİ (çağrı kaydı, transkript, son-müşteri/PII) GÖSTERİLMEZ. Audit
//    kaydı bir işlemin META verisidir (kim/ne/ne zaman/sonuç), içeriği DEĞİL. Tipler YAPISAL OLARAK
//    iş-içeriği/PII taşımaz; `assertNoPii` çalışma-anında doğrular. Tenant kimliği (tenantRef) izinlidir
//    (BRD §17.7: tenant kimliği L0'a açık; yasaklanan SON-MÜŞTERİ verisidir).
//  - KRİTİK: P-07'nin kendisi break-glass'i YÖNETMEZ; yalnız break-glass oturumlarının uyum METADATASINI
//    (maker-checker, time-box, tenant onayı, bildirim) izler. İçeriğe fiili erişim Tier B akışındadır
//    (FR-IAM-009/010, 12.2.x); bu ekran o akışın audit/uyum görünürlüğüdür.
//  - SAF/DETERMİNİSTİK: türetme yardımcıları (auditOutcomeTone/breakGlassStatusTone/severityTone/
//    securityStatusTone/countByOutcome/wormGaps/countActiveBreakGlass/pendingApprovals/makerCheckerViolations/
//    standingAccessViolations/tenantApprovalGaps/notificationGaps/breakGlassComplianceGaps/openSecurityEvents/
//    criticalOpenEvents) Date.now/rastgelelik içermez → birim-test edilebilir + Python aynası
//    (screens/p07-audit/p07_audit_probe.py).
//  - İŞ MANTIĞI/AUTHZ YOK (SAD §14.4.1 A8): audit dışa aktarım / break-glass onay aksiyonları UI'da yalnız
//    görsel kapıdır; nihai yetki + zorlama backend'de (12.2.x; permission-key `audit:read` + `audit:export` +
//    `breakglass:approve`, SAD §7). RBAC (BRD §17.6): bu ekran `platform_owner`=Yönet + `platform_sre`=
//    Görüntüle + `platform_billing`=erişim yok.

// Audit aktörü — L0 platform rolü (tenant rolleri tamamen ayrı; FR-IAM-008).
export type PlatformRole = "platform_owner" | "platform_sre" | "platform_billing";

// Audit kategorisi:
//  - auth: oturum açma/kapama, MFA, başarısız giriş
//  - config_change: platform yapılandırma değişikliği (kota, politika, sağlayıcı yönlendirme)
//  - content_access: tenant iş içeriğine break-glass ile erişim (Tier B) — yalnız META kaydı (FR-REC-009)
//  - provisioning: tenant oluşturma/askıya alma/silme
//  - security: güvenlik ile ilgili olay/aksiyon
export type AuditCategory = "auth" | "config_change" | "content_access" | "provisioning" | "security";

// Audit sonucu: success (başarılı) · denied (yetki reddi) · error (hata).
export type AuditOutcome = "success" | "denied" | "error";

// Break-glass katmanı (FR-IAM-009): A (metrik/log, PII'sız — break-glass gerekmez) · B (transkript/kayıt/PII).
export type BreakGlassTier = "A" | "B";

// Break-glass oturum durumu: active (süreli erişim açık) · pending_approval (maker-checker bekliyor) ·
// expired (otomatik sonlandı — tasarım gereği) · revoked (manuel iptal) · denied (onay reddi).
export type BreakGlassStatus = "active" | "pending_approval" | "expired" | "revoked" | "denied";

// Güvenlik olayı önem derecesi.
export type SecuritySeverity = "critical" | "high" | "medium" | "low";

// Güvenlik olayı durumu: open (açık) · investigating (inceleniyor) · resolved (çözüldü).
export type SecurityStatus = "open" | "investigating" | "resolved";

// StatusPill/Alert ile hizalı ton kümesi.
export type Tone = "success" | "warning" | "info" | "danger" | "neutral";

// Platform-geneli audit kaydı (FR-IAM-006: değiştirilemez/WORM audit log; FR-REC-009: erişim audit'i).
// İşlemin META verisi — iş içeriği değil. tenantRef tenant KİMLİĞİdir (izinli), son-müşteri verisi değil.
export interface AuditEntry {
  id: string;
  occurredAt: string; // ISO-8601 (sabit yer tutucu — SSR-stabil, Date.now YOK)
  actorRole: PlatformRole; // L0 aktör rolü
  action: string; // permission-key biçimi eylem (ör. "tenant:provision") — çeviri değil, kod
  category: AuditCategory;
  outcome: AuditOutcome;
  tenantRef: string; // hedef tenant KİMLİĞİ (izinli; iş içeriği DEĞİL) — platform-geneli ise "platform"
  wormAnchored: boolean; // FR-IAM-006: kayıt WORM/değiştirilemez depoya çapalandı mı (integrity)
  mappedFr: string; // izlenebilirlik (FR-IAM-006 vb.) — kod string
}

// Break-glass erişim oturumu (FR-IAM-009/010) — uyum METADATASI (içeriğe erişim akışının audit'i).
export interface BreakGlassSession {
  id: string;
  tier: BreakGlassTier;
  status: BreakGlassStatus;
  tenantRef: string; // hedef tenant kimliği (izinli)
  reasonCode: string; // zorunlu gerekçe kodu (FR-IAM-009) — serbest metin değil, kod
  requestedBy: string; // talep eden RMC operatörü (kimlik handle'ı; son-müşteri değil)
  approvedBy: string | null; // onaylayan (maker ≠ checker; null = henüz onaylanmadı)
  durationMin: number; // talep edilen time-box (dk) — max 240 (4 saat), standing access yok
  remainingMin: number; // kalan süre (dk); 0 = sona erdi
  tenantApprovalRequired: boolean; // FR-IAM-010: regüle tenant'ta tenant onayı zorunlu
  tenantApproved: boolean; // tenant onayı alındı mı
  notified: boolean; // FR-IAM-009: tenant security_compliance_officer + tenant_owner bildirildi mi
  mappedFr: string;
}

// Platform-geneli güvenlik olayı (vendor-nötr tip etiketi).
export interface SecurityEvent {
  id: string;
  type: string; // vendor-nötr olay tipi (ör. "auth_anomaly", "rate_limit_breach", "policy_violation")
  severity: SecuritySeverity;
  status: SecurityStatus;
  occurredAt: string; // ISO-8601 (sabit yer tutucu)
  mappedFr: string;
}

export interface AuditSnapshot {
  generatedAt: string; // ISO-8601 (sabit yer tutucu — SSR-stabil, Date.now YOK)
  auditEntries: AuditEntry[];
  breakGlassSessions: BreakGlassSession[];
  securityEvents: SecurityEvent[];
}

// Break-glass Tier B max süre (FR-IAM-009: varsayılan 60 dk, MAX 4 saat = 240 dk; standing access yok).
export const MAX_BREAK_GLASS_MINUTES = 240;

// ── saf türetme yardımcıları ────────────────────────────────────────────────────

// Audit sonucu tonu: success başarı (success) · denied yetki reddi (warning) · error hata (danger).
const AUDIT_OUTCOME_TONE: Record<AuditOutcome, Tone> = {
  success: "success",
  denied: "warning",
  error: "danger",
};
export function auditOutcomeTone(o: AuditOutcome): Tone {
  return AUDIT_OUTCOME_TONE[o];
}

// Break-glass durumu tonu: active süreli erişim AÇIK (warning — hassas, izlenmeli) · pending_approval
// onay bekliyor (info) · expired tasarım gereği sonlandı (neutral) · revoked iptal (neutral) · denied red (neutral).
const BREAK_GLASS_STATUS_TONE: Record<BreakGlassStatus, Tone> = {
  active: "warning",
  pending_approval: "info",
  expired: "neutral",
  revoked: "neutral",
  denied: "neutral",
};
export function breakGlassStatusTone(s: BreakGlassStatus): Tone {
  return BREAK_GLASS_STATUS_TONE[s];
}

// Güvenlik önem tonu: critical/high danger · medium warning · low neutral.
const SEVERITY_TONE: Record<SecuritySeverity, Tone> = {
  critical: "danger",
  high: "danger",
  medium: "warning",
  low: "neutral",
};
export function severityTone(s: SecuritySeverity): Tone {
  return SEVERITY_TONE[s];
}

// Güvenlik durumu tonu: open danger · investigating warning · resolved success.
const SECURITY_STATUS_TONE: Record<SecurityStatus, Tone> = {
  open: "danger",
  investigating: "warning",
  resolved: "success",
};
export function securityStatusTone(s: SecurityStatus): Tone {
  return SECURITY_STATUS_TONE[s];
}

// Audit sonuç sayımı (özet KPI: success/denied/error).
export function countByOutcome(entries: AuditEntry[]): Record<AuditOutcome, number> {
  const acc: Record<AuditOutcome, number> = { success: 0, denied: 0, error: 0 };
  for (const e of entries) acc[e.outcome] += 1;
  return acc;
}

// Audit integrity boşluğu (FR-IAM-006): WORM çapasız audit kaydı id'leri (değiştirilebilirlik riski).
export function wormGaps(snap: AuditSnapshot): string[] {
  return snap.auditEntries.filter((e) => !e.wormAnchored).map((e) => e.id);
}

// Aktif (süreli erişimi açık) break-glass oturum sayısı.
export function countActiveBreakGlass(sessions: BreakGlassSession[]): number {
  return sessions.filter((s) => s.status === "active").length;
}

// Onay bekleyen (maker-checker) break-glass oturum id'leri.
export function pendingApprovals(sessions: BreakGlassSession[]): string[] {
  return sessions.filter((s) => s.status === "pending_approval").map((s) => s.id);
}

// Maker-checker ihlali (FR-IAM-005/009): aktif/sonlanmış Tier B oturum onaysız (approvedBy boş) VEYA
// talep eden = onaylayan (maker ≠ checker zorunlu). pending_approval/denied henüz/hiç erişim sağlamadığından
// ihlal sayılmaz (onay süreci doğru işliyor).
export function makerCheckerViolations(snap: AuditSnapshot): string[] {
  return snap.breakGlassSessions
    .filter((s) => s.tier === "B" && (s.status === "active" || s.status === "expired" || s.status === "revoked"))
    .filter((s) => !s.approvedBy || s.approvedBy === s.requestedBy)
    .map((s) => s.id);
}

// Standing-access ihlali (FR-IAM-009: time-boxed, MAX 4 saat, standing access YOK): Tier B time-box > 240 dk.
export function standingAccessViolations(snap: AuditSnapshot): string[] {
  return snap.breakGlassSessions
    .filter((s) => s.tier === "B" && s.durationMin > MAX_BREAK_GLASS_MINUTES)
    .map((s) => s.id);
}

// Tenant onayı boşluğu (FR-IAM-010): tenant onayı zorunlu ama alınmamış oturum id'leri.
// pending_approval/denied erişim sağlamadığından bu kapsamda değil (yalnız erişim sağlamış oturumlar).
export function tenantApprovalGaps(snap: AuditSnapshot): string[] {
  return snap.breakGlassSessions
    .filter((s) => (s.status === "active" || s.status === "expired" || s.status === "revoked"))
    .filter((s) => s.tenantApprovalRequired && !s.tenantApproved)
    .map((s) => s.id);
}

// Bildirim boşluğu (FR-IAM-009: tenant security_compliance_officer + tenant_owner anlık bildirimi):
// erişim sağlamış Tier B oturum bildirilmemiş.
export function notificationGaps(snap: AuditSnapshot): string[] {
  return snap.breakGlassSessions
    .filter((s) => s.tier === "B" && (s.status === "active" || s.status === "expired" || s.status === "revoked"))
    .filter((s) => !s.notified)
    .map((s) => s.id);
}

// Break-glass uyum boşluğu — maker-checker ∪ standing-access ∪ tenant-onayı ∪ bildirim ihlal id'leri (tekil, sıralı).
// Başlık uyarısı için toplulaştırılmış kümedir (FR-IAM-005/009/010).
export function breakGlassComplianceGaps(snap: AuditSnapshot): string[] {
  const set = new Set<string>([
    ...makerCheckerViolations(snap),
    ...standingAccessViolations(snap),
    ...tenantApprovalGaps(snap),
    ...notificationGaps(snap),
  ]);
  return [...set].sort();
}

// Açık (çözülmemiş) güvenlik olayı id'leri (open + investigating).
export function openSecurityEvents(events: SecurityEvent[]): string[] {
  return events.filter((e) => e.status !== "resolved").map((e) => e.id);
}

// Kritik + açık güvenlik olayı id'leri (severity critical && status != resolved).
export function criticalOpenEvents(events: SecurityEvent[]): string[] {
  return events.filter((e) => e.severity === "critical" && e.status !== "resolved").map((e) => e.id);
}

// ── ALTIN KURAL koruması (iş-içeriği/son-müşteri PII sızıntısı) ───────────────────
// Snapshot yapısı içinde tenant İŞ İÇERİĞİ/SON-MÜŞTERİ PII'sini çağrıştıran ALAN ADI bulunursa hata
// fırlatır. Bu, P-07'nin yalnız platform-geneli audit/erişim/güvenlik METADATASI göstermesini çalışma-anında
// garanti eder (BRD §17.7). tenantRef (tenant KİMLİĞİ) izinli olduğundan FORBIDDEN listesinde değildir.
export const FORBIDDEN_PII_KEYS: readonly string[] = [
  "transcript",
  "recording",
  "recordingurl",
  "audio",
  "msisdn",
  "phonenumber",
  "callerid",
  "customer",
  "cardpan",
  "cvv",
  "iban",
  "pii",
  "email",
  "ssn",
];

export function assertNoPii(node: unknown, path = "$"): void {
  if (node && typeof node === "object") {
    if (Array.isArray(node)) {
      node.forEach((v, i) => assertNoPii(v, `${path}[${i}]`));
      return;
    }
    for (const k of Object.keys(node as Record<string, unknown>)) {
      if (FORBIDDEN_PII_KEYS.includes(k.toLowerCase())) {
        throw new Error(`P-07 ALTIN KURAL ihlali: yasak iş-içeriği/PII alanı "${path}.${k}" (BRD §17.7)`);
      }
      assertNoPii((node as Record<string, unknown>)[k], `${path}.${k}`);
    }
  }
}

// ── veri SEAM (yer tutucu) ───────────────────────────────────────────────────────
// Deterministik yer tutucu: platform-geneli audit/erişim/güvenlik METADATASI (iş-içeriği/PII DEĞİL).
// Gerçek implementasyon (F2 §14.1) Audit servisi (FR-IAM-006 WORM audit log; SAD §13.x) + IAM break-glass
// akışı (FR-IAM-009/010) + Güvenlik olay hattı (0.4.7 gözlemlenebilirlik omurgası / SIEM) ile beslenir.
// Varsayılan profilde tüm audit kayıtları WORM çapalı + tüm Tier B oturum uyumlu (sağlıklı taban);
// ihlal senaryoları samples/* altında.
const PLACEHOLDER_SNAPSHOT: AuditSnapshot = {
  generatedAt: "2026-06-17T09:00:00.000Z",
  auditEntries: [
    { id: "a-1", occurredAt: "2026-06-17T08:55:00.000Z", actorRole: "platform_owner", action: "tenant:provision", category: "provisioning", outcome: "success", tenantRef: "tenant-aurora", wormAnchored: true, mappedFr: "FR-IAM-006" },
    { id: "a-2", occurredAt: "2026-06-17T08:50:00.000Z", actorRole: "platform_sre", action: "resource:quota:manage", category: "config_change", outcome: "success", tenantRef: "tenant-borealis", wormAnchored: true, mappedFr: "FR-IAM-006" },
    { id: "a-3", occurredAt: "2026-06-17T08:42:00.000Z", actorRole: "platform_owner", action: "breakglass:open", category: "content_access", outcome: "success", tenantRef: "tenant-aurora", wormAnchored: true, mappedFr: "FR-REC-009" },
    { id: "a-4", occurredAt: "2026-06-17T08:30:00.000Z", actorRole: "platform_billing", action: "calls:read", category: "content_access", outcome: "denied", tenantRef: "tenant-borealis", wormAnchored: true, mappedFr: "FR-IAM-008" },
    { id: "a-5", occurredAt: "2026-06-17T08:10:00.000Z", actorRole: "platform_sre", action: "auth:login", category: "auth", outcome: "success", tenantRef: "platform", wormAnchored: true, mappedFr: "FR-IAM-006" },
    { id: "a-6", occurredAt: "2026-06-17T07:58:00.000Z", actorRole: "platform_owner", action: "policy:guardrail:manage", category: "config_change", outcome: "success", tenantRef: "platform", wormAnchored: true, mappedFr: "FR-IAM-006" },
  ],
  breakGlassSessions: [
    { id: "bg-1", tier: "B", status: "active", tenantRef: "tenant-aurora", reasonCode: "INCIDENT-SUPPORT", requestedBy: "ops-sre-1", approvedBy: "ops-owner-1", durationMin: 60, remainingMin: 42, tenantApprovalRequired: true, tenantApproved: true, notified: true, mappedFr: "FR-IAM-009" },
    { id: "bg-2", tier: "B", status: "expired", tenantRef: "tenant-borealis", reasonCode: "QA-REVIEW", requestedBy: "ops-sre-2", approvedBy: "ops-owner-1", durationMin: 120, remainingMin: 0, tenantApprovalRequired: false, tenantApproved: false, notified: true, mappedFr: "FR-IAM-009" },
    { id: "bg-3", tier: "B", status: "pending_approval", tenantRef: "tenant-cobalt", reasonCode: "INCIDENT-SUPPORT", requestedBy: "ops-sre-1", approvedBy: null, durationMin: 60, remainingMin: 60, tenantApprovalRequired: true, tenantApproved: false, notified: false, mappedFr: "FR-IAM-009" },
    { id: "bg-4", tier: "A", status: "active", tenantRef: "tenant-borealis", reasonCode: "METRIC-VIEW", requestedBy: "ops-sre-2", approvedBy: "ops-sre-2", durationMin: 60, remainingMin: 30, tenantApprovalRequired: false, tenantApproved: false, notified: false, mappedFr: "FR-IAM-009" },
  ],
  securityEvents: [
    { id: "se-1", type: "auth_anomaly", severity: "medium", status: "investigating", occurredAt: "2026-06-17T08:40:00.000Z", mappedFr: "FR-IAM-006" },
    { id: "se-2", type: "rate_limit_breach", severity: "low", status: "resolved", occurredAt: "2026-06-17T07:20:00.000Z", mappedFr: "FR-IAM-006" },
    { id: "se-3", type: "policy_violation", severity: "high", status: "open", occurredAt: "2026-06-17T08:05:00.000Z", mappedFr: "FR-LLM-007" },
  ],
};

export async function getAudit(): Promise<AuditSnapshot> {
  const snap = PLACEHOLDER_SNAPSHOT;
  assertNoPii(snap); // ALTIN KURAL: yapısal iş-içeriği/son-müşteri PII yok (BRD §17.7)
  return snap;
}
