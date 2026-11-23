/* 精核 · 本地界面逻辑（原生 JS，无依赖） */
"use strict";

(function () {
  var POLL_MS = 400;
  var $ = function (id) { return document.getElementById(id); };

  var el = {
    inputPath: $("inputPath"),
    outPath: $("outPath"),
    btnPickFiles: $("btnPickFiles"),
    btnBrowseOut: $("btnBrowseOut"),
    btnPreview: $("btnPreview"),
    btnPreviewInline: $("btnPreviewInline"),
    btnRun: $("btnRun"),
    btnCancel: $("btnCancel"),
    btnOpenMerged: $("btnOpenMerged"),
    optOpenMerged: $("optOpenMerged"),
    errorBar: $("errorBar"),
    runStatus: $("runStatus"),
    progressBar: $("progressBar"),
    inputMeta: $("inputMeta"),
    dropZone: $("dropZone"),
    toast: $("toast"),
    fileListTitle: $("fileListTitle"),
    fileList: $("fileList"),
    fileListEmpty: $("fileListEmpty"),
    btnToggleFiles: $("btnToggleFiles"),
    fileCheckAll: $("fileCheckAll"),
    fileCheckAllWrap: $("fileCheckAllWrap"),
    mSuccess: $("mSuccess"),
    mSuccessLabel: $("mSuccessLabel"),
    mFailed: $("mFailed"),
    mDeferred: $("mDeferred"),
    mElapsed: $("mElapsed"),
    overviewHint: $("overviewHint"),
    degradedTable: $("degradedTable"),
    degradedBody: $("degradedBody"),
    degradedEmpty: $("degradedEmpty"),
    degradedBadge: $("degradedBadge"),
    logBox: $("logBox"),
    btnSummarize: $("btnSummarize"),
    btnExportDocx: $("btnExportDocx"),
    btnWordEnhance: $("btnWordEnhance"),
    btnAudioTranscribe: $("btnAudioTranscribe"),
    btnAudioCancel: $("btnAudioCancel"),
    btnVideoTranscribe: $("btnVideoTranscribe"),
    btnVideoCancel: $("btnVideoCancel"),
    // S5：视频链接 → .md
    linkUrls: $("linkUrls"),
    linkCookie: $("linkCookie"),
    btnLinkRun: $("btnLinkRun"),
    btnLinkInspect: $("btnLinkInspect"),
    btnLinkCancel: $("btnLinkCancel"),
    linkStatus: $("linkStatus"),
    linkCap: $("linkCap"),
    // v1.1.0：知识库页（S9 后端端点已实现，此前首页按钮仅是「规划中」占位）
    btnKbIngest: $("btnKbIngest"),
    btnKbRefresh: $("btnKbRefresh"),
    kbStatus: $("kbStatus"),
    kbStats: $("kbStats"),
    kbQuery: $("kbQuery"),
    btnKbQuery: $("btnKbQuery"),
    kbResults: $("kbResults"),
    // S12a：订阅博主/频道
    subUrl: $("subUrl"),
    subName: $("subName"),
    subCookie: $("subCookie"),
    subInterval: $("subInterval"),
    subSchedHint: $("subSchedHint"),
    subCapHint: $("subCapHint"),
    subStatus: $("subStatus"),
    subEvents: $("subEvents"),
    subList: $("subList"),
    btnSubAdd: $("btnSubAdd"),
    btnSubSyncAll: $("btnSubSyncAll"),
    btnSubCancel: $("btnSubCancel"),
    btnSubRefresh: $("btnSubRefresh"),
    toolStatus: $("toolStatus"),
    // 左侧导航与页面
    appShell: $("appShell"),
    sidebar: $("sidebar"),
    navResizer: $("navResizer"),
    pageTitle: $("pageTitle"),
    pageSub: $("pageSub"),
    headerTag: $("headerTag"),
    pages: {
      home: $("page-home"),
      process: $("page-process"),
      kb: $("page-kb"),
      refine: $("page-refine"),
      revise: $("page-revise"),
      settings: $("page-settings"),
      about: $("page-about")
    },
    // 设置页
    setAutoExit: $("setAutoExit"),
    setExitGrace: $("setExitGrace"),
    setRememberPaths: $("setRememberPaths"),
    setDefaultOutdir: $("setDefaultOutdir"),
    setDefaultIndir: $("setDefaultIndir"),
    btnPickIndir: $("btnPickIndir"),
    btnPickOutdir: $("btnPickOutdir"),
    btnSaveSettings: $("btnSaveSettings"),
    btnResetSettings: $("btnResetSettings"),
    settingsStatus: $("settingsStatus"),
    // S10：相关组件列表
    componentList: $("componentList"),
    // S7d：精读 / 修订页 + 后端配置
    refineCap: $("refineCap"),
    refineSource: $("refineSource"),
    refineModel: $("refineModel"),
    btnPickRefine: $("btnPickRefine"),
    btnStartRefine: $("btnStartRefine"),
    btnCancelRefine: $("btnCancelRefine"),
    refineProgress: $("refineProgress"),
    refineResult: $("refineResult"),
    refineResultPath: $("refineResultPath"),
    refinePreview: $("refinePreview"),
    btnOpenRefine: $("btnOpenRefine"),
    btnSendToRevise: $("btnSendToRevise"),
    reviseCap: $("reviseCap"),
    reviseSource: $("reviseSource"),
    reviseInstruction: $("reviseInstruction"),
    btnPickRevise: $("btnPickRevise"),
    btnStartRevise: $("btnStartRevise"),
    btnCancelRevise: $("btnCancelRevise"),
    reviseProgress: $("reviseProgress"),
    reviseResult: $("reviseResult"),
    revisePreviewHtml: $("revisePreviewHtml"),
    revisePreviewMd: $("revisePreviewMd"),
    btnOpenReviseHtml: $("btnOpenReviseHtml"),
    reviseSyncCheck: $("reviseSyncCheck"),
    refineArtifactSel: $("refineArtifactSel"),
    btnReloadArtifacts: $("btnReloadArtifacts"),
    revisePreviewMdEl: $("revisePreviewMd"),
    beKind: $("beKind"),
    beMode: $("beMode"),
    beRounds: $("beRounds"),
    beAllowSupplement: $("beAllowSupplement"),
    beEndpoint: $("beEndpoint"),
    beApiKey: $("beApiKey"),
    beModel: $("beModel"),
    btnSaveBackend: $("btnSaveBackend"),
    btnProbeBackend: $("btnProbeBackend"),
    backendStatus: $("backendStatus"),
    // 关于页 · 版本更新（v0.4.9：「最新版本」信息格已取消）
    aboutVersion: $("aboutVersion"),
    btnCheckUpdate: $("btnCheckUpdate"),
    btnUpdateNow: $("btnUpdateNow"),
    btnUpdateCancel: $("btnUpdateCancel"),
    updateStatus: $("updateStatus"),
    updateProgress: $("updateProgress"),
    updateProgressBar: $("updateProgressBar"),
    updateProgressText: $("updateProgressText"),
    // 关于页 · 运行日志
    aboutPython: $("aboutPython"),
    aboutPlatform: $("aboutPlatform"),
    aboutLog: $("aboutLog"),
    btnOpenAboutLog: $("btnOpenAboutLog"),
    aboutSettingsFile: $("aboutSettingsFile"),
    btnOpenAboutSettings: $("btnOpenAboutSettings"),
    btnExportData: $("btnExportData"),
    exportIncludeLogs: $("exportIncludeLogs"),
    exportDataStatus: $("exportDataStatus")
  };

  // 后端 app.log 路径（来自 /api/state.log_file）；启动即可用，按钮常亮
  var logFile = "";

  var running = false;
  var previewing = false;
  var pollTimer = null;
  var pollFails = 0;
  var since = 0;
  var summary = null;
  var lastTotal = 0;
  var stateName = "idle";
  var lastDoneOutdir = null;

  /* 多选文件路径；空数组表示单选（输入框路径）或文件夹模式 */
  var sel = { inputs: [] };

  /* v0.4.9：已识别清单的逐项数据（name / kind / path）与勾选状态。
     preview 时若清单有勾选，则只对勾选的文件预览分流。*/
  var fileItems = [];      // [{name, kind, path}]
  var fileChecked = [];    // 与 fileItems 等长的布尔数组

  function currentInputs() {
    return sel.inputs.length ? sel.inputs.slice() : [];
  }

  /* ------------------------------ 基础工具 ------------------------------ */
  function api(path, body, timeoutMs) {
    var opt = { method: body === undefined ? "GET" : "POST", headers: {} };
    if (body !== undefined) {
      opt.headers["Content-Type"] = "application/json";
      opt.body = JSON.stringify(body);
    }
    // 只有显式传入 timeoutMs>0 的请求才加 AbortController：
    // pick-* 类要等用户操作原生对话框，绝不能 abort（第三参数传 0）。
    // 裸 fetch 无超时是可证实的机制缺陷；连接层异常时它可能永久不 settle，
    // 此处为根治隐患（非针对已复现的故障），是唯一能强制结束挂起的手段。
    var ctrl = ("AbortController" in window) ? new AbortController() : null;
    var timer = null;
    var timedOut = false;
    if (timeoutMs > 0 && ctrl) {
      opt.signal = ctrl.signal;
      timer = setTimeout(function () {
        timedOut = true;
        ctrl.abort();
      }, timeoutMs);
    }
    return fetch(path, opt).then(function (res) {
      return res.text().then(function (text) {
        var data = null;
        if (text) {
          try { data = JSON.parse(text); } catch (e) {
            throw new Error("服务返回了非 JSON 内容（HTTP " + res.status + "）");
          }
        }
        if (!res.ok) {
          throw new Error((data && data.error) || ("HTTP " + res.status));
        }
        return data || {};
      });
    }).catch(function (err) {
      // 仅把本函数自己触发的超时归一化成可读中文；其它网络错误、
      // HTTP 错误、JSON 解析错误一律原样透传给调用方的 catch。
      if (timedOut) { throw new Error("请求超时，已自动恢复，请重试"); }
      throw err;
    }).finally(function () {
      // 只清 timer；状态位复位绝不依赖这里（见 doPreview 的 finally / finish / init）。
      if (timer !== null) { clearTimeout(timer); timer = null; }
    });
  }

  function pad(n) { return n < 10 ? "0" + n : String(n); }

  function nowHMS() {
    var d = new Date();
    return pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds());
  }

  function defaultOutdir() {
    if (settings.default_outdir) return settings.default_outdir;
    // 用户 2026-11-19 裁决：产物直接放系统临时目录，不再在前端拼
    // ".\out-YYYYMMDD-HHmm" 这类带随机名的相对路径子目录——相对路径会
    // 随程序工作目录漂移，老是提示「文件夹不存在」。
    // 绝对路径由后端 /api/settings 的 default_outdir_path 提供。
    if (settings.default_outdir_path) return settings.default_outdir_path;
    return "";
  }

  // ---- 桌面端便利：跨重启记住路径 ------------------------------------- //
  // 服务端的「上次输入/输出」只活在本次进程内，退出软件就没了；
  // localStorage 让桌面软件像桌面软件那样记住上次的输入与输出目录。
  var LS_INPUT = "jinghe.input";
  var LS_OUTDIR = "jinghe.outdir";

  function lsGet(key) {
    // 「记住路径」关掉后，路径类记录一律不读不写
    if ((key === LS_INPUT || key === LS_OUTDIR) && settings.remember_paths === false) return "";
    try { return window.localStorage.getItem(key) || ""; }
    catch (e) { return ""; }   // 隐私模式 / 存储被禁用：静默降级
  }

  function lsSet(key, value) {
    if ((key === LS_INPUT || key === LS_OUTDIR) && settings.remember_paths === false) return;
    try { window.localStorage.setItem(key, value || ""); }
    catch (e) { /* 存不了就算了，不影响主流程 */ }
  }

  function rememberPaths() {
    lsSet(LS_INPUT, el.inputPath.value.trim());
    lsSet(LS_OUTDIR, el.outPath.value.trim());
  }

  // ---- 左侧导航：折叠状态 + 页面切换 ------------------------------------- //
  var LS_NAV = "jinghe.nav.collapsed";
  var LS_NAV_W = "jinghe.nav.width";
  var NAV_W_MIN = 148;   // 再窄文字会被挤掉
  var NAV_W_MAX = 360;   // 再宽内容区太窄
  var NAV_W_DEFAULT = 184;
  var currentPage = "home";

  // 后端设置（来自 /api/settings）；remember_paths 决定路径要不要记
  var settings = {
    auto_exit: true,
    exit_grace_seconds: 90,
    remember_paths: true,
    default_outdir: "",
    // 默认输入路径（留空 = 用后端下发的桌面）
    default_indir: "",
    // 后端给的默认输出目录绝对路径（%TEMP%\jinghe-out，兜底）
    default_outdir_path: "",
    // 后端下发的桌面绝对路径（默认输入/输出的占位与恢复默认用）
    default_desktop: ""
  };

  function defaultIndir() {
    if (settings.default_indir) return settings.default_indir;
    return settings.default_desktop || "";
  }

  var PAGE_META = {
    home: { title: "① 获取 · 文件提取", sub: "第一步：选文件 → 预览分流 → 开始提取 → 查看结果" },
    process: { title: "① 获取 · 更多来源", sub: "文档 / 音视频 / 视频链接 → md；订阅博主在「知识库」页，后台自动同步" },
    kb: { title: "④ 沉淀 · 知识库", sub: "把产物入库为可检索条目 + 订阅博主自动更新，全部保存在本机" },
    refine: { title: "② 加工 · 提纯核心", sub: "第二步：对 md 提取核心知识点，默认抽取式（原文原句、可逐字回溯）" },
    revise: { title: "③ 加工 · 改写补充", sub: "第三步：术语归一 / 合并去重 / 改写补充，变更以颜色标记区分" },
    settings: { title: "系统 · 设置", sub: "提纯方式与迭代轮数、组件、路径——只保存在本机，改动即时生效" },
    about: { title: "系统 · 关于", sub: "版本、路线与隐私说明" }
  };

  // S14 步骤条映射函数已移除（用户 2026-11-23 裁决：删除全局步骤条）。

  function setNavCollapsed(collapsed) {
    if (!el.appShell) return;
    el.appShell.classList.toggle("nav-collapsed", !!collapsed);
    lsSet(LS_NAV, collapsed ? "1" : "");
  }

  // 侧栏宽度写在 .app 的 --sidebar-w 上：折叠态由 CSS 覆盖为 58px，
  // 展开后自动回到用户上次拖出来的宽度。拖动时临时关掉 transition 跟手。
  function applyNavWidth(px) {
    var w = Math.max(NAV_W_MIN, Math.min(NAV_W_MAX, Math.round(px)));
    if (el.appShell) el.appShell.style.setProperty("--sidebar-w", w + "px");
    return w;
  }

  function initNavResize() {
    if (!el.navResizer || !el.sidebar) return;
    var saved = parseInt(lsGet(LS_NAV_W), 10);
    if (saved >= NAV_W_MIN && saved <= NAV_W_MAX) applyNavWidth(saved);

    var dragging = false;
    var startX = 0;
    var startW = NAV_W_DEFAULT;
    var targetW = NAV_W_DEFAULT;   // 记录钳制后的目标宽度，不读动画中间帧

    el.navResizer.addEventListener("mousedown", function (e) {
      if (el.appShell.classList.contains("nav-collapsed")) return;
      dragging = true;
      startX = e.clientX;
      startW = el.sidebar.getBoundingClientRect().width;
      targetW = startW;
      el.appShell.classList.add("nav-resizing");
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
      e.preventDefault();
    });
    document.addEventListener("mousemove", function (e) {
      if (!dragging) return;
      targetW = applyNavWidth(startW + (e.clientX - startX));
    });
    document.addEventListener("mouseup", function () {
      if (!dragging) return;
      dragging = false;
      el.appShell.classList.remove("nav-resizing");
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      // 保存目标值：此时 transition 可能仍在从旧宽度动画到新宽度，
      // getBoundingClientRect() 会读到中间帧，直接用 targetW 才准确。
      lsSet(LS_NAV_W, String(targetW));
    });
    el.navResizer.addEventListener("dblclick", function () {
      targetW = applyNavWidth(NAV_W_DEFAULT);
      lsSet(LS_NAV_W, String(targetW));
    });
  }

  function activatePage(name) {
    if (!el.pages[name]) name = "home";
    currentPage = name;
    Object.keys(el.pages).forEach(function (key) {
      if (el.pages[key]) el.pages[key].hidden = (key !== name);
    });
    var items = document.querySelectorAll(".nav-item");
    for (var i = 0; i < items.length; i += 1) {
      var on = items[i].getAttribute("data-page") === name;
      items[i].classList.toggle("active", on);
    }
    var meta = PAGE_META[name] || PAGE_META.home;
    if (el.pageTitle) el.pageTitle.textContent = meta.title;
    if (el.pageSub) el.pageSub.textContent = meta.sub;
    if (name === "settings") { loadSettingsIntoForm(); loadBackendForm(); loadComponents(); }
    if (name === "about") loadAbout();
    if (name === "refine" || name === "revise") refreshRefineCap();
    // v1.1.0：进入加工页时刷新一次工具能力（按钮「未启用」判定依赖它）
    if (name === "process") loadTools();
    // v1.1.0：进入知识库页时刷新真实状态（S9 端点早已实现）
    if (name === "kb") loadKbStatus();
    if (name === "kb") loadSubList();
    // v1.0.8：进入精读页时刷新本次产物清单
    if (name === "refine") loadArtifacts();
  }

  function applySettings(cfg) {
    // 合并而非整体替换：default_outdir_path / default_desktop 是后端下发的绝对路径，
    // 不在 settings 落盘内容里，整体替换会把它抹掉（保存设置后即失效）。
    if (cfg && typeof cfg === "object") {
      var keepPath = settings.default_outdir_path;
      var keepDesktop = settings.default_desktop;
      settings = cfg;
      if (!settings.default_outdir_path && keepPath) {
        settings.default_outdir_path = keepPath;
      }
      if (!settings.default_desktop && keepDesktop) {
        settings.default_desktop = keepDesktop;
      }
    }
    if (el.setAutoExit) el.setAutoExit.checked = settings.auto_exit !== false;
    if (el.setExitGrace) el.setExitGrace.value = settings.exit_grace_seconds;
    if (el.setRememberPaths) el.setRememberPaths.checked = settings.remember_paths !== false;
    if (el.setDefaultOutdir) el.setDefaultOutdir.value = settings.default_outdir || "";
    if (el.setDefaultIndir) el.setDefaultIndir.value = settings.default_indir || "";
  }

  function loadSettingsIntoForm() {
    api("/api/settings", undefined, 10000).then(function (r) {
      if (!r || !r.ok) return;
      applySettings(r.settings);
      // 默认输出目录（绝对路径）由后端下发，前端不再自己拼
      if (r.default_outdir_path) settings.default_outdir_path = r.default_outdir_path;
      // 桌面绝对路径：默认输入/输出的占位与恢复默认用
      if (r.default_desktop) settings.default_desktop = r.default_desktop;
      // init() 先于本回调执行，那时尚无后端路径 → 这里补齐，
      // 避免输入框/输出框留空导致「请先填写」
      if (el.outPath && !el.outPath.value.trim()) {
        var dflt = defaultOutdir();
        if (dflt) el.outPath.value = dflt;
      }
      if (el.inputPath && !el.inputPath.value.trim()) {
        var din = defaultIndir();
        if (din) el.inputPath.value = din;
      }
      // 设置页两个路径框：用户从未设置时显示桌面默认值作为占位/回填
      if (el.setDefaultIndir && !el.setDefaultIndir.value.trim() && settings.default_desktop) {
        el.setDefaultIndir.value = settings.default_desktop;
      }
      if (el.setDefaultOutdir && !el.setDefaultOutdir.value.trim() && settings.default_desktop) {
        el.setDefaultOutdir.value = settings.default_desktop;
      }
    }).catch(function () { /* 设置读不到时保持现状，不打断使用 */ });
  }

  function saveSettings(payload, okText) {
    el.settingsStatus.textContent = "保存中…";
    api("/api/settings", { settings: payload }, 10000).then(function (r) {
      if (!r || !r.ok) {
        el.settingsStatus.textContent = "保存失败：" + ((r && r.error) || "未知错误");
        return;
      }
      applySettings(r.settings);
      el.settingsStatus.textContent = okText || "已保存";
      if (settings.default_outdir) el.outPath.value = settings.default_outdir;
      if (settings.default_indir) el.inputPath.value = settings.default_indir;
    }).catch(function (err) {
      el.settingsStatus.textContent = "保存失败：" + (err.message || err);
    });
  }

  function readSettingsForm() {
    return {
      auto_exit: el.setAutoExit.checked,
      exit_grace_seconds: parseInt(el.setExitGrace.value, 10) || 90,
      remember_paths: el.setRememberPaths.checked,
      default_outdir: el.setDefaultOutdir.value.trim(),
      default_indir: el.setDefaultIndir.value.trim()
    };
  }

  // 设置页：为默认输入/输出框选择文件夹（后端原生对话框，pick-* 不设超时）
  function pickDefaultFolder(inputEl) {
    if (!inputEl) return;
    api("/api/pick-folder", { path: inputEl.value.trim() }, 0).then(function (r) {
      if (r && r.ok === false && r.error) { showToast(r.error, true); return; }
      var p = (r && r.path) || "";
      if (p) inputEl.value = p;
    }).catch(function (err) {
      showToast("选择文件夹失败：" + (err.message || err), true);
    });
  }

  function loadAbout() {
    api("/api/state", undefined, 10000).then(function (st) {
      if (!st) return;
      var ver = st.version || "—";
      if (el.aboutVersion) el.aboutVersion.textContent = ver;
      if (el.aboutPython) el.aboutPython.textContent = st.python || "—";
      if (el.aboutPlatform) el.aboutPlatform.textContent = st.platform || "—";
      if (el.aboutLog) el.aboutLog.textContent = st.log_file || "—";
      // v1.0.1：设置文件路径从设置页迁来，与日志行并排显示
      api("/api/settings", undefined, 10000).then(function (sr) {
        if (el.aboutSettingsFile && sr && sr.settings_file) {
          el.aboutSettingsFile.textContent = sr.settings_file;
        }
      }).catch(function () {});
      if (el.headerTag) el.headerTag.textContent = "v" + ver;
    }).catch(function () { /* 读不到就保持占位符 */ });
  }

  /* v0.4.8：关于页「版本更新」改两步走
       ① 检查更新 → 只查版本，如实回显「当前版本 / 最新版本 / 是否有新版本」；
       ② 立即更新 → 后台下载安装包并替换运行中的程序，进度条实时显示百分比，
          替换完成后程序自动重启。
     离线、发布里没有安装包、下载失败都如实回显，绝不谎报"已是最新"。*/
  var updatePollTimer = null;
  var updateSince = 0;
  var updateRunning = false;  // v0.4.9：更新任务门闩，更新期间禁止再次点「检查更新」

  function setUpdateStatus(text, cls) {
    if (!el.updateStatus) return;
    var s = text || "";
    el.updateStatus.textContent = s;
    el.updateStatus.hidden = !s;
    el.updateStatus.className = "update-status" + (cls && s ? " " + cls : "");
  }

  function setUpdateProgress(percent, text) {
    if (!el.updateProgress) return;
    var p = Math.max(0, Math.min(100, Math.round(percent || 0)));
    el.updateProgress.hidden = false;
    if (el.updateProgressBar) el.updateProgressBar.style.width = p + "%";
    if (el.updateProgressText) el.updateProgressText.textContent = text || (p + "%");
  }

  function hideUpdateProgress() {
    if (el.updateProgress) el.updateProgress.hidden = true;
    if (el.updateProgressBar) el.updateProgressBar.style.width = "0";
  }

  /* ==================================================================== *
   * v1.2.0：Electron 外壳自更新（方案 A）——经 preload 白名单走 IPC。
   * 纯浏览器（源码调试）下 window.desktopUpdater 不存在，自动回落到下方
   * 原有的 /api/update/* HTTP 通道；两条通道互斥，同一时刻只走一条。
   * ==================================================================== */
  function hasShellUpdater() {
    return !!(window.desktopUpdater && window.desktopUpdater.available);
  }

  // Electron 外壳：检查更新 → 有新版本直接下载 → 下载完安装重启。
  function shellCheckUpdate() {
    var u = window.desktopUpdater;
    if (!el.btnCheckUpdate) return;
    if (updateRunning) { showToast("正在更新中，请稍候", false); return; }
    var old = el.btnCheckUpdate.textContent;
    el.btnCheckUpdate.disabled = true;
    el.btnCheckUpdate.textContent = "检查中…";
    setUpdateStatus("", "");
    hideUpdateProgress();
    u.check().then(function (r) {
      if (!r) throw new Error("无响应");
      if (r.dev) {
        showToast("开发模式不检查更新", false);
        return;
      }
      if (!r.ok) {
        var why = r.error || "检查更新失败";
        setUpdateStatus(why, "is-err");
        showToast(why, true);
        return;
      }
      var latest = r.latest || "—";
      if (r.up_to_date !== false) {
        setUpdateStatus("", "");
        if (el.btnUpdateNow) el.btnUpdateNow.hidden = true;
        showToast("当前是最新版本", false);
        return;
      }
      // 有新版本：显示「立即更新」并直接进入下载流程。
      if (el.btnUpdateNow) {
        el.btnUpdateNow.hidden = false;
        el.btnUpdateNow.textContent = "立即更新到 " + latest;
      }
      setUpdateStatus("发现新版本 " + latest + "，正在更新…", "is-new");
      shellStartUpdate();
    }).catch(function (err) {
      var msg = "检查更新失败：" + (err.message || String(err));
      setUpdateStatus(msg, "is-err");
      showToast(msg, true);
    }).finally(function () {
      el.btnCheckUpdate.disabled = false;
      el.btnCheckUpdate.textContent = old;
    });
  }

  var shellUnsub = null;  // 退订函数，避免重复订阅造成进度回显多次触发

  function shellStartUpdate() {
    var u = window.desktopUpdater;
    if (!el.btnUpdateNow || updateRunning) return;
    updateRunning = true;
    el.btnUpdateNow.disabled = true;
    el.btnUpdateNow.textContent = "更新中…";
    if (el.btnUpdateCancel) el.btnUpdateCancel.hidden = false;
    setUpdateStatus("正在下载更新包…", "is-new");
    setUpdateProgress(0, "0%");

    if (shellUnsub) { shellUnsub(); shellUnsub = null; }
    shellUnsub = u.onProgress(function (p) {
      if (p && typeof p.percent === "number") setUpdateProgress(p.percent, Math.round(p.percent) + "%");
    });
    // 下载完成事件：安装器接管前给一次明确回显。
    var unsubStatus = u.onStatus(function (s) {
      if (s && s.state === "downloaded") setUpdateStatus("更新包已下载，正在安装…", "is-new");
      if (s && s.state === "error") {
        updateRunning = false;
        if (shellUnsub) { shellUnsub(); shellUnsub = null; }
        if (unsubStatus) unsubStatus();
        hideUpdateProgress();
        setUpdateStatus("更新失败：" + (s.error || "未知错误"), "is-err");
        if (el.btnUpdateCancel) el.btnUpdateCancel.hidden = true;
      }
    });

    u.download().then(function (r) {
      if (!r || !r.ok) throw new Error((r && r.error) || "下载失败");
      setUpdateProgress(100, "100%");
      setUpdateStatus("正在安装，程序即将重启…", "is-new");
      return u.install();
    }).then(function (r) {
      if (!r || !r.ok) throw new Error((r && r.error) || "安装失败");
      setUpdateStatus("更新完成，程序即将重启…", "is-ok");
    }).catch(function (err) {
      updateRunning = false;
      if (shellUnsub) { shellUnsub(); shellUnsub = null; }
      if (unsubStatus) unsubStatus();
      hideUpdateProgress();
      setUpdateStatus("更新失败：" + (err.message || String(err)), "is-err");
      if (el.btnUpdateCancel) el.btnUpdateCancel.hidden = true;
    });
  }

  function shellCancelUpdate() {
    var u = window.desktopUpdater;
    u.cancel().then(function () {
      updateRunning = false;
      if (shellUnsub) { shellUnsub(); shellUnsub = null; }
      hideUpdateProgress();
      setUpdateStatus("已取消更新安装", "is-new");
      if (el.btnUpdateCancel) el.btnUpdateCancel.hidden = true;
    }).catch(function (err) {
      setUpdateStatus("取消失败：" + (err.message || String(err)), "is-err");
    });
  }

  /* v0.4.9：点击检查更新 →
       · 已是最新版本 → 弹「当前是最新版本」轻提示，3 秒自动消失；
       · 有新版本 → 直接进入更新流程（无需再点「立即更新」）；
       · 离线 / 报错 → 如实回显，绝不谎报「已是最新」。
     关键修复：/api/update/check 是 GET 端点，body 必须传 undefined，
     否则 api() 会把它当 POST 发出，命中「未知接口」404。*/
  function checkUpdate() {
    if (!el.btnCheckUpdate) return;
    // 外壳环境优先走 IPC 白名单通道（方案 A）；浏览器调试回落 HTTP。
    if (hasShellUpdater()) { shellCheckUpdate(); return; }
    // 更新进行中再次点击：只做一次轻提示，绝不重复启动更新任务。
    if (updateRunning) {
      showToast("正在更新中，请稍候", false);
      return;
    }
    var old = el.btnCheckUpdate.textContent;
    el.btnCheckUpdate.disabled = true;
    el.btnCheckUpdate.textContent = "检查中…";
    setUpdateStatus("", "");
    hideUpdateProgress();  // 清掉上一次更新残留的进度条
    api("/api/update/check", undefined, 20000).then(function (r) {
      if (!r) throw new Error("无响应");
      if (r.offline) {
        var offMsg = "无法连接版本服务，请检查网络后重试";
        setUpdateStatus(offMsg, "is-err");
        showToast(offMsg, true);
        return;
      }
      if (r.error && !r.latest) {
        var why = r.error || "检查更新失败";
        setUpdateStatus(why, "is-err");
        showToast(why, true);
        return;
      }
      var latest = r.latest_version || r.latest || "—";
      if (r.up_to_date === true) {
        setUpdateStatus("", "");
        if (el.btnUpdateNow) el.btnUpdateNow.hidden = true;
        showToast("当前是最新版本", false);
        return;
      }
      if (r.up_to_date === false) {
        if (!r.has_asset) {
          var noAsset = "发现新版本 " + latest + "，但发布里没有安装包，请到发布页手动下载";
          setUpdateStatus(noAsset, "is-err");
          if (el.btnUpdateNow) el.btnUpdateNow.hidden = true;
          return;
        }
        // 有新版本：直接进入更新流程，不再要求用户二次点击「立即更新」。
        if (el.btnUpdateNow) {
          el.btnUpdateNow.hidden = false;
          el.btnUpdateNow.textContent = "立即更新到 " + latest;
          el.btnUpdateNow.title = r.can_install ? "" : (r.install_reason || "");
        }
        setUpdateStatus("发现新版本 " + latest + "，正在更新…", "is-new");
        startUpdate();
        return;
      }
      var unknown = r.error || "无法比较版本，请稍后重试";
      setUpdateStatus(unknown, "is-err");
      showToast(unknown, true);
    }).catch(function (err) {
      var msg = "检查更新失败：" + (err.message || String(err));
      setUpdateStatus(msg, "is-err");
      showToast(msg, true);
    }).finally(function () {
      el.btnCheckUpdate.disabled = false;
      el.btnCheckUpdate.textContent = old;
    });
  }

  /* 启动更新：后端跑后台任务（查版本 → 下载 → 替换 → 重启），
     前端只轮询进度，绝不长时间阻塞在一次请求上。*/
  function startUpdate() {
    if (!el.btnUpdateNow) return;
    if (hasShellUpdater()) { shellStartUpdate(); return; }
    if (updateRunning) return;
    updateRunning = true;
    el.btnUpdateNow.disabled = true;
    el.btnUpdateNow.textContent = "更新中…";
    if (el.btnUpdateCancel) el.btnUpdateCancel.hidden = false;
    setUpdateStatus("正在更新…", "is-new");
    setUpdateProgress(0, "0%");
    updateSince = 0;
    api("/api/update/start", {}, 20000).then(function (r) {
      if (!r || !r.ok) throw new Error((r && r.error) || "无法启动更新");
      pollUpdateStatus();
    }).catch(function (err) {
      updateRunning = false;
      setUpdateStatus("更新失败：" + (err.message || String(err)), "is-err");
      el.btnUpdateNow.disabled = false;
      el.btnUpdateNow.textContent = "立即更新";
      if (el.btnUpdateCancel) el.btnUpdateCancel.hidden = true;
    });
  }

  function pollUpdateStatus() {
    if (updatePollTimer) { window.clearTimeout(updatePollTimer); updatePollTimer = null; }
    api("/api/update/status?since=" + updateSince, undefined, 8000).then(function (s) {
      if (!s) return;
      if (s.next) updateSince = s.next;
      var evs = s.events || [];
      if (evs.length && s.message) {
        if (s.percent) setUpdateProgress(s.percent, s.percent + "%");
        setUpdateStatus(s.message, "is-new");
      }
      if (s.state === "done" || s.state === "failed" ||
          s.state === "cancelled" || s.state === "restarting") {
        finishUpdate(s);
        return;
      }
      updatePollTimer = window.setTimeout(pollUpdateStatus, 700);
    }).catch(function () {
      // 轮询失败不打断更新本身，退避后重试
      updatePollTimer = window.setTimeout(pollUpdateStatus, 1500);
    });
  }

  function finishUpdate(s) {
    updateRunning = false;
    if (updatePollTimer) { window.clearTimeout(updatePollTimer); updatePollTimer = null; }
    if (el.btnUpdateCancel) el.btnUpdateCancel.hidden = true;
    if (el.btnUpdateNow) { el.btnUpdateNow.hidden = true; }
    if (s.state === "restarting") {
      setUpdateProgress(100, "100%");
      setUpdateStatus("更新完成，程序即将重启…", "is-ok");
      return;
    }
    if (s.state === "done") {
      setUpdateProgress(100, "100%");
      setUpdateStatus(s.message || "更新完成", "is-ok");
      return;
    }
    if (s.state === "cancelled") {
      hideUpdateProgress();
      setUpdateStatus("更新已取消", "is-err");
      return;
    }
    hideUpdateProgress();
    setUpdateStatus(s.error || "更新失败", "is-err");
  }

  function cancelUpdate() {
    if (hasShellUpdater()) { shellCancelUpdate(); return; }
    api("/api/update/cancel", {}, 5000).then(function (r) {
      if (!r || !r.ok) setUpdateStatus((r && r.error) || "取消失败", "is-err");
      else setUpdateStatus("已请求取消更新", "is-new");
    }).catch(function (err) {
      setUpdateStatus("取消失败：" + (err.message || err), "is-err");
    });
  }

  function showBar(kind, message) {
    el.errorBar.className = "bar " + (kind === "notice" ? "bar-notice" : "bar-error");
    el.errorBar.textContent = message;
    el.errorBar.hidden = false;
  }

  function showError(message) { showBar("error", message); }
  function showNotice(message) { showBar("notice", message); }

  /* v0.4.9：轻量提示 toast——无新版本时「当前是最新版本」，3 秒自动消失。
     用 setTimeout 而非 CSS 动画计时，确保「显示→淡出→隐藏」三段可控、可重复触发。*/
  var toastTimer = null;
  var toastFadeTimer = null;
  function showToast(message, isError) {
    if (!el.toast) return;
    if (toastTimer) { window.clearTimeout(toastTimer); toastTimer = null; }
    if (toastFadeTimer) { window.clearTimeout(toastFadeTimer); toastFadeTimer = null; }
    el.toast.textContent = message || "";
    el.toast.className = "toast" + (isError ? " is-err" : "");
    el.toast.hidden = false;
    toastTimer = window.setTimeout(function () {
      el.toast.classList.add("is-fade");
      toastFadeTimer = window.setTimeout(function () {
        el.toast.hidden = true;
        el.toast.classList.remove("is-fade");
      }, 260);
    }, 3000);
  }
  function clearBar() { el.errorBar.hidden = true; el.errorBar.textContent = ""; }

  function openLogFile() {
    if (!logFile) { showError("日志路径尚未就绪，请稍候重试。"); return; }
    api("/api/open", { path: logFile }, 10000)
      .then(function (r) {
        if (!r || !r.ok) showError("打开日志失败：" + ((r && r.error) || "未知"));
      })
      .catch(function (err) { showError("打开日志失败：" + (err.message || err)); });
  }

  /* v1.1.9：导出本机数据备份（设置 + 知识库 + 可选日志）为 .zip。
     另存为对话框要等用户操作，第三参数传 0：绝不能 abort。 */
  function exportData() {
    if (!el.btnExportData) return;
    var includeLogs = !!(el.exportIncludeLogs && el.exportIncludeLogs.checked);
    var btn = el.btnExportData;
    var old = btn.textContent;
    btn.disabled = true;
    btn.textContent = "导出中…";
    if (el.exportDataStatus) el.exportDataStatus.textContent = "正在打开另存为对话框…";
    api("/api/export-data", { path: "", include_logs: includeLogs }, 0)
      .then(function (r) {
        if (!r || !r.ok) {
          if (r && r.cancelled) {
            if (el.exportDataStatus) el.exportDataStatus.textContent = "已取消导出";
          } else {
            var msg = (r && r.error) || "未知错误";
            if (el.exportDataStatus) el.exportDataStatus.textContent = "导出失败：" + msg;
            showError("导出数据失败：" + msg);
          }
          return;
        }
        var size = Math.max(1, Math.round((r.bytes || 0) / 1024));
        var txt = "已导出 " + (r.entries || 0) + " 项（约 " + size + " KB）→ " + r.path;
        if (el.exportDataStatus) el.exportDataStatus.textContent = txt;
        showNotice("数据备份完成，已保存到你选择的位置。");
      })
      .catch(function (err) {
        if (el.exportDataStatus) el.exportDataStatus.textContent = "导出失败：" + (err.message || err);
        showError("导出数据失败：" + (err.message || err));
      })
      .finally(function () {
        btn.disabled = false;
        btn.textContent = old;
      });
  }

  function setState(name) {
    stateName = name;
    var map = { idle: "就绪", running: "运行中", cancelled: "已取消", failed: "失败" };
    // v1.0.2：状态栏信息已取消，状态机逻辑保留但不再写 DOM
  }

  function setProgress(ratio) {
    var pct = Math.max(0, Math.min(1, ratio || 0)) * 100;
    el.progressBar.style.width = pct.toFixed(1) + "%";
  }

  function updateControls() {
    var lock = running || previewing;
    var ids = ["inputPath", "outPath", "btnPickFiles", "btnBrowseOut",
      "btnRun", "btnPreview", "btnPreviewInline"];
    ids.forEach(function (id) { $(id).disabled = lock; });
    el.btnCancel.disabled = !running;
  }

  /* ------------------------------ 分流展示 ------------------------------ */
  var KIND_CLASS = {
    "文本类": "text",
    "富文档": "rich",
    "阶段3预留": "deferred",
    "需预处理": "legacy",
    "不支持": "unsupported"
  };

  var FILE_LIST_MAX = 500;

  /* v0.3.8：已识别清单已从输入卡片移到右列独立卡片，常显不隐藏；
     空态时显示提示文字并隐藏列表与「收起」按钮，避免右列留一大块空白。*/
  function clearFileList() {
    el.fileList.textContent = "";
    el.fileList.hidden = true;
    fileItems = [];
    fileChecked = [];
    if (el.fileListTitle) el.fileListTitle.textContent = "已识别 0 个文件";
    if (el.btnToggleFiles) el.btnToggleFiles.hidden = true;
    if (el.fileCheckAllWrap) el.fileCheckAllWrap.hidden = true;
    if (el.fileCheckAll) el.fileCheckAll.checked = true;
    if (el.fileListEmpty) el.fileListEmpty.hidden = false;
  }

  /* 全选/取消全选：同时刷新每行的复选框、行高亮与内部勾选数组。*/
  function setAllChecked(checked) {
    fileChecked = fileItems.map(function () { return !!checked; });
    var boxes = el.fileList.querySelectorAll('input[type="checkbox"][data-file-idx]');
    for (var i = 0; i < boxes.length; i += 1) {
      var idx = Number(boxes[i].getAttribute("data-file-idx"));
      boxes[i].checked = !!checked;
      var row = boxes[i].closest ? boxes[i].closest(".file-item") : boxes[i].parentNode;
      if (row) row.classList.toggle("is-selected", !!checked);
      if (Number.isNaN(idx)) continue;
      fileChecked[idx] = !!checked;
    }
  }

  function renderFileList(data) {
    var items = Array.isArray(data.items) ? data.items : [];
    if (!items.length) { clearFileList(); return; }

    // 保存逐项数据与勾选状态（默认全选）
    fileItems = items.map(function (it) {
      return {name: it.name || "", kind: it.kind || "未知", path: it.path || ""};
    });
    fileChecked = fileItems.map(function () { return true; });

    el.fileList.textContent = "";
    var shown = items.length > FILE_LIST_MAX ? items.slice(0, FILE_LIST_MAX) : items;

    shown.forEach(function (item, i) {
      var li = document.createElement("li");
      li.className = "file-item is-selected";

      var check = document.createElement("input");
      check.type = "checkbox";
      check.setAttribute("data-file-idx", String(i));
      check.checked = true;
      check.title = "勾选后点「预览分流」只预览选中的文件";
      check.addEventListener("change", function () {
        var idx = Number(check.getAttribute("data-file-idx"));
        if (!Number.isNaN(idx) && idx < fileChecked.length) fileChecked[idx] = check.checked;
        li.classList.toggle("is-selected", check.checked);
        syncCheckAll();
      });
      li.appendChild(check);

      var kind = item.kind || "未知";
      var chip = document.createElement("span");
      chip.className = "file-kind kind-" + (KIND_CLASS[kind] || "other");
      chip.textContent = kind;
      li.appendChild(chip);

      var name = document.createElement("span");
      name.className = "file-name";
      name.textContent = item.name || "—";
      name.title = it_path_title(item);
      li.appendChild(name);

      el.fileList.appendChild(li);
    });

    if (items.length > shown.length) {
      var more = document.createElement("li");
      more.className = "file-more";
      more.textContent = "…还有 " + (items.length - shown.length) + " 个文件未列出（未列出的按全选处理）";
      el.fileList.appendChild(more);
    }

    var counted = Number(data.total || 0);
    if (!counted) counted = items.length;
    el.fileListTitle.textContent = "已识别 " + counted + " 个文件";

    el.fileList.hidden = false;
    if (el.fileListEmpty) el.fileListEmpty.hidden = true;
    if (el.btnToggleFiles) {
      el.btnToggleFiles.hidden = false;
      el.btnToggleFiles.textContent = "收起";
    }
    if (el.fileCheckAllWrap) el.fileCheckAllWrap.hidden = false;
    if (el.fileCheckAll) el.fileCheckAll.checked = true;
  }

  function it_path_title(item) {
    return item.path ? (item.name + "\n" + item.path) : (item.name || "");
  }

  function syncCheckAll() {
    if (!el.fileCheckAll) return;
    var anyFalse = fileChecked.some(function (v) { return !v; });
    var anyTrue = fileChecked.some(function (v) { return !!v; });
    el.fileCheckAll.checked = !anyFalse;
    el.fileCheckAll.indeterminate = anyTrue && anyFalse;
  }

  /* 取勾选文件的真实路径作为预览输入；无 path 时回退用 name。
     全不选返回空数组，由调用方给出「请先勾选」提示，避免误判成预览全部。*/
  function checkedFilePaths() {
    var out = [];
    for (var i = 0; i < fileItems.length; i += 1) {
      if (fileChecked[i]) out.push(fileItems[i].path || fileItems[i].name);
    }
    return out;
  }

  /* ------------------------------ 预览 ------------------------------ */
  /* forcedInputs：v0.4.9 清单勾选后传入的选中文件路径；为空则走原有全量输入。*/
  function doPreview(forcedInputs) {
    var input = el.inputPath.value.trim();
    var explicit = Array.isArray(forcedInputs) ? forcedInputs.slice() : [];
    if (!input && !explicit.length) { showError("请先填写输入路径"); return; }
    if (running || previewing) { showNotice("正在处理，请稍候…"); return; }
    rememberPaths();
    clearBar();
    previewing = true;
    updateControls();
    var oldInline = el.btnPreviewInline.textContent;
    var oldMain = el.btnPreview.textContent;
    el.btnPreviewInline.textContent = "预览中…";
    el.btnPreview.textContent = "预览中…";

    var chosen = explicit.length ? explicit : currentInputs();
    var body = chosen.length ? { inputs: chosen } : { input: input };
    // v0.4.9 交互打磨：勾选预览是「只读盘点」，只用选中文件算一次分类统计，
    // 绝不能拿子集去重建「已识别清单」——那会让未勾选的文件凭空消失、勾选态归零。
    var isSubsetPreview = explicit.length > 0;
    // 40000 = 后端 _dry_run 的 DRY_RUN_TIMEOUT(30s) + 10s 余量，
    // 避免前端误杀合法的长盘点。
    api("/api/dry-run", body, 40000).then(function (r) {
      if (!r.ok) throw new Error(r.error || "预览分流失败");
      if (!isSubsetPreview) renderFileList(r);
      // U1：常驻可见的完成反馈，每次重写且带本地时间戳，
      // 即便数字与上次完全相同，用户也能看出「这次点下去了、程序回应了」。
      var b = r.buckets || {};
      var total = Number(r.total || 0);
      var stamp = nowHMS();
      var lead = isSubsetPreview
        ? "已按勾选的 " + chosen.length + " 个文件预览 · 命中 " + total + " 个 · "
        : "预览完成 · 共 " + total + " 个文件 · ";
      if (total > 0) {
        el.inputMeta.textContent = lead +
          "文本类 " + Number(b["文本类"] || 0) + " / 富文档 " + Number(b["富文档"] || 0) +
          " / 阶段3预留 " + Number(b["阶段3预留"] || 0) + " / 需预处理 " +
          Number(b["需预处理"] || 0) + " / 不支持 " + Number(b["不支持"] || 0) +
          " · " + stamp;
      } else {
        el.inputMeta.textContent = isSubsetPreview
          ? "勾选的 " + chosen.length + " 个文件未发现可识别内容 · " + stamp
          : "预览完成 · 未发现可识别文件 · " + stamp;
      }
      el.inputMeta.classList.add("filled");
    }).catch(function (err) {
      // U1：失败同样给带时间的明确文案，不只写「预览失败」。
      el.inputMeta.textContent = "预览失败 · " + (err.message || String(err)) + " · " + nowHMS();
      el.inputMeta.classList.remove("filled");
      clearFileList();
      showError(err.message || String(err));
    }).finally(function () {
      // 成功、失败、catch 自身抛错、api reject/abort 四条路径都会走到这里。
      // 绝不能写成 .then(cleanup)：catch 抛错时会跳过它，导致 previewing 永久 true。
      previewing = false;
      el.btnPreviewInline.textContent = oldInline;
      el.btnPreview.textContent = oldMain;
      updateControls();
    });
  }

  /* ------------------------------ 输出目录打开 ------------------------------ */
  // 首页输出区「打开」：只在系统文件管理器中浏览当前输出**文件夹**，
  // 不再弹「选择文件夹」对话框、也不接受文件（后端只收目录）。
  // 想改输出目录可直接编辑输入框。
  function browseOutput() {
    // 反馈统一走顶部 toast：errorBar 位于页面底部（约 1000px 以下），
    // 用户在输出卡片点按钮时看不见它，会误以为「点了没反应」。
    if (running || previewing) {
      showToast("任务进行中，完成后再打开输出文件夹", true);
      return;
    }
    var target = (el.outPath.value || "").trim();
    if (!target) {
      showToast("请先设置输出目录（在上方输入框填写，或先完成一次提取）", true);
      return;
    }
    api("/api/open-folder", { path: target }, 10000).then(function (r) {
      if (!r || !r.ok) {
        showToast("打开文件夹失败：" + ((r && r.error) || "未知"), true);
        return;
      }
      showToast("已打开输出文件夹", false);
    }).catch(function (err) {
      showToast("打开文件夹失败：" + (err.message || err), true);
    });
  }

  /* ------------------------------ 拖拽输入（v0.4.9） ------------------------------ */
  /* 普通 Edge 页面拿不到拖入文件的本地绝对路径，只能把文件内容上传到本机后端，
     由 /api/drop-files 落到暂存目录后返回真实路径，再走既有 dry-run 识别。 */
  function uploadDropped(fileList) {
    var files = [];
    for (var i = 0; i < fileList.length; i += 1) files.push(fileList[i]);
    if (!files.length) return;
    if (running || previewing) { showNotice("正在处理，请稍候…"); return; }
    var zone = el.dropZone;
    if (zone) zone.classList.add("is-busy");
    var oldMeta = el.inputMeta.textContent;
    el.inputMeta.textContent = "正在接收 " + files.length + " 个拖入文件…";
    el.inputMeta.classList.remove("filled");

    var paths = [];
    var errors = [];
    var chain = Promise.resolve();
    files.forEach(function (file) {
      chain = chain.then(function () {
        return fetch("/api/drop-files?name=" + encodeURIComponent(file.name || "dropped.bin"), {
          method: "POST",
          headers: {"Content-Type": "application/octet-stream"},
          body: file
        }).then(function (res) {
          return res.text().then(function (text) {
            var data = null;
            try { data = JSON.parse(text); } catch (e) { data = null; }
            if (!res.ok || !data || !data.ok) {
              throw new Error((data && data.error) || ("HTTP " + res.status));
            }
            paths.push(data.path);
          });
        }).catch(function (err) {
          errors.push((file.name || "文件") + "：" + (err.message || err));
        });
      });
    });

    chain.then(function () {
      if (zone) zone.classList.remove("is-busy");
      if (!paths.length) {
        el.inputMeta.textContent = "拖入失败 · " + errors.join("；");
        showError(errors.join("；") || "拖入失败");
        return;
      }
      sel.inputs = paths;
      el.inputPath.value = paths[0];
      el.inputPath.title = paths.join("\n");
      el.inputMeta.textContent = "已接收 " + paths.length + " 个拖入文件" +
        (errors.length ? "（" + errors.length + " 个失败：" + errors.join("；") + "）" : "");
      el.inputMeta.classList.add("filled");
      // 接收完成后直接识别分流，与「打开」按钮保持一致的体验。
      doPreview();
    });
  }

  function setupDropZone() {
    var zone = el.dropZone;
    if (!zone) return;
    // v0.4.9：整页兜底——拖到框外的文件若被浏览器默认处理会直接打开文件、
    // 跳出应用。整页禁掉 dragover/drop 默认行为，引导用户拖进框内。
    ["dragover", "drop"].forEach(function (evt) {
      document.addEventListener(evt, function (e) { e.preventDefault(); });
    });
    // 点击拖拽框 = 触发原生多选（与「打开」一致），文件或目录都支持。
    zone.addEventListener("click", function () {
      if (!running && !previewing) pickFiles();
    });
    zone.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pickFiles(); }
    });
    ["dragenter", "dragover"].forEach(function (evt) {
      zone.addEventListener(evt, function (e) {
        e.preventDefault();
        if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
        zone.classList.add("is-over");
      });
    });
    ["dragleave", "dragend"].forEach(function (evt) {
      zone.addEventListener(evt, function () { zone.classList.remove("is-over"); });
    });
    zone.addEventListener("drop", function (e) {
      e.preventDefault();
      zone.classList.remove("is-over");
      if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) {
        uploadDropped(e.dataTransfer.files);
      }
    });
  }

  /* ------------------------------ 文件选择（多选） ------------------------------ */
  function pickFiles() {
    if (running || previewing) return;
    var btn = el.btnPickFiles;
    var old = btn.textContent;
    btn.disabled = true;
    btn.textContent = "打开中…";
    // 多选后输入框里是展示文案（「C:\a\x.pdf 等 3 个文件」），不能当 initial 传给后端；
    // 有已选路径时用第一条真实路径定位。
    var initial = sel.inputs.length ? sel.inputs[0] : el.inputPath.value.trim();
    // pick-files 要等用户操作原生对话框，第三参数传 0 = 绝不 abort。
    api("/api/pick-files", { initial: initial }, 0).then(function (r) {
      // 后端区分「取消」(error=null, paths=[]) 与「打不开」(error=原因)：
      // 后者必须显式告知，否则用户点按钮只觉得「没反应」。
      if (r && r.error) { showError(r.error); return; }
      var paths = (r && Array.isArray(r.paths)) ? r.paths : [];
      if (!paths.length) return;
      sel.inputs = paths;
      // 输入框只放**首个真实路径**，绝不拼「等 N 个文件」这种假路径——
      // 它在可编辑框里，用户敲一下就会把假串当成真输入去提取。
      // 件数与全量清单交给 inputMeta 与文件清单显示。
      el.inputPath.value = paths[0];
      el.inputPath.title = paths.join("\n");
      doPreview();
    }).catch(function (err) {
      showError("打开文件选择框失败：" + (err.message || err));
    }).finally(function () {
      btn.textContent = old;
      updateControls();
    });
  }

  /* ------------------------------ 运行 ------------------------------ */
  function resetRunUI() {
    since = 0;
    summary = null;
    lastTotal = 0;
    pollFails = 0;
    el.logBox.textContent = "";
    el.runStatus.textContent = "";
    setProgress(0);
    el.mSuccess.textContent = "—";
    el.mSuccessLabel.textContent = "成功产出";
    el.mFailed.textContent = "—";
    el.mDeferred.textContent = "—";
    el.mElapsed.textContent = "—";
    // v1.0.2：状态栏信息已取消
    el.overviewHint.textContent = "正在运行…";
    el.degradedBody.textContent = "";
    el.degradedTable.hidden = true;
    el.degradedEmpty.hidden = false;
    el.degradedEmpty.textContent = "本次运行没有降级项";
    el.degradedBadge.hidden = true;
    el.degradedBadge.textContent = "0";
    el.btnOpenMerged.disabled = true;
    lastDoneOutdir = null;
    updateFeatureButtons();
  }

  function startRunning() {
    running = true;
    setState("running");
    updateControls();
    if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
    poll();
  }

  function doRun() {
    var input = el.inputPath.value.trim();
    var outdir = el.outPath.value.trim();
    if (!input) { showError("请先填写输入路径"); return; }
    if (!outdir) { showError("请先填写输出目录"); return; }
    if (running) return;
    rememberPaths();
    clearBar();
    resetRunUI();
    var runBody = { outdir: outdir };
    if (currentInputs().length) runBody.inputs = currentInputs();
    else runBody.input = input;
    api("/api/run", runBody, 10000).then(function (r) {
      if (!r.ok) {
        showError(r.error || "无法启动任务");
        if (typeof r.error === "string" && r.error.indexOf("已有任务") >= 0) startRunning();
        return;
      }
      startRunning();
    }).catch(function (err) {
      showError("启动失败：" + (err.message || err));
      running = false;
      setState("failed");
      updateControls();
    });
  }

  function appendEvent(ev) {
    var text = (typeof ev.raw === "string" ? ev.raw : ev.text) || "";
    var nearBottom = el.logBox.scrollTop + el.logBox.clientHeight >= el.logBox.scrollHeight - 24;
    el.logBox.appendChild(document.createTextNode(text + "\n"));
    if (nearBottom) el.logBox.scrollTop = el.logBox.scrollHeight;
  }

  function applyProgress(r) {
    var events = r.events || [];
    events.forEach(function (ev) {
      if (typeof ev.i === "number" && ev.i > since) since = ev.i;
      appendEvent(ev);
      if (ev.type === "progress") {
        var ratio = typeof ev.progress === "number" ? ev.progress : null;
        if (ratio !== null) setProgress(ratio);
        var total = Number(ev.total || r.total || lastTotal || 0);
        if (total) lastTotal = total;
        var current = Number(ev.current || 0);
        if (!current && ratio !== null && lastTotal) current = Math.round(ratio * lastTotal);
        var text = "处理 " + (ev.text || "");
        if (current && lastTotal) text += " · " + current + " / " + lastTotal;
        el.runStatus.textContent = text;
      }
      if (ev.type === "log" && /\[ERROR\]/.test(ev.text || "")) {
        showError(ev.text);
      }
    });
    if (typeof r.next === "number" && r.next > since) since = r.next;
    if (r.summary) summary = r.summary;
    if (r.total) lastTotal = r.total;
  }

  function poll() {
    pollTimer = null;
    api("/api/progress?since=" + since, undefined, 10000).then(function (r) {
      pollFails = 0;
      applyProgress(r);
      if (r.running) {
        pollTimer = setTimeout(poll, POLL_MS);
        return;
      }
      running = false;
      updateControls();
      finish(r);
    }).catch(function (err) {
      // 只覆盖请求 reject / then 链抛错；对「请求挂起」无效——
      // 挂起由 api() 的 AbortController 超时（M1）强制 reject 后才会走到这里。
      // pollFails 是硬上限：连续 3 次失败即复位 running、停止续轮询。
      pollFails += 1;
      if (pollFails >= 3) {
        running = false;
        updateControls();
        setState("failed");
        showError("与本地服务的连接中断：" + (err.message || err));
      } else {
        pollTimer = setTimeout(poll, 800);
      }
    });
  }

  /* ------------------------------ 收尾渲染 ------------------------------ */
  function chipClass(status) {
    if (status.indexOf("待人工授权") >= 0) return "chip chip-orange";
    if (status.indexOf("无效") >= 0 || status.indexOf("转换失败") >= 0) return "chip chip-red";
    return "chip chip-gray";
  }

  function shortStatus(status) {
    if (status.indexOf("待人工授权") >= 0) return "待人工授权";
    if (status.indexOf("无效") >= 0 || status.indexOf("转换失败") >= 0) return "无效容器";
    if (status.indexOf("阶段 3") >= 0 || status.indexOf("阶段3") >= 0) return "阶段 3 待支持";
    var i = status.indexOf("：");
    return i > 0 ? status.slice(0, i) : status;
  }

  var PREP_TIP = "需预处理 = 旧版二进制格式，请先另存为 .docx/.xlsx/.pptx；" +
    "不支持 = 扩展名不在支持清单";

  function renderPrep(s) {
    // v1.0.2：底部状态栏信息全部取消，此处不再写 DOM（保留签名供既有调用）
    return;
  }

  function renderSummary(s, state) {
    if (!s) {
      el.overviewHint.textContent = "未取得汇总信息（任务未正常结束）。";
      return;
    }
    var cancelled = state === "cancelled";
    var produced = s.produced != null ? s.produced : (s.success || 0);
    var cand = s.candidates != null ? s.candidates : 0;
    var failed = s.failed != null ? s.failed : 0;

    // 取消时只承诺「已产出多少」，绝不写成「成功 N」
    el.mSuccessLabel.textContent = cancelled ? "已产出（未完成）" : "成功产出";
    el.mSuccess.textContent = String(cancelled ? produced : (s.success != null ? s.success : 0));
    el.mFailed.textContent = cancelled ? "—" : String(failed);
    el.mDeferred.textContent = cancelled ? "—" : String(s.deferred != null ? s.deferred : 0);
    el.mElapsed.textContent = (s.elapsed != null ? Number(s.elapsed).toFixed(1) : "0.0");

    renderPrep(s);

    if (cancelled) {
      el.overviewHint.textContent = "任务已取消，已产出 " + produced + " 项，产物不完整；细节见「运行日志」。";
    } else {
      el.overviewHint.textContent = failed > 0
        ? "候选 " + cand + " 项 · 成功 " + (s.success || 0) + " / 未成功 " + failed +
          "，逐条处置见「降级明细」。"
        : "候选 " + cand + " 项全部成功" +
          (s.no_heading ? "；其中 " + s.no_heading + " 项无标题层级。" : "。");
    }


    var list = Array.isArray(s.degraded) ? s.degraded : [];
    el.degradedBody.textContent = "";
    if (!list.length) {
      el.degradedTable.hidden = true;
      el.degradedEmpty.hidden = false;
      el.degradedEmpty.textContent = cancelled ? "任务已取消，无降级明细。" : "本次运行没有降级项";
      el.degradedBadge.hidden = true;
      el.degradedBadge.textContent = "0";
      el.degradedBadge.classList.add("zero");
      return;
    }

    list.forEach(function (item) {
      var tr = document.createElement("tr");

      var tdFile = document.createElement("td");
      tdFile.className = "file";
      tdFile.textContent = item.name || "—";
      tdFile.title = item.name || "";
      tr.appendChild(tdFile);

      var tdStatus = document.createElement("td");
      var chip = document.createElement("span");
      chip.className = chipClass(item.status || "");
      chip.textContent = shortStatus(item.status || "—");
      chip.title = item.status || "";
      tdStatus.appendChild(chip);
      tr.appendChild(tdStatus);

      var tdNote = document.createElement("td");
      tdNote.textContent = item.note || "—";
      tr.appendChild(tdNote);

      el.degradedBody.appendChild(tr);
    });

    el.degradedTable.hidden = false;
    el.degradedEmpty.hidden = true;
    el.degradedBadge.hidden = false;
    el.degradedBadge.textContent = String(list.length);
    el.degradedBadge.classList.remove("zero");
  }

  /* v0.3.7：「打开合并文档」不再由前端拼路径后丢给通用 /api/open。
     改用专用端点 /api/open-merged：
     ① 后端 os.path.join 拼 MERGED.md 并校验存在，避免混合分隔符；
     ② .md 常无系统关联，os.startfile 抛错时后端回退记事本；
     ③ 结果必须回显给用户，绝不静默吞掉（旧版「点了没反应」的根因）。*/
  function openMerged(outdir) {
    var dir = outdir || lastDoneOutdir || el.outPath.value.trim();
    if (!dir) { showError("请先完成一次提取，再打开合并文档"); return; }
    clearBar();
    api("/api/open-merged", { outdir: dir }, 10000).then(function (r) {
      if (!r || !r.ok) throw new Error((r && r.error) || "打开合并文档失败");
      var via = r.via === "notepad" ? "（已用系统记事本打开）" : "";
      showNotice("已打开合并文档：" + (r.path || "MERGED.md") + via + " · " + nowHMS());
    }).catch(function (err) {
      showError("打开合并文档失败：" + (err.message || String(err)));
    });
  }

  // 启动时 / 改输出目录后探测 MERGED.md 是否已存在：软件重启后 summary 为空，
  // 旧实现会让「打开合并文档」一直灰着，看起来同样像按钮失效。
  function refreshMergedButton() {
    var dir = el.outPath.value.trim();
    if (!dir) {
      lastDoneOutdir = null;
      el.btnOpenMerged.disabled = true;
      return;
    }
    api("/api/merged-status?outdir=" + encodeURIComponent(dir), undefined, 10000)
      .then(function (r) {
        if (r && r.ok && r.exists) {
          lastDoneOutdir = r.outdir || dir;
          el.btnOpenMerged.disabled = false;
        } else {
          lastDoneOutdir = null;
          el.btnOpenMerged.disabled = true;
        }
        updateFeatureButtons();
      }).catch(function () { /* 探测失败保持现状，不误开入口 */ });
  }

  function finish(r) {
    var st = r.state || (summary ? "done" : "failed");
    el.btnCancel.textContent = "取消";
    if (st === "cancelled") {
      setState("cancelled");
      showNotice("任务已取消，产物不完整，已生成的产物保留在输出目录。");
      el.runStatus.textContent = "已取消";
    } else if (st === "failed") {
      setState("failed");
      showError(r.error || "提取失败，请查看运行日志。");
      el.runStatus.textContent = "";
    } else {
      setState("idle");
      setProgress(1);
      el.runStatus.textContent = lastTotal
        ? "处理完成 · " + lastTotal + " / " + lastTotal
        : "处理完成";
    }
    renderSummary(r.summary || summary, st);
    // O5：仅正常完成且拿到产物目录时开放「打开合并文档」入口；
    // 该按钮绝不进 updateControls() 的 ids，产物查看不被 running/previewing 锁住。
    if (st === "done" && summary && summary.outdir) {
      el.btnOpenMerged.disabled = false;
      lastDoneOutdir = summary.outdir;
      updateFeatureButtons();
      // v1.0.8：提取完成即刷新「本次产物」清单，精读页可直接选
      loadArtifacts();
    }
    if (st === "done" && el.optOpenMerged.checked && summary && summary.outdir) {
      openMerged(summary.outdir);
    }
    // 最后一道兜底锁：无论 poll → finish 的链路如何走偏，收尾一定解锁。
    running = false;
    previewing = false;
    if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
    updateControls();
  }

  function doCancel() {
    if (!running) return;
    el.btnCancel.disabled = true;
    el.btnCancel.textContent = "取消中…";
    api("/api/cancel", undefined, 10000).then(function () {
      el.btnCancel.textContent = "取消";
      updateControls();
      // 取消成功后若轮询已停，重启一次，避免「取消成功但前端还锁着」。
      if (!pollTimer) { poll(); }
    }).catch(function (err) {
      showError("取消失败：" + (err.message || err));
      el.btnCancel.textContent = "取消";
      el.btnCancel.disabled = false;
    });
  }

  /* ------------------------------ 阶段 2 / 3 后处理 ------------------------------ */
  // S1：工具健康探测结果。缺工具 / 能力未接入时，按钮必须诚实显示「未启用」。
  var toolState = null;

  function capabilityEnabled(name) {
    return !!(toolState && toolState.capabilities &&
              toolState.capabilities[name] &&
              toolState.capabilities[name].enabled);
  }

  function renderToolStatus() {
    if (!el.toolStatus) return;
    var tools = (toolState && toolState.tools) || {};
    var names = ["ffmpeg", "whisper", "yt-dlp"];
    var parts = names.map(function (n) {
      var t = tools[n] || {};
      return n + " " + (t.available ? "可用" : "未启用") +
             (t.version ? "（" + t.version + "）" : "");
    });
    var cap = (toolState && toolState.capabilities &&
               toolState.capabilities.media_transcribe) || {};
    var why = cap.reason || "本机工具状态未知";
    var at = (toolState && toolState.audio_transcribe) || {};
    var vt = (toolState && toolState.video_transcribe) || {};
    var wi = (toolState && toolState.word_input) || {};
    var lr = (toolState && toolState.link_resolve) || {};
    if (el.linkCap) {
      el.linkCap.textContent = "链接提取：" +
        (lr.enabled ? "已启用（本机 yt-dlp + 复用视频 handler，域名不设限、SSRF 防护）"
                    : "未启用（" + (lr.reason || "缺少本机工具") + "）");
      el.linkCap.hidden = false;
    }
    var legacy = wi.legacy_doc || {};
    el.toolStatus.textContent = "本机工具：" + parts.join(" · ") +
      "；音视频转写：" +
      (capabilityEnabled("media_transcribe") ? "已启用" : "未启用（" + why + "）") +
      "；Word 输入增强：" +
      (wi.enabled ? "已启用（.docx）" : "未启用") +
      "，.doc 旧格式：" +
      (legacy.enabled ? "可用（LibreOffice " + (legacy.tool && legacy.tool.version || "") + "）" : "未启用") +
      "；Word 导出：" +
      ((((toolState || {}).word_export) || {}).enabled ? "已启用（标准库 OOXML）" : "未启用") +
      "；音频转写：" +
      (at.enabled ? "已启用（本机 whisper + ffmpeg）" : "未启用（" + (at.reason || "缺少本机工具") + "）") +
      "；视频提取：" +
      (vt.enabled ? "已启用（独立 video handler）" : "未启用（" + (vt.reason || "缺少本机工具") + "）");
    el.toolStatus.hidden = false;
  }

  function loadTools() {
    api("/api/tools/probe", undefined, 15000).then(function (r) {
      toolState = (r && r.ok) ? r : null;
      renderToolStatus();
      updateFeatureButtons();
      refreshRefineCap();
    }).catch(function () {
      // 探测失败也必须诚实：不能默认当成「可用」而点亮按钮。
      toolState = null;
      renderToolStatus();
      updateFeatureButtons();
      refreshRefineCap();
    });
  }

  // ---------------- S10：设置页「相关组件」（v0.10 支持真并发）----------------
  var componentState = null;
  // v1.0.1：扫描件 OCR（外部工具链，软件绝不自动下载）
  var ocrState = null;
  var componentPoll = null;
  var componentJobs = {};   // cid -> {next, state, percent, message}

  function loadComponents() {
    if (!el.componentList) return;
    // 扫描件 OCR 能力状态（可选增强，仅探测本机工具链，不下载）
    // v1.0.1：改为与其他组件同排列——结果存入 ocrState，由 renderComponents 渲染成一行
    api("/api/pdf/ocr/status", undefined, 10000).then(function (o) {
      ocrState = (o && o.ok) ? o : null;
      renderComponents();
    }).catch(function () {});
    api("/api/components?refresh=1", undefined, 15000).then(function (r) {
      componentState = (r && r.ok) ? r : null;
      renderComponents();
      if ((componentState && componentState.job && componentState.job.running) ||
          anyComponentRunning()) startComponentPolling();
    }).catch(function (err) {
      el.componentList.textContent = "组件状态读取失败：" + (err.message || err);
    });
  }

  function anyComponentRunning() {
    for (var cid in componentJobs) {
      if (componentJobs[cid] && componentJobs[cid].running) return true;
    }
    return false;
  }

  function makeEl(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function renderComponents() {
    if (!el.componentList || !componentState) return;
    var list = componentState.components || [];
    el.componentList.textContent = "";
    list.forEach(function (c) {
      var j = componentJobs[c.id] || {};
      var installing = !!j.running;
      var row = makeEl("div", "component-row" + (c.installed ? "" : " is-missing"));
      row.setAttribute("data-cid", c.id);

      var info = makeEl("div", "component-info");
      info.appendChild(makeEl("span", "component-name", c.name));
      info.appendChild(makeEl("span", "component-desc", c.desc));
      var msg = makeEl("div", "component-msg");
      msg.setAttribute("data-role", "msg");
      if (installing && j.message) msg.textContent = j.message;
      info.appendChild(msg);

      // 绿色进度条：每个组件独立，正在装时显示
      var prog = makeEl("div", "component-progress" + (installing ? " is-active" : ""));
      prog.setAttribute("data-role", "progress");
      var track = makeEl("div", "component-progress-track");
      var bar = makeEl("div", "component-progress-bar");
      bar.setAttribute("data-role", "bar");
      bar.style.width = (installing ? (j.percent || 0) : 0).toFixed(1) + "%";
      track.appendChild(bar);
      var pct = makeEl("span", "component-progress-text",
                       installing ? ((j.percent || 0).toFixed(0) + "%") : "0%");
      pct.setAttribute("data-role", "pct");
      prog.appendChild(track);
      prog.appendChild(pct);
      info.appendChild(prog);

      var compState = c.state || (c.installed ? "ok" : "missing");
      var badgeText = c.installed ? "已安装"
                     : (compState === "timeout" ? "探测超时" : "未安装");
      var badge = makeEl("span", "component-badge" + (c.installed ? "" : " is-off"),
                         installing ? "安装中" : badgeText);
      badge.setAttribute("data-role", "badge");
      if (!c.installed && c.reason) badge.title = c.reason;

      // 只禁用"正在安装的那个"与"已安装的"，其他未装组件保持可点 → 真并发
      var btn = makeEl("button", "btn component-toggle",
                       installing ? "安装中…" : (c.installed ? "已启用" : "启用"));
      btn.type = "button";
      btn.setAttribute("data-role", "toggle");
      btn.setAttribute("data-cid", c.id);
      if (c.installed || installing) btn.disabled = true;

      row.appendChild(info);
      row.appendChild(badge);
      row.appendChild(btn);
      el.componentList.appendChild(row);
    });

    // v1.0.1：扫描件 OCR 与其他组件同排列（三列结构一致）。
    // 它是外部工具链（tesseract + poppler），软件红线「绝不自动下载」，
    // 所以按钮不触发安装，而是弹出清晰的安装指引——诚实，不假装能装。
    if (ocrState) {
      var ocrRow = makeEl("div", "component-row" + (ocrState.available ? "" : " is-missing"));
      ocrRow.setAttribute("data-cid", "ocr");
      var oi = makeEl("div", "component-info");
      oi.appendChild(makeEl("span", "component-name", "扫描件 OCR"));
      oi.appendChild(makeEl("span", "component-desc",
        ocrState.available ? "本机 tesseract + poppler 已就绪，提取时自动识别扫描件图片页"
                           : ("未启用——" + (ocrState.hint || ocrState.reason || "未检测到工具链"))));
      // 与真实组件一致：进度条占位（OCR 无下载进度，恒 0%）
      var op = makeEl("div", "component-progress");
      op.setAttribute("data-role", "progress");
      var ot = makeEl("div", "component-progress-track");
      ot.appendChild(makeEl("div", "component-progress-bar"));
      op.appendChild(ot);
      op.appendChild(makeEl("span", "component-progress-text", "0%"));
      oi.appendChild(op);
      var ob = makeEl("span", "component-badge" + (ocrState.available ? "" : " is-off"),
                      ocrState.available ? "已启用" : "未安装");
      ob.setAttribute("data-role", "badge");
      if (!ocrState.available && ocrState.reason) ob.title = ocrState.reason;
      var obtn = makeEl("button", "btn component-toggle",
                        ocrState.available ? "已启用" : "查看安装指引");
      obtn.type = "button";
      obtn.setAttribute("data-role", "toggle");
      obtn.setAttribute("data-cid", "ocr");
      if (ocrState.available) obtn.disabled = true;
      else obtn.addEventListener("click", function () {
        showNotice("扫描件 OCR 需本机安装 tesseract 与 poppler：软件绝不自动下载，请自行安装后重启软件。");
      });
      ocrRow.appendChild(oi);
      ocrRow.appendChild(ob);
      ocrRow.appendChild(obtn);
      el.componentList.appendChild(ocrRow);
    }
  }

  function rowFor(cid) {
    if (!el.componentList) return null;
    return el.componentList.querySelector('.component-row[data-cid="' + cid + '"]');
  }

  function applyComponentJob(cid, st) {
    var row = rowFor(cid);
    if (!row) return;
    var p = row.querySelector('[data-role="progress"]');
    var bar = row.querySelector('[data-role="bar"]');
    var pct = row.querySelector('[data-role="pct"]');
    var msg = row.querySelector('[data-role="msg"]');
    var badge = row.querySelector('[data-role="badge"]');
    var btn = row.querySelector('[data-role="toggle"]');
    if (p) p.classList.toggle("is-active", !!st.running || st.state === "running");
    if (bar) bar.style.width = Math.max(0, Math.min(100, st.percent || 0)).toFixed(1) + "%";
    if (pct) pct.textContent = (st.percent || 0).toFixed(0) + "%";
    if (msg) msg.textContent = st.message || "";
    if (badge && (st.running || st.state === "running")) badge.textContent = "安装中";
    if (btn && (st.running || st.state === "running")) {
      btn.disabled = true;
      btn.textContent = "安装中…";
    }
  }

  function startComponentPolling() {
    if (componentPoll) return;
    componentPoll = setInterval(function () {
      api("/api/components/status?cid=*", undefined, 10000)
        .then(function (r) {
          if (!r || !r.ok) return;
          var jobs = r.jobs || {};
          var finished = [];
          Object.keys(jobs).forEach(function (cid) {
            var st = jobs[cid];
            componentJobs[cid] = st;
            applyComponentJob(cid, st);
            // 记录完成的任务（由 running -> 非 running），提示一次
            if (!st.running && st.state && st.state !== "idle") {
              if (!componentJobs[cid]._notified) {
                componentJobs[cid]._notified = true;
                finished.push(st);
              }
            } else if (st.running) {
              componentJobs[cid]._notified = false;
            }
          });
          if (finished.length) {
            finished.forEach(function (st) {
              if (st.state === "done") showNotice("组件安装成功：" + (st.id || ""));
              else if (st.state === "failed") showError("组件安装失败：" + (st.error || "未知原因"));
              else if (st.state === "cancelled") showNotice("已取消组件安装：" + (st.id || ""));
            });
            loadTools();
          }
          if (!r.running) {
            stopComponentPolling();
            loadComponents();
          }
        })
        .catch(function () { /* 轮询偶发失败下一次重试，不打断安装 */ });
    }, 500);
  }

  function stopComponentPolling() {
    if (componentPoll) { clearInterval(componentPoll); componentPoll = null; }
  }

  function enableComponent(cid) {
    api("/api/components/install", { id: cid }, 15000).then(function (r) {
      if (!r || !r.ok) { showError("启动安装失败：" + ((r && r.error) || "未知")); return; }
      if (r.already_installed) { showNotice("该组件已安装。"); loadComponents(); return; }
      componentJobs[cid] = { running: true, state: "running", percent: 0, _notified: false };
      renderComponents();
      startComponentPolling();
    }).catch(function (err) { showError("启动安装失败：" + (err.message || err)); });
  }

  function bindComponentEvents() {
    if (!el.componentList) return;
    el.componentList.addEventListener("click", function (e) {
      var btn = e.target && e.target.closest ? e.target.closest('[data-role="toggle"]') : null;
      if (!btn || btn.disabled) return;
      enableComponent(btn.getAttribute("data-cid"));
    });
  }

  // ---------------- S7d：精读 / 修订 ----------------
  var refinePolling = null;
  var refineSince = 0;

  function setBar(node, text, ok) {
    if (!node) return;
    node.textContent = text;
    node.classList.toggle("bar-ok", !!ok);
    node.classList.toggle("bar-warn", !ok);
    node.hidden = false;
  }

  function refineCapability() {
    return ((toolState || {}).refine) || null;
  }

  function refreshRefineCap() {
    var cap = refineCapability();
    var enabled = !!(cap && cap.enabled);
    var reason = (cap && cap.reason) || "尚未探测到精读后端";
    setBar(el.refineCap, enabled ? "精读后端：已启用" : "精读后端：未启用（" + reason + "）", enabled);
    setBar(el.reviseCap, enabled ? "精读后端：已启用" : "精读后端：未启用（" + reason + "）", enabled);
    if (el.btnStartRefine) el.btnStartRefine.disabled = !enabled;
    if (el.btnStartRevise) el.btnStartRevise.disabled = !enabled;
    if (enabled) loadRefineModels();
  }

  function loadRefineModels() {
    api("/api/refine/models", undefined, 15000).then(function (r) {
      if (!el.refineModel) return;
      el.refineModel.innerHTML = "";
      var models = (r && Array.isArray(r.models)) ? r.models : [];
      if (!models.length) {
        var o = document.createElement("option");
        o.value = "";
        o.textContent = (r && r.note) ? r.note : "（用后端默认模型）";
        el.refineModel.appendChild(o);
        return;
      }
      models.forEach(function (m) {
        var opt = document.createElement("option");
        opt.value = m; opt.textContent = m;
        el.refineModel.appendChild(opt);
      });
    }).catch(function () {
      if (el.refineModel) {
        el.refineModel.innerHTML = "";
        var o = document.createElement("option");
        o.value = ""; o.textContent = "（无法读取模型列表）";
        el.refineModel.appendChild(o);
      }
    });
  }

  function loadBackendForm() {
    api("/api/refine/backend", undefined, 10000).then(function (r) {
      var cfg = (r && r.config) || {};
      if (el.beMode) el.beMode.value = cfg.mode || "extract";
      if (el.beKind) el.beKind.value = cfg.kind || "none";
      if (el.beEndpoint) el.beEndpoint.value = cfg.endpoint || "";
      if (el.beApiKey) el.beApiKey.value = cfg.api_key || "";  // 掩码，真 key 不回显
      if (el.beModel) el.beModel.value = cfg.model || "";
      if (el.beRounds) el.beRounds.value = String(cfg.refine_rounds || 1);
      if (el.beAllowSupplement) el.beAllowSupplement.checked = !!cfg.allow_suppplement;
      applyBackendMode();
    }).catch(function () {
      if (el.backendStatus) el.backendStatus.textContent = "读取后端配置失败";
    });
  }

  // S8：抽取式模式无需端点/密钥/模型；把这些字段置灰并给出说明，避免误填
  function applyBackendMode() {
    var mode = (el.beMode && el.beMode.value) || "extract";
    var llm = (mode === "llm");
    var fields = [el.beKind, el.beEndpoint, el.beApiKey, el.beModel];
    for (var i = 0; i < fields.length; i += 1) {
      if (fields[i]) fields[i].disabled = !llm;
    }
    // S11：迭代轮数只对「可信提纯」生效，LLM 模式置灰并给出说明
    if (el.beRounds) el.beRounds.disabled = llm;
    var roundsRow = document.getElementById("beRoundsRow");
    if (roundsRow) roundsRow.hidden = llm;
    var tip = document.getElementById("beLlmHint");
    if (tip) tip.hidden = llm;
    // 精读 / 修订页按模式联动：
    // extract 模式无模型概念、无补写（补写只在 llm 模式且开关开启时才有）
    if (el.refineModel) el.refineModel.disabled = !llm;
    if (el.reviseInstruction) el.reviseInstruction.disabled = !llm;
    var rsub = document.getElementById("refineSub");
    if (rsub) {
      rsub.innerHTML = llm
        ? "对已转换为 md 的文件做语义级提纯（由大模型完成，输出可能偏离原文，请核对）。"
        : "对已转换为 md 的文件提纯核心知识点。默认「可信提纯」用内置抽取式引擎，"
          + "核心为<strong>原文原句、可逐字回溯</strong>，零依赖离线运行。";
    }
    var vsub = document.getElementById("reviseSub");
    if (vsub) {
      vsub.innerHTML = llm
        ? "对已提炼的核心做加工。补写（原文没有的内容）需在设置里开启「允许补写」；"
          + "新增与修改内容均以颜色/标记区分，请对照原文核对。"
        : "对已提炼的核心做加工。默认「可信提纯」模式下只做<strong>原文内改写</strong>"
          + "（术语归一 / 合并去重 / 结构重排），不动事实。";
    }
  }

  function saveBackendCfg(thenProbe) {
    // 密钥回填的是掩码（如 ****3456），不是真 key。若原样提交，
    // 后端会把掩码当成新 key 写入、真 key 被永久覆盖（云端后端从此全 401）。
    // 这里主动把「看起来是掩码」的值转成空串，交由后端「空值=不改」语义处理；
    // 后端另有「掩码值=未修改」的兜底，两道防线互不依赖。
    var keyVal = (el.beApiKey && el.beApiKey.value || "").trim();
    if (/^\*{4}/.test(keyVal)) keyVal = "";
    var payload = {
      kind: (el.beKind && el.beKind.value) || "none",
      mode: (el.beMode && el.beMode.value) || "extract",
      endpoint: (el.beEndpoint && el.beEndpoint.value || "").trim(),
      api_key: keyVal,
      model: (el.beModel && el.beModel.value || "").trim(),
      allow_suppplement: !!(el.beAllowSupplement && el.beAllowSupplement.checked),
      refine_rounds: (el.beRounds && el.beRounds.value) || "1"
    };
    if (el.backendStatus) el.backendStatus.textContent = "保存中…";
    api("/api/refine/backend", payload, 10000).then(function (r) {
      if (!r || !r.ok) {
        if (el.backendStatus) el.backendStatus.textContent = "保存失败：" + ((r && r.error) || "未知");
        return;
      }
      // 回显是掩码；把输入框也刷成掩码，避免用户以为真 key 被清空
      if (el.beApiKey && r.config) el.beApiKey.value = r.config.api_key || "";
      if (el.beAllowSupplement && r.config) {
        el.beAllowSupplement.checked = !!r.config.allow_suppplement;
      }
      if (el.beRounds && r.config) {
        el.beRounds.value = String(r.config.refine_rounds || 1);
      }
      if (el.backendStatus) el.backendStatus.textContent = "已保存";
      if (thenProbe) {
        api("/api/tools/probe", { refresh: true }, 15000).then(function (p) {
          toolState = (p && p.ok) ? p : null;
          refreshRefineCap();
          var cap = refineCapability();
          setBar(el.backendStatus, cap && cap.enabled ? "连接成功：后端可用" : ("连接失败：" + (cap && cap.reason || "不可用")), !!(cap && cap.enabled));
        }).catch(function () {
          if (el.backendStatus) el.backendStatus.textContent = "连接探测失败";
        });
      }
    }).catch(function (err) {
      if (el.backendStatus) el.backendStatus.textContent = "保存失败：" + (err.message || err);
    });
  }

  function renderRefineEvents(events) {
    events.forEach(function (ev) {
      if (el.refineProgress) el.refineProgress.textContent = ev.text || "";
    });
  }

  function stopRefinePolling() {
    if (refinePolling) { clearInterval(refinePolling); refinePolling = null; }
    if (el.btnCancelRefine) el.btnCancelRefine.disabled = true;
    if (el.btnStartRefine) el.btnStartRefine.disabled = false;
    if (el.btnStartRevise) el.btnStartRevise.disabled = false;
  }

  function startRefinePolling(isRevise) {
    refineSince = 0;
    if (refinePolling) clearInterval(refinePolling);
    if (el.btnCancelRefine) el.btnCancelRefine.disabled = false;
    refinePolling = setInterval(function () {
      api("/api/refine/status?since=" + refineSince, undefined, 8000).then(function (st) {
        if (!st) return;
        renderRefineEvents(st.events || []);
        if (typeof st.next === "number") refineSince = st.next;
        if (!st.running) {
          stopRefinePolling();
          if (st.state === "done") {
            loadRefineResult(isRevise, st.output || "");
          } else if (st.error) {
            showError("任务失败：" + st.error);
          }
        }
      }).catch(function () { /* 轮询偶发失败不打断，下轮重试 */ });
    }, 500);
  }

  function loadRefineResult(isRevise, output) {
    if (isRevise) {
      // 修订：彩色 html 内嵌预览（经只读端点取文本 + srcdoc，sandbox 隔离）+ 符号标记 md
      if (el.reviseResult && output) {
        var htmlPath = output.replace(/\.revise\.md$/, ".revise.html");
        el.reviseResult.dataset.html = htmlPath;
        api("/api/refine/artifact?path=" + encodeURIComponent(htmlPath), undefined, 8000)
          .then(function (r) {
            if (el.revisePreviewHtml && r && r.ok) {
              // v1.0.2：注入滚动上报脚本——sandbox 只给 allow-scripts，
              // 用 postMessage 把滚动比例传出，不触碰父页面 DOM（仍隔离）
              var scrollProbe = '<script>(function(){' +
                'var d=document.documentElement,b=document.body;' +
                'function ratio(){var max=(d.scrollHeight||b.scrollHeight)-(window.innerHeight||0);' +
                'return max>0?Math.min(1,Math.max(0,window.scrollY/max)):0;}' +
                'window.addEventListener("scroll",function(){' +
                'parent.postMessage({type:"jinghe-scroll",ratio:ratio()},"*");},{passive:true});' +
                'window.addEventListener("message",function(e){' +
                'var d2=e.data;if(!d2||d2.type!=="jinghe-scroll-to")return;' +
                'var max=(d.scrollHeight||b.scrollHeight)-(window.innerHeight||0);' +
                'window.scrollTo(0,max*d2.ratio);});' +
                '})();<\/script>';
              el.revisePreviewHtml.srcdoc = r.text + scrollProbe;
            }
          }).catch(function () { /* 预览失败不影响产物本身 */ });
      }
      if (output && el.revisePreviewMd) {
        api("/api/refine/artifact?path=" + encodeURIComponent(output), undefined, 8000)
          .then(function (r) {
            el.revisePreviewMd.textContent = (r && r.ok) ? r.text : "（无法读取 md 预览，请打开产物查看）";
          }).catch(function () { el.revisePreviewMd.textContent = "（无法读取 md 预览）"; });
      }
      if (el.reviseResult) el.reviseResult.hidden = false;
    } else {
      if (el.refineResultPath) el.refineResultPath.textContent = output || "";
      if (el.refineResult && output) {
        api("/api/refine/artifact?path=" + encodeURIComponent(output), undefined, 8000)
          .then(function (r) {
            if (el.refinePreview) el.refinePreview.textContent = (r && r.ok) ? r.text : "（无法读取预览，请打开产物查看）";
          }).catch(function () { if (el.refinePreview) el.refinePreview.textContent = "（无法读取预览）"; });
        el.refineResult.dataset.path = output;
        el.refineResult.hidden = false;
      }
    }
  }

  function pickRefineSource(isRevise) {
    api("/api/pick-files", { initial: "" }, 0).then(function (r) {
      if (r && r.error) { showError(r.error); return; }
      var paths = (r && Array.isArray(r.paths)) ? r.paths : [];
      if (!paths.length) return;
      var node = isRevise ? el.reviseSource : el.refineSource;
      if (node) node.value = paths[0];
    }).catch(function (err) { showError(err.message || err); });
  }

  // S2a：只要选择了 Word 文件就能用；没跑提取也可以（产物落独立 derived 区）。
  function hasWordInput() {
    var list = currentInputs();
    if (!list.length) {
      var v = (el.inputPath && el.inputPath.value || "").trim();
      if (v) list = [v];
    }
    for (var i = 0; i < list.length; i += 1) {
      if (/\.(docx|doc)$/i.test(list[i])) return true;
    }
    return false;
  }

  // S3：只认注册表里的音频后缀；扩展名列表与后端 MEDIA_AUDIO 保持一致。
  var AUDIO_EXT_RE = /\.(mp3|wav|m4a|aac|flac|ogg|wma|amr)$/i;
  function hasAudioInput() {
    var list = currentInputs();
    if (!list.length) {
      var v = (el.inputPath && el.inputPath.value || "").trim();
      if (v) list = [v];
    }
    for (var i = 0; i < list.length; i += 1) {
      if (AUDIO_EXT_RE.test(list[i])) return true;
    }
    return false;
  }

  // S4：只认注册表里的视频后缀；扩展名列表与后端 MEDIA_VIDEO 保持一致。
  var VIDEO_EXT_RE = /\.(mp4|mov|avi|mkv|flv|webm|m4v|wmv)$/i;
  function hasVideoInput() {
    var list = currentInputs();
    if (!list.length) {
      var v = (el.inputPath && el.inputPath.value || "").trim();
      if (v) list = [v];
    }
    for (var i = 0; i < list.length; i += 1) {
      if (VIDEO_EXT_RE.test(list[i])) return true;
    }
    return false;
  }

  // 仅在「本次运行成功且有产物目录」时点亮后处理按钮；运行/预览中不点亮。
  function updateFeatureButtons() {
    var on = !!lastDoneOutdir && !running && !previewing;
    var mediaOn = capabilityEnabled("media_transcribe");
    el.btnSummarize.disabled = !on;
    // S2b：纯标准库导出恒可用；只需有输出目录（后端会自动只读收集 MERGED.md）。
    var we = ((toolState || {}).word_export) || {};
    var exportOn = !!we.enabled;
    var outReady = !!(lastDoneOutdir || (el.outPath && el.outPath.value || "").trim());
    el.btnExportDocx.disabled = !(exportOn && outReady && !running && !previewing);
    el.btnExportDocx.textContent = exportOn ? "导出 Word" : "导出 Word（未启用）";
    var wi = (toolState && toolState.word_input) || {};
    var wordOn = !!wi.enabled;
    el.btnWordEnhance.disabled = !(!running && !previewing && wordOn &&
                                   (hasWordInput() || on));
    el.btnWordEnhance.textContent = wordOn ? "Word 输入增强" : "Word 输入增强（未启用）";
    // S3：真实能力走 /api/tools/probe 顶层 audio_transcribe；缺工具恒禁用并显示「未启用」。
    var at = ((toolState || {}).audio_transcribe) || {};
    var audioOn = !!at.enabled;
    var audioOut = !!(lastDoneOutdir || (el.outPath && el.outPath.value || "").trim());
    el.btnAudioTranscribe.disabled = !(!running && !previewing && audioOn &&
                                       hasAudioInput() && audioOut);
    el.btnAudioTranscribe.textContent = audioOn ? "音频转写 → .md" : "音频转写（未启用）";
    // S4：真实能力走顶层 video_transcribe；与音频按钮各走一条独立端点。
    var vt = ((toolState || {}).video_transcribe) || {};
    var videoOn = !!vt.enabled;
    el.btnVideoTranscribe.disabled = !(!running && !previewing && videoOn &&
                                       hasVideoInput() && audioOut);
    el.btnVideoTranscribe.textContent = videoOn ? "视频提取 → .md" : "视频提取（未启用）";
    // S5：链接提取——能力走顶层 link_resolve；需有链接与输出目录。
    var lr = ((toolState || {}).link_resolve) || {};
    var linkOn = !!lr.enabled;
    var hasLinks = !!(el.linkUrls && el.linkUrls.value.trim());
    if (el.btnLinkRun) {
      el.btnLinkRun.disabled = !(!running && !previewing && linkOn && hasLinks && audioOut);
      el.btnLinkRun.textContent = linkOn ? "链接提取 → .md" : "链接提取（未启用）";
    }
    if (el.btnLinkInspect) el.btnLinkInspect.disabled = !(linkOn && hasLinks);
  }

  // 统一的后端动作：调用 /api/*，成功给带时间戳的常驻文案，失败显式报错。
  // 复用 api() 的 AbortController 超时与 .finally 复位机制（与预览同构）。
  function callFeature(path, body, btn, doingLabel) {
    if (running || previewing) { showNotice("正在处理，请稍候…"); return; }
    var old = btn.textContent;
    btn.disabled = true;
    btn.textContent = doingLabel;
    clearBar();
    api(path, body, 30000).then(function (r) {
      if (!r.ok) throw new Error(r.error || (path + " 失败"));
      var msg = r.path ? "已生成：" + r.path : "完成";
      if (r.chars) msg += "（" + r.chars + " 字）";
      if (r.bytes) msg += "（" + Math.round((r.bytes || 0) / 1024) + " KB）";
      showNotice(msg + " · " + nowHMS());
    }).catch(function (err) {
      showError(err.message || String(err));
    }).finally(function () {
      btn.textContent = old;
      updateFeatureButtons();
    });
  }

  function doSummarize() {
    var outdir = (summary && summary.outdir) || el.outPath.value.trim();
    if (!outdir) { showError("请先完成提取以生成输出目录"); return; }
    callFeature("/api/summarize", { outdir: outdir }, el.btnSummarize, "提炼中…");
  }

  // ------------------------------------------------------------------ //
  // v1.0.2 修订预览同步滚动：勾选后彩色版 iframe 与符号标记版 pre 同比例滚动。
  // iframe 是 sandbox=allow-scripts（不放行 same-origin），靠 postMessage 通信。
  // ------------------------------------------------------------------ //
  var reviseSyncOn = false;
  var reviseSyncBusy = false;

  function reviseScrollPre() {
    var pre = el.revisePreviewMdEl;
    if (!reviseSyncOn || reviseSyncBusy || !pre) return;
    var max = pre.scrollHeight - pre.clientHeight;
    if (max <= 0) return;
    reviseSyncBusy = true;
    var ratio = Math.min(1, Math.max(0, pre.scrollTop / max));
    if (el.revisePreviewHtml && el.revisePreviewHtml.contentWindow) {
      el.revisePreviewHtml.contentWindow.postMessage(
        { type: "jinghe-scroll-to", ratio: ratio }, "*");
    }
    setTimeout(function () { reviseSyncBusy = false; }, 80);
  }

  window.addEventListener("message", function (e) {
    var d = e.data;
    if (!reviseSyncOn || reviseSyncBusy || !d || d.type !== "jinghe-scroll") return;
    var pre = el.revisePreviewMdEl;
    if (!pre) return;
    var max = pre.scrollHeight - pre.clientHeight;
    if (max <= 0) return;
    reviseSyncBusy = true;
    pre.scrollTop = max * Math.min(1, Math.max(0, d.ratio || 0));
    setTimeout(function () { reviseSyncBusy = false; }, 80);
  });

  // ------------------------------------------------------------------ //
  // v1.0.8（T3 接线）：本次产物清单——精读/修订不必手填路径。
  // 阶段 1 产物名是 NNN-<stem>.md 序号名，序号会随批次漂移，
  // 手填既费事又可能指向别的文件，故由后端给出当前批次的真实清单。
  // ------------------------------------------------------------------ //
  function currentOutdir() {
    return (lastDoneOutdir || (el.outPath && el.outPath.value) || "").trim();
  }

  function loadArtifacts() {
    if (!el.refineArtifactSel) return;
    var sel = el.refineArtifactSel;
    var dir = currentOutdir();
    if (!dir) {
      sel.innerHTML = '<option value="">（先在首页完成一次提取）</option>';
      return;
    }
    api("/api/artifacts?outdir=" + encodeURIComponent(dir), undefined, 15000)
      .then(function (r) {
        sel.innerHTML = "";
        if (!r || !r.ok) {
          var o = document.createElement("option");
          o.value = ""; o.textContent = "（读取失败：" + ((r && r.error) || "未知") + "）";
          sel.appendChild(o);
          return;
        }
        var md = r.md || [], dv = r.derived || [];
        if (!md.length && !dv.length) {
          var o2 = document.createElement("option");
          o2.value = ""; o2.textContent = "（本次尚无产物）";
          sel.appendChild(o2);
          return;
        }
        if (md.length) {
          var g1 = document.createElement("optgroup");
          g1.label = "阶段 1 提取产物（md）";
          md.forEach(function (f) {
            var op = document.createElement("option");
            op.value = f.path; op.textContent = f.name;
            g1.appendChild(op);
          });
          sel.appendChild(g1);
        }
        if (dv.length) {
          var g2 = document.createElement("optgroup");
          g2.label = "后处理产物（derived）";
          dv.forEach(function (f) {
            var op = document.createElement("option");
            op.value = f.path; op.textContent = f.name;
            g2.appendChild(op);
          });
          sel.appendChild(g2);
        }
        // 与输入框当前值保持一致
        if (el.refineSource && el.refineSource.value) {
          sel.value = el.refineSource.value;
        }
      }).catch(function () {
        sel.innerHTML = '<option value="">（读取失败）</option>';
      });
  }

  // v1.0.8（T3 接线）：精读完成 → 一键送往修订（自动填路径并切页）
  function sendRefineToRevise() {
    var path = (el.refineResult && el.refineResult.dataset.path) || "";
    if (!path) { showError("还没有精读产物可发送。"); return; }
    if (el.reviseSource) el.reviseSource.value = path;
    var btn = el.btnSendToRevise;
    if (btn) btn.disabled = true;
    try {
      activatePage("revise");
      showNotice("已把精读产物带到修订页，可直接点「开始修订」。");
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  function bindArtifacts() {
    if (el.refineArtifactSel) {
      el.refineArtifactSel.addEventListener("change", function () {
        if (el.refineArtifactSel.value && el.refineSource) {
          el.refineSource.value = el.refineArtifactSel.value;
        }
      });
    }
    if (el.btnReloadArtifacts) {
      el.btnReloadArtifacts.addEventListener("click", loadArtifacts);
    }
    if (el.btnSendToRevise) {
      el.btnSendToRevise.addEventListener("click", sendRefineToRevise);
    }
  }

  function bindReviseSync() {
    if (el.reviseSyncCheck) {
      el.reviseSyncCheck.addEventListener("change", function () {
        reviseSyncOn = !!el.reviseSyncCheck.checked;
      });
    }
    if (el.revisePreviewMdEl) {
      el.revisePreviewMdEl.addEventListener("scroll", reviseScrollPre, { passive: true });
    }
  }

  // ------------------------------------------------------------------ //
  // v1.1.0 知识库：S9 后端 /api/kb/status|ingest|query|open-source 早已实现，
  // 此前首页按钮只弹「规划中」。这里接上真实端点（GET 务必传 undefined）。
  // ------------------------------------------------------------------ //
  function loadKbStatus() {
    if (!el.kbStats) return;
    api("/api/kb/status", undefined, 10000).then(function (r) {
      if (!r || !r.ok) { el.kbStats.textContent = "知识库状态读取失败"; return; }
      if (!r.initialized) {
        el.kbStats.textContent = "尚未初始化：入库一次产物后即可检索";
      } else {
        el.kbStats.textContent = "已入库 " + r.entries + " 条 · " +
          (r.fts ? "全文检索已启用" : "基础检索") +
          (r.created_at ? " · 建于 " + new Date(r.created_at * 1000).toLocaleString() : "");
      }
      if (el.btnKbQuery) el.btnKbQuery.disabled = !r.initialized;
    }).catch(function () { el.kbStats.textContent = "知识库状态读取失败"; });
  }

  // ------------------------------------------------------------------ //
  // S12a：订阅博主 / 频道
  // ------------------------------------------------------------------ //
  function escHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function loadSubSchedStatus() {
    api("/api/sub/scheduler", undefined, 10000).then(function (r) {
      if (!el.subSchedHint) return;
      var s = (r && r.scheduler) || {};
      if (s.running) {
        el.subSchedHint.textContent = "后台同步已开启：每 " +
          Math.round((s.tick || 60)) + " 秒检查一次，已自动触发 " +
          (s.triggers || 0) + " 次" +
          (s.last_error ? "（最近错误：" + s.last_error.slice(0, 50) + "）" : "");
        el.subSchedHint.className = "bar bar-ok";
      } else {
        el.subSchedHint.textContent = "后台同步未运行";
        el.subSchedHint.className = "bar bar-warn";
      }
    }).catch(function () {
      if (el.subSchedHint) el.subSchedHint.textContent = "后台调度状态读取失败";
    });
  }

  function loadSubList() {
    loadSubSchedStatus();
    api("/api/sub/list", undefined, 10000).then(function (r) {
      if (!r || !r.ok) {
        if (el.subList) el.subList.textContent = "订阅列表读取失败";
        return;
      }
      var cap = r.capability || {};
      if (el.subCapHint) {
        el.subCapHint.hidden = !!cap.enabled;
        el.subCapHint.textContent = cap.enabled ? "" : (cap.reason || "订阅依赖 yt-dlp");
        el.subCapHint.className = "bar bar-warn";
      }
      var subs = r.subscriptions || [];
      if (!el.subList) return;
      if (!subs.length) {
        el.subList.textContent = "尚未添加订阅。粘贴博主主页或频道链接即可开始。";
        return;
      }
      var html = "";
      for (var i = 0; i < subs.length; i += 1) {
        var s = subs[i];
        var badges = [];
        badges.push(s.enabled ? "已启用" : "已停用");
        if (s.due) badges.push("待同步");
        if (s.last_status === "failed") badges.push("上次失败");
        if (s.last_status === "ok") badges.push("正常");
        var detail = "已处理 " + (s.seen_ids ? s.seen_ids.length : 0) + " 个视频" +
          (s.last_new ? " · 上次新增 " + s.last_new : "") +
          (s.last_error ? " · " + s.last_error.slice(0, 60) : "");
        html += '<div class="kb-hit">' +
          '<div><strong>' + escHtml(s.name || s.url) + '</strong> ' +
          '<span class="badge">' + escHtml(badges.join(" / ")) + '</span></div>' +
          '<div class="hint">' + escHtml(detail) + '</div>' +
          '<div class="row">' +
          '<button class="btn btn-ghost" type="button" data-sub-sync="' + escHtml(s.id) + '">立即同步</button>' +
          '<button class="btn btn-ghost" type="button" data-sub-toggle="' + escHtml(s.id) + '" data-on="' + (s.enabled ? "0" : "1") + '">' + (s.enabled ? "停用" : "启用") + '</button>' +
          '<button class="btn btn-ghost" type="button" data-sub-del="' + escHtml(s.id) + '">删除</button>' +
          '</div></div>';
      }
      el.subList.innerHTML = html;
    }).catch(function () {
      if (el.subList) el.subList.textContent = "订阅列表读取失败";
    });
  }

  function doSubAdd() {
    var url = (el.subUrl && el.subUrl.value || "").trim();
    if (!url) { showError("请先粘贴频道 / 博主主页链接"); return; }
    var payload = {
      url: url,
      name: (el.subName && el.subName.value || "").trim(),
      cookie_file: (el.subCookie && el.subCookie.value || "").trim(),
      interval_hours: (el.subInterval && el.subInterval.value) || "24"
    };
    api("/api/sub/add", payload, 10000).then(function (r) {
      if (!r || !r.ok) { showError("添加订阅失败：" + ((r && r.error) || "未知")); return; }
      showNotice("订阅已添加，可点「立即同步」拉取首批内容");
      if (el.subUrl) el.subUrl.value = "";
      if (el.subName) el.subName.value = "";
      loadSubList();
    }).catch(function (err) { showError("添加订阅失败：" + err.message); });
  }

  function doSubSync(ids) {
    var list = ids || [];
    api("/api/sub/run-now", { ids: list }, 15000).then(function (r) {
      if (!r || !r.ok) { showError("启动同步失败：" + ((r && r.error) || "未知")); return; }
      if (el.subStatus) el.subStatus.textContent = "同步中…";
      pollSubStatus();
    }).catch(function (err) { showError("启动同步失败：" + err.message); });
  }

  var subPolling = false;
  function pollSubStatus() {
    if (subPolling) return;
    subPolling = true;
    api("/api/sub/status", undefined, 10000).then(function (r) {
      var running = !!(r && r.running);
      if (el.subStatus) el.subStatus.textContent = running ? "同步中…" : "";
      if (r && r.events && r.events.length && el.subEvents) {
        el.subEvents.hidden = false;
        el.subEvents.textContent = r.events.map(function (e) { return e.text; }).join(" ｜ ");
      }
      if (r && !running && r.state && r.state !== "idle") {
        showNotice("订阅同步结束：" + r.state + (r.error ? "（" + r.error + "）" : ""));
        loadSubList();
      }
      if (running) { setTimeout(pollSubStatus, 1000); }
      else { subPolling = false; }
    }).catch(function () { subPolling = false; });
  }

  function doKbIngest() {
    var dir = (lastDoneOutdir || (el.outPath && el.outPath.value) || "").trim();
    if (!dir) { showError("请先完成一次提取，或填写输出目录"); return; }
    var btn = el.btnKbIngest;
    if (btn) { btn.disabled = true; btn.textContent = "入库中…"; }
    if (el.kbStatus) el.kbStatus.textContent = "正在入库…";
    api("/api/kb/ingest", { dir: dir }, 120000).then(function (r) {
      if (el.kbStatus) el.kbStatus.textContent = "";
      if (!r || !r.ok) { showError("入库失败：" + ((r && r.error) || "未知错误")); return; }
      showNotice("入库完成：扫描 " + r.files + " 个 md，新增 " + r.added +
                 " 条，重复 " + (r.duplicate || 0) + " 条" +
                 (r.skipped_ai ? "，跳过 AI 补写 " + r.skipped_ai + " 条" : ""));
      loadKbStatus();
    }).catch(function (err) {
      if (el.kbStatus) el.kbStatus.textContent = "";
      showError("入库失败：" + (err.message || err));
    }).finally(function () {
      if (btn) { btn.textContent = "入库当前产物"; btn.disabled = false; }
    });
  }

  function doKbQuery() {
    var q = (el.kbQuery && el.kbQuery.value || "").trim();
    if (!q) { showError("请输入检索关键词"); return; }
    if (!el.kbResults) return;
    el.kbResults.textContent = "检索中…";
    api("/api/kb/query", { q: q }, 30000).then(function (r) {
      if (!r || !r.ok) { el.kbResults.textContent = "检索失败：" + ((r && r.error) || "未知错误"); return; }
      if (!r.results || !r.results.length) { el.kbResults.textContent = "没有匹配的知识条目。"; return; }
      el.kbResults.textContent = "";
      el.kbResults.dataset.results = JSON.stringify(r.results);
      var head = document.createElement("div");
      head.textContent = "找到 " + r.count + " 条（模式：" + (r.mode || "—") + "）：";
      el.kbResults.appendChild(head);
      r.results.forEach(function (item) {
        var row = document.createElement("div");
        row.className = "kb-hit";
        row.appendChild(document.createTextNode(
          "[" + item.block + "] " + (item.locator || item.doc_id) +
          " — " + (item.snippet || "").replace(/\s+/g, " ") + " "));
        // S9：回跳原文位置（后端只解析坐标、不执行打开；路径围栏）
        var jump = document.createElement("button");
        jump.className = "link-btn";
        jump.type = "button";
        jump.textContent = "回跳原文";
        jump.addEventListener("click", function () {
          api("/api/kb/open-source", { id: item.id }, 10000).then(function (j) {
            if (!j || !j.ok) { showError("回跳失败：" + ((j && j.error) || "未知错误")); return; }
            showNotice("原文位置：" + (j.locator || j.source_file || "已定位"));
          }).catch(function (err) { showError("回跳失败：" + (err.message || err)); });
        });
        row.appendChild(jump);
        el.kbResults.appendChild(row);
      });
    }).catch(function (err) { el.kbResults.textContent = "检索失败：" + (err.message || err); });
  }

  function bindKbEvents() {
    if (el.btnKbRefresh) el.btnKbRefresh.addEventListener("click", loadKbStatus);
    if (el.btnKbIngest) el.btnKbIngest.addEventListener("click", doKbIngest);
    // S12a：订阅博主/频道
    if (el.btnSubAdd) el.btnSubAdd.addEventListener("click", doSubAdd);
    if (el.btnSubRefresh) el.btnSubRefresh.addEventListener("click", loadSubList);
    if (el.btnSubSyncAll) el.btnSubSyncAll.addEventListener("click", function () { doSubSync([]); });
    if (el.btnSubCancel) el.btnSubCancel.addEventListener("click", function () {
      api("/api/sub/cancel", {}, 10000).then(function () {
        if (el.subStatus) el.subStatus.textContent = "正在取消…";
      });
    });
    // 订阅列表内的行内按钮（事件委托）
    if (el.subList) el.subList.addEventListener("click", function (ev) {
      var t = ev.target;
      if (!t || !t.getAttribute) return;
      var syncId = t.getAttribute("data-sub-sync");
      var delId = t.getAttribute("data-sub-del");
      var toggleId = t.getAttribute("data-sub-toggle");
      if (syncId) { doSubSync([syncId]); return; }
      if (delId) {
        api("/api/sub/remove", { id: delId }, 10000).then(function (r) {
          if (!r || !r.ok) { showError("删除失败：" + ((r && r.error) || "未知")); return; }
          showNotice("订阅已删除"); loadSubList();
        });
        return;
      }
      if (toggleId) {
        api("/api/sub/enabled", { id: toggleId, enabled: t.getAttribute("data-on") === "1" }, 10000)
          .then(function (r) {
            if (!r || !r.ok) { showError("操作失败：" + ((r && r.error) || "未知")); return; }
            loadSubList();
          });
      }
    });
    if (el.btnKbQuery) el.btnKbQuery.addEventListener("click", doKbQuery);
    if (el.kbQuery) el.kbQuery.addEventListener("keydown", function (e) {
      if (e.key === "Enter") { e.preventDefault(); doKbQuery(); }
    });
  }

  // S2a：逐条回显成功 / 失败原因，绝不把「部分成功」说成「全部完成」。
  function doWordEnhance() {
    var inputs = currentInputs();
    if (!inputs.length) {
      var v = el.inputPath.value.trim();
      if (v) inputs = [v];
    }
    inputs = inputs.filter(function (p) { return /\.(docx|doc)$/i.test(p); });
    if (!inputs.length) { showError("请先选择 .docx / .doc 文件"); return; }
    var outdir = (summary && summary.outdir) || lastDoneOutdir ||
                 el.outPath.value.trim();
    if (!outdir) { showError("请先指定输出目录"); return; }
    if (running || previewing) { showNotice("正在处理，请稍候…"); return; }
    var btn = el.btnWordEnhance;
    var old = btn.textContent;
    btn.disabled = true;
    btn.textContent = "解析中…";
    clearBar();
    api("/api/word/enhance", { inputs: inputs, outdir: outdir }, 120000)
      .then(function (r) {
        if (!r.ok) {
          var detail = (r.results || []).filter(function (x) { return !x.ok; })
            .map(function (x) { return x.name + "：" + x.error; }).join("；");
          throw new Error((r.error || "Word 输入增强失败") +
                          (detail ? "（" + detail + "）" : ""));
        }
        var msg = "已生成 " + r.success + " 份增强 .md：" + r.derived_dir;
        if (r.failed) msg += "；另有 " + r.failed + " 项未处理（见产物清单）";
        showNotice(msg + " · " + nowHMS());
      }).catch(function (err) {
        showError(err.message || String(err));
      }).finally(function () {
        btn.textContent = old;
        updateFeatureButtons();
      });
  }

  // S2b：把 MERGED.md / 所选 .md 导出为独立 .docx，逐条回显失败原因。
  function doWordExport() {
    var inputs = currentInputs().filter(function (p) {
      return /\.(md|markdown)$/i.test(p);
    });
    var outdir = (summary && summary.outdir) || lastDoneOutdir ||
                 el.outPath.value.trim();
    if (!outdir) { showError("请先指定输出目录"); return; }
    if (running || previewing) { showNotice("正在处理，请稍候…"); return; }
    var btn = el.btnExportDocx;
    var old = btn.textContent;
    btn.disabled = true;
    btn.textContent = "导出中…";
    clearBar();
    api("/api/word/export", { inputs: inputs, outdir: outdir }, 120000)
      .then(function (r) {
        if (!r.ok) {
          var detail = (r.results || []).filter(function (x) { return !x.ok; })
            .map(function (x) { return x.name + "：" + x.error; }).join("；");
          throw new Error((r.error || "Word 导出失败") +
                          (detail ? "（" + detail + "）" : ""));
        }
        var msg = "已生成 " + r.success + " 份 .docx：" + r.derived_dir;
        if (r.failed) msg += "；另有 " + r.failed + " 项未处理（见产物清单）";
        showNotice(msg + " · " + nowHMS());
      }).catch(function (err) {
        showError(err.message || String(err));
      }).finally(function () {
        btn.textContent = old;
        updateFeatureButtons();
      });
  }

  // S3：长任务同步请求 + 独立进度轮询；「取消转写」会终止本机 whisper 进程树。
  function doAudioTranscribe() {
    var inputs = currentInputs().filter(function (p) {
      return AUDIO_EXT_RE.test(p);
    });
    if (!inputs.length) {
      var v = (el.inputPath && el.inputPath.value || "").trim();
      if (v && AUDIO_EXT_RE.test(v)) inputs = [v];
    }
    if (!inputs.length) { showError("请先选择音频文件（mp3 / wav / m4a / flac 等）"); return; }
    var outdir = (summary && summary.outdir) || lastDoneOutdir ||
                 (el.outPath && el.outPath.value || "").trim();
    if (!outdir) { showError("请先指定输出目录"); return; }
    if (running || previewing) { showNotice("正在处理，请稍候…"); return; }
    var btn = el.btnAudioTranscribe;
    var cancelBtn = el.btnAudioCancel;
    var old = btn.textContent;
    btn.disabled = true;
    btn.textContent = "转写中…";
    cancelBtn.hidden = false;
    cancelBtn.disabled = false;
    clearBar();
    var since = 0;
    var timer = window.setInterval(function () {
      api("/api/audio/status?since=" + since, undefined, 5000).then(function (s) {
        if (!s) return;
        if (s.next) since = s.next;
        var evs = s.events || [];
        if (evs.length) showNotice(evs[evs.length - 1].text + " · " + nowHMS());
      }).catch(function () { /* 进度轮询失败不打断转写 */ });
    }, 800);
    api("/api/audio/transcribe", { inputs: inputs, outdir: outdir }, 900000)
      .then(function (r) {
        if (!r.ok) {
          var detail = (r.results || []).filter(function (x) { return !x.ok; })
            .map(function (x) { return x.name + "：" + x.error; }).join("；");
          throw new Error((r.error || "音频转写失败") +
                          (detail ? "（" + detail + "）" : ""));
        }
        var msg = "已生成 " + r.success + " 份带时间戳的 .md：" + r.derived_dir;
        if (r.failed) msg += "；另有 " + r.failed + " 项未处理（见产物清单）";
        if (r.cancelled) msg = "转写已取消：" + (r.error || "");
        showNotice(msg + " · " + nowHMS());
      }).catch(function (err) {
        showError(err.message || String(err));
      }).finally(function () {
        window.clearInterval(timer);
        cancelBtn.hidden = true;
        btn.textContent = old;
        updateFeatureButtons();
      });
  }

  function doAudioCancel() {
    api("/api/audio/cancel", {}, 5000).then(function (r) {
      if (!r.ok) showError(r.error || "取消失败");
      else showNotice("已请求取消转写（会终止本机工具进程） · " + nowHMS());
    }).catch(function (err) {
      showError(err.message || String(err));
    });
  }

  // S4：独立 video handler 的长任务；绝不复用 /api/audio/* 端点。
  function doVideoTranscribe() {
    var inputs = currentInputs().filter(function (p) {
      return VIDEO_EXT_RE.test(p);
    });
    if (!inputs.length) {
      var v = (el.inputPath && el.inputPath.value || "").trim();
      if (v && VIDEO_EXT_RE.test(v)) inputs = [v];
    }
    if (!inputs.length) { showError("请先选择视频文件（mp4 / mov / mkv / avi / webm 等）"); return; }
    var outdir = (summary && summary.outdir) || lastDoneOutdir ||
                 (el.outPath && el.outPath.value || "").trim();
    if (!outdir) { showError("请先指定输出目录"); return; }
    if (running || previewing) { showNotice("正在处理，请稍候…"); return; }
    var btn = el.btnVideoTranscribe;
    var cancelBtn = el.btnVideoCancel;
    var old = btn.textContent;
    btn.disabled = true;
    btn.textContent = "提取中…";
    cancelBtn.hidden = false;
    cancelBtn.disabled = false;
    clearBar();
    var since = 0;
    var timer = window.setInterval(function () {
      api("/api/video/status?since=" + since, undefined, 5000).then(function (s) {
        if (!s) return;
        if (s.next) since = s.next;
        var evs = s.events || [];
        if (evs.length) showNotice(evs[evs.length - 1].text + " · " + nowHMS());
      }).catch(function () { /* 进度轮询失败不打断提取 */ });
    }, 800);
    api("/api/video/transcribe", { inputs: inputs, outdir: outdir }, 1800000)
      .then(function (r) {
        if (!r.ok) {
          var detail = (r.results || []).filter(function (x) { return !x.ok; })
            .map(function (x) { return x.name + "：" + x.error; }).join("；");
          throw new Error((r.error || "视频提取失败") +
                          (detail ? "（" + detail + "）" : ""));
        }
        var msg = "已生成 " + r.success + " 份三区块 .md：" + r.derived_dir;
        if (r.failed) msg += "；另有 " + r.failed + " 项未处理（见产物清单）";
        if (r.cancelled) msg = "提取已取消：" + (r.error || "");
        showNotice(msg + " · " + nowHMS());
      }).catch(function (err) {
        showError(err.message || String(err));
      }).finally(function () {
        window.clearInterval(timer);
        cancelBtn.hidden = true;
        btn.textContent = old;
        updateFeatureButtons();
      });
  }

  function doVideoCancel() {
    api("/api/video/cancel", {}, 5000).then(function (r) {
      if (!r.ok) showError(r.error || "取消失败");
      else showNotice("已请求取消提取（会终止本机工具进程树） · " + nowHMS());
    }).catch(function (err) {
      showError(err.message || String(err));
    });
  }

  /* ------------------------------ S5：视频链接 → .md ------------------------------ */
  var linkPolling = null;
  var linkSince = 0;

  function linkList() {
    return (el.linkUrls && el.linkUrls.value || "").split(/\r?\n/)
      .map(function (s) { return s.trim(); }).filter(Boolean);
  }

  function doLinkInspect() {
    var urls = linkList();
    if (!urls.length) { showError("请先填写链接"); return; }
    if (el.linkStatus) el.linkStatus.textContent = "预检中…";
    // 只预检第一条（逐条预检在任务启动时统一做）
    api("/api/link/inspect", { url: urls[0] }, 15000).then(function (r) {
      if (!r || !r.ok) {
        if (el.linkStatus) el.linkStatus.textContent = "预检未通过：" +
          (((r || {}).check || {}).error || (r && r.error) || "未知");
        return;
      }
      var c = r.check || {};
      if (el.linkStatus) el.linkStatus.textContent =
        "预检通过：" + (c.host || "") +
        "（IP " + ((c.ips || []).join(", ") || "—") + "）";
    }).catch(function (err) {
      if (el.linkStatus) el.linkStatus.textContent = "预检失败：" + (err.message || err);
    });
  }

  function doLinkRun() {
    var urls = linkList();
    if (!urls.length) { showError("请先填写链接"); return; }
    var out = (el.outPath && el.outPath.value || "").trim();
    if (!out) { showError("请先填写输出目录"); return; }
    if (el.btnLinkRun) { el.btnLinkRun.disabled = true; el.btnLinkRun.textContent = "启动中…"; }
    if (el.btnLinkCancel) el.btnLinkCancel.hidden = false;
    clearBar();
    api("/api/media/run", {
      urls: urls, outdir: out,
      cookie_file: (el.linkCookie && el.linkCookie.value || "").trim()
    }, 15000).then(function (r) {
      if (!r || !r.ok) {
        showError((r && r.error) || "链接提取启动失败");
        updateFeatureButtons();
        return;
      }
      linkSince = 0;
      showNotice("链接提取已启动（共 " + (r.total || urls.length) + " 条） · " + nowHMS());
      startLinkPolling();
    }).catch(function (err) {
      showError(err.message || String(err));
      updateFeatureButtons();
    });
  }

  function doLinkCancel() {
    api("/api/media/cancel", {}, 5000).then(function (r) {
      if (!r.ok) showError(r.error || "取消失败");
      else showNotice("已请求取消链接提取（会清理临时下载） · " + nowHMS());
    }).catch(function (err) { showError(err.message || String(err)); });
  }

  function startLinkPolling() {
    if (linkPolling) clearTimeout(linkPolling);
    var poll = function () {
      api("/api/media/status?since=" + linkSince, undefined, 10000).then(function (s) {
        if (!s) return;
        if (typeof s.next === "number") linkSince = s.next;
        (s.events || []).forEach(function (ev) {
          if (el.linkStatus) el.linkStatus.textContent = ev.text || "";
        });
        if (s.running) {
          linkPolling = setTimeout(poll, 1000);
        } else {
          linkPolling = null;
          if (el.btnLinkCancel) el.btnLinkCancel.hidden = true;
          updateFeatureButtons();
          if (s.state === "done") {
            showNotice("链接提取完成：成功 " + (s.success || 0) +
              " / 失败 " + (s.failed || 0) + " · " + nowHMS());
          } else if (s.state === "failed") {
            showError(s.error || "链接提取失败");
          } else if (s.state === "cancelled") {
            showNotice("链接提取已取消 · " + nowHMS());
          }
        }
      }).catch(function () {
        linkPolling = setTimeout(poll, 2000);
      });
    };
    poll();
  }

  /* ------------------------------ Tabs ------------------------------ */
  function activateTab(name) {
    var tabs = document.querySelectorAll(".tab");
    for (var i = 0; i < tabs.length; i += 1) {
      tabs[i].classList.toggle("active", tabs[i].getAttribute("data-tab") === name);
    }
    var panels = document.querySelectorAll(".panel");
    for (var j = 0; j < panels.length; j += 1) {
      panels[j].classList.toggle("active", panels[j].id === "tab-" + name);
    }
    if (name === "log") {
      el.logBox.scrollTop = el.logBox.scrollHeight;
    }
  }

  /* ------------------------------ 初始化 ------------------------------ */
  function init() {
    // 页面初始化一律从干净状态起步，避免残留状态位把控件锁死。
    running = false;
    previewing = false;
    if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
    el.outPath.value = defaultOutdir();
    // 记住上次用过的输出目录（服务端状态优先，见下面的 /api/state 处理）
    var savedOut = lsGet(LS_OUTDIR);
    if (savedOut) el.outPath.value = savedOut;
    var tabs = document.querySelectorAll(".tab");
    for (var i = 0; i < tabs.length; i += 1) {
      tabs[i].addEventListener("click", function () {
        activateTab(this.getAttribute("data-tab"));
      });
    }

    el.btnPreview.addEventListener("click", function () { doPreview(); });
    // v0.4.9：清单标题栏的「预览分流」只对勾选文件生效；未识别任何文件时回退全量。
    el.btnPreviewInline.addEventListener("click", function () {
      if (!fileItems.length) { doPreview(); return; }
      var picked = checkedFilePaths();
      if (!picked.length) { showNotice("请先勾选要预览的文件"); return; }
      doPreview(picked);
    });
    el.btnRun.addEventListener("click", doRun);
    el.btnCancel.addEventListener("click", doCancel);
    el.btnOpenMerged.addEventListener("click", function () { openMerged(); });
    el.btnBrowseOut.addEventListener("click", browseOutput);
    el.btnPickFiles.addEventListener("click", pickFiles);
    bindKbEvents();
    bindReviseSync();
    bindArtifacts();
    el.btnSummarize.addEventListener("click", doSummarize);
    el.btnExportDocx.addEventListener("click", doWordExport);
    el.btnWordEnhance.addEventListener("click", doWordEnhance);
    el.btnAudioTranscribe.addEventListener("click", doAudioTranscribe);
    el.btnAudioCancel.addEventListener("click", doAudioCancel);
    el.btnVideoTranscribe.addEventListener("click", doVideoTranscribe);
    el.btnVideoCancel.addEventListener("click", doVideoCancel);
    // S5：链接提取
    if (el.linkUrls) el.linkUrls.addEventListener("input", updateFeatureButtons);
    if (el.btnLinkRun) el.btnLinkRun.addEventListener("click", doLinkRun);
    if (el.btnLinkInspect) el.btnLinkInspect.addEventListener("click", doLinkInspect);
    if (el.btnLinkCancel) el.btnLinkCancel.addEventListener("click", doLinkCancel);
    if (el.btnToggleFiles) el.btnToggleFiles.addEventListener("click", function () {
      var willHide = !el.fileList.hidden;
      el.fileList.hidden = willHide;
      el.btnToggleFiles.textContent = willHide ? "展开" : "收起";
    });
    // v0.4.9：全选框联动
    if (el.fileCheckAll) {
      el.fileCheckAll.addEventListener("change", function () {
        setAllChecked(el.fileCheckAll.checked);
        el.fileCheckAll.indeterminate = false;
      });
    }
    setupDropZone();
    el.inputPath.addEventListener("keydown", function (e) {
      if (e.key === "Enter") { e.preventDefault(); doPreview(); }
    });
    el.inputPath.addEventListener("input", function () {
      el.inputMeta.textContent = "未选择输入";
      el.inputMeta.classList.remove("filled");
      sel.inputs = [];
      clearFileList();
      rememberPaths();
    });
    el.outPath.addEventListener("input", rememberPaths);
    el.outPath.addEventListener("change", refreshMergedButton);

    // 左侧导航：页面切换（单击）+ 折叠/展开（双击任意导航项）
    // 用户裁决 2026-11-23：取消顶部横杠按钮，改为双击导航项折叠/展开。
    // 单击仍切页、双击仍会顺带切页（已确认接受），折叠切换是额外的 dblclick 行为。
    var navItems = document.querySelectorAll(".nav-item");
    for (var n = 0; n < navItems.length; n += 1) {
      navItems[n].addEventListener("click", function () {
        activatePage(this.getAttribute("data-page"));
      });
      navItems[n].addEventListener("dblclick", function () {
        setNavCollapsed(!el.appShell.classList.contains("nav-collapsed"));
      });
    }
    // S14：流程指引卡片的跨页跳转
    var gotoBtns = document.querySelectorAll("[data-goto]");
    for (var gi = 0; gi < gotoBtns.length; gi += 1) {
      gotoBtns[gi].addEventListener("click", function () {
        activatePage(this.getAttribute("data-goto"));
      });
    }
    // S7d：精读 / 修订 / 后端配置
    if (el.btnSaveBackend) el.btnSaveBackend.addEventListener("click", function () { saveBackendCfg(false); });
    if (el.btnProbeBackend) el.btnProbeBackend.addEventListener("click", function () { saveBackendCfg(true); });
    if (el.beMode) el.beMode.addEventListener("change", function () { applyBackendMode(); });
    if (el.btnPickRefine) el.btnPickRefine.addEventListener("click", function () { pickRefineSource(false); });
    if (el.btnPickRevise) el.btnPickRevise.addEventListener("click", function () { pickRefineSource(true); });
    if (el.btnStartRefine) el.btnStartRefine.addEventListener("click", function () {
      var path = (el.refineSource && el.refineSource.value || "").trim();
      if (!path) { showError("请先选择已转换的 md 文件"); return; }
      var model = (el.refineModel && el.refineModel.value || "").trim();
      // v1.0.7：补传 outdir —— 此前唯二漏传，导致产物嵌进冻结盘
      // （out/md/derived/，修订再套一层 derived/derived/）
      var refineOut = (el.outPath && el.outPath.value || lastDoneOutdir || "").trim();
      api("/api/refine/start", { path: path, model: model, outdir: refineOut }, 15000).then(function (r) {
        if (!r || !r.ok) { showError("精读启动失败：" + ((r && r.error) || "未知")); return; }
        el.btnStartRefine.disabled = true;
        startRefinePolling(false);
      }).catch(function (err) { showError(err.message || err); });
    });
    if (el.btnStartRevise) el.btnStartRevise.addEventListener("click", function () {
      var path = (el.reviseSource && el.reviseSource.value || "").trim();
      if (!path) { showError("请先选择精读产物 .refine.md"); return; }
      var instruction = (el.reviseInstruction && el.reviseInstruction.value || "").trim();
      var reviseOut = (el.outPath && el.outPath.value || lastDoneOutdir || "").trim();
      api("/api/revise/start", { path: path, instruction: instruction, outdir: reviseOut }, 15000).then(function (r) {
        if (!r || !r.ok) { showError("修订启动失败：" + ((r && r.error) || "未知")); return; }
        el.btnStartRevise.disabled = true;
        startRefinePolling(true);
      }).catch(function (err) { showError(err.message || err); });
    });
    if (el.btnCancelRefine) el.btnCancelRefine.addEventListener("click", function () {
      api("/api/refine/cancel", {}, 10000).then(function () {
        if (el.refineProgress) el.refineProgress.textContent = "已请求取消";
      });
    });
    if (el.btnOpenRefine) el.btnOpenRefine.addEventListener("click", function () {
      var p = el.refineResult && el.refineResult.dataset.path;
      if (p) api("/api/refine/open", { path: p }, 10000);
    });
    if (el.btnOpenReviseHtml) el.btnOpenReviseHtml.addEventListener("click", function () {
      var p = el.reviseResult && el.reviseResult.dataset.html;
      if (p) api("/api/refine/open", { path: p }, 10000);
    });
    if (el.btnSaveSettings) {
      el.btnSaveSettings.addEventListener("click", function () {
        saveSettings(readSettingsForm(), "已保存");
      });
    }
    if (el.btnPickIndir) {
      el.btnPickIndir.addEventListener("click", function () { pickDefaultFolder(el.setDefaultIndir); });
    }
    if (el.btnPickOutdir) {
      el.btnPickOutdir.addEventListener("click", function () { pickDefaultFolder(el.setDefaultOutdir); });
    }
    if (el.btnResetSettings) {
      el.btnResetSettings.addEventListener("click", function () {
        var desk = settings.default_desktop || "";
        saveSettings({
          auto_exit: true,
          exit_grace_seconds: 90,
          remember_paths: true,
          default_outdir: desk,
          default_indir: desk
        }, "已恢复默认");
      });
    }
    if (el.btnOpenAboutLog) {
      el.btnOpenAboutLog.addEventListener("click", function () { openLogFile(); });
    }
    if (el.btnExportData) {
      el.btnExportData.addEventListener("click", function () { exportData(); });
    }
    if (el.btnCheckUpdate) {
      el.btnCheckUpdate.addEventListener("click", function () { checkUpdate(); });
    }
    if (el.btnUpdateNow) {
      el.btnUpdateNow.addEventListener("click", function () { startUpdate(); });
    }
    if (el.btnUpdateCancel) {
      el.btnUpdateCancel.addEventListener("click", function () { cancelUpdate(); });
    }
    if (el.btnOpenAboutSettings) {
      el.btnOpenAboutSettings.addEventListener("click", function () {
        api("/api/settings", undefined, 10000).then(function (r) {
          if (!r || !r.settings_file) { showNotice("设置文件路径尚未就绪。"); return; }
          api("/api/open", { path: r.settings_file }, 10000)
            .then(function (res) {
              if (!res || !res.ok) showError("打开设置文件失败：" + ((res && res.error) || "未知"));
            })
            .catch(function (err) { showError("打开设置文件失败：" + (err.message || err)); });
        }).catch(function (err) {
          showError("读取设置文件路径失败：" + (err.message || err));
        });
      });
    }
    bindComponentEvents();
    setNavCollapsed(lsGet(LS_NAV) === "1");
    initNavResize();
    activatePage("home");

    // 桌面端快捷键：Ctrl+Enter 开始提取、Esc 取消运行中的任务
    document.addEventListener("keydown", function (e) {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        e.preventDefault();
        if (!running && !previewing) doRun();
        return;
      }
      if (e.key === "Escape" && running) {
        e.preventDefault();
        doCancel();
      }
    });

    updateControls();
    setState("idle");
    updateFeatureButtons();

    // 启动即读后端设置：决定「默认输出目录」与「是否记住路径」
    api("/api/settings", undefined, 10000).then(function (r) {
      if (!r || !r.ok) return;
      applySettings(r.settings);
      if (settings.default_outdir) {
        el.outPath.value = settings.default_outdir;
        refreshMergedButton();
      }
    }).catch(function () { /* 读不到设置就用默认值，不影响使用 */ });

    // 桌面端「关窗即退」心跳：每 2 秒上报一次「窗口还开着」。
    // 窗口关闭后心跳停止，服务端看门狗在宽限期后自动退出，
    // 不再留无界面的后台进程。请求失败静默忽略（服务已退出时亦然）。
    setInterval(function () {
      api("/api/heartbeat", undefined, 5000).catch(function () {});
    }, 2000);

    api("/api/state", undefined, 10000).then(function (st) {
      if (st.python) {
      }
      // 窗口标题 / 页头 / 侧栏版本标签：v0.4.0 起版本号唯一来源是后端 /api/state，
      // 必须在启动时注入。loadAbout() 只在切到「关于」页时才跑，不能让它负责
      // 全局标签，否则首页的 headerTag 会一直停留在占位符「—」。
      if (st.version && st.version !== "unknown") {
        document.title = "精核 · 文件提取 v" + st.version;
        if (el.headerTag) el.headerTag.textContent = "v" + st.version;
      }
      if (st.log_file) {
        logFile = st.log_file;
      }
      if (Array.isArray(st.inputs) && st.inputs.length > 1) {
        sel.inputs = st.inputs.slice();
        el.inputPath.value = st.inputs[0];
        el.inputPath.title = st.inputs.join("\n");
        el.inputMeta.textContent = "上次用了 " + st.inputs.length +
          " 个文件，点击「预览分流」查看清单";
      } else if (st.input) {
        el.inputPath.value = st.input;
        el.inputMeta.textContent = "上次使用的输入，点击「预览分流」查看件数";
      } else if (Array.isArray(st.inputs) && st.inputs.length === 1) {
        el.inputPath.value = st.inputs[0];
        el.inputMeta.textContent = "上次使用的输入，点击「预览分流」查看件数";
      } else {
        // 服务端没有上次记录（软件重启过）：用 localStorage 里的路径顶上
        var savedIn = lsGet(LS_INPUT);
        if (savedIn) {
          el.inputPath.value = savedIn;
          el.inputMeta.textContent = "已记住上次的输入路径，点击「预览分流」查看件数";
        }
      }
      if (st.outdir) el.outPath.value = st.outdir;
      else if (savedOut) el.outPath.value = savedOut;
      // 重启后按实际产物恢复「打开合并文档」入口，不再依赖内存里的 summary
      refreshMergedButton();
      if (st.running) {
        // 后端残留 running=true 不能直接 startRunning()（会把前端永久锁死）：
        // 先带超时确认 /api/progress 确实仍在运行，确认失败则保持解锁并提示。
        api("/api/progress?since=0", undefined, 10000).then(function (r) {
          if (r && r.running === true) {
            resetRunUI();
            startRunning();
          } else {
            showNotice("上次任务已结束，界面已恢复可用。");
            updateControls();
          }
        }).catch(function (err) {
          showNotice("无法确认上次任务状态，界面已恢复可用：" + (err.message || err));
          updateControls();
        });
      }
    }).catch(function (err) {
      showError("无法连接本地服务：" + (err.message || err));
    });

    // S1：工具健康探测只在启动时跑一次，绝不挂到 400ms 轮询上。
    loadTools();
    // S8：按当前配置初始化模式联动（抽取式/大模型），避免首屏控件状态不对
    api("/api/refine/backend", undefined, 10000).then(function (r) {
      var cfg = (r && r.config) || {};
      if (el.beMode) el.beMode.value = cfg.mode || "extract";
      if (el.beRounds) el.beRounds.value = String(cfg.refine_rounds || 1);
      if (el.beAllowSupplement) {
        el.beAllowSupplement.checked = !!cfg.allow_suppplement;
      }
      applyBackendMode();
    }).catch(function () { applyBackendMode(); });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
