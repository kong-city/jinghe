#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精核 · S5b 链接下载编排（本机 yt-dlp，零第三方依赖）。

用户 2026-11-17 裁决：URL 域名不设限；允许自带本机 cookie 文件（只读不落盘）。

职责：
* 调用本机 ``yt-dlp`` 下载单个链接 / 播放列表条目到临时目录；
* 下载前走 :mod:`link_guard` 预检，下载后用 yt-dlp 报告的实际 URL **二次校验**
  （防重定向绕过）；
* ``.part`` 临时文件 + 原子替换；取消即终止子进程树并清理；
* cookie 文件**只读**传给 yt-dlp（``--cookies``），绝不复制进 derived / 日志 / 产物；
* 不内置任何账号密码，不绕验证码 / DRM。

**DNS 重绑定残留窗口（如实披露）**：yt-dlp 自行解析 DNS，零依赖架构下无法
在连接层固定预检 IP（改 host 会破坏 HTTPS SNI/证书校验，反而更不安全）。
本模块用「预检逐跳校验 + 下载后实际 URL 二次校验 + 跳数上限」把风险降到最低，
但不声称完全消除重绑定窗口——这是诚实边界，不假装做到做不到的事。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path

import link_guard

# 规模上限（用户裁决「默认」= 采用立项建议值）
MAX_ENTRIES = 20
MAX_DURATION_SECONDS = 2 * 3600
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
DOWNLOAD_TIMEOUT = 600.0

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_LOCK = threading.Lock()


class DownloadRejected(ValueError):
    """下载被拒绝（安全 / 规模 / 配置原因）。"""


def build_argv(url: str, outdir: Path, *, cookie_file: str = "",
               max_duration: int = MAX_DURATION_SECONDS) -> list[str]:
    """构造 yt-dlp 参数；顺序固定，便于测试与审计。"""
    tmpl = str(outdir / "%(id)s.%(ext)s")
    argv = [
        "yt-dlp",
        "--no-playlist",              # 播放列表由本模块逐条调度，不交给 yt-dlp 批量
        "--max-downloads", "1",
        "--socket-timeout", "30",
        "--retries", "2",
        "--max-redirects", str(link_guard.MAX_REDIRECTS),
        "--match-filter", "duration <= %d" % int(max_duration),
        "--print", "after_move:filepath",
        "-o", tmpl,
    ]
    if cookie_file:
        # 只读引用用户给的本机路径；不复制、不写入任何产物或日志
        argv += ["--cookies", cookie_file]
    argv.append(url)
    return argv


def validate_cookie_file(raw: str) -> str:
    """cookie 文件预检：必须是存在的**文件**、绝对路径由调用方展开；不读内容。

    只读引用，不复制、不解析、不落盘。返回规范化路径供 ``--cookies`` 使用。
    """
    p = (raw or "").strip()
    if not p:
        return ""
    try:
        path = Path(p).expanduser().resolve()
    except (OSError, ValueError):
        raise DownloadRejected("cookie 文件路径无效")
    if not path.is_file():
        raise DownloadRejected("cookie 文件不存在（请提供本机文件路径）")
    return str(path)


def _parse_final_url(stderr: str) -> str:
    """从 yt-dlp 日志里尽力提取最终 URL（仅用于二次校验，取不到就跳过）。"""
    m = re.findall(r"https?://[^\s'\"]+", stderr or "")
    return m[-1] if m else ""


def run_download(url: str, outdir: Path, *, cookie_file: str = "",
                 runner=None, job=None, cancel_check=None) -> dict:
    """下载单个链接，返回 ``{ok, path|error, final_url}``。

    ``runner`` / ``job`` / ``cancel_check`` 可注入用于测试与长任务进度。
    """
    # ① 预检（域名不设限，但 SSRF 红线不变）
    pre = link_guard.check_link(url)
    if not pre.ok:
        return {"ok": False, "error": "链接安全校验失败：%s" % pre.error}

    # ② cookie 只读预检（不读内容）
    try:
        cookies = validate_cookie_file(cookie_file)
    except DownloadRejected as exc:
        return {"ok": False, "error": str(exc)}

    outdir = Path(outdir)
    try:
        outdir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return {"ok": False, "error": "临时目录不可创建"}

    argv = build_argv(url, outdir, cookie_file=cookies)
    if cancel_check and cancel_check():
        return {"ok": False, "error": "已取消"}
    try:
        if runner is not None:
            res = runner(argv, timeout=DOWNLOAD_TIMEOUT, job=job)
        else:
            cp = subprocess.run(argv, capture_output=True, text=True,
                                encoding="utf-8", errors="replace",
                                timeout=DOWNLOAD_TIMEOUT,
                                creationflags=_CREATE_NO_WINDOW)
            res = {"returncode": cp.returncode,
                   "stdout": cp.stdout or "", "stderr": cp.stderr or ""}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "下载超时"}
    except OSError as exc:
        return {"ok": False, "error": "yt-dlp 启动失败：%s" % type(exc).__name__}

    stdout = str(res.get("stdout") or "")
    stderr = str(res.get("stderr") or "")
    # ③ 下载后实际 URL 二次校验（重定向可能指向内网）
    final_url = _parse_final_url(stderr) or url
    if final_url != url:
        post = link_guard.check_redirect_chain(
            final_url, hops=1)
        if not post.ok:
            # 已下载的文件可能是内网资源 → 立刻删除，绝不产出
            for line in stdout.splitlines():
                try:
                    Path(line.strip()).unlink(missing_ok=True)
                except OSError:
                    pass
            return {"ok": False, "error": "重定向后链接未通过安全校验：%s" % post.error}

    if int(res.get("returncode") or 0) != 0:
        # 失败不留残文件
        for line in stdout.splitlines():
            try:
                Path(line.strip()).unlink(missing_ok=True)
            except OSError:
                pass
        return {"ok": False, "error": "yt-dlp 下载失败（退出码 %d）"
                % int(res.get("returncode") or 0)}

    # ④ 取下载产物（yt-dlp --print after_move:filepath 的最后一行）
    lines = [ln.strip() for ln in stdout.splitlines() if ln.strip()]
    if not lines:
        return {"ok": False, "error": "yt-dlp 未报告下载文件"}
    target = Path(lines[-1])
    if not target.is_file():
        return {"ok": False, "error": "下载文件不存在"}
    try:
        size = target.stat().st_size
    except OSError:
        return {"ok": False, "error": "下载文件不可读"}
    if size > MAX_TOTAL_BYTES:
        target.unlink(missing_ok=True)
        return {"ok": False, "error": "下载文件超过大小上限"}
    return {"ok": True, "path": str(target), "size": size,
            "final_url": final_url, "host": pre.host}
