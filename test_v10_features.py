
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v0.10 新功能契约测试：默认路径设置 / 组件并发 / OCR 可选增强 / 请求来源校验。"""


# JINGHE_LAYOUT_BOOTSTRAP
import sys as _jinghe_sys
from pathlib import Path as _jinghe_Path
_jinghe_root = _jinghe_Path(__file__).resolve().parent
for _jinghe_sub in ("core", "media", "knowledge", "link", "subs"):
    _jinghe_p = str(_jinghe_root / _jinghe_sub)
    if _jinghe_p not in _jinghe_sys.path:
        _jinghe_sys.path.insert(0, _jinghe_p)
# END JINGHE_LAYOUT_BOOTSTRAP
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class TestDefaultPaths(unittest.TestCase):
    """设置页新增默认输入/输出路径（桌面）。"""

    def test_default_settings_have_both_paths(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        m = re.search(r"DEFAULT_SETTINGS\s*=\s*\{(.*?)\n\}", src, re.S)
        self.assertIsNotNone(m)
        self.assertIn('"default_indir"', m.group(1))
        self.assertIn('"default_outdir"', m.group(1))
        self.assertIn("DEFAULT_DESKTOP", m.group(1))

    def test_desktop_uses_known_folder(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("SHGetKnownFolderPath", src, "应使用 Windows Known Folder 取桌面")
        self.assertIn("FOLDERID_Desktop", src)

    def test_ui_has_both_path_fields(self):
        html = (ROOT / "ui/index.html").read_text(encoding="utf-8")
        self.assertIn('id="setDefaultIndir"', html)
        self.assertIn('id="setDefaultOutdir"', html)
        self.assertIn('id="btnPickIndir"', html)
        self.assertIn('id="btnPickOutdir"', html)

    def test_settings_api_exposes_desktop(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('"default_desktop"', src)


class TestComponentConcurrency(unittest.TestCase):
    """组件安装支持真并发（按 cid 独立 job/令牌）。"""

    def setUp(self):
        import components
        self.c = components

    def test_jobs_is_per_component_dict(self):
        self.assertIsInstance(self.c._JOBS, dict, "_JOBS 应为按组件索引的字典")

    def test_opt_in_set_exists(self):
        self.assertIsInstance(self.c._USER_OPT_INS, set, "并发令牌集合应存在")

    def test_new_job_independent(self):
        a = self.c._new_job("ffmpeg")
        b = self.c._new_job("yt-dlp")
        a["percent"] = 42.0
        self.assertEqual(b["percent"], 0.0, "两个 job 不应共享状态")

    def test_status_all_jobs(self):
        st = self.c.install_status(0, "*")
        self.assertIn("jobs", st)
        self.assertIn("running", st)

    def test_status_with_cid(self):
        st = self.c.install_status(0, "ffmpeg")
        self.assertIn("id", st)
        self.assertEqual(st["id"], "ffmpeg")

    def test_concurrent_tokens_independent(self):
        with self.c._LOCK:
            self.c._USER_OPT_INS.discard("ffmpeg")
            self.c._USER_OPT_INS.discard("yt-dlp")
            self.c._USER_OPT_IN["granted"] = False
            self.c._USER_OPT_IN["component_id"] = ""
            self.c._USER_OPT_INS.add("ffmpeg")
            self.c._USER_OPT_INS.add("yt-dlp")
        # 消费 ffmpeg 不影响 yt-dlp
        self.c._require_opt_in("ffmpeg")
        self.c._require_opt_in("yt-dlp")   # 不应抛异常
        with self.assertRaises(RuntimeError):
            self.c._require_opt_in("ffmpeg")   # 重复消费失败
        with self.c._LOCK:
            self.c._USER_OPT_INS.clear()


class TestOptionalOCR(unittest.TestCase):
    """扫描件 PDF 的 tesseract 可选 OCR 增强。"""

    def setUp(self):
        import pdf_ocr
        self.m = pdf_ocr

    def test_module_is_standalone(self):
        src = (ROOT / "media" / "pdf_ocr.py").read_text(encoding="utf-8")
        self.assertIn("def status", src)
        self.assertIn("def ocr_pdf", src)

    def test_extract_frozen_unchanged(self):
        # OCR 不得写进冻结内核 extract.py
        src = (ROOT / "extract.py").read_text(encoding="utf-8")
        self.assertNotIn("tesseract", src)
        self.assertNotIn("_pdf_ocr", src)

    def test_status_shape(self):
        st = self.m.status()
        self.assertIn("ok", st)
        self.assertIn("available", st)
        self.assertIn("hint", st)
        self.assertIsInstance(st["available"], bool)

    def test_build_spec_has_ocr_module(self):
        spec = (ROOT / "build.spec").read_text(encoding="utf-8")
        self.assertIn("'pdf_ocr'", spec, "pdf_ocr 必须进 hiddenimports")

    def test_no_auto_download_ocr_tool(self):
        # OCR 模块绝不下载工具，只探测本机
        src = (ROOT / "media" / "pdf_ocr.py").read_text(encoding="utf-8")
        self.assertNotIn("pip install", src)
        self.assertNotIn("urlopen", src)


class TestRequestHardening(unittest.TestCase):
    """写操作请求来源校验（CSRF / DNS rebinding 防护）。"""

    def test_check_write_request_exists(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("def _check_write_request", src)
        self.assertIn("def _check_host", src)

    def test_content_type_enforced(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        m = re.search(r"def _check_write_request\(.*?\n    def ", src, re.S)
        self.assertIsNotNone(m)
        body = m.group(0)
        self.assertIn("application/json", body)
        self.assertIn("415", body)

    def test_origin_and_host_checked(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        m = re.search(r"def _check_write_request\(.*?\n    def ", src, re.S)
        self.assertIn('"Origin"', m.group(0))
        self.assertIn("127.0.0.1", m.group(0))
        host = re.search(r"def _check_host\(.*?\n    def ", src, re.S)
        self.assertIsNotNone(host)
        self.assertIn('"Host"', host.group(0))

    def test_get_checks_host(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        m = re.search(r"def do_GET\(.*?\n        try:", src, re.S)
        self.assertIsNotNone(m)
        self.assertIn("_check_host", m.group(0))


class TestElectronProcessReaping(unittest.TestCase):
    """Electron 外壳 + Python 后端的进程树回收（防僵尸 / 防孤儿）。"""

    def setUp(self):
        self.main_js = (ROOT / "electron" / "main.js").read_text(encoding="utf-8")
        self.app_py = (ROOT / "app.py").read_text(encoding="utf-8")

    def test_tree_kill_helper_exists(self):
        js = self.main_js
        self.assertIn("function terminateProcessTree", js)
        self.assertIn("taskkill", js)
        for flag in ("/T", "/F", "/PID"):
            self.assertIn(flag, js)
        self.assertIn("terminateProcessTree(backendPid)", js)
        # PyInstaller onefile 的 Python 子进程会脱离 bootloader 进程树，
        # 必须有按完整路径的兜底清理，且只能匹配 backend 目录。
        self.assertIn("function killStrayBackendProcesses", js)
        self.assertIn("ExecutablePath", js)

    def test_spawn_error_is_handled(self):
        # 没有 error 监听器时，spawn 失败会变成未捕获异常直接崩掉外壳。
        self.assertIn("backend.on('error'", self.main_js)

    def test_adopted_backend_is_reaped(self):
        # 端口上遗留的精核后端必须记录 PID 并在关窗时回收。
        self.assertIn("adoptedBackendPid = findListenerPid", self.main_js)
        self.assertIn("terminateProcessTree(adoptedBackendPid)", self.main_js)

    def test_before_quit_defers_until_cleanup(self):
        js = self.main_js
        self.assertIn("app.on('before-quit'", js)
        self.assertIn("event.preventDefault()", js)
        self.assertIn("cleanupDone", js)

    def test_backend_has_atexit_child_cleanup(self):
        src = self.app_py
        self.assertIn("def _terminate_all_jobs_on_exit", src)
        self.assertIn("atexit.register(_terminate_all_jobs_on_exit)", src)
        for name in ("_JOB", "_AUDIO_JOB", "_VIDEO_JOB", "_UPDATE_JOB"):
            self.assertIn(name, src)

    def test_backend_signal_handlers_registered(self):
        src = self.app_py
        self.assertIn("def _on_exit_signal", src)
        self.assertIn("signal.signal(_sig, _on_exit_signal)", src)

    def test_media_tools_tree_kill_kept(self):
        src = (ROOT / "media" / "media_tools.py").read_text(encoding="utf-8")
        self.assertIn("def terminate_process_tree", src)
        self.assertIn('"taskkill"', src)

    def test_uninstaller_removes_app_asar(self):
        pkg = (ROOT / "electron" / "package.json").read_text(encoding="utf-8")
        self.assertIn('"include": "installer.nsh"', pkg)
        nsh = (ROOT / "electron" / "installer.nsh").read_text(encoding="utf-8")
        self.assertIn("!macro customUnInstall", nsh)
        self.assertIn("app.asar", nsh)

    def test_uninstaller_prompts_for_data_deletion(self):
        nsh = (ROOT / "electron" / "installer.nsh").read_text(encoding="utf-8")
        self.assertIn("IfSilent", nsh, "静默卸载必须跳过数据删除询问")
        self.assertIn("MB_YESNO", nsh, "交互式卸载必须询问是否删除数据")
        self.assertIn("MB_DEFBUTTON2", nsh, "默认按钮必须是安全选项（否）")
        self.assertIn("jinghe_skip_data_prompt", nsh)
        self.assertIn('RMDir /r "$LOCALAPPDATA\\Jinghe"', nsh)


class TestDataExport(unittest.TestCase):
    """v1.1.9：用户数据导出（设置 / 知识库 / 日志 → zip）。"""

    def test_export_api_routes_wired(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('path == "/api/export-data"', src)
        self.assertIn('path == "/api/pick-export-dest"', src)
        self.assertIn("import zipfile", src)
        self.assertIn("def _api_export_data", src)

    def test_export_uses_stdlib_zipfile(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        m = re.search(r"def _api_export_data\(.*?(?=\n    def |\n    # ---)", src, re.S)
        self.assertIsNotNone(m, "应能定位 _api_export_data 方法体")
        body = m.group(0)
        self.assertIn("zipfile.ZipFile", body)
        self.assertIn("ZIP_DEFLATED", body)
        self.assertIn("settings.json", body)
        self.assertIn('"kb/"', body)
        # 原子写入，避免半截 zip
        self.assertIn(".tmp", body)
        self.assertIn(".replace(", body)

    def test_export_actually_produces_zip(self):
        """用临时目录替换 LOG_DIR/KB_DIR，真实调用导出方法并校验 zip 内容。"""
        import tempfile
        import zipfile as _zipfile
        from unittest import mock

        import app as appmod

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            log_dir = root / "Jinghe"
            kb_dir = log_dir / "kb"
            kb_dir.mkdir(parents=True)
            (log_dir / "settings.json").write_text('{"auto_exit": true}', encoding="utf-8")
            (log_dir / "app.log").write_text("[INFO] hello\n", encoding="utf-8")
            (kb_dir / "kb.sqlite3").write_bytes(b"fake-sqlite-bytes")
            (kb_dir / "note.md").write_text("# note\n", encoding="utf-8")
            dest = root / "backup.zip"

            handler = appmod.Handler.__new__(appmod.Handler)
            with mock.patch.object(appmod, "LOG_DIR", log_dir), \
                 mock.patch.object(appmod, "KB_DIR", kb_dir):
                res = handler._api_export_data(str(dest), include_logs=True)

            self.assertTrue(res.get("ok"), "导出应成功：%s" % res)
            self.assertTrue(dest.is_file(), "zip 文件应生成")
            with _zipfile.ZipFile(dest) as zf:
                names = set(zf.namelist())
            self.assertIn("settings.json", names)
            self.assertIn("kb/kb.sqlite3", names)
            self.assertIn("kb/note.md", names)
            self.assertIn("app.log", names)
            self.assertIn("备份说明.txt", names)
            self.assertEqual(res.get("entries"), 4)

    def test_export_without_logs_excludes_logs(self):
        import tempfile
        import zipfile as _zipfile
        from unittest import mock

        import app as appmod

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            log_dir = root / "Jinghe"
            kb_dir = log_dir / "kb"
            kb_dir.mkdir(parents=True)
            (log_dir / "settings.json").write_text("{}", encoding="utf-8")
            (log_dir / "app.log").write_text("[INFO] x\n", encoding="utf-8")
            (kb_dir / "kb.sqlite3").write_bytes(b"db")
            dest = root / "backup.zip"

            handler = appmod.Handler.__new__(appmod.Handler)
            with mock.patch.object(appmod, "LOG_DIR", log_dir), \
                 mock.patch.object(appmod, "KB_DIR", kb_dir):
                res = handler._api_export_data(str(dest), include_logs=False)

            self.assertTrue(res.get("ok"))
            with _zipfile.ZipFile(dest) as zf:
                names = set(zf.namelist())
            self.assertIn("settings.json", names)
            self.assertIn("kb/kb.sqlite3", names)
            self.assertNotIn("app.log", names, "include_logs=False 时不应打包日志")

    def test_ui_export_button_wired(self):
        html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="btnExportData"', html)
        self.assertIn('id="exportDataStatus"', html)
        js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        self.assertIn('function exportData()', js)
        self.assertIn('api("/api/export-data"', js)
        self.assertIn("btnExportData", js)


class TestShellUpdateIPC(unittest.TestCase):
    """v1.2.0 方案 A：Electron 外壳自更新的 IPC 接入守护。

    只校验静态契约（频道对齐 / 白名单 / dev 守卫 / 双通道互斥 / 进程回收时序），
    不启动真实 updater（依赖外网，不适合作单元测试）。
    """

    def test_main_registers_update_ipc(self):
        js = (ROOT / "electron" / "main.js").read_text(encoding="utf-8")
        for ch in ("update:check", "update:download", "update:install", "update:cancel"):
            self.assertIn("ipcMain.handle('%s'" % ch, js,
                          "主进程缺少 IPC handler：%s" % ch)
        self.assertIn("require('electron-updater')", js, "未引入 electron-updater")
        self.assertIn("autoUpdater.autoDownload = false", js,
                      "必须关闭自动下载，下载时机由用户显式驱动")
        self.assertIn("autoUpdater.autoInstallOnAppQuit = false", js,
                      "必须关闭退出自动安装，避免与关窗回收打架")

    def test_main_dev_guard(self):
        js = (ROOT / "electron" / "main.js").read_text(encoding="utf-8")
        self.assertIn("if (!app.isPackaged)", js, "dev 环境缺少 isPackaged 守卫")
        # 三个真实动作都必须有 dev 守卫；check 分支 dev 返回的是只读提示。
        self.assertGreaterEqual(js.count("if (!app.isPackaged)"), 3,
                                "检查/下载/安装应各有 dev 守卫")

    def test_main_kills_backend_before_install(self):
        js = (ROOT / "electron" / "main.js").read_text(encoding="utf-8")
        install = js[js.index("ipcMain.handle('update:install'"):]
        install = install[:install.index("ipcMain.handle('update:cancel'")]
        self.assertIn("await stopBackendProcesses()", install,
                      "安装前必须先回收后端进程树，否则 NSIS 覆盖 exe 会因占用失败")
        self.assertIn("quitAndInstall", install, "安装入口未调用 quitAndInstall")
        self.assertIn("cleanupDone = true", install,
                      "回收后应放行 before-quit 守卫，避免重复清理")

    def test_main_progress_events_to_renderer(self):
        js = (ROOT / "electron" / "main.js").read_text(encoding="utf-8")
        self.assertIn("function bindUpdaterEvents", js)
        self.assertIn("autoUpdater.on('download-progress'", js)
        self.assertIn("mainWindow.webContents.send(channel, payload)", js,
                      "进度必须经 webContents 回推渲染进程")

    def test_preload_whitelist_no_raw_ipc(self):
        js = (ROOT / "electron" / "preload.js").read_text(encoding="utf-8")
        self.assertIn("contextBridge.exposeInMainWorld('desktopUpdater'", js)
        for m in ("check", "download", "install", "cancel", "onStatus", "onProgress"):
            self.assertIn("%s:" % m, js, "preload 白名单缺少方法：%s" % m)
        # 安全红线：绝不把 ipcRenderer 本体交给页面。
        self.assertNotIn("exposeInMainWorld('desktopUpdater', ipcRenderer", js)
        self.assertNotIn("ipcRenderer: ipcRenderer", js)
        # 回调只回传 payload，不回传 event 对象（防 event.sender 反向操控）。
        self.assertIn("callback(data)", js)
        self.assertIn("function (_event, data)", js)

    def test_channels_aligned_between_preload_and_main(self):
        preload = (ROOT / "electron" / "preload.js").read_text(encoding="utf-8")
        main = (ROOT / "electron" / "main.js").read_text(encoding="utf-8")
        for ch in ("update:check", "update:download", "update:install", "update:cancel",
                   "update:status", "update:progress"):
            self.assertIn("'%s'" % ch, preload, "preload 缺少频道 %s" % ch)
            self.assertIn("'%s'" % ch, main, "主进程缺少频道 %s" % ch)

    def test_frontend_routes_to_shell_updater(self):
        js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        self.assertIn("function hasShellUpdater()", js)
        self.assertIn("window.desktopUpdater && window.desktopUpdater.available", js)
        # 三个入口都优先走外壳通道，浏览器模式回落原 HTTP 通道（测试契约保留）。
        cu = js[js.index("function checkUpdate()"):js.index("function startUpdate()")]
        self.assertIn("hasShellUpdater()", cu, "检查更新未路由到外壳通道")
        self.assertIn('api("/api/update/check", undefined, 20000)', cu,
                      "浏览器回落通道被误删（破坏既有契约）")
        su = js[js.index("function startUpdate()"):js.index("function pollUpdateStatus()")]
        self.assertIn("hasShellUpdater()", su, "启动更新未路由到外壳通道")
        self.assertIn('api("/api/update/start", {}, 20000)', su,
                      "浏览器回落通道被误删")
        self.assertIn("function shellStartUpdate()", js)
        self.assertIn("u.onProgress", js, "前端未订阅下载进度事件")

    def test_backend_shell_guard_disables_replacement(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("def _shell_owns_update()", src)
        self.assertIn('os.environ.get("JINGHE_SHELL"', src)
        start = src[src.index("def _api_update_start"):src.index("def _api_update_cancel")]
        apply = src[src.index("def _api_update_apply"):src.index("def _api_update_status")]
        self.assertIn("_shell_owns_update()", start, "更新启动入口缺少外壳守卫")
        self.assertIn("_shell_owns_update()", apply, "替换入口缺少外壳守卫")

    def test_main_injects_shell_env_to_backend(self):
        js = (ROOT / "electron" / "main.js").read_text(encoding="utf-8")
        self.assertIn("JINGHE_SHELL: 'electron'", js,
                      "主进程未向后端注入外壳标记，双通道互斥失效")

    def test_electron_updater_dependency_pinned(self):
        import json
        import extract
        pkg = json.loads((ROOT / "electron" / "package.json").read_text(encoding="utf-8"))
        # 必须是生产依赖：electron-builder 只把 dependencies 打进 asar，
        # 放 devDependencies 会导致打包后 require('electron-updater') 失败白屏。
        self.assertIn("electron-updater", pkg.get("dependencies", {}),
                      "electron-updater 必须在 dependencies（生产依赖），否则不进 asar")
        self.assertNotIn("electron-updater", pkg.get("devDependencies", {}),
                         "electron-updater 不应在 devDependencies")
        self.assertEqual(pkg["version"], extract.__version__,
                         "package.json 版本与真源不一致，latest.yml 会报错误版本")

    def test_app_icon_single_source_for_install_desktop_tray(self):
        """安装包/桌面/exe/托盘图标三者同源（用户 2026-11-23 裁决）。"""
        import json
        pkg = json.loads((ROOT / "electron" / "package.json").read_text(encoding="utf-8"))
        build = pkg.get("build", {})
        # ① 安装包与桌面快捷方式图标由 electron-builder 从 build/icon.png 生成 ICO
        self.assertEqual(build.get("win", {}).get("icon"), "build/icon.png",
                         "win.icon 应指向品牌图标真源")
        self.assertTrue((ROOT / "electron" / "build" / "icon.png").is_file(),
                        "图标真源 icon.png 必须存在")
        # ② 桌面快捷方式仍开启（图标即上面 ICO）
        self.assertTrue(build.get("nsis", {}).get("createDesktopShortcut"),
                        "桌面快捷方式应保留，才能看到统一图标")
        # ③ 托盘从同一张图运行时缩放（extraResources 带到 resources/icon.png）
        extra = build.get("extraResources", [])
        self.assertTrue(any(e.get("from") == "build/icon.png" for e in extra),
                        "icon.png 须随 extraResources 发布，供托盘同源加载")
        js = (ROOT / "electron" / "main.js").read_text(encoding="utf-8")
        self.assertIn("loadTrayIcon", js, "托盘应从品牌真源加载图标")
        self.assertIn("process.resourcesPath", js, "打包态应从 resources 读图标")
        self.assertIn("resize({ width: 16, height: 16 })", js,
                      "托盘图应从真源缩放到 16x16")
        self.assertIn("TRAY_ICON_DATA_URL", js, "内嵌小图兜底应保留")


if __name__ == "__main__":
    unittest.main()
