#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v0.10 新功能契约测试：默认路径设置 / 组件并发 / OCR 可选增强 / 请求来源校验。"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class TestDefaultPaths(unittest.TestCase):
    """设置页新增默认输入/输出路径（桌面）。"""

    def test_default_settings_have_both_paths(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        m = re.search(r"DEFAULT_SETTINGS\s*=\s*\{(.*?)\n\}", src, re.S)
        self.assertIsNotNone(m)
        self.assertIn('"default_indir"', m.group(1))
        self.assertIn('"default_outdir"', m.group(1))
        self.assertIn("DEFAULT_DESKTOP", m.group(1))

    def test_desktop_uses_known_folder(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("SHGetKnownFolderPath", src, "应使用 Windows Known Folder 取桌面")
        self.assertIn("FOLDERID_Desktop", src)

    def test_ui_has_both_path_fields(self):
        html = (ROOT / "ui/index.html").read_text(encoding="utf-8")
        self.assertIn('id="setDefaultIndir"', html)
        self.assertIn('id="setDefaultOutdir"', html)
        self.assertIn('id="btnPickIndir"', html)
        self.assertIn('id="btnPickOutdir"', html)

    def test_settings_api_exposes_desktop(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('"default_desktop"', src)


class TestComponentConcurrency(unittest.TestCase):
    """组件安装支持真并发（按 cid 独立 job/令牌）。"""

    def setUp(self):
        import components
        self.c = components

    def test_jobs_is_per_component_dict(self):
        self.assertIsInstance(self.c._JOBS, dict, "_JOBS 应为按组件索引的字典")

    def test_opt_in_set_exists(self):
        self.assertIsInstance(self.c._USER_OPT_INS, set, "并发令牌集合应存在")

    def test_new_job_independent(self):
        a = self.c._new_job("ffmpeg")
        b = self.c._new_job("yt-dlp")
        a["percent"] = 42.0
        self.assertEqual(b["percent"], 0.0, "两个 job 不应共享状态")

    def test_status_all_jobs(self):
        st = self.c.install_status(0, "*")
        self.assertIn("jobs", st)
        self.assertIn("running", st)

    def test_status_with_cid(self):
        st = self.c.install_status(0, "ffmpeg")
        self.assertIn("id", st)
        self.assertEqual(st["id"], "ffmpeg")

    def test_concurrent_tokens_independent(self):
        with self.c._LOCK:
            self.c._USER_OPT_INS.discard("ffmpeg")
            self.c._USER_OPT_INS.discard("yt-dlp")
            self.c._USER_OPT_IN["granted"] = False
            self.c._USER_OPT_IN["component_id"] = ""
            self.c._USER_OPT_INS.add("ffmpeg")
            self.c._USER_OPT_INS.add("yt-dlp")
        # 消费 ffmpeg 不影响 yt-dlp
        self.c._require_opt_in("ffmpeg")
        self.c._require_opt_in("yt-dlp")   # 不应抛异常
        with self.assertRaises(RuntimeError):
            self.c._require_opt_in("ffmpeg")   # 重复消费失败
        with self.c._LOCK:
            self.c._USER_OPT_INS.clear()


class TestOptionalOCR(unittest.TestCase):
    """扫描件 PDF 的 tesseract 可选 OCR 增强。"""

    def setUp(self):
        import pdf_ocr
        self.m = pdf_ocr

    def test_module_is_standalone(self):
        src = (ROOT / "pdf_ocr.py").read_text(encoding="utf-8")
        self.assertIn("def status", src)
        self.assertIn("def ocr_pdf", src)

    def test_extract_frozen_unchanged(self):
        # OCR 不得写进冻结内核 extract.py
        src = (ROOT / "extract.py").read_text(encoding="utf-8")
        self.assertNotIn("tesseract", src)
        self.assertNotIn("_pdf_ocr", src)

    def test_status_shape(self):
        st = self.m.status()
        self.assertIn("ok", st)
        self.assertIn("available", st)
        self.assertIn("hint", st)
        self.assertIsInstance(st["available"], bool)

    def test_build_spec_has_ocr_module(self):
        spec = (ROOT / "build.spec").read_text(encoding="utf-8")
        self.assertIn("'pdf_ocr'", spec, "pdf_ocr 必须进 hiddenimports")

    def test_no_auto_download_ocr_tool(self):
        # OCR 模块绝不下载工具，只探测本机
        src = (ROOT / "pdf_ocr.py").read_text(encoding="utf-8")
        self.assertNotIn("pip install", src)
        self.assertNotIn("urlopen", src)


class TestRequestHardening(unittest.TestCase):
    """写操作请求来源校验（CSRF / DNS rebinding 防护）。"""

    def test_check_write_request_exists(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("def _check_write_request", src)
        self.assertIn("def _check_host", src)

    def test_content_type_enforced(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        m = re.search(r"def _check_write_request\(.*?\n    def ", src, re.S)
        self.assertIsNotNone(m)
        body = m.group(0)
        self.assertIn("application/json", body)
        self.assertIn("415", body)

    def test_origin_and_host_checked(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        m = re.search(r"def _check_write_request\(.*?\n    def ", src, re.S)
        self.assertIn('"Origin"', m.group(0))
        self.assertIn("127.0.0.1", m.group(0))
        host = re.search(r"def _check_host\(.*?\n    def ", src, re.S)
        self.assertIsNotNone(host)
        self.assertIn('"Host"', host.group(0))

    def test_get_checks_host(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        m = re.search(r"def do_GET\(.*?\n        try:", src, re.S)
        self.assertIsNotNone(m)
        self.assertIn("_check_host", m.group(0))


if __name__ == "__main__":
    unittest.main()
