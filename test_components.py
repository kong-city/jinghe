
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S10 · 可选组件管理契约测试（修复「假绿灯」）。

用户 2026-11-19 裁决：
1. 软件绝不主动下载组件，只有用户手动点「启用」按钮才下载；
2. ffmpeg / whisper / yt-dlp 不进 exe、不进 Release、不随 GitHub 上传；
3. 新模块必须有测试 + 门禁 + CI 守护（此前 components.py 零测试 = 假绿灯）。

本测试锁死上述红线，任何绕过都会变红。
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
import io
import json
import os
import subprocess
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
        src = (ROOT / "knowledge" / "components.py").read_text(encoding="utf-8")
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
        src = (ROOT / "knowledge" / "components.py").read_text(encoding="utf-8")
        self.assertIn("绝不主动下载", src)
        self.assertIn("手动点击", src)



class TestPipInterpreter(unittest.TestCase):
    """回归：冻结态必须用真 Python 跑 pip（用户 2026-11-19 pip 退出码 2）。"""

    def setUp(self):
        import components
        self.c = components
        # 清冻结态 Python 选择缓存（否则跨用例污染）
        self.c._PIP_PYTHON = ""
        self.c._PIP_PYTHON_FP = ""

    def tearDown(self):
        self.c._PIP_PYTHON = ""
        self.c._PIP_PYTHON_FP = ""

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



class TestPipProbeSameSource(unittest.TestCase):
    """回归：pip 装到哪个 Python，探测就必须查那个 Python 的 Scripts。

    用户 2026-11-19 实测报错「安装结束但仍探测不到 whisper.exe」——
    根因是 junction 展开（Path.resolve）导致 pip 用真实路径、探测用别名
    路径，两者可能不是同一目录 → 装探错位。本组测试锁死同源。
    """

    def setUp(self):
        import components
        self.c = components
        self.c._PIP_PYTHON = ""
        self.c._PIP_PYTHON_FP = ""

    def tearDown(self):
        self.c._PIP_PYTHON = ""
        self.c._PIP_PYTHON_FP = ""

    def test_scripts_dir_comes_from_pip_itself(self):
        """_scripts_dir 必须问 pip（sysconfig），不得用 resolve() 猜。"""
        with tempfile.TemporaryDirectory() as td:
            py = Path(td) / "PyA" / "python.exe"
            py.parent.mkdir(parents=True)
            py.write_bytes(b"")
            fake_scripts = py.parent / "Scripts"
            fake_scripts.mkdir()
            with mock.patch.object(self.c, "_python_for_pip", return_value=str(py)), \
                 mock.patch.object(self.c, "_pip_scripts_dir",
                                   return_value=fake_scripts) as m:
                got = self.c._scripts_dir()
            self.assertEqual(got, fake_scripts)
            m.assert_called_once_with(str(py))

    def test_pip_scripts_dir_asks_pip(self):
        """_pip_scripts_dir 应执行 python -c sysconfig 并采用其输出。"""
        with tempfile.TemporaryDirectory() as td:
            scripts = Path(td) / "RealScripts"
            scripts.mkdir()
            py = Path(td) / "python.exe"
            py.write_bytes(b"")
            out = mock.Mock(stdout=str(scripts) + "\n", stderr="", returncode=0)
            with mock.patch.object(self.c.subprocess, "run", return_value=out):
                got = self.c._pip_scripts_dir(str(py))
            self.assertEqual(got, scripts)

    def test_candidate_dirs_include_all_scripts(self):
        """候选目录必须包含 PATH 里所有 Scripts（多 Python 共存场景）。"""
        with tempfile.TemporaryDirectory() as td:
            a = Path(td) / "A" / "Scripts"
            b = Path(td) / "B" / "Scripts"
            a.mkdir(parents=True); b.mkdir(parents=True)
            with mock.patch.object(self.c, "_scripts_dir", return_value=a), \
                 mock.patch.dict(os.environ, {"PATH": str(b)}, clear=False):
                dirs = [str(x) for x in self.c._candidate_scripts_dirs()]
            self.assertIn(str(a), dirs)
            self.assertIn(str(b), dirs)

    def test_install_error_carries_diagnostics(self):
        """安装后探测失败的报错必须带诊断信息，不能只有一句谜语。"""
        src = (ROOT / "knowledge" / "components.py").read_text(encoding="utf-8")
        self.assertIn("诊断：pip 使用 Python", src)
        self.assertIn("探测查找目录", src)
        self.assertIn("目标文件是否存在", src)



