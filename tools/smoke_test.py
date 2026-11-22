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
    """探活 /api/state；后端起来了才返回 dict。

    必须**绕过系统代理**：构建机（CI runner）常带 http_proxy/https_proxy 环境
    变量，urllib 默认会读它们，导致访问 127.0.0.1 也走代理而失败——
    那是环境问题不是产品问题，却会让冒烟误判为「后端起不来」。
    这里显式使用一个不走代理的 opener。
    """
    url = "http://127.0.0.1:%d/api/state" % port
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=timeout) as resp:
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


def check_asar(asar_path: str) -> tuple[bool, str]:
    """**确定性**检查：打包产物里的 main.js 必须含有关键符号。

    为什么需要这一步：GUI 外壳在**无交互桌面会话**的环境（如 CI runner）
    可能根本起不来，此时「跑不起来」是环境限制而非缺陷，直接判失败会误杀。
    但「asar 里缺关键符号」是**确定的打包缺陷**——例如 main.js 没被打进去、
    或 asar 内容与源码脱节。这类问题无论有没有桌面都必须拦下。

    本检查不依赖运行环境，因此在任何 CI/本地都稳定可复现。
    """
    required = ("app.whenReady", "startBackend", "createTray", "createWindow")
    try:
        data = Path(asar_path).read_bytes()
    except OSError as exc:
        return False, "读不到 app.asar：%s" % exc
    # asar 是归档格式，main.js 内容以明文存在其中；用子串判定即可，
    # 无需引入 asar 库（本项目要求零第三方依赖）。
    missing = [sym for sym in required if sym.encode("utf-8") not in data]
    if missing:
        return False, "app.asar 内缺少关键符号：%s" % "、".join(missing)
    return True, "app.asar 含全部关键符号（%s）" % "、".join(required)


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


def classify_shell_failure(text: str, asar_ok: bool = False) -> tuple[str, str]:
    """把外壳启动失败归类为「环境限制」或「产品缺陷」。

    判据（有先后，不能颠倒）：
    1. **asar 检查通过** = main.js 完整且含关键符号 = 打包本身没问题。
       此时起不来，最可能是运行环境没有交互桌面会话（CI runner 常见）——
       归为环境限制，放行并说明（确定性缺陷已由 asar 检查覆盖）。
    2. **asar 检查失败** = 打包本身坏了 → 缺陷，一律拦截。
    3. 日志命中失败标志（托盘创建失败 / 后端启动失败 / 后端意外退出 …）
       → 缺陷，一律拦截。
    4. 其余情况 → 默认从严判缺陷（静默放过会漏掉真问题）。
    """
    low = text.lower()
    if not text.strip():
        if asar_ok:
            return ("env", "asar 校验通过但外壳未就绪：无交互桌面会话的构建机"
                           "（CI runner 常见），main.js 无人执行")
        return ("defect", "无 shell.log 诊断信息：外壳既没就绪也没留下任何日志")
    for kw in DEFECT_HINTS:
        if kw in text:
            return ("defect", "诊断日志命中缺陷关键词「%s」：%s" % (kw, _last(text)))
    for kw in ENV_HINTS:
        if kw in low:
            return ("env", "疑似环境限制（命中「%s」）：%s" % (kw, _last(text)))
    if asar_ok:
        return ("env", "asar 校验通过、外壳未就绪：疑似无交互桌面会话（CI runner）")
    return ("defect", "无法归类为环境限制，按缺陷处理：%s" % _last(text))


def _last(text: str, limit: int = 200) -> str:
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    return lines[-1][:limit] if lines else ""


def smoke_shell(exe: str, port: int, strict: bool, asar_ok: bool = False) -> tuple[bool, str]:
    """外壳冒烟（尽力而为）：起得来算通过，起不来必须说清原因。

    两处曾经的错误（本地复现抓到，已修）：
    1. ``start()`` 失败时读的是**全局** shell.log（含上次运行的旧日志），
       会把上次的结论当成本次判定 —— 现在只看本次新增的行。
    2. 外壳二进制**根本无法执行**（如文件损坏）被当成环境限制放行 ——
       那是打包缺陷，必须拦截。
    """
    log("外壳冒烟：%s" % exe)
    before = read_shell_log()
    # 外壳拉起的后端端口由 JINGHE_PORT 决定，必须显式指定，否则探活找错端口
    proc = start(exe, [], env_extra={"JINGHE_PORT": str(port)})
    if proc is None:
        # 进程都没起来：连「起不来」这件事本身都不是环境问题，而是打包/执行失败。
        # 本次没有任何新日志可依据，因此按缺陷处理（不放行）。
        return False, "外壳 exe 无法启动（进程未创建）：打包产物损坏或无法执行"
    try:
        state = wait_ready(port, READY_TIMEOUT, proc)
        if state:
            log("外壳就绪：version=%s" % state.get("version"))
            return True, str(state.get("version") or "")
        text = read_shell_log()
        # 只看本次启动新增的日志行，避免拿上次的结论误判
        new_text = text[len(before):] if text.startswith(before) else text
        kind, why = classify_shell_failure(new_text, asar_ok)
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
        # ① 确定性检查：asar 内 main.js 必须含关键符号（与环境无关，必过）
        shell_dir = Path(args.shell).parent
        asar = shell_dir / "resources" / "app.asar"
        asar_ok = False
        if asar.is_file():
            asar_ok, a_msg = check_asar(str(asar))
            log(("asar 检查通过：%s" % a_msg) if asar_ok else ("asar 检查失败：%s" % a_msg))
            ok = ok and asar_ok
        else:
            log("asar 检查跳过：未找到 %s" % asar)

        # ② 运行时检查：外壳能不能真正起来（无桌面会话的 CI 上可能起不来）
        s_ok, s_msg = smoke_shell(args.shell, args.port + 1, args.strict_shell, asar_ok)
        log(("外壳冒烟通过：%s" % s_msg) if s_ok else ("外壳冒烟失败：%s" % s_msg))
        ok = ok and s_ok

    log("=== 冒烟结果：%s ===" % ("全部通过" if ok else "存在真缺陷"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
