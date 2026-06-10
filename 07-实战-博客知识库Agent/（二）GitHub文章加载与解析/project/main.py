"""
（二）GitHub 文章加载与解析 —— 演示入口

验证数据入口的完整链路：仓库后端 -> 文件列表 -> 解析 -> Article + hash。

运行方式：
    uv sync && uv run python main.py        # 默认 local 后端，离线可跑
    # 想试真实 GitHub 仓库：.env 配 BLOG_SOURCE=github + GITHUB_REPO 再跑
"""

import config
from models import content_hash
from parser import parse_file
from repo_backend import get_backend
from rich.console import Console
from rich.table import Table

console = Console()


def main() -> None:
    backend = get_backend()
    console.print(f"数据源：[bold]{config.BLOG_SOURCE}[/bold]（{type(backend).__name__}）\n")

    # ---- 1. 列出仓库中的文章文件 ----
    paths = backend.list_paths()
    console.print(f"发现 {len(paths)} 个文章文件：{paths}\n")

    # ---- 2. 逐个读取 + 解析成统一 Article ----
    table = Table(title="解析结果（三种格式 -> 统一 Article）")
    for col in ("id", "标题", "格式", "tags", "content_hash"):
        table.add_column(col)
    articles = []
    for path in paths:
        article = parse_file(backend.get_file(path))
        if article is None:
            continue
        articles.append(article)
        table.add_row(
            article.id, article.title[:22], path.rsplit(".", 1)[-1],
            ",".join(article.tags[:2]), article.hash,
        )
    console.print(table)

    # ---- 3. 演示 content_hash 的灵敏度：改一个字，指纹完全不同 ----
    sample = articles[0]
    tampered = content_hash(sample.content + "。")
    console.print(
        f"\n[bold]content_hash 演示[/bold]（增量索引的判断依据）："
        f"\n  原文 hash：{sample.hash}"
        f"\n  加一个句号后：{tampered}"
        f"\n  [yellow]内容变 -> hash 变 -> 下一章的索引 pipeline 据此只重建变化的文章。[/yellow]"
    )

    # ---- 4. URL 生成：article_id -> 博客链接（推荐文章功能要用）----
    console.print(
        f"\nURL 规则（.env 的 BLOG_URL_TEMPLATE）：\n  "
        f"{sample.id} -> {config.BLOG_URL_TEMPLATE.format(id=sample.id)}"
    )


if __name__ == "__main__":
    main()
