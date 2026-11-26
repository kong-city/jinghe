#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1.7.2 · 架构优化守护测试。

锁定本轮 5 项有证据的优化：
1. keyword_scores 三遍算 → 透传复用（数值等价）
2. /api/state 高频轮询不再每次重算 platform.platform()
3. provenance_media.json 并发安全（锁 + 原子替换）
4. kb 批量入库（executemany + 同文件重复 id 语义等价）
5. iterate_engine 同样复用 global_scores
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for _sub in ("core", "media", "knowledge", "link", "subs"):
    _p = str(ROOT / _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestArchOptimizations(unittest.TestCase):

    def test_01_keyword_scores_reuse_is_equivalent(self):
        """透传 global_scores 与原计算逐字等价（句向量 + 关键词）。"""
        import core.extract_engine as X
        text = "# 标题\n\n精核提取公告：软件用于把文档提炼为要点。\n关键词提取与文本摘要是核心能力。\n" * 4
        blocks = X.split_blocks(text)
        sents = X.collect_sentences(blocks)
        gs = X.keyword_scores(sents)
        self.assertEqual(X.sentence_vectors(sents),
                         X.sentence_vectors(sents, global_scores=gs),
                         "句向量透传后数值变了")
        heads = X.heading_terms(blocks)
        self.assertEqual(X.top_keywords(sents, heads=heads),
                         X.top_keywords(sents, heads=heads, global_scores=gs),
                         "关键词透传后结果变了")

    def test_02_extract_core_passes_scores(self):
        """extract_core 必须复用算好的分数，不再让下游重复计算。"""
        src = (ROOT / "core" / "extract_engine.py").read_text(encoding="utf-8")
        self.assertIn("sentence_vectors(sents, global_scores=global_scores)", src)
        self.assertIn("top_keywords(sents, heads=heads, global_scores=global_scores)", src)

    def test_03_platform_label_cached(self):
        """/api/state 400ms 轮询不能每次重算 platform.platform()。"""
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("def _platform_label()", src)
        self.assertIn('"platform": _platform_label()', src)
        self.assertNotIn('"platform": platform.platform()', src)

    def test_04_provenance_atomic_and_locked(self):
        """provenance_media.json 必须加锁 + 原子替换（并发读不到半截 JSON）。"""
        src = (ROOT / "media" / "media_runtime.py").read_text(encoding="utf-8")
        self.assertIn("threading.Lock()", src)
        self.assertIn("os.replace(tmp, target)", src)
        self.assertIn("with _PROVENANCE_LOCK:", src)

    def test_05_kb_batch_insert_and_dup_semantics(self):
        """批量入库：executemany + 同文件重复 id 的 ref_count 语义保持。"""
        import tempfile
        import sqlite3
        import kb
        md = """<!-- source: chapter.txt | format: .txt -->
<!-- src: doc_abc123def45 | path: chapter.txt | format: .txt | sha256: deadbeef -->

<!-- anchor: doc_abc123def45 | block: 1 | line: 1..2 -->
# 第一章 知识提取的边界

<!-- anchor: doc_abc123def45 | block: 2 | line: 3..4 -->
## 1.1 文字层
文字层 PDF 可直接提取文本，保留标题层级。
"""
        with tempfile.TemporaryDirectory(prefix="jinghe-kb-arch-") as td:
            root = Path(td)
            src = root / "a.md"
            src.write_text(md, encoding="utf-8")
            kbdir = root / "kb"
            r1 = kb.ingest_md(kbdir, src, allowed_roots=[root])
            r2 = kb.ingest_md(kbdir, src, allowed_roots=[root])
            self.assertEqual((r1.get("added"), r1.get("duplicate")), (2, 0))
            self.assertEqual((r2.get("added"), r2.get("duplicate")), (0, 2))
            con = sqlite3.connect(kbdir / "kb.sqlite3")
            counts = [row[0] for row in con.execute("SELECT ref_count FROM entries")]
            con.close()
            self.assertEqual(counts, [2, 2], "重复入库后 ref_count 应累加到 2")

    def test_06_kb_uses_executemany(self):
        src = (ROOT / "knowledge" / "kb.py").read_text(encoding="utf-8")
        self.assertIn("conn.executemany(", src)
        self.assertIn("SELECT id FROM entries", src)

    def test_07_iterate_engine_reuses_scores(self):
        src = (ROOT / "core" / "iterate_engine.py").read_text(encoding="utf-8")
        self.assertIn("X.sentence_vectors(sents, global_scores=global_scores)", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
