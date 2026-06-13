#!/usr/bin/env python3
"""media_latency_probe.py — Telekom medya-streaming gecikme ölçüm hattı (WBS 0.2.1, →ADR-002).

Amaç: Twilio Media Streams / Telnyx Media Streaming (WebSocket) ve ham SIP/RTP (SBC/BYOC)
entegrasyon modlarında **medya streaming gecikmesini** sağlayıcı-nötr, tekrarlanabilir biçimde
ölçmek ve SAD §20 gecikme bütçesindeki "Ağ/medya ~50–100 ms (P95)" kalemine göre kapı (gate)
uygulamak.

Tasarım ilkeleri (CLAUDE.md):
- **Vendor-neutral:** Araç hiçbir sağlayıcı seçmez; ölçüt-tabanlı sonuç üretir. Sağlayıcı bağlantısı
  yalnız `--url` ile dışarıdan verilir (sır/credential dosyaya YAZILMAZ; ortam değişkeniyle geçilir).
- **stdlib-only:** Harici bağımlılık yok (gen_rtm.py / gen_adr_index.py disiplini).
- **Self-test edilebilir:** Dahili loopback WebSocket echo sunucusu ile gerçek credential olmadan
  uçtan uca ölçülebilir (CI'da koşar).

Modlar:
  serve    — Yerel WS echo sunucusu (loopback self-test / PoC köprüsü taklidi).
  probe    — Bir WS echo/bridge ucuna 8 kHz/20 ms çerçeveleme ile medya akıtır, frame-RTT ölçer.
  stats    — Ham RTT örnek JSON'undan P50/P95/P99/jitter/loss/MOS-vekil türetir + bütçe kapısı.
  compare  — Çok sağlayıcılı ölçüm JSON'larından karşılaştırma matrisi (markdown) üretir.

Çerçeve modeli telefoni gerçeğini yansıtır: 8 kHz, 20 ms paket (50 fps), G.711 μ-law (160 bayt/çerçeve).
WebSocket taşıma, Twilio/Telnyx "media" JSON mesaj biçimini taklit eder (base64 payload).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import socket
import struct
import sys
import threading
import time

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

# Telefoni medya sabitleri (8 kHz, 20 ms çerçeve).
FRAME_MS = 20
FRAMES_PER_SEC = 1000 // FRAME_MS  # 50
ULAW_BYTES_PER_FRAME = 160  # 8000 Hz * 0.020 s * 1 bayt

# SAD §20 gecikme bütçesi — medya/ağ kalemi (tek-yön, P95). Kapı (gate) eşiği.
BUDGET_MEDIA_ONEWAY_P95_MS = 100.0
BUDGET_MEDIA_ONEWAY_P95_GREEN_MS = 50.0  # ideal bant (yeşil)


# ----------------------------------------------------------------------------
# Minimal RFC 6455 WebSocket (stdlib socket üzerinde; text+binary, parça yok)
# ----------------------------------------------------------------------------
def _recv_exactly(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("bağlantı erken kapandı")
        buf.extend(chunk)
    return bytes(buf)


def _ws_send(sock: socket.socket, data: bytes, *, opcode: int = 0x2, mask: bool) -> None:
    """Tek WebSocket çerçevesi gönder (FIN=1). opcode 0x1=text, 0x2=binary, 0x8=close."""
    header = bytearray()
    header.append(0x80 | opcode)
    length = len(data)
    mask_bit = 0x80 if mask else 0x00
    if length < 126:
        header.append(mask_bit | length)
    elif length < 65536:
        header.append(mask_bit | 126)
        header.extend(struct.pack(">H", length))
    else:
        header.append(mask_bit | 127)
        header.extend(struct.pack(">Q", length))
    if mask:
        mask_key = os.urandom(4)
        header.extend(mask_key)
        data = bytes(b ^ mask_key[i % 4] for i, b in enumerate(data))
    sock.sendall(bytes(header) + data)


def _ws_recv(sock: socket.socket) -> tuple[int, bytes]:
    """Tek WebSocket çerçevesi al → (opcode, payload). Parçalanmış çerçeve beklenmez."""
    b0, b1 = _recv_exactly(sock, 2)
    opcode = b0 & 0x0F
    masked = bool(b1 & 0x80)
    length = b1 & 0x7F
    if length == 126:
        length = struct.unpack(">H", _recv_exactly(sock, 2))[0]
    elif length == 127:
        length = struct.unpack(">Q", _recv_exactly(sock, 8))[0]
    mask_key = _recv_exactly(sock, 4) if masked else b""
    payload = _recv_exactly(sock, length) if length else b""
    if masked:
        payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
    return opcode, payload


def _ws_handshake_server(sock: socket.socket) -> None:
    """Sunucu tarafı WS el sıkışma."""
    data = b""
    while b"\r\n\r\n" not in data:
        data += sock.recv(1024)
    key = ""
    for line in data.decode("latin-1").split("\r\n"):
        if line.lower().startswith("sec-websocket-key:"):
            key = line.split(":", 1)[1].strip()
    accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
    resp = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
    )
    sock.sendall(resp.encode())


def _ws_handshake_client(sock: socket.socket, host: str, port: int, path: str) -> None:
    """İstemci tarafı WS el sıkışma (loopback ucu için yeterli; TLS yok)."""
    key = base64.b64encode(os.urandom(16)).decode()
    req = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    )
    sock.sendall(req.encode())
    data = b""
    while b"\r\n\r\n" not in data:
        data += sock.recv(1024)
    if b"101" not in data.split(b"\r\n", 1)[0]:
        raise ConnectionError(f"WS el sıkışma başarısız: {data[:80]!r}")


# ----------------------------------------------------------------------------
# serve — loopback echo sunucusu
# ----------------------------------------------------------------------------
def cmd_serve(args: argparse.Namespace) -> int:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((args.host, args.port))
    srv.listen(8)
    actual_port = srv.getsockname()[1]
    print(f"echo-server dinliyor ws://{args.host}:{actual_port}{args.path}", flush=True)

    def handle(conn: socket.socket) -> None:
        try:
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            _ws_handshake_server(conn)
            send_lock = threading.Lock()

            def echo(op: int, data: bytes) -> None:
                with send_lock:  # eşzamanlı timer'larda çerçeve karışmasını önle
                    _ws_send(conn, data, opcode=op, mask=False)  # server→client unmasked

            while True:
                opcode, payload = _ws_recv(conn)
                if opcode == 0x8:  # close
                    break
                if args.delay_ms:
                    # Sabit tek-yön gecikme modeli: echo'yu okumayı BLOKLAMADAN ertele
                    # (aksi halde 50 fps akışta kuyruk birikir → yapay tıkanıklık).
                    threading.Timer(args.delay_ms / 1000.0, echo, args=(opcode, payload)).start()
                else:
                    echo(opcode, payload)
        except (ConnectionError, OSError):
            pass
        finally:
            conn.close()

    if args.once:
        conn, _ = srv.accept()
        handle(conn)
        srv.close()
        return 0
    try:
        while True:
            conn, _ = srv.accept()
            threading.Thread(target=handle, args=(conn,), daemon=True).start()
    except KeyboardInterrupt:
        return 0
    finally:
        srv.close()


# ----------------------------------------------------------------------------
# probe — medya akıtıp frame-RTT ölç
# ----------------------------------------------------------------------------
def _build_frame(seq: int, payload_mode: str) -> tuple[bytes, int]:
    """Bir medya çerçevesi kur. seq frame'e gömülür (eşleştirme için). → (bytes, opcode)."""
    audio = bytes((seq + i) & 0xFF for i in range(ULAW_BYTES_PER_FRAME))  # sentetik μ-law
    if payload_mode == "twilio-json":
        msg = {
            "event": "media",
            "sequenceNumber": str(seq),
            "streamSid": "MZ-probe-local",
            "media": {
                "track": "outbound",
                "chunk": str(seq),
                "timestamp": str(seq * FRAME_MS),
                "payload": base64.b64encode(audio).decode(),
            },
            "_seq": seq,  # probe-içi eşleştirme anahtarı
        }
        return json.dumps(msg, separators=(",", ":")).encode(), 0x1  # text
    # binary: 4 bayt big-endian seq + ses
    return struct.pack(">I", seq) + audio, 0x2


