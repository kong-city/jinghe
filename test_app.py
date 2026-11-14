#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精核 v0.2.0「本地网页界面」的 API / 界面契约回归测试。

标准库 unittest，零第三方依赖（HTTP 客户端用 urllib，不引入 requests）。

设计约定：
  * 每个用例独立起停一个真实 `python app.py --no-browser --port 0` 子进程，
    tearDown 必 terminate + wait，绝不留下孤儿进程；用例之间不共享服务实例。
  * 端口用 `--port 0` 让内核分配，再从启动横幅
    `[INFO] 精核 UI: http://127.0.0.1:<port>/` 里读回真实端口——app.py 打印的是
    `httpd.server_address[1]`（协商结果），不是入参，所以不存在「先 bind 试探再
    抢占」的窗口（`app.py:1074-1078`）。
  * 所有产物只写 tempfile 目录，绝不碰项目的 out/；不动 samples/、extract.py、
    app.py、ui/。
  * 轮询一律有上限（本文件内 RUN_TIMEOUT），超时即 fail，绝不死等。
  * 断言只针对「前后端约定」：状态码、JSON 字段名与取值、事件序号/进度语义、
    目录清理等；不硬编码 HTML/CSS/JS 的具体文案，避免前端改样式就红。

覆盖的契约（逐条对应 app.py 实现）：
  1. 启动与 /api/state（字段齐全、running=false、未跑任务时 progress 为 idle 空集）
  2. 版本号与 `extract.py --version` 子进程实测一致（不硬编码版本字面量）
  3. 首页 / 与静态资源 /ui/app.css、/ui/app.js（外加不存在资源必须 404）
  4. 路径穿越四种变体（../、%2e%2e%2f、..%5c..%5c、....//）不得 200、不得返回源码
  5. dry-run 契约（total / 五桶 / items，且与磁盘样例数交叉校验）
  6. dry-run 错误形状（不存在路径、空输入）
  7. run + 进度轮询（summary 各计数、degraded 6 条不含音视频、md 实盘 12）
  8. 进度语义（单调不减、末值 1.0、[PROGRESS] 事件数 == 候选数、事件序号连续）
  9. since 增量语义（不重复旧事件、严格 > since 且连续）
 10. 并发保护（运行中再 run 必被拒）
 11. 取消（第一次 ok、state=cancelled、第二次 ok=false）
 12. 临时目录清理（正常完成 / 取消两条路径下 jinghe-run-* 与 jinghe-enc-* 均无残留）
 13. /api/open（不存在 → ok=false；存在 → ok=true，用打了补丁的启动器避免真弹窗）
 14. 中文路径（dry-run 与 run 全链路）
 15. `--cli` 自我重入（冻结版靠它跑提取，必须不启 HTTP、参数透传给 extract.py）
 16. 启动时的孤儿目录清扫：已死 pid 的 `jinghe-run-<pid>-<seq>` 被清、
     **存活进程的同类目录不得误删**、形状不符（`jinghe-run-notapid`）不得误伤，
     且 app.log 留痕「启动清理：移除 N 个」。清扫只在进程启动时发生，
     故该用例单独起子进程验证，不复用 setUp 的服务实例。

无法覆盖（原因见文件末尾注释）：真实 Edge `--app` 窗口、`--windowed` 的
MessageBoxW 兜底、/api/pick-folder 的原生文件夹对话框、以及「只监听 127.0.0.1」
的本机外部网卡连通性。

运行：
    python test_app.py                 # 逐项结果 + 末尾数字摘要
    python -m unittest -v test_app     # 只跑用例
