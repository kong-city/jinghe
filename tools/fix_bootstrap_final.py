#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""最终修正引导块归属（2026-11-23）：

前一轮误判：只看顶层 ^import，漏了测试方法内部的 import（setUp / test_xx 里
的 `import subscription_store` 等）。结果 7 个测试失去引导，靠 unittest
discovery 的顺序副作用（test_iterate 先加载污染 sys.path）才碰巧能过 ——
单文件运行直接 ModuleNotFoundError。

本脚本给「确实 import 迁移模块」的 7 个测试重新注入引导块，并确认 3 个
不需要引导的测试（含冻结护栏 test_extract.py）保持零引导。幂等。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARK = "# JINGHE_LAYOUT_BOOTSTRAP"
END = "# END JINGHE_LAYOUT_BOOTSTRAP"
NEEDS_BOOTSTRAP = {
    "test_app.py", "test_components.py", "test_iterate.py", "test_kb.py",
    "test_scheduler.py", "test_subscription.py", "test_v10_features.py",
}
NO_BOOTSTRAP = {"test_extract.py", "test_smoke_harness.py", "test_ui_layout.py"}

BOOTSTRAP = (
    f"{MARK}\n"
    "import sys as _jinghe_sys\n"
    "from pathlib import Path as _jinghe_Path\n"
    "_jinghe_root = _jinghe_Path(__file__).resolve().parent\n"
    "for _jinghe_sub in (\"core\", \"media\", \"knowledge\", \"link\", \"subs\"):\n"
    "    _jinghe_p = str(_jinghe_root / _jinghe_sub)\n"
    "    if _jinghe_p not in _jinghe_sys.path:\n"
    "        _jinghe_sys.path.insert(0, _jinghe_p)\n"
    f"{END}\n"
)


def first_real_stmt_line(lines: list[str]) -> int:
    """返回第一个真实语句的行索引（0-based）：跳过注释/docstring/future。"""
    i = 0
    n = len(lines)
    while i < n and (not lines[i].strip() or lines[i].lstrip().startswith("#")):
        i += 1
    if i < n and lines[i].strip().startswith(('"""', "'''")):
        q = lines[i].strip()[:3]
        if lines[i].strip().count(q) >= 2:
            i += 1
        else:
            i += 1
            while i < n and q not in lines[i]:
                i += 1
            i += 1
    while i < n and (not lines[i].strip() or lines[i].lstrip().startswith("#")):
        i += 1
    if i < n and lines[i].strip().startswith("from __future__"):
        i += 1
    while i < n and not lines[i].strip():
        i += 1
    return i


def add_bootstrap(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if MARK in text:
        return False
    lines = text.splitlines(keepends=True)
    idx = first_real_stmt_line(lines)
    lines.insert(idx, "\n" + BOOTSTRAP)
    path.write_text("".join(lines), encoding="utf-8")
    return True


def strip_bootstrap(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if MARK not in text:
        return False
    head = text.index(MARK)
    tail = text.index(END, head) + len(END)
    if tail < len(text) and text[tail] == "\n":
        tail += 1
    new = text[:head] + text[tail:]
    if new == text:
        return False
    path.write_text(new, encoding="utf-8")
    return True


def main() -> int:
    for name in sorted(NEEDS_BOOTSTRAP):
        p = ROOT / name
        if p.is_file() and add_bootstrap(p):
            print(f"注入引导: {name}")
    for name in sorted(NO_BOOTSTRAP):
        p = ROOT / name
        if p.is_file() and strip_bootstrap(p):
            print(f"移除引导: {name}")
    print("[OK] 引导块归属已修正")
    return 0


if __name__ == "__main__":
    sys.exit(main())