def _parse_seq(opcode: int, payload: bytes, payload_mode: str) -> int | None:
    try:
        if payload_mode == "twilio-json":
            return int(json.loads(payload.decode())["_seq"])
        return struct.unpack(">I", payload[:4])[0]
    except (ValueError, KeyError, struct.error, UnicodeDecodeError):
        return None


def cmd_probe(args: argparse.Namespace) -> int:
    url = args.url
    if not url.startswith("ws://"):
        print("HATA: yalnız ws:// destekleniyor (loopback/PoC). Gerçek wss:// için TLS proxy kullan.",
              file=sys.stderr)
        return 2
    rest = url[len("ws://"):]
    hostport, _, path = rest.partition("/")
    path = "/" + path
    host, _, port_s = hostport.partition(":")
    port = int(port_s) if port_s else 80

    sock = socket.create_connection((host, port), timeout=args.timeout)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    _ws_handshake_client(sock, host, port, path)

    total = args.frames
    send_ts: dict[int, float] = {}
    rtts_ms: list[float] = []
    recv_seqs: set[int] = set()
    done = threading.Event()

    def receiver() -> None:
        received = 0
        while received < total and not done.is_set():
            try:
                opcode, payload = _ws_recv(sock)
            except (ConnectionError, OSError):
                break
            if opcode == 0x8:
                break
            seq = _parse_seq(opcode, payload, args.payload_mode)
            now = time.perf_counter()
            if seq is not None and seq in send_ts:
                rtts_ms.append((now - send_ts[seq]) * 1000.0)
                recv_seqs.add(seq)
                received += 1
        done.set()

    rx = threading.Thread(target=receiver, daemon=True)
    rx.start()

    interval = FRAME_MS / 1000.0
    start = time.perf_counter()
    for seq in range(total):
        frame, opcode = _build_frame(seq, args.payload_mode)
        send_ts[seq] = time.perf_counter()
        try:
            _ws_send(sock, frame, opcode=opcode, mask=True)  # client→server masked (RFC 6455)
        except (ConnectionError, OSError):
            break
        # 50 fps pacing (gerçek telefoni akışı gibi)
        target = start + (seq + 1) * interval
        slack = target - time.perf_counter()
        if slack > 0:
            time.sleep(slack)

    done.wait(timeout=args.timeout)
    done.set()
    try:
        _ws_send(sock, b"", opcode=0x8, mask=True)
    except OSError:
        pass
    sock.close()

    result = _summarize(rtts_ms, sent=total, received=len(recv_seqs),
                        provider=args.provider, mode=args.payload_mode, url=url)
    out = json.dumps(result, indent=2, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(out + "\n")
        print(f"yazıldı: {args.out}")
    print(out)
    return 0 if result["gate"]["pass"] else 1


# ----------------------------------------------------------------------------
# İstatistik çekirdeği (saf — test edilebilir)
# ----------------------------------------------------------------------------
def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return float("nan")
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    rank = pct / 100.0 * (len(sorted_vals) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = rank - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def _jitter_ms(rtts_ms: list[float]) -> float:
    """RFC 3550 benzeri ardışık tek-yön gecikme farkı ortalaması (tek-yön ≈ RTT/2)."""
    one_way = [r / 2.0 for r in rtts_ms]
    if len(one_way) < 2:
        return 0.0
    diffs = [abs(one_way[i] - one_way[i - 1]) for i in range(1, len(one_way))]
    return sum(diffs) / len(diffs)


def _mos_proxy(one_way_p95_ms: float, loss_pct: float, jitter_ms: float) -> float:
    """Basit ITU-T E-model vekili (sağlayıcı karşılaştırması için göreli skor, mutlak değil).
    R = 93.2 − Id(gecikme) − Ie(kayıp); MOS ≈ 1 + 0.035R + 7e-6·R(R-60)(100-R)."""
    delay = one_way_p95_ms + jitter_ms  # etkin gecikme
    id_factor = 0.024 * delay + 0.11 * max(0.0, delay - 177.3)
    ie_factor = 30.0 * (loss_pct / 100.0) ** 0.5 * 5  # kayba kaba duyarlılık
    r = max(0.0, min(100.0, 93.2 - id_factor - ie_factor))
    mos = 1 + 0.035 * r + 7e-6 * r * (r - 60) * (100 - r)
    return round(max(1.0, min(4.5, mos)), 2)


def _summarize(rtts_ms: list[float], *, sent: int, received: int,
               provider: str, mode: str, url: str) -> dict:
    s = sorted(rtts_ms)
    loss_pct = round(100.0 * (sent - received) / sent, 3) if sent else 0.0
    rtt_p50 = round(_percentile(s, 50), 3)
    rtt_p95 = round(_percentile(s, 95), 3)
    rtt_p99 = round(_percentile(s, 99), 3)
    one_way_p95 = round(rtt_p95 / 2.0, 3) if s else float("nan")
    jitter = round(_jitter_ms(rtts_ms), 3)
    mos = _mos_proxy(one_way_p95 if s else 999, loss_pct, jitter)
    if not s:
        verdict = "VERİ-YOK"
    elif one_way_p95 <= BUDGET_MEDIA_ONEWAY_P95_GREEN_MS:
        verdict = "YEŞİL"
    elif one_way_p95 <= BUDGET_MEDIA_ONEWAY_P95_MS:
        verdict = "SARI"
    else:
        verdict = "KIRMIZI"
    return {
        "provider": provider,
        "payload_mode": mode,
        "url": url,
        "frame_ms": FRAME_MS,
        "fps": FRAMES_PER_SEC,
        "samples": {"sent": sent, "received": received, "loss_pct": loss_pct},
        "rtt_ms": {"p50": rtt_p50, "p95": rtt_p95, "p99": rtt_p99,
                   "min": round(s[0], 3) if s else None,
                   "max": round(s[-1], 3) if s else None,
                   "mean": round(sum(s) / len(s), 3) if s else None},
        "one_way_ms": {"p95_est": one_way_p95},
        "jitter_ms": jitter,
        "mos_proxy": mos,
        "gate": {
            "budget_oneway_p95_ms": BUDGET_MEDIA_ONEWAY_P95_MS,
            "green_oneway_p95_ms": BUDGET_MEDIA_ONEWAY_P95_GREEN_MS,
            "measured_oneway_p95_ms": one_way_p95 if s else None,
            "verdict": verdict,
            "pass": bool(s) and one_way_p95 <= BUDGET_MEDIA_ONEWAY_P95_MS,
        },
        "iz": "SAD §20 (Ağ/medya P95 ≤100ms); ADR-002; FR-RTC-001; FR-TEL-002",
    }


# ----------------------------------------------------------------------------
# stats — ham RTT örnek dosyasından özet
# ----------------------------------------------------------------------------
def cmd_stats(args: argparse.Namespace) -> int:
    with open(args.samples, encoding="utf-8") as fh:
        data = json.load(fh)
    rtts = data["rtt_ms_samples"] if isinstance(data, dict) else data
    result = _summarize([float(x) for x in rtts],
                        sent=int(data.get("sent", len(rtts))) if isinstance(data, dict) else len(rtts),
                        received=int(data.get("received", len(rtts))) if isinstance(data, dict) else len(rtts),
                        provider=(data.get("provider") if isinstance(data, dict) else None) or args.provider,
                        mode=args.payload_mode, url="(offline)")
    out = json.dumps(result, indent=2, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(out + "\n")
    print(out)
    return 0 if result["gate"]["pass"] else 1


# ----------------------------------------------------------------------------
# compare — çok sağlayıcılı karşılaştırma matrisi (markdown)
# ----------------------------------------------------------------------------
def cmd_compare(args: argparse.Namespace) -> int:
    rows = []
    for path in args.results:
        with open(path, encoding="utf-8") as fh:
            rows.append(json.load(fh))
    lines = [
        "| Sağlayıcı / mod | RTT P50 | RTT P95 | RTT P99 | Tek-yön P95 | Jitter | Kayıp % | MOS-vekil | Kapı |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        g = r["gate"]
        badge = {"YEŞİL": "🟢", "SARI": "🟡", "KIRMIZI": "🔴", "VERİ-YOK": "⚪"}.get(g["verdict"], "?")
        rtt = r["rtt_ms"]
        lines.append(
            f"| {r.get('provider','?')} / {r.get('payload_mode','?')} "
            f"| {rtt['p50']} | {rtt['p95']} | {rtt['p99']} "
            f"| {r['one_way_ms']['p95_est']} | {r['jitter_ms']} "
            f"| {r['samples']['loss_pct']} | {r['mos_proxy']} "
            f"| {badge} {g['verdict']} |"
        )
    lines.append("")
    lines.append(f"> Kapı: tek-yön P95 ≤ {BUDGET_MEDIA_ONEWAY_P95_MS:.0f} ms (SAD §20). "
                 f"Yeşil bant ≤ {BUDGET_MEDIA_ONEWAY_P95_GREEN_MS:.0f} ms. "
                 "Değerler ölçüm koşuluna bağlıdır; sağlayıcı seçimi 0.2.6'da bütünsel yapılır (vendor-neutral).")
    table = "\n".join(lines)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(table + "\n")
        print(f"yazıldı: {args.out}")
    print(table)
    return 0


# ----------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Telekom medya-streaming gecikme ölçüm hattı (WBS 0.2.1)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("serve", help="loopback WS echo sunucusu")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8765)
    sp.add_argument("--path", default="/media")
    sp.add_argument("--delay-ms", type=float, default=0.0, help="yapay tek-yön gecikme (senaryo)")
    sp.add_argument("--once", action="store_true", help="tek bağlantı işle ve çık")
    sp.set_defaults(func=cmd_serve)

    pp = sub.add_parser("probe", help="WS ucuna medya akıt, frame-RTT ölç")
    pp.add_argument("--url", required=True, help="ws://host:port/path")
    pp.add_argument("--frames", type=int, default=500, help="çerçeve sayısı (500 = 10 sn)")
    pp.add_argument("--payload-mode", choices=["twilio-json", "binary"], default="twilio-json")
    pp.add_argument("--provider", default="loopback")
    pp.add_argument("--timeout", type=float, default=10.0)
    pp.add_argument("--out", help="sonuç JSON dosyası")
    pp.set_defaults(func=cmd_probe)

    st = sub.add_parser("stats", help="ham RTT örneklerinden özet + kapı")
    st.add_argument("samples", help="JSON: {rtt_ms_samples:[...], sent, received, provider} veya [..]")
    st.add_argument("--provider", default="(dosya)")
    st.add_argument("--payload-mode", default="(n/a)")
    st.add_argument("--out")
    st.set_defaults(func=cmd_stats)

    cp = sub.add_parser("compare", help="çok sağlayıcılı karşılaştırma matrisi")
    cp.add_argument("results", nargs="+", help="probe/stats çıktısı JSON dosyaları")
    cp.add_argument("--out")
    cp.set_defaults(func=cmd_compare)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
