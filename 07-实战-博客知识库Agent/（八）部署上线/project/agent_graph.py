"""
agent_graph.py —— 问答内核（LangGraph 生产图版）

替换第四章的 rag.py（保留作对照），API 层契约不变：
    answer_stream(question, session_id) -> ("delta", str) / ("done", QaResult)

图结构（05 模块练过的所有模式在此合体）：

    route ──聊天──> chitchat ──────────────────┐
      │                                         │
      └─技术──> rewrite -> retrieve --评分达标--> generate ──> END
                   ↑           │
                   └──不达标重试─┘──次数用尽──> refuse ──> END

相比 Workflow 版的三个升级：
1. 路由：闲聊不再触发检索（省 embedding + 检索开销，回答也更自然）
2. 改写 + 低置信度二次检索：结合会话历史改写检索词（"那它怎么部署？"
   能被还原成完整问题），首搜不达标自动换词重试
3. 跨进程会话记忆：SQLite checkpointer 按 thread_id 存档，服务重启不丢上下文
"""

import sqlite3
import uuid
from typing import Annotated, Iterator, Literal, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from lc_client import get_chat_model
import config
from rag import SCORE_THRESHOLD, SYSTEM_PROMPT, TOP_K, QaResult, article_url, build_cards
from vector_store import search

MAX_ATTEMPTS = 2          # 最多检索 2 次（首搜 + 1 次换词重试）
HISTORY_WINDOW = 8        # 节点内只取最近 8 条消息参与推理，防止上下文无限膨胀
CHECKPOINT_DB = config.DATA_DIR / "checkpoints.db"


# ---------------------------------------------------------------------------
# 状态：messages 由 checkpointer 跨请求持久化，其余字段是单次问答的中间产物
# ---------------------------------------------------------------------------
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]   # 会话记忆（add_messages 自动追加）
    question: str
    user_id: str             # 08 模块三章接入：长期记忆的隔离主体
    category: str            # tech / chitchat
    query: str               # 当前检索词（可能被改写多次）
    attempts: int
    hits: list[dict]
    confidence: float
    answer: str


def _memory_block(state: AgentState) -> str:
    """召回该用户的长期记忆，拼成可注入 system prompt 的片段。

    召回失败不能影响主流程 —— 记忆是「锦上添花」，挂了就当没有。
    """
    try:
        from user_memory import recall

        memories = recall(state["user_id"], state["question"])
    except Exception:
        memories = []
    if not memories:
        return ""
    return "\n\n关于这位读者的已知信息（自然地用上，不要逐条复述）：\n" + "\n".join(
        f"- {m}" for m in memories
    )


class RouteDecision(BaseModel):
    """路由节点的结构化输出：只许二选一，杜绝自由发挥。"""

    category: Literal["tech", "chitchat"] = Field(
        description="tech=技术问题需要查博客资料；chitchat=寒暄/闲聊/与技术无关"
    )


def _recent(state: AgentState) -> list:
    """取最近几条历史（不含本轮刚追加的用户消息）。"""
    return state["messages"][-HISTORY_WINDOW - 1 : -1]


# ---------------------------------------------------------------------------
# 节点
# ---------------------------------------------------------------------------
def route(state: AgentState) -> dict:
    decider = get_chat_model(temperature=0).with_structured_output(RouteDecision)
    decision = decider.invoke(
        [
            SystemMessage(content="判断用户最新一条消息属于哪类。"),
            *_recent(state),
            HumanMessage(content=state["question"]),
        ]
    )
    return {"category": decision.category, "attempts": 0, "query": state["question"]}


def chitchat(state: AgentState) -> dict:
    """闲聊：不检索，直接简短回应并把话题引向博客（带用户记忆，回应更自然）。"""
    reply = get_chat_model(temperature=0.7).invoke(
        [
            SystemMessage(
                content="你是技术博客的AI助手。用1-2句话友好回应，"
                "并顺势提一句可以问你博客里的技术问题。" + _memory_block(state)
            ),
            *_recent(state),
            HumanMessage(content=state["question"]),
        ]
    )
    return {"answer": reply.content, "messages": [AIMessage(content=reply.content)]}


def rewrite(state: AgentState) -> dict:
    """结合会话历史改写检索词；重试时要求换一种表述。"""
    hint = (
        f"上次用「{state['query']}」检索效果不佳，请换一种说法（同义词/换角度）。"
        if state["attempts"] > 0
        else "把用户最新问题改写成一句独立完整的检索查询（补全代词指代）。"
    )
    reply = get_chat_model(temperature=0).invoke(
        [
            SystemMessage(content=f"{hint}只输出改写后的查询本身，不要解释。"),
            *_recent(state),
            HumanMessage(content=state["question"]),
        ]
    )
    return {"query": reply.content.strip(), "attempts": state["attempts"] + 1}


