#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精核 · 抽取式知识提纯引擎（S8a）。

用户诉求（2026-11-17）：**对内容核心提取，不能造假**。

本模块实现 A 档「可信提纯」：**只从原文里"捡"，绝不自己"造"**。

铁律：
1. 输出的每一条核心都是**原文的原样子串**（仅裁剪首尾空白），
   因此能在原文里定位 —— 结构上不可能编造；
2. 每条核心带块级锚点（``block_anchor``），回溯路径与 S7 体系一致；
3. 纯标准库：中文用**字符二元组**切分规避第三方分词器，
   图算法用 PageRank 幂迭代实现，无需 numpy/scipy/networkx。

算法流水线：
    分块 → 分句 → 二元组词表 → TF-ICF 关键词 → 句子相似度图
    → TextRank 中心度 → 结构/标题共现加权 → MMR 去冗余 → 核心条目

每个环节的分数都保留下来，最终给用户"这条为什么是核心"的理由。
"""
from __future__ import annotations

import math
import re
import time
from pathlib import Path

import media_runtime

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #
MAX_BLOCKS = 400
MAX_SENTENCES = 600
MAX_KEYWORDS = 8
DEFAULT_TOP_K = 8
MMR_LAMBDA = 0.72          # 相关性 vs 多样性的权衡
NEAR_DUP_THRESHOLD = 0.82  # bigram Jaccard 相似度超此值视为近似重复

# 中文停用词（覆盖虚词、常见套话、动词）；刻意保守：宁少勿多
STOPWORDS = frozenset(
    "的 了 和 是 在 我 有 就 不 人 都 一 一个 上 也 很 到 说 要 去 你 会 着 没有 看 好 自己 这 "
    "那 与 及 或 而 但 并 被 把 让 使 从 对 向 于 以 为 之 其 此 该 等 中 内 外 前 后 时 可 能 应 "
    "如果 因为 所以 然后 因此 但是 而且 并且 或者 以及 虽然 然而 于是 进行 通过 根据 按照 "
    "对于 关于 方面 情况 问题 方面 进行 实现 完成 具有 相关 一定 必须 需要 可以 我们 他们 "
    "这些 那些 这些 什么 怎么 因为 由于 从而 之后 之前 之间 更多 更好 以及 一样 一直 "
    "the a an of and or to in for is are was were be been by on at as with that this it "
    "from we you they i he she his her its not but if then else when while can may will "
    "would should could have has had do does did been more most some such only own same "
    "so too very just also into about over under again further once here there".split()
)

# 中文高频但有信息量的量词/代词补充过滤（避免二元组跨词切出垃圾）
_BAD_CHARS = frozenset("的了和是在有就不人都一上也很到说要去你会着看好这那与及或而但并被把让使从对向于以为之其此该等中内外前后时可应")

# 句子切分：中文标点 + 英文标点（保留终止标点本身）
_SENT_SPLIT = re.compile(r"(?<=[。！？!?；;])\s*|\n{2,}")
# 块边界：标题行 / 列表项 / 空行分段
_BLOCK_SPLIT = re.compile(r"\n\s*\n+")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
# 数字/日期/人名线索（提高句子信息量权重）
_NUMERIC = re.compile(r"\d")


# --------------------------------------------------------------------------- #
# 1. 分块与分句
# --------------------------------------------------------------------------- #
def split_blocks(md_text: str) -> list[dict]:
    """把 md 切成编号块（沿用 S7 的逐行切块口径，锚点语义一致）。

    返回 ``[{"n": 1, "text": "..."}, ...]``；n 从 1 开始，与 block_anchor 对齐。
    """
    blocks: list[dict] = []
    for raw in md_text.splitlines():
        s = raw.strip()
        if not s:
            continue
        if len(blocks) >= MAX_BLOCKS:
            break
        blocks.append({"n": len(blocks) + 1, "text": s})
    return blocks


def split_sentences(text: str) -> list[str]:
    """把一段文本切成句子；只做切分，不改任何字符（除裁剪首尾空白）。"""
    out: list[str] = []
    for piece in _SENT_SPLIT.split(text or ""):
        piece = piece.strip()
        if piece:
            out.append(piece)
    return out


def collect_sentences(blocks: list[dict]) -> list[dict]:
    """把块展开成句子列表，每句带其所属块号与结构特征。"""
    sents: list[dict] = []
    for b in blocks:
        btext = b["text"]
        is_heading = bool(_HEADING.match(btext))
        is_list = bool(_LIST_ITEM.match(btext))
        head_text = ""
        if is_heading:
            head_text = _HEADING.match(btext).group(2).strip()
        # 标题本身也是一句（它常是知识点）；剥离 Markdown 标记前缀，
        # 否则「## 技术架构」会把语法符号混进核心正文
        pieces = [(head_text or btext)] if is_heading else split_sentences(btext)
        for p in pieces:
            if len(sents) >= MAX_SENTENCES:
                return sents
            body = p.strip()
            if not body:
                continue
            sents.append({
                "idx": len(sents),
                "text": body,
                "block": b["n"],
                "is_heading": is_heading,
                "is_list": is_list,
                "heading": head_text,
                "pos_in_block": 0,
            })
    # 标注块内位置（首句 / 末句权重不同）
    per_block: dict[int, list[int]] = {}
    for s in sents:
        per_block.setdefault(s["block"], []).append(s["idx"])
    for _, idxs in per_block.items():
        if len(idxs) == 1:
            sents[idxs[0]]["pos_in_block"] = 0
            continue
        for k, i in enumerate(idxs):
            sents[i]["pos_in_block"] = k
    return sents


# --------------------------------------------------------------------------- #
# 2. 二元组词表（规避第三方分词器）
# --------------------------------------------------------------------------- #
def bigrams(text: str) -> list[str]:
    """字符二元组切分；中文连续片段用二元组，英文/数字按词切。

    刻意不做词级分词：中文词表会随领域失效，而二元组对"核心提纯""数据一致性"
    这类固定搭配的捕捉能力接近词级，且零依赖。
    """
    return [t for t, _, _ in term_items(text)]


def term_items(text: str) -> list[tuple[str, int, int]]:
    """候选词 + **半开区间跨度** ``(term, start, end)``。

    跨度用于「槽位冲突」消解：两个词若跨度重叠，说明它们抢同一处文字
    （典型如「核项」= 精核|项目 的边界碎片），只应保留其中一个。
    """
    out: list[tuple[str, int, int]] = []
    for m in re.finditer(r"[A-Za-z][A-Za-z0-9_.\-]*|\d+(?:\.\d+)*", text):
        w = m.group(0).lower()
        if len(w) >= 2 and w not in STOPWORDS:
            out.append((w, m.start(), m.end()))
    for m in re.finditer(r"[\u4e00-\u9fff]+", text):
        seg = m.group(0)
        base = m.start()
        if len(seg) == 1:
            if seg not in STOPWORDS and seg not in _BAD_CHARS:
                out.append((seg, base, base + 1))
            continue
        for i in range(len(seg) - 1):
            bg = seg[i:i + 2]
            if bg[0] in _BAD_CHARS or bg[1] in _BAD_CHARS:
                continue
            if bg in STOPWORDS:
                continue
            out.append((bg, base + i, base + i + 2))
    return out


# 领域词表（高置信词源）：技术文档核心概念常以固定词形出现，
# 命中即优先采用，天然避开二元组边界碎片。零依赖、可离线。
DOMAIN_LEXICON = frozenset([
    "核心提纯", "知识核心", "核心", "提纯", "精读", "修订", "补写", "改写", "原文",
    "架构", "分层", "模块", "接口", "端点", "契约", "产物", "派生", "冻结", "内核",
    "主流水线", "后处理", "编排", "适配器", "适配", "能力", "注册表", "探测", "降级",
    "后端", "本地", "云端", "离线", "隐私", "外传", "密钥", "脱敏", "校验", "门禁",
    "溯源", "回溯", "可回溯", "锚点", "块级", "来源", "出处", "注释", "字段",
    "依赖", "第三方", "零依赖", "体积", "打包", "安装", "下载",
    "模型", "摘要", "提纲", "要点", "关键词", "段落", "标题", "章节", "结构",
    "一致性", "不可变", "不变量", "红线", "边界", "隔离", "只读", "写入",
    "测试", "用例", "回归", "断言", "验收", "版本", "发版", "发布",
    "增量", "空心位", "占位", "诚实", "兜底", "回退", "策略",
    "阶段", "路线", "优先级", "裁决", "闸门", "确认", "收口", "主线",
    "缓存", "队列", "事件", "进度", "超时", "取消", "子进程", "进程树",
    "文件", "目录", "路径", "格式", "编码", "文本",
])


def lexicon_hits(text: str) -> list[tuple[str, int, int]]:
    """命中的领域词 + 跨度（长词优先，避免被短词抢占跨度）。"""
    hits: list[tuple[str, int, int]] = []
    taken: list[tuple[int, int]] = []
    for term in sorted(DOMAIN_LEXICON, key=len, reverse=True):
        start = 0
        while True:
            pos = text.find(term, start)
            if pos < 0:
                break
            end = pos + len(term)
            if not any(pos < e and s < end for s, e in taken):
                hits.append((term, pos, end))
                taken.append((pos, end))
            start = pos + 1
    return hits


def heading_terms(blocks: list[dict]) -> set[str]:
    """从标题与列表项里挖术语 —— 技术文档的概念名高度一致，是可靠词源。

    中文串**贪婪整取**（不切碎）：「数据一致性保障机制」应整体入池，
    切成「数据一致性保障机」反而制造跨词碎片。
    """
    terms: set[str] = set()
    for b in blocks:
        t = b["text"]
        m = _HEADING.match(t)
        head = m.group(2).strip() if m else (t if _LIST_ITEM.match(t) else "")
        if not head:
            continue
        head = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", head).strip()
        for seg in re.findall(r"[\u4e00-\u9fff]{2,}", head):
            terms.add(seg)
            if len(seg) >= 4:
                terms.add(seg[:4])
        for w in re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", head):
            terms.add(w.lower())
    return terms


def _spans_conflict(a: tuple[int, int], b: tuple[int, int]) -> bool:
    """半开区间跨度是否重叠（重叠 = 抢同一个槽位）。"""
    return a[0] < b[1] and b[0] < a[1]


def pick_terms(items: list[tuple[str, float, int, int, int]], limit: int) -> list[str]:
    """按分数挑词，并做**槽位冲突消解**（同句内重叠跨度只留高分者）。

    这样「精核」(0-2) 与「项目」(2-4) 可共存，而「核项」(1-3) 与两者都冲突被淘汰。

    **跨度是句内坐标**：句 1 的第 3 字与句 5 的第 3 字不是同一处文字，
    跨句比较毫无意义。故每个候选词都带所属句号 ``sid``，
    冲突判定**只在同一句内**进行。

    **更具体者优先**：两个词在同句内重叠且一个是另一个的子串时，
    保留**更长**的那个（「数据一致性保障机制」优于「一致性」），
    避免完整概念名被拆成信息量更低的碎片。

    items 元素：``(term, score, sid, start, end)``。
    """
    picked: list[str] = []
    used: list[tuple[int, int, int]] = []
    for term, score, sid, s, e in sorted(items, key=lambda x: (-x[1], x[0])):
        if len(picked) >= limit:
            break
        conflict = None
        for i, u in enumerate(used):
            if u[0] == sid and _spans_conflict((s, e), (u[1], u[2])):
                conflict = i
                break
        if conflict is not None:
            old = picked[conflict]
            # 长词覆盖短词：用更具体的概念名替换（保留位置与次序）
            if len(term) > len(old) and old in term:
                picked[conflict] = term
                used[conflict] = (sid, s, e)
            continue
        if any(term in p for p in picked):
            continue
        picked.append(term)
        used.append((sid, s, e))
    return picked


def term_freq(tokens: list[str]) -> dict[str, int]:
    tf: dict[str, int] = {}
    for t in tokens:
        tf[t] = tf.get(t, 0) + 1
    return tf


# --------------------------------------------------------------------------- #
# 3. TF-ICF 关键词
# --------------------------------------------------------------------------- #
def keyword_scores(sents: list[dict]) -> dict[str, float]:
    """TF-ICF：ICF = log(N / 出现在该词的不同块数)。

    块当作"类别"（ICF 的原始定义是类别频率），天然贴合分块结构：
    一个词若在每个块都出现 → 区分度低；只在少数块出现 → 区分度高。
    """
    if not sents:
        return {}
    n_blocks = len({s["block"] for s in sents})
    tf: dict[str, int] = {}
    df_blocks: dict[str, set] = {}
    for s in sents:
        toks = set(bigrams(s["text"]))
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
            df_blocks.setdefault(t, set()).add(s["block"])
    scores: dict[str, float] = {}
    for t, freq in tf.items():
        icf = math.log((n_blocks + 1) / (len(df_blocks[t]) + 1)) if n_blocks else 0.0
        # 词长加权：更长的二元组通常信息量更高
        length_bonus = 1.0 + 0.15 * (len(t) - 2)
        scores[t] = (1 + math.log(freq)) * max(icf, 0.0) * length_bonus
    return scores


def _first_positions(sents: list[dict]) -> dict[str, list]:
    """每个候选词的**首次出现位置**（句号 + 句内偏移）与出现次数，一次遍历建索引。

    槽位消解需要真实坐标；早期实现把位置统一凑到首句开头，
    导致同句之外的词互相「撞车」被误杀。这里改为记录真实命中位置。

    返回值：``{term: [freq, sid, start]}``（freq 为该词出现的句子次数）。
    """
    pos: dict[str, list] = {}
    for idx, s in enumerate(sents):
        for term, st, _en in term_items(s["text"]):
            cur = pos.get(term)
            if cur is None:
                pos[term] = [1, idx, st]
            else:
                cur[0] += 1
    return pos


def top_keywords(sents: list[dict], limit: int = MAX_KEYWORDS,
                 heads: set[str] | None = None) -> list[str]:
    """取全局 top 关键词。

    三路词源合并打分：**领域词表**（高置信）> **标题挖词**（概念名一致）> **二元组**（兜底），
    最后统一做槽位冲突消解（**同句内**重叠才判冲突），避免「核项」这类边界碎片入选。

    每路词源都必须携带**真实命中位置**（句号 + 句内偏移）：
    位置造假会让不同句的词互相冲突，把整片标题词误杀。
    """
    scores = keyword_scores(sents)
    positions = _first_positions(sents)
    items: list[tuple[str, float, int, int, int]] = []
    head_set = heads or set()

    # ① 领域词表：命中即给高权重（按其自身二元组分数的上限加成）
    term_hits: dict[str, list[tuple[int, int, int]]] = {}
    for idx, s in enumerate(sents):
        for term, st, en in lexicon_hits(s["text"]):
            term_hits.setdefault(term, []).append((idx, st, en))
    for term, spans in term_hits.items():
        base = max([scores.get(t, 0.0) for t in bigrams(term)] or [0.0])
        freq = len(spans)
        w = (base or 1.0) * (1 + math.log(freq)) * 2.6
        sid, st, en = spans[0]
        items.append((term, w, sid, st, en))

    # ② 标题挖词：概念名在正文反复出现 → 加权；位置取**真实命中句**
    for term in head_set:
        n = 0
        hit: tuple[int, int, int] | None = None
        for idx, s in enumerate(sents):
            p = s["text"].find(term)
            if p >= 0:
                n += 1
                if hit is None:
                    hit = (idx, p, p + len(term))
        if not n or hit is None:
            continue
        base = max([scores.get(t, 0.0) for t in bigrams(term)] or [0.0])
        w = (base or 0.6) * (1 + math.log(n)) * 1.8
        items.append((term, w, hit[0], hit[1], hit[2]))

    # ③ 二元组兜底（位置取首次真实命中）
    for term, sc in scores.items():
        hit = positions.get(term)
        if hit is None:
            continue
        freq, sid, st = hit
        # 全文只出现一次的二元组，几乎必然是跨词碎片（「只追」「录每」）；
        # 真正的概念要么在领域词表、要么在标题里（由 ①② 提供）。
        # 关键词要的是「能代表主题的词」，宁可少收也不放碎片。
        if freq <= 1 and term not in DOMAIN_LEXICON and term not in head_set:
            continue
        items.append((term, sc, sid, st, st + len(term)))

    return pick_terms(items, limit)


def keywords_of_sentence(sent: dict, global_scores: dict[str, float],
                         limit: int = 4) -> list[str]:
    """取某句自身的关键词（领域词优先 + 槽位冲突消解）。"""
    items: list[tuple[str, float, int, int, int]] = []
    for term, st, en in lexicon_hits(sent["text"]):
        base = max([global_scores.get(t, 0.0) for t in bigrams(term)] or [0.0])
        items.append((term, (base or 1.0) * 2.6, 0, st, en))
    for term, st, en in term_items(sent["text"]):
        if term in DOMAIN_LEXICON:
            continue
        items.append((term, global_scores.get(term, 0.0), 0, st, en))
    return pick_terms(items, limit)


# --------------------------------------------------------------------------- #
# 4. 句子相似度 + TextRank
# --------------------------------------------------------------------------- #
def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    small, large = (a, b) if len(a) <= len(b) else (b, a)
    dot = 0.0
    for k, v in small.items():
        w = large.get(k)
        if w:
            dot += v * w
    if not dot:
        return 0.0
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if not na or not nb:
        return 0.0
    return dot / (na * nb)


def sentence_vectors(sents: list[dict]) -> list[dict[str, float]]:
    """句向量 = 二元组 TF-IDF（用全局关键词分数做 IDF 近似）。"""
    global_scores = keyword_scores(sents)
    maxv = max(global_scores.values()) if global_scores else 1.0
    vecs: list[dict[str, float]] = []
    for s in sents:
        toks = bigrams(s["text"])
        tf = term_freq(toks)
        vec: dict[str, float] = {}
        for t, c in tf.items():
            idf = (global_scores.get(t, 0.0) / maxv) if maxv else 0.0
            if idf <= 0:
                continue
            vec[t] = (1 + math.log(c)) * idf
        vecs.append(vec)
    return vecs


def textrank(sents: list[dict], vecs: list[dict[str, float]],
             damping: float = 0.85, iterations: int = 40) -> list[float]:
    """PageRank 幂迭代（纯 Python，无第三方）。节点=句子，边=余弦相似度>0。"""
    n = len(sents)
    if n == 0:
        return []
    if n == 1:
        return [1.0]
    # 相似度矩阵（稀疏：只保留 > 0.05 的边，避免稠密计算）
    edges: list[list[tuple[int, float]]] = [[] for _ in range(n)]
    out_sum = [0.0] * n
    for i in range(n):
        vi = vecs[i]
        for j in range(i + 1, n):
            w = _cosine(vi, vecs[j])
            if w > 0.05:
                edges[i].append((j, w))
                edges[j].append((i, w))
                out_sum[i] += w
                out_sum[j] += w
    # 无边时退化为均匀分布
    if not any(out_sum):
        return [1.0 / n] * n
    rank = [1.0 / n] * n
    for _ in range(iterations):
        new = [(1.0 - damping) / n] * n
        for i in range(n):
            if out_sum[i] <= 0:
                # 孤立节点：把权重均分给所有节点
                for j in range(n):
                    new[j] += damping * rank[i] / n
                continue
            ri = rank[i]
            for j, w in edges[i]:
                new[j] += damping * ri * w / out_sum[i]
        delta = sum(abs(new[k] - rank[k]) for k in range(n))
        rank = new
        if delta < 1e-8:
            break
    return rank


# --------------------------------------------------------------------------- #
# 5. 结构加权
# --------------------------------------------------------------------------- #
def structure_bonus(sent: dict, global_scores: dict[str, float]) -> float:
    """结构先验（**倍率**，不是加法）。

    为什么是倍率：中心度是"内容重要性"，结构是"位置提示"。若用加法，
    短文档里中心度区分度低（多句相似度为 0、中心度同为 0.15），
    结构分会凌驾其上，把纯标题抬进核心、把实质正文压到末尾。
    倍率语义 = 结构只能**放大**内容本身的重要性，不能凭空造重要性。
    """
    factor = 1.0
    if sent["is_heading"]:
        # 标题是章节标签还是知识点？短标题（≤6 字且无数字）几乎必然
        # 有下位正文承载知识点，故不额外加成；长标题自带完整信息，适度放大。
        core_text = sent["text"]
        if len(core_text) <= 6 and not _NUMERIC.search(core_text):
            factor *= 1.00
        else:
            factor *= 1.25
    if sent["is_list"]:
        factor *= 1.20
    if sent["pos_in_block"] == 0:
        factor *= 1.12
    if _NUMERIC.search(sent["text"]):
        factor *= 1.10
    # 标题共现度：句子词与所在标题的词重合越多，越可能是该节核心
    if sent["heading"]:
        head_terms = set(bigrams(sent["heading"]))
        if head_terms:
            sent_terms = set(bigrams(sent["text"]))
            overlap = len(head_terms & sent_terms) / len(head_terms)
            factor *= (1.0 + 0.35 * overlap)
    # 过长的句子通常不是"核心点"，轻微惩罚
    length = len(sent["text"])
    if length > 160:
        factor *= 0.92
    if length < 8:
        factor *= 0.88
    return factor


# --------------------------------------------------------------------------- #
# 6. MMR 去冗余
# --------------------------------------------------------------------------- #
def _bigram_set(text: str) -> set[str]:
    return set(bigrams(text))


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if not inter:
        return 0.0
    return inter / float(len(a | b))


def mmr_select(cands: list[dict], k: int, lam: float = MMR_LAMBDA) -> list[dict]:
    """最大边际相关：兼顾相关性与多样性。"""
    if not cands:
        return []
    chosen: list[dict] = []
    pool = list(cands)
    while pool and len(chosen) < k:
        best = None
        best_score = -1.0
        for c in pool:
            if not chosen:
                score = c["score"]
            else:
                max_sim = max(jaccard(c["grams"], g["grams"]) for g in chosen)
                score = lam * c["score"] - (1 - lam) * max_sim
            if score > best_score:
                best_score = score
                best = c
        if best is None:
            break
        chosen.append(best)
        pool.remove(best)
    return chosen


# --------------------------------------------------------------------------- #
# 7. 主流程
# --------------------------------------------------------------------------- #
def extract_core(md_text: str, top_k: int = DEFAULT_TOP_K) -> dict:
    """抽取式核心提取主流程。

    返回 ``{"points": [{"text","block","keywords","score","reasons"}], ...],
              "keywords": [...], "stats": {...}}``。

    **每条 point 的 text 都是原文原样子串**，可在源文件中逐字定位。
    """
    t0 = time.time()
    blocks = split_blocks(md_text)
    sents = collect_sentences(blocks)
    if not sents:
        return {"points": [], "keywords": [], "stats": {"blocks": 0, "sentences": 0,
                                                      "elapsed": 0.0}}

    global_scores = keyword_scores(sents)
    vecs = sentence_vectors(sents)
    ranks = textrank(sents, vecs)
    heads = heading_terms(blocks)

    max_rank = max(ranks) if ranks else 1.0
    cands: list[dict] = []
    for i, s in enumerate(sents):
        r = (ranks[i] / max_rank) if max_rank else 0.0
        factor = structure_bonus(s, global_scores)
        # 中心度为主、结构为倍率：结构只放大内容重要性，不凭空创造重要性
        score = r * factor
        reasons = []
        if r > 0:
            reasons.append("中心度 %.2f" % r)
        if s["is_heading"] and len(s["text"]) > 6:
            reasons.append("标题")
        if s["is_list"]:
            reasons.append("列表项")
        if factor >= 1.2:
            reasons.append("标题共现/位置")
        if _NUMERIC.search(s["text"]):
            reasons.append("含数据")
        cands.append({
            "text": s["text"],
            "block": s["block"],
            "score": round(score, 4),
            "reasons": reasons,
            "keywords": keywords_of_sentence(s, global_scores),
            "grams": _bigram_set(s["text"]),
        })

    # 候选准入：纯章节标签（短标题，无数字）不进候选池。
    # 短标题几乎必然有下位正文承载知识点，把它当独立核心只会挤占名额；
    # 但若它**没有**下位正文（文档末尾的孤立标题），仍予以保留，避免丢信息。
    label_only = set()
    for i, s in enumerate(sents):
        if not (s["is_heading"] and len(s["text"]) <= 6
                and not _NUMERIC.search(s["text"])):
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
    filtered: list[dict] = []
    for i, c in enumerate(cands):
        if i in label_only:
            continue    # 有下位正文承载 → 纯标签，剔除
        filtered.append(c)

    picked = mmr_select(filtered, top_k)
    points = []
    for c in picked:
        points.append({
            "text": c["text"],
            "block": c["block"],
            "keywords": c["keywords"],
            "score": c["score"],
            "reasons": c["reasons"],
        })
    points.sort(key=lambda p: (-p["score"], p["block"]))
    return {
        "points": points,
        "keywords": top_keywords(sents, heads=heads),
        "stats": {
            "blocks": len(blocks),
            "sentences": len(sents),
            "candidates": len(cands),
            "selected": len(points),
            "elapsed": round(time.time() - t0, 3),
        },
    }


def verify_traceable(md_text: str, points: list[dict]) -> tuple[bool, str]:
    """**A 档红线校验**：每条核心必须能在原文中定位。

    这是抽取式"不可能造假"的机器可验证证明；任一条对不上即判失败。

    匹配口径：两侧都去掉**全部空白**再比对（原文可能有连续空格、软换行，
    核心句保留原样空白），文字与标点必须逐字一致。
    """
    norm = re.sub(r"\s+", "", md_text)
    for p in points:
        needle = re.sub(r"\s+", "", p.get("text") or "")
        if not needle:
            return False, "存在空核心条目"
        if needle not in norm:
            return False, "核心条目无法在原文中定位：%s" % (p.get("text", "")[:20])
    return True, ""


# --------------------------------------------------------------------------- #
# 8. 产物渲染
# --------------------------------------------------------------------------- #
def render_md(src: Path, result: dict, meta: dict) -> tuple[str, str]:
    """渲染 ``.refine.md``（可信提纯版）：8 字段来源注释 + 三区块 + 块级锚点。

    与 S7 的产物结构保持一致（便于用户对照），但内容性质不同：
    这里每条都是**原文原句**，不是模型重写，故措辞更强调可回溯。
    """
    info = media_runtime.source_info(src)
    # doc_id 可由调用方覆盖（修订产物须沿用精读产物的同一个 id，避免产物链断裂）
    doc_id = (meta.get("doc_id") or info["doc_id"])
    points = result.get("points") or []
    stats = result.get("stats") or {}
    mode = meta.get("mode") or "可信提纯（抽取式）"
    is_rewrite = "改写" in mode
    comment = media_runtime.source_comment(
        src, ".md", meta.get("converter") or "抽取式提纯（纯标准库，零依赖）",
        anchors=["block"])
    promise = ("本文件为**原文内改写**结果：只动结构与措辞、未改事实，"
               "每个片段可在原文定位。"
               if is_rewrite else
               "本文件核心**全部为原文原句**，逐条可在原文定位，未做任何改写或生成。")
    lines = [
        comment, "",
        "# %s · 可信提纯（核心提取）" % src.stem, "",
        "## 文档信息", "",
        "- 源文件：%s" % src.name,
        "- 大小：%d 字节" % info["size"],
        "- 生成时间：%s" % time.strftime("%Y-%m-%d %H:%M:%S"),
    ] + ([
        "- 源块数：%d ｜ 候选句：%d ｜ 入选核心：%d"
        % (int(stats.get("blocks") or 0), int(stats.get("sentences") or 0),
           len(points)),
    ] if not is_rewrite else [
        "- 改写前核心：%d 条 ｜ 改写后：%d 条 ｜ 合并去重：%d 条"
        % (int(stats.get("before") or 0), int(stats.get("after") or 0),
           int(stats.get("merged") or 0)),
    ]) + [
        "- 关键词：%s" % ("、".join(result.get("keywords") or []) or "见各条"),
        "",
        "> %s" % promise,
        "", "## 核心知识点", "",
    ]
    for p in points:
        # 多块锚点（B 档合并后并列多个来源块），单块时与 S7 格式一致
        blocks = p.get("blocks") or [p.get("block")]
        if len(blocks) > 1:
            lines.append("<!-- anchor: %s | block: %s | blocks: %s -->"
                         % (doc_id, blocks[0], ",".join(str(b) for b in blocks)))
        else:
            lines.append(media_runtime.block_anchor(doc_id, p["block"]))
        lines.append("- %s" % p["text"])
        bits = []
        if p.get("keywords"):
            bits.append("关键词：%s" % "、".join(p["keywords"]))
        if p.get("reasons"):
            bits.append("依据：%s" % "、".join(p["reasons"]))
        bits.append("评分：%.3f" % float(p.get("score") or 0))
        lines.append("  <sub>%s</sub>" % " ｜ ".join(bits))
        lines.append("")
    lines += [
        "## 提纯元数据", "",
        "- 转换器：%s" % (meta.get("converter") or "抽取式提纯"),
        "- 模式：%s" % (meta.get("mode") or "可信提纯（抽取式）"),
        "- 保真度：%s" % ("架构级保证 —— 只用原文素材，未改事实；每个片段可在原文定位"
                       if is_rewrite else
                       "架构级保证 —— 每条核心均为原文原句，可逐字定位"),
    ]
    # B 档操作说明由渲染层**原生输出**（不再由调用方事后 replace 拼接 ——
    # 那条旧路径的匹配串与实际输出不一致，replace 静默失效、操作行从未出现）。
    ops = stats.get("ops") or []
    if ops:
        lines.append("- 本次改写操作：%s（合并 %d 条）"
                     % ("、".join(str(o) for o in ops),
                        int(stats.get("merged") or 0)))
    lines += [
        "- 耗时：%.3f 秒" % float(stats.get("elapsed") or 0),
        "- 源文件 sha256：%s" % info["sha256"],
        "- doc_id：%s" % doc_id,
        "- 产物区：out/derived/（不参与阶段 1 件数对账）",
        "",
    ]
    return "\n".join(lines), doc_id


# --------------------------------------------------------------------------- #
# 9. B 档：原文内改写（只用原文素材，白名单外一律不做）
# --------------------------------------------------------------------------- #
# 白名单（契约 S8 §四）：
#   ① 术语归一：同一概念的不同写法 → 统一到高频写法（须有共现证据）
#   ② 要点合并去重：高度重叠的两条核心 → 合并，块锚点并列
#   ③ 结构重排：按块号/章节分组，不增删内容
#   ④ 排版归一：全半角标点统一
# **禁止**：改写事实、添加解释、生成结论、调整数字/单位/人名/日期。
# 因此本模块的每一条输出仍是**原文原句或原文句的组合**，绝不产生新句。

# 全角 → 半角标点（仅标点，不动文字与数字）
_PUNCT_FULL2HALF = {
    "，": ",", "。": ".", "；": ";", "：": ":", "！": "!", "？": "?",
    "（": "(", "）": ")", "【": "[", "】": "]", "《": "<", "》": ">",
    "“": '"', "”": '"', "‘": "'", "’": "'", "、": ",",
}
_PUNCT_RE = re.compile("|".join(re.escape(k) for k in _PUNCT_FULL2HALF))


def normalize_punct(text: str) -> str:
    """排版归一：全角标点 → 半角。**只动标点，不动任何文字与数字**。"""
    return _PUNCT_RE.sub(lambda m: _PUNCT_FULL2HALF[m.group(0)], text)


def normalize_terms(points: list[dict], threshold: float = 0.55) -> list[dict]:
    """术语归一：把同一概念的多种写法统一到**频次最高**的写法。

    判据（须有证据，不猜）：两个词若其 bigram 集合 Jaccard 相似度 ≥ threshold，
    则视为同一概念的变体 —— 只有这样才归一，且统一到全文出现次数最多的写法。

    归一只改**写法**（选一个已有写法），不产生任何新词，因此不引入新事实。
    """
    if not points:
        return []
    # 统计每个候选词的全局出现次数（用于选代表写法）
    freq: dict[str, int] = {}
    for p in points:
        for t in p.get("keywords") or []:
            freq[t] = freq.get(t, 0) + 1
    grams = {t: set(bigrams(t)) for t in freq}
    # 归组：相似词归到同一簇，代表 = 频次最高（并列则取更长更具体者）
    groups: list[list[str]] = []
    for term in sorted(freq, key=lambda t: (-freq[t], -len(t), t)):
        placed = False
        for g in groups:
            if any(jaccard(grams[term], grams[rep]) >= threshold for rep in g):
                g.append(term)
                placed = True
                break
        if not placed:
            groups.append([term])
    mapping: dict[str, str] = {}
    for g in groups:
        if len(g) < 2:
            continue
        rep = sorted(g, key=lambda t: (-freq[t], -len(t), t))[0]
        for t in g:
            if t != rep:
                mapping[t] = rep
    if not mapping:
        return points
    out = []
    for p in points:
        q = dict(p)
        q["keywords"] = [mapping.get(t, t) for t in (p.get("keywords") or [])]
        # 去重（归一后可能出现重复词）
        seen, dedup = set(), []
        for t in q["keywords"]:
            if t not in seen:
                seen.add(t)
                dedup.append(t)
        q["keywords"] = dedup
        out.append(q)
    return out


def merge_duplicates(points: list[dict],
                     threshold: float = NEAR_DUP_THRESHOLD) -> list[dict]:
    """要点合并去重：语义高度重叠的两条核心 → 合并为一条，块锚点并列。

    合并时**保留两条的原文句子**（用 ` ｜ ` 连接），不重写、不概括，
    因此合并结果仍完全由原文构成，绝不产生新表述。
    """
    if len(points) <= 1:
        return points
    out: list[dict] = []
    for p in points:
        merged = False
        for q in out:
            g1 = _bigram_set(p.get("text") or "")
            g2 = _bigram_set(q.get("text") or "")
            if jaccard(g1, g2) >= threshold:
                # 保留两条原文，块号并列
                texts = [q.get("text") or "", p.get("text") or ""]
                blocks = sorted(set((q.get("blocks") or [q.get("block")])
                                    + (p.get("blocks") or [p.get("block")])))
                q["text"] = " ｜ ".join(t for t in texts if t)
                q["blocks"] = blocks
                q["block"] = blocks[0] if blocks else q.get("block")
                q["merged"] = int(q.get("merged", 1)) + 1
                kws = list(q.get("keywords") or [])
                for t in (p.get("keywords") or []):
                    if t not in kws:
                        kws.append(t)
                q["keywords"] = kws[:6]
                merged = True
                break
        if not merged:
            q = dict(p)
            q["blocks"] = [p.get("block")]
            q.setdefault("merged", 1)
            out.append(q)
    return out


def group_by_section(points: list[dict]) -> list[dict]:
    """结构重排：按块号升序排列（保持原文出现顺序），不增删内容。"""
    return sorted(points, key=lambda p: (p.get("block") or 0))


def rewrite_in_source(points: list[dict], blocks: list[dict] | None = None,
                      punct_normalize: bool = False) -> dict:
    """B 档主流程：原文内改写（术语归一 + 合并去重 + 结构重排 [+ 排版归一]）。

    ``punct_normalize`` **默认 False**：排版归一会改标点（全角→半角），
    虽然事实零变化，但会破坏「逐字可在原文定位」这条 A 档红线，
    因此它不是默认操作，只是**可选**的排版偏好。

    返回 ``{"points": [...], "stats": {...}}``；每条仍带 block 锚点与原文句。
    """
    pts = [dict(p) for p in (points or [])]
    before = len(pts)
    pts = normalize_terms(pts)
    pts = merge_duplicates(pts)
    pts = group_by_section(pts)
    ops = ["术语归一", "合并去重", "结构重排"]
    if punct_normalize:
        for p in pts:
            p["text"] = normalize_punct(p.get("text") or "")
        ops.append("排版归一")
    merged = sum(int(p.get("merged", 1)) - 1 for p in pts)
    return {
        "points": pts,
        "stats": {
            "before": before,
            "after": len(pts),
            "merged": merged,
            "ops": ops,
            # 与 A 档 stats 同形，便于统一渲染
            "blocks": 0,
            "sentences": len(pts),
            "candidates": before,
            "selected": len(pts),
            "elapsed": 0.0,
        },
    }


def verify_no_new_content(md_text: str, points: list[dict]) -> tuple[bool, str]:
    """B 档红线：每条核心的**每个片段**都必须能在原文中找到。

    与 A 档的 :func:`verify_traceable` 的区别：合并后的条目含多个片段
    （用 `` ｜ `` 分隔），本函数逐片段校验，并**忽略标点全半角差异**
    （排版归一只改标点、不改事实，故不算「新增内容」）。
    """
    def canon(t: str) -> str:
        return re.sub(r"\s+", "", normalize_punct(t))
    norm = canon(md_text)
    for p in points:
        for frag in (p.get("text") or "").split(" ｜ "):
            frag = frag.strip()
            if not frag:
                continue
            if canon(frag) not in norm:
                return False, "改写引入了原文没有的内容：%s" % frag[:20]
    return True, ""
