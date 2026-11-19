# 精核 · 阶段 2/3 新能力契约（v0.1 · S0 草案）

> 立约日期：2026-11-15 · 状态：**v0.9 已生效**（S0–S4 已完成放行；S7 精读/修订已发布 v0.5.0；**S8 可信提纯已发布 v0.6.0，缺陷修复版 v0.6.1（LLM 真推理已接入）**；S5 视频链接已实现（域名不设限 + SSRF 防护 + cookie 只读）；S9 阶段 4 知识库已合并（85feb75）并随 **v0.7.0 发布**）
> 适用能力：Word 输入增强 / `.md` → `.docx` 导出 / 音频 → `.md` / 视频 → `.md` / 视频链接 → `.md` / 自更新 / 拖拽输入与勾选预览 / **精读提纯 + 修订双产物** / **可信提纯（A/B/C 三档）**
> 代码基线：`extract.py` v0.6.0（S8 升号），CI 全绿，82 用例，9 项发版门禁
> 规格基线：`SPEC.md` v2.11（冻结，唯一写者，本契约不修改它）

---

## 0. 本契约的地位：正交补充，不是修订

`SPEC.md` 是**阶段 1 的冻结规格正本**，其第 4 行明写「阶段 2 核心提炼 / Word、阶段 3 音视频、阶段 4 知识库 / 自动化一律不提前实现」；第 110 行把音视频列为「阶段 3 预留组：不纳入转换候选、不调用任何 ASR、不产出 md」；第 190 行是红线 2「不得把视频当音频转写」。

因此新增能力**不能靠改 `SPEC.md` 来解禁**，否则会一次性推翻黑盒回归、件数对账与「设计内降级」语义。正确做法是另立一份**正交契约**：

| 判定 | 归属 | 依据 |
| --- | --- | --- |
| 输入经 `extract.py::classify()` 落入 `DEFERRED_EXT` | 仍按 `SPEC.md` 判「阶段 3 待支持」，不解析、不调 ASR、不产出 md | `SPEC.md` §3.D / 红线 2 |
| 输入经**新入口**主动选择音视频/链接/Word 能力 | 按本契约走独立 handler、独立端点、独立产物区 | 本契约 §2 / §4 |
| 两者冲突时 | **阶段 1 内核优先，本契约让路** | §1 不变量 |

一句话：**老路面一寸不动，新流量走新匝道**。若将来要把新能力合并进阶段 1 主流水线，须由用户单独确认修订 `SPEC.md`；本契约不授予该权限。

---

## 1. 不变量（任何阶段都不得突破）

1. **冻结内核**：`extract.py` 的探测 / 分流 / 提取 / 汇总 / 对账主流水线一行不动；`SPEC.md` 一字不改。
2. **零第三方依赖**：软件本体仍只用标准库；模型、ASR 引擎、ffmpeg、yt-dlp、云服务**只放独立模块，绝不冻结进 exe**，也不随安装包分发。用户已选定「本机可插拔工具」策略。
3. **单文件 exe**：PyInstaller onefile + windowed；`build.spec` 不收集任何外部可执行文件或模型。
4. **只监听本机**：恒绑 `127.0.0.1:54321`，不对外开端口；进度用 400ms 轮询 `/api/progress?since=N`，**不引 SSE / WebSocket**（`SPEC.md` §8.7 / §8.8）。
5. **服务状态收敛**：只报 `idle / running / done / cancelled / failed` 五态（`SPEC.md` §8.4）；`running` 期间拒绝并发任务。
6. **诚实降级**：缺工具、缺引擎、超时、解析失败一律显式回 `ok:false` + 可读原因；**绝不产出伪转写、绝不写空 md、绝不假装成功**。UI 必须显示「未启用」而不是灰色可点按钮。
7. **不污染阶段 1 对账**：新能力产物**不得写入 `out/md/*.md`**。该目录受双向件数对账约束（`SPEC.md` §3.F、`test_extract.py` 实盘数断言），多写一个文件就会让对账不平。新产物落独立区（§4）。
8. **出处可回溯**：新产物的每个内容块都能回溯到 `(doc_id, anchor, 工具名与版本)`；沿用 8 字段 `src` 注释与块级锚点格式（`SPEC.md` §5.1 / §5.2）。
9. **临时文件所有权归父进程**：任何「子进程 + 临时文件」链路必须先回答清理责任；`finally` + `atexit` + 启动孤儿清扫三条链齐备，**靠 `atexit` 兜强杀场景一律不合格**（`SPEC.md` §8.6）。
10. **每次修改后**：全量用例 + 9 项门禁 + 打包 exe（供本地查看）；**上传 GitHub / 推版本 tag / 发 Release 改为「用户明确说上传才做」**（2026-11-16 用户改定，覆盖早期「每次都上传」的规则）。

---

## 2. 五层架构与扩展点

```
┌─ L5 产物契约 ────────────────────────────────────────────┐
│  .md 结构 / src 8 字段 / 块级锚点 / derived + provenance │
├─ L4 后处理编排 ──────────────────────────────────────────┤
│  app.py：Job 事件总线、进度、取消、超时、端点路由         │
├─ L3 能力适配 ────────────────────────────────────────────┤
│  ToolAdapter 统一接口 + 健康探测 + 诚实降级；handler 注册表│
├─ L2 解析与安全 ──────────────────────────────────────────┤
│  URL 白名单 / 防 SSRF / 重定向收敛 / 大小与时长上限        │
├─ L1 输入来源 ────────────────────────────────────────────┤
│  本地文件、本地文件夹、视频直链、播放列表                  │
└════════════ 冻结内核：extract.py（阶段 1，不动） ═══════┘
```

- **单一注册源 `FORMAT_REGISTRY`**（S1 落地）：把散落 4 处的扩展名集合收敛为一张表，每条记录含 `ext / kind(文本|富文档|音视频|旧版|链接) / stage1_bucket / new_capability / handler / tool`。现有漂移见 `S0-立项与契约对账.md` §5。
- **handler 注册表**：新能力以 `register(ext/kind, handler)` 挂到 L3，不改 `if/elif` 主链；`/api/transcribe`（`app.py:2370`）现有的「诚实拒绝」保留为空心位，由 S3/S4 填充实现或改由新端点承接。
- **可复用模板**：`extract.py:1653 _resolve_markitdown()`（可选增强 + 健康探测 + 静默回退）、`app.py:113 _download_release_asset()`（白名单 + 流式下载 + `.part` 原子替换 + 大小上限）、`app.py:690 Job` 与 `Job.add(..., progress=...)`（事件总线）、`app.py:1701 _extractive_summary()`（后处理产物范式）。

---

## 3. 外部工具适配器契约（用户选定「本机可插拔工具」）

| 项 | 约定 |
| --- | --- |
| 统一接口 | `probe() -> {available, path, version, reason}`；`run(job, input, ...) -> 结构化结果`；`cancel()` 能终止外部子进程 |
| 探测方式 | 真实执行一次轻量命令（如 `ffmpeg -version` / `whisper --help` / `yt-dlp --version`），带超时、捕获输出、`CREATE_NO_WINDOW`；结果缓存，进程期内可刷新 |
| 缺工具语义 | 端点返回 `{"ok": false, "capability": "unavailable", "error": "…未启用，请在本机安装 X 后重试"}`；UI 显示「未启用」并给出安装提示，**不产出任何 md** |
| 工具来源 | 由用户在**本机**提供；软件不下载、不打包、不自动安装、不内置凭据 |
| 版本记录 | 产物 `src` 注释的 `converter` 字段必须写真实工具名 + 探测到的版本，便于回溯 |
| 隐私 | 音视频与链接内容只在本机处理；除非用户显式配置，不外传任何云服务 |

**绝对禁止**：把「探测不到工具」包装成成功；用占位文本 / 文件名 / 元数据冒充转写正文；把视频文件直接丢给音频 handler 后声称完成（红线 2）。

---

## 4. 产物契约

### 4.1 存放位置（S0 关键裁决）

- 阶段 1 的 `out/md/*.md`、`out/INDEX.md`、`out/MERGED.md`、`out/provenance.json` 属**冻结对账盘**，新能力只读、不写。
- 新产物落 `out/derived/`（暂定名，S1 定稿），例如 `out/derived/<doc_id>.md`；配套 `out/derived/provenance_media.json` 记录逐条状态、工具版本、耗时、失败原因。
- 「三处留痕」的准确含义：**新产物自带来源注释 + 块级锚点 + 独立 provenance 条目**；不改写 `INDEX.md` / `MERGED.md` 的件数统计。若将来要合并进 `MERGED.md`，须走显式「追加章节 + 同步 provenance + 不动件数」流程，且默认不做。

> 这是对上一轮路线图「落 INDEX/MERGED/provenance 三处留痕」的精化：直接写入会破坏 §3.F 双向件数对账与多条黑盒断言。

### 4.2 `.md` 结构

```
<!-- source: 相对路径 | format: .mp4 | extracted: YYYY-MM-DD HH:MM:SS -->
<!-- src: doc_<12hex> | path: <规范化相对路径> | format: .mp4 | converter: <工具名+版本> | extracted: <stamp> | size: <bytes> | sha256: <完整64位小写hex> | anchors: <键列表> -->
# <标题>

## 元数据
- 时长 / 分辨率 / 码率 / 容器 / 来源 URL（如适用）

## 音轨转写
<!-- anchor: doc_<12hex> | block: 1 | time: 00:00:00.000-00:00:08.240 -->
[00:00:00.000 → 00:00:08.240] …

## 画面 / 字幕
<!-- anchor: doc_<12hex> | block: 2 | time: … -->
…
```

- 8 字段**固定顺序、全必含**；`sha256` 用原始文件字节的完整 64 位小写十六进制；`doc_id = doc_ + sha256(原始字节)[:12]`，不含路径字符（`SPEC.md` §5.1）。
- 块级锚点沿用 `<!-- anchor: doc_[0-9a-f]{12} | … -->` 正则；音视频用 `block` + 新增 `time`/`frame` 定位键，**不适用的 `page/slide/sheet/chapter` 省略而非留空**（§5.2）。
- **视频产物必须包含三区块**：音轨转写 + 画面/字幕 + 元数据。只有音轨转写的产物视为不合格（红线 2 的正向要求）。
- 失败项不落空文件；在 `provenance_media.json` 与运行日志中显式留痕。

---

## 5. 长任务契约

