#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精核 · OCR 子进程 worker（在组件 venv 的 Python 下运行）。

为什么需要独立 worker：主程序零第三方依赖（PyInstaller 打包不带 OCR 包），
而 rapidocr-onnxruntime / pymupdf 装在软件自管的 venv 里。故 OCR 走子进程：
主进程把 PDF 路径交给 venv python 执行本脚本，识别结果写进指定的输出文件。

约定：
    python ocr_worker.py <pdf_path> <out_txt_path> [--max-pages N]

依赖（由 ocr 组件点击安装到 venv）：
    pymupdf              —— 把 PDF 页渲染成像素（替代 poppler）
    rapidocr-onnxruntime —— 纯 Python OCR（替代 tesseract，自带中英模型）

成功：退出码 0，识别文本写入 out_txt_path（UTF-8）；
      置信度统计写入旁车 <out_txt_path>.meta.json（不影响原接口）。
失败：退出码非 0，原因写 stderr。

v1.7.2 增强（不触碰冻结内核 extract.py）：
    1. 引入离线 OCR 清洗（水印 / 高置信误识 / 断行折叠），清洗模块随包携带；
    2. 保留 RapidOCR 每页置信度，输出平均置信度与低置信页数供上层提示；
    3. 逐页释放像素缓冲，降低大文件 OCR 的内存峰值。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# 低置信页阈值：低于此平均分的页会被计数，仅用于提示，不阻断产物。
_LOW_CONF_PAGE = 0.60
_SIDECAR_SUFFIX = ".meta.json"


def _load_cleaner():
    """优先复用项目现成的保守清洗器；缺失时退化为最小内置清洗。

    worker 由组件 venv 的 python 执行，sys.path[0] 即本脚本所在 tools/ 目录，
    clean_ocr.py 随包携带（build.spec datas），因此正常都能导入。
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from clean_ocr import clean  # type: ignore
        return clean
    except Exception:
        # 兜底：只做控制字符清理 + 空行折叠，保证任何环境都有基本清洗
        import re

        def _basic_clean(text: str) -> str:
            text = "".join(
                c for c in text
                if c in "\n\r\t" or ord(c) >= 32
            )
            return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"
        return _basic_clean


def _confidence_of(result) -> tuple[float, int]:
    """从 RapidOCR 结果算 (平均置信度, 有效行数)；无有效分数返回 (0.0, 0)。"""
    scores: list[float] = []
    for item in result or []:
        if not isinstance(item, (list, tuple)) or len(item) < 3:
            continue
        try:
            score = float(item[2])
        except (TypeError, ValueError):
            continue
        if 0.0 <= score <= 1.0:
            scores.append(score)
    if not scores:
        return 0.0, 0
    return round(sum(scores) / len(scores), 4), len(scores)


def main() -> int:
    if len(sys.argv) < 3:
        print("用法: ocr_worker.py <pdf> <out.txt> [--max-pages N]", file=sys.stderr)
        return 2
    pdf = Path(sys.argv[1])
    out = Path(sys.argv[2])
    max_pages = 0
    if "--max-pages" in sys.argv:
        try:
            max_pages = int(sys.argv[sys.argv.index("--max-pages") + 1])
        except (ValueError, IndexError):
            pass
    if not pdf.is_file():
        print("PDF 不存在：%s" % pdf, file=sys.stderr)
        return 2

    try:
        import fitz  # pymupdf
    except Exception as exc:
        print("缺少 pymupdf：%s" % exc, file=sys.stderr)
        return 3
    try:
        from rapidocr_onnxruntime import RapidOCR
    except Exception as exc:
        print("缺少 rapidocr-onnxruntime：%s" % exc, file=sys.stderr)
        return 3

    try:
        cleaner = _load_cleaner()
        engine = RapidOCR()
        doc = fitz.open(str(pdf))
        total = doc.page_count
        limit = min(total, max_pages) if max_pages > 0 else total
        chunks: list[str] = []
        page_stats: list[dict] = []
        for i in range(limit):
            page = doc.load_page(i)
            # 2x 缩放（约 144dpi），文字清晰且内存可控
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            img_bytes = pix.tobytes("png")
            # 大文件逐页释放像素缓冲：pix 常驻会随页数线性推高内存峰值
            del pix
            result, _ = engine(img_bytes)
            del img_bytes
            lines = []
            conf, nlines = _confidence_of(result)
            if result:
                lines = [item[1] for item in result
                         if isinstance(item, (list, tuple)) and len(item) >= 2 and item[1]]
            if lines:
                chunks.append("\n".join(lines))
            page_stats.append({
                "page": i + 1,
                "confidence": conf,
                "lines": nlines,
                "low": bool(nlines and conf < _LOW_CONF_PAGE),
            })
        doc.close()
        text = "\n\n".join(chunks).strip()
        if not text:
            print("OCR 未识别出任何文字", file=sys.stderr)
            return 4
        text = cleaner(text).strip()
        if not text:
            print("OCR 清洗后无有效文本", file=sys.stderr)
            return 4

        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")

        valid = [p for p in page_stats if p["lines"] > 0]
        avg = (round(sum(p["confidence"] * p["lines"] for p in valid)
                     / sum(p["lines"] for p in valid), 4)
               if valid else 0.0)
        sidecar = {
            "engine": "rapidocr-onnxruntime",
            "pages_total": total,
            "pages_ocr": limit,
            "pages_with_text": len(valid),
            "avg_confidence": avg,
            "low_confidence_pages": [p["page"] for p in valid if p["low"]],
            "low_threshold": _LOW_CONF_PAGE,
            "cleaned": True,
        }
        Path(str(out) + _SIDECAR_SUFFIX).write_text(
            json.dumps(sidecar, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0
    except Exception as exc:  # noqa: BLE001 - worker 必须把任何异常落地为退出码
        print("OCR 识别失败：%s" % exc, file=sys.stderr)
        return 5


if __name__ == "__main__":
    sys.exit(main())
