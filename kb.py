# -*- coding: utf-8 -*-
"""精核 · S9 阶段 4 知识库核心（正交新能力，不改 extract.py / SPEC.md）。

设计约束（见 docs/S9-阶段4知识库立项与契约对账.md）：
* 纯标准库：sqlite3 + json + re + hashlib + pathlib；零第三方依赖。
* 正交：只消费 extract.py 已产出的 md（src 注释 + 块锚点），不碰冻结内核。
* 可回溯：每条入库条目携带 doc_id + 块锚点 + 来源文件 + sha256。
* 不造假：只重组产物中已有的正文，不生成新内容。
* AI 补写隔离：含 ``[AI ++ … ++]`` 或「AI 补充」分区的条目默认不入库。
* 路径围栏：入库 / 打开只接受白名单目录，拒绝任意路径。

对外 API（纯函数式，便于测试）：
    init_kb(kb_dir) -> dict                       初始化，返回状态
    kb_status(kb_dir) -> dict                     状态：条目数 / 建库时间
    ingest_dir(kb_dir, product_dir, *,           把产物目录入库
               include_ai=False, allowed_roots=None) -> dict
    query(kb_dir, text, *, limit=20) -> dict      关键词检索，带来源标注
    open_source(kb_dir, entry_id, *,             解析条目的原文回跳位置
                allowed_roots=None) -> dict
    reset_kb(kb_dir) -> dict                      清空索引（手动维护入口）
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from pathlib import Path

__version__ = "0.1.0"  # kb 模块自身版本，与软件版本双轨

# ── 解析用的正则（与 extract.py 的产物格式严格对齐）──────────────────────────
_SRC_RE = re.compile(r"^<!--\s*src:\s*(.*?)\s*-->\s*$", re.M)
_ANCHOR_RE = re.compile(r"^<!--\s*anchor:\s*(.*?)\s*-->\s*$", re.M)
_AI_MARK_RE = re.compile(r"\[AI\s*\+\+.*?\+\+\]", re.S)
_AI_SECTION_HEAD = "## AI 补充"


def _parse_fields(text: str) -> dict:
    """把 ``k: v | k2: v2`` 形式解析为字典；首段作为 ``_first``。"""
    out = {}
    parts = [p.strip() for p in text.split("|")]
    if parts and parts[0]:
        out["_first"] = parts[0]
    for p in parts[1:]:
        if ":" in p:
            k, v = p.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def _content_hash(text: str) -> str:
    """正文规范化后取 hash，用于去重与完整性。"""
    norm = re.sub(r"\s+", " ", text).strip()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


# ── 路径围栏 ────────────────────────────────────────────────────────────────
def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def _check_allowed(target: Path, allowed_roots) -> str:
    """路径必须在允许的根目录之一内，否则拒绝（防目录穿越 / 任意读取）。"""
    roots = list(allowed_roots or [])
    if not roots:
        return "未提供允许的根目录"
    for root in roots:
        if _is_within(target, Path(root)):
            return ""
    return "路径不在允许范围内"


# ── sqlite 存储 ─────────────────────────────────────────────────────────────
def _db_path(kb_dir) -> Path:
    return Path(kb_dir) / "kb.sqlite3"


def _connect(kb_dir):
    Path(kb_dir).mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_db_path(kb_dir)))
    conn.row_factory = sqlite3.Row
    return conn


def _fts_available(conn) -> str:
    """探测 FTS5 分词器。返回 'trigram' / 'unicode61' / ''（不可用）。

    S9 决策：中文检索优先 trigram——unicode61 把连续中文当成一整个 token，
    任意中文子串都匹配不到；trigram 支持中文子串（≥3 字符），短词由 LIKE 兜底。
    """
    for tok in ("trigram", "unicode61"):
        try:
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS __kb_fts_probe "
                "USING fts5(x, tokenize='%s')" % tok
            )
            conn.execute("DROP TABLE __kb_fts_probe")
            return tok
        except sqlite3.Error:
            continue
    return ""


def init_kb(kb_dir) -> dict:
    """初始化知识库（幂等）。"""
    conn = _connect(kb_dir)
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS entries (
                   id TEXT PRIMARY KEY,
                   doc_id TEXT NOT NULL,
                   block INTEGER NOT NULL,
                   locator TEXT NOT NULL DEFAULT '',
                   body TEXT NOT NULL,
                   source_file TEXT NOT NULL,
                   sha256 TEXT NOT NULL DEFAULT '',
                   content_hash TEXT NOT NULL,
                   ref_count INTEGER NOT NULL DEFAULT 1,
                   created_at REAL NOT NULL
               )"""
        )
        tokenizer = _fts_available(conn)
        fts = bool(tokenizer)
        if fts:
            # 分词器变了要重建虚拟表（幂等：先探测旧表是否存在）
            existing = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='entries_fts'"
            ).fetchone()
            want = "tokenize='%s'" % tokenizer
            if existing and want not in (existing[0] or ""):
                conn.execute("DROP TABLE entries_fts")
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts "
                "USING fts5(id UNINDEXED, body, tokenize='%s')" % tokenizer
            )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta(k,v) VALUES('created_at',?)",
            (str(time.time()),),
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta(k,v) VALUES('fts',?)",
            ("1" if fts else "0",),
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta(k,v) VALUES('tokenizer',?)",
            (tokenizer or "none",),
        )
        conn.commit()
        return {
            "ok": True,
            "kb_dir": str(Path(kb_dir).resolve()),
            "fts": fts,
            "tokenizer": tokenizer or "none",
        }
    finally:
        conn.close()


