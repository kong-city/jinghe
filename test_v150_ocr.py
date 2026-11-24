#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1.5.0 · OCR 组件化 + 状态条按需提示的守护测试。

用户 2026-11-23 裁决：
1. 扫描件 OCR 从外部 tesseract+poppler 工具链改为 pip 组件（pylib），
   像其他组件一样「点击就能装」；
2. 删除状态条常驻的全部能力长文字，只在组件未就绪时提示 + 引导安装。

守护要点：
    OCR-1  OCR 注册为 pylib 组件（probe_module / 多包 package）
    OCR-2  多包 pip 命令拆成独立 argv
    OCR-3  pylib 探测走严格 import 校验（假绿灯防护）
    OCR-4  OCR worker 存在且用 pymupdf+rapidocr
    OCR-5  pdf_ocr 对外接口不变、引擎已换成子进程
    OCR-6  前端 OCR 假组件行已删、走统一安装
    OCR-7  状态条按需渲染：仅未就绪项 + 去启用，无常驻长文字
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for _sub in ("core", "media", "knowledge", "link", "subs"):
    _p = str(ROOT / _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import unittest


class TestV150OcrComponent(unittest.TestCase):

    def setUp(self) -> None:
        self.ocr_comp = None
        sys.path.insert(0, str(ROOT / "knowledge"))
        import components
        self.components = components
        for c in components.COMPONENTS:
            if c["id"] == "ocr":
                self.ocr_comp = c
        self.ui_js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        self.ui_html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")

    def test_01_ocr_registered_as_pylib(self) -> None:
        self.assertIsNotNone(self.ocr_comp, "COMPONENTS 缺 ocr 组件")
        self.assertEqual(self.ocr_comp["kind"], "pylib", "OCR 应为 pylib 类型")
        self.assertIn("probe_module", self.ocr_comp, "pylib 缺 probe_module")
        self.assertIn("fitz", self.ocr_comp["probe_module"])
        self.assertIn("rapidocr_onnxruntime", self.ocr_comp["probe_module"])
        self.assertIn("pymupdf", self.ocr_comp["package"])
        self.assertIn("rapidocr-onnxruntime", self.ocr_comp["package"])

    def test_02_multipackage_pip_argv(self) -> None:
        cmd = self.components._pip_cmd_install("pymupdf rapidocr-onnxruntime")
        self.assertIn("pymupdf", cmd)
        self.assertIn("rapidocr-onnxruntime", cmd)
        # 两个包必须是独立 argv，不能是一个含空格的参数
        self.assertNotIn("pymupdf rapidocr-onnxruntime", cmd,
                         "多包未被拆成独立 argv")

    def test_03_strict_import_no_false_green(self) -> None:
        """假绿灯防护：不存在的 python 必须判为不可用（不是宽容 True）。"""
        ok, reason = self.components._import_check_strict(
            "C:/nonexistent/python.exe", ["fitz"])
        self.assertFalse(ok, "严格校验把不存在的解释器误判为可用")
        self.assertIn("不存在", reason)

    def test_04_worker_exists(self) -> None:
        worker = ROOT / "tools" / "ocr_worker.py"
        self.assertTrue(worker.is_file(), "缺 OCR worker 脚本")
        src = worker.read_text(encoding="utf-8")
        self.assertIn("fitz", src, "worker 未用 pymupdf")
        self.assertIn("RapidOCR", src, "worker 未用 rapidocr")
        self.assertIn("--max-pages", src)

    def test_05_pdf_ocr_api_kept(self) -> None:
        import pdf_ocr
        for fn in ("status", "ocr_pdf", "ocr_pdf_to_md"):
            self.assertTrue(hasattr(pdf_ocr, fn), "pdf_ocr 缺接口 %s" % fn)
        src = (ROOT / "media" / "pdf_ocr.py").read_text(encoding="utf-8")
        self.assertIn("ocr_worker.py", src, "pdf_ocr 未改用 worker 子进程")
        self.assertNotIn("pdftoppm", src, "pdf_ocr 仍在用 poppler")
        self.assertNotIn("tesseract", src, "pdf_ocr 仍在用 tesseract")

    def test_06_frontend_unified_install(self) -> None:
        self.assertNotIn('ocrState = ', self.ui_js,
                         "前端仍有 OCR 独立状态变量")
        self.assertNotIn("查看安装指引", self.ui_js,
                         "前端仍有 OCR 假组件的「查看安装指引」按钮")
        # OCR 通过统一组件清单渲染（清单里含 ocr 组件由 test_01 守护）

    def test_07_status_on_demand(self) -> None:
        """状态条：仅未就绪项 + 去启用，无常驻长文字。"""
        fn = self.ui_js[self.ui_js.index("function renderToolStatus"):
                        self.ui_js.index("function loadTools")]
        # 保留音视频真实状态读取（test_v140_fixes 守护）
        self.assertIn("音频转写：", fn)
        self.assertIn("视频提取：", fn)
        self.assertIn("at.enabled", fn)
        self.assertIn("vt.enabled", fn)
        # 新行为：收集 missing、去启用按钮、全就绪则隐藏
        self.assertIn("missing", fn, "未实现「仅收集未就绪项」")
        self.assertIn("去启用", fn, "未给出去启用引导")
        self.assertIn("el.toolStatus.hidden = true", fn,
                      "全部就绪时未隐藏状态条")
        self.assertIn("activatePage(\"settings\")", fn,
                      "去启用未跳转到设置页")
        # 旧常驻长文字已删除
        self.assertNotIn('"本机工具：" + parts.join', fn,
                         "仍显示常驻的「本机工具：…」长文字")
        self.assertNotIn('"Word 输入增强：" +', fn,
                         "仍显示常驻的 Word 输入增强状态")
        # HTML 容器支持放按钮（div 而非 p）
        self.assertIn('<div id="toolStatus"', self.ui_html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
