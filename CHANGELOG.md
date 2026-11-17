# 更新日志

本文件记录「精核」软件版本的可感知变更。格式参照 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循语义化版本。

软件版本（`extract.py: __version__`）与 `SPEC.md` 的规格版本（v2.x）是两套编号，不要混淆。`SPEC.md` 为冻结的规格契约，不随本文件更新。

## [0.6.1] - 2026-11-17

**S8 缺陷修复**（对 v0.6.0 可信提纯做系统代码检测后的修复；不改能力、不改契约红线）。

### Fixed

- **API Key 不再被掩码覆盖**：设置页回填的是掩码（如 `****3456`），此前**任意一次保存**（哪怕只改补写开关）都会把掩码串当成新 key 写入，真 key 永久丢失、云端后端从此全部 401。现在前端提交前把掩码转成空串、后端另设「掩码值 = 未修改」的兜底，两道防线互不依赖；主动换 key 不受影响。
- **关键词提取质量**：全局关键词的候选词位置此前被统一凑到首句开头，导致不同句的标题词互相「撞车」被整片误杀，输出退化成「心约 / 析安」这类跨词碎片。现在跨度改为**真实命中位置**、槽位冲突消解**只在同一句内**判定，并采用「更具体者优先」（完整概念名压过其内部短词）；全文只出现一次的二元组碎片不再进入关键词。
- **B 档操作说明行不再丢失**：原文内改写产物里的「本次改写操作：术语归一、合并去重、结构重排」此前**从未出现在产物中**（拼接用的匹配串与实际输出不一致，静默失效）。改由渲染层原生输出，不再靠字符串替换。
- **修订产物 doc_id 断链**：extract 模式的修订产物此前用 `.refine.md` 的内容哈希另算一个 id，产物名与精读产物对不上；现统一沿用精读产物的同一个 id（`doc_A.refine.md` → `doc_A.revise.md`），与 LLM 路径口径一致。
- **多块锚点可解析**：B 档合并条目产生的 `| blocks: 2,7` 锚点此前无法被解析，链式处理会**静默丢掉**这些核心；现可解析出完整块列表。
- **补写开关判定保守化**：字符串 `"false"` 此前会被 `bool()` 强转成 `True`（补写开关被误开启）；现在只认「明确为真」，其余一律判关 —— 敏感开关宁可误关不可误开。

### Added

- **系统日志按天切割 + 保留 7 天**（新增 `log_rotate.py`，零依赖）：当前日志真源仍是 `app.log`（不动白名单与导出契约），跨天时按文件修改时间归档为 `app-YYYY-MM-DD.log`；后台每小时轮询清理 7 天前的归档（只删严格日期形状的归档，不碰 `app.log` / `app.log.1` / 其它文件）。跨天即时切割由写入钩子完成，长期挂着靠轮询兜底。
- **输出区「打开」文件夹端点** `/api/open-folder`：只接受**目录**、拒绝文件路径，在系统文件管理器中浏览输出文件夹。

### Changed

- 关于页顺序：**系统信息**移到**版本更新**上面；系统日志卡片独立保留在其下。
- 首页输出区按钮「更改」改为「**打开**」，点击后浏览文件夹（不再弹选择框，也不能进文件）；输出路径仍可在输入框手动填写。
- 左侧导航：顶部「精」图标移到**左下角版本号旁**；折叠按钮换成**三条横杠**（汉堡菜单）；精读图标换成星形。
- **关于页「运行日志」区精简**：移除整条日志导出栏（「打开文件」「生成指定文件…」「仅导出报错 / 警告行」、状态文字与导出路径回显）；随后进一步拆卡——原卡片更名为「系统信息」（只保留版本 / Python / 平台 / 规格 / 界面形态），「系统日志」独立成一张同级卡片排在其下方，卡内为日志路径 + 「打开」按钮（带无障碍标签）。导出端点仍保留在后端，仅从界面移除，不影响排查能力的历史契约。
- 发版门禁的「关键源文件语法可编译」纳入 S7/S8 新增模块（`backend.py` / `refine.py` / `refine_engine.py` / `revise_engine.py` / `extract_engine.py`），此前新模块语法错误只会在运行时暴露。
- 抽取式 / 原文内改写路径补上取消检查点（与 LLM 路径对齐）；抽取式模式下列模型接口改为透传「不依赖模型」的诚实说明，不再回「尚未配置后端」。
- 全量用例 82 → **83**（新增 `test_55` 缺陷回归：掩码往返、开关类型判定、关键词算法、B 档操作行、doc_id 链、多块锚点）。

