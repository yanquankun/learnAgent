"""
pipeline.py —— 记忆写入与维护的核心管线

四个环节：
    extract      从对话里抽取「原子事实」（LLM 结构化输出）
    consolidate  入库前与已有记忆比对：重复跳过 / 冲突更新 / 新事实追加
    decay        按时间衰减记忆权重（旧偏好自然让位给新偏好）
    inject       检索 top-k 注入上下文（而不是全量倾倒）

设计原则：
    1. 原子化 —— 一条记忆一个事实，是检索准确率的根基
    2. 入库必经整合 —— 不整合的记忆库会变成「重复+互相矛盾」的垃圾场
    3. 没配 LLM Key 时自动降级：抽取用内置示例、冲突判定用相似度启发式，
       保证全部演示离线可跑（降级点都有注释标注）
"""

import math
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

from langgraph.store.memory import InMemoryStore
from pydantic import BaseModel, Field

from embedder import EMBEDDING_DIM, embed_texts

# 整合阈值：与最近邻记忆的相似度落在哪个区间，决定怎么处理。
# 这两个值不是拍脑袋来的，是用真实句对实测校准的（bge-small-zh-v1.5）：
#   「构建工具是webpack」vs「构建工具是Vite」（真冲突对）   = 0.921
#   「构建工具是webpack」vs「部署在阿里云」（无关事实对）    = 0.674
#   其余无关事实对全部 < 0.70
# 换 embedding 模型必须重新校准 —— 不同模型的分数分布差异很大
DUP_THRESHOLD = 0.95       # 高于它：几乎同一句话，直接跳过
RELATED_THRESHOLD = 0.85   # 高于它：同主题近邻，需判定「冲突更新」还是「补充新增」
HALF_LIFE_DAYS = 90        # 记忆权重半衰期：90 天后权重减半


def has_llm() -> bool:
    key = os.getenv("LLM_API_KEY", "")
    return bool(key) and "请替换" not in key


def make_store() -> InMemoryStore:
    def embed_fn(texts: list[str]) -> list[list[float]]:
        return embed_texts(texts).tolist()

    return InMemoryStore(index={"embed": embed_fn, "dims": EMBEDDING_DIM, "fields": ["text"]})


# ============================================================
# 1. 抽取：对话 -> 原子事实
# ============================================================

class Fact(BaseModel):
    """一条原子事实。"""

    text: str = Field(description="一句话、单一事实、含主语，如：用户的构建工具是 Vite")
    kind: Literal["fact", "preference", "episode"] = Field(
        description="fact=客观事实 preference=偏好 episode=带时间的经历"
    )


class ExtractResult(BaseModel):
    facts: list[Fact] = Field(description="值得长期记住的原子事实列表；闲聊寒暄不算")


EXTRACT_PROMPT = (
    "从下面的对话中抽取关于用户的、值得长期记住的事实。规则：\n"
    "1. 每条必须是「原子」的：一句话只说一件事，拆开能独立成立\n"
    "2. 只记长期有效的信息（身份/技术栈/偏好/项目情况），闲聊和一次性内容不记\n"
    "3. 不要记敏感隐私（住址/证件号/健康状况等）\n"
    "4. 用第三人称改写，主语统一为「用户」"
)

# 离线降级用的内置抽取结果（与下方示例对话对应）
CANNED_FACTS = [
    Fact(text="用户是资深前端工程师", kind="fact"),
    Fact(text="用户的个人博客构建工具是 webpack", kind="fact"),
    Fact(text="用户的博客部署在阿里云服务器上", kind="fact"),
    Fact(text="用户回答问题时喜欢先看结论再看代码", kind="preference"),
]


def extract_facts(transcript: str) -> list[Fact]:
    """从对话抽取原子事实；无 Key 时返回内置示例（降级点①）。"""
    if not has_llm():
        return CANNED_FACTS

    from langchain_core.messages import HumanMessage, SystemMessage

    from lc_client import get_chat_model

    model = get_chat_model(temperature=0).with_structured_output(ExtractResult)
    result = model.invoke(
        [SystemMessage(content=EXTRACT_PROMPT), HumanMessage(content=transcript)]
    )
    return result.facts


