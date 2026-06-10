"""
chunker.py —— 文档切片（Chunking）

为什么不能整篇文章直接做 Embedding？
  1. 语义稀释：一篇讲 5 个主题的文章，向量是 5 个主题的「平均值」，
     哪个主题都搜不准
  2. 上下文浪费：检索命中后要把内容塞给 LLM，整篇塞会浪费大量 token
  3. 定位粒度：用户问的往往是文章里「某一小节」的内容

切片的核心权衡：
  切得太大 -> 语义稀释、检索不准
  切得太小 -> 上下文残缺、模型拿到的信息不完整

本文件实现两种策略：
  策略 A：固定大小 + 重叠（最通用的兜底策略）
  策略 B：按 markdown 标题切分（结构化文档的首选），内部再用策略 A 兜底
"""

import re
from dataclasses import dataclass, field

from loader import Article


@dataclass
class Chunk:
    """一个文本切片 + 它的元数据。

    metadata 的设计原则：检索命中一个 chunk 后，必须能回答——
      「它来自哪篇文章？」(article_id / title)
      「在文章的哪个位置？」(heading_path / chunk_index)
    这是后面做「来源引用」和「推荐文章链接」的基础。
    """

    article_id: str
    title: str
    content: str                 # 切片的正文文本（拿去做 embedding 的就是它）
    chunk_index: int             # 本文内的序号
    heading_path: list[str] = field(default_factory=list)  # 标题路径，如 ["迁移背景"]
    tags: list[str] = field(default_factory=list)


def split_by_size(text: str, chunk_size: int = 400, overlap: int = 80) -> list[str]:
    """策略 A：固定大小切片 + 重叠（overlap）。

    chunk_size：每片的目标字符数。中文场景 300~500 字符比较常用
                （bge-small 模型的输入上限是 512 token，不要超过它）。
    overlap   ：相邻两片的重叠字符数。重叠的意义：防止一句完整的话
                恰好被切断在两片的边界上，导致两片都「断章取义」。

    实现细节：优先在句号/换行等自然边界断开，避免把句子拦腰切断。
    """
    if len(text) <= chunk_size:
        return [text] if text.strip() else []

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))

        # 尝试把切点回退到最近的句子边界（。！？或换行）
        if end < len(text):
            boundary = max(
                text.rfind("。", start, end),
                text.rfind("！", start, end),
                text.rfind("？", start, end),
                text.rfind("\n", start, end),
            )
            # 边界至少要超过片段中点，否则切出来的片太小，宁可硬切
            if boundary > start + chunk_size // 2:
                end = boundary + 1

        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)

        if end >= len(text):
            break
        # 下一片的起点向前回退 overlap 个字符，形成重叠区
        start = end - overlap

    return chunks


def split_markdown_by_heading(article: Article) -> list[tuple[list[str], str]]:
    """策略 B 的第一步：按 markdown 标题（## / ###）把文章切成小节。

    返回 [(标题路径, 小节正文), ...]，例如：
        (["三个迁移大坑", "坑一：CommonJS 依赖处理"], "老项目里有不少...")

    保留「标题路径」非常重要：它既是定位信息（告诉用户答案在哪一节），
    也会拼进切片文本里参与 embedding（标题本身就是高质量的语义信号）。
    """
    lines = article.content.splitlines()
    sections: list[tuple[list[str], str]] = []

    heading_stack: list[tuple[int, str]] = []  # [(级别, 标题文字)]
    buffer: list[str] = []

    def flush() -> None:
        """把缓冲区的正文连同当前标题路径存入结果。"""
        body = "\n".join(buffer).strip()
        if body:
            sections.append(([h for _, h in heading_stack], body))
        buffer.clear()

    for line in lines:
        m = re.match(r"^(#{1,4})\s+(.*)", line)
        if m:
            flush()  # 遇到新标题，先把上一节的内容保存
            level = len(m.group(1))
            # 弹出层级 >= 当前级别的标题，维持正确的嵌套路径
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, m.group(2).strip()))
        else:
            buffer.append(line)
    flush()  # 别忘了最后一节

    return sections


def chunk_article(article: Article, chunk_size: int = 400, overlap: int = 80) -> list[Chunk]:
    """策略 B（完整版）：按标题切小节，超长的小节再用固定大小切片兜底。

    每个切片的文本最终形如：
        "webpack 迁移 Vite 实录 > 三个迁移大坑 > 坑一\n老项目里有不少..."
    把「标题 + 标题路径」拼进正文一起 embedding，可以显著提升检索质量
    ——因为用户的提问往往和标题的表述更接近。
    """
    chunks: list[Chunk] = []
    index = 0

    for heading_path, body in split_markdown_by_heading(article):
        # 小节仍然超长时，用策略 A 再切
        for piece in split_by_size(body, chunk_size, overlap):
            # 把标题上下文拼接进切片文本（参与 embedding）
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
