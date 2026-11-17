#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精核 · 修订引擎（S7c）：补写缺失 + 修改核心，双产物同源渲染。

输入：精读产物 ``.refine.md`` 里的核心知识点（带块级锚点）。
输出：
* ``<doc_id>.revise.md``  —— 纯文本符号标记版（通用可读、可 diff）
* ``<doc_id>.revise.html`` —— 彩色样式版（查看用，内联 style 无外部依赖）

**单一真源 = 结构化变更列表**：每条变更 {type, block, text, ...}。
两份产物都由这份列表渲染，**不从其中一份反推另一份**——保证标记一致。

**红线**：
1. 每条变更必须挂靠有效核心块（block 在输入核心集合内），否则丢弃；
2. 交付前逐条校验：每条变更在 md 与 html 两份产物中都找到对应标记；
   对不上 → 判失败 → 零产物（绝不出现"改了却没标记"误导用户）；
3. 全无效变更 → 零产物，不写空壳；
4. 颜色达 WCAG AA（正文对比 ≥4.5:1）。

阶段边界：本模块只提供纯函数（parse / build_prompt / parse_changes /
render_both / verify），不发起模型调用；由 refine.py 的 Job 调 Backend.chat()。
"""
from __future__ import annotations

import html as _html
import json
import re
import time
from pathlib import Path

import media_runtime

REVISE_MD_SUFFIX = ".revise.md"
REVISE_HTML_SUFFIX = ".revise.html"

# md 符号标记（与 refine.py 契约 §4.3 一致）
MD_ADD_OPEN, MD_ADD_CLOSE = "[++ ", " ++]"
MD_MOD_OPEN, MD_MOD_MID, MD_MOD_CLOSE = "[[~~ ", " ~~ → ", "]]"
# S8：AI 补写（模型生成）专用标记 —— 与修订新增 `[++ ]` 物理区分
MD_AI_OPEN, MD_AI_CLOSE = "[AI ++ ", " ++]"

# html 颜色（WCAG AA：正文对白底 ≥4.5:1）
C_ADD_FG, C_ADD_BG = "#1F6B3B", "#EDF7F0"   # 新增绿字浅绿底
C_MOD_OLD = "#A32D2D"                       # 修改旧：红删除线
C_MOD_NEW = "#185FA5"                       # 修改新：蓝字
C_TEXT = "#1F1F1D"                          # 原文黑
# S8：AI 补写（模型生成）专用色 —— 警示性红系，与「修改」的蓝/红区分：
# 修改是对原文的调整，补写是原文之外的新增内容，性质不同、必须一眼可辨。
C_AI_FG, C_AI_BG = "#501313", "#FCEBEB"

_ANCHOR_RE = re.compile(r"<!--\s*anchor:\s*doc_[0-9a-f]{12}\s*\|\s*block:\s*(\d+)\s*-->")
_CORE_RE = re.compile(r"^-\s+(.*?)（来源块\s*(\d+)）\s*$")


# --------------------------------------------------------------------------- #
# 1. 从 .refine.md 解析核心观点（修订输入基线）
# --------------------------------------------------------------------------- #
def parse_core(md_text: str) -> list[dict]:
    """从精读产物解析核心：``[{"block": N, "text": "..."}, ...]``。

    **兼容两种产物格式**（S8 起精读有两种模式）：
    1. S7 LLM 产物：``- 文本（来源块 N）`` —— 块号来自行尾后缀；
    2. S8 抽取式产物：``- 文本`` —— 块号来自其上方的 ``anchor`` 注释。

    只认块号一致的核心，防止解析错位导致修订挂靠到错误块。
    """
    lines = md_text.splitlines()
    cores: list[dict] = []
    pending_anchor: int | None = None
    in_core_section = False
    for line in lines:
        stripped = line.strip()
        # 只解析「## 核心知识点」区块内的条目，避免把文档信息区的
        # `- 源文件：…` 之类列表项误当成核心
        if stripped.startswith("## "):
            in_core_section = (stripped == "## 核心知识点")
            pending_anchor = None
            continue
        if not in_core_section:
            continue
        m = _ANCHOR_RE.search(line)
        if m:
            pending_anchor = int(m.group(1))
            continue
        s = stripped
        if not s.startswith("- "):
            continue
        body = s[2:].strip()
        if not body:
            continue
        c = _CORE_RE.match(s)
        if c and pending_anchor is not None:
            # 格式 1：行尾带「（来源块 N）」，且必须与上方 anchor 一致
            text, block = c.group(1).strip(), int(c.group(2))
            if block == pending_anchor:
                cores.append({"block": block, "text": text})
            pending_anchor = None
            continue
        if pending_anchor is not None:
            # 格式 2：S8 抽取式产物，块号取自上方 anchor
            cores.append({"block": pending_anchor, "text": body})
            pending_anchor = None
    return cores


# --------------------------------------------------------------------------- #
# 2. prompt
# --------------------------------------------------------------------------- #
def build_prompt(cores: list[dict], instruction: str = "") -> str:
    """构造修订 prompt：补写缺失 + 修改核心，返回结构化变更列表 JSON。"""
    lines = [
        "你是文档修订助手。下面是文档的核心知识点（每条带块号）。",
        "请做两件事：① 对缺少必要内容的核心做补写；② 对表述不准的核心做修改。",
        "严格按以下 JSON 输出，不要多余文字：",
        '{"changes":['
        '{"type":"add","block":块号,"text":"补充的内容"},'
        '{"type":"modify","block":块号,"old":"原核心文本","text":"修改后的文本"}'
        ']}',
        "硬性要求：",
        "1. block 必须是下面给出的块号之一（整数），不得编造；",
        "2. type 只能是 add 或 modify；modify 的 old 必须与下面对应的原文一致；",
        "3. 补充/修改不得违背原文事实，不确定的不要写；",
        "4. 没有需要补写或修改的就输出 {\"changes\":[]}；",
    ]
    if instruction.strip():
        lines.append("用户额外要求：%s" % instruction.strip())
    lines += ["", "核心知识点："]
    for c in cores:
        lines.append("[块 %d] %s" % (c["block"], c["text"]))
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 3. 解析 + 校验变更列表（反编造 + 挂靠有效核心）
# --------------------------------------------------------------------------- #
def _strip_fence(text: str) -> str:
    s = (text or "").strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", s, re.S | re.I)
    return m.group(1).strip() if m else s


def parse_changes(response_text: str, cores: list[dict],
                  allow_suppplement: bool = True) -> tuple[list[dict], int]:
    """解析变更列表并校验：block 必须有效、type 合法、modify 的 old 匹配原文。

    S8：**补写开关真正生效** —— ``allow_suppplement=False`` 时，
    ``type="add"``（补写）类变更一律丢弃并计入 skipped。
    开关关闭就必须真的没有补写内容，而不是"提示用户去核对"。

    返回 ``(有效变更列表, 丢弃条数)``。
    """
    try:
        data = json.loads(_strip_fence(response_text))
    except (ValueError, TypeError):
        return [], 0
    if not isinstance(data, dict) or not isinstance(data.get("changes"), list):
        return [], 0

    by_block = {c["block"]: c["text"] for c in cores}
    kept: list[dict] = []
    skipped = 0
    for item in data["changes"]:
        if not isinstance(item, dict):
            skipped += 1
            continue
        block = item.get("block")
        typ = item.get("type")
        text = item.get("text")
        if (isinstance(block, bool) or not isinstance(block, int)
                or block not in by_block or typ not in ("add", "modify")
                or not isinstance(text, str) or not text.strip()):
            skipped += 1
            continue
        # 补写开关关闭 → 丢弃 add（补写）类变更
        if typ == "add" and not allow_suppplement:
            skipped += 1
            continue
        entry = {"type": typ, "block": block, "text": text.strip()}
        if typ == "modify":
            old = item.get("old")
            # modify 必须带 old，且要与原文核心一致（否则视为编造）
            if not isinstance(old, str) or old.strip() != by_block[block]:
                skipped += 1
                continue
            entry["old"] = old.strip()
        kept.append(entry)
    return kept, skipped


# --------------------------------------------------------------------------- #
# 4. 双产物同源渲染（单一真源 = changes）
# --------------------------------------------------------------------------- #
def _render_md(cores: list[dict], changes: list[dict], meta: dict) -> str:
    by_block = {c["block"]: c["text"] for c in cores}
    adds = [c for c in changes if c["type"] == "add"]
    mods = [c for c in changes if c["type"] == "modify"]

    lines = [
        "<!-- 精核 · 修订文档（符号标记版） -->",
        "<!-- 图例：[[~~ 原文 ~~ → 修改]] 模型修改 ｜ [AI ++ … ++] AI 补写（模型生成） ｜ 无标记 = 精读原文核心 -->",
        "",
        "# %s · 修订（补写 + 修改）" % meta.get("stem", "文档"),
        "",
        "## 文档信息", "",
        "- 生成时间：%s" % time.strftime("%Y-%m-%d %H:%M:%S"),
        "- 后端：%s ｜ 模型：%s" % (meta.get("backend_kind", "?"), meta.get("model", "?")),
        "- 修改：%d 条 ｜ AI 补写：%d 条 ｜ 丢弃非法变更：%d 条"
        % (len(mods), len(adds), int(meta.get("skipped", 0))),
        "",
    ]
    if adds:
        lines += [
            "> **本文件含模型生成内容**（AI 补写分区），仅供参考，请核对原文。",
            "",
        ]
    lines += [
        "> 标记内容由模型补写/修改，请对照原文核对。",
        "", "## 核心知识点（含修订）", "",
    ]
    for c in cores:
        lines.append(media_runtime.block_anchor(meta.get("doc_id", "doc_000000000000"), c["block"]))
        base = "- " + by_block[c["block"]]
        # 先写原文核心，再追加该块的**修改**标记（补写不进核心区）
        lines.append(base)
        for ch in changes:
            if ch["block"] != c["block"] or ch["type"] != "modify":
                continue
            lines.append("  " + MD_MOD_OPEN + ch["old"] + MD_MOD_MID
                         + ch["text"] + MD_MOD_CLOSE)
        lines.append("")
    # S8：AI 补写**独立分区**（物理隔离 + 强制标注 + 不声明块锚点）
    if adds:
        lines += [
            "## AI 补充（模型生成，请核对）", "",
            "> 以下内容由模型补写，**原文并不存在**，仅供补充参考；请自行核对。",
            "",
        ]
        for ch in adds:
            lines.append("- " + MD_AI_OPEN + ch["text"] + MD_AI_CLOSE)
        lines.append("")
    lines += ["## 修订元数据", "",
              "- 原文核心块数：%d" % len(cores),
              "- 标记语法：%s / %s / %s" % (MD_MOD_OPEN.strip(), MD_ADD_OPEN.strip(),
                                          MD_AI_OPEN.strip()),
              "- 产物区：out/derived/（不参与阶段 1 件数对账）", ""]
    return "\n".join(lines)


def _render_html(cores: list[dict], changes: list[dict], meta: dict) -> str:
    by_block = {c["block"]: c["text"] for c in cores}
    esc = _html.escape
    body: list[str] = []
    for c in cores:
        parts = ['<div class="core">', '<div class="base">%s</div>' % esc(by_block[c["block"]])]
        for ch in changes:
            if ch["block"] != c["block"] or ch["type"] != "modify":
                continue
            parts.append('<div class="mod-old">- %s</div>' % esc(ch["old"]))
            parts.append('<div class="mod-new">→ %s</div>' % esc(ch["text"]))
        parts.append("</div>")
        body.append("".join(parts))
    adds = [c for c in changes if c["type"] == "add"]
    mods = [c for c in changes if c["type"] == "modify"]
    # S8：AI 补写独立分区（与核心区物理分离）
    supp_html: list[str] = []
    if adds:
        supp_html.append('<h2 class="ai-h">AI 补充（模型生成，请核对）</h2>')
        supp_html.append('<div class="ai-note">以下内容由模型补写，<b>原文并不存在</b>，'
                         '仅供补充参考；请自行核对。</div>')
        for ch in adds:
            supp_html.append('<div class="ai-item">+ %s</div>' % esc(ch["text"]))
    style = (
        "body{font-family:system-ui,'Microsoft YaHei',sans-serif;max-width:860px;"
        "margin:40px auto;padding:0 20px;color:%s;line-height:1.7;font-size:14px}"
        "h1{font-size:22px;font-weight:600}h2{font-size:17px;font-weight:600;margin-top:28px}"
        ".note{background:#F4F6F8;border-left:3px solid %s;padding:10px 12px;font-size:13px}"
        ".warn{background:%s;border-left:3px solid %s;padding:10px 12px;font-size:13px;"
        "color:%s;margin:10px 0}"
        ".core{border:1px solid #E5E3DC;border-radius:8px;padding:12px 14px;margin:12px 0}"
        ".base{color:%s}"
        ".add{color:%s;background:%s;padding:4px 8px;border-radius:4px;margin-top:6px}"
        ".mod-old{color:%s;text-decoration:line-through;margin-top:6px}"
        ".mod-new{color:%s;margin-top:2px}"
        ".ai-h{color:%s;margin-top:34px;padding-top:14px;border-top:2px solid %s}"
        ".ai-note{background:%s;border-left:3px solid %s;padding:10px 12px;"
        "font-size:13px;color:%s}"
        ".ai-item{color:%s;background:%s;padding:8px 10px;border-radius:6px;"
        "margin:8px 0;border-left:3px solid %s}"
        ".legend span{margin-right:16px;font-size:13px}"
    ) % (C_TEXT, C_MOD_NEW, C_AI_BG, C_MOD_OLD, C_AI_FG, C_TEXT, C_ADD_FG, C_ADD_BG,
         C_MOD_OLD, C_MOD_NEW,
         C_AI_FG, C_MOD_OLD, C_AI_BG, C_MOD_OLD, C_AI_FG,
         C_AI_FG, C_AI_BG, C_MOD_OLD)
    warn = ('<div class="warn">本文件含模型生成内容（AI 补充分区），仅供参考，请核对原文。</div>'
            if adds else "")
    return "\n".join([
        "<!DOCTYPE html>", '<html lang="zh-CN"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        "<title>精核 · 修订预览</title><style>", style, "</style></head><body>",
        "<h1>精核 · 修订预览</h1>",
        '<div class="note">标记内容由模型补写/修改，<b>请对照原文核对</b>。'
        '后端：%s ｜ 模型：%s</div>' % (esc(str(meta.get("backend_kind", "?"))),
                                    esc(str(meta.get("model", "?")))),
        warn,
        '<h2>图例</h2><div class="legend">',
        '<span style="color:%s;text-decoration:line-through">修改前</span>' % C_MOD_OLD,
        '<span style="color:%s">修改后</span>' % C_MOD_NEW,
        ('<span style="color:%s">AI 补写（模型生成）</span>' % C_MOD_OLD) if adds else "",
        "</div>",
        "<h2>核心知识点（含修订）</h2>",
        *body,
        *supp_html,
        "<p>修改 %d 条 ｜ AI 补写 %d 条 ｜ 丢弃非法变更 %d 条</p>"
        % (len(mods), len(adds), int(meta.get("skipped", 0))),
        "</body></html>",
    ])


def render_both(cores: list[dict], changes: list[dict],
                meta: dict) -> tuple[str, str]:
    """由同一份 changes 渲染两份产物，返回 ``(md_text, html_text)``。"""
    return _render_md(cores, changes, meta), _render_html(cores, changes, meta)


# --------------------------------------------------------------------------- #
# 5. 标记完整性校验（红线 2）
# --------------------------------------------------------------------------- #
def verify_marks(changes: list[dict], md_text: str, html_text: str) -> tuple[bool, str]:
    """逐条校验每条变更在两份产物中都有对应标记；对不上则返回失败原因。

    S8：补写（add）项额外要求**物理隔离** —— 必须落在「AI 补充」分区内，
    且核心区里不得出现补写内容，避免模型生成物被误当成原文核心。
    """
    core_zone = md_text
    ai_zone = ""
    if "## AI 补充（模型生成，请核对）" in md_text:
        head, _, tail = md_text.partition("## AI 补充（模型生成，请核对）")
        core_zone = head
        ai_zone = tail
    for ch in changes:
        text = ch["text"]
        if ch["type"] == "add":
            frag = MD_AI_OPEN + text + MD_AI_CLOSE
            if frag not in md_text:
                return False, "md 缺 AI 补写标记：%s" % text[:20]
            if frag in core_zone:
                return False, "AI 补写内容混进了核心区：%s" % text[:20]
            if not ai_zone or frag not in ai_zone:
                return False, "AI 补写未落在独立分区：%s" % text[:20]
            if 'class="ai-item"' not in html_text:
                return False, "html 缺 AI 补写分区"
            if '">+ ' + _html.escape(text) + "</div>" not in html_text:
                return False, "html 缺 AI 补写标记：%s" % text[:20]
        else:
            frag = (MD_MOD_OPEN + ch["old"] + MD_MOD_MID + text + MD_MOD_CLOSE)
            if frag not in md_text:
                return False, "md 缺修改标记：%s" % text[:20]
            if ('- ' + _html.escape(ch["old"]) + "</div>") not in html_text:
                return False, "html 缺修改前标记：%s" % ch["old"][:20]
            if ('→ ' + _html.escape(text) + "</div>") not in html_text:
                return False, "html 缺修改后标记：%s" % text[:20]
    return True, ""
