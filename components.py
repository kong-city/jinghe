# -*- coding: utf-8 -*-
"""精核 · 可选组件管理（设置页"相关组件"列表的数据与安装后端）。

设计约束：
* 纯标准库；组件探测复用 media_tools.ToolAdapter，不碰 TOOL_SPECS / capabilities()
  （S1 契约 test_33/34 锁死「恰好 3 工具 + 全 False」，本模块只加独立字段）。
* 三个核心组件：ffmpeg（音视频基础）、whisper（本机转写）、yt-dlp（链接下载）。
* **绝不主动下载（用户 2026-11-19 硬裁决）**：软件启动、能力探测、定时任务
  一律不下载任何组件；只有用户在设置页**手动点击「启用」按钮**，才触发下载。
  技术上以 ``_USER_OPT_IN`` 令牌强制：任何下载路径必须先经 :func:`install`
  写入令牌，绕过者（含未来误调）直接拒绝。
* 内置固定源仅供手动安装使用：ffmpeg=gyan.dev 静态 zip；whisper/yt-dlp=pip
  阿里镜像。下载地址只从本文件的 COMPONENTS 常量取，前端不能传任意 URL（防 SSRF）。
* 安装到 %LOCALAPPDATA%/Jinghe/components/bin，不写系统目录、不需要管理员权限。
  **工具二进制不进 exe、不进 Release、不随 GitHub 上传**（build.spec binaries=[]）。
* 安装过程后台线程执行，进度通过 install_status(since) 事件队列暴露，前端轮询。

对外 API：
    list_components(refresh=False) -> dict        组件清单 + 安装状态
    install(component_id) -> dict                 启动安装（幂等：已在装则拒绝）
    install_status(since=0) -> dict               进度事件 / 状态
    cancel_install() -> dict                      取消当前安装
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

import media_tools

__version__ = "0.1.0"

COMPONENT_DIR = Path(os.environ.get("LOCALAPPDATA") or str(Path.home())) / "Jinghe" / "components"
BIN_DIR = COMPONENT_DIR / "bin"

# 内置固定源——前端不可改。pip 镜像用于装 whisper / yt-dlp（两者都会生成 CLI 到 Scripts/）。
PIP_INDEX = "https://mirrors.aliyun.com/pypi/simple/"
PIP_TRUSTED_HOST = "mirrors.aliyun.com"
FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

# 组件定义（顺序即 UI 展示顺序）
COMPONENTS = (
    {
        "id": "ffmpeg",
        "name": "FFmpeg",
        "desc": "音视频解码、抽轨与字幕导出，转写/链接处理的基础依赖",
        "probe": "ffmpeg",
        "kind": "zip",
        "url": FFMPEG_URL,
        "exe": "ffmpeg.exe",
    },
    {
        "id": "whisper",
        "name": "Whisper",
        "desc": "本机语音转写模型（OpenAI Whisper，首次运行会下载模型）",
        "probe": "whisper",
        "kind": "pip",
        "package": "openai-whisper",
        "exe": "whisper.exe",
    },
    {
        "id": "yt-dlp",
        "name": "yt-dlp",
        "desc": "视频/音频链接下载与解析",
        "probe": "yt-dlp",
        "kind": "pip",
        "package": "yt-dlp",
        "exe": "yt-dlp.exe",
    },
)
_BY_ID = {c["id"]: c for c in COMPONENTS}

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_LOCK = threading.Lock()
# 手动点击令牌（用户 2026-11-19 硬裁决：绝不主动下载）。
# 只有 install() 在确认「用户点了启用按钮」后才会置 True；_install_worker
# 消费一次即清。任何绕过 install() 直接调 _download/_pip_install 的路径，
# 令牌为空 → 拒绝下载，从代码层杜绝自动/误触下载。
_USER_OPT_IN = {"granted": False, "component_id": ""}
_JOB = {
    "running": False,
    "id": "",
    "state": "idle",       # idle / running / done / failed / cancelled
    "percent": 0.0,
    "message": "",
    "error": "",
    "cancelled": False,
    "events": [],          # [{seq, type, text, progress}]
    "next_seq": 1,
}


# --------------------------------------------------------------------------- #
# PATH 增强：让 pip 装出来的 CLI / 解压出的 ffmpeg 能被 shutil.which 找到
# --------------------------------------------------------------------------- #
def _scripts_dir() -> Path:
    """真实 Python 的 Scripts 目录（pip 装 CLI 落这里）。

    冻结态 ``sys.prefix`` 指向 exe 的临时解压目录，那里没有 pip 装的 CLI；
    必须用 :func:`_python_for_pip` 找到的真 Python 反推其 Scripts 目录，
    否则组件装完仍探测不到（whisper.exe 在真 Python 的 Scripts 下）。
    """
    try:
        py = _python_for_pip()
        return Path(py).resolve().parent / "Scripts"
    except RuntimeError:
        # 找不到真 Python 时回退到 sys.prefix（源码态即正确）
        return Path(sys.prefix) / "Scripts"


def ensure_component_path() -> None:
    """把组件 bin / Scripts 加进 PATH（幂等），供探测与运行时使用。"""
    for p in (BIN_DIR, _scripts_dir()):
        s = str(p)
        if p.is_dir() and s.lower() not in (os.environ.get("PATH") or "").lower():
            os.environ["PATH"] = s + os.pathsep + (os.environ.get("PATH") or "")


def _which(name: str) -> str:
    ensure_component_path()
    return shutil.which(name) or ""


# --------------------------------------------------------------------------- #
# 清单与状态
# --------------------------------------------------------------------------- #
def _probe_one(probe_name: str) -> dict:
    """用统一的 ToolAdapter 探测，结果归一为 {available, version, reason, path}。

    argv / 版本正则 / 超时都从 media_tools.TOOL_SPECS 按名字取，绝不另写一套
    （避免与 S1 契约的探测口径分叉）；只注入我们自己的 which 以带上组件 PATH。
    """
    spec = next((s for s in media_tools.TOOL_SPECS if s[0] == probe_name), None)
    if spec is None:
        return {"available": False, "version": "", "reason": "无探测规格", "path": ""}
    adapter = media_tools.ToolAdapter(
        spec[0], spec[1], spec[2],
        timeout=media_tools.PROBE_TIMEOUTS.get(probe_name, media_tools.DEFAULT_TIMEOUT),
        which=_which,
    )
    r = adapter.probe()
    return {
        "available": bool(r.get("available")),
        "version": r.get("version") or "",
        "reason": r.get("reason") or "",
        "path": r.get("path") or "",
    }


def list_components(refresh: bool = False) -> dict:
    """组件清单；installed 以真实探测为准，不缓存安装状态。"""
    if refresh:
        media_tools.reset_cache()
    ensure_component_path()
    items = []
    for c in COMPONENTS:
        st = _probe_one(c["probe"])
        items.append({
            "id": c["id"],
            "name": c["name"],
            "desc": c["desc"],
            "installed": st["available"],
            "version": st["version"],
            "path": st["path"],
            "reason": "" if st["available"] else (st["reason"] or "未安装"),
        })
    with _LOCK:
        job = {
            "running": _JOB["running"],
            "id": _JOB["id"],
            "state": _JOB["state"],
            "percent": _JOB["percent"],
            "message": _JOB["message"],
        }
    return {"ok": True, "components": items, "job": job, "install_dir": str(BIN_DIR)}


# --------------------------------------------------------------------------- #
# 进度事件
# --------------------------------------------------------------------------- #
def _emit(event: str, text: str, progress: float | None = None) -> None:
    with _LOCK:
        seq = _JOB["next_seq"]
        _JOB["next_seq"] = seq + 1
        ev = {"seq": seq, "type": event, "text": text, "progress": progress}
        _JOB["events"].append(ev)
        if len(_JOB["events"]) > 500:
            _JOB["events"] = _JOB["events"][-200:]
        if progress is not None:
            _JOB["percent"] = max(0.0, min(100.0, float(progress) * 100.0))
        _JOB["message"] = text


def install_status(since: int = 0) -> dict:
    with _LOCK:
        events = [dict(e) for e in _JOB["events"] if e["seq"] > since]
        nxt = _JOB["next_seq"] - 1
        return {
            "ok": True,
            "events": events,
            "next": nxt,
            "running": _JOB["running"],
            "state": _JOB["state"],
            "percent": round(_JOB["percent"], 1),
            "message": _JOB["message"],
            "error": _JOB["error"],
            "id": _JOB["id"],
        }


def cancel_install() -> dict:
    with _LOCK:
        if not _JOB["running"]:
            return {"ok": False, "error": "当前没有安装任务"}
        _JOB["cancelled"] = True
    _emit("info", "已请求取消，正在清理…")
    return {"ok": True}


def _cancelled() -> bool:
    with _LOCK:
        return _JOB["cancelled"]


# --------------------------------------------------------------------------- #
# 下载与安装
# --------------------------------------------------------------------------- #
def _require_opt_in(component_id: str) -> None:
    """下载前的硬闸门：必须存在刚由 install() 写入的手动点击令牌。

    这是「绝不主动下载」的代码级保证：探测 / 定时器 / 其它模块即使误调
    下载函数，也会因无令牌而失败，不会发出任何网络请求。
    """
    with _LOCK:
        ok = (_USER_OPT_IN["granted"]
              and _USER_OPT_IN["component_id"] == component_id)
        if ok:
            _USER_OPT_IN["granted"] = False   # 一次性消费
            _USER_OPT_IN["component_id"] = ""
    if not ok:
        raise RuntimeError("未获用户手动启用授权，拒绝下载（软件绝不主动下载）")


def _download(url: str, dest: Path, component_id: str) -> None:
    """流式下载（走环境变量代理），写 .part 后原子替换。必须持手动令牌。"""
    _require_opt_in(component_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "jinghe-component-installer"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        got = 0
        with open(tmp, "wb") as f:
            while True:
                if _cancelled():
                    tmp.unlink(missing_ok=True)
                    raise RuntimeError("cancelled")
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if total:
                    _emit("progress", "下载中 %d%%" % int(got * 100 / total), got / total)
                else:
                    _emit("progress", "已下载 %.1f MB" % (got / 1024 / 1024), None)
    tmp.replace(dest)


def _extract_ffmpeg(zip_path: Path) -> str:
    """从静态 zip 里取出 ffmpeg.exe（及 ffprobe.exe，顺带增强）。"""
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    copied = []
    with zipfile.ZipFile(zip_path) as zf:
        members = [m for m in zf.namelist()
                   if m.lower().endswith(("ffmpeg.exe", "ffprobe.exe"))
                   and "/" not in m.rstrip("/").replace("\\", "/")[:-10]]
        # 只取文件名就匹配的目标（允许 bin/ 前缀）
        targets = [m for m in zf.namelist()
                   if m.lower().endswith(("/ffmpeg.exe", "/ffprobe.exe"))]
        for m in (targets or members):
            name = m.replace("\\", "/").rsplit("/", 1)[-1]
            if name.lower() not in ("ffmpeg.exe", "ffprobe.exe"):
                continue
            with zf.open(m) as src, open(BIN_DIR / name, "wb") as dst:
                shutil.copyfileobj(src, dst)
            copied.append(name)
    zip_path.unlink(missing_ok=True)
    if "ffmpeg.exe" not in copied:
        raise RuntimeError("压缩包内未找到 ffmpeg.exe")
    return "已解压 " + ", ".join(copied)


def _python_for_pip() -> str:
    """返回能真正执行 ``-m pip`` 的 Python 解释器路径。

    **冻结态陷阱（用户 2026-11-19 实测踩到：pip 退出码 2）**：PyInstaller
    打包后 ``sys.executable`` 指向 ``Jinghe.exe`` 本身，exe 不内置 pip，
    ``Jinghe.exe -m pip install ...`` 会被当成程序参数 → 退出码 2。
    因此冻结态必须改用 PATH 上的真实 Python；源码态才用 ``sys.executable``。
    找不到 Python 时诚实报错，不假装安装成功。
    """
    if not getattr(sys, "frozen", False):
        return sys.executable
    # 冻结态：从 PATH 找真实 Python（含大小写变体，Windows 上 .EXE）
    for name in ("python.exe", "python", "python3.exe", "python3"):
        found = shutil.which(name)
        if found and os.path.normcase(os.path.abspath(found)) != \
                os.path.normcase(os.path.abspath(sys.executable)):
            return found
    raise RuntimeError(
        "冻结模式下未在本机 PATH 找到 Python，无法通过 pip 安装组件。\n"
        "请先在本机安装 Python 并确保 python 在 PATH 中，"
        "或手动安装 whisper / yt-dlp 后重启软件。")


def _pip_cmd_install(package: str) -> list[str]:
    """组装 pip install 命令，正确处理「无代理」情形。

    旧代码 ``if not cmd[-1]: cmd = cmd[:-2]`` 永远为 False（末项是
    ``--disable-pip-version-check`` 常量），导致无代理时仍传 ``--proxy ""``，
    pip 会报参数错误。这里改为显式判断代理值。
    """
    proxy = (os.environ.get("HTTPS_PROXY")
             or os.environ.get("https_proxy")
             or os.environ.get("HTTP_PROXY")
             or os.environ.get("http_proxy") or "").strip()
    cmd = [_python_for_pip(), "-m", "pip", "install", package,
           "-i", PIP_INDEX, "--trusted-host", PIP_TRUSTED_HOST,
           "--disable-pip-version-check"]
    if proxy:
        cmd.extend(["--proxy", proxy])
    return cmd


def _pip_install(package: str, component_id: str) -> str:
    """用内置镜像装 Python 包，解析 pip 输出映射为 5%~95% 的进度。必须持手动令牌。"""
    _require_opt_in(component_id)
    cmd = _pip_cmd_install(package)
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
        bufsize=1, creationflags=_CREATE_NO_WINDOW,
    )
    steps = ("Collecting", "Downloading", "Installing", "Successfully installed")
    reached = set()
    errors: list[str] = []   # 收集 pip 的 ERROR 行，失败时回显真实原因
    assert proc.stdout is not None
    for line in proc.stdout:
        if _cancelled():
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            raise RuntimeError("cancelled")
        text = line.rstrip()
        if "ERROR" in text or "error:" in text.lower():
            errors.append(text[:200])
            _emit("progress", text[:120], None)
        for i, kw in enumerate(steps):
            if kw in text and kw not in reached:
                reached.add(kw)
                _emit("progress", text[:120], min(0.95, (i + 1) / (len(steps) + 1)))
                break
        else:
            if "Downloading" in text or "MB" in text:
                _emit("progress", text[:120], None)
    rc = proc.wait()
    if rc != 0:
        # 用户要能看到 pip 的真实报错，而不是只有「退出码 2」这种谜语
        detail = errors[-1] if errors else "（pip 未输出 ERROR 行）"
        raise RuntimeError("pip 安装失败（退出码 %d）：%s" % (rc, detail))
    return "安装完成"


def _install_worker(component_id: str) -> None:
    comp = _BY_ID.get(component_id)
    try:
        if not comp:
            raise RuntimeError("未知组件：%s" % component_id)
        _emit("progress", "准备安装 %s…" % comp["name"], 0.01)
        if comp["kind"] == "zip":
            dest = COMPONENT_DIR / (comp["id"] + ".zip")
            _download(comp["url"], dest, component_id)
            _emit("progress", "解压中…", 0.9)
            detail = _extract_ffmpeg(dest)
        else:
            detail = _pip_install(comp["package"], component_id)

        if _cancelled():
            raise RuntimeError("cancelled")
        ensure_component_path()
        st = _probe_one(comp["probe"])
        if not st["available"]:
            raise RuntimeError("安装结束但仍探测不到 %s，请重启软件后重试" % comp["exe"])
        with _LOCK:
            _JOB["state"] = "done"
            _JOB["percent"] = 100.0
            _JOB["running"] = False
        _emit("done", "%s 安装成功（%s）" % (comp["name"], detail or st["version"]), 1.0)
    except Exception as exc:  # noqa: BLE001 - 后台线程必须落地任何失败
        msg = str(exc)
        cancelled = msg == "cancelled" or _cancelled()
        with _LOCK:
            _JOB["state"] = "cancelled" if cancelled else "failed"
            _JOB["running"] = False
            _JOB["error"] = "" if cancelled else msg
        _emit("cancelled" if cancelled else "error",
              "已取消安装" if cancelled else ("安装失败：" + msg), None)


def install(component_id: str) -> dict:
    """启动安装（异步）。**仅代表用户手动点击「启用」后由 UI 调用**。

    软件内部（启动 / 探测 / 定时器 / 其它模块）一律不得调用本函数去下载；
    令牌机制保证即便误调，下载层也会拒绝。
    """
    comp = _BY_ID.get(component_id)
    if not comp:
        return {"ok": False, "error": "未知组件"}
    with _LOCK:
        if _JOB["running"]:
            return {"ok": False, "error": "已有组件正在安装，请等待完成"}
    check = _probe_one(comp["probe"])
    if check["available"]:
        with _LOCK:
            _JOB.update({"running": False, "state": "done", "percent": 100.0,
                         "id": component_id, "events": [], "next_seq": 1})
        _emit("done", "%s 已安装" % comp["name"], 1.0)
        return {"ok": True, "already_installed": True}
    # 只有走到这里（用户点了启用 + 组件确实未安装）才发令牌
    with _LOCK:
        _USER_OPT_IN["granted"] = True
        _USER_OPT_IN["component_id"] = component_id
        _JOB.update({
            "running": True, "id": component_id, "state": "running",
            "percent": 0.0, "message": "", "error": "", "cancelled": False,
            "events": [], "next_seq": 1,
        })
    threading.Thread(target=_install_worker, args=(component_id,),
                     name="jinghe-component-install", daemon=True).start()
    return {"ok": True, "already_installed": False}
