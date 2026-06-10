"""
（一）何时需要 MultiAgent：四种模式的最小可跑骨架

运行：uv run python main.py（全部离线，不需要 API Key）

本章代码刻意「去 LLM 化」：所有决策都用规则函数代替模型调用，
让你把注意力全部放在**控制流与上下文的流动**上 ——
看清骨架之后，第二章把规则换成真 LLM 就是水到渠成。

四个演示：
    1. Pipeline      固定边，无动态决策（05-一 的形态）
    2. Supervisor    中心节点用 Command(goto=...) 动态分派
    3. Handoff 互踢  点对点移交 + 「无限互踢」事故现场与防环修复
    4. 成本对照      共享完整历史 vs 隔离+摘要回传 的 token 账单
"""

from typing import Literal

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from rich.console import Console
from rich.table import Table
from typing_extensions import TypedDict

console = Console()


# ============================================================
# 演示 1：Pipeline —— 固定边，没有任何动态决策
# ============================================================

class PipeState(TypedDict):
    text: str


def demo_1_pipeline() -> None:
    console.rule("[bold cyan]演示 1：Pipeline（固定流水线）")

    def load(state: PipeState) -> dict:
        return {"text": state["text"] + " -> 已加载"}

    def retrieve(state: PipeState) -> dict:
        return {"text": state["text"] + " -> 已检索"}

    def generate(state: PipeState) -> dict:
        return {"text": state["text"] + " -> 已生成"}

    builder = StateGraph(PipeState)
    builder.add_node("load", load)
    builder.add_node("retrieve", retrieve)
    builder.add_node("generate", generate)
    # 控制流完全写死在边上 —— 这就是 Pipeline 与 Agent 的本质区别
    builder.add_edge(START, "load")
    builder.add_edge("load", "retrieve")
    builder.add_edge("retrieve", "generate")
    builder.add_edge("generate", END)

    result = builder.compile().invoke({"text": "任务"})
    console.print(f"执行轨迹：{result['text']}")
    console.print("[dim]步骤确定就用 Pipeline —— 最便宜、最好调，别给确定性流程上 Agent[/dim]\n")


# ============================================================
# 演示 2：Supervisor —— 中心节点动态分派
# ============================================================

class TeamState(TypedDict):
    task: str
    results: dict        # worker 名 -> 回传的「结论摘要」（不是过程）
    trace: list[str]     # 带 Agent 标签的轨迹（责任可追溯）


def demo_2_supervisor() -> None:
    console.rule("[bold cyan]演示 2：Supervisor（中心调度）")

    # Command 是 LangGraph 的路由原语：节点返回 Command(goto=..., update=...)
    # 同时完成「改状态」和「决定下一跳」—— 这就是动态控制流的底层机制。
    # 本章用规则决定 goto；第二章换成 LLM 决定，骨架一行不用改。
    def supervisor(state: TeamState) -> Command[Literal["searcher", "calculator", "__end__"]]:
        if "searcher" not in state["results"]:
            goto = "searcher"
        elif "calculator" not in state["results"]:
            goto = "calculator"
        else:
            console.print(f"  [green]supervisor 汇总：{state['results']}[/green]")
            return Command(goto=END)
        return Command(goto=goto, update={"trace": state["trace"] + [f"supervisor->{goto}"]})

    def searcher(state: TeamState) -> Command[Literal["supervisor"]]:
        # worker 内部可能查了 10 个网页（过程），但只回传一句结论 ——
        # 摘要化回传是控制多 Agent 成本的第一杠杆（见演示 4 的账单）
        conclusion = "检索结论：博客共有 6 篇文章，3 篇与 Docker 相关"
        return Command(goto="supervisor", update={
            "results": {**state["results"], "searcher": conclusion},
            "trace": state["trace"] + ["searcher 完成"],
        })

    def calculator(state: TeamState) -> Command[Literal["supervisor"]]:
        conclusion = "计算结论：Docker 文章占比 50%"
        return Command(goto="supervisor", update={
            "results": {**state["results"], "calculator": conclusion},
            "trace": state["trace"] + ["calculator 完成"],
        })

    builder = StateGraph(TeamState)
    builder.add_node("supervisor", supervisor)
    builder.add_node("searcher", searcher)
    builder.add_node("calculator", calculator)
    builder.add_edge(START, "supervisor")
    # 注意：没有添加任何固定边！所有跳转都由 Command(goto=...) 在运行时决定

    result = builder.compile().invoke({"task": "统计博客中 Docker 文章占比", "results": {}, "trace": []})
    console.print("执行轨迹：", " | ".join(result["trace"]))
    console.print()


