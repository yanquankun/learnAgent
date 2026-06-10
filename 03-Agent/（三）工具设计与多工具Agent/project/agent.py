"""
agent.py —— 基于 Function Calling 的通用 Agent 类

把 01 模块第四章的 run_with_tools() 循环升级成可复用的 Agent 类：
  - 工具来自 tools.py 的注册表（自动生成 schema）
  - 工具执行错误作为 Observation 喂回模型（自我纠正）
  - max_rounds 安全阀防止死循环
  - verbose 模式打印每一步决策过程（Agent 可观测性的最小实现）

这个类大约 80 行 —— 市面上 Agent 框架的核心循环也就是它的加强版。
"""

import json

from rich.console import Console

from llm_client import MODEL, get_client
from tools import execute, get_schemas

console = Console()


class Agent:
    """单 Agent + 多工具的最小实现。"""

    def __init__(self, system_prompt: str, max_rounds: int = 8, verbose: bool = True):
        self.system_prompt = system_prompt
        self.max_rounds = max_rounds   # 安全阀：最多允许几轮工具调用
        self.verbose = verbose
        self.client = get_client()

    def _log(self, text: str) -> None:
        if self.verbose:
            console.print(text)

    def run(self, task: str) -> str:
        """执行一个任务，返回最终回答。

        循环逻辑（和 01 模块四章一致，但工具来自注册表）：
            模型返回 tool_calls -> 逐个执行 -> 结果回传 -> 直到输出文字回答
        """
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": task},
        ]

        for round_no in range(1, self.max_rounds + 1):
            response = self.client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=get_schemas(),  # schema 由注册表自动生成
                temperature=0,
            )
            message = response.choices[0].message

            # 模型不再调用工具 -> 最终回答
            if not message.tool_calls:
                return message.content

            messages.append(message)  # tool_calls 消息必须进入历史

            for tc in message.tool_calls:
                name = tc.function.name
                args = json.loads(tc.function.arguments)
                self._log(f"[blue]第{round_no}轮[/blue] 调用 [bold]{name}[/bold]({args})")

                # execute 内部已把异常转成错误文本，这里永远不会抛异常
                result = execute(name, args)
                self._log(f"        -> {result[:80]}{'…' if len(result) > 80 else ''}")

                messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": result}
                )

        return "（达到最大轮数限制，任务未完成 —— 请检查工具是否反复失败）"