### Notes

- `SPEC.md`、阶段 1 冻结主流水线、既有端点与红线均未改动；不造假校验、补写隔离、冻结盘保护全部保持。
- **已知边界**：大模型（LLM）模式的真推理尚未接入（`chat()` 仍是显式未实现），切换到 LLM 模式执行会诚实报 `NotImplementedError`；该项排期后续阶段处理。
- 详见 `docs/S8-代码检测报告.md`。

## [0.6.0] - 2026-11-17

**S8 · 可信提纯**（按用户「对内容核心提取，不能造假」+「补写保留，增加补写开关」落地）。左侧导航的「精读 / 修订」现在默认走**内置抽取式引擎**：零依赖、离线运行，核心为原文原句、可逐字回溯。

### Added

- **可信提纯（默认，零配置零依赖）**：字符二元组切词 + TF-ICF 关键词 + TextRank 句级中心度 + MMR 去冗余 + 领域词表/标题挖词，纯标准库实现。每条核心 = **原文原句 + 关键词 + 块锚点 + 评分与依据**（中心度 / 标题共现 / 含数据）。
- **架构级不造假**：产出前逐条验证「可在原文逐字定位」，对不上即零产物 —— 不是靠模型自觉，而是结构上不可能编造。
- **原文内改写**（修订页，extract 模式）：术语归一（需共现证据，统一到高频写法，不产生新词）、要点合并去重（块锚点并列、原文连接不重写）、结构重排、排版归一（可选，默认不做）。
- **AI 补写开关**（默认关闭）：开启后补写内容进独立「AI 补充（模型生成，请核对）」分区，带 `[AI ++ … ++]` 专用标记，**不声明块锚点**，md/html 双产物同步隔离 + 头部诚实告知。开关关闭时补写类变更**直接丢弃**，不是「提示核对」。
- **提纯模式选择**：设置页可切「可信提纯（抽取式）」/「大模型提纯（LLM）」，界面随模式联动（置灰模型下拉与额外要求、切换页面说明）。

### Notes

- 抽取引擎零第三方依赖（测试用 AST 扫描锁死）；软件不下载、不打包任何模型或组件。
- `SPEC.md`、阶段 1 冻结主流水线、`/api/summarize`、`/api/transcribe` 零改动；全量 82 用例 + 9 项发版门禁全绿。
- 详见 `docs/S8-可信提纯验收.md` 与 `docs/S8-可信提纯立项与契约.md`。

## [0.5.0] - 2026-11-16

**S7 · 精读 / 修订能力**（全新后处理工作流，语义化版本 minor 升级）。左侧导航新增「精读」「修订」两项，对已转换为 md 的文件做核心提纯与补写修改；后端可插拔、产物双格式、全程诚实降级。

### Added

- **精读**：从已转换 md 语义级提纯核心知识点（只提纯，不补写）。核心观点必须带有效块级锚点，编造/越界一律丢弃，全无效零产物。
- **修订**：对精读核心补写缺失 + 修改已有；新增/修改内容双产物区分——`revise.md`（符号标记 `[++ ]` / `[[~~ → ]]`）+ `revise.html`（彩色样式，WCAG AA），由同一变更列表同源渲染，逐条标记完整性校验，篡改即零产物。
- **可插拔后端（方案 C）**：客户自选本机 ollama（内容不出本机）或云端 OpenAI 兼容端点（配置即知情同意）；软件零下载、零打包、零自动安装，未配置=未启用。
- **设置页「精读后端」配置区**：类型/端点/API key（脱敏回显、留空不改）/模型/测试连接；密钥独立 `backend.json`，不进日志与产物。
- **只读产物端点**：`GET /api/refine/artifact`（限定 derived/ + 防穿越）与独立 `POST /api/refine/open`，不动 `/api/open` 白名单。

