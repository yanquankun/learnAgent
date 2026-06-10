"""
（一）Embedding 与向量相似度 —— 演示入口

RAG 的全部魔法都建立在一个事实之上：
    「语义相近的文本，转成向量后在空间中的距离也相近」

本章不调用任何 LLM，纯粹研究向量本身：
    演示 1：把文本变成向量，看看它长什么样
    演示 2：计算余弦相似度，验证「语义相近 = 向量相近」
    演示 3：实现一个最迷你的语义搜索（这就是 RAG 检索的核心原型！）

运行方式：
    cd 到本 project 目录 -> uv sync -> uv run python main.py
    （首次运行会下载约 90MB 的模型文件，请耐心等待）
"""

import numpy as np
from rich.console import Console
from rich.table import Table

from embedder import embed_one, embed_texts

console = Console()


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """计算两个向量的余弦相似度。

    公式：cos(θ) = (a · b) / (|a| × |b|)

    含义：两个向量夹角的余弦值，只关心「方向」是否一致，不关心长度。
      1.0  -> 方向完全相同（语义几乎一样）
      0.0  -> 互相垂直（语义无关）
     -1.0  -> 方向完全相反（实际文本向量很少出现负值）

    经验值（bge 中文模型）：> 0.6 通常表示相关，> 0.75 表示高度相关。
    """
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def demo_1_what_is_embedding() -> None:
    """演示 1：文本 -> 向量，看看 Embedding 到底是个什么东西。"""
    console.rule("[bold cyan]演示 1：文本变向量")

    text = "React 是一个用于构建用户界面的 JavaScript 库"
    vector = embed_one(text)

    console.print(f"原文：{text}")
    console.print(f"向量维度：{vector.shape}  [dim]# 512 个浮点数[/dim]")
    console.print(f"向量前 8 个数字：{np.round(vector[:8], 4).tolist()}")
    console.print(
        "\n[yellow]这 512 个数字就是这句话在「语义空间」中的坐标。\n"
        "单看每个数字没有意义，但向量之间的【距离】蕴含了语义关系。[/yellow]\n"
    )


def demo_2_similarity() -> None:
    """演示 2：验证「语义相近 = 向量相近」。

    准备 4 句话：前两句都在讲 React（但用词不同），
    第三句讲 Vue（同领域不同主题），第四句讲做菜（完全无关）。
    """
    console.rule("[bold cyan]演示 2：余弦相似度")

    sentences = [
        "React 的 useEffect 用于处理组件中的副作用",   # A
        "在 React 组件里，副作用逻辑应该写在 useEffect 中",  # B：和 A 语义几乎相同，用词不同
        "Vue 的 watch 可以监听数据变化并执行回调",       # C：同为前端框架，主题不同
        "红烧肉要先焯水，再用小火慢炖四十分钟",          # D：完全无关
    ]
    vectors = embed_texts(sentences)

    table = Table(title="两两余弦相似度")
    table.add_column("")
    for label in ["A", "B", "C", "D"]:
        table.add_column(label, justify="center")
    for i, label in enumerate(["A", "B", "C", "D"]):
        row = [label]
        for j in range(4):
            sim = cosine_similarity(vectors[i], vectors[j])
            # 高亮显示高相似度
            style = "bold green" if sim > 0.75 and i != j else ""
            row.append(f"[{style}]{sim:.3f}[/{style}]" if style else f"{sim:.3f}")
        table.add_row(*row)
    console.print(table)

    console.print(
        "[yellow]观察：A 和 B 用词不同但语义相同 -> 相似度最高；\n"
        "A 和 C 同领域 -> 中等；A 和 D 无关 -> 最低。\n"
        "重点：Embedding 捕捉的是【语义】而不是【关键词】——\n"
        "这是它比传统关键词搜索（如 Elasticsearch 的 BM25）强大的地方。[/yellow]\n"
    )


def demo_3_mini_semantic_search() -> None:
    """演示 3：最迷你的语义搜索引擎 —— RAG 检索的核心原型。

    流程（记住这个流程，后面所有 RAG 都是它的放大版）：
        1. 【离线】把知识库里的所有文本算好向量，存起来
        2. 【在线】用户提问 -> 把问题也算成向量
        3. 计算问题向量和每条知识向量的相似度
        4. 取相似度最高的 top_k 条 -> 这就是「检索结果」
    """
    console.rule("[bold cyan]演示 3：迷你语义搜索")

    # 模拟一个「博客文章标题」知识库
    knowledge_base = [
        "React useEffect 依赖数组的常见陷阱与解决方案",
        "webpack 迁移 Vite 实录：冷启动从12秒到0.8秒",
        "用 Docker Compose 一键部署 Postgres 和 Redis",
        "浏览器事件循环机制：宏任务与微任务详解",
        "Python 虚拟环境管理：从 venv 到 uv",
        "TypeScript 类型体操实用技巧",
    ]
    # 第 1 步：知识库向量化（真实项目中这一步是离线完成并持久化的）
    kb_vectors = embed_texts(knowledge_base)

    # 第 2 步：用户的口语化提问（注意：和文章标题的用词差异很大！）
    query = "前端项目构建太慢了怎么办"
    query_vector = embed_one(query)

    # 第 3 步：和知识库逐条算相似度
    scores = [cosine_similarity(query_vector, kv) for kv in kb_vectors]

    # 第 4 步：按相似度从高到低排序，取 top 3
    top_k = 3
    ranked = sorted(zip(scores, knowledge_base), key=lambda x: x[0], reverse=True)

    console.print(f"用户提问：[bold]{query}[/bold]\n")
    console.print(f"Top {top_k} 检索结果：")
    for rank, (score, title) in enumerate(ranked[:top_k], start=1):
        console.print(f"  {rank}. [{score:.3f}] {title}")

    console.print(
        "\n[yellow]注意：提问里根本没有「webpack」「Vite」这些词，\n"
        "但语义搜索依然把构建工具的文章排在了第一 —— 这就是 RAG 检索的威力。\n"
        "不过：逐条暴力计算相似度，文章多了就慢了 -> 第三章用向量数据库解决。[/yellow]"
    )


if __name__ == "__main__":
    demo_1_what_is_embedding()
    demo_2_similarity()
    demo_3_mini_semantic_search()
    console.print("\n[bold green]本章演示全部完成！下一章学习如何把「整篇文章」处理成适合检索的片段。[/bold green]")
