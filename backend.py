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

**阶段边界（2026-11-17 更新）**：S7b 最初只实现配置管理 + probe + list_models，
``chat()`` 显式抛 NotImplementedError 绝不返回假结果。S8 收口后（用户明确
「LLM 模式要真能用」）已接入真推理：``LocalBackend.chat`` 走本机 ollama 的
OpenAI 兼容 ``/v1/chat/completions``，``CloudBackend.chat`` 走客户端点
``/chat/completions``，共用上述 HTTP 层；超时/异常仍诚实拒绝、绝不返回假结果。
基类 ``Backend.chat`` 保留 NotImplementedError（kind=none 未配置时诚实拒绝）。
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

# S8：提纯模式（与 LLM 后端类型正交）
# - extract：抽取式可信提纯（默认，零依赖零配置，架构级不造假）
# - llm：走大模型后端（需配置 kind + 模型）
MODE_EXTRACT = "extract"
MODE_LLM = "llm"
VALID_MODES = (MODE_EXTRACT, MODE_LLM)

# S11：多轮自我迭代提纯轮数（仅 extract 模式生效）
# 默认 1 轮 = 与 S8 旧行为完全一致；上限 5，防止误配导致长耗时。
REFINE_ROUNDS_DEFAULT = 1
REFINE_ROUNDS_MIN = 1
REFINE_ROUNDS_MAX = 5