### Notes

- 真模型质量需客户环境（ollama 或云端 key）验证；本版工程逻辑全部经 mock 验证。
- `SPEC.md`、阶段 1 冻结主流水线、`/api/summarize`、`/api/transcribe` 零改动；全量 79 用例 + 9 项门禁全绿。

## [0.4.9] - 2026-11-16

**交互体验补齐**（按交互专家「顺滑」的意见收敛信息架构）。本轮只动 UI 交互与后处理层后端接线，`SPEC.md`、阶段 1 冻结主流水线（`extract.py` 提取逻辑）、`test_06` / `test_11` 冻结断言零改动。

### Fixed

- **「检查更新失败：未知接口：/api/update/check」**：`ui/app.js` 的 `checkUpdate()` 原先把空对象 `{}` 当 body 传给 `api()`，被判成 **POST**；而该端点只注册了 **GET**，于是命中 404 兜底文案。改为传 `undefined`（走 GET），实测 GET 200 / POST 404 精确复现并修复。

### Changed

- **关于页「检查更新」交互**：取消「最新版本」信息格；点击后按实际情况反馈——已是最新版本弹「当前是最新版本」轻提示（**3 秒自动消失**），发现新版本**直接进入更新流程**（无需再点「立即更新」），离线或报错如实回显，绝不谎报「已是最新」。

### Added

- **首页拖拽输入**：输入卡片新增拖拽框，把文件 / 音频 / 视频拖进框内即识别为输入。普通 Edge 页面拿不到本地绝对路径，故新增 `POST /api/drop-files` 把文件内容流式上传到本机临时目录（`jinghe-drop-*`，pid 归属 + 启动清扫 + atexit 兜底，单文件上限 2GB，文件名 basename 清洗防穿越），返回真实路径后走既有 `/api/dry-run` 识别。
- **已识别清单勾选预览**：「预览分流」按钮移到「已识别」标题栏右对齐；清单项带复选框与全选框，勾选后点「预览分流」只对选中文件预览。后端在 `_api_dry_run` 层为每个 item 补 `path` 字段（basename→真实路径映射，不改冻结的 extract.py），供勾选后精确预览。

### 交互打磨（同版本增量，静态审视后修复）

- **勾选预览不再清空清单**：原先勾选部分文件点「预览分流」后，会用选中子集重建「已识别清单」，导致未勾选文件消失、勾选状态归零。现在预览只读盘点、只更新统计反馈，**保留完整清单与勾选状态**。
- **更新门闩**：更新进行中再点「检查更新」只提示「正在更新中」，不再重复触发更新任务；开始检查时清掉上一次残留的进度条。
- **拖拽整页防护**：拖到拖拽框外的文件不再被 Edge 默认打开而跳出应用，统一引导拖入框内。
- 新增 `test_45`（交互打磨契约），测试基线 72 → **73**。

### 本机工具就绪（同版本增量）

- 按用户要求在本机装齐可插拔工具：**ffmpeg + ffprobe**（win64-gpl 静态构建，约 500MB）、**openai-whisper CLI**（torch 走 CPU wheel）、**yt-dlp**。工具装在软件外部（软件仍不下载、不打包、不自动安装），只把目录加入用户 PATH。
- torch 兼容性：官方最新 2.15+cpu 依赖系统缺失的 `VCRUNTIME140_THREADS.dll`，降级到 **torch 2.6.0+cpu** 后加载正常；whisper `--help` 实测提供项目所需的 `--model/--task/--output_format json/--output_dir` 参数。
- **探测超时修正**：whisper 启动需 import torch + numba（实测 6–8s）、yt-dlp 首次启动解析依赖也慢，原统一 2s 超时会把"已装好"误判"未启用"。`media_tools.py` 新增 `PROBE_TIMEOUTS`（whisper 15s / yt-dlp 10s，ffmpeg 仍 2s），仍真跑探测命令验证可用，诚实原则不变。冻结态实测 `/api/tools/probe` 三工具全绿，S3 音频 / S4 视频能力均 `available=true`。
- 模型权重按约定**不预下载**，首次转写时由 whisper 自行准备。

### 首页 UI 可访问性审查修复（ui-ux-pro-max）

