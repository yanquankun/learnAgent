"""
（三）实战：博客内容团队 —— 单 Agent vs 多 Agent 对照实验

运行：uv run python main.py
    演示 1（语义检索）离线可跑；演示 2（对照实验）需要 LLM_API_KEY。

任务：「根据博客已有文章，写一篇《容器化部署个人博客的完整方案》的大纲与草稿」
    多 Agent：researcher -> writer -> reviewer（不达标打回，上限 2 轮）
    单 Agent：一个 LLM + 检索工具全包
对比维度：token 成本 / 耗时 / 质量评分（同一个裁判 prompt 打分）
"""

import os

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

import corpus

console = Console()

TOPIC = "容器化部署个人博客的完整方案"


def has_llm() -> bool:
    key = os.getenv("LLM_API_KEY", "")
    return bool(key) and "请替换" not in key


def demo_1_corpus() -> None:
    console.rule("[bold cyan]演示 1：researcher 的检索底座（离线）")
    for h in corpus.search(TOPIC, top_k=3):
        console.print(f"  {h['score']:.3f}  《{h['title']}》")
    console.print("[dim]researcher 拿到的就是这些 —— 检索质量决定全队上限（错误级联的源头）[/dim]\n")


def demo_2_experiment() -> None:
    console.rule("[bold cyan]演示 2：单 Agent vs 多 Agent 对照实验")

    from content_team import judge, run_single, run_team

    console.print(f"任务主题：{TOPIC}\n")

    console.print("[bold]>>> 单 Agent 基线跑起来…[/bold]")
    single = run_single(TOPIC)
    console.print(f"  完成：{single['seconds']}s / {single['tokens']} tokens\n")

    console.print("[bold]>>> 多 Agent 团队跑起来…[/bold]")
    team = run_team(TOPIC)
    for step in team["trace"]:
        console.print(f"  {step}")
    console.print(f"  完成：{team['seconds']}s / {team['tokens']} tokens\n")

    # 同一个裁判给两份产出打分（评审环节对 writer 的加成已经发生在 team 内部）
    s_review = judge(TOPIC, single["draft"])
    t_review = judge(TOPIC, team["draft"])

    table = Table(title="对照实验结果（同任务、同检索工具、同裁判）")
    for col in ("维度", "单 Agent", "多 Agent 团队"):
        table.add_column(col, justify="right")
    table.add_row("token 总量", f"{single['tokens']:,}", f"{team['tokens']:,}")
    table.add_row("耗时", f"{single['seconds']}s", f"{team['seconds']}s")
    table.add_row("裁判评分", f"{s_review.score}/10", f"{t_review.score}/10")
    table.add_row("LLM 调用次数",
                  str(sum(c["calls"] for c in single["cost"].values())),
                  str(sum(c["calls"] for c in team["cost"].values())))
    console.print(table)

    console.print(Panel(team["draft"][:600] + "\n…", title="多 Agent 产出（节选）"))
    console.print(
        "[dim]典型结论：多 Agent 成本约为单 Agent 的 2-4 倍，质量在「评审打回」生效时"
        "更稳（尤其复杂主题）。\n是否值得，取决于你的场景里质量差距换不换得回成本 —— "
        "这正是（一）章判断三标准的量化版。[/dim]"
    )


if __name__ == "__main__":
    demo_1_corpus()
    if has_llm():
        demo_2_experiment()
    else:
        console.print("[dim]未配置 LLM_API_KEY，跳过对照实验。配置后可看到：\n"
                      "  researcher->writer->reviewer 的协作轨迹（含打回重写）\n"
                      "  单/多 Agent 的 token、耗时、评分三维对比表[/dim]")
