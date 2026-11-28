#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1.7.7 · 左侧功能栏导航图标主题适配 · 回归测试。

背景（用户裁决）：
  - 深色模式下，左侧功能栏折叠后图标看不见；
  - 深色模式下图标也应保持彩色，而不是被压成单色文本色。

守护：
  ①展开/折叠两态共用同一套「功能专属色」，折叠态不再有单独改色规则；
  ②深浅两主题各一套专属色，深色为同色相提亮版；
  ③两套配色在各自侧栏底色上对比度均 ≥ 3:1（WCAG 非文本图形门槛），
    且在 hover / active 底色上同样达标，避免点选后看不清；
  ④深色主题不得再用规则把图标统一压成 var(--c-text) / var(--c-accent)。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# v1.8.5：加工页已删，6 个导航入口
PAGES = ("home", "refine", "revise", "kb", "settings", "about")

# 侧栏底色（浅色主题 / 深色主题）与交互态底色，取自 ui/app.css
LIGHT_SIDEBAR = "#FFFFFF"
DARK_SIDEBAR = "#1E2226"
DARK_HOVER = "#2B3036"
DARK_ACTIVE = "#233348"


def _rel_lum(hex_color):
    """sRGB 相对亮度（WCAG 2.1 定义）。"""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    chans = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255.0
        chans.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = chans
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(fg, bg):
    """对比度（WCAG 2.1）。"""
    a, b = _rel_lum(fg), _rel_lum(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


class TestNavIconTheme(unittest.TestCase):

    def setUp(self):
        self.css = (ROOT / "ui" / "app.css").read_text(encoding="utf-8")

    # ---------- 取色 ---------- #
    def _light_colors(self):
        out = {}
        for p in PAGES:
            m = re.search(r"\.nav-item\[data-page=\"%s\"\] svg \{ stroke: (#[0-9A-Fa-f]{3,6}); \}" % p,
                          self.css)
            self.assertIsNotNone(m, "浅色主题缺 %s 专属图标色" % p)
            out[p] = m.group(1)
        return out

    def _dark_colors(self):
        out = {}
        for p in PAGES:
            m = re.search(r"html\[data-theme=\"dark\"\] \.nav-item\[data-page=\"%s\"\] svg \{ stroke: (#[0-9A-Fa-f]{3,6}); \}" % p,
                          self.css)
            self.assertIsNotNone(m, "深色主题缺 %s 专属图标色" % p)
            out[p] = m.group(1)
        return out

    # ---------- ① 折叠态不得另起颜色 ---------- #
    def test_01_collapsed_state_shares_page_colors(self):
        self.assertNotIn(".app.nav-collapsed .nav-item svg", self.css,
                         "折叠态不得单独改图标色，应与展开态共用功能专属色")
        self.assertNotIn(".app.nav-collapsed .nav-item { color: #1F1F1D; }", self.css,
                         "折叠态不得把文字色写死为近黑（深色底上不可见）")
        # 折叠态的布局规则必须保留
        self.assertIn(".app.nav-collapsed .nav-label { display: none; }", self.css)
        self.assertIn(".app.nav-collapsed .nav-item { justify-content: center; padding: 0; }", self.css)

    # ---------- ② 深色不得压成单色 ---------- #
    def test_02_dark_theme_keeps_page_colors(self):
        for p in PAGES:
            self.assertNotIn(".app:not(.nav-collapsed) .nav-item[data-page=\"%s\"] svg" % p,
                             self.css, "%s 图标色被限定在展开态" % p)
        self.assertNotIn('html[data-theme="dark"] .app:not(.nav-collapsed) .nav-item svg { stroke: var(--c-text); }',
                         self.css, "深色主题不得把图标压成单色文本色")
        self.assertNotIn('html[data-theme="dark"] .app:not(.nav-collapsed) .nav-item.active svg { stroke: var(--c-accent); }',
                         self.css, "深色主题不得把图标压成单色强调色")

    # ---------- ③ 对比度硬门槛 ---------- #
    def test_03_light_palette_contrast_ok(self):
        for p, c in self._light_colors().items():
            r = _contrast(c, LIGHT_SIDEBAR)
            self.assertGreaterEqual(r, 3.0,
                                    "浅色主题 %s 图标 %s 在白底对比度仅 %.2f" % (p, c, r))

    def test_04_dark_palette_contrast_ok(self):
        for p, c in self._dark_colors().items():
            r = _contrast(c, DARK_SIDEBAR)
            self.assertGreaterEqual(r, 3.0,
                                    "深色主题 %s 图标 %s 在深底对比度仅 %.2f" % (p, c, r))

    def test_05_dark_palette_contrast_ok_on_interaction_states(self):
        """hover / active 底色上同样要看得清。"""
        for p, c in self._dark_colors().items():
            for name, bg in (("hover", DARK_HOVER), ("active", DARK_ACTIVE)):
                r = _contrast(c, bg)
                self.assertGreaterEqual(r, 3.0,
                                        "深色主题 %s 图标 %s 在 %s 底 %s 上对比度仅 %.2f"
                                        % (p, c, name, bg, r))

    # ---------- ④ 两套配色必须是"提亮"关系 ---------- #
    def test_06_dark_palette_is_brighter_than_light(self):
        for p in PAGES:
            lc = _rel_lum(self._light_colors()[p])
            dc = _rel_lum(self._dark_colors()[p])
            self.assertGreater(dc, lc,
                               "%s 的深色版应比浅色版更亮（深底上才够醒目）" % p)

    def test_07_palette_entries_are_distinct(self):
        for name, getter in (("浅色", self._light_colors), ("深色", self._dark_colors)):
            colors = getter()
            self.assertEqual(len(set(colors.values())), len(PAGES),
                             "%s主题存在重复图标色，功能入口难以区分" % name)


if __name__ == "__main__":
    unittest.main()
