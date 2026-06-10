"""
（三）向量数据库 Qdrant 入门 —— 演示入口

第一章我们「逐条暴力计算相似度」，文章多了就慢了。
向量数据库专门解决这个问题：用 HNSW 等索引算法实现毫秒级的
近似最近邻检索（ANN），并提供持久化、元数据过滤等工程能力。

本章使用 Qdrant 的「内存模式」（QdrantClient(":memory:")），
零安装零配置即可学习全部 API —— 换成 Docker 服务端时代码完全一样，
只需把连接参数改成 url="http://localhost:6333"。

演示内容：
    演示 1：创建 collection（向量集合）
    演示 2：写入向量点（upsert）+ payload 元数据
    演示 3：向量检索（query_points）
    演示 4：带元数据过滤的检索（向量相似度 + 结构化条件）

运行方式：
    cd 到本 project 目录 -> uv sync -> uv run python main.py
"""

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)
from rich.console import Console

from embedder import EMBEDDING_DIM, embed_one, embed_texts

console = Console()

COLLECTION = "blog_demo"

# ":memory:" = 在 Python 进程内存里模拟一个 Qdrant，进程退出数据即消失。
# 学习和写单元测试的利器。生产环境的三种部署方式见本章 README。
client = QdrantClient(":memory:")


def demo_1_create_collection() -> None:
    """演示 1：创建 collection —— 类比关系数据库的「建表」。

    创建时必须声明两件事：
      1. size    : 向量维度。必须和 Embedding 模型的输出维度一致！
                   （bge-small-zh-v1.5 是 512 维，维度不匹配会直接报错）
      2. distance: 距离度量方式。文本检索基本都用 COSINE（余弦）
    """
    console.rule("[bold cyan]演示 1：创建 collection")

    client.create_collection(
        collection_name=COLLECTION,
        vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
    )

    info = client.get_collection(COLLECTION)
    console.print(f"collection 创建成功：{COLLECTION}")
    console.print(f"  向量维度：{EMBEDDING_DIM}，距离度量：COSINE，当前点数：{info.points_count}\n")


def demo_2_upsert() -> None:
    """演示 2：写入向量点（Point）。

    Qdrant 中一条数据叫一个 Point，由三部分组成：
      id      : 唯一标识（整数或 UUID 字符串）
      vector  : 向量本体（embedding 的结果）
      payload : 任意 JSON 元数据 —— 上一章设计的 chunk 元数据就放这里！

    upsert = update + insert：id 已存在则覆盖，不存在则插入。
    这个特性是后面「动态更新知识库」的基础（文章改了就按 id 覆盖）。
    """
    console.rule("[bold cyan]演示 2：upsert 写入向量点")

    # 模拟 6 个文章切片（真实场景里它们来自上一章的 chunker）
    chunks = [
        {"text": "React useEffect 依赖数组的常见陷阱与解决方案", "article_id": "react-useeffect", "tag": "frontend"},
        {"text": "useEffect 的清理函数防止内存泄漏", "article_id": "react-useeffect", "tag": "frontend"},
        {"text": "webpack 迁移 Vite 后冷启动从12秒降到0.8秒", "article_id": "vite-migration", "tag": "frontend"},
        {"text": "Docker Compose 一键部署 Postgres 和 Redis", "article_id": "docker-compose-deploy", "tag": "devops"},
        {"text": "数据库端口不要绑定到公网，用 Docker 内部网络访问", "article_id": "docker-compose-deploy", "tag": "devops"},
        {"text": "uv 是 Rust 编写的 Python 包管理器，比 pip 快几十倍", "article_id": "python-env-uv", "tag": "python"},
    ]

    vectors = embed_texts([c["text"] for c in chunks])

    points = [
        PointStruct(
            id=i,  # 教学用自增 id；实战中会用「article_id + chunk_index」生成稳定 id
            vector=vectors[i].tolist(),
            payload={
                "text": chunks[i]["text"],
                "article_id": chunks[i]["article_id"],
                "tag": chunks[i]["tag"],
            },
        )
        for i in range(len(chunks))
    ]

    client.upsert(collection_name=COLLECTION, points=points)
    console.print(f"已写入 {len(points)} 个向量点（每个点 = 向量 + payload 元数据）\n")


def demo_3_search() -> None:
    """演示 3：向量检索 —— RAG 在线阶段的核心操作。

    query_points：传入「问题的向量」，Qdrant 返回最相似的 top_k 个点。
    每个命中结果包含：id、score（余弦相似度）、payload（我们存的元数据）。
    """
    console.rule("[bold cyan]演示 3：向量检索")

    query = "前端项目构建速度优化"
    hits = client.query_points(
        collection_name=COLLECTION,
        query=embed_one(query).tolist(),
        limit=3,  # top_k
    ).points

    console.print(f"提问：[bold]{query}[/bold]")
    for hit in hits:
        console.print(f"  score={hit.score:.3f}  {hit.payload['text']}  [dim](文章: {hit.payload['article_id']})[/dim]")
    console.print(
        "\n[yellow]payload 跟着检索结果一起返回 —— 这就是为什么元数据要在入库时存好：\n"
        "拿到命中结果立刻就知道「来自哪篇文章」，可以直接生成推荐链接。[/yellow]\n"
    )


def demo_4_filtered_search() -> None:
    """演示 4：向量相似度 + 元数据过滤的混合检索。

    场景：只想在 devops 类的文章里搜索。
    Filter 写法类比 SQL 的 WHERE：must=[条件1, 条件2] 相当于 AND。
    实战项目里可以按 tags、分类、发布时间等任意 payload 字段过滤。
    """
    console.rule("[bold cyan]演示 4：带元数据过滤的检索")

    query = "怎么部署数据库"
    hits = client.query_points(
        collection_name=COLLECTION,
        query=embed_one(query).tolist(),
        limit=3,
        query_filter=Filter(
            must=[FieldCondition(key="tag", match=MatchValue(value="devops"))]
        ),
    ).points

    console.print(f"提问：[bold]{query}[/bold]（限定 tag=devops）")
    for hit in hits:
        console.print(f"  score={hit.score:.3f}  {hit.payload['text']}  [dim](tag: {hit.payload['tag']})[/dim]")
    console.print("\n[yellow]结果全部来自 devops 标签 —— 「语义检索 + 结构化过滤」是工程中最常用的组合。[/yellow]")


if __name__ == "__main__":
    demo_1_create_collection()
    demo_2_upsert()
    demo_3_search()
    demo_4_filtered_search()
    console.print("\n[bold green]本章演示全部完成！下一章把 loader + chunker + Qdrant + LLM 串成完整的 RAG。[/bold green]")