用 `ui-ux-pro-max` 对首页做了一轮系统审查，量化核对了颜色对比度、焦点可见性、输入标签与动效降级，修复 4 类问题：

- **焦点环全站缺失**：审查发现全站仅 2 处 `:focus`，且拖拽框与输入框直接 `outline: none` 却不给替代 —— 键盘用户完全无法定位焦点（WCAG 2.4.7 失败）。现统一用 `:focus-visible` 画焦点环（鼠标点击不显示、键盘 Tab 显示），环色 `#185FA5`（对白底 6.52:1），用 `outline` 不影响布局；输入框额外加内发光，焦点环颜色本身也过 3:1 门槛。
- **可见文字对比度不达标**：占位符 `#9A9890` 对白底仅 **2.89:1**，另有一处"即将推出"按钮、空态提示、卡片副标题、设置项说明、侧栏版本号、拖拽框副文案共 6 处同色文字同样不合格。统一改为 `#6F6D66`（白底 5.18:1 / 浅灰底 4.50:1，两种底色都达 AA），仍明显弱于正文 `#1F1F1D`（16.51:1），保留层级感。
- **输入框缺标签**：输入路径 / 输出目录两个输入框只靠 placeholder 提示，屏幕阅读器无关联名。现补 `aria-label`，拖拽框（`role="button"`）补可访问名称；设置页输入框本已被 `<label>` 包裹，维持不变。
- **未适配"减少动态效果"**：补 `@media (prefers-reduced-motion: reduce)`，统一把过渡压到 0.01ms（保留 `transitionend` 触发，避免依赖过渡的脚本失效）；同时给按钮、导航项、链接按钮补 160ms 过渡，消除 hover 生硬跳变。

新增 `test_46`（可访问性契约，逐条锁定上述修复，含对比度实算），测试基线 73 → **74**。

## [0.4.8] - 2026-11-16

**自更新闭环**（运维阶段补齐）。关于页「检查更新」从「查一下版本号、顺便打开网页」升级为**真正能完成更新**：点击后如实回显**当前版本与最新版本**，发现新版本可一键**下载 → 替换正在运行的程序文件 → 自动重启**，全过程有**百分比进度**反馈。同时把仓库 `kong-city/jinghe` 由私有改为**公开**，匿名即可查询 release 与安装包（此前私有仓库让客户端匿名访问 GitHub Release API 一律 404，「检查更新」永远拿不到真实版本号）。

### Added

- `self_update.py`（新，纯标准库）：`check()` 查版本与安装包资产、`download_asset()` 流式下载（进度回调 + 可取消 + `.part` 原子替换）、`install_plan()` 判定能否自动替换、`build_install_script()` / `schedule_install()` 派发替换脚本。
- 四个新端点：`GET /api/update/check`（只查版本，不下载不安装）、`POST /api/update/start`（后台跑更新任务，立即返回）、`GET /api/update/status?since=N`（进度轮询，独立事件队列）、`POST /api/update/cancel`、`POST /api/update/apply`。`/api/state` 新增 `update` 字段说明当前能否自动替换。
- 关于页「版本更新」卡片改为三格：**检查更新 / 当前版本 / 最新版本**；查到新版本后出现「立即更新」按钮，下载期间显示进度条与百分比，完成后提示「程序即将重启」。
- Windows 替换机制：正在运行的 exe 被系统独占无法就地覆盖，因此先下载到同目录 `Jinghe.new.exe`，再派发一个脱离父进程的 PowerShell 脚本——等待本进程退出 → 备份旧文件 → 覆盖 → 启动新版 → 新版 4 秒内退出则**自动回滚**旧版并重启。

### Fixed

- 仓库可见性：`kong-city/jinghe` 私有 → **public**。此前匿名调用 `https://api.github.com/repos/kong-city/jinghe/releases/latest` 返回 404，「检查更新」永远落在「离线 / 无法获取」分支，拿不到真实最新版本号（挂账多轮的 D5 结清）。
- 旧 `/api/check-update` 的 assets 解析逻辑迁到 `self_update.py` 单点真源，`app.py` 只保留字段形状与旧端点兼容，杜绝两处各写一套解析规则。

