"""One-click benchmark must work whatever the number of models. Run:  python tests/any_count_test.py

Uses offline mock models, so it needs no network or key. For 1, 2 and 6 models (plus one model
that cannot connect) it checks that the run finishes, that the judging mechanism fits the count,
that no model ever judges its own answer, and that
scores and routing agree with the leaderboard.
"""
from __future__ import annotations

import os
import sys
import tempfile
from collections import Counter
from pathlib import Path

os.environ["SLIDEARENA_HOME"] = tempfile.mkdtemp(prefix="sa_count_")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from slidearena import benchmark, config  # noqa: E402

FAILED = []


def check(cond, msg):
    print(("PASS  " if cond else "FAIL  ") + msg)
    if not cond:
        FAILED.append(msg)


def mock(i: int) -> dict:
    return config.upsert_model({"id": f"m{i}", "name": f"模型{i}", "protocol": "mock", "model": "mock",
                                "mock_skill": {"default": 0.5 + 0.08 * i, "slowness": 0}})


models = [mock(i) for i in range(6)]
broken = config.upsert_model({"id": "broken", "name": "连不上", "protocol": "openai",
                              "base_url": "http://127.0.0.1:1/v1", "model": "x", "api_key": "k"})
quiet = lambda msg: None  # noqa: E731
dims = ["text", "layout"]

for n, expect in ((1, "none"), (2, "anchored"), (6, "anchored")):
    ids = [m["id"] for m in models[:n]] + [broken["id"]]
    plan = benchmark.plan(ids, dims=dims)
    check(plan["models"] == n + 1 and plan["lines"], f"{n} 个模型：开测前给出测试计划")
    r = benchmark.run(ids, progress=quiet, dims=dims)
    check(sorted(r["scores"]) == sorted(ids[:n]) and [x["id"] for x in r["excluded"]] == ["broken"],
          f"{n} 个模型：一键跑完，连不上的模型自动排除")
    modes = r["judging"]["modes"]
    log = r["judging"]["log"]
    check(modes.get("text") == expect and modes.get("layout") == expect, f"{n} 个模型：评审方式为 {expect}")
    if expect == "none":
        check(not log and r["scores"]["m0"]["dims"]["text"]["rank"] == "only", "1 个模型：只按规则评分，不标第一")
        continue
    check(all(x["judge"] != x["model"] for x in log), f"{n} 个模型：没有模型评自己的答案")
    per_model = Counter(x["model"] for x in log)
    check(len(per_model) == n and len(set(per_model.values())) == 1,
          f"{n} 个模型：每个模型的每份大纲和排版都对比了参考答案 {dict(per_model)}")
    load = Counter(x["judge"] for x in log)
    check(max(load.values()) - min(load.values()) <= 1, f"{n} 个模型：评审工作量平摊 {dict(load)}")
    for dim in ("text", "layout"):
        chosen = benchmark.route(dim, models[:n])["id"]
        check(r["scores"][chosen]["dims"][dim]["rank"] in ("leader", "tied"),
              f"{n} 个模型：做 PPT 时「{dim}」交给的模型在排行榜上不是“落后”")

# a model's score does not depend on who else is in the run (same answers, same judge verdicts)
config.upsert_model({"id": "judge", "name": "裁判", "protocol": "mock", "model": "mock",
                     "mock_skill": {"default": 0.7, "slowness": 0}})
with_strong = benchmark.run(["m0", "m5"], judge_ids=["judge"], progress=quiet, dims=dims)["scores"]["m0"]["dims"]
with_weak = benchmark.run(["m0", "m1"], judge_ids=["judge"], progress=quiet, dims=dims)["scores"]["m0"]["dims"]
check(all(with_strong[d]["score"] == with_weak[d]["score"] for d in dims),
      f"同一模型和强对手、弱对手同场，分数相同 {[with_strong[d]['score'] for d in dims]}")

print("\n全部通过" if not FAILED else f"\n{len(FAILED)} 项失败")
sys.exit(1 if FAILED else 0)
