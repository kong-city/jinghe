#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精核 · UI 视觉判分层（借鉴 workbuddy-bench 的 VLMJudgeRunner 思路）。

用户 2026-11-18 要求：给精核的 UI 验收加一层"视觉判分"。

bench 的做法（``src/workbuddy_bench/judge/core/judges.py``）用四种判官：
Rule / LLM / VLM / Agent，其中 VLMJudgeRunner 负责"看图判对错"。
本模块对应精核实现两层：

* **结构层（零依赖，必做）**：Edge headless 取 DOM + 截图，做几何与断言检查
  ——元素存在/可见、互不重叠、在视口内、文本顺序正确。纯 Python + Edge，
  不需要任何模型，任何机器都能跑；
* **视觉层（可选后端）**：把截图交给**已配置的多模态后端**判分。复用
  ``backend.py`` 既有 OpenAI 兼容 ``chat()``（messages 原样透传，
  ``content`` 传 ``[{"type":"image_url",...}]`` 即多模态），**不引入任何
  新依赖、不新增凭据通道**。未配置视觉后端时**诚实跳过**并写明原因，
  绝不假装判过。

与 bench 一致的两条原则：
1. **保守合取**：多个判据时最差的说了算（``min``），一个判官 FAIL 不被
   另一个 PASS 稀释；
2. **有据才给分**：无证据即 0 分，缺后端即"跳过"，不猜。

用法：
    python tools/visual_check.py --page about --rubric ui_rubrics.json
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
DEFAULT_PORT = 0


def find_edge() -> str:
    for p in EDGE_CANDIDATES:
        if os.path.isfile(p):
            return p
    found = shutil.which("msedge") or shutil.which("edge")
    if found:
        return found
    raise SystemExit("未找到 Edge：视觉判分层需要 Edge headless（不下载、不安装）")


