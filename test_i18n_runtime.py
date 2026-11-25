# -*- coding: utf-8 -*-
"""v1.6.6：i18n 运行时行为测试（通过 node 在 VM 中真实执行 applyLang）。

与 test_v164_i18n.py 的静态契约互补：本文件验证「切语言后 DOM 真的变了」，
包括 textContent / placeholder / aria-label / title / html lang 五类变化，
以及切回中文时 tr() 回退返回中文原文 key 的行为。
"""
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class TestI18nRuntime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("node"):
            raise unittest.SkipTest("未安装 node，跳过运行时行为测试")

    def test_apply_lang_changes_dom(self):
        """node VM 里执行 applyLang('en'/'zh')，断言 DOM 五类属性真实变化。"""
        script = ROOT / "tools" / "test_i18n_runtime.js"
        self.assertTrue(script.exists(), "行为测试脚本缺失")
        proc = subprocess.run(
            ["node", str(script)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )
        self.assertEqual(
            proc.returncode, 0,
            "i18n 行为测试失败:\n%s\n%s" % (proc.stdout, proc.stderr),
        )
        self.assertIn("行为测试全部通过", proc.stdout)

    def test_runtime_script_uses_real_apply_lang(self):
        """行为脚本确实从 app.js 抽取 applyLang，而非硬编码一份逻辑。"""
        src = (ROOT / "tools" / "test_i18n_runtime.js").read_text(encoding="utf-8")
        self.assertIn('fs.readFileSync', src)
        self.assertIn('ui/app.js', src)
        self.assertIn('function applyLang', src)
        self.assertIn("vm.runInContext", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
