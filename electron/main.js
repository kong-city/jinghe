/*
 * 精核 · Electron 主进程
 * ---------------------------------------------------------------------------
 * 职责边界（与现有 Python 后端的分工）：
 *   - 本文件只负责「窗口壳」：启动本地 HTTP 后端 → 开一个无浏览器外观的窗口
 *     加载 http://127.0.0.1:PORT/ → 关窗时回收后端进程。
 *   - 所有 UI（ui/*.html/js/css）、业务（extract.py 等）、API、轮询、心跳、
 *     自更新逻辑全部留在 Python 后端，**一行未改**。
 *   - 换句话说：Electron 只是把原来「系统 Edge --app 模式」这层壳换成了
 *     随包分发的 Chromium，观感零损失，且不再依赖目标机器装没装 Edge。
 *
 * 零外部依赖约定：后端仍由 PyInstaller 打成单文件 exe（随包放在
 * backend/ 下），因此目标机器无需 Python；Electron 自带 Chromium，
 * 因此也无需 Edge。二者合并即「完全不依赖目标机器任何预装组件」。
 */
'use strict';

// 打包态诊断：这一行必须放在所有 require 之前 —— 若它都没出现在 shell.log，
// 说明 main.js 压根没被加载（app.asar 打包问题），而非业务逻辑异常。
try {
  const os = require('os');
  const p = require('path');
  const fsx = require('fs');
  const dir = process.env.LOCALAPPDATA || os.homedir();
  fsx.mkdirSync(p.join(dir, 'Jinghe'), { recursive: true });
  fsx.appendFileSync(p.join(dir, 'Jinghe', 'shell.log'),
    `[${new Date().toISOString()}] main.js 已加载\n`, 'utf8');
} catch (_) { /* 诊断失败不影响主流程 */ }

