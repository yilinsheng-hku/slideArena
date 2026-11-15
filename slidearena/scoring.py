"""Scorers. Each returns (score 0-100, parts {name: points}, notes [str]).

All checks are deterministic. Parts are kept so the report can show *why* a model lost points.
"""
from __future__ import annotations

import math
import re

from . import facts
from .cases import MARGIN, SLIDE_H, SLIDE_W


def _clip(x: float, hi: float = 100.0) -> float:
    return max(0.0, min(hi, x))


def _len(s) -> float:
    """Display length in CJK characters: spaces are free, ASCII letters/digits count as half."""
    return sum(0 if ch.isspace() else (0.5 if ord(ch) < 128 else 1) for ch in str(s).strip())


def _all_text(data) -> str:
    if isinstance(data, dict) and isinstance(data.get("slides"), list):
        return "\n".join(str(s.get("title", "")) + "\n" + "\n".join(map(str, s.get("bullets") or []))
                         for s in data["slides"] if isinstance(s, dict))
    if isinstance(data, dict):
        return str(data.get("title", "")) + "\n" + "\n".join(map(str, data.get("bullets") or []))
    return ""


def coverage(text: str, must_numbers: list[str], must_terms: list[str]) -> tuple[float, list[str]]:
    missing = [m for m in must_numbers if not facts.mentions(text, facts.q(m))]
    missing += [t for t in must_terms if t not in text]
    total = len(must_numbers) + len(must_terms)
    return (1.0 if not total else (total - len(missing)) / total), missing


def faithfulness(text: str, source: str, points: float, per_error: float) -> tuple[float, list[str], dict]:
    rep = facts.Source(source).report(text)
    bad = rep["unsupported"]
    return _clip(points - per_error * len(bad), points), bad, rep


def known_traps(text: str, case: dict) -> list[str]:
    """Case-specific wrong answers that the generic fact check cannot see, because the wrong number
    *is* in the source: a figure that was later corrected, an unverified rumour, "个百分点" written as "%".
    A pattern may carry a third item: a regex that, when it is on the same line, marks the mention as
    an honest explanation ("初稿 8.6 亿已更正为 8.2 亿") rather than a mistake."""
    hits = []
    for item in case.get("wrong_patterns", []):
        pat, msg, excuse = (list(item) + [None])[:3]
        for line in str(text).splitlines():
            if re.search(pat, line) and not (excuse and re.search(excuse, line)):
                hits.append(msg)
                break
    return hits


# --------------------------------------------------------------------------- outline
def score_outline(data, case) -> tuple[float, dict, list[str]]:
    slides = data.get("slides") if isinstance(data, dict) else None
    if not isinstance(slides, list) or not slides or not all(isinstance(s, dict) for s in slides):
        return 0.0, {}, ["没有合法的 slides 数组"]
    notes, n = [], case["n"]
    body = slides[1:]
    # format: 35
    f_count = 10.0 if len(slides) == n else max(0.0, 10 - 5 * abs(len(slides) - n))
    if len(slides) != n:
        notes.append(f"页数 {len(slides)}，要求 {n}")
    long_t = sum(1 for s in slides if _len(s.get("title", "")) > 16)
    f_title = 8 * (1 - long_t / len(slides))
    if long_t:
        notes.append(f"{long_t} 个标题超过 16 字")
    bad_cnt = sum(1 for s in body if not 3 <= len(s.get("bullets") or []) <= 5)
    f_bcount = 8 * (1 - bad_cnt / max(1, len(body)))
    if bad_cnt:
        notes.append(f"{bad_cnt} 页要点数量不在 3-5 条")
    bullets = [b for s in slides for b in (s.get("bullets") or [])]
    long_b = sum(1 for b in bullets if _len(b) > 28)
    f_blen = 9 * (1 - long_b / max(1, len(bullets)))
    if long_b:
        notes.append(f"{long_b} 条要点超过 28 字")
    fmt = f_count + f_title + f_bcount + f_blen

    text = _all_text(data)
    cov, missing = coverage(text, case["must_numbers"], case["must_terms"])
    if missing:
        notes.append("漏掉关键信息：" + "、".join(missing))
    if case.get("check_numbers", True):
        faith, bad, rep = faithfulness(text, case["material"], 30, 12)
        if bad:
            notes.append("资料里没有依据的数字：" + "、".join(bad[:6]))
        if rep["unverifiable"]:
            notes.append(f"{len(rep['unverifiable'])} 个数字精度太粗无法核实（不扣分）")
    else:
        faith = 30.0
    traps = known_traps(text, case)
    if traps:
        faith = _clip(faith - 12 * len(traps), 30)
        notes += traps
    parts = {"格式": round(fmt, 1), "关键信息覆盖": round(35 * cov, 1), "数字可信": round(faith, 1)}
    return round(sum(parts.values()), 1), parts, notes


