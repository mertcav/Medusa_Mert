// WBS 13.2.8 — P-08 "Sürüm & Dağıtım (Release) Yönetimi" veri katmanı (seam) + SAF türetme yardımcıları.
//
// ÇEKİRDEK İLKELER (P-01..P-07 ile aynı disiplin; lib/platform/overview.ts + tenants.ts + resources.ts +
// providers.ts + billing.ts + policy.ts + audit.ts):
//  - ALTIN KURAL (BRD §17.7 / FR-IAM-008): L0 platform konsolu YALNIZ platform-geneli sürüm/dağıtım/
//    feature-flag METADATASI gösterir; tenant İŞ İÇERİĞİ (çağrı kaydı, transkript, son-müşteri/PII)
//    GÖSTERİLMEZ. Tipler YAPISAL OLARAK iş-içeriği/PII taşımaz; `assertNoPii` çalışma-anında doğrular.
//    Feature flag'in `enabledTenants` alanı TOPLULAŞTIRILMIŞ SAYIDIR (tenant listesi/kimliği DEĞİL).
//  - İÇERİK (BRD §17.3): platform versiyonlama + feature flag + kademeli yayma (canary/staged rollout).
//    Bu, agent-seviyesi yaşam döngüsü/rollback disiplininin (FR-AGT-005 draft/test/staging/production +
//    FR-AGT-006 tek-işlem rollback) PLATFORM ölçeğine yansımasıdır; ekranın kendisi BRD §17.3 P-08'dir.
//  - SAF/DETERMİNİSTİK: türetme yardımcıları (releaseStageTone/releaseHealthTone/rolloutStrategyTone/
//    flagStatusTone/deploymentOutcomeTone/deploymentTypeTone/countByStage/activeFlagCount/failingReleases/
//    canaryRisks/failedDeployments/rollbackEvents/flagConfigGaps/percentageRollouts) Date.now/rastgelelik
//    içermez → birim-test edilebilir + Python aynası (screens/p08-releases/p08_releases_probe.py).
//  - İŞ MANTIĞI/AUTHZ YOK (SAD §14.4.1 A8): dağıtım / kademeli yayma / rollback / flag aksiyonları UI'da
//    yalnız görsel kapıdır; nihai yetki + zorlama backend'de (12.2.x; permission-key `release:read` +
//    `release:deploy` + `release:rollback` + `featureflag:manage`, SAD §7). RBAC (BRD §17.6): bu ekran
//    `platform_owner`=Yönet + `platform_sre`=Düzenle + `platform_billing`=erişim yok.

// Aktör — L0 platform rolü (tenant rolleri tamamen ayrı; FR-IAM-008).
export type PlatformRole = "platform_owner" | "platform_sre" | "platform_billing";

// Sürüm aşaması (FR-AGT-005 yaşam döngüsü disiplini, platform ölçeğinde):
//  draft → staging → canary → production; rolled_back (FR-AGT-006 rollback ile önceki sürüme dönüş).
export type ReleaseStage = "draft" | "staging" | "canary" | "production" | "rolled_back";

// Sürüm sağlık durumu: healthy (sağlıklı) · degraded (bozulmuş) · failing (başarısız).
export type ReleaseHealth = "healthy" | "degraded" | "failing";

// Feature flag yayma stratejisi (kademeli yayma): disabled (kapalı) · internal (yalnız dahili) ·
// percentage (yüzde bazlı kademeli) · full (tam açık).
export type RolloutStrategy = "disabled" | "internal" | "percentage" | "full";

// Feature flag durumu: active (etkin) · inactive (pasif) · archived (arşiv).
export type FlagStatus = "active" | "inactive" | "archived";

// Dağıtım olayı tipi: promote (ilerletme) · rollback (geri alma, FR-AGT-006) · flag_change (flag değişikliği) ·
// canary_pause (canary durdurma).
export type DeploymentEventType = "promote" | "rollback" | "flag_change" | "canary_pause";

// Dağıtım olayı sonucu: success · in_progress · failed.
export type DeploymentOutcome = "success" | "in_progress" | "failed";

// StatusPill/Alert ile hizalı ton kümesi.
export type Tone = "success" | "warning" | "info" | "danger" | "neutral";

