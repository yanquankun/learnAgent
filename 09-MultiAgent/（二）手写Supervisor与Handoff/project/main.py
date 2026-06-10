"""
（二）手写 Supervisor 与 Handoff 机制

运行：uv run python main.py（两个演示都需要 LLM_API_KEY；未配置时友好跳过）

演示：
    1. 消息配对事故现场 —— AIMessage(tool_calls) 后面少了 ToolMessage 会怎样
    2. 完整团队协作 —— supervisor 调度两个 worker 回答复合问题，
       打印轨迹（责任可追溯）与分 Agent 的 token 成本表
"""

import os

from rich.console import Console
from rich.table import Table

console = Console()


def has_llm() -> bool:
    key = os.getenv("LLM_API_KEY", "")
    return bool(key) and "请替换" not in key


# ============================================================
# 演示 1：消息配对 —— 多 Agent 最隐蔽的坑
# ============================================================

def demo_1_pairing() -> None:
    console.rule("[bold cyan]演示 1：tool_call 与 ToolMessage 的配对规则")

    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    from lc_client import get_chat_model
    from team import search_blog

    model = get_chat_model(temperature=0).bind_tools([search_blog])

    # 手工构造一条「带 tool_calls 的 AIMessage」—— 模拟移交后的共享历史
    ai_with_call = AIMessage(content="", tool_calls=[
        {"name": "search_blog", "args": {"keyword": "docker"}, "id": "call_demo_001"}
    ])

    # ---- 错误姿势：漏掉配对的 ToolMessage，直接接用户消息 ----
    broken = [HumanMessage(content="博客里有几篇 Docker 文章？"),
              ai_with_call,
              HumanMessage(content="然后呢？")]
    try:
        model.invoke(broken)
        console.print("[yellow]（这个服务商没有严格校验，但 OpenAI 兼容协议要求必须配对）[/yellow]")
    except Exception as exc:
        console.print(f"[red]漏配 ToolMessage -> 调用直接报错：{str(exc)[:120]}…[/red]")

    # ---- 正确姿势：每个 tool_call_id 都有配对的 ToolMessage ----
    fixed = [HumanMessage(content="博客里有几篇 Docker 文章？"),
             ai_with_call,
             ToolMessage(content="共 3 篇 Docker 相关文章", tool_call_id="call_demo_001"),
             HumanMessage(content="然后呢？")]
    reply = model.invoke(fixed)
    console.print(f"[green]配对完整 -> 正常回复：{reply.content[:80]}…[/green]")
    console.print("[dim]多 Agent 拼接/裁剪共享历史时，配对一旦被剪断就是线上 400 —— \n"
                  "裁剪历史必须以「AIMessage(tool_calls)+其全部 ToolMessage」为原子单位[/dim]\n")


# ============================================================
# 演示 2：完整团队协作（轨迹 + 成本表）
# ============================================================

def demo_2_team() -> None:
    console.rule("[bold cyan]演示 2：Supervisor 团队实战")

    from team import run_team

    question = "我的博客里有几篇 Docker 相关的文章？占全部文章的百分之多少？"
    console.print(f"[yellow]用户：{question}[/yellow]\n")

    result = run_team(question)

    console.print("[bold]执行轨迹：[/bold]")
    for step in result["trace"]:
        console.print(f"  {step}")
    console.print(f"\n[green]最终答案：{result['answer']}[/green]\n")

    table = Table(title=f"token 成本表（共移交 {result['handoffs']} 次）")
    for col in ("Agent", "LLM调用次数", "输入token", "输出token"):
        table.add_column(col, justify="right")
    total_in = total_out = 0
    for agent, c in result["cost"].items():
        table.add_row(agent, str(c["calls"]), str(c["input"]), str(c["output"]))
        total_in += c["input"]
        total_out += c["output"]
    table.add_row("合计", "-", str(total_in), str(total_out))
    console.print(table)
    console.print("[dim]supervisor 的输入 token 通常最高（每次决策都要读共享历史）——\n"
                  "这就是为什么 worker 必须摘要化回传，垃圾进共享历史是全队反复付费[/dim]\n")


if __name__ == "__main__":
    if not has_llm():
        console.print("[dim]未配置 LLM_API_KEY：本章两个演示都依赖真实 LLM 调度，已跳过。\n"
                      "配置后可看到：配对报错现场 + 团队协作轨迹与成本表。\n"
                      "（图结构与离线机制演示见（一）章 project）[/dim]")
    else:
        demo_1_pairing()
        demo_2_team()