class TestNoConsolePopup(unittest.TestCase):
    """回归：所有子进程调用必须隐藏控制台窗口。

    用户 2026-11-19 实测：桌面一直弹终端黑框。根因是探测 pip 路径的
    ``subprocess.run([python, "-c", ...])`` 漏加 ``creationflags``，
    每探测一次组件就弹一个窗。此处锁死「不得有裸 subprocess 调用」。
    """

    def test_components_subprocess_all_hide_window(self):
        import re
        src = (ROOT / "knowledge" / "components.py").read_text(encoding="utf-8")
        bad = []
        # 用括号配平切出完整调用块，再看是否带 creationflags
        for m in re.finditer(r"subprocess\.(run|Popen|call)\(", src):
            i = src.index("(", m.start())
            depth, j = 0, i
            while j < len(src):
                if src[j] == "(":
                    depth += 1
                elif src[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            blk = src[i:j + 1]
            if "creationflags" not in blk and "NO_WINDOW" not in blk:
                bad.append(src[:m.start()].count("\n") + 1)
        self.assertEqual(bad, [], "components.py 存在会弹终端窗的子进程调用，行号 %s" % bad)

    def test_pip_scripts_dir_hides_window(self):
        src = (ROOT / "knowledge" / "components.py").read_text(encoding="utf-8")
        blk = src[src.index("def _pip_scripts_dir"):src.index("def _python_for_pip")]
        self.assertIn("creationflags=_CREATE_NO_WINDOW", blk,
                      "_pip_scripts_dir 必须隐藏控制台窗口，否则桌面弹黑框")



class TestConsoleScriptRecovery(unittest.TestCase):
    """回归：包已装但 console script（exe）缺失时，必须离线补生成。

    用户 2026-11-19 实测：pip 报 "Requirement already satisfied" 就整个
    跳过安装，**不会补回丢失的 whisper.exe** → 软件报「安装结束仍探测不到」。
    重装（--force-reinstall）不可行：需重下 640MB 且内网镜像不可达。
    """

    def setUp(self):
        import components
        self.c = components
        self.c._PIP_PYTHON = ""
        self.c._PIP_PYTHON_FP = ""

    def tearDown(self):
        self.c._PIP_PYTHON = ""
        self.c._PIP_PYTHON_FP = ""

    def test_ensure_console_script_uses_distlib_scriptmaker(self):
        src = (ROOT / "knowledge" / "components.py").read_text(encoding="utf-8")
        self.assertIn("def _ensure_console_script", src)
        # 必须用 pip 自带的 distlib ScriptMaker（离线、不重装）
        self.assertIn("ScriptMaker", src)
        self.assertIn("pip._vendor.distlib.scripts", src)
        # 不得依赖 force-reinstall（需重下 640MB 且该模式在部分网络下
        # 会报 "from versions: none"）——只看 _pip_cmd_install 的实际命令行
        cmd_fn = src[src.index("def _pip_cmd_install"):
                     src.index("def _pip_install")]
        self.assertNotIn("--force-reinstall", cmd_fn,
                         "不得用 force-reinstall：需重下 640MB 且可能不可达")

    def test_install_worker_calls_recovery_when_exe_missing(self):
        src = (ROOT / "knowledge" / "components.py").read_text(encoding="utf-8")
        blk = src[src.index("def _install_worker"):]
        blk = blk[:blk.index("def ", 10)]
        self.assertIn("_ensure_console_script", blk,
                      "安装流程必须在 exe 缺失时调用补生成")
        self.assertIn("is_file()", blk)

    def test_recovery_raises_with_readable_message(self):
        with mock.patch.object(self.c.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=1, stdout="", stderr="boom")
            with self.assertRaises(RuntimeError) as ctx:
                self.c._ensure_console_script(r"C:/fake/python.exe",
                                              "openai-whisper", "whisper.exe")
        self.assertIn("whisper.exe", str(ctx.exception))
        self.assertIn("boom", str(ctx.exception))



class TestFastProbePath(unittest.TestCase):
    """回归：whisper 探测走轻量快路径，且超时与「未安装」严格区分。

    用户 2026-11-19 实测：`whisper --help` 会连带 import torch（509 MB），
    冷启动 4–7 秒，机器繁忙时逼近 15 秒超时 → **被静默误判为「未安装」**。
    修复：轻量快路径（纯文件检查，毫秒级）+ 深度验证（真跑命令）双轨。
    """

    def test_toOL_specs_structure_unchanged(self):
        """S1 契约：TOOL_SPECS 三元组结构一字不动。"""
        import media_tools
        self.assertEqual(len(media_tools.TOOL_SPECS), 3)
        for spec in media_tools.TOOL_SPECS:
            self.assertEqual(len(spec), 3, "TOOL_SPECS 三元组结构被改动")
        self.assertEqual([s[0] for s in media_tools.TOOL_SPECS],
                         ["ffmpeg", "whisper", "yt-dlp"])

    def test_light_check_requires_three_evidence(self):
        """轻量检查必须三重校验：dist-info + 包目录 + entry point。"""
        import media_tools
        src = (ROOT / "media" / "media_tools.py").read_text(encoding="utf-8")
        # 三重校验在通用实现 _light_check_package 里
        blk = src[src.index("def _light_check_package"):
                  src.index("def _light_check_whisper")]
        self.assertIn("entry_points.txt", blk)
        self.assertIn("sp.glob(dist_glob)", blk, "必须按发行版 glob 找 dist-info")
        self.assertIn("(sp / pkg_dir).is_dir()", blk, "必须校验包目录存在")
        # 各工具的包名映射
        self.assertIn("openai_whisper-*.dist-info", src)
        self.assertIn("yt_dlp-*.dist-info", src)
        self.assertIn('"whisper"', src)
        self.assertIn('"yt-dlp"', src)

    def test_probe_state_distinguishes_timeout_from_missing(self):
        """超时必须与「真没装」区分开（state 字段）。"""
        import media_tools
        ad = media_tools.ToolAdapter("whisper", ["--help"], None, timeout=0.01,
                                     which=lambda n: r"C://fake//whisper.exe")
        def _timeout_runner(**kw):
            raise subprocess.TimeoutExpired(cmd="x", timeout=0.01)
        ad._runner = _timeout_runner
        r = ad.probe()
        self.assertEqual(r.get("state"), "timeout")
        self.assertFalse(r["available"])
        self.assertIn("可能已安装", r["reason"])

    def test_missing_tool_state(self):
        import media_tools
        ad = media_tools.ToolAdapter("whisper", ["--help"], None,
                                     which=lambda n: None)
        r = ad.probe()
        self.assertEqual(r.get("state"), "missing")

    def test_deep_mode_skips_fast_path(self):
        """深度验证必须真跑命令（deep=True 不走轻量快路径）。"""
        import media_tools
        ad = media_tools.ToolAdapter("whisper", ["--help"], None,
                                     which=lambda n: r"C://fake//whisper.exe",
                                     deep=True)
        called = []
        ad._runner = lambda **kw: (called.append(kw) or
                                   mock.Mock(returncode=0, stdout="", stderr=""))
        ad.probe()
        self.assertTrue(called, "deep 模式必须真跑探测命令")

    def test_probe_deep_entry_exists(self):
        import media_tools
        self.assertTrue(hasattr(media_tools, "probe_deep"))



class TestProbeRefreshWindow(unittest.TestCase):
    """回归：一轮刷新只真探一次（用户 2026-11-19 实测端点耗时 4 秒）。

    /api/tools/probe 会依次调 payload → audio_transcribe → video_transcribe，
    三处都取工具状态；各自带 refresh=True 就是把同一份探测跑 3 遍。
    修复用「刷新窗口」：一轮内共享同一份结果。

    同时锁死「不得在持锁时调用探测」——非重入锁会死锁（实测端点直接超时）。
    """

    def setUp(self):
        import media_tools
        self.m = media_tools

    def tearDown(self):
        import media_tools
        media_tools.end_refresh()
        media_tools.reset_cache()

    def test_refresh_window_shares_one_probe(self):
        calls = []
        orig = self.m._probe_now

        def counting():
            calls.append(1)
            return orig()
        self.m._probe_now = counting
        try:
            self.m.begin_refresh()
            for _ in range(3):
                self.m.probe_all(refresh=True)
            self.assertEqual(len(calls), 1,
                             "一轮刷新内只应真探一次，实测 %d 次" % len(calls))
            # 新一轮 → 应再真探一次
            self.m.end_refresh()
            self.m.begin_refresh()
            self.m.probe_all(refresh=True)
            self.assertEqual(len(calls), 2, "新一轮刷新应再真探一次")
        finally:
            self.m._probe_now = orig

    def test_probe_now_not_called_under_lock(self):
        """_probe_now 绝不能在持有 _LOCK 时调用（非重入锁 → 死锁）。"""
        src = (ROOT / "media" / "media_tools.py").read_text(encoding="utf-8")
        fn = src[src.index("def probe_all"):src.index("def begin_refresh")]
        # probe_all 的函数体里，with _LOCK 块之后才调 _probe_now
        lock_idx = fn.index("with _LOCK:")
        after = fn[lock_idx:]
        block_end = after.index("if cached is not None:")
        in_lock = after[:block_end]
        self.assertNotIn("_probe_now()", in_lock,
                         "_probe_now 不得在持锁期间调用（会死锁）")

    def test_ytdlp_also_uses_light_path(self):
        """yt-dlp 同为纯 Python 包，也走轻量路径（--version 要 1.2 秒）。"""
        import media_tools
        self.assertIn("yt-dlp", media_tools._LIGHT_CHECKS)
        self.assertNotIn("ffmpeg", media_tools._LIGHT_CHECKS,
                         "ffmpeg 是独立二进制，无 Python 包，不走轻量路径")


if __name__ == "__main__":
    unittest.main(verbosity=2)
