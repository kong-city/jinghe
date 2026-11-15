#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精核 · Word → .md 输入增强（S2a · 阶段 2 一期）。

本模块是**独立后处理层**，与冻结内核完全正交：

* 不 import 也不修改 ``extract.py`` 的提取流水线；``SPEC.md`` 一字不动。
* 不引入任何第三方库：``.docx`` 走 ``zipfile`` + ``xml.etree.ElementTree``。
* ``.doc`` 旧格式借**本机** LibreOffice（soffice）预处理为 ``.docx``，
  工具由用户提供，软件不下载 / 不打包 / 不自动安装（契约 §3）。缺工具时
  只回 ``unavailable``，**不产出任何 md、不写空文件、不伪装成功**。
* 加密 / 受保护文档只做**正向证据识别**，一律单列 ``needs_authorization``，
  绝不破译、绝不猜测口令、绝不盲重试（契约 §8 S2a 验收口径）。

产物严格落 ``out/derived/<doc_id>.md`` + ``provenance_media.json``，
自带 8 字段 ``src`` 来源注释与块级锚点；**绝不写** ``out/md/``、
``INDEX.md``、``MERGED.md``、``provenance.json``（契约 §4 / 不变量 7）。

临时目录三链齐备（契约 §9）：父进程持有 → ``finally`` 删除 →
``atexit`` 兜底 → 启动时清扫过期孤儿；不靠单一 ``atexit`` 兜强杀。
"""
from __future__ import annotations

import atexit
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import format_registry
import media_runtime
import media_tools

# --------------------------------------------------------------------------- #
# 常量与安全上限
# --------------------------------------------------------------------------- #
MAX_BYTES = 64 * 1024 * 1024          # 单文件上限，超限直接断链不解析
CONVERT_TIMEOUT = 90.0                # soffice 预处理超时（秒）
PROBE_TIMEOUT = 2.0
CONVERTER_LABEL = "精核 Word 输入增强 v1（标准库 zipfile+ElementTree）"
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_PK_MAGIC = b"PK\x03\x04"
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

STATUS_OK = "成功"
STATUS_NEEDS_AUTH = "待人工授权"
STATUS_UNAVAILABLE = "未启用"
STATUS_UNSUPPORTED = "不支持"
STATUS_FAILED = "失败"

# --------------------------------------------------------------------------- #
# 临时目录：父进程持有 + finally + atexit + 启动孤儿清扫（三链）
# --------------------------------------------------------------------------- #
_TEMP_PREFIX = "jinghe-word-"
_LIVE_TEMPS: set[str] = set()
_TEMPS_LOCK = threading.Lock()
_ORPHAN_MAX_AGE = 24 * 3600.0        # 只敢清扫一天前的历史残留


def _register_temp(path: Path) -> None:
    with _TEMPS_LOCK:
        _LIVE_TEMPS.add(str(path))


def _drop_temp(path: Path) -> None:
    shutil.rmtree(str(path), ignore_errors=True)
    with _TEMPS_LOCK:
        _LIVE_TEMPS.discard(str(path))


def _cleanup_all_temps() -> None:
    with _TEMPS_LOCK:
        pending = list(_LIVE_TEMPS)
    for item in pending:
        shutil.rmtree(item, ignore_errors=True)
    with _TEMPS_LOCK:
        _LIVE_TEMPS.clear()


def _sweep_orphan_temps() -> int:
    """启动时清扫上次强杀留下的过期目录；只按 mtime 判断，不猜进程存活。

    不触碰 24 小时内的目录，避免误删另一个正在运行的精核实例的临时区。
    """
    root = Path(tempfile.gettempdir())
    now = time.time()
    removed = 0
    try:
        candidates = list(root.glob(_TEMP_PREFIX + "*"))
    except OSError:
        return 0
    for item in candidates:
        if not item.is_dir():
            continue
        with _TEMPS_LOCK:
            if str(item) in _LIVE_TEMPS:
                continue
        try:
            if now - item.stat().st_mtime < _ORPHAN_MAX_AGE:
                continue
            shutil.rmtree(str(item), ignore_errors=True)
            removed += 1
        except OSError:
            continue
    return removed


atexit.register(_cleanup_all_temps)
_sweep_orphan_temps()


def _new_temp() -> Path:
    path = Path(tempfile.mkdtemp(prefix="%s%d-" % (_TEMP_PREFIX, os.getpid())))
    _register_temp(path)
    return path


# --------------------------------------------------------------------------- #
# 本机 LibreOffice 探测（刻意不并入 media_tools.TOOL_SPECS）
# --------------------------------------------------------------------------- #
_SOFFICE_CACHE: dict | None = None
_SOFFICE_LOCK = threading.Lock()


def _which_soffice(_name: str) -> str | None:
    """Windows 常见安装路径 + PATH；找不到就返回 None，绝不假装可用。"""
    for exe in ("soffice.com", "soffice", "soffice.exe", "libreoffice"):
        found = shutil.which(exe)
        if found:
            return found
    for var in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base = os.environ.get(var)
        if not base:
            continue
        for rel in ("LibreOffice/program/soffice.com",
                    "LibreOffice/program/soffice.exe",
                    "Programs/LibreOffice/program/soffice.exe"):
            candidate = Path(base) / rel
            if candidate.is_file():
                return str(candidate)
    return None


def probe_soffice(refresh: bool = False) -> dict:
    """``probe() -> {available, path, version, reason}``；结果进程内缓存。"""
    global _SOFFICE_CACHE
    with _SOFFICE_LOCK:
        if _SOFFICE_CACHE is not None and not refresh:
            return dict(_SOFFICE_CACHE)
    adapter = media_tools.ToolAdapter(
        "soffice", ["--version"], r"LibreOffice\s+([\d.]+)",
        timeout=PROBE_TIMEOUT, which=_which_soffice)
    result = adapter.probe()
    result["name"] = "soffice"
    with _SOFFICE_LOCK:
        _SOFFICE_CACHE = result
    return dict(result)


def capability(refresh: bool = False) -> dict:
    """S2a 能力状态。``.docx`` 纯标准库恒可用；``.doc`` 取决于本机工具。

    刻意放在本模块而非 ``media_tools.capabilities()``：S1 契约测试锁住了
    后者「全部未启用」与工具数量，S2a 不改写既有断言，走增量字段。
    """
    tool = probe_soffice(refresh=refresh)
    return {
        "name": "word_input_enhance",
        "enabled": True,
        "ooxml": {
            "enabled": True,
            "reason": ".docx 批注、修订、加密识别由标准库完成，无需外部工具",
        },
        "legacy_doc": {
            "enabled": bool(tool.get("available")),
            "reason": (".doc 旧格式可用本机 LibreOffice 预处理"
                       if tool.get("available") else
                       "本机未找到 LibreOffice（soffice），.doc 旧格式预处理未启用"),
            "tool": tool,
        },
        "encryption": {
            "enabled": False,
            "reason": "加密文档一律单列「待人工授权」，软件不破译、不询问口令",
        },
        "note": "产物落 out/derived/，不写阶段 1 对账盘",
    }


# --------------------------------------------------------------------------- #
# 加密 / 格式正向识别：只判证据，绝不解密
# --------------------------------------------------------------------------- #
def _read_head(path: Path, size: int = 8) -> bytes:
    with open(str(path), "rb") as fh:
        return fh.read(size)


def _probe_encryption(path: Path) -> str:
    """返回空串表示无加密正向证据；否则返回「待人工授权」的可读原因。"""
    try:
        head = _read_head(path)
    except OSError:
        return ""
    if head == b"":
        return ""

    # ① OOXML 敏捷加密：外层是 OLE 容器，内含 EncryptedPackage 流
    if head.startswith(_OLE_MAGIC):
        try:
            with open(str(path), "rb") as fh:
                blob = fh.read(2 * 1024 * 1024)
        except OSError:
            blob = b""
        # OLE 目录项名是 UTF-16LE；同时兼容直接可打印的 ASCII 标记
        for marker in ("EncryptedPackage", "EncryptionInfo"):
            if marker.encode("utf-16-le") in blob or marker.encode("ascii", "ignore") in blob:
                return ("待人工授权：疑似加密的 Office 文档（OLE 容器含 %s），"
                        "需人工解密后再处理" % marker)
        return ""   # 普通 .doc 本来就是 OLE 复合文档，不能一律判加密

    # ② ZIP（.docx）：加密位或加密信息成员
    if head.startswith(_PK_MAGIC[:2]):
        try:
            with zipfile.ZipFile(str(path)) as zf:
                names = zf.namelist()
                if any(n.startswith(("EncryptionInfo", "EncryptedPackage"))
                       for n in names):
                    return ("待人工授权：Office 文档已加密（含加密信息成员），"
                            "需人工解密后再处理")
                if any(info.flag_bits & 0x1 for info in zf.infolist()):
                    return "待人工授权：ZIP 成员已加密（需口令），需人工解密后再处理"
        except (zipfile.BadZipFile, OSError, ValueError):
            return ""   # 损坏容器是「失败」，不是「加密」，由上层诚实回显
    return ""


# --------------------------------------------------------------------------- #
# OOXML 解析（批注 / 修订 / 正文）
# --------------------------------------------------------------------------- #
def _ns_of(root: ET.Element) -> str:
    tag = root.tag
    return tag.split("}", 1)[0] + "}" if tag.startswith("{") else ""


def _xml(zf: zipfile.ZipFile, name: str):
    try:
        return ET.fromstring(zf.read(name))
    except (KeyError, ET.ParseError, ValueError):
        return None


def _text_of(el: ET.Element, ns: str, tag: str = "t") -> str:
    return "".join(t.text or "" for t in el.iter(ns + tag)).strip()


def _parse_comments(zf: zipfile.ZipFile):
    """返回 (批注列表, 命名空间)。批注含作者 / 时间 / 正文 / 锚定段落序号。"""
    root = _xml(zf, "word/comments.xml")
    if root is None:
        return [], ""
    ns = _ns_of(root)
    items = []
    for node in root.iter(ns + "comment"):
        items.append({
            "id": node.get(ns + "id", "") or "",
            "author": node.get(ns + "author", "") or "（未署名）",
            "initials": node.get(ns + "initials", "") or "",
            "date": node.get(ns + "date", "") or "",
            "text": _text_of(node, ns),
        })
    return items, ns


def _comment_positions(zf: zipfile.ZipFile) -> dict:
    """批注 id → 正文段落序号（1 基），用于产物里给出可回溯定位。"""
    root = _xml(zf, "word/document.xml")
    if root is None:
        return {}
    ns = _ns_of(root)
    body = root.find(ns + "body")
    if body is None:
        body = root
    out = {}
    for idx, el in enumerate(list(body), 1):
        for marker in el.iter(ns + "commentRangeStart"):
            cid = marker.get(ns + "id", "") or ""
            if cid and cid not in out:
                out[cid] = idx
    return out


def _parse_revisions(zf: zipfile.ZipFile) -> dict:
    """插入 / 删除 / 移动 / 格式修订的明细与计数。"""
    root = _xml(zf, "word/document.xml")
    result = {"insertions": [], "deletions": [], "moves": [],
              "format_changes": 0, "total": 0}
    if root is None:
        return result
    ns = _ns_of(root)
    for node in root.iter(ns + "ins"):
        result["insertions"].append({
            "author": node.get(ns + "author", "") or "（未署名）",
            "date": node.get(ns + "date", "") or "",
            "text": _text_of(node, ns, "t"),
        })
    for node in root.iter(ns + "del"):
        result["deletions"].append({
            "author": node.get(ns + "author", "") or "（未署名）",
            "date": node.get(ns + "date", "") or "",
            "text": _text_of(node, ns, "delText"),
        })
    for node in list(root.iter(ns + "moveFrom")) + list(root.iter(ns + "moveTo")):
        result["moves"].append({
            "author": node.get(ns + "author", "") or "（未署名）",
            "date": node.get(ns + "date", "") or "",
            "text": _text_of(node, ns, "t") or _text_of(node, ns, "delText"),
        })
    result["format_changes"] = sum(
        1 for _ in list(root.iter(ns + "rPrChange")) + list(root.iter(ns + "pPrChange")))
    result["total"] = (len(result["insertions"]) + len(result["deletions"])
                       + len(result["moves"]) + result["format_changes"])
    return result


def _parse_body(zf: zipfile.ZipFile) -> list[dict]:
    """正文分块：段落（含标题级别）与表格，按文档顺序。

    ``w:del`` 的文字是 ``w:delText`` 而非 ``w:t``，天然不会混进正文；
    因此正文等价于「接受全部修订」的视图，修订明细另列区块，不丢任何信息。
    """
    root = _xml(zf, "word/document.xml")
    if root is None:
        return []
    ns = _ns_of(root)
    body = root.find(ns + "body")
    if body is None:
        body = root
    blocks = []
    for el in list(body):
        if el.tag == ns + "p":
            level = 0
            ppr = el.find(ns + "pPr")
            if ppr is not None:
                st = ppr.find(ns + "pStyle")
                if st is not None:
                    m = re.search(r"(?i)heading\s*(\d)|title",
                                  st.get(ns + "val", "") or "")
                    if m:
                        level = min((int(m.group(1)) if m.group(1) else 1) + 1, 6)
            txt = _text_of(el, ns)
            if txt:
                blocks.append({"kind": "p", "level": level, "text": txt})
        elif el.tag == ns + "tbl":
            rows = []
            for tr in el.iter(ns + "tr"):
                cells = [" ".join(t.text or "" for t in tc.iter(ns + "t"))
                         .strip().replace("|", "\\|")
                         for tc in tr.findall(ns + "tc")]
                if cells:
                    rows.append(cells)
            if rows:
                width = max(len(r) for r in rows)
                rows = [r + [""] * (width - len(r)) for r in rows]
                lines = ["| " + " | ".join(rows[0]) + " |",
                         "|" + " --- |" * width]
                lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
                blocks.append({"kind": "tbl", "level": 0,
                               "text": "\n".join(lines)})
    return blocks


def parse_ooxml(path: Path) -> dict:
    """解析一个 .docx（或经预处理得到的 .docx），返回结构化内容。"""
    with zipfile.ZipFile(str(path)) as zf:
        if "word/document.xml" not in zf.namelist():
            raise ValueError("ZIP 内缺少 word/document.xml，不是有效的 Word 文档")
        comments, _ = _parse_comments(zf)
        positions = _comment_positions(zf)
        for item in comments:
            item["paragraph"] = positions.get(item["id"], 0)
        return {
            "blocks": _parse_body(zf),
            "comments": comments,
            "revisions": _parse_revisions(zf),
        }


# --------------------------------------------------------------------------- #
# .doc 旧格式：本机 LibreOffice 预处理（缺工具即诚实降级）
# --------------------------------------------------------------------------- #
def _convert_legacy(path: Path) -> tuple[dict | None, dict | None, str]:
    """返回 ``(parsed, tool_info, error)``；三者互斥，失败绝不返回假内容。"""
    tool = probe_soffice()
    if not tool.get("available"):
        return None, None, ("未启用：本机未找到 LibreOffice（soffice），"
                            ".doc 旧格式预处理未启用；请在本机安装后重试。"
                            "（%s）" % tool.get("reason", ""))
    temp = _new_temp()
    try:
        cmd = [tool["path"], "--headless", "--norestore",
               "--convert-to", "docx", "--outdir", str(temp), str(path)]
        kwargs = {
            "args": cmd, "capture_output": True, "text": True,
            "encoding": "utf-8", "errors": "replace",
            "timeout": CONVERT_TIMEOUT,
        }
        if _CREATE_NO_WINDOW:
            kwargs["creationflags"] = _CREATE_NO_WINDOW
        try:
            res = subprocess.run(**kwargs)
        except subprocess.TimeoutExpired:
            return None, None, ("未启用：LibreOffice 预处理超时（%.0fs），"
                                "已取消且未产出任何 md" % CONVERT_TIMEOUT)
        except (OSError, ValueError) as exc:
            return None, None, "失败：无法启动 LibreOffice 预处理：%s" % exc
        converted = temp / (path.stem + ".docx")
        if getattr(res, "returncode", -1) != 0 or not converted.is_file():
            tail = ((getattr(res, "stderr", "") or "") +
                    (getattr(res, "stdout", "") or "")).strip()[-200:]
            return None, None, ("失败：LibreOffice 未生成 .docx（退出码 %s）%s"
                                % (getattr(res, "returncode", -1),
                                   ("；" + tail) if tail else ""))
        try:
            parsed = parse_ooxml(converted)
        except (ValueError, zipfile.BadZipFile, ET.ParseError, OSError) as exc:
            return None, None, "失败：预处理产物无法解析：%s" % exc
        info = {"name": "soffice", "version": tool.get("version", ""),
                "path": tool.get("path", ""),
                "output": converted.name}
        return parsed, info, ""
    finally:
        _drop_temp(temp)


# --------------------------------------------------------------------------- #
# 产物渲染：8 字段 src 注释 + 块级锚点 + 分区内容
# --------------------------------------------------------------------------- #
def _render_md(path: Path, fmt: str, parsed: dict, converter: str,
               source_note: str = "") -> tuple[str, str]:
    info = media_runtime.source_info(path)
    doc_id = info["doc_id"]
    anchors = ["block"]
    header = media_runtime.source_comment(path, fmt, converter, anchors)
    lines = [header, "", "# %s" % path.stem, ""]

    lines += ["## 文档信息", ""]
    lines += ["- 原始格式：`%s`" % fmt,
              "- 文件大小：%d 字节" % info["size"],
              "- 正文块数：%d" % len(parsed["blocks"]),
              "- 批注数：%d" % len(parsed["comments"]),
              "- 修订数：%d（插入 %d / 删除 %d / 移动 %d / 格式 %d）"
              % (parsed["revisions"]["total"],
                 len(parsed["revisions"]["insertions"]),
                 len(parsed["revisions"]["deletions"]),
                 len(parsed["revisions"]["moves"]),
                 parsed["revisions"]["format_changes"])]
    if source_note:
        lines.append("- 预处理：%s" % source_note)
    lines += ["- 正文视图：按「接受全部修订」呈现；修订明细见下方独立区块。", ""]

    block_idx = 0
    lines += ["## 正文", ""]
    block_idx += 1
    lines.append(media_runtime.block_anchor(doc_id, block_idx))
    lines.append("")
    if parsed["blocks"]:
        for blk in parsed["blocks"]:
            if blk["kind"] == "p":
                lines.append(("#" * blk["level"] + " " if blk["level"] else "")
                             + blk["text"])
            else:
                lines.append(blk["text"])
            lines.append("")
    else:
        lines += ["<!-- 文档正文无文本（可能为纯图片 / 空白文档） -->", ""]

    block_idx += 1
    lines += ["## 批注", "", media_runtime.block_anchor(doc_id, block_idx), ""]
    if parsed["comments"]:
        for i, c in enumerate(parsed["comments"], 1):
            bits = ["批注 %d" % i, "作者 %s" % c["author"]]
            if c["date"]:
                bits.append("时间 %s" % c["date"])
            if c["paragraph"]:
                bits.append("定位 第 %d 段" % c["paragraph"])
            lines.append("- **%s**：%s" % (" / ".join(bits), c["text"] or "（无文本）"))
        lines.append("")
    else:
        lines += ["<!-- 未发现批注 -->", ""]

    rev = parsed["revisions"]
    block_idx += 1
    lines += ["## 修订", "", media_runtime.block_anchor(doc_id, block_idx), ""]
    if rev["total"]:
        for label, key, mark in (("插入", "insertions", "+"),
                                 ("删除", "deletions", "-"),
                                 ("移动", "moves", "~")):
            for item in rev[key]:
                meta = "作者 %s" % item["author"]
                if item["date"]:
                    meta += " / 时间 %s" % item["date"]
                lines.append("- `%s` **%s**（%s）：%s"
                             % (mark, label, meta, item["text"] or "（无文本）"))
        if rev["format_changes"]:
            lines.append("- `*` **格式修订**：%d 处（不改变正文文字）"
                         % rev["format_changes"])
        lines.append("")
    else:
        lines += ["<!-- 未发现修订 -->", ""]

    return "\n".join(lines).rstrip() + "\n", doc_id


# --------------------------------------------------------------------------- #
# 对外 API：inspect（只读预检） / enhance（写 derived 产物）
# --------------------------------------------------------------------------- #
def _basic_check(raw: str) -> dict:
    """单文件基础校验：存在 / 是文件 / 后缀 / 大小 / 加密正向证据。"""
    p = Path(raw)
    if not p.is_file():
        return {"ok": False, "status": STATUS_FAILED,
                "error": "文件不存在或不是普通文件：%s" % p.name}
    ext = p.suffix.lower()
    if not format_registry.is_word_input(ext):
        return {"ok": False, "status": STATUS_UNSUPPORTED,
                "format": ext,
                "error": "S2a 仅支持 .docx / .doc 输入增强，收到 %s" % (ext or "无后缀")}
    try:
        size = p.stat().st_size
    except OSError as exc:
        return {"ok": False, "status": STATUS_FAILED, "error": "无法读取文件属性：%s" % exc}
    if size > MAX_BYTES:
        return {"ok": False, "status": STATUS_FAILED, "format": ext,
                "error": "文件超过 %d MB 上限，已拒绝解析" % (MAX_BYTES // 1024 // 1024)}
    reason = _probe_encryption(p)
    if reason:
        return {"ok": False, "status": STATUS_NEEDS_AUTH, "format": ext,
                "error": reason}
    return {"ok": True, "status": STATUS_OK, "path": str(p),
            "name": p.name, "format": ext, "size": size}


def inspect(inputs) -> dict:
    """只读预检：逐文件给出可处理性判断，不写任何文件、不创建目录。"""
    items = []
    for raw in list(inputs or []):
        base = _basic_check(str(raw))
        entry = {"input": str(raw), "name": Path(str(raw)).name,
                 "status": base["status"], "ok": base["ok"],
                 "format": base.get("format", ""),
                 "error": base.get("error", "")}
        if base["ok"]:
            ext = base["format"]
            if ext == ".doc":
                tool = probe_soffice()
                entry["legacy_ready"] = bool(tool.get("available"))
                entry["tool"] = tool.get("version", "")
                if not tool.get("available"):
                    entry["status"] = STATUS_UNAVAILABLE
                    entry["ok"] = False
                    entry["error"] = ("未启用：本机未找到 LibreOffice（soffice），"
                                      ".doc 旧格式预处理未启用")
            else:
                try:
                    parsed = parse_ooxml(Path(base["path"]))
                    entry["comments"] = len(parsed["comments"])
                    entry["revisions"] = parsed["revisions"]["total"]
                    entry["blocks"] = len(parsed["blocks"])
                except (ValueError, zipfile.BadZipFile, ET.ParseError, OSError) as exc:
                    entry["status"] = STATUS_FAILED
                    entry["ok"] = False
                    entry["error"] = "失败：OOXML 解析失败：%s" % exc
        items.append(entry)
    ready = sum(1 for e in items if e["ok"])
    return {
        "ok": True, "capability": "word_input_enhance",
        "items": items, "total": len(items), "ready": ready,
        "note": "只读预检，不写任何文件；加密文档单列待人工授权，绝不破译",
    }


def _merge_provenance(outdir: Path, new_entries: list) -> list:
    """保留历史条目，追加本批次；provenance_media.json 只读 derived 区。"""
    old = media_runtime.read_provenance(outdir)
    prior = old.get("entries") if isinstance(old, dict) else None
    entries = list(prior) if isinstance(prior, list) else []
    entries.extend(new_entries)
    return entries


def enhance(inputs, outdir) -> dict:
    """把选中的 Word 文件转换为带批注 / 修订 / 加密识别的独立增强 .md。

    失败项不落空文件，只在 ``provenance_media.json`` 与 results 中留痕；
    只要有任意一条失败就不宣称「全部成功」。
    """
    out_root = Path(str(outdir or "")).expanduser()
    if not str(outdir or "").strip():
        return {"ok": False, "error": "请先指定输出目录（本次提取的输出路径）"}
    if out_root.exists() and not out_root.is_dir():
        return {"ok": False, "error": "输出路径不是目录：%s" % out_root}

    before = media_runtime.frozen_snapshot(out_root)
    results = []
    entries = []
    written = []

    for raw in list(inputs or []):
        base = _basic_check(str(raw))
        record = {
            "input": str(raw), "name": Path(str(raw)).name,
            "format": base.get("format", ""), "status": base["status"],
            "ok": False, "error": base.get("error", ""),
            "converter": "", "path": "", "doc_id": "",
        }
        converter = CONVERTER_LABEL
        parsed = None
        source_note = ""

        if not base["ok"]:
            results.append(record)
            entries.append({"name": record["name"], "format": record["format"],
                            "status": record["status"], "reason": record["error"],
                            "converter": ""})
            continue

        src = Path(base["path"])
        tool_info = None
        if base["format"] == ".doc":
            parsed, tool_info, err = _convert_legacy(src)
            if parsed is None:
                record["ok"] = False
                record["status"] = (STATUS_UNAVAILABLE if "未启用" in err
                                    else STATUS_FAILED)
                record["error"] = err
                results.append(record)
                entries.append({"name": record["name"], "format": ".doc",
                                "status": record["status"], "reason": err,
                                "converter": ""})
                continue
            converter = "LibreOffice %s + %s" % (
                tool_info.get("version") or "（版本未探测到）", CONVERTER_LABEL)
            source_note = "soffice 预处理为 %s（本机工具，未随软件分发）" % (
                tool_info.get("output", "docx"))
        else:
            try:
                parsed = parse_ooxml(src)
            except (ValueError, zipfile.BadZipFile, ET.ParseError, OSError) as exc:
                record["ok"] = False
                record["status"] = STATUS_FAILED
                record["error"] = "失败：OOXML 解析失败：%s" % exc
                results.append(record)
                entries.append({"name": record["name"], "format": ".docx",
                                "status": STATUS_FAILED,
                                "reason": record["error"], "converter": ""})
                continue

        if not parsed["blocks"] and not parsed["comments"] and not parsed["revisions"]["total"]:
            # 真空文档：不写占位 md，诚实回显（契约：绝不写空 md）
            record["ok"] = False
            record["status"] = STATUS_FAILED
            record["error"] = "失败：文档无可提取文本、批注或修订，拒绝写空 md"
            results.append(record)
            entries.append({"name": record["name"], "format": record["format"],
                            "status": STATUS_FAILED, "reason": record["error"],
                            "converter": converter})
            continue

        try:
            text, doc_id = _render_md(src, base["format"], parsed, converter,
                                      source_note)
            target = media_runtime.ensure_derived(out_root) / (doc_id + ".md")
            tmp = target.with_name(target.name + ".part")
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(target)
        except (OSError, ValueError) as exc:
            record["ok"] = False
            record["status"] = STATUS_FAILED
            record["error"] = "失败：写入 derived 产物失败：%s" % exc
            results.append(record)
            entries.append({"name": record["name"], "format": record["format"],
                            "status": STATUS_FAILED, "reason": record["error"],
                            "converter": converter})
            continue

        record.update({"ok": True, "status": STATUS_OK, "error": "",
                       "path": str(target), "doc_id": doc_id,
                       "converter": converter,
                       "comments": len(parsed["comments"]),
                       "revisions": parsed["revisions"]["total"],
                       "blocks": len(parsed["blocks"])})
        results.append(record)
        written.append(str(target))
        entries.append({"name": record["name"], "format": record["format"],
                        "status": STATUS_OK, "path": str(target),
                        "doc_id": doc_id, "converter": converter,
                        "tool": tool_info or {"name": "标准库"},
                        "reason": ""})

    success = len(written)
    failed = len(results) - success
    try:
        merged = _merge_provenance(out_root, entries)
        prov = media_runtime.write_provenance(out_root, entries=merged)
        prov_path = str(prov)
    except (OSError, ValueError):
        # md 产物已写好；provenance 本次写失败不掩盖成功，下批次会重试合并。
        prov_path = ""

    unchanged = media_runtime.frozen_unchanged(before, out_root)
    payload = {
        "ok": success > 0,
        "results": results, "success": success, "failed": failed,
        "total": len(results),
        "derived_dir": str(media_runtime.derived_dir(out_root)),
        "provenance": prov_path,
        "frozen_unchanged": unchanged,
        "path": written[0] if written else "",
    }
    if not results:
        payload["error"] = "请先选择 .docx / .doc 文件"
    elif success == 0:
        payload["error"] = "本次没有可生成的增强产物；逐条原因见 results"
    elif failed:
        payload["warning"] = "共 %d 项未处理，逐条原因见 results" % failed
    return payload
