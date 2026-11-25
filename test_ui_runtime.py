# -*- coding: utf-8 -*-
"""v1.7.0 界面改造真运行时测试（Node VM）。

在 VM 里真实执行 ui/app.js 的 renderFileList() / renderKbSource()，
喂给最小 DOM stub，断言逐文件诊断徽标与同源块反向引用确实生成、
文案经 tr() 翻译、点选会切换 activeId。与静态契约测试互补。

CI 模块：test_ui_runtime（第 20 个）。
"""
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "tools" / "test_ui_runtime.js"


class TestUiRuntime(unittest.TestCase):
    def test_ui_runtime_behavior(self):
        """Node VM 真执行渲染函数，断言 DOM 节点与交互行为。"""
        result = subprocess.run(
            ["node", str(SCRIPT)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(ROOT),
            timeout=60,
        )
        output = (result.stdout or "") + (result.stderr or "")
        if result.returncode != 0:
            self.fail("界面改造运行时测试失败（rc=%d）：\n%s" % (result.returncode, output))
        self.assertIn("界面改造行为测试全部通过", output)

    def test_script_executes_real_functions(self):
        """行为脚本从 app.js 抽取真实函数，不是硬编码副本。"""
        src = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('extractFn("renderFileList")', src)
        self.assertIn('extractFn("renderKbSource")', src)
        self.assertNotIn("console.log(\"PASS", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
