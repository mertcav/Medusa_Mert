#!/usr/bin/env python3
# WBS 13.2.4 — P-04 probe davranış testi (stdlib-only). Probe'un üç kapısının (validate/check/selftest)
# çıkış kodu 0 döndürdüğünü doğrular; CI'da tek komutla koşulabilir.
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROBE = os.path.join(HERE, "..", "p04_providers_probe.py")


def run(cmd):
    r = subprocess.run([sys.executable, PROBE, cmd], capture_output=True, text=True)
    ok = r.returncode == 0
    print(f"  [{'PASS' if ok else 'FAIL'}] probe {cmd} → exit {r.returncode}")
    if not ok:
        print(r.stdout[-2000:])
    return ok


def main():
    results = [run(c) for c in ("selftest", "check", "validate")]
    passed = sum(results)
    print(f"\nbehavior: {passed}/{len(results)} {'🟢' if passed == len(results) else '🔴'}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