"""
from __future__ import annotations

import gc
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = ROOT / "app.py"
EXTRACT = ROOT / "extract.py"
SAMPLES = ROOT / "samples"

# 启动横幅是拿端口的唯一权威来源（打印的是协商后的 server_address[1]）。
BANNER_RE = re.compile(r"\[INFO\]\s*精核 UI:\s*http://127\.0\.0\.1:(\d+)/")

# 与 samples/ 现状及 #9 / #10 交付形态绑定的契约数字。
# samples 一旦增删，这里会红——那是预期信号：先确认新基线，再同步本文件与 SPEC。
# test_06 会用磁盘实盘数交叉校验 EXPECT_TOTAL，防止常量与样例集悄悄脱节。
EXPECT_TOTAL = 19
EXPECT_BUCKETS = {"文本类": 6, "富文档": 12, "阶段3预留": 1, "需预处理": 0, "不支持": 0}
EXPECT_CANDIDATES = 18
EXPECT_SUCCESS = 12
EXPECT_FAILED = 6
EXPECT_DEFERRED = 1
EXPECT_PRODUCED = 12
EXPECT_DEGRADED = 6

# 测试专用启动器：把 os.startfile 换成空函数，验证 /api/open 的正向分支时不弹窗。
# 只在测试进程里生效，不修改 app.py 本身。
LAUNCHER_SOURCE = '''# -*- coding: utf-8 -*-
"""测试专用启动器：屏蔽 os.startfile 后启动 app.main，避免弹出资源管理器。"""
import os
import sys

sys.path.insert(0, sys.argv[1])
import app  # noqa: E402

os.startfile = lambda path: None  # 只在本测试子进程里生效
app._open_document = lambda p: "startfile"  # 禁止真弹记事本 / 切换窗口
app.webbrowser.open = lambda *a, **kw: True  # 一键更新测试不真弹浏览器
raise SystemExit(app.main(["--no-browser", "--port", "0"]))
'''

# 测试专用启动器：让 _build_summary 抛异常，验证任务线程 finally 必复位 running。
# 只在独立子进程里生效，不修改 app.py，也不污染测试进程的模块全局。
LAUNCHER_FAIL_SUMMARY_SOURCE = '''# -*- coding: utf-8 -*-
"""测试专用启动器：注入 _build_summary 异常，验证异常路径不残留 running。"""
import os
import sys

sys.path.insert(0, sys.argv[1])
import app  # noqa: E402

os.startfile = lambda path: None


def _boom(*args, **kwargs):
    raise RuntimeError("注入：_build_summary 异常")


app._build_summary = _boom
raise SystemExit(app.main(["--no-browser", "--port", "0"]))
'''


# --------------------------------------------------------------------------- #
# 临时目录探测：v0.2.0 修掉「取消后残留用户文档副本」的隐私泄漏，需回归保护
# --------------------------------------------------------------------------- #
def jinghe_temp_entries() -> set:
    """%TEMP% 下所有 jinghe-run-* 与 jinghe-enc-* 目录名。"""
    tmp = Path(tempfile.gettempdir())
    names: set = set()
    for pattern in ("jinghe-run-*", "jinghe-enc-*"):
        names |= {p.name for p in tmp.glob(pattern)}
    return names


def pid_run_dirs(pid: int) -> set:
    """指定进程创建过的编码副本目录（app.py: _new_enc_dir 的命名规则）。"""
    return {p.name for p in Path(tempfile.gettempdir()).glob("jinghe-run-%d-*" % pid)}


# --------------------------------------------------------------------------- #
# 被测服务：真实子进程 + 真实 HTTP
# --------------------------------------------------------------------------- #
class AppServer:
    """起一个真实 app.py 实例；所有交互走 HTTP，不 import app.py。"""

    def __init__(self, *, cwd=None, patch_open: bool = False, workdir=None,
                 env_extra: dict | None = None) -> None:
        self.cwd = str(cwd or ROOT)
        self.patch_open = patch_open
        self.workdir = Path(workdir) if workdir else None
        self.env_extra = {k: str(v) for k, v in (env_extra or {}).items()}
        self.proc: subprocess.Popen | None = None
        self.base = ""
        self.port = 0
        self.exit_code: int | None = None
        self._lines: list[str] = []
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._stopped = False

    # ---------------------------- 生命周期 ---------------------------- #
    def _argv(self) -> list[str]:
        if self.patch_open:
            assert self.workdir is not None, "patch_open 需要 workdir 落启动器"
            launcher = self.workdir / "launch_no_startfile.py"
            launcher.write_text(LAUNCHER_SOURCE, encoding="utf-8")
            return [sys.executable, "-u", str(launcher), str(ROOT)]
        return [sys.executable, "-u", str(APP), "--no-browser", "--port", "0"]

    def start(self, timeout: float = 60.0) -> "AppServer":
        self.proc = subprocess.Popen(
            self._argv(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",       # 控制台中文在 cp936 下会花屏，一律按 utf-8 读
            errors="replace",
            bufsize=1,
            cwd=self.cwd,
            env=dict(os.environ, **self.env_extra) if self.env_extra else None,
        )
        threading.Thread(target=self._pump, daemon=True).start()
        if not self._ready.wait(timeout):
            raise AssertionError(
                "app.py 在 %.0fs 内未打印启动横幅（rc=%s）\n输出：\n%s"
                % (timeout, self.proc.poll(), self.tail()))
        return self

    def _pump(self) -> None:
        assert self.proc is not None and self.proc.stdout is not None
        for raw in self.proc.stdout:
            line = raw.rstrip("\r\n")
            with self._lock:
                self._lines.append(line)
            if not self._ready.is_set():
                m = BANNER_RE.search(line)
                if m:
                    self.port = int(m.group(1))
                    self.base = "http://127.0.0.1:%d" % self.port
                    self._ready.set()

    def stop(self) -> None:
        if self._stopped or self.proc is None:
            return
        self._stopped = True
        pid = self.proc.pid
        if self.proc.poll() is None:
            # 先给任务线程的 finally 一点时间：TerminateProcess 不会执行 finally/atexit，
            # 若在「running 已置 false、_drop_enc_dir 还没跑完」的瞬间强杀，会把
            # jinghe-run-<pid>-* 留在 %TEMP%（这是测试台架的收尾顺序问题，不是被测契约；
            # 契约本身由 test_12 / test_13 在终止之前断言）。
            deadline = time.time() + 3.0
            while time.time() < deadline and pid_run_dirs(pid):
                time.sleep(0.05)
            self.proc.terminate()          # Windows 上是 TerminateProcess
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                try:
                    self.proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
        self.exit_code = self.proc.returncode
        # 兜底清理本进程目录，避免多次运行互相污染 baseline（断言已在终止前完成）
        for name in pid_run_dirs(pid):
            shutil.rmtree(Path(tempfile.gettempdir()) / name, ignore_errors=True)
        # 关掉读端，避免 ResourceWarning: unclosed file（读取线程此时已到 EOF）
        try:
            if self.proc.stdout is not None:
                self.proc.stdout.close()
        except Exception:
            pass

    # ---------------------------- 输出留痕 ---------------------------- #
    def tail(self, n: int = 25) -> str:
        with self._lock:
            return "\n".join(self._lines[-n:])

    def output(self) -> str:
        with self._lock:
            return "\n".join(self._lines)

    # ---------------------------- HTTP ---------------------------- #
    def request(self, method: str, path: str, *, data: bytes | None = None,
                timeout: float = 60.0) -> tuple[int, dict, bytes]:
        """返回 (status, headers, body)。4xx/5xx 作为正常返回值，不抛异常。"""
        last: Exception | None = None
        for _ in range(50):  # 横幅已打印，但 serve_forever 可能还差几微秒
            try:
                req = urllib.request.Request(self.base + path, data=data, method=method)
                if data is not None:
                    req.add_header("Content-Type", "application/json; charset=utf-8")
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return resp.getcode(), dict(resp.headers), resp.read()
            except urllib.error.HTTPError as exc:
                return exc.code, dict(exc.headers or {}), exc.read()
            except (urllib.error.URLError, ConnectionError, socket.timeout, OSError) as exc:
                last = exc
                time.sleep(0.1)
        raise AssertionError("请求 %s %s 失败：%s\n服务输出：\n%s"
                             % (method, path, last, self.tail()))

    def get(self, path: str, timeout: float = 60.0) -> tuple[int, dict, bytes]:
        return self.request("GET", path, timeout=timeout)

    def get_json(self, path: str, timeout: float = 60.0) -> tuple[int, dict]:
        status, _, body = self.get(path, timeout=timeout)
        return status, json.loads(body.decode("utf-8"))

    def post_json(self, path: str, payload: dict | None = None,
                  timeout: float = 180.0) -> tuple[int, dict]:
        data = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
        status, _, body = self.request("POST", path, data=data, timeout=timeout)
        return status, json.loads(body.decode("utf-8"))


# --------------------------------------------------------------------------- #
# 用例基类
# --------------------------------------------------------------------------- #
class AppContractTest(unittest.TestCase):
    START_TIMEOUT = 60.0
    RUN_TIMEOUT = 180.0
    POLL = 0.1

    def setUp(self) -> None:
        self._tmp_holder = tempfile.TemporaryDirectory(prefix="jinghe-qa-app-")
        self.tmp = Path(self._tmp_holder.name)
        self.srv: AppServer | None = None
        self.temp_baseline = jinghe_temp_entries()

    def tearDown(self) -> None:
        try:
            if self.srv is not None:
                self.srv.stop()
        finally:
            self._tmp_holder.cleanup()

    # ---------------------------- 辅助 ---------------------------- #
    def start(self, *, patch_open: bool = False,
              env_extra: dict | None = None) -> AppServer:
        self.srv = AppServer(patch_open=patch_open, workdir=self.tmp,
                             cwd=ROOT, env_extra=env_extra)
        self.srv.start(timeout=self.START_TIMEOUT)
        return self.srv

    def start_job(self, input_arg: str, outdir: Path) -> dict:
        assert self.srv is not None
        status, obj = self.srv.post_json(
            "/api/run", {"input": input_arg, "outdir": str(outdir)})
        self.assertEqual(status, 200, "POST /api/run HTTP %s：%s" % (status, obj))
        self.assertTrue(obj.get("ok"), "POST /api/run 未被接受：%s" % obj)
        return obj

    def collect(self, timeout: float | None = None) -> tuple[dict, list]:
        """轮询 /api/progress 直到 running=false，返回 (最后一次响应, 全量事件)。"""
        assert self.srv is not None
        limit = self.RUN_TIMEOUT if timeout is None else timeout
        deadline = time.time() + limit
        events: list = []
        since = 0
        while True:
            status, d = self.srv.get_json("/api/progress?since=%d" % since)
            self.assertEqual(status, 200, "GET /api/progress HTTP %s" % status)
            events.extend(d["events"])
            since = d["next"]
            if not d["running"]:
                return d, events
            if time.time() > deadline:
                self.fail("轮询 /api/progress 超时（%.0fs），已收 %d 个事件仍 running\n%s"
                          % (limit, len(events), self.srv.tail()))
            time.sleep(self.POLL)

    def run_to_end(self, input_arg: str, outdir: Path,
                   timeout: float | None = None) -> tuple[dict, list]:
        self.start_job(input_arg, outdir)
        return self.collect(timeout)

    def assert_temp_clean(self, pid: int) -> None:
        """临时目录清理契约（v0.2.0 修的隐私泄漏，必须有回归保护）。

        判据分两层：
          1. 本服务的 jinghe-run-<pid>-* 必须归零——目录名带创建者 pid，可归因，
             是最硬的一条。running=false 先于 finally 的 _drop_enc_dir 落地，
             故用短等而非立刻断言。
          2. 全局不得新增 jinghe-enc-*（前置层自建目录＝app 没传 JINGHE_ENCDIR，
             属真泄漏）；他人进程的 jinghe-run-<别的 pid>-* 不算我的账。
        """
        assert self.srv is not None
        ok = self.wait_for(lambda: not pid_run_dirs(pid), 10.0)
        self.assertTrue(ok, "任务结束后 jinghe-run-%d-* 仍残留：%s"
                            "（编码副本目录未清理，用户文档副本泄漏在 %%TEMP%%）"
                            % (pid, sorted(pid_run_dirs(pid))))
        deadline = time.time() + 2.0  # 沉降窗：等他人并发进程的瞬态目录自然消失
        while time.time() < deadline:
            if not (jinghe_temp_entries() - self.temp_baseline):
                return
            time.sleep(0.1)
        new = jinghe_temp_entries() - self.temp_baseline
        foreign = {n for n in new
                   if n.startswith("jinghe-run-") and n.split("-")[2] != str(pid)}
        suspicious = new - foreign
        self.assertEqual(suspicious, set(),
                         "任务结束后 %%TEMP%% 新增残留：%s（忽略他人并发的 %s）"
                         % (sorted(suspicious), sorted(foreign)))

    @staticmethod
    def wait_for(predicate, timeout: float) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return True
            time.sleep(0.05)
        return predicate()

    @staticmethod
    def expected_degraded() -> set:
        """samples 里应计入「降级」的 6 个：5 个真加密 + 1 个无效容器。"""
        return {p.name for p in SAMPLES.iterdir()
                if p.is_file() and (p.name.startswith("locked") or p.name == "broken.docx")}

    @staticmethod
    def cli_version() -> str:
        r = subprocess.run([sys.executable, str(EXTRACT), "--version"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=120, cwd=str(ROOT))
        assert r.returncode == 0, "extract.py --version 失败：%s" % r.stderr
        return (r.stdout or "").strip().splitlines()[0].strip()

    # ------------------------------------------------------------------ #
    # 1) 启动 + /api/state + 未跑任务的 progress + 错误响应形状
    # ------------------------------------------------------------------ #
    def test_01_state_and_idle_progress(self):
        srv = self.start()
        status, state = srv.get_json("/api/state")
        self.assertEqual(status, 200, "/api/state 未返回 200")
        for key in ("version", "python", "running", "input", "outdir",
                    "converter", "cwd"):
            self.assertIn(key, state, "state 缺少字段 %s（前端按名取值）" % key)
        self.assertIs(state["running"], False, "刚启动时 running 应为 false")
        self.assertTrue(srv.base.startswith("http://127.0.0.1:"),
                        "服务应只监听回环地址，实际 %s" % srv.base)

        # 从未跑过任务：progress 必须是 idle 空集，否则前端会误显示上一次的进度
        status, d = srv.get_json("/api/progress?since=0")
        self.assertEqual(status, 200)
        self.assertEqual(d["events"], [], "空状态不应有事件")
        self.assertEqual(d["state"], "idle", "空状态 state 应为 idle")
        self.assertIs(d["running"], False)
        self.assertIsNone(d["summary"], "空状态不应带 summary")
        self.assertEqual(d["next"], 0)

        # 未知接口 → 404 + ok=false；坏 JSON → 400 + ok=false
        status, obj = srv.post_json("/api/no-such-api", {})
        self.assertEqual(status, 404, "未知接口应 404")
        self.assertIs(obj.get("ok"), False, "未知接口响应缺 ok=false")
        self.assertTrue(obj.get("error"), "未知接口响应缺 error 文案")

        # 同一契约的 GET 半边（SPEC §8.3：未知 /api/* → 404 {ok:false,error}）。
        # 关键在「响应体能解析成 JSON」——只断言状态码的话，纯文本 404 也会过，
        # 这正是这条缺口此前漏网的原因（do_GET 兜底曾直接 _send_text）。
        status, headers, body = srv.get("/api/no-such-api")
        self.assertEqual(status, 404, "GET 未知接口应 404，实得 %s" % status)
        try:
            get_obj = json.loads(body.decode("utf-8"))
        except ValueError as exc:
            self.fail("GET 未知接口响应不是合法 JSON（%s）：%r"
                      % (exc, body[:200]))
        self.assertIsInstance(get_obj, dict, "GET 未知接口应返回 JSON 对象")
        self.assertIs(get_obj.get("ok"), False, "GET 未知接口响应缺 ok=false")
        self.assertTrue(get_obj.get("error"), "GET 未知接口响应缺 error 文案")
        self.assertIn("application/json", headers.get("Content-Type", "").lower(),
                      "GET 未知接口的 Content-Type 不是 JSON：%s"
                      "（前端按 Content-Type 分流，纯文本会被当页面）"
                      % headers.get("Content-Type"))

        status, _, body = srv.request("POST", "/api/dry-run", data=b"{not-json")
        self.assertEqual(status, 400, "坏 JSON 应 400，实得 %s" % status)
        obj = json.loads(body.decode("utf-8"))
        self.assertIs(obj.get("ok"), False)
        self.assertTrue(obj.get("error"))

    # ------------------------------------------------------------------ #
    # 2) 版本号：与 extract.py --version 子进程实测一致
    # ------------------------------------------------------------------ #
    def test_02_version_matches_extract_cli(self):
        srv = self.start()
        _, state = srv.get_json("/api/state")
        want = self.cli_version()
        self.assertTrue(want, "extract.py --version 无输出，无法比对")
        self.assertNotEqual(state["version"], "unknown",
                            "能力探测失败：UI 拿不到 extract.py 版本")
        self.assertEqual(state["version"], want,
                         "UI 显示的版本 %r 与 extract.py --version %r 不一致"
                         "（界面会骗人）" % (state["version"], want))
        self.assertRegex(state["version"], r"^\d+\.\d+\.\d+")
        self.assertEqual(state["python"], platform.python_version(),
                         "state.python 不是真实解释器版本")

    # ------------------------------------------------------------------ #
    # 3) 首页
    # ------------------------------------------------------------------ #
    def test_03_index_html(self):
        srv = self.start()
        status, headers, body = srv.get("/")
        self.assertEqual(status, 200, "首页未返回 200")
        self.assertIn("text/html", headers.get("Content-Type", "").lower(),
                      "首页 Content-Type 不是 text/html：%s" % headers.get("Content-Type"))
        html = body.decode("utf-8")
        self.assertTrue("<!DOCTYPE html" in html or "<html" in html,
                        "首页不是 HTML 文档")
        self.assertGreater(len(body), 500, "首页疑似空壳（%d 字节）" % len(body))
        # 首页必须引用两个静态资源，否则「样式/脚本丢了」在浏览器里才暴露
        self.assertIn("/ui/app.css", html, "首页未引用 app.css")
        self.assertIn("/ui/app.js", html, "首页未引用 app.js")

    # ------------------------------------------------------------------ #
    # 4) 静态资源
    # ------------------------------------------------------------------ #
    def test_04_static_assets(self):
        srv = self.start()
        for path, frag in (("/ui/app.css", "text/css"),
                           ("/ui/app.js", "javascript")):
            status, headers, body = srv.get(path)
            self.assertEqual(status, 200, "%s 未返回 200" % path)
            self.assertIn(frag, headers.get("Content-Type", "").lower(),
                          "%s Content-Type 不符：%s"
                          % (path, headers.get("Content-Type")))
            self.assertGreater(len(body), 200, "%s 内容过短" % path)
        # 不存在的静态资源必须 404，不能回落到首页（否则前端缓存会串味）。
        # 这里刻意只断言状态码、不要求 JSON：静态资源缺失走的是 do_GET 末尾的
        # 文本兜底，与 /api/* 的 JSON 错误体是两条不同契约；要求成 JSON 反而会把
        # 合法实现逼成错误形状。
        status, _, _ = srv.get("/ui/no-such-asset.css")
        self.assertEqual(status, 404, "缺失静态资源应 404，实得 %s" % status)

    # ------------------------------------------------------------------ #
    # 5) 路径穿越：四变体均不得 200，且不得返回源码
    # ------------------------------------------------------------------ #
    def test_05_path_traversal_blocked(self):
        srv = self.start()
        variants = [
            "/ui/../extract.py",
            "/ui/%2e%2e%2fextract.py",
            "/ui/..%5c..%5cextract.py",
            "/ui/....//extract.py",
        ]
        for path in variants:
            status, _, body = srv.get(path)
            self.assertNotEqual(status, 200, "路径穿越未被拦截：%s 返回 200（%d 字节）"
                                % (path, len(body)))
            self.assertIn(status, (400, 403, 404),
                          "%s 返回了意外状态码 %s" % (path, status))
            text = body.decode("utf-8", "replace")
            for marker in ("argparse", "import argparse", "def main("):
                self.assertNotIn(marker, text,
                                 "%s 响应体泄漏了源码特征 %r" % (path, marker))

    # ------------------------------------------------------------------ #
    # 6) dry-run 契约
    # ------------------------------------------------------------------ #
    def test_06_dry_run_contract(self):
        srv = self.start()
        status, d = srv.post_json("/api/dry-run", {"input": "samples"})
        self.assertEqual(status, 200, "dry-run HTTP %s" % status)
        self.assertIs(d.get("ok"), True, "dry-run 失败：%s" % d.get("error"))
        self.assertEqual(d["total"], EXPECT_TOTAL, "dry-run.total 不符")
        self.assertEqual(d["buckets"], EXPECT_BUCKETS, "dry-run.buckets 不符")
        self.assertEqual(len(d["items"]), EXPECT_TOTAL, "items 条数应等于 total")
        # 自洽性：总数 == 五桶之和；候选 == 文本类 + 富文档
        self.assertEqual(d["total"], sum(d["buckets"].values()),
                         "total 与 buckets 之和不一致")
        self.assertEqual(EXPECT_CANDIDATES,
                         d["buckets"]["文本类"] + d["buckets"]["富文档"],
                         "候选数 != 文本类 + 富文档")
        # items 的 kind 分布必须与 buckets 对得上（前端拿 items 渲染清单）
        kinds: dict = {key: 0 for key in EXPECT_BUCKETS}  # 预置零桶，缺项也要比对
        names: list = []
        for item in d["items"]:
            self.assertIn("name", item, "items 元素缺 name")
            self.assertIn("kind", item, "items 元素缺 kind")
            self.assertIn(item["kind"], EXPECT_BUCKETS,
                          "items 出现未知分类 %r" % item["kind"])
            kinds[item["kind"]] += 1
            names.append(item["name"])
        self.assertEqual(kinds, EXPECT_BUCKETS, "items 的 kind 分布与 buckets 不一致")
        self.assertEqual(len(set(names)), len(names), "items 出现重名")
        # 常量必须与磁盘实盘数一致，防止样例集改了而常量悄悄过期
        on_disk = len([p for p in SAMPLES.iterdir() if p.is_file()])
        self.assertEqual(EXPECT_TOTAL, on_disk,
                         "契约常量 %d 与 samples/ 实盘 %d 脱节" % (EXPECT_TOTAL, on_disk))

    # ------------------------------------------------------------------ #
    # 7) dry-run 错误分支
    # ------------------------------------------------------------------ #
    def test_07_dry_run_errors(self):
        srv = self.start()
        status, d = srv.post_json("/api/dry-run", {"input": "no/such/dir"})
        self.assertEqual(status, 200, "业务错误应仍返回 HTTP 200 + ok=false")
        self.assertIs(d.get("ok"), False, "不存在的输入路径竟返回 ok=true")
        self.assertTrue((d.get("error") or "").strip(), "缺 error 文案")
        self.assertIn("不存在", d["error"], "错误文案未说明路径不存在：%s" % d["error"])

        status, d = srv.post_json("/api/dry-run", {"input": "   "})
        self.assertIs(d.get("ok"), False, "空输入应失败")
        self.assertIn("输入", d.get("error") or "", "空输入错误文案不符：%s" % d.get("error"))

    # ------------------------------------------------------------------ #
    # 8) run + 进度轮询 + summary
    # ------------------------------------------------------------------ #
    def test_08_run_summary_and_progress(self):
        srv = self.start()
        outdir = self.tmp / "out-run"
        d, events = self.run_to_end("samples", outdir)

        self.assertEqual(d["state"], "done",
                         "任务未正常结束：state=%s error=%s" % (d["state"], d["error"]))
        self.assertIs(d["running"], False)
        self.assertIsNone(d["error"], "正常任务却带 error：%s" % d["error"])
        summary = d["summary"]
        self.assertIsNotNone(summary, "任务结束却没有 summary")

        for key, want in (("success", EXPECT_SUCCESS), ("failed", EXPECT_FAILED),
                          ("candidates", EXPECT_CANDIDATES),
                          ("deferred", EXPECT_DEFERRED),
                          ("produced", EXPECT_PRODUCED)):
            self.assertEqual(summary[key], want,
                             "summary.%s 期望 %s 实得 %s" % (key, want, summary[key]))
        self.assertEqual(summary["success"] + summary["failed"], summary["candidates"],
                         "成功 + 失败 != 候选（前端对账会不闭合）")

        degraded = summary["degraded"]
        self.assertEqual(len(degraded), EXPECT_DEGRADED,
                         "degraded 应为 %d 条，实得 %d 条" % (EXPECT_DEGRADED, len(degraded)))
        names = {g["name"] for g in degraded}
        self.assertEqual(names, self.expected_degraded(),
                         "降级清单不符：多 %s / 少 %s"
                         % (sorted(names - self.expected_degraded()),
                            sorted(self.expected_degraded() - names)))
        self.assertFalse(any("future-audio" in n for n in names),
                        "future-audio.mp3 是「阶段 3 预留」，不是降级，不应出现在 degraded")
        for g in degraded:
            self.assertTrue((g.get("status") or "").strip(), "降级项缺 status：%s" % g)
            self.assertTrue((g.get("note") or "").strip(),
                            "降级项缺 note（前端要展示原因）：%s" % g)
        self.assertIn("部分未完成", summary["verdict"],
                      "验收结论应与 INDEX 一致（部分未完成）：%r" % summary["verdict"])

        # md 实盘：summary 给的 outdir 与调用方给的 outdir 都必须是 12
        md_from_summary = Path(summary["outdir"]) / "md"
        self.assertEqual(len(list(md_from_summary.glob("*.md"))), EXPECT_PRODUCED,
                         "summary.outdir 下 md 数与 produced 不符")
        self.assertEqual(len(list((outdir / "md").glob("*.md"))), EXPECT_PRODUCED,
                         "调用方 outdir 下 md 数不符")

        # 进度事件语义
        progress_events = [e for e in events if e.get("type") == "progress"]
        self.assertEqual(len(progress_events), summary["candidates"],
                         "[PROGRESS] 事件数应等于候选数 %d，实得 %d"
                         % (summary["candidates"], len(progress_events)))
        values = [e["progress"] for e in progress_events]
        self.assertEqual(values, sorted(values), "progress 非单调不减：%s" % values[:20])
        self.assertAlmostEqual(values[-1], 1.0, places=6,
                               msg="末个 progress 应为 1.0，实得 %r" % values[-1])
        for ev in progress_events:
            self.assertIn("current", ev, "progress 事件缺 current")
            self.assertIn("total", ev, "progress 事件缺 total")
            self.assertLessEqual(ev["current"], ev["total"], "current > total")

        index_seq = [e["i"] for e in events]
        self.assertEqual(index_seq, list(range(1, len(events) + 1)),
                         "事件序号必须从 1 连续递增（前端按 i 去重/续拉）")
        for ev in events:
            self.assertTrue((ev.get("text") or "").strip(),
                            "事件缺 text，前端无法显示：%s" % ev)

    # ------------------------------------------------------------------ #
    # 9) since 增量语义
    # ------------------------------------------------------------------ #
    def test_09_progress_since_semantics(self):
        srv = self.start()
        indir = self.tmp / "input-since"
        indir.mkdir()
        (indir / "a.txt").write_text("# A\n\n正文 A\n", encoding="utf-8")
        (indir / "b.txt").write_text("# B\n\n正文 B\n", encoding="utf-8")
        outdir = self.tmp / "out-since"
        d, _ = self.run_to_end(str(indir), outdir, timeout=120)
        self.assertEqual(d["state"], "done", "小样例任务未完成：%s" % d["error"])

        status, full = srv.get_json("/api/progress?since=0")
        total = len(full["events"])
        self.assertGreaterEqual(total, 3, "事件太少（%d），无法验证增量语义" % total)
        self.assertEqual(full["next"], total,
                         "全量拉取后 next 应指向最后一个事件序号，实得 %s" % full["next"])

        # 用 next 再拉：不得重放旧事件
        status, again = srv.get_json("/api/progress?since=%d" % full["next"])
        self.assertEqual(again["events"], [],
                         "since=next 仍返回旧事件，前端会重复追加")
        self.assertEqual(again["next"], full["next"], "空增量不应推进 next")

        # 任意中间 since：严格 > since 且序号连续
        for since in (1, total // 2, total - 1):
            if since < 1 or since >= total:
                continue
            status, part = srv.get_json("/api/progress?since=%d" % since)
            self.assertTrue(part["events"], "since=%d 应返回剩余事件" % since)
            self.assertEqual([e["i"] for e in part["events"]],
                             list(range(since + 1, total + 1)),
                             "since 语义错误：应严格 > since 且连续")

    # ------------------------------------------------------------------ #
    # 10) 并发保护
    # ------------------------------------------------------------------ #
    def test_10_concurrent_run_rejected(self):
        srv = self.start()
        outdir = self.tmp / "out-concurrent"
        self.start_job("samples", outdir)
        status, obj = srv.post_json(
            "/api/run", {"input": "samples", "outdir": str(outdir)})
        self.assertEqual(status, 200)
        self.assertIs(obj.get("ok"), False,
                      "任务运行中第二次 /api/run 竟被接受（会双写同一 outdir）")
        self.assertIn("已有任务在运行", obj.get("error") or "",
                      "并发保护错误文案不符：%s" % obj.get("error"))
        d, _ = self.collect()
        self.assertEqual(d["state"], "done", "首个任务应正常完成")

    # ------------------------------------------------------------------ #
    # 11) 取消
    # ------------------------------------------------------------------ #
    def test_11_cancel_then_cancel_again(self):
        srv = self.start()
        outdir = self.tmp / "out-cancel"
        self.start_job("samples", outdir)
        status, obj = srv.post_json("/api/cancel", {})
        self.assertIs(obj.get("ok"), True,
                      "取消未被接受：%s（若任务已结束，说明 samples 跑得太快，"
                      "本用例需换更大输入）" % obj)
        ok = self.wait_for(
            lambda: srv.get_json("/api/state")[1]["running"] is False, 120.0)
        self.assertTrue(ok, "取消后 120s 仍 running=true\n%s" % srv.tail())

        status, obj2 = srv.post_json("/api/cancel", {})
        self.assertIs(obj2.get("ok"), False, "无任务时再取消应失败")
        self.assertIn("无运行中任务", obj2.get("error") or "",
                      "重复取消错误文案不符：%s" % obj2.get("error"))

        _, d = srv.get_json("/api/progress?since=0")
        self.assertEqual(d["state"], "cancelled",
                         "取消后 state 应为 cancelled，实得 %s" % d["state"])

    # ------------------------------------------------------------------ #
    # 12) 临时目录清理（正常完成）
    # ------------------------------------------------------------------ #
    def test_12_temp_dirs_cleaned_after_run(self):
        srv = self.start()
        pid = srv.proc.pid
        outdir = self.tmp / "out-clean"
        d, _ = self.run_to_end("samples", outdir)
        self.assertEqual(d["state"], "done")
        self.assert_temp_clean(pid)

    # ------------------------------------------------------------------ #
    # 13) 临时目录清理（取消强杀路径——atexit 不执行，最易泄漏）
    # ------------------------------------------------------------------ #
    def test_13_temp_dirs_cleaned_after_cancel(self):
        srv = self.start()
        pid = srv.proc.pid
        outdir = self.tmp / "out-clean-cancel"
        self.start_job("samples", outdir)
        status, obj = srv.post_json("/api/cancel", {})
        self.assertIs(obj.get("ok"), True, "取消未被接受：%s" % obj)
        ok = self.wait_for(
            lambda: srv.get_json("/api/state")[1]["running"] is False, 120.0)
        self.assertTrue(ok, "取消后仍 running=true")
        self.assert_temp_clean(pid)

    # ------------------------------------------------------------------ #
    # 14) /api/open（用打补丁的启动器，避免真弹窗）
    # ------------------------------------------------------------------ #
    def test_14_open_api(self):
        srv = self.start(patch_open=True)
        status, obj = srv.post_json("/api/open", {"path": str(self.tmp / "no-such-path")})
        self.assertEqual(status, 200)
        self.assertIs(obj.get("ok"), False, "不存在的路径竟返回 ok=true")
        self.assertIn("不存在", obj.get("error") or "",
                      "错误文案未说明路径不存在：%s" % obj.get("error"))

        status, obj = srv.post_json("/api/open", {"path": ""})
        self.assertIs(obj.get("ok"), False, "空路径应失败")
        self.assertTrue(obj.get("error"), "空路径缺 error 文案")

        # 本子进程内 os.startfile 已被替换为空函数，下面的 ok=true 不会弹出窗口
        target = self.tmp / "存在 的文件.txt"
        target.write_text("x", encoding="utf-8")
        status, obj = srv.post_json("/api/open", {"path": str(target)})
        self.assertIs(obj.get("ok"), True, "已存在的文件应可打开：%s" % obj)

        status, obj = srv.post_json("/api/open", {"path": str(self.tmp)})
        self.assertIs(obj.get("ok"), True, "已存在的目录应可打开：%s" % obj)

    # ------------------------------------------------------------------ #
    # 15) 中文路径
    # ------------------------------------------------------------------ #
    def test_15_chinese_path(self):
        srv = self.start()
        indir = self.tmp / "中文 样本"
        indir.mkdir()
        (indir / "第一篇 笔记.txt").write_text("# 第一章 标题\n\n中文正文一\n",
                                             encoding="utf-8")
        (indir / "第二篇 笔记.txt").write_text("# 第二章 标题\n\n中文正文二\n",
                                             encoding="utf-8")

        status, d = srv.post_json("/api/dry-run", {"input": str(indir)})
        self.assertIs(d.get("ok"), True, "中文路径 dry-run 失败：%s" % d.get("error"))
        self.assertEqual(d["total"], 2, "中文路径 dry-run total 不符")
        self.assertEqual(d["buckets"]["文本类"], 2, "中文路径分类不符")
        self.assertEqual(len(d["items"]), 2)

        outdir = self.tmp / "中文 产物"
        d2, _ = self.run_to_end(str(indir), outdir)
        self.assertEqual(d2["state"], "done", "中文路径任务未完成：%s" % d2["error"])
        self.assertEqual(d2["summary"]["success"], 2, "中文路径成功数不符")
        md_files = sorted((outdir / "md").glob("*.md"))
        self.assertEqual(len(md_files), 2, "中文路径产物数不符")
        body = md_files[0].read_text(encoding="utf-8")
        self.assertIn("中文正文", body, "中文正文丢失")
        self.assertIn("<!-- src: doc_", body, "中文路径产物缺出处注释")

    # ------------------------------------------------------------------ #
    # 16) --cli 自我重入（冻结版靠它跑提取）
    # ------------------------------------------------------------------ #
    def test_16_cli_reentry(self):
        r = subprocess.run([sys.executable, "-u", str(APP), "--cli", "--version"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=120, cwd=str(ROOT))
        self.assertEqual(r.returncode, 0, "--cli --version rc=%s\n%s"
                         % (r.returncode, r.stderr))
        self.assertEqual((r.stdout or "").strip(), self.cli_version(),
                         "--cli 未把参数透传给 extract.py：%r" % r.stdout)
        self.assertNotIn("精核 UI:", r.stdout,
                         "--cli 不得启动 HTTP 服务（父进程会一直等它退出）")

    # ------------------------------------------------------------------ #
    # 17) 启动时的孤儿目录清扫（硬杀遗留；§8.6 所有权与生命周期对齐）
    # ------------------------------------------------------------------ #
    def test_17_orphan_sweep(self):
        """清扫只发生在进程启动那一刻，所以必须新起一个子进程来验。

        三条断言缺一不可：
          ① 已死 pid 的 jinghe-run-<pid>-1 被清掉（缺口本身）
          ② 真实存活进程的同类目录完好（**安全边界**：只测 ① 等于没测）
          ③ 形状不符的 jinghe-run-notapid 不被误伤（正则必须是精确形状）
        """
        temp_root = Path(tempfile.gettempdir())
        # 造一个「已死 pid」：起一个立刻退出的进程，回收后该 pid 即不存在。
        # ⚠ 必须释放 Popen 持有的进程句柄：Windows 上只要有句柄没关，进程对象就还在，
        #   OpenProcess 仍能成功 → 清扫会（正确地）判「活着」→ 用例会假失败。
        #   这不是实现缺陷，是本用例的观测前提。
        corpse = subprocess.Popen([sys.executable, "-c", "pass"])
        corpse.wait(timeout=120)
        dead_pid = corpse.pid
        corpse.__exit__(None, None, None)
        del corpse
        gc.collect()
        # 造一个「真实存活」的子进程，用例结束必须 kill，否则会污染后续用例
        live = subprocess.Popen([sys.executable, "-c",
                                 "import time; time.sleep(300)"])

        def _stop_live() -> None:
            try:
                if live.poll() is None:
                    live.kill()
                live.wait(timeout=60)
            except Exception:
                pass

        self.addCleanup(_stop_live)

        dead_dir = temp_root / ("jinghe-run-%d-1" % dead_pid)
        live_dir = temp_root / ("jinghe-run-%d-1" % live.pid)
        weird_dir = temp_root / "jinghe-run-notapid"  # 形状不符：清扫永不碰
        for path in (dead_dir, live_dir, weird_dir):
            path.mkdir(parents=True, exist_ok=True)
            (path / "marker.txt").write_text("marker", encoding="utf-8")
        # 三个目录都得由本用例收尾（weird_dir 清扫逻辑永远不会清，必须自己删）
        self.addCleanup(lambda: [shutil.rmtree(p, ignore_errors=True)
                                 for p in (dead_dir, live_dir, weird_dir)])

        # 把 LOCALAPPDATA 指到临时目录，隔离 app.log，不污染用户真实日志
        appdata = self.tmp / "localappdata"
        appdata.mkdir()
        srv = self.start(env_extra={"LOCALAPPDATA": str(appdata)})
        status, _ = srv.get_json("/api/state")   # 轮询就绪（横幅之后还差几微秒）
        self.assertEqual(status, 200, "/api/state 未就绪，无法判定清扫已执行")

        # ① 死进程的目录被清
        self.assertFalse(dead_dir.exists(),
                         "已退出进程(pid=%d)遗留的 %s 未被清扫——硬杀场景的副本"
                         "会永久留在 %%TEMP%%" % (dead_pid, dead_dir.name))
        # ② 活进程的目录完好（安全边界）
        self.assertTrue(live_dir.is_dir(),
                        "存活进程(pid=%d)的编码副本目录被误删——会打断正在跑的任务"
                        % live.pid)
        self.assertTrue((live_dir / "marker.txt").is_file(),
                        "存活进程目录里的内容被误删")
        # ③ 形状不符的目录绝不误伤
        self.assertTrue(weird_dir.is_dir(),
                        "形状不符的 jinghe-run-notapid 被误伤（清扫应按精确形状匹配）")

        # ④ 留痕：不断言精确数量（%TEMP% 里可能有别人的孤儿被一并清掉）
        log = appdata / "Jinghe" / "app.log"
        self.assertTrue(log.is_file(), "app.log 未生成：%s" % log)
        logged = log.read_text(encoding="utf-8")
        self.assertIn("启动清理：移除 ", logged, "app.log 未记录孤儿清扫")
        m = re.search(r"启动清理：移除 (\d+) 个", logged)
        self.assertIsNotNone(m, "启动清理行没有数量：%r" % logged[-300:])
        self.assertGreaterEqual(int(m.group(1)), 1,
                                "清理数量 %s 至少应含本用例造的那 1 个" % m.group(1))

    def test_18_pick_files_win32_contract(self):
        """多选文件对话框（GetOpenFileNameW）契约，全程不弹窗。

        锁住这次整改的关键不变量：
          ① 不再走 COM vtable —— pick_files_ex 不应触碰 _com_method；
          ② OPENFILENAMEW 结构体尺寸必须等于 Win32 ABI（x64=152 / x86=88），
             尺寸错位会让 GetOpenFileNameW 直接失败；
          ③ 必须开启多选 + Explorer 风格 + 不改进程 CWD（CWD 被改会破坏
             服务端相对路径）；
          ④ 过滤器必须覆盖常见格式并有「所有文件」兜底；
          ⑤ 多选缓冲切分与路径还原；
          ⑥ 取消 → ([], None)；异常 → ([], 错误说明)。
        """
        try:
            import app as jinghe_app
        except Exception as exc:  # noqa: BLE001
            self.skipTest("无法导入 app 模块：%s" % exc)
        import ctypes as ct

        # ② Win32 ABI 尺寸
        expect_size = 152 if ct.sizeof(ct.c_void_p) == 8 else 88
        self.assertEqual(ct.sizeof(jinghe_app._OPENFILENAMEW), expect_size,
                         "OPENFILENAMEW 结构体尺寸错位，GetOpenFileNameW 会失败")

        # ③ 关键选项位
        flags = jinghe_app._OFN_FLAGS
        self.assertTrue(flags & jinghe_app._OFN_ALLOWMULTISELECT,
                        "缺少 OFN_ALLOWMULTISELECT：对话框不能多选")
        self.assertTrue(flags & jinghe_app._OFN_EXPLORER,
                        "缺少 OFN_EXPLORER：多选缓冲格式不成立")
        self.assertTrue(flags & jinghe_app._OFN_NOCHANGEDIR,
                        "缺少 OFN_NOCHANGEDIR：会改变服务进程工作目录")

        # ④ 过滤器：常见格式 + 兜底 + 双 NUL 结束
        filt = jinghe_app._ofn_filter_string()
        for ext in ("*.pdf", "*.docx", "*.xlsx", "*.pptx", "*.txt", "*.md", "*.*"):
            self.assertIn(ext, filt, "过滤器缺少 %s" % ext)
        self.assertTrue(filt.endswith("\0\0"), "过滤器表必须以双 NUL 结束")

        # ⑤ 多选缓冲切分：dir\0f1\0f2\0\0
        buf = ct.create_unicode_buffer("C:\\a\0one.pdf\0two.docx\0\0")
        self.assertEqual(["C:\\a", "one.pdf", "two.docx"],
                         jinghe_app._split_ofn_buffer(buf, len(buf)))
        self.assertEqual([], jinghe_app._parse_ofn_paths([]))
        self.assertEqual(["C:\\a\\one.pdf"],
                         jinghe_app._parse_ofn_paths(["C:\\a\\one.pdf"]))
        self.assertEqual(["C:\\a\\one.pdf", "C:\\a\\two.docx"],
                         jinghe_app._parse_ofn_paths(
                             ["C:\\a", "one.pdf", "two.docx"]))

        # ① + ⑥ 不碰 COM vtable；取消 / 失败语义
        orig_com = jinghe_app._com_method
        orig_win32 = jinghe_app._pick_files_win32

        def boom_com(*a, **k):
            raise AssertionError("pick_files_ex 不该再调用 COM vtable")

        try:
            jinghe_app._com_method = boom_com
            jinghe_app._pick_files_win32 = lambda initial: []
            paths, err = jinghe_app.pick_files_ex("")
            self.assertEqual([], paths, "取消应返回空列表")
            self.assertIsNone(err, "取消不是失败，error 必须为 None")

            def fail(initial):
                raise OSError("模拟失败")

            jinghe_app._pick_files_win32 = fail
            paths, err = jinghe_app.pick_files_ex("")
            self.assertEqual([], paths)
            self.assertIn("打开文件选择框失败", err or "")
        finally:
            jinghe_app._com_method = orig_com
            jinghe_app._pick_files_win32 = orig_win32

    # ------------------------------------------------------------------ #
    # 19) dry-run 返回契约（补：字段名 / 五桶键名 / items 结构稳定）
    # ------------------------------------------------------------------ #
    def test_19_dry_run_response_contract(self):
        srv = self.start()
        indir = self.tmp / "input-dry-contract"
        indir.mkdir()
        (indir / "a.txt").write_text("# A\n\n正文 A\n", encoding="utf-8")
        (indir / "b.md").write_text("# B\n\n正文 B\n", encoding="utf-8")
        cases = (
            ("单文件", {"input": str(indir / "a.txt")}),
            ("小目录", {"input": str(indir)}),
            ("样例集", {"input": "samples"}),
        )
        # 五桶键名以 app.py:_dry_run 的初始化为准，固定且不得多/少
        want_buckets = {"文本类", "富文档", "阶段3预留", "需预处理", "不支持"}
        for name, payload in cases:
            with self.subTest(case=name):
                status, d = srv.post_json("/api/dry-run", payload)
                self.assertEqual(status, 200, "%s dry-run HTTP %s" % (name, status))
                self.assertIs(d.get("ok"), True,
                              "%s dry-run 失败：%s" % (name, d.get("error")))
                for key in ("ok", "total", "buckets", "items"):
                    self.assertIn(key, d, "%s dry-run 响应缺字段 %s" % (name, key))
                self.assertEqual(set(d["buckets"]), want_buckets,
                                 "%s 五桶键名不符：%s" % (name, sorted(d["buckets"])))
                self.assertIsInstance(d["total"], int, "%s total 应为整数" % name)
                self.assertIsInstance(d["items"], list, "%s items 应为数组" % name)
                for item in d["items"]:
                    self.assertIsInstance(item, dict, "%s items 元素应为对象" % name)
                    self.assertIn("name", item, "%s items 元素缺 name" % name)
                    self.assertIn("kind", item, "%s items 元素缺 kind" % name)
                    self.assertIn(item["kind"], want_buckets,
                                  "%s items 出现未知分类 %r" % (name, item["kind"]))
                self.assertEqual(d["total"], sum(d["buckets"].values()),
                                 "%s total 与五桶之和不一致" % name)
                self.assertEqual(len(d["items"]), d["total"],
                                 "%s items 条数应等于 total" % name)

    # ------------------------------------------------------------------ #
    # 20) 预览不污染任务状态（守住「仅预览分流不该锁状态」）
    # ------------------------------------------------------------------ #
    def test_20_dry_run_does_not_pollute_state(self):
        srv = self.start()
        for i in (1, 2):
            status, d = srv.post_json("/api/dry-run", {"input": "samples"})
            self.assertEqual(status, 200, "第 %d 次 dry-run HTTP %s" % (i, status))
            self.assertIs(d.get("ok"), True,
                          "第 %d 次 dry-run 失败：%s" % (i, d.get("error")))
        _, state = srv.get_json("/api/state")
        self.assertIs(state["running"], False,
                      "连续两次 dry-run 之后 /api/state.running 仍为 true")
        _, prog = srv.get_json("/api/progress?since=0")
        self.assertIs(prog["running"], False,
                      "dry-run 之后 /api/progress.running 仍为 true")
        self.assertEqual(prog["state"], "idle",
                         "dry-run 把 state 改成了 %s（应为 idle）" % prog["state"])
        self.assertIsNone(prog.get("error"),
                          "dry-run 不该留下 error：%s" % prog.get("error"))
        self.assertEqual(prog["events"], [], "dry-run 不该产生进度事件")
        self.assertIsNone(prog.get("summary"), "dry-run 不该产生 summary")

    # ------------------------------------------------------------------ #
    # 21) 静态资源禁缓存（app.py:_send_bytes 的 Cache-Control: no-store）
    # ------------------------------------------------------------------ #
    def test_21_static_assets_no_store(self):
        srv = self.start()
        for path in ("/", "/ui/app.js", "/ui/app.css"):
            with self.subTest(path=path):
                status, headers, _ = srv.get(path)
                self.assertEqual(status, 200, "%s 未返回 200" % path)
                cc = " ".join(v for k, v in headers.items()
                              if k.lower() == "cache-control").lower()
                self.assertIn("no-store", cc,
                              "%s 缺 Cache-Control: no-store（前端可能拿到旧 app.js）"
                              % path)

    # ------------------------------------------------------------------ #
    # 22) 前端状态锁静态契约（无前端测试框架，用文本断言防止修复回退）
    # ------------------------------------------------------------------ #
    def test_22_frontend_lock_contract(self):
        js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")

        # ① 超时与复位机制：AbortController + .finally + dry-run 显式超时
        self.assertIn("AbortController", js,
                      "api() 缺 AbortController：fetch 永久挂起时锁无法强制复位")
        self.assertIn(".finally(", js,
                      "前端用 .then 冒充 .finally，catch 抛错时会跳过锁复位")
        m = re.search(r'api\("/api/dry-run"\s*,\s*body\s*,\s*(\d+)\s*\)', js)
        self.assertIsNotNone(m, "doPreview 未给 /api/dry-run 传显式超时毫秒")
        self.assertEqual(int(m.group(1)), 40000,
                         "dry-run 前端超时应为 40000ms（后端 DRY_RUN_TIMEOUT=30s + 10s），"
                         "实得 %s" % m.group(1))

        # ② 旧写法不得残留：用正则容忍换行/空白差异，不做整行匹配
        legacy = re.search(
            r'\.then\(\s*function\s*\(\)\s*\{\s*previewing\s*=\s*false', js)
        self.assertIsNone(legacy,
                          "仍存在 .then(function () { previewing = false 的"
                          " then 冒充 finally 残留")

        # ③ 产物入口按钮必须存在，且不得进 updateControls 的 ids 禁用名单
        self.assertIn("btnOpenMerged", js, "app.js 缺少 btnOpenMerged 引用")
        start = js.find("function updateControls()")
        self.assertGreaterEqual(start, 0, "找不到 updateControls 函数")
        nxt = js.find("\n  function ", start + 1)
        body = js[start:nxt if nxt >= 0 else len(js)]
        ids = re.search(r'var\s+ids\s*=\s*\[(.*?)\]', body, re.S)
        self.assertIsNotNone(ids, "updateControls 里找不到 ids 数组")
        self.assertNotIn('"btnOpenMerged"', ids.group(1),
                         "btnOpenMerged 被放进 updateControls 的 ids 禁用名单，"
                         "previewing/running 锁会把它一起禁用")
        tag = re.search(r'<button[^>]*id="btnOpenMerged"[^>]*>', html)
        self.assertIsNotNone(tag, 'index.html 缺少 id="btnOpenMerged" 按钮')
        self.assertIn("disabled", tag.group(0),
                      "btnOpenMerged 必须默认 disabled（无产物时不可点）")

    # ------------------------------------------------------------------ #
    # 23) run 完成后 /api/state.running 复位（僵尸 job 兜底的 HTTP 侧验收）
    # ------------------------------------------------------------------ #
    def test_23_run_job_resets_running(self):
        srv = self.start()
        outdir = self.tmp / "out-state-after-run"
        d, _ = self.run_to_end("samples", outdir)
        self.assertIs(d["running"], False, "任务结束后 progress.running 应为 false")
        self.assertEqual(d["state"], "done", "任务应正常结束：%s" % d["state"])
        # /api/state 不含 state 字段（见 app.py:_api_state），只断言 running；
        # state 由 /api/progress 提供，上面已断言。
        _, state = srv.get_json("/api/state")
        self.assertIs(state["running"], False,
                      "任务结束后 /api/state.running 仍为 true（僵尸 job 未复位）")

    # ------------------------------------------------------------------ #
    # 24) 注入 _build_summary 异常：任务线程 finally 必复位 running
    # ------------------------------------------------------------------ #
    def test_24_summary_exception_no_stuck(self):
        """异常路径不残留 running：注入只发生在独立子进程的启动器里。

        与 LAUNCHER_SOURCE 同机制：不改 app.py、不污染测试进程的模块全局，
        _build_summary 在 _run_job_inner 里是裸名调用，替换模块全局即可命中。
        """
        class FailSummaryServer(AppServer):
            def _argv(self):
                assert self.workdir is not None
                launcher = self.workdir / "launch_fail_summary.py"
                launcher.write_text(LAUNCHER_FAIL_SUMMARY_SOURCE, encoding="utf-8")
                return [sys.executable, "-u", str(launcher), str(ROOT)]

        srv = FailSummaryServer(workdir=self.tmp, cwd=ROOT)
        self.srv = srv                      # tearDown 负责 stop
        srv.start(timeout=self.START_TIMEOUT)

        outdir = self.tmp / "out-fail-summary"
        d, _ = self.run_to_end("samples", outdir)
        self.assertIs(d["running"], False,
                      "_build_summary 抛异常后 progress.running 未复位（finally 缺失）")
        self.assertEqual(d["state"], "failed",
                         "异常路径 state 应落为 failed，不能残留 running：%s" % d["state"])
        _, state = srv.get_json("/api/state")
        self.assertIs(state["running"], False,
                      "_build_summary 抛异常后 /api/state.running 仍为 true")

    # ------------------------------------------------------------------ #
    # 25) 桌面端「关窗即退」契约：心跳端点形状 + 前后端钩子必须存在
    # ------------------------------------------------------------------ #
    def test_25_heartbeat_contract(self):
        srv = self.start()
        status, obj = srv.get_json("/api/heartbeat")
        self.assertEqual(status, 200, "/api/heartbeat 未返回 200")
        self.assertIsInstance(obj, dict, "/api/heartbeat 应返回 JSON 对象")
        self.assertIs(obj.get("ok"), True, "/api/heartbeat 应返回 {ok: true}")
        # 前端必须有周期心跳（真实窗口关闭行为自动化无法断言，见文件尾注）；
        # 缺了它，窗口关闭后服务端看门狗永远等不到「最后心跳」。
        js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        self.assertIn('"/api/heartbeat"', js,
                      "app.js 缺少 /api/heartbeat 周期心跳")
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("_start_window_watchdog(httpd)", src,
                      "app.py 未在窗口模式下挂看门狗：关窗不会自动退出")
        self.assertIn("HEARTBEAT_GRACE", src,
                      "app.py 缺少心跳宽限期常量")

    # ------------------------------------------------------------------ #
    # 26) v0.3.4 优化契约：身份标记 / 日志封顶 / 连接重置不刷栈 /
    #     高频端点不记访问日志 / 端口占用者身份校验
    # ------------------------------------------------------------------ #
    def test_26_optimization_contracts(self):
        srv = self.start()
        # ① /api/state 带 app 标记：单实例保护据此区分「自己」与「别的程序」
        _, state = srv.get_json("/api/state")
        self.assertEqual(state.get("app"), "jinghe",
                         "/api/state 缺少 app 标记：无法识别端口占用者身份")

        # ② 高频内部端点不写访问日志（心跳每 2 秒一次，逐条记录会淹没日志）
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('"/api/heartbeat"', src, "访问日志过滤列表缺少心跳端点")
        log_fn = src.split("def log_message", 1)[1].split("def ", 1)[0]
        for noisy in ("/api/heartbeat", "/api/state", "/api/progress"):
            self.assertIn('"%s"' % noisy, log_fn,
                          "log_message 未过滤 %s：桌面端日志会被高频请求刷屏" % noisy)

        # ③ 日志必须封顶（轮转），否则长期使用会无限膨胀
        self.assertIn("LOG_MAX_BYTES", src, "app.py 缺少日志上限常量")
        self.assertIn("_rotate_if_needed", src, "app.py 缺少日志轮转实现")

        # ④ 连接类异常静默：Edge 关窗时的预连接重置不该刷一整页栈回溯
        self.assertIn("handle_error", src, "app.py 未自定义 handle_error")
        self.assertIn("ConnectionResetError", src,
                      "handle_error 未区分连接重置：关窗会刷屏栈回溯")

        # ⑤ 端口被别的程序占用时要能识别，而不是当成「已有实例」弹陌生页面
        self.assertIn("_probe_running_instance", src,
                      "app.py 缺少端口占用者身份校验")
        self.assertIn('"app": "jinghe"', src,
                      "/api/state 未提供 app 标记，身份校验无从判断")

    # ------------------------------------------------------------------ #
    # 27) v0.3.5 界面改版契约：左侧可折叠导航 + 三页面 + 设置持久化接口
    # ------------------------------------------------------------------ #
    def test_27_sidebar_nav_and_settings(self):
        srv = self.start()
        html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "ui" / "app.css").read_text(encoding="utf-8")

        # ① 左侧导航栏结构：首页 / 设置 / 关于三个入口
        self.assertIn('class="sidebar"', html, "index.html 缺少左侧导航栏")
        self.assertIn('id="btnToggleNav"', html, "缺少折叠/展开按钮")
        for page in ("home", "settings", "about"):
            self.assertIn('data-page="%s"' % page, html,
                          "导航栏缺少 %s 入口" % page)
            self.assertIn('id="page-%s"' % page, html,
                          "缺少 %s 页面容器" % page)

        # ② 图标是导航的主要线索：折叠后只剩图标，文字标签隐藏
        self.assertIn("nav-collapsed", css, "样式里没有折叠态定义")
        self.assertIn(".nav-label", css, "折叠态未隐藏文字标签")
        self.assertIn(".nav-item svg", css, "导航项缺少图标样式")

        # ③ 页面切换逻辑：同一时刻只显示一个页面
        self.assertIn("activatePage", js, "app.js 缺少页面切换逻辑")
        self.assertIn(".nav-item", js, "app.js 未绑定导航点击事件")

        # ④ 设置接口：GET 返回默认值，POST 能持久化，非法值被收敛
        status, got = srv.get_json("/api/settings")
        self.assertEqual(status, 200, "/api/settings 未返回 200")
        self.assertIs(got.get("ok"), True, "/api/settings 缺少 ok=true")
        cfg = got.get("settings")
        self.assertIsInstance(cfg, dict, "/api/settings 未返回 settings 对象")
        for key in ("auto_exit", "exit_grace_seconds", "remember_paths",
                    "default_outdir"):
            self.assertIn(key, cfg, "设置项缺少 %s" % key)
        self.assertIsInstance(cfg["auto_exit"], bool, "auto_exit 应为布尔")

        status, saved = srv.post_json("/api/settings", {"settings": {
            "auto_exit": False, "exit_grace_seconds": 45,
            "remember_paths": False, "default_outdir": "probe-out"}})
        self.assertEqual(status, 200, "POST /api/settings 未返回 200")
        self.assertIs(saved["settings"]["auto_exit"], False, "auto_exit 未保存")
        self.assertEqual(saved["settings"]["exit_grace_seconds"], 45,
                         "exit_grace_seconds 未保存")
        self.assertEqual(saved["settings"]["default_outdir"], "probe-out",
                         "default_outdir 未保存")

        # 越界值必须被收敛（不能把任意数字直接写进配置）
        _, clamped = srv.post_json("/api/settings", {"settings": {
            "exit_grace_seconds": 999999, "default_outdir": 123}})
        self.assertEqual(clamped["settings"]["exit_grace_seconds"], 600,
                         "超范围宽限期未被收敛到 600")
        self.assertEqual(clamped["settings"]["default_outdir"], "",
                         "非字符串目录未被清空")

        # 复原默认，避免影响后续用例
        srv.post_json("/api/settings", {"settings": {
            "auto_exit": True, "exit_grace_seconds": 90,
            "remember_paths": True, "default_outdir": ""}})

        # ⑤ 设置确实落盘到本地文件（桌面软件的设置必须活过进程重启）
        self.assertTrue(got.get("settings_file"), "/api/settings 未返回设置文件路径")
        self.assertTrue(Path(got["settings_file"]).is_file(),
                        "设置文件未落盘：%s" % got["settings_file"])

        # ⑥ 设置页表单字段与后端键名一一对应
        for fid in ("setAutoExit", "setExitGrace", "setRememberPaths",
                    "setDefaultOutdir"):
            self.assertIn('id="%s"' % fid, html, "设置页缺少 %s 控件" % fid)

    # ------------------------------------------------------------------ #
    # 28) v0.3.6：侧栏宽度可调节 + 关于页版本更新 / 运行日志导出
    # ------------------------------------------------------------------ #
    def test_28_resizable_nav_update_and_log_export(self):
        srv = self.start()
        html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "ui" / "app.css").read_text(encoding="utf-8")
        src = (ROOT / "app.py").read_text(encoding="utf-8")

        # ① 侧栏宽度可调节：CSS 变量 + 拖拽手柄 + 记忆 + 折叠态覆盖
        self.assertIn("--sidebar-w", css, "侧栏宽度未用 CSS 变量，无法动态调节")
        self.assertIn("width: var(--sidebar-w)", css,
                      ".sidebar 宽度未绑定 --sidebar-w")
        self.assertIn(".nav-resizer", css, "缺少拖拽手柄样式")
        self.assertIn(".app.nav-collapsed .nav-resizer", css,
                      "折叠态未隐藏拖拽手柄（折叠宽度必须固定 58px）")
        self.assertIn('id="navResizer"', html, "index.html 缺少拖拽手柄元素")
        self.assertIn("initNavResize", js, "app.js 未初始化宽度拖拽")
        self.assertIn("LS_NAV_W", js, "侧栏宽度未记忆到 localStorage")
        self.assertIn("applyNavWidth", js, "缺少宽度钳制函数")
        # 折叠态规则优先级更高，必须能覆盖变量
        self.assertIn(".app.nav-collapsed .sidebar { width: 58px; }", css,
                      "折叠态宽度未固定为 58px")

        # ② 关于页「版本更新」：v0.3.8 起只保留一个「检查更新」按钮（本段按新版契约更新）
        self.assertIn('id="btnCheckUpdate"', html, "关于页缺少检查更新按钮")
        self.assertNotIn('id="btnDownloadLatest"', html,
                         "v0.3.8 已取消「下载最新版本」按钮")
        self.assertNotIn('id="aboutLatest"', html,
                         "v0.3.8 已把「最新版本」信息格换成检查更新按钮")
        self.assertIn('id="repoLink"', html, "关于页缺少仓库链接")
        self.assertIn("https://github.com/kong-city/jinghe/releases/latest", html,
                      "下载链接未指向 GitHub 仓库最新版本页")
        self.assertIn("RELEASES_LATEST_URL", src, "后端未定义最新版本链接常量")
        self.assertIn("/api/update", js, "前端未调用一键更新接口")
        self.assertIn("/api/update", src, "后端缺少一键更新路由")

        # ③ 首页「输出与选项」移除打开日志按钮，功能迁到关于页运行日志区
        self.assertNotIn('id="btnOpenLog"', html,
                         "首页仍保留打开日志文件按钮（应移到关于页）")
        self.assertNotIn("btnOpenLog:", js, "app.js 仍注册已删除的首页日志按钮")
        self.assertIn('id="btnOpenAboutLog"', html, "关于页运行日志缺少打开文件按钮")
        self.assertIn('id="btnExportLog"', html, "关于页运行日志缺少生成指定文件按钮")
        self.assertIn('id="chkErrorsOnly"', html, "缺少「仅导出报错行」选项")

        # ④ 检查更新接口：离线也要诚实降级，但下载链接始终可用
        status, upd = srv.get_json("/api/check-update")
        self.assertEqual(status, 200, "/api/check-update 未返回 200")
        self.assertIs(upd.get("ok"), True, "检查更新接口缺少 ok=true")
        self.assertIn("current", upd, "检查更新未返回当前版本")
        self.assertIn("latest_url", upd, "检查更新未返回下载链接")
        self.assertTrue(upd["latest_url"].startswith(
            "https://github.com/kong-city/jinghe/releases"),
            "下载链接不是仓库 releases 页面：%s" % upd.get("latest_url"))
        # 离线时 latest 可以为 None，但必须标记 offline 而不是伪装成功
        if upd.get("offline"):
            self.assertIsNone(upd.get("latest"), "离线时不应伪造最新版本号")
            self.assertTrue(upd.get("error"), "离线降级缺少 error 说明")

        # ⑤ 日志导出：显式给 path（不弹原生对话框），验证生成内容与报错筛选
        dest = self.tmp / "jinghe-export.log"
        status, exported = srv.post_json("/api/export-log",
                                         {"path": str(dest), "errors_only": False})
        self.assertEqual(status, 200, "/api/export-log 未返回 200")
        self.assertIs(exported.get("ok"), True,
                      "日志导出失败：%s" % exported.get("error"))
        self.assertTrue(dest.is_file(), "日志导出文件未生成")
        text = dest.read_text(encoding="utf-8")
        self.assertIn("精核 · 运行日志导出", text, "导出文件缺少报告头")
        self.assertIn("软件版本", text, "导出报告缺少版本信息")
        self.assertIn("导出模式", text, "导出报告缺少模式标注")
        self.assertGreater(exported.get("bytes", 0), 0, "导出字节数异常")
        self.assertIs(exported.get("errors_only"), False, "errors_only 回显错误")

        # 仅报错模式：行数不应超过完整导出，且带模式标记
        dest2 = self.tmp / "jinghe-errors-only.log"
        status, only = srv.post_json("/api/export-log",
                                     {"path": str(dest2), "errors_only": True})
        self.assertEqual(status, 200, "仅报错导出未返回 200")
        self.assertIs(only.get("ok"), True, "仅报错导出失败")
        self.assertIs(only.get("errors_only"), True, "errors_only 回显错误")
        self.assertLessEqual(only.get("lines", 1 << 30),
                             exported.get("lines", 0),
                             "仅报错模式行数居然多于完整导出")
        self.assertIn("仅报错 / 警告行", dest2.read_text(encoding="utf-8"),
                      "仅报错导出文件缺少模式标注")

        # ⑥ 安全：目标是目录 / 是原始日志文件时必须拒绝，不能覆盖
        status, bad = srv.post_json("/api/export-log",
                                    {"path": str(self.tmp), "errors_only": False})
        self.assertEqual(status, 200)
        self.assertIs(bad.get("ok"), False, "目标为目录时未拒绝")

        # ⑦ /api/open-latest 契约：URL 固定常量，不接受外部参数（防滥用）
        self.assertIn("RELEASES_LATEST_URL", src)
        self.assertIn('elif path == "/api/open-latest"', src,
                      "后端缺少打开下载页路由")


    # ------------------------------------------------------------------ #
    # 29) v0.3.7：首页文案 / 按钮精简 + 「打开合并文档」按钮失效修复
    # ------------------------------------------------------------------ #
    def test_29_home_ui_slim_and_open_merged(self):
        html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        src = (ROOT / "app.py").read_text(encoding="utf-8")

        # ① 卡片标题与「打开」按钮文案
        self.assertIn('<div class="card-title">输入</div>', html,
                      "首页卡片标题未改为「输入」")
        self.assertIn('<div class="card-title">输出</div>', html,
                      "首页卡片标题未改为「输出」")
        self.assertNotIn("输入来源", html, "首页仍残留「输入来源」")
        self.assertNotIn("输出与选项", html, "首页仍残留「输出与选项」")
        pick = re.search(r'<button[^>]*id="btnPickFiles"[^>]*>(.*?)</button>', html)
        self.assertIsNotNone(pick, "index.html 缺少 btnPickFiles 按钮")
        self.assertEqual(pick.group(1), "打开",
                         "「选择文件」按钮未改名为「打开」：%s" % pick.group(1))

        # ② 取消「选择文件夹」「打开输出目录」按钮与两条冗余提示
        for gone in ('id="btnBrowseInput"', "选择文件夹",
                     'id="btnOpenOut"', "打开输出目录",
                     "仅预览分流只盘点分类", "运行日志已移到", "meta-hint"):
            self.assertNotIn(gone, html, "首页仍残留已取消元素：%s" % gone)
        for gone_js in ("btnBrowseInput", "btnOpenOut", "openOutputDir",
                        'path: base + "/MERGED.md"'):
            self.assertNotIn(gone_js, js, "app.js 仍残留旧实现：%s" % gone_js)
        self.assertIn('id="btnOpenMerged"', html, "「打开合并文档」按钮不能一并删掉")

        # ③ 前端：专用端点 + 结果回显 + 重启后按产物恢复入口
        self.assertIn("/api/open-merged", js, "前端未调用专用打开端点")
        self.assertIn("/api/merged-status", js, "前端未做产物探测")
        self.assertIn("refreshMergedButton", js, "缺少重启后的按钮恢复逻辑")
        self.assertIn("showNotice(\"已打开合并文档", js,
                      "打开成功未给可见反馈（旧版静默吞结果的根因）")

        # ④ 后端：固定文件名、显式回传 via、无关联时回退记事本
        self.assertIn('elif path == "/api/open-merged"', src,
                      "后端缺少 /api/open-merged 路由")
        self.assertIn('if path == "/api/merged-status"', src,
                      "后端缺少 /api/merged-status 路由")
        self.assertIn("MERGED_NAME", src, "后端未固定合并文档文件名")
        self.assertIn('"via": via', src, "打开结果未回传打开方式")
        self.assertIn("_open_document", src, "缺少统一的可见打开器")
        self.assertIn("notepad.exe", src, "缺少系统记事本兜底")

        # ⑤ 真实 HTTP：探测端点不谎报、专用打开端点各分支形状正确
        srv = self.start(patch_open=True)
        status, st = srv.get_json("/api/merged-status?outdir=")
        self.assertEqual(status, 200, "/api/merged-status 未返回 200")
        self.assertIs(st.get("exists", True), False, "空 outdir 不应谎报存在")

        empty = self.tmp / "out-empty-37"
        empty.mkdir()
        q = urllib.parse.quote(str(empty), safe="")
        status, st = srv.get_json("/api/merged-status?outdir=" + q)
        self.assertEqual(status, 200)
        self.assertIs(st.get("exists", True), False, "空目录不应谎报已有 MERGED.md")

        status, obj = srv.post_json("/api/open-merged", {"outdir": ""})
        self.assertIs(obj.get("ok"), False, "空 outdir 应判失败")
        self.assertTrue(obj.get("error"), "空 outdir 缺错误文案")

        status, obj = srv.post_json("/api/open-merged", {"outdir": str(empty)})
        self.assertIs(obj.get("ok"), False, "没有 MERGED.md 却返回 ok=true")
        self.assertIn("未找到", obj.get("error") or "",
                      "缺产物时错误文案不明确：%s" % obj.get("error"))

        good = self.tmp / "out-good-37"
        good.mkdir()
        (good / "MERGED.md").write_text("# 合并文档\n\n正文\n", encoding="utf-8")
        status, st = srv.get_json("/api/merged-status?outdir=" +
                                 urllib.parse.quote(str(good), safe=""))
        self.assertIs(st.get("exists"), True, "已有 MERGED.md 未探测到")
        status, obj = srv.post_json("/api/open-merged", {"outdir": str(good)})
        self.assertIs(obj.get("ok"), True,
                      "已存在的 MERGED.md 应能打开：%s" % obj)
        self.assertTrue((obj.get("path") or "").endswith("MERGED.md"),
                        "未回传合并文档路径：%s" % obj)
        self.assertIn(obj.get("via"), ("startfile", "notepad", "browser"),
                      "打开方式回传异常：%s" % obj.get("via"))

    # ------------------------------------------------------------------ #
    # 30) v0.3.8：关于页一键检查更新 + 首页上下布局 / 已识别移到原输出位
    # ------------------------------------------------------------------ #
    def test_30_one_click_update_and_home_layout(self):
        html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "ui" / "app.css").read_text(encoding="utf-8")
        src = (ROOT / "app.py").read_text(encoding="utf-8")

        # ① 关于页：保留「当前版本」，「最新版本」信息格换成检查更新按钮
        self.assertIn("<span>当前版本</span>", html, "关于页缺少「当前版本」")
        self.assertIn('class="about-grid about-grid-update"', html,
                      "版本更新卡片未改为 about-grid-update")
        self.assertIn('id="btnCheckUpdate"', html, "缺少检查更新按钮")
        self.assertIn('class="btn btn-primary about-check-btn"', html,
                      "检查更新按钮未放到「最新版本」原来的格子里")
        self.assertNotIn("<span>最新版本</span>", html, "「最新版本」信息格未移除")
        self.assertNotIn('id="aboutLatest"', html, "仍残留 aboutLatest 元素")
        self.assertNotIn('id="btnDownloadLatest"', html, "「下载最新版本」按钮未取消")
        self.assertIn('id="updateStatus" class="update-status"', html,
                      "缺少独立可见的更新状态条")
        p_ver = html.index("<span>当前版本</span>")
        p_btn = html.index('id="btnCheckUpdate"')
        p_st = html.index('id="updateStatus"')
        self.assertLess(p_ver, p_btn, "检查更新按钮未取代「最新版本」格")
        self.assertLess(p_btn, p_st, "更新状态条位置异常")

        # ② 前端：一键端点、状态回显、旧按钮 / 旧函数彻底清理
        self.assertIn("/api/update", js, "前端未调用 /api/update")
        self.assertIn("setUpdateStatus", js, "前端缺少更新结果回显")
        self.assertNotIn("downloadLatest", js, "仍残留 downloadLatest 实现")
        self.assertNotIn("aboutLatest", js, "仍残留 aboutLatest 引用")
        self.assertNotIn("/api/open-latest", js,
                         "前端不应再单独调用下载页接口")
        self.assertNotIn("/api/check-update", js,
                         "前端不应再单独调用检查接口（已合并到 /api/update）")

        # ③ 后端：一键端点 + URL 白名单 + 结果形状
        self.assertIn('elif path == "/api/update"', src, "后端缺少 /api/update 路由")
        self.assertIn("def _api_update", src, "后端缺少 _api_update 实现")
        self.assertIn('url.startswith(REPO_URL + "/releases")', src,
                      "一键更新未做 URL 白名单收敛")
        self.assertIn("webbrowser.open(url)", src,
                      "一键更新未自动打开最新版本页面")

        # ④ 首页：输入 / 输出上下堆叠，已识别移到原输出的右列
        self.assertIn('class="card card-input"', html, "首页缺少输入卡片标记")
        self.assertIn('class="card card-output"', html, "首页缺少输出卡片标记")
        self.assertIn('class="card card-files" id="fileListWrap"', html,
                      "已识别清单未做成独立卡片")
        p_in = html.index('class="card card-input"')
        p_out = html.index('class="card card-output"')
        p_files = html.index('class="card card-files"')
        self.assertLess(p_in, p_out, "输出卡片未放在输入下面")
        self.assertLess(p_out, p_files, "已识别卡片未放在原输出的位置（右列）")
        self.assertIn('"input files"', css, "CSS 未把已识别放到右列")
        self.assertIn('"output files"', css, "CSS 未让输出在输入下方")
        self.assertIn("grid-template-areas", css, "首页未改用 grid 区域布局")
        self.assertIn("[hidden] { display: none !important; }", css,
                      "缺少 hidden 强制隐藏，列表空态会留下空列")
        self.assertIn('id="fileListEmpty"', html, "已识别卡片缺少空态提示")
        self.assertNotIn("fileListWrap.hidden", js,
                         "已识别卡片应常显，不再整体 hidden")

        # ⑤ 真实 HTTP：一键更新返回完整形状，离线不伪造版本号
        srv = self.start(patch_open=True)
        status, upd = srv.post_json("/api/update", {})
        self.assertEqual(status, 200, "/api/update 未返回 200：%s" % upd)
        self.assertIs(upd.get("ok"), True, "一键更新未返回 ok=true")
        for key in ("current", "latest", "latest_url", "url", "opened",
                    "status", "message", "offline"):
            self.assertIn(key, upd, "/api/update 缺少字段 %s" % key)
        self.assertIn(upd.get("status"),
                      ("up_to_date", "new_version", "offline"),
                      "一键更新状态取值异常：%s" % upd.get("status"))
        self.assertTrue((upd.get("url") or "").startswith(
            "https://github.com/kong-city/jinghe/releases"),
            "打开链接不是仓库 releases 页：%s" % upd.get("url"))
        self.assertTrue(upd.get("message"), "一键更新缺少可读结果说明")
        if upd.get("offline"):
            self.assertIsNone(upd.get("latest"), "离线时不应伪造最新版本号")
        if upd.get("status") == "up_to_date":
            self.assertIs(upd.get("opened"), False, "已是最新却仍弹了下载页")
        else:
            self.assertIs(upd.get("opened"), True,
                          "发现新版本 / 离线时未自动打开最新版本页")

        # ⑥ 保留的旧端点仍可用（后端能力不删，UI 不再单独暴露）
        status, chk = srv.get_json("/api/check-update")
        self.assertEqual(status, 200, "/api/check-update 兼容端点不可用")
        self.assertIs(chk.get("ok"), True)


def print_summary(result=None) -> None:
    """末尾打印契约数字摘要，便于交付留痕（风格与 test_extract.py 一致）。"""
    print("\n=== 界面 / API 契约数字摘要 ===")
    # 口径与 SPEC §8.3 对齐：8 个 /api/* 业务端点（v2.7 加入 /api/pick-files），
    # favicon 是短路由，不把 favicon 算进 API 计数（早先的口误）。
    print("被测对象            : app.py（ThreadingHTTPServer + 多个 /api/* 端点 + favicon 短路 + 2 静态路由）")
    print("样例契约            : %d 文件 / 候选 %d / 成功 %d / 未成功 %d / 阶段3预留 %d"
          % (EXPECT_TOTAL, EXPECT_CANDIDATES, EXPECT_SUCCESS, EXPECT_FAILED, EXPECT_DEFERRED))
    print("降级契约            : %d 条（5 加密 + 1 无效容器，不含音视频）" % EXPECT_DEGRADED)
    print("端口获取            : --port 0 + 解析启动横幅（非 bind 试探）")
    print("孤儿清扫            : 启动时清已死 pid 目录，存活进程与形状不符者跳过")
    print("--------------------------------")
    if result is not None:
        passed = (result.testsRun - len(result.failures) - len(result.errors)
                  - len(result.expectedFailures) - len(result.skipped)
                  - len(result.unexpectedSuccesses))
        print("断言用例总数        : %d" % result.testsRun)
        print("正式通过            : %d" % passed)
        print("失败 / 错误         : %d / %d" % (len(result.failures), len(result.errors)))
        print("预期失败门禁        : %d（@expectedFailure 用例数）"
              % len(result.expectedFailures))
        print("意外成功(需转正)    : %d" % len(result.unexpectedSuccesses))
    print("==============================")


# 本文件刻意不覆盖的契约（写在这里，避免被误当成漏测）：
#   * 真实 Edge --app 窗口：会弹出 GUI，自动化环境无法断言窗口行为，只验证
#     `--no-browser` 分支不调用 open_window（启动横幅是唯一可观察信号）。
#   * `--windowed` 打包态的 MessageBoxW 兜底（app.py:_fatal）：仅 frozen 且非
#     --cli 时触发，源码模式无法进入该分支。
#   * /api/pick-folder：会弹出原生 IFileDialog 模态框，无人值守环境下必然阻塞，
#     故不调用；其返回值只做 HTTP 形状约定，无法做功能断言。
#     （/api/pick-files 的做法不同：test_18 把 Show 拦成「取消」，在**不弹窗**的
#      前提下验证了选项位与过滤器——真机点选仍需人工，但回归风险已被锁住。）
#   * 「只监听 127.0.0.1」的网卡级验证：从本机非回环地址连自己的端口会受防火墙
#     策略影响，结果不稳定，仅断言横幅 URL 的主机是 127.0.0.1。

if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    outcome = runner.run(suite)
    print_summary(outcome)
    sys.exit(0 if outcome.wasSuccessful() else 1)