- 复用 `Job`（`app.py:690`）+ `Job.add(etype, text, progress=...)` + 400ms 轮询；**不新开 SSE**。
- S1 需补齐：`deadline` / 单任务超时、`cancel()` 对**外部工具子进程**的终止链（含进程组）、批量队列的逐条状态。
- 取消后状态必须收敛到 `cancelled`，不允许停在 `running`；首卡标签沿用「已产出（未完成）」，禁止显示「成功 N」（`SPEC.md` §8.5）。
- 临时目录由父进程按 `jinghe-run-<pid>-<seq>` 分配并持有，`finally` 删除；取消/强杀后不留用户文档副本（§8.6 三链）。
- 播放列表：逐条入队、逐条成功/失败/跳过，单条失败不终止整批；总条目数与单条大小/时长都有上限。

---

## 6. 安全契约（S5 重点）

| 风险 | 强制措施 |
| --- | --- |
| SSRF / 内网探测 | 只接受 `http`/`https`；解析后逐跳校验 IP，拒绝环回、私网、链路本地、保留段；DNS 重绑定须固定首次解析结果并用于连接；重定向**逐跳重新校验**，限制最大跳数 |
| 超大 / 超长资源 | 大小上限、时长上限、分片数上限；流式写入、超限即断链并清理 |
| 下载完整性 | `.part` 临时文件 + 原子替换；取消即清理；参照 `_download_release_asset()` 白名单范式 |
| 任意路径 / 任意程序启动 | 沿用 `/api/open` 白名单收敛（`SPEC.md` §8.7 路径穿越防护）；新端点不得接受任意绝对路径 |
| 平台与合规 | 不内置任何平台凭据，不提供绕过登录 / 付费 / DRM / 防盗链的能力；仅处理用户有权访问的内容；产物归属与版权由用户负责 |
| 隐私 | 链接与日志不回传；错误文案不泄漏本机绝对路径以外的敏感信息 |

---

## 7. 端点命名规范（S1 定稿，此处仅约定形状）

- 响应统一 `{"ok": bool, ...}`；失败必带可读 `error`；未知 `/api/*` 的 GET/POST 同形返回 `404 + JSON`（`SPEC.md` §8.3）。
- 候选：`/api/tools/probe`（健康探测）、`/api/word/export`（`.md` → `.docx`）、`/api/media/run` `/api/media/status` `/api/media/cancel`（音视频与批量）、`/api/link/resolve`（链接预检）。
- **不得**改动既有端点旧契约：`/api/transcribe` 在无后端时仍返回诚实拒绝；`/api/summarize` 行为不变；新增端点走增量，不重写路由主链。
- S3 定稿：`POST /api/audio/inspect`、`POST /api/audio/transcribe`、`POST /api/audio/cancel`、`GET /api/audio/status?since=N`。
- S4 定稿：`POST /api/video/inspect`、`POST /api/video/transcribe`、`POST /api/video/cancel`、`GET /api/video/status?since=N`；与 `/api/audio/*` 形状对称、但走**完全独立的 video handler**，`/api/media/run` **留给 S5** 批量编排，`/api/link/resolve` 仍是 S5 候选。（订正 v0.5 曾写「留给 S4/S5」的漂移：S4 已由 `/api/video/*` 承接。）

---

## 8. 分阶段与验收口径（逐阶段确认）

| 阶段 | 交付 | 验收 | 闸门 |
| --- | --- | --- | --- |
| **S0** 立项与契约对账 | 本契约 + 需求确认表 + 红线解禁清单 + 受影响断言清单 | 60 用例原样全绿、9 项门禁通过、`SPEC.md` 与功能代码零改动 | 等用户确认 |
| **S1** 能力框架地基 | `FORMAT_REGISTRY` 收敛、`ToolAdapter` + 健康探测、`Job` 进度/取消/超时、`derived/` 产物区 | 缺工具时按钮诚实显示「未启用」；长任务可取消；临时文件零残留；既有断言全绿 | 等确认 |
| **S2a** Word → .md 输入增强 | `.doc` 旧格式（本机 LibreOffice 预处理适配）、批注/修订/加密识别 | 不引第三方库；加密仍单列「待人工授权」不破译；产物守 8 字段 | **已完成** |
| **S2b** .md → .docx 导出 | 纯标准库 `zipfile` + OOXML 独立模块，放开禁用按钮 | 产物可被 Word 打开；来源注释与锚点不丢；exe 不含重依赖 | **已完成**（S2b 闸门已放行） |
| **S3** 音频 → .md | ASR 适配器 + 时间戳 + 诚实降级 | 真实样本非空、可取消、失败诚实回显；绝不伪转写 | **已完成**（S3 闸门已放行） |
| **S4** 视频 → .md | 独立 video handler（音轨 + 画面/字幕 + 元数据），**不复用音频路径** | 三区块齐备；`test_06`/`test_11` 原样全绿（守护冻结内核） | **已完成 · 等确认（S5）** |
| **S5** 视频链接 → .md | 任意链接与播放列表、防 SSRF、重定向、批量队列（复用 S4 handler） | 恶意/越界 URL 被拒；取消即清理；单条失败不拖垮整批 | **已实现 · 等确认（S6）** |
| **S6** 工程化收口 | 测试矩阵、CI 可选依赖探测、门禁扩项、exe、push tag、Release 资产核对 | 全量用例 + 门禁 + CI 全绿；Release 带 exe | 最终验收 |

每阶段收尾按用户长期规则：全量用例 → 9 项门禁 → 打包 exe → 上传 GitHub → 推版本 tag → **停下等确认**。

---

## 9. 风险登记（S0 先挂账，不承诺消除）

| 编号 | 风险 | 处置 |
| --- | --- | --- |
| R1 | 外部工具版本差异导致输出漂移 | `converter` 字段记录版本；测试用 mock 后端，真实工具只做冒烟 |
| R2 | 平台解析涉及鉴权 / 版权 / 合规 | 不内置凭据、不绕过限制；S5 开工前再确认可接受范围 |
| R3 | 长任务资源占用与强杀残留 | §5 超时与三链清理；测试覆盖取消与临时目录 |
| R4 | 私有仓库导致匿名「检查更新」404（v0.4.1 遗留） | **已消除（v0.4.8）**：仓库改为 public，匿名可查 release 与安装包；自更新另立白名单与红线，见 §12 |
| R5 | 新产物与阶段 1 对账盘混淆 | §4.1 独立 `derived/` 区；新增断言守护「`md/` 实盘数不变」 |
| R6 | 规格漂移（UI 路线图标阶段 3「已交付」等） | 见 `S0-立项与契约对账.md` §5；按阶段订正，不动 `SPEC.md` |

---

## 10. 生效条件

本契约在用户确认 S0 交付后生效；生效后作为 S1–S6 的引用基线。任何与本契约冲突的实现，以 §1 不变量为准。契约本身的修订须在本文件追加版本记录（v0.2、v0.3…），不得回改 `SPEC.md`。

---

## 11. 版本记录

- **v0.1（2026-11-15 · S0）**：初始草案。另立与 `SPEC.md` 正交的新能力契约，钉死 10 条不变量、五层架构、产物区 `out/derived/`、S0–S6 验收口径与风险登记；同时裁决「`test_06`/`test_11` 永不改写」与「新产物不写冻结对账盘」。
- **v0.2（2026-11-15 · S1）**：用户确认 S0 后生效；S1 落地后补以下裁决，**§1 不变量一条未改**：
  1. `FORMAT_REGISTRY` 采用「冻结内核只读真源 + 注册表单向镜像 + 一致性断言」。`stage1` 是 `extract.py` 常量的只读副本，`media` 是新能力唯一写者；`.m4v` / `.wmv` 并集只属于 `media`，不回写冻结内核。
  2. 工具健康探测定稿为独立端点 `GET /api/tools/probe`（支持 `?refresh=1`），**不挂** 400ms 轮询的 `/api/state`；`capabilities` 如实标记 S2b / S3 / S5 未接入，缺工具时 UI 显示「未启用」。
  3. 超时看门狗不侵入 `_run_job_inner` 主循环；阶段 1 提取任务不挂看门狗，行为零变化。
  4. `out/derived/` 只在被新能力显式调用时创建；阶段 1 流程完全不碰，`INDEX.md` / `MERGED.md` / `out/md/` 保持只读。
  5. 测试基线由 60 → **62 用例**（`test_33` / `test_34` 对应 S0 报告 B 类扩项：注册表一致性、诚实降级、产物区不污染、超时与子进程终止）。
  6. §7 端点候选中的 `/api/tools/probe` 已定稿实现；`/api/word/export`、`/api/media/run`、`/api/link/resolve` 仍是候选，S2b / S3 / S5 再定稿。
- **v0.3（2026-11-15 · S2a）**：用户确认 S1 后开工；S2a 落地后补以下裁决，**§1 不变量一条未改**：
  1. S2a 端点定稿为 `POST /api/word/inspect`（只读预检、不写文件）与 `POST /api/word/enhance`（写 `derived/` 产物）。`/api/word/export` 仍是 S2b 候选，不得提前占用。
  2. 新工具探测**独立挂** `word_input.probe_soffice()`，不并入 `media_tools.TOOL_SPECS`；能力状态作为 `/api/tools/probe` 的**顶层增量字段 `word_input`** 返回。理由：S1 契约测试硬锁了「3 个工具」与「`capabilities()` 全部未启用」，S2a 不改写既有 62 个断言。
  3. `.docx` 增量解析为纯标准库，正文按「接受全部修订」呈现，修订明细另列区块；批注带作者 / 时间 / 锚定段落号；产物为「文档信息 / 正文 / 批注 / 修订」四区块，每区块前挂块级锚点。
  4. 加密只认**正向证据**（OLE 内含 `EncryptedPackage`/`EncryptionInfo`、ZIP 成员加密位、加密信息成员），单列 `待人工授权`；普通 `.doc` 的 OLE 复合文档头**不得**误判为加密；不破译、不询问口令、不盲重试。
  5. `.doc` 预处理临时目录三链齐备：父进程持有 → `finally` 删除 → `atexit` 兜底 → 启动时清扫 24 小时前过期孤儿；不靠单一 `atexit` 兜强杀。
  6. 新产物四区块之外，失败项一律不落空 md，只在 `results` 与 `provenance_media.json` 留痕；部分成功必须显式回 `warning`，不得宣称全部完成。
  7. 测试基线由 62 → **64 用例**（`test_35` / `test_36`）。`test_06` / `test_11` 仍原样保留，`/api/transcribe` 空心位留给 S3/S4。
