#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精核 · 格式注册表（S1 · 阶段 2/3 能力框架地基）。

设计前提（见 docs/CAPABILITY_CONTRACT.md §0 / §1）：

* ``SPEC.md`` 与 ``extract.py`` 的阶段 1 提取内核是**冻结基线**，一行不动。
* 因此本模块**不改写** ``extract.py`` 的任何常量，而是直接读取它们作为
  「只读镜像」；新能力（音视频 / 链接 / Word）只查本注册表。
* 注册表是新能力的**唯一写者**；冻结内核是阶段 1 分流的**唯一真源**。
  两者的一致性由 ``test_app.py::test_33`` 逐字锁住，杜绝手工对表漂移。

S0 登记的两处漂移在此收敛：

* D1 ``extract.py:DEFERRED_EXT`` 含 ``.m4v`` 无 ``.wmv``，
  ``app.py:_STAGE3_AUDIO_EXT`` 曾恰好相反 —— 现在拆成
  ``STAGE1_DEFERRED``（冻结镜像）与 ``MEDIA_EXT``（新能力并集）两个语义。
* D2 ``app.py:_FILE_FILTERS`` 曾列出 ``.rtf/.odt/.yaml/.ini`` 等
  ``extract.py`` 并不支持的扩展名，且完全不含音视频 —— 现在由
  :func:`file_filters` 从注册表派生，不再手写。
"""
from __future__ import annotations

import extract  # 冻结内核：仅只读其常量，绝不修改

# --------------------------------------------------------------------------- #
# 阶段 1 分流基线（只读镜像；顺序与 extract.py 保持一致）
# --------------------------------------------------------------------------- #
STAGE1_SKILL = frozenset(extract.SKILL_EXT)
STAGE1_PLAIN = frozenset(extract.PLAIN_EXT)
STAGE1_RICH = frozenset(extract.RICH_EXT)
STAGE1_DEFERRED = frozenset(extract.DEFERRED_EXT)
STAGE1_LEGACY = frozenset(extract.LEGACY_EXT)


def all_stage1_ext() -> frozenset[str]:
    """阶段 1 会识别的全部扩展名（不含「不支持」的其它后缀）。"""
    return (STAGE1_SKILL | STAGE1_PLAIN | STAGE1_RICH
            | STAGE1_DEFERRED | STAGE1_LEGACY)


# --------------------------------------------------------------------------- #
# 阶段 2/3 新能力扩展名（本注册表是唯一写者）
# --------------------------------------------------------------------------- #
MEDIA_AUDIO = frozenset({
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".wma", ".amr",
})
# 视频取并集：既含冻结内核的 .m4v，也含后处理层曾单独登记的 .wmv。
MEDIA_VIDEO = frozenset({
    ".mp4", ".mov", ".avi", ".mkv", ".flv", ".webm", ".m4v", ".wmv",
})
MEDIA_EXT = MEDIA_AUDIO | MEDIA_VIDEO

# Word 输入增强（S2a）与导出（S2b）的候选后缀，S1 只登记、不实现。
WORD_INPUT_LEGACY = frozenset({".doc", ".xls", ".ppt"})
WORD_INPUT_OOXML = frozenset({".docx", ".xlsx", ".pptx"})
WORD_EXPORT_SUFFIX = ".docx"


def stage1_bucket(ext: str) -> str:
    """返回阶段 1 五桶之一；与 extract.py::classify 的口径一致。"""
    e = str(ext or "").lower()
    if e in STAGE1_DEFERRED:
        return "阶段3预留"
    if e in STAGE1_LEGACY:
        return "需预处理"
    if e in STAGE1_RICH:
        return "富文档"
    if e in STAGE1_SKILL or e in STAGE1_PLAIN:
        return "文本类"
    return "不支持"


def is_media(ext: str) -> bool:
    return str(ext or "").lower() in MEDIA_EXT


def media_kind(ext: str) -> str:
    """``audio`` / ``video`` / 空串。视频绝不归到音频（红线 2）。"""
    e = str(ext or "").lower()
    if e in MEDIA_VIDEO:
        return "video"
    if e in MEDIA_AUDIO:
        return "audio"
    return ""


def _pattern(exts) -> str:
    return ";".join("*" + e for e in sorted(exts))


def file_filters() -> list[tuple[str, str]]:
    """Win32 文件对话框过滤器，完全由注册表派生，不手写扩展名。

    「全部支持格式」只列阶段 1 真正会识别的后缀；音视频在 S1 尚未启用，
    通过「所有文件」选择，避免像旧版那样把不支持的格式列成「支持」。
    """
    common_candidates = (
        ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt",
        ".txt", ".md", ".html", ".htm", ".csv", ".json", ".epub", ".zip",
    )
    common = [e for e in common_candidates
              if stage1_bucket(e) != "不支持"]
    return [
        ("常用文档", _pattern(common)),
        ("全部支持格式", _pattern(all_stage1_ext())),
        ("所有文件", "*.*"),
    ]


def describe() -> dict:
    """给健康探测端点 / 契约测试用的结构化视图。"""
    return {
        "stage1": {
            "文本类": sorted(STAGE1_SKILL | STAGE1_PLAIN),
            "富文档": sorted(STAGE1_RICH),
            "阶段3预留": sorted(STAGE1_DEFERRED),
            "需预处理": sorted(STAGE1_LEGACY),
        },
        "media": {
            "audio": sorted(MEDIA_AUDIO),
            "video": sorted(MEDIA_VIDEO),
            "all": sorted(MEDIA_EXT),
        },
        "filters": [{"name": n, "pattern": p} for n, p in file_filters()],
        "note": "stage1 为 extract.py 冻结常量的只读镜像；media 为新能力唯一写者",
    }
