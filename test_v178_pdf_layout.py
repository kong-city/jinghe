#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1.7.8 · PDF 版面后处理守护测试（断行重连 + 目录层级还原）。

契约边界（CAPABILITY_CONTRACT.md §1）：
- extract.py 主流水线 / SPEC.md 一字不动；本功能全部落在独立后处理模块。
- 新产物落 derived/，不污染 out/md/ 对账盘。
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

import pdf_layout as PL


class TestPdfLayout(unittest.TestCase):

    def test_01_reflow_joins_broken_sentence(self):
        """PDF 物理断行切在词中间（「我感|到自己」）必须重连成一句。"""
        src = ("在很长的一段时间里我都梦想着有一天能够辞掉我的工作，为自己工作。我感\n"
               "到自己被困在公司里工作，我知道，如果我能自己离开会做得更好。\n")
        out = PL.reflow_lines(src)
        self.assertIn("我感到自己被困在公司里工作", out)
        self.assertNotIn("我感\n", out)

    def test_02_reflow_keeps_cip_entries_separate(self):
        """CIP 版权页的独立条目行不能被误合并（短行保护）。"""
        src = ("[美 ］ John Z. Sonmez 著  王小刚 译\n"
               "中国工信出版集团\n"
               "人民邮电出版社\n"
               "ISBN 978-7-115-42947-6\n")
        out = PL.reflow_lines(src)
        self.assertIn("中国工信出版集团\n人民邮电出版社", out)
        self.assertIn("ISBN 978-7-115-42947-6", out)

    def test_03_reflow_respects_terminators_and_blank_lines(self):
        """终止标点结尾 / 空行 = 段落边界，不合并。"""
        src = "第一句完整结束了。\n第二句是新的段落。\n\n第三段开头。\n"
        out = PL.reflow_lines(src)
        self.assertIn("第一句完整结束了。\n第二句", out)
        self.assertIn("\n\n第三段", out)

    def test_04_reflow_has_merge_cap(self):
        """连续合并有上限，不会把整页连成一个巨型段落。"""
        src = "\n".join("这是第%d行的很长内容没有句号结尾" % i for i in range(12)) + "\n"
        out = PL.reflow_lines(src)
        max_len = max(len(l) for l in out.splitlines())
        self.assertLess(max_len, 300, "出现超长合并行：%d 字" % max_len)

    def test_05_toc_hierarchy(self):
        """目录层级：篇=1、章=2、数字小节=3，且去重补全。"""
        text = ("第一篇　职业\n"
                "第2章\n"
                "从非同凡响开始：绝不要做他人都在做的事\n"
                "第3章思考未来：你的目标是什么10\n"
                "第2章\n"
                "从非同凡响开始：绝不要做他人都在做的事\n")
        toc = PL.build_toc(text)
        self.assertEqual(toc[0]["level"], 1)
        self.assertTrue(any(t["level"] == 2 and "从非同凡响" in t["title"] for t in toc))
        self.assertEqual(sum(1 for t in toc if "从非同凡响" in t["title"]), 1,
                         "重复章节未去重")
        self.assertTrue(any("思考未来" in t["title"] for t in toc))

    def test_06_toc_render(self):
        toc = [{"level": 1, "title": "第一篇 职业"},
               {"level": 2, "title": "第2章 开篇"}]
        md = PL.render_toc(toc)
        self.assertIn("## 目录", md)
        self.assertIn("- 第一篇 职业", md)
        self.assertIn("  - 第2章 开篇", md)

    def test_07_postprocess_combines(self):
        # 用接近满行的真实断行形态（PDF 栏宽切断的典型长度）
        text = ("第一篇　职业\n"
                "第1章标题\n"
                "在很长的一段时间里我都梦想着有一天能够辞掉我的工作，为自己工作。我感\n"
                "到自己被困在公司里工作，我知道，如果我能自己离开会做得更好。\n")
        out, toc = PL.postprocess(text)
        self.assertIn("我感到自己被困在公司里工作", out)
        self.assertTrue(toc)

    def test_08_frozen_core_untouched(self):
        """冻结内核契约：extract.py / SPEC.md 未被本功能改动。"""
        ex = (ROOT / "extract.py").read_text(encoding="utf-8")
        self.assertIn("def _pdf_runs_to_text", ex)  # 原函数仍在
        # 断行重连逻辑不写进内核
        self.assertNotIn("pdf_layout", ex)

    def test_09_wired_in_app_and_spec(self):
        """接入点：app.py 调用后处理；build.spec 含新模块（打包可用）。"""
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        spec = (ROOT / "build.spec").read_text(encoding="utf-8")
        self.assertIn("import pdf_layout", app)
        self.assertIn("_pdf_layout_postprocess(job)", app)
        self.assertIn("'pdf_layout'", spec)

    def test_10_output_not_pollute_md_dir(self):
        """新产物只写 derived/，绝不写 out/md/（对账红线）。"""
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        fn = src[src.index("def _pdf_layout_postprocess"):src.index("def _error_tail")]
        self.assertIn("media_runtime.ensure_derived", fn)
        self.assertIn("_目录与连贯.md", fn)
        self.assertNotIn("/ 'md'", fn)


if __name__ == "__main__":
    unittest.main(verbosity=2)
