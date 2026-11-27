# -*- coding: utf-8 -*-
"""v1.8.2 环境韧性与重试机制守护测试。

覆盖用户 2026-11-27 裁决的 P0：
  1. 安装前环境预检（VC++ / venv / 目录权限），阻断项一次说清；
  2. 坏 venv 自动换槽位重建，不删旧目录（安全软件拦截删除的绕行）；
  3. 下载 / pip 网络类失败自动重试，取消与摘要不符绝不重试；
  4. 环境诊断接口零网络；装完清探测缓存，不再要求重启。

全部用 mock 构造异常环境，不依赖测试机真实安装状态、不发真实网络请求。
"""
from __future__ import annotations

# JINGHE_LAYOUT_BOOTSTRAP
import sys as _jinghe_sys
from pathlib import Path as _jinghe_Path
_jinghe_root = _jinghe_Path(__file__).resolve().parent
for _jinghe_sub in ("core", "media", "knowledge", "link", "subs"):
    _jinghe_p = str(_jinghe_root / _jinghe_sub)
    if _jinghe_p not in _jinghe_sys.path:
        _jinghe_sys.path.insert(0, _jinghe_p)
# END JINGHE_LAYOUT_BOOTSTRAP

import hashlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "knowledge"))
import components as C  # noqa: E402


class _Resp:
    """轻量 urllib 响应替身。"""

    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.headers = {"Content-Length": str(len(payload))}

    def read(self, _n: int = -1) -> bytes:
        if not self.payload:
            return b""
        data, self.payload = self.payload, b""
        return data

    def __enter__(self) -> "_Resp":
        return self

    def __exit__(self, *_a) -> None:
        return None


class _Proc:
    """pip 子进程替身。"""

    def __init__(self, rc: int, lines: list[str]) -> None:
        self.stdout = iter(lines)
        self.rc = rc

    def wait(self) -> int:
        return self.rc

    def terminate(self) -> None:
        pass

    def kill(self) -> None:
        pass


