"""
incremental.py —— 增量索引：处理一次 push 的文件变更

三种变更的处理策略（动态 RAG 的核心逻辑）：
    added     新文章：解析 -> 切片 -> 入库 -> 记账
    modified  修改：hash 没变跳过；变了则删旧向量重建（稳定 ID 保证覆盖干净）
    removed   删除：按账本反查 article_id -> 删向量 -> 账本标记 deleted

所有处理都包在一个 indexing_job 里 —— 出错也有记录可查。
"""

from pathlib import PurePosixPath

from rich.console import Console

import db
from chunker import chunk_article
from parser import SUPPORTED_SUFFIXES, parse_file
from repo_backend import get_backend
from vector_store import delete_article_points, ensure_collection, upsert_chunks

console = Console()


def process_changes(
    added: list[str], modified: list[str], removed: list[str], trigger: str = "webhook"
) -> dict:
    """处理一批文件变更，返回统计。由 Webhook 的后台任务调用。"""
    # 过滤掉不支持的文件（push 里可能混着图片、配置文件等）
    added = [p for p in added if PurePosixPath(p).suffix in SUPPORTED_SUFFIXES]
    modified = [p for p in modified if PurePosixPath(p).suffix in SUPPORTED_SUFFIXES]
    removed = [p for p in removed if PurePosixPath(p).suffix in SUPPORTED_SUFFIXES]

    conn = db.get_db()
    job_id = db.start_job(conn, trigger, added + modified + removed)
    stats = {"indexed": 0, "skipped": 0, "deleted": 0, "failed": 0}

    try:
        ensure_collection()
        backend = get_backend()

        # ---- 新增 + 修改：统一走「解析 -> hash 对比 -> 重建」----
        for path in added + modified:
            try:
                article = parse_file(backend.get_file(path))
                if article is None:
                    continue
                if db.get_indexed_hash(conn, article.id) == article.hash:
                    stats["skipped"] += 1
                    console.print(f"  [dim]内容未变，跳过：{path}[/dim]")
                    continue
                delete_article_points(article.id)        # 先删旧向量（防幽灵切片）
                chunks = chunk_article(article)
                upsert_chunks(chunks)
                db.record_indexed(conn, article, len(chunks))
                stats["indexed"] += 1
                console.print(f"  [green]已更新索引：{article.id}（{len(chunks)} 切片）[/green]")
            except Exception as exc:  # noqa: BLE001（单个文件失败不拖垮整批）
                stats["failed"] += 1
                console.print(f"  [red]处理失败 {path}：{exc}[/red]")

        # ---- 删除：文件没了，只能靠账本的 source_path 反查 ----
        for path in removed:
            row = db.find_article_by_path(conn, path)
            if row is None:
                console.print(f"  [dim]账本中无此文件，忽略删除：{path}[/dim]")
                continue
            delete_article_points(row["id"])
            db.record_deleted(conn, row["id"])
            stats["deleted"] += 1
            console.print(f"  [yellow]已删除：{row['id']}（向量与账本同步清理）[/yellow]")

        error = f"{stats['failed']} 个文件处理失败" if stats["failed"] else ""
        db.finish_job(conn, job_id, error=error)
        console.print(f"增量索引完成：{stats}")
        return stats
    except Exception as exc:
        db.finish_job(conn, job_id, error=str(exc))
        raise
    finally:
        conn.close()
