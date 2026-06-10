"""
（一）记忆分层与长期记忆：LangGraph Store 实战

运行：uv run python main.py

三个演示：
    1. Store 基础：namespace / put / get / search —— 长期记忆的「文件系统」
    2. 语义记忆检索：自定义 FastEmbed 接入 Store 的向量搜索（本地免费）
    3. 记忆 Agent：checkpointer（thread内记忆）+ Store（跨thread记忆）同台对比
       —— 换一个 thread 聊天，Agent 依然记得你是谁（需配置 LLM_API_KEY）

核心概念：
    checkpointer 记的是「这场对话聊到哪了」（会话状态，thread 级）
    Store        记的是「关于这个用户我知道什么」（事实知识，user 级）
    两者不可互相替代 —— 生产 Agent 通常两个都要。
"""

from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore
from rich.console import Console

from embedder import EMBEDDING_DIM, embed_texts

console = Console()


# ============================================================
# 演示 1：Store 基础 —— namespace 是记忆的「目录结构」
# ============================================================

def demo_1_store_basics() -> None:
    console.rule("[bold cyan]演示 1：Store 基础（namespace / put / get）")

    store = InMemoryStore()

    # namespace 是一个元组，类似文件夹路径：(用户ID, 记忆类型)
    # 这是长期记忆设计的第一道关卡 —— namespace 错了，用户记忆就会「串台」
    store.put(("user_mint", "facts"), "fact-1", {"text": "资深前端工程师，主技术栈 React"})
    store.put(("user_mint", "facts"), "fact-2", {"text": "个人博客部署在阿里云，用 Docker"})
    store.put(("user_mint", "prefs"), "pref-1", {"text": "回答偏好：要代码示例，不要长篇大论"})
    # 另一个用户的记忆，完全隔离
    store.put(("user_alice", "facts"), "fact-1", {"text": "后端工程师，主要写 Go"})

    # get：按 namespace + key 精确读取
    item = store.get(("user_mint", "facts"), "fact-1")
    console.print(f"精确读取 -> {item.value['text']}")

    # search：列出某个 namespace 下的所有记忆（不带 query 就是普通列表）
    items = store.search(("user_mint", "facts"))
    console.print(f"user_mint 的 facts 有 {len(items)} 条")

    # 关键验证：namespace 隔离 —— mint 的查询永远碰不到 alice 的记忆
    items = store.search(("user_alice", "facts"))
    console.print(f"user_alice 的 facts 有 {len(items)} 条（与 mint 完全隔离）\n")


# ============================================================
# 演示 2：语义记忆检索 —— 给 Store 插上向量搜索
# ============================================================

def make_semantic_store() -> InMemoryStore:
    """创建带语义检索能力的 Store。

    index 配置三要素：
        embed  —— 任何「list[str] -> list[向量]」的函数都行，
                  这里直接用课程一直在用的本地 FastEmbed（免费离线）
        dims   —— 向量维度，必须与模型一致（bge-small-zh 是 512）
        fields —— 写入时默认对哪些字段做向量化
    """
    def embed_fn(texts: list[str]) -> list[list[float]]:
        return embed_texts(texts).tolist()

    return InMemoryStore(index={"embed": embed_fn, "dims": EMBEDDING_DIM, "fields": ["text"]})


def demo_2_semantic_search() -> None:
    console.rule("[bold cyan]演示 2：语义检索 —— 记忆像 RAG 一样按意思找")

    store = make_semantic_store()
    ns = ("user_mint", "facts")
    memories = [
        "资深前端工程师，主技术栈是 React 和 TypeScript",
        "正在自学 Agent 开发，用 Python 和 LangGraph",
        "个人博客的文章存在 GitHub 仓库里，格式是 Markdown",
        "喜欢喝美式咖啡，工作日早上一杯",
        "服务器是阿里云的，配了泛域名 HTTPS",
    ]
    for i, text in enumerate(memories):
        store.put(ns, f"fact-{i}", {"text": text})

    # 注意查询词和记忆原文几乎没有字面重叠 —— 这就是语义检索的价值
    for query in ["这个人会什么编程技术？", "早上有什么习惯？"]:
        results = store.search(ns, query=query, limit=2)
        console.print(f"[bold]查询：{query}[/bold]")
        for r in results:
            console.print(f"  score={r.score:.3f}  {r.value['text']}")
    console.print()


