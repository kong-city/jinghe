#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""架构师端到端实测：单进程内起 AppServer → 跑真实 PDF → 轮询到结束。

用法：python tools/arch_e2e_probe.py <pdf路径> <outdir> [超时秒]
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from test_app import AppServer  # 复用测试夹具（真实 HTTP 服务）


def main() -> int:
    if len(sys.argv) < 3:
        print("用法: arch_e2e_probe.py <pdf> <outdir> [timeout]", file=sys.stderr)
        return 2
    pdf = Path(sys.argv[1]).resolve()
    outdir = Path(sys.argv[2]).resolve()
    timeout = float(sys.argv[3]) if len(sys.argv) > 3 else 1200.0
    outdir.mkdir(parents=True, exist_ok=True)

    srv = AppServer(patch_open=True, workdir=str(ROOT), cwd=str(ROOT))
    srv.start(timeout=60)
    try:
        status, obj = srv.post_json(
            "/api/run", {"input": str(pdf), "outdir": str(outdir)})
        print("任务受理:", status, obj.get("ok"), flush=True)
        if status != 200 or not obj.get("ok"):
            print("受理失败:", obj)
            return 1
        since = 0
        t0 = time.time()
        seen_msgs = set()
        while time.time() - t0 < timeout:
            status, d = srv.get_json("/api/progress?since=%d" % since)
            for ev in d.get("events", []):
                msg = (ev.get("message") or ev.get("text") or "")
                if msg and msg not in seen_msgs and any(
                        k in msg for k in ("OCR", "版面", "完成", "失败", "降级")):
                    seen_msgs.add(msg)
                    print("  [%.0fs] %s" % (time.time() - t0, str(msg)[:110]), flush=True)
            since = d.get("next", since)
            if not d.get("running"):
                print("结束: state=%s elapsed=%.0fs" % (
                    d.get("state"), time.time() - t0), flush=True)
                # 列产物
                s, art = srv.get_json("/api/artifacts?outdir=" + str(outdir))
                if s == 200:
                    for item in art.get("items", art.get("md", [])):
                        print("  产物:", item.get("name"), flush=True)
                return 0
            time.sleep(2)
        print("超时 %.0fs" % timeout, flush=True)
        return 3
    finally:
        srv.stop()


if __name__ == "__main__":
    sys.exit(main())
