#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精核 · 本地图形界面（唯一入口，纯 Python 标准库）。

用标准库 http.server 提供一个只监听 127.0.0.1 的本地服务，页面在 ui/ 下，
用 Edge 的 --app 模式打开成无地址栏的独立窗口。

用法：
    python app.py                  # 自动选端口并打开窗口
    python app.py --no-browser     # 只起服务（测试用）
    python app.py --port 8765      # 指定端口

设计约束：零第三方依赖；打包（PyInstaller onefile）后资源通过 sys._MEIPASS 解析。
服务提供若干 /api/* 业务端点：state / pick-folder / pick-files / dry-run / run /
progress / cancel / open / open-merged / merged-status / settings / check-update /
update / open-latest / pick-log-dest / export-log / summarize / transcribe 等。
"""

from __future__ import annotations

import argparse
import atexit
import ctypes
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import extract  # 同目录模块：版本号唯一来源（冻结后由 PyInstaller 一并打包）

HOST = "127.0.0.1"
# 固定端口：界面只听本机，端口固定后用户好记、也避免「对着已退出的旧端口发请求」
# 而误报 Failed to fetch。若端口被占用（已有实例在跑），main 会识别并主动退出，
# 而不是抢占——这是有意的单实例保护。
DEFAULT_PORT = 54321
CREATE_NO_WINDOW = 0x08000000

# 仓库与「最新版本」链接：GitHub 的 /releases/latest 会重定向到最新的 release，
# 因此即使离线（无法调 API 查询具体 tag），下载按钮也始终指向仓库最新版本。
REPO_URL = "https://github.com/kong-city/jinghe"
RELEASES_LATEST_URL = REPO_URL + "/releases/latest"
RELEASES_API_URL = "https://api.github.com/repos/kong-city/jinghe/releases/latest"
# 检查更新的网络超时（秒）：桌面软件不能被慢网络卡住，超时即诚实降级。
UPDATE_TIMEOUT = 4.0
# 仅预览（--dry-run）超时：extract.py 会 rglob 全量递归（extract.py:1690-1693）
# 并对每个文件读全盘算 sha256（extract.py:1756），网络盘 / 被占用文件 /
# 超大目录会显著拖慢；600 秒对「预览」不可接受，收敛到 30 秒并给前端准确文案，
# 避免长时间停在「预览中…」却无任何反馈。
DRY_RUN_TIMEOUT = 30

# 合并文档固定文件名：专用端点只认这个名字，不接受任意文件路径
MERGED_NAME = "MERGED.md"


# --------------------------------------------------------------------------- #
# 路径与子进程
# --------------------------------------------------------------------------- #
def resource_dir() -> Path:
    """打包后资源在 sys._MEIPASS；源码运行时在 app.py 所在目录。"""
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) if base else Path(__file__).resolve().parent


RESOURCE = resource_dir()
UI_DIR = RESOURCE / "ui"
EXTRACT = RESOURCE / "extract.py"
VENDOR_SCRIPT = RESOURCE / "vendor" / "md_convert.py"
INDEX_FILE = UI_DIR / "index.html"

# 冻结后没有控制台，所有异常必须落盘，否则用户只能看到「双击没反应」
LOG_DIR = Path(os.environ.get("LOCALAPPDATA") or str(Path.home())) / "Jinghe"
LOG_FILE = LOG_DIR / "app.log"
# 日志封顶：超过就轮转为 app.log.1（只留 1 份历史）。桌面端长期运行 +
# 高频请求会让日志无限增长，不封顶迟早撑爆磁盘。
LOG_MAX_BYTES = 2 * 1024 * 1024

# 全局唯一的日志 sink：_append_log 与 stdout/stderr 共用，
# 保证轮转时不会有第二个句柄把文件锁住（Windows 上 rename 会被拒）。
_SINK: "_LogSink | None" = None


def _get_sink() -> "_LogSink":
    global _SINK
    if _SINK is None:
        _SINK = _LogSink(LOG_FILE)
    return _SINK


def _append_log(text: str) -> None:
    try:
        _get_sink().write_block(text)
    except Exception:
        pass


def _reconfigure_streams() -> None:
    """必须在任何 print 之前：Windows 管道默认 cp936，会把中文写成 GBK 乱码。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:
            pass


class _LogSink:
    """共享一个 app.log 文件句柄，按行加时间戳（stdout/stderr 共用一个 sink）。

    自己持有文件句柄（而不是外部传入已打开的 fh），这样才能在 Windows 上
    安全轮转：先关闭旧句柄再改名，否则 rename 会被「文件正在使用」拒绝。
    超过 LOG_MAX_BYTES 就把 app.log 轮转为 app.log.1（只保留 1 份），
    避免桌面端长期使用把日志撑成几十 MB。
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._fh = None
        self._lock = threading.Lock()

    def _ensure_open(self) -> None:
        if self._fh is not None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(self._path, "a", encoding="utf-8", buffering=1)
        except Exception:
            self._fh = None

    def _rotate_if_needed(self) -> None:
        try:
            if not self._path.exists():
                return
            if self._path.stat().st_size <= LOG_MAX_BYTES:
                return
            if self._fh is not None:
                try:
                    self._fh.close()
                except Exception:
                    pass
                self._fh = None
            bak = self._path.with_name(self._path.name + ".1")
            if bak.exists():
                bak.unlink()
            self._path.replace(bak)
        except Exception:
            pass

    def write(self, text: str) -> None:
        if not text:
            return
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        body = text[:-1] if text.endswith("\n") else text
        with self._lock:
            try:
                self._rotate_if_needed()
                self._ensure_open()
                if self._fh is None:
                    return
                for line in body.split("\n"):
                    self._fh.write("[%s] %s\n" % (stamp, line))
                self._fh.flush()
            except Exception:
                pass

    def write_block(self, text: str) -> None:
        """整块写入，只在块首打一个时间戳（报错现场的多行记录用这个）。"""
        if not text:
            return
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            try:
                self._rotate_if_needed()
                self._ensure_open()
                if self._fh is None:
                    return
                self._fh.write("[%s] %s\n" % (stamp, text.rstrip()))
                self._fh.flush()
            except Exception:
                pass


class _TeeStream:
    """同时写日志与原始流；原始流不可用（windowed 的哑对象）时只写日志。

    注意：PyInstaller --windowed 下 sys.stdout 并不是 None，而是一个「写进去就
    丢弃」的哑对象，因此不能靠 `is None` 判断要不要落盘。
    """

    def __init__(self, sink: _LogSink, original=None) -> None:
        self._sink = sink
        self._original = original
        self._buf = ""
        self._lock = threading.Lock()

    def write(self, text: str) -> int:
        if not text:
            return 0
        if self._original is not None:
            try:
                self._original.write(text)
                self._original.flush()
            except Exception:
                self._original = None  # 已关闭/不可写：之后只落盘
        with self._lock:
            self._buf += text
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                self._sink.write(line + "\n")
        return len(text)

    def writelines(self, lines) -> None:
        for line in lines:
            self.write(line)

    def flush(self) -> None:
        if self._original is not None:
            try:
                self._original.flush()
            except Exception:
                self._original = None
        with self._lock:
            if self._buf:
                self._sink.write(self._buf + "\n")
                self._buf = ""

    @property
    def encoding(self) -> str:
        return "utf-8"

    def isatty(self) -> bool:
        try:
            return bool(self._original is not None and self._original.isatty())
        except Exception:
            return False

    def fileno(self):
        if self._original is not None:
            try:
                return self._original.fileno()
            except Exception:
                pass
        raise OSError("无文件描述符")

    def reconfigure(self, **kwargs):
        return None


def _excepthook(exc_type, exc, tb) -> None:
    _append_log("未捕获异常:\n" + "".join(traceback.format_exception(exc_type, exc, tb)))


def _thread_excepthook(args) -> None:
    name = args.thread.name if getattr(args, "thread", None) else "?"
    _append_log("线程未捕获异常 (%s):\n%s" % (
        name, "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)),
    ))


def _prepare_runtime() -> None:
    """冻结后无条件把 stdout/stderr 落盘，并安装异常钩子。

    - 冻结（--windowed）：无论 sys.stdout 是 None 还是哑对象，都写 app.log；
      若原流可用（终端启动）则 tee，两边都保留。
    - 源码模式：仅当流为 None（pythonw）时落盘，正常终端不写日志（启动标记除外）。
    """
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    frozen = bool(getattr(sys, "frozen", False))
    if frozen or sys.stdout is None or sys.stderr is None:
        sink = _get_sink()
        if sys.stdout is None:
            sys.stdout = _TeeStream(sink, None)
        elif frozen:
            sys.stdout = _TeeStream(sink, sys.stdout)
        if sys.stderr is None:
            sys.stderr = _TeeStream(sink, None)
        elif frozen:
            sys.stderr = _TeeStream(sink, sys.stderr)
    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook


def _log_startup_banner() -> None:
    """启动标记：用户报问题时能定位版本、进程与启动参数。"""
    try:
        args = " ".join(sys.argv[1:]) or "(无)"
        _append_log("[INFO] 精核 UI 启动 v%s pid=%d args=%s"
                    % (extract.__version__, os.getpid(), args))
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# 运行时报错落盘：组件 + 环境状态 + 任务上下文
# --------------------------------------------------------------------------- #
def _env_snapshot() -> dict:
    """采集当前运行时环境状态，报错时一并落盘，便于定位。"""
    snap: dict = {}
    try:
        snap["version"] = extract.__version__
    except Exception:
        snap["version"] = "?"
    snap["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
    snap["python"] = platform.python_version()
    snap["platform"] = platform.platform()
    snap["system"] = platform.system()
    snap["machine"] = platform.machine()
    try:
        snap["cwd"] = os.getcwd()
    except Exception:
        snap["cwd"] = "?"
    snap["executable"] = sys.executable
    snap["frozen"] = bool(getattr(sys, "frozen", False))
    try:
        snap["pid"] = os.getpid()
    except Exception:
        snap["pid"] = "?"
    snap["thread"] = threading.current_thread().name
    try:
        snap["cpu_count"] = os.cpu_count()
    except Exception:
        snap["cpu_count"] = None
    try:
        snap["thread_count"] = threading.active_count()
    except Exception:
        snap["thread_count"] = None
    # 可用物理内存（仅 Windows 尽力而为，失败不影响主流程）
    if platform.system() == "Windows":
        try:
            class _MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            ms = _MEMORYSTATUSEX()
            ms.dwLength = ctypes.sizeof(ms)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
                snap["mem_avail_mb"] = ms.ullAvailPhys // (1024 * 1024)
                snap["mem_total_mb"] = ms.ullTotalPhys // (1024 * 1024)
        except Exception:
            pass
    return snap


def _version_tuple(text: str) -> tuple[int, ...]:
    """把 'v0.3.6' / '0.3.6' 归一成可比数字元组；非数字段忽略。"""
    nums = re.findall(r"\d+", text or "")
    return tuple(int(n) for n in nums[:3])


def _job_context() -> str:
    """当前后台任务（组件）上下文，报错时标注当时任务状态。"""
    try:
        _reap_dead_job()
        with _JOB_LOCK:
            job = _JOB
        if job is None:
            return "无运行任务"
        with job.lock:
            return ("任务 input=%s outdir=%s state=%s running=%s rc=%s "
                    "current=%s/%s current_name=%s cancelled=%s"
                    % (job.inputs, job.outdir, job.state, job.running,
                       getattr(job, "rc", None), job.current, job.total,
                       job.current_name, job.cancelled))
    except Exception as exc:
        return "任务上下文采集失败：%r" % (exc,)


def _log_error(component: str, message: str,
               exc: BaseException | None = None,
               request: str | None = None) -> None:
    """统一报错落盘：组件 + 消息 + 环境状态 + 任务上下文 + 异常栈。

    这是「运行时报错记录在日志」的核心入口：任何未处理异常都应通过本函数
    记录当时的涉及组件与环境状态，而非仅留一句 traceback。
    """
    snap = _env_snapshot()
    lines = ["[ERROR] 组件=%s 消息=%s" % (component, message)]
    if request:
        lines.append("请求上下文=%s" % request)
    lines.append("环境状态:")
    for key in ("timestamp", "version", "python", "platform", "system", "machine",
                "cwd", "executable", "frozen", "pid", "thread", "cpu_count",
                "thread_count", "mem_avail_mb", "mem_total_mb"):
        if key in snap and snap[key] is not None:
            lines.append("    %s=%s" % (key, snap[key]))
    lines.append("任务上下文=%s" % _job_context())
    if exc is not None:
        lines.append("异常类型=%s" % type(exc).__name__)
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        lines.append(tb.rstrip())
    for ln in lines:
        _append_log(ln)


def _excepthook(exc_type, exc, tb) -> None:
    _log_error("主线程未捕获异常", "进程级未捕获异常", exc)


def _thread_excepthook(args) -> None:
    name = args.thread.name if getattr(args, "thread", None) else "?"
    _log_error("线程未捕获异常(%s)" % name, "线程级未捕获异常", args.exc_value)


# --------------------------------------------------------------------------- #
# 子进程编码副本目录：父进程持有、父进程清理
# extract.py 的 atexit 在 terminate() 时不会执行，取消强杀会把用户文档的
# UTF-8 副本留在 %TEMP%。所以由这里创建、经 JINGHE_ENCDIR 传入，finally 必删。
# --------------------------------------------------------------------------- #
_RUN_LOCK = threading.Lock()
_RUN_SEQ = 0
_RUN_DIRS: set[str] = set()
# 只认这种精确形状，绝不按前缀模糊匹配，避免误伤同名前缀的其它目录
_RUN_DIR_RE = re.compile(r"^jinghe-run-(\d+)-(\d+)$")


def _new_enc_dir() -> Path:
    global _RUN_SEQ
    with _RUN_LOCK:
        _RUN_SEQ += 1
        seq = _RUN_SEQ
    path = Path(tempfile.gettempdir()) / ("jinghe-run-%d-%d" % (os.getpid(), seq))
    path.mkdir(parents=True, exist_ok=True)
    with _RUN_LOCK:
        _RUN_DIRS.add(str(path))
    return path


def _drop_enc_dir(path: Path) -> None:
    shutil.rmtree(str(path), ignore_errors=True)
    with _RUN_LOCK:
        _RUN_DIRS.discard(str(path))


def _sweep_run_dirs() -> None:
    """兜底：清掉本进程创建过 / 遗留的 jinghe-run-*（只扫自己的 pid）。"""
    with _RUN_LOCK:
        dirs = list(_RUN_DIRS)
        _RUN_DIRS.clear()
    for item in dirs:
        shutil.rmtree(item, ignore_errors=True)
    try:
        for child in Path(tempfile.gettempdir()).glob("jinghe-run-%d-*" % os.getpid()):
            shutil.rmtree(child, ignore_errors=True)
    except Exception:
        pass


def _pid_alive(pid: int) -> bool:
    """存活判定。**保守优先**：任何拿不准的情况一律判「活着」，
    宁可留一份垃圾，也不误删另一个正在运行的实例手上的目录。"""
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except OSError:
            return True
        return True
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    ERROR_INVALID_PARAMETER = 87      # 该 pid 不存在
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        # 打不开：87 = 没这个进程；其它（典型是 5 拒绝访问）= 存在但够不着，算活着
        return kernel32.GetLastError() != ERROR_INVALID_PARAMETER
    except Exception:
        return True


def _sweep_orphan_dirs() -> int:
    """启动时清掉**已死进程**遗留的 jinghe-run-<pid>-<seq>，返回清理个数。

    为什么需要：`_sweep_run_dirs()` 只认自己的 pid，而上一条清理链依赖
    `finally` / `atexit`，两者在 `TerminateProcess`（任务管理器强杀、
    强关窗口）下都不执行 —— 于是那份 UTF-8 副本会永久留在 %TEMP%。
    本函数补的正是这个缺口，是 §8.6「所有权与生命周期对齐」的收尾。

    安全边界：只碰 `jinghe-run-<数字>-<数字>` 这一种名字；pid 仍存在
    （含被系统复用给无关进程的情形）一律跳过。pid 复用导致的漏清属
    可接受残留，比误删正在跑的任务安全得多。
    """
    me = os.getpid()
    swept = 0
    try:
        children = list(Path(tempfile.gettempdir()).iterdir())
    except Exception:
        return 0
    for child in children:
        m = _RUN_DIR_RE.match(child.name)
        if not m or not child.is_dir():
            continue
        pid = int(m.group(1))
        if pid == me or _pid_alive(pid):
            continue
        shutil.rmtree(str(child), ignore_errors=True)
        if not child.exists():
            swept += 1
    return swept


atexit.register(_sweep_run_dirs)


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONUTF8"] = "1"
    return env


def _extract_cmd(extra: list[str]) -> list[str]:
    """冻结后用 exe 自我重入 --cli（onefile 没有独立解释器）；源码用当前解释器跑 extract.py。"""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--cli"] + list(extra)
    cmd = [sys.executable, "-u", str(EXTRACT)]
    if VENDOR_SCRIPT.is_file():
        cmd += ["--skill-script", str(VENDOR_SCRIPT)]
    return cmd + list(extra)


def _popen_kwargs(enc_dir: Path | None = None) -> dict:
    env = _child_env()
    if enc_dir is not None:
        env["JINGHE_ENCDIR"] = str(enc_dir)
    kwargs = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "bufsize": 1,
        "env": env,
    }
    if os.name == "nt":
        kwargs["creationflags"] = CREATE_NO_WINDOW
    return kwargs


# --------------------------------------------------------------------------- #
# extract.py 能力探测（--version / --progress 可能尚未提供）
# --------------------------------------------------------------------------- #
_CAP_LOCK = threading.Lock()
_CAP: dict | None = None
_CONVERTER = ""


def capabilities() -> dict:
    global _CAP
    with _CAP_LOCK:
        if _CAP is not None:
            return _CAP
        cap = {"version": "unknown", "progress": False}
        try:
            probe = subprocess.run(
                _extract_cmd(["--help"]),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                env=_child_env(),
                **(dict(creationflags=CREATE_NO_WINDOW) if os.name == "nt" else {}),
            )
            text = (probe.stdout or "") + (probe.stderr or "")
            cap["progress"] = "--progress" in text
            if "--version" in text:
                vp = subprocess.run(
                    _extract_cmd(["--version"]),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                    env=_child_env(),
                    **(dict(creationflags=CREATE_NO_WINDOW) if os.name == "nt" else {}),
                )
                if vp.returncode == 0 and (vp.stdout or "").strip():
                    cap["version"] = (vp.stdout or "").strip().splitlines()[0].strip()
        except Exception:
            pass
        _CAP = cap
        return cap


# --------------------------------------------------------------------------- #
# 任务与事件队列
# --------------------------------------------------------------------------- #
class Job:
    def __init__(self, inputs: list[str], outdir: str) -> None:
        self.inputs = list(inputs)
        # self.input 保留为「单值视图」：多选时为空串，既有 _api_state / 摘要引用不断
        self.input = self.inputs[0] if len(self.inputs) == 1 else ""
        self.outdir = outdir
        self.events: list[dict] = []
        self.lock = threading.Lock()
        self.proc: subprocess.Popen | None = None
        # 任务线程句柄：供 _reap_dead_job() 判断线程是否已退出（僵尸 job 兜底）
        self.thread: threading.Thread | None = None
        self.running = True
        self.cancelled = False
        self.state = "running"
        self.summary: dict | None = None
        self.error: str | None = None
        self.rc: int | None = None
        self.started = time.time()
        self.total = 0
        self.current = 0
        self.current_name = ""
        self.converter = ""
        self.success: int | None = None
        self.candidates: int | None = None
        self.empty: int | None = None
        self.no_heading: int | None = None

    def add(self, etype: str, text: str, progress: float | None = None,
            raw: str | None = None, **extra) -> dict:
        with self.lock:
            ev: dict = {"i": len(self.events) + 1, "type": etype, "text": text}
            if progress is not None:
                ev["progress"] = round(float(progress), 4)
            if raw is not None:
                ev["raw"] = raw
            ev.update(extra)
            self.events.append(ev)
            return ev


_JOB: Job | None = None
_JOB_LOCK = threading.Lock()
_LAST_INPUT = ""
_LAST_INPUTS: list[str] = []
_LAST_OUTDIR = ""

# ---- 桌面端「关窗即退」：页面心跳 + 看门狗 --------------------------------
# 页面每 2 秒打一次 /api/heartbeat；窗口被关闭后心跳停止。看门狗在宽限期
# 内没见到心跳且没有任务在跑，就让 serve_forever 退出、进程随之结束——
# 桌面软件的直觉是「关了窗口程序就该退」，而不是留一个无界面的后台进程。
# 宽限期取 90s：Edge 最小化超过 5 分钟会把页面定时器节流到约 1 次/分钟，
# 60s < 90s 保证最小化不会被误判为关窗。
_LAST_SEEN = time.time()
_SEEN_LOCK = threading.Lock()
HEARTBEAT_GRACE = 90.0   # 无心跳宽限期（秒，可被设置项覆盖）
HEARTBEAT_CHECK = 15.0   # 看门狗巡检周期（秒）

# ---- 设置项：本地持久化 ---------------------------------------------------
# 桌面软件的设置必须活过进程重启，所以落盘到 %LOCALAPPDATA%\Jinghe\settings.json。
# 全部设置都在本机，不上传任何数据。
SETTINGS_FILE = LOG_DIR / "settings.json"
DEFAULT_SETTINGS = {
    "auto_exit": True,           # 关闭窗口后自动退出
    "exit_grace_seconds": 90,    # 自动退出宽限期（秒）
    "remember_paths": True,      # 记住上次的输入/输出路径
    "default_outdir": "",        # 默认输出目录；留空 = 按时间自动生成
}
_SETTINGS_LOCK = threading.Lock()
_SETTINGS_CACHE: dict | None = None


def _validate_settings(data: object) -> dict:
    """把外部输入收敛成合法设置：非法值退回默认，绝不因脏数据崩掉。"""
    out = dict(DEFAULT_SETTINGS)
    if not isinstance(data, dict):
        return out
    for key in ("auto_exit", "remember_paths"):
        if key in data:
            out[key] = bool(data[key])
    if "exit_grace_seconds" in data:
        try:
            val = int(data["exit_grace_seconds"])
        except (TypeError, ValueError):
            val = int(DEFAULT_SETTINGS["exit_grace_seconds"])
        out["exit_grace_seconds"] = max(30, min(600, val))
    if "default_outdir" in data:
        val = data["default_outdir"]
        out["default_outdir"] = val.strip() if isinstance(val, str) else ""
    return out


def _load_settings() -> dict:
    """读取设置（带缓存）。文件损坏或缺失时静默回退默认值。"""
    global _SETTINGS_CACHE
    with _SETTINGS_LOCK:
        if _SETTINGS_CACHE is not None:
            return dict(_SETTINGS_CACHE)
        data: dict = {}
        try:
            if SETTINGS_FILE.is_file():
                raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    data = raw
        except (OSError, ValueError) as exc:
            _append_log("[WARN] 读取设置文件失败，按默认设置启动：%r" % (exc,))
        _SETTINGS_CACHE = _validate_settings(data)
        return dict(_SETTINGS_CACHE)


def _save_settings(data: object) -> dict:
    """保存设置：先写临时文件再原子替换，避免写一半损坏配置。"""
    global _SETTINGS_CACHE
    clean = _validate_settings(data)
    with _SETTINGS_LOCK:
        _SETTINGS_CACHE = clean
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            tmp = SETTINGS_FILE.with_name(SETTINGS_FILE.name + ".tmp")
            tmp.write_text(json.dumps(clean, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            tmp.replace(SETTINGS_FILE)
        except OSError as exc:
            _append_log("[ERROR] 保存设置失败：%r" % (exc,))
    return dict(clean)


def _touch_heartbeat() -> None:
    global _LAST_SEEN
    with _SEEN_LOCK:
        _LAST_SEEN = time.time()


def _start_window_watchdog(httpd: ThreadingHTTPServer) -> None:
    """仅「打开过窗口」的实例启动看门狗；--no-browser（测试/手动）永不自动退出。"""

    def _watch() -> None:
        while True:
            time.sleep(HEARTBEAT_CHECK)
            # 每次巡检读一次设置：用户在「设置」页改完立即生效，无需重启
            cfg = _load_settings()
            if not cfg.get("auto_exit", True):
                continue
            try:
                grace = float(cfg.get("exit_grace_seconds") or HEARTBEAT_GRACE)
            except (TypeError, ValueError):
                grace = HEARTBEAT_GRACE
            with _SEEN_LOCK:
                idle = time.time() - _LAST_SEEN
            if idle <= grace:
                continue
            with _JOB_LOCK:
                job = _JOB
                running = bool(job and job.running)
            if running:
                # 任务运行中不打断；窗口若已关闭，任务结束后下一轮巡检再退出
                continue
            _append_log("[INFO] 窗口已关闭（%.0f 秒无心跳），精核自动退出" % idle)
            try:
                httpd.shutdown()  # 看门狗线程调用，serve_forever 会正常返回
            except Exception:
                os._exit(0)  # shutdown 失败也不能留死进程
            return

    threading.Thread(target=_watch, name="window-watchdog", daemon=True).start()


def _reap_dead_job() -> None:
    """僵尸 job 兜底：任务线程已退出但 running 仍为 true 时强制复位。

    正常路径由 _run_job_inner 的 finally 复位；这里只兜底「线程根本没跑起来」
    或「线程在 finally 之外崩溃」（如 _new_enc_dir 抛异常）导致的残留状态，
    避免 /api/state 与 /api/progress 永远返回 running=true 把前端锁死。
    与 _api_run 共用 _JOB_LOCK，保证不会在「_JOB 已赋值但线程尚未 start」
    的中间态把正常任务误判为僵尸；线程仍在运行或句柄缺失时一律不复位。
    """
    with _JOB_LOCK:
        job = _JOB
        if job is None or not job.running:
            return
        t = job.thread
        if t is None or t.is_alive():
            return
        with job.lock:
            job.running = False
            if job.state == "running":
                job.state = "failed"
    _append_log("[WARN] 任务线程已退出但状态未复位，已强制复位 running=false / state=failed")


def _norm_inputs(data: dict) -> list[str]:
    """请求体 → 输入路径列表：inputs 优先（去空白、去重、保序），否则回退单值 input。"""
    raw = data.get("inputs")
    out: list[str] = []
    seen: set[str] = set()
    if isinstance(raw, list):
        for value in raw:
            if not isinstance(value, str):
                continue
            path = value.strip()
            if not path:
                continue
            key = os.path.normcase(path)
            if key in seen:
                continue
            seen.add(key)
            out.append(path)
    if out:
        return out
    single = str(data.get("input") or "").strip()
    return [single] if single else []


def _input_args(inputs: list[str]) -> list[str]:
    """展开成 extract.py 的重复 -i 参数：["-i", a, "-i", b, ...]。"""
    args: list[str] = []
    for path in inputs:
        args += ["-i", path]
    return args


def _missing_text(missing: list[str]) -> str:
    """错误文案里最多列 3 个不存在路径，其余给出总数，避免长列表刷屏。"""
    shown = "、".join(missing[:3])
    if len(missing) > 3:
        shown += " 等 %d 项" % len(missing)
    return shown


PROGRESS_RE = re.compile(r"^\[PROGRESS\]\s+(\d+)\s*/\s*(\d+)\s*(.*)$")
DONE_RE = re.compile(
    r"^\[DONE\]\s*成功\s*(\d+)\s*/\s*候选\s*(\d+)\s*[；;]\s*空文件\s*(\d+)\s*[；;]\s*无标题层级\s*(\d+)"
)
CONV_RE = re.compile(r"^\[INFO\]\s*转换器来源:\s*(.+)$")
COUNT_RE = re.compile(
    r"盘点\s*(\d+)\s*个文件\s*->\s*文本类\s*(\d+)\s*/\s*富文档\s*(\d+)\s*/"
    r"\s*阶段3预留\s*(\d+)\s*/\s*需预处理\s*(\d+)\s*/\s*不支持\s*(\d+)"
)
ITEM_RE = re.compile(r"^\s+\[(文本类|富文档|阶段3预留|需预处理|不支持)\]\s+(.+?)\s*$")


