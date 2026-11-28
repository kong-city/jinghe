#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1.7.6 · 标题栏跟随主题 + 组件状态异常隔离/重试 · 守护测试。

背景（用户 2026-11-26 截图实测）：
1. 原生菜单已随 themeSource 变深色，但窗口抬头仍是白条——Windows 标题栏
   由 OS 外框绘制，themeSource 管不到，必须走 titleBarOverlay；
2. 本机没装系统 Python 时，OCR 探测抛 RuntimeError 把 /api/components
   整条打成 500，设置页只剩「组件状态读取失败」，连正常的 ffmpeg 都看不到；
3. 状态读取与安装失败都没有重试入口。

本模块锁定：标题栏双链路（菜单 themeSource + 标题栏 overlay）、探测异常
逐项隔离、状态读取 3 次退避重试、失败后可点「重试」；不触发任何下载。
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent
for _sub in ("core", "media", "knowledge", "link", "subs"):
    _p = str(ROOT / _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestTitlebarTheme(unittest.TestCase):
    def setUp(self):
        self.main = (ROOT / "electron" / "main.js").read_text(encoding="utf-8")
        self.html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        self.css = (ROOT / "ui" / "app.css").read_text(encoding="utf-8")

    def test_01_native_titlebar_overlay_in_main(self):
        self.assertIn("titleBarStyle: 'hidden'", self.main)
        self.assertIn("titleBarOverlay:", self.main)
        self.assertIn("setTitleBarOverlay", self.main)
        self.assertIn("applyTitleBarTheme(source)", self.main)

    def test_02_overlay_colors_follow_theme_tokens(self):
        # v1.8.3：overlay 色值改为与网页 --c-surface 同源（见 v183 守护测试）。
        self.assertIn("dark: { color: '#22262B'", self.main)
        self.assertIn("light: { color: '#FFFFFF'", self.main)
        self.assertIn("symbolColor", self.main)

    def test_03_menu_survives_hidden_titlebar(self):
        """隐藏标题栏会连原生菜单条一起拿掉，必须用同一模板的页面入口补回。"""
        self.assertIn("setMenuBarVisibility(true)", self.main)
        self.assertIn("MENU_TOP_KEYS", self.main)
        self.assertIn("ipcMain.handle('menu:open'", self.main)
        self.assertIn("submenu.popup({ window: mainWindow })", self.main)
        self.assertIn('id="shellMenu"', self.html)
        for key in ("file", "edit", "view", "window", "help"):
            self.assertIn('data-menu-key="%s"' % key, self.html)

    def test_04_dom_title_text_and_drag_region(self):
        self.assertIn('id="shellTitlebar"', self.html)
        self.assertIn('id="shellTitleText"', self.html)
        self.assertIn(".shell-titlebar", self.css)
        self.assertIn("app-region: drag", self.css)
        self.assertIn("-webkit-app-region: drag", self.css)
        self.assertIn("env(titlebar-area-width", self.css)

    def test_04b_no_titlebar_bottom_border(self):
        """v1.8.9：取消标题栏底部灰线——原线只画到按钮区中途、右侧未对齐。"""
        start = self.css.index(".shell-titlebar {")
        end = self.css.index("}", start)
        block = self.css[start:end]
        self.assertNotIn("border-bottom", block, "标题栏底部灰线应取消")
        # 宽度仍避开 overlay 按钮区，标题文字不被窗口按钮覆盖
        self.assertIn("env(titlebar-area-width", self.css)

    def test_05_menu_bridge_is_whitelisted(self):
        preload = (ROOT / "electron" / "preload.js").read_text(encoding="utf-8")
        js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        for channel in ("menu:open", "menu:labels", "menu:labels-changed"):
            self.assertIn(channel, preload)
        self.assertIn("allowed.indexOf(key) >= 0", preload)
        self.assertIn("initShellMenu()", js)
        self.assertIn('app-region: no-drag', self.css)

    def test_05b_layout_reserves_titlebar_height(self):
        self.assertIn("--shell-titlebar-h:", self.css)
        self.assertIn("height: calc(100vh - var(--shell-titlebar-h))", self.css)
        self.assertNotIn("height: 100vh;\n  overflow: hidden;", self.css)


class TestComponentResilience(unittest.TestCase):
    def setUp(self):
        import components
        self.c = components
        self.js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        self.py = (ROOT / "knowledge" / "components.py").read_text(encoding="utf-8")

    def test_06_probe_exception_isolated_per_component(self):
        """单项探测抛异常时，其余组件仍正常返回，状态接口不再是 500。"""
        real_pylib, real_one = self.c._probe_pylib, self.c._probe_one
        # v1.8.0：system 项（VC++）走独立探测函数，同样纳入异常隔离验证。
        real_vc = getattr(self.c, "_probe_vc_runtime", None)
        def boom(_arg=None):
            raise RuntimeError("未在本机找到可用于 pip 的 Python 解释器")
        try:
            self.c._probe_pylib = boom
            self.c._probe_one = boom
            if real_vc is not None:
                self.c._probe_vc_runtime = boom
            r = self.c.list_components(refresh=False)
        finally:
            self.c._probe_pylib, self.c._probe_one = real_pylib, real_one
            if real_vc is not None:
                self.c._probe_vc_runtime = real_vc
        self.assertTrue(r.get("ok"))
        self.assertTrue(r.get("components"))
        for item in r["components"]:
            self.assertFalse(item["installed"])
            self.assertEqual(item["state"], "error")
            self.assertIn("Python", item["reason"])

    def test_07_partial_failure_keeps_healthy_items(self):
        """一个组件探测炸了，不能把别的组件也标记成异常。"""
        real_pylib = self.c._probe_pylib
        def boom(_arg):
            raise RuntimeError("boom")
        try:
            self.c._probe_pylib = boom
            r = self.c.list_components(refresh=False)
        finally:
            self.c._probe_pylib = real_pylib
        self.assertTrue(r.get("ok"))
        states = {i["id"]: i["state"] for i in r["components"]}
        self.assertEqual(states.get("ocr"), "error")
        self.assertNotEqual(states.get("ffmpeg"), "error")

    def test_08_source_guards_each_probe(self):
        self.assertIn("try:", self.py[self.py.index("def list_components"):
                                      self.py.index("def _emit")])
        self.assertIn('"state": "error"', self.py)

    def test_09_status_read_retries_three_times(self):
        self.assertIn("function apiWithRetry(", self.js)
        self.assertIn('apiWithRetry("/api/components?refresh=1", undefined, 15000, 3,', self.js)
        self.assertIn("350 * (total - left)", self.js)

    def test_10_failed_status_has_clickable_retry(self):
        self.assertIn('"btn btn-ghost component-retry"', self.js)
        self.assertIn('retry.addEventListener("click", loadComponents)', self.js)

    def test_11_failed_install_can_be_retried(self):
        self.assertIn('j.state === "failed"', self.js)
        self.assertIn('st.state === "failed"', self.js)
        self.assertIn('tr("重试")', self.js)

    def test_12_retry_never_auto_downloads(self):
        """重试只重读状态/重发用户点击，令牌闸门必须还在。"""
        self.assertIn("_USER_OPT_INS.add(component_id)", self.py)
        self.assertIn("_require_opt_in", self.py)
        self.assertNotIn("apiWithRetry(\"/api/components/install\"", self.js)

    def test_13_i18n_entries_source_of_truth(self):
        en = (ROOT / "tools" / "i18n_en_map.py").read_text(encoding="utf-8")
        built = (ROOT / "ui" / "i18n.js").read_text(encoding="utf-8")
        for key in ("重试", "探测异常", "组件状态读取失败，正在重试", "组件状态读取失败："):
            self.assertIn('"%s"' % key, en, "EN 映射真源缺词条：%s" % key)
            self.assertIn('"%s"' % key, built, "构建产物缺词条：%s" % key)


if __name__ == "__main__":
    unittest.main()
