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
import json
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
    mode = backend.load_config().get("mode", backend.MODE_EXTRACT)
    if mode == backend.MODE_EXTRACT:
        engine_name = "内置抽取式提纯引擎（零依赖离线，核心为原文原句）"
        engine_reason = ("可信提纯：抽取式核心提取 + 原文内改写，只用原文素材，"
                         "架构级保证不造假；无需安装、无需下载、无需配置")
    else:
        engine_name = "可插拔大模型后端（Local ollama / Cloud 兼容端点，均未随软件分发）"
        engine_reason = ("大模型提纯：精读提纯与修订由客户自选后端完成；本地后端不出本机、"
                         "云端后端需客户配置即知情同意；软件不下载/不打包/不自动安装")
    return {
        "name": CAPABILITY_NAME,
        "enabled": available,
        "capability": "available" if available else STATUS_UNAVAILABLE,
        "engine": {
            "name": engine_name,
            "reason": engine_reason,
            "mode": mode,
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
    """列出当前后端可用模型（经 Backend.list_models()，绝不编造模型名）。

    抽取式模式没有「模型」概念，但也不该回一句「尚未配置后端」误导用户 ——
    直接透传 ExtractBackend 的诚实说明。
    """
    cfg = backend.load_config(refresh=refresh)
    if cfg.get("mode", backend.MODE_EXTRACT) == backend.MODE_EXTRACT:
        return backend.ExtractBackend(cfg).list_models()
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
# 产物 doc_id 统一口径
# --------------------------------------------------------------------------- #
def _doc_id_of(src: Path) -> str:
    """产物 doc_id：优先沿用**源文件名**里的 doc_id，保持同一条产物链。

    修订输入是 ``<doc_id>.refine.md``，产物理应是 ``<doc_id>.revise.md``。
    若改用 refine.md 的**内容哈希**另算一个 id，用户按 doc_id 追产物链就会断
    （且与 LLM 路径「从文件名提取」的行为不一致）。取不到文件名 id 时
    才回退到内容哈希。
    """
    m = re.search(r"(doc_[0-9a-f]{12})", src.name)
    if m:
        return m.group(1)
    return media_runtime.source_info(src)["doc_id"]


# --------------------------------------------------------------------------- #
# 轻量任务状态（自洽，不依赖 app.py 的 Job，避免循环 import）
# --------------------------------------------------------------------------- #
import threading as _threading
import refine_engine as _engine
import extract_engine as _extract  # S8：抽取式可信提纯（纯标准库，零依赖）

# S8：抽取式默认入选核心条数
_EXTRACT_TOP_K = 8

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
    """提纯任务线程体：全程只读源 md，产物只落 derived/。

    S8：按 mode 分流——
    * ``extract``（默认）：内置抽取式，输出**原文原句**，架构级不造假；
    * ``llm``：走大模型后端，沿用 S7 的锚点校验路径。
    """
    global _TASK
    try:
        mode = backend.load_config().get("mode", backend.MODE_EXTRACT)
        if mode == backend.MODE_EXTRACT:
            _run_refine_extract(path, outdir, cap)
            return
        _run_refine_llm(path, model, outdir, backend_obj, cap)
    except Exception as exc:
        with _TASK_LOCK:
            _TASK["state"] = "failed"
            _TASK["error"] = "提纯失败：%s" % type(exc).__name__
        _task_add("error", "提纯失败：%s" % type(exc).__name__, 1.0)

    finally:
        # v1.0.7 修复：**运行标志必须复位**。
        # 旧实现只在外层 wrapper（_run_refine）里复位，若有调用方直接调
        # _run_refine_inner（测试与内嵌调用都会这样），任务结束后
        # _TASK["running"] 仍是 True → status() 永远显示「运行中」，
        # 且后续所有精读/修订都被「已有精读任务在运行」挡住 —— 典型
        # 「点了没反应」。这里在 inner 层也复位，形成双保险。
        with _TASK_LOCK:
            if _TASK is not None:
                _TASK["running"] = False


def _run_refine_extract(path: str, outdir: str, cap: dict) -> None:
    """S8 抽取式提纯：纯标准库、零依赖、输出原文原句。

    **红线**：产出前用 ``verify_traceable`` 逐条验证「可在原文逐字定位」，
    对不上即判失败、零产物 —— 这是抽取式「不可能造假」的机器可验证证明。
    """
    src = Path(path)
    _task_add("log", "读取源 md…", 0.08)
    with _TASK_LOCK:
        if _TASK is not None and _TASK.get("cancelled"):
            _TASK["state"] = "cancelled"
            return
    text = src.read_text(encoding="utf-8", errors="replace")
    _task_add("log", "抽取式提纯中（TF-ICF + TextRank + MMR）…", 0.35)
    result = _extract.extract_core(text, top_k=_EXTRACT_TOP_K)
    points = result.get("points") or []
    _task_add("log", "入选核心 %d 条" % len(points), 0.7)
    if not points:
        _task_add("error", "未选出有效核心，未产出文档", 1.0)
        with _TASK_LOCK:
            _TASK["state"] = "failed"
            _TASK["error"] = "未选出有效核心，未产出文档"
        return

    ok, why = _extract.verify_traceable(text, points)
    if not ok:
        _task_add("error", "可回溯校验失败：%s" % why, 1.0)
        with _TASK_LOCK:
            _TASK["state"] = "failed"
            _TASK["error"] = "可回溯校验失败：%s" % why
        return

    before = media_runtime.frozen_snapshot(outdir)
    meta = {
        "converter": "抽取式提纯（纯标准库，零依赖离线）",
        "mode": "可信提纯（抽取式）",
        "model": "—",
    }
    md_text, doc_id = _extract.render_md(src, result, meta)
    target = media_runtime.ensure_derived(outdir) / (doc_id + REFINE_SUFFIX)
    target.write_text(md_text, encoding="utf-8")
    _engine.append_provenance(outdir, {
        "capability": "refine", "stage": "refine", "doc_id": doc_id,
        "source": src.name, "backend": "extract", "model": "—",
        "points": len(points), "skipped": 0, "mode": "extract",
        "output": target.name, "status": "成功",
    })
    frozen_ok = media_runtime.frozen_unchanged(before, outdir)
    _task_add("log", "产物：%s" % target.name, 0.95)
    with _TASK_LOCK:
        _TASK["state"] = "done" if frozen_ok else "failed"
        _TASK["output"] = str(target)
        _TASK["error"] = None if frozen_ok else "冻结对账盘被改动（异常）"
    _task_add("log", "完成" if frozen_ok else "冻结盘校验失败", 1.0)


def _run_refine_llm(path: str, model: str, outdir: str, backend_obj, cap: dict) -> None:
    """S7 LLM 提纯路径（保留）：锚点校验 + 可选 AI 补写。"""
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

        # S8：AI 补写（**仅在开关开启时**）—— 独立分区、强制标注，不与原文核心混同
        supplement_lines: list[str] = []
        cfg = backend.load_config()
        if cfg.get("allow_suppplement") and cfg.get("mode") == backend.MODE_LLM:
            _task_add("log", "AI 补写已开启，生成补充内容…", 0.78)
            supp = _run_supplement(backend_obj, blocks, points)
            if supp:
                supplement_lines = supp
                _task_add("log", "补写 %d 条（已隔离标注）" % len(supp), 0.85)

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
        if supplement_lines:
            # 独立分区插在「提纯元数据」之前，物理隔离 + 显式告知
            md_text = _append_supplement(md_text, supplement_lines)
        target = media_runtime.ensure_derived(outdir) / (doc_id + REFINE_SUFFIX)
        target.write_text(md_text, encoding="utf-8")
        _engine.append_provenance(outdir, {
            "capability": "refine", "stage": "refine", "doc_id": doc_id,
            "source": src.name, "backend": meta["backend_kind"], "model": meta["model"],
            "points": len(points), "skipped": skipped,
            "supplement": len(supplement_lines),
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


def _run_supplement(backend_obj, blocks: list[dict],
                    points: list[dict]) -> list[str]:
    """S8：AI 补写 —— 由模型补上原文没有的内容。

    **诚实边界**：补写内容按定义不在原文里，因此：
    * **不声明块锚点**（它不对应任何原文块）—— 这是与原文核心最直观的区分；
    * 强制带 ``[AI ++ … ++]`` 标记（区别于 S7 修订的 ``[++ … ++]``）；
    * 失败不阻塞主流程（补写是可选增强，失败即无补写内容）。
    """
    if not blocks:
        return []
    body_lines = []
    for b in blocks[:120]:
        body_lines.append("[块 %d] %s" % (b["n"], b["text"]))
    core_lines = ["- %s" % p["text"] for p in points[:20]]
    prompt = "\n".join([
        "你是文档补写助手。下面是一份文档的分块与已提炼的核心。",
        "请补充文档中**明显缺失**的关键信息（定义、步骤、前置条件、边界说明）。",
        "严格输出 JSON：",
        '{"supplements":[{"text":"补充内容","reason":"为什么需要补充"}]}',
        "要求：只输出 JSON；没有明显缺失就输出 {\"supplements\":[]}；",
        "不要重复已有核心，不要编造具体数字、人名、日期。",
        "",
        "已提炼核心：",
    ] + core_lines + ["", "文档分块："] + body_lines)
    try:
        raw = backend_obj.chat([
            {"role": "system", "content": "你是文档补写助手，只输出 JSON。"},
            {"role": "user", "content": prompt},
        ])
    except Exception:
        return []   # 补写失败不影响主流程
    try:
        data = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", (raw or "").strip()))
    except (ValueError, TypeError):
        return []
    if not isinstance(data, dict) or not isinstance(data.get("supplements"), list):
        return []
    out: list[str] = []
    for item in data["supplements"]:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        reason = item.get("reason")
        reason = reason.strip() if isinstance(reason, str) and reason.strip() else "补充要点"
        out.append("[AI ++ %s ++]（%s）" % (text.strip(), reason))
        if len(out) >= 10:
            break
    return out


def _append_supplement(md_text: str, supplement_lines: list[str]) -> str:
    """把 AI 补写作为**独立分区**插到「提纯元数据」之前。

    物理隔离 + 头部显式告知，确保用户一眼能分清哪些是原文、哪些是模型写的。
    """
    if not supplement_lines:
        return md_text
    block = [
        "## AI 补充（模型生成，请核对）", "",
        "> 以下内容由模型补写，**原文并不存在**，仅供补充参考；请自行核对。",
        "",
    ] + supplement_lines + ["", ""]
    marker = "## 提纯元数据"
    if marker in md_text:
        head, _, tail = md_text.partition(marker)
        return head + "\n".join(block) + marker + tail
    return md_text + "\n" + "\n".join(block)


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
    # v1.0.7：不再退化到「源 md 的父目录」。
    # 旧 fallback 会把 derived/ 建在用户源文件旁边（桌面 / 项目目录里
    # 凭空多出 derived 子目录），且当源 md 位于 out/md 下时，产物会嵌进
    # **冻结对账盘**（out/md/derived/），下一轮修订再套一层
    # out/md/derived/derived/ —— 冻结盘被污染、INDEX.md 永不承认、永不清理。
    # 现在缺输出目录就明确报错，与其它能力（word_enhance 等）口径一致：
    # **绝不猜落点，绝不写到用户源目录旁边**。
    if not outdir:
        return {"ok": False, "error": "请先指定输出目录（本次提取的输出路径）"}
    out = Path(outdir)
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
    """修订任务线程体。

    S8：按 mode 分流——
    * ``extract``（默认）：**B 档原文内改写**（术语归一 / 合并去重 / 结构重排），
      只用原文素材，零依赖，架构级不造假；
    * ``llm``：沿用 S7 的补写 + 修改双产物路径（补写仍需开关开启）。
    """
    global _TASK
    try:
        mode = backend.load_config().get("mode", backend.MODE_EXTRACT)
        if mode == backend.MODE_EXTRACT:
            _run_revise_extract(path, outdir, cap)
            return
        _run_revise_llm(path, model, outdir, backend_obj, cap, instruction)
    except Exception as exc:
        with _TASK_LOCK:
            _TASK["state"] = "failed"
            _TASK["error"] = "修订失败：%s" % type(exc).__name__
        _task_add("error", "修订失败：%s" % type(exc).__name__, 1.0)

    finally:
        # v1.0.7：同 _run_refine_inner —— 运行标志必须复位（双保险）
        with _TASK_LOCK:
            if _TASK is not None:
                _TASK["running"] = False


def _run_revise_extract(path: str, outdir: str, cap: dict) -> None:
    """S8 B 档：原文内改写（**只动结构与措辞，不动事实**）。

    输入是精读产物 ``.refine.md`` 的核心清单；输出是改写后的核心清单
    （同源渲染 md + html 双产物），每条仍带块锚点与原文句。
    """
    src = Path(path)
    _task_add("log", "读取精读核心…", 0.1)
    with _TASK_LOCK:
        if _TASK is not None and _TASK.get("cancelled"):
            _TASK["state"] = "cancelled"
            return
    text = src.read_text(encoding="utf-8", errors="replace")
    cores = _revise.parse_core(text)
    _task_add("log", "解析到 %d 条核心" % len(cores), 0.25)
    if not cores:
        _task_add("error", "精读文档无可改写的核心", 1.0)
        with _TASK_LOCK:
            _TASK["state"] = "failed"
            _TASK["error"] = "精读文档无可改写的核心"
        return

    _task_add("log", "原文内改写（术语归一 / 合并去重 / 结构重排）…", 0.5)
    rewritten = _extract.rewrite_in_source(cores)

    # B 档红线：每个片段都必须在原文（精读产物）里找得到，不得引入新内容
    ok, why = _extract.verify_no_new_content(text, rewritten["points"])
    if not ok:
        _task_add("error", "改写校验失败：%s" % why, 1.0)
        with _TASK_LOCK:
            _TASK["state"] = "failed"
            _TASK["error"] = "改写校验失败：%s" % why
        return

    before = media_runtime.frozen_snapshot(outdir)
    meta = {
        "converter": "原文内改写（纯标准库，零依赖离线）",
        "mode": "原文内改写（抽取式）",
        "model": "—",
        # 沿用精读产物的同一个 doc_id：doc_A.refine.md → doc_A.revise.md
        "doc_id": _doc_id_of(src),
    }
    md_text, doc_id = _extract.render_md(src, rewritten, meta)
    stats = rewritten.get("stats") or {}
    derived = media_runtime.ensure_derived(outdir)
    md_path = derived / (doc_id + _revise.REVISE_MD_SUFFIX)
    html_path = derived / (doc_id + _revise.REVISE_HTML_SUFFIX)
    md_path.write_text(md_text, encoding="utf-8")
    html_path.write_text(_revise_simple_html(md_text, stats), encoding="utf-8")
    _engine.append_provenance(outdir, {
        "capability": "refine", "stage": "revise", "doc_id": doc_id,
        "source": src.name, "backend": "extract", "model": "—",
        "mode": "extract", "changes": len(rewritten["points"]),
        "merged": int(stats.get("merged") or 0),
        "outputs": [md_path.name, html_path.name], "status": "成功",
    })
    frozen_ok = media_runtime.frozen_unchanged(before, outdir)
    _task_add("log", "产物：%s + %s" % (md_path.name, html_path.name), 0.95)
    with _TASK_LOCK:
        _TASK["state"] = "done" if frozen_ok else "failed"
        _TASK["output"] = str(md_path)
        _TASK["error"] = None if frozen_ok else "冻结对账盘被改动（异常）"
    _task_add("log", "完成" if frozen_ok else "冻结盘校验失败", 1.0)


def _revise_simple_html(md_text: str, stats: dict) -> str:
    """B 档改写的 html 版：把 md 文本原样包进 html（无内联样式依赖外部文件）。"""
    import html as _h
    body = _h.escape(md_text)
    return "\n".join([
        "<!DOCTYPE html>", '<html lang="zh-CN"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        "<title>精核 · 原文内改写</title><style>",
        "body{font-family:system-ui,'Microsoft YaHei',sans-serif;max-width:860px;"
        "margin:40px auto;padding:0 20px;color:#1F1F1D;line-height:1.7;font-size:14px}",
        "pre{white-space:pre-wrap;word-break:break-word;background:#FBFCFE;"
        "border:1px solid #E5E3DC;border-radius:8px;padding:14px;font-size:12.5px}",
        "</style></head><body>",
        "<h1>精核 · 原文内改写</h1>",
        '<div style="background:#EAF3DE;border:1px solid #97C459;color:#27500A;'
        'padding:10px 12px;border-radius:8px;font-size:13px">'
        "本次改写只动结构与措辞，未改事实；每个片段可在原文逐字定位。"
        "（操作：%s，合并 %d 条）</div>"
        % ("、".join(stats.get("ops") or []), int(stats.get("merged") or 0)),
        "<pre>", body, "</pre></body></html>",
    ])


def _run_revise_llm(path: str, model: str, outdir: str, backend_obj,
                    cap: dict, instruction: str = "") -> None:
    """S7 LLM 修订路径（保留）：补写 + 修改双产物。"""
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

        # S8：补写开关真正生效 —— 关闭时 add（补写）类变更一律丢弃
        _cfg = backend.load_config()
        _allow_supp = bool(_cfg.get("allow_suppplement"))
        changes, skipped = _revise.parse_changes(response, cores,
                                                 allow_suppplement=_allow_supp)
        _task_add("log", "校验变更：有效 %d 条，丢弃 %d 条" % (len(changes), skipped), 0.65)
        if not changes:
            _task_add("error", "无有效修订（锚点校验后为空），未产出文档", 1.0)
            with _TASK_LOCK:
                _TASK["state"] = "failed"
                _TASK["error"] = "无有效修订，未产出文档"
            return

        # doc_id 沿用精读产物名里的 id（doc_xxx.refine.md → doc_xxx.revise.md），
        # 保证与精读同一 id、产物链不断
        doc_id = _doc_id_of(src)
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
    # v1.0.7：同 start_refine —— 缺输出目录明确报错，不退化到源文件旁
    if not outdir:
        return {"ok": False, "error": "请先指定输出目录（本次提取的输出路径）"}
    out = Path(outdir)
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

