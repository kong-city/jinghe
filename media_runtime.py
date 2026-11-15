#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精核 · 新能力产物区与出处骨架（S1 · 阶段 2/3 能力框架地基）。

**S0 关键裁决（必须遵守）**：阶段 1 的 ``out/md/*.md``、``INDEX.md``、
``MERGED.md`` 是冻结对账盘，``SPEC.md`` §3.F 要求 ``md/`` 实盘数与成功
记录数双向对账。新能力若往里写一个文件，件数立刻不平、多条黑盒断言失败。

因此本模块把新产物统一放到 ``out/derived/``，配一份独立的
``provenance_media.json``；**绝不写入** ``out/md/`` 或改写
``INDEX.md`` / ``MERGED.md`` / ``provenance.json``。

S1 只交付骨架与helper，不产出任何实际内容文档；S2–S5 复用本模块的
:func:`source_info` / :func:`source_comment` / :func:`block_anchor` 生成
符合 ``SPEC.md`` §5.1 / §5.2 的 8 字段来源注释与块级锚点。
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

DERIVED_DIRNAME = "derived"
PROVENANCE_NAME = "provenance_media.json"
FROZEN_ARTIFACTS = (
    "md", "INDEX.md", "MERGED.md", "provenance.json", "run.log",
)
SCHEMA = "jinghe.media.provenance.v1"


def derived_dir(outdir) -> Path:
    return Path(outdir) / DERIVED_DIRNAME


def ensure_derived(outdir) -> Path:
    """只在被新能力显式调用时创建；阶段 1 提取流程完全不碰它。"""
    path = derived_dir(outdir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def frozen_snapshot(outdir) -> dict:
    """记录冻结对账盘的当前形状，供运行前后比对。"""
    root = Path(outdir)
    md = root / "md"
    return {
        "md_count": len(list(md.glob("*.md"))) if md.is_dir() else 0,
        "index_exists": (root / "INDEX.md").is_file(),
        "merged_exists": (root / "MERGED.md").is_file(),
        "provenance_exists": (root / "provenance.json").is_file(),
    }


def frozen_unchanged(before: dict, outdir) -> bool:
    """新能力运行前后，冻结对账盘必须一模一样。"""
    return frozen_snapshot(outdir) == before


def new_provenance() -> dict:
    return {
        "schema": SCHEMA,
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "generator": "精核 S1 能力框架",
        "entries": [],
        "frozen_artifacts_untouched": list(FROZEN_ARTIFACTS),
        "note": "新能力产物的独立出处清单；不参与阶段 1 件数对账",
    }


def write_provenance(outdir, entries=None) -> Path:
    """写 ``out/derived/provenance_media.json``；失败项也通过 entries 留痕。"""
    target = ensure_derived(outdir) / PROVENANCE_NAME
    data = new_provenance()
    data["entries"] = list(entries or [])
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    return target


def read_provenance(outdir) -> dict:
    path = derived_dir(outdir) / PROVENANCE_NAME
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# 出处定位骨架（与 SPEC.md §5.1 / §5.2 逐字兼容）
# --------------------------------------------------------------------------- #
def source_info(path) -> dict:
    """一次流式读取同时得到 ``doc_id`` 与完整 64 位小写 sha256。

    ``doc_id`` 只取内容哈希前 12 位、不含路径字符；sha256 用完整值，
    供阶段 2 做原文完整性校验与跨批次去重。
    """
    h = hashlib.sha256()
    size = 0
    with open(str(path), "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            size += len(chunk)
            h.update(chunk)
    digest = h.hexdigest()
    return {
        "doc_id": "doc_" + digest[:12],
        "sha256": digest,
        "size": size,
    }


def source_comment(path, fmt: str, converter: str,
                   anchors=None, stamp: str | None = None) -> str:
    """双行来源注释：首行沿用 qa test_05 契约，次行 8 字段固定顺序全必含。"""
    p = Path(path)
    info = source_info(p)
    when = stamp or time.strftime("%Y-%m-%d %H:%M:%S")
    rel = p.name
    keys = ", ".join(anchors) if anchors else "none"
    first = "<!-- source: %s | format: %s | extracted: %s -->" % (rel, fmt, when)
    second = ("<!-- src: %s | path: %s | format: %s | converter: %s "
              "| extracted: %s | size: %d | sha256: %s | anchors: %s -->"
              % (info["doc_id"], rel, fmt, converter, when,
                 info["size"], info["sha256"], keys))
    return first + "\n" + second


# 锚点键顺序与 SPEC.md §5.2 一致，音视频扩展 time / frame。
_ANCHOR_KEYS = ("block", "page", "slide", "sheet", "chapter", "member",
                "line", "time", "frame")


def block_anchor(doc_id: str, block_idx: int, **locators) -> str:
    """块级锚点；不适用的定位键省略而非留空（§5.2）。

    生成结果必须能被 ``<!--\\s*anchor:\\s*doc_[0-9a-f]{12}\\s*\\|`` 匹配。
    """
    parts = ["doc_%s" % doc_id if not str(doc_id).startswith("doc_")
             else str(doc_id), "block: %d" % int(block_idx)]
    for key in _ANCHOR_KEYS:
        if key == "block" or key not in locators:
            continue
        value = locators[key]
        if value is None or value == "":
            continue
        parts.append("%s: %s" % (key, value))
    return "<!-- anchor: %s -->" % " | ".join(parts)
