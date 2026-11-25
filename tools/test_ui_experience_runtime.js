/* 真运行时行为测试（v1.7.0 UI 体验翻新）：在 VM 里真实执行
 * applyTheme / cmdMatches / renderCmdList / showDoneSummary，
 * 喂最小 DOM stub，断言深色主题落到 <html>、命令面板渲染出条目、
 * 结果前置生成摘要文本。退出码 0 = 全部通过。
 */
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(__dirname, "..");
const js = fs.readFileSync(path.join(ROOT, "ui", "app.js"), "utf8");
const i18nSrc = fs.readFileSync(path.join(ROOT, "ui", "i18n.js"), "utf8");

function extractBalanced(src, startMarker) {
  const start = src.indexOf(startMarker);
  if (start < 0) throw new Error("未找到 " + startMarker);
  const objStart = src.indexOf("[", start) >= 0 && src.indexOf("[", start) < src.indexOf("{", start)
    ? src.indexOf("[", start) : src.indexOf("{", start);
  let depth = 0, inStr = false, quote = "", esc = false;
  for (let i = objStart; i < src.length; i++) {
    const c = src[i];
    if (inStr) {
      if (esc) { esc = false; continue; }
      if (c === "\\") { esc = true; continue; }
      if (c === quote) inStr = false;
      continue;
    }
    if (c === '"' || c === "'" || c === "`") { inStr = true; quote = c; continue; }
    if (c === "[" || c === "{") depth++;
    else if (c === "]" || c === "}") { depth--; if (depth === 0) return src.slice(start, i + 1); }
  }
  throw new Error("括号未闭合: " + startMarker);
}

function extractFn(name) {
  const re = new RegExp("function " + name + "\\s*\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n  \\}");
  const m = js.match(re);
  if (!m) throw new Error("无法抽取函数 " + name);
  return m[0];
}

const i18nDecl = extractBalanced(i18nSrc, "window.JINGHE_I18N =")
  .replace("window.JINGHE_I18N =", "var I18N =");
const CMD_DECL = extractBalanced(js, "var CMD_ITEMS =");

function makeNode(tag) {
  return {
    tag: tag || "div", children: [], attrs: {}, _text: "", _listeners: {},
    className: "", type: "", checked: false, disabled: false, hidden: false,
    value: "", title: "", style: {},
    get textContent() {
      var child = (this.children || []).map(function (c) { return c.textContent; }).join("");
      return this._text + child;
    },
    set textContent(v) { this._text = String(v); this.children = []; },
    setAttribute(k, v) { this.attrs[k] = String(v); },
    getAttribute(k) { return this.attrs[k] !== undefined ? this.attrs[k] : null; },
    appendChild(c) { this.children.push(c); return c; },
    addEventListener(ev, fn) { this._listeners[ev] = fn; },
    querySelectorAll(sel) {
      const out = [];
      const cls = sel.replace(/^\./, "");
      (function walk(n) {
        (n.children || []).forEach(function (c) {
          if (String(c.className).split(/\s+/).indexOf(cls) >= 0) out.push(c);
          walk(c);
        });
      })(this);
      return out;
    },
    scrollIntoView() {},
    classList: {
      _set: new Set(),
      toggle(c, on) { if (on === undefined) on = !this._set.has(c); if (on) this._set.add(c); else this._set.delete(c); },
      add(c) { this._set.add(c); },
      remove(c) { this._set.delete(c); },
      contains(c) { return this._set.has(c); },
    },
  };
}

const htmlNode = { attrs: {}, setAttribute(k, v) { this.attrs[k] = String(v); }, getAttribute(k) { return this.attrs[k]; } };
const cmdList = makeNode("div");
const cmdInput = makeNode("input");
const doneSummary = makeNode("div");
const doneText = makeNode("span");
const doneBtn = makeNode("button");
const themeLight = makeNode("input");
const themeDark = makeNode("input");

const el = {
  cmdList, cmdInput, doneSummary, doneSummaryText: doneText,
  btnDoneOpenMerged: doneBtn, setThemeLight: themeLight, setThemeDark: themeDark,
  pageTitle: makeNode("h1"), pageSub: makeNode("p"),
  setLangZh: makeNode("input"), setLangEn: makeNode("input"),
};

const sandbox = {
  console, el,
  document: {
    documentElement: htmlNode,
    createElement(tag) { return makeNode(tag); },
    getElementById() { return null; },
    querySelectorAll() { return []; },
  },
  window: {
    setTimeout(fn, ms) { return 0; },
    clearTimeout() {},
  },
  currentLang: "zh",
  currentTheme: "light",
  lastDoneOutdir: null,
  cmdActive: 0,
  cmdVisible: [],
  activatePage(p) { sandbox.__activated = p; },
  doRun() { sandbox.__ran = true; },
  doPreview() {},
  doRunAndIngest() {},
  doKbRebuild() {},
  openMerged() {},
  readSettingsForm() { return { lang: "zh", theme: "dark" }; },
  saveSettings(p) { sandbox.__savedTheme = p.theme; },
  showNotice(m) { sandbox.__notice = m; },
  doneSummaryTimer: null,
  setTimeout(fn, ms) { return 0; },
  clearTimeout() {},
};
vm.createContext(sandbox);

