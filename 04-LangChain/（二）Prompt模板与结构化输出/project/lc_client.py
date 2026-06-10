"""
lc_client.py —— LangChain 版的模型客户端封装

对照 01 模块手写的 llm_client.py：
    手写版：OpenAI(api_key=..., base_url=...)  -> client.chat.completions.create(...)
    本版本：ChatDeepSeek(...)                   -> model.invoke(messages)

LangChain 的核心价值之一就是「模型抽象」：ChatDeepSeek / ChatOpenAI /
ChatTongyi 等所有模型类都实现同一套接口（invoke / stream / batch），
上层代码完全不用关心底层是哪家模型 —— 切换服务商只换这一个文件。

注意：我们显式传入根目录 .env 里的 LLM_API_KEY，
而不是依赖 langchain-deepseek 默认读取的 DEEPSEEK_API_KEY 环境变量，
保持整套课程「一个 .env 管所有章节」的约定。
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek


def _load_env() -> None:
    """向上逐级查找 .env 并加载（与 01 模块的 llm_client.py 完全一致）。"""
    current = Path(__file__).resolve().parent
    for directory in [current, *current.parents]:
        candidate = directory / ".env"
        if candidate.exists():
            load_dotenv(candidate)
            return


_load_env()

API_KEY = os.getenv("LLM_API_KEY", "")
MODEL_NAME = os.getenv("LLM_MODEL", "deepseek-chat")


def get_chat_model(temperature: float = 0.3) -> ChatDeepSeek:
    """创建 LangChain 的 ChatDeepSeek 模型实例。

    没配 Key 时给出友好提示（沿用全课程的约定）。
    """
    if not API_KEY or "请替换" in API_KEY:
        print("=" * 60)
        print("【环境未配置】没有找到可用的 LLM_API_KEY！")
        print("请在仓库根目录：cp .env.example .env 并填入 DeepSeek API Key")
        print("Key 申请地址：https://platform.deepseek.com/api_keys")
        print("=" * 60)
        sys.exit(1)

    return ChatDeepSeek(
        model=MODEL_NAME,
        api_key=API_KEY,       # 显式传入，不依赖 DEEPSEEK_API_KEY 环境变量
        temperature=temperature,
        max_retries=2,         # 网络抖动自动重试（手写版需要自己实现的能力之一）
    )


if __name__ == "__main__":
    # 环境自检
    model = get_chat_model()
    reply = model.invoke("请回复：LangChain 环境配置成功！")
    print(f"模型回复：{reply.content}")
