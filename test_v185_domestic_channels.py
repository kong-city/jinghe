#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1.8.5 · 国内稳定下载渠道 + 组件版本适配守护。

用户 2026-11-28 裁决：
1. 下载一律走方便稳定的渠道（国内可达、摘要固定）；
2. 组件版本必须与软件适配，版本过高时迭代软件而不是放任不可用；
3. 旧版产物不阻塞迭代；
4. 项目文件（代码 / 清单 / 版本）实时同步，便于后续迭代。

本模块只做静态与无网络的边界校验，不依赖跑测试那台机器装了哪些组件。
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
sys.path.insert(0, str(ROOT / "knowledge"))


class TestDomesticChannels(unittest.TestCase):
    def setUp(self):
        import components as c
        self.c = c

    # ---------- 稳定渠道 ---------- #
    def test_01_vc_wheel_uses_aliyun_with_pinned_sha(self):
        self.assertIn("mirrors.aliyun.com", self.c.VC_MSVC_WHEEL_URL)
        self.assertIn("msvc_runtime", self.c.VC_MSVC_WHEEL_URL)
        self.assertRegex(self.c.VC_MSVC_WHEEL_SHA256, r"^[0-9a-f]{64}$")
        # 官方源仍保留为备选（既有 test_v180 守护前端按钮，不改）
        self.assertTrue(self.c.VC_REDIST_URL.startswith("https://aka.ms/"))

    def test_02_model_mirror_matches_whisper_upstream_pin(self):
        self.assertIn("hf-mirror.com", self.c.WHISPER_MODEL_MIRROR)
        # 5 个权重的 sha256 与 whisper 上游 _MODELS URL 里的 pin 逐一相同
        # （从模型库 LFS oid 实测比对，字节级一致）
        self.assertEqual(self.c.WHISPER_MODEL_SHA256, {
            "tiny": "65147644a518d12f04e32d6f3b26facc3f8dd46e5390956a9424a650c0ce22b9",
            "base": "ed3a0b6b1c0edf879ad9b11b1af5a0e6ab5db9205f891f668f8b0e6c6326e34e",
            "small": "9ecf779972d90ba49c06d968637d720dd632c55bbf19d441fb42bf17a411e794",
            "medium": "345ae4da62f9b3d59415adc60127b97c714f32e89e936602e85993674d08dcb1",
            "large-v2": "81f7c96c852ee8fc832187b0132e569d6c3065a3252ed18e56effd0b6a73e524",
        })

    # ---------- 版本适配 ---------- #
    def test_03_ocr_pins_compatible_onnxruntime(self):
        ocr = next(x for x in self.c.COMPONENTS if x["id"] == "ocr")
        self.assertIn("onnxruntime==1.20.0", ocr["package"])
        self.assertIn("rapidocr-onnxruntime", ocr["package"])
        # 1.32.0 要求 Win10+，在 Server 2019 上 import 即崩溃 —— 不得回退
        self.assertNotIn("onnxruntime==1.32", ocr["package"])

    # ---------- 手动令牌红线 ---------- #
    def test_04_vc_mirror_requires_user_initiation(self):
        with mock.patch.object(self.c, "_download") as dl:
            r = self.c.install_vc_runtime()
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "no-opt-in")
        dl.assert_not_called()

    def test_05_vc_mirror_skips_download_when_complete(self):
        with mock.patch.object(self.c, "_vc_dlls_present",
                               return_value=self.c._VC_PROBE_DLLS), \
             mock.patch.object(self.c, "_download") as dl:
            r = self.c.install_vc_runtime(user_initiated=True)
        self.assertTrue(r["ok"])
        self.assertTrue(r["already_installed"])
        dl.assert_not_called()

    def test_06_system_component_still_refuses_install(self):
        # v1.8.0 红线不因新增镜像通道而放宽
        r = self.c.install("vc-runtime")
        self.assertFalse(r["ok"])

    # ---------- 前后端接通 ---------- #
    def test_07_app_exposes_vc_mirror_endpoint(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("/api/components/vc-mirror", src)
        self.assertIn("install_vc_runtime(user_initiated=True)", src)

    def test_08_frontend_keeps_official_and_adds_mirror(self):
        js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        self.assertIn('data-role", isSystem ? "download" : "toggle"', js)
        self.assertIn('btn.getAttribute("data-role") === "vc-mirror"', js)
        self.assertIn('"/api/components/vc-mirror"', js)

    # ---------- 项目文件实时同步 ---------- #
    def test_09_manifest_records_domestic_channels(self):
        text = (ROOT / "docs" / "组件与环境清单.md").read_text(encoding="utf-8")
        m = re.search(r"JINGHE_COMPONENT_MANIFEST_BEGIN\s*(\{.*?\})\s*"
                      r"JINGHE_COMPONENT_MANIFEST_END", text, re.S)
        self.assertIsNotNone(m, "机器可读清单块缺失")
        data = json.loads(m.group(1))
        self.assertEqual(data["generated_at"], "2026-11-28")
        self.assertTrue(data["install_policy"]["domestic_only"])
        vc = next(x for x in data["components"] if x["id"] == "vc-runtime")
        self.assertIn("mirrors.aliyun.com", vc["mirror_source"])
        self.assertEqual(vc["mirror_sha256"], self.c.VC_MSVC_WHEEL_SHA256)
        ocr = next(x for x in data["components"] if x["id"] == "ocr")
        self.assertIn("onnxruntime==1.20.0", ocr["package"])
        self.assertEqual(data["runtime_baseline"]["onnxruntime"], "1.20.0")

    def test_10_version_sync_across_release_points(self):
        version = re.search(r'^__version__\s*=\s*["\']([^"\']+)',
                            (ROOT / "extract.py").read_text(encoding="utf-8"), re.M).group(1)
        # v1.8.6 起改为动态读真源：本测试守护的是「派生点一致」，不应把
        # 版本值硬编码——否则每次合法升号都会误报，反而掩盖真正的不同步。
        self.assertRegex(version, r'^\d+\.\d+\.\d+$')
        self.assertIn("## [%s]" % version,
                      (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))
        pkg = json.loads((ROOT / "electron" / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(pkg["version"], version)


if __name__ == "__main__":
    unittest.main()
