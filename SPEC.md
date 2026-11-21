# 精核 · 阶段 1 输入格式矩阵与降级规格（v2.12）

> 本文件是共享任务 #2「建立输入格式矩阵与降级规格」的落盘定稿，按交付形态拍板（v2）更新。
> 只描述阶段 1「文件内容提取 + 汇总」的规格；阶段 2 核心提炼 / Word、阶段 3 音视频、阶段 4 知识库 / 自动化一律不提前实现。
> 本轮变更只涉及规格文档本身，未改动 `extract.py` / `samples` / `test_extract.py` / `out`。

## 0. 版本与变更记录

| 版本 | 变更 |
| --- | --- |
| v1 | #2 初版：五类分流矩阵、逐格式提取路径 / 依赖 / 失败模式 / 降级动作、出处定位规范、6 条红线。rich 组依赖声明为 `markitdown[all]` CLI，未安装时状态「待安装依赖 markitdown[all]」。结论此前仅在团队消息中传递，未落盘。 |
| v2 | 按交付形态拍板重构依赖总纲：软件本体走零依赖内置解析为主路径，markitdown 降为可选增强、须健康探测通过才启用、不随软件打包；矩阵新增「内置零依赖解析是否覆盖 / 可选增强启用条件」两列；写入本机实测事实；收敛「待安装依赖」口径；登记阶段 2 启动前已知限制。首次落盘为 `SPEC.md`。 |
| v2.1 | 按 lead 裁定新增 §1.1 交付口径（设计内降级语义、动态「验收口径」说明行、阶段 2 读清单约定）；将 §5 重写为出处定位字段定稿（src 8 字段固定顺序、块级锚点格式与 qa 门禁正则逐字对齐、排除清单 INDEX + MERGED 双落点）；§6 把 rich 六格式零覆盖限制标注「已解除」，并拆出剩余阶段 2 前置未完成项。 |
| v2.1.1 | sha256 字段口径裁定：§5.1 模板由 `<hash12>` 改为**完整 64 位小写十六进制**；理由——doc_id 已取 sha256 前 12 位，该字段若再放 12 位即同一份数据的冗余副本，既无法校验完整性也无法发现碰撞，完整值才能供阶段 2 做原文完整性校验与跨批次去重。此为「规格定稿 / 门禁期望 / 实现注入值」漂移的又一实例；其余章节不动。 |
| v2.2 | 按 lead 裁定新增 §3.G「文本编码前置预处理层（#10 口径）」：严格编码探测链（BOM / UTF-16 / UTF-8 / GB18030 / Big5 / Latin-1 兜底）、UTF-8 临时副本、INDEX / run.log 留痕原编码与转换决策、禁止 `errors="replace"` 静默吞、Latin-1 兜底须标注「编码不确定」；单列硬约束「doc_id 与 sha256 一律基于原始文件字节，UTF-8 临时副本绝不参与计算」；§5.1 术语统一为「原始文件字节」；§6.2 把块级锚点注入与摘要排除清单标注为已由 #9 第二批落地（待 qa 转正），GBK 前置预处理层为唯一剩余项，历史留痕文字不删。 |
| v2.3 | **#10 编码前置层已落地，本文档从「口径/待实现」改为与实现对齐**。§3.G 整节重写为已落地版：补入实测判定顺序与两条排序理由（UTF-32 BOM 先于 UTF-16、GBK 先于 GB18030、Big5 居后）、`latin-1(低置信)` 兜底口径、**副本必须与源文件同名**的规格级约束（否则 MERGED 去重正则失配、泄漏临时文件名标题）、`errors="replace"` 四项清除 / 三项保留的审计清单、INDEX 与 run.log 留痕的固定形状与段落位置、`samples/` 不新增 GBK 样例的范围决策；§3.A 的 `.txt` 行、§4 红线 6 由「剩余真缺口」改为「已修」但保留历史留痕；§6.1 / §6.2 更新现状数字并解除唯一剩余前置项，**阶段 2 启动前的前置项已全部收敛**。 |
| v2.3.1 | 订正与补记，v2.3 正文不动：① §6.1 改用 qa-verify 独立复跑的**权威数字**（25 / 25 / 0 门禁 / 0 失败 / 0 错误 / 0 意外成功，两入口 `Ran 25 tests / OK`）并写明演进链 `24(23+1) → 25(25+0)`，历史数字保留；② §3.G ⑥ 补记**断言演进**——第一版转正的两处弱断言（`assertIn("gbk")` 被 fixture 文件名 `gbk.txt` 满足；`assertNotIn("\ufeff")` 被 `normalize_markdown` 旧补丁掩盖）及 qa-verify 的变异证据与修法，含「断言不得被输入文件名满足」的通用教训；③ 新增 §6.4 两条实测已知边界（Latin-1 文本可能被 GBK 误判、大文件 + 非 UTF-8 的 3–4 倍内存与耗时）。 |
| v2.4 | **软件 v0.2.0 新增图形界面层，本节纳入规格**：§0 立「软件版本 / 规格版本」双轨制；新增 §8 界面层（文件职责、onefile 自我重入进程结构、9 条路由与 7 个 `/api/*` 契约、`idle → previewing → idle → running → done/cancelled/failed` 状态机、三条语义裁决、路径穿越防护、轮询而非 SSE 的理由、临时副本目录所有权规则）；§7 更新为 v0.2.0 完整文件清单；§6.4 追加界面层两条已知边界（依赖 Edge 应用模式、旧 cmd.exe 代码页 936 花屏）；§3.G ③ 的副本清理规则按「所有权与生命周期对齐」改写并交叉引用 §8.6。 |
| v2.5 | 非仅订正——§8 新增两条实质规则：① **§8.3 契约补齐**：未知 `/api/*` 的 **GET 与 POST 现在同形**，均 `404 + {ok:false,error}` JSON（此前 GET 走纯文本兜底，与 POST 不一致）；同时明确「静态资源缺失仍是文本 404」为**刻意区分**的第二条契约。② **§8.6 新增「孤儿目录清扫」第三路**：`finally` / `atexit` 在 `TerminateProcess`（任务管理器强杀、强关窗口）下都不执行，而原清扫只 glob 本进程 pid，旧 pid 的目录永远扫不到——改为启动时按精确形状正则扫 `%TEMP%` 并以保守存活判定清理，补齐硬杀场景的泄漏缺口。③ **§8.7 订正一处错误认识**：`--windowed` 下 `sys.stdout` 并非 `None`，而是「可写、写进去就丢弃」的哑对象，导致 `if sys.stdout is None` 恒假、`app.log` 从不落盘（真实双击场景只有目录没有文件）；判据改为「`sys.frozen` 为真**或**流为 `None`」，冻结后无条件落盘、原流可用时再 tee。④ **§7.1 数字刷新**到 v0.2.0 定稿值并新增 `pack.py`。 |
| v2.6 | **修复双击 / 浏览框「Failed to fetch」两类根因，端口改为固定 + 单实例**：① **STA 套间修复**——`pick_folder` 原用 `CoInitialize(None)`（=MTA），`IFileDialog` 必须在 STA 才能 `Show()`，MTA 上死锁使请求永不返回、前端 `fetch` 超时；改为显式 `CoInitializeEx(COINIT_APARTMENTTHREADED)`，并对 `RPC_E_CHANGED_MODE(0x80010106)` 回退旧式 `SHBrowseForFolderW`。② **固定端口 54321 + 单实例保护**——原默认端口 0 每次随机分配，重复双击 `ThreadingHTTPServer`（开 `SO_REUSEADDR`）在 Windows 上重复 `bind` 不抛 10048、两实例抢端口、一个退出后变死端口 → 前端对着死端口 `fetch` 必失败；改为 `DEFAULT_PORT=54321` 固定，启动先 `socket.connect((HOST,port))` 探活，已有实例在 listen 则本进程退出，比 bind 异常可靠。③ §8.7 端口口径由「默认自动选取」改为「固定 54321 + 单实例」（新增 §8.8）。④ §7.1 数字刷新到含上述修复的定稿值（app.py 1305 行 / 49739B、exe 8,708,966B / sha256 `3d0343ea…`）。 |
| v2.7 | **软件 v0.2.1：修「浏览看不到文件」与「中文 PDF 假成功」两处用户实测缺陷**。① **多选文件对话框**：新增 `IFileOpenDialog` 多选路径（`FOS_FORCEFILESYSTEM \| FOS_ALLOWMULTISELECT`，**不设 `FOS_PICKFOLDERS`**——该位正是「对话框只显示文件夹、用户以为目录是空的」的根因），STA 处理与 `pick_folder` 同构；新增端点 `POST /api/pick-files`。② **多输入贯通**：`-i/--input` 改为 `action="append"` 可重复，跨 root 合并按 `os.path.normcase` 保序去重，相对路径基准单 root 沿用旧式、多 root 用 `commonpath`（跨盘 `ValueError` 退化为文件名）；`Job(inputs, outdir)`、`/api/state` 新增 `inputs` 字段，`/api/dry-run`、`/api/run` 改为 `inputs` 优先、`input` 回退（**旧单值形态零变化**）。③ **界面新增文件清单**：预览后渲染 `items[{name,kind}]`（文件名 + 分类标签，可展开/收起，上限 500 条），解决「只给一个件数、无法确认识别到了什么」。④ **PDF CID 字体提取**（本次最严重缺陷）：原 `_pdf_extract` 把 `/Type0` + `/Identity-H` 的 2 字节字形号当字符编码解，中文 PDF 产出乱码却记「成功」——**假成功**。新增对象扫描（不依赖 xref）、`/FlateDecode` 流解码、`/ToUnicode` CMap 解析（bfchar / bfrange 递增 / bfrange 数组 / 多码元目标）、按字体 `Tf` 切换的按码宽查表解码、行基线聚行与阅读方向判定（兼容 WPS `1 0 0 -1 cm` 翻转）；**新增乱码门禁**：正文合理字符占比 <60% 判失败，状态 `需专用解析器`，宁报失败不出乱码。⑤ 订正 §1 中「`待安装依赖 markitdown[all]`」的误导性文案为可操作说明（本机 markitdown 因 `onnxruntime` 段错误不可用属环境事实，不是用户欠装的东西）。⑥ §7.1 数字刷新到 v0.2.1 定稿值。 |
| v2.8 | **软件 v0.2.2：对 v2.7 那轮整改做的自审修补（不是新功能）**。① **`/api/pick-files` 区分取消与失败**：原先两者都回 `{paths:[]}`，对话框打不开时前端只能表现为「点了没反应」——正是本工具反复被吐槽的无反馈模式；改为 `{paths, error}`，取消 `error=null`、失败带原因，前端显式报错。② **去掉输入框里的假路径**：多选后曾写 `C:\a.pdf 等 3 个文件`，它在**可编辑输入框**里，用户一敲字就触发 `input` 事件清空 `sel.inputs`，随后拿这个假串去提取 → 报「输入路径不存在：C:\a.pdf 等 3 个文件」；改为只填首个真实路径，件数交给 `inputMeta` 与清单标题，全量路径放 `title` 悬浮提示。③ **冻结态跳过 `-m markitdown` 候选**：exe 里 `sys.executable` 是 `Jinghe.exe`，`-m markitdown` 实为自身重入、被自家 argparse 拒绝（实测打印 usage、rc≠0），等于每次首遇富文档白拉一个 onefile 进程。④ **落盘口径去歧义**：INDEX / run.log 的「转换器」只描述文本类，改为 `技能脚本 md_convert.py（仅文本类；富文档解析另见标记）`——本机正是在 markitdown 崩溃、实际用内置解析时仍显示「技能脚本」，属二次误导。⑤ **PDF 缺字可见**：`/ToUnicode` 缺码位 ≥5% 时打 `[WARN]`，不改状态（提阈值会误伤正常子集字体）。⑥ **补回归**：`test_18` 把 `Show` 拦成「取消」，在不弹窗前提下锁住选项位（**不得含 `FOS_PICKFOLDERS`**、须含 `ALLOWMULTISELECT`）与三个过滤器——手写 COM 下标写错不会抛异常，只能靠断言兜住。⑦ §8.3 端点表补 `/api/pick-files` 与 `inputs` 字段（7 → 8 个）；§7.1 数字与冷启动实测（1.58–1.69s）刷新。 |

