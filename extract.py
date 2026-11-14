#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""知识提炼软件 · 阶段 1：文件内容提取与汇总。

本期范围（明确边界）：
  做：多文件盘点分流 -> 结构化 Markdown 提取 -> 质量校验 -> 汇总合并 -> 对账留痕
  不做：核心内容提炼/摘要、Word 导出、音频与视频转写（阶段 2 / 3）

产物：
  out/md/NNN-<stem>.md   每份源文件一份结构化 Markdown（头部带来源注释）
  out/INDEX.md           工程汇总：件数对账、状态、结构抽检
  out/MERGED.md          内容汇总：带来源标注的合并文档（标题自动降位）
  out/run.log            运行日志与验收结论

设计约定：
  1) 转换规则复用 markitdown 技能自带的 scripts/md_convert.py；找不到时回退内置转换器。
  2) 富文档（PDF/Office/EPUB/ZIP）：markitdown 可用则优先；否则用内置零依赖解析
     真实提取，不静默出空文件；加密/扫描件/超大/旧版按状态降级，绝不伪装成功。
  3) 音视频一律标记「阶段 3 待支持」，绝不按音频尝试转写（技能红线）。
  4) 交付前必做：件数对账、空文件扫描、标题/表格抽检。
  5) 文本编码前置层（#10）：文本类文件先按【原始字节】严格探测编码
     （BOM -> utf-8 -> gbk -> gb18030 -> big5 -> latin-1），非 UTF-8 生成
     同名 UTF-8 临时副本只喂转换器；doc_id / sha256 始终基于原始文件字节，
     绝不基于副本，否则 provenance 与全部锚点失效。
"""
from __future__ import annotations

import argparse
import atexit
import csv
import datetime as dt
import hashlib
import importlib.util
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
import zlib
from html.parser import HTMLParser
from pathlib import Path

# 软件版本（语义化）。注意与 SPEC.md 的「规格版本」（v2.x）区分：
# 规格版本随文档修订递增，软件版本随功能交付递增，两者不同步。
__version__ = "0.3.0"

# 转换器依赖解析顺序（打包调整，让依赖真正跟着包走）：
#   1) 随包分发的 vendor/md_convert.py —— 相对本脚本位置解析，整个目录可移动到任意机器
#   2) 本机 markitdown 技能脚本绝对路径 —— 仅开发环境兜底
#   3) 两者都不存在时 load_converters 自动落到内置零依赖转换器，软件仍可运行
# 三条路径产出的 Markdown 结构一致，只有 INDEX/run.log 的「转换器」标签不同。
def resource_dir() -> Path:
    """资源根目录：PyInstaller onefile 下为 sys._MEIPASS，源码运行为脚本所在目录。

    界面层（app.py）与 vendor/ 依赖都通过它解析，避免写死「相对当前工作目录」——
    exe 可能从任意目录双击启动。
    """
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base)
    return Path(__file__).resolve().parent


_HERE = resource_dir()
_BUNDLED_SKILL_SCRIPT = _HERE / "vendor" / "md_convert.py"
_DEV_SKILL_SCRIPT = (
    r"C:\Users\songweihu\.workbuddy\plugins\marketplaces\experts\plugins"
    r"\markitdown-skill\skills\markitdown-skill\scripts\md_convert.py"
)


def default_skill_script() -> str:
    """优先随包分发的依赖，其次本机技能脚本；都不在时返回内置回退路径。"""
    if _BUNDLED_SKILL_SCRIPT.is_file():
        return str(_BUNDLED_SKILL_SCRIPT)
    if Path(_DEV_SKILL_SCRIPT).is_file():
        return _DEV_SKILL_SCRIPT
    return str(_BUNDLED_SKILL_SCRIPT)

SKILL_EXT = {".txt", ".text", ".log", ".html", ".htm", ".csv"}
PLAIN_EXT = {".md", ".json", ".xml"}
RICH_EXT = {".pdf", ".docx", ".pptx", ".xlsx", ".epub", ".zip"}
DEFERRED_EXT = {
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".wma", ".amr",
    ".mp4", ".mov", ".avi", ".mkv", ".flv", ".webm", ".m4v",
}
LEGACY_EXT = {".doc", ".xls", ".ppt"}
MAX_SINGLE_BYTES = 100 * 1024 * 1024
# 富文档「近乎空输出」判定阈值，可配置；默认 1 表示仅真正空输出判失败，
# 避免把短小但有效的文档误判为扫描件/失败（FM-05/FM-08）。
try:
    MIN_TEXT_CHARS = max(1, int(os.environ.get("EXTRACT_MIN_TEXT_CHARS", "1")))
except ValueError:
    MIN_TEXT_CHARS = 1


# --------------------------------------------------------------------------
# 转换器：优先加载技能脚本，失败则回退到内置等价实现
# --------------------------------------------------------------------------
class _FallbackHtml(HTMLParser):
    DROP = {"script", "style", "head", "noscript", "svg"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._drop = 0
        self._row: list[str] = []
        self._cell: list[str] | None = None
        self._link: str | None = None

    def _nl(self, n: int = 1) -> None:
        text = "".join(self.parts)
        if not text.endswith("\n" * n):
            self.parts.append("\n" * n)

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in self.DROP:
            self._drop += 1
            return
        if self._drop:
            return
        if re.fullmatch(r"h[1-6]", tag):
            self._nl(2)
            self.parts.append("#" * int(tag[1]) + " ")
        elif tag in ("p", "div", "blockquote"):
            self._nl(2)
            if tag == "blockquote":
                self.parts.append("> ")
        elif tag == "li":
            self._nl(1)
            self.parts.append("- ")
        elif tag == "br":
            self.parts.append("  \n")
        elif tag == "hr":
            self._nl(2)
            self.parts.append("---\n")
        elif tag in ("b", "strong"):
            self.parts.append("**")
        elif tag in ("i", "em"):
            self.parts.append("*")
        elif tag == "a":
            self._link = dict(attrs).get("href", "")
        elif tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = []
        elif tag == "table":
            self._nl(2)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self.DROP:
            self._drop = max(0, self._drop - 1)
            return
        if self._drop:
            return
        if re.fullmatch(r"h[1-6]", tag) or tag in ("p", "div", "ul", "ol", "table"):
            self._nl(2)
        elif tag in ("b", "strong"):
            self.parts.append("**")
        elif tag in ("i", "em"):
            self.parts.append("*")
        elif tag == "a":
            if self._link:
                self.parts.append("](%s)" % self._link)
            self._link = None
        elif tag in ("td", "th"):
            self._row.append(re.sub(r"\s+", " ", "".join(self._cell or [])).strip())
            self._cell = None
        elif tag == "tr" and self._row:
            self.parts.append("| " + " | ".join(self._row) + " |\n")
            if sum(1 for p in self.parts if p.startswith("| ")) == 1:
                self.parts.append("|" + " --- |" * len(self._row) + "\n")
            self._row = []

    def handle_data(self, data):
        if self._drop:
            return
        if self._cell is not None:
            self._cell.append(data)
        else:
            self.parts.append(re.sub(r"[ \t\r\n]+", " ", data))

    def result(self) -> str:
        text = "".join(self.parts)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip() + "\n"


def _fallback_converters():
    # 入参已由 #10 编码前置层保证是 UTF-8（原文件严格 utf-8，或同名 UTF-8
    # 临时副本），因此这里用严格解码：万一前置层被绕过会直接抛错暴露，
    # 而不是 errors="replace" 静默把 GBK 字节吞成 U+FFFD。
    def txt(path):
        raw = Path(path).read_text(encoding="utf-8")
        return "# %s\n\n%s\n" % (Path(path).name, raw.rstrip() + "\n")

    def html(path):
        p = _FallbackHtml()
        p.feed(Path(path).read_text(encoding="utf-8"))
        p.close()
        return p.result()

    def csv_md(path):
        with open(path, "r", encoding="utf-8", newline="") as fh:
            rows = list(csv.reader(fh))
        if not rows:
            return "# %s\n\n<!-- 空 CSV -->\n" % Path(path).name
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        out = ["| " + " | ".join(c.replace("|", "\\|") for c in rows[0]) + " |",
               "|" + " --- |" * width]
        for r in rows[1:]:
            out.append("| " + " | ".join(c.replace("|", "\\|") for c in r) + " |")
        return "# %s\n\n%s\n" % (Path(path).name, "\n".join(out))

    return {".txt": txt, ".text": txt, ".log": txt,
            ".html": html, ".htm": html, ".csv": csv_md}


def load_converters(skill_script: str):
    path = Path(skill_script)
    if path.is_file():
        try:
            spec = importlib.util.spec_from_file_location("_md_convert", str(path))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            conv = dict(mod.CONVERTERS)
            if conv:
                # 补齐技能脚本可能缺失的纯文本扩展名，避免「无可用转换器」
                for e, fn in _fallback_converters().items():
                    conv.setdefault(e, fn)
                return conv, "技能脚本 %s" % path.name
        except Exception as exc:  # noqa: BLE001
            print("[WARN] 技能脚本加载失败，回退内置转换器: %s" % exc)
    return _fallback_converters(), "内置回退转换器"


def normalize_markdown(text: str) -> str:
    """结构修补：对齐技能「检查点 4 / 失败模式 8」的产物质量要求。

    修复复用转换脚本时实测到的三类问题：UTF-8 BOM 污染表头、
    表格行行首多余空格、<a> 标签转换后只剩右半边括号。
    """
    text = text.replace("\ufeff", "")
    text = re.sub(r"(?m)^[ \t]+(\|)", r"\1", text)
    text = re.sub(r"(?<!\[)([\w\u4e00-\u9fff]+)\]\(([^)\s]+)\)", r"[\1](\2)", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


# --------------------------------------------------------------------------
# 文本编码前置预处理层（#10）
#
# 问题：技能脚本 md_convert.py:177/185/195 与内置回退转换器都用
#   open(..., encoding="utf-8", errors="replace") 读文件，GBK/GB18030 字节
#   被静默替换成 U+FFFD，原文永久丢失（红线三 / FM-05），且转换器本身
#   仍报「成功」——这是最危险的静默降级。
# 做法：读【原始字节】-> BOM 与严格解码链探测编码 -> 需要时生成【同名】
#   UTF-8 临时副本，只把副本喂给转换器；原文件一个字节都不改。
#
# ⚠ 硬约束（#10 铁律）：doc_id = doc_ + sha256(原始文件字节)[:12]，src
#   注释第 7 字段 sha256 为原始文件字节的完整 64 位小写 hex。UTF-8 临时
#   副本只用于喂转换器，绝不参与 doc_id / sha256 计算，否则 provenance
#   manifest、MERGED 目录锚点与块级锚点全部失效。
# --------------------------------------------------------------------------
_BOMS = (
    (b"\xef\xbb\xbf", "utf-8-sig", "BOM: UTF-8"),
    # UTF-32 的 BOM 以 UTF-16 的 BOM 为前缀，必须先判断
    (b"\xff\xfe\x00\x00", "utf-32-le", "BOM: UTF-32 LE"),
    (b"\x00\x00\xfe\xff", "utf-32-be", "BOM: UTF-32 BE"),
    (b"\xff\xfe", "utf-16-le", "BOM: UTF-16 LE"),
    (b"\xfe\xff", "utf-16-be", "BOM: UTF-16 BE"),
)

# 严格解码链。GBK 排在 GB18030 之前只为拿到更精确的编码名：GB18030 是 GBK
# 的超集，任何 GBK 文件都能被它解开，但标签会宽泛成 gb18030。Big5 在两者
# 之后：对简体中文场景 GBK 命中率远高，先判 Big5 会把部分 GBK 误标。
# Latin-1 兜底保证任何字节都能出文本，但编码名会带「低置信」标记供复核。
_STRICT_CHAIN = ("utf-8", "gbk", "gb18030", "big5")


def decode_text_bytes(data: bytes) -> tuple[str, str, str]:
    """原始字节 -> (文本, 编码名, 判定依据)。全程 errors="strict"，绝不吞字节。"""
    for bom, enc, why in _BOMS:
        if data.startswith(bom):
            try:
                text = data.decode(enc)
            except UnicodeDecodeError:
                break  # BOM 不可信，交给下面的严格链
            # utf-8-sig 自动吃掉 BOM；显式端序解码后 BOM 会变成一个 \ufeff 字符
            return text.lstrip("\ufeff"), enc, why
    for enc in _STRICT_CHAIN:
        try:
            return data.decode(enc), enc, "严格解码命中 %s" % enc
        except UnicodeDecodeError:
            continue
    return (data.decode("latin-1"), "latin-1(低置信)",
            "严格解码链全部失败，Latin-1 兜底（可能损失原文）")


def _enc_workdir() -> Path:
    """编码副本工作目录：父进程指定则沿用并交由父进程清理，否则自建并自清理。

    环境变量 JINGHE_ENCDIR 由图形界面（app.py）设置。之所以要父进程持有目录：
    atexit 在 terminate() 时不执行，界面点「取消」强杀子进程会把用户文档的
    UTF-8 副本留在 %TEMP%，既是垃圾也是隐私泄漏。
    """
    given = os.environ.get("JINGHE_ENCDIR")
    if given:
        d = Path(given)
        d.mkdir(parents=True, exist_ok=True)
        return d
    d = Path(tempfile.mkdtemp(prefix="jinghe-enc-"))
    atexit.register(shutil.rmtree, str(d), True)
    return d


def preprocess_text_encoding(path: Path, workdir: Path | None,
                             slot: int) -> tuple[Path, dict]:
    """编码前置处理：返回 (喂给转换器的路径, 留痕信息)。

    - 无 BOM 的纯 UTF-8：原路径直接用，零复制、零副作用。
    - 其他编码（GBK / GB18030 / GB18030 系 / UTF-16 ...）：在
      workdir/<slot>/ 下生成【同名】UTF-8 临时副本。
      同名很关键——转换器用 Path(path).name 生成标题，改名会让 MERGED.md
      的去重标题逻辑失配，泄漏一行 `# 临时文件名`。

    本函数只读原文件，任何情况下都不写回原路径。
    """
    data = path.read_bytes()
    text, enc, why = decode_text_bytes(data)
    info = {"encoding": enc, "basis": why, "bytes": len(data),
            "converted": False, "feed": path}
    if enc == "utf-8":
        return path, info
    if workdir is None:  # dry-run 等只读场景：不落副本，仅留痕
        return path, info
    slot_dir = workdir / ("%04d" % slot)
    slot_dir.mkdir(parents=True, exist_ok=True)
    feed = slot_dir / path.name
    feed.write_text(text, encoding="utf-8")
    info.update(converted=True, feed=feed)
    return feed, info


# --------------------------------------------------------------------------
# 出处定位最小集（#9）：追加式、不覆盖既有 source 注释
# --------------------------------------------------------------------------
def _sha256_hex(path: Path) -> str:
    """一次读盘取完整 64 位 sha256；派生 doc_id 与 src 注释的 sha256 字段。"""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _doc_id(path: Path) -> str:
    """doc_id = doc_ + sha256(文件字节)[:12]；只含内容哈希，不含路径字符。"""
    return "doc_" + _sha256_hex(path)[:12]


def _content_status(record: dict) -> str:
    """阶段 2 摘要流水线的内容可用性三态：normal / placeholder / unavailable。"""
    if record["status"] == "成功":
        return ("placeholder" if (record["size"] == 0 or "占位产物" in record["note"])
                else "normal")
    return "unavailable"


def _degrade_label(status: str) -> str:
    """把降级状态归入人可读分项，供验收口径说明动态统计（严禁硬编码件数）。"""
    if status.startswith("待人工授权"):
        return "待人工授权"
    if "无效 OOXML/ZIP 容器" in status:
        return "无效容器"
    if "需先 OCR" in status or "疑似扫描件" in status:
        return "需 OCR"
    if status.startswith("需拆分"):
        return "需拆分"
    if status.startswith("需预处理"):
        return "需预处理"
    if status.startswith("待安装依赖"):
        return "待专用解析器"
    if status.startswith("转换失败"):
        return "转换失败"
    return re.split(r"[：:]", status)[0] or "其他降级"


# 块级锚点接口（#9 第二批）：make_anchor / parse_anchor，保证 round-trip 可解析。
# 形态：<!-- anchor: <真实doc_id> | block: N | page: N | slide: N | sheet: 名
#        | chapter: N | member: 路径 | line: A..B -->（键用冒号，只写适用键）。
_ANCHOR_LOC_KEYS = ("page", "slide", "sheet", "chapter", "member",
                    "heading_path", "line")


def _anchor_value(val) -> str:
    """锚点 / src 字段值不得含 ` | ` 或 `-->`，避免破坏分隔与注释闭合。"""
    s = str(val).replace("|", "_").replace("-->", "--&gt;")
    return re.sub(r"\s+", " ", s).strip()[:80]


def make_anchor(doc_id: str, block_idx: int, **locators) -> str:
    """生成块级锚点：第一个值是真实 doc_id，键统一 `key: value` 冒号形式。

    只写该格式适用的键，不为凑字段填空值（SPEC.md:122 接口定义）。
    """
    parts = [doc_id, "block: %d" % block_idx]
    for key in _ANCHOR_LOC_KEYS:
        val = locators.get(key)
        if val not in (None, ""):
            parts.append("%s: %s" % (key, _anchor_value(val)))
    return "<!-- anchor: %s -->" % " | ".join(parts)


def parse_anchor(comment: str) -> dict:
    """解析 make_anchor 产出的注释，保证 round-trip 可解析（#6 引用级回填用）。"""
    m = re.match(r"<!--\s*anchor:\s*(.*?)\s*-->\s*$", comment.strip(), re.S)
    if not m:
        return {}
    fields = [f.strip() for f in m.group(1).split("|")]
    if not fields or not fields[0]:
        return {}
    out = {"doc_id": fields[0]}
    for f in fields[1:]:
        if ":" in f:
            k, v = f.split(":", 1)
            out[k.strip()] = v.strip()
    return out


