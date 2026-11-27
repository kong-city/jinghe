#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1.7.9 · 版面后处理实测缺陷修复守护测试。

来源：架构师用桌面两个 PDF 端到端实测 + 三专家轮番审视发现的真实 bug：
- P1(致命)：OCR 产物写 outdir 根，模块却只在 derived/ 找 → 扫描件/CID 降级件
  的版面后处理永远落空（端到端实测：目录0项/合并18行）。
- P0：clean_ocr 只跑 [:2] 条水印模式 → www.epul / WWW.ep 残留；
  「步社区」自我叠加成「异异异步社区」。
- P1：CIP「书名原文」「使用方法」等结构化字段行被错误合并到上一行。
- P2：目录页把广告页脚/页码当目录项；HTML 注释行被合并。
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for _sub in ("core", "media", "knowledge", "link", "subs", "tools"):
    _p = str(ROOT / _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pdf_layout as PL
from clean_ocr import clean


class TestLayoutRobustness(unittest.TestCase):

    # ---------- clean_ocr 实测 bug ----------
    def test_01_all_watermark_patterns_run(self):
        """全部水印模式都要执行（此前 [:2] 漏掉 fragment/异步社区）。"""
        for frag in ("www.epul", "WWW.ep", "WWW.epubit"):
            self.assertEqual(clean(frag).strip(), "",
                             "水印碎片未清除：%r" % frag)

    def test_02_no_typo_self_stack(self):
        """「异异步社区」不能被再次叠加成「异异异步社区」。"""
        out = clean("异异步社区全站所有图书").strip()
        self.assertIn("异步社区", out)
        self.assertNotIn("异异异", out)
        self.assertNotIn("异异步", out)

    def test_03_whitelist_promo_kept(self):
        """白名单促销正文（异步社区全站…）要保留。"""
        self.assertIn("异步社区全站所有图书", clean("异步社区全站所有图书"))

    # ---------- pdf_layout 实测 bug ----------
    def test_04_structured_lines_not_merged(self):
        """CIP 结构化字段行不被合并。"""
        src = ("…订单满50元（不包含运费）即可使用\n"
               "使用方法：在购书单页面，输入96JEQ\n")
        out = PL.reflow_lines(src)
        self.assertIn("即可使用\n使用方法", out)

    def test_05_html_comment_not_merged(self):
        """HTML 注释行不被合并。"""
        src = "<!-- src: doc_abc | path: a.md -->\n正文内容继续写下去没有句号结尾哦\n"
        out = PL.reflow_lines(src)
        self.assertIn("<!-- src: doc_abc | path: a.md -->\n", out)

    def test_06_ellipsis_terminator(self):
        """省略号结尾是段落边界。"""
        src = "他沉默着什么也没有说……\n下一段另起一行讲别的事情\n"
        out = PL.reflow_lines(src)
        self.assertIn("……\n", out)

    def test_07_toc_no_ad_footer(self):
        """广告页脚/价格行不算目录项。"""
        text = ("异步社区全站所有图书所有版本通用订单满50元\n"
                "59.00\n"
                "第一篇　职业\n"
                "第2章从非同凡响开始\n")
        toc = PL.build_toc(text)
        titles = [t["title"] for t in toc]
        self.assertTrue(any("第一篇" in t for t in titles))
        self.assertFalse(any("59" in t or "订单满50" in t for t in titles))

    def test_08_real_ocr_sample_quality(self):
        """真实 OCR 稿：目录与断行都达标（端到端实测回归保护）。"""
        p = Path("C:/Users/Administrator/Desktop/测试文件/"
                 "《软技能：代码之外的生存指南》试读_OCR精校.md")
        if not p.is_file():
            self.skipTest("桌面样本不存在")
        text = p.read_text(encoding="utf-8")
        out, toc = PL.postprocess(text)
        self.assertGreaterEqual(len(toc), 70, "目录识别数量不足")
        self.assertIn("我感到自己被困在公司里工作", out)
        self.assertNotIn("即可使用使用方法", out)
        self.assertNotIn("异异异步社区", out)

    # ---------- 接入层实测 bug ----------
    def test_09_ocr_output_at_outdir_root(self):
        """OCR 产物在 outdir 根时，来源识别必须找到它（致命 bug 回归）。"""
        import tempfile
        import app as AP
        with tempfile.TemporaryDirectory(prefix="jinghe-layout-src-") as td:
            root = Path(td)
            pdf = root / "sample.pdf"
            pdf.write_bytes(b"%PDF-1.4 dummy")
            # 模拟 OCR 产物写在 outdir 根
            (root / "sample.md").write_text("OCR 正文", encoding="utf-8")
            class Job:
                outdir = td
                inputs = [str(pdf)]
            sources = AP._pdf_layout_sources(Job())
            self.assertEqual(len(sources), 1)
            self.assertEqual(sources[0][0].name, "sample.md")

    def test_10_filename_match_strict(self):
        """文件名匹配不能用子串：a.pdf 不能匹配 a2.pdf 的产物。"""
        import tempfile
        import app as AP
        with tempfile.TemporaryDirectory(prefix="jinghe-layout-match-") as td:
            root = Path(td)
            (root / "md").mkdir()
            pdf = root / "a.pdf"
            pdf.write_bytes(b"%PDF-1.4")
            (root / "md" / "001-a2.md").write_text("别的产物", encoding="utf-8")
            class Job:
                outdir = td
                inputs = [str(pdf)]
            sources = AP._pdf_layout_sources(Job())
            self.assertEqual(sources, [], "a.pdf 误匹配了 a2.md")


if __name__ == "__main__":
    unittest.main(verbosity=2)
