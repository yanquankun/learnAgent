"""
lc_client.py —— LangChain 版模型客户端

与 llm_client.py（裸 OpenAI SDK）并存：LangGraph 节点内用 ChatDeepSeek
（消息对象 + 流式回调 + 结构化输出都更顺手），配置缺失时同样抛
LLMNotConfigured，由 API 层统一兜底。
"""

from langchain_deepseek import ChatDeepSeek

import config
from llm_client import LLMNotConfigured


def get_chat_model(temperature: float = 0.3) -> ChatDeepSeek:
    if not config.LLM_API_KEY or "请替换" in config.LLM_API_KEY:
        raise LLMNotConfigured(
            "LLM_API_KEY 未配置：请在仓库根目录 cp .env.example .env 并填入 DeepSeek API Key"
        )
    return ChatDeepSeek(
        model=config.LLM_MODEL,
        api_key=config.LLM_API_KEY,
        api_base=config.LLM_BASE_URL,
        temperature=temperature,
        max_retries=2,
    )
