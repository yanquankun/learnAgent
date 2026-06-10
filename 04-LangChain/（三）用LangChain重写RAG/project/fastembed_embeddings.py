"""
fastembed_embeddings.py —— 自己实现 LangChain 的 Embeddings 接口

本文件是本章最有教学价值的部分：LangChain 没有「开箱即用」地集成
我们想要的本地 FastEmbed 中文模型？没关系 —— 框架的扩展点就是接口。

LangChain 的 Embeddings 抽象只要求实现两个方法：
    embed_documents(texts) -> list[list[float]]   # 入库时：批量向量化文档
    embed_query(text)      -> list[float]         # 检索时：向量化单条查询

实现了它，我们的 FastEmbed 就能接入 LangChain 的任何向量库组件
（QdrantVectorStore、retriever……），享受整个生态。

【为什么区分 documents 和 query 两个方法？】
还记得 02 模块五章的「bge 查询指令前缀」吗 —— 很多向量模型对
「文档侧」和「查询侧」的处理方式不同。接口层面拆开，正是为了
让实现者有机会做这种差异化处理。我们这里就把它用上！
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.embeddings import Embeddings


def _load_env() -> None:
    current = Path(__file__).resolve().parent
    for directory in [current, *current.parents]:
        candidate = directory / ".env"
        if candidate.exists():
            load_dotenv(candidate)
            return


_load_env()
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

from fastembed import TextEmbedding  # noqa: E402（必须在设置镜像后 import）

EMBEDDING_DIM = 512
MODEL_NAME = "BAAI/bge-small-zh-v1.5"

# bge 中文模型官方建议的查询前缀（02 模块五章实验过）
QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："


class FastEmbedEmbeddings(Embeddings):
    """把本地 FastEmbed 模型包装成 LangChain 的 Embeddings 组件。"""

    def __init__(self) -> None:
        print(f"加载本地向量模型 {MODEL_NAME}（首次运行需下载约90MB）……")
        self._model = TextEmbedding(model_name=MODEL_NAME)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """文档侧：直接向量化（不加前缀）。"""
        return [vec.tolist() for vec in self._model.embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        """查询侧：加上 bge 官方查询前缀再向量化（白捡的检索质量）。"""
        vec = next(iter(self._model.embed([QUERY_INSTRUCTION + text])))
        return vec.tolist()
