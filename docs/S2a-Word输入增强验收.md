# S2a · Word → .md 输入增强 验收与确认闸门

> 阶段：S2a（七阶段路线图 S2 的一期） · 日期：2026-11-15 · 版本：v0.4.4
> 前置：S0 / S1 已由用户确认，`docs/CAPABILITY_CONTRACT.md` 生效（本阶段升至 v0.3）
> **状态：已完成，停在闸门，不进入 S2b**

---

## 一、本阶段目标

在 S1 地基上交付第一个真正面向用户的新能力：对所选 `.docx` / `.doc` 生成带**批注、修订、加密识别**的独立增强 Markdown。

关键前提：`.docx → .md` 在阶段 1 已支持且被冻结，S2a **不是**去改那条流水线，而是在后处理层另开一条匝道，只做「增量信息」的识别与呈现。四条硬约束：

1. `SPEC.md` 一字不改，`extract.py` 探测 / 分流 / 提取 / 汇总 / 对账主流水线零改动；
2. 零第三方依赖：`.docx` 全靠标准库 `zipfile` + `xml.etree.ElementTree`；
3. 加密文档单列「待人工授权」，**不破译、不询问口令、不盲重试**；
4. 产物只落 `out/derived/`，绝不写 `out/md/` / `INDEX.md` / `MERGED.md`。

---

## 二、交付清单

| 位置 | 作用 |
| --- | --- |
| `word_input.py`（新，约 460 行） | OOXML 增量解析、加密正向证据识别、`.doc` 本机预处理、产物渲染、临时目录三链、`inspect()` / `enhance()` / `capability()` |
| `format_registry.py` | 新增 `WORD_INPUT_EXTS` / `is_word_input()` / `word_kind()`；注册表仍是新能力支持格式的唯一写者 |
| `app.py` | 新增 `POST /api/word/inspect`、`POST /api/word/enhance`；`/api/tools/probe` 增加顶层 `word_input` 字段；`import word_input` |
| `ui/index.html` / `ui/app.js` | 后处理卡片新增「Word 输入增强」按钮；`hasWordInput()` / `doWordEnhance()`；工具状态行追加 `.docx` / `.doc` 可用性与原因 |
| `build.spec` / `tools/check_release.py` | `hiddenimports` 与门禁编译列表纳入 `word_input.py` |
| `test_app.py` | 新增 `test_35_s2a_word_input_contract` / `test_36_s2a_word_http_and_ui`；基线 62 → 64 |
| `docs/CAPABILITY_CONTRACT.md` | 升级 v0.3，追加 7 条 S2a 裁决；§8 表格 S2a 行标记「已完成 · 等确认（S2b）」 |
| `CHANGELOG.md` / `使用说明.md` | v0.4.4 条目与「附：v0.4.4」章节 |

### 端点契约

| 端点 | 语义 | 失败形态 |
| --- | --- | --- |
| `POST /api/word/inspect` | `{inputs:[...]}` → 只读预检，返回每项 `status` / `format` / 批注数 / 修订数 / 块数；**不写任何文件、不创建目录** | 文件不存在 → `失败`；后缀越界 → `不支持`；加密 → `待人工授权`；缺工具 → `未启用` |
| `POST /api/word/enhance` | `{inputs:[...], outdir:"..."}` → 写 `out/derived/<doc_id>.md` + `provenance_media.json` | 失败项不落空 md，只在 `results` 与 provenance 留痕；部分成功显式回 `warning`；全失败 `ok:false` + `error` |

### 产物结构

```
<!-- source: <文件名> | format: .docx | extracted: <时间> -->
<!-- src: doc_<12hex> | path: … | format: … | converter: … | extracted: … | size: … | sha256: <64hex> | anchors: block -->

# <文件名>
## 文档信息        （格式 / 大小 / 块数 / 批注数 / 修订数 / 预处理说明 / 正文视图口径）
<!-- anchor: doc_… | block: 1 -->
## 正文            （标题层级、表格；按「接受全部修订」呈现）
<!-- anchor: doc_… | block: 2 -->
## 批注            （作者 / 时间 / 锚定段落号 / 文本）
<!-- anchor: doc_… | block: 3 -->
## 修订            （插入 / 删除 / 移动 / 格式，含作者与时间）
```

`.doc` 的 `converter` 字段写真实探测到的 `LibreOffice <版本> + 精核 Word 输入增强 v1`，保证可回溯。写入用 `.part` + 原子替换。

---

## 三、架构裁决（S2a 新增，已写入契约 v0.3）