- **v0.4（2026-11-15 · S2b）**：用户确认 S2a 后开工；S2b 落地后补以下裁决，**§1 不变量一条未改**：
  1. §7 端点候选 `/api/word/export` 正式定稿为 `POST /api/word/export`。显式 `.md` 输入优先；未给时**只读**自动收集 `MERGED.md`，其次 `out/md/*.md`（上限 20 个）。`/api/media/run`、`/api/link/resolve` 仍是 S3/S5 候选。
  2. 产物为 `out/derived/<doc_id>.docx`（`doc_id` 取源 `.md` 字节的 sha256 前 12 位）+ `provenance_media.json`；**provenance 必须读旧条目后追加**，不得覆盖 S2a 历史条目；空输入零副作用（连 `derived/` 都不创建）。
  3. 「来源注释与锚点不丢」定稿为双保险：① 每条 `<!-- source/src/anchor … -->` 按**原文**渲染为 `SourceNote` 段落，位置顺序不变；② `src` 原文写入 `docProps/core.xml` 的 `dc:description`。验收须用 `word_input.parse_ooxml()` 反向读回形成闭环。
  4. OOXML 包最小部件定为 8 个（内容类型、根关系、document.xml、document.xml.rels、styles.xml、settings.xml、core.xml、app.xml）；所有文本必须 XML 转义并剔除 XML 1.0 非法控制字符；`body` 以空段落收尾，表格后不得直接接 `sectPr`。
  5. **`media_tools.capabilities()` 是 S1 的「能力占位清单」**，被 `test_33` 的「全部未启用」硬断言锁死，**S2a/S2b 一律不改写**；其 `word_export.enabled=false` 仅表示占位未接入，已落地能力的真实状态一律以 `/api/tools/probe` **顶层增量字段**（`word_input` / `word_export`）为准。本轮只订正该函数的注释说明，逻辑零改动。
  6. 输入上限：单文件 8 MB / 2 万行；文件不存在、非 `.md`、空白正文、超上限、写入失败一律诚实失败且零 `.docx` 产出；`.part` 原子替换，失败清理半成品；部分成功显式回 `warning`。
  7. 测试基线由 64 → **66 用例**（`test_37` / `test_38`）。`test_06` / `test_11` 与 `/api/transcribe` 空心位仍原样保留。
- **v0.5（2026-11-15 · S3）**：用户确认 S2b 后开工；S3 落地后补以下裁决，**§1 不变量一条未改**：
  1. **`/api/transcribe` 空心位原样保留**。`test_34`（识别到文件也只诚实拒绝）、`test_38`（「阶段 3 音视频转写需专用转写器」与 `el.btnTranscribe.disabled = !on || !mediaOn`）双锁旧契约；就地填充必然删改文案并使既有 66 个断言变红。S3 另开 `/api/audio/*` 四个端点，S4 视频走独立 handler，绝不复用音频路径。
  2. **能力状态仍走顶层增量字段**：`/api/tools/probe` 新增 `audio_transcribe`（`enabled` = 本机 whisper 与 ffmpeg 同时可用）。`media_tools.capabilities()` / `TOOL_SPECS` / `payload.tools` 与 `media_ready()` 一律不改写；`media_ready()` 因占位清单锁死恒 False，**不得**当 S3 就绪判据。
  3. **只认 JSON 文件输出**：`whisper <in> --model <m> --task transcribe --output_format json --output_dir <temp>`，从 `--output_dir` 读 `<stem>.json`，不读 stdout（冻结态 stdout 可能为 None）；否决 srt / vtt（逗号毫秒、BOM、二次解析易把失败伪装成空转写）。ffmpeg 只做 `ffmpeg -hide_banner -i <in>` 只读时长探测，失败不阻断转写，元数据明确写「未探测到」。
  4. **绝不产出伪转写**：`segments` 必须存在且含至少一条 `text` 非空、时间合法（`0 <= start <= end <= 99h`、有限值）的分段才写 md；空分段 / 无语音 / 非法 JSON / 非 0 退出 / 缺工具一律 `ok:false` + 零 md，**不生成「无语音」说明文档**。非法时间段逐条丢弃并在 `## 转写元数据` 计数。时间戳统一 `HH:MM:SS.mmm`。
  5. **视频拒收优先于存在性与工具检查**：只认 `format_registry.MEDIA_AUDIO`，且 `media_kind(ext) == "video"` 先于文件存在性判定；不得沿用 `app.py:_STAGE3_AUDIO_EXT`（它是 `MEDIA_EXT` 并集，含全部视频后缀，是当前最危险的真实隐患）。缺工具时视频仍逐条回「不支持」而非笼统「未启用」。
  6. **产物与出处**：`out/derived/<doc_id>.md`（`doc_id = doc_ + sha256(原始音频字节)[:12]`）+ 8 字段 `src`（`converter` 只写 `whisper <版本> + ffmpeg <版本>`，探不到写「版本未探测到」，绝不写「内置 ASR」）+ 块级锚点 `time` 键；区块为「文档信息 / 音轨转写 / 转写元数据」，**音频不写画面 / 字幕区块**（那是 S4 视频三区块要求）。provenance 读旧追加，失败项也留痕；**能力级缺工具时零副作用**（连 `derived/` 都不创建），只在 results 与运行日志回显。
  7. **长任务与进程树**：转写任务单独持有 `_AUDIO_JOB`（不污染阶段 1 `/api/progress` 与件数对账），复用 `Job` 事件总线 / `register_child` / `terminate_children` 与 `start_job_watchdog`；新增 `media_tools.terminate_process_tree()`，Windows 用 `taskkill /T /F /PID` 杀 whisper 派生的整棵 ffmpeg 进程树，POSIX 用 `killpg`。临时目录 `jinghe-run-audio-<pid>-<seq>` 三链齐备，前缀刻意与阶段 1 `jinghe-run-<pid>-<seq>` 隔离，避免孤儿清扫误删。
  8. **UI 增量**：新增「音频转写 → .md」与「取消转写」按钮；老的音视频转写占位按钮与 S1 诚实降级判定原样保留。缺工具显示「未启用」。
  9. 测试基线由 66 → **68 用例**（`test_39` / `test_40`）。`test_06` / `test_11`、`test_34` / `test_38` 的空心位断言全部原样保留。
- **v0.6（2026-11-15 · S4）**：用户确认 S3 后开工；S4 落地后补以下裁决，**§1 不变量一条未改**：
  1. **端点与 S5 契约订正**：S4 定稿为 `POST /api/video/inspect` / `transcribe` / `cancel` + `GET /api/video/status?since=N`，与 `/api/audio/*` 形状对称但互不相交；`/api/media/run` **留给 S5** 批量编排（订正 v0.5「留给 S4/S5」漂移）。`/api/transcribe` 空心位与 `test_34` / `test_38` 双锁断言继续原样保留。
  2. **双向红线隔离**：`video_transcribe.py` **不 import** `audio_transcribe`、不调用其 `transcribe` / `parse_segments` / `_whisper_argv`（连 `format_timestamp` 也自带一份）；`audio_transcribe.py` 亦不反向依赖视频模块。两侧都在存在性与工具检查之前先做分类：视频只认 `MEDIA_VIDEO`、音频只认 `MEDIA_AUDIO`，对方后缀逐条回「不支持」。
  3. **能力探测**：`video_transcribe.enabled` = 本机 whisper 与 ffmpeg 同时可用；**ffprobe 只是可选增强**，只在 `video_transcribe.capability()['tools']['ffprobe']` 自有子结构里探测，**绝不并入 `media_tools.TOOL_SPECS` / `probe['tools']`**（`test_40` / `test_42` 硬锁恰好 3 个工具）。`capabilities()` / `media_ready()` 恒不变，不得当就绪判据。
  4. **画面 / 字幕区块的诚实实现**：零依赖下不提供 OCR / 视觉模型，只写两类可验证事实 —— ① `ffmpeg -map 0:s:0 -c:s srt` 机械导出的真实内嵌字幕条目（SRT 逗号毫秒归一化 `HH:MM:SS.mmm`）；② 只读探测到的画面流元数据（分辨率 / 帧率 / 编码 / 时长，`ffprobe -of json` 优先、失败回退 `ffmpeg -i` 文本解析）。**绝不写「画面显示…」「可以看到…」等语义描述**；无字幕轨时该区块只陈述「未检测到内嵌字幕轨」与「不生成画面语义描述」等客观状态，**不用占位文本冒充画面内容**；bitmap 字幕（dvd_sub / dvb_sub）转 srt 失败即诚实跳过，绝不 OCR。
  5. **双门禁防伪产物**：① 必须解析出至少一条视频流元数据，否则零 md（不写空壳三区块）；② **真实语音分段或真实字幕条目至少有一项**，只有元数据 / 状态说明的视频一律 `ok:false` + 零 md，并在 provenance 留失败痕。无音轨但有字幕（或反之）允许产出，缺失一侧只写客观状态行。
  6. **调用形状**：ffmpeg 一律加 `-hide_banner -nostdin`（防子进程读 stdin 挂住）；抽音轨 `-map 0:a:0 -vn -ac 1 -ar 16000 -c:a pcm_s16le`；字幕导出 `-map 0:s:0 -c:s srt`；whisper 仍只认 `--output_format json` 的**文件输出**，不读 stdout。所有正文严格 `encoding='utf-8'`，`errors='replace'` 只用于诊断输出。
  7. **产物与出处**：恰好三区块「元数据 / 音轨转写 / 画面 / 字幕」；8 字段 `src` + `<!-- anchor … | block | time -->`；`converter` 写 `whisper <ver> + ffmpeg <ver>`（ffprobe 可用时追加其版本），**绝不写「内置视觉模型」**；`anchors` 只声明实际用到的 `block` / `time`，**不虚报未实现的 `frame` 键**。产物落 `out/derived/<doc_id>.md`（`.part` 原子替换）+ provenance 读旧追加，失败项也留痕；能力级缺工具零副作用（连 `derived/` 都不创建）。
  8. **长任务与进程树**：单独持有 `_VIDEO_JOB` / `_VIDEO_LOCK`（与 `_JOB`、`_AUDIO_JOB` 三条事件队列互不相交），复用 `Job` + `start_job_watchdog` + `register_child` / `terminate_children` + `media_tools.terminate_process_tree()`；临时目录 `jinghe-run-video-<pid>-<seq>` 三链齐备并在启动时 `sweep_orphan_temps()` 清扫，前缀与阶段 1 / S3 隔离。
  9. **UI 增量**：新增「视频提取 → .md」与「取消提取」按钮，真实能力走顶层 `video_transcribe`；老的音视频转写占位按钮与 S1 诚实降级判定原样保留。
  10. 测试基线由 68 → **70 用例**（`test_41` / `test_42`）。`test_06` / `test_11`、`test_34` / `test_38` 的冻结与空心位断言全部原样保留。
