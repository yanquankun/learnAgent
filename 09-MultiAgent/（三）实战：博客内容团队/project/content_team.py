"""
content_team.py —— 博客内容团队（多 Agent）与单 Agent 基线

任务：根据博客已有文章，为指定主题写「新文章大纲 + 开头草稿」。

多 Agent 版（Pipeline 骨架 + Evaluator 回路）：
    researcher  检索已有文章，产出素材清单（只回传素材，不回传检索过程）
    writer      基于素材写大纲与草稿；收到评审反馈则针对性重写
    reviewer    结构化评审（评分 + 是否通过 + 反馈）；不达标打回，上限 2 轮

单 Agent 基线：同一个任务、同一个检索工具，一个 LLM 全包 ——
对照实验的意义：用数据回答「多 Agent 值不值」，而不是凭感觉。
"""

import time
from collections import defaultdict
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

import corpus
from lc_client import get_chat_model

MAX_REVIEW_ROUNDS = 2     # 评审打回上限：防「永不满意」的无限回路

COST: dict[str, dict] = defaultdict(lambda: {"input": 0, "output": 0, "calls": 0})


def _track(agent: str, response) -> None:
    usage = response.usage_metadata or {}
    COST[agent]["input"] += usage.get("input_tokens", 0)
    COST[agent]["output"] += usage.get("output_tokens", 0)
    COST[agent]["calls"] += 1


def reset_cost() -> None:
    COST.clear()


def total_tokens() -> int:
    return sum(c["input"] + c["output"] for c in COST.values())


# ============================================================
# 多 Agent 版
# ============================================================

class TeamState(TypedDict):
    topic: str
    materials: str        # researcher 的素材清单
    draft: str            # writer 的当前稿
    feedback: str         # reviewer 的最新反馈
    review_rounds: int
    trace: list[str]


def researcher(state: TeamState) -> dict:
    """检索员：查已有文章 -> 提炼素材清单。上下文隔离：检索结果不直接进 writer。"""
    hits = corpus.search(state["topic"], top_k=3)
    raw = "\n\n".join(f"《{h['title']}》(相关度{h['score']})\n{h['content']}" for h in hits)
    response = get_chat_model(temperature=0).invoke([
        SystemMessage(content="你是内容调研员。把检索到的文章整理成素材清单："
                              "每篇列出可引用的要点（保留具体数字与命令），并指出与新主题的关联。"),
        HumanMessage(content=f"新文章主题：{state['topic']}\n\n检索结果：\n{raw}"),
    ])
    _track("researcher", response)
    return {"materials": response.content,
            "trace": state["trace"] + [f"researcher: 检索 {len(hits)} 篇并提炼素材"]}


def writer(state: TeamState) -> dict:
    """撰稿人：只看素材与反馈，不看检索原文 —— prompt 显著比单 Agent 版简单。"""
    user = f"主题：{state['topic']}\n\n素材清单：\n{state['materials']}"
    if state["feedback"]:
        user += f"\n\n上一稿：\n{state['draft']}\n\n评审反馈（必须逐条解决）：\n{state['feedback']}"
    response = get_chat_model(temperature=0.4).invoke([
        SystemMessage(content="你是技术博客撰稿人。输出两部分：「## 大纲」（3-5 个小节，"
                              "每节一句话说明写什么）和「## 开头草稿」（150字左右，要引用素材"
                              "里的具体事实）。基于素材写作，不要编造素材之外的数据。"),
        HumanMessage(content=user),
    ])
    _track("writer", response)
    action = "根据反馈重写" if state["feedback"] else "完成初稿"
    return {"draft": response.content, "trace": state["trace"] + [f"writer: {action}"]}


class Review(BaseModel):
    score: int = Field(ge=1, le=10, description="综合评分：结构、是否引用素材事实、可读性")
    approved: bool = Field(description="8 分及以上才算通过")
    feedback: str = Field(description="不通过时给出具体可执行的修改意见；通过则留空")


