#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1.9.1 · 卸载时结束进程树，根治「卸载后右下角托盘仍能点开页面」。

用户 2026-11-28 反馈：在系统中卸载精核后，右下角托盘进程仍在，点击还能打开页面。
根因：Electron 外壳与后端进程同名 Jinghe.exe，关窗设计成 hide 到托盘并常驻；
electron-builder 的卸载段只删文件，自己的 customUnInstall 宏也只补删 app.asar
和询问数据，全程没有结束正在运行的进程。Windows 上已载入内存的进程不受删文件
影响，托盘图标由进程运行时注册，故进程不退则图标不消失。

修复：在 electron-builder 的 customUnInit 钩子（un.onInit，早于文件删除）里
用 taskkill /F /T /IM Jinghe.exe 结束整个进程树，并等待文件锁释放。

本模块只做静态契约校验，不依赖运行时进程或管理员权限。
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "knowledge"))


class TestUninstallProcessCleanup(unittest.TestCase):
    def setUp(self):
        self.nsh = (ROOT / "electron" / "installer.nsh").read_text(encoding="utf-8")

    def _macro_body(self, name):
        marker = "!macro " + name
        start = self.nsh.find(marker)
        self.assertGreaterEqual(start, 0, "缺少宏 " + name)
        end = self.nsh.find("!macroend", start)
        self.assertGreater(end, start, "宏 " + name + " 未闭合")
        return self.nsh[start:end]

    def test_01_custom_uninit_hook_defined(self):
        """必须在 customUnInit 钩子里杀进程，不能只放卸载段末尾。"""
        self.assertIn("!macro customUnInit", self.nsh)
        body = self._macro_body("customUnInit")
        self.assertNotIn("!macro", body.replace("!macro customUnInit", ""))

    def test_02_hook_runs_before_file_deletion(self):
        """customUnInit 定义位置必须早于 customUnInstall（编译顺序守护）。"""
        self.assertLess(
            self.nsh.index("!macro customUnInit"),
            self.nsh.index("!macro customUnInstall"),
        )

    def test_03_kills_process_tree_by_image_name(self):
        """外壳与后端同名 Jinghe.exe，必须按映像名强杀整棵树。"""
        body = self._macro_body("customUnInit")
        self.assertIn("taskkill", body)
        self.assertIn("/F", body)
        self.assertIn("/T", body)
        self.assertIn("/IM", body)
        self.assertIn('"Jinghe.exe"', body)

    def test_04_uses_ns_exec_to_avoid_console_flash(self):
        """用 nsExec::ExecToLog 静默执行，不弹 cmd 黑窗。"""
        body = self._macro_body("customUnInit")
        self.assertIn("nsExec::ExecToLog", body)

    def test_05_waits_for_file_lock_release(self):
        """杀进程后必须等待，否则紧接着的 Delete 仍可能撞上文件占用。"""
        body = self._macro_body("customUnInit")
        self.assertIn("Sleep", body)

    def test_06_stack_balanced(self):
        """nsExec 会向栈压返回值，必须弹出，不能污染后续安装逻辑。"""
        body = self._macro_body("customUnInit")
        self.assertEqual(body.count("Push $0"), 1)
        self.assertEqual(body.count("Pop $0"), 2)

    def test_07_builder_template_supports_hook(self):
        """确认 electron-builder 模板确实在 un.onInit 调用 customUnInit。"""
        tpl = (
            ROOT / "electron" / "node_modules" / "app-builder-lib"
            / "templates" / "nsis" / "uninstaller.nsh"
        )
        if not tpl.exists():
            self.skipTest("electron-builder 模板未安装（node_modules 缺失）")
        text = tpl.read_text(encoding="utf-8")
        self.assertIn("!ifmacrodef customUnInit", text)
        self.assertIn("!insertmacro customUnInit", text)


if __name__ == "__main__":
    unittest.main()
