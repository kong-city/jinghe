#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精核 · 精读提纯引擎（S7b 后半）。

职责：把「已转换的 md」提纯成结构化核心知识点，并**机检每条观点可回溯**。

反编造机制（本能力的红线）：
1. 先把源 md 切成编号块（block 1、2、3…），每块带原文；
2. prompt 要求模型只返回 JSON：``{"points":[{"text":"...","block":<块号>}]}``；
3. 解析后**逐条校验** block 是否为 1..N 的整数且对应块存在；
   * 无 block / block 越界 / 非整数 / text 为空 → **丢弃该条**；
   * 全部被丢弃 / 解析失败 / 空输出 → **零产物**（不写空壳文档）。
4. 产物每条核心都带 ``block_anchor``，指向它引用的源块，人工可核对。

**诚实边界**：块号有效只能保证「观点挂靠到某个真实块」，不能 100% 保证
「观点内容确实出自该块」（模型可能张冠李戴）。因此产物显式标注
「核心由模型提纯，请对照原文核对」，不假装零幻觉。

阶段边界：本引擎不直接发起模型调用（不 import backend 的 chat 执行），
只提供 ``build_prompt`` / ``parse_points`` / ``render_md`` 三个纯函数，
由 refine.py 的 Job 调用 Backend.chat()。这样可用 mock Backend 完整验证。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import media_runtime

# 提纯产物后缀与 provenance（与 refine.py 契约一致）
REFINE_SUFFIX = ".refine.md"
PROVENANCE_NAME = "provenance_refine.json"
SCHEMA = "jinghe.refine.provenance.v1"

# 单块最大字符数：避免把超长 md 一次性塞进 prompt（截断块，但保留编号）
MAX_BLOCK_CHARS = 1200
MAX_BLOCKS_IN_PROMPT = 120


# --------------------------------------------------------------------------- #
# 1. 分块
# --------------------------------------------------------------------------- #
def split_blocks(md_text: str) -> list[dict]:
    """把 md 切成编号块：**每个标题、每个正文段各自成块**。

    块越细，锚点越精确——模型引用的 block 能落到具体段落，人工核对更容易。
    返回 ``[{"n": 1, "text": "..."}, ...]``，n 从 1 开始（与 block_anchor 一致）。
    """
    blocks: list[dict] = []

    def add(text: str):
        text = text.strip()
        if text and len(blocks) < MAX_BLOCKS_IN_PROMPT:
            blocks.append({"n": len(blocks) + 1,
                           "text": text[:MAX_BLOCK_CHARS]})

    for raw in md_text.splitlines():
        s = raw.strip()
        if not s:
            continue
        if s.startswith("#"):
            add(s)          # 标题单独成块
        else:
            add(s)          # 每个非空行/段落单独成块
        if len(blocks) >= MAX_BLOCKS_IN_PROMPT:
            break
    return blocks


# --------------------------------------------------------------------------- #
# 2. 构造 prompt
# --------------------------------------------------------------------------- #
def build_prompt(blocks: list[dict]) -> str:
    """构造提纯 prompt：要求结构化 JSON，且每条观点必须带有效块号。"""
    lines = [
        "你是文档提纯助手。下面是一份文档的分块（每块有编号）。",
        "请提炼核心知识点，严格按以下 JSON 格式输出，不要输出任何多余文字：",
        '{"points": [{"text": "核心观点（一句话）", "block": 块号}, ...]}',
        "硬性要求：",
        "1. block 必须是下面给出的块编号之一（整数），不得编造新编号；",
        "2. 每条观点必须能在对应块中找到依据，不确定就宁可不输出；",
        "3. 只保留真正核心的内容，一般 3-10 条；没有可提纯内容就输出 {\"points\": []}；",
        "4. 不要补充原文没有的知识，不要改写数字、人名、结论。",
        "",
        "文档分块：",
    ]
    for b in blocks:
        lines.append("[块 %d] %s" % (b["n"], b["text"]))
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 3. 解析 + 校验（反编造核心）
# --------------------------------------------------------------------------- #
def _strip_fence(text: str) -> str:
    """宽松去掉模型常见的 ```json ... ``` 包裹。"""
    s = (text or "").strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", s, re.S | re.I)
    return m.group(1).strip() if m else s


