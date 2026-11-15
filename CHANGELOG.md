# 更新日志

本文件记录「精核」软件版本的可感知变更。格式参照 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循语义化版本。

软件版本（`extract.py: __version__`）与 `SPEC.md` 的规格版本（v2.x）是两套编号，不要混淆。`SPEC.md` 为冻结的规格契约，不随本文件更新。

## [0.4.7] - 2026-11-15

**S4 · 视频 → `.md`**（阶段 3 二期）。新增**完全独立**的 `video_transcribe.py` video handler：ffmpeg 只读探测流信息 / 抽取音轨 / 机械导出内嵌字幕轨，本机 whisper CLI 转写音轨，产出**三区块齐备**（元数据 / 音轨转写 / 画面·字幕）的 Markdown。软件不提供 OCR / 视觉模型，**绝不编造画面语义描述**；不打包、不下载、不安装任何工具或模型。按「逐阶段确认」，S4 完成后停在闸门等确认，**不进入 S5**（视频链接 → .md）。

### Added

- `video_transcribe.py`（新）：`capability()` / `inspect()` / `transcribe()` / `probe_streams()` / `parse_srt()`；与 `audio_transcribe.py` **双向不依赖**（`test_41` 断言锁死），视频只认 `MEDIA_VIDEO`、音频只认 `MEDIA_AUDIO`，分类先于存在性与工具检查。
- 四个新端点：`POST /api/video/inspect` / `transcribe` / `cancel`、`GET /api/video/status?since=N`；`/api/tools/probe` 顶层新增 `video_transcribe` 字段。ffprobe 只是可选增强，**不进** `media_tools.TOOL_SPECS`（`probe.tools` 仍恰好 3 个工具）。
- UI 新增「视频提取 → .md」与「取消提取」按钮、独立 800ms 进度轮询；老的音视频转写占位按钮与 S1 诚实降级判定原样保留。
- 产物 `out/derived/<doc_id>.md`：元数据（时长 / 分辨率 / 帧率 / 视频与音频流 / 字幕轨数 / 工具版本 / sha256）、音轨转写（带 `HH:MM:SS.mmm` 时间戳与 `time` 锚点）、画面·字幕（真实导出的 SRT 条目，或「未检测到内嵌字幕轨 + 不生成画面语义描述」的客观状态）；8 字段 `src` + 块级锚点，`provenance_media.json` 读旧追加。
- ffprobe `-of json` 结构化元数据优先，探不到或解析失败自动回退 `ffmpeg -i` 文本解析，并在产物里写明「元数据来源」；`converter` 记录 whisper / ffmpeg（及 ffprobe）真实版本。

### Changed

- 契约升 **v0.6**：订正 v0.5「`/api/media/run` 留给 S4/S5」的漂移为「留给 S5 批量编排」；新增 10 条 S4 裁决（独立 handler、画面区块诚实实现、双门禁、长任务与进程树等）。
- 发版门禁编译列表与 PyInstaller `hiddenimports` 纳入 `video_transcribe.py`；启动时清扫 `jinghe-run-video-*` 孤儿临时目录。
- 测试基线 68 → **70 用例**（`test_41` / `test_42`）。

### 不变量

- 双门禁防伪产物：解析不出视频流元数据、或既无真实语音分段又无真实字幕条目，一律 `ok:false` + **零 md**，绝不写空壳三区块 / 占位正文。
- 缺工具（whisper / ffmpeg）诚实显示「未启用」且连 `derived/` 都不创建；产物只落 `derived/`，`out/md/` / `INDEX.md` / `MERGED.md` / `provenance.json` 全程只读。
- `/api/transcribe` 的 S1 空心位、`test_06` / `test_11` / `test_34` / `test_38` 全部原样保留；`SPEC.md` 与 `extract.py` 主流水线一字未改。

## [0.4.6] - 2026-11-15

**S3 · 音频 → `.md`**（阶段 3 一期）。用**本机可插拔** whisper CLI + ffmpeg 把音频转成带时间戳的 Markdown；软件本体仍是零第三方依赖的单文件 exe，模型与工具由用户在本机提供，不下载、不打包、不自动安装。按「逐阶段确认」，S3 完成后停在闸门等确认，**不进入 S4**（视频 → .md）。

### Added

