#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""修复引导块位置：统一移到 docstring + from __future__ 之后。

refactor_layout.py 初版对「shebang/编码注释 + docstring」文件定位不准，
导致 app.py/extract.py 的引导块插到 from __future__ 之前，触发 SyntaxError。
本脚本用 tokenize 精确定位「首个真实语句」的字符偏移，幂等可重跑。
"""
from __future__ import annotations

import io
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
START = "# JINGHE_LAYOUT_BOOTSTRAP"
END = "# END JINGHE_LAYOUT_BOOTSTRAP"


def extract_block(text: str) -> tuple[str, str]:
    """摘出引导块；返回 (块文本, 移除块后的文本)。"""
    if START not in text or END not in text:
        raise ValueError("引导块标记不完整")
    head = text.index(START)
    tail = text.index(END, head) + len(END)
    block = text[head:tail]
    if tail < len(text) and text[tail] == "\n":
        tail += 1
    return block, text[:head] + text[tail:]


def first_real_stmt_offset(text: str) -> int:
    """用 tokenize 找到第一个非注释/非 docstring/非 future import 的语句起始偏移。"""
    toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    i = 0
    # 跳过编码/shebang 注释、NL、INDENT 等
    while i < len(toks) and toks[i].type in (
        tokenize.ENCODING, tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE
    ):
        i += 1
    # 跳过模块 docstring（第一个 STRING token）
    if i < len(toks) and toks[i].type == tokenize.STRING:
        i += 1
        while i < len(toks) and toks[i].type == tokenize.NEWLINE:
            i += 1
    # 跳过 from __future__ import 行（到 NEWLINE）
    while i < len(toks) and toks[i].type in (tokenize.COMMENT, tokenize.NL):
        i += 1
    if i < len(toks) and toks[i].type == tokenize.NAME and toks[i].string == "from":
        # 检查这一行是否是 from __future__
        line = toks[i].line
        if "from __future__ import" in line:
            while i < len(toks) and toks[i].type != tokenize.NEWLINE:
                i += 1
            i += 1  # 跳过 NEWLINE
    # 跳过其后的空行/注释
    while i < len(toks) and toks[i].type in (tokenize.COMMENT, tokenize.NL):
        i += 1
    if i < len(toks):
        return toks[i].start[0], toks[i].start[1]  # (行号, 列)
    return len(text.splitlines()) + 1, 0


def fix_file(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if START not in text:
        return False
    block, cleaned = extract_block(text)
    lineno, col = first_real_stmt_offset(cleaned)
    lines = cleaned.splitlines(keepends=True)
    # 定位到目标行（1-based），插入前一行的末尾
    idx = max(0, min(lineno - 1, len(lines)))
    insert_at = sum(len(x) for x in lines[:idx]) + col
    new_text = cleaned[:insert_at] + "\n" + block + "\n" + cleaned[insert_at:]
    if new_text == text:
        return False
    path.write_text(new_text, encoding="utf-8")
    return True


def main() -> int:
    targets = [ROOT / "app.py", ROOT / "extract.py", ROOT / "build.py", ROOT / "pack.py"]
    targets += sorted(ROOT.glob("test_*.py"))
    n = 0
    for t in targets:
        if t.is_file() and fix_file(t):
            n += 1
            print(f"修正位置: {t.name}")
    print(f"\n[OK] 共修正 {n} 个文件的引导块位置")
    return 0


if __name__ == "__main__":
    sys.exit(main())
