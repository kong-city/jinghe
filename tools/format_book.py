#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 OCR 精校稿排版成真正可读的 Markdown 电子书。

输入：按扫描行切碎的 OCR 文本（每行=一个扫描行）
输出：段落合并、章节分层、页眉页码清除的结构化 md

排版规则（保守，宁可少合并也不错并）：
1. 正文区从「第11章 赢得自由」起（试读版正文起点）；
2. 前置区（封面/版权/目录）保留为「出版信息」与「目录」两节；
3. 章节标题 `^第N章` → ##，小节（短行且无标点结尾）→ ###；
4. 段落合并：行尾无终止标点且下一行不是标题/页码 → 续行拼接；
5. 页眉页脚：纯数字页码、"目录"、水印残留 → 删。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

BODY_START = re.compile(r"^第\s*11\s*章")  # 试读版正文起点
CHAPTER = re.compile(r"^第\s*(\d+)\s*章[\s　]*(.*)$")
PAGE_NUM = re.compile(r"^\d{1,4}$")
HEADER_NOISE = {"目录", "MANNING", "SOFT SKILLS", "异步社区"}
# 行尾有这些标点 → 段落结束
END_PUNCT = "。！？；：”』】）.!?;:"
# 明显的小节标题：短、无句末标点、无常见句首词
SECTION_HINT = re.compile(
    r"^(采取行动|小结|引言|前言|最后|关于|如何|为什么|什么|什么是|第一步|第二步|"
    r"第[一二三四五六七八九十]+步|[^，。！？；：]{2,18})$")


def is_noise(line: str) -> bool:
    s = line.strip()
    if not s or PAGE_NUM.match(s):
        return True
    if s in HEADER_NOISE:
        return True
    # 水印碎片：WV / W / m / .c / bit.com.ci 等纯噪声短行
    if re.fullmatch(r"[WwVvBMmIl.]{1,6}", s):
        return True
    if re.fullmatch(r"[\W\d_]+", s):  # 纯符号/数字
        return True
    if re.search(r"(?:www\.|epubit|com\.cn|ptpress|manning\.com)", s, re.I) and len(s) < 40:
        return True
    return False


def format_body(lines: list[str]) -> list[str]:
    out: list[str] = []
    para: list[str] = []
    consumed: set[int] = set()
    seen_chapters: set[int] = set()

    def flush() -> None:
        if para:
            text = "".join(para).strip()
            if text:
                out.append(text)
            para.clear()

    for idx, raw in enumerate(lines):
        if idx in consumed:
            continue
        s = raw.strip()
        if is_noise(s):
            # 空行/页码：段落结束
            flush()
            continue

        m = CHAPTER.match(s)
        if m:
            num_i = int(m.group(1))
            # 页眉每页重复章名：章节号已见过 → 丢弃（保留正文首次出现）
            if num_i in seen_chapters:
                flush()
                continue
            seen_chapters.add(num_i)
            flush()
            num, rest = m.group(1), m.group(2).strip()
            # 去掉尾部粘连的页码（如「第1章标题1」）
            rest = re.sub(r"\d{1,4}$", "", rest).strip(" 　#")
            # OCR 常把章节标题拆成多行：「第11章」+「赢得自由一」+「如何辞职」；
            # 若本行只有章号，连续窥视后续短句补进标题，直到遇到长正文行。
            if not rest:
                while idx + 1 < len(lines):
                    nxt = lines[idx + 1].strip()
                    # 标题可含冒号/顿号，但不能有句末终止标点（那是正文）
                    if (0 < len(nxt) <= 28 and not PAGE_NUM.match(nxt)
                            and nxt not in HEADER_NOISE
                            and not CHAPTER.match(nxt)
                            and not re.search(r"[。！？]", nxt)):
                        rest += re.sub(r"\d{1,4}$", "", nxt).strip(" 　#")
                        consumed.add(idx + 1)
                        idx += 1
                    else:
                        break
            rest = rest.strip(" 一—　")
            if rest:
                out.append("\n## 第%s章 %s\n" % (num, rest))
            else:
                out.append("\n## 第%s章\n" % num)
            continue

        # 小节标题候选：短行、无终止标点、下一行不是续句
        if (len(s) <= 20 and not s[-1] in END_PUNCT
                and not s.startswith(("他", "我", "你", "这", "那", "但", "而", "如", "在", "为", "如", "如"))):
            if SECTION_HINT.match(s) and " " not in s[:3]:
                flush()
                out.append("\n### %s\n" % s)
                continue

        # 保守排版：OCR 扫描行本就是一行一句，中文行尾常无标点（标点被漏识），
        # 强行按标点合并会把整页黏成一个病态长句。改为每条扫描行独立成段，
        # 仅在「上一行明确以逗号结尾」时才续接（真正的断行）。
        if (para and para[-1].rstrip()[-1] in "，,、"
                and not s.startswith(("第", "他", "我", "你", "这", "那", "但", "而", "如", "在", "为", "如"))):
            para.append(s)
        else:
            flush()
            para.append(s)
    flush()
    return out


def format_front(lines: list[str]) -> list[str]:
    """前置区：出版信息 + 目录，保留但不混入正文。"""
    out: list[str] = []
    for raw in lines:
        s = raw.strip()
        if not s:
            continue
        if re.fullmatch(r"[\W\d_]+", s) or PAGE_NUM.match(s) or s in HEADER_NOISE:
            continue
        out.append(s)
    return out


def main() -> int:
    if len(sys.argv) < 3:
        print("用法: format_book.py <精校.txt> <输出.md>", file=sys.stderr)
        return 2
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    lines = src.read_text(encoding="utf-8").splitlines()

    # 找正文起点：目录里每个章名都会出现一次，正文里再出现一次。
    # 因此取「第11章」的**第二次**命中；若没有第二次（试读版不含该章正文），
    # 退回到「第N章标题 + 紧随其后 100 字内无页码数字行」的位置。
    hits = [i for i, l in enumerate(lines) if BODY_START.match(l.strip())]
    if len(hits) >= 2:
        body_at = hits[1]
    else:
        body_at = hits[0] if hits else len(lines)
        # 兜底：找「第N章」下一行是标题、再下一行起是长句的
        for i, l in enumerate(lines):
            m = CHAPTER.match(l.strip())
            if not m or i + 2 >= len(lines):
                continue
            nxt = [x.strip() for x in lines[i + 1:i + 6]]
            if any(len(x) > 25 and not PAGE_NUM.match(x) for x in nxt):
                body_at = i
                break
    front = format_front(lines[:body_at])
    body = format_body(lines[body_at:])

    doc: list[str] = [
        "# 软技能：代码之外的生存指南（试读版）",
        "",
        "> 〔美〕John Z. Sonmez 著 · 王小刚 译 · 人民邮电出版社",
        "> 本文件由扫描版 PDF 经 OCR 识别与排版整理，供个人阅读使用。",
        "",
        "---",
        "",
        "## 出版信息",
        "",
    ]
    # 出版信息里版权声明之后到目录之前的内容
    for s in front:
        doc.append(s)
        if len(doc) > 400:  # 目录太长，截断保护
            break
    doc.extend(["", "---", ""])
    doc.extend(body)

    result = "\n".join(doc)
    # 清理连续空行
    result = re.sub(r"\n{4,}", "\n\n\n", result).strip() + "\n"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(result, encoding="utf-8")
    print("排版完成：正文起点行 %d，前置 %d 行 → 输出 %d 字符 / %d 行" % (
        body_at, len(front), len(result), len(result.splitlines())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
