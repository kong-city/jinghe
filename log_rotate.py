#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精核 · 系统日志按天切割 + 保留期清理（零第三方依赖）。

用户 2026-11-17 要求：系统日志按时间轮询切割，保留 7 天，删除 7 天前的日志。

设计要点（不破坏既有契约）：
* **当前日志真源仍是 ``app.log``**——``/api/open`` 白名单、``/api/export-log``、
  ``_LogSink`` 单例、所有既有测试都依赖这个固定路径，故绝不改名；
* 跨天时把 ``app.log`` **原子改名**为 ``app-YYYY-MM-DD.log`` 归档，
  随后 sink 重新打开一个空的 ``app.log``；
* 归档命名带日期，保留最近 ``RETAIN_DAYS`` 天（默认 7），更早的删除；
* ``check_and_rotate()`` 供 ``_LogSink`` 每次写入前调用（跨天即时切割），
  ``start_retention_watchdog()`` 后台定时轮询（默认每小时），两者共用一把锁，
  保证「跨天立刻切 + 长期挂着也会清」双保险；
* 归档/删除都只碰本软件 ``LOG_DIR`` 内、严格匹配 ``app-YYYY-MM-DD.log``
  形状的条目，绝不误删 app.log 本身、app.log.1 或其它文件。

Windows 注意：归档前必须先关闭 sink 持有的 app.log 句柄（由调用方在锁内完成），
否则 ``Path.replace`` 会因文件被占用而失败——这与既有 ``_rotate_if_needed``
按大小轮转的处理方式一致。
"""
from __future__ import annotations

import datetime as _dt
import re
import threading
import time
from pathlib import Path

RETAIN_DAYS = 7
# 归档文件名：app-YYYY-MM-DD.log（严格形状，避免误删其它文件）
ARCHIVE_RE = re.compile(r"^app-(\d{4})-(\d{2})-(\d{2})\.log$")
# 轮询间隔（秒）：每小时检查一次即可，跨天即时切割由写入钩子负责
WATCH_INTERVAL = 3600.0

_LOCK = threading.Lock()
_WATCH_STARTED = False


def archive_name(day: _dt.date) -> str:
    """给定日期返回归档文件名（如 app-2026-11-17.log）。"""
    return "app-%s.log" % day.isoformat()


def list_archives(log_dir: Path) -> list[tuple[_dt.date, Path]]:
    """列出合法形状的归档 ``(日期, 路径)``，按日期升序；非法/损坏条目忽略。"""
    out: list[tuple[_dt.date, Path]] = []
    try:
        candidates = list(Path(log_dir).glob("app-*.log"))
    except OSError:
        return out
    for p in candidates:
        m = ARCHIVE_RE.match(p.name)
        if not m:
            continue
        try:
            day = _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
        out.append((day, p))
    out.sort(key=lambda x: x[0])
    return out


def prune_old(log_dir: Path, today: _dt.date | None = None,
              retain_days: int = RETAIN_DAYS) -> list[str]:
    """删除 ``retain_days`` 天前的归档，返回被删文件名列表。

    口径：保留「今天」及往前 ``retain_days - 1`` 天，共 ``retain_days`` 天；
    早于 ``today - (retain_days - 1)`` 的归档一律删除。只删严格匹配形状的
    归档文件，绝不碰 app.log / app.log.1 / 其它文件。
    """
    today = today or _dt.date.today()
    cutoff = today - _dt.timedelta(days=max(1, retain_days) - 1)
    removed: list[str] = []
    with _LOCK:
        for day, path in list_archives(log_dir):
            if day < cutoff:
                try:
                    path.unlink()
                    removed.append(path.name)
                except OSError:
                    # 删除失败（占用/权限）不抛错，下次轮询会再试
                    continue
    return removed


def should_rotate(log_file: Path, today: _dt.date | None = None) -> bool:
    """纯预检：app.log 的内容是否属于更早的日期（供调用方先关句柄再归档）。"""
    today = today or _dt.date.today()
    p = Path(log_file)
    try:
        if not p.is_file() or p.stat().st_size == 0:
            return False
        mtime = _dt.datetime.fromtimestamp(p.stat().st_mtime).date()
    except OSError:
        return False
    return mtime < today


def rotate_if_needed(log_file: Path, today: _dt.date | None = None) -> str | None:
    """如果 ``log_file`` 的内容属于更早的日期，就归档它，返回归档文件名。

    判定依据用**文件最后修改时间**（不是进程时间）：这样即使软件跨天一直没重启，
    也能把「昨天的日志」按昨天归档；刚打开尚无内容的 app.log 不会误归档。
    归档名若已存在（同一天多次启动），追加时分秒后缀避免覆盖。
    """
    if not should_rotate(log_file, today):
        return None
    today = today or _dt.date.today()
    p = Path(log_file)
    try:
        mtime = _dt.datetime.fromtimestamp(p.stat().st_mtime).date()
        name = archive_name(mtime)
        dest = p.with_name(name)
        if dest.exists():
            stamp = _dt.datetime.fromtimestamp(p.stat().st_mtime).strftime("%H%M%S")
            dest = p.with_name("app-%s-%s.log" % (mtime.isoformat(), stamp))
        p.replace(dest)
    except OSError:
        return None
    return dest.name


def check_and_rotate(log_file: Path) -> str | None:
    """写入钩子：跨天归档 + 顺手清理过期归档。返回归档名（若发生切割）。"""
    archived = rotate_if_needed(log_file)
    if archived:
        prune_old(Path(log_file).parent)
    return archived


def start_retention_watchdog(log_dir: Path, current_log: Path,
                             interval: float = WATCH_INTERVAL) -> bool:
    """启动后台轮询线程（daemon，幂等）；hourly 清理旧日志 + 兜底切割。

    ``current_log`` 必须是 ``_LogSink`` 正在写的那个文件：轮询线程只在 sink
    锁外调用本模块自己的锁，真正的归档仍需 sink 写入钩子配合关闭句柄；
    因此轮询线程只负责**清理**（安全、无需碰当前句柄），跨天切割交给写入钩子。
    """
    global _WATCH_STARTED
    with _LOCK:
        if _WATCH_STARTED:
            return False
        _WATCH_STARTED = True

    def _watch() -> None:
        while True:
            time.sleep(interval)
            try:
                prune_old(Path(log_dir))
            except Exception:
                pass  # 清理失败绝不打断主程序，下次轮询再试

    threading.Thread(target=_watch, name="jinghe-log-retention",
                     daemon=True).start()
    return True
