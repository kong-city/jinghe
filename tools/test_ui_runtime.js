/* 真运行时行为测试（v1.7.0 界面改造）：在 VM 里真实执行 renderFileList()
 * 与 renderKbSource()，喂给最小 DOM stub，断言逐文件诊断徽标与同源块节点
 * 确实被创建、文案经 tr() 翻译、点选同源块会切换 activeId。
 *
 * 由 test_ui_runtime.py 通过 node 调用；退出码 0 = 全部通过。
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

function extractFn(name) {
  const re = new RegExp("function " + name + "\\s*\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n  \\}");
  const m = js.match(re);
  if (!m) throw new Error("无法抽取函数 " + name);
  return m[0];
}

const i18nDecl = extractBalanced(i18nSrc, "window.JINGHE_I18N =")
  .replace("window.JINGHE_I18N =", "var I18N =");
const KIND_DIAG_DECL = extractBalanced(js, "var KIND_DIAG =");
const KIND_CLASS_DECL = extractBalanced(js, "var KIND_CLASS =");

// ---- 最小 DOM stub：支持 createElement/appendChild/addEventListener/classList ----
function makeNode(tag) {
  return {
    tag: tag || "div",
    children: [],
    attrs: {},
    _text: "",
    _listeners: {},
    className: "",
    type: "",
    checked: false,
    disabled: false,
    hidden: false,
    title: "",
    get textContent() { return this._text; },
    set textContent(v) { this._text = String(v); this.children = []; },
    setAttribute(k, v) { this.attrs[k] = String(v); },
    getAttribute(k) { return this.attrs[k] !== undefined ? this.attrs[k] : null; },
    appendChild(c) { this.children.push(c); return c; },
    addEventListener(ev, fn) { this._listeners[ev] = fn; },
    classList: { toggle() {}, add() {}, remove() {} },
  };
}

const fileListNode = makeNode("ul");
const kbSourceNode = makeNode("div");
const fileTitleNode = makeNode("span");
const toggleNode = makeNode("button");
const checkWrapNode = makeNode("label");
const checkAllNode = makeNode("input");

const el = {
  fileList: fileListNode,
  fileListTitle: fileTitleNode,
  fileListEmpty: makeNode("div"),
  btnToggleFiles: toggleNode,
  fileCheckAllWrap: checkWrapNode,
  fileCheckAll: checkAllNode,
  kbSource: kbSourceNode,
};

const sandbox = {
  console,
  el: el,
  document: {
    createElement(tag) { return makeNode(tag); },
    getElementById() { return null; },
  },
  showNotice(msg) { sandbox.__notices.push(msg); },
  showError() {},
  __notices: [],
  // renderFileList 依赖的全局状态
  fileItems: [],
  fileChecked: [],
  FILE_LIST_MAX: 500,
  KIND_CLASS: null,
  KIND_DIAG: null,
  it_path_title(item) { return item.path || item.name || ""; },
  syncCheckAll() {},
  // renderKbSource 依赖
  kbView: { items: [], docs: [], activeDoc: "", activeId: "", mode: "browse" },
  kbTextOf(item) { return String(item.body || item.snippet || ""); },
  renderKbBlocks() { sandbox.__blocksRerendered = (sandbox.__blocksRerendered || 0) + 1; },
  api() { return Promise.resolve({ ok: true, opened: false }); },
  currentLang: "en",
};
vm.createContext(sandbox);

const code = [
  i18nDecl,
  "function tr(key) { var d = I18N[currentLang] || I18N.zh; return (d[key] !== undefined) ? d[key] : key; }",
  KIND_CLASS_DECL,
  KIND_DIAG_DECL,
  extractFn("renderFileList"),
  extractFn("renderKbSource"),
  "this.__renderFileList = renderFileList;",
  "this.__renderKbSource = renderKbSource;",
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

// ---- 场景 1：逐文件诊断徽标 ----
const dryRun = {
  ok: true,
  total: 3,
  items: [
    { name: "a.txt", kind: "文本类", path: "/a.txt" },
    { name: "b.pdf", kind: "富文档", path: "/b.pdf" },
    { name: "c.mp3", kind: "阶段3预留", path: "/c.mp3" },
  ],
};
sandbox.__renderFileList(dryRun);
const allFileNodes = flatten(fileListNode, []);
const badges = allFileNodes.filter(n => String(n.className).indexOf("file-diag") >= 0);
check(badges.length === 3, "预览 3 个文件 → 生成 3 个诊断徽标（实际 " + badges.length + "）");
check(badges[0].textContent === "Ready to extract", "英文界面：文本类徽标 = Ready to extract（实际 " + badges[0].textContent + "）");
check(String(badges[0].className).indexOf("diag-ok") >= 0, "文本类徽标带 diag-ok 语义色");
check(badges[1].textContent === "Enhanced parsing", "英文界面：富文档徽标 = Enhanced parsing");
check(badges[2].textContent === "A/V · needs tools", "英文界面：音视频徽标 = A/V · needs tools");
// 点徽标应弹诊断说明（英文）
if (badges[0]._listeners.click) badges[0]._listeners.click({ preventDefault() {}, stopPropagation() {} });
check(sandbox.__notices.length === 1 && sandbox.__notices[0].indexOf("dependency-free") >= 0,
  "点徽标弹出英文诊断说明");

// ---- 场景 2：同源块反向引用 ----
sandbox.kbView.items = [
  { id: "blk1", doc_id: "DOC_A", locator: "p1", body: "第一章内容" },
  { id: "blk2", doc_id: "DOC_A", locator: "p2", body: "第二章内容" },
  { id: "blk3", doc_id: "DOC_B", locator: "p1", body: "另一文档" },
];
sandbox.kbView.activeId = "blk1";
kbSourceNode.textContent = "";
sandbox.__renderKbSource();
const allKbNodes = flatten(kbSourceNode, []);
const relItems = allKbNodes.filter(n => String(n.className).indexOf("kb-rel-item") >= 0);
const relHeads = allKbNodes.filter(n => String(n.className).indexOf("kb-rel-head") >= 0);
check(relHeads.length === 1 && relHeads[0].textContent === "Blocks from same source · 1",
  "来源栏显示同源块标题（实际 " + (relHeads[0] && relHeads[0].textContent) + "）");
check(relItems.length === 1, "仅列出同 doc_id 的 1 个兄弟块（实际 " + relItems.length + "）");
check(relItems[0].textContent.indexOf("blk2") >= 0, "同源块项含兄弟块 id");
// 点同源块应切换 activeId 并触发块视图重渲染
if (relItems[0]._listeners.click) relItems[0]._listeners.click();
check(sandbox.kbView.activeId === "blk2", "点同源块后 activeId 切到 blk2");
check(sandbox.__blocksRerendered === 1, "点同源块触发块视图重渲染");

// 换到无兄弟块的场景
sandbox.kbView.activeId = "blk3";
kbSourceNode.textContent = "";
sandbox.__renderKbSource();
const noneNodes = flatten(kbSourceNode, []).filter(n => n.textContent === "No other blocks in this document");
check(noneNodes.length === 1, "无同源块时显示英文空态提示");

if (failures) {
  console.error("\n界面改造行为测试失败: " + failures + " 项");
  process.exit(1);
}
console.log("\n界面改造行为测试全部通过（12 项断言）");
