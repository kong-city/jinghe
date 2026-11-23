#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精核 · S12a 频道发现（只枚举，不下载）。

职责：给一个「博主主页 / 播放列表 / 频道」URL，用本机 yt-dlp 的
``--flat-playlist --dump-single-json`` 列出该频道最近 N 条视频的
``id / url / 标题 / 上传日期``，**不下载任何媒体**。

为什么不复用 link_downloader：
* 下载器刻意 ``--no-playlist --max-downloads 1``（逐条调度，契约锁死）；
* 发现阶段需要「一次拿到列表」，两者语义不同 —— 这里新建独立的只读枚举，
  不碰 S5 下载器，符合「新能力独立模块、冻结契约不动」的纪律。

安全与诚实边界：
* URL 先过 ``link_guard.check_link(shape only)``，SSRF 红线不打折；
* cookie 只做存在性预检（复用 link_downloader.validate_cookie_file），只读引用；
* 拿不到列表（平台反爬/需登录/无 yt-dlp）一律返回 ok=False + 原因，
  **不编造视频条目**；平台不支持 flat-playlist 时也如实说明；
* ``runner`` 可注入用于测试，生产路径为 None。
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import link_guard
import link_downloader

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DEFAULT_LIMIT = 20
MAX_LIMIT = 50
DISCOVER_TIMEOUT = 120.0


def capability() -> dict:
    """yt-dlp 是否可用（复用 S5 link_media 的能力探测，避免口径分叉）。

    注意：必须走 ``link_media.capability()``（内部 ``media_tools.probe_all``），
    不能用 ``media_tools.capabilities()`` —— 后者返回的是 media_transcribe /
    word_export / link_resolve 三个能力块，没有顶层 tools 键。
    """
    import link_media
    cap = link_media.capability(refresh=False)
    y = (cap.get("tools") or {}).get("yt-dlp") or {}
    available = bool(y.get("available"))
    return {"enabled": available,
            "reason": "" if available else
                      "未检测到本机 yt-dlp。订阅功能依赖 yt-dlp 枚举频道，"
                      "软件不下载、不打包该工具，请先在本机安装。"}


def build_argv(url: str, *, limit: int = DEFAULT_LIMIT,
               cookie_file: str = "") -> list[str]:
    """构造只读枚举参数（顺序固定，便于测试与审计）。"""
    argv = [
        "yt-dlp",
        "--flat-playlist",        # 只列条目，不解析每条的完整信息
        "--dump-single-json",     # 一次性输出整个播放列表 JSON
        "--playlist-end", str(int(limit)),
        "--no-warnings",
        "--socket-timeout", "30",
    ]
    if cookie_file:
        argv += ["--cookies", cookie_file]
    argv.append(url)
    return argv


def _video_ref(entry: dict) -> dict | None:
    """把 yt-dlp flat 条目收敛成规范 VideoRef；无 id/url 的条目丢弃。"""
    if not isinstance(entry, dict):
        return None
    vid = str(entry.get("id") or "").strip()
    url = str(entry.get("url") or "").strip() or \
        str(entry.get("webpage_url") or "").strip()
    if not vid:
        return None
    # flat 模式下 url 常是相对 ID，补成可下载的形状交给后续（详情由下载器负责）
    if url and url.startswith("//"):
        url = "https:" + url
    published = str(entry.get("upload_date") or
                     (entry.get("timestamp") and
                      __import__("datetime").datetime.utcfromtimestamp(
                          float(entry["timestamp"])).strftime("%Y%m%d")) or "").strip()
    return {
        "id": vid,
        "url": url,
        "title": str(entry.get("title") or vid).strip()[:200],
        "published": published[:8],
    }


def parse_entries(payload: object, *, limit: int = DEFAULT_LIMIT) -> list[dict]:
    """解析 yt-dlp 的 JSON 输出为 VideoRef 列表（去重、限量、保序）。"""
    if not isinstance(payload, dict):
        return []
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for e in entries:
        ref = _video_ref(e)
        if not ref or ref["id"] in seen:
            continue
        seen.add(ref["id"])
        out.append(ref)
        if len(out) >= limit:
            break
    return out


def discover(url: str, *, limit: int = DEFAULT_LIMIT,
             cookie_file: str = "", runner=None) -> dict:
    """枚举频道的近期视频。

    ``runner(argv, timeout)`` 可注入；返回 ``{ok, entries|error, url}``。
    成功时 entries 是 VideoRef 列表（可能为空——如频道确实没有视频，这不是错误）。
    """
    raw = str(url or "").strip()
    if not raw:
        return {"ok": False, "error": "请提供频道地址", "entries": []}
    limit = max(1, min(MAX_LIMIT, int(limit or DEFAULT_LIMIT)))

    # ① 形状预检（DNS 解析交给后续下载阶段，这里只查形状，避免阻塞响应）
    shape = link_guard.check_link(raw, resolve=False)
    if not shape.ok:
        return {"ok": False, "error": "订阅地址不合法：%s" % shape.error,
                "entries": []}

    # ② cookie 只读预检（不读内容）
    try:
        cookies = link_downloader.validate_cookie_file(cookie_file)
    except link_downloader.DownloadRejected as exc:
        return {"ok": False, "error": "cookie 不可用：%s" % exc, "entries": []}

    cap = capability()
    if not cap["enabled"]:
        return {"ok": False, "error": cap["reason"], "entries": []}

    argv = build_argv(raw, limit=limit, cookie_file=cookies)
    try:
        if runner is not None:
            res = runner(argv, DISCOVER_TIMEOUT)
        else:
            res = subprocess.run(
                argv, capture_output=True, timeout=DISCOVER_TIMEOUT,
                creationflags=_CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "枚举超时（频道可能过大或网络不通）",
                "entries": []}
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": "枚举失败：%s" % type(exc).__name__,
                "entries": []}

    # 兼容两种 runner 返回：subprocess.CompletedProcess 或 dict(stdout/returncode)
    if hasattr(res, "stdout"):
        out_text = res.stdout or b""
        code = res.returncode
        err_text = res.stderr or b""
    elif isinstance(res, dict):
        out_text = res.get("stdout") or b""
        code = res.get("returncode", 0)
        err_text = res.get("stderr") or b""
    else:
        return {"ok": False, "error": "枚举返回格式异常", "entries": []}
    if isinstance(out_text, bytes):
        out_text = out_text.decode("utf-8", "replace")
    if code not in (0, None):
        detail = err_text.decode("utf-8", "replace") if isinstance(err_text, bytes) \
            else str(err_text)
        return {"ok": False,
                "error": "yt-dlp 枚举失败（码 %s）：%s" % (code, detail[-200:]),
                "entries": []}
    try:
        payload = json.loads(out_text)
    except (ValueError, TypeError):
        return {"ok": False, "error": "yt-dlp 输出无法解析（可能需登录或平台不支持）",
                "entries": []}
    entries = parse_entries(payload, limit=limit)
    return {"ok": True, "entries": entries, "url": raw,
            "total": int(payload.get("playlist_count") or len(entries)) or len(entries)}