# --------------------------------------------------------------------------- condense
def score_condense(data, case) -> tuple[float, dict, list[str]]:
    if not isinstance(data, dict) or not isinstance(data.get("bullets"), list) or not data["bullets"]:
        return 0.0, {}, ["没有合法的 bullets 数组"]
    notes, bl = [], [str(b) for b in data["bullets"]]
    f_cnt = 15.0 if 3 <= len(bl) <= case["max_bullets"] else 5.0
    if f_cnt < 15:
        notes.append(f"要点 {len(bl)} 条，要求 3-{case['max_bullets']} 条")
    over = sum(1 for b in bl if _len(b) > case["max_len"])
    f_len = 20 * (1 - over / len(bl))
    if over:
        notes.append(f"{over} 条要点超过 {case['max_len']} 字")
    f_title = 5.0 if 0 < _len(data.get("title", "")) <= 16 else 0.0
    if not f_title:
        notes.append(f"标题缺失或超过 16 字（约 {_len(data.get('title', '')):g} 字）")
    text = _all_text(data)
    cov, missing = coverage(text, case["must_numbers"], case.get("must_terms", []))
    if missing:
        notes.append("丢了关键信息：" + "、".join(missing))
    faith, bad, _ = faithfulness(text, case["material"], 20, 10)
    if bad:
        notes.append("资料里没有依据的数字：" + "、".join(bad))
    traps = known_traps(text, case)
    if traps:
        faith = _clip(faith - 10 * len(traps), 20)
        notes += traps
    parts = {"格式": f_cnt + round(f_len, 1) + f_title, "关键数字保留": round(40 * cov, 1), "数字可信": faith}
    return round(sum(parts.values()), 1), parts, notes


# --------------------------------------------------------------------------- chart
_CAT_SUFFIX = re.compile(r"(地区|区域|渠道|年度|年|区|商)$")


def norm_cat(c) -> str:
    s = re.sub(r"[（(].*?[）)]", "", str(c))
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"^20\d\d年(?=\d)", "", s)          # "2026年7月" -> "7月"
    s = re.sub(r"^0(?=\d月)", "", s)               # "07月" -> "7月"
    return _CAT_SUFFIX.sub("", s)


def score_chart(data, case) -> tuple[float, dict, list[str]]:
    if not isinstance(data, dict):
        return 0.0, {}, ["不是 JSON 对象"]
    if case.get("skip"):
        if data.get("skip") is True:
            return 100.0, {"正确拒绝": 100}, []
        return 0.0, {"正确拒绝": 0}, ["资料里没有数据，却画出了图表（编造）"]
    if data.get("skip"):
        return 0.0, {}, ["资料里有数据，却拒绝作图"]
    notes = []
    try:
        series = data["series"]
        vals_by_series = [[float(v) for v in item["values"]] for item in series]
    except (KeyError, IndexError, TypeError, ValueError):
        return 0.0, {}, ["没有可用的数值"]
    want_by_series = case.get("series_values") or [case["values"]]
    tol_abs = case.get("tol", 0.051)
    total_values = sum(len(want) for want in want_by_series)
    right = 0
    for got, want in zip(vals_by_series, want_by_series):
        right += sum(1 for i, expected in enumerate(want)
                     if i < len(got) and abs(got[i] - expected) <= max(tol_abs, 0.006 * abs(expected)))
    p_vals = 60 * right / max(1, total_values)
    if right < total_values:
        notes.append(f"{total_values - right}/{total_values} 个数值不对（应为 {want_by_series}，给出 {vals_by_series}）")
    cats = [norm_cat(c) for c in (data.get("categories") or [])]
    want_c = [norm_cat(c) for c in case["categories"]]
    c_right = sum(1 for i, w in enumerate(want_c) if i < len(cats) and cats[i] == w)
    p_cats = 20 * c_right / len(want_c)
    if c_right < len(want_c):
        notes.append(f"分类标签不对（应为 {case['categories']}）")
    ctype = str(data.get("chart_type", "")).lower()
    p_type = 10.0 if ctype in case["good_types"] else 0.0
    if not p_type:
        notes.append(f"图表类型 {ctype or '空'} 不适合")
    clean = len(series) == len(want_by_series) and all(
        len(got) == len(want) == len(want_c) for got, want in zip(vals_by_series, want_by_series)
    ) and len(cats) == len(want_c)
    p_clean = 10.0 if clean else 0.0
    if not clean:
        notes.append("混入了无关数据或多余系列")
    parts = {"数值": round(p_vals, 1), "分类": round(p_cats, 1), "类型": p_type, "无多余数据": p_clean}
    return round(sum(parts.values()), 1), parts, notes


