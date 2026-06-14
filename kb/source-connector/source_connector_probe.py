#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
source_connector_probe.py — WBS 6.1.2 SharePoint/Confluence connector (FR-KB-002)

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only KURUMSAL KAYNAK CONNECTOR referans
uygulaması + statik kapı. 6.1.1 ingest connector tek doküman ALIR (upload/web); bu görev SAD §10.1
offline indeksleme hattının İKİNCİ aşaması olan kurumsal kaynak connector'ı uygular:

  SharePoint site / Confluence space ──► [EnterpriseSourceConnector] ──► enumerate + delta + ACL-map
        │                                                                        │
        └─ her doküman ham baytı ──► (6.1.1 FormatExtractor) ──► NormalizedDocument + kaynak metadata
                                                                                │ (6.1.3 chunk→embed→index)

Connector'ın işi: kurumsal sisteme BAĞLANIR (endpoint allowlist + SSRF + auth), kapsamı (site/library/
space) sayfalı ENUMERATE eder, change-token/cursor ile ARTIMSAL (delta) senkronize eder, kaynak
İZİNLERİNİ (SharePoint sharingScope+roleAssignment / Confluence read restriction / generic visibility)
classification + acl_ref + source_principals'a EŞLER (→6.1.4), her dokümanın ham baytını 6.1.1
FormatExtractor SPI'sine DEVREDER (ayıklamayı yeniden YAZMAZ — S5), çıktıyı kaynak-sistem metadata ile
zenginleştirir. Çıktıyı 6.1.3 chunk→embed→index+versiyonlama TÜKETİR.

KAPSAM AYRIMI (S10 — bilinçli sınır): chunk/embed/index/versiyonlama → 6.1.3; doküman-bazı erişim
yetkisi UYGULAMA → 6.1.4 (connector yalnız metadata EŞLER); içerik bayatlama/TTL → 6.1.5; vector store
namespace fiziksel → 1.1.7; retrieval/rerank/trim → 6.2.x. Bu motor embedding ÜRETMEZ, vektör YAZMAZ,
erişim KARARI (granted/denied) üretmez.

Komutlar:
  validate           source-connector-spec.json'ı invariant'lara (S1–S10) + config kayıt defterine
                     doğrular (statik; sunucu/credential gerekmez).
  sync <sample>      Deterministik SyncEngine — senaryo run'larını işler (full + delta) → SyncResult'lar
                     + HARD kapılar (S1–S10) → çıkış kodu. SharePoint/Confluence native snapshot'larını
                     parse eder + 6.1.1 ayıklayıcılarına devreder.
  selftest           İyi/kötü senaryolar + her connector'ı sürerek kapıların doğru tetiklendiğini kanıtlar.
  schema             Beklenen spec/sample şeklini özetler.

