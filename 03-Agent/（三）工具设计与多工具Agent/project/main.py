"""
（三）工具设计与多工具 Agent —— 演示入口

本章把上一章的 ReAct 循环升级为生产级写法：
    1. Function Calling 替代文本协议（可靠的结构化参数）
    2. @tool 装饰器 + 注册表（写函数即得 schema，永不失同步）
    3. 工具错误作为 Observation（模型自我纠正，程序不崩溃）

演示内容：
    演示 1：看看注册表自动生成的 schema
    演示 2：多工具协作完成任务
    演示 3：工具报错时模型的自我纠正（本章最精彩的部分）

运行方式：
    cd 到本 project 目录 -> uv sync -> uv run python main.py
"""

import json
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from agent import Agent
from tools import get_schemas, tool

console = Console()
BASE_DIR = Path(__file__).parent


# ---------------------------------------------------------------------------
# 用 @tool 装饰器定义工具：写普通函数 + 类型注解 + docstring 即可
# 注意每个 docstring 都在回答「什么场景该用我」—— 这是工具设计的核心
# ---------------------------------------------------------------------------
@tool(param_desc={"expression": "Python 语法的数学表达式，如 '38*17+5'"})
def calculate(expression: str) -> str:
    """计算数学表达式的精确结果。任何涉及数字计算的场景都必须使用本工具，不要心算。"""
    allowed = set("0123456789+-*/.() ")
    if not set(expression) <= allowed:
        raise ValueError("表达式包含不允许的字符，只支持数字和 + - * / . ( )")
    return str(eval(expression))  # noqa: S307 —— 已做字符白名单


@tool()
def get_now() -> str:
    """获取当前的日期和时间。用户询问时间、日期、星期几时使用。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S（%A）")


@tool(param_desc={"filename": "文件名（相对于项目目录），如 'notes.txt'"})
def read_file(filename: str) -> str:
    """读取项目目录下指定文本文件的内容。用户要求查看、总结、分析某个文件时使用。"""
    path = (BASE_DIR / filename).resolve()
    # 安全边界：禁止读取项目目录以外的文件（防止 ../../etc/passwd 这类路径穿越）
    if not str(path).startswith(str(BASE_DIR.resolve())):
        raise PermissionError("禁止访问项目目录以外的文件")
    if not path.exists():
        raise FileNotFoundError(f"文件 {filename} 不存在。请确认文件名是否正确。")
    return path.read_text(encoding="utf-8")


@tool(param_desc={"text": "需要统计的文本内容"})
def count_words(text: str) -> str:
    """统计一段文本的字符数和行数。需要精确统计字数时使用。"""
    lines = text.splitlines()
    return f"字符数：{len(text)}，行数：{len(lines)}"


def demo_1_auto_schema() -> None:
    """演示 1：注册表自动生成的 schema —— 和上一模块手写的对比一下。"""
    console.rule("[bold cyan]演示 1：@tool 装饰器自动生成的 schema")
    schemas = get_schemas()
    console.print(f"共注册 {len(schemas)} 个工具：{[s['function']['name'] for s in schemas]}\n")
    console.print(Panel(
        json.dumps(schemas[0], ensure_ascii=False, indent=2),
        title="calculate 的 schema（从函数签名+docstring自动生成）",
        border_style="cyan",
    ))
    console.print("[yellow]函数改了参数，schema 自动跟着变 —— 代码即文档，永不失同步。[/yellow]\n")


def demo_2_multi_tool_task() -> None:
    """演示 2：一个需要多工具协作的任务。"""
    console.rule("[bold cyan]演示 2：多工具协作")

    agent = Agent(
        system_prompt="你是一个严谨的助手。优先使用工具获取准确信息，回答要简洁。",
    )
    answer = agent.run("读取 notes.txt，统计它的字数，并告诉我现在的时间。")
    console.print(Panel(answer, title="最终回答", border_style="green"))


def demo_3_self_correction() -> None:
    """演示 3：工具报错时的自我纠正（本章最精彩的部分）。

    我们故意让模型读一个不存在的文件。观察它收到错误 Observation 后的反应：
    通常它会改用正确的文件名重试（错误信息里有提示），或如实告知用户。
    """
    console.rule("[bold cyan]演示 3：错误自我纠正")

    agent = Agent(
        system_prompt=(
            "你是一个严谨的助手。项目目录下有一个 notes.txt 文件。"
            "工具调用失败时，分析错误原因并尝试修正。"
        ),
    )
    # 用户记错了文件名 —— 模型应该能从错误信息+系统提示中纠正过来
    answer = agent.run("帮我读取 note.md 这个文件的内容并总结成一句话。")
    console.print(Panel(answer, title="最终回答", border_style="green"))
    console.print(
        "[yellow]复盘：read_file 抛出 FileNotFoundError -> 被 execute() 转成错误文本\n"
        "-> 模型读到错误后自动改用 notes.txt 重试 —— 程序全程没有崩溃。\n"
        "「错误也是信息」是 Agent 工程最重要的设计哲学之一。[/yellow]"
    )


if __name__ == "__main__":
    demo_1_auto_schema()
    demo_2_multi_tool_task()
    demo_3_self_correction()
    console.print("\n[bold green]本章演示全部完成！下一章给 Agent 装上「记忆」。[/bold green]")
