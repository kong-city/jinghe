#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精核 · S12a 订阅注册表（落盘持久化）。

职责：把「订阅的博主频道 / 视频主页」当作**配置数据**持久化到
``%LOCALAPPDATA%\\Jinghe\\subscriptions.json``，与 settings.json 并列，
活过进程重启。每条订阅保存：

* ``seen_ids`` —— 已处理过的视频 id 指纹集合（**第一层去重**，避免重复下载）；
* ``last_polled`` —— 上次成功拉取时间戳（供「启动补跑」判断 due）；
* ``fail_count`` / ``last_error`` —— 连续失败计数与最后一次错误（失败显式化，
  不假装成功；连续失败可在 UI 标红）。

设计纪律（继承项目铁律）：
* 纯标准库、零第三方依赖；
* 原子写入（``.tmp`` + ``replace``），崩溃不留半截文件；
* 保守校验：脏数据回退、非法字段丢弃，绝不因坏 JSON 崩掉服务；
* cookie 只存**用户给的本机路径字符串**，不读内容、不落日志、不进产物（复用 S5 契约）。

注意：本模块只管「数据落盘」，不含调度逻辑（在 subscription_engine /
subscription_scheduler），也不含下载（复用 link_downloader）。
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

# 落盘路径（可用环境变量覆盖，便于测试与多实例隔离）
_LOG_DIR = Path(os.environ.get("LOCALAPPDATA") or str(Path.home())) / "Jinghe"
SUB_FILE = Path(os.environ.get("JINGHE_SUBS_FILE") or
                str(_LOG_DIR / "subscriptions.json"))

# 规模上限（防误配撑爆本地资源；与 S5 MAX_ENTRIES 同量级）
MAX_SUBS = 50
MAX_SEEN_IDS = 500
DEFAULT_INTERVAL_HOURS = 24.0
MIN_INTERVAL_HOURS = 1.0
MAX_INTERVAL_HOURS = 720.0
MAX_FAILS_BEFORE_DISABLE = 5

_LOCK = threading.Lock()


def _new_id() -> str:
    """生成短订阅 id（时间戳 + 随机后缀，足够本地唯一）。"""
    import secrets
    return "sub_%s%s" % (format(int(time.time() * 1000), "x"),
                         secrets.token_hex(2))


def _as_interval(value) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL_HOURS
    return max(MIN_INTERVAL_HOURS, min(MAX_INTERVAL_HOURS, v))


def _clean_seen(value) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for v in value:
        if isinstance(v, str) and v.strip() and v.strip() not in out:
            out.append(v.strip())
    return out[-MAX_SEEN_IDS:]


def validate(raw: object) -> list[dict]:
    """把磁盘/外部数据收敛成合法订阅列表；脏项丢弃，绝不抛异常。"""
    if not isinstance(raw, dict):
        return []
    items = raw.get("subscriptions")
    if not isinstance(items, list):
        return []
    out: list[dict] = []
    seen_ids: set[str] = set()
    for item in items[:MAX_SUBS]:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        sid = str(item.get("id") or "").strip() or _new_id()
        if sid in seen_ids:
            continue
        seen_ids.add(sid)
        out.append({
            "id": sid,
            "url": url,
            "name": str(item.get("name") or "").strip()[:120],
            "enabled": bool(item.get("enabled", True)),
            "cookie_file": str(item.get("cookie_file") or "").strip(),
            "interval_hours": _as_interval(
                item.get("interval_hours", DEFAULT_INTERVAL_HOURS)),
            "seen_ids": _clean_seen(item.get("seen_ids")),
            "last_polled": float(item.get("last_polled") or 0) or 0.0,
            "last_new": int(item.get("last_new") or 0) or 0,
            "fail_count": int(item.get("fail_count") or 0) or 0,
            "last_error": str(item.get("last_error") or "").strip()[:300],
            "last_status": str(item.get("last_status") or "never").strip()[:40],
            "created_at": float(item.get("created_at") or 0) or time.time(),
        })
    return out