# ============================================================
# 演示 3：记忆 Agent —— checkpointer 与 Store 同台对比
# ============================================================
# 工具通过官方的 InjectedStore 注解拿到 Store（参数对 LLM 不可见、由框架注入），
# user_id 则从 config["configurable"] 读取 —— 与 thread_id 走同一个通道。

def build_memory_agent(store: InMemoryStore):
    """手工搭一个带「记忆工具」的 Agent 图（结构与 05-四 完全一致）。"""
    import uuid

    from langgraph.graph import END, StateGraph
    from langgraph.graph.message import MessagesState
    from langgraph.prebuilt import InjectedStore, ToolNode, tools_condition

    from lc_client import get_chat_model

    # 注意：InjectedStore() 注解的参数不能写默认值（= None），
    # 否则 LangChain 不会把它识别为「注入参数」，转 schema 时直接报错 —— 实测踩过的坑
    @tool
    def remember(fact: str, config: RunnableConfig,
                 store: Annotated[BaseStore, InjectedStore()]) -> str:
        """当用户透露关于自己的长期有效信息（身份/技术栈/偏好/项目情况）时，
        把它保存成一条简短的事实。"""
        user_id = config["configurable"]["user_id"]
        store.put(("memories", user_id), f"mem-{uuid.uuid4().hex[:8]}", {"text": fact})
        return f"已记住：{fact}"

    @tool
    def recall(query: str, config: RunnableConfig,
               store: Annotated[BaseStore, InjectedStore()]) -> str:
        """需要了解用户的背景/偏好来回答时，按语义检索已保存的用户记忆。"""
        user_id = config["configurable"]["user_id"]
        items = store.search(("memories", user_id), query=query, limit=3)
        if not items:
            return "（还没有关于该用户的记忆）"
        return "\n".join(f"- {it.value['text']}" for it in items)

    tools = [remember, recall]
    model = get_chat_model().bind_tools(tools)

    def call_model(state: MessagesState) -> dict:
        from langchain_core.messages import SystemMessage
        system = SystemMessage(content=(
            "你是用户的技术学习助手。用户透露个人信息时调用 remember 保存；"
            "回答需要用户背景时调用 recall 检索。回答简洁（100字内）。"
        ))
        return {"messages": [model.invoke([system, *state["messages"]])]}

    builder = StateGraph(MessagesState)
    builder.add_node("model", call_model)
    builder.add_node("tools", ToolNode(tools))
    builder.add_edge("__start__", "model")
    builder.add_conditional_edges("model", tools_condition, {"tools": "tools", END: END})
    builder.add_edge("tools", "model")

    # 同时挂上 checkpointer（thread内）与 store（跨thread）——一行之差，两种记忆
    return builder.compile(checkpointer=InMemorySaver(), store=store)


def chat(graph, thread_id: str, user_id: str, text: str) -> None:
    config = {"configurable": {"thread_id": thread_id, "user_id": user_id}}
    console.print(f"[yellow]({thread_id}) 用户：{text}[/yellow]")
    result = graph.invoke({"messages": [("user", text)]}, config)
    for msg in result["messages"]:
        if getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                console.print(f"  [dim]-> 调用工具 {tc['name']}({tc['args']})[/dim]")
    console.print(f"[green]助手：{result['messages'][-1].content}[/green]\n")


def demo_3_memory_agent() -> None:
    console.rule("[bold cyan]演示 3：跨 thread 的用户记忆（需 LLM Key）")

    import os
    if not os.getenv("LLM_API_KEY") or "请替换" in os.getenv("LLM_API_KEY", ""):
        console.print("[dim]未配置 LLM_API_KEY，跳过本演示（配置后可看到跨会话记忆效果）[/dim]\n")
        return

    graph = build_memory_agent(make_semantic_store())

    # 会话 1：用户透露信息 -> Agent 调 remember 存入 Store
    chat(graph, "thread-1", "user_mint", "我是前端工程师，最近在用 LangGraph 学 Agent 开发")

    # 会话 2：全新 thread！checkpointer 里没有任何历史，
    # 但 Agent 通过 recall 从 Store 找回了用户背景 —— 这就是长期记忆
    chat(graph, "thread-2", "user_mint", "根据你对我的了解，推荐我接下来深入学什么？")

    # 对照：换一个 user_id，记忆是空的（namespace 隔离）
    chat(graph, "thread-3", "user_stranger", "你知道我是做什么的吗？")


if __name__ == "__main__":
    demo_1_store_basics()
    demo_2_semantic_search()
    demo_3_memory_agent()
