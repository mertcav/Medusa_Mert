#!/usr/bin/env python3
"""
cache_behavior_test.py — WBS 1.1.5 canlı Redis davranış kapısı (stdlib-only).

Çalışan iki Redis örneğine (session pool + cache pool) karşı keyspace-spec.json
invariant'larının GERÇEK davranışını doğrular. Minimal RESP istemcisi (socket) ile;
harici bağımlılık YOK. Sır/credential kullanmaz (loopback).

Kullanım:  python3 cache_behavior_test.py <session_port> <cache_port>
Çıkış kodu: 0 tüm assertion geçti, 1 başarısız.
"""
import socket
import sys
import time


class RespError(Exception):
    pass


class Resp:
    """Minimal RESP (RESP2) istemcisi — yalnız test için."""

    def __init__(self, host, port, timeout=5.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.buf = b""

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    def _read_line(self):
        while b"\r\n" not in self.buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RespError("bağlantı kapandı")
            self.buf += chunk
        line, self.buf = self.buf.split(b"\r\n", 1)
        return line

    def _read_n(self, n):
        while len(self.buf) < n + 2:  # +2 = trailing CRLF
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RespError("bağlantı kapandı")
            self.buf += chunk
        data, self.buf = self.buf[:n], self.buf[n + 2:]
        return data

    def _parse(self):
        line = self._read_line()
        t, rest = line[:1], line[1:]
        if t == b"+":
            return rest.decode()
        if t == b"-":
            raise RespError(rest.decode())
        if t == b":":
            return int(rest)
        if t == b"$":
            n = int(rest)
            if n == -1:
                return None
            return self._read_n(n)
        if t == b"*":
            n = int(rest)
            if n == -1:
                return None
            return [self._parse() for _ in range(n)]
        raise RespError(f"beklenmeyen tip: {line!r}")

    def cmd(self, *args):
        parts = [b"*%d\r\n" % len(args)]
        for a in args:
            if isinstance(a, str):
                a = a.encode()
            elif isinstance(a, int):
                a = str(a).encode()
            parts.append(b"$%d\r\n%s\r\n" % (len(a), a))
        self.sock.sendall(b"".join(parts))
        return self._parse()


def wait_ready(host, port, attempts=80, delay=0.1):
    for _ in range(attempts):
        try:
            c = Resp(host, port, timeout=1.0)
            if c.cmd("PING") == "PONG":
                return c
            c.close()
        except (OSError, RespError):
            time.sleep(delay)
    raise RespError(f"{host}:{port} hazır değil")


def info_field(client, field):
    raw = client.cmd("INFO")
    if isinstance(raw, bytes):
        raw = raw.decode(errors="replace")
    for ln in raw.splitlines():
        if ln.startswith(field + ":"):
            return ln.split(":", 1)[1].strip()
    return None


# --------------------------------------------------------------------------- #
def run(session_port, cache_port):
    results = []

    def check(name, cond):
        results.append((name, bool(cond)))
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")

    sess = wait_ready("127.0.0.1", session_port)
    cache = wait_ready("127.0.0.1", cache_port)
    sess.cmd("FLUSHALL")
    cache.cmd("FLUSHALL")

    # --- 1. Pool politikaları gerçekten yüklü (config → runtime) ----------- #
    check("cache pool maxmemory-policy=volatile-lru",
          cache.cmd("CONFIG", "GET", "maxmemory-policy")[1] == b"volatile-lru")
    check("session pool maxmemory-policy=noeviction",
          sess.cmd("CONFIG", "GET", "maxmemory-policy")[1] == b"noeviction")
    check("cache persistence kapalı (save='', appendonly=no)",
          cache.cmd("CONFIG", "GET", "save")[1] == b"" and
          cache.cmd("CONFIG", "GET", "appendonly")[1] == b"no")
    check("session persistence kapalı (save='', appendonly=no)",
          sess.cmd("CONFIG", "GET", "save")[1] == b"" and
          sess.cmd("CONFIG", "GET", "appendonly")[1] == b"no")

    # --- 2. TTL sözleşmesi: her anahtar TTL'li, kalıcı anahtar yok --------- #
    sess.cmd("SET", "{t:A}:sess:c1:state", "dialog", "EX", 1800)
    cache.cmd("SET", "{t:A}:sem:ag1:deadbeef", "cached-answer", "EX", 86400)
    cache.cmd("SET", "{t:A}:tts:v1:cafe", "s3://obj/uri", "EX", 2592000)
    check("session_state TTL pozitif (idle 1800s)", 0 < sess.cmd("TTL", "{t:A}:sess:c1:state") <= 1800)
    check("semantic_cache TTL pozitif (<=24h)", 0 < cache.cmd("TTL", "{t:A}:sem:ag1:deadbeef") <= 86400)
    check("tts_cache_index TTL pozitif (<=30g)", 0 < cache.cmd("TTL", "{t:A}:tts:v1:cafe") <= 2592000)
    # I2: kalıcı (-1) anahtar bulunmamalı
    persistent = [k for k in (cache.cmd("KEYS", "*") or []) if cache.cmd("TTL", k) == -1]
    check("I2 cache'te kalıcı (-1 TTL) anahtar yok", not persistent)

    # --- 3. Tenant namespace izolasyonu (I1 / SEC-15) --------------------- #
    cache.cmd("SET", "{t:B}:sem:ag1:deadbeef", "tenant-B-answer", "EX", 86400)
    a_keys = set(cache.cmd("SCAN", 0, "MATCH", "{t:A}:*", "COUNT", 1000)[1] or [])
    check("SCAN {t:A}:* yalnız A anahtarlarını döndürür (B sızmaz)",
          all(k.startswith(b"{t:A}:") for k in a_keys) and a_keys)

    # --- 4. delete_on_call_end: çağrı sonunda oturum silinir -------------- #
    sess.cmd("DEL", "{t:A}:sess:c1:state")
    check("session delete_on_call_end → anahtar yok", sess.cmd("EXISTS", "{t:A}:sess:c1:state") == 0)

    # --- 5. TTL expiry gerçekten çalışır (ephemeral silme) ---------------- #
    cache.cmd("SET", "{t:A}:sem:ag1:short", "x", "PX", 150)
    before = cache.cmd("EXISTS", "{t:A}:sem:ag1:short")
    time.sleep(0.3)
    after = cache.cmd("EXISTS", "{t:A}:sem:ag1:short")
    check("TTL expiry: anahtar süre dolunca kaybolur", before == 1 and after == 0)

    # --- 6. EVICTION DAVRANIŞI (kritik fark) ------------------------------ #
    # Cache pool: bellek baskısında volatile-lru evict EDER (cache miss = kabul edilebilir).
    cache.cmd("FLUSHALL")
    cache.cmd("CONFIG", "RESETSTAT")
    used = int(info_field(cache, "used_memory"))
    cache.cmd("CONFIG", "SET", "maxmemory", str(used + 2_000_000))  # ~2MB başlık
    blob = "x" * 50_000
    oom_cache = False
    for i in range(200):
        try:
            cache.cmd("SET", f"{{t:A}}:sem:ag1:k{i}", blob, "EX", 86400)
        except RespError as e:
            oom_cache = "OOM" in str(e)
            break
    evicted_cache = int(info_field(cache, "evicted_keys") or 0)
    check("cache pool baskı altında evict eder (volatile-lru, evicted_keys>0)",
          evicted_cache > 0 and not oom_cache)
    cache.cmd("CONFIG", "SET", "maxmemory", "0")

    # Session pool: noeviction → aktif oturum ASLA sessizce düşmez; yazım OOM ile REDDEDİLİR.
    sess.cmd("FLUSHALL")
    sess.cmd("CONFIG", "RESETSTAT")
    used_s = int(info_field(sess, "used_memory"))
    sess.cmd("CONFIG", "SET", "maxmemory", str(used_s + 2_000_000))
    oom_sess = False
    for i in range(200):
        try:
            sess.cmd("SET", f"{{t:A}}:sess:c{i}:state", blob, "EX", 1800)
        except RespError as e:
            oom_sess = "OOM" in str(e)
            break
    evicted_sess = int(info_field(sess, "evicted_keys") or 0)
    check("session pool noeviction: doluyken yazım OOM ile reddedilir (sessiz kayıp yok)",
          oom_sess and evicted_sess == 0)
    sess.cmd("CONFIG", "SET", "maxmemory", "0")

    sess.cmd("FLUSHALL")
    cache.cmd("FLUSHALL")
    sess.close()
    cache.close()

    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    print(f"\ncache_behavior_test: {passed}/{total} assertion geçti")
    return passed == total


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("kullanım: cache_behavior_test.py <session_port> <cache_port>", file=sys.stderr)
        sys.exit(2)
    ok = run(int(sys.argv[1]), int(sys.argv[2]))
    sys.exit(0 if ok else 1)
