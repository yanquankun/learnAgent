"""
（五）持久化、人工介入与流式 —— 演示入口（05 模块收官）

生产级 Agent 的最后三件套：

    演示 1：checkpointer + thread_id —— 多用户会话隔离（内存版）
    演示 2：SQLite checkpointer —— 重启进程，记忆还在！（多次运行本脚本验证）
    演示 3：interrupt 人工审批 —— 危险操作先「请示人类」（离线可跑）
    演示 4：三种 stream 模式 —— values / updates / messages（逐 token）

运行方式：
    cd 到本 project 目录 -> uv sync -> uv run python main.py
    （演示 3 离线可跑；其余需要 LLM Key）
"""

import sqlite3
from typing import TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.types import Command, interrupt
from rich.console import Console
from rich.panel import Panel

console = Console()


# ============================================================
# 公用：最简聊天图（一个模型节点 + 记忆全靠 checkpointer）
# ============================================================

def build_chat_graph(checkpointer):
    """对照 03 模块四章：手写记忆要自己维护 history 列表、裁剪、传参；
    LangGraph 把「状态保存/恢复」抽成了 checkpointer —— 图跑完每一步，
    状态自动存档；带着同一个 thread_id 再来，状态自动恢复。"""
    from lc_client import get_chat_model

    model = get_chat_model()

    def chat(state: MessagesState) -> dict:
        reply = model.invoke(
            [("system", "你是简洁的AI助手，回答不超过40字。"), *state["messages"]]
        )
        return {"messages": [reply]}

    builder = StateGraph(MessagesState)
    builder.add_node("chat", chat)
    builder.add_edge(START, "chat")
    builder.add_edge("chat", END)
    return builder.compile(checkpointer=checkpointer)  # 编译时挂上存档器


def demo_1_thread_memory() -> None:
    """演示 1：thread_id = 会话编号。不同 thread 的记忆完全隔离。"""
    console.rule("[bold cyan]演示 1：checkpointer + thread_id（会话隔离）")

    graph = build_chat_graph(InMemorySaver())
    alice = {"configurable": {"thread_id": "alice"}}
    bob = {"configurable": {"thread_id": "bob"}}

    graph.invoke({"messages": [("user", "我叫Alice，最喜欢React")]}, alice)
    graph.invoke({"messages": [("user", "我叫Bob，最喜欢Vue")]}, bob)

    r1 = graph.invoke({"messages": [("user", "我叫什么？喜欢什么框架？")]}, alice)
    r2 = graph.invoke({"messages": [("user", "我叫什么？喜欢什么框架？")]}, bob)
    console.print(f"alice 线程：[green]{r1['messages'][-1].content}[/green]")
    console.print(f"bob   线程：[green]{r2['messages'][-1].content}[/green]")
    console.print("[yellow]同一张图、两份独立记忆 —— 多用户聊天服务的地基。[/yellow]\n")


def demo_2_sqlite_persistence() -> None:
    """演示 2：SQLite 存档 —— 关掉进程，记忆还在。

    第一次运行：告诉它你的名字。
    第二次运行（重新执行本脚本！）：它还记得 —— 这是手写版（03模块四章，
    记忆存在 Python 列表里）做不到的跨进程持久化。
    """
    console.rule("[bold cyan]演示 2：SQLite 持久化（重启进程记忆不丢）")

    conn = sqlite3.connect("chat_memory.db", check_same_thread=False)
    graph = build_chat_graph(SqliteSaver(conn))
    config = {"configurable": {"thread_id": "long-term-user"}}

    # 先问它记不记得 —— 第一次运行必然不记得，第二次就记得了
    r = graph.invoke({"messages": [("user", "你还记得我是谁、在做什么项目吗？")]}, config)
    console.print(f"AI：[green]{r['messages'][-1].content}[/green]")

    graph.invoke(
        {"messages": [("user", "记住：我是Mint，正在做博客知识库Agent项目")]}, config
    )
    console.print("[yellow]已写入 chat_memory.db。请重新运行本脚本，看它还记不记得你！[/yellow]\n")
    conn.close()