- `audio_transcribe.py`（新）：`capability()` / `inspect()` / `transcribe()` 三层；只认 whisper 的 `--output_format json` **文件输出**（不读 stdout），`segments[].start/end/text` 解析成 `HH:MM:SS.mmm` 时间戳；ffmpeg 仅做 `-hide_banner -i` 只读容器时长探测。
- 产物 `out/derived/<doc_id>.md`：`# 标题` / `## 文档信息` / `## 音轨转写` / `## 转写元数据` 三区块，8 字段 `src` 来源注释 + 带 `time` 键的块级锚点（`<!-- anchor: doc_x | block: N | time: 00:00:00.000-00:00:08.240 -->`），`converter` 只写真实工具名与探测到的版本；`provenance_media.json` **读旧追加**，不覆盖 S2a / S2b 历史条目。
- 新端点 `POST /api/audio/inspect`（只读预检）、`POST /api/audio/transcribe`、`POST /api/audio/cancel`、`GET /api/audio/status?since=N`；`GET /api/tools/probe` 新增顶层增量字段 `audio_transcribe`。**`/api/transcribe` 的 S1 空心位原样保留**，S4 视频走独立 handler，不复用音频路径。
- 长任务链路：复用 S1 的 `Job`（事件总线 / `register_child` / `terminate_children`）与 `start_job_watchdog`，转写任务单独持有 `_AUDIO_JOB`，不污染阶段 1 的 `/api/progress` 事件队列；UI 提供「取消转写」按钮与 800ms 进度轮询。
- `media_tools.terminate_process_tree()`：whisper 会再派生 ffmpeg，取消时按 `taskkill /T /F /PID` 杀整棵进程树（POSIX 走 `killpg`），不再只杀外壳留孤儿。
- UI：后处理卡片新增「音频转写 → .md」与「取消转写」；缺工具时按钮显示「未启用」并给出安装提示，工具状态行追加音频能力；老的「音视频转写」占位按钮仍按 S1 诚实降级判定。

### Safety

- **绝不产出伪转写**：空分段 / 无语音 / 缺 `segments` / 非法 JSON / 无 JSON 输出 / 非 0 退出 / 缺工具，一律 `ok:false` + 可读原因，**零 md 产出**，也不生成「无语音」说明文档；缺工具时连 `derived/` 目录都不创建。非法时间段（NaN / 负值 / `end < start` / 超 99 小时）逐段丢弃并计数，绝不编造时间戳。
- **红线 2**：只认 `format_registry.MEDIA_AUDIO`，`.mp4/.mov/.mkv` 等视频后缀逐条显式拒收并提示「S4 独立 video handler」，且不沿用历史上名不副实的 `_STAGE3_AUDIO_EXT`（那是含全部视频的 `MEDIA_EXT` 并集）。
- 单文件 256 MB / 单批 50 个 / 单文件 900 秒超时；临时目录 `jinghe-run-audio-<pid>-<seq>` 走「父进程持有 → `finally` 删除 → `atexit` 兜底 → 启动清扫 24h 前孤儿」三链；`.part` 原子替换、失败清半成品；`md/` 实盘数与 `INDEX.md` / `MERGED.md` / `provenance.json` 全程只读，写前后 `frozen_snapshot` 比对。

### Tests

- 新增 `test_39` / `test_40`：伪转写五条路径、视频拒收、缺工具诚实降级、mock 后端中文真实样本（8 字段 / 锚点 / 时间戳 / 三区块 / 冻结盘隔离）、provenance 追加、取消收敛与进程树终止、HTTP 端点与 UI 接线、门禁与打包清单。测试基线 **66 → 68 用例**。

---

## [0.4.5] - 2026-11-15

**S2b · `.md` → `.docx` 导出**（阶段 2 二期）。放开界面上长期禁用的「导出 Word」占位按钮，用**纯标准库**生成真正可被 Word 打开的 `.docx`；`.md` 输入全程只读，产物落独立 `out/derived/`，阶段 1 冻结对账盘一字不动。按「逐阶段确认」，S2b 完成后停在闸门等确认，**不进入 S3**（音频 → .md）。

### Added

