#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1.7.2 · 关于页界面主题快捷开关 · 守护测试。

背景：主题切换控件此前只在「设置」页，用户在顶部导航栏「关于」里找不到，
误以为「设置深色没有修改」。本轮在关于页加入口，且必须：
- 与设置页共用单一真源（applyTheme / persistUiPref / settings.json），
  不得另建状态、不得重复 id（测试已全局锁定 id="setThemeDark" 唯一）；
- 中英双语齐全；
- 不破坏关于页既有结构断言（日志/设置/导出三行等）。
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class TestAboutTheme(unittest.TestCase):

    def setUp(self) -> None:
        self.html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        self.js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        self.css = (ROOT / "ui" / "app.css").read_text(encoding="utf-8")
        self.i18n = (ROOT / "ui" / "i18n.js").read_text(encoding="utf-8")
        self.about = self.html[self.html.index('id="page-about"'):]

    def test_01_about_has_theme_entry(self):
        self.assertIn('id="aboutThemeCard"', self.about)
        self.assertIn('id="aboutThemeToggle"', self.about)
        self.assertIn('id="aboutThemeState"', self.about)
        self.assertIn("界面主题", self.about)

    def test_02_no_duplicate_theme_ids(self):
        """设置页的 setThemeDark/Light 是全局锁定 id，关于页不得复用。"""
        self.assertEqual(self.html.count('id="setThemeDark"'), 1)
        self.assertEqual(self.html.count('id="setThemeLight"'), 1)
        self.assertEqual(self.html.count('id="aboutThemeToggle"'), 1)

    def test_03_shares_single_source_of_truth(self):
        """关于页按钮必须走 applyTheme + persistUiPref，不能自建状态。"""
        seg = self.js[self.js.index('aboutThemeToggle.addEventListener'):]
        seg = seg[:seg.index("});", seg.index("persistUiPref")) + 3]
        self.assertIn("applyTheme(next)", seg)
        self.assertIn('uiPrefOverride.theme = next', seg)
        self.assertIn('persistUiPref("theme", next)', seg)

    def test_04_apply_theme_syncs_about_widget(self):
        fn = self.js[self.js.index("function applyTheme"):self.js.index("// v1.7.1")]
        self.assertIn("el.aboutThemeState", fn)
        self.assertIn("el.aboutThemeToggle", fn)

    def test_05_i18n_complete(self):
        # 词条三个都必须在字典里：「切换到浅色」由 JS tr() 动态取，
        # 不经过 HTML 的 data-i18n 属性。
        for key in ("切换到深色", "切换到浅色",
                    "切换后立即生效并保存到本机设置；与「设置 · 界面主题」同步。"):
            self.assertIn('"%s"' % key, self.i18n, "i18n 缺词条：%s" % key)
        for key in ("切换到深色",
                    "切换后立即生效并保存到本机设置；与「设置 · 界面主题」同步。"):
            self.assertIn('data-i18n="%s"' % key, self.html,
                          "HTML 未挂 i18n：%s" % key)
        self.assertIn('tr(currentTheme === "dark" ? "切换到浅色" : "切换到深色")',
                      self.js, "动态文案未走 i18n")

    def test_06_css_present_and_dark_aware(self):
        self.assertIn(".about-theme-row", self.css)
        self.assertIn('html[data-theme="dark"] .about-theme-row b', self.css)

    def test_07_about_existing_structure_intact(self):
        """不破坏既有三行日志/设置/导出结构断言。"""
        self.assertEqual(self.about.count('class="about-log-row"'), 3)
        self.assertIn('id="btnCheckUpdate"', self.about)
        self.assertIn('id="aboutVersion"', self.about)


if __name__ == "__main__":
    unittest.main(verbosity=2)
