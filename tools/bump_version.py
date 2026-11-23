#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精核 · 一键自动升号（确保永不与远端撞号）。

用户 2026-11-19 裁决：**本地每次改动都要升版本号**，防止版本号与远端相同
导致 for-upload 门禁拒绝上传。靠人记着手动改必然会漏，故做成本工具。

做什么：
1. 读 ``version-policy.json`` 规则 + ``extract.py`` 当前版本；
2. 按改动类型（patch/minor/major）算出候选版本号；
3. **联网核对 GitHub latest**：若候选号仍 ≤ 远端，自动往上顶（patch +1 直到
   严格大于远端）——从数学上杜绝撞号；
4. 原子同步所有「当前版本」派生点（v1.1.4 起补全 Electron 开发线）：
   - ``extract.py::__version__``（唯一真源）
   - ``CHANGELOG.md`` 顶部新增 ``## [x.y.z] - 日期`` 条目
   - ``使用说明.md`` 的「当前版本 **vX.Y.Z**」
   - ``electron/package.json`` 的顶层 ``version``
   - ``electron/package-lock.json`` 的顶层 ``version`` 与 ``packages[""].version``
   - ``electron/README.md`` 标题的「当前 vX.Y.Z」
   - ``开发线说明.md`` 的目录表版本与「当前状态（vX.Y.Z）」
   历史留痕（契约 vN 记录、CHANGELOG 旧条目、测试里的 mock 值、依赖版本号）一律不动。
   Electron 化后外壳 exe 也带版本号，漏同步任何一个点都会造成「后端说 v1.1.4、
   安装包说 v1.1.0」的混乱，故必须由工具统一写入、由门禁统一校验。

用法：
    python tools/bump_version.py minor --reason "新增 XX 能力"
    python tools/bump_version.py patch --reason "修 XX bug"
    python tools/bump_version.py --dry-run minor     # 只看会改成什么，不落盘
    python tools/bump_version.py --bump-to 0.9.0 --reason "指定版本"

零第三方依赖；GitHub 查询失败时**保守处理**（在当前号基础上 +1 patch，
并在输出里明确提示无法联网核对，由调用方决定是否继续）。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POLICY = ROOT / "version-policy.json"
EXTRACT = ROOT / "extract.py"
CHANGELOG = ROOT / "CHANGELOG.md"
GUIDE = ROOT / "使用说明.md"
ELECTRON_PKG = ROOT / "electron" / "package.json"
ELECTRON_LOCK = ROOT / "electron" / "package-lock.json"
ELECTRON_README = ROOT / "electron" / "README.md"
DEV_LINE = ROOT / "开发线说明.md"
LATEST_API = "https://api.github.com/repos/kong-city/jinghe/releases/latest"


def read_version() -> str:
    src = EXTRACT.read_text(encoding="utf-8")
    m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', src, re.M)
    if not m:
        raise SystemExit("无法从 extract.py 解析 __version__")
    return m.group(1)


def as_tuple(v: str) -> tuple[int, int, int]:
    parts = [int(x) for x in re.findall(r"\d+", v)[:3]]
    while len(parts) < 3:
        parts.append(0)
    return parts[0], parts[1], parts[2]


def fmt(t: tuple[int, int, int]) -> str:
    return "%d.%d.%d" % t


def _gh_token() -> str:
    """从 git credential 取 GitHub token（只读，不落盘、不打印）。

    GitHub **匿名 API 会限流返回 403**（用户 2026-11-20 实测），
    匿名查询失败会让升号工具误判「无法核对远端」而跳号。
    带 token 查询稳定，故作匿名失败时的回退。
    """
    try:
        import subprocess
        out = subprocess.run(["git", "credential", "fill"],
                             input="protocol=https\nhost=github.com\n\n",
                             capture_output=True, text=True, timeout=15).stdout
        for line in out.splitlines():
            if line.startswith("password="):
                return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return ""