def _build_summary(job: Job, elapsed: float) -> dict:
    outdir = Path(job.outdir)
    degraded: list[dict] = []
    deferred = 0
    legacy = 0
    unsupported = 0
    prov_success: int | None = None
    prov = outdir / "provenance.json"
    if prov.is_file():
        try:
            data = json.loads(prov.read_text(encoding="utf-8"))
            entries = data.get("entries") or []
            if isinstance(entries, list) and entries:
                for e in entries:
                    if not isinstance(e, dict):
                        continue
                    status = str(e.get("status") or "")
                    if status == "成功":
                        prov_success = (prov_success or 0) + 1
                    elif _is_out_of_scope(status):
                        # 本期范围外、从未尝试：不算降级，单独计数
                        if status.startswith(("阶段 3", "阶段3")):
                            deferred += 1
                        elif status.startswith("需预处理"):
                            legacy += 1
                        else:
                            unsupported += 1
                    else:
                        degraded.append({
                            "name": str(e.get("path") or ""),
                            "status": status,
                            "note": str(e.get("note") or ""),
                        })
        except Exception:
            pass

    verdict = ""
    log_file = outdir / "run.log"
    if log_file.is_file():
        try:
            for line in log_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("验收:"):
                    verdict = line[len("验收:"):].strip()
                elif line.startswith("- 转换器:") and not job.converter:
                    job.converter = line.split(":", 1)[1].strip()
        except Exception:
            pass

    md_dir = outdir / "md"
    produced = len(list(md_dir.glob("*.md"))) if md_dir.is_dir() else 0

    if job.success is not None:
        success = job.success
    elif prov_success is not None:
        success = prov_success
    else:
        # 取消/中断时还没有 provenance：按已落盘 md 估算，供「已产出（未完成）」展示
        success = produced
    if job.candidates is not None:
        candidates = job.candidates
    elif job.total:
        candidates = job.total
    else:
        candidates = success + len(degraded)
    return {
        "success": int(success),
        "candidates": int(candidates),
        "failed": max(int(candidates) - int(success), 0),
        "deferred": int(deferred),
        "legacy": int(legacy),
        "unsupported": int(unsupported),
        "produced": int(produced),
        "empty": int(job.empty or 0),
        "no_heading": int(job.no_heading or 0),
        "elapsed": round(elapsed, 1),
        "outdir": job.outdir,
        "converter": job.converter or _CONVERTER,
        "verdict": verdict,
        "degraded": degraded,
    }


