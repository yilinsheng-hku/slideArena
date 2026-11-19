"""Benchmark: measure every connected model on the abilities a PPT needs.

Pipeline
  1. Every model answers the same question bank (cases.py), optionally several times
     (`repeats`) because LLM output varies between calls.
  2. Deterministic scorers (scoring.py) grade each answer and explain lost points.
     Numbers are fact-checked against the source material (facts.py).
  3. Outline quality that rules cannot capture is judged *pairwise*: a third model sees two
     outlines side by side, twice with A/B swapped to cancel position bias. Models never judge
     themselves; with only two models they judge each other and a win needs the loser to agree.
     Pairs are scheduled so each model is compared equally often whatever the number of models.
     Wins are combined with Bradley-Terry (stats.py).
  4. Per dimension we report the mean, a bootstrap confidence interval over cases, and whether
     the gap to the leader is real or within noise (paired bootstrap).
  5. Profiles store score, interval, cost and latency. Routing reads them.

Dimensions
  text    - outline writing (rules 75% + pairwise judging 25% when >= 2 models) and condensing
  chart   - picking, converting and computing the right numbers; refusing when there are none
  layout  - placing elements so nothing overlaps, everything fits, design asks are met
            (rules 75% + pairwise judging of rendered screenshots by vision models 25%)
  image   - generating an illustration (image-capable endpoints only; success rate)
  speed   - median latency, log scale
"""
from __future__ import annotations

import base64
import itertools
import json
import random
import statistics
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

from . import cases as C
from . import config, llm, render, scoring, stats

DIMENSIONS = {"text": "文字 / 大纲", "layout": "排版", "chart": "数据图表", "image": "配图", "speed": "速度"}
QUALITY_DIMS = ("text", "layout", "chart")
ALL_CASES = [c for bank in (C.OUTLINE, C.REVISE, C.CONDENSE, C.CHART, C.LAYOUT, C.IMAGE) for c in bank]

# kept for deck.py and older callers
SYS = C.SYS
OUTLINE_PROMPT = C.OUTLINE_PROMPT


def task_list(model: dict) -> list[tuple[str, str, dict]]:
    """(dimension, kind, case) for one model."""
    jobs = [("text", "outline", c) for c in C.OUTLINE]
    jobs += [("text", "revise", c) for c in C.REVISE]
    jobs += [("text", "condense", c) for c in C.CONDENSE]
    jobs += [("chart", "chart", c) for c in C.CHART]
    jobs += [("layout", "layout", c) for c in C.LAYOUT]
    if model.get("can_image"):
        jobs += [("image", "image", c) for c in C.IMAGE]
    return jobs


def build_prompt(kind: str, case: dict) -> str:
    if kind == "outline":
        return C.OUTLINE_PROMPT.format(n=case["n"], brief=C.outline_brief(case))
    if kind == "revise":
        return C.REVISE_PROMPT.format(n=case["n"], brief=case["brief"], material=case["material"],
                                      flawed_json=json.dumps(case["flawed"], ensure_ascii=False))
    if kind == "condense":
        return C.CONDENSE_PROMPT.format(material=case["material"], max_bullets=case["max_bullets"],
                                        max_len=case["max_len"])
    if kind == "chart":
        return C.CHART_PROMPT.format(material=case["material"], ask=case["ask"])
    if kind == "layout":
        return C.LAYOUT_PROMPT.format(desc=case["desc"], elements=C.layout_elements_text(case))
    raise ValueError(kind)


MAX_TOKENS = 12000


def _truncated(reply) -> bool:
    raw = reply.raw or {}
    try:
        return raw["choices"][0].get("finish_reason") == "length"
    except (KeyError, IndexError, TypeError):
        return raw.get("stop_reason") == "max_tokens"


SCORERS = {"outline": scoring.score_outline, "revise": scoring.score_revise, "condense": scoring.score_condense,
           "chart": scoring.score_chart, "layout": scoring.score_layout}


