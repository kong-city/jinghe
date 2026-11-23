# -*- coding: utf-8 -*-
"""精核 · 可选组件管理（设置页"相关组件"列表的数据与安装后端）。

设计约束：
* 纯标准库；组件探测复用 media_tools.ToolAdapter，不碰 TOOL_SPECS / capabilities()
  （S1 契约 test_33/34 锁死「恰好 3 工具 + 全 False」，本模块只加独立字段）。
* 三个核心组件：ffmpeg（音视频基础）、whisper（本机转写）、yt-dlp（链接下载）。
* **绝不主动下载（用户 2026-11-19 硬裁决）**：软件启动、能力探测、定时任务
  一律不下载任何组件；只有用户在设置页**手动点击「启用」按钮**，才触发下载。
  技术上以 ``_USER_OPT_IN`` 令牌强制：任何下载路径必须先经 :func:`install`
  写入令牌，绕过者（含未来误调）直接拒绝。
* 内置固定源仅供手动安装使用：ffmpeg=gyan.dev 静态 zip；whisper/yt-dlp=pip
  阿里镜像。下载地址只从本文件的 COMPONENTS 常量取，前端不能传任意 URL（防 SSRF）。
* 安装到 %LOCALAPPDATA%/Jinghe/components/bin，不写系统目录、不需要管理员权限。
  **工具二进制不进 exe、不进 Release、不随 GitHub 上传**（build.spec binaries=[]）。
* 安装过程后台线程执行，进度通过 install_status(since) 事件队列暴露，前端轮询。

对外 API：
    list_components(refresh=False) -> dict        组件清单 + 安装状态
    install(component_id) -> dict                 启动安装（幂等：已在装则拒绝）
    install_status(since=0) -> dict               进度事件 / 状态
    cancel_install() -> dict                      取消当前安装
"""

from __future__ import annotations

import os
import re
import shutil
import struct
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

import media_tools

__version__ = "0.1.0"

COMPONENT_DIR = Path(os.environ.get("LOCALAPPDATA") or str(Path.home())) / "Jinghe" / "components"
BIN_DIR = COMPONENT_DIR / "bin"

# --------------------------------------------------------------------------- #
# 组件收口目录结构（v1.4.0）
# --------------------------------------------------------------------------- #
# venv：Python 虚拟环境。新装的 pip 包一律进这里，**不再污染宿主 Python**。
# 实测隔离彻底（venv/Scripts/yt-dlp.exe 独立可跑，包落 venv/Lib/site-packages，
# 宿主 site-packages 零新增），且 pip 在 venv 里**自动生成 CLI**。
VENV_DIR = COMPONENT_DIR / "venv"
# models：whisper 模型权重。whisper CLI 的 --model_dir 直指此处
# （whisper/transcribe.py: model_dir → load_model(download_root=...)），
# 不再落在用户家目录 ~/.cache/whisper/（那处不受软件管理、卸载清不掉）。
MODELS_DIR = COMPONENT_DIR / "models"
# runtime：便携 Python 运行时（按需下载兜底，v1.4.x 实现）。
# 当前仅预留目录定义，不参与安装流程。
RUNTIME_DIR = COMPONENT_DIR / "runtime"

# venv 内部布局
VENV_SCRIPTS = VENV_DIR / "Scripts"
VENV_PYTHON = VENV_SCRIPTS / "python.exe"

# 导入可用性校验的缓存：exe 路径 + 解释器路径 → (时间戳, 结论)
# 校验一次约 0.7~1.3 秒（要起一个 Python 解释器 import 包），不能每次刷新都跑。
# 以「解释器 + 包目录」的 mtime 作为失效依据：包被重装/升级后 mtime 变化 → 自动重校。
_IMPORT_CHECK_CACHE: dict[tuple[str, str], tuple[float, bool, str]] = {}
_IMPORT_CHECK_TTL = 300.0  # 5 分钟兜底过期（防止手工改环境后缓存不更新）

# 需要做「导入可用性校验」的组件：它们的包 import 会连带加载原生扩展，
# 而原生扩展可能因缺 DLL / 版本不匹配而加载失败 —— 此时「文件在」≠「能用」。
# whisper 的 __init__ 会 import torch，torch 加载 shm.dll 失败即典型案例
# （用户 2026-11-23 实测：exe 存在、界面显示已安装，真跑却 WinError 126）。
_IMPORT_CHECK_TARGETS = {
    "whisper": "whisper",
    "yt-dlp": "yt_dlp",
}

# 受控目录内的组件（软件自己装的）改用 **DLL 依赖预检** 而非 import 校验：
# import 要起一个解释器并加载 300MB 的 torch，耗时 1.2~2.4 秒，
# 每次刷新都跑会明显卡顿；DLL 预检是纯文件扫描，毫秒级。
# 二者互补：外部组件用 import（抓 Python 层错误），
#           受控组件用 DLL 预检（抓原生依赖缺失）。
# 用户 2026-11-23 实测：受控目录豁免 import 校验会让「假绿灯」回归 ——
# venv 里的 whisper 因系统缺 VCRUNTIME140_THREADS.dll 而不可用，
# 探测却因豁免而返回 installed=True。

# 已知属于 Microsoft Visual C++ Redistributable 的运行时 DLL。
# 缺它们 → torch_cpu.dll / torch_python.dll 加载失败 → whisper 整体报
# WinError 126。这是「装了组件却用不了」最常见的环境原因，
# 必须给出可操作的指引（去装 VC++ 运行库），而不是笼统说「DLL 缺失」。
_MSVC_RUNTIME_DLLS = {
    "vcruntime140.dll",
    "vcruntime140_1.dll",
    "vcruntime140_threads.dll",
    "vcruntime140_atomic_wait.dll",
    "msvcp140.dll",
    "msvcp140_atomic_wait.dll",
    "msvcp140_1.dll",
    "msvcp140_2.dll",
    "concrt140.dll",
}

# 组件包内的原生库目录名 → 需要扫描的 DLL 所在处。
# whisper 依赖 torch，torch 的 DLL 全在 torch/lib 下。
_DLL_SCAN_DIRS = ("torch", "torch/lib", "numpy", "numpy.libs", "llvmlite",
                  "numba", "scipy", "scipy.libs")

# 各组件**实际依赖**的原生库目录 —— 只扫自己用到的，不连坐。
# yt-dlp 是纯 Python 包，不依赖 torch；若无差别全扫，它会被 whisper 的
# torch 环境问题连坐成「不可用」（实测踩到）。
_DLL_DEPS_BY_COMPONENT = {
    "whisper": ("torch", "torch/lib", "numpy", "numpy.libs", "llvmlite",
                "numba", "scipy", "scipy.libs"),
    "yt-dlp": (),  # 纯 Python，无原生依赖
}

# 内置固定源——前端不可改。pip 镜像用于装 whisper / yt-dlp（两者都会生成 CLI 到 Scripts/）。
PIP_INDEX = "https://mirrors.aliyun.com/pypi/simple/"
PIP_TRUSTED_HOST = "mirrors.aliyun.com"
FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

