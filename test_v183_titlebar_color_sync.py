#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1.8.3 · 标题栏左右色差修复守护测试。

背景（用户 2026-11-27 截图实测）：
Windows 下标题栏被拆成两块绘制——左侧标题文字/菜单是网页 DOM，背景取
ui/app.css 的 --c-surface；右侧最小化/最大化/关闭按钮由 OS 用
electron/main.js 的 titleBarOverlay.color 画。v1.7.6 引入时两者取了不同
色值（网页 #FFFFFF vs overlay #f5f6f8），出现硬色差分界线。

本模块从 CSS 反向解析 --c-surface 的浅色/深色真值，强制 overlay color 与
之严格相等：任一侧改色都会让测试失败，杜绝两套色源再次漂移。同时校验
symbolColor 在对应底色上的对比度 >= 3:1，保证窗口按钮始终可见。
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for _sub in ("core", "media", "knowledge", "link", "subs"):
    _p = str(ROOT / _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _norm_color(value: str) -> str:
    """统一成小写 #rrggbb，忽略大小写与空白。"""
    v = value.strip().lower()
    if re.fullmatch(r"#[0-9a-f]{6}", v):
        return v
    if re.fullmatch(r"#[0-9a-f]{3}", v):
        return "#" + "".join(c * 2 for c in v[1:])
    return v


def _css_surface(css: str, dark: bool) -> str:
    """从 app.css 的 :root / html[data-theme="dark"] 块里取 --c-surface。"""
    if dark:
        m = re.search(r'html\[data-theme="dark"\]\s*\{([^}]*)\}', css)
    else:
        m = re.search(r':root\s*\{([^}]*)\}', css)
    assert m, "未找到 %s 的 CSS 变量块" % ("dark" if dark else "light")
    v = re.search(r'--c-surface\s*:\s*([^;]+);', m.group(1))
    assert v, "未找到 --c-surface 定义"
    return _norm_color(v.group(1))


def _overlay_colors(main_js: str) -> tuple[str, str, str, str]:
    """取 TITLEBAR_THEME 的 light/dark color 与 symbolColor。"""
    block = re.search(r'const TITLEBAR_THEME\s*=\s*Object\.freeze\(\{(.*?)\}\);',
                      main_js, re.S)
    assert block, "未找到 TITLEBAR_THEME"
    body = block.group(1)
    light = re.search(r"light:\s*\{\s*color:\s*'([^']+)'\s*,\s*symbolColor:\s*'([^']+)'", body)
    dark = re.search(r"dark:\s*\{\s*color:\s*'([^']+)'\s*,\s*symbolColor:\s*'([^']+)'", body)
    assert light and dark, "TITLEBAR_THEME 结构不完整"
    return (_norm_color(light.group(1)), _norm_color(light.group(2)),
            _norm_color(dark.group(1)), _norm_color(dark.group(2)))


def _luminance(color: str) -> float:
    """WCAG 相对亮度。"""
    rgb = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


class TestTitlebarColorSync(unittest.TestCase):
    def setUp(self):
        self.main = (ROOT / "electron" / "main.js").read_text(encoding="utf-8")
        self.css = (ROOT / "ui" / "app.css").read_text(encoding="utf-8")

    def test_01_light_overlay_equals_css_surface(self):
        """浅色：右侧窗口按钮区必须与左侧标题栏同为 #FFFFFF。"""
        light_color, _, _, _ = _overlay_colors(self.main)
        self.assertEqual(light_color, _css_surface(self.css, dark=False),
                         "浅色 overlay 与 --c-surface 不同源，会复现左白右灰色差")

    def test_02_dark_overlay_equals_css_surface(self):
        """深色：同理，overlay 必须跟随深色 --c-surface。"""
        _, _, dark_color, _ = _overlay_colors(self.main)
        self.assertEqual(dark_color, _css_surface(self.css, dark=True),
                         "深色 overlay 与 --c-surface 不同源")

    def test_03_no_stale_overlay_colors(self):
        """禁止回退到 v1.7.6 的两套旧色值。"""
        self.assertNotIn("color: '#f5f6f8'", self.main)
        self.assertNotIn("color: '#1E2226'", self.main)

    def test_04_window_background_matches_light_surface(self):
        """BrowserWindow 初始底色也要一致，避免启动瞬间闪一条不同色带。"""
        m = re.search(r"backgroundColor:\s*'([^']+)'", self.main)
        self.assertTrue(m, "未找到 backgroundColor")
        self.assertEqual(_norm_color(m.group(1)), _css_surface(self.css, dark=False))

    def test_05_symbol_color_contrast(self):
        """窗口按钮图标在对应底色上对比度 >= 3:1。"""
        light_bg, light_sym, dark_bg, dark_sym = _overlay_colors(self.main)
        self.assertGreaterEqual(_contrast(light_sym, light_bg), 3.0,
                                "浅色 symbolColor 对比度不足")
        self.assertGreaterEqual(_contrast(dark_sym, dark_bg), 3.0,
                                "深色 symbolColor 对比度不足")

    def test_06_dom_titlebar_uses_surface_token(self):
        """网页侧标题栏必须继续用 var(--c-surface)，不能写死别的颜色。"""
        m = re.search(r'\.shell-titlebar\s*\{([^}]*)\}', self.css)
        self.assertTrue(m, "未找到 .shell-titlebar 样式块")
        self.assertIn("background: var(--c-surface)", m.group(1))


if __name__ == "__main__":
    unittest.main()
