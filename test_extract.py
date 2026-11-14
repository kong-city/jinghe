#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阶段 1「文件内容提取 + 汇总」提取质量回归测试。

标准库 unittest，零第三方依赖。

设计约定：
  * 每次运行在临时目录里重新执行 extract.py（默认参数、以 samples/ 为输入），
    绝不改动项目里已有的 out/ 产物，也不修改 extract.py 本身。
  * 断言只依赖「产物契约」（结构、自洽性、对账等式），不硬编码某个转换器的
    具体字符数，因此「技能脚本 / 内置回退」两条转换路径都应通过。
  * 覆盖：件数对账、空文件扫描、标题层级与表格抽检、单文件 source 头部注释、
    音视频分流（阶段 3 待支持）、INDEX.md 与 run.log 验收结论一致、
    MERGED.md 每节带来源标注、样例集完整盘点、
    大文件（>100MB）与旧格式（.doc/.xls/.ppt）降级标记、
    红线反例（空文本 / 视频 / 无文字层 PDF / 加密文档 / 超大文件 / GBK）、
    降级链（技能脚本失败回退、markitdown 未安装）、原有 4 文件基线锚点、
    .text/.log 双转换路径回归、技能脚本部分转换器补齐（test_19，归属 #10）、
    #9 第一批 6 格式真实提取回归（test_21）与 5 类真加密/无效容器独立状态（test_20）、
    #9 第二批块级锚点/出处最小集转正（test_22/test_23，17:16）、
    #10 GBK 前置编码层无损解码转正（test_24，17:58）+ BOM 去除边界（test_25）。
  * test_24 的编码断言锚定「判定：严格解码命中 gbk」等留痕字段，不用裸编码名：
    fixture 原名 gbk.txt 会让文件名本身满足 assertIn("gbk", ...)，使「探测是否
    精确命中 gbk」失效（qa-verify 终验实证），故改名为 cp936-legacy.txt。
  * test_25 除产物级断言外，还在用例内 import extract 直调
    preprocess_text_encoding，锁住前置层内部契约：副本必须与源同名、BOM 必须
    剥离、纯 UTF-8 必须零复制、源文件字节不变（产物正文的 assertNotIn("\ufeff")
    会被 normalize_markdown 的 replace 掩盖，不足以作门禁）。
  * test_19 原拟为门禁，因 extract.py:185-197 已用 conv.setdefault 实现补齐而
    转正为正式断言；若该补齐被回退，用例会变红，等价于门禁效果。
  * 现无 @expectedFailure 门禁：GBK 无乱码已于 #10「文本编码前置预处理层」
    （2026-11-12 17:58）落地后转正为 test_24_no_lossy_encoding。
  * 曾为门禁、因能力落地而转正为正式断言的共 6 项：
    INDEX 备注标注占位产物（test_16）、产物目录实盘对账/重跑不残留（test_17）、
    加密文档「待人工授权」降级（test_20，15:47 富文档分支）、
    块级出处锚点/出处最小集（test_22，#9 第二批 2026-11-12 17:16 转正）、
    阶段2 摘要排除清单（test_23，#9 第二批 2026-11-12 17:16 转正）、
    无有损编码 / GBK 前置预处理层（test_24，#10 2026-11-12 17:58 转正）。
  * test_19 亦原拟为门禁，因 load_converters 已用 conv.setdefault 实现补齐而转正。
  * 红线反例大多在测试运行时的临时输入目录里构造；#9 第一批起 samples/ 由
    parser 扩充了 6 个真实富文档与 6 个降级样例（共 19 个，原有 7 个一字未动），
    test_20/test_21 直接复用这些真字节 fixture，不改动任何样例文件、不写项目 out/。
    主样例集的所有数字均按产物契约/对账等式动态解析，不硬编码具体件数。

运行：
    python test_extract.py            # 逐项结果 + 末尾数字摘要
    python -m unittest -v test_extract
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXTRACT = ROOT / "extract.py"
SAMPLES = ROOT / "samples"

# 与 extract.py 的 DEFERRED_EXT 对齐，用于扫描样例集里的音视频占位文件。
MEDIA_EXT = {
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".wma", ".amr",
    ".mp4", ".mov", ".avi", ".mkv", ".flv", ".webm", ".m4v",
}

# 与 extract.py 的 stats() 保持一致的统计口径。
HEAD_RE = re.compile(r"(?m)^\s{0,3}#{1,6}\s")
ROW_RE = re.compile(r"(?m)^\s*\|")
SOURCE_HEADER_RE = re.compile(
    r"^<!-- source: (?P<src>.+?) \| format: (?P<fmt>\.\w+) "
    r"\| extracted: (?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) -->\s*$")

_CTX: dict | None = None  # 模块级缓存：一次生成，供所有测试与末尾摘要复用


# --------------------------------------------------------------------------
# 解析辅助：全部针对「产物文本」，不 import extract.py。
# 例外：test_25 为锁住编码前置层的内部契约（同名副本 / BOM 剥离 / 零复制）会
# 就地在用例内 import 被测模块直调 preprocess_text_encoding——只读调用，不写项目
# 目录（workdir 指向 tempfile），也绝不修改 extract.py。
# --------------------------------------------------------------------------
def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def parse_index(text: str) -> dict:
    """从 INDEX.md 解析对账数字与对账表数据行。"""
    def grab(pattern, default=None):
        m = re.search(pattern, text)
        return m.group(1) if m else default

    total = grab(r"源文件总数：(\d+)")
    conv = grab(r"纳入转换\s*(\d+)")
    defer = grab(r"阶段\s*3\s*预留\s*(\d+)")
    legacy = grab(r"需预处理\s*(\d+)")
    unsup = grab(r"不支持\s*(\d+)")
    success_line = grab(r"成功产出：(\d+)")

    rec = re.search(r"件数对账：候选\s*(\d+)\s*/\s*成功\s*(\d+)\s*/\s*未成功\s*(\d+)", text)
    cand, succ, fail = (rec.group(1), rec.group(2), rec.group(3)) if rec else (None, None, None)

    empty_line = grab(r"(?m)^-\s*空文件扫描：(.+)$")
    struct_line = grab(r"(?m)^-\s*结构抽检：(.+)$")

    rows = []
    for line in text.splitlines():
        m = re.match(r"^\|\s*(\d+|-)\s*\|", line)
        if not m:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 9:
            continue
        rows.append({
            "no": cells[0], "src": cells[1], "ext": cells[2], "status": cells[3],
            "chars": cells[4], "heads": cells[5], "rows": cells[6],
            "artifact": cells[7].strip("`"), "note": cells[8],
        })
    return {
        "total": total, "conv": conv, "defer": defer, "legacy": legacy,
        "unsup": unsup, "success_line": success_line,
        "cand": cand, "succ": succ, "fail": fail,
        "empty_line": empty_line, "struct_line": struct_line, "rows": rows,
    }


def parse_runlog(text: str) -> dict:
    def grab(pattern, default=None):
        m = re.search(pattern, text, re.M)
        return m.group(1) if m else default

    nums = {k: grab(r"(?m)^-\s*%s:\s*(\d+)$" % k)
            for k in ("盘点", "候选", "成功", "未成功", "阶段3预留", "空文件", "无标题层级")}
    verdict = grab(r"(?m)^验收:\s*(.+)$")
    lines = []
    for m in re.finditer(r"(?m)^-\s*\[(.+?)\]\s+(.+?)\s+->\s+(\S+)", text):
        lines.append({"status": m.group(1), "src": m.group(2), "artifact": m.group(3)})
    return {"nums": nums, "verdict": verdict, "lines": lines}