const { app, BrowserWindow, Tray, Menu, nativeImage, dialog, shell, ipcMain, nativeTheme } = require('electron');
// 免安装版由 pack_portable.py 自行组装，可能未带 electron-updater 依赖。
// 可选加载：依赖缺失时只禁用自更新，绝不让整个外壳启动崩溃。
let autoUpdater = null;
try {
  autoUpdater = require('electron-updater').autoUpdater;
} catch (err) {
  console.warn('[jinghe] electron-updater 不可用，自更新已禁用:', String(err && err.message || err));
}
const { spawn, spawnSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const http = require('http');
const net = require('net');

const PORT = Number(process.env.JINGHE_PORT || 54321);
const HOST = '127.0.0.1';
const APP_URL = `http://${HOST}:${PORT}/`;

/* --------------------------------------------------------------------------
 * 打包态诊断日志：Windows GUI 程序没有控制台，stdout 全部丢弃 —— 外壳一旦
 * 启动失败（如托盘创建抛错、后端 spawn 失败），用户只看到「双击没反应」，
 * 无从判断原因。这里把关键节点落到 %LOCALAPPDATA%\Jinghe\shell.log，
 * 与后端 app.log 并列，供「关于页 → 日志与数据」排查。
 * -------------------------------------------------------------------------- */
const SHELL_LOG = path.join(
  process.env.LOCALAPPDATA || (process.env.HOME || process.env.USERPROFILE || '.'),
  'Jinghe', 'shell.log');

function shellLog(msg) {
  try {
    fs.mkdirSync(path.dirname(SHELL_LOG), { recursive: true });
    fs.appendFileSync(SHELL_LOG,
      `[${new Date().toISOString()}] ${msg}\n`, 'utf8');
  } catch (err) { /* 日志写不进去也不能影响主流程 */ }
}

let backend = null;            // 由本进程拉起的 Python 后端子进程
let backendPid = null;         // spawn 当即记下 PID（exit 后 ChildProcess.pid 可能清空）
let adoptedBackendPid = null;  // 端口上已存在的精核后端 PID（上次崩溃遗留），关窗时需回收
let mainWindow = null;         // 主窗口
let tray = null;               // 右下角托盘图标（关窗后程序在后台运行）
let trayNotified = false;      // 「已最小化到托盘」提示只弹一次
let quitting = false;          // 退出流程防重入
let cleanupDone = false;       // 子进程回收完成，before-quit 才放行

// v1.7.6：Windows 标题栏由 OS 绘制，themeSource 改不动它（用户截图实测）。
// 用 titleBarOverlay 接管外框配色，切主题时经 win.setTitleBarOverlay() 实时更新。
// DOM 里的标题文字见 ui/index.html 的 #shellTitlebar（overlay 只画右侧窗口按钮）。
// v1.8.3：overlay 的 color 必须与 ui/app.css 的 --c-surface 严格同源——
// 左侧标题栏（网页画）用 --c-surface，右侧按钮区（OS 画）用这里的 color，
// 两者一旦不同源就会出现「左白右灰」的硬色差分界线（用户截图实测）。
// 守护测试 test_v183_titlebar_color_sync 会从 CSS 反解色值强制校验，勿硬改。
// v1.9.0：显式指定 overlay 高度，与 ui/app.css 的 --shell-titlebar-h 严格同源。
// 系统默认高度比网页标题栏高约 5px，会在右侧按钮区下方多出一条白底（用户截图实测），
// 故两层同高，消除这条未对齐的色带。height 必须放在 symbolColor 之后——
// test_v183 的正则按 color,symbolColor 顺序解析，插在中间会破坏守护。
const TITLEBAR_HEIGHT = 28;
const TITLEBAR_THEME = Object.freeze({
  light: { color: '#FFFFFF', symbolColor: '#2A2E33', height: TITLEBAR_HEIGHT },
  dark: { color: '#22262B', symbolColor: '#ECEDEE', height: TITLEBAR_HEIGHT },
});
function applyTitleBarTheme(theme) {
  const source = (theme === 'dark') ? 'dark' : 'light';
  if (!mainWindow || mainWindow.isDestroyed()) return source;
  if (typeof mainWindow.setTitleBarOverlay !== 'function') return source;
  const colors = TITLEBAR_THEME[source];
  try {
    mainWindow.setTitleBarOverlay({
      color: colors.color,
      symbolColor: colors.symbolColor,
      height: TITLEBAR_HEIGHT,
    });
    shellLog('原生标题栏配色已同步 color=' + colors.color + ' height=' + TITLEBAR_HEIGHT);
  } catch (err) {
    shellLog('标题栏配色同步失败（已忽略）：' + String(err));
  }
  return source;
}

/* -------------------------------------------------------------------------- */
/* 托盘（用户裁决 2026-11-22）：关窗不再退出，缩到右下角图标，后台继续同步订阅   */
/* -------------------------------------------------------------------------- */
// 图标真源：build/icon.png（与安装包/桌面/exe 同一张图，electron-builder 由它生成 ICO）。
// 托盘优先从该图运行时缩放到 16x16 —— 保证「托盘图标 == 桌面图标」；
// 内嵌 16x16 base64 仅作兜底（开发态/资源缺失时），避免托盘因资源问题建不起来。
const TRAY_ICON_DATA_URL = 'data:image/png;base64,' +
  // 经 Electron 31 实测 isEmpty()==false / 16x16（勿随意替换：手写 PNG 会解成空图）
  'iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAO0lEQVR42mNggAI5h4r/pGAGZECqZhRDyNUMNwSXBDoYNYDeBmADA28ALkMYKPE/3kCkS36gKEfC9AEAzt4d153g+NgAAAAASUVORK5CYII=';

// 解析图标真源路径：打包态在 resources/icon.png（extraResources 复制），
// 开发态在 __dirname/build/icon.png。两处都由 package.json 配置保证存在。
function trayIconPath() {
  if (app.isPackaged) return path.join(process.resourcesPath || '', 'icon.png');
  return path.join(__dirname, 'build', 'icon.png');
}

function loadTrayIcon() {
  // 优先用真源图缩放到 16x16，与桌面图标同源
  try {
    const p = trayIconPath();
    const fs = require('fs');
    if (fs.existsSync(p)) {
      const big = nativeImage.createFromPath(p);
      if (!big.isEmpty()) {
        const small = big.resize({ width: 16, height: 16 });
        if (!small.isEmpty()) {
          shellLog('托盘图标使用品牌真源 icon.png（与桌面图标同源）');
          return small;
        }
      }
    }
  } catch (err) {
    shellLog('品牌图标加载失败，回退内嵌小图：' + String(err));
  }
  return nativeImage.createFromDataURL(TRAY_ICON_DATA_URL);
}

function createTray() {
  try {
    let icon = loadTrayIcon();
    if (icon.isEmpty()) {
      // 极端环境下图像解码失败：如实记日志，用空图仍可建托盘（菜单可用，
      // 仅图标不可见）。不发 balloon——那是误导用户"一切正常"。
      shellLog('托盘图标解码为空，托盘仅能通过菜单使用');
      icon = nativeImage.createEmpty();
    }
    tray = new Tray(icon);
    tray.setToolTip('精核 · 后台运行中');
    const menu = Menu.buildFromTemplate([
      { label: '显示主窗口', click: showWindow },
      { type: 'separator' },
      { label: '退出精核', click: () => shutdown() },
    ]);
    tray.setContextMenu(menu);
    tray.on('double-click', showWindow);
    shellLog('托盘已创建（关窗后后台运行）');
    return true;
  } catch (err) {
    // 托盘不可用时降级为「关窗即退」旧行为，保证用户不会被困在关不掉的窗口里。
    // 关键：绝不让托盘失败阻断窗口/后端的启动（打包态无控制台，失败会表现为
    // 「双击没反应」而用户无从得知原因）。
    shellLog('托盘创建失败，降级为关窗即退：' + String(err));
    console.error('[jinghe] 托盘创建失败，降级为关窗即退:', err);
    tray = null;
    return false;
  }
}

function showWindow() {
  if (!mainWindow || mainWindow.isDestroyed()) {
    createWindow();
    return;
  }
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
}

/* -------------------------------------------------------------------------- */
/* 原生应用菜单（双语骨架）                                                    */
/* -------------------------------------------------------------------------- */
// 用户裁决 2026-11-25：菜单「可不用，但不能没有」，为后续迭代保留标准骨架。
// 默认显示中文；网页切语言时经 menu:set-lang IPC 同步重建，避免菜单停留在英文。
// 菜单能力保持克制：只放导航/视图/帮助等通用项，业务操作仍在页面内完成。
const MENU_LABELS = {
  zh: {
    app: '精核', file: '文件', show: '显示主窗口', reload: '重新加载',
    close: '关闭窗口', quit: '退出精核',
    edit: '编辑', undo: '撤销', redo: '重做', cut: '剪切', copy: '复制',
    paste: '粘贴', selectAll: '全选',
    view: '视图', resetZoom: '重置缩放', zoomIn: '放大', zoomOut: '缩小',
    fullscreen: '全屏',
    window: '窗口', minimize: '最小化',
    help: '帮助', homepage: '项目主页', about: '关于精核',
  },
  en: {
    app: 'Jinghe', file: 'File', show: 'Show Window', reload: 'Reload',
    close: 'Close Window', quit: 'Quit Jinghe',
    edit: 'Edit', undo: 'Undo', redo: 'Redo', cut: 'Cut', copy: 'Copy',
    paste: 'Paste', selectAll: 'Select All',
    view: 'View', resetZoom: 'Reset Zoom', zoomIn: 'Zoom In', zoomOut: 'Zoom Out',
    fullscreen: 'Fullscreen',
    window: 'Window', minimize: 'Minimize',
    help: 'Help', homepage: 'Project Home', about: 'About Jinghe',
  },
};

let currentMenuLang = 'zh';
// v1.7.6：Windows 隐藏标题栏后原生菜单条被 OS 一并拿掉（截图实测），
// 页面顶栏保留同名按钮，点击时仍弹出下面这套原生菜单——骨架/双语不丢。
const MENU_TOP_KEYS = Object.freeze(['file', 'edit', 'view', 'window', 'help']);

function menuLabels(lang) {
  const t = MENU_LABELS[(lang === 'en') ? 'en' : 'zh'];
  return MENU_TOP_KEYS.map(function (key) { return t[key]; });
}

function buildAppMenu(lang) {
  currentMenuLang = (lang === 'en') ? 'en' : 'zh';
  const t = MENU_LABELS[currentMenuLang];
  const template = [
    {
      label: t.file,
      submenu: [
        { label: t.show, click: function () { showWindow(); } },
        { label: t.reload, role: 'reload' },
        { type: 'separator' },
        { label: t.close, role: 'close' },
        { label: t.quit, click: function () { shutdown(); } },
      ],
    },
    {
      label: t.edit,
      submenu: [
        { label: t.undo, role: 'undo' },
        { label: t.redo, role: 'redo' },
        { type: 'separator' },
        { label: t.cut, role: 'cut' },
        { label: t.copy, role: 'copy' },
        { label: t.paste, role: 'paste' },
        { label: t.selectAll, role: 'selectAll' },
      ],
    },
    {
      label: t.view,
      submenu: [
        { label: t.resetZoom, role: 'resetZoom' },
        { label: t.zoomIn, role: 'zoomIn' },
        { label: t.zoomOut, role: 'zoomOut' },
        { type: 'separator' },
        { label: t.fullscreen, role: 'togglefullscreen' },
      ],
    },
    {
      label: t.window,
      role: 'window',
      submenu: [
        { label: t.minimize, role: 'minimize' },
        { label: t.close, role: 'close' },
      ],
    },
    {
      label: t.help,
      role: 'help',
      submenu: [
        { label: t.homepage, click: function () {
          shell.openExternal('https://github.com/kong-city/jinghe');
        } },
        { label: t.about, click: function () {
          // 跳到应用内「关于」页，而不是 Electron 原生关于面板。
          showWindow();
          if (mainWindow && !mainWindow.isDestroyed()) activatePageInRenderer('about');
        } },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
  shellLog('应用菜单已构建 lang=' + currentMenuLang);
}

// 让菜单的「关于」跳到网页内的 about 页；渲染进程未就绪时静默跳过。
function activatePageInRenderer(name) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('menu:navigate', name);
  }
}

/* -------------------------------------------------------------------------- */
/* 自更新（方案 A）：electron-updater + GitHub latest.yml                       */
/* -------------------------------------------------------------------------- */
// 重要：关闭自动下载/自动安装，全部由网页经 IPC 显式驱动，避免「后台偷偷更新」
// 与关窗回收进程树打架；检查到的版本只做展示，真正下载在用户点「立即更新」后。
if (autoUpdater) {
  autoUpdater.autoDownload = false;
  autoUpdater.autoInstallOnAppQuit = false;
}
let updateBusy = false;        // 更新任务门闩：下载/安装期间拒绝重复触发

// 把后端进程树回收抽成可复用函数：正常关窗与「安装更新前」都要用。
// 安装更新时若后端还在跑，NSIS 覆盖 resources/backend/Jinghe.exe 会因文件占用失败。
async function stopBackendProcesses() {
  try {
    if (backend && backend.exitCode === null && !backend.killed) {
      if (process.platform === 'win32') {
        // onefile 的 Popen.pid 是 PyInstaller bootloader 父进程。必须先在父进程
        // 还活着时按树杀，否则真正的 Python 子进程会脱离树、继续占端口几十秒。
        console.log('[jinghe] 按进程树终止后端 pid=' + backendPid);
        terminateProcessTree(backendPid);
        await waitForExit(backend, 3000);
        try { backend.kill(); } catch (_) { /* 已退出 */ }
      } else {
        // POSIX：发 SIGTERM 让 Python atexit 清子进程，超时再 SIGKILL。
        try { backend.kill(); } catch (_) { /* 已退出 */ }
        await waitForExit(backend, 2000);
        if (backend.exitCode === null) {
          try { backend.kill('SIGKILL'); } catch (_) { /* 已退出 */ }
          await waitForExit(backend, 1000);
        }
      }
    }
    // 兜底一：父进程已退出时，按树补刀它派生过的 whisper / ffmpeg。
    if (backendPid) terminateProcessTree(backendPid);
    if (adoptedBackendPid && adoptedBackendPid !== backendPid) {
      terminateProcessTree(adoptedBackendPid);
    }
    // 兜底二：onefile 的 Python 子进程若已脱离进程树，按完整路径再扫一次。
    killStrayBackendProcesses();
  } catch (err) {
    console.error('[jinghe] 清理后端进程失败:', err);
  }
}

// 版本号比较：只比三段数字，避免 "v1.2.0" / "1.2.0" 字符串比较出错。
function compareVersion(a, b) {
  const pa = String(a || '').replace(/^v/i, '').split('.').map(Number);
  const pb = String(b || '').replace(/^v/i, '').split('.').map(Number);
  for (let i = 0; i < 3; i++) {
    const x = Number.isFinite(pa[i]) ? pa[i] : 0;
    const y = Number.isFinite(pb[i]) ? pb[i] : 0;
    if (x !== y) return x > y ? 1 : -1;
  }
  return 0;
}

// 网页通过 preload 白名单调用；所有返回值都是纯数据，绝不回传 Electron 对象。
function registerUpdateIPC() {
  // 网页 applyLang 切语言后同步重建原生菜单（白名单由 preload.js 控制）。
  ipcMain.handle('menu:set-lang', (_event, lang) => {
    buildAppMenu(lang);
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('menu:labels-changed',
        { keys: MENU_TOP_KEYS, labels: menuLabels(currentMenuLang) });
    }
    return { ok: true, lang: currentMenuLang };
  });

  // v1.7.6：页面顶栏菜单按钮 → 弹出同一套原生菜单（不另建命令，杜绝行为分叉）。
  ipcMain.handle('menu:labels', () => ({
    keys: MENU_TOP_KEYS, labels: menuLabels(currentMenuLang),
  }));
  ipcMain.handle('menu:open', (_event, key) => {
    const idx = MENU_TOP_KEYS.indexOf(key);
    const menu = Menu.getApplicationMenu();
    if (idx < 0 || !menu || !menu.items[idx] || !menu.items[idx].submenu) {
      return { ok: false, error: '菜单项不可用' };
    }
    try {
      // 不传 x/y 时 Electron 默认在鼠标位置弹出；窗口归属显式指定，避免弹出后失焦。
      // 日志写在 popup 前：Windows 上 popup 会阻塞到菜单关闭，写后面无法证明已触发。
      shellLog('页面入口弹出原生菜单 key=' + key);
      menu.items[idx].submenu.popup({ window: mainWindow });
      return { ok: true };
    } catch (err) {
      shellLog('弹出原生菜单失败：' + String(err));
      return { ok: false, error: String(err) };
    }
  });

  // v1.7.5：网页 applyTheme 切主题后同步原生菜单/标题栏配色。
  // Windows 上原生菜单由 Electron/Chromium 绘制，只认 themeSource，网页 CSS 管不到；
  // 值已在 preload 归一化为 dark/light，这里再兜一层防御。
  ipcMain.handle('menu:set-theme', (_event, theme) => {
    const source = (theme === 'dark') ? 'dark' : 'light';
    nativeTheme.themeSource = source;
    shellLog('原生主题已同步 themeSource=' + source);
    // v1.7.6：菜单归 themeSource 管，标题栏归 titleBarOverlay 管，两条链路一起切。
    applyTitleBarTheme(source);
    return { ok: true, themeSource: source, shouldUseDarkColors: nativeTheme.shouldUseDarkColors };
  });

  ipcMain.handle('update:check', async () => {
    // dev 未打包：没有 app-update.yml，updater 无法工作。如实告知，不假装失败。
    if (!app.isPackaged) {
      return { ok: true, dev: true, current: app.getVersion(),
               up_to_date: true, message: '开发模式不检查更新' };
    }
    if (!autoUpdater) return { ok: false, error: '自更新组件不可用' };
    try {
      const result = await autoUpdater.checkForUpdates();
      const latest = (result && result.updateInfo && result.updateInfo.version) || '';
      const upToDate = !latest || compareVersion(latest, app.getVersion()) <= 0;
      return { ok: true, current: app.getVersion(), latest: latest,
               up_to_date: upToDate, has_asset: !upToDate && Boolean(latest) };
    } catch (err) {
      // 断网 / GitHub 不可达：offline 让前端给出诚实降级提示。
      console.warn('[jinghe] 检查更新失败:', String(err));
      return { ok: false, offline: true, error: String(err && err.message || err) };
    }
  });

  ipcMain.handle('update:download', async () => {
    if (!app.isPackaged) return { ok: false, dev: true, error: '开发模式不下载更新' };
    if (!autoUpdater) return { ok: false, error: '自更新组件不可用' };
    if (updateBusy) return { ok: false, error: '已有更新任务在运行' };
    updateBusy = true;
    try {
      await autoUpdater.downloadUpdate();
      return { ok: true, started: true };
    } catch (err) {
      console.error('[jinghe] 下载更新失败:', String(err));
      return { ok: false, error: String(err && err.message || err) };
    } finally {
      updateBusy = false;
    }
  });

  ipcMain.handle('update:install', async () => {
    if (!app.isPackaged) return { ok: false, dev: true, error: '开发模式不安装更新' };
    if (!autoUpdater) return { ok: false, error: '自更新组件不可用' };
    if (updateBusy) return { ok: false, error: '更新包尚未下载完成' };
    // 关键时序：先把后端进程树杀干净，再让 NSIS 覆盖随包 exe，否则必因占用失败。
    await stopBackendProcesses();
    // 进程已由本处理器回收完毕：置位让 before-quit 守卫直接放行，既不重复清理，
    // 也不 preventDefault 干扰 electron-updater 的退出后重启流程。
    cleanupDone = true;
    updateBusy = true;
    autoUpdater.quitAndInstall(true, true);
    return { ok: true, message: '正在安装更新，程序即将重启' };
  });

  ipcMain.handle('update:cancel', async () => {
    // electron-updater 6.x 无官方取消下载 API；这里把门闩复位并如实告知。
    // 真正在后台下载的分块无法被强制中断，但不会安装、也不会替换任何文件。
    updateBusy = false;
    return { ok: true, message: '已取消更新安装' };
  });
}

// 把 updater 事件转成纯数据推给渲染进程；网页侧只认 update:* 这几个频道。
function bindUpdaterEvents() {
  if (!autoUpdater) return;
  autoUpdater.on('checking-for-update', () => pushUpdate('update:status', { state: 'checking' }));
  autoUpdater.on('update-available', (info) =>
    pushUpdate('update:status', { state: 'available', version: info && info.version }));
  autoUpdater.on('update-not-available', () =>
    pushUpdate('update:status', { state: 'up_to_date' }));
  autoUpdater.on('download-progress', (p) =>
    pushUpdate('update:progress', { percent: Number(p && p.percent) || 0,
                                    transferred: Number(p && p.transferred) || 0,
                                    total: Number(p && p.total) || 0 }));
  autoUpdater.on('update-downloaded', () =>
    pushUpdate('update:status', { state: 'downloaded' }));
  autoUpdater.on('error', (err) =>
    pushUpdate('update:status', { state: 'error', error: String(err && err.message || err) }));
}

function pushUpdate(channel, payload) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send(channel, payload);
  }
}

