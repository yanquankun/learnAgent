"""
repo_backend.py —— 数据源双后端（本章核心）

同一个抽象接口，两种实现：
    LocalRepoBackend  读本地目录（课程模拟仓库，零依赖可学习）
    GitHubBackend     调 GitHub REST API（你的真实文章仓库）

切换方式：根 .env 改一行 BLOG_SOURCE=local / github。
上层代码（解析、索引、问答）完全感知不到差异 —— 这就是
04 模块三章「面向接口编程」在自己项目里的应用。
"""

from pathlib import Path
from typing import Protocol

import httpx

import config
from models import RepoFile
from parser import SUPPORTED_SUFFIXES


class RepoBackend(Protocol):
    """仓库后端接口：上层只依赖这两个方法。"""

    def list_paths(self) -> list[str]:
        """列出仓库中所有受支持的文章文件路径。"""
        ...

    def get_file(self, path: str) -> RepoFile:
        """读取单个文件的内容。"""
        ...


class LocalRepoBackend:
    """本地目录后端：把一个目录当成「仓库」。

    除了学习用，它还有真实价值：在服务器上 git clone 你的仓库后，
    用本地后端定时 git pull 也是一种低配可用的同步方案。
    """

    def __init__(self, repo_dir: Path | None = None) -> None:
        self.repo_dir = Path(repo_dir or config.LOCAL_REPO_DIR)

    def list_paths(self) -> list[str]:
        return sorted(
            str(p.relative_to(self.repo_dir))
            for p in self.repo_dir.rglob("*")
            if p.is_file() and p.suffix in SUPPORTED_SUFFIXES
        )

    def get_file(self, path: str) -> RepoFile:
        content = (self.repo_dir / path).read_text(encoding="utf-8")
        return RepoFile(path=path, content=content)


class GitHubBackend:
    """GitHub REST API 后端。

    用到三个端点（第五章 Webhook 还会用到 compare）：
        GET /repos/{repo}/git/trees/{branch}?recursive=1   列出仓库文件树
        GET /repos/{repo}/contents/{path}                  读取文件内容
        GET /repos/{repo}/compare/{base}...{head}          比较两个 commit 的差异
    """

    API = "https://api.github.com"

    def __init__(self, repo: str = "", token: str = "", branch: str = "") -> None:
        self.repo = repo or config.GITHUB_REPO
        self.branch = branch or config.GITHUB_BRANCH
        if not self.repo:
            raise ValueError("BLOG_SOURCE=github 需要在 .env 配置 GITHUB_REPO（如 yourname/blog-posts）")
        headers = {"Accept": "application/vnd.github+json"}
        token = token or config.GITHUB_TOKEN
        if token:    # 公开仓库可不带 token（但有较低的频率限制）
            headers["Authorization"] = f"Bearer {token}"
        self._http = httpx.Client(base_url=self.API, headers=headers, timeout=20)

    def list_paths(self) -> list[str]:
        resp = self._http.get(f"/repos/{self.repo}/git/trees/{self.branch}", params={"recursive": "1"})
        resp.raise_for_status()
        return sorted(
            item["path"]
            for item in resp.json()["tree"]
            if item["type"] == "blob" and Path(item["path"]).suffix in SUPPORTED_SUFFIXES
        )

    def get_file(self, path: str) -> RepoFile:
        # raw 媒体类型直接返回文件原文，省去 base64 解码
        resp = self._http.get(
            f"/repos/{self.repo}/contents/{path}",
            params={"ref": self.branch},
            headers={"Accept": "application/vnd.github.raw+json"},
        )
        resp.raise_for_status()
        return RepoFile(path=path, content=resp.text)

    def compare(self, base: str, head: str) -> dict:
        """比较两个 commit，返回 {added/modified/removed 文件列表}（第五章用）。"""
        resp = self._http.get(f"/repos/{self.repo}/compare/{base}...{head}")
        resp.raise_for_status()
        changed = {"added": [], "modified": [], "removed": []}
        for f in resp.json()["files"]:
            status = {"added": "added", "modified": "modified", "removed": "removed",
                      "renamed": "modified", "changed": "modified"}.get(f["status"])
            if status and Path(f["filename"]).suffix in SUPPORTED_SUFFIXES:
                changed[status].append(f["filename"])
        return changed


def get_backend() -> RepoBackend:
    """按 .env 的 BLOG_SOURCE 返回对应后端 —— 上层唯一的入口。"""
    if config.BLOG_SOURCE == "github":
        return GitHubBackend()
    return LocalRepoBackend()