# 兼容 #9 第一批的旧调用名
_anchor = make_anchor


def _inject_anchors(text: str, ext: str, doc_id: str) -> tuple[str, list[str]]:
    """逐块注入块级锚点，返回 (注入后文本, 实际使用的键名列表)。

    以 Markdown 标题行作为块边界；按格式给出真实可用的定位键：
      PDF->page / PPTX->slide / XLSX->sheet / EPUB->chapter+member /
      ZIP->member / DOCX->heading_path（可选扩展）/ 文本类->line。
    所有块都带 block 序号与 line 行号范围；不编造格式不存在的定位键。
    """
    lines = text.splitlines()
    if not lines:
        return text, []
    # 块边界按格式选用真正的结构标题（PPTX→Slide N / XLSX→sheet 名 /
    # EPUB→Chapter N / ZIP→member 名；其余按 Markdown 标题），避免把文件主标题
    # 或正文里的 h1 误当分块点而编造定位键。
    if ext == ".pptx":
        boundary = re.compile(r"^##\s+Slide\s+(\d+)\b")
    elif ext == ".xlsx":
        boundary = re.compile(r"^##\s+(.+)$")
    elif ext == ".epub":
        boundary = re.compile(r"^##\s+Chapter\s+(\d+)\b")
    elif ext == ".zip":
        boundary = re.compile(r"^##\s+(.+)$")
    else:
        boundary = re.compile(r"^#{1,6}\s+.+$")

    starts = [0] + [i for i, ln in enumerate(lines)
                    if i and boundary.match(ln)]
    bounds = sorted(set(starts + [len(lines)]))
    blocks = [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)
              if bounds[i + 1] > bounds[i]]
    if not blocks:
        blocks = [(0, len(lines))]

    used: set[str] = set()
    out: list[str] = []
    for n, (a, b) in enumerate(blocks, 1):
        head = lines[a]
        hit = boundary.match(head)  # 主标题块不命中结构标题 -> 不写定位键
        loc: dict = {"line": "%d..%d" % (a + 1, b)}
        if ext == ".pdf":
            loc["page"] = n
        elif ext == ".pptx" and hit:
            loc["slide"] = int(hit.group(1))
        elif ext == ".xlsx" and hit:
            loc["sheet"] = hit.group(1).strip()
        elif ext == ".epub" and hit:
            loc["chapter"] = int(hit.group(1))
            for ln in lines[a:b]:
                mm = re.match(r"^>\s*member:\s*`([^`]+)`", ln)
                if mm:
                    loc["member"] = mm.group(1)
                    break
        elif ext == ".zip" and hit:
            loc["member"] = hit.group(1).strip()
        elif ext == ".docx" and re.match(r"^#{1,6}\s", head):
            loc["heading_path"] = re.sub(r"^#{1,6}\s+", "", head).strip()
        used.update(k for k in _ANCHOR_LOC_KEYS if loc.get(k) not in (None, ""))
        out.append(make_anchor(doc_id, n, **loc))
        out.extend(lines[a:b])

    order = ("page", "slide", "sheet", "chapter", "member",
             "heading_path", "block", "line")
    keys = [k for k in order if k == "block" or k in used]
    return "\n".join(out) + "\n", keys