const code = [
  i18nDecl,
  "function tr(key) { var d = I18N[currentLang] || I18N.zh; return (d[key] !== undefined) ? d[key] : (I18N.zh[key] !== undefined ? I18N.zh[key] : key); }",
  "var currentLang = 'zh';",
  "var currentTheme = 'light';",
  "var currentPage = 'home';",
  "var doneSummaryTimer = null;",
  CMD_DECL,
  extractFn("applyTheme"),
  extractFn("cmdMatches"),
  extractFn("renderCmdList"),
  extractFn("showDoneSummary"),
  "this.__applyTheme = applyTheme;",
  "this.__cmdMatches = cmdMatches;",
  "this.__renderCmdList = renderCmdList;",
  "this.__showDoneSummary = showDoneSummary;",
  "this.__CMD_ITEMS = CMD_ITEMS;",
].join("\n");
vm.runInContext(code, sandbox);

let failures = 0;
function check(cond, msg) {
  if (cond) console.log("  PASS " + msg);
  else { console.error("  FAIL " + msg); failures++; }
}
function flatten(node, out) {
  out.push(node);
  (node.children || []).forEach(function (c) { flatten(c, out); });
  return out;
}

// ---- 场景 1：主题切换落到 <html data-theme> ----
sandbox.__applyTheme("dark");
check(htmlNode.getAttribute("data-theme") === "dark", "applyTheme('dark') 落到 html[data-theme=dark]");
check(themeDark.checked === true && themeLight.checked === false, "深色单选被选中");
sandbox.__applyTheme("light");
check(htmlNode.getAttribute("data-theme") === "light", "applyTheme('light') 切回浅色");
sandbox.currentLang = "en";

// ---- 场景 2：命令注册表 + 模糊搜索 ----
check(sandbox.__CMD_ITEMS.length === 15, "命令注册表含 15 条（7 页面 + 6 动作 + 2 主题）");
check(sandbox.__cmdMatches(sandbox.__CMD_ITEMS[4], "知识库") === true, "中文关键词命中知识库页");
check(sandbox.__cmdMatches(sandbox.__CMD_ITEMS[4], "kb") === true, "英文关键词命中知识库页");
check(sandbox.__cmdMatches(sandbox.__CMD_ITEMS[4], "zzzz") === false, "无关关键词不匹配");

// ---- 场景 3：渲染命令列表（英文界面）----
cmdInput.value = "theme";
cmdList.textContent = "";
sandbox.__renderCmdList();
const nodes = flatten(cmdList, []);
const items = nodes.filter(n => String(n.className).indexOf("cmd-item") >= 0);
const groups = nodes.filter(n => String(n.className).indexOf("cmd-group-title") >= 0);
check(items.length === 2, "搜索 theme → 渲染 2 条主题命令（实际 " + items.length + "）");
check(groups.length === 1 && groups[0].textContent === "Appearance", "英文界面分组标题 = Appearance");
check(items[0].textContent.indexOf("Light theme") >= 0, "英文界面首条含 Light theme（实际 " + items[0].textContent + "）");
check(typeof items[0]._listeners.click === "function", "命令条目绑定了点击事件");

// 中文界面渲染
sandbox.currentLang = "zh";
cmdInput.value = "知识库";
cmdList.textContent = "";
sandbox.__renderCmdList();
const zhItems = flatten(cmdList, []).filter(n => String(n.className).indexOf("cmd-item") >= 0);
check(zhItems.length >= 1, "中文搜索「知识库」渲染出条目");
check(zhItems.some(n => n.textContent.indexOf("知识库") >= 0), "中文条目文案含「知识库」");

// ---- 场景 4：结果前置摘要 ----
sandbox.__showDoneSummary({ success: 7, failed: 1, elapsed: 2.34, outdir: "/out" });
check(doneSummary.hidden === false, "成功后结果前置条显示");
check(doneText.textContent.indexOf("本次完成 7 项") >= 0, "摘要含成功数（实际 " + doneText.textContent + "）");
check(doneText.textContent.indexOf("未成功 1") >= 0, "摘要含失败数");
check(doneText.textContent.indexOf("耗时 2.3s") >= 0, "摘要含耗时（实际 " + doneText.textContent + "）");
check(doneBtn.hidden === false, "有产物时显示打开合并文档按钮");

sandbox.__showDoneSummary({ success: 2, failed: 0, elapsed: 1.0, outdir: "" });
check(doneBtn.hidden === true, "无产物时隐藏打开合并文档按钮");

if (failures) {
  console.error("\nUI 体验行为测试失败: " + failures + " 项");
  process.exit(1);
}
console.log("\nUI 体验行为测试全部通过（19 项断言）");
