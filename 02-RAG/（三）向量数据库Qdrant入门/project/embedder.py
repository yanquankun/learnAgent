"""
embedder.py —— 文本向量化（Embedding）统一封装

本课程使用 FastEmbed 在「本地」生成向量：
  - 完全免费、离线运行、不消耗任何 API 额度
  - 底层是 ONNX 推理，不依赖庞大的 PyTorch，Mac 上运行轻快
  - 默认模型 BAAI/bge-small-zh-v1.5：北京智源开源的中文向量模型，
    体积约 90MB，输出 512 维向量，中文语义效果优秀

【第一次运行须知】
首次运行会自动从 HuggingFace 下载模型文件（约 90MB）。
国内网络建议配置镜像：仓库根目录 .env 中的 HF_ENDPOINT=https://hf-mirror.com
（本文件会自动向上查找并加载根目录的 .env）
"""

import os
from pathlib import Path

import numpy as np
from dotenv import load_dotenv


def _load_env() -> None:
    """向上逐级查找 .env 并加载（主要为了读取 HF_ENDPOINT 镜像配置）。"""
    current = Path(__file__).resolve().parent
    for directory in [current, *current.parents]:
        candidate = directory / ".env"
        if candidate.exists():
            load_dotenv(candidate)
            return


_load_env()

# 如果 .env 没配置，这里兜底设置国内镜像，保证模型能下载成功
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

# 注意：必须在设置好 HF_ENDPOINT 之后再 import fastembed
from fastembed import TextEmbedding  # noqa: E402

# 模型输出的向量维度（bge-small-zh-v1.5 固定是 512 维）
# 后面创建 Qdrant collection 时必须和这个值一致
EMBEDDING_DIM = 512

MODEL_NAME = "BAAI/bge-small-zh-v1.5"

# 模型加载比较耗时（秒级），用模块级变量缓存，整个进程只加载一次
_model: TextEmbedding | None = None


def get_model() -> TextEmbedding:
    """获取（懒加载的）Embedding 模型实例。"""
    global _model
    if _model is None:
        print(f"正在加载 Embedding 模型 {MODEL_NAME}（首次运行需下载约90MB）……")
        _model = TextEmbedding(model_name=MODEL_NAME)
        print("模型加载完成！")
    return _model


def embed_texts(texts: list[str]) -> np.ndarray:
    """把一批文本转成向量矩阵，形状为 (文本数量, 512)。"""
    model = get_model()
    # model.embed() 返回生成器，转成 numpy 矩阵方便后续计算
    return np.array(list(model.embed(texts)))


def embed_one(text: str) -> np.ndarray:
    """把单条文本转成一个 512 维向量。"""
    return embed_texts([text])[0]
