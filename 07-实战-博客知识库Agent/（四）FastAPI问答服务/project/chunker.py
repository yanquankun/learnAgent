"""
chunker.py —— 文档切片（02 模块的成熟实现，改用实战版 Article）

策略：按 markdown 标题切小节 + 超长小节用固定大小兜底 +
标题路径拼进切片正文参与 embedding。详细推导见 02 模块二章。
"""

import re
from dataclasses import dataclass, field

from models import Article


@dataclass
class Chunk:
    """一个文本切片 + 元数据（来源引用与推荐文章的基础）。"""

    article_id: str
    title: str
    content: str
    chunk_index: int
    heading_path: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


def split_by_size(text: str, chunk_size: int = 400, overlap: int = 80) -> list[str]:
    """固定大小切片 + 重叠，优先在句子边界断开。"""
    if len(text) <= chunk_size:
        return [text] if text.strip() else []

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            boundary = max(
                text.rfind("。", start, end),
                text.rfind("！", start, end),
                text.rfind("？", start, end),
                text.rfind("\n", start, end),
            )
            if boundary > start + chunk_size // 2:
                end = boundary + 1
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start = end - overlap
    return chunks


def split_markdown_by_heading(article: Article) -> list[tuple[list[str], str]]:
    """按 ##/### 标题切小节，返回 [(标题路径, 小节正文), ...]。"""
    sections: list[tuple[list[str], str]] = []
    heading_stack: list[tuple[int, str]] = []
    buffer: list[str] = []

    def flush() -> None:
        body = "\n".join(buffer).strip()
        if body:
            sections.append(([h for _, h in heading_stack], body))
        buffer.clear()

    for line in article.content.splitlines():
        m = re.match(r"^(#{1,4})\s+(.*)", line)
        if m:
            flush()
            level = len(m.group(1))
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, m.group(2).strip()))
        else:
            buffer.append(line)
    flush()
    return sections


def chunk_article(article: Article, chunk_size: int = 400, overlap: int = 80) -> list[Chunk]:
    """完整切片：标题小节 -> 超长兜底 -> 标题路径拼进正文。"""
    chunks: list[Chunk] = []
    index = 0
    for heading_path, body in split_markdown_by_heading(article):
        for piece in split_by_size(body, chunk_size, overlap):
            context_line = " > ".join([article.title, *heading_path])
            chunks.append(
                Chunk(
                    article_id=article.id,
                    title=article.title,
                    content=f"{context_line}\n{piece}",
                    chunk_index=index,
                    heading_path=heading_path,
                    tags=article.tags,
                )
            )
            index += 1
    return chunks
