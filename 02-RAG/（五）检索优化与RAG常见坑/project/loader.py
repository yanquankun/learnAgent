"""
loader.py —— 博客文章加载与解析器

目标：把三种不同格式的文章文件（.md / .json / .js），统一解析成
标准的 Article 数据结构。「先统一数据模型，再做后续处理」是数据
工程的基本功 —— 后面的切片、向量化、入库都只面对 Article，
不再关心原始格式。

这正是你真实博客仓库的场景：文章以 md/json/js 三种格式存在 GitHub 仓库里。
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Article:
    """统一的文章数据模型（实战项目中它会扩展出 url、commit_sha 等字段）。"""

    id: str                      # 文章唯一标识，用文件名（slug）充当
    title: str                   # 标题
    content: str                 # 正文（统一为 markdown 格式的纯文本）
    source_path: str             # 来源文件路径，排查问题时能追溯到原始文件
    file_type: str               # markdown / json / javascript
    tags: list[str] = field(default_factory=list)
    created_at: str = ""


def parse_markdown(path: Path) -> Article:
    """解析 .md 文件：frontmatter 元数据 + markdown 正文。

    frontmatter 是文章开头两条 '---' 之间的元数据区，例如：
        ---
        title: React useEffect 详解
        tags: [react, hooks]
        ---
    这里手写一个极简解析器（只支持 key: value 和 [a, b] 数组），
    目的是让你看清原理。生产代码可以用 python-frontmatter 库。
    """
    text = path.read_text(encoding="utf-8")

    meta: dict = {}
    body = text
    # 匹配开头的 --- ... --- 区块（re.S 让 . 能匹配换行）
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if match:
        body = text[match.end():]  # frontmatter 之后才是正文
        for line in match.group(1).splitlines():
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            key, value = key.strip(), value.strip()
            if value.startswith("[") and value.endswith("]"):
                # 解析 [react, hooks] 这种简单数组
                meta[key] = [item.strip() for item in value[1:-1].split(",")]
            else:
                meta[key] = value

    return Article(
        id=meta.get("slug", path.stem),
        title=meta.get("title", path.stem),
        content=body.strip(),
        source_path=str(path),
        file_type="markdown",
        tags=meta.get("tags", []),
        created_at=str(meta.get("createdAt", "")),
    )


def parse_json(path: Path) -> Article:
    """解析 .json 文件：sections 数组拼接成 markdown 正文。

    JSON 格式的文章把内容存在 sections 数组里，每个 section 有
    heading 和 content。我们把它「还原」成 markdown（## 标题 + 段落），
    这样后续的切片逻辑就可以和 markdown 文章共用一套。
    """
    data = json.loads(path.read_text(encoding="utf-8"))

    parts = []
    for section in data.get("sections", []):
        parts.append(f"## {section['heading']}\n\n{section['content']}")
    content = "\n\n".join(parts)

    return Article(
        id=data.get("slug", path.stem),
        title=data["title"],
        content=content,
        source_path=str(path),
        file_type="json",
        tags=data.get("tags", []),
        created_at=data.get("createdAt", ""),
    )


def parse_js(path: Path) -> Article:
    """解析 .js 文件：用正则从 module.exports 对象里提取字段。

    在 Python 里没法直接执行 JS，常见做法有两种：
      1. 用正则提取所需字段（本章用这种，简单够用）
      2. 起一个 Node 子进程执行 JS 后输出 JSON（实战模块的可选优化）

    我们约定 js 文章的 content 放在模板字符串（反引号）里，
    title/slug 等元数据是普通字符串字面量。
    """
    text = path.read_text(encoding="utf-8")

    def extract_str(key: str) -> str:
        """提取 key: "value" 形式的字符串字段。"""
        m = re.search(rf'{key}\s*:\s*["\'](.+?)["\']', text)
        return m.group(1) if m else ""

    # tags: ["a", "b"] -> 提取数组里所有被引号包裹的元素
    tags_match = re.search(r"tags\s*:\s*\[(.*?)\]", text, re.S)
    tags = re.findall(r'["\'](.+?)["\']', tags_match.group(1)) if tags_match else []

    # content 在反引号模板字符串中
    content_match = re.search(r"content\s*:\s*`(.*?)`", text, re.S)
    content = content_match.group(1).strip() if content_match else ""

    return Article(
        id=extract_str("slug") or path.stem,
        title=extract_str("title") or path.stem,
        content=content,
        source_path=str(path),
        file_type="javascript",
        tags=tags,
        created_at=extract_str("createdAt"),
    )


# 扩展名 -> 解析函数 的分发表。以后支持新格式只需在这里加一行
PARSERS = {
    ".md": parse_markdown,
    ".json": parse_json,
    ".js": parse_js,
}


def load_articles(data_dir: str | Path) -> list[Article]:
    """加载目录下所有支持格式的文章，返回统一的 Article 列表。"""
    data_path = Path(data_dir)
    articles = []
    # sorted 保证加载顺序稳定（不同操作系统遍历顺序可能不同）
    for path in sorted(data_path.iterdir()):
        parser = PARSERS.get(path.suffix)
        if parser is None:
            continue  # 跳过不认识的文件类型
        articles.append(parser(path))
    return articles
