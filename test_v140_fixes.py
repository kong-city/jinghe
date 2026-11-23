#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1.4.0 · 功能实现度盘点修复的守护测试。

背景：v1.3.9 之前做了一次全项目功能盘点（文档契约 × 代码实现 × 运行时链路
三方交叉验证），发现 12 项真实缺口。本文件守护本轮**已实施**的 9 项修复，
每条都是「先坏过、现在必须好」的回归保护：

======  ==========================================  ==========================
编号    缺口                                       本文件用例
======  ==========================================  ==========================
A1      音视频状态条读 S1 占位清单，界面自相矛盾    test_01 / test_02
A2      media_ready 字段恒 false 却对外发布          test_03
A3      /api/transcribe 用音视频并集，违反红线 2    test_04
A4      extract 模式静默丢弃用户修订指令            test_09
B1      「回跳原文」只解析坐标、不执行打开          test_05
B2      阶段 1 的 out/md/*.md 软件内打不开           test_06
B3      订阅抓取不做多轮提纯（空承诺）               test_07 / test_08
B4      知识库无重建索引 / 清理入口                  test_10 / test_11
C3      >50MB 非 UTF-8 无「建议先拆分」提示          test_12
======  ==========================================  ==========================

运行：
    python test_v140_fixes.py
    python -m unittest -v test_v140_fixes
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
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestV140Fixes(unittest.TestCase):
    """v1.4.0 修复的守护测试。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="jinghe-v140-")
        self.tmp = Path(self._tmp.name)
        self.ui_js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
        self.ui_html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        self.app_src = (ROOT / "app.py").read_text(encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @staticmethod
    def strip_js_comments(src: str) -> str:
        """剥掉 JS 注释，只留**可执行代码**。

        本文件多处断言「某标识符 / 某文案不得再出现」，但注释里**应该**
        允许保留对历史问题的描述（例如「旧实现读的是占位清单」）。
        不剥注释的话，加一段说明性注释就会让守护测试假失败。
        """
        import re
        out = re.sub(r"/\*.*?\*/", "", src, flags=re.S)      # 块注释
        out = re.sub(r"^\s*//.*$", "", out, flags=re.M)       # 整行注释
        out = re.sub(r"//[^\n\"']*$", "", out, flags=re.M)    # 行尾注释
        return out

    # ------------------------------------------------------------------ #
    # A1 · 音视频状态条改读顶层增量字段
    # ------------------------------------------------------------------ #
    def test_01_ui_tool_status_not_read_placeholder(self):
        """状态条不得再读 media_tools.capabilities() 这个 S1 占位清单。

        占位清单的 media_transcribe.enabled 恒 false（被 test_33 锁死），
        旧实现读它 → 状态条同一行出现「音视频转写：未启用（S3 阶段的历史
        占位文案）」紧接「音频转写：已启用」，自相矛盾且是过时假信息。

        断言一律在**剥掉注释的可执行代码**上做——注释里允许保留对历史
        问题的说明，否则加一句解释就会让守护测试假失败。
        """
        code = self.strip_js_comments(self.ui_js)
        fn = code[code.index("function renderToolStatus"):
                  code.index("function loadTools")]
        self.assertNotIn("capabilities", fn,
                         "renderToolStatus 仍在读占位清单 toolState.capabilities")
        self.assertNotIn("media_transcribe", fn,
                         "renderToolStatus 仍在读占位条目 media_transcribe")
        # 真实状态必须来自顶层增量字段
        self.assertIn("toolState.audio_transcribe", fn,
                      "状态条未读顶层 audio_transcribe 字段")
        self.assertIn("toolState.video_transcribe", fn,
                      "状态条未读顶层 video_transcribe 字段")
        # 过时假信息不得再出现在界面文案里
        self.assertNotIn("阶段 3 转写后端尚未接入", code,
                         "界面仍显示过时的「S3 尚未接入」文案")
        # capabilityEnabled 辅助函数只服务于占位清单，已随修复删除
        self.assertNotIn("function capabilityEnabled", code,
                         "capabilityEnabled 未删除，仍是读占位清单的死路径")
        self.assertNotIn("mediaOn", code,
                         "死变量 mediaOn 未删除")

    def test_02_ui_tool_status_shows_real_capabilities(self):
        """状态条仍要如实显示音视频两项的真实就绪状态（不能整段删掉）。"""
        code = self.strip_js_comments(self.ui_js)
        fn = code[code.index("function renderToolStatus"):
                  code.index("function loadTools")]
        self.assertIn("音频转写：", fn, "状态条缺少音频转写状态")
        self.assertIn("视频提取：", fn, "状态条缺少视频提取状态")
        self.assertIn("at.enabled", fn, "音频转写状态未按真实能力渲染")
        self.assertIn("vt.enabled", fn, "视频提取状态未按真实能力渲染")

    # ------------------------------------------------------------------ #
    # A2 · media_ready 误导字段
    # ------------------------------------------------------------------ #
    def test_03_media_ready_contract_kept_and_disambiguated(self):
        """media_ready 恒 false 是**契约锁死**的已知状态，不能改行为；
        但必须澄清语义，避免外部集成误当就绪判据。"""
        import media_tools
        # 契约锁死：占位清单不得改写、media_ready 恒 false
        caps = media_tools.capabilities()
        self.assertTrue(all(not v["enabled"] for v in caps.values()),
                        "S1 占位清单被改动")
        self.assertFalse(media_tools.media_ready(),
                         "media_ready 恒 False 被破坏")
        # 语义澄清：note 必须点明它是占位遗留 + 真实判据在哪
        note = media_tools.payload()["note"]
        self.assertIn("media_ready", note, "note 未澄清 media_ready 的语义")
        self.assertIn("audio_transcribe", note,
                      "note 未指明真实就绪状态的读取位置")

    # ------------------------------------------------------------------ #
    # A3 · /api/transcribe 视频拒收（红线 2）
    # ------------------------------------------------------------------ #
    def test_04_transcribe_endpoint_rejects_video(self):
        """/api/transcribe 是锁死的空心占位（端点与文案都被测试锁死），
        但**必须先做视频拒收**——它用的是音视频并集，接线就会违反红线 2。"""
        # 端点仍在（契约锁死）
        self.assertIn('path == "/api/transcribe"', self.app_src)
        # 占位文案仍在（契约锁死）
        self.assertIn("阶段 3 音视频转写需专用转写器", self.app_src)
        # 视频拒收分支必须存在，且用 MEDIA_VIDEO 精确判定
        self.assertIn("format_registry.MEDIA_VIDEO", self.app_src,
                      "端点未按 MEDIA_VIDEO 拒收视频")
        self.assertIn("红线 2", self.app_src,
                      "视频拒收分支未说明红线依据")
        # 且必须在存在性判定**之前**
        body = self.app_src[self.app_src.index("def _api_transcribe"):
                            self.app_src.index("def _api_word_inspect")]
        self.assertLess(body.index("MEDIA_VIDEO"), body.index("os.path.exists"),
                        "视频拒收必须先于存在性判定（红线 2 优先级）")

    # ------------------------------------------------------------------ #
    # B1 · 回跳原文补最后一跳
    # ------------------------------------------------------------------ #
    def test_05_kb_open_source_executes_open(self):
        """回跳原文必须能真正打开文件（此前只返回坐标，前端弹个 toast 就完）。"""
        self.assertIn('path == "/api/kb/open-source"', self.app_src)
        body = self.app_src[self.app_src.index('path == "/api/kb/open-source"'):
                            self.app_src.index('path == "/api/kb/rebuild"')]
        self.assertIn('data.get("open")', body,
                      "回跳原文未接 open 参数（最后一跳没接上）")
        self.assertIn("_open_document", body,
                      "回跳原文未执行打开动作")
        self.assertIn('res["opened"] = True', body,
                      "回跳原文未回显打开结果")
        # 前端必须真的传 open=true
        self.assertIn('open: true', self.ui_js,
                      "前端未传 open=true，回跳仍只会弹坐标")

    # ------------------------------------------------------------------ #
    # B2 · 阶段 1 的 out/md/*.md 可在软件内打开
    # ------------------------------------------------------------------ #
    def test_06_artifact_open_endpoint(self):
        """新增 /api/artifacts/open：只放行**产物目录内的 .md**。

        注意**不得放宽 /api/open 的白名单**——那是 v0.4.0 刻意堵死
        「启动任意程序」的收敛成果，既有测试（test_app.py）明确断言
        derived 产物走 /api/open 必须失败。
        """
        self.assertIn('path == "/api/artifacts/open"', self.app_src,
                      "缺 /api/artifacts/open 端点")
        fn = self.app_src[self.app_src.index("def _api_open_artifact"):
                          self.app_src.index("def _api_open_folder")]
        self.assertIn("_kb_allowed_roots", fn,
                      "打开产物未走允许根目录围栏")
        self.assertIn('.md', fn, "打开产物未限定 .md 后缀")
        self.assertIn("_open_document", fn, "打开产物未执行打开动作")
        # /api/open 的白名单原文不得被改（既有测试锁死）
        self.assertIn("只允许打开本软件的日志文件与设置文件", self.app_src,
                      "/api/open 白名单文案被改动")
        # 前端入口
        self.assertIn('id="btnOpenArtifact"', self.ui_html,
                      "精读页缺「打开产物」按钮")
        self.assertIn('"/api/artifacts/open"', self.ui_js,
                      "前端未调用 /api/artifacts/open")

    # ------------------------------------------------------------------ #
    # B3 · 订阅抓取接上多轮提纯
    # ------------------------------------------------------------------ #
    def test_07_subscription_iterate_wired(self):
        """iterate_fn / refine_rounds 此前一路透传却从不使用，属空承诺。"""
        import subscription_engine as E
        src = (ROOT / "subs" / "subscription_engine.py").read_text(
            encoding="utf-8")
        self.assertIn("def default_iterate_fn", src,
                      "缺默认提纯器 default_iterate_fn")
        self.assertIn("iterate_fn(md, refine_rounds)", src,
                      "_sync_one 未调用 iterate_fn（提纯仍未接线）")
        # 后处理产物必须被排除，否则会被再次提纯 / 重复入库
        self.assertIn("REFINE_SUFFIX", src, "未排除 .refine.md 产物")
        self.assertIn("REVISE_SUFFIX", src, "未排除 .revise.md 产物")
        # 提纯失败必须如实降级，绝不丢内容
        self.assertIn("提纯失败", src, "提纯失败未如实回显")
        # 默认注入
        self.assertIn("iterate_fn=default_iterate_fn", src,
                      "start() 未默认接上提纯器")

    def test_08_subscription_refine_excludes_derived(self):
        """带 iterate_fn 跑一轮：产物目录里的 .refine.md 不得被重复入库。"""
        import subscription_engine as E
        outdir = self.tmp / "out"
        derived = outdir / "derived"
        derived.mkdir(parents=True)
        kbdir = self.tmp / "kb"
        kbdir.mkdir()

        # 预置两个文件：一份原始转写 + 一份后处理产物（.refine.md）
        (derived / "doc.md").write_text(
            "<!-- src: x -->\n## k\n\n<!-- anchor: d1 | block: 2 -->\n- 要点",
            encoding="utf-8")
        (derived / "doc_deadbeef1234.refine.md").write_text(
            "<!-- src: y -->\n## k2", encoding="utf-8")

        ingested = []

        def disc(url, **kw):
            return {"ok": True, "entries": [
                {"id": "v1", "url": "u1", "title": "视频1"}]}

        def dl(url, tmpd, **kw):
            p = Path(tmpd) / (url + ".mp4")
            p.write_bytes(b"x")
            return {"ok": True, "path": str(p)}

        def tr(files, out):
            return {"ok": True}

        def ing(kd, md, **kw):
            ingested.append(md)
            return {"ok": True, "added": 1}

        def it(md, rounds):
            # 提纯「失败」——验证降级路径仍会入库原始转写
            raise ValueError("模拟提纯失败")

        sub = {"id": "s1", "url": "https://x/channel", "name": "测试",
               "seen_ids": [], "cookie_file": ""}
        res = E._sync_one(sub, outdir=outdir, kb_dir=kbdir,
                          discover_fn=disc, download_fn=dl,
                          transcribe_fn=tr, ingest_fn=ing, iterate_fn=it)
        self.assertTrue(res["ok"], "同步失败：%s" % res)
        # 只入库 1 份：原始转写；.refine.md 被排除
        self.assertEqual(len(ingested), 1,
                         "入库数量不对（.refine.md 应被排除）：%s" % ingested)
        self.assertTrue(ingested[0].endswith("doc.md"),
                        "入库的不是原始转写：%s" % ingested[0])

    # ------------------------------------------------------------------ #
    # B4 · 知识库重建索引 / 清理入口
    # ------------------------------------------------------------------ #
    def test_09_refine_extract_mode_echoes_instruction(self):
        """extract 模式（默认）不支持自定义指令，此前**静默丢弃**。"""
        src = (ROOT / "knowledge" / "refine.py").read_text(encoding="utf-8")
        self.assertIn("不支持自定义修订指令", src,
                      "extract 模式未回显「不支持自定义修订指令」")
        body = src[src.index("def _run_revise_inner"):
                   src.index("def _run_revise_extract")]
        self.assertIn("instruction", body,
                      "extract 分支未检查 instruction 是否为空")

    def test_10_kb_rebuild_index(self):
        """重建索引：entries 是主数据、entries_fts 是派生索引，重建不丢条目。"""
        import kb
        kbdir = self.tmp / "kb"
        kb.init_kb(kbdir)
        md = self.tmp / "src.md"
        md.write_text(
            "<!-- src: doc_abc123def45 | path: src.md | format: .md | "
            "converter: t | extracted: 2026-01-01 00:00:00 | size: 10 | "
            "sha256: abc | anchors: block -->\n"
            "<!-- anchor: doc_abc123def45 | block: 1 -->\n"
            "独特词元 zzzqwert\n", encoding="utf-8")
        r = kb.ingest_md(kbdir, str(md), allowed_roots=[str(self.tmp)])
        self.assertTrue(r.get("ok"), "入库失败：%s" % r)
        self.assertEqual(r.get("added"), 1, "应入库 1 条")

        # 重建前后条目数必须一致（重建不丢条目）
        before = kb.kb_status(kbdir).get("entries")
        rb = kb.rebuild_index(kbdir)
        self.assertTrue(rb.get("ok"), "重建索引失败：%s" % rb)
        self.assertEqual(rb.get("entries"), before,
                         "重建前后主数据条目数不一致（重建丢了条目）")
        self.assertEqual(rb.get("indexed"), before,
                         "重建后索引条目数与主数据不一致")
        # 重建后仍能检索到
        q = kb.query(kbdir, "独特词元")
        self.assertTrue(q.get("ok"), "重建后检索失败：%s" % q)
        self.assertTrue(q.get("results"), "重建后检索不到内容")

    def test_11_kb_reset_and_endpoints(self):
        """清空条目 + 两个维护端点 + UI 入口。"""
        import kb
        kbdir = self.tmp / "kb"
        kb.init_kb(kbdir)
        md = self.tmp / "src.md"
        md.write_text(
            "<!-- src: doc_abc123def45 | path: src.md | format: .md | "
            "converter: t | extracted: 2026-01-01 00:00:00 | size: 10 | "
            "sha256: abc | anchors: block -->\n"
            "<!-- anchor: doc_abc123def45 | block: 1 -->\n内容\n",
            encoding="utf-8")
        kb.ingest_md(kbdir, str(md), allowed_roots=[str(self.tmp)])
        self.assertGreater(kb.kb_status(kbdir).get("entries", 0), 0)
        r = kb.reset_kb(kbdir)
        self.assertTrue(r.get("ok"), "清空失败：%s" % r)
        self.assertEqual(kb.kb_status(kbdir).get("entries"), 0,
                         "清空后仍有条目")
        # 端点
        self.assertIn('path == "/api/kb/rebuild"', self.app_src,
                      "缺 /api/kb/rebuild 端点")
        self.assertIn('path == "/api/kb/reset"', self.app_src,
                      "缺 /api/kb/reset 端点")
        # UI 入口
        self.assertIn('id="btnKbRebuild"', self.ui_html, "缺「重建索引」按钮")
        self.assertIn('id="btnKbReset"', self.ui_html, "缺「清空条目」按钮")
        self.assertIn('"/api/kb/rebuild"', self.ui_js, "前端未调用重建端点")
        self.assertIn('"/api/kb/reset"', self.ui_js, "前端未调用清空端点")

    # ------------------------------------------------------------------ #
    # C3 · >50MB 非 UTF-8 的「建议先拆分」提示
    # ------------------------------------------------------------------ #
    def test_12_large_text_split_hint(self):
        """SPEC §6.4 限制 B 写明的操作建议此前从未编码进实现。

        落在 app.py 后处理层（**不动冻结内核 extract.py**——它被 test_59 的
        「只允许版本号变更」硬断言锁死）。
        """
        self.assertIn("LARGE_TEXT_SPLIT_HINT_BYTES", self.app_src,
                      "app.py 缺大文件提示阈值")
        self.assertIn("_annotate_large_text_hints", self.app_src,
                      "app.py 缺大文件提示标注函数")
        # 必须落在 app.py 而非 extract.py
        extract_src = (ROOT / "extract.py").read_text(encoding="utf-8")
        self.assertNotIn("LARGE_TEXT_SPLIT_HINT_BYTES", extract_src,
                         "不得改冻结内核 extract.py（只允许版本号变更）")
        # 只对文本类生效
        fn = self.app_src[self.app_src.index("def _annotate_large_text_hints"):
                          self.app_src.index("def _dry_run")]
        self.assertIn('"文本类"', fn, "大文件提示未限定文本类")
        # 前端要显示得出来
        self.assertIn("file-hint", self.ui_js, "前端未渲染大文件提示")
        self.assertIn(".file-hint", (ROOT / "ui" / "app.css").read_text(
            encoding="utf-8"), "缺 .file-hint 样式")


if __name__ == "__main__":
    unittest.main(verbosity=2)
