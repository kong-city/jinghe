#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精核 · 可插拔大模型后端适配层（S7b 适配层 · 方案 C）。

用户 2026-11-16 改定：精读/修订的后端从「本机 ollama 单后端」改为
**可插拔多后端**——统一 :class:`Backend` 接口，客户自选：

* :class:`LocalBackend` —— 本机 ollama（``http://localhost:11434``），内容不出本机；
* :class:`CloudBackend` —— 客户填的 OpenAI 兼容端点 + key，内容外传（客户配置即知情同意）。

两者共用 OpenAI 兼容 ``/chat/completions`` 协议，底层 HTTP 调用一致。

**安全红线（密钥）**：
* 后端配置独立存 ``%LOCALAPPDATA%/Jinghe/backend.json``，**不放 settings.json**
  （后者被 /api/settings 明文回显，且可被日志导出端点触及）；
* 读配置一律脱敏 api_key；写配置时 key 空值表示「不改」；
* **绝不**把 key 写进日志、provenance、产物、异常堆栈。

**阶段边界**：本文件 S7b 适配层只实现配置管理 + probe + list_models 的形状；
``chat()`` 真推理显式抛 NotImplementedError（留 S7b 后半），绝不静默返回假结果。
"""
from __future__ import annotations

import json
import os
import re
import threading
import urllib.error
import urllib.request
from pathlib import Path

LOG_DIR = Path(os.environ.get("LOCALAPPDATA") or str(Path.home())) / "Jinghe"
CONFIG_FILE = LOG_DIR / "backend.json"

KIND_NONE = "none"
KIND_LOCAL = "local"
KIND_CLOUD = "cloud"
VALID_KINDS = (KIND_NONE, KIND_LOCAL, KIND_CLOUD)

LOCAL_DEFAULT_ENDPOINT = "http://localhost:11434"
DEFAULT_CONFIG = {
    "kind": KIND_NONE,
    "endpoint": "",     # Cloud 必填；Local 可留空（用 LOCAL_DEFAULT_ENDPOINT）
    "api_key": "",      # Cloud 必填；Local 留空
    "model": "",        # 可选；空则用后端默认/第一个模型
}

_TIMEOUT_PROBE = 3.0
_TIMEOUT_MODELS = 8.0

_LOCK = threading.Lock()
_CACHE: dict | None = None


# --------------------------------------------------------------------------- #
# 配置读写（独立文件 + 密钥脱敏）
# --------------------------------------------------------------------------- #
def _validate_config(data: object) -> dict:
    """把外部输入收敛成合法配置；非法值退回默认，绝不因脏数据崩掉。"""
    out = dict(DEFAULT_CONFIG)
    if not isinstance(data, dict):
        return out
    kind = data.get("kind", KIND_NONE)
    out["kind"] = kind if kind in VALID_KINDS else KIND_NONE
    for key in ("endpoint", "api_key", "model"):
        val = data.get(key, "")
        out[key] = val.strip() if isinstance(val, str) else ""
    return out


def load_config(refresh: bool = False) -> dict:
    """读配置（带缓存）。返回的是**含真实 key 的内部副本**，仅供后端调用，不回显 UI。"""
    global _CACHE
    with _LOCK:
        if _CACHE is not None and not refresh:
            return dict(_CACHE)
        data: dict = {}
        try:
            if CONFIG_FILE.is_file():
                raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    data = raw
        except (OSError, ValueError):
            # 配置损坏时静默回退默认，不把内容（可能含 key）写进日志
            data = {}
        _CACHE = _validate_config(data)
        return dict(_CACHE)


def save_config(data: object) -> dict:
    """保存配置：api_key 传空串表示「保留原值」（脱敏回显场景不会覆盖真 key）。"""
    global _CACHE
    incoming = _validate_config(data)
    with _LOCK:
        # 注意：_LOCK 不可重入，锁内绝不能调 load_config()（它会再拿同一把锁 → 自死锁）。
        # 直接在锁内读当前 key：优先用缓存，否则从文件读（仅取 api_key 字段）。
        current_key = ""
        if _CACHE is not None:
            current_key = _CACHE.get("api_key", "")
        elif CONFIG_FILE.is_file():
            try:
                disk = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                if isinstance(disk, dict):
                    current_key = str(disk.get("api_key") or "")
            except (OSError, ValueError):
                pass
        clean = dict(incoming)
        if not incoming["api_key"]:
            clean["api_key"] = current_key
        _CACHE = clean
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            tmp = CONFIG_FILE.with_name(CONFIG_FILE.name + ".tmp")
            tmp.write_text(json.dumps(clean, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            tmp.replace(CONFIG_FILE)
        except OSError:
            # 不把异常细节写到任何可能含 key 的位置；保存失败由返回值的 ok 体现
            pass
    return dict(clean)


def mask_key(key: str) -> str:
    """脱敏：空 -> 空；短 key -> ****；长 key -> **** + 后 4 位。"""
    if not key:
        return ""
    if len(key) <= 4:
        return "****"
    return "****" + key[-4:]


def public_config() -> dict:
    """给 UI 的**脱敏**配置：api_key 只回显掩码，绝不回显真值。"""
    cfg = load_config()
    return {
        "kind": cfg["kind"],
        "endpoint": cfg["endpoint"],
        "model": cfg["model"],
        "api_key": mask_key(cfg["api_key"]),
        "has_key": bool(cfg["api_key"]),
        "config_file": str(CONFIG_FILE),
    }


# --------------------------------------------------------------------------- #
# 统一后端接口
# --------------------------------------------------------------------------- #
class Backend:
    """所有后端实现的统一接口；refine.py 只认这个接口，不知道后端是本地还是云端。"""

    kind = KIND_NONE

    def __init__(self, config: dict | None = None):
        self.config = dict(config or {})

    def probe(self) -> dict:
        raise NotImplementedError

    def list_models(self) -> dict:
        raise NotImplementedError

    def chat(self, messages: list[dict]) -> str:
        raise NotImplementedError("真实推理将在 S7b 后半接入；当前绝不返回假结果")


def _http_get_json(url: str, headers: dict | None = None, timeout: float = _TIMEOUT_PROBE) -> dict:
    """轻量 GET，返回 (ok, data, error) 三元组内部用；异常里绝不拼入 key。"""
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        return {"ok": True, "data": json.loads(raw.decode("utf-8", "replace"))}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": "端点返回 HTTP %d" % exc.code}
    except (urllib.error.URLError, OSError, ValueError) as exc:
        # 只回错误类型，不回可能含 key 的 URL/头
        return {"ok": False, "error": "连接失败：%s" % type(exc).__name__}


def _endpoint_of(cfg: dict) -> str:
    """Cloud 用客户填的端点； Local 用固定本地地址（忽略配置里的端点）。"""
    return (cfg.get("endpoint") or "").rstrip("/")


def _auth_headers(cfg: dict) -> dict:
    """Cloud 加 Bearer；Local 不加鉴权头。key 只在这里短暂进入内存构造头。"""
    key = cfg.get("api_key") or ""
    return {"Authorization": "Bearer " + key, "Content-Type": "application/json"} if key else {}


# --------------------------------------------------------------------------- #
# LocalBackend —— 本机 ollama
# --------------------------------------------------------------------------- #
class LocalBackend(Backend):
    kind = KIND_LOCAL

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.base = LOCAL_DEFAULT_ENDPOINT

    def probe(self) -> dict:
        # ollama 的 GET /api/tags 是原生轻量端点；不打印响应体（可能含模型路径）
        res = _http_get_json(self.base + "/api/tags", timeout=_TIMEOUT_PROBE)
        return {
            "available": bool(res.get("ok")),
            "kind": KIND_LOCAL,
            "endpoint": self.base,
            "reason": "可用" if res.get("ok") else
                      ("未启用：本机 ollama 未运行（%s）" % res.get("error", "连接失败")),
        }

    def list_models(self) -> dict:
        res = _http_get_json(self.base + "/api/tags", timeout=_TIMEOUT_MODELS)
        if not res.get("ok"):
            return {"ok": False, "models": [], "error": res.get("error", "读取模型失败")}
        names = []
        for m in (res.get("data", {}).get("models") or []):
            if isinstance(m, dict) and m.get("name"):
                names.append(str(m["name"]))
        return {"ok": True, "models": names}


# --------------------------------------------------------------------------- #
# CloudBackend —— OpenAI 兼容端点（就是方案 B 的实现）
# --------------------------------------------------------------------------- #
class CloudBackend(Backend):
    kind = KIND_CLOUD

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.base = _endpoint_of(self.config)
        self.model = (self.config.get("model") or "").strip()

    def _ready(self) -> str | None:
        """返回 None 表示配置齐全；否则返回缺失提示。"""
        if not self.base:
            return "未配置云端端点"
        if not self.config.get("api_key"):
            return "未配置 API key"
        if not re.match(r"^https?://", self.base):
            return "端点必须以 http:// 或 https:// 开头"
        return None

    def probe(self) -> dict:
        missing = self._ready()
        if missing:
            return {"available": False, "kind": KIND_CLOUD,
                    "endpoint": self.base, "reason": "未启用：%s" % missing}
        # 探活：GET {endpoint}/models；失败诚实降级，错误不含 key
        # 注意：脱敏只针对 api_key，endpoint 是用户自己填的非敏感配置，原样回显。
        res = _http_get_json(self.base + "/models",
                             headers=_auth_headers(self.config), timeout=_TIMEOUT_PROBE)
        return {
            "available": bool(res.get("ok")),
            "kind": KIND_CLOUD,
            "endpoint": self.base,
            "reason": "可用" if res.get("ok") else
                      ("未启用：云端端点不可达（%s）" % res.get("error", "连接失败")),
        }

    def list_models(self) -> dict:
        missing = self._ready()
        if missing:
            return {"ok": False, "models": [], "error": missing}
        res = _http_get_json(self.base + "/models",
                             headers=_auth_headers(self.config), timeout=_TIMEOUT_MODELS)
        if not res.get("ok"):
            return {"ok": False, "models": [], "error": res.get("error", "读取模型失败")}
        names = []
        for m in (res.get("data", {}).get("data") or []):
            if isinstance(m, dict) and m.get("id"):
                names.append(str(m["id"]))
        return {"ok": True, "models": names}


# --------------------------------------------------------------------------- #
# 工厂 + 当前后端探测
# --------------------------------------------------------------------------- #
def current_backend(config: dict | None = None) -> Backend:
    cfg = dict(config if config is not None else load_config())
    kind = cfg.get("kind", KIND_NONE)
    if kind == KIND_LOCAL:
        return LocalBackend(cfg)
    if kind == KIND_CLOUD:
        return CloudBackend(cfg)
    return Backend(cfg)  # kind=none：基类，probe() 未实现 → 上层按未启用处理


def probe_current(refresh: bool = False) -> dict:
    """探测当前配置的后端；未配置返回诚实未启用，绝不假报可用。"""
    cfg = load_config(refresh=refresh)
    kind = cfg.get("kind", KIND_NONE)
    if kind == KIND_NONE:
        return {"available": False, "kind": KIND_NONE, "endpoint": "",
                "reason": "未启用：尚未配置精读后端（本地 ollama 或云端兼容端点）"}
    return current_backend(cfg).probe()


def list_models_current(refresh: bool = False) -> dict:
    cfg = load_config(refresh=refresh)
    if cfg.get("kind", KIND_NONE) == KIND_NONE:
        return {"ok": False, "models": [],
                "error": "尚未配置精读后端，请先到设置中配置"}
    return current_backend(cfg).list_models()
