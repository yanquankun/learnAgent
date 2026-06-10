"""
memory.py —— Agent 的记忆管理

LLM 没有记忆（02 模块五章验证过），「记忆」= 每次请求重发历史。
但历史会无限增长，带来三个问题：token 费用上涨、响应变慢、
最终撑爆上下文窗口。所以需要「记忆管理」。

本文件实现两级策略（也是业界聊天产品的主流做法）：

    第一级：滑动窗口 —— 保留最近的对话原文（细节完整）
    第二级：摘要压缩 —— 更早的对话用 LLM 压缩成摘要（保留要点，丢弃细节）

         ┌────────────────────────────────────────────┐
         │ system prompt                              │
         │ [对话摘要]: 用户叫小明, 在重构博客, 用Vite…  │  <- 旧对话被压缩成这一条
         │ user: 那部署用什么?         ┐               │
         │ assistant: 推荐Docker…     │ 最近N轮原文    │
         │ user: 数据怎么备份?         ┘               │
         └────────────────────────────────────────────┘
"""

from llm_client import MODEL, get_client


def estimate_tokens(text: str) -> int:
    """粗略估算文本的 token 数。

    精确计数需要模型对应的分词器，但「裁剪历史」这种场景不需要精确，
    用经验公式足够：中文约 0.6 token/字，英文约 0.3 token/字符。
    这里统一按「字符数 x 0.6」从严估算（宁可多算，不要超窗）。
    """
    return int(len(text) * 0.6) + 4  # +4 是每条消息的固定开销


class ConversationMemory:
    """两级记忆管理器：滑动窗口 + 摘要压缩。"""

    def __init__(
        self,
        max_recent_tokens: int = 2000,   # 「最近对话原文」最多占的 token 预算
        summarize_threshold: int = 6,    # 被挤出窗口的消息攒够几条就触发摘要
    ):
        self.recent: list[dict] = []     # 最近的对话原文（滑动窗口）
        self.summary: str = ""           # 更早对话的摘要（持续更新）
        self.overflow: list[dict] = []   # 被挤出窗口、等待摘要的消息
        self.max_recent_tokens = max_recent_tokens
        self.summarize_threshold = summarize_threshold

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------
    def add(self, role: str, content: str) -> None:
        """追加一条消息，并在窗口超预算时把最旧的消息挤出去。"""
        self.recent.append({"role": role, "content": content})
        self._slide_window()
        self._maybe_summarize()

    def _slide_window(self) -> None:
        """滑动窗口：总 token 超预算时，从最旧的开始移入 overflow。"""
        while self._recent_tokens() > self.max_recent_tokens and len(self.recent) > 2:
            # 永远保留最近的消息，把最旧的挤出去
            self.overflow.append(self.recent.pop(0))

    def _recent_tokens(self) -> int:
        return sum(estimate_tokens(m["content"]) for m in self.recent)

    def _maybe_summarize(self) -> None:
        """overflow 攒够了就调用 LLM 做摘要压缩（合并进已有摘要）。"""
        if len(self.overflow) < self.summarize_threshold:
            return

        old_text = "\n".join(f"{m['role']}: {m['content']}" for m in self.overflow)
        prompt = (
            "请把下面的对话历史压缩成一段简洁的中文摘要（150字以内）。\n"
            "必须保留：用户的身份信息、明确的偏好、关键事实、未完成的任务。\n"
            f"已有摘要（合并进去）：{self.summary or '无'}\n"
            f"<history>\n{old_text}\n</history>"
        )
        client = get_client()
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        self.summary = response.choices[0].message.content.strip()
        self.overflow.clear()
        print(f"  （记忆压缩完成，摘要更新为：{self.summary[:50]}……）")

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------
    def build_messages(self, system_prompt: str) -> list[dict]:
        """组装发给 API 的完整 messages：system + 摘要 + 最近原文。"""
        messages = [{"role": "system", "content": system_prompt}]
        if self.summary:
            # 摘要以 system 消息注入，模型会把它当作背景知识
            messages.append(
                {"role": "system", "content": f"[早前对话的摘要]\n{self.summary}"}
            )
        messages.extend(self.recent)
        return messages

    def stats(self) -> str:
        """返回当前记忆状态的统计信息（调试用）。"""
        return (
            f"窗口内 {len(self.recent)} 条消息（约 {self._recent_tokens()} token），"
            f"待压缩 {len(self.overflow)} 条，"
            f"摘要 {'有' if self.summary else '无'}"
        )

    def clear(self) -> None:
        self.recent.clear()
        self.overflow.clear()
        self.summary = ""
