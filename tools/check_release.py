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

    # ⑦ 关键 Python 文件语法可编译（不落 __pycache__）
    bad = []
    for rel in ("app.py", "extract.py", "test_app.py", "test_extract.py",
                "format_registry.py", "media_tools.py", "media_runtime.py",
                "word_input.py", "word_export.py", "audio_transcribe.py",
                "video_transcribe.py", "self_update.py",
                # S7/S8 新增模块同样纳入编译校验（此前漏检，新模块语法错误
                # 只会在运行时才暴露）
                "backend.py", "refine.py", "refine_engine.py",
                "revise_engine.py", "extract_engine.py", "log_rotate.py",
                "link_guard.py", "link_downloader.py", "link_media.py",
                # 验收工具（S5 外部体检 + UI 视觉判分层）
                "tools/bench_office_check.py", "tools/visual_check.py",
                # S9 阶段 4 知识库（远端 85feb75 合并进来）
                "kb.py",
                # S10 可选组件管理（用户裁决：必须有测试 + 门禁守护）
                "components.py", "test_components.py",
                # 版本契约判定器 + 一键升号（双终端协作护栏）
                "tools/version_check.py", "tools/bump_version.py"):
        try:
            compile(_read(rel), rel, "exec")
        except (SyntaxError, OSError, UnicodeError) as exc:
            bad.append("%s:%s" % (rel, exc))
    check(not bad, "关键源文件语法可编译", "; ".join(bad))

    # ⑧ exe 产物（发布阶段强制；本地构建后可选）
    # 对外产物名带版本号（dist/Jinghe-<version>.exe，用户 2026-11-19 裁决），
    # 兼容旧的 Jinghe.exe（过渡期）。两者都没有才算缺失。
    exe = next(iter(sorted((ROOT / "dist").glob("Jinghe-*.exe"))), None)
    if exe is None:
        exe = ROOT / "dist" / "Jinghe.exe"
    if args.no_exe:
        check(True, "exe 产物", "CI 测试阶段按 --no-exe 跳过")
    elif exe.is_file():
        size = exe.stat().st_size
        check(size > 1024 * 1024, "exe 产物可用", "%d 字节" % size)
    elif args.require_exe:
        check(False, "exe 产物必须存在", str(exe))
    else:
        check(True, "exe 产物", "尚未构建，本地开发阶段跳过")

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