| v2.9 | **软件 v0.2.4：把多选文件对话框从 COM vtable 换成 Win32 API，彻底终结「打开文件选择框失败」**。① 用户实测反馈 `GetResults 0x00000000` → 改为 `0x80004005`，两次都是 `IFileOpenDialog::GetResults` 人工维护的 vtable 下标猜错（27 越界返回垃圾、25 调到别的方法）；**根因不是某个数字，而是这条 实现路线本身不可靠**。② `/api/pick-files` 的返回契约**不变**（`{paths, error}`，取消 `error=null`），但内部改走 `comdlg32.GetOpenFileNameW`：普通 Win32 函数 + `OPENFILENAMEW` 结构体，无 vtable、无 STA 套间要求，`OFN_ALLOWMULTISELECT | OFN_EXPLORER` 支持多选与三档文件过滤器，`OFN_NOCHANGEDIR` 防止改动服务进程 CWD，64K wchar 缓冲超限时给出可操作提示。③ 删除已废弃的 `_pick_files_com`、`_COMDLG_FILTERSPEC` 及 `_VT_GET_RESULTS` / `_VT_ARR_*` 等错误下标常量，杜绝再被 改错；「选择文件夹」仍用 IFileDialog（COM 下标只服务该路径）。④ `test_18` 重写为 `test_18_pick_files_win32_contract`：不弹窗锁定 OPENFILENAMEW ABI 尺寸（x64=152 / x86=88）、关键选项位、过滤器与双 NUL 结尾、多选缓冲切分/路径还原、**`pick_files_ex` 不得再触碰 `_com_method`**、取消与失败语义。⑤ **真机端到端验证**：自动弹出对话框、填入两个真实文件并点确定，生产函数返回两条正确路径（PASS）；`test_app.py` 18/18、`test_extract.py` 27/27 全绿。 |

| v2.10 | **软件 v0.2.5：治理「仅预览分流」无反馈隐患 + 后端两类加固 + 新增产物入口**。**定性校正（重要）**：本轮回应的用户反馈「提取成功后打开 .md、关掉再点『仅预览分流』没反应」，最终定性为——前端 `api()` 原本是裸 `fetch` **无超时**、`doPreview()` 用 `.then()` 冒充 `.finally()` 复位状态，是可证实的机制缺陷（会话日志确有 3 次 `ConnectionResetError 10054`，响应体未完整送达时 Promise 永不落定 → `previewing` 永久 true → 按钮被禁用且点击被静默吞掉）；但**不能断言「已复现锁死」**——日志里 open 之后仍有 5 条 dry-run 到达且服务端已回，且 `/api/progress`、`/api/state` 不打日志、日志只证「开始发送响应」而非「送达」，故本次是**根治隐患**而非修复已坐实的故障。① **前端**：`api(path, body, timeoutMs)` + `AbortController` 分级超时（dry-run 40000 / progress·state·cancel·open·run 10000 / pick-* 0 不 abort）/ 超时中文归一化「请求超时，已自动恢复，请重试」；`doPreview`·`browse`·`pickFiles` 的 cleanup 改 `.finally`；`finish()` 与 `init()` 兜底复位 `running`/`previewing`；`init()` 的 `if (st.running)` 改为先带超时确认 `/api/progress` 再决定是否 `startRunning`；`doCancel` 补 `.then`、`doRun` 加 `typeof` 守卫与 catch 复位。② **消除观感缺口**：预览成功/失败在 `inputMeta` 写**带 HH:MM:SS 时间戳**的常驻文案（输入不变也能看出已响应）；新增「打开合并文档」按钮（默认 disabled、不进 `updateControls` 禁用列表、`finish()` 在任务成功且有 outdir 时启用），弥补「关闭 MERGED.md 后无入口重开」；界面加一行说明「仅预览分流只盘点分类，不生成文件、不打开文档」。③ **后端加固（非根因，但消除同类隐患）**：`DRY_RUN_TIMEOUT` 由 600s 收敛为 30s，超时单独分支返回中文「预览超时（超过 30 秒）：目录过大 / 文件被占用 / 位于网络盘，请缩小选择范围」；`_run_job_inner` 把 `job.running = False` 放进 `finally` 并把异常路径 `state` 置 `failed`；新增 `_reap_dead_job()` 僵尸任务兜底（判据：`running=True` 且线程为 None 或已退出），在 `/api/state`、`/api/progress`、`/api/run` 三处调用。④ **排查方法论沉淀**：`app.py` 日志在 `send_response()` 写状态行时打印、**早于** `wfile.write(body)`（`except (BrokenPipeError, ConnectionResetError)` 静默吞写失败），故日志出现不代表响应体送达；`/api/progress`、`/api/state` 不打日志；日志条数 ≠ 点击次数——以后不要仅凭「日志出现」断定响应送达，也不要仅凭「零日志」断定按钮锁死。⑤ 回归：`test_app.py` 24/24（新增 `test_19` dry-run 契约、`test_20` 预览不污染状态、`test_21` 静态资源 no-store、`test_22` 前端锁静态契约、`test_23` 运行态复位、`test_24` 僵尸 job 兜底）、`test_extract.py` 27/27 全绿。 |

| v2.11 | **软件 v0.2.6：新增「打开输出目录」按钮，弥补只看到文件夹、看不到导出内容的缺口**。① 现状：提取产物落在 `out-<时间戳>`（含 `MERGED.md` / `INDEX.md` / `md/*.md` / `provenance.json` / `run.log`），但「输出与选项」卡片此前只有「打开合并文档」（仅开 `MERGED.md`）与「更改」（输出目录选择器，文件夹对话框本就只显示文件夹）——用户没有一键打开整个输出文件夹的入口，于是「打开只能看到文件夹、看不到导出内容」。② 改动：UI 新增「打开输出目录」按钮（默认 disabled、不进 `updateControls` 禁用列表、`finish()` 在任务成功且有 `outdir` 时启用），点击经 `POST /api/open` 传 `outdir`，后端 `os.startfile(dir)` 用资源管理器打开该目录；复用既有静态契约，纯前端改动、后端 `/api/open` 已天然支持目录。③ 实测产物目录结构复核确认内容正常生成（顶层 `MERGED.md` / `INDEX.md` 与 `md/` 子目录均在），故本次是补入口而非修生成。 |
| v2.12 | **规格随软件 v1.1.x 的 Electron 化同步修订（规格版本独立轨道，仅描述界面外壳变更，阶段 1 提取语义一字未动）**。① §6.4 限制 C 由「依赖 Edge 应用模式」改写为「Edge → Electron 自带 Chromium」：默认发布形态改为 Electron 外壳，目标机器无需 Edge / Python / Node，原 Edge 路径降为源码态调试回退；记录体积代价（~10MB → 免安装 ~267MB / NSIS ~60–100MB）与用户裁决（接受）。② §8.1 文件职责：`app.py` 的窗口启动器口径改指 Electron `--no-browser`，新增 `electron/` 目录职责说明。③ 新增 §8.2.1「Electron 外壳进程结构」：两层进程、单实例、后端复用探测、关窗回收、`--cli` 自我重入不变、`latest.yml` 自更新元数据。④ 规格版本 v2.11 → v2.12。**这说明「规格同步」实现的是规格文档与实现的一致性，不是新增软件功能**；§8 首段「界面只消费 `extract.py` 产物、不改变阶段 1 语义」的铁律继续成立。 |

### 0.1 版本号双轨制（v2.4 立规，防误用）

| 轨道 | 载体 | 当前值 | 递增规则 |
| --- | --- | --- | --- |
| **软件版本** | `extract.py` 的 `__version__`（`--version` 输出） | `0.2.6` | 语义化版本，随**功能交付**递增 |
| **规格版本** | 本文件标题与本节表格 | `v2.11` | 随**文档修订**递增 |

- **二者不同步、不互推**：规格改到 v2.4 不代表软件是 2.4；软件升到 0.3.0 也不必让规格跳到 v3。
- **禁止**把本文件的 `v2.x` 当作软件版本写进产物、界面、`INDEX.md` 或安装包名；也禁止用 `__version__` 反推规格章节号。
- 需要对外报版本时一律报**软件版本**（`0.2.6`）；需要追溯契约变更时一律报**规格版本**（`v2.11`）+ 章节号。

## 1. 交付形态与依赖总纲（拍板结论）