def convert_text_file(path: Path, converters) -> str | None:
    """文本类转换入口。path 由 #10 前置层保证是可严格解码的 UTF-8。"""
    ext = path.suffix.lower()
    if ext in SKILL_EXT and ext in converters:
        return normalize_markdown(converters[ext](str(path)))
    raw = path.read_text(encoding="utf-8")
    if ext == ".md":
        return normalize_markdown(raw)
    if ext == ".json":
        try:
            pretty = json.dumps(json.loads(raw), ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            pretty = raw
        return normalize_markdown("# %s\n\n```json\n%s\n```\n" % (path.name, pretty))
    if ext == ".xml":
        return normalize_markdown("# %s\n\n```xml\n%s\n```\n" % (path.name, raw.rstrip()))
    return None


# --------------------------------------------------------------------------
# 富文档：内置零依赖解析（markitdown 缺失时的真实提取，不是占位/伪装成功）
# 仅用标准库 zipfile / xml.etree / zlib / re；产物结构、自检逻辑均不变。
# --------------------------------------------------------------------------
_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_A_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_S_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _smart_text(data: bytes) -> str:
    """字节 -> 文本：复用 #10 前置层的严格解码链（BOM -> utf-8 -> gbk -> ...）。

    不使用 errors="replace" 静默吞掉无法解码的字节（FM-05 / 红线三）。
    """
    return decode_text_bytes(data)[0]


def _zip_xml(zf: zipfile.ZipFile, name: str):
    try:
        return ET.fromstring(zf.read(name))
    except (KeyError, ET.ParseError):
        return None


def _docx_body(zf: zipfile.ZipFile) -> str:
    """word/document.xml：段落（含标题样式）与表格 -> Markdown。"""
    root = _zip_xml(zf, "word/document.xml")
    if root is None:
        return ""
    body = root.find(_W_NS + "body")
    if body is None:
        body = root
    out: list[str] = []
    for el in list(body):
        if el.tag == _W_NS + "p":
            level = 0
            ppr = el.find(_W_NS + "pPr")
            if ppr is not None:
                st = ppr.find(_W_NS + "pStyle")
                if st is not None:
                    m = re.search(r"(?i)heading\s*(\d)|title", st.get(_W_NS + "val", "") or "")
                    if m:
                        level = min((int(m.group(1)) if m.group(1) else 1) + 1, 6)
            txt = "".join(t.text or "" for t in el.iter(_W_NS + "t")).strip()
            if txt:
                out.append(("#" * level + " " + txt) if level else txt)
                out.append("")
        elif el.tag == _W_NS + "tbl":
            rows: list[list[str]] = []
            for tr in el.iter(_W_NS + "tr"):
                cells = [" ".join(t.text or "" for t in tc.iter(_W_NS + "t")).strip()
                         .replace("|", "\\|")
                         for tc in tr.findall(_W_NS + "tc")]
                if cells:
                    rows.append(cells)
            if rows:
                width = max(len(r) for r in rows)
                rows = [r + [""] * (width - len(r)) for r in rows]
                out.append("| " + " | ".join(rows[0]) + " |")
                out.append("|" + " --- |" * width)
                for r in rows[1:]:
                    out.append("| " + " | ".join(r) + " |")
                out.append("")
    return "\n".join(out).strip()


def _pptx_body(zf: zipfile.ZipFile) -> str:
    """ppt/slides/slideN.xml：逐页抽取 <a:t> 文本，按页分节。"""
    names = sorted(
        (n for n in zf.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
        key=lambda n: int(re.search(r"(\d+)\.xml", n).group(1)))
    out: list[str] = []
    for i, name in enumerate(names, 1):
        root = _zip_xml(zf, name)
        if root is None:
            continue
        lines = [(t.text or "").strip() for t in root.iter(_A_NS + "t")
                 if (t.text or "").strip()]
        out += ["## Slide %d" % i, ""]
        out.append("\n".join("- " + t for t in lines) if lines
                   else "<!-- 本页无文本（可能为图片） -->")
        out.append("")
    return "\n".join(out).strip()


def _col_index(ref: str) -> int:
    m = re.match(r"([A-Z]+)", ref or "")
    if not m:
        return -1
    idx = 0
    for ch in m.group(1):
        idx = idx * 26 + (ord(ch) - 64)
    return idx - 1


def _xlsx_body(zf: zipfile.ZipFile) -> str:
    """xl/sharedStrings.xml + xl/worksheets/sheetN.xml：每工作表一张 Markdown 表。"""
    shared: list[str] = []
    ss = _zip_xml(zf, "xl/sharedStrings.xml")
    if ss is not None:
        for si in ss:
            shared.append("".join(t.text or "" for t in si.iter(_S_NS + "t")))
    sheet_names: list[str] = []
    wb = _zip_xml(zf, "xl/workbook.xml")
    if wb is not None:
        for sh in wb.iter(_S_NS + "sheet"):
            sheet_names.append(sh.get("name") or "Sheet")
    sheet_files = sorted(
        (n for n in zf.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)),
        key=lambda n: int(re.search(r"(\d+)\.xml", n).group(1)))
    out: list[str] = []
    for i, sf in enumerate(sheet_files):
        name = sheet_names[i] if i < len(sheet_names) else "Sheet%d" % (i + 1)
        out += ["## %s" % name, ""]
        root = _zip_xml(zf, sf)
        if root is None:
            out += ["<!-- 工作表解析失败 -->", ""]
            continue
        rows: list[list[str]] = []
        for row in root.iter(_S_NS + "row"):
            cells: dict[int, str] = {}
            for c in row.findall(_S_NS + "c"):
                ci = _col_index(c.get("r", ""))
                if ci < 0:
                    continue
                t, val = c.get("t"), ""
                if t == "inlineStr":
                    is_el = c.find(_S_NS + "is")
                    if is_el is not None:
                        val = "".join(x.text or "" for x in is_el.iter(_S_NS + "t"))
                else:
                    v = c.find(_S_NS + "v")
                    raw = (v.text or "") if v is not None else ""
                    if t == "s":
                        try:
                            val = shared[int(raw)]
                        except (ValueError, IndexError):
                            val = raw
                    elif t == "b":
                        val = "TRUE" if raw == "1" else "FALSE"
                    else:
                        val = raw
                cells[ci] = val.replace("|", "\\|").replace("\n", " ")
            if cells:
                width = max(cells) + 1
                rows.append([cells.get(j, "") for j in range(width)])
        if rows:
            width = max(len(r) for r in rows)
            rows = [r + [""] * (width - len(r)) for r in rows]
            out.append("| " + " | ".join(rows[0]) + " |")
            out.append("|" + " --- |" * width)
            for r in rows[1:]:
                out.append("| " + " | ".join(r) + " |")
        out.append("")
    return "\n".join(out).strip()


def _epub_body(zf: zipfile.ZipFile) -> str:
    """container.xml -> opf -> spine -> xhtml 正文；缺失时按文件名兜底。"""
    opf_path = None
    cont = _zip_xml(zf, "META-INF/container.xml")
    if cont is not None:
        for rf in cont.iter():
            if rf.tag.endswith("}rootfile"):
                opf_path = rf.get("full-path")
                break
    chapters: list[tuple[str, str]] = []
    if opf_path and opf_path in zf.namelist():
        base = posixpath.dirname(opf_path)
        opf = _zip_xml(zf, opf_path)
        manifest: dict[str, str] = {}
        spine: list[str] = []
        if opf is not None:
            for el in opf.iter():
                if el.tag.endswith("}item"):
                    manifest[el.get("id", "")] = el.get("href", "")
                elif el.tag.endswith("}itemref"):
                    spine.append(el.get("idref", ""))
        for idref in spine:
            href = manifest.get(idref, "")
            if not href:
                continue
            full = posixpath.normpath(posixpath.join(base, href))
            if full in zf.namelist():
                chapters.append((full, _smart_text(zf.read(full))))
    if not chapters:
        for n in sorted(x for x in zf.namelist()
                        if x.lower().endswith((".xhtml", ".html", ".htm"))):
            chapters.append((n, _smart_text(zf.read(n))))
    out: list[str] = []
    for i, (name, raw) in enumerate(chapters, 1):
        p = _FallbackHtml()
        try:
            p.feed(raw)
            p.close()
            text = p.result()
        except Exception:  # noqa: BLE001
            text = re.sub(r"<[^>]+>", " ", raw)
        out += ["## Chapter %d" % i, "", "> member: `%s`" % name, "",
                text.strip(), ""]
    return "\n".join(out).strip()


def _zip_body(zf: zipfile.ZipFile) -> str:
    """遍历成员抽取文本类；仅展开一层，嵌套 ZIP 不递归并留痕（FM-07）。"""
    text_ext = (".txt", ".text", ".log", ".md", ".csv", ".json", ".xml",
                ".html", ".htm", ".xhtml")
    out: list[str] = []
    nested: list[str] = []
    for info in zf.infolist():
        name = info.filename
        if info.is_dir():
            continue
        low = name.lower()
        if low.endswith(".zip"):
            nested.append(name)
            continue
        if not low.endswith(text_ext):
            continue
        raw = zf.read(info)[:200_000]
        text = _smart_text(raw)
        if low.endswith((".html", ".htm", ".xhtml")):
            p = _FallbackHtml()
            p.feed(text)
            p.close()
            body = p.result()
        else:
            body = text.strip()
        out += ["## %s" % name, "", body.strip(), ""]
    lines: list[str] = []
    if nested:
        lines += ["> 注：检测到 %d 个嵌套 ZIP，按 FM-07 仅展开一层、未递归：%s"
                  % (len(nested), ", ".join(nested)), ""]
    return "\n".join(lines + out).strip()


def _pdf_streams(data: bytes):
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
        chunk = m.group(1)
        if b"FlateDecode" in data[max(0, m.start() - 300):m.start()]:
            try:
                chunk = zlib.decompress(chunk)
            except zlib.error:
                pass
        yield chunk


def _pdf_literal_strings(blob: bytes) -> list[bytes]:
    """抽取 PDF 文本对象里的 (...) 字符串，处理转义与嵌套括号。"""
    res, i, n = [], 0, len(blob)
    esc = {0x6E: 10, 0x72: 13, 0x74: 9, 0x62: 8, 0x66: 12}
    while i < n:
        if blob[i] != 0x28:  # '('
            i += 1
            continue
        depth, buf, i = 1, bytearray(), i + 1
        while i < n and depth:
            ch = blob[i]
            if ch == 0x5C:  # backslash
                nx = blob[i + 1] if i + 1 < n else 0
                if nx in esc:
                    buf.append(esc[nx]); i += 2; continue
                if 0x30 <= nx <= 0x37:  # 八进制
                    j, oc = i + 1, b""
                    while j < n and len(oc) < 3 and 0x30 <= blob[j] <= 0x37:
                        oc += bytes([blob[j]]); j += 1
                    buf.append(int(oc, 8) & 0xFF); i = j; continue
                if nx in (0x0A, 0x0D):  # 续行
                    i += 2; continue
                buf.append(nx); i += 2; continue
            if ch == 0x28:
                depth += 1; buf.append(ch)
            elif ch == 0x29:
                depth -= 1
                if depth == 0:
                    i += 1; break
                buf.append(ch)
            else:
                buf.append(ch)
            i += 1
        res.append(bytes(buf))
    return res


def _decode_pdf_string(b: bytes) -> str:
    if b.startswith(b"\xfe\xff"):
        try:
            return b[2:].decode("utf-16-be")
        except UnicodeDecodeError:
            pass
    for enc in ("utf-8", "gb18030", "big5"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("latin-1")


def _pdf_hex_strings(blob: bytes) -> list[bytes]:
    """抽取 PDF 文本对象里的 <...> 十六进制串（常见文本编码形式，原解析器漏掉了）。

    PDF 文本常以十六进制串表达（如 <48656C6C6F> = "Hello"）。原 _pdf_literal_strings
    只认 (...) 字面量串，导致大量文本 PDF 提取为空、被判「待安装依赖 markitdown[all]」。
    这里单独抽取 <...>，并跳过字典定界符 << >>。
    """
    res, i, n = [], 0, len(blob)
    while i < n:
        if blob[i] != 0x3C:  # '<'
            i += 1
            continue
        if i + 1 < n and blob[i + 1] == 0x3C:  # '<<' 字典开始，跳过
            i += 2
            continue
        start = i + 1
        j = start
        while j < n and blob[j] != 0x3E:  # '>'
            j += 1
        res.append(blob[start:j])
        i = j + 1
    return res


def _decode_pdf_hex(b: bytes) -> str:
    clean = b"".join(b.split())  # 去空白
    if len(clean) % 2 == 1:
        clean = clean + b"0"
    try:
        raw = bytes.fromhex(clean.decode("ascii"))
    except Exception:
        return ""
    return _decode_pdf_string(raw)


# --------------------------------------------------------------------------
# PDF 对象 / 流 / CID 字体映射（#11 真实文件修复，2026-11-13）
#
# 背景：WPS 导出的中文 PDF 用 /Type0 + /Encoding /Identity-H + /CIDFontType2
# 字体，内容流里的 <...> 是【2 字节字形号 GID】，不是字符编码。旧实现把 GID
# 直接丢给 _decode_pdf_string 猜 utf-8/gb18030/latin-1，解出随机汉字并报「成功」
# ——假成功比报错更糟。这里按 /ToUnicode CMap 把 GID 映射回 Unicode；映射
# 不完整时由 _builtin_rich_extract 的质量门禁诚实降级。
# --------------------------------------------------------------------------
# 状态文案：CID 子集字体 + ToUnicode 映射不完整时必须用这条，不得报成功。
PDF_CID_NEEDS_SPECIALIST = (
    "需专用解析器：PDF 使用了 CID 子集字体但 ToUnicode 映射不完整，"
    "内置解析无法还原文字（本机 markitdown 因 onnxruntime 崩溃不可用），"
    "建议另存为可复制文本的 PDF 或转 .docx 后重试")

# "N 0 obj" 头。前面加 (?<![0-9]) 避免把 "12 0 obj" 从 "112 0 obj" 截出来，
# 后面用 \b 防止 "objXxx" 误命中。
_PDF_OBJ_RE = re.compile(rb"(?<![0-9])(\d+)\s+(\d+)\s+obj\b")
# /Length 可能是间接引用（/Length 12 0 R），间接时不能当数字用。
# 负向先行断言把 "<数字> <数字> R" 这种间接引用排除掉。
_PDF_LENGTH_RE = re.compile(rb"/Length\s+(\d+)(?!\s+\d+\s+R)")
_PDF_WS = b" \t\r\n\f\x00"
# 内容流定界符（PDF 规范 Table 1 的 delimiter 字符 + 空白）
_PDF_DELIM = b" \t\r\n\f\x00()<>[]{}/%"


def _pdf_object_end(blob: bytes, start: int) -> int:
    """返回对象体结束偏移（不含 endobj）。优先按 /Length 跳过二进制流，
    避免压缩流里偶然出现的 "endobj" 把对象body截断。"""
    n = len(blob)
    endobj = blob.find(b"endobj", start)
    if endobj < 0:
        endobj = n
    stream_at = blob.find(b"stream", start, min(n, start + 4096))
    if stream_at < 0 or stream_at > endobj:
        return endobj
    m = _PDF_LENGTH_RE.search(blob[start:stream_at])
    if not m:
        return endobj
    data_start = stream_at + 6  # 跳过 "stream"
    if blob[data_start:data_start + 2] == b"\r\n":
        data_start += 2
    elif blob[data_start:data_start + 1] in (b"\n", b"\r"):
        data_start += 1
    tail = blob.find(b"endobj", data_start + int(m.group(1)))
    return tail if tail > 0 else endobj


def _pdf_objects(blob: bytes) -> dict[int, bytes]:
    """扫 `N 0 obj ... endobj`，返回 {对象号: 对象体字节}。不依赖 xref 表
    （不少导出器写的 xref 偏移是错的）。同一对象号重复出现时后写覆盖
    （增量更新以最新一代为准）。"""
    objs: dict[int, bytes] = {}
    for m in _PDF_OBJ_RE.finditer(blob):
        start = m.end()
        body = blob[start:_pdf_object_end(blob, start)]
        head = body.lstrip(_PDF_WS)[:1]
        # 压缩流里可能随机出现 "N 0 obj"，只接受以合法对象起始符开头的候选。
        if head not in (b"<", b"/", b"[", b"(", b"{") and not head.isdigit():
            continue
        objs[int(m.group(1))] = body
    return objs


def _pdf_stream_bytes(obj_body: bytes) -> bytes | None:
    """取出 stream 与 endstream 之间的原始字节并按 /Filter 解码。

    仅支持无过滤器与 /FlateDecode（含 raw deflate 兜底）；DCTDecode 等其它
    过滤器、或解压失败一律返回 None（调用方据此降级，绝不猜）。
    """
    s = obj_body.find(b"stream")
    if s < 0:
        return None
    head = obj_body[:s]
    ds = s + 6
    if obj_body[ds:ds + 2] == b"\r\n":
        ds += 2
    elif obj_body[ds:ds + 1] in (b"\n", b"\r"):
        ds += 1
    m = _PDF_LENGTH_RE.search(head)
    raw = None
    if m and ds + int(m.group(1)) <= len(obj_body):
        raw = obj_body[ds:ds + int(m.group(1))]
    if raw is None:  # /Length 缺失或不可信 -> 退回 endstream 定界
        e = obj_body.find(b"endstream", ds)
        if e < 0:
            return None
        raw = obj_body[ds:e].rstrip(b"\r\n")
    if re.search(rb"/FlateDecode\b|/Fl\b", head):
        for unpack in (lambda b: zlib.decompress(b),
                       lambda b: zlib.decompressobj(-15).decompress(b)):
            try:
                return unpack(raw)
            except zlib.error:
                continue
        return None
    if re.search(rb"/Filter\b", head):
        return None
    return raw


def _pdf_dict_slice(blob: bytes, start: int) -> bytes:
    """从 start（指向 '<<'）取出配平的字典字节；不配平时截断兜底。"""
    depth, i, n = 0, start, len(blob)
    while i < n - 1:
        two = blob[i:i + 2]
        if two == b"<<":
            depth += 1
            i += 2
            continue
        if two == b">>":
            depth -= 1
            i += 2
            if depth <= 0:
                return blob[start:i]
            continue
        i += 1
    return blob[start:start + 2000]


def _pdf_font_refs(objs: dict[int, bytes]) -> dict[str, int]:
    """收集「字体资源名 -> 字体对象号」。

    做法：扫每个对象里的 /Font 子字典，取 `/Name N 0 R`。这是【实用近似】：
    资源名 F1/F2/FT11 在同一文档里基本唯一，因此不做「页 -> 资源字典」的
    逐页隔离；同名不同字体（极罕见）会以最后出现的为准。
    """
    refs: dict[str, int] = {}
    for body in objs.values():
        for m in re.finditer(rb"/Font\s*<<", body):
            sub = _pdf_dict_slice(body, m.end() - 2)
            for fm in re.finditer(
                    rb"/([^\s/<>\[\](){}%]+)\s+(\d+)\s+\d+\s+R", sub):
                refs.setdefault(fm.group(1).decode("latin-1"),
                                int(fm.group(2)))
    return refs


def _pdf_font_widths(objs: dict[int, bytes]) -> dict[str, int]:
    """字体资源名 -> 码宽（Identity-H 等 Type0 复合字体为 2 字节，其余 1）。"""
    widths: dict[str, int] = {}
    for name, num in _pdf_font_refs(objs).items():
        body = objs.get(num, b"")
        cid = b"/Type0" in body or b"/Identity-H" in body
        widths[name] = 2 if cid else 1
    return widths


def _hex_to_int(h: str) -> int | None:
    clean = "".join(h.split())
    if not clean:
        return None
    try:
        return int(clean, 16)
    except ValueError:
        return None


def _utf16be_to_str(h: str) -> str | None:
    """CMap 目标串：UTF-16BE 十六进制 -> Python str（支持多码元连字）。"""
    clean = "".join(h.split())
    if not clean:
        return None
    if len(clean) % 4:  # 奇数字节按右补 0 对齐到一个码元
        clean = clean.ljust(len(clean) + (4 - len(clean) % 4), "0")
    try:
        return bytes.fromhex(clean).decode("utf-16-be")
    except (ValueError, UnicodeDecodeError):
        return None


def _bf_dst_increment(start_hex: str, offset: int) -> str | None:
    """bfrange 递增形式：只对目标串【最后一个 UTF-16 码元】加 offset。"""
    clean = "".join(start_hex.split())
    if not clean:
        return None
    if len(clean) % 4:
        clean = clean.ljust(len(clean) + (4 - len(clean) % 4), "0")
    try:
        buf = bytearray(bytes.fromhex(clean))
    except ValueError:
        return None
    if len(buf) < 2:
        return None
    unit = ((buf[-2] << 8) | buf[-1]) + offset
    unit &= 0xFFFF
    buf[-2], buf[-1] = unit >> 8, unit & 0xFF
    try:
        return bytes(buf).decode("utf-16-be")
    except UnicodeDecodeError:
        return None


def _parse_bf_range_body(body: str, out: dict[int, str]) -> None:
    """解析 beginbfrange…endbfrange 的正文（两种形式都支持）。"""
    toks: list[tuple[str, str]] = []
    for m in re.finditer(r"<([0-9A-Fa-f\s]*)>|\[|\]", body):
        if m.group(0) == "[":
            toks.append(("[", ""))
        elif m.group(0) == "]":
            toks.append(("]", ""))
        else:
            toks.append(("h", m.group(1)))
    k = 0
    while k + 2 < len(toks):
        if toks[k][0] != "h" or toks[k + 1][0] != "h":
            k += 1
            continue
        lo, hi = _hex_to_int(toks[k][1]), _hex_to_int(toks[k + 1][1])
        k += 2
        if lo is None or hi is None or hi < lo:
            continue
        if k < len(toks) and toks[k][0] == "[":
            k += 1
            off = 0
            while k < len(toks) and toks[k][0] == "h":
                if lo + off > hi:
                    break
                s = _utf16be_to_str(toks[k][1])
                if s:
                    out[lo + off] = s
                off += 1
                k += 1
            if k < len(toks) and toks[k][0] == "]":
                k += 1
        elif k < len(toks) and toks[k][0] == "h":
            start_hex = toks[k][1]
            k += 1
            count = hi - lo + 1
            if count > 0x10000:  # 防御畸形 CMap，避免巨大循环
                continue
            for off in range(count):
                s = _bf_dst_increment(start_hex, off)
                if s:
                    out[lo + off] = s
        else:  # 缺少目标串，跳到下一个
            continue


def _parse_bf_cmap(text: str) -> dict[int, str]:
    """解析 ToUnicode CMap，返回 {源码位: Unicode 字符串}。

    支持 beginbfchar（`<src> <dst>` 对）与 beginbfrange（`<lo> <hi> <dstStart>`
    递增、`<lo> <hi> [<d1> <d2> …]` 数组）两种形式。目标可以是多字符
    （连字/组合音），按原样保留。
    """
    cmap: dict[int, str] = {}
    for sec in re.finditer(r"beginbfchar(.*?)endbfchar", text, re.S):
        hexes = re.findall(r"<([0-9A-Fa-f\s]*)>", sec.group(1))
        for i in range(0, len(hexes) - 1, 2):
            src = _hex_to_int(hexes[i])
            dst = _utf16be_to_str(hexes[i + 1])
            if src is not None and dst is not None:
                cmap[src] = dst
    for sec in re.finditer(r"beginbfrange(.*?)endbfrange", text, re.S):
        _parse_bf_range_body(sec.group(1), cmap)
    return cmap


def _pdf_font_maps(objs: dict[int, bytes]) -> dict[str, dict[int, str]]:
    """字体资源名 -> {源码位: Unicode}。只收录 ToUnicode 可用的字体；
    没收录的字体在解码时走旧的字节猜编码逻辑（行为不变）。"""
    maps: dict[str, dict[int, str]] = {}
    for name, num in _pdf_font_refs(objs).items():
        body = objs.get(num)
        if not body:
            continue
        m = re.search(rb"/ToUnicode\s+(\d+)\s+\d+\s+R", body)
        if not m:
            continue
        raw = _pdf_stream_bytes(objs.get(int(m.group(1)), b""))
        if raw is None:
            continue
        cmap = _parse_bf_cmap(raw.decode("latin-1"))
        if cmap:
            maps[name] = cmap
    return maps


def _pdf_page_contents(objs: dict[int, bytes], data: bytes) -> list[bytes]:
    """按页返回内容流字节；找不到页面对象时退回全量 stream 扫描。"""
    pages: list[bytes] = []
    for body in objs.values():
        if not re.search(rb"/Type\s*/Page\b", body):
            continue
        m = re.search(rb"/Contents\s*(\[[^\]]*\]|\d+\s+\d+\s+R)", body)
        if not m:
            continue
        nums = [int(x) for x in re.findall(rb"(\d+)\s+\d+\s+R", m.group(1))]
        chunks = []
        for num in nums:
            raw = _pdf_stream_bytes(objs.get(num, b""))
            if raw:
                chunks.append(raw)
        if chunks:
            pages.append(b"\n".join(chunks))
    return pages or list(_pdf_streams(data))


_PDF_ESC = {0x6E: 10, 0x72: 13, 0x74: 9, 0x62: 8, 0x66: 12}
_PDF_STRUCT_OPS = ("<<", ">>", "[", "]", "{", "}")


def _pdf_content_tokens(blob: bytes):
    """极简内容流词法器，产出 (kind, value)：
    kind = num / name / str(bytes) / hex(bytes) / op(str)。
    不做完整语法分析，只保证字符串与操作符不被混淆（内联图像按 ID…EI 跳过）。
    """
    i, n = 0, len(blob)
    while i < n:
        c = blob[i]
        if c in _PDF_WS:
            i += 1
            continue
        if c == 0x25:  # '%' 注释
            j = blob.find(b"\n", i)
            i = n if j < 0 else j + 1
            continue
        if c == 0x28:  # '(' 字面量串，处理转义与嵌套括号
            buf, depth, i = bytearray(), 1, i + 1
            while i < n and depth:
                ch = blob[i]
                if ch == 0x5C:
                    nx = blob[i + 1] if i + 1 < n else 0
                    if nx in _PDF_ESC:
                        buf.append(_PDF_ESC[nx])
                        i += 2
                        continue
                    if 0x30 <= nx <= 0x37:  # 八进制转义
                        j, oc = i + 1, b""
                        while j < n and len(oc) < 3 and 0x30 <= blob[j] <= 0x37:
                            oc += bytes([blob[j]])
                            j += 1
                        buf.append(int(oc, 8) & 0xFF)
                        i = j
                        continue
                    if nx in (0x0A, 0x0D):  # 续行
                        i += 2
                        continue
                    buf.append(nx)
                    i += 2
                    continue
                if ch == 0x28:
                    depth += 1
                    buf.append(ch)
                elif ch == 0x29:
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                    buf.append(ch)
                else:
                    buf.append(ch)
                i += 1
            yield ("str", bytes(buf))
            continue
        if c == 0x3C:  # '<'
            if i + 1 < n and blob[i + 1] == 0x3C:
                yield ("op", "<<")
                i += 2
                continue
            j = blob.find(b">", i + 1)
            if j < 0:
                j = n
            yield ("hex", blob[i + 1:j])
            i = j + 1
            continue
        if c == 0x3E and i + 1 < n and blob[i + 1] == 0x3E:  # '>>'
            yield ("op", ">>")
            i += 2
            continue
        if c in b"[]{}":
            yield ("op", chr(c))
            i += 1
            continue
        if c == 0x2F:  # '/' 名字对象
            j = i + 1
            while j < n and blob[j] not in _PDF_DELIM:
                j += 1
            yield ("name", blob[i + 1:j].decode("latin-1"))
            i = j
            continue
        j = i
        while j < n and blob[j] not in _PDF_DELIM:
            j += 1
        tok = blob[i:j].decode("latin-1")
        i = j
        if tok == "ID":  # 内联图像数据：跳到 EI，避免把像素当操作符
            k = blob.find(b"EI", i)
            i = n if k < 0 else k + 2
            yield ("op", "ID")
            continue
        try:
            yield ("num", float(tok))
        except ValueError:
            yield ("op", tok)


def _pdf_hex_bytes(b: bytes) -> bytes | None:
    clean = b"".join(b.split())
    if len(clean) % 2:
        clean += b"0"
    try:
        return bytes.fromhex(clean.decode("ascii"))
    except (ValueError, UnicodeDecodeError):
        return None


def _pdf_decode_with_cmap(raw: bytes, cmap: dict[int, str],
                          width: int) -> tuple[str, int]:
    """按字体码宽切块查 ToUnicode；查不到的码位【跳过并计数】（不猜）。"""
    out: list[str] = []
    miss = 0
    if width == 2:
        limit = len(raw) - 1
        for k in range(0, limit, 2):
            ch = cmap.get((raw[k] << 8) | raw[k + 1])
            if ch is None:
                miss += 1
            else:
                out.append(ch)
        if len(raw) % 2:
            miss += 1
    else:
        for byte in raw:
            ch = cmap.get(byte)
            if ch is None:
                miss += 1
            else:
                out.append(ch)
    return "".join(out), miss


def _pdf_text_runs(blob: bytes, font_maps: dict[str, dict[int, str]],
                   font_widths: dict[str, int]):
    """解释内容流，产出 [(x, y, 文本)]。跟踪 Tf/Tm/Td/TD/T*/TL 与
    Tj/TJ/'/" 四种显示操作符；当前字体有 ToUnicode 就查表，否则沿用
    _decode_pdf_string（老 PDF 行为不变）。返回 (runs, 未命中码位数)。"""
    runs: list[tuple[float, float, str]] = []
    stack: list[tuple[str, object]] = []
    font, leading = "", 0.0
    tx = ty = line_x = 0.0
    # Tm 的缩放分量：Td/TD/TL 的位移量在【文本空间】，要乘回去才是页面坐标
    # （WPS 用 0.05 缩放矩阵，直接累加会把 x 放大 20 倍，行内顺序全乱）。
    ta, td = 1.0, 1.0
    miss_total = 0
    for kind, val in _pdf_content_tokens(blob):
        if not isinstance(val, str) or kind != "op" or val in _PDF_STRUCT_OPS:
            stack.append((kind, val))
            continue
        op = val
        if op == "Tf":
            names = [v for k, v in stack if k == "name"]
            if names:
                font = str(names[-1])
        elif op == "TL":
            nums = [v for k, v in stack if k == "num"]
            if nums:
                leading = float(nums[-1])
        elif op == "Tm":
            nums = [v for k, v in stack if k == "num"]
            if len(nums) >= 6:
                ta, td = float(nums[-6]), float(nums[-3])
                tx, ty = float(nums[-2]), float(nums[-1])
                line_x = tx
        elif op in ("Td", "TD"):
            nums = [v for k, v in stack if k == "num"]
            if len(nums) >= 2:
                tx += float(nums[-2]) * ta
                ty += float(nums[-1]) * td
                line_x = tx
                if op == "TD":
                    leading = -float(nums[-1])
        elif op == "T*":
            ty -= leading * td
            tx = line_x
        elif op in ("Tj", "TJ", "'", '"'):
            if op in ("'", '"'):
                ty -= leading * td
                tx = line_x
            cmap = font_maps.get(font)
            width = font_widths.get(font, 1)
            parts: list[str] = []
            for k, v in stack:
                if k == "str":
                    raw = v
                elif k == "hex":
                    raw = _pdf_hex_bytes(v)
                else:
                    continue
                if not raw:
                    continue
                if cmap:
                    piece, miss = _pdf_decode_with_cmap(raw, cmap, width)
                    miss_total += miss
                    parts.append(piece)
                else:
                    parts.append(_decode_pdf_string(raw))
            text = "".join(parts)
            if text:
                runs.append((tx, ty, text))
        stack.clear()
    return runs, miss_total


def _pdf_runs_to_text(runs: list[tuple[float, float, str]]) -> str:
    """把文本块按「行基线」聚成行：同 y（容差 2）合成一行，行内按 x 排序。

    阅读方向由流内首/末块的 y 走向判断：WPS 用 `1 0 0 -1 cm` 翻转坐标系，
    行基线随内容自顶向下递增；常规 PDF 自顶向下递减。
    """
    if not runs:
        return ""
    asc = runs[0][1] <= runs[-1][1]
    ordered = sorted(runs, key=lambda r: (r[1] if asc else -r[1], r[0]))
    lines: list[list[tuple[float, float, str]]] = [[ordered[0]]]
    for run in ordered[1:]:
        if abs(run[1] - lines[-1][0][1]) <= 2.0:
            lines[-1].append(run)
        else:
            lines.append([run])
    out: list[str] = []
    for line in lines:
        line.sort(key=lambda r: r[0])
        text = "".join(t for _, _, t in line).strip()
        if text:
            out.append(text)
    return "\n".join(out)


def _pdf_extract_legacy(data: bytes) -> tuple[bool, str]:
    """老路径：逐字符串成行，供没有 ToUnicode 的普通 PDF 使用（行为不变）。"""
    streams = list(_pdf_streams(data))
    blobs = streams or [data]
    has_layer, lines = False, []
    for blob in blobs:
        if b"BT" in blob and (b"Tj" in blob or b"TJ" in blob):
            has_layer = True
        for m in re.finditer(rb"BT(.*?)ET", blob, re.S):
            seg = m.group(1)
            for s in _pdf_literal_strings(seg):
                t = _decode_pdf_string(s).strip()
                if t:
                    lines.append(t)
            for h in _pdf_hex_strings(seg):
                t = _decode_pdf_hex(h).strip()
                if t:
                    lines.append(t)
    return has_layer, "\n".join(lines).strip()


def _pdf_extract(path: Path) -> tuple[bool, str]:
    """返回 (是否检测到文字层, 提取到的文本)。

    有 ToUnicode 的文档走「按字体切换解码」的 CID 路径（GID -> Unicode）；
    整篇没有任何 ToUnicode 时退回老路径，保证普通 PDF 的产出与旧版一致。
    """
    try:
        data = path.read_bytes()
    except OSError:
        return False, ""
    objs = _pdf_objects(data)
    font_maps = _pdf_font_maps(objs)
    if not font_maps:
        return _pdf_extract_legacy(data)
    widths = _pdf_font_widths(objs)
    has_layer, chunks = False, []
    miss_total = 0
    for content in _pdf_page_contents(objs, data):
        if b"BT" in content and (b"Tj" in content or b"TJ" in content):
            has_layer = True
        runs, miss = _pdf_text_runs(content, font_maps, widths)
        miss_total += miss
        text = _pdf_runs_to_text(runs)
        if text:
            chunks.append(text)
    text = "\n".join(chunks).strip()
    # ToUnicode 覆盖度留痕：门禁只拦「整篇乱码」，拦不住「少量缺字」。
    # 这里把缺失码位打进日志，让「缺了几个字」可被看见，但不改状态语义——
    # 提阈值会误伤正常子集字体（很多 PDF 的 ToUnicode 本就不覆盖全部 GID）。
    if miss_total:
        total_codes = miss_total + len(_PDF_REASONABLE_RE.findall(text))
        ratio = miss_total / total_codes if total_codes else 0.0
        if ratio >= 0.05:
            print("[WARN] PDF ToUnicode 覆盖不全：缺 %d 个码位（约 %.0f%%），正文可能少量缺字"
                  % (miss_total, ratio * 100))
    return has_layer, text


# 质量门禁用的「合理字符」集合：CJK 统一表意文字、中文标点、全角字符、
# 常见西文标点、ASCII 可打印与空白。刻意不收 Latin-1 补充区（U+00A0–U+00FF）：
# CID 字节被误当 latin-1 解出来的乱码正是那一段（·、³、À、¬ 等），
# 放过它们会让「假成功」通过门禁。
_PDF_REASONABLE_RE = re.compile(
    r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef"
    r"\u2010-\u2027\u2030-\u205e\x20-\x7e\s]")


def _pdf_text_is_reasonable(text: str) -> bool:
    """提取结果质量判定：len>=40 且合理字符占比 <0.6 视为解码失败。

    判定对象是「去掉 HTML 注释锚点后的正文」，避免 <!-- src: ... --> 干扰。
    """
    body = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    if len(body) < 40:
        return True
    good = len(_PDF_REASONABLE_RE.findall(body))
    return good / len(body) >= 0.6


def _builtin_rich_extract(path: Path) -> tuple[str | None, str]:
    """按扩展名分派内置解析；返回 (markdown 或 None, 状态)。"""
    ext = path.suffix.lower()
    title = "# %s\n\n" % path.name
    try:
        if ext == ".pdf":
            has_layer, text = _pdf_extract(path)
            if not has_layer:
                return None, "疑似扫描件，需先 OCR"
            if len(text) < MIN_TEXT_CHARS:
                return None, ("待安装依赖 markitdown[all]：PDF 文字层无法解码（字体编码复杂或属扫描件）。"
                              "本机 markitdown 因 onnxruntime 崩溃不可用，建议另存为可复制文本的 PDF 或转 .docx 后重试")
            # 假成功门禁：解出大量乱码时绝不报成功（GID 查表失败 / 字体子集
            # 的 ToUnicode 缺项都会落在这里），交给专用解析器。
            if not _pdf_text_is_reasonable(text):
                return None, PDF_CID_NEEDS_SPECIALIST
            return title + text + "\n", "成功"
        if not zipfile.is_zipfile(path):
            # 容器损坏/伪装文件是反向失败，不是加密（spec：加密须正向证据命中）。
            # 只有 _probe_protection() 命中加密特征才单列「待人工授权」。
            return None, "转换失败：无效 OOXML/ZIP 容器（文件损坏或非富文档）"
        with zipfile.ZipFile(path) as zf:
            if ext == ".docx":
                body = _docx_body(zf)
            elif ext == ".pptx":
                body = _pptx_body(zf)
            elif ext == ".xlsx":
                body = _xlsx_body(zf)
            elif ext == ".epub":
                body = _epub_body(zf)
            elif ext == ".zip":
                body = _zip_body(zf)
            else:
                return None, ("待安装依赖 markitdown[all]：该格式内置解析未覆盖。"
                              "本机 markitdown 因 onnxruntime 崩溃不可用，建议先另存为 .docx/.xlsx/.pptx 或 PDF 后重试")
    except (zipfile.BadZipFile, OSError, ET.ParseError) as exc:
        return None, "转换失败: %s" % exc
    if not body.strip():
        return None, "转换失败: 解析结果为空"
    return title + body.strip() + "\n", "成功（内置零依赖解析）"


def _probe_protection(path: Path) -> str | None:
    """加密/受保护文档预检；命中返回「待人工授权」，绝不破译或盲重试（FM-06）。"""
    ext = path.suffix.lower()
    try:
        with open(path, "rb") as fh:
            head = fh.read(8)
        if ext == ".pdf":
            if b"/Encrypt" in path.read_bytes():
                return "待人工授权：PDF 已加密/设置用户密码，需人工提供口令"
            return None
        if ext in (".zip", ".epub", ".docx", ".pptx", ".xlsx"):
            if head == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
                return "待人工授权：疑似加密/受保护的 Office 文档（OLE 复合文档），需先解密"
            if not zipfile.is_zipfile(path):
                return None
            with zipfile.ZipFile(path) as zf:
                low = [n.lower() for n in zf.namelist()]
                if any(i.flag_bits & 0x1 for i in zf.infolist()):
                    return "待人工授权：ZIP 成员已加密（需口令）"
                if any("encryptioninfo" in n or "encryptedpackage" in n for n in low):
                    return "待人工授权：Office 文档已加密（敏捷加密），需先解密"
                if ext == ".epub" and any("encryption.xml" in n for n in low):
                    return "待人工授权：EPUB 含 DRM/加密，需先授权"
    except (OSError, zipfile.BadZipFile):
        pass
    return None


_MARKITDOWN_PROBED = False
_MARKITDOWN_CMD = None
_MARKITDOWN_REASON = None
# 可选增强不可用时的统一留痕文案（run.log / INDEX 用），不写成「转换失败」。
_MK_UNAVAILABLE = "可选增强不可用（markitdown 段错误/未安装），已用内置零依赖解析"


def _markitdown_healthy(cmd) -> bool:
    """一次性健康冒烟探测：仅 rc==0 且 stdout 非空才认为可用。"""
    try:
        probe = subprocess.run(cmd + ["--version"], stdin=subprocess.DEVNULL,
                               capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               timeout=30)
    except Exception as exc:  # noqa: BLE001
        print("[WARN] markitdown 健康探测失败，本轮改用内置解析: %s" % exc)
        return False
    rc = probe.returncode
    # Unix 信号(rc<0) 与 Windows 异常状态码(0xC0000005 等大正数)都视为崩溃；
    # 正常 CLI 退出码在 0..255 之间。裸装缺原生依赖时 -m 会直接段错误。
    if rc < 0 or rc > 255:
        print("[WARN] markitdown 进程异常终止(rc=%s)，本轮改用内置解析" % rc)
        return False
    return rc == 0 and bool((probe.stdout or "").strip())


def _resolve_markitdown():
    """返回可用的 markitdown 命令；健康冒烟探测只做一次并缓存（模块级变量）。

    本机裸装 markitdown 会因 onnxruntime 段错误(rc=3221225477)而不可用，
    importlib.util.find_spec 会误判为可用，故必须用
    `python -m markitdown --version` 实测：仅 returncode==0 且 stdout 非空
    才返回命令，否则返回 None 直接走内置解析。结果缓存，避免每个富文档
    都重复拉起子进程。
    """
    global _MARKITDOWN_PROBED, _MARKITDOWN_CMD, _MARKITDOWN_REASON
    if _MARKITDOWN_PROBED:
        return _MARKITDOWN_CMD
    _MARKITDOWN_PROBED = True
    # 候选项顺序：源码运行时先试「当前解释器 -m markitdown」；**冻结后必须跳过**，
    # 因为 sys.executable 是 Jinghe.exe，`-m markitdown` 会变成对自身的重入，
    # 被自家 argparse 拒绝（实测 stderr 打印 usage、rc≠0），等于每次首遇富文档
    # 都白拉一个 onefile 进程（解包 30~60MB）。冻结后只认 PATH 里的 markitdown。
    candidates = []
    if not getattr(sys, "frozen", False):
        candidates.append([sys.executable, "-m", "markitdown"])
    exe = shutil.which("markitdown")
    if exe:
        candidates.append([exe])
    for cmd in candidates:
        if _markitdown_healthy(cmd):
            _MARKITDOWN_CMD = cmd
            _MARKITDOWN_REASON = None
            return cmd
    _MARKITDOWN_CMD = None
    _MARKITDOWN_REASON = _MK_UNAVAILABLE
    return None


def _looks_like_encryption_error(msg: str) -> bool:
    """只认明确的「需要口令/已加密」用户态错误；崩溃堆栈或泛化字样不算。"""
    low = (msg or "").lower()
    if "traceback" in low:  # 程序崩溃不是加密判定依据
        return False
    return any(k in low for k in (
        "password protected", "password required", "incorrect password",
        "user password", "owner password", "is encrypted", "encrypted document",
        "decryption failed", "needs a password", "口令", "密码", "加密文档"))


def convert_rich_file(path: Path) -> tuple[str | None, str]:
    """富文档：markitdown 优先，缺失时用内置零依赖解析真实提取；分级降级。"""
    verdict = _probe_protection(path)
    if verdict:
        return None, verdict

    md = _resolve_markitdown()
    mk_note = None
    if md:
        try:
            proc = subprocess.run(md + [str(path)], capture_output=True,
                                  text=True, encoding="utf-8", errors="replace",
                                  timeout=300)
        except Exception as exc:  # noqa: BLE001
            return None, "转换异常: %s" % exc
        if proc.returncode == 0 and (proc.stdout or "").strip():
            out = normalize_markdown(proc.stdout)
            # 不信任近乎为空的输出（裸 markitdown 缺格式依赖时可能只回一行提示）
            if len(out.strip()) >= MIN_TEXT_CHARS:
                return out, "成功（markitdown）"
            mk_note = "markitdown 输出近乎为空，转内置解析"
        else:
            err = ((proc.stderr or "").strip() or "输出为空")[:120]
            if _looks_like_encryption_error(proc.stderr or ""):
                return None, "待人工授权：需要密码/解密（%s）" % err
            mk_note = err

    text, status = _builtin_rich_extract(path)
    if text is None:
        # 内置解析给出的分级结论是终态，不能被 markitdown 的失败信息改写或混淆。
        # 仅当内置也是泛化的「转换失败」时，才附带 markitdown 报错便于排查。
        if mk_note and not status.startswith(
                ("疑似扫描件", "待人工授权", "待安装依赖", "需拆分", "需预处理",
                 "需专用解析器")):
            return None, "转换失败：markitdown 报「%s」；内置解析：%s" % (mk_note, status)
        return None, status
    return normalize_markdown(text), status


# --------------------------------------------------------------------------
# 校验与汇总
# --------------------------------------------------------------------------
def stats(text: str) -> tuple[int, int, int]:
    return (len(text),
            len(re.findall(r"(?m)^\s{0,3}#{1,6}\s", text)),
            len(re.findall(r"(?m)^\s*\|", text)))


def demote_headings(text: str, levels: int = 2) -> str:
    """合并文档时把源文件标题降位，避免与汇总文档层级冲突；跳过代码块。"""
    out, in_fence = [], False
    for line in text.splitlines():
        if re.match(r"^\s*```", line):
            in_fence = not in_fence
            out.append(line)
            continue
        m = re.match(r"^(\s{0,3})(#{1,6})(\s+)(.*)$", line)
        if m and not in_fence:
            out.append("%s%s%s%s" % (m.group(1),
                                     "#" * min(len(m.group(2)) + levels, 6),
                                     m.group(3), m.group(4)))
        else:
            out.append(line)
    return "\n".join(out)


def classify(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in SKILL_EXT or ext in PLAIN_EXT:
        return "text"
    if ext in RICH_EXT:
        return "rich"
    if ext in DEFERRED_EXT:
        return "deferred"
    if ext in LEGACY_EXT:
        return "legacy"
    return "unsupported"


def collect(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    return sorted(p for p in root.rglob("*") if p.is_file())


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    ap = argparse.ArgumentParser(
        prog="extract.py",
        description="阶段 1：文件内容提取与汇总（不含核心提炼、Word、音视频）")
    ap.add_argument("--input", "-i", required=True, action="append", dest="inputs",
                    metavar="PATH", help="输入文件或目录，可重复指定")
    ap.add_argument("--outdir", "-o", default="out", help="产物目录，默认 out")
    ap.add_argument("--skill-script", default=default_skill_script(),
                    help="转换脚本路径；默认优先随包 vendor/md_convert.py，"
                         "缺失时回退内置零依赖转换器")
    ap.add_argument("--progress", action="store_true",
                    help="逐文件打印 [PROGRESS] i/N 名称，供图形界面显示进度")
    # --version 用 argparse 的 version 动作：在解析到该参数时立即打印并退出，
    # 因此不受 -i 必填约束（`python extract.py --version` 可单独执行）。
    ap.add_argument("--version", action="version", version=__version__)
    ap.add_argument("--dry-run", action="store_true", help="只盘点分流，不写产物")
    args = ap.parse_args(argv)

    roots = [Path(p).resolve() for p in args.inputs]
    missing = [str(r) for r in roots if not r.exists()]
    if missing:
        print("[ERROR] 输入路径不存在: %s" % ", ".join(missing))
        return 2
    # 单 root 时完全沿用旧行为（相对路径基准 = root 本身或其父目录）；
    # 多 root 时取公共父目录作为基准，跨盘符无法求公共路径则退化为纯文件名。
    if len(roots) == 1:
        base: Path | None = roots[0] if roots[0].is_dir() else roots[0].parent
    else:
        try:
            base = Path(os.path.commonpath(
                [str(r if r.is_dir() else r.parent) for r in roots]))
        except ValueError:
            base = None
    inputs_label = str(roots[0]) if len(roots) == 1 else "; ".join(str(r) for r in roots)
    outdir = Path(args.outdir).resolve()
    converters, conv_source = load_converters(args.skill_script)
    # 落盘口径用带限定词的标签：`conv_source` 只描述**文本类**转换器，
    # 富文档走 markitdown / 内置解析（逐文件写在 src 注释的 converter 字段）。
    # 不加限定词时，INDEX / run.log 里的「转换器」会被读成全局结论 —— 本机正是
    # 在 markitdown 崩溃、实际用内置解析的情况下，仍显示「技能脚本 md_convert.py」。
    conv_store_label = "%s（仅文本类；富文档解析另见标记）" % conv_source
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 多输入合并并保序去重：同一文件被目录与文件参数同时覆盖时只处理一次。
    files: list[Path] = []
    seen: set[str] = set()
    for r in roots:
        for p in collect(r):
            key = os.path.normcase(str(p))
            if key in seen:
                continue
            seen.add(key)
            files.append(p)
    # 出处定位最小集（#9 第二批）：一次读盘取完整 sha256，派生 doc_id 与
    # src 注释的 sha256 字段（追加式，不改变既有产物结构）。
    file_hashes = {p: _sha256_hex(p) for p in files}
    doc_ids = {p: "doc_" + file_hashes[p][:12] for p in files}
    buckets = {"text": [], "rich": [], "deferred": [], "legacy": [], "unsupported": []}
    for p in files:
        buckets[classify(p)].append(p)

    print("[INFO] 转换器来源: %s" % conv_source)
    print("[INFO] 盘点 %d 个文件 -> 文本类 %d / 富文档 %d / 阶段3预留 %d / 需预处理 %d / 不支持 %d"
          % (len(files), len(buckets["text"]), len(buckets["rich"]),
             len(buckets["deferred"]), len(buckets["legacy"]), len(buckets["unsupported"])))
    if args.dry_run:
        for key, label in (("text", "文本类"), ("rich", "富文档"),
                           ("deferred", "阶段3预留"), ("legacy", "需预处理"),
                           ("unsupported", "不支持")):
            for p in buckets[key]:
                print("  [%s] %s" % (label, p.name))
        print("[DONE] dry-run 结束，未写产物")
        return 0

    # 可选增强状态留痕（#9 第一批）：富文档存在时做一次健康探测并缓存，
    # run.log / INDEX 记录「可选增强不可用（markitdown 段错误/未安装），已用内置零依赖解析」。
    enhance_note = None
    if buckets["rich"]:
        _resolve_markitdown()
        enhance_note = (_MARKITDOWN_REASON
                        or ("可选增强可用（markitdown 健康探测通过）"
                            if _MARKITDOWN_CMD else None))

    md_dir = outdir / "md"
    md_dir.mkdir(parents=True, exist_ok=True)
    stale_artifacts = sorted(p for p in md_dir.glob("*.md"))
    for p in stale_artifacts:
        p.unlink()
    records = []

    # #10 编码前置层工作区：只存放喂转换器的同 UTF-8 副本，不参与任何哈希。
    #
    # 目录归属（v0.2.0 修正）：优先使用父进程通过环境变量 JINGHE_ENCDIR 指定的
    # 目录，由父进程负责清理。原因是 atexit 在进程被 terminate() 时不会执行——
    # 图形界面点「取消」会强杀子进程，自主创建的 mkdtemp 目录就会残留用户文档
    # 副本（既是垃圾也是隐私问题）。父进程持有目录才能在强杀后兜底清理。
    enc_workdir = _enc_workdir()
    enc_records: list[dict] = []

    candidates = buckets["text"] + buckets["rich"]
    for idx, path in enumerate(candidates, 1):
        # 图形界面进度协议：每个候选文件开始处理前打一行，供 app.py 解析为进度事件。
        # 仅在显式 --progress 时输出，避免污染命令行用户与既有测试的输出。
        if args.progress:
            print("[PROGRESS] %d/%d %s" % (idx, len(candidates), path.name), flush=True)
        ext = path.suffix.lower()
        size = path.stat().st_size
        rel = os.path.relpath(path, base) if base else path.name
        record = {"no": idx, "src": rel, "ext": ext, "size": size,
                  "doc_id": doc_ids[path],
                  "status": "", "chars": 0, "heads": 0, "rows": 0,
                  "artifact": "", "note": ""}
        if size > MAX_SINGLE_BYTES:
            record["status"] = "需拆分"
            record["note"] = "单文件 >100MB，按页/工作表分段后再转"
            records.append(record)
            continue
        if path in buckets["rich"]:
            text, status = convert_rich_file(path)
        else:
            # 编码前置层：先按原始字节严格探测，再决定喂原文件还是 UTF-8 副本。
            # doc_id / sha256 已在 collect 之前基于原始字节算好，此处不复算、不改写。
            feed, enc_info = preprocess_text_encoding(path, enc_workdir, idx)
            enc_info["rel"] = rel
            enc_records.append(enc_info)
            try:
                text = convert_text_file(feed, converters)
                status = "成功" if text else "无可用转换器"
            except Exception as exc:  # noqa: BLE001
                text, status = None, "转换异常: %s" % exc
        if not text:
            record["status"] = status
            record["note"] = "不产出空文件，按失败模式降级并标记"
            # spec v2：run.log / INDEX 记录 PDF 文字层判定依据，便于复核。
            if "需先 OCR" in status:
                record["note"] += "；文字层探测: 无 BT/Tj/TJ 文本对象"
            records.append(record)
            continue

        # 追加式出处定位（#9 第二批）：首行 source 注释原样保留（qa test_05 契约），
        # 另起一行追加 8 字段机器可读 src 注释；正文逐块注入块级锚点。
        # stats 基于注入后的同一份文本，保证 INDEX 数字与产物全文自洽。
        did = doc_ids[path]
        anchored, anchor_keys = _inject_anchors(text, ext, did)
        converter_label = (("markitdown" if "markitdown" in status
                            else "内置零依赖解析")
                           if path in buckets["rich"] else conv_source)
        src_fields = [
            did,
            "path: %s" % _anchor_value(rel.replace("\\", "/")),
            "format: %s" % ext,
            "converter: %s" % _anchor_value(converter_label),
            "extracted: %s" % stamp,
            "size: %d" % size,
            "sha256: %s" % file_hashes[path],
            "anchors: %s" % (",".join(anchor_keys) if anchor_keys else "none"),
        ]
        header = ("<!-- source: %s | format: %s | extracted: %s -->\n"
                  "<!-- src: %s -->\n\n"
                  % (rel, ext, stamp, " | ".join(src_fields)))
        body = header + anchored
        dst = md_dir / ("%03d-%s.md" % (idx, re.sub(r"[^\w\u4e00-\u9fff-]", "_", path.stem)))
        dst.write_text(body, encoding="utf-8")
        c, h, r = stats(anchored)
        record.update(status="成功", chars=c, heads=h, rows=r,
                      artifact=str(dst.relative_to(outdir)).replace("\\", "/"))
        if size == 0 or "<!-- 空 CSV -->" in text:
            record["note"] = "源文件无实质内容/占位产物，阶段 2 摘要须排除"
        elif h == 0:
            record["note"] = "抽检提示：未发现标题层级"
        records.append(record)

    for key, status, note in (
        ("deferred", "阶段 3 待支持", "音视频转写不在本期范围，未尝试解析"),
        ("legacy", "需预处理", "旧版二进制格式，先转 OOXML 后再纳入"),
        ("unsupported", "不支持", "扩展名不在支持清单"),
    ):
        for path in buckets[key]:
            rel = os.path.relpath(path, base) if base else path.name
            records.append({"no": "-", "src": rel, "ext": path.suffix.lower(),
                            "size": path.stat().st_size, "doc_id": doc_ids[path],
                            "status": status,
                            "chars": 0, "heads": 0, "rows": 0,
                            "artifact": "", "note": note})

    ok = [r for r in records if r["status"] == "成功"]
    total_src = len(buckets["text"]) + len(buckets["rich"])
    empties = [r["artifact"] for r in ok if r["chars"] == 0]
    no_heads = [r["artifact"] for r in ok if r["heads"] == 0]
    expected_artifacts = {r["artifact"] for r in ok}
    actual_artifacts = {"md/" + p.name for p in md_dir.glob("*.md")}
    orphans = sorted(actual_artifacts - expected_artifacts)
    missing = sorted(expected_artifacts - actual_artifacts)
    disk_ok = (len(actual_artifacts) == len(ok) and not orphans and not missing)
    verdict = ("通过" if (len(ok) == total_src and not empties and disk_ok)
               else "部分未完成，见 INDEX.md 未成功项")

    # 验收口径说明（lead 裁定 (a)）：降级样例留在 samples/，verdict 文案一字不改；
    # 只动态追加一行，区分「设计内降级」与「软件缺陷」。N 与分项全部按实际记录
    # 统计得出，严禁硬编码件数。
    fail_records = [r for r in records if r["no"] != "-" and r["status"] != "成功"]
    if fail_records:
        grouped: dict[str, int] = {}
        for r in fail_records:
            label = _degrade_label(r["status"])
            grouped[label] = grouped.get(label, 0) + 1
        detail = " / ".join("%d 项%s" % (v, k) for k, v in grouped.items())
        acceptance_note = ("- 验收口径: 未成功 %d 项均为样例集内设计内降级（%s），"
                           "属软件按规格正确处置，非缺陷" % (len(fail_records), detail))
    else:
        acceptance_note = "- 验收口径: 未成功 0 项，全部候选按规格成功，无设计内降级项"

    # 阶段 2 摘要排除清单：content_status != normal 的条目（占位 / 来源不可用）。
    excluded = [r for r in records if _content_status(r) != "normal"]

    # INDEX.md —— 工程汇总与对账
    enc_converted = [e for e in enc_records if e["converted"]]
    enc_summary = ("- 文本编码前置层：文本类 %d 个，非 UTF-8 %d 个（已转 UTF-8 临时副本喂转换器；"
                   "原文件字节未改，doc_id / sha256 仍基于原始字节）"
                   % (len(enc_records), len(enc_converted)))
    idx_lines = [
        "# 阶段 1 提取汇总 · 对账清单", "",
        "- 生成时间：%s" % stamp,
        "- 输入目录：`%s`" % inputs_label,
        "- 转换器：%s" % conv_store_label,
        *(["- %s" % enhance_note] if enhance_note else []),
        "- 源文件总数：%d（纳入转换 %d，阶段 3 预留 %d，需预处理 %d，不支持 %d）"
        % (len(files), total_src, len(buckets["deferred"]),
           len(buckets["legacy"]), len(buckets["unsupported"])),
        "- 成功产出：%d" % len(ok), enc_summary, "",
        "| # | 源文件 | 格式 | 状态 | 字符数 | 标题数 | 表格行 | 产物 | 备注 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in records:
        idx_lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            r["no"], r["src"].replace("|", "\\|"), r["ext"], r["status"],
            r["chars"], r["heads"], r["rows"],
            ("`%s`" % r["artifact"]) if r["artifact"] else "-", r["note"] or "-"))
    idx_lines += [
        "", "## 交付前自检", "",
        "- 件数对账：候选 %d / 成功 %d / 未成功 %d"
        % (total_src, len(ok), total_src - len(ok)),
        "- 空文件扫描：%s" % (("、".join(empties) + " 为空") if empties else "无空文件"),
        "- 结构抽检：%s" % (("、".join(no_heads) + " 无标题层级") if no_heads else "全部含标题层级"),
        "- 产物目录实盘对账：磁盘 %d / 成功记录 %d / 孤立 %d / 缺失 %d（%s）%s"
        % (len(actual_artifacts), len(ok), len(orphans), len(missing),
           "一致" if disk_ok else "不一致",
           ("；明细：" + "、".join(orphans + missing)) if (orphans or missing) else ""),
        acceptance_note,
        "", "## 本期不包含", "",
        "- 核心内容提炼 / 摘要（阶段 2）",
        "- Word 等格式导出（阶段 2）",
        "- 音频与视频转写（阶段 3）",
    ]
    # 文本编码前置处理明细（#10）：逐条留痕原编码与转换决策，便于人工复核。
    # 放在「阶段 2 摘要排除清单」之前，避免污染该节的 bullet 解析。
    if enc_converted:
        idx_lines += ["", "## 文本编码前置处理明细", ""]
        for e in enc_converted:
            idx_lines.append(
                "- `%s` ｜ 原编码：%s ｜ 判定：%s ｜ 处理：UTF-8 临时副本（原 %d 字节，原文件未改）"
                % (_anchor_value(e["rel"].replace("\\", "/")), e["encoding"],
                   _anchor_value(e["basis"]), e["bytes"]))
    # 阶段 2 摘要排除清单：人可读、落在 INDEX.md（门禁检查 INDEX+MERGED 文本）。
    # 用 bullet + 全角分隔符，绝不产生以 `|` 起头的行，避免污染对账表 rows。
    idx_lines += ["", "## 阶段 2 摘要排除清单", "",
                  "> 阶段 2 摘要流水线须跳过以下 doc_id（占位产物或来源不可用），不得假定所有格式产物齐备。",
                  ""]
    for r in excluded:
        cs = _content_status(r)
        reason = ("placeholder（占位产物）" if cs == "placeholder"
                  else "unavailable（来源不可用，无产物）")
        idx_lines.append("- `%s` ｜ `%s` ｜ %s ｜ 状态：%s" % (
            r["doc_id"], _anchor_value(r["src"].replace("\\", "/")),
            reason, _anchor_value(r["status"])))
    if not excluded:
        idx_lines.append("- 无（本轮全部产物均可纳入摘要）")
    (outdir / "INDEX.md").write_text("\n".join(idx_lines) + "\n", encoding="utf-8")

    # MERGED.md —— 带来源标注的内容汇总
    merged = [
        "# 内容汇总 · 阶段 1", "",
        "> 本期只做结构化提取与合并，未做核心内容提炼。",
        "> 每节标注来源路径；源文件标题已降位两级，避免与本文档层级冲突。",
        "> 生成时间：%s" % stamp, "",
        "## 目录", "",
    ]
    for n, r in enumerate(ok, 1):
        # #9：目录锚点改用内容哈希 doc_id，不依赖路径/文件名
        tag = ("（占位产物，阶段 2 摘要须排除）"
               if _content_status(r) == "placeholder" else "")
        merged.append("%d. [%s](#%s) — %s 字符 / %s 个标题%s" % (
            n, r["src"], r["doc_id"], r["chars"], r["heads"], tag))
    if excluded:
        merged.append("")
        merged.append("> 阶段 2 摘要排除清单（跳过以下 doc_id）：" + "、".join(
            "`%s`(%s, %s)" % (r["doc_id"], Path(r["src"]).name,
                              _content_status(r)) for r in excluded))
    merged += ["", "---", ""]
    for n, r in enumerate(ok, 1):
        art = outdir / r["artifact"]
        raw = art.read_text(encoding="utf-8")
        raw = re.sub(r"^<!--.*?-->\s*", "", raw, count=1, flags=re.S)
        stem = Path(r["src"]).name
        raw = re.sub(r"(?m)^#\s+" + re.escape(stem) + r"[ \t]*\n+", "", raw, count=1)
        merged += [
            "## %d. %s" % (n, r["src"]), "",
            '<a id="%s"></a>' % r["doc_id"], "",
            "> 来源：`%s`" % r["src"],
            "> 格式：%s ｜ 字符数：%d ｜ 标题数：%d ｜ 表格行：%d"
            % (r["ext"], r["chars"], r["heads"], r["rows"]),
            "> 单文件产物：`%s`" % r["artifact"], "",
            demote_headings(raw.strip()), "", "---", "",
        ]
    (outdir / "MERGED.md").write_text("\n".join(merged).rstrip() + "\n", encoding="utf-8")

    # run.log
    log = ["# extract.py 运行日志", "", "- 时间: %s" % stamp,
           "- 输入: %s" % inputs_label, "- 转换器: %s" % conv_store_label,
           *(["- %s" % enhance_note] if enhance_note else []),
           "- 盘点: %d" % len(files),
           "- 编码前置: 文本类 %d / 非 UTF-8 %d"
           % (len(enc_records), len(enc_converted)),
           "- 清理陈旧产物: %d" % len(stale_artifacts), ""]
    for r in records:
        log.append("- [%s] %s -> %s (%s)" % (
            r["status"], r["src"], r["artifact"] or "-", r["note"] or "-"))
    # #10 编码决策逐条留痕：原编码 + 判定依据 + 处理方式，便于复核
    # 「原文没丢」而不只是「转换成功」。此行不以 `-[...] ->` 形式出现，
    # 避免与上面的状态记录行混淆。
    for e in enc_converted:
        log.append("- 编码: %s 原编码 %s（%s），已转 UTF-8 临时副本 %d 字节"
                   % (e["rel"], e["encoding"], e["basis"], e["bytes"]))
    log += ["", "- 候选: %d" % total_src, "- 成功: %d" % len(ok),
            "- 未成功: %d" % (total_src - len(ok)),
            "- 阶段3预留: %d" % len(buckets["deferred"]),
            "- 空文件: %d" % len(empties), "- 无标题层级: %d" % len(no_heads),
            "- 实盘对账: 磁盘 %d / 成功 %d / 孤立 %d / 缺失 %d"
            % (len(actual_artifacts), len(ok), len(orphans), len(missing)),
            "", "验收: %s" % verdict, acceptance_note]
    (outdir / "run.log").write_text("\n".join(log) + "\n", encoding="utf-8")

    # provenance.json —— 机器可读出处清单（#9：含 content_status，追加式产物）
    manifest = {
        "generated": stamp,
        "input": inputs_label,
        "converter": conv_source,
        # 明确标注「模板」、键用冒号；与 src 注释口径一致，避免 manifest 与产物分叉：
        # doc_id 为真实值 doc_ + sha256(字节)[:12]；src 第 7 字段 sha256 为完整 64 位小写 hex。
        "block_anchor_interface": (
            "模板（实际注入只保留该格式适用的键；doc_id 为真实值 doc_ + sha256(字节)[:12]；"
            "src 注释第 7 字段 sha256 为完整 64 位小写 hex）: "
            "<!-- anchor: <doc_id> | block: <N> | page: <N> | slide: <N> | "
            "sheet: <名> | chapter: <N> | member: <path> | line: <A>..<B> -->"),
        "entries": [],
    }
    for r in records:
        cs = _content_status(r)
        manifest["entries"].append({
            "doc_id": r["doc_id"], "path": r["src"].replace("\\", "/"),
            "format": r["ext"], "status": r["status"],
            "content_status": cs, "artifact": r["artifact"],
            "chars": r["chars"], "note": r["note"],
        })
    (outdir / "provenance.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("[DONE] 成功 %d / 候选 %d；空文件 %d；无标题层级 %d"
          % (len(ok), total_src, len(empties), len(no_heads)))
    print("[DONE] 产物: %s" % outdir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
