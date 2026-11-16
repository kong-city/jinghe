#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精核 · 精读 / 修订能力地基（S7a · 阶段 2 后处理层）。

用户已定功能定义（2026-11-16）：
* **精读**：对已转换为 md 的文件做语义级「提纯核心知识点」（只提纯，不补写）；
* **修订**：对核心知识点做「补写缺失 + 修改已有内容」，且新增 / 修改内容须样式区分。

本模块是 **S7a 地基**：只做能力声明、本机大模型探测、来源只读检查与诚实降级，
**不写真调模型的逻辑**（留 S7b / S7c）。任何真实推理调用在 S7a 阶段必须显式报错，
绝不静默返回假结果、不产出伪文档。

架构裁决（与 S1–S4 一致）：
* 这是 phase-2 后处理层独立 handler，``extract.py`` 主流水线与 ``SPEC.md`` 一字不动；
* ollama 探测**独立挂** ``capability()['tools']['ollama']``，
  **绝不并入 ``media_tools.TOOL_SPECS``**（S1 契约锁死 3 工具 + 占位清单）；
* 真实状态走 ``/api/tools/probe`` **顶层增量字段 ``refine``**，不改 tools 结构；
* 产物只落 ``out/derived/``，与冻结对账盘（out/md、INDEX、MERGED）严格隔离。
"""
from __future__ import annotations

import re
import time
from pathlib import Path

import media_runtime
import backend  # S7b：可插拔多后端适配层（Local ollama / Cloud OpenAI兼容）
import revise_engine as _revise  # S7c：修订双产物（md 符号标记 + html 彩色）

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #
CAPABILITY_NAME = "refine"
DEFAULT_MODEL = ""            # 不预设模型；由当前后端的 list_models() 读取

MAX_BYTES = 8 * 1024 * 1024   # 单 md 上限 8MB（与 word_export 一致）
MAX_LINES = 20000             # 单 md 上限 2 万行

# 精读 / 修订产物后缀（契约 §4.1）
REFINE_SUFFIX = ".refine.md"
REVISE_MD_SUFFIX = ".revise.md"
REVISE_HTML_SUFFIX = ".revise.html"
PROVENANCE_NAME = "provenance_refine.json"

# 修订产物的双标记语法（契约 §4.3）；与 html 彩色样式同源渲染，S7a 只声明不渲染
MD_ADD_OPEN, MD_ADD_CLOSE = "[++ ", " ++]"
MD_MOD_OPEN, MD_MOD_MID, MD_MOD_CLOSE = "[[~~ ", " ~~ → ", "]]"

# 能力状态字符串
STATUS_UNAVAILABLE = "unavailable"


# --------------------------------------------------------------------------- #
# 能力探测：ollama 独立 tools 子结构，绝不进 TOOL_SPECS / capabilities()
# --------------------------------------------------------------------------- #
def capability(refresh: bool = False) -> dict:
    """/api/tools/probe 的顶层增量字段 refine（S7b 可插拔多后端版）。

    S1 的 media_tools.capabilities() 是被 test_33 锁死的占位清单，恒 enabled=False；
    S7 的真实状态只走本字段（与 S2a/S2b/S3/S4 同一裁决）。

    后端（方案 C）：客户在 backend.json 自选 Local(ollama) / Cloud(OpenAI兼容)，
    未配置或探测失败 → enabled=False + 可读原因，UI 显示「未启用」，零产物。
    本模块只探测、不下载、不打包、不自动安装任何组件。
    """
    be = backend.probe_current(refresh=refresh)
    available = bool(be.get("available"))
    kind = be.get("kind", backend.KIND_NONE)
    missing = [] if available else [kind if kind != backend.KIND_NONE else "backend"]
    return {
        "name": CAPABILITY_NAME,
        "enabled": available,
        "capability": "available" if available else STATUS_UNAVAILABLE,
        "engine": {
            "name": "可插拔大模型后端（Local ollama / Cloud 兼容端点，均未随软件分发）",
            "reason": ("精读提纯与修订增修由客户自选后端完成；本地后端不出本机、"
                       "云端后端需客户配置即知情同意；软件不下载/不打包/不自动安装"),
        },
        "tools": {"backend": be},
        "missing": missing,
        "reason": ("可用" if available else be.get("reason", "未启用：尚未配置精读后端")),
        "input": {"suffix": ".md", "max_bytes": MAX_BYTES, "max_lines": MAX_LINES},
        "output": {
            "dirname": media_runtime.DERIVED_DIRNAME,
            "refine_suffix": REFINE_SUFFIX,
            "revise_md_suffix": REVISE_MD_SUFFIX,
            "revise_html_suffix": REVISE_HTML_SUFFIX,
            "provenance": PROVENANCE_NAME,
        },
        "stages": {
            "refine": "提纯核心知识点（只提纯，不补写）",
            "revise": "对核心补写缺失 + 修改已有，新增/修改须样式区分",
        },
        "note": ("精读/修订产物只落 derived/；绝不写 out/md、INDEX.md、MERGED.md；"
                 "S7b 仅适配层，真实推理调用将在后续阶段接入"),
    }


def listed_models(refresh: bool = False) -> dict:
    """列出当前后端可用模型（经 Backend.list_models()，绝不编造模型名）。"""
    cap = capability(refresh=refresh)
    if not cap["enabled"]:
        return {"ok": False, "capability": STATUS_UNAVAILABLE,
                "models": [], "error": cap["reason"]}
    return backend.list_models_current(refresh=refresh)


# --------------------------------------------------------------------------- #
# 来源只读检查（S7a 骨架）
# --------------------------------------------------------------------------- #
def check_source(path: str) -> dict:
    """只读检查一个 md 是否可作为精读来源；不修改任何文件。

    S7a 只做存在性 / 后缀 / 大小 / 行数检查，不调用模型、不产出任何文档。
    """
    base = {"ok": False, "status": "failed", "path": "", "size": 0,
            "lines": 0, "error": ""}
    raw = (path or "").strip()
    if not raw:
        base["error"] = "请先选择已转换的 md 文件"
        return base
    p = Path(raw)
    if not p.is_file():
        base["error"] = "文件不存在：%s" % raw
        return base
    if p.suffix.lower() != ".md":
        base["error"] = "只接受 .md 文件：%s" % p.name
        return base
    try:
        size = p.stat().st_size
    except OSError as exc:
        base["error"] = "读取文件信息失败：%s" % exc
        return base
    if size > MAX_BYTES:
        base["error"] = "文件超过 %dMB 上限，请拆分后重试" % (MAX_BYTES // 1024 // 1024)
        return base
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        base["error"] = "读取文件失败：%s" % exc
        return base
    lines = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
    if not text.strip():
        base["error"] = "文件内容为空，无可提纯的核心"
        return base
    if lines > MAX_LINES:
        base["error"] = "文件超过 %d 行上限，请拆分后重试" % MAX_LINES
        base["lines"] = lines
        base["size"] = size
        return base
    base.update({"ok": True, "status": "ok", "path": str(p),
                 "size": size, "lines": lines})
    return base


def inspect(path: str, refresh: bool = False) -> dict:
    """POST /api/refine/inspect：来源检查 + 能力状态，全程只读。"""
    cap = capability(refresh=refresh)
    result = check_source(path)
    return {
        "ok": result["ok"],
        "capability": cap["capability"],
        "enabled": cap["enabled"],
        "source": result,
        "reason": cap["reason"] if not cap["enabled"] else result["error"],
    }


# --------------------------------------------------------------------------- #
# 轻量任务状态（自洽，不依赖 app.py 的 Job，避免循环 import）
# --------------------------------------------------------------------------- #
import threading as _threading
import refine_engine as _engine

_TASK_LOCK = _threading.Lock()
_TASK: dict | None = None


def _task_add(etype: str, text: str, progress: float | None = None) -> dict:
    with _TASK_LOCK:
        if _TASK is None:
            return {}
        ev = {"i": len(_TASK["events"]) + 1, "type": etype, "text": text}
        if progress is not None:
            ev["progress"] = round(float(progress), 4)
        _TASK["events"].append(ev)
        return ev


def _run_refine(path: str, model: str, outdir: str, backend_obj, cap: dict) -> None:
    """线程 wrapper：无论成功/失败/取消，结束时都清 running 标志。"""
    global _TASK
    try:
        _run_refine_inner(path, model, outdir, backend_obj, cap)
    finally:
        with _TASK_LOCK:
            if _TASK is not None:
                _TASK["running"] = False


def _run_refine_inner(path: str, model: str, outdir: str, backend_obj, cap: dict) -> None:
    """提纯任务线程体：全程只读源 md，产物只落 derived/。"""
    global _TASK
    try:
        _task_add("log", "开始读取源 md", 0.05)
        src = Path(path)
        text = src.read_text(encoding="utf-8", errors="replace")

        blocks = _engine.split_blocks(text)
        _task_add("log", "源文档分为 %d 块" % len(blocks), 0.15)
        if not blocks:
            _task_add("error", "无可提纯内容", 1.0)
            with _TASK_LOCK:
                _TASK["state"] = "failed"
                _TASK["error"] = "无可提纯内容"
            return

        with _TASK_LOCK:
            if _TASK["cancelled"]:
                _TASK["state"] = "cancelled"
                return

        _task_add("log", "调用后端提纯…", 0.3)
        prompt = _engine.build_prompt(blocks)
        try:
            response = backend_obj.chat([
                {"role": "system", "content": "你是文档提纯助手，只输出 JSON。"},
                {"role": "user", "content": prompt},
            ])
        except NotImplementedError:
            raise
        except Exception as exc:
            # 异常文案不打印可能含 key 的细节；只报类型
            _task_add("error", "后端调用失败：%s" % type(exc).__name__, 1.0)
            with _TASK_LOCK:
                _TASK["state"] = "failed"
                _TASK["error"] = "后端调用失败：%s" % type(exc).__name__
            return

        points, skipped = _engine.parse_points(response, blocks)
        _task_add("log", "校验核心：有效 %d 条，丢弃 %d 条" % (len(points), skipped), 0.7)

        # 红线：全无效 → 零产物，不写空壳
        if not points:
            _task_add("error", "无有效核心（锚点校验后为空），未产出文档", 1.0)
            with _TASK_LOCK:
                _TASK["state"] = "failed"
                _TASK["error"] = "无有效核心，未产出文档"
            return

        with _TASK_LOCK:
            if _TASK["cancelled"]:
                _TASK["state"] = "cancelled"
                return

        # 冻结对账盘只读快照
        before = media_runtime.frozen_snapshot(outdir)
        meta = {
            "block_count": len(blocks),
            "skipped": skipped,
            "backend_kind": cap["tools"]["backend"].get("kind", ""),
            "model": model or "后端默认",
            "converter": "可插拔后端（%s）" % cap["tools"]["backend"].get("kind", "?"),
        }
        md_text, doc_id = _engine.render_md(src, points, meta)
        target = media_runtime.ensure_derived(outdir) / (doc_id + REFINE_SUFFIX)
        target.write_text(md_text, encoding="utf-8")
        _engine.append_provenance(outdir, {
            "capability": "refine", "stage": "refine", "doc_id": doc_id,
            "source": src.name, "backend": meta["backend_kind"], "model": meta["model"],
            "points": len(points), "skipped": skipped,
            "output": target.name, "status": "成功",
        })
        frozen_ok = media_runtime.frozen_unchanged(before, outdir)
        _task_add("log", "产物：%s" % target.name, 0.95)
        with _TASK_LOCK:
            _TASK["state"] = "done" if frozen_ok else "failed"
            _TASK["output"] = str(target)
            _TASK["error"] = None if frozen_ok else "冻结对账盘被改动（异常）"
        _task_add("log", "完成" if frozen_ok else "冻结盘校验失败", 1.0)
    except Exception as exc:
        with _TASK_LOCK:
            _TASK["state"] = "failed"
            _TASK["error"] = "提纯失败：%s" % type(exc).__name__
        _task_add("error", "提纯失败：%s" % type(exc).__name__, 1.0)


def start_refine(path: str, model: str = DEFAULT_MODEL, outdir: str = "",
                 refresh: bool = False) -> dict:
    """POST /api/refine/start：校验后启动提纯线程，立即返回。"""
    global _TASK
    cap = capability(refresh=refresh)
    if not cap["enabled"]:
        return {"ok": False, "capability": STATUS_UNAVAILABLE,
                "error": cap["reason"]}
    chk = check_source(path)
    if not chk["ok"]:
        return {"ok": False, "capability": cap["capability"],
                "error": chk["error"], "source": chk}
    out = Path(outdir) if outdir else Path(path).resolve().parent
    with _TASK_LOCK:
        if _TASK is not None and _TASK["running"]:
            return {"ok": False, "error": "已有精读任务在运行，请等待或取消"}
        _TASK = {"state": "running", "running": True, "cancelled": False,
                 "events": [], "output": "", "error": None}
    be = backend.current_backend()
    t = _threading.Thread(target=_run_refine,
                          args=(chk["path"], model, str(out), be, cap),
                          daemon=True)
    t.start()
    return {"ok": True, "capability": cap["capability"], "started": True}


def _run_revise_inner(path: str, model: str, outdir: str, backend_obj,
                      cap: dict, instruction: str = "") -> None:
    """修订任务线程体：读 .refine.md 核心 → 调后端补写/修改 → 双产物同源渲染。"""
    global _TASK
    try:
        _task_add("log", "读取精读核心…", 0.05)
        src = Path(path)
        text = src.read_text(encoding="utf-8", errors="replace")
        cores = _revise.parse_core(text)
        _task_add("log", "解析到 %d 条核心" % len(cores), 0.15)
        if not cores:
            _task_add("error", "精读文档无可修订的核心", 1.0)
            with _TASK_LOCK:
                _TASK["state"] = "failed"
                _TASK["error"] = "精读文档无可修订的核心"
            return

        with _TASK_LOCK:
            if _TASK["cancelled"]:
                _TASK["state"] = "cancelled"
                return

        _task_add("log", "调用后端修订…", 0.35)
        try:
            response = backend_obj.chat([
                {"role": "system", "content": "你是文档修订助手，只输出 JSON。"},
                {"role": "user", "content": _revise.build_prompt(cores, instruction)},
            ])
        except Exception as exc:
            _task_add("error", "后端调用失败：%s" % type(exc).__name__, 1.0)
            with _TASK_LOCK:
                _TASK["state"] = "failed"
                _TASK["error"] = "后端调用失败：%s" % type(exc).__name__
            return

        changes, skipped = _revise.parse_changes(response, cores)
        _task_add("log", "校验变更：有效 %d 条，丢弃 %d 条" % (len(changes), skipped), 0.65)
        if not changes:
            _task_add("error", "无有效修订（锚点校验后为空），未产出文档", 1.0)
            with _TASK_LOCK:
                _TASK["state"] = "failed"
                _TASK["error"] = "无有效修订，未产出文档"
            return

        # doc_id 从精读产物名提取（doc_xxx.refine.md），保证与精读同一 id
        m = re.search(r"(doc_[0-9a-f]{12})", src.name)
        doc_id = m.group(1) if m else "doc_" + media_runtime.source_info(src)["doc_id"][4:16]
        meta = {
            "stem": src.name.split(".")[0],
            "doc_id": doc_id,
            "backend_kind": cap["tools"]["backend"].get("kind", ""),
            "model": model or "后端默认",
            "skipped": skipped,
        }
        md_text, html_text = _revise.render_both(cores, changes, meta)
        # 红线：交付前逐条校验标记完整性，对不上零产物
        ok, why = _revise.verify_marks(changes, md_text, html_text)
        if not ok:
            _task_add("error", "标记完整性校验失败：%s" % why, 1.0)
            with _TASK_LOCK:
                _TASK["state"] = "failed"
                _TASK["error"] = "标记完整性校验失败：%s" % why
            return

        before = media_runtime.frozen_snapshot(outdir)
        derived = media_runtime.ensure_derived(outdir)
        md_path = derived / (doc_id + REVISE_MD_SUFFIX)
        html_path = derived / (doc_id + REVISE_HTML_SUFFIX)
        md_path.write_text(md_text, encoding="utf-8")
        html_path.write_text(html_text, encoding="utf-8")
        _engine.append_provenance(outdir, {
            "capability": "refine", "stage": "revise", "doc_id": doc_id,
            "source": src.name, "backend": meta["backend_kind"], "model": meta["model"],
            "changes": len(changes), "skipped": skipped,
            "outputs": [md_path.name, html_path.name], "status": "成功",
        })
        frozen_ok = media_runtime.frozen_unchanged(before, outdir)
        _task_add("log", "产物：%s + %s" % (md_path.name, html_path.name), 0.95)
        with _TASK_LOCK:
            _TASK["state"] = "done" if frozen_ok else "failed"
            _TASK["output"] = str(md_path)
            _TASK["error"] = None if frozen_ok else "冻结对账盘被改动（异常）"
        _task_add("log", "完成" if frozen_ok else "冻结盘校验失败", 1.0)
    except Exception as exc:
        with _TASK_LOCK:
            _TASK["state"] = "failed"
            _TASK["error"] = "修订失败：%s" % type(exc).__name__
        _task_add("error", "修订失败：%s" % type(exc).__name__, 1.0)


def start_revise(path: str, model: str = DEFAULT_MODEL, outdir: str = "",
                 instruction: str = "", refresh: bool = False) -> dict:
    """POST /api/revise/start：校验后启动修订线程（输入为 .refine.md），立即返回。"""
    global _TASK
    cap = capability(refresh=refresh)
    if not cap["enabled"]:
        return {"ok": False, "capability": STATUS_UNAVAILABLE, "error": cap["reason"]}
    chk = check_source(path)
    if not chk["ok"]:
        return {"ok": False, "capability": cap["capability"], "error": chk["error"]}
    out = Path(outdir) if outdir else Path(path).resolve().parent
    with _TASK_LOCK:
        if _TASK is not None and _TASK["running"]:
            return {"ok": False, "error": "已有精读/修订任务在运行"}
        _TASK = {"state": "running", "running": True, "cancelled": False,
                 "events": [], "output": "", "error": None}
    be = backend.current_backend()
    t = _threading.Thread(
        target=_revise_run_wrapped,
        args=(chk["path"], model, str(out), be, cap, instruction),
        daemon=True)
    t.start()
    return {"ok": True, "capability": cap["capability"], "started": True}


def _revise_run_wrapped(path, model, outdir, be, cap, instruction):
    try:
        _run_revise_inner(path, model, outdir, be, cap, instruction)
    finally:
        with _TASK_LOCK:
            if _TASK is not None:
                _TASK["running"] = False


def status(since: int = 0) -> dict:
    """GET /api/refine/status：返回增量事件 + 任务状态。"""
    with _TASK_LOCK:
        if _TASK is None:
            return {"state": "idle", "running": False, "events": [], "next": 0,
                    "output": "", "error": None}
        events = [e for e in _TASK["events"] if e["i"] > since]
        return {"state": _TASK["state"], "running": _TASK["running"],
                "events": events,
                "next": events[-1]["i"] if events else since,
                "output": _TASK["output"], "error": _TASK["error"]}


def cancel() -> dict:
    """POST /api/refine/cancel：置取消标志（线程在检查点自行退出）。"""
    global _TASK
    with _TASK_LOCK:
        if _TASK is None or not _TASK["running"]:
            return {"ok": True, "cancelled": False}
        _TASK["cancelled"] = True
        return {"ok": True, "cancelled": True}

