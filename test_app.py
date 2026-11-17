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
 13. /api/open（v0.4.0 起白名单收敛：任意路径 → ok=false；本软件日志文件 → ok=true）
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
import urllib.parse
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
app._download_release_asset = lambda url, version: {"ok": False, "error": "测试替身：禁止联网下载"}
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
    # 14) /api/open（v0.4.0：白名单收敛，不再接受任意路径）
    # ------------------------------------------------------------------ #
    def test_14_open_api(self):
        srv = self.start(patch_open=True)

        status, obj = srv.post_json("/api/open", {"path": ""})
        self.assertEqual(status, 200)
        self.assertIs(obj.get("ok"), False, "空路径应失败")
        self.assertTrue(obj.get("error"), "空路径缺 error 文案")

        # 任意路径（文件 / 目录 / 不存在）一律拒绝：不再把任意程序交给 startfile
        outside = self.tmp / "存在 的文件.txt"
        outside.write_text("x", encoding="utf-8")
        for p in (str(self.tmp), str(outside), str(self.tmp / "no-such-path")):
            status, obj = srv.post_json("/api/open", {"path": p})
            self.assertIs(obj.get("ok"), False,
                          "白名单外的路径竟可打开：%s -> %s" % (p, obj))
            self.assertIn("只允许", obj.get("error") or "",
                          "拒绝原因不明确：%s" % obj)

        # 白名单内：后端自报的日志文件应能打开（启动器已把打开器替换为空操作）
        status, st = srv.get_json("/api/state")
        self.assertEqual(status, 200)
        log_path = str(st.get("log_file") or "")
        self.assertTrue(log_path, "/api/state 未返回 log_file")
        status, obj = srv.post_json("/api/open", {"path": log_path})
        self.assertIs(obj.get("ok"), True,
                      "本软件日志文件应可打开：%s" % obj)

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

        # ② 关于页「版本更新」：v0.3.9 起只保留「检查更新」（左）+「当前版本」（右）
        self.assertIn('id="btnCheckUpdate"', html, "关于页缺少检查更新按钮")
        self.assertNotIn('id="btnDownloadLatest"', html,
                         "「下载最新版本」按钮已取消")
        self.assertNotIn('id="aboutLatest"', html,
                         "「最新版本」信息格已移除")
        self.assertNotIn('id="repoLink"', html,
                         "v0.3.9 已清除显示的 GitHub 链接")
        self.assertNotIn("https://github.com/kong-city/jinghe/releases/latest", html,
                         "版本更新卡片不再显示 GitHub 链接")
        self.assertIn("RELEASES_LATEST_URL", src,
                      "后端仍保留最新版本链接常量（发现新版本时自动打开）")
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

        # ① 关于页：保留「当前版本」；v0.4.9 起按用户新要求取消「最新版本」栏——
        #    最新版本只通过检查结果反馈（「当前是最新版本」轻提示 / 直接更新）给出，
        #    不再单列信息格。仍不恢复独立「下载最新版本」按钮。
        self.assertIn("<span>当前版本</span>", html, "关于页缺少「当前版本」")
        self.assertIn('class="about-grid about-grid-update"', html,
                      "版本更新卡片未改为 about-grid-update")
        self.assertIn('id="btnCheckUpdate"', html, "缺少检查更新按钮")
        self.assertIn('class="btn btn-primary about-check-btn"', html,
                      "检查更新按钮样式异常")
        self.assertNotIn("<span>最新版本</span>", html,
                         "v0.4.9：「最新版本」信息格应已取消")
        self.assertNotIn('id="aboutNewVersion"', html, "v0.4.9：最新版本显示位应已移除")
        self.assertNotIn('id="aboutLatest"', html, "仍残留 aboutLatest 元素")
        self.assertNotIn('id="btnDownloadLatest"', html, "「下载最新版本」按钮未取消")
        self.assertIn('id="updateStatus" class="update-status" hidden', html,
                      "更新状态条应默认隐藏（离线长文案已清除）")
        p_ver = html.index("<span>当前版本</span>")
        p_btn = html.index('id="btnCheckUpdate"')
        p_st = html.index('id="updateStatus"')
        self.assertLess(p_btn, p_ver,
                        "v0.3.9：检查更新按钮应在左侧（先于「当前版本」）")
        self.assertLess(p_ver, p_st, "更新状态条位置异常")

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
        elif upd.get("status") == "offline":
            self.assertIs(upd.get("opened"), False,
                          "v0.3.9：离线不应再自动弹浏览器")
        else:
            self.assertTrue(upd.get("opened") or upd.get("downloaded"),
                            "发现新版本时既未下载安装包，也未打开下载页")

        # ⑥ 保留的旧端点仍可用（后端能力不删，UI 不再单独暴露）
        status, chk = srv.get_json("/api/check-update")
        self.assertEqual(status, 200, "/api/check-update 兼容端点不可用")
        self.assertIs(chk.get("ok"), True)

    # ------------------------------------------------------------------ #
    # 31) v0.3.9：关于页清除说明内容/链接/离线长文案 + 按钮左、当前版本右
    # ------------------------------------------------------------------ #
    def test_31_about_cleanup_and_button_left(self):
        html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "ui" / "app.css").read_text(encoding="utf-8")
        src = (ROOT / "app.py").read_text(encoding="utf-8")

        # ① 清除说明段：整段「点击「检查更新」即可完成更新…」不再出现在页面
        for gone in ("点击「检查更新」即可完成更新",
                     "发现新版本时自动打开最新版本下载页",
                     "离线时也会打开仓库最新发布页供手动确认"):
            self.assertNotIn(gone, html, "版本更新卡片仍残留说明文案：%s" % gone)
        # 版本更新卡片内不允许再有 card-sub
        seg = html[html.index('id="page-about"'):]
        card = seg[:seg.index("</section>")]
        self.assertNotIn("card-sub", card, "版本更新卡片说明段未清除")
        self.assertNotIn("github.com", card, "版本更新卡片仍显示 GitHub 链接")

        # ② 检查更新按钮在左、当前版本在右（DOM 顺序即左右顺序）
        self.assertIn('class="about-grid about-grid-update"', html,
                      "版本更新卡片未使用双列 grid")
        p_btn = card.index('id="btnCheckUpdate"')
        p_ver = card.index("<span>当前版本</span>")
        self.assertLess(p_btn, p_ver, "检查更新按钮未放到左侧")
        self.assertIn(">检查更新</button>", card, "按钮文案应为「检查更新」")
        self.assertIn('id="aboutVersion"', card, "右侧缺少当前版本")

        # ③ 清除显示的 GitHub 链接与离线长文案
        self.assertNotIn('id="repoLink"', html, "仍残留 repoLink 链接")
        self.assertNotIn("repo-link", css, "仍残留 repo-link 样式")
        self.assertNotIn("el.repoLink", js, "前端仍引用已删除的链接")
        self.assertNotIn('href="https://github.com/kong-city/jinghe', html,
                         "关于页仍显示 GitHub 链接")
        self.assertNotIn('<span class="mono set-path">https://github.com', html,
                         "隐私与依赖卡片仍显示仓库地址")
        offline_msg = "无法连接 GitHub，已打开最新版本页面，请手动确认是否有更新"
        self.assertNotIn(offline_msg, html, "页面仍残留离线长文案")
        self.assertNotIn(offline_msg, js, "前端仍残留离线长文案")
        self.assertNotIn(offline_msg, src, "后端仍生成离线长文案")
        self.assertNotIn("is-warn", css, "离线专用警告样式未清除")

        # ④ 状态条默认隐藏；离线时给的是**短句诚实反馈**（v0.4.8 起不再静默隐藏，
        #    用户要求「按实际情况给出结果反馈」），但仍不弹浏览器、不用旧长文案
        self.assertIn('id="updateStatus" class="update-status" hidden', html,
                      "状态条应默认隐藏，不显示任何占位文案")
        self.assertIn("el.updateStatus.hidden = !s", js,
                      "前端未实现空文案隐藏状态条")
        self.assertIn('if (r.offline)', js,
                      "前端未对离线状态做单独处理")
        self.assertIn("无法连接版本服务", js,
                      "离线时必须给出可读反馈，不得静默无反应")
        self.assertIn('if info.get("up_to_date") is False:', src,
                      "后端只在发现新版本时自动打开下载页")
        self.assertNotIn("need_open = bool(info.get(\"offline\")", src,
                         "后端仍会在离线时弹浏览器")
        self.assertIn("self._api_check_update()", src,
                      "点击检查更新后必须真的查询 GitHub 最新版本")

        # ⑤ 真实 HTTP：离线诚实降级、不弹浏览器、不返回被清除的文案
        srv = self.start(patch_open=True)
        status, upd = srv.post_json("/api/update", {})
        self.assertEqual(status, 200, "/api/update 未返回 200：%s" % upd)
        self.assertIs(upd.get("ok"), True)
        if upd.get("offline"):
            self.assertEqual(upd.get("status"), "offline")
            self.assertIs(upd.get("opened"), False,
                          "离线时不应自动打开浏览器：%s" % upd)
            self.assertNotIn("无法连接 GitHub", upd.get("message") or "",
                             "离线提示仍含被清除的文案：%s" % upd.get("message"))
            self.assertIsNone(upd.get("latest"), "离线不应伪造最新版本号")

    # ------------------------------------------------------------------ #
    # 32) v0.4.0：工程化交付闭环（CI / CHANGELOG / 发版门禁 / 更新资产 / 安全边界）
    # ------------------------------------------------------------------ #
    def test_32_engineering_delivery_and_update_asset(self):
        html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        wf = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        version = re.search(
            r'^__version__\s*=\s*"([^"]+)"',
            (ROOT / "extract.py").read_text(encoding="utf-8"), re.M).group(1)

        # ① 构建 / 发布阶段：测试门禁 + tag 触发构建并上传 exe 资产
        for token in ("windows-latest", "python -m unittest", "pyinstaller",
                      "tags:", "python build.py", "gh release",
                      "dist/Jinghe.exe", "check_release.py"):
            self.assertIn(token, wf, "CI workflow 缺少：%s" % token)
        self.assertIn("needs: test", wf, "发布前必须先通过测试门禁")

        # ② 发布管理：CHANGELOG 与版本单一来源（HTML 不再硬编码）
        self.assertIn("## [%s]" % version, changelog,
                      "CHANGELOG.md 缺少当前版本条目")
        self.assertIn("Jinghe.exe", changelog)
        self.assertIsNone(re.search(r'>\s*v\d+\.\d+\.\d+\s*<', html),
                          "ui/index.html 仍硬编码版本号")
        self.assertIn('id="headerTag"', html)
        self.assertIn("headerTag.textContent", js,
                      "版本号未由 /api/state 动态注入")
        # 防回归：loadAbout() 只在切到关于页时才跑，页头标签必须在启动分支注入
        boot = js[js.index('document.title = "精核 · 文件提取 v"'):]
        self.assertIn("el.headerTag", boot[:500],
                      "页头版本号挂在 loadAbout 里，首页会一直显示占位符")

        # 防回归：Windows runner 默认 cp1252，门禁打印中文会抛
        # UnicodeEncodeError，导致整个 Release 构建作业被 needs: test 跳过。
        gate_src = (ROOT / "tools" / "check_release.py").read_text(
            encoding="utf-8")
        self.assertIn('reconfigure(encoding="utf-8"', gate_src,
                      "发版门禁缺少 Windows 控制台 UTF-8 兜底")
        self.assertIn("PYTHONUTF8", wf, "CI 未固定 Python UTF-8 模式")

        # ③ 发版门禁脚本可独立运行且判定通过
        gate = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "check_release.py"), "--no-exe"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=90,
            encoding="utf-8", errors="replace")
        self.assertEqual(gate.returncode, 0,
                         "发版门禁未通过：%s" % (gate.stdout + gate.stderr)[-800:])

        # ④ 更新闭环：解析 assets、URL 白名单、大小上限、下载结果字段
        #    v0.4.8：assets 解析与白名单收敛迁到 self_update.py（单点真源），
        #    app.py 只保留字段形状与旧端点兼容。
        su_src = (ROOT / "self_update.py").read_text(encoding="utf-8")
        for token in ("RELEASES_DOWNLOAD_PREFIX", "MAX_UPDATE_BYTES",
                      "_download_release_asset", "has_asset", "asset_url",
                      "downloaded", "download_path", "_current_version",
                      "extract.__version__"):
            self.assertIn(token, src, "后端缺少 v0.4.0 更新闭环实现：%s" % token)
        for token in ('data.get("assets")', "RELEASES_DOWNLOAD_PREFIX",
                      "is_asset_url"):
            self.assertIn(token, su_src,
                          "self_update.py 缺少更新资产解析实现：%s" % token)
        self.assertIn("is_asset_url(dl)", su_src,
                      "资产直链未做白名单收敛")
        # v0.4.8：前端改为「先查版本、再后台更新」两步，不再一次性等下载
        self.assertIn('"/api/update/check"', js, "前端未调用版本检查接口")
        self.assertIn('"/api/update/start"', js, "前端未调用更新启动接口")

        # ⑤ unknown 版本回退 + 下载地址白名单（直接测模块函数，不联网）
        sys.path.insert(0, str(ROOT))
        try:
            import app as app_mod
            cur = app_mod._current_version()
            self.assertTrue(re.match(r"^\d+\.\d+\.\d+", cur),
                            "current 版本回退失败：%s" % cur)
            bad = app_mod._download_release_asset(
                "https://evil.example.com/Jinghe.exe", "9.9.9")
            self.assertIs(bad.get("ok"), False, "白名单外地址竟允许下载")
            self.assertIn("白名单", bad.get("error") or "")
            self.assertGreaterEqual(app_mod.MAX_UPDATE_BYTES, 8 * 1024 * 1024,
                                    "安装包大小上限过小")
        finally:
            sys.path.remove(str(ROOT))

        # ⑥ 安全边界：/api/open 不再接受任意路径
        self.assertIn("只允许打开本软件的日志文件与设置文件", src)
        self.assertIn("target not in allowed", src)
        srv = self.start(patch_open=True)
        outside = self.tmp / "outside-40.txt"
        outside.write_text("x", encoding="utf-8")
        status, obj = srv.post_json("/api/open", {"path": str(outside)})
        self.assertIs(obj.get("ok"), False, "任意路径仍可打开：%s" % obj)

        # ⑦ 真实 HTTP：检查更新返回资产字段；离线不下载、不弹浏览器
        status, chk = srv.get_json("/api/check-update")
        self.assertEqual(status, 200)
        for key in ("has_asset", "asset_name", "asset_size", "asset_url", "current"):
            self.assertIn(key, chk, "/api/check-update 缺少资产字段 %s" % key)
        self.assertTrue(re.match(r"^\d+\.\d+\.\d+", str(chk.get("current"))),
                        "current 不应是 unknown：%s" % chk.get("current"))
        status, upd = srv.post_json("/api/update", {})
        self.assertEqual(status, 200)
        self.assertIn("downloaded", upd)
        self.assertIn("download_path", upd)
        if upd.get("offline"):
            self.assertIs(upd.get("downloaded"), False,
                          "离线时不应触发下载：%s" % upd)
            self.assertIs(upd.get("opened"), False,
                          "离线时不应自动弹浏览器：%s" % upd)

    # ------------------------------------------------------------------ #
    # 33) v0.4.3 / S1：FORMAT_REGISTRY、工具健康探测、独立产物区
    # ------------------------------------------------------------------ #
    def test_33_s1_registry_tools_and_derived(self):
        sys.path.insert(0, str(ROOT))
        try:
            import extract
            import format_registry as reg
            import media_tools
            import media_runtime as rt
        finally:
            sys.path.remove(str(ROOT))
        from unittest import mock

        app_src = (ROOT / "app.py").read_text(encoding="utf-8")
        html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        gate = (ROOT / "tools" / "check_release.py").read_text(encoding="utf-8")

        # ① 冻结内核只读镜像必须逐字一致，且 extract.py 本身没被改写
        self.assertEqual(reg.STAGE1_SKILL, set(extract.SKILL_EXT))
        self.assertEqual(reg.STAGE1_PLAIN, set(extract.PLAIN_EXT))
        self.assertEqual(reg.STAGE1_RICH, set(extract.RICH_EXT))
        self.assertEqual(reg.STAGE1_DEFERRED, set(extract.DEFERRED_EXT))
        self.assertEqual(reg.STAGE1_LEGACY, set(extract.LEGACY_EXT))
        self.assertNotIn(".wmv", extract.DEFERRED_EXT,
                         "冻结内核被改动：DEFERRED_EXT 不应混入 .wmv")
        self.assertEqual(reg.stage1_bucket(".mp4"), "阶段3预留")
        self.assertEqual(reg.stage1_bucket(".doc"), "需预处理")
        self.assertEqual(reg.stage1_bucket(".zzz"), "不支持")

        # ② D1 漂移收敛：.m4v 与 .wmv 并存，视频绝不归音频（红线 2）
        self.assertIn(".m4v", reg.MEDIA_EXT)
        self.assertIn(".wmv", reg.MEDIA_EXT)
        self.assertEqual(reg.media_kind(".mp4"), "video")
        self.assertEqual(reg.media_kind(".wmv"), "video")
        self.assertEqual(reg.media_kind(".mp3"), "audio")
        self.assertIn("_STAGE3_AUDIO_EXT = set(format_registry.MEDIA_EXT)", app_src)
        self.assertIn("_FILE_FILTERS = format_registry.file_filters()", app_src)

        # ③ D2 漂移收敛：过滤器不再列出 extract.py 不支持的扩展名
        filters = dict(reg.file_filters())
        tokens = set(filters["全部支持格式"].split(";"))
        for bad in (".rtf", ".odt", ".ods", ".odp", ".yaml", ".yml",
                    ".ini", ".py", ".js", ".markdown"):
            self.assertNotIn("*" + bad, tokens,
                             "过滤器仍把不支持的 %s 列为「全部支持格式」" % bad)
        self.assertIn("*.docx", tokens)
        self.assertIn("*.mp4", tokens)  # 阶段 1 会识别（判为预留）

        # ④ 工具探测三条路径：缺工具 / 探测失败 / 探测成功，全都不撒谎
        missing = media_tools.ToolAdapter(
            "ffmpeg", ["-version"], which=lambda n: None).probe()
        self.assertIs(missing["available"], False)
        self.assertIn("未找到", missing["reason"])

        class _Fail:
            returncode = 2
            stdout = ""
            stderr = "bad option"

        failed = media_tools.ToolAdapter(
            "ffmpeg", ["-version"], which=lambda n: "C:/fake/ffmpeg.exe",
            runner=lambda **kw: _Fail()).probe()
        self.assertIs(failed["available"], False,
                      "工具存在但探测失败，不能报可用")
        self.assertIn("退出码", failed["reason"])

        class _OK:
            returncode = 0
            stdout = "ffmpeg version 6.1.1 Copyright (c)"
            stderr = ""

        good = media_tools.ToolAdapter(
            "ffmpeg", ["-version"], r"ffmpeg version\s+(\S+)",
            which=lambda n: "C:/fake/ffmpeg.exe",
            runner=lambda **kw: _OK()).probe()
        self.assertIs(good["available"], True)
        self.assertEqual(good["version"], "6.1.1")

        # ④b 重依赖 CLI 单独超时：whisper 启动 6–8s（import torch/numba），
        #     必须比默认 2s 宽，否则「已装好」会被误判「未启用」。
        self.assertGreater(media_tools.PROBE_TIMEOUTS.get("whisper", 2.0),
                           media_tools.DEFAULT_TIMEOUT,
                           "whisper 探测超时未放宽，重依赖 CLI 会被误判未启用")
        adapters = media_tools._adapters()
        self.assertGreater(adapters["whisper"].timeout, media_tools.DEFAULT_TIMEOUT)
        self.assertEqual(adapters["ffmpeg"].timeout, media_tools.DEFAULT_TIMEOUT,
                         "ffmpeg 是轻量 CLI，不应无故放宽超时")
        self.assertGreaterEqual(adapters["yt-dlp"].timeout, media_tools.DEFAULT_TIMEOUT)
        # TOOL_SPECS 三工具结构不变（S1 契约）
        self.assertEqual([s[0] for s in media_tools.TOOL_SPECS],
                         ["ffmpeg", "whisper", "yt-dlp"])

        # ⑤ 探测结果进程内缓存，不会每次请求都起外部子进程
        calls = {"n": 0}

        def _runner(**kw):
            calls["n"] += 1
            return _OK()

        media_tools.reset_cache()
        with mock.patch.object(media_tools.shutil, "which",
                               return_value="C:/fake/tool.exe"), \
             mock.patch.object(media_tools.subprocess, "run",
                               side_effect=_runner):
            first = media_tools.probe_all()
            second = media_tools.probe_all()
        self.assertEqual(calls["n"], 3, "探测结果未缓存或工具数量不符")
        self.assertEqual(first, second)
        media_tools.reset_cache()

        # ⑥ S1 能力一律未启用：绝不因为工具齐全就伪装成可用
        caps = media_tools.capabilities()
        self.assertTrue(all(not v["enabled"] for v in caps.values()))
        self.assertIs(media_tools.media_ready(
            {"ffmpeg": {"available": True}, "whisper": {"available": True}},
            caps), False, "S3 未接入却允许点亮转写入口")

        # ⑦ 独立产物区：写 derived/ 后冻结对账盘必须一模一样
        (self.tmp / "md").mkdir()
        (self.tmp / "md" / "a.md").write_text("# a\n", encoding="utf-8")
        (self.tmp / "INDEX.md").write_text("idx\n", encoding="utf-8")
        (self.tmp / "MERGED.md").write_text("merged\n", encoding="utf-8")
        before = rt.frozen_snapshot(self.tmp)
        prov = rt.write_provenance(
            self.tmp, entries=[{"status": "unavailable", "reason": "缺工具"}])
        self.assertEqual(prov.parent.name, rt.DERIVED_DIRNAME)
        self.assertTrue(rt.frozen_unchanged(before, self.tmp),
                        "新能力污染了阶段 1 的 md/ 对账盘")
        data = rt.read_provenance(self.tmp)
        self.assertEqual(data["schema"], rt.SCHEMA)
        self.assertEqual(len(data["entries"]), 1)
        self.assertIn("md", data["frozen_artifacts_untouched"])

        # ⑧ 出处骨架：8 字段 src 注释 + 完整 sha256 + 块级锚点正则
        comment = rt.source_comment(self.tmp / "md" / "a.md", ".md", "内置转换器 v1")
        self.assertIn("<!-- source:", comment)
        for key in ("src:", "path:", "format:", "converter:", "extracted:",
                    "size:", "sha256:", "anchors:"):
            self.assertIn(key, comment, "src 注释缺少字段 %s" % key)
        self.assertIsNotNone(re.search(r"sha256: [0-9a-f]{64}", comment))
        anchor = rt.block_anchor("doc_0123456789ab", 1, time="00:00:01.000")
        self.assertRegex(anchor, r"<!--\s*anchor:\s*doc_[0-9a-f]{12}\s*\|")
        self.assertIn("time: 00:00:01.000", anchor)
        self.assertNotIn("page:", anchor, "不适用的定位键必须省略")

        # ⑨ UI 诚实降级 + 新模块纳入发版门禁的编译检查
        self.assertIn('id="toolStatus"', html)
        self.assertIn("/api/tools/probe", js)
        self.assertIn("未启用", js)
        self.assertIn("el.btnTranscribe.disabled = !on || !mediaOn", js)
        for name in ("format_registry.py", "media_tools.py", "media_runtime.py"):
            self.assertIn(name, gate, "门禁未编译新模块 %s" % name)

    # ------------------------------------------------------------------ #
    # 34) v0.4.3 / S1：探测端点、诚实降级、长任务超时与子进程终止
    # ------------------------------------------------------------------ #
    def test_34_s1_probe_http_and_long_job(self):
        srv = self.start(patch_open=True)

        # ① 真实 HTTP：健康探测契约 + 独立产物区声明
        status, obj = srv.get_json("/api/tools/probe")
        self.assertEqual(status, 200, "探测端点未返回 200：%s" % obj)
        self.assertIs(obj.get("ok"), True)
        for key in ("tools", "capabilities", "media_ready", "derived"):
            self.assertIn(key, obj, "探测响应缺少 %s" % key)
        for name in ("ffmpeg", "whisper", "yt-dlp"):
            tool = obj["tools"].get(name)
            self.assertIsInstance(tool, dict, "缺少工具 %s 的探测结果" % name)
            self.assertIn("available", tool)
            self.assertIn("reason", tool)
        self.assertEqual(obj["derived"]["dirname"], "derived")
        self.assertIn("md", obj["derived"]["frozen_artifacts_untouched"])
        self.assertIs(obj["capabilities"]["media_transcribe"]["enabled"], False)
        self.assertIs(obj["media_ready"], False,
                      "S1 未接入转写后端，media_ready 必须为 false")

        status2, obj2 = srv.get_json("/api/tools/probe?refresh=1")
        self.assertEqual(status2, 200)
        self.assertEqual(set(obj2["tools"]), set(obj["tools"]))

        # ② 转写入口仍是空心占位：识别到文件也只诚实拒绝，绝不产出伪转写
        clip = self.tmp / "clip.mp3"
        clip.write_bytes(b"ID3 fake audio")
        status3, tr = srv.post_json("/api/transcribe",
                                    {"inputs": [str(clip)]})
        self.assertEqual(status3, 200)
        self.assertIs(tr.get("ok"), False)
        self.assertIn("未启用", tr.get("error") or "")
        self.assertEqual(list(self.tmp.glob("*.md")), [],
                         "缺工具时竟产出了 md 文件")

        # ③ 长任务超时：取消 + 终止外部子进程；提前停止不得误判
        sys.path.insert(0, str(ROOT))
        try:
            import app as app_mod
            from unittest import mock

            child = mock.MagicMock()
            child.poll.return_value = None
            job = app_mod.Job([], "")
            job.register_child(child)
            stop = app_mod.start_job_watchdog(job, 0.05)
            self.assertIsNotNone(stop)
            self.assertIsNotNone(job.deadline)
            time.sleep(0.25)
            self.assertIs(job.timed_out, True, "超时未触发")
            self.assertIs(job.cancelled, True, "超时未收敛到取消")
            child.terminate.assert_called()
            stop.set()

            job2 = app_mod.Job([], "")
            stop2 = app_mod.start_job_watchdog(job2, 0.05)
            stop2.set()
            time.sleep(0.15)
            self.assertIs(job2.timed_out, False,
                          "任务已提前结束却仍被判超时")

            child.poll.return_value = 1  # 已退出的子进程不该再 terminate
            self.assertEqual(job.terminate_children(), 0)
        finally:
            sys.path.remove(str(ROOT))
        self.assertIn("job.terminate_children()",
                      (ROOT / "app.py").read_text(encoding="utf-8"),
                      "取消链路未终止外部工具子进程")

    # ------------------------------------------------------------------ #
    # S2a 公共夹具：用标准库现场造一个真实 OOXML 包，绝不依赖 samples/
    # ------------------------------------------------------------------ #
    def _s2a_make_docx(self, path: Path, *, with_body=True,
                       with_comments=True, with_revisions=True) -> Path:
        import zipfile
        ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        paras = []
        if with_body:
            paras.append('<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
                         '<w:r><w:t>验收标题</w:t></w:r></w:p>')
            paras.append('<w:p><w:commentRangeStart w:id="1"/>'
                         '<w:r><w:t>正文第一段</w:t></w:r>'
                         '<w:commentRangeEnd w:id="1"/>'
                         '<w:r><w:commentReference w:id="1"/></w:r></w:p>')
        if with_revisions:
            paras.append('<w:p><w:ins w:author="张三" w:date="2026-11-15T10:00:00Z">'
                         '<w:r><w:t>新增文字</w:t></w:r></w:ins>'
                         '<w:del w:author="李四"><w:r><w:delText>删除文字'
                         '</w:delText></w:r></w:del></w:p>')
        doc = ('<w:document xmlns:w="%s"><w:body>%s</w:body></w:document>'
               % (ns, "".join(paras)))
        comments = ('<w:comments xmlns:w="%s"><w:comment w:id="1" w:author="王五" '
                    'w:date="2026-11-15T11:00:00Z"><w:p><w:r><w:t>这是一条批注'
                    '</w:t></w:r></w:p></w:comment></w:comments>' % ns)
        with zipfile.ZipFile(str(path), "w") as zf:
            zf.writestr("[Content_Types].xml", "<Types/>")
            zf.writestr("word/document.xml", doc)
            if with_comments:
                zf.writestr("word/comments.xml", comments)
        return path

    # ------------------------------------------------------------------ #
    # 35) S2a：Word 输入增强的解析 / 产物 / 诚实降级契约
    # ------------------------------------------------------------------ #
    def test_35_s2a_word_input_contract(self):
        sys.path.insert(0, str(ROOT))
        try:
            import format_registry as reg
            import media_runtime as rt
            import word_input as wi
        finally:
            sys.path.remove(str(ROOT))
        from unittest import mock

        # ① 注册表是 S2a 支持格式的唯一写者；冻结内核测试原样保留
        self.assertEqual(reg.WORD_INPUT_EXTS, {".doc", ".docx"})
        self.assertIs(reg.is_word_input(".docx"), True)
        self.assertIs(reg.is_word_input(".xlsx"), False)
        self.assertEqual(reg.word_kind(".doc"), "legacy")
        self.assertEqual(reg.word_kind(".docx"), "ooxml")
        self.assertIn("import extract", (ROOT / "format_registry.py").read_text(
            encoding="utf-8"))
        self.assertNotIn("import extract", (ROOT / "word_input.py").read_text(
            encoding="utf-8"), "S2a 不得回写 / 依赖冻结内核的解析流水线")
        frozen_tests = (ROOT / "test_extract.py").read_text(encoding="utf-8")
        self.assertIn("def test_06_deferred_media", frozen_tests)
        self.assertIn("def test_11_video_redline", frozen_tests)

        # ② OOXML 增量：批注（含锚定段落）/ 插入 / 删除 / 表格
        src = self._s2a_make_docx(self.tmp / "sample.docx")
        parsed = wi.parse_ooxml(src)
        self.assertEqual(len(parsed["blocks"]), 3)
        self.assertEqual(len(parsed["comments"]), 1)
        self.assertEqual(parsed["comments"][0]["author"], "王五")
        self.assertEqual(parsed["comments"][0]["paragraph"], 2)
        self.assertEqual(parsed["revisions"]["insertions"][0]["text"], "新增文字")
        self.assertEqual(parsed["revisions"]["deletions"][0]["text"], "删除文字")
        self.assertEqual(parsed["revisions"]["total"], 2)

        # ③ 产物：8 字段 src 注释 + 块级锚点 + 三区块，且冻结对账盘零污染
        outdir = self.tmp / "out"
        (outdir / "md").mkdir(parents=True)
        (outdir / "md" / "a.md").write_text("# a\n", encoding="utf-8")
        (outdir / "INDEX.md").write_text("idx\n", encoding="utf-8")
        (outdir / "MERGED.md").write_text("merged\n", encoding="utf-8")
        before = rt.frozen_snapshot(outdir)
        res = wi.enhance([str(src)], str(outdir))
        self.assertIs(res["ok"], True, res)
        self.assertEqual(res["success"], 1)
        self.assertEqual(res["failed"], 0)
        self.assertIs(res["frozen_unchanged"], True)
        self.assertTrue(rt.frozen_unchanged(before, outdir),
                        "S2a 污染了阶段 1 的 md/ 对账盘")
        md_path = Path(res["path"])
        self.assertEqual(md_path.parent.name, rt.DERIVED_DIRNAME)
        md = md_path.read_text(encoding="utf-8")
        for key in ("src:", "path:", "format:", "converter:", "extracted:",
                    "size:", "sha256:", "anchors:"):
            self.assertIn(key, md, "S2a 产物缺少 8 字段中的 %s" % key)
        self.assertIsNotNone(re.search(r"sha256: [0-9a-f]{64}", md))
        self.assertRegex(md, r"<!--\s*anchor:\s*doc_[0-9a-f]{12}\s*\|")
        for section in ("## 文档信息", "## 正文", "## 批注", "## 修订"):
            self.assertIn(section, md)
        self.assertIn("这是一条批注", md)
        self.assertIn("新增文字", md)
        self.assertIn("删除文字", md)
        prov = rt.read_provenance(outdir)
        self.assertEqual(len(prov["entries"]), 1)
        self.assertEqual(prov["entries"][0]["status"], "成功")

        # ④ 加密：只做正向证据识别，单列「待人工授权」，绝不破译 / 绝不产 md
        secret = self.tmp / "secret.doc"
        secret.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 512
                           + "EncryptedPackage".encode("utf-16-le")
                           + b"\x00" * 128)
        ins = wi.inspect([str(secret)])
        self.assertEqual(ins["items"][0]["status"], wi.STATUS_NEEDS_AUTH)
        self.assertIn("待人工授权", ins["items"][0]["error"])
        enc = wi.enhance([str(secret)], str(outdir))
        self.assertIs(enc["ok"], False)
        self.assertEqual(enc["success"], 0)
        self.assertEqual(enc["results"][0]["status"], wi.STATUS_NEEDS_AUTH)
        self.assertEqual(len(list((outdir / "derived").glob("*.md"))), 1,
                         "加密文件竟产出了 md")

        # ⑤ 损坏容器 = 失败（不是加密）；空文档拒绝写空 md
        broken = self.tmp / "broken.docx"
        broken.write_bytes(b"PK\x03\x04" + b"\x00" * 64)
        self.assertEqual(wi.inspect([str(broken)])["items"][0]["status"],
                         wi.STATUS_FAILED)
        empty = self._s2a_make_docx(
            self.tmp / "empty.docx",
            with_body=False, with_comments=False, with_revisions=False)
        empty_res = wi.enhance([str(empty)], str(outdir))
        self.assertIs(empty_res["ok"], False)
        self.assertIn("拒绝写空 md", empty_res["results"][0]["error"])

        # ⑥ .doc 旧格式缺工具：诚实「未启用」，零 md 产出（不依赖本机是否装 LO）
        legacy = self.tmp / "legacy.doc"
        legacy.write_bytes(b"fake legacy word binary")
        fake_tool = {"available": False, "path": "", "version": "",
                     "reason": "本机未找到 soffice", "name": "soffice"}
        with mock.patch.object(wi, "probe_soffice", return_value=fake_tool):
            cap = wi.capability()
            self.assertIs(cap["ooxml"]["enabled"], True)
            self.assertIs(cap["legacy_doc"]["enabled"], False)
            self.assertIs(cap["encryption"]["enabled"], False,
                          "加密能力不得被标记为已启用")
            legacy_res = wi.enhance([str(legacy)], str(outdir))
        self.assertIs(legacy_res["ok"], False)
        self.assertEqual(legacy_res["results"][0]["status"], wi.STATUS_UNAVAILABLE)
        self.assertIn("未启用", legacy_res["results"][0]["error"])
        self.assertEqual(len(list((outdir / "derived").glob("*.md"))), 1,
                         "缺工具时竟产出了 md")

        # ⑦ 新模块纳入编译门禁与冻结打包清单
        self.assertIn("word_input.py",
                      (ROOT / "tools" / "check_release.py").read_text(encoding="utf-8"))
        self.assertIn("'word_input'",
                      (ROOT / "build.spec").read_text(encoding="utf-8"))

    # ------------------------------------------------------------------ #
    # 36) S2a：HTTP 端点、能力状态与 UI 契约
    # ------------------------------------------------------------------ #
    def test_36_s2a_word_http_and_ui(self):
        srv = self.start()

        # ① 探测端点增量字段：不改写 S1 的 capabilities / tools 结构
        status, probe = srv.get_json("/api/tools/probe")
        self.assertEqual(status, 200)
        self.assertIs(probe["ok"], True)
        self.assertEqual(set(probe["tools"]), {"ffmpeg", "whisper", "yt-dlp"})
        self.assertIs(probe["capabilities"]["media_transcribe"]["enabled"], False)
        wi = probe["word_input"]
        self.assertIs(wi["enabled"], True)
        self.assertIs(wi["ooxml"]["enabled"], True)
        self.assertIs(wi["encryption"]["enabled"], False)
        self.assertIn("enabled", wi["legacy_doc"])

        # ② 只读预检端点：不写任何文件
        src = self._s2a_make_docx(self.tmp / "http.docx")
        status, ins = srv.post_json("/api/word/inspect", {"inputs": [str(src)]})
        self.assertEqual(status, 200, ins)
        self.assertIs(ins["ok"], True)
        self.assertEqual(ins["total"], 1)
        self.assertEqual(ins["ready"], 1)
        self.assertEqual(ins["items"][0]["comments"], 1)
        self.assertEqual(ins["items"][0]["revisions"], 2)
        self.assertFalse((self.tmp / "derived").exists(),
                         "预检端点不应创建 derived 目录")

        # ③ 增强端点：真实 HTTP 产出 derived 产物，冻结对账盘一动不动
        outdir = self.tmp / "out"
        (outdir / "md").mkdir(parents=True)
        (outdir / "md" / "a.md").write_text("# a\n", encoding="utf-8")
        (outdir / "MERGED.md").write_text("merged\n", encoding="utf-8")
        status, res = srv.post_json(
            "/api/word/enhance", {"inputs": [str(src)], "outdir": str(outdir)})
        self.assertEqual(status, 200, res)
        self.assertIs(res["ok"], True, res)
        self.assertEqual(res["success"], 1)
        self.assertIs(res["frozen_unchanged"], True)
        produced = Path(res["path"])
        self.assertTrue(produced.is_file())
        self.assertEqual(produced.parent.name, "derived")
        self.assertIn("## 批注", produced.read_text(encoding="utf-8"))
        self.assertEqual([p.name for p in (outdir / "md").glob("*.md")], ["a.md"])

        # ④ 缺工具 / 加密 / 不支持后缀都走诚实回显，且未知端点仍是 404 JSON
        legacy = self.tmp / "legacy.doc"
        legacy.write_bytes(b"fake legacy word binary")
        text = self.tmp / "note.txt"
        text.write_text("hello\n", encoding="utf-8")
        status, mixed = srv.post_json(
            "/api/word/enhance",
            {"inputs": [str(src), str(legacy), str(text)], "outdir": str(outdir)})
        self.assertEqual(status, 200, mixed)
        self.assertIs(mixed["ok"], True, mixed)
        self.assertEqual(mixed["total"], 3)
        self.assertGreaterEqual(mixed["failed"], 2)
        statuses = {r["name"]: r["status"] for r in mixed["results"]}
        self.assertEqual(statuses["note.txt"], "不支持")
        self.assertIn(statuses["legacy.doc"], ("未启用", "失败"))
        self.assertIn("warning", mixed, "部分成功必须显式提示，不能宣称全部完成")
        status, unknown = srv.post_json("/api/word/nope", {})
        self.assertEqual(status, 404)
        self.assertIs(unknown["ok"], False)

        # ⑤ UI 入口与降级文案；S1 的音视频判定行原样保留
        html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        app_src = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('id="btnWordEnhance"', html)
        self.assertIn("/api/word/enhance", js)
        self.assertIn("doWordEnhance", js)
        self.assertIn("wi.enabled", js)
        self.assertIn("el.btnTranscribe.disabled = !on || !mediaOn", js,
                      "S1 的音视频诚实降级判定被改写")
        self.assertIn('path == "/api/word/enhance"', app_src)
        self.assertIn('path == "/api/word/inspect"', app_src)
        self.assertIn("_api_transcribe", app_src)
        self.assertIn("阶段 3 音视频转写需专用转写器", app_src,
                      "S3 空心占位被提前填充或改写")

    def _s2b_write_md(self, name: str, body: str) -> Path:
        """构造一份带 8 字段来源注释与块级锚点的真实 Markdown。"""
        sys.path.insert(0, str(ROOT))
        try:
            import media_runtime as media_rt
        finally:
            sys.path.remove(str(ROOT))
        path = self.tmp / name
        path.write_text("", encoding="utf-8")
        header = media_rt.source_comment(
            path, ".md", "精核 MD→DOCX 导出 v1（标准库 zipfile+ElementTree）",
            ["block"])
        path.write_text(header + "\n" + body, encoding="utf-8")
        return path

    def test_37_s2b_word_export_ooxml_contract(self):
        import zipfile
        import xml.etree.ElementTree as ET
        sys.path.insert(0, str(ROOT))
        try:
            import extract
            import format_registry as reg
            import media_runtime as rt
            import media_tools
            import word_input as wi
            import word_export as we
        finally:
            sys.path.remove(str(ROOT))

        # ① 注册表是 S2b 输入后缀的唯一写者；冻结内核仍原样
        self.assertEqual(reg.WORD_EXPORT_INPUT_EXTS, {".md", ".markdown"})
        self.assertEqual(reg.WORD_EXPORT_SUFFIX, ".docx")
        self.assertIs(reg.is_word_export_input(".md"), True)
        self.assertIs(reg.is_word_export_input(".docx"), False)
        self.assertNotIn("import extract", (ROOT / "word_export.py").read_text(
            encoding="utf-8"), "S2b 不得依赖冻结内核的提取流水线")
        frozen_tests = (ROOT / "test_extract.py").read_text(encoding="utf-8")
        self.assertIn("def test_06_deferred_media", frozen_tests)
        self.assertIn("def test_11_video_redline", frozen_tests)
        self.assertIs(we.capability()["enabled"], True)
        # S1 的 capabilities() 是「占位清单」，被 test_33 锁死为全未启用；
        # S2b 不改写它，真实状态走 /api/tools/probe 顶层增量字段。
        caps = media_tools.capabilities()
        self.assertTrue(all(not v["enabled"] for v in caps.values()))
        self.assertIs(caps["word_export"]["enabled"], False)

        body = (
            "# 标题一 · 中文\n\n"
            "正文 A & B <tag> \"双引号\" '单引号' 100% 与 **粗体**、`代码`。\n\n"
            "- 无序项\n1. 有序项\n\n> 引用行\n\n"
            "| 列A | 列B |\n| --- | --- |\n| 1 | 2 |\n\n"
            "```\nprint(\"hello & <world>\")\n```\n\n"
            "<!-- anchor: doc_abcdef123456 | block: 1 -->\n\n---\n\n"
            "## 末尾小节\n")
        self.assertEqual({b["kind"] for b in we.parse_markdown(body)},
                         {"heading", "para", "list", "quote", "table",
                          "code", "comment", "hr"})

        src = self._s2b_write_md("sample.md", body)
        outdir = self.tmp / "out"
        (outdir / "md").mkdir(parents=True)
        (outdir / "md" / "a.md").write_text("# a\n", encoding="utf-8")
        (outdir / "INDEX.md").write_text("idx\n", encoding="utf-8")
        (outdir / "MERGED.md").write_text("merged\n", encoding="utf-8")
        before = rt.frozen_snapshot(outdir)

        # ② 导出：8 个部件齐全、每个 XML 可解析、zip 无损坏
        res = we.export([str(src)], str(outdir))
        self.assertIs(res["ok"], True, res)
        self.assertEqual(res["success"], 1)
        self.assertIs(res["frozen_unchanged"], True, res)
        path = Path(res["path"])
        self.assertEqual(path.parent.name, rt.DERIVED_DIRNAME)
        self.assertEqual(path.suffix, ".docx")
        required = {"[Content_Types].xml", "_rels/.rels", "word/document.xml",
                    "word/_rels/document.xml.rels", "word/styles.xml",
                    "word/settings.xml", "docProps/core.xml", "docProps/app.xml"}
        with zipfile.ZipFile(str(path)) as zf:
            self.assertTrue(required.issubset(set(zf.namelist())))
            self.assertIsNone(zf.testzip(), "docx 压缩包存在损坏成员")
            for name in zf.namelist():
                if name.endswith((".xml", ".rels")):
                    try:
                        ET.fromstring(zf.read(name))
                    except ET.ParseError as exc:
                        self.fail("S2b 部件 XML 不合法：%s（%s）" % (name, exc))
            core = zf.read("docProps/core.xml").decode("utf-8")
            self.assertIn("src:", core)
            self.assertIn("sha256:", core)

        # ③ 产物能被反向解析回 Word 结构；来源注释 / 锚点 / 特殊字符不丢
        parsed = wi.parse_ooxml(path)
        joined = "\n".join(b["text"] for b in parsed["blocks"])
        for needle in ("<!-- source:", "<!-- src:", "<!-- anchor:",
                       "标题一 · 中文", "A & B <tag> \"双引号\" '单引号' 100%",
                       "print(\"hello & <world>\")", "列A", "末尾小节"):
            self.assertIn(needle, joined, "导出丢失了：%s" % needle)
        self.assertIsNotNone(re.search(r"doc_[0-9a-f]{12}", joined))
        self.assertRegex(joined, r"sha256: [0-9a-f]{64}")

        # ④ 阶段 1 冻结对账盘零污染：实盘数与文件内容都不变
        self.assertTrue(rt.frozen_unchanged(before, outdir))
        self.assertEqual([p.name for p in (outdir / "md").glob("*.md")], ["a.md"])
        self.assertEqual((outdir / "MERGED.md").read_text(encoding="utf-8"),
                         "merged\n")
        self.assertEqual(list((outdir / "derived").glob("*.part")), [],
                         "原子替换后残留了 .part 半成品")

        # ⑤ 默认输入：不显式给 inputs 时，只读收集 MERGED.md
        auto = we.export([], str(outdir))
        self.assertIs(auto["auto_inputs"], True)
        self.assertIs(auto["ok"], True, auto)
        self.assertEqual(auto["results"][0]["name"], "MERGED.md")

        # ⑥ 失败路径一律零 docx：不存在 / 非 md / 空白 / 超行上限
        before_count = len(list((outdir / "derived").glob("*.docx")))
        blank = self.tmp / "blank.md"
        blank.write_text("\n\n", encoding="utf-8")
        huge = self.tmp / "huge.md"
        huge.write_text("x\n" * (we.MAX_LINES + 1), encoding="utf-8")
        bad_txt = self.tmp / "note.txt"
        bad_txt.write_text("hello\n", encoding="utf-8")
        failed = we.export([str(self.tmp / "nope.md"), str(bad_txt),
                            str(blank), str(huge)], str(outdir))
        self.assertIs(failed["ok"], False)
        self.assertEqual(failed["success"], 0)
        self.assertEqual(failed["failed"], 4)
        statuses = {r["name"]: r["status"] for r in failed["results"]}
        self.assertEqual(statuses["note.txt"], "不支持")
        self.assertEqual(statuses["blank.md"], "失败")
        self.assertIn("拒绝写空 docx",
                      next(r["error"] for r in failed["results"]
                           if r["name"] == "blank.md"))
        self.assertEqual(len(list((outdir / "derived").glob("*.docx"))),
                         before_count, "失败批次竟产出了 docx")

        # ⑦ 部分成功必须显式 warning；provenance 保留历史条目不覆盖
        mixed = we.export([str(src), str(bad_txt)], str(outdir))
        self.assertIs(mixed["ok"], True)
        self.assertEqual(mixed["failed"], 1)
        self.assertIn("warning", mixed)
        prov = rt.read_provenance(outdir)
        self.assertGreaterEqual(len(prov["entries"]), 2)
        self.assertTrue(any(e.get("capability") == "word_export"
                            for e in prov["entries"]))

    def test_38_s2b_word_export_http_and_ui(self):
        import zipfile
        srv = self.start()

        # ① 探测端点：顶层增量字段，S1 的 tools / capabilities 结构原样
        status, probe = srv.get_json("/api/tools/probe")
        self.assertEqual(status, 200)
        self.assertEqual(set(probe["tools"]), {"ffmpeg", "whisper", "yt-dlp"})
        self.assertIs(probe["capabilities"]["media_transcribe"]["enabled"], False)
        self.assertIs(probe["word_input"]["enabled"], True)
        self.assertIs(probe["word_export"]["enabled"], True)
        self.assertEqual(probe["word_export"]["output"]["suffix"], ".docx")
        self.assertIs(probe["capabilities"]["word_export"]["enabled"], False,
                      "S1 占位清单不得改写；真实状态以顶层 word_export 为准")

        outdir = self.tmp / "out"
        (outdir / "md").mkdir(parents=True)
        (outdir / "md" / "a.md").write_text("# a\n", encoding="utf-8")
        (outdir / "MERGED.md").write_text("# merged\n\n内容\n", encoding="utf-8")
        src = self._s2b_write_md("http.md", "# HTTP 标题\n\n段落 & <标签>\n")

        # ② 真实 HTTP 导出：产物在 derived/，冻结对账盘一动不动
        status, res = srv.post_json(
            "/api/word/export", {"inputs": [str(src)], "outdir": str(outdir)})
        self.assertEqual(status, 200, res)
        self.assertIs(res["ok"], True, res)
        self.assertIs(res["frozen_unchanged"], True)
        produced = Path(res["path"])
        self.assertTrue(produced.is_file())
        self.assertEqual(produced.parent.name, "derived")
        with zipfile.ZipFile(str(produced)) as zf:
            self.assertIn("word/document.xml", zf.namelist())
        self.assertEqual([p.name for p in (outdir / "md").glob("*.md")], ["a.md"])
        self.assertEqual((outdir / "MERGED.md").read_text(encoding="utf-8"),
                         "# merged\n\n内容\n")

        # ③ 混合批次：部分成功回 warning，失败项逐条给出可读原因
        txt = self.tmp / "note.txt"
        txt.write_text("hello\n", encoding="utf-8")
        status, mixed = srv.post_json(
            "/api/word/export",
            {"inputs": [str(src), str(txt)], "outdir": str(outdir)})
        self.assertEqual(status, 200, mixed)
        self.assertIs(mixed["ok"], True)
        self.assertEqual(mixed["failed"], 1)
        self.assertIn("warning", mixed)
        self.assertEqual({r["name"]: r["status"] for r in mixed["results"]}
                         ["note.txt"], "不支持")

        # ④ 空目录 / 空输入：诚实失败，不写空 docx；未知端点仍 404 JSON
        empty_out = self.tmp / "empty_out"
        empty_out.mkdir()
        status, none = srv.post_json(
            "/api/word/export", {"inputs": [], "outdir": str(empty_out)})
        self.assertEqual(status, 200, none)
        self.assertIs(none["ok"], False)
        self.assertIn("未找到可导出的 Markdown", none["error"])
        self.assertFalse((empty_out / "derived").exists() or
                         list((empty_out / "derived").glob("*.docx")),
                         "空输入竟产出了目录或 docx")
        status, unknown = srv.post_json("/api/word/export/nope", {})
        self.assertEqual(status, 404)
        self.assertIs(unknown["ok"], False)

        # ⑤ UI：禁用占位已放开，S1 音视频诚实降级判定仍原样保留
        html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        app_src = (ROOT / "app.py").read_text(encoding="utf-8")
        gate = (ROOT / "tools" / "check_release.py").read_text(encoding="utf-8")
        spec = (ROOT / "build.spec").read_text(encoding="utf-8")
        self.assertNotIn("导出 Word（规划中）", html)
        self.assertIn('id="btnExportDocx"', html)
        self.assertIn("/api/word/export", js)
        self.assertIn("doWordExport", js)
        self.assertIn("word_export", js)
        self.assertIn('path == "/api/word/export"', app_src)
        self.assertIn('data["word_export"]', app_src)
        self.assertIn("el.btnTranscribe.disabled = !on || !mediaOn", js,
                      "S1 的音视频诚实降级判定被改写")
        self.assertIn("阶段 3 音视频转写需专用转写器", app_src,
                      "S3 空心占位被提前填充或改写")
        self.assertIn("word_export.py", gate)
        self.assertIn("'word_export'", spec,
                      "新模块未加入 PyInstaller hiddenimports")


    # ------------------------------------------------------------------ #
    # S3 公共夹具：本机工具的「假探测结果」与 mock 转写后端
    # ------------------------------------------------------------------ #
    @staticmethod
    def _s3_fake_cap(*, enabled=True, whisper_version="1.2.3",
                     ffmpeg_version="7.0.2") -> dict:
        return {
            "name": "audio_transcribe",
            "enabled": enabled,
            "capability": "available" if enabled else "unavailable",
            "tools": {
                "whisper": {"available": enabled, "path": "whisper",
                            "version": whisper_version, "reason": "可用"},
                "ffmpeg": {"available": enabled, "path": "ffmpeg",
                           "version": ffmpeg_version, "reason": "可用"},
            },
            "missing": [] if enabled else ["whisper", "ffmpeg"],
            "reason": ("可用" if enabled else
                       "未启用：本机未找到 whisper / ffmpeg，请安装后重试"),
        }

    @staticmethod
    def _s3_runner(payload=None, *, rc=0, write=True, raw_text=None):
        """模拟本机 whisper：把 JSON 写进 --output_dir；ffmpeg 只回元数据。"""
        def runner(argv):
            if "-hide_banner" in argv:
                return {"returncode": 1, "stdout": "", "stderr":
                        "  Duration: 00:00:15.50, start: 0.000000\n"
                        "    Stream #0:0: Audio: mp3, 44100 Hz, stereo, fltp"}
            if write:
                outd = Path(argv[argv.index("--output_dir") + 1])
                inp = Path(argv[1])
                content = (raw_text if raw_text is not None else
                           json.dumps(payload, ensure_ascii=False))
                (outd / (inp.stem + ".json")).write_text(content, encoding="utf-8")
            return {"returncode": rc, "stdout": "",
                    "stderr": "工具报错" if rc else ""}
        return runner

    @staticmethod
    def _s3_frozen_outdir(root: Path) -> Path:
        out = root / "out"
        (out / "md").mkdir(parents=True)
        (out / "md" / "a.md").write_text("# a\n", encoding="utf-8")
        (out / "INDEX.md").write_text("idx\n", encoding="utf-8")
        (out / "MERGED.md").write_text("merged\n", encoding="utf-8")
        return out

    # ------------------------------------------------------------------ #
    # 39) S3：音频 ASR 适配器 / 产物 / 诚实降级契约
    # ------------------------------------------------------------------ #
    def test_39_s3_audio_asr_contract(self):
        sys.path.insert(0, str(ROOT))
        try:
            import audio_transcribe as at
            import media_runtime as rt
            import format_registry as reg
            import media_tools as mt
        finally:
            sys.path.remove(str(ROOT))
        from unittest import mock

        good_payload = {
            "text": "中文 转写", "language": "zh",
            "segments": [
                {"start": 0.0, "end": 8.24, "text": " 这是第一段中文转写 "},
                {"start": 8.24, "end": 15.5, "text": "第二段 & <标签>"},
                {"start": 16, "end": 15, "text": "非法段应丢弃"},
            ],
        }
        audio = self.tmp / "voice.mp3"
        audio.write_bytes(b"ID3 fake audio bytes")

        # ① 冻结内核 / 注册表 / 时间戳与分段解析
        frozen_tests = (ROOT / "test_extract.py").read_text(encoding="utf-8")
        self.assertIn("def test_06_deferred_media", frozen_tests)
        self.assertIn("def test_11_video_redline", frozen_tests)
        asr_src = (ROOT / "audio_transcribe.py").read_text(encoding="utf-8")
        self.assertNotIn("import extract", asr_src,
                         "S3 不得依赖冻结内核的解析流水线")
        self.assertIn("format_registry.MEDIA_AUDIO", asr_src,
                      "必须显式用 MEDIA_AUDIO 过滤，不得沿用含视频的 _STAGE3_AUDIO_EXT")
        self.assertEqual(reg.media_kind(".mp3"), "audio")
        self.assertEqual(reg.media_kind(".mp4"), "video")
        self.assertEqual(at.format_timestamp(8.24), "00:00:08.240")
        self.assertEqual(at.format_timestamp(3661.5), "01:01:01.500")
        self.assertEqual(at.format_timestamp(float("nan")), "00:00:00.000")
        segs, meta = at.parse_segments(good_payload)
        self.assertEqual(len(segs), 2)
        self.assertEqual(meta["skipped"], 1, "end<start 的非法段必须丢弃")
        self.assertEqual(meta["language"], "zh")

        # ② 视频拒收（红线 2）：分类先于存在性判断，逐条显式「不支持」
        videos = []
        for ext in (".mp4", ".mov", ".mkv"):
            p = self.tmp / ("clip" + ext)
            p.write_bytes(b"\x00\x00\x00\x18ftypmp42")
            videos.append(str(p))
        insp = at.inspect(videos)
        self.assertEqual(insp["total"], 3)
        self.assertEqual(insp["ready"], 0)
        for item in insp["items"]:
            self.assertEqual(item["status"], at.STATUS_UNSUPPORTED)
            self.assertIn("S4", item["error"])
            self.assertIn("红线 2", item["error"])

        # ③ 缺工具：诚实「未启用」，零 md、连 derived/ 都不创建
        out0 = self.tmp / "out_unavailable"
        out0.mkdir()
        with mock.patch.object(at, "capability",
                               return_value=self._s3_fake_cap(enabled=False)):
            unavailable = at.transcribe([str(audio)], str(out0))
        self.assertIs(unavailable["ok"], False)
        self.assertEqual(unavailable["capability"], "unavailable")
        self.assertIn("未启用", unavailable["error"])
        self.assertEqual(unavailable["results"][0]["status"], at.STATUS_UNAVAILABLE)
        self.assertFalse((out0 / "derived").exists(), "缺工具竟创建了 derived 目录")
        self.assertEqual(list(out0.rglob("*.md")), [])

        # ④ mock 后端真实样本：8 字段 src / 锚点 / 时间戳 / 三区块 / 冻结盘隔离
        outdir = self._s3_frozen_outdir(self.tmp)
        before = rt.frozen_snapshot(outdir)
        with mock.patch.object(at, "capability",
                               return_value=self._s3_fake_cap()):
            res = at.transcribe([str(audio)], str(outdir),
                                runner=self._s3_runner(good_payload))
        self.assertIs(res["ok"], True, res)
        self.assertEqual(res["success"], 1)
        self.assertEqual(res["results"][0]["segments"], 2)
        self.assertIs(res["frozen_unchanged"], True)
        self.assertTrue(rt.frozen_unchanged(before, outdir),
                        "S3 污染了阶段 1 的 md/ 对账盘")
        produced = Path(res["path"])
        self.assertEqual(produced.parent.name, rt.DERIVED_DIRNAME)
        md = produced.read_text(encoding="utf-8")
        for key in ("src:", "path:", "format:", "converter:", "extracted:",
                    "size:", "sha256:", "anchors:"):
            self.assertIn(key, md, "S3 产物缺少 8 字段中的 %s" % key)
        self.assertIsNotNone(re.search(r"sha256: [0-9a-f]{64}", md))
        self.assertRegex(md, r"<!--\s*anchor:\s*doc_[0-9a-f]{12}\s*\|")
        self.assertIn("time: 00:00:00.000-00:00:08.240", md)
        self.assertIn("[00:00:00.000 → 00:00:08.240] 这是第一段中文转写", md)
        self.assertIn("第二段 & <标签>", md)
        self.assertIn("whisper 1.2.3 + ffmpeg 7.0.2", md)
        self.assertNotIn("非法段应丢弃", md)
        for section in ("## 文档信息", "## 音轨转写", "## 转写元数据"):
            self.assertIn(section, md)
        self.assertEqual([p.name for p in (outdir / "md").glob("*.md")], ["a.md"])
        self.assertEqual((outdir / "MERGED.md").read_text(encoding="utf-8"), "merged\n")
        self.assertEqual(list((outdir / "derived").glob("*.part")), [],
                         ".part 半成品未清理")
        prov = rt.read_provenance(outdir)
        self.assertEqual(len(prov["entries"]), 1)
        self.assertEqual(prov["entries"][0]["capability"], "audio_transcribe")
        self.assertEqual(prov["entries"][0]["segments"], 2)

        # ⑤ 伪转写防护：空分段 / 缺 segments / 非法 JSON / 无输出 / 非 0 退出
        bad_cases = [
            ("空分段", self._s3_runner({"text": "", "segments": []})),
            ("缺少 segments", self._s3_runner({"text": "只有全文占位"})),
            ("非法 JSON", self._s3_runner(raw_text="{not json")),
            ("无 json 输出", self._s3_runner(write=False)),
            ("非 0 退出", self._s3_runner(good_payload, rc=1)),
        ]
        for i, (label, bad_runner) in enumerate(bad_cases):
            sub = self.tmp / ("bad_%d" % i)
            sub.mkdir()
            with mock.patch.object(at, "capability",
                                   return_value=self._s3_fake_cap()):
                bad = at.transcribe([str(audio)], str(sub), runner=bad_runner)
            self.assertIs(bad["ok"], False, "%s 竟宣称成功" % label)
            self.assertEqual(list((sub / "derived").glob("*.md")) if
                             (sub / "derived").exists() else [], [],
                             "%s 竟产出了 md" % label)
            self.assertNotIn("无语音说明", str(bad))
        with mock.patch.object(at, "capability",
                               return_value=self._s3_fake_cap()):
            no_speech = at.transcribe(
                [str(audio)], str(self.tmp / "bad_no_speech"),
                runner=self._s3_runner({"text": "", "segments": []}))
        self.assertEqual(no_speech["results"][0]["status"], at.STATUS_NO_SPEECH)
        self.assertIn("拒绝写空 md", no_speech["results"][0]["error"])

        # ⑥ provenance 追加而非覆盖（S2b 历史条目必须还在）
        rt.write_provenance(outdir, entries=[
            {"capability": "word_export", "name": "old.docx", "status": "成功"}])
        with mock.patch.object(at, "capability",
                               return_value=self._s3_fake_cap()):
            again = at.transcribe([str(audio)], str(outdir),
                                  runner=self._s3_runner(good_payload))
        self.assertIs(again["ok"], True)
        caps = {e.get("capability") for e in
                rt.read_provenance(outdir)["entries"]}
        self.assertIn("word_export", caps)
        self.assertIn("audio_transcribe", caps)

        # ⑦ 取消收敛 + 外部工具进程树终止
        with mock.patch.object(at, "capability",
                               return_value=self._s3_fake_cap()):
            cancelled = at.transcribe(
                [str(audio)], str(self.tmp / "out_cancel"),
                runner=self._s3_runner(good_payload),
                cancel_check=lambda: True)
        self.assertIs(cancelled["ok"], False)
        self.assertIs(cancelled["cancelled"], True)
        self.assertEqual(cancelled["results"][0]["status"], at.STATUS_CANCELLED)
        self.assertEqual(list((self.tmp / "out_cancel").rglob("*.md")), [])
        long_proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            with mock.patch.object(mt.subprocess, "run") as mocked:
                self.assertIs(mt.terminate_process_tree(long_proc), True)
                argv = mocked.call_args[0][0]
                self.assertIn("/T", argv, "未用 /T 杀整棵进程树")
                self.assertIn("/F", argv)
        finally:
            long_proc.terminate()
            long_proc.wait(timeout=5)
        self.assertIs(mt.terminate_process_tree(object()), False,
                      "非 Popen 不得误触进程树终止")

        # ⑧ 新模块纳入编译门禁与冻结打包清单
        self.assertIn("audio_transcribe.py",
                      (ROOT / "tools" / "check_release.py").read_text(
                          encoding="utf-8"))
        self.assertIn("'audio_transcribe'",
                      (ROOT / "build.spec").read_text(encoding="utf-8"))

    # ------------------------------------------------------------------ #
    # 40) S3：HTTP 端点、能力状态与 UI 契约
    # ------------------------------------------------------------------ #
    def test_40_s3_audio_http_and_ui(self):
        srv = self.start()

        # ① 探测端点：顶层增量字段；S1 占位清单 / 三工具结构原样
        status, probe = srv.get_json("/api/tools/probe")
        self.assertEqual(status, 200)
        self.assertEqual(set(probe["tools"]), {"ffmpeg", "whisper", "yt-dlp"})
        self.assertIn("audio_transcribe", probe)
        # 不硬编码 enabled 的真假：本机是否装 whisper/ffmpeg 随环境变化。
        # 真正要守的是「**不许谎报**」——上层结论必须与实际探测一致。
        _tools_ready = bool(probe["tools"]["whisper"].get("available")
                            and probe["tools"]["ffmpeg"].get("available"))
        self.assertIs(probe["audio_transcribe"]["enabled"], _tools_ready,
                      "audio_transcribe.enabled 与实际工具探测不一致（谎报可用/不可用）")
        self.assertEqual(
            probe["audio_transcribe"]["capability"],
            "available" if _tools_ready else "unavailable")
        self.assertIs(probe["capabilities"]["media_transcribe"]["enabled"], False)
        self.assertIs(probe["capabilities"]["word_export"]["enabled"], False,
                      "S1 占位清单不得改写")
        self.assertIs(probe["word_input"]["enabled"], True)
        self.assertIs(probe["word_export"]["enabled"], True)

        # 刚启动、尚未发起任何转写：状态端点必须是 idle 空事件
        status, st = srv.get_json("/api/audio/status?since=0")
        self.assertEqual(status, 200)
        self.assertEqual(st["state"], "idle")
        self.assertEqual(st["events"], [])

        outdir = self._s3_frozen_outdir(self.tmp)
        audio = self.tmp / "voice.mp3"
        audio.write_bytes(b"ID3 fake audio bytes")
        video = self.tmp / "clip.mp4"
        video.write_bytes(b"\x00\x00\x00\x18ftypmp42")

        # ② 只读预检：视频逐条拒收，零副作用
        status, ins = srv.post_json(
            "/api/audio/inspect", {"inputs": [str(audio), str(video)]})
        self.assertEqual(status, 200)
        self.assertIs(ins["ok"], True)
        by_name = {i["name"]: i for i in ins["items"]}
        self.assertEqual(by_name["clip.mp4"]["status"], "不支持")
        self.assertIn("S4", by_name["clip.mp4"]["error"])
        self.assertFalse((outdir / "derived").exists(), "预检竟创建了 derived 目录")

        # ③ 缺工具诚实降级：零 md、零 derived
        # 用**隔离 PATH** 起一个「找不到 whisper/ffmpeg」的服务实例，
        # 这样降级路径在本机是否装了工具的环境下都能稳定复现（不依赖环境假设）。
        empty_bin = Path(self.tmp) / "empty_bin"
        empty_bin.mkdir(exist_ok=True)
        srv_no_tools = self.start(env_extra={"PATH": str(empty_bin)})
        # 用独立 outdir：前面的成功转写可能已建 derived，混用会污染断言
        outdir_no_tools = Path(self.tmp) / "out_no_tools"
        status, res = srv_no_tools.post_json(
            "/api/audio/transcribe",
            {"inputs": [str(audio)], "outdir": str(outdir_no_tools)})
        self.assertEqual(status, 200, res)
        self.assertIs(res["ok"], False)
        self.assertEqual(res["capability"], "unavailable")
        self.assertIn("未启用", res["error"])
        self.assertFalse((outdir_no_tools / "derived").exists())
        self.assertEqual([p.name for p in (outdir / "md").glob("*.md")], ["a.md"])

        # ④ 视频走音频端点仍显式拒收（不因缺工具被笼统盖掉）
        # 用独立 outdir：前面的成功转写可能已建 derived，混用会污染断言
        outdir_reject = Path(self.tmp) / "out_reject_video"
        status, vr = srv.post_json(
            "/api/audio/transcribe",
            {"inputs": [str(video)], "outdir": str(outdir_reject)})
        self.assertEqual(status, 200)
        self.assertIs(vr["ok"], False)
        self.assertEqual(vr["results"][0]["status"], "不支持")
        # 意图是「该文件没被转写出 md」；provenance 留痕允许存在（失败也留痕是 S3 设计）
        self.assertEqual(list((outdir_reject / "derived").glob("*.md")), [])

        # ⑤ 任务结束后状态必须收敛（不能停在 running）；取消 / 未知端点
        status, st = srv.get_json("/api/audio/status?since=0")
        self.assertEqual(status, 200)
        self.assertIn(st["state"], ("done", "failed", "cancelled"))
        self.assertIs(st["running"], False)
        status, cancel = srv.post_json("/api/audio/cancel", {})
        self.assertEqual(status, 200)
        self.assertIs(cancel["ok"], False)
        status, unknown = srv.post_json("/api/audio/nope", {})
        self.assertEqual(status, 404)
        self.assertIs(unknown["ok"], False)

        # ⑥ UI 与后端接线；S1 空心位与冻结断言原样保留
        html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        app_src = (ROOT / "app.py").read_text(encoding="utf-8")
        gate = (ROOT / "tools" / "check_release.py").read_text(encoding="utf-8")
        spec = (ROOT / "build.spec").read_text(encoding="utf-8")
        self.assertIn('id="btnAudioTranscribe"', html)
        self.assertIn('id="btnAudioCancel"', html)
        for needle in ("/api/audio/transcribe", "/api/audio/status",
                       "/api/audio/cancel", "doAudioTranscribe",
                       "audio_transcribe", "hasAudioInput"):
            self.assertIn(needle, js)
        self.assertIn('path == "/api/audio/transcribe"', app_src)
        self.assertIn('data["audio_transcribe"]', app_src)
        self.assertIn("el.btnTranscribe.disabled = !on || !mediaOn", js,
                      "S1 音视频诚实降级判定被改写")
        self.assertIn("阶段 3 音视频转写需专用转写器", app_src,
                      "S1 空心占位被提前填充或改写")
        self.assertIn("audio_transcribe.py", gate)
        self.assertIn("'audio_transcribe'", spec)

    # ------------------------------------------------------------------ #
    # S4 公共夹具：本机工具的「假探测结果」与 mock 视频后端
    # ------------------------------------------------------------------ #
    @staticmethod
    def _s4_outdir(root: Path, name: str) -> Path:
        out = root / name
        (out / "md").mkdir(parents=True)
        (out / "md" / "a.md").write_text("# a\n", encoding="utf-8")
        (out / "INDEX.md").write_text("idx\n", encoding="utf-8")
        (out / "MERGED.md").write_text("merged\n", encoding="utf-8")
        return out

    @staticmethod
    def _s4_fake_cap(*, enabled=True, with_ffprobe=False) -> dict:
        return {
            "name": "video_transcribe", "enabled": enabled,
            "capability": "available" if enabled else "unavailable",
            "tools": {
                "whisper": {"available": enabled, "path": "whisper",
                            "version": "1.2.3", "reason": "可用"},
                "ffmpeg": {"available": enabled, "path": "ffmpeg",
                           "version": "7.0.2", "reason": "可用"},
                "ffprobe": {"available": with_ffprobe, "path": "ffprobe",
                            "version": "7.0.2" if with_ffprobe else "",
                            "reason": "可用" if with_ffprobe else "未安装"},
            },
            "missing": [] if enabled else ["whisper", "ffmpeg"],
            "reason": ("可用" if enabled else
                       "未启用：本机未找到 whisper / ffmpeg，请安装后重试"),
        }

    @staticmethod
    def _s4_runner(*, probe=None, srt=None, segments=None,
                   ffprobe_json=None, whisper_rc=0) -> object:
        """模拟 ffmpeg / ffprobe / whisper：把 json、srt 写进临时目录。"""
        default_probe = (
            "  Duration: 00:00:20.50, start: 0.000000\n"
            "    Stream #0:0: Video: h264 (High), yuv420p, 1920x1080, 25 fps\n"
            "    Stream #0:1: Audio: aac (LC), 48000 Hz, stereo, fltp\n")
        default_segs = {"text": "视频语音", "language": "zh", "segments": [
            {"start": 0, "end": 8.24, "text": " 第一段中文语音 "},
            {"start": 8.24, "end": 15.5, "text": "第二段 & <标签>"},
            {"start": 16, "end": 15, "text": "非法段应丢弃"}]}
        p_text = default_probe if probe is None else probe
        segs = default_segs if segments is None else segments

        def runner(argv):
            a = list(map(str, argv))
            if "-show_streams" in a:
                if ffprobe_json is None:
                    return {"returncode": 1, "stdout": "", "stderr": "no ffprobe"}
                return {"returncode": 0,
                        "stdout": json.dumps(ffprobe_json, ensure_ascii=False),
                        "stderr": ""}
            if "-c:s" in a:
                if srt is None:
                    return {"returncode": 1, "stdout": "", "stderr": "no subtitle"}
                Path(a[-1]).write_text(srt, encoding="utf-8")
                return {"returncode": 0, "stdout": "", "stderr": ""}
            if "-c:a" in a:
                return {"returncode": 0, "stdout": "", "stderr": ""}
            if "--output_dir" in a:
                outd = Path(a[a.index("--output_dir") + 1])
                (outd / (Path(a[1]).stem + ".json")).write_text(
                    json.dumps(segs, ensure_ascii=False), encoding="utf-8")
                return {"returncode": whisper_rc, "stdout": "",
                        "stderr": "工具报错" if whisper_rc else ""}
            return {"returncode": 1, "stdout": "", "stderr": p_text}
        return runner

    # ------------------------------------------------------------------ #
    # 41) S4：独立 video handler / 三区块 / 伪内容防护 / derived 隔离
    # ------------------------------------------------------------------ #
    def test_41_s4_video_handler_contract(self):
        sys.path.insert(0, str(ROOT))
        try:
            import video_transcribe as vt
            import audio_transcribe as at
            import media_runtime as rt
            import format_registry as reg
        finally:
            sys.path.remove(str(ROOT))
        from unittest import mock

        frozen_tests = (ROOT / "test_extract.py").read_text(encoding="utf-8")
        self.assertIn("def test_06_deferred_media", frozen_tests)
        self.assertIn("def test_11_video_redline", frozen_tests)
        v_src = (ROOT / "video_transcribe.py").read_text(encoding="utf-8")
        a_src = (ROOT / "audio_transcribe.py").read_text(encoding="utf-8")
        self.assertNotIn("import audio_transcribe", v_src,
                         "S4 绝不复用音频转写路径（红线 2）")
        self.assertNotIn("import extract", v_src)
        self.assertNotIn("video_transcribe", a_src,
                         "双向红线：音频 handler 不得反向依赖视频 handler")
        self.assertIn("format_registry.MEDIA_VIDEO", v_src)
        self.assertEqual(reg.media_kind(".mp4"), "video")
        self.assertEqual(reg.media_kind(".mp3"), "audio")

        # 时间戳 / SRT / 分段解析
        self.assertEqual(vt.format_timestamp(8.24), "00:00:08.240")
        self.assertEqual(vt.format_timestamp(float("nan")), "00:00:00.000")
        subs = vt.parse_srt("1\n00:00:00,000 --> 00:00:02,500\n第一条<i>字幕</i>\n\n"
                            "2\n00:00:03,000 --> 00:00:05,240\n第二条\n")
        self.assertEqual(len(subs), 2)
        self.assertEqual(subs[1]["start"], 3.0)
        segs, meta = vt.parse_segments({"segments": [
            {"start": 0, "end": 2, "text": "好"},
            {"start": 5, "end": 4, "text": "非法"}]})
        self.assertEqual(len(segs), 1)
        self.assertEqual(meta["skipped"], 1)

        video = self.tmp / "clip.mp4"
        video.write_bytes(b"\x00\x00\x00\x18ftypmp42 fake video")
        audio = self.tmp / "voice.mp3"
        audio.write_bytes(b"ID3 fake audio")
        # 双向红线：视频拒收音频、音频拒收视频，分类先于存在性判断
        vi = vt.inspect([str(audio)])
        self.assertEqual(vi["items"][0]["status"], vt.STATUS_UNSUPPORTED)
        self.assertIn("S3", vi["items"][0]["error"])
        ai = at.inspect([str(video)])
        self.assertEqual(ai["items"][0]["status"], at.STATUS_UNSUPPORTED)
        self.assertIn("S4", ai["items"][0]["error"])

        # 缺工具：诚实「未启用」，零 md、连 derived/ 都不创建
        out0 = self.tmp / "out_unavailable"
        out0.mkdir()
        with mock.patch.object(vt, "capability",
                               return_value=self._s4_fake_cap(enabled=False)):
            un = vt.transcribe([str(video)], str(out0))
        self.assertIs(un["ok"], False)
        self.assertEqual(un["capability"], "unavailable")
        self.assertIn("未启用", un["error"])
        self.assertFalse((out0 / "derived").exists())

        cap = self._s4_fake_cap()
        srt_text = ("1\n00:00:00,000 --> 00:00:02,500\n真实字幕第一条\n\n"
                    "2\n00:00:03,000 --> 00:00:05,240\n真实字幕第二条\n")
        probe_sub = (
            "  Duration: 00:00:20.50, start: 0.000000\n"
            "    Stream #0:0: Video: h264, 1920x1080, 25 fps\n"
            "    Stream #0:1: Audio: aac, 48000 Hz\n"
            "    Stream #0:2: Subtitle: mov_text\n")

        # ① 音轨 + 字幕轨：三区块齐备 / 8 字段 src / time 锚点 / 冻结盘隔离
        outdir = self._s4_outdir(self.tmp, "out_full")
        before = rt.frozen_snapshot(outdir)
        runner = self._s4_runner(probe=probe_sub, srt=srt_text)
        with mock.patch.object(vt, "capability", return_value=cap):
            res = vt.transcribe([str(video)], str(outdir), runner=runner)
        self.assertIs(res["ok"], True, res)
        self.assertEqual(res["results"][0]["segments"], 2)
        self.assertEqual(res["results"][0]["subtitles"], 2)
        self.assertEqual(res["results"][0]["sections"], 3)
        self.assertIs(res["frozen_unchanged"], True)
        self.assertTrue(rt.frozen_unchanged(before, outdir))
        self.assertEqual(Path(res["path"]).parent.name, rt.DERIVED_DIRNAME)
        md = Path(res["path"]).read_text(encoding="utf-8")
        for key in ("src:", "path:", "format:", "converter:", "extracted:",
                    "size:", "sha256: [0-9a-f]{64}", "anchors:"):
            if "[0-9a-f]{64}" in key:
                self.assertRegex(md, r"sha256: [0-9a-f]{64}")
            else:
                self.assertIn(key, md)
        self.assertRegex(md, r"<!--\s*anchor:\s*doc_[0-9a-f]{12}\s*\|")
        self.assertEqual([x for x in md.splitlines() if x.startswith("## ")],
                         ["## 元数据", "## 音轨转写", "## 画面 / 字幕"])
        self.assertIn("00:00:00.000-00:00:08.240", md)
        self.assertIn("第一段中文语音", md)
        self.assertIn("真实字幕第一条", md)
        self.assertIn("whisper 1.2.3 + ffmpeg 7.0.2", md)
        for bad in ("画面显示", "可以看到", "镜头中", "无语音说明文档"):
            self.assertNotIn(bad, md, "伪画面描述 / 占位正文混入产物")
        self.assertFalse(list((outdir / "derived").glob("*.part")))
        self.assertEqual(sorted(p.name for p in outdir.glob("*.md")),
                         ["INDEX.md", "MERGED.md"])
        self.assertEqual((outdir / "MERGED.md").read_text(encoding="utf-8"),
                         "merged\n")

        # ② 无字幕轨：画面区块只写客观事实，不编造画面内容，仍靠真实分段出 md
        out_nosub = self._s4_outdir(self.tmp, "out_nosub")
        with mock.patch.object(vt, "capability", return_value=cap):
            r2 = vt.transcribe([str(video)], str(out_nosub),
                               runner=self._s4_runner())
        self.assertIs(r2["ok"], True, r2)
        md2 = Path(r2["path"]).read_text(encoding="utf-8")
        self.assertIn("未检测到内嵌字幕轨", md2)
        self.assertIn("不生成画面语义描述", md2)
        self.assertNotIn("真实字幕第一条", md2)
        self.assertEqual(r2["results"][0]["subtitles"], 0)

        # ③ 无音轨但有字幕：音轨区块留客观状态，字幕是真实内容 → 允许出 md
        out_noaudio = self._s4_outdir(self.tmp, "out_noaudio")
        probe_noaudio = ("  Duration: 00:00:20.50\n"
                         "    Stream #0:0: Video: h264, 1920x1080, 25 fps\n"
                         "    Stream #0:1: Subtitle: mov_text\n")
        with mock.patch.object(vt, "capability", return_value=cap):
            r3 = vt.transcribe([str(video)], str(out_noaudio),
                               runner=self._s4_runner(probe=probe_noaudio,
                                                      srt=srt_text))
        self.assertIs(r3["ok"], True, r3)
        md3 = Path(r3["path"]).read_text(encoding="utf-8")
        self.assertIn("未获得可用的带时间戳语音分段", md3)
        self.assertIn("真实字幕第一条", md3)
        self.assertIs(r3["results"][0]["has_audio"], False)

        # ④ 伪内容防护：空分段 + 无字幕 → 零 md，provenance 留失败痕
        out_empty = self._s4_outdir(self.tmp, "out_empty")
        empty = {"text": "", "language": "zh", "segments": []}
        with mock.patch.object(vt, "capability", return_value=cap):
            r4 = vt.transcribe([str(video)], str(out_empty),
                               runner=self._s4_runner(segments=empty))
        self.assertIs(r4["ok"], False)
        self.assertEqual(r4["results"][0]["status"], vt.STATUS_NO_CONTENT)
        self.assertIn("拒绝写占位", r4["results"][0]["error"])
        self.assertEqual(list((out_empty / "derived").glob("*.md")), [])
        prov = rt.read_provenance(out_empty)
        self.assertTrue(any(e.get("capability") == "video_transcribe"
                            for e in prov.get("entries", [])))

        # ⑤ 元数据门禁：解析不出视频流 → 零 md（不写空壳三区块）
        out_nostream = self._s4_outdir(self.tmp, "out_nostream")
        with mock.patch.object(vt, "capability", return_value=cap):
            r5 = vt.transcribe([str(video)], str(out_nostream),
                               runner=self._s4_runner(probe="no stream info"))
        self.assertIs(r5["ok"], False)
        self.assertIn("视频流元数据", r5["results"][0]["error"])

        # ⑥ ffprobe 可选增强（绝不进 media_tools.TOOL_SPECS / probe.tools）
        out_ffprobe = self._s4_outdir(self.tmp, "out_ffprobe")
        capf = self._s4_fake_cap(with_ffprobe=True)
        fjson = {"streams": [
            {"codec_type": "video", "codec_name": "h264", "width": 1280,
             "height": 720, "r_frame_rate": "30/1"},
            {"codec_type": "audio", "codec_name": "aac"}],
            "format": {"duration": "12.500000"}}
        with mock.patch.object(vt, "capability", return_value=capf):
            r6 = vt.transcribe([str(video)], str(out_ffprobe),
                               runner=self._s4_runner(probe=probe_sub,
                                                      srt=srt_text,
                                                      ffprobe_json=fjson))
        self.assertIs(r6["ok"], True, r6)
        md6 = Path(r6["path"]).read_text(encoding="utf-8")
        self.assertIn("ffprobe JSON", md6)
        self.assertIn("1280 × 720", md6)
        self.assertIn("ffprobe 7.0.2", md6)

        # ⑦ provenance 读旧追加（历史条目不被覆盖）+ 取消 / 临时目录清理
        out_hist = self._s4_outdir(self.tmp, "out_hist")
        rt.write_provenance(out_hist, entries=[
            {"capability": "word_export", "name": "old.md", "status": "成功"}])
        with mock.patch.object(vt, "capability", return_value=cap):
            r7 = vt.transcribe([str(video)], str(out_hist),
                               runner=self._s4_runner(probe=probe_sub,
                                                      srt=srt_text))
        self.assertIs(r7["ok"], True, r7)
        entries = rt.read_provenance(out_hist).get("entries", [])
        self.assertIn("word_export", [e.get("capability") for e in entries])
        self.assertIn("video_transcribe", [e.get("capability") for e in entries])
        out_cancel = self._s4_outdir(self.tmp, "out_cancel")
        with mock.patch.object(vt, "capability", return_value=cap):
            r8 = vt.transcribe([str(video)], str(out_cancel),
                               runner=self._s4_runner(),
                               cancel_check=lambda: True)
        self.assertIs(r8["ok"], False)
        self.assertIs(r8["cancelled"], True)
        self.assertEqual(list((out_cancel / "derived").glob("*.md")), [])
        import tempfile
        self.assertEqual(list(Path(tempfile.gettempdir()).glob(
            "jinghe-run-video-*")), [], "临时目录三链未收干净")

    # ------------------------------------------------------------------ #
    # 42) S4：HTTP 端点 / probe 顶层字段 / UI 接线 / 冻结断言零回归
    # ------------------------------------------------------------------ #
    def test_42_s4_video_http_and_ui(self):
        srv = self.start()

        # ① probe 顶层增量字段；S1 占位清单与三工具结构原样
        status, probe = srv.get_json("/api/tools/probe")
        self.assertEqual(status, 200)
        self.assertEqual(set(probe["tools"]), {"ffmpeg", "whisper", "yt-dlp"},
                         "ffprobe 只能待在 video_transcribe.tools，绝不进 TOOL_SPECS")
        self.assertIn("video_transcribe", probe)
        # 同 test_40：不硬编码真假，只守「enabled 必须与实际探测一致」（不许谎报）
        _ffmpeg_ok = bool(probe["tools"]["ffmpeg"].get("available"))
        _ffprobe_ok = bool(probe["video_transcribe"]["tools"]["ffprobe"].get("available"))
        self.assertIs(probe["video_transcribe"]["enabled"], _ffmpeg_ok and _ffprobe_ok,
                      "video_transcribe.enabled 与实际探测不一致（谎报可用/不可用）")
        self.assertEqual(
            probe["video_transcribe"]["capability"],
            "available" if (_ffmpeg_ok and _ffprobe_ok) else "unavailable")
        self.assertIn("ffprobe", probe["video_transcribe"]["tools"])
        self.assertIs(probe["capabilities"]["media_transcribe"]["enabled"], False)
        self.assertIs(probe["capabilities"]["word_export"]["enabled"], False)
        self.assertIs(probe["word_export"]["enabled"], True)
        _audio_tools_ready = bool(probe["tools"]["whisper"].get("available")
                                  and probe["tools"]["ffmpeg"].get("available"))
        self.assertIs(probe["audio_transcribe"]["enabled"], _audio_tools_ready,
                      "audio_transcribe.enabled 与实际探测不一致")

        status, st = srv.get_json("/api/video/status?since=0")
        self.assertEqual(status, 200)
        self.assertEqual(st["state"], "idle")
        self.assertEqual(st["events"], [])

        outdir = self._s4_outdir(self.tmp, "out_http")
        video = self.tmp / "clip.mp4"
        video.write_bytes(b"\x00\x00\x00\x18ftypmp42")
        audio = self.tmp / "voice.mp3"
        audio.write_bytes(b"ID3 fake audio")

        # ② 只读预检：音频逐条拒收，零副作用
        status, ins = srv.post_json(
            "/api/video/inspect", {"inputs": [str(video), str(audio)]})
        self.assertEqual(status, 200)
        by_name = {i["name"]: i for i in ins["items"]}
        self.assertEqual(by_name["voice.mp3"]["status"], "不支持")
        self.assertIn("S3", by_name["voice.mp3"]["error"])
        self.assertFalse((outdir / "derived").exists())

        # ③ 缺工具诚实降级：零 md、零 derived
        # 同 test_40：用隔离 PATH 造一个「找不到工具」的环境，降级路径稳定可复现
        empty_bin_v = Path(self.tmp) / "empty_bin_v"
        empty_bin_v.mkdir(exist_ok=True)
        srv_no_tools = self.start(env_extra={"PATH": str(empty_bin_v)})
        # 独立 outdir：前面的成功提取可能已建 derived，混用会污染断言
        outdir_no_tools = Path(self.tmp) / "out_no_tools_v"
        status, res = srv_no_tools.post_json(
            "/api/video/transcribe",
            {"inputs": [str(video)], "outdir": str(outdir_no_tools)})
        self.assertEqual(status, 200, res)
        self.assertIs(res["ok"], False)
        self.assertEqual(res["capability"], "unavailable")
        self.assertIn("未启用", res["error"])
        self.assertFalse((outdir_no_tools / "derived").exists())
        self.assertEqual([p.name for p in (outdir / "md").glob("*.md")], ["a.md"])

        # ④ 音频走视频端点仍显式拒收（不因缺工具被笼统盖掉）
        # 用独立 outdir：前面的成功提取可能已建 derived，混用会污染断言
        outdir_reject_v = Path(self.tmp) / "out_reject_audio"
        status, ar = srv.post_json(
            "/api/video/transcribe",
            {"inputs": [str(audio)], "outdir": str(outdir_reject_v)})
        self.assertEqual(status, 200)
        self.assertIs(ar["ok"], False)
        self.assertEqual(ar["results"][0]["status"], "不支持")
        # 意图是「该文件没被提取出 md」；provenance 留痕允许存在（失败也留痕是 S4 设计）
        self.assertEqual(list((outdir_reject_v / "derived").glob("*.md")), [])

        # ⑤ 状态收敛 / 取消无任务 / 未知端点
        status, st = srv.get_json("/api/video/status?since=0")
        self.assertEqual(status, 200)
        self.assertIn(st["state"], ("done", "failed", "cancelled"))
        self.assertIs(st["running"], False)
        status, cancel = srv.post_json("/api/video/cancel", {})
        self.assertEqual(status, 200)
        self.assertIs(cancel["ok"], False)
        status, unknown = srv.post_json("/api/video/nope", {})
        self.assertEqual(status, 404)
        self.assertIs(unknown["ok"], False)

        # ⑥ UI / 后端接线 / 打包清单；S1 空心位与冻结断言原样保留
        html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        app_src = (ROOT / "app.py").read_text(encoding="utf-8")
        gate = (ROOT / "tools" / "check_release.py").read_text(encoding="utf-8")
        spec = (ROOT / "build.spec").read_text(encoding="utf-8")
        contract = (ROOT / "docs" / "CAPABILITY_CONTRACT.md").read_text(
            encoding="utf-8")
        self.assertIn('id="btnVideoTranscribe"', html)
        self.assertIn('id="btnVideoCancel"', html)
        for needle in ("/api/video/transcribe", "/api/video/status",
                       "/api/video/cancel", "doVideoTranscribe",
                       "video_transcribe", "hasVideoInput", "VIDEO_EXT_RE"):
            self.assertIn(needle, js)
        for needle in ('path == "/api/video/transcribe"',
                       'path == "/api/video/status"',
                       'data["video_transcribe"]', "_VIDEO_JOB",
                       "import video_transcribe"):
            self.assertIn(needle, app_src)
        self.assertIn("video_transcribe.py", gate)
        self.assertIn("'video_transcribe'", spec)
        self.assertIn("el.btnTranscribe.disabled = !on || !mediaOn", js,
                      "S1 的音视频诚实降级判定被改写")
        self.assertIn("阶段 3 音视频转写需专用转写器", app_src,
                      "S1 空心占位被提前填充或改写")
        self.assertIn("v0.6", contract)
        self.assertIn("留给 S5", contract,
                      "契约须订正：/api/media/run 不再留给 S4")


