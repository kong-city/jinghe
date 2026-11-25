#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""组装「精核 · Electron 版」免安装目录（零第三方依赖，纯标准库）。

为什么不直接用 electron-builder：
  国内网络下 electron-builder 会从 GitHub 下载 NSIS / winCodeSign 等二进制，
  极慢且常卡住。但 npm install 已经把完整 Electron 运行时装到
  node_modules/electron/dist（含全部 DLL），本脚本直接复用它组装出可运行目录，
  绕开任何额外下载。CI（境外）里仍可用 npm run dist 出 NSIS 安装包。

产物：release/win-unpacked/
  ├── Jinghe.exe            （由 electron.exe 改名，独立图标/任务栏名）
  ├── *.dll / *.pak / ...   （Electron 运行时）
  └── resources/
      ├── app/              （应用代码：main.js / preload.js / package.json）
      │   └── node_modules/ （无需，主进程只用 Node 内置模块）
      └── backend/
          └── Jinghe.exe    （PyInstaller 后端，~9.6MB）

用法：
  python pack_portable.py            # 组装
  python pack_portable.py --size     # 只报告体积
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DIST = HERE / "node_modules" / "electron" / "dist"
# 允许用 JINGHE_PACK_OUT 指定输出目录名（沙箱禁止删除时可换全新目录组装）
OUT = HERE / "release" / os.environ.get("JINGHE_PACK_OUT", "win-unpacked")
BACKEND_SRC = HERE / "backend" / "Jinghe.exe"
APP_FILES = ["main.js", "preload.js", "package.json"]


def current_version() -> str:
    pkg = json.loads((HERE / "package.json").read_text(encoding="utf-8"))
    return str(pkg.get("version", ""))


def human(n: int) -> str:
    return "%.1f MB" % (n / 1024 / 1024)


def dir_size(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def assemble() -> int:
    if not DIST.is_dir():
        print("[ERROR] 找不到 Electron 运行时：%s\n请先 npm install" % DIST, file=sys.stderr)
        return 1
    if not BACKEND_SRC.is_file():
        print("[ERROR] 找不到后端 exe：%s\n请先 python build.py 并拷贝到 backend/" % BACKEND_SRC,
              file=sys.stderr)
        return 1

    if OUT.exists():
        try:
            shutil.rmtree(OUT)
        except OSError:
            # 某些沙箱环境禁止删除操作：退而求其次，把旧产物重命名挪走。
            import time
            stale = OUT.with_name(OUT.name + ".stale-%d" % int(time.time()))
            try:
                OUT.rename(stale)
            except OSError:
                pass
    OUT.mkdir(parents=True, exist_ok=True)

    # 1) 复制 Electron 运行时全部文件
    for item in DIST.iterdir():
        if item.name.lower() in ("debug.log",):
            continue
        dst = OUT / item.name
        if item.is_dir():
            # 复制阶段就排除 default_app.asar，避免事后 unlink 触发沙箱安全删除拦截。
            shutil.copytree(item, dst,
                            ignore=shutil.ignore_patterns("default_app.asar"))
        else:
            shutil.copy2(item, dst)

    # 2) exe 改名为产品名
    exe = OUT / "electron.exe"
    if exe.is_file():
        exe.rename(OUT / "Jinghe.exe")

    # 3) 应用代码放到 resources/app/
    app_dir = OUT / "resources" / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    # default_app.asar 已在复制阶段用 ignore_patterns 排除；这里仅作兜底，
    # 且吞掉沙箱对 unlink 的拦截异常（某些环境禁止删除操作）。
    try:
        (OUT / "resources" / "default_app.asar").unlink(missing_ok=True)
    except OSError:
        pass
    for name in APP_FILES:
        src = HERE / name
        if not src.is_file():
            print("[ERROR] 缺少应用文件 %s" % src, file=sys.stderr)
            return 1
        shutil.copy2(src, app_dir / name)

    # 3.1) 主进程依赖：main.js 顶层 require('electron-updater')，缺依赖会直接崩溃。
    # 只复制 updater 的依赖闭包，避免把 electron-builder 全家桶（数百 MB）打进免安装版。
    nm_src = HERE / "node_modules"
    if nm_src.is_dir():
        import json
        wanted, queue = set(), ["electron-updater"]
        while queue:
            name = queue.pop(0)
            if name in wanted:
                continue
            wanted.add(name)
            pj = nm_src / name / "package.json"
            if not pj.is_file():
                continue
            try:
                meta = json.loads(pj.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for dep in list(meta.get("dependencies", {})) + list(meta.get("optionalDependencies", {})):
                queue.append(dep)
        for name in sorted(wanted):
            src = nm_src / name
            if not src.is_dir():
                continue
            dst = app_dir / "node_modules" / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dst, dirs_exist_ok=True)

    # 4) 后端 exe 放到 resources/backend/（main.js 打包态优先读这里）
    backend_dir = OUT / "resources" / "backend"
    backend_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(BACKEND_SRC, backend_dir / "Jinghe.exe")

    # 5) 品牌图标真源放到 resources/icon.png，托盘与桌面图标同源。
    # 缺这个文件时 main.js 会回退到内嵌 16x16 兜底图，视觉上像「图标被换过」。
    icon = HERE / "build" / "icon.png"
    if icon.is_file():
        shutil.copy2(icon, OUT / "resources" / "icon.png")

    total = dir_size(OUT)
    print("[OK] 免安装版已组装：%s" % OUT)
    print("     版本 v%s · 总体积 %s" % (current_version(), human(total)))
    print("     后端 %s · Electron 运行时 %s"
          % (human(BACKEND_SRC.stat().st_size), human(dir_size(OUT) - BACKEND_SRC.stat().st_size)))
    return 0


def report_size() -> int:
    if not OUT.is_dir():
        print("[ERROR] 尚未组装，请先不带参数运行", file=sys.stderr)
        return 1
    total = dir_size(OUT)
    exe = OUT / "Jinghe.exe"
    print("版本        : v%s" % current_version())
    print("免安装目录  : %s" % OUT)
    print("总体积      : %s (%d bytes)" % (human(total), total))
    if exe.is_file():
        print("主程序 exe  : %s" % human(exe.stat().st_size))
    backend = OUT / "resources" / "backend" / "Jinghe.exe"
    if backend.is_file():
        print("后端 exe    : %s" % human(backend.stat().st_size))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="组装精核 Electron 免安装版")
    ap.add_argument("--size", action="store_true", help="只报告已组装产物体积")
    args = ap.parse_args()
    return report_size() if args.size else assemble()


if __name__ == "__main__":
    sys.exit(main())
