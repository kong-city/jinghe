# 精核 · 版本迭代契约

> 机器可读规则见 [`version-policy.json`](version-policy.json)；判定器见
> [`tools/version_check.py`](tools/version_check.py)。本文件是人类可读说明。
> 两终端共用同一套规则，**每次改代码/上传前都必须读**。

## 为什么需要这份契约

两个终端都通过 GitHub 连接器操作同一仓库。如果上传代码却不改版本号，
另一终端**无法凭任何信号判断代码已变更**，就会重复劳动或用旧代码覆盖。
因此定下一条硬约束：

> **上传必升号**：本地版本号必须严格大于 GitHub 上的 latest，否则拒绝上传。
> 版本号递增 = "代码有变更，请拉取"的信号。

## 版本真源

- **唯一真源**：`extract.py` 的 `__version__`
- 其它文件（CHANGELOG、使用说明、契约状态行）都是派生，**不得手写第二份**
- 规格版本 `SPEC.md` 的 v2.x 是独立轨道，**与软件版本永不互推**

## 升号规则（上传时按改动类型选）

**每段上限 9，满 9 自动进一位并把本段归 0**（用户 2026-11-19 裁决）：

```
0.7.8  --patch-->  0.7.9
0.7.9  --patch-->  0.8.0     ← 不是 0.7.10
0.8.9  --patch-->  0.9.0
0.9.9  --patch-->  1.0.0
```

因此版本号里**不会出现 0.7.10 这类号**，每段恒为 0–9。

| 改动类型 | 规则 | 例子 |
|---|---|---|
| 修 bug / 文案 / 测试 / 文档 / 配置 | **patch +1**（满 9 进 minor） | 0.7.8 → 0.7.9；0.7.9 → 0.8.0 |
| 新增模块 / 端点 / 能力 | **minor +1，patch 归零**（满 9 进 major） | 0.7.9 → 0.8.0；0.9.9 → 1.0.0 |
| 冻结契约破坏 / 架构变更 / 产物不兼容 | **major +1**，minor/patch 归零 | 0.7.0 → 1.0.0 |

拿不准时问判定器：`python tools/version_check.py suggest minor`。

## 一键升号（每次改动必做）

**不要手动改版本号** —— 用工具，它会自动同步真源 + 6 个派生点并确保不撞号：

```bash
python tools/bump_version.py patch --reason "修 XX bug"
python tools/bump_version.py minor --reason "新增 XX 能力"
python tools/bump_version.py major --reason "架构级变更"
```

工具会：① 按 `version-policy.json` 规则算号；② **联网核对 GitHub latest，
若候选号仍 ≤ 远端就自动 +1 顶上去**（数学上杜绝撞号）；③ 同步全部当前版本标记：
`extract.py`（真源）、`CHANGELOG.md`、`使用说明.md`、`electron/package.json`、
`electron/package-lock.json`（顶层 + `packages[""]`）、`electron/README.md` 标题、
`开发线说明.md`（目录表 + 当前状态）。历史记录与依赖版本号一律不动。
`tools/check_release.py` 会逐项校验，漂移即失败。预览用 `--dry-run`。
离线时保守 +1 并提示人工确认。

**为什么每次改动都要升号**：本地与远端共用一套版本号，若上传时版本没变，
`for-upload` 会拒绝（另一终端也无法凭版本识别代码变更）。升号是上传的通行证。

## 两个必做检查

**改代码前**：
```bash
python tools/version_check.py before-change
```
- 远端有新提交 → 先 `git pull --ff-only origin main`，再改
- 本地领先 → 正常改（上传仍需用户明确指令）
- 同步 → 直接改

**上传前**：
```bash
python tools/version_check.py for-upload
```
- 本地版本必须 **严格大于** GitHub latest，否则 `[BLOCK]` 拒绝
- 网络失败也拒绝（宁可不动，不可盲传）

## 双终端协作流程

```
终端 A 改代码 → 升号 → 上传 → GitHub latest 变新
                                    ↓
终端 B before-change 检测到远端领先 → 拉取 → 在新版本上继续改
```

版本号是主信号，commit 差距（`git rev-list --left-right --count`）是辅助信号，
两者都看才稳妥。

## 人工兜底

判定器只是护栏，最终由**发版人确认**：升号是否符合改动类型、
CHANGELOG/使用说明是否同步、门禁是否全绿。机器算号，人把关出口。
