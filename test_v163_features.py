#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1.6.3 · 三项改进的契约测试。

1. 清单 app_version 用 "auto" 占位，加载时自动跟随 extract.__version__；
2. 组件静默补齐**默认关闭**——客户安装后行为完全不变，红线守住；
3. 知识库思源式三栏：块浏览只读端点、完整 body、被锁定的 id/函数名保留。
"""

# JINGHE_LAYOUT_BOOTSTRAP
import sys as _jinghe_sys
from pathlib import Path as _jinghe_Path
_jinghe_root = _jinghe_Path(__file__).resolve().parent
for _jinghe_sub in ("core", "media", "knowledge", "link", "subs"):
    _jinghe_p = str(_jinghe_root / _jinghe_sub)
    if _jinghe_p not in _jinghe_sys.path:
        _jinghe_sys.path.insert(0, _jinghe_p)
# END JINGHE_LAYOUT_BOOTSTRAP
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


class TestManifestAutoVersion(unittest.TestCase):
    def setUp(self):
        import components
        self.c = components

    def test_01_manifest_uses_auto_placeholder(self):
        text = (ROOT / "docs" / "组件与环境清单.md").read_text(encoding="utf-8")
        m = re.search(r'"app_version"\s*:\s*"([^"]+)"', text)
        self.assertIsNotNone(m, "清单缺 app_version 字段")
        self.assertEqual(m.group(1), "auto", "app_version 必须是 auto 占位符")

    def test_02_loaded_version_follows_code(self):
        import extract
        loaded = self.c.load_manifest(refresh=True)
        self.assertTrue(loaded["ok"], loaded.get("reason"))
        self.assertEqual(loaded["manifest"]["app_version"], extract.__version__)

    def test_03_compare_echoes_current_version(self):
        import extract
        r = self.c.compare_with_manifest(refresh=True)
        self.assertTrue(r["ok"])
        self.assertEqual(r["app_version"], extract.__version__)


class TestSilentInstallDefaultOff(unittest.TestCase):
    def setUp(self):
        import components
        self.c = components

    def test_04_default_off_does_nothing(self):
        with mock.patch.object(self.c, "list_components") as lc, \
             mock.patch.object(self.c, "install") as ins:
            r = self.c.auto_install_missing()
        self.assertFalse(r["ok"])
        self.assertFalse(r["enabled"])
        self.assertEqual(lc.call_count, 0, "默认关闭时不应发起探测")
        self.assertEqual(ins.call_count, 0, "默认关闭时不应安装")

    def test_05_explicit_enable_installs_only_missing(self):
        with mock.patch.object(self.c, "list_components", return_value={"components": [
                {"id": "ffmpeg", "installed": False},
                {"id": "yt-dlp", "installed": True},
        ]}), mock.patch.object(self.c, "install", return_value={"ok": True}) as ins:
            r = self.c.auto_install_missing(enabled=True)
        self.assertTrue(r["ok"])
        self.assertEqual(r["missing"], ["ffmpeg"])
        self.assertEqual(r["started"], ["ffmpeg"])
        self.assertEqual(ins.call_count, 1)
        self.assertEqual(ins.call_args[0][0], "ffmpeg")

    def test_06_setting_default_is_false(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        m = re.search(r'"auto_install_components"\s*:\s*(True|False)', src)
        self.assertIsNotNone(m, "设置缺 auto_install_components 默认值")
        self.assertEqual(m.group(1), "False", "静默安装必须默认关闭")

    def test_07_no_auto_install_at_startup_without_switch(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('if bool(_load_settings().get("auto_install_components"))', src)
        self.assertIn("auto_install_missing", src)

    def test_08_ui_switch_present(self):
        h = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="setAutoInstallComponents"', h)
        self.assertIn("默认关闭", h)


class TestKbBlockView(unittest.TestCase):
    def setUp(self):
        import kb
        self.kb = kb

    def test_09_browse_is_readonly_and_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            r = self.kb.browse(d)
            self.assertTrue(r["ok"])
            self.assertEqual(r["count"], 0)
            self.assertEqual(r["results"], [])
            self.assertEqual(r["docs"], [])

    def test_10_browse_endpoint_wired(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('path == "/api/kb/browse"', src)
        self.assertIn("kb.browse(KB_DIR", src)

    def test_11_three_column_html(self):
        h = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        for fid in ("kbResults", "kbDocTree", "kbBlocks", "kbSource", "btnKbBrowse"):
            self.assertIn('id="%s"' % fid, h, "三栏缺 %s" % fid)
        self.assertIn("kb-three-col", h)
        for fid in ("btnKbIngest", "btnKbRefresh", "kbQuery", "btnKbQuery"):
            self.assertIn('id="%s"' % fid, h)

    def test_12_js_contracts_preserved(self):
        js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        for fn in ("loadKbStatus", "doKbIngest", "doKbQuery", "bindKbEvents",
                   "loadKbBrowse", "renderKbThreeCol"):
            self.assertIn("function %s" % fn, js, "缺函数 %s" % fn)
        self.assertIn("/api/kb/open-source", js)
        self.assertIn("open: true", js)
        self.assertIn("回跳原文", js)
        self.assertIn("dataset.results", js)


if __name__ == "__main__":
    unittest.main(verbosity=2)
