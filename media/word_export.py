#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精核 · .md → .docx 导出（S2b · 阶段 2 二期）。

本模块与冻结内核完全正交，**纯标准库**实现：

* ``zipfile`` 组装 OOXML 包，``xml.etree`` 只用于自检，不引入 python-docx
  或任何第三方库；LibreOffice / Word 都不需要安装，也不随 exe 分发。
* 输入只认 Markdown 文件（默认 ``MERGED.md``，其次 ``out/md/*.md``），
  **全部只读**；产物严格落 ``out/derived/<doc_id>.docx`` +
  ``provenance_media.json``。绝不写 ``out/md/`` / ``INDEX.md`` /
  ``MERGED.md`` / ``provenance.json``（契约 §4 / 不变量 7）。
* **出处不丢**：Markdown 里的 ``<!-- source: … -->``、8 字段 ``<!-- src: … -->``
  与块级 ``<!-- anchor: … -->`` 注释按原文渲染成 Word 的 ``SourceNote``
  段落，同时把 ``src`` 原文写入 ``docProps/core.xml`` 的 ``dc:description``。
  导出后仍可用 ``word_input.parse_ooxml()`` 反向读回，形成闭环。
* 诚实降级：文件不存在 / 非 md / 超上限 / 空白内容 / 写入失败一律
  ``ok:false`` + 可读原因，不落空 docx、不落半成品、不伪装成功；
  部分成功显式回 ``warning``。

端点由 ``app.py`` 后处理层挂 ``POST /api/word/export``；本模块不碰路由，
也不 import ``extract.py`` 的提取流水线，``SPEC.md`` 一字不改。
"""
from __future__ import annotations

import io
import re
import time
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import format_registry
import media_runtime

# --------------------------------------------------------------------------- #
# 常量与安全上限
# --------------------------------------------------------------------------- #
MAX_BYTES = 8 * 1024 * 1024         # 单个 md 上限，超限拒绝解析
MAX_LINES = 20000                   # 行数上限，避免超大文档卡死 UI
MAX_AUTO_INPUTS = 20                # 未显式给 inputs 时，最多自动收 20 个 md
CONVERTER_LABEL = "精核 MD→DOCX 导出 v1（标准库 zipfile+ElementTree）"
SCHEMA_NOTE = "S2b 导出产物；不参与阶段 1 件数对账"

STATUS_OK = "成功"
STATUS_UNSUPPORTED = "不支持"
STATUS_FAILED = "失败"

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_XML_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
_ILLEGAL_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")
_INLINE_RE = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`|~~[^~]+~~|\*[^*]+\*)")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_LIST_RE = re.compile(r"^(\s*)([-*+]|\d+\.)\s+(.*)$")
_QUOTE_RE = re.compile(r"^>\s?(.*)$")
_COMMENT_RE = re.compile(r"<!--(.*?)-->", re.S)
_HR_RE = re.compile(r"^(?:-{3,}|\*{3,}|_{3,})$")
_SEP_RE = re.compile(r"^:?-{3,}:?$")
_CELL_SPLIT_RE = re.compile(r"(?<!\\)\|")


def _esc(text) -> str:
    """XML 文本转义 + 剔除 XML 1.0 非法控制字符（否则 Word 会拒绝打开）。"""
    cleaned = _ILLEGAL_XML.sub("", str(text))
    return escape(cleaned, {'"': "&quot;", "'": "&apos;"})


def _utc_stamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _local_stamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def capability() -> dict:
    """S2b 能力状态。

    与 S2a 同样刻意放在本模块、作为 ``/api/tools/probe`` 的**顶层增量字段**：
    S1 契约测试锁死了 ``media_tools.capabilities()`` 全部未启用与「3 个工具」，
    S2b 绝不改写那些结构。纯标准库实现，因此恒可用、无外部工具依赖。
    """
    return {
        "name": "word_export",
        "enabled": True,
        "engine": {
            "name": "标准库 zipfile + ElementTree",
            "reason": "OOXML 由标准库生成，无需安装 Word / LibreOffice",
        },
        "input": {
            "exts": sorted(format_registry.WORD_EXPORT_INPUT_EXTS),
            "default": "MERGED.md 优先（只读），其次 out/md/*.md",
        },
        "output": {
            "dirname": media_runtime.DERIVED_DIRNAME,
            "suffix": format_registry.WORD_EXPORT_SUFFIX,
        },
        "note": "来源注释与块级锚点按原文保留；产物落 out/derived/，不写阶段 1 对账盘",
    }


# --------------------------------------------------------------------------- #
# WordprocessingML 片段生成
# --------------------------------------------------------------------------- #
def _run(text: str, *, bold=False, italic=False, mono=False,
         strike=False, color="", size="") -> str:
    props = []
    if bold:
        props.append("<w:b/>")
    if italic:
        props.append("<w:i/>")
    if strike:
        props.append("<w:strike/>")
    if mono:
        props.append('<w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" '
                     'w:eastAsia="Microsoft YaHei"/>')
    if color:
        props.append('<w:color w:val="%s"/>' % color)
    if size:
        props.append('<w:sz w:val="%s"/>' % size)
    rpr = "<w:rPr>%s</w:rPr>" % "".join(props) if props else ""
    return ("<w:r>%s<w:t xml:space=\"preserve\">%s</w:t></w:r>"
            % (rpr, _esc(text)))


def _runs(text: str) -> str:
    """轻量行内格式：**粗体** / *斜体* / `等宽` / ~~删除线~~。"""
    pieces = []
    pos = 0
    for match in _INLINE_RE.finditer(text):
        if match.start() > pos:
            pieces.append(_run(text[pos:match.start()]))
        token = match.group(0)
        if token.startswith("**"):
            pieces.append(_run(token[2:-2], bold=True))
        elif token.startswith("`"):
            pieces.append(_run(token[1:-1], mono=True))
        elif token.startswith("~~"):
            pieces.append(_run(token[2:-2], strike=True))
        else:
            pieces.append(_run(token[1:-1], italic=True))
        pos = match.end()
    if pos < len(text):
        pieces.append(_run(text[pos:]))
    return "".join(pieces) or _run("")


def _para(runs_xml: str, style: str = "", *, border=False) -> str:
    props = []
    if style:
        props.append('<w:pStyle w:val="%s"/>' % _esc(style))
    if border:
        props.append('<w:pBdr><w:bottom w:val="single" w:sz="6" '
                     'w:space="1" w:color="BBBBBB"/></w:pBdr>')
    ppr = "<w:pPr>%s</w:pPr>" % "".join(props) if props else ""
    return "<w:p>%s%s</w:p>" % (ppr, runs_xml)


def _table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    grid = "".join('<w:gridCol w:w="%d"/>' % (9000 // width) for _ in range(width))
    borders = "".join(
        '<w:%s w:val="single" w:sz="4" w:space="0" w:color="999999"/>' % side
        for side in ("top", "left", "bottom", "right", "insideH", "insideV"))
    body = []
    for row in rows:
        cells = []
        for cell in row:
            cells.append(
                '<w:tc><w:tcPr><w:tcW w:w="%d" w:type="dxa"/></w:tcPr>%s</w:tc>'
                % (9000 // width, _para(_runs(cell.replace("\\|", "|")))))
        body.append("<w:tr>%s</w:tr>" % "".join(cells))
    return ("<w:tbl><w:tblPr><w:tblW w:w=\"9000\" w:type=\"dxa\"/>"
            "<w:tblBorders>%s</w:tblBorders></w:tblPr>"
            "<w:tblGrid>%s</w:tblGrid>%s</w:tbl>"
            % (borders, grid, "".join(body)))


# --------------------------------------------------------------------------- #
# Markdown → 块序列
# --------------------------------------------------------------------------- #
def _cells(line: str) -> list[str]:
    return [c.strip() for c in _CELL_SPLIT_RE.split(line.strip().strip("|"))]


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(_SEP_RE.match(c) for c in cells)


def parse_markdown(text: str) -> list[dict]:
    """把 Markdown 切成有序块；不追求完整 CommonMark，覆盖产物实际用到的语法。"""
    lines = text.splitlines()
    blocks: list[dict] = []
    code: list[str] = []
    table: list[list[str]] = []
    in_code = False

    def flush_table():
        nonlocal table
        if table:
            blocks.append({"kind": "table", "rows": table})
            table = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            flush_table()
            if in_code:
                blocks.append({"kind": "code", "text": "\n".join(code)})
                code = []
                in_code = False
            else:
                in_code = True
            continue
        if in_code:
            code.append(line)
            continue
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = _cells(stripped)
            if not _is_separator(cells):
                table.append(cells)
            continue
        flush_table()
        if not stripped:
            continue
        if _COMMENT_RE.fullmatch(stripped):
            blocks.append({"kind": "comment", "text": stripped})
            continue
        if _HR_RE.match(stripped):
            blocks.append({"kind": "hr"})
            continue
        heading = _HEADING_RE.match(line)
        if heading:
            blocks.append({"kind": "heading", "level": len(heading.group(1)),
                           "text": heading.group(2)})
            continue
        quote = _QUOTE_RE.match(line)
        if quote:
            blocks.append({"kind": "quote", "text": quote.group(1)})
            continue
        item = _LIST_RE.match(line)
        if item:
            marker, body = item.group(2), item.group(3)
            prefix = (marker + " ") if marker[0].isdigit() else "• "
            blocks.append({"kind": "list", "text": prefix + body})
            continue
        blocks.append({"kind": "para", "text": line})
    if in_code and code:
        blocks.append({"kind": "code", "text": "\n".join(code)})
    flush_table()
    return blocks


def _blocks_to_xml(blocks: list[dict]) -> str:
    out = []
    for block in blocks:
        kind = block["kind"]
        if kind == "heading":
            out.append(_para(_runs(block["text"]),
                             "Heading%d" % min(block["level"], 6)))
        elif kind == "para":
            out.append(_para(_runs(block["text"])))
        elif kind == "list":
            out.append(_para(_runs(block["text"]), "ListParagraph"))
        elif kind == "quote":
            out.append(_para(_runs(block["text"]), "Quote"))
        elif kind == "code":
            for line in block["text"].split("\n"):
                out.append(_para(_run(line, mono=True, size="19"), "CodeBlock"))
        elif kind == "hr":
            out.append(_para(_run(""), border=True))
        elif kind == "comment":
            # 关键：来源注释与块级锚点按原文渲染，绝不丢弃（契约 §4 / 不变量 8）
            out.append(_para(_run(block["text"], mono=True,
                                  color="808080", size="16"), "SourceNote"))
        elif kind == "table":
            out.append(_table(block["rows"]))
    # OOXML 要求 body 以段落收尾（表格之后不能直接接 sectPr）。
    out.append("<w:p/>")
    return "".join(out)


# --------------------------------------------------------------------------- #
# OOXML 包部件
# --------------------------------------------------------------------------- #
_CONTENT_TYPES = (
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
    '<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>'
    '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
    '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
    '</Types>'
)

_ROOT_RELS = (
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
    '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
    '</Relationships>'
)

_DOC_RELS = (
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/>'
    '</Relationships>'
)

_SETTINGS = ('<w:settings xmlns:w="%s"><w:zoom w:percent="100"/>'
             '<w:defaultTabStop w:val="420"/></w:settings>' % W)

_APP = ('<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
        '<Application>精核 MD to DOCX exporter</Application><AppVersion>1.0</AppVersion>'
        '</Properties>')


def _styles_xml() -> str:
    styles = [
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
        '<w:name w:val="Normal"/><w:qFormat/></w:style>'
    ]
    for level, size in enumerate((32, 28, 26, 24, 22, 20), 1):
        styles.append(
            '<w:style w:type="paragraph" w:styleId="Heading%d">'
            '<w:name w:val="heading %d"/><w:basedOn w:val="Normal"/>'
            '<w:next w:val="Normal"/><w:qFormat/>'
            '<w:pPr><w:keepNext/><w:spacing w:before="240" w:after="120"/>'
            '<w:outlineLvl w:val="%d"/></w:pPr>'
            '<w:rPr><w:b/><w:sz w:val="%d"/></w:rPr></w:style>'
            % (level, level, level - 1, size))
    styles += [
        '<w:style w:type="paragraph" w:styleId="ListParagraph">'
        '<w:name w:val="List Paragraph"/><w:basedOn w:val="Normal"/>'
        '<w:pPr><w:ind w:left="480"/></w:pPr></w:style>',
        '<w:style w:type="paragraph" w:styleId="Quote">'
        '<w:name w:val="Quote"/><w:basedOn w:val="Normal"/>'
        '<w:pPr><w:ind w:left="480"/></w:pPr>'
        '<w:rPr><w:i/><w:color w:val="555555"/></w:rPr></w:style>',
        '<w:style w:type="paragraph" w:styleId="CodeBlock">'
        '<w:name w:val="Code Block"/><w:basedOn w:val="Normal"/>'
        '<w:pPr><w:shd w:val="clear" w:fill="F4F4F2"/><w:spacing w:after="0"/></w:pPr>'
        '<w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" '
        'w:eastAsia="Microsoft YaHei"/></w:rPr></w:style>',
        '<w:style w:type="paragraph" w:styleId="SourceNote">'
        '<w:name w:val="Source Note"/><w:basedOn w:val="Normal"/>'
        '<w:pPr><w:spacing w:after="0"/></w:pPr>'
        '<w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" '
        'w:eastAsia="Microsoft YaHei"/><w:color w:val="808080"/>'
        '<w:sz w:val="16"/></w:rPr></w:style>',
    ]
    defaults = (
        '<w:docDefaults><w:rPrDefault><w:rPr>'
        '<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="Microsoft YaHei"/>'
        '<w:sz w:val="21"/><w:szCs w:val="21"/>'
        '</w:rPr></w:rPrDefault><w:pPrDefault><w:pPr>'
        '<w:spacing w:after="120" w:line="276" w:lineRule="auto"/>'
        '</w:pPr></w:pPrDefault></w:docDefaults>')
    return ('<w:styles xmlns:w="%s">%s%s</w:styles>'
            % (W, defaults, "".join(styles)))


def _core_xml(title: str, description: str) -> str:
    return (
        '<cp:coreProperties '
        'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        '<dc:title>%s</dc:title><dc:creator>精核</dc:creator>'
        '<cp:lastModifiedBy>精核</cp:lastModifiedBy>'
        '<dcterms:created xsi:type="dcterms:W3CDTF">%s</dcterms:created>'
        '<dc:description>%s</dc:description></cp:coreProperties>'
        % (_esc(title), _utc_stamp(), _esc(description)))


def _document_xml(md_text: str, src: Path, info: dict) -> str:
    blocks = parse_markdown(md_text)
    comments = _COMMENT_RE.findall(md_text)
    src_line = next((c.strip() for c in comments if "src:" in c), "")
    intro = [
        _para(_run("导出信息 · 精核 .md → .docx"), "Heading1"),
        _para(_run("源文件：" + src.name)),
        _para(_run("doc_id：" + info["doc_id"])),
        _para(_run("sha256：" + info["sha256"])),
        _para(_run("大小：%d 字节" % info["size"])),
        _para(_run("转换器：" + CONVERTER_LABEL)),
        _para(_run("生成时间：" + _local_stamp())),
        _para(_run("溯源注释：%d 条，按原文保留于下方 SourceNote 段落"
                   % len(comments))),
    ]
    sect = ('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
            '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" '
            'w:left="1440" w:header="720" w:footer="720" w:gutter="0"/>'
            '</w:sectPr>')
    body = "".join(intro) + _blocks_to_xml(blocks) + sect
    return ('<w:document xmlns:w="%s" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<w:body>%s</w:body></w:document>' % (W, body)), src_line


def build_docx_bytes(md_text: str, src: Path, info: dict) -> tuple[bytes, str]:
    """在内存里组装完整 OOXML 包；返回 (zip 字节, src 注释原文)。"""
    document_xml, src_line = _document_xml(md_text, src, info)
    parts = {
        "[Content_Types].xml": _CONTENT_TYPES,
        "_rels/.rels": _ROOT_RELS,
        "word/document.xml": document_xml,
        "word/_rels/document.xml.rels": _DOC_RELS,
        "word/styles.xml": _styles_xml(),
        "word/settings.xml": _SETTINGS,
        "docProps/core.xml": _core_xml(src.stem, src_line or CONVERTER_LABEL),
        "docProps/app.xml": _APP,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in parts.items():
            zf.writestr(name, (_XML_DECL + content).encode("utf-8"))
    return buf.getvalue(), src_line


# --------------------------------------------------------------------------- #
# 输入解析与逐条校验
# --------------------------------------------------------------------------- #
def _read_md(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _resolve_inputs(inputs, out_root: Path) -> tuple[list[str], bool]:
    """显式 inputs 优先；否则只读地自动收集 MERGED.md / out/md/*.md。"""
    raw = [str(x).strip() for x in (inputs or []) if str(x).strip()]
    if raw:
        return raw, False
    merged = out_root / "MERGED.md"
    if merged.is_file():
        return [str(merged)], True
    md_dir = out_root / "md"
    if md_dir.is_dir():
        found = sorted(p for p in md_dir.glob("*.md") if p.is_file())
        if found:
            return [str(p) for p in found[:MAX_AUTO_INPUTS]], True
    return [], True


def _basic_check(raw: str) -> dict:
    p = Path(raw)
    if not p.is_file():
        return {"ok": False, "status": STATUS_FAILED,
                "error": "文件不存在或不是普通文件：%s" % p.name}
    ext = p.suffix.lower()
    if not format_registry.is_word_export_input(ext):
        return {"ok": False, "status": STATUS_UNSUPPORTED, "format": ext,
                "error": "S2b 仅支持 .md / .markdown 输入，收到 %s"
                         % (ext or "无后缀")}
    try:
        size = p.stat().st_size
    except OSError as exc:
        return {"ok": False, "status": STATUS_FAILED,
                "error": "无法读取文件属性：%s" % exc}
    if size > MAX_BYTES:
        return {"ok": False, "status": STATUS_FAILED, "format": ext,
                "error": "文件超过 %d MB 上限，已拒绝导出"
                         % (MAX_BYTES // 1024 // 1024)}
    return {"ok": True, "status": STATUS_OK, "path": str(p),
            "name": p.name, "format": ext, "size": size}


def _merge_provenance(outdir: Path, new_entries: list) -> list:
    """保留 S2a 等历史条目，追加本批次；绝不覆盖 derived 区已有清单。"""
    old = media_runtime.read_provenance(outdir)
    prior = old.get("entries") if isinstance(old, dict) else None
    entries = list(prior) if isinstance(prior, list) else []
    entries.extend(new_entries)
    return entries


# --------------------------------------------------------------------------- #
# 对外 API
# --------------------------------------------------------------------------- #
def export(inputs, outdir) -> dict:
    """把 Markdown 导出为独立 ``out/derived/<doc_id>.docx``。

    失败项不落空 docx、不落 ``.part`` 半成品；只要有任意一条失败就不宣称
    「全部成功」。阶段 1 冻结对账盘全程只读。
    """
    if not str(outdir or "").strip():
        return {"ok": False, "error": "请先指定输出目录（本次提取的输出路径）"}
    out_root = Path(str(outdir)).expanduser()
    if out_root.exists() and not out_root.is_dir():
        return {"ok": False, "error": "输出路径不是目录：%s" % out_root}

    resolved, auto = _resolve_inputs(inputs, out_root)
    before = media_runtime.frozen_snapshot(out_root)
    results, entries, written = [], [], []

    for raw in resolved:
        base = _basic_check(raw)
        record = {"input": raw, "name": Path(raw).name,
                  "format": base.get("format", ""), "status": base["status"],
                  "ok": False, "error": base.get("error", ""),
                  "converter": "", "path": "", "doc_id": ""}
        if not base["ok"]:
            results.append(record)
            entries.append({"name": record["name"], "format": record["format"],
                            "status": record["status"], "reason": record["error"],
                            "capability": "word_export"})
            continue

        src = Path(base["path"])
        try:
            text = _read_md(src)
        except OSError as exc:
            record["error"] = "失败：读取 Markdown 失败：%s" % exc
            record["status"] = STATUS_FAILED
            results.append(record)
            entries.append({"name": record["name"], "format": record["format"],
                            "status": STATUS_FAILED, "reason": record["error"],
                            "capability": "word_export"})
            continue

        lines = text.splitlines()
        if len(lines) > MAX_LINES:
            record["error"] = "失败：Markdown 超过 %d 行上限，已拒绝导出" % MAX_LINES
            record["status"] = STATUS_FAILED
            results.append(record)
            entries.append({"name": record["name"], "format": record["format"],
                            "status": STATUS_FAILED, "reason": record["error"],
                            "capability": "word_export"})
            continue
        meaningful = [l for l in lines
                      if l.strip() and not _COMMENT_RE.fullmatch(l.strip())]
        if not meaningful:
            # 契约：绝不写空文件，也不用文件名/元数据冒充正文
            record["error"] = "失败：Markdown 无可导出正文，拒绝写空 docx"
            record["status"] = STATUS_FAILED
            results.append(record)
            entries.append({"name": record["name"], "format": record["format"],
                            "status": STATUS_FAILED, "reason": record["error"],
                            "capability": "word_export"})
            continue

        info = media_runtime.source_info(src)
        doc_id = info["doc_id"]
        try:
            blob, src_line = build_docx_bytes(text, src, info)
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            record["error"] = "失败：生成 OOXML 失败：%s" % exc
            record["status"] = STATUS_FAILED
            results.append(record)
            entries.append({"name": record["name"], "format": record["format"],
                            "status": STATUS_FAILED, "reason": record["error"],
                            "capability": "word_export"})
            continue

        target = media_runtime.ensure_derived(out_root) / (
            doc_id + format_registry.WORD_EXPORT_SUFFIX)
        tmp = target.with_name(target.name + ".part")
        try:
            tmp.write_bytes(blob)
            tmp.replace(target)
        except OSError as exc:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            record["error"] = "失败：写入 derived 产物失败：%s" % exc
            record["status"] = STATUS_FAILED
            results.append(record)
            entries.append({"name": record["name"], "format": record["format"],
                            "status": STATUS_FAILED, "reason": record["error"],
                            "capability": "word_export"})
            continue

        record.update({"ok": True, "status": STATUS_OK, "error": "",
                       "path": str(target), "doc_id": doc_id,
                       "converter": CONVERTER_LABEL,
                       "bytes": len(blob), "blocks": len(parse_markdown(text)),
                       "comments": len(_COMMENT_RE.findall(text))})
        results.append(record)
        written.append(str(target))
        entries.append({"name": record["name"], "format": record["format"],
                        "status": STATUS_OK, "path": str(target),
                        "doc_id": doc_id, "converter": CONVERTER_LABEL,
                        "source_comment": src_line, "tool": {"name": "标准库"},
                        "reason": "", "capability": "word_export",
                        "note": SCHEMA_NOTE})

    success = len(written)
    failed = len(results) - success
    prov_path = ""
    # 空输入必须「零副作用」：连 derived/ 目录都不创建，更不写 provenance。
    # 只要有逐条结果（哪怕全失败），才在 derived 区留痕。
    if results:
        try:
            prov = media_runtime.write_provenance(
                out_root, entries=_merge_provenance(out_root, entries))
            prov_path = str(prov)
        except (OSError, ValueError):
            prov_path = ""

    payload = {
        "ok": success > 0,
        "results": results, "success": success, "failed": failed,
        "total": len(results), "auto_inputs": auto,
        "derived_dir": str(media_runtime.derived_dir(out_root)),
        "provenance": prov_path,
        "frozen_unchanged": media_runtime.frozen_unchanged(before, out_root),
        "path": written[0] if written else "",
    }
    if not results:
        payload["error"] = ("未找到可导出的 Markdown：请显式选择 .md 文件，"
                            "或先完成提取生成 MERGED.md")
    elif success == 0:
        payload["error"] = "本次没有可生成的 .docx；逐条原因见 results"
    elif failed:
        payload["warning"] = "共 %d 项未处理，逐条原因见 results" % failed
    return payload