def parse_points(response_text: str, blocks: list[dict]) -> tuple[list[dict], int]:
    """解析模型响应并逐条校验块引用。

    返回 ``(有效观点列表, 丢弃条数)``。校验规则：
    * JSON 解析失败 / 结构不符 → 返回 ([], 0)，上层判零产物；
    * 每条 point 必须有非空 text + 合法整数 block（1..N）；
    * block 越界 / 非整数 / text 空 → 丢弃并计数。
    """
    raw = _strip_fence(response_text)
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return [], 0
    if not isinstance(data, dict) or not isinstance(data.get("points"), list):
        return [], 0

    valid_nums = {b["n"] for b in blocks}
    kept: list[dict] = []
    skipped = 0
    for item in data["points"]:
        if not isinstance(item, dict):
            skipped += 1
            continue
        text_val = item.get("text")
        block_val = item.get("block")
        # block 必须是整数（布尔是 int 子类，要排除），且在有效块集合内
        if isinstance(block_val, bool) or not isinstance(block_val, int):
            skipped += 1
            continue
        if block_val not in valid_nums:
            skipped += 1
            continue
        if not isinstance(text_val, str) or not text_val.strip():
            skipped += 1
            continue
        kept.append({"text": text_val.strip(), "block": block_val})
    return kept, skipped


# --------------------------------------------------------------------------- #
# 4. 渲染产物
# --------------------------------------------------------------------------- #
def render_md(src: Path, points: list[dict], meta: dict) -> tuple[str, str]:
    """渲染 `.refine.md`：8 字段来源注释 + 三区块 + 块级锚点。

    返回 ``(markdown文本, doc_id)``。每条核心观点带 block_anchor 指向源块。
    """
    info = media_runtime.source_info(src)
    doc_id = info["doc_id"]
    converter = meta.get("converter") or "可插拔后端（模型由客户配置）"
    comment = media_runtime.source_comment(
        src, ".md", converter, anchors=["block"])
    lines = [
        comment, "",
        "# %s · 精读（核心提纯）" % src.stem, "",
        "## 文档信息", "",
        "- 源文件：%s" % src.name,
        "- 大小：%d 字节" % info["size"],
        "- 生成时间：%s" % time.strftime("%Y-%m-%d %H:%M:%S"),
        "- 源块数：%d" % int(meta.get("block_count") or 0),
        "- 提纯核心条数：%d" % len(points),
        "",
        "> 核心由模型提纯，块级锚点指向原文对应块；请对照原文核对。",
        "", "## 核心知识点", "",
    ]
    for p in points:
        lines.append(media_runtime.block_anchor(doc_id, p["block"]))
        lines.append("- %s（来源块 %d）" % (p["text"], p["block"]))
        lines.append("")
    lines += [
        "## 提纯元数据", "",
        "- 转换器：%s" % converter,
        "- 后端类型：%s" % (meta.get("backend_kind") or "未标注"),
        "- 模型：%s" % (meta.get("model") or "未标注"),
        "- 丢弃的非法观点：%d" % int(meta.get("skipped") or 0),
        "- 源文件 sha256：%s" % info["sha256"],
        "- doc_id：%s" % doc_id,
        "- 产物区：out/derived/（不参与阶段 1 件数对账）",
        "",
    ]
    return "\n".join(lines), doc_id


# --------------------------------------------------------------------------- #
# 5. provenance_refine.json：读旧追加（独立文件，不动冻结 helper）
# --------------------------------------------------------------------------- #
def load_provenance(outdir: Path) -> dict:
    path = Path(outdir) / media_runtime.DERIVED_DIRNAME / PROVENANCE_NAME
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def append_provenance(outdir: Path, entry: dict) -> Path:
    """读旧追加，绝不覆盖 S7 之前的历史条目。"""
    old = load_provenance(outdir)
    entries = list(old.get("entries") or []) if isinstance(old.get("entries"), list) else []
    entries.append(entry)
    data = {
        "schema": SCHEMA,
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "entries": entries,
        "note": "精读/修订产物的独立出处清单；不参与阶段 1 件数对账",
    }
    target = media_runtime.ensure_derived(outdir) / PROVENANCE_NAME
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    return target
