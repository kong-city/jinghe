#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精核 · 发版一致性门禁（零第三方依赖）。

软件版本号唯一来源是 ``extract.py`` 的 ``__version__``。本脚本在 CI 与本地
发版前校验所有引用点是否同步，避免「改了版本号，界面 / 文档 / CHANGELOG
还停在旧版」这类漂移。

用法：
    python tools/check_release.py                 # 自动：exe 存在则校验，不存在则跳过
    python tools/check_release.py --no-exe        # CI 测试阶段：完全跳过 exe
    python tools/check_release.py --require-exe   # CI 发布阶段：exe 必须存在

退出码：0 = 全部通过；1 = 有校验项失败。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.\-]+)?$")
HARDCODED_TAG = re.compile(r">\s*v\d+\.\d+\.\d+\s*<")


def _force_utf8_streams() -> None:
    """Windows runner 默认 cp1252，打印中文会抛 UnicodeEncodeError。

    v0.4.0 的 CI 因此挂在「全量单元测试」里的门禁子进程，发布作业被
    整体跳过，Release 从未生成 exe 资产。这里只重配置真实的终端 / 管道
    流（TextIOWrapper）；被 unittest 捕获的 StringIO 没有 reconfigure，
    直接跳过，不影响测试替身。
    """
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError, TypeError):
            pass


def _read(rel: str) -> str:
    p = ROOT / rel
    if not p.is_file():
        raise FileNotFoundError(rel)
    return p.read_text(encoding="utf-8")


def evaluate_exe(version: str, dist_dir: Path, *, require_exe: bool,
                 no_exe: bool) -> tuple[bool, str, str]:
    """判定 exe 产物校验项，返回 (ok, 检查项名称, 详情)。

    抽成纯函数便于隔离单测（可传临时 dist 目录构造「只有旧版 exe」等场景）。
    发布阶段（require_exe）只认当前版本的精确产物 dist/Jinghe-<version>.exe，
    否则「代码升到新版但包还是旧的」会静默通过 —— 2026-11-23 实测缺陷。
    """
    if no_exe:
        return True, "exe 产物", "CI 测试阶段按 --no-exe 跳过"

    exact_exe = dist_dir / ("Jinghe-%s.exe" % version)
    legacy_exe = dist_dir / "Jinghe.exe"
    # 保留 glob：test_64 断言门禁识别带版本号产物命名
    versioned = sorted(dist_dir.glob("Jinghe-*.exe"))

    if require_exe:
        if exact_exe.is_file():
            size = exact_exe.stat().st_size
            return (size > 1024 * 1024, "exe 产物版本匹配",
                    "%s · %d 字节" % (exact_exe.name, size))
        found = [p.name for p in versioned]
        if legacy_exe.is_file():
            found.append(legacy_exe.name)
        return (False, "exe 产物版本匹配",
                "缺 dist/Jinghe-%s.exe（现有: %s）"
                % (version, ", ".join(found) or "无"))

    # 本地开发阶段：优先当前版本；无则容忍任意 exe 但提示重建，不静默放过。
    if exact_exe.is_file():
        size = exact_exe.stat().st_size
        return (size > 1024 * 1024, "exe 产物可用",
                "%s · %d 字节" % (exact_exe.name, size))
    fallback = legacy_exe if legacy_exe.is_file() else (
        versioned[0] if versioned else None)
    if fallback is not None and fallback.is_file():
        size = fallback.stat().st_size
        return (size > 1024 * 1024, "exe 产物可用（非当前版本）",
                "%s · %d 字节；当前版本 %s 尚未构建，建议先 python build.py"
                % (fallback.name, size, version))
    return True, "exe 产物", "尚未构建，本地开发阶段跳过"


