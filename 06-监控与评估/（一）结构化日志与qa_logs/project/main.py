"""
（一）结构化日志与 qa_logs —— 演示入口

给 02 模块的 RAG 问答装上「黑匣子」：

    演示 1：print vs JSON 结构化日志（离线可跑）
    演示 2：完整记录一次 RAG 问答 —— 每个环节打日志 + 全程入 qa_logs 表
            （没配 LLM Key 时自动用模拟回答，照样演示完整链路）
    演示 3：回放与统计 —— 从 qa_logs 查出历史问答，算平均延迟/检索质量

运行方式：
    cd 到本 project 目录 -> uv sync -> uv run python main.py
"""

import json

from rich.console import Console
from rich.table import Table

import llm_client
from embedder import embed_one
from indexer import COLLECTION, build_index, get_qdrant
from qa_logger import Timer, fetch_recent, log_event, new_trace_id, save_qa_log

console = Console()
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："

# 本地模式的 Qdrant 同一时刻只允许一个客户端实例，全局复用这一个
qdrant = get_qdrant()


def demo_1_plain_vs_json() -> None:
    console.rule("[bold cyan]演示 1：print vs 结构化日志")

    console.print("[dim]print 风格（人能看，机器难解析）：[/dim]")
    print("  检索完成，找到3条结果，最高分0.62，耗时45ms")

    console.print("[dim]JSON 结构化风格（每行一个事件，能进日志系统按字段聚合）：[/dim]")
    trace_id = new_trace_id()
    log_event("retrieve.done", trace_id, hits=3, top_score=0.62, latency_ms=45)
    log_event("generate.done", trace_id, tokens=210, latency_ms=1830)
    console.print(
        "[yellow]注意两条日志共享同一个 trace_id —— 一次请求的所有事件靠它串联。\n"
        "日志同时写入了 app.log 文件（cat 一下看看）。[/yellow]\n"
    )


def logged_qa(question: str) -> None:
    """带完整日志的 RAG 问答 —— 本章的核心代码。

    对照 02 模块四章的裸版问答：业务逻辑一行没变，
    只是在每个环节「顺手」记录了结构化事件，最后整体落库。
    """
    trace_id = new_trace_id()
    log_event("qa.start", trace_id, question=question)

    # ---- 1. 检索（02 模块的代码 + 日志）----
    with Timer() as t_ret:
        vector = embed_one(QUERY_PREFIX + question)
        points = qdrant.query_points(
            collection_name=COLLECTION, query=vector.tolist(), limit=3
        ).points
    retrieved = [
        {"article_id": p.payload["article_id"], "title": p.payload["title"], "score": round(p.score, 3)}
        for p in points
    ]
    log_event(
        "retrieve.done", trace_id,
        hits=len(retrieved),
        top_score=retrieved[0]["score"] if retrieved else 0,
        latency_ms=t_ret.ms,
    )

    # ---- 2. 生成（没配 Key 就用模拟回答，保证本章离线可学）----
    has_key = bool(llm_client.API_KEY) and "请替换" not in llm_client.API_KEY
    with Timer() as t_gen:
        if has_key:
            context = "\n\n".join(p.payload["content"] for p in points)
            resp = llm_client.get_client().chat.completions.create(
                model=llm_client.MODEL,
                messages=[
                    {"role": "system", "content": "根据资料回答，120字以内，给出来源标题。"},
                    {"role": "user", "content": f"<资料>{context}</资料>\n问题：{question}"},
                ],
            )
            answer = resp.choices[0].message.content
            usage = resp.usage
            prompt_tokens, completion_tokens = usage.prompt_tokens, usage.completion_tokens
        else:
            answer = f"（模拟回答）根据《{retrieved[0]['title']}》……"
            prompt_tokens = completion_tokens = 0
    log_event(
        "generate.done", trace_id,
        latency_ms=t_gen.ms, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
    )

    # ---- 3. 整次问答落库 ----
    save_qa_log(
        trace_id=trace_id, question=question, answer=str(answer),
        retrieved=retrieved, latency_ms=t_ret.ms + t_gen.ms,
        prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
        model=llm_client.MODEL if has_key else "mock",
    )
    log_event("qa.done", trace_id, total_ms=t_ret.ms + t_gen.ms)
    console.print(f"[green]回答：{str(answer)[:100]}[/green]\n")


def demo_2_logged_qa() -> None:
    console.rule("[bold cyan]演示 2：带黑匣子的 RAG 问答")
    for q in ["useEffect 为什么执行两次？", "怎么用 Docker 部署数据库？"]:
        console.print(f"提问：[bold]{q}[/bold]")
        logged_qa(q)


def demo_3_replay_and_stats() -> None:
    """演示 3：黑匣子的价值 —— 历史可查、指标可算。

    有了 qa_logs，你能回答以前答不了的问题：
    「用户都在问什么？」「平均多慢？」「检索质量怎么样？」
    """
    console.rule("[bold cyan]演示 3：回放与统计")

    rows = fetch_recent(10)
    table = Table(title=f"最近 {len(rows)} 条问答记录（qa_logs.db）")
    for col in ("trace_id", "question", "top_score", "latency_ms", "model"):
        table.add_column(col)
    for r in rows:
        table.add_row(r["trace_id"], r["question"][:18], f"{r['top_score']:.3f}", str(r["latency_ms"]), r["model"])
    console.print(table)

    if rows:
        avg_latency = sum(r["latency_ms"] for r in rows) / len(rows)
        low_quality = sum(1 for r in rows if r["top_score"] < 0.5)
        console.print(f"平均延迟：{avg_latency:.0f}ms   检索低分（<0.5）占比：{low_quality}/{len(rows)}")

    # 回放：取最近一条，看当时检索到了什么 —— 排查「为什么答错」的第一手证据
    if rows:
        latest = rows[0]
        console.print(f"\n回放 trace {latest['trace_id']} 当时的检索结果：")
        for hit in json.loads(latest["retrieved"]):
            console.print(f"  score={hit['score']}  《{hit['title'][:24]}》")


if __name__ == "__main__":
    console.print("[bold]检查/构建索引……[/bold]")
    if not qdrant.collection_exists(COLLECTION):
        build_index(qdrant)

    demo_1_plain_vs_json()
    demo_2_logged_qa()
    demo_3_replay_and_stats()
    console.print("\n[bold green]本章完成！下一章把 trace_id 升级成真正的分布式追踪（OpenTelemetry）。[/bold green]")
