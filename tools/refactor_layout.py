#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性源码分层迁移脚本（2026-11-23，可重入、可审计）。

把 24 个业务模块从项目根目录移入 5 个功能子目录，并修复所有引用：

迁移映射
--------
core/       format_registry, extract_engine, refine_engine, revise_engine,
            iterate_engine, log_rotate
media/      media_tools, media_runtime, audio_transcribe, video_transcribe,
            pdf_ocr, word_input, word_export
knowledge/  kb, refine, components
link/       link_downloader, link_guard, link_media
subs/       subscription_store, channel_discovery, subscription_engine,
            subscription_scheduler

保留在根目录（不迁移）
----------------------
app.py        主入口 / 版本真源调用方 / 47 处测试按路径断言
extract.py    版本真源 __version__ + 子进程 CLI 入口 + 冻结基线护栏
backend.py    S7b 内核适配层（refine 等直接 import，路径断言多）
build.py      打包入口
pack.py       源码打包工具
test_*.py     全部测试（避免改 discovery 契约）
其他配置/文档/ui/vendor/electron/tools

引用修复
--------
1) build.spec: pathex 加入 5 个子目录（PyInstaller 打包态靠它找到裸 import）
2) 测试文件: ROOT / "<moved>.py" → ROOT / "<subdir>" / "<moved>.py"
   （14 个模块被测试读取源码文本做断言，必须同步）
3) 所有 .py 入口/测试顶层加 sys.path 引导（源码态裸 import 生效）
   注：不用 sitecustomize.py —— 本环境 PYTHONPATH 已被 WorkBuddy shim 占用，
   项目根的 sitecustomize 不会被加载。显式引导最可靠。

可重入：已迁移的模块会跳过；路径引用重复替换不会产生嵌套。
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 模块 → 目标子目录
MOVES: dict[str, str] = {
    # core：内核/引擎/基础设施
    "format_registry": "core",
    "extract_engine": "core",
    "refine_engine": "core",
    "revise_engine": "core",
    "iterate_engine": "core",
    "log_rotate": "core",
    # media：音视频/文档转换
    "media_tools": "media",
    "media_runtime": "media",
    "audio_transcribe": "media",
    "video_transcribe": "media",
    "pdf_ocr": "media",
    "word_input": "media",
    "word_export": "media",
    # knowledge：知识库/精读/组件
    "kb": "knowledge",
    "refine": "knowledge",
    "components": "knowledge",
    # link：链接处理
    "link_downloader": "link",
    "link_guard": "link",
    "link_media": "link",
    # subs：订阅
    "subscription_store": "subs",
    "channel_discovery": "subs",
    "subscription_engine": "subs",
    "subscription_scheduler": "subs",
}

SUBDIRS = sorted(set(MOVES.values()))

# 每个顶层 .py 需要的 sys.path 引导块（幂等标记）
BOOTSTRAP_MARK = "# JINGHE_LAYOUT_BOOTSTRAP"
BOOTSTRAP = (
    f"{BOOTSTRAP_MARK}\n"
    "import sys as _jinghe_sys\n"
    "from pathlib import Path as _jinghe_Path\n"
    "_jinghe_root = _jinghe_Path(__file__).resolve().parent\n"
    "for _jinghe_sub in (\"core\", \"media\", \"knowledge\", \"link\", \"subs\"):\n"
    "    _jinghe_p = str(_jinghe_root / _jinghe_sub)\n"
    "    if _jinghe_p not in _jinghe_sys.path:\n"
    "        _jinghe_sys.path.insert(0, _jinghe_p)\n"
    "# END JINGHE_LAYOUT_BOOTSTRAP\n"
)


