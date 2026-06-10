"""
（一）认识 LLM 与第一次 API 调用 —— 演示入口

本脚本演示 LLM 应用开发中最核心的一次交互：
    构造 messages 消息列表 -> 调用 Chat Completions API -> 解析返回结果

运行方式（两种任选其一）：
    1. PyCharm：直接点本文件的绿色运行箭头
    2. 终端：  cd 到本 project 目录后执行  uv run python main.py

前置条件：已在仓库根目录配置好 .env（参考根目录 README.md）
"""

from rich.console import Console
from rich.panel import Panel

from llm_client import MODEL, get_client

# rich 是一个让终端输出更好看的库，和 LLM 无关，纯粹为了学习体验
console = Console()


def demo_1_first_call() -> None:
    """演示 1：最简单的一次 LLM 调用。

    核心概念 —— messages 消息列表：
    LLM 的 Chat API 不是「发一句话、回一句话」，而是「发一个消息列表」。
    列表里的每条消息都有一个 role（角色）：

      - system   : 系统提示词。给模型设定身份、规则、输出要求。用户看不到。
      - user     : 用户消息。真正的提问内容。
      - assistant: 模型的历史回复。多轮对话时要把之前的回复带上（第五章细讲）。
    """
    console.rule("[bold cyan]演示 1：第一次 API 调用")

    client = get_client()

    response = client.chat.completions.create(
        model=MODEL,  # 使用哪个模型，读取自 .env 的 LLM_MODEL
        messages=[
            # system 消息：设定模型的「人设」和行为边界
            {
                "role": "system",
                "content": "你是一位资深的编程导师，回答务必简洁，不超过100字。",
            },
            # user 消息：用户的实际提问
            {
                "role": "user",
                "content": "用一句话解释：什么是大语言模型（LLM）？",
            },
        ],
    )

    # response 的结构（重点记住这条取值路径）：
    #   response.choices[0].message.content  -> 模型回复的文本
    answer = response.choices[0].message.content
    console.print(Panel(answer, title="模型回复", border_style="green"))

    # usage 字段记录了本次调用消耗的 token 数 —— 这是 LLM 计费的依据，
    # 也是后面「监控与评估」模块里要采集的核心指标之一
    usage = response.usage
    console.print(
        f"[dim]token 消耗：输入 {usage.prompt_tokens} + "
        f"输出 {usage.completion_tokens} = 总计 {usage.total_tokens}[/dim]"
    )


def demo_2_inspect_response() -> None:
    """演示 2：完整观察一次 API 返回的数据结构。

    新手常犯的错误是只知道取 content，对返回结构一知半解。
    这里把重要字段都打印出来，建议逐个对照理解。
    """
    console.rule("[bold cyan]演示 2：解剖 API 返回结构")

    client = get_client()
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": "你好"}],
    )

    console.print(f"id            : {response.id}            [dim]# 本次请求的唯一标识，排查问题用[/dim]")
    console.print(f"model         : {response.model}         [dim]# 实际使用的模型[/dim]")
    console.print(f"created       : {response.created}       [dim]# 创建时间戳[/dim]")

    choice = response.choices[0]
    console.print(f"finish_reason : {choice.finish_reason}   [dim]# 结束原因，见下方说明[/dim]")
    console.print(f"role          : {choice.message.role}    [dim]# 回复的角色，固定是 assistant[/dim]")
    console.print(f"content       : {choice.message.content!r}")

    console.print()
    console.print(
        "[yellow]finish_reason 的常见取值：[/yellow]\n"
        "  stop       -> 模型自然说完了（正常情况）\n"
        "  length     -> 达到 max_tokens 上限被截断（回答不完整，要警惕！）\n"
        "  tool_calls -> 模型要求调用工具（第四章的主角）"
    )


def demo_3_temperature() -> None:
    """演示 3：temperature 参数 —— 控制回答的随机性。

    temperature 越低 -> 输出越稳定、确定（适合：代码生成、知识问答、RAG）
    temperature 越高 -> 输出越发散、有创意（适合：写文案、头脑风暴）

    我们用同一个问题各调用 2 次，观察输出差异。
    """
    console.rule("[bold cyan]演示 3：temperature 对输出的影响")

    client = get_client()
    question = "给一个程序员博客起一个名字，只输出名字本身"

    for temp in (0.0, 1.5):
        console.print(f"\n[bold]temperature = {temp}[/bold]")
        for i in range(2):
            response = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": question}],
                temperature=temp,   # 随机性：0 最稳定，越大越随机
                max_tokens=50,      # 限制回复最多生成多少 token，防止超长输出
            )
            console.print(f"  第{i + 1}次 -> {response.choices[0].message.content}")

    console.print(
        "\n[yellow]观察结论：temperature=0 时两次输出几乎相同；"
        "1.5 时差异明显。\n做 RAG / Agent 这类「要求准确」的应用，"
        "建议用 0 ~ 0.3。[/yellow]"
    )


if __name__ == "__main__":
    demo_1_first_call()
    demo_2_inspect_response()
    demo_3_temperature()
    console.print("\n[bold green]本章演示全部完成！可以开始阅读《（二）Prompt工程基础》了。[/bold green]")