def _is_out_of_scope(status: str) -> bool:
    """阶段 3 预留 / 需预处理 / 不支持：本期从未尝试，不属于「候选失败」。"""
    return status.startswith(("阶段 3", "阶段3", "需预处理", "不支持"))


def _error_tail(lines: list[str]) -> str:
    for line in reversed(lines):
        if line.startswith("[ERROR]"):
            return line.strip()
    tail = [ln.strip() for ln in lines if ln.strip()][-3:]
    return " / ".join(tail)[:500]


def _run_job(job: Job) -> None:
    """每个任务独占一个编码副本目录，无论正常/失败/强杀都在 finally 清掉。"""
    enc_dir = _new_enc_dir()
    try:
        _run_job_inner(job, enc_dir)
    finally:
        _drop_enc_dir(enc_dir)


def _run_job_inner(job: Job, enc_dir: Path) -> None:
    # 整个任务体包在 try/finally 里：无论 _extract_cmd / capabilities /
    # _build_summary 等任何一步抛未捕获异常，都必须无条件复位 running，
    # 否则 daemon 线程崩溃后 /api/state 与 /api/progress 永远 running=true，
    # 前端按钮会被永久禁用（刷新后 init 又会重新锁死）。
    # 时序保持不变：本层 finally 先落地 running=false，_run_job 的 finally
    # 再清理编码副本目录（test_app.py 的强杀用例依赖这个先后顺序）。
    tail: list[str] = []
    try:
        cmd = _extract_cmd(_input_args(job.inputs) + ["-o", job.outdir])
        if capabilities()["progress"]:
            cmd.append("--progress")
        try:
            proc = subprocess.Popen(cmd, **_popen_kwargs(enc_dir))
            job.proc = proc
            if job.cancelled and proc.poll() is None:
                # 取消请求早于进程就绪：补一次终止，避免「已取消但仍在跑」
                proc.terminate()
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = raw.rstrip("\r\n")
                if not line.strip():
                    continue
                m = PROGRESS_RE.match(line)
                if m:
                    cur, total = int(m.group(1)), int(m.group(2))
                    name = m.group(3).strip()
                    job.current, job.total, job.current_name = cur, total, name
                    job.add("progress", name or line,
                            progress=(cur / total if total else 0.0), raw=line,
                            current=cur, total=total)
                    continue
                m = DONE_RE.match(line)
                if m:
                    job.success = int(m.group(1))
                    job.candidates = int(m.group(2))
                    job.empty = int(m.group(3))
                    job.no_heading = int(m.group(4))
                    job.add("done", line, raw=line)
                    continue
                m = CONV_RE.match(line)
                if m:
                    job.converter = m.group(1).strip()
                tail.append(line)
                job.add("log", line, raw=line)
            rc = proc.wait()
            job.rc = rc
        except Exception as exc:  # 子进程都起不来
            rc = -1
            job.rc = rc
            msg = "无法启动 extract.py：%s" % exc
            job.add("log", msg, raw=msg)
            tail.append(msg)
            _log_error("提取任务-启动子进程", msg, exc)

        elapsed = time.time() - job.started
        job.summary = _build_summary(job, elapsed)
        if job.cancelled:
            job.state = "cancelled"
        elif rc != 0:
            job.state = "failed"
            job.error = "extract.py 退出码 %d：%s" % (rc, _error_tail(tail))
            job.add("log", job.error, raw=job.error)
        else:
            job.state = "done"
    except Exception as exc:
        # 兜底异常路径：state 必须落为 failed，不能残留 "running"。
        # 只处理「任务体抛出未捕获异常」，正常 done/cancelled/failed 判定不受影响。
        job.state = "failed"
        job.error = "任务异常：%s" % exc
        job.add("log", job.error, raw=job.error)
        _log_error("提取任务", "任务线程未捕获异常", exc)
    finally:
        with job.lock:
            job.running = False
            if job.state == "running":
                job.state = "failed"


# --------------------------------------------------------------------------- #
# 文件夹选择对话框（ctypes，Windows 原生）
# 主路径 IFileDialog：SetFolder 只定位、不限制，用户可自由向上导航。
# 失败回退 SHBrowseForFolderW(root=None)：从「此电脑」自由浏览，只丢定位。
# --------------------------------------------------------------------------- #
class _BROWSEINFOW(ctypes.Structure):
    _fields_ = [
        ("hwndOwner", ctypes.c_void_p),
        ("pidlRoot", ctypes.c_void_p),
        ("pszDisplayName", ctypes.c_wchar_p),
        ("lpszTitle", ctypes.c_wchar_p),
        ("ulFlags", ctypes.c_uint),
        ("lpfn", ctypes.c_void_p),
        ("lParam", ctypes.c_ssize_t),
        ("iImage", ctypes.c_int),
    ]


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _guid(d1: int, d2: int, d3: int, data4: tuple[int, ...]) -> _GUID:
    return _GUID(d1, d2, d3, (ctypes.c_ubyte * 8)(*data4))


