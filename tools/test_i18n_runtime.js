/* 真运行时行为测试：从 ui/app.js 抽出 I18N 字典 + tr() + applyLang()，
 * 在 VM 中执行并喂给最小 DOM stub，断言切换语言后 DOM 真的变化。
 *
 * 由 test_i18n_runtime.py 通过 node 调用；退出码 0 = 全部通过。
 */
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(__dirname, "..");
const js = fs.readFileSync(path.join(ROOT, "ui", "app.js"), "utf8");
const i18nSrc = fs.readFileSync(path.join(ROOT, "ui", "i18n.js"), "utf8");

// 抽取：var I18N = {...};  （从 var I18N 到与之配对的 };）
function extractBalanced(src, startMarker) {
  const start = src.indexOf(startMarker);
  if (start < 0) throw new Error("未找到 " + startMarker);
  const objStart = src.indexOf("{", start);
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
    if (c === "{") depth++;
    else if (c === "}") { depth--; if (depth === 0) return src.slice(start, i + 1); }
  }
  throw new Error("括号未闭合: " + startMarker);
}

const i18nDecl = extractBalanced(i18nSrc, "window.JINGHE_I18N =");
// i18n.js 里字典是 window.JINGHE_I18N = {...}；VM 中先按 var I18N 绑定
const i18nAsVar = i18nDecl.replace("window.JINGHE_I18N =", "var I18N =");
const trFn = js.match(/function tr\(key\)\s*\{[\s\S]*?\n  \}/);
const applyFn = js.match(/function applyLang\(lang\)\s*\{[\s\S]*?\n  \}/);
if (!trFn || !applyFn) {
  console.error("无法从 app.js 抽取 tr()/applyLang() 函数体");
  process.exit(1);
}

// 最小 DOM stub
function makeNode(attrs) {
  return {
    attrs: Object.assign({}, attrs),
    textContent: attrs._text || "",
    getAttribute(k) { return this.attrs[k] !== undefined ? this.attrs[k] : null; },
    setAttribute(k, v) { this.attrs[k] = v; },
    checked: false,
  };
}
const navNode = makeNode({ "data-i18n": "nav.home", _text: "首页" });
const cnTextNode = makeNode({ "data-i18n": "保存设置", _text: "保存设置" });
const phNode = makeNode({ "data-i18n-ph": "输出目录", placeholder: "输出目录" });
const ariaNode = makeNode({ "data-i18n-aria": "输入文件或文件夹路径", "aria-label": "输入文件或文件夹路径" });
const titleNode = makeNode({ "data-i18n-title": "主导航", title: "主导航" });
const allNodes = [navNode, cnTextNode, phNode, ariaNode, titleNode];

const byAttr = (name) => allNodes.filter(n => n.getAttribute(name) !== null);
const documentStub = {
  documentElement: makeNode({}),
  querySelectorAll(sel) {
    const m = sel.match(/^\[([^\]]+)\]$/);
    return m ? byAttr(m[1]) : [];
  },
  getElementById() { return null; },
};

const sandbox = {
  document: documentStub,
  console,
};
vm.createContext(sandbox);
vm.runInContext(
  i18nAsVar + "\n" + trFn[0] + "\n" + applyFn[0] + "\n" +
  "var currentPage = 'home';\n" +
  "var el = { pageTitle: null, pageSub: null, setLangZh: null, setLangEn: null };\n" +
  "this.__applyLang = applyLang;\n",
  sandbox
);

let failures = 0;
function check(cond, msg) {
  if (cond) console.log("  PASS " + msg);
  else { console.error("  FAIL " + msg); failures++; }
}

// 切英文
vm.runInContext("__applyLang('en')", sandbox);
check(navNode.textContent === "Home", "nav.home 英文后 textContent = Home (实际: " + navNode.textContent + ")");
check(cnTextNode.textContent === "Save settings", "中文原文 key 英文后 = Save settings (实际: " + cnTextNode.textContent + ")");
check(phNode.getAttribute("placeholder") === "Output directory", "placeholder 英文后 = Output directory");
check(ariaNode.getAttribute("aria-label") === "Input file or folder path", "aria-label 英文后 = Input file or folder path");
check(titleNode.getAttribute("title") === "Main navigation", "title 英文后 = Main navigation");
check(documentStub.documentElement.getAttribute("lang") === "en", "html lang 属性 = en");

// 切回中文（tr fallback 应返回中文原文）
vm.runInContext("__applyLang('zh')", sandbox);
check(navNode.textContent === "首页", "切回中文 nav.home = 首页");
check(cnTextNode.textContent === "保存设置", "切回中文正文 = 保存设置（fallback 返回 key 本身）");
check(phNode.getAttribute("placeholder") === "输出目录", "切回中文 placeholder = 输出目录");
check(documentStub.documentElement.getAttribute("lang") === "zh-CN", "html lang 属性 = zh-CN");

if (failures) {
  console.error("\n行为测试失败: " + failures + " 项");
  process.exit(1);
}
console.log("\n行为测试全部通过（10 项断言）");
