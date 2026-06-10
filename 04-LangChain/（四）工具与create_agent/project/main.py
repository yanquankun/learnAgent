"""
（四）工具与 create_agent —— 演示入口

03 模块你手写了：@tool 装饰器（自动生成 schema）、工具注册表、
Function Calling 循环、错误自我纠正。本章看 LangChain 1.x 的官方答案：

    演示 1：@tool 装饰器 —— 和我们手写版几乎一模一样（验证你学对了）
    演示 2：create_agent —— 一行替代手写的 Agent 循环
    演示 3：流式观察中间步骤 —— 工具调用过程全透明
    演示 4：错误自我纠正 —— 框架内置了我们手写的「错误即信息」

运行方式（全部需要 LLM Key）：
    cd 到本 project 目录 -> uv sync -> uv run python main.py
"""

import json
from datetime import datetime

from langchain.agents import create_agent
from langchain_core.tools import tool
from rich.console import Console
from rich.panel import Panel

from lc_client import get_chat_model

console = Console()


# ============================================================
# 第一部分：用 @tool 定义工具（对照 03 模块手写的 tools.py）
# ============================================================

@tool
def get_now() -> str:
    """获取当前日期和时间。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S 星期%w")


@tool
def calculate(expression: str) -> str:
    """计算一个数学表达式，例如 '365 * 24' 或 '(100 - 17) / 3'。

    Args:
        expression: 合法的 Python 数学表达式，只能包含数字和 + - * / ( ) 符号
    """
    allowed = set("0123456789+-*/(). ")
    if not set(expression) <= allowed:
        raise ValueError(f"表达式包含不允许的字符：{set(expression) - allowed}")
    return str(eval(expression))  # noqa: S307（已做字符白名单）


# 模拟博客检索（真实 RAG 版在 05 模块四章用 LangGraph 实现）
FAKE_BLOG = [
    {"id": "react-useeffect", "title": "React useEffect 依赖数组的常见陷阱", "tags": "react,hooks"},
    {"id": "vite-migration", "title": "webpack 迁移 Vite 实录", "tags": "vite,build"},
    {"id": "docker-deploy", "title": "Docker Compose 部署实战", "tags": "docker,devops"},
]


@tool
def search_blog(keyword: str) -> str:
    """按关键词搜索博客文章，返回匹配的文章列表（JSON 格式）。

    Args:
        keyword: 搜索关键词，例如 'react' 或 'docker'
    """
    hits = [
        a for a in FAKE_BLOG
        if keyword.lower() in (a["title"] + a["tags"]).lower()
    ]
    if not hits:
        return f"没有找到包含「{keyword}」的文章"
    return json.dumps(hits, ensure_ascii=False)


def demo_1_inspect_tool() -> None:
    """演示 1：看看 @tool 自动生成了什么 —— 和你手写的注册表对照。

    我们 03 模块手写的 @tool 做的事：函数名->工具名、docstring->描述、
    类型注解->参数 schema。LangChain 官方版完全一样（殊途同归！）。
    """
    console.rule("[bold cyan]演示 1：@tool 生成的 schema")
    console.print(f"name        : {calculate.name}")
    console.print(f"description : {calculate.description}")
    console.print(f"args_schema : {json.dumps(calculate.args, ensure_ascii=False)}")
    console.print("[yellow]对照 03 模块三章你手写的 @tool 装饰器 —— 思路一模一样。[/yellow]\n")


def demo_2_create_agent() -> None:
    """演示 2：create_agent —— 一行替代 03 模块手写的 Agent 类。

    你手写的 Agent.run() 里的循环（调模型 -> 解析 tool_calls -> 执行 ->
    结果回填 -> 再调模型），create_agent 全部内置。
    """
    console.rule("[bold cyan]演示 2：create_agent")

    agent = create_agent(
        model=get_chat_model(),
        tools=[get_now, calculate, search_blog],
        system_prompt="你是博客网站的AI助手，回答简洁，优先使用工具获取准确信息。",
    )

    result = agent.invoke(
        {"messages": [("user", "今天星期几？另外帮我找找关于 docker 的文章")]}
    )
    console.print(Panel(result["messages"][-1].content, title="Agent 最终回答", border_style="green"))
    console.print(f"[dim]本轮共产生 {len(result['messages'])} 条消息（含工具调用与结果）[/dim]\n")


def demo_3_stream_steps() -> None:
    """演示 3：流式观察 Agent 的每一步 —— 不再是黑盒。

    agent.stream(..., stream_mode='values') 每一步吐出完整状态，
    我们打印最新一条消息，就能看到 模型决策 -> 工具结果 -> 最终回答 的全过程。
    （这其实是 LangGraph 的能力 —— create_agent 底层就是一张 LangGraph 图！）
    """
    console.rule("[bold cyan]演示 3：流式观察中间步骤")

    agent = create_agent(
        model=get_chat_model(),
        tools=[get_now, calculate, search_blog],
        system_prompt="你是计算助手，必须使用工具计算。",
    )

    for step in agent.stream(
        {"messages": [("user", "一年365天共有多少小时？再乘以60是多少分钟？")]},
        stream_mode="values",
    ):
        msg = step["messages"][-1]
        kind = type(msg).__name__
        if getattr(msg, "tool_calls", None):
            calls = ", ".join(f"{c['name']}({c['args']})" for c in msg.tool_calls)
            console.print(f"  [magenta]{kind}[/magenta] 请求调用 -> {calls}")
        else:
            text = str(msg.content)[:80]
            console.print(f"  [magenta]{kind}[/magenta] {text}")
    console.print()


def demo_4_self_correction() -> None:
    """演示 4：错误自我纠正 —— 框架版的「错误即信息」。

    故意诱导模型先写出带中文符号的表达式，calculate 抛异常后，
    create_agent 会把异常文本作为工具结果喂回模型，模型自行修正重试
    —— 03 模块三章我们手写的 execute() 错误处理，框架同样内置了。
    """
    console.rule("[bold cyan]演示 4：错误自我纠正")

    agent = create_agent(
        model=get_chat_model(),
        tools=[calculate],
        system_prompt="你是计算助手，必须使用 calculate 工具。",
    )

    for step in agent.stream(
        {"messages": [("user", "帮我算：（一百减十七）除以三，注意我说的是中文数字")]},
        stream_mode="values",
    ):
        msg = step["messages"][-1]
        if type(msg).__name__ == "ToolMessage":
            console.print(f"  [red]工具返回：{str(msg.content)[:80]}[/red]")
        elif getattr(msg, "tool_calls", None):
            console.print(f"  [magenta]模型尝试：{msg.tool_calls[0]['args']}[/magenta]")
        else:
            console.print(f"  最终回答：{str(msg.content)[:100]}")


if __name__ == "__main__":
    demo_1_inspect_tool()       # 此演示离线可跑
    demo_2_create_agent()
    demo_3_stream_steps()
    demo_4_self_correction()
    console.print(
        "\n[bold green]模块 04 完成！create_agent 返回的其实是一张 LangGraph 图 —— "
        "下个模块我们把这张图亲手画出来。[/bold green]"
    )
