"""
config.py —— 项目配置（统一从根目录 .env 读取）

实战项目的所有可变配置都集中在这里，代码里不允许散落 os.getenv。
"""

import os
from pathlib import Path

from dotenv import load_dotenv


def _load_env() -> None:
    current = Path(__file__).resolve().parent
    for directory in [current, *current.parents]:
        candidate = directory / ".env"
        if candidate.exists():
            load_dotenv(candidate)
            return


_load_env()

BASE_DIR = Path(__file__).resolve().parent

# ---- 数据源：local（课程模拟仓库）/ github（你的真实仓库）----
BLOG_SOURCE = os.getenv("BLOG_SOURCE", "local")
LOCAL_REPO_DIR = Path(os.getenv("LOCAL_REPO_DIR", str(BASE_DIR / "mock_repo")))

# ---- GitHub 后端配置（BLOG_SOURCE=github 时生效）----
GITHUB_REPO = os.getenv("GITHUB_REPO", "")          # 例如 "yourname/blog-posts"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")        # 私有仓库需要；公开仓库可留空
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")

# ---- 博客 URL 规则：article_id 如何变成文章链接 ----
BLOG_URL_TEMPLATE = os.getenv("BLOG_URL_TEMPLATE", "https://blog.example.com/posts/{id}")

# ---- LLM ----
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")

# ---- 向量库（第三章起使用 Docker 服务端模式）----
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "blog_chunks")

# ---- 用户长期记忆（08 模块三章接入：与博客切片分库存储）----
USER_MEMORY_COLLECTION = os.getenv("USER_MEMORY_COLLECTION", "user_memories")

# ---- Webhook 与管理接口 ----
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")     # GitHub Webhook 签名密钥
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")           # /api/admin/* 的访问令牌

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
