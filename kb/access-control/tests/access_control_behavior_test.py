#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 6.1.4 — Doküman bazı erişim yetkisi davranış testleri (T1–T12). Stdlib-only, credential-free,
deterministik. Probe'un selftest'inden BAĞIMSIZ siyah-kutu davranış kontrolü (regresyon kapısı). Çalıştır:
    python3 tests/access_control_behavior_test.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..")))
import access_control_probe as P  # noqa: E402

_fails = []


def check(cond, msg):
    if not cond:
        _fails.append(msg)


PROF = {"require_acl_classifications": ["confidential", "restricted"],
        "redaction_mode": "redact", "default_acl_decision": "deny", "deny_wins": True}


def ctx(**kw):
    base = {"tenant_id": "t-a", "kb_ids": ["kb-1"], "principals": ["role:human_agent"],
            "clearance": "internal", "channel_no_log": False}
    base.update(kw)
    return base


def chunk(**kw):
    base = {"chunk_id": "c", "document_id": "d", "tenant_id": "t-a", "kb_id": "kb-1",
            "namespace": P.IDX._namespace("t-a", "kb-1"), "active": True, "classification": "internal",
            "acl_ref": None, "sensitive": False, "redaction_state": "applied", "content": "metin"}
    base.update(kw)
    return base


# T1 — Happy: aynı clearance + applied → ALLOWED (karar metadata-only).
def t1():
    g = P.AccessGate(PROF)
    d = g.decide(ctx(), chunk())
    check(d["decision"] == "ALLOW" and d["reason"] == "ALLOWED", "T1 happy ALLOWED")


# T2 — Fail-closed: bağlam eksik → MISSING_PRINCIPAL_CONTEXT; hiçbir chunk dönmez (G1).
def t2():
    g = P.AccessGate(PROF)
    check(g.decide({}, chunk())["reason"] == "MISSING_PRINCIPAL_CONTEXT", "T2 boş bağlam deny")
    check(g.decide(ctx(principals=[]), chunk())["reason"] == "MISSING_PRINCIPAL_CONTEXT", "T2b principal yok deny")


# T3 — Namespace izolasyonu (G2): cross-tenant + cross-kb → CROSS_NAMESPACE.
def t3():
    g = P.AccessGate(PROF)
    check(g.decide(ctx(), chunk(tenant_id="t-b", namespace=P.IDX._namespace("t-b", "kb-1")))["reason"]
          == "CROSS_NAMESPACE", "T3 cross-tenant")
    check(g.decide(ctx(), chunk(kb_id="kb-9", namespace=P.IDX._namespace("t-a", "kb-9")))["reason"]
          == "CROSS_NAMESPACE", "T3b cross-kb")


# T4 — Classification lattice monoton (G3).
def t4():
    g = P.AccessGate(PROF)
    check(g.decide(ctx(clearance="internal"), chunk(classification="confidential"))["reason"]
          == "CLASSIFICATION_EXCEEDS_CLEARANCE", "T4 düşük clearance yüksek sınıf deny")
    check(g.decide(ctx(clearance="restricted"), chunk(classification="public"))["decision"] == "ALLOW",
          "T4b yüksek clearance düşük sınıf allow")
    # bilinmeyen sınıf → fail-closed (rank yüksek).
    check(g.decide(ctx(clearance="restricted"), chunk(classification="weird"))["decision"] == "DENY",
          "T4c bilinmeyen sınıf fail-closed")


# T5 — ACL deny-wins (G4) + not-granted + grant + default deny.
def t5():
    acls = {"acl:x": {"default": "deny", "allow": ["group:a"], "deny": ["group:b"]}}
    g = P.AccessGate(PROF, acls)
    ch = chunk(classification="confidential", acl_ref="acl:x")
    check(g.decide(ctx(clearance="confidential", principals=["group:a"]), ch)["decision"] == "ALLOW", "T5 grant")
    check(g.decide(ctx(clearance="confidential", principals=["group:c"]), ch)["reason"] == "ACL_NOT_GRANTED",
          "T5b not granted (default deny)")
    check(g.decide(ctx(clearance="confidential", principals=["group:a", "group:b"]), ch)["reason"]
          == "ACL_EXPLICIT_DENY", "T5c deny wins")


# T6 — ACL_REQUIRED: confidential/restricted + acl_ref yok → deny.
def t6():
    g = P.AccessGate(PROF)
    check(g.decide(ctx(clearance="restricted"), chunk(classification="confidential", acl_ref=None))["reason"]
          == "ACL_REQUIRED", "T6 ACL required")
    # internal acl_ref yok → require_acl değil → allow.
    check(g.decide(ctx(), chunk(classification="internal", acl_ref=None))["decision"] == "ALLOW",
          "T6b internal ACL gerekmez")


