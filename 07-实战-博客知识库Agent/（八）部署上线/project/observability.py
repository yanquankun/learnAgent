"""
observability.py —— 服务观测三件套（06 模块的落地版）

1. 结构化 JSON 日志（06-一）：每行一个 JSON，trace_id 串起一次问答的所有事件
2. Prometheus 指标（06-三）：请求量 / 延迟 / 置信度 / 路由分布 / 拒答数
3. OpenTelemetry 追踪（06-二）：qa.request 根 span，默认不导出，
   OTEL_EXPORT=console 打印到控制台，OTEL_EXPORT=jaeger 发往本地 Jaeger(4318)

学习项目里三者各教一章；生产服务里它们是一个整体——本文件就是「整体」长什么样。
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from prometheus_client import Counter, Histogram

# ============================================================
# 1. 结构化日志
# ============================================================

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "event": record.getMessage(),
            **getattr(record, "fields", {}),
        }
        return json.dumps(entry, ensure_ascii=False)


logger = logging.getLogger("blog_agent")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def log_event(event: str, trace_id: str, **fields) -> None:
    logger.info(event, extra={"fields": {"trace_id": trace_id, **fields}})


# ============================================================
# 2. Prometheus 指标（在 app.py 暴露 /metrics）
# ============================================================

QA_REQUESTS = Counter(
    "qa_requests_total", "问答请求总数", ["status", "category"]
)
QA_LATENCY = Histogram(
    "qa_latency_seconds", "问答端到端延迟（秒）",
    buckets=[0.5, 1, 2, 4, 8, 15, 30],
)
QA_CONFIDENCE = Histogram(
    "qa_confidence", "检索置信度分布（看知识库覆盖质量）",
    buckets=[0.3, 0.4, 0.5, 0.6, 0.7, 0.8],
)
QA_REFUSED = Counter("qa_refused_total", "拒答次数（知识库盲区信号）")

# ---- 用户长期记忆指标（08 模块三章接入）----
# 召回命中数持续为 0：要么没人是回头客，要么抽取管线挂了 —— 都值得看一眼
MEMORY_RECALLS = Counter("memory_recalls_total", "记忆召回命中条数（注入回答的记忆数）")
MEMORY_EVENTS = Counter("memory_events_total", "记忆写操作次数", ["op"])  # add/update/skip


# ============================================================
# 3. OpenTelemetry 追踪
# ============================================================

def setup_tracing() -> trace.Tracer:
    provider = TracerProvider(
        resource=Resource.create({"service.name": "blog-agent"})
    )
    mode = os.getenv("OTEL_EXPORT", "off")
    if mode == "console":
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    elif mode == "jaeger":
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint="http://localhost:4318/v1/traces"))
        )
    trace.set_tracer_provider(provider)
    return trace.get_tracer("blog-agent")


tracer = setup_tracing()