- `word_export.py`（新）：`zipfile` 组装 8 个 OOXML 部件（`[Content_Types].xml`、`_rels/.rels`、`word/document.xml`、`word/_rels/document.xml.rels`、`word/styles.xml`、`word/settings.xml`、`docProps/core.xml`、`docProps/app.xml`），不引入 python-docx / lxml / Word / LibreOffice，也不随 exe 分发任何外部工具。
- Markdown 映射：一至六级标题、普通段落、有序 / 无序列表、引用、围栏代码块、水平线、真实 `w:tbl` 表格，行内 `**粗体**` / `*斜体*` / `` `等宽` `` / `~~删除线~~` 拆成 `w:r`；所有文本做 XML 转义并剔除 XML 1.0 非法控制字符，中文字体固定 `Microsoft YaHei`。
- **出处不丢**：`<!-- source: … -->`、8 字段 `<!-- src: … -->`、块级 `<!-- anchor: … -->` 按原文渲染成 `SourceNote` 段落，`src` 原文同时写进 `docProps/core.xml` 的 `dc:description`；导出后可用 `word_input.parse_ooxml()` 反向读回，形成闭环。文档开头另有「导出信息」区块（源文件 / doc_id / sha256 / 大小 / 转换器 / 时间 / 溯源注释数）。
- 新增 `POST /api/word/export`：显式 `.md` 输入优先；未给时**只读**自动收集 `MERGED.md`，其次 `out/md/*.md`（上限 20 个）。产物 `out/derived/<doc_id>.docx` + `provenance_media.json`，`.part` 原子替换，失败清理半成品。
- `GET /api/tools/probe` 新增顶层 `word_export` 能力字段；`format_registry.py` 新增 `WORD_EXPORT_INPUT_EXTS` / `is_word_export_input()`；`build.spec` 与发版门禁编译列表纳入新模块。
- UI：「导出 Word」不再是禁用占位，接上逐条状态回显；工具状态行追加导出能力。混合批次部分成功显式提示「另有 N 项未处理」。

### Fixed

- `media_tools.capabilities()` 的注释订正：它是 S1 的**能力占位清单**，被 `test_33` 锁死为「全部未启用」，S2a / S2b 均不改写；已落地能力的真实状态由 `/api/tools/probe` 顶层增量字段给出。逻辑零改动，避免返回两个互相矛盾的字段被误读。

### Safety

- 单文件 8 MB / 2 万行上限；文件不存在、非 `.md`、空白正文、超上限、写入失败一律 `ok:false` + 可读原因，**零 docx 产出**；空输入连 `derived/` 目录都不创建。阶段 1 的 `out/md/`、`INDEX.md`、`MERGED.md`、`provenance.json` 全程只读。

### Tests

- 新增 `test_37` / `test_38`：OOXML 部件齐全且全部 XML 可解析、zip 无损坏、反向解析保留来源注释 / 锚点 / 中文与 `& < > " ' %` 特殊字符、对账盘零污染、自动输入、四条失败路径、部分成功 `warning`、provenance 保留历史条目、真实 HTTP 与 UI 契约。测试基线 **64 → 66 用例**，全量 OK。

---

## [0.4.4] - 2026-11-15

**S2a · Word → .md 输入增强**（阶段 2 一期）。在 S1 地基之上交付第一个真正面向用户的新能力：对所选 `.docx` / `.doc` 生成带批注、修订与加密识别的独立增强 Markdown。按「逐阶段确认」，S2a 完成后停在闸门等确认，**不进入 S2b**（`.md` → `.docx` 导出）。

### Added

- `word_input.py`（新）：纯标准库 `zipfile` + `xml.etree.ElementTree` 的 OOXML 增量解析 —— `word/comments.xml` 批注（作者 / 时间 / 锚定段落）、`w:ins` / `w:del` / `w:move*` / `w:rPrChange` 修订明细、标题与表格正文。零第三方依赖，不 import 也不改写 `extract.py`。
- `.doc` 旧格式的**本机可插拔预处理**：LibreOffice `soffice --headless --convert-to docx`，工具由本机提供，软件不下载 / 不打包 / 不自动安装；缺工具、探测失败、超时一律 `未启用` + 可读原因，**零 md 产出**。临时目录由父进程持有，`finally` + `atexit` + 启动过期孤儿清扫三链齐备。
- 加密正向证据识别：OLE 容器含 `EncryptedPackage` / `EncryptionInfo`、ZIP 成员加密位、加密信息成员一律单列 `待人工授权`，**绝不破译、不询问口令、不盲重试**；普通 `.doc` 的 OLE 头不会被误判为加密。
- 新增 `POST /api/word/inspect`（只读预检，不写任何文件）与 `POST /api/word/enhance`（写独立产物）。`GET /api/tools/probe` 新增顶层 `word_input` 能力字段，刻意不改写 S1 的 `capabilities` / `tools` 结构。
- 产物落 `out/derived/<doc_id>.md` + `provenance_media.json`：8 字段 `src` 来源注释、块级锚点、文档信息 / 正文 / 批注 / 修订四区块；`.part` 原子替换；失败项不落空文件、只在 results 与 provenance 留痕；部分成功显式回 `warning`。
- UI：「后处理 · 阶段 2/3」新增「Word 输入增强」按钮，选中 Word 文件即可用；`本机工具` 状态行追加 `.docx` / `.doc` 可用性与原因。
- 新增 `test_35_s2a_word_input_contract` / `test_36_s2a_word_http_and_ui` 两个契约用例；测试基线 62 → **64**。