# 组件定义（顺序即 UI 展示顺序）
COMPONENTS = (
    {
        "id": "ffmpeg",
        "name": "FFmpeg",
        "desc": "音视频解码、抽轨与字幕导出，转写/链接处理的基础依赖",
        "probe": "ffmpeg",
        "kind": "zip",
        "url": FFMPEG_URL,
        "exe": "ffmpeg.exe",
    },
    {
        "id": "whisper",
        "name": "Whisper",
        "desc": "本机语音转写模型（OpenAI Whisper，首次运行会下载模型）",
        "probe": "whisper",
        "kind": "pip",
        "package": "openai-whisper",
        "exe": "whisper.exe",
    },
    {
        "id": "yt-dlp",
        "name": "yt-dlp",
        "desc": "视频/音频链接下载与解析",
        "probe": "yt-dlp",
        "kind": "pip",
        "package": "yt-dlp",
        "exe": "yt-dlp.exe",
    },
)
_BY_ID = {c["id"]: c for c in COMPONENTS}

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_LOCK = threading.Lock()
# 手动点击令牌（用户 2026-11-19 硬裁决：绝不主动下载）。
# 只有 install() 在确认「用户点了启用按钮」后才会置 True；_install_worker
# 消费一次即清。任何绕过 install() 直接调 _download/_pip_install 的路径，
# 令牌为空 → 拒绝下载，从代码层杜绝自动/误触下载。
# v0.10：令牌改为「按组件 id 集合」，支持多组件并发且互不消费对方的令牌；
# _USER_OPT_IN 保留为兼容旧测试的「最近一次令牌」视图。
_USER_OPT_IN = {"granted": False, "component_id": ""}
_USER_OPT_INS: set[str] = set()
# 选定的 pip 用 Python（首次查找后锁定，保证「装」与「探」同源）
_PIP_PYTHON = ""
# 该选择的 PATH 指纹；PATH 变化则重新查找
_PIP_PYTHON_FP = ""
def _new_job(cid: str = "") -> dict:
    return {
        "running": False,
        "id": cid,
        "state": "idle",       # idle / running / done / failed / cancelled
        "percent": 0.0,
        "message": "",
        "error": "",
        "cancelled": False,
        "events": [],          # [{seq, type, text, progress}]
        "next_seq": 1,
    }


# 兼容视图：_JOB 始终指向「最近一次操作」的 job 对象（旧 API/测试读它）。
_JOB = _new_job()
# 真实状态源：每个组件一个独立 job，支持真并发（各自进度/事件/取消）。
_JOBS: dict[str, dict] = {}


def _job_for(cid: str | None) -> dict:
    """取组件对应的 job；cid 为空时回落到最近任务（兼容旧调用）。"""
    if not cid:
        return _JOB
    with _LOCK:
        return _JOBS.setdefault(cid, _new_job(cid))


def _sync_recent(cid: str | None) -> None:
    """把某个 job 设为「最近任务」视图（不拷贝，保持同一对象引用）。"""
    global _JOB
    if cid:
        with _LOCK:
            _JOB = _JOBS.setdefault(cid, _new_job(cid))


# --------------------------------------------------------------------------- #
# PATH 增强：让 pip 装出来的 CLI / 解压出的 ffmpeg 能被 shutil.which 找到
# --------------------------------------------------------------------------- #
def _scripts_dir() -> Path:
    """真实 Python 的 Scripts 目录（pip 装 CLI 落这里）。

    冻结态 ``sys.prefix`` 指向 exe 的临时解压目录，那里没有 pip 装的 CLI；
    必须用 :func:`_python_for_pip` 找到的真 Python，**并问 pip 自己**
    scripts 路径（见 :func:`_pip_scripts_dir`），保证「pip 装到哪」与
    「探测去哪」严格同源——否则会出现「安装结束仍探测不到 whisper.exe」。

    **v1.4.0 收口**：venv 存在时，优先返回 ``venv\\Scripts`` ——
    新装的包都在 venv 里，问 venv 的 pip 得到的才是真正的一致答案。
    """
    try:
        if _venv_python_usable():
            return VENV_SCRIPTS
        py = _python_for_pip()
        return _pip_scripts_dir(py)
    except RuntimeError:
        # 找不到真 Python 时回退到 sys.prefix（源码态即正确）
        return Path(sys.prefix) / "Scripts"


def _candidate_scripts_dirs() -> list[Path]:
    """所有可能存放 pip CLI 的 Scripts 目录（按优先级）。

    **v1.4.0 收口后的优先级**：
      1. ``venv\\Scripts`` —— 软件自己装的组件所在处（最高优先）
      2. **系统 Python 的 Scripts（问 pip 自己）** —— 兼容用户手动装的组件
      3. PATH 里所有以 Scripts 结尾的条目 —— 多 Python 共存兜底

    **第 2 项为何不能省（用户 2026-11-23 实测踩坑）**：本机系统 Python 的
    ``Scripts`` **不在 PATH 里**（PATH 里只有 ``...\\envs\\default\\Scripts``），
    若只靠 PATH 扫描，venv 优先后系统 Python 里那份 whisper 就探测不到了
    —— 直接违背「兼容用户已有组件、不强制重装」的承诺。故必须**主动**问
    pip 自己要它的 scripts 路径（见 :func:`_pip_scripts_dir`）。

    多个 Python 共存时（本机同时有 workbuddy versions\\3.13.12 与
    WorkBuddy vendor\\python），组件可能装在任一处。全都注入 PATH，
    探测就不会因为「装 A 处、只查 B 处」而失败。
    """
    out: list[Path] = []
    # ① venv 优先（软件自管目录）
    #    用 _venv_python_usable() 而非 is_dir()：venv 目录可能存在但已损坏
    #    （只剩 Scripts、缺 pyvenv.cfg），此时不能把它当作有效来源。
    try:
        if _venv_python_usable():
            out.append(VENV_SCRIPTS)
    except Exception:
        pass
    # ② 系统 Python 的 Scripts（问 pip 自己，装探同源）
    #    注意：不能依赖 PATH 是否含该目录 —— 实测本机就不含。
    #    也不能问 _python_for_pip()（它已优先返回 venv 的 python），
    #    必须直接问**系统 Python**：_find_python_for_pip()。
    try:
        base_py = _find_python_for_pip()
        out.append(_pip_scripts_dir(base_py))
    except Exception:
        pass
    # ②b 已探测到的 CLI 所在目录反推（whisper.exe / yt-dlp.exe 所在处）
    #     多 Python 共存时，组件可能装在任一处。
    for cli in ("whisper", "yt-dlp"):
        try:
            found = shutil.which(cli)
        except Exception:
            found = ""
        if found:
            try:
                out.append(Path(found).resolve().parent)
            except (OSError, ValueError):
                pass
    # ③ PATH 里所有以 Scripts 结尾的条目
    for entry in (os.environ.get("PATH") or "").split(os.pathsep):
        entry = entry.strip().strip('"')
        if not entry:
            continue
        try:
            p = Path(entry)
            if p.name.lower() == "scripts" and p.is_dir():
                out.append(p)
        except OSError:
            continue
    # 去重（保持顺序）
    seen: set[str] = set()
    uniq: list[Path] = []
    for p in out:
        key = os.path.normcase(os.path.abspath(str(p)))
        if key not in seen:
            seen.add(key)
            uniq.append(p)
    return uniq


