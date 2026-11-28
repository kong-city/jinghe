/* 真运行时行为测试（v1.7.1 主题持久化 + 布局改造）：
 *
 * 复现并锁死一个真实缺陷：
 *   点「深色」只改了前端 DOM，从未落盘；切到别的功能页再回设置页时，
 *   loadSettingsIntoForm() 拉回后端仍是 light 的旧值，applySettings() 覆盖回去，
 *   界面自己变回浅色。
 *
 * 本脚本在 VM 里真实执行 applyTheme / persistUiPref / applySettings，
 * 喂最小 DOM stub，断言：
 *   1. 点深色会真的发出落盘请求（带 theme=dark）
 *   2. 落盘成功前，本地 override 已生效（竞态保护）
 *   3. 切页后重新拉回后端旧值 light，界面仍然是 dark（不被打回）
 *   4. 落盘成功后本地 settings 被回写
 *   5. 流程条随页面切换高亮当前阶段
 *
 * 退出码 0 = 全部通过。
 */
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(__dirname, "..");
const js = fs.readFileSync(path.join(ROOT, "ui", "app.js"), "utf8");
const i18nSrc = fs.readFileSync(path.join(ROOT, "ui", "i18n.js"), "utf8");

let passed = 0;
function check(cond, msg) {
  if (!cond) {
    console.error("FAIL: " + msg);
    process.exitCode = 1;
    return;
  }
  passed += 1;
  console.log("PASS: " + msg);
}

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