### Changed

- `format_registry.py` 新增 `WORD_INPUT_EXTS` / `is_word_input()` / `word_kind()`，注册表仍是新能力支持格式的唯一写者。
- `build.spec` 的 `hiddenimports` 与 `tools/check_release.py` 的编译列表纳入 `word_input.py`。
- 契约升级 **v0.3**，新增 `docs/S2a-Word输入增强验收.md`。

### 不变

- `SPEC.md` 一字未改；`extract.py` 阶段 1 探测 / 分流 / 提取 / 汇总 / 对账主流水线零改动；`test_06` / `test_11` 原样保留；`/api/transcribe` 的诚实拒绝空心位原样保留；阶段 1 冻结对账盘（`out/md/`、`INDEX.md`、`MERGED.md`）只读。

## [0.4.3] - 2026-11-15

**S1 · 能力框架地基**（阶段 2/3 七阶段路线图第 1 阶段）。本版本**不含面向用户的新转换能力** —— 音视频转写仍是空心占位、绝不产出伪转写；S1 只把「以后每加一类格式就要在 7 个文件里手工对表」的地基浇好。按用户确认的「逐阶段推进」，S1 完成后停在闸门等确认。

### Added

- `format_registry.py`：格式注册表。`stage1` 部分是 `extract.py` 冻结常量的只读镜像，`media` 部分是新能力的唯一写者（含 `.m4v` 与 `.wmv` 并集）；提供桶判定、音视频归类、文件对话框过滤器派生与结构化视图。
- `media_tools.py`：`ToolAdapter` 统一接口与健康探测。本机 ffmpeg / whisper / yt-dlp 由用户自己提供，软件不下载、不打包、不自动安装；找不到工具、探测失败、超时一律 `available=false` + 可读原因，结果进程内缓存。`capabilities()` 如实标记 S2b / S3 / S5 尚未接入。
- `media_runtime.py`：独立产物区 `out/derived/` + `provenance_media.json` 骨架，以及 8 字段 `src` 来源注释 / 块级锚点生成函数，供 S2–S5 复用。
- `GET /api/tools/probe`：工具健康探测端点（支持 `?refresh=1`），响应含 `tools` / `capabilities` / `media_ready` / `derived`。刻意不挂到 400ms 轮询的 `/api/state` 上。
- `Job` 扩展：`deadline` / `timed_out` / `register_child()` / `terminate_children()` 与 `start_job_watchdog()`；取消时一并终止外部工具子进程。
- UI：「后处理 · 阶段 2/3」卡片新增本机工具状态行；能力未接入或缺工具时，音视频按钮显示「未启用」并禁用。
- 新增 `test_33_s1_registry_tools_and_derived` / `test_34_s1_probe_http_and_long_job` 两个契约用例。

### Changed

- `app.py` 的 `_FILE_FILTERS` 与 `_STAGE3_AUDIO_EXT` 改为从注册表派生，消除 S0 登记的 **D1**（`.m4v`/`.wmv` 两处集合不一致）与 **D2**（过滤器列出 `.rtf/.odt/.yaml/.ini` 等不支持格式）漂移。
- `tools/check_release.py` 门禁 ⑦ 的编译列表纳入 3 个新模块；`build.spec` 的 `hiddenimports` 同步。

### Notes

