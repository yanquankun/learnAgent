"""
（四）LangGraph Agent 与工具 —— 演示入口

亲手搭出 create_agent 的内部构造：模型节点 + 工具节点 + 条件边。

    演示 1：手工搭 Agent 图 —— bind_tools + ToolNode + tools_condition
    演示 2：BlogAgent 图化版 —— 接上真实 RAG 工具，流式观察决策过程

与第三章的本质区别：
    第三章（Workflow）：走哪条路由「我们写的规则」决定
    本章（Agent）   ：调不调工具、调几次由「模型自己」决定

运行方式：
    cd 到本 project 目录 -> uv sync -> uv run python main.py（需要 LLM Key）
"""

from langchain_core.messages import SystemMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from rich.console import Console
from rich.panel import Panel

from blog_tools import BLOG_TOOLS, ensure_index
from lc_client import get_chat_model

console = Console()

SYSTEM_PROMPT = (
    "你是技术博客的AI助手。回答用户问题时优先用 search_blog 检索博客内容，"
    "根据检索结果回答并注明来源文章；检索不到就诚实说明。回答控制在150字内。"
)


def build_agent_graph():
    """手工搭建 Agent 图 —— 这就是 create_agent 帮你做的事。

    三个零件：
      1. bind_tools：把工具 schema 挂到模型上（01 模块四章的 tools= 参数）
      2. ToolNode：预制的工具执行节点（执行 tool_calls、产出 ToolMessage、
         异常自动转为错误信息 —— 03 模块手写的 execute() 它全包了）
      3. tools_condition：预制路由（有 tool_calls 去工具节点，没有就 END
         —— 03 模块手写循环里的那个 if）
    """
    model_with_tools = get_chat_model().bind_tools(BLOG_TOOLS)

    def call_model(state: MessagesState) -> dict:
        """模型节点。MessagesState 是预制状态：{'messages': [...]}，
        自带「追加合并」逻辑 —— 返回的消息会 append 而不是覆盖。"""
        messages = [SystemMessage(SYSTEM_PROMPT), *state["messages"]]
        reply = model_with_tools.invoke(messages)
        return {"messages": [reply]}

    builder = StateGraph(MessagesState)
    builder.add_node("model", call_model)
    builder.add_node("tools", ToolNode(BLOG_TOOLS))

    builder.add_edge(START, "model")
    builder.add_conditional_edges("model", tools_condition, {"tools": "tools", END: END})
    builder.add_edge("tools", "model")   # 工具跑完回到模型 —— Agent 循环成型
    return builder.compile()


def demo_1_structure() -> None:
    console.rule("[bold cyan]演示 1：手工搭出的 Agent 图（即 create_agent 的内脏）")
    graph = build_agent_graph()
    console.print(Panel(graph.get_graph().draw_mermaid(), title="Agent 图结构", border_style="blue"))
    console.print(
        "[yellow]model -> tools -> model 的回边构成循环；"
        "tools_condition 决定继续调工具还是结束。\n"
        "对照 03 模块三章你手写的 Agent.run() —— 同一个循环，两种表达。[/yellow]\n"
    )


def demo_2_blog_agent() -> None:
    console.rule("[bold cyan]演示 2：BlogAgent 图化版（真实 RAG 工具）")
    graph = build_agent_graph()

    questions = [
        "博客里都有哪些文章？",
        "useEffect 在开发环境为什么执行两次？怎么解决？",
    ]
    for q in questions:
        console.print(f"\n提问：[bold]{q}[/bold]")
        for step in graph.stream(
            {"messages": [("user", q)]},
            stream_mode="values",
        ):
            msg = step["messages"][-1]
            if getattr(msg, "tool_calls", None):
                for call in msg.tool_calls:
                    console.print(f"  [magenta]模型决定调用 {call['name']}({call['args']})[/magenta]")
            elif type(msg).__name__ == "ToolMessage":
                console.print(f"  [dim]工具返回：{str(msg.content)[:80]}……[/dim]")
            elif type(msg).__name__ == "AIMessage":
                console.print(Panel(str(msg.content), title="最终回答", border_style="green"))


if __name__ == "__main__":
    console.print("[bold]检查/构建索引……[/bold]")
    ensure_index()
    demo_1_structure()
    demo_2_blog_agent()
    console.print(
        "\n[bold green]本章完成！这个 BlogAgent 还是「金鱼记忆」——"
        "下一章用 checkpointer 给它装上跨进程的持久记忆。[/bold green]"
    )
