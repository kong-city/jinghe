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
# v0.10：令牌改为「按组件 id 集合」，支持多组件并发且互不消费对方的令牌；
# _USER_OPT_IN 保留为兼容旧测试的「最近一次令牌」视图。
_USER_OPT_IN = {"granted": False, "component_id": ""}
_USER_OPT_INS: set[str] = set()
# 选定的 pip 用 Python（首次查找后锁定，保证「装」与「探」同源）
_PIP_PYTHON = ""
# 该选择的 PATH 指纹；PATH 变化则重新查找
_PIP_PYTHON_FP = ""
def _new_job(cid: str = "") -> dict:
    return {
        "running": False,
        "id": cid,
        "state": "idle",       # idle / running / done / failed / cancelled
        "percent": 0.0,
        "message": "",
        "error": "",
        "cancelled": False,
        "events": [],          # [{seq, type, text, progress}]
        "next_seq": 1,
    }


# 兼容视图：_JOB 始终指向「最近一次操作」的 job 对象（旧 API/测试读它）。
_JOB = _new_job()
# 真实状态源：每个组件一个独立 job，支持真并发（各自进度/事件/取消）。
_JOBS: dict[str, dict] = {}


def _job_for(cid: str | None) -> dict:
    """取组件对应的 job；cid 为空时回落到最近任务（兼容旧调用）。"""
    if not cid:
        return _JOB
    with _LOCK:
        return _JOBS.setdefault(cid, _new_job(cid))


def _sync_recent(cid: str | None) -> None:
    """把某个 job 设为「最近任务」视图（不拷贝，保持同一对象引用）。"""
    global _JOB
    if cid:
        with _LOCK:
            _JOB = _JOBS.setdefault(cid, _new_job(cid))


# --------------------------------------------------------------------------- #
# PATH 增强：让 pip 装出来的 CLI / 解压出的 ffmpeg 能被 shutil.which 找到
# --------------------------------------------------------------------------- #
def _scripts_dir() -> Path:
    """真实 Python 的 Scripts 目录（pip 装 CLI 落这里）。

    冻结态 ``sys.prefix`` 指向 exe 的临时解压目录，那里没有 pip 装的 CLI；
    必须用 :func:`_python_for_pip` 找到的真 Python，**并问 pip 自己**
    scripts 路径（见 :func:`_pip_scripts_dir`），保证「pip 装到哪」与
    「探测去哪」严格同源——否则会出现「安装结束仍探测不到 whisper.exe」。
    """
    try:
        py = _python_for_pip()
        return _pip_scripts_dir(py)
    except RuntimeError:
        # 找不到真 Python 时回退到 sys.prefix（源码态即正确）
        return Path(sys.prefix) / "Scripts"


def _candidate_scripts_dirs() -> list[Path]:
    """所有可能存放 pip CLI 的 Scripts 目录（按优先级）。

    多个 Python 共存时（本机同时有 workbuddy versions\\3.13.12 与
    WorkBuddy vendor\\python），组件可能装在任一处。全都注入 PATH，
    探测就不会因为「装 A 处、只查 B 处」而失败。
    """
    out: list[Path] = []
    try:
        out.append(_scripts_dir())
    except Exception:
        pass
    # PATH 里所有以 Scripts 结尾的条目
    for entry in (os.environ.get("PATH") or "").split(os.pathsep):
        entry = entry.strip().strip('"')
        if not entry:
            continue
        try:
            p = Path(entry)
            if p.name.lower() == "scripts" and p.is_dir():
                out.append(p)
        except OSError:
            continue
    # 去重（保持顺序）
    seen: set[str] = set()
    uniq: list[Path] = []
    for p in out:
        key = os.path.normcase(os.path.abspath(str(p)))
        if key not in seen:
            seen.add(key)
            uniq.append(p)
    return uniq


def ensure_component_path() -> None:
    """把组件 bin / 候选 Scripts 加进 PATH（幂等），供探测与运行时使用。"""
    for p in [BIN_DIR] + _candidate_scripts_dirs():
        s = str(p)
        if p.is_dir() and s.lower() not in (os.environ.get("PATH") or "").lower():
            os.environ["PATH"] = s + os.pathsep + (os.environ.get("PATH") or "")


