#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S14a · 打包产物冒烟验证 · 回归测试。

守护：① CI 真的接了冒烟步骤（在构建之后、上传之前）；② 冒烟脚本存在且
分级判定正确（后端严格、外壳尽力而为且默认从严）；③ 缺陷关键词表里
**不得混入正常启动标志**（否则正常包会被误判为缺陷）。
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class TestSmokeHarness(unittest.TestCase):

    def setUp(self):
        self.script = (ROOT / "tools" / "smoke_test.py").read_text(encoding="utf-8")
        self.ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    def test_01_ci_has_smoke_step(self):
        self.assertIn("smoke_test.py", self.ci, "CI 未接入冒烟验证")
        self.assertIn("冒烟验证", self.ci)
        # 冒烟必须在「构建安装包」之后、「上传资产」之前
        ci = self.ci
        self.assertLess(ci.index("构建 Electron 安装包"), ci.index("smoke_test.py"),
                        "冒烟必须在构建之后")
        self.assertLess(ci.index("smoke_test.py"), ci.index("gh release upload"),
                        "冒烟必须在上传资产之前（坏包不该被发出去）")

    def test_02_smoke_script_graded(self):
        self.assertIn("def smoke_backend", self.script)
        self.assertIn("def smoke_shell", self.script)
        # 后端严格：失败即失败（ok = ok and b_ok）
        self.assertIn("ok = ok and b_ok", self.script)
        # 外壳默认放行但可严格化
        self.assertIn("--strict-shell", self.script)
        self.assertIn("ok = ok and s_ok", self.script)

    def test_03_defect_keywords_exclude_normal_markers(self):
        """「main.js 已加载」「托盘已创建」是**正常**标志，混进缺陷表就会误杀。"""
        seg = self.script[self.script.index("DEFECT_HINTS"):]
        seg = seg[:seg.index(")")]
        self.assertNotIn("main.js 已加载", seg, "正常启动标志不得算缺陷")
        self.assertNotIn("托盘已创建", seg, "正常启动标志不得算缺陷")
        # 真正的失败标志必须在
        for kw in ("托盘创建失败", "后端进程启动失败", "后端意外退出"):
            self.assertIn(kw, seg, "缺陷关键词缺失：%s" % kw)

    def test_04_default_strict_on_unknown(self):
        """无法归类时必须判缺陷（从严），不得静默放行。

        放行的唯一旁路是「asar 校验通过 + 明确命中环境关键词」——
        因为 asar 通过已证明打包本身没问题，此时起不来只可能是运行环境
        （CI runner 无交互桌面会话）。
        """
        seg = self.script[self.script.index("def classify_shell_failure"):]
        seg = seg[:seg.index("def _last")]
        self.assertIn('return ("defect"', seg,
                      "无法归类时必须判缺陷；静默放行会漏掉真问题")
        self.assertIn('"env"', seg, "仅明确命中环境关键词才放行")
        self.assertIn("asar_ok", seg, "分类必须依赖 asar 校验结果")

    def test_05_asar_check_is_deterministic(self):
        """asar 校验是与环境无关的确定性检查，必须存在且覆盖关键符号。"""
        self.assertIn("def check_asar", self.script)
        seg = self.script[self.script.index("def check_asar"):]
        seg = seg[:seg.index("def smoke_backend")]
        for sym in ("app.whenReady", "startBackend", "createTray", "createWindow"):
            self.assertIn(sym, seg, "asar 校验缺关键符号 %s" % sym)
        # 主流程必须真的调用它
        self.assertIn("check_asar(str(asar))", self.script)

    def test_06_ci_uses_job_level_version_var(self):
        """回归防护：GitHub Actions 每步是独立进程，步骤内定义的 $version
        不会传给下一步——版本号必须放在 job 级 env 里。

        同时防护另一类错：VERSION 来自 tag 名（带 v，如 v1.2.8），而产物名
        不带 v（Jinghe-1.2.8.exe）。凡拼产物路径处必须去前缀，否则
        会出现「文件未找到」这种看着像产品问题、其实是拼错的失败。
        """
        self.assertIn("VERSION: ${{ github.ref_name }}", self.ci,
                      "版本号必须提到 job 级 env")
        self.assertIn("dist/Jinghe-$ver.exe", self.ci,
                      "冒烟步骤必须用去前缀后的版本拼产物路径")
        # 不允许在步骤里再各自定义 version（会误导后来人）
        self.assertNotIn('$version = $tag -replace', self.ci,
                         "步骤内定义的 version 不会跨步骤生效，应改用 job 级 env")
        # 每处拼产物路径都应先去 v
        self.assertIn("-replace '^v', ''", self.ci,
                      "tag 名带 v 前缀，拼产物路径前必须去掉")

    def test_05_env_var_interference_stripped(self):
        """ELECTRON_RUN_AS_NODE 会让 Electron 变纯 Node 模式——那是环境干扰，
        冒烟脚本必须清掉它，不能让环境问题把测试带偏。"""
        self.assertIn('env.pop("ELECTRON_RUN_AS_NODE", None)', self.script)
        self.assertIn('env.pop("NODE_OPTIONS", None)', self.script)
        # 外壳端口必须显式指定，否则探活找错端口
        self.assertIn('JINGHE_PORT', self.script)

    def test_06_local_reusable(self):
        """脚本要能在本地独立跑（CLI 参数完整）。"""
        for arg in ("--backend", "--shell", "--port", "--timeout"):
            self.assertIn(arg, self.script, "缺参数 %s" % arg)
        self.assertIn("if __name__ ==", self.script)

    def test_07_gate_compiles_script(self):
        gate = (ROOT / "tools" / "check_release.py").read_text(encoding="utf-8")
        self.assertIn("tools/smoke_test.py", gate,
                      "门禁编译清单缺 smoke_test.py")

    def test_08_probe_bypasses_proxy(self):
        """回归防护：构建机常带 http_proxy，urllib 默认读环境变量会让
        访问 127.0.0.1 也走代理 → 探活必然失败 → 误判「后端起不来」。"""
        seg = self.script[self.script.index("def probe"):]
        seg = seg[:seg.index("def wait_ready")]
        self.assertIn("ProxyHandler({})", seg, "探活必须绕过系统代理")
        self.assertIn("build_opener", seg)

    def test_09_shell_launch_failure_is_defect(self):
        """回归防护：外壳二进制无法执行（文件损坏）是打包缺陷，不能放行。"""
        seg = self.script[self.script.index("def smoke_shell"):]
        seg = seg[:seg.index("def main")]
        self.assertIn("if proc is None:", seg)
        none_branch = seg[seg.index("if proc is None:"):]
        none_branch = none_branch[:none_branch.index("try:")]
        self.assertIn("return False", none_branch,
                      "外壳无法启动必须判缺陷；误放行会漏掉损坏的包")
        self.assertNotIn("classify_shell_failure", none_branch,
                         "启动失败时不得用全局 shell.log（含上次运行的旧日志）")

    def test_10_ci_reports_failure_as_annotation(self):
        """CI 失败必须把诊断打进 annotation，否则页面看不到原因、只能盲猜。"""
        self.assertIn("::error title=冒烟验证失败::", self.ci)
        self.assertIn("Tee-Object", self.ci, "冒烟输出需落盘以便回显")


if __name__ == "__main__":
    unittest.main()
