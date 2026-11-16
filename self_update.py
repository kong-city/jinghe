# -*- coding: utf-8 -*-
"""v0.4.8 自更新能力：检查版本 → 下载安装包 → 替换运行中的程序并重启。

本模块是**独立的后处理层能力**（与 S1~S4 同级），不触碰 extract.py 主流水线，
也不写 out/md/、INDEX.md、MERGED.md——它只产出"程序文件"，不产出文档。

红线（本模块任何改动都不得放松）：

1. **下载白名单**：只接受本仓库 ``releases/download/`` 前缀下的 ``Jinghe*.exe``，
   绝不接受任意外部地址——本模块绝不能退化成"任意下载器"。
2. **安装目标唯一**：只允许替换"当前正在运行的可执行文件自身"
   （打包态 ``sys.executable``），绝不接受前端或外部传入的路径，
   绝不覆盖源码目录里的任何文件。
3. **源码模式不落盘**：未打包（``sys.frozen`` 为假）时只下载并如实报告路径，
   绝不覆盖 ``python.exe`` 或源码文件。
4. **失败必须诚实**：任何一步失败都如实回显原因，绝不谎报"更新完成"。
5. **零第三方依赖**：只用标准库（urllib / pathlib / subprocess / base64）。

替换原理（Windows）：正在运行的 exe 被系统独占，无法就地覆盖。因此流程是
「下载到同目录的 ``Jinghe.new.exe`` → 派发一个脱离父进程的 PowerShell 脚本 →
脚本等待本进程退出 → 备份旧文件 → 覆盖 → 启动新版 → 新版起不来则回滚」。
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

# --------------------------------------------------------------------------- #
# 常量：仓库与版本服务
# --------------------------------------------------------------------------- #
REPO_SLUG = "kong-city/jinghe"
REPO_URL = "https://github.com/kong-city/jinghe"
RELEASES_API_URL = "https://api.github.com/repos/%s/releases/latest" % REPO_SLUG
RELEASES_LATEST_URL = REPO_URL + "/releases/latest"
# 只接受本仓库该前缀，杜绝把更新接口变成任意地址下载器。
RELEASES_DOWNLOAD_PREFIX = REPO_URL + "/releases/download/"

# 网络超时（秒）：桌面软件不能被慢网络卡住，超时即诚实降级。
CHECK_TIMEOUT = 6.0
DOWNLOAD_TIMEOUT = 30.0
# 安装包大小上限（120 MB）与下限（1 MB，低于此值视为下载不完整）。
MAX_UPDATE_BYTES = 120 * 1024 * 1024
MIN_UPDATE_BYTES = 1024 * 1024

# 安装脚本文件名与落盘目录（临时目录，随系统清理）。
INSTALL_SCRIPT_NAME = "jinghe-update.ps1"
INSTALL_WORK_DIRNAME = "jinghe-update"
# 替换执行器：新版 exe 用自己的 --self-update 模式完成覆盖与重启。
UPDATE_FLAG = "--self-update"
# 暂存文件名（与目标同目录，便于原子替换）。
STAGED_SUFFIX = ".new.exe"

# Windows 进程创建标志：隐藏窗口 + 脱离父进程，父进程退出后脚本继续跑。
_CREATE_NO_WINDOW = 0x08000000
_DETACHED_PROCESS = 0x00000008


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def is_frozen() -> bool:
    """是否打包版（PyInstaller onefile / onedir）。"""
    return bool(getattr(sys, "frozen", False))


def current_exe() -> str | None:
    """当前运行的可执行文件路径；源码模式返回 None。

    源码模式下 ``sys.executable`` 是 python.exe，**绝不能**把它当成更新目标。
    """
    if not is_frozen():
        return None
    exe = getattr(sys, "executable", "") or ""
    if not exe:
        return None
    try:
        return str(Path(exe).resolve())
    except OSError:
        return str(exe)


def version_tuple(text: str) -> tuple[int, ...]:
    """把 'v0.4.8' / '0.4.8' 归一成可比数字元组；非数字段忽略。"""
    nums = re.findall(r"\d+", str(text or ""))
    return tuple(int(n) for n in nums[:3])


def _normalize_version(text: str) -> str:
    """'v0.4.8' → '0.4.8'；无数字时原样返回。"""
    raw = str(text or "").strip()
    nums = re.findall(r"\d+", raw)
    if len(nums) >= 3:
        return ".".join(nums[:3])
    return raw.lstrip("vV")


def _token() -> str:
    """可选的 GitHub 只读令牌。

    默认走匿名访问（仓库已公开，匿名即可查 release）。
    若日后仓库转私有，可用环境变量 ``JINGHE_GH_TOKEN`` 兜底，
    令牌绝不写进代码、绝不落到界面上。
    """
    return str(os.environ.get("JINGHE_GH_TOKEN") or "").strip()


def is_asset_url(url: str) -> bool:
    """判断地址是否落在本仓库 release 资产白名单内。"""
    if not isinstance(url, str) or not url.startswith(RELEASES_DOWNLOAD_PREFIX):
        return False
    tail = url[len(RELEASES_DOWNLOAD_PREFIX):]
    if not tail or "/" not in tail:
        return False
    name = tail.rsplit("/", 1)[-1].lower()
    return name.startswith("jinghe") and name.endswith(".exe")


def _http_reason(exc: urllib.error.HTTPError) -> str:
    """把 HTTP 错误码翻译成人话（只覆盖更新场景会遇到的几个）。"""
    code = getattr(exc, "code", 0)
    return {
        401: "未授权（仓库转私有且未提供令牌）",
        403: "访问被拒绝（可能触发速率限制）",
        404: "仓库不可匿名访问，或尚未发布任何版本",
        429: "请求过于频繁（GitHub 速率限制）",
    }.get(code, "HTTP %s" % code)


# --------------------------------------------------------------------------- #
# ① 检查版本
# --------------------------------------------------------------------------- #
def check(current_version: str, *, timeout: float = CHECK_TIMEOUT,
          token: str | None = None) -> dict:
    """查询最新发布版本与安装包资产；断网 / 越权都诚实降级。

    返回字段（稳定契约，前端与测试都依赖）：
      ok / current / latest / latest_version / up_to_date / has_asset /
      asset_name / asset_size / asset_url / published_at / release_url /
      offline / error / notes / can_install / install_reason
    ``up_to_date`` 为 True/False/None：
      True=已是最新，False=有新版，None=无法比较（离线或版本号异常）。
    """
    current = str(current_version or "").strip() or "unknown"
    out: dict = {
        "ok": False,
        "current": current,
        "latest": None,
        "latest_version": None,
        "up_to_date": None,
        "has_asset": False,
        "asset_name": None,
        "asset_size": 0,
        "asset_url": None,
        "published_at": None,
        "release_url": RELEASES_LATEST_URL,
        "offline": False,
        "error": None,
        "notes": "",
        "source": "github-release",
        "can_install": False,
        "install_reason": "",
    }
    tok = _token() if token is None else str(token or "").strip()
    headers = {"User-Agent": "jinghe-desktop",
               "Accept": "application/vnd.github+json"}
    if tok:
        headers["Authorization"] = "token %s" % tok
    req = urllib.request.Request(RELEASES_API_URL, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        data = json.loads(raw.decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        # 404 既可能是仓库不可见，也可能是没有发布过版本——都要说清楚，不能装成"离线"
        out["error"] = "版本服务返回 %s：%s" % (
            getattr(exc, "code", "HTTP"), _http_reason(exc))
        out["notes"] = "无法获取版本信息"
        out["offline"] = False
        return out
    except Exception as exc:
        out["offline"] = True
        out["error"] = "无法连接版本服务：%s" % exc
        out["notes"] = "离线或网络不可达"
        return out

    if not isinstance(data, dict):
        out["error"] = "版本服务返回了无法解析的内容"
        return out

    tag = str(data.get("tag_name") or "").strip()
    html_url = str(data.get("html_url") or "").strip()
    published = str(data.get("published_at") or "").strip()
    if tag:
        out["latest"] = tag
        out["latest_version"] = _normalize_version(tag)
    if html_url.startswith(REPO_URL):
        out["release_url"] = html_url
    if published:
        out["published_at"] = published

    if tag and re.match(r"^\d+\.\d+\.\d+", current):
        out["up_to_date"] = (version_tuple(current) >= version_tuple(tag))
    elif tag:
        out["notes"] = "当前版本号格式异常，无法比较"

    for asset in (data.get("assets") or []):
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "")
        dl = str(asset.get("browser_download_url") or "")
        if not (name.lower().startswith("jinghe") and name.lower().endswith(".exe")):
            continue
        if not is_asset_url(dl):
            continue
        size = asset.get("size")
        out["has_asset"] = True
        out["asset_name"] = name
        out["asset_size"] = size if isinstance(size, int) and size > 0 else 0
        out["asset_url"] = dl
        break

    out["ok"] = True
    plan = install_plan()
    out["can_install"] = bool(plan.get("ok"))
    out["install_reason"] = str(plan.get("reason") or "")
    return out


# --------------------------------------------------------------------------- #
# ② 下载安装包
# --------------------------------------------------------------------------- #
def download_asset(url: str, dest: str | Path, *,
                   progress=None, cancel_check=None,
                   timeout: float = DOWNLOAD_TIMEOUT,
                   expected_size: int = 0) -> dict:
    """把 release 里的新版 exe 下载到指定路径（流式 + 进度回调 + 可取消）。

    约束：URL 必须在白名单内；流式写入 ``.part`` 临时文件；超过大小上限立即中止；
    成功后原子替换到目标路径。``progress(downloaded, total)`` 用于回报进度，
    ``cancel_check()`` 返回 True 时立刻中止并清理临时文件。
    """
    if not is_asset_url(url):
        return {"ok": False, "error": "下载地址不在仓库 release 白名单内"}
    dest_p = Path(dest)
    tmp = dest_p.with_name(dest_p.name + ".part")
    try:
        dest_p.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {"ok": False, "error": "目标目录不可用：%s" % exc}
    got = 0
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "jinghe-desktop"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            declared = resp.headers.get("Content-Length")
            total = 0
            if declared and str(declared).isdigit():
                total = int(declared)
            elif expected_size:
                total = int(expected_size)
            if total > MAX_UPDATE_BYTES:
                return {"ok": False, "error": "安装包超过大小上限"}
            with tmp.open("wb") as fh:
                while True:
                    if cancel_check is not None and cancel_check():
                        fh.close()
                        tmp.unlink(missing_ok=True)
                        return {"ok": False, "cancelled": True, "error": "已取消下载"}
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    got += len(chunk)
                    if got > MAX_UPDATE_BYTES:
                        fh.close()
                        tmp.unlink(missing_ok=True)
                        return {"ok": False, "error": "安装包超过大小上限"}
                    fh.write(chunk)
                    if progress is not None:
                        progress(got, total)
        if got < MIN_UPDATE_BYTES:
            tmp.unlink(missing_ok=True)
            return {"ok": False, "error": "下载内容不完整（小于 1 MB）"}
        if expected_size and got != int(expected_size):
            tmp.unlink(missing_ok=True)
            return {"ok": False,
                    "error": "下载大小与发布信息不一致（%d ≠ %d）" % (got, expected_size)}
        tmp.replace(dest_p)
    except Exception as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return {"ok": False, "error": "下载失败：%s" % exc}
    return {"ok": True, "path": str(dest_p), "bytes": got}


# --------------------------------------------------------------------------- #
# ③ 安装（替换运行中的程序并重启）
# --------------------------------------------------------------------------- #
def _dir_writable(path: Path) -> bool:
    """目录是否可写（试建临时文件判定，不改动任何用户文件）。"""
    probe = path / (".jinghe-write-probe-%d.tmp" % os.getpid())
    try:
        probe.write_bytes(b"0")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def install_plan() -> dict:
    """决定"能不能自动替换、替换谁、暂存到哪"。

    返回 ok / frozen / target / work_dir / staged / writable / reason。
    源码模式恒为不可安装（reason 说明原因），绝不返回可执行的替换目标。
    """
    out: dict = {"ok": False, "frozen": False, "target": None,
                 "work_dir": None, "staged": None, "writable": False,
                 "reason": ""}
    if not is_frozen():
        out["reason"] = "源码运行模式下无法自动替换程序文件（可下载后手动替换）"
        return out
    exe = current_exe()
    if not exe:
        out["reason"] = "无法确定当前程序路径"
        return out
    target = Path(exe)
    out["frozen"] = True
    out["target"] = str(target)
    out["work_dir"] = str(target.parent)
    out["staged"] = str(target.with_name(target.stem + ".new.exe"))
    out["writable"] = _dir_writable(target.parent)
    if not out["writable"]:
        out["reason"] = "程序所在目录不可写（可能安装在受保护位置）"
        return out
    out["ok"] = True
    return out


def _ps_quote(text: str) -> str:
    """PowerShell 单引号字符串：内部单引号需要写成两个。"""
    return str(text or "").replace("'", "''")


def build_install_script(staged: str, target: str, pid: int,
                         version: str = "") -> str:
    """生成替换脚本正文（纯函数，便于测试断言，不执行任何动作）。

    脚本逻辑：等待目标进程退出 → 备份旧文件 → 用新版覆盖 → 启动新版 →
    新版 4 秒内退出则回滚旧版并重启 → 清理暂存与备份文件。

    注意：变量名用 ``$targetPid`` 而不是 ``$pid``——``$PID`` 是 PowerShell
    只读自动变量（当前脚本进程号），赋值会直接报错。
    """
    return (
        "$ErrorActionPreference = 'SilentlyContinue'\n"
        "$target = '%s'\n"
        "$staged = '%s'\n"
        "$backup = '%s'\n"
        "$targetPid = %d\n"
        "$version = '%s'\n"
        "try { Wait-Process -Id $targetPid -ErrorAction SilentlyContinue } catch { }\n"
        "Start-Sleep -Milliseconds 1500\n"
        "if (Test-Path -LiteralPath $target) {\n"
        "  Copy-Item -LiteralPath $target -Destination $backup -Force\n"
        "}\n"
        "Copy-Item -LiteralPath $staged -Destination $target -Force\n"
        "$proc = Start-Process -FilePath $target -PassThru\n"
        "Start-Sleep -Seconds 4\n"
        "if ($proc -and $proc.HasExited) {\n"
        "  if (Test-Path -LiteralPath $backup) {\n"
        "    Copy-Item -LiteralPath $backup -Destination $target -Force\n"
        "    Start-Process -FilePath $target | Out-Null\n"
        "  }\n"
        "}\n"
        "Start-Sleep -Seconds 2\n"
        "Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue\n"
        "Remove-Item -LiteralPath $staged -Force -ErrorAction SilentlyContinue\n"
        % (_ps_quote(target), _ps_quote(staged),
           _ps_quote(str(target) + ".bak"), int(pid),
           _ps_quote(version))
    )


def schedule_install(staged: str | Path, target: str | Path, *,
                     version: str = "", pid: int | None = None) -> dict:
    """派发替换执行：等待本进程退出后覆盖程序文件并启动新版。

    红线复核（不可绕过）：
      * 目标必须等于当前运行的 exe 自身——外部传入的任意路径一律拒绝；
      * 源码模式直接拒绝（此时 sys.executable 是 python.exe）；
      * 暂存文件必须真实存在。

    执行方式有两条，优先用第一条：
      1. **新版 exe 自己执行**（``<staged> --self-update …``）——纯自带能力，
         不依赖 PowerShell / cmd / 任何外部解释器，最稳；
      2. **PowerShell 脚本**（备选）——某些环境禁止运行 exe 时兜底。
    """
    exe = current_exe()
    if not exe:
        return {"ok": False, "error": "当前不是打包版，无法自动替换程序文件"}
    target_p = Path(target)
    if os.path.normcase(str(target_p)) != os.path.normcase(str(Path(exe))):
        return {"ok": False, "error": "安装目标必须是当前运行的程序本身"}
    staged_p = Path(staged)
    if not staged_p.is_file():
        return {"ok": False, "error": "新版本安装包不存在"}
    wait_pid = int(pid or os.getpid())
    errors: list[str] = []

    # 方式 1：新版 exe 自我替换（首选，零外部依赖）
    try:
        argv = build_helper_argv(staged_p, target_p, wait_pid)
        subprocess.Popen(argv, creationflags=_CREATE_NO_WINDOW | _DETACHED_PROCESS,
                         close_fds=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"ok": True, "mode": "self-exe", "target": str(target_p),
                "staged": str(staged_p)}
    except OSError as exc:
        errors.append("self-exe: %s" % exc)

    # 方式 2：PowerShell 脚本（备选）
    try:
        work_dir = Path(tempfile.gettempdir()) / INSTALL_WORK_DIRNAME
        work_dir.mkdir(parents=True, exist_ok=True)
        script_path = work_dir / INSTALL_SCRIPT_NAME
        script = build_install_script(str(staged_p), str(target_p),
                                      wait_pid, version)
        # utf-8-sig：BOM 让 Windows PowerShell 5.1 正确识别中文路径
        script_path.write_text(script, encoding="utf-8-sig")
        enc = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        cmd = ["powershell", "-NoProfile", "-NonInteractive",
               "-WindowStyle", "Hidden", "-ExecutionPolicy", "Bypass",
               "-EncodedCommand", enc]
        subprocess.Popen(cmd, creationflags=_CREATE_NO_WINDOW | _DETACHED_PROCESS,
                         close_fds=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"ok": True, "mode": "powershell", "script": str(script_path),
                "target": str(target_p), "staged": str(staged_p)}
    except Exception as exc:
        errors.append("powershell: %s" % exc)
        return {"ok": False, "error": "无法安排更新替换：%s" % "；".join(errors)}


# --------------------------------------------------------------------------- #
# ④ 替换执行器（由新版 exe 自己跑，零外部依赖）
# --------------------------------------------------------------------------- #
def build_helper_argv(staged: str | Path, target: str | Path, pid: int) -> list[str]:
    """拼出替换执行器的命令行：新版 exe --self-update --staged … --target … --pid …"""
    return [str(staged), UPDATE_FLAG,
            "--staged", str(staged),
            "--target", str(target),
            "--pid", str(int(pid))]


def _helper_arg_value(argv: list[str], flag: str, default: str = "") -> str:
    try:
        idx = argv.index(flag)
    except ValueError:
        return default
    if idx + 1 < len(argv):
        return argv[idx + 1]
    return default


def run_helper_from_argv(argv: list[str], logger=None) -> int:
    """``--self-update`` 入口：解析参数并执行替换，返回进程退出码。"""
    staged = _helper_arg_value(argv, "--staged")
    target = _helper_arg_value(argv, "--target")
    try:
        pid = int(_helper_arg_value(argv, "--pid", "0") or 0)
    except (TypeError, ValueError):
        pid = 0
    if not staged or not target:
        return 2
    res = run_helper(staged, target, pid, logger=logger)
    if logger is not None:
        try:
            logger("[INFO] 自更新替换执行器结束：%s"
                   % json.dumps(res, ensure_ascii=False))
        except Exception:
            pass
    return 0 if res.get("ok") else 1


def _wait_target_released(target_p: Path, timeout: float = 90.0) -> bool:
    """等旧进程释放程序文件的写锁。

    Windows 上运行中的 exe 被独占：以读写方式打开会被拒绝；能打开即说明
    旧进程已退出。文件不存在则直接视为已释放。
    """
    deadline = time.time() + max(1.0, float(timeout))
    while time.time() < deadline:
        try:
            if not target_p.exists():
                return True
            with open(target_p, "r+b"):
                pass
            return True
        except OSError:
            time.sleep(0.5)
    return False


def run_helper(staged: str | Path, target: str | Path, pid: int = 0,
               *, wait_timeout: float = 90.0,
               verify_seconds: float = 5.0, logger=None) -> dict:
    """替换执行器本体：等旧进程退出 → 备份 → 覆盖 → 启动新版 → 失败回滚。

    跑在**新版 exe** 里（``--self-update``），因此不依赖 PowerShell / cmd /
    任何外部解释器——这是"能真正完成更新"最稳的一条路。
    """
    def _log(text: str) -> None:
        if logger is not None:
            try:
                logger(text)
            except Exception:
                pass

    staged_p = Path(staged)
    target_p = Path(target)
    if not staged_p.is_file():
        return {"ok": False, "error": "新版本安装包不存在"}
    # ---- 安全红线：替换执行器只允许"覆盖同目录的同名单程序" ----
    # 否则 `--self-update` 会变成"任意覆盖任意文件 + 任意启动"的危险入口。
    helper = current_exe()
    if not helper:
        return {"ok": False, "error": "替换执行器只能在打包版运行"}
    helper_p = Path(helper)
    if os.path.normcase(str(staged_p)) != os.path.normcase(str(helper_p)):
        return {"ok": False, "error": "安装包必须是替换执行器自身"}
    if not helper_p.name.endswith(STAGED_SUFFIX):
        return {"ok": False, "error": "替换执行器文件名不符合约定"}
    expected = helper_p.with_name(helper_p.name[:-len(STAGED_SUFFIX)])
    if os.path.normcase(str(expected)) != os.path.normcase(str(target_p)):
        return {"ok": False, "error": "替换目标必须是同目录的同名单程序"}
    backup_p = target_p.with_name(target_p.name + ".bak")
    _log("[INFO] 替换执行器启动：等待旧进程 %d 退出…" % int(pid))
    if not _wait_target_released(target_p, wait_timeout):
        return {"ok": False, "error": "旧程序仍在运行，无法覆盖程序文件"}
    try:
        if target_p.exists():
            shutil.copy2(target_p, backup_p)
        shutil.copy2(staged_p, target_p)
    except OSError as exc:
        return {"ok": False, "error": "覆盖程序文件失败：%s" % exc}
    _log("[INFO] 已覆盖程序文件：%s" % target_p)
    try:
        proc = subprocess.Popen([str(target_p)],
                                creationflags=_CREATE_NO_WINDOW | _DETACHED_PROCESS,
                                close_fds=True, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        _restore_backup(backup_p, target_p)
        return {"ok": False, "error": "启动新版本失败：%s" % exc}
    time.sleep(max(1.0, float(verify_seconds)))
    if proc.poll() is not None:
        # 新版起不来：回滚旧版并重新启动，绝不把用户留在"装坏了"的状态
        restored = _restore_backup(backup_p, target_p)
        return {"ok": False, "error": "新版本启动失败，已回滚到旧版本",
                "rolled_back": restored}
    _cleanup_quiet(backup_p)
    _log("[INFO] 新版本已启动：%s" % target_p)
    return {"ok": True, "target": str(target_p), "staged": str(staged_p)}


def _restore_backup(backup_p: Path, target_p: Path) -> bool:
    try:
        if backup_p.is_file():
            shutil.copy2(backup_p, target_p)
            _cleanup_quiet(backup_p)
            subprocess.Popen([str(target_p)],
                             creationflags=_CREATE_NO_WINDOW | _DETACHED_PROCESS,
                             close_fds=True, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
    except OSError:
        pass
    return False


def _cleanup_quiet(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def sweep_stale_staged(retry_seconds: float = 60.0) -> bool:
    """清理上次更新遗留的暂存文件（``<exe>.new.exe``）。

    替换执行器自己就跑在暂存文件里，删不掉；由**新启动的程序**接手清理。
    执行器退出前删除会失败，因此这里带重试。
    """
    exe = current_exe()
    if not exe:
        return False
    staged_p = Path(exe).with_name(Path(exe).stem + STAGED_SUFFIX)
    if not staged_p.exists():
        return False
    deadline = time.time() + max(0.0, float(retry_seconds))
    while True:
        try:
            staged_p.unlink()
            return True
        except OSError:
            if time.time() >= deadline:
                return False
            time.sleep(1.0)


def fallback_path(version: str = "") -> str:
    """退化路径：无法自动替换时，安装包落到用户「下载」文件夹。"""
    safe = re.sub(r"[^0-9A-Za-z._-]", "_", str(version or "").strip())[:40]
    safe = (safe or "latest").lstrip("vV") or "latest"
    base = Path.home() / "Downloads"
    try:
        if not base.is_dir():
            base = Path(tempfile.gettempdir()) / "jinghe-update"
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        base = Path(tempfile.gettempdir())
    return str(base / ("Jinghe-v%s.exe" % safe))


def human_bytes(num: int) -> str:
    """字节数 → 人类可读（用于进度文案）。"""
    try:
        n = float(num or 0)
    except (TypeError, ValueError):
        return "—"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0
    return "%.1f GB" % n


__all__ = [
    "REPO_SLUG", "REPO_URL", "RELEASES_API_URL", "RELEASES_LATEST_URL",
    "RELEASES_DOWNLOAD_PREFIX", "CHECK_TIMEOUT", "DOWNLOAD_TIMEOUT",
    "MAX_UPDATE_BYTES", "MIN_UPDATE_BYTES", "is_frozen", "current_exe",
    "version_tuple", "is_asset_url", "check", "download_asset",
    "install_plan", "build_install_script", "schedule_install",
    "fallback_path", "human_bytes", "build_helper_argv",
    "run_helper_from_argv", "run_helper", "sweep_stale_staged", "UPDATE_FLAG",
]
