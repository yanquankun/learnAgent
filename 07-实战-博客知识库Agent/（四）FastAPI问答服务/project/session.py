"""
session.py —— 会话管理（内存版滑动窗口）

03 模块四章手写过完整的两级记忆（窗口+摘要），这里取够用的子集：
每个 sessionId 保留最近 MAX_TURNS 轮对话。第六章升级 LangGraph 后
会换成 SQLite checkpointer（跨进程持久），本版先保证 API 可用。
"""

from collections import defaultdict

MAX_TURNS = 4   # 保留最近 4 轮（8 条消息）

_sessions: dict[str, list[dict]] = defaultdict(list)


def get_history(session_id: str) -> list[dict]:
    return list(_sessions[session_id])


def append_turn(session_id: str, question: str, answer: str) -> None:
    history = _sessions[session_id]
    history.append({"role": "user", "content": question})
    history.append({"role": "assistant", "content": answer})
    # 滑动窗口：只留最近 MAX_TURNS 轮
    del history[: max(0, len(history) - MAX_TURNS * 2)]