def reset_kb(kb_dir) -> dict:
    """清空条目索引（手动维护入口；不删知识库目录本身）。"""
    conn = _connect(kb_dir)
    try:
        conn.execute("DELETE FROM entries")
        conn.execute("DELETE FROM entries_fts")
        conn.commit()
        n = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        return {"ok": True, "entries": n}
    except sqlite3.Error as e:
        return {"ok": False, "error": "清空失败: %s" % e}
    finally:
        conn.close()


def kb_status(kb_dir) -> dict:
    db = _db_path(kb_dir)
    if not db.exists():
        return {"ok": True, "initialized": False, "entries": 0, "fts": False}
    conn = _connect(kb_dir)
    try:
        n = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        row = conn.execute("SELECT v FROM meta WHERE k='fts'").fetchone()
        created = conn.execute("SELECT v FROM meta WHERE k='created_at'").fetchone()
        return {
            "ok": True,
            "initialized": True,
            "entries": n,
            "fts": bool(row and row[0] == "1"),
            "created_at": float(created[0]) if created else None,
            "db": str(db.resolve()),
        }
    finally:
        conn.close()


# ── 入库 ────────────────────────────────────────────────────────────────────
def parse_md_entries(md_text: str, *, source_file: str = "") -> dict:
    """解析一份产物 md：返回 src 元数据 + 块条目列表（纯函数，便于测试）。

    块边界是 ``<!-- anchor: ... -->`` 注释；每条正文为锚点后到下一锚点/文末。
    AI 补写内容（``[AI ++ … ++]`` 或「## AI 补充」分区）默认标记 ``is_ai``。
    """
    src_match = _SRC_RE.search(md_text)
    src = _parse_fields(src_match.group(1)) if src_match else {}
    doc_id = (
        src.get("_first")
        or (src.get("path") or "").strip()
        or Path(source_file).stem
    )
    sha256 = src.get("sha256", "")

    anchors = list(_ANCHOR_RE.finditer(md_text))
    entries = []
    in_ai_section = False
    for i, m in enumerate(anchors):
        info = _parse_fields(m.group(1))
        block_raw = info.get("block", "")
        try:
            block = int(block_raw)
        except (TypeError, ValueError):
            block = i + 1
        start = m.end()
        end = anchors[i + 1].start() if i + 1 < len(anchors) else len(md_text)
        raw = md_text[start:end].strip()
        # 去掉块内可能残留的其它 HTML 注释（如 "<!-- 本页无文本 -->"）
        body = re.sub(r"<!--.*?-->", "", raw, flags=re.S).strip()
        locator_keys = [
            "%s: %s" % (k, v)
            for k, v in info.items()
            if k not in ("_first", "block")
        ]
        locator = " | ".join(locator_keys)

        # AI 判定：显式 [AI ++ … ++] 标记，或「AI 补充」分区特征（标题含
        # 「模型生成」+ 正文含「原文并不存在」）。两个特征都在原始 body 上取，
        # 不能先删标题行——「模型生成」正是标题行里的关键词。
        in_ai_section = body.startswith(_AI_SECTION_HEAD) or (
            _AI_SECTION_HEAD in body
        )
        is_ai = bool(_AI_MARK_RE.search(body)) or (
            in_ai_section and "原文并不存在" in body
        )
        if not body:
            continue
        entries.append(
            {
                "id": "%s#%d" % (doc_id, block),
                "doc_id": doc_id,
                "block": block,
                "locator": locator,
                "body": body,
                "source_file": source_file,
                "sha256": sha256,
                "content_hash": _content_hash(body),
                "is_ai": is_ai,
            }
        )
    return {"doc_id": doc_id, "sha256": sha256, "src": src, "entries": entries}


