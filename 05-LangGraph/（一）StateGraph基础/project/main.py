"""
（一）StateGraph 基础 —— 演示入口

LangGraph 的世界观只有三样东西：状态（State）、节点（Node）、边（Edge）。

    演示 1：最小的图 —— 纯 Python，不调用 LLM，看清图的机制本身
    演示 2：draw_mermaid —— 让图自己画出流程图
    演示 3：提示链工作流 —— 大纲 -> 草稿 -> 润色（03 模块一章讲过的模式，需要 Key）

运行方式：
    cd 到本 project 目录 -> uv sync -> uv run python main.py
"""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from rich.console import Console
from rich.panel import Panel

console = Console()


# ============================================================
# 演示 1：最小的图 —— 不用 LLM，看清机制
# ============================================================

class CounterState(TypedDict):
    """状态就是一个「带类型说明的字典」，图里所有节点共享它。"""

    count: int
    history: list[str]


def add_one(state: CounterState) -> dict:
    """节点 = 普通函数：拿到当前状态，返回「要更新的字段」。

    注意：只返回想更新的部分，LangGraph 负责合并进状态 ——
    这和 React 的 setState（部分更新）是一个思路。
    """
    new_count = state["count"] + 1
    return {"count": new_count, "history": state["history"] + [f"add_one -> {new_count}"]}


def double(state: CounterState) -> dict:
    new_count = state["count"] * 2
    return {"count": new_count, "history": state["history"] + [f"double  -> {new_count}"]}


def demo_1_minimal_graph() -> None:
    console.rule("[bold cyan]演示 1：最小的图（无 LLM）")

    # 建图三步：声明状态结构 -> 加节点 -> 连边
    builder = StateGraph(CounterState)
    builder.add_node("add_one", add_one)
    builder.add_node("double", double)
    builder.add_edge(START, "add_one")   # START：入口
    builder.add_edge("add_one", "double")
    builder.add_edge("double", END)      # END：出口

    graph = builder.compile()            # 编译成可执行对象（Runnable！）

    result = graph.invoke({"count": 3, "history": []})
    console.print(f"初始 count=3，最终 count={result['count']}")
    for line in result["history"]:
        console.print(f"  [dim]{line}[/dim]")
    console.print(
        "[yellow]状态像水流一样依次流过节点，每个节点只改自己关心的字段。\n"
        "compile() 的产物也是 Runnable —— invoke/stream/batch 全都支持。[/yellow]\n"
    )


# ============================================================
# 演示 2：图能画出自己 —— draw_mermaid
# ============================================================

def demo_2_draw_mermaid() -> None:
    """代码即文档：graph.get_graph().draw_mermaid() 输出 mermaid 源码。

    把输出粘到任何支持 mermaid 的地方（比如本课程的 README）就能看图。
    流程复杂之后，这是排查「图连错了」的利器。
    """
    console.rule("[bold cyan]演示 2：让图画出自己")

    builder = StateGraph(CounterState)
    builder.add_node("add_one", add_one)
    builder.add_node("double", double)
    builder.add_edge(START, "add_one")
    builder.add_edge("add_one", "double")
    builder.add_edge("double", END)
    graph = builder.compile()

    console.print(Panel(graph.get_graph().draw_mermaid(), title="draw_mermaid() 输出", border_style="blue"))


# ============================================================
# 演示 3：提示链（Prompt Chaining）工作流 —— 需要 LLM Key
# ============================================================

class WriterState(TypedDict):
    """博客写作流水线的状态：每个节点填一个字段。"""

    topic: str
    outline: str
    draft: str
    polished: str


def make_writer_graph():
    """组装「大纲 -> 草稿 -> 润色」三连节点。

    这正是 03 模块一章讲的 Workflow 模式之一「提示链」：
    把大任务拆成几次简单调用，每步可检查、可调试。
    """
    from lc_client import get_chat_model

    model = get_chat_model()

    def write_outline(state: WriterState) -> dict:
        reply = model.invoke(f"为博客文章《{state['topic']}》列一个3点大纲，每点一行，只输出大纲。")
        return {"outline": reply.content}

    def write_draft(state: WriterState) -> dict:
        reply = model.invoke(
            f"按大纲写一段120字以内的博客开篇：\n标题：{state['topic']}\n大纲：\n{state['outline']}"
        )
        return {"draft": reply.content}

    def polish(state: WriterState) -> dict:
        reply = model.invoke(f"润色这段文字，使其更口语化、更吸引人，长度不变：\n{state['draft']}")
        return {"polished": reply.content}

    builder = StateGraph(WriterState)
    builder.add_node("outline", write_outline)
    builder.add_node("draft", write_draft)
    builder.add_node("polish", polish)
    builder.add_edge(START, "outline")
    builder.add_edge("outline", "draft")
    builder.add_edge("draft", "polish")
    builder.add_edge("polish", END)
    return builder.compile()


def demo_3_prompt_chain() -> None:
    console.rule("[bold cyan]演示 3：提示链工作流（需要 LLM Key）")

    graph = make_writer_graph()

    # 用 stream 观察每个节点完成时的状态更新（stream_mode="updates"）
    final: dict = {}
    for update in graph.stream(
        {"topic": "为什么前端工程师应该学一点 Agent 开发"},
        stream_mode="updates",
    ):
        node_name = next(iter(update))
        console.print(f"  [magenta]节点 {node_name} 完成[/magenta]")
        final.update(update[node_name])

    console.print(Panel(final["polished"], title="最终成稿", border_style="green"))


if __name__ == "__main__":
    demo_1_minimal_graph()
    demo_2_draw_mermaid()
    demo_3_prompt_chain()
    console.print("\n[bold green]本章完成！下一章给图加上「判断力」：条件路由与循环。[/bold green]")