class V182EnvironmentRetryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.old_tokens = set(C._USER_OPT_INS)
        self.old_legacy = dict(C._USER_OPT_IN)
        C._USER_OPT_INS.clear()
        C._USER_OPT_IN.update({"granted": False, "component_id": ""})
        C._VENV_HEALTH_CACHE.clear()

    def tearDown(self) -> None:
        C._USER_OPT_INS.clear()
        C._USER_OPT_INS.update(self.old_tokens)
        C._USER_OPT_IN.clear()
        C._USER_OPT_IN.update(self.old_legacy)
        C._VENV_HEALTH_CACHE.clear()

    # ---------- 预检 ---------- #
    def test_01_preflight_is_local_only(self):
        import inspect
        src = inspect.getsource(C.preflight)
        self.assertNotIn("urlopen", src, "预检不得联网")
        self.assertNotIn("requests", src, "预检不得联网")
        self.assertTrue(callable(C.preflight))

    def test_02_missing_vc_blocks_whisper_with_human_message(self):
        vc = {"available": False, "version": "", "path": "",
              "reason": "缺 DLL", "state": "missing"}
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(C, "COMPONENT_DIR", Path(td)), \
             mock.patch.object(C, "_probe_vc_runtime", return_value=vc):
            r = C.preflight("whisper")
        self.assertFalse(r["ok"])
        self.assertEqual(r["blockers"][0]["code"], "vc-runtime")
        self.assertIn("VC++", r["message"])
        self.assertIn("下载安装", r["message"])
        self.assertIn("aka.ms", r["blockers"][0]["url"])

    def test_03_vc_does_not_block_ffmpeg(self):
        vc = {"available": False, "reason": "缺 DLL"}
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(C, "COMPONENT_DIR", Path(td)), \
             mock.patch.object(C, "_probe_vc_runtime", return_value=vc), \
             mock.patch.object(C, "_venv_pip_health", return_value=(True, "")):
            r = C.preflight("ffmpeg")
        self.assertTrue(r["ok"], "VC++ 不影响 ffmpeg，不得连坐")
        self.assertEqual(r["blockers"], [])

    def test_04_broken_venv_is_warning_not_blocker(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(C, "COMPONENT_DIR", Path(td)), \
             mock.patch.object(C, "_find_python_for_pip", return_value="python"), \
             mock.patch.object(C, "_venv_pip_health",
                               return_value=(False, "No module named pip._internal")):
            r = C.preflight("ocr")
        self.assertTrue(r["ok"], "坏 venv 有自愈，不该直接拒绝安装")
        self.assertEqual(r["warnings"][0]["code"], "venv-broken")
        self.assertIn("旧环境保留", r["warnings"][0]["message"])

    def test_05_unwritable_dir_blocks_install(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(C, "COMPONENT_DIR", Path(td)), \
             mock.patch("builtins.open", side_effect=OSError("access denied")):
            r = C.preflight("ffmpeg")
        self.assertFalse(r["ok"])
        self.assertEqual(r["blockers"][0]["code"], "dir-unwritable")
        self.assertIn("权限", r["message"])

    # ---------- venv 健康与自愈 ---------- #
    def test_06_pip_health_detects_broken_pip(self):
        bad = subprocess.CompletedProcess([], 1,
                                          "ModuleNotFoundError: No module named pip._internal")
        with mock.patch.object(C, "VENV_DIR", Path("C:/venv")), \
             mock.patch.object(C, "VENV_PYTHON", Path("C:/venv/Scripts/python.exe")), \
             mock.patch.object(C.subprocess, "run", return_value=bad):
            ok, reason = C._venv_pip_health()
        self.assertFalse(ok)
        self.assertIn("pip._internal", reason)

    def test_07_venv_usable_requires_healthy_pip(self):
        with tempfile.TemporaryDirectory() as td:
            vdir = Path(td) / "venv"
            (vdir / "Scripts").mkdir(parents=True)
            (vdir / "Scripts" / "python.exe").write_bytes(b"")
            (vdir / "pyvenv.cfg").write_text("home=x", encoding="utf-8")
            good = subprocess.CompletedProcess([], 0, "")
            with mock.patch.object(C, "VENV_DIR", vdir), \
                 mock.patch.object(C, "VENV_PYTHON", vdir / "Scripts" / "python.exe"), \
                 mock.patch.object(C.subprocess, "run", return_value=good), \
                 mock.patch.object(C, "_venv_pip_health",
                                   return_value=(False, "pip 残缺")):
                self.assertFalse(C._venv_python_usable(),
                                 "pip 残缺的 venv 不得判为可用")

    def test_08_self_heal_switches_to_healthy_slot(self):
        with mock.patch.object(C, "_venv_python_usable", return_value=False), \
             mock.patch.object(C, "_probe_venv_slot", side_effect=[False, True]) as probe, \
             mock.patch.object(C, "_select_venv_slot") as select, \
             mock.patch.object(C, "_find_python_for_pip", return_value="python"), \
             mock.patch.object(C, "_create_venv") as create:
            C._ensure_venv("ocr")
        self.assertEqual(probe.call_count, 2)
        select.assert_called_once_with(2)
        create.assert_not_called(), "已有健康槽位时不得重建"

    def test_09_next_slot_skips_existing_broken_venv(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "venv").mkdir()
            with mock.patch.object(C, "COMPONENT_DIR", Path(td)):
                self.assertEqual(C._next_venv_slot(), 2)

    # ---------- 重试 ---------- #
    def test_10_download_retries_network_failure(self):
        C._USER_OPT_INS.add("ffmpeg")
        payload = b"ok-payload"
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "pkg.bin"
            with mock.patch.object(C.urllib.request, "urlopen",
                                   side_effect=[OSError("network down"),
                                                _Resp(payload)]) as op, \
                 mock.patch.object(C.time, "sleep"):
                C._download("https://example.com/x.bin", dest, "ffmpeg")
            self.assertEqual(dest.read_bytes(), payload)
            self.assertEqual(op.call_count, 2, "网络失败应重试一次")
        evs = C.install_status(0, "ffmpeg")["events"]
        self.assertTrue(any("重试" in e["text"] for e in evs),
                        "重试必须对用户可见")

    def test_11_sha256_mismatch_never_retries(self):
        C._USER_OPT_INS.add("ffmpeg")
        digest = hashlib.sha256(b"expected").hexdigest()
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "pkg.bin"
            with mock.patch.object(C.urllib.request, "urlopen",
                                   return_value=_Resp(b"tampered")) as op, \
                 mock.patch.object(C.time, "sleep"):
                with self.assertRaises(RuntimeError) as ctx:
                    C._download("https://example.com/x.bin", dest,
                                "ffmpeg", sha256=digest)
            self.assertIn("校验失败", str(ctx.exception))
            self.assertEqual(op.call_count, 1, "摘要不符绝不重试")
            self.assertFalse(dest.exists())
            self.assertFalse(dest.with_name(dest.name + ".part").exists())

    def test_12_cancel_never_retries(self):
        C._USER_OPT_INS.add("ffmpeg")
        job = C._job_for("ffmpeg")
        with mock.patch.dict(job, {"cancelled": True}):
            with tempfile.TemporaryDirectory() as td:
                dest = Path(td) / "pkg.bin"
                with mock.patch.object(C.urllib.request, "urlopen") as op, \
                     mock.patch.object(C.time, "sleep"):
                    with self.assertRaises(RuntimeError) as ctx:
                        C._download("https://example.com/x.bin", dest, "ffmpeg")
                self.assertIn("cancelled", str(ctx.exception))
                op.assert_not_called()

    def test_13_pip_install_retries_once(self):
        C._USER_OPT_INS.add("ocr")
        bad = subprocess.CompletedProcess([], 1, "")
        procs = [_Proc(1, ["ERROR: network timeout"]),
                 _Proc(0, ["Successfully installed pymupdf"])]
        with mock.patch.object(C.subprocess, "Popen", side_effect=procs) as popen, \
             mock.patch.object(C.time, "sleep"):
            self.assertEqual(C._pip_install("pymupdf", "ocr"), "安装完成")
        self.assertEqual(popen.call_count, 2, "pip 网络失败应重试一次")

    def test_14_pip_bad_token_still_rejected(self):
        with self.assertRaises(RuntimeError) as ctx:
            C._pip_install("yt-dlp", "yt-dlp")
        self.assertIn("手动启用授权", str(ctx.exception))

    # ---------- 诊断接口 / 集成 ---------- #
    def test_15_environment_report_is_readonly_and_complete(self):
        import inspect
        src = inspect.getsource(C.environment_report)
        self.assertNotIn("urlopen", src, "环境诊断不得联网")
        vc = {"available": False, "reason": "缺 DLL"}
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(C, "COMPONENT_DIR", Path(td)), \
             mock.patch.object(C, "_probe_vc_runtime", return_value=vc), \
             mock.patch.object(C, "_venv_pip_health", return_value=(False, "坏")), \
             mock.patch.object(C, "_python_for_pip", return_value="python"):
            r = C.environment_report()
        self.assertTrue(r["ok"])
        for key in ("python_version", "python_exe", "dir_writable", "venv",
                    "vc_runtime", "bin_dir_in_path", "retries"):
            self.assertIn(key, r, "诊断缺字段 %s" % key)
        self.assertFalse(r["vc_runtime"]["available"])
        self.assertEqual(r["retries"]["download"], C.DOWNLOAD_RETRIES)

    def test_16_install_blocked_by_preflight_without_token(self):
        blocker = {"code": "vc-runtime", "message": "请先装 VC++"}
        with mock.patch.object(C, "preflight",
                               return_value={"ok": False, "blockers": [blocker],
                                             "warnings": [], "message": blocker["message"]}), \
             mock.patch.object(C, "_probe_one",
                               return_value={"available": False}):
            r = C.install("whisper")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "vc-runtime")
        self.assertNotIn("whisper", C._USER_OPT_INS, "预检阻断不得发下载令牌")

    def test_17_cache_invalidation_removes_probe_cache(self):
        import media_tools
        old = media_tools._CACHE
        try:
            media_tools._CACHE = {"stale": True}
            C._invalidate_probe_cache()
            self.assertIsNone(media_tools._CACHE)
        finally:
            media_tools._CACHE = old

    def test_18_route_and_ui_wired(self):
        app_src = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('path == "/api/components/environment"', app_src)
        html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="btnComponentEnv"', html)
        js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        self.assertIn("loadEnvironmentReport", js)
        self.assertIn("/api/components/environment", js)


if __name__ == "__main__":
    unittest.main()