# ============================================================
# 2. 整合：入库前先跟旧记忆「对账」
# ============================================================

@dataclass
class ConsolidateLog:
    """整合过程的台账（演示与排错都靠它）。"""

    added: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    updated: list[tuple[str, str]] = field(default_factory=list)   # (旧, 新)


class ConflictDecision(BaseModel):
    relation: Literal["conflict", "complement"] = Field(
        description="conflict=新事实与旧记忆矛盾（应更新旧的）；complement=互补的两个事实（应都保留）"
    )


def judge_conflict(old: str, new: str) -> str:
    """判定同主题的新旧记忆是冲突还是互补。

    有 Key 用 LLM 判定；无 Key 用启发式（同主题即视为冲突更新，降级点②）。
    """
    if not has_llm():
        return "conflict"

    from langchain_core.messages import HumanMessage, SystemMessage

    from lc_client import get_chat_model

    model = get_chat_model(temperature=0).with_structured_output(ConflictDecision)
    decision = model.invoke(
        [
            SystemMessage(content="判断两条关于同一用户的记忆是矛盾（新的取代旧的）还是互补（都成立）。"),
            HumanMessage(content=f"旧记忆：{old}\n新事实：{new}"),
        ]
    )
    return decision.relation


def consolidate(store: InMemoryStore, ns: tuple, facts: list[Fact]) -> ConsolidateLog:
    """逐条入库：先查最近邻，再决定 跳过 / 更新 / 新增。"""
    log = ConsolidateLog()
    for fact in facts:
        neighbors = store.search(ns, query=fact.text, limit=1)
        top = neighbors[0] if neighbors else None

        if top and top.score >= DUP_THRESHOLD:
            log.skipped.append(fact.text)
            continue

        if top and top.score >= RELATED_THRESHOLD:
            relation = judge_conflict(top.value["text"], fact.text)
            if relation == "conflict":
                # 关键决策：更新（覆盖同一个 key）而不是追加 ——
                # 追加会让新旧两条都被检索到，Agent 各引用一半，回答自相矛盾
                store.put(ns, top.key, {
                    "text": fact.text, "kind": fact.kind,
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                })
                log.updated.append((top.value["text"], fact.text))
                continue

        store.put(ns, f"mem-{uuid.uuid4().hex[:8]}", {
            "text": fact.text, "kind": fact.kind,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })
        log.added.append(fact.text)
    return log


# ============================================================
# 3. 衰减与遗忘：旧记忆自然让位
# ============================================================

def decayed_score(score: float, created_at: str, now: datetime | None = None) -> float:
    """检索得分 × 时间衰减因子（半衰期 HALF_LIFE_DAYS 天）。

    比「到期硬删除」更平滑：旧记忆只是排名下降，
    在没有新记忆竞争时仍然可被召回。
    """
    now = now or datetime.now()
    age_days = max((now - datetime.fromisoformat(created_at)).days, 0)
    return score * math.pow(0.5, age_days / HALF_LIFE_DAYS)


def recall_with_decay(store: InMemoryStore, ns: tuple, query: str,
                      top_k: int = 3, now: datetime | None = None) -> list[dict]:
    """带时间衰减的记忆召回：先语义检索，再按衰减后得分重排。"""
    items = store.search(ns, query=query, limit=top_k * 2)
    ranked = sorted(
        (
            {
                "text": it.value["text"],
                "raw": round(it.score, 3),
                "final": round(decayed_score(it.score, it.value["created_at"], now), 3),
            }
            for it in items
        ),
        key=lambda x: x["final"],
        reverse=True,
    )
    return ranked[:top_k]


def days_ago(n: int) -> str:
    return (datetime.now() - timedelta(days=n)).isoformat(timespec="seconds")
