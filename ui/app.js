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
    stateLabel: $("stateLabel"),
    pyLabel: $("pyLabel"),
    convLabel: $("convLabel"),
    verdictLabel: $("verdictLabel"),
    selfCheckWrap: $("selfCheckWrap"),
    selfCheck: $("selfCheck"),
    prepWrap: $("prepWrap"),
    prepNote: $("prepNote"),
    producedWrap: $("producedWrap"),
    producedNote: $("producedNote"),
    btnSummarize: $("btnSummarize"),
    btnExportDocx: $("btnExportDocx"),
    btnTranscribe: $("btnTranscribe"),
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
    btnKnowledgeBase: $("btnKnowledgeBase"),
    toolStatus: $("toolStatus"),
    // 左侧导航与页面
    appShell: $("appShell"),
    sidebar: $("sidebar"),
    navResizer: $("navResizer"),
    btnToggleNav: $("btnToggleNav"),
    sideVersion: $("sideVersion"),
    pageTitle: $("pageTitle"),
    pageSub: $("pageSub"),
    headerTag: $("headerTag"),
    pages: {
      home: $("page-home"),
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
    btnSaveSettings: $("btnSaveSettings"),
    btnResetSettings: $("btnResetSettings"),
    settingsStatus: $("settingsStatus"),
    settingsLogPath: $("settingsLogPath"),
    settingsFilePath: $("settingsFilePath"),
    btnOpenLogSettings: $("btnOpenLogSettings"),
    btnOpenSettingsFile: $("btnOpenSettingsFile"),
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
    beKind: $("beKind"),
    beMode: $("beMode"),
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
    aboutVersion2: $("aboutVersion2"),
    aboutPython: $("aboutPython"),
    aboutPlatform: $("aboutPlatform"),
    aboutLog: $("aboutLog"),
    btnOpenAboutLog: $("btnOpenAboutLog")
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
    var d = new Date();
    return ".\\out-" + d.getFullYear() + pad(d.getMonth() + 1) + pad(d.getDate()) +
      "-" + pad(d.getHours()) + pad(d.getMinutes());
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
    default_outdir: ""
  };

  var PAGE_META = {
    home: { title: "精核 · 文件提取", sub: "阶段 1 提取已交付 · 阶段 2 / 3 功能已就绪" },
    refine: { title: "精读 · 提纯核心", sub: "对已转换 md 提取核心知识点（模型由本机可插拔后端提供）" },
    revise: { title: "修订 · 补写与修改", sub: "补写缺失 + 修改核心，变更内容以颜色/标记区分" },
    settings: { title: "设置", sub: "只保存在本机，改动即时生效" },
    about: { title: "关于", sub: "版本、路线与隐私说明" }
  };

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
    if (name === "settings") { loadSettingsIntoForm(); loadBackendForm(); }
    if (name === "about") loadAbout();
    if (name === "refine" || name === "revise") refreshRefineCap();
  }

  function applySettings(cfg) {
    if (cfg && typeof cfg === "object") settings = cfg;
    if (el.setAutoExit) el.setAutoExit.checked = settings.auto_exit !== false;
    if (el.setExitGrace) el.setExitGrace.value = settings.exit_grace_seconds;
    if (el.setRememberPaths) el.setRememberPaths.checked = settings.remember_paths !== false;
    if (el.setDefaultOutdir) el.setDefaultOutdir.value = settings.default_outdir || "";
  }

  function loadSettingsIntoForm() {
    api("/api/settings", undefined, 10000).then(function (r) {
      if (!r || !r.ok) return;
      applySettings(r.settings);
      if (el.settingsLogPath) el.settingsLogPath.textContent = logFile || "—";
      if (el.settingsFilePath) el.settingsFilePath.textContent = r.settings_file || "—";
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
    }).catch(function (err) {
      el.settingsStatus.textContent = "保存失败：" + (err.message || err);
    });
  }

  function readSettingsForm() {
    return {
      auto_exit: el.setAutoExit.checked,
      exit_grace_seconds: parseInt(el.setExitGrace.value, 10) || 90,
      remember_paths: el.setRememberPaths.checked,
      default_outdir: el.setDefaultOutdir.value.trim()
    };
  }

  function loadAbout() {
    api("/api/state", undefined, 10000).then(function (st) {
      if (!st) return;
      var ver = st.version || "—";
      if (el.aboutVersion) el.aboutVersion.textContent = ver;
      if (el.aboutVersion2) el.aboutVersion2.textContent = ver;
      if (el.aboutPython) el.aboutPython.textContent = st.python || "—";
      if (el.aboutPlatform) el.aboutPlatform.textContent = st.platform || "—";
      if (el.aboutLog) el.aboutLog.textContent = st.log_file || "—";
      if (el.sideVersion) el.sideVersion.textContent = "v" + ver;
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

  /* v0.4.9：点击检查更新 →
       · 已是最新版本 → 弹「当前是最新版本」轻提示，3 秒自动消失；
       · 有新版本 → 直接进入更新流程（无需再点「立即更新」）；
       · 离线 / 报错 → 如实回显，绝不谎报「已是最新」。
     关键修复：/api/update/check 是 GET 端点，body 必须传 undefined，
     否则 api() 会把它当 POST 发出，命中「未知接口」404。*/
  function checkUpdate() {
    if (!el.btnCheckUpdate) return;
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

  function setState(name) {
    stateName = name;
    var map = { idle: "就绪", running: "运行中", cancelled: "已取消", failed: "失败" };
    el.stateLabel.textContent = map[name] || "就绪";
    el.stateLabel.className = "state " + (map[name] ? name : "idle");
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
    if (running || previewing) return;
    var target = (el.outPath.value || "").trim();
    if (!target) { showError("请先填写输出目录路径"); return; }
    api("/api/open-folder", { path: target }, 10000).then(function (r) {
      if (!r || !r.ok) showError("打开文件夹失败：" + ((r && r.error) || "未知"));
    }).catch(function (err) {
      showError("打开文件夹失败：" + (err.message || err));
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
    el.selfCheckWrap.hidden = true;
    el.prepWrap.hidden = true;
    el.producedWrap.hidden = true;
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
    var legacy = Number(s.legacy || 0);
    var unsupported = Number(s.unsupported || 0);
    if (!legacy && !unsupported) {
      el.prepWrap.hidden = true;
      return;
    }
    var parts = [];
    if (legacy) parts.push("需预处理 " + legacy);
    if (unsupported) parts.push("不支持 " + unsupported);
    el.prepNote.textContent = parts.join(" · ");
    el.prepNote.title = PREP_TIP;
    el.prepNote.classList.toggle("warn", legacy > 0);
    el.prepWrap.hidden = false;
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

    el.selfCheck.textContent = "空文件 " + (s.empty != null ? s.empty : 0);
    el.selfCheckWrap.hidden = false;
    renderPrep(s);

    if (cancelled) {
      el.producedNote.textContent = "已产出 " + produced + (cand ? " / " + cand : "");
      el.producedWrap.hidden = false;
      el.overviewHint.textContent = "任务已取消，已产出 " + produced + " 项，产物不完整；细节见「运行日志」。";
    } else {
      el.producedWrap.hidden = true;
      el.overviewHint.textContent = failed > 0
        ? "候选 " + cand + " 项 · 成功 " + (s.success || 0) + " / 未成功 " + failed +
          "，逐条处置见「降级明细」。"
        : "候选 " + cand + " 项全部成功" +
          (s.no_heading ? "；其中 " + s.no_heading + " 项无标题层级。" : "。");
    }

    if (s.converter) el.convLabel.textContent = "转换器 " + s.converter;
    el.verdictLabel.textContent = "验收 " + (s.verdict || "—");

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
      allow_suppplement: !!(el.beAllowSupplement && el.beAllowSupplement.checked)
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
            if (el.revisePreviewHtml && r && r.ok) el.revisePreviewHtml.srcdoc = r.text;
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
    el.btnTranscribe.disabled = !on || !mediaOn;
    el.btnTranscribe.textContent = mediaOn ? "音视频转写" : "音视频转写（未启用）";
    var wi = (toolState && toolState.word_input) || {};
    var wordOn = !!wi.enabled;
    el.btnWordEnhance.disabled = !(!running && !previewing && wordOn &&
                                   (hasWordInput() || on));
    el.btnWordEnhance.textContent = wordOn ? "Word 输入增强" : "Word 输入增强（未启用）";
    // S3：真实能力走 /api/tools/probe 顶层 audio_transcribe；缺工具恒禁用并显示「未启用」。
    // 老的音视频转写占位按钮（btnTranscribe）仍按 S1 的诚实降级判定，原样保留。
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

  function doTranscribe() {
    var inputs = currentInputs();
    if (!inputs.length) {
      var v = el.inputPath.value.trim();
      if (v) inputs = [v];
    }
    if (!inputs.length) { showError("请先选择音视频文件"); return; }
    callFeature("/api/transcribe", { inputs: inputs }, el.btnTranscribe, "转写中…");
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
    el.btnSummarize.addEventListener("click", doSummarize);
    el.btnExportDocx.addEventListener("click", doWordExport);
    el.btnTranscribe.addEventListener("click", doTranscribe);
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
    el.btnKnowledgeBase.addEventListener("click", function () {
      showNotice("阶段 4 知识库 / 自动化规划中，敬请期待。");
    });
    el.btnToggleFiles.addEventListener("click", function () {
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
    el.prepNote.addEventListener("click", function () {
      showNotice(PREP_TIP);
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

    // 左侧导航：折叠/展开 + 页面切换（点开才显示对应内容）
    if (el.btnToggleNav) {
      el.btnToggleNav.addEventListener("click", function () {
        setNavCollapsed(!el.appShell.classList.contains("nav-collapsed"));
      });
    }
    var navItems = document.querySelectorAll(".nav-item");
    for (var n = 0; n < navItems.length; n += 1) {
      navItems[n].addEventListener("click", function () {
        activatePage(this.getAttribute("data-page"));
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
      api("/api/refine/start", { path: path, model: model }, 15000).then(function (r) {
        if (!r || !r.ok) { showError("精读启动失败：" + ((r && r.error) || "未知")); return; }
        el.btnStartRefine.disabled = true;
        startRefinePolling(false);
      }).catch(function (err) { showError(err.message || err); });
    });
    if (el.btnStartRevise) el.btnStartRevise.addEventListener("click", function () {
      var path = (el.reviseSource && el.reviseSource.value || "").trim();
      if (!path) { showError("请先选择精读产物 .refine.md"); return; }
      var instruction = (el.reviseInstruction && el.reviseInstruction.value || "").trim();
      api("/api/revise/start", { path: path, instruction: instruction }, 15000).then(function (r) {
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
    if (el.btnResetSettings) {
      el.btnResetSettings.addEventListener("click", function () {
        saveSettings({
          auto_exit: true,
          exit_grace_seconds: 90,
          remember_paths: true,
          default_outdir: ""
        }, "已恢复默认");
      });
    }
    if (el.btnOpenLogSettings) {
      el.btnOpenLogSettings.addEventListener("click", function () { openLogFile(); });
    }
    if (el.btnOpenAboutLog) {
      el.btnOpenAboutLog.addEventListener("click", function () { openLogFile(); });
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
    if (el.btnOpenSettingsFile) {
      el.btnOpenSettingsFile.addEventListener("click", function () {
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
        var v = (st.version && st.version !== "unknown") ? "精核 " + st.version + " · " : "";
        el.pyLabel.textContent = v + "Python " + st.python;
      }
      // 窗口标题 / 页头 / 侧栏版本标签：v0.4.0 起版本号唯一来源是后端 /api/state，
      // 必须在启动时注入。loadAbout() 只在切到「关于」页时才跑，不能让它负责
      // 全局标签，否则首页的 headerTag 会一直停留在占位符「—」。
      if (st.version && st.version !== "unknown") {
        document.title = "精核 · 文件提取 v" + st.version;
        if (el.headerTag) el.headerTag.textContent = "v" + st.version;
        if (el.sideVersion) el.sideVersion.textContent = "v" + st.version;
      }
      if (st.log_file) {
        logFile = st.log_file;
      }
      if (st.converter) el.convLabel.textContent = "转换器 " + st.converter;
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
