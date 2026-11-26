#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1.7.2 · OCR 质量与并发优化守护测试。

锁定本轮 4 项改动（全部在独立后处理层，冻结内核 extract.py 零改动）：
1. worker 保留置信度并输出旁车 + 内联清洗（水印 / 误识 / 断行）；
2. pdf_ocr 读回置信度、force 参数修复「部分乱码被跳过」漏洞；
3. app.py OCR 后处理并发（按 CPU 核数，上限 4）且降级件强制重跑；
4. build.spec 把 clean_ocr.py 随包携带（否则打包态 worker 无法清洗）。
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent
for _sub in ("core", "media", "knowledge", "link", "subs"):
    _p = str(ROOT / _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestWorkerQuality(unittest.TestCase):

    def test_01_confidence_of_keeps_scores(self):
        """worker 的置信度解析：取 item[2]，过滤越界与非数值。"""
        src = (ROOT / "tools" / "ocr_worker.py").read_text(encoding="utf-8")
        sys.path.insert(0, str(ROOT / "tools"))
        import ocr_worker
        avg, n = ocr_worker._confidence_of([
            ([0, 0, 1, 1], "甲", 0.9),
            ([0, 0, 1, 1], "乙", 0.7),
            ([0, 0, 1, 1], "丙", 1.5),   # 越界，忽略
            ([0, 0, 1, 1], "丁", "x"),   # 非数值，忽略
            ("too-short",),
        ])
        self.assertEqual(n, 2)
        self.assertAlmostEqual(avg, 0.8, places=3)
        self.assertIn("meta.json", src, "worker 必须写置信度旁车")

    def test_02_cleaner_inline_fallback(self):
        """清洗器优先复用 clean_ocr，缺失时退化为内置最小清洗。"""
        sys.path.insert(0, str(ROOT / "tools"))
        import ocr_worker
        cleaner = ocr_worker._load_cleaner()
        self.assertTrue(callable(cleaner))
        # 清洗器应折叠多余空行并保留正文（水印行会被 clean_ocr 按既定规则删除）
        self.assertEqual(cleaner("甲\n\n\n\n乙").strip(), "甲\n\n乙")

    def test_03_build_spec_carries_cleaner(self):
        """打包态 worker 要 import clean_ocr，必须随包携带。"""
        spec = (ROOT / "build.spec").read_text(encoding="utf-8")
        self.assertIn("tools/clean_ocr.py", spec)


class TestPdfOcrForce(unittest.TestCase):

    def test_04_force_signature_present(self):
        """ocr_pdf_to_md 必须有 force 可选参数且不破坏原签名调用。"""
        import inspect
        import pdf_ocr
        sig = inspect.signature(pdf_ocr.ocr_pdf_to_md)
        self.assertIn("force", sig.parameters)
        self.assertEqual(sig.parameters["force"].default, False)
        for fn in ("status", "ocr_pdf", "ocr_pdf_to_md"):
            self.assertTrue(hasattr(pdf_ocr, fn))

    def test_05_quality_hint_text(self):
        """置信度提示文案：含平均分与低置信页号。"""
        import pdf_ocr
        hint = pdf_ocr._quality_hint({
            "avg_confidence": 0.55,
            "low_confidence_pages": [3, 7],
        })
        self.assertIn("0.55", hint)
        self.assertIn("3,7", hint)
        self.assertIn("复核", hint)
        self.assertEqual(pdf_ocr._quality_hint({}), "")

    def test_06_force_overwrites_existing(self):
        """force=True 时即使已有 >40 字产物也必须重跑并覆盖。"""
        import pdf_ocr
        with tempfile.TemporaryDirectory() as td:
            pdf = Path(td) / "doc.pdf"
            pdf.write_bytes(b"%PDF-1.4 dummy")
            md = Path(td) / "doc.md"
            md.write_text("# 旧产物\n" + "乱码" * 60, encoding="utf-8")
            calls = []

            def fake_raw(path, max_pages=0):
                calls.append((str(path), max_pages))
                return "全新 OCR 正文", "成功（OCR）", {"avg_confidence": 0.91}

            with mock.patch.object(pdf_ocr, "_ocr_pdf_raw", side_effect=fake_raw):
                res = pdf_ocr.ocr_pdf_to_md(pdf, td, force=True)
            self.assertTrue(res["ok"])
            self.assertFalse(res["skipped"])
            self.assertEqual(len(calls), 1, "force=True 不应跳过")
            self.assertIn("全新 OCR 正文", md.read_text(encoding="utf-8"))
            self.assertIn("ocr:", md.read_text(encoding="utf-8"), "应有溯源注释")

    def test_07_no_force_skips_existing(self):
        """force=False 保持旧行为：已有 >40 字产物跳过。"""
        import pdf_ocr
        with tempfile.TemporaryDirectory() as td:
            pdf = Path(td) / "doc.pdf"
            pdf.write_bytes(b"%PDF-1.4 dummy")
            md = Path(td) / "doc.md"
            old = "# 旧产物\n" + "正文" * 60
            md.write_text(old, encoding="utf-8")
            with mock.patch.object(pdf_ocr, "_ocr_pdf_raw") as fake:
                res = pdf_ocr.ocr_pdf_to_md(pdf, td)
            self.assertTrue(res.get("skipped"))
            fake.assert_not_called()
            self.assertEqual(md.read_text(encoding="utf-8"), old)


class TestAppParallel(unittest.TestCase):

    def test_08_parallel_limit_by_cpu(self):
        """并发路数 = min(cpu, 4, 文件数)；单文件必串行。"""
        import app
        self.assertEqual(app._ocr_parallel_limit(["a.pdf"]), 1)
        with mock.patch.object(app.os, "cpu_count", return_value=16):
            self.assertEqual(app._ocr_parallel_limit(["a", "b", "c"]), 3)
            self.assertEqual(app._ocr_parallel_limit(["a", "b", "c", "d", "e"]), 4)
        with mock.patch.object(app.os, "cpu_count", return_value=2):
            self.assertEqual(app._ocr_parallel_limit(["a", "b", "c"]), 2)

    def test_09_ocr_block_keeps_diagnosis(self):
        """并发改造不得破坏「组件不可用仍输出诊断」的既有守护。"""
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        block = src[src.index("ocr_st = pdf_ocr.status()"):
                    src.index("except Exception as exc:", src.index("ocr_st = pdf_ocr.status()"))]
        self.assertIn("else:", block)
        self.assertIn("_ocr_degraded_names(job.outdir)", block)
        self.assertIn("_ocr_guidance(False", block)
        self.assertIn('job.add("log"', block)
        self.assertIn("ThreadPoolExecutor", block)
        self.assertIn("_ocr_one(src, job.outdir, force)", block)
        self.assertIn("Path(src).name in degraded", block)

    def test_10_frozen_core_unchanged(self):
        """冻结内核 extract.py 主流水线本轮零改动（版本号行允许随升号变化）。

        契约冻结的是「探测/分流/提取/汇总/对账主流水线」，不是版本号常量；
        每次升号都会改 __version__，这是唯一允许的改动。
        """
        import subprocess
        diff = subprocess.run(
            ["git", "diff", "extract.py"],
            cwd=str(ROOT), capture_output=True, text=True)
        changed = [
            ln for ln in diff.stdout.splitlines()
            if (ln.startswith("+") or ln.startswith("-"))
            and not ln.startswith("+++") and not ln.startswith("---")
        ]
        unexpected = [ln for ln in changed if "__version__" not in ln]
        self.assertEqual(unexpected, [], "extract.py 主流水线被改动，违反冻结契约")
