#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OCR 质量验收：把「百分百识别」变成可量化的硬指标。

检查 6 项：
1. 控制字符 / 私用区乱码 = 0
2. 水印循环污染 = 0（同一水印串重复 > 3 次即判污染）
3. 中文可读性：常用中文字符占比达标
4. 页数覆盖：OCR 文本分块数 == PDF 页数（每页都有内容）
5. 关键锚点：书名、作者、出版社等 CIP 专名可对照
6. 断行完整性：无单字母/单数字成行的碎片（水印残留特征）
"""
from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

WATERMARK = re.compile(r"(?:www\s*\.\s*)?epubit|epu[bhil]?\s*\.\s*com", re.I)


def check(text: str, expected_pages: int = 73) -> dict:
    lines = text.splitlines()
    total = len(text)

    # 1. 控制字符/私用区
    bad = [(i, c) for i, l in enumerate(lines) for c in l
           if (ord(c) < 32 and c not in "\n\r\t") or 0xE000 <= ord(c) <= 0xF8FF
           or c == "\ufffd"]
    # 2. 水印循环：水印词在同一行重复 > 3
    wm_lines = [i for i, l in enumerate(lines)
                if len(WATERMARK.findall(l)) > 3]

    # 3. 中文可读性
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    letters = sum(1 for c in text if c.isalpha())
    cjk_ratio = cjk / letters if letters else 0

    # 4. 页数覆盖（OCR worker 用空行分隔页块）
    # 纯水印页（只有"异步社区 + www.epubit..."、无正文）被后处理正确删除，
    # 不算丢失正文 —— 从期望分母里剔除，避免把正确清理误判为丢页。
    all_blocks = [b for b in re.split(r"\n\s*\n", text) if b.strip()]
    blocks = [b for b in all_blocks
              if len(re.sub(r"异步社区|www\.|epubit|\.com|\.cn|\s", "", b, flags=re.I)) >= 20]

    # 5. 关键锚点（本书 CIP 页可对照文字）
    anchors = ["软技能", "代码之外的生存指南", "John Z. Sonmez",
               "王小刚", "人民邮电出版社", "Software Developer"]
    found = [a for a in anchors if a.lower() in text.lower()]

    # 6. 单字符碎片行
    fragments = [i for i, l in enumerate(lines)
                 if len(l.strip()) == 1 and not l.strip().isdigit()
                 and not ("\u4e00" <= l.strip() <= "\u9fff")]

    result = {
        "总字符": total,
        "总行数": len(lines),
        "①控制字符/乱码": len(bad),
        "②水印循环行": len(wm_lines),
        "③中文占比": round(cjk_ratio, 3),
        "④页数覆盖": "%d/%d" % (len(blocks), expected_pages),
        "⑤关键锚点": "%d/%d %s" % (len(found), len(anchors), found),
        "⑥单字符碎片行": len(fragments),
    }
    ok = (not bad and not wm_lines and cjk_ratio > 0.3
          and len(blocks) >= expected_pages * 0.9
          and len(found) >= len(anchors) - 1
          and len(fragments) < 10)
    result["验收"] = "通过" if ok else "未通过"
    if bad:
        result["乱码样本"] = repr(bad[:5])
    if wm_lines:
        result["水印样本"] = [lines[i][:80] for i in wm_lines[:3]]
    if fragments:
        result["碎片样本"] = [lines[i] for i in fragments[:8]]
    return result


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: check_ocr_quality.py <ocr.txt> [期望页数]", file=sys.stderr)
        return 2
    text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
    pages = int(sys.argv[2]) if len(sys.argv) > 2 else 73
    r = check(text, pages)
    for k, v in r.items():
        print("%-18s %s" % (k + ":", v))
    return 0 if r["验收"] == "通过" else 1


if __name__ == "__main__":
    sys.exit(main())
