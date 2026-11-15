# S2b · `.md` → `.docx` 导出 验收与确认闸门

> 阶段：S2b（七阶段路线图 S2 的二期） · 日期：2026-11-15 · 版本：v0.4.5
> 前置：S0 / S1 / S2a 已由用户逐阶段确认，`docs/CAPABILITY_CONTRACT.md` 生效（本阶段升至 v0.4）
> **状态：已完成，停在闸门，不进入 S3**

---

## 一、本阶段目标

把阶段 1 提取得到的 Markdown（默认 `MERGED.md`）导出成**真正可被 Word 打开的 `.docx`**，放开界面上从 v0.3.0 起就一直禁用的「导出 Word（规划中）」占位按钮。

四条硬约束：

1. **零第三方依赖**：不引 python-docx / lxml，不需要安装 Word 或 LibreOffice，不把外部工具冻进 exe。
2. **输入只读**：`MERGED.md` 与 `out/md/*.md` 全程只读；产物只落 `out/derived/`。
3. **出处不丢**：8 字段 `src` 来源注释与块级锚点必须随导出保留，不能因为「Word 看不见 HTML 注释」就丢链。
4. **诚实降级**：任何失败都显式回显，不产出空 `.docx`、不留半成品、不伪装成功。

`SPEC.md` 与 `extract.py` 主流水线**一字未改**；`test_06` / `test_11` 原样保留。

---

## 二、交付内容

| 位置 | 作用 |
| --- | --- |
| `word_export.py`（新） | 纯标准库 OOXML 生成：8 个包部件、Markdown 块解析、行内格式拆 `w:r`、XML 转义与非法控制字符剔除、`.part` 原子替换、provenance 追加 |
| `format_registry.py` | 新增 `WORD_EXPORT_INPUT_EXTS = {".md", ".markdown"}` 与 `is_word_export_input()`；`WORD_EXPORT_SUFFIX = ".docx"` 早于 S1 登记，本阶段启用 |
| `app.py` | `POST /api/word/export` + `_api_word_export()`；`/api/tools/probe` 顶层增量字段 `word_export`；污染冻结盘时落 `[ERROR]` 运行日志 |
| `ui/index.html` / `ui/app.js` | 「导出 Word」按钮去掉 `is-soon` / 恒禁用 / 「规划中」文案；新增 `doWordExport()` 逐条回显；工具状态行追加导出能力 |
| `build.spec` / `tools/check_release.py` | `hiddenimports` 与门禁 ⑦ 编译列表纳入 `word_export.py` |
| `media_tools.py` | 仅订正 `capabilities()` 的注释（逻辑零改动），说明它是被锁死的 S1 占位清单 |
| 文档 | 契约升 **v0.4**（7 条裁决）、`CHANGELOG.md` 与「附：v0.4.5」、本报告 |

### OOXML 包部件（最小可用集）

```
[Content_Types].xml
_rels/.rels
word/document.xml
word/_rels/document.xml.rels
word/styles.xml          # Normal / Heading1-6 / ListParagraph / Quote / CodeBlock / SourceNote
word/settings.xml
docProps/core.xml        # dc:description 写 src 注释原文
docProps/app.xml
```

`styles.xml` 的 `docDefaults` 把中文字体固定为 `Microsoft YaHei`；`document.xml` 的 `body` 以空段落收尾（表格后不直接接 `sectPr`，否则 Word 可能拒绝打开）。

### Markdown → Word 映射

一至六级标题、普通段落、有序 / 无序列表、引用、围栏代码块、水平线（下边框）、真实 `w:tbl` 表格（含边框与 `tblGrid`）；行内 `**粗体**` / `*斜体*` / `` `等宽` `` / `~~删除线~~` 拆成独立 `w:r`。所有文本经 XML 转义，并剔除 XML 1.0 非法控制字符（否则 Word 会判定文件损坏）。

---

## 三、产物契约：出处不丢的双保险

| # | 措施 | 可验证方式 |
| --- | --- | --- |
| ① | 每条 `<!-- source: … -->` / `<!-- src: … -->` / `<!-- anchor: … -->` 按**原文**渲染成 `SourceNote` 段落，位置与顺序不变 | `word_input.parse_ooxml()` 反向读回，文本里能找到三类注释与完整 64 位 sha256 |
| ② | `src` 注释原文写入 `docProps/core.xml` 的 `dc:description` | 解 zip 读 core.xml，含 `src:` / `sha256:` |
| ③ | 文档开头「导出信息」区块列源文件 / doc_id / sha256 / 大小 / 转换器 / 生成时间 / 溯源注释数 | 反向解析的首批段落 |
| ④ | `out/derived/<doc_id>.docx` + `provenance_media.json`（**追加**而非覆盖 S2a 历史条目） | 连续跑 S2a → S2b 后条目数 ≥ 2 |

