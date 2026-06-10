"""
indexer.py —— 知识库索引构建（RAG 的「离线阶段」）

把前几章的能力串起来：
    loader 加载文章 -> chunker 切片 -> embedder 向量化 -> Qdrant 入库

本章开始使用 Qdrant 的「本地持久化模式」：
    QdrantClient(path="./qdrant_data")
向量数据保存在磁盘上，构建一次索引后，问答脚本可以反复使用。
"""

import atexit
import uuid
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from chunker import chunk_article
from embedder import EMBEDDING_DIM, embed_texts
from loader import load_articles

# 所有路径都基于本文件所在目录，保证从任何工作目录运行都正确
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
QDRANT_PATH = str(BASE_DIR / "qdrant_data")  # 向量库的磁盘存储目录
COLLECTION = "blog_chunks"


def get_qdrant() -> QdrantClient:
    """获取本地持久化模式的 Qdrant 客户端。

    atexit 注册关闭函数：程序退出时干净地释放本地存储的文件锁，
    避免解释器关闭阶段打印无害但吓人的告警信息。
    """
    client = QdrantClient(path=QDRANT_PATH)
    atexit.register(client.close)
    return client


def stable_point_id(article_id: str, chunk_index: int) -> str:
    """为切片生成「稳定」的 Point ID。

    用 uuid5（基于内容的确定性 UUID）：同一篇文章的同一个切片序号，
    永远生成同一个 ID。好处：重新构建索引时，upsert 会自动覆盖旧数据，
    而不是无限追加重复数据 —— 这是将来「动态更新知识库」的关键设计。
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{article_id}#{chunk_index}"))


def build_index(client: QdrantClient) -> int:
    """构建（或重建）整个知识库索引，返回入库的 chunk 数量。"""
    print("【1/4】加载文章……")
    articles = load_articles(DATA_DIR)
    print(f"       共 {len(articles)} 篇（md/json/js）")

    print("【2/4】切片……")
    chunks = []
    for article in articles:
        chunks.extend(chunk_article(article))
    print(f"       共切出 {len(chunks)} 个 chunk")

    print("【3/4】向量化（首次运行需下载模型）……")
    vectors = embed_texts([c.content for c in chunks])

    print("【4/4】写入 Qdrant……")
    # recreate：如果 collection 已存在先删除，保证一个干净的索引
    if client.collection_exists(COLLECTION):
        client.delete_collection(COLLECTION)
    client.create_collection(
        collection_name=COLLECTION,
        vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
    )

    points = [
        PointStruct(
            id=stable_point_id(chunk.article_id, chunk.chunk_index),
            vector=vectors[i].tolist(),
            # payload 里存检索后需要用到的一切元数据
            payload={
                "article_id": chunk.article_id,
                "title": chunk.title,
                "content": chunk.content,
                "heading_path": chunk.heading_path,
                "chunk_index": chunk.chunk_index,
                "tags": chunk.tags,
            },
        )
        for i, chunk in enumerate(chunks)
    ]
    client.upsert(collection_name=COLLECTION, points=points)

    print(f"索引构建完成！共 {len(points)} 个向量点，存储于 {QDRANT_PATH}")
    return len(points)


if __name__ == "__main__":
    # 单独运行本文件 = 手动重建索引
    build_index(get_qdrant())
