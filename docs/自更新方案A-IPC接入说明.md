# 自更新方案 A · Electron IPC 接入说明（v1.2.0）

> 实施日期：2026-11-21　版本：v1.2.0（由 v1.1.9 按 patch 满 9 进位）
> 方案：electron-updater 6.3.9 + GitHub Release `latest.yml`
> 用户裁决：六项未决事项第 1 项「自更新链路断层」→ 方案 A，本轮「按规划开工」

## 一、解决什么问题

改造前，CI 每次发版都产出 `latest.yml` 与 `Jinghe-<ver>-setup.exe` 并上传 Release，
但**没有任何代码消费 `latest.yml`**：网页「检查更新」按钮仍走 Python 后端的
`/api/update/*`，而后端自带的 `self_update` 只替换 `backend/Jinghe.exe`（10MB 组件），
换不掉 Electron 外壳、Chromium 与 UI——更新对象是错的，且 Windows 下替换运行中
文件常失败。这就是此前记录的「链路断层」。

方案 A 把更新链路迁到 Electron 外壳主进程，更新对象改为**整个安装包**（NSIS
setup.exe），一次覆盖外壳 + UI + 后端，与 CI 产物完全对齐。

## 二、进程模型与 IPC 链路

```
渲染进程(ui/app.js)           preload 桥                    主进程(electron/main.js)
  ├ checkUpdate()  ──路由──▶ desktopUpdater.check() ──IPC──▶ ipcMain('update:check')
  │                                                          └ autoUpdater.checkForUpdates()
  ├ shellStartUpdate() ─────▶ desktopUpdater.download() ─IPC─▶ ipcMain('update:download')
  │                          onProgress(cb) ◀─send──────────── download-progress 事件
  │                          onStatus(cb)   ◀─send──────────── update-downloaded / error
  └ install() ──────────────▶ desktopUpdater.install() ──IPC─▶ ipcMain('update:install')
                                                                ├ stopBackendProcesses() 先回收后端
                                                                └ autoUpdater.quitAndInstall()
```

- **白名单桥**：`preload.js` 用 `contextBridge` 只暴露 `check/download/install/cancel/
  onStatus/onProgress` 六个具名方法，绝不交出 `ipcRenderer` 本体；事件回调只回传
  payload、不回传 `event` 对象（杜绝经 `event.sender` 反向操控主进程）。
- **频道一一对应**：preload 的六个 channel 与 main 的 `ipcMain.handle` 严格对齐，
  有守护测试逐条校验。
- **进度回推**：updater 的 `download-progress` 事件经 `webContents.send` 推给网页，
  复用原有进度条 UI，无需轮询。

## 三、关键设计决策

| 决策 | 做法 | 原因 |
|---|---|---|
| 下载/安装时机 | `autoDownload=false`、`autoInstallOnAppQuit=false`，全部由网页显式驱动 | 避免后台偷偷更新与关窗回收进程树打架 |
| dev 环境 | `app.isPackaged` 守卫，check 返回只读提示、download/install 拒绝 | 未打包无 `app-update.yml`，updater 无法工作，如实告知不伪装失败 |
| 版本真源一致 | 版本唯一真源 `extract.py::__version__`，升号工具同步 `package.json` | `latest.yml` 版本来自 package.json，与后端不一致会「装完版本号没变」 |
| 双通道互斥 | 主进程拉起后端时注入 `JINGHE_SHELL=electron`；后端在 `start`/`apply` 替换入口据此拒绝 | 后端旧通道只换 backend exe、会与新通道互相覆盖文件 |
| 安装前清理 | `ipcMain('update:install')` 先 `await stopBackendProcesses()` 再 `quitAndInstall` | NSIS 覆盖 `resources/backend/Jinghe.exe` 时若后端在跑会因占用失败 |
| 浏览器兼容 | 网页运行时探测 `window.desktopUpdater`，不存在则回落原 `/api/update/*` | 源码调试、既有测试契约全部保留 |

## 四、实测验证证据（v1.2.0 装机）

| 验证项 | 结果 | 证据 |
|---|---|---|
| 静默安装 | 退出码 0 | 外壳 exe / 后端 exe 均就位 |
| 启动与版本 | `/api/state` = 1.2.0 | 与安装包、latest.yml、真源一致 |
| **asar 含 updater** | ✅ 302 条目含 `node_modules/electron-updater` | 首轮误装 devDependencies 致 asar 仅 3 文件、已修为 dependencies |
| latest.yml | version 1.2.0，含 sha512 / size / path | electron-builder 正常产出 |
| app-update.yml | provider github / kong-city / jinghe | 随包生成，updater 据此定位 Release |
| **双通道互斥** | `/api/update/start` 与 `/api/update/apply` 均返回 `shell_owned=true, ok=false` | 端到端确认后端替换入口在外壳下被禁用 |
| 只读检查保留 | `/api/update/check` 仍返回 `up_to_date` | 互斥不影响无害的只读检查 |
| 关窗进程回收 | 1.968s 进程归零、54329 端口无监听 | `stopBackendProcesses()` 重构无回归 |
| 全量测试 | 197/197 通过 | 含 10 项新增 IPC 守护测试 |
| 发版门禁 | 16/16 通过 | 新增「Electron 自更新 IPC 链完整」断言 |

## 五、已知限制与风险

- **下载完成前无法真取消**：electron-updater 6.x 无官方取消下载 API。`update:cancel`
  仅复位门闩、保证不安装、不替换任何文件；正在下载的分块会在后台自然结束。
- **无代码签名**：NSIS 安装包未签名，Windows SmartScreen 可能告警。开源项目可接受，
  用户点「仍要运行」即可；若要消除告警需购买代码签名证书（本次未做）。
- **`latest.yml` 必须随每次 Release 上传**：CI 已稳定上传三类资产；若未来改动 CI
  漏传 latest.yml，外壳将检查不到更新。发版门禁已校验 CI 含 latest.yml 关键字。
- **下载→安装的完整链路**：本机即最新 1.2.0，无更新可下，故「发现新版本
  → 真实下载 → 静默安装 → 重启」这段未在本机端到端跑通；已通过静态契约测试 +
  updater 配置产物校验覆盖，建议首个真实新版本发布时做一次真实升级验证。

## 六、文件清单

- `electron/main.js`：updater IPC 注册、进度事件、`stopBackendProcesses()` 复用、环境变量注入
- `electron/preload.js`：`desktopUpdater` 具名白名单桥
- `electron/package.json`：`electron-updater` 生产依赖 + `publish.github`
- `app.py`：`_shell_owns_update()` 守卫 + 两个替换入口拒绝
- `ui/app.js`：运行时路由 + `shellCheckUpdate/shellStartUpdate/shellCancelUpdate`
- `test_v10_features.py`：`TestShellUpdateIPC`（10 项）
- `tools/check_release.py`：门禁新增 IPC 链断言（第 16 项）