def ensure_component_path() -> None:
    """把组件 bin / 候选 Scripts 按**优先级顺序**加到 PATH 最前面（幂等）。

    同时做一次「陈旧 ``.part`` 清理」（缺陷 1 兜底）：此处是所有探测与
    安装路径的必经入口，被强杀 / 断电等来不及执行 finally 的场景留下的
    ``.part`` 残留会在这里被扫掉。

    **必须重排而非仅「不存在才加」（用户 2026-11-23 实测踩坑）**：
    本机系统 Python 的 ``Scripts`` **本来就在 PATH 首位**（环境自带），
    旧实现见「已存在」就跳过 → venv 虽有 yt-dlp，``shutil.which`` 仍命中
    系统那份 → 收口形同虚设。

    现在按候选目录的优先级顺序**重建 PATH 前缀**：venv 在最前，
    系统 Python 其次，其余 PATH 条目原序保留在后面。
    """
    _cleanup_stale_parts()
    cands = [BIN_DIR] + _candidate_scripts_dirs()
    # 收集要置顶的目录（保持优先级顺序，去重）
    front: list[str] = []
    seen: set[str] = set()
    for p in cands:
        try:
            if not p.is_dir():
                continue
        except OSError:
            continue
        key = os.path.normcase(os.path.abspath(str(p)))
        if key in seen:
            continue
        seen.add(key)
        front.append(str(p))
    if not front:
        return
    # 重建 PATH：置顶目录在最前，其余条目（去掉与置顶重复的）保持原序
    old = (os.environ.get("PATH") or "").split(os.pathsep)
    rest: list[str] = []
    for entry in old:
        e = entry.strip()
        if not e:
            continue
        try:
            key = os.path.normcase(os.path.abspath(e))
        except (OSError, ValueError):
            rest.append(e)
            continue
        if key in seen:
            continue  # 已在置顶区，避免重复
        rest.append(e)
    os.environ["PATH"] = os.pathsep.join(front + rest)


def _which(name: str) -> str:
    ensure_component_path()
    return shutil.which(name) or ""


# --------------------------------------------------------------------------- #
# 导入可用性校验（缺陷 4：轻量探测假绿灯）
# --------------------------------------------------------------------------- #
def _is_managed_path(path: str) -> bool:
    """该 exe 是否位于**软件自己管理的目录**下（Jinghe 组件目录内）。

    受控目录里的组件由软件自己安装与维护，其可用性用**DLL 依赖预检**
    判断（见 :func:`_dll_precheck`），而不是 import 校验（太慢）。
    """
    try:
        p = Path(os.path.abspath(path)).resolve()
        root = COMPONENT_DIR.resolve()
        return str(p).lower().startswith(str(root).lower())
    except (OSError, ValueError):
        return False


def _site_packages_of(exe_path: str) -> Path:
    """由 console script 的 exe 路径反推其所属 Python 的 site-packages。

    两种常见布局都要覆盖（venv 与系统安装不同）：

    * venv（Windows）：``<venv>\\Scripts\\<exe>``
      → site-packages = ``<venv>\\Lib\\site-packages``
      （注意 venv **没有** 系统的 ``PythonXY\\`` 那一层）
    * 系统安装：``<Python>\\Lib\\site-packages\\Scripts\\<exe>``
      → site-packages = ``<Python>\\Lib\\site-packages``

    做法：不猜层级，**从 Scripts 目录逐级向上找含 site-packages 的祖先**。
    找不到时返回一个不存在的路径（调用方据此跳过预检，不误判）。
    """
    try:
        cur = Path(os.path.abspath(exe_path)).resolve().parent
    except (OSError, ValueError):
        return Path(os.path.abspath(exe_path)).parent / "__no_site_packages__"
    # 从 Scripts 向上最多找 4 层，命中含 site-packages 的目录即返回
    for _ in range(4):
        cand = cur / "Lib" / "site-packages"
        if cand.is_dir():
            return cand
        cand = cur / "site-packages"
        if cand.is_dir():
            return cand
        if cur.parent == cur:
            break
        cur = cur.parent
    return Path(os.path.abspath(exe_path)).parent / "__no_site_packages__"


def _base_python_dirs(site_packages: Path) -> list[Path]:
    """列出可能存放 Python 自身 DLL（python3xx.dll）的目录。

    venv 的 ``pyvenv.cfg`` 记录了基础解释器路径，Python DLL 在**那里**，
    不在 venv 内（venv 只拷贝了 exe）。查不到就退而求其次用层级推断。
    """
    out: list[Path] = []
    try:
        cfg = site_packages.parent.parent / "pyvenv.cfg"
        if cfg.is_file():
            for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
                key, _, val = line.partition("=")
                if key.strip().lower() == "home" and val.strip():
                    out.append(Path(val.strip()))
    except OSError:
        pass
    # 层级推断：site-packages 的上上级（venv 根 或 Python 根）
    try:
        out.append(site_packages.parent.parent)
    except (OSError, ValueError):
        pass
    return out


def _pe_import_dlls(dll_path: Path) -> list[str]:
    """解析 PE 文件的导入表，返回它依赖的 DLL 名列表。

    只用标准库 struct 手工解析，不依赖 pefile 等第三方库。
    解析失败（不是 PE / 格式异常）返回空列表 —— 宁可放过，不误报。
    """
    try:
        data = dll_path.read_bytes()
    except OSError:
        return []
    try:
        if len(data) < 0x40:
            return []
        e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
        if e_lfanew + 4 > len(data) or data[e_lfanew:e_lfanew + 4] != b"PE\x00\x00":
            return []
        coff = e_lfanew + 4
        nsec = struct.unpack_from("<H", data, coff + 2)[0]
        optsz = struct.unpack_from("<H", data, coff + 16)[0]
        opt = coff + 20
        magic = struct.unpack_from("<H", data, opt)[0]
        # 导入表目录在可选头的第 1 个数据目录项（偏移 96 / 112）
        dd_off = opt + (112 if magic == 0x20B else 96)
        imp_rva, _ = struct.unpack_from("<II", data, dd_off + 8)
        if not imp_rva:
            return []
        secs = []
        so = opt + optsz
        for i in range(nsec):
            b = so + i * 40
            vsz, va, rsz, ra = struct.unpack_from("<IIII", data, b + 8)
            secs.append((va, vsz, ra, rsz))

        def r2o(rva: int) -> int | None:
            for va, vsz, ra, rsz in secs:
                if va <= rva < va + max(vsz, rsz):
                    return ra + (rva - va)
            return None

        out: list[str] = []
        off = r2o(imp_rva)
        if off is None:
            return []
        while off + 20 <= len(data):
            ent = data[off:off + 20]
            if ent == b"\x00" * 20:
                break
            name_rva = struct.unpack_from("<I", ent, 12)[0]
            if not name_rva:
                break
            no = r2o(name_rva)
            if no is None:
                break
            end = data.find(b"\x00", no)
            if end < 0:
                break
            out.append(data[no:end].decode("ascii", "replace"))
            off += 20
        return out
    except (struct.error, IndexError, ValueError, UnicodeDecodeError):
        return []