# T7 — Çözülemez acl_ref → MALFORMED_ACL fail-closed.
def t7():
    g = P.AccessGate(PROF, {"acl:y": {"allow": ["*"]}})
    check(g.decide(ctx(), chunk(acl_ref="acl:yok"))["reason"] == "MALFORMED_ACL", "T7 malformed acl deny")


# T8 — Sensitive yalnız no-log kanal (G5, FR-KB-010).
def t8():
    g = P.AccessGate(PROF)
    s = chunk(sensitive=True)
    check(g.decide(ctx(channel_no_log=False), s)["reason"] == "SENSITIVE_REQUIRES_NO_LOG", "T8 logged kanal deny")
    check(g.decide(ctx(channel_no_log=True), s)["decision"] == "ALLOW", "T8b no-log allow")


# T9 — Redaction (G6): pending+redact → ALLOWED_REDACTED + ham PII gider; deny modu → REDACTION_PENDING.
def t9():
    g = P.AccessGate(PROF)
    raw = "Eposta test@ornek.com numara 4521 7788 3300 kayitli"
    d = g.decide(ctx(), chunk(redaction_state="pending", content=raw))
    check(d["reason"] == "ALLOWED_REDACTED" and d["redacted"], "T9 pending redact")
    check("test@ornek.com" not in d["content"] and "4521 7788 3300" not in d["content"], "T9b ham PII maskelendi")
    gd = P.AccessGate({"require_acl_classifications": ["confidential", "restricted"], "redaction_mode": "deny",
                       "default_acl_decision": "deny", "deny_wins": True})
    check(gd.decide(ctx(), chunk(redaction_state="pending"))["reason"] == "REDACTION_PENDING", "T9c deny modu")


# T10 — Active-only (G7): inactive → INACTIVE_VERSION.
def t10():
    g = P.AccessGate(PROF)
    check(g.decide(ctx(), chunk(active=False))["reason"] == "INACTIVE_VERSION", "T10 inactive deny")


# T11 — 6.1.3 entegrasyon: gerçek IndexedChunk üzerinden SR-KB-005 (yetkisiz doküman dönmez).
def t11():
    pipe, chunks, _ = P.index_documents([
        {"source_id": "pub", "tenant_id": "t-a", "kb_id": "kb-1", "classification": "public",
         "redaction_state": "not_required", "inline_text": "Genel bilgi metni yeterince uzundur."},
        {"source_id": "conf", "tenant_id": "t-a", "kb_id": "kb-1", "classification": "confidential",
         "acl_ref": "acl:hr", "redaction_state": "applied", "inline_text": "Gizli politika metni."},
    ])
    g = P.AccessGate(PROF, {"acl:hr": {"default": "deny", "allow": ["group:hr"]}})
    decs = g.authorize(ctx(clearance="internal", channel_no_log=True), chunks)
    allowed = {d["document_id"] for d in decs if d["decision"] == "ALLOW"}
    check("pub" in allowed and "conf" not in allowed, "T11 public izinli, confidential yetkisiz (SR-KB-005)")
    check(all(c.get("active") for c in chunks), "T11b indexlenen chunk'lar aktif")


# T12 — Prefilter parity (G8) + audit (G9): sound+complete; audit ham PII'sız.
def t12():
    acls = {"acl:x": {"default": "deny", "allow": ["group:a"], "deny": ["group:b"]}}
    g = P.AccessGate(PROF, acls)
    chunks = [chunk(chunk_id="1", classification="public"),
              chunk(chunk_id="2", classification="confidential", acl_ref="acl:x"),
              chunk(chunk_id="3", tenant_id="t-b", namespace=P.IDX._namespace("t-b", "kb-1"))]
    c = ctx(clearance="confidential", principals=["group:a"], channel_no_log=True)
    decs = g.authorize(c, chunks)
    sound = comp = True
    for ch, d in zip(chunks, decs):
        adm = g.prefilter_admits(c, ch)
        if adm and d["decision"] == "DENY" and d["reason"] in P.STORE_DIM_DENY:
            sound = False
        if d["decision"] == "ALLOW" and not adm:
            comp = False
    check(sound and comp, "T12 prefilter sound+complete")
    import json
    blob = json.dumps(g.audit, ensure_ascii=False)
    check(len(g.audit) == 3 and "content" not in g.audit[0], "T12b audit yapısal, ham içerik yok")
    check(not P.NUM_RE.search(blob) and not P.EMAIL_RE.search(blob), "T12c audit ham PII'sız")


def main():
    for fn in [t1, t2, t3, t4, t5, t6, t7, t8, t9, t10, t11, t12]:
        fn()
    if _fails:
        print("FAIL: %d kontrol başarısız" % len(_fails))
        for m in _fails:
            print("  ✗ %s" % m)
        return 1
    print("OK: 12 davranış grubu geçti")
    return 0


if __name__ == "__main__":
    sys.exit(main())
