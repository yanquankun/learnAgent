"""
qa_logger.py —— 结构化日志 + qa_logs 落库

监控体系的第一块砖：让每一次问答「可记录、可查询、可回放」。

两件事：
    1. JSON 结构化日志：每条日志是一行 JSON（机器可解析），并贯穿 trace_id
    2. qa_logs 表（SQLite）：把问答全过程（问题/检索结果/回答/延迟/token）
       结构化落库 —— 这张表就是之后所有评估与优化的「原材料」

为什么是 JSON 日志而不是 print？
    print("检索到3条")        -> 人能看，机器难解析
    {"event":"retrieve",...}  -> 能进 ELK/Loki，能按字段过滤聚合
"""

import json
import logging
import sqlite3
import sys
import time
import uuid
from pathlib import Path

DB_PATH = Path(__file__).parent / "qa_logs.db"


# ============================================================
# 1) JSON 结构化日志
# ============================================================

class JsonFormatter(logging.Formatter):
    """把日志记录格式化成单行 JSON。

    约定：业务字段统一放在 record 的 extra["payload"] 里。
    """

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        entry.update(getattr(record, "payload", {}))
        return json.dumps(entry, ensure_ascii=False)


def get_logger() -> logging.Logger:
    """同时输出到控制台和 app.log 文件的 JSON logger。"""
    logger = logging.getLogger("qa")
    if logger.handlers:        # 防止重复添加 handler
        return logger
    logger.setLevel(logging.INFO)
    for handler in (
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(Path(__file__).parent / "app.log", encoding="utf-8"),
    ):
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    return logger


def log_event(event: str, trace_id: str, **fields) -> None:
    """记录一个结构化事件。所有事件都带 trace_id —— 同一次请求的
    所有日志靠它串起来（这是 02 章「链路追踪」思想的最朴素形态）。"""
    get_logger().info(event, extra={"payload": {"trace_id": trace_id, **fields}})


def new_trace_id() -> str:
    return uuid.uuid4().hex[:16]


# ============================================================
# 2) qa_logs 表（SQLite）
# ============================================================

def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS qa_logs (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            trace_id      TEXT NOT NULL,
            created_at    TEXT DEFAULT (datetime('now', 'localtime')),
            question      TEXT NOT NULL,
            answer        TEXT,
            retrieved     TEXT,      -- 检索结果 JSON：[{article_id,title,score}]
            top_score     REAL,      -- 最高检索分（监控「检索质量」的核心字段）
            latency_ms    INTEGER,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            model         TEXT
        )
        """
    )
    return conn


def save_qa_log(
    trace_id: str,
    question: str,
    answer: str,
    retrieved: list[dict],
    latency_ms: int,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    model: str = "",
) -> None:
    """一次问答的完整记录入库。"""
    conn = get_db()
    with conn:
        conn.execute(
            "INSERT INTO qa_logs (trace_id, question, answer, retrieved, top_score,"
            " latency_ms, prompt_tokens, completion_tokens, model)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (
                trace_id,
                question,
                answer,
                json.dumps(retrieved, ensure_ascii=False),
                retrieved[0]["score"] if retrieved else 0.0,
                latency_ms,
                prompt_tokens,
                completion_tokens,
                model,
            ),
        )
    conn.close()


def fetch_recent(limit: int = 10) -> list[sqlite3.Row]:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM qa_logs ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return rows


class Timer:
    """计时小工具：with Timer() as t: ... ; t.ms"""

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *args):
        self.ms = int((time.perf_counter() - self._start) * 1000)
