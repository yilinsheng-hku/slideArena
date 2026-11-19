"""Statistics for the leaderboard.

  bootstrap_ci  - confidence interval of one model's mean score, resampling over test cases
  behind_flags  - which models are clearly behind another one, for any number of models

Why a permutation test and not "compare everyone with the leader":
the leader is itself the highest of N noisy scores, and N - 1 separate comparisons each have
their own chance of a false alarm. With 10 equally good models a per-pair 90% test wrongly
declared someone "behind" in ~90% of runs. `behind_flags` controls the error over *all*
pairs at once (Westfall-Young max-T, permuting model labels within each case), so the false
alarm rate stays at about `alpha` whether there are 2 models or 20, and whether there are
7 cases or 30. See tests/test_scoring.py for the simulation that checks this.
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


def _paired_t(rows: list[list[float]], m: int, k: int) -> dict[tuple[int, int], float]:
    """Paired t statistic of (model j - model i) over cases, for every i < j."""
    out = {}
    for i in range(m):
        for j in range(i + 1, m):
            d = [rows[c][j] - rows[c][i] for c in range(k)]
            mu = sum(d) / k
            var = sum((x - mu) ** 2 for x in d) / (k - 1)
            if var > 1e-12:
                out[(i, j)] = mu / math.sqrt(var / k)
            else:                       # identical on every case, or a constant gap
                out[(i, j)] = 0.0 if abs(mu) < 1e-12 else math.copysign(1e6, mu)
    return out


def behind_flags(case_scores: dict[str, dict[str, float]], alpha: float = 0.1, n: int = 1000,
                 seed: int = 7) -> dict[str, bool]:
    """case_scores[model][case] -> {model: True if some other model is clearly better}.

    Only cases every model answered are used, so the comparison stays paired. Under the null
    hypothesis that the models are interchangeable, shuffling which model gave which score on
    each case changes nothing; the (1 - alpha) quantile of the largest |t| over all pairs in
    shuffled data is the bar a real gap must clear."""
    models = list(case_scores)
    m = len(models)
    flags = {mid: False for mid in models}
    if m < 2:
        return flags
    common = sorted(set.intersection(*(set(case_scores[mid]) for mid in models)))
    k = len(common)
    if k < 3:                           # too few shared cases to tell anyone apart
        return flags
    rows = [[float(case_scores[mid][c]) for mid in models] for c in common]
    observed = _paired_t(rows, m, k)
    rng = random.Random(seed)
    null = []
    for _ in range(n):
        shuffled = [rng.sample(row, m) for row in rows]
        null.append(max(abs(t) for t in _paired_t(shuffled, m, k).values()))
    null.sort()
    bar = null[min(n - 1, int(math.ceil((1 - alpha) * n)) - 1)]
    for (i, j), t in observed.items():
        if t > bar:
            flags[models[i]] = True     # j is clearly above i
        elif t < -bar:
            flags[models[j]] = True
    return flags
