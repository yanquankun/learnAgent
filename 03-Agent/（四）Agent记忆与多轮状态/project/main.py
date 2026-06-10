"""
（四）Agent 记忆与多轮状态 —— 演示入口

上一章的 Agent 每次 run() 都是「失忆」的。本章给它装上记忆：
    演示 1：跨轮记忆 —— 「它」「刚才说的」这类指代能被正确理解
    演示 2：观察记忆压缩 —— 旧对话被 LLM 压缩成摘要，token 不再无限增长
    演示 3：交互式带记忆的聊天 Agent

运行方式：
    cd 到本 project 目录 -> uv sync -> uv run python main.py
"""

from rich.console import Console
from rich.panel import Panel

from llm_client import MODEL, get_client
from memory import ConversationMemory

console = Console()
client = get_client()

SYSTEM_PROMPT = (
    "你是「小博」，技术博客的AI助手。回答简洁，不超过80字。"
    "充分利用对话历史和摘要理解用户的指代（如「它」「刚才说的」）。"
)


class MemoryChatAgent:
    """带记忆的聊天 Agent。

    每轮对话：
        1. 用户消息写入记忆
        2. 用「system + 摘要 + 最近原文」组装上下文请求模型
        3. 模型回复也写入记忆
    记忆的滑动窗口和摘要压缩由 ConversationMemory 自动完成。
    """

    def __init__(self, max_recent_tokens: int = 2000):
        self.memory = ConversationMemory(max_recent_tokens=max_recent_tokens)

    def chat(self, user_input: str) -> str:
        self.memory.add("user", user_input)
        response = client.chat.completions.create(
            model=MODEL,
            messages=self.memory.build_messages(SYSTEM_PROMPT),
            temperature=0.3,
        )
        reply = response.choices[0].message.content
        self.memory.add("assistant", reply)
        return reply


def demo_1_cross_turn_memory() -> None:
    """演示 1：跨轮指代 —— 记忆让「它」有了着落。"""
    console.rule("[bold cyan]演示 1：跨轮记忆与指代理解")

    agent = MemoryChatAgent()
    turns = [
        "我的博客是用 Vite 构建的，部署在阿里云上。",
        "它的冷启动速度怎么样？",            # 「它」 = Vite
        "那我刚才说我的博客部署在哪里来着？",  # 考验记忆
    ]
    for q in turns:
        console.print(f"\n[bold blue]用户：[/bold blue]{q}")
        console.print(f"[bold magenta]小博：[/bold magenta]{agent.chat(q)}")

    console.print(
        "\n[yellow]「它」能被理解为 Vite、部署位置能被想起来 ——\n"
        "全靠每轮请求都带上了历史。没有记忆管理，这两个问题都答不了。[/yellow]\n"
    )


def demo_2_watch_compression() -> None:
    """演示 2：观察记忆压缩的发生。

    故意把窗口预算调得很小（400 token），多聊几轮就能看到：
      1. 旧消息被挤出滑动窗口
      2. 攒够数量后触发 LLM 摘要压缩
      3. 压缩后仍然记得最早说过的关键信息（摘要的功劳）
    """
    console.rule("[bold cyan]演示 2：记忆压缩（窗口故意调小到400token）")

    agent = MemoryChatAgent(max_recent_tokens=400)
    turns = [
        "你好，我叫小明，是一名前端工程师，正在学习 Agent 开发。",
        "我的博客文章存在 GitHub 仓库里，有 md、json、js 三种格式。",
        "我打算用 Qdrant 做向量库，Embedding 用 bge 模型。",
        "后端框架我选了 FastAPI，跑在阿里云的 Docker 里。",
        "监控打算用 Prometheus 加 Grafana。",
        "对了，我还想给博客加一个 AI 导读功能。",
    ]
    for q in turns:
        console.print(f"\n[bold blue]用户：[/bold blue]{q}")
        console.print(f"[bold magenta]小博：[/bold magenta]{agent.chat(q)}")
        console.print(f"[dim]记忆状态：{agent.memory.stats()}[/dim]")

    # 关键测试：最早的信息（名字、职业）应该已被挤出窗口、进入摘要
    console.print("\n[bold]关键测试 —— 问最早说过的信息：[/bold]")
    q = "我叫什么名字？做什么工作的？"
    console.print(f"[bold blue]用户：[/bold blue]{q}")
    console.print(f"[bold magenta]小博：[/bold magenta]{agent.chat(q)}")
    console.print(
        "\n[yellow]名字早就被挤出滑动窗口了，但摘要里保留了它 ——\n"
        "这就是两级记忆（窗口保细节 + 摘要保要点）的价值。[/yellow]\n"
    )


def demo_3_interactive() -> None:
    """演示 3：交互式带记忆聊天（/exit 退出，/stats 看记忆状态，/clear 清空）。"""
    console.rule("[bold cyan]演示 3：交互式聊天（/exit 退出，/stats 记忆状态，/clear 清空）")

    agent = MemoryChatAgent()
    while True:
        try:
            user_input = console.input("\n[bold blue]你 >[/bold blue] ").strip()
        except (KeyboardInterrupt, EOFError):
            break
        if not user_input:
            continue
        if user_input == "/exit":
            break
        if user_input == "/stats":
            console.print(f"[dim]{agent.memory.stats()}[/dim]")
            if agent.memory.summary:
                console.print(Panel(agent.memory.summary, title="当前摘要", border_style="cyan"))
            continue
        if user_input == "/clear":
            agent.memory.clear()
            console.print("[yellow]（记忆已清空）[/yellow]")
            continue
        console.print(f"[bold magenta]小博 >[/bold magenta] {agent.chat(user_input)}")

    console.print("\n[dim]再见！[/dim]")


if __name__ == "__main__":
    demo_1_cross_turn_memory()
    demo_2_watch_compression()
    demo_3_interactive()
    console.print("\n[bold green]本章完成！下一章把 02 模块的 RAG 接进 Agent —— BlogAgent 雏形登场。[/bold green]")
