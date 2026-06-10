"""
eval/run_eval.py —— 实战服务的检索回归评估（06 模块五章的接入版）

不调 LLM、零成本、秒级完成：每次改 chunker / 阈值 / 换 embedding 模型，
先跑它再上线。低于阈值 exit 1，可直接挂 CI 或部署前检查。

运行（项目根目录）：
    uv run python eval/run_eval.py            # 生成 eval/eval_report.md
    uv run python eval/run_eval.py --strict   # 上线前用严格阈值
"""

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))   # 引用项目根的模块

from rich.console import Console
from rich.table import Table

from rag import SCORE_THRESHOLD, TOP_K
from vector_store import search

console = Console()
EVAL_DIR = Path(__file__).parent

# 回归红线：低于这些值说明这次改动让系统变差了
THRESHOLDS = {"hit_at_k": 0.8, "hit_at_1": 0.6, "refuse_acc": 0.65}
STRICT_THRESHOLDS = {"hit_at_k": 0.9, "hit_at_1": 0.8, "refuse_acc": 1.0}


def load_dataset() -> list[dict]:
    lines = (EVAL_DIR / "eval_dataset.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def evaluate(cases: list[dict]) -> dict:
    details = []
    for case in cases:
        hits = search(case["question"], top_k=TOP_K)
        top_ids = [h["article_id"] for h in hits]
        top_score = hits[0]["score"] if hits else 0.0
        all_text = "\n".join(h["content"] for h in hits)

        extra = {}
        if case["should_refuse"]:
            # 拒答用例：top_score 低于服务的拒答阈值 = 系统会正确说「不知道」
            passed = top_score < SCORE_THRESHOLD
            detail = f"top_score={top_score:.3f}（阈值{SCORE_THRESHOLD}）"
        else:
            hit_k = any(a in top_ids for a in case["expected_articles"])
            hit_1 = bool(top_ids) and top_ids[0] in case["expected_articles"]
            missing = [kw for kw in case["must_contain"] if kw not in all_text]
            passed = hit_k and not missing
            detail = f"top1={top_ids[0] if top_ids else '无'}"
            if missing:
                detail += f"，缺关键词:{missing}"
            extra = {"hit_k": hit_k, "hit_1": hit_1}

        details.append({"case": case, "passed": passed, "detail": detail, **extra})

    normal = [d for d in details if not d["case"]["should_refuse"]]
    refuse = [d for d in details if d["case"]["should_refuse"]]
    summary = {
        "hit_at_k": sum(d["hit_k"] for d in normal) / len(normal) if normal else 1.0,
        "hit_at_1": sum(d["hit_1"] for d in normal) / len(normal) if normal else 1.0,
        "refuse_acc": sum(d["passed"] for d in refuse) / len(refuse) if refuse else 1.0,
    }
    return {"summary": summary, "details": details}


def write_report(result: dict, thresholds: dict, all_pass: bool) -> Path:
    s = result["summary"]
    lines = [
        "# 检索回归评估报告",
        f"\n生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"\n结论：{'✅ 全部达标' if all_pass else '❌ 低于阈值，本次改动让检索变差了'}",
        "\n| 指标 | 得分 | 阈值 | 结果 |",
        "| --- | --- | --- | --- |",
    ]
    names = {
        "hit_at_k": f"检索命中率 hit@{TOP_K}",
        "hit_at_1": "推荐命中率 hit@1",
        "refuse_acc": "拒答正确率",
    }
    for key, name in names.items():
        ok = s[key] >= thresholds[key]
        lines.append(f"| {name} | {s[key]:.0%} | {thresholds[key]:.0%} | {'✅' if ok else '❌'} |")

    lines.append("\n## 用例明细\n\n| 问题 | 通过 | 说明 |\n| --- | --- | --- |")
    for d in result["details"]:
        mark = "✅" if d["passed"] else "❌"
        lines.append(f"| {d['case']['question']} | {mark} | {d['detail']} |")

    report_path = EVAL_DIR / "eval_report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def main() -> None:
    thresholds = STRICT_THRESHOLDS if "--strict" in sys.argv else THRESHOLDS

    cases = load_dataset()
    console.print(f"加载评估集：{len(cases)} 个用例，开始评估……\n")
    result = evaluate(cases)

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
    console.print(f"\n报告已写入：eval/{report.name}")

    if not all_pass:
        console.print("[bold red]低于阈值，exit 1（CI 会拦下这次改动）[/bold red]")
        sys.exit(1)
    console.print("[bold green]全部达标，exit 0[/bold green]")


if __name__ == "__main__":
    main()