### Safety

- **下载白名单**：只接受本仓库 `releases/download/` 前缀下的 `Jinghe*.exe`，绝不接受任意外部地址——自更新绝不能退化成「任意下载器」。
- **安装目标唯一**：只允许替换**当前正在运行的可执行文件自身**，外部传入的任意路径一律拒绝；源码模式下（`sys.executable` 是 `python.exe`）直接拒绝自动替换，绝不覆盖源码目录里的任何文件。
- 失败必须诚实：离线、发布里没有安装包、下载中断、尺寸与发布信息不符、替换失败，一律如实回显原因，**绝不谎报「已是最新」或「更新完成」**；无法自动替换时只下载到「下载」文件夹并给出手动替换指引。
- 自更新事件队列独立（`_UPDATE_JOB`），不污染阶段 1 的 `/api/progress`，也不触碰 `out/md/` / `INDEX.md` / `MERGED.md`。

### Tests

- 新增 `test_43`：下载白名单、白名单外零网络零落盘、替换脚本内容与 `$PID` 只读变量雷区、安装红线（源码模式 / 非自身目标）、四个新端点真实 HTTP、更新任务终态收敛、关于页三格与进度条接线、打包清单与契约文档。测试基线 70 → **71 用例**。
- 修订 `test_30` / `test_32`：按用户新要求恢复「最新版本」信息格（「给出结果反馈 当前最新」），并把 assets 解析断言迁到 `self_update.py`；被取代的旧断言（前端一次性调用 `/api/update` 并放宽超时）同步订正。

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

### S7a · 精读 / 修订能力地基（用户放行「按你的节奏走」；停在 S7a 闸门）

- 新增 `refine.py`（S7a 地基）：能力声明、本机 ollama 探测、来源只读检查、诚实降级骨架；**不写真调模型逻辑**（S7b/S7c 才接），任何真实推理调用显式拒绝、绝不产伪文档。
- `/api/tools/probe` 顶层新增 `refine` 字段；**ollama 独立 tools 子结构，不进 TOOL_SPECS**（S1 契约锁死 3 工具）。
- 六个增量端点：`POST /api/refine/inspect|start|cancel`、`POST /api/revise/start`、`GET /api/refine/status|models`；缺工具/空输入一律诚实拒绝，零产物。
- 双产物契约已声明（`.refine.md` / `.revise.md` + `.revise.html`），S7a 只声明不渲染。
- 新增 `test_47`（S7a 地基契约），测试基线 74 → **75**；全量 75 + 门禁 9 项全绿；冻结态实起验证 probe 顶层 refine 与新端点可用。
- **严格不碰**：`SPEC.md` / `extract.py` / `/api/summarize` / `/api/transcribe` 全部原样。

### S7b · 可插拔后端适配层（方案 C，用户放行；停在 S7b 闸门）

- 后端裁决由「本机 ollama 单后端」改为 **方案 C 可插拔多后端**：统一 `Backend` 接口 + `LocalBackend`（ollama localhost:11434）/ `CloudBackend`（OpenAI 兼容端点+key）双实现，客户自选、零强制；软件本体恒定 9MB，不下载/不打包/不自动安装任何组件。B 方案 = C 选 CloudBackend。
- 新增 `backend.py`：配置独立存 `%LOCALAPPDATA%\Jinghe\backend.json`（**不放 settings.json**，后者被 /api/settings 回显、可被日志导出触及）；`api_key` 读端点脱敏回显、写端点空值不改、**绝不进日志/产物/异常堆栈**；`chat()` 真推理显式拒绝（留 S7b 后半）。
- `refine.py` 探测改走 `backend.probe_current()`，tools 子结构由 `ollama` 改为 `backend`；`listed_models()` 走当前后端 `list_models()`。
- app.py 新增 `GET/POST /api/refine/backend`（配置读脱敏 / 写回显脱敏）。
- 新增 `test_48`（双实现、密钥脱敏、独立存储、缺配置诚实降级、HTTP 回显/日志无 key），测试基线 75 → **76**；全量 76 + 门禁 9 项全绿；冻结态实测 probe.tools=backend、POST key 回显 `****1234`、日志零泄漏。
- **修一个死锁**：`save_config` 持 `_LOCK` 时调 `load_config(refresh)` 再拿同一把非重入锁 → 自锁；改为锁内直接读当前 key。
- **严格不碰**：`SPEC.md` / `extract.py` / 既有端点全部原样。真推理产出与 UI 仍留后续阶段。

