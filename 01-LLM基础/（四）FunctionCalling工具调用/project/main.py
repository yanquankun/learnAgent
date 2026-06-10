"""
（四）Function Calling 工具调用 —— 演示入口

LLM 本身只会「生成文字」：它不知道现在几点、不会做精确计算、查不了数据库。
Function Calling（也叫 Tool Calling）让模型能够「请求调用你写的函数」，
这是从聊天机器人迈向 Agent 最关键的一步。

【必须先想明白的一件事】
模型并不会真的执行函数！它只会输出「我想调用 xxx 函数，参数是 yyy」，
真正执行函数的是你的 Python 代码，执行结果还要由你喂回给模型。

本章演示：
    演示 1：观察模型发起的 tool_calls 长什么样（只看不执行）
    演示 2：完整的工具调用闭环（调用 -> 执行 -> 回传 -> 最终回答）
    演示 3：多工具 + 多轮循环（模型连续调用多个工具完成任务）

运行方式：
    cd 到本 project 目录 -> uv sync -> uv run python main.py
"""

import json
from datetime import datetime

from rich.console import Console
from rich.panel import Panel

from llm_client import MODEL, get_client

console = Console()
client = get_client()


# ---------------------------------------------------------------------------
# 第一步：用 Python 实现工具函数（普通函数，没有任何魔法）
# ---------------------------------------------------------------------------
def get_current_time() -> str:
    """返回当前日期和时间。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S（%A）")


def calculate(expression: str) -> str:
    """计算一个数学表达式，例如 '38 * 17 + 5'。"""
    # 真实项目中不要用裸 eval（任意代码执行风险）！
    # 这里限制了可用字符，仅作教学演示
    allowed = set("0123456789+-*/.() ")
    if not set(expression) <= allowed:
        return "错误：表达式包含不允许的字符"
    try:
        return str(eval(expression))  # noqa: S307 —— 已做字符白名单限制
    except Exception as e:
        return f"计算出错：{e}"


def search_blog(keyword: str) -> str:
    """按关键词搜索博客文章（本章先用假数据模拟，02-RAG 模块会换成真实检索）。"""
    fake_db = {
        "vite": "《webpack迁移Vite实录》—— 讲述构建工具迁移的三个坑",
        "react": "《React useEffect 原理解析》—— 深入依赖数组与执行时机",
        "docker": "《Docker Compose 部署实战》—— 多容器编排入门",
    }
    for key, article in fake_db.items():
        if key in keyword.lower():
            return article
    return "没有找到相关文章"


# ---------------------------------------------------------------------------
# 第二步：编写「工具说明书」（tools schema）
#
# 模型看不到你的 Python 代码，它只能看到这份 JSON 格式的说明书。
# description 写得越清楚，模型调用得越准 —— 这本身就是一种 Prompt 工程！
# ---------------------------------------------------------------------------
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "获取当前的日期和时间。当用户询问时间、日期、星期几时使用。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "计算数学表达式的精确结果。涉及数字计算时必须使用本工具，不要心算。",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Python 语法的数学表达式，如 '38 * 17 + 5'",
                    }
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_blog",
            "description": "按关键词搜索博客文章，返回文章标题和简介。用户询问博客内容时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "搜索关键词，如 'vite'"}
                },
                "required": ["keyword"],
            },
        },
    },
]

# 工具名 -> Python 函数 的映射表，执行时按名字查找
TOOL_REGISTRY = {
    "get_current_time": get_current_time,
    "calculate": calculate,
    "search_blog": search_blog,
}


def demo_1_see_tool_call() -> None:
    """演示 1：只观察，不执行 —— 看看模型发起的 tool_calls 长什么样。"""
    console.rule("[bold cyan]演示 1：模型发起的 tool_calls 结构")

    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": "现在几点了？"}],
        tools=TOOLS,  # 把工具说明书递给模型
    )

    message = response.choices[0].message
    # 当模型决定调用工具时：content 为空，tool_calls 里是调用请求
    console.print(f"finish_reason : {response.choices[0].finish_reason}  [dim]# 注意变成了 tool_calls[/dim]")
    console.print(f"content       : {message.content!r}  [dim]# 没有文字回答[/dim]")
    for tc in message.tool_calls:
        console.print(
            f"tool_calls    : id={tc.id}\n"
            f"                函数名={tc.function.name}\n"
            f"                参数(JSON字符串)={tc.function.arguments!r}"
        )
    console.print("[yellow]模型只是「请求」调用工具，函数并没有被执行 —— 执行是我们代码的事。[/yellow]\n")


def run_with_tools(question: str, max_rounds: int = 5) -> str:
    """演示 2/3 共用：完整的工具调用循环。

    流程（这个循环就是 Agent 的雏形，03 模块会基于它构建真正的 Agent）：
        1. 把 问题 + 工具说明书 发给模型
        2. 模型若返回 tool_calls -> 逐个执行函数 -> 把结果以 tool 消息回传
        3. 重复第 2 步，直到模型不再调用工具，输出最终文字回答
    """
    messages = [
        {"role": "system", "content": "你是一个助手，优先使用工具获取准确信息，不要凭空编造。"},
        {"role": "user", "content": question},
    ]

    for round_no in range(1, max_rounds + 1):
        response = client.chat.completions.create(model=MODEL, messages=messages, tools=TOOLS)
        message = response.choices[0].message

        # 模型不再调用工具 -> 这就是最终回答，循环结束
        if not message.tool_calls:
            return message.content

        # 重要：必须把模型的 tool_calls 消息原样追加进历史，
        # 否则下一轮模型不知道自己请求过什么
        messages.append(message)

        for tc in message.tool_calls:
            func_name = tc.function.name
            # 参数是 JSON 字符串，需要先解析成 dict
            func_args = json.loads(tc.function.arguments)
            console.print(f"  [blue]第{round_no}轮[/blue] 模型调用 {func_name}({func_args})")

            # 从注册表找到真正的 Python 函数并执行
            result = TOOL_REGISTRY[func_name](**func_args)
            console.print(f"         执行结果 -> {result}")

            # 把执行结果以 role="tool" 的消息回传给模型
            # tool_call_id 用于对应「哪一次调用请求」（一轮可能有多个调用）
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": str(result),
                }
            )

    return "（达到最大轮数限制，强制结束）"


def demo_2_full_loop() -> None:
    """演示 2：完整闭环 —— 一次工具调用 + 最终回答。"""
    console.rule("[bold cyan]演示 2：完整的工具调用闭环")
    answer = run_with_tools("帮我算一下 38 * 17 + 5 等于多少？")
    console.print(Panel(answer, title="最终回答", border_style="green"))


def demo_3_multi_tools() -> None:
    """演示 3：一个问题触发多个工具、多轮调用。

    模型需要自己规划：先查时间 -> 再搜文章 -> 综合成最终回答。
    注意观察打印出来的调用顺序 —— 这种「自主规划」就是 Agent 的核心特征。
    """
    console.rule("[bold cyan]演示 3：多工具多轮调用")
    answer = run_with_tools("今天是星期几？另外帮我找找博客里有没有讲 vite 的文章。")
    console.print(Panel(answer, title="最终回答", border_style="green"))


if __name__ == "__main__":
    demo_1_see_tool_call()
    demo_2_full_loop()
    demo_3_multi_tools()
    console.print("\n[bold green]本章演示全部完成！你已经写出了 Agent 的雏形（工具调用循环）。[/bold green]")