def ingest_md(kb_dir, md_path, *, include_ai=False, allowed_roots=None) -> dict:
    """把一份产物 md 入库（幂等去重）。"""
    p = Path(md_path)
    err = _check_allowed(p, allowed_roots)
    if err:
        return {"ok": False, "error": err, "file": str(p)}
    if not p.is_file():
        return {"ok": False, "error": "文件不存在", "file": str(p)}

    text = p.read_text(encoding="utf-8", errors="replace")
    parsed = parse_md_entries(text, source_file=str(p))
    init_kb(kb_dir)
    conn = _connect(kb_dir)
    added = skipped_ai = dup = 0
    try:
        fts = bool(
            conn.execute("SELECT v FROM meta WHERE k='fts'").fetchone()[0] == "1"
        )
        for e in parsed["entries"]:
            if e["is_ai"] and not include_ai:
                skipped_ai += 1
                continue
            exists = conn.execute(
                "SELECT ref_count FROM entries WHERE id=?", (e["id"],)
            ).fetchone()
            if exists:
                conn.execute(
                    "UPDATE entries SET ref_count=ref_count+1 WHERE id=?", (e["id"],)
                )
                dup += 1
                continue
            conn.execute(
                """INSERT INTO entries
                   (id,doc_id,block,locator,body,source_file,sha256,content_hash,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    e["id"],
                    e["doc_id"],
                    e["block"],
                    e["locator"],
                    e["body"],
                    e["source_file"],
                    e["sha256"],
                    e["content_hash"],
                    time.time(),
                ),
            )
            if fts:
                conn.execute(
                    "INSERT INTO entries_fts(id,body) VALUES(?,?)",
                    (e["id"], e["body"]),
                )
            added += 1
        conn.commit()
        if added == 0 and dup == 0 and skipped_ai == 0:
            # 诚实降级：该 md 没有 src 注释 / 块锚点，解析不出任何条目。
            # 如实说明原因，**不谎报入库成功**（否则用户以为收进去了）。
            return {
                "ok": False,
                "error": "未找到 src 来源注释或块锚点，无法入库",
                "file": str(p),
                "doc_id": parsed["doc_id"],
                "added": 0,
                "duplicate": 0,
                "skipped_ai": 0,
            }
        return {
            "ok": True,
            "file": str(p),
            "doc_id": parsed["doc_id"],
            "added": added,
            "duplicate": dup,
            "skipped_ai": skipped_ai,
        }
    except sqlite3.Error as ex:
        conn.rollback()
        return {"ok": False, "error": "入库失败: %s" % ex, "file": str(p)}
    finally:
        conn.close()


def ingest_dir(kb_dir, product_dir, *, include_ai=False, allowed_roots=None) -> dict:
    """把一个产物目录里的 md 全部入库；逐文件报告，单个失败不拖垮整批。"""
    d = Path(product_dir)
    err = _check_allowed(d, allowed_roots)
    if err:
        return {"ok": False, "error": err, "dir": str(d)}
    if not d.is_dir():
        return {"ok": False, "error": "产物目录不存在", "dir": str(d)}

    # v1.0.6 修复（用户 2026-11-20 复盘实测：3 个 md 只扫到 1 个）：
    # 旧实现只扫 md/ 一层（glob 非递归），导致 out/derived/ 下的音视频/
    # Word/链接产物与根级 SUMMARY.md 全部漏掉——知识库只能装阶段 1。
    # 现改为递归扫描，并排除**汇总/对账文件**（内容与 md/ 重复，入库会重复命中）。
    _SKIP_NAMES = {"INDEX.md", "MERGED.md"}
    _SKIP_DIRS = {".git", ".svn", "__pycache__", "node_modules", ".ipynb_checkpoints"}
    mds = []
    for p in sorted(d.rglob("*.md")):
        if p.name in _SKIP_NAMES:
            continue
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        if p.is_file():
            mds.append(p)
    results = []
    for m in mds:
        r = ingest_md(kb_dir, m, include_ai=include_ai, allowed_roots=allowed_roots)
        results.append(r)
    ok_n = sum(1 for r in results if r.get("ok"))
    return {
        "ok": True,
        "dir": str(d),
        "files": len(mds),
        "succeeded": ok_n,
        "failed": len(mds) - ok_n,
        "added": sum(r.get("added", 0) for r in results),
        "duplicate": sum(r.get("duplicate", 0) for r in results),
        "skipped_ai": sum(r.get("skipped_ai", 0) for r in results),
        "details": results,
    }


# ── 检索 ────────────────────────────────────────────────────────────────────
def query(kb_dir, text, *, limit=20) -> dict:
    """关键词检索：优先 FTS5，缺失时降级 LIKE 扫描（诚实提示）。"""
    q = (text or "").strip()
    if not q:
        return {"ok": False, "error": "查询词为空", "results": []}
    db = _db_path(kb_dir)
    if not db.exists():
        return {"ok": True, "mode": "empty", "results": []}
    conn = _connect(kb_dir)
    try:
        meta_f = conn.execute("SELECT v FROM meta WHERE k='fts'").fetchone()
        meta_t = conn.execute("SELECT v FROM meta WHERE k='tokenizer'").fetchone()
        fts = bool(meta_f and meta_f[0] == "1")
        tokenizer = meta_t[0] if meta_t else ""
        results = []
        mode = "like"
        if fts and tokenizer == "trigram" and len(q) >= 3:
            # trigram 支持中文子串；用 LIKE 风格短语，整串作为一个 MATCH 词
            try:
                rows = conn.execute(
                    """SELECT e.* FROM entries_fts f
                       JOIN entries e ON e.id=f.id
                       WHERE entries_fts MATCH ?
                       ORDER BY e.block LIMIT ?""",
                    ('"%s"' % q.replace('"', '""'), limit),
                ).fetchall()
                results = [dict(r) for r in rows]
                mode = "trigram"
            except sqlite3.Error:
                results = []
        if not results:
            # LIKE 兜底：任意长度（含 2 字中文词）、trigram 未命中或不可用时
            like = "%{0}%".format(q.replace("%", "\\%").replace("_", "\\_"))
            rows = conn.execute(
                "SELECT * FROM entries WHERE body LIKE ? ESCAPE '\\' "
                "ORDER BY block LIMIT ?",
                (like, limit),
            ).fetchall()
            results = [dict(r) for r in rows]
            mode = mode if mode == "trigram" else "like"
        # 只回传带来源标注的字段，正文截断
        out = []
        for r in results:
            body = r["body"]
            out.append(
                {
                    "id": r["id"],
                    "doc_id": r["doc_id"],
                    "block": r["block"],
                    "locator": r["locator"],
                    "source_file": r["source_file"],
                    "sha256": r["sha256"],
                    "snippet": body[:200] + ("…" if len(body) > 200 else ""),
                }
            )
        return {"ok": True, "mode": mode, "count": len(out), "results": out}
    finally:
        conn.close()


def open_source(kb_dir, entry_id, *, allowed_roots=None) -> dict:
    """解析条目的原文回跳位置（doc_id + 块锚点 + 来源文件）。"""
    db = _db_path(kb_dir)
    if not db.exists():
        return {"ok": False, "error": "知识库未初始化"}
    conn = _connect(kb_dir)
    try:
        row = conn.execute(
            "SELECT * FROM entries WHERE id=?", (entry_id,)
        ).fetchone()
        if not row:
            return {"ok": False, "error": "条目不存在", "id": entry_id}
        src_file = Path(row["source_file"])
        err = _check_allowed(src_file, allowed_roots)
        if err:
            return {"ok": False, "error": err}
        return {
            "ok": True,
            "id": row["id"],
            "doc_id": row["doc_id"],
            "block": row["block"],
            "locator": row["locator"],
            "source_file": str(src_file),
            "sha256": row["sha256"],
            "exists": src_file.is_file(),
        }
    finally:
        conn.close()
