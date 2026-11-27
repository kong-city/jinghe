# -*- coding: utf-8 -*-
"""PDF 文本版面后处理：断行重连 + 目录层级还原（独立模块，冻结内核零改动）。

背景（docs/CAPABILITY_CONTRACT.md §1）：
    extract.py 的探测 / 分流 / 提取 / 汇总 / 对账主流水线是冻结内核，一行不动。
    本模块作为 L4 后处理层，对**已提取出的文本**做两件事：

    1. reflow_lines()  —— PDF 物理断行把一句话切成两行时，重新连成一句；
    2. build_toc()     —— 从正文里识别「第X篇 / 第X章 / X.X 小节」的层级目录。

    只处理文本，不重新解析 PDF、不写 out/md/*.md（不污染阶段 1 对账）。

设计原则（保守优先，宁可漏连不可错连）：
    * 上一行以终止标点结尾 → 段落边界，绝不合并；
    * 上一行以「悬挂修饰语」结尾（的/了/和/与/为/把/被/从/对/以/逗号…）→ 强证据，合并；
    * 下一行以承接词开头 + 上一行非完整句 → 中等证据，合并；
    * 标题行 / 页码 / CIP 条目行 / 纯英数行 → 绝不参与合并；
    * 目录识别只认明确模式（第X篇/第X章/附录X/数字小节），不猜。
"""
from __future__ import annotations

import re
from typing import Iterable

# 行尾出现这些标点 → 句子已结束，不合并
# 含省略号/破折号（P2-7：实测「…沉默着什么也没有说……」被误合并）
_TERMINATORS = "。！？；：!?;:”』】》」』）)]…—～~\"'"
# 上一行以这些字/符号结尾 → 明显话没说完（悬挂修饰语），强证据合并
_DANGLING = set("，,、的和与并为把被从对以在是其所之而则即如虽然但当且或向让使给靠按照于关于通过")
# 下一行以这些**双字承接词**开头 → 中等证据。
# 注意：绝不能收单字（中/人/我/的…），它们是正常行首高频字，会造成大量错连
# （如「中国工信出版集团」「人类」被误并到上一行）。只收明确的句间连接词。
_CONTINUE_STARTS = (
    "然而", "但是", "不过", "因此", "所以", "于是", "并且", "而且", "以及",
    "同时", "另外", "例如", "比如", "其中", "此外", "否则", "换言之", "也就是说",
    "不仅如此", "与此", "对此", "因而", "从而", "进而", "继而", "可见", "事实上",
)
# 接近满行的阈值：PDF 栏宽切断的行通常 >= 30 字（本书 OCR 实测典型 34-37 字）。
# 段落自然结束的行往往明显更短，不会误触发。
_FULL_LINE_MIN = 30
# 连续合并上限：真实句子很少超过 3 个物理行，超过说明把多个段落连起来了
_MAX_MERGE_RUN = 3

# 标题模式：第X篇/第X章/附录X/数字小节/常见问题等
_CHAPTER_RE = re.compile(
    r"^\s*(第\s*[0-9一二三四五六七八九十百]+\s*[篇章部卷]\s*|附录\s*[A-Za-z0-9一二三四五六七八九十]+\s*)")
_SECTION_RE = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,2}){0,3})[\s、.．]")
_PAGE_RE = re.compile(r"^\s*\d{1,4}\s*$")
# 结构化字段行：CIP 版权页/版权声明里的独立字段，绝不能并到上一行。
# 实测 bug：「…即可使用」+「使用方法：在购书单…」被错误连成一句。
_STRUCTURED_LINE_RE = re.compile(
    r"^(?:使用方法|网址|电话|邮编|电子邮件|ISBN|开本|印张|字数|版次|印数|"
    r"定价|责任编辑|责任印制|书名原文|出版发行|印刷|中国版本图书馆|"
    r"Copyright|Original|Manning|Simplified|All rights|http|www\.)", re.I)
# 纯英数/符号行（CIP 条目、水印、英文书名）
_LATIN_ONLY_RE = re.compile(r"^[\x20-\x7e\u3000-\u303f\uff00-\uffef]+$")


def _is_title(line: str) -> bool:
    return bool(_CHAPTER_RE.match(line) or _SECTION_RE.match(line))


def _is_blocked(line: str) -> bool:
    """这些行绝不参与合并（标题 / 页码 / 结构化字段 / 纯英数 / 太短 / 水印）。"""
    if not line:
        return True
    if (_is_title(line) or _PAGE_RE.match(line)
            or _STRUCTURED_LINE_RE.match(line)
            or line.startswith(("<!--", "-->", "#", "##", "###"))):
        return True
    if len(line) < 6:
        return True
    if _LATIN_ONLY_RE.match(line) and not re.search(r"[\u4e00-\u9fff]", line):
        return True
    if re.search(r"(?:www\.|epubit|com\.cn|ptpress|manning\.com)", line, re.I):
        return True
    return False


