#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精核 · 多轮自我迭代提纯引擎（S11）。

用户诉求（2026-11-22）：在可信提纯之上增加「多轮自我迭代」——核心提取
不再是「一次性出结果」，而是逐轮以**上一轮核心为焦点**重新审视全文，
让真正的核心上浮、边缘噪声下沉，直到结果稳定或到达轮数上限。

**不造假红线（继承 S8，逐轮守住）**：
1. 每一轮的候选句子都来自 ``extract_engine.split_blocks/collect_sentences``，
   都是原文原句；焦点重排只改**排序权重**，绝不生成新句；
2. 每一轮产出都过 ``verify_traceable``，任一条对不上立即中止并回退到
   上一轮结果 —— 多轮迭代不会成为「越迭代越编造」的后门；
3. 只复用 ``extract_engine`` 的纯函数，不改冻结内核 ``extract.py``，也不
   改 ``extract_engine.py`` 的算法（该文件受 AST 测试锁定，仅允标准库导入）。

迭代语义：
    轮 1 = 全文 ``extract_core``（与旧行为完全一致，默认 1 轮时零行为变化）
    轮 N = 以轮 N-1 核心的关键词 + 二元组为焦点种子，对全文句子重打分：
           ``score = 中心度 × 结构倍率 × (1 + FOCUS_BOOST × 焦点命中率)``
           再跑一次 MMR 选 top_k（焦点命中率 = 句子二元组落在焦点集的比例）
    收敛 = 相邻两轮核心 text 集合的 Jaccard ≥ ``CONVERGE_JACCARD``
    早停 = 焦点集为空 / 回溯校验失败 / 到达轮数上限 / 收到 cancel 信号

确定性：全部纯函数计算，无随机、无网络、无第三方依赖；同输入同输出。
"""
from __future__ import annotations

import time

import extract_engine as X

# 默认 1 轮：与 S8 行为完全兼容（不显式开启时零变化）
DEFAULT_ROUNDS = 1
MIN_ROUNDS = 1
MAX_ROUNDS = 5
# 相邻两轮核心重合度达到此值即判收敛，提前停止
CONVERGE_JACCARD = 0.90
# 焦点命中率对分数的放大系数（保守：焦点只「加权」，不「造句」）
FOCUS_BOOST = 0.85
# 焦点种子上限：锐利优先，避免覆盖全语料导致「假迭代」
FOCUS_TOP = 12


def normalize_rounds(value) -> int:
    """把外部传入的轮数收敛到 [MIN_ROUNDS, MAX_ROUNDS] 的整数。

    保守解析：非整数 / 非法字符串一律回退默认值，绝不因脏配置崩掉任务。
    """
    try:
        n = int(value)
    except (TypeError, ValueError):
        return DEFAULT_ROUNDS
    if n < MIN_ROUNDS:
        return MIN_ROUNDS
    if n > MAX_ROUNDS:
        return MAX_ROUNDS
    return n


def normalize_jaccard(value) -> float:
    """收敛阈值钳制到 (0, 1]；脏值回退默认，避免比较时抛 TypeError。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return CONVERGE_JACCARD
    if v <= 0 or v > 1:
        return CONVERGE_JACCARD
    return v


def _focus_from(points: list[dict]) -> set[str]:
    """从上一轮核心提取**共识焦点**：在多条核心里共同出现的关键词。

    关键设计：不能用核心句的全部二元组当焦点 —— 那会覆盖语料的绝大多数
    gram，所有句子的命中率都接近，逐轮重排等于没发生（假迭代）。取而代之：
    * 只取上一轮已提炼的关键词（及其二元组，与句子 grams 同口径）；
    * 统计它们出现在**几条**核心里，优先取跨核心共识词（文档频次高）；
    * 上限 FOCUS_TOP 个，保证焦点锐利、命中率有区分度。
    """
    df: dict[str, int] = {}
    for p in points or []:
        seen: set[str] = set()
        for term in p.get("keywords") or []:
            t = str(term).strip()
            if not t:
                continue
            seen.add(t)
            seen.update(X.bigrams(t))
        for gram in seen:
            df[gram] = df.get(gram, 0) + 1
    if not df:
        return set()
    multi = [t for t, c in df.items() if c >= 2]
    pool = multi or list(df)
    pool.sort(key=lambda t: (-df[t], t))
    return set(pool[:FOCUS_TOP])


