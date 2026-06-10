"""
（四）Ragas 入门（v0.4 API）—— 演示入口

「可观测性三件套」管住了快慢与成本，但管不住**回答质量**。
Ragas 用「LLM 当裁判」的思路，把质量变成可比较的分数：

    Faithfulness     忠实度：回答是否被检索内容支撑（测「编没编」）
    AnswerRelevancy  回答相关性：答的是不是问的（测「跑没跑题」）
    ContextPrecision 上下文精确率：检索结果排序靠不靠谱（测检索）
    ContextRecall    上下文召回率：该召回的内容召回了吗（测检索）

本章用 DeepSeek 作裁判模型评估 4 个样本，其中第 2 个样本是
故意编造的错误回答 —— 看忠实度分数能不能抓住它。

运行方式（需要 LLM Key；评估 4 个样本约需 1~3 分钟）：
    cd 到本 project 目录 -> uv sync -> uv run python main.py
"""

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

console = Console()


def _load_env() -> None:
    current = Path(__file__).resolve().parent
    for directory in [current, *current.parents]:
        candidate = directory / ".env"
        if candidate.exists():
            load_dotenv(candidate)
            return


_load_env()
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

API_KEY = os.getenv("LLM_API_KEY", "")
BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
MODEL = os.getenv("LLM_MODEL", "deepseek-chat")

if not API_KEY or "请替换" in API_KEY:
    print("【环境未配置】本章需要 LLM_API_KEY（DeepSeek 作裁判模型），请配置根目录 .env")
    sys.exit(1)


# ============================================================
# 1) 裁判模型：llm_factory + OpenAI 兼容客户端指向 DeepSeek
# ============================================================

from openai import AsyncOpenAI  # noqa: E402
from ragas.llms import llm_factory  # noqa: E402

judge_llm = llm_factory(
    MODEL,
    provider="openai",
    client=AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL),
)


# ============================================================
# 2) 本地 Embedding：实现 Ragas 的 BaseRagasEmbedding 接口
#    （AnswerRelevancy 需要算「生成的问题 vs 原问题」的相似度。
#      又一次「实现框架接口」—— 04 模块三章干过同样的事！）
# ============================================================

from ragas.embeddings.base import BaseRagasEmbedding  # noqa: E402


class LocalFastEmbed(BaseRagasEmbedding):
    """用课程一直在用的 bge-small-zh 模型，给 Ragas 提供 embedding 能力。"""

    def __init__(self) -> None:
        from fastembed import TextEmbedding

        console.print("[dim]加载本地向量模型（复用之前的缓存）……[/dim]")
        self._model = TextEmbedding(model_name="BAAI/bge-small-zh-v1.5")

    def embed_text(self, text: str, **kwargs) -> list[float]:
        return next(iter(self._model.embed([text]))).tolist()

    async def aembed_text(self, text: str, **kwargs) -> list[float]:
        return self.embed_text(text)


# ============================================================
# 3) 评估样本：模拟 4 次「博客 RAG 问答」的现场记录
#    每个样本四元组：问题 / 回答 / 检索到的上下文 / 标准答案(reference)
# ============================================================

CONTEXT_USEEFFECT = (
    "React 18 的 StrictMode 在开发环境会刻意把组件挂载两次（mount -> unmount -> mount），"
    "以暴露副作用清理不当的问题。因此 useEffect 在开发环境执行两次是刻意设计，"
    "生产构建中不会发生。正确的做法是写好清理函数，而不是用 ref 绕过。"
)
CONTEXT_DOCKER = (
    "使用 docker compose 部署 Postgres 时，最重要的是为数据目录挂载卷："
    "volumes 配置 ./pgdata:/var/lib/postgresql/data，否则容器删除后数据全部丢失。"
    "另外建议固定镜像的主版本号，例如 postgres:16。"
)