- **v0.7（2026-11-16 · v0.4.8 自更新）**：用户要求「检查更新」按实际情况反馈当前/最新版本、显示正在更新、并能真正完成更新后补以下裁决，**§1 不变量一条未改**：
  1. **版本来源转公开**：`kong-city/jinghe` 由 private 改为 **public**（用户明确决策）。此前匿名访问 `api.github.com/repos/kong-city/jinghe/releases/latest` 恒 404，「检查更新」永远落在离线分支，R4 结清。客户端仍支持可选 `JINGHE_GH_TOKEN` 环境变量作为仓库再转私有时的兜底，令牌**不入代码、不上界面**。
  2. **两步式端点**：`GET /api/update/check`（只查版本，不下载不安装不弹浏览器）、`POST /api/update/start`（后台任务，立即返回）、`GET /api/update/status?since=N`（进度轮询）、`POST /api/update/cancel`、`POST /api/update/apply`（补救入口）。旧 `GET /api/check-update` / `POST /api/update` / `POST /api/open-latest` **保留兼容**，只做字段形状兼容，解析真源收敛到 `self_update.check`。
  3. **进度队列独立**：自更新单独持有 `_UPDATE_JOB` / `_UPDATE_LOCK`，与 `_JOB`（阶段 1）/ `_AUDIO_JOB`（S3）/ `_VIDEO_JOB`（S4）四条队列互不相交，不污染 `/api/progress`，更不触碰 `out/md/` / `INDEX.md` / `MERGED.md`。
  4. **下载白名单**：只接受本仓库 `releases/download/` 前缀下的 `Jinghe*.exe`；`is_asset_url()` 是唯一判据，白名单外地址**零网络请求、零落盘**。大小上限 120 MB、下限 1 MB，尺寸与发布信息不符即判失败；`.part` 临时文件原子替换，失败清半成品。
  5. **安装目标唯一**：只允许替换**当前正在运行的可执行文件自身**（打包态 `sys.executable`）；外部传入的任意路径一律拒绝。源码模式下 `sys.executable` 是 `python.exe`，因此**直接拒绝自动替换**，绝不覆盖源码目录里的任何文件，只下载到「下载」文件夹并给出手动替换指引。
  6. **替换机制**：Windows 上运行中的 exe 被独占，无法就地覆盖——下载到同目录 `Jinghe.new.exe`，再派发脱离父进程的 PowerShell 脚本（`-EncodedCommand` + UTF-8 BOM，规避中文路径与引号转义）：等待本进程退出 → 备份旧文件 → 覆盖 → 启动新版 → 新版 4 秒内退出则**自动回滚**并重启旧版 → 清理暂存与备份。脚本变量用 `$targetPid`，**不得**用 PowerShell 只读自动变量 `$PID`。
  7. **诚实反馈**：离线、发布无安装包、下载中断、尺寸不符、替换失败，一律如实回显原因，**绝不谎报「已是最新」或「更新完成」**；无法自动替换时明确告知并给出手动路径。`up_to_date` 为 True / False / None 三态，None 表示无法比较（离线或版本号异常）。
  8. **UI 增量**：关于页「版本更新」卡片改为三格（检查更新 / 当前版本 / 最新版本），查到新版本后出现「立即更新」与「取消更新」按钮，下载期间显示进度条与百分比，完成后提示「程序即将重启」。v0.3.9 清除的说明段、仓库链接、离线长文案**仍不恢复**；「最新版本」信息格是用户本轮明确要求的信息回显，不是旧版 UI 回潮。
  9. **assets 解析单点真源**：`_api_check_update` 的解析逻辑迁到 `self_update.check`，`app.py` 只保留字段形状，杜绝两处各写一套解析规则。
  10. 测试基线由 70 → **71 用例**（`test_43`）。按用户新要求修订 `test_30`（恢复「最新版本」格断言）与 `test_32`（assets 断言迁到 `self_update.py`、前端改为两步调用）；`test_06` / `test_11` / `test_34` / `test_38` 的冻结与空心位断言全部原样保留。

- **v0.8（2026-11-16 · v0.4.9 交互体验补齐）**：用户要求三件事——「检查更新」按实际给反馈并修复报错、首页加拖拽输入、已识别清单勾选预览；并明确**后续版本暂不自动上传 GitHub，等用户说上传再上传**。本轮由交互专家「顺滑」视角收敛信息架构，**§1 不变量一条未改**：
  1. **检查更新 GET 修复**：`ui/app.js::checkUpdate()` 原把 `{}` 当 body 传给 `api()` → 被判 POST → 命中后端 GET-only 端点的「未知接口」404。改为传 `undefined` 走 GET。契约锁：`api("/api/update/check", undefined, 20000)`；实测 GET 200 / POST 404。
  2. **关于页信息架构收敛**：取消「最新版本」信息格（用户改口「最新版本这栏取消」），最新版本只通过检查结果反馈。检查后三分支：已是最新 → `#toast` 轻提示「当前是最新版本」3 秒自动消失；有新版本且 `has_asset` → `checkUpdate` 内直接调 `startUpdate()`（无需二次点击）；离线/无资产/报错 → 如实回显、绝不谎报「已是最新」。v0.4.8 的「立即更新」按钮保留为下载入口与进度载体，不作为必需二次操作。
  3. **拖拽输入（新增后处理层，不动冻结内核）**：普通 Edge 页面拿不到 `File.path`，故新增 `POST /api/drop-files`——body 为文件原始字节、文件名走 query，流式写入 `%TEMP%/jinghe-drop-<pid>-<seq>/`，返回真实路径交 `/api/dry-run` 识别。安全边界：`basename` 清洗 + 非法字符替换防穿越、单文件 2GB 上限、同名序号去重、`pid` 归属 + 启动清扫死进程遗留 + atexit 兜底。前端 `setupDropZone()` 绑定 dragenter/over/leave/drop，点击框等价「打开」；接收完自动 `doPreview()`。
  4. **已识别清单勾选预览**：「预览分流」按钮从输入行移到 `.card-files` 标题栏右对齐；清单项加 `checkbox[data-file-idx]` 与「全选」联动，勾选后按钮只对选中文件预览（`doPreview(picked)`），零勾选提示「请先勾选要预览的文件」。因 extract.py 冻结 dry-run 仅输出 basename，在 `app.py::_dry_run` 后处理层用 `_build_name_path_map(inputs)` 为每个 item 补 `path` 字段（同名取首次，属可接受近似），**不改 extract.py 主流水线一行**。
  5. **发版流程变更（用户明确）**：本轮及后续版本**不自动上传 GitHub、不推 tag**，打包 exe 仅供本地查看；等用户明确说「上传」才推。上一轮 E2E 临时发布 v0.4.9 与本地临时脚本须在本轮清理，避免污染版本来源。
  6. 测试基线由 71 → **72 用例**（`test_44`）。按用户新要求修订 `test_30` / `test_43`（最新版本格由「断言存在」改为「断言已移除」）、`test_31`（离线仍单独处理）、`test_32`（CHANGELOG 版本条目）；`test_06` / `test_11` / `test_34` / `test_38` 的冻结与空心位断言全部原样保留。

- **v0.8.1（2026-11-16 · v0.4.9 交互打磨，用户选「先打磨当前交互」）**：静态审视三条交互链路后修复 4 处真实缺陷，**§1 不变量一条未改、版本号不变（仍未推送）**：
  1. **勾选预览不再重建清单**：`doPreview(forcedInputs)` 子集预览时只更新 inputMeta 统计反馈，**跳过 `renderFileList(r)`**——预览是只读盘点，不得拿选中子集覆盖「已识别清单」导致未勾选文件消失、勾选态归零。新增 `isSubsetPreview` 判据；顺带删除被覆盖而成死代码的 `renderBuckets()`。
  2. **更新任务门闩**：`updateRunning` 布尔量——`startUpdate()` 置位、`finishUpdate()` 与启动失败 catch 复位；`checkUpdate()` 开头若门闩已置位只弹「正在更新中」轻提示，杜绝更新中重复点检查更新触发第二个任务。检查开始时 `hideUpdateProgress()` 清掉上次残留进度条。
  3. **拖拽整页防护**：`setupDropZone()` 在 document 级拦截 `dragover` / `drop` 默认行为，防止文件拖到框外被 Edge 直接打开而跳出应用（zone 自身的 drop 处理仍在冒泡阶段正常执行）。
  4. 测试基线由 72 → **73 用例**（`test_45`），独立锁定以上打磨点；`test_06` / `test_11` / `test_34` / `test_38` 冻结断言原样保留。