// Platform bileşen sürümü. component VENDOR-NÖTR bileşen adıdır (somut marka değil; ADR-002).
// region NFR 10.7 bölgesi (UK/EU/NA/ME) veya "global".
export interface PlatformRelease {
  id: string;
  version: string; // semver (kod string — ör. "2.5.0-rc1")
  component: string; // vendor-nötr platform bileşeni (ör. "voice-runtime", "orchestrator", "control-plane")
  stage: ReleaseStage;
  rolloutPct: number; // kademeli yayma yüzdesi 0..100
  health: ReleaseHealth;
  region: string; // NFR 10.7: "global" | "UK" | "EU" | "NA" | "ME"
  createdAt: string; // ISO-8601 (sabit yer tutucu — SSR-stabil, Date.now YOK)
  mappedFr: string; // izlenebilirlik (FR-AGT-005/006 vb.) — kod string
}

// Feature flag (kademeli yayma kontrolü). enabledTenants TOPLULAŞTIRILMIŞ SAYIDIR (altın kural; liste değil).
export interface FeatureFlag {
  id: string;
  key: string; // flag anahtarı (kod, çeviri değil — ör. "barge_in_v2")
  status: FlagStatus;
  strategy: RolloutStrategy;
  rolloutPct: number; // percentage stratejisi için kademeli yayma yüzdesi 0..100
  enabledTenants: number; // etkin tenant SAYISI (toplulaştırılmış — izinli; tenant kimliği/listesi DEĞİL)
  updatedAt: string; // ISO-8601 (sabit yer tutucu)
  mappedFr: string;
}

// Dağıtım/rollback olayı — işlemin META verisi (tüm işlemler audit edilir; P-07/FR-IAM-006).
export interface DeploymentEvent {
  id: string;
  occurredAt: string; // ISO-8601 (sabit yer tutucu)
  type: DeploymentEventType;
  actorRole: PlatformRole;
  target: string; // hedef sürüm versiyonu veya flag anahtarı (kod string)
  outcome: DeploymentOutcome;
  mappedFr: string;
}

export interface ReleaseSnapshot {
  generatedAt: string; // ISO-8601 (sabit yer tutucu — SSR-stabil, Date.now YOK)
  releases: PlatformRelease[];
  flags: FeatureFlag[];
  events: DeploymentEvent[];
}

// ── saf türetme yardımcıları ────────────────────────────────────────────────────

// Sürüm aşaması tonu: draft neutral · staging info · canary warning (izlenmeli) · production success ·
// rolled_back neutral.
const RELEASE_STAGE_TONE: Record<ReleaseStage, Tone> = {
  draft: "neutral",
  staging: "info",
  canary: "warning",
  production: "success",
  rolled_back: "neutral",
};
export function releaseStageTone(s: ReleaseStage): Tone {
  return RELEASE_STAGE_TONE[s];
}

// Sürüm sağlık tonu: healthy success · degraded warning · failing danger.
const RELEASE_HEALTH_TONE: Record<ReleaseHealth, Tone> = {
  healthy: "success",
  degraded: "warning",
  failing: "danger",
};
export function releaseHealthTone(h: ReleaseHealth): Tone {
  return RELEASE_HEALTH_TONE[h];
}

// Yayma stratejisi tonu: disabled neutral · internal info · percentage warning (kademeli, izlenmeli) · full success.
const ROLLOUT_STRATEGY_TONE: Record<RolloutStrategy, Tone> = {
  disabled: "neutral",
  internal: "info",
  percentage: "warning",
  full: "success",
};
export function rolloutStrategyTone(s: RolloutStrategy): Tone {
  return ROLLOUT_STRATEGY_TONE[s];
}

// Flag durumu tonu: active success · inactive neutral · archived neutral.
const FLAG_STATUS_TONE: Record<FlagStatus, Tone> = {
  active: "success",
  inactive: "neutral",
  archived: "neutral",
};
export function flagStatusTone(s: FlagStatus): Tone {
  return FLAG_STATUS_TONE[s];
}

// Dağıtım sonucu tonu: success success · in_progress info · failed danger.
const DEPLOYMENT_OUTCOME_TONE: Record<DeploymentOutcome, Tone> = {
  success: "success",
  in_progress: "info",
  failed: "danger",
};
export function deploymentOutcomeTone(o: DeploymentOutcome): Tone {
  return DEPLOYMENT_OUTCOME_TONE[o];
}