SAMPLES = [
    {
        "name": "正常样本：回答忠实于资料",
        "user_input": "useEffect 为什么在开发环境执行两次？",
        "response": "这是 React 18 StrictMode 的刻意设计：开发环境会把组件挂载两次来暴露副作用清理问题，生产环境不会。应对方法是写好清理函数。",
        "retrieved_contexts": [CONTEXT_USEEFFECT],
        "reference": "React 18 StrictMode 在开发环境故意双重挂载组件以暴露副作用问题，生产环境不受影响，应编写正确的清理函数。",
    },
    {
        "name": "坏样本：回答是编造的（看忠实度能否抓住）",
        "user_input": "useEffect 为什么在开发环境执行两次？",
        "response": "这是因为 React 的调度器有 bug，在 18.3 版本已经修复，升级即可。也可以设置 React.unstable_strictMode=false 全局关闭。",
        "retrieved_contexts": [CONTEXT_USEEFFECT],
        "reference": "React 18 StrictMode 在开发环境故意双重挂载组件以暴露副作用问题，生产环境不受影响，应编写正确的清理函数。",
    },
    {
        "name": "答非所问样本（看回答相关性能否抓住）",
        "user_input": "docker compose 部署 Postgres 要注意什么？",
        "response": "Docker 是一种容器技术，2013 年由 dotCloud 公司发布，它让应用打包和分发变得简单。",
        "retrieved_contexts": [CONTEXT_DOCKER],
        "reference": "最重要的是为数据目录挂载卷防止数据丢失，并固定镜像版本。",
    },
    {
        "name": "检索跑偏样本（看上下文指标能否抓住）",
        "user_input": "docker compose 部署 Postgres 要注意什么？",
        "response": "需要为数据目录挂载卷，并固定镜像版本。",
        "retrieved_contexts": [CONTEXT_USEEFFECT],   # 检索错了：拿到的是 React 的内容
        "reference": "最重要的是为数据目录挂载卷防止数据丢失，并固定镜像版本。",
    },
]


# ============================================================
# 4) 逐样本评估：v0.4 collections API —— await metric.ascore(...)
# ============================================================

async def evaluate_all() -> None:
    from ragas.metrics.collections import (
        AnswerRelevancy,
        ContextPrecision,
        ContextRecall,
        Faithfulness,
    )

    embeddings = LocalFastEmbed()
    faithfulness = Faithfulness(llm=judge_llm)
    relevancy = AnswerRelevancy(llm=judge_llm, embeddings=embeddings)
    precision = ContextPrecision(llm=judge_llm)
    recall = ContextRecall(llm=judge_llm)

    table = Table(title="Ragas 评估结果（分数越接近 1 越好）")
    for col in ("样本", "忠实度", "回答相关", "上下文精确", "上下文召回"):
        table.add_column(col)

    for sample in SAMPLES:
        console.print(f"[dim]评估中：{sample['name']}……[/dim]")
        f = await faithfulness.ascore(
            user_input=sample["user_input"],
            response=sample["response"],
            retrieved_contexts=sample["retrieved_contexts"],
        )
        r = await relevancy.ascore(
            user_input=sample["user_input"], response=sample["response"]
        )
        p = await precision.ascore(
            user_input=sample["user_input"],
            reference=sample["reference"],
            retrieved_contexts=sample["retrieved_contexts"],
        )
        c = await recall.ascore(
            user_input=sample["user_input"],
            retrieved_contexts=sample["retrieved_contexts"],
            reference=sample["reference"],
        )

        def color(v: float) -> str:
            return f"[green]{v:.2f}[/green]" if v >= 0.7 else f"[red]{v:.2f}[/red]"

        table.add_row(sample["name"], color(f.value), color(r.value), color(p.value), color(c.value))

    console.print(table)
    console.print(
        "\n[yellow]解读要点：\n"
        "  样本2 忠实度应明显偏低 —— 回答编造了资料里没有的内容\n"
        "  样本3 回答相关性应偏低 —— 答的不是问的\n"
        "  样本4 上下文精确/召回应偏低 —— 检索拿错了资料（回答再对也是巧合）\n"
        "质量出问题时，这组分数能告诉你「锅在检索还是在生成」。[/yellow]"
    )


if __name__ == "__main__":
    asyncio.run(evaluate_all())
    console.print("\n[bold green]本章完成！下一章自建评估集，把评估变成可自动回归的工程。[/bold green]")
