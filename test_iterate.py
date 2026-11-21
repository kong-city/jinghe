#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S11 多轮自我迭代提纯 · 回归测试。

守护四条不变量：
1. 默认 1 轮 == S8 extract_core（零行为漂移）；
2. 任意轮数下，每一轮核心都仍是原文原句（不造假红线）；
3. 焦点重排真的发生（有中间轮 jaccard < 1），且能收敛早停；
4. 配置 / UI / 构建清单贯通，取消与脏配置不崩。
"""
import unittest
from pathlib import Path

import backend
import extract_engine as X
import iterate_engine as I
import refine
from unittest import mock

ROOT = Path(__file__).resolve().parent

MD = (
    "# 系统设计说明\n\n"
    "本系统保证数据一致性，所有数据一致性约束均已实现。\n\n"
    "## 架构\n\n"
    "后端采用分层架构，界面层与业务层解耦，便于维护。\n\n"
    "数据一致性是分布式场景的核心挑战，需要一致性协议保障。\n\n"
    "日志模块按天切割，避免单文件过大影响检索效率。\n\n"
    "## 存储\n\n"
    "为了保证数据一致性，写入路径采用原子替换与事务日志。\n\n"
    "附件下载走白名单校验，拒绝任意外部地址，保障安全。\n\n"
    "一致性校验在每次提交后执行，发现不一致立即告警并记录。\n\n"
    "样式表使用原生 CSS，无第三方前端框架依赖。\n\n"
    "## 观测\n\n"
    "监控面板展示请求延迟与错误率，数据一致性指标单独看板呈现。\n\n"
    "用户导出数据时打包为 zip，纯标准库实现，零外部依赖。\n"
)


class TestIterateEngine(unittest.TestCase):

    def test_01_default_one_round_equals_extract_core(self):
        """默认 1 轮与 S8 extract_core 逐字等价（零行为漂移）。"""
        base = X.extract_core(MD, top_k=5)
        one = I.iterate_core(MD, top_k=5)
        self.assertEqual([p["text"] for p in base["points"]],
                         [p["text"] for p in one["points"]])
        self.assertEqual(len(one["rounds"]), 1)
        self.assertFalse(one["converged"])

    def test_02_every_round_stays_traceable(self):
        """逐轮红线：任意轮数的产出都必须能在原文逐字定位。"""
        for rounds in (2, 3, 5):
            r = I.iterate_core(MD, top_k=5, max_rounds=rounds)
            ok, why = X.verify_traceable(MD, r["points"])
            self.assertTrue(ok, "%d 轮产出造假：%s" % (rounds, why))

    def test_03_focus_reorder_really_happens_and_converges(self):
        """焦点重排必须真实改变核心（中间轮 jaccard<1），并最终收敛。"""
        r = I.iterate_core(MD, top_k=5, max_rounds=5)
        self.assertGreater(len(r["rounds"]), 2,
                           "焦点种子未推动任何重排（疑似假迭代）")
        self.assertLess(r["rounds"][1]["jaccard"], 1.0,
                        "第 2 轮与上轮完全相同，迭代无效果")
        self.assertTrue(r["converged"], "未收敛")
        self.assertGreaterEqual(r["rounds"][-1]["jaccard"],
                                I.CONVERGE_JACCARD)

    def test_04_no_fabrication_guard_on_tamper(self):
        """篡改校验链条仍有效：verify_traceable 能抓出编造句。"""
        r = I.iterate_core(MD, top_k=5, max_rounds=3)
        bad = [dict(p) for p in r["points"]]
        bad[0]["text"] = "模型编造的原文之外内容"
        self.assertFalse(X.verify_traceable(MD, bad)[0])

    def test_05_cancel_stops_after_current_round(self):
        """取消回调：当前轮结束后停止，不产生后续轮。"""
        r = I.iterate_core(MD, top_k=5, max_rounds=5,
                           cancelled=lambda: True)
        self.assertEqual(len(r["rounds"]), 1)
        self.assertTrue(r["stats"]["cancelled"])
        ok, _ = X.verify_traceable(MD, r["points"])
        self.assertTrue(ok, "取消后产出仍须可回溯")

    def test_06_rounds_normalization_is_conservative(self):
        """脏配置钳制：负数/超限/字符串都不崩，收敛到 [1,5]。"""
        self.assertEqual(I.normalize_rounds(-3), 1)
        self.assertEqual(I.normalize_rounds(99), 5)
        self.assertEqual(I.normalize_rounds("abc"), 1)
        self.assertEqual(I.normalize_rounds("3"), 3)
        # 收敛阈值脏值同样不得崩（第 2 轮自审发现的真实缺陷）
        self.assertEqual(I.normalize_jaccard("bad"), I.CONVERGE_JACCARD)
        self.assertEqual(I.normalize_jaccard(0), I.CONVERGE_JACCARD)
        self.assertEqual(I.normalize_jaccard(2), I.CONVERGE_JACCARD)
        self.assertEqual(I.normalize_jaccard(0.5), 0.5)
        r = I.iterate_core(MD, top_k=5, max_rounds=3, converge_jaccard="bad")
        ok, _ = X.verify_traceable(MD, r["points"])
        self.assertTrue(ok)

    def test_07_zero_third_party_dependency(self):
        """新引擎仅用标准库 + 冻结引擎，不许引入第三方/冻结内核。"""
        src = (ROOT / "iterate_engine.py").read_text(encoding="utf-8")
        self.assertNotIn("import numpy", src)
        self.assertNotIn("import jieba", src)
        self.assertNotIn("from extract import", src, "不得改/依赖冻结内核的业务函数")
        import ast
        imported = set()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Import):
                for a in node.names:
                    imported.add(a.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertTrue(imported <= {"__future__", "time", "extract_engine"},
                        "出现非白名单导入：%s" % (imported - {"__future__", "time", "extract_engine"}))

    def test_08_config_roundtrip(self):
        """配置层：refine_rounds 默认 1、脏值钳制、public_config 脱敏回显。"""
        with mock.patch.object(backend, "CONFIG_FILE", Path(self.tmp) / "be.json"), \
             mock.patch.object(backend, "_CACHE", None):
            backend.save_config({})
            cfg = backend.load_config(refresh=True)
            self.assertEqual(cfg["refine_rounds"], 1)
            backend.save_config({"refine_rounds": 999})
            self.assertEqual(backend.load_config(refresh=True)["refine_rounds"], 5)
            backend.save_config({"refine_rounds": "junk"})
            self.assertEqual(backend.load_config(refresh=True)["refine_rounds"], 1)
            self.assertEqual(backend.public_config()["refine_rounds"], 1)

    def test_09_integration_product_has_iteration_trace(self):
        """端到端：多轮模式产物含迭代轨迹，且核心仍逐字可回溯。"""
        outdir = Path(self.tmp) / "out"
        src = Path(self.tmp) / "来源.md"
        src.write_text(MD, encoding="utf-8")
        with mock.patch.object(backend, "CONFIG_FILE", Path(self.tmp) / "be.json"), \
             mock.patch.object(backend, "_CACHE", None):
            backend.save_config({"mode": backend.MODE_EXTRACT, "refine_rounds": 4})
            refine._TASK = {"state": "running", "running": True,
                            "cancelled": False, "events": [],
                            "output": "", "error": None}
            refine._run_refine_inner(str(src), "", str(outdir),
                                     backend.current_backend(), refine.capability())
            st = refine.status()
            self.assertEqual(st["state"], "done", st["error"])
            text = Path(st["output"]).read_text(encoding="utf-8")
            self.assertIn("## 迭代轨迹", text)
            self.assertIn("迭代轮数", text)
            self.assertIn("## 核心知识点", text)
            # 轨迹里记录的轮数 > 1
            self.assertIn("第 2 轮", text)

    def test_10_wiring_contract(self):
        """接线契约：app/config/ui/build 全部贯通 refine_rounds。"""
        for name, path in (
            ("backend.py", ROOT / "backend.py"),
            ("app.py", ROOT / "app.py"),
            ("refine.py", ROOT / "refine.py"),
        ):
            self.assertIn("refine_rounds", path.read_text(encoding="utf-8"),
                          "%s 未贯通迭代轮数" % name)
        html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="beRounds"', html)
        self.assertIn('aria-label="提纯迭代轮数"', html)
        self.assertIn("refine_rounds:", js)
        self.assertIn("beRounds:", js)
        self.assertIn("iterate_engine", (ROOT / "build.spec").read_text(encoding="utf-8"))

    def test_11_render_rounds_is_append_only(self):
        """渲染只追加，不改 extract_engine.render_md 的既有结构。"""
        r = I.iterate_core(MD, top_k=5, max_rounds=3)
        base, _ = X.render_md(Path("samples/chapter-01.txt"), r, {})
        full = I.render_rounds(base, r)
        self.assertTrue(full.startswith(base), "迭代轨迹破坏了原产物前缀")
        one = I.iterate_core(MD, top_k=5, max_rounds=1)
        self.assertEqual(I.render_rounds(base, one), base, "单轮不应追加轨迹")

    def setUp(self):
        import tempfile
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        backend._CACHE = None

    def tearDown(self):
        self._td.cleanup()
        backend._CACHE = None


if __name__ == "__main__":
    unittest.main()
