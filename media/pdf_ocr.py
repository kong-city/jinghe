# -*- coding: utf-8 -*-
"""精核 · PDF 图片页 OCR 可选增强（独立后处理层，冻结内核 extract.py 零改动）。

设计约束：
* 主程序零第三方依赖（PyInstaller 打包不带 OCR 库）。OCR 引擎
  （pymupdf + rapidocr-onnxruntime）作为**组件**点击安装进软件自管 venv；
  本模块只派发子进程 venv python 执行 tools/ocr_worker.py。
* 无组件时明确回报不可用、不假成功、不伪装产物。
* 由 app.py 在提取任务完成后对「需 OCR」的扫描件 PDF 调用，产出补充 md。
* 失败一律返回 {ok:False, error}，由调用方如实留痕。

对外 API（v1.5.0 保持签名不变，内部引擎替换）：
    status() -> dict                          工具链探测结果（是否可用）
    ocr_pdf(pdf_path, max_pages=0) -> tuple    保留原签名；返回 (文本, 状态文案)
    ocr_pdf_to_md(pdf_path, outdir, ...) -> dict   OCR 并把结果写成 md

v1.7.2 增强（冻结内核 extract.py 零改动，全部在独立后处理层）：
    * worker 产出置信度旁车，本模块读回并随结果返回 quality 字段；
    * ocr_pdf_to_md 新增 force/max_pages 可选参数，修复「部分乱码但过质量门禁
      的件因已有 >40 字产物被误跳过」的漏洞——调用方可按 provenance 降级状态
      精确强制重跑；
    * 低置信度只在返回里提示，不阻断产物生成（诚实降级，不假成功）。
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

__version__ = "0.3.0"

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _resource_dir() -> Path:
    """打包后资源在 sys._MEIPASS（worker 随 datas 打进 tools/），源码态用项目根。"""
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) if base else Path(__file__).resolve().parent.parent


_ROOT = _resource_dir()
_WORKER = _ROOT / "tools" / "ocr_worker.py"
_LOCALAPPDATA = os.environ.get("LOCALAPPDATA") or str(Path.home())
_COMPONENT_DIR = Path(_LOCALAPPDATA) / "Jinghe" / "components"
_VENV_PYTHON = _COMPONENT_DIR / "venv" / "Scripts" / "python.exe"

# 需要 venv 里真实可导入的包（探测与 OCR 前都校验）
_REQUIRED_MODULES = ("fitz", "rapidocr_onnxruntime")
_PROBED = False
_AVAILABLE = False
_REASON = ""


def _find_interpreter() -> str:
    """定位能跑 OCR 的 Python：优先组件 venv，其次当前解释器。"""
    if _VENV_PYTHON.is_file():
        return str(_VENV_PYTHON)
    return sys.executable


def _check_modules(py: str) -> tuple[bool, str]:
    """真跑一次 import 校验（不是只看文件在不在）。"""
    code = "import " + ", ".join(_REQUIRED_MODULES)
    try:
        r = subprocess.run(
            [py, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", timeout=60,
            creationflags=_CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, "探测 OCR 组件异常：%s" % exc
    if r.returncode == 0:
        return True, ""
    lines = (r.stdout or "").strip().splitlines()
    return False, lines[-1][:200] if lines else "OCR 组件不可用"


def status(force: bool = False) -> dict:
    """探测 OCR 组件是否可用（结果缓存，force=True 强制重探）。"""
    global _PROBED, _AVAILABLE, _REASON
    if not _PROBED or force:
        _PROBED = True
        py = _find_interpreter()
        ok, reason = _check_modules(py)
        # 用了当前解释器但没装包 → 明确提示去设置页点「启用」
        if not ok and py == sys.executable:
            reason = "未安装 OCR 组件（请在 设置 · 组件 中点击启用）"
        _AVAILABLE = ok
        _REASON = reason
    return {
        "ok": True,
        "available": _AVAILABLE,
        "reason": "" if _AVAILABLE else _REASON,
        "hint": "在「设置 · 组件」中点击启用「扫描件 OCR」，"
                "系统会自动安装识别引擎，之后扫描件 PDF 的图片页将自动识别",
    }


def _read_quality(out_txt: Path) -> dict:
    """读 worker 写出的置信度旁车；缺失时返回空 dict（旧版 worker 兼容）。"""
    side = Path(str(out_txt) + ".meta.json")
    if not side.is_file():
        return {}
    try:
        import json
        data = json.loads(side.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _quality_hint(quality: dict) -> str:
    """把置信度翻成可写进日志的短文案；无数据返回空串。"""
    if not quality:
        return ""
    avg = quality.get("avg_confidence")
    low = quality.get("low_confidence_pages") or []
    parts: list[str] = []
    if isinstance(avg, (int, float)):
        parts.append("平均置信度 %.2f" % float(avg))
    if low:
        parts.append("低置信页 %s（建议复核）" %
                     ",".join(str(p) for p in low[:8]))
    return "，".join(parts)


def _ocr_pdf_raw(pdf_path: str | Path, max_pages: int = 0) -> tuple[str, str, dict]:
    """内部：返回 (文本, 状态文案, 质量字典)。失败抛异常。"""
    st = status()
    if not st["available"]:
        raise RuntimeError(st["reason"] or "OCR 组件未安装")
    pdf = Path(pdf_path)
    if not pdf.is_file():
        raise RuntimeError("PDF 不存在：%s" % pdf)
    if not _WORKER.is_file():
        raise RuntimeError("OCR worker 缺失：%s" % _WORKER)

    tmpdir = Path(tempfile.mkdtemp(prefix="jinghe-ocr-"))
    out_txt = tmpdir / "ocr.txt"
    try:
        cmd = [_find_interpreter(), str(_WORKER), str(pdf), str(out_txt)]
        if max_pages > 0:
            cmd.extend(["--max-pages", str(max_pages)])
        r = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", timeout=900,
            creationflags=_CREATE_NO_WINDOW)
        if r.returncode != 0:
            detail = (r.stdout or "").strip().splitlines()
            msg = detail[-1][:200] if detail else "OCR 子进程失败"
            raise RuntimeError(msg)
        text = out_txt.read_text(encoding="utf-8", errors="replace").strip()
        if not text:
            raise RuntimeError("OCR 未识别出任何文字")
        quality = _read_quality(out_txt)
        state = "成功（OCR）"
        hint = _quality_hint(quality)
        if hint:
            state += "，" + hint
        # 置信度字典随结果带出，供上层写入质量报告（不阻断产物）
        return text, state, quality
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def ocr_pdf(pdf_path: str | Path, max_pages: int = 0) -> tuple[str, str]:
    """对 PDF 做 OCR，返回 (合并文本, 状态文案)（v1.5.0 签名保持不变）。"""
    text, state, _quality = _ocr_pdf_raw(pdf_path, max_pages)
    return text, state


def ocr_pdf_to_md(pdf_path: str | Path, outdir: str | Path,
                  force: bool = False, max_pages: int = 0) -> dict:
    """OCR 指定 PDF 并把结果写成 outdir 下的同名 md。

    force=False（默认）：已有 >40 字且非「需先 OCR」的产物时跳过，保持旧行为。
    force=True：忽略已有产物强制重跑——用于 provenance 标记为 CID 降级 /
    疑似扫描件但内核仍产出疑似乱码的件；此时即使已有产物也以 OCR 结果覆盖。

    返回值在 v1.5.0 的 ok/skipped/path/state/chars 基础上新增 quality 字段。
    """
    pdf = Path(pdf_path)
    out = Path(outdir)
    try:
        md = out / (pdf.stem + ".md")
        if not force and md.exists():
            existing = md.read_text(encoding="utf-8", errors="replace").strip()
            if existing and "需先 OCR" not in existing and len(existing) > 40:
                return {"ok": True, "skipped": True, "path": str(md),
                        "state": "已有文本产物", "chars": len(existing),
                        "quality": {}}

        text, state, quality = _ocr_pdf_raw(pdf, max_pages)
        out.mkdir(parents=True, exist_ok=True)
        # 溯源注释：标记这是 OCR 后处理产物（含质量信息），不写冻结对账盘
        header = "<!-- ocr: engine=rapidocr-onnxruntime"
        if quality:
            header += ", avg_conf=%s" % quality.get("avg_confidence", "n/a")
            low = quality.get("low_confidence_pages") or []
            if low:
                header += ", low_pages=%s" % ",".join(str(p) for p in low[:8])
        header += " -->\n"
        md.write_text(header + "# %s\n\n%s\n" % (pdf.name, text), encoding="utf-8")
        return {"ok": True, "skipped": False, "path": str(md),
                "state": state, "chars": len(text), "quality": quality}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