def _which(name: str) -> str:
    ensure_component_path()
    return shutil.which(name) or ""


# --------------------------------------------------------------------------- #
# 清单与状态
# --------------------------------------------------------------------------- #
def _probe_one(probe_name: str, deep: bool = False) -> dict:
    """用统一的 ToolAdapter 探测，结果归一为 {available, version, reason, path}。

    argv / 版本正则 / 超时都从 media_tools.TOOL_SPECS 按名字取，绝不另写一套
    （避免与 S1 契约的探测口径分叉）；只注入我们自己的 which 以带上组件 PATH。

    ``deep=True`` 跳过轻量快路径、真跑探测命令（安装流程末尾的深度验证用）。
    """
    spec = next((s for s in media_tools.TOOL_SPECS if s[0] == probe_name), None)
    if spec is None:
        return {"available": False, "version": "", "reason": "无探测规格", "path": ""}
    adapter = media_tools.ToolAdapter(
        spec[0], spec[1], spec[2],
        timeout=media_tools.PROBE_TIMEOUTS.get(probe_name, media_tools.DEFAULT_TIMEOUT),
        which=_which,
        deep=deep,
    )
    r = adapter.probe()
    return {
        "available": bool(r.get("available")),
        "version": r.get("version") or "",
        "reason": r.get("reason") or "",
        "path": r.get("path") or "",
        # ok / missing / timeout / error：超时与「真没装」必须分开，
        # 否则界面只显示「未安装」，用户无法区分（用户 2026-11-19 实测）。
        "state": r.get("state") or ("ok" if r.get("available") else "missing"),
    }


def list_components(refresh: bool = False) -> dict:
    """组件清单；installed 以真实探测为准，不缓存安装状态。"""
    if refresh:
        # 只清缓存，**不关刷新窗口**（reset_cache 会关窗，会让同一轮里
        # audio/video 的探测重新真跑一遍，用户 2026-11-19 实测端点耗时 4 秒）
        with media_tools._LOCK:
            media_tools._CACHE = None
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
            "state": st["state"],
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
def _emit(event: str, text: str, progress: float | None = None,
          component_id: str | None = None) -> None:
    job = _job_for(component_id)
    with _LOCK:
        seq = job["next_seq"]
        job["next_seq"] = seq + 1
        ev = {"seq": seq, "type": event, "text": text, "progress": progress,
              "cid": job["id"]}
        job["events"].append(ev)
        if len(job["events"]) > 500:
            job["events"] = job["events"][-200:]
        if progress is not None:
            job["percent"] = max(0.0, min(100.0, float(progress) * 100.0))
        job["message"] = text


def install_status(since: int = 0, component_id: str | None = None) -> dict:
    """单个组件进度（cid 为空=最近任务）；cid='*' 返回全部任务快照。"""
    if component_id == "*":
        with _LOCK:
            jobs = {}
            for cid, job in _JOBS.items():
                jobs[cid] = {
                    "events": [dict(e) for e in job["events"]],
                    "next": job["next_seq"] - 1,
                    "running": job["running"], "state": job["state"],
                    "percent": round(job["percent"], 1),
                    "message": job["message"], "error": job["error"],
                    "id": cid,
                }
            running_n = sum(1 for j in _JOBS.values() if j["running"])
        return {"ok": True, "jobs": jobs, "running": running_n,
                "events": [], "next": 0, "state": "running" if running_n else "idle",
                "percent": 0.0, "message": "", "error": "", "id": ""}
    job = _job_for(component_id)
    with _LOCK:
        events = [dict(e) for e in job["events"] if e["seq"] > since]
        nxt = job["next_seq"] - 1
        return {
            "ok": True,
            "events": events,
            "next": nxt,
            "running": job["running"],
            "state": job["state"],
            "percent": round(job["percent"], 1),
            "message": job["message"],
            "error": job["error"],
            "id": job["id"],
        }


