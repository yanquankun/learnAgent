"""
（五）流式输出与多轮对话 —— 演示入口

本章解决两个真实产品必备的体验问题：
    演示 1：流式输出 —— 像 ChatGPT 一样逐字「打字」，不让用户干等
    演示 2：多轮对话 —— 模型本身没有记忆，「记忆」是靠每次重发历史实现的
    演示 3：交互式聊天 —— 综合前两者，做一个命令行版的「博客聊天框」

运行方式：
    cd 到本 project 目录 -> uv sync -> uv run python main.py
    演示 3 是交互式的，输入 /exit 退出，/clear 清空记忆
"""

from rich.console import Console

from llm_client import MODEL, get_client

console = Console()
client = get_client()


def demo_1_streaming() -> None:
    """演示 1：流式输出。

    非流式：等模型生成完所有 token，一次性返回 —— 长回答要等好几秒
    流式　：生成一个 token 就推送一个 —— 首字延迟极低，体验好得多

    实现上只需两步：
      1. 请求时加 stream=True
      2. 用 for 循环逐块（chunk）读取，每块的增量文本在 chunk.choices[0].delta.content
    """
    console.rule("[bold cyan]演示 1：流式输出（注意观察逐字出现的效果）")

    stream = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": "用100字左右介绍一下什么是流式输出，以及它对聊天产品体验的意义。"}],
        stream=True,  # 关键参数：开启流式
    )

    full_text = ""
    for chunk in stream:
        # delta 是「增量」：这一块新生成的几个字符（也可能是空）
        delta = chunk.choices[0].delta.content
        if delta:
            full_text += delta
            # end="" 不换行，flush=True 立即显示 —— 这就是打字机效果
            print(delta, end="", flush=True)
    print("\n")
    console.print(f"[dim]完整回答共 {len(full_text)} 个字符，是一块一块拼出来的。[/dim]")
    console.print(
        "[yellow]Web 场景中，后端用 SSE（Server-Sent Events）把这些块持续推给浏览器，\n"
        "你的博客聊天框就是这样实现打字效果的（实战模块会写）。[/yellow]\n"
    )


def demo_2_no_memory() -> None:
    """演示 2：戳破一个关键认知 —— 模型本身没有任何记忆！

    HTTP API 是无状态的：每次调用都是全新的开始。
    所谓「多轮对话」，其实是客户端把完整历史在每次请求时重新发一遍。
    """
    console.rule("[bold cyan]演示 2：模型没有记忆")

    # 第一次调用：告诉模型我的名字
    r1 = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": "你好，我叫小明，是一名前端工程师。"}],
    )
    console.print(f"[green]第1次调用[/green] 模型：{r1.choices[0].message.content[:60]}……")

    # 第二次调用：不带历史，直接问名字 —— 模型不可能知道
    r2 = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": "我叫什么名字？"}],
    )
    console.print(f"[red]第2次调用（不带历史）[/red] 模型：{r2.choices[0].message.content[:60]}……")

    # 第三次调用：把完整历史带上 —— 模型就「记得」了
    r3 = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "user", "content": "你好，我叫小明，是一名前端工程师。"},
            {"role": "assistant", "content": r1.choices[0].message.content},
            {"role": "user", "content": "我叫什么名字？"},
        ],
    )
    console.print(f"[green]第3次调用（带完整历史）[/green] 模型：{r3.choices[0].message.content[:60]}……")
    console.print("[yellow]结论：「记忆」= 每次请求都重发历史消息。历史越长，消耗的 token 越多。[/yellow]\n")


class ChatSession:
    """一个最简单的多轮对话会话管理器。

    职责：
      1. 维护 messages 历史列表（system 提示词固定在第一条）
      2. 历史过长时做「裁剪」—— 只保留最近 N 轮，防止 token 爆炸
      3. 提供流式回复

    这就是聊天产品后端 session 的最小模型，
    03-Agent 模块的「记忆管理」章节会在此基础上升级（按 token 裁剪、摘要压缩）。
    """

    # 最多保留的对话轮数（1 轮 = 1 条 user + 1 条 assistant）
    MAX_TURNS = 8

    def __init__(self, system_prompt: str):
        self.system_prompt = system_prompt
        self.history: list[dict] = []  # 只存 user/assistant 消息，system 单独管理

    def _build_messages(self) -> list[dict]:
        """组装本次请求的完整 messages：system + 裁剪后的历史。"""
        # 裁剪策略：只保留最近 MAX_TURNS 轮（从后往前数 MAX_TURNS*2 条）
        trimmed = self.history[-self.MAX_TURNS * 2:]
        return [{"role": "system", "content": self.system_prompt}, *trimmed]

    def ask_stream(self, user_input: str) -> str:
        """发送用户消息，流式打印并返回完整回复。"""
        self.history.append({"role": "user", "content": user_input})

        stream = client.chat.completions.create(
            model=MODEL,
            messages=self._build_messages(),
            stream=True,
            temperature=0.7,
        )

        full_reply = ""
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                full_reply += delta
                print(delta, end="", flush=True)
        print()

        # 把模型回复也存进历史，下一轮才能「记得」
        self.history.append({"role": "assistant", "content": full_reply})
        return full_reply

    def clear(self) -> None:
        """清空对话记忆。"""
        self.history.clear()


def demo_3_interactive_chat() -> None:
    """演示 3：交互式聊天 —— 命令行版「博客聊天框」雏形。

    支持的命令：
        /exit  退出
        /clear 清空对话记忆（清空后模型就不记得之前聊的内容了，可以验证）
    """
    console.rule("[bold cyan]演示 3：交互式多轮聊天（/exit 退出，/clear 清空记忆）")

    session = ChatSession(
        system_prompt=(
            "你是「小博」，一个技术博客的AI助手，性格友好，回答简洁。"
            "你擅长前端、Python 和 AI 应用开发话题。"
        )
    )

    while True:
        try:
            user_input = console.input("\n[bold blue]你 >[/bold blue] ").strip()
        except (KeyboardInterrupt, EOFError):
            break

        if not user_input:
            continue
        if user_input == "/exit":
            break
        if user_input == "/clear":
            session.clear()
            console.print("[yellow]（记忆已清空）[/yellow]")
            continue

        console.print("[bold magenta]小博 >[/bold magenta] ", end="")
        session.ask_stream(user_input)

    console.print("\n[dim]再见！[/dim]")


if __name__ == "__main__":
    demo_1_streaming()
    demo_2_no_memory()
    demo_3_interactive_chat()
    console.print("\n[bold green]恭喜完成 01-LLM基础 模块！可以进入 02-RAG 模块了。[/bold green]")