# ============================================================
# 演示 3：interrupt 人工审批（离线可跑）
# ============================================================

class DeleteState(TypedDict):
    article_id: str
    result: str


def confirm_delete(state: DeleteState) -> dict:
    """审批节点：interrupt() 会把整张图「暂停」在这里。

    图的状态已被 checkpointer 存档，进程甚至可以退出；
    直到有人用 Command(resume=答复) 恢复，interrupt() 才带着答复返回。
    """
    approved = interrupt(
        {"action": "delete_article", "article_id": state["article_id"], "question": "确认删除吗？"}
    )
    if approved:
        return {"result": f"文章 {state['article_id']} 已删除（这里执行真正的删除逻辑）"}
    return {"result": "操作已取消"}


def demo_3_interrupt() -> None:
    console.rule("[bold cyan]演示 3：interrupt 人工审批（离线可跑）")

    builder = StateGraph(DeleteState)
    builder.add_node("confirm_delete", confirm_delete)
    builder.add_edge(START, "confirm_delete")
    builder.add_edge("confirm_delete", END)
    graph = builder.compile(checkpointer=InMemorySaver())  # interrupt 必须配 checkpointer

    config = {"configurable": {"thread_id": "approval-1"}}

    # 第一步：执行到 interrupt 处暂停
    result = graph.invoke({"article_id": "react-useeffect", "result": ""}, config)
    pause = result["__interrupt__"][0]
    console.print(f"图已暂停，等待审批：[yellow]{pause.value}[/yellow]")

    # 第二步：人类拍板（真实场景中这发生在另一个 HTTP 请求里！）
    result = graph.invoke(Command(resume=True), config)
    console.print(f"恢复执行（批准）：[green]{result['result']}[/green]")

    # 再来一个「拒绝」的线程
    config2 = {"configurable": {"thread_id": "approval-2"}}
    graph.invoke({"article_id": "vite-migration", "result": ""}, config2)
    result = graph.invoke(Command(resume=False), config2)
    console.print(f"恢复执行（拒绝）：[red]{result['result']}[/red]\n")


def demo_4_stream_modes() -> None:
    """演示 4：三种 stream 模式 —— 给前端的三种「直播信号」。

    values  ：每步之后的完整状态（适合调试）
    updates ：每步的增量更新（适合展示「Agent 正在做什么」）
    messages：LLM 的逐 token 输出（适合打字机效果，对接 SSE）
    """
    console.rule("[bold cyan]演示 4：三种 stream 模式")

    graph = build_chat_graph(InMemorySaver())
    config = {"configurable": {"thread_id": "stream-demo"}}
    question = {"messages": [("user", "一句话介绍LangGraph")]}

    console.print("[bold]stream_mode='updates'（节点级进度）：[/bold]")
    for update in graph.stream(question, config, stream_mode="updates"):
        console.print(f"  节点 {next(iter(update))} 完成")

    console.print("[bold]stream_mode='messages'（逐 token，打字机效果）：[/bold]  ", end="")
    for token, _metadata in graph.stream(question, config, stream_mode="messages"):
        print(token.content, end="", flush=True)
    print()
    console.print(
        "[yellow]实战（07模块）：messages 模式 + FastAPI SSE = 博客聊天框的打字机效果。[/yellow]"
    )


if __name__ == "__main__":
    demo_3_interrupt()        # 离线可跑，放最前面
    demo_1_thread_memory()
    demo_2_sqlite_persistence()
    demo_4_stream_modes()
    console.print(
        Panel(
            "模块 05 完成！你已经掌握：图、路由、循环、Agent 图、持久化、人工介入、流式。\n"
            "下一站模块 06：给这些能力装上「仪表盘」—— 日志、追踪、指标与评估。",
            border_style="green",
        )
    )