def _read_disk() -> list[dict]:
    try:
        if SUB_FILE.is_file():
            return validate(json.loads(SUB_FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return []


def _write_disk(items: list[dict]) -> bool:
    try:
        SUB_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = SUB_FILE.with_name(SUB_FILE.name + ".tmp")
        tmp.write_text(json.dumps({"subscriptions": items},
                                  ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(SUB_FILE)
        return True
    except OSError:
        return False


def list_subs() -> list[dict]:
    """读全部订阅（返回副本，调用方改了不污染缓存——本模块无缓存，直接读盘）。"""
    with _LOCK:
        return _read_disk()


def get_sub(sid: str) -> dict | None:
    for s in list_subs():
        if s["id"] == sid:
            return s
    return None


def add_sub(url: str, *, name: str = "", cookie_file: str = "",
            interval_hours=DEFAULT_INTERVAL_HOURS) -> dict:
    """新增订阅；URL 非空即可（安全校验在发现/下载阶段由 link_guard 负责）。"""
    url = str(url or "").strip()
    if not url:
        return {"ok": False, "error": "请提供订阅地址"}
    with _LOCK:
        items = _read_disk()
        if len(items) >= MAX_SUBS:
            return {"ok": False, "error": "订阅数量已达上限 %d" % MAX_SUBS}
        if any(s["url"] == url for s in items):
            return {"ok": False, "error": "该地址已订阅"}
        sid = _new_id()
        items.append({
            "id": sid, "url": url, "name": str(name or "").strip()[:120],
            "enabled": True, "cookie_file": str(cookie_file or "").strip(),
            "interval_hours": _as_interval(interval_hours),
            "seen_ids": [], "last_polled": 0.0, "last_new": 0,
            "fail_count": 0, "last_error": "", "last_status": "never",
            "created_at": time.time(),
        })
        if not _write_disk(items):
            return {"ok": False, "error": "订阅保存失败（磁盘不可写）"}
        return {"ok": True, "id": sid,
                "subscription": next(s for s in items if s["id"] == sid)}


def remove_sub(sid: str) -> dict:
    with _LOCK:
        items = _read_disk()
        kept = [s for s in items if s["id"] != sid]
        if len(kept) == len(items):
            return {"ok": False, "error": "订阅不存在"}
        if not _write_disk(kept):
            return {"ok": False, "error": "删除失败（磁盘不可写）"}
        return {"ok": True, "id": sid}


def set_enabled(sid: str, enabled: bool) -> dict:
    with _LOCK:
        items = _read_disk()
        target = next((s for s in items if s["id"] == sid), None)
        if target is None:
            return {"ok": False, "error": "订阅不存在"}
        target["enabled"] = bool(enabled)
        if not _write_disk(items):
            return {"ok": False, "error": "保存失败（磁盘不可写）"}
        return {"ok": True, "id": sid, "enabled": target["enabled"]}


def update_result(sid: str, *, seen_ids: list[str] | None = None,
                  new_count: int = 0, error: str = "") -> dict:
    """拉取结束后回写：成功更新指纹与时间、清零失败；失败累加计数。"""
    with _LOCK:
        items = _read_disk()
        target = next((s for s in items if s["id"] == sid), None)
        if target is None:
            return {"ok": False, "error": "订阅不存在"}
        if error:
            target["fail_count"] = int(target.get("fail_count") or 0) + 1
            target["last_error"] = str(error).strip()[:300]
            target["last_status"] = "failed"
            if target["fail_count"] >= MAX_FAILS_BEFORE_DISABLE:
                target["enabled"] = False
                target["last_error"] += "（连续失败已达上限，已自动停用）"
        else:
            if seen_ids is not None:
                target["seen_ids"] = _clean_seen(seen_ids)
            target["last_polled"] = time.time()
            target["last_new"] = int(new_count) or 0
            target["fail_count"] = 0
            target["last_error"] = ""
            target["last_status"] = "ok"
        if not _write_disk(items):
            return {"ok": False, "error": "回写失败（磁盘不可写）"}
        return {"ok": True, "subscription": target}


def due_subs(now: float | None = None) -> list[dict]:
    """返回到期待拉取的订阅（启用 + 从未拉取或距上次超过间隔）。"""
    now = now if now is not None else time.time()
    out: list[dict] = []
    for s in list_subs():
        if not s["enabled"]:
            continue
        last = float(s.get("last_polled") or 0)
        if last <= 0 or (now - last) >= s["interval_hours"] * 3600:
            out.append(s)
    return out
