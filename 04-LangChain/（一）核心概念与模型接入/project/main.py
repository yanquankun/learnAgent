"""
（一）LangChain 核心概念与模型接入 —— 演示入口

学了三个模块的「手写」之后，正式进入框架世界。本章演示 LangChain 最核心的
四件事，每一件都请回想你手写过的对应代码：

    演示 1：invoke 与消息对象（对照 client.chat.completions.create）
    演示 2：stream 流式（对照 01 模块五章的手动逐 chunk 处理）
    演示 3：batch 并发批量（手写版需要自己开线程池！）
    演示 4：Runnable 管道初体验（prompt | model 的「乐高式」组合）

运行方式：
    cd 到本 project 目录 -> uv sync -> uv run python main.py
"""

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from rich.console import Console
from rich.panel import Panel

from lc_client import get_chat_model

console = Console()
model = get_chat_model()


def demo_1_invoke() -> None:
    """演示 1：invoke —— 一次调用，消息从 dict 变成了「类型化对象」。

    手写版的 {"role": "system", "content": ...} 在 LangChain 里变成
    SystemMessage / HumanMessage / AIMessage 对象。
    返回值 AIMessage 自带 token 统计（usage_metadata）等元信息。
    """
    console.rule("[bold cyan]演示 1：invoke 与消息对象")

    reply = model.invoke(
        [
            SystemMessage("你是一位资深编程导师，回答不超过50字。"),
            HumanMessage("一句话说明 LangChain 是什么？"),
        ]
    )

    console.print(Panel(reply.content, title="AIMessage.content", border_style="green"))
    console.print(f"type           : {type(reply).__name__}   [dim]# AIMessage 对象，不是裸字符串[/dim]")
    console.print(f"usage_metadata : {reply.usage_metadata}   [dim]# token 统计，自动帮你解析好了[/dim]")
    console.print(
        "[yellow]对照手写版：response.choices[0].message.content 的取值链没有了，\n"
        "框架把「调用 + 解析 + 重试」都收进了 invoke 一个方法。[/yellow]\n"
    )


def demo_2_stream() -> None:
    """演示 2：stream —— 流式输出从「处理 delta」简化为「遍历 chunk」。"""
    console.rule("[bold cyan]演示 2：stream 流式输出")

    # 手写版要自己判断 chunk.choices[0].delta.content 是否为 None，
    # LangChain 直接产出 AIMessageChunk，content 永远是字符串
    for chunk in model.stream("用50字介绍流式输出的好处。"):
        print(chunk.content, end="", flush=True)
    print("\n")


def demo_3_batch() -> None:
    """演示 3：batch —— 并发批量调用，框架内置线程池。

    场景：给 4 篇博客文章标题同时生成标签（实战中批量索引时很常用）。
    手写版要自己用 concurrent.futures 开线程池，这里一行搞定。
    """
    console.rule("[bold cyan]演示 3：batch 并发批量")

    titles = [
        "React useEffect 依赖数组的常见陷阱",
        "webpack 迁移 Vite 实录",
        "Docker Compose 部署 Postgres",
        "浏览器事件循环机制详解",
    ]
    prompts = [f"为这篇文章生成2个英文标签，逗号分隔，只输出标签：{t}" for t in titles]

    # batch 内部并发执行（默认 max_concurrency 可配），总耗时约等于最慢的一次
    replies = model.batch(prompts)

    for title, reply in zip(titles, replies):
        console.print(f"  {title}  ->  [green]{reply.content}[/green]")
    console.print()


def demo_4_runnable_pipe() -> None:
    """演示 4：Runnable 管道 —— LangChain 的「乐高接口」。

    LangChain 中几乎一切组件（提示词模板、模型、解析器、检索器）都实现了
    Runnable 接口（invoke/stream/batch），所以可以用 | 把它们拼成管道：

        chain = prompt | model
        chain.invoke({"topic": "..."})

    数据像水流一样依次流过每个组件。下一章会拼出更长的管道。
    """
    console.rule("[bold cyan]演示 4：Runnable 管道初体验")

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", "你是技术博客作者，文风简洁。"),
            ("user", "用一句话向前端工程师解释：{topic}"),
        ]
    )

    # | 操作符把两个 Runnable 接成一个新的 Runnable
    chain = prompt | model

    reply = chain.invoke({"topic": "向量数据库"})
    console.print(Panel(reply.content, title='chain.invoke({"topic": "向量数据库"})', border_style="green"))
    console.print(
        "[yellow]管道本身也是 Runnable —— 同样支持 stream / batch。\n"
        "「组件实现统一接口 + 自由组合」正是 LangChain 设计的精髓。[/yellow]"
    )


if __name__ == "__main__":
    demo_1_invoke()
    demo_2_stream()
    demo_3_batch()
    demo_4_runnable_pipe()
    console.print("\n[bold green]本章完成！下一章用模板和结构化输出把管道拼得更长。[/bold green]")