`doc_id` 取源 `.md` 字节 sha256 前 12 位，同名导出天然幂等。

---

## 四、关键架构裁决

**1. `media_tools.capabilities()` 不改写。** 它本来就有 `word_export` 占位条目，且被 `test_33` 的 `all(not v["enabled"] for v in caps.values())` 锁死为「全部未启用」。S2b 若把它改成 `True`，既有 64 个断言立刻变红。因此延续 S2a 裁决：**占位清单保持原样，真实能力状态走 `/api/tools/probe` 顶层增量字段 `word_export`**；UI 读顶层字段。本轮只订正该函数的注释说明，逻辑零改动。

> 阅读探测响应时请以顶层 `word_export.enabled` 为准；`capabilities.word_export.enabled=false` 仅表示 S1 占位尚未接入，二者并不矛盾。

**2. 默认输入只读自动收集。** 用户点「导出 Word」时常未显式选 `.md`，后端按 `MERGED.md` → `out/md/*.md`（上限 20）只读收集，前端只要给了输出目录即可用。绝不因为「省事」去改写 `MERGED.md`。

**3. 空输入零副作用。** 没有任何逐条结果时不写 `provenance_media.json`，连 `derived/` 目录都不创建；有结果（哪怕全失败）才在 derived 区留痕。

**4. 产物区与冻结盘严格隔离。** 写前后用 `media_runtime.frozen_snapshot()` 比对；若被污染，端点落 `[ERROR]` 运行日志。测试同时校验 `md/` 实盘文件名与 `MERGED.md` 内容字节不变。

---

## 五、验收记录

| 项 | 命令 / 手段 | 结果 |
| --- | --- | --- |
| 全量单元测试 | `python -m unittest -v test_extract test_app` | **66/66 OK**（160.531s），新增 `test_37` / `test_38`，既有 64 个断言零回归 |
| 发版门禁 | `python tools/check_release.py --no-exe` | **9/9 通过** |
| 冻结内核 | `git diff -- SPEC.md`、`git diff --stat -- extract.py` | 验收时均为空；随后仅按发版规则推进版本号 |
| OOXML 完整性 | zipfile 打开 + `testzip()` + 逐个 `ET.fromstring` | 8 部件齐全、无损坏成员、全部 XML 合法 |
| 出处闭环 | `word_input.parse_ooxml()` 反向读回 | `source` / `src` / `anchor`、中文、`& < > " ' %`、代码块、表格全部保留 |
| 对账盘隔离 | 写前后 `frozen_snapshot` + `md/` 实盘数 + `MERGED.md` 内容 | 完全一致；`.part` 零残留 |
| 诚实降级 | 不存在 / 非 `.md` / 空白正文 / 超 2 万行 | 四项全部 `ok:false`，零 `.docx` 产出 |
| 部分成功 | 混合 1 个有效 `.md` + 1 个 `.txt` | `ok:true` + `failed=1` + 显式 `warning` |
| HTTP 契约 | 真实起服务请求 `/api/word/export` | 200 + derived 产物；空输入诚实失败；未知端点 404 JSON |
| 冻结态打包 | `dist_v045/Jinghe.exe --cli --version`、实起服务探测 | 见下方「发版」 |

### 发版

- 版本推进 **v0.4.5**（仅版本元数据与文档同步后打包），`CHANGELOG.md` 与「附：v0.4.5」同步。
- 按长期规则：打包单文件 exe → 冻结态实起服务验证新模块进包 → push `main` → 推 `v0.4.5` tag → 核对 CI 两作业与 Release 的 `Jinghe.exe` 资产。

---

## 六、确认闸门

**S2b 到此为止，不进入 S3。** 需确认三件事：

1. 导出 `.docx` 的结构与「出处不丢」的双保险（SourceNote 段落 + core.xml description）是否认可；
2. 默认输入（未选文件时只读收集 `MERGED.md`）、8 MB / 2 万行上限、以及「`capabilities()` 占位清单不改写、真实状态走顶层字段」的裁决是否认可；
3. 是否开工 **S3 · 音频 → `.md`**：ASR 适配器与时间戳、缺引擎诚实降级、绝不产出伪转写；**视频红线由 S4 独立 handler 处理，不复用音频路径**。

确认后回「开工」即可；每到一个闸门仍会停下来等确认。

---

## 附：仍挂账的漂移与遗留

- D3：`SPEC.md` 记 8 个端点、实际更多 —— 规格冻结不修订。
- D4：UI 路线图把阶段 3 标「已交付」—— 待 S3/S4 落地后订正。
- D5：私有仓库导致匿名「检查更新」仍 404 —— 按契约挂在 S6 单独决策（公开仓库 / 公开版本清单 / 只读 token 三选一）。
- `/api/transcribe` 仍是空心占位；`test_06` / `test_11` 守护阶段 1 冻结分流，永不改写。