def reflow_lines(text: str) -> str:
    """把 PDF 物理断行切开的句子重新连成连贯一句。

    只合并「强证据 + 中等证据」的行对，其余原样保留。空行视为段落边界。
    """
    lines = text.splitlines()
    out: list[str] = []
    merged_run = 0  # 当前已连续合并的行数（防止把整页连成一片）
    for raw in lines:
        line = raw.strip()
        if not line:
            if out and out[-1] != "":
                out.append("")
            merged_run = 0
            continue
        if not out or out[-1] == "":
            out.append(line)
            merged_run = 0
            continue
        # 下一行是短行且无终止标点 → 很可能是小节标题（如「快速分析和小结277」），
        # 不能被上一行的满行合并吞掉。
        if len(line) < 12 and line[-1] not in _TERMINATORS:
            out.append(line)
            merged_run = 0
            continue
        if merged_run >= _MAX_MERGE_RUN:
            out.append(line)
            merged_run = 0
            continue
        prev = out[-1]
        if _is_blocked(prev) or _is_blocked(line):
            out.append(line)
            continue
        if prev[-1] in _TERMINATORS:
            out.append(line)
            continue

        # 强证据①：上一行以悬挂修饰语 / 逗号结尾 → 话没说完
        dangling = prev[-1] in _DANGLING
        # 强证据②：上一行接近满行（PDF 物理断行的典型特征）且无终止标点。
        # 中文断行可切在词中间（「我感|到自己」「开|发人员」），只靠标点穷举
        # 覆盖不了；接近满行是排版学上判定「被栏宽切断」的可靠信号。
        full_line = len(prev) >= _FULL_LINE_MIN
        # 中等证据：下一行以明确的双字承接词开头（「然而」「因此」「以及」…）
        connective = line.startswith(_CONTINUE_STARTS)
        if dangling or full_line or connective:
            out[-1] = prev + line
            merged_run += 1
        else:
            out.append(line)
            merged_run = 0
    return "\n".join(out).strip() + "\n"


def build_toc(text: str, max_level: int = 3) -> list[dict]:
    """从文本识别目录层级，返回 [{level, title, line}]。

    level 1 = 篇/章/附录，level 2 = 数字小节，level 3 = 更细的数字小节。
    只认明确模式，识别不到就返回空列表（诚实降级，不猜目录）。
    同一标题在目录页 + 正文页眉重复出现时只保留首次出现的完整版本。
    """
    lines = text.splitlines()
    toc: list[dict] = []
    seen: set[str] = set()
    for i, raw in enumerate(lines):
        line = raw.strip()
        if not line:
            continue
        m = _CHAPTER_RE.match(line)
        if m:
            # 层级：篇/部/卷 = 1（顶层），章 = 2，附录 = 1
            head = m.group(1)
            level = 2 if re.search(r"[章]", head) else 1
            # 去掉尾部粘连的页码（如「第1章标题1」）
            title = re.sub(r"\d{1,4}\s*$", "", line).strip(" 　#")
            # 标题只有章号没名字时，尝试用下一短行补全（OCR 常拆成两行）
            if re.fullmatch(r"第\s*[0-9一二三四五六七八九十百]+\s*[篇章部卷]", title):
                nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
                if (nxt and len(nxt) <= 34 and not _PAGE_RE.match(nxt)
                        and re.search(r"[\u4e00-\u9fff]", nxt)):
                    title = title + " " + re.sub(r"\d{1,4}\s*$", "", nxt).strip()
            key = re.sub(r"\s+", "", title)
            if key and key not in seen:
                seen.add(key)
                toc.append({"level": level, "title": title, "line": i})
            continue
        m = _SECTION_RE.match(line)
        if m:
            depth = m.group(1).count(".") + 1
            title = re.sub(r"\d{1,4}\s*$", "", line).strip()
            # 小节必须有「数字之外的实质标题」：纯数字行（CIP 的「1 4 000 20」、
            # 价格「59.00」等）不是目录项。要求去掉编号后仍有中文或 ≥4 字母。
            remainder = re.sub(r"^\s*\d+(?:\.\d+)*\s*[、.．]?\s*", "", title)
            if not (re.search(r"[\u4e00-\u9fff]", remainder)
                    or len(re.findall(r"[A-Za-z]", remainder)) >= 4):
                continue
            if depth + 2 <= max_level + 1:
                key = re.sub(r"\s+", "", title)
                if key and key not in seen:
                    seen.add(key)
                    toc.append({"level": depth + 2, "title": title, "line": i})
    return toc


def render_toc(toc: Iterable[dict]) -> str:
    """把目录渲染成 Markdown 列表（缩进 = 层级）。"""
    lines = ["## 目录", ""]
    for item in toc:
        level = max(1, min(int(item.get("level", 1)), 4))
        lines.append("  " * (level - 1) + "- " + str(item.get("title", "")))
    return "\n".join(lines) + "\n"


def postprocess(text: str) -> tuple[str, list[dict]]:
    """一步完成：断行重连 + 目录识别；返回 (处理后的文本, 目录)。"""
    reflowed = reflow_lines(text)
    toc = build_toc(reflowed)
    return reflowed, toc
