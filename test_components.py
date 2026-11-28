
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
        # **隔离本机真实 venv 状态**（v1.4.0）：本组测试验证的是
        # 「venv 尚未建立」时的回退逻辑；若不隔离，测试机上若存在
        # %LOCALAPPDATA%\Jinghe\components\venv，则 _python_for_pip /
        # _scripts_dir 会优先返回 venv，把本组断言全部带偏（实测 7 例假失败）。
        self._venv_patch = mock.patch.object(
            self.c, "_venv_python_usable", return_value=False)
        self._venv_patch.start()
        self.addCleanup(self._venv_patch.stop)

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
        # 隔离本机真实 venv 状态（v1.4.0）：本组验证「venv 未建立」时的同源逻辑
        self._venv_patch = mock.patch.object(
            self.c, "_venv_python_usable", return_value=False)
        self._venv_patch.start()
        self.addCleanup(self._venv_patch.stop)

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
        """候选目录必须包含 PATH 里所有 Scripts（多 Python 共存场景）。

        **v1.4.0 适配**：候选目录的第 ② 项现在直接问**系统 Python**
        （``_find_python_for_pip`` + ``_pip_scripts_dir``）而不再经
        ``_scripts_dir``（后者在 venv 可用时返回 venv），
        故 mock 对象同步更新；测试意图（所有 Scripts 都要被纳入）不变。
        """
        with tempfile.TemporaryDirectory() as td:
            a = Path(td) / "A" / "Scripts"
            b = Path(td) / "B" / "Scripts"
            a.mkdir(parents=True); b.mkdir(parents=True)
            with mock.patch.object(self.c, "_find_python_for_pip",
                                   return_value=r"C://fake//python.exe"), \
                 mock.patch.object(self.c, "_pip_scripts_dir",
                                   return_value=a), \
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
        # **按函数边界切片，不依赖定义顺序**（v1.4.0 把 _pip_scripts_dir
        # 移到了 _python_for_pip 之后，原先的 index 切片会变成空串）
        start = src.index("def _pip_scripts_dir")
        end = src.index("\ndef ", start + 1)
        blk = src[start:end]
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


# --------------------------------------------------------------------------- #
# 缺陷 1：.part 残留清理（用户 2026-11-23 实测本机残留 13.6MB）
# --------------------------------------------------------------------------- #
class TestPartCleanup(unittest.TestCase):
    """.part 半截文件在任何失败路径都必须被清理。"""

    def setUp(self):
        import components
        self.c = components
        self._optin = dict(self.c._USER_OPT_IN)
        self.c._USER_OPT_IN.update({"granted": True, "component_id": "ffmpeg"})
        self.tmp = tempfile.mkdtemp(prefix="jinghe-part-")
        self.dest = Path(self.tmp) / "pkg.zip"

    def tearDown(self):
        self.c._USER_OPT_IN.update(self._optin)
        try:
            for p in Path(self.tmp).glob("*"):
                p.unlink(missing_ok=True)
            Path(self.tmp).rmdir()
        except OSError:
            pass

    def test_part_removed_on_network_failure(self):
        """网络中断（urlopen 抛异常）→ .part 不得残留。"""
        part = self.dest.with_name(self.dest.name + ".part")

        class _Resp:
            headers = {"Content-Length": "100"}

            def read(self, n):
                return b"x" * 10

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def _boom(req, timeout=None):
            # 先写一半再抛错，模拟「下载中断」
            part.write_bytes(b"partial")
            raise OSError("网络中断")

        with mock.patch.object(self.c.urllib.request, "urlopen", _boom):
            with self.assertRaises(OSError):
                self.c._download("https://example.com/x.zip", self.dest, "ffmpeg")
        self.assertFalse(part.exists(),
                         "网络中断后 .part 必须被清理，实际残留 %d 字节"
                         % (part.stat().st_size if part.exists() else 0))

    def test_part_removed_on_cancel(self):
        """主动取消 → .part 必须被清理（原有行为不能退化）。"""
        part = self.dest.with_name(self.dest.name + ".part")

        class _Resp:
            headers = {"Content-Length": "100"}

            def read(self, n):
                part.write_bytes(b"partial")
                return b"x" * 10

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with mock.patch.object(self.c.urllib.request, "urlopen",
                               lambda req, timeout=None: _Resp()):
            with mock.patch.object(self.c, "_cancelled", return_value=True):
                with self.assertRaises(RuntimeError):
                    self.c._download("https://example.com/x.zip", self.dest, "ffmpeg")
        self.assertFalse(part.exists(), "取消后 .part 必须被清理")

    def test_cleanup_stale_parts_removes_only_part_files(self):
        """兜底清理：只删 *.part 文件，不动其它文件、不动目录。"""
        with mock.patch.object(self.c, "COMPONENT_DIR", Path(self.tmp)):
            (Path(self.tmp) / "a.zip.part").write_bytes(b"x")
            (Path(self.tmp) / "b.zip.part").write_bytes(b"x")
            (Path(self.tmp) / "keep.zip").write_bytes(b"x")
            (Path(self.tmp) / "keep.txt").write_bytes(b"x")
            sub = Path(self.tmp) / "sub.part"
            sub.mkdir()
            removed = self.c._cleanup_stale_parts()
            self.assertEqual(sorted(removed), ["a.zip.part", "b.zip.part"],
                             "只应清理顶层 .part 文件")
            self.assertTrue((Path(self.tmp) / "keep.zip").exists(),
                            "非 .part 文件不得被删")
            self.assertTrue((Path(self.tmp) / "keep.txt").exists(),
                            "非 .part 文件不得被删")
            self.assertTrue(sub.exists(), "目录不得被删")


