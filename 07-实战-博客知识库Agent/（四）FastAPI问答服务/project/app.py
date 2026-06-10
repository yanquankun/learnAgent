"""
app.py —— FastAPI 问答服务

启动（先确保 Qdrant 在跑、索引已建好）：
    docker compose up -d
    uv run python index_cli.py
    uv run uvicorn app:app --port 8000 --reload

测试页：浏览器打开 http://localhost:8000/
接口契约见第一章 README。
"""

import json

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pathlib import Path
from pydantic import BaseModel, Field

import session
from llm_client import LLMNotConfigured
from rag import QaResult, answer_stream

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
    stream: bool = True


def result_payload(result: QaResult) -> dict:
    """QaResult -> API 响应 JSON（第一章定义的契约）。"""
    return {
        "answer": result.answer,
        "sources": result.sources,
        "recommendedArticles": result.recommended,
        "confidence": result.confidence,
        "traceId": result.trace_id,
    }


@app.post("/api/chat")
def chat(req: ChatRequest):
    history = session.get_history(req.sessionId)

    # ---- 非流式：直接跑完返回完整 JSON ----
    if not req.stream:
        final: QaResult | None = None
        for kind, payload in answer_stream(req.question, history):
            if kind == "done":
                final = payload
        session.append_turn(req.sessionId, req.question, final.answer)
        return result_payload(final)

    # ---- 流式：SSE（Server-Sent Events）----
    # 事件流格式：每条 "data: {json}\n\n"
    #   {"type": "delta", "text": "..."}   增量文本（打字机效果）
    #   {"type": "done", ...完整契约字段}   最后一个事件，带来源与推荐
    def event_source():
        for kind, payload in answer_stream(req.question, history):
            if kind == "delta":
                yield f"data: {json.dumps({'type': 'delta', 'text': payload}, ensure_ascii=False)}\n\n"
            else:
                session.append_turn(req.sessionId, req.question, payload.answer)
                done = {"type": "done", **result_payload(payload)}
                yield f"data: {json.dumps(done, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        # 反代环境（Nginx）需要关掉缓冲，SSE 才能逐条到达（第八章会配合 Nginx 配置）
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/")
def index() -> FileResponse:
    """最小化测试聊天页（你的博客前端可参照它的 SSE 处理逻辑）。"""
    return FileResponse(STATIC_DIR / "chat.html")
