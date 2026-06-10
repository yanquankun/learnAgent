"""
models.py —— 统一的文章数据模型

不管文章来自本地目录还是 GitHub、是 md 还是 json/js，
进入系统后都长成同一个 Article —— 这是第一章设计的「统一货币」。
"""

import hashlib
from dataclasses import dataclass, field


def content_hash(text: str) -> str:
    """内容指纹：增量索引的核心。

    内容不变 -> hash 不变 -> 跳过重新索引（省 embedding 钱、省时间）。
    用 sha256 截断到 16 位：碰撞概率对本场景完全可忽略。
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


@dataclass
class RepoFile:
    """仓库后端返回的原始文件。"""

    path: str          # 仓库内路径，如 posts/react-useeffect.md
    content: str       # 文件原文


@dataclass
class Article:
    """解析后的标准文章。"""

    id: str                          # 文章唯一 id（取文件名，如 react-useeffect）
    title: str
    content: str                     # 纯正文（已剥离 frontmatter / 代码结构）
    source_path: str                 # 来源文件路径
    tags: list[str] = field(default_factory=list)
    commit_sha: str = ""             # GitHub 后端填充；本地后端为空
    hash: str = ""                   # content_hash(content)，解析时自动计算

    def __post_init__(self) -> None:
        if not self.hash:
            self.hash = content_hash(self.content)