**用户悬置问题的答案：markitdown 不跟软件走。** 软件本体以标准库零依赖解析为主路径（`zipfile` / `xml.etree` / `zlib` / `re` / `csv` / `html.parser` / `json`）；`markitdown` 仅为**可选增强**，用于提升结构还原质量，**不随软件打包**。本机这一轮安装只是验证用途，且验证结论为「不可用」。

### 可选增强启用条件（硬规则）

1. **必须做实际子进程冒烟探测**：以子进程执行 `markitdown --version`（或等价入口），**返回码为 0** 才判定可用；探测一次性执行并做模块级缓存。
2. **`importlib.util.find_spec("markitdown")` 为 True 不代表可用**——本机即为反例（find_spec 为真，但任何实际调用均段错误）。禁止以 find_spec / import 成功作为启用依据。
3. **探测失败一律静默回退内置解析**：不得污染用户可见状态、不得把段错误写成「转换失败」、不得因增强不可用而把条目计入未成功。可选增强不可用属于「环境能力缺失」，不是「该文件的转换失败」。
4. 探测通过才启用增强；增强仅提升结构还原质量，**不改变**分流、降级、件数对账、留痕与出处定位语义。
5. 增强启停不写入 INDEX / run.log 的失败项；如需留痕，只作为工程诊断信息，不进入用户可见状态列。

### 1.1 交付口径裁定 (a) · 设计内降级（阶段 2 读清单约定）

- 降级样例保留在**主样例集 `samples/`**，不另置旁路目录。因此 `out/` 的验收结论恒为 `部分未完成，见 INDEX.md 未成功项`，**该文案作为测试契约一字不改**（含后缀，不得简写为「部分未完成」）。
- **语义约定（关键）**：未成功项全部是**设计内降级**——「待人工授权 / 需 OCR / 需拆分 / 需预处理 / 无效容器 / 阶段 3 预留 / 不支持」等状态是软件**按规格正确处置**的结果，**不是软件缺陷、不代表阶段 1 未完成**。
- `INDEX.md` 与 `run.log` 必须追加**动态生成的「验收口径」说明行**：按状态分项统计各类降级数量，**严禁硬编码**任何数字或固定段落；数字须由本次运行记录实时汇总。
- **阶段 2 读清单时的口径约定**：下游（摘要流水线 / 知识卡片）读取 INDEX / run.log 时，须按上述语义把降级项视为「已按规格处置的输入」并显式跳过或标注，**不得把降级项当 bug 处理、不得据此判定阶段 1 未交付**。

## 2. 本机实测事实（写入矩阵依据，team-lead 亲自核验）