/* -------------------------------------------------------------------------- */
/* 后端可执行文件定位                                                          */
/* -------------------------------------------------------------------------- */
function backendCommand() {
  // 打包态：extraResources 里随包的 backend/Jinghe.exe
  const resDir = (process.resourcesPath || path.join(__dirname, '..', '..'));
  const exeInPkg = path.join(resDir, 'backend', 'Jinghe.exe');
  const exeInDev = path.join(__dirname, 'backend', 'Jinghe.exe');
  const exe = fs.existsSync(exeInPkg) ? exeInPkg
            : fs.existsSync(exeInDev) ? exeInDev : null;

  if (exe) {
    return { cmd: exe, args: ['--no-browser', '--port', String(PORT)], cwd: path.dirname(exe) };
  }
  // 开发态：直接跑源码 app.py（需本机 python）；--no-browser 只起服务不开 Edge
  const py = process.env.JINGHE_PYTHON || 'python';
  const appPy = path.join(__dirname, '..', 'app.py');
  return { cmd: py, args: [appPy, '--no-browser', '--port', String(PORT)], cwd: path.join(__dirname, '..') };
}

/* -------------------------------------------------------------------------- */
/* 端口就绪探测（用 TCP connect，与后端自身的单实例保护口径一致）               */
/* -------------------------------------------------------------------------- */
function portReady(port, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve) => {
    const tryOnce = () => {
      const sock = net.connect({ host: HOST, port }, () => {
        sock.destroy();
        resolve(true);
      });
      sock.on('error', () => {
        sock.destroy();
        if (Date.now() >= deadline) resolve(false);
        else setTimeout(tryOnce, 150);
      });
      sock.setTimeout(1000, () => { sock.destroy(); });
    };
    tryOnce();
  });
}