CLSID_FileOpenDialog = _guid(0xDC1C5A9C, 0xE88A, 0x4DDE,
                             (0xA5, 0xA1, 0x60, 0xF8, 0x2A, 0x20, 0xAE, 0xF7))
IID_IFileDialog = _guid(0x42F85136, 0xDB7E, 0x439C,
                        (0x85, 0xF1, 0xE4, 0x07, 0x5D, 0x13, 0x5F, 0xC8))
IID_IShellItem = _guid(0x43826D1E, 0xE718, 0x42EE,
                       (0xBC, 0x55, 0xA1, 0xE2, 0x61, 0xC3, 0x7B, 0xFE))

_FOS_PICKFOLDERS = 0x00000020
_FOS_FORCEFILESYSTEM = 0x00000040
_SIGDN_FILESYSPATH = 0x80058000
_ERROR_CANCELLED = 0x800704C7

# 以下 vtable 下标只用于「选择文件夹」（_pick_folder_com，IFileDialog 单继承链）。
# 多选文件对话框已改用 comdlg32.GetOpenFileNameW，不再依赖任何 IFileOpenDialog
# 下标 —— 那组下标曾先后引发「GetResults 0x00000000」「0x80004005」两次必现失败。
_VT_SHOW = 3
_VT_SET_OPTIONS = 9
_VT_GET_OPTIONS = 10
_VT_SET_FOLDER = 12
_VT_SET_TITLE = 17
_VT_GET_RESULT = 20
_VT_SET_FILE_TYPES = 4
_VT_RELEASE = 2
_VT_GET_DISPLAY_NAME = 5
# 注意：上面这组 COM vtable 下标现在只服务于「选择文件夹」（pick_folder）。
# 「选择文件（多选）」已改用下面的 comdlg32.GetOpenFileNameW，不再碰 vtable。


# --------------------------------------------------------------------------- #
# 多选文件对话框：comdlg32.GetOpenFileNameW（纯 Win32 API）
#
# 为什么弃用 IFileOpenDialog::GetResults：那条路依赖人工记忆的 COM vtable 下标，
# 线上先后必现「GetResults 0x00000000」（越界槽返回 S_OK 但结果指针为 NULL）和
# 「GetResults 0x80004005」（调到了别的方法），两次都没修好。GetOpenFileNameW 是
# 稳定的 Win32 ABI：普通函数 + OPENFILENAMEW 结构体，无 vtable、无 STA 套间要求，
# 原生支持多选和文件类型过滤；Vista+ 配合 OFN_EXPLORER 仍呈现现代通用对话框。
# --------------------------------------------------------------------------- #
class _OPENFILENAMEW(ctypes.Structure):
    _fields_ = [
        ("lStructSize", ctypes.c_uint32),
        ("hwndOwner", ctypes.c_void_p),
        ("hInstance", ctypes.c_void_p),
        ("lpstrFilter", ctypes.c_void_p),
        ("lpstrCustomFilter", ctypes.c_void_p),
        ("nMaxCustFilter", ctypes.c_uint32),
        ("nFilterIndex", ctypes.c_uint32),
        ("lpstrFile", ctypes.c_void_p),
        ("nMaxFile", ctypes.c_uint32),
        ("lpstrFileTitle", ctypes.c_void_p),
        ("nMaxFileTitle", ctypes.c_uint32),
        ("lpstrInitialDir", ctypes.c_void_p),
        ("lpstrTitle", ctypes.c_void_p),
        ("Flags", ctypes.c_uint32),
        ("nFileOffset", ctypes.c_uint16),
        ("nFileExtension", ctypes.c_uint16),
        ("lpstrDefExt", ctypes.c_void_p),
        ("lCustData", ctypes.c_void_p),      # LPARAM：指针宽度，随 32/64 位变化
        ("lpfnHook", ctypes.c_void_p),
        ("lpTemplateName", ctypes.c_void_p),
        ("pvReserved", ctypes.c_void_p),
        ("dwReserved", ctypes.c_uint32),
        ("FlagsEx", ctypes.c_uint32),
    ]


_OFN_HIDEREADONLY = 0x00000004
_OFN_NOCHANGEDIR = 0x00000008
_OFN_ALLOWMULTISELECT = 0x00000200
_OFN_PATHMUSTEXIST = 0x00000800
_OFN_FILEMUSTEXIST = 0x00001000
_OFN_EXPLORER = 0x00080000
_OFN_LONGNAMES = 0x00200000
_OFN_ENABLESIZING = 0x00800000
_FNERR_BUFFERTOOSMALL = 0x3003
_OFN_FILE_BUFFER_CHARS = 65536  # 64K wchar，足够容纳数百个多选文件

_OFN_FLAGS = (_OFN_HIDEREADONLY | _OFN_NOCHANGEDIR | _OFN_ALLOWMULTISELECT
              | _OFN_EXPLORER | _OFN_PATHMUSTEXIST | _OFN_FILEMUSTEXIST
              | _OFN_LONGNAMES | _OFN_ENABLESIZING)

_OFN_TITLE = "选择要提取的文件（可多选）"

# 「把日志生成到指定文件」用 GetSaveFileNameW（另存为）：
# 与多选打开框共用 _OPENFILENAMEW 结构，但不能带 ALLOWMULTISELECT / FILEMUSTEXIST，
# 改带 OVERWRITEPROMPT（覆盖已有文件时让用户确认）。
_OFN_OVERWRITEPROMPT = 0x00000002
_SAVE_FLAGS = (_OFN_HIDEREADONLY | _OFN_NOCHANGEDIR | _OFN_EXPLORER
               | _OFN_PATHMUSTEXIST | _OFN_LONGNAMES | _OFN_ENABLESIZING
               | _OFN_OVERWRITEPROMPT)
_SAVE_TITLE = "把运行日志生成到指定文件"

# 过滤器：name\0spec\0 依次排列，末尾再补一个 \0 表示整表结束
_FILE_FILTERS = [
    ("常用文档",
     "*.pdf;*.docx;*.doc;*.xlsx;*.xls;*.pptx;*.ppt;*.txt;*.md;*.markdown;"
     "*.html;*.htm;*.csv;*.json;*.epub"),
    ("全部支持格式",
     "*.pdf;*.docx;*.doc;*.xlsx;*.xls;*.pptx;*.ppt;*.txt;*.md;*.markdown;"
     "*.html;*.htm;*.csv;*.json;*.epub;*.rtf;*.odt;*.ods;*.odp;*.zip;"
     "*.log;*.xml;*.yaml;*.yml;*.ini;*.py;*.js"),
    ("所有文件", "*.*"),
]


def _ofn_filter_string() -> str:
    return "".join("%s\0%s\0" % (n, s) for n, s in _FILE_FILTERS) + "\0"


def _split_ofn_buffer(buf, size: int) -> list[str]:
    """把 lpstrFile 缓冲按 NUL 切段；多选格式为 dir\\0f1\\0f2\\0\\0。"""
    parts: list[str] = []
    cur: list[str] = []
    for i in range(size):
        ch = buf[i]
        if ch == "\x00":
            if cur:
                parts.append("".join(cur))
                cur = []
            elif parts:
                break  # 连续两个 NUL = 结果结束
        else:
            cur.append(ch)
    if cur:
        parts.append("".join(cur))
    return parts


def _parse_ofn_paths(parts: list[str]) -> list[str]:
    """把 GetOpenFileNameW 的缓冲段还原成完整路径列表。"""
    if not parts:
        return []
    if len(parts) == 1:
        return [parts[0]]  # 只选一个文件时给的是完整路径
    base = parts[0]       # 选多个时第一段是目录，其后是文件名
    return [os.path.join(base, p) for p in parts[1:]]


def _pick_files_win32(initial: str) -> list[str]:
    """GetOpenFileNameW 多选；用户取消返回 []，真实错误抛异常。"""
    comdlg32 = ctypes.windll.comdlg32
    user32 = ctypes.windll.user32
    comdlg32.GetOpenFileNameW.restype = ctypes.c_int
    comdlg32.GetOpenFileNameW.argtypes = [ctypes.POINTER(_OPENFILENAMEW)]
    comdlg32.CommDlgExtendedError.restype = ctypes.c_uint32
    comdlg32.CommDlgExtendedError.argtypes = []
    user32.GetForegroundWindow.restype = ctypes.c_void_p

    filt = ctypes.create_unicode_buffer(_ofn_filter_string())
    filebuf = ctypes.create_unicode_buffer(_OFN_FILE_BUFFER_CHARS)
    initbuf = ctypes.create_unicode_buffer(1024)
    titlebuf = ctypes.create_unicode_buffer(_OFN_TITLE)

    folder = ""
    if initial:
        if os.path.isdir(initial):
            folder = os.path.abspath(initial)
        elif os.path.isfile(initial):
            folder = os.path.dirname(os.path.abspath(initial))
    if folder and len(folder) < 1000:
        initbuf.value = folder

    ofn = _OPENFILENAMEW()
    ofn.lStructSize = ctypes.sizeof(_OPENFILENAMEW)
    ofn.hwndOwner = ctypes.c_void_p(user32.GetForegroundWindow())
    ofn.lpstrFilter = ctypes.cast(filt, ctypes.c_void_p)
    ofn.nFilterIndex = 1
    ofn.lpstrFile = ctypes.cast(filebuf, ctypes.c_void_p)
    ofn.nMaxFile = _OFN_FILE_BUFFER_CHARS
    ofn.lpstrInitialDir = (ctypes.cast(initbuf, ctypes.c_void_p)
                           if folder else None)
    ofn.lpstrTitle = ctypes.cast(titlebuf, ctypes.c_void_p)
    ofn.Flags = _OFN_FLAGS

    ok = comdlg32.GetOpenFileNameW(ctypes.byref(ofn))
    if not ok:
        err = comdlg32.CommDlgExtendedError()
        if err == 0:
            return []  # 用户取消
        if err == _FNERR_BUFFERTOOSMALL:
            raise OSError("所选文件过多，超出选择框缓冲容量，请分批选择")
        raise OSError("GetOpenFileNameW 0x%04X" % err)
    return _parse_ofn_paths(_split_ofn_buffer(filebuf, _OFN_FILE_BUFFER_CHARS))


def _pick_save_file_win32(default_name: str) -> str | None:
    """GetSaveFileNameW 另存为；用户取消返回 None，真实错误抛异常。"""
    comdlg32 = ctypes.windll.comdlg32
    user32 = ctypes.windll.user32
    comdlg32.GetSaveFileNameW.restype = ctypes.c_int
    comdlg32.GetSaveFileNameW.argtypes = [ctypes.POINTER(_OPENFILENAMEW)]
    comdlg32.CommDlgExtendedError.restype = ctypes.c_uint32
    comdlg32.CommDlgExtendedError.argtypes = []
    user32.GetForegroundWindow.restype = ctypes.c_void_p

    filt = ctypes.create_unicode_buffer(
        "日志文件\0*.log\0文本文件\0*.txt\0Markdown\0*.md\0所有文件\0*.*\0\0")
    filebuf = ctypes.create_unicode_buffer(1024)
    filebuf.value = default_name
    initbuf = ctypes.create_unicode_buffer(1024)
    initbuf.value = str(LOG_DIR)
    titlebuf = ctypes.create_unicode_buffer(_SAVE_TITLE)
    defext = ctypes.create_unicode_buffer("log")

    ofn = _OPENFILENAMEW()
    ofn.lStructSize = ctypes.sizeof(_OPENFILENAMEW)
    ofn.hwndOwner = ctypes.c_void_p(user32.GetForegroundWindow())
    ofn.lpstrFilter = ctypes.cast(filt, ctypes.c_void_p)
    ofn.nFilterIndex = 1
    ofn.lpstrFile = ctypes.cast(filebuf, ctypes.c_void_p)
    ofn.nMaxFile = 1024
    ofn.lpstrInitialDir = ctypes.cast(initbuf, ctypes.c_void_p)
    ofn.lpstrTitle = ctypes.cast(titlebuf, ctypes.c_void_p)
    ofn.lpstrDefExt = ctypes.cast(defext, ctypes.c_void_p)
    ofn.Flags = _SAVE_FLAGS

    ok = comdlg32.GetSaveFileNameW(ctypes.byref(ofn))
    if not ok:
        err = comdlg32.CommDlgExtendedError()
        if err == 0:
            return None  # 用户取消
        raise OSError("GetSaveFileNameW 0x%04X" % err)
    return filebuf.value


