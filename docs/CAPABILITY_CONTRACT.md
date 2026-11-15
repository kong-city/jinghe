# 精核 · 阶段 2/3 新能力契约（v0.1 · S0 草案）

> 立约日期：2026-11-15 · 状态：**v0.6 已生效**（S0/S1/S2a/S2b/S3/S4 已完成，停在 S4 闸门）
> 适用能力：Word 输入增强 / `.md` → `.docx` 导出 / 音频 → `.md` / 视频 → `.md` / 视频链接 → `.md`
> 代码基线：`extract.py` v0.4.1，CI 全绿，60 用例，9 项发版门禁
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
10. **每次修改后**：全量用例 + 9 项门禁 + 打包 exe + 上传 GitHub + 推版本 tag（用户长期规则）。

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
| **S5** 视频链接 → .md | 任意链接与播放列表、防 SSRF、重定向、m3u8/DASH、批量队列 | 恶意/越界 URL 被拒；取消即清理；单条失败不拖垮整批 | 等确认 |
| **S6** 工程化收口 | 测试矩阵、CI 可选依赖探测、门禁扩项、exe、push tag、Release 资产核对 | 全量用例 + 门禁 + CI 全绿；Release 带 exe | 最终验收 |

每阶段收尾按用户长期规则：全量用例 → 9 项门禁 → 打包 exe → 上传 GitHub → 推版本 tag → **停下等确认**。

---

## 9. 风险登记（S0 先挂账，不承诺消除）

| 编号 | 风险 | 处置 |
| --- | --- | --- |
| R1 | 外部工具版本差异导致输出漂移 | `converter` 字段记录版本；测试用 mock 后端，真实工具只做冒烟 |
| R2 | 平台解析涉及鉴权 / 版权 / 合规 | 不内置凭据、不绕过限制；S5 开工前再确认可接受范围 |
| R3 | 长任务资源占用与强杀残留 | §5 超时与三链清理；测试覆盖取消与临时目录 |
| R4 | 私有仓库导致匿名「检查更新」404（v0.4.1 遗留） | 与能力开发解耦，S6 单独决策（公开仓库 / 公开版本清单 / 只读 token） |
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
