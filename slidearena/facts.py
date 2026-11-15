"""Number fact-checking: is every number a model wrote backed by the user's material?

A number counts as *supported* when it
  1. appears in the source, possibly in another unit (71,000 万 = 7.1 亿), or
  2. can be derived from nearby source numbers in one common step: difference, growth rate,
     ratio, total of a consecutive run (+ shares of it), amount x percentage, or a
     percentage-point change.
Rounding is respected: "41%" matches 41.28..., while "41.3%" must be within 0.05.

Derivations only pair figures listed close together (a time series or a breakdown is written
consecutively). That keeps random coincidences rare; see tests for measured false-pass rates.
It is a heuristic: it can miss some invented numbers, but does not flag correctly derived ones.
"""
from __future__ import annotations

import bisect
import re
from dataclasses import dataclass

# unit -> (family, multiplier). Longest units first so "亿元" wins over "亿".
_UNITS = {"个百分点": ("pct", 1.0), "%": ("pct", 1.0), "％": ("pct", 1.0),
          "亿元": ("num", 1e8), "亿": ("num", 1e8), "千万": ("num", 1e7), "百万": ("num", 1e6),
          "万元": ("num", 1e4), "万": ("num", 1e4), "元": ("num", 1.0)}
_NUM = re.compile(r"(?<![A-Za-z0-9.])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s*(" +
                  "|".join(re.escape(u) for u in _UNITS) + r")?")


@dataclass(frozen=True)
class Qty:
    value: float      # as written
    decimals: int
    unit: str
    family: str       # "pct" or "num"
    mult: float
    text: str

    @property
    def norm(self) -> float:
        return self.value * self.mult

    @property
    def tol(self) -> float:
        """Half of the last written digit (rounding tolerance), in normalized units."""
        return 0.5 * 10 ** (-self.decimals) * self.mult + 1e-9


def extract(text: str) -> list[Qty]:
    out = []
    for m in _NUM.finditer(str(text)):
        intpart, frac, unit = m.group(1), m.group(2) or "", m.group(3) or ""
        family, mult = _UNITS.get(unit, ("num", 1.0))
        out.append(Qty(float(intpart.replace(",", "") + frac), max(0, len(frac) - 1), unit, family, mult,
                       m.group(0).strip()))
    return out


def is_trivial(x: Qty) -> bool:
    """Years, quarter/month/list indices and other small counts are not factual claims."""
    if x.decimals or x.unit:
        return False
    return x.value <= 12 or 1900 <= x.value <= 2100


def facts(text: str) -> list[Qty]:
    return [x for x in extract(text) if not is_trivial(x)]


def q(text: str) -> Qty:
    """Parse a single quantity, e.g. q("7.1亿")."""
    found = extract(text)
    if not found:
        raise ValueError(f"no number in {text!r}")
    return found[0]