def _com_method(ptr, index: int, restype, *argtypes):
    vtable = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    proto = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    return proto(vtable[index])


def _com_release(ptr) -> None:
    try:
        _com_method(ptr, _VT_RELEASE, ctypes.c_ulong)(ptr)
    except Exception:
        pass


def _pick_folder_com(initial: str) -> str | None:
    """IFileDialog 主路径；非取消错误抛异常，交由调用方回退。"""
    ole32 = ctypes.windll.ole32
    shell32 = ctypes.windll.shell32
    user32 = ctypes.windll.user32

    ole32.CoCreateInstance.restype = ctypes.c_long
    ole32.CoCreateInstance.argtypes = [
        ctypes.POINTER(_GUID), ctypes.c_void_p, ctypes.c_ulong,
        ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p),
    ]
    shell32.SHCreateItemFromParsingName.restype = ctypes.c_long
    shell32.SHCreateItemFromParsingName.argtypes = [
        ctypes.c_wchar_p, ctypes.c_void_p, ctypes.POINTER(_GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    user32.GetForegroundWindow.restype = ctypes.c_void_p

    dialog = ctypes.c_void_p()
    hr = ole32.CoCreateInstance(
        ctypes.byref(CLSID_FileOpenDialog), None, 1,
        ctypes.byref(IID_IFileDialog), ctypes.byref(dialog),
    )
    if hr != 0 or not dialog:
        raise OSError("CoCreateInstance 0x%08X" % (hr & 0xFFFFFFFF))

    try:
        get_options = _com_method(dialog, _VT_GET_OPTIONS, ctypes.c_long,
                                  ctypes.POINTER(ctypes.c_uint32))
        options = ctypes.c_uint32(0)
        if get_options(dialog, ctypes.byref(options)) == 0:
            set_options = _com_method(dialog, _VT_SET_OPTIONS, ctypes.c_long, ctypes.c_uint32)
            set_options(dialog, ctypes.c_uint32(
                options.value | _FOS_PICKFOLDERS | _FOS_FORCEFILESYSTEM))

        set_title = _com_method(dialog, _VT_SET_TITLE, ctypes.c_long, ctypes.c_wchar_p)
        set_title(dialog, "选择文件夹")

        # 只定位，不限制浏览范围（与 SHBrowseForFolder 的 pidlRoot 不同）
        if initial and os.path.isdir(initial):
            item = ctypes.c_void_p()
            hr_item = shell32.SHCreateItemFromParsingName(
                os.path.abspath(initial), None, ctypes.byref(IID_IShellItem),
                ctypes.byref(item),
            )
            if hr_item == 0 and item:
                try:
                    _com_method(dialog, _VT_SET_FOLDER, ctypes.c_long, ctypes.c_void_p)(dialog, item)
                finally:
                    _com_release(item)

        show = _com_method(dialog, _VT_SHOW, ctypes.c_long, ctypes.c_void_p)
        hr = show(dialog, ctypes.c_void_p(user32.GetForegroundWindow()))
        if hr != 0:
            if (hr & 0xFFFFFFFF) == _ERROR_CANCELLED:
                return None
            raise OSError("Show 0x%08X" % (hr & 0xFFFFFFFF))

        result = ctypes.c_void_p()
        hr = _com_method(dialog, _VT_GET_RESULT, ctypes.c_long,
                         ctypes.POINTER(ctypes.c_void_p))(dialog, ctypes.byref(result))
        if hr != 0 or not result:
            raise OSError("GetResult 0x%08X" % (hr & 0xFFFFFFFF))
        try:
            name = ctypes.c_wchar_p()
            hr = _com_method(result, _VT_GET_DISPLAY_NAME, ctypes.c_long,
                             ctypes.c_uint32, ctypes.POINTER(ctypes.c_wchar_p))(
                result, ctypes.c_uint32(_SIGDN_FILESYSPATH), ctypes.byref(name))
            if hr != 0:
                raise OSError("GetDisplayName 0x%08X" % (hr & 0xFFFFFFFF))
            try:
                return str(name.value) if name.value else None
            finally:
                ole32.CoTaskMemFree(ctypes.cast(name, ctypes.c_void_p))
        finally:
            _com_release(result)
    finally:
        _com_release(dialog)


def _pick_folder_legacy() -> str | None:
    """回退：SHBrowseForFolderW，root=None，从「此电脑」自由浏览（不定位）。"""
    ole32 = ctypes.windll.ole32
    shell32 = ctypes.windll.shell32
    user32 = ctypes.windll.user32

    shell32.SHBrowseForFolderW.restype = ctypes.c_void_p
    shell32.SHBrowseForFolderW.argtypes = [ctypes.POINTER(_BROWSEINFOW)]
    shell32.SHGetPathFromIDListW.restype = ctypes.c_int
    shell32.SHGetPathFromIDListW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    user32.GetForegroundWindow.restype = ctypes.c_void_p

    display = ctypes.create_unicode_buffer(1024)
    bi = _BROWSEINFOW()
    bi.hwndOwner = user32.GetForegroundWindow()
    bi.pidlRoot = None
    bi.pszDisplayName = ctypes.cast(display, ctypes.c_wchar_p)
    bi.lpszTitle = "选择文件夹"
    bi.ulFlags = 0x00000001 | 0x00000040  # RETURNONLYFSDIRS | NEWDIALOGSTYLE
    pidl = shell32.SHBrowseForFolderW(ctypes.byref(bi))
    path = None
    if pidl:
        buf = ctypes.create_unicode_buffer(1024)
        if shell32.SHGetPathFromIDListW(pidl, buf):
            path = buf.value or None
        ole32.CoTaskMemFree(ctypes.c_void_p(pidl))
    return path


def pick_folder(initial: str = "") -> str | None:
    """弹出原生「选择文件夹」对话框；取消或任何异常返回 None。

    关键：IFileDialog 必须在 **STA** 套间里创建并显示。HTTP 工作线程默认是
    MTA（`CoInitialize(None)` 即 MTA），在 MTA 上 Show() 要么直接失败、
    要么在 worker 线程上死锁卡住，导致该请求永不返回、前端 fetch 超时
    （表现为「Failed to fetch」）。所以这里显式 CoInitializeEx(APARTMENTTHREADED)。
    """
    if os.name != "nt":
        return None
    ole32 = ctypes.windll.ole32
    ole32.CoInitializeEx.restype = ctypes.c_long
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    ole32.CoUninitialize.restype = None
    _COINIT_APARTMENTTHREADED = 2
    _RPC_E_CHANGED_MODE = 0x80010106
    hr = ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)
    if hr == _RPC_E_CHANGED_MODE:
        # 该线程已被初始化为 MTA（理论上本函数独占调用不会，但防御），
        # IFileDialog 无法在其中工作，直接回退到不依赖套间模型的旧式 API
        _append_log("[WARN] 线程已是 MTA，IFileDialog 不可用，回退 SHBrowseForFolderW")
        try:
            return _pick_folder_legacy()
        except Exception as exc:
            _append_log("[ERROR] 文件夹选择失败：%s" % exc)
            return None
    if hr < 0:
        _append_log("[ERROR] COM 初始化失败：0x%08X" % (hr & 0xFFFFFFFF))
        return None
    try:
        try:
            return _pick_folder_com(initial)
        except Exception as exc:
            _append_log("[WARN] IFileDialog 不可用，回退 SHBrowseForFolderW：%s" % exc)
            try:
                return _pick_folder_legacy()
            except Exception as exc2:
                _append_log("[ERROR] 文件夹选择失败：%s" % exc2)
                return None
    finally:
        ole32.CoUninitialize()


def pick_files_ex(initial: str = "") -> tuple[list[str], str | None]:
    """弹出原生多选文件对话框，返回 (路径列表, 错误说明)。

    **为什么要区分「用户取消」和「失败」**：两者过去都返回 []，前端无法分辨，
    于是对话框打不开时用户点「选择文件…」只看到「没反应」——正是本工具反复
    被吐槽的那类无反馈体验。取消返回 ([], None)，失败返回 ([], "原因")。

    走 comdlg32.GetOpenFileNameW（纯 Win32 API）：既不需要人工维护 COM vtable
    下标，也不要求 STA 套间。此前 IFileOpenDialog::GetResults 因下标错误先后必现
    「GetResults 0x00000000」「GetResults 0x80004005」，故整体换实现而非再猜数字。
    """
    if os.name != "nt":
        return [], "当前系统不支持原生文件选择框"
    try:
        return _pick_files_win32(initial), None
    except Exception as exc:
        _append_log("[ERROR] 文件选择失败：%s" % exc)
        return [], "打开文件选择框失败：%s" % exc


def pick_files(initial: str = "") -> list[str]:
    """兼容包装：只要路径列表（取消与失败都返回 []）。"""
    return pick_files_ex(initial)[0]


# --------------------------------------------------------------------------- #
# HTTP 处理
# --------------------------------------------------------------------------- #
MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}


def _dry_run(inputs: list[str]) -> dict:
    try:
        proc = subprocess.run(
            _extract_cmd(_input_args(inputs) + ["--dry-run"]),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=DRY_RUN_TIMEOUT,
            env=_child_env(),
            **(dict(creationflags=CREATE_NO_WINDOW) if os.name == "nt" else {}),
        )
    except subprocess.TimeoutExpired:
        # 单独分支：TimeoutExpired 是 Exception 的子类，若混进下面会把「超时」
        # 误报成「无法启动 extract.py」，前端 app.js:216 会把误导文案原样弹给用户。
        _append_log("[WARN] 仅预览超时（超过 %d 秒）：%s" % (
            DRY_RUN_TIMEOUT, "、".join(inputs[:3])))
        return {"ok": False, "error":
                "预览超时（超过 %d 秒）：目录过大、文件被占用或位于网络盘，请缩小选择范围后重试"
                % DRY_RUN_TIMEOUT}
    except Exception as exc:
        return {"ok": False, "error": "无法启动 extract.py：%s" % exc}

    out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    if proc.returncode != 0:
        err = ""
        for line in out.splitlines():
            if line.startswith("[ERROR]"):
                err = line.strip()
        if not err:
            tail = [ln.strip() for ln in out.splitlines() if ln.strip()][-3:]
            err = " / ".join(tail)[:500] or ("extract.py 退出码 %d" % proc.returncode)
        return {"ok": False, "error": err}

    global _CONVERTER, _LAST_INPUT, _LAST_INPUTS
    total = 0
    buckets = {"文本类": 0, "富文档": 0, "阶段3预留": 0, "需预处理": 0, "不支持": 0}
    items: list[dict] = []
    for line in out.splitlines():
        m = COUNT_RE.search(line)
        if m:
            total = int(m.group(1))
            buckets["文本类"] = int(m.group(2))
            buckets["富文档"] = int(m.group(3))
            buckets["阶段3预留"] = int(m.group(4))
            buckets["需预处理"] = int(m.group(5))
            buckets["不支持"] = int(m.group(6))
            continue
        m = ITEM_RE.match(line)
        if m:
            items.append({"name": m.group(2).strip(), "kind": m.group(1)})
            continue
        m = CONV_RE.match(line)
        if m:
            _CONVERTER = m.group(1).strip()
    _LAST_INPUTS = list(inputs)
    _LAST_INPUT = inputs[0] if len(inputs) == 1 else ""
    return {"ok": True, "buckets": buckets, "total": total, "items": items}