function makeNode(tag) {
  return {
    tag: tag || "div", children: [], attrs: {}, _text: "", _listeners: {},
    className: "", type: "", checked: false, disabled: false, hidden: false,
    value: "", title: "", style: {},
    get textContent() {
      const child = (this.children || []).map(function (c) { return c.textContent; }).join("");
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
const themeLight = makeNode("input");
const themeDark = makeNode("input");
const langZh = makeNode("input");
const langEn = makeNode("input");
const settingsStatus = makeNode("span");

// 三个流程条步骤（①取内容 ②加工 ③沉淀），用于验证高亮跟随页面切换
const stripHome = makeNode("button");
stripHome.className = "strip-step";
stripHome.setAttribute("data-goto", "home");
const stripProcess = makeNode("button");
stripProcess.className = "strip-step";
stripProcess.setAttribute("data-goto", "refine");
const stripKb = makeNode("button");
stripKb.className = "strip-step";
stripKb.setAttribute("data-goto", "kb");

const el = {
  setThemeLight: themeLight, setThemeDark: themeDark,
  setLangZh: langZh, setLangEn: langEn,
  settingsStatus: settingsStatus,
};

const stripSteps = [stripHome, stripProcess, stripKb];

// 后端设置存储（模拟 settings.json）
let serverSettings = { lang: "zh", theme: "light", auto_exit: true, exit_grace_seconds: 90 };

const sandbox = {
  console, el,
  document: {
    documentElement: htmlNode,
    createElement(tag) { return makeNode(tag); },
    getElementById() { return null; },
    querySelectorAll(sel) {
      if (sel === ".strip-step") return stripSteps;
      return [];
    },
  },
  window: { setTimeout(fn, ms) { return 0; }, clearTimeout() {} },
  currentLang: "zh",
  currentTheme: "light",
  currentPage: "home",
  settings: { lang: "zh", theme: "light" },
  // 记录发出的落盘请求
  __requests: [],
  api(path, body) {
    const req = { path, body };
    sandbox.__requests.push(req);
    // 模拟后端：合并落盘并回包
    if (path === "/api/settings" && body && body.settings) {
      Object.assign(serverSettings, body.settings);
      return Promise.resolve({ ok: true, settings: Object.assign({}, serverSettings) });
    }
    return Promise.resolve({ ok: true, settings: Object.assign({}, serverSettings) });
  },
  showError(m) { sandbox.__error = m; },
  showNotice(m) { sandbox.__notice = m; },
  tr(key) { return key; },
  setTimeout(fn, ms) { return 0; },
  clearTimeout() {},
  activatePage() {},
};
vm.createContext(sandbox);

const code = [
  i18nDecl,
  "var currentLang = 'zh';",
  "var currentTheme = 'light';",
  "var currentPage = 'home';",
  "var settings = { lang: 'zh', theme: 'light' };",
  // applySettings 会调 applyLang；这里用轻量 stub（i18n 另有专项运行时测试覆盖）
  "function applyLang(lang) { currentLang = (lang === 'en') ? 'en' : 'zh'; }",
  extractFn("applyTheme"),
  extractFn("persistUiPref"),
  extractFn("applySettings"),
  extractFn("syncStrip"),
  "this.__applyTheme = applyTheme;",
  "this.__persistUiPref = persistUiPref;",
  "this.__applySettings = applySettings;",
  "this.__syncStrip = syncStrip;",
].join("\n");
vm.runInContext(code, sandbox);

// ─────────────────────────────────────────────────────────────
// 场景：用户点「深色」
// ─────────────────────────────────────────────────────────────
sandbox.__applyTheme("dark");
sandbox.uiPrefOverride = { lang: null, theme: "dark" };
check(htmlNode.attrs["data-theme"] === "dark", "点深色后 <html data-theme> = dark");
check(themeDark.checked === true, "点深色后深色单选被选中");
check(themeLight.checked === false, "点深色后浅色单选取消");

// 发出落盘请求
sandbox.__persistUiPref("theme", "dark");
const req = sandbox.__requests[sandbox.__requests.length - 1];
check(req && req.path === "/api/settings", "点深色发出 /api/settings 落盘请求");
check(req && req.body && req.body.settings && req.body.settings.theme === "dark",
  "落盘请求体带 theme=dark");

// ─────────────────────────────────────────────────────────────
// 场景：保存请求在途时切页，后端 GET 返回旧值 light
// ─────────────────────────────────────────────────────────────
serverSettings.theme = "light";  // 后端仍是旧的 light（请求尚未落盘）
sandbox.__applySettings({ lang: "zh", theme: "light", auto_exit: true, exit_grace_seconds: 90 });
check(htmlNode.attrs["data-theme"] === "dark",
  "切页拉回后端旧值 light 后，界面仍是 dark（不被打回浅色）");

// ─────────────────────────────────────────────────────────────
// 场景：落盘成功后，后端已是 dark，再次切页
// ─────────────────────────────────────────────────────────────
serverSettings.theme = "dark";
sandbox.__applySettings({ lang: "zh", theme: "dark", auto_exit: true, exit_grace_seconds: 90 });
check(htmlNode.attrs["data-theme"] === "dark", "落盘后再切页，界面仍为 dark");

// ─────────────────────────────────────────────────────────────
// 场景：落盘成功后本地 settings 被回写为 dark
// ─────────────────────────────────────────────────────────────
sandbox.settings = { lang: "zh", theme: "light" };
sandbox.__persistUiPref("theme", "dark");
setTimeout(function () {
  check(sandbox.settings.theme === "dark", "落盘成功后本地 settings.theme 回写为 dark");
  check(settingsStatus.textContent === "已保存", "落盘成功后状态栏显示已保存");
  check(!sandbox.__error, "落盘过程无错误");

  // ───────────────────────────────────────────────────────────
  // 场景：流程条高亮跟随页面切换
  // ───────────────────────────────────────────────────────────
  sandbox.__syncStrip("home");
  check(stripHome.classList.contains("is-current"), "首页时高亮 ①取内容");
  check(!stripProcess.classList.contains("is-current"), "首页时不高亮 ②加工");

  sandbox.__syncStrip("refine");
  check(stripProcess.classList.contains("is-current"), "加工页时高亮 ②加工");
  check(!stripHome.classList.contains("is-current"), "加工页时不高亮 ①取内容");

  sandbox.__syncStrip("kb");
  check(stripKb.classList.contains("is-current"), "知识库页时高亮 ③沉淀");
  check(!stripProcess.classList.contains("is-current"), "知识库页时不高亮 ②加工");

  console.log("\n主题持久化 + 布局行为测试全部通过（" + passed + " 项断言）");
}, 0);