Vendor-neutral (ADR-002): SharePoint/Confluence/genel kaynak adapter'ları TEK EnterpriseSourceConnector
SPI arkasındadır; canlıda Microsoft Graph / Confluence REST istemcisi aynı imza arkasına TAKILIR.
Determinizm: sanal saat + tamsayı sürüm belirteci (Date.now/rastgele YOK). Spec/config/sample'larda
sır/credential ve gerçek PII DEĞERİ yok (snapshot içerikleri sentetik — FR-TST-008).
"""
import base64
import json
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "source-connector-spec.json")
PROFILES_CFG = os.path.join(HERE, "config", "source-connector-profiles.json")
FIXTURES_DIR = os.path.join(HERE, "samples", "fixtures")

# 6.1.1 ingest connector'ı (FormatExtractor SPI) YENİDEN KULLAN — ayıklama/normalizasyon devri (S5).
_ING_DIR = os.path.join(os.path.dirname(HERE), "ingest-connector")
sys.path.insert(0, _ING_DIR)
import ingest_connector_probe as ING  # noqa: E402
ING_FIXTURES_DIR = ING.FIXTURES_DIR

# Kayıtlı kurumsal kaynak connector'ları (vendor-neutral; canlıda gerçek istemci aynı SPI arkası).
CONNECTORS = ["sharepoint", "confluence", "generic"]

# Connector hata taksonomisi (API §11.6 ruhu — kaynak-bağlantıya özgü). DETERMİNİSTİK + müşteriye sızmaz.
CONNECTION_CLASSES = {
    "AUTH_FAILED", "FORBIDDEN", "NOT_FOUND", "THROTTLED", "TIMEOUT", "UNAVAILABLE",
    "ENDPOINT_NOT_ALLOWED", "SSRF_BLOCKED", "REGION_VIOLATION", "MISSING_TENANT_CONTEXT",
    "INVALID_CURSOR", "UNSUPPORTED_CONNECTOR",
}
RETRYABLE_CLASSES = {"THROTTLED", "TIMEOUT", "UNAVAILABLE"}
# 6.1.1'den devralınan ayıklama hata sınıfları (bir öğenin ayıklama hatası senkronu durdurmaz — S8).
DELEGATED_CLASSES = set(ING.ERROR_CLASSES)
ALL_ERROR_CLASSES = CONNECTION_CLASSES | DELEGATED_CLASSES

CLASSIFICATIONS = {"public", "internal", "confidential", "restricted"}

GATE_IDS = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10"]

SECRET_RE = re.compile(
    r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer|client[_-]?secret|access[_-]?token)\b"
    r"\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}"
)
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")
CREDIT_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,16}\b")
# Çıktıda credential alanı sızıntısı taraması.
CRED_FIELD_RE = re.compile(r"(?i)(token|secret|password|bearer|credential|client_secret)")


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_placeholder(v):
    return isinstance(v, str) and PLACEHOLDER_RE.match(v) is not None


# ─────────────────────────────────────────────────────────────────────────────
# Bağlantı hata sinyali (yapısal taksonomi — S8)
# ─────────────────────────────────────────────────────────────────────────────
class ConnError(Exception):
    def __init__(self, cls, detail, retryable=None):
        super().__init__(detail)
        self.cls = cls
        self.detail = detail
        self.retryable = retryable if retryable is not None else (cls in RETRYABLE_CLASSES)


# ─────────────────────────────────────────────────────────────────────────────
# SSRF / endpoint allowlist (S7)
# ─────────────────────────────────────────────────────────────────────────────
_PRIVATE_HOST_RE = re.compile(
    r"^(?:localhost|127\.\d+\.\d+\.\d+|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|"
    r"169\.254\.\d+\.\d+|172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+|0\.0\.0\.0|\[?::1\]?)$",
    re.IGNORECASE,
)


def _host_of(endpoint):
    """Endpoint URL'inden host (port'suz, küçük harf) çıkar. Şema yoksa ham kabul."""
    m = re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://([^/]+)", endpoint or "")
    host = m.group(1) if m else (endpoint or "")
    host = host.split("@")[-1]          # userinfo'yu at
    host = host.split(":")[0]           # port'u at
    return host.strip().lower()


def check_endpoint(endpoint, allowed_hosts, ssrf_guard):
    """SSRF guard (özel/iç IP) → allowlist suffix eşleşme. İhlal → ConnError."""
    host = _host_of(endpoint)
    if not host:
        raise ConnError("ENDPOINT_NOT_ALLOWED", "kaynak endpoint yok")
    if ssrf_guard and (_PRIVATE_HOST_RE.match(host) or host.endswith(".internal") or host.endswith(".local.")):
        raise ConnError("SSRF_BLOCKED", "özel/iç host reddedildi: %s" % host)
    if not any(host == h or host.endswith("." + h) or host.endswith(h) for h in allowed_hosts):
        raise ConnError("ENDPOINT_NOT_ALLOWED", "host allowlist dışı: %s" % host)
    return host


# ─────────────────────────────────────────────────────────────────────────────
# EnterpriseSourceConnector SPI — connector adapter'ları (vendor-neutral, ADR-002)
#   Her adapter native snapshot'ı ortak SourceItem'a normalize eder + native ACL'i eşler.
# ─────────────────────────────────────────────────────────────────────────────
class SourceItem(object):
    __slots__ = ("external_id", "title", "fmt", "version", "deleted", "content",
                 "content_type", "acl_native", "last_modified", "fault", "source_uri")

    def __init__(self, external_id, title, fmt, version, deleted, content,
                 content_type, acl_native, last_modified, fault, source_uri):
        self.external_id = external_id
        self.title = title
        self.fmt = fmt
        self.version = version
        self.deleted = deleted
        self.content = content
        self.content_type = content_type
        self.acl_native = acl_native
        self.last_modified = last_modified
        self.fault = fault
        self.source_uri = source_uri


class BaseConnector(object):
    name = "base"
    scope_kind = "collection"

    def normalize(self, native):
        raise NotImplementedError

    def map_acl(self, acl_native):
        raise NotImplementedError

    def list_changes(self, items, cursor):
        """Delta: cursor (int) üzeri sürümler. → (upserts, deletions, new_cursor). Deterministik sıra."""
        cursor = cursor or 0
        upserts = [it for it in items if not it.deleted and it.version > cursor]
        deletions = [it for it in items if it.deleted and it.version > cursor]
        upserts.sort(key=lambda it: (it.version, it.external_id))
        deletions.sort(key=lambda it: (it.version, it.external_id))
        new_cursor = max([cursor] + [it.version for it in items]) if items else cursor
        return upserts, deletions, new_cursor

    def fetch_content(self, item):
        """Öğe baytını getir; arıza işaretliyse yapısal ConnError fırlat."""
        if item.fault:
            raise ConnError(item.fault, "kaynak öğe arızası: %s" % item.fault)
        raw = _read_item_bytes(item.content)
        if raw is None:
            raise ConnError("NOT_FOUND", "öğe içeriği yok")
        return raw


class SharePointConnector(BaseConnector):
    name = "sharepoint"
    scope_kind = "site/drive"

    def normalize(self, native):
        return SourceItem(
            external_id=native["id"],
            title=native.get("name") or native.get("title"),
            fmt=native.get("format"),
            version=int(native.get("version", native.get("etag_n", 1))),
            deleted=bool(native.get("deleted", False)),
            content=native.get("content", {}),
            content_type=(native.get("file") or {}).get("mimeType") or native.get("content_type"),
            acl_native=native.get("permissions", {}),
            last_modified=int(native.get("version", 1)),
            fault=native.get("fault"),
            source_uri=native.get("webUrl") or native.get("source_uri"),
        )

    def map_acl(self, acl_native):
        scope = (acl_native or {}).get("sharingScope", "organization")
        ra = (acl_native or {}).get("roleAssignments", [])
        principals = sorted(r.get("principal") for r in ra if r.get("principal"))
        if scope == "anonymous":
            cls, restricted = "public", False
        elif scope == "organization":
            cls, restricted = "internal", False
        else:  # specific — yalnız atanan principal'lar görür
            restricted = True
            cls = "restricted" if any(r.get("role") in ("owner", "fullControl") for r in ra) else "confidential"
        acl_ref = "sp:%s:%s" % (scope, ",".join(principals)) if principals else "sp:%s" % scope
        return {"classification": cls, "principals": principals, "acl_ref": acl_ref, "restricted": restricted}


class ConfluenceConnector(BaseConnector):
    name = "confluence"
    scope_kind = "space"

    def normalize(self, native):
        ver = native.get("version")
        vnum = int(ver.get("number") if isinstance(ver, dict) else (ver or 1))
        links = native.get("_links", {}) or {}
        return SourceItem(
            external_id=native["id"],
            title=native.get("title"),
            fmt=native.get("format"),
            version=vnum,
            deleted=bool(native.get("deleted", False)),
            content=native.get("content", native.get("body", {})),
            content_type=native.get("content_type"),
            acl_native=native.get("restrictions", {}),
            last_modified=vnum,
            fault=native.get("fault"),
            source_uri=links.get("webui") or native.get("source_uri"),
        )

    def map_acl(self, acl_native):
        an = acl_native or {}
        if an.get("space_anonymous"):
            return {"classification": "public", "principals": [], "acl_ref": "cf:anonymous", "restricted": False}
        read = an.get("read", {}) or {}
        users = read.get("users", []) or []
        groups = read.get("groups", []) or []
        principals = sorted(["user:" + u for u in users] + ["group:" + g for g in groups])
        if not principals:
            # Space varsayılanı: space üyeleri görür (genel kurumsal) → internal.
            return {"classification": "internal", "principals": [], "acl_ref": "cf:space-default", "restricted": False}
        return {"classification": "confidential", "principals": principals,
                "acl_ref": "cf:read:%s" % ",".join(principals), "restricted": True}


class GenericConnector(BaseConnector):
    name = "generic"
    scope_kind = "collection"

    def normalize(self, native):
        return SourceItem(
            external_id=native["id"],
            title=native.get("title"),
            fmt=native.get("format"),
            version=int(native.get("version", 1)),
            deleted=bool(native.get("deleted", False)),
            content=native.get("content", {}),
            content_type=native.get("content_type"),
            acl_native=native.get("acl", {}),
            last_modified=int(native.get("version", 1)),
            fault=native.get("fault"),
            source_uri=native.get("uri") or native.get("source_uri"),
        )

    def map_acl(self, acl_native):
        an = acl_native or {}
        vis = an.get("visibility", "internal")
        cls = vis if vis in CLASSIFICATIONS else "internal"
        principals = sorted(an.get("principals", []) or [])
        return {"classification": cls, "principals": principals,
                "acl_ref": "dms:%s:%s" % (cls, ",".join(principals)) if principals else "dms:%s" % cls,
                "restricted": cls in ("confidential", "restricted")}


CONNECTOR_REGISTRY = {
    "sharepoint": SharePointConnector,
    "confluence": ConfluenceConnector,
    "generic": GenericConnector,
}


def _read_item_bytes(content):
    """SourceItem içeriğini bayta çevir: inline_text | bytes_b64 | fixture (lokal sonra 6.1.1 dizini)."""
    if not isinstance(content, dict):
        return None
    if "inline_text" in content:
        return content["inline_text"].encode("utf-8")
    if "bytes_b64" in content:
        return base64.b64decode(content["bytes_b64"])
    if "fixture" in content:
        for d in (FIXTURES_DIR, ING_FIXTURES_DIR):
            path = os.path.join(d, content["fixture"])
            if os.path.exists(path):
                with open(path, "rb") as f:
                    return f.read()
        return None
    return None


# ─────────────────────────────────────────────────────────────────────────────
# SyncEngine — bağlantı kapıları + enumerate/delta + ayıklama devri + SyncResult
# ─────────────────────────────────────────────────────────────────────────────
class SyncEngine(object):
    def __init__(self, profile):
        self.p = profile
        self.allowed_connectors = set(profile.get("allowed_connectors", CONNECTORS))
        self.allowed_hosts = list(profile.get("allowed_source_hosts", []))
        self.ssrf_guard = bool(profile.get("ssrf_guard", True))
        self.page_size = int(profile.get("page_size", 200))
        self.max_items = int(profile.get("max_items_per_sync", 100000))
        self.region = profile.get("residency_region", "home")
        self.allowed_regions = set(profile.get("allowed_regions", [self.region]))
        # 6.1.1 ayıklama profili (devir) — dedup/cursor tenant kapsamlı kalıcı.
        self._ing_profile = {
            "allowed_formats": profile.get("allowed_formats", ING.FORMATS),
            "max_bytes": profile.get("max_bytes", 25 * 1024 * 1024),
            "max_units": profile.get("max_units", {}),
            "residency_region": self.region,
            "allowed_regions": list(self.allowed_regions),
            "virtual_t0": profile.get("virtual_t0", 1_000_000),
        }
        self.ingestors = {}   # (tenant,kb) -> ING.IngestConnector (dedup uzayı izole + kalıcı)
        self.cursors = {}     # (connector,tenant,kb,scope) -> cursor (kalıcı, devam edilebilir)

    def _ingestor(self, tenant, kb):
        key = (tenant, kb)
        if key not in self.ingestors:
            self.ingestors[key] = ING.IngestConnector(dict(self._ing_profile))
        return self.ingestors[key]

    def run_sync(self, spec, items):
        """Tek senkron çalıştırma → SyncResult. spec: connector/tenant/kb/scope/endpoint/region/cursor/fault."""
        cname = spec.get("connector")
        tenant = spec.get("tenant_id")
        kb = spec.get("kb_id")
        scope = spec.get("scope")
        region = spec.get("region", self.region)
        endpoint = spec.get("endpoint")
        ckey = (cname, tenant, kb, scope)

        # Cursor çözümü (kalıcı / devam edilebilir — S9).
        cur_spec = spec.get("cursor", None)
        if cur_spec == "prev":
            cursor_in = self.cursors.get(ckey, 0)
        elif cur_spec is None:
            cursor_in = 0
        else:
            cursor_in = int(cur_spec)

        def err(cls, detail, retryable=False):
            return {"connector": cname, "tenant_id": tenant, "kb_id": kb, "scope": scope,
                    "cursor_in": cursor_in, "cursor_out": cursor_in, "items": [], "pages": 0,
                    "counts": {"total": 0, "synced": 0, "deleted": 0, "failed": 0, "duplicate": 0},
                    "status": "sync_error", "error_class": cls, "retryable": retryable, "detail": detail}

        # ── Bağlantı kapıları ──
        if cname not in self.allowed_connectors or cname not in CONNECTOR_REGISTRY:
            return err("UNSUPPORTED_CONNECTOR", "connector '%s' kayıtlı/izinli değil" % cname)
        if not tenant or not kb:
            return err("MISSING_TENANT_CONTEXT", "tenant_id/kb_id zorunlu (fail-closed)")
        if region not in self.allowed_regions:
            return err("REGION_VIOLATION", "kaynak bölgesi %s izinli değil" % region)
        try:
            check_endpoint(endpoint, self.allowed_hosts, self.ssrf_guard)
        except ConnError as e:
            return err(e.cls, e.detail, e.retryable)
        # Bağlantı-seviyesi arıza (auth/throttle/...) — enumerate'ten önce.
        if spec.get("fault"):
            ce = ConnError(spec["fault"], "bağlantı arızası: %s" % spec["fault"])
            return err(ce.cls, ce.detail, ce.retryable)
        if cur_spec not in (None, "prev") and cursor_in < 0:
            return err("INVALID_CURSOR", "cursor negatif")

        conn = CONNECTOR_REGISTRY[cname]()
        upserts, deletions, new_cursor = conn.list_changes(items, cursor_in)

        # S2 — enumerate öğe tavanı.
        total_changes = len(upserts) + len(deletions)
        if total_changes > self.max_items:
            return err("UNAVAILABLE", "öğe sayısı %d > max_items_per_sync %d" % (total_changes, self.max_items))
        pages = (total_changes + self.page_size - 1) // self.page_size if total_changes else 0

        ing = self._ingestor(tenant, kb)
        out_items = []
        n_sync = n_dup = n_fail = 0

        for it in upserts:                       # S2 sayfalı işleme (sıra deterministik)
            rec = self._process_upsert(conn, it, ing, tenant, kb, scope, region)
            if rec["status"] == "synced":
                n_sync += 1
                if rec.get("duplicate_of"):
                    n_dup += 1
            else:
                n_fail += 1
            out_items.append(rec)

        for it in deletions:                     # tombstone — silme yayılımı (S3)
            out_items.append({
                "status": "deleted", "change_type": "delete", "connector": cname,
                "source_system": cname, "external_id": it.external_id, "tenant_id": tenant,
                "kb_id": kb, "source_uri": it.source_uri, "source_version": it.version,
            })

        # Cursor kalıcılaştır (monoton — S9).
        self.cursors[ckey] = max(self.cursors.get(ckey, 0), new_cursor)
        return {
            "connector": cname, "tenant_id": tenant, "kb_id": kb, "scope": scope,
            "cursor_in": cursor_in, "cursor_out": self.cursors[ckey], "pages": pages,
            "items": out_items,
            "counts": {"total": total_changes, "synced": n_sync, "deleted": len(deletions),
                       "failed": n_fail, "duplicate": n_dup},
            "status": "ok", "error_class": None,
        }

    def _process_upsert(self, conn, it, ing, tenant, kb, scope, region):
        base = {"status": "failed", "change_type": "upsert", "connector": conn.name,
                "external_id": it.external_id, "tenant_id": tenant, "kb_id": kb}
        # Öğe baytını getir (throttle/timeout/not-found arızaları yapısal).
        try:
            raw = conn.fetch_content(it)
        except ConnError as e:
            base.update({"error_class": e.cls, "retryable": e.retryable, "detail": e.detail})
            return base
        # Kaynak ACL → standart classification/acl_ref/principals (S4).
        acl = conn.map_acl(it.acl_native)
        # 6.1.1 FormatExtractor'a DEVRET (S5) — ayıklama/normalizasyon/dedup orada.
        src = {
            "source_id": it.external_id, "format_declared": it.fmt,
            "tenant_id": tenant, "kb_id": kb, "region": region,
            "bytes_b64": base64.b64encode(raw).decode("ascii"),
            "content_type": it.content_type,
            "classification": acl["classification"], "acl_ref": acl["acl_ref"],
            "sensitive": acl["restricted"],
            "filename": it.title, "url": it.source_uri,
        }
        doc = ing.ingest_source(src)
        if doc.get("status") != "ingested":
            base.update({"error_class": doc.get("error_class"), "retryable": False,
                         "detail": doc.get("detail")})
            return base
        # Kaynak-sistem metadata ile zenginleştir (S5).
        doc.update({
            "status": "synced", "change_type": "upsert",
            "source_system": conn.name, "external_id": it.external_id,
            "etag": "v%d" % it.version, "source_version": it.version,
            "last_modified": it.last_modified, "source_uri": it.source_uri,
            "source_scope": scope, "source_principals": acl["principals"],
        })
        return doc


# ─────────────────────────────────────────────────────────────────────────────
# Senaryo çalıştırma (full + delta run dizisi) — sanal mutasyon (bump/delete/add)
# ─────────────────────────────────────────────────────────────────────────────
def _native_items(scenario):
    return [dict(n) for n in scenario.get("source", [])]


def _native_version(n):
    """Native snapshot öğesinin sürüm tamsayısı (SharePoint int / Confluence version{number})."""
    v = n.get("version", 1)
    if isinstance(v, dict):
        return int(v.get("number", 1))
    return int(v)


def _set_native_version(n, v):
    """Native öğenin sürümünü ayarla (SharePoint int / Confluence version{number} biçimini koru)."""
    if isinstance(n.get("version"), dict):
        n["version"]["number"] = v
    else:
        n["version"] = v


def run_scenario(scenario, engine):
    """Senaryo run dizisini sırayla çalıştır; her run öncesi snapshot mutasyonu uygula. → run sonuçları + meta."""
    cname = scenario.get("connector")
    base_spec = {k: scenario.get(k) for k in ("connector", "tenant_id", "kb_id", "scope", "endpoint", "region")}
    conn = CONNECTOR_REGISTRY.get(cname, GenericConnector)()
    snapshot = _native_items(scenario)
    vclock = max([_native_version(n) for n in snapshot], default=0)
    runs = scenario.get("runs") or [{"cursor": None}]
    results = []
    run_meta = []
    for run in runs:
        mutated = False
        # bump: mevcut öğeyi düzenle (yeni sürüm > tüm cursor'lar).
        for ext in run.get("bump", []):
            vclock += 1
            for n in snapshot:
                if n.get("id") == ext:
                    _set_native_version(n, vclock)
                    mutated = True
        # delete: tombstone (silme).
        for ext in run.get("delete", []):
            vclock += 1
            for n in snapshot:
                if n.get("id") == ext:
                    n["deleted"] = True
                    _set_native_version(n, vclock)
                    mutated = True
        # add: yeni öğe.
        for newn in run.get("add", []):
            vclock += 1
            nn = dict(newn)
            if _native_version(nn) <= vclock - 1 and "version" not in newn:
                _set_native_version(nn, vclock)
            snapshot.append(nn)
            mutated = True
        spec = dict(base_spec)
        spec["cursor"] = run.get("cursor", None)
        if "fault" in run:
            spec["fault"] = run["fault"]
        items = [conn.normalize(n) for n in snapshot]
        res = engine.run_sync(spec, items)
        results.append(res)
        run_meta.append({"mutated": mutated, "cursor_req": run.get("cursor", None),
                         "expect": run.get("expect", {})})
    return results, run_meta


# ─────────────────────────────────────────────────────────────────────────────
# Kapı değerlendirme (S1–S10) — senaryo run sonuçları üzerinde
# ─────────────────────────────────────────────────────────────────────────────
def evaluate_gates(scenario, results, run_meta, engine):
    checks = []

    def chk(sid, ok, msg):
        checks.append((sid, bool(ok), msg))

    cname = scenario.get("connector")
    tenant = scenario.get("tenant_id")
    kb = scenario.get("kb_id")
    synced = [i for r in results for i in r["items"] if i["status"] == "synced"]
    failed = [i for r in results for i in r["items"] if i["status"] == "failed"]
    deleted = [i for r in results for i in r["items"] if i["status"] == "deleted"]
    sync_errors = [r for r in results if r["status"] == "sync_error"]

    # Beklenti uyumsuzlukları (S8'e katlanır).
    expect_mismatch = []
    for r, m in zip(results, run_meta):
        exp = m.get("expect", {})
        if not exp:
            continue
        if "status" in exp and exp["status"] != r["status"]:
            expect_mismatch.append((r.get("connector"), "status", exp["status"], r["status"]))
        if "error_class" in exp and exp["error_class"] != r.get("error_class"):
            expect_mismatch.append((r.get("connector"), "error_class", exp["error_class"], r.get("error_class")))
        for ck in ("synced", "deleted", "failed"):
            if ck in exp and exp[ck] != r["counts"].get(ck):
                expect_mismatch.append((r.get("connector"), ck, exp[ck], r["counts"].get(ck)))
        if exp.get("delta_noop") and (r["counts"]["synced"] or r["counts"]["deleted"]):
            expect_mismatch.append((r.get("connector"), "delta_noop", 0, r["counts"]["synced"] + r["counts"]["deleted"]))

    # S1 CONNECTOR COVERAGE — connector kayıtlı; synced doc'lar boş-olmayan metin + source_system.
    ok_reg = cname in CONNECTOR_REGISTRY
    ok_docs = all(d.get("source_system") and d["char_count"] > 0 and d["blocks"] for d in synced)
    chk("S1", ok_reg and ok_docs,
        "connector=%s kayıtlı=%s synced=%d hepsi metin+source_system=%s" % (cname, ok_reg, len(synced), ok_docs))

    # S2 ENUMERATION + PAGINATION — sayfa boyutu ≤ tavan; öğe sayısı ≤ max_items; pages tutarlı.
    page_ok = engine.page_size <= 1000
    items_ok = all(r["counts"]["total"] <= engine.max_items for r in results if r["status"] == "ok")
    pages_ok = all(r["pages"] == ((r["counts"]["total"] + engine.page_size - 1) // engine.page_size
                                  if r["counts"]["total"] else 0)
                   for r in results if r["status"] == "ok")
    chk("S2", page_ok and items_ok and pages_ok,
        "page_size=%d≤1000=%s öğe-tavan=%s pages-tutarlı=%s" % (engine.page_size, page_ok, items_ok, pages_ok))

    # S3 INCREMENTAL DELTA — cursor monoton; mutasyonsuz prev-cursor run'ı 0 değişiklik (idempotent).
    ok_runs = [r for r in results if r["status"] == "ok"]
    cursor_mono = all(b["cursor_out"] >= a["cursor_out"] for a, b in zip(ok_runs, ok_runs[1:]))
    noop_bad = []
    for r, m in zip(results, run_meta):
        if r["status"] != "ok":
            continue
        if (not m["mutated"]) and m["cursor_req"] == "prev":
            if r["counts"]["synced"] or r["counts"]["deleted"]:
                noop_bad.append((r["connector"], r["counts"]))
    chk("S3", cursor_mono and not noop_bad,
        "cursor-monoton=%s delta-noop-ihlal=%d" % (cursor_mono, len(noop_bad)))

    # S4 SOURCE ACL MAPPING — her synced doc classification∈vocab + acl_ref + principals; kısıtlı≠public.
    acl_bad = [d for d in synced
               if d.get("classification") not in CLASSIFICATIONS or not d.get("acl_ref")
               or d.get("source_principals") is None]
    leak_pub = [d for d in synced if d.get("sensitive") and d.get("classification") == "public"]
    chk("S4", not acl_bad and not leak_pub,
        "acl-eksik=%d kısıtlı-public-sızıntı=%d" % (len(acl_bad), len(leak_pub)))

    # S5 EXTRACTION DELEGATION — kanonik NormalizedDocument (6.1.1) + kaynak metadata.
    norm_bad = [d for d in synced
                if not d.get("content_hash") or not d.get("text") or not d.get("blocks")
                or ING._CTRL_RE.search(d["text"])
                or d["text"] != unicodedata.normalize("NFC", d["text"])]
    meta_bad = [d for d in synced
                if not d.get("external_id") or not d.get("etag") or d.get("last_modified") is None
                or not d.get("source_uri")]
    chk("S5", not norm_bad and not meta_bad,
        "ayıklama-kanonik-bozuk=%d kaynak-metadata-eksik=%d" % (len(norm_bad), len(meta_bad)))

    # S6 TENANT/KB ISOLATION — her synced/deleted doc senaryo tenant+kb; cross-tenant sızıntı=0.
    cross = [d for d in (synced + deleted) if d.get("tenant_id") != tenant or d.get("kb_id") != kb]
    chk("S6", not cross, "cross-tenant/kb-sızıntı=%d (tenant=%s kb=%s)" % (len(cross), tenant, kb))

    # S7 RESIDENCY + ENDPOINT + SSRF + NO-LOG — synced home-region+no_log+redaction pending; SSRF→0 synced.
    region_bad = [d for d in synced if d.get("residency_region") not in engine.allowed_regions]
    nolog_bad = [d for d in synced if not d.get("no_log") or d.get("redaction_state") != "pending"]
    ssrf_leak = sum(len(r["items"]) for r in results
                    if r["status"] == "sync_error" and r.get("error_class") in ("SSRF_BLOCKED", "ENDPOINT_NOT_ALLOWED"))
    cred_leak = _scan_credential_fields(results)
    chk("S7", not region_bad and not nolog_bad and ssrf_leak == 0 and not cred_leak,
        "region-ihlal=%d no_log/redaction-eksik=%d ssrf-sızıntı=%d cred-sızıntı=%d"
        % (len(region_bad), len(nolog_bad), ssrf_leak, len(cred_leak)))

    # S8 ROBUST + TAXONOMY + THROTTLE — hata sınıfları taksonomide + retryable doğru; beklentiler tuttu.
    bad_cls = [i for i in failed if i.get("error_class") not in ALL_ERROR_CLASSES]
    bad_cls += [r for r in sync_errors if r.get("error_class") not in ALL_ERROR_CLASSES]
    retry_bad = [i for i in failed
                 if "retryable" in i and bool(i["retryable"]) != (i.get("error_class") in RETRYABLE_CLASSES)]
    retry_bad += [r for r in sync_errors
                  if "retryable" in r and bool(r["retryable"]) != (r.get("error_class") in RETRYABLE_CLASSES)]
    chk("S8", not bad_cls and not retry_bad and not expect_mismatch,
        "geçersiz-sınıf=%d retryable-yanlış=%d beklenti-uyumsuz=%d"
        % (len(bad_cls), len(retry_bad), len(expect_mismatch)))

    # S9 SYNC STATE / CURSOR — counts mutabakatı + cursor_out≥cursor_in.
    recon_bad = [r for r in ok_runs
                 if r["counts"]["total"] != r["counts"]["synced"] + r["counts"]["deleted"] + r["counts"]["failed"]]
    cursor_bad = [r for r in ok_runs if r["cursor_out"] < r["cursor_in"]]
    chk("S9", not recon_bad and not cursor_bad,
        "counts-mutabakat-bozuk=%d cursor-gerileme=%d" % (len(recon_bad), len(cursor_bad)))

    # S10 SCOPE BOUNDARY — embedding/vektör/erişim-kararı/credential alanı yok.
    forbidden = ("embedding", "vector", "chunk_ids", "index_id", "access_granted", "access_denied",
                 "token", "secret", "oauth_token")
    leaked = [d for d in synced if any(k in d for k in forbidden)]
    chk("S10", not leaked, "kapsam-dışı/credential alan sızıntısı=%d (embed/index→6.1.3, enforce→6.1.4)" % len(leaked))

    return checks


def _scan_credential_fields(obj, hits=None):
    """Çıktıda credential-benzeri anahtar/değer taraması (S7 cred_leak=0)."""
    if hits is None:
        hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if CRED_FIELD_RE.search(str(k)) and isinstance(v, str) and len(v) >= 12 and not _is_placeholder(v):
                # etag 'vN' / acl_ref gibi kısa/yapısal değerler değil — yalnız uzun opak değerler.
                if SECRET_RE.search("%s=%s" % (k, v)) or re.match(r"^[A-Za-z0-9/\+_\-]{20,}$", v):
                    hits.append(k)
            _scan_credential_fields(v, hits)
    elif isinstance(obj, list):
        for v in obj:
            _scan_credential_fields(v, hits)
    return hits


# ─────────────────────────────────────────────────────────────────────────────
# validate — statik spec/config kapısı
# ─────────────────────────────────────────────────────────────────────────────
def _scan_secrets(obj, path="$"):
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            hits += _scan_secrets(v, "%s.%s" % (path, k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits += _scan_secrets(v, "%s[%d]" % (path, i))
    elif isinstance(obj, str):
        if _is_placeholder(obj):
            return hits
        if SECRET_RE.search(obj):
            hits.append(("secret", path))
        if CREDIT_CARD_RE.search(obj) and "comment" not in path.lower():
            hits.append(("pii-card", path))
    return hits


def validate():
    n = 0
    fail = 0

    def ok(cond, msg):
        nonlocal n, fail
        n += 1
        if not cond:
            fail += 1
            print("  ✗ %s" % msg)

    try:
        spec = _load(SPEC_PATH)
    except Exception as e:
        print("FAIL: spec yüklenemedi: %s" % e)
        return 2
    try:
        cfg = _load(PROFILES_CFG)
    except Exception as e:
        print("FAIL: config yüklenemedi: %s" % e)
        return 2

    for key in ("wbs", "phase", "priority", "trace", "placement", "spi", "connectors",
                "gates", "error_taxonomy", "residency", "pii", "invariants"):
        ok(key in spec, "spec.%s eksik" % key)
    ok(spec.get("wbs") == "6.1.2", "wbs=6.1.2 olmalı")
    ok(spec.get("phase") == "F2", "phase=F2 olmalı")
    ok(spec.get("priority") == "Should", "priority=Should olmalı")

    tr = spec.get("trace", {})
    ok("FR-KB-002" in tr.get("fr", []), "trace.fr FR-KB-002 içermeli")
    ok("SR-KB-002" in tr.get("srs", []), "trace.srs SR-KB-002 içermeli")
    ok("TC-KB-002" in tr.get("rtm", []), "trace.rtm TC-KB-002 içermeli")
    for adr in ("ADR-001", "ADR-002"):
        ok(any(str(a).startswith(adr) for a in tr.get("adr", [])), "trace.adr %s içermeli" % adr)
    ok(any("6.1.1" in str(c) for c in tr.get("consumes", [])), "trace.consumes 6.1.1 içermeli (ayıklama devri)")

    # Connector'lar: ≥2 + kayıtlı sınıf var.
    cspec = spec.get("connectors", {})
    ckeys = {k for k in cspec if not k.startswith("$")}
    for c in ("sharepoint", "confluence"):
        ok(c in ckeys, "connectors.%s eksik" % c)
        ok(c in CONNECTOR_REGISTRY, "CONNECTOR_REGISTRY.%s eksik (kod)" % c)
    ok(len(ckeys & set(CONNECTORS)) >= 2, "en az 2 connector tanımlı olmalı")

    # Gates eşikleri.
    g = spec.get("gates", {})
    for key in ("min_connectors", "max_page_size", "require_delta", "require_acl_mapping",
                "require_extraction_delegation", "max_cross_tenant", "require_tenant_context",
                "require_endpoint_allowlist", "max_ssrf_leak", "require_no_log",
                "require_redaction_pending", "require_cursor_persistence", "max_credential_leak"):
        ok(key in g, "gates.%s eksik" % key)
    ok(g.get("min_connectors") == 2, "min_connectors=2 olmalı")
    ok(g.get("max_cross_tenant") == 0, "max_cross_tenant=0 olmalı")
    ok(g.get("max_ssrf_leak") == 0, "max_ssrf_leak=0 olmalı")
    ok(g.get("max_credential_leak") == 0, "max_credential_leak=0 olmalı")
    ok(g.get("require_extraction_delegation") is True, "require_extraction_delegation=true (6.1.1 devri)")

    # Invariants S1–S10.
    inv_ids = [i.get("id") for i in spec.get("invariants", [])]
    for sid in GATE_IDS:
        ok(sid in inv_ids, "invariant %s eksik" % sid)
    ok(len(inv_ids) == len(set(inv_ids)), "invariant id'leri tekil olmalı")

    # Error taxonomy — kod ile birebir.
    et = spec.get("error_taxonomy", {})
    conn_classes = set(et.get("connection_classes", []))
    ok(conn_classes == CONNECTION_CLASSES,
       "error_taxonomy.connection_classes kod ile birebir (fark: %s)" % (conn_classes ^ CONNECTION_CLASSES))
    ok(set(et.get("retryable_classes", [])) == RETRYABLE_CLASSES, "retryable_classes kod ile birebir")
    ok(set(et.get("delegated_from_6_1_1", [])) <= DELEGATED_CLASSES, "delegated sınıflar 6.1.1 altkümesi")

    # Residency / pii bayrakları.
    res = spec.get("residency", {})
    ok(res.get("region_pin_required") is True, "residency.region_pin_required=true")
    ok(res.get("endpoint_allowlist_required") is True, "residency.endpoint_allowlist_required=true")
    ok(res.get("ssrf_guard_required") is True, "residency.ssrf_guard_required=true")
    ok(res.get("credential_in_repo_forbidden") is True, "residency.credential_in_repo_forbidden=true")
    pii = spec.get("pii", {})
    ok(pii.get("raw_pii_in_spec_forbidden") is True, "pii.raw_pii_in_spec_forbidden=true")
    ok(pii.get("durable_redaction_state") == "pending", "pii.durable_redaction_state=pending")

    # Config profilleri.
    profiles = cfg.get("profiles", {})
    ok(len(profiles) >= 2, "en az 2 profil olmalı")
    for name, pr in profiles.items():
        ac = set(pr.get("allowed_connectors", []))
        ok(ac and ac <= set(CONNECTORS), "profil %s allowed_connectors geçersiz" % name)
        ok(pr.get("allowed_source_hosts"), "profil %s allowed_source_hosts eksik" % name)
        ok(pr.get("page_size", 0) > 0 and pr.get("page_size") <= g.get("max_page_size", 1000),
           "profil %s page_size geçerli" % name)
        ok("residency_region" in pr, "profil %s residency_region eksik" % name)
        ok(pr.get("ssrf_guard") is True, "profil %s ssrf_guard=true" % name)
        af = set(pr.get("allowed_formats", []))
        ok(af and af <= set(ING.FORMATS), "profil %s allowed_formats ⊆ 6.1.1 formatları" % name)

    # Sır + PII taraması.
    sec = _scan_secrets(spec, "spec") + _scan_secrets(cfg, "config")
    ok(not sec, "spec/config sır/PII içermemeli: %s" % sec[:3])

    print("validate: %d kontrol, %d hata" % (n, fail))
    if fail == 0:
        print("OK 🟢 validate %d/%d" % (n - fail, n))
    return 1 if fail else 0


# ─────────────────────────────────────────────────────────────────────────────
# sync <sample>
# ─────────────────────────────────────────────────────────────────────────────
def _profile_for(scenario, cfg):
    pname = scenario.get("profile", "pilot-default")
    pr = dict((cfg.get("profiles", {}).get(pname)) or {})
    if "virtual_t0" in scenario:
        pr["virtual_t0"] = scenario["virtual_t0"]
    return pname, pr


def sync_cmd(sample_path):
    try:
        scenario = _load(sample_path)
        cfg = _load(PROFILES_CFG)
    except Exception as e:
        print("FAIL: yüklenemedi: %s" % e)
        return 2
    pname, pr = _profile_for(scenario, cfg)
    engine = SyncEngine(pr)
    results, run_meta = run_scenario(scenario, engine)
    checks = evaluate_gates(scenario, results, run_meta, engine)

    print("== senaryo: %s (connector=%s, profil=%s, %d run) =="
          % (scenario.get("scenario", "?"), scenario.get("connector"), pname, len(results)))
    for i, r in enumerate(results):
        if r["status"] == "ok":
            c = r["counts"]
            print("  run%d cursor %s→%s pages=%d | synced=%d (dup=%d) deleted=%d failed=%d"
                  % (i, r["cursor_in"], r["cursor_out"], r["pages"],
                     c["synced"], c["duplicate"], c["deleted"], c["failed"]))
            for it in r["items"]:
                if it["status"] == "synced":
                    print("      ✓ %-10s %-5s %-12s → doc=%s %d kar%s"
                          % (it["external_id"], it.get("format"), it.get("classification"),
                             it.get("doc_id"), it.get("char_count", 0),
                             " [DUP]" if it.get("duplicate_of") else ""))
                elif it["status"] == "deleted":
                    print("      ⊘ %-10s DELETE (tombstone)" % it["external_id"])
                else:
                    print("      ✗ %-10s FAILED %s (retryable=%s)"
                          % (it["external_id"], it.get("error_class"), it.get("retryable")))
        else:
            print("  run%d SYNC_ERROR %s (retryable=%s): %s"
                  % (i, r.get("error_class"), r.get("retryable"), r.get("detail")))

    n_fail = 0
    print("  -- kapılar --")
    for sid, okc, msg in checks:
        print("  %s %s: %s" % ("🟢" if okc else "🔴", sid, msg))
        if not okc:
            n_fail += 1

    expect_gate = scenario.get("expect_gate", "pass")
    gate_pass = n_fail == 0
    print("== %s kapı=%s beklenen=%s ==" % (
        scenario.get("scenario", "?"), "GEÇTİ" if gate_pass else "ELEDİ", expect_gate))
    if expect_gate == "pass":
        return 0 if gate_pass else 1
    if gate_pass:
        print("  HATA: bu senaryo elemeliydi ama tüm kapılar geçti")
        return 1
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# selftest
# ─────────────────────────────────────────────────────────────────────────────
def _engine(**over):
    pr = {
        "allowed_connectors": CONNECTORS,
        "allowed_source_hosts": ["sharepoint.com", "atlassian.net", "dms.allowed.example"],
        "allowed_formats": ING.FORMATS,
        "page_size": 50,
        "max_items_per_sync": 100000,
        "max_bytes": 25 * 1024 * 1024,
        "max_units": {"pages": 2000, "rows": 1_000_000, "chars": 5_000_000, "blocks": 100000, "paragraphs": 50000},
        "residency_region": "home",
        "allowed_regions": ["home"],
        "ssrf_guard": True,
        "virtual_t0": 1_000_000,
    }
    pr.update(over)
    return SyncEngine(pr)


def _sp_item(eid, fmt, content, version=1, scope="specific", principals=("group:HR",), **kw):
    n = {"id": eid, "name": eid, "format": fmt, "version": version, "content": content,
         "webUrl": "https://contoso.sharepoint.com/sites/hr/%s" % eid,
         "permissions": {"sharingScope": scope,
                         "roleAssignments": [{"principal": p, "role": "read"} for p in principals]}}
    n.update(kw)
    return n


def _cf_item(eid, fmt, content, version=1, users=(), groups=(), **kw):
    n = {"id": eid, "title": eid, "format": fmt, "version": {"number": version}, "content": content,
         "_links": {"webui": "/spaces/HELP/pages/%s" % eid},
         "restrictions": {"read": {"users": list(users), "groups": list(groups)}}}
    n.update(kw)
    return n


def selftest():
    passed = 0
    failed = 0

    def expect(cond, msg):
        nonlocal passed, failed
        if cond:
            passed += 1
        else:
            failed += 1
            print("  ✗ %s" % msg)

    # 1) SharePoint full sync — çoklu format devri (S1/S5 — SR-KB-002 'en az bir connector senkronize eder').
    eng = _engine()
    sp_scn = {
        "connector": "sharepoint", "tenant_id": "t-1", "kb_id": "kb-1", "scope": "site:hr",
        "endpoint": "https://contoso.sharepoint.com", "region": "home",
        "source": [
            _sp_item("sp-html", "html", {"inline_text": "<html><head><title>Izin</title></head>"
                                         "<body><h1>Izin Politikasi</h1><p>Yillik 14 gun.</p></body></html>"},
                     version=1, scope="organization"),
            _sp_item("sp-csv", "csv", {"inline_text": "soru,yanit\niade,14 gun\nkargo,ucretsiz\n"},
                     version=2, scope="specific", principals=("group:Finance",)),
            _sp_item("sp-txt", "text", {"inline_text": "Sirket gizli notu birinci satir\nikinci satir"},
                     version=3, scope="specific", principals=("user:ceo",), permissions_role="owner"),
        ],
        "runs": [{"cursor": None}],
    }
    r, m = run_scenario(sp_scn, eng)
    by = {i["external_id"]: i for i in r[0]["items"]}
    expect(r[0]["status"] == "ok" and r[0]["counts"]["synced"] == 3, "SP full sync 3 synced")
    expect(by["sp-html"]["classification"] == "internal", "SP organization→internal")
    expect(by["sp-csv"]["classification"] == "confidential" and by["sp-csv"]["sensitive"],
           "SP specific→confidential+sensitive")
    expect(by["sp-html"]["source_system"] == "sharepoint" and by["sp-html"]["source_uri"].startswith("https://"),
           "SP source metadata")
    expect("group:Finance" in by["sp-csv"]["source_principals"], "SP principals eşlenir")
    g = {s: o for s, o, _ in evaluate_gates(sp_scn, r, m, eng)}
    for sid in GATE_IDS:
        expect(g[sid], "SP happy: %s geçmeli" % sid)

    # 2) Confluence full sync — read restriction → confidential (S4).
    eng2 = _engine()
    cf_scn = {
        "connector": "confluence", "tenant_id": "t-1", "kb_id": "kb-1", "scope": "space:HELP",
        "endpoint": "https://acme.atlassian.net", "region": "home",
        "source": [
            _cf_item("cf-open", "html", {"inline_text": "<html><body><h1>SSS</h1><p>Genel bilgi.</p></body></html>"},
                     version=1),
            _cf_item("cf-restricted", "text", {"inline_text": "Yonetim kurulu notu gizli"},
                     version=2, groups=("board",)),
        ],
        "runs": [{"cursor": None}],
    }
    r2, m2 = run_scenario(cf_scn, eng2)
    by2 = {i["external_id"]: i for i in r2[0]["items"]}
    expect(r2[0]["counts"]["synced"] == 2, "CF full sync 2 synced")
    expect(by2["cf-open"]["classification"] == "internal", "CF space-default→internal")
    expect(by2["cf-restricted"]["classification"] == "confidential", "CF restriction→confidential")
    expect(by2["cf-restricted"]["source_system"] == "confluence", "CF source_system")
    expect(all(o for _, o, _ in evaluate_gates(cf_scn, r2, m2, eng2)), "CF happy tüm kapı geçer")

    # 3) Delta idempotency (S3): 2. run prev-cursor + mutasyonsuz → 0 değişiklik.
    eng3 = _engine()
    delta_scn = dict(sp_scn)
    delta_scn = json.loads(json.dumps(sp_scn))  # derin kopya
    delta_scn["runs"] = [{"cursor": None}, {"cursor": "prev", "expect": {"delta_noop": True}}]
    r3, m3 = run_scenario(delta_scn, eng3)
    expect(r3[0]["counts"]["synced"] == 3, "delta run0 full=3")
    expect(r3[1]["counts"]["synced"] == 0 and r3[1]["counts"]["deleted"] == 0, "delta run1 noop=0")
    expect(r3[1]["cursor_out"] == r3[0]["cursor_out"], "delta cursor sabit (idempotent)")
    expect(all(o for _, o, _ in evaluate_gates(delta_scn, r3, m3, eng3)), "delta-noop kapı geçer")

    # 4) Delta bump (S3): düzenlenen öğe yeniden senkronize edilir.
    eng4 = _engine()
    bump_scn = json.loads(json.dumps(sp_scn))
    bump_scn["runs"] = [{"cursor": None}, {"cursor": "prev", "bump": ["sp-csv"], "expect": {"synced": 1}}]
    r4, m4 = run_scenario(bump_scn, eng4)
    expect(r4[1]["counts"]["synced"] == 1 and r4[1]["items"][0]["external_id"] == "sp-csv",
           "bump sonrası yalnız sp-csv yeniden senkron")
    expect(r4[1]["cursor_out"] > r4[0]["cursor_out"], "bump cursor ilerler (monoton)")

    # 5) Delta delete (S3): silme tombstone yayılır.
    eng5 = _engine()
    del_scn = json.loads(json.dumps(sp_scn))
    del_scn["runs"] = [{"cursor": None}, {"cursor": "prev", "delete": ["sp-txt"], "expect": {"deleted": 1}}]
    r5, m5 = run_scenario(del_scn, eng5)
    expect(r5[1]["counts"]["deleted"] == 1 and r5[1]["items"][0]["status"] == "deleted",
           "delete sonrası tombstone")
    expect(r5[1]["items"][0]["change_type"] == "delete", "tombstone change_type=delete")

    # 6) Endpoint allowlist (S7): host allowlist dışı → ENDPOINT_NOT_ALLOWED, 0 synced.
    eng6 = _engine(allowed_source_hosts=["sharepoint.com"])
    bad_ep = {"connector": "confluence", "tenant_id": "t-1", "kb_id": "kb-1", "scope": "space:X",
              "endpoint": "https://evil.example.com", "region": "home",
              "source": [_cf_item("c1", "text", {"inline_text": "x"})],
              "runs": [{"cursor": None, "expect": {"status": "sync_error", "error_class": "ENDPOINT_NOT_ALLOWED"}}]}
    r6, m6 = run_scenario(bad_ep, eng6)
    expect(r6[0]["status"] == "sync_error" and r6[0]["error_class"] == "ENDPOINT_NOT_ALLOWED",
           "allowlist dışı host ENDPOINT_NOT_ALLOWED")

    # 7) SSRF guard (S7): iç/loopback host → SSRF_BLOCKED.
    eng7 = _engine(allowed_source_hosts=["127.0.0.1", "localhost"])  # allowlist'te olsa bile SSRF reddeder
    ssrf = {"connector": "generic", "tenant_id": "t-1", "kb_id": "kb-1", "scope": "c",
            "endpoint": "http://127.0.0.1:8080/api", "region": "home",
            "source": [{"id": "g1", "format": "text", "content": {"inline_text": "x"}, "version": 1,
                        "uri": "http://127.0.0.1/g1", "acl": {"visibility": "internal"}}],
            "runs": [{"cursor": None, "expect": {"status": "sync_error", "error_class": "SSRF_BLOCKED"}}]}
    r7, m7 = run_scenario(ssrf, eng7)
    expect(r7[0]["status"] == "sync_error" and r7[0]["error_class"] == "SSRF_BLOCKED",
           "loopback host SSRF_BLOCKED")
    expect(all(o for _, o, _ in evaluate_gates(ssrf, r7, m7, eng7)), "SSRF senaryo kapı geçer (0 synced)")

    # 8) Missing tenant context (S6 fail-closed).
    eng8 = _engine()
    nt = {"connector": "sharepoint", "kb_id": "kb-1", "scope": "s", "endpoint": "https://x.sharepoint.com",
          "region": "home", "source": [_sp_item("s1", "text", {"inline_text": "x"})],
          "runs": [{"cursor": None, "expect": {"status": "sync_error", "error_class": "MISSING_TENANT_CONTEXT"}}]}
    r8, m8 = run_scenario(nt, eng8)
    expect(r8[0]["status"] == "sync_error" and r8[0]["error_class"] == "MISSING_TENANT_CONTEXT",
           "tenant'sız MISSING_TENANT_CONTEXT")

    # 9) Region violation (S7).
    eng9 = _engine(allowed_regions=["home"])
    rv = {"connector": "sharepoint", "tenant_id": "t-1", "kb_id": "kb-1", "scope": "s",
          "endpoint": "https://x.sharepoint.com", "region": "us-east",
          "source": [_sp_item("s1", "text", {"inline_text": "x"})],
          "runs": [{"cursor": None, "expect": {"error_class": "REGION_VIOLATION"}}]}
    r9, m9 = run_scenario(rv, eng9)
    expect(r9[0]["error_class"] == "REGION_VIOLATION", "yabancı bölge REGION_VIOLATION")

    # 10) Throttle (S8): geçici hata retryable=True + batch dayanıklılığı (diğer öğe synced).
    eng10 = _engine()
    thr = {"connector": "sharepoint", "tenant_id": "t-1", "kb_id": "kb-1", "scope": "s",
           "endpoint": "https://x.sharepoint.com", "region": "home",
           "source": [
               _sp_item("ok", "text", {"inline_text": "gecerli icerik"}, version=1, scope="organization"),
               _sp_item("thr", "text", {"inline_text": "x"}, version=2, fault="THROTTLED"),
           ], "runs": [{"cursor": None}]}
    r10, m10 = run_scenario(thr, eng10)
    items10 = {i["external_id"]: i for i in r10[0]["items"]}
    expect(items10["ok"]["status"] == "synced", "throttle: diğer öğe synced (batch dayanıklı)")
    expect(items10["thr"]["status"] == "failed" and items10["thr"]["error_class"] == "THROTTLED"
           and items10["thr"]["retryable"] is True, "throttle retryable=True")
    expect(r10[0]["counts"]["total"] == r10[0]["counts"]["synced"] + r10[0]["counts"]["failed"],
           "counts mutabakatı (S9)")

    # 11) Delegated extraction error (S8): bozuk PDF → CORRUPT/NEEDS_OCR, senkron durmaz.
    eng11 = _engine()
    bad_pdf = base64.b64encode(b"%PDF-1.4\nnotapdf\n").decode()
    de = {"connector": "generic", "tenant_id": "t-1", "kb_id": "kb-1", "scope": "c",
          "endpoint": "https://dms.allowed.example", "region": "home",
          "source": [
              {"id": "good", "format": "text", "content": {"inline_text": "iyi metin"}, "version": 1,
               "uri": "https://dms.allowed.example/good", "acl": {"visibility": "internal"}},
              {"id": "bad", "format": "pdf", "content": {"bytes_b64": bad_pdf}, "version": 2,
               "uri": "https://dms.allowed.example/bad", "acl": {"visibility": "internal"}},
          ], "runs": [{"cursor": None}]}
    r11, m11 = run_scenario(de, eng11)
    it11 = {i["external_id"]: i for i in r11[0]["items"]}
    expect(it11["good"]["status"] == "synced", "iyi öğe synced")
    expect(it11["bad"]["status"] == "failed" and it11["bad"]["error_class"] in DELEGATED_CLASSES,
           "bozuk öğe devralınan ayıklama hatası (senkron durmaz)")

    # 12) Cross-tenant isolation (S6): aynı içerik iki tenant → ayrı doc, sızıntı yok.
    engA = _engine()
    sA = {"connector": "sharepoint", "tenant_id": "t-acme", "kb_id": "kb-1", "scope": "s",
          "endpoint": "https://x.sharepoint.com", "region": "home",
          "source": [_sp_item("d", "text", {"inline_text": "paylasilan icerik"}, scope="organization")],
          "runs": [{"cursor": None}]}
    sB = json.loads(json.dumps(sA)); sB["tenant_id"] = "t-globex"
    rA, mA = run_scenario(sA, engA)
    rB, mB = run_scenario(sB, engA)   # aynı engine → dedup uzayı tenant kapsamlı
    docA = rA[0]["items"][0]; docB = rB[0]["items"][0]
    expect(docA["tenant_id"] == "t-acme" and docB["tenant_id"] == "t-globex", "her doc kendi tenant'ı")
    expect(docA["content_hash"] == docB["content_hash"] and docB.get("duplicate_of") is None,
           "farklı tenant aynı içerik DUP değil (izole namespace)")
    expect(all(o for _, o, _ in evaluate_gates(sA, rA, mA, engA)), "tenant-A kapı geçer")

    # 13) Content dedup across delta (S5/S9 reuse): aynı içerik bump → hash aynı → duplicate.
    engD = _engine()
    dd = {"connector": "generic", "tenant_id": "t-1", "kb_id": "kb-1", "scope": "c",
          "endpoint": "https://dms.allowed.example", "region": "home",
          "source": [{"id": "x", "format": "text", "content": {"inline_text": "sabit icerik"}, "version": 1,
                      "uri": "https://dms.allowed.example/x", "acl": {"visibility": "internal"}}],
          "runs": [{"cursor": None}, {"cursor": "prev", "bump": ["x"], "expect": {"synced": 1}}]}
    rD, mD = run_scenario(dd, engD)
    expect(rD[1]["items"][0].get("duplicate_of") == "x", "içerik değişmeden bump → content dedup duplicate")

    # 14) Unsupported connector (S8).
    engU = _engine(allowed_connectors=["sharepoint"])
    uc = {"connector": "confluence", "tenant_id": "t-1", "kb_id": "kb-1", "scope": "s",
          "endpoint": "https://x.atlassian.net", "region": "home",
          "source": [_cf_item("c", "text", {"inline_text": "x"})],
          "runs": [{"cursor": None, "expect": {"error_class": "UNSUPPORTED_CONNECTOR"}}]}
    rU, mU = run_scenario(uc, engU)
    expect(rU[0]["error_class"] == "UNSUPPORTED_CONNECTOR", "izinsiz connector UNSUPPORTED_CONNECTOR")

    # 15) Auth failure (S8) permanent retryable=False.
    engAu = _engine()
    au = {"connector": "sharepoint", "tenant_id": "t-1", "kb_id": "kb-1", "scope": "s",
          "endpoint": "https://x.sharepoint.com", "region": "home",
          "source": [_sp_item("s", "text", {"inline_text": "x"})],
          "runs": [{"cursor": None, "fault": "AUTH_FAILED", "expect": {"error_class": "AUTH_FAILED"}}]}
    rAu, mAu = run_scenario(au, engAu)
    expect(rAu[0]["error_class"] == "AUTH_FAILED" and rAu[0]["retryable"] is False, "auth fail kalıcı")

    # 16) Pagination accounting (S2): page_size=2, 5 öğe → 3 sayfa.
    engP = _engine(page_size=2)
    items = [_sp_item("p%d" % i, "text", {"inline_text": "satir %d icerik" % i}, version=i + 1,
                      scope="organization") for i in range(5)]
    pg = {"connector": "sharepoint", "tenant_id": "t-1", "kb_id": "kb-1", "scope": "s",
          "endpoint": "https://x.sharepoint.com", "region": "home", "source": items,
          "runs": [{"cursor": None}]}
    rP, mP = run_scenario(pg, engP)
    expect(rP[0]["pages"] == 3 and rP[0]["counts"]["synced"] == 5, "5 öğe / page_size 2 → 3 sayfa")

    # 17) ACL anonymous → public (S4) ve restricted asla public değil.
    engAn = _engine()
    an = {"connector": "sharepoint", "tenant_id": "t-1", "kb_id": "kb-1", "scope": "s",
          "endpoint": "https://x.sharepoint.com", "region": "home",
          "source": [_sp_item("pub", "text", {"inline_text": "herkese acik duyuru"}, scope="anonymous",
                              principals=())],
          "runs": [{"cursor": None}]}
    rAn, mAn = run_scenario(an, engAn)
    expect(rAn[0]["items"][0]["classification"] == "public", "anonymous→public")

    # 18) validate() temiz spec/config'te 0 döner.
    expect(validate() == 0, "validate() temiz repo'da 0 dönmeli")

    print("\nselftest: %d geçti, %d başarısız" % (passed, failed))
    if failed == 0:
        print("OK 🟢 selftest %d/%d" % (passed, passed))
    return 1 if failed else 0


# ─────────────────────────────────────────────────────────────────────────────
# schema
# ─────────────────────────────────────────────────────────────────────────────
def schema():
    print(__doc__)
    print("Beklenen spec anahtarları: wbs, phase, priority, trace, placement, spi, connectors,")
    print("  gates, error_taxonomy, residency, pii, invariants (S1–S10).")
    print("Sample/senaryo: {scenario, expect_gate(pass|fail), profile, connector(sharepoint|confluence|generic),")
    print("  tenant_id, kb_id, scope, endpoint, region, source[native], runs[]}")
    print("run: {cursor(null|'prev'|int), bump[ids], delete[ids], add[native], fault?, expect?{status,error_class,synced,deleted,failed,delta_noop}}")
    print("SharePoint native: {id,name,format,version,webUrl,file.mimeType,permissions{sharingScope,roleAssignments[]},content,deleted?,fault?}")
    print("Confluence native: {id,title,format,version{number},_links.webui,restrictions{read{users,groups}},content,deleted?,fault?}")
    print("SyncResult: {connector,tenant_id,kb_id,scope,cursor_in,cursor_out,pages,items[],counts{total,synced,deleted,failed,duplicate},status}")
    print("synced item: NormalizedDocument(6.1.1) + source_system/external_id/etag/source_version/last_modified/source_uri/source_scope/source_principals/classification/change_type")
    print("Bağlantı hata sınıfları: %s" % ", ".join(sorted(CONNECTION_CLASSES)))
    print("Devralınan ayıklama hata sınıfları (6.1.1): %s" % ", ".join(sorted(DELEGATED_CLASSES)))
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if cmd == "validate":
        return validate()
    if cmd == "sync":
        if len(sys.argv) < 3:
            print("kullanım: source_connector_probe.py sync <sample.json>")
            return 2
        return sync_cmd(sys.argv[2])
    if cmd == "selftest":
        return selftest()
    if cmd == "schema":
        return schema()
    print("bilinmeyen komut: %s (validate|sync|selftest|schema)" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main())
