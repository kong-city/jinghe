#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键打包：python build.py

等价于 `python -m PyInstaller --noconfirm --clean build.spec`，
先产出 dist/Jinghe.exe（onefile / windowed），再按当前软件版本重命名为
``dist/Jinghe-<version>.exe``（如 Jinghe-0.8.4.exe），作为唯一对外产物。

为什么 PyInstaller 内部仍叫 Jinghe.exe：
* 自我重入 `exe --cli ...`、app.py/extract.py 的冻结态判断都引用这个名字；
* 只在打包完成后重命名对外文件，避免触碰内部契约。
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def current_version() -> str:
    src = (ROOT / "extract.py").read_text(encoding="utf-8")
    m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', src, re.M)
    return m.group(1) if m else ""


def main() -> int:
    spec = ROOT / "build.spec"
    if not spec.is_file():
        print("[ERROR] 找不到 build.spec", file=sys.stderr)
        return 1
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(spec)]
    print("[INFO] " + " ".join(cmd), flush=True)
    rc = subprocess.call(cmd, cwd=str(ROOT))
    if rc != 0:
        return rc
    # 打包成功后重命名为带版本号的对外产物
    version = current_version()
    if not version:
        print("[WARN] 无法读取版本号，保留 dist/Jinghe.exe", file=sys.stderr)
        return 0
    dist = ROOT / "dist"
    src_exe = dist / "Jinghe.exe"
    dst_exe = dist / ("Jinghe-%s.exe" % version)
    if src_exe.is_file():
        if dst_exe.exists():
            dst_exe.unlink()
        src_exe.rename(dst_exe)
        print("[OK] 对外产物：%s（%d 字节）" % (dst_exe.name, dst_exe.stat().st_size))
    return 0


if __name__ == "__main__":
    sys.exit(main())
