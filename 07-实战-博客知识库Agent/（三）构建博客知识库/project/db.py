"""
db.py —— SQLite：文章账本与索引任务记录

向量在 Qdrant，账目在 SQLite：
    articles       每篇文章的 content_hash（增量索引的判断依据）+ 索引状态
    indexing_jobs  每次索引任务的执行记录（第五章 Webhook 会大量使用）

为什么需要「账本」？向量库只存「现在有什么」，回答不了
「这篇文章上次索引时内容是什么版本」—— 没有账本就只能全量重建。
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "blog_agent.db"


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS articles (
            id           TEXT PRIMARY KEY,
            title        TEXT,
            source_path  TEXT,
            content_hash TEXT,
            commit_sha   TEXT DEFAULT '',
            chunk_count  INTEGER DEFAULT 0,
            indexed_at   TEXT,
            status       TEXT DEFAULT 'indexed'   -- indexed / deleted
        );
        CREATE TABLE IF NOT EXISTS indexing_jobs (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            trigger_type  TEXT,                    -- full / webhook / manual
            status        TEXT DEFAULT 'running',  -- running / success / failed
            changed_files TEXT DEFAULT '[]',
            error         TEXT DEFAULT '',
            started_at    TEXT,
            finished_at   TEXT
        );
        """
    )
    return conn


# ============================================================
# articles 账本
# ============================================================

def get_indexed_hash(conn: sqlite3.Connection, article_id: str) -> str | None:
    """查询某文章上次索引时的 content_hash；没索引过返回 None。"""
    row = conn.execute(
        "SELECT content_hash FROM articles WHERE id = ? AND status = 'indexed'",
        (article_id,),
    ).fetchone()
    return row["content_hash"] if row else None


def record_indexed(conn: sqlite3.Connection, article, chunk_count: int) -> None:
    with conn:
        conn.execute(
            "INSERT INTO articles (id, title, source_path, content_hash, commit_sha, chunk_count, indexed_at, status)"
            " VALUES (?,?,?,?,?,?,?,'indexed')"
            " ON CONFLICT(id) DO UPDATE SET title=excluded.title, source_path=excluded.source_path,"
            " content_hash=excluded.content_hash, commit_sha=excluded.commit_sha,"
            " chunk_count=excluded.chunk_count, indexed_at=excluded.indexed_at, status='indexed'",
            (
                article.id, article.title, article.source_path, article.hash,
                article.commit_sha, chunk_count, datetime.now().isoformat(timespec="seconds"),
            ),
        )


def record_deleted(conn: sqlite3.Connection, article_id: str) -> None:
    with conn:
        conn.execute("UPDATE articles SET status='deleted', chunk_count=0 WHERE id=?", (article_id,))


def find_article_by_path(conn: sqlite3.Connection, source_path: str) -> sqlite3.Row | None:
    """按文件路径反查文章（处理「删除文件」的 webhook 事件时用）。"""
    return conn.execute(
        "SELECT * FROM articles WHERE source_path = ?", (source_path,)
    ).fetchone()


# ============================================================
# indexing_jobs 任务记录
# ============================================================

def start_job(conn: sqlite3.Connection, trigger_type: str, changed_files: list[str]) -> int:
    with conn:
        cursor = conn.execute(
            "INSERT INTO indexing_jobs (trigger_type, changed_files, started_at) VALUES (?,?,?)",
            (trigger_type, json.dumps(changed_files, ensure_ascii=False),
             datetime.now().isoformat(timespec="seconds")),
        )
    return cursor.lastrowid


def finish_job(conn: sqlite3.Connection, job_id: int, error: str = "") -> None:
    with conn:
        conn.execute(
            "UPDATE indexing_jobs SET status=?, error=?, finished_at=? WHERE id=?",
            ("failed" if error else "success", error,
             datetime.now().isoformat(timespec="seconds"), job_id),
        )