- **`SPEC.md` 与 `extract.py` 提取主流水线零改动**。契约要求的「`FORMAT_REGISTRY` 单一来源」与「冻结内核一行不动」存在张力，S1 的裁决是：**冻结内核为阶段 1 分流的只读真源，注册表为新能力的唯一写者，两者由一致性断言逐字锁住**，而不是反过来改内核。
- 阶段 1 提取任务**不挂**超时看门狗，行为零变化；`_run_job_inner` 主循环一行未动。
- `/api/transcribe` 仍只诚实拒绝；S1 未产出任何实际内容文档，也未写 `out/md/`、`INDEX.md`、`MERGED.md`。
- 验收：`python -m unittest -v test_extract test_app` **62/62 OK**（146.115s）、门禁 **9/9**、`git diff -- SPEC.md` 与 `git diff --stat -- extract.py` 均为空。
- **S1 到此为止，等用户确认后才进入 S2a（Word → .md 输入增强）**。

---

## [0.4.2] - 2026-11-15

阶段 2/3 能力扩展（Word / 音频 / 视频 / 视频链接 → `.md`）的 **S0 立项与契约对账** 里程碑。**本版本不含功能变更**，桌面端行为与 v0.4.1 完全一致；升级版本号仅为履行「每阶段收尾打包 exe + 上传 GitHub + 推版本 tag」的发版规则。

### Added

- `docs/CAPABILITY_CONTRACT.md`：另立的「阶段 2/3 新能力契约 v0.1 草案」。界定与冻结 `SPEC.md` 的正交关系、10 条不变量、五层架构与 `FORMAT_REGISTRY` / `ToolAdapter` / handler 注册表扩展点、产物契约（`out/derived/` + 8 字段 `src` 注释 + 块级锚点）、长任务与安全（防 SSRF）契约、S0–S6 验收口径、6 项风险登记。
- `docs/S0-立项与契约对账.md`：需求确认表（含用户四项决策）、现场事实（精确到行号）、红线解禁清单、受影响断言清单（A 保持 / B 扩项 / C 订正三类）、5 项已知漂移登记、S0 验收记录与确认闸门。

### Notes

- `SPEC.md` 保持冻结，一字未改；阶段 1 提取内核一行未动。
- 对上一轮路线图两处精化：`test_06` / `test_11` **原样保留**（它们守护冻结内核），视频红线改由 S4 的独立新测试守护；新能力产物落独立 `out/derived/`，不写 `INDEX.md` / `MERGED.md` / `out/md/`，避免破坏 `SPEC.md` §3.F 的双向件数对账。
- 验收快照：`python -m unittest -v test_extract test_app` 60/60 OK；`python tools/check_release.py --no-exe` 9/9；验收时 `git diff -- SPEC.md` 与 `git diff --stat -- "*.py" ui/` 均为空。
- **S0 到此为止，等用户确认后才进入 S1**。

---

## [0.4.1] - 2026-11-14

修复发版链路的最后一环：v0.4.0 的代码与 tag 都已推送，但 GitHub 上始终没有 Release、也没有 `Jinghe.exe` 资产，客户端「检查更新」因此拿不到安装包。

### Fixed

- **CI 在 Windows 上因中文输出崩溃**：`tools/check_release.py` 打印中文门禁结果时，Windows runner 的默认 `cp1252` 编码抛 `UnicodeEncodeError`；`test_app.py::test_32` 随之失败，`needs: test` 使「构建 exe 并上传 Release 资产」作业被整段跳过。现由脚本自身把 `stdout/stderr` 重配置为 UTF-8（`errors=replace`），并在 workflow 全局设置 `PYTHONUTF8=1` / `PYTHONIOENCODING=utf-8`。
- **父进程解码不一致**：`test_32` 调用门禁的子进程显式按 UTF-8 解码，避免 cp1252 下中文输出乱码或再次抛异常。

### Added

- 防回归断言：`test_32` 检查门禁脚本含 UTF-8 兜底、CI workflow 含 `PYTHONUTF8`，保证发布作业不会再因编码被静默跳过。
- 本版本同时补发 v0.4.0 / v0.4.1 的 Release 资产，使 `/api/check-update` 的 `assets[]` 解析链路真正可用。

---

## [0.4.0] - 2026-11-14

架构阶段：从「手工迭代」升级为「工程化交付闭环」，补齐软件项目里一直缺失的构建发布与运维更新两个阶段。

### Added