- **v0.8.2（2026-11-16 · 本机工具就绪 + 探测超时修正）**：用户要求「之前需要下载的相关组件全部下载」，在本机装齐三工具，**不改软件「不下载/不打包/不自动安装」的契约**——只是代用户在本机提供，工具仍在软件外部：
  1. **安装清单**：ffmpeg + ffprobe（BtbN win64-gpl 静态构建，含两者）、openai-whisper CLI（提供 `whisper <file> --model/--task/--output_format json/--output_dir` 接口）、yt-dlp（S5 预留）。装在 `%USERPROFILE%\jinghe-tools\` 与本机 Python Scripts，加入用户 PATH；whisper 模型权重**不预下载**（首次转写时由 whisper 自行准备，符合「模型不下载不打包」约定）。
  2. **torch 版本裁决**：官方最新 `torch 2.15.0+cpu` 依赖精简系统缺失的 `VCRUNTIME140_THREADS.dll`，加载失败；降级 **torch 2.6.0+cpu** 后 `import torch` / `import whisper` 正常。不修改系统 VC++ 运行库、不往 torch/lib 塞 DLL。
  3. **探测超时（关键修复）**：whisper 启动 import torch + numba 实测 6–8s、yt-dlp 首次启动也慢，原统一 `DEFAULT_TIMEOUT=2.0` 会把「已装好」误判「未启用」。`media_tools.py` 新增 `PROBE_TIMEOUTS={"whisper":15.0,"yt-dlp":10.0}`，`_adapters()` 按工具名覆盖；**TOOL_SPECS 三元组结构与 capabilities() 占位清单不变**（S1 契约锁死）。仍真跑探测命令、超时仍诚实标未启用，只是给足重依赖 CLI 启动窗口。
  4. **验收**：冻结态 exe 实起 `/api/tools/probe?refresh=1`，ffmpeg/whisper/yt-dlp 三项 `available=true`；`audio_transcribe` / `video_transcribe` 均 `enabled=true, capability=available, missing=[]`。全量 73 用例 + 门禁 9 项全绿；`test_33` 扩展断言 per-tool 超时与三工具结构。

- **v0.8.3（2026-11-16 · 首页 UI 可访问性审查修复）**：用 `ui-ux-pro-max` 对首页做系统审查并**量化核对**（对比度实算 + 焦点规则清点 + 标签检查 + 动效检查），修 4 类问题，**§1 不变量一条未改、冻结内核零改动**：
  1. **焦点可见性（WCAG 2.4.7）**：审查发现全站仅 2 处 `:focus`，且 `.drop-zone` / `.text-input` 直接 `outline: none` 却不给替代 → 键盘用户无法定位焦点。修法：统一 `:focus-visible` 焦点环（鼠标点击不显示、Tab 显示），`outline: 2px solid #185FA5` + `outline-offset: 2px`（不用 box-shadow，不影响布局、不被裁切），环色对白底 6.52:1（≥3:1 非文本门槛）；输入框额外内发光。**所有 `outline:none` 一律移除**，由 `test_46` 逐行正则清点锁死。
  2. **可见文字对比度（WCAG 1.4.3）**：占位符 `#9A9890` 对白底仅 **2.89:1**；另有 `.feature-btn.is-soon`、`.file-empty`、`.card-sub`、`.set-text em`、`.side-foot`、`.drop-zone small` 共 6 处同色可见文字同样不合格。统一改 `#6F6D66`（白底 5.18:1 / `#FAFAF8` 4.63:1 / `#FBFAF7` 4.63:1），仍弱于正文 `#1F1F1D`（16.51:1）以保留层级。**只改文字色，不动边框/背景色**（那些是装饰，不适用 4.5:1）。
  3. **输入标签（WCAG 3.3.2）**：`#inputPath` / `#outPath` 只靠 placeholder → 补 `aria-label`；拖拽框 `role="button"` 补可访问名称。设置页输入框本已隐式关联 `<label class="set-row">`，**不动**。
  4. **动效降级（WCAG 2.3.3）**：补 `@media (prefers-reduced-motion: reduce)`，过渡压到 **0.01ms**（而非 none，保留 `transitionend` 触发，避免依赖过渡完成的脚本失效）；另给 `.btn` / `.nav-item` / `.link-btn` 补 **160ms** 过渡（skill 建议窗口 150–300ms）。
  5. **已知取舍（不修）**：`.file-list` 空态↔列表切换会有布局跳动（右侧独立卡片，不挤压主内容），强制固定高度会让空态出现大片空白，**判定为可接受不动**。
  6. 测试基线由 73 → **74 用例**（`test_46`，含对比度实算断言：正文/次级/主色/成功/错误各 ≥4.5:1、焦点环 ≥3:1）。

- **v0.8.4（2026-11-16 · S7a 精读/修订能力地基，用户放行但停在 S7a 闸门）**：
  1. 新增 `refine.py` 独立 handler——精读（提纯核心）/ 修订（补写+修改，新增/修改须样式区分）两阶段地基；只做能力声明、ollama 探测、来源只读检查、诚实降级，**真实推理留 S7b/S7c，S7a 调用显式拒绝、零伪文档**。
  2. ollama 探测独立挂 `refine.capability()['tools']['ollama']`，**绝不进 TOOL_SPECS / capabilities()**（S1 契约锁死 3 工具 + 占位清单）；真实状态走 `/api/tools/probe` 顶层增量字段 `refine`。
  3. 六个增量端点：`POST /api/refine/inspect|start|cancel`、`POST /api/revise/start`、`GET /api/refine/status|models`；缺工具/空输入诚实拒绝，**不改 `/api/summarize` / `/api/transcribe` 等既有端点**。
  4. 双产物契约声明：`.refine.md`（精读）+ `.revise.md`（符号标记）+ `.revise.html`（彩色样式）；产物只落 `out/derived/`，冻结对账盘只读。S7a 只声明不渲染。
  5. 测试基线 74 → **75 用例**（`test_47`）；冻结态实测 probe 顶层 refine + 新端点可用、缺工具诚实降级；SPEC.md / extract.py 零改动。

- **v0.8.5（2026-11-16 · S7 后端裁决改为方案 C 可插拔多后端，用户确认放行）**：原 S7 契约「本机 ollama 单后端」作废（用户连续追问体积/带宽后改定），改为 **方案 C**：
  1. **统一 `Backend` 接口**（probe/list_models/chat）+ 两实现：`LocalBackend`（ollama `localhost:11434`，内容不出本机）、`CloudBackend`（客户填 OpenAI 兼容端点 + key，内容外传）。两者共用 `/chat/completions` 协议。B 方案 = C 选 CloudBackend，C 自动覆盖 B。
  2. **客户自选、零强制**：只配云端=零膨胀（软件本体恒 9MB）、只配本地=客户自己装 ollama+模型、两者都配=运行时切换；软件不下载/不打包/不自动安装任何组件；未配置=未启用（与 S7a 诚实降级一致）。
  3. **密钥安全**：后端配置独立存 `%LOCALAPPDATA%\Jinghe\backend.json`，**不放 settings.json**（后者被 /api/settings 明文回显 + 可被日志导出触及）；读端点 api_key 脱敏回显、写端点空值不改、绝不进日志/provenance/产物/异常堆栈。
  4. **隔离不变**：后端探测走 `/api/tools/probe` 顶层 `refine` 的 `backend` 子结构，**绝不进 TOOL_SPECS**（S1 锁死 3 工具）。
  5. 隐私条款改为「随后端而定」：Cloud 需客户配置即知情同意；新增风险登记「密钥泄漏」由 test_48 锁定。

- **v0.8.6（2026-11-16 · S7b 可插拔后端适配层落地）**：
  1. 新增 `backend.py`：`Backend` 统一接口（probe/list_models/chat）+ `LocalBackend`（ollama `localhost:11434`，GET /api/tags 探活）/ `CloudBackend`（客户端点 + Bearer key，GET /models 探活），共用 OpenAI 兼容协议。`chat()` 真推理显式 NotImplementedError（S7b 后半接入）。
  2. **密钥安全**：独立 `backend.json`（隔离 settings.json）；`mask_key` 脱敏、public_config 只回显掩码、save_config 空 key 保留原值、backend.py 内部零日志；test_48 用隔离 LOCALAPPDATA 验证落盘有真 key（设计预期）但**回显/日志/app.log 零泄漏**。
  3. `refine.py` 探测改走 `backend.probe_current()`，顶层 `refine.tools` 子结构由 `ollama` → `backend`（kind 三态 none/local/cloud，缺配置诚实降级）。
  4. app.py 新增 `GET/POST /api/refine/backend`；POST 回显走 public_config 不回显真 key。
  5. 测试基线 75 → **76 用例**（test_48）；修 `_LOCK` 非重入自死锁（save_config 锁内不再调 load_config）。冻结态实测脱敏全绿；SPEC.md / extract.py 零改动。
  6. 停在 S7b 适配层闸门；真推理产出（精读 .refine.md）+ 修订双产物 + UI 留后续阶段。

- **v0.8.7（2026-11-16 · S7b 后半精读提纯引擎落地，mock 验证）**：
  1. 新增 `refine_engine.py` 纯函数（split_blocks / build_prompt / parse_points / render_md / provenance 读写）。**反编造机制**：模型只返回带块号的 JSON 核心，每条 block 必须 ∈ 1..N 且为整数，否则丢弃；全无效 → 零产物（不写空壳）。
  2. 产物 `out/derived/<doc_id>.refine.md` = 8 字段 src 注释 + 三区块 + 每条 `block_anchor`；独立 `provenance_refine.json` 读旧追加（与 provenance_media.json 分离，避免污染音视频 schema）；冻结快照 before/after 比对保护 §3.F。
  3. refine.py 轻量任务状态（模块级 `_TASK` + 锁 + 线程，不依赖 app.py Job）：start_refine(path, model, outdir) / status(since) / cancel；线程 finally 清 running；后端调用走 Backend.chat()，mock 可完整验证。
  4. 诚实边界写进产物："块号有效≠内容出自该块"，标注请核对，不宣称零幻觉。
  5. 测试基线 76 → **77 用例**（test_49）；冻结态实测端点形状 + 空输入诚实降级；SPEC.md / extract.py 零改动。
  6. 停在 S7b 闸门；真模型质量验证待用户环境，后续 S7c 修订双产物、S7d UI、S7e 收口。

- **v0.8.8（2026-11-16 · S7c 修订双产物落地，mock 验证，用户放行上传）**：
  1. 新增 `revise_engine.py`：parse_core（anchor 与来源块号须一致）/ build_prompt / parse_changes（block 有效 + type 合法 + modify 的 old 匹配原文，否则丢弃）/ render_both / verify_marks。
  2. **双产物同源渲染**：单一真源=changes，`.revise.md`（`[++ 新增 ++]` / `[[~~ 旧 ~~ → 新]]`）+ `.revise.html`（内联 style 彩色）均由 changes 渲染；交付前 `verify_marks` 逐条校验两份产物标记，篡改任一即零产物（杜绝"改了没标记"）。
  3. WCAG AA 颜色：新增 `#1F6B3B` on `#EDF7F0`、修改旧 `#A32D2D` 删除线、修改新 `#185FA5`、原文 `#1F1F1D`，test_50 实算 ≥4.5:1。
  4. refine.py 的 start_revise 接 `_run_revise_inner`（doc_id 从 refine 文件名提取，与精读同 id），provenance stage=revise 读旧追加，冻结快照比对。
  5. 测试基线 77 → **78 用例**（test_50）；冻结态实测端点 + 产物声明；SPEC.md / extract.py 零改动。
  6. 停在 S7 收尾：S7d UI（导航两项 + 配置页 + 双产物预览）、S7e 收口；真模型质量验证待用户环境。