def _label_only(sents: list[dict]) -> set[int]:
    """与 ``extract_core`` 一致的准入规则：有下位正文承载的短标题不进候选。"""
    label_only: set[int] = set()
    for i, s in enumerate(sents):
        if not (s["is_heading"] and len(s["text"]) <= 6
                and not X._NUMERIC.search(s["text"])):
            continue
        following = False
        for j in range(i + 1, len(sents)):
            if sents[j]["block"] != s["block"]:
                following = True
                break
            if not sents[j]["is_heading"]:
                following = True
                break
        if following:
            label_only.add(i)
    return label_only


def _build_candidates(md_text: str) -> tuple[list[dict], int]:
    """构造**基线**候选集（不含焦点加成）；返回 ``(cands, 分句数)``。

    中心度/结构/关键词只算一次，逐轮只叠加不同的焦点权重 —— 这是「迭代」
    而非「反复重跑」的效率点，也让焦点加成只有一个计算位置、便于审计。
    """
    blocks = X.split_blocks(md_text)
    sents = X.collect_sentences(blocks)
    if not sents:
        return [], 0
    global_scores = X.keyword_scores(sents)
    vecs = X.sentence_vectors(sents, global_scores=global_scores)
    ranks = X.textrank(sents, vecs)
    max_rank = max(ranks) if ranks else 1.0
    excluded = _label_only(sents)

    cands: list[dict] = []
    for i, s in enumerate(sents):
        if i in excluded:
            continue
        r = (ranks[i] / max_rank) if max_rank else 0.0
        factor = X.structure_bonus(s, global_scores)
        base = r * factor
        grams = X._bigram_set(s["text"])
        reasons = []
        if r > 0:
            reasons.append("中心度 %.2f" % r)
        if s["is_heading"] and len(s["text"]) > 6:
            reasons.append("标题")
        if s["is_list"]:
            reasons.append("列表项")
        if factor >= 1.2:
            reasons.append("标题共现/位置")
        if X._NUMERIC.search(s["text"]):
            reasons.append("含数据")
        cands.append({
            "text": s["text"], "block": s["block"], "score": base,
            "reasons": reasons,
            "keywords": X.keywords_of_sentence(s, global_scores),
            "grams": grams,
        })
    return cands, len(sents)


def _points_from(picked: list[dict]) -> list[dict]:
    """把 MMR 选中的候选转成与 ``extract_core`` 同构的 points。"""
    points = [{
        "text": c["text"], "block": c["block"],
        "keywords": c["keywords"], "score": round(c["score"], 4),
        "reasons": c["reasons"],
    } for c in picked]
    points.sort(key=lambda p: (-p["score"], p["block"]))
    return points


