"""
team.py —— 手写 Supervisor + Handoff 的完整实现

结构（一张平铺图，没有任何固定边，全部 Command 动态路由）：

    supervisor（真 LLM 调度）
        ├── handoff 工具: transfer_to_searcher / transfer_to_calculator
        ├── 防环闸门: handoffs >= MAX_HANDOFFS 时没收工具、强制直答
        └── 不调工具 = 给出最终答案 -> END
    searcher / calculator（worker）
        ├── 私有上下文: 只看到「任务描述」，看不到团队完整历史
        ├── 自带工具的小型 ReAct 循环（上限 3 轮）
        └── 只回传一句「结论摘要」—— 过程不出 worker

三个本章核心机制都在这个文件里：
    ① 消息配对: AIMessage(tool_calls) 之后必须紧跟配对的 ToolMessage
    ② 摘要化回传: worker 的 ReAct 过程不进共享 messages
    ③ token 计量: 每次 LLM 调用按 Agent 记账，最后能打出成本表
"""

import json
from collections import defaultdict
from typing import Literal

from langchain_core.messages import (
    AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage,
)
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Command
from typing_extensions import Annotated, TypedDict

from lc_client import get_chat_model

MAX_HANDOFFS = 5          # 防环：supervisor 最多分派 5 次
WORKER_MAX_STEPS = 3      # worker 内部 ReAct 循环上限

# token 记账本：agent 名 -> {"input": n, "output": n, "calls": n}
COST: dict[str, dict] = defaultdict(lambda: {"input": 0, "output": 0, "calls": 0})


def _track(agent: str, response: AIMessage) -> None:
    usage = response.usage_metadata or {}
    COST[agent]["input"] += usage.get("input_tokens", 0)
    COST[agent]["output"] += usage.get("output_tokens", 0)
    COST[agent]["calls"] += 1


def reset_cost() -> None:
    COST.clear()


# ============================================================
# worker 的业务工具（刻意保持简单，重点在协作机制）
# ============================================================

BLOG_INDEX = [
    {"id": "docker-intro", "title": "Docker 入门：从镜像到容器", "tags": ["docker"]},
    {"id": "docker-compose-deploy", "title": "用 Docker Compose 部署全栈应用", "tags": ["docker", "deploy"]},
    {"id": "dockerfile-best", "title": "Dockerfile 写法的十个最佳实践", "tags": ["docker"]},
    {"id": "vite-migration", "title": "博客从 webpack 迁移到 Vite 实录", "tags": ["vite", "frontend"]},
    {"id": "typescript-tips", "title": "TypeScript 高级类型实用技巧", "tags": ["typescript", "frontend"]},
    {"id": "python-env-uv", "title": "用 uv 管理 Python 项目环境", "tags": ["python"]},
]


@tool
def search_blog(keyword: str) -> str:
    """按关键词检索博客文章，返回命中的标题列表。"""
    hits = [a for a in BLOG_INDEX
            if keyword.lower() in a["title"].lower() or keyword.lower() in a["tags"]]
    if not hits:
        return f"没有找到包含「{keyword}」的文章"
    return json.dumps({"total": len(BLOG_INDEX), "hits": [a["title"] for a in hits]},
                      ensure_ascii=False)


@tool
def calculate(expression: str) -> str:
    """计算一个算术表达式，如 3/6*100。"""
    allowed = set("0123456789+-*/().% ")
    if not set(expression) <= allowed:
        return "表达式包含不允许的字符"
    try:
        return str(round(eval(expression), 4))  # noqa: S307 字符白名单已限制
    except Exception as exc:
        return f"计算失败：{exc}"


WORKERS = {
    "searcher": {
        "prompt": "你是博客检索员。用 search_blog 工具查证后回答，禁止凭记忆编造。",
        "tools": [search_blog],
    },
    "calculator": {
        "prompt": "你是数据计算员。所有算术都必须用 calculate 工具完成，不要心算。",
        "tools": [calculate],
    },
}


# ============================================================
# handoff 工具：只是「给 LLM 看的路由选项」，真正的跳转在 supervisor 节点里
# ============================================================

@tool
def transfer_to_searcher(task: str) -> str:
    """需要查博客文章（数量/标题/某主题有哪些）时，把任务移交给博客检索员。
    task 要写成给检索员的完整任务描述。"""
    return task   # 占位：实际执行发生在 supervisor 节点


@tool
def transfer_to_calculator(task: str) -> str:
    """需要算术计算（占比/求和/平均）时，把任务移交给数据计算员。
    task 要写成给计算员的完整任务描述，包含必需的数字。"""
    return task


HANDOFF_TARGET = {"transfer_to_searcher": "searcher", "transfer_to_calculator": "calculator"}


# ============================================================
# 图的状态与节点
# ============================================================

class TeamState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]   # 共享历史（只有摘要级内容）
    handoffs: int
    trace: list[str]    # 带 Agent 标签的轨迹（责任可追溯）


