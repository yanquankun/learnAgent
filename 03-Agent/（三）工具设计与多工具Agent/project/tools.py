"""
tools.py —— 工具注册表（Tool Registry）

上一章手写 tools schema 的痛点：
  1. JSON 写起来又长又容易错
  2. 函数改了参数，schema 忘了同步改 -> 线上诡异 bug

本文件实现一个小而美的解决方案：@tool 装饰器。
写一个普通 Python 函数（带类型注解和 docstring），schema 自动生成：

    @tool(param_desc={"expression": "数学表达式，如 '38*17+5'"})
    def calculate(expression: str) -> str:
        \"\"\"计算数学表达式的精确结果。\"\"\"
        ...

设计原则（这就是「工具设计」的核心功）：
  - 函数名 = 工具名：动词开头、见名知意（search_blog 好于 blog_tool）
  - docstring = 工具描述：写清楚「什么场景该用我」，模型靠它做选择
  - 类型注解 = 参数 schema：代码即文档，永不失同步
"""

import inspect
from typing import Callable

# Python 类型 -> JSON Schema 类型 的映射
_TYPE_MAP = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}

# 全局注册表：工具名 -> {func, schema}
REGISTRY: dict[str, dict] = {}


def tool(param_desc: dict[str, str] | None = None) -> Callable:
    """装饰器：把一个 Python 函数注册为 Agent 可用的工具。

    param_desc：每个参数的中文描述（会写进 schema，帮助模型理解参数）。
    """
    param_desc = param_desc or {}

    def decorator(func: Callable) -> Callable:
        # 1. 从 docstring 取工具描述（模型选工具时看的就是它）
        description = inspect.getdoc(func) or func.__name__

        # 2. 从函数签名 + 类型注解生成参数 schema
        properties = {}
        required = []
        for name, param in inspect.signature(func).parameters.items():
            annotation = param.annotation
            json_type = _TYPE_MAP.get(annotation, "string")  # 不认识的类型按字符串处理
            properties[name] = {
                "type": json_type,
                "description": param_desc.get(name, name),
            }
            # 没有默认值的参数 = 必填参数
            if param.default is inspect.Parameter.empty:
                required.append(name)

        # 3. 拼装 OpenAI 格式的 tools schema
        schema = {
            "type": "function",
            "function": {
                "name": func.__name__,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

        REGISTRY[func.__name__] = {"func": func, "schema": schema}
        return func  # 函数本身原样返回，依然可以正常直接调用

    return decorator


def get_schemas() -> list[dict]:
    """返回所有已注册工具的 schema 列表（直接传给 API 的 tools 参数）。"""
    return [item["schema"] for item in REGISTRY.values()]


def execute(name: str, arguments: dict) -> str:
    """按名字执行工具，并把所有异常转成「给模型看的错误信息」。

    这是 Agent 工程的关键设计：工具报错不应该让程序崩溃，
    而应该作为 Observation 告诉模型 ——「调用失败了，原因是 xxx」，
    模型有很强的自我纠正能力（换参数重试、换工具、或如实告知用户）。
    """
    if name not in REGISTRY:
        return f"错误：不存在名为 {name} 的工具。可用工具：{list(REGISTRY)}"
    try:
        result = REGISTRY[name]["func"](**arguments)
        return str(result)
    except Exception as e:  # noqa: BLE001 —— 故意兜住一切异常喂给模型
        return f"工具执行出错：{type(e).__name__}: {e}"
