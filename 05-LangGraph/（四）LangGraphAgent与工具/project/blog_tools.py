"""
blog_tools.py —— BlogAgent 的工具集（LangChain @tool 版）

03 模块五章我们用手写注册表定义过同样的工具，这里改用 LangChain 的
@tool 装饰器重写，检索逻辑（embedder + Qdrant）原样复用 02 模块基建。
"""

import json

from langchain_core.tools import tool

from embedder import embed_one
from indexer import COLLECTION, build_index, get_qdrant
from loader import load_articles

QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："
DATA_DIR = "data"

_qdrant = get_qdrant()


def ensure_index() -> None:
    """确保索引存在（首次运行自动构建）。"""
    if not _qdrant.collection_exists(COLLECTION):
        build_index(_qdrant)


@tool
def search_blog(query: str) -> str:
    """语义搜索博客文章，返回最相关的内容片段（JSON 格式，含相关度分数）。

    Args:
        query: 检索查询，建议使用简洁的技术关键词组合
    """
    vector = embed_one(QUERY_PREFIX + query)
    points = _qdrant.query_points(
        collection_name=COLLECTION, query=vector.tolist(), limit=4
    ).points
    if not points or points[0].score < 0.45:
        return f"没有检索到与「{query}」相关的博客内容，可以换个关键词试试。"
    hits = [
        {
            "article_id": p.payload["article_id"],
            "title": p.payload["title"],
            "score": round(p.score, 3),
            "snippet": p.payload["content"][:150],
        }
        for p in points
    ]
    return json.dumps(hits, ensure_ascii=False)


@tool
def list_articles() -> str:
    """列出博客的全部文章（标题和ID），适合回答「博客里都有什么」类问题。"""
    articles = load_articles(DATA_DIR)
    return "\n".join(f"- {a.title}（id: {a.id}）" for a in articles)


BLOG_TOOLS = [search_blog, list_articles]
