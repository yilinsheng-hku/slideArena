"""Generate the README sample-results table from the latest local benchmark.

The script reads only ``~/.slidearena/benchmarks.json`` and never opens ``models.json``. Run
``python scripts/results_table.py --update-readme`` after a new benchmark to refresh both READMEs.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
USER_HOME = Path.home() / ".slidearena"
sys.path.insert(0, str(ROOT))


def _load() -> dict:
    path = USER_HOME / "benchmarks.json"
    history = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(history, list) or not history:
        raise RuntimeError("benchmarks.json 没有可用记录")
    # Model metadata is not needed for the report. Drop credential-like and
    # endpoint fields before anything can be rendered into a README.
    result = dict(history[-1])
    result["models"] = []
    for model in history[-1].get("models", []):
        result["models"].append(
            {
                key: value
                for key, value in model.items()
                if "api_key" not in key.lower() and key.lower() not in {"base_url", "url"}
            }
        )
    return result


def _speed_ranks(result: dict) -> dict[str, str]:
    scores = {mid: row.get("dims", {}).get("speed", {}).get("score")
              for mid, row in result.get("scores", {}).items()}
    scores = {mid: score for mid, score in scores.items() if score is not None}
    if not scores:
        return {}
    best = max(scores.values())
    winners = [score for score in scores.values() if score == best]
    return {mid: "tied" if len(winners) > 1 and score == best else
            "leader" if score == best else "behind"
            for mid, score in scores.items()}


def _mark(rank: str | None, english: bool) -> str:
    labels = {
        "leader": "leader" if english else "第一",
        "tied": "tied" if english else "并列",
        "behind": "behind" if english else "落后",
    }
    return labels.get(rank or "behind", "behind" if english else "落后")


def _cell(dim: dict | None, english: bool, rank: str | None = None) -> str:
    if not dim or dim.get("score") is None:
        return "—"
    score = float(dim["score"])
    return f"{score:.1f} ({_mark(rank or dim.get('rank'), english)})"


def render(result: dict, english: bool = False) -> str:
    speed_ranks = _speed_ranks(result)
    headers = ("Model", "Text", "Layout", "Charts", "Speed", "Median latency", "Tokens/call", "Failures") if english else (
        "模型", "文字", "排版", "数据图表", "速度", "中位耗时", "token/次", "失败数")
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for model in result.get("models", []):
        mid = model["id"]
        score = result.get("scores", {}).get(mid, {})
        dims = score.get("dims", {})
        row = [
            model.get("name", mid),
            _cell(dims.get("text"), english),
            _cell(dims.get("layout"), english),
            _cell(dims.get("chart"), english),
            _cell(dims.get("speed"), english, speed_ranks.get(mid)),
            f"{score.get('median_latency') or '—'}s",
            str(score.get("tokens_per_call") or "—"),
            str(score.get("errors", 0)),
        ]
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _metadata(result: dict, english: bool) -> str:
    pairwise = result.get("pairwise", {})
    by_dim = pairwise.get("by_dim", {})
    outline = by_dim.get("text", 0)
    layout = by_dim.get("layout", 0)
    if english:
        review = f"outline review enabled ({outline} groups); visual layout review enabled ({layout} groups)"
        return (f"Test date: {result.get('time', '—')}; task bank: {result.get('bank_version', '—')} "
                f"({result.get('question_count', '—')} tasks, {result.get('hard_count', '—')} hard); repeats per task: "
                f"{result.get('repeats', '—')}; {review}. Results represent this task bank on this day only.")
    review = f"大纲评审：开启（{outline} 组）；排版视觉评审：开启（{layout} 组）"
    return (f"测试日期：{result.get('time', '—')}；题库版本：{result.get('bank_version', '—')}；题库题数：{result.get('question_count', '—')}（难题 {result.get('hard_count', '—')} 道）；"
            f"每题重复次数：{result.get('repeats', '—')}；"
            f"{review}。结果只代表这套题库在这一天的表现。")


def _section(result: dict, english: bool) -> str:
    title = "Sample results" if english else "实测结果示例 / Sample results"
    return f"## {title}\n\n{render(result, english)}\n\n{_metadata(result, english)}"


def _replace(path: Path, marker: str, content: str) -> None:
    text = path.read_text(encoding="utf-8")
    begin = f"<!-- BEGIN {marker} -->"
    end = f"<!-- END {marker} -->"
    start = text.index(begin) + len(begin)
    finish = text.index(end, start)
    path.write_text(text[:start] + "\n" + content + "\n" + text[finish:], encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the latest benchmark table")
    parser.add_argument("--lang", choices=("zh", "en"), default="zh")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--update-readme", action="store_true")
    args = parser.parse_args()
    result = _load()
    output = _section(result, args.lang == "en")
    if args.output:
        args.output.write_text(output + "\n", encoding="utf-8")
    else:
        print(output)
    if args.update_readme:
        _replace(ROOT / "README.md", "SAMPLE_RESULTS_ZH", _section(result, False))
        _replace(ROOT / "README.en.md", "SAMPLE_RESULTS_EN", _section(result, True))
        print("已更新 README.md 和 README.en.md 的实测结果段落")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