# --------------------------------------------------------------------------- #
# 缺陷 4：轻量探测假绿灯（包在 ≠ 能用）
# --------------------------------------------------------------------------- #
class TestImportAvailabilityCheck(unittest.TestCase):
    """外部位置的组件必须做导入可用性校验，受控目录的可跳过。"""

    def setUp(self):
        import components
        self.c = components
        self.c._IMPORT_CHECK_CACHE.clear()

    def tearDown(self):
        self.c._IMPORT_CHECK_CACHE.clear()

    def test_import_check_detects_broken_package(self):
        """import 失败 → 结论为不可用，且 reason 带真实错误。"""
        exe = r"C:\fake\python\Scripts\whisper.exe"
        py = r"C:\fake\python\python.exe"

        def _fake_run(cmd, **kw):
            self.assertIn("import whisper", cmd[-1])
            return subprocess.CompletedProcess(
                cmd, 1, stdout="OSError: [WinError 126] 找不到指定的模块",
                stderr=None)

        with mock.patch.object(self.c, "_interpreter_for", return_value=py), \
             mock.patch.object(self.c.subprocess, "run", _fake_run):
            ok, reason = self.c._import_check(exe, "whisper")
        self.assertFalse(ok, "import 失败必须判为不可用")
        self.assertIn("WinError 126", reason, "reason 必须带真实错误")

    def test_import_check_passes_for_healthy_package(self):
        """import 成功 → 判为可用。"""
        exe = r"C:\fake\python\Scripts\yt-dlp.exe"
        py = r"C:\fake\python\python.exe"

        def _fake_run(cmd, **kw):
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr=None)

        with mock.patch.object(self.c, "_interpreter_for", return_value=py), \
             mock.patch.object(self.c.subprocess, "run", _fake_run):
            ok, _ = self.c._import_check(exe, "yt_dlp")
        self.assertTrue(ok)

    def test_import_check_not_false_negative_when_no_interpreter(self):
        """找不到解释器 → 不误判为坏（宁可不校验，不冤枉好组件）。"""
        with mock.patch.object(self.c, "_interpreter_for", return_value=""):
            ok, _ = self.c._import_check(r"C:\x\Scripts\whisper.exe", "whisper")
        self.assertTrue(ok, "找不到解释器时不得误判为不可用")

    def test_import_check_result_is_cached(self):
        """校验结果必须缓存，避免每次刷新都起解释器（实测省 3 秒）。"""
        exe = r"C:\fake\python\Scripts\whisper.exe"
        py = r"C:\fake\python\python.exe"
        calls = []

        def _fake_run(cmd, **kw):
            calls.append(1)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr=None)

        with mock.patch.object(self.c, "_interpreter_for", return_value=py), \
             mock.patch.object(self.c.subprocess, "run", _fake_run):
            for _ in range(3):
                self.c._import_check(exe, "whisper")
        self.assertEqual(len(calls), 1,
                         "同一解释器+模块应只真跑一次，实测 %d 次" % len(calls))

    def test_probe_reports_broken_external_component_as_error(self):
        """探测层集成：外部位置的坏组件必须报 error，不得显示已安装。"""
        # 模拟：轻量探测判为可用，但导入校验失败
        fake = {"available": True, "version": "20250625", "reason": "",
                "path": r"C:\system\python\Scripts\whisper.exe", "state": "ok"}
        with mock.patch.object(self.c.media_tools.ToolAdapter, "probe",
                               return_value=fake), \
             mock.patch.object(self.c, "_is_managed_path", return_value=False), \
             mock.patch.object(self.c, "_import_check",
                               return_value=(False, "WinError 126 DLL 缺失")):
            got = self.c._probe_one("whisper")
        self.assertFalse(got["available"], "不可用的组件不得报 available")
        self.assertEqual(got["state"], "error", "必须报 error 而非 missing/ok")
        self.assertIn("WinError 126", got["reason"])

    def test_managed_path_skips_import_check(self):
        """受控目录内的组件跳过导入校验（装完已深验过，省时间）。"""
        fake = {"available": True, "version": "20250625", "reason": "",
                "path": r"C:\Jinghe\components\venv\Scripts\whisper.exe",
                "state": "ok"}
        with mock.patch.object(self.c.media_tools.ToolAdapter, "probe",
                               return_value=fake), \
             mock.patch.object(self.c, "_is_managed_path", return_value=True), \
             mock.patch.object(self.c, "_import_check") as m:
            got = self.c._probe_one("whisper")
        m.assert_not_called()
        self.assertTrue(got["available"])

    def test_is_managed_path_detects_component_dir(self):
        """受控目录判定：组件目录内的路径应为 True，外部应为 False。"""
        with mock.patch.object(self.c, "COMPONENT_DIR", Path(self.tmpdir())):
            inside = str(Path(self.tmpdir()) / "venv" / "Scripts" / "whisper.exe")
            outside = r"C:\Windows\System32\whisper.exe"
            self.assertTrue(self.c._is_managed_path(inside))
            self.assertFalse(self.c._is_managed_path(outside))

    def tmpdir(self):
        d = getattr(self, "_d", None)
        if d is None:
            d = tempfile.mkdtemp(prefix="jinghe-managed-")
            self._d = d
        return d


