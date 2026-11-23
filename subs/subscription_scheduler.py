#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精核 · S13 应用内订阅调度器（方案 B，调度无关核心的外壳）。

用户裁决 2026-11-22：方案 B 作为一期基线——软件运行时按订阅间隔轮询，
启动时补跑到期项；关窗后随托盘后台运行继续轮询；进程真正退出时随后端
停止。下次启动再从 ``last_polled`` 补上遗漏（兑现裁决③）。

设计：
* **daemon 线程 + Event 停止**：不 spawn 常驻子进程，不违背「真正退出时
  零残留」——进程退出时线程随之结束，订阅引擎的临时目录照常清理。
* **不抢锁**：真正干活的是 ``subscription_engine``（自带单实例 Job 锁）。
  调度器只判断「当前没有任务在跑」才触发，避免与手动「立即同步」打架。
* **可注入**：``sleep_fn`` / ``due_fn`` / ``start_fn`` / ``running_fn`` 可替换，
  测试不依赖真实时钟与网络。
* **失败不影响调度**：某次 due 触发失败只记 last_error，下一轮照常尝试。
"""
from __future__ import annotations

import threading
import time

import subscription_engine as engine
import subscription_store as store

DEFAULT_TICK_SECONDS = 60.0     # 检查间隔（分钟级足够，订阅默认 24h）
MIN_TICK_SECONDS = 10.0
DEFAULT_START_DELAY = 10.0      # 启动后延迟补跑，避免与界面初始化抢资源

_STATE: dict = {
    "running": False,
    "started_at": 0.0,
    "last_check": 0.0,
    "last_start": 0.0,
    "triggers": 0,
    "last_error": "",
}
_THREAD: threading.Thread | None = None
_STOP: threading.Event | None = None
_LOCK = threading.Lock()


def _loop(tick: float, start_delay: float, *, outdir: str, kb_dir,
          sleep_fn, due_fn, start_fn, running_fn) -> None:
    """调度主循环（在 daemon 线程内运行）。"""
    if start_delay > 0:
        sleep_fn(start_delay)
    while _STOP is not None and not _STOP.is_set():
        try:
            with _LOCK:
                _STATE["last_check"] = time.time()
            if not running_fn():
                due = due_fn()
                if due:
                    res = start_fn([s["id"] for s in due], outdir, kb_dir)
                    with _LOCK:
                        if res.get("ok"):
                            _STATE["triggers"] += 1
                            _STATE["last_start"] = time.time()
                            _STATE["last_error"] = ""
                        else:
                            _STATE["last_error"] = str(res.get("error") or "")[:200]
        except Exception as exc:
            with _LOCK:
                _STATE["last_error"] = "调度异常：%s" % type(exc).__name__
        sleep_fn(tick)


def start(outdir: str, kb_dir, *, tick: float = DEFAULT_TICK_SECONDS,
          start_delay: float = DEFAULT_START_DELAY,
          sleep_fn=None, due_fn=None, start_fn=None, running_fn=None) -> dict:
    """启动调度线程（幂等：已在跑则直接返回）。"""
    global _THREAD, _STOP
    with _LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return {"ok": True, "already_running": True}
        if not str(outdir or "").strip():
            return {"ok": False, "error": "缺少输出目录，调度器未启动"}
        tick = max(MIN_TICK_SECONDS, float(tick or DEFAULT_TICK_SECONDS))
        _STOP = threading.Event()
        kwargs = {
            "outdir": outdir, "kb_dir": kb_dir,
            "sleep_fn": sleep_fn or (lambda s: _STOP.wait(s)),
            "due_fn": due_fn or store.due_subs,
            "start_fn": start_fn or engine.start,
            "running_fn": running_fn or (lambda: bool(engine.status().get("running"))),
        }
        _THREAD = threading.Thread(target=_loop, args=(tick, start_delay),
                                   kwargs=kwargs,
                                   daemon=True, name="jinghe-sub-scheduler")
        _THREAD.start()
        _STATE.update({"running": True, "started_at": time.time(),
                       "triggers": 0, "last_error": ""})
        return {"ok": True, "started": True, "tick": tick}


def stop(timeout: float = 3.0) -> dict:
    """请求停止调度线程（由后端退出钩子调用；daemon 属性保证兜底退出）。"""
    global _THREAD, _STOP
    with _LOCK:
        if _STOP is None:
            return {"ok": True, "stopped": False}
        _STOP.set()
        t = _THREAD
        _STATE["running"] = False
    if t is not None and t.is_alive():
        t.join(timeout=timeout)
    with _LOCK:
        _THREAD = None
        _STOP = None
    return {"ok": True, "stopped": True}


def status() -> dict:
    with _LOCK:
        return dict(_STATE)
