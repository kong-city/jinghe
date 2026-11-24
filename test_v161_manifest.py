#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1.6.1 · 组件与环境清单契约测试。

锁死三件事：
1. 清单文件存在、机器可读块可解析、声明与 COMPONENTS 常量一致（防漂移）；
2. 比对逻辑只读（零下载/安装副作用）、状态分类如实（missing / unusable / different 分开）；
3. 软件侧接入点齐全（端点、前端展示、打包资源），且绝不自动下载。

这些断言是硬契约——将来改清单格式或比对逻辑时，必须同步更新测试，
不允许靠删断言让测试变绿。
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
import json
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

MANIFEST_PATH = ROOT / "docs" / "组件与环境清单.md"


class TestManifestFile(unittest.TestCase):
    """清单文件本身：存在、可解析、声明与代码真源一致。"""

    def setUp(self):
        import components
        self.c = components

    def test_manifest_file_exists(self):
        self.assertTrue(MANIFEST_PATH.is_file(),
                        "组件与环境清单.md 不存在")

    def test_machine_readable_block_parses(self):
        text = MANIFEST_PATH.read_text(encoding="utf-8")
        self.assertIn(self.c.MANIFEST_BEGIN, text)
        self.assertIn(self.c.MANIFEST_END, text)
        m = re.search(
            r"%s\s*\n(.*?)\n\s*%s" % (
                re.escape(self.c.MANIFEST_BEGIN), re.escape(self.c.MANIFEST_END)),
            text, re.S)
        self.assertIsNotNone(m, "机器可读块缺失")
        data = json.loads(m.group(1))
        self.assertEqual(data.get("schema"), "jinghe-components-manifest/v1")
        self.assertIsInstance(data.get("components"), list)
        self.assertFalse(data.get("install_policy", {}).get("auto_download"),
                         "清单不得声明自动下载")

    def test_manifest_ids_match_components_constant(self):
        """清单声明的组件 id 必须与 COMPONENTS 真源一致，防漂移。"""
        loaded = self.c.load_manifest(refresh=True)
        self.assertTrue(loaded["ok"], "清单加载失败：" + loaded["reason"])
        manifest_ids = {c["id"] for c in loaded["manifest"]["components"]}
        code_ids = {c["id"] for c in self.c.COMPONENTS}
        self.assertEqual(manifest_ids, code_ids,
                         "清单组件与 COMPONENTS 常量不一致：%s vs %s" %
                         (manifest_ids, code_ids))

    def test_manifest_kind_and_source_match_constant(self):
        """每个组件的 kind / package / probe 必须与真源一致。"""
        loaded = self.c.load_manifest(refresh=True)
        declared = {c["id"]: c for c in loaded["manifest"]["components"]}
        for comp in self.c.COMPONENTS:
            d = declared[comp["id"]]
            self.assertEqual(d.get("kind"), comp["kind"],
                             "%s kind 漂移" % comp["id"])
            self.assertEqual(d.get("package", ""), comp.get("package", ""),
                             "%s package 漂移" % comp["id"])
            self.assertEqual(d.get("probe", ""), comp.get("probe", ""),
                             "%s probe 漂移" % comp["id"])

    def test_load_manifest_missing_file_reports_honestly(self):
        """文件缺失时必须 ok=False + 给出 reason，绝不静默返回空清单。"""
        with mock.patch.object(self.c, "_manifest_candidates", return_value=[]):
            r = self.c.load_manifest(refresh=True)
        self.assertFalse(r["ok"])
        self.assertIsNone(r["manifest"])
        self.assertTrue(r["reason"])


class TestCompareReadOnly(unittest.TestCase):
    """比对逻辑：只读、状态分类如实、零安装副作用。"""

    def setUp(self):
        import components
        self.c = components

    def test_compare_returns_read_only_flags(self):
        r = self.c.compare_with_manifest(refresh=True)
        self.assertTrue(r["ok"], "比对失败：" + r.get("reason", ""))
        self.assertTrue(r.get("read_only"))
        self.assertFalse(r.get("auto_download"))

    def test_compare_has_no_install_side_effect(self):
        """比对过程中绝不调用 install / 下载 / pip 安装。

        注意：探测组件版本会起 Popen 子进程（读 stdout/stderr 的线程是
        Popen 内部实现），那属于只读探测，不是安装副作用，故不 mock Thread。
        """
        with mock.patch.object(self.c, "install") as inst, \
             mock.patch.object(self.c, "_download") as dl, \
             mock.patch.object(self.c, "_pip_install") as pip:
            self.c.compare_with_manifest(refresh=True)
        inst.assert_not_called()
        dl.assert_not_called()
        pip.assert_not_called()

    def test_status_vocabulary_is_closed(self):
        """比对结果的状态只能来自约定集合，防止冒出新词让前端无法处理。"""
        allowed = {"match", "different", "missing", "unusable",
                   "no-expectation", "unknown-local", "not-in-manifest"}
        r = self.c.compare_with_manifest(refresh=True)
        self.assertTrue(r["ok"])
        for it in r["items"]:
            self.assertIn(it["status"], allowed,
                          "未知状态 %s（组件 %s）" % (it["status"], it["id"]))

    def test_version_status_pure_comparison(self):
        f = self.c._version_status
        self.assertEqual(f("1.2.3", "1.2.3"), "match")
        self.assertEqual(f("1.2.4", "1.2.3"), "different")
        self.assertEqual(f("", "1.2.3"), "unknown-local")
        self.assertEqual(f("1.2.3", ""), "no-expectation")
        self.assertEqual(f("", ""), "no-expectation")

    def test_summary_counts_consistent_with_items(self):
        r = self.c.compare_with_manifest(refresh=True)
        self.assertTrue(r["ok"])
        items = r["items"]
        s = r["summary"]
        self.assertEqual(s["missing"], sum(1 for i in items if i["status"] == "missing"))
        self.assertEqual(s["different"], sum(1 for i in items if i["status"] == "different"))
        self.assertEqual(s["unusable"], sum(1 for i in items if i["status"] == "unusable"))
        self.assertEqual(s["total"], len(items))


class TestWiring(unittest.TestCase):
    """软件侧接入点：端点、前端展示、打包资源、CI/门禁覆盖。"""

    def test_endpoint_in_app(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('/api/components/manifest', src)
        self.assertIn('compare_with_manifest', src)

    def test_frontend_uses_endpoint_and_never_auto_installs(self):
        js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        self.assertIn('/api/components/manifest', js)
        self.assertIn('loadComponentManifest', js)
        self.assertIn('unusable', js)
        # 清单状态条文案必须声明只读，不误导用户以为会自动装
        self.assertIn('不会自动下载安装', js)

    def test_manifest_bundled_in_build_spec(self):
        spec = (ROOT / "build.spec").read_text(encoding="utf-8")
        self.assertIn('组件与环境清单.md', spec,
                      "清单未随包携带，冻结态读不到")

    def test_covered_by_ci(self):
        """新测试模块必须进 CI 的 unittest 命令，否则是假绿灯。"""
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("test_v161_manifest", ci,
                      "test_v161_manifest 未纳入 CI")


if __name__ == "__main__":
    unittest.main()
