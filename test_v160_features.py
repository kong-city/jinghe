#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1.6.0 · 三项剩余功能的守护测试。

用户 2026-11-24 裁决「还有哪些没上的功能开始上」，本轮实现：
1. 一键流水线（S9 §3.3）：提取 → 提纯 → 入库一次点击串联
2. 便携 Python 运行时兜底（RUNTIME_DIR 从零引用到真实可用）
3. S12c 直播回放专门支持（分类 + 诚实拒绝实时直播 + UI 文案）

守护要点：
    F1  一键流水线后端编排函数 + 端点 + 降级不丢内容
    F2  前端「提取并入库」按钮 + finish 自动串联
    F3  便携运行时配置 + 下载红线（无令牌拒下载）+ 兜底接线
    F4  S12c URL 分类 + 实时直播拒绝 + UI 诚实文案
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for _sub in ("core", "media", "knowledge", "link", "subs"):
    _p = str(ROOT / _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import unittest


class TestV160Features(unittest.TestCase):

    def setUp(self) -> None:
        self.ui_js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        self.ui_html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        self.app_src = (ROOT / "app.py").read_text(encoding="utf-8")

    # ---------------- F1 一键流水线 ---------------- #
    def test_01_pipeline_backend(self) -> None:
        self.assertIn("def _pipeline_finish(", self.app_src)
        self.assertIn('path == "/api/pipeline/finish"', self.app_src)
        # 复用订阅提纯器 + kb 幂等入库，不重复造轮子
        fn = self.app_src[self.app_src.index("def _pipeline_finish("):
                          self.app_src.index("def _update_plan(")]
        self.assertIn("default_iterate_fn", fn, "未复用订阅抽取式提纯器")
        self.assertIn("kb.ingest_md", fn, "未复用 kb 幂等入库")
        self.assertIn("_kb_allowed_roots", fn, "未走产物目录围栏")
        self.assertIn("to_ingest.append(md)", fn, "提纯失败未降级回原文")

    def test_02_pipeline_e2e(self) -> None:
        """造一批产物实测提纯+入库编排。"""
        import app as app_mod
        tmp = Path(tempfile.mkdtemp(prefix="v160-pipe-"))
        prod = tmp / "out-test"
        (prod / "md").mkdir(parents=True)
        (prod / "md" / "001-demo.md").write_text(
            "# 标题\n\n第一段正文含关键知识点。\n\n## 小节\n\n第二段实质内容。",
            encoding="utf-8")
        old_written = set(app_mod._WRITTEN_OUTDIRS)
        old_kb = app_mod.KB_DIR
        try:
            app_mod._WRITTEN_OUTDIRS.add(str(prod))
            app_mod.KB_DIR = tmp / "kb"
            r = app_mod._pipeline_finish(str(prod))
            self.assertTrue(r["ok"])
            self.assertEqual(r["sources"], 1)
            self.assertEqual(r["refined"], 1, "应提纯 1 份")
            self.assertGreaterEqual(r["ingested"], 1, "应入库至少 1 条")
            self.assertEqual(r["refine_failed"], [])
        finally:
            app_mod._WRITTEN_OUTDIRS.clear()
            app_mod._WRITTEN_OUTDIRS.update(old_written)
            app_mod.KB_DIR = old_kb

    def test_03_pipeline_fence(self) -> None:
        """越权目录必须被拒。"""
        import app as app_mod
        r = app_mod._pipeline_finish("C:/Windows/System32")
        self.assertFalse(r["ok"])
        self.assertIn("允许范围", r["error"])

    def test_04_pipeline_frontend(self) -> None:
        self.assertIn('id="btnRunAndIngest"', self.ui_html, "缺一键流水线按钮")
        self.assertIn("function doRunAndIngest(", self.ui_js)
        self.assertIn("function finishPipeline(", self.ui_js)
        self.assertIn('"/api/pipeline/finish"', self.ui_js)
        # extract 完成后自动串联（仅流水线模式）
        finish_fn = self.ui_js[self.ui_js.index("function finish("):
                               self.ui_js.index("function doCancel(")]
        self.assertIn("if (pipelineMode) finishPipeline", finish_fn)

    # ---------------- F2 便携运行时 ---------------- #
    def test_05_runtime_config(self) -> None:
        sys.path.insert(0, str(ROOT / "knowledge"))
        import components as c
        self.assertTrue(str(c.RUNTIME_DIR).endswith("runtime"))
        self.assertTrue(c.RUNTIME_PYTHON.name.lower() == "python.exe")
        self.assertIn("python.org", c.RUNTIME_URL)
        self.assertIn("embed", c.RUNTIME_URL)
        self.assertTrue(hasattr(c, "_ensure_runtime_python"))

    def test_06_runtime_redline(self) -> None:
        """无手动令牌时，便携运行时下载必须被拒（绝不主动下载）。"""
        sys.path.insert(0, str(ROOT / "knowledge"))
        import components as c
        old_set = set(c._USER_OPT_INS)
        old_legacy = dict(c._USER_OPT_IN)
        try:
            c._USER_OPT_INS.clear()
            c._USER_OPT_IN.update({"granted": False, "component_id": ""})
            with self.assertRaises(RuntimeError) as ctx:
                c._download(c.RUNTIME_URL, c.RUNTIME_DIR / "redline-test.zip", "ocr")
            self.assertIn("手动启用授权", str(ctx.exception))
        finally:
            c._USER_OPT_INS.clear()
            c._USER_OPT_INS.update(old_set)
            c._USER_OPT_IN.clear()
            c._USER_OPT_IN.update(old_legacy)

    def test_07_runtime_wired(self) -> None:
        src = (ROOT / "knowledge" / "components.py").read_text(encoding="utf-8")
        fn = src[src.index("def _ensure_venv("):src.index("def _python_for_pip(")]
        self.assertIn("component_id", fn, "venv 创建未接收组件 id")
        self.assertIn("_ensure_runtime_python", fn, "venv 创建未接便携运行时兜底")

    # ---------------- F3 S12c ---------------- #
    def test_08_s12c_classify(self) -> None:
        sys.path.insert(0, str(ROOT / "subs"))
        sys.path.insert(0, str(ROOT / "link"))
        import channel_discovery as cd
        cases = [
            ("https://live.bilibili.com/12345", "live", False),
            ("https://live.douyin.com/abc", "live", False),
            ("https://www.bilibili.com/video/BV1xx", "replay", True),
            ("https://www.youtube.com/watch?v=abc", "replay", True),
            ("https://space.bilibili.com/123", "channel", True),
        ]
        for url, kind, supported in cases:
            r = cd.classify_url(url)
            self.assertEqual(r["kind"], kind, "分类错误：%s" % url)
            self.assertEqual(r["supported"], supported)

    def test_09_s12c_live_rejected(self) -> None:
        sys.path.insert(0, str(ROOT / "subs"))
        sys.path.insert(0, str(ROOT / "link"))
        import channel_discovery as cd
        r = cd.discover("https://live.bilibili.com/12345")
        self.assertFalse(r["ok"])
        self.assertIn("实时直播", r["error"])
        self.assertIn("kind", r)

    def test_10_s12c_ui_honest(self) -> None:
        self.assertIn("直播回放链接", self.ui_html, "UI 未披露回放链接支持")
        self.assertIn("实时直播", self.ui_html, "UI 未披露实时直播不支持")
        self.assertIn("liveMarkers", self.ui_js, "前端未做实时直播诚实拒绝")
        self.assertIn("isReplay", self.ui_js, "前端未对回放链接给专属提示")


if __name__ == "__main__":
    unittest.main(verbosity=2)