# --------------------------------------------------------------------------- layout
TEXT_INNER_PADDING_IN = 0.1
TEXT_LINE_HEIGHT_EM = 1.25
TEXT_PARAGRAPH_GAP_EM = 0.3
TEXT_FIT_TOLERANCE_IN = 0.02


def _visual_len(s: str) -> float:
    return sum(0.55 if ord(ch) < 128 else 1.0 for ch in str(s))


def text_height(paras: list[str], w_in: float, font_pt: float) -> float:
    """Estimated text height in inches using the same metrics as the layout renderer."""
    usable = max(0.05, w_in - 2 * TEXT_INNER_PADDING_IN) * 72
    cpl = max(1.0, math.floor(usable / font_pt))
    lines = sum(max(1, math.ceil(_visual_len(p) / cpl)) for p in paras)
    return (lines * font_pt * TEXT_LINE_HEIGHT_EM / 72 + 2 * TEXT_INNER_PADDING_IN
            + max(0, len(paras) - 1) * font_pt * TEXT_PARAGRAPH_GAP_EM / 72)


def text_fits(paras: list[str], w_in: float, font_pt: float, h_in: float) -> bool:
    """Return the shared rule for whether text fits in a box."""
    return text_fit_ratio(paras, w_in, font_pt, h_in) <= 1.0


def text_fit_ratio(paras: list[str], w_in: float, font_pt: float, h_in: float) -> float:
    """Return required height divided by available height.

    The small tolerance keeps a glyph that lands within 0.02 inches of the
    lower edge from being penalized, while still exposing gradual overflow to
    the scorer and the renderer.
    """
    return text_height(paras, w_in, font_pt) / max(0.05, h_in + TEXT_FIT_TOLERANCE_IN)


def text_fit_score(ratio: float) -> float:
    """Map fit ratio to a 0..1 score: full at 1.0, zero at 1.5."""
    return max(0.0, min(1.0, (1.5 - ratio) / 0.5))


def _overlap(a, b) -> float:
    dx = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
    dy = min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"])
    return max(0.0, dx) * max(0.0, dy)


