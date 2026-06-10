"""
（三）LangGraph 版 RAG 工作流 —— 演示入口

把 02 模块五章学的「检索调优手段」组装成一张会自我纠正的图
（轻量版 Corrective RAG）：

    改写查询 -> 检索 -> 相关性评分 --合格--> 生成带来源回答
                  ^              |
                  |          不合格且还有机会
                  +----- 换种说法重写 <-+
                                 |
                              机会用完 -> 礼貌拒答

复用 02 模块的全部基建：loader / chunker / embedder / indexer。

运行方式：
    cd 到本 project 目录 -> uv sync -> uv run python main.py（需要 LLM Key）
"""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from rich.console import Console
from rich.panel import Panel

from embedder import embed_one
from indexer import COLLECTION, build_index, get_qdrant
from lc_client import get_chat_model

console = Console()
model = get_chat_model()
qdrant = get_qdrant()

TOP_K = 4
SCORE_THRESHOLD = 0.55   # 02 模块五章实验得出的经验阈值
MAX_ATTEMPTS = 2         # 最多重写 2 次查询（循环上限！）
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："


# ============================================================
# 状态：整条 RAG 流水线共享的数据
# ============================================================

class RagState(TypedDict):
    question: str        # 用户原始问题（永远不变）
    query: str           # 当前用于检索的查询（会被改写）
    tried_queries: list  # 用过的查询（避免重写成重复的）
    hits: list           # 检索结果 [{score, title, text, article_id}]
    best_score: float    # 本轮最高分
    attempts: int        # 已检索次数
    answer: str          # 最终回答


# ============================================================
# 节点
# ============================================================

def rewrite_query(state: RagState) -> dict:
    """节点 1：查询改写（02 模块五章的 Query Rewrite，进了图之后可循环）。"""
    if not state["tried_queries"]:
        prompt = (
            f"把用户的口语化问题改写成适合向量检索的简洁查询（保留技术关键词，"
            f"只输出改写结果）：{state['question']}"
        )
    else:
        prompt = (
            f"用户问题：{state['question']}\n"
            f"已尝试过的检索查询：{state['tried_queries']}，但没检索到相关内容。\n"
            f"请换一个角度改写（比如换同义技术词、换抽象层级），只输出新查询。"
        )
    query = str(model.invoke(prompt).content).strip()
    console.print(f"  [magenta]改写查询：{query}[/magenta]")
    return {"query": query, "tried_queries": state["tried_queries"] + [query]}


def retrieve(state: RagState) -> dict:
    """节点 2：真实向量检索（复用 02 模块的 embedder + Qdrant）。"""
    vector = embed_one(QUERY_PREFIX + state["query"])
    points = qdrant.query_points(
        collection_name=COLLECTION, query=vector.tolist(), limit=TOP_K
    ).points
    hits = [
        {
            "score": p.score,
            "title": p.payload["title"],
            "text": p.payload["content"],
            "article_id": p.payload["article_id"],
        }
        for p in points
    ]
    best = hits[0]["score"] if hits else 0.0
    console.print(f"  [dim]检索到 {len(hits)} 条，最高分 {best:.3f}[/dim]")
    return {"hits": hits, "best_score": best, "attempts": state["attempts"] + 1}


def generate(state: RagState) -> dict:
    """节点 3a：基于命中内容生成带来源的回答（02 模块四章的 Prompt 三原则）。"""
    context = "\n\n".join(
        f"【{h['title']}】(相关度{h['score']:.2f})\n{h['text']}"
        for h in state["hits"]
        if h["score"] >= SCORE_THRESHOLD - 0.1  # 弱相关的也给模型参考
    )
    reply = model.invoke(
        f"你是技术博客AI助手。严格根据资料回答问题，不要编造，"
        f"150字以内，结尾用「来源：」列出引用的文章标题。\n\n"
        f"<资料>\n{context}\n</资料>\n\n问题：{state['question']}"
    )
    return {"answer": str(reply.content)}


def refuse(state: RagState) -> dict:
    """节点 3b：诚实拒答，但给出最接近的文章（02 模块四章的拒答策略）。"""
    closest = "、".join(dict.fromkeys(h["title"] for h in state["hits"][:2])) or "无"
    return {
        "answer": (
            f"抱歉，博客中暂时没有找到与这个问题直接相关的内容"
            f"（已尝试 {state['attempts']} 种检索方式）。最接近的文章：{closest}"
        )
    }


# ============================================================
# 路由：评分及格 -> 生成；不及格但还有机会 -> 重写；机会用完 -> 拒答
# ============================================================

def grade_route(state: RagState) -> str:
    if state["best_score"] >= SCORE_THRESHOLD:
        return "generate"
    if state["attempts"] < MAX_ATTEMPTS:
        console.print(f"  [yellow]最高分 {state['best_score']:.3f} 不及格，换种说法重试[/yellow]")
        return "rewrite_query"
    return "refuse"


def build_rag_graph():
    builder = StateGraph(RagState)
    builder.add_node("rewrite_query", rewrite_query)
    builder.add_node("retrieve", retrieve)
    builder.add_node("generate", generate)
    builder.add_node("refuse", refuse)

    builder.add_edge(START, "rewrite_query")
    builder.add_edge("rewrite_query", "retrieve")
    builder.add_conditional_edges(
        "retrieve", grade_route, ["generate", "rewrite_query", "refuse"]
    )
    builder.add_edge("generate", END)
    builder.add_edge("refuse", END)
    return builder.compile()


def ask(graph, question: str) -> None:
    console.print(f"\n提问：[bold]{question}[/bold]")
    result = graph.invoke(
        {
            "question": question, "query": "", "tried_queries": [],
            "hits": [], "best_score": 0.0, "attempts": 0, "answer": "",
        }
    )
    console.print(Panel(result["answer"], border_style="green"))


def main() -> None:
    console.print("[bold]构建/检查索引……[/bold]")
    build_index(qdrant)

    graph = build_rag_graph()
    console.print(Panel(graph.get_graph().draw_mermaid(), title="RAG 工作流图", border_style="blue"))

    # 问题 1：正常技术问题（一次检索就该及格 -> generate）
    ask(graph, "我页面老是莫名其妙重复请求接口，是不是 useEffect 的问题？")
    # 问题 2：博客里没有的内容（重试后仍不及格 -> refuse）
    ask(graph, "K8s 的 Operator 模式怎么开发？")


if __name__ == "__main__":
    main()