def cancel_install(component_id: str | None = None) -> dict:
    job = _job_for(component_id)
    with _LOCK:
        if not job["running"]:
            return {"ok": False, "error": "当前没有安装任务"}
        job["cancelled"] = True
    _emit("info", "已请求取消，正在清理…", None, job["id"])
    return {"ok": True}


def _cancelled(component_id: str | None = None) -> bool:
    job = _job_for(component_id)
    with _LOCK:
        return job["cancelled"]


# --------------------------------------------------------------------------- #
# 下载与安装
# --------------------------------------------------------------------------- #
def _require_opt_in(component_id: str) -> None:
    """下载前的硬闸门：必须存在刚由 install() 写入的手动点击令牌。

    这是「绝不主动下载」的代码级保证：探测 / 定时器 / 其它模块即使误调
    下载函数，也会因无令牌而失败，不会发出任何网络请求。
    """
    with _LOCK:
        # 新机制：按组件 id 的令牌集合，互不消费（支持并发）。
        in_set = component_id in _USER_OPT_INS
        if in_set:
            _USER_OPT_INS.discard(component_id)
        # 兼容视图：旧测试/旧调用直接写 _USER_OPT_IN 后调本函数。
        legacy = (_USER_OPT_IN["granted"]
                  and _USER_OPT_IN["component_id"] == component_id)
        if legacy:
            _USER_OPT_IN["granted"] = False
            _USER_OPT_IN["component_id"] = ""
        ok = in_set or legacy
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
                if _cancelled(component_id):
                    tmp.unlink(missing_ok=True)
                    raise RuntimeError("cancelled")
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if total:
                    _emit("progress", "下载中 %d%%" % int(got * 100 / total),
                          got / total, component_id)
                else:
                    _emit("progress", "已下载 %.1f MB" % (got / 1024 / 1024),
                          None, component_id)
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


def _python_root_has_exe(root: Path) -> str:
    """给定 Python 根目录，返回其中的 python.exe（存在才返回）。"""
    for name in ("python.exe", "python"):
        p = root / name
        try:
            if p.is_file():
                return str(p)
        except OSError:
            continue
    return ""


