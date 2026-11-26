# v1.7.2 · OCR 质量与并发优化说明

> 日期：2026-11-26　基线：v1.7.1 → v1.7.2
> 约束：冻结内核 `extract.py` 主流水线一行不动（版本号行随升号变化除外）
> 用户决策：并发数按 CPU 核数自动（上限 4）；置信度"记录 + 低置信提示"，不阻断产物

---

## 一、修了什么（4 项确定性缺陷）

### 1. OCR 文本没清洗 → 现在接入离线清洗
**缺口**：`tools/clean_ocr.py`（满页水印过滤 + 11 条高置信误识修正 + 断行折叠）和
`check_ocr_quality.py` 全项目无运行时调用，OCR 原始文本直接写 md，水印/误识全保留。

**改法**：
- `tools/ocr_worker.py` 新增 `_load_cleaner()`，优先 import 项目现成的 `clean_ocr.clean()`，
  缺失时退化为内置最小清洗（控制字符清理 + 空行折叠）；
- `build.spec` datas 增加 `tools/clean_ocr.py`，保证打包态 worker 能导入；
- worker 在写出前调用 cleaner，产出即干净文本。

### 2. 置信度被丢弃 → 现在记录 + 低置信提示
**缺口**：`ocr_worker.py` 只取 RapidOCR 的 `item[1]` 文本，`item[2]` 置信度全丢；
"认清了"和"蒙对了"无法区分。

**改法**：
- worker 新增 `_confidence_of()`，按页算平均置信度与有效行数；
- 写出旁车 `<out.txt>.meta.json`，含 `avg_confidence` / `low_confidence_pages` / 各项统计；
- `pdf_ocr._read_quality()` + `_quality_hint()` 读回并转成日志文案
  （如"平均置信度 0.55，低置信页 3,7（建议复核）"）；
- 低置信**只提示不阻断**，符合"诚实降级、不假成功"契约。

### 3. 部分乱码被当成成功 → 现在精确强制重跑
**缺口**：内核质量门禁 `len>=40 且合理字符占比>=0.6` 是二值判断；"部分乱码但过 0.6"
的件会产出 >40 字 md，OCR 后处理因"产物已存在"直接跳过，乱码留在成品里。

**改法**：
- `ocr_pdf_to_md(pdf_path, outdir, force=False, max_pages=0)` 新增 `force` 参数：
  - `force=False`：保持旧行为（已有 >40 字产物跳过）；
  - `force=True`：忽略已有产物强制 OCR 覆盖，并写 `<!-- ocr: ... -->` 溯源注释。
- `app.py` 用 `_ocr_degraded_names()`（读 provenance）识别 CID 降级 / 疑似扫描件，
  这些件传 `force=True` 强制重跑。

### 4. 大文件内存峰值 → 现在逐页释放像素缓冲
**缺口**：worker 每页 `get_pixmap()` 后 `pix` 常驻，随页数线性推高内存峰值。

**改法**：`del pix` / `del img_bytes` 在每页 OCR 后立即释放；OCR 引擎仍只初始化一次
（避免重复加载模型的更大开销）。

---

## 二、优化了什么（多文件并发转换）

**改法**（全部在 `app.py` OCR 后处理层，不动内核）：
- 新增 `_ocr_parallel_limit(paths)`：并发数 = `min(CPU核数, 4, 文件数)`；单文件串行，
  避免小批量开子进程的反而更慢；
- 新增 `_ocr_one()` / `_log_ocr_result()`：单件 OCR 包装 + 日志落地；
- 多 PDF 时用 `ThreadPoolExecutor` 并行派发独立 OCR 子进程，`as_completed` 收集结果；
- `Job.add()` 自带 `threading.Lock`，日志序号唯一（顺序可能交错，属可接受）。

**为什么是 4 路上限**：每个 OCR 子进程加载 RapidOCR 模型约 200-400MB，8 路并发在
8GB 内存机器上会吃紧。按 CPU 核数自适应兼顾速度与内存。

**实测环境**：本机 OCR 组件未安装（`available=false`，符合"不主动下载用于测试"约定），
故并发路径用 mock 单测守护（`test_v172_ocr_quality` 10 项），未做真实多 PDF 跑批。

---

## 三、验证

| 项 | 结果 |
|---|---|
| 语法检查（app.py / pdf_ocr.py / ocr_worker.py / clean_ocr.py） | 全过 |
| OCR 守护测试（test_v150_ocr + test_v10_features） | 55 项全过 |
| 新增测试（test_v172_ocr_quality） | 10 项全过 |
| 全量 unittest | 445 项全过（2m19s） |
| 发版门禁 | 16 项全过 / 0 失败 |
| CI 测试模块 | 25 个（新增 test_v172_ocr_quality 已同步进 ci.yml） |
| 置信度旁车读取（真实函数实测） | avg / 低置信页 / 提示文案正确 |
| 清洗链路（模拟 OCR 结果实测） | 水印行被删、正文保留、旁车写出正确 |

新增测试守护：置信度解析、清洗器、随包携带、force 覆盖/跳过语义、并发路数、
OCR 块诊断锚点、冻结内核零改动（排除版本号行）。

---

## 四、风险提示与常见坑

1. **内核冻结**：`extract.py` 主流水线一行不能动；本轮只改了版本号行（升号必需），
   `test_v172_ocr_quality::test_10` 守护。
2. **质量门禁阈值别调**：0.6 / 5% 是踩过坑的 empiric 值，代码注释明确警告调高会误伤
   正常子集字体。本轮没动。
3. **OCR 组件版本未锁定**：历史发生过 onnxruntime DLL 初始化失败。本轮没装组件、
   没锁版本，风险仍在；下次动 OCR 依赖时优先锁版本。
4. **force=True 会覆盖已有 md**：只对 provenance 标记降级的件启用，其他件不覆盖；
   覆盖前不备份（产物可由原 PDF 重跑恢复）。
5. **日志顺序可能交错**：并发下 `_log_ocr_result` 的调用顺序不保证与输入顺序一致，
   但事件序号唯一、内容完整。
6. **低置信提示非门禁**：低于 0.60 只提示复核，不阻断产物——这是用户选择，避免
   误伤正常扫描件。

---

## 五、变更文件清单

| 文件 | 改动 |
|---|---|
| `tools/ocr_worker.py` | 清洗接入 + 置信度旁车 + 逐页释放内存 |
| `media/pdf_ocr.py` | 读置信度 + force/max_pages 参数 + 溯源注释；版本 0.2.0→0.3.0 |
| `app.py` | OCR 后处理并发 + 降级件 force 重跑 + 置信度日志 |
| `build.spec` | datas 增加 tools/clean_ocr.py |
| `.github/workflows/ci.yml` | 测试模块 24→25 |
| `test_v172_ocr_quality.py` | 新增 10 项守护测试 |
| 7 个版本点 | 1.7.1 → 1.7.2（`bump_version.py` 自动同步） |

**未提交、未 push、未发版**——按约定等用户明确指令。
