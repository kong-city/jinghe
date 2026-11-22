#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S12a 订阅博主/频道内容提取 · 回归测试。

守护不变量：
1. 订阅注册表落盘/校验/去重/due 判断正确，脏数据不崩；
2. 频道发现只枚举不下载，解析去重、失败诚实降级；
3. 增量编排两层去重（seen_ids + content_hash 接口），逐条失败隔离、可取消；
4. 零第三方依赖、接线（app/UI/build/门禁/CI）完整。

全部用注入 fn + 临时目录，不依赖真实网络 / yt-dlp / whisper。
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent


class TestSubscription(unittest.TestCase):

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.tmp = Path(self.td.name)
        self.sub_file = self.tmp / "subs.json"
        import subscription_store as S
        self.S = S
        self._old_sub_file = S.SUB_FILE
        S.SUB_FILE = self.sub_file

    def tearDown(self):
        self.S.SUB_FILE = self._old_sub_file
        self.td.cleanup()

    # ---------------- 注册表 ---------------- #
    def test_01_store_crud_and_dedup(self):
        S = self.S
        r = S.add_sub("https://x/channel", name="测试", interval_hours=24)
        self.assertTrue(r["ok"])
        sid = r["id"]
        # 重复地址拒绝
        self.assertFalse(S.add_sub("https://x/channel")["ok"])
        self.assertEqual(len(S.list_subs()), 1)
        # last_seen + due
        S.update_result(sid, seen_ids=["v1", "v2"], new_count=2)
        sub = S.get_sub(sid)
        self.assertEqual(sub["seen_ids"], ["v1", "v2"])
        self.assertEqual(sub["last_status"], "ok")
        self.assertEqual(S.due_subs(now=sub["last_polled"] + 1), [],
                         "刚同步过不应 due")
        self.assertEqual(len(S.due_subs(now=sub["last_polled"] + 25 * 3600)), 1)
        # 停用后不 due
        S.set_enabled(sid, False)
        self.assertEqual(S.due_subs(), [])
        # 删除
        self.assertTrue(S.remove_sub(sid)["ok"])
        self.assertEqual(S.list_subs(), [])

    def test_02_store_dirty_data_conservative(self):
        S = self.S
        dirty = {"subscriptions": [
            {"url": ""},                                   # 无 URL 丢弃
            {"url": "https://a", "id": "x", "interval_hours": -5,
             "seen_ids": "not-a-list"},                    # 脏值收敛
            {"url": "https://a", "id": "x"},                # 重复 id 丢弃
            "not-a-dict",                                   # 非对象丢弃
        ]}
        self.sub_file.write_text(json.dumps(dirty), encoding="utf-8")
        subs = S.list_subs()
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]["interval_hours"], S.MIN_INTERVAL_HOURS)
        self.assertEqual(subs[0]["seen_ids"], [])
        # 坏 JSON 不崩
        self.sub_file.write_text("{broken", encoding="utf-8")
        self.assertEqual(S.list_subs(), [])

    def test_03_store_failure_accumulates_and_disables(self):
        S = self.S
        sid = S.add_sub("https://x/c")["id"]
        for _ in range(S.MAX_FAILS_BEFORE_DISABLE):
            S.update_result(sid, error="模拟失败")
        sub = S.get_sub(sid)
        self.assertFalse(sub["enabled"], "连续失败应自动停用")
        self.assertIn("连续失败", sub["last_error"])

    # ---------------- 频道发现 ---------------- #
    def test_04_discovery_parse_entries(self):
        import channel_discovery as D
        payload = {"id": "pl", "entries": [
            {"id": "a", "title": "视频A", "url": "//x/a", "upload_date": "20261120"},
            {"id": "a", "title": "重复", "url": "https://x/a"},
            {"id": "b", "title": "视频B", "url": "https://x/b"},
            {"title": "无 id 应丢弃"},
        ]}
        refs = D.parse_entries(payload)
        self.assertEqual([r["id"] for r in refs], ["a", "b"])
        self.assertEqual(refs[0]["url"], "https://x/a")
        self.assertLessEqual(len(D.parse_entries(payload, limit=1)), 1)

    def test_05_discover_success_and_failure(self):
        import channel_discovery as D
        with mock.patch.object(D, "capability",
                               return_value={"enabled": True, "reason": ""}):
            class CP:
                stdout = json.dumps({"entries": [
                    {"id": "a", "url": "https://x/a", "title": "A"}]}).encode()
                stderr = b""
                returncode = 0
            res = D.discover("https://x/channel", runner=lambda argv, t: CP())
            self.assertTrue(res["ok"])
            self.assertEqual(len(res["entries"]), 1)

            class Fail:
                stdout = b""
                stderr = b"Sign in to confirm"
                returncode = 1
            res2 = D.discover("https://x/channel", runner=lambda argv, t: Fail())
            self.assertFalse(res2["ok"])
            self.assertEqual(res2["entries"], [], "失败不得编造视频条目")

        with mock.patch.object(D, "capability",
                               return_value={"enabled": False, "reason": "缺工具"}):
            res3 = D.discover("https://x/channel")
            self.assertFalse(res3["ok"])
            self.assertIn("缺工具", res3["error"])

    # ---------------- 增量编排 ---------------- #
    def _sync(self, sub, outdir, kbdir, disc, dl, tr, ing):
        """同步调用内部 _sync_one，避开后台线程 + sleep（测试更稳）。"""
        import subscription_engine as E
        return E._sync_one(sub, outdir=outdir, kb_dir=kbdir,
                           discover_fn=disc, download_fn=dl,
                           transcribe_fn=tr, ingest_fn=ing)

    def test_06_pipeline_incremental_and_idempotent(self):
        outdir = self.tmp / "out"; outdir.mkdir()
        kbdir = self.tmp / "kb"; derived = outdir / "derived"; derived.mkdir()
        sid = self.S.add_sub("https://x/channel")["id"]
        sub = self.S.get_sub(sid)

        def disc(url, **kw):
            return {"ok": True, "entries": [
                {"id": "v1", "url": "u1", "title": "视频1"},
                {"id": "v2", "url": "u2", "title": "视频2"}]}
        def dl(url, tmpd, **kw):
            p = Path(tmpd) / (url + ".mp4"); p.write_bytes(b"x")
            return {"ok": True, "path": str(p)}
        def tr(files, out):
            (derived / "doc.md").write_text(
                "<!-- src: x -->\n## k\n\n<!-- anchor: d1 | block: 2 -->\n- 要点",
                encoding="utf-8")
            return {"ok": True}

        ingested = []
        def ing(kd, md, **kw):
            ingested.append(md)
            return {"ok": True, "added": 1}

        res = self._sync(sub, outdir, kbdir, disc, dl, tr, ing)
        self.assertTrue(res["ok"])
        self.assertEqual(res["new_ids"], ["v1", "v2"])
        self.assertEqual(len(ingested), 1, "应入库转写产物")
        # 回写 seen 后，二次同步差集为空
        merged = sorted(set(sub["seen_ids"]) | set(res["new_ids"]))
        self.S.update_result(sid, seen_ids=merged, new_count=res["new_count"])
        sub2 = self.S.get_sub(sid)
        res2 = self._sync(sub2, outdir, kbdir, disc, dl, tr, ing)
        self.assertEqual(res2["new_count"], 0, "二次同步应零新增（幂等）")

    def test_07_pipeline_partial_failure_isolated(self):
        outdir = self.tmp / "out"; outdir.mkdir()
        kbdir = self.tmp / "kb"; derived = outdir / "derived"; derived.mkdir()
        sid = self.S.add_sub("https://x/channel")["id"]
        sub = self.S.get_sub(sid)

        def disc(url, **kw):
            return {"ok": True, "entries": [
                {"id": "v1", "url": "u1", "title": "好视频"},
                {"id": "v2", "url": "u2", "title": "坏视频"}]}
        def dl(url, tmpd, **kw):
            if url == "u2":
                return {"ok": False, "error": "模拟下载失败"}
            p = Path(tmpd) / (url + ".mp4"); p.write_bytes(b"x")
            return {"ok": True, "path": str(p)}
        def tr(files, out):
            self.assertEqual(len(files), 1, "只应转写下载成功的视频")
            (derived / "doc.md").write_text("<!-- src: x -->\n## k\n", encoding="utf-8")
            return {"ok": True}
        def ing(kd, md, **kw): return {"ok": True, "added": 1}

        res = self._sync(sub, outdir, kbdir, disc, dl, tr, ing)
        self.assertTrue(res["ok"])
        self.assertEqual(res["new_ids"], ["v1"], "坏视频应被隔离，不影响好视频")

    def test_08_discovery_failure_reported(self):
        outdir = self.tmp / "out"; outdir.mkdir()
        sid = self.S.add_sub("https://x/channel")["id"]
        sub = self.S.get_sub(sid)
        def disc(url, **kw): return {"ok": False, "error": "需登录"}
        res = self._sync(sub, outdir, self.tmp / "kb", disc,
                         lambda *a, **k: None, lambda *a, **k: None,
                         lambda *a, **k: None)
        self.assertFalse(res["ok"])
        self.assertEqual(res["new_ids"], [])

    # ---------------- 契约 ---------------- #
    def test_09_zero_third_party_and_no_frozen_touch(self):
        for name in ("subscription_store.py", "channel_discovery.py",
                     "subscription_engine.py"):
            src = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("import requests", src)
            self.assertNotIn("import yaml", src)
            self.assertNotIn("from extract import", src, "不得依赖冻结内核业务函数")

    def test_10_wiring(self):
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        spec = (ROOT / "build.spec").read_text(encoding="utf-8")
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        gate = (ROOT / "tools" / "check_release.py").read_text(encoding="utf-8")
        for ep in ("/api/sub/add", "/api/sub/list", "/api/sub/remove",
                   "/api/sub/run-now", "/api/sub/cancel"):
            self.assertIn(ep, app, "缺端点 %s" % ep)
        for mod in ("subscription_store", "channel_discovery", "subscription_engine"):
            self.assertIn(mod, app, "app 未接线 %s" % mod)
            self.assertIn(mod, spec, "build.spec 缺 %s" % mod)
            self.assertIn(mod + ".py", gate, "门禁编译清单缺 %s" % mod)
        self.assertIn('id="subUrl"', html)
        self.assertIn("loadSubList", js)
        self.assertIn("test_subscription", ci, "CI 未覆盖 test_subscription")


if __name__ == "__main__":
    unittest.main()
