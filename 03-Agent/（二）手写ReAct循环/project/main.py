"""
（二）手写 ReAct 循环 —— 演示入口

ReAct（Reason + Act）是 Agent 的鼻祖模式，出自论文
《ReAct: Synergizing Reasoning and Acting in Language Models》(2022)。

本章故意【不用 Function Calling API】，纯靠 Prompt 约定让模型输出：
    Thought: 我现在的思考……
    Action: 工具名[参数]
然后我们的代码解析这段文本、执行工具、把结果作为 Observation 喂回去。

为什么要学这种「原始」写法？
  1. 它把 Agent 循环的每个零件都暴露在明面上，没有任何 SDK 魔法
  2. 你会真正理解 Function Calling API 在背后帮你做了什么
  3. 面试时能讲清 ReAct 的人，比只会调框架的人稀缺得多

运行方式：
    cd 到本 project 目录 -> uv sync -> uv run python main.py
"""

import re
from datetime import date

from rich.console import Console
from rich.panel import Panel

from llm_client import MODEL, get_client

console = Console()
client = get_client()


# ---------------------------------------------------------------------------
# 工具定义（普通 Python 函数）
# ---------------------------------------------------------------------------
def calculate(expression: str) -> str:
    """计算数学表达式。"""
    allowed = set("0123456789+-*/.() ")
    if not set(expression) <= allowed:
        return "错误：表达式包含不允许的字符"
    try:
        return str(eval(expression))  # noqa: S307 —— 已做字符白名单
    except Exception as e:
        return f"计算出错：{e}"


def get_today(_: str = "") -> str:
    """返回今天的日期。"""
    return date.today().isoformat()


def search_blog(keyword: str) -> str:
    """模拟博客搜索（05 章会换成真正的向量检索）。"""
    fake_db = {
        "vite": "找到文章《webpack迁移Vite实录》：冷启动从12秒降到0.8秒，发布于2025-09-03",
        "useeffect": "找到文章《React useEffect 依赖数组的常见陷阱》：讲解严格模式二次执行、依赖数组、清理函数，发布于2025-08-12",
        "react": "找到文章《React useEffect 依赖数组的常见陷阱》：发布于2025-08-12",
        "docker": "找到文章《用Docker Compose一键部署Postgres和Redis》：发布于2025-10-21",
    }
    for key, result in fake_db.items():
        if key in keyword.lower():
            return result
    return "没有找到相关文章"


TOOLS = {
    "calculate": (calculate, "计算数学表达式，输入如：38*17+5"),
    "get_today": (get_today, "获取今天的日期，输入留空即可"),
    "search_blog": (search_blog, "按关键词搜索博客文章，输入如：vite"),
}


# ---------------------------------------------------------------------------
# ReAct 的 System Prompt —— 整个模式的灵魂
# 用 Prompt 约定一个「文本协议」：模型必须按 Thought/Action 格式输出
# ---------------------------------------------------------------------------
def build_system_prompt() -> str:
    tool_lines = "\n".join(f"  - {name}: {desc}" for name, (_, desc) in TOOLS.items())
    return f"""你是一个会使用工具解决问题的助手，严格按 ReAct 格式工作。

可用工具：
{tool_lines}

输出格式（每次回复只能输出一个 Thought 和一个动作）：

需要使用工具时：
Thought: <分析当前情况，思考下一步>
Action: <工具名>[<输入参数>]

得到足够信息、可以回答时：
Thought: <总结思考>
Final Answer: <给用户的最终回答>

规则：
1. 每次只执行一个 Action，等待 Observation 后再继续
2. 不要自己编造 Observation —— 工具结果由系统提供
3. 涉及计算、日期、博客内容时必须用工具，不要凭记忆回答"""


# 解析模型输出中的 "Action: 工具名[参数]"
ACTION_RE = re.compile(r"Action:\s*(\w+)\[(.*?)\]", re.S)
FINAL_RE = re.compile(r"Final Answer:\s*(.*)", re.S)


def run_react(question: str, max_steps: int = 6) -> str:
    """ReAct 主循环 —— 本章的核心代码。

    流程：
        1. 把问题交给模型，模型输出 Thought + Action
        2. 代码解析 Action，执行对应工具
        3. 把结果以 "Observation: ..." 追加到对话，回到第 1 步
        4. 模型输出 Final Answer 时结束

    max_steps 是安全阀：防止模型陷入「调用→失败→再调用」的死循环。
    """
    messages = [
        {"role": "system", "content": build_system_prompt()},
        {"role": "user", "content": question},
    ]

    for step in range(1, max_steps + 1):
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            temperature=0,
            # stop 序列：模型一旦想自己编造 "Observation:" 就立刻截断
            # 这是文本协议 ReAct 的经典技巧
            stop=["Observation:"],
        )
        output = response.choices[0].message.content
        console.print(Panel(output.strip(), title=f"第 {step} 步 模型输出", border_style="cyan"))

        # 情况 1：模型给出了最终答案 -> 循环结束
        final_match = FINAL_RE.search(output)
        if final_match:
            return final_match.group(1).strip()

        # 情况 2：模型请求执行一个 Action
        action_match = ACTION_RE.search(output)
        if action_match:
            tool_name = action_match.group(1).strip()
            tool_input = action_match.group(2).strip()

            if tool_name in TOOLS:
                tool_func = TOOLS[tool_name][0]
                observation = tool_func(tool_input)
            else:
                # 工具名写错了也作为 Observation 告诉模型，让它自我纠正
                observation = f"错误：不存在名为 {tool_name} 的工具"

            console.print(f"  [yellow]Observation: {observation}[/yellow]\n")

            # 把模型输出和工具结果都追加进对话历史
            messages.append({"role": "assistant", "content": output})
            messages.append({"role": "user", "content": f"Observation: {observation}"})
            continue

        # 情况 3：格式不对（既没有 Action 也没有 Final Answer）-> 提醒模型
        messages.append({"role": "assistant", "content": output})
        messages.append({"role": "user", "content": "请严格按格式输出 Action 或 Final Answer。"})

    return "（达到最大步数限制，任务未完成）"


if __name__ == "__main__":
    # 这个问题需要模型连续推理：先查日期 -> 再搜文章 -> 再算天数
    question = "我博客里那篇讲 vite 迁移的文章发布多少天了？请用工具一步步查证后计算。"
    console.rule("[bold cyan]ReAct Agent 演示")
    console.print(f"任务：{question}\n")

    answer = run_react(question)
    console.print(Panel(answer, title="最终答案", border_style="green"))
    console.print(
        "\n[yellow]复盘要点：注意模型是如何「自主规划」步骤顺序的 ——\n"
        "先 get_today 拿日期，再 search_blog 拿发布日期，最后 calculate 算差值。\n"
        "这个顺序没有写在任何代码里，完全是模型自己决定的 —— 这就是 Agent。[/yellow]"
    )