def _run_one(model: dict, dim: str, kind: str, case: dict, rep: int) -> dict:
    rec = {"model_id": model["id"], "task": case["id"], "dimension": dim, "kind": kind, "rep": rep,
           "score": 0.0, "parts": {}, "notes": [], "latency": 0.0, "in_tokens": 0, "out_tokens": 0,
           "error": None, "answer": None}
    try:
        if kind == "image":
            img, lat = llm.generate_image(model, case["prompt"])
            ok = len(img) > 1000
            rec.update(latency=lat, score=100.0 if ok else 0.0,
                       answer="data:image/png;base64," + base64.b64encode(img).decode() if ok else None,
                       notes=["生成成功（画面好坏请人工查看）" if ok else "返回的图片为空"])
            return rec
        # reasoning models spend output tokens on thinking first; leave room so the answer is not cut off
        reply = llm.chat(model, build_prompt(kind, case), system=C.SYS, max_tokens=MAX_TOKENS,
                         temperature=0.3 if rep else 0.2, timeout=240)
        rec.update(latency=reply.latency, in_tokens=reply.input_tokens, out_tokens=reply.output_tokens,
                   answer=reply.text)
        if _truncated(reply):
            rec["truncated"] = True
        try:
            data = llm.extract_json(reply.text)
        except llm.ModelError:
            if rec.get("truncated"):
                raise llm.ModelError(f"输出达到 {MAX_TOKENS} token 上限被截断（多为思考过长），没有给出完整答案") from None
            raise
        rec["score"], rec["parts"], rec["notes"] = SCORERS[kind](data, case)
        if kind in ("outline", "revise", "layout"):
            rec["parsed"] = data
    except llm.RateLimited as e:
        # the account's rate limit, not the model's ability: leave this call out of the score
        rec["skipped"] = True
        rec["notes"] = ["账号限流，多次重试仍被拒绝，本题不计分：" + str(e)[:160]]
    except llm.ModelError as e:
        rec["error"] = str(e)
        rec["notes"] = [str(e)[:200]]
    except Exception as e:  # one bad answer must not crash the run
        rec["error"] = f"{type(e).__name__}: {e}"
        rec["notes"] = [rec["error"][:200]]
        traceback.print_exc()
    return rec


# --------------------------------------------------------------------------- pairwise judging
def _outline_text(data: dict) -> str:
    lines = []
    for i, s in enumerate(data.get("slides", []), 1):
        lines.append(f"{i}. {s.get('title', '')}")
        lines += [f"   - {b}" for b in s.get("bullets") or []]
    return "\n".join(lines)[:3500]


def _parse_winner(text: str) -> str | None:
    try:
        w = str(llm.extract_json(text).get("winner", "")).strip().upper()
    except (llm.ModelError, AttributeError):
        import re
        m = re.search(r'"winner"\s*:\s*"(A|B|tie)"', text, re.I)
        w = m.group(1).upper() if m else ""
    return {"A": "A", "B": "B", "TIE": "tie"}.get(w)


def _judge_request(kind: str, case: dict, a_rec: dict, b_rec: dict, flip: bool) -> tuple[str, list[str] | None]:
    """Prompt (and images) for one verdict. flip=True shows B first."""
    first, second = (b_rec, a_rec) if flip else (a_rec, b_rec)
    if kind == "outline":
        return C.PAIRWISE_PROMPT.format(brief=C.outline_brief(case), a=_outline_text(first["parsed"]),
                                        b=_outline_text(second["parsed"])), None
    imgs = [render.data_url(render.render_layout(r["parsed"], case)) for r in (first, second)]
    return C.VISUAL_PAIRWISE_PROMPT.format(desc=case["desc"]), imgs


