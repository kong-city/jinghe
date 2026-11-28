#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1.6.2 · 统一提取台布局契约测试。

锁死五件事：
1. 首页四类来源 tab 齐全、面板齐全、id 无重复；
2. 音视频/链接/订阅入口与表单确实在首页，且不在原页面；
3. 加工页回归纯二次加工，知识库页不再有订阅表单；
4. 前端切换逻辑（switchExtractSource / switchVideoSub / bindExtractSourceTabs）存在，
   且 tab 选择器收窄（不误伤另一组 tab）；
5. 导航 6 入口（v1.8.5 加工页已删）+ 4 分组 + 页面物理顺序保留（S14 契约）。

这些断言是硬契约——改布局时必须同步更新，不允许靠删断言让测试变绿。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class TestUnifiedExtractHub(unittest.TestCase):

    def setUp(self):
        self.html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        self.js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        self.css = (ROOT / "ui" / "app.css").read_text(encoding="utf-8")

    def _page(self, name, next_name):
        return self.html[self.html.index('id="page-%s"' % name):
                         self.html.index('id="page-%s"' % next_name)]

    # ---------- 1. 来源 tab 与面板 ----------
    def test_01_four_source_tabs_present(self):
        home = self._page("home", "kb")
        for src in ("file", "audio", "video", "sub"):
            self.assertIn('data-extract-tab="%s"' % src, home,
                          "首页缺来源 tab：%s" % src)
            self.assertIn('data-extract-panel="%s"' % src, home,
                          "首页缺来源面板：%s" % src)
        # 默认激活面板必须是「文档 / PDF」
        self.assertRegex(home, r'class="extract-panel active" data-extract-panel="file"')

    def test_02_video_subswitch_present(self):
        home = self._page("home", "kb")
        for mode in ("local", "link"):
            self.assertIn('data-video-sub="%s"' % mode, home, "视频缺子切换 tab：%s" % mode)
            self.assertIn('data-video-subpanel="%s"' % mode, home, "视频缺子面板：%s" % mode)
        # 本地视频默认激活
        self.assertRegex(home, r'class="video-subpanel active" data-video-subpanel="local"')

    def test_03_no_duplicate_ids(self):
        ids = re.findall(r'\bid="([^"]+)"', self.html)
        dups = {x for x in ids if ids.count(x) > 1}
        self.assertEqual(dups, set(), "HTML 存在重复 id：%s" % dups)

    # ---------- 2. 入口归属 ----------
    def test_04_extract_entries_all_in_home(self):
        home = self._page("home", "kb")
        for fid in ("btnRun", "btnPreview", "btnAudioTranscribe", "btnVideoTranscribe",
                    "btnLinkRun", "btnLinkInspect", "subUrl", "btnSubAdd", "toolStatus",
                    "linkCap", "subSchedHint"):
            self.assertIn('id="%s"' % fid, home, "统一提取台缺 %s" % fid)

    def test_05_process_page_deleted(self):
        """v1.8.5：加工页整体删除，文档加工三按钮在首页产物中心上方。"""
        home = self._page("home", "kb")
        self.assertNotIn('id="page-process"', self.html, "加工页容器未删净")
        for fid in ("btnSummarize", "btnExportDocx", "btnWordEnhance"):
            self.assertIn('id="%s"' % fid, home, "首页产物中心上方缺 %s" % fid)

    def test_06_kb_no_sub_form(self):
        kb = self._page("kb", "refine")
        for fid in ("btnKbIngest", "btnKbRefresh", "kbQuery", "btnKbQuery"):
            self.assertIn('id="%s"' % fid, kb, "知识库页缺 %s" % fid)
        self.assertNotIn('id="subUrl"', kb, "订阅表单应从知识库页迁出")

    # ---------- 3. 前端切换逻辑 ----------
    def test_07_switch_functions_exist(self):
        for fn in ("switchExtractSource", "switchVideoSub", "bindExtractSourceTabs"):
            self.assertIn("function %s" % fn, self.js, "缺函数 %s" % fn)
        self.assertIn("bindExtractSourceTabs();", self.js, "初始化未调用来源 tab 绑定")

    def test_08_tab_selectors_scoped(self):
        """结果区 tab 与来源 tab 都带 .tab 类，选择器必须按 data 属性收窄，互不误伤。"""
        self.assertIn('querySelectorAll(".tab[data-tab]")', self.js)
        self.assertIn('querySelectorAll("[data-extract-tab]")', self.js)
        self.assertIn('querySelectorAll("[data-video-sub]")', self.js)

    def test_09_home_refreshes_tools_and_subs(self):
        self.assertIn('if (name === "home") loadTools();', self.js)
        self.assertIn('if (name === "home") loadSubList();', self.js)

    # ---------- 4. S14 骨架不破 ----------
    def test_10_nav_seven_entries_intact(self):
        for p in ("home", "kb", "refine", "revise", "settings", "about"):
            self.assertIn('data-page="%s"' % p, self.html, "导航缺 %s" % p)
            self.assertIn('id="page-%s"' % p, self.html, "缺页面容器 %s" % p)

    def test_11_nav_four_groups_intact(self):
        for g in ("source", "refine-flow", "knowledge", "system"):
            self.assertIn('data-group="%s"' % g, self.html, "缺导航分组 %s" % g)

    def test_12_page_physical_order_intact(self):
        pages = re.findall(r'id="page-([a-z]+)"', self.html)
        self.assertEqual(pages, ["home", "kb", "refine", "revise",
                                 "settings", "about"], "页面物理顺序被破坏")

    def test_13_css_styles_present(self):
        self.assertIn(".extract-tabs", self.css)
        self.assertIn(".video-subtabs", self.css)
        self.assertIn(".extract-panel[hidden]", self.css)


if __name__ == "__main__":
    unittest.main()