# ============================================================
# 演示 3：Handoff 与「无限互踢」事故现场
# ============================================================

class HandoffState(TypedDict):
    question: str
    handoffs: int
    answer: str


def build_handoff_graph(max_handoffs: int):
    """两个客服 Agent 点对点移交。规则故意写出「互踢」bug：
    售前认为退款该售后管，售后认为「买前咨询」该售前管 —— 都不接。
    """

    def make_agent(name: str, other: str):
        def agent(state: HandoffState) -> Command:
            # 防环闸门：移交次数到上限，谁手里就谁兜底回答
            if state["handoffs"] >= max_handoffs:
                return Command(goto=END, update={
                    "answer": f"{name} 兜底回答（移交已达上限 {max_handoffs} 次）"})
            # 故意的互踢规则：两边都觉得「这问题不归我管」
            return Command(goto=other, update={"handoffs": state["handoffs"] + 1})
        return agent

    builder = StateGraph(HandoffState)
    builder.add_node("presale", make_agent("售前", "aftersale"))
    builder.add_node("aftersale", make_agent("售后", "presale"))
    builder.add_edge(START, "presale")
    return builder.compile()


def demo_3_handoff_pingpong() -> None:
    console.rule("[bold cyan]演示 3：Handoff 与无限互踢")

    # LangGraph 默认 recursion_limit=25，真无限循环会直接抛异常 ——
    # 框架兜底救得了进程，救不了已经烧掉的 24 次 LLM 调用费
    question = {"question": "我买之前想问下，不满意能退款吗？", "handoffs": 0, "answer": ""}

    graph = build_handoff_graph(max_handoffs=999)   # 形同没有上限
    try:
        graph.invoke(question, {"recursion_limit": 10})
    except Exception as exc:
        console.print(f"[red]没有防环上限：{type(exc).__name__} —— 互踢到框架递归限制才被掐断[/red]")

    result = build_handoff_graph(max_handoffs=3).invoke(question)
    console.print(f"[green]加上防环上限：{result['answer']}[/green]")
    console.print("[dim]防环三件套：移交次数上限 + 兜底直答 + 轨迹日志（二章在真 LLM 上实现）[/dim]\n")


# ============================================================
# 演示 4：成本对照 —— 通信策略决定 token 账单
# ============================================================

def est_tokens(chars: int) -> int:
    """粗估：中文约 1 token ≈ 1.7 字符（够看出量级差异）。"""
    return int(chars / 1.7)


def demo_4_cost_compare() -> None:
    console.rule("[bold cyan]演示 4：共享完整历史 vs 隔离+摘要回传（token 账单）")

    agents, rounds = 3, 4          # 3 个 Agent 协作 4 轮
    output_chars = 600             # 每次发言约 600 字（中间过程）
    summary_chars = 80             # 摘要回传只有 80 字结论
    system_chars = 400             # 每个 Agent 的 system prompt

    # 策略 A：所有 Agent 共享同一条完整 messages
    # 第 n 次调用的输入 = system + 之前所有人的全部发言
    shared_input = 0
    history = 0
    for _ in range(rounds):
        for _ in range(agents):
            shared_input += est_tokens(system_chars + history)
            history += output_chars

    # 策略 B：各 Agent 私有上下文，只能看到别人回传的「摘要」
    isolated_input = 0
    summaries = 0
    for _ in range(rounds):
        for _ in range(agents):
            isolated_input += est_tokens(system_chars + summaries + output_chars)
            summaries += summary_chars

    table = Table(title=f"{agents} 个 Agent 协作 {rounds} 轮的输入 token 估算")
    table.add_column("通信策略")
    table.add_column("输入 token 总量", justify="right")
    table.add_column("相对成本", justify="right")
    table.add_row("A. 共享完整历史", f"{shared_input:,}", f"{shared_input / isolated_input:.1f}x")
    table.add_row("B. 隔离 + 摘要回传", f"{isolated_input:,}", "1.0x")
    console.print(table)
    console.print("[dim]共享历史的成本是 O(轮数²)，隔离+摘要近似 O(轮数) ——\n"
                  "轮数越多差距越大；代价是摘要可能丢细节，这是设计时要显式权衡的取舍[/dim]\n")


if __name__ == "__main__":
    demo_1_pipeline()
    demo_2_supervisor()
    demo_3_handoff_pingpong()
    demo_4_cost_compare()
