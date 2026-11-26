#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1.7.3 · 首次启动组件向导守护测试。

锁定本轮改动（减少用户操作 + 包体积不变 + 不破红线）：
1. batch_enable：只装用户勾选组件，逐个走 install() → 手动令牌，非法 id 过滤；
2. settings 加 component_setup_done 首次运行标记（默认 False，白名单归一化）；
3. setup-batch 端点接线，且绝不读静默开关、绝不自动触发；
4. 前端向导 DOM + 逻辑（轻量默认勾选、whisper 默认不勾、跳过即落标记）；
5. 契约澄清行：一次性勾选批量启用 ≠ 自动安装。

纯源码/文本断言 + mock，不触发真实下载（符合「不主动下载用于测试」裁决）。
"""
import re
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


class TestBatchEnable(unittest.TestCase):
    def setUp(self):
        import components
        self.c = components

    def test_01_batch_enable_exists(self):
        self.assertTrue(callable(getattr(self.c, "batch_enable", None)),
                        "components.batch_enable 缺失")

    def test_02_rejects_non_list(self):
        r = self.c.batch_enable("ffmpeg")
        self.assertFalse(r["ok"])
        self.assertEqual(r["requested"], [])

    def test_03_filters_illegal_and_dedups(self):
        """非法 id 不安装、重复 id 去重保序。"""
        with mock.patch.object(self.c, "install", return_value={"ok": True}) as ins:
            r = self.c.batch_enable(["yt-dlp", "bogus", "yt-dlp", "ffmpeg"])
        self.assertTrue(r["ok"])
        self.assertEqual(r["requested"], ["yt-dlp", "ffmpeg"])
        self.assertEqual(r["invalid"], ["bogus"])
        self.assertEqual(ins.call_count, 2)

    def test_04_each_goes_through_install_token(self):
        """批量启用不绕过令牌：每个 id 都逐一调 install()，未勾选的不碰。"""
        with mock.patch.object(self.c, "install", return_value={"ok": True}) as ins:
            self.c.batch_enable(["ffmpeg", "ocr"])
        called = [c.args[0] for c in ins.call_args_list]
        self.assertEqual(called, ["ffmpeg", "ocr"])

    def test_05_install_not_called_for_unselected(self):
        """whisper 未被勾选时绝不安装（体积大头不误装）。"""
        with mock.patch.object(self.c, "install", return_value={"ok": True}) as ins:
            self.c.batch_enable(["ffmpeg", "yt-dlp"])
        called = [c.args[0] for c in ins.call_args_list]
        self.assertNotIn("whisper", called)

    def test_06_partial_failure_isolated(self):
        """单组件失败不影响其余勾选。"""
        def fake_install(cid):
            return {"ok": False, "error": "网络失败"} if cid == "ocr" else {"ok": True}
        with mock.patch.object(self.c, "install", side_effect=fake_install):
            r = self.c.batch_enable(["ffmpeg", "ocr", "yt-dlp"])
        self.assertEqual(r["started"], ["ffmpeg", "yt-dlp"])
        self.assertEqual(len(r["skipped"]), 1)
        self.assertEqual(r["skipped"][0]["id"], "ocr")

    def test_07_no_install_when_all_illegal(self):
        with mock.patch.object(self.c, "install") as ins:
            r = self.c.batch_enable(["x", "y"])
        self.assertFalse(r["ok"])
        self.assertEqual(ins.call_count, 0)


class TestSettingsFlag(unittest.TestCase):
    def test_08_default_false(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        m = re.search(r'"component_setup_done"\s*:\s*(True|False)', src)
        self.assertIsNotNone(m, "设置缺 component_setup_done 默认值")
        self.assertEqual(m.group(1), "False", "首次运行标记必须默认 False")

    def test_09_in_validate_whitelist(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('"component_setup_done"', src.split("_SETTINGS_LOCK")[0],
                      "component_setup_done 需进 _validate_settings 布尔白名单")

    def test_10_validate_settings_accepts_bool(self):
        import app
        out = app._validate_settings({"component_setup_done": True})
        self.assertTrue(out["component_setup_done"])
        out2 = app._validate_settings({"component_setup_done": "garbage"})
        self.assertIsInstance(out2["component_setup_done"], bool)


class TestEndpointWiring(unittest.TestCase):
    def test_11_setup_batch_endpoint_wired(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('path == "/api/components/setup-batch"', src)
        self.assertIn("components.batch_enable(data.get(\"ids\"))", src)

    def test_12_no_auto_install_switch_in_batch(self):
        """批量端点绝不读静默开关，纯用户点击驱动。"""
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        block = src.split('path == "/api/components/setup-batch"', 1)[1].split("elif path", 1)[0]
        self.assertNotIn("auto_install_components", block,
                         "批量端点不得读静默开关")
        self.assertIn("batch_enable", block)


class TestFrontendWizard(unittest.TestCase):
    def test_13_dom_elements_present(self):
        h = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        for eid in ("setupOverlay", "setupList", "setupInstall", "setupSkip", "setupStatus"):
            self.assertIn('id="%s"' % eid, h, "缺向导元素 %s" % eid)

    def test_14_light_default_heavy_not(self):
        js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        self.assertIn('SETUP_LIGHT_IDS = ["ffmpeg", "ocr", "yt-dlp"]', js)
        self.assertIn('SETUP_HEAVY_IDS = ["whisper"]', js)
        self.assertIn("var checked = !heavy;", js, "轻量默认勾选、whisper 默认不勾")

    def test_15_first_run_trigger(self):
        js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        self.assertIn("settings.component_setup_done !== false", js,
                      "仅首次运行触发向导")
        self.assertIn("maybeShowSetupWizard()", js)

    def test_16_skip_marks_done(self):
        js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        self.assertIn('settings: { component_setup_done: true }', js)
        self.assertIn('setupSkip', js)

    def test_17_batch_call_uses_checkbox_ids(self):
        js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        self.assertIn('api("/api/components/setup-batch", { ids: ids }', js)

    def test_18_css_overlay_and_dark(self):
        css = (ROOT / "ui" / "app.css").read_text(encoding="utf-8")
        self.assertIn(".setup-overlay", css)
        self.assertIn("html[data-theme=\"dark\"] .setup-box", css)

    def test_19_i18n_entries(self):
        mp = (ROOT / "tools" / "i18n_en_map.py").read_text(encoding="utf-8")
        for zh in ("首次使用 · 组件初始化", "安装选中组件", "跳过"):
            self.assertIn('"%s"' % zh, mp, "缺英译条目 %s" % zh)


class TestContract(unittest.TestCase):
    def test_20_contract_clarifies_batch_install(self):
        text = (ROOT / "docs" / "CAPABILITY_CONTRACT.md").read_text(encoding="utf-8")
        self.assertIn("一次性批量启用", text)
        self.assertIn("不违反「不自动安装」", text)

    def test_21_frozen_core_unchanged(self):
        """冻结内核 extract.py 本轮只允许版本号行变化。"""
        import subprocess
        diff = subprocess.run(["git", "diff", "--unified=0", "extract.py"],
                              cwd=str(ROOT), capture_output=True, text=True)
        changed = [ln for ln in diff.stdout.splitlines()
                   if ln.startswith("+") and not ln.startswith("+++")]
        for ln in changed:
            self.assertIn("__version__", ln,
                          "extract.py 出现非版本号改动，违反冻结契约：%s" % ln)

    def test_22_i18n_map_source_of_truth(self):
        """i18n.js 自动段必须完整来自 EN 映射真源——杜绝手工注入被重建冲掉。

        本轮踩坑：v1.7.1 的 3 条关于页主题词条曾只手工写进 i18n.js 自动段，
        EN map 未同步；跑 i18n_build 重建时词条丢失，全量测试捕获。
        现在补进 EN map 真源，并锁死「段内每条都能在 EN map 找到」。
        """
        import json
        sys.path.insert(0, str(ROOT / "tools"))
        from i18n_en_map import EN
        js = (ROOT / "ui" / "i18n.js").read_text(encoding="utf-8")
        seg = js.split("I18N_AUTO_BEGIN", 1)[1].split("I18N_AUTO_END", 1)[0]
        # i18n_build 用 json.dumps 生成键，含 \\n 的词条在 JS 里是转义形式；
        # 比对前必须 json.loads 还原成真实字符串，否则会误报「不在真源」。
        raw_keys = re.findall(r'"((?:[^"\\]|\\.)*)"\s*:', seg)
        auto_keys = {json.loads('"%s"' % k) for k in raw_keys}
        missing = auto_keys - set(EN)
        self.assertEqual(missing, set(),
                         "i18n.js 自动段有词条不在 EN 映射真源：%s" % sorted(missing))
        # v1.7.4：关于页主题快捷开关已移除，三条失效英译必须从真源一并删除。
        for k in ("切换到深色", "切换到浅色",
                  "切换后立即生效并保存到本机设置；与「设置 · 界面主题」同步。"):
            self.assertNotIn(k, EN, "失效的关于页主题词条仍留在 EN 映射真源：%s" % k)


if __name__ == "__main__":
    unittest.main()
