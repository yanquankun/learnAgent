"""
rag.py —— 问答内核（Workflow 版）

流程：检索 -> 置信度判断 -> 生成（流式）-> 组装 sources / recommendedArticles。
第六章会把这个内核替换成 LangGraph 图（带路由与重试），但 API 层不变 ——
这正是第一章「内核与服务解耦」的设计意图。
"""

import uuid
from dataclasses import dataclass, field
from typing import Iterator

import config
from llm_client import get_client
from vector_store import search

TOP_K = 4
SCORE_THRESHOLD = 0.50   # 低于它视为「博客里没有相关内容」

SYSTEM_PROMPT = (
    "你是技术博客的AI助手。严格根据<资料>回答问题：资料里没有的不要编造；"
    "回答简洁（200字以内）、用中文；不要在回答里罗列来源（系统会单独展示来源卡片）。"
)


@dataclass
class QaResult:
    """一次问答的完整结果（API 响应的数据来源）。"""

    trace_id: str
    answer: str = ""
    sources: list[dict] = field(default_factory=list)
    recommended: list[dict] = field(default_factory=list)
    confidence: float = 0.0
    category: str = "tech"   # 第七章新增：观测埋点用（tech / chitchat）


def article_url(article_id: str) -> str:
    return config.BLOG_URL_TEMPLATE.format(id=article_id)


def build_cards(hits: list[dict]) -> tuple[list[dict], list[dict]]:
    """从检索结果组装 sources（引用）与 recommendedArticles（延伸阅读）。

    规则：每篇文章取最高分；前 2 篇作为来源，其余作为推荐。
    """
    best: dict[str, dict] = {}
    for hit in hits:
        existing = best.get(hit["article_id"])
        if existing is None or hit["score"] > existing["score"]:
            best[hit["article_id"]] = hit
    ranked = sorted(best.values(), key=lambda h: h["score"], reverse=True)

    sources = [
        {"title": h["title"], "url": article_url(h["article_id"]), "score": round(h["score"], 3)}
        for h in ranked[:2]
    ]
    recommended = [
        {"title": h["title"], "url": article_url(h["article_id"])}
        for h in ranked[2:4]
    ]
    return sources, recommended


def answer_stream(question: str, history: list[dict]) -> Iterator[tuple[str, QaResult | str]]:
    """流式问答生成器。

    产出两种事件（供 API 层转成 SSE）：
        ("delta", 文本片段)   —— 回答的增量内容
        ("done",  QaResult)   —— 最终的完整结果（含来源与推荐）
    """
    result = QaResult(trace_id=uuid.uuid4().hex[:16])

    # ---- 1. 检索 ----
    hits = search(question, top_k=TOP_K)
    result.confidence = round(hits[0]["score"], 3) if hits else 0.0

    # ---- 2. 置信度不足：诚实拒答（不调用 LLM，省钱且不胡说）----
    if result.confidence < SCORE_THRESHOLD:
        closest = [
            {"title": h["title"], "url": article_url(h["article_id"])}
            for h in {h["article_id"]: h for h in hits}.values()
        ][:2]
        result.sources = []
        result.recommended = closest
        result.answer = "抱歉，博客中暂时没有与这个问题直接相关的内容。"
        if closest:
            result.answer += "你可以看看这些相对接近的文章。"
        yield ("delta", result.answer)
        yield ("done", result)
        return

    # ---- 3. 正常生成：拼上下文 + 会话历史，流式输出 ----
    result.sources, result.recommended = build_cards(hits)
    context = "\n\n".join(
        f"【{h['title']}｜{' > '.join(h['heading_path'])}】\n{h['content']}" for h in hits
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *history,
        {"role": "user", "content": f"<资料>\n{context}\n</资料>\n\n问题：{question}"},
    ]

    stream = get_client().chat.completions.create(
        model=config.LLM_MODEL, messages=messages, stream=True, temperature=0.3
    )
    parts: list[str] = []
    for chunk in stream:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            parts.append(delta)
            yield ("delta", delta)

    result.answer = "".join(parts)
    yield ("done", result)
