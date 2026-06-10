"""
（五）检索优化与 RAG 常见坑 —— 演示入口

RAG 系统「能跑」和「好用」之间隔着一个调优阶段。
本章用四个实验，把最重要的调优手段亲手做一遍：

    实验 1：top_k 的权衡 —— 取多少条检索结果合适？
    实验 2：score 阈值与拒答 —— 如何优雅地说「我不知道」
    实验 3：查询改写（Query Rewrite）—— 口语化提问的救星
    实验 4：查询指令前缀 —— bge 模型的官方提分技巧

运行方式：
    cd 到本 project 目录 -> uv sync -> uv run python main.py
    （实验 3 需要调用 LLM，其余实验离线可跑）
"""

from rich.console import Console
from rich.table import Table

from embedder import embed_one
from indexer import COLLECTION, build_index, get_qdrant
from llm_client import MODEL, get_client

console = Console()
client = get_qdrant()


def search(query_vector: list[float], top_k: int = 4, threshold: float | None = None):
    """对知识库做一次向量检索（本章实验的公共函数）。"""
    return client.query_points(
        collection_name=COLLECTION,
        query=query_vector,
        limit=top_k,
        score_threshold=threshold,
    ).points


def show_hits(hits, title: str) -> None:
    """用表格展示检索结果。"""
    table = Table(title=title)
    table.add_column("score", justify="right")
    table.add_column("文章")
    table.add_column("小节")
    for h in hits:
        table.add_row(
            f"{h.score:.3f}",
            h.payload["title"][:18],
            " > ".join(h.payload["heading_path"])[:24],
        )
    console.print(table)


def exp_1_top_k() -> None:
    """实验 1：top_k 的权衡。

    top_k 太小 -> 可能漏掉关键信息（召回不足）
    top_k 太大 -> 塞进一堆弱相关内容，干扰模型、浪费 token（精度下降）

    观察 top_k=8 时排在后面的结果：分数明显变低、内容开始跑题。
    """
    console.rule("[bold cyan]实验 1：top_k 的权衡")

    query = "useEffect 怎么避免内存泄漏"
    vec = embed_one(query).tolist()
    console.print(f"提问：[bold]{query}[/bold]\n")

    for top_k in (1, 3, 8):
        hits = search(vec, top_k=top_k)
        show_hits(hits, f"top_k = {top_k}")

    console.print(
        "[yellow]top_k=1 信息可能不够；top_k=8 后几条已经跑题（分数差距很大）。\n"
        "经验起点：top_k=3~5，再结合分数阈值过滤 —— 没有万能值，要按数据实测。[/yellow]\n"
    )


def exp_2_threshold_and_refuse() -> None:
    """实验 2：score 阈值与拒答策略。

    对比一个「知识库里有答案」和一个「完全无关」的问题的分数分布，
    你会发现两者有明显的分数鸿沟 —— 阈值就卡在鸿沟中间。
    """
    console.rule("[bold cyan]实验 2：score 阈值与拒答")

    for query in ("React 严格模式为什么让 effect 执行两次", "今晚吃什么比较好"):
        vec = embed_one(query).tolist()
        hits = search(vec, top_k=3)  # 不带阈值，看原始分数
        console.print(f"提问：[bold]{query}[/bold]")
        for h in hits:
            console.print(f"  score={h.score:.3f}  《{h.payload['title'][:18]}》")
        console.print()

    console.print(
        "[yellow]无关问题的最高分通常也比相关问题低一大截。\n"
        "把阈值（如 0.45）卡在中间：低于阈值 -> 全部丢弃 -> 触发拒答。\n"
        "三档回答策略：高分=正常回答；中分=「没有直接答案，但这篇可能相关」；全部低于阈值=明确拒答。[/yellow]\n"
    )


def exp_3_query_rewrite() -> None:
    """实验 3：查询改写（Query Rewrite）。

    真实用户的提问往往口语化、带废话：
        「那个，我记得你之前写过一篇讲打包贼慢的优化的文章来着？」
    直接拿去检索，噪音词会拉低相似度。

    解法：先让 LLM 把问题改写成「检索友好」的简洁查询，再去检索。
    这是成本最低、收益最明显的检索优化手段之一。
    """
    console.rule("[bold cyan]实验 3：查询改写（需要调用 LLM）")

    raw_query = "那个，我记得你之前好像写过一篇讲打包贼慢然后做了优化的文章来着？"

    # 用 LLM 做查询改写（注意：这是一次额外的 LLM 调用，有延迟成本）
    llm = get_client()
    response = llm.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "你是搜索查询改写器。把用户的口语化提问改写成适合向量检索的简洁查询：\n"
                    "去掉语气词和无关内容，保留核心概念，补全技术术语。只输出改写后的查询。"
                ),
            },
            {"role": "user", "content": raw_query},
        ],
        temperature=0,
    )
    rewritten = response.choices[0].message.content.strip()

    console.print(f"原始提问：{raw_query}")
    console.print(f"改写结果：[bold green]{rewritten}[/bold green]\n")

    show_hits(search(embed_one(raw_query).tolist(), top_k=3), "用原始提问检索")
    show_hits(search(embed_one(rewritten).tolist(), top_k=3), "用改写后查询检索")
    console.print("[yellow]对比 score：改写后的检索分数明显更高、排序更准。[/yellow]\n")


def exp_4_query_instruction() -> None:
    """实验 4：bge 模型的查询指令前缀。

    bge 中文模型官方建议：做「短查询 -> 长文档」检索时，
    给查询加上指令前缀（文档侧不需要加）：
        为这个句子生成表示以用于检索相关文章：{query}

    这是模型训练时的约定，加上它通常能小幅提升检索效果。
    """
    console.rule("[bold cyan]实验 4：查询指令前缀（bge 官方技巧）")

    query = "数据库部署安全注意事项"
    prefixed = f"为这个句子生成表示以用于检索相关文章：{query}"

    show_hits(search(embed_one(query).tolist(), top_k=3), "无前缀")
    show_hits(search(embed_one(prefixed).tolist(), top_k=3), "加指令前缀")
    console.print(
        "[yellow]前缀带来的提升通常是「小幅但稳定」的（分数和排序略有变化）。\n"
        "类似的模型特定技巧务必查阅模型卡（model card）—— 用对约定，白捡效果。[/yellow]"
    )


if __name__ == "__main__":
    # 索引不存在时自动构建
    if not client.collection_exists(COLLECTION):
        console.print("[yellow]首次运行，正在构建知识库索引……[/yellow]\n")
        build_index(client)

    exp_1_top_k()
    exp_2_threshold_and_refuse()
    exp_3_query_rewrite()
    exp_4_query_instruction()
    console.print("\n[bold green]恭喜完成 02-RAG 模块！下一站：03-Agent，让模型学会「自主决定」什么时候检索。[/bold green]")