SUPERVISOR_PROMPT = (
    "你是团队协调者，负责回答用户问题。你手下有两位专家：\n"
    "- 博客检索员（transfer_to_searcher）：查博客文章\n"
    "- 数据计算员（transfer_to_calculator）：做算术\n"
    "规则：一次只移交一个任务；专家回报的结论已在对话里，不要重复移交同一任务；"
    "信息凑齐后直接输出最终答案（不调用任何工具）。"
)


def supervisor(state: TeamState) -> Command[Literal["searcher", "calculator", "__end__"]]:
    model = get_chat_model(temperature=0)

    # ---- 防环闸门：移交次数到上限就「没收工具」，模型只能直答 ----
    if state["handoffs"] >= MAX_HANDOFFS:
        response = model.invoke(
            [SystemMessage(content=SUPERVISOR_PROMPT + "\n（移交额度已用完，基于已有信息直接回答）"),
             *state["messages"]]
        )
        _track("supervisor", response)
        return Command(goto=END, update={
            "messages": [response],
            "trace": state["trace"] + ["supervisor: 达到移交上限，兜底直答"],
        })

    response = model.bind_tools(
        [transfer_to_searcher, transfer_to_calculator]
    ).invoke([SystemMessage(content=SUPERVISOR_PROMPT), *state["messages"]])
    _track("supervisor", response)

    # ---- 不调工具 = 信息已凑齐，这就是最终答案 ----
    if not response.tool_calls:
        return Command(goto=END, update={
            "messages": [response],
            "trace": state["trace"] + ["supervisor: 输出最终答案"],
        })

    # ---- 调了 handoff 工具：路由给对应 worker ----
    call = response.tool_calls[0]
    target = HANDOFF_TARGET[call["name"]]
    task = call["args"].get("task", "")

    # ★ 消息配对（本章最隐蔽的坑）：
    # response 里带着 tool_calls，进入共享历史后，必须紧跟一条
    # tool_call_id 配对的 ToolMessage —— 否则下一次把历史喂给 LLM 时
    # OpenAI 兼容接口直接报 400（demo_pairing 有事故现场）。
    # 即使模型一次吐出多个 tool_calls，每一个都必须有配对的 ToolMessage。
    pairing_msgs = [ToolMessage(content=f"已移交给 {target}：{task}",
                                tool_call_id=tc["id"]) for tc in response.tool_calls]

    return Command(goto=target, update={
        "messages": [response, *pairing_msgs],
        "handoffs": state["handoffs"] + 1,
        "trace": state["trace"] + [f"supervisor -> {target}（任务：{task[:30]}…）"],
    })


def make_worker(name: str):
    """生成 worker 节点：私有上下文跑 ReAct，只回传一句结论摘要。"""
    spec = WORKERS[name]
    tools_by_name = {t.name: t for t in spec["tools"]}

    def worker(state: TeamState) -> Command[Literal["supervisor"]]:
        # ---- 上下文隔离：worker 只拿到「任务描述」（最后一条 ToolMessage）----
        # 它看不到团队完整历史 —— 这是控成本、防干扰的关键设计（一章演示 4 的账单）
        task = state["messages"][-1].content
        model = get_chat_model(temperature=0).bind_tools(spec["tools"])
        private: list[BaseMessage] = [
            SystemMessage(content=spec["prompt"] + "\n完成后用一句话报告结论。"),
            HumanMessage(content=task),
        ]

        steps = []
        for _ in range(WORKER_MAX_STEPS):
            response = model.invoke(private)
            _track(name, response)
            private.append(response)
            if not response.tool_calls:
                break
            for tc in response.tool_calls:   # 配对规则在 worker 私有上下文里同样成立
                output = tools_by_name[tc["name"]].invoke(tc["args"])
                steps.append(f"{tc['name']}({tc['args']}) -> {output}")
                private.append(ToolMessage(content=str(output), tool_call_id=tc["id"]))

        # ---- 摘要化回传：私有上下文（可能很长）就地丢弃，只交一句结论 ----
        conclusion = private[-1].content if private[-1].content else "（worker 没有产出结论）"
        return Command(goto="supervisor", update={
            "messages": [HumanMessage(content=f"[{name} 回报] {conclusion}")],
            "trace": state["trace"] + [f"{name}: 执行 {len(steps)} 次工具调用，回传结论"],
        })

    return worker


def build_team():
    builder = StateGraph(TeamState)
    builder.add_node("supervisor", supervisor)
    builder.add_node("searcher", make_worker("searcher"))
    builder.add_node("calculator", make_worker("calculator"))
    builder.add_edge(START, "supervisor")
    # 没有其他固定边：supervisor 与 worker 之间的全部流转都由 Command 决定
    return builder.compile()


def run_team(question: str) -> dict:
    reset_cost()
    graph = build_team()
    result = graph.invoke({
        "messages": [HumanMessage(content=question)],
        "handoffs": 0,
        "trace": [],
    })
    return {
        "answer": result["messages"][-1].content,
        "trace": result["trace"],
        "handoffs": result["handoffs"],
        "cost": {k: dict(v) for k, v in COST.items()},
    }
