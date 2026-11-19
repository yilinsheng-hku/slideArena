"""Command line entry:  slidearena [serve|add|list|test|bench|make|demo]"""
from __future__ import annotations

import argparse
import getpass
import sys

from . import __version__, benchmark, config, deck, llm, server


def _pick_preset() -> dict:
    for i, p in enumerate(llm.PRESETS, 1):
        print(f"  {i:>2}. {p['label']}")
    while True:
        s = input("选择服务商编号：").strip()
        if s.isdigit() and 1 <= int(s) <= len(llm.PRESETS):
            return llm.PRESETS[int(s) - 1]


def cmd_add(a):
    p = _pick_preset()
    base = input(f"base_url [{p['base_url']}]：").strip() or p["base_url"]
    model = input(f"模型名称 [{p['model']}]：").strip() or p["model"]
    name = input(f"显示名称 [{model or p['label']}]：").strip() or model or p["label"]
    key = "" if p["protocol"] == "mock" else getpass.getpass("API Key（输入不显示，可写 env:变量名）：").strip()
    can_image = input("这个接口能生成图片吗？[y/N]：").strip().lower() == "y"
    m = config.upsert_model({"name": name, "protocol": p["protocol"], "base_url": base, "model": model,
                             "api_key": key, "can_image": can_image})
    print(f"已保存 {m['name']}（id={m['id']}），测试连接…")
    print(benchmark.ping(m))


def cmd_list(a):
    ms = config.list_models()
    if not ms:
        print("还没有模型。运行 slidearena add 或 slidearena demo")
    prof = config.load("profiles.json", {})
    for m in ms:
        s = prof.get(m["id"], {})
        scores = "  ".join(f"{benchmark.DIMENSIONS[d]}={s[d]:.0f}" for d in benchmark.DIMENSIONS
                           if isinstance(s.get(d), (int, float)))
        print(f"{m['id']:<14} {m['name']:<24} {m.get('model',''):<24} {scores}")


def cmd_test(a):
    for m in config.list_models():
        print(m["name"], benchmark.ping(m))


def _w(s: str) -> int:
    """Display width: CJK characters take two columns."""
    return sum(2 if ord(ch) > 0x2E7F else 1 for ch in s)


def _pad(s: str, n: int) -> str:
    return s + " " * max(1, n - _w(s))


def print_board(r: dict) -> None:
    names = {m["id"]: m["name"] for m in r["models"]}
    dims = [d for d in benchmark.DIMENSIONS if any(d in row["dims"] for row in r["scores"].values())]
    width = max(12, *(_w(n) for n in names.values())) + 2
    print("\n" + _pad("模型", width) + "".join(_pad(benchmark.DIMENSIONS[d], 16) for d in dims)
          + _pad("中位耗时", 10) + _pad("token/次", 10) + "失败")
    for mid, row in r["scores"].items():
        cells = []
        for d in dims:
            x = row["dims"].get(d)
            if not x:
                cells.append(_pad("-", 16))
                continue
            mark = {"leader": "*", "tied": "~", "behind": " ", "only": " "}.get(x.get("rank"), " ")
            ci = f"[{x['lo']:.0f}-{x['hi']:.0f}]" if "lo" in x and x["lo"] != x["hi"] else ""
            cells.append(_pad(f"{mark}{x['score']:.0f} {ci}", 16))
        print(_pad(names[mid], width) + "".join(cells)
              + _pad(f"{row['median_latency'] or '-'}s", 10) + _pad(str(row["tokens_per_call"]), 10) + str(row["errors"])
              + (f"（另有 {row['skipped']} 题因限流未计分）" if row.get("skipped") else ""))
    for x in r.get("excluded") or []:
        print(_pad(x["name"], width) + f"连接失败，未参加测试：{x['error'][:80]}")
    if len(r["scores"]) == 1:
        print("\n只测了 1 个模型：以上是相对题库的绝对分，没有排名和两两评审。   [a-b] 90% 置信区间")
    else:
        print("\n* 该项第一   ~ 与第一的差距在统计误差内（视为并列）   [a-b] 90% 置信区间")
    pw = r.get("pairwise", {})
    if pw.get("judged"):
        by = pw.get("by_dim") or {"text": pw["judged"]}
        parts = [f"{'大纲' if d == 'text' else '排版截图'} {n} 组" for d, n in by.items() if n]
        mutual = any(m in ("mutual", "mixed") for m in (pw.get("modes") or {}).values())
        print(f"两两评审：{'，'.join(parts)}（每组正反各问一次，计入该项 25%"
              f"{'；没有第三方裁判的组由双方互评' if mutual else ''}）")
    case_stats = r.get("case_stats", [])
    if case_stats:
        print(f"共 {r.get('question_count', len(case_stats))} 道题，其中 {sum(1 for c in case_stats if c.get('saturated'))} 道饱和。")
        print("注：数据图表类题目对顶级模型区分度有限，所有模型均满分时排版和大纲的两两评审承担主要区分功能。")


