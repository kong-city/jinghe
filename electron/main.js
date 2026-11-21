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
const { spawn, spawnSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const http = require('http');
const net = require('net');

const PORT = Number(process.env.JINGHE_PORT || 54321);
const HOST = '127.0.0.1';
const APP_URL = `http://${HOST}:${PORT}/`;

let backend = null;            // 由本进程拉起的 Python 后端子进程
let backendPid = null;         // spawn 当即记下 PID（exit 后 ChildProcess.pid 可能清空）
let adoptedBackendPid = null;  // 端口上已存在的精核后端 PID（上次崩溃遗留），关窗时需回收
let mainWindow = null;         // 主窗口
let quitting = false;          // 退出流程防重入
let cleanupDone = false;       // 子进程回收完成，before-quit 才放行

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
    if (!quitting) {
      dialog.showErrorBox('精核无法启动', '无法启动后端进程：\n' + String(err));
      shutdown();
    }
  });
  backend.on('exit', (code) => {
    if (!quitting) {
      console.error('[jinghe] 后端意外退出 code=' + code);
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

async function shutdown() {
  if (quitting) return;
  quitting = true;
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
  } finally {
    cleanupDone = true;
    app.quit();
  }
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
  // 任何退出路径（关窗 / 系统关机 / Cmd+Q）都先回收进程树再真正退出。
  app.on('before-quit', (event) => {
    if (cleanupDone) return;
    event.preventDefault();
    shutdown();
  });
}
