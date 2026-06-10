"""
blog_tools.py —— BlogAgent 的工具集

把 02 模块的 RAG 能力封装成 Agent 工具。注意对比 02 模块四章的固定流程：

    固定 RAG Workflow：提问 -> 必定检索一次 -> 生成
    BlogAgent        ：模型自主决定 —— 要不要检索？检索什么词？
                       结果不好要不要换词重试？要不要看文章全文？

三个工具的分工：
    search_blog   : 语义检索文章片段（最常用）
    get_article   : 按 id 读文章完整内容（检索片段不够时深入阅读）
    list_articles : 列出全部文章（用户问「你的博客都写了什么」时用）
"""

from pathlib import Path

from embedder import embed_one
from indexer import COLLECTION, build_index, get_qdrant
from loader import load_articles
from tools import tool

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
BLOG_URL_TEMPLATE = "https://your-blog.com/articles/{slug}"

# Qdrant 客户端全局唯一（本地文件模式不允许多个客户端同时打开同一目录）
_qdrant = get_qdrant()


def ensure_index() -> None:
    """索引不存在时自动构建（首次运行）。"""
    if not _qdrant.collection_exists(COLLECTION):
        print("首次运行，正在构建博客知识库索引……")
        build_index(_qdrant)


@tool(param_desc={"query": "检索查询词。建议用简洁的技术术语，如 '前端构建速度优化'"})
def search_blog(query: str) -> str:
    """在博客知识库中语义检索文章片段。回答任何与博客内容相关的问题前必须先调用本工具。
    如果检索结果相关度低（分数<0.5），可以换更具体或更通用的关键词再试一次。"""
    hits = _qdrant.query_points(
        collection_name=COLLECTION,
        query=embed_one(query).tolist(),
        limit=4,
        score_threshold=0.4,
    ).points

    if not hits:
        return "没有检索到相关内容。可以换个关键词重试，或如实告诉用户博客中没有相关文章。"

    parts = []
    for h in hits:
        location = " > ".join(h.payload["heading_path"]) or "全文"
        parts.append(
            f"[相关度{h.score:.2f}] 文章id={h.payload['article_id']}《{h.payload['title']}》"
            f"「{location}」小节：\n{h.payload['content'][:300]}"
        )
    return "\n\n".join(parts)


@tool(param_desc={"article_id": "文章id（slug），可从 search_blog 或 list_articles 的结果中获得"})
def get_article(article_id: str) -> str:
    """读取一篇文章的完整内容。当检索到的片段信息不足、需要通读全文时使用。"""
    articles = {a.id: a for a in load_articles(DATA_DIR)}
    article = articles.get(article_id)
    if article is None:
        return f"文章 {article_id} 不存在。可用的文章id：{list(articles)}"
    # 全文可能很长，截断到 2000 字符防止撑爆上下文
    content = article.content[:2000]
    return f"《{article.title}》（标签：{', '.join(article.tags)}）\n{content}"


@tool()
def list_articles() -> str:
    """列出博客的全部文章（标题、id、标签、发布日期）。用户想了解博客整体内容时使用。"""
    articles = load_articles(DATA_DIR)
    lines = [
        f"- id={a.id}《{a.title}》 标签:{','.join(a.tags)} 发布:{a.created_at}"
        for a in articles
    ]
    return f"博客共有 {len(articles)} 篇文章：\n" + "\n".join(lines)


def article_url(article_id: str) -> str:
    """根据文章 id 拼出博客链接（给最终回答用）。"""
    return BLOG_URL_TEMPLATE.format(slug=article_id)
