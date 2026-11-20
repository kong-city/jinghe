#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CDP 实测 v1.0.1 五条 UI 改动。"""
import base64
import json
import os
import socket
import struct
import sys
import time
import urllib.request

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9232
PAGE_PORT = sys.argv[2] if len(sys.argv) > 2 else "54978"


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
            res = r["result"]["result"]
            if "exceptionDetails" in r["result"]:
                return "ERR: " + str(r["result"].get("exceptionDetails", {}).get("text", ""))
            return res.get("value")


def main():
    s = connect()
    ev(s, 'location.href="http://127.0.0.1:%s/"' % PAGE_PORT, 1)
    time.sleep(3)

    print("=== ① 状态栏：全页显示 + sticky 固定 ===")
    for pg in ("home", "process", "kb", "refine", "revise", "settings", "about"):
        ev(s, 'document.querySelector(\'.nav-item[data-page="%s"]\').click()' % pg, 10 + len(pg))
        time.sleep(0.3)
        r = ev(s, '''(function(){
          var sb=document.getElementById('statusbar');
          var cs=getComputedStyle(sb);
          return JSON.stringify({hidden:sb.hidden, visible:sb.offsetHeight>0,
                                 position:cs.position, bottom:cs.bottom});
        })()''', 30 + len(pg))
        print("   %-8s %s" % (pg, r))

    print("\n=== ② 关于页描述 ===")
    ev(s, 'document.querySelector(\'.nav-item[data-page="about"]\').click()', 50)
    time.sleep(0.5)
    r = ev(s, '''(function(){
      var c=Array.from(document.querySelectorAll('#page-about .card'))
        .find(function(x){var t=x.querySelector('.card-title');return t&&t.textContent==='日志与数据';});
      var sub=c.querySelector('.card-sub');
      return JSON.stringify({text:sub.textContent, lines:Math.round(sub.offsetHeight/parseFloat(getComputedStyle(sub).lineHeight))});
    })()''', 51)
    print("  ", r)

    print("\n=== ③ 修订页同步滚动 ===")
    ev(s, 'document.querySelector(\'.nav-item[data-page="revise"]\').click()', 60)
    time.sleep(0.5)
    r = ev(s, '''(function(){
      var chk=document.getElementById('reviseSyncCheck');
      var iframe=document.getElementById('revisePreviewHtml');
      var pre=document.getElementById('revisePreviewMd');
      return JSON.stringify({hasCheck:!!chk, sandbox:iframe.getAttribute('sandbox'),
        hasPre:!!pre, syncLabel:document.querySelector('.sync-toggle')?
          document.querySelector('.sync-toggle').textContent.trim():''});
    })()''', 61)
    print("  控件:", r)
    # 验证同步逻辑存在（postMessage 通道）
    r = ev(s, '''(function(){
      var src=document.querySelector('script[defer]')?'external':'';
      // 通过勾选并派发滚动事件，观察是否不报错（真正内容需产物，这里验证绑定）
      var chk=document.getElementById('reviseSyncCheck');
      chk.checked=true; chk.dispatchEvent(new Event('change'));
      var pre=document.getElementById('revisePreviewMd');
      pre.scrollTop=50; pre.dispatchEvent(new Event('scroll'));
      return JSON.stringify({checked:chk.checked, scrollTop:pre.scrollTop});
    })()''', 62)
    print("  勾选+滚动:", r)

    print("\n=== ④ 导航顺序 ===")
    r = ev(s, '(function(){return JSON.stringify(Array.from(document.querySelectorAll(".nav-item")).map(function(b){return b.getAttribute("data-page")}))})()', 70)
    print("  ", r)

    print("\n=== ⑤ 组件长文案已清 ===")
    ev(s, 'document.querySelector(\'.nav-item[data-page="settings"]\').click()', 80)
    time.sleep(0.5)
    r = ev(s, '''(function(){
      var card=document.getElementById('componentsCard');
      return JSON.stringify({hasLongText:card.textContent.indexOf('下列组件用于')>=0,
        hasList:!!document.getElementById('componentList')});
    })()''', 81)
    print("  ", r)
    s.close()


if __name__ == "__main__":
    main()
