#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OCR 文本后处理：过滤满页水印、合并断行、修正明显 OCR 误识。

只做**保守**修正——每一条都可用原文对照，绝不改写正常内容。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# 满页平铺水印：完整串与碎片（OCR 常只认出一部分）
WATERMARK_PATTERNS = (
    re.compile(r"(?:www\s*\.\s*)?epubit\s*\.\s*com(?:\s*\.\s*cn)?", re.I),
    # OCR 错序碎片：pubit.com. / bit.com. / ubit.com.cn 等
    re.compile(r"\bp-?u?bit\s*\.\s*com(?:\s*\.\s*cn)?\.?", re.I),
    re.compile(r"www\s*\.\s*epu[bhil]?\b", re.I),
    re.compile(r"异步社区", re.I),  # 水印同源的营销文字（正文引用除外，见 WHITELIST）
)
# 这些上下文里出现的水印词是正版内容，不能删
WHITELIST = ("异步社区全站", "异步社区，", "异步社区 ")

# 高置信度 OCR 误识修正（每条都可用原书对照，绝不改正常内容）
TYPO_FIXES = (
    # CIP 版权页专名
    (r"E小刚译", "王小刚译"),
    (r"正II、软件开发", "Ⅲ、软件开发"),
    (r"中版本图书馆", "中国版本图书馆"),
    (r"POSTS\s*&\s*TEIECOM", "POSTS & TELECOM"),
    (r"Developer'?\s+s Life", "Developer's Life"),
    # 全书高频形近字误识（「己/已」「袤/衰」「坛/毫」等，上下文唯一）
    (r"自已", "自己"),
    (r"广衰的世界", "广袤的世界"),
    (r"神毫上", "神坛上"),
    (r"一一这可是", "——这可是"),
    (r"步社区", "异步社区"),
)


def clean(text: str) -> str:
    out_lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            out_lines.append("")
            continue
        # 水印：整行只有水印 → 丢掉；行内水印 → 抹除后若剩空也丢掉
        cleaned = line
        for pat in WATERMARK_PATTERNS[:2]:
            cleaned = pat.sub("", cleaned)
        cleaned = re.sub(r"[\s.。]+$", "", cleaned).strip()
        if not cleaned:
            continue
        # 「异步社区」营销行：仅当整行几乎都是水印词时丢
        if "异步社区" in cleaned and len(cleaned) < 12 and not any(w in cleaned for w in WHITELIST):
            continue
        # 目录页 OCR 把「异步社区」缩成单个 m/l 的碎片（上下文多为页码行）
        if cleaned in ("m", "l") and len(out_lines) > 0:
            prev = out_lines[-1].strip()
            if prev.isdigit() or "社区" in prev:
                continue
        for pat, repl in TYPO_FIXES:
            cleaned = re.sub(pat, repl, cleaned)
        out_lines.append(cleaned)
    # 折叠 3 行以上空行
    text = "\n".join(out_lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def main() -> int:
    if len(sys.argv) < 3:
        print("用法: clean_ocr.py <in.txt> <out.md>", file=sys.stderr)
        return 2
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    text = src.read_text(encoding="utf-8", errors="replace")
    result = clean(text)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(result, encoding="utf-8")
    print("清理完成：%d → %d 字符，%d 行" % (
        len(text), len(result), len(result.splitlines())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