def _prepare_outdir(raw: str) -> tuple[str | None, str | None]:
    """返回 (绝对路径, 错误信息)。"""
    path = os.path.abspath(os.path.expanduser(raw))
    try:
        os.makedirs(path, exist_ok=True)
    except Exception as exc:
        return None, "无法创建输出目录：%s（%s）" % (path, exc)
    if not os.path.isdir(path):
        return None, "输出目录不是文件夹：%s" % path
    try:
        with tempfile.NamedTemporaryFile(dir=path, prefix=".jinghe-", delete=True):
            pass
    except Exception as exc:
        return None, "输出目录不可写：%s（%s）" % (path, exc)
    return path, None


def _open_document(path: Path) -> str:
    """用「一定看得见」的编辑器打开文档，返回打开方式标记。

    v0.3.7 实测：本机 `.md` 的用户级关联（HKCU UserChoice）指向单实例程序，
    `os.startfile` 不抛错却可能只把别的窗口切到前台，页面里毫无反应。
    桌面端因此固定用系统记事本打开合并文档；记事本缺失 / 非 Windows 时
    依次降级到系统关联与浏览器。测试启动器会把本函数替换为空操作。
    """
    notepad = (Path(os.environ.get("WINDIR", r"C:\Windows"))
               / "System32" / "notepad.exe")
    if os.name == "nt" and notepad.is_file():
        try:
            subprocess.Popen([str(notepad), str(path)])
            return "notepad"
        except Exception:
            pass  # 落到下面的系统关联 / 浏览器
    if hasattr(os, "startfile"):
        os.startfile(str(path))  # type: ignore[attr-defined]
        return "startfile"
    webbrowser.open(path.as_uri())
    return "browser"


def _merged_path(outdir: str) -> Path | None:
    """按输出目录解析 MERGED.md；端点只认固定文件名，不接受任意文件路径。

    v0.3.7：旧实现由前端拼 `outdir + "/MERGED.md"` 再交给通用 /api/open，
    Windows 上会产生混合分隔符；且 .md 常无系统关联，os.startfile 抛错后
    又被前端静默吞掉，表现成「按钮点了没反应」。这里统一由后端解析。
    """
    if not outdir:
        return None
    try:
        base = Path(os.path.abspath(os.path.expanduser(outdir)))
    except (OSError, ValueError):
        return None
    return base / MERGED_NAME


# --------------------------------------------------------------------------- #
# 阶段 2 / 3 后处理（纯标准库实现，守住「零第三方依赖 / 单文件 exe」设计不变量）
# --------------------------------------------------------------------------- #
_STAGE3_AUDIO_EXT = {
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".wma", ".amr",
    ".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".webm",
}



def _extractive_summary(md_text: str) -> str:
    """抽取式摘要（阶段 2 v1）：保留各级标题，并取每个小节首段前 2 行。

    深度语义提炼需接入 LLM，此处只做结构化抽取，绝不编造内容。
    """
    out: list[str] = []
    heading = None
    taken = 0
    for raw in md_text.splitlines():
        s = raw.strip()
        if not s:
            continue
        if s.startswith("#"):
            level = 0
            for ch in s:
                if ch == "#":
                    level += 1
                else:
                    break
            text = s[level:].strip()
            if level <= 3:
                out.append(("#" * level) + " " + text)
                heading = text
                taken = 0
            continue
        if heading and taken < 2:
            out.append(s)
            taken += 1
        elif not heading:
            out.append(s)
    return "\n".join(out)


