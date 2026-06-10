"""
index_cli.py —— 知识库索引 pipeline（命令行入口）

    uv run python index_cli.py                  # 智能索引：hash 没变的文章自动跳过
    uv run python index_cli.py --rebuild        # 全量重建（删 collection 重来）
    uv run python index_cli.py --search "问题"  # 检索自测
    uv run python index_cli.py --stats          # 查看账本统计

核心流程（增量靠 content_hash 账本）：
    仓库后端列文件 -> 解析 Article -> 对比账本 hash
        没变 -> 跳过（省 embedding 钱）
        变了/新文章 -> 删旧向量 -> 切片 -> 向量化 -> upsert -> 记账
"""

import sys

from rich.console import Console
from rich.table import Table

import db
from chunker import chunk_article
from parser import parse_file
from repo_backend import get_backend
from vector_store import (
    delete_article_points,
    drop_collection,
    ensure_collection,
    search,
    upsert_chunks,
)

console = Console()


def run_index(rebuild: bool = False) -> dict:
    """跑一次索引，返回统计：{indexed, skipped, total_chunks}。"""
    conn = db.get_db()
    job_id = db.start_job(conn, "full" if rebuild else "manual", [])

    try:
        if rebuild:
            console.print("[yellow]--rebuild：删除现有 collection，全量重建[/yellow]")
            drop_collection()
        ensure_collection()

        backend = get_backend()
        paths = backend.list_paths()
        console.print(f"仓库中发现 {len(paths)} 个文章文件")

        stats = {"indexed": 0, "skipped": 0, "total_chunks": 0}
        for path in paths:
            article = parse_file(backend.get_file(path))
            if article is None:
                continue

            # ---- 增量判断：hash 没变就跳过 ----
            if not rebuild and db.get_indexed_hash(conn, article.id) == article.hash:
                stats["skipped"] += 1
                console.print(f"  [dim]跳过（内容未变）：{article.id}[/dim]")
                continue

            # ---- 重建该文章：删旧向量 -> 切片 -> 入库 -> 记账 ----
            delete_article_points(article.id)
            chunks = chunk_article(article)
            upsert_chunks(chunks)
            db.record_indexed(conn, article, len(chunks))
            stats["indexed"] += 1
            stats["total_chunks"] += len(chunks)
            console.print(f"  [green]已索引：{article.id}（{len(chunks)} 个切片）[/green]")

        db.finish_job(conn, job_id)
        console.print(
            f"\n完成：索引 {stats['indexed']} 篇 / 跳过 {stats['skipped']} 篇"
            f" / 新增切片 {stats['total_chunks']} 个"
        )
        return stats
    except Exception as exc:
        db.finish_job(conn, job_id, error=str(exc))
        raise
    finally:
        conn.close()


def show_stats() -> None:
    conn = db.get_db()
    table = Table(title="articles 账本")
    for col in ("id", "hash", "切片数", "索引时间", "状态"):
        table.add_column(col)
    for r in conn.execute("SELECT * FROM articles ORDER BY id"):
        table.add_row(r["id"], r["content_hash"], str(r["chunk_count"]), r["indexed_at"], r["status"])
    console.print(table)

    jobs = Table(title="indexing_jobs 最近任务")
    for col in ("id", "触发", "状态", "开始", "结束"):
        jobs.add_column(col)
    for r in conn.execute("SELECT * FROM indexing_jobs ORDER BY id DESC LIMIT 5"):
        jobs.add_row(str(r["id"]), r["trigger_type"], r["status"], r["started_at"], r["finished_at"] or "-")
    console.print(jobs)
    conn.close()


def run_search(query: str) -> None:
    console.print(f"检索：[bold]{query}[/bold]")
    for hit in search(query):
        console.print(f"  score={hit['score']:.3f}  《{hit['title'][:24]}》 {' > '.join(hit['heading_path'])}")


if __name__ == "__main__":
    if "--search" in sys.argv:
        run_search(sys.argv[sys.argv.index("--search") + 1])
    elif "--stats" in sys.argv:
        show_stats()
    else:
        run_index(rebuild="--rebuild" in sys.argv)