### S7b 后半 · 精读提纯引擎（mock 验证；停在 S7b 闸门）

- 新增 `refine_engine.py`：源 md 逐行分块（标题与每段各自成块）→ 构造结构化 JSON prompt → 解析模型响应 → **反编造锚点校验**（每条核心观点必须带有效整数块号，越界/无号/空文本/非整数一律丢弃，全无效 → 零产物）。
- 产物 `out/derived/<doc_id>.refine.md`：8 字段来源注释 + 三区块（文档信息/核心知识点/提纯元数据）+ 每条观点带 `block_anchor`；独立 `provenance_refine.json` 读旧追加；冻结对账盘只读快照比对。
- `refine.py` 接入轻量任务状态（自洽，不依赖 app.py Job 避免循环 import）：start_refine 启动线程 + status(since 增量事件) + cancel；模型调用走 `Backend.chat()`（mock 验证，产品代码永远走真实后端）。
- **诚实边界**：块号有效只保证观点挂靠真实块，不能 100% 保证内容出自该块；产物显式标注"核心由模型提纯，请对照原文核对"，不假装零幻觉。
- 新增 `test_49`（mock 后端：分块/prompt 约束、反编造丢弃、8字段+锚点+三区块、provenance 读旧追加、冻结盘只读、全无效零产物、端点形状），测试基线 76 → **77**；全量 77 + 门禁 9 项全绿；冻结态实测端点形状与诚实降级。
- **严格不碰**：`SPEC.md` / `extract.py` / 既有端点全部原样。真模型质量验证需用户环境（ollama/云端 key），本次 mock 只验工程逻辑。

### S7c · 修订双产物（mock 验证；用户放行并上传）

- 新增 `revise_engine.py`：从 `.refine.md` 解析核心（anchor 与「来源块」须一致）→ 结构化变更列表（add/modify，block 须挂靠有效核心、modify 的 old 须匹配原文）→ **双产物同源渲染**（单一真源=changes，md 符号标记 + html 彩色均从它渲染，不从一份反推另一份）。
- **标记完整性校验**：交付前逐条确认每条变更在两份产物中都有对应标记，篡改任一份即失败 → 零产物；全无效变更也零产物。颜色达 WCAG AA（新增绿字浅绿底、修改旧红删除线/新蓝、原文黑）。
- `refine.py` 接入 `_run_revise_inner` + start_revise 透传 outdir/instruction；doc_id 从精读产物名提取，与精读同一 id；provenance stage=revise 读旧追加；冻结盘快照比对。
- 新增 `test_50`（核心解析/反编造变更/双产物同源/标记篡改抓出/WCAG AA 实算/端到端双产物/全无效零产物），测试基线 77 → **78**；全量 78 + 门禁 9 项全绿；冻结态端点与产物声明验证通过。
- **严格不碰**：`SPEC.md` / `extract.py` / 既有端点原样。真模型质量需用户环境，mock 只验工程逻辑。

### S7d · UI 接入（用户放行；本次不上传，停在 S7d 闸门）

- 左侧导航新增「精读」「修订」两项（含 SVG 图标、与首页/设置/关于同级）；新增两个页面容器与 PAGE_META/pages 映射。
- 设置页新增「精读后端」配置区：类型（未配置/本机 ollama/云端兼容）、接口地址、API key（**password 输入 + 脱敏回显 + 留空不改**）、默认模型、测试连接；云端配置附知情同意告知。
- 精读页：源 md 选择 + 模型下拉 + 开始/取消 + 进度 + 结果预览；修订页：refine.md 选择 + 额外要求 + 双产物预览（iframe srcdoc sandbox 彩色版 + details 符号标记版）。
- 新增两个只读端点：`GET /api/refine/artifact`（限定 derived/ 内 + .md/.html + realpath 防穿越，供预览）、`POST /api/refine/open`（独立打开产物，**不动 /api/open 白名单**）。
- JS 交互：能力状态复用 toolState.refine、GET 端点严格传 undefined、增量轮询 status?since、产物经只读端点取文本。
- 新增 `test_51`（导航/页面/配置表单/aria-label/端点调用/artifact 安全边界/焦点环与 reduced-motion 未被破坏），测试基线 78 → **79**；全量 79 + 门禁 9 项全绿；Edge headless DOM 实测两个新按钮/页面/控件真实出现。
- **严格不碰**：`SPEC.md` / `extract.py` / `/api/open` 白名单 / 既有端点原样。

