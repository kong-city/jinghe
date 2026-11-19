#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精核 · 版本契约判定器（双终端共用，机器可读）。

读取 ``version-policy.json``（版本迭代规则的唯一真源），提供三种判定：

* ``before-change`` —— 改代码前：fetch + 比对 commit 差距，输出该做什么；
* ``for-upload``    —— 上传前：**硬门禁**，本地版本必须严格大于 GitHub latest，
  否则拒绝上传（版本不变 = 另一终端无法识别代码已变更）；
* ``suggest``       —— 根据改动类型（patch/minor/major）算出建议版本号。

零第三方依赖；网络失败一律诚实报告 offline，绝不假装通过。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POLICY = ROOT / "version-policy.json"
LATEST_API = "https://api.github.com/repos/kong-city/jinghe/releases/latest"
TIMEOUT = 15.0


def load_policy() -> dict:
    return json.loads(POLICY.read_text(encoding="utf-8"))


def local_version() -> tuple[str, tuple[int, ...]]:
    p = load_policy()["version_source"]
    src = (ROOT / p["file"]).read_text(encoding="utf-8")
    m = re.search(p["pattern"], src, re.M)
    if not m:
        raise SystemExit("无法从 %s 解析版本号" % p["file"])
    text = m.group(1)
    nums = tuple(int(x) for x in re.findall(r"\d+", text)[:3])
    return text, nums


def remote_latest() -> dict:
    """返回 {ok, version, tag, error}；网络失败诚实报 offline。"""
    try:
        req = urllib.request.Request(LATEST_API, headers={
            "User-Agent": "jinghe-version-check",
            "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = json.loads(r.read().decode("utf-8"))
        tag = str(data.get("tag_name") or "")
        ver = re.sub(r"^v", "", tag)
        return {"ok": True, "version": ver, "tag": tag, "error": ""}
    except Exception as exc:
        return {"ok": False, "version": "", "tag": "",
                "error": "offline / 查询失败：%s" % type(exc).__name__}


def commit_gap() -> tuple[int, int]:
    """返回 (远端独有, 本地独有)。fetch 失败返回 (-1,-1)。"""
    try:
        subprocess.run(["git", "fetch", "origin", "--quiet"], cwd=str(ROOT),
                       capture_output=True, timeout=30)
        out = subprocess.run(
            ["git", "rev-list", "--left-right", "--count", "origin/main...HEAD"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30).stdout.strip()
        a, b = out.split()
        return int(a), int(b)
    except Exception:
        return -1, -1


def cmp_version(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    """a 与 b 语义比较：>0 表示 a 更新。"""
    for x, y in zip(a, b):
        if x != y:
            return 1 if x > y else -1
    return 0


def cmd_before_change(_args) -> int:
    lv, lnums = local_version()
    remote, rnums = commit_gap()
    print("本地版本 : %s" % lv)
    print("commit 差距（远端独有 / 本地独有）: %d / %d" % (remote, rnums))
    if remote < 0:
        print("[WARN] git fetch/比对失败，请检查仓库与网络；未确认前不要改代码")
        return 2
    if remote > 0:
        print("[ACTION] 远端有 %d 个新提交 → 先 git pull --ff-only origin main 再改"
              % remote)
        return 1
    if rnums > 0:
        print("[OK] 本地领先 %d 提交，可继续改（上传仍需用户指令）" % rnums)
        return 0
    print("[OK] 本地与远端同步，可继续改")
    return 0


def cmd_for_upload(_args) -> int:
    lv, lnums = local_version()
    rem = remote_latest()
    print("本地版本 : %s" % lv)
    if not rem["ok"]:
        print("[BLOCK] %s" % rem["error"])
        print("        无法确认远端版本，拒绝上传（宁可不动，不可盲传）")
        return 2
    print("GitHub latest : %s" % rem["tag"])
    rv = tuple(int(x) for x in re.findall(r"\d+", rem["version"])[:3])
    c = cmp_version(lnums, rv)
    if c <= 0:
        print("[BLOCK] 本地版本 %s 未高于远端 %s → 拒绝上传。"
              % (lv, rem["tag"]))
        print("        请先升号（见 version-policy.json 的 bump_rules），"
              "确保另一终端能凭版本号识别代码变更。")
        return 1
    print("[OK] 本地版本严格高于远端，允许上传")
    return 0


def cmd_suggest(args) -> int:
    lv, _ = local_version()
    policy = load_policy()
    kind = args.kind
    rule = next((r for r in policy["bump_rules"] if r["id"] == kind), None)
    if not rule:
        print("未知改动类型：%s（可选 %s）" % (
            kind, "/".join(r["id"] for r in policy["bump_rules"])))
        return 2
    parts = [int(x) for x in re.findall(r"\d+", lv)[:3]]
    while len(parts) < 3:
        parts.append(0)
    maj, minor, patch = parts
    if kind == "patch":
        patch += 1
    elif kind == "minor":
        minor += 1
        patch = 0
    else:
        maj += 1
        minor = patch = 0
    print("当前: %s" % lv)
    print("改动类型: %s" % kind)
    print("建议版本: %d.%d.%d" % (maj, minor, patch))
    print("依据: %s" % rule["action"])
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="精核版本契约判定器")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("before-change", help="改代码前：检查是否需先拉取")
    sub.add_parser("for-upload", help="上传前：硬门禁，版本必须严格递增")
    ps = sub.add_parser("suggest", help="按改动类型建议下一个版本号")
    ps.add_argument("kind", choices=("patch", "minor", "major"))
    args = ap.parse_args(argv)
    return {"before-change": cmd_before_change,
            "for-upload": cmd_for_upload,
            "suggest": cmd_suggest}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
