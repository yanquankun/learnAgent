"""
（二）条件路由与循环 —— 演示入口

给图加上「判断力」。两个经典模式（均在 03 模块一章的 Workflow 清单里）：

    演示 1：路由（Routing）—— 闲聊直接答，技术问题走「检索」分支
    演示 2：评估-优化循环（Evaluator-Optimizer）—— 写口号，评分不过就带着
            反馈重写，直到达标或到达重试上限

两个演示都需要 LLM Key。运行前先看 build_xxx_graph 的建图代码。

运行方式：
    cd 到本 project 目录 -> uv sync -> uv run python main.py
"""

from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field
from rich.console import Console
from rich.panel import Panel

from lc_client import get_chat_model

console = Console()
model = get_chat_model()


# ============================================================
# 演示 1：条件路由 —— add_conditional_edges
# ============================================================

class RouteState(TypedDict):
    question: str
    category: str   # chitchat / tech
    answer: str


class RouteDecision(BaseModel):
    """路由判断结果（用 04 模块学的结构化输出，保证字段合法）。"""

    category: Literal["chitchat", "tech"] = Field(
        description="chitchat=寒暄闲聊；tech=技术问题需要查博客资料"
    )


def classify(state: RouteState) -> dict:
    """节点：判断问题类型。结构化输出保证 category 只会是合法枚举值。"""
    decision = model.with_structured_output(RouteDecision).invoke(
        f"判断这个问题的类型：{state['question']}"
    )
    console.print(f"  [magenta]路由判断：{decision.category}[/magenta]")
    return {"category": decision.category}


def answer_chitchat(state: RouteState) -> dict:
    reply = model.invoke(f"你是博客站的AI助手，友好地回应（30字内）：{state['question']}")
    return {"answer": reply.content}


def answer_tech(state: RouteState) -> dict:
    """技术分支：这里先用提示词模拟「带资料回答」，下一章换成真检索。"""
    reply = model.invoke(
        f"你是技术博客AI助手，专业地回答这个技术问题（80字内）：{state['question']}"
    )
    return {"answer": "【走了RAG分支】" + str(reply.content)}


def route_by_category(state: RouteState) -> str:
    """路由函数：读状态，返回下一个节点的名字 —— 条件边的核心。

    注意它不是节点（不改状态），只是「看一眼状态，指个方向」。
    """
    return "answer_tech" if state["category"] == "tech" else "answer_chitchat"


def build_router_graph():
    builder = StateGraph(RouteState)
    builder.add_node("classify", classify)
    builder.add_node("answer_chitchat", answer_chitchat)
    builder.add_node("answer_tech", answer_tech)

    builder.add_edge(START, "classify")
    # 条件边：classify 跑完后，由 route_by_category 决定去哪
    builder.add_conditional_edges(
        "classify",
        route_by_category,
        ["answer_chitchat", "answer_tech"],  # 显式声明可能的去向（画图/校验用）
    )
    builder.add_edge("answer_chitchat", END)
    builder.add_edge("answer_tech", END)
    return builder.compile()


def demo_1_routing() -> None:
    console.rule("[bold cyan]演示 1：条件路由")
    graph = build_router_graph()
    console.print(Panel(graph.get_graph().draw_mermaid(), title="路由图结构", border_style="blue"))

    for q in ["你好呀，今天天气不错", "Qdrant 的 payload 过滤怎么用？"]:
        console.print(f"\n提问：[bold]{q}[/bold]")
        result = graph.invoke({"question": q, "category": "", "answer": ""})
        console.print(f"回答：[green]{result['answer']}[/green]")
    console.print()


# ============================================================
# 演示 2：评估-优化循环 —— 条件边指回上游 = 循环
# ============================================================

class SloganState(TypedDict):
    product: str
    slogan: str
    feedback: str
    score: int
    attempts: int


class Review(BaseModel):
    """评审结果。"""

    score: int = Field(description="口号质量评分 1~10，8分及以上算合格", ge=1, le=10)
    feedback: str = Field(description="一句话改进建议")


def write_slogan(state: SloganState) -> dict:
    """生成节点：如果有上轮反馈，带着反馈重写 —— 循环的关键。"""
    hint = f"\n上一版是「{state['slogan']}」，评审意见：{state['feedback']}，请针对性改进。" if state["feedback"] else ""
    reply = model.invoke(f"为「{state['product']}」写一句12字以内的中文宣传口号，只输出口号。{hint}")
    attempts = state["attempts"] + 1
    console.print(f"  [magenta]第{attempts}稿：{reply.content}[/magenta]")
    return {"slogan": reply.content, "attempts": attempts}


def review_slogan(state: SloganState) -> dict:
    """评估节点：用另一次 LLM 调用当「裁判」，结构化输出评分。"""
    review = model.with_structured_output(Review).invoke(
        f"严格评审这句宣传口号（产品：{state['product']}）：「{state['slogan']}」。"
        f"从朗朗上口、点明卖点两方面打分。"
    )
    console.print(f"  [dim]评分 {review.score}/10：{review.feedback}[/dim]")
    return {"score": review.score, "feedback": review.feedback}


def should_retry(state: SloganState) -> str:
    """循环出口判断：合格或重试次数用完就结束，否则回到生成节点。

    没有重试上限的循环 = 烧钱的死循环，这是 Agent 工程的铁律。
    """
    if state["score"] >= 8:
        return "good"
    if state["attempts"] >= 3:
        return "give_up"
    return "retry"


def build_loop_graph():
    builder = StateGraph(SloganState)
    builder.add_node("write", write_slogan)
    builder.add_node("review", review_slogan)

    builder.add_edge(START, "write")
    builder.add_edge("write", "review")
    # 条件边指回 write —— 这就构成了循环
    builder.add_conditional_edges(
        "review",
        should_retry,
        {"retry": "write", "good": END, "give_up": END},  # 映射写法：路由值 -> 节点
    )
    return builder.compile()


def demo_2_evaluator_loop() -> None:
    console.rule("[bold cyan]演示 2：评估-优化循环")
    graph = build_loop_graph()

    result = graph.invoke(
        {"product": "程序员的AI博客问答助手", "slogan": "", "feedback": "", "score": 0, "attempts": 0}
    )
    verdict = "合格" if result["score"] >= 8 else "已达重试上限，取最后一稿"
    console.print(
        Panel(
            f"最终口号：{result['slogan']}\n评分：{result['score']}/10（{verdict}，共{result['attempts']}稿）",
            border_style="green",
        )
    )


if __name__ == "__main__":
    demo_1_routing()
    demo_2_evaluator_loop()
    console.print("\n[bold green]本章完成！下一章把路由和循环用在真正的 RAG 上。[/bold green]")