# --------------------------------------------------------------------------- #
# v1.4.0 组件收口：venv 优先 + 兼容回退 + 模型目录
# --------------------------------------------------------------------------- #
class TestVenvCollapse(unittest.TestCase):
    """组件统一收口到 %LOCALAPPDATA%\\Jinghe\\components\\venv 的契约。"""

    def setUp(self):
        import components
        self.c = components

    def test_component_paths_are_under_component_dir(self):
        """bin / models / venv 必须都在组件目录下（收口的根本前提）。"""
        root = self.c.COMPONENT_DIR
        for p in (self.c.BIN_DIR, self.c.MODELS_DIR, self.c.VENV_DIR):
            self.assertTrue(str(p).startswith(str(root)),
                            "%s 必须位于组件目录 %s 内" % (p, root))

    def test_venv_layout(self):
        """venv 内部路径：Scripts\\python.exe 与 Scripts 目录。"""
        self.assertEqual(self.c.VENV_PYTHON,
                         self.c.VENV_DIR / "Scripts" / "python.exe")
        self.assertEqual(self.c.VENV_SCRIPTS, self.c.VENV_DIR / "Scripts")

    def test_python_for_pip_prefers_venv(self):
        """venv 可用时，pip 目标解释器必须是 venv 内的 python（装探同源）。"""
        with mock.patch.object(self.c, "_venv_python_usable", return_value=True), \
             mock.patch.object(self.c, "VENV_PYTHON",
                               Path(r"C:\Jinghe\components\venv\Scripts\python.exe")):
            got = self.c._python_for_pip()
        self.assertEqual(got, str(Path(r"C:\Jinghe\components\venv\Scripts\python.exe")))

    def test_scripts_dir_prefers_venv(self):
        """venv 可用时，_scripts_dir 必须返回 venv\\Scripts。"""
        with mock.patch.object(self.c, "_venv_python_usable", return_value=True), \
             mock.patch.object(self.c, "VENV_SCRIPTS",
                               Path(r"C:\Jinghe\components\venv\Scripts")):
            got = self.c._scripts_dir()
        self.assertEqual(got, Path(r"C:\Jinghe\components\venv\Scripts"))

    def test_candidate_dirs_venv_first(self):
        """候选目录优先级：venv 必须排第一。"""
        with mock.patch.object(self.c, "_venv_python_usable", return_value=True), \
             mock.patch.object(self.c, "VENV_SCRIPTS",
                               Path(r"C:\Jinghe\components\venv\Scripts")), \
             mock.patch.object(self.c, "_find_python_for_pip",
                               return_value=r"C://sys//python.exe"), \
             mock.patch.object(self.c, "_pip_scripts_dir",
                               return_value=Path(r"C:\sys\Scripts")):
            dirs = self.c._candidate_scripts_dirs()
        self.assertTrue(dirs)
        self.assertEqual(dirs[0], Path(r"C:\Jinghe\components\venv\Scripts"))

    def test_candidate_dirs_keep_system_python_fallback(self):
        """**兼容回退不可丢**：系统 Python 的 Scripts 必须仍在候选里。

        用户 2026-11-23 实测踩坑：本机系统 Python 的 Scripts **不在 PATH**，
        若只靠 PATH 扫描，venv 优先后系统那份 whisper/yt-dlp 就探测不到 →
        直接违背「兼容用户已有组件、不强制重装」的承诺。
        """
        with mock.patch.object(self.c, "_venv_python_usable", return_value=True), \
             mock.patch.object(self.c, "VENV_SCRIPTS",
                               Path(r"C:\Jinghe\components\venv\Scripts")), \
             mock.patch.object(self.c, "_find_python_for_pip",
                               return_value=r"C://sys//python.exe"), \
             mock.patch.object(self.c, "_pip_scripts_dir",
                               return_value=Path(r"C:\sys\Scripts")):
            dirs = [str(d) for d in self.c._candidate_scripts_dirs()]
        self.assertIn(str(Path(r"C:\sys\Scripts")), dirs,
                      "系统 Python 的 Scripts 必须保留在候选目录中")

    def test_ensure_path_reorders_venv_to_front(self):
        """PATH 必须按优先级**重排**（不能「已存在就跳过」）。

        实测踩坑：本机系统 Python 的 Scripts 本来就在 PATH 首位，
        旧实现见「已存在」就跳过 → venv 虽有 yt-dlp，which 仍命中系统那份。

        用**真实临时目录**（不存在的目录本就不该进 PATH）。
        """
        with tempfile.TemporaryDirectory() as td:
            venv_s = Path(td) / "venv" / "Scripts"
            sys_s = Path(td) / "sys" / "Scripts"
            venv_s.mkdir(parents=True)
            sys_s.mkdir(parents=True)
            with mock.patch.object(self.c, "_cleanup_stale_parts", return_value=[]), \
                 mock.patch.object(self.c, "_candidate_scripts_dirs",
                                   return_value=[venv_s, sys_s]), \
                 mock.patch.object(self.c, "BIN_DIR", Path(td) / "bin"), \
                 mock.patch.dict(os.environ,
                                 {"PATH": os.pathsep.join([str(sys_s), r"C:\other"])},
                                 clear=False):
                self.c.ensure_component_path()
                got = os.environ.get("PATH", "").split(os.pathsep)
            self.assertEqual(got[0], str(venv_s),
                             "venv 必须被排到 PATH 最前，实测 %s" % got[0])

    def test_venv_usable_requires_pyvenv_cfg(self):
        """venv 有效性：缺 pyvenv.cfg 不算可用（防只剩 Scripts 的残废 venv）。"""
        with tempfile.TemporaryDirectory() as td:
            vdir = Path(td) / "venv"
            (vdir / "Scripts").mkdir(parents=True)
            (vdir / "Scripts" / "python.exe").write_bytes(b"")
            with mock.patch.object(self.c, "VENV_DIR", vdir), \
                 mock.patch.object(self.c, "VENV_PYTHON",
                                   vdir / "Scripts" / "python.exe"), \
                 mock.patch.object(self.c.subprocess, "run",
                                   return_value=subprocess.CompletedProcess([], 0)):
                self.assertFalse(self.c._venv_python_usable(),
                                 "缺 pyvenv.cfg 的残废 venv 不得判为可用")

    def test_pip_cmd_targets_venv(self):
        """pip 安装命令的解释器必须是 venv 内的 python。"""
        with mock.patch.object(self.c, "_venv_python_usable", return_value=True), \
             mock.patch.object(self.c, "VENV_PYTHON",
                               Path(r"C:\Jinghe\components\venv\Scripts\python.exe")):
            cmd = self.c._pip_cmd_install("yt-dlp")
        self.assertTrue(cmd[0].endswith("venv\\Scripts\\python.exe"),
                        "pip 目标必须是 venv 内的 python，实测 %s" % cmd[0])

    def test_whisper_model_dir_is_managed(self):
        """whisper 模型目录必须落在组件目录内（不再散落 ~/.cache/whisper）。"""
        import media_tools
        d = media_tools.whisper_model_dir()
        self.assertIn("Jinghe", d)
        self.assertTrue(d.replace("/", "\\").endswith("components\\models"),
                        "模型目录实测算 %s" % d)

    def test_whisper_argv_has_model_dir(self):
        """两个转写模块的 whisper 命令都必须带 --model_dir。"""
        import audio_transcribe
        import video_transcribe
        cap = {"tools": {"whisper": {"path": "whisper.exe"}}}
        for mod in (audio_transcribe, video_transcribe):
            argv = mod._whisper_argv(Path("a.wav"), Path("/tmp"), cap, "base")
            self.assertIn("--model_dir", argv,
                          "%s 的 whisper 命令必须带 --model_dir" % mod.__name__)
            self.assertIn("models", argv[-1])

    def test_migration_hint_for_external_component(self):
        """系统里有、组件目录里没有 → 给出迁移提示（不强制重装）。"""
        with mock.patch.object(self.c, "_is_managed_path", return_value=False), \
             mock.patch.object(self.c.shutil, "which",
                               return_value=r"C:\sys\Scripts\yt-dlp.exe"):
            hint = self.c._external_install_hint(
                {"id": "yt-dlp", "name": "yt-dlp", "probe": "yt-dlp"})
        self.assertIn("系统 Python", hint)
        self.assertIn("不影响使用", hint)

    def test_no_migration_hint_for_managed_component(self):
        """已在受控目录内 → 不给迁移提示。"""
        with mock.patch.object(self.c, "_is_managed_path", return_value=True), \
             mock.patch.object(self.c.shutil, "which",
                               return_value=r"C:\Jinghe\venv\Scripts\yt-dlp.exe"):
            hint = self.c._external_install_hint(
                {"id": "yt-dlp", "name": "yt-dlp", "probe": "yt-dlp"})
        self.assertEqual(hint, "")


