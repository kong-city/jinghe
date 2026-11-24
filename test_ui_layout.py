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
        for sym in ('class="sidebar"', 'id="navResizer"',
                    'class="card card-input"', 'class="card card-output"'):
            self.assertIn(sym, self.html, "骨架元素缺失 %s" % sym)
        # 横杠按钮已取消（用户 2026-11-23 裁决），改为双击导航项折叠
        self.assertNotIn('id="btnToggleNav"', self.html, "横杠按钮应已取消")

    def test_02_page_button_ownership_unchanged(self):
        """v1.6.2：四类来源入口统一到首页；加工页回归纯二次加工。
        导航 7 入口与页面骨架不变，只调整按钮归属（详见交付报告）。"""
        home = self.html[self.html.index('id="page-home"'):self.html.index('id="page-process"')]
        proc = self.html[self.html.index('id="page-process"'):self.html.index('id="page-kb"')]
        kb = self.html[self.html.index('id="page-kb"'):self.html.index('id="page-refine"')]
        self.assertIn("btnRun", home)
        self.assertIn("btnPreview", home)
        # 四类内容获取入口（含迁入的订阅）全在首页统一提取台
        for fid in ("btnAudioTranscribe", "btnVideoTranscribe", "btnLinkRun", "subUrl"):
            self.assertIn('id="%s"' % fid, home, "统一提取台缺 %s" % fid)
        # 加工页只留二次加工
        for fid in ("btnSummarize", "btnExportDocx", "btnWordEnhance"):
            self.assertIn('id="%s"' % fid, proc, "加工页缺 %s" % fid)
        self.assertNotIn("btnAudioTranscribe", proc, "音视频入口已迁至首页")
        for fid in ("btnKbIngest", "btnKbRefresh", "kbQuery", "btnKbQuery"):
            self.assertIn('id="%s"' % fid, kb, "知识库页缺 %s" % fid)
        self.assertNotIn("subUrl", kb, "订阅表单已迁至首页统一提取台")

    # ---------- 新布局 ---------- #
    def test_03_nav_grouped_into_four(self):
        self.assertIn('class="nav-group"', self.html)
        self.assertGreaterEqual(self.html.count('class="nav-group"'), 4)
        for g in ("source", "refine-flow", "knowledge", "system"):
            self.assertIn('data-group="%s"' % g, self.html, "缺导航分组 %s" % g)
            self.assertIn('class="nav-group-title"', self.html)
        self.assertIn(".nav-group-title", self.css)
        self.assertIn(".app.nav-collapsed .nav-group-title", self.css)

    def test_04_flow_steps_removed(self):
        # 用户 2026-11-23 裁决：每个功能页都删除全局任务步骤条。
        self.assertNotIn('id="flowSteps"', self.html)
        self.assertNotIn('class="flow-steps"', self.html)
        for step in ("home", "refine", "revise", "kb"):
            self.assertNotIn('data-step="%s"' % step, self.html, "步骤条未删净 %s" % step)
        # CSS 里只允许注释里提及，不允许残留真实选择器规则
        for sym in (".flow-steps {", ".flow-step {", ".flow-step.active {", ".flow-num {"):
            self.assertNotIn(sym, self.css, "步骤条样式未删净 %s" % sym)

    def test_05_step_mapping_removed(self):
        self.assertNotIn("function stepOfPage", self.js)
        self.assertNotIn("stepOfPage(name)", self.js)

    def test_06_steps_highlight_and_click_removed(self):
        self.assertNotIn("el.flowSteps", self.js)
        self.assertNotIn("flowBtns", self.js)
        self.assertNotIn("getAttribute(\"data-step\")", self.js)

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

    def test_09_nav_icon_colors_expand_vs_collapse(self):
        # 用户 2026-11-23 裁决：展开态每个功能图标专属色，折叠态统一深色
        pages = ("home", "process", "refine", "revise", "kb", "settings", "about")
        for p in pages:
            self.assertIn(".app:not(.nav-collapsed) .nav-item[data-page=\"%s\"] svg" % p,
                          self.css, "展开态缺 %s 专属图标色" % p)
        # 折叠态必须统一深色，且规则存在
        self.assertIn(".app.nav-collapsed .nav-item svg { stroke: #1F1F1D; }", self.css)


if __name__ == "__main__":
    unittest.main()
