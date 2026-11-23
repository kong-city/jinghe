#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精核 · 一键发版：提交 → 打 tag → push → 触发 CI 远端打包。

用户 2026-11-23 裁决：**本地打的包不上传 GitHub，每次版本更新都要在远端打包**。
本脚本把「push v* tag 触发 CI 远端构建 + 上传 Release」固化成一条命令，
避免漏打 tag、顺序出错（先打 tag 后 commit 会构建到旧代码）等人为失误。

做什么：
1. 读 ``extract.py`` 版本，校验 tag ``v<版本>`` 本地/远端均未占用；
2. 跑发版门禁 ``check_release.py --no-exe``；
3. 检查 git 状态：本地不得落后远端；有改动则 add + commit；
4. push main → 打 annotated tag → push tag（CI 收到 tag 自动远端打包）；
5. 输出 CI 链接；``--watch`` 时用 GitHub API 轮询到运行结束。

安全设计：
- ``--dry-run`` 执行全部只读检查，但不做任何写操作（commit/push/tag）；
- 任何一步失败立即中止，不产生「已 push main 但没打 tag」的半截状态；
- 不删 tag、不改版本号、不碰 Release —— 破坏性操作一律人工确认。

用法：
    python tools/release.py --reason "新增 XX 能力"
    python tools/release.py --reason "新增 XX 能力" --dry-run
    python tools/release.py --reason "新增 XX 能力" --watch
    python tools/release.py --reason "..." --require-clean   # 有改动时中止，不自动提交

零第三方依赖；token 从 git credential 读取（只读，不落盘、不打印）。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXTRACT = ROOT / "extract.py"
GATE = ROOT / "tools" / "check_release.py"
REPO = "kong-city/jinghe"
CI_URL = "https://github.com/%s/actions/workflows/ci.yml" % REPO
API_RUNS = "https://api.github.com/repos/%s/actions/runs?event=push&per_page=10" % REPO


def read_version() -> str:
    src = EXTRACT.read_text(encoding="utf-8")
    m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', src, re.M)
    if not m:
        raise SystemExit("无法从 extract.py 解析 __version__")
    return m.group(1)


