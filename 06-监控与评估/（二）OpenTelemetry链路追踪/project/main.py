"""
（二）OpenTelemetry 链路追踪 —— 演示入口

给 RAG 问答的每个环节套上 span，把一次请求画成「瀑布图」：

    qa.request（整次请求）
      ├── rewrite   （查询改写，本章用 sleep 模拟 LLM 耗时）
      ├── retrieve  （真实检索）
      │     ├── embed         （向量化）
      │     └── qdrant.query  （向量库查询）
      └── generate  （回答生成，模拟）

运行方式（全程离线可跑）：
    uv run python main.py            # span 打印到控制台
    docker compose up -d             # 起本地 Jaeger
    uv run python main.py --jaeger   # span 导出到 Jaeger，浏览器看瀑布图
"""

import random
import sys
import time

from rich.console import Console

from embedder import embed_one
from indexer import COLLECTION, build_index, get_qdrant
from tracing import setup_tracing

console = Console()
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："

tracer = setup_tracing(use_jaeger="--jaeger" in sys.argv)
qdrant = get_qdrant()


def rewrite(question: str) -> str:
    """查询改写。本章重点是追踪而非 LLM，用 sleep 模拟一次 LLM 调用的耗时。"""
    with tracer.start_as_current_span("rewrite") as span:
        span.set_attribute("input.question", question)
        time.sleep(random.uniform(0.3, 0.8))      # 模拟 LLM 延迟
        query = question.replace("为什么", "").replace("？", "")
        span.set_attribute("output.query", query)
        return query


def retrieve(query: str) -> list:
    """真实检索 —— 注意内部还有两个子 span，瀑布图会显示嵌套层级。"""
    with tracer.start_as_current_span("retrieve") as span:
        with tracer.start_as_current_span("embed"):
            vector = embed_one(QUERY_PREFIX + query)

        with tracer.start_as_current_span("qdrant.query") as q_span:
            points = qdrant.query_points(
                collection_name=COLLECTION, query=vector.tolist(), limit=3
            ).points
            q_span.set_attribute("db.collection", COLLECTION)

        # span 属性：把关键业务数据挂上去，排查时不用翻日志
        span.set_attribute("hits.count", len(points))
        span.set_attribute("hits.top_score", points[0].score if points else 0)
        return points


def generate(question: str, points: list) -> str:
    """回答生成（模拟）。span 事件（add_event）用来标记瞬间动作。"""
    with tracer.start_as_current_span("generate") as span:
        span.add_event("prompt.built", {"context.chunks": len(points)})
        time.sleep(random.uniform(0.8, 2.0))      # 模拟 LLM 生成耗时
        answer = f"根据《{points[0].payload['title']}》：……（模拟回答）"
        span.set_attribute("answer.length", len(answer))
        return answer


def qa(question: str) -> None:
    """一次完整问答 —— 最外层 span 是整棵 trace 树的根。"""
    with tracer.start_as_current_span("qa.request") as span:
        span.set_attribute("question", question)
        query = rewrite(question)
        points = retrieve(query)
        answer = generate(question, points)
        console.print(f"[green]回答：{answer[:60]}[/green]")


if __name__ == "__main__":
    if not qdrant.collection_exists(COLLECTION):
        console.print("[bold]首次运行，构建索引……[/bold]")
        build_index(qdrant)

    for q in ["useEffect 为什么执行两次？", "怎么部署 Postgres？", "事件循环是什么？"]:
        console.print(f"\n提问：[bold]{q}[/bold]")
        qa(q)

    # BatchSpanProcessor 是异步导出的，等它把缓冲区刷完
    from opentelemetry import trace as otel_trace

    otel_trace.get_tracer_provider().force_flush()
    console.print(
        "\n[bold green]完成！如果用了 --jaeger，打开 http://localhost:16686，"
        "Service 选 blog-rag，就能看到每次问答的瀑布图。[/bold green]"
    )