// Dağıtım olay tipi tonu: promote info · rollback warning (geri dönüş, dikkat) · flag_change neutral ·
// canary_pause warning.
const DEPLOYMENT_TYPE_TONE: Record<DeploymentEventType, Tone> = {
  promote: "info",
  rollback: "warning",
  flag_change: "neutral",
  canary_pause: "warning",
};
export function deploymentTypeTone(t: DeploymentEventType): Tone {
  return DEPLOYMENT_TYPE_TONE[t];
}

// Sürüm aşama sayımı (özet KPI).
export function countByStage(releases: PlatformRelease[]): Record<ReleaseStage, number> {
  const acc: Record<ReleaseStage, number> = { draft: 0, staging: 0, canary: 0, production: 0, rolled_back: 0 };
  for (const r of releases) acc[r.stage] += 1;
  return acc;
}

// Aktif (etkin) feature flag sayısı.
export function activeFlagCount(flags: FeatureFlag[]): number {
  return flags.filter((f) => f.status === "active").length;
}

// Başarısız sürümler: canlı yayında (production VEYA canary) sağlığı failing olan sürüm id'leri (dağıtım sağlık riski).
export function failingReleases(snap: ReleaseSnapshot): string[] {
  return snap.releases
    .filter((r) => (r.stage === "production" || r.stage === "canary") && r.health === "failing")
    .map((r) => r.id);
}

// Canary riski (FR-AGT-005 kademeli yayma): canary aşamasında sağlığı healthy OLMAYAN (degraded/failing) sürümler
// — production'a ilerletmeden önce incelenmeli.
export function canaryRisks(snap: ReleaseSnapshot): string[] {
  return snap.releases
    .filter((r) => r.stage === "canary" && r.health !== "healthy")
    .map((r) => r.id);
}

// Başarısız dağıtım olayları (outcome=failed) — rollback gerekebilir (FR-AGT-006).
export function failedDeployments(events: DeploymentEvent[]): string[] {
  return events.filter((e) => e.outcome === "failed").map((e) => e.id);
}

// Rollback olayları (tip=rollback) — bilgi amaçlı (FR-AGT-006).
export function rollbackEvents(events: DeploymentEvent[]): string[] {
  return events.filter((e) => e.type === "rollback").map((e) => e.id);
}

// Flag yapılandırma boşluğu: percentage stratejisi seçili ama rolloutPct uçlarda (≤0 disabled ile, ≥100 full ile
// çelişir) → strateji/yüzde tutarsızlığı (yanlış yapılandırma riski).
export function flagConfigGaps(flags: FeatureFlag[]): string[] {
  return flags
    .filter((f) => f.strategy === "percentage" && (f.rolloutPct <= 0 || f.rolloutPct >= 100))
    .map((f) => f.id);
}

// Yüzde-bazlı kademeli yayma uygulayan flag id'leri (strategy=percentage).
export function percentageRollouts(flags: FeatureFlag[]): string[] {
  return flags.filter((f) => f.strategy === "percentage").map((f) => f.id);
}

// ── ALTIN KURAL koruması (iş-içeriği/son-müşteri PII sızıntısı) ───────────────────
// Snapshot yapısı içinde tenant İŞ İÇERİĞİ/SON-MÜŞTERİ PII'sini çağrıştıran ALAN ADI bulunursa hata
// fırlatır. Bu, P-08'in yalnız platform-geneli sürüm/dağıtım/flag METADATASI göstermesini çalışma-anında
// garanti eder (BRD §17.7). enabledTenants (toplulaştırılmış SAYI) izinli olduğundan listede değildir.
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
        throw new Error(`P-08 ALTIN KURAL ihlali: yasak iş-içeriği/PII alanı "${path}.${k}" (BRD §17.7)`);
      }
      assertNoPii((node as Record<string, unknown>)[k], `${path}.${k}`);
    }
  }
}

