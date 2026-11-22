#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打包产物冒烟测试：验证「能构建」之外的东西——**能不能真的跑起来**。

背景（2026-11-22 实测）：CI 只验证「包能构建出来」，不验证「包在运行时的
环境里能不能启动」。于是「托盘创建在关键路径上抛错 → 打包态双击没反应且
无任何提示」这类缺陷被放过了 —— 在 CI 上构建成功就上传，从没真启动过。

本脚本补上这块盲区，分两级：

* **后端 exe（严格）**：启动 → 探活 ``/api/state`` → 校验版本号 → 终止进程树。
  失败 = CI 失败，因为后端起不来就是真缺陷。
* **Electron 外壳（尽力而为）**：尝试启动打包产物并探活；起不来时读取
  ``%LOCALAPPDATA%\\Jinghe\\shell.log`` **如实分类**原因：
    - 「无桌面会话 / 沙箱环境」→ 环境限制，记 WARN，不阻塞发版；
    - 「托盘异常 / 后端 spawn 失败 / main.js 未加载」→ 真缺陷，记 FAIL。
  绝不静默放过，也绝不把环境问题误判成产品缺陷。

用法::

    python tools/smoke_test.py --backend dist/Jinghe-1.2.5.exe
    python tools/smoke_test.py --backend ... --shell electron/release/win-unpacked/Jinghe.exe
    python tools/smoke_test.py --backend ... --shell ... --port 54987 --strict-shell

退出码：0 全部通过（外壳仅 WARN 也算通过）；1 有真缺陷。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DEFAULT_PORT = 54987
READY_TIMEOUT = 60.0
SHELL_LOG = Path(os.environ.get("LOCALAPPDATA") or str(Path.home())) / "Jinghe" / "shell.log"

# 判定「环境限制」而非「产品缺陷」的关键词（shell.log / 现象描述）
ENV_HINTS = (
    "no desktop", "no window station", "session 0", "headless",
    "display", "gpu", "sandbox", "缺少桌面", "无桌面",
)
# 判定「真缺陷」的关键词（只放**失败标志**；「main.js 已加载」「托盘已创建」
# 是正常启动标志，绝不能进这张表，否则正常也会被判成缺陷）
DEFECT_HINTS = (
    "托盘创建失败", "后端进程启动失败", "后端意外退出", "后端启动中止",
    "端口", "托盘初始化异常",
)


def log(msg: str) -> None:
    print("[smoke] " + msg, flush=True)


def read_shell_log() -> str:
    try:
        return SHELL_LOG.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def probe(port: int, timeout: float = 2.0) -> dict | None:
    """探活 /api/state；后端起来了才返回 dict。"""
    url = "http://127.0.0.1:%d/api/state" % port
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read(65536).decode("utf-8", "replace")
        return json.loads(body)
    except (urllib.error.URLError, OSError, ValueError):
        return None


def wait_ready(port: int, timeout: float, proc=None) -> dict | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            # 进程已退出：再探一次（可能刚好启动完成），否则判定失败
            state = probe(port)
            if state:
                return state
            return None
        state = probe(port)
        if state:
            return state
        time.sleep(1.0)
    return None


def kill_tree(pid: int | None) -> None:
    """按进程树终止（Windows 必需：PyInstaller onefile 会派生子进程）。"""
    if not pid:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)],
                       capture_output=True, timeout=20)
    else:
        try:
            os.killpg(os.getpgid(pid), 15)
        except Exception:
            try:
                os.kill(pid, 15)
            except Exception:
                pass


def start(exe: str, args: list[str], env_extra: dict | None = None) -> subprocess.Popen | None:
    try:
        # 清掉 ELECTRON_RUN_AS_NODE：某些环境（沙箱/IDE 终端）会注入它，
        # 那会让 Electron 以纯 Node 模式启动、main.js 一行不执行——
        # 那是环境干扰，不是产品缺陷，不能让它把冒烟测试带偏。
        env = dict(os.environ)
        env.pop("ELECTRON_RUN_AS_NODE", None)
        env.pop("NODE_OPTIONS", None)
        if env_extra:
            env.update(env_extra)
        return subprocess.Popen(
            [exe] + args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            env=env, creationflags=CREATE_NO_WINDOW)
    except OSError as exc:
        log("启动失败：%s（%s）" % (exc, type(exc).__name__))
        return None