function isJingheListening(port) {
  // 探测端口上跑的是不是精核自己（读 /api/state），避免误用一个陌生服务
  return new Promise((resolve) => {
    const req = http.get({ host: HOST, port, path: '/api/state', timeout: 2000 }, (res) => {
      let body = '';
      res.on('data', (c) => { body += c; if (body.length > 8192) res.destroy(); });
      res.on('end', () => {
        try { resolve(Boolean(JSON.parse(body).version)); }
        catch (_) { resolve(/version/i.test(body)); }
      });
    });
    req.on('error', () => resolve(false));
    req.on('timeout', () => { req.destroy(); resolve(false); });
  });
}

/* -------------------------------------------------------------------------- */
/* 进程回收：Windows 下 backend.kill() 只杀直接子进程，whisper / ffmpeg 等        */
/* 孙进程会变孤儿；必须按进程树终止。POSIX 用 SIGTERM（子进程自成进程组）。        */
/* -------------------------------------------------------------------------- */
function findListenerPid(port) {
  if (process.platform === 'win32') {
    const r = spawnSync('netstat', ['-ano', '-p', 'tcp'], {
      encoding: 'utf8', windowsHide: true, timeout: 5000,
    });
    if (r.error || r.status !== 0) return null;
    const re = new RegExp('127\\.0\\.0\\.1:' + port + '\\s+.*\\sLISTENING\\s+(\\d+)', 'i');
    const m = (r.stdout || '').match(re);
    return m ? Number(m[1]) : null;
  }
  // macOS / Linux：优先 lsof，退化到 ss。拿不到就返回 null（不猜 PID，避免误杀）。
  const r = spawnSync('lsof', ['-nP', '-tiTCP:' + port, '-sTCP:LISTEN'], {
    encoding: 'utf8', timeout: 5000,
  });
  if (!r.error && r.status === 0 && (r.stdout || '').trim()) {
    const pid = Number((r.stdout || '').trim().split(/\s+/)[0]);
    return Number.isFinite(pid) ? pid : null;
  }
  return null;
}

