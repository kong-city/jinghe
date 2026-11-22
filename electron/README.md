# 精核 · Electron 桌面外壳（当前 v1.2.7；下述实测记录为 v1.1.1 时的产物）

> 本目录属于去浏览器内核开发线 `desktop/native-gui`，与已封存的 v1.0.9 基线物理隔离。

## 一句话说明

把原来「系统 Edge `--app` 模式」这层窗口壳，换成随包分发的 Electron（自带 Chromium）。
**UI、业务、API、测试一行未改**——Electron 只做三件事：拉起本地后端 → 开窗口加载 `http://127.0.0.1:PORT/` → 关窗时回收后端进程。

## 为什么观感零损失

原架构的本质是「Web UI + 本地 HTTP 服务 + 无地址栏窗口壳」。换壳前后，界面始终由 Chromium 渲染同一套 `ui/index.html + app.css + app.js`：

| 层 | 换壳前 | 换壳后 | 是否改动 |
|---|---|---|---|
| 窗口壳 | 系统 Edge `--app=` | Electron BrowserWindow | **替换（仅此一层）** |
| Chromium 内核 | 系统 Edge 提供 | 随包分发（Electron 内置） | 来源变了，渲染能力相同 |
| Web UI（4530 行） | Chromium 渲染 | Chromium 渲染 | 零改动 |
| HTTP 后端 `app.py` | `--no-browser` 起服务 | `--no-browser` 起服务 | 零改动 |
| 业务核心（extract 等 1.5 万行） | Python | Python | 零改动 |
| 前端↔后端通信 | fetch + 400ms 轮询 | 完全相同 | 零改动 |

关键差别：以前 Chromium 由 Windows 系统提供（没装 Edge 就降级成带地址栏的浏览器窗口）；现在 Chromium 跟着应用走，**完全不依赖目标机器任何预装组件**。

## 目录结构

```
electron/
├── package.json      # Electron + electron-builder 配置，版本与软件版本同步
├── main.js           # 主进程：启动后端 / 单实例 / 窗口 / 关窗退出 / 外链处理
├── preload.js        # 最小 preload：只暴露只读 shell 标记，不赋权
├── installer.nsh     # NSIS 卸载补强：补删 app.asar + 询问是否删除个人数据
├── .npmrc            # 国内镜像（npmmirror），加速 electron 二进制下载
├── backend/          # 打包时放置 PyInstaller 产出的 Jinghe.exe（当前为空，见未决项）
└── node_modules/     # npm install 生成（不入库）
```

## 启动方式

### 开发态（当前可用）

```bash
cd electron
npm install                       # 首次；已用 npmmirror 镜像
# 清除 WorkBuddy 注入的 ELECTRON_RUN_AS_NODE（否则 electron 会退化成 node）
env -u ELECTRON_RUN_AS_NODE \
    JINGHE_PYTHON=/path/to/python.exe \
    JINGHE_PORT=54322 \
    ./node_modules/.bin/electron .
```

- `JINGHE_PYTHON`：指定跑 `app.py` 的解释器；不设则用 PATH 里的 `python`
- `JINGHE_PORT`：端口，默认 54321；验证时用 54322 避开已运行的旧实例
- Windows 原生 CMD/PowerShell 下用 `set ELECTRON_RUN_AS_NODE=` 清除即可

### 打包态（已打通 ✅）

```bash
# 1) 先用 PyInstaller 打后端，拷到 electron/backend/Jinghe.exe
python build.py
cp dist/Jinghe-<ver>.exe electron/backend/Jinghe.exe

# 2a) 组装免安装目录（推荐，纯标准库、无额外下载）
cd electron && python pack_portable.py
#   → 产物 electron/release/win-unpacked/Jinghe.exe，双击即运行
#   → python pack_portable.py --size 查看体积
#   沙箱禁止删除旧目录时，可换全新目录名组装：
#   JINGHE_PACK_OUT=Jinghe-v1.1.1 python pack_portable.py

# 2b) NSIS 安装包（CI 里用，国内会因下载 NSIS 二进制卡住）
cd electron && npm run dist
#   → 产物 electron/release/Jinghe-<ver>-setup.exe
```

`main.js` 会优先找 `resources/backend/Jinghe.exe`（打包后）或 `electron/backend/Jinghe.exe`（开发），找不到才回退到源码 `app.py`，因此目标机器无需 Python。

> **沙箱调试提醒**：本 WorkBuddy 环境注入了 `ELECTRON_RUN_AS_NODE=1` 和 `NODE_OPTIONS=--require=...`，打包态 exe 会因此立即退出（"NODE_OPTIONs not supported in packaged apps"）。本地验证须 `env -u ELECTRON_RUN_AS_NODE -u NODE_OPTIONS ./Jinghe.exe`。用户正常双击不受影响。

## 已验证（v1.1.1）

