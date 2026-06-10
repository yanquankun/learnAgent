"""
（二）文档加载与 Chunk 切片 —— 演示入口

本章不需要调用 LLM 和向量模型，专注做好「数据预处理」：
    演示 1：把 md / json / js 三种格式的文章统一解析成 Article
    演示 2：对比两种切片策略的效果
    演示 3：完整的切片产物（带元数据），它们就是下一章入库的原料

运行方式：
    cd 到本 project 目录 -> uv sync -> uv run python main.py
"""

from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from chunker import chunk_article, split_by_size
from loader import load_articles

console = Console()
DATA_DIR = Path(__file__).parent / "data"


def demo_1_load() -> None:
    """演示 1：加载并统一解析三种格式的文章。"""
    console.rule("[bold cyan]演示 1：统一解析 md / json / js 文章")

    articles = load_articles(DATA_DIR)

    table = Table(title=f"共加载 {len(articles)} 篇文章")
    table.add_column("id")
    table.add_column("格式")
    table.add_column("标题")
    table.add_column("正文字数", justify="right")
    table.add_column("标签")
    for a in articles:
        table.add_row(a.id, a.file_type, a.title, str(len(a.content)), ", ".join(a.tags))
    console.print(table)

    console.print(
        "[yellow]三种格式的文件被解析成了完全相同的 Article 结构 ——\n"
        "后续所有处理（切片/向量化/入库）都只面对 Article，不再关心原始格式。\n"
        "这正是你博客 GitHub 仓库的真实场景。[/yellow]\n"
    )


def demo_2_compare_strategies() -> None:
    """演示 2：对比两种切片策略。"""
    console.rule("[bold cyan]演示 2：固定大小切片 vs 按标题切片")

    articles = load_articles(DATA_DIR)
    # 拿《vite迁移》这篇做对比（标题层级丰富）
    article = next(a for a in articles if a.id == "vite-migration")

    # 策略 A：无视文档结构，按 400 字符硬切
    plain_pieces = split_by_size(article.content, chunk_size=400, overlap=80)
    console.print(f"[bold]策略 A（固定大小+重叠）[/bold]：切出 {len(plain_pieces)} 片")
    console.print(Panel(plain_pieces[1][:120] + "……", title="策略A的第2片（开头可能是断句）", border_style="red"))

    # 策略 B：按标题切，保留标题路径
    chunks = chunk_article(article)
    console.print(f"\n[bold]策略 B（按标题+元数据）[/bold]：切出 {len(chunks)} 片")
    sample = chunks[2]
    console.print(
        Panel(
            sample.content[:160] + "……",
            title=f"策略B的第3片 | 标题路径: {' > '.join(sample.heading_path)}",
            border_style="green",
        )
    )
    console.print(
        "[yellow]策略 B 的优势：每片都是完整的语义小节，自带「标题路径」上下文。\n"
        "用户的提问往往和标题表述接近，把标题拼进切片文本能显著提升检索命中率。[/yellow]\n"
    )


def demo_3_full_pipeline() -> None:
    """演示 3：全量文章切片 —— 看看下一章要入库的完整原料。"""
    console.rule("[bold cyan]演示 3：全量切片产物")

    articles = load_articles(DATA_DIR)
    all_chunks = []
    for article in articles:
        all_chunks.extend(chunk_article(article))

    table = Table(title=f"全部 {len(articles)} 篇文章共切出 {len(all_chunks)} 个 chunk")
    table.add_column("article_id")
    table.add_column("#", justify="right")
    table.add_column("标题路径")
    table.add_column("字数", justify="right")
    for c in all_chunks[:12]:  # 只展示前 12 个
        table.add_row(c.article_id, str(c.chunk_index), " > ".join(c.heading_path), str(len(c.content)))
    console.print(table)
    console.print("[dim]（仅展示前 12 个）[/dim]")

    console.print(
        "\n[yellow]每个 chunk 都带着完整的元数据（来自哪篇文章、哪个小节）。\n"
        "下一章就把它们 embedding 后存入向量数据库 Qdrant。[/yellow]"
    )


if __name__ == "__main__":
    demo_1_load()
    demo_2_compare_strategies()
    demo_3_full_pipeline()
    console.print("\n[bold green]本章演示全部完成！下一章学习向量数据库 Qdrant。[/bold green]")