def score_layout(data, case) -> tuple[float, dict, list[str]]:
    raw = data.get("elements") if isinstance(data, dict) else None
    if not isinstance(raw, list) or not raw:
        return 0.0, {}, ["没有 elements 数组"]
    els, notes = {}, []
    for e in raw:
        try:
            role = str(e["role"])
            els[role] = {**e, **{k: float(e[k]) for k in ("x", "y", "w", "h")}}
        except (KeyError, TypeError, ValueError):
            continue
    spec = case["elements"]
    present = [r for r in spec if r in els]
    p_struct = 15 * len(present) / len(spec)
    if len(present) < len(spec):
        notes.append("缺少元素：" + "、".join(r for r in spec if r not in els))
    if not present:
        return 0.0, {}, notes
    lo_x, lo_y, hi_x, hi_y = MARGIN - 0.02, MARGIN - 0.02, SLIDE_W - MARGIN + 0.02, SLIDE_H - MARGIN + 0.02
    out = [r for r in present if els[r]["w"] <= 0 or els[r]["h"] <= 0 or els[r]["x"] < lo_x or els[r]["y"] < lo_y
           or els[r]["x"] + els[r]["w"] > hi_x or els[r]["y"] + els[r]["h"] > hi_y]
    p_bounds = 15 * (1 - len(out) / len(present))
    if out:
        notes.append("超出边距：" + "、".join(out))
    ov = sum(_overlap(els[a], els[b]) for i, a in enumerate(present) for b in present[i + 1:])
    p_overlap = 20.0 if ov <= 0.01 else max(0.0, 20 - ov * 10)
    if ov > 0.01:
        notes.append(f"元素重叠 {ov:.2f} 平方英寸")

    text_roles = [r for r in present if spec[r] is not None]
    fit_scores, font_ok = [], 0
    for r in text_roles:
        e = els[r]
        try:
            fs = float(e.get("font_size"))
        except (TypeError, ValueError):
            notes.append(f"{r} 没有字号")
            continue
        lo, hi = (28, 44) if r == "title" else (14, 24)
        if lo <= fs <= hi:
            font_ok += 1
        else:
            notes.append(f"{r} 字号 {fs:g} 不在 {lo}-{hi}")
        need = text_height(spec[r], e["w"], fs)
        ratio = text_fit_ratio(spec[r], e["w"], fs, e["h"])
        fit_scores.append(text_fit_score(ratio))
        if ratio > 1.0:
            overflow = max(0.0, (ratio - 1.0) * 100)
            notes.append(f"{r} 文字超出约 {overflow:.0f}%（需要 {need:.2f} 英寸高，只给了 {e['h']:.2f}）")
    n_text = max(1, len(text_roles))
    p_fit = 25 * sum(fit_scores) / n_text
    p_font = 10 * font_ok / n_text

    checks, passed = 0, 0
    if "title" in els and case.get("title_on_top", True):
        checks += 1
        others = [els[r] for r in present if r != "title"]
        # title must sit above the *text* elements; a full-height image beside it is fine
        texts = [els[r] for r in present if r != "title" and spec.get(r) is not None]
        if all(els["title"]["y"] <= e["y"] + 1e-6 for e in (texts or others)):
            passed += 1
        else:
            notes.append("标题不在文字内容的上方")
    for r, frac in (case.get("min_area") or {}).items():
        checks += 1
        if r in els and els[r]["w"] * els[r]["h"] >= frac * SLIDE_W * SLIDE_H - 1e-6:
            passed += 1
        else:
            notes.append(f"{r} 面积不足画面的 {frac:.0%}")
    uni = [els[r] for r in case.get("uniform", []) if r in els]
    if case.get("uniform"):
        checks += 1
        if len(uni) == len(case["uniform"]) and all(
                abs(u["w"] - uni[0]["w"]) <= 0.05 * uni[0]["w"] and abs(u["h"] - uni[0]["h"]) <= 0.05 * uni[0]["h"]
                for u in uni):
            passed += 1
        else:
            notes.append("卡片大小不一致")
    for cap, target in (case.get("below") or {}).items():
        checks += 1
        c, t = els.get(cap), els.get(target)
        # caption sits right under its own chart (gap <= 0.4 in) and horizontally within it
        if c and t and 0 <= c["y"] - (t["y"] + t["h"]) + 0.02 <= 0.42 and \
                c["x"] >= t["x"] - 0.1 and c["x"] + c["w"] <= t["x"] + t["w"] + 0.1:
            passed += 1
        else:
            notes.append(f"{cap} 没有紧贴在 {target} 下方")
    if case.get("row"):
        checks += 1
        row = [els[r] for r in case["row"] if r in els]
        if len(row) == len(case["row"]) and all(abs(e["y"] - row[0]["y"]) <= 0.05 for e in row) and \
                all(row[i]["x"] + row[i]["w"] <= row[i + 1]["x"] + 0.01 for i in range(len(row) - 1)):
            passed += 1
        else:
            notes.append("没有按顺序排成一行")
    p_req = 15 * passed / max(1, checks)
    parts = {"元素齐全": round(p_struct, 1), "不越界": round(p_bounds, 1), "不重叠": round(p_overlap, 1),
             "文字放得下": round(p_fit, 1), "字号合适": round(p_font, 1), "版式要求": round(p_req, 1)}
    return round(sum(parts.values()), 1), parts, notes


def speed_score(latencies: list[float]) -> float:
    if not latencies:
        return 0.0
    lat = sorted(latencies)[len(latencies) // 2]
    # 3 s or less = 100, 60 s or more = 0, log scale in between (doubling latency costs the same)
    if lat <= 3:
        return 100.0
    return _clip(100 * (1 - math.log(lat / 3) / math.log(20)))