def retrieve(state: AgentState) -> dict:
    hits = search(state["query"], top_k=TOP_K)
    confidence = round(hits[0]["score"], 3) if hits else 0.0
    return {"hits": hits, "confidence": confidence}


def grade(state: AgentState) -> str:
    """条件边：达标生成 / 不达标重试 / 次数用尽拒答。"""
    if state["confidence"] >= SCORE_THRESHOLD:
        return "generate"
    if state["attempts"] < MAX_ATTEMPTS:
        return "rewrite"
    return "refuse"


def generate(state: AgentState) -> dict:
    context = "\n\n".join(
        f"【{h['title']}｜{' > '.join(h['heading_path'])}】\n{h['content']}"
        for h in state["hits"]
    )
    reply = get_chat_model().invoke(
        [
            # 记忆注入点：读者背景拼进 system prompt（top-k + 阈值召回，不是全量倾倒）
            SystemMessage(content=SYSTEM_PROMPT + _memory_block(state)),
            *_recent(state),
            HumanMessage(content=f"<资料>\n{context}\n</资料>\n\n问题：{state['question']}"),
        ]
    )
    return {"answer": reply.content, "messages": [AIMessage(content=reply.content)]}


def refuse(state: AgentState) -> dict:
    """两次检索都不达标：诚实拒答（不调 LLM 编造）。"""
    answer = "抱歉，博客中暂时没有与这个问题直接相关的内容。"
    if state["hits"]:
        answer += "你可以看看下方相对接近的文章。"
    return {"answer": answer, "messages": [AIMessage(content=answer)]}


# ---------------------------------------------------------------------------
# 组图（模块级单例：编译一次，所有请求共用；会话靠 thread_id 隔离）
# ---------------------------------------------------------------------------
def build_graph():
    builder = StateGraph(AgentState)
    builder.add_node("route", route)
    builder.add_node("chitchat", chitchat)
    builder.add_node("rewrite", rewrite)
    builder.add_node("retrieve", retrieve)
    builder.add_node("generate", generate)
    builder.add_node("refuse", refuse)

    builder.add_edge(START, "route")
    builder.add_conditional_edges(
        "route",
        lambda s: s["category"],
        {"tech": "rewrite", "chitchat": "chitchat"},
    )
    builder.add_edge("rewrite", "retrieve")
    builder.add_conditional_edges("retrieve", grade, ["generate", "rewrite", "refuse"])
    builder.add_edge("chitchat", END)
    builder.add_edge("generate", END)
    builder.add_edge("refuse", END)

    # check_same_thread=False：uvicorn 的请求可能跑在不同线程上
    conn = sqlite3.connect(CHECKPOINT_DB, check_same_thread=False)
    return builder.compile(checkpointer=SqliteSaver(conn))


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


# ---------------------------------------------------------------------------
# 对 API 层暴露的生成器（与 rag.answer_stream 同一契约，app.py 几乎无感切换）
# ---------------------------------------------------------------------------
STREAM_NODES = {"generate", "chitchat"}   # 只把这两个节点的 token 透传给前端


def answer_stream(
    question: str, session_id: str, user_id: str = ""
) -> Iterator[tuple[str, QaResult | str]]:
    graph = get_graph()
    thread = {"configurable": {"thread_id": session_id}}
    result = QaResult(trace_id=uuid.uuid4().hex[:16])

    streamed = False
    # stream_mode="messages"：图里每次 LLM 调用的 token 都会流出来，
    # metadata["langgraph_node"] 标明来源节点 —— 路由/改写的内部输出不透传给用户
    for chunk, metadata in graph.stream(
        {
            "question": question,
            "user_id": user_id or session_id,   # 没传 userId 就用 sessionId 兜底
            "messages": [HumanMessage(content=question)],
        },
        thread,
        stream_mode="messages",
    ):
        if metadata.get("langgraph_node") in STREAM_NODES and chunk.content:
            streamed = True
            yield ("delta", chunk.content)

    # 流结束后从 checkpointer 取最终状态，组装契约字段
    state = graph.get_state(thread).values
    result.answer = state.get("answer", "")
    result.confidence = state.get("confidence", 0.0)
    result.category = state.get("category", "tech")
    hits = state.get("hits", [])
    if state.get("category") == "tech":
        if result.confidence >= SCORE_THRESHOLD:
            result.sources, result.recommended = build_cards(hits)
        else:   # 拒答：给最接近的文章当推荐
            result.recommended = [
                {"title": h["title"], "url": article_url(h["article_id"])}
                for h in {h["article_id"]: h for h in hits}.values()
            ][:2]

    if not streamed and result.answer:   # refuse 不调 LLM，没有 token 流，补发一条
        yield ("delta", result.answer)
    yield ("done", result)
