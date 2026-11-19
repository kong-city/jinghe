# -*- coding: utf-8 -*-
"""精核 · PDF 图片页 OCR 可选增强（独立后处理层，冻结内核 extract.py 零改动）。

设计约束：
* 纯标准库；不打包任何 OCR 工具。只在健康探测通过时调用本机
  tesseract + poppler（pdftoppm/pdftocairo）；无工具链时明确回报不可用，
  不假成功、不伪装产物。
* 由 app.py 在提取任务完成后对「需 OCR」的扫描件 PDF 调用，产出补充 md。
* 失败一律返回 {ok:False, error}，由调用方如实留痕。

对外 API：
    status() -> dict                          工具链探测结果（是否可用）
    ocr_pdf_to_md(pdf_path, outdir) -> dict    OCR 并把结果写成 md
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

__version__ = "0.1.0"

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_PROBED = False
_TOOLS: dict | None = None
_PROBED_REASON = ""


def status() -> dict:
    """探测本机 OCR 工具链（tesseract + poppler），结果缓存。"""
    global _PROBED, _TOOLS, _PROBED_REASON
    if not _PROBED:
        _PROBED = True
        tess = shutil.which("tesseract")
        raster = shutil.which("pdftoppm") or shutil.which("pdftocairo")
        raster_kind = "pdftoppm" if shutil.which("pdftoppm") else (
            "pdftocairo" if shutil.which("pdftocairo") else "")
        ok = False
        reason = ""
        if not tess:
            reason = "未找到 tesseract"
        elif not raster:
            reason = "未找到 poppler（pdftoppm/pdftocairo）"
        else:
            try:
                r = subprocess.run([tess, "--version"], stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, timeout=8,
                                   creationflags=_CREATE_NO_WINDOW)
                if r.returncode == 0:
                    ok = True
                else:
                    reason = "tesseract 冒烟探测失败"
            except Exception as exc:
                reason = "tesseract 探测异常：%s" % exc
        _TOOLS = ({"tesseract": tess, "raster": raster, "raster_kind": raster_kind}
                  if ok else None)
        if not ok and not reason:
            reason = "OCR 工具链不可用"
        _PROBED_REASON = reason
    return {
        "ok": True,
        "available": _TOOLS is not None,
        "reason": "" if _TOOLS else _PROBED_REASON,
        "hint": "安装 tesseract 与 poppler 后，扫描件 PDF 的图片页将自动识别",
    }


def ocr_pdf(pdf_path: str | Path) -> tuple[str, str]:
    """对 PDF 所有页做 OCR，返回 (合并文本, 状态文案)。失败抛异常。"""
    st = status()
    if not st["available"]:
        raise RuntimeError(st["reason"] or "OCR 工具链不可用")
    tools = _TOOLS
    pdf = Path(pdf_path)
    if not pdf.is_file():
        raise RuntimeError("PDF 不存在：%s" % pdf)
    tmpdir = Path(tempfile.mkdtemp(prefix="jinghe-ocr-"))
    try:
        prefix = tmpdir / "page"
        cmd = [tools["raster"], "-png", "-r", "200", str(pdf), str(prefix)]
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=180, creationflags=_CREATE_NO_WINDOW)
        if r.returncode != 0:
            raise RuntimeError("PDF 渲染为图片失败")
        pages = sorted(tmpdir.glob("page-*.png"))
        if not pages:
            raise RuntimeError("未渲染出页面图片")
        chunks = []
        for png in pages:
            # 优先中英混合，失败退英文（语言包未装时不至于全盘失败）
            for langs in ("chi_sim+eng", "eng"):
                try:
                    out = subprocess.run(
                        [tools["tesseract"], str(png), "stdout", "-l", langs],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        timeout=120, creationflags=_CREATE_NO_WINDOW)
                    txt = out.stdout.decode("utf-8", "replace").strip()
                    if out.returncode == 0 and txt:
                        chunks.append(txt)
                        break
                except Exception:
                    continue
        text = "\n\n".join(chunks).strip()
        if not text:
            raise RuntimeError("OCR 未识别出任何文字")
        return text, "成功（OCR）"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def ocr_pdf_to_md(pdf_path: str | Path, outdir: str | Path) -> dict:
    """OCR 指定 PDF 并把结果写成 outdir 下的同名 md（不覆盖已存在的成功产物）。"""
    pdf = Path(pdf_path)
    out = Path(outdir)
    try:
        text, state = ocr_pdf(pdf)
        out.mkdir(parents=True, exist_ok=True)
        md = out / (pdf.stem + ".md")
        if md.exists():
            existing = md.read_text(encoding="utf-8", errors="replace").strip()
            # 已有实质文本产物（非"需 OCR"占位）就不覆盖
            if existing and "需先 OCR" not in existing and len(existing) > 40:
                return {"ok": True, "skipped": True, "path": str(md),
                        "state": "已有文本产物", "chars": len(existing)}
        md.write_text("# %s\n\n%s\n" % (pdf.name, text), encoding="utf-8")
        return {"ok": True, "skipped": False, "path": str(md),
                "state": state, "chars": len(text)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
