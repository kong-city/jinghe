#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精核 · S4 视频 → .md（独立 video handler，绝不复用音频路径）。

**红线 2（SPEC.md / 契约 §1）**：视频绝不能被当成音频转写。本模块与
``audio_transcribe.py`` 是两条互不相交的链路：

* 本模块**不 import** ``audio_transcribe``，也不调用它的任何函数；
* 音频 handler 只认 ``format_registry.MEDIA_AUDIO``，本模块只认
  ``MEDIA_VIDEO``，两边都在「存在性 / 工具检查」之前先做分类拒收；
* 视频产物必须**三区块齐备**（元数据 / 音轨转写 / 画面·字幕），
  只有音轨转写的产物视为不合格。

零第三方依赖：ffmpeg 负责只读流探测、音轨抽取、内嵌字幕轨导出；
本机 whisper CLI 负责抽出音轨的转写。软件**不打包 / 不下载 / 不安装**
任何工具或模型，也不提供 OCR / 视觉模型 —— 因此「画面 / 字幕」区块
只写两类可验证事实：① 从视频里真实导出的内嵌字幕条目；
② 只读探测到的画面流元数据（分辨率 / 帧率 / 编码 / 时长）。
**绝不编造画面语义描述**（「画面显示…」「可以看到…」一律不写）；
探测不到字幕轨时写「未检测到内嵌字幕轨」，不写占位正文冒充内容。