def remote_latest() -> dict:
    headers = {
        "User-Agent": "jinghe-bump-version",
        "Accept": "application/vnd.github+json",
        "Cache-Control": "no-cache",
    }
    token = _gh_token()
    if token:
        headers["Authorization"] = "Bearer " + token
    try:
        req = urllib.request.Request(LATEST_API, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
        return {"ok": True, "version": re.sub(r"^v", "", str(data.get("tag_name") or ""))}
    except Exception as exc:
        # 认证也失败：如实回报失败，**绝不猜**（猜了就会跳号）
        return {"ok": False, "version": "", "error": type(exc).__name__}


MAX_DIGIT = 9   # 每段上限 9，满则进位（用户 2026-11-19 裁决：0.7.9 → 0.8.0）


def _carry(digits: list[int]) -> list[int]:
    """三段十进制进位：任一段超过 9 则向高位进 1，本段归 0。"""
    maj, minor, patch = digits
    if patch > MAX_DIGIT:
        patch, minor = 0, minor + 1
    if minor > MAX_DIGIT:
        minor, maj = 0, maj + 1
    if maj > MAX_DIGIT:
        raise SystemExit("主版本号超过 %d，无法继续进位" % MAX_DIGIT)
    return [maj, minor, patch]


def compute(kind: str, current: str) -> tuple[tuple[int, int, int], str]:
    """按改动类型算目标版本号。

    **进位规则（用户 2026-11-19 裁决）**：每段上限 9，满 9 进一位并归零，
    即 0.7.9 --patch--> 0.8.0（而不是 0.7.10），0.9.9 --> 1.0.0。
    """
    digits = list(as_tuple(current))
    if kind == "patch":
        digits[2] += 1
        note = "patch +1"
    elif kind == "minor":
        digits[1] += 1
        digits[2] = 0
        note = "minor +1, patch 归零"
    elif kind == "major":
        digits[0] += 1
        digits[1] = digits[2] = 0
        note = "major +1, minor/patch 归零"
    else:
        raise SystemExit("未知升号类型：%s" % kind)
    carried = _carry(digits)
    if carried != digits:
        note += "（满 %d 进位）" % MAX_DIGIT
    return (carried[0], carried[1], carried[2]), note


def ensure_above_remote(candidate: tuple[int, int, int], remote: dict) -> tuple[tuple, str]:
    """若候选号仍 ≤ 远端，自动 +1 并按进位规则顶上去，确保严格大于。"""
    if not remote.get("ok") or not remote.get("version"):
        bumped = tuple(_carry([candidate[0], candidate[1], candidate[2] + 1]))
        return bumped, "无法联网核对远端，保守再 +1 patch（请人工确认）"
    r = as_tuple(remote["version"])
    note = ""
    while candidate <= r:
        candidate = tuple(_carry([candidate[0], candidate[1], candidate[2] + 1]))
        note = "候选号未超过远端 %s，自动 +1（满 %d 进位）" % (remote["version"], MAX_DIGIT)
    return candidate, note


def set_extract(version: str, dry: bool) -> None:
    src = EXTRACT.read_text(encoding="utf-8")
    new, n = re.subn(r'^(__version__\s*=\s*["\'])[^"\']+(["\'])',
                     lambda m: m.group(1) + version + m.group(2), src,
                     count=1, flags=re.M)
    if n != 1:
        raise SystemExit("extract.py 版本号替换失败（匹配 %d 处）" % n)
    if not dry:
        EXTRACT.write_text(new, encoding="utf-8", newline="")


def add_changelog(version: str, reason: str, dry: bool) -> None:
    text = CHANGELOG.read_text(encoding="utf-8")
    if re.search(r"^## \[%s\]" % re.escape(version), text, re.M):
        return  # 已存在，不重复插入
    today = dt.date.today().isoformat()
    entry = "## [%s] - %s\n\n- %s\n\n" % (version, today, reason or "版本迭代")
    # 插到第一个 ## [ 之前（保持倒序，最新在上）
    m = re.search(r"^## \[", text, re.M)
    if m:
        new = text[:m.start()] + entry + text[m.start():]
    else:
        new = text.rstrip("\n") + "\n\n" + entry
    if not dry:
        CHANGELOG.write_text(new, encoding="utf-8", newline="")


def set_guide(version: str, dry: bool) -> None:
    text = GUIDE.read_text(encoding="utf-8")
    new, n = re.subn(r'(当前版本 \*\*v)\d+\.\d+\.\d+(\*\*)',
                     lambda m: m.group(1) + version + m.group(2), text, count=1)
    if n != 1:
        raise SystemExit("使用说明.md 当前版本替换失败（匹配 %d 处）" % n)
    if not dry:
        GUIDE.write_text(new, encoding="utf-8", newline="")


def _replace_once(path: Path, pattern: str, version: str, label: str,
                  dry: bool, count: int = 1) -> None:
    """按正则替换当前版本标记；匹配数不符即报错，宁可停也不静默漏改。"""
    text = path.read_text(encoding="utf-8")
    new, n = re.subn(pattern,
                     lambda m: m.group(1) + version + m.group(2), text,
                     count=count)
    if n != count:
        raise SystemExit("%s 当前版本替换失败（期望 %d 处，实际 %d 处）"
                         % (label, count, n))
    if not dry:
        path.write_text(new, encoding="utf-8", newline="")


def set_electron_and_devline(version: str, dry: bool) -> None:
    """同步 Electron 外壳工程与开发线文档里的「当前版本」标记。"""
    # package.json 顶层 version；lock 前两处正好是顶层与 packages[""].version，
    # 后续都是依赖版本，绝不能动。
    _replace_once(ELECTRON_PKG, r'("version"\s*:\s*")\d+\.\d+\.\d+(")',
                  version, "electron/package.json", dry)
    _replace_once(ELECTRON_LOCK, r'("version"\s*:\s*")\d+\.\d+\.\d+(")',
                  version, "electron/package-lock.json", dry, count=2)
    _replace_once(ELECTRON_README,
                  r'(# 精核 · Electron 桌面外壳（当前 v)\d+\.\d+\.\d+(；)',
                  version, "electron/README.md", dry)
    # 开发线说明有两处当前版本标记：目录表 + 当前状态标题。
    _replace_once(DEV_LINE,
                  r'(jinghe-desktop/` \| `desktop/native-gui` · \*\*v)\d+\.\d+\.\d+(\*\*)',
                  version, "开发线说明.md 目录表", dry)
    _replace_once(DEV_LINE, r'(## 当前状态（v)\d+\.\d+\.\d+(）)',
                  version, "开发线说明.md 当前状态", dry)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="精核一键自动升号")
    ap.add_argument("kind", nargs="?", choices=("patch", "minor", "major"),
                    default="patch", help="改动类型（默认 patch）")
    ap.add_argument("--reason", default="", help="本次改动说明（写入 CHANGELOG）")
    ap.add_argument("--bump-to", default="", help="直接指定目标版本号（跳过规则计算）")
    ap.add_argument("--dry-run", action="store_true", help="只预览，不落盘")
    ap.add_argument("--no-remote", action="store_true", help="跳过远端核对")
    args = ap.parse_args(argv)

    current = read_version()
    if args.bump_to:
        target = as_tuple(args.bump_to)
        if target <= as_tuple(current):
            raise SystemExit("指定版本 %s 未高于当前 %s" % (args.bump_to, current))
        note = "指定版本号"
    else:
        target, _ = compute(args.kind, current)
        if not args.no_remote:
            target, note = ensure_above_remote(target, remote_latest())
        else:
            note = "已跳过远端核对（--no-remote）"
    new_ver = fmt(target)

    print("当前版本 : %s" % current)
    print("目标版本 : %s" % new_ver)
    print("说明     : %s" % (note or "按规则升号"))
    print("派生点   : extract.py / CHANGELOG.md / 使用说明.md / "
          "electron/package.json / electron/package-lock.json / "
          "electron/README.md / 开发线说明.md")
    if args.dry_run:
        print("[DRY-RUN] 未写入任何文件")
        return 0

    set_extract(new_ver, dry=False)
    add_changelog(new_ver, args.reason, dry=False)
    set_guide(new_ver, dry=False)
    set_electron_and_devline(new_ver, dry=False)
    print("[OK] 已升号 %s → %s，真源 + 6 个派生点已同步" % (current, new_ver))
    # 发版约定（用户 2026-11-23 裁决）：本地包只用于本地验证/自用，不上传 GitHub；
    # GitHub Release 上的资产一律由 CI 在远端构建。旧提示「上传前跑 for-upload」
    # 属于已废弃的手动上传流程，会误导调用方，故改为 tag → CI 远端打包。
    print("下一步（远端打包约定：本地包不上传，Release 由 CI 产出）：")
    print("  1. 本地验证：python tools/check_release.py --no-exe")
    print("  2. 一键发版：python tools/release.py --reason \"本次改动说明\"")
    print("     或手动：git add -A && git commit -m \"...\" && git push origin main")
    print("            git tag -a v%s -m \"...\" && git push origin v%s" % (new_ver, new_ver))
    print("  3. CI 收到 v* tag 后自动在远端构建 exe + 安装包 + 上传 Release")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
