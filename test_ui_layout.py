#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S14 · UI 信息架构重组 · 回归测试。

守护：①导航按任务流归为 4 组、7 个入口本身不变；②全局步骤条 4 步且
映射正确；③加工页流程指引可跳转；④旧 UI 契约（7 页面/顺序/锚点按钮）
一条不破 —— 这次改造的原则是「重做引导层，保留兼容骨架」。
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class TestUILayout(unittest.TestCase):

    def setUp(self):
        self.html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        self.js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        self.css = (ROOT / "ui" / "app.css").read_text(encoding="utf-8")

    # ---------- 旧契约不破 ---------- #
    def test_01_seven_pages_intact(self):
        pages = ("home", "process", "kb", "refine", "revise", "settings", "about")
        positions = []
        for p in pages:
            self.assertIn('data-page="%s"' % p, self.html, "导航缺 %s" % p)
            pos = self.html.find('id="page-%s"' % p)
            self.assertGreater(pos, -1, "缺页面容器 %s" % p)
            positions.append(pos)
            self.assertIn("%s: $(" % p, self.js, "el.pages 缺 %s" % p)
            self.assertIn("%s: { title:" % p, self.js, "PAGE_META 缺 %s" % p)
        self.assertEqual(positions, sorted(positions), "页面物理顺序被破坏")
        for sym in ('class="sidebar"', 'id="btnToggleNav"', 'id="navResizer"',
                    'class="card card-input"', 'class="card card-output"'):
            self.assertIn(sym, self.html, "骨架元素缺失 %s" % sym)

    def test_02_page_button_ownership_unchanged(self):
        home = self.html[self.html.index('id="page-home"'):self.html.index('id="page-process"')]
        proc = self.html[self.html.index('id="page-process"'):self.html.index('id="page-kb"')]
        kb = self.html[self.html.index('id="page-kb"'):self.html.index('id="page-refine"')]
        self.assertIn("btnRun", home)
        self.assertIn("btnPreview", home)
        for fid in ("btnSummarize", "btnExportDocx", "btnWordEnhance",
                    "btnAudioTranscribe", "btnVideoTranscribe", "btnLinkRun"):
            self.assertIn('id="%s"' % fid, proc, "加工页缺 %s" % fid)
        for fid in ("btnKbIngest", "btnKbRefresh", "kbQuery", "btnKbQuery"):
            self.assertIn('id="%s"' % fid, kb, "知识库页缺 %s" % fid)

    # ---------- 新布局 ---------- #
    def test_03_nav_grouped_into_four(self):
        self.assertIn('class="nav-group"', self.html)
        self.assertGreaterEqual(self.html.count('class="nav-group"'), 4)
        for g in ("source", "refine-flow", "knowledge", "system"):
            self.assertIn('data-group="%s"' % g, self.html, "缺导航分组 %s" % g)
            self.assertIn('class="nav-group-title"', self.html)
        self.assertIn(".nav-group-title", self.css)
        self.assertIn(".app.nav-collapsed .nav-group-title", self.css)

    def test_04_flow_steps_present(self):
        self.assertIn('id="flowSteps"', self.html)
        for step in ("home", "refine", "revise", "kb"):
            self.assertIn('data-step="%s"' % step, self.html, "步骤条缺 %s" % step)
            self.assertIn('"%s"' % step, self.js)
        for sym in (".flow-steps", ".flow-step", ".flow-step.active", ".flow-num"):
            self.assertIn(sym, self.css, "步骤条样式缺 %s" % sym)

    def test_05_step_mapping(self):
        self.assertIn("function stepOfPage", self.js)
        seg = self.js[self.js.index("function stepOfPage"):]
        seg = seg[:seg.index("function setNavCollapsed")]
        self.assertIn('name === "home" || name === "process"', seg)
        self.assertIn('return "home"', seg)
        self.assertIn('name === "kb") return "kb"', seg)

    def test_06_steps_highlight_and_click(self):
        self.assertIn("var activeStep = stepOfPage(name)", self.js)
        self.assertIn('steps[si].getAttribute("data-step") === activeStep', self.js)
        self.assertIn('flowBtns[fi].addEventListener("click"', self.js)

    def test_07_process_guide_links(self):
        self.assertIn('id="flowGuide"', self.html)
        guide = self.html[self.html.index('id="flowGuide"'):self.html.index('id="page-refine"')]
        for target in ("refine", "revise", "kb"):
            self.assertIn('data-goto="%s"' % target, guide, "指引缺跳转 %s" % target)
        self.assertIn("document.querySelectorAll(\"[data-goto]\")", self.js)

    def test_08_no_new_api_or_id_breakage(self):
        # 改造只动 UI 层，不新增/删除后端端点
        for ep in ("/api/refine/start", "/api/revise/start", "/api/kb/ingest",
                   "/api/sub/list", "/api/sub/scheduler"):
            self.assertIn(ep, self.js, "端点丢失 %s" % ep)
        # 加工页不得出现僵尸占位（旧断言）
        proc = self.html[self.html.index('id="page-process"'):self.html.index('id="page-kb"')]
        self.assertNotIn("规划中", proc)
        self.assertNotIn("btnTranscribe", proc)


if __name__ == "__main__":
    unittest.main()
