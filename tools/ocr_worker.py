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

成功：退出码 0，识别文本写入 out_txt_path（UTF-8）。
失败：退出码非 0，原因写 stderr。
"""
from __future__ import annotations

import sys
from pathlib import Path


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
        engine = RapidOCR()
        doc = fitz.open(str(pdf))
        total = doc.page_count
        limit = min(total, max_pages) if max_pages > 0 else total
        chunks: list[str] = []
        for i in range(limit):
            page = doc.load_page(i)
            # 2x 缩放（约 144dpi），文字清晰且内存可控
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            img_bytes = pix.tobytes("png")
            result, _ = engine(img_bytes)
            if result:
                lines = [item[1] for item in result if len(item) >= 2 and item[1]]
                if lines:
                    chunks.append("\n".join(lines))
        doc.close()
        text = "\n\n".join(chunks).strip()
        if not text:
            print("OCR 未识别出任何文字", file=sys.stderr)
            return 4
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        return 0
    except Exception as exc:  # noqa: BLE001 - worker 必须把任何异常落地为退出码
        print("OCR 识别失败：%s" % exc, file=sys.stderr)
        return 5


if __name__ == "__main__":
    sys.exit(main())
