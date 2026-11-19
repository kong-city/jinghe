#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S10 · 可选组件管理契约测试（修复「假绿灯」）。

用户 2026-11-19 裁决：
1. 软件绝不主动下载组件，只有用户手动点「启用」按钮才下载；
2. ffmpeg / whisper / yt-dlp 不进 exe、不进 Release、不随 GitHub 上传；
3. 新模块必须有测试 + 门禁 + CI 守护（此前 components.py 零测试 = 假绿灯）。

本测试锁死上述红线，任何绕过都会变红。
"""
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


class TestComponentNoAutoDownload(unittest.TestCase):
    """红线 1：绝不主动下载，令牌闸门不可绕过。"""

    def setUp(self):
        import components
        self.c = components
        # 隔离令牌与任务状态，避免污染
        self._optin = dict(self.c._USER_OPT_IN)
        self.c._USER_OPT_IN.update({"granted": False, "component_id": ""})

    def tearDown(self):
        self.c._USER_OPT_IN.update(self._optin)

    def test_download_without_token_rejected(self):
        # 无令牌直接调下载 → 必须在发任何网络请求前就被拒
        with mock.patch.object(self.c.urllib.request, "urlopen") as u:
            with self.assertRaises(RuntimeError) as ctx:
                self.c._download("https://example.com/x.zip",
                                 Path(tempfile.gettempdir()) / "x.zip", "ffmpeg")
        self.assertIn("手动", str(ctx.exception))
        u.assert_not_called(), "无令牌仍发起了网络请求"

    def test_pip_install_without_token_rejected(self):
        with mock.patch.object(self.c.subprocess, "Popen") as p:
            with self.assertRaises(RuntimeError):
                self.c._pip_install("yt-dlp", "yt-dlp")
        p.assert_not_called(), "无令牌仍启动了 pip"

    def test_token_is_one_shot_and_bound(self):
        # 令牌与组件 id 绑定，且一次性消费
        self.c._USER_OPT_IN.update({"granted": True, "component_id": "ffmpeg"})
        self.c._require_opt_in("ffmpeg")       # 消费成功
        self.assertFalse(self.c._USER_OPT_IN["granted"])
        with self.assertRaises(RuntimeError):
            self.c._require_opt_in("ffmpeg")   # 再消费即失败
        # 组件 id 不匹配也拒绝
        self.c._USER_OPT_IN.update({"granted": True, "component_id": "ffmpeg"})
        with self.assertRaises(RuntimeError):
            self.c._require_opt_in("yt-dlp")

    def test_list_components_does_not_download(self):
        # 探测清单只跑 --version / --help，绝不下载、绝不 pip install
        with mock.patch.object(self.c.urllib.request, "urlopen") as u, \
             mock.patch.object(self.c.subprocess, "Popen") as p:
            self.c.list_components()
        u.assert_not_called(), "探测时发起了网络下载"
        # Popen 只可能被 ToolAdapter 用来跑探测命令（--version / --help）
        for call in p.call_args_list:
            argv = call.kwargs.get("args") or (call.args[0] if call.args else [])
            argv_text = " ".join(str(a) for a in argv)
            self.assertNotIn("pip", argv_text.lower()), "探测时启动了 pip"
            self.assertNotIn("install", argv_text.lower()), "探测时执行了安装"


class TestComponentNoBundling(unittest.TestCase):
    """红线 2：三工具不进 exe / Release / GitHub。"""

    def test_build_spec_has_no_binaries(self):
        spec = (ROOT / "build.spec").read_text(encoding="utf-8")
        self.assertIn("binaries=[]", spec.replace(" ", ""),
                      "build.spec binaries 必须为空，不得打包任何工具二进制")
        # hiddenimports 只允许 Python 模块名，不得出现工具二进制
        for bad in ("ffmpeg.exe", "whisper.exe", "yt-dlp.exe"):
            self.assertNotIn(bad, spec, "工具二进制不得进 build.spec：%s" % bad)

    def test_components_install_outside_repo(self):
        src = (ROOT / "components.py").read_text(encoding="utf-8")
        self.assertIn("LOCALAPPDATA", src,
                      "组件必须装到 %LOCALAPPDATA%，不进仓库/产物目录")
        self.assertIn("COMPONENT_DIR", src)

    def test_no_tool_exe_in_repo_tracked(self):
        import subprocess
        tracked = subprocess.run(
            ["git", "ls-files"], cwd=str(ROOT),
            capture_output=True, text=True).stdout.splitlines()
        for f in tracked:
            low = f.lower()
            self.assertFalse(low.endswith(("ffmpeg.exe", "ffprobe.exe",
                                           "whisper.exe", "yt-dlp.exe")),
                             "仓库不得跟踪工具二进制：%s" % f)


class TestComponentContractSource(unittest.TestCase):
    """红线 3：新模块必须被门禁 + CI 守护。"""

    def test_gate_and_ci_cover_components(self):
        gate = (ROOT / "tools" / "check_release.py").read_text(encoding="utf-8")
        self.assertIn("components.py", gate, "门禁未纳入 components.py 语法校验")
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("test_components", ci, "CI 未纳入 test_components")

    def test_docstring_states_no_auto_download(self):
        src = (ROOT / "components.py").read_text(encoding="utf-8")
        self.assertIn("绝不主动下载", src)
        self.assertIn("手动点击", src)



class TestPipInterpreter(unittest.TestCase):
    """回归：冻结态必须用真 Python 跑 pip（用户 2026-11-19 pip 退出码 2）。"""

    def setUp(self):
        import components
        self.c = components

    def test_source_mode_uses_sys_executable(self):
        with mock.patch.object(self.c.sys, "frozen", False, create=True):
            self.assertEqual(self.c._python_for_pip(), self.c.sys.executable)

    def test_frozen_mode_uses_path_python(self):
        import shutil
        real_py = shutil.which("python") or shutil.which("python.exe")
        if not real_py:
            self.skipTest("PATH 无 python")
        with mock.patch.object(self.c.sys, "frozen", True, create=True), \
             mock.patch.object(self.c.sys, "executable",
                               r"C://fake//Jinghe.exe"):
            got = self.c._python_for_pip()
        # 必须返回 PATH 上的真 Python，绝不是 Jinghe.exe
        self.assertNotIn("Jinghe.exe", got)
        self.assertTrue(os.path.basename(got).lower().startswith("python"))

    def test_frozen_mode_no_python_raises(self):
        # 屏蔽全部查找策略：which、PATH、CLI 反推、常见位置（glob）
        with mock.patch.object(self.c.sys, "frozen", True, create=True), \
             mock.patch.object(self.c.sys, "executable",
                               r"C://fake//Jinghe.exe"), \
             mock.patch.object(self.c.shutil, "which", return_value=""), \
             mock.patch.dict(os.environ, {"PATH": ""}), \
             mock.patch.object(self.c.Path, "glob", return_value=[]), \
             mock.patch.object(self.c, "_python_root_has_exe", return_value=""):
            with self.assertRaises(RuntimeError) as ctx:
                self.c._python_for_pip()
        msg = str(ctx.exception)
        self.assertIn("Python", msg)
        self.assertIn("640", msg), "报错应告知体积，避免用户困惑"
        self.assertIn("pip install", msg), "报错应给出可操作指引"

    def test_scripts_parent_fallback(self):
        # 关键回归：PATH 只含 Scripts 目录（无 python.exe）时，从父目录反推。
        # 这正是本机 workbuddy Python 布局，也是用户安装失败的真正原因。
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "Python313"
            scripts = root / "Scripts"
            scripts.mkdir(parents=True)
            fake_exe = root / "python.exe"
            fake_exe.write_bytes(b"")
            with mock.patch.object(self.c.sys, "frozen", True, create=True), \
                 mock.patch.object(self.c.sys, "executable",
                                   r"C://fake//Jinghe.exe"), \
                 mock.patch.object(self.c.shutil, "which",
                                   side_effect=lambda n: str(scripts) if n == "whisper" else ""), \
                 mock.patch.dict(os.environ, {"PATH": str(scripts)}):
                got = self.c._python_for_pip()
            self.assertEqual(got, str(fake_exe),
                             "应从 Scripts 反推父目录的 python.exe")

    def test_pip_cmd_no_empty_proxy(self):
        # 无代理时不得传 --proxy ""（旧代码永远生效不了的 bug）
        with mock.patch.dict(os.environ, {"HTTPS_PROXY": "", "https_proxy": "",
                                          "HTTP_PROXY": "", "http_proxy": ""},
                             clear=False), \
             mock.patch.object(self.c, "_python_for_pip", return_value="python"):
            cmd = self.c._pip_cmd_install("yt-dlp")
        self.assertNotIn("--proxy", cmd, "无代理时不应传 --proxy")

    def test_pip_cmd_with_proxy(self):
        with mock.patch.dict(os.environ, {"HTTPS_PROXY": "http://proxy:1"},
                             clear=False), \
             mock.patch.object(self.c, "_python_for_pip", return_value="python"):
            cmd = self.c._pip_cmd_install("yt-dlp")
        self.assertIn("--proxy", cmd)
        self.assertIn("http://proxy:1", cmd)

    def test_scripts_dir_uses_real_python(self):
        # 冻结态 Scripts 目录应来自真 Python，不是 exe 临时解压目录
        with mock.patch.object(self.c.sys, "frozen", True, create=True), \
             mock.patch.object(self.c.sys, "executable",
                               r"C://fake//Jinghe.exe"), \
             mock.patch.object(self.c, "_python_for_pip",
                               return_value=r"C://Python313//python.exe"):
            d = self.c._scripts_dir()
        self.assertIn("Python313", str(d))
        self.assertTrue(str(d).lower().endswith("scripts"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
