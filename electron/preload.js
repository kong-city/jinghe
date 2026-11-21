/*
 * 精核 · Electron preload
 * ---------------------------------------------------------------------------
 * 当前 UI 通过 fetch('/api/*') 与后端通信，全部走同源 HTTP，不需要任何
 * Electron 专用 API。此文件刻意保持最小：只暴露一个只读的 shell 标记，
 * 供前端/调试识别「正运行在 Electron 壳里」，不赋予任何额外权限。
 *
 * 注意：contextIsolation = true，页面拿不到 Node/require，安全边界与
 * 浏览器一致；后端原有的 Origin 校验（只放行 127.0.0.1）在 Electron 下
 * 同样生效——Electron 加载的页面 Origin 仍是 http://127.0.0.1:PORT。
 */
'use strict';

const { contextBridge } = require('electron');

contextBridge.exposeInMainWorld('JINGHE_SHELL', Object.freeze({
  name: 'electron',
  electron: process.versions.electron || '',
  chromium: process.versions.chrome || '',
}));
