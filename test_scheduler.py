#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S13 应用内订阅调度 + Electron 托盘契约 · 回归测试。

守护：
1. 调度器 daemon 线程启停幂等、启动补跑 due、单实例不抢锁、失败不中断；
2. 托盘改造：关窗 hide 到托盘、真正退出才回收、旧进程回收符号全保留；
3. 接线（app/UI/build/CI/门禁）完整。
"""
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class TestScheduler(unittest.TestCase):

    def setUp(self):
        import subscription_scheduler as SC
        self.SC = SC
        SC.stop()  # 确保干净起点

    def tearDown(self):
        self.SC.stop()

    def test_01_start_stop_idempotent(self):
        SC = self.SC
        out = str(Path(tempfile.mkdtemp()))
        # 用极慢 tick + 可打断 sleep，避免真跑调度
        gate = threading.Event()
        def sleep_fn(s): gate.wait(0.02)
        r = SC.start(out, str(Path(tempfile.mkdtemp())),
                     tick=60, start_delay=0, sleep_fn=sleep_fn,
                     due_fn=lambda: [], start_fn=lambda *a, **k: {"ok": True},
                     running_fn=lambda: False)
        self.assertTrue(r["ok"])
        self.assertTrue(SC.status()["running"])
        self.assertTrue(SC.start(out, "x", sleep_fn=sleep_fn)["already_running"])
        gate.set()
        self.assertTrue(SC.stop()["stopped"])
        self.assertFalse(SC.status()["running"])

    def test_02_triggers_due_and_counts(self):
        SC = self.SC
        out = str(Path(tempfile.mkdtemp()))
        fired = []
        done = threading.Event()
        def sleep_fn(s):
            # 不在这里停循环；让主线程在观察到触发后调 stop，避免漏检 due
            done.wait(0.005)
        def due_fn(): return [{"id": "s1"}]
        def start_fn(ids, o, k):
            fired.append(ids)
            done.set()
            return {"ok": True}
        SC.start(out, "kb", tick=10, start_delay=0, sleep_fn=sleep_fn,
                 due_fn=due_fn, start_fn=start_fn, running_fn=lambda: False)
        for _ in range(300):
            if fired: break
            time.sleep(0.01)
        SC.stop()
        self.assertTrue(fired, "due 订阅应被触发")
        self.assertEqual(fired[0], ["s1"])
        self.assertGreaterEqual(SC.status()["triggers"], 1)

    def test_03_no_trigger_while_manual_task_running(self):
        SC = self.SC
        out = str(Path(tempfile.mkdtemp()))
        fired = []
        ticks = {"n": 0}
        def sleep_fn(s):
            ticks["n"] += 1
            time.sleep(0.005)
        SC.start(out, "kb", tick=10, start_delay=0, sleep_fn=sleep_fn,
                 due_fn=lambda: [{"id": "s1"}],
                 start_fn=lambda *a, **k: fired.append(a) or {"ok": True},
                 running_fn=lambda: True)  # 手动任务在跑
        for _ in range(100):
            if ticks["n"] >= 3: break
            time.sleep(0.01)
        SC.stop()
        self.assertEqual(fired, [], "手动任务运行中调度器不应触发")
        self.assertGreaterEqual(ticks["n"], 2)

    def test_04_failure_does_not_kill_loop(self):
        SC = self.SC
        out = str(Path(tempfile.mkdtemp()))
        ticks = {"n": 0}
        def sleep_fn(s):
            ticks["n"] += 1
            time.sleep(0.005)
        SC.start(out, "kb", tick=10, start_delay=0, sleep_fn=sleep_fn,
                 due_fn=lambda: [{"id": "s1"}],
                 start_fn=lambda *a, **k: {"ok": False, "error": "模拟失败"},
                 running_fn=lambda: False)
        for _ in range(100):
            if ticks["n"] >= 3: break
            time.sleep(0.01)
        SC.stop()
        self.assertEqual(SC.status()["last_error"], "模拟失败")
        self.assertGreaterEqual(ticks["n"], 2, "失败后循环应继续")


class TestTrayContract(unittest.TestCase):
    """静态守护：托盘改造不破坏旧的进程回收/自更新时序。"""

    def setUp(self):
        self.js = (ROOT / "electron" / "main.js").read_text(encoding="utf-8")

    def test_10_tray_imports_and_creation(self):
        for sym in ("Tray", "Menu", "nativeImage", "new Tray",
                    "tray.setContextMenu", "tray.setToolTip"):
            self.assertIn(sym, self.js, "托盘缺符号 %s" % sym)

    def test_11_close_hides_to_tray(self):
        self.assertIn("mainWindow.on('close'", self.js)
        self.assertIn("event.preventDefault()", self.js)
        self.assertIn("mainWindow.hide()", self.js)
        self.assertIn("window-all-closed", self.js)
        # 降级：无托盘时仍保持关窗即退
        self.assertIn("if (!tray && !quitting) shutdown()", self.js)

    def test_12_real_exit_only_from_tray_or_before_quit(self):
        self.assertIn("{ label: '退出精核', click: () => shutdown() }", self.js)
        self.assertIn("app.on('before-quit'", self.js)
        self.assertIn("app.on('will-quit'", self.js)

    def test_13_single_instance_restores_hidden_window(self):
        seg = self.js[self.js.index("app.on('second-instance'"):]
        seg = seg[:seg.index("app.whenReady")]
        self.assertIn("showWindow()", seg)
        self.assertIn("if (mainWindow.isMinimized()) mainWindow.restore()",
                      self.js)

    def test_14_old_process_reap_contract_kept(self):
        for sym in ("stopBackendProcesses", "terminateProcessTree(backendPid)",
                    "killStrayBackendProcesses",
                    "adoptedBackendPid = findListenerPid",
                    "terminateProcessTree(adoptedBackendPid)", "cleanupDone"):
            self.assertIn(sym, self.js, "旧进程回收契约被破坏：%s" % sym)

    def test_15_update_install_timing_kept(self):
        install = self.js[self.js.index("ipcMain.handle('update:install'"):]
        install = install[:install.index("ipcMain.handle('update:cancel'")]
        self.assertIn("await stopBackendProcesses()", install)
        self.assertIn("cleanupDone = true", install)
        self.assertIn("quitAndInstall", install)

    def test_16_wiring(self):
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        spec = (ROOT / "build.spec").read_text(encoding="utf-8")
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        gate = (ROOT / "tools" / "check_release.py").read_text(encoding="utf-8")
        self.assertIn("subscription_scheduler", app)
        self.assertIn("/api/sub/scheduler", app)
        self.assertIn("subscription_scheduler", spec)
        self.assertIn("subscription_scheduler.py", gate)
        self.assertIn("test_scheduler", ci)

    def test_17_tray_never_blocks_main_startup(self):
        """打包态可诊断性：托盘失败不得连窗口/后端都开不出来。

        背景（实测）：打包态 Windows GUI 程序无控制台，一旦关键路径抛错，
        用户只看到「双击没反应」。因此要求：
        ① 先建窗口再放托盘；② 托盘整体包在 try/catch 内。
        """
        js = self.js
        when = js[js.index("app.whenReady()"):]
        when = when[:when.index("app.on('window-all-closed'")]
        self.assertLess(when.index("createWindow()"), when.index("createTray()"),
                        "必须先建窗口再建托盘：托盘抛错会连窗口都开不出来")
        self.assertIn("try { createTray(); } catch", when,
                      "托盘创建必须整体兜底，不能让它阻断主流程")
        self.assertIn("function shellLog", js, "缺打包态诊断日志函数")
        self.assertIn("shell.log", js, "诊断日志未落盘")
        # 关键节点都要留痕，否则日志形同虚设
        for node in ("main.js 已加载", "外壳就绪", "启动后端", "托盘已创建"):
            self.assertIn(node, js, "诊断日志缺节点：%s" % node)


if __name__ == "__main__":
    unittest.main()