def build_context() -> dict:
    """在临时目录里重新生成一次产物，返回解析好的上下文。失败也返回可诊断信息。"""
    tmp = tempfile.TemporaryDirectory(prefix="jinghe-qa-")
    outdir = Path(tmp.name) / "out"
    proc = subprocess.run(
        [sys.executable, str(EXTRACT), "-i", str(SAMPLES), "-o", str(outdir)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    ctx = {
        "tmp": tmp, "outdir": outdir,
        "rc": proc.returncode, "stdout": proc.stdout or "", "stderr": proc.stderr or "",
        "samples": sorted(p for p in SAMPLES.rglob("*") if p.is_file()),
        "index_text": "", "runlog_text": "", "merged_text": "",
        "index": None, "runlog": None,
        "md_files": sorted((outdir / "md").glob("*.md")) if (outdir / "md").is_dir() else [],
    }
    for key, name in (("index_text", "INDEX.md"), ("runlog_text", "run.log"),
                      ("merged_text", "MERGED.md")):
        p = outdir / name
        if p.is_file():
            ctx[key] = _read(p)
    if ctx["index_text"]:
        ctx["index"] = parse_index(ctx["index_text"])
    if ctx["runlog_text"]:
        ctx["runlog"] = parse_runlog(ctx["runlog_text"])
    return ctx


def get_ctx() -> dict:
    global _CTX
    if _CTX is None:
        _CTX = build_context()
    return _CTX


def scenario_paths(td: str) -> tuple[Path, Path]:
    """为独立场景准备 <临时目录>/input 与 <临时目录>/out。"""
    root = Path(td)
    indir, outdir = root / "input", root / "out"
    indir.mkdir()
    return indir, outdir


def run_scenario(indir: Path, outdir: Path, extra_args=()) -> dict:
    """在给定输入/输出目录运行一次 extract.py，返回解析好的场景上下文。

    用于红线反例与降级链：输入目录里的文件由各测试自行构造，不写 samples/。
    """
    proc = subprocess.run(
        [sys.executable, str(EXTRACT), "-i", str(indir), "-o", str(outdir), *extra_args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    ctx = {
        "indir": indir, "outdir": outdir,
        "rc": proc.returncode, "stdout": proc.stdout or "", "stderr": proc.stderr or "",
        "index_text": "", "runlog_text": "", "merged_text": "",
        "index": None, "runlog": None, "md_files": [],
    }
    for key, name in (("index_text", "INDEX.md"), ("runlog_text", "run.log"),
                      ("merged_text", "MERGED.md")):
        p = outdir / name
        if p.is_file():
            ctx[key] = _read(p)
    if ctx["index_text"]:
        ctx["index"] = parse_index(ctx["index_text"])
    if ctx["runlog_text"]:
        ctx["runlog"] = parse_runlog(ctx["runlog_text"])
    if (outdir / "md").is_dir():
        ctx["md_files"] = sorted((outdir / "md").glob("*.md"))
    return ctx


# --------------------------------------------------------------------------
# #11 CID 字体夹具：纯 Python 手工拼最小 PDF（自包含，绝不依赖桌面真实文件）
#
# 用途：锁住「/Type0 + /Encoding /Identity-H 时，内容流 <...> 是 2 字节字形号
# GID，必须按 /ToUnicode 还原」以及「ToUnicode 缺失时不得假成功」两条红线。
# 不写 xref：被测解析器按对象头扫描，也不该依赖 xref（很多导出器写错）。
# --------------------------------------------------------------------------
def _pdf_stream_object(data: bytes) -> bytes:
    """最小 stream 对象体（不压缩，便于测试里肉眼核对）。"""
    return b"<< /Length %d >>\nstream\n" % len(data) + data + b"\nendstream"


def _cid_pdf_bytes(pairs: dict[int, str], codes: list[int],
                   with_tounicode: bool = True) -> bytes:
    """拼一个单页 CID PDF：pairs 为 GID -> Unicode，codes 为正文使用的 GID 序列。"""
    hex_codes = "".join("%04X" % c for c in codes)
    content = ("BT\n/F1 12 Tf\n72 700 Td\n<%s> Tj\nET\n" % hex_codes).encode("ascii")
    font = (b"<< /Type /Font /Subtype /Type0 /BaseFont /TestCID "
            b"/Encoding /Identity-H /DescendantFonts [6 0 R]")
    if with_tounicode:
        font += b" /ToUnicode 8 0 R"
    font += b" >>"
    objs = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 7 0 R /Resources << /Font << /F1 5 0 R >> >> >>"),
        5: font,
        6: (b"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /TestCID "
            b"/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) "
            b"/Supplement 0 >> /DW 1000 >>"),
        7: _pdf_stream_object(content),
    }
    if with_tounicode:
        entries = "\n".join(
            "<%04X> <%s>" % (gid, dst.encode("utf-16-be").hex().upper())
            for gid, dst in sorted(pairs.items()))
        cmap = ("/CIDInit /ProcSet findresource begin\n"
                "12 dict begin\nbegincmap\n"
                "/CIDSystemInfo <</Registry (Adobe) /Ordering (UCS) /Supplement 0>> def\n"
                "/CMapName /Adobe-Identity-UCS def\n/CMapType 2 def\n"
                "1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n"
                "%d beginbfchar\n%s\nendbfchar\n"
                "endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n"
                % (len(pairs), entries)).encode("ascii")
        objs[8] = _pdf_stream_object(cmap)
    out = bytearray(b"%PDF-1.7\n")
    for num in sorted(objs):
        out += b"%d 0 obj\n" % num + objs[num] + b"\nendobj\n"
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\n%%%%EOF\n" % (max(objs) + 1)
    return bytes(out)


class ExtractQualityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = get_ctx()

    # ---- 前置：生成成功、产物齐全 ------------------------------------------
    def test_01_generation_ok(self):
        c = self.c
        self.assertEqual(
            c["rc"], 0,
            "extract.py 运行失败\n--- stdout ---\n%s\n--- stderr ---\n%s"
            % (c["stdout"], c["stderr"]))
        for name in ("INDEX.md", "MERGED.md", "run.log"):
            self.assertTrue((c["outdir"] / name).is_file(), "缺少产物 %s" % name)
        self.assertTrue((c["outdir"] / "md").is_dir(), "缺少 out/md 目录")
        self.assertTrue(c["md_files"], "out/md 下没有任何单文件产物")
        self.assertIsNotNone(c["index"], "INDEX.md 无法解析")
        self.assertIsNotNone(c["runlog"], "run.log 无法解析")

    # ---- 1) 件数对账：候选 = 成功 + 未成功 ----------------------------------
    def test_02_reconciliation(self):
        c, idx, log = self.c, self.c["index"], self.c["runlog"]
        cand, succ, fail = int(idx["cand"]), int(idx["succ"]), int(idx["fail"])
        self.assertEqual(cand, succ + fail,
                         "INDEX 件数对账不成立：候选 %d != 成功 %d + 未成功 %d"
                         % (cand, succ, fail))
        # INDEX 与 run.log 三个数字两两一致
        ln = log["nums"]
        self.assertEqual((cand, succ, fail),
                         (int(ln["候选"]), int(ln["成功"]), int(ln["未成功"])),
                         "INDEX 与 run.log 的对账数字不一致")
        self.assertEqual(int(idx["success_line"]), succ, "「成功产出」与对账成功数不一致")
        # 源文件总数 = 各分流之和；候选 = 纳入转换
        self.assertEqual(int(idx["total"]),
                         int(idx["conv"]) + int(idx["defer"]) + int(idx["legacy"]) + int(idx["unsup"]),
                         "源文件总数 != 纳入转换+阶段3预留+需预处理+不支持")
        self.assertEqual(cand, int(idx["conv"]), "候选数 != 纳入转换数")
        self.assertEqual(int(idx["total"]), int(ln["盘点"]), "INDEX 总数 != run.log 盘点数")
        self.assertEqual(len(idx["rows"]), int(idx["total"]),
                         "INDEX 对账表行数 != 源文件总数（有文件漏记）")
        # 成功行数、产物文件数、成功数三者一致
        ok_rows = [r for r in idx["rows"] if r["status"] == "成功"]
        self.assertEqual(len(ok_rows), succ, "INDEX 中状态为「成功」的行数 != 成功数")
        self.assertEqual(len(c["md_files"]), succ, "out/md 产物数 != 成功数")
        for r in ok_rows:
            art = c["outdir"] / r["artifact"]
            self.assertTrue(art.is_file(), "成功行指向的产物不存在：%s" % r["artifact"])
            self.assertTrue(art.name.endswith(".md"))

    # ---- 2) 空文件扫描 ------------------------------------------------------
    def test_03_empty_file_scan(self):
        c, idx, log = self.c, self.c["index"], self.c["runlog"]
        self.assertIsNotNone(idx["empty_line"], "INDEX 缺少「空文件扫描」自检项")
        empty_line = idx["empty_line"]
        log_empties = int(log["nums"]["空文件"])

        # 实际：所有成功产物文件非空，且去掉 source 头部后仍有正文；chars 列 > 0
        actual_empty = []
        for r in idx["rows"]:
            if r["status"] != "成功":
                continue
            art = c["outdir"] / r["artifact"]
            body = _read(art)
            stripped = re.sub(r"^<!--.*?-->\s*", "", body, count=1, flags=re.S).strip()
            if not body.strip() or not stripped or int(r["chars"]) == 0:
                actual_empty.append(r["artifact"])

        if empty_line.strip() == "无空文件":
            self.assertEqual(log_empties, 0, "INDEX 报无空文件，但 run.log 空文件数非 0")
            self.assertEqual(actual_empty, [], "实际存在空产物：%s" % actual_empty)
        else:
            self.assertGreater(log_empties, 0, "INDEX 列出空文件，但 run.log 空文件数为 0")
            self.assertEqual(len(actual_empty), log_empties,
                             "INDEX/run.log 报告的空文件数与实际不符")

        # 边界样例 empty.txt（0 字节）必须被纳入且「不产出空文件」
        empty_samples = [p for p in c["samples"] if p.stat().st_size == 0]
        if empty_samples:
            for p in empty_samples:
                rec = [r for r in idx["rows"] if r["src"].replace("\\", "/").endswith(p.name)]
                self.assertTrue(rec, "0 字节样例 %s 未出现在对账表" % p.name)
                self.assertEqual(rec[0]["status"], "成功", "空样例 %s 未成功降级" % p.name)
                art = c["outdir"] / rec[0]["artifact"]
                self.assertTrue(art.is_file() and art.stat().st_size > 0,
                                "空样例 %s 产出了空文件" % p.name)

    # ---- 3) 标题层级与表格抽检 ----------------------------------------------
    def test_04_headings_and_tables(self):
        c, idx, log = self.c, self.c["index"], self.c["runlog"]
        self.assertIsNotNone(idx["struct_line"], "INDEX 缺少「结构抽检」自检项")

        # 逐产物复算 stats，与 INDEX 表格数字核对
        with_heads, with_rows = 0, 0
        zero_head_arts = []
        for r in idx["rows"]:
            if r["status"] != "成功":
                continue
            text = _read(c["outdir"] / r["artifact"])
            heads = len(HEAD_RE.findall(text))
            rows = len(ROW_RE.findall(text))
            self.assertEqual(heads, int(r["heads"]),
                             "%s 标题数统计不一致（产物 %d / INDEX %s）"
                             % (r["artifact"], heads, r["heads"]))
            self.assertEqual(rows, int(r["rows"]),
                             "%s 表格行数统计不一致（产物 %d / INDEX %s）"
                             % (r["artifact"], rows, r["rows"]))
            with_heads += heads > 0
            with_rows += rows > 0
            if heads == 0:
                zero_head_arts.append(r["artifact"])

        # 样例集里应同时存在「含标题」与「含表格」的产物，抽检才有意义
        self.assertGreater(with_heads, 0, "没有任何产物含标题层级")
        self.assertGreater(with_rows, 0, "没有任何产物含表格行")

        # 结构抽检结论与实际一致（两种措辞都兼容）
        struct = idx["struct_line"]
        if "全部含标题层级" in struct:
            self.assertEqual(zero_head_arts, [], "INDEX 报全部含标题，但存在无标题产物")
            self.assertEqual(int(log["nums"]["无标题层级"]), 0)
        else:
            self.assertEqual(int(log["nums"]["无标题层级"]), len(zero_head_arts),
                             "run.log 无标题层级数与实际不符")
            for art in zero_head_arts:
                self.assertIn(art, struct, "无标题产物 %s 未列入结构抽检结论" % art)
            # 对应行应带「未发现标题层级」提示
            for r in idx["rows"]:
                if r["status"] == "成功" and r["artifact"] in zero_head_arts:
                    self.assertIn("未发现标题层级", r["note"],
                                  "无标题产物 %s 缺少降级备注" % r["artifact"])

        # MERGED.md 不应泄漏源文件的顶级标题（标题已降位）
        self.assertEqual(len(re.findall(r"(?m)^# ", c["merged_text"])), 1,
                         "MERGED.md 出现多处一级标题，疑似源文件标题未降位")

    # ---- 4) 单文件产物头部 source 注释 --------------------------------------
    def test_05_source_header(self):
        c, idx = self.c, self.c["index"]
        src_names = {p.name for p in c["samples"]}
        src_rels = {p.relative_to(SAMPLES).as_posix() for p in c["samples"]}
        for art in c["md_files"]:
            first = _read(art).splitlines()[0] if _read(art).splitlines() else ""
            m = SOURCE_HEADER_RE.match(first)
            self.assertIsNotNone(m, "%s 首行缺少合规 source 头部注释：%r" % (art.name, first))
            s, fmt = m.group("src"), m.group("fmt")
            self.assertTrue(s in src_rels or Path(s).name in src_names,
                            "%s 的 source 无法对应到样例：%s" % (art.name, s))
            self.assertEqual(Path(s).suffix.lower(), fmt.lower(),
                             "%s 的 format 与源文件扩展名不一致" % art.name)
            body = "\n".join(_read(art).splitlines()[1:]).strip()
            self.assertTrue(body, "%s 在 source 注释之后没有正文" % art.name)

    # ---- 5) 音视频被标记「阶段 3 待支持」且不产出 .md ------------------------
    def test_06_deferred_media(self):
        c, idx, log = self.c, self.c["index"], self.c["runlog"]
        medias = [p for p in c["samples"] if p.suffix.lower() in MEDIA_EXT]
        self.assertTrue(medias, "样例集里没有任何音视频占位文件，分流用例失效")
        self.assertTrue(any(p.name == "future-audio.mp3" for p in medias),
                        "缺少已知占位样例 future-audio.mp3")

        stems = {p.stem.lower() for p in medias}
        for p in medias:
            rec = [r for r in idx["rows"]
                   if r["src"].replace("\\", "/").endswith(p.name)]
            self.assertTrue(rec, "音视频 %s 未出现在对账表" % p.name)
            r = rec[0]
            self.assertEqual(r["status"], "阶段 3 待支持",
                             "音视频 %s 状态不是「阶段 3 待支持」" % p.name)
            self.assertIn(r["artifact"], ("", "-"),
                          "音视频 %s 竟然产出了产物 %s" % (p.name, r["artifact"]))
            # run.log 对应行
            log_rec = [l for l in log["lines"] if l["src"].replace("\\", "/").endswith(p.name)]
            self.assertTrue(log_rec, "run.log 缺少 %s 的分流记录" % p.name)
            self.assertEqual(log_rec[0]["status"], "阶段 3 待支持")

        # md/ 下不得出现以媒体 stem 命名的产物
        for art in c["md_files"]:
            self.assertFalse(any(s in art.stem.lower() for s in stems),
                             "音视频占位文件被错误地产出了 .md：%s" % art.name)

        # 计数一致，且 deferred 不计入候选
        self.assertEqual(int(idx["defer"]), len(medias),
                         "INDEX 阶段3预留数 != 样例集里媒体文件数")
        self.assertEqual(int(log["nums"]["阶段3预留"]), len(medias))
        self.assertLessEqual(int(idx["defer"]),
                             int(idx["total"]) - int(idx["cand"]),
                             "阶段3预留文件被错误计入了候选")

        # 守护：占位文件应为极小的可读文本，而非真实音视频二进制
        for p in medias:
            self.assertLess(p.stat().st_size, 64 * 1024,
                            "%s 体积过大，疑似误放了真实音视频二进制" % p.name)
            _read(p)  # 能按 utf-8 解码，说明是文本占位

    # ---- 6) INDEX.md 与 run.log 存在且验收结论一致 --------------------------
    def test_07_index_runlog_acceptance(self):
        c, idx, log = self.c, self.c["index"], self.c["runlog"]
        self.assertTrue((c["outdir"] / "INDEX.md").is_file())
        self.assertTrue((c["outdir"] / "run.log").is_file())
        cand, succ = int(idx["cand"]), int(idx["succ"])
        empties = int(log["nums"]["空文件"])
        # 验收结论完整行（extract.py:458）是「验收: 部分未完成，见 INDEX.md 未成功项」，
        # 「通过」则是「验收: 通过」。故此处对「部分未完成」用完整字符串精确匹配，
        # 其余测试用包含匹配；切勿改成精确等于「部分未完成」（spec 澄清3 特别提醒）。
        verdict = (log["verdict"] or "").strip()
        self.assertIn(verdict, ("通过", "部分未完成，见 INDEX.md 未成功项"),
                      "run.log 验收结论异常：%r" % verdict)

        if verdict == "通过":
            self.assertEqual(succ, cand, "验收=通过，但成功数 != 候选数")
            self.assertEqual(empties, 0, "验收=通过，但存在空文件")
            bad = [r["src"] for r in idx["rows"]
                   if r["status"] not in ("成功", "阶段 3 待支持", "需预处理", "不支持")]
            self.assertEqual(bad, [], "验收=通过，但对账表存在失败项：%s" % bad)
        else:
            self.assertTrue(succ < cand or empties > 0,
                            "验收=部分未完成，但成功数=候选且无空文件，结论不自洽")

        # 数字层面再次交叉核对
        self.assertEqual(int(idx["success_line"]), int(log["nums"]["成功"]))
        self.assertEqual(int(idx["total"]), int(log["nums"]["盘点"]))
        self.assertEqual(int(log["nums"]["成功"]) + int(log["nums"]["未成功"]),
                         int(log["nums"]["候选"]),
                         "run.log 内 候选 != 成功 + 未成功")

    # ---- 7) MERGED.md 每节带来源标注 ----------------------------------------
    def test_08_merged_source_annotation(self):
        c, idx = self.c, self.c["index"]
        merged = c["merged_text"]
        self.assertTrue(merged.strip(), "MERGED.md 为空")
        self.assertIn("# 内容汇总", merged, "MERGED.md 缺少汇总标题")
        ok_srcs = [r["src"] for r in idx["rows"] if r["status"] == "成功"]
        sections = re.split(r"(?m)^## \d+\.\s+", merged)[1:]
        self.assertEqual(len(sections), len(ok_srcs),
                         "MERGED.md 分节数 %d != 成功产物数 %d" % (len(sections), len(ok_srcs)))

        marked = []
        for sec in sections:
            m = re.search(r"(?m)^>\s*来源：`([^`]+)`", sec)
            self.assertIsNotNone(m, "MERGED.md 存在缺少「> 来源：」标注的分节")
            src = m.group(1)
            marked.append(src)
            self.assertIn(src, ok_srcs, "MERGED 来源标注 %s 不在成功清单里" % src)
            art_m = re.search(r"(?m)^>\s*单文件产物：`([^`]+)`", sec)
            self.assertIsNotNone(art_m, "分节 %s 缺少单文件产物标注" % src)
            self.assertTrue((c["outdir"] / art_m.group(1)).is_file(),
                            "分节 %s 标注的产物不存在" % src)
        # 每个成功源文件都被标注
        self.assertEqual(set(marked), set(ok_srcs),
                         "MERGED.md 来源标注集合与成功清单不一致")

    # ---- 8) 样例集完整盘点 --------------------------------------------------
    def test_09_sample_inventory(self):
        c, idx = self.c, self.c["index"]
        self.assertGreaterEqual(len(c["samples"]), 4, "原有 4 个样例疑似缺失")
        recorded = {r["src"].replace("\\", "/") for r in idx["rows"]}
        for p in c["samples"]:
            rel = p.relative_to(SAMPLES).as_posix()
            self.assertIn(rel, recorded, "样例 %s 未被盘点进对账表" % rel)
        self.assertEqual(len(c["samples"]), int(idx["total"]),
                         "样例集文件数 != INDEX 源文件总数")

    # ---- 9) 大文件与旧格式降级标记 ------------------------------------------
    def test_10_large_and_legacy_degradation(self):
        # 在独立临时目录构造 >100MB 稀疏文件与 .doc 占位，验证降级标记。
        # 这两个文件只在测试运行时生成，不写入 samples/，也不影响主样例集
        # （主样例集验收仍为「通过」）；extract.py 读内容前就按 size 跳过超大文件。
        with tempfile.TemporaryDirectory(prefix="jinghe-qa-degrade-") as td:
            root = Path(td)
            indir, outdir = root / "input", root / "out"
            indir.mkdir()
            shutil.copy2(SAMPLES / "chapter-01.txt", indir / "chapter-01.txt")
            (indir / "legacy.doc").write_text(
                "旧版 .doc 文本占位，用于验证「需预处理」标记（非真实二进制）",
                encoding="utf-8")
            with open(indir / "huge.txt", "wb") as fh:
                fh.truncate(100 * 1024 * 1024 + 1)  # 稀疏文件，>100MB

            proc = subprocess.run(
                [sys.executable, str(EXTRACT), "-i", str(indir), "-o", str(outdir)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            self.assertEqual(proc.returncode, 0,
                             "降级场景生成失败\n%s\n%s" % (proc.stdout, proc.stderr))
            idx = parse_index(_read(outdir / "INDEX.md"))
            rows = {r["src"].replace("\\", "/"): r for r in idx["rows"]}

            # 旧格式 -> 需预处理；大文件 -> 需拆分；均不产出产物
            self.assertIn("legacy.doc", rows)
            self.assertEqual(rows["legacy.doc"]["status"], "需预处理")
            self.assertIn(rows["legacy.doc"]["artifact"], ("", "-"))
            self.assertIn("huge.txt", rows)
            self.assertEqual(rows["huge.txt"]["status"], "需拆分")
            self.assertIn(rows["huge.txt"]["artifact"], ("", "-"))
            for art in (outdir / "md").glob("*.md"):
                self.assertNotIn("legacy", art.stem.lower())
                self.assertNotIn("huge", art.stem.lower())

            # 计数自洽：大文件计入候选且计入未成功；旧格式不计入候选
            self.assertEqual(int(idx["conv"]), 2, "候选应为 2（正常 txt + 超大 txt）")
            self.assertEqual(int(idx["succ"]), 1)
            self.assertEqual(int(idx["fail"]), 1)
            self.assertEqual(int(idx["legacy"]), 1)
            self.assertEqual(int(idx["cand"]), int(idx["succ"]) + int(idx["fail"]))
            self.assertEqual(int(idx["total"]),
                             int(idx["conv"]) + int(idx["defer"]) +
                             int(idx["legacy"]) + int(idx["unsup"]))

            # 该场景因存在未成功项，验收应为「部分未完成」
            log = parse_runlog(_read(outdir / "run.log"))
            self.assertIn("部分未完成", log["verdict"] or "",
                          "存在未成功项却判定为通过")
            for src, expect in (("legacy.doc", "需预处理"), ("huge.txt", "需拆分")):
                rec = [l for l in log["lines"] if l["src"].replace("\\", "/") == src]
                self.assertTrue(rec, "run.log 缺少 %s 的降级记录" % src)
                self.assertEqual(rec[0]["status"], expect)

    # ---- 10) 视频红线：不得把视频当音频转写 ---------------------------------
    def test_11_video_redline(self):
        # .mp4 与 .mp3 同属阶段3预留；断言不调用 ASR、不产出 md、显式留痕。
        with tempfile.TemporaryDirectory(prefix="jinghe-qa-video-") as td:
            indir, outdir = scenario_paths(td)
            (indir / "clip.mp4").write_text(
                "视频占位文本，非真实视频；阶段1 不得尝试 ASR 转写", encoding="utf-8")
            (indir / "ok.txt").write_text("# 基准标题\n\n正文\n", encoding="utf-8")
            c = run_scenario(indir, outdir)
            self.assertEqual(c["rc"], 0, "视频场景生成失败\n%s\n%s" % (c["stdout"], c["stderr"]))
            idx, log = c["index"], c["runlog"]
            rows = {r["src"].replace("\\", "/"): r for r in idx["rows"]}
            r = rows["clip.mp4"]
            self.assertEqual(r["status"], "阶段 3 待支持")
            self.assertIn(r["artifact"], ("", "-"))
            self.assertIn("未尝试解析", r["note"], "视频未显式记录「未尝试解析」")
            self.assertFalse(any("clip" in a.stem.lower() for a in c["md_files"]),
                             "视频被错误产出 .md")
            # 黑盒层验证未调用 ASR：整个产物目录不得出现任何转写类文件
            for p in outdir.rglob("*"):
                if p.is_file():
                    self.assertNotRegex(p.name, r"(?i)transcript|asr|转写|字幕")
            log_rec = [l for l in log["lines"] if l["src"] == "clip.mp4"]
            self.assertTrue(log_rec and log_rec[0]["status"] == "阶段 3 待支持",
                            "run.log 缺少视频分流留痕")
            self.assertEqual(int(idx["defer"]), 1)
            self.assertEqual(int(idx["cand"]), 1, "视频被错误计入候选")
            self.assertEqual(log["verdict"], "通过")

    # ---- 11) 空文本红线：不静默产出空文件 + 显式留痕 ------------------------
    def test_12_empty_text_redline(self):
        # 0 字节 txt 与空 CSV：阶段1 契约（spec 澄清1 定 (b)）是产出
        # 「带 source 头、带显式空标记的占位 md」并计入成功，绝非静默丢弃；
        # INDEX/run.log 均须留痕。规格要求「显式标注」而非「改成未成功」。
        with tempfile.TemporaryDirectory(prefix="jinghe-qa-empty-") as td:
            indir, outdir = scenario_paths(td)
            (indir / "blank.txt").write_bytes(b"")
            (indir / "blank.csv").write_bytes(b"")
            (indir / "ok.txt").write_text("# 基准标题\n\n正文\n", encoding="utf-8")
            c = run_scenario(indir, outdir)
            self.assertEqual(c["rc"], 0, "空文本场景生成失败\n%s\n%s" % (c["stdout"], c["stderr"]))
            idx, log = c["index"], c["runlog"]
            rows = {r["src"].replace("\\", "/"): r for r in idx["rows"]}
            for name in ("blank.txt", "blank.csv"):
                r = rows[name]
                self.assertNotIn(r["artifact"], ("", "-"), "%s 未产出占位 md" % name)
                art = outdir / r["artifact"]
                self.assertTrue(art.is_file() and art.stat().st_size > 0,
                                "%s 产出了空文件" % name)
                self.assertIsNotNone(SOURCE_HEADER_RE.match(_read(art).splitlines()[0]),
                                     "%s 占位 md 缺少 source 头部" % name)
                self.assertTrue([l for l in log["lines"] if l["src"] == name],
                                "run.log 缺少 %s 留痕" % name)
            self.assertIn("无空文件", idx["empty_line"])
            self.assertEqual(int(log["nums"]["空文件"]), 0)
            self.assertEqual(int(idx["cand"]), int(idx["succ"]) + int(idx["fail"]))
            # 规格定稿（spec 澄清1 定 (b)）：占位 md 计入「成功」属合规，test_12 不翻转。
            # 红线 1 判违规的三种情形：① 产物 0 字节；② 产物无 source 头；
            # ③ 异常项未留痕 / 对账不平却判「通过」。源文件本身为空不判违规。
            # 定稿要求「显式标注」而非「改成未成功」，故锁定 status == 「成功」。
            for name in ("blank.txt", "blank.csv"):
                self.assertEqual(rows[name]["status"], "成功",
                                 "%s 状态语义发生变化，请同步本断言与规格" % name)
            # 规格增强①：占位产物内应有显式空内容标记（空 CSV 为 <!-- 空 CSV -->，
            # 技能脚本与内置回退两条路径均产出该标记）
            self.assertIn("<!-- 空 CSV -->",
                          _read(outdir / rows["blank.csv"]["artifact"]),
                          "空 CSV 占位产物缺少显式空内容标记")
            # 团队指令2 / spec 定稿：占位产物在 INDEX 备注列须显式标注
            # 「源文件无实质内容/占位产物」；status 语义不变（仍为「成功」）。
            for name in ("blank.txt", "blank.csv"):
                self.assertRegex(rows[name]["note"],
                                 r"无实质内容|占位产物|placeholder",
                                 "%s 的 INDEX 备注缺少占位产物标注" % name)

    # ---- 12) 降级链：技能脚本加载失败 -> 内置回退转换器 ----------------------
    def test_13_skill_script_fallback(self):
        with tempfile.TemporaryDirectory(prefix="jinghe-qa-fallback-") as td:
            root = Path(td)
            outdir = root / "out"
            missing = root / "no_such_md_convert.py"  # 一定不存在的路径
            c = run_scenario(SAMPLES, outdir,
                             extra_args=("--skill-script", str(missing)))
            self.assertEqual(c["rc"], 0, "回退场景生成失败\n%s\n%s" % (c["stdout"], c["stderr"]))
            idx, log = c["index"], c["runlog"]
            self.assertIn("内置回退转换器", c["index_text"], "INDEX 未记录回退转换器")
            self.assertIn("内置回退转换器", c["runlog_text"], "run.log 未记录回退转换器")
            self.assertEqual(len(c["md_files"]), int(idx["succ"]))
            for art in c["md_files"]:
                self.assertGreater(art.stat().st_size, 0, "回退产物为空：%s" % art.name)
                self.assertIsNotNone(SOURCE_HEADER_RE.match(_read(art).splitlines()[0]),
                                     "回退产物缺少 source 头部：%s" % art.name)
            # 与技能脚本路径结构等价：件数对账数字一致、验收结论一致。
            # 不硬编码「通过」——#9 会往 samples/ 加入降级样例，届时两条路径的
            # 验收结论会同变为「部分未完成」，仍应保持一致。
            self.assertEqual(int(idx["cand"]), int(idx["succ"]) + int(idx["fail"]))
            main = self.c["index"]
            for key in ("total", "cand", "succ", "fail", "defer"):
                self.assertEqual(int(idx[key]), int(main[key]),
                                 "回退路径与技能脚本路径的 %s 不一致" % key)
            self.assertEqual(log["verdict"], self.c["runlog"]["verdict"],
                             "回退路径与技能脚本路径的验收结论不一致")

    # ---- 13) rich 降级：markitdown 缺失时不得静默出空文件 -------------------
    def test_14_rich_degradation(self):
        # 无文字层 PDF 占位。当前环境 markitdown 未安装 -> 「待安装依赖」；
        # 若已安装，假 PDF 也应落到「转换失败 / 需 OCR」等非成功状态。
        with tempfile.TemporaryDirectory(prefix="jinghe-qa-rich-") as td:
            indir, outdir = scenario_paths(td)
            (indir / "scan.pdf").write_bytes(b"%PDF-1.4\n% no-text-layer placeholder\n")
            (indir / "ok.txt").write_text("# 基准标题\n\n正文\n", encoding="utf-8")
            c = run_scenario(indir, outdir)
            self.assertEqual(c["rc"], 0, "rich 场景生成失败\n%s\n%s" % (c["stdout"], c["stderr"]))
            idx, log = c["index"], c["runlog"]
            rows = {r["src"].replace("\\", "/"): r for r in idx["rows"]}
            r = rows["scan.pdf"]
            self.assertNotEqual(r["status"], "成功", "无文字层 PDF 被判为成功")
            self.assertTrue(any(k in r["status"] for k in
                                ("待安装依赖", "OCR", "转换失败", "扫描件", "待人工")),
                            "降级状态文案异常：%s" % r["status"])
            self.assertIn(r["artifact"], ("", "-"), "降级文件竟产出了产物")
            self.assertFalse(any("scan" in a.stem.lower() for a in c["md_files"]))
            self.assertTrue([l for l in log["lines"] if l["src"] == "scan.pdf"],
                            "run.log 缺少 PDF 降级留痕")
            # 计入未成功 -> 验收「部分未完成」
            self.assertLess(int(idx["succ"]), int(idx["cand"]))
            self.assertIn("部分未完成", log["verdict"] or "")
            self.assertEqual(int(idx["cand"]), int(idx["succ"]) + int(idx["fail"]))

    # ---- 14) 原有 4 文件基线锚点 + 三项交付自检可重复性 ---------------------
    def test_15_baseline_four_samples(self):
        c, idx = self.c, self.c["index"]
        rows = {r["src"].replace("\\", "/"): r for r in idx["rows"]}
        # 基线锚点：4 个原有样例的状态与结构不得漂移
        base = {
            "chapter-01.txt":   ("成功", 1, 0),
            "glossary.csv":     ("成功", 1, 1),
            "notes.html":       ("成功", 1, 1),
            "future-audio.mp3": ("阶段 3 待支持", 0, 0),
        }
        for name, (status, hmin, rmin) in base.items():
            self.assertIn(name, rows, "基线样例 %s 缺失" % name)
            r = rows[name]
            self.assertEqual(r["status"], status, "基线样例 %s 状态漂移" % name)
            if status == "成功":
                self.assertGreaterEqual(int(r["heads"]), hmin, "%s 标题层级丢失" % name)
                self.assertGreaterEqual(int(r["rows"]), rmin, "%s 表格结构丢失" % name)
        # 三项交付自检在 INDEX.md 中显式、可重复
        for item in ("件数对账", "空文件扫描", "结构抽检"):
            self.assertIn(item, c["index_text"], "INDEX 缺少自检项：%s" % item)
        for item in ("候选:", "成功:", "未成功:", "空文件:", "无标题层级:", "验收:"):
            self.assertIn(item, c["runlog_text"], "run.log 缺少：%s" % item)
        self.assertEqual(int(idx["cand"]), int(idx["succ"]) + int(idx["fail"]))

    # ---- 22) 块级出处锚点 / 出处最小集（#9 第二批 17:16 转正）---------------
    def test_22_block_level_anchors(self):
        # 原 @expectedFailure 门禁；team-lead 于 2026-11-12 17:16 独立验收 #9
        # 第二批后转正。落实转正补强：块级锚点真实 doc_id、src 8 字段
        # （sha256 完整 64 位、anchors 非空、字段顺序与 ` | ` 分隔）、
        # provenance.json ↔ src 注释 ↔ MERGED 目录三者 doc_id 一致。
        c = self.c
        merged = c["merged_text"]
        ANCHOR_RE = re.compile(r"^<!--\s*anchor:\s*doc_[0-9a-f]{12}\s*\|")
        SRC_ANCHOR_RE = re.compile(r"^<!--\s*src:\s*doc_[0-9a-f]{12}\b")
        FIELDS = ["path", "format", "converter", "extracted",
                  "size", "sha256", "anchors"]

        # (1) MERGED / 单文件 md 块级锚点：doc_id 必须真实 12hex，数量一致
        merged_anchors = [ln.strip() for ln in merged.splitlines()
                          if "<!-- anchor:" in ln]
        self.assertTrue(merged_anchors, "MERGED.md 缺少块级锚点")
        md_anchors = []
        for md in c["md_files"]:
            for ln in _read(md).splitlines():
                if "<!-- anchor:" in ln:
                    md_anchors.append(ln.strip())
        self.assertEqual(len(md_anchors), len(merged_anchors),
                         "单文件 md 与 MERGED 的块级锚点数不一致")
        for ln in merged_anchors + md_anchors:
            self.assertRegex(ln, ANCHOR_RE,
                             "块级锚点 doc_id 非真实 12hex（字面 doc_id / 模板占位）：%s" % ln)

        # (2) 成功态 md 的第二行 src 注释：8 字段契约
        src_ids = []
        for md in c["md_files"]:
            lines = _read(md).splitlines()
            if len(lines) < 2 or not lines[1].startswith("<!-- src:"):
                continue
            s = lines[1]
            # ② 单条锚定正则：src: 后紧跟真实 doc_id，排除字面/尖括号占位
            self.assertRegex(s, SRC_ANCHOR_RE,
                             "src 注释 doc_id 非真实 12hex 或非紧跟：%s" % s)
            did = re.search(r"doc_[0-9a-f]{12}", s).group(0)
            src_ids.append(did)
            # 8 字段顺序 + ` | ` 分隔符
            self.assertEqual(re.findall(r"\|\s*([a-z0-9_]+):", s), FIELDS,
                             "src 注释 8 字段顺序/齐全性不符：%s" % s)
            self.assertEqual(len(re.findall(r"\s\|\s", s)), len(FIELDS),
                             "src 注释字段分隔符不是 ` | `：%s" % s)
            # ① sha256 完整 64 位小写 hex（明确不是 12 位）
            sha = re.search(r"sha256:\s*([0-9a-f]+)", s)
            self.assertIsNotNone(sha, "src 注释缺少 sha256：%s" % s)
            self.assertRegex(sha.group(1), r"^[0-9a-f]{64}$",
                             "sha256 不是完整 64 位小写 hex（疑似 12 位）：%s" % sha.group(1))
            self.assertEqual(did, "doc_" + sha.group(1)[:12],
                             "doc_id != sha256 前 12 位：%s" % s)
            # anchors 非空、非 none/占位（用 split，规避复杂正则）
            tail = s.split("anchors:", 1)[1].rstrip()
            if tail.endswith("-->"):
                tail = tail[:-3].rstrip()
            self.assertNotIn(tail.strip().lower(), ("", "none", "-"),
                             "src 注释 anchors 值为空/占位：%s" % s)
        self.assertEqual(len(src_ids), int(c["index"]["succ"]),
                         "带 src 注释的 md 数 != 成功记录数")

        # (3) ③ 跨文件一致性：manifest ↔ src ↔ MERGED 目录
        prov = json.loads(_read(c["outdir"] / "provenance.json"))
        prov_ids = {e["doc_id"] for e in prov["entries"]}
        merged_ids = set(re.findall(r'<a id="(doc_[0-9a-f]{12})"', merged))
        self.assertTrue(merged_ids, "MERGED 目录缺少 doc_id 锚点")
        self.assertEqual(set(src_ids), merged_ids,
                         "src 注释 doc_id 集合 != MERGED 目录 doc_id 集合")
        self.assertTrue(set(src_ids) <= prov_ids,
                        "src 注释存在 manifest 中没有的 doc_id")
        self.assertTrue(merged_ids <= prov_ids,
                        "MERGED 目录存在 manifest 中没有的 doc_id")
        anchor_ids = {re.search(r"doc_[0-9a-f]{12}", ln).group(0)
                      for ln in merged_anchors}
        self.assertTrue(anchor_ids <= prov_ids,
                        "块级锚点存在 manifest 中没有的 doc_id")

    def test_20_encrypted_document_degradation(self):
        # 归属 #9 富文档分支（原为 @expectedFailure 门禁，15:47 预检实现后转正）。
        # #9 第一批升级 fixture：不再用「假 docx / 无效容器」冒充加密，改为复用
        # samples/ 里 parser 生成的 5 类真加密字节，逐项证明 _probe_protection 命中
        # 「待人工授权」终态、不破译/不重试/不产出（FM-06）；另含 1 个无效容器，
        # 须落独立状态「转换失败：无效 OOXML/ZIP 容器」，验证 spec「不得与
        # 待人工授权混淆」。team-lead 已预告：无效容器文案改动会令旧断言变红。
        ENC = {
            "locked.pdf":      "PDF 已加密",
            "locked.zip":      "ZIP 成员已加密",
            "locked.docx":     "敏捷加密",
            "locked-ole.docx": "OLE 复合文档",
            "locked.epub":     "DRM",
        }
        with tempfile.TemporaryDirectory(prefix="jinghe-qa-enc-") as td:
            indir, outdir = scenario_paths(td)
            for name in list(ENC) + ["broken.docx"]:
                shutil.copy2(SAMPLES / name, indir / name)
            # 保证至少 1 个成功项，使 succ < cand 且验收为「部分未完成」
            (indir / "ok.txt").write_text("# 基准\n\n正文\n", encoding="utf-8")
            c = run_scenario(indir, outdir)
            self.assertEqual(c["rc"], 0,
                             "加密场景生成失败\n%s\n%s" % (c["stdout"], c["stderr"]))
            rows = {r["src"].replace("\\", "/"): r for r in c["index"]["rows"]}
            # (1) 5 类真加密：待人工授权终态 + 各自预检分支文案 + 无产物 + run.log 留痕
            for name, keyword in ENC.items():
                r = rows[name]
                self.assertTrue(r["status"].startswith("待人工授权"),
                                "%s 未命中「待人工授权」：%s" % (name, r["status"]))
                self.assertIn(keyword, r["status"],
                              "%s 未命中预检分支「%s」：%s" % (name, keyword, r["status"]))
                for wrong in ("转换失败", "需 OCR", "待安装依赖"):
                    self.assertNotIn(wrong, r["status"],
                                     "%s 的「待人工授权」被误写成 %s" % (name, wrong))
                self.assertIn(r["artifact"], ("", "-"),
                              "%s 加密文档被尝试破译并产出产物" % name)
                log_rec = [l for l in c["runlog"]["lines"] if l["src"] == name]
                self.assertTrue(log_rec and log_rec[0]["status"].startswith("待人工授权"),
                                "run.log 缺少 %s 的「待人工授权」留痕" % name)
            # (2) 无效容器：独立状态「转换失败」，不得冒充「待人工授权」
            brk = rows["broken.docx"]
            self.assertTrue(brk["status"].startswith("转换失败"),
                            "无效容器未用独立「转换失败」状态：%s" % brk["status"])
            self.assertIn("无效 OOXML/ZIP 容器", brk["status"])
            self.assertNotIn("待人工授权", brk["status"],
                             "无效容器被误标为「待人工授权」，违反 spec 不得混淆约束")
            self.assertIn(brk["artifact"], ("", "-"), "无效容器不应产出产物")
            # (3) 所有降级项都不产出 .md
            self.assertFalse(
                any(any(k in a.stem.lower() for k in ("locked", "broken"))
                    for a in c["md_files"]),
                "加密/无效容器样例被产出了 .md")
            # (4) 件数对账 + 计入未成功 + 验收「部分未完成」
            idx = c["index"]
            self.assertEqual(int(idx["cand"]), int(idx["succ"]) + int(idx["fail"]))
            self.assertEqual(int(idx["fail"]), len(ENC) + 1,
                             "降级项数量不等于 5 加密 + 1 无效容器")
            self.assertLess(int(idx["succ"]), int(idx["cand"]))
            self.assertIn("部分未完成", c["runlog"]["verdict"] or "")

    def test_21_six_format_real_extraction(self):
        # 归属 #9 第一批：6 个真实富文档样例（pdf/docx/pptx/xlsx/epub/zip）
        # 逐个断言「成功态 + 产物非空 + 首行 source 头 + 第二行 #9 出处注释 +
        # 结构化统计(chars/heads/rows) + 内容可回溯」。均基于主 context（完整 samples）。
        c, idx = self.c, self.c["index"]
        rows = {r["src"].replace("\\", "/"): r for r in idx["rows"]}
        # name -> (必须出现的内容片段, rows 下限)
        FORMATS = {
            "sample.pdf":  (["Chapter One", "text layer"], 0),
            "sample.docx": (["季度经营总结", "| 指标 |", "营收"], 1),
            "sample.pptx": (["Slide 1", "Slide 2", "Slide 3"], 0),
            "sample.xlsx": (["销售数据", "区域汇总", "| 月份 |"], 1),
            "sample.epub": (["Chapter 1", "Chapter 2", "OEBPS/ch1.xhtml"], 0),
            "sample.zip":  (["readme.txt", "notes.md", "nested.zip"], 0),
        }
        # #9 出处定位最小集：文件级 doc_id = "doc_" + sha256(字节)[:12]，
        # 以 < 起头另起一行，不污染以 | 开头的 stats 表格行。下方分字段断言，
        # 不锁死分隔符与空格，兼容 #9 第二批在 anchors: 后填入块级锚点。
        for name, (must, rmin) in FORMATS.items():
            self.assertIn(name, rows, "#9 样例 %s 缺失" % name)
            r = rows[name]
            self.assertEqual(r["status"], "成功", "%s 未成功提取" % name)
            self.assertGreater(int(r["chars"]), 0, "%s chars 为 0" % name)
            self.assertGreater(int(r["heads"]), 0, "%s 无标题层级" % name)
            self.assertGreaterEqual(int(r["rows"]), rmin, "%s 表格结构丢失" % name)
            art = c["outdir"] / r["artifact"]
            self.assertTrue(art.is_file() and art.stat().st_size > 0,
                            "%s 产物为空或不存在" % name)
            lines = _read(art).splitlines()
            # 首行 source 注释原样保留（test_05 契约不变）
            self.assertIsNotNone(SOURCE_HEADER_RE.match(lines[0]),
                                 "%s 首行缺少 source 头" % name)
            # 第二行 #9 出处注释（doc_id / path / anchors）
            src_line = lines[1]
            self.assertTrue(src_line.startswith("<!-- src: doc_"),
                            "%s 第二行不是 #9 出处注释（须以 < 起头、不污染表格行）" % name)
            self.assertRegex(src_line, r"doc_[0-9a-f]{12}",
                             "%s 出处注释缺少 12 位 hex doc_id" % name)
            for field in ("path:", "anchors:"):
                self.assertIn(field, src_line,
                              "%s 出处注释缺少字段 %s" % (name, field))
            self.assertTrue(src_line.rstrip().endswith("-->"),
                            "%s 出处注释未正确闭合" % name)
            body = "\n".join(lines)
            for frag in must:
                self.assertIn(frag, body, "%s 产物缺少可回溯内容：%s" % (name, frag))
        # 6 个降级/受保护样例在完整样例集里计入未成功、不产出 .md
        for name in ("locked.pdf", "locked.zip", "locked.docx",
                     "locked-ole.docx", "locked.epub", "broken.docx"):
            self.assertNotEqual(rows[name]["status"], "成功",
                                "%s 降级项被误记为成功" % name)
            self.assertIn(rows[name]["artifact"], ("", "-"),
                          "%s 降级项产出了 .md" % name)

    # ---- 24) 无有损编码（GBK 前置预处理层，#10 2026-11-12 17:58 转正）--------
    def test_24_no_lossy_encoding(self):
        # 原 test_gate_gbk_encoding（@expectedFailure）；team-lead 于 2026-11-12
        # 17:58 完成 #10「文本编码前置预处理层」后转正。锁定：GBK 无损解码
        # （U+FFFD=0、原文完整）、INDEX/run.log 留痕原编码与转换决策、
        # doc_id / sha256 一律基于原始文件字节（跑两次一致且等于 sha256(原始字节)）、
        # 前置层不改动源文件原始字节。
        text = "知识提取阶段一编码边界样例"
        raw = text.encode("gbk")
        expected_sha = hashlib.sha256(raw).hexdigest()
        with tempfile.TemporaryDirectory(prefix="jinghe-qa-enc2-") as td:
            root = Path(td)
            indir = root / "input"
            indir.mkdir()
            # 文件名刻意不含 gbk / gb18030 子串：否则 INDEX 明细行与表格里的
            # 文件名本身就会满足 assertIn("gbk", ...)，让「编码探测是否精确命中
            # gbk」这条断言被文件名污染而形同虚设（qa-verify 终验实证）。
            src = indir / "cp936-legacy.txt"
            src.write_bytes(raw)
            c1 = run_scenario(indir, root / "out1")
            self.assertEqual(c1["rc"], 0,
                             "GBK 场景生成失败\n%s\n%s" % (c1["stdout"], c1["stderr"]))
            self.assertEqual(len(c1["md_files"]), 1, "GBK 场景应产出 1 份 md")
            body = _read(c1["md_files"][0])
            # a) 无 U+FFFD、中文原文完整可回溯
            self.assertNotIn("\ufffd", body, "产物含 U+FFFD 替换字符（乱码）")
            self.assertIn(text, body, "GBK 中文未正确解码 / 原文丢失")
            lines = body.splitlines()
            self.assertIsNotNone(SOURCE_HEADER_RE.match(lines[0]),
                                 "GBK 产物缺少 source 头")
            self.assertTrue(lines[1].startswith("<!-- src: doc_"),
                            "GBK 产物缺少 src 注释")
            # b) INDEX / run.log 记录原编码(gbk)与转换决策(UTF-8 临时副本)
            #    断言按 label 分别锚定留痕字段，不用裸编码名 `assertIn("gbk", ...)`：
            #    后者会被文件名 / 汇总行满足，测不出「探测是否精确命中 gbk」。
            #    「严格解码命中 gbk」最锋利——若 gbk 从 _STRICT_CHAIN 移除而退化成
            #    gb18030，文案会变成「严格解码命中 gb18030」，不含本子串。
            for label, blob in (("INDEX", c1["index_text"]),
                                ("run.log", c1["runlog_text"])):
                self.assertIn("编码前置", blob, "%s 缺少编码前置层留痕" % label)
                self.assertIn("严格解码命中 gbk", blob,
                              "%s 未记录判定依据「严格解码命中 gbk」"
                              "（退化到 gb18030 / 用兜底编码即会触发）" % label)
                self.assertIn("UTF-8 临时副本", blob,
                              "%s 未记录「UTF-8 临时副本」决策" % label)
            # INDEX 明细字段名用全角冒号，run.log 用空格分隔，各自精确锚定
            self.assertIn("原编码：gbk", c1["index_text"],
                          "INDEX 明细未记录原编码 gbk（期望 `原编码：gbk`）")
            self.assertIn("原编码 gbk", c1["runlog_text"],
                          "run.log 未记录原编码 gbk（期望 `原编码 gbk`）")
            # c) 跑两次 doc_id / sha256 一致，且 == sha256(原始字节)
            sha1 = re.search(r"sha256:\s*([0-9a-f]{64})", lines[1]).group(1)
            doc1 = re.search(r"doc_[0-9a-f]{12}", lines[1]).group(0)
            self.assertEqual(sha1, expected_sha,
                             "src sha256 != sha256(原始字节)，疑似用临时副本算哈希")
            self.assertEqual(doc1, "doc_" + expected_sha[:12],
                             "doc_id != doc_ + sha256(原始字节)[:12]")
            c2 = run_scenario(indir, root / "out2")
            self.assertEqual(c2["rc"], 0, "GBK 第二次运行失败")
            l2 = _read(c2["md_files"][0]).splitlines()
            sha2 = re.search(r"sha256:\s*([0-9a-f]{64})", l2[1]).group(1)
            doc2 = re.search(r"doc_[0-9a-f]{12}", l2[1]).group(0)
            self.assertEqual(doc1, doc2,
                             "两次运行 doc_id 不一致（疑似基于临时副本算哈希）")
            self.assertEqual(sha1, sha2, "两次运行 sha256 不一致")
            # d) 前置层不改动源文件原始字节
            self.assertEqual(src.read_bytes(), raw, "前置层修改了原始文件字节")

    # ---- 25) BOM 去除（utf-8-sig 输入，#10 前置层边界）---------------------
    def test_25_bom_strip(self):
        # #10 前置层边界：utf-8-sig（带 BOM）输入应正确去 BOM，产物不含 U+FEFF，
        # 且 INDEX 明细记录原编码 utf-8-sig 与「UTF-8 临时副本」决策。
        text = "BOM 编码边界样例正文"
        with tempfile.TemporaryDirectory(prefix="jinghe-qa-bom-") as td:
            root = Path(td)
            indir = root / "input"
            indir.mkdir()
            (indir / "bom.txt").write_bytes(
                bytes([0xef, 0xbb, 0xbf]) + text.encode("utf-8"))
            c = run_scenario(indir, root / "out")
            self.assertEqual(c["rc"], 0,
                             "BOM 场景生成失败\n%s\n%s" % (c["stdout"], c["stderr"]))
            self.assertEqual(len(c["md_files"]), 1, "BOM 场景应产出 1 份 md")
            body = _read(c["md_files"][0])
            self.assertNotIn("\ufeff", body, "产物残留 BOM（U+FEFF）")
            self.assertIn(text, body, "BOM 文件正文丢失")
            self.assertIn("utf-8-sig", c["index_text"],
                          "INDEX 明细未记录原编码 utf-8-sig")
            self.assertIn("UTF-8 临时副本", c["index_text"],
                          "INDEX 未记录「UTF-8 临时副本」决策")

            # ---- 前置层单元级断言 -------------------------------------------
            # 产物正文那条 assertNotIn("\ufeff") 是弱断言：normalize_markdown 本身
            # 就 replace("\ufeff","")，所以即使前置层生成的副本带 BOM 也能过
            # （qa-verify 变异 M-a 实证漏检）。真正的锁在这里：直接调前置层，
            # 检查「副本必须同名 / 副本必须无 BOM / 副本正文正确 / UTF-8 零复制」。
            sys.path.insert(0, str(EXTRACT.parent))
            import extract as EX  # noqa: E402  （被测系统，只在临时目录里跑）

            workdir = root / "encwork"
            bom_src = root / "input" / "bom-exact.txt"
            bom_src.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
            feed, info = EX.preprocess_text_encoding(bom_src, workdir, 1)
            self.assertEqual(info["encoding"], "utf-8-sig",
                             "BOM 输入未被识别为 utf-8-sig（实得 %s）"
                             % info["encoding"])
            self.assertTrue(info["converted"],
                            "utf-8-sig 输入应生成 UTF-8 临时副本（BOM 须剥离）")
            self.assertEqual(feed.name, bom_src.name,
                             "临时副本必须与源文件同名，实得 %s != %s"
                             "（改名会让 MERGED 去重标题失配）"
                             % (feed.name, bom_src.name))
            self.assertFalse(
                feed.read_bytes().startswith(b"\xef\xbb\xbf"),
                "临时副本仍带 BOM，转换器会读到 U+FEFF")
            self.assertEqual(feed.read_text(encoding="utf-8"), text,
                             "临时副本正文与原文不一致")
            self.assertEqual(bom_src.read_bytes(),
                             b"\xef\xbb\xbf" + text.encode("utf-8"),
                             "前置层改动了源文件原始字节")

            # 纯 UTF-8 无 BOM：必须原路径直用、零复制（不产生无谓临时文件）
            plain = root / "input" / "plain-utf8.txt"
            plain.write_bytes(text.encode("utf-8"))
            feed2, info2 = EX.preprocess_text_encoding(plain, workdir, 2)
            self.assertEqual(info2["encoding"], "utf-8",
                             "纯 UTF-8 应判为 utf-8，实得 %s" % info2["encoding"])
            self.assertFalse(info2["converted"],
                             "纯 UTF-8 不应生成副本（应零复制）")
            self.assertEqual(feed2, plain, "纯 UTF-8 应原路径直用")

    # ---- 26) CID/Identity-H 字体按 /ToUnicode 还原（#11 2026-11-13）---------
    def test_26_cid_identity_h_tounicode(self):
        # 真实文件复现的 bug：WPS 导出的中文 PDF 用 /Type0 + /Identity-H，
        # 内容流里的 <...> 是 2 字节 GID。旧实现把它当 utf-8/gb18030/latin-1
        # 去猜，解出乱码还报「成功」。此处用自包含的最小 PDF 锁住三条：
        # ① GID 必须按 ToUnicode 还原成中文；② bfchar/bfrange 两种 CMap 形式
        # 都要解析（含数组形式与多字符目标）；③ 能还原时必须仍判「成功」。
        sys.path.insert(0, str(EXTRACT.parent))
        import extract as EX  # noqa: E402  （只读调用被测模块）

        pairs = {1: "精", 2: "核", 3: "提", 4: "取", 5: "公", 6: "告"}
        raw = _cid_pdf_bytes(pairs, [1, 2, 3, 4, 5, 6])
        with tempfile.TemporaryDirectory(prefix="jinghe-cid-") as td:
            pdf = Path(td) / "cid.pdf"
            pdf.write_bytes(raw)
            has_layer, text = EX._pdf_extract(pdf)
            self.assertTrue(has_layer, "CID PDF 未识别出文字层")
            self.assertIn("精核提取公告", text,
                          "Identity-H 字形号未被 ToUnicode 还原，实得：%r" % text)
            self.assertNotIn("\ufffd", text, "CID 还原结果含替换字符")
            md, status = EX._builtin_rich_extract(pdf)
            self.assertEqual(status, "成功",
                             "可还原的 CID PDF 被误判降级：%s" % status)
            self.assertIn("精核提取公告", md or "",
                          "内置解析产物丢失 CID 正文")

        # CMap 解析器单测：覆盖 bfchar、bfrange 递增、bfrange 数组、
        # 以及「目标为多字符（连字）」的情况。
        cmap_text = (
            "begincmap\n"
            "1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n"
            "2 beginbfchar\n<0001> <7CBE>\n<0002> <00660069>\nendbfchar\n"
            "2 beginbfrange\n<0010> <0012> <4E00>\n"
            "<0020> <0021> [<516C> <544A>]\nendbfrange\n"
            "endcmap\n")
        cmap = EX._parse_bf_cmap(cmap_text)
        self.assertEqual(cmap.get(0x0001), "精", "bfchar 单字映射错误")
        self.assertEqual(cmap.get(0x0002), "fi", "bfchar 多字符（连字）映射错误")
        self.assertEqual(cmap.get(0x0011), "丁", "bfrange 递增形式映射错误")
        self.assertEqual(cmap.get(0x0020), "公", "bfrange 数组形式映射错误")
        self.assertEqual(cmap.get(0x0021), "告", "bfrange 数组形式映射错误")

    # ---- 27) ToUnicode 缺失必须诚实降级，不得假成功（#11 2026-11-13）-------
    def test_27_cid_without_tounicode_degrades(self):
        # 同上是 CID 字体但【没有】/ToUnicode：GID 无法还原，旧逻辑会把
        # \x00\x01… 这类字节当编码猜出一堆控制字符/乱码并报成功。
        # 质量门禁（len>=40 且合理字符占比 <0.6）必须拦下并给出专用解析器文案。
        sys.path.insert(0, str(EXTRACT.parent))
        import extract as EX  # noqa: E402

        pairs = {1: "精", 2: "核", 3: "提", 4: "取", 5: "公", 6: "告"}
        codes = [1, 2, 3, 4, 5, 6] * 10  # 60 个 GID -> 120 字节，足够触发门禁
        raw = _cid_pdf_bytes(pairs, codes, with_tounicode=False)
        with tempfile.TemporaryDirectory(prefix="jinghe-cid-nomap-") as td:
            pdf = Path(td) / "cid-nomap.pdf"
            pdf.write_bytes(raw)
            has_layer, text = EX._pdf_extract(pdf)
            self.assertTrue(has_layer, "无 ToUnicode 的 CID PDF 未识别出文字层")
            self.assertGreaterEqual(len(text), 40, "夹具正文太短，无法验证质量门禁")
            md, status = EX._builtin_rich_extract(pdf)
            self.assertIsNone(md, "解码失败的 PDF 仍返回了产物（假成功）")
            self.assertTrue(status.startswith("需专用解析器"),
                            "解码失败未落到「需专用解析器」，实得：%s" % status)
            self.assertNotEqual(status, "成功", "乱码被记为成功")

    def test_28_streaming_encoding_equivalence(self):
        # v0.3.4 优化：编码前置层改为「流式判编码、utf-8 零读全文」。
        # 判定逻辑必须与历史实现逐字等价——这是本用例存在的全部理由：
        # 优化的是内存占用，不能动编码判定与产物内容。
        sys.path.insert(0, str(EXTRACT.parent))
        import extract as EX  # noqa: E402

        cn = "中文内容测试ABC\n第二行\n"
        samples = [
            ("utf8", cn.encode("utf-8")),
            ("utf8-bom", b"\xef\xbb\xbf" + cn.encode("utf-8")),
            ("utf16le-bom", b"\xff\xfe" + cn.encode("utf-16-le")),
            ("utf16be-bom", b"\xfe\xff" + cn.encode("utf-16-be")),
            ("utf32le-bom", b"\xff\xfe\x00\x00" + cn.encode("utf-32-le")),
            ("gbk", cn.encode("gbk")),
            ("gb18030", ("中文汉字€").encode("gb18030")),
            ("big5", ("繁體中文測試").encode("big5")),
            ("latin1-junk", b"\x81\x82\x83\xfe\xff\x00binary"),
            ("empty", b""),
        ]

        def legacy_preprocess(path, workdir, slot):
            """历史实现：整块读 + decode_text_bytes（对拍基准）。"""
            data = path.read_bytes()
            text, enc, why = EX.decode_text_bytes(data)
            info = {"encoding": enc, "basis": why, "bytes": len(data),
                    "converted": False, "feed": path}
            if enc == "utf-8" or workdir is None:
                return path, info
            slot_dir = workdir / ("%04d" % slot)
            slot_dir.mkdir(parents=True, exist_ok=True)
            feed = slot_dir / path.name
            feed.write_text(text, encoding="utf-8")
            info.update(converted=True, feed=feed)
            return feed, info

        with tempfile.TemporaryDirectory(prefix="jinghe-enc-stream-") as td:
            root = Path(td)
            for name, data in samples:
                src = root / (name + ".txt")
                src.write_bytes(data)
                # ① 判定等价：编码名、判定依据、字节数三项都要一致
                old = EX.decode_text_bytes(src.read_bytes())
                new = EX.detect_encoding_of_file(src)
                self.assertEqual(new[0], old[1],
                                 "%s：流式判定编码名与历史实现不一致" % name)
                self.assertEqual(new[1], old[2],
                                 "%s：流式判定依据与历史实现不一致" % name)
                self.assertEqual(new[2], len(data),
                                 "%s：流式统计字节数与实际不符" % name)
                # ② 产物等价：dry-run（不落副本）与落副本两种模式都要逐字节一致
                for wd in (None, root / ("wd_" + name)):
                    o_feed, o_info = legacy_preprocess(src, wd, 0)
                    n_feed, n_info = EX.preprocess_text_encoding(src, wd, 0)
                    self.assertEqual(
                        {k: v for k, v in o_info.items() if k != "feed"},
                        {k: v for k, v in n_info.items() if k != "feed"},
                        "%s：前置层留痕信息与历史实现不一致" % name)
                    if o_feed.is_file():
                        self.assertEqual(o_feed.read_bytes(), n_feed.read_bytes(),
                                         "%s：UTF-8 副本内容与历史实现不一致" % name)

            # ③ 流式字节搜索：跨 1MB 块边界的 /Encrypt 不能漏检
            big = root / "big.bin"
            big.write_bytes(b"x" * (1 << 20) + b"/Encrypt" + b"y" * 32)
            self.assertTrue(EX._file_contains(big, b"/Encrypt"),
                            "跨块边界的 /Encrypt 被漏检（会漏判加密 PDF）")
            self.assertFalse(EX._file_contains(big, b"/EncryptX"),
                             "流式字节搜索出现误命中")

    def test_17_artifact_dir_reconciliation(self):
        # spec 规格条款「产物目录实盘对账」：① 写入前清空/重建 outdir/md/；
        # ② 交付前自检的件数对账须含第三项 md/*.md 实盘数 == 成功记录数（双向核对）；
        # ③ 不一致时判「部分未完成」并列出孤立/缺失产物；④ 严禁残留旧 .md 作为
        # 「幽灵来源」污染 provenance manifest。
        # 原为 @expectedFailure 门禁；parser 于 15:37 在 extract.py:326-330 / 390-396
        # 落实「清理 stale_artifacts + 实盘对账 + 验收纳入 disk_ok」后转正为正式断言。
        with tempfile.TemporaryDirectory(prefix="jinghe-qa-gate-rerun-") as td:
            root = Path(td)
            outdir = root / "out"
            # 用固定的纯文本样例集，不复制 samples/ 全量——#9 会新增富文档 /
            # 降级样例，若全量复制会引入未成功项、改变验收结论，干扰本用例。
            first_names = ("chapter-01.txt", "glossary.csv", "notes.html",
                           "future-audio.mp3")
            second_names = ("chapter-01.txt", "edge-structures.md", "empty.txt",
                            "glossary.csv", "no-heading.md", "notes.html",
                            "future-audio.mp3")
            first = root / "input1"
            first.mkdir()
            for name in first_names:
                shutil.copy2(SAMPLES / name, first / name)
            c1 = run_scenario(first, outdir)
            self.assertEqual(c1["rc"], 0)
            first_arts = {p.name for p in (outdir / "md").glob("*.md")}
            second = root / "input2"
            second.mkdir()
            for name in second_names:
                shutil.copy2(SAMPLES / name, second / name)
            c2 = run_scenario(second, outdir)
            self.assertEqual(c2["rc"], 0)
            second_arts = {p.name for p in (outdir / "md").glob("*.md")}
            expected_arts = {Path(r["artifact"]).name
                             for r in c2["index"]["rows"] if r["status"] == "成功"}
            n_art = len(second_arts)
            self.assertEqual(n_art, int(c2["index"]["succ"]),
                             "重跑后 md/ 残留 %d 个孤儿文件（成功数 %s）"
                             % (n_art - int(c2["index"]["succ"]), c2["index"]["succ"]))
            # 通用双向核对：磁盘产物集合 == 本轮成功记录集合（spec 实盘对账②）
            self.assertEqual(second_arts, expected_arts,
                             "产物目录与本轮成功记录不一致：多 %s / 少 %s"
                             % (sorted(second_arts - expected_arts),
                                sorted(expected_arts - second_arts)))
            # 显式断言不存在过期孤儿（两轮编号漂移后第一轮旧文件名不应残留）
            stale = (first_arts - expected_arts) & second_arts
            self.assertFalse(stale, "重跑后仍残留过期孤儿产物：%s" % sorted(stale))
            # 规格②：INDEX 交付前自检含实盘对账第三项且结论为「一致」
            self.assertIn("产物目录实盘对账", c2["index_text"],
                          "INDEX 缺少产物目录实盘对账自检项")
            self.assertRegex(c2["index_text"], r"产物目录实盘对账[^\n]*（一致）",
                             "INDEX 实盘对账结论不是「一致」")
            # run.log 两行留痕：「清理陈旧产物」与「实盘对账」
            self.assertIn("清理陈旧产物", c2["runlog_text"],
                          "run.log 缺少「清理陈旧产物」留痕")
            self.assertIn("实盘对账", c2["runlog_text"],
                          "run.log 缺少「实盘对账」留痕")
            # 规格③：实盘一致时验收仍「通过」（固定输入保证全部成功）
            self.assertEqual(c2["runlog"]["verdict"], "通过",
                             "实盘一致却判为部分未完成")

    def test_16_placeholder_note_in_index(self):
        # 规格澄清1 增强②：占位产物在 INDEX 备注列应标注
        # 「源文件无实质内容/占位产物」及建议 content_status=placeholder。
        # 原为 @expectedFailure 门禁；parser 于 15:37 在 extract.py:368-369 落实后转正。
        with tempfile.TemporaryDirectory(prefix="jinghe-qa-note-") as td:
            indir, outdir = scenario_paths(td)
            (indir / "blank.csv").write_bytes(b"")
            (indir / "ok.txt").write_text("# 基准标题\n\n正文\n", encoding="utf-8")
            c = run_scenario(indir, outdir)
            self.assertEqual(c["rc"], 0)
            rows = {r["src"].replace("\\", "/"): r for r in c["index"]["rows"]}
            self.assertRegex(rows["blank.csv"]["note"],
                             r"无实质内容|占位产物|placeholder|content_status",
                             "INDEX 备注未标注占位产物（源文件无实质内容）")

    # ---- 23) 阶段 2 摘要排除清单（#9 第二批 17:16 转正）---------------------
    def test_23_placeholder_exclusion_list(self):
        # 原 @expectedFailure 门禁；team-lead 于 2026-11-12 17:16 独立验收 #9
        # 第二批后转正。落实转正补强：排除清单逐条用真实 doc_id、以 `- `
        # 起头（不污染 parse_index rows）、与 provenance.json 中
        # content_status != normal 的条目双向对得上、MERGED 同步标注。
        c = self.c
        prov = json.loads(_read(c["outdir"] / "provenance.json"))
        abnormal = {e["doc_id"]: e for e in prov["entries"]
                    if e.get("content_status", "normal") != "normal"}
        self.assertTrue(abnormal, "manifest 中没有任何 content_status != normal 的条目")
        # INDEX 排除清单段落（用行定位，规避复杂正则）
        lines = c["index_text"].splitlines()
        start = next((i for i, ln in enumerate(lines)
                      if "摘要排除清单" in ln and ln.lstrip().startswith("##")), None)
        self.assertIsNotNone(start, "INDEX.md 缺少「阶段 2 摘要排除清单」段落")
        end = next((i for i in range(start + 1, len(lines))
                    if lines[i].startswith("## ")), len(lines))
        bullets = [ln for ln in lines[start + 1:end] if ln.startswith("- ")]
        self.assertEqual(len(bullets), len(abnormal),
                         "排除清单条数 != manifest 中 content_status!=normal 条数")
        listed = set()
        for ln in bullets:
            # 逐条用真实 doc_id、以 - 起头（不以 | 起头，不污染 rows）
            self.assertRegex(ln, r"doc_[0-9a-f]{12}",
                             "排除清单条目 doc_id 非真实 12hex：%s" % ln)
            did = re.search(r"doc_[0-9a-f]{12}", ln).group(0)
            listed.add(did)
            self.assertRegex(ln, r"placeholder|unavailable",
                             "排除清单条目缺少 content_status 原因：%s" % ln)
        # ④ 双向一致：清单集合 == manifest 异常集合
        self.assertEqual(listed, set(abnormal),
                         "排除清单 doc_id 集合与 manifest 中 content_status!=normal 不一致")
        # MERGED 同步标注（至少含这些 doc_id 之一）
        self.assertTrue(any(did in c["merged_text"] for did in listed),
                        "MERGED 未同步标注排除清单 doc_id")

    def test_18_text_log_conversion(self):
        # #10 提及的 .text/.log 格式：实测技能脚本 CONVERTERS（md_convert.py:216-219）
        # 与内置回退转换器（extract.py:170-171）均覆盖这两个扩展名，
        # 两条转换路径都应成功产出非空 md。作为该格式的正式回归锚点。
        # 注：#10 描述的「技能脚本未覆盖 .text/.log 导致无可用转换器」
        # 在当前环境不可复现（详见给 team-lead 的回报），故不设为门禁。
        with tempfile.TemporaryDirectory(prefix="jinghe-qa-textlog-") as td:
            indir, _ = scenario_paths(td)
            (indir / "memo.text").write_text("# 备忘录\n\n正文内容\n", encoding="utf-8")
            (indir / "run.log").write_text("# 运行记录\n\n正文内容\n", encoding="utf-8")
            for label, extra in (
                ("skill", ()),
                ("fallback", ("--skill-script", str(Path(td) / "missing_md_convert.py"))),
            ):
                out = Path(td) / ("out_" + label)
                c = run_scenario(indir, out, extra_args=extra)
                self.assertEqual(c["rc"], 0, "%s 路径生成失败" % label)
                rows = {r["src"].replace("\\", "/"): r for r in c["index"]["rows"]}
                for name in ("memo.text", "run.log"):
                    self.assertEqual(rows[name]["status"], "成功",
                                     "%s 在 %s 路径下被记为「%s」"
                                     % (name, label, rows[name]["status"]))
                    art = out / rows[name]["artifact"]
                    self.assertTrue(art.is_file() and art.stat().st_size > 0,
                                    "%s 在 %s 路径下产物为空" % (name, label))
                    self.assertIsNotNone(SOURCE_HEADER_RE.match(_read(art).splitlines()[0]),
                                         "%s 在 %s 路径下缺少 source 头" % (name, label))

    def test_19_partial_converter_fallback(self):
        # 归属 #10：技能脚本存在但 CONVERTERS 缺某个扩展名（此处故意缺 .csv）时，
        # 应「只补齐该扩展名到内置同名转换器、其余仍走技能脚本」，
        # 产物非空且件数对账与完整技能脚本路径一致。
        # 团队指令原拟以 @expectedFailure 门禁留痕（前提是 extract.py 未实现）；
        # 但 extract.py:185-197 的 load_converters 已用 conv.setdefault(e, fn)
        # 实现该补齐，门禁会变成 unexpected success 让套件变红，故转正为正式断言。
        # 若未来该补齐被回退，本用例会立刻变红，等价于门禁效果。
        with tempfile.TemporaryDirectory(prefix="jinghe-qa-partial-") as td:
            root = Path(td)
            fake = root / "partial_md_convert.py"
            fake.write_text(
                'from pathlib import Path\n'
                'def _conv(p):\n'
                '    return "# " + Path(p).name + (chr(10) * 2) + '
                'Path(p).read_text(encoding="utf-8", errors="replace") + chr(10)\n'
                'CONVERTERS = {".txt": _conv, ".text": _conv, ".log": _conv, '
                '".html": _conv, ".htm": _conv}\n',  # 故意不含 .csv
                encoding="utf-8",
            )
            indir, _ = scenario_paths(td)
            shutil.copy2(SAMPLES / "chapter-01.txt", indir / "chapter-01.txt")
            shutil.copy2(SAMPLES / "glossary.csv", indir / "glossary.csv")

            base = run_scenario(indir, root / "out_base")  # 完整技能脚本作基准
            part = run_scenario(indir, root / "out_part",
                                extra_args=("--skill-script", str(fake)))
            self.assertEqual(part["rc"], 0,
                             "补齐场景生成失败\n%s\n%s" % (part["stdout"], part["stderr"]))
            rows = {r["src"].replace("\\", "/"): r for r in part["index"]["rows"]}
            # 缺 .csv 的技能脚本仍应把 .csv 补齐为内置同名转换器并成功
            self.assertEqual(rows["glossary.csv"]["status"], "成功",
                             "技能脚本缺 .csv 时未回退内置同名转换器")
            art = root / "out_part" / rows["glossary.csv"]["artifact"]
            self.assertTrue(art.is_file() and art.stat().st_size > 0,
                            ".csv 补齐后的产物为空")
            self.assertIsNotNone(SOURCE_HEADER_RE.match(_read(art).splitlines()[0]),
                                 ".csv 补齐后的产物缺少 source 头")
            # 其余扩展名仍走技能脚本：来源应标注技能脚本，而非整体回退内置
            self.assertIn("技能脚本", part["index_text"],
                          "补齐后错误地整体回退为内置转换器")
            self.assertNotIn("内置回退转换器", part["index_text"])
            # 产物数字与完整技能脚本路径一致
            for key in ("total", "cand", "succ", "fail"):
                self.assertEqual(int(part["index"][key]), int(base["index"][key]),
                                 "%s 与完整技能脚本路径不一致" % key)
            self.assertEqual(part["runlog"]["verdict"], "通过")


def print_summary(c: dict, result=None) -> None:
    """末尾打印样例集与产物的具体数字，便于交付留痕。"""
    print("\n=== 样例集 / 产物数字摘要 ===")
    if not c["index"] or not c["runlog"]:
        print("生成失败，无法统计。rc=%s\nstdout:\n%s\nstderr:\n%s"
              % (c["rc"], c["stdout"], c["stderr"]))
        return
    idx, log = c["index"], c["runlog"]
    conv_source = re.search(r"(?m)^-\s*转换器：(.+)$", c["index_text"])
    print("样例文件总数        : %d" % len(c["samples"]))
    print("源文件总数(INDEX)   : %s" % idx["total"])
    print("候选/纳入转换       : %s / %s" % (idx["cand"], idx["conv"]))
    print("成功产出            : %s" % idx["succ"])
    print("未成功              : %s" % idx["fail"])
    print("阶段3预留(音视频)   : %s" % idx["defer"])
    print("需预处理 / 不支持   : %s / %s" % (idx["legacy"], idx["unsup"]))
    print("out/md 产物数       : %d" % len(c["md_files"]))
    print("空文件(run.log)     : %s" % log["nums"]["空文件"])
    print("无标题层级(run.log) : %s" % log["nums"]["无标题层级"])
    print("验收结论            : %s" % log["verdict"])
    print("转换器              : %s" % (conv_source.group(1) if conv_source else "-"))
    print("INDEX 空文件扫描    : %s" % idx["empty_line"])
    print("INDEX 结构抽检      : %s" % idx["struct_line"])
    print("--------------------------------")
    if result is not None:
        passed = (result.testsRun - len(result.failures) - len(result.errors)
                  - len(result.expectedFailures) - len(result.skipped)
                  - len(result.unexpectedSuccesses))
        print("断言用例总数        : %d" % result.testsRun)
        print("正式通过            : %d" % passed)
        print("失败 / 错误         : %d / %d" % (len(result.failures), len(result.errors)))
        print("预期失败门禁        : %d（@expectedFailure 用例数）"
              % len(result.expectedFailures))
        print("意外成功(需转正)    : %d" % len(result.unexpectedSuccesses))
    print("==============================")


if __name__ == "__main__":
    result = unittest.main(verbosity=2, exit=False).result
    print_summary(get_ctx(), result)
    sys.exit(0 if result.wasSuccessful() else 1)
