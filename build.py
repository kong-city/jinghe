#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键打包：python build.py

等价于 `python -m PyInstaller --noconfirm --clean build.spec`，
产物为 dist/Jinghe.exe（onefile / windowed）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    spec = ROOT / "build.spec"
    if not spec.is_file():
        print("[ERROR] 找不到 build.spec", file=sys.stderr)
        return 1
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(spec)]
    print("[INFO] " + " ".join(cmd), flush=True)
    return subprocess.call(cmd, cwd=str(ROOT))


if __name__ == "__main__":
    sys.exit(main())