def reviewer(state: TeamState) -> Command[Literal["writer", "__end__"]]:
    """评审员：结构化输出 + 打回上限 —— Evaluator 回路的生产形态。"""
    response = get_chat_model(temperature=0).with_structured_output(Review, include_raw=True).invoke([
        SystemMessage(content="你是严格的技术编辑。评审标准：大纲结构是否合理递进、"
                              "草稿是否引用了素材中的具体事实（数字/命令）、语言是否啰嗦。"),
        HumanMessage(content=f"主题：{state['topic']}\n\n素材：\n{state['materials']}\n\n"
                             f"待评审稿：\n{state['draft']}"),
    ])
    _track("reviewer", response["raw"])
    review: Review = response["parsed"]
    rounds = state["review_rounds"] + 1

    if review.approved or rounds >= MAX_REVIEW_ROUNDS:
        verdict = f"评分 {review.score}/10，" + ("通过" if review.approved else f"达到打回上限({MAX_REVIEW_ROUNDS})放行")
        return Command(goto=END, update={
            "review_rounds": rounds, "trace": state["trace"] + [f"reviewer: {verdict}"]})

    return Command(goto="writer", update={
        "review_rounds": rounds, "feedback": review.feedback,
        "trace": state["trace"] + [f"reviewer: 评分 {review.score}/10，打回（第 {rounds} 轮）"]})


def build_team():
    builder = StateGraph(TeamState)
    builder.add_node("researcher", researcher)
    builder.add_node("writer", writer)
    builder.add_node("reviewer", reviewer)
    builder.add_edge(START, "researcher")
    builder.add_edge("researcher", "writer")   # 固定边：流程确定的部分用 Pipeline
    builder.add_edge("writer", "reviewer")
    # reviewer -> writer / END 由 Command 动态决定：确定性用边，决策点用 Command
    return builder.compile()


def run_team(topic: str) -> dict:
    reset_cost()
    start = time.perf_counter()
    result = build_team().invoke({
        "topic": topic, "materials": "", "draft": "", "feedback": "",
        "review_rounds": 0, "trace": [],
    })
    return {
        "draft": result["draft"], "trace": result["trace"],
        "seconds": round(time.perf_counter() - start, 1),
        "tokens": total_tokens(), "cost": {k: dict(v) for k, v in COST.items()},
    }


# ============================================================
# 单 Agent 基线：同任务、同工具，一个 LLM 全包
# ============================================================

@tool
def search_posts(query: str) -> str:
    """检索博客已有文章，返回最相关的 3 篇的标题与内容。"""
    hits = corpus.search(query, top_k=3)
    return "\n\n".join(f"《{h['title']}》\n{h['content']}" for h in hits)


SINGLE_PROMPT = (
    "你是技术博客写作助手。先用 search_posts 检索已有文章找素材，然后输出"
    "「## 大纲」（3-5 个小节，每节一句话说明）和「## 开头草稿」（150字左右，"
    "引用检索到的具体事实），并自己检查一遍质量后再输出最终版。"
)


def run_single(topic: str) -> dict:
    reset_cost()
    start = time.perf_counter()
    model = get_chat_model(temperature=0.4).bind_tools([search_posts])
    messages = [SystemMessage(content=SINGLE_PROMPT),
                HumanMessage(content=f"新文章主题：{topic}")]

    draft = ""
    for _ in range(4):   # 简单 ReAct 循环
        response = model.invoke(messages)
        _track("single_agent", response)
        messages.append(response)
        if not response.tool_calls:
            draft = response.content
            break
        for tc in response.tool_calls:
            output = search_posts.invoke(tc["args"])
            messages.append(ToolMessage(content=str(output), tool_call_id=tc["id"]))

    return {
        "draft": draft, "trace": ["single_agent: 检索+写作+自查一体完成"],
        "seconds": round(time.perf_counter() - start, 1),
        "tokens": total_tokens(), "cost": {k: dict(v) for k, v in COST.items()},
    }


# ============================================================
# 公平裁判：同一个评审 prompt 给两份产出打分
# ============================================================

def judge(topic: str, draft: str) -> Review:
    response = get_chat_model(temperature=0).with_structured_output(Review).invoke([
        SystemMessage(content="你是严格的技术编辑。评审标准：大纲结构是否合理递进、"
                              "草稿是否引用了具体事实（数字/命令）、语言是否啰嗦。"),
        HumanMessage(content=f"主题：{topic}\n\n待评审稿：\n{draft}"),
    ])
    return response
