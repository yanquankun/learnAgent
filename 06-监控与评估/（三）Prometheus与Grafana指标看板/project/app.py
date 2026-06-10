"""
app.py —— 带 Prometheus 埋点的迷你问答服务

为了让你能「刷出大量流量、看到漂亮曲线」，本章的问答是模拟的
（随机延迟/分数/token），但**埋点代码与真实服务完全一致** ——
07 模块会把同样的埋点装进真正的 BlogAgent 服务。

四个最值得监控的指标（覆盖：流量、性能、成本、质量）：
    qa_requests_total        Counter   请求总数（按 status 区分）
    qa_latency_seconds       Histogram 请求延迟分布（算 P95/P99 用）
    llm_tokens_total         Counter   token 消耗（按 kind 区分，算钱用）
    retrieval_empty_total    Counter   检索为空次数（RAG 质量的哨兵指标）

启动：
    uv run uvicorn app:app --port 8000
指标端点：
    http://localhost:8000/metrics
"""

import random
import time

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

app = FastAPI(title="迷你问答服务（Prometheus 埋点示范）")

# ============================================================
# 指标定义：名字、帮助文本、标签维度
# ============================================================

QA_REQUESTS = Counter(
    "qa_requests_total",
    "问答请求总数",
    ["status"],                 # 标签 = 维度：之后可以按 status 分别画曲线
)
QA_LATENCY = Histogram(
    "qa_latency_seconds",
    "问答延迟（秒）",
    # 桶边界按「LLM 应用」的量级设计：从 100ms 到 10s
    buckets=[0.1, 0.3, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0],
)
LLM_TOKENS = Counter("llm_tokens_total", "LLM token 消耗", ["kind"])
RETRIEVAL_EMPTY = Counter("retrieval_empty_total", "检索为空（无相关内容）次数")

# /metrics 端点：把当前所有指标按 Prometheus 文本格式「摆」出来，
# 等着 Prometheus 每 5 秒来抓一次（拉模型）
@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/api/chat")
def chat(q: str = "默认问题") -> dict:
    """模拟一次 RAG 问答，并完成全部埋点。"""
    start = time.perf_counter()

    # ---- 模拟检索：10% 概率检索为空 ----
    top_score = random.choices([random.uniform(0.5, 0.8), 0.0], weights=[9, 1])[0]
    if top_score == 0.0:
        RETRIEVAL_EMPTY.inc()

    # ---- 模拟 LLM 生成：延迟与 token ----
    time.sleep(random.uniform(0.05, 0.6))     # 演示用，比真实 LLM 快
    prompt_tokens = random.randint(400, 1200)
    completion_tokens = random.randint(50, 300)
    LLM_TOKENS.labels(kind="prompt").inc(prompt_tokens)
    LLM_TOKENS.labels(kind="completion").inc(completion_tokens)

    # ---- 模拟偶发错误：5% 概率失败 ----
    ok = random.random() > 0.05
    QA_REQUESTS.labels(status="ok" if ok else "error").inc()
    QA_LATENCY.observe(time.perf_counter() - start)

    if not ok:
        return {"error": "模拟的偶发错误"}
    return {"answer": f"（模拟回答）{q}", "top_score": round(top_score, 3)}