def _dll_precheck(site_packages: Path, component: str = "") -> tuple[bool, str]:
    """扫描组件依赖的原生 DLL，检查其系统依赖是否齐备。

    返回 ``(ok, reason)``：

    * ``ok=True``  → 未发现缺失的系统 DLL
    * ``ok=False`` → 有缺失，``reason`` 说明缺什么、怎么补

    **为什么需要（用户 2026-11-23 实测）**：
    whisper 依赖 torch，torch 的 ``torch_cpu.dll`` 依赖
    ``VCRUNTIME140_THREADS.dll``（Microsoft Visual C++ Redistributable
    的一部分）。该 DLL 在本机 System32 中**完全缺失**时：
    文件在、pip 装成功、界面显示「已安装」，但真跑报
    ``OSError: [WinError 126]``。这是「组件装了却用不了」最典型的成因。

    只做**文件存在性**检查，不真正 LoadLibrary —— 后者会加载
    300MB 的 torch 进内存，代价与 import 相当，得不偿失。

    **按组件范围扫描**（``component``）：只查该组件真正依赖的原生库，
    避免一个组件被另一个组件的环境问题连坐（实测：yt-dlp 是纯 Python
    包，却因 torch 缺 VC++ 运行库被误判为不可用）。
    """
    if not site_packages.is_dir():
        return True, ""
    scan_dirs = _DLL_DEPS_BY_COMPONENT.get(component, _DLL_SCAN_DIRS)
    if not scan_dirs:
        return True, ""  # 该组件无原生依赖
    sys32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    # Python 自身的 DLL（python3xx.dll）在**基础解释器**目录，不在 venv 内
    # （venv 只拷贝 exe），故从 pyvenv.cfg 读出基础解释器路径一并搜。
    py_dirs = _base_python_dirs(site_packages)
    missing: set[str] = set()
    for sub in scan_dirs:
        d = site_packages / sub
        if not d.is_dir():
            continue
        try:
            dlls = list(d.glob("*.dll"))
        except OSError:
            continue
        for dll in dlls:
            for dep in _pe_import_dlls(dll):
                low = dep.lower()
                # API Set（api-ms-* / ext-ms-*）是系统虚拟转发，不落实体文件
                if low.startswith("api-ms-") or low.startswith("ext-ms-"):
                    continue
                # 搜索顺序：同目录 DLL（torch/lib 内部互相依赖）→
                # site-packages 上级（.libs 目录）→ 基础解释器目录
                # （python3xx.dll）→ System32（系统运行库）
                if (d / dep).exists():
                    continue
                if (site_packages.parent / dep).exists():
                    continue
                if any((root / dep).exists() for root in py_dirs):
                    continue
                if (sys32 / dep).exists():
                    continue
                missing.add(dep)
    if not missing:
        return True, ""
    # 区分「缺 VC++ 运行库」与「其它缺件」——前者有明确解法，要突出说明
    msvc = sorted(m for m in missing if m.lower() in _MSVC_RUNTIME_DLLS)
    others = sorted(missing - set(msvc))
    parts: list[str] = []
    if msvc:
        parts.append(
            "缺少 Microsoft Visual C++ 运行库：%s。\n"
            "请安装「Microsoft Visual C++ Redistributable（最新版本）」后重启软件，"
            "再重新启用该组件。" % "、".join(msvc))
    if others:
        parts.append("另缺少：%s。" % "、".join(others))
    return False, "".join(parts) or ("缺失 DLL：%s" % "、".join(sorted(missing)))


def _interpreter_for(exe_path: str) -> str:
    """由 console script 的 exe 路径反推它所属的 Python 解释器。

    exe 位于 ``<python>\\Scripts\\`` 下，其父目录即 Python 根目录。
    找不到可用解释器时返回空串（调用方据此跳过校验，不误判）。
    """
    try:
        scripts = Path(exe_path).resolve().parent
        base = scripts.parent
        for name in ("python.exe", "pythonw.exe"):
            cand = base / name
            if cand.is_file():
                return str(cand)
    except (OSError, ValueError):
        pass
    return ""


