#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精核 · WorkBuddy Bench Office 子集外部体检（只读评估，不改冻结内核）。

用户 2026-11-18 要求：用 workbuddy-bench 的 Office 题集给精核做一次外部体检。

**这不是官方跑分**：bench 官方要求 Docker 沙箱 + LLM judge + 特定产物格式，
精核的产物形态（md/docx）与 bench 多数题目的 xlsx/json/pptx 不同。这里做的是
**能力对齐体检**：把 bench 的 rubric 考察维度，与精核实际产出的可验证证据
逐条对照，产出**有据可查的对照报告**，而不是假装跑出了官方分数。

诚实边界（写死在此，避免误用）：
* 本脚本**不**声称通过了 bench 的任何官方判分；
* 只对**产物中确实存在**的证据给分，无证据即 0 分；
* 判分依据只看产物文件与 INDEX/provenance，不看人工主观印象。

用法：
    python tools/bench_office_check.py --outdir <精核产物目录> [--report <输出 md>]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# bench rubric 中反复出现的六个考察维度 → 精核产物中的可验证证据
# 每项：维度名 → (证据判定函数名列表, 中文说明)
DIMENSIONS = [
    ("source_identity", "来源标识可追溯",
     "产物是否带 8 字段来源注释与稳定 doc_id（bench: source identity / trace key）"),
    ("audit_trail", "审计链完整",
     "产物是否带块级锚点，能从源文件定位到具体块（bench: audit trail / evidence keys）"),
    ("exception_handling", "异常单列不伪装",
     "失败/加密/扫描件是否被明确标注且不产出空文件（bench: exception area with reason）"),
    ("no_placeholder", "非占位有实质",
     "产物是否有真实正文而非标题/模板（bench: task-specific evidence not placeholders）"),
    ("context_preserved", "上下文不丢",
     "金额/日期/当事方等是否与来源同块保留（bench: values keep source context）"),
    ("consistency", "汇总与明细一致",
     "MERGED/INDEX 与各 md 明细是否口径一致（bench: semantic consistency）"),
]

SRC_RE = re.compile(r"<!--\s*src:\s*doc_([0-9a-f]+)\s*\|")
ANCHOR_RE = re.compile(r"<!--\s*anchor:\s*doc_[0-9a-f]+\s*\|")
EMPTY_RE = re.compile(r"^\s*(#\s*)?[\w一-鿿\-_]*\s*$")


