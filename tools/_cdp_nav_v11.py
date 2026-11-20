#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CDP 实测 v1.1.0 新导航：7 项切换、页面元素、知识库端点、无重叠。"""
import base64
import json
import os
import socket
import struct
import sys
import time
import urllib.request

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9230
PAGE_PORT = sys.argv[2] if len(sys.argv) > 2 else "54980"


def connect():
    for _ in range(15):
        try:
            pages = json.loads(urllib.request.urlopen(
                "http://127.0.0.1:%d/json" % PORT, timeout=3).read())
            break
        except Exception:
            time.sleep(1)
    else:
        raise SystemExit("无法连调试端口")
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


def ev(s, expr, rid):
    send(s, {"id": rid, "method": "Runtime.evaluate",
             "params": {"expression": expr, "returnByValue": True}})
    while True:
        r = recv(s)
        if r.get("id") == rid:
            return r["result"]["result"].get("value")


def main():
    s = connect()
    ev(s, 'location.href="http://127.0.0.1:%s/"' % PAGE_PORT, 1)
    time.sleep(3)
    navs = ev(s, '(function(){return JSON.stringify(Array.from(document.querySelectorAll(".nav-item")).map(function(b){return b.getAttribute("data-page")}))})()', 2)
    print("导航项:", navs)

    pages = ["home", "process", "kb", "refine", "revise", "settings", "about"]
    print("\n=== 逐页切换实测 ===")
    for i, pg in enumerate(pages):
        r = ev(s, '''(function(){
          var b=document.querySelector('.nav-item[data-page="%s"]');
          if(!b) return 'NO_NAV';
          b.click();
          var page=document.getElementById('page-%s');
          var title=document.getElementById('pageTitle');
          var visible=page && !page.hidden;
          var others=Array.from(document.querySelectorAll('.page')).filter(function(p){return !p.hidden}).map(function(p){return p.id});
          return JSON.stringify({visible:visible, title:title?title.textContent:'', shown:others});
        })()''' % (pg, pg), 10 + i)
        print("  %-8s %s" % (pg, r))

    print("\n=== 加工页按钮分布 ===")
    ev(s, 'document.querySelector(\'.nav-item[data-page="process"]\').click()', 30)
    time.sleep(1)
    btns = ev(s, '''(function(){
      var p=document.getElementById('page-process');
      var bs=Array.from(p.querySelectorAll('button')).filter(function(b){return !b.hidden})
             .map(function(b){return b.textContent.trim()||b.id});
      return JSON.stringify(bs);
    })()''', 31)
    print("  可见按钮:", btns)

    print("\n=== 知识库页端点实测 ===")
    ev(s, 'document.querySelector(\'.nav-item[data-page="kb"]\').click()', 40)
    time.sleep(2)
    stats = ev(s, '(function(){var e=document.getElementById("kbStats");return e?e.textContent:"NO_EL"})()', 41)
    print("  状态显示:", stats)
    # 直接打后端端点验证
    try:
        with urllib.request.urlopen("http://127.0.0.1:%s/api/kb/status" % PAGE_PORT, timeout=10) as r:
            print("  /api/kb/status:", r.read().decode()[:200])
    except Exception as exc:
        print("  端点失败:", exc)

    print("\n=== 重叠检测（首页主干）===")
    ev(s, 'document.querySelector(\'.nav-item[data-page="home"]\').click()', 50)
    time.sleep(1)
    overlap = ev(s, '''(function(){
      var run=document.getElementById('btnRun').getBoundingClientRect();
      var prev=document.getElementById('btnPreview').getBoundingClientRect();
      var out=document.getElementById('outPath').getBoundingClientRect();
      return JSON.stringify({run_top:run.top, out_bottom:out.bottom,
        run_after_out:run.top>out.bottom, prev_same_row:Math.abs(run.top-prev.top)<5});
    })()''', 51)
    print("  ", overlap)
    s.close()


if __name__ == "__main__":
    main()
