"""
llm_client.py —— LLM 客户端（实战版，配置走 config.py）

注意：服务场景里不能像脚本那样 sys.exit ——
配置缺失时抛出专门的异常，由 API 层转成对前端友好的错误响应。
"""

from openai import OpenAI

import config


class LLMNotConfigured(RuntimeError):
    """LLM_API_KEY 未配置。"""


def get_client() -> OpenAI:
    if not config.LLM_API_KEY or "请替换" in config.LLM_API_KEY:
        raise LLMNotConfigured(
            "LLM_API_KEY 未配置：请在仓库根目录 cp .env.example .env 并填入 DeepSeek API Key"
        )
    return OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL)
