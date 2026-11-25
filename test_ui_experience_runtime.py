# -*- coding: utf-8 -*-
"""v1.7.0 UI 体验翻新真运行时测试（Node VM）。

在 VM 里真实执行 ui/app.js 的 applyTheme / cmdMatches / renderCmdList /
showDoneSummary，喂最小 DOM stub，断言深色主题落到 <html data-theme>、
命令面板渲染出条目、结果前置生成摘要文本。与静态契约测试互补。

CI 模块：test_ui_experience_runtime（第 21 个）。
"""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "tools" / "test_ui_experience_runtime.js"


class TestUiExperienceRuntime(unittest.TestCase):
    def test_runtime_behavior(self):
        """Node VM 真执行主题/命令面板/结果前置函数，断言 DOM 行为。"""
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
            self.fail("UI 体验运行时测试失败（rc=%d）：\n%s" % (result.returncode, output))
        self.assertIn("UI 体验行为测试全部通过", output)

    def test_script_executes_real_functions(self):
        """行为脚本从 app.js 抽取真实函数，不是硬编码副本。"""
        src = SCRIPT.read_text(encoding="utf-8")
        for fn in ("applyTheme", "cmdMatches", "renderCmdList", "showDoneSummary"):
            self.assertIn('extractFn("%s")' % fn, src,
                          "运行时脚本未抽取真实函数：%s" % fn)


if __name__ == "__main__":
    unittest.main(verbosity=2)