- **v0.8.9（2026-11-16 · S7d UI 接入落地，用户放行，本次不上传）**：
  1. 导航新增「精读」「修订」两项 + 两页面容器 + PAGE_META/pages 映射；设置页新增精读后端配置区（类型/端点/key/model，key password+脱敏+留空不改，云端知情同意）。
  2. 精读页（源 md + 模型 + 开始/取消 + 进度 + 结果预览）、修订页（refine.md + 指令 + 双产物预览：iframe srcdoc sandbox 彩色 + details 符号 md）。
  3. 新增只读端点 `GET /api/refine/artifact`（derived/ 内 + .md/.html + realpath 防穿越）与 `POST /api/refine/open`（独立，**不改 /api/open v0.4.0 白名单契约**）；JS 的 GET 一律传 undefined、status 走 since 增量轮询。
  4. 测试基线 78 → **79 用例**（test_51，含 artifact 安全边界与既有可访问性断言不回退）；Edge headless DOM 实测新 UI 元素出现；SPEC.md / extract.py 零改动。
  5. 停在 S7d 闸门；S7e 收口与上传待用户指令。真模型质量验证仍待用户环境。

- **v0.8.9（2026-11-16 · S7e 工程化收口，契约定稿）**：S7 五阶段（立项/S7a/S7b/S7b后半/S7c/S7d）全部落地并逐阶段验收；收口复核冻结内核零改动、零依赖、单文件、3 工具占位锁死、既有端点不变、产物只落 derived；全量 79 用例 + 门禁 9 项 + 冻结态 + Edge DOM 全绿。验收报告 `docs/S7-精读修订验收.md`。软件版本仍 v0.4.9（与规格版本双轨，不互推）。停在 S7e 闸门：本轮 UI 未上传 GitHub，是否推送由用户决定。

- **v0.9.0（2026-11-16 · 软件升号 v0.5.0 并上传，契约定稿）**：用户明确「升号」——S7 精读/修订为全新能力（5 子阶段、10+ 新文件/端点），按语义化版本 minor 由 v0.4.9 升 **v0.5.0**（软件版本），规格版本 `SPEC.md` v2.11 冻结不变，双轨不互推。版本真源 `extract.py::__version__` 与 test_44 断言同步更新；CHANGELOG/契约/验收文档/使用说明版本头更新；历史注释里的 v0.4.9 留痕不改。上传按清理口径只保留最新 Release/tag。

- **v0.9.1（2026-11-17 · S8 可信提纯立项 + 抽取式引擎落地）**：用户诉求「核心提取、不能造假」+ 拍板「补写保留、增加补写开关」。
  1. **三档可信度分层**（S8 契约 `docs/S8-可信提纯立项与契约.md`）：A 可信提纯（抽取式，**架构级不造假**，默认）/ B 原文内改写（只用原文素材）/ C AI 补写（生成物，**无法保证不造假**）。
  2. **抽取式引擎** `extract_engine.py`：纯标准库（AST 校验无第三方）；二元组切词 + TF-ICF + TextRank + MMR + 领域词表/标题挖词 + 跨度冲突消解；输出「原文原句 + 关键词 + 锚点 + 评分与依据」。`verify_traceable` 逐条校验可逐字定位，对不上零产物。
  3. **模式与开关**：`mode=extract|llm`（默认 extract，零配置恒可用）；`allow_suppplement` **默认 false**；开启后补写独立分区「AI 补充（模型生成，请核对）」、`[AI ++ … ++]` 标记、**不声明块锚点**。
  4. **UI**：设置页增「提纯模式」+「允许补写」开关；抽取式模式置灰 LLM 字段并说明。
  5. 测试基线 79 → **80**（test_52）；顺带修 4 处环境脆弱性断言（隔离 PATH 验证降级路径、断言与实际探测一致、拒收场景独立 outdir）。SPEC.md / extract.py / TOOL_SPECS 三工具零改动。
  6. 停在 S8a 闸门；S8b（主线切换与 UI 收口）/ S8c（B 档原文内改写）/ S8d（C 档补写完整链路）/ S8e（收口发版）待续。

- **v0.9.2（2026-11-17 · S8b B 档原文内改写 + 修订分流落地）**：
  1. **B 档实现**（`extract_engine.py` §9）：术语归一（需共现证据，统一到高频写法，不产生新词）/ 要点合并去重（阈值判定，块锚点并列，原文用 ` ｜ ` 连接不重写）/ 结构重排 / 排版归一（**默认不做**，因改标点会破坏逐字定位，仅可选）。
  2. **B 档红线** `verify_no_new_content`：逐片段校验「每个片段都在原文」，忽略标点全半角差异；篡改即失败。
  3. **修订按 mode 分流**：extract → B 档（纯标准库、零依赖、架构级不造假）；llm → S7 补写+修改双产物。extract 模式绝不调 LLM。
  4. `parse_core` 兼容 S7/S8 两种精读产物格式，且只解析「## 核心知识点」区块（防误收文档信息区列表项）。
  5. 渲染按模式区分文案与统计；多块锚点用 `blocks:` 并列；capability 暴露 `engine.mode`；UI 两页副标题与控件随模式联动。
  6. 测试基线 80 → **81 用例**（test_53）；test_49/50 显式声明所守路径；全量 81 + 门禁 9 全绿 + 冻结态双链路实测通过。SPEC.md / extract.py / TOOL_SPECS 零改动。
  7. 停在 S8b 闸门；S8c（C 档补写完整链路与隔离分区收口）/ S8d（工程化收口）/ S8e（发版）待续。

- **v0.9.3（2026-11-17 · S8c/d/e 收口，契约定稿；软件升号 v0.6.0）**：
  1. **C 档补写隔离与开关生效**：`parse_changes(allow_suppplement=False)` 直接丢弃 add 类变更并计入 skipped —— 开关关闭即真的没有补写；开启时 md 独立「AI 补充（模型生成，请核对）」分区 + `[AI ++ … ++]` 专用标记 + html `ai-item` 样式 + 头部「本文件含模型生成内容」告知；补写**不声明块锚点**（不对应任何原文块）；`verify_marks` 追加**物理隔离**校验（补写不得出现在核心区）。
  2. **配色升级**：AI 补写改用警示红系 `C_AI_FG #501313` on `C_AI_BG #FCEBEB`（对比度 12.62:1，WCAG AA），与「修改」的蓝/红区分 —— 修改是对原文的调整，补写是原文之外的新增内容，性质不同。
  3. **验收报告** `docs/S8-可信提纯验收.md`（三档落地对照、关键裁决、验证矩阵、5 条风险）。
  4. 测试基线 81 → **82 用例**（test_54）；test_50 的 mock 显式声明补写开关开启（它守双产物同源渲染），补写开关关闭的契约由 test_54 守。
  5. 软件版本 v0.5.0 → **v0.6.0**（S8 全新能力线 minor 升号）；规格 `SPEC.md` v2.11 冻结未改（三套编号不互推）。
  6. 全量 82 + 门禁 9 项全绿；冻结态双链路实测 + Edge DOM 实测通过。SPEC.md / extract.py 主流水线 / TOOL_SPECS 三工具零改动。

- **v0.9.4（2026-11-17 · S8 缺陷修复收口，软件升号 v0.6.1）**：对 v0.6.0 做系统代码检测（静态审查 + 脚本实测复现），红线全部守住，修复以下缺陷并补回归用例：
  1. **密钥掩码不得覆盖真 key**：设置页回填掩码后再次保存，曾把掩码串当新 key 写入、真 key 永久丢失。现定稿：**空串**与**与当前掩码相同**两种写法都表示「未修改」，保留原 key（后端兜底）；前端提交前把掩码转空串（第一道防线）；主动换 key 不受影响。
  2. **保守布尔判定**：补写开关只认「明确为真」（真布尔 True / 1 / 字符串 "1|true|yes|on"），其余（含字符串 "false"）一律判关 —— 敏感开关宁可误关不可误开；配置与回显统一走 `backend._as_bool`。
  3. **关键词槽位消解按句分组**：候选词跨度必须是**真实命中位置**（句号 + 句内偏移），冲突判定只在同一句内进行；并采「更具体者优先」（完整概念名压过其内部短词）；全文只出现一次的二元组碎片不入关键词。标题挖词源由此恢复生效。
  4. **产物 doc_id 同链**：修订产物沿用精读产物的同一个 doc_id（`doc_A.refine.md` → `doc_A.revise.md`），与 LLM 路径口径一致，不再按 refine.md 内容哈希另算。
  5. **多块锚点可解析**：锚点正则兼容 `| blocks: 2,7`（B 档合并条目），`parse_core` 解析出完整块列表，链式处理不再静默丢核心。
  6. **B 档操作说明行**：由渲染层原生输出，不再靠调用方字符串替换（此前匹配串与实际输出不一致，replace 静默失效，该行从未出现在产物中）。
  7. **工程加固**：发版门禁的语法编译校验纳入 S7/S8 新增 5 个模块；抽取式路径补取消检查点；抽取式模式的模型列表接口改为透传诚实说明。
  8. **已知边界（不掩盖）**：LLM 模式真推理仍未接入（`chat()` 显式 `NotImplementedError`，由既有测试锁死），AI 补写真实环境不可用，排期后续阶段。
  9. 测试基线 82 → **83 用例**（test_55 缺陷回归）；软件版本 v0.6.0 → **v0.6.1**（补丁号，缺陷修复不涉能力变更）；规格 `SPEC.md` v2.11 冻结未改。

- **v0.9.5（2026-11-17 · S8 收口：LLM 真推理接入，软件仍为 v0.6.1）**：用户指令「2 开始」，补齐 S8 最后缺口——此前 `chat()` 是空心位、LLM 模式与 AI 补写开关在真实环境不可用。
  1. **两条真推理路径**：`LocalBackend.chat` 走本机 ollama 的 OpenAI 兼容 `/v1/chat/completions`（模型名空时从 `/api/tags` 取第一个，绝不编造）；`CloudBackend.chat` 走客户端点 `/chat/completions`。共用 `_http_post_json` / `_chat_content`，`stream=False`、`temperature=0.2`（提纯要稳定）。
  2. **安全与诚实**：`api_key` 只在 Bearer 头短暂进入内存；HTTP 异常**只报状态码**、不读 body/reason（防 key 回显）；空响应 / 形状不符 / 无有效正文一律报错，绝不返回空串冒充成功。基类 `Backend.chat` 保留 `NotImplementedError`（`kind=none` 未配置时诚实拒绝）。
  3. **配置边界不变**：mode=extract 仍为默认、恒可用、架构级不造假；LLM 需用户自行配置后端，软件不下载 / 不打包 / 不自动安装；大模型输出不保证逐字可回溯，UI 如实提示核对。
  4. **测试基线 84 → 85 用例**（test_57：Cloud Bearer + 端点 / key 不进异常 / 空响应拒绝 / Local ollama 模型回退 / 端到端 LLM 精读产出）；test_48 的「chat 抛 NotImplementedError」断言改为守基类未配置分支。
  5. 软件版本保持 **v0.6.1**（能力收口不单独升号，随下个发版节奏走）；`SPEC.md` v2.11 冻结未改，冻结主流水线与 TOOL_SPECS 三工具零改动。

