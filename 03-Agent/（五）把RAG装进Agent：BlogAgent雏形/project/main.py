"""
（五）把 RAG 装进 Agent：BlogAgent 雏形 —— 演示入口（本模块的里程碑！）

把 02 模块的 RAG 和本模块的 Agent 能力组装成实战项目的第一个完整原型：

    02模块四章（固定流程）         本章 BlogAgent（自主决策）
    ─────────────────            ──────────────────────
    提问 -> 必定检索一次 -> 生成    模型自己决定：
                                  - 闲聊？直接回答，不检索
                                  - 技术问题？调 search_blog
                                  - 检索分数低？换关键词再试
                                  - 片段不够？get_article 读全文
                                  - 问博客概况？list_articles

运行方式：
    cd 到本 project 目录 -> uv sync -> uv run python main.py
    （首次运行会自动构建索引）

建议依次试这三类输入，观察 Agent 的不同决策路径：
    1. 「你好呀」                          -> 应该不检索，直接回答
    2. 「useEffect 为什么执行两次？」       -> 应该调 search_blog
    3. 「你的博客都写了哪些主题？」          -> 应该调 list_articles
"""

import json

from rich.console import Console
from rich.panel import Panel

import blog_tools  # noqa: F401 —— import 即注册所有博客工具（@tool 装饰器的副作用）
from blog_tools import ensure_index
from llm_client import MODEL, get_client
from tools import execute, get_schemas

console = Console()

SYSTEM_PROMPT = """你是「小博」，技术博客的AI助手。你的知识来源是博客的文章知识库。

工作原则：
1. 与博客内容相关的问题，必须先调用 search_blog 检索，严格依据检索结果回答，不要编造
2. 闲聊、问候等与博客无关的输入，直接友好回应，不要调用工具
3. 检索结果相关度低时，可以换关键词重试一次；仍然没有就如实告知「博客中没有相关文章」
4. 回答控制在150字以内，并在结尾推荐相关文章，格式：
   推荐阅读：《文章标题》(id: 文章id)
5. 永远诚实：检索结果里没有的内容，不要出现在回答里"""


class BlogAgent:
    """博客问答 Agent：多工具 + 跨轮记忆 + 自主决策。

    结构 = 第三章的工具循环 + 第四章的对话记忆（简化版滑动窗口）。
    """

    MAX_TURNS = 6      # 记忆只保留最近 6 轮对话
    MAX_ROUNDS = 5     # 单轮提问最多允许 5 轮工具调用（安全阀）

    def __init__(self):
        self.client = get_client()
        self.history: list[dict] = []  # 跨轮对话记忆（只存 user/assistant 文本消息）

    def chat(self, user_input: str) -> str:
        """处理一轮用户输入：工具循环 + 记忆维护。"""
        # 组装本轮的 messages：system + 历史记忆 + 本轮问题
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *self.history[-self.MAX_TURNS * 2:],
            {"role": "user", "content": user_input},
        ]

        # ---- 工具调用循环（第三章的核心逻辑）----
        for _ in range(self.MAX_ROUNDS):
            response = self.client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=get_schemas(),
                temperature=0.2,
            )
            message = response.choices[0].message

            if not message.tool_calls:
                answer = message.content
                break

            messages.append(message)
            for tc in message.tool_calls:
                args = json.loads(tc.function.arguments)
                console.print(f"  [dim][决策] 调用 {tc.function.name}({args})[/dim]")
                result = execute(tc.function.name, args)
                console.print(f"  [dim][结果] {result[:80].replace(chr(10), ' ')}……[/dim]")
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
        else:
            answer = "（处理超时，请换个方式提问）"

        # ---- 记忆维护：只保存「干净」的问答文本，不保存工具调用细节 ----
        # 工具调用的中间过程又长又没有跨轮价值，存进记忆纯属浪费 token
        self.history.append({"role": "user", "content": user_input})
        self.history.append({"role": "assistant", "content": answer})
        return answer


def main() -> None:
    ensure_index()  # 首次运行自动构建博客知识库索引

    agent = BlogAgent()

    console.rule("[bold cyan]BlogAgent 雏形（输入 /exit 退出）")
    console.print(
        "[dim]试试三类输入，观察决策路径的差异：\n"
        "  1. 你好呀                       （应直接回答，不检索）\n"
        "  2. useEffect 为什么执行两次？     （应调 search_blog）\n"
        "  3. 你的博客都写了哪些主题？       （应调 list_articles）[/dim]"
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

        answer = agent.chat(user_input)
        console.print(Panel(answer, title="小博", border_style="green"))

    console.print("\n[dim]再见！[/dim]")


if __name__ == "__main__":
    main()
    console.print(
        "\n[bold green]恭喜完成 03-Agent 模块！[/bold green]\n"
        "[yellow]你已经独立实现了实战项目的核心原型。接下来 04-LangChain / 05-LangGraph\n"
        "会教你用工业级框架重写它 —— 你会发现框架做的事你全都懂。[/yellow]"
    )