def main(argv: list[str] | None = None) -> int:
    _force_utf8_streams()
    ap = argparse.ArgumentParser(description="精核发版一致性门禁")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--no-exe", action="store_true", help="跳过 exe 校验")
    g.add_argument("--require-exe", action="store_true", help="exe 必须存在")
    args = ap.parse_args(argv)

    results: list[tuple[bool, str, str]] = []

    def check(ok: bool, name: str, detail: str = "") -> None:
        results.append((bool(ok), name, detail))

    # ① 版本号唯一来源：extract.py 必须能解析出合法语义化版本
    version = ""
    try:
        src = _read("extract.py")
        m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', src, re.M)
        version = m.group(1) if m else ""
    except (OSError, UnicodeError) as exc:
        check(False, "extract.py 可读", str(exc))
    check(bool(version) and bool(SEMVER.match(version)),
          "版本号唯一来源 extract.py", "__version__ = %r" % version)

    if not version:
        for ok, name, detail in results:
            print("[%s] %s %s" % ("OK" if ok else "FAIL", name, detail))
        return 1

    # ② 页面不得硬编码版本号（由 /api/state 动态注入）
    try:
        html = _read("ui/index.html")
        tag = re.search(r'id="headerTag"[^>]*>([^<]*)<', html)
        tag_text = tag.group(1).strip() if tag else ""
        check('id="headerTag"' in html and not HARDCODED_TAG.search(html),
              "ui/index.html 无硬编码版本", "headerTag 占位符 = %r" % tag_text)
    except (OSError, UnicodeError) as exc:
        check(False, "ui/index.html 可读", str(exc))

    # ③ 前端确实从后端 state 注入版本
    try:
        js = _read("ui/app.js")
        check("headerTag" in js and '"/api/state"' in js
              and re.search(r'headerTag\.textContent\s*=', js) is not None,
              "ui/app.js 由 /api/state 注入版本")
    except (OSError, UnicodeError) as exc:
        check(False, "ui/app.js 可读", str(exc))

    # ④ app.py 不得出现另一份写死的版本号
    try:
        app = _read("app.py")
        check(re.search(r'__version__\s*=\s*["\']', app) is None,
              "app.py 无重复版本号定义")
    except (OSError, UnicodeError) as exc:
        check(False, "app.py 可读", str(exc))

    # ⑤ CHANGELOG 与 使用说明 必须同步到当前版本
    try:
        log = _read("CHANGELOG.md")
        check(("## [%s]" % version) in log,
              "CHANGELOG.md 含当前版本条目", "## [%s]" % version)
    except (OSError, UnicodeError) as exc:
        check(False, "CHANGELOG.md 可读", str(exc))
    try:
        doc = _read("使用说明.md")
        check(("当前版本 **v%s**" % version) in doc,
              "使用说明.md 当前版本一致", "当前版本 **v%s**" % version)
    except (OSError, UnicodeError) as exc:
        check(False, "使用说明.md 可读", str(exc))

    # ⑤-a Electron 化后新增的版本派生点必须全部等于真源（v1.1.4 起守护）。
    # 曾实测到 package-lock.json 停在 1.1.0、README 标题停在 1.1.2，
    # 后端说一套、安装包说另一套，用户无法判断装的是哪个版本。
    try:
        pkg = json.loads(_read("electron/package.json"))
        check(str(pkg.get("version", "")) == version,
              "electron/package.json 当前版本一致",
              "version=%r，期望 %s" % (pkg.get("version"), version))
    except (OSError, UnicodeError, ValueError) as exc:
        check(False, "electron/package.json 可解析", str(exc))
    try:
        lock = json.loads(_read("electron/package-lock.json"))
        root_v = str(lock.get("version", ""))
        pkg_v = str(((lock.get("packages") or {}).get("") or {}).get("version", ""))
        check(root_v == version and pkg_v == version,
              "electron/package-lock.json 当前版本一致",
              "顶层=%r, packages['']=%r，期望 %s" % (root_v, pkg_v, version))
    except (OSError, UnicodeError, ValueError) as exc:
        check(False, "electron/package-lock.json 可解析", str(exc))
    try:
        ereadme = _read("electron/README.md")
        m = re.search(r"当前 v(\d+\.\d+\.\d+)", ereadme)
        got = m.group(1) if m else ""
        check(got == version, "electron/README.md 当前版本一致",
              "标题标记=%r，期望 %s" % (got, version))
    except (OSError, UnicodeError) as exc:
        check(False, "electron/README.md 可读", str(exc))
    try:
        devline = _read("开发线说明.md")
        found = re.findall(r"(?:· \*\*v|当前状态（v)(\d+\.\d+\.\d+)", devline)
        check(bool(found) and all(v == version for v in found),
              "开发线说明.md 当前版本一致",
              "标记=%s，期望全部为 %s" % (",".join(found) or "无", version))
    except (OSError, UnicodeError) as exc:
        check(False, "开发线说明.md 可读", str(exc))

    # ⑥ CI workflow 存在且发布阶段会上传 exe 资产
    try:
        wf = _read(".github/workflows/ci.yml")
        needed = ("windows-latest", "pyinstaller", "tags:", "gh release",
                  "Jinghe-$version.exe")
        missing = [k for k in needed if k.lower() not in wf.lower()]
        check(not missing, "CI workflow 完整",
              "缺少关键字：%s" % ",".join(missing) if missing else "测试 + 构建 + 上传资产")
    except (OSError, UnicodeError) as exc:
        check(False, "CI workflow 可读", str(exc))

    # ⑥-a CI 必须构建 Electron 安装包并产出 latest.yml（v1.1.2 起）
    # Electron 化后对外主产物是 setup.exe，后端 exe 只是随包组件。若 CI 被
    # 回退成只打 PyInstaller，外壳就再无人构建、自更新元数据也会断供。
    try:
        wf3 = _read(".github/workflows/ci.yml")
        electron_keys = ("setup-node", "npm ci", "npm run dist",
                         "latest.yml", "Jinghe-$version-setup.exe")
        missing3 = [k for k in electron_keys if k.lower() not in wf3.lower()]
        check(not missing3, "CI 构建 Electron 安装包",
              "缺少关键字：%s" % ",".join(missing3) if missing3
              else "Node + npm ci + electron-builder + latest.yml")
    except (OSError, UnicodeError) as exc:
        check(False, "CI Electron 链可查", str(exc))

    # ⑥-c 外壳自更新 IPC 链（v1.2.0 方案 A）：产了 latest.yml 还必须有
    # 消费它的代码。若只上传元数据却没接 updater，用户点「检查更新」仍是空的。
    try:
        main_js = _read("electron/main.js")
        preload_js = _read("electron/preload.js")
        app_js = _read("ui/app.js")
        ipc_keys = ("ipcMain.handle('update:check'", "ipcMain.handle('update:install'",
                    "require('electron-updater')", "autoUpdater.quitAndInstall")
        miss_main = [k for k in ipc_keys if k not in main_js]
        miss_pre = [k for k in ("desktopUpdater", "contextBridge", "ipcRenderer.invoke")
                    if k not in preload_js]
        miss_ui = [k for k in ("window.desktopUpdater", "shellCheckUpdate", "u.onProgress")
                   if k not in app_js]
        ok_ipc = not miss_main and not miss_pre and not miss_ui
        detail_ipc = ("主进程缺:%s 桥缺:%s 前端缺:%s" % (miss_main, miss_pre, miss_ui)
                      if not ok_ipc else "check/download/install + 白名单桥 + 进度回推")
        check(ok_ipc, "Electron 自更新 IPC 链完整", detail_ipc)
    except (OSError, UnicodeError) as exc:
        check(False, "Electron 自更新 IPC 链可查", str(exc))

    # ⑥-b CI 必须覆盖仓库里**每一个** test_*.py（否则 CI 绿灯是假的）
    # 2026-11-20 实测缺口：test_v10_features 有 19 个用例（守护冻结内核、
    # host 检查安全边界、OCR 不自动下载、多组件 Job 独立性），却既不在 CI
    # 的 unittest 命令里、也不在门禁的编译清单里 —— CI 显示全绿，实际少跑
    # 一整套。新增测试文件若忘记加进 CI，门禁在此直接拦住。
    try:
        wf2 = _read(".github/workflows/ci.yml")
        all_tests = sorted(p.stem for p in ROOT.glob("test_*.py"))
        not_in_ci = [m for m in all_tests if m not in wf2]
        check(not not_in_ci, "CI 覆盖全部测试模块",
              "CI 未跑：%s（新增测试文件必须同步加进 .github/workflows/ci.yml）"
              % ", ".join(not_in_ci) if not_in_ci
              else "%d 个测试模块全部在 CI 内" % len(all_tests))
    except (OSError, UnicodeError) as exc:
        check(False, "CI 测试覆盖可查", str(exc))

    # ⑦ 关键 Python 文件语法可编译（不落 __pycache__）
    # 2026-11-23 源码分层：24 个业务模块移入 core/media/knowledge/link/subs，
    # 路径随之更新（模块名不变，裸 import 靠各入口 sys.path 引导）。
    bad = []
    for rel in ("app.py", "extract.py", "test_app.py", "test_extract.py",
                # core：内核/引擎/基础设施
                "core/format_registry.py", "core/extract_engine.py",
                "core/refine_engine.py", "core/revise_engine.py",
                "core/iterate_engine.py", "core/log_rotate.py",
                # media：音视频/文档转换
                "media/media_tools.py", "media/media_runtime.py",
                "media/word_input.py", "media/word_export.py",
                "media/audio_transcribe.py", "media/video_transcribe.py",
                "media/pdf_ocr.py",
                "self_update.py",  # 保留根目录：自更新被 app/extract 直接引用
                # S7/S8 新增模块同样纳入编译校验（此前漏检，新模块语法错误
                # 只会在运行时才暴露）
                "backend.py", "knowledge/refine.py",
                # S14a：打包产物冒烟脚本（CI 用来验证「包能构建」之外的真能跑）
                "tools/smoke_test.py",
                "link/link_guard.py", "link/link_downloader.py", "link/link_media.py",
                # 验收工具（S5 外部体检 + UI 视觉判分层）
                "tools/bench_office_check.py", "tools/visual_check.py",
                # S9 阶段 4 知识库（远端 85feb75 合并进来）
                "knowledge/kb.py",
                # S10 可选组件管理（用户裁决：必须有测试 + 门禁守护）
                "knowledge/components.py", "test_components.py",
                # v1.0.0 特性测试（默认路径 / 多组件 Job / OCR / 安全边界）
                "test_v10_features.py", "test_ui_layout.py", "test_v164_i18n.py",
                # v1.7.0：界面改造 + UI 体验真运行时测试（诊断/同源块 + 主题/命令面板/结果前置）
                # 注意：只列 .py；.js 由 node 在测试内执行，不能喂给 Python compile()
                "test_ui_runtime.py", "test_ui_experience_runtime.py",
                # v1.7.1：主题持久化 + 布局改造真运行时测试
                # 注意：只列 .py；.js 由 node 在测试内执行，不能喂给 Python compile()
                "test_ui_layout_runtime.py",
                # v1.4.0 功能盘点修复的守护测试（12 项：状态条 / 回跳原文 /
                # 产物打开 / 订阅提纯 / 知识库维护 / 红线 2 等）
                "test_v140_fixes.py",
                # subs：订阅（S12a/S13）
                "subs/subscription_store.py", "subs/channel_discovery.py",
                "subs/subscription_engine.py", "subs/subscription_scheduler.py",
                # 版本契约判定器 + 一键升号（双终端协作护栏）
                "tools/version_check.py", "tools/bump_version.py"):
        try:
            compile(_read(rel), rel, "exec")
        except (SyntaxError, OSError, UnicodeError) as exc:
            bad.append("%s:%s" % (rel, exc))
    check(not bad, "关键源文件语法可编译", "; ".join(bad))

    # ⑧ exe 产物（发布阶段强制；本地构建后可选）
    # 对外产物名带版本号（dist/Jinghe-<version>.exe，用户 2026-11-19 裁决）。
    # 判定逻辑抽成纯函数 evaluate_exe，便于隔离单测「只有旧版 exe」等场景；
    # 原 sorted(glob)[0] 缺陷见该函数文档（2026-11-23 修）。
    check(*evaluate_exe(version, ROOT / "dist",
                        require_exe=bool(args.require_exe),
                        no_exe=bool(args.no_exe)))

    failed = 0
    for ok, name, detail in results:
        print("[%s] %s%s" % ("OK" if ok else "FAIL", name,
                             (" · " + detail) if detail else ""))
        if not ok:
            failed += 1
    print("-" * 52)
    print("发版门禁：%d 项通过 / %d 项失败 · 版本 v%s"
          % (len(results) - failed, failed, version))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
