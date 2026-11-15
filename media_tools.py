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

import re
import shutil
import subprocess
import threading
from typing import Callable

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# 每台工具一次轻量探测；超时刻意压短，避免启动界面被外部 CLI 拖住。
DEFAULT_TIMEOUT = 2.0

# (工具名, 探测参数, 版本正则或 None)
TOOL_SPECS: tuple[tuple[str, list[str], str | None], ...] = (
    ("ffmpeg", ["-version"], r"ffmpeg version\s+(\S+)"),
    ("whisper", ["--help"], None),
    ("yt-dlp", ["--version"], r"^\s*(\d[^\s]*)"),
)

_CACHE: dict[str, dict] | None = None
_LOCK = threading.Lock()


class ToolAdapter:
    """统一接口：``probe() -> {available, path, version, reason}``。

    ``run()`` 留给 S3/S4/S5 的真实调用实现，S1 只落接口与健康探测，
    绝不提前产出内容。``which`` / ``runner`` 可注入，便于契约测试。
    """

    def __init__(self, name: str, argv: list[str],
                 version_re: str | None = None,
                 timeout: float = DEFAULT_TIMEOUT,
                 which: Callable[[str], str | None] | None = None,
                 runner: Callable | None = None) -> None:
        self.name = name
        self.argv = list(argv)
        self.version_re = re.compile(version_re) if version_re else None
        self.timeout = timeout
        self._which = which or shutil.which
        self._runner = runner

    def probe(self) -> dict:
        base = {"available": False, "path": "", "version": "", "reason": ""}
        try:
            found = self._which(self.name)
        except Exception as exc:
            base["reason"] = "工具查找失败：%s" % exc
            return base
        if not found:
            base["reason"] = "本机未找到 %s，请安装后重试" % self.name
            return base
        base["path"] = str(found)
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
            base["reason"] = "%s 探测超时（%.1fs），本次判定为未启用" % (
                self.name, self.timeout)
            return base
        except (OSError, ValueError, TypeError) as exc:
            base["reason"] = "%s 探测失败：%s" % (self.name, exc)
            return base
        except Exception as exc:  # 外部 CLI 千差万别，一律诚实降级
            base["reason"] = "%s 探测异常：%s" % (self.name, exc)
            return base
        if getattr(res, "returncode", -1) != 0:
            base["reason"] = "%s 探测命令退出码 %s，本次判定为未启用" % (
                self.name, getattr(res, "returncode", -1))
            return base
        text = (getattr(res, "stdout", "") or "") + (getattr(res, "stderr", "") or "")
        if self.version_re:
            m = self.version_re.search(text)
            if m:
                base["version"] = m.group(1).strip()
        base["available"] = True
        base["reason"] = "可用"
        return base

    def run(self, *args, **kwargs):
        """S1 不实现真实调用；提前调用必须显式报错，绝不静默返回假结果。"""
        raise NotImplementedError(
            "%s 的真实调用将在对应能力阶段（S3/S4/S5）接入" % self.name)


def _adapters() -> dict[str, ToolAdapter]:
    return {name: ToolAdapter(name, argv, ver)
            for name, argv, ver in TOOL_SPECS}


def reset_cache() -> None:
    """清空缓存（测试与「刷新探测」用）。"""
    global _CACHE
    with _LOCK:
        _CACHE = None


def probe_all(refresh: bool = False) -> dict:
    """探测全部工具，结果进程内缓存；刷新时重新执行。"""
    global _CACHE
    with _LOCK:
        cached = None if refresh else _CACHE
    if cached is not None:
        return dict(cached)
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
