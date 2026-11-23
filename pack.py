
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键打源码包：python pack.py

产物：dist/jinghe-stage1-v<软件版本>-<yyyymmdd>.zip
包内根目录固定为 jinghe-stage1/，并生成 MANIFEST.txt（sha256 + 字节数 + 相对路径）。

为什么用白名单而不是排除法：排除法一旦新增目录（比如 `.venv`、`node_modules`、
编辑器临时目录）就会悄悄把垃圾打进包；白名单漏了会少文件，但 `--check` 能立刻发现。

用法：
    python pack.py            # 打包
    python pack.py --check    # 只校验必需文件齐不齐，不写包
"""

from __future__ import annotations


import datetime
import hashlib
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PKG_ROOT = "jinghe-stage1"

# 顶层单文件（白名单）
TOP_FILES = [
    "SPEC.md",
    "app.py",
    "extract.py",
    "build.py",
    "build.spec",
    "pack.py",
    "test_extract.py",
    "test_app.py",
    "使用说明.md",
]
# 整目录递归收录（白名单）
# 2026-11-23 源码分层：5 个业务模块子目录必须收录，否则源码包缺 24 个模块
TOP_DIRS = ["ui", "vendor", "samples", "out",
            "core", "media", "knowledge", "link", "subs"]
# 兜底排除（即使是白名单目录内也跳过）
SKIP_NAMES = {"__pycache__", ".DS_Store", "Thumbs.db"}


def software_version() -> str:
    """从 extract.py 读 __version__（软件版本的唯一来源），不 import 以免副作用。"""
    text = (ROOT / "extract.py").read_text(encoding="utf-8", errors="replace")
    m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', text, re.M)
    if not m:
        raise SystemExit("[ERROR] extract.py 里找不到 __version__")
    return m.group(1)


def collect() -> list[Path]:
    files: list[Path] = []
    missing: list[str] = []
    for name in TOP_FILES:
        p = ROOT / name
        if p.is_file():
            files.append(p)
        else:
            missing.append(name)
    for name in TOP_DIRS:
        d = ROOT / name
        if not d.is_dir():
            missing.append(name + "/")
            continue
        for child in sorted(d.rglob("*")):
            if not child.is_file():
                continue
            if any(part in SKIP_NAMES for part in child.relative_to(ROOT).parts):
                continue
            if child.suffix == ".pyc":
                continue
            files.append(child)
    if missing:
        print("[WARN] 白名单里缺失（未打进包）: %s" % ", ".join(missing))
    return sorted(set(files), key=lambda p: p.relative_to(ROOT).as_posix())


def main(argv: list[str]) -> int:
    files = collect()
    if not files:
        print("[ERROR] 没有可打包的文件", file=sys.stderr)
        return 1

    version = software_version()
    total = sum(f.stat().st_size for f in files)
    print("[INFO] 软件版本 %s；收录 %d 个文件，合计 %.1f KB" % (version, len(files), total / 1024.0))

    if "--check" in argv:
        for f in files:
            print("  %8d  %s" % (f.stat().st_size, f.relative_to(ROOT).as_posix()))
        return 0

    manifest = ["# 精核 阶段1 包清单（sha256，按路径排序）", ""]
    for f in files:
        data = f.read_bytes()
        manifest.append("%s  %8d  %s" % (
            hashlib.sha256(data).hexdigest(), len(data), f.relative_to(ROOT).as_posix()))
    manifest_text = "\n".join(manifest) + "\n"

    stamp = datetime.date.today().strftime("%Y%m%d")
    out_zip = ROOT / "dist" / ("jinghe-stage1-v%s-%s.zip" % (version, stamp))
    out_zip.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in files:
            arcname = "%s/%s" % (PKG_ROOT, f.relative_to(ROOT).as_posix())
            info = zipfile.ZipInfo(arcname)
            info.compress_type = zipfile.ZIP_DEFLATED
            # 强制 UTF-8 文件名标志位（bit 11 / 0x800），避免中文名（如使用说明.md）
            # 在部分解包工具下被按系统代码页解码成乱码。
            info.flag_bits |= 0x800
            z.writestr(info, f.read_bytes())
        minfo = zipfile.ZipInfo("%s/MANIFEST.txt" % PKG_ROOT)
        minfo.compress_type = zipfile.ZIP_DEFLATED
        minfo.flag_bits |= 0x800
        z.writestr(minfo, manifest_text.encode("utf-8"))

    size = out_zip.stat().st_size
    digest = hashlib.sha256(out_zip.read_bytes()).hexdigest()
    print("[OK] %s" % out_zip)
    print("     条目 %d（含 MANIFEST）/ 包体 %d B (%.1f KB)" % (len(files) + 1, size, size / 1024.0))
    print("     sha256 %s" % digest)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