产物只落 ``out/derived/<doc_id>.md`` + ``provenance_media.json``（读旧追加），
绝不写 ``out/md/*.md`` / ``INDEX.md`` / ``MERGED.md`` / ``provenance.json``。
"""
from __future__ import annotations

import atexit
import json
import math
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

import format_registry
import media_runtime
import media_tools

# --------------------------------------------------------------------------- #
# 常量与状态
# --------------------------------------------------------------------------- #
MAX_BYTES = 2 * 1024 * 1024 * 1024    # 单个视频上限 2 GB
MAX_SEGMENTS = 20000                   # 音轨分段上限
MAX_SUBTITLES = 20000                  # 字幕条目上限
MAX_INPUTS = 20                        # 单批次视频数上限
MAX_TEXT_CHARS = 4000                  # 单条文本上限，防畸形输出撑爆 md
DEFAULT_TIMEOUT = 1800.0               # 单文件处理超时（秒）
DEFAULT_MODEL = "base"                 # 模型由本机 whisper 自行准备
FFMPEG_PROBE_TIMEOUT = 20.0
FFMPEG_EXTRACT_TIMEOUT = 600.0
ADAPTER_LABEL = "精核 S4 视频结构化适配器 v1（标准库调度，独立 handler）"
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_CREATE_NEW_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

_DURATION_RE = re.compile(r"Duration:\s*(\d{2}):(\d{2}):(\d{2}\.\d+)")
_VIDEO_STREAM_RE = re.compile(r"Stream\s+#\d+:\d+.*?Video:\s*([^\r\n]+)", re.I)
_AUDIO_STREAM_RE = re.compile(r"Stream\s+#\d+:\d+.*?Audio:\s*([^\r\n]+)", re.I)
_SUBTITLE_STREAM_RE = re.compile(r"Stream\s+#\d+:\d+.*?Subtitle:\s*([^\r\n]+)", re.I)
_RESOLUTION_RE = re.compile(r"\b(\d{2,5})x(\d{2,5})\b")
_FPS_RE = re.compile(r"\b([0-9]+(?:\.[0-9]+)?)\s*fps\b", re.I)
_SRT_TIME_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*"
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{1,3})")

STATUS_OK = "成功"
STATUS_UNSUPPORTED = "不支持"
STATUS_UNAVAILABLE = "未启用"
STATUS_NO_CONTENT = "无有效内容"
STATUS_FAILED = "失败"
STATUS_CANCELLED = "已取消"

# 临时目录三链：进程内登记 / finally 清理 / atexit + 启动孤儿清扫。
# 前缀刻意与阶段 1 jinghe-run- 和 S3 jinghe-run-audio- 隔离，避免误删。
_TEMP_PREFIX = "jinghe-run-video-"
_TEMPS: set[Path] = set()
_TEMPS_LOCK = threading.Lock()
_ORPHAN_MAX_AGE = 24 * 3600.0
_TEMP_SEQ = 0


def _register_temp(path: Path) -> None:
    with _TEMPS_LOCK:
        _TEMPS.add(path)


def _drop_temp(path: Path) -> None:
    with _TEMPS_LOCK:
        _TEMPS.discard(path)
    shutil.rmtree(str(path), ignore_errors=True)


def _cleanup_all_temps() -> None:
    with _TEMPS_LOCK:
        pending = list(_TEMPS)
    for path in pending:
        shutil.rmtree(str(path), ignore_errors=True)


def sweep_orphan_temps() -> int:
    """启动清扫：只删本模块前缀且超龄的临时目录，绝不碰其它前缀。"""
    import tempfile
    base = Path(tempfile.gettempdir())
    removed = 0
    try:
        candidates = list(base.glob(_TEMP_PREFIX + "*"))
    except OSError:
        return 0
    now = time.time()
    for path in candidates:
        try:
            if not path.is_dir() or now - path.stat().st_mtime < _ORPHAN_MAX_AGE:
                continue
            shutil.rmtree(str(path), ignore_errors=True)
            removed += 1
        except OSError:
            continue
    return removed


def _new_temp() -> Path:
    global _TEMP_SEQ
    import tempfile
    with _TEMPS_LOCK:
        _TEMP_SEQ += 1
        seq = _TEMP_SEQ
    path = Path(tempfile.mkdtemp(prefix="%s%d-%d-" % (_TEMP_PREFIX, os.getpid(), seq)))
    _register_temp(path)
    return path


atexit.register(_cleanup_all_temps)


# --------------------------------------------------------------------------- #
# 能力探测：顶层增量字段 video_transcribe，绝不改 S1 占位清单
# --------------------------------------------------------------------------- #
def capability(refresh: bool = False) -> dict:
    """``/api/tools/probe`` 的顶层增量字段 ``video_transcribe``。

    ``media_tools.capabilities()`` 被 ``test_33`` 锁死为 S1 占位清单；
    ``media_ready()`` 恒 False，**不得**当本能力的就绪判据。
    whisper 负责音轨转写、ffmpeg 负责流探测 / 抽轨 / 字幕导出，两者都在
    才算启用；缺一即诚实显示「未启用」，不降级成「只有音轨」的半成品。
    """
    tools = media_tools.probe_all(refresh=refresh)
    whisper = dict(tools.get("whisper") or {})
    ffmpeg = dict(tools.get("ffmpeg") or {})
    missing = [name for name, tool in (("whisper", whisper), ("ffmpeg", ffmpeg))
               if not tool.get("available")]
    enabled = not missing
    return {
        "name": "video_transcribe",
        "enabled": enabled,
        "capability": "available" if enabled else "unavailable",
        "engine": {
            "name": "本机 whisper CLI + ffmpeg（未随软件分发）",
            "reason": ("ffmpeg 只读探测流信息 / 抽取音轨 / 导出内嵌字幕轨，"
                       "whisper 转写抽出的音轨；软件不提供 OCR / 视觉模型、"
                       "不下载模型、不打包工具、不自动安装"),
        },
        # ffprobe 只是可选增强：绝不并入 media_tools.TOOL_SPECS（test_40
        # 硬锁 probe["tools"] 恰好 3 个工具），探不到就回退 ffmpeg -i 文本解析。
        "tools": {"whisper": whisper, "ffmpeg": ffmpeg,
                  "ffprobe": _locate_ffprobe(ffmpeg.get("path", ""),
                                             refresh=refresh)},
        "missing": missing,
        "reason": ("可用" if enabled else
                   "未启用：本机未找到 %s，请安装后重试"
                   % " / ".join(missing)),
        "input": {"exts": sorted(format_registry.MEDIA_VIDEO),
                  "max_bytes": MAX_BYTES, "max_inputs": MAX_INPUTS},
        "output": {"dirname": media_runtime.DERIVED_DIRNAME, "suffix": ".md",
                   "sections": ["元数据", "音轨转写", "画面 / 字幕"]},
        "note": ("只处理视频文件；音频由 S3 独立 handler 处理。"
                 "画面/字幕区块只写真实导出字幕与只读流元数据，绝不编造画面描述"),
    }


def _converter(cap: dict) -> str:
    """8 字段 src 的 converter：只写真实工具名 + 探测到的版本。"""
    w = cap["tools"]["whisper"]
    f = cap["tools"]["ffmpeg"]
    fp = cap["tools"].get("ffprobe") or {}
    parts = ["whisper %s" % (w.get("version") or "版本未探测到"),
             "ffmpeg %s" % (f.get("version") or "版本未探测到")]
    if fp.get("available") and fp.get("version"):
        parts.append("ffprobe %s" % fp["version"])
    return " + ".join(parts)


# --------------------------------------------------------------------------- #
# 输入检查：双向红线，分类先于存在性与工具检查
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
    # 音频必须明确拒收：S4 不复用音频路径，也不允许音频反向流入视频 handler。
    if format_registry.media_kind(ext) == "audio":
        base["status"] = STATUS_UNSUPPORTED
        base["error"] = ("失败：%s 是音频文件，须由 S3 独立音频 handler 处理，"
                         "不复用视频路径（红线 2）" % ext)
        return base
    if ext not in format_registry.MEDIA_VIDEO:
        base["status"] = STATUS_UNSUPPORTED
        base["error"] = "失败：不支持的输入格式 %s（S4 只处理视频）" % (ext or "无后缀")
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
        base["error"] = "失败：视频文件为空"
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
        "ok": True, "capability": "video_inspect",
        "items": items, "total": len(items),
        "ready": sum(1 for e in items if e["ok"]),
        "enabled": cap["enabled"], "missing": cap["missing"],
        "note": "只读预检；音频文件由 S3 独立处理，不落入视频路径",
    }


# --------------------------------------------------------------------------- #
# 时间戳 / whisper JSON / SRT 解析
# --------------------------------------------------------------------------- #
def format_timestamp(seconds) -> str:
    """秒(float) → ``HH:MM:SS.mmm``；非法值归零，绝不编造时间。"""
    try:
        val = float(seconds)
    except (TypeError, ValueError):
        return "00:00:00.000"
    if not math.isfinite(val) or val < 0 or val > 99 * 3600:
        return "00:00:00.000"
    total_ms = int(round(val * 1000))
    hh, rem = divmod(total_ms, 3600000)
    mm, rem = divmod(rem, 60000)
    ss, ms = divmod(rem, 1000)
    return "%02d:%02d:%02d.%03d" % (hh, mm, ss, ms)


def _valid_pair(start, end) -> bool:
    try:
        s, e = float(start), float(end)
    except (TypeError, ValueError):
        return False
    if not (math.isfinite(s) and math.isfinite(e)):
        return False
    return 0 <= s <= e <= 99 * 3600


def parse_segments(payload) -> tuple[list[dict], dict]:
    """whisper JSON → 合法分段；空 / 非法一律不产正文。"""
    out: list[dict] = []
    meta = {"language": "", "raw_text": "", "skipped": 0}
    if not isinstance(payload, dict):
        return out, meta
    lang = payload.get("language")
    meta["language"] = str(lang).strip() if isinstance(lang, (str, int, float)) else ""
    text = payload.get("text")
    meta["raw_text"] = str(text) if isinstance(text, str) else ""
    raw = payload.get("segments")
    if not isinstance(raw, list):
        return out, meta
    for item in raw[:MAX_SEGMENTS]:
        if not isinstance(item, dict) or not _valid_pair(item.get("start"), item.get("end")):
            meta["skipped"] += 1
            continue
        body = item.get("text")
        if not isinstance(body, str) or not body.strip():
            meta["skipped"] += 1
            continue
        out.append({"start": float(item["start"]), "end": float(item["end"]),
                    "text": body.strip()[:MAX_TEXT_CHARS]})
    if len(raw) > MAX_SEGMENTS:
        meta["skipped"] += len(raw) - MAX_SEGMENTS
    return out, meta


def parse_srt(text: str) -> list[dict]:
    """SRT → [{start, end, text}]；逗号毫秒与 BOM 一并归一化。

    只认真实解析出的条目；任意解析失败返回空，调用方据此诚实降级，
    **绝不把解析失败包装成「无字幕」占位正文**。
    """
    if not isinstance(text, str) or not text.strip():
        return []
    body = text.lstrip("\ufeff")
    out: list[dict] = []
    for block in re.split(r"\r?\n\s*\r?\n", body):
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        # 允许省略序号；找第一条含 --> 的时间轴
        timeline = next((ln for ln in lines if "-->" in ln), "")
        m = _SRT_TIME_RE.search(timeline)
        if not m:
            continue
        g = m.groups()
        start = (int(g[0]) * 3600 + int(g[1]) * 60 + int(g[2])
                 + int(g[3].ljust(3, "0")) / 1000.0)
        end = (int(g[4]) * 3600 + int(g[5]) * 60 + int(g[6])
               + int(g[7].ljust(3, "0")) / 1000.0)
        idx = lines.index(timeline)
        content = " ".join(lines[idx + 1:]).strip()
        if not _valid_pair(start, end) or not content:
            continue
        # 去掉 SRT 内联标签，但保留文字本身（不改写语义）
        content = re.sub(r"<[^>]+>", "", content).strip()
        if content:
            out.append({"start": start, "end": end,
                        "text": content[:MAX_TEXT_CHARS]})
        if len(out) >= MAX_SUBTITLES:
            break
    return out


# --------------------------------------------------------------------------- #
# 外部工具调度（与 S3 同形，但完全独立，不 import 音频模块）
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
        "stdout": subprocess.PIPE, "stderr": subprocess.PIPE,
        "text": True, "encoding": "utf-8",
        "errors": "replace",   # 仅诊断输出；正文一律从 json / srt 文件严格读
        "env": env,
    }
    if flags:
        kwargs["creationflags"] = flags
    if os.name != "nt":
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


def _ffmpeg_argv(cap: dict, args: list[str]) -> list[str]:
    return [cap["tools"]["ffmpeg"].get("path") or "ffmpeg",
            "-hide_banner", "-nostdin"] + args


# ffprobe 只在 S4 自有 tools 子结构里探测；TOOL_SPECS / probe["tools"]
# 被 test_40 锁死为 {ffmpeg, whisper, yt-dlp}，绝不改写。
_FFPROBE_LOCK = threading.Lock()
_FFPROBE_CACHE: dict | None = None


def _locate_ffprobe(ffmpeg_path: str, refresh: bool = False) -> dict:
    """可选工具：优先 ffmpeg 同目录，其次 PATH；探不到就走文本解析兜底。"""
    global _FFPROBE_CACHE
    with _FFPROBE_LOCK:
        if _FFPROBE_CACHE is not None and not refresh:
            return dict(_FFPROBE_CACHE)
    candidate = ""
    if ffmpeg_path:
        sibling = Path(ffmpeg_path).with_name(
            "ffprobe" + (".exe" if os.name == "nt" else ""))
        if sibling.is_file():
            candidate = str(sibling)
    if not candidate:
        candidate = shutil.which("ffprobe") or ""
    if not candidate:
        info = {"available": False, "path": "", "version": "",
                "reason": "本机未找到 ffprobe；元数据改用 ffmpeg -i 只读文本解析"}
    else:
        res = _spawn([candidate, "-version"], timeout=8.0)
        m = re.search(r"ffprobe version\s+([^\s]+)",
                      (res["stdout"] or "") + (res["stderr"] or ""))
        ok = res["returncode"] == 0 and not res["error"]
        info = {"available": bool(ok), "path": candidate,
                "version": m.group(1) if m else "",
                "reason": ("可用" if ok else
                           "探测失败；元数据改用 ffmpeg -i 只读文本解析")}
    with _FFPROBE_LOCK:
        _FFPROBE_CACHE = dict(info)
    return info


def _from_ffprobe_json(data) -> dict | None:
    """ffprobe -of json → 统一流视图；解析不出视频流即返回 None 走兜底。"""
    if not isinstance(data, dict):
        return None
    streams = data.get("streams")
    if not isinstance(streams, list) or not streams:
        return None
    pick = lambda kind: [s for s in streams
                         if isinstance(s, dict) and s.get("codec_type") == kind]
    vids, auds, subs = pick("video"), pick("audio"), pick("subtitle")
    if not vids:
        return None
    v = vids[0]
    fps = ""
    rate = str(v.get("r_frame_rate") or v.get("avg_frame_rate") or "")
    if "/" in rate:
        try:
            num, den = rate.split("/", 1)
            if float(den):
                fps = "%.2f" % (float(num) / float(den))
        except (TypeError, ValueError, ZeroDivisionError):
            fps = ""
    width = int(v.get("width") or 0)
    height = int(v.get("height") or 0)
    codec = str(v.get("codec_name") or "video")
    fmt = data.get("format") if isinstance(data.get("format"), dict) else {}
    raw_dur = v.get("duration") or fmt.get("duration") or ""
    duration = ""
    try:
        if raw_dur not in ("", "N/A", None):
            duration = format_timestamp(float(raw_dur))
    except (TypeError, ValueError):
        duration = ""
    if not duration:
        duration = format_timestamp(0)
    vline = "%s, %dx%d%s" % (codec, width, height,
                             (", %s fps" % fps if fps else ""))
    return {
        "duration": duration, "video_stream": vline,
        "audio_stream": (str(auds[0].get("codec_name") or "audio")
                         if auds else ""),
        "subtitle_stream": (str(subs[0].get("codec_name") or "subtitle")
                            if subs else ""),
        "subtitle_count": len(subs),
        "width": width, "height": height, "fps": fps,
        "has_audio": bool(auds), "has_subtitle": bool(subs),
        "probe_ok": True, "metadata_source": "ffprobe JSON",
    }


def probe_streams(src: Path, cap: dict, *, job=None, runner=None) -> dict:
    """只读探测：ffprobe JSON 优先，失败回退 ffmpeg -i 文本解析。"""
    ff = cap.get("tools", {}).get("ffprobe") or {}
    if ff.get("available"):
        argv = [ff.get("path") or "ffprobe", "-v", "error",
                "-show_streams", "-show_format", "-of", "json", str(src)]
        res = _spawn(argv, timeout=FFMPEG_PROBE_TIMEOUT, job=job, runner=runner)
        if (res["returncode"] == 0 and not res["error"]
                and not res["timed_out"]):
            try:
                parsed = _from_ffprobe_json(json.loads(res["stdout"]))
            except (ValueError, TypeError, KeyError):
                parsed = None
            if parsed is not None:
                return parsed
    # 兜底：ffmpeg -i 无输出文件必然非 0 退出，但流信息在 stderr，不看 rc。
    argv = _ffmpeg_argv(cap, ["-i", str(src)])
    res = _spawn(argv, timeout=FFMPEG_PROBE_TIMEOUT, job=job, runner=runner)
    text = (res["stdout"] or "") + "\n" + (res["stderr"] or "")
    m = _DURATION_RE.search(text)
    duration = ""
    if m:
        duration = "%s:%s:%s" % (m.group(1), m.group(2),
                                 ("%.2f" % float(m.group(3))).zfill(5))
    vids = _VIDEO_STREAM_RE.findall(text)
    auds = _AUDIO_STREAM_RE.findall(text)
    subs = _SUBTITLE_STREAM_RE.findall(text)
    vline = vids[0].strip() if vids else ""
    res_m = _RESOLUTION_RE.search(vline)
    fps_m = _FPS_RE.search(vline)
    return {
        "duration": duration, "video_stream": vline,
        "audio_stream": (auds[0].strip() if auds else ""),
        "subtitle_stream": (subs[0].strip() if subs else ""),
        "subtitle_count": len(subs),
        "width": int(res_m.group(1)) if res_m else 0,
        "height": int(res_m.group(2)) if res_m else 0,
        "fps": fps_m.group(1) if fps_m else "",
        "has_audio": bool(auds), "has_subtitle": bool(subs),
        "probe_ok": bool(duration or vline or auds or subs),
        "metadata_source": "ffmpeg -i 文本解析",
    }


def _extract_audio(src: Path, tmp: Path, cap: dict, *, job=None,
                   runner=None) -> tuple[bool, str]:
    """把视频音轨抽成 16k 单声道 wav，供本机 whisper 转写。"""
    wav = tmp / "audio.wav"
    # 显式 -map 0:a:0 避免选错流；-nostdin 避免子进程读 stdin 挂住。
    argv = _ffmpeg_argv(cap, ["-y", "-i", str(src), "-map", "0:a:0",
                              "-vn", "-ac", "1", "-ar", "16000",
                              "-c:a", "pcm_s16le", str(wav)])
    res = _spawn(argv, timeout=FFMPEG_EXTRACT_TIMEOUT, job=job, runner=runner)
    if res["timed_out"] or res["error"] or res["returncode"] != 0:
        return False, (res["error"] or (res["stderr"] or "").strip()[:200]
                       or "ffmpeg 抽轨失败")
    if runner is None and not wav.is_file():
        return False, "ffmpeg 未产出 wav 文件"
    return True, ""


def _extract_subtitles(src: Path, tmp: Path, cap: dict, *, job=None,
                       runner=None) -> tuple[bool, str]:
    """只导出第 0 条内嵌字幕轨为 srt；无字幕轨时根本不调用。"""
    srt = tmp / "subs.srt"
    argv = _ffmpeg_argv(cap, ["-y", "-i", str(src), "-map", "0:s:0",
                              "-c:s", "srt", str(srt)])
    # bitmap 字幕（dvd_sub / dvb_sub）转 srt 必然失败：诚实跳过，绝不 OCR。
    res = _spawn(argv, timeout=FFMPEG_EXTRACT_TIMEOUT, job=job, runner=runner)
    if res["timed_out"] or res["error"] or res["returncode"] != 0:
        return False, (res["error"] or (res["stderr"] or "").strip()[:200]
                       or "ffmpeg 字幕导出失败")
    if runner is None and not srt.is_file():
        return False, "ffmpeg 未产出 srt 文件"
    return True, ""


def _whisper_argv(wav: Path, tmp: Path, cap: dict, model: str,
                  language: str = "") -> list[str]:
    tool = cap["tools"]["whisper"]
    argv = [tool.get("path") or "whisper", str(wav),
            "--model", model, "--task", "transcribe",
            "--output_format", "json", "--output_dir", str(tmp),
            "--verbose", "False"]
    if language:
        argv += ["--language", language]
    return argv


def _find_result_json(tmp: Path, wav: Path) -> Path | None:
    named = tmp / (wav.stem + ".json")
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
# 产物渲染：三区块齐备，画面区块只写可验证事实
# --------------------------------------------------------------------------- #
def _render_md(src: Path, ext: str, segments: list[dict], subtitles: list[dict],
               streams: dict, meta: dict, converter: str) -> tuple[str, str]:
    info = media_runtime.source_info(src)
    doc_id = info["doc_id"]
    comment = media_runtime.source_comment(
        src, ext, converter, anchors=["block", "time"])
    res = ("%d × %d" % (streams["width"], streams["height"])
           if streams["width"] and streams["height"] else "未探测到")
    lines = [comment, "", "# %s · 视频结构化提取" % src.stem, "",
             "## 元数据", "",
             "- 源文件：%s" % src.name,
             "- 格式：%s" % ext,
             "- 大小：%d 字节" % info["size"],
             "- 容器时长：%s" % (streams["duration"] or "未探测到"),
             "- 分辨率：%s" % res,
             "- 帧率：%s" % (streams["fps"] or "未探测到"),
             "- 视频流：%s" % (streams["video_stream"] or "未探测到"),
             "- 音频流：%s" % (streams["audio_stream"] or "未检测到音轨"),
             "- 内嵌字幕轨：%d 条%s" % (
                 streams["subtitle_count"],
                 ("（%s）" % streams["subtitle_stream"]
                  if streams["subtitle_stream"] else "")),
             "- 元数据来源：%s（只读；字幕轨为机械导出，无 OCR / 视觉模型）"
             % streams.get("metadata_source", "ffmpeg -i 文本解析"),
             "- 识别语言：%s" % (meta.get("language") or "未标注"),
             "- 语音分段：%d" % len(segments),
             "- 字幕条目：%d" % len(subtitles),
             "- 生成时间：%s" % time.strftime("%Y-%m-%d %H:%M:%S"),
             "- 转换器：%s" % converter,
             "- 适配器：%s" % ADAPTER_LABEL,
             "- 模型：%s（由本机 whisper 提供，软件不下载 / 不打包）" % meta.get("model", ""),
             "- whisper 版本：%s" % (meta.get("whisper_version") or "版本未探测到"),
             "- ffmpeg 版本：%s" % (meta.get("ffmpeg_version") or "版本未探测到"),
             "- 流信息探测：%s" % ("成功" if streams["probe_ok"] else "未探测到"),
             "- 音轨抽取：%s" % meta.get("audio_extract", "未执行"),
             "- 字幕轨导出：%s" % meta.get("subtitle_extract", "未执行"),
             "- 丢弃的非法分段：%d" % int(meta.get("skipped") or 0),
             "- 处理耗时：%.2f 秒" % float(meta.get("elapsed") or 0),
             "- 源文件 sha256：%s" % info["sha256"],
             "- doc_id：%s" % doc_id,
             "- 产物区：out/derived/（不参与阶段 1 件数对账）",
             "",
             "> 本文件由 S4 独立 video handler 生成；ffmpeg 只读探测与抽轨、"
             "本机 whisper 转写音轨。软件不提供 OCR / 视觉模型，"
             "不生成画面语义描述。",
             "", "## 音轨转写", ""]
    if segments:
        for idx, seg in enumerate(segments, 1):
            start, end = format_timestamp(seg["start"]), format_timestamp(seg["end"])
            lines.append(media_runtime.block_anchor(
                doc_id, idx, time="%s-%s" % (start, end)))
            lines.append("[%s → %s] %s" % (start, end, seg["text"]))
            lines.append("")
    else:
        lines += ["- 未获得可用的带时间戳语音分段：%s"
                  % (meta.get("audio_note") or "未检测到音轨或未识别到语音"),
                  "",
                  "> 本区块不写占位正文；未识别到语音时不伪造转写内容。", ""]
    lines += ["## 画面 / 字幕", ""]
    if subtitles:
        lines += ["- 内嵌字幕轨已导出，共 %d 条（原文，未改写语义）：" % len(subtitles), ""]
        base = len(segments)
        for idx, sub in enumerate(subtitles, 1):
            start, end = format_timestamp(sub["start"]), format_timestamp(sub["end"])
            lines.append(media_runtime.block_anchor(
                doc_id, base + idx, time="%s-%s" % (start, end)))
            lines.append("[%s → %s] %s" % (start, end, sub["text"]))
            lines.append("")
    else:
        lines += ["- 未检测到内嵌字幕轨，或字幕轨导出 / 解析未得到任何条目：%s"
                  % (meta.get("subtitle_note") or "无字幕内容"),
                  "- 本软件不提供 OCR / 视觉模型，**不生成画面语义描述**；"
                  "画面信息仅以上方「元数据」中的只读流参数为准。",
                  "",
                  "> 本区块只陈述可验证事实，不用占位文本冒充画面内容。", ""]
    return "\n".join(lines), doc_id


# --------------------------------------------------------------------------- #
# provenance：读旧 + 追加，绝不覆盖 S2a / S2b / S3 历史条目
# --------------------------------------------------------------------------- #
def _merge_provenance(outdir: Path, new_entries: list) -> list:
    old = media_runtime.read_provenance(outdir)
    prior = old.get("entries") if isinstance(old, dict) else None
    entries = list(prior) if isinstance(prior, list) else []
    entries.extend(new_entries)
    return entries


def _entry(record: dict, cap: dict, **extra) -> dict:
    item = {
        "capability": "video_transcribe",
        "name": record["name"], "format": record["format"],
        "status": record["status"], "reason": record["error"],
        "converter": record.get("converter", ""),
        "tool": {"name": "whisper + ffmpeg",
                 "version": cap["tools"]["ffmpeg"].get("version", "")},
    }
    item.update(extra)
    return item


# --------------------------------------------------------------------------- #
# 主入口（名字刻意不叫 transcribe：避免与 S3 音频路径混淆）
# --------------------------------------------------------------------------- #
def transcribe(inputs, outdir, *, job=None, refresh: bool = False, runner=None,
               timeout: float = DEFAULT_TIMEOUT, model: str = DEFAULT_MODEL,
               language: str = "", cancel_check=None) -> dict:
    """把选中的**视频**文件转成三区块齐备的独立 ``.md``。

    名字与 S3 ``audio_transcribe.transcribe`` 对称，但**实现完全独立**：
    本模块不 import 音频模块、不调用它的任何函数（红线 2）。

    ``runner`` 是契约测试的 mock 后端注入点（生产路径永远为 ``None``）；
    ``job`` 复用 S1 的 ``Job``（``register_child`` / ``add`` / ``cancelled``）。
    三区块齐备是结构要求；此外至少有「真实语音分段」或「真实字幕条目」
    之一，才允许落盘 —— 只有元数据 / 占位说明的视频一律零 md。
    """
    out_root = Path(str(outdir or "")).expanduser()
    if not str(outdir or "").strip():
        return {"ok": False, "error": "请先指定输出目录（本次提取的输出路径）"}
    if out_root.exists() and not out_root.is_dir():
        return {"ok": False, "error": "输出路径不是目录：%s" % out_root}
    raw_inputs = list(inputs or [])
    if not raw_inputs:
        return {"ok": False, "error": "请先选择视频文件", "results": [],
                "success": 0, "failed": 0, "total": 0}
    if len(raw_inputs) > MAX_INPUTS:
        return {"ok": False, "error": "单批次最多 %d 个视频文件" % MAX_INPUTS}

    cap = capability(refresh=refresh)
    if not cap["enabled"]:
        # 能力级不可用：不遍历、不创建 derived/、不写 provenance。
        results = []
        for raw in raw_inputs:
            base = _basic_check(str(raw))
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
        _emit(job, "正在提取 %s（%d/%d）" % (src.name, idx, total),
              progress=(idx - 1) / total)
        if job is not None:
            job.current = idx
            job.current_name = src.name
            job.total = total
        tmp = _new_temp()
        started = time.time()
        try:
            # ① 只读流探测：决定后续抽哪些轨，绝不凭文件名猜。
            streams = probe_streams(src, cap, job=job, runner=runner)
            audio_note = "未检测到音轨" if not streams["has_audio"] else ""
            subtitle_note = ("未检测到内嵌字幕轨"
                             if not streams["has_subtitle"] else "")

            # ② 内嵌字幕轨：只在探测到字幕流时才导出，解析不出条目即诚实留白。
            subtitles: list[dict] = []
            subtitle_extract = "未执行（未检测到字幕轨）"
            if streams["has_subtitle"]:
                ok_s, why_s = _extract_subtitles(src, tmp, cap, job=job,
                                                 runner=runner)
                subtitle_extract = "成功" if ok_s else "失败（%s）" % why_s
                if ok_s:
                    try:
                        subtitles = parse_srt((tmp / "subs.srt").read_text(
                            encoding="utf-8-sig", errors="strict"))
                    except (OSError, UnicodeError, ValueError) as exc:
                        subtitle_note = "字幕文件解析失败：%s" % exc
                    else:
                        if not subtitles:
                            subtitle_note = "字幕轨未解析到任何有效条目"
                else:
                    subtitle_note = "字幕轨导出失败：%s" % why_s
            if _is_cancelled(job, cancel_check):
                record["status"] = STATUS_CANCELLED
                record["error"] = "任务已取消，未产出 md"
                results.append(record)
                entries.append(_entry(record, cap))
                continue

            # ③ 音轨：只在探测到音频流时抽轨 + whisper 转写。
            segments: list[dict] = []
            parsed_meta = {"language": "", "raw_text": "", "skipped": 0}
            audio_extract = "未执行（未检测到音轨）"
            if streams["has_audio"]:
                ok_a, why_a = _extract_audio(src, tmp, cap, job=job,
                                             runner=runner)
                audio_extract = "成功" if ok_a else "失败（%s）" % why_a
                if ok_a:
                    wav = tmp / "audio.wav"
                    argv = _whisper_argv(wav, tmp, cap, model or DEFAULT_MODEL,
                                         language)
                    res = _spawn(argv, timeout=timeout, job=job, runner=runner)
                    if res["timed_out"]:
                        audio_note = "音轨转写超时，已终止外部工具进程"
                    elif res["error"] or res["returncode"] != 0:
                        audio_note = "whisper 失败：%s" % (
                            res["error"] or (res["stderr"] or "").strip()[:200]
                            or "退出码 %s" % res["returncode"])
                    else:
                        json_path = _find_result_json(tmp, wav)
                        if json_path is None:
                            audio_note = "whisper 未产出唯一的 JSON 结果文件"
                        else:
                            try:
                                payload = json.loads(json_path.read_text(
                                    encoding="utf-8"))
                                segments, parsed_meta = parse_segments(payload)
                            except (OSError, UnicodeError, ValueError,
                                    TypeError) as exc:
                                audio_note = "转写结果解析失败：%s" % exc
                            else:
                                if not segments:
                                    audio_note = "未识别到带时间戳的语音分段"
                else:
                    audio_note = "音轨抽取失败：%s" % why_a
            if _is_cancelled(job, cancel_check):
                record["status"] = STATUS_CANCELLED
                record["error"] = "任务已取消，未产出 md"
                results.append(record)
                entries.append(_entry(record, cap))
                continue

            # ④ 元数据门禁：解析不出视频流就不写空壳三区块。
            if not streams["video_stream"]:
                record["status"] = STATUS_NO_CONTENT
                record["error"] = ("失败：未解析到视频流元数据，"
                                   "拒绝写空壳三区块 / 伪产物")
                results.append(record)
                entries.append(_entry(record, cap, segments=0, subtitles=0))
                continue
            # ⑤ 真实内容门禁：只有元数据 / 占位说明一律零 md。
            if not segments and not subtitles:
                record["status"] = STATUS_NO_CONTENT
                record["error"] = ("失败：既无真实语音分段也无真实字幕条目，"
                                   "拒绝写占位 md / 伪内容")
                results.append(record)
                entries.append(_entry(record, cap, segments=0, subtitles=0))
                continue

            meta = {
                "language": parsed_meta["language"],
                "skipped": parsed_meta["skipped"],
                "model": model or DEFAULT_MODEL,
                "whisper_version": cap["tools"]["whisper"].get("version", ""),
                "ffmpeg_version": cap["tools"]["ffmpeg"].get("version", ""),
                "elapsed": time.time() - started,
                "audio_note": audio_note, "subtitle_note": subtitle_note,
                "audio_extract": audio_extract,
                "subtitle_extract": subtitle_extract,
            }
            try:
                text, doc_id = _render_md(src, base["format"], segments,
                                          subtitles, streams, meta, converter)
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
                           "subtitles": len(subtitles),
                           "sections": 3,
                           "has_audio": streams["has_audio"],
                           "has_subtitle_track": streams["has_subtitle"],
                           "skipped": parsed_meta["skipped"],
                           "language": parsed_meta["language"],
                           "duration": streams["duration"]})
            results.append(record)
            written.append(str(target))
            entries.append(_entry(record, cap, path=str(target),
                                 doc_id=doc_id, segments=len(segments),
                                 subtitles=len(subtitles),
                                 elapsed=meta["elapsed"], model=meta["model"]))
            _emit(job, "已生成 %s（%d 段语音 / %d 条字幕）"
                  % (target.name, len(segments), len(subtitles)),
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
        "tool": {"name": "whisper + ffmpeg",
                 "version": cap["tools"]["ffmpeg"].get("version", "")},
    }
    if cancelled:
        payload["error"] = "任务已取消，状态收敛为 cancelled"
    elif success == 0:
        payload["error"] = "本次没有可生成的视频产物；逐条原因见 results"
    elif failed:
        payload["warning"] = "共 %d 项未处理，逐条原因见 results" % failed
    return payload