class Handler(BaseHTTPRequestHandler):
    server_version = "JingheUI/%s" % extract.__version__
    protocol_version = "HTTP/1.1"

    # ---------------------------- 基础响应 ---------------------------- #
    def _send_bytes(self, body: bytes, ctype: str, code: int = 200) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_json(self, obj: dict, code: int = 200) -> None:
        self._send_bytes(json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                         "application/json; charset=utf-8", code)

    def _send_text(self, text: str, code: int = 200) -> None:
        self._send_bytes(text.encode("utf-8"), "text/plain; charset=utf-8", code)

    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        if length > 8 * 1024 * 1024:
            raise ValueError("请求体过大")
        raw = self.rfile.read(length)
        if not raw.strip():
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            raise ValueError("请求体不是合法 JSON")
        return data if isinstance(data, dict) else {}

    def log_message(self, fmt: str, *args) -> None:
        path = self.path.split("?", 1)[0]
        # 高频内部端点不记访问日志：心跳每 2 秒一次，progress/state 是轮询，
        # 逐条记录会把 app.log 变成噪音墙（实测半小时就 900 行心跳）。
        if path in ("/api/progress", "/api/state", "/api/heartbeat",
                    "/favicon.ico"):
            return
        sys.stderr.write("[HTTP] %s %s\n" % (self.command, path))

    # ---------------------------- GET ---------------------------- #
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/":
                self._serve_index()
                return
            if path.startswith("/ui/"):
                self._serve_static(unquote(path[len("/ui/"):]))
                return
            if path == "/api/heartbeat":
                # 页面存活信号：窗口开着才有的请求，刷新看门狗计时
                _touch_heartbeat()
                self._send_json({"ok": True})
                return
            if path == "/api/check-update":
                _touch_heartbeat()
                self._send_json(self._api_check_update())
                return
            if path == "/api/merged-status":
                _touch_heartbeat()
                qs = parse_qs(parsed.query)
                self._send_json(self._api_merged_status(
                    (qs.get("outdir") or [""])[0]))
                return
            if path == "/api/settings":
                _touch_heartbeat()
                self._send_json({
                    "ok": True,
                    "settings": _load_settings(),
                    "settings_file": str(SETTINGS_FILE),
                })
                return
            if path == "/api/state":
                _touch_heartbeat()
                self._send_json(self._api_state())
                return
            if path == "/api/progress":
                _touch_heartbeat()
                qs = parse_qs(parsed.query)
                try:
                    since = int((qs.get("since") or ["0"])[0])
                except (TypeError, ValueError):
                    since = 0
                self._send_json(self._api_progress(since))
                return
            if path == "/favicon.ico":
                self._send_bytes(b"", "image/x-icon", 204)
                return
            # 未知 /api/* 一律回 JSON，与 do_POST 保持同一形态：
            # 前端对接口响应的处理是统一的（res.json()），若这里回纯文本，
            # 未来新增端点写错路径时前端会抛 SyntaxError 而不是拿到可读 error。
            if path.startswith("/api/"):
                self._send_json({"ok": False, "error": "未知接口：%s" % path}, 404)
                return
            self._send_text("404 Not Found", 404)
        except Exception as exc:  # 兜底：把组件 + 环境状态一并落盘，再回 500
            _log_error("HTTP-GET:%s" % path, "请求处理异常", exc,
                       request=parsed.query or None)
            self._send_json({"ok": False, "error": "服务器内部错误：%s" % exc}, 500)

    def _serve_index(self) -> None:
        if not INDEX_FILE.is_file():
            self._send_text("404 Not Found: ui/index.html 缺失", 404)
            return
        try:
            body = INDEX_FILE.read_bytes()
        except OSError:
            self._send_text("500 Internal Server Error", 500)
            return
        self._send_bytes(body, "text/html; charset=utf-8")

    def _serve_static(self, rel: str) -> None:
        ui_root = UI_DIR.resolve()
        if not rel:
            self._send_text("404 Not Found", 404)
            return
        try:
            target = (ui_root / rel).resolve()
            target.relative_to(ui_root)
        except (ValueError, OSError):
            self._send_text("403 Forbidden", 403)
            return
        if not target.is_file():
            self._send_text("404 Not Found", 404)
            return
        ctype = MIME.get(target.suffix.lower(), "application/octet-stream")
        try:
            body = target.read_bytes()
        except OSError:
            self._send_text("404 Not Found", 404)
            return
        self._send_bytes(body, ctype)

    def _api_state(self) -> dict:
        _reap_dead_job()
        cap = capabilities()
        with _JOB_LOCK:
            job = _JOB
        running = bool(job and job.running)
        converter = (job.converter if job and job.converter else _CONVERTER)
        return {
            # app 标记：让「占用端口的是不是精核自己」可以被外部判定
            # （单实例保护据此区分「已有实例」与「端口被别的程序占用」）
            "app": "jinghe",
            "version": cap["version"],
            "python": platform.python_version(),
            "platform": platform.platform(),
            "running": running,
            "input": job.input if job else _LAST_INPUT,
            "inputs": job.inputs if job else _LAST_INPUTS,
            "outdir": job.outdir if job else _LAST_OUTDIR,
            "converter": converter,
            "cwd": os.getcwd(),
            "log_file": str(LOG_FILE),
        }

    def _api_progress(self, since: int) -> dict:
        _reap_dead_job()
        with _JOB_LOCK:
            job = _JOB
        if job is None:
            return {"events": [], "next": since, "running": False,
                    "summary": None, "state": "idle", "error": None,
                    "total": 0, "current": 0, "current_name": ""}
        with job.lock:
            events = [dict(ev) for ev in job.events if ev["i"] > since]
            next_i = events[-1]["i"] if events else since
            payload = {
                "events": events,
                "next": next_i,
                "running": job.running,
                "summary": job.summary,
                "state": job.state,
                "error": job.error,
                "total": job.total,
                "current": job.current,
                "current_name": job.current_name,
            }
        return payload

    # ---------------------------- POST ---------------------------- #
    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            data = self._read_json()
        except ValueError as exc:
            self._send_json({"ok": False, "error": str(exc)}, 400)
            return

        try:
            if path == "/api/pick-files":
                initial = str(data.get("initial") or "")
                paths, pick_err = pick_files_ex(initial)
                self._send_json({"paths": paths, "error": pick_err})
            elif path == "/api/pick-folder":
                initial = str(data.get("initial") or "")
                self._send_json({"path": pick_folder(initial)})
            elif path == "/api/dry-run":
                self._send_json(self._api_dry_run(_norm_inputs(data)))
            elif path == "/api/run":
                self._send_json(self._api_run(
                    _norm_inputs(data),
                    str(data.get("outdir") or "").strip(),
                ))
            elif path == "/api/cancel":
                self._send_json(self._api_cancel())
            elif path == "/api/settings":
                # 保存设置：非法值由 _validate_settings 收敛，不接受前端直接落盘
                merged = dict(_load_settings())
                incoming = data.get("settings")
                if isinstance(incoming, dict):
                    merged.update(incoming)
                saved = _save_settings(merged)
                _append_log("[INFO] 设置已保存：%s" % json.dumps(saved, ensure_ascii=False))
                self._send_json({"ok": True, "settings": saved,
                                 "settings_file": str(SETTINGS_FILE)})
            elif path == "/api/open":
                self._send_json(self._api_open(str(data.get("path") or "").strip()))
            elif path == "/api/open-merged":
                self._send_json(self._api_open_merged(
                    str(data.get("outdir") or "").strip()))
            elif path == "/api/update":
                self._send_json(self._api_update())
            elif path == "/api/open-latest":
                self._send_json(self._api_open_latest())
            elif path == "/api/pick-log-dest":
                self._send_json(self._api_pick_log_dest())
            elif path == "/api/export-log":
                self._send_json(self._api_export_log(
                    str(data.get("path") or "").strip(),
                    bool(data.get("errors_only")),
                ))
            elif path == "/api/summarize":
                self._send_json(
                    self._api_summarize(str(data.get("outdir") or "").strip()))
            elif path == "/api/transcribe":
                self._send_json(self._api_transcribe(_norm_inputs(data)))
            else:
                self._send_json({"ok": False, "error": "未知接口：%s" % path}, 404)
        except Exception as exc:  # 兜底，避免 500 页面，并落盘组件与环境状态
            req = ""
            try:
                req = json.dumps(data, ensure_ascii=False)[:500]
            except Exception:
                req = ""
            _log_error("HTTP-POST:%s" % path, "请求处理异常", exc,
                       request=req or None)
            self._send_json({"ok": False, "error": "服务器内部错误：%s" % exc}, 500)

    def _api_dry_run(self, inputs: list[str]) -> dict:
        if not inputs:
            return {"ok": False, "error": "请先填写输入路径"}
        missing = [p for p in inputs if not os.path.exists(p)]
        if missing:
            return {"ok": False, "error": "输入路径不存在：%s" % _missing_text(missing)}
        return _dry_run(inputs)

    def _api_run(self, inputs: list[str], outdir: str) -> dict:
        global _JOB, _LAST_INPUT, _LAST_INPUTS, _LAST_OUTDIR
        if not inputs:
            return {"ok": False, "error": "请先填写输入路径"}
        if not outdir:
            return {"ok": False, "error": "请先填写输出目录"}
        missing = [p for p in inputs if not os.path.exists(p)]
        if missing:
            return {"ok": False, "error": "输入路径不存在：%s" % _missing_text(missing)}
        out_abs, err = _prepare_outdir(outdir)
        if err:
            return {"ok": False, "error": err}

        # 与 /api/state、/api/progress 保持一致：读 job 状态前先复位僵尸任务，
        # 避免残留 running=true 把本次「开始提取」误拒成「已有任务在运行」。
        # 必须在 _JOB_LOCK 之外调用（_reap_dead_job 内部会自行获取该锁）。
        _reap_dead_job()
        with _JOB_LOCK:
            if _JOB is not None and _JOB.running:
                return {"ok": False, "error": "已有任务在运行"}
            job = Job(inputs, out_abs)
            _JOB = job
            _LAST_INPUTS = list(inputs)
            _LAST_INPUT = inputs[0] if len(inputs) == 1 else ""
            _LAST_OUTDIR = out_abs
            # 线程句柄与 _JOB 在同一临界区内设置并启动：_reap_dead_job() 也持
            # _JOB_LOCK，因此不会看到「_JOB 已赋值但线程尚未 start」而误判僵尸。
            t = threading.Thread(target=_run_job, args=(job,), daemon=True)
            job.thread = t
            t.start()
        return {"ok": True}

    def _api_cancel(self) -> dict:
        with _JOB_LOCK:
            job = _JOB
        if job is None or not job.running:
            return {"ok": False, "error": "当前无运行中任务"}
        job.cancelled = True
        proc = job.proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
        return {"ok": True}

    def _api_open(self, path: str) -> dict:
        if not path:
            return {"ok": False, "error": "请提供要打开的路径"}
        if not os.path.exists(path):
            return {"ok": False, "error": "路径不存在：%s" % path}
        try:
            if hasattr(os, "startfile"):
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                webbrowser.open(Path(path).as_uri())
        except Exception as exc:
            return {"ok": False, "error": "打开失败：%s" % exc}
        return {"ok": True}

    def _api_merged_status(self, outdir: str) -> dict:
        """探测输出目录里是否已有 MERGED.md（重启后恢复「打开合并文档」入口）。"""
        merged = _merged_path(outdir)
        if merged is None:
            return {"ok": True, "exists": False, "outdir": outdir, "path": None}
        return {
            "ok": True,
            "exists": merged.is_file(),
            "outdir": str(merged.parent),
            "path": str(merged),
        }

    def _api_open_merged(self, outdir: str) -> dict:
        """打开本次提取的合并文档 MERGED.md，并把结果显式回给前端。

        与通用 /api/open 的区别：只认「输出目录 + 固定文件名」；
        用 _open_document 固定走系统记事本（避免 .md 的单实例关联
        让「打开」变成静默切换窗口）；打开结果 ok / path / via 全部回传，
        前端据此显示成功路径或明确错误，绝不再静默吞掉。
        """
        merged = _merged_path(outdir)
        if merged is None:
            return {"ok": False, "error": "请先完成一次提取，再打开合并文档"}
        if not merged.is_file():
            return {"ok": False,
                    "error": "未找到合并文档：%s（请先完成提取）" % merged,
                    "path": str(merged)}
        try:
            via = _open_document(merged)
        except Exception as exc:
            _log_error("API:/api/open-merged", "打开合并文档失败", exc,
                       request="path=%s" % merged)
            return {"ok": False, "error": "打开失败：%s" % exc,
                    "path": str(merged)}
        _append_log("[INFO] 已打开合并文档（%s）：%s" % (via, merged))
        return {"ok": True, "path": str(merged), "via": via}

    # ---------------------------- 关于页：版本更新 / 运行日志 ---------------------------- #
    def _api_check_update(self) -> dict:
        """查询 GitHub 最新 release。断网/超时诚实降级，下载链接始终指向仓库最新版。"""
        current = capabilities().get("version", "unknown")
        out = {
            "ok": True,
            "current": current,
            "latest": None,
            "latest_url": RELEASES_LATEST_URL,
            "repo_url": REPO_URL,
            "up_to_date": None,
            "offline": False,
            "error": None,
        }
        try:
            req = urllib.request.Request(
                RELEASES_API_URL,
                headers={"User-Agent": "jinghe-desktop",
                         "Accept": "application/vnd.github+json"},
            )
            with urllib.request.urlopen(req, timeout=UPDATE_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
            tag = str(data.get("tag_name") or "").strip()
            html_url = str(data.get("html_url") or "").strip()
            if tag:
                out["latest"] = tag
                out["up_to_date"] = _version_tuple(current) >= _version_tuple(tag.lstrip("vV"))
                if html_url.startswith(REPO_URL):
                    out["latest_url"] = html_url
        except Exception as exc:
            out["offline"] = True
            out["error"] = "检查更新请求失败：%s" % exc
            _append_log("[WARN] 检查更新失败（离线降级）：%s" % exc)
        return out

    def _api_update(self) -> dict:
        """v0.3.9 一键检查更新：只做「查询 GitHub 仓库最新版本」这一件事。

        关于页按需求清除了说明文字、仓库链接显示与离线长文案：
          · 已是最新 → 简短提示，不弹浏览器；
          · 发现新版本 → 自动用系统浏览器打开下载页；
          · 离线 → 诚实降级，不弹浏览器，也不再输出离线长文案，
            由前端隐藏状态条（按钮从「检查中…」恢复即是已完成反馈）。
        打开的 URL 仍收敛在仓库 releases 之下，不接受任意跳转。
        """
        info = self._api_check_update()
        out = dict(info)
        url = info.get("latest_url") or RELEASES_LATEST_URL
        if not (isinstance(url, str) and url.startswith(REPO_URL + "/releases")):
            url = RELEASES_LATEST_URL
        out["url"] = url
        out["opened"] = False

        # 只有「确实发现新版本」才自动打开下载页；离线按需求不再弹浏览器
        if info.get("up_to_date") is False:
            try:
                # webbrowser.open 返回 False 表示系统没有可用浏览器，不能谎报已打开
                result = webbrowser.open(url)
                out["opened"] = bool(result)
                if result:
                    _append_log("[INFO] 检查更新已打开最新版本页面：%s" % url)
                else:
                    out["error"] = ((out.get("error") or "") +
                                    "；系统未找到可用浏览器")
            except Exception as exc:
                _log_error("API:/api/update", "打开最新版本页面失败", exc,
                           request="url=%s" % url)
                out["error"] = ((out.get("error") or "") +
                                "；打开下载页失败：%s" % exc)

        if info.get("up_to_date") is True:
            out["status"] = "up_to_date"
            out["message"] = "已是最新版本 %s" % (
                info.get("latest") or info.get("current"))
        elif info.get("offline") or not info.get("latest"):
            out["status"] = "offline"
            # v0.3.9：按需求清除离线长文案，只保留极短的排查说明（UI 不展示）
            out["message"] = "检查更新失败，请检查网络后重试"
        else:
            out["status"] = "new_version"
            out["message"] = ("发现新版本 %s，" % info["latest"] +
                              ("已打开下载页" if out["opened"]
                               else "但打开下载页失败"))
        return out

    def _api_open_latest(self) -> dict:
        """用系统默认浏览器打开仓库「最新版本」下载页（URL 为固定常量，不接受外部参数）。"""
        try:
            webbrowser.open(RELEASES_LATEST_URL)
        except Exception as exc:
            _log_error("API:/api/open-latest", "打开下载页失败", exc)
            return {"ok": False, "error": "打开浏览器失败：%s" % exc,
                    "url": RELEASES_LATEST_URL}
        _append_log("[INFO] 已打开仓库最新版本下载页：%s" % RELEASES_LATEST_URL)
        return {"ok": True, "url": RELEASES_LATEST_URL}

    def _api_pick_log_dest(self) -> dict:
        """弹出「另存为」对话框，仅返回用户选定的路径，不写文件。"""
        if os.name != "nt":
            return {"ok": False, "error": "当前系统不支持原生另存为对话框，请直接填写目标路径"}
        try:
            chosen = _pick_save_file_win32(
                "jinghe-log-%s.log" % time.strftime("%Y%m%d-%H%M%S"))
        except Exception as exc:
            _log_error("API:/api/pick-log-dest", "另存为对话框失败", exc)
            return {"ok": False, "error": "另存为对话框失败：%s" % exc}
        if not chosen:
            return {"ok": False, "cancelled": True}
        return {"ok": True, "path": chosen}

    def _api_export_log(self, target: str, errors_only: bool) -> dict:
        """把运行日志生成为指定文件；可选只保留报错/警告行，便于系统排查与提交反馈。"""
        if not target:
            picked = self._api_pick_log_dest()
            if not picked.get("ok"):
                return picked
            target = str(picked["path"])
        try:
            dest = Path(target).expanduser()
            if not dest.is_absolute():
                dest = (Path.cwd() / dest).resolve()
            else:
                dest = dest.resolve()
        except (OSError, ValueError) as exc:
            return {"ok": False, "error": "目标路径无效：%s" % exc}
        protected = {LOG_FILE.resolve(),
                     LOG_FILE.with_name(LOG_FILE.name + ".1").resolve()}
        if dest in protected or dest.is_dir():
            return {"ok": False, "error": "不能覆盖原始日志文件或目录，请另选文件名"}

        snap = _env_snapshot()
        header = [
            "精核 · 运行日志导出",
            "导出时间: %s" % time.strftime("%Y-%m-%d %H:%M:%S"),
            "软件版本: %s" % snap.get("version"),
            "运行平台: %s" % snap.get("platform"),
            "Python  : %s" % snap.get("python"),
            "工作目录: %s" % snap.get("cwd"),
            "可执行文件: %s" % snap.get("executable"),
            "进程 PID: %s" % snap.get("pid"),
            "任务上下文: %s" % _job_context(),
            "导出模式: %s" % ("仅报错 / 警告行" if errors_only else "完整日志"),
            "原始日志: %s" % LOG_FILE,
            "=" * 60,
        ]
        raw = ""
        for src in (LOG_FILE.with_name(LOG_FILE.name + ".1"), LOG_FILE):
            try:
                if src.is_file():
                    raw += src.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass
        lines = raw.splitlines()
        if errors_only:
            marks = ("[ERROR]", "[WARN]", "[FATAL]", "Traceback", "组件=", "异常",
                     "环境状态:", "任务上下文=", "请求上下文=")
            keep: list[str] = []
            in_block = False
            for ln in lines:
                if any(m in ln for m in marks):
                    keep.append(ln)
                    in_block = True
                elif in_block and ln.startswith((" ", "\t")):
                    keep.append(ln)  # 环境状态明细 / 栈缩进一并保留
                else:
                    in_block = False
            lines = keep or ["（本次日志中未找到报错 / 警告记录）"]
        if not lines:
            lines = ["（日志暂无内容）"]
        text = "\n".join(header + lines) + "\n"
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".tmp")
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(dest)
        except OSError as exc:
            _log_error("API:/api/export-log", "写日志导出文件失败", exc,
                       request=target)
            return {"ok": False, "error": "写入文件失败：%s" % exc}
        _append_log("[INFO] 运行日志已生成到指定文件：%s（%d 行，仅报错=%s）"
                    % (dest, len(lines), errors_only))
        return {"ok": True, "path": str(dest),
                "bytes": len(text.encode("utf-8")),
                "lines": len(lines), "errors_only": bool(errors_only)}

    # ---------------------------- 阶段 2 / 3 后处理 ---------------------------- #
    def _api_summarize(self, outdir: str) -> dict:
        if not outdir:
            return {"ok": False, "error": "请先完成提取并指定输出目录"}
        out_abs = Path(outdir)
        if not out_abs.is_dir():
            return {"ok": False, "error": "输出目录不存在：%s" % outdir}
        merged = out_abs / "MERGED.md"
        if not merged.is_file():
            return {"ok": False, "error": "未找到 MERGED.md，请先完成提取"}
        try:
            text = merged.read_text(encoding="utf-8")
        except OSError as exc:
            return {"ok": False, "error": "读取 MERGED.md 失败：%s" % exc}
        summary = _extractive_summary(text)
        header = ("<!-- 精核 · 抽取式摘要（阶段 2 v1） -->\n"
                  "<!-- 生成时间 %s -->\n\n"
                  % time.strftime("%Y-%m-%d %H:%M:%S"))
        prov = out_abs / "provenance.json"
        if prov.is_file():
            try:
                data = json.loads(prov.read_text(encoding="utf-8"))
                entries = data.get("entries") or []
                if isinstance(entries, list):
                    success = sum(1 for e in entries
                                  if isinstance(e, dict) and e.get("status") == "成功")
                    total = len(entries)
                    header += ("> 来源：%d 个源文件，成功抽出 %d 份；本摘要为抽取式（取各节首段），"
                               "深度语义提炼需接入 LLM。\n\n" % (total, success))
            except Exception:
                pass
        out_path = out_abs / "SUMMARY.md"
        try:
            out_path.write_text(header + summary, encoding="utf-8")
        except OSError as exc:
            return {"ok": False, "error": "写入 SUMMARY.md 失败：%s" % exc}
        return {"ok": True, "path": str(out_path), "chars": len(header) + len(summary)}

    def _api_transcribe(self, inputs: list[str]) -> dict:
        if not inputs:
            return {"ok": False, "error": "请先选择音视频文件（阶段 3 预留格式）"}
        found = [p for p in inputs
                 if Path(p).suffix.lower() in _STAGE3_AUDIO_EXT and os.path.exists(p)]
        if not found:
            return {"ok": False, "error": "未找到可转写的音视频文件（支持 mp3/wav/mp4/mov 等）"}
        # 阶段 3 音视频转写：当前零依赖运行环境未内置专用转写器（刻意不引入重依赖），
        # 此处只诚实标记、绝不产出伪转写；接入转写后端后在此调用。
        return {"ok": False, "error":
                "阶段 3 音视频转写需专用转写器，当前零依赖运行环境未启用；"
                "已识别 %d 个音视频文件，请在启用转写后端后重试。" % len(found)}