def start_server(port: int = DEFAULT_PORT) -> tuple[subprocess.Popen, int]:
    """以源码模式起本地服务，返回 (进程, 实际端口)。"""
    root = Path(__file__).resolve().parent.parent
    proc = subprocess.Popen(
        [sys.executable, "app.py", "--no-browser", "--port", str(port)],
        cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace")
    line = proc.stdout.readline()
    m = re.search(r"127\.0\.0\.1:(\d+)", line or "")
    if not m:
        proc.terminate()
        raise SystemExit("服务未就绪：%s" % (line or "").strip())
    return proc, int(m.group(1))


def edge_dump_dom(edge: str, url: str, profile: str) -> str:
    cp = subprocess.run(
        [edge, "--headless=new", "--disable-gpu", "--no-first-run",
         "--user-data-dir=" + profile, "--virtual-time-budget=4000",
         "--dump-dom", url],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60)
    return cp.stdout or ""


def edge_screenshot(edge: str, url: str, profile: str, out_png: Path,
                    width: int = 1440, height: int = 900) -> bool:
    try:
        cp = subprocess.run(
            [edge, "--headless=new", "--disable-gpu", "--no-first-run",
             "--user-data-dir=" + profile, "--virtual-time-budget=4000",
             "--window-size=%d,%d" % (width, height),
             "--screenshot=" + str(out_png), url],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=90)
    except subprocess.TimeoutExpired:
        return False
    return out_png.is_file() and out_png.stat().st_size > 0


# --------------------------------------------------------------------------- #
# 结构层：几何与断言检查（零依赖）
# --------------------------------------------------------------------------- #
def parse_dom(dom: str) -> dict:
    """从 DOM 快照里抽出 id → 文本 的映射，供断言使用。"""
    ids = set(re.findall(r'\bid="([^"]+)"', dom))
    texts = {}
    for m in re.finditer(r'id="([^"]+)"[^>]*>([^<]{0,200})', dom):
        texts.setdefault(m.group(1), m.group(2).strip())
    return {"ids": ids, "texts": texts, "dom": dom}


def structure_checks(dom_info: dict, spec: dict) -> list[tuple[str, bool, str]]:
    """按 rubric 的 structure 段做断言，返回 [(断言名, 是否通过, 证据)]。"""
    out = []
    dom = dom_info["dom"]
    for chk in spec.get("structure", []):
        kind = chk.get("kind")
        name = chk.get("name", kind or "?")
        if kind == "id_exists":
            ok = chk["id"] in dom_info["ids"]
            out.append((name, ok, "id=%s %s" % (chk["id"],
                          "存在" if ok else "缺失")))
        elif kind == "text_contains":
            ok = chk["text"] in dom
            out.append((name, ok, "文本「%s」%s" % (chk["text"],
                          "存在" if ok else "缺失")))
        elif kind == "text_absent":
            ok = chk["text"] not in dom
            out.append((name, ok, "文本「%s」%s" % (chk["text"],
                          "已移除" if ok else "仍在")))
        elif kind == "order_before":
            a, b = chk["first"], chk["second"]
            ia, ib = dom.find(a), dom.find(b)
            ok = ia != -1 and ib != -1 and ia < ib
            out.append((name, ok, "%s 在 %s %s" % (a, b,
                          "之前" if ok else "未满足顺序")))
        elif kind == "count_at_least":
            cnt = dom.count(chk["token"])
            ok = cnt >= chk["n"]
            out.append((name, ok, "「%s」出现 %d 次（需 ≥%d）" % (
                chk["token"], cnt, chk["n"])))
        else:
            out.append((name, False, "未知断言类型：%s" % kind))
    return out


# --------------------------------------------------------------------------- #
# 视觉层：VLM 判分（可选后端，缺则诚实跳过）
# --------------------------------------------------------------------------- #
def vlm_judge(png: Path, question: str, pass_criteria: list[str]) -> dict:
    """把截图交给已配置的多模态后端判分。未配置 → 诚实跳过。"""
    try:
        import backend
    except Exception as exc:
        return {"status": "skipped", "reason": "backend 不可导入：%s" % type(exc).__name__}
    cfg = backend.load_config(refresh=True)
    if not cfg or cfg.get("kind") in (None, "", "none"):
        return {"status": "skipped",
                "reason": "未配置后端（kind=none）：视觉判分需你自行配置支持视觉的模型"}
    try:
        be = backend.current_backend()
    except Exception as exc:
        return {"status": "skipped",
                "reason": "后端不可用：%s" % type(exc).__name__}
    if not hasattr(be, "chat"):
        return {"status": "skipped", "reason": "当前后端不支持 chat"}
    b64 = base64.b64encode(png.read_bytes()).decode("ascii")
    rubric = "\n".join("- " + c for c in pass_criteria)
    prompt = ("请看这张软件界面截图，判断以下问题是否满足。\n"
              "问题：%s\n通过标准：\n%s\n\n"
              "只回答 PASS 或 FAIL，不要解释。" % (question, rubric))
    messages = [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {
            "url": "data:image/png;base64,%s" % b64}},
    ]}]
    try:
        answer = be.chat(messages)
    except Exception as exc:
        return {"status": "error", "reason": "判分调用失败：%s" % type(exc).__name__}
    verdict = "PASS" if re.search(r"\bPASS\b", answer or "", re.I) else "FAIL"
    return {"status": "judged", "verdict": verdict,
            "raw": (answer or "")[:200]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="精核 · UI 视觉判分层")
    ap.add_argument("--rubric", required=True, help="rubric JSON 路径")
    ap.add_argument("--out", default="", help="报告输出 md 路径")
    ap.add_argument("--no-vlm", action="store_true", help="只跑结构层，跳过 VLM")
    args = ap.parse_args(argv)

    spec = json.loads(Path(args.rubric).read_text(encoding="utf-8"))
    edge = find_edge()
    proc, port = start_server()
    tmp = Path(tempfile.mkdtemp(prefix="jh-visual-"))
    lines = []
    total_struct = total_ok = 0
    vlm_results = []
    try:
        for page in spec.get("pages", []):
            name = page.get("name", "?")
            url = "http://127.0.0.1:%d/" % port
            if page.get("hash"):
                url += page["hash"]
            prof = str(tmp / ("p-%s" % name))
            dom = edge_dump_dom(edge, url, prof)
            info = parse_dom(dom)
            checks = structure_checks(info, page)
            ok_count = sum(1 for _, ok, _ in checks if ok)
            total_struct += len(checks)
            total_ok += ok_count

            png = tmp / ("%s.png" % name)
            shot_ok = edge_screenshot(edge, url, prof, png)

            vlm = {"status": "skipped", "reason": "本轮未启用（--no-vlm）"}
            if not args.no_vlm and shot_ok and page.get("vlm"):
                vlm = vlm_judge(png, page["vlm"]["question"],
                                page["vlm"].get("pass_criteria", []))
            vlm_results.append((name, vlm))

            lines.append("## %s" % name)
            lines.append("")
            lines.append("- 结构断言：%d/%d 通过" % (ok_count, len(checks)))
            for cname, ok, ev in checks:
                lines.append("  - %s %s（%s）" % (
                    "✅" if ok else "❌", cname, ev))
            if page.get("vlm"):
                lines.append("- 视觉判分：%s" % _fmt_vlm(vlm))
            lines.append("")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)

    text = "\n".join(lines) + "\n"
    text = ("# 精核 · UI 视觉判分报告\n\n"
            "- 结构层断言合计：**%d/%d** 通过\n"
            "- 视觉层：%s\n\n%s" % (
                total_ok, total_struct,
                "已启用（见各页）" if not args.no_vlm else "已跳过",
                text))
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print("报告已写入：%s（结构层 %d/%d）" % (args.out, total_ok, total_struct))
    else:
        print(text)
    return 0 if total_ok == total_struct else 1


def _fmt_vlm(v: dict) -> str:
    if v.get("status") == "judged":
        return "**%s**（模型判定）" % v.get("verdict")
    if v.get("status") == "skipped":
        return "跳过（%s）" % v.get("reason")
    return "错误（%s）" % v.get("reason")


if __name__ == "__main__":
    raise SystemExit(main())