# ------------------------------------------------------------------ #
    # 43) v0.4.8：自更新闭环（查版本 → 下载 → 替换运行中的程序 → 重启）
    # ------------------------------------------------------------------ #
    def test_43_v048_self_update_contract(self):
        sys.path.insert(0, str(ROOT))
        try:
            import self_update as su
        finally:
            sys.path.remove(str(ROOT))
        from unittest import mock

        app_src = (ROOT / "app.py").read_text(encoding="utf-8")
        html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "ui" / "app.css").read_text(encoding="utf-8")
        gate = (ROOT / "tools" / "check_release.py").read_text(encoding="utf-8")
        spec = (ROOT / "build.spec").read_text(encoding="utf-8")
        contract = (ROOT / "docs" / "CAPABILITY_CONTRACT.md").read_text(
            encoding="utf-8")

        # ① 下载白名单：只认本仓库 releases/download 下的 Jinghe*.exe
        self.assertTrue(su.is_asset_url(
            "https://github.com/kong-city/jinghe/releases/download/v0.4.8/Jinghe.exe"))
        for bad in ("https://evil.example.com/Jinghe.exe",
                    "https://github.com/other/repo/releases/download/v1/Jinghe.exe",
                    "https://github.com/kong-city/jinghe/releases/download/v0.4.8/readme.md",
                    "https://github.com/kong-city/jinghe/releases/latest/Jinghe.exe"):
            self.assertFalse(su.is_asset_url(bad), "白名单放行了非法地址：%s" % bad)

        # ② 白名单外地址：零网络请求、零落盘
        with mock.patch.object(su.urllib.request, "urlopen") as fake:
            res = su.download_asset("https://evil.example.com/Jinghe.exe",
                                    self.tmp / "never.exe")
        self.assertIs(res.get("ok"), False)
        self.assertIn("白名单", res.get("error") or "")
        self.assertFalse(fake.called, "白名单外地址竟发起了网络请求")
        self.assertFalse((self.tmp / "never.exe").exists())

        # ③ 替换脚本：等待退出 / 备份 / 覆盖 / 启动 / 回滚；变量名不得用只读的 $PID
        script = su.build_install_script(r"C:\Jinghe\Jinghe.new.exe",
                                         r"C:\Jinghe\Jinghe.exe", 4321, "v0.4.8")
        for token in ("Wait-Process", "$targetPid = 4321", "Copy-Item",
                      "Start-Process", "HasExited", ".bak"):
            self.assertIn(token, script, "替换脚本缺少：%s" % token)
        self.assertNotIn("$pid =", script, "替换脚本误用 PowerShell 只读变量 $PID")

        # ④ 安装红线：源码模式不可自动替换；目标必须是程序自身
        plan = su.install_plan()
        self.assertIs(plan.get("ok"), False, "源码模式竟声称可自动替换")
        self.assertIn("源码", plan.get("reason") or "")
        res = su.schedule_install(self.tmp / "fake.exe",
                                  r"C:\Windows\System32\cmd.exe")
        self.assertIs(res.get("ok"), False, "竟允许替换非自身程序")
        res = su.schedule_install(self.tmp / "not-exist.exe",
                                  r"C:\Windows\System32\cmd.exe")
        self.assertIs(res.get("ok"), False)

        # ⑤ 后端接线：四个新端点 + 独立进度队列
        for token in ('path == "/api/update/check"',
                      'path == "/api/update/start"',
                      'path == "/api/update/status"',
                      'path == "/api/update/cancel"',
                      'path == "/api/update/apply"',
                      "_UPDATE_JOB", "import self_update",
                      "def _run_update_job"):
            self.assertIn(token, app_src, "后端缺少自更新接线：%s" % token)

        # ⑥ 真实 HTTP：查版本 / 进度 / 取消 / 手动替换
        srv = self.start()
        status, chk = srv.get_json("/api/update/check")
        self.assertEqual(status, 200)
        for key in ("current", "latest", "up_to_date", "has_asset",
                    "offline", "error"):
            self.assertIn(key, chk, "/api/update/check 缺少字段 %s" % key)
        self.assertTrue(re.match(r"^\d+\.\d+\.\d+", str(chk.get("current"))),
                        "current 不应是 unknown：%s" % chk.get("current"))
        if chk.get("offline"):
            self.assertIsNone(chk.get("latest"), "离线时不得伪造最新版本号")

        status, st = srv.get_json("/api/update/status?since=0")
        self.assertEqual(status, 200)
        self.assertEqual(st["state"], "idle")
        self.assertEqual(st["events"], [])

        status, cancel = srv.post_json("/api/update/cancel", {})
        self.assertEqual(status, 200)
        self.assertIs(cancel.get("ok"), False, "无任务时取消竟返回成功")

        status, applied = srv.post_json("/api/update/apply", {})
        self.assertEqual(status, 200)
        self.assertIs(applied.get("ok"), False, "无更新时竟允许安装")

        # ⑦ 启动更新任务：立即返回，状态在有限时间内收敛到终态
        status, started = srv.post_json("/api/update/start", {})
        self.assertEqual(status, 200)
        self.assertIs(started.get("ok"), True)
        self.assertIs(started.get("started"), True)
        deadline = time.time() + 60
        state = ""
        while time.time() < deadline:
            _, st = srv.get_json("/api/update/status?since=0")
            state = st.get("state")
            if state in ("done", "failed", "cancelled", "restarting"):
                break
            time.sleep(0.5)
        self.assertIn(state, ("done", "failed", "cancelled", "restarting"),
                      "更新任务未收敛到终态：%s" % state)
        self.assertIs(st.get("running"), False)

        # ⑧ 关于页：当前 / 立即更新 / 取消 / 进度条 / 轻提示
        #    v0.4.9：「最新版本」信息格已取消（用户新要求），改用 toast 反馈。
        for needle in ('id="aboutVersion"', 'id="btnUpdateNow"',
                       'id="btnUpdateCancel"', 'id="updateProgress"',
                       'id="updateProgressBar"', 'id="updateProgressText"',
                       'id="toast"'):
            self.assertIn(needle, html, "关于页缺少：%s" % needle)
        self.assertNotIn("<span>最新版本</span>", html,
                         "v0.4.9：「最新版本」信息格应已取消")
        for needle in ("/api/update/check", "/api/update/start",
                       "/api/update/status", "/api/update/cancel",
                       "startUpdate", "pollUpdateStatus", "cancelUpdate",
                       "setUpdateProgress"):
            self.assertIn(needle, js, "前端缺少：%s" % needle)
        self.assertIn(".update-progress", css)
        self.assertIn(".update-progress-bar", css)

        # ⑨ 打包清单与契约文档
        self.assertIn("self_update.py", gate)
        self.assertIn("'self_update'", spec)
        self.assertIn("自更新", contract)


    # ------------------------------------------------------------------ #
    # 44) v0.4.9：检查更新交互修复 + 拖拽输入 + 已识别清单勾选预览
    # ------------------------------------------------------------------ #
    def test_44_v049_update_feedback_and_drop_input(self):
        html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "ui" / "app.css").read_text(encoding="utf-8")
        src = (ROOT / "app.py").read_text(encoding="utf-8")

        # ① 检查更新 GET 修复：传 undefined 才会走 GET；POST 同路径会 404。
        self.assertIn('api("/api/update/check", undefined, 20000)', js,
                      "检查更新仍把空对象当 body 发出（会变 POST → 未知接口 404）")
        self.assertIn('body === undefined ? "GET" : "POST"',
                      js, "api() 的 GET/POST 判据被改动")

        # ② 关于页：最新版本栏取消、轻提示 toast、无新版本与直接更新两条反馈
        self.assertNotIn('id="aboutNewVersion"', html, "最新版本栏应已取消")
        self.assertIn('id="toast" class="toast"', html, "缺少轻提示 toast 容器")
        self.assertIn("showToast", js, "前端缺少 showToast 实现")
        self.assertIn("当前是最新版本", js, "无新版本未弹「当前是最新版本」")
        self.assertIn("3000", js, "轻提示未在 3 秒后消失")
        # 有新版本直接进更新流程（checkUpdate 内调用 startUpdate）
        chk_fn = js[js.index("function checkUpdate"):js.index("function startUpdate")]
        self.assertIn("startUpdate()", chk_fn, "发现新版本未直接进入更新流程")
        self.assertIn(".toast", css, "缺少 toast 样式")

        # ③ 拖拽输入：拖拽框 + 上传端点 + 接收后触发识别
        self.assertIn('id="dropZone" class="drop-zone"', html, "输入卡片缺少拖拽框")
        self.assertIn("拖入文件 / 音频 / 视频", html, "拖拽框缺少引导文案")
        self.assertIn("function setupDropZone", js, "前端缺少拖拽事件绑定")
        self.assertIn("function uploadDropped", js, "前端缺少拖入文件上传逻辑")
        self.assertIn('"/api/drop-files?name="', js, "前端未调用拖拽上传端点")
        self.assertIn("dropEffect", js, "拖拽未设置 copy 效果")
        for token in ('path == "/api/drop-files"', "def _api_drop_files",
                      "_DROP_MAX_BYTES", "_new_drop_dir",
                      "def _build_name_path_map", "_sweep_orphan_drop_dirs"):
            self.assertIn(token, src, "后端缺少拖拽上传实现：%s" % token)
        self.assertIn(".drop-zone.is-over", css, "缺少拖拽悬停高亮样式")

        # ④ 已识别清单：勾选框 + 全选 + 预览按钮移到标题栏右侧 + 按勾选预览
        self.assertIn('class="card-title file-title-row"', html,
                      "「已识别」标题行未改为 file-title-row")
        title_row = html[html.index('class="card-title file-title-row"'):]
        title_row_end = title_row.index("</div>")
        title_row = title_row[:title_row_end]
        self.assertIn('id="btnPreviewInline"', title_row,
                      "预览分流按钮未移到「已识别」标题栏")
        self.assertIn('id="fileCheckAll"', html, "缺少全选框")
        self.assertIn('data-file-idx', js, "清单项未带勾选索引")
        self.assertIn("function checkedFilePaths", js, "缺少勾选路径收集")
        self.assertIn("请先勾选要预览的文件", js, "未勾选时缺少提示")
        self.assertIn("doPreview(picked)", js, "点预览分流未走勾选子集")
        self.assertIn('it["path"]', src, "dry-run 未给清单项补真实路径")

        # ⑤ 冻结契约：test_06 / test_11 与原主流水线不得被本轮改动碰过
        extract_src = (ROOT / "extract.py").read_text(encoding="utf-8")
        # v0.6.0：S8 可信提纯能力落地，版本号随发版升号（0.5.0 → 0.6.0）
        self.assertIn('__version__ = "0.6.0"', extract_src, "版本号未升到 0.6.0")
        self.assertIn("if args.dry_run:", extract_src, "extract.py 冻结主流水线被改动")

        # ⑥ 真实 HTTP：GET 检查更新 200、POST 同路径仍 404（锁死根因）、上传落盘
        srv = self.start()
        status, chk = srv.get_json("/api/update/check")
        self.assertEqual(status, 200, "GET /api/update/check 应 200")
        self.assertIn("up_to_date", chk)
        up = Path(self.tmp) / "dragged.txt"
        up.write_bytes(b"v0.4.9 drag payload")
        req = urllib.request.Request(
            srv.base + "/api/drop-files?name=dragged.txt",
            data=up.read_bytes(), method="POST",
            headers={"Content-Type": "application/octet-stream"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        self.assertTrue(body.get("ok"), "拖拽上传失败：%s" % body)
        self.assertTrue(Path(body["path"]).is_file(), "上传文件未落盘")
        self.assertEqual(Path(body["path"]).read_bytes(), b"v0.4.9 drag payload")
        self.assertEqual(Path(body["path"]).name, "dragged.txt")

    # ------------------------------------------------------------------ #
    # 45) v0.4.9 交互打磨：清单不被子集覆盖 / 更新门闩 / 拖拽整页防护
    # ------------------------------------------------------------------ #
    def test_45_v049_interaction_polish(self):
        js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")

        # ① 勾选预览是只读盘点：绝不能拿选中子集重建「已识别清单」，
        #    否则未勾选文件消失、勾选态归零。
        self.assertIn("var isSubsetPreview = explicit.length > 0;", js,
                      "前端未区分勾选预览与全量预览")
        # doPreview 的 then 块内：renderFileList 只在非子集预览时调用
        dp = js[js.index("function doPreview"):js.index("/* ------------------------------ 输出目录选择")]
        self.assertIn("if (!isSubsetPreview) renderFileList(r);", dp,
                      "勾选预览仍会重建清单（未勾选文件会消失）")
        self.assertIn("已按勾选的", dp, "勾选预览缺少明确的反馈文案")

        # ② 更新任务门闩：更新中重复点检查更新不得再启动一次任务
        self.assertIn("var updateRunning = false;", js, "缺少更新任务门闩")
        cu = js[js.index("function checkUpdate"):js.index("function startUpdate")]
        self.assertIn("if (updateRunning)", cu, "检查更新未拦截更新中的重复点击")
        self.assertIn("hideUpdateProgress()", cu, "检查更新未清掉上次进度条残留")
        su = js[js.index("function startUpdate"):js.index("function pollUpdateStatus")]
        self.assertIn("updateRunning = true;", su, "启动更新未置位门闩")
        fu = js[js.index("function finishUpdate"):]
        self.assertIn("updateRunning = false;", fu[:fu.index("function cancelUpdate")],
                      "更新收尾未复位门闩")

        # ③ 拖拽整页防护：拖到框外的文件不得被浏览器默认打开
        self.assertIn("document.addEventListener(evt", js,
                      "缺少整页 dragover/drop 默认行为拦截")

        # ④ 死代码清理：旧的 renderBuckets 已被 inputMeta 覆盖，不应再残留
        self.assertNotIn("function renderBuckets", js, "残留无调用的 renderBuckets 死代码")

    # ------------------------------------------------------------------ #
    # 46) v0.4.9 可访问性审查修复：焦点环 / 对比度 / 标签 / 动效降级
    #     （依据 ui-ux-pro-max 审查；冻结内核与主流水线零改动）
    # ------------------------------------------------------------------ #
    def test_46_v049_accessibility_audit_fixes(self):
        html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "ui" / "app.css").read_text(encoding="utf-8")

        def _lum(hexs):
            h = hexs.lstrip("#")
            if len(h) == 3:
                h = "".join(c * 2 for c in h)
            ch = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
            f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
            r, g, b = [f(c) for c in ch]
            return 0.2126 * r + 0.7152 * g + 0.0722 * b

        def _ratio(a, b):
            l1, l2 = sorted([_lum(a), _lum(b)], reverse=True)
            return (l1 + 0.05) / (l2 + 0.05)

        # ① 焦点可见性：不得有「移除 outline 却不给替代」的情况
        #    先完整剥离 CSS 注释块（注释里会引用 outline:none 这个词，不能误伤），
        #    再检查所有写法：outline:none / outline: none / outline:none;
        css_no_comment = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        for line in css_no_comment.splitlines():
            self.assertNotRegex(line, r"outline\s*:\s*none",
                                "仍有 outline:none 且未提供替代焦点环：%s" % line.strip())
        self.assertIn(":focus-visible", css, "缺少 :focus-visible 焦点环规则")
        for sel in (".btn:focus-visible", ".nav-item:focus-visible",
                    ".link-btn:focus-visible", ".text-input:focus-visible",
                    ".drop-zone:focus-visible"):
            self.assertIn(sel, css, "焦点环未覆盖：%s" % sel)
        self.assertIn("outline: 2px solid #185FA5", css, "焦点环样式缺失")
        # 焦点环颜色本身要够醒目（对白底 ≥3:1）
        self.assertGreaterEqual(_ratio("#185FA5", "#FFFFFF"), 3.0,
                                "焦点环颜色对白底对比度不足 3:1")

        # ② 可见文字对比度：正文级文字全部达 WCAG AA 4.5:1
        for fg, bg, what in (
            ("#6F6D66", "#FFFFFF", "次级文字"),
            ("#6F6D66", "#FAFAF8", "虚线按钮文字"),
            ("#6F6D66", "#FBFAF7", "拖拽框副文案"),
            ("#1F1F1D", "#FFFFFF", "正文"),
            ("#185FA5", "#FFFFFF", "主色链接与按钮"),
            ("#1F6B3B", "#EDF7F0", "成功提示"),
            ("#9A3B2F", "#FCEEEC", "错误提示"),
        ):
            self.assertGreaterEqual(_ratio(fg, bg), 4.5,
                                    "%s 对比度 %.2f:1 未达 AA" % (what, _ratio(fg, bg)))
        # 低对比度的旧色不得再作为前景色出现（注释里提及不算）
        for line in css_no_comment.splitlines():
            if "color:" in line and "#9A9890" in line:
                self.fail("仍有 #9A9890 被用作前景色：%s" % line.strip())

        # ③ 输入框不能只靠 placeholder 当标签
        for fid in ("inputPath", "outPath"):
            m = re.search(r'<input id="%s"[^>]*>' % fid, html, re.S)
            self.assertIsNotNone(m, "找不到 #%s" % fid)
            tag = m.group(0)
            self.assertIn("aria-label=", tag,
                          "#%s 缺少 aria-label（输入框只靠 placeholder 不可访问）" % fid)
        self.assertIn('aria-label="拖拽输入区', html,
                      "拖拽框（role=button）缺少可访问名称")

        # ④ 动效降级：必须尊重系统的「减少动态效果」
        self.assertIn("@media (prefers-reduced-motion: reduce)", css,
                      "缺少 prefers-reduced-motion 降级")
        self.assertIn("transition-duration: 0.01ms", css,
                      "reduced-motion 未关闭过渡")

        # ⑤ 微交互过渡窗口 150–300ms（skill 规范），按钮须有平滑反馈
        self.assertRegex(css, r"\.btn \{[^}]*transition:[^}]*160ms",
                         ".btn 缺少 160ms 过渡（hover 会生硬跳变）")

    # ------------------------------------------------------------------ #
    # 47) S7a 精读 / 修订能力地基：独立 handler / 探测隔离 / 诚实降级
    # ------------------------------------------------------------------ #
    def test_47_s7a_refine_foundation(self):
        import refine
        import media_tools

        app_src = (ROOT / "app.py").read_text(encoding="utf-8")
        refine_src = (ROOT / "refine.py").read_text(encoding="utf-8")

        # ① 独立 handler + 冻结内核零改动
        self.assertIn("import refine", app_src, "app.py 未挂接 refine handler")
        extract_src = (ROOT / "extract.py").read_text(encoding="utf-8")
        self.assertIn("if args.dry_run:", extract_src, "extract.py 冻结主流水线被改动")
        spec_src = (ROOT / "SPEC.md").read_text(encoding="utf-8")
        self.assertIn("不提前实现", spec_src, "SPEC.md 冻结规格被改动")

        # ② ollama 探测隔离：绝不进 TOOL_SPECS / 占位清单
        self.assertNotIn("ollama", [s[0] for s in media_tools.TOOL_SPECS],
                         "ollama 不得并入 TOOL_SPECS（S1 契约锁死 3 工具）")
        self.assertEqual([s[0] for s in media_tools.TOOL_SPECS],
                         ["ffmpeg", "whisper", "yt-dlp"])
        self.assertIn("绝不并入", refine_src, "refine.py 缺少探测隔离声明")
        self.assertNotIn("capabilities()[", refine_src, "不应改写占位清单")

        # ③ probe 顶层增量字段 + 既有端点不变
        self.assertIn('data["refine"] = refine.capability', app_src,
                      "probe 未挂顶层 refine 字段")
        for frozen in ('/api/summarize', '/api/transcribe'):
            self.assertIn('path == "%s"' % frozen, app_src,
                          "冻结端点 %s 被改动" % frozen)

        # ④ 六个新端点齐全（4 POST + 2 GET）
        for ep in ('/api/refine/inspect', '/api/refine/start',
                   '/api/revise/start', '/api/refine/cancel',
                   '/api/refine/status', '/api/refine/models'):
            self.assertIn(ep, app_src, "缺少端点：%s" % ep)

        # ⑤ S7a 诚实降级：缺工具 / 空输入一律拒绝，零产物、不写真推理
        cap = refine.capability()
        self.assertIsInstance(cap, dict)
        self.assertIn("capability", cap)
        self.assertIn("tools", cap)
        # S7b 起 tools 子结构从 ollama 改为 backend（方案 C 可插拔多后端）
        self.assertIn("backend", cap["tools"])
        self.assertIn("refine", cap["stages"])
        self.assertIn("revise", cap["stages"])
        # 无论本机是否装 ollama，start 在 S7a 阶段都必须诚实拒绝真实推理
        refused = refine.start_refine(str(ROOT / "不存在.md"))
        self.assertIs(refused["ok"], False, "S7a 不得静默启动真实推理")
        self.assertIn("capability", refused)
        # 空输入必须拒绝
        empty = refine.check_source("")
        self.assertIs(empty["ok"], False)
        self.assertIn("请先选择", empty["error"])
        # status/cancel 地基形状
        self.assertIs(refine.status()["running"], False)
        self.assertIs(refine.cancel()["ok"], True)

        # ⑥ 双产物契约声明（S7a 只声明不渲染）
        self.assertIn(".refine.md", refine_src)
        self.assertIn(".revise.md", refine_src)
        self.assertIn(".revise.html", refine_src)
        self.assertIn("MD_ADD_OPEN", refine_src, "缺少新增标记语法声明")
        self.assertIn("MD_MOD_OPEN", refine_src, "缺少修改标记语法声明")

        # ⑦ 真实 HTTP：probe 含顶层 refine；六个新端点形状正确、诚实拒绝
        srv = self.start()
        status, probe = srv.get_json("/api/tools/probe")
        self.assertEqual(status, 200, "probe 应 200")
        self.assertIn("refine", probe, "probe 缺少顶层 refine 字段")
        self.assertIn("capability", probe["refine"])
        # GET status / models
        st, st_body = srv.get_json("/api/refine/status")
        self.assertEqual(st, 200, "GET /api/refine/status 应 200")
        self.assertIn("running", st_body)
        st, models = srv.get_json("/api/refine/models")
        self.assertEqual(st, 200, "GET /api/refine/models 应 200")
        self.assertIn("models", models)
        # POST inspect / start / revise / cancel —— 空输入或地基阶段一律诚实拒绝
        st, insp = srv.post_json("/api/refine/inspect", {"path": ""})
        self.assertEqual(st, 200, "POST /api/refine/inspect 应 200")
        self.assertIs(insp["ok"], False, "空输入 inspect 应拒绝")
        st, started = srv.post_json("/api/refine/start", {"path": ""})
        self.assertEqual(st, 200, "POST /api/refine/start 应 200")
        self.assertIs(started["ok"], False, "空输入 start 应拒绝")
        st, revised = srv.post_json("/api/revise/start", {"path": ""})
        self.assertEqual(st, 200, "POST /api/revise/start 应 200")
        self.assertIs(revised["ok"], False, "空输入 revise 应拒绝")
        st, cancelled = srv.post_json("/api/refine/cancel", {})
        self.assertEqual(st, 200, "POST /api/refine/cancel 应 200")
        self.assertIs(cancelled["ok"], True)
        # 冻结端点未变：/api/summarize 行为照旧（空 outdir 诚实拒绝）
        st, summ = srv.post_json("/api/summarize", {"outdir": ""})
        self.assertEqual(st, 200)
        self.assertIs(summ["ok"], False)

    # ------------------------------------------------------------------ #
    # 48) S7b 可插拔后端适配层（方案 C）：双实现 / 密钥脱敏 / 独立存储
    # ------------------------------------------------------------------ #
    def test_48_s7b_backend_adapter(self):
        import backend
        import media_tools
        from unittest import mock

        app_src = (ROOT / "app.py").read_text(encoding="utf-8")
        be_src = (ROOT / "backend.py").read_text(encoding="utf-8")
        settings_src = (ROOT / "app.py").read_text(encoding="utf-8")

        # ① 双实现 + 统一接口
        self.assertTrue(issubclass(backend.LocalBackend, backend.Backend))
        self.assertTrue(issubclass(backend.CloudBackend, backend.Backend))
        for meth in ("probe", "list_models", "chat"):
            self.assertTrue(hasattr(backend.Backend, meth), "接口缺方法：%s" % meth)
        self.assertEqual(backend.LocalBackend.kind, backend.KIND_LOCAL)
        self.assertEqual(backend.CloudBackend.kind, backend.KIND_CLOUD)

        # ② 独立存储：backend.json 不放 settings.json
        self.assertIn("backend.json", be_src)
        self.assertNotIn("api_key", settings_src.split("DEFAULT_SETTINGS")[1].split("}")[0],
                         "api_key 不得进 DEFAULT_SETTINGS（会被 /api/settings 回显）")
        self.assertIn("CONFIG_FILE", be_src)

        # ③ 脱敏：mask_key 各分支 + public_config 不泄漏真 key
        self.assertEqual(backend.mask_key(""), "")
        self.assertEqual(backend.mask_key("abc"), "****")
        masked = backend.mask_key("sk-1234567890abcdef")
        self.assertTrue(masked.startswith("****") and masked.endswith("cdef"))
        self.assertNotIn("1234567890", masked)

        cfg_file = Path(self.tmp) / "backend.json"
        with mock.patch.object(backend, "CONFIG_FILE", cfg_file), \
             mock.patch.object(backend, "_CACHE", None):
            backend.save_config({"kind": backend.KIND_CLOUD,
                                 "endpoint": "https://api.example.com/v1",
                                 "api_key": "sk-SUPERSECRET123456",
                                 "model": "gpt-x"})
            pub = backend.public_config()
            self.assertNotIn("SUPERSECRET", json.dumps(pub, ensure_ascii=False),
                             "public_config 泄漏了真实 key")
            self.assertEqual(pub["api_key"], "****3456")
            self.assertTrue(pub["has_key"])
            # 空值 key 保存 = 保留原值（脱敏回显场景不覆盖）
            backend.save_config({"kind": backend.KIND_CLOUD, "api_key": "",
                                 "endpoint": "https://api.example.com/v1", "model": "gpt-x"})
            self.assertEqual(backend.load_config(refresh=True)["api_key"],
                             "sk-SUPERSECRET123456", "空 key 应保留原值")
            # 真 key 不落日志文案：backend.py 里 _append_log 不应出现
            self.assertNotIn("_append_log", be_src, "backend.py 不应写日志（防 key 泄漏）")

        # ④ 缺配置诚实降级 + chat 真推理显式拒绝
        # S8 起默认 mode=extract（内置引擎恒可用）；此处显式切 llm 模式，
        # 守「LLM 模式未配置后端 → 诚实不可用」。extract 模式恒可用由 test_52 守。
        with mock.patch.object(backend, "CONFIG_FILE", Path(self.tmp) / "none.json"), \
             mock.patch.object(backend, "_CACHE", None):
            backend.save_config({"mode": backend.MODE_LLM, "kind": "none"})
            probe = backend.probe_current(refresh=True)
            self.assertIs(probe["available"], False)
            self.assertEqual(probe["kind"], backend.KIND_NONE)
            self.assertIn("尚未配置", probe["reason"])
        with self.assertRaises(NotImplementedError):
            backend.CloudBackend({"endpoint": "https://x", "api_key": "k"}).chat([])

        # ⑤ 端到端：app.py 挂了两个配置端点且回显脱敏
        self.assertIn('path == "/api/refine/backend"', app_src)
        self.assertIn("public_config()", app_src, "配置端点必须走脱敏回显")
        self.assertNotIn('data["api_key"]', app_src.split("elif path == \"/api/refine/backend\"")[1][:400]
                         if 'elif path == "/api/refine/backend"' in app_src else "",
                         "POST 回显不得直接带 data['api_key']")
        self.assertIn("import backend", app_src)

        # ⑥ 隔离：后端不进 TOOL_SPECS
        self.assertEqual([s[0] for s in media_tools.TOOL_SPECS],
                         ["ffmpeg", "whisper", "yt-dlp"])

        # ⑦ 真实 HTTP：GET /api/refine/backend 脱敏、POST 保存后仍脱敏、日志无真 key
        # 把 LOCALAPPDATA 指到临时目录，隔离 backend.json 与 app.log，不污染用户真实环境
        appdata = self.tmp / "localappdata_s7b"
        appdata.mkdir(exist_ok=True)
        srv = self.start(env_extra={"LOCALAPPDATA": str(appdata)})
        st, _ = srv.get_json("/api/state")
        self.assertEqual(st, 200, "服务未就绪")
        st, got = srv.get_json("/api/refine/backend")
        self.assertEqual(st, 200)
        self.assertIn("config", got)
        self.assertIn("api_key", got["config"])
        secret = "sk-E2E-SECRET-998877"
        st, saved = srv.post_json("/api/refine/backend", {
            "kind": "cloud", "endpoint": "https://api.example.com/v1",
            "api_key": secret, "model": "m"})
        self.assertEqual(st, 200)
        self.assertTrue(saved["ok"])
        self.assertNotIn(secret, json.dumps(saved, ensure_ascii=False),
                         "POST 回显泄漏了真 key")
        # 服务器输出（含日志）不得出现真 key
        tail = srv.tail()
        self.assertNotIn(secret, tail, "日志/输出泄漏了真 key")
        # backend.json 落在隔离目录（真 key 明文存盘是设计预期，操作系统层面保护）
        cfg_on_disk = appdata / "Jinghe" / "backend.json"
        self.assertTrue(cfg_on_disk.is_file(), "隔离的 backend.json 未落盘")
        self.assertIn(secret, cfg_on_disk.read_text(encoding="utf-8"),
                      "key 应落盘到独立 backend.json（供重启后使用）")
        # 但 app.log（可能被日志导出端点触及）绝不能出现真 key
        app_log = appdata / "Jinghe" / "app.log"
        if app_log.is_file():
            self.assertNotIn(secret, app_log.read_text(encoding="utf-8"),
                             "app.log 泄漏了真 key")

    # ------------------------------------------------------------------ #
    # 49) S7b 后半：精读提纯引擎（mock 后端，反编造锚点校验 + 产物契约）
    # ------------------------------------------------------------------ #
    def test_49_s7b_refine_engine(self):
        import backend
        import refine
        import refine_engine as E
        from unittest import mock

        md = ("# 项目定位\n强调隐私。\n强调零依赖。\n\n"
              "# 技术方案\n本机处理。\n不上传数据。\n")
        blocks = E.split_blocks(md)
        self.assertEqual(len(blocks), 6, "分块数不符（标题+每段各一块）")
        self.assertEqual([b["n"] for b in blocks], [1, 2, 3, 4, 5, 6])
        prompt = E.build_prompt(blocks)
        self.assertIn("[块 1]", prompt)
        self.assertIn("block", prompt, "prompt 未要求结构化 block")
        self.assertIn("不得编造新编号", prompt, "prompt 缺反编造约束")

        # 反编造：有效保留，越界/无号/空文本/非整数一律丢弃
        resp = ('```json\n{"points":['
                '{"text":"注重隐私","block":2},'
                '{"text":"编造块","block":999},'
                '{"text":"无块号"},'
                '{"text":"","block":3},'
                '{"text":"字符串块","block":"2"},'
                '{"text":"本机处理","block":5}'
                ']}\n```')
        pts, skipped = E.parse_points(resp, blocks)
        self.assertEqual([p["text"] for p in pts], ["注重隐私", "本机处理"])
        self.assertEqual(skipped, 4)
        # 全无效 → 空列表（上层据此零产物）
        bad, _ = E.parse_points('{"points":[{"text":"x","block":999}]}', blocks)
        self.assertEqual(bad, [])
        # 解析失败 → 空
        self.assertEqual(E.parse_points("not json", blocks), ([], 0))

        # 产物：mock 后端跑完整提纯，校验 8 字段 / 锚点 / 三区块 / provenance 追加
        class FakeBackend(backend.Backend):
            kind = "local"
            def chat(self, messages):
                return ('{"points":[{"text":"注重隐私","block":2},'
                        '{"text":"编造","block":999},'
                        '{"text":"本机处理","block":5}]}')

        src = Path(self.tmp) / "精读源.md"
        src.write_text(md, encoding="utf-8")
        # 预置一条历史 provenance，验证读旧追加
        E.append_provenance(self.tmp, {"capability": "prior", "status": "历史"})
        cap = {"tools": {"backend": {"kind": "local"}}, "capability": "available"}
        refine._TASK = {"state": "running", "running": True, "cancelled": False,
                        "events": [], "output": "", "error": None}
        # S8 起默认 mode=extract；本用例守护的是 **LLM 提纯路径**，故显式切 llm 模式
        with mock.patch.object(backend, "load_config",
                               return_value={"mode": backend.MODE_LLM,
                                             "kind": backend.KIND_LOCAL,
                                             "allow_suppplement": False}):
            refine._run_refine_inner(str(src), "fake-model", str(self.tmp),
                                     FakeBackend({}), cap)
        st = refine.status()
        self.assertEqual(st["state"], "done", "提纯任务未完成：%s" % st["error"])
        out = Path(st["output"])
        self.assertTrue(out.is_file())
        self.assertTrue(out.name.endswith(refine.REFINE_SUFFIX))
        text = out.read_text(encoding="utf-8")
        self.assertIn("<!-- src:", text, "缺 8 字段来源注释")
        for field in ("doc_id", "path:", "format:", "converter:", "extracted:",
                      "size:", "sha256:", "anchors:"):
            self.assertIn(field, text, "src 注释缺字段：%s" % field)
        for sec in ("## 文档信息", "## 核心知识点", "## 提纯元数据"):
            self.assertIn(sec, text, "缺区块：%s" % sec)
        self.assertIn("<!-- anchor:", text, "核心观点缺块级锚点")
        self.assertIn("注重隐私", text)
        self.assertNotIn("编造", text, "编造观点未被丢弃")
        self.assertIn("请对照原文核对", text, "缺诚实核对提示")
        # provenance 读旧追加（历史条目仍在）
        prov = E.load_provenance(Path(self.tmp))
        entries = prov.get("entries") or []
        self.assertEqual(len(entries), 2, "provenance 未读旧追加")
        self.assertEqual(entries[0]["capability"], "prior")
        self.assertEqual(entries[1]["capability"], "refine")
        # 冻结对账盘只读：out/md / INDEX / MERGED 都未出现
        self.assertFalse((Path(self.tmp) / "md").exists())
        self.assertFalse((Path(self.tmp) / "INDEX.md").exists())
        self.assertFalse((Path(self.tmp) / "MERGED.md").exists())
        # 产物只在 derived/
        self.assertEqual(out.parent.name, "derived", "产物未落 derived/")

        # 全无效模型输出 → 零产物
        class BadBackend(backend.Backend):
            kind = "local"
            def chat(self, messages):
                return '{"points":[{"text":"瞎编","block":999}]}'
        before = len(list((Path(self.tmp) / "derived").glob("*.refine.md")))
        refine._TASK = {"state": "running", "running": True, "cancelled": False,
                        "events": [], "output": "", "error": None}
        with mock.patch.object(backend, "load_config",
                               return_value={"mode": backend.MODE_LLM,
                                             "kind": backend.KIND_LOCAL,
                                             "allow_suppplement": False}):
            refine._run_refine_inner(str(src), "", str(self.tmp), BadBackend({}), cap)
        after = len(list((Path(self.tmp) / "derived").glob("*.refine.md")))
        self.assertEqual(after, before, "全无效输出仍产出了文档（违反零产物红线）")
        self.assertEqual(refine.status()["state"], "failed")

        # 端点形状：start 支持 outdir，status 支持 since
        app_src = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('data.get("outdir")', app_src.split("/api/refine/start")[1][:300])
        self.assertIn("refine.status(since)", app_src)

    # ------------------------------------------------------------------ #
    # 50) S7c 修订双产物：同源渲染 / 标记完整性 / 反编造 / WCAG AA
    # ------------------------------------------------------------------ #
    def test_50_s7c_revise_dual_output(self):
        import backend
        import refine
        import revise_engine as R
        import refine_engine
        from unittest import mock

        core_md = ("<!-- src: x -->\n## 核心知识点\n\n"
                   "<!-- anchor: doc_abc123456789 | block: 2 -->\n- 注重隐私（来源块 2）\n\n"
                   "<!-- anchor: doc_abc123456789 | block: 4 -->\n- 本地处理（来源块 4）\n")
        cores = R.parse_core(core_md)
        self.assertEqual([c["block"] for c in cores], [2, 4])
        # anchor 块号与「来源块」不一致的脏数据应被跳过
        dirty = ("<!-- anchor: doc_abc123456789 | block: 2 -->\n- 文本（来源块 9）\n")
        self.assertEqual(R.parse_core(dirty), [])

        # 解析变更：编造块/错误 type/old 不匹配 一律丢弃
        resp = json.dumps({"changes": [
            {"type": "add", "block": 2, "text": "尤其零依赖"},
            {"type": "modify", "block": 4, "old": "本地处理", "text": "全程离线处理"},
            {"type": "add", "block": 999, "text": "编造块"},
            {"type": "delete", "block": 2, "text": "非法类型"},
            {"type": "modify", "block": 4, "old": "错误的原文", "text": "改"},
        ]})
        changes, skipped = R.parse_changes(resp, cores)
        self.assertEqual(len(changes), 2)
        self.assertEqual(skipped, 3)

        # 双产物同源渲染 + 标记完整性
        meta = {"stem": "x", "doc_id": "doc_abc123456789",
                "backend_kind": "cloud", "model": "m", "skipped": skipped}
        md_out, html_out = R.render_both(cores, changes, meta)
        ok, why = R.verify_marks(changes, md_out, html_out)
        self.assertTrue(ok, "标记完整性校验失败：%s" % why)
        # S8：补写（add）已改为独立分区 + `[AI ++ … ++]` 专用标记
        self.assertIn("[AI ++ 尤其零依赖 ++]", md_out)
        self.assertIn("## AI 补充（模型生成，请核对）", md_out, "补写未落在独立分区")
        self.assertNotIn("[AI ++ 尤其零依赖 ++]",
                         md_out.split("## AI 补充")[0],
                         "补写内容混进了核心区")
        self.assertIn("[[~~ 本地处理 ~~ → 全程离线处理]]", md_out)
        self.assertIn('class="ai-item"', html_out)
        self.assertIn('text-decoration:line-through', html_out)
        # 篡改任一份产物都应被校验抓出
        self.assertFalse(R.verify_marks(changes, md_out.replace("尤其零依赖", "被改"), html_out)[0])
        self.assertFalse(R.verify_marks(changes, md_out, html_out.replace("+ 尤其零依赖", "+ 被改"))[0])

        # WCAG AA：颜色常量对比度实算
        def lum(h):
            h = h.lstrip("#")
            ch = [int(h[i:i+2], 16)/255 for i in (0, 2, 4)]
            f = lambda c: c/12.92 if c <= 0.03928 else ((c+0.055)/1.055)**2.4
            r, g, b = [f(c) for c in ch]
            return 0.2126*r + 0.7152*g + 0.0722*b
        def ratio(a, b):
            l1, l2 = sorted([lum(a), lum(b)], reverse=True)
            return (l1+0.05)/(l2+0.05)
        self.assertGreaterEqual(ratio(R.C_AI_FG, R.C_AI_BG), 4.5, "AI 补写字色未达 AA")
        self.assertGreaterEqual(ratio(R.C_MOD_OLD, "#FFFFFF"), 4.5, "修改前字色未达 AA")
        self.assertGreaterEqual(ratio(R.C_MOD_NEW, "#FFFFFF"), 4.5, "修改后字色未达 AA")
        self.assertGreaterEqual(ratio(R.C_TEXT, "#FFFFFF"), 4.5, "原文黑未达 AA")

        # 端到端：mock 后端跑修订，落双产物 + provenance，冻结盘只读
        class FakeRevise(backend.Backend):
            kind = "cloud"
            def chat(self, messages):
                return resp
        derived = Path(self.tmp) / "derived"
        derived.mkdir(exist_ok=True)
        core_file = derived / "doc_abc123456789.refine.md"
        core_file.write_text(core_md, encoding="utf-8")
        refine_engine.append_provenance(self.tmp, {"capability": "prior2", "status": "历史"})
        cap = {"tools": {"backend": {"kind": "cloud"}}, "capability": "available"}
        refine._TASK = {"state": "running", "running": True, "cancelled": False,
                        "events": [], "output": "", "error": None}
        # S8 起修订按 mode 分流；本用例守的是 **LLM 双产物路径**，显式切 llm 模式。
        # 补写开关开启，才能验「changes 里每条（含补写）都在两份落盘产物中」——
        # 开关关闭时 add 被丢弃，那是 S8c 的另一条契约（由 test_54 守）。
        with mock.patch.object(backend, "load_config",
                               return_value={"mode": backend.MODE_LLM,
                                             "kind": backend.KIND_CLOUD,
                                             "allow_suppplement": True}):
            refine._run_revise_inner(str(core_file), "m", str(self.tmp), FakeRevise({}), cap)
        st = refine.status()
        self.assertEqual(st["state"], "done", "修订失败：%s" % st["error"])
        md_path = Path(st["output"])
        html_path = md_path.with_name(md_path.name.replace(".revise.md", ".revise.html"))
        self.assertTrue(md_path.is_file() and html_path.is_file(), "双产物未落盘")
        self.assertIn("<html", html_path.read_text(encoding="utf-8"))
        prov = refine_engine.load_provenance(Path(self.tmp))
        entries = prov.get("entries") or []
        self.assertEqual(len(entries), 2, "provenance 未读旧追加")
        self.assertEqual(entries[1]["stage"], "revise")
        self.assertFalse((Path(self.tmp) / "md").exists(), "冻结盘被创建")
        # 同源：changes 里的每条标记都在两份落盘产物中
        ok2, _ = R.verify_marks(changes, md_path.read_text(encoding="utf-8"),
                                html_path.read_text(encoding="utf-8"))
        self.assertTrue(ok2, "落盘双产物标记不一致")

        # 全无效 → 零产物
        class BadRevise(backend.Backend):
            kind = "cloud"
            def chat(self, messages):
                return '{"changes":[{"type":"add","block":999,"text":"瞎编"}]}'
        n_before = len(list(derived.glob("*.revise.md")))
        refine._TASK = {"state": "running", "running": True, "cancelled": False,
                        "events": [], "output": "", "error": None}
        with mock.patch.object(backend, "load_config",
                               return_value={"mode": backend.MODE_LLM,
                                             "kind": backend.KIND_CLOUD,
                                             "allow_suppplement": False}):
            refine._run_revise_inner(str(core_file), "", str(self.tmp), BadRevise({}), cap)
        self.assertEqual(len(list(derived.glob("*.revise.md"))), n_before,
                         "全无效修订仍产出文档")
        self.assertEqual(refine.status()["state"], "failed")

        # 端点：revise/start 透传 outdir 与 instruction
        app_src = (ROOT / "app.py").read_text(encoding="utf-8")
        seg = app_src.split("/api/revise/start")[1][:400] if "/api/revise/start" in app_src else ""
        self.assertIn("outdir", seg)
        self.assertIn("instruction", seg)

    # ------------------------------------------------------------------ #
    # 51) S7d UI：导航两项 + 配置页 + 精读/修订页 + 产物只读安全
    # ------------------------------------------------------------------ #
    def test_51_s7d_ui(self):
        html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "ui" / "app.css").read_text(encoding="utf-8")
        app_src = (ROOT / "app.py").read_text(encoding="utf-8")

        # ① 导航两项 + 页面容器
        for page in ("refine", "revise"):
            self.assertIn('data-page="%s"' % page, html, "导航缺少 %s" % page)
            self.assertIn('id="page-%s"' % page, html, "缺页面容器 %s" % page)
            self.assertIn("%s: $(" % page, js, "pages 映射缺 %s" % page)
            self.assertIn("%s: { title:" % page, js, "PAGE_META 缺 %s" % page)
        # 既有三项仍在（不破坏 test_06 守护的导航结构）
        for page in ("home", "settings", "about"):
            self.assertIn('data-page="%s"' % page, html)

        # ② 后端配置表单：类型/端点/key/model + 脱敏提示 + key 用 password
        for fid in ("beKind", "beEndpoint", "beApiKey", "beModel"):
            self.assertIn('id="%s"' % fid, html, "缺配置字段 %s" % fid)
        self.assertIn('id="beApiKey" class="text-input set-wide" type="password"', html,
                      "API key 输入框必须是 password 类型")
        self.assertIn("留空 = 保留原密钥", html, "缺密钥脱敏/保留提示")
        self.assertIn("配置即视为知情同意", html, "云端外传缺知情同意告知")

        # ③ 精读/修订页控件 + aria-label（可访问性，沿用 A1/A2 修复）
        for fid in ("refineSource", "btnStartRefine", "btnCancelRefine", "refinePreview",
                    "reviseSource", "reviseInstruction", "btnStartRevise",
                    "revisePreviewHtml", "revisePreviewMd"):
            self.assertIn('id="%s"' % fid, html, "缺控件 %s" % fid)
        for label in ("精读来源 md 路径", "修订来源 refine.md 路径",
                      "修订额外要求", "精读后端类型", "后端接口地址", "后端 API 密钥"):
            self.assertIn('aria-label="%s"' % label, html, "缺 aria-label：%s" % label)
        self.assertIn("iframe", html)
        self.assertIn('sandbox=""', html, "彩色预览 iframe 必须 sandbox 隔离")
        self.assertIn("srcdoc", js, "彩色预览应走 srcdoc（经只读端点取文本）")

        # ④ JS 调端点正确：GET 传 undefined（api() 靠 body===undefined 判 GET）
        self.assertIn('api("/api/refine/backend", undefined', js,
                      "GET backend 必须传 undefined")
        self.assertIn('api("/api/refine/models", undefined', js,
                      "GET models 必须传 undefined")
        # status 带 since 查询串：api("/api/refine/status?since=" + N, undefined, …)
        status_line = [ln for ln in js.splitlines() if 'api("/api/refine/status' in ln]
        self.assertTrue(status_line, "未调用 status 端点")
        self.assertIn("undefined", status_line[0], "GET status 必须传 undefined")
        self.assertIn('api("/api/refine/start"', js)
        self.assertIn('api("/api/revise/start"', js)
        self.assertIn('api("/api/refine/cancel"', js)
        self.assertIn('api("/api/refine/artifact?path="', js, "预览须走只读产物端点")
        # 打开按钮走专用端点，不动 /api/open 白名单
        self.assertIn('api("/api/refine/open"', js)
        self.assertNotIn('api("/api/open", { path: p }', js)

        # ⑤ CSS：新样式存在且不破坏焦点环/reduced-motion 契约
        for cls in (".result-box", ".preview-frame", ".preview-md", ".bar-warn", ".bar-ok"):
            self.assertIn(cls, css, "缺样式 %s" % cls)
        self.assertIn("outline: 2px solid #185FA5", css, "焦点环被破坏")
        self.assertIn("@media (prefers-reduced-motion: reduce)", css)

        # ⑥ artifact 只读端点的安全边界（真实 HTTP）
        srv = self.start()
        # 任意路径必须拒绝
        st, obj = srv.get_json("/api/refine/artifact?path=" +
                               urllib.parse.quote(str(Path(self.tmp) / "outside.md")))
        self.assertEqual(st, 200)
        self.assertIs(obj["ok"], False, "非 derived 路径应拒绝")
        self.assertIn("derived", obj["error"])
        # 合法 derived 产物可读
        derived = Path(self.tmp) / "derived"
        derived.mkdir(exist_ok=True)
        good = derived / "doc_abc123456789.refine.md"
        good.write_text("# 精读产物\n核心内容", encoding="utf-8")
        st, obj = srv.get_json("/api/refine/artifact?path=" + urllib.parse.quote(str(good)))
        self.assertEqual(st, 200)
        self.assertTrue(obj["ok"])
        self.assertIn("核心内容", obj["text"])
        # 非 md/html 后缀拒绝
        bad = derived / "evil.exe"
        bad.write_bytes(b"MZ")
        st, obj = srv.get_json("/api/refine/artifact?path=" + urllib.parse.quote(str(bad)))
        self.assertIs(obj["ok"], False, "非 md/html 应拒绝")
        # /api/open 白名单未被放宽（derived 产物不能走它）
        st, obj = srv.post_json("/api/open", {"path": str(good)})
        self.assertIs(obj["ok"], False, "/api/open 白名单被放宽了")
        # 端点存在
        self.assertIn('path == "/api/refine/artifact"', app_src)
        self.assertIn('path == "/api/refine/open"', app_src)

    # ------------------------------------------------------------------ #
    # 52) S8 可信提纯：抽取式不造假 / 补写开关默认关闭且隔离标注
    # ------------------------------------------------------------------ #
    def test_52_s8_trusted_extract(self):
        import backend
        import extract_engine as X
        import refine
        from unittest import mock

        md = ("# 精核项目说明\n\n"
              "本项目是一款本地优先的文档处理工具，强调零依赖与内容不外传。\n\n"
              "## 技术架构\n\n"
              "系统采用五层架构：输入来源、解析与安全、能力适配、后处理编排、产物契约。\n\n"
              "冻结内核不得修改，新能力一律以独立模块挂载在后处理层。\n\n"
              "## 关键约束\n\n"
              "单文件 exe 体积恒定约 9MB，模型与工具一律不打包进程序。\n\n"
              "后端可插拔，Local 模式内容不出本机，Cloud 模式由客户显式配置。\n")

        # ① A 档红线：每条核心必须能在原文逐字定位（架构级不造假）
        r = X.extract_core(md, top_k=6)
        self.assertTrue(r["points"], "抽取式未选出任何核心")
        ok, why = X.verify_traceable(md, r["points"])
        self.assertTrue(ok, "核心无法在原文逐字定位：%s" % why)
        # 篡改一条即校验失败（证明校验真的在起作用）
        bad = [dict(p) for p in r["points"]]
        bad[0]["text"] = "这是模型编造的内容"
        self.assertFalse(X.verify_traceable(md, bad)[0],
                         "编造内容竟然通过了可回溯校验")

        # ② 纯章节标签不进候选（有下位正文承载的短标题）
        heads = [p["text"] for p in r["points"]]
        self.assertNotIn("技术架构", heads, "纯标题被当作核心条目")
        self.assertNotIn("关键约束", heads, "纯标题被当作核心条目")

        # ③ 零第三方依赖：抽取引擎不得引入第三方模块
        src = (ROOT / "extract_engine.py").read_text(encoding="utf-8")
        for bad_mod in ("import numpy", "import scipy", "import jieba",
                        "import networkx", "import sklearn", "import torch"):
            self.assertNotIn(bad_mod, src, "抽取引擎引入了第三方依赖：%s" % bad_mod)
        # 抽取引擎只用标准库
        import ast
        tree = ast.parse(src)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    imported.add(a.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        std = {"math", "re", "time", "pathlib", "__future__", "media_runtime"}
        self.assertTrue(imported <= std,
                        "抽取引擎出现非标准库导入：%s" % (imported - std))

        # ④ extract 是内置引擎，绝不进 TOOL_SPECS
        import media_tools
        self.assertEqual([s[0] for s in media_tools.TOOL_SPECS],
                         ["ffmpeg", "whisper", "yt-dlp"])
        self.assertNotIn("extract", [s[0] for s in media_tools.TOOL_SPECS])

        # ⑤ 配置默认：mode=extract、补写开关关闭
        with mock.patch.object(backend, "CONFIG_FILE", Path(self.tmp) / "be.json"), \
             mock.patch.object(backend, "_CACHE", None):
            backend.save_config({})
            cfg = backend.load_config(refresh=True)
            self.assertEqual(cfg["mode"], backend.MODE_EXTRACT, "默认模式应为抽取式")
            self.assertIs(cfg["allow_suppplement"], False, "补写开关必须默认关闭")
            # extract 模式恒可用（零配置，不需装 ollama / 不填 key）
            probe = backend.probe_current(refresh=True)
            self.assertTrue(probe["available"], "抽取式引擎应恒可用")
            self.assertEqual(probe["kind"], "extract")

        # ⑥ 补写必须隔离：独立分区 + 强制标注 + 不带锚点
        core_lines = ["- 要点一", "- 要点二"]
        md_text = "\n".join(["## 核心知识点", ""] + core_lines +
                            ["", "## 提纯元数据", "- x"])
        supp = refine._append_supplement(md_text, ["[AI ++ 补充内容 ++]（缺前置条件）"])
        self.assertIn("AI 补充（模型生成，请核对）", supp, "缺补写独立分区")
        self.assertIn("[AI ++ 补充内容 ++]", supp, "补写缺 AI 标记")
        self.assertIn("原文并不存在", supp, "缺诚实告知")
        # 补写分区必须在元数据之前，且核心分区内容未被污染
        self.assertLess(supp.index("AI 补充"), supp.index("## 提纯元数据"))
        self.assertIn("- 要点一", supp)
        self.assertNotIn("[++ ", supp, "补写混用了修订的新增标记")

        # ⑦ 补写开关关闭时不产出补写内容
        with mock.patch.object(backend, "CONFIG_FILE", Path(self.tmp) / "be2.json"), \
             mock.patch.object(backend, "_CACHE", None):
            backend.save_config({"mode": backend.MODE_LLM, "kind": "cloud",
                                 "endpoint": "https://x/v1", "api_key": "k",
                                 "allow_suppplement": False})
            cfg = backend.load_config(refresh=True)
            self.assertIs(cfg["allow_suppplement"], False)
            # 开关关闭 → 补写函数即使被调用也不应产出（此处验证配置读取路径）
            self.assertIn("allow_suppplement", backend.public_config())

        # ⑧ extract 模式端到端：产出 .refine.md，含逐字可回溯 + 保真度声明
        outdir = Path(self.tmp) / "s8out"
        src_md = Path(self.tmp) / "来源.md"
        src_md.write_text(md, encoding="utf-8")
        with mock.patch.object(backend, "CONFIG_FILE", Path(self.tmp) / "be3.json"), \
             mock.patch.object(backend, "_CACHE", None):
            backend.save_config({"mode": backend.MODE_EXTRACT})
            refine._TASK = {"state": "running", "running": True, "cancelled": False,
                            "events": [], "output": "", "error": None}
            refine._run_refine_inner(str(src_md), "", str(outdir),
                                     backend.current_backend(), refine.capability())
            st = refine.status()
            self.assertEqual(st["state"], "done", "抽取式提纯失败：%s" % st["error"])
            out = Path(st["output"])
            self.assertTrue(out.is_file())
            text = out.read_text(encoding="utf-8")
            self.assertIn("<!-- src:", text, "缺 8 字段来源注释")
            self.assertIn("<!-- anchor:", text, "核心缺块级锚点")
            self.assertIn("原文原句", text, "缺逐字可回溯的保真度声明")
            self.assertIn("可信提纯", text)
            # 产物里的每条核心都必须在源文件里找得到
            core_section = text.split("## 核心知识点")[1].split("## 提纯元数据")[0]
            for line in core_section.splitlines():
                line = line.strip()
                if line.startswith("- ") and not line.startswith("- 源"):
                    body = line[2:].split("（来源块")[0].strip()
                    if body and body not in md:
                        self.fail("产物核心无法在原文定位：%s" % body)
            # 冻结盘未动
            self.assertFalse((outdir / "md").exists())
            self.assertFalse((outdir / "INDEX.md").exists())

        # ⑨ probe 顶层 refine 仍含 backend 子结构（既有契约不回退）
        app_src = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('data["refine"] = refine.capability', app_src)
        self.assertIn("allow_suppplement", app_src, "app.py 未透传补写开关")

        # ⑩ UI：模式选择 + 补写开关（默认关）+ 抽取式提示
        html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="beMode"', html, "缺提纯模式选择")
        self.assertIn('value="extract"', html, "缺抽取式模式选项")
        self.assertIn('value="llm"', html, "缺 LLM 模式选项")
        self.assertIn('id="beAllowSupplement"', html, "缺 AI 补写开关")
        self.assertIn('id="beLlmHint"', html, "缺抽取式说明提示")
        self.assertIn('aria-label="提纯模式"', html, "缺 aria-label")
        self.assertIn('aria-label="允许 AI 补写"', html, "缺 aria-label")
        # JS：读写 mode 与开关，并随模式置灰 LLM 字段
        self.assertIn("mode:", js, "JS 未提交 mode")
        self.assertIn("allow_suppplement:", js, "JS 未提交补写开关")
        self.assertIn("applyBackendMode", js, "JS 未按模式置灰字段")
        # 补写开关默认不勾选（HTML 里 checked 不应出现）
        supp_tag = [ln for ln in html.splitlines() if 'id="beAllowSupplement"' in ln]
        self.assertTrue(supp_tag)
        self.assertNotIn("checked", supp_tag[0], "补写开关默认不应勾选")

    # ------------------------------------------------------------------ #
    # 53) S8b：B 档原文内改写（白名单） + 修订按模式分流 + UI 联动
    # ------------------------------------------------------------------ #
    def test_53_s8b_rewrite_in_source(self):
        import backend
        import extract_engine as X
        import refine
        import revise_engine as R
        from unittest import mock

        md = ("# 数据一致性\n\n"
              "本系统保证数据一致性，所有数据一致性约束均已实现。\n\n"
              "零依赖是核心约束，零依赖设计贯穿全系统。\n\n"
              "数据一致性机制依赖架构分层。\n")

        # ① B 档白名单：只动结构与措辞，**不改事实**
        # 注意：pts 的文本必须逐字取自 md（与真实流程一致），否则校验会正确地报红
        pts = [
            {"text": "本系统保证数据一致性，所有数据一致性约束均已实现。",
             "block": 2, "keywords": ["一致性", "约束"], "score": 0.9, "reasons": []},
            {"text": "本系统保证数据一致性，所有数据一致性约束均已实现。",
             "block": 7, "keywords": ["一致性", "约束"], "score": 0.8, "reasons": []},
            {"text": "数据一致性机制依赖架构分层。",
             "block": 9, "keywords": ["依赖", "分层"], "score": 0.2, "reasons": []},
        ]
        rw = X.rewrite_in_source(pts)
        # 合并去重：两条重复的合成一条，块号并列
        self.assertEqual(len(rw["points"]), 2, "重复核心未被合并")
        self.assertEqual(rw["points"][0]["blocks"], [2, 7], "合并后块号未并列")
        self.assertEqual(rw["points"][0]["merged"], 2)
        self.assertEqual(rw["stats"]["merged"], 1)
        # 合并结果仍由原文构成（用 ｜ 连接，不重写）
        self.assertIn(" ｜ ", rw["points"][0]["text"])
        # B 档红线：每个片段都能在原文定位
        ok, why = X.verify_no_new_content(md, rw["points"])
        self.assertTrue(ok, "B 档引入了原文没有的内容：%s" % why)
        # 篡改一条即失败（证明校验有效）
        bad = [dict(rw["points"][0]), dict(rw["points"][1])]
        bad[0]["text"] = "这句原文里根本没有"
        self.assertFalse(X.verify_no_new_content(md, bad)[0])

        # ② 术语归一：相似写法统一到高频写法，且**不产生新词**
        norm_pts = [{"text": "数据一致性", "block": 1, "keywords": ["数据一致性"], "score": 1},
                    {"text": "数据一致性", "block": 2, "keywords": ["一致性"], "score": 1}]
        nt = X.normalize_terms(norm_pts)
        self.assertTrue(all(t in ("数据一致性", "一致性")
                            for p in nt for t in p["keywords"]))

        # ③ 排版归一默认**不做**（会破坏逐字定位）；显式开启仍通过红线
        # 文本取自 md 原文（含全角逗号），排版归一只把它变成半角
        base = [{"text": "本系统保证数据一致性，所有数据一致性约束均已实现。",
                 "block": 2, "keywords": [], "score": 1}]
        self.assertNotIn("排版归一", X.rewrite_in_source(base)["stats"]["ops"],
                         "排版归一不应默认执行")
        self.assertIn("排版归一",
                      X.rewrite_in_source(base, punct_normalize=True)["stats"]["ops"])
        self.assertTrue(X.verify_no_new_content(md, X.rewrite_in_source(
            base, punct_normalize=True)["points"])[0],
            "排版归一（仅标点）不应被判为新增内容")

        # ④ 修订按模式分流：extract 模式走 B 档，绝不调 LLM
        cores_md = ("<!-- src: x -->\n## 核心知识点\n\n"
                    "<!-- anchor: doc_abc123456789 | block: 2 -->\n- 注重隐私（来源块 2）\n\n"
                    "<!-- anchor: doc_abc123456789 | block: 4 -->\n- 本地处理（来源块 4）\n")
        outdir = Path(self.tmp) / "s8b"
        (outdir / "derived").mkdir(parents=True, exist_ok=True)
        core_file = outdir / "derived" / "doc_abc123456789.refine.md"
        core_file.write_text(cores_md, encoding="utf-8")
        with mock.patch.object(backend, "CONFIG_FILE", Path(self.tmp) / "be.json"), \
             mock.patch.object(backend, "_CACHE", None):
            backend.save_config({"mode": backend.MODE_EXTRACT})
            refine._TASK = {"state": "running", "running": True, "cancelled": False,
                            "events": [], "output": "", "error": None}
            refine._run_revise_inner(str(core_file), "", str(outdir),
                                     backend.current_backend(), refine.capability(), "")
            st = refine.status()
            self.assertEqual(st["state"], "done", "extract 模式修订失败：%s" % st["error"])
            md_path = Path(st["output"])
            text = md_path.read_text(encoding="utf-8")
            # 双产物
            html_path = md_path.with_name(md_path.name.replace(".revise.md", ".revise.html"))
            self.assertTrue(md_path.is_file() and html_path.is_file(), "双产物未落盘")
            # 锚点必须保留（红线）
            self.assertIn("<!-- anchor:", text, "B 档产物丢了块级锚点")
            # 文案必须说清是「原文内改写」而非「原文原句」
            self.assertIn("原文内改写", text)
            self.assertIn("未改事实", text)
            # 产物内容必须源自精读产物的核心
            self.assertIn("注重隐私", text)
            self.assertIn("本地处理", text)
            # 冻结盘只读
            self.assertFalse((outdir / "md").exists())
            self.assertFalse((outdir / "INDEX.md").exists())

        # ⑤ capability 的 engine 说明按模式区分
        with mock.patch.object(backend, "CONFIG_FILE", Path(self.tmp) / "be2.json"), \
             mock.patch.object(backend, "_CACHE", None):
            backend.save_config({"mode": backend.MODE_EXTRACT})
            cap = refine.capability(refresh=True)
            self.assertTrue(cap["enabled"], "抽取式模式应恒可用")
            self.assertEqual(cap["engine"]["mode"], backend.MODE_EXTRACT)
            self.assertIn("抽取式", cap["engine"]["name"])
            self.assertIn("不造假", cap["engine"]["reason"])

        # ⑥ UI 模式联动
        html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="refineSub"', html, "缺精读页模式说明元素")
        self.assertIn('id="reviseSub"', html, "缺修订页模式说明元素")
        self.assertIn("applyBackendMode", js)
        # extract 模式置灰模型下拉与额外要求
        self.assertIn("el.refineModel.disabled = !llm", js, "模型下拉未按模式置灰")
        self.assertIn("el.reviseInstruction.disabled = !llm", js, "额外要求未按模式置灰")
        # 初始化即联动（首屏控件状态正确）
        self.assertIn('api("/api/refine/backend", undefined, 10000)', js)

    # ------------------------------------------------------------------ #
    # 54) S8c：C 档补写 —— 开关真正生效 + 独立分区隔离 + 双产物同步
    # ------------------------------------------------------------------ #
    def test_54_s8c_supplement_isolation(self):
        import backend
        import json as _json
        import refine
        import revise_engine as R
        from unittest import mock

        cores = [{"block": 2, "text": "注重隐私"}, {"block": 4, "text": "本地处理"}]
        resp = _json.dumps({"changes": [
            {"type": "add", "block": 2, "text": "尤其零依赖"},
            {"type": "modify", "block": 4, "old": "本地处理", "text": "全程离线处理"},
        ]})

        # ① 开关关闭 → add（补写）类变更必须被丢弃，不能只是「提示核对」
        off, off_skipped = R.parse_changes(resp, cores, allow_suppplement=False)
        self.assertEqual(len(off), 1, "开关关闭却保留了补写变更")
        self.assertEqual(off[0]["type"], "modify")
        self.assertEqual(off_skipped, 1, "丢弃数未计入补写项")
        md_off, html_off = R.render_both(cores, off, {
            "stem": "t", "doc_id": "doc_abc123456789", "skipped": off_skipped})
        self.assertNotIn("尤其零依赖", md_off, "开关关闭却产出了补写内容")
        self.assertNotIn("## AI 补充", md_off)
        self.assertTrue(R.verify_marks(off, md_off, html_off)[0])

        # ② 开关开启 → 补写进**独立分区**，标记专用，绝不与核心混同
        on, on_skipped = R.parse_changes(resp, cores, allow_suppplement=True)
        self.assertEqual(len(on), 2)
        md_on, html_on = R.render_both(cores, on, {
            "stem": "t", "doc_id": "doc_abc123456789", "skipped": on_skipped})
        ok, why = R.verify_marks(on, md_on, html_on)
        self.assertTrue(ok, "补写隔离校验失败：%s" % why)
        self.assertIn("## AI 补充（模型生成，请核对）", md_on)
        self.assertIn("[AI ++ 尤其零依赖 ++]", md_on)
        # 核心区里绝不能出现补写内容
        self.assertNotIn("尤其零依赖", md_on.split("## AI 补充")[0],
                         "补写内容混进了核心区")
        # 头部诚实告知
        self.assertIn("本文件含模型生成内容", md_on)
        self.assertIn("原文并不存在", md_on)
        # html 同步隔离
        self.assertIn('class="ai-item"', html_on)
        self.assertIn("本文件含模型生成内容", html_on)

        # ③ 隔离标记被破坏 → 校验必须抓出（防止"混同"悄悄发生）
        broken = md_on.replace("[AI ++ 尤其零依赖 ++]", "尤其零依赖")
        self.assertFalse(R.verify_marks(on, broken, html_on)[0],
                         "补写失去隔离标记却通过了校验")

        # ④ 补写项**不声明块锚点**（它不对应任何原文块）
        ai_zone = md_on.split("## AI 补充")[1]
        self.assertNotIn("<!-- anchor:", ai_zone,
                         "补写项不应声明块锚点")

        # ⑤ 端到端：LLM 模式 + 开关开启 → 产物含独立补写分区
        outdir = Path(self.tmp) / "s8c"
        (outdir / "derived").mkdir(parents=True, exist_ok=True)
        core_file = outdir / "derived" / "doc_abc123456789.refine.md"
        core_file.write_text(
            "<!-- src: x -->\n## 核心知识点\n\n"
            "<!-- anchor: doc_abc123456789 | block: 2 -->\n- 注重隐私（来源块 2）\n\n"
            "<!-- anchor: doc_abc123456789 | block: 4 -->\n- 本地处理（来源块 4）\n",
            encoding="utf-8")

        class FakeLLM(backend.Backend):
            kind = "cloud"
            def chat(self, messages):
                return resp

        cap = {"tools": {"backend": {"kind": "cloud"}}, "capability": "available"}
        for allow, want_supplement in ((True, True), (False, False)):
            with mock.patch.object(backend, "CONFIG_FILE",
                                   Path(self.tmp) / ("be_%s.json" % allow)), \
                 mock.patch.object(backend, "_CACHE", None):
                backend.save_config({"mode": backend.MODE_LLM, "kind": "cloud",
                                     "endpoint": "https://x/v1", "api_key": "k",
                                     "allow_suppplement": allow})
                refine._TASK = {"state": "running", "running": True,
                                "cancelled": False, "events": [],
                                "output": "", "error": None}
                refine._run_revise_inner(str(core_file), "m", str(outdir),
                                         FakeLLM({}), cap, "")
                st = refine.status()
                self.assertEqual(st["state"], "done",
                                 "修订失败：%s" % st["error"])
                text = Path(st["output"]).read_text(encoding="utf-8")
                if want_supplement:
                    self.assertIn("## AI 补充（模型生成，请核对）", text)
                    self.assertIn("尤其零依赖", text)
                    self.assertIn("本文件含模型生成内容", text)
                else:
                    self.assertNotIn("尤其零依赖", text,
                                     "补写开关关闭却产出了补写内容")
                    self.assertNotIn("## AI 补充", text)
                # 两种情况核心修改都必须在
                self.assertIn("全程离线处理", text)

        # ⑥ 契约一致性：配置键名贯通 backend / app / refine
        bsrc = (ROOT / "backend.py").read_text(encoding="utf-8")
        asrc = (ROOT / "app.py").read_text(encoding="utf-8")
        rsrc = (ROOT / "refine.py").read_text(encoding="utf-8")
        for name, src in (("backend", bsrc), ("app", asrc), ("refine", rsrc)):
            self.assertIn("allow_suppplement", src,
                          "%s 未贯通补写开关" % name)
        # 补写开关默认关闭
        self.assertIn('"allow_suppplement": False', bsrc)


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