1. **不碰 S1 的硬断言**。`test_33` ⑤ 锁死「探测结果恰好 3 个工具」，`test_33` ⑥ / `test_34` ① 锁死 `capabilities()` 全部未启用。若把 `soffice` 塞进 `media_tools.TOOL_SPECS` 或把 `word_input` 塞进 `capabilities()`，既有 62 个断言立刻改红。裁定：新工具探测独立挂 `word_input.probe_soffice()`（内含 Windows 常见安装路径候选 + 进程内缓存），能力状态作为 `/api/tools/probe` 的**顶层增量字段 `word_input`** 返回。
2. **加密只认正向证据**。普通 `.doc` 本身就是 OLE 复合文档，不能因 OLE 魔数就判加密（否则所有旧格式都被误伤）。只有 OLE 目录里出现 `EncryptedPackage` / `EncryptionInfo`、ZIP 成员加密位、或加密信息成员才算命中。损坏容器归 `失败`，不归 `待人工授权`。
3. **正文 = 接受全部修订**。`w:del` 的文字是 `w:delText` 而非 `w:t`，天然不会混进正文；`w:ins` 的 `w:t` 被正文收录。修订明细另列区块，两条信息都不丢，且产物明确标注这一口径。
4. **临时目录三链齐备**。`soffice` 预处理的临时目录由父进程 `tempfile.mkdtemp()` 持有并登记 → `finally` 删除 → `atexit` 兜底 → 模块加载时清扫 24 小时前的过期孤儿。不靠单一 `atexit` 兜强杀场景（契约 §9）。
5. **不提前占用 S2b 名字**。`POST /api/word/export` 仍是候选；界面「导出 Word（规划中）」按钮保持禁用，S2b 再放开。

---

## 四、验收记录

| 项 | 命令 / 方式 | 结果 |
| --- | --- | --- |
| 全量单元测试 | `python -m unittest -v test_extract test_app` | **64/64 OK**（151.028s），既有 62 个断言零回归 |
| 发版门禁 | `python tools/check_release.py --no-exe` | **9/9**（版本 0.4.4 同步后复跑） |
| 冻结内核 | `git diff -- SPEC.md` / `git diff --stat -- extract.py` | 均为空 |
| OOXML 增量 | 现场构造含批注 / 插入 / 删除 / 表格的 `.docx` | 批注 1 条（锚定第 2 段）、插入 1 / 删除 1、正文块 3，全部正确 |
| 产物契约 | 读回 `derived/<doc_id>.md` | 8 字段 `src` 注释齐全、sha256 完整 64 位、块级锚点正则命中、四区块齐备 |
| 冻结对账盘 | 写前 / 写后 `frozen_snapshot()` 比对 | `frozen_unchanged=True`，`md/` 实盘数与 `INDEX.md` / `MERGED.md` 不变 |
| 加密 | 构造含 UTF-16LE `EncryptedPackage` 的 OLE 假文档 | `待人工授权`，`ok:false`，**零 md 产出** |
| 缺工具 | `mock` 掉 `probe_soffice` 为不可用 | `未启用`，零 md 产出；`capability().encryption.enabled` 恒 `false` |
| 损坏容器 / 空白文档 | `PK` 头坏包 / 无正文无批注无修订 | 分别 `失败` / 「拒绝写空 md」，均零 md 产出 |
| HTTP 端点 | 真实 `app.py` 子进程 + `urllib` | 预检不建目录；增强产出 derived 文件；3 文件混合批 `failed≥2` 且回 `warning`；未知端点 404 JSON |
| 冻结态打包 | `dist/Jinghe-0.4.4.exe --cli --version` + 实起服务请求 `/api/tools/probe` | 见下方发版记录 |

---

## 五、已知边界与风险

- **`.doc` 依赖本机工具**：未安装 LibreOffice 时该支路恒为「未启用」，这是用户选定的「本机可插拔工具」策略的预期行为，不是缺陷。软件不下载、不打包、不自动安装。
- **只支持 `.doc` / `.docx`**：`.xls` / `.ppt` / `.docm` 等仍登记为「候选」，S2a 遇到时诚实回「不支持」；宏与 VBA 不解析、不执行。
- **批注范围**：读 `word/comments.xml` 与正文 `commentRangeStart` 定位；不处理 `commentsExtended.xml` 的「已解决 / 回复串」等扩展语义，留待后续有明确需求再补。
- **修订范围**：插入 / 删除 / 移动 / 格式变更已覆盖；批注本身的修订、以及 `w:customXml*` 等深水区不在本阶段。
- **加密**：只识别、绝不破译；用户需自行在本机解密后重新选择文件。
- **仍挂账的漂移**：D3（`SPEC.md` 记 8 个端点、实际更多）、D4（UI 路线图把阶段 3 标「已交付」，待 S3/S4 落地后订正）、D5（私有仓库匿名「检查更新」404，S6 单独决策）。
- **S2b 尚未做**：`.md` → `.docx` 导出仍是禁用占位，界面「导出 Word（规划中）」不动。

---

## 六、确认闸门（S2a 到此为止）

**本阶段不进入 S2b。** 需用户确认三件事：

1. 增强产物的「文档信息 / 正文 / 批注 / 修订」四区块结构与 `converter` 字段口径是否认可；
2. 加密「待人工授权」与 `.doc` 缺工具「未启用」的降级表述是否符合预期（本机未装 LibreOffice 时，选中 `.doc` 应看到明确原因且零产物）；
3. 是否开工 **S2b · `.md` → `.docx` 导出**（纯标准库 `zipfile` + OOXML 独立模块，放开禁用按钮，产物可被 Word 打开且来源注释 / 锚点不丢）。

确认后回「确认，S2b 开工」即可；每到一个闸门都会停下等确认。
