"""
tracing.py —— OpenTelemetry 初始化封装

两种导出方式，一键切换：
    setup_tracing()                 -> 控制台导出（离线学习用，span 直接打印）
    setup_tracing(use_jaeger=True)  -> OTLP HTTP 导出到本地 Jaeger
                                       （先 docker compose up -d 起 Jaeger）

概念速记：
    Span  ：一段有名字、有起止时间的操作（如「检索」「生成」）
    Trace ：一次请求产生的所有 Span 组成的树
    上一章的 trace_id 思想，在这里成为正式标准（W3C Trace Context）
"""

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

JAEGER_OTLP_ENDPOINT = "http://localhost:4318/v1/traces"


def setup_tracing(service_name: str = "blog-rag", use_jaeger: bool = False) -> trace.Tracer:
    """初始化追踪并返回 tracer（之后用 tracer.start_as_current_span 包代码）。"""
    provider = TracerProvider(
        # Resource：标识「这些 span 来自哪个服务」，Jaeger 里按它筛选
        resource=Resource.create({"service.name": service_name})
    )

    if use_jaeger:
        exporter = OTLPSpanExporter(endpoint=JAEGER_OTLP_ENDPOINT)
        print(f"span 将导出到 Jaeger：{JAEGER_OTLP_ENDPOINT}（浏览器打开 http://localhost:16686 查看）")
    else:
        exporter = ConsoleSpanExporter()
        print("span 将打印到控制台（加 --jaeger 参数可导出到 Jaeger）")

    # BatchSpanProcessor：span 先攒批再异步导出，不阻塞业务代码
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return trace.get_tracer(service_name)
