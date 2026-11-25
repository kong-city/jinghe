# -*- coding: utf-8 -*-
"""v1.7.1 主题持久化 + 布局改造真运行时测试（Node VM）。

在 VM 里真实执行 ui/app.js 的 applyTheme / persistUiPref / applySettings /
syncStrip，喂最小 DOM stub，断言：

1. 点「深色」真的发出落盘请求（带 theme=dark）
2. 保存请求在途时切页、拉回后端旧值 light，界面仍是 dark
3. 落盘成功后本地 settings 回写为 dark
4. 首页流程指引条随页面切换高亮当前阶段

这条测试直接复现并锁死了「点深色 → 切页 → 变回浅色」的真实缺陷，
与静态契约测试（test_v164_i18n）互补。

CI 模块：test_ui_layout_runtime（第 22 个）。
"""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "tools" / "test_ui_layout_runtime.js"


class TestUiLayoutRuntime(unittest.TestCase):
    def test_runtime_behavior(self):
        """Node VM 真执行主题持久化与流程条高亮，断言 DOM 行为。"""
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
            self.fail("布局运行时测试失败（rc=%d）：\n%s" % (result.returncode, output))
        self.assertIn("主题持久化 + 布局行为测试全部通过", output)

    def test_script_executes_real_functions(self):
        """行为脚本从 app.js 抽取真实函数，不是硬编码副本。"""
        src = SCRIPT.read_text(encoding="utf-8")
        for fn in ("applyTheme", "persistUiPref", "applySettings", "syncStrip"):
            self.assertIn('extractFn("%s")' % fn, src,
                          "运行时脚本未抽取真实函数：%s" % fn)

    def test_regression_scenario_is_covered(self):
        """必须覆盖「切页拉回旧值不覆盖用户选择」这个关键场景。"""
        src = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("切页拉回后端旧值 light 后，界面仍是 dark", src,
                      "未覆盖主题回退场景")


if __name__ == "__main__":
    unittest.main(verbosity=2)
