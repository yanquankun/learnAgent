"""
vector_store.py —— Qdrant 服务端模式封装

与前面模块的两个区别：
    1. 改用 Docker 服务端模式（QDRANT_URL）：本地文件模式只允许单进程，
       而实战中「API 服务」和「索引任务」要同时访问向量库
    2. 稳定 Point ID（UUIDv5）：同一篇文章的同一个切片序号永远生成同一个 ID
       -> 重新索引时自动覆盖旧向量，删除时能精确定位（动态 RAG 的关键）
"""

import uuid

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

import config
from chunker import Chunk
from embedder import EMBEDDING_DIM, embed_one, embed_texts

QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："

_client: QdrantClient | None = None


def get_client() -> QdrantClient:
    """连接 Qdrant 服务端；连不上时给出可操作的提示。"""
    global _client
    if _client is None:
        _client = QdrantClient(url=config.QDRANT_URL, timeout=10)
        try:
            _client.get_collections()
        except Exception as exc:   # noqa: BLE001（启动期的连接自检）
            raise SystemExit(
                f"无法连接 Qdrant（{config.QDRANT_URL}）：{exc}\n"
                f"请先启动 Qdrant：在本章 project 目录执行 docker compose up -d"
            ) from exc
    return _client


def ensure_collection() -> None:
    client = get_client()
    if not client.collection_exists(config.QDRANT_COLLECTION):
        client.create_collection(
            collection_name=config.QDRANT_COLLECTION,
            vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
        )


def stable_point_id(article_id: str, chunk_index: int) -> str:
    """UUIDv5：对同样的输入永远生成同样的 ID（覆盖式更新的基础）。"""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{article_id}#{chunk_index}"))


def upsert_chunks(chunks: list[Chunk]) -> None:
    """切片向量化后写入；同 ID 自动覆盖旧版本。"""
    vectors = embed_texts([c.content for c in chunks])
    points = [
        PointStruct(
            id=stable_point_id(c.article_id, c.chunk_index),
            vector=vector.tolist(),
            payload={
                "article_id": c.article_id,
                "title": c.title,
                "content": c.content,
                "heading_path": c.heading_path,
                "chunk_index": c.chunk_index,
                "tags": c.tags,
            },
        )
        for c, vector in zip(chunks, vectors)
    ]
    get_client().upsert(collection_name=config.QDRANT_COLLECTION, points=points)


def delete_article_points(article_id: str) -> None:
    """按 article_id 删除该文章的全部向量（文章被删除/重建前调用）。"""
    get_client().delete(
        collection_name=config.QDRANT_COLLECTION,
        points_selector=Filter(
            must=[FieldCondition(key="article_id", match=MatchValue(value=article_id))]
        ),
    )


def search(query: str, top_k: int = 4) -> list[dict]:
    """语义检索：返回 [{article_id, title, content, score}]。"""
    vector = embed_one(QUERY_PREFIX + query)
    points = get_client().query_points(
        collection_name=config.QDRANT_COLLECTION, query=vector.tolist(), limit=top_k
    ).points
    return [
        {
            "article_id": p.payload["article_id"],
            "title": p.payload["title"],
            "content": p.payload["content"],
            "heading_path": p.payload.get("heading_path", []),
            "score": p.score,
        }
        for p in points
    ]


def drop_collection() -> None:
    client = get_client()
    if client.collection_exists(config.QDRANT_COLLECTION):
        client.delete_collection(config.QDRANT_COLLECTION)
