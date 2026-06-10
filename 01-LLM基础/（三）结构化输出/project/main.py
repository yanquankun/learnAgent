"""
（三）结构化输出 —— 演示入口

程序无法直接消费一段自然语言，我们需要模型输出「可解析的数据结构」。
本章演示三步进阶：
    演示 1：只靠 Prompt 要求 JSON（不可靠，体会问题所在）
    演示 2：开启 JSON 模式（json_object），保证输出合法 JSON
    演示 3：JSON 模式 + Pydantic 校验 + 自动重试（生产级写法）

场景贯穿实战项目：从博客文章内容中提取结构化元数据（标题/分类/标签/摘要）。

运行方式：
    cd 到本 project 目录 -> uv sync -> uv run python main.py
"""

import json

from pydantic import BaseModel, Field, ValidationError
from rich.console import Console
from rich.panel import Panel

from llm_client import MODEL, get_client

console = Console()
client = get_client()

# 一段模拟的博客文章，作为本章所有演示的输入数据
ARTICLE = """
最近把博客的构建工具从 webpack 迁移到了 Vite，整体开发体验提升明显。
冷启动从 12 秒降到了 0.8 秒，热更新几乎是瞬时完成。
本文记录迁移过程中遇到的三个坑：CommonJS 依赖的处理、
环境变量前缀从 process.env 换成 import.meta.env、
以及生产构建时 Rollup 的分包配置。
总体来说，对于中小型项目，非常推荐尽早迁移到 Vite。
"""


def demo_1_prompt_only() -> None:
    """演示 1：只在 Prompt 里要求输出 JSON —— 不可靠的做法。

    常见翻车现场：
      - 模型在 JSON 前后加解释文字：「好的，以下是提取结果：{...}」
      - 模型用 markdown 代码块包裹：```json {...} ```
      - 字段名和你要求的不一致

    这些都会导致 json.loads() 直接抛异常，线上服务直接 500。
    """
    console.rule("[bold cyan]演示 1：只靠 Prompt 要求 JSON（不可靠）")

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "user", "content": f"从下面的文章中提取标题、标签、摘要，用JSON返回：\n{ARTICLE}"},
        ],
        temperature=0,
    )
    raw = response.choices[0].message.content
    console.print(Panel(raw, title="模型原始输出（注意它可能不是纯 JSON！）", border_style="red"))

    try:
        json.loads(raw)
        console.print("[green]这次运气好，是合法 JSON —— 但「运气好」不能作为工程依赖！[/green]\n")
    except json.JSONDecodeError as e:
        console.print(f"[red]解析失败：{e} —— 这就是只靠 Prompt 的风险[/red]\n")


def demo_2_json_mode() -> None:
    """演示 2：开启 JSON 模式 —— API 层面保证输出是合法 JSON。

    关键参数：response_format={"type": "json_object"}
    注意两点（DeepSeek 与 OpenAI 的要求一致）：
      1. Prompt 里必须出现 "json" 这个词，否则 API 会报错
      2. 最好在 Prompt 里给出字段示例，否则字段名仍然可能漂移
    """
    console.rule("[bold cyan]演示 2：JSON 模式（json_object）")

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "你是博客元数据提取器，必须输出 JSON，格式示例：\n"
                    '{"title": "文章标题", "category": "frontend", '
                    '"tags": ["tag1", "tag2"], "summary": "50字以内摘要"}'
                ),
            },
            {"role": "user", "content": f"提取这篇文章的元数据：\n{ARTICLE}"},
        ],
        # 这一行是本演示的核心：强制模型输出合法 JSON
        response_format={"type": "json_object"},
        temperature=0,
    )
    raw = response.choices[0].message.content
    data = json.loads(raw)  # JSON 模式下，这里一定能解析成功
    console.print(Panel(json.dumps(data, ensure_ascii=False, indent=2), title="解析后的 JSON", border_style="green"))
    console.print("[yellow]JSON 一定合法了，但「字段名对不对、类型对不对」仍然没有保证 -> 看演示 3。[/yellow]\n")


# ---------------------------------------------------------------------------
# 演示 3 的准备：用 Pydantic 定义「我们期望的数据结构」
# Pydantic 是 Python 生态的数据校验标准库（FastAPI 也基于它），
# 它能在运行时校验：字段是否齐全、类型是否正确、取值是否合法。
# ---------------------------------------------------------------------------
class ArticleMeta(BaseModel):
    """博客文章元数据 —— 实战项目中知识库的基础数据结构。"""

    title: str = Field(description="文章标题，10~30个字")
    category: str = Field(description="分类，只能是 frontend / backend / ai 之一")
    tags: list[str] = Field(description="2~4个英文标签", min_length=2, max_length=4)
    summary: str = Field(description="50字以内的中文摘要", max_length=60)


def demo_3_pydantic_with_retry(max_retries: int = 3) -> ArticleMeta:
    """演示 3：JSON 模式 + Pydantic 校验 + 失败自动重试（生产级写法）。

    流程：
        调用 LLM(JSON模式) -> json.loads -> Pydantic 校验
            -> 校验通过：返回强类型对象
            -> 校验失败：把错误信息喂回给模型，让它修正后重试
    """
    console.rule("[bold cyan]演示 3：Pydantic 校验 + 自动重试")

    # 技巧：直接把 Pydantic 模型的 JSON Schema 放进 Prompt，
    # 模型照着 Schema 输出，字段名/类型的准确率会高很多
    schema = json.dumps(ArticleMeta.model_json_schema(), ensure_ascii=False)
    messages = [
        {
            "role": "system",
            "content": f"你是博客元数据提取器，输出必须是符合此 JSON Schema 的 json：\n{schema}",
        },
        {"role": "user", "content": f"提取这篇文章的元数据：\n{ARTICLE}"},
    ]

    for attempt in range(1, max_retries + 1):
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0,
        )
        raw = response.choices[0].message.content

        try:
            # model_validate_json = json解析 + 字段校验，一步完成
            meta = ArticleMeta.model_validate_json(raw)
            console.print(f"[green]第 {attempt} 次尝试校验通过！[/green]")
            console.print(Panel(repr(meta), title="强类型的 ArticleMeta 对象", border_style="green"))
            return meta
        except ValidationError as e:
            console.print(f"[red]第 {attempt} 次校验失败：{e.error_count()} 个错误[/red]")
            # 关键技巧：把模型的错误输出和校验错误一起喂回去，让它自我修正
            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {
                    "role": "user",
                    "content": f"你输出的 json 没有通过校验，错误信息：\n{e}\n请修正后重新输出完整 json。",
                }
            )

    raise RuntimeError(f"重试 {max_retries} 次后仍无法获得合法输出")


if __name__ == "__main__":
    demo_1_prompt_only()
    demo_2_json_mode()
    meta = demo_3_pydantic_with_retry()
    # 拿到强类型对象后，就可以像普通 Python 对象一样安全使用了
    console.print(f"\n标题：{meta.title}")
    console.print(f"标签：{', '.join(meta.tags)}")
    console.print("\n[bold green]本章演示全部完成！下一章学习 Function Calling —— Agent 的基石。[/bold green]")
