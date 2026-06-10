"""
app.py —— FastAPI 问答服务

启动（先确保 Qdrant 在跑、索引已建好）：
    docker compose up -d
    uv run python index_cli.py
    uv run uvicorn app:app --port 8000 --reload

测试页：浏览器打开 http://localhost:8000/
接口契约见第一章 README。
"""

import hashlib
import hmac
import json
import time
from typing import Iterator

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pathlib import Path
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

import config
import db
from agent_graph import answer_stream   # 第六章：内核换成 LangGraph 图，契约不变
from incremental import process_changes
from llm_client import LLMNotConfigured
from observability import (
    QA_CONFIDENCE, QA_LATENCY, QA_REFUSED, QA_REQUESTS, log_event, tracer,
)
from rag import QaResult

app = FastAPI(title="博客知识库 Agent 服务")

# CORS：允许你的博客前端跨域调用（上线时把 * 换成你的博客域名）
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

STATIC_DIR = Path(__file__).parent / "static"


@app.exception_handler(LLMNotConfigured)
def llm_not_configured(_request: Request, exc: LLMNotConfigured) -> JSONResponse:
    """配置缺失返回 503 + 可操作的提示，而不是干巴巴的 500。"""
    return JSONResponse(status_code=503, content={"error": str(exc)})


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    sessionId: str = "default"
    userId: str = ""        # 长期记忆的隔离主体；不传则用 sessionId（匿名访客）
    stream: bool = True


def schedule_memory_update(user_id: str, question: str, answer: str) -> None:
    """对话结束后，后台线程跑「抽取 + 整合」（08 模块二章的管线）。

    用 daemon 线程而非 BackgroundTasks：流式响应场景下，
    answer 要等 SSE 全部吐完才拿得到，此时已错过注册 BackgroundTasks 的时机。
    """
    import threading

    from user_memory import extract_and_store

    transcript = f"读者：{question}\n助手：{answer}"
    threading.Thread(
        target=lambda: extract_and_store(user_id, transcript), daemon=True
    ).start()


def result_payload(result: QaResult) -> dict:
    """QaResult -> API 响应 JSON（第一章定义的契约）。"""
    return {
        "answer": result.answer,
        "sources": result.sources,
        "recommendedArticles": result.recommended,
        "confidence": result.confidence,
        "traceId": result.trace_id,
    }


def observed_stream(
    question: str, session_id: str, user_id: str = ""
) -> Iterator[tuple[str, QaResult | str]]:
    """第七章：给问答内核包一层观测（日志 + 指标 + 追踪 + qa_logs）。

    埋点放在包装层而不是内核里 —— 内核保持纯粹，观测随时可拆可换。
    """
    start = time.perf_counter()
    with tracer.start_as_current_span("qa.request") as span:
        span.set_attribute("qa.question", question[:100])
        try:
            for kind, payload in answer_stream(question, session_id, user_id):
                if kind == "done":
                    final: QaResult = payload
                yield kind, payload
        except Exception as exc:
            QA_REQUESTS.labels(status="error", category="unknown").inc()
            log_event("qa.error", "-", question=question, error=str(exc))
            span.record_exception(exc)
            raise

        latency_ms = int((time.perf_counter() - start) * 1000)
        refused = final.category == "tech" and not final.sources
        span.set_attribute("qa.category", final.category)
        span.set_attribute("qa.confidence", final.confidence)

        # 指标：聚合趋势（Grafana 看板的数据源）
        QA_REQUESTS.labels(status="ok", category=final.category).inc()
        QA_LATENCY.observe(latency_ms / 1000)
        if final.category == "tech":
            QA_CONFIDENCE.observe(final.confidence)
            if refused:
                QA_REFUSED.inc()

        # 日志 + qa_logs：单条明细（排错与评估的原材料）
        log_event(
            "qa.done", final.trace_id, category=final.category,
            confidence=final.confidence, refused=refused, latency_ms=latency_ms,
        )
        db.save_qa_log(
            trace_id=final.trace_id, session_id=session_id, question=question,
            answer=final.answer, category=final.category,
            confidence=final.confidence, source_cnt=len(final.sources),
            latency_ms=latency_ms,
        )