- **GitHub Actions CI/CD**（`.github/workflows/ci.yml`）：`push` / `PR` 触发 Windows runner 跑全量单元测试与发版门禁；推送 `v*` tag 时自动安装钉版 PyInstaller、构建 `dist/Jinghe.exe`、创建 GitHub Release 并上传 `Jinghe.exe` 资产。此前 release 从无二进制资产，用户点「检查更新」进到的页面没有安装包可下。
- **`CHANGELOG.md`**：集中记录版本变更，替代散落在 `使用说明.md` 里的长版本串。
- **发版门禁 `tools/check_release.py`**：校验版本号唯一来源（`extract.py`）、HTML 不含硬编码版本、CHANGELOG 有对应条目、使用说明当前版本一致、CI workflow 存在、产物可选校验。CI 与本地发版前均可执行。
- **检查更新解析 release 资产**：`GET /api/check-update` 新增 `has_asset / asset_name / asset_size / asset_url`，只接受仓库 `releases/download/` 下的 `.exe` 资产；`POST /api/update` 发现新版本时自动把新版 exe 下载到用户「下载」文件夹并简短回显，无资产时退回打开下载页。
- **下载安全约束**：URL 白名单、120 MB 大小上限、30 秒超时、临时文件 + 原子替换，失败不阻断其他降级路径。

### Changed

- 版本号不再硬编码在 `ui/index.html`：页面标签改为占位符，由 `/api/state` 返回的后端版本动态注入，消除第 4 处手工同步点。
- 「检查更新」从「只查版本 + 打开网页」升级为「查版本 + 拿到安装包」，功能真正闭环；界面不显示任何 GitHub 链接，离线行为保持不变。

### Fixed

- `capabilities()` 子进程探测失败返回 `"unknown"` 时，版本比较会误判为「发现新版本」并弹出浏览器；现在回退到 `extract.__version__`。
- `/api/open` 收敛为只允许打开应用数据目录内的自身文件（日志、设置），不再接受任意绝对路径交给 `os.startfile`。

---

## [0.3.9] - 2026-11-14

关于页「版本更新」卡片精简：清除说明段、清除页面显示的 GitHub 链接（含隐私卡片地址）、清除离线长文案；「检查更新」按钮移到左侧、「当前版本」移到右侧；离线不再自动弹浏览器，状态条默认隐藏。

## [0.3.8] - 2026-11-14

关于页合并为单个「检查更新」按钮（新增 `POST /api/update`）；首页 `.cards` 改用 `grid-template-areas`，输入在上、输出在下，「已识别」清单移到原输出所在的右列并带空态；窄窗口降级单列。

## [0.3.7] - 2026-11-14

首页文案精简（输入 / 输出 / 打开），取消「选择文件夹」「打开输出目录」按钮与两条冗余提示；修复「打开合并文档」点击无反应——新增 `POST /api/open-merged` 与 `GET /api/merged-status`，固定用系统记事本打开 `MERGED.md`，重启后按实际产物恢复按钮可用状态。

## [0.3.6] - 2026-11-14

左侧导航栏宽度可拖动调节；关于页新增「版本更新」卡片（指向 GitHub 最新 release）；运行日志集中到关于页，支持打开文件、生成指定文件、仅导出报错行。

## [0.3.5] - 2026-11-14

界面改版为左侧可折叠导航栏（首页 / 设置 / 关于），点开才显示具体文字；设置项持久化到 `%LOCALAPPDATA%\Jinghe\settings.json`。

## [0.3.4] - 2026-11-14

系统性代码优化：日志去噪与 2 MB 轮转、连接重置不再刷栈、端口占用者身份校验、编码探测与 PDF 加密检测流式化、记住路径与快捷键。

## [0.3.3] - 2026-11-14

桌面端体验：关闭窗口后程序自动退出（心跳看门狗）、启动窗口居中。

## [0.3.2] - 2026-11-14

修复「双击运行无反应」：单实例保护改为重复启动时主动唤起已运行实例窗口，浏览器唤起失败时 MessageBox 兜底。

## [0.3.1] - 2026-11-14

增加运行时日志记录，报错时一并记录涉及的组件与运行环境状态，并提供「打开日志文件」按钮。

## [0.3.0] - 2026-11-14

重新设计界面，新增「后处理 · 阶段 2/3」功能卡片。

## [0.2.0] - 2026-11-14 及更早

本地网页界面与基础提取能力；v0.2.1 修文件多选与中文 PDF 提取，v0.2.2 修对话框失败无反馈等 4 处，v0.2.4 多选文件对话框改为 Win32 原生 API，v0.2.5 治理前端请求无超时隐患并新增「打开合并文档」，v0.2.6 新增「打开输出目录」按钮。