class TestDllPrecheck(unittest.TestCase):
    """DLL 依赖预检（用户 2026-11-23 实测缺陷）。

    背景：本机 System32 缺 ``VCRUNTIME140_THREADS.dll`` 与
    ``MSVCP140_ATOMIC_WAIT.dll``（均属 Microsoft Visual C++
    Redistributable），导致 torch_cpu.dll / torch_python.dll 加载失败 →
    whisper 报 ``OSError: [WinError 126]``。但 venv 里 whisper.exe 在、
    pip 装成功、界面却显示「已安装」—— 假绿灯。

    根因：受控目录（venv）曾被豁免导入校验。修复方案是受控目录改用
    **DLL 依赖预检**（毫秒级，纯文件扫描，不加载 300MB 的 torch）。
    """

    def setUp(self):
        import components
        self.c = components

    def _real_torch_dll(self) -> Path | None:
        """找一份真实的 torch DLL 作夹具。

        真实 torch 的 ``torch_cpu.dll`` 依赖 ``VCRUNTIME140_THREADS.dll``
        （Microsoft Visual C++ Redistributable 的一部分）—— 这正是
        「装了 whisper 却用不了」的真实成因，用它当夹具最贴近现场。
        """
        roots = [
            Path(r"C:\Users\songweihu\AppData\Local\Jinghe\components\venv"),
            Path(sys.prefix).parent,
            Path(sys.prefix),
        ]
        for root in roots:
            cand = root / "Lib" / "site-packages" / "torch" / "lib" / "torch_cpu.dll"
            if cand.is_file():
                return cand
        return None

    @staticmethod
    def _real_system_dll() -> Path | None:
        """找一份真实的小型系统 DLL 当夹具。"""
        sys32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
        for name in ("winmm.dll", "version.dll", "mpr.dll", "userenv.dll"):
            p = sys32 / name
            if p.is_file():
                return p
        return None

    def test_pe_import_parser_reads_dlls(self):
        """PE 导入表解析必须能读出依赖的 DLL 名（用真实 DLL 验证）。"""
        dll = self._real_torch_dll() or self._real_system_dll()
        if dll is None:
            self.skipTest("找不到可用的 DLL 夹具")
        got = self.c._pe_import_dlls(dll)
        self.assertTrue(got, "真实 DLL 必须能解析出导入表")
        self.assertTrue(any(n.lower().endswith(".dll") for n in got))

    def test_pe_import_parser_tolerates_garbage(self):
        """非 PE / 损坏文件必须返回空列表（宁可放过，不误报）。"""
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "bad.dll"
            bad.write_bytes(b"not a pe file at all")
            self.assertEqual(self.c._pe_import_dlls(bad), [])
            self.assertEqual(self.c._pe_import_dlls(Path(td) / "missing.dll"), [])

    def test_dll_precheck_detects_missing_msvc_runtime(self):
        """缺 VC++ 运行库必须被抓到，并给出「装 VC++ Redistributable」的指引。

        用**真实 torch DLL**（依赖 VCRUNTIME140_THREADS.dll）当夹具：
        这正是用户本机的真实故障场景。

        组件 bin 目录（v1.8.5 起也是合法 DLL 来源）必须**显式隔离**：
        否则开发机若恰好备了 VC++ 补充 DLL，「缺 VC++」这一前提就被打破，
        预检会改报别的缺件——用例结果取决于开发机状态，而非被测逻辑。
        """
        src = self._real_torch_dll()
        if src is None:
            self.skipTest("本机无 torch DLL 夹具")
        with tempfile.TemporaryDirectory() as td:
            sp = Path(td) / "Lib" / "site-packages"
            lib = sp / "torch" / "lib"
            lib.mkdir(parents=True)
            (lib / "torch_cpu.dll").write_bytes(src.read_bytes())
            empty_bin = Path(td) / "empty_bin"
            empty_bin.mkdir()
            with mock.patch.object(self.c, "BIN_DIR", empty_bin):
                ok, reason = self.c._dll_precheck(sp, "whisper")
        self.assertFalse(ok, "隔离组件 bin 后仍应判定缺 VC++ 运行库")
        self.assertIn("VCRUNTIME140_THREADS.dll", reason)
        self.assertIn("Visual C++", reason)

    def test_dll_precheck_passes_when_all_present(self):
        """依赖齐备时必须放行（不能误报）。"""
        src = self._real_system_dll()
        if src is None:
            self.skipTest("找不到系统 DLL 夹具")
        with tempfile.TemporaryDirectory() as td:
            sp = Path(td) / "Lib" / "site-packages"
            lib = sp / "torch" / "lib"
            lib.mkdir(parents=True)
            (lib / "a.dll").write_bytes(src.read_bytes())
            empty_bin = Path(td) / "empty_bin"
            empty_bin.mkdir()
            with mock.patch.object(self.c, "BIN_DIR", empty_bin):
                ok, reason = self.c._dll_precheck(sp, "whisper")
        self.assertTrue(ok, "系统 DLL 依赖齐备，不该报缺失：%s" % reason)

    def test_dll_precheck_scoped_per_component(self):
        """预检必须按组件范围扫描 —— yt-dlp 不该被 whisper 的 torch 问题连坐。"""
        src = self._real_torch_dll()
        if src is None:
            self.skipTest("本机无 torch DLL 夹具")
        with tempfile.TemporaryDirectory() as td:
            sp = Path(td) / "Lib" / "site-packages"
            lib = sp / "torch" / "lib"
            lib.mkdir(parents=True)
            (lib / "torch_cpu.dll").write_bytes(src.read_bytes())
            empty_bin = Path(td) / "empty_bin"
            empty_bin.mkdir()
            with mock.patch.object(self.c, "BIN_DIR", empty_bin):
                # yt-dlp 是纯 Python 包，不依赖 torch → 必须放行
                ok, _ = self.c._dll_precheck(sp, "yt-dlp")
        self.assertTrue(ok, "yt-dlp 不该被 torch 的环境问题连坐")

    def test_managed_component_not_exempt_from_check(self):
        """受控目录组件**不得**豁免校验 —— 豁免会让假绿灯回归。

        这是本组测试的核心契约：venv 里的 whisper 因缺 VC++ 运行库
        不可用，探测必须如实报 error，而不是 installed=True。
        """
        src = self._real_torch_dll()
        if src is None:
            self.skipTest("本机无 torch DLL 夹具")
        with tempfile.TemporaryDirectory() as td:
            sp = Path(td) / "Lib" / "site-packages"
            lib = sp / "torch" / "lib"
            lib.mkdir(parents=True)
            (lib / "torch_cpu.dll").write_bytes(src.read_bytes())
            exe = Path(td) / "venv" / "Scripts" / "whisper.exe"
            exe.parent.mkdir(parents=True)
            exe.write_bytes(b"MZ")
            empty_bin = Path(td) / "empty_bin"
            empty_bin.mkdir()
            with mock.patch.object(self.c, "BIN_DIR", empty_bin), \
                 mock.patch.object(self.c, "_is_managed_path", return_value=True), \
                 mock.patch.object(self.c, "_site_packages_of", return_value=sp), \
                 mock.patch.object(self.c.shutil, "which", return_value=str(exe)):
                r = self.c._probe_one("whisper")
        # 组件 bin 已隔离 → 「坏组件」场景必然成立，不该因开发机状态而 skip
        self.assertFalse(r["available"], "受控目录的坏组件必须报不可用")
        self.assertEqual(r["state"], "error")

    def test_site_packages_reverse_lookup_venv_layout(self):
        """venv 布局（<venv>\\Scripts\\exe）必须能反推出 site-packages。"""
        with tempfile.TemporaryDirectory() as td:
            sp = Path(td) / "venv" / "Lib" / "site-packages"
            sp.mkdir(parents=True)
            exe = Path(td) / "venv" / "Scripts" / "whisper.exe"
            exe.parent.mkdir(parents=True)
            exe.write_bytes(b"MZ")
            got = self.c._site_packages_of(str(exe))
        self.assertEqual(got, sp.resolve())

    def test_site_packages_reverse_lookup_system_layout(self):
        """系统布局（<Py>\\Lib\\site-packages\\Scripts\\exe）同样要能反推。"""
        with tempfile.TemporaryDirectory() as td:
            sp = Path(td) / "Lib" / "site-packages"
            (sp / "Scripts").mkdir(parents=True)
            exe = sp / "Scripts" / "yt-dlp.exe"
            exe.write_bytes(b"MZ")
            got = self.c._site_packages_of(str(exe))
        self.assertEqual(got, sp.resolve())

    def test_base_python_dirs_reads_pyvenv_cfg(self):
        """必须从 pyvenv.cfg 读出基础解释器目录（Python DLL 在那里）。"""
        with tempfile.TemporaryDirectory() as td:
            venv = Path(td) / "venv"
            sp = venv / "Lib" / "site-packages"
            sp.mkdir(parents=True)
            (venv / "pyvenv.cfg").write_text(
                "home = C:\\Python313\ninclude-system-site-packages = false\n",
                encoding="utf-8")
            dirs = self.c._base_python_dirs(sp)
        self.assertIn(Path(r"C:\Python313"), dirs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