def _pip_scripts_dir(python_exe: str) -> Path:
    """**问 pip 自己**它的 console script 落点，绝不靠猜。

    为什么必须问（用户 2026-11-19 实测踩坑）：
    ``Path(python).resolve()`` 会把 Windows junction 展开成别名路径
    （本机 ``...\\versions\\3.13.12`` → ``...\\vendor\\python``），
    而 pip 用的是**未解析的真实路径**。两者一旦不是同一目录，就会
    「pip 装到 A、探测去 B」→ 安装结束仍探测不到 whisper.exe。
    直接问 pip 的 ``sysconfig.get_path('scripts')`` 可保证装与探同源。
    """
    try:
        out = subprocess.run(
            [python_exe, "-c",
             "import sysconfig;print(sysconfig.get_path('scripts'))"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", timeout=20,
            # 必须带 NO_WINDOW：否则每次探测都会在桌面弹一个控制台黑框
            # （用户 2026-11-19 实测被弹窗刷屏，根因即此处漏加）
            creationflags=_CREATE_NO_WINDOW)
        path = (out.stdout or "").strip().splitlines()
        if path and path[0]:
            p = Path(path[0].strip())
            if p.is_dir():
                return p
    except Exception:
        pass
    # 兜底：未解析的真实父目录 + Scripts（不做 resolve，避免展开 junction）
    return Path(python_exe).parent / "Scripts"


def _python_for_pip() -> str:
    """返回能真正执行 ``-m pip`` 的 Python 解释器路径。

    **冻结态陷阱（用户 2026-11-19 实测踩到：pip 退出码 2）**：PyInstaller
    打包后 ``sys.executable`` 指向 ``Jinghe.exe`` 本身，exe 不内置 pip，
    ``Jinghe.exe -m pip install ...`` 会被当成程序参数 → 退出码 2。
    因此冻结态必须改用本机真实 Python；源码态才用 ``sys.executable``。

    **第二个坑（同日实测）**：Windows 上用户 PATH 常只含 ``...\\Python3xx\\Scripts``
    （whisper.exe 所在），**不含** ``python.exe`` 所在的父目录，导致
    ``shutil.which("python")`` 失败。故增加「从 PATH 里的 Scripts 反推父目录」
    策略——这是本机 workbuddy Python 的真实布局。查找顺序：
      1. PATH 直接找 python.exe；
      2. PATH 每个条目若以 Scripts 结尾，反推父目录找 python.exe；
      3. 从已探测到的 whisper/yt-dlp 位置反推；
      4. LOCALAPPDATA/Programs/Python 与 C:\\Python3xx 常见位置。
    全部失败才诚实报错，并给出可操作指引。

    **结果缓存**（仅冻结态）：首次选定后即锁定，保证「pip 装到哪」与
    「探测去哪」全程同一个 Python（否则中途环境变化会装探错位）。
    源码态不缓存——``sys.executable`` 本身不会变。
    缓存带**环境指纹**（PATH），PATH 变了就重新查找，避免环境变更后
    仍用旧结果导致「装探错位」。
    """
    if not getattr(sys, "frozen", False):
        return sys.executable
    global _PIP_PYTHON, _PIP_PYTHON_FP
    fingerprint = os.environ.get("PATH") or ""
    with _LOCK:
        if _PIP_PYTHON and _PIP_PYTHON_FP == fingerprint:
            return _PIP_PYTHON
    found = _find_python_for_pip()
    with _LOCK:
        _PIP_PYTHON = found
        _PIP_PYTHON_FP = fingerprint
    return found


def _find_python_for_pip() -> str:
    """真正执行查找逻辑（见 :func:`_python_for_pip` 的策略说明）。"""
    if not getattr(sys, "frozen", False):
        return sys.executable
    exepath = os.path.normcase(os.path.abspath(sys.executable))

    def valid(p: str) -> bool:
        return bool(p) and os.path.normcase(os.path.abspath(p)) != exepath

    # ① PATH 直接找
    for name in ("python.exe", "python", "python3.exe", "python3"):
        found = shutil.which(name)
        if valid(found):
            return found
    # ② 从 PATH 里的 Scripts 反推父目录（本机 workbuddy Python 布局）
    for entry in (os.environ.get("PATH") or "").split(os.pathsep):
        entry = entry.strip().strip('"')
        if not entry:
            continue
        try:
            p = Path(entry)
            if p.name.lower() == "scripts":
                got = _python_root_has_exe(p.parent)
                if valid(got):
                    return got
        except OSError:
            continue
    # ③ 从已装 CLI（whisper/yt-dlp）位置反推
    for cli in ("whisper", "whisper.exe", "yt-dlp", "yt-dlp.exe"):
        found = shutil.which(cli)
        if found:
            got = _python_root_has_exe(Path(found).resolve().parent.parent)
            if valid(got):
                return got
    # ④ 常见安装位置
    roots = [Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python"]
    roots += [Path("C:/Python3%d" % n) for n in range(8, 14)]
    for base in roots:
        try:
            for child in sorted(base.glob("python3*"), reverse=True):
                got = _python_root_has_exe(child)
                if valid(got):
                    return got
        except OSError:
            continue
    raise RuntimeError(
        "未在本机找到可用于 pip 的 Python 解释器。\n"
        "Whisper 约 640 MB（含 torch 464 MB），需联网下载，无法打包进软件。\n"
        "解决办法（选一）：\n"
        "  1) 安装 Python 时勾选「Add Python to PATH」，重启软件后再点启用；\n"
        "  2) 手动执行 pip install openai-whisper，重启软件即可识别；\n"
        "  3) 若已装在本机，把 python.exe 所在目录加入 PATH。")


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
        if _cancelled(component_id):
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            raise RuntimeError("cancelled")
        text = line.rstrip()
        if "ERROR" in text or "error:" in text.lower():
            errors.append(text[:200])
            _emit("progress", text[:120], None, component_id)
        for i, kw in enumerate(steps):
            if kw in text and kw not in reached:
                reached.add(kw)
                _emit("progress", text[:120],
                      min(0.95, (i + 1) / (len(steps) + 1)), component_id)
                break
        else:
            if "Downloading" in text or "MB" in text:
                _emit("progress", text[:120], None, component_id)
    rc = proc.wait()
    if rc != 0:
        # 用户要能看到 pip 的真实报错，而不是只有「退出码 2」这种谜语
        detail = errors[-1] if errors else "（pip 未输出 ERROR 行）"
        raise RuntimeError("pip 安装失败（退出码 %d）：%s" % (rc, detail))
    return "安装完成"


def _ensure_console_script(python_exe: str, package: str, exe_name: str) -> str:
    """包已装但 console script（exe）缺失时，**离线补生成**该 exe。

    **为什么需要（用户 2026-11-19 实测踩坑）**：pip 装的其实是「包」，
    ``whisper.exe`` 只是它的 console script 副产品。若包早已安装
    （``Requirement already satisfied``），pip 会**整个跳过**，
    **不会补回丢失的 exe** → 软件报「安装结束仍探测不到 whisper.exe」。
    重装（``--force-reinstall``）也不可行：需重下 640 MB，且内网镜像
    在部分网络下不可达（``from versions: none``）。

    这里用 **pip 自带的 distlib ScriptMaker** 离线重建启动器：
    不联网、不重装依赖、pip 与生成器版本天然匹配。
    返回生成结果描述；失败时抛异常，由调用方转成可读报错。
    """
    code = r"""
import sys
from importlib.metadata import distribution
try:
    from pip._vendor.distlib.scripts import ScriptMaker
except Exception:
    from pip._internal.operations.install.wheel import ScriptMaker
pkg = sys.argv[1]
exe = sys.argv[2]
scripts_dir = sys.argv[3]
dist = distribution(pkg)
eps = [e for e in dist.entry_points if e.group == "console_scripts"]
if not eps:
    raise SystemExit("包 %s 没有 console_scripts 入口点" % pkg)
maker = ScriptMaker(None, scripts_dir)
maker.executable = sys.executable
maker.set_mode = True
made = []
for ep in eps:
    made += maker.make("%s = %s" % (ep.name, ep.value))
print("|".join(made))
"""
    scripts_dir = str(_scripts_dir())
    try:
        out = subprocess.run(
            [python_exe, "-c", code, package, exe_name, scripts_dir],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", timeout=120,
            creationflags=_CREATE_NO_WINDOW)
    except Exception as exc:
        raise RuntimeError("补生成 %s 失败：%s" % (exe_name, exc))
    if out.returncode != 0:
        raise RuntimeError("补生成 %s 失败：%s" % (
            exe_name, (out.stderr or out.stdout or "").strip()[:300]))
    made = (out.stdout or "").strip().splitlines()[-1:] if out.stdout else []
    target = os.path.join(scripts_dir, exe_name)
    if not os.path.isfile(target):
        raise RuntimeError("补生成 %s 后仍未找到：%s" % (exe_name, target))
    return "已离线补生成 %s" % (made[0] if made else exe_name)


def _install_worker(component_id: str) -> None:
    comp = _BY_ID.get(component_id)
    job = _job_for(component_id)
    try:
        if not comp:
            raise RuntimeError("未知组件：%s" % component_id)
        _emit("progress", "准备安装 %s…" % comp["name"], 0.01, component_id)
        if comp["kind"] == "zip":
            dest = COMPONENT_DIR / (comp["id"] + ".zip")
            _download(comp["url"], dest, component_id)
            _emit("progress", "解压中…", 0.9, component_id)
            detail = _extract_ffmpeg(dest)
        else:
            detail = _pip_install(comp["package"], component_id)
            # pip 装的是「包」，exe 是它的副产品：包已装但 exe 丢失时，
            # pip 会「already satisfied」整个跳过、不会补回 exe → 离线补生成。
            try:
                exe_path = _scripts_dir() / comp["exe"]
            except RuntimeError:
                exe_path = None
            if exe_path is not None and not exe_path.is_file():
                _emit("progress", "补生成 %s 启动器…" % comp["exe"], 0.97, component_id)
                detail = _ensure_console_script(
                    _python_for_pip(), comp["package"], comp["exe"])

        if _cancelled(component_id):
            raise RuntimeError("cancelled")
        ensure_component_path()
        # 安装流程末尾做**深度验证**（真跑探测命令）：此处必须确认命令真的
        # 能跑，不能只凭轻量检查说「装好了」。
        st = _probe_one(comp["probe"], deep=True)
        if not st["available"]:
            # 报错必须带诊断信息（用户 2026-11-19 反馈：只有「仍探测不到」
            # 无法定位）。此处明示：pip 用哪个 Python、探测查哪个目录、
            # 目标 exe 是否真的不在那里。
            try:
                py = _python_for_pip()
            except RuntimeError:
                py = "(未找到 Python)"
            dirs = [str(d) for d in _candidate_scripts_dirs()]
            raise RuntimeError(
                "安装结束但仍探测不到 %s。\n"
                "诊断：pip 使用 Python = %s\n"
                "　　 探测查找目录 = %s\n"
                "　　 目标文件是否存在 = %s\n"
                "请重启软件后重试；若仍失败，请把以上诊断信息反馈给开发者。"
                % (comp["exe"], py, " | ".join(dirs) or "(无)",
                   (Path(dirs[0]) / comp["exe"]).is_file() if dirs else "未知"))
        with _LOCK:
            job["state"] = "done"
            job["percent"] = 100.0
            job["running"] = False
        _emit("done", "%s 安装成功（%s）" % (comp["name"], detail or st["version"]), 1.0, component_id)
    except Exception as exc:  # noqa: BLE001 - 后台线程必须落地任何失败
        msg = str(exc)
        cancelled = msg == "cancelled" or _cancelled(component_id)
        with _LOCK:
            job["state"] = "cancelled" if cancelled else "failed"
            job["running"] = False
            job["error"] = "" if cancelled else msg
        _emit("cancelled" if cancelled else "error",
              "已取消安装" if cancelled else ("安装失败：" + msg), None, component_id)


def install(component_id: str) -> dict:
    """启动安装（异步）。**仅代表用户手动点击「启用」后由 UI 调用**。

    软件内部（启动 / 探测 / 定时器 / 其它模块）一律不得调用本函数去下载；
    令牌机制保证即便误调，下载层也会拒绝。多组件可并发（各自独立 job/令牌）。
    """
    global _JOB
    comp = _BY_ID.get(component_id)
    if not comp:
        return {"ok": False, "error": "未知组件"}
    # v0.10：按组件维度判断是否已在装——不同组件可并发，同一组件仍拒绝重复点击
    with _LOCK:
        existing = _JOBS.get(component_id)
        if existing and existing["running"]:
            return {"ok": False, "error": "该组件正在安装中，请勿重复点击"}
    check = _probe_one(comp["probe"])
    if check["available"]:
        with _LOCK:
            job = _JOBS.setdefault(component_id, _new_job(component_id))
            job.update({"running": False, "state": "done", "percent": 100.0,
                        "id": component_id, "events": [], "next_seq": 1})
            _JOB = job
        _emit("done", "%s 已安装" % comp["name"], 1.0, component_id)
        return {"ok": True, "already_installed": True}
    # 只有走到这里（用户点了启用 + 组件确实未安装）才发令牌。
    # 并发：每组件独立令牌写入 set；兼容视图 _USER_OPT_IN 指向最近一个。
    with _LOCK:
        _USER_OPT_INS.add(component_id)
        _USER_OPT_IN["granted"] = True
        _USER_OPT_IN["component_id"] = component_id
        job = _JOBS.setdefault(component_id, _new_job(component_id))
        job.update({
            "running": True, "id": component_id, "state": "running",
            "percent": 0.0, "message": "", "error": "", "cancelled": False,
            "events": [], "next_seq": 1,
        })
        _JOB = job
    threading.Thread(target=_install_worker, args=(component_id,),
                     name="jinghe-component-install-%s" % component_id,
                     daemon=True).start()
    return {"ok": True, "already_installed": False}
