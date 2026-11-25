#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1.6.6：把 i18n_en_map.EN 生成成 JS 片段，注入 ui/i18n.js 的 I18N.en 字典。

幂等：用标记注释包裹生成段，重复运行只替换标记之间的内容。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "ui" / "i18n.js"
sys.path.insert(0, str(ROOT / "tools"))
from i18n_en_map import EN  # noqa: E402

BEGIN = "    /* I18N_AUTO_BEGIN */"
END = "    /* I18N_AUTO_END */"


def js_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def build_block() -> str:
    lines = [BEGIN]
    items = sorted(EN.items())
    for i, (k, v) in enumerate(items):
        suffix = "" if i == len(items) - 1 else ","
        lines.append(f"    {js_str(k)}: {js_str(v)}{suffix}")
    lines.append(END)
    return "\n".join(lines)


def main() -> int:
    src = JS.read_text(encoding="utf-8")
    block = build_block()
    if BEGIN in src and END in src:
        head, rest = src.split(BEGIN, 1)
        _, tail = rest.split(END, 1)
        new = head + block + tail
    else:
        # 首次注入：在 en 字典的收尾 }; 前插入（I18N 定义块 329-372）
        marker = '      "page.about.sub": "Version, roadmap and privacy"\n    }\n  };'
        if marker not in src:
            print("错误：找不到 I18N.en 字典收尾锚点")
            return 1
        new = src.replace(marker, '      "page.about.sub": "Version, roadmap and privacy",\n' + block + "\n    }\n  };", 1)
    JS.write_text(new, encoding="utf-8")
    print(f"已注入 {len(EN)} 条英文映射到 {JS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
