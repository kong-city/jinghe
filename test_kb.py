
# -*- coding: utf-8 -*-
"""S9 阶段 4 知识库红线测试（纯标准库 unittest，不访问网络）。

覆盖 S9 立项文档 §5 安全契约与 §8 验收口径：
* 块锚点解析（含 S8 的 ``| blocks: 2,7`` 多块锚点）
* 入库去重（doc_id + block + 内容 hash）
* 路径围栏（拒绝越界目录 / 文件）
* 检索：trigram（≥3 字符中文子串）+ LIKE 降级（2 字词）
* AI 补写隔离（``[AI ++ … ++]`` / 「AI 补充」分区默认不入库）
* 不造假（只重组产物正文，入库后正文与原文逐字一致）
"""


# JINGHE_LAYOUT_BOOTSTRAP
import sys as _jinghe_sys
from pathlib import Path as _jinghe_Path
_jinghe_root = _jinghe_Path(__file__).resolve().parent
for _jinghe_sub in ("core", "media", "knowledge", "link", "subs"):
    _jinghe_p = str(_jinghe_root / _jinghe_sub)
    if _jinghe_p not in _jinghe_sys.path:
        _jinghe_sys.path.insert(0, _jinghe_p)
# END JINGHE_LAYOUT_BOOTSTRAP
import tempfile
import unittest
from pathlib import Path

import kb


def _sample_md():
    """一份符合 extract.py 产物格式的样例（src 注释 + 3 个块锚点）。"""
    return """<!-- source: chapter.txt | format: .txt | extracted: 2026-11-18 -->
<!-- src: doc_abc123def45 | path: chapter.txt | format: .txt | converter: 内置零依赖解析 | extracted: 2026-11-18 | size: 100 | sha256: deadbeefcafe | anchors: block,line -->

<!-- anchor: doc_abc123def45 | block: 1 | line: 1..2 -->
# 第一章 知识提取的边界

<!-- anchor: doc_abc123def45 | block: 2 | line: 3..4 -->
## 1.1 文字层
文字层 PDF 可直接提取文本，保留标题层级。

<!-- anchor: doc_abc123def45 | block: 3 | line: 5..6 -->
## 1.2 扫描件
扫描件没有文字层，必须先做 OCR；未配置 OCR 时不得交付空文件。
"""


def _md_with_ai():
    return _sample_md() + """
<!-- anchor: doc_abc123def45 | block: 4 -->
## AI 补充（模型生成，请核对）
> 以下内容由模型补写，原文并不存在
[AI ++ 这是模型编造的补充内容 ++]
"""


class TestParseEntries(unittest.TestCase):
    def test_src_fields(self):
        p = kb.parse_md_entries(_sample_md())
        self.assertEqual(p["doc_id"], "doc_abc123def45")
        self.assertEqual(p["sha256"], "deadbeefcafe")
        self.assertEqual(p["src"]["format"], ".txt")

    def test_block_split(self):
        p = kb.parse_md_entries(_sample_md())
        self.assertEqual([e["block"] for e in p["entries"]], [1, 2, 3])
        self.assertIn("line: 1..2", p["entries"][0]["locator"])

    def test_body_roundtrip_no_fabrication(self):
        """不造假：入库正文必须与原文逐字一致（去掉注释后）。"""
        p = kb.parse_md_entries(_sample_md())
        bodies = {e["block"]: e["body"] for e in p["entries"]}
        self.assertTrue(bodies[2].startswith("## 1.1 文字层"))
        self.assertIn("可直接提取文本，保留标题层级", bodies[2])

    def test_html_comment_stripped(self):
        md = _sample_md().replace(
            "文字层 PDF", "<!-- 本页无文本 -->\n文字层 PDF")
        p = kb.parse_md_entries(md)
        b = [e for e in p["entries"] if e["block"] == 2][0]["body"]
        self.assertNotIn("<!--", b)
        self.assertIn("文字层 PDF", b)