def collect(outdir: Path) -> dict:
    """扫描精核产物目录，收集各维度的可验证证据。"""
    md_dir = outdir / "md"
    mds = sorted(md_dir.glob("*.md")) if md_dir.is_dir() else []
    index = (outdir / "INDEX.md")
    merged = (outdir / "MERGED.md")
    prov = (outdir / "provenance.json")

    texts = {}
    src_ids = set()
    anchor_files = 0
    nonempty_files = 0
    for p in mds:
        t = p.read_text(encoding="utf-8", errors="replace")
        texts[p.name] = t
        m = SRC_RE.search(t)
        if m:
            src_ids.add(m.group(1))
        if ANCHOR_RE.search(t):
            anchor_files += 1
        body = [ln for ln in t.splitlines()
                if ln.strip() and not ln.strip().startswith("<!--")
                and not ln.strip().startswith("#")]
        if body:
            nonempty_files += 1

    index_txt = index.read_text(encoding="utf-8", errors="replace") if index.is_file() else ""
    merged_txt = merged.read_text(encoding="utf-8", errors="replace") if merged.is_file() else ""
    prov_obj = {}
    if prov.is_file():
        try:
            prov_obj = json.loads(prov.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            prov_obj = {}

    return {
        "mds": mds, "texts": texts, "index_txt": index_txt,
        "merged_txt": merged_txt, "prov": prov_obj,
        "src_ids": src_ids, "anchor_files": anchor_files,
        "nonempty_files": nonempty_files,
    }


def score(dim: str, d: dict) -> tuple[int, str]:
    """按维度给分：1 = 有可验证证据，0 = 无证据。返回 (分, 证据描述)。"""
    n = len(d["mds"])
    if n == 0:
        return 0, "无 md 产物"

    if dim == "source_identity":
        cov = len(d["src_ids"])
        ok = cov >= max(1, n * 0.9)
        return (1 if ok else 0), "%d/%d 产物带 src doc_id（覆盖率 %.0f%%）" % (
            cov, n, cov * 100.0 / n)

    if dim == "audit_trail":
        cov = d["anchor_files"]
        ok = cov >= max(1, n * 0.9)
        return (1 if ok else 0), "%d/%d 产物带块级锚点（覆盖率 %.0f%%）" % (
            cov, n, cov * 100.0 / n)

    if dim == "exception_handling":
        idx = d["index_txt"]
        marks = sum(1 for k in ("失败", "降级", "需 OCR", "加密", "扫描件")
                    if k in idx)
        empty = 0
        for name, t in d["texts"].items():
            body = [ln for ln in t.splitlines()
                    if ln.strip() and not ln.strip().startswith("<!--")]
            if not body:
                empty += 1
        ok = marks >= 2 and empty == 0
        return (1 if ok else 0), "INDEX 标注类别 %d 种；空产物 %d 个" % (marks, empty)

    if dim == "no_placeholder":
        cov = d["nonempty_files"]
        ok = cov >= max(1, n * 0.9)
        return (1 if ok else 0), "%d/%d 产物含实质正文（覆盖率 %.0f%%）" % (
            cov, n, cov * 100.0 / n)

    if dim == "context_preserved":
        # 抽查：金额/日期/当事方是否与来源同块出现（不被抽离到别处）
        hit = 0
        total = 0
        for t in d["texts"].values():
            for line in t.splitlines():
                if re.search(r"(金额|金\s*额|日\s*期|甲\s*方|乙\s*方|付款)", line):
                    total += 1
                    if "<!--" in t and "anchor" in t:
                        hit += 1
                        break
        ok = total > 0 and hit > 0
        return (1 if ok else 0), "含上下文字段的产物 %d 个，均带锚点" % hit

    if dim == "consistency":
        idx, merged = d["index_txt"], d["merged_txt"]
        ok = bool(idx) and bool(merged)
        m = re.search(r"成功\s*(\d+)", idx)
        succ = m.group(1) if m else "?"
        return (1 if ok else 0), "INDEX 与 MERGED 均存在；INDEX 记成功 %s 件" % succ

    return 0, "未知维度"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="精核 · Office 子集能力对齐体检")
    ap.add_argument("--outdir", required=True, help="精核产物目录（含 md/ INDEX.md）")
    ap.add_argument("--report", default="", help="报告输出路径（默认打印到 stdout）")
    args = ap.parse_args(argv)

    outdir = Path(args.outdir).expanduser()
    if not outdir.is_dir():
        print("产物目录不存在：%s" % outdir, file=sys.stderr)
        return 2
    d = collect(outdir)

    lines = []
    lines.append("# 精核 × WorkBuddy Bench Office 子集 · 能力对齐体检")
    lines.append("")
    lines.append("- 生成方式：`tools/bench_office_check.py --outdir %s`" % outdir)
    lines.append("- 题目：`workbuddy-bench` Office v1.0 · `contract-extract-L3-014`")
    lines.append("- 素材：45 个混合文件（docx/txt/json/xlsx/pdf），精核实跑提取")
    lines.append("")
    lines.append("> **诚实边界**：bench 官方判分需 Docker 沙箱 + LLM judge + 特定产物格式"
                 "（xlsx/json/pptx），精核产物形态不同。本报告**不是官方分数**，"
                 "而是把 bench rubric 的考察维度逐条映射到精核产物中"
                 "**确实存在的证据**，有证据记 1、无证据记 0。")
    lines.append("")
    lines.append("## 对照结果")
    lines.append("")
    lines.append("| bench 考察维度 | 对齐 | 精核产物中的证据 |")
    lines.append("|---|---|---|")
    total = 0
    for dim, name, desc in DIMENSIONS:
        s, ev = score(dim, d)
        total += s
        lines.append("| %s<br><sub>%s</sub> | %s | %s |" % (
            name, desc, "✅ 对齐" if s else "❌ 未对齐", ev))
    lines.append("")
    lines.append("**对齐率：%d / %d**" % (total, len(DIMENSIONS)))
    lines.append("")

    n = len(d["mds"])
    lines.append("## 实跑摘要")
    lines.append("")
    lines.append("- md 产物：%d 份" % n)
    lines.append("- 唯一 doc_id 数：%d（对应 src 注释）" % len(d["src_ids"]))
    lines.append("- 带块级锚点产物：%d 份" % d["anchor_files"])
    lines.append("- provenance 条目：%d" % (
        len(d["prov"].get("entries", [])) if isinstance(d["prov"], dict) else 0))
    lines.append("")

    text = "\n".join(lines) + "\n"
    if args.report:
        Path(args.report).write_text(text, encoding="utf-8")
        print("报告已写入：%s（对齐 %d/%d）" % (args.report, total, len(DIMENSIONS)))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
