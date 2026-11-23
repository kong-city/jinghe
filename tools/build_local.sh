#!/usr/bin/env bash
# 精核 · 本地一键打包（封装三个历史坑，见 docs/本地打包指南.md）
#
# 用法（Git Bash / WSL）：
#   bash tools/build_local.sh backend   # ① 只重建后端 exe 并复制到 electron/backend/
#   bash tools/build_local.sh package   # ② 重建后端 + 打 Electron 安装包（--publish never）
#   bash tools/build_local.sh run       # 开发态启动 Electron（已清环境变量）
#   bash tools/build_local.sh verify    # 发版门禁 + 产物自检
#   bash tools/build_local.sh all       # backend + package + verify（默认）
#
# 三个坑的解法已写进本脚本，调用方无需再手动处理：
#   坑1 ELECTRON_RUN_AS_NODE / NODE_OPTIONS —— 入口处直接 unset
#   坑2 后端 exe 必须先就位到 electron/backend/ —— backend 子命令自动复制
#   坑3 win-unpacked 被占用 —— package 前检测并提示结束残留进程

set -euo pipefail

# 坑1：沙箱/IDE 会注入 ELECTRON_RUN_AS_NODE=1，让 Electron 退化成纯 Node
# （--version 输出 v20.x、main.js 不执行、双击无反应）。任何 electron 调用前必须清除。
unset ELECTRON_RUN_AS_NODE
unset NODE_OPTIONS

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# 版本号唯一真源：extract.py::__version__（用 python 提取，避免 shell 引号转义坑）
get_version() {
  python -c 'import re,pathlib,sys; s=pathlib.Path("extract.py").read_text(encoding="utf-8"); m=re.search(r"^__version__\s*=\s*[\"\x27]([^\"\x27]+)", s, re.M); sys.stdout.write(m.group(1) if m else "")'
}

VERSION="$(get_version)"
if [ -z "$VERSION" ]; then
  echo "[ERROR] 无法从 extract.py 读取版本号" >&2
  exit 1
fi
echo "[INFO] 当前版本：$VERSION"

step_backend() {
  echo "===== [1/3] 重建后端 onefile exe ====="
  python build.py
  local out="dist/Jinghe-${VERSION}.exe"
  if [ ! -f "$out" ]; then
    echo "[ERROR] 未找到产物 $out" >&2
    exit 1
  fi
  # 坑2：electron/backend/ 被 gitignore，安装包 extraResources 从这里取件；
  # 漏了这步会出现「包能打出来但装完启动不了」。
  mkdir -p electron/backend
  cp -f "$out" electron/backend/Jinghe.exe
  echo "[OK] 后端 exe 已就位：electron/backend/Jinghe.exe"
  echo "[INFO] 后端自报版本：$(./electron/backend/Jinghe.exe --cli --version 2>&1 | head -1)"
}

step_package() {
  echo "===== [2/3] 打 Electron 安装包 ====="
  # 坑3：应用仍在运行时 electron-builder 重写 win-unpacked 会报 ffmpeg.dll Access denied。
  local stale
  stale="$(tasklist 2>/dev/null | grep -i 'Jinghe.exe' || true)"
  if [ -n "$stale" ]; then
    echo "[WARN] 检测到仍在运行的 Jinghe.exe，打包前请先结束："
    echo "$stale"
    echo "[WARN] 本脚本不强制杀进程，确认后重试。可手动：taskkill /T /F /IM Jinghe.exe"
    exit 1
  fi
  (cd electron && npm run dist -- --publish never)
  echo "[OK] 安装包：electron/release/Jinghe-${VERSION}-setup.exe"
  echo "[OK] 更新元数据：electron/release/latest.yml"
}

step_verify() {
  echo "===== [3/3] 发版门禁 + 产物自检 ====="
  python tools/check_release.py --require-exe
  echo "[INFO] 安装包内容自检（后端是否随包）："
  if [ -f electron/release/win-unpacked/resources/backend/Jinghe.exe ]; then
    echo "[OK] win-unpacked 内后端存在"
  else
    echo "[WARN] 未做免安装目录展开，跳过（仅 NSIS 安装包时可忽略）"
  fi
}

step_run() {
  echo "===== 开发态启动 Electron（已清 ELECTRON_RUN_AS_NODE/NODE_OPTIONS） ====="
  (cd electron && ./node_modules/.bin/electron .)
}

ACTION="${1:-all}"
case "$ACTION" in
  backend)  step_backend ;;
  package)  step_package ;;
  run)      step_run ;;
  verify)   step_verify ;;
  all)      step_backend && step_package && step_verify ;;
  *)
    echo "用法：bash tools/build_local.sh {backend|package|run|verify|all}" >&2
    exit 2
    ;;
esac