def git(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    """在仓库根目录执行 git 命令；check=True 时失败即中止。"""
    cmd = ["git", "-C", str(ROOT)] + args
    r = subprocess.run(cmd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise SystemExit("git 命令失败：%s\n%s" % (" ".join(cmd),
                                                  (r.stderr or r.stdout).strip()))
    return r


def run_gate() -> None:
    """发版门禁必须过；输出直接透传，便于人工确认。"""
    print("\n[1/5] 发版门禁 check_release.py --no-exe")
    r = subprocess.run([sys.executable, str(GATE), "--no-exe"], cwd=str(ROOT))
    if r.returncode != 0:
        raise SystemExit("门禁未通过，中止发版（请先修复再重跑）")


def check_repo_state(tag: str, require_clean: bool) -> tuple[bool, int]:
    """检查远端领先情况、tag 是否占用、工作区是否有改动。

    返回：(是否有未提交改动, 本地领先远端的提交数)。
    """
    print("\n[2/5] 检查仓库状态")
    git(["fetch", "origin", "--quiet"])          # 只读操作，dry-run 也执行

    # behind ahead
    counts = git(["rev-list", "--left-right", "--count", "origin/main...HEAD"]).stdout.split()
    behind, ahead = int(counts[0]), int(counts[1])
    if behind:
        raise SystemExit("本地落后远端 %d 个提交，请先 git pull --rebase 再发版" % behind)
    print("  本地领先远端：%d 个提交" % ahead)

    local_tag = git(["tag", "-l", tag]).stdout.strip()
    if local_tag:
        raise SystemExit("本地已存在 tag %s，请升版本后重试" % tag)
    remote_tag = git(["ls-remote", "--tags", "origin", "refs/tags/" + tag]).stdout.strip()
    if remote_tag:
        raise SystemExit("远端已存在 tag %s（同名 tag 推送不会触发新构建），请升版本" % tag)
    print("  tag %s 本地/远端均未占用" % tag)

    dirty = git(["status", "--porcelain"]).stdout.strip()
    if dirty:
        if require_clean:
            raise SystemExit("工作区有未提交改动且指定了 --require-clean，请先自行提交")
        files = dirty.splitlines()
        print("  检测到 %d 处未提交改动，将自动 add + commit：" % len(files))
        for line in files[:15]:
            print("    " + line)
        if len(files) > 15:
            print("    ... 其余 %d 处省略" % (len(files) - 15))
    else:
        print("  工作区干净")
    return bool(dirty), ahead


def commit_push_tag(version: str, tag: str, reason: str, dirty: bool,
                    ahead: int, dry: bool) -> None:
    """提交改动 → push main → 打 tag → push tag。dry-run 只打印不执行。"""
    print("\n[3/5] 提交改动" if dirty else "\n[3/5] 提交改动（无改动，跳过）")
    if dirty:
        msg = "release(v%s): %s" % (version, reason)
        if dry:
            print("  [DRY-RUN] git add -A && git commit -m \"%s\"" % msg)
        else:
            git(["add", "-A"])
            git(["commit", "-m", msg])
            print("  已提交：%s" % msg)

    print("\n[4/5] push main")
    if dry:
        print("  [DRY-RUN] git push origin main")
    else:
        git(["push", "origin", "main"])
        print("  main 已推送")

    print("\n[5/5] 打 tag 并 push（触发 CI 远端打包）")
    tag_msg = "精核 v%s：%s" % (version, reason)
    if dry:
        print("  [DRY-RUN] git tag -a %s -m \"%s\"" % (tag, tag_msg))
        print("  [DRY-RUN] git push origin %s" % tag)
        print("\n[DRY-RUN] 未执行任何写操作")
    else:
        git(["tag", "-a", tag, "-m", tag_msg])
        git(["push", "origin", tag])
        print("  tag %s 已推送" % tag)


def _gh_token() -> str:
    """从 git credential 取 token（只读）；取不到则轮询功能降级为只输出链接。"""
    try:
        out = subprocess.run(["git", "credential", "fill"],
                             input="protocol=https\nhost=github.com\n\n",
                             capture_output=True, text=True, timeout=15).stdout
        for line in out.splitlines():
            if line.startswith("password="):
                return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return ""


def watch_ci(tag: str, timeout: int = 1800) -> None:
    """轮询 GitHub API，直到该 tag 对应的 workflow run 结束。"""
    token = _gh_token()
    if not token:
        print("\n未取得 GitHub token，跳过状态轮询。请手动查看：%s" % CI_URL)
        return
    headers = {
        "User-Agent": "jinghe-release-watch",
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer " + token,
    }
    deadline = time.time() + timeout
    print("\n监控 CI 中（最长 %d 秒）..." % timeout)
    while time.time() < deadline:
        try:
            req = urllib.request.Request(API_RUNS, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                runs = json.loads(resp.read().decode("utf-8")).get("workflow_runs", [])
            hit = next((r for r in runs if r.get("head_branch") == tag), None)
            if hit:
                status = hit.get("status")
                conclusion = hit.get("conclusion")
                print("  run #%s: %s %s" % (hit.get("id"), status, conclusion or ""))
                if status == "completed":
                    if conclusion == "success":
                        print("  ✅ 远端打包 + Release 上传成功：%s" % hit.get("html_url"))
                    else:
                        print("  ❌ CI 失败：%s" % hit.get("html_url"))
                        print("     请用 API 拉 job 日志定位，修复后升 patch 重发")
                    return
        except Exception as exc:
            print("  查询 CI 状态失败（%s），稍后重试" % type(exc).__name__)
        time.sleep(20)
    print("  超时未获得终态，请查看：%s" % CI_URL)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="精核一键发版（push tag → CI 远端打包）")
    ap.add_argument("--reason", default="", help="改动说明（写入 commit 与 tag message）")
    ap.add_argument("--dry-run", action="store_true", help="只预览，不执行写操作")
    ap.add_argument("--watch", action="store_true", help="推送后轮询 CI 状态直到结束")
    ap.add_argument("--require-clean", action="store_true", help="工作区有改动时中止，不自动提交")
    args = ap.parse_args(argv)

    version = read_version()
    tag = "v" + version
    reason = args.reason or "版本迭代 " + version

    print("=== 精核一键发版（本地包不上传，Release 由 CI 远端打包）===")
    print("版本     : %s  (tag %s)" % (version, tag))
    print("改动说明 : %s" % reason)
    if args.dry_run:
        print("模式     : DRY-RUN（只读检查，不写仓库）")

    run_gate()
    dirty, ahead = check_repo_state(tag, args.require_clean)
    commit_push_tag(version, tag, reason, dirty, ahead, args.dry_run)

    if not args.dry_run:
        print("\n远端已触发打包。CI 页面：%s" % CI_URL)
        print("Release 页面：https://github.com/%s/releases/tag/%s" % (REPO, tag))
        if args.watch:
            watch_ci(tag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
