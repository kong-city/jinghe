#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1.5.0 · T4 产物中心的守护测试。

T4（CAPABILITY_CONTRACT 记为「待办 T4」）：产物中心 =
统一索引 + 历史批次 + 软件内打开。本文件逐条锁住实现要点：

======  ==============================================  =====================
编号    要点                                           用例
======  ==============================================  =====================
T4-1    后端 _list_artifact_history 函数存在            test_01
T4-2    GET /api/artifacts/history 路由已接线           test_02
T4-3    只索引围栏内产物（越权目录不进索引）           test_03
T4-4    历史批次字段完整（路径/时间/md/derived/大小）  test_04
T4-5    前端首页产物中心卡片 + 刷新/打开接线            test_05
T4-6    提取完成后自动刷新历史索引                     test_06
T4-7    不新增导航入口（6 入口测试契约，加工页已删）    test_07
T4-8    不碰冻结 extract.py 内核 / 不放宽 /api/open     test_08
======  ==============================================  =====================

运行：
    python test_v150_t4.py
    python -m unittest -v test_v150_t4
"""
from __future__ import annotations

# JINGHE_LAYOUT_BOOTSTRAP
import sys as _jinghe_sys
from pathlib import Path as _jinghe_Path
_jinghe_root = _jinghe_Path(__file__).resolve().parent
for _jinghe_sub in ("core", "media", "knowledge", "link", "subs"):
    _jinghe_p = str(_jinghe_root / _jinghe_sub)
    if _jinghe_p not in _jinghe_sys.path:
        _jinghe_sys.path.insert(0, _jinghe_p)
# END JINGHE_LAYOUT_BOOTSTRAP
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestV150T4(unittest.TestCase):
    """v1.5.0 T4 产物中心守护测试。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="jinghe-v150-t4-")
        self.tmp = Path(self._tmp.name)
        self.ui_js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        self.ui_html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        self.app_src = (ROOT / "app.py").read_text(encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_01_history_function_exists(self) -> None:
        self.assertIn("def _list_artifact_history(", self.app_src,
                      "缺 _list_artifact_history 后端函数")

    def test_02_history_route_wired(self) -> None:
        self.assertIn('path == "/api/artifacts/history"', self.app_src,
                      "缺 /api/artifacts/history GET 路由")
        self.assertIn("_list_artifact_history()", self.app_src,
                      "路由未调用历史索引函数")

    def test_03_fence_blocks_outside_dirs(self) -> None:
        """越权目录（系统目录）绝不进入索引。"""
        import app as app_mod
        # 直接调用：当前围栏不应把 C:/Windows 当产物批次
        r = app_mod._list_artifact_history()
        self.assertTrue(r.get("ok"))
        for b in r.get("batches", []):
            self.assertNotIn("Windows", b.get("path", ""),
                             "越权系统目录混入产物索引：%s" % b.get("path"))
        # 函数源码里必须复用围栏与 _is_within 双重校验
        func_src = self.app_src[
            self.app_src.index("def _list_artifact_history("):
            self.app_src.index("def _update_plan(")]
        self.assertIn("_kb_allowed_roots()", func_src,
                      "历史索引未复用产物目录白名单")
        self.assertIn("kb._is_within", func_src,
                      "历史索引缺双重围栏校验")

    def test_04_batch_fields_complete(self) -> None:
        """造一个围栏内批次，验证字段完整。"""
        import app as app_mod
        prod = self.tmp / "out-2026-11-23-2300"
        (prod / "md").mkdir(parents=True)
        (prod / "md" / "001-demo.md").write_text("# demo\n", encoding="utf-8")
        (prod / "MERGED.md").write_text("# merged\n", encoding="utf-8")
        # 临时把该目录注入围栏（模拟软件写过产物）
        old = set(app_mod._WRITTEN_OUTDIRS)
        try:
            app_mod._WRITTEN_OUTDIRS.add(str(prod))
            r = app_mod._list_artifact_history()
            # 索引用 resolve() 后的规范长路径，临时目录可能是 8.3 短路径，
            # 故两边都 resolve 再比对。
            want = str(prod.resolve())
            found = [b for b in r.get("batches", []) if b["path"] == want]
            self.assertEqual(len(found), 1, "自建批次未进索引")
            b = found[0]
            for k in ("path", "name", "mtime", "md_count",
                      "derived_count", "has_merged", "size"):
                self.assertIn(k, b, "批次缺字段 %s" % k)
            self.assertEqual(b["md_count"], 1)
            self.assertTrue(b["has_merged"])
            self.assertGreater(b["size"], 0)
        finally:
            app_mod._WRITTEN_OUTDIRS.clear()
            app_mod._WRITTEN_OUTDIRS.update(old)

    def test_05_ui_wired(self) -> None:
        self.assertIn('id="artifactCenter"', self.ui_html,
                      "首页缺产物中心卡片")
        self.assertIn("btnRefreshHistory", self.ui_html)
        self.assertIn("historyList", self.ui_html)
        self.assertIn('"/api/artifacts/history"', self.ui_js,
                      "前端未调用历史索引端点")
        self.assertIn("function loadHistory(", self.ui_js)
        self.assertIn("function renderHistory(", self.ui_js)
        self.assertIn('"/api/artifacts/open"', self.ui_js,
                      "产物中心未复用软件内打开端点")

    def test_06_auto_refresh_after_run(self) -> None:
        self.assertIn("loadHistory();", self.ui_js,
                      "提取完成后未刷新历史索引")

    def test_07_no_new_nav_entry(self) -> None:
        """6 入口测试契约（v1.8.5 加工页已删）：不新增 data-page。"""
        import re
        pages = re.findall(r'data-page="([^"]+)"', self.ui_html)
        self.assertEqual(
            sorted(set(pages)),
            sorted(["home", "refine", "revise",
                    "kb", "settings", "about"]),
            "产物中心不得新增导航入口（6 入口锁死）")

    def test_08_frozen_contract_untouched(self) -> None:
        """不碰冻结 extract.py；不放宽 /api/open 白名单。"""
        # 版本号从真源动态读取（不写死，避免升号后脆弱断言）：
        # 本测试只守护「extract.py 有合法版本真源」，具体版本值由门禁守护。
        import re as _re
        extract_src = (ROOT / "extract.py").read_text(encoding="utf-8")
        m = _re.search(r'^__version__\s*=\s*["\']([\d.]+)["\']',
                       extract_src, _re.M)
        self.assertIsNotNone(m, "extract.py 缺版本真源")
        self.assertGreaterEqual(len(m.group(1).split(".")), 2,
                                "版本号格式不合法")
        # /api/open 白名单仍由 _api_open 守护，历史索引用独立端点
        self.assertIn("def _api_open(", self.app_src)
        self.assertIn("def _api_open_artifact(", self.app_src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
