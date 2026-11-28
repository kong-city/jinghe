#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S14 · UI 信息架构重组 · 回归测试。

守护：①导航按任务流归为 4 组、6 个入口（v1.8.5 加工页已删）；②全局步骤条
已移除；③首页流程条②改指向精读页；④旧 UI 契约（页面顺序/锚点按钮）
一条不破 —— 这次改造的原则是「重做引导层，保留兼容骨架」。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class TestUILayout(unittest.TestCase):

    def setUp(self):
        self.html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        self.js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        self.css = (ROOT / "ui" / "app.css").read_text(encoding="utf-8")

    # ---------- 旧契约不破 ---------- #
    def test_01_six_pages_intact(self):
        """v1.8.5：加工页已删（用户裁决），7 页骨架收敛为 6 页；其余不破。"""
        pages = ("home", "kb", "refine", "revise", "settings", "about")
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
        """v1.6.2：四类来源入口统一到首页；v1.8.5：文档加工三按钮再迁首页产物中心上方。
        加工页已删，页面骨架收敛为 6 页，只调整按钮归属（详见交付报告）。"""
        home = self.html[self.html.index('id="page-home"'):self.html.index('id="page-kb"')]
        kb = self.html[self.html.index('id="page-kb"'):self.html.index('id="page-refine"')]
        self.assertIn("btnRun", home)
        self.assertIn("btnPreview", home)
        # 四类内容获取入口（含迁入的订阅）全在首页统一提取台
        for fid in ("btnAudioTranscribe", "btnVideoTranscribe", "btnLinkRun", "subUrl"):
            self.assertIn('id="%s"' % fid, home, "统一提取台缺 %s" % fid)
        # v1.8.5：文档加工三按钮迁入首页产物中心上方；加工页已整体删除
        for fid in ("btnSummarize", "btnExportDocx", "btnWordEnhance"):
            self.assertIn('id="%s"' % fid, home, "首页产物中心上方缺 %s" % fid)
        # 文档加工卡片必须排在产物中心之前（右栏纵向堆叠：加工 → 产物中心）
        self.assertLess(home.index('id="btnSummarize"'),
                        home.index('id="artifactCenter"'),
                        "文档加工卡片应位于产物中心上方")
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

    def test_07_process_page_removed_strip_points_refine(self):
        """v1.8.5：加工页与看板已删；首页流程条②改指向精读页。"""
        self.assertNotIn('id="page-process"', self.html, "加工页容器未删净")
        self.assertNotIn('id="flowGuide"', self.html, "看板未删净")
        self.assertNotIn('data-page="process"', self.html, "加工导航项未删净")
        self.assertNotIn('data-goto="process"', self.html, "流程条仍指向已删的加工页")
        strip = self.html[self.html.index('class="pipeline-strip"'):
                          self.html.index('source-tabs-card')]
        for target in ("home", "refine", "kb"):
            self.assertIn('data-goto="%s"' % target, strip, "流程条缺跳转 %s" % target)
        self.assertIn("document.querySelectorAll(\"[data-goto]\")", self.js)

    def test_08_no_new_api_or_id_breakage(self):
        # 改造只动 UI 层，不新增/删除后端端点
        for ep in ("/api/refine/start", "/api/revise/start", "/api/kb/ingest",
                   "/api/sub/list", "/api/sub/scheduler"):
            self.assertIn(ep, self.js, "端点丢失 %s" % ep)
        # 加工页已删：不得出现其容器与僵尸占位
        self.assertNotIn('id="page-process"', self.html)
        self.assertNotIn("btnTranscribe", self.html)

    def test_09_nav_icon_colors_expand_vs_collapse(self):
        # v1.7.7 用户裁决：展开/折叠两态、深浅两主题都保持功能专属色。
        # 折叠后图标是唯一线索；深色侧栏底上近黑配色曾导致图标不可见。
        pages = ("home", "refine", "revise", "kb", "settings", "about")
        for p in pages:
            self.assertIn(".nav-item[data-page=\"%s\"] svg" % p, self.css,
                          "缺 %s 专属图标色" % p)
            # 专属色规则不得再用 :not(.nav-collapsed) 限定展开态
            self.assertNotIn(".app:not(.nav-collapsed) .nav-item[data-page=\"%s\"] svg" % p,
                             self.css, "%s 图标色被限定在展开态，折叠后会回退" % p)
            # 深色主题必须有自己的提亮版，否则深色底上看不清
            self.assertIn("html[data-theme=\"dark\"] .nav-item[data-page=\"%s\"] svg" % p,
                          self.css, "深色主题缺 %s 专属图标色" % p)
        # 折叠态不得再统一压成近黑
        self.assertNotIn(".app.nav-collapsed .nav-item svg", self.css,
                         "折叠态不得单独改图标色")
        self.assertNotIn(".app.nav-collapsed .nav-item { color: #1F1F1D; }", self.css,
                         "折叠态不得把文字色写死为近黑")
        # 折叠态布局规则保留（居中 + 隐藏文字）
        self.assertIn(".app.nav-collapsed .nav-label { display: none; }", self.css)

    def test_10_doc_features_above_artifact_center(self):
        """v1.8.5：文档加工迁入首页右栏产物中心上方；概览空栏高度减免。"""
        home = self.html[self.html.index('id="page-home"'):
                         self.html.index('id="page-kb"')]
        # 三个功能按钮留在首页，且与产物中心同处一个右栏列容器
        for fid in ("btnSummarize", "btnExportDocx", "btnWordEnhance"):
            self.assertIn('id="%s"' % fid, home, "首页缺文档加工 %s" % fid)
        self.assertIn('class="artifact-column"', home, "缺右栏列容器")
        docs_pos = home.index('id="btnSummarize"')
        art_pos = home.index('id="artifactCenter"')
        self.assertLess(docs_pos, art_pos, "文档加工应在产物中心上方")
        self.assertLess(art_pos, home.index('id="btnSummarize"') + 2000,
                        "文档加工与产物中心应在同一列容器（位置相邻）")
        # CSS：列容器占 artifacts 格，内容纵向堆叠
        self.assertIn('> .artifact-column { grid-area: artifacts; }', self.css)
        self.assertIn('.artifact-column { display: flex; flex-direction: column;', self.css)
        # 概览结果卡不再固定 200px / 340px 空栏高
        result_block = self.css[self.css.index(".result {"):self.css.index(".result {") + 160]
        self.assertIn("min-height: 0", result_block, "概览空栏 min-height 未减免")
        self.assertNotIn("height: 340px", self.css, "矮屏仍固定 340px 空栏高")

    def test_11_process_page_deleted_six_page_contract(self):
        """v1.8.5 用户裁决：左侧「加工」导航与加工页整体删除，骨架收敛为 6 页。"""
        pages = re.findall(r'id="page-([a-z]+)"', self.html)
        self.assertEqual(pages, ["home", "kb", "refine", "revise", "settings", "about"],
                         "页面物理顺序/页数不对（加工页应已删除）")
        navs = re.findall(r'data-page="([a-z]+)"', self.html)
        self.assertEqual(sorted(navs), sorted(pages), "导航项与页面容器不一致")
        # 加工页相关 JS/CSS/i18n 引用一并清干净
        for sym in ('process: $("page-process")', 'process: { title:',
                    'page.process.title', 'nav.process', 'activatePage("process")'):
            self.assertNotIn(sym, self.js, "JS 残留加工页引用 %s" % sym)
        self.assertNotIn('.nav-item[data-page="process"] svg', self.css,
                         "CSS 残留 process 图标色")

    def test_12_header_lang_toggle_contract(self):
        """v1.8.6：页头右上角版本号徽章改为中英切换按钮（中/EN，单击切换）。"""
        # DOM：保留 id（兼容历史契约），改为 button 且带 i18n 提示
        self.assertIn('class="header-tag" id="headerTag" type="button"', self.html)
        self.assertIn('data-i18n-title="切换界面语言"', self.html)
        self.assertIn('data-i18n-aria="切换界面语言"', self.html)
        self.assertNotIn('>v1.8.5<', self.html, "页头仍硬编码版本号")
        # JS：applyLang 统一渲染 中/EN，单击切换并落盘
        self.assertIn('el.headerTag.textContent = (currentLang === "en") ? "EN" : "中"', self.js)
        self.assertIn('el.headerTag.addEventListener("click"', self.js)
        self.assertIn('persistUiPref("lang", next)', self.js)
        self.assertNotIn('el.headerTag.textContent = "v" + ver', self.js,
                         "loadAbout 仍在写版本号到页头")
        self.assertNotIn('el.headerTag.textContent = "v" + st.version', self.js,
                         "启动分支仍在写版本号到页头")
        # CSS：按钮可点击 + 悬停反馈（明暗两套）
        self.assertIn("cursor: pointer", self.css)
        self.assertIn('html[data-theme="dark"] .header-tag:hover', self.css)
        # i18n：真源与生成物都有新词条
        en_map = (Path(__file__).parent / "tools" / "i18n_en_map.py").read_text(encoding="utf-8")
        self.assertIn('"切换界面语言": "Switch interface language"', en_map)
        i18n = (Path(__file__).parent / "ui" / "i18n.js").read_text(encoding="utf-8")
        self.assertIn('"切换界面语言": "Switch interface language"', i18n)

    def test_13_header_theme_toggle_contract(self):
        """v1.8.7：深浅主题按钮紧邻中英按钮，单击切换并复用主题落盘链路。"""
        # DOM：新按钮位于中英按钮右侧、同一容器内，带 i18n 提示
        self.assertIn('class="header-tags"', self.html)
        self.assertIn('class="header-tag" id="themeTag" type="button"', self.html)
        self.assertIn('data-i18n-title="切换界面主题"', self.html)
        self.assertIn('data-i18n-aria="切换界面主题"', self.html)
        self.assertLess(self.html.index('id="headerTag"'),
                        self.html.index('id="themeTag"'),
                        "深浅按钮应放在中英按钮右侧")
        # JS：两个按钮文字单一渲染点 + 单击切换主题并落盘
        self.assertIn('themeTag: $("themeTag")', self.js)
        self.assertIn('el.themeTag.textContent = (currentTheme === "dark")', self.js)
        self.assertIn('el.themeTag.addEventListener("click"', self.js)
        self.assertIn('var next = (currentTheme === "dark") ? "light" : "dark";', self.js)
        self.assertIn('applyTheme(next)', self.js)
        self.assertIn('uiPrefOverride.theme = next', self.js)
        self.assertIn('persistUiPref("theme", next)', self.js)
        apply_lang = self.js[self.js.index("function applyLang("):
                             self.js.index("function applyTheme(")]
        self.assertIn("el.themeTag.textContent", apply_lang)
        apply_theme = self.js[self.js.index("function applyTheme("):
                              self.js.index("// v1.7.1：用户显式选择过的界面偏好")]
        self.assertIn("el.themeTag.textContent", apply_theme)
        # CSS：并排布局 + 明暗两套按钮反馈
        self.assertIn(".header-tags {", self.css)
        self.assertIn("gap: 6px", self.css)
        self.assertIn('html[data-theme="dark"] .header-tag:hover', self.css)
        # i18n：真源与生成物都有新词条
        en_map = (Path(__file__).parent / "tools" / "i18n_en_map.py").read_text(encoding="utf-8")
        self.assertIn('"切换界面主题": "Switch interface theme"', en_map)
        i18n = (Path(__file__).parent / "ui" / "i18n.js").read_text(encoding="utf-8")
        self.assertIn('"切换界面主题": "Switch interface theme"', i18n)


if __name__ == "__main__":
    unittest.main()