@app.post("/api/chat")
def chat(req: ChatRequest):
    # 会话记忆已由 LangGraph checkpointer 接管（sessionId 即 thread_id）——
    # 第四章手写的 session.py 整个退役，且记忆升级为 SQLite 持久化（重启不丢）
    user_id = req.userId or req.sessionId

    # ---- 非流式：直接跑完返回完整 JSON ----
    if not req.stream:
        final: QaResult | None = None
        for kind, payload in observed_stream(req.question, req.sessionId, user_id):
            if kind == "done":
                final = payload
        schedule_memory_update(user_id, req.question, final.answer)
        return result_payload(final)

    # ---- 流式：SSE（Server-Sent Events）----
    # 事件流格式：每条 "data: {json}\n\n"
    #   {"type": "delta", "text": "..."}   增量文本（打字机效果）
    #   {"type": "done", ...完整契约字段}   最后一个事件，带来源与推荐
    def event_source():
        for kind, payload in observed_stream(req.question, req.sessionId, user_id):
            if kind == "delta":
                yield f"data: {json.dumps({'type': 'delta', 'text': payload}, ensure_ascii=False)}\n\n"
            else:
                schedule_memory_update(user_id, req.question, payload.answer)
                done = {"type": "done", **result_payload(payload)}
                yield f"data: {json.dumps(done, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        # 反代环境（Nginx）需要关掉缓冲，SSE 才能逐条到达（第八章会配合 Nginx 配置）
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/github/webhook", status_code=202)
async def github_webhook(
    request: Request,
    background: BackgroundTasks,
    x_hub_signature_256: str = Header(default=""),
    x_github_event: str = Header(default=""),
) -> dict:
    """GitHub push 事件入口（动态 RAG 的触发器）。

    安全三连：
      1. 验签：HMAC-SHA256(密钥, 原始body) 必须与签名头一致 ——
         没有这步，任何人 curl 一下就能让你的服务器疯狂跑索引
      2. compare_digest 比较：恒定时间比较，防时序攻击
      3. 202 立即返回：索引进后台任务，不能让 GitHub 等（10 秒超时）
    """
    body = await request.body()

    # ---- 1. 签名校验 ----
    if not config.WEBHOOK_SECRET:
        raise HTTPException(500, "服务端未配置 WEBHOOK_SECRET")
    expected = "sha256=" + hmac.new(
        config.WEBHOOK_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, x_hub_signature_256):
        raise HTTPException(403, "签名校验失败")

    # ---- 2. 只处理 push 事件（ping 等其他事件直接确认）----
    if x_github_event != "push":
        return {"status": "ignored", "event": x_github_event}

    # ---- 3. 汇总本次 push 所有 commit 的文件变更 ----
    payload = json.loads(body)
    added, modified, removed = set(), set(), set()
    for commit in payload.get("commits", []):
        added.update(commit.get("added", []))
        modified.update(commit.get("modified", []))
        removed.update(commit.get("removed", []))
    # 同一文件「先改后删」时以删除为准
    added -= removed
    modified -= removed

    # ---- 4. 进后台任务，立即 202 ----
    background.add_task(
        process_changes, sorted(added), sorted(modified), sorted(removed), "webhook"
    )
    return {
        "status": "accepted",
        "added": len(added), "modified": len(modified), "removed": len(removed),
    }


@app.post("/api/admin/reindex", status_code=202)
def admin_reindex(background: BackgroundTasks, x_admin_token: str = Header(default="")) -> dict:
    """手动全量重建（兜底）。需在 .env 配置 ADMIN_TOKEN。"""
    if not config.ADMIN_TOKEN or not hmac.compare_digest(x_admin_token, config.ADMIN_TOKEN):
        raise HTTPException(403, "无效的管理令牌")
    from index_cli import run_index

    background.add_task(run_index, True)
    return {"status": "accepted"}


@app.get("/api/index/jobs")
def index_jobs(limit: int = 10) -> list[dict]:
    """查看最近的索引任务（排查 Webhook 是否生效的第一入口）。"""
    import db

    conn = db.get_db()
    rows = conn.execute(
        "SELECT * FROM indexing_jobs ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/memories")
def memories(userId: str, x_admin_token: str = Header(default="")) -> dict:
    """调试端点：看「Agent 记住了关于某用户的什么」。

    记忆属于敏感数据 —— 必须管理令牌才能看（与 /api/admin/reindex 同一把）。
    """
    from user_memory import list_memories

    if not config.ADMIN_TOKEN or not hmac.compare_digest(x_admin_token, config.ADMIN_TOKEN):
        raise HTTPException(403, "无效的管理令牌")
    return {
        "facts": list_memories(userId),
        "recent_events": db.recent_memory_events(userId),
    }


@app.get("/metrics")
def metrics() -> Response:
    """Prometheus 抓取端点（06 模块三章的同款写法）。"""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/api/stats")
def stats() -> dict:
    """qa_logs 速览：今天答了多少、平均延迟、拒答率（无需 Grafana 也能看）。"""
    conn = db.get_db()
    row = conn.execute(
        "SELECT COUNT(*) AS total, AVG(latency_ms) AS avg_ms,"
        " SUM(CASE WHEN category='tech' AND source_cnt=0 THEN 1 ELSE 0 END) AS refused"
        " FROM qa_logs WHERE created_at >= date('now')"
    ).fetchone()
    conn.close()
    total = row["total"] or 0
    return {
        "today_total": total,
        "avg_latency_ms": round(row["avg_ms"] or 0),
        "refused": row["refused"] or 0,
        "refuse_rate": round((row["refused"] or 0) / total, 3) if total else 0,
    }


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/")
def index() -> FileResponse:
    """最小化测试聊天页（你的博客前端可参照它的 SSE 处理逻辑）。"""
    return FileResponse(STATIC_DIR / "chat.html")
