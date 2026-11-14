/* 精核 · 本地界面逻辑（原生 JS，无依赖） */
"use strict";

(function () {
  var POLL_MS = 400;
  var $ = function (id) { return document.getElementById(id); };

  var el = {
    inputPath: $("inputPath"),
    outPath: $("outPath"),
    btnPickFiles: $("btnPickFiles"),
    btnBrowseInput: $("btnBrowseInput"),
    btnBrowseOut: $("btnBrowseOut"),
    btnPreview: $("btnPreview"),
    btnPreviewInline: $("btnPreviewInline"),
    btnRun: $("btnRun"),
    btnCancel: $("btnCancel"),
    btnOpenMerged: $("btnOpenMerged"),
    btnOpenOut: $("btnOpenOut"),
    optOpenMerged: $("optOpenMerged"),
    errorBar: $("errorBar"),
    runStatus: $("runStatus"),
    progressBar: $("progressBar"),
    inputMeta: $("inputMeta"),
    fileListWrap: $("fileListWrap"),
    fileListTitle: $("fileListTitle"),
    fileList: $("fileList"),
    btnToggleFiles: $("btnToggleFiles"),
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
    btnKnowledgeBase: $("btnKnowledgeBase")
  };

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
    var d = new Date();
    return ".\\out-" + d.getFullYear() + pad(d.getMonth() + 1) + pad(d.getDate()) +
      "-" + pad(d.getHours()) + pad(d.getMinutes());
  }

  function showBar(kind, message) {
    el.errorBar.className = "bar " + (kind === "notice" ? "bar-notice" : "bar-error");
    el.errorBar.textContent = message;
    el.errorBar.hidden = false;
  }

  function showError(message) { showBar("error", message); }
  function showNotice(message) { showBar("notice", message); }
  function clearBar() { el.errorBar.hidden = true; el.errorBar.textContent = ""; }

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
    var ids = ["inputPath", "outPath", "btnPickFiles", "btnBrowseInput", "btnBrowseOut",
      "btnRun", "btnPreview", "btnPreviewInline"];
    ids.forEach(function (id) { $(id).disabled = lock; });
    el.btnCancel.disabled = !running;
  }

  /* ------------------------------ 分流展示 ------------------------------ */
  function renderBuckets(data) {
    var b = data.buckets || {};
    var parts = [];
    var labels = [
      ["文本类", "文本"], ["富文档", "富文档"], ["阶段3预留", "音视频"],
      ["需预处理", "需预处理"], ["不支持", "不支持"]
    ];
    labels.forEach(function (pair) {
      var n = Number(b[pair[0]] || 0);
      if (n > 0) parts.push(pair[1] + " " + n);
    });
    var total = Number(data.total || 0);
    el.inputMeta.textContent = total + " 个文件" + (parts.length ? " · " + parts.join(" / ") : "");
    el.inputMeta.classList.toggle("filled", total > 0);
  }

  var KIND_CLASS = {
    "文本类": "text",
    "富文档": "rich",
    "阶段3预留": "deferred",
    "需预处理": "legacy",
    "不支持": "unsupported"
  };

  var FILE_LIST_MAX = 500;

  function clearFileList() {
    el.fileListWrap.hidden = true;
    el.fileList.textContent = "";
  }

  function renderFileList(data) {
    var items = Array.isArray(data.items) ? data.items : [];
    if (!items.length) { clearFileList(); return; }

    el.fileList.textContent = "";
    var shown = items.length > FILE_LIST_MAX ? items.slice(0, FILE_LIST_MAX) : items;

    shown.forEach(function (item) {
      var li = document.createElement("li");
      li.className = "file-item";

      var kind = item.kind || "未知";
      var chip = document.createElement("span");
      chip.className = "file-kind kind-" + (KIND_CLASS[kind] || "other");
      chip.textContent = kind;
      li.appendChild(chip);

      var name = document.createElement("span");
      name.className = "file-name";
      name.textContent = item.name || "—";
      name.title = item.name || "";
      li.appendChild(name);

      el.fileList.appendChild(li);
    });

    if (items.length > shown.length) {
      var more = document.createElement("li");
      more.className = "file-more";
      more.textContent = "…还有 " + (items.length - shown.length) + " 个文件未列出";
      el.fileList.appendChild(more);
    }

    var counted = Number(data.total || 0);
    if (!counted) counted = items.length;
    el.fileListTitle.textContent = "已识别 " + counted + " 个文件";

    el.fileList.hidden = false;
    el.btnToggleFiles.textContent = "收起";
    el.fileListWrap.hidden = false;
  }

  /* ------------------------------ 预览 ------------------------------ */
  function doPreview() {
    var input = el.inputPath.value.trim();
    if (!input) { showError("请先填写输入路径"); return; }
    if (running || previewing) { showNotice("正在处理，请稍候…"); return; }
    clearBar();
    previewing = true;
    updateControls();
    var oldInline = el.btnPreviewInline.textContent;
    var oldMain = el.btnPreview.textContent;
    el.btnPreviewInline.textContent = "预览中…";
    el.btnPreview.textContent = "预览中…";

    var body = currentInputs().length ? { inputs: currentInputs() } : { input: input };
    // 40000 = 后端 _dry_run 的 DRY_RUN_TIMEOUT(30s) + 10s 余量，
    // 避免前端误杀合法的长盘点。
    api("/api/dry-run", body, 40000).then(function (r) {
      if (!r.ok) throw new Error(r.error || "预览分流失败");
      renderBuckets(r);
      renderFileList(r);
      // U1：常驻可见的完成反馈，每次重写且带本地时间戳，
      // 即便数字与上次完全相同，用户也能看出「这次点下去了、程序回应了」。
      var b = r.buckets || {};
      var total = Number(r.total || 0);
      var stamp = nowHMS();
      if (total > 0) {
        el.inputMeta.textContent = "预览完成 · 共 " + total + " 个文件 · " +
          "文本类 " + Number(b["文本类"] || 0) + " / 富文档 " + Number(b["富文档"] || 0) +
          " / 阶段3预留 " + Number(b["阶段3预留"] || 0) + " / 需预处理 " +
          Number(b["需预处理"] || 0) + " / 不支持 " + Number(b["不支持"] || 0) +
          " · " + stamp;
      } else {
        el.inputMeta.textContent = "预览完成 · 未发现可识别文件 · " + stamp;
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

  /* ------------------------------ 文件夹选择 ------------------------------ */
  function browse(target) {
    if (running || previewing) return;
    var btn = target === el.inputPath ? el.btnBrowseInput : el.btnBrowseOut;
    var old = btn.textContent;
    btn.disabled = true;
    btn.textContent = "选择中…";
    // pick-folder 要等用户操作原生对话框，第三参数传 0 = 绝不 abort。
    api("/api/pick-folder", { initial: target.value.trim() }, 0).then(function (r) {
      if (r && r.path) {
        target.value = r.path;
        if (target === el.inputPath) {
          sel.inputs = [];
          clearFileList();
          doPreview();
        }
      }
    }).catch(function (err) {
      showError("打开文件夹选择框失败：" + (err.message || err));
    }).finally(function () {
      btn.textContent = old;
      updateControls();
    });
  }

  /* ------------------------------ 文件选择（多选） ------------------------------ */
  function pickFiles() {
    if (running || previewing) return;
    var btn = el.btnPickFiles;
    var old = btn.textContent;
    btn.disabled = true;
    btn.textContent = "选择中…";
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
    el.btnOpenOut.disabled = true;
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

  function openMerged(outdir) {
    if (!outdir) return;
    var base = String(outdir).replace(/[\\/]+$/, "");
    api("/api/open", { path: base + "/MERGED.md" }, 10000).catch(function () { /* 静默 */ });
  }

  function openOutputDir(outdir) {
    if (!outdir) return;
    api("/api/open", { path: String(outdir).replace(/[\\/]+$/, "") }, 10000).catch(function () { /* 静默 */ });
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
      el.btnOpenOut.disabled = false;
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
  // 仅在「本次运行成功且有产物目录」时点亮后处理按钮；运行/预览中不点亮。
  function updateFeatureButtons() {
    var on = !!lastDoneOutdir && !running && !previewing;
    el.btnSummarize.disabled = !on;
    el.btnExportDocx.disabled = true;  // 导出 Word 为后续计划，恒禁用
    el.btnTranscribe.disabled = !on;
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
    var tabs = document.querySelectorAll(".tab");
    for (var i = 0; i < tabs.length; i += 1) {
      tabs[i].addEventListener("click", function () {
        activateTab(this.getAttribute("data-tab"));
      });
    }

    el.btnPreview.addEventListener("click", doPreview);
    el.btnPreviewInline.addEventListener("click", doPreview);
    el.btnRun.addEventListener("click", doRun);
    el.btnCancel.addEventListener("click", doCancel);
    el.btnOpenMerged.addEventListener("click", function () {
      openMerged(summary && summary.outdir);
    });
    el.btnBrowseInput.addEventListener("click", function () { browse(el.inputPath); });
    el.btnBrowseOut.addEventListener("click", function () { browse(el.outPath); });
    el.btnOpenOut.addEventListener("click", function () {
      openOutputDir(summary && summary.outdir);
    });
    el.btnPickFiles.addEventListener("click", pickFiles);
    el.btnSummarize.addEventListener("click", doSummarize);
    el.btnExportDocx.addEventListener("click", function () {
      showNotice("导出 Word 为后续计划（阶段 2 二期），当前输出格式为 Markdown（MERGED.md）。");
    });
    el.btnTranscribe.addEventListener("click", doTranscribe);
    el.btnKnowledgeBase.addEventListener("click", function () {
      showNotice("阶段 4 知识库 / 自动化规划中，敬请期待。");
    });
    el.btnToggleFiles.addEventListener("click", function () {
      var willHide = !el.fileList.hidden;
      el.fileList.hidden = willHide;
      el.btnToggleFiles.textContent = willHide ? "展开" : "收起";
    });
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
    });

    updateControls();
    setState("idle");
    updateFeatureButtons();

    api("/api/state", undefined, 10000).then(function (st) {
      if (st.python) {
        var v = (st.version && st.version !== "unknown") ? "精核 " + st.version + " · " : "";
        el.pyLabel.textContent = v + "Python " + st.python;
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
      }
      if (st.outdir) el.outPath.value = st.outdir;
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
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
