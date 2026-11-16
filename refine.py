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

import time
from pathlib import Path

import media_runtime
import backend  # S7b：可插拔多后端适配层（Local ollama / Cloud OpenAI兼容）

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
# 真实推理调用：S7a 显式拒绝，绝不静默返回假结果
# --------------------------------------------------------------------------- #
def _not_implemented(stage: str) -> dict:
    return {
        "ok": False,
        "capability": STATUS_UNAVAILABLE,
        "error": ("%s 的真实推理将在后续阶段（S7b/S7c）接入；"
                  "S7a 仅交付能力地基，绝不产出伪文档" % stage),
    }


def start_refine(path: str, model: str = DEFAULT_MODEL, refresh: bool = False) -> dict:
    """POST /api/refine/start（S7a：能力检查后诚实拒绝真实推理）。"""
    cap = capability(refresh=refresh)
    if not cap["enabled"]:
        return {"ok": False, "capability": STATUS_UNAVAILABLE,
                "error": cap["reason"]}
    chk = check_source(path)
    if not chk["ok"]:
        return {"ok": False, "capability": cap["capability"],
                "error": chk["error"], "source": chk}
    return _not_implemented("精读提纯")


def start_revise(path: str, model: str = DEFAULT_MODEL, refresh: bool = False) -> dict:
    """POST /api/revise/start（S7a：能力检查后诚实拒绝真实推理）。"""
    cap = capability(refresh=refresh)
    if not cap["enabled"]:
        return {"ok": False, "capability": STATUS_UNAVAILABLE,
                "error": cap["reason"]}
    chk = check_source(path)
    if not chk["ok"]:
        return {"ok": False, "capability": cap["capability"],
                "error": chk["error"], "source": chk}
    return _not_implemented("修订增修")


def status() -> dict:
    """GET /api/refine/status（S7a：无长任务，恒空闲）。"""
    return {"state": "idle", "running": False, "events": [], "next": 0}


def cancel() -> dict:
    """POST /api/refine/cancel（S7a：无长任务可取消）。"""
    return {"ok": True, "cancelled": False, "note": "S7a 地基：当前无运行中的精读/修订任务"}