function terminateProcessTree(pid) {
  if (pid === null || pid === undefined || !Number.isFinite(Number(pid))) return false;
  const p = Number(pid);
  if (process.platform === 'win32') {
    const r = spawnSync('taskkill', ['/T', '/F', '/PID', String(p)], {
      encoding: 'utf8', windowsHide: true, timeout: 8000,
    });
    const text = (r.stdout || '') + (r.stderr || '');
    // 进程已经退出不算失败，其余情况如实返回 false 供日志排查。
    return r.status === 0 || /not found|no process|找不到|没有找到|不存在/i.test(text);
  }
  try {
    process.kill(p, 'SIGTERM');
    return true;
  } catch (_) {
    return false;
  }
}

function waitForExit(child, timeoutMs) {
  if (child.exitCode !== null || child.signalCode !== null) return Promise.resolve();
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, timeoutMs);
    child.once('exit', () => { clearTimeout(timer); resolve(); });
  });
}

function killStrayBackendProcesses() {
  // PyInstaller onefile 的 Popen.pid 是 bootloader 父进程；它先死时，真正的
  // Python 子进程会脱离进程树。按完整路径兜底扫一次，只匹配 backend 目录，
  // 绝不误杀外壳自身（外壳 exe 在安装根目录，路径不同）。
  if (process.platform !== 'win32') return;
  const { cmd } = backendCommand();
  if (path.extname(cmd).toLowerCase() !== '.exe') return;
  const escaped = cmd.replace(/'/g, "''");
  const script = "$_.ExecutablePath -eq '" + escaped + "'";
  spawnSync('powershell', ['-NoProfile', '-NonInteractive', '-Command',
    "Get-CimInstance Win32_Process | Where-Object { " + script +
    " } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"],
    { encoding: 'utf8', windowsHide: true, timeout: 10000 });
}

/* -------------------------------------------------------------------------- */
/* 启动后端（尊重已有实例：端口上已有精核则直接复用，不再重复拉起）              */
/* -------------------------------------------------------------------------- */
async function startBackend() {
  if (await portReady(PORT, 800)) {
    const ours = await isJingheListening(PORT);
    if (ours) {
      // 能应答 /api/state 说明这就是精核后端。记录 PID，关窗时一并回收，
      // 否则上次崩溃遗留的后端会永久占着端口（僵尸宿主的典型形态）。
      adoptedBackendPid = findListenerPid(PORT);
      console.log('[jinghe] 复用已在运行的后端实例 port=' + PORT
        + ' pid=' + (adoptedBackendPid || 'unknown'));
      return { reused: true };
    }
    // 端口被别的程序占用：明确报错，绝不劫持
    shellLog('端口 ' + PORT + ' 被非精核程序占用，无法启动');
    dialog.showErrorBox('精核无法启动',
      `端口 ${PORT} 已被其他程序占用（非精核）。\n\n请关闭占用该端口的程序后重试。`);
    app.quit();
    return { aborted: true };
  }

  const { cmd, args, cwd } = backendCommand();
  console.log('[jinghe] 启动后端:', cmd, args.join(' '));
  shellLog('启动后端：' + cmd + ' ' + args.join(' '));
  try {
    backend = spawn(cmd, args, {
      cwd,
      windowsHide: true,
      detached: false,
      stdio: ['ignore', 'pipe', 'pipe'],
      // 标记后端「运行在桌面外壳内」：后端据此禁用自带的 exe 替换逻辑，
      // 避免与外壳 electron-updater 形成双通道（版本错配 / 互相覆盖文件）。
      env: Object.assign({}, process.env, { JINGHE_SHELL: 'electron' }),
    });
    backendPid = backend.pid || null;
  } catch (err) {
    dialog.showErrorBox('精核无法启动', '无法启动后端进程：\n' + String(err));
    app.quit();
    return { aborted: true };
  }
  backend.stdout.on('data', (d) => process.stdout.write('[backend] ' + d));
  backend.stderr.on('data', (d) => process.stderr.write('[backend] ' + d));
  // spawn 失败是异步 error 事件；没有监听器会直接抛未捕获异常并崩溃。
  backend.on('error', (err) => {
    console.error('[jinghe] 后端进程启动失败:', err);
    shellLog('后端进程启动失败：' + String(err));
    if (!quitting) {
      dialog.showErrorBox('精核无法启动', '无法启动后端进程：\n' + String(err));
      shutdown();
    }
  });
  backend.on('exit', (code) => {
    if (!quitting) {
      console.error('[jinghe] 后端意外退出 code=' + code);
      shellLog('后端意外退出 code=' + code);
      // 父进程先死时，它派生的 whisper / ffmpeg 可能仍在跑，按树补刀；
      // onefile 的 Python 子进程若已脱离树，再按完整路径扫一次。
      terminateProcessTree(backendPid);
      killStrayBackendProcesses();
      if (mainWindow && !mainWindow.isDestroyed()) {
        dialog.showErrorBox('精核后端已退出',
          `本地服务意外停止（退出码 ${code}）。程序即将关闭，请重新启动。`);
      }
      shutdown();
    }
  });

  const ok = await portReady(PORT, 30000);
  if (!ok) {
    dialog.showErrorBox('精核无法启动', '后端在 30 秒内未就绪，请查看日志文件 app.log。');
    shutdown();
    return { aborted: true };
  }
  return { reused: false };
}

/* -------------------------------------------------------------------------- */
/* 窗口                                                                        */
/* -------------------------------------------------------------------------- */
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1060,
    height: 720,
    minWidth: 720,
    minHeight: 480,
    title: '精核',
    // 品牌图标：开发态跑通用 electron.exe（默认图标），必须显式指定才能显示精核图标；
    // 打包态 electron-builder 也会用同一张真源图生成 exe 图标，两处同源不冲突。
    icon: nativeImage.createFromPath(trayIconPath()),
    backgroundColor: '#FFFFFF',
    // v1.7.6：标题栏由 overlay 绘制，颜色可随主题实时改；标题文字由页面 #shellTitlebar 承担。
    // Windows/Linux 下 hidden 必须与 titleBarOverlay 同用，否则窗口按钮会整排消失。
    ...(process.platform === 'win32' ? {
      titleBarStyle: 'hidden',
      titleBarOverlay: { color: TITLEBAR_THEME.light.color,
                         symbolColor: TITLEBAR_THEME.light.symbolColor,
                         height: TITLEBAR_HEIGHT },
    } : {}),
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      spellcheck: false,
      // 拖拽本地文件到窗口：允许 file:// 供 DataTransfer 读取路径（后端仍做白名单校验）
      webSecurity: true,
    },
  });

  // 隐藏原生标题栏后显式保住菜单条（B 方案：菜单可不用但不能没有）。
  try { if (process.platform === 'win32') mainWindow.setMenuBarVisibility(true); } catch (err) {
    shellLog('菜单条显式保活失败（已忽略）：' + String(err));
  }
  mainWindow.once('ready-to-show', () => mainWindow.show());
  mainWindow.loadURL(APP_URL);

  // 外部链接（如「检查更新」打开的 GitHub 发布页）交给系统浏览器，
  // 不在应用窗口里跳走，保持桌面应用观感。
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//.test(url)) {
      shell.openExternal(url);
      return { action: 'deny' };
    }
    return { action: 'allow' };
  });

  // 用户裁决 2026-11-22：关窗 = 隐藏到托盘，后端 + 订阅调度继续在后台跑。
  // 只有托盘创建失败（降级模式）才回到旧行为真正关闭。
  mainWindow.on('close', (event) => {
    if (quitting || !tray || mainWindow.isDestroyed()) return;
    event.preventDefault();
    mainWindow.hide();
    if (!trayNotified) {
      trayNotified = true;
      try {
        tray.showBalloon('精核', '已最小化到右下角托盘，订阅仍在后台同步。');
      } catch (_) { /* 气球提示不可用不影响隐藏行为 */ }
    }
  });

  mainWindow.on('closed', () => { mainWindow = null; });
}