// ── veri SEAM (yer tutucu) ───────────────────────────────────────────────────────
// Deterministik yer tutucu: platform-geneli sürüm/dağıtım/feature-flag METADATASI (iş-içeriği/PII DEĞİL).
// Gerçek implementasyon (F2 §14.1) Release/Deployment servisi (CI/CD + sürüm kayıtları) + Feature Flag servisi
// + 0.4.7 gözlemlenebilirlik omurgası (deploy sağlık metrikleri) ile beslenir. Bileşen adları VENDOR-NÖTR
// (somut marka değil; ADR-002). Varsayılan profilde tüm production/canary sürümleri sağlıklı + flag'ler
// tutarlı (sağlıklı taban); ihlal/risk senaryoları samples/* altında.
const PLACEHOLDER_SNAPSHOT: ReleaseSnapshot = {
  generatedAt: "2026-06-17T09:00:00.000Z",
  releases: [
    { id: "r-1", version: "2.4.0", component: "voice-runtime", stage: "production", rolloutPct: 100, health: "healthy", region: "global", createdAt: "2026-06-10T10:00:00.000Z", mappedFr: "FR-AGT-005" },
    { id: "r-2", version: "2.5.0-rc1", component: "orchestrator", stage: "canary", rolloutPct: 10, health: "healthy", region: "EU", createdAt: "2026-06-16T14:00:00.000Z", mappedFr: "FR-AGT-005" },
    { id: "r-3", version: "2.4.1", component: "policy-engine", stage: "staging", rolloutPct: 0, health: "healthy", region: "global", createdAt: "2026-06-15T09:00:00.000Z", mappedFr: "FR-AGT-005" },
    { id: "r-4", version: "2.3.8", component: "media-gateway", stage: "rolled_back", rolloutPct: 0, health: "healthy", region: "UK", createdAt: "2026-06-12T11:00:00.000Z", mappedFr: "FR-AGT-006" },
    { id: "r-5", version: "2.6.0-dev", component: "voice-runtime", stage: "draft", rolloutPct: 0, health: "healthy", region: "global", createdAt: "2026-06-17T08:00:00.000Z", mappedFr: "FR-AGT-005" },
  ],
  flags: [
    { id: "f-1", key: "barge_in_v2", status: "active", strategy: "percentage", rolloutPct: 25, enabledTenants: 12, updatedAt: "2026-06-16T15:00:00.000Z", mappedFr: "FR-AGT-005" },
    { id: "f-2", key: "semantic_cache", status: "active", strategy: "full", rolloutPct: 100, enabledTenants: 40, updatedAt: "2026-06-11T09:00:00.000Z", mappedFr: "FR-AGT-005" },
    { id: "f-3", key: "region_routing", status: "active", strategy: "internal", rolloutPct: 0, enabledTenants: 3, updatedAt: "2026-06-14T12:00:00.000Z", mappedFr: "FR-AGT-005" },
    { id: "f-4", key: "legacy_flow", status: "inactive", strategy: "disabled", rolloutPct: 0, enabledTenants: 0, updatedAt: "2026-06-09T09:00:00.000Z", mappedFr: "FR-AGT-005" },
  ],
  events: [
    { id: "e-1", occurredAt: "2026-06-16T14:05:00.000Z", type: "promote", actorRole: "platform_owner", target: "2.5.0-rc1", outcome: "success", mappedFr: "FR-AGT-005" },
    { id: "e-2", occurredAt: "2026-06-12T11:10:00.000Z", type: "rollback", actorRole: "platform_owner", target: "2.3.8", outcome: "success", mappedFr: "FR-AGT-006" },
    { id: "e-3", occurredAt: "2026-06-16T15:00:00.000Z", type: "flag_change", actorRole: "platform_sre", target: "barge_in_v2", outcome: "success", mappedFr: "FR-AGT-005" },
    { id: "e-4", occurredAt: "2026-06-17T08:30:00.000Z", type: "canary_pause", actorRole: "platform_sre", target: "2.5.0-rc1", outcome: "in_progress", mappedFr: "FR-AGT-005" },
  ],
};

export async function getReleases(): Promise<ReleaseSnapshot> {
  const snap = PLACEHOLDER_SNAPSHOT;
  assertNoPii(snap); // ALTIN KURAL: yapısal iş-içeriği/son-müşteri PII yok (BRD §17.7)
  return snap;
}