### S7e · 工程化收口与验收（2026-11-16）

- 冻结契约复核：SPEC.md / extract.py / test_extract.py 相对起点提交与 v0.4.9 tag 双重 diff 为空；零第三方依赖（全标准库 + 自有模块）；单文件 exe 8,952,693 字节；build.spec 未收集外部工具/模型。
- 不变量复核：`probe.tools` 恒锁 3 工具（ffmpeg/whisper/yt-dlp），新能力全走顶层增量字段；`/api/summarize`/`/api/transcribe`/`/api/open`/`/api/settings` 原样；新模块零写入冻结对账盘。
- 收口总验：全量 **79/79** + 门禁 **9 项** + 冻结态 8 端点 HTTP 200 + Edge headless DOM 新按钮确认。
- 新增 `docs/S7-精读修订验收.md`（边界/裁决演进/红线落地/验证矩阵/风险/闸门）；契约 v0.8.9 定稿。
- 软件版本 v0.4.9（未随 S7 升号，符合双轨规则）；本轮 UI 未上传，停在 S7e 闸门。

### S8a · 可信提纯（抽取式主线 + AI 补写开关；停在 S8a 闸门）

用户明确要求：**「对内容核心提取，不能造假」**，并拍板**「补写保留，增加补写开关」**。

- 新增 `extract_engine.py`（**纯标准库、零第三方**）：字符二元组切词（规避分词器依赖）+ TF-ICF 关键词 + TextRank 句级中心度（PageRank 幂迭代）+ 领域词表/标题挖词 + **半开区间跨度冲突消解**（消除「核项」类边界碎片）+ 结构倍率加权 + MMR 去冗余。
- **A 档可信提纯（默认，零配置零依赖离线）**：输出每条 = **原文原句** + 关键词 + 块级锚点 + 评分与依据（中心度/标题共现/含数据）。`verify_traceable` 逐条验证「可在原文逐字定位」——**架构级保证不造假**，对不上即零产物。
- 新增 `mode` 配置（extract|llm，默认 extract）区分提纯模式；新增 `ExtractBackend`（内置引擎恒可用，**绝不进 TOOL_SPECS**）。
- **AI 补写开关 `allow_suppplement` 默认关闭**：开启后补写内容单独分区「AI 补充（模型生成，请核对）」、带 `[AI ++ … ++]` 标记、**不声明块锚点**（它不对应原文块），与原文核心物理隔离。
- UI：设置页新增「提纯模式」下拉与「允许补写」开关，抽取式模式下自动置灰 LLM 字段并给出说明。
- 新增 `test_52`（不造假逐条回溯、零第三方 AST 校验、extract 不进 TOOL_SPECS、默认关闭补写、隔离标注、纯标题剔除、UI 契约），测试基线 79 → **80**。
- **修 4 处环境脆弱性测试**：test_40/test_42 原硬编码「本机未装 whisper/ffmpeg」，现改为**隔离 PATH 造缺工具环境**稳定复现降级路径；能力断言改为「与实际探测一致」；拒收场景改用独立 outdir 并断言「无 md 产出」（provenance 留痕允许存在，是 S3/S4 既定设计）。
- 全量 **80/80** + 门禁 9 项全绿；冻结态实测：零配置下 probe 即 `available`（内置引擎）、补写开关默认关、Edge DOM 确认新 UI、端到端产出 6 条全为原文原句的核心。
- **严格不碰**：`SPEC.md` / `extract.py` 主流水线 / `TOOL_SPECS` 三工具 / 既有端点原样。

