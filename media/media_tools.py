#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精核 · 本机可插拔工具的健康探测（S1 · 阶段 2/3 能力框架地基）。

用户已选定「本机可插拔工具」策略：ffmpeg / whisper / yt-dlp 由用户在**本机**
提供，软件不下载、不打包、不自动安装、不内置任何凭据（契约 §3）。

本模块只负责**诚实回答「某工具现在能不能用」**：

* 找不到可执行文件 → ``available=False`` + 可读原因，不执行任何命令；
* 找到但探测命令失败 / 超时 → ``available=False`` + 原因，**绝不因为
  「文件存在」就报可用**；
* 成功 → ``available=True`` + 探测到的版本字符串（解析不出则留空）。

任何路径都**不产出伪转写、不写空 md、不假装成功**。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
from typing import Callable

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# 每台工具一次轻量探测；超时刻意压短，避免启动界面被外部 CLI 拖住。
DEFAULT_TIMEOUT = 2.0
# 重依赖 CLI 的单独超时：whisper 每次启动要 import torch + numba（实测 6–8s），
# 若沿用 2s 会把「已装好」误判为「未启用」。这里只放宽 whisper 的探测窗口，
# 仍真跑 `--help` 验证可用（不是放宽成「文件存在就算可用」），诚实原则不变。
PROBE_TIMEOUTS: dict[str, float] = {"whisper": 15.0, "yt-dlp": 10.0}

# (工具名, 探测参数, 版本正则或 None)
TOOL_SPECS: tuple[tuple[str, list[str], str | None], ...] = (
    ("ffmpeg", ["-version"], r"ffmpeg version\s+(\S+)"),
    ("whisper", ["--help"], None),
    ("yt-dlp", ["--version"], r"^\s*(\d[^\s]*)"),
)

_CACHE: dict[str, dict] | None = None
# 刷新窗口：开启期间，同一轮内的重复 refresh=True 复用同一份结果
_REFRESH_OPEN = False
_LOCK = threading.Lock()


# --------------------------------------------------------------------------- #
# 组件数据目录（v1.4.0 收口）
# --------------------------------------------------------------------------- #
def component_dir() -> str:
    """软件管理的组件数据根目录（``%LOCALAPPDATA%\\Jinghe\\components``）。

    与 :mod:`components` 模块的 ``COMPONENT_DIR`` 同源，但**在此独立实现**
    （不反向 import）——``media_tools`` 是底层探测模块，被多个模块依赖；
    让它 import ``components`` 会形成循环依赖。

    两处都用同一套规则（``LOCALAPPDATA`` 优先，回落家目录），
    因此取值必然一致。
    """
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Jinghe", "components")


def whisper_model_dir() -> str:
    """whisper 模型权重的存放目录（``components\\models``）。

    **为什么要指定（v1.4.0 收口）**：whisper CLI 默认把权重下到
    ``~/.cache/whisper/`` —— 那是**用户家目录**，不受软件管理、卸载清不掉，
    且与其它组件分散在两处。指定 ``--model_dir`` 后，权重统一收口到
    软件自己的目录，卸载时可一并清理。

    对应 whisper CLI 参数（``whisper/transcribe.py``）::

        parser.add_argument("--model_dir", type=str, default=None,
                            help="the path to save model files; uses ~/.cache/whisper by default")
        model = load_model(model_name, device=device, download_root=model_dir)
    """
    return os.path.join(component_dir(), "models")


# --------------------------------------------------------------------------- #
# 轻量存在性检查（快路径）
# --------------------------------------------------------------------------- #
# 为什么需要（用户 2026-11-19 实测踩坑）：
# whisper 的真实探测命令是 ``whisper --help``，它会连带 ``import torch``
# （site-packages 里 509 MB），冷启动实测 4–7 秒；机器繁忙时逼近 15 秒
# 超时阈值 → **被静默误判为「未安装」**（界面与 exe 真丢失完全无法区分）。
#
# 这里给 whisper 加一条**快路径**：只做文件系统检查（dist-info + 包目录 +
# entry point 三重校验），实测 0.003 秒。证据强度远高于「文件存在」，
# 因此不违背本模块「绝不因文件存在就报可用」的诚实原则。
# 真实命令探测（深度验证）依然保留：安装流程末尾与真正转写前都会真跑一次。
#
# **TOOL_SPECS 三元组结构一字不动**（S1 契约锁死），轻量检查是独立层。

