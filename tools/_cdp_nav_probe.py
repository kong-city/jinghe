#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CDP 实测：折叠按钮与导航图标 x 坐标（展开态 vs 折叠态）。

stdlib 手写最小 websocket 客户端，连 Edge --remote-debugging-port，
用 Runtime.evaluate 量 DOM 几何。用法：在一个 Bash 调用里先起 Edge
headless 带调试端口，再跑本脚本。
"""
import base64
import json
import os
import socket
import struct
import sys
import time
import urllib.request

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9225
PAGE_PORT = sys.argv[2] if len(sys.argv) > 2 else "54321"


def connect():
    for _ in range(12):
        try:
            pages = json.loads(urllib.request.urlopen(
                "http://127.0.0.1:%d/json" % PORT, timeout=3).read())
            break
        except Exception:
            time.sleep(1)
    else:
        raise SystemExit("无法连调试端口 %d" % PORT)
    ws = next(p["webSocketDebuggerUrl"] for p in pages if p.get("type") == "page")
    path = ws.split(":%d" % PORT, 1)[1]
    s = socket.create_connection(("127.0.0.1", PORT), timeout=10)
    key = base64.b64encode(os.urandom(16)).decode()
    s.sendall((f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{PORT}\r\n"
               f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        buf += s.recv(4096)
    return s


def send(s, o):
    data = json.dumps(o).encode()
    mask = os.urandom(4)
    n = len(data)
    hdr = bytes([0x81])
    hdr += bytes([0x80 | n]) if n < 126 else bytes([0xFE]) + struct.pack(">H", n)
    s.sendall(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))


def recv(s):
    h = s.recv(2)
    n = h[1] & 0x7F
    if n == 126:
        n = struct.unpack(">H", s.recv(2))[0]
    elif n == 127:
        n = struct.unpack(">Q", s.recv(8))[0]
    d = b""
    while len(d) < n:
        d += s.recv(n - len(d))
    return json.loads(d.decode())


def evaluate(s, expr, rid):
    send(s, {"id": rid, "method": "Runtime.evaluate",
             "params": {"expression": expr, "returnByValue": True}})
    while True:
        r = recv(s)
        if r.get("id") == rid:
            return r["result"]["result"].get("value")


def main():
    s = connect()
    # 确保在主页
    evaluate(s, f'location.href="http://127.0.0.1:{PAGE_PORT}/"', 1)
    time.sleep(2)
    probe = """(function(){
      var btn=document.querySelector('#btnToggleNav');
      var icon=document.querySelector('.nav-item svg');
      if(!btn||!icon) return 'NO_ELEMENT';
      var b=btn.getBoundingClientRect(), i=icon.getBoundingClientRect();
      var sb=document.querySelector('.sidebar').getBoundingClientRect();
      return JSON.stringify({btnLeft:+b.left.toFixed(1), btnCenter:+(b.left+b.width/2).toFixed(1),
        iconLeft:+i.left.toFixed(1), iconCenter:+(i.left+i.width/2).toFixed(1),
        sidebarLeft:+sb.left.toFixed(1), sidebarWidth:+sb.width.toFixed(1),
        collapsed:document.querySelector('.app').classList.contains('nav-collapsed')});
    })()"""
    expanded = evaluate(s, probe, 2)
    print("展开态:", expanded)
    # 点折叠
    evaluate(s, "document.querySelector('#btnToggleNav').click()", 3)
    time.sleep(1)
    collapsed = evaluate(s, probe, 4)
    print("折叠态:", collapsed)
    import json as J
    a, b = J.loads(expanded), J.loads(collapsed)
    print()
    print("  按钮 x: 展开 %.1f → 折叠 %.1f （位移 %.1f px）" %
          (a["btnLeft"], b["btnLeft"], b["btnLeft"] - a["btnLeft"]))
    print("  图标 x: 展开 %.1f → 折叠 %.1f （位移 %.1f px）" %
          (a["iconLeft"], b["iconLeft"], b["iconLeft"] - a["iconLeft"]))
    print("  展开态按钮与图标偏差: %.1f px" % (a["btnLeft"] - a["iconLeft"]))
    print("  折叠态按钮与图标偏差: %.1f px" % (b["btnLeft"] - b["iconLeft"]))
    s.close()


if __name__ == "__main__":
    main()