- **v0.9.6（2026-11-17 · S5 视频链接 → .md 落地，软件仍为 v0.6.1）**：用户确认四项边界（域名不设限 / 规模默认 / cookie 只读 / 版权不纳入判断）后实施。
  1. **新增 3 个零依赖模块**：`link_guard.py`（URL 形状 + 逐跳 IP 校验，禁环回/私网/链路本地/保留/多播/未指定；DNS 重绑定预检锁定；重定向跳数上限）、`link_downloader.py`（本机 yt-dlp；cookie 文件只读引用不落盘；.part + 原子替换；下载后实际 URL 二次校验；超时/取消即清理）、`link_media.py`（批量编排，独立 `_MEDIA_JOB`，逐条成功/失败互不影响，复用 `video_transcribe.transcribe` 产出 S4 三区块）。
  2. **端点（增量）**：`POST /api/link/inspect`（只读预检，零下载）、`/api/media/run|status|cancel`；`/api/tools/probe` 顶层 `link_resolve` 字段。既有端点与 TOOL_SPECS 三工具零改动，`media_ready()` 仍恒 False。
  3. **DNS 重绑定诚实边界**：yt-dlp 自行解析 DNS，零依赖架构下无法在连接层固定预检 IP（改 host 会破坏 HTTPS 证书校验）。采用「预检逐跳校验 + 下载后实际 URL 二次校验 + 跳数上限」，覆盖绝大多数 SSRF；**残留重绑定窗口如实披露**，不假装完全消除。
  4. 测试基线 85 → **87 用例**（test_58 SSRF 红线、test_59 编排/端点/cookie/冻结不变量）；全量 + 门禁 9/9 + Edge DOM + 冻结态 exe 实测全绿。SPEC.md v2.11 与冻结主流水线零改动。

- **v0.9.7（2026-11-18 · S9 验收工具链：外部体检 + UI 视觉判分层，软件仍为 v0.6.1）**：用户要求引入 workbuddy-bench（腾讯官方 Agent 评测基准）的两件东西——① 用其 Office 子集给精核做外部体检；② 借鉴其 `VLMJudgeRunner` 给 UI 验收加视觉判分层。
  1. **外部体检**（`tools/bench_office_check.py`）：从 `tencent/workbuddy-bench` 的 Office v1.0 拉 `contract-extract-L3-014`（45 个混合素材 docx/txt/json/xlsx/pdf），精核实跑提取（40 成功 / 5 扫描件降级），把 bench rubric 的六个考察维度逐条映射到**产物中确实存在的证据**：来源标识、审计链、异常单列、非占位、上下文不丢、汇总一致 → **对齐 6/6**。**诚实边界**：bench 官方判分需 Docker 沙箱 + LLM judge + xlsx/json/pptx 产物，本报告不是官方分数，只认有据可查的证据。
  2. **UI 视觉判分层**（`tools/visual_check.py` + `tools/ui_rubrics.json`）：两层——**结构层**（Edge headless 取 DOM + 截图，做 id/文本/顺序/计数断言，纯 Python 零依赖，必做）与**视觉层**（把截图交给**已配置的多模态后端**判分，复用 `backend.py` 既有 OpenAI 兼容 `chat()`，messages 原样透传即多模态，**不引入新依赖、不新增凭据通道**；未配置时**诚实跳过**并写明原因）。守 bench 两条原则：保守合取（多判据取 min）、有据才给分。
  3. **首跑即抓到两处真实不一致**：① 关于页旧「运行日志」卡片标题断言过粗（误伤主页面同名 tab）→ 断言改精确；② 功能路线卡片仍把已交付的 Word 导出标「规划中」→ **顺手修正（P-2）**，并补上视频链接提取 / 精读修订两项真实进度。
  4. 测试基线 87 → **88 用例**（test_60）；另修 test_56 的**写死日期脆弱断言**（2026-11-18 实测跨天变红，改为相对日期基准）。全量 + 门禁 9/9 全绿；SPEC.md 与冻结主流水线零改动。

- **v0.9.8（2026-11-18 · 双端并行合并，软件仍为 v0.6.1）**：另一终端经 GitHub 连接器提交了 S9 阶段 4 知识库（`85feb75`：`kb.py` 461 行 + `test_kb.py` 195 行 + app.py 四端点 + 立项对账文档），本地同时有 S9 验收工具链（`2f74bb9`）。
  1. **合并对账**：双方各 1 提交，**仅 `app.py` 一个文件重叠**，Git 自动合并**零冲突**（0 冲突文件）；知识库只新增端点与 import，不改既有路由。
  2. **合并后验证**：test_app 60 + test_extract 28 + **test_kb 16** = **104 用例全绿**，门禁 9/9；冻结文件 `SPEC.md` / `extract.py` / `test_extract.py` / `audio_transcribe.py` / `video_transcribe.py` / `media_tools.py` **零改动**。
  3. **知识库红线核验**（读源码确认）：纯标准库（sqlite3 + json + re + hashlib）、正交只消费已产出 md、每条条目带 doc_id + 块锚点 + 来源文件 + sha256（可回溯）、只重组不生成新内容（不造假）、`[AI ++ … ++]` 条目默认不入库（AI 补写隔离）、入库与打开均走路径围栏白名单。方向定为**关键词检索（trigram 主 / LIKE 降级）**，与用户此前询问的「B 归类标签检索」一致，未引入向量库或第三方依赖。
  4. **工程化补齐**：门禁纳入 `kb.py` 语法校验；CI 测试步骤改为 `python -m unittest -v test_extract test_app test_kb`（此前 test_kb 不在 CI 内跑，等于新能力无 CI 守护——本次补上）。
  5. **双端协作教训留痕**：两端口同时用 GitHub 连接器写同一仓库时，**git 层面能零冲突合并**（改动面不重叠时），但**CI 覆盖与门禁清单容易漏**——新模块若不进 CI，绿灯是假的。本次已补。

- **v0.9.9（2026-11-18 · S6/S9 收口发版，软件升号 v0.7.0）**：用户指令「将远端新版下载、合并本地领先内容、上传 GitHub」。合并态 `main` 已含远端知识库 + 本地验收工具链，版本由 0.6.1 升至 0.7.0（首个含阶段 4 的 minor 版本）。测试基线 88 → **104 用例**（新增 test_kb 16），CI 纳入 test_kb、门禁纳入 kb.py。全量 + 门禁 9/9 全绿；SPEC.md v2.11 与冻结主流水线零改动。tag v0.7.0 + Release 由 CI 自动构建发布，按清理口径保留最新 Release/tag。

- **v1.0.0（2026-11-19 · S10 手动下载护栏 + 假绿灯收口，软件仍为 v0.7.0）**：用户六项裁决落地。① 按「更新前必检 GitHub 版本」规则首检，远端领先 2 提交（S10 组件管理 `fee83ee` + kb 打包修复 `b8ff978`），fast-forward 拉取后本地/远端同步。② **软件绝不主动下载**：`components.py` 加一次性手动点击令牌 `_require_opt_in`，下载与 pip 安装前强制校验，探测路径零下载；UI 文案明确「软件绝不自动下载，只有手动点启用才下载」。③ 三工具不进 exe（`build.spec binaries=[]`，hiddenimports 仅 Python 模块）、不进 Release、不随 GitHub 上传，只装 `%LOCALAPPDATA%/Jinghe/components`。④ **修复假绿灯**：新增 `test_components.py`（9 用例，锁令牌/不打包/门禁 CI 覆盖），纳入门禁语法校验与 CI 测试步骤。⑤ 双向功能对账：本地与远端模块集合完全一致，无遗漏。全量 **113 用例**（60+28+16+9）+ 门禁 9/9 + 冻结态 exe 实测全绿；SPEC.md 与冻结主流水线零改动。

- **v1.0.1（2026-11-19 · 双终端版本契约 + C 方案窗口锁定，软件仍为 v0.7.0）**：用户三项裁决。① **机器可读版本契约**：新增 `version-policy.json`（版本真源/升号规则/协作铁律，机器可解析）+ `VERSIONING.md`（人可读）+ `tools/version_check.py`（三模式：before-change 改前检查 / for-upload **上传前硬门禁：本地版本必须严格大于 GitHub latest，同版本或离线一律 BLOCK** / suggest 按改动类型算号）。此机制确保另一终端凭版本号即可识别代码变更并拉取。② **C 方案窗口**：确认 `app.py::open_window` 已是 Edge `--app=` 模式（无地址栏/标签页，像原生窗口），补 test_61 锁定不被回退。③ **B 方案体积实测**（仅讨论未实施）：本机无 WebView2 运行时、无 tkinter；随包带 WebView2 bootstrapper +2~3MB（首次仍联网装 100MB+ 运行时），tkinter 路线 +5~8MB 且要重写 162KB 的 UI 并视觉降级。结论维持 C。全量 **114 用例**（61+28+16+9）+ 门禁 9/9 全绿；SPEC.md 与冻结主流水线零改动。

- **v1.0.2（2026-11-19 · 一键升号工具，软件升号 v0.8.0）**：用户裁决「本地每次改动都要升版本号，防止与远端同号导致无法上传」。新增 `tools/bump_version.py`：按 `version-policy.json` 规则算号，**联网核对 GitHub latest，候选号 ≤ 远端则自动 patch +1 顶到严格大于**（数学上杜绝撞号）；一键同步 `extract.py` / `CHANGELOG.md` / `使用说明.md` 三个当前版本派生点；离线保守 +1 并提示人工确认；`--dry-run` 可预览。version-policy.json 增 `bump_tool` 声明。新增 test_62 锁住算号/防撞号/派生点/离线兜底，bump 工具纳入门禁语法校验。
  - **度的说明**：合理的保证是「每个待上传版本必须升号」（由 `for-upload` 硬门禁 + 本工具实现），而非「每敲一次代码就升号」（会导致版本号爆炸且无意义）。实测：当前本地 0.7.0 与远端 v0.7.0 撞号 → for-upload BLOCK；用工具 minor 升到 **0.8.0** 后三派生点自动同步、for-upload 放行。
  - 测试基线 114 → **115 用例**（62+28+16+9），门禁 9/9（识别 v0.8.0）全绿；SPEC.md 与冻结主流水线零改动。本地领先远端 3 提交，未上传。

