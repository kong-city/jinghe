/*
 * 精核 · Electron preload
 * ---------------------------------------------------------------------------
 * 安全边界：contextIsolation = true，页面拿不到 Node/require。
 * 本文件通过 contextBridge 暴露两组**只读/具名** API：
 *   1) JINGHE_SHELL —— 只读外壳标记，供前端识别「正运行在 Electron 壳里」；
 *   2) desktopUpdater —— 自更新（方案 A）的白名单通道。
 *
 * 绝不暴露 ipcRenderer 本体：页面只能调用下面列出的固定方法，无法任意发
 * channel。事件回调只回传 payload，不回传 event 对象——杜绝经 event.sender
 * 反向操控主进程。后端原有的 Origin 校验在 Electron 下同样生效。
 */
'use strict';

const { contextBridge, ipcRenderer } = require('electron');

// 固定的 channel 白名单：与 electron/main.js 的 ipcMain.handle 一一对应。
const UPDATE_CHANNELS = Object.freeze({
  check: 'update:check',
  download: 'update:download',
  install: 'update:install',
  cancel: 'update:cancel',
  status: 'update:status',
  progress: 'update:progress',
});

// 原生菜单通道：页面切语言时同步菜单，菜单「关于」时通知页面跳页。
const MENU_CHANNELS = Object.freeze({
  setLang: 'menu:set-lang',
  navigate: 'menu:navigate',
});

// 把 event 剥掉，只把 data 交给页面回调；返回退订函数供页面清理监听器。
function subscribe(channel, callback) {
  if (typeof callback !== 'function') return function () {};
  const listener = function (_event, data) { callback(data); };
  ipcRenderer.on(channel, listener);
  return function () { ipcRenderer.removeListener(channel, listener); };
}

contextBridge.exposeInMainWorld('JINGHE_SHELL', Object.freeze({
  name: 'electron',
  electron: process.versions.electron || '',
  chromium: process.versions.chrome || '',
}));

contextBridge.exposeInMainWorld('desktopMenu', Object.freeze({
  available: true,
  // 只接受白名单枚举后的语言值，避免任意字符串污染主进程菜单模板。
  setLang: function (lang) {
    var normalized = (lang === 'en') ? 'en' : 'zh';
    return ipcRenderer.invoke(MENU_CHANNELS.setLang, normalized);
  },
  onNavigate: function (cb) { return subscribe(MENU_CHANNELS.navigate, cb); },
}));

contextBridge.exposeInMainWorld('desktopUpdater', Object.freeze({
  // 前端据此选择「IPC 通道」还是「后端 HTTP 兼容通道」。
  available: true,

  check: function () { return ipcRenderer.invoke(UPDATE_CHANNELS.check); },
  download: function () { return ipcRenderer.invoke(UPDATE_CHANNELS.download); },
  install: function () { return ipcRenderer.invoke(UPDATE_CHANNELS.install); },
  cancel: function () { return ipcRenderer.invoke(UPDATE_CHANNELS.cancel); },

  // 进度与状态事件：只回传纯数据 payload。
  onStatus: function (cb) { return subscribe(UPDATE_CHANNELS.status, cb); },
  onProgress: function (cb) { return subscribe(UPDATE_CHANNELS.progress, cb); },
}));
