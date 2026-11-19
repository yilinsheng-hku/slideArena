"""One-click benchmark must work whatever the number of models. Run:  python tests/any_count_test.py

Uses offline mock models, so it needs no network or key. For 1, 2 and 6 models (plus one model
that cannot connect) it checks that the run finishes, that the judging mechanism fits the count,
and that no model ever judges its own answer.
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

for n, expect in ((1, None), (2, None), (6, "third_party")):
    ids = [m["id"] for m in models[:n]] + [broken["id"]]
    plan = benchmark.plan(ids, dims=dims)
    check(plan["models"] == n + 1 and plan["lines"], f"{n} 个模型：开测前给出测试计划")
    r = benchmark.run(ids, progress=quiet, dims=dims)
    check(sorted(r["scores"]) == sorted(ids[:n]) and [x["id"] for x in r["excluded"]] == ["broken"],
          f"{n} 个模型：一键跑完，连不上的模型自动排除")
    modes = r["pairwise"]["modes"]
    log = r["pairwise"]["log"]
    if expect is None:
        check(not log and modes.get("text", "none") == "none" and modes.get("layout", "none") == "none",
              f"{n} 个模型：没有组外裁判，只按规则评分，不做两两评审")
        if n == 1:
            check(r["scores"]["m0"]["dims"]["text"]["rank"] == "only", "1 个模型：不标第一")
        continue
    check(modes.get("text") == expect and modes.get("layout") == expect and r["pairwise"]["judged"] > 0,
          f"{n} 个模型：评审方式为 {expect}，完成 {r['pairwise']['judged']} 组")
    check(all(x["judge"] not in (x["a"], x["b"]) for x in log), f"{n} 个模型：模型不会评自己")
    per_model = Counter(m for x in log if x["kind"] == "outline" for m in (x["a"], x["b"]))
    check(len(per_model) == n and max(per_model.values()) - min(per_model.values()) <= 2,
          f"{n} 个模型：每个模型被比较的次数均衡 {dict(per_model)}")
    load = Counter(x["judge"] for x in log)
    check(max(load.values()) - min(load.values()) <= 3, f"{n} 个模型：评审工作量平摊 {dict(load)}")

# two contestants plus a model that only judges: third-party review comes back
r = benchmark.run(["m0", "m1"], judge_ids=["m0", "m1", "m5"], progress=quiet, dims=["text"])
log = r["pairwise"]["log"]
check(r["pairwise"]["modes"]["text"] == "third_party" and log and all(x["judge"] == "m5" for x in log),
      "2 个模型 + 指定外部裁判：由外部裁判做两两评审")

print("\n全部通过" if not FAILED else f"\n{len(FAILED)} 项失败")
sys.exit(1 if FAILED else 0)
