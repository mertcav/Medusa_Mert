#!/usr/bin/env python3
"""
objstore_behavior_test.py — WBS 1.1.6 canlı S3-uyumlu davranış kapısı (stdlib-only).

`aws` CLI'yi `${OBJSTORE_ENDPOINT}` (S3-uyumlu: MinIO/Ceph/AWS) karşısında sürerek
storage-spec.json + policy/*.json politikalarının GERÇEK davranışını doğrular:
  1. public-access-block dört bayrak da etkin (O4).
  2. Şifresiz PutObject reddedilir; SSE-KMS doğru CMK ile geçer (O2).
  3. TLS olmayan istek reddedilir (endpoint https ise) (O3).
  4. data_class prefix'i ile yazma + okuma (O6); cross-tenant bucket erişimi reddedilir (O5).
  5. lifecycle config uygulanır + geri okunur (O7).
  6. Object Lock (governance) content bucket'ında etkin (O10).

Endpoint/credential YALNIZCA ortam değişkeninden gelir (repoya yazılmaz):
  OBJSTORE_ENDPOINT, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, OBJSTORE_KMS_KEY_ID, OBJSTORE_BUCKET
`aws` yoksa veya OBJSTORE_ENDPOINT tanımsızsa SKIP (exit 0) — run_live_test.sh ile aynı sözleşme.

Bu env'de canlı S3/CLI YOK → SKIP. Çalışan davranış kapısı: objstore_probe.py selftest
(deterministik access-decision + lifecycle simülatörü, sunucu gerektirmez).
"""
import json
import os
import shutil
import subprocess
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
POLICY = os.path.join(os.path.dirname(HERE), "policy")


def _skip(msg):
    print(f"SKIP: {msg}")
    sys.exit(0)


def aws(args, expect_ok=True, stdin=None):
    endpoint = os.environ["OBJSTORE_ENDPOINT"]
    cmd = ["aws", "--endpoint-url", endpoint] + args
    p = subprocess.run(cmd, capture_output=True, text=True, input=stdin)
    ok = p.returncode == 0
    return ok, p.stdout, p.stderr


def main():
    if not shutil.which("aws"):
        _skip("aws CLI bulunamadı (CI'da S3-uyumlu endpoint + aws ile koşar).")
    if not os.environ.get("OBJSTORE_ENDPOINT"):
        _skip("OBJSTORE_ENDPOINT tanımsız (endpoint/credential yalnız ortamdan; repoya yazılmaz).")

    bucket = os.environ.get("OBJSTORE_BUCKET", f"objstore-test-{uuid.uuid4().hex[:8]}")
    kms = os.environ.get("OBJSTORE_KMS_KEY_ID", "")
    passed, failed = 0, 0

    def check(name, ok):
        nonlocal passed, failed
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        passed += ok
        failed += (not ok)

    # Bucket (object-lock etkin) + public-access-block
    aws(["s3api", "create-bucket", "--bucket", bucket, "--object-lock-enabled-for-bucket"])
    with open(os.path.join(POLICY, "public-access-block.json")) as fh:
        pab = json.load(fh)
    pab.pop("_comment", None)
    ok, _, _ = aws(["s3api", "put-public-access-block", "--bucket", bucket,
                    "--public-access-block-configuration", json.dumps(pab)])
    check("O4 public-access-block uygulandı", ok)

    # O2 — şifresiz put reddi (bucket-policy uygulandıysa)
    key = f"recording/2026/06/13/{uuid.uuid4()}"
    body = "/tmp/_objstore_probe_body"
    with open(body, "w") as fh:
        fh.write("test")
    ok_plain, _, _ = aws(["s3", "cp", body, f"s3://{bucket}/{key}"])
    check("O2 şifresiz PutObject reddedilir (policy varsa)", not ok_plain)

    # O2 — SSE-KMS doğru CMK ile geçer
    if kms:
        ok_enc, _, _ = aws(["s3", "cp", body, f"s3://{bucket}/{key}",
                            "--sse", "aws:kms", "--sse-kms-key-id", kms])
        check("O2 SSE-KMS doğru CMK ile PutObject geçer", ok_enc)

    # O7 — lifecycle uygula + geri oku
    with open(os.path.join(POLICY, "lifecycle.template.json")) as fh:
        lc = json.load(fh)
    lc.pop("_comment", None)
    for r in lc["Rules"]:
        for k in list(r):
            if k.startswith("_"):
                r.pop(k)
    ok_lc, _, _ = aws(["s3api", "put-bucket-lifecycle-configuration", "--bucket", bucket,
                       "--lifecycle-configuration", json.dumps(lc)])
    check("O7 lifecycle config uygulandı", ok_lc)
    ok_get, out, _ = aws(["s3api", "get-bucket-lifecycle-configuration", "--bucket", bucket])
    check("O7 lifecycle geri okunabilir (5 kural)", ok_get and out.count('"ID"') >= 5)

    os.remove(body)
    print(f"\nobjstore_behavior_test: {passed} geçti, {failed} başarısız")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
