"""
user_memory.py —— 用户长期记忆（08 模块二章管线的生产落地版）

选型结论（详见 08-记忆系统（三）章）：不引入 LangMem/Mem0 等新依赖，
直接复用本项目已有的 Qdrant —— 新开一个 collection 存用户记忆，
记忆条目与博客切片彻底分库，互不污染。

完整链路：
    对话结束 -> 后台线程 extract_and_store（抽取 + 整合）-> Qdrant
    下次提问 -> recall 注入 generate/chitchat 节点 -> 个性化回答
    全部写操作记入 SQLite memory_events 表（可审计、可排错）

阈值沿用 08 模块二章的实测校准值（bge-small-zh-v1.5），换模型须重测。
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field
from qdrant_client import models

import config
import db
from embedder import EMBEDDING_DIM, embed_one
from vector_store import get_client

COLLECTION = config.USER_MEMORY_COLLECTION
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："

DUP_THRESHOLD = 0.95       # 近重复 -> 跳过
RELATED_THRESHOLD = 0.85   # 同主题近邻 -> LLM 判定冲突/互补
RECALL_THRESHOLD = 0.45    # 召回下限：低于它宁可不注入（防无关记忆污染回答）

# 观测埋点（第七章起 observability 才存在；第六章静默跳过）
try:
    from observability import MEMORY_EVENTS, MEMORY_RECALLS
except ImportError:
    MEMORY_EVENTS = MEMORY_RECALLS = None


def ensure_collection() -> None:
    client = get_client()
    if not client.collection_exists(COLLECTION):
        client.create_collection(
            collection_name=COLLECTION,
            vectors_config=models.VectorParams(
                size=EMBEDDING_DIM, distance=models.Distance.COSINE
            ),
        )


def _user_filter(user_id: str) -> models.Filter:
    """所有读写都必须带 user_id 过滤 —— 记忆串台是长期记忆的第一事故源。"""
    return models.Filter(must=[
        models.FieldCondition(key="user_id", match=models.MatchValue(value=user_id))
    ])


# ============================================================
# 抽取（LLM 结构化输出，规则与 08 模块二章一致）
# ============================================================

class Fact(BaseModel):
    text: str = Field(description="一句话、单一事实、主语统一为「读者」")
    kind: Literal["fact", "preference"] = Field(description="fact=客观事实 preference=偏好")


class ExtractResult(BaseModel):
    facts: list[Fact] = Field(description="值得长期记住的原子事实；没有就返回空列表")


EXTRACT_PROMPT = (
    "从博客问答对话中抽取关于提问读者的、值得长期记住的信息（技术背景/正在做的事/偏好）。\n"
    "规则：每条原子化（一句话一个事实）；只记长期有效的；闲聊和一次性问题不记；"
    "不记隐私（姓名之外的个人身份信息）；主语统一为「读者」。"
)


class ConflictDecision(BaseModel):
    relation: Literal["conflict", "complement"] = Field(
        description="conflict=矛盾（新的取代旧的）；complement=互补（都保留）"
    )


def extract_and_store(user_id: str, transcript: str) -> dict:
    """后台任务入口：抽取 -> 逐条整合入库。返回统计（测试与日志用）。"""
    from langchain_core.messages import HumanMessage, SystemMessage

    from lc_client import get_chat_model

    ensure_collection()
    model = get_chat_model(temperature=0)
    result = model.with_structured_output(ExtractResult).invoke(
        [SystemMessage(content=EXTRACT_PROMPT), HumanMessage(content=transcript)]
    )

    stats = {"added": 0, "updated": 0, "skipped": 0}
    client = get_client()
    for fact in result.facts:
        vector = embed_one(fact.text).tolist()
        neighbors = client.query_points(
            collection_name=COLLECTION, query=vector,
            query_filter=_user_filter(user_id), limit=1,
        ).points
        top = neighbors[0] if neighbors else None

        if top and top.score >= DUP_THRESHOLD:
            stats["skipped"] += 1
            _audit(user_id, "skip", fact.text)
            continue

        point_id = str(uuid.uuid4())
        if top and top.score >= RELATED_THRESHOLD:
            decision = model.with_structured_output(ConflictDecision).invoke([
                SystemMessage(content="判断两条关于同一读者的记忆是矛盾还是互补。"),
                HumanMessage(content=f"旧记忆：{top.payload['text']}\n新事实：{fact.text}"),
            ])
            if decision.relation == "conflict":
                point_id = str(top.id)   # 覆盖旧点 —— 更新而非追加，防新旧打架
                stats["updated"] += 1
                _audit(user_id, "update", f"{top.payload['text']} -> {fact.text}")
            else:
                stats["added"] += 1
                _audit(user_id, "add", fact.text)
        else:
            stats["added"] += 1
            _audit(user_id, "add", fact.text)

        client.upsert(collection_name=COLLECTION, points=[
            models.PointStruct(id=point_id, vector=vector, payload={
                "user_id": user_id, "text": fact.text, "kind": fact.kind,
                "created_at": datetime.now().isoformat(timespec="seconds"),
            })
        ])
    return stats


# ============================================================
# 召回与查询
# ============================================================

def recall(user_id: str, query: str, top_k: int = 3) -> list[str]:
    """按语义召回该用户的记忆（带阈值，宁缺毋滥）。"""
    client = get_client()
    if not client.collection_exists(COLLECTION):
        return []
    points = client.query_points(
        collection_name=COLLECTION,
        query=embed_one(QUERY_PREFIX + query).tolist(),
        query_filter=_user_filter(user_id), limit=top_k,
    ).points
    memories = [p.payload["text"] for p in points if p.score >= RECALL_THRESHOLD]
    if MEMORY_RECALLS is not None and memories:
        MEMORY_RECALLS.inc(len(memories))
    return memories


def list_memories(user_id: str) -> list[dict]:
    """调试端点用：列出该用户的全部记忆。"""
    client = get_client()
    if not client.collection_exists(COLLECTION):
        return []
    points, _ = client.scroll(
        collection_name=COLLECTION, scroll_filter=_user_filter(user_id), limit=100
    )
    return [
        {"text": p.payload["text"], "kind": p.payload["kind"],
         "created_at": p.payload["created_at"]}
        for p in points
    ]


def _audit(user_id: str, op: str, text: str) -> None:
    db.record_memory_event(user_id, op, text)
    if MEMORY_EVENTS is not None:
        MEMORY_EVENTS.labels(op=op).inc()