async function shutdown() {
  if (quitting) return;
  quitting = true;
  await stopBackendProcesses();
  cleanupDone = true;
  app.quit();
}

/* -------------------------------------------------------------------------- */
/* 单实例 + 生命周期                                                            */
/* -------------------------------------------------------------------------- */
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  // 已有实例在运行（第二次双击／开发态与打包态并存）→ 本次直接退出。
  // 必须留日志痕迹：否则 shell.log 只剩「main.js 已加载」一行，
  // 排查时极易误判为「程序坏了／打包异常」。
  shellLog('已有实例在运行，本次启动退出（再次双击属正常行为，非故障）');
  app.quit();
} else {
  app.on('second-instance', () => {
    // 再次双击：从托盘唤起已有窗口（后端由第一个实例托管）
    showWindow();
  });

  app.whenReady().then(async () => {
    shellLog('外壳就绪 isPackaged=' + app.isPackaged + ' port=' + PORT);
    // 默认浅色，与 settings.theme 默认值一致；网页加载设置后会经 menu:set-theme 同步真实值。
    nativeTheme.themeSource = 'light';
    buildAppMenu('zh');    // 先建中文菜单骨架；网页设置返回语言后再经 IPC 同步
    registerUpdateIPC();   // 更新 IPC 白名单（update:check/download/install/cancel）+ menu:set-lang
    bindUpdaterEvents();   // updater 进度 → 网页 update:status / update:progress
    const r = await startBackend();
    if (r.aborted) { shellLog('后端启动中止，外壳退出'); return; }
    // 先出窗口再放托盘：托盘是增强（关窗后台运行），窗口与后端才是本体。
    // 顺序颠倒时，托盘一旦抛错会连窗口都开不出来（打包态无提示＝双击没反应）。
    createWindow();
    try { createTray(); } catch (err) { shellLog('托盘初始化异常（已忽略）：' + String(err)); }
  });

  // 关窗走 hide 到托盘，不再因「所有窗口关闭」而退出后端。
  // 真正退出只由托盘菜单「退出」或 before-quit（系统关机等）触发 shutdown。
  app.on('window-all-closed', () => {
    if (!tray && !quitting) shutdown();  // 降级模式（无托盘）仍保持关窗即退
  });

  app.on('will-quit', () => {
    if (tray) { tray.destroy(); tray = null; }
  });
  // 任何退出路径（关窗 / 系统关机 / Cmd+Q）都先回收进程树再真正退出。
  app.on('before-quit', (event) => {
    if (cleanupDone) return;
    event.preventDefault();
    shutdown();
  });
}
