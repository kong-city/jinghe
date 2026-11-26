#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1.7.4 · 主题入口唯一化 + 深色卡片补齐 · 守护测试。

背景：
- v1.7.2 曾在「关于」页加过一个主题快捷开关；v1.7.4 用户裁决：设置页已有
  浅色/深色按钮，关于页那颗重复且文案易混淆，**移除**，主题入口全局唯一。
- 同轮发现深色模式下 .about-item / .metric 等内层卡片硬编码浅色底未随主题，
  切深色仍呈白块——本轮集中补齐，本文件守护其不回退。

注意：文件名保留 v171（CI 显式模块清单已锁定），内容随 v1.7.4 契约更新。
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

    def test_01_about_has_no_theme_entry(self):
        """关于页不得再有主题切换控件——设置页是唯一入口。"""
        for token in ("aboutThemeCard", "aboutThemeToggle", "aboutThemeState", "about-theme-row"):
            self.assertNotIn(token, self.about, "关于页残留主题控件：%s" % token)
        self.assertNotIn("界面主题", self.about, "关于页不应出现「界面主题」卡片")

    def test_02_settings_theme_entry_is_unique_and_intact(self):
        """设置页浅色/深色单选仍在，且全局唯一。"""
        self.assertEqual(self.html.count('id="setThemeDark"'), 1)
        self.assertEqual(self.html.count('id="setThemeLight"'), 1)
        self.assertEqual(self.html.count('name="setTheme"'), 2)
        self.assertIn('id="themeRow"', self.html)

    def test_03_no_stale_js_wiring(self):
        """JS 里不得残留关于页按钮的引用、同步与事件绑定。"""
        for token in ("aboutThemeToggle", "aboutThemeState", "about-theme-row"):
            self.assertNotIn(token, self.js, "JS 残留失效引用：%s" % token)

    def test_04_apply_theme_still_drives_settings_only(self):
        """applyTheme 仍同步设置页单选，且不再触碰关于页控件。"""
        fn = self.js[self.js.index("function applyTheme"):self.js.index("// v1.7.1")]
        self.assertIn("el.setThemeLight.checked", fn)
        self.assertIn("el.setThemeDark.checked", fn)
        self.assertNotIn("aboutTheme", fn)

    def test_05_i18n_stale_keys_removed(self):
        """三条失效英译从构建产物中消失。"""
        for key in ("切换到深色", "切换到浅色",
                    "切换后立即生效并保存到本机设置；与「设置 · 界面主题」同步。"):
            self.assertNotIn('"%s"' % key, self.i18n, "i18n 残留失效词条：%s" % key)

    def test_06_no_stale_css(self):
        self.assertNotIn(".about-theme-row", self.css)

    def test_07_about_existing_structure_intact(self):
        """删主题卡片不破坏关于页既有结构断言。"""
        self.assertEqual(self.about.count('class="about-log-row"'), 3)
        self.assertIn('id="btnCheckUpdate"', self.about)
        self.assertIn('id="aboutVersion"', self.about)
        self.assertIn('class="about-grid"', self.about)


class TestDarkThemeCards(unittest.TestCase):
    """v1.7.4：深色下内层卡片不得再呈白块。"""

    def setUp(self) -> None:
        self.css = (ROOT / "ui" / "app.css").read_text(encoding="utf-8")

    def test_08_about_item_dark_covered(self):
        self.assertIn('html[data-theme="dark"] .about-item', self.css)

    def test_09_update_status_dark_covered(self):
        self.assertIn('html[data-theme="dark"] .update-status', self.css)

    def test_10_common_inner_cards_dark_covered(self):
        """指标格 / 功能按钮 / 工具状态 / 组件提示 / 进度轨道全部补齐。"""
        for cls in (".metric", ".feature-btn", ".tool-status", ".component-hint",
                    ".manifest-status", ".kb-rel-item", ".component-progress-track",
                    ".update-progress-track", ".toast.is-err"):
            self.assertIn('html[data-theme="dark"] ' + cls, self.css,
                          "深色覆盖缺失：%s" % cls)

    def test_11_dark_uses_theme_variables(self):
        """补齐的卡片用主题变量而非新的硬编码浅色。"""
        block = self.css[self.css.index("v1.7.4：深色主题补齐浅色硬编码卡片"):]
        self.assertIn("var(--c-input-bg)", block)
        self.assertIn("var(--c-border)", block)


if __name__ == "__main__":
    unittest.main(verbosity=2)
