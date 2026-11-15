# 更新日志

本文件记录「精核」软件版本的可感知变更。格式参照 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循语义化版本。

软件版本（`extract.py: __version__`）与 `SPEC.md` 的规格版本（v2.x）是两套编号，不要混淆。`SPEC.md` 为冻结的规格契约，不随本文件更新。

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
