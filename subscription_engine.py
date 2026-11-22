#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精核 · S12a 订阅增量编排引擎（手动触发，调度无关）。

职责：把「订阅一条频道」变成一条可重复执行、幂等、可取消的流水线：

    discover（列频道近期视频）
      → 差集（去掉 seen_ids，只看新视频）
      → link_guard + link_downloader（逐条安全下载）
      → video_transcribe（S4 独立 handler，三区块 md + 锚点）
      → kb.ingest_md（content_hash 幂等去重，第二层保险）
      → subscription_store.update_result（回写 seen_ids / 时间 / 失败计数）

**两层去重**：
1. ``seen_ids``（订阅注册表）—— 已处理过的视频 id，避免重复下载（省流量）；
2. ``content_hash``（kb.ingest_md）—— 内容级幂等，避免重复入库（保库干净）。
   二者互不依赖，任一层失效另一层兜底。

**调度无关**：本模块只提供 ``run_due`` / ``run_one`` / ``run_now``，由谁触发
（手动按钮、应用内定时器、外部 cron）不关心。这是 S12 架构分析里「核心与
调度外壳解耦」原则的落地，将来加系统常驻服务不用改这里。

纪律：
* 单实例串行（与 S5 一样，不并发抢带宽），daemon 线程，不 spawn 常驻子进程；
* 可取消、有进度事件、逐条失败隔离；
* 全部外部依赖（发现/下载/转写/入库）可注入 runner，测试不需真实网络与模型；
* 下载临时目录随任务清理，取消/失败都不留残留。
"""
from __future__ import annotations

import shutil
import tempfile
import threading
import time
from pathlib import Path

import channel_discovery
import kb
import link_downloader
import media_runtime
import subscription_store as store
import video_transcribe

_LOCK = threading.Lock()
_JOB: dict | None = None
MAX_PER_RUN = 20          # 单次同步最多处理的新视频数（防误配撑爆）
_TEMP_ROOT = Path(tempfile.gettempdir())


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
    base = _TEMP_ROOT / ("jinghe-sub-%d-%d" % (time.time_ns(), 0))
    base.mkdir(parents=True, exist_ok=True)
    return base


def _kb_roots(outdir: Path, kb_dir) -> list[str]:
    """给入库的显式白名单：产物目录 + 知识库目录（不放开任意路径）。"""
    roots = [str(outdir.resolve()), str(Path(kb_dir).resolve())]
    return roots


def _sync_one(sub: dict, *, outdir: Path, kb_dir, discover_fn, download_fn,
              transcribe_fn, ingest_fn, iterate_fn=None, refine_rounds=1) -> dict:
    """同步单条订阅，返回 ``{ok, new_ids, new_count, error}``。"""
    sid = sub["id"]
    seen = set(sub.get("seen_ids") or [])
    disc = discover_fn(sub["url"], limit=MAX_PER_RUN,
                       cookie_file=sub.get("cookie_file", ""))
    if not disc.get("ok"):
        return {"ok": False, "new_ids": [], "new_count": 0,
                "error": disc.get("error", "频道枚举失败")}
    entries = disc.get("entries") or []
    fresh = [e for e in entries if e.get("id") not in seen]
    if not fresh:
        return {"ok": True, "new_ids": [], "new_count": 0, "error": ""}

    fresh = fresh[:MAX_PER_RUN]
    _add("log", "频道「%s」发现 %d 条新视频"
         % (sub.get("name") or sub["url"][:40], len(fresh)))
    tmp = _new_tmpdir()
    downloaded: list[str] = []
    new_ids: list[str] = []
    try:
        for i, ref in enumerate(fresh, 1):
            if _cancelled():
                break
            _add("log", "下载 %d/%d：%s" % (i, len(fresh), ref.get("title", "")[:40]),
                 i / len(fresh) / 2)
            dl = download_fn(ref["url"], tmp, cookie_file=sub.get("cookie_file", ""))
            if not dl.get("ok"):
                _add("error", "下载失败：%s → %s"
                     % (ref.get("title", "")[:30], dl.get("error", "未知")))
                continue
            downloaded.append(dl["path"])
            new_ids.append(ref["id"])

        if _cancelled() or not downloaded:
            return {"ok": True, "new_ids": new_ids, "new_count": len(new_ids),
                    "error": "" if not _cancelled() else "已取消"}

        _add("log", "转写 %d 个视频…" % len(downloaded), 0.6)
        tr = transcribe_fn(downloaded, str(outdir))
        if not tr.get("ok"):
            return {"ok": False, "new_ids": new_ids, "new_count": len(new_ids),
                    "error": tr.get("error", "视频转写失败")}

        # 转写产物在 derived/ 内的 .md；逐份入库（content_hash 幂等）
        derived = media_runtime.derived_dir(outdir)
        mds = sorted(derived.glob("*.md")) if derived.is_dir() else []
        added = 0
        roots = _kb_roots(outdir, kb_dir)
        for md in mds:
            if _cancelled():
                break
            ing = ingest_fn(kb_dir, str(md), allowed_roots=roots)
            if ing.get("ok"):
                added += int(ing.get("added") or 0)
        _add("log", "入库完成：新增 %d 条知识条目" % added, 0.9)
        return {"ok": True, "new_ids": new_ids, "new_count": len(new_ids),
                "error": ""}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run(sids: list[str], outdir: str, kb_dir, *, discover_fn, download_fn,
         transcribe_fn, ingest_fn, iterate_fn=None, refine_rounds=1) -> None:
    global _JOB
    out = Path(outdir).expanduser().resolve()
    try:
        out.mkdir(parents=True, exist_ok=True)
    except OSError:
        with _LOCK:
            if _JOB is not None:
                _JOB.update({"state": "failed", "running": False,
                             "error": "输出目录不可创建"})
        return
    processed = 0
    try:
        for idx, sid in enumerate(sids, 1):
            if _cancelled():
                break
            sub = store.get_sub(sid)
            if not sub:
                continue
            _add("log", "同步订阅 %d/%d：%s"
                 % (idx, len(sids), sub.get("name") or sub["url"][:40]),
                 (idx - 1) / len(sids))
            res = _sync_one(
                sub, outdir=out, kb_dir=kb_dir,
                discover_fn=discover_fn, download_fn=download_fn,
                transcribe_fn=transcribe_fn, ingest_fn=ingest_fn,
                iterate_fn=iterate_fn, refine_rounds=refine_rounds)
            if res.get("error") and not res.get("new_ids"):
                store.update_result(sid, error=res["error"])
                _add("error", "订阅失败：%s" % res["error"])
            elif res.get("ok"):
                merged = sorted(set(sub.get("seen_ids") or []) |
                                set(res.get("new_ids") or []))
                store.update_result(sid, seen_ids=merged,
                                    new_count=int(res.get("new_count") or 0))
            processed += 1
        with _LOCK:
            if _JOB is not None:
                _JOB["state"] = "cancelled" if _cancelled() else "done"
                _JOB["processed"] = processed
        _add("log", "订阅同步完成", 1.0)
    except Exception as exc:
        with _LOCK:
            if _JOB is not None:
                _JOB.update({"state": "failed",
                             "error": "订阅同步异常：%s" % type(exc).__name__})
        _add("error", "订阅同步异常：%s" % type(exc).__name__)
    finally:
        with _LOCK:
            if _JOB is not None:
                _JOB["running"] = False


def start(sids: list[str], outdir: str, kb_dir, *, refine_rounds: int = 1,
          discover_fn=None, download_fn=None, transcribe_fn=None,
          ingest_fn=None, iterate_fn=None, refresh: bool = False) -> dict:
    """启动一次订阅同步（立即返回，后台线程执行）。

    默认注入真实实现；测试可替换任一 fn。返回 ``{ok, started, total}``。
    """
    global _JOB
    with _LOCK:
        if _JOB is not None and _JOB.get("running"):
            return {"ok": False, "error": "已有订阅同步在运行，请等待或取消"}
    ids = [str(x) for x in (sids or []) if str(x).strip()]
    if not ids:
        return {"ok": False, "error": "请先选择要同步的订阅"}
    if not str(outdir or "").strip():
        return {"ok": False, "error": "请先指定输出目录"}
    cap = channel_discovery.capability()
    if not cap["enabled"]:
        return {"ok": False, "capability": "unavailable", "error": cap["reason"]}

    d_fn = discover_fn or (lambda url, **kw: channel_discovery.discover(url, **kw))
    dl_fn = download_fn or (lambda url, tmp, **kw:
                            link_downloader.run_download(url, Path(tmp), **kw))
    tr_fn = transcribe_fn or (lambda files, out: video_transcribe.transcribe(files, out))
    ing_fn = ingest_fn or (lambda kd, md, **kw: kb.ingest_md(kd, md, **kw))

    with _LOCK:
        _JOB = {"state": "running", "running": True, "cancelled": False,
                "events": [], "error": None, "processed": 0, "total": len(ids)}
    threading.Thread(
        target=_run,
        args=(ids, outdir, kb_dir),
        kwargs={"discover_fn": d_fn, "download_fn": dl_fn,
                "transcribe_fn": tr_fn, "ingest_fn": ing_fn,
                "iterate_fn": iterate_fn, "refine_rounds": refine_rounds},
        daemon=True, name="jinghe-subscription").start()
    return {"ok": True, "started": True, "total": len(ids)}


def start_due(outdir: str, kb_dir, **kwargs) -> dict:
    """同步所有到期的订阅（应用内调度器调用；手动「全部同步」也可复用）。"""
    due = store.due_subs()
    if not due:
        return {"ok": False, "error": "当前没有到期的订阅"}
    return start([s["id"] for s in due], outdir, kb_dir, **kwargs)


def status(since: int = 0) -> dict:
    with _LOCK:
        if _JOB is None:
            return {"state": "idle", "running": False, "events": [], "next": 0,
                    "error": None, "processed": 0, "total": 0}
        events = [e for e in _JOB["events"] if e["i"] > since]
        return {"state": _JOB["state"], "running": _JOB["running"],
                "events": events,
                "next": events[-1]["i"] if events else since,
                "error": _JOB.get("error"),
                "processed": _JOB.get("processed", 0),
                "total": _JOB.get("total", 0)}


def cancel() -> dict:
    with _LOCK:
        if _JOB is None or not _JOB.get("running"):
            return {"ok": True, "cancelled": False}
        _JOB["cancelled"] = True
        return {"ok": True, "cancelled": True}
