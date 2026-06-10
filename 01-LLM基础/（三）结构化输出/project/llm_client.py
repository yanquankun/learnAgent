"""
llm_client.py —— LLM 客户端统一封装

这是整套课程中最基础的一个文件，后续几乎每一章的 project 里都会带上它
（或者它的增强版本）。它只做三件事：

1. 自动查找并加载 .env 配置文件（API Key 等敏感信息不写死在代码里）
2. 创建一个 OpenAI 兼容的客户端（DeepSeek 提供 OpenAI 兼容接口，
   所以我们直接用官方 openai SDK，以后换模型服务商只需改 .env）
3. 在 Key 没配置时给出清晰的中文提示，而不是抛出一堆看不懂的堆栈

【为什么用 OpenAI SDK 调 DeepSeek？】
OpenAI 的 Chat Completions API 已经成为行业事实标准，
DeepSeek / 通义千问 / Kimi / 月之暗面等几乎所有国产模型都提供兼容接口。
学会这一套，等于学会了调用市面上 95% 的大模型。
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


def _load_env() -> None:
    """从当前文件所在目录开始，逐级向上查找 .env 文件并加载。

    查找顺序示例：
        project/.env                  -> 章节内的本地配置（优先级最高，可选）
        （一）认识LLM与第一次API调用/.env
        01-LLM基础/.env
        learnAgent/.env               -> 仓库根目录的全局配置（推荐放这里）

    这样设计的好处：API Key 只需要在仓库根目录配置一次，
    所有章节的 project 都能自动读到，不用每章复制一遍。
    """
    current = Path(__file__).resolve().parent
    for directory in [current, *current.parents]:
        candidate = directory / ".env"
        if candidate.exists():
            load_dotenv(candidate)
            return


# 模块被 import 时就加载环境变量
_load_env()

# 从环境变量读取配置，os.getenv 的第二个参数是「读不到时的默认值」
API_KEY = os.getenv("LLM_API_KEY", "")
BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
MODEL = os.getenv("LLM_MODEL", "deepseek-chat")


def get_client() -> OpenAI:
    """创建并返回一个 OpenAI 兼容客户端。

    如果没有配置 API Key，打印友好的中文指引后退出程序，
    避免新手看到 AuthenticationError 堆栈时一头雾水。
    """
    if not API_KEY or "请替换" in API_KEY:
        print("=" * 60)
        print("【环境未配置】没有找到可用的 LLM_API_KEY！")
        print()
        print("请按以下步骤配置：")
        print("  1. 打开 https://platform.deepseek.com/api_keys 创建 API Key")
        print("  2. 在仓库根目录（learnAgent/）执行：cp .env.example .env")
        print("  3. 编辑 .env，把 LLM_API_KEY 的值替换成你自己的 Key")
        print("  4. 重新运行本脚本")
        print("=" * 60)
        sys.exit(1)

    # base_url 指向 DeepSeek 的 OpenAI 兼容接口
    # 如果以后想换其他服务商，改 .env 里的 LLM_BASE_URL 即可，这里不用动
    return OpenAI(api_key=API_KEY, base_url=BASE_URL)


if __name__ == "__main__":
    # 直接运行本文件 = 环境自检：能拿到客户端并成功调用，说明环境 OK
    client = get_client()
    print(f"客户端创建成功！base_url={BASE_URL}, model={MODEL}")
    print("正在发送测试请求……")
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": "请回复：环境配置成功！"}],
    )
    print(f"模型回复：{resp.choices[0].message.content}")