class TestIngestDedup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kbdir = str(Path(self.tmp) / "kb")
        self.prod = Path(self.tmp) / "product"
        (self.prod / "md").mkdir(parents=True)
        (self.prod / "md" / "001-chapter.md").write_text(
            _sample_md(), encoding="utf-8")

    def test_ingest_then_dedup(self):
        r1 = kb.ingest_dir(self.kbdir, str(self.prod),
                           allowed_roots=[self.tmp])
        self.assertTrue(r1["ok"])
        self.assertEqual(r1["added"], 3)
        self.assertEqual(r1["duplicate"], 0)
        r2 = kb.ingest_dir(self.kbdir, str(self.prod),
                           allowed_roots=[self.tmp])
        self.assertEqual(r2["added"], 0)
        self.assertEqual(r2["duplicate"], 3)
        self.assertEqual(kb.kb_status(self.kbdir)["entries"], 3)

    def test_idempotent_init(self):
        kb.init_kb(self.kbdir)
        kb.init_kb(self.kbdir)
        self.assertTrue(kb.kb_status(self.kbdir)["initialized"])

    def test_reset(self):
        kb.ingest_dir(self.kbdir, str(self.prod), allowed_roots=[self.tmp])
        r = kb.reset_kb(self.kbdir)
        self.assertTrue(r["ok"])
        self.assertEqual(kb.kb_status(self.kbdir)["entries"], 0)


class TestPathGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kbdir = str(Path(self.tmp) / "kb")
        self.prod = Path(self.tmp) / "product"
        self.prod.mkdir()
        (self.prod / "a.md").write_text(_sample_md(), encoding="utf-8")

    def test_reject_outside_dir(self):
        r = kb.ingest_dir(self.kbdir, str(Path(self.tmp) / "other"),
                          allowed_roots=[str(self.prod)])
        self.assertFalse(r["ok"])
        self.assertIn("允许范围", r["error"])

    def test_reject_file_outside(self):
        r = kb.ingest_md(self.kbdir, str(self.prod / "a.md"),
                         allowed_roots=[str(Path(self.tmp) / "other")])
        self.assertFalse(r["ok"])

    def test_open_source_guard(self):
        kb.ingest_md(self.kbdir, str(self.prod / "a.md"),
                     allowed_roots=[self.tmp])
        r = kb.open_source(self.kbdir, "doc_abc123def45#1",
                           allowed_roots=[str(Path(self.tmp) / "other")])
        self.assertFalse(r["ok"])
        self.assertIn("允许范围", r["error"])


class TestQuery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kbdir = str(Path(self.tmp) / "kb")
        p = Path(self.tmp) / "a.md"
        p.write_text(_sample_md(), encoding="utf-8")
        kb.ingest_md(self.kbdir, str(p), allowed_roots=[self.tmp])

    def test_trigram_chinese_substring(self):
        r = kb.query(self.kbdir, "知识提取")
        self.assertTrue(r["ok"])
        self.assertIn(r["mode"], ("trigram", "like"))
        self.assertGreaterEqual(r["count"], 1)
        self.assertEqual(r["results"][0]["doc_id"], "doc_abc123def45")

    def test_short_word_like_fallback(self):
        r = kb.query(self.kbdir, "边界")  # 2 字 → LIKE
        self.assertTrue(r["ok"])
        self.assertEqual(r["mode"], "like")
        self.assertGreaterEqual(r["count"], 1)

    def test_empty_query(self):
        r = kb.query(self.kbdir, "  ")
        self.assertFalse(r["ok"])

    def test_result_has_provenance(self):
        r = kb.query(self.kbdir, "扫描件")
        self.assertGreaterEqual(r["count"], 1)
        first = r["results"][0]
        for key in ("id", "doc_id", "block", "locator", "source_file", "sha256"):
            self.assertIn(key, first)


class TestAIIsolation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.kbdir = str(Path(self.tmp) / "kb")

    def test_ai_marked_and_skipped_by_default(self):
        p = kb.parse_md_entries(_md_with_ai())
        ai = [e for e in p["entries"] if e["block"] == 4]
        self.assertEqual(len(ai), 1)
        self.assertTrue(ai[0]["is_ai"])
        md = Path(self.tmp) / "ai.md"
        md.write_text(_md_with_ai(), encoding="utf-8")
        r = kb.ingest_md(self.kbdir, str(md), allowed_roots=[self.tmp])
        self.assertEqual(r["skipped_ai"], 1)
        self.assertEqual(r["added"], 3)

    def test_include_ai_optin(self):
        md = Path(self.tmp) / "ai.md"
        md.write_text(_md_with_ai(), encoding="utf-8")
        r = kb.ingest_md(self.kbdir, str(md),
                         include_ai=True, allowed_roots=[self.tmp])
        self.assertEqual(r["added"], 4)
        self.assertEqual(r["skipped_ai"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
