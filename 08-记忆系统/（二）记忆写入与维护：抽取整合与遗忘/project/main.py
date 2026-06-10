"""
（二）记忆写入与维护：抽取、整合、冲突与遗忘

运行：uv run python main.py
（未配置 LLM_API_KEY 也能完整跑通：抽取与冲突判定自动降级，降级点见 pipeline.py）

四个演示：
    1. 原子化 vs 大杂烩 —— 同一批信息两种存法，检索准确率立见高下（离线）
    2. 对话 -> 原子事实抽取（LLM 结构化输出）
    3. 整合管线 —— 重复跳过 / 冲突更新（webpack→Vite）/ 新增
    4. 时间衰减 —— 90天前的旧偏好自然让位给上周的新偏好（离线）
"""

from datetime import datetime

from rich.console import Console
from rich.table import Table

from pipeline import (
    consolidate, days_ago, extract_facts, has_llm, make_store, recall_with_decay,
)

console = Console()


# ============================================================
# 演示 1：原子化是检索准确率的根基
# ============================================================

def demo_1_atomic_vs_blob() -> None:
    console.rule("[bold cyan]演示 1：原子化 vs 大杂烩")

    store = make_store()

    # 错误示范：把用户画像整段塞成一条记忆
    store.put(("blob", "facts"), "all", {"text": (
        "用户是资深前端工程师，主技术栈 React 和 TypeScript，"
        "个人博客用 webpack 构建、部署在阿里云，平时喜欢喝美式咖啡，"
        "回答问题时喜欢先看结论再看代码示例。"
    )})

    # 正确示范：拆成原子事实
    atoms = [
        "用户是资深前端工程师，主技术栈 React 和 TypeScript",
        "用户的个人博客用 webpack 构建",
        "用户的博客部署在阿里云服务器",
        "用户喜欢喝美式咖啡",
        "用户回答问题时喜欢先看结论再看代码示例",
    ]
    for i, text in enumerate(atoms):
        store.put(("atomic", "facts"), f"m{i}", {"text": text})

    query = "用户的博客是怎么构建和部署的？"
    console.print(f"[bold]查询：{query}[/bold]")
    blob = store.search(("blob", "facts"), query=query, limit=1)[0]
    console.print(f"  大杂烩版 top1 得分：{blob.score:.3f}（咖啡偏好稀释了构建部署的语义）")
    for r in store.search(("atomic", "facts"), query=query, limit=2):
        console.print(f"  原子化版：{r.score:.3f}  {r.value['text']}")
    console.print("[dim]结论：原子化让相关事实得分更高、且不夹带无关内容进上下文[/dim]\n")


# ============================================================
# 演示 2 + 3：抽取 -> 整合 的完整管线
# ============================================================

TRANSCRIPT_DAY1 = """
用户：你好！我是个资深前端，最近想给自己的博客加个 AI 问答。
助手：可以的，你的博客是什么技术栈？
用户：webpack 构建的老项目了，跑在我的阿里云服务器上。
助手：明白。回答你会希望什么风格？
用户：先给结论，再给代码，别铺垫一堆理论。今天天气真不错哈哈。
"""

TRANSCRIPT_DAY30 = """
用户：跟你说个事，我上个月把博客从 webpack 迁到 Vite 了，冷启动快太多了。
助手：恭喜！迁移顺利吗？
用户：还行，另外我最近开始学 Rust 了，纯属兴趣。
"""


def demo_2_and_3_pipeline() -> None:
    console.rule("[bold cyan]演示 2+3：对话 -> 抽取 -> 整合（含冲突更新）")
    mode = "LLM 抽取/判定" if has_llm() else "离线降级（内置示例+启发式）"
    console.print(f"[dim]当前模式：{mode}[/dim]\n")

    store = make_store()
    ns = ("user_mint", "memories")

    # ---- 第 1 天的对话：全部是新事实 ----
    facts = extract_facts(TRANSCRIPT_DAY1)
    console.print("[bold]Day 1 抽取结果：[/bold]")
    for f in facts:
        console.print(f"  [{f.kind}] {f.text}")
    log = consolidate(store, ns, facts)
    console.print(f"整合：新增 {len(log.added)} / 跳过 {len(log.skipped)} / 更新 {len(log.updated)}\n")

    # ---- 第 30 天的对话：webpack->Vite 是冲突，学 Rust 是新增 ----
    if has_llm():
        facts2 = extract_facts(TRANSCRIPT_DAY30)
    else:
        from pipeline import Fact
        facts2 = [
            Fact(text="用户的个人博客构建工具是 Vite", kind="fact"),
            Fact(text="用户正在学习 Rust", kind="fact"),
        ]
    console.print("[bold]Day 30 抽取结果：[/bold]")
    for f in facts2:
        console.print(f"  [{f.kind}] {f.text}")
    log2 = consolidate(store, ns, facts2)
    for old, new in log2.updated:
        console.print(f"  [yellow]冲突更新：[/yellow]「{old}」->「{new}」")
    for text in log2.added:
        console.print(f"  [green]新增：[/green]{text}")

    # ---- 验证：现在问构建工具，答案应该只有 Vite ----
    console.print("\n[bold]验证查询：用户的博客用什么构建？[/bold]")
    for r in store.search(ns, query="用户的博客用什么构建工具", limit=2):
        console.print(f"  {r.score:.3f}  {r.value['text']}")
    console.print("[dim]webpack 那条已被原地覆盖 —— 不会出现新旧打架[/dim]\n")


# ============================================================
# 演示 4：时间衰减 —— 旧记忆自然让位
# ============================================================

def demo_4_decay() -> None:
    console.rule("[bold cyan]演示 4：时间衰减（半衰期 90 天）")

    store = make_store()
    ns = ("user_mint", "preferences")
    # 两条语义相近但时间悬殊的偏好（模拟没做冲突整合的历史库存）
    store.put(ns, "old", {"text": "用户偏好深色主题的代码示例",
                          "created_at": days_ago(365)})
    store.put(ns, "new", {"text": "用户最近偏好浅色主题的代码示例",
                          "created_at": days_ago(7)})

    table = Table(title="查询：用户喜欢什么主题的代码示例？")
    for col in ("记忆", "原始得分", "衰减后"):
        table.add_column(col)
    for r in recall_with_decay(store, ns, "用户喜欢什么主题的代码示例", top_k=2,
                               now=datetime.now()):
        table.add_row(r["text"], str(r["raw"]), str(r["final"]))
    console.print(table)
    console.print("[dim]一年前的旧偏好原始得分可能更高，但衰减后让位给上周的新偏好。\n"
                  "衰减是冲突整合的「兜底网」：整合漏掉的旧记忆，随时间自然降权。[/dim]\n")


if __name__ == "__main__":
    demo_1_atomic_vs_blob()
    demo_2_and_3_pipeline()
    demo_4_decay()
