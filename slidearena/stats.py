"""Statistics for the leaderboard.

  bootstrap_ci   - confidence interval of a mean score, resampling over test cases
  separable      - are two models' scores really different, or a tie within noise?
  bradley_terry  - turn pairwise wins (A beat B) into one strength score per model
"""
from __future__ import annotations

import math
import random
import statistics


def bootstrap_ci(values: list[float], n: int = 2000, level: float = 0.9, seed: int = 7) -> tuple[float, float, float]:
    """(mean, low, high). With one value the interval collapses to that value."""
    if not values:
        return 0.0, 0.0, 0.0
    mean = statistics.mean(values)
    if len(values) == 1:
        return mean, mean, mean
    rng = random.Random(seed)
    k = len(values)
    means = sorted(statistics.mean(rng.choices(values, k=k)) for _ in range(n))
    lo = means[int((1 - level) / 2 * n)]
    hi = means[min(n - 1, int((1 + level) / 2 * n))]
    return mean, lo, hi


def paired_diff_ci(a: list[float], b: list[float], n: int = 2000, level: float = 0.9, seed: int = 11):
    """CI of mean(a - b) over the same cases (paired). Returns (diff, low, high)."""
    diffs = [x - y for x, y in zip(a, b)]
    return bootstrap_ci(diffs, n, level, seed)


def separable(a: list[float], b: list[float]) -> int:
    """+1 if a is clearly better, -1 if b is clearly better, 0 if the difference is within noise."""
    if len(a) != len(b) or not a:
        return 0
    d, lo, hi = paired_diff_ci(a, b)
    if lo > 0:
        return 1
    if hi < 0:
        return -1
    return 0


def bradley_terry(models: list[str], wins: dict[tuple[str, str], float], iters: int = 200,
                  prior: float = 0.5) -> dict[str, float]:
    """MM algorithm (Hunter 2004). wins[(i, j)] = how many times i beat j (ties count 0.5 each way).

    A small prior (virtual half-win against every opponent) keeps strengths finite when a model
    wins or loses everything. Returned on an Elo-like scale centred on 1000.
    """
    if len(models) < 2:
        return {m: 1000.0 for m in models}
    w = {(i, j): wins.get((i, j), 0.0) + prior for i in models for j in models if i != j}
    p = {m: 1.0 for m in models}
    for _ in range(iters):
        new = {}
        for i in models:
            num = sum(w[(i, j)] for j in models if j != i)
            den = sum((w[(i, j)] + w[(j, i)]) / (p[i] + p[j]) for j in models if j != i)
            new[i] = num / den if den else p[i]
        g = math.exp(statistics.mean(math.log(v) for v in new.values()))
        p = {m: v / g for m, v in new.items()}
    return {m: round(1000 + 400 * math.log10(v), 1) for m, v in p.items()}


def win_rate_to_points(elo: dict[str, float]) -> dict[str, float]:
    """Map BT strengths to 0-100: expected win rate against an average opponent of the group."""
    if len(elo) < 2:
        return {m: 50.0 for m in elo}
    out = {}
    for m, r in elo.items():
        others = [o for o in elo if o != m]
        out[m] = round(100 * statistics.mean(1 / (1 + 10 ** ((elo[o] - r) / 400)) for o in others), 1)
    return out
