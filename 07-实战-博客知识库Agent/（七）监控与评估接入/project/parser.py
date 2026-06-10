"""
parser.py —— 文章解析器（02 模块 loader.py 的实战升级版）

与学习版的两个区别：
    1. 输入从「文件路径」变成「RepoFile（路径+内容字符串）」——
       因为内容可能来自 GitHub API，本地根本没有这个文件
    2. 解析结果自动带上 content_hash（增量索引要用）

解析逻辑本身与 02 模块二章完全一致：md 的 frontmatter、
json 的 sections、js 的 module.exports 正则提取。
"""

import json
import re
from pathlib import PurePosixPath

from models import Article, RepoFile


def parse_markdown(file: RepoFile) -> Article:
    """md：frontmatter 元数据 + markdown 正文。"""
    text = file.content
    meta: dict = {}
    body = text
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if match:
        body = text[match.end():]
        for line in match.group(1).splitlines():
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            key, value = key.strip(), value.strip()
            if value.startswith("[") and value.endswith("]"):
                meta[key] = [item.strip() for item in value[1:-1].split(",")]
            else:
                meta[key] = value

    stem = PurePosixPath(file.path).stem
    return Article(
        id=meta.get("slug", stem),
        title=meta.get("title", stem),
        content=body.strip(),
        source_path=file.path,
        tags=meta.get("tags", []),
    )


def parse_json(file: RepoFile) -> Article:
    """json：sections 数组还原成 markdown（## 标题 + 段落）。"""
    data = json.loads(file.content)
    parts = [f"## {s['heading']}\n\n{s['content']}" for s in data.get("sections", [])]
    stem = PurePosixPath(file.path).stem
    return Article(
        id=data.get("slug", stem),
        title=data.get("title", stem),
        content="\n\n".join(parts),
        source_path=file.path,
        tags=data.get("tags", []),
    )


def parse_js(file: RepoFile) -> Article:
    """js：正则从 module.exports 提取字段（content 在反引号模板字符串里）。"""
    text = file.content

    def extract_str(key: str) -> str:
        m = re.search(rf'{key}\s*:\s*["\'](.+?)["\']', text)
        return m.group(1) if m else ""

    tags_match = re.search(r"tags\s*:\s*\[(.*?)\]", text, re.S)
    tags = re.findall(r'["\'](.+?)["\']', tags_match.group(1)) if tags_match else []
    content_match = re.search(r"content\s*:\s*`(.*?)`", text, re.S)
    content = content_match.group(1).strip() if content_match else ""

    stem = PurePosixPath(file.path).stem
    return Article(
        id=extract_str("slug") or stem,
        title=extract_str("title") or stem,
        content=content,
        source_path=file.path,
        tags=tags,
    )


PARSERS = {".md": parse_markdown, ".json": parse_json, ".js": parse_js}
SUPPORTED_SUFFIXES = set(PARSERS)


def parse_file(file: RepoFile) -> Article | None:
    """解析单个仓库文件；不支持的格式返回 None。"""
    parser = PARSERS.get(PurePosixPath(file.path).suffix)
    return parser(file) if parser else None