# --------------------------------------------------------------------------- #
# 启动器
# --------------------------------------------------------------------------- #
def find_edge() -> str | None:
    candidates = [
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Edge"
        / "Application" / "msedge.exe",
    ]
    for path in candidates:
        try:
            if path.is_file():
                return str(path)
        except OSError:
            continue
    return shutil.which("msedge") or shutil.which("msedge.exe")


def _window_position(width: int = 1060, height: int = 720) -> str | None:
    """按主屏分辨率计算让窗口居中的 --window-position 参数。

    用未开 DPI 感知的 GetSystemMetrics（虚拟化坐标），与 Chromium 对
    --window-position 的解读在主屏上基本一致；偏上 1/3 更符合桌面窗口习惯。
    任何异常都返回 None——居中只是锦上添花，绝不能影响启动。
    """
    try:
        user32 = ctypes.windll.user32
        sw = user32.GetSystemMetrics(0)   # SM_CXSCREEN
        sh = user32.GetSystemMetrics(1)   # SM_CYSCREEN
        if sw <= 0 or sh <= 0:
            return None
        x = max(0, (sw - width) // 2)
        y = max(0, (sh - height) // 3)
        return "--window-position=%d,%d" % (x, y)
    except Exception:
        return None


def open_window(url: str) -> None:
    edge = find_edge()
    if edge:
        try:
            cmd = [edge, "--app=%s" % url, "--window-size=1060,720"]
            pos = _window_position()
            if pos:
                cmd.append(pos)
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return
        except Exception:
            pass
    # 无 Edge 或 Edge 启动失败：退回系统默认浏览器（如本机 Chrome）
    try:
        if webbrowser.open(url):
            return
    except Exception:
        pass
    # 所有自动打开方式都失败：明确告知用户服务地址，避免「双击无反应」
    try:
        import ctypes as _ct
        _ct.windll.user32.MessageBoxW(
            None,
            "精核已在后台启动，但无法自动打开窗口。\n\n请手动在浏览器打开：\n%s" % url,
            "精核",
            0x00000040,
        )
    except Exception:
        pass


class _Server(ThreadingHTTPServer):
    """把「客户端正常断开」与「真正的异常」分开处理。

    Edge 关闭窗口时会把预连接（浏览器 socket 预热）直接断开，socketserver
    默认会为每个这种 ConnectionResetError 打印一整页栈回溯——桌面端既刷屏，
    又把日志冲成噪音。连接类异常静默丢弃，其余异常走统一落盘
    （组件 + 环境状态 + 任务上下文），符合「报错要能定位」的要求。
    """

    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address) -> None:  # noqa: D102
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, BrokenPipeError,
                            ConnectionAbortedError, TimeoutError)):
            return
        _log_error("HTTP-连接", "请求处理线程异常",
                   exc if isinstance(exc, BaseException) else None,
                   request="%s:%s" % (client_address[0], client_address[1]))


def _port_in_use(host: str, port: int) -> bool:
    """端口是否已被占用。

    用 connect 探测而不是「bind 抛 10048」：ThreadingHTTPServer 开了
    SO_REUSEADDR，Windows 下重复 bind 同一端口不报错，但会让两个实例抢同一
    端口，其中一个在会话结束后变死端口，前端就会 Failed to fetch。
    """
    import socket as _sock
    probe = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
    probe.settimeout(0.5)
    try:
        probe.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def _probe_running_instance(port: int) -> bool | None:
    """判断占用本机端口的是不是「精核自己」。

    True  = 确认是精核实例；False = 确认不是（端口被别的程序占用）；
    None  = 无法判定（对方不响应 / 返回不是本服务的 JSON），
            按「可能是自己」处理，保持旧行为不回归。
    """
    for _ in range(2):
        try:
            with urllib.request.urlopen(
                    "http://%s:%d/api/state" % (HOST, port), timeout=1.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data.get("app") == "jinghe"
        except Exception:
            time.sleep(0.3)
    return None


def _show_error_box(title: str, text: str) -> None:
    """桌面端弹窗告知用户。

    仅冻结态（windowed，无控制台）且非 --cli 时弹窗——--cli 会被父进程当
    子进程调用，弹窗会卡住自动化。源码模式由调用方打印到终端。
    """
    try:
        if getattr(sys, "frozen", False) and "--cli" not in sys.argv:
            ctypes.windll.user32.MessageBoxW(None, text, title, 0x00000010)
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    # 必须在任何 print 之前：管道默认 cp936 会把中文写成 GBK 乱码
    _reconfigure_streams()
    args_list = list(sys.argv[1:] if argv is None else argv)

    # 冻结后 exe 自我重入：Jinghe.exe --cli -i ... -o ... 直接跑提取，不启动界面
    if "--cli" in args_list:
        args_list.remove("--cli")
        return int(extract.main(args_list))

    parser = argparse.ArgumentParser(description="精核 · 本地图形界面（纯标准库）")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help="监听端口，默认 54321（固定，便于记忆与单实例保护）")
    parser.add_argument("--no-browser", action="store_true",
                        help="只启动服务，不打开窗口（测试用）")
    args = parser.parse_args(args_list)

    _prepare_runtime()
    _log_startup_banner()

    # 单实例保护（仅固定端口）：先 connect 本机端口，若已有人在 listen 则退出。
    # 不能用「bind 抛 10048」判断——ThreadingHTTPServer 开了 SO_REUSEADDR，
    # Windows 下重复 bind 同一端口不报错，但会让两个实例抢同一端口，其中一个
    # 在工具会话结束后变死端口，前端就会 Failed to fetch。connect 能真实探到
    # 是否有实例在 listen，比 bind 异常可靠。
    if args.port != 0 and _port_in_use(HOST, args.port):
        # 端口有人占：必须区分「精核自己已在运行」与「被别的程序占用」。
        # 误判成前者会弹出陌生页面，用户只会觉得软件坏了。
        who = _probe_running_instance(args.port)
        if who is False:
            msg = ("端口 %d 已被其他程序占用（不是精核）。\n\n"
                   "请关闭占用该端口的程序后重新启动精核。" % args.port)
            _append_log("[WARN] 端口 %d 被其他程序占用（非精核），拒绝启动" % args.port)
            print("[WARN] 端口 %d 被其他程序占用（非精核），请关闭占用程序后重试。"
                  % args.port, flush=True)
            _show_error_box("精核无法启动", msg)
            return 1
        _append_log("[INFO] 端口 %d 已有实例在运行" % args.port)
        if args.no_browser:
            print("[INFO] 端口 %d 已有实例在运行（请勿重复启动）" % args.port, flush=True)
        else:
            # 界面实例已在运行：再次唤起浏览器窗口，避免「双击无反应」
            open_window("http://127.0.0.1:%d/" % args.port)
            _append_log("[INFO] 已尝试唤起已有实例的窗口")
        return 0

    _sweep_run_dirs()  # 清掉上次异常退出遗留的本 pid 编码副本目录
    try:
        _n = _sweep_orphan_dirs()  # 再清已死进程遗留的孤儿目录（硬杀场景）
        if _n:
            _append_log("启动清理：移除 %d 个已退出进程遗留的编码副本目录" % _n)
    except Exception as exc:
        _append_log("启动清理孤儿目录失败（不影响使用）：%r" % (exc,))
    capabilities()  # 预热：探测 extract.py 的 --version / --progress

    httpd = _Server((HOST, args.port), Handler)
    httpd.daemon_threads = True
    port = httpd.server_address[1]
    url = "http://127.0.0.1:%d/" % port
    print("[INFO] 精核 UI: %s" % url, flush=True)
    if not args.no_browser:
        open_window(url)
        # 关窗即退：窗口实例才有看门狗；--no-browser（测试/手动调试）永不自动退出
        _start_window_watchdog(httpd)
    try:
        httpd.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        print("\n[INFO] 收到中断，正在退出", flush=True)
    finally:
        httpd.server_close()
    return 0


def _fatal(exc: BaseException) -> None:
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    _append_log("启动失败:\n" + tb)
    try:
        # --cli 模式绝不弹窗（会被父进程当子进程调用，弹窗会卡住自动化）
        if getattr(sys, "frozen", False) and "--cli" not in sys.argv:
            import ctypes as _ct
            _ct.windll.user32.MessageBoxW(
                None,
                "精核启动失败：%s\n\n日志：%s" % (exc, LOG_FILE),
                "精核",
                0x00000010,
            )
    except Exception:
        pass


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as _exc:  # 启动阶段任何异常都要留痕
        _fatal(_exc)
        sys.exit(1)