### S8b · B 档原文内改写 + 修订按模式分流（停在 S8b 闸门）

- **B 档「原文内改写」落地**（`extract_engine.py` 第 9 节）：术语归一（相似词共现证据 → 统一到高频写法，**不产生新词**）、要点合并去重（bigram Jaccard 超阈值 → 合并，**块锚点并列**、原文用 ` ｜ ` 连接不重写）、结构重排（按块号）、排版归一（**默认不做**，因它改标点会破坏逐字定位，仅作可选偏好）。
- 新增 B 档红线 `verify_no_new_content`：逐片段校验「每个片段都在原文」（忽略标点全半角差异）；篡改任一即失败。
- **修订按 mode 分流**：`extract` → B 档原文内改写（纯标准库、零依赖、架构级不造假）；`llm` → 沿用 S7 补写+修改双产物。extract 模式**绝不调 LLM**。
- `revise_engine.parse_core` 兼容两种精读产物格式（S7「（来源块 N）」行尾后缀 / S8 抽取式 anchor 注释），并限定只解析「## 核心知识点」区块，避免把文档信息区的列表项误当核心。
- 产物渲染按模式区分文案（A 档"全部为原文原句" / B 档"原文内改写、未改事实"），多块锚点用 `blocks:` 并列。
- UI 模式联动：extract 模式置灰模型下拉与「额外要求」，两页副标题按模式切换；初始化即联动，首屏控件状态正确。
- capability 的 engine 说明按模式区分（抽取式 vs 大模型），并暴露 `engine.mode`。
- 新增 `test_53`（B 档白名单/合并去重/块号并列/三条红线/排版归一可选/修订分流/锚点保留/UI 联动），测试基线 80 → **81**；test_49/test_50 显式声明所守路径（S7 LLM 路径）以适配新分流。
- 全量 **81/81** + 门禁 9 项全绿；冻结态实测：精读 → 修订双链路端到端通过，双产物齐备、锚点保留、冻结盘未动。
- **严格不碰**：`SPEC.md` / `extract.py` / `TOOL_SPECS` 三工具 / 既有端点原样。

### S8c · C 档补写隔离与开关真正生效

- **补写开关真正生效**：`parse_changes(allow_suppplement=False)` 直接丢弃 add（补写）类变更并计入 skipped —— 关闭就是真的没有，不是"提示你去核对"。
- **补写物理隔离**：md 独立「AI 补充（模型生成，请核对）」分区 + `[AI ++ … ++]` 专用标记（区别于修订的 `[[~~ ]]`）+ html `ai-item` 样式 + 头部「本文件含模型生成内容」告知；补写**不声明块锚点**（不对应任何原文块）。
- `verify_marks` 追加**隔离校验**：补写内容不得出现在核心区，隔离标记被破坏即判失败。
- **配色升级**：AI 补写改用警示红系 `#501313` on `#FCEBEB`（对比度 12.62:1，WCAG AA），与「修改」的蓝/红区分 —— 修改是对原文的调整，补写是原文之外的新增内容。
- 新增 `test_54`（开关开/关两种端到端、隔离校验、篡改可抓出、补写无锚点、配置键贯通），测试基线 81 → **82**。

### S8d · 工程化收口与验收

- 冻结内核复核：`SPEC.md` 零改动；`extract.py` 相对 v0.5.0 tag **仅版本号一行**改动；`TOOL_SPECS` 恒 3 工具。
- 收口总验：全量 **82/82** + 门禁 **9 项** + 冻结态（version 0.6.0、零配置 probe 即 available、补写默认关）+ Edge DOM（提纯模式/补写开关/两页说明均在场，补写开关**无 checked**）+ **不造假抽检**（A 档 5 条核心、B 档 5 条改写后核心，逐条逐字可定位）。
- 新增 `docs/S8-可信提纯验收.md`（三档落地对照、关键裁决、验证矩阵、5 条风险）；契约 v0.9.3 定稿；使用说明「三之三」章节重写为三档可信度说明。

### S8e · 升号 v0.6.0 并发布

- 软件版本 v0.5.0 → **v0.6.0**（S8 全新能力线 minor 升号）；规格 `SPEC.md` v2.11 冻结未改。
