"""
（四）手写完整 RAG 问答链路 —— 演示入口（本模块的里程碑！）

把前三章的所有能力串成完整的 RAG 系统：

    离线阶段（indexer.py）：
        加载文章 -> 切片 -> 向量化 -> 入库 Qdrant

    在线阶段（本文件）：
        用户提问 -> 向量化 -> 检索 top_k -> 组装 Prompt -> LLM 生成
        -> 返回「回答 + 来源 + 推荐文章」

运行方式：
    cd 到本 project 目录 -> uv sync -> uv run python main.py
    （首次运行会自动构建索引；之后直接进入问答；
      文章数据变更后可运行 `uv run python indexer.py` 手动重建索引）

可以试试这些问题：
    - 为什么 useEffect 在开发环境会执行两次？
    - 前端项目构建太慢怎么优化？
    - 怎么在服务器上部署数据库？
    - uv 和 pip 有什么区别？
"""

from dataclasses import dataclass

from rich.console import Console
from rich.panel import Panel

from embedder import embed_one
from indexer import COLLECTION, build_index, get_qdrant
from llm_client import MODEL, get_client

console = Console()

# 你的博客文章地址模板（实战时换成真实域名）
BLOG_URL_TEMPLATE = "https://your-blog.com/articles/{slug}"

# 检索参数：top_k 取几条、低于多少分认为不相关（经验值，第五章会专门调优）
TOP_K = 4
SCORE_THRESHOLD = 0.45


@dataclass
class RetrievedChunk:
    """一条检索结果（从 Qdrant 的命中结果整理而来）。"""

    article_id: str
    title: str
    content: str
    heading_path: list[str]
    score: float


def retrieve(client, query: str) -> list[RetrievedChunk]:
    """检索阶段：把问题向量化，从 Qdrant 取最相关的 top_k 个切片。"""
    hits = client.query_points(
        collection_name=COLLECTION,
        query=embed_one(query).tolist(),
        limit=TOP_K,
        score_threshold=SCORE_THRESHOLD,  # 低于阈值的结果直接不要
    ).points

    return [
        RetrievedChunk(
            article_id=h.payload["article_id"],
            title=h.payload["title"],
            content=h.payload["content"],
            heading_path=h.payload["heading_path"],
            score=h.score,
        )
        for h in hits
    ]


def build_prompt(question: str, chunks: list[RetrievedChunk]) -> list[dict]:
    """组装 Prompt：把检索到的切片作为「上下文」喂给模型。

    注意三个关键设计（都来自 01 模块学过的 Prompt 工程）：
      1. 用 <context> 标签隔离检索内容和指令（防注入 + 边界清晰）
      2. 给每段上下文编号 [1][2]...，要求模型回答时标注引用来源
      3. 明确要求「上下文里没有的就说不知道」—— 这是抑制幻觉的核心手段
    """
    context_parts = []
    for i, chunk in enumerate(chunks, start=1):
        location = " > ".join(chunk.heading_path) or "全文"
        context_parts.append(
            f"[{i}] 出自文章《{chunk.title}》的「{location}」小节：\n{chunk.content}"
        )
    context_text = "\n\n".join(context_parts)

    system = (
        "你是一个技术博客的AI助手。请严格根据 <context> 标签中提供的博客文章片段回答用户问题。\n"
        "规则：\n"
        "1. 只使用 <context> 中的信息回答，不要编造上下文里没有的内容\n"
        "2. 回答时在相关句子末尾用 [1][2] 这样的标记标注信息来源\n"
        "3. 如果上下文不足以回答问题，诚实地说「博客中没有找到相关内容」\n"
        "4. 用简洁的中文回答，控制在200字以内"
    )
    user = f"<context>\n{context_text}\n</context>\n\n用户问题：{question}"

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def recommend_articles(chunks: list[RetrievedChunk]) -> list[dict]:
    """从检索结果整理「推荐文章」列表。

    多个切片可能来自同一篇文章，需要按 article_id 去重，
    并用该文章所有命中切片的最高分作为文章的推荐分。
    """
    best: dict[str, dict] = {}
    for chunk in chunks:
        existing = best.get(chunk.article_id)
        if existing is None or chunk.score > existing["score"]:
            best[chunk.article_id] = {
                "title": chunk.title,
                "url": BLOG_URL_TEMPLATE.format(slug=chunk.article_id),
                "score": chunk.score,
            }
    # 按分数从高到低排序
    return sorted(best.values(), key=lambda x: x["score"], reverse=True)


def answer_question(client, llm, question: str) -> None:
    """完整的一次 RAG 问答：检索 -> 生成 -> 展示来源和推荐。"""
    # ---------- 检索 ----------
    chunks = retrieve(client, question)

    # 检索为空的兜底：明确告诉用户没有相关内容，绝不让 LLM 自由发挥
    if not chunks:
        console.print(Panel(
            "抱歉，博客中没有找到与这个问题相关的内容。",
            title="回答", border_style="yellow",
        ))
        return

    console.print("[dim]检索到的切片：[/dim]")
    for i, c in enumerate(chunks, start=1):
        console.print(f"[dim]  [{i}] score={c.score:.3f} 《{c.title}》> {' > '.join(c.heading_path)}[/dim]")

    # ---------- 生成 ----------
    response = llm.chat.completions.create(
        model=MODEL,
        messages=build_prompt(question, chunks),
        temperature=0.2,  # RAG 问答要求稳定，低温度
    )
    answer = response.choices[0].message.content

    # ---------- 展示 ----------
    console.print(Panel(answer, title="回答", border_style="green"))
    console.print("[bold]推荐阅读：[/bold]")
    for article in recommend_articles(chunks):
        console.print(f"  - 《{article['title']}》 {article['url']}  [dim](相关度 {article['score']:.2f})[/dim]")


def main() -> None:
    client = get_qdrant()

    # 索引不存在时自动构建（首次运行）
    if not client.collection_exists(COLLECTION):
        console.print("[yellow]首次运行，正在构建知识库索引……[/yellow]")
        build_index(client)
        console.print()

    llm = get_client()

    console.rule("[bold cyan]博客知识库问答（输入 /exit 退出）")
    console.print("[dim]试试：为什么 useEffect 在开发环境会执行两次？[/dim]")

    while True:
        try:
            question = console.input("\n[bold blue]提问 >[/bold blue] ").strip()
        except (KeyboardInterrupt, EOFError):
            break
        if not question:
            continue
        if question == "/exit":
            break
        answer_question(client, llm, question)

    console.print("\n[dim]再见！[/dim]")


if __name__ == "__main__":
    main()
