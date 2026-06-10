"""
corpus.py —— 博客文章语料与本地语义检索

researcher 的「知识库」：6 篇模拟博客文章（主题与 07 模块 mock_repo 一致），
用 FastEmbed 在内存里做语义检索 —— 不依赖 Qdrant，开箱即跑。
"""

import numpy as np

from embedder import embed_one, embed_texts

POSTS = [
    {
        "id": "docker-intro",
        "title": "Docker 入门：从镜像到容器",
        "content": "镜像是只读模板，容器是镜像的运行实例。常用命令：docker pull 拉取镜像、"
                   "docker run 启动容器、docker ps 查看运行中的容器。镜像分层存储，"
                   "上层修改不影响底层，多个镜像可共享基础层以节省磁盘。",
    },
    {
        "id": "docker-compose-deploy",
        "title": "用 Docker Compose 部署全栈应用",
        "content": "Compose 用一个 YAML 描述多容器应用：services 定义各服务，volumes 定义"
                   "数据卷，depends_on 声明启动顺序。数据库容器必须挂载卷持久化数据，"
                   "否则容器删除数据就没了。docker compose up -d 一键拉起全部服务。",
    },
    {
        "id": "dockerfile-best",
        "title": "Dockerfile 写法的十个最佳实践",
        "content": "多阶段构建能把构建依赖留在 builder 阶段，最终镜像只含运行时；"
                   "把变化最少的层（依赖安装）放前面以充分利用缓存；用非 root 用户运行；"
                   "用 .dockerignore 排除无关文件缩小构建上下文。",
    },
    {
        "id": "vite-migration",
        "title": "博客从 webpack 迁移到 Vite 实录",
        "content": "Vite 开发模式基于原生 ESM 按需编译，冷启动从 30 秒降到 1 秒内。"
                   "迁移要点：入口从配置文件改为 index.html、环境变量前缀改为 VITE_、"
                   "CommonJS 依赖需要预构建处理。生产构建用 Rollup，产物体积略小于 webpack。",
    },
    {
        "id": "typescript-tips",
        "title": "TypeScript 高级类型实用技巧",
        "content": "infer 在条件类型中提取类型变量，如 ReturnType 的实现；"
                   "模板字面量类型可以做字符串级别的类型校验；satisfies 运算符"
                   "既校验类型又保留字面量推断，配置对象场景特别好用。",
    },
    {
        "id": "python-env-uv",
        "title": "用 uv 管理 Python 项目环境",
        "content": "uv 是 Rust 写的 Python 包管理器，解析依赖比 pip 快 10-100 倍。"
                   "uv sync 按 lock 文件精确还原环境，uv add 添加依赖并自动更新锁文件，"
                   "uv run 在项目环境中执行命令，免去手动激活虚拟环境。",
    },
]

_vectors: np.ndarray | None = None


def _ensure_index() -> np.ndarray:
    global _vectors
    if _vectors is None:
        texts = [f"{p['title']}\n{p['content']}" for p in POSTS]
        vecs = embed_texts(texts)
        _vectors = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)
    return _vectors


def search(query: str, top_k: int = 3) -> list[dict]:
    """语义检索：返回 [{id, title, content, score}]。"""
    vectors = _ensure_index()
    q = embed_one(query)
    q = q / np.linalg.norm(q)
    scores = vectors @ q
    order = np.argsort(scores)[::-1][:top_k]
    return [{**POSTS[i], "score": round(float(scores[i]), 3)} for i in order]