def ensure_bootstrap(path: Path) -> bool:
    """在 docstring / from __future__ 之后插入引导块（幂等）。返回是否修改。

    Python 语法约束：模块 docstring 必须是第一条语句，``from __future__``
    必须紧随其后。引导块要放在这两者之后、其他 import 之前。
    """
    text = path.read_text(encoding="utf-8")
    if BOOTSTRAP_MARK in text:
        return False
    lines = text.splitlines(keepends=True)

    insert_at = 0
    # ① 跳过模块 docstring（支持三引号 """ 与 '''）
    if lines:
        first = lines[0].lstrip()
        if first.startswith(('"""', "'''")):
            quote = first[:3]
            if first.count(quote) >= 2 and first.rstrip().endswith(quote):
                insert_at = 1  # 单行 docstring
            else:
                for i in range(1, len(lines)):
                    if quote in lines[i]:
                        insert_at = i + 1
                        break
    # ② 跳过 from __future__ import（必须在 docstring 之后）
    for i in range(insert_at, min(insert_at + 3, len(lines))):
        if lines[i].startswith("from __future__ import"):
            insert_at = i + 1
            break

    lines.insert(insert_at, "\n" + BOOTSTRAP)
    path.write_text("".join(lines), encoding="utf-8")
    return True


def move_modules() -> list[str]:
    """git mv 模块到子目录，返回实际移动的模块名。"""
    moved = []
    for sub in SUBDIRS:
        (ROOT / sub).mkdir(exist_ok=True)
        # 子目录作为 namespace package（不加 __init__.py，保持裸 import 语义）
    for mod, sub in MOVES.items():
        src = ROOT / f"{mod}.py"
        dst = ROOT / sub / f"{mod}.py"
        if not src.is_file():
            if dst.is_file():
                continue  # 已迁移
            raise FileNotFoundError(f"待迁移模块不存在: {src}")
        shutil.move(str(src), str(dst))
        moved.append(mod)
    return moved


def fix_test_paths() -> int:
    """修正测试里 ROOT / "moved.py" 的源码文本断言路径。返回修改处数。"""
    total = 0
    for test in ROOT.glob("test_*.py"):
        text = test.read_text(encoding="utf-8")
        orig = text
        for mod, sub in MOVES.items():
            # ROOT / "mod.py"  →  ROOT / "sub" / "mod.py"
            text = text.replace(f'ROOT / "{mod}.py"', f'ROOT / "{sub}" / "{mod}.py"')
        if text != orig:
            test.write_text(text, encoding="utf-8")
            total += 1
    return total


def fix_build_spec() -> bool:
    """build.spec pathex 加入子目录。"""
    p = ROOT / "build.spec"
    text = p.read_text(encoding="utf-8")
    if '"core"' in text and '"subs"' in text:
        return False
    new_path = "pathex=['core', 'media', 'knowledge', 'link', 'subs'],"
    text = re.sub(r"pathex=\[[^\]]*\],", new_path, text, count=1)
    p.write_text(text, encoding="utf-8")
    return True


def fix_tools_paths() -> int:
    """tools/ 下按路径读版本真源/模块的引用（extract.py 留根目录，通常无需改）。"""
    # extract.py / app.py / build.py 都保留根目录，工具里的路径引用不受影响。
    # 此处仅预留钩子，便于审计时确认。
    return 0


def main() -> int:
    print("=== 源码分层迁移 ===")
    moved = move_modules()
    print(f"① 迁移模块 {len(moved)} 个: {', '.join(moved) if moved else '(已全部迁移)'}")

    n = fix_test_paths()
    print(f"② 修正测试源码路径断言: {n} 个测试文件")

    if fix_build_spec():
        print("③ build.spec pathex 已加入 5 个子目录")
    else:
        print("③ build.spec 已是目标状态")

    # 入口 + 所有测试加引导（tools 不 import 业务模块，无需引导）
    targets = [ROOT / "app.py", ROOT / "extract.py", ROOT / "build.py", ROOT / "pack.py"]
    targets += sorted(ROOT.glob("test_*.py"))
    bootstrapped = 0
    for t in targets:
        if t.is_file() and ensure_bootstrap(t):
            bootstrapped += 1
    print(f"④ 注入 sys.path 引导: {bootstrapped} 个入口/测试文件")

    print("\n[OK] 迁移完成，下一步跑全套测试验证。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