def smoke_backend(exe: str, port: int) -> tuple[bool, str]:
    """后端 exe 冒烟（严格）：起服务 → 探活 → 校验版本。"""
    log("后端冒烟：%s" % exe)
    proc = start(exe, ["--no-browser", "--port", str(port)])
    if proc is None:
        return False, "后端 exe 无法启动"
    try:
        state = wait_ready(port, READY_TIMEOUT, proc)
        if not state:
            return False, "后端在 %ds 内未就绪（/api/state 无响应）" % READY_TIMEOUT
        version = str(state.get("version") or "")
        if not version:
            return False, "后端已响应但 /api/state 缺 version 字段"
        log("后端就绪：version=%s" % version)
        return True, version
    finally:
        kill_tree(proc.pid)


def classify_shell_failure(text: str) -> tuple[str, str]:
    """把外壳启动失败归类为「环境限制」或「产品缺陷」。

    取舍：**默认从严**。没有诊断信息时判为缺陷（而非静默放行）——
    「外壳起不来且查不到原因」本身就是需要拦下的问题。只有明确命中
    环境关键词（无桌面会话等）才放行。
    """
    low = text.lower()
    if not text.strip():
        return ("defect", "无 shell.log 诊断信息：外壳既没就绪也没留下任何日志，"
                          "说明 main.js 很可能根本没被执行（打包异常或环境变量干扰）")
    # 缺陷关键词优先：产品缺陷不能被环境关键词掩盖
    for kw in DEFECT_HINTS:
        if kw in text:
            return ("defect", "诊断日志命中缺陷关键词「%s」：%s" % (kw, _last(text)))
    for kw in ENV_HINTS:
        if kw in low:
            return ("env", "疑似环境限制（命中「%s」）：%s" % (kw, _last(text)))
    return ("defect", "无法归类为环境限制，按缺陷处理：%s" % _last(text))


def _last(text: str, limit: int = 200) -> str:
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    return lines[-1][:limit] if lines else ""


def smoke_shell(exe: str, port: int, strict: bool) -> tuple[bool, str]:
    """外壳冒烟（尽力而为）：起得来算通过，起不来必须说清原因。"""
    log("外壳冒烟：%s" % exe)
    before = read_shell_log()
    # 外壳拉起的后端端口由 JINGHE_PORT 决定，必须显式指定，否则探活找错端口
    proc = start(exe, [], env_extra={"JINGHE_PORT": str(port)})
    if proc is None:
        kind, why = classify_shell_failure(read_shell_log())
        return (False, "外壳 exe 无法启动：%s" % why) if strict else (True, "WARN 外壳未启动（%s）" % why)
    try:
        state = wait_ready(port, READY_TIMEOUT, proc)
        if state:
            log("外壳就绪：version=%s" % state.get("version"))
            return True, str(state.get("version") or "")
        text = read_shell_log()
        # 只看本次启动新增的日志行，避免拿上次的结论误判
        new_text = text[len(before):] if text.startswith(before) else text
        kind, why = classify_shell_failure(new_text)
        if kind == "defect":
            return False, "外壳启动失败（产品缺陷）：%s" % why
        return True, "WARN 外壳未就绪，按环境限制放行（%s）" % why
    finally:
        kill_tree(proc.pid)


def main() -> int:
    global READY_TIMEOUT
    ap = argparse.ArgumentParser(description="打包产物冒烟测试")
    ap.add_argument("--backend", required=True, help="后端 exe 路径")
    ap.add_argument("--shell", default="", help="Electron 外壳 exe 路径（可选）")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="探活端口")
    ap.add_argument("--timeout", type=float, default=READY_TIMEOUT, help="就绪等待秒数")
    ap.add_argument("--strict-shell", action="store_true",
                    help="外壳起不来也判失败（默认按环境限制放行）")
    args = ap.parse_args()

    READY_TIMEOUT = args.timeout

    ok = True
    b_ok, b_msg = smoke_backend(args.backend, args.port)
    log(("后端冒烟通过：%s" % b_msg) if b_ok else ("后端冒烟失败：%s" % b_msg))
    ok = ok and b_ok

    if args.shell:
        s_ok, s_msg = smoke_shell(args.shell, args.port + 1, args.strict_shell)
        log(("外壳冒烟通过：%s" % s_msg) if s_ok else ("外壳冒烟失败：%s" % s_msg))
        ok = ok and s_ok

    log("=== 冒烟结果：%s ===" % ("全部通过" if ok else "存在真缺陷"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