def cmd_bench(a):
    ids = a.models or [m["id"] for m in config.list_models()]
    if not ids:
        print("还没有模型。运行 slidearena add 或 slidearena demo")
        return 1
    opts = dict(repeats=a.repeats, pairwise=not a.no_judge, dims=a.only, visual=not a.no_visual)
    for line in benchmark.plan(ids, **opts)["lines"]:
        print("· " + line)
    try:
        r = benchmark.run(ids, **opts)
    except ValueError as e:
        print(e)
        return 1
    print_board(r)
    for d in (a.only or ("text", "chart", "layout")):
        if d == "image":
            continue
        print(f"做 PPT 时「{benchmark.DIMENSIONS[d]}」会交给：{benchmark.explain_route(d)}")


def cmd_selftest(a):
    bad = 0
    for cid, s in benchmark.selftest():
        print(f"{'PASS' if s == 100 else 'FAIL'}  {cid}  参考答案得分 {s}")
        bad += s != 100
    print("评分器自检通过" if not bad else f"有 {bad} 道题的参考答案没拿满分，评分器有问题")
    return 1 if bad else 0


def cmd_make(a):
    r = deck.build(a.brief, a.slides)
    print(r)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="slidearena", description="测一测你的模型谁最会做 PPT，再让它们分工合作")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("serve", help="打开网页界面（默认）")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-browser", action="store_true")
    sub.add_parser("add", help="交互式添加一个模型")
    sub.add_parser("list", help="列出模型和分数")
    sub.add_parser("test", help="测试所有模型连接")
    b = sub.add_parser("bench", help="运行能力测试")
    b.add_argument("models", nargs="*", help="模型 id（默认全部）")
    b.add_argument("-r", "--repeats", type=int, default=1, help="每道题重复几次（模型输出有随机性，重复越多越准）")
    b.add_argument("--no-judge", action="store_true", help="跳过两两对比评审，只用规则评分")
    b.add_argument("--no-visual", action="store_true", help="跳过排版截图的视觉评审")
    b.add_argument("--only", nargs="+", choices=["text", "layout", "chart", "image"],
                   help="只测这些维度，例如 --only layout")
    sub.add_parser("selftest", help="评分器自检：所有参考答案必须拿满分")
    mk = sub.add_parser("make", help="按测试结果分工做一份 PPT")
    mk.add_argument("brief")
    mk.add_argument("-n", "--slides", type=int, default=6)
    sub.add_parser("demo", help="添加 3 个离线演示模型")
    a = ap.parse_args(argv)
    if a.cmd in (None, "serve"):
        server.serve(getattr(a, "port", 8765), not getattr(a, "no_browser", False))
    elif a.cmd == "demo":
        print(f"已添加 {server.add_demo_models()} 个演示模型")
    else:
        return {"add": cmd_add, "list": cmd_list, "test": cmd_test, "bench": cmd_bench, "make": cmd_make,
                "selftest": cmd_selftest}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