- **v1.0.3（2026-11-19 · 修复冻结态组件安装 pip 退出码 2，软件升号 v0.8.1）**：用户实测「Whisper 点击启用报 pip 安装失败（退出码 2）」。
  - **根因**：PyInstaller 打包后 `sys.executable` 指向 `Jinghe.exe` 本身，exe 不内置 pip，`Jinghe.exe -m pip install ...` 被当成程序参数 → 退出码 2。源码模式用 python.exe 故从不复现，只在冻结态暴露。
  - **修复三处**：① 新增 `_python_for_pip()`：源码态用 `sys.executable`，冻结态改用 PATH 上真实 Python（找不到则诚实报错，不假装成功）；② 新增 `_pip_cmd_install()` 显式判断代理值——旧代码 `if not cmd[-1]: cmd=cmd[:-2]` 永远为 False（末项是常量），无代理时仍传 `--proxy ""`；③ `_scripts_dir()` 冻结态改用真 Python 的 Scripts 目录（否则 pip 装完 whisper.exe 仍探测不到）；④ pip 失败时回显真实 ERROR 行，而非光秃秃的「退出码 2」。
  - 回归 `test_components.py` 新增 6 用例（源码/冻结解释器选择、找不到 Python 报错、空代理、有代理、Scripts 目录），9 → **15 用例**。冻结态 exe 实测版本/探测/无自动安装全绿。
  - 全量 **121 用例**（62+28+16+15）+ 门禁 9/9；SPEC.md 与冻结主流水线零改动。按规则先升号 patch 0.8.0 → 0.8.1，未上传。

- **v1.0.4（2026-11-19 · 关于页精简，软件升号 v0.8.2）**：用户两项 UI 裁决。① **删除系统信息卡片里的「软件版本」字段**——版本更新卡片已有「当前版本」，两处重复；同步移除 `ui/app.js` 的 aboutVersion2 引用与赋值。② **删除「功能路线」卡片**——它是写死在 HTML 的静态进度展示，内容早已过时（阶段 4 知识库已实现却标「规划中」），职责由 CHANGELOG/文档承担；同步移除 CSS（`.road-list`/`.road-tag`）与 test_59 的旧守护断言（改为断言卡片已移除）。UI 视觉判分层 25/25 仍绿。全量 **121 用例**（62+28+16+15）+ 门禁 9/9；SPEC.md 与冻结主流水线零改动。按规则升号 0.8.1 → 0.8.2，未上传。

- **v1.0.5（2026-11-19 · 导航栏固定 + 澄清「删除未生效」假象，软件升号 v0.8.3）**：用户反馈「刚删的两处还在」——排查发现**删除其实已生效**：磁盘文件与新版 exe 里两处均为 0 处，真正原因是**旧 exe 进程（PID 13828，11:28 启动）仍占着 54321 端口**，单实例保护下双击新 exe 只会把旧窗口切前台，看到的是旧页面。停掉旧进程、起新 exe 后实测页面两处已删。
  - **导航栏固定**：原布局 `.app{min-height:100vh}` 导致整页滚动、侧栏跟着跑。改为桌面应用双栏独立滚动：`.app{height:100vh;overflow:hidden}` + `.content{height:100vh;overflow-y:auto}` + `.sidebar{position:sticky;top:0;height:100vh;overflow-y:auto}`。test_63 锁定三处 CSS。
  - 新 exe 实测：页面两处已删、三处 CSS 生效；Edge DOM 视觉判分 25/25。全量 **122 用例**（63+28+16+15）+ 门禁 9/9；按规则升号 0.8.2 → 0.8.3，未上传。

- **v1.0.6（2026-11-19 · exe 带版本号 + 导航栏底部精简，软件升号 v0.8.4）**：用户五项裁决。① **exe 对外产物改名带版本号**：`build.py` 打包后按 `__version__` 自动重命名为 `dist/Jinghe-0.8.4.exe`，PyInstaller 内部仍产出 `Jinghe.exe`（保自我重入 `--cli` 契约）；CI 上传 `Jinghe$tag.exe`，门禁 glob 匹配 `Jinghe-*.exe`，自更新 `Jinghe*.exe` 前缀白名单天然兼容；本地只留带版本号那份（用户选择）。② **导航栏底部**：删 `sideVersion` 版本号（含 JS 两处赋值）、品牌「精」→「精核」（字号调小适配方块）、侧栏 `overflow-y: hidden` 去滚动条。test_64 锁定命名与布局契约，视觉判分 26/26。全量 **123 用例**（64+28+16+15）+ 门禁 9/9；冻结态 exe 实测 UI 五处全绿；SPEC.md 与冻结主流水线零改动。按规则升号 0.8.3 → 0.8.4。

- **v1.0.7（2026-11-19 · 修复侧栏底部横向滚动条，软件升号 v0.8.8）**：用户反馈「左侧导航栏最下面左右滑动条还在」。排查发现 v0.8.7 进程虽是新版、CSS 已是 `overflow-y:hidden`，但**用户说的是横向（左右）滚动条，上次只改了纵向**。
  - **根因（经典 CSS 陷阱）**：CSS 规范规定 `overflow-y:hidden` 时默认的 `overflow-x:visible` 会被**隐式计算为 `auto`**；`.nav-resizer` 拖拽手柄 `right:-3px` 恰好制造 3px 横向溢出 → 底部冒出横向滚动条。
  - **修复**：`.sidebar` 显式加 `overflow-x: hidden`（双轴都 hidden）；`.nav-resizer` 从 `right:-3px` 改为 `right:0`（贴边，7px 热区仍在）。test_65 锁定两处防回退。
  - **CDP 浏览器实测**（不再靠 CSS 推理）：`.sidebar` scrollWidth=183 = clientWidth=183、scrollHeight=487 = clientHeight=487、overflowX/Y 均 hidden、**横纵溢出皆 false**。证据确凿。
  - 全量 **124 用例**（65+28+16+15）+ 门禁 9/9 + 视觉判分 26/26；按规则升号 0.8.7 → 0.8.8，未上传。

- **v1.0.8（2026-11-19 · 折叠按钮位置固定，软件升号 v0.8.9）**：用户反馈「折叠按钮展开/折叠时位置变化，希望与下方功能按钮对齐不动」。
  - **CDP 实测根因**：图标 x 两态恒为 20（本就不动）；按钮 x 展开 10 → 折叠 15.5（跳 5.5px）。折叠态因 `.app.nav-collapsed .side-top{justify-content:center}` 使按钮中心对齐，但展开态按钮 `space-between` 左缘贴边 → 两态基准不一致。
  - **修复**：删掉折叠态居中覆盖；`.side-top` 固定 `padding-left:10px` + `justify-content:flex-start`（左内边距 10 + 侧栏 10 = 20px，与 `.nav-item` 图标左缘同一基准）。
  - **CDP 复测**：按钮 x 展开 20 → 折叠 20（位移 **0px**），图标 x 恒定 20，按钮与图标左缘偏差 **0px**（两态严丝合缝）。新增 `tools/_cdp_nav_probe.py` 供以后实测，test_66 锁定 CSS 契约。
  - 全量 **125 用例**（66+28+16+15）+ 门禁 9/9 + 视觉判分 26/26；按规则升号 0.8.8 → 0.8.9，未上传。

- **v1.0.9（2026-11-19 · 修组件安装找不到 Python，软件升号 v0.8.10）**：用户点 Whisper 启用报「冻结模式下未在本机 PATH 找到 Python」。
  - **体积答复**：Whisper 全套约 **644 MB**（torch 464 + llvmlite 116 + numpy 31 + numba 26 + whisper 本体仅 2 MB），必须联网下载，无法打包进 exe——这正是「本机可插拔工具」策略的原因。
  - **根因**：本机 Python 装在 workbuddy 私有目录，用户 PATH **只含 `...\3.13.12\Scripts`（whisper.exe 所在）**，不含 `python.exe` 所在的父目录 → 旧实现 `shutil.which("python")` 必然失败。用户从桌面双击 exe 继承的就是这份 PATH。
  - **修复**：`_python_for_pip()` 改多策略查找：① PATH 直接找 ② **从 PATH 里的 Scripts 反推父目录**（本机真实布局，关键）③ 从已装 CLI 反推 ④ 常见安装位置；全部失败才报错，且错误明示体积与三条可操作指引（勾 Add to PATH / 手动 pip install / 加 python.exe 目录到 PATH）。
  - 新增 `test_scripts_parent_fallback` 回归（15→16 用例），`no_python_raises` 升级为屏蔽全部策略并断言提示含体积与指引。冻结态模拟实测：找到 `...\3.13.12\python.exe`、跑 pip 退出码 0。
  - 全量 **126 用例**（66+28+16+16）+ 门禁 9/9；按规则升号 0.8.9 → 0.8.10，未上传。

- **v1.1.0（2026-11-19 · 版本号进位规则：每段上限 9，满 9 进位归零，软件升号 v0.9.0）**：用户裁决「小数到 10 时自动进一位，小数位变为 0，如 0.7.9 → 0.8.0」。
  - **规则落地**：`bump_version.py` 新增 `MAX_DIGIT=9` 与 `_carry()`——任一段超过 9 即向高位进 1、本段归 0（0.7.9→0.8.0、0.8.9→0.9.0、0.9.9→1.0.0）。`ensure_above_remote()` 撞号顶升同样走进位。
  - **消除双实现分叉**：`version_check.py suggest` 原有一套独立算号逻辑，改为**直接复用 bump_version.compute**（单一真源）。
  - **契约同步**：`version-policy.json` 增 `digit_rule` 段（max_digit=9 + 进位示例 + 「不会出现 0.7.10 这类号」），`bump_rules` 描述改写；`VERSIONING.md` 增进位说明与示例表。
  - **历史号修正**：0.8.10 是旧规则产物且尚未上传 → 按新规则修正为 **v0.9.0**（extract.py / CHANGELOG / 使用说明三处同步），故版本序列不会出现 0.8.10。
  - **不影响比较逻辑**：`self_update.version_tuple` 用数值元组比较，0.8.10 > 0.8.9 判断本就正确，无需改动。
  - 新增 test_67 锁定 8 组进位用例 + 撞号顶升 + 契约声明 + 「当前版本每段 ≤9」断言。全量 **127 用例**（67+28+16+16）+ 门禁 9/9；SPEC.md 与冻结主流水线零改动。
