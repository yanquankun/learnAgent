"""
run_eval.py —— 自建评估集的自动化回归脚本

与 Ragas（上一章）互补的「便宜评估」：不调用任何 LLM、零成本、
秒级完成、结果确定 —— 适合每次改动后跑、适合挂 CI。

评估集格式（eval_dataset.jsonl，每行一个用例）：
    question          用户问题（建议收集真实提问，口语化的更有价值）
    expected_articles 应该命中的文章 id 列表
    must_contain      检索结果中必须出现的关键内容（抽查切片质量）
    should_refuse     这个问题是否应该拒答（知识库里没有）

输出三个核心指标：
    检索命中率（hit@K）   expected 文章出现在 top-K 里的比例
    推荐命中率（hit@1）   top-1 就是 expected 文章的比例
    拒答正确率            should_refuse 用例中 top_score 低于阈值的比例

低于阈值时 exit code = 1 —— 可直接接入 CI，「检索变差」直接挡住合并。

运行：
    uv run python run_eval.py            # 跑评估，生成 eval_report.md
    uv run python run_eval.py --strict   # 阈值更严格（演示「不达标退出码非0」）
"""

import json
import sys
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from embedder import embed_one
from indexer import COLLECTION, build_index, get_qdrant

console = Console()
BASE_DIR = Path(__file__).parent
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："

TOP_K = 4
REFUSE_THRESHOLD = 0.50   # top_score 低于它 = 应该拒答（02 模块五章的经验值）

# 回归红线：低于这些值说明这次改动让系统变差了
THRESHOLDS = {"hit_at_k": 0.8, "hit_at_1": 0.6, "refuse_acc": 0.65}
STRICT_THRESHOLDS = {"hit_at_k": 0.95, "hit_at_1": 0.9, "refuse_acc": 1.0}


def load_dataset() -> list[dict]:
    lines = (BASE_DIR / "eval_dataset.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def retrieve(client, question: str) -> list[dict]:
    vector = embed_one(QUERY_PREFIX + question)
    points = client.query_points(
        collection_name=COLLECTION, query=vector.tolist(), limit=TOP_K
    ).points
    return [
        {"article_id": p.payload["article_id"], "score": p.score, "content": p.payload["content"]}
        for p in points
    ]


def evaluate(client, cases: list[dict]) -> dict:
    """逐用例评估，返回汇总结果与明细。"""
    details = []
    for case in cases:
        hits = retrieve(client, case["question"])
        top_ids = [h["article_id"] for h in hits]
        top_score = hits[0]["score"] if hits else 0.0
        all_text = "\n".join(h["content"] for h in hits)

        if case["should_refuse"]:
            # 拒答用例：检索分数足够低 = 系统能正确说「不知道」
            passed = top_score < REFUSE_THRESHOLD
            detail = f"top_score={top_score:.3f}（阈值{REFUSE_THRESHOLD}）"
        else:
            hit_k = any(a in top_ids for a in case["expected_articles"])
            hit_1 = top_ids[:1] == case["expected_articles"][:1] or (
                bool(top_ids) and top_ids[0] in case["expected_articles"]
            )
            missing = [kw for kw in case["must_contain"] if kw not in all_text]
            passed = hit_k and not missing
            detail = f"top1={top_ids[0] if top_ids else '无'}"
            if missing:
                detail += f"，缺关键词:{missing}"
            details_extra = {"hit_k": hit_k, "hit_1": hit_1}

        details.append(
            {
                "case": case,
                "passed": passed,
                "detail": detail,
                **(details_extra if not case["should_refuse"] else {}),
            }
        )

    normal = [d for d in details if not d["case"]["should_refuse"]]
    refuse = [d for d in details if d["case"]["should_refuse"]]
    summary = {
        "hit_at_k": sum(d["hit_k"] for d in normal) / len(normal) if normal else 1.0,
        "hit_at_1": sum(d["hit_1"] for d in normal) / len(normal) if normal else 1.0,
        "refuse_acc": sum(d["passed"] for d in refuse) / len(refuse) if refuse else 1.0,
    }
    return {"summary": summary, "details": details}


def write_report(result: dict, thresholds: dict, all_pass: bool) -> Path:
    """输出 markdown 报告 —— 给人看的版本（CI 里可作为构件存档）。"""
    s = result["summary"]
    lines = [
        "# 检索回归评估报告",
        f"\n生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"\n结论：{'✅ 全部达标' if all_pass else '❌ 低于阈值，本次改动让检索变差了'}",
        "\n| 指标 | 得分 | 阈值 | 结果 |",
        "| --- | --- | --- | --- |",
    ]
    names = {"hit_at_k": f"检索命中率 hit@{TOP_K}", "hit_at_1": "推荐命中率 hit@1", "refuse_acc": "拒答正确率"}
    for key, name in names.items():
        ok = s[key] >= thresholds[key]
        lines.append(f"| {name} | {s[key]:.0%} | {thresholds[key]:.0%} | {'✅' if ok else '❌'} |")

    lines.append("\n## 用例明细\n\n| 问题 | 通过 | 说明 |\n| --- | --- | --- |")
    for d in result["details"]:
        mark = "✅" if d["passed"] else "❌"
        lines.append(f"| {d['case']['question']} | {mark} | {d['detail']} |")

    report_path = BASE_DIR / "eval_report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def main() -> None:
    thresholds = STRICT_THRESHOLDS if "--strict" in sys.argv else THRESHOLDS

    client = get_qdrant()
    if not client.collection_exists(COLLECTION):
        console.print("[bold]首次运行，构建索引……[/bold]")
        build_index(client)

    cases = load_dataset()
    console.print(f"加载评估集：{len(cases)} 个用例，开始评估……\n")
    result = evaluate(client, cases)

    table = Table(title="评估结果")
    for col in ("问题", "类型", "通过", "说明"):
        table.add_column(col)
    for d in result["details"]:
        kind = "拒答" if d["case"]["should_refuse"] else "检索"
        mark = "[green]✅[/green]" if d["passed"] else "[red]❌[/red]"
        table.add_row(d["case"]["question"][:22], kind, mark, d["detail"])
    console.print(table)

    s = result["summary"]
    all_pass = all(s[k] >= thresholds[k] for k in thresholds)
    console.print(
        f"\n检索命中率 hit@{TOP_K}：{s['hit_at_k']:.0%}（阈值 {thresholds['hit_at_k']:.0%}）"
        f"\n推荐命中率 hit@1：{s['hit_at_1']:.0%}（阈值 {thresholds['hit_at_1']:.0%}）"
        f"\n拒答正确率：{s['refuse_acc']:.0%}（阈值 {thresholds['refuse_acc']:.0%}）"
    )

    report = write_report(result, thresholds, all_pass)
    console.print(f"\n报告已写入：{report.name}")

    if not all_pass:
        console.print("[bold red]低于阈值，exit 1（CI 会拦下这次改动）[/bold red]")
        sys.exit(1)
    console.print("[bold green]全部达标，exit 0[/bold green]")


if __name__ == "__main__":
    main()
