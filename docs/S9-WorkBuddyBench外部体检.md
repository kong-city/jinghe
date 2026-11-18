# 精核 × WorkBuddy Bench Office 子集 · 能力对齐体检

- 生成方式：`tools/bench_office_check.py --outdir C:\Users\SONGWE~1\AppData\Local\Temp\1\jh-bench\out`
- 题目：`workbuddy-bench` Office v1.0 · `contract-extract-L3-014`
- 素材：45 个混合文件（docx/txt/json/xlsx/pdf），精核实跑提取

> **诚实边界**：bench 官方判分需 Docker 沙箱 + LLM judge + 特定产物格式（xlsx/json/pptx），精核产物形态不同。本报告**不是官方分数**，而是把 bench rubric 的考察维度逐条映射到精核产物中**确实存在的证据**，有证据记 1、无证据记 0。

## 对照结果

| bench 考察维度 | 对齐 | 精核产物中的证据 |
|---|---|---|
| 来源标识可追溯<br><sub>产物是否带 8 字段来源注释与稳定 doc_id（bench: source identity / trace key）</sub> | ✅ 对齐 | 40/40 产物带 src doc_id（覆盖率 100%） |
| 审计链完整<br><sub>产物是否带块级锚点，能从源文件定位到具体块（bench: audit trail / evidence keys）</sub> | ✅ 对齐 | 40/40 产物带块级锚点（覆盖率 100%） |
| 异常单列不伪装<br><sub>失败/加密/扫描件是否被明确标注且不产出空文件（bench: exception area with reason）</sub> | ✅ 对齐 | INDEX 标注类别 4 种；空产物 0 个 |
| 非占位有实质<br><sub>产物是否有真实正文而非标题/模板（bench: task-specific evidence not placeholders）</sub> | ✅ 对齐 | 40/40 产物含实质正文（覆盖率 100%） |
| 上下文不丢<br><sub>金额/日期/当事方等是否与来源同块保留（bench: values keep source context）</sub> | ✅ 对齐 | 含上下文字段的产物 34 个，均带锚点 |
| 汇总与明细一致<br><sub>MERGED/INDEX 与各 md 明细是否口径一致（bench: semantic consistency）</sub> | ✅ 对齐 | INDEX 与 MERGED 均存在；INDEX 记成功 40 件 |

**对齐率：6 / 6**

## 实跑摘要

- md 产物：40 份
- 唯一 doc_id 数：40（对应 src 注释）
- 带块级锚点产物：40 份
- provenance 条目：45

