#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精核 · 音频 → .md（S3 · 阶段 3 一期）。

本模块是**独立后处理层**，与冻结内核完全正交：

* 不 import 也不修改 ``extract.py`` 的提取流水线；``SPEC.md`` 一字不动。
  音视频在阶段 1 仍走 ``DEFERRED_EXT`` 的「设计内降级」，由
  ``test_extract.py::test_06`` / ``test_11`` 原样守护。
* 零第三方依赖：只用标准库 ``subprocess`` / ``json`` / ``pathlib``。
  转写后端是**用户本机**的 whisper CLI，容器元数据读本机 ffmpeg；
  软件不下载模型、不打包工具、不自动安装、不内置任何凭据（契约 §3）。
* **只处理音频**。视频后缀一律拒收，交给 S4 独立 video handler，
  绝不复用本模块的路径（红线 2 / 契约 §4.2）。
* **绝不产出伪转写**：只认 whisper 的 ``--output_format json`` 文件输出，
  必须有带合法时间戳且正文非空的 ``segments`` 才写 md；空分段 / 无语音 /
  非 JSON / 非 0 退出 / 缺工具一律 ``ok:false`` + 可读原因，零 md 产出，
  也**不生成「无语音」说明文档**（占位文本冒充产物同样违 §1.6）。

产物严格落 ``out/derived/<doc_id>.md`` + ``provenance_media.json``（追加），
自带 8 字段 ``src`` 来源注释与带 ``time`` 的块级锚点；**绝不写**
``out/md/``、``INDEX.md``、``MERGED.md``、``provenance.json``（契约 §4 / 不变量 7）。