- ✅ Electron 31.7.7 安装成功（二进制 180MB，含完整 Chromium）
- ✅ **开发态 + 打包态双验证**：主进程拉起后端，`/api/state` 返回 `version=1.1.1`
- ✅ 界面 7 个功能按钮文案已中文化，打包版 `/ui/index.html` 实测含全部新文案
- ✅ 前端全部初始化 API（settings / refine / tools / components / kb / pdf）正常返回
- ✅ `POST /api/dry-run` 提取预览链路在开发态与打包态均跑通（`ok=true`, total=1, buckets=5）
- ✅ 单实例锁、重复双击唤起、关窗即退、端口占用识别均已实现
- ✅ `main.js` / `preload.js` 通过 `node --check` 语法校验
- ✅ 发版门禁 10/10；完整测试 173/173 通过
- ✅ **免安装版组装成功**：`release/Jinghe-v1.1.1/Jinghe.exe`，双击 exe 即运行，完全自包含（无需 Python / Edge / Node）
- ✅ 打包版进程树确认：Electron 主进程 → 拉起后端 exe（子进程）
- ✅ `pack_portable.py` 沙箱兼容增强：复制阶段排除 `default_app.asar`、删除操作容错、`JINGHE_PACK_OUT` 自定义输出目录

## 自更新链路（2026-11-21 已裁决）

**推荐并采纳方案 A：electron-updater + GitHub Release。**

原 `self_update.py` 替换的是运行中的后端 `backend/Jinghe.exe`。Electron 化后用户看到/运行的是**外壳 exe**，只更后端会导致版本错配——这正是「断层」根源。三方案对比：

| 方案 | 做法 | 评价 |
|---|---|---|
| **A（采纳）** | electron-updater 消费 CI 产出的 `latest.yml`，更新整个应用包 | **唯一更新对象正确**；开源 GitHub + CI 产元数据 + 接受体积，正好是其标准土壤 |
| B | 后端查版本、前端打开发布页手动下载 | 体验倒退成「网页提示」，不推荐 |
| C | 后端自更新照旧、外壳随安装包手动升级 | 双轨使 Chromium 安全补丁永远到不了终端，是技术债 |

**已铺路（v1.1.2）**：`package.json` 配置 `publish.github`（kong-city/jinghe），CI 稳定产出 `latest.yml` 并随 Release 上传。
**完整接入（v1.2.0 已实施）**：`main.js` 引入 electron-updater，`ipcMain.handle` 注册 `update:check/download/install/cancel`；`preload.js` 用 contextBridge 暴露具名 `desktopUpdater` 白名单；`ui/app.js` 运行时路由（外壳走 IPC、浏览器回落 HTTP）；后端注入 `JINGHE_SHELL=electron` 禁用替换入口实现双通道互斥；安装前先回收后端进程树再 `quitAndInstall`。详见 `docs/自更新方案A-IPC接入说明.md`。

## 六项未决 —— 裁决结果（2026-11-21）

| # | 事项 | 裁决 |
|---|---|---|
| 1 | 自更新链路 | ✅ 方案 A（见上）v1.2.0 完整接入：updater IPC + 白名单桥 + 双通道互斥 |
| 2 | CI 构建链 | ✅ 已创建：Node + npm ci + electron-builder，上传 setup.exe + latest.yml + 后端 exe |
| 3 | SPEC 同步 | ✅ 已修改（非摒弃）：规格版本 v2.12，§6.4 限制 C / §8.1 / 新增 §8.2.1 |
| 4 | 版本策略 | 一律 patch 小升级，已按 1.1.1 → 1.1.4 执行；7 个版本标记（真源 + 6 派生点）由升号工具同步、门禁校验 |
| 5 | 合规/法务 | 开源上传 GitHub：Electron 为 MIT，开源分发无商用编解码顾虑 |
| 6 | 体积 | 接受：免安装 267.4MB（未压缩）/ NSIS 约 60–100MB |

## 数据管理（v1.1.9）

**导出数据**（关于页 → 日志与数据 → 「导出数据」）：把本机用户数据打包成 `.zip` 备份，可选是否含运行日志。覆盖 `%LOCALAPPDATA%\Jinghe` 下的 `settings.json`、`kb/`（知识库）、`app.log`。纯标准库 `zipfile`，原子写入（.tmp → replace），只读不改原始数据。后端端点 `/api/export-data`、`/api/pick-export-dest`。

**卸载时删除数据**（`installer.nsh` 的 `customUnInstall`）：
- 交互式卸载：弹窗询问是否删除个人数据，默认按钮为「否」（安全），选「是」才删除。
- 静默卸载（`/S`，CI / 自动化）：一律保留数据（`IfSilent` 跳过询问），杜绝无人值守误删。
- 顺带补删 electron-builder 默认清单漏掉的 `resources/app.asar`。

实测：工作区外干净路径静默卸载退出码 0、零残留；此前工作区内复测残留的 app.asar 经查是被 WorkBuddy 安全扫描器持有句柄（独占打开失败）的测试环境伪影，非安装包缺陷。详见 `docs/安装卸载与进程回收测试报告.md`。

## 中英切换方案（暂停封存）

用户 2026-11-21 裁决「中英方案暂时不做了，待处理封存」。本轮不引入语言开关、不新增字典端点、不改 `ui/` 任何文件；恢复施工清单见 `docs/待处理项-中英切换.md`。

## 风险提示

- **ELECTRON_RUN_AS_NODE / NODE_OPTIONS**：WorkBuddy 沙箱注入的变量；不清除会导致 electron 退化成 node（`app` undefined）或打包态秒退（NODE_OPTIONS 不受支持）。调试时必须 `env -u ELECTRON_RUN_AS_NODE -u NODE_OPTIONS`。用户正常双击 exe 不受影响。
- **S5 冻结护栏**：`test_app.py` 用 `git diff HEAD -- SPEC.md` 检测未提交改动；SPEC 修订需 commit 后测试才放行（设计行为，勿削弱测试）。