def iterate_core(md_text: str, top_k: int = X.DEFAULT_TOP_K,
                 max_rounds: int = DEFAULT_ROUNDS,
                 converge_jaccard: float = CONVERGE_JACCARD,
                 cancelled=None) -> dict:
    """多轮自我迭代提纯主入口。

    参数：
        md_text: 源 Markdown（只读，不改一个字）
        top_k: 每轮入选核心条数
        max_rounds: 轮数上限，内部收敛到 [1, 5]；``1`` = 旧行为
        converge_jaccard: 相邻两轮重合度阈值，达到即收敛早停
        cancelled: 可选零参回调，返回 True 表示用户取消（在当前轮结束后停）

    返回：与 ``extract_core`` 同构（points/keywords/stats），另加：
        ``rounds``: 逐轮留痕 [{round, selected, focus, jaccard, converged, elapsed}]
        ``converged``: 是否因收敛而提前停止
    每轮 points 都过 ``verify_traceable``；失败则回退上一轮，绝不带病产出。
    """
    t0 = time.time()
    rounds_limit = normalize_rounds(max_rounds)
    converge_jaccard = normalize_jaccard(converge_jaccard)
    rounds_log: list[dict] = []
    converged = False
    cancelled_flag = False

    # ---- 轮 1：完全复用 extract_core，保证默认行为零变化 ----
    first = X.extract_core(md_text, top_k=top_k)
    points = first.get("points") or []
    stats = dict(first.get("stats") or {})
    keywords = list(first.get("keywords") or [])
    if not points:
        return {"points": [], "keywords": keywords, "stats": stats,
                "rounds": [], "converged": False}

    ok, why = X.verify_traceable(md_text, points)
    if not ok:  # 防御：基线本身异常，绝不继续迭代
        return {"points": [], "keywords": keywords,
                "stats": dict(stats, error=why), "rounds": [],
                "converged": False}
    prev_texts = {p["text"] for p in points}
    rounds_log.append({"round": 1, "selected": len(points), "focus": 0,
                       "jaccard": 1.0, "converged": False,
                       "elapsed": round(time.time() - t0, 3)})

    if rounds_limit <= 1:
        stats.update({"rounds": 1, "rounds_run": 1, "converged": False,
                      "elapsed": round(time.time() - t0, 3)})
        return {"points": points, "keywords": keywords, "stats": stats,
                "rounds": rounds_log, "converged": False}

    # 打分基线只算一次；逐轮只换焦点权重
    focus = _focus_from(points)
    cands, sent_count = _build_candidates(md_text)
    if not cands or not sent_count:
        stats.update({"rounds": rounds_limit, "rounds_run": 1,
                      "converged": False,
                      "elapsed": round(time.time() - t0, 3)})
        return {"points": points, "keywords": keywords, "stats": stats,
                "rounds": rounds_log, "converged": False}

    for n in range(2, rounds_limit + 1):
        if callable(cancelled) and cancelled():
            cancelled_flag = True
            break
        if not focus:
            break
        ts = time.time()
        # 按上一轮焦点重打分：基线分恒定，只叠加焦点命中率
        rescored = []
        for c in cands:
            grams = c["grams"]
            hit = (len(grams & focus) / len(grams)) if (grams and focus) else 0.0
            reasons = [x for x in c["reasons"]
                       if not x.startswith("焦点命中")]
            if hit > 0:
                reasons.append("焦点命中 %.0f%%" % (hit * 100))
            rescored.append(dict(c, score=c["score"] * (1.0 + FOCUS_BOOST * hit),
                                 reasons=reasons))
        picked = X.mmr_select(rescored, top_k)
        new_points = _points_from(picked)
        ok, why = X.verify_traceable(md_text, new_points)
        if not ok or not new_points:
            # 回溯失败 → 保留上一轮结果，本轮不产出（红线优先）
            rounds_log.append({"round": n, "selected": 0, "focus": len(focus),
                               "jaccard": 0.0, "converged": False,
                               "elapsed": round(time.time() - ts, 3),
                               "error": why or "焦点重排后无有效核心"})
            break
        texts = {p["text"] for p in new_points}
        sim = X.jaccard(prev_texts, texts)
        points = new_points
        prev_texts = texts
        focus = _focus_from(points)
        rounds_log.append({"round": n, "selected": len(points),
                           "focus": len(focus), "jaccard": round(sim, 4),
                           "converged": sim >= converge_jaccard,
                           "elapsed": round(time.time() - ts, 3)})
        if sim >= converge_jaccard:
            converged = True
            break

    stats.update({"rounds": rounds_limit, "rounds_run": len(rounds_log),
                  "converged": converged, "cancelled": cancelled_flag,
                  "elapsed": round(time.time() - t0, 3)})
    return {"points": points, "keywords": keywords, "stats": stats,
            "rounds": rounds_log, "converged": converged}


def render_rounds(md: str, result: dict) -> str:
    """在提纯产物末尾追加「迭代轨迹」区块（仅多轮时调用）。

    不动 ``extract_engine.render_md`` 的输出结构，保证原有产物契约与解析
    测试不受影响；追加内容只记录轮次、重合度、收敛状态，不含新事实。
    """
    rounds_log = result.get("rounds") or []
    if len(rounds_log) <= 1:
        return md
    stats = result.get("stats") or {}
    lines = ["", "## 迭代轨迹", "",
             "- 迭代轮数：%d（上限 %d）"
             % (int(stats.get("rounds_run") or 0),
                int(stats.get("rounds") or 0)),
             "- 收敛状态：%s" % ("已收敛（提前停止）" if result.get("converged")
                             else "未收敛（达上限或用户取消）"),
             ""]
    for r in rounds_log:
        bits = ["第 %d 轮" % int(r.get("round") or 0),
                "入选 %d 条" % int(r.get("selected") or 0)]
        if int(r.get("round") or 0) > 1:
            bits.append("与上轮重合 %.0f%%" % (float(r.get("jaccard") or 0) * 100))
            bits.append("焦点词 %d" % int(r.get("focus") or 0))
        if r.get("converged"):
            bits.append("**收敛**")
        if r.get("error"):
            bits.append("回退：%s" % r["error"])
        bits.append("%.3fs" % float(r.get("elapsed") or 0))
        lines.append("- %s" % " ｜ ".join(bits))
    lines.append("")
    lines.append("> 每轮核心均为原文原句，逐条可在原文逐字定位；"
                 "迭代只调整入选顺序与范围，不生成原文之外的内容。")
    lines.append("")
    return md + "\n".join(lines)
