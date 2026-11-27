#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1.8.0 · VC++ 运行库「系统依赖引导项」守护测试。

锁定本轮改动：
1. COMPONENTS 新增 kind=system 的 vc-runtime 项，探测 5 个关键 DLL；
2. list_components 把 system 项分流到 _probe_vc_runtime，并暴露 kind/url；
3. install() / batch_enable() 显式拒绝 system 项 —— 不下载、不弹 UAC、
   不进令牌链路（这是「绝不静默安装系统级依赖」红线的代码级保证）；
4. 前端：system 项按钮走 window.open 官方下载页、不触发 enableComponent；
   向导勾选列表排除 system 项；
5. i18n 中英词条同步（下载安装 / 已安装）。

纯 mock + 源码文本断言，不触发任何真实下载或系统目录写入。
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


class TestVcComponentDef(unittest.TestCase):
    def setUp(self):
        import components
        self.c = components

    def test_01_vc_component_registered_as_system(self):
        comp = next((x for x in self.c.COMPONENTS if x["id"] == "vc-runtime"), None)
        self.assertIsNotNone(comp, "vc-runtime 未注册到 COMPONENTS")
        self.assertEqual(comp["kind"], "system")
        self.assertEqual(comp["exe"], "")
        self.assertEqual(comp["probe"], "")
        self.assertTrue(comp["url"].startswith("https://aka.ms/"))

    def test_02_probe_dll_list_is_explicit(self):
        """探测口径固定为 5 个 whisper/torch 实际需要的 DLL。"""
        dlls = set(self.c._VC_PROBE_DLLS)
        self.assertEqual(len(dlls), 5)
        self.assertIn("vcruntime140.dll", dlls)
        self.assertIn("vcruntime140_threads.dll", dlls)
        self.assertIn("msvcp140_atomic_wait.dll", dlls)

    def test_03_probe_reports_missing_with_actionable_reason(self):
        """缺 DLL → installed=False + 明确「下载安装」指引，不是笼统报错。"""
        with mock.patch.object(self.c, "_vc_dlls_present",
                               return_value=("vcruntime140.dll",)):
            st = self.c._probe_vc_runtime()
        self.assertFalse(st["available"])
        self.assertEqual(st["state"], "missing")
        self.assertIn("VC++ 运行库文件", st["reason"])
        self.assertIn("下载安装", st["reason"])

    def test_04_probe_ok_when_all_dlls_present(self):
        with mock.patch.object(self.c, "_vc_dlls_present",
                               return_value=tuple(self.c._VC_PROBE_DLLS)):
            st = self.c._probe_vc_runtime()
        self.assertTrue(st["available"])
        self.assertEqual(st["state"], "ok")
        self.assertEqual(st["reason"], "")

    def test_05_install_refuses_system_component(self):
        """系统级依赖绝不进 install() —— 无令牌、无下载。"""
        with mock.patch.object(self.c, "_require_opt_in") as opt:
            r = self.c.install("vc-runtime")
        self.assertFalse(r["ok"])
        self.assertIn("系统级依赖", r["error"])
        opt.assert_not_called()

    def test_06_batch_enable_excludes_system_component(self):
        """向导批量接口也不得安装系统依赖。"""
        with mock.patch.object(self.c, "install", return_value={"ok": True}) as ins:
            r = self.c.batch_enable(["ffmpeg", "vc-runtime"])
        self.assertEqual(r["requested"], ["ffmpeg"])
        self.assertIn("vc-runtime", r["invalid"])
        ins.assert_called_once_with("ffmpeg")

    def test_07_list_components_exposes_kind_and_url(self):
        """前端需要 kind/url 才能分流渲染。"""
        with mock.patch.object(self.c, "_probe_vc_runtime",
                               return_value={"available": False, "version": "",
                                             "path": "", "reason": "缺 DLL",
                                             "state": "missing"}), \
             mock.patch.object(self.c, "_probe_one", return_value={"available": False,
                 "version": "", "path": "", "reason": "", "state": "missing"}), \
             mock.patch.object(self.c, "_probe_pylib", return_value={"available": False,
                 "version": "", "path": "", "reason": "", "state": "missing"}):
            items = self.c.list_components()["components"]
        vc = next(x for x in items if x["id"] == "vc-runtime")
        self.assertEqual(vc["kind"], "system")
        self.assertTrue(vc["url"].startswith("https://aka.ms/"))
        self.assertFalse(vc["installed"])


class TestVcFrontend(unittest.TestCase):
    """前端文本守护：system 项只做引导，绝不走安装链路。"""

    @classmethod
    def setUpClass(cls):
        cls.app = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        cls.en_map = (ROOT / "tools" / "i18n_en_map.py").read_text(encoding="utf-8")
        cls.i18n_js = (ROOT / "ui" / "i18n.js").read_text(encoding="utf-8")

    def test_01_system_button_role_exists(self):
        self.assertIn('data-role", isSystem ? "download" : "toggle"', self.app)

    def test_02_download_button_uses_window_open(self):
        self.assertIn('window.open(url, "_blank")', self.app)

    def test_03_download_branch_does_not_call_enable(self):
        """download 分支必须在 enableComponent 之前 return，杜绝误装。"""
        block = self.app.split('if (btn.getAttribute("data-role") === "download")', 1)[1]
        block = block.split("enableComponent(", 1)[0]
        self.assertIn("return;", block, "download 分支缺少 return，会误触发安装")

    def test_04_url_allowlist_guard(self):
        """只放行 https 官方链接，杜绝任意 URL 注入。"""
        self.assertIn('/^https?:\\/\\//.test(url)', self.app)

    def test_05_wizard_excludes_system(self):
        self.assertIn('if (!c || c.kind === "system") return;', self.app)

    def test_06_i18n_bilingual(self):
        self.assertIn('"下载安装": "Download installer"', self.en_map)
        self.assertIn('"已安装": "Installed"', self.en_map)
        self.assertIn('"下载安装": "Download installer"', self.i18n_js)
        self.assertIn('"已安装": "Installed"', self.i18n_js)


if __name__ == "__main__":
    unittest.main()