端点由 ``app.py`` 后处理层挂 ``POST /api/audio/inspect``、
``POST /api/audio/transcribe``、``POST /api/audio/cancel``、
``GET /api/audio/status``；既有的 ``/api/transcribe`` 空心位**原样保留**。
"""
from __future__ import annotations

import atexit
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import format_registry
import media_runtime
import media_tools

# --------------------------------------------------------------------------- #
# 常量与安全上限
# --------------------------------------------------------------------------- #
MAX_BYTES = 256 * 1024 * 1024        # 单个音频文件上限，超限直接断链
MAX_SEGMENTS = 20000                 # 分段数上限，避免超大 json 撑爆内存
MAX_INPUTS = 50                      # 单批次文件数上限
DEFAULT_TIMEOUT = 900.0             # 单文件转写超时（秒）
DEFAULT_MODEL = "base"              # 模型由本机 whisper 自行准备，软件不下载
FFMPEG_PROBE_TIMEOUT = 15.0
ADAPTER_LABEL = "精核 S3 音频 ASR 适配器 v1（标准库调度）"
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_CREATE_NEW_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
_DURATION_RE = re.compile(r"Duration:\s*(\d{2}):(\d{2}):(\d{2}\.\d+)")
_AUDIO_STREAM_RE = re.compile(r"Stream\s+#\d+:\d+.*?Audio:\s*([^\r\n]+)", re.I)

STATUS_OK = "成功"
STATUS_UNSUPPORTED = "不支持"
STATUS_UNAVAILABLE = "未启用"
STATUS_NO_SPEECH = "无语音"
STATUS_FAILED = "失败"
STATUS_CANCELLED = "已取消"

# --------------------------------------------------------------------------- #
# 临时目录三链：父进程持有 → finally 删除 → atexit 兜底 → 启动清扫过期孤儿
# 前缀刻意与阶段 1 的 `jinghe-run-<pid>-<seq>` 隔离，避免误删另一条流水线。
# --------------------------------------------------------------------------- #
_TEMP_PREFIX = "jinghe-run-audio-"
_LIVE_TEMPS: set[str] = set()
_TEMPS_LOCK = threading.Lock()
_ORPHAN_MAX_AGE = 24 * 3600.0
_TEMP_SEQ = 0


def _register_temp(path: Path) -> None:
    with _TEMPS_LOCK:
        _LIVE_TEMPS.add(str(path))


def _drop_temp(path: Path) -> None:
    shutil.rmtree(str(path), ignore_errors=True)
    with _TEMPS_LOCK:
        _LIVE_TEMPS.discard(str(path))


def _cleanup_all_temps() -> None:
    with _TEMPS_LOCK:
        pending = list(_LIVE_TEMPS)
    for item in pending:
        shutil.rmtree(item, ignore_errors=True)
    with _TEMPS_LOCK:
        _LIVE_TEMPS.clear()


def sweep_orphan_temps() -> int:
    """启动 / 验收时清扫 24 小时前的孤儿目录；只按 mtime，不猜进程存活。"""
    root = Path(tempfile.gettempdir())
    now = time.time()
    removed = 0
    try:
        candidates = list(root.glob(_TEMP_PREFIX + "*"))
    except OSError:
        return 0
    for item in candidates:
        if not item.is_dir():
            continue
        with _TEMPS_LOCK:
            if str(item) in _LIVE_TEMPS:
                continue
        try:
            if now - item.stat().st_mtime < _ORPHAN_MAX_AGE:
                continue
            shutil.rmtree(str(item), ignore_errors=True)
            removed += 1
        except OSError:
            continue
    return removed


atexit.register(_cleanup_all_temps)
sweep_orphan_temps()


def _new_temp() -> Path:
    global _TEMP_SEQ
    with _TEMPS_LOCK:
        _TEMP_SEQ += 1
        seq = _TEMP_SEQ
    path = Path(tempfile.mkdtemp(
        prefix="%s%d-%d-" % (_TEMP_PREFIX, os.getpid(), seq)))
    _register_temp(path)
    return path


# --------------------------------------------------------------------------- #
# 能力探测：复用 S1 的 ToolAdapter 结果，绝不并入 TOOL_SPECS / capabilities()
# --------------------------------------------------------------------------- #
def capability(refresh: bool = False) -> dict:
    """``/api/tools/probe`` 的顶层增量字段 ``audio_transcribe``。

    S1 的 ``media_tools.capabilities()`` 是被 ``test_33`` 锁死的占位清单，
    恒 ``enabled=False``；S3 的真实状态只走本字段（S2a / S2b 同例）。
    whisper 负责转写，ffmpeg 负责容器时长探测，两者都可用才算启用。
    """
    tools = media_tools.probe_all(refresh=refresh)
    whisper = dict(tools.get("whisper") or {})
    ffmpeg = dict(tools.get("ffmpeg") or {})
    missing = [name for name, tool in (("whisper", whisper), ("ffmpeg", ffmpeg))
               if not tool.get("available")]
    enabled = not missing
    return {
        "name": "audio_transcribe",
        "enabled": enabled,
        "capability": "available" if enabled else "unavailable",
        "engine": {
            "name": "本机 whisper CLI + ffmpeg（未随软件分发）",
            "reason": ("音频转写由本机 whisper CLI 完成，ffmpeg 只读探测容器时长；"
                       "软件不下载模型、不打包工具、不自动安装"),
        },
        "tools": {"whisper": whisper, "ffmpeg": ffmpeg},
        "missing": missing,
        "reason": ("可用" if enabled else
                   "未启用：本机未找到 %s，请安装后重试"
                   % " / ".join(missing)),
        "input": {"exts": sorted(format_registry.MEDIA_AUDIO),
                  "max_bytes": MAX_BYTES, "max_inputs": MAX_INPUTS},
        "output": {"dirname": media_runtime.DERIVED_DIRNAME, "suffix": ".md"},
        "note": "只处理音频文件；视频由 S4 独立 handler 处理，不复用音频路径",
    }


def _converter(cap: dict) -> str:
    """8 字段 src 的 converter：只写真实工具名 + 探测到的版本。"""
    w = cap["tools"]["whisper"]
    f = cap["tools"]["ffmpeg"]
    wv = w.get("version") or "版本未探测到"
    fv = f.get("version") or "版本未探测到"
    return "whisper %s + ffmpeg %s" % (wv, fv)


# --------------------------------------------------------------------------- #
# 输入检查：只读，视频显式拒收（红线 2）
# --------------------------------------------------------------------------- #
def _basic_check(raw: str) -> dict:
    base = {"ok": False, "status": STATUS_FAILED, "format": "", "path": "",
            "size": 0, "error": ""}
    text = str(raw or "").strip()
    if not text:
        base["error"] = "输入路径为空"
        return base
    p = Path(text)
    ext = p.suffix.lower()
    base["format"] = ext
    # 关键：只认注册表里的 MEDIA_AUDIO，绝不沿用 app.py 的
    # _STAGE3_AUDIO_EXT（那是 MEDIA_EXT 并集，含全部视频后缀）。
    # 分类先于存在性判断：视频文件无论是否存在都必须显式拒收（红线 2）。
    if format_registry.media_kind(ext) == "video":
        base["status"] = STATUS_UNSUPPORTED
        base["error"] = ("失败：%s 是视频文件，须由 S4 独立 video handler 处理，"
                         "不复用音频转写路径（红线 2）" % ext)
        return base
    if ext not in format_registry.MEDIA_AUDIO:
        base["status"] = STATUS_UNSUPPORTED
        base["error"] = "失败：不支持的输入格式 %s（S3 只处理音频）" % (ext or "无后缀")
        return base
    if not p.is_file():
        base["error"] = "文件不存在或不是普通文件：%s" % p.name
        return base
    try:
        size = p.stat().st_size
    except OSError as exc:
        base["error"] = "失败：读取文件信息失败：%s" % exc
        return base
    base["size"] = size
    if size <= 0:
        base["error"] = "失败：音频文件为空"
        return base
    if size > MAX_BYTES:
        base["error"] = "失败：文件超过 %d MB 上限" % (MAX_BYTES // (1024 * 1024))
        return base
    base["ok"] = True
    base["status"] = STATUS_OK
    base["path"] = str(p)
    return base


def inspect(inputs, refresh: bool = False) -> dict:
    """只读预检：逐文件给出可处理性判断，不写任何文件、不创建目录。"""
    cap = capability(refresh=refresh)
    items = []
    for raw in list(inputs or []):
        base = _basic_check(str(raw))
        entry = {"input": str(raw), "name": Path(str(raw)).name,
                 "status": base["status"], "ok": base["ok"],
                 "format": base["format"], "error": base["error"],
                 "size": base["size"]}
        if base["ok"] and not cap["enabled"]:
            entry["status"] = STATUS_UNAVAILABLE
            entry["ok"] = False
            entry["error"] = cap["reason"]
        items.append(entry)
    return {
        "ok": True, "capability": "audio_inspect",
        "items": items, "total": len(items),
        "ready": sum(1 for e in items if e["ok"]),
        "enabled": cap["enabled"],
        "missing": cap["missing"],
        "note": "只读预检；视频文件由 S4 独立处理，不落入音频路径",
    }


# --------------------------------------------------------------------------- #
# 时间戳与 whisper JSON 解析
# --------------------------------------------------------------------------- #
def format_timestamp(seconds) -> str:
    """浮点秒 → ``HH:MM:SS.mmm``，与契约 §4.2 示例逐字一致。"""
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return "00:00:00.000"
    if not math.isfinite(value) or value < 0:
        return "00:00:00.000"
    ms = int(round(value * 1000))
    hours, ms = divmod(ms, 3600000)
    minutes, ms = divmod(ms, 60000)
    secs, ms = divmod(ms, 1000)
    return "%02d:%02d:%02d.%03d" % (hours, minutes, secs, ms)


def _valid_pair(start, end) -> bool:
    try:
        s = float(start)
        e = float(end)
    except (TypeError, ValueError):
        return False
    if not (math.isfinite(s) and math.isfinite(e)):
        return False
    return 0 <= s <= e <= 99 * 3600


def parse_segments(payload) -> tuple[list[dict], dict]:
    """解析 whisper 的 JSON 输出；非法分段丢弃并计数，绝不编造时间戳。

    只接受 ``segments`` 列表里的 ``start/end/text``；``text`` 为空、时间
    为 NaN / 负值 / ``end < start`` / 超 99 小时的分段一律跳过。
    """
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        raise ValueError("转写结果不是 JSON 对象")
    raw = payload.get("segments")
    if not isinstance(raw, list):
        raise ValueError("转写结果缺少 segments 列表")
    if len(raw) > MAX_SEGMENTS:
        raise ValueError("分段数超过 %d 上限" % MAX_SEGMENTS)
    segments: list[dict] = []
    skipped = 0
    for item in raw:
        if not isinstance(item, dict):
            skipped += 1
            continue
        if not _valid_pair(item.get("start"), item.get("end")):
            skipped += 1
            continue
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            skipped += 1
            continue
        segments.append({
            "start": float(item["start"]),
            "end": float(item["end"]),
            "text": " ".join(text.split()),
        })
    language = payload.get("language")
    return segments, {
        "language": language if isinstance(language, str) else "",
        "skipped": skipped,
        "raw_text": payload.get("text") if isinstance(payload.get("text"), str) else "",
    }


# --------------------------------------------------------------------------- #
# 外部工具调用：Popen + 进程登记 + 超时 + 取消 + 进程树终止
# --------------------------------------------------------------------------- #
def _spawn_kwargs() -> dict:
    flags = _CREATE_NO_WINDOW
    if os.name == "nt" and _CREATE_NEW_GROUP:
        flags |= _CREATE_NEW_GROUP
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    kwargs = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",   # 仅用于诊断输出；正文一律从 json 文件严格读
        "env": env,
    }
    if flags:
        kwargs["creationflags"] = flags
    if os.name != "nt":
        # 让外部工具自成进程组：POSIX 的 killpg 才不会误杀精核自己。
        kwargs["start_new_session"] = True
    return kwargs


def _spawn(argv: list[str], *, timeout: float, job=None, runner=None) -> dict:
    """起一个外部工具进程；``runner`` 仅用于契约测试的 mock 后端注入。"""
    if runner is not None:
        result = runner(list(argv))
        return {
            "returncode": int(result.get("returncode", -1)),
            "stdout": str(result.get("stdout") or ""),
            "stderr": str(result.get("stderr") or ""),
            "timed_out": bool(result.get("timed_out")),
            "error": str(result.get("error") or ""),
            "proc": None,
        }
    try:
        proc = subprocess.Popen(list(map(str, argv)), **_spawn_kwargs())
    except (OSError, ValueError) as exc:
        return {"returncode": -1, "stdout": "", "stderr": str(exc),
                "timed_out": False, "error": "启动外部工具失败：%s" % exc,
                "proc": None}
    if job is not None and hasattr(job, "register_child"):
        job.register_child(proc)
    timed_out = False
    try:
        out, err = proc.communicate(timeout=max(1.0, float(timeout)))
    except subprocess.TimeoutExpired:
        timed_out = True
        media_tools.terminate_process_tree(proc)
        try:
            proc.kill()
        except Exception:
            pass
        try:
            out, err = proc.communicate(timeout=5)
        except Exception:
            out, err = "", ""
    except (OSError, ValueError, UnicodeError) as exc:
        media_tools.terminate_process_tree(proc)
        return {"returncode": -1, "stdout": "", "stderr": str(exc),
                "timed_out": False, "error": "外部工具输出读取失败：%s" % exc,
                "proc": proc}
    return {"returncode": proc.returncode, "stdout": out or "",
            "stderr": err or "", "timed_out": timed_out, "error": "",
            "proc": proc}


def _ffmpeg_metadata(src: Path, cap: dict, *, job=None, runner=None) -> dict:
    """只读探测容器时长 / 音频流；失败不阻断转写，元数据明确写「未探测到」。"""
    tool = cap["tools"]["ffmpeg"]
    argv = [tool.get("path") or "ffmpeg", "-hide_banner", "-i", str(src)]
    res = _spawn(argv, timeout=FFMPEG_PROBE_TIMEOUT, job=job, runner=runner)
    text = (res["stdout"] or "") + "\n" + (res["stderr"] or "")
    m = _DURATION_RE.search(text)
    duration = ""
    if m:
        duration = "%s:%s:%s" % (m.group(1), m.group(2),
                                 ("%.2f" % float(m.group(3))).zfill(5))
    a = _AUDIO_STREAM_RE.search(text)
    return {"duration": duration, "stream": (a.group(1).strip() if a else ""),
            "probe_ok": bool(duration or a)}


def _whisper_argv(src: Path, tmp: Path, cap: dict, model: str,
                  language: str = "") -> list[str]:
    tool = cap["tools"]["whisper"]
    argv = [tool.get("path") or "whisper", str(src),
            "--model", model, "--task", "transcribe",
            "--output_format", "json", "--output_dir", str(tmp),
            "--verbose", "False"]
    if language:
        argv += ["--language", language]
    return argv


def _find_result_json(tmp: Path, src: Path) -> Path | None:
    """只认 whisper 写出的 json 文件；同名优先，否则要求恰好一个。"""
    named = tmp / (src.stem + ".json")
    if named.is_file():
        return named
    candidates = sorted(tmp.glob("*.json"))
    return candidates[0] if len(candidates) == 1 else None


def _is_cancelled(job, cancel_check=None) -> bool:
    if cancel_check is not None:
        try:
            return bool(cancel_check())
        except Exception:
            return True
    if job is None:
        return False
    return bool(getattr(job, "cancelled", False) or getattr(job, "timed_out", False))


def _emit(job, text: str, progress: float | None = None) -> None:
    if job is None or not hasattr(job, "add"):
        return
    job.add("log", text, progress=progress)


# --------------------------------------------------------------------------- #
# 产物渲染
# --------------------------------------------------------------------------- #
def _render_md(src: Path, ext: str, segments: list[dict], meta: dict,
               converter: str) -> tuple[str, str]:
    info = media_runtime.source_info(src)
    doc_id = info["doc_id"]
    comment = media_runtime.source_comment(
        src, ext, converter, anchors=["block", "time"])
    lines = [comment, "", "# %s · 音频转写" % src.stem, "",
             "## 文档信息", "",
             "- 源文件：%s" % src.name,
             "- 格式：%s" % ext,
             "- 大小：%d 字节" % info["size"],
             "- 容器时长：%s" % (meta.get("duration") or "未探测到"),
             "- 音频流：%s" % (meta.get("stream") or "未探测到"),
             "- 识别语言：%s" % (meta.get("language") or "未标注"),
             "- 语音分段：%d" % len(segments),
             "- 生成时间：%s" % time.strftime("%Y-%m-%d %H:%M:%S"),
             "",
             "> 本文件由本机 whisper CLI 的音轨转写生成，仅处理音频；"
             "视频内容须由 S4 独立 handler 处理（红线 2）。",
             "", "## 音轨转写", ""]
    for idx, seg in enumerate(segments, 1):
        start = format_timestamp(seg["start"])
        end = format_timestamp(seg["end"])
        lines.append(media_runtime.block_anchor(
            doc_id, idx, time="%s-%s" % (start, end)))
        lines.append("[%s → %s] %s" % (start, end, seg["text"]))
        lines.append("")
    lines += ["## 转写元数据", "",
              "- 转换器：%s" % converter,
              "- 适配器：%s" % ADAPTER_LABEL,
              "- 模型：%s（由本机 whisper 提供，软件不下载 / 不打包）" % meta.get("model", ""),
              "- whisper 版本：%s" % (meta.get("whisper_version") or "版本未探测到"),
              "- ffmpeg 版本：%s" % (meta.get("ffmpeg_version") or "版本未探测到"),
              "- 容器时长探测：%s" % ("成功" if meta.get("probe_ok") else "未探测到（不影响转写正文）"),
              "- 丢弃的非法分段：%d" % int(meta.get("skipped") or 0),
              "- 转写耗时：%.2f 秒" % float(meta.get("elapsed") or 0),
              "- 源文件 sha256：%s" % info["sha256"],
              "- doc_id：%s" % doc_id,
              "- 产物区：out/derived/（不参与阶段 1 件数对账）",
              ""]
    return "\n".join(lines), doc_id


# --------------------------------------------------------------------------- #
# provenance：读旧 + 追加，绝不覆盖 S2a / S2b 历史条目
# --------------------------------------------------------------------------- #
def _merge_provenance(outdir: Path, new_entries: list) -> list:
    old = media_runtime.read_provenance(outdir)
    prior = old.get("entries") if isinstance(old, dict) else None
    entries = list(prior) if isinstance(prior, list) else []
    entries.extend(new_entries)
    return entries


def _entry(record: dict, cap: dict, **extra) -> dict:
    item = {
        "capability": "audio_transcribe",
        "name": record["name"], "format": record["format"],
        "status": record["status"], "reason": record["error"],
        "converter": record.get("converter", ""),
        "tool": {"name": "whisper",
                 "version": cap["tools"]["whisper"].get("version", "")},
    }
    item.update(extra)
    return item


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #
def transcribe(inputs, outdir, *, job=None, refresh: bool = False,
               runner=None, timeout: float = DEFAULT_TIMEOUT,
               model: str = DEFAULT_MODEL, language: str = "",
               cancel_check=None) -> dict:
    """把选中的**音频**文件转成带时间戳的独立 ``.md``。

    ``runner`` 是契约测试的 mock 后端注入点（生产路径永远为 ``None``）；
    ``job`` 复用 S1 的 ``Job``（``register_child`` / ``add`` / ``cancelled``）。
    """
    out_root = Path(str(outdir or "")).expanduser()
    if not str(outdir or "").strip():
        return {"ok": False, "error": "请先指定输出目录（本次提取的输出路径）"}
    if out_root.exists() and not out_root.is_dir():
        return {"ok": False, "error": "输出路径不是目录：%s" % out_root}
    raw_inputs = list(inputs or [])
    if not raw_inputs:
        return {"ok": False, "error": "请先选择音频文件", "results": [],
                "success": 0, "failed": 0, "total": 0}
    if len(raw_inputs) > MAX_INPUTS:
        return {"ok": False, "error": "单批次最多 %d 个音频文件" % MAX_INPUTS}

    cap = capability(refresh=refresh)
    if not cap["enabled"]:
        # 能力级不可用：不遍历、不创建 derived/、不写 provenance，
        # 只在 results 与运行日志（由 app.py 落）里诚实回显。
        results = []
        for raw in raw_inputs:
            base = _basic_check(str(raw))
            # 格式 / 红线判定的优先级高于「工具未装」：视频必须明确拒收，
            # 不能被笼统的「未启用」盖掉（红线 2 的可观察性）。
            status = STATUS_UNAVAILABLE if base["ok"] else base["status"]
            error = cap["reason"] if base["ok"] else base["error"]
            results.append({
                "input": str(raw), "name": Path(str(raw)).name,
                "format": base["format"], "status": status,
                "ok": False, "error": error, "path": "", "doc_id": "",
                "converter": "",
            })
        return {
            "ok": False, "capability": "unavailable",
            "error": "未启用：本机未找到 %s，请安装后重试；本次零产物"
                     % " / ".join(cap["missing"]),
            "results": results, "success": 0, "failed": len(results),
            "total": len(results), "missing": cap["missing"],
            "derived_dir": str(media_runtime.derived_dir(out_root)),
            "provenance": "", "frozen_unchanged": True,
        }

    before = media_runtime.frozen_snapshot(out_root)
    converter = _converter(cap)
    results: list[dict] = []
    entries: list[dict] = []
    written: list[str] = []
    total = len(raw_inputs)

    for idx, raw in enumerate(raw_inputs, 1):
        base = _basic_check(str(raw))
        record = {
            "input": str(raw), "name": Path(str(raw)).name,
            "format": base["format"], "status": base["status"],
            "ok": False, "error": base["error"], "converter": converter,
            "path": "", "doc_id": "",
        }
        if _is_cancelled(job, cancel_check):
            record["status"] = STATUS_CANCELLED
            record["error"] = "任务已取消，未处理该文件"
            results.append(record)
            entries.append(_entry(record, cap))
            continue
        if not base["ok"]:
            results.append(record)
            entries.append(_entry(record, cap))
            continue

        src = Path(base["path"])
        _emit(job, "正在转写 %s（%d/%d）" % (src.name, idx, total),
              progress=(idx - 1) / total)
        if job is not None:
            job.current = idx
            job.current_name = src.name
            job.total = total
        tmp = _new_temp()
        started = time.time()
        try:
            argv = _whisper_argv(src, tmp, cap, model or DEFAULT_MODEL, language)
            res = _spawn(argv, timeout=timeout, job=job, runner=runner)
            if _is_cancelled(job, cancel_check):
                record["status"] = STATUS_CANCELLED
                record["error"] = "任务已取消，未产出 md"
                results.append(record)
                entries.append(_entry(record, cap))
                continue
            if res["timed_out"]:
                record["status"] = STATUS_FAILED
                record["error"] = "失败：转写超时（%.0fs），已终止外部工具进程" % timeout
                results.append(record)
                entries.append(_entry(record, cap))
                continue
            if res["error"] or res["returncode"] != 0:
                detail = res["error"] or (res["stderr"] or "").strip()[:300]
                record["status"] = STATUS_FAILED
                record["error"] = ("失败：whisper 退出码 %s；%s"
                                   % (res["returncode"], detail or "无错误输出"))
                results.append(record)
                entries.append(_entry(record, cap))
                continue

            json_path = _find_result_json(tmp, src)
            if json_path is None:
                record["status"] = STATUS_FAILED
                record["error"] = "失败：whisper 未产出唯一的 JSON 结果文件，拒绝猜测正文"
                results.append(record)
                entries.append(_entry(record, cap))
                continue
            try:
                payload = json.loads(json_path.read_text(encoding="utf-8"))
                segments, parsed_meta = parse_segments(payload)
            except (OSError, UnicodeError, ValueError, TypeError) as exc:
                record["status"] = STATUS_FAILED
                record["error"] = "失败：转写结果解析失败：%s" % exc
                results.append(record)
                entries.append(_entry(record, cap))
                continue
            if not segments:
                record["status"] = (STATUS_NO_SPEECH
                                    if not parsed_meta["raw_text"].strip()
                                    else STATUS_FAILED)
                record["error"] = ("失败：未识别到带时间戳的语音分段，"
                                   "拒绝写空 md / 伪转写")
                results.append(record)
                entries.append(_entry(record, cap, segments=0))
                continue

            probe = _ffmpeg_metadata(src, cap, job=job, runner=runner)
            meta = {
                "duration": probe["duration"], "stream": probe["stream"],
                "probe_ok": probe["probe_ok"],
                "language": parsed_meta["language"],
                "skipped": parsed_meta["skipped"],
                "model": model or DEFAULT_MODEL,
                "whisper_version": cap["tools"]["whisper"].get("version", ""),
                "ffmpeg_version": cap["tools"]["ffmpeg"].get("version", ""),
                "elapsed": time.time() - started,
            }
            try:
                text, doc_id = _render_md(src, base["format"], segments,
                                          meta, converter)
                target = media_runtime.ensure_derived(out_root) / (doc_id + ".md")
                part = target.with_name(target.name + ".part")
                part.write_text(text, encoding="utf-8")
                part.replace(target)
            except (OSError, ValueError) as exc:
                record["status"] = STATUS_FAILED
                record["error"] = "失败：写入 derived 产物失败：%s" % exc
                results.append(record)
                entries.append(_entry(record, cap))
                continue

            record.update({"ok": True, "status": STATUS_OK, "error": "",
                           "path": str(target), "doc_id": doc_id,
                           "segments": len(segments),
                           "skipped": parsed_meta["skipped"],
                           "language": parsed_meta["language"],
                           "duration": probe["duration"]})
            results.append(record)
            written.append(str(target))
            entries.append(_entry(record, cap, path=str(target),
                                 doc_id=doc_id, segments=len(segments),
                                 skipped=parsed_meta["skipped"],
                                 elapsed=meta["elapsed"],
                                 model=meta["model"]))
            _emit(job, "已生成 %s（%d 个分段）" % (target.name, len(segments)),
                  progress=idx / total)
        finally:
            _drop_temp(tmp)

    success = len(written)
    failed = len(results) - success
    try:
        merged = _merge_provenance(out_root, entries)
        prov = media_runtime.write_provenance(out_root, entries=merged)
        prov_path = str(prov)
    except (OSError, ValueError):
        prov_path = ""
    unchanged = media_runtime.frozen_unchanged(before, out_root)
    cancelled = _is_cancelled(job, cancel_check)
    payload = {
        "ok": success > 0 and not cancelled,
        "capability": "available",
        "results": results, "success": success, "failed": failed,
        "total": len(results),
        "derived_dir": str(media_runtime.derived_dir(out_root)),
        "provenance": prov_path,
        "frozen_unchanged": unchanged,
        "path": written[0] if written else "",
        "cancelled": cancelled,
        "converter": converter,
        "tool": {"name": "whisper",
                 "version": cap["tools"]["whisper"].get("version", "")},
    }
    if cancelled:
        payload["error"] = "任务已取消，状态收敛为 cancelled"
    elif success == 0:
        payload["error"] = "本次没有可生成的转写产物；逐条原因见 results"
    elif failed:
        payload["warning"] = "共 %d 项未处理，逐条原因见 results" % failed
    return payload