def _import_check(exe_path: str, module: str) -> tuple[bool, str]:
    """校验 ``module`` 能否被该 exe 所属的 Python 真正 import 成功。

    返回 ``(ok, reason)``：

    * ``ok=True``  → 导入成功，包确实可用
    * ``ok=False`` → 导入失败，``reason`` 带上真实错误（如 DLL 缺失）

    **为什么需要（缺陷 4，用户 2026-11-23 实测）**：
    ``media_tools._light_check_package`` 只校验「dist-info / 包目录 / entry_points
    存在」，能证明**pip 装过这个包**，但**证明不了包能用**。whisper 的
    ``__init__`` 会 import torch，torch 加载 ``shm.dll`` 失败（WinError 126）
    时：exe 在、包在、界面显示「已安装」，但用户点下去转写立刻报错——
    比直接说「未安装」更坑。故此处补一次**真实导入**校验。

    找不到解释器或超时时**不误判为坏**（返回 ok=True + 说明），
    避免因环境探测失败而把好组件误标为不可用。
    """
    py = _interpreter_for(exe_path)
    if not py:
        return True, ""  # 找不到解释器 → 无法判定，不误伤
    key = (os.path.normcase(os.path.abspath(py)), module)
    now = time.time()
    with _LOCK:
        hit = _IMPORT_CHECK_CACHE.get(key)
        if hit:
            ts, ok, reason = hit
            if now - ts < _IMPORT_CHECK_TTL:
                return ok, reason
    try:
        proc = subprocess.run(
            [py, "-c", "import %s" % module],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", timeout=60,
            creationflags=_CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        # 超时 ≠ 坏：环境慢，不误判
        with _LOCK:
            _IMPORT_CHECK_CACHE[key] = (now, True, "")
        return True, ""
    except (OSError, ValueError) as exc:
        with _LOCK:
            _IMPORT_CHECK_CACHE[key] = (now, True, "")
        return True, ""
    if proc.returncode == 0:
        with _LOCK:
            _IMPORT_CHECK_CACHE[key] = (now, True, "")
        return True, ""
    out = (proc.stdout or "").strip().splitlines()
    reason = out[-1][:200] if out else "导入失败（退出码 %d）" % proc.returncode
    with _LOCK:
        _IMPORT_CHECK_CACHE[key] = (now, False, reason)
    return False, reason


# --------------------------------------------------------------------------- #
# 清单与状态
# --------------------------------------------------------------------------- #
def _probe_one(probe_name: str, deep: bool = False) -> dict:
    """用统一的 ToolAdapter 探测，结果归一为 {available, version, reason, path}。

    argv / 版本正则 / 超时都从 media_tools.TOOL_SPECS 按名字取，绝不另写一套
    （避免与 S1 契约的探测口径分叉）；只注入我们自己的 which 以带上组件 PATH。

    ``deep=True`` 跳过轻量快路径、真跑探测命令（安装流程末尾的深度验证用）。

    **缺陷 4 修复（用户 2026-11-23 实测）**：轻量探测只证明「pip 装过这个包」，
    证明不了「包能用」。系统 Python 里那份 whisper 就是**包在但用不了**
    （torch 加载 shm.dll 失败），而界面因轻量探测显示「已安装」→ 用户点下去
    转写才炸。此处在轻量探测判定可用后，追加一次**真实导入校验**：
      * 受控目录（Jinghe 组件目录）内的组件 → 装完已深验过，跳过（省 1 秒）
      * 外部位置（系统 Python 等）的组件 → 必须校验，不可用则如实报 error
    """
    spec = next((s for s in media_tools.TOOL_SPECS if s[0] == probe_name), None)
    if spec is None:
        return {"available": False, "version": "", "reason": "无探测规格", "path": ""}
    adapter = media_tools.ToolAdapter(
        spec[0], spec[1], spec[2],
        timeout=media_tools.PROBE_TIMEOUTS.get(probe_name, media_tools.DEFAULT_TIMEOUT),
        which=_which,
        deep=deep,
    )
    r = adapter.probe()
    result = {
        "available": bool(r.get("available")),
        "version": r.get("version") or "",
        "reason": r.get("reason") or "",
        "path": r.get("path") or "",
        # ok / missing / timeout / error：超时与「真没装」必须分开，
        # 否则界面只显示「未安装」，用户无法区分（用户 2026-11-19 实测）。
        "state": r.get("state") or ("ok" if r.get("available") else "missing"),
    }
    # 轻量探测判为可用时，补一次可用性校验（缺陷 4）
    if result["available"] and not deep:
        module = _IMPORT_CHECK_TARGETS.get(probe_name)
        exe = result["path"]
        if module and exe:
            if _is_managed_path(exe):
                # 受控目录：用 DLL 依赖预检（毫秒级）。**不能豁免**——
                # 豁免会让「假绿灯」回归（本机 venv 内 whisper 因系统缺
                # VCRUNTIME140_THREADS.dll 而不可用，探测却报已安装）。
                ok, reason = _dll_precheck(_site_packages_of(exe), probe_name)
            else:
                # 外部位置：用真实 import 校验（抓 Python 层错误）
                ok, reason = _import_check(exe, module)
            if not ok:
                result["available"] = False
                result["state"] = "error"
                result["reason"] = (
                    "已检测到 %s，但组件实际不可用：%s\n"
                    "（文件存在不等于可用，通常是原生依赖 DLL 缺失或版本不匹配。"
                    "建议在设置页重新安装该组件。）" % (probe_name, reason)
                )
    return result


def _external_install_hint(comp: dict) -> str:
    """检测「用户系统里有、但 Jinghe 组件目录里没有」的组件，给出迁移提示。

    **背景（v1.4.0 收口）**：pip 包改装进 ``components\\venv`` 后，用户此前
    手动装在系统 Python 里的组件**不再算作「Jinghe 组件已安装」** ——
    这是收口的有意前提（否则卸载仍清不掉它们）。

    但**不能一棍子打死**：系统那份若**实际可用**，功能照常工作，只是
    不受软件管理。此时界面应如实说明「检测到系统内已有可用版本」，
    让用户自己决定是否装到 Jinghe 目录（点了也只是多一份，不影响使用）。

    返回空串表示无迁移提示。
    """
    try:
        found = shutil.which(comp["probe"])
    except Exception:
        found = ""
    if not found:
        return ""
    try:
        if _is_managed_path(found):
            return ""  # 已在受控目录，无需提示
    except Exception:
        pass
    return ("检测到系统 Python 中已有 %s（%s）。\n"
            "如需让精核统一管理并支持一键清理，可重新点「启用」装到精核目录；"
            "不重新安装也不影响使用。" % (comp["name"], found))


def list_components(refresh: bool = False) -> dict:
    """组件清单；installed 以真实探测为准，不缓存安装状态。"""
    if refresh:
        # 只清缓存，**不关刷新窗口**（reset_cache 会关窗，会让同一轮里
        # audio/video 的探测重新真跑一遍，用户 2026-11-19 实测端点耗时 4 秒）
        with media_tools._LOCK:
            media_tools._CACHE = None
    ensure_component_path()
    items = []
    for c in COMPONENTS:
        st = _probe_one(c["probe"])
        items.append({
            "id": c["id"],
            "name": c["name"],
            "desc": c["desc"],
            "installed": st["available"],
            "version": st["version"],
            "path": st["path"],
            "reason": "" if st["available"] else (st["reason"] or "未安装"),
            "state": st["state"],
            # 迁移提示：系统里已有可用组件时给出说明（不强制重装）
            "migration_hint": _external_install_hint(c) if not st["available"] else "",
        })
    with _LOCK:
        job = {
            "running": _JOB["running"],
            "id": _JOB["id"],
            "state": _JOB["state"],
            "percent": _JOB["percent"],
            "message": _JOB["message"],
        }
    return {"ok": True, "components": items, "job": job, "install_dir": str(BIN_DIR)}


# --------------------------------------------------------------------------- #
# 进度事件
# --------------------------------------------------------------------------- #
def _emit(event: str, text: str, progress: float | None = None,
          component_id: str | None = None) -> None:
    job = _job_for(component_id)
    with _LOCK:
        seq = job["next_seq"]
        job["next_seq"] = seq + 1
        ev = {"seq": seq, "type": event, "text": text, "progress": progress,
              "cid": job["id"]}
        job["events"].append(ev)
        if len(job["events"]) > 500:
            job["events"] = job["events"][-200:]
        if progress is not None:
            job["percent"] = max(0.0, min(100.0, float(progress) * 100.0))
        job["message"] = text


def install_status(since: int = 0, component_id: str | None = None) -> dict:
    """单个组件进度（cid 为空=最近任务）；cid='*' 返回全部任务快照。"""
    if component_id == "*":
        with _LOCK:
            jobs = {}
            for cid, job in _JOBS.items():
                jobs[cid] = {
                    "events": [dict(e) for e in job["events"]],
                    "next": job["next_seq"] - 1,
                    "running": job["running"], "state": job["state"],
                    "percent": round(job["percent"], 1),
                    "message": job["message"], "error": job["error"],
                    "id": cid,
                }
            running_n = sum(1 for j in _JOBS.values() if j["running"])
        return {"ok": True, "jobs": jobs, "running": running_n,
                "events": [], "next": 0, "state": "running" if running_n else "idle",
                "percent": 0.0, "message": "", "error": "", "id": ""}
    job = _job_for(component_id)
    with _LOCK:
        events = [dict(e) for e in job["events"] if e["seq"] > since]
        nxt = job["next_seq"] - 1
        return {
            "ok": True,
            "events": events,
            "next": nxt,
            "running": job["running"],
            "state": job["state"],
            "percent": round(job["percent"], 1),
            "message": job["message"],
            "error": job["error"],
            "id": job["id"],
        }


def cancel_install(component_id: str | None = None) -> dict:
    job = _job_for(component_id)
    with _LOCK:
        if not job["running"]:
            return {"ok": False, "error": "当前没有安装任务"}
        job["cancelled"] = True
    _emit("info", "已请求取消，正在清理…", None, job["id"])
    return {"ok": True}


def _cancelled(component_id: str | None = None) -> bool:
    job = _job_for(component_id)
    with _LOCK:
        return job["cancelled"]


# --------------------------------------------------------------------------- #
# 下载与安装
# --------------------------------------------------------------------------- #
def _require_opt_in(component_id: str) -> None:
    """下载前的硬闸门：必须存在刚由 install() 写入的手动点击令牌。

    这是「绝不主动下载」的代码级保证：探测 / 定时器 / 其它模块即使误调
    下载函数，也会因无令牌而失败，不会发出任何网络请求。
    """
    with _LOCK:
        # 新机制：按组件 id 的令牌集合，互不消费（支持并发）。
        in_set = component_id in _USER_OPT_INS
        if in_set:
            _USER_OPT_INS.discard(component_id)
        # 兼容视图：旧测试/旧调用直接写 _USER_OPT_IN 后调本函数。
        legacy = (_USER_OPT_IN["granted"]
                  and _USER_OPT_IN["component_id"] == component_id)
        if legacy:
            _USER_OPT_IN["granted"] = False
            _USER_OPT_IN["component_id"] = ""
        ok = in_set or legacy
    if not ok:
        raise RuntimeError("未获用户手动启用授权，拒绝下载（软件绝不主动下载）")


def _download(url: str, dest: Path, component_id: str) -> None:
    """流式下载（走环境变量代理），写 .part 后原子替换。必须持手动令牌。

    **``.part`` 必须在任何失败路径都被清理（缺陷 1，用户 2026-11-23 实测）**：
    原实现只在「主动取消」分支里 ``tmp.unlink()``，而网络断开、进程被杀、
    用户关窗等异常中断**不经过该分支** → ``.part`` 永久残留
    （本机实测残留 13.6 MB 的 ``ffmpeg.zip.part``）。

    现在改为：``finally`` 中无条件清理「尚未改名」的临时文件。
    成功路径已 ``tmp.replace(dest)``（临时文件不存在，``missing_ok`` 兜底），
    失败路径则真正删除，绝不留下垃圾。
    """
    _require_opt_in(component_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "jinghe-component-installer"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            got = 0
            with open(tmp, "wb") as f:
                while True:
                    if _cancelled(component_id):
                        raise RuntimeError("cancelled")
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    if total:
                        _emit("progress", "下载中 %d%%" % int(got * 100 / total),
                              got / total, component_id)
                    else:
                        _emit("progress", "已下载 %.1f MB" % (got / 1024 / 1024),
                              None, component_id)
        tmp.replace(dest)
    finally:
        # 成功路径：tmp 已被 replace 走，文件不存在 → missing_ok 静默跳过
        # 失败路径：删除残留的半截文件
        tmp.unlink(missing_ok=True)


def _cleanup_stale_parts() -> list[str]:
    """清理组件目录里遗留的 ``*.part`` 半截文件（缺陷 1 兜底）。

    进程被强杀 / 断电 / 崩溃等**连 finally 都来不及执行**的路径仍可能留下
    ``.part``。本函数在组件目录被使用前调用一次，把陈旧残留扫掉。

    只删 ``.part`` 后缀的**文件**（不递归、不碰目录、不碰任何其它文件），
    返回被清理的文件名列表，便于日志与测试断言。
    """
    removed: list[str] = []
    try:
        if not COMPONENT_DIR.is_dir():
            return removed
        for p in COMPONENT_DIR.glob("*.part"):
            try:
                if not p.is_file():
                    continue
                p.unlink()
                removed.append(p.name)
            except OSError:
                # 被占用等：跳过即可，不能因清理失败影响主流程
                continue
    except OSError:
        return removed
    return removed


def _extract_ffmpeg(zip_path: Path) -> str:
    """从静态 zip 里取出 ffmpeg.exe（及 ffprobe.exe，顺带增强）。"""
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    copied = []
    with zipfile.ZipFile(zip_path) as zf:
        members = [m for m in zf.namelist()
                   if m.lower().endswith(("ffmpeg.exe", "ffprobe.exe"))
                   and "/" not in m.rstrip("/").replace("\\", "/")[:-10]]
        # 只取文件名就匹配的目标（允许 bin/ 前缀）
        targets = [m for m in zf.namelist()
                   if m.lower().endswith(("/ffmpeg.exe", "/ffprobe.exe"))]
        for m in (targets or members):
            name = m.replace("\\", "/").rsplit("/", 1)[-1]
            if name.lower() not in ("ffmpeg.exe", "ffprobe.exe"):
                continue
            with zf.open(m) as src, open(BIN_DIR / name, "wb") as dst:
                shutil.copyfileobj(src, dst)
            copied.append(name)
    zip_path.unlink(missing_ok=True)
    if "ffmpeg.exe" not in copied:
        raise RuntimeError("压缩包内未找到 ffmpeg.exe")
    return "已解压 " + ", ".join(copied)


def _python_root_has_exe(root: Path) -> str:
    """给定 Python 根目录，返回其中的 python.exe（存在才返回）。"""
    for name in ("python.exe", "python"):
        p = root / name
        try:
            if p.is_file():
                return str(p)
        except OSError:
            continue
    return ""


# --------------------------------------------------------------------------- #
# venv 管理（v1.4.0 组件收口核心）
# --------------------------------------------------------------------------- #
def _venv_python_usable() -> bool:
    """venv 是否存在且可用。

    判定标准（三项全过）：
      1. ``venv\\Scripts\\python.exe`` 存在；
      2. 能真的跑起来（``-c pass`` 退出码 0）—— 防「文件在但环境已坏」；
      3. ``pyvenv.cfg`` 存在 —— 说明它是完整的 venv，不是随便拷来的 exe。

    第 3 项防的是一种隐蔽故障：用户（或清理工具）删掉了 ``Lib\\site-packages``
    只留下 ``Scripts``，此时 exe 能跑但 pip 装不了包。
    """
    try:
        if not VENV_PYTHON.is_file():
            return False
        if not (VENV_DIR / "pyvenv.cfg").is_file():
            return False
        proc = subprocess.run(
            [str(VENV_PYTHON), "-c", "pass"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=30, creationflags=_CREATE_NO_WINDOW)
        return proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _create_venv(base_python: str) -> str:
    """用 ``base_python`` 创建 venv，返回 venv 内的 python 路径。

    创建失败时抛异常，由调用方转成可读报错。**不会静默降级到宿主 Python**——
    降级会导致「装 A 处探 B 处」，正是本模块要消灭的病根。
    """
    try:
        VENV_DIR.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            [base_python, "-m", "venv", str(VENV_DIR)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            timeout=300, creationflags=_CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("创建虚拟环境失败：%s" % exc)
    if proc.returncode != 0:
        out = (proc.stdout or "").strip().splitlines()
        detail = out[-1][:200] if out else "（无输出）"
        raise RuntimeError("创建虚拟环境失败（退出码 %d）：%s" % (proc.returncode, detail))
    if not _venv_python_usable():
        raise RuntimeError("虚拟环境已创建但校验未通过（venv\\Scripts\\python.exe 不可用）")
    return str(VENV_PYTHON)


def _ensure_venv() -> str:
    """确保 venv 可用，返回 venv 内的 python 路径；不存在则用系统 Python 创建。

    **为什么用系统 Python 创建、而不是内置运行时（v1.4.0 决策）**：
    venv 的 Python 版本窗口必须**跟随用户机器**。组件的版本要求会随时间右移
    （实测 yt-dlp 2026.10.26 要求 ``>=3.11``；torch 的 win wheel 从 cp310~313
    一路覆盖到 cp311~315）。若把运行时锁死在安装包里，一旦内置版本落后于
    组件要求窗口，功能就会**静默失效**（显示已安装，pip 报 requires a
    different Python），排查成本极高。用系统 Python 建 venv 则天然免疫。

    若用户机器**确实没有 Python**，此处会抛出带指引的异常；
    按需下载便携 Python 到 ``components\\runtime\\`` 的兜底逻辑留待 v1.4.x。
    """
    if _venv_python_usable():
        return str(VENV_PYTHON)
    base = _find_python_for_pip()
    if not base:
        raise RuntimeError(
            "未找到可用于创建组件环境的 Python 解释器。\n"
            "请安装 Python 3.11 或更高版本（安装时勾选「Add Python to PATH」），"
            "重启软件后再点启用。")
    try:
        return _create_venv(base)
    except RuntimeError as exc:
        raise RuntimeError("%s\n（用到的 Python：%s）" % (exc, base))


def _python_for_pip() -> str:
    """返回能真正执行 ``-m pip`` 的 Python 解释器路径。

    **优先级（v1.4.0 组件收口）**：
      1. **venv 内的 python** —— 新装的包一律进 venv，装与探严格同源；
      2. 系统 Python —— venv 尚未建立时回退（保证「用户手动装在系统
         Python 的组件」仍可被探测与维护，且 venv 能用它来创建）。

    **这里不会自动创建 venv**：探测是高频只读操作，不能有副作用；
    创建 venv 只发生在用户点击「启用」的安装流程里（见 :func:`_ensure_venv`）。

    **冻结态陷阱（用户 2026-11-19 实测踩到：pip 退出码 2）**：PyInstaller
    打包后 ``sys.executable`` 指向 ``Jinghe.exe`` 本身，exe 不内置 pip，
    ``Jinghe.exe -m pip install ...`` 会被当成程序参数 → 退出码 2。
    因此冻结态必须改用本机真实 Python；源码态才用 ``sys.executable``。

    **第二个坑（同日实测）**：Windows 上用户 PATH 常只含 ``...\\Python3xx\\Scripts``
    （whisper.exe 所在），**不含** ``python.exe`` 所在的父目录，导致
    ``shutil.which("python")`` 失败。故增加「从 PATH 里的 Scripts 反推父目录」
    策略——这是本机 workbuddy Python 的真实布局。查找顺序：
      1. PATH 直接找 python.exe；
      2. PATH 每个条目若以 Scripts 结尾，反推父目录找 python.exe；
      3. 从已探测到的 whisper/yt-dlp 位置反推；
      4. LOCALAPPDATA/Programs/Python 与 C:\\Python3xx 常见位置。
    全部失败才诚实报错，并给出可操作指引。

    **结果缓存**（仅冻结态）：首次选定后即锁定，保证「pip 装到哪」与
    「探测去哪」全程同一个 Python（否则中途环境变化会装探错位）。
    源码态不缓存——``sys.executable`` 本身不会变。
    缓存带**环境指纹**（PATH），PATH 变了就重新查找，避免环境变更后
    仍用旧结果导致「装探错位」。
    """
    # ① venv 优先（软件自管目录，装探同源）
    try:
        if _venv_python_usable():
            return str(VENV_PYTHON)
    except Exception:
        pass
    if not getattr(sys, "frozen", False):
        return sys.executable
    global _PIP_PYTHON, _PIP_PYTHON_FP
    fingerprint = os.environ.get("PATH") or ""
    with _LOCK:
        if _PIP_PYTHON and _PIP_PYTHON_FP == fingerprint:
            return _PIP_PYTHON
    found = _find_python_for_pip()
    with _LOCK:
        _PIP_PYTHON = found
        _PIP_PYTHON_FP = fingerprint
    return found


def _pip_scripts_dir(python_exe: str) -> Path:
    """**问 pip 自己**它的 console script 落点，绝不靠猜。

    为什么必须问（用户 2026-11-19 实测踩坑）：
    ``Path(python).resolve()`` 会把 Windows junction 展开成别名路径
    （本机 ``...\\versions\\3.13.12`` → ``...\\vendor\\python``），
    而 pip 用的是**未解析的真实路径**。两者一旦不是同一目录，就会
    「pip 装到 A、探测去 B」→ 安装结束仍探测不到 whisper.exe。
    直接问 pip 的 ``sysconfig.get_path('scripts')`` 可保证装与探同源。
    """
    try:
        out = subprocess.run(
            [python_exe, "-c",
             "import sysconfig;print(sysconfig.get_path('scripts'))"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", timeout=20,
            # 必须带 NO_WINDOW：否则每次探测都会在桌面弹一个控制台黑框
            # （用户 2026-11-19 实测被弹窗刷屏，根因即此处漏加）
            creationflags=_CREATE_NO_WINDOW)
        path = (out.stdout or "").strip().splitlines()
        if path and path[0]:
            p = Path(path[0].strip())
            if p.is_dir():
                return p
    except Exception:
        pass
    # 兜底：未解析的真实父目录 + Scripts（不做 resolve，避免展开 junction）
    return Path(python_exe).parent / "Scripts"


def _find_python_for_pip() -> str:
    """真正执行查找逻辑（见 :func:`_python_for_pip` 的策略说明）。"""
    if not getattr(sys, "frozen", False):
        return sys.executable
    exepath = os.path.normcase(os.path.abspath(sys.executable))

    def valid(p: str) -> bool:
        return bool(p) and os.path.normcase(os.path.abspath(p)) != exepath

    # ① PATH 直接找
    for name in ("python.exe", "python", "python3.exe", "python3"):
        found = shutil.which(name)
        if valid(found):
            return found
    # ② 从 PATH 里的 Scripts 反推父目录（本机 workbuddy Python 布局）
    for entry in (os.environ.get("PATH") or "").split(os.pathsep):
        entry = entry.strip().strip('"')
        if not entry:
            continue
        try:
            p = Path(entry)
            if p.name.lower() == "scripts":
                got = _python_root_has_exe(p.parent)
                if valid(got):
                    return got
        except OSError:
            continue
    # ③ 从已装 CLI（whisper/yt-dlp）位置反推
    for cli in ("whisper", "whisper.exe", "yt-dlp", "yt-dlp.exe"):
        found = shutil.which(cli)
        if found:
            got = _python_root_has_exe(Path(found).resolve().parent.parent)
            if valid(got):
                return got
    # ④ 常见安装位置
    roots = [Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python"]
    roots += [Path("C:/Python3%d" % n) for n in range(8, 14)]
    for base in roots:
        try:
            for child in sorted(base.glob("python3*"), reverse=True):
                got = _python_root_has_exe(child)
                if valid(got):
                    return got
        except OSError:
            continue
    raise RuntimeError(
        "未在本机找到可用于 pip 的 Python 解释器。\n"
        "Whisper 约 640 MB（含 torch 464 MB），需联网下载，无法打包进软件。\n"
        "解决办法（选一）：\n"
        "  1) 安装 Python 时勾选「Add Python to PATH」，重启软件后再点启用；\n"
        "  2) 手动执行 pip install openai-whisper，重启软件即可识别；\n"
        "  3) 若已装在本机，把 python.exe 所在目录加入 PATH。")


def _pip_cmd_install(package: str) -> list[str]:
    """组装 pip install 命令，正确处理「无代理」情形。

    旧代码 ``if not cmd[-1]: cmd = cmd[:-2]`` 永远为 False（末项是
    ``--disable-pip-version-check`` 常量），导致无代理时仍传 ``--proxy ""``，
    pip 会报参数错误。这里改为显式判断代理值。
    """
    proxy = (os.environ.get("HTTPS_PROXY")
             or os.environ.get("https_proxy")
             or os.environ.get("HTTP_PROXY")
             or os.environ.get("http_proxy") or "").strip()
    cmd = [_python_for_pip(), "-m", "pip", "install", package,
           "-i", PIP_INDEX, "--trusted-host", PIP_TRUSTED_HOST,
           "--disable-pip-version-check"]
    if proxy:
        cmd.extend(["--proxy", proxy])
    return cmd


def _pip_install(package: str, component_id: str) -> str:
    """用内置镜像装 Python 包，解析 pip 输出映射为 5%~95% 的进度。必须持手动令牌。

    **v1.4.0 收口**：安装目标解释器切到 **venv 内的 python** ——
    新装的包一律落在 ``components\\venv``，**不再污染宿主 Python**
    （改造前 whisper+torch 共 554MB 会留在系统 site-packages，卸载清不掉）。

    venv 不可用时（如用户机器没有 Python）由 :func:`_ensure_venv` 抛出
    带指引的异常，**绝不静默降级**到宿主 Python —— 降级会重新引入
    「装 A 处探 B 处」的病根。
    """
    _require_opt_in(component_id)
    cmd = _pip_cmd_install(package)
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
        bufsize=1, creationflags=_CREATE_NO_WINDOW,
    )
    steps = ("Collecting", "Downloading", "Installing", "Successfully installed")
    reached = set()
    errors: list[str] = []   # 收集 pip 的 ERROR 行，失败时回显真实原因
    assert proc.stdout is not None
    for line in proc.stdout:
        if _cancelled(component_id):
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            raise RuntimeError("cancelled")
        text = line.rstrip()
        if "ERROR" in text or "error:" in text.lower():
            errors.append(text[:200])
            _emit("progress", text[:120], None, component_id)
        for i, kw in enumerate(steps):
            if kw in text and kw not in reached:
                reached.add(kw)
                _emit("progress", text[:120],
                      min(0.95, (i + 1) / (len(steps) + 1)), component_id)
                break
        else:
            if "Downloading" in text or "MB" in text:
                _emit("progress", text[:120], None, component_id)
    rc = proc.wait()
    if rc != 0:
        # 用户要能看到 pip 的真实报错，而不是只有「退出码 2」这种谜语
        detail = errors[-1] if errors else "（pip 未输出 ERROR 行）"
        raise RuntimeError("pip 安装失败（退出码 %d）：%s" % (rc, detail))
    return "安装完成"


def _ensure_console_script(python_exe: str, package: str, exe_name: str) -> str:
    """包已装但 console script（exe）缺失时，**离线补生成**该 exe。

    **为什么需要（用户 2026-11-19 实测踩坑）**：pip 装的其实是「包」，
    ``whisper.exe`` 只是它的 console script 副产品。若包早已安装
    （``Requirement already satisfied``），pip 会**整个跳过**，
    **不会补回丢失的 exe** → 软件报「安装结束仍探测不到 whisper.exe」。
    重装（``--force-reinstall``）也不可行：需重下 640 MB，且内网镜像
    在部分网络下不可达（``from versions: none``）。

    这里用 **pip 自带的 distlib ScriptMaker** 离线重建启动器：
    不联网、不重装依赖、pip 与生成器版本天然匹配。
    返回生成结果描述；失败时抛异常，由调用方转成可读报错。
    """
    code = r"""
import sys
from importlib.metadata import distribution
try:
    from pip._vendor.distlib.scripts import ScriptMaker
except Exception:
    from pip._internal.operations.install.wheel import ScriptMaker
pkg = sys.argv[1]
exe = sys.argv[2]
scripts_dir = sys.argv[3]
dist = distribution(pkg)
eps = [e for e in dist.entry_points if e.group == "console_scripts"]
if not eps:
    raise SystemExit("包 %s 没有 console_scripts 入口点" % pkg)
maker = ScriptMaker(None, scripts_dir)
maker.executable = sys.executable
maker.set_mode = True
made = []
for ep in eps:
    made += maker.make("%s = %s" % (ep.name, ep.value))
print("|".join(made))
"""
    scripts_dir = str(_scripts_dir())
    try:
        out = subprocess.run(
            [python_exe, "-c", code, package, exe_name, scripts_dir],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", timeout=120,
            creationflags=_CREATE_NO_WINDOW)
    except Exception as exc:
        raise RuntimeError("补生成 %s 失败：%s" % (exe_name, exc))
    if out.returncode != 0:
        raise RuntimeError("补生成 %s 失败：%s" % (
            exe_name, (out.stderr or out.stdout or "").strip()[:300]))
    made = (out.stdout or "").strip().splitlines()[-1:] if out.stdout else []
    target = os.path.join(scripts_dir, exe_name)
    if not os.path.isfile(target):
        raise RuntimeError("补生成 %s 后仍未找到：%s" % (exe_name, target))
    return "已离线补生成 %s" % (made[0] if made else exe_name)


def _install_worker(component_id: str) -> None:
    comp = _BY_ID.get(component_id)
    job = _job_for(component_id)
    try:
        if not comp:
            raise RuntimeError("未知组件：%s" % component_id)
        _emit("progress", "准备安装 %s…" % comp["name"], 0.01, component_id)
        if comp["kind"] == "zip":
            dest = COMPONENT_DIR / (comp["id"] + ".zip")
            _download(comp["url"], dest, component_id)
            _emit("progress", "解压中…", 0.9, component_id)
            detail = _extract_ffmpeg(dest)
        else:
            # v1.4.0 收口：pip 类组件一律装进 **venv**（软件专属目录），
            # 不再污染宿主 Python。venv 不存在/失效时在此创建（用系统 Python）。
            _emit("progress", "准备组件运行环境…", 0.02, component_id)
            venv_python = _ensure_venv()
            detail = _pip_install(comp["package"], component_id)
            # pip 装的是「包」，exe 是它的副产品：包已装但 exe 丢失时，
            # pip 会「already satisfied」整个跳过、不会补回 exe → 离线补生成。
            try:
                exe_path = _scripts_dir() / comp["exe"]
            except RuntimeError:
                exe_path = None
            if exe_path is not None and not exe_path.is_file():
                _emit("progress", "补生成 %s 启动器…" % comp["exe"], 0.97, component_id)
                detail = _ensure_console_script(
                    venv_python, comp["package"], comp["exe"])

        if _cancelled(component_id):
            raise RuntimeError("cancelled")
        ensure_component_path()
        # 安装流程末尾做**深度验证**（真跑探测命令）：此处必须确认命令真的
        # 能跑，不能只凭轻量检查说「装好了」。
        st = _probe_one(comp["probe"], deep=True)
        if not st["available"]:
            # 报错必须带诊断信息（用户 2026-11-19 反馈：只有「仍探测不到」
            # 无法定位）。此处明示：pip 用哪个 Python、探测查哪个目录、
            # 目标 exe 是否真的不在那里。
            try:
                py = _python_for_pip()
            except RuntimeError:
                py = "(未找到 Python)"
            dirs = [str(d) for d in _candidate_scripts_dirs()]
            raise RuntimeError(
                "安装结束但仍探测不到 %s。\n"
                "诊断：pip 使用 Python = %s\n"
                "　　 探测查找目录 = %s\n"
                "　　 目标文件是否存在 = %s\n"
                "请重启软件后重试；若仍失败，请把以上诊断信息反馈给开发者。"
                % (comp["exe"], py, " | ".join(dirs) or "(无)",
                   (Path(dirs[0]) / comp["exe"]).is_file() if dirs else "未知"))
        with _LOCK:
            job["state"] = "done"
            job["percent"] = 100.0
            job["running"] = False
        _emit("done", "%s 安装成功（%s）" % (comp["name"], detail or st["version"]), 1.0, component_id)
    except Exception as exc:  # noqa: BLE001 - 后台线程必须落地任何失败
        msg = str(exc)
        cancelled = msg == "cancelled" or _cancelled(component_id)
        with _LOCK:
            job["state"] = "cancelled" if cancelled else "failed"
            job["running"] = False
            job["error"] = "" if cancelled else msg
        _emit("cancelled" if cancelled else "error",
              "已取消安装" if cancelled else ("安装失败：" + msg), None, component_id)


def install(component_id: str) -> dict:
    """启动安装（异步）。**仅代表用户手动点击「启用」后由 UI 调用**。

    软件内部（启动 / 探测 / 定时器 / 其它模块）一律不得调用本函数去下载；
    令牌机制保证即便误调，下载层也会拒绝。多组件可并发（各自独立 job/令牌）。
    """
    global _JOB
    comp = _BY_ID.get(component_id)
    if not comp:
        return {"ok": False, "error": "未知组件"}
    # v0.10：按组件维度判断是否已在装——不同组件可并发，同一组件仍拒绝重复点击
    with _LOCK:
        existing = _JOBS.get(component_id)
        if existing and existing["running"]:
            return {"ok": False, "error": "该组件正在安装中，请勿重复点击"}
    check = _probe_one(comp["probe"])
    if check["available"]:
        with _LOCK:
            job = _JOBS.setdefault(component_id, _new_job(component_id))
            job.update({"running": False, "state": "done", "percent": 100.0,
                        "id": component_id, "events": [], "next_seq": 1})
            _JOB = job
        _emit("done", "%s 已安装" % comp["name"], 1.0, component_id)
        return {"ok": True, "already_installed": True}
    # 只有走到这里（用户点了启用 + 组件确实未安装）才发令牌。
    # 并发：每组件独立令牌写入 set；兼容视图 _USER_OPT_IN 指向最近一个。
    with _LOCK:
        _USER_OPT_INS.add(component_id)
        _USER_OPT_IN["granted"] = True
        _USER_OPT_IN["component_id"] = component_id
        job = _JOBS.setdefault(component_id, _new_job(component_id))
        job.update({
            "running": True, "id": component_id, "state": "running",
            "percent": 0.0, "message": "", "error": "", "cancelled": False,
            "events": [], "next_seq": 1,
        })
        _JOB = job
    threading.Thread(target=_install_worker, args=(component_id,),
                     name="jinghe-component-install-%s" % component_id,
                     daemon=True).start()
    return {"ok": True, "already_installed": False}
