#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精核 · S5b 链接批量编排（下载 + 复用 S4 视频 handler，独立任务队列）。

用户 2026-11-17 裁决：域名不设限、规模默认（≤20 条 / 单条 ≤2h / 总 ≤2GB）、
允许本机 cookie 文件（只读不落盘）、版权不纳入软件判断。

职责边界：
* 本模块**只编排**：逐条预检 → 下载 → 汇总路径 → 调 ``video_transcribe.transcribe``
  产出 md。绝不自己写转写逻辑，绝不 import 音频模块（守 S4 红线）；
* 独立任务队列 ``_MEDIA_JOB``，不污染阶段 1 / 音频 / 视频 / 精读四条队列；
* 逐条成功/失败/跳过互不影响，单条失败不拖垮整批；
* 取消即置标志，下载器与 S4 handler 在检查点自行退出并清理临时文件。
"""
from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time
from pathlib import Path

import link_downloader
import link_guard
import media_tools
import media_runtime
import video_transcribe

# 能力状态字符串
STATUS_UNAVAILABLE = "unavailable"

_LOCK = threading.Lock()
_JOB: dict | None = None
_TEMP_ROOT = Path(tempfile.gettempdir())


def capability(refresh: bool = False) -> dict:
    """/api/tools/probe 顶层增量字段 ``link_resolve`` 的真实能力状态。"""
    tools = media_tools.probe_all(refresh=refresh)
    ydl = tools.get("yt-dlp") or {}
    ffmpeg = tools.get("ffmpeg") or {}
    missing = [name for name, ok in (("yt-dlp", ydl.get("available")),
                                     ("ffmpeg", ffmpeg.get("available")))
               if not ok]
    available = not missing
    return {
        "name": "link_resolve",
        "enabled": available,
        "capability": "available" if available else STATUS_UNAVAILABLE,
        "reason": ("可用" if available else
                   "未启用：缺少本机工具（%s）；软件不下载不打包，请自行安装"
                   % "、".join(missing)),
        "tools": {"yt-dlp": ydl, "ffmpeg": ffmpeg},
        "missing": missing,
        "limits": {
            "max_entries": link_downloader.MAX_ENTRIES,
            "max_duration_seconds": link_downloader.MAX_DURATION_SECONDS,
            "max_total_bytes": link_downloader.MAX_TOTAL_BYTES,
        },
        "cookie": "只读引用本机 cookie 文件，不落盘不外传",
        "note": ("域名不设限；SSRF 内网防护为硬红线；产物只落 out/derived/，"
                 "不参与阶段 1 件数对账"),
    }


def _add(etype: str, text: str, progress: float | None = None) -> dict:
    with _LOCK:
        if _JOB is None:
            return {}
        ev = {"i": len(_JOB["events"]) + 1, "type": etype, "text": text}
        if progress is not None:
            ev["progress"] = round(float(progress), 4)
        _JOB["events"].append(ev)
        return ev


def _cancelled() -> bool:
    with _LOCK:
        return bool(_JOB and _JOB.get("cancelled"))


def _new_tmpdir() -> Path:
    base = _TEMP_ROOT / ("jinghe-link-%d-%d" % (os.getpid(), time.time_ns()))
    base.mkdir(parents=True, exist_ok=True)
    return base


def start(urls: list[str], outdir: str, *, cookie_file: str = "",
          refresh: bool = False) -> dict:
    """校验后启动批量任务线程，立即返回。"""
    global _JOB
    cap = capability(refresh=refresh)
    if not cap["enabled"]:
        return {"ok": False, "capability": STATUS_UNAVAILABLE,
                "error": cap["reason"]}
    raw = [u.strip() for u in (urls or []) if isinstance(u, str) and u.strip()]
    if not raw:
        return {"ok": False, "error": "请提供视频链接"}
    if len(raw) > link_downloader.MAX_ENTRIES:
        return {"ok": False, "error": "单次最多 %d 条链接"
                % link_downloader.MAX_ENTRIES}
    # 全部先做形状预检（DNS 解析在下载线程里逐条做，避免阻塞 HTTP 响应）
    for u in raw:
        shape = link_guard.check_link(u, resolve=False)
        if not shape.ok:
            return {"ok": False, "error": "链接不合法：%s → %s" % (u[:60], shape.error)}
    try:
        out = Path(outdir).expanduser().resolve()
    except (OSError, ValueError):
        return {"ok": False, "error": "输出目录无效"}
    if not str(outdir or "").strip():
        return {"ok": False, "error": "请先指定输出目录"}

    with _LOCK:
        if _JOB is not None and _JOB.get("running"):
            return {"ok": False, "error": "已有链接提取任务在运行，请等待或取消"}
        _JOB = {"state": "running", "running": True, "cancelled": False,
                "events": [], "output": "", "error": None,
                "total": len(raw), "done": 0, "success": 0, "failed": 0}
    t = threading.Thread(target=_run, args=(raw, str(out), cookie_file),
                         daemon=True, name="jinghe-link-media")
    t.start()
    return {"ok": True, "capability": cap["capability"], "started": True,
            "total": len(raw)}


def _run(urls: list[str], outdir: str, cookie_file: str) -> None:
    global _JOB
    tmp = _new_tmpdir()
    downloaded: list[str] = []
    total = len(urls)
    try:
        for idx, url in enumerate(urls, 1):
            if _cancelled():
                _add("log", "任务已取消，停止后续下载", idx / total)
                break
            _add("log", "下载第 %d/%d 条…" % (idx, total), (idx - 1) / total)
            res = link_downloader.run_download(
                url, tmp, cookie_file=cookie_file, cancel_check=_cancelled)
            if res.get("ok"):
                downloaded.append(res["path"])
                _add("log", "下载完成：%s" % Path(res["path"]).name)
            else:
                with _LOCK:
                    if _JOB is not None:
                        _JOB["failed"] = _JOB["failed"] + 1
                _add("error", "第 %d 条失败：%s" % (idx, res.get("error", "未知")))
            with _LOCK:
                if _JOB is not None:
                    _JOB["done"] = idx
                    _JOB["success"] = len(downloaded)

        if _cancelled():
            with _LOCK:
                if _JOB is not None:
                    _JOB["state"] = "cancelled"
            return
        if not downloaded:
            with _LOCK:
                if _JOB is not None:
                    _JOB["state"] = "failed"
                    _JOB["error"] = "所有链接均未下载成功，零产物"
            _add("error", "所有链接均未下载成功，未产出文档", 1.0)
            return

        # 复用 S4 handler 产出 md（三区块 + 锚点 + provenance 全部沿用）
        _add("log", "调用视频提取 handler 处理 %d 个文件…" % len(downloaded), 0.8)
        result = video_transcribe.transcribe(
            downloaded, outdir, cancel_check=_cancelled)
        ok = bool(result.get("ok"))
        with _LOCK:
            if _JOB is not None:
                _JOB["state"] = "done" if ok else "failed"
                _JOB["output"] = str(result.get("derived_dir") or "")
                _JOB["error"] = None if ok else result.get("error", "视频提取失败")
        _add("log", "完成" if ok else "视频提取失败", 1.0)
    except Exception as exc:
        with _LOCK:
            if _JOB is not None:
                _JOB["state"] = "failed"
                _JOB["error"] = "链接提取失败：%s" % type(exc).__name__
        _add("error", "链接提取失败：%s" % type(exc).__name__, 1.0)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)   # 取消 / 失败都清理临时下载
        with _LOCK:
            if _JOB is not None:
                _JOB["running"] = False


def status(since: int = 0) -> dict:
    with _LOCK:
        if _JOB is None:
            return {"state": "idle", "running": False, "events": [], "next": 0,
                    "output": "", "error": None, "total": 0, "done": 0,
                    "success": 0, "failed": 0}
        events = [e for e in _JOB["events"] if e["i"] > since]
        return {"state": _JOB["state"], "running": _JOB["running"],
                "events": events,
                "next": events[-1]["i"] if events else since,
                "output": _JOB["output"], "error": _JOB["error"],
                "total": _JOB["total"], "done": _JOB["done"],
                "success": _JOB["success"], "failed": _JOB["failed"]}


def cancel() -> dict:
    with _LOCK:
        if _JOB is None or not _JOB["running"]:
            return {"ok": True, "cancelled": False}
        _JOB["cancelled"] = True
        return {"ok": True, "cancelled": True}
