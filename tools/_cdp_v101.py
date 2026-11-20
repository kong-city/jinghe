#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CDP 实测 v1.0.1 四条 UI 改动。"""
import base64
import json
import os
import socket
import struct
import sys
import time
import urllib.request

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9231
PAGE_PORT = sys.argv[2] if len(sys.argv) > 2 else "54979"


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

    print("=== ① 版本号 ===")
    print("  headerTag:", ev(s, 'document.getElementById("headerTag").textContent', 2))

    print("\n=== ② 关于页「日志与数据」两行 ===")
    ev(s, 'document.querySelector(\'.nav-item[data-page="about"]\').click()', 10)
    time.sleep(2)
    r = ev(s, '''(function(){
      var card=Array.from(document.querySelectorAll('#page-about .card'))
        .find(function(c){return c.querySelector('.card-title') &&
          c.querySelector('.card-title').textContent==='日志与数据';});
      if(!card) return 'NO_CARD';
      var title=card.querySelector('.card-title').textContent;
      var rows=Array.from(card.querySelectorAll('.about-log-row')).map(function(x){
        return {path:x.querySelector('b').textContent, btn:x.querySelector('button').textContent};
      });
      return JSON.stringify({title:title, rows:rows});
    })()''', 11)
    print("  ", r)

    print("\n=== ③ 设置页无日志区块 ===")
    ev(s, 'document.querySelector(\'.nav-item[data-page="settings"]\').click()', 20)
    time.sleep(1)
    r = ev(s, '''(function(){
      var p=document.getElementById('page-settings');
      return JSON.stringify({hasLogCard:p.textContent.indexOf('日志与数据')>=0,
        hasOldBtn:!!document.getElementById('btnOpenSettingsFile')});
    })()''', 21)
    print("  ", r)

    print("\n=== ④ 组件列表 OCR 行 ===")
    ev(s, 'document.querySelector(\'.nav-item[data-page="settings"]\').click()', 30)
    time.sleep(2)
    r = ev(s, '''(function(){
      var rows=Array.from(document.querySelectorAll('#componentList .component-row')).map(function(x){
        return {cid:x.getAttribute('data-cid'),
                name:x.querySelector('.component-name')?x.querySelector('.component-name').textContent:'',
                btn:x.querySelector('button')?x.querySelector('button').textContent:'',
                hasProgress:!!x.querySelector('[data-role="progress"]'),
                hasBadge:!!x.querySelector('[data-role="badge"]')};
      });
      return JSON.stringify(rows);
    })()''', 31)
    print("  ", r)

    print("\n=== ⑤ 状态栏按页显隐 ===")
    for pg in ("home", "about", "process", "kb", "refine", "settings"):
        ev(s, 'document.querySelector(\'.nav-item[data-page="%s"]\').click()' % pg, 40 + len(pg))
        time.sleep(0.4)
        r = ev(s, '''(function(){
          var sb=document.getElementById('statusbar');
          return JSON.stringify({hidden:sb.hidden, visible:sb.offsetHeight>0});
        })()''', 60 + len(pg))
        print("   %-8s %s" % (pg, r))
    s.close()


if __name__ == "__main__":
    main()