def _dist_info_version(dist_info: Path) -> str:
    """从 .dist-info/METADATA 读 Version（纯文件读，不 import 目标包）。"""
    meta = dist_info / "METADATA"
    try:
        if meta.is_file():
            for line in meta.read_text(encoding="utf-8",
                                       errors="replace").splitlines()[:20]:
                if line.startswith("Version:"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return ""


def _site_packages_roots(exe_path: str) -> list:
    """由 exe 路径反推可能的 site-packages 目录。

    exe 位于某 Python 的 ``Scripts`` 下，其父目录即 Python 根目录。
    两者可能经由 Windows junction 互为别名（``versions\\3.13.12`` ↔
    ``vendor\\python``），故两条路径都试。
    """
    from pathlib import Path
    roots = []
    try:
        scripts = Path(exe_path).resolve().parent
        for base in (scripts.parent, Path(os.path.abspath(scripts.parent))):
            for sp in (base / "Lib" / "site-packages",
                       base / "lib" / "site-packages"):
                key = os.path.normcase(str(sp))
                if key not in {os.path.normcase(str(r)) for r in roots}:
                    roots.append(sp)
    except (OSError, ValueError):
        pass
    return roots


def _light_check_package(exe_path: str, dist_glob: str, pkg_dir: str,
                        script_name: str) -> str | None:
    """轻量确认某 pip 包已安装；返回版本号，未确认则 None（走深度验证）。

    三重校验（缺一不可）：
      1. ``<dist_glob>`` 存在 → pip 装过这个发行版；
      2. 包目录存在（导入包名，如 whisper / yt_dlp）；
      3. ``entry_points.txt`` 声明了对应的 console script。

    证据强度远高于「文件存在」，因此不违背本模块「绝不因文件存在就报可用」
    的诚实原则。
    """
    from pathlib import Path
    for sp in _site_packages_roots(exe_path):
        try:
            if not sp.is_dir():
                continue
            dists = sorted(sp.glob(dist_glob))
            if not dists:
                continue
            if not (sp / pkg_dir).is_dir():
                continue
            eps = dists[-1] / "entry_points.txt"
            ok_eps = False
            if eps.is_file():
                try:
                    txt = eps.read_text(encoding="utf-8", errors="replace")
                    ok_eps = bool(re.search(
                        r"^\s*%s\s*=" % re.escape(script_name), txt, re.M))
                except OSError:
                    ok_eps = False
            if not ok_eps:
                continue
            return _dist_info_version(dists[-1])
        except OSError:
            continue
    return None


def _light_check_whisper(exe_path: str) -> str | None:
    """轻量确认 whisper 包已安装（openai-whisper → 导入包名 ``whisper``）。"""
    return _light_check_package(exe_path, "openai_whisper-*.dist-info",
                                "whisper", "whisper")


def _light_check_ytdlp(exe_path: str) -> str | None:
    """轻量确认 yt-dlp 包已安装（导入包名 ``yt_dlp``）。

    yt-dlp 的 ``--version`` 要启动 Python 解释器（约 1.2 秒），而默认探测
    超时只有 2.0 秒，余量很小；轻量路径把它降到毫秒级。
    """
    return _light_check_package(exe_path, "yt_dlp-*.dist-info",
                                "yt_dlp", "yt-dlp")


# 工具名 → 轻量检查函数（返回版本号 = 已确认安装；None = 需走深度验证）。
# ffmpeg 不在此列：它是独立二进制（无 Python 包），本就是毫秒级探测。
_LIGHT_CHECKS: dict[str, Callable[[str], str | None]] = {
    "whisper": _light_check_whisper,
    "yt-dlp": _light_check_ytdlp,
}


class ToolAdapter:
    """统一接口：``probe() -> {available, path, version, reason}``。

    ``run()`` 留给 S3/S4/S5 的真实调用实现，S1 只落接口与健康探测，
    绝不提前产出内容。``which`` / ``runner`` 可注入，便于契约测试。
    """

    def __init__(self, name: str, argv: list[str],
                 version_re: str | None = None,
                 timeout: float = DEFAULT_TIMEOUT,
                 which: Callable[[str], str | None] | None = None,
                 runner: Callable | None = None,
                 deep: bool = False) -> None:
        self.name = name
        self.argv = list(argv)
        self.version_re = re.compile(version_re) if version_re else None
        self.timeout = timeout
        self._which = which or shutil.which
        self._runner = runner
        # deep=True 时跳过轻量快路径，强制真跑探测命令（深度验证用）。
        self.deep = deep

    def probe(self) -> dict:
        # state: ok / missing / timeout / error
        # 关键：**timeout（探测超时）与 missing（真没装）必须区分**——
        # 用户 2026-11-19 实测被「超时被静默判成未安装」坑过。
        base = {"available": False, "path": "", "version": "", "reason": "",
                "state": "error"}
        try:
            found = self._which(self.name)
        except Exception as exc:
            base["reason"] = "工具查找失败：%s" % exc
            base["state"] = "error"
            return base
        if not found:
            base["reason"] = "本机未找到 %s，请安装后重试" % self.name
            base["state"] = "missing"
            return base
        base["path"] = str(found)
        # 快路径：轻量存在性检查（仅限声明了检查函数的工具，如 whisper）。
        # 证据强度是「包确已安装」，远高于「文件存在」；真跑命令的深度验证
        # 仍保留在安装流程末尾与真正调用时执行。
        if not self.deep:
            light = _LIGHT_CHECKS.get(self.name)
            if light is not None:
                try:
                    ver = light(str(found))
                except Exception:
                    ver = None
                if ver is not None:
                    base["available"] = True
                    base["version"] = ver
                    base["reason"] = ""
                    base["state"] = "ok"
                    return base
        kwargs = {
            "args": [str(found)] + self.argv,
            "capture_output": True,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "timeout": self.timeout,
        }
        if _CREATE_NO_WINDOW:
            kwargs["creationflags"] = _CREATE_NO_WINDOW
        try:
            run = self._runner or subprocess.run
            res = run(**kwargs)
        except subprocess.TimeoutExpired:
            # 超时 ≠ 未安装：工具可能已装好，只是本机繁忙导致响应慢
            base["reason"] = "%s 探测超时（%.1fs），工具可能已安装但响应慢" % (
                self.name, self.timeout)
            base["state"] = "timeout"
            return base
        except (OSError, ValueError, TypeError) as exc:
            base["reason"] = "%s 探测失败：%s" % (self.name, exc)
            base["state"] = "error"
            return base
        except Exception as exc:  # 外部 CLI 千差万别，一律诚实降级
            base["reason"] = "%s 探测异常：%s" % (self.name, exc)
            base["state"] = "error"
            return base
        if getattr(res, "returncode", -1) != 0:
            base["reason"] = "%s 探测命令退出码 %s，本次判定为未启用" % (
                self.name, getattr(res, "returncode", -1))
            base["state"] = "error"
            return base
        text = (getattr(res, "stdout", "") or "") + (getattr(res, "stderr", "") or "")
        if self.version_re:
            m = self.version_re.search(text)
            if m:
                base["version"] = m.group(1).strip()
        base["available"] = True
        base["reason"] = "可用"
        base["state"] = "ok"
        return base

    def run(self, *args, **kwargs):
        """S1 不实现真实调用；提前调用必须显式报错，绝不静默返回假结果。"""
        raise NotImplementedError(
            "%s 的真实调用将在对应能力阶段（S3/S4/S5）接入" % self.name)


def _adapters(deep: bool = False) -> dict[str, ToolAdapter]:
    # TOOL_SPECS 三元组结构保持不变（S1 契约锁死）；只按工具名覆盖探测超时。
    return {name: ToolAdapter(name, argv, ver,
                              timeout=PROBE_TIMEOUTS.get(name, DEFAULT_TIMEOUT),
                              deep=deep)
            for name, argv, ver in TOOL_SPECS}


def probe_deep(name: str) -> dict:
    """**深度验证**：真跑探测命令，不走轻量快路径。

    用于「必须确认命令真的能跑」的时刻：组件安装流程末尾（确认装好了）
    与真正调用前。普通界面探测走 :func:`probe_all` 的快路径（毫秒级）。
    """
    spec = next((s for s in TOOL_SPECS if s[0] == name), None)
    if spec is None:
        return {"available": False, "path": "", "version": "",
                "reason": "无探测规格"}
    adapter = ToolAdapter(spec[0], spec[1], spec[2],
                          timeout=PROBE_TIMEOUTS.get(name, DEFAULT_TIMEOUT),
                          deep=True)
    return adapter.probe()


def reset_cache() -> None:
    """清空缓存（测试与「刷新探测」用）。"""
    global _CACHE, _REFRESH_OPEN
    with _LOCK:
        _CACHE = None
        _REFRESH_OPEN = False


def probe_all(refresh: bool = False) -> dict:
    """探测全部工具，结果进程内缓存；刷新时重新执行。

    **同一轮刷新只真探一次**（用户 2026-11-19 实测：/api/tools/probe 会依次调
    payload → audio_transcribe → video_transcribe，若每处都带 refresh=True
    就会把同一份探测跑 3 遍）。

    做法：用「刷新令牌」区分「新一轮刷新」与「同一轮内的重复调用」。
    显式调用 :func:`begin_refresh` 开启新一轮；同一轮内重复调用直接复用缓存。
    未开启新轮次时，refresh=True 也只真探一次（令牌不变则复用）。
    """
    global _CACHE
    # 注意：**绝不在持有 _LOCK 时调用 _probe_now()**——它内部会再取同一把
    # 非重入锁 → 死锁（用户 2026-11-19 实测 /api/tools/probe 直接超时）。
    with _LOCK:
        if not refresh:
            cached = _CACHE
        else:
            # refresh=True：本轮窗口已开 → 同轮重复调用，复用缓存
            cached = _CACHE if _REFRESH_OPEN else None
    if cached is not None:
        return dict(cached)
    return _probe_now()


def begin_refresh() -> None:
    """开启新一轮刷新（清缓存 + 打开刷新窗口）。

    由调用方（/api/tools/probe 等）在处理一次用户「刷新」动作时调用一次，
    使该轮内的多处探测共享同一份结果。"""
    global _CACHE, _REFRESH_OPEN
    with _LOCK:
        _CACHE = None
        _REFRESH_OPEN = True


def end_refresh() -> None:
    """结束刷新窗口（此后 refresh=True 会真探一次新的）。"""
    global _REFRESH_OPEN
    with _LOCK:
        _REFRESH_OPEN = False


def _probe_now() -> dict:
    """真正执行一轮探测并写入缓存。"""
    global _CACHE
    result = {}
    for name, adapter in _adapters().items():
        result[name] = adapter.probe()
    with _LOCK:
        _CACHE = result
    return dict(result)


def capabilities() -> dict:
    """S1 预留的「能力占位清单」，一律如实标记 ``enabled=False``。

    **S2a / S2b 裁决**：本清单被 ``test_33`` 的
    ``all(not v["enabled"] for v in caps.values())`` 锁死，后续阶段
    **不得改写**（否则既有断言变红）。已落地能力的真实状态由
    ``app.py::_api_tools_probe`` 挂到 ``/api/tools/probe`` 的**顶层增量字段**
    ``word_input`` / ``word_export`` 给出；UI 读顶层字段，不读本清单。
    """
    return {
        "media_transcribe": {
            "enabled": False,
            "reason": "阶段 3 转写后端尚未接入（S3）",
        },
        "word_export": {
            "enabled": False,
            "reason": "阶段 2 二期导出尚未实现（S2b）",
        },
        "link_resolve": {
            "enabled": False,
            "reason": "链接解析尚未实现（S5）",
        },
    }


def media_ready(tools: dict | None = None, caps: dict | None = None) -> bool:
    """音视频转写是否真的可点：能力已接入 + 必需工具都可用。"""
    caps = caps if caps is not None else capabilities()
    tools = tools if tools is not None else probe_all()
    if not caps.get("media_transcribe", {}).get("enabled"):
        return False
    return all(bool(tools.get(name, {}).get("available"))
               for name in ("ffmpeg", "whisper"))


def payload(refresh: bool = False) -> dict:
    """``/api/tools/probe`` 的响应体。"""
    tools = probe_all(refresh=refresh)
    caps = capabilities()
    return {
        "ok": True,
        "tools": tools,
        "capabilities": caps,
        "media_ready": media_ready(tools, caps),
        "note": "工具由本机提供，软件不下载 / 不打包 / 不自动安装",
    }


# --------------------------------------------------------------------------- #
# S3 增量辅助：外部工具进程树终止（不改 TOOL_SPECS / capabilities 的既有契约）
# --------------------------------------------------------------------------- #
def terminate_process_tree(proc) -> bool:
    """终止 ``proc`` 及其派生的子进程，返回是否尝试过进程树终止。

    whisper CLI 内部会再拉起 ffmpeg 解码音频；只 ``terminate()`` 外壳会留下
    孤儿进程继续占用 CPU 与临时文件（契约 §5 / §9 R3）。Windows 用
    ``taskkill /T /F /PID`` 杀整棵树；POSIX 用进程组 ``killpg``。

    仅对**真实** ``subprocess.Popen`` 生效；测试里的 MagicMock 会原样走
    ``Job.terminate_children()`` 的单进程分支，既有断言不受影响。
    """
    if not isinstance(proc, subprocess.Popen):
        return False
    try:
        if proc.poll() is not None:
            return False
    except Exception:
        return False
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                capture_output=True, timeout=5,
                creationflags=_CREATE_NO_WINDOW,
            )
        else:
            import signal
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except Exception:
        return False
    return True