class Source:
    """The user's material, pre-expanded into every value a model could honestly write."""

    def __init__(self, text: str):
        self.qtys = facts(text)
        num_q = [x for x in self.qtys if x.family == "num"]
        nums = [x.norm for x in num_q]                             # text order, duplicates kept
        pcts = _unique([x.value for x in self.qtys if x.family == "pct"])
        self._raw = {"num": sorted(set(nums)), "pct": sorted(set(pcts))}
        d_num, d_pct = set(nums), set(pcts)
        for i, a in enumerate(nums):
            for b in nums[i + 1:i + 4]:
                d_num.add(abs(b - a))                                  # change between two figures
                for base in (a, b):
                    if base:
                        d_pct.add(abs(b - a) / base * 100)             # growth / decline rate
                lo, hi = sorted((a, b))
                if hi:
                    d_pct.add(lo / hi * 100)                           # ratio, e.g. MAU / registered
        # figures with the same explicit unit (亿 with 亿, 万 with 万) are often compared even when far
        # apart in the text, e.g. "new product = 19.8% of revenue"
        groups: dict[float, list[float]] = {}
        for x in num_q:
            if x.unit:
                groups.setdefault(x.mult, []).append(x.norm)
        for vals in groups.values():
            for i, a in enumerate(vals):
                for b in vals[i + 1:]:
                    lo, hi = sorted((a, b))
                    if hi:
                        d_pct.add(lo / hi * 100)
                    for base in (a, b):
                        if base:
                            d_pct.add(abs(b - a) / base * 100)
        # totals and shares only within one sentence: a breakdown is written together
        # ("华东 7.1 亿、华南 3.2 亿、其他 6.9 亿。"); summing across sentences adds unrelated figures
        for sent in re.split(r"[。；;！!？?\n]", text):
            vals = [x.norm for x in facts(sent) if x.family == "num"]
            for i in range(len(vals)):
                for j in range(i + 2, min(len(vals), i + 6) + 1):
                    total = sum(vals[i:j])
                    d_num.add(total)
                    for a in vals[i:j]:
                        d_pct.add(a / total * 100)
        for p in pcts:
            for a in nums:
                d_num.add(a * p / 100)                                 # amount x percentage
        for i, a in enumerate(pcts):
            for b in pcts[i + 1:]:
                d_pct.add(abs(a - b))                                  # percentage-point change
        # same explicit unit (亿 with 亿): differences are common even between far-apart figures
        for vals in groups.values():
            for i, a in enumerate(vals):
                for b in vals[i + 1:]:
                    d_num.add(abs(a - b))
        self._pool = {"num": sorted(d_num), "pct": sorted(d_pct)}
        # two-step derivations (a derived rate vs a target, users x conversion x price, x12 to annualise):
        # plausible, but loose enough that random numbers match too -> only ever "unverifiable".
        # Products only pair a count/amount with a small factor (a price or headcount, < 10,000),
        # never two large amounts, which would match almost anything.
        raw_nums = _unique(nums)
        small = [b for b in raw_nums if b < 1e4]
        p2 = {abs(p - r) for p in d_pct for r in pcts}
        n2 = {a * b for a in d_num for b in small}
        n2 |= {v * 12 for v in n2}
        self._pool2 = {"num": sorted(n2), "pct": sorted(p2)}

    def classify(self, x: Qty) -> str:
        """trivial / supported / unverifiable / unsupported.

        "unverifiable": the number matches only a *derived* value and is written so coarsely
        (e.g. "41%") that a made-up number would match by chance too often to call it supported.
        """
        if is_trivial(x):
            return "trivial"
        # a number written without its unit ("12.5→14.8") may mean 亿 or 万 from the source
        scales = (1.0, 1e4, 1e8) if x.family == "num" and not x.unit else (1.0,)
        coarse = x.tol / max(abs(x.norm), 1e-9) > 0.005
        for k in scales:
            v, tol = x.norm * k, x.tol * k
            if _near(self._raw[x.family], v, tol):
                return "supported"
            if _near(self._pool[x.family], v, tol):
                return "unverifiable" if coarse else "supported"
        for k in scales:
            if _near(self._pool2[x.family], x.norm * k, x.tol * k):
                return "unverifiable"
        return "unsupported"

    def report(self, text: str) -> dict:
        out = {"supported": [], "unverifiable": [], "unsupported": []}
        for x in facts(text):
            c = self.classify(x)
            if c in out:
                out[c].append(x.text)
        return out

    def supports(self, x: Qty) -> bool:
        return self.classify(x) != "unsupported"

    def supports_value(self, v, scales=(1.0, 1e4, 1e8)) -> bool:
        """A bare chart value whose unit is given separately: accept it in any of these units or as a percentage."""
        try:
            v = abs(float(v))
        except (TypeError, ValueError):
            return False
        s = repr(v)
        dec = min(4, len(s.split(".")[1])) if "." in s and not s.endswith(".0") else 0
        tol = 0.5 * 10 ** (-dec) + 1e-9
        if _near(self._pool["pct"], v, tol):
            return True
        return any(_near(self._pool["num"], v * k, tol * k) for k in scales)

    def unsupported(self, text: str) -> list[str]:
        return [x.text for x in facts(text) if not self.supports(x)]

    def unsupported_values(self, values) -> list[float]:
        return [v for v in values if not self.supports_value(v)]


def mentions(text: str, target: Qty) -> bool:
    """Does the text contain this quantity (allowing unit conversion and rounding)?"""
    for x in extract(text):
        if x.family == target.family and abs(x.norm - target.norm) <= max(x.tol, target.tol):
            return True
    return False


def _unique(vals):
    seen, out = set(), []
    for v in vals:
        k = round(v, 9)
        if k not in seen:
            seen.add(k)
            out.append(v)
    return out


def _near(sorted_vals: list[float], x: float, tol: float) -> bool:
    i = bisect.bisect_left(sorted_vals, x - tol)
    return i < len(sorted_vals) and sorted_vals[i] <= x + tol