def schedule_pairs(ids: list[str], case_index: int = 0, seed: int = 42) -> list[tuple[str, str]]:
    """Which pairs to compare on one case, for any number of models.

    Up to 4 models: every pair (at most 6). From 5 models on: one "round" of a circle schedule,
    pairing each model with the one `d` seats away, so every model is compared the same number
    of times on this case (twice, or once when d = N/2). `d` rotates from case to case, so over
    the bank all pairs get covered while each model's judging cost stays constant as N grows.
    """
    ids = sorted(ids)
    n = len(ids)
    if n < 2:
        return []
    if n <= 4:
        return list(itertools.combinations(ids, 2))
    seats = ids[:]
    random.Random(seed).shuffle(seats)      # seat order must not follow config order
    d = 1 + case_index % (n // 2)
    pairs = {tuple(sorted((seats[i], seats[(i + d) % n]))) for i in range(n)}
    return sorted(pairs)


def judging_mode(model_ids: list[str], judge_ids: list[str]) -> str:
    """How pairs will be judged for this set of models and judges:
    none        - fewer than two models (or no judge at all): rule scores only
    third_party - every pair can be judged by a model outside it
    mutual      - no pair has an outside judge, so the two models judge each other
    mixed       - some pairs third-party, some mutual"""
    if len(model_ids) < 2 or not judge_ids:
        return "none"
    modes = set()
    for a, b in itertools.combinations(sorted(set(model_ids)), 2):
        if any(j not in (a, b) for j in judge_ids):
            modes.add("third_party")
        elif a in judge_ids and b in judge_ids:
            modes.add("mutual")
    if not modes:
        return "none"
    return modes.pop() if len(modes) == 1 else "mixed"


def _verdict_pair(judge: dict, kind: str, case: dict, ra: dict, rb: dict) -> str | None:
    """One judge, asked twice with A/B swapped. Returns "A", "B", "tie" or None on failure.
    A verdict counts only if both orders agree; disagreement is a tie (position bias)."""
    verdicts = []
    for flip in (False, True):
        try:
            prompt, imgs = _judge_request(kind, case, ra, rb, flip)
            r = llm.chat(judge, prompt, system=C.SYS, images=imgs, max_tokens=4000, temperature=0, timeout=240)
            w = _parse_winner(r.text)
        except Exception:
            w = None
        if w is None:
            return None
        if flip and w != "tie":
            w = "B" if w == "A" else "A"
        verdicts.append(w)
    return verdicts[0] if verdicts[0] == verdicts[1] else "tie"


def pairwise_judging(records: list[dict], models: list[dict], judges: list[dict], progress,
                     kind: str = "outline") -> dict:
    """Judge answers pairwise: outlines as text, layouts as rendered screenshots (vision judges).

    Works for any number of models:
      * pairs come from `schedule_pairs`, balanced per model;
      * a pair is judged by a model outside it when one exists (least-loaded judge first, the
        others as backups);
      * otherwise (two models, no outside judge) both models judge the pair and a win counts only
        when both agree, i.e. the loser concedes; a self-serving vote can only produce a tie.
    Each judge is asked twice with A/B swapped; inconsistent answers are a tie."""
    by_case: dict[str, dict[str, dict]] = {}
    for r in records:
        if r["kind"] == kind and r.get("parsed") and r["rep"] == 0:
            by_case.setdefault(r["task"], {})[r["model_id"]] = r
    bank = C.OUTLINE if kind == "outline" else C.LAYOUT
    case_map = {c["id"]: c for c in bank}
    order_of = {c["id"]: i for i, c in enumerate(bank)}
    judge_by_id = {j["id"]: j for j in judges}
    wins: dict[tuple[str, str], float] = {}
    log = []
    jobs = []
    load = {j["id"]: 0 for j in judges}
    for cid in sorted(by_case, key=lambda c: order_of.get(c, 0)):
        answers = by_case[cid]
        for a, b in schedule_pairs(list(answers), order_of.get(cid, 0)):
            eligible = [j for j in judges if j["id"] not in (a, b)]
            if eligible:
                eligible.sort(key=lambda j: load[j["id"]])     # stable: ties keep config order
                load[eligible[0]["id"]] += 1
                jobs.append((cid, a, b, "third_party", eligible))
            elif a in judge_by_id and b in judge_by_id:
                jobs.append((cid, a, b, "mutual", [judge_by_id[a], judge_by_id[b]]))
    if not jobs:
        return {"wins": wins, "log": log, "judged": 0}

    def ask(job):
        cid, a, b, mode, order = job
        ra, rb = by_case[cid][a], by_case[cid][b]
        case = case_map[cid]
        if mode == "mutual":
            votes = [_verdict_pair(j, kind, case, ra, rb) for j in order]
            return job, order, votes
        # the same judge gives both orders; if it fails (rate limit, bad output), try the next one
        for judge in order:
            v = _verdict_pair(judge, kind, case, ra, rb)
            if v is not None:
                return job, [judge], [v]
        return job, order[:1], [None]

    label = "视觉评审" if kind == "layout" else "两两评审"
    with ThreadPoolExecutor(max_workers=4) as ex:
        for (cid, a, b, mode, _), used, votes in ex.map(ask, jobs):
            entry = {"case": cid, "a": a, "b": b, "kind": kind, "mode": mode,
                     "judge": used[0]["id"] if mode == "third_party" else "mutual",
                     "judges": [j["id"] for j in used], "votes": votes}
            if None in votes:
                entry["result"] = "评审失败"
                log.append(entry)
                continue
            if len(set(votes)) == 1 and votes[0] != "tie":
                outcome = a if votes[0] == "A" else b
            else:
                outcome = "tie"                     # explicit tie, or mutual judges disagree
            entry["result"] = outcome
            if outcome == "tie":
                wins[(a, b)] = wins.get((a, b), 0) + 0.5
                wins[(b, a)] = wins.get((b, a), 0) + 0.5
            else:
                loser = b if outcome == a else a
                wins[(outcome, loser)] = wins.get((outcome, loser), 0) + 1
            log.append(entry)
            who = "双方互评" if mode == "mutual" else used[0]["name"]
            progress(f"{label} {cid}：{a} vs {b} → {'平局' if outcome == 'tie' else outcome}（评审：{who}）")
    return {"wins": wins, "log": log, "judged": sum(1 for x in log if x["result"] != "评审失败")}


# --------------------------------------------------------------------------- summary
def _price(model: dict, rec: dict) -> float | None:
    pin, pout = model.get("price_in"), model.get("price_out")   # currency per 1M tokens
    if pin is None or pout is None:
        return None
    return (rec["in_tokens"] * float(pin) + rec["out_tokens"] * float(pout)) / 1e6


def summarize(records: list[dict], models: list[dict], pair: dict | None = None) -> dict:
    out: dict[str, dict] = {}
    for m in models:
        allmine = [r for r in records if r["model_id"] == m["id"]]
        mine = [r for r in allmine if not r.get("skipped")]          # rate-limited calls do not count
        row: dict = {"dims": {}, "skipped": len(allmine) - len(mine)}
        for dim in ("text", "layout", "chart", "image"):
            rs = [r for r in mine if r["dimension"] == dim]
            if not rs:
                continue
            # average repeats per case first, so each case weighs the same
            per_case: dict[str, list[float]] = {}
            for r in rs:
                per_case.setdefault(r["task"], []).append(r["score"])
            case_scores = [statistics.mean(v) for v in per_case.values()]
            mean, lo, hi = stats.bootstrap_ci(case_scores)
            row["dims"][dim] = {"score": round(mean, 1), "lo": round(lo, 1), "hi": round(hi, 1),
                                "cases": {k: round(statistics.mean(v), 1) for k, v in per_case.items()},
                                "stdev_repeats": round(statistics.mean(
                                    [statistics.pstdev(v) for v in per_case.values() if len(v) > 1] or [0]), 1)}
        ok = [r for r in mine if not r["error"] and r["dimension"] != "image"]
        lat = sorted(r["latency"] for r in ok)
        row["median_latency"] = round(lat[len(lat) // 2], 2) if lat else None
        row["dims"]["speed"] = {"score": round(scoring.speed_score(lat), 1)}
        calls = [r for r in mine if r["dimension"] != "image"]
        row["calls"] = len(calls)
        row["errors"] = sum(1 for r in mine if r["error"])
        row["in_tokens"] = sum(r["in_tokens"] for r in calls)
        row["out_tokens"] = sum(r["out_tokens"] for r in calls)
        row["tokens_per_call"] = round((row["in_tokens"] + row["out_tokens"]) / max(1, len(calls)))
        costs = [_price(m, r) for r in calls]
        row["cost"] = round(sum(c for c in costs if c is not None), 4) if all(c is not None for c in costs) else None
        out[m["id"]] = row

    # pairwise judging blends into its dimension (25%): outline judging -> "text",
    # screenshot judging -> "layout". Older callers pass a single outline result.
    if pair and "wins" in pair:
        pair = {"text": pair}
    for dim, pr in (pair or {}).items():
        if not pr or not pr.get("judged"):
            continue
        ids = [m["id"] for m in models if dim in out[m["id"]]["dims"]]
        elo = stats.bradley_terry(ids, pr["wins"])
        pts = stats.win_rate_to_points(elo)
        for mid in ids:
            d = out[mid]["dims"][dim]
            d["rule_score"] = d["score"]
            d["elo"] = elo[mid]
            d["pairwise"] = pts[mid]
            shift = 0.25 * (pts[mid] - 50)          # 50 = average opponent, so no inflation overall
            clamp = lambda v: round(max(0.0, min(100.0, v)), 1)  # noqa: E731
            d["score"] = clamp(d["score"] + shift)
            d["lo"], d["hi"] = clamp(d["lo"] + shift), clamp(d["hi"] + shift)
            d["cases"] = {k: clamp(v + shift) for k, v in d["cases"].items()}

    # is the leader really ahead? paired bootstrap on per-case scores vs every other model
    for dim in QUALITY_DIMS:
        have = [mid for mid in out if dim in out[mid]["dims"]]
        if not have:
            continue
        if len(have) == 1:
            out[have[0]]["dims"][dim]["rank"] = "only"      # nothing to rank against
            continue
        leader = max(have, key=lambda mid: out[mid]["dims"][dim]["score"])
        lc = out[leader]["dims"][dim]["cases"]
        for mid in have:
            d = out[mid]["dims"][dim]
            if mid == leader:
                d["rank"] = "leader"
                continue
            keys = [k for k in lc if k in d["cases"]]
            sep = stats.separable([lc[k] for k in keys], [d["cases"][k] for k in keys])
            d["rank"] = "behind" if sep == 1 else "tied"
    return out


def summarize_cases(records: list[dict], models: list[dict]) -> list[dict]:
    """Summarize per-question spread so saturated questions are visible."""
    by_task: dict[str, dict[str, list[float]]] = {}
    meta = {c["id"]: c for c in ALL_CASES}
    for rec in records:
        if rec.get("skipped") or rec.get("error"):
            continue
        by_task.setdefault(rec["task"], {}).setdefault(rec["model_id"], []).append(float(rec.get("score", 0)))
    out = []
    for task, by_model in by_task.items():
        scores = {mid: round(statistics.mean(values), 1) for mid, values in by_model.items()}
        values = list(scores.values())
        if not values:
            continue
        case = meta.get(task, {})
        out.append({"task": task,
                    "dimension": next((r["dimension"] for r in records if r["task"] == task), ""),
                    "level": case.get("level", "standard"), "scores": scores,
                    "range": round(max(values) - min(values), 1),
                    "stdev": round(statistics.pstdev(values), 1),
                    "saturated": len(models) >= 2 and len(scores) == len(models)
                                 and all(value >= 98 for value in values)})
    return sorted(out, key=lambda item: item["task"])


JUDGING_TEXT = {
    "none": "只有 1 个模型，没有对手可比：只按规则评分（大纲、排版不加两两评审）",
    "third_party": "两两评审：每组由第三个模型当裁判，模型不会评自己",
    "mutual": "两两评审：没有第三个模型，改为双方互评——只有输的一方也认输才算胜，否则记平局，自评偏向只会变成平局",
    "mixed": "两两评审：有第三方裁判的组由第三方评，没有的组双方互评",
}


def _jobs(models: list[dict], repeats: int, dims: list[str] | None) -> list[tuple]:
    return [(m, dim, kind, case, rep) for m in models for rep in range(max(1, repeats))
            for dim, kind, case in task_list(m)
            if not (kind == "image" and rep) and (not dims or dim in dims)]


def plan(model_ids: list[str], judge_ids: list[str] | None = None, repeats: int = 1,
         pairwise: bool = True, dims: list[str] | None = None, visual: bool = True) -> dict:
    """What a run will do for this many models, before spending any quota."""
    all_models = config.list_models()
    models = [m for m in all_models if m["id"] in model_ids]
    ids = [m["id"] for m in models]
    jobs = _jobs(models, repeats, dims)
    judges = [m for m in all_models if m["id"] in (judge_ids or ids)]
    out = {"models": len(models), "task_calls": len(jobs),
           "calls_per_model": {m["name"]: sum(1 for j in jobs if j[0] is m) for m in models},
           "judging": {}, "judge_calls": 0, "lines": []}
    want = [("text", "outline", C.OUTLINE, judges)]
    if visual:
        want.append(("layout", "layout", C.LAYOUT, [j for j in judges if j.get("vision", True)]))
    for dim, kind, bank, pool in want:
        if not pairwise or (dims and dim not in dims):
            continue
        mode = judging_mode(ids, [j["id"] for j in pool])
        calls = 0
        if mode != "none":
            for i, _ in enumerate(bank):
                for a, b in schedule_pairs(ids, i):
                    third = any(j["id"] not in (a, b) for j in pool)
                    calls += 2 if third else 4
        out["judging"][dim] = {"mode": mode, "calls": calls}
        out["judge_calls"] += calls
    n = len(models)
    out["lines"].append(f"{n} 个模型，共 {len(jobs)} 次答题调用"
                        + (f"（每个模型约 {len(jobs) // n} 次）" if n else ""))
    if out["judging"] and all(j["mode"] == "none" for j in out["judging"].values()):
        out["lines"].append(JUDGING_TEXT["none"])
    for dim, j in out["judging"].items():
        if all(x["mode"] == "none" for x in out["judging"].values()):
            break
        name = "大纲" if dim == "text" else "排版截图"
        out["lines"].append(f"{name}：{JUDGING_TEXT[j['mode']]}" + (f"，约 {j['calls']} 次评审调用" if j["calls"] else ""))
    if n >= 5 and out["judging"]:
        out["lines"].append("模型较多：每道题只比一轮均衡配对（每个模型比 1–2 次），轮换覆盖全部组合，每个模型的评审开销不随人数增长")
    if n:
        out["lines"].append("开测前会先检查连接；连不上的模型自动排除，评审方式按实际参加的人数调整")
    return out


def preflight(models: list[dict], progress) -> tuple[list[dict], list[dict]]:
    """Ping every model in parallel. Unreachable ones are left out of the run so a single wrong
    key does not cost dozens of timeouts; the rest go ahead whatever their number."""
    if not models:
        return [], []
    with ThreadPoolExecutor(max_workers=min(8, len(models))) as ex:
        results = list(ex.map(ping, models))
    ok, bad = [], []
    for m, r in zip(models, results):
        if r["ok"]:
            ok.append(m)
        else:
            bad.append({"id": m["id"], "name": m["name"], "error": r.get("error", "")[:300]})
            progress(f"{m['name']} 连接失败，本次不参加测试：{r.get('error', '')[:120]}")
    return ok, bad


def run(model_ids: list[str], judge_ids: list[str] | None = None, progress=print, repeats: int = 1,
        pairwise: bool = True, dims: list[str] | None = None, visual: bool = True,
        check_connection: bool = True) -> dict:
    """Benchmark any number of models (1, 2, ... N) with one call.

    dims: only test these dimensions (e.g. ["layout"]); visual: judge layout screenshots pairwise;
    check_connection: ping first and leave unreachable models out."""
    all_models = config.list_models()
    models = [m for m in all_models if m["id"] in model_ids]
    if not models:
        raise ValueError("没有选中任何已接入的模型")
    excluded: list[dict] = []
    if check_connection:
        progress(f"检查 {len(models)} 个模型的连接…")
        models, excluded = preflight(models, progress)
        if not models:
            raise ValueError("所有选中的模型都连接失败，请检查 Key、接口地址和模型名称")
    ids = [m["id"] for m in models]
    jobs = _jobs(models, repeats, dims)
    progress(f"共 {len(models)} 个模型 × 约 {len(jobs) // max(1, len(models))} 道题"
             f"{f'（每题 {repeats} 次）' if repeats > 1 else ''}，开始测试…")
    records = []
    t0 = time.time()
    # interleave models so one slow provider does not block the others; 3 in flight per model
    jobs.sort(key=lambda j: (j[4], j[3]["id"], j[0]["id"]))
    with ThreadPoolExecutor(max_workers=max(1, min(12, len(models) * 3))) as ex:
        names = {m["id"]: m["name"] for m in models}
        for rec in ex.map(lambda j: _run_one(*j), jobs):
            records.append(rec)
            status = "限流跳过" if rec.get("skipped") else "失败" if rec["error"] else f"{rec['score']:.0f} 分"
            progress(f"{names[rec['model_id']]} · {rec['task']} · {status}")

    pair: dict[str, dict] = {}
    modes: dict[str, str] = {}
    reachable = {m["id"] for m in models} | {m["id"] for m in all_models if m["id"] not in model_ids}
    judges = [m for m in all_models if m["id"] in (judge_ids or ids) and m["id"] in reachable]
    if pairwise:
        if len(models) < 2:
            progress("只有 1 个模型：没有对手可比，大纲和排版只按规则评分")
        if any(r["kind"] == "outline" for r in records):
            modes["text"] = judging_mode(ids, [j["id"] for j in judges])
            if modes["text"] != "none":
                progress(f"开始大纲两两对比评审（{JUDGING_TEXT[modes['text']].split('：', 1)[-1]}）…")
                pair["text"] = pairwise_judging(records, models, judges, progress, kind="outline")
        # vision judges look at rendered screenshots; mark a model "vision": false to keep it out
        vjudges = [j for j in judges if j.get("vision", True)]
        if visual and any(r["kind"] == "layout" for r in records):
            modes["layout"] = judging_mode(ids, [j["id"] for j in vjudges])
            if modes["layout"] != "none":
                progress("开始排版截图视觉评审（把坐标渲染成图片，让能看图的模型比较）…")
                pair["layout"] = pairwise_judging(records, models, vjudges, progress, kind="layout")

    scores = summarize(records, models, pair)
    logs = [x for p in pair.values() for x in p.get("log", [])]
    case_stats = summarize_cases(records, models)
    result = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "version": 2, "bank_version": C.BANK_VERSION,
              "question_count": len(case_stats), "hard_count": sum(c.get("level") == "hard" for c in ALL_CASES),
              "case_stats": case_stats, "repeats": repeats,
              "duration": round(time.time() - t0, 1),
              "models": [config.public_model(m) for m in models],
              "excluded": excluded,
              "records": [{k: v for k, v in r.items() if k != "parsed"} for r in records],
              "pairwise": {"log": logs, "judged": sum(p.get("judged", 0) for p in pair.values()),
                           "by_dim": {d: p.get("judged", 0) for d, p in pair.items()},
                           "modes": modes},
              "scores": scores}
    history = config.load("benchmarks.json", [])
    history.append(result)
    config.save("benchmarks.json", history[-20:])
    _update_profiles(scores)
    progress(f"测试完成，用时 {result['duration']} 秒")
    return result


def _update_profiles(scores: dict) -> None:
    prof = config.load("profiles.json", {})
    for mid, row in scores.items():
        p = prof.setdefault(mid, {})
        for dim, d in row["dims"].items():
            p[dim] = d["score"]
            if "lo" in d:
                p[dim + "_ci"] = [d["lo"], d["hi"]]
        p["median_latency"] = row["median_latency"]
        p["tokens_per_call"] = row["tokens_per_call"]
        p["errors"] = row["errors"]
        p["calls"] = row["calls"]
    config.save("profiles.json", prof)


def ping(model: dict) -> dict:
    try:
        r = llm.chat(model, "[task:ping] 请只回复 pong", max_tokens=20, temperature=0, timeout=30)
        return {"ok": True, "latency": round(r.latency, 2), "reply": r.text[:80]}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


def selftest() -> list[tuple[str, float]]:
    """Score every reference answer. All must be 100, otherwise the scorer is wrong."""
    out = []
    for kind, bank in (("outline", C.OUTLINE), ("revise", C.REVISE), ("condense", C.CONDENSE),
                       ("chart", C.CHART), ("layout", C.LAYOUT)):
        for case in bank:
            out.append((case["id"], SCORERS[kind](case["reference"], case)[0]))
    return out


# --------------------------------------------------------------------------- routing
def route(dim: str, candidates: list[dict] | None = None, prefer: str = "balanced") -> dict | None:
    """Pick the model for a task.

    1. Keep models whose score is statistically tied with the best (CI overlap) and that
       failed less than 20% of calls.
    2. Among those, choose by preference: "quality" = highest score, "cheap" = fewest tokens
       per call, "fast" = lowest latency, "balanced" = score minus small cost/latency penalties.
    Without benchmark data, fall back to the first capable model.
    """
    prof = config.load("profiles.json", {})
    models = candidates if candidates is not None else config.list_models()
    if dim == "image":
        models = [m for m in models if m.get("can_image")]
    if not models:
        return None
    scored = []
    for m in models:
        p = prof.get(m["id"], {})
        if dim not in p:
            continue
        calls = max(1, p.get("calls") or 1)
        if (p.get("errors") or 0) / calls > 0.2:
            continue
        scored.append((m, p))
    if not scored:
        return models[0]
    best = max(scored, key=lambda t: t[1][dim])
    best_lo = best[1].get(dim + "_ci", [best[1][dim]] * 2)[0]
    tied = [(m, p) for m, p in scored if p.get(dim + "_ci", [p[dim]] * 2)[1] >= best_lo]
    if prefer == "quality":
        return max(tied, key=lambda t: t[1][dim])[0]
    if prefer == "cheap":
        return min(tied, key=lambda t: t[1].get("tokens_per_call") or 1e9)[0]
    if prefer == "fast":
        return min(tied, key=lambda t: t[1].get("median_latency") or 1e9)[0]
    max_tok = max((p.get("tokens_per_call") or 0) for _, p in tied) or 1
    max_lat = max((p.get("median_latency") or 0) for _, p in tied) or 1

    def utility(t):
        m, p = t
        return (p[dim] - 5 * (p.get("tokens_per_call") or 0) / max_tok
                - 5 * (p.get("median_latency") or 0) / max_lat)
    return max(tied, key=utility)[0]


def best_model_for(dim: str, candidates: list[dict] | None = None) -> dict | None:
    return route(dim, candidates)


def explain_route(dim: str, candidates: list[dict] | None = None) -> str:
    prof = config.load("profiles.json", {})
    m = route(dim, candidates)
    if not m:
        return "无可用模型"
    p = prof.get(m["id"], {})
    if dim not in p:
        return f"{m['name']}（还没有测试分数）"
    return f"{m['name']}（{p[dim]:.0f} 分，区间 {p.get(dim + '_ci', ['?', '?'])[0]}–{p.get(dim + '_ci', ['?', '?'])[1]}）"
