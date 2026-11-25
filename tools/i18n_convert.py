#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1.6.6：把 ui/index.html 里的中文文案接入 i18n 框架。

设计约束（零结构改动优先）：
1. 纯文本元素：只在开始标签追加 data-i18n / data-i18n-* 属性，文本节点保持原样；
2. 混合内容元素（内部还有子标签）：才用 <span data-i18n> 包裹中文文本；
3. 不改任何 id / class / data-page / 结构层级；
4. 中文原文直接作为 key（tr() 在 zh 下缺 key 时回退返回 key 本身）；
5. --dry-run 只统计不落盘；默认落盘并把待翻译 key 写入 tools/i18n_pending_en.json。

实现：HTMLParser 扫描原文件，记录每个开始标签的字符偏移与“是否纯文本子内容”。
"""
from __future__ import annotations

import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "ui" / "index.html"
PENDING = ROOT / "tools" / "i18n_pending_en.json"

CN = re.compile(r"[\u4e00-\u9fff]")
I18N_ATTR = {
    "title": "data-i18n-title",
    "placeholder": "data-i18n-ph",
    "aria-label": "data-i18n-aria",
}
VOID = {"input", "br", "hr", "img", "meta", "link"}


class Scanner(HTMLParser):
    """记录：属性追加点(offset, attr, key)、需要 span 包裹的文本段。"""

    def __init__(self, src: str) -> None:
        super().__init__(convert_charrefs=False)
        self.src = src
        self.keys: dict[str, str] = {}
        # (offset_of_tag_end, attr_name, key) —— 追加到开始标签 '>' 之前
        self.attr_add: list[tuple[int, str, str]] = []
        # (data_start, data_end, key) —— 需要 span 包裹的原始文本区间
        self.wrap: list[tuple[int, int, str]] = []
        self.stack: list[dict] = []
        self.skip_depth = 0

    def _key(self, text: str) -> str:
        k = text.strip()
        if k:
            self.keys.setdefault(k, k)
        return k

    def handle_starttag(self, tag, attrs):
        name = tag.lower()
        d = dict(attrs)
        already_text = "data-i18n" in d
        # 标签结束位置：getpos 给行列，换算成绝对偏移
        line, col = self.getpos()
        lines = self.src.splitlines(keepends=True)
        off = sum(len(x) for x in lines[: line - 1]) + col
        # 找该标签的 '>'（考虑属性中的 '>' 罕见；用简单搜索）
        gt = self.src.find(">", off)
        if name not in VOID:
            self.stack.append({
                "tag": name, "tag_start": off, "tag_end": gt,
                "attrs": d, "has_child": False, "has_text": False,
                "already_text": already_text, "skip": False,
            })
        if name in {"script", "style", "title"}:
            self.skip_depth += 1
        # 属性：追加 data-i18n-*（保留原属性）
        for k, v in attrs:
            if v is None:
                continue
            target = I18N_ATTR.get(k)
            if target and target not in d and CN.search(v):
                self.attr_add.append((gt, target, self._key(v)))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if self.stack and tag.lower() not in VOID:
            self.stack.pop()

    def handle_endtag(self, tag):
        name = tag.lower()
        if self.stack:
            self.stack.pop()
        if name in {"script", "style", "title"} and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data):
        if self.skip_depth or not CN.search(data) or not data.strip():
            return
        if not self.stack:
            return
        par = self.stack[-1]
        if par["skip"] or par["already_text"]:
            return
        key = self._key(data.strip())
        line, col = self.getpos()
        lines = self.src.splitlines(keepends=True)
        off = sum(len(x) for x in lines[: line - 1]) + col
        if par["has_child"]:
            # 混合内容：包 span（记录原始文本区间）
            self.wrap.append((off, off + len(data), key))
        else:
            # 纯文本：给父元素开始标签追加 data-i18n（同一元素只标一次）
            if not par["has_text"]:
                self.attr_add.append((par["tag_end"], "data-i18n", key))
                par["has_text"] = True

    def handle_entityref(self, name):
        if self.stack:
            self.stack[-1]["has_child"] = True

    def handle_charref(self, name):
        if self.stack:
            self.stack[-1]["has_child"] = True

    def handle_comment(self, data):
        pass

    def handle_decl(self, decl):
        pass


def apply(src: str, sc: Scanner) -> str:
    # 从后往前插入，避免偏移失效
    edits: list[tuple[int, int, str]] = []
    for off, attr, key in sc.attr_add:
        q = "'" if '"' in key else '"'
        edits.append((off, off, f' {attr}={q}{key}{q}'))
    for s, e, key in sc.wrap:
        q = "'" if '"' in key else '"'
        raw = src[s:e]
        edits.append((s, e, f'<span data-i18n={q}{key}{q}>{raw}</span>'))
    # 检查区间不重叠
    edits.sort(key=lambda x: x[0], reverse=True)
    last_start = len(src) + 1
    for s, e, rep in edits:
        if e > last_start:
            raise RuntimeError(f"编辑区间重叠: {s}-{e} 与后续冲突")
        src = src[:s] + rep + src[e:]
        last_start = s
    return src


def main() -> int:
    dry = "--dry-run" in sys.argv
    src = HTML.read_text(encoding="utf-8")
    sc = Scanner(src)
    sc.feed(src)
    converted = apply(src, sc)
    print(f"纯文本标记: {sum(1 for _,a,_ in sc.attr_add if a=='data-i18n')}")
    print(f"属性标记  : {sum(1 for _,a,_ in sc.attr_add if a!='data-i18n')}")
    print(f"span 包裹 : {len(sc.wrap)}")
    print(f"待翻译 key（去重）: {len(sc.keys)}")
    print(f"长度: {len(src)} -> {len(converted)}")
    if dry:
        print("[dry-run] 未落盘")
        return 0
    HTML.write_text(converted, encoding="utf-8")
    PENDING.write_text(
        json.dumps({k: "" for k in sc.keys}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"已写入 {HTML}")
    print(f"已写入 {PENDING}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