- 基础包安装完成：`markitdown 0.1.9`、`magika 1.0.3`、`onnxruntime 1.31.1`、`numpy 2.5.4`、`markdownify 1.2.3`、`beautifulsoup4 4.15.0`、`charset-normalizer 3.5.2`，落在 `.../versions/3.13.12/Lib/site-packages`。
- `shutil.which("markitdown") = None`；`markitdown.exe` 位于 `C:\Users\songweihu\.workbuddy\binaries\python\versions\3.13.12\Scripts\`，**未加入 PATH**。
- `python -c "import markitdown"`、`python -c "import onnxruntime"`、`python -m markitdown --version` **全部 exit=139 Segmentation fault**（onnxruntime 二进制层崩溃）。
- `pip install "markitdown[all]"` 26 分钟卡死已终止。
- 解析库未安装：`pdfminer` / `pdfplumber` / `fitz` / `pypdf` / `docx` / `pptx` / `openpyxl` / `ebooklib` / `lxml` / `pandas`（**注：`bs4` 随本次基础包已装上**）。
- **结论**：依赖「装上了」不等于「能调用」；`find_spec` 为真不等于可用；唯一可信判据是实际子进程冒烟探测返回 0。

## 3. 逐格式依赖矩阵

统一列定义：
- **内置零依赖覆盖**：软件本体标准库是否覆盖该格式的提取。
- **提取路径**：实际执行链路。
- **已知限制**：格式级或环境级限制。
- **可选增强启用条件**：见第 1 节硬规则；`不适用` 表示该格式无需增强。

### 3.A 文本类 · 技能脚本组（`.txt` / `.text` / `.log` / `.html` / `.htm` / `.csv`）

| 格式 | 内置零依赖覆盖 | 提取路径 | 已知限制 | 可选增强启用条件 |
| --- | --- | --- | --- | --- |
| `.txt` `.text` `.log` | 是 | 技能脚本 `md_convert.py` 的 CONVERTERS；脚本缺失 / 加载异常 → 内置等价转换器（`re`） | GBK / GB2312 编码**已由 #10 编码前置层解决**（v2.3）：入转换器前按原始字节严格探测 → 同名 UTF-8 临时副本，U+FFFD = 0、原文可回溯（口径见 §3.G）。历史留痕：v2.3 之前主链路 `errors="replace"` 静默吞乱码，属当时真缺口 | 不适用（内置已完整覆盖） |
| `.html` `.htm` | 是 | 技能脚本 HTML 转换器 / 内置 `html.parser`，剔除 script / style / head / svg，保留标题 / 表格 / 列表 / 链接 | 仅静态 HTML，JavaScript 动态渲染内容丢失（需浏览器渲染 / Playwright，阶段 1 只标注不实现）；UTF-8 BOM 污染表头、表格行首空格、`<a>` 只剩右括号三类已由 `normalize_markdown` 修补 | 可选（正文剔除质量），须健康探测通过 |
| `.csv` | 是 | 技能脚本 / 内置 `csv.reader` → Markdown 表格，列宽补齐、单元格竖线转义 | 空 CSV 产出「带 source 头 + 空内容注释的占位 md」计入成功（合规），须 INDEX 备注「源文件无实质内容 / 占位产物」并纳入阶段 2 摘要排除清单（双落点见 §5.3） | 不适用 |

### 3.B 文本类 · 内联组（`.md` / `.json` / `.xml`）

| 格式 | 内置零依赖覆盖 | 提取路径 | 已知限制 | 可选增强启用条件 |
| --- | --- | --- | --- | --- |
| `.md` | 是 | `normalize_markdown` 原样修补（去 BOM、表格行首空格、连续空行） | front-matter；源文件一级标题与合并链路层级冲突（`demote_headings` 降位两级） | 不适用 |
| `.json` | 是 | `json.loads` + `json.dumps(indent=2, ensure_ascii=False)` 美化后包 JSON 代码块 | 语法错误时降级为源码包裹，**须显式标注**而非静默记「成功」 | 不适用 |
| `.xml` | 是 | 原样包 XML 代码块；文本节点可用 `xml.etree` | CDATA / 命名空间 / 实体不解析文本节点；降级为源码包裹须标注 | 不适用 |

### 3.C 富文档组（`.pdf` / `.docx` / `.pptx` / `.xlsx` / `.epub` / `.zip`）—— 依赖总纲变更的核心

| 格式 | 内置零依赖覆盖 | 提取路径 | 已知限制 | 可选增强启用条件 |
| --- | --- | --- | --- | --- |
| `.pdf` | **部分** | 原始字节 `re` 探测文字层（BT 文本对象 + Tj / TJ 操作符）+ `zlib` 解 FlateDecode 流提取文本 | 扫描件（无文字层）判「需 OCR」，须 Azure Document Intelligence / 本地 OCR，阶段 1 只标注；复杂排版 / 嵌入字体可能丢结构；有文字层但无法可靠还原 → 「转换失败 / 待专用解析器」 | 健康探测通过才启用（提升表格 / 结构还原），否则静默回退内置 |
| `.docx` | 是 | `zipfile` 解 OOXML 容器 + `xml.etree` 取 `word/document.xml` 标题 / 段落 / 表格 | 多栏排版、文本框、艺术字丢格式；VBA 宏不提取；**Office「限制编辑」不阻碍读取，正常提取**（仅真正加密 / 口令判「待人工授权」） | 同上 |
| `.pptx` | 是 | `zipfile` + `xml.etree` 取幻灯片标题 / 正文 / 备注区文本 | SmartArt、动画、嵌入视频不转换 | 同上 |
| `.xlsx` | 是 | `zipfile` + `xml.etree` 取工作表 / 共享字符串 → Markdown 表格 | 公式仅缓存值、不重算（需 LibreOffice `--headless --calc --convert-to xlsx` 强制重算）；图表 / 图片 / SmartArt 丢弃；多工作表须按 sheet 定位 | 同上 |
| `.epub` | 是 | `zipfile` + `xml.etree` 按 spine / 章节提取 | 需保留章节序号（chapter 锚点） | 同上 |
| `.zip` | 是 | `zipfile` **仅展开一层**，逐成员按扩展名再分流 | **嵌套 ZIP 不递归**（须先递归解压再批量转换）；加密 ZIP（成员 `flag_bits & 0x1`）判「待人工授权」；**无效 OOXML / ZIP 容器**落「转换失败：文件无法识别（非有效 OOXML / ZIP 容器）」独立状态，不判「待人工授权」 | 同上 |

> 加密文档判定须为**正向证据命中**（PDF `/Encrypt`、ZIP 成员 `flag_bits & 0x1`、Office 敏捷加密 `EncryptionInfo` / `EncryptedPackage`、EPUB `META-INF/encryption.xml`）；「读不出来 / 容器损坏」是反向失败，绝不能因解析不通反猜成加密。真正加密一律单列「待人工授权」，终止该项、不破译、不盲重试。

### 3.D 阶段 3 预留组（音视频）

| 格式 | 内置零依赖覆盖 | 提取路径 | 已知限制 | 可选增强启用条件 |
| --- | --- | --- | --- | --- |
| 音频 `.mp3/.wav/.m4a/.aac/.flac/.ogg/.wma/.amr`；视频 `.mp4/.mov/.avi/.mkv/.flv/.webm/.m4v` | 不适用（不解析） | 一律标记「阶段 3 待支持」，不纳入转换候选、不调用任何 ASR、不产出 md | **红线：不得把视频当音频转写**；时间戳 / 字幕 / ASR 全部留给阶段 3 | 不适用 |

### 3.E 需预处理 / 不支持组

| 格式 | 内置零依赖覆盖 | 提取路径 | 已知限制 | 可选增强启用条件 |
| --- | --- | --- | --- | --- |
| `.doc` `.xls` `.ppt` | 否 | 标记「需预处理」，不解析、不产出空文件 | 旧版 OLE 二进制，内置解析与 MarkItDown 均不支持；须 LibreOffice 转 OOXML（`.docx` / `.xlsx` / `.pptx`）后再纳入 | 不适用（属外部预处理） |
| 其他扩展名 | 否 | 标记「不支持」，显式留痕 | 不在支持清单 | 不适用 |

### 3.F 横切约束

- 单文件 `>100MB`：「需拆分」，不一次性加载，按页 / 工作表分段后逐件转换并对账件数（红线 5）。
- 交付前自检：件数对账（含 `md/*.md` 实盘数与成功记录数的**双向对账**）、空文件扫描、标题 / 表格抽检；不一致判「部分未完成」并列出孤立 / 缺失产物。
- 产物目录写前清理陈旧 `.md`，防止编号漂移产生「幽灵来源」。

### 3.G 文本编码前置预处理层（#10 · 已落地，本节与实现对齐）

> **历史根因（留痕，不删除）**：GBK 编码的 `gbk.txt`（「知识提取阶段一编码边界样例」）经 v2.2 之前的主链路，rc=0 但产物含 **13 个 U+FFFD**、原文完全丢失——转换器报「成功」，实际已静默丢字，属最危险的降级形态，`test_gate_gbk_encoding` 因此长期为 expectedFailure。代码事实（当时）：`_smart_text()` 已实现 BOM / UTF-16 / UTF-8 / GB18030 / Big5 / Latin-1 严格解码，但只服务富文档内置解析；文本入口 `convert_text_file` 与 `_fallback_converters` 仍是 `utf-8 + errors="replace"`。
> **落地现状**：新增 `decode_text_bytes()` / `preprocess_text_encoding()`（extract.py:257 / :276，区块位于 `normalize_markdown` 之后、出处定位最小集之前）。`extract.py` 59869B / 2026-11-12 17:58:34，`py_compile OK`。

1. **判定顺序（实现事实，非设计意图）**
   - `_BOMS`：UTF-8 BOM → **UTF-32 LE → UTF-32 BE** → UTF-16 LE → UTF-16 BE。**UTF-32 两种 BOM 必须排在 UTF-16 之前**：`\xff\xfe\x00\x00` 以 `\xff\xfe` 为前缀，顺序颠倒会把 UTF-32 LE 误判成 UTF-16 LE，NUL 字节混进正文。BOM 命中但严格解码抛错时视为「BOM 不可信」，落回严格链，不硬认。
   - `_STRICT_CHAIN = ("utf-8", "gbk", "gb18030", "big5")`。**GBK 先于 GB18030 只为拿到更精确的编码名**：GB18030 是 GBK 超集，任何 GBK 文件都能被它解开，只是标签会宽泛成 `gb18030`，不影响正确性；**Big5 居两者之后**：简体场景 GBK 命中率远高，先判 Big5 会把部分 GBK 误标。该排序是**启发式**而非判定器：西欧文本存在假阳性（`E9 58` 可被当作合法 GBK 双字节），属已知边界、本轮不引入 CJK 占比二次判定，见 §6.4 限制 A。
   - 全链严格解码失败 → Latin-1 兜底，编码名固定写作 **`latin-1(低置信)`**、判定依据写「严格解码链全部失败，Latin-1 兜底（可能损失原文）」，**不得伪装成成功解码**。
   - 全流程 `errors="strict"`，任何环节不得用 `replace` 吞字节；产物出现 U+FFFD 即视为失败交付。
   - **不得依赖 markitdown 修复**：其内部同样 `errors=replace`，且本机 import 即 `exit=139`（见 §2）。

2. **⚠ 硬约束（最关键，单列）**：`doc_id = doc_ + sha256(原始文件字节)[:12]`，src 注释第 7 字段 `sha256` 为**原始字节的完整 64 位小写 hex**（见 §5.1）；**UTF-8 临时副本只用于喂转换器，绝不参与 `doc_id` / `sha256` 计算**。否则同一份文件会产生随编码变化的 doc_id，provenance manifest、MERGED 目录锚点与块级锚点全部失效。（实现上 doc_id 在 `collect` 阶段基于原始字节算好，前置层不复算、不改写。）

3. **副本策略**
   - **无 BOM 的纯 UTF-8**（判定结果恰为 `utf-8`）：**原路径直接喂转换器，零复制、零副作用**。
   - 其余编码（`utf-8-sig` / UTF-16 / UTF-32 / GBK / GB18030 / Big5 / latin-1）：在 `tempfile.mkdtemp(prefix="jinghe-enc-")/<4 位 slot>/` 下写 UTF-8 副本；slot 即候选序号，保证不同目录下同名文件不互相覆盖。
   - **⚠ 副本必须与原文件同名**（规格级约束，非风格偏好）：转换器用 `Path(path).name` 生成 `# <文件名>` 一级标题，MERGED.md 用 `re.sub(r"(?m)^#\s+" + re.escape(stem) + ...)` 去掉重复标题；副本一旦改名，该正则失配，产物会多出一行「临时文件名」标题。这是实测发现的隐性耦合。
   - dry-run 等只读场景（`workdir` 为 `None`）**只留痕不落副本**。
   - 工作区清理**按目录所有权分两路**（v0.2.0 修正）：命令行独立运行时自建 `jinghe-enc-*` 并用 `atexit.register(shutil.rmtree, ..., True)` 自清；**图形界面运行时优先沿用环境变量 `JINGHE_ENCDIR` 指定的父进程目录，此时不自建 `mkdtemp`、不注册 atexit，清理责任在父进程**（理由与完整规则见 §8.6）。任何情况下不写回源目录。
   - 样本集实况：唯一非 UTF-8 文件是 `glossary.csv`（`utf-8-sig` / BOM）。此前靠 `normalize_markdown` 的 `replace("\ufeff","")` 打补丁，现由前置层从源头处理；该补丁保留作双保险。

4. **`errors="replace"` 清除范围（审计口径：四项清除、三项保留）**
   - **已清除（改严格 `utf-8`）**：`_fallback_converters` 的 txt(:169) / html(:174) / csv(:179) 三处、`convert_text_file` 的 `raw = path.read_text(...)`(:465)。
   - **保留（合法用途，不得误判为遗漏）**：`_markitdown_healthy`(:873) 与富文档子进程调用(:936) 的 `subprocess.run(..., errors="replace")`——解码外部进程 stdout，不是源文件；`sys.stdout.reconfigure(..., errors="replace")`(:1011)——控制台输出。
   - **语义变化（故意的）**：前置层保证入参为 UTF-8，故下游统一严格解码；万一前置层被绕过会抛 `UnicodeDecodeError`，该条目落「转换异常: …」。**响亮失败优于静默吞字节**——这正是本层要消除的静默降级。

5. **留痕形状（供机械核对）**
   - INDEX 汇总行：`- 文本编码前置层：文本类 <N> 个，非 UTF-8 <M> 个（已转 UTF-8 临时副本喂转换器；原文件字节未改，doc_id / sha256 仍基于原始字节）`
   - INDEX 明细段 `## 文本编码前置处理明细`，逐条 bullet：`` - `<rel>` ｜ 原编码：<enc> ｜ 判定：<basis> ｜ 处理：UTF-8 临时副本（原 <bytes> 字节，原文件未改） ``；**该段位置固定在「## 本期不包含」之后、「## 阶段 2 摘要排除清单」之前**——否则其 `- ` bullet 会被排除清单解析误吞，污染 §5.3 的双落点核对。
   - run.log：汇总 `- 编码前置: 文本类 <N> / 非 UTF-8 <M>`，逐条 `- 编码: <rel> 原编码 <enc>（<basis>），已转 UTF-8 临时副本 <bytes> 字节`（不以 `-[状态] … ->` 形式出现，避免与状态记录行混淆）。
   - 官方重跑实测（`out/`）：汇总「文本类 6 个，非 UTF-8 1 个」，明细 1 条 `glossary.csv ｜ utf-8-sig ｜ BOM: UTF-8 ｜ 265 字节`。

6. **验收口径与现状**：GBK 中文原文完整可回溯、产物 **U+FFFD = 0**、INDEX / run.log 记录原编码与转换决策。`test_gate_gbk_encoding` 已于 17:58 **转正为 `test_24_no_lossy_encoding`**，并新增 `test_25_bom_strip`（BOM 去除边界，确保 `\ufeff` 不泄进首行标题 / 表头）；测试集当前**无 `@expectedFailure` 门禁**。
   - **权威数字（qa-verify 独立复跑，两入口一致）**：用例总数 **25** / 正式通过 **25** / `@expectedFailure` 门禁 **0** / 失败 **0** / 错误 **0** / 意外成功 **0**，两入口均 `Ran 25 tests / OK`（`test_extract.py` 75821B / 18:12:20）。演进链：`24（23 正式 + 1 门禁）→ #10 转正 test_24 + 新增 test_25 → 25（25 正式 + 0 门禁）`。早期「24 项 = 21 正式 + 3 门禁」是 test_22 / test_23 转正**之前**的数字，仅作历史留痕。
   - **断言演进（v2.3.1 补记：第一版转正有两处弱断言，被 qa-verify 另选角度的变异抓出）**
     - **弱断言 1（真缺陷）**：原 `assertIn("gbk", index_text)` 可被 fixture 文件名 `gbk.txt` 里的 `gbk` 子串满足——把 `_STRICT_CHAIN` 中的 `"gbk"` 删掉（编码名退化成 `gb18030`）后 test_24 **仍然通过**，只有把输入改名成 `legacy.txt` 再跑同样变异才 FAIL。**通用教训：断言不得被输入的文件名 / 路径满足，fixture 命名须避开被测关键字。**
       修法：fixture 改名 **`cp936-legacy.txt`**（文件名不含被测编码名），并同时锚定三处留痕——INDEX `原编码：gbk`（全角冒号）、run.log `原编码 gbk`、**`严格解码命中 gbk`**；第三条是唯一能抓退化的（退化后「原编码」「编码前置」两条仍成立）。
     - **弱断言 2**：`assertNotIn("\ufeff", body)` 在 #10 之前也能通过，因为 `normalize_markdown` 本就有 `text.replace("\ufeff","")`——断言测到的是旧补丁而非前置层。修法：用例内 `import extract` 直调 `preprocess_text_encoding` 做单元级断言，并顺带锁上两条此前无人验证的契约：**副本必须与源文件同名**、**纯 UTF-8 必须零复制（`converted is False` 且 `feed == 原路径`）**。
     - **修后变异证据**：M-c（删 `gbk` 链）FAIL @919、M-e（前置层形同虚设）FAIL @965、M-f（副本改名）FAIL @987、M-a（副本带 BOM）FAIL @991；副本恢复后两入口 25/25 全绿。
     - **工程注脚**：`import extract` 实测 0.158s，模块级**不探测 markitdown、不起子进程、不写文件**（`_MARKITDOWN_PROBED` 保持 `False`），故测试内导入无副作用。

7. **边界与范围决策**
   - **不改技能脚本 `md_convert.py`**（外部文件）；其内部仍 `errors=replace`，由前置层保证入参 UTF-8 来规避，不在本层修复。
   - **`samples/` 不新增 GBK 样例（刻意决策）**：会打乱 19 / 18 / 12 / 6、排除清单 8 条、锚点 34 条等既有基线，收益不抵成本；GBK 覆盖由回归测试在临时目录自建 fixture 承担（`test_24`）。
   - `_smart_text()`（富文档内置解析用）与前置层并存，判定链一致但代码独立；是否合并为单一实现须单独立项，**不在 v2.3 范围**。
   - 不做阶段 2-4。

## 4. 降级口径 v2（收敛旧「待安装依赖」）

**作废**：v1 中 rich 组未装 markitdown 时统一落「待安装依赖 markitdown[all]」的口径，以及「『待安装依赖』优先级高于『需 OCR』」「20 字符阈值作为扫描件判据」三条。

**新口径**：

1. **环境阻塞与内容阻塞分离**。可选增强不可用时**静默回退内置解析**（不产生用户可见的失败状态）；只有内置解析本身失败才计入未成功。扫描件不该等装完依赖才暴露。
2. **「需 OCR」只由内容探测触发**：基于真实内容流（BT 文本对象 + Tj / TJ 操作符或等效）确认无文字层；**不绑定依赖是否安装**；严禁凭文件名、体积、扩展名猜测；run.log / INDEX 须记录判定依据（如「文字层探测: 无 BT / Tj / TJ」）以便复核。
3. **有文字层但当前解析器无法可靠还原** → 落「转换失败 / 待专用解析器」，**计入未成功，绝不产出乱码**。
4. 上述两类（内容阻塞、转换失败）均须：不产出空文件或乱码、计入未成功、INDEX / run.log 显式留痕、验收「部分未完成」。
5. **可选增强健康探测失败（含 exit=139 段错误）**：静默回退内置解析，**不得污染用户可见状态、不得把段错误写成「转换失败」**。

### 红线清单（v2 下继续有效）

| # | 红线 | v2 口径要点 |
| --- | --- | --- |
| 1 | 不得静默产出空文件 | 禁止 0 字节 / 无 source 头 / 异常项未留痕 / 对账不平却判「通过」；源文件为空时带 source 头 + 显式空标记的占位 md 计入成功属合规 |
| 2 | 不得把视频当音频转写 | 音视频并列 deferred，不解析、不调 ASR、不产出 md |
| 3 | 扫描件无文字层必须标记需 OCR | 由内容探测触发，人审后方可落库 |
| 4 | 加密文档不破译 | 正向证据命中 → 单列「待人工授权」，终止该项、不重试、不破译；不得与「转换失败」「需 OCR」混淆 |
| 5 | 单文件 >100MB 必须拆分 | 拦截、分段、逐件对账 |
| 6 | GBK 编码先转 UTF-8 | 前置预处理层转码、禁止 `errors="replace"` 静默吞乱码、转换后重跑留痕。**已落地（v2.3）**：#10 编码前置层 + `test_24_no_lossy_encoding` / `test_25_bom_strip` 转正，口径与审计清单见 §3.G；v2.3 之前为「剩余真缺口」 |

## 5. 出处定位字段定稿（归 #9 第二批）

本批（#9 第一批）交付的是富文档真实样例与逐格式实跑证据；**出处定位最小集属 #9 第二批**，以**追加式兼容**落地，不覆盖既有产物格式。本节为**字段级定稿**，核心目的是消除「规格定稿 / 门禁期望 / 实现注入值」三者漂移——此前门禁正则按字面 `doc_id` 匹配、而实现注入真实 ID，即此类坑。凡本节出现的占位符，实现必须注入真实值，且规格须与门禁正则逐字对齐。

### 5.1 来源注释（双行，追加不覆盖）

- **首行原样不动**：`<!-- source: 相对路径 | format: .ext | extracted: 时间 -->`（qa `test_05` 契约，禁止改写或删除）。
- **另起一行追加机器可读字段**，8 字段**固定顺序、全必含**，`key: value` 冒号形式、` | ` 分隔：
  `<!-- src: <doc_id> | path: <规范化相对路径> | format: <ext> | converter: <> | extracted: <stamp> | size: <bytes> | sha256: <完整64位小写hex> | anchors: <键列表> -->`
- `doc_id = doc_ + sha256(原始文件字节)[:12]`，**只含内容哈希、不含路径字符**；规范化相对路径仅作绑定字段，不进 doc_id；**「原始文件字节」不含 §3.G 的 UTF-8 临时副本**。
- **`sha256` 字段必须用完整 64 位小写十六进制**：`doc_id` 已取 sha256 前 12 位，该字段若再放 12 位就是同一份数据的冗余副本，既无法校验完整性也无法发现碰撞；完整值才能供阶段 2 做原文完整性校验与跨批次去重。
- `anchors` 为该文件实际定位键名列表；**无锚点写 `none`，不留空**。
- MERGED 目录锚点改用 `doc_id`（不用路径）。

### 5.2 块级锚点（逐块注入）

- 统一载体，**每块前插一条**：
  `<!-- anchor: doc_<真实12hex> | block: N | page: N | slide: N | sheet: <名> | chapter: N | member: <path> | line: A..B -->`
- `doc_id` 必须是**真实值**（`doc_` + 12 位十六进制），不是字面占位符；key 用冒号形式、` | ` 分隔；**只填该格式实际用得上的定位键**，不适用的键省略而非留空；`heading_path` 为可选扩展。
- 定位键按格式：PDF→`page`、PPTX→`slide`、XLSX→`sheet`、EPUB→`chapter`、ZIP→`member`、DOCX→`heading_path` / `block`、文本类→`line` / `block`；`block` 在单文件内单调递增。
- **与 qa 门禁正则逐字一致**：`<!--\s*anchor:\s*doc_[0-9a-f]{12}\s*\|`。规格中的 `doc_<真实12hex>` 必须与该正则匹配；实现不得写字面 `doc_id`，否则门禁永不 unexpected success、无法转正。
- 接口：`make_anchor(doc_id, block_idx, **locators) -> str`、`parse_anchor(comment) -> dict`。

### 5.3 阶段 2 摘要排除清单（双落点）

- `content_status` 归 `provenance manifest`（结构化产物），字段语义含 `normal` / `placeholder` 等。
- **人可读的排除清单必须同时出现在 `INDEX.md` 与 `MERGED.md` 两处**：逐条列出 `content_status != normal` 的 `doc_id`、`path`、**原因**。仅写进 manifest 而不落到这两个人可读产物，qa 门禁（检查 INDEX + MERGED 文本）将永远无法 unexpected success、转不了正。
- 该清单即阶段 2 摘要流水线的跳过依据，与 §1.1 的设计内降级语义一致。

### 5.4 边界

- `provenance manifest`、块级锚点、排除清单同样**追加**、不覆盖既有产物格式；合并链路不得剥离来源信息，`demote_headings` 须保留原始层级元数据。
- **接口定义与注入属 #9，#6 只做引用级 `(doc_id, anchor)` 回填。**

## 6. 阶段 2 启动前已知限制（v2.4：解除条件、前置项收敛状态、已知边界分开记载）

### 6.1 已解除：rich 六格式零真实提取覆盖

- **原限制（留痕，不删除）**：#9 第一批完成前，rich 六格式（`.pdf`/`.docx`/`.pptx`/`.xlsx`/`.epub`/`.zip`）零真实提取覆盖；当时 23 项回归（20 正式通过 + 3 expectedFailure 门禁 + 0 失败 / 错误 / 意外成功）只覆盖文本类 / deferred / legacy 分支与分流、降级、件数对账、留痕链路，不证明 rich 六格式可提取，阶段 2 不得假定产物齐备。
- **解除依据（#9 第一批已落地）**：新增 **6 个真实富文档样例**与逐格式实跑证据，主样例集扩至 **19 样例 / 12 成功 / 6 降级**；六格式均有真实提取覆盖。
- **状态：已解除**。原解除条件（#9 第一批逐格式真实样例实跑证据齐备并经复核）已满足；与 #5 二次验收范围注解一致。
- **当前状态（现状，与上方历史留痕分开）**：`samples 19 / 成功 12 / 未成功 6 / 实盘对账一致`。测试侧权威数字（qa-verify 独立复跑，两入口一致）：**用例总数 25 / 正式通过 25 / `@expectedFailure` 门禁 0 / 失败 0 / 错误 0 / 意外成功 0**，两入口均 `Ran 25 tests / OK`（`test_extract.py` 75821B / 18:12:20）。演进链：`24（23 正式 + 1 门禁）→ #10 转正 test_24 + 新增 test_25 → 25（25 正式 + 0 门禁）`。上方「当时 23 项回归」及「24 项 = 21 正式 + 3 门禁」均为历史数字、不代表现状；v2.3 曾在此标出「§6.1 数字与磁盘矛盾」，现已按上述权威复跑**订正**（该矛盾说明保留作留痕，不抹掉）。

### 6.2 曾为阶段 2 前置未完成项（v2.3 已全部收敛，编号文字保留作历史留痕）

1. **块级锚点注入**（§5.2）：逐块 `<!-- anchor: ... -->` 落地、与门禁正则对齐、合并链路不剥离。
2. **GBK 前置预处理层**（原 #10 剩余真缺口）：文本类主链路曾 `errors="replace"` 静默吞乱码，须编码探测 → 转 UTF-8 → 留痕重跑。
3. **阶段 2 摘要排除清单**（§5.3）：`content_status` 归 manifest，且人可读清单须同时落 `INDEX.md` 与 `MERGED.md`。

> **收敛状态（#10 落地后 · v2.3）**：第 **1** 项「块级锚点注入」与第 **3** 项「阶段 2 摘要排除清单」已由 #9 第二批实现落地（逐块真值锚点、INDEX + MERGED 双落点），并经 lead 于 17:16 只读独立验收；第 **2** 项「GBK 前置预处理层」已由 #10 落地（2026-11-12 17:58，`extract.py` 59869B / `py_compile OK`），门禁已转正为 `test_24_no_lossy_encoding` 并补 `test_25_bom_strip`。**至此阶段 2 启动前的前置项已全部收敛，无剩余项**；阶段 2 只受 §6.3 读清单口径约束，不再被阶段 1 缺口阻塞。上方三项编号文字为历史留痕，不删除。

### 6.3 阶段 2 读清单口径（持续有效）

- 摘要流水线**须显式跳过或标注降级项**（无产物、占位产物、需 OCR、待人工授权、转换失败 / 待专用解析器、需拆分、需预处理、无效容器、阶段 3 预留、不支持），**不得假定所有格式产物齐备**。
- 降级项为**设计内降级**、非软件缺陷（见 §1.1）；下游不得把降级项当 bug 处理，也不得据此判定阶段 1 未交付。

### 6.4 已知边界（v2.3.1 实测 + v2.4 界面层补充，**不阻塞阶段 2**）

**限制 A · Latin-1 文本可能被 GBK 误判**
- 机制：严格链 `utf-8 → gbk → gb18030 → big5` 对简体中文场景最优，但对西欧文本存在假阳性。GBK 尾字节范围为 `0x40–0xFE`（排除 `0x7F`），`caféX` 的 `E9 58` 恰好构成合法 GBK 双字节，会被解成一个 CJK 字，而不是 `é` + `X`。
- 处置：**属启发式检测的固有代价，本轮不做 CJK 占比二次判定**——那会把 `_STRICT_CHAIN` 变成评分器，复杂度与阶段 1 不匹配。目标场景是中文文档，**接受并文档化**；未来若要接入西欧语料，须单独立项。
- 对阶段 2 的含义：该类文件仍按「成功 + 留痕 `原编码：gbk`」入档，不会被判为降级项；摘要流水线遇明显乱码的非中文文本，应按 §6.3 标注、不得当 bug 反推阶段 1 缺陷。

**限制 B · 大文件 + 非 UTF-8 的内存与耗时**
- 峰值内存：前置层为探测编码必须整读文件，额外驻留「原始字节 + 解码后 str + UTF-8 文本」三份，峰值约为文件大小的 **3–4 倍**。
- 实测：20.0 MB GBK / 501,968 行 → **10.8s**、产物 28.1 MB、`U+FFFD = 0`、首末行原文完整；线性外推 100 MB 约 **55s**。
- **好消息（顺序上不会更坏）**：`> MAX_SINGLE_BYTES(100MB)` 的分支在编码预处理**之前**就 `continue` 落「需拆分」，因此真正进入编码探测的最大档位就是 100 MB，不会出现「200 MB 先被整读进内存、再判拆分」的倒序。
- 操作建议：`>50MB 且非 UTF-8` 时**提示用户先拆分**，而不是硬扛。

**限制 C · 界面外壳：Edge 应用模式 → Electron 自带 Chromium（v1.1.0 起修订）**
- 历史（v0.2.0–v1.0.9）：桌面窗口通过 `msedge.exe --app=<url> --window-size=1060,720` 打开，不使用 WebView2 或内嵌浏览器内核；Edge 被卸载 / 组策略禁用时降级为系统默认浏览器带地址栏打开。
- **现状（v1.1.0+）：对外默认形态改为 Electron 桌面外壳（`electron/`）**——随包分发 Chromium 内核，`main.js` 起无浏览器外观的窗口加载本地 HTTP 服务，`app.py` 以 `--no-browser` 仅作后端。目标机器**无需 Edge、无需 Python、无需 Node**。原 Edge 路径保留为源码态调试的可选回退，不再是发布形态。
- 口径：**界面层依然只是「呈现与调度外壳」，不改变阶段 1 的任何提取语义**（§8 首段铁律不变）。换壳只替换最外层窗口容器，`ui/`、后端 API、轮询、状态机、路径防护全部零改动。
- 代价：体积由 ~10MB 增至免安装目录 ~267MB（NSIS 约 60–100MB）；用户 2026-11-21 裁决接受该代价。

**限制 D · `--no-browser` 调试输出在旧版 `cmd.exe` 花屏**
- 机制：界面进程按 **UTF-8** 统一写出（`sys.stdout/stderr.reconfigure(encoding="utf-8")`），而旧版 `cmd.exe` 默认代码页为 **936（GBK）**，直接重定向阅读会出现乱码 / 花屏。
- 定性：这是「**强制 UTF-8 写出**」的固有取舍，**不修**——反向切到 GBK 会让跨平台、日志文件与子进程管道一起变脆。
- 规避：调试时改用 `chcp 65001` 的终端、或读 `%LOCALAPPDATA%\Jinghe\app.log`（该文件恒为 UTF-8，是权威诊断源）。

## 7. 文件边界

### 7.1 v0.2.1 完整文件清单（规格侧归口与可写性）

| 路径 | 体量 | 职责 | 归口 | 本文件（spec）可否改 |
| --- | --- | --- | --- | --- |
| `SPEC.md` | 本文件 | 阶段 1 规格正本 | spec | **是（唯一写者）** |
| `extract.py` | 2076 行 / 91538B | CLI 提取引擎，`__version__ = "0.2.5"`；含 `-i` 可重复、PDF `/ToUnicode` CMap 解码与乱码门禁 | team-lead | 否（只读） |
| `app.py` | 1599 行 / 63792B | 本地 HTTP 服务 + Edge 启动器 + `--cli` 自我重入 + 启动清扫孤儿编码副本目录 + 固定端口 54321 单实例保护 + 多选文件对话框（`/api/pick-files`，v0.2.4 起走 `comdlg32.GetOpenFileNameW`）+ v0.2.5 前端超时/状态锁治理与僵尸 job 兜底 | team-lead | 否（只读） |
| `ui/index.html` / `ui/app.js` / `ui/app.css` | 128 / 735 / 472 行 | 单页界面，零 CDN、离线可用；含「选择文件…」多选入口、识别清单渲染、v0.2.5 的「打开合并文档」入口与带时间戳的预览反馈 | team-lead | 否（只读） |
| `vendor/md_convert.py` | 技能脚本 | 文本类转换器（可选路径，缺失时回退内置） | 外部资产 | 否 |
| `build.py` / `build.spec` | 728B / 1013B | PyInstaller onefile + `--windowed` 构建 | team-lead | 否（只读） |
| `dist/Jinghe.exe` | 5,963,471B（约 5.7 MB）；sha256 `66d5a4f8601edb354c3398afca77daca351c466b39c1ff4f2490add0644ccbc6` | 单文件可执行产物（**v0.2.4**，PyInstaller 6.22.3 / 32 位 / `console=False`，bootloader `runw.exe`）：**解释器内嵌、无控制台窗口、无需外部 Python**，双击即用。冷启动未重测（旧值 1.58–1.69s 属 64 位 v0.2.2，仅供参考） | 构建产物 | 否 |
| `pack.py` | 131 行 / 4578B | 源码包构建：白名单式收录 + 生成 `MANIFEST.txt`（sha256 / 字节数 / 相对路径）+ `--check` 只校验不写包 | team-lead | 否（只读） |
| `dist/jinghe-stage1-v0.1-20261112.zip` | 94,481B | 阶段 1 归档包（历史产物，勿与 v0.2.x 混淆） | 归档 | 否 |
| `dist/jinghe-stage1-v0.2.4-20261113.zip` | 约 170 KB（以实际产物为准） | 阶段 1 源码交付包（含 v0.2.4 全部修复；不含 exe，exe 单独见上）。**sha256 不写入本表**：包内含本文件，写死的哈希会被下一次改动推翻，实际值以 `pack.py` 输出 / 交付记录为准 | 交付 | 否 |
| `test_extract.py` | 1356 行 / 82832B / 27 用例 | 提取质量回归（§6.1 权威数字来源）；v2.7 新增 CID 字体与乱码门禁两例 | qa | 否（只读） |
| `test_app.py` | 1165 行 / 64246B / 24 用例 | 界面层回归；test_18 锁住 Win32 多选对话框 ABI/选项位，test_19–test_24 锁 dry-run 契约/状态不残留/静态资源 no-store/前端锁静态契约/运行态复位/僵尸 job 兜底 | qa | 否（只读） |
| `samples/` | 19 个 | 主样例集（含设计内降级样例，§1.1） | qa / parser | 否（只读） |
| `out/` | 19 条记录 | 提取产物（`md/`、`INDEX.md`、`MERGED.md`、`run.log`、`provenance.json`） | 运行期生成 | 否（只读） |
| `使用说明.md` | 9170B | 面向用户的快速上手 | team-lead | 否 |
| `build/` | — | PyInstaller 中间产物 | 构建缓存 | 否 |

### 7.2 本轮改动边界

本轮（v2.7）**只改 `SPEC.md` 一个文件**；上表其余路径在本轮全部只读。若发现规格与实现不一致，**记录并上报 team-lead，不自行改代码**。

## 8. 界面层（v0.2.0 新增）

界面层是**呈现与调度外壳**，不改变阶段 1 的任何提取语义：分流、降级、件数对账、留痕、出处定位全部仍由 `extract.py` 单一实现，界面只消费其产物与进度输出。

### 8.1 文件职责

- **`app.py`（1263 行）**：标准库 `ThreadingHTTPServer` 承载单页界面；8 个 `/api/*` 业务端点 + 静态路由（§8.3）；窗口启动器（源码态调试用 Edge `--app` / Electron 外壳用 `--no-browser`，见 §8.2.1）；`--cli` 自我重入入口；`ctypes` 原生文件夹选择对话框（`GetOpenFileNameW` 多选，文件夹仍用 `IFileDialog`）；冻结态兼容（`sys._MEIPASS`、无控制台、无 `python.exe`）；**启动时清扫已退出进程遗留的编码副本目录（`_sweep_orphan_dirs`）**。
- **`ui/index.html` / `ui/app.js` / `ui/app.css`**：零 CDN、零外部字体，**离线可用**；不引入任何前端框架与构建步骤。
- **`build.py` / `build.spec`**：PyInstaller onefile + `--windowed`；`--add-data "ui;ui"`、`--add-data "vendor;vendor"`。产出的是**后端组件 exe**，由 Electron 外壳以 `extraResources` 随包携带。
- **`electron/`（v1.1.0+ 新增）**：`main.js`（起后端 + 单实例 + 关窗即退 + 端口识别）、`preload.js`、`package.json`、`pack_portable.py`（纯标准库组装免安装版）。只替换窗口壳，不碰任何 UI / 业务 / API。详见 `electron/README.md`。

### 8.2.1 Electron 外壳进程结构（v1.1.0+ 默认发布形态）

- **两层进程**：Electron 主进程（`electron/main.js`）只管窗口壳；它 `spawn` 随包后端 `resources/backend/Jinghe.exe --no-browser --port <port>`，窗口加载 `http://127.0.0.1:<port>/`。
- **生命周期**：单实例锁（二次双击唤起已有窗口）、后端复用探测（`isJingheListening` 读 `/api/state`）、端口占用拒绝劫持、关窗 / 进程退出时回收后端。
- **后端仍守 §8.2 的 `--cli` 自我重入**：外壳只是把原来的 Edge 启动器换成了自带 Chromium 的窗口，`app.py` 的 HTTP 服务、路由、状态机一行未改。
- **自更新元数据**：CI 打 NSIS 时产出 `latest.yml`（`electron-builder` + `publish.github`），供 electron-updater 消费；外壳更新与后端自更新（`self_update.py`）的关系见 `electron/README.md` 未决项。

### 8.2 进程结构（冻结后自我重入）

- 源码运行：`app.py` 用当前解释器启动 `extract.py` 子进程。
- **冻结后：`Jinghe.exe --cli <extract 参数>` 自我重入** → 进程内调用 `extract.main(argv)`，**不塞独立解释器**。理由：onefile 包内没有 `python.exe`，塞解释器既脆又大；自我重入仍保留子进程隔离（转换崩溃不带崩界面）。
- 进度协议：子进程在 `--progress` 下每候选文件前打印 `[PROGRESS] i/N 文件名`（已 `flush`）；父进程逐行解析为事件。**不加 `--progress` 时输出与 v0.1 完全一致**——这是既有 25 项回归不被污染的关键。
- `--cli` 模式**绝不弹窗**（会被父进程当子进程调用，弹窗会卡住自动化）。

### 8.3 路由与契约

共 **8 个 `/api/*` 业务端点 + 静态路由**（v2.7 由 7 个增至 8 个：新增 `/api/pick-files`。「8 个」在 v2.4 曾是把 `/favicon.ico` 计入的口误，现已名副其实——favicon 仍是短路由，不计入业务端点）。

| 方法 | 路径 | 请求 | 响应要点 |
| --- | --- | --- | --- |
| GET | `/` | — | `ui/index.html`（缺失则 404 文本） |
| GET | `/ui/<file>` | — | 静态资源，MIME 按后缀；越界 403（见 §8.7） |
| GET | `/favicon.ico` | — | 204 空响应（避免控制台噪音） |
| GET | `/api/state` | — | `version` / `python` / `running` / `input` / `inputs` / `outdir` / `converter` / `cwd` |
| GET | `/api/progress?since=N` | 增量游标，默认 0 | `events` / `next` / `running` / `summary` / `state` / `error` / `total` / `current` / `current_name` |
| POST | `/api/pick-folder` | `{initial}` | `{path}`，用户取消为 `null` |
| POST | `/api/pick-files` | `{initial}` | `{paths:[...], error}`：**取消时 `paths=[]` 且 `error=null`，失败时 `error` 为原因**——两者必须可分，否则对话框打不开时前端只能表现为「点了没反应」（v2.7） |
| POST | `/api/dry-run` | `{input}` 或 `{inputs:[...]}` | 盘点结果 `{"ok":true,"total":N,"buckets":{"文本类":a,"富文档":b,"阶段3预留":c,"需预处理":d,"不支持":e},"items":[{"name","kind"}]}`（五桶键名固定、与前端 `renderBuckets`/`renderFileList` 逐字一致），**不落盘、不生成 md、不打开输出目录**；失败 `{"ok":false,"error}`（含 30s 超时中文文案） |
| POST | `/api/run` | `{input,outdir}` 或 `{inputs:[...],outdir}` | `{ok:true}` 或 `{ok:false, error}`；已有任务在跑时拒绝 |
| POST | `/api/cancel` | — | `{ok:true}`；无运行中任务时 `{ok:false, error}` |
| POST | `/api/open` | `{path}` | `{ok:true}`（`os.startfile`，非 Windows 用 `webbrowser` 兜底） |

- **`inputs` 优先、`input` 回退**（v2.7）：`inputs` 为非空字符串数组时按其处理（去空白、`normcase` 去重、保序），否则回退单值 `input`。**旧单值形态行为零变化**，长度 1 的 `inputs` 同样合法。

- 请求体上限 8 MB，超限 / 非法 JSON 一律 400 而非 500。
- **未知 `/api/*`：GET 与 POST 同形**——都返回 `404 + {ok:false,error}` JSON（v2.5 统一；此前 GET 走纯文本兜底，与 POST 不一致）。理由：前端对接口响应统一 `res.json()`，回纯文本会让未来写错路径时抛 `SyntaxError` 而不是拿到可读 error。
- **静态资源缺失仍是纯文本 404，这是刻意区分的第二条契约**：`/`、`/ui/<file>` 是浏览器直接加载的资源，要求它们也回 JSON 会把合法实现逼成错误形状。**两条契约不许「顺手统一」**——接口面回 JSON，资源面回文本。
- `/api/state` 与 `/api/progress` 的访问**不写 HTTP 日志**（每 400ms 轮询会淹没输出）。

### 8.4 任务状态机

```
idle ──dry-run──> (客户端 previewing，服务端仍 idle) ──> idle
idle ──run──────> running ──> done | cancelled | failed
```

- **服务端只报 5 个状态**：`idle` / `running` / `done` / `cancelled` / `failed`。`previewing` 是**客户端本地布尔量**，服务端不感知、也不出现在 `/api/progress` 的 `state` 里。
- `run` 在 `running` 期间重复提交必须拒绝（`{ok:false}`），不允许并发任务。
- `cancel` 后状态必须收敛到 `cancelled`，**不允许停在 `running`**；取消请求早于子进程就绪时须补一次终止，避免「已取消但仍在跑」。
- `failed` 仅用于**任务级**失败（起不了子进程、汇总缺失等）；单个文件转换失败不进 `failed`，只进降级明细（§8.5）。

### 8.5 界面语义裁决（三条，实现过程中定，属规格）

1. **「降级明细」只列候选文件里未成功的项**（官方样例集为 6）。`阶段 3 预留` / `需预处理` / `不支持` 属于**从未尝试**的类别，单独计数、**不进降级表**。
   理由：混进去会让「6 个失败」失去意义——它们不是「试过没成功」，而是「按规格根本没试」。
2. **「取消」后首卡标签为「已产出（未完成）」**，取已落盘 `md/*.md` 计数，**禁止显示「成功 N」**。
   理由：取消的产物不完整，不能当完成态呈现；用「已产出」只承诺磁盘事实，不承诺完整性。
3. **`需预处理` / `不支持` 在状态栏仅非零时显示**，且 `需预处理 > 0` 用**琥珀色**。
   理由：这两类代表用户的文件确实被跳过、需要用户动手处理；零值时占用状态栏属噪音，非零时必须可见且区别于普通信息。

### 8.6 临时副本目录的所有权（隐私级修正，通用规则）

- **事故根因（留痕）**：编码前置层的 UTF-8 临时副本原由子进程 `mkdtemp` 自建、`atexit` 自清；而 **`atexit` 在 `terminate()` 时不执行** → 界面点「取消」强杀子进程，会把用户文档副本**永久留在 `%TEMP%`**（实测残留 `jinghe-enc-mjclw9n3\0004\glossary.csv`）。
- **通用规则（不是一次性 bug 修复）**：**临时副本目录的所有权必须与「能保证清理的生命周期」对齐**。谁的进程活得比目录内容久，谁持有目录并负责删除。
- 落地（清理共**三条链**，第三条 v2.5 补）：
  - `extract.py` 侧 `_enc_workdir()` **优先读 `JINGHE_ENCDIR`**；有则沿用、不自建 `mkdtemp`、不注册 `atexit`，清理责任移交父进程。
  - ① **`finally`**：`app.py` 每次任务分配独立目录 `jinghe-run-<pid>-<seq>`，正常 / 异常两路都在 `finally` 删除。
  - ② **`atexit` + 启动同类清扫**：`_sweep_run_dirs()` 由 `atexit` 注册，并在启动时也跑一次，清掉**本进程 pid** 上次异常退出的遗留（只 glob 自己的 pid，不误删其他实例）。
  - ③ **启动孤儿清扫**：`_sweep_orphan_dirs()`，见下。

**第三路 · 启动孤儿清扫（v2.5 新增）**

- **缺口**：`finally` 与 `atexit` 在 `TerminateProcess`（任务管理器强杀、强关窗口）下**都不执行**；而第 ② 条只 glob 本进程 pid，**旧 pid 的目录永远扫不到** → 副本永久留在 `%TEMP%`。
- **做法**：`main()` 启动时调 `_sweep_orphan_dirs()`，遍历 `%TEMP%` 下匹配 `^jinghe-run-(\d+)-(\d+)$` 的**目录**；pid 等于本进程则跳过；`_pid_alive(pid)` 为真则跳过；其余 `rmtree(ignore_errors=True)` 删除。清理个数写 app.log：`启动清理：移除 N 个已退出进程遗留的编码副本目录`（异常只记一行、不影响启动）。
- **只认精确形状正则，不按前缀模糊匹配**：`jinghe-run-notapid` 这类相似名字不能被误伤；形状不符一律不碰。
- **存活判定保守优先**：Windows 用 `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)`；打不开时**只有 `GetLastError() == 87`（ERROR_INVALID_PARAMETER）才判死**，其它错误码（典型 5 = 拒绝访问）一律判活；任何异常也判活。
- **为什么保守**：误删另一个正在运行实例的目录会**直接打断那个任务**（转换器读不到临时副本），代价远高于留下一份垃圾。**宁可漏清，不可误删。**
- **已知残留（如实登记）**：pid 被系统复用给无关进程的目录会留着不删，属**可接受残留**。
- **一条会让后来人踩坑的观测事实**：Windows 上只要还有进程句柄没关，进程对象就依然存在——`subprocess.Popen` 在 `wait()` 之后**仍持句柄**，此时 `OpenProcess` 成功、`_pid_alive` 会正确判「活着」。因此测这条逻辑必须先把句柄放掉（`del` + `gc.collect()`）才是真正的「死 pid」。**这不是实现缺陷，恰好印证保守策略正确。**
- 对阶段 2 的含义：任何新增的「子进程 + 临时文件」链路都必须先回答所有权问题，再决定用不用 `atexit`；**靠 `atexit` 清理强杀场景一律视为不合格**。

### 8.7 安全与呈现约束

- **只监听本机（硬要求）**：服务恒绑 `127.0.0.1`（`HOST` 常量），**不得绑 `0.0.0.0`**、不得对外开放端口；端口可指定（`--port`），**默认固定为 `54321`**。固定端口同时是单实例保护的锚点（见 §8.8）。
- **固定端口 + 单实例保护（v2.6 新增）**：默认端口从「0 自动分配」改为固定 `54321`，原因是——`ThreadingHTTPServer` 默认开 `SO_REUSEADDR`，在 Windows 上两个实例重复 `bind` 同一端口**不抛 10048**，会各自 listen、互相抢连接；较早启动的那个一旦退出，端口变成「死端口」，前端对着它 `fetch` 必现「Failed to fetch」；随机端口还会让每次地址都变、重复双击更难排查。保护机制：启动时先 `socket.connect((HOST, port))` 探活，**有实例在 listen 则本进程直接退出（`return 0`）**，不再 bind；探活比「bind 抛异常」可靠。重复双击时第二个实例会打印「端口 54321 已有实例在运行（请勿重复启动）」后安全退出，端口上始终只有一个监听者。
- **路径穿越防护（硬要求）**：`/ui/*` 一律 `resolve()` 后 `relative_to(ui_root)` 校验，越界返回 403，**不得凭字符串前缀判断**（`..`、符号链接、盘符切换都要挡住）。
- **轮询而非 SSE/WebSocket**：进度用 400ms 轮询 `/api/progress?since=N`。理由——标准库 `ThreadingHTTPServer` 已够用，SSE 需长连接与心跳管理，收益不抵复杂度；`since` 增量游标保证不重复堆积事件。
- 轮询连续失败 3 次后放宽到 800ms（服务抖动时不刷屏、不狂打）。
- **无控制台时的日志落盘（v2.5 订正错误认识）**
  - **错在哪（留痕）**：v2.4 曾写「`--windowed` 下 `stdout/stderr` 为 `None`」——**这个前提不成立**。PyInstaller `--windowed` 下 `sys.stdout` 是一个**可写、写进去就丢弃**的哑对象，不是 `None`。于是 `if sys.stdout is None` 恒假，日志通道从不触发：真实双击场景下 `%LOCALAPPDATA%\Jinghe\` 只有目录、没有 `app.log`。这是一个由错误前提直接导致的真 bug。
  - **正确判据**：**`sys.frozen` 为真，或流为 `None`**。冻结后**无条件**打开 `app.log`（UTF-8、逐行时间戳）；原流仍可用时（终端启动）再 **tee 一份**到终端，两边都保留。源码模式仅在流为 `None`（`pythonw`）时落盘。
  - **通用教训**：**不要用 `is None` 判断「有没有控制台」**——哑对象与真流在类型上无从区分，只有 `sys.frozen` 这类显式的运行形态标志才可信。
  - 另：安装 `sys.excepthook` 与 `threading.excepthook`；起不了服务时用 `MessageBoxW` 弹窗告知日志路径（**绝不静默退出**）。
- **资源解析统一走 `resource_dir()`**：冻结取 `sys._MEIPASS`、源码取脚本目录，`ui/` 与 `vendor/` 均经它解析，因此 exe **可从任意工作目录启动**。

### 8.8 前端请求超时与状态锁（v0.2.5 治理「仅预览分流」无反馈）

- **根因（机制缺陷，非「已复现的锁死」）**：`api()` 原本是裸 `fetch` 无超时；`doPreview`/`browse`/`pickFiles` 用 `.then(cleanup)` 冒充 `.finally(cleanup)` 复位 `previewing`/`running`。一旦响应体未完整送达（连接被重置），Promise 永不落定 → 复位链整条不执行 → 状态位永久卡死 → 按钮被 `updateControls()` 禁用、点击被 `if (running || previewing) return;` 静默吞掉（无任何可见反馈）。该会话日志确有 3 次 `ConnectionResetError 10054`，属可证实的隐患，但**不能据日志断言已复现锁死**（见 §8.11）。
- **设计原则（硬规则）**：`.finally` / `.catch` 只能覆盖「Promise reject 或 then 抛错」，**解不了「永不 settle 的挂起」**——唯一解挂起的是 `AbortController` 超时。据此：
  - `api(path, body, timeoutMs)`：超时分级 —— `/api/dry-run` **40000**（> 后端 `DRY_RUN_TIMEOUT` 30s + 余量）、`/api/progress`/`/api/state`/`/api/cancel`/`/api/open`/`/api/run` **10000**、`/api/pick-folder`/`/api/pick-files` **0**（绝不 abort，因要等用户操作原生对话框）。abort 错误归一化为中文「请求超时，已自动恢复，请重试」。
  - 状态复位全部进 `.finally`：`doPreview`/`browse`/`pickFiles` 的 cleanup、`finish()` 在 `updateControls()` 前兜底 `running=false; previewing=false;` 并清轮询定时器、`init()` 首行复位两状态位并清定时器。
  - `init()` 的 `if (st.running)` **不再无条件 `startRunning`**：先发带超时的 `/api/progress?since=0` 确认 `r.running===true` 才恢复轮询，否则保持解锁并提示。
  - `poll()` 的 catch 有硬上限（连续失败 3 次才把 `running` 置 false 并停止续轮询），且只对「reject / then 抛错」有效；挂起仍由 `AbortController` 解。
  - `doCancel` 补 `.then`（取消成功也恢复文案、重启一次轮询）；`doRun` 加 `typeof r.error === "string"` 守卫与 catch 复位。

### 8.9 僵尸任务兜底（v0.2.5 后端加固）

- **背景**：`_run_job_inner` 把 `job.running = False` 放在 try/except 之外的末尾；若 `_build_summary` 等步骤抛未捕获异常，daemon 线程崩溃、`threading.excepthook` 只落日志不复位 → `job.running` 永久 True → 前端按 §8.4 永久禁用按钮、刷新页面还会被 `init()` 重新锁死。
- **修复**：`job.running = False` 与异常态 `state="failed"` 放进 `finally`；新增模块级 `_reap_dead_job()`（判据：`running=True` 且 `job.thread` 为 None 或 `is_alive()` 为 False），在 `/api/state`、`/api/progress`、`/api/run` 三处调用（均在各自 `_JOB_LOCK` 锁外，避免自锁死）。`Job` 新增 `thread` 字段，由 `_api_run` 在同临界区内赋值并 `start()`，因此服务创建的任务必然带句柄；`thread=None` 只可能是测试构造或极老残留，**当前实现对此类不误杀**（保持「宁可漏清不可误伤」）。
- `DRY_RUN_TIMEOUT` 由 600s 收敛为 30s；`subprocess.TimeoutExpired` 单独分支返回中文「预览超时（超过 30 秒）：目录过大 / 文件被占用 / 位于网络盘，请缩小选择范围」，避免把超时误报成「无法启动 extract.py」。

### 8.10 界面控件：打开合并文档按钮（v0.2.5 新增）

- 与「完成后打开合并文档」复选框的区别：复选框是**任务成功时自动弹出** `MERGED.md`（默认勾选，由 `openMerged()` 调 `/api/open`，fire-and-forget、不改状态）；按钮是**手动入口**——默认 disabled，`finish()` 在 `st==="done" && summary && summary.outdir` 时启用，点击复用 `openMerged(summary.outdir)`。按钮**不进 `updateControls()` 的禁用列表**，任务运行中不会被锁死（但此时 `summary` 可能是上一次的旧值，已在 `resetRunUI` 中把按钮禁用、仅在 done 时启用以规避）。
- 界面另加一行静态说明：「仅预览分流只盘点分类，不生成文件、不打开文档」，明确该功能边界。

### 8.11 排查方法论沉淀（v0.2.5）

- `app.py` 的 `log_message` 由标准库 `send_response()` 触发，**早于** `wfile.write(body)`（且 `except (BrokenPipeError, ConnectionResetError): pass` 静默吞写失败、不记日志）。因此 `[HTTP] POST /api/dry-run` 只证「服务端进入发送流程」，**不证明响应体完整送达浏览器**，更不代表前端 Promise 已落定。
- `/api/progress`、`/api/state` 的访问不打 HTTP 日志（每 400ms 轮询会淹没输出）。
- 日志条数 ≠ 点击次数：do_POST 兜底异常会再打一条 `[HTTP]`。
- 推论：不要用「日志出现」断定响应送达；也不要用「窗口某段零日志」断定按钮锁死（静默既可能是锁死，也可能只是用户停止操作）。

---

## 附记（v0.2.4 交付形态回正）

v0.2.3 阶段因本机未定位到构建工具链，曾临时改用 `python.exe` 直接跑 `app.py` 源码，导致桌面出现控制台黑框（`python.exe` 是 CUI 程序，Windows 自动附 `conhost.exe`）。**这不是产品形态要求**。随后确认该精简 Python 自带可用 `pip 26.0.1`，遂以 `pip install --user pyinstaller` 装入用户目录（未改动企业微信自带目录），再用 `python build.py` 重建 `dist/Jinghe.exe`。重建后进程形态恢复为 `Jinghe.exe`（bootloader + 主进程两个，`MainWindowHandle=0`），无任何 `python.exe` 服务进程，用户机器不需要安装 Python。

重建后综合验收全部 PASS：静态资源 `/`、`/ui/app.css`、`/ui/app.js` 均 200；`POST /api/dry-run` 经 `--cli` 自我重入返回 19 个候选（证明内嵌 `extract` 可用）；`POST /api/pick-files` 真机自动选中两个文件并返回两条正确路径、`error=null`（证明 `GetOpenFileNameW` 在冻结态同样工作）。
