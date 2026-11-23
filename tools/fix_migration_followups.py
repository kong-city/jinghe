#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""迁移后续修复（2026-11-23，幂等）：

1) 移除「不需要引导」的测试文件里的引导块（保留冻结护栏 test_extract.py
   零改动），只给 test_iterate.py / test_kb.py 保留（它们直接 import 迁移模块）。
2) test_app.py 冻结护栏清单里的 media 模块路径更新为子目录。
3) test_subscription.py 的模块文件名清单更新为 subdir/ 路径。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
START = "# JINGHE_LAYOUT_BOOTSTRAP"
END = "# END JINGHE_LAYOUT_BOOTSTRAP"

# 直接 import 迁移模块、真正需要引导的测试
KEEP_BOOTSTRAP = {"test_iterate.py", "test_kb.py"}


def strip_bootstrap(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if START not in text:
        return False
    head = text.index(START)
    tail = text.index(END, head) + len(END)
    if tail < len(text) and text[tail] == "\n":
        tail += 1
    new = text[:head] + text[tail:]
    if new == text:
        return False
    path.write_text(new, encoding="utf-8")
    return True


def replace(path: Path, old: str, new: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        return False
    path.write_text(text.replace(old, new), encoding="utf-8")
    return True


def main() -> int:
    # ① 移除不需要的引导块
    removed = []
    for t in sorted(ROOT.glob("test_*.py")):
        if t.name not in KEEP_BOOTSTRAP and strip_bootstrap(t):
            removed.append(t.name)
    print(f"① 移除多余引导块: {', '.join(removed) or '无'}")

    # ② test_app.py 冻结护栏：
    #    - SPEC.md / test_extract.py 留根目录，仍断言 git diff HEAD 零改动；
    #    - audio/video_transcribe.py 已迁移到 media/，git diff HEAD 会把移动
    #      看成「删除+新增」。护栏真实意图是「S5 不碰这些内容」，故改为对比
    #      新路径内容 vs HEAD 中旧路径内容 —— 语义不削弱，反而更严格（防止
    #      迁移时被偷偷改代码）。
    old_guard = '''        for rel in ("SPEC.md", "test_extract.py",
                    "audio_transcribe.py", "video_transcribe.py"):
            self.assertEqual(
                subprocess.run(["git", "diff", "--quiet", "HEAD", "--", rel],
                               cwd=str(ROOT), capture_output=True).returncode, 0,
                "%s 被 S5 改动" % rel)'''
    new_guard = '''        for rel in ("SPEC.md", "test_extract.py"):
            self.assertEqual(
                subprocess.run(["git", "diff", "--quiet", "HEAD", "--", rel],
                               cwd=str(ROOT), capture_output=True).returncode, 0,
                "%s 被 S5 改动" % rel)
        # 迁移到 media/ 的两个 handler：内容与 HEAD 中旧路径逐字一致才算未改动
        for old_rel, new_rel in (("audio_transcribe.py", "media/audio_transcribe.py"),
                                 ("video_transcribe.py", "media/video_transcribe.py")):
            head_bytes = subprocess.run(["git", "show", "HEAD:" + old_rel],
                                        cwd=str(ROOT), capture_output=True).stdout
            self.assertEqual((ROOT / new_rel).read_bytes(), head_bytes,
                             "%s 迁移后内容被改动" % new_rel)'''
    r1 = replace(ROOT / "test_app.py", old_guard, new_guard)
    print(f"② 冻结护栏改为内容对比: {'完成' if r1 else '未命中(可能已修)'}")

    # ③ test_subscription.py 文件名清单
    old_list = 'for name in ("subscription_store.py", "channel_discovery.py",'
    new_list = 'for name in ("subs/subscription_store.py", "subs/channel_discovery.py",'
    r2 = replace(ROOT / "test_subscription.py", old_list, new_list)
    print(f"③ 订阅模块清单路径更新: {'完成' if r2 else '未命中(可能已修)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
