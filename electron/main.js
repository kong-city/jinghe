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

const { app, BrowserWindow, dialog, shell } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const http = require('http');
const net = require('net');

const PORT = Number(process.env.JINGHE_PORT || 54321);
const HOST = '127.0.0.1';
const APP_URL = `http://${HOST}:${PORT}/`;

let backend = null;      // 由本进程拉起的 Python 后端子进程
let mainWindow = null;   // 主窗口
let quitting = false;    // 退出流程防重入

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
/* 启动后端（尊重已有实例：端口上已有精核则直接复用，不再重复拉起）              */
/* -------------------------------------------------------------------------- */
async function startBackend() {
  if (await portReady(PORT, 800)) {
    const ours = await isJingheListening(PORT);
    if (ours) {
      console.log('[jinghe] 复用已在运行的后端实例 port=' + PORT);
      return { reused: true };
    }
    // 端口被别的程序占用：明确报错，绝不劫持
    dialog.showErrorBox('精核无法启动',
      `端口 ${PORT} 已被其他程序占用（非精核）。\n\n请关闭占用该端口的程序后重试。`);
    app.quit();
    return { aborted: true };
  }

  const { cmd, args, cwd } = backendCommand();
  console.log('[jinghe] 启动后端:', cmd, args.join(' '));
  try {
    backend = spawn(cmd, args, {
      cwd,
      windowsHide: true,
      detached: false,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
  } catch (err) {
    dialog.showErrorBox('精核无法启动', '无法启动后端进程：\n' + String(err));
    app.quit();
    return { aborted: true };
  }
  backend.stdout.on('data', (d) => process.stdout.write('[backend] ' + d));
  backend.stderr.on('data', (d) => process.stderr.write('[backend] ' + d));
  backend.on('exit', (code) => {
    if (!quitting) {
      console.error('[jinghe] 后端意外退出 code=' + code);
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
    backgroundColor: '#f5f6f8',
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

  mainWindow.on('closed', () => { mainWindow = null; });
}

function shutdown() {
  if (quitting) return;
  quitting = true;
  if (backend && !backend.killed) {
    try { backend.kill(); } catch (_) { /* 已退出 */ }
  }
  app.quit();
}

/* -------------------------------------------------------------------------- */
/* 单实例 + 生命周期                                                            */
/* -------------------------------------------------------------------------- */
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    // 再次双击：唤起已有窗口（后端由第一个实例托管）
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });

  app.whenReady().then(async () => {
    const r = await startBackend();
    if (r.aborted) return;
    createWindow();
  });

  app.on('window-all-closed', shutdown);
  app.on('before-quit', () => {
    if (backend && !backend.killed) {
      try { backend.kill(); } catch (_) { /* noop */ }
    }
  });
}
