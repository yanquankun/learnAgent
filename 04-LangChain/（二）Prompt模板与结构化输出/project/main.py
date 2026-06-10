"""
（二）Prompt 模板与结构化输出 —— 演示入口

把 01 模块的 Prompt 工程（二章）和结构化输出（三章）迁移到 LangChain：

    演示 1：ChatPromptTemplate —— 提示词从字符串拼接升级为「模板组件」
    演示 2：few-shot 模板化 —— 示例不再手写进 messages
    演示 3：with_structured_output —— 一行替代手写的「JSON校验+重试」循环
    演示 4：完整管道 —— 模板 | 模型 | 解析，三节车厢跑通

运行方式：
    cd 到本 project 目录 -> uv sync -> uv run python main.py
"""

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, FewShotChatMessagePromptTemplate
from pydantic import BaseModel, Field
from rich.console import Console
from rich.panel import Panel

from lc_client import get_chat_model

console = Console()
model = get_chat_model()


def demo_1_prompt_template() -> None:
    """演示 1：ChatPromptTemplate —— 模板是可复用、可组合的组件。

    手写版的痛点：f-string 拼提示词，变量散落各处、无法复用。
    模板版：变量名清晰声明，invoke 时统一填充，模板本身可以入库、版本化。
    """
    console.rule("[bold cyan]演示 1：ChatPromptTemplate")

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", "你是技术博客的{role}，回答控制在{max_len}字以内。"),
            ("user", "解释一下：{question}"),
        ]
    )

    # 模板填充后产出 messages（先看看中间产物，理解数据流）
    messages = prompt.invoke({"role": "AI助手", "max_len": 50, "question": "什么是Embedding"})
    console.print(f"[dim]模板填充结果：{messages.to_messages()}[/dim]\n")

    chain = prompt | model
    reply = chain.invoke({"role": "AI助手", "max_len": 50, "question": "什么是Embedding"})
    console.print(Panel(reply.content, title="回答", border_style="green"))


def demo_2_few_shot() -> None:
    """演示 2：few-shot 模板化 —— 对照 01 模块二章手写的示例消息。

    手写版要把示例一条条写进 messages；FewShotChatMessagePromptTemplate
    让「示例数据」和「模板结构」分离 —— 示例可以来自数据库、可以动态筛选。
    """
    console.rule("[bold cyan]演示 2：few-shot 模板化")

    examples = [
        {"input": "React useEffect 依赖数组的常见陷阱", "output": "react, hooks, use-effect"},
        {"input": "用 Docker Compose 部署 Postgres 和 Redis", "output": "docker, docker-compose, devops"},
    ]
    example_prompt = ChatPromptTemplate.from_messages(
        [("user", "{input}"), ("assistant", "{output}")]
    )
    few_shot = FewShotChatMessagePromptTemplate(
        examples=examples,
        example_prompt=example_prompt,
    )
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", "你是博客标签生成器，参考示例的风格为文章标题生成标签。"),
            few_shot,                       # 示例块插在 system 和真实输入之间
            ("user", "{title}"),
        ]
    )

    chain = prompt | model | StrOutputParser()  # StrOutputParser: AIMessage -> str
    tags = chain.invoke({"title": "深入理解浏览器的事件循环机制"})
    console.print(f"生成标签：[green]{tags}[/green]")
    console.print("[yellow]示例与模板分离后，「按相似度动态挑选示例」这类高级玩法才有可能。[/yellow]\n")


# ---- 演示 3 的目标结构：与 01 模块三章完全相同的 ArticleMeta，方便对照 ----
class ArticleMeta(BaseModel):
    """博客文章元数据。"""

    title: str = Field(description="文章标题，10~30个字")
    category: str = Field(description="分类，只能是 frontend / backend / ai 之一")
    tags: list[str] = Field(description="2~4个英文标签", min_length=2, max_length=4)
    summary: str = Field(description="50字以内的中文摘要", max_length=60)


ARTICLE = """
最近把博客的构建工具从 webpack 迁移到了 Vite，冷启动从 12 秒降到了 0.8 秒。
本文记录迁移过程中的三个坑：CommonJS 依赖处理、环境变量前缀变化、
以及生产构建的 Rollup 分包配置。对于中小型项目，非常推荐尽早迁移。
"""


def demo_3_structured_output() -> None:
    """演示 3：with_structured_output —— 一行替代手写的校验+重试循环。

    回想 01 模块三章你手写了什么：
        JSON模式参数 + Schema放进Prompt + json.loads + Pydantic校验 + 失败重试
    LangChain 把这一整套打包成一个方法：

        model.with_structured_output(ArticleMeta)

    它底层用 Function Calling 让模型按 schema 输出（比 JSON 模式更稳），
    返回值直接就是 Pydantic 对象。
    """
    console.rule("[bold cyan]演示 3：with_structured_output")

    structured_model = model.with_structured_output(ArticleMeta)
    meta = structured_model.invoke(f"提取这篇文章的元数据：\n{ARTICLE}")

    console.print(Panel(repr(meta), title="直接得到 ArticleMeta 对象", border_style="green"))
    console.print(f"类型校验：isinstance(meta, ArticleMeta) = {isinstance(meta, ArticleMeta)}")
    console.print(
        "[yellow]手写版约40行的「校验+喂回错误+重试」，现在一行。\n"
        "但正因为你手写过，你知道它失败时该去哪排查（schema太复杂/字段描述不清）。[/yellow]\n"
    )


def demo_4_full_chain() -> None:
    """演示 4：三节车厢的完整管道 —— 模板 | 模型(结构化) 组合应用。

    场景：批量提取文章元数据（实战索引 pipeline 的一个环节）。
    """
    console.rule("[bold cyan]演示 4：模板 + 结构化输出的完整管道")

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", "你是博客元数据提取器。"),
            ("user", "提取这篇文章的元数据：\n<article>{article}</article>"),
        ]
    )
    chain = prompt | model.with_structured_output(ArticleMeta)

    meta = chain.invoke({"article": ARTICLE})
    console.print(f"标题：{meta.title}")
    console.print(f"分类：{meta.category}  标签：{', '.join(meta.tags)}")
    console.print(f"摘要：{meta.summary}")


if __name__ == "__main__":
    demo_1_prompt_template()
    demo_2_few_shot()
    demo_3_structured_output()
    demo_4_full_chain()
    console.print("\n[bold green]本章完成！下一章用 LangChain 重写 02 模块的整套 RAG。[/bold green]")