LOCAL_DEFAULT_ENDPOINT = "http://localhost:11434"
DEFAULT_CONFIG = {
    "kind": KIND_NONE,
    "mode": MODE_EXTRACT,     # S8：默认抽取式；"不造假"是默认状态
    "endpoint": "",     # Cloud 必填；Local 可留空（用 LOCAL_DEFAULT_ENDPOINT）
    "api_key": "",      # Cloud 必填；Local 留空
    "model": "",        # 可选；空则用后端默认/第一个模型
    "allow_suppplement": False,  # S8：AI 补写开关，默认关闭（用户 2026-11-17 明确）
    "refine_rounds": REFINE_ROUNDS_DEFAULT,  # S11：多轮自我迭代轮数，默认 1（兼容旧行为）
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
    mode = data.get("mode", MODE_EXTRACT)
    out["mode"] = mode if mode in VALID_MODES else MODE_EXTRACT
    for key in ("endpoint", "api_key", "model"):
        val = data.get(key, "")
        out[key] = val.strip() if isinstance(val, str) else ""
    # S8：补写开关只认「明确为真」；缺省 false（默认关闭 = 默认不造假）
    out["allow_suppplement"] = _as_bool(data.get("allow_suppplement", False))
    # S11：迭代轮数收敛到 [1,5]；脏值回退默认，绝不因配置崩任务
    out["refine_rounds"] = _as_rounds(data.get("refine_rounds", REFINE_ROUNDS_DEFAULT))
    return out


def _as_rounds(value) -> int:
    """保守整数解析：非法/越界值收敛到合法区间，默认 1 轮。"""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return REFINE_ROUNDS_DEFAULT
    return max(REFINE_ROUNDS_MIN, min(REFINE_ROUNDS_MAX, n))


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
        # 「未修改」的两种写法都要保留原 key：
        #   ① 空串 —— 契约约定的「空值表示不改」；
        #   ② 与当前掩码完全相同 —— UI 会把掩码回填进输入框，用户没改却
        #      再保存时提交上来的就是掩码串。若不识别它，真 key 会被掩码
        #      永久覆盖（云端后端从此全部 401）。此处做后端兜底，
        #      前端也会主动把掩码转成空串，两道防线互不依赖。
        if not incoming["api_key"] or (
                current_key and incoming["api_key"] == mask_key(current_key)):
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


def _as_bool(value) -> bool:
    """**保守**布尔解析：只有明确为真才判真，其余一律判假。

    背景：``allow_suppplement``（AI 补写开关）会生成**原文之外**的内容，
    是敏感开关。若用 ``bool(value)`` 强转，字符串 ``"false"`` 会被当成
    True（Python 里非空字符串为真），从而在用户明确关闭时反而开启补写 ——
    方向错误且违反「默认不造假」的默认状态。

    规则：真布尔 True / 数字 1 / 字符串 "1|true|yes|on"（忽略大小写与空白）
    判开；其余（含 "false"、"0"、None、字典、列表）一律判关。
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value == 1
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return False


def public_config() -> dict:
    """给 UI 的**脱敏**配置：api_key 只回显掩码，绝不回显真值。"""
    cfg = load_config()
    return {
        "kind": cfg["kind"],
        "mode": cfg.get("mode", MODE_EXTRACT),
        "endpoint": cfg["endpoint"],
        "model": cfg["model"],
        "api_key": mask_key(cfg["api_key"]),
        "has_key": bool(cfg["api_key"]),
        "allow_suppplement": _as_bool(cfg.get("allow_suppplement", False)),
        "refine_rounds": _as_rounds(cfg.get("refine_rounds", REFINE_ROUNDS_DEFAULT)),
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
        raise NotImplementedError("未配置后端（kind=none）不提供真推理；请先在设置里选择本地或云端后端")


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


# 真推理超时（秒）：精读/修订是长任务，但不能无限挂住；超时即诚实报错，
# 绝不返回假结果。本地模型首次加载可能较慢，给得比探测宽一些。
_TIMEOUT_CHAT = 180.0


def _http_post_json(url: str, payload: dict, headers: dict | None = None,
                    timeout: float = _TIMEOUT_CHAT) -> dict:
    """轻量 POST JSON，返回 ``{ok, data|error}``；异常里绝不拼入 key / URL。"""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    hdrs = dict(headers or {})
    hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        return {"ok": True, "data": json.loads(raw.decode("utf-8", "replace"))}
    except urllib.error.HTTPError as exc:
        # HTTPError 的 reason 可能回显请求头片段 → 只报状态码，不读 body/reason
        return {"ok": False, "error": "端点返回 HTTP %d" % exc.code}
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
        return {"ok": False, "error": "连接失败：%s" % type(exc).__name__}


def _chat_content(res: dict) -> str:
    """从 OpenAI 兼容响应里取第一条 message.content；形状不符即报错。

    绝不返回空串冒充成功——没内容就是没内容，上层按失败处理、零产物。
    """
    if not res.get("ok"):
        raise RuntimeError("模型调用失败：%s" % res.get("error", "未知错误"))
    data = res.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("模型响应格式异常")
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("模型响应无 choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise RuntimeError("模型响应 choices 格式异常")
    msg = first.get("message")
    content = msg.get("content") if isinstance(msg, dict) else first.get("text")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("模型响应无有效正文")
    return content.strip()


def _resolve_chat_model(be) -> str:
    """确定 chat 用的模型名：配置里填了就用它，否则取后端第一个模型。

    本地 ollama 的 /v1/chat/completions 要求 model 字段；空着会报错，
    故从 /api/tags 取第一个诚实可用模型。云端服务端多支持省略 model，
    取不到就传空串（由服务端决定默认）。
    """
    configured = (be.config.get("model") or "").strip()
    if configured:
        return configured
    listed = be.list_models()
    models = listed.get("models") if isinstance(listed, dict) else None
    if isinstance(models, list) and models:
        return str(models[0])
    return ""


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

    def chat(self, messages: list[dict]) -> str:
        """本机 ollama 真推理（OpenAI 兼容 ``/v1/chat/completions``）。

        内容不出本机；model 空时从 ``/api/tags`` 诚实取第一个模型。
        """
        if not isinstance(messages, list) or not messages:
            raise ValueError("messages 不能为空")
        model = _resolve_chat_model(self)
        if not model:
            raise RuntimeError("本机 ollama 未安装任何模型，请先在 ollama 中拉取模型")
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "temperature": 0.2,   # 提纯要稳定可复现，不要发散
        }
        res = _http_post_json(self.base + "/v1/chat/completions", payload,
                              headers={}, timeout=_TIMEOUT_CHAT)
        return _chat_content(res)


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

    def chat(self, messages: list[dict]) -> str:
        """云端 OpenAI 兼容端点真推理（``{endpoint}/chat/completions``）。

        配置即知情同意（内容外传）；key 只在 Bearer 头里短暂进入内存，
        异常不回显 key / URL 细节。
        """
        missing = self._ready()
        if missing:
            raise RuntimeError("云端后端未就绪：%s" % missing)
        if not isinstance(messages, list) or not messages:
            raise ValueError("messages 不能为空")
        model = _resolve_chat_model(self)
        payload = {
            "messages": messages,
            "stream": False,
            "temperature": 0.2,
        }
        if model:
            payload["model"] = model
        res = _http_post_json(self.base + "/chat/completions", payload,
                              headers=_auth_headers(self.config),
                              timeout=_TIMEOUT_CHAT)
        return _chat_content(res)


class ExtractBackend(Backend):
    """S8：内置抽取式提纯引擎（**恒可用、零依赖、零配置**）。

    它不是"用户配置的后端"，而是永远存在的兜底引擎：
    * 不需要装 ollama、不需要云端 key、不下载任何模型；
    * 纯标准库实现（二元组切词 + TF-ICF + TextRank + MMR）；
    * 输出为**原文原句**，架构级保证不造假（见 extract_engine.verify_traceable）。

    因此 ``probe()`` 恒返回 available —— 这是内置能力，不是外部工具探测，
    **绝不进 media_tools.TOOL_SPECS**（S1 契约锁死 3 工具）。
    """

    kind = "extract"

    def __init__(self, config: dict | None = None):
        super().__init__(config)

    def probe(self) -> dict:
        return {
            "available": True,
            "kind": "extract",
            "endpoint": "",
            "reason": "可用（内置抽取式引擎，零依赖离线运行）",
        }

    def list_models(self) -> dict:
        # 抽取式没有"模型"概念；如实说明，不编造
        return {"ok": True, "models": [],
                "note": "抽取式模式不依赖模型，无模型列表"}

    def extract(self, md_text: str, top_k: int = 8) -> dict:
        """执行抽取式提纯（真正的实现在 extract_engine，避免本模块膨胀）。"""
        import extract_engine
        return extract_engine.extract_core(md_text, top_k=top_k)


# --------------------------------------------------------------------------- #
# 工厂 + 当前后端探测
# --------------------------------------------------------------------------- #
def current_backend(config: dict | None = None) -> Backend:
    """按配置返回当前引擎。

    * ``mode == "extract"``（默认）→ 内置 :class:`ExtractBackend`，恒可用；
    * ``mode == "llm"`` → 按 kind 取 Local/Cloud，kind=none 时退化为基类（未启用）。
    """
    cfg = dict(config if config is not None else load_config())
    if cfg.get("mode", MODE_EXTRACT) == MODE_EXTRACT:
        return ExtractBackend(cfg)
    kind = cfg.get("kind", KIND_NONE)
    if kind == KIND_LOCAL:
        return LocalBackend(cfg)
    if kind == KIND_CLOUD:
        return CloudBackend(cfg)
    return Backend(cfg)  # kind=none：基类，probe() 未实现 → 上层按未启用处理


def probe_current(refresh: bool = False) -> dict:
    """探测当前配置的后端；未配置返回诚实未启用，绝不假报可用。"""
    cfg = load_config(refresh=refresh)
    mode = cfg.get("mode", MODE_EXTRACT)
    if mode == MODE_EXTRACT:
        return ExtractBackend(cfg).probe()
    kind = cfg.get("kind", KIND_NONE)
    if kind == KIND_NONE:
        return {"available": False, "kind": KIND_NONE, "endpoint": "",
                "reason": "未启用：LLM 模式尚未配置后端（本地 ollama 或云端兼容端点）"}
    return current_backend(cfg).probe()


def list_models_current(refresh: bool = False) -> dict:
    cfg = load_config(refresh=refresh)
    if cfg.get("kind", KIND_NONE) == KIND_NONE:
        return {"ok": False, "models": [],
                "error": "尚未配置精读后端，请先到设置中配置"}
    return current_backend(cfg).list_models()
