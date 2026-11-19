"""Benchmark: measure every connected model on the abilities a PPT needs.

Pipeline
  1. Every model answers the same question bank (cases.py), optionally several times
     (`repeats`) because LLM output varies between calls.
  2. Deterministic scorers (scoring.py) grade each answer and explain lost points.
     Numbers are fact-checked against the source material (facts.py).
  3. Quality that rules cannot capture is judged against the case's reference answer: another
     model sees the answer and the reference blind, as A and B, twice with the order swapped to
     cancel position bias. Models never judge their own answers. Because the yardstick is fixed,
     a score does not depend on which other models are in the run, and the cost per model is
     constant whether 2 or 20 models take part.
  4. Infrastructure failures (timeouts, 5xx, rate limits) are left out of the score, not counted
     as wrong answers.
  5. Per dimension we report the mean, a bootstrap confidence interval over cases, and which
     models are clearly behind another, with one permutation test over all pairs (stats.py) so
     the labels stay reliable with any number of models.
  6. Profiles store score, interval, per-case scores, cost and latency. Routing reruns the
     leaderboard's test on them, so both always agree.

Dimensions
  text    - outline writing (rules 75% + comparison with the reference 25%), revising, condensing
  chart   - picking, converting and computing the right numbers; refusing when there are none
  layout  - placing elements so nothing overlaps, everything fits, design asks are met
            (rules 75% + vision-model comparison of rendered screenshots with the reference 25%)
  image   - generating an illustration (image-capable endpoints only; success rate)
  speed   - median latency, log scale
"""
from __future__ import annotations

import base64
import json
import statistics
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

from . import cases as C
from . import config, generate, llm, render, scoring, stats

DIMENSIONS = {"text": "文字 / 大纲", "layout": "排版", "chart": "数据图表", "image": "配图", "speed": "速度"}
QUALITY_DIMS = ("text", "layout", "chart")
ALL_CASES = [c for bank in (C.OUTLINE, C.REVISE, C.CONDENSE, C.CHART, C.LAYOUT, C.IMAGE) for c in bank]


def case_bank(seed: str | None = "auto") -> dict[str, list[dict]]:
    """The questions for one run: the hand-checked bank plus a batch of generated cases.

    seed: "auto" (default) = this ISO week's batch, so runs in the same week are comparable;
    any other string = that batch; None = hand-checked bank only."""
    out = {"outline": list(C.OUTLINE), "revise": list(C.REVISE), "condense": list(C.CONDENSE),
           "chart": list(C.CHART), "layout": list(C.LAYOUT), "image": list(C.IMAGE)}
    if seed is not None:
        for kind, cases in generate.bank(generate.default_seed() if seed == "auto" else seed).items():
            out[kind] += cases
    return out


def _all(bank: dict[str, list[dict]]) -> list[dict]:
    return [c for cases in bank.values() for c in cases]

# kept for deck.py and older callers
SYS = C.SYS
OUTLINE_PROMPT = C.OUTLINE_PROMPT


def task_list(model: dict, bank: dict[str, list[dict]] | None = None) -> list[tuple[str, str, dict]]:
    """(dimension, kind, case) for one model."""
    bank = bank or case_bank(None)
    jobs = [("text", "outline", c) for c in bank["outline"]]
    jobs += [("text", "revise", c) for c in bank["revise"]]
    jobs += [("text", "condense", c) for c in bank["condense"]]
    jobs += [("chart", "chart", c) for c in bank["chart"]]
    jobs += [("layout", "layout", c) for c in bank["layout"]]
    if model.get("can_image"):
        jobs += [("image", "image", c) for c in bank["image"]]
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
        rec.update(skipped=True, skip_reason="rate_limit")
        rec["notes"] = ["账号限流，多次重试仍被拒绝，本题不计分：" + str(e)[:160]]
    except llm.ServiceError as e:
        # timeouts, dropped connections, 5xx: the provider or network failed, not the model
        rec.update(skipped=True, skip_reason="service")
        rec["notes"] = ["服务商或网络故障，多次重试仍失败，本题不计分：" + str(e)[:160]]
    except llm.ModelError as e:
        rec["error"] = str(e)
        rec["notes"] = [str(e)[:200]]
    except Exception as e:  # one bad answer must not crash the run
        rec["error"] = f"{type(e).__name__}: {e}"
        rec["notes"] = [rec["error"][:200]]
        traceback.print_exc()
    return rec


# --------------------------------------------------------------------------- judging against the reference
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


def judging_mode(model_ids: list[str], judge_ids: list[str]) -> str:
    """How answers will be judged against the reference answers:
    none     - no model has another model to judge it (one model, no extra judge): rules only
    anchored - every model is judged by some other model
    partial  - some models have no other judge (e.g. the only vision-capable model in the group)"""
    covered = [any(j != mid for j in judge_ids) for mid in model_ids]
    if not any(covered):
        return "none"
    return "anchored" if all(covered) else "partial"


def _verdict_pair(judge: dict, kind: str, case: dict, ra: dict, rb: dict) -> list[str] | None:
    """One judge, asked twice with A/B swapped. Returns both verdicts ("A", "B" or "tie", already
    mapped back to the unswapped order) or None on failure."""
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
    return verdicts


JUDGE_POINTS = {"win": 100.0, "tie": 50.0, "loss": 0.0}

# --------------------------------------------------------------------------- judge calibration
# Before a model may judge, it must tell a reference answer from a deliberately worse copy of it
# (blind, both orders). A judge that prefers the worse copy, or cannot tell them apart at all
# (e.g. it always picks the first one), is left out of judging for that dimension.
CONTROLS_PER_JUDGE = 2
_FAKE_AMOUNTS = ("63.9 亿元", "9.47 亿元", "5.83 亿元", "1,234 万元", "27.6 亿元")


def degrade(kind: str, case: dict) -> dict:
    """A copy of the reference answer that is clearly worse in ways the judge prompt names."""
    import copy

    from . import facts
    ans = copy.deepcopy(case["reference"])
    if kind == "outline":
        src = facts.Source(case["material"])
        fakes = [a for a in _FAKE_AMOUNTS if src.unsupported(a)]
        body = [sl for sl in ans["slides"][1:] if sl.get("bullets")]
        for i, sl in enumerate(body[:3]):              # invented numbers replace real key facts
            fake = fakes[i % len(fakes)].replace(" ", "")
            sl["bullets"][0] = f"新增合同额{fake}，表现超出预期" if i % 2 == 0 else f"利润预计达到{fake}"
        return ans
    els = ans["elements"]
    texts = [e for e in els if case["elements"].get(e["role"]) is not None and e["role"] != "title"]
    for e in texts:                                     # text needs twice the room it gets: spills in red
        need = scoring.text_height(case["elements"][e["role"]], e["w"], float(e["font_size"]))
        e["h"] = round(min(e["h"], need) * 0.5, 2)
    others = [e for e in els if e["role"] != "title"]
    if len(others) >= 2:                                # and two blocks overlap
        others[1]["x"], others[1]["y"] = others[0]["x"] + 0.4, others[0]["y"] + 0.3
    return ans


def control_cases(kind: str) -> list[dict]:
    if kind == "outline":
        return [c for c in C.OUTLINE if c.get("check_numbers", True) and c["must_numbers"]]
    return list(C.LAYOUT)


def calibrate(judges: list[dict], kind: str, progress) -> dict[str, dict]:
    """Run the control comparisons. Returns {judge_id: {"passed": bool, "controls": [...]}}.
    A judge passes when it never prefers the worse copy and gets at least one control right."""
    pool = control_cases(kind)
    jobs = []
    for j_index, judge in enumerate(judges):
        for t in range(CONTROLS_PER_JUDGE):
            jobs.append((judge, pool[(j_index * CONTROLS_PER_JUDGE + t) % len(pool)]))

    def ask(job):
        judge, case = job
        votes = _verdict_pair(judge, kind, case, {"parsed": case["reference"]}, {"parsed": degrade(kind, case)})
        if votes is None:
            outcome = "failed"
        elif votes == ["A", "A"]:
            outcome = "correct"
        elif votes == ["B", "B"]:
            outcome = "wrong"
        else:
            outcome = "unsure"
        return judge, {"case": case["id"], "votes": votes, "outcome": outcome}

    out: dict[str, dict] = {j["id"]: {"controls": []} for j in judges}
    with ThreadPoolExecutor(max_workers=4) as ex:
        for judge, ctl in ex.map(ask, jobs):
            out[judge["id"]]["controls"].append(ctl)
    label = "大纲" if kind == "outline" else "排版截图"
    for judge in judges:
        rec = out[judge["id"]]
        outcomes = [c["outcome"] for c in rec["controls"]]
        rec["passed"] = "wrong" not in outcomes and "correct" in outcomes
        progress(f"{label}裁判校验 {judge['name']}：{'通过' if rec['passed'] else '未通过，本次不当裁判'}"
                 f"（对照题 {'、'.join({'correct': '判对', 'wrong': '判反', 'unsure': '分不清', 'failed': '调用失败'}[o] for o in outcomes)}）")
    return out


def reference_judging(records: list[dict], models: list[dict], judges: list[dict], progress,
                      kind: str = "outline", cases: list[dict] | None = None) -> dict:
    """Compare every answer with the case's hand-checked reference answer, blind.

    The judge sees the model's answer and the reference as "A" and "B" (it is not told which is
    which), twice with the order swapped; only two matching verdicts count, otherwise it is a tie.
    The judge is always a model other than the one being judged (least-loaded first, the others as
    backups), so it works the same for 2 models or 20 and costs 2 calls per answer.
    Because the yardstick is fixed, the result does not depend on who else is in the run.
    Returns {"results": {model_id: {case_id: points}}, "log": [...], "judged": n}."""
    case_map = {c["id"]: c for c in (cases if cases is not None else (C.OUTLINE if kind == "outline" else C.LAYOUT))}
    answers = [r for r in records if r["kind"] == kind and r.get("parsed") and r["rep"] == 0
               and r["task"] in case_map]
    answers.sort(key=lambda r: (r["task"], r["model_id"]))
    load = {j["id"]: 0 for j in judges}
    jobs = []
    for r in answers:
        eligible = [j for j in judges if j["id"] != r["model_id"]]
        if not eligible:
            continue
        eligible.sort(key=lambda j: load[j["id"]])          # stable: ties keep config order
        load[eligible[0]["id"]] += 1
        jobs.append((r, eligible))
    results: dict[str, dict[str, float]] = {}
    log: list[dict] = []
    if not jobs:
        return {"results": results, "log": log, "judged": 0}

    def ask(job):
        r, order = job
        ref = {"parsed": case_map[r["task"]]["reference"]}
        for judge in order:                     # same judge for both orders; next one if it fails
            votes = _verdict_pair(judge, kind, case_map[r["task"]], r, ref)
            if votes is not None:
                return r, judge, votes
        return r, order[0], None

    names = {m["id"]: m["name"] for m in models}
    label = "排版截图评审" if kind == "layout" else "大纲评审"
    with ThreadPoolExecutor(max_workers=4) as ex:
        for r, judge, votes in ex.map(ask, jobs):
            entry = {"case": r["task"], "model": r["model_id"], "kind": kind, "judge": judge["id"], "votes": votes}
            if votes is None:
                entry["result"] = "评审失败"
            else:
                v1, v2 = votes
                entry["result"] = ("win" if v1 == "A" else "loss") if v1 == v2 and v1 != "tie" else "tie"
                results.setdefault(r["model_id"], {})[r["task"]] = JUDGE_POINTS[entry["result"]]
                word = {"win": "胜过参考答案", "tie": "与参考答案持平", "loss": "不如参考答案"}[entry["result"]]
                progress(f"{label} {r['task']}：{names.get(r['model_id'], r['model_id'])} {word}（评审：{judge['name']}）")
            log.append(entry)
    return {"results": results, "log": log, "judged": sum(1 for x in log if x["result"] != "评审失败")}


# --------------------------------------------------------------------------- summary
def _price(model: dict, rec: dict) -> float | None:
    pin, pout = model.get("price_in"), model.get("price_out")   # currency per 1M tokens
    if pin is None or pout is None:
        return None
    return (rec["in_tokens"] * float(pin) + rec["out_tokens"] * float(pout)) / 1e6


JUDGE_WEIGHT = 0.25     # share of a judged case's score that comes from the comparison with the reference


def _clamp(v: float) -> float:
    return round(max(0.0, min(100.0, v)), 1)


def summarize(records: list[dict], models: list[dict], judged: dict | None = None) -> dict:
    """Per-model scores. judged[dim]["results"][model][case] = points vs the reference
    (100 beat it, 50 as good, 0 worse). On a judged case the score moves by
    JUDGE_WEIGHT * (points - 50): matching the reference leaves the rule score unchanged, so runs
    with and without judging, and with any set of opponents, stay on the same scale."""
    judged = judged or {}
    out: dict[str, dict] = {}
    for m in models:
        allmine = [r for r in records if r["model_id"] == m["id"]]
        mine = [r for r in allmine if not r.get("skipped")]          # infra failures do not count
        skipped = [r for r in allmine if r.get("skipped")]
        row: dict = {"dims": {}, "skipped": len(skipped),
                     "skipped_service": sum(1 for r in skipped if r.get("skip_reason") == "service"),
                     "skipped_rate_limit": sum(1 for r in skipped if r.get("skip_reason") != "service"),
                     "unscored_rate": round(len(skipped) / max(1, len(allmine)), 3)}
        for dim in ("text", "layout", "chart", "image"):
            rs = [r for r in mine if r["dimension"] == dim]
            if not rs:
                continue
            # average repeats per case first, so each case weighs the same
            per_case: dict[str, list[float]] = {}
            for r in rs:
                per_case.setdefault(r["task"], []).append(r["score"])
            rule_cases = {k: round(statistics.mean(v), 1) for k, v in per_case.items()}
            vs_ref = ((judged.get(dim) or {}).get("results") or {}).get(m["id"], {})
            cases = {k: _clamp(v + JUDGE_WEIGHT * (vs_ref[k] - 50)) if k in vs_ref else v
                     for k, v in rule_cases.items()}
            mean, lo, hi = stats.bootstrap_ci(list(cases.values()))
            d = {"score": round(mean, 1), "lo": round(lo, 1), "hi": round(hi, 1), "cases": cases,
                 "stdev_repeats": round(statistics.mean(
                     [statistics.pstdev(v) for v in per_case.values() if len(v) > 1] or [0]), 1)}
            if vs_ref:
                d["rule_score"] = round(statistics.mean(rule_cases.values()), 1)
                d["vs_reference"] = round(statistics.mean(vs_ref.values()), 1)   # 50 = as good as the reference
                d["judged_cases"] = len(vs_ref)
            row["dims"][dim] = d
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

    for dim in QUALITY_DIMS:
        rank_dimension({mid: row["dims"][dim] for mid, row in out.items() if dim in row["dims"]})
    return out


def rank_dimension(dims: dict[str, dict]) -> None:
    """Label each model "leader", "tied" (not clearly behind anyone) or "behind" (clearly worse
    than at least one other model), with one test over all pairs at once (stats.behind_flags),
    so the labels stay trustworthy however many models are compared."""
    if not dims:
        return
    if len(dims) == 1:
        next(iter(dims.values()))["rank"] = "only"           # nothing to rank against
        return
    flags = stats.behind_flags({mid: d["cases"] for mid, d in dims.items()})
    leader = max(dims, key=lambda mid: dims[mid]["score"])
    for mid, d in dims.items():
        d["rank"] = "leader" if mid == leader else "behind" if flags[mid] else "tied"


def summarize_cases(records: list[dict], models: list[dict], cases: list[dict] | None = None) -> list[dict]:
    """Summarize per-question spread so saturated questions are visible."""
    by_task: dict[str, dict[str, list[float]]] = {}
    meta = {c["id"]: c for c in (cases or ALL_CASES)}
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
                    "level": case.get("level", "standard"), "generated": "generated" in case, "scores": scores,
                    "range": round(max(values) - min(values), 1),
                    "stdev": round(statistics.pstdev(values), 1),
                    "saturated": len(models) >= 2 and len(scores) == len(models)
                                 and all(value >= 98 for value in values)})
    return sorted(out, key=lambda item: item["task"])


JUDGING_TEXT = {
    "none": "没有其他模型当裁判：只按规则评分（模型不评自己的答案）",
    "anchored": "对比参考答案：每份答案与人工参考答案盲比，由另一个模型当裁判，分数不受同场对手影响",
    "partial": "对比参考答案：由另一个模型当裁判；个别模型找不到其他裁判，只按规则评分",
}


def _jobs(models: list[dict], repeats: int, dims: list[str] | None, bank: dict) -> list[tuple]:
    return [(m, dim, kind, case, rep) for m in models for rep in range(max(1, repeats))
            for dim, kind, case in task_list(m, bank)
            if not (kind == "image" and rep) and (not dims or dim in dims)]


def _judge_pools(judges: list[dict], visual: bool) -> list[tuple[str, str, list[dict]]]:
    pools = [("text", "outline", judges)]
    if visual:     # screenshots need a vision model; mark a model "vision": false to keep it out
        pools.append(("layout", "layout", [j for j in judges if j.get("vision", True)]))
    return pools


def plan(model_ids: list[str], judge_ids: list[str] | None = None, repeats: int = 1,
         pairwise: bool = True, dims: list[str] | None = None, visual: bool = True,
         seed: str | None = "auto") -> dict:
    """What a run will do for this many models, before spending any quota."""
    all_models = config.list_models()
    models = [m for m in all_models if m["id"] in model_ids]
    ids = [m["id"] for m in models]
    bank = case_bank(seed)
    jobs = _jobs(models, repeats, dims, bank)
    judges = [m for m in all_models if m["id"] in (judge_ids or ids)]
    out = {"models": len(models), "task_calls": len(jobs),
           "calls_per_model": {m["name"]: sum(1 for j in jobs if j[0] is m) for m in models},
           "judging": {}, "judge_calls": 0, "lines": []}
    for dim, kind, pool in _judge_pools(judges, visual):
        if not pairwise or (dims and dim not in dims):
            continue
        pool_ids = [j["id"] for j in pool]
        mode = judging_mode(ids, pool_ids)
        calls = 2 * len(bank[kind]) * sum(1 for mid in ids if any(j != mid for j in pool_ids))
        if mode != "none":
            calls += 2 * CONTROLS_PER_JUDGE * len(pool_ids)          # calibration controls
        out["judging"][dim] = {"mode": mode, "calls": calls}
        out["judge_calls"] += calls
    n = len(models)
    n_gen = sum(1 for c in _all(bank) if "generated" in c)
    out["seed"] = generate.default_seed() if seed == "auto" else seed
    out["lines"].append(f"{n} 个模型，共 {len(jobs)} 次答题调用"
                        + (f"（每个模型约 {len(jobs) // n} 次）" if n else ""))
    if n_gen:
        out["lines"].append(f"题目：人工题库 + 本批 {n_gen} 道参数化新题（批次 {out['seed']}，数字和内容每批不同，无法提前背题）")
    if out["judging"] and all(j["mode"] == "none" for j in out["judging"].values()):
        out["lines"].append(JUDGING_TEXT["none"])
    else:
        for dim, j in out["judging"].items():
            name = "大纲" if dim == "text" else "排版截图"
            out["lines"].append(f"{name}：{JUDGING_TEXT[j['mode']]}"
                                + (f"，约 {j['calls']} 次评审调用（含每个裁判 {CONTROLS_PER_JUDGE} 道对照题校验；每个模型的开销固定，不随人数增长）" if j["calls"] else ""))
    if n:
        out["lines"].append("开测前会先检查连接；连不上的模型自动排除。网络或服务商故障的题不计分，不算模型答错")
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


UNSCORED_WARN = 0.2     # warn (and keep out of routing) when more than this share of calls went unscored


def run(model_ids: list[str], judge_ids: list[str] | None = None, progress=print, repeats: int = 1,
        pairwise: bool = True, dims: list[str] | None = None, visual: bool = True,
        check_connection: bool = True, seed: str | None = "auto") -> dict:
    """Benchmark any number of models (1, 2, ... N) with one call.

    dims: only test these dimensions (e.g. ["layout"]); visual: judge layout screenshots;
    pairwise: compare outlines / layouts with the reference answers using another model as judge;
    check_connection: ping first and leave unreachable models out;
    seed: batch of generated questions ("auto" = this week's, None = hand-checked bank only)."""
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
    seed = generate.default_seed() if seed == "auto" else seed
    bank = case_bank(seed)
    jobs = _jobs(models, repeats, dims, bank)
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
            status = ("限流，不计分" if rec.get("skip_reason") == "rate_limit" else
                      "网络/服务商故障，不计分" if rec.get("skipped") else
                      "失败" if rec["error"] else f"{rec['score']:.0f} 分")
            progress(f"{names[rec['model_id']]} · {rec['task']} · {status}")

    judged: dict[str, dict] = {}
    modes: dict[str, str] = {}
    reachable = set(ids) | {m["id"] for m in all_models if m["id"] not in model_ids}
    judges = [m for m in all_models if m["id"] in (judge_ids or ids) and m["id"] in reachable]
    calibration: dict[str, dict] = {}
    if pairwise:
        for dim, kind, pool in _judge_pools(judges, visual):
            if not any(r["kind"] == kind for r in records):
                continue
            label = "大纲" if dim == "text" else "排版截图"
            if judging_mode(ids, [j["id"] for j in pool]) == "none":
                modes[dim] = "none"
                progress(f"{label}：{JUDGING_TEXT['none']}")
                continue
            progress(f"{label}裁判校验：每个裁判先比 {CONTROLS_PER_JUDGE} 道对照题（参考答案 vs 故意改差的版本）…")
            calibration[dim] = calibrate(pool, kind, progress)
            pool = [j for j in pool if calibration[dim][j["id"]]["passed"]]
            modes[dim] = judging_mode(ids, [j["id"] for j in pool])
            if modes[dim] == "none":
                progress(f"{label}：没有裁判通过校验，只按规则评分")
                continue
            progress(f"开始{label}评审：与人工参考答案盲比，正反各问一次…")
            judged[dim] = reference_judging(records, models, pool, progress, kind=kind, cases=bank[kind])
            for jid, rec in calibration[dim].items():     # how often each judge agreed with itself
                votes = [x["votes"] for x in judged[dim]["log"] if x["judge"] == jid and x["votes"]]
                if votes:
                    rec["consistency"] = round(sum(v[0] == v[1] for v in votes) / len(votes), 2)

    scores = summarize(records, models, judged)
    for mid, row in scores.items():
        if row["unscored_rate"] > UNSCORED_WARN:
            progress(f"注意：{names[mid]} 有 {row['skipped']} 题因网络/限流没有计分，它的分数只基于剩下的题，可信度较低")
    logs = [x for p in judged.values() for x in p.get("log", [])]
    case_stats = summarize_cases(records, models, _all(bank))
    asked = {r["task"] for r in records}
    result = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "version": 3, "bank_version": C.BANK_VERSION,
              "seed": seed, "generated_count": sum(1 for c in _all(bank) if "generated" in c and c["id"] in asked),
              "question_count": len(case_stats),
              "hard_count": sum(c.get("level") == "hard" for c in _all(bank) if c["id"] in asked),
              "case_stats": case_stats, "repeats": repeats,
              "duration": round(time.time() - t0, 1),
              "models": [config.public_model(m) for m in models],
              "excluded": excluded,
              "records": [{k: v for k, v in r.items() if k != "parsed"} for r in records],
              "judging": {"log": logs, "judged": sum(p.get("judged", 0) for p in judged.values()),
                          "by_dim": {d: p.get("judged", 0) for d, p in judged.items()},
                          "modes": modes, "weight": JUDGE_WEIGHT, "calibration": calibration},
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
            if "cases" in d:
                p[dim + "_cases"] = d["cases"]          # routing re-runs the leaderboard's test on these
        p["median_latency"] = row["median_latency"]
        p["tokens_per_call"] = row["tokens_per_call"]
        p["errors"] = row["errors"]
        p["calls"] = row["calls"]
        p["unscored_rate"] = row.get("unscored_rate", 0)
    config.save("profiles.json", prof)


def explain_error(msg: str) -> str:
    """Turn a raw connection error into advice a user can act on."""
    m = msg.lower()
    if msg.startswith(("HTTP 401", "HTTP 403")) and "agent proxy" not in m or "invalid api key" in m or "authentication" in m:
        return "Key 无效、已过期或没有这个模型的权限，请检查 Key"
    if msg.startswith("HTTP 404") or "model_not_found" in m or "does not exist" in m or "no such model" in m:
        return "找不到这个模型，请检查模型名称和接口地址"
    if msg.startswith("HTTP 402") or "insufficient" in m or "balance" in m or "quota" in m or "余额" in msg:
        return "账户余额或额度不足"
    if "403 forbidden (agent proxy" in m or "tunnel connection failed" in m:
        return "当前网络不允许访问这个服务商"
    if "超时" in msg or "timed out" in m or "连接失败" in msg:
        return "连不上接口地址，请检查网络或 base_url"
    if "base_url" in msg:
        return "请填写接口地址 base_url"
    return ""


def ping(model: dict) -> dict:
    try:
        r = llm.chat(model, "[task:ping] 请只回复 pong", max_tokens=20, temperature=0, timeout=30)
        return {"ok": True, "latency": round(r.latency, 2), "reply": r.text[:80]}
    except Exception as e:
        err = str(e)[:300]
        hint = explain_error(err)
        out = {"ok": False, "error": f"{hint}（{err[:160]}）" if hint else err}
        if hint.startswith("找不到这个模型"):
            names = llm.available_models(model)
            if names:
                out["available_models"] = names[:40]
                out["error"] = f"找不到模型 {model.get('model')}；这个 Key 可用的有：{'、'.join(names[:12])}" + \
                    ("等" if len(names) > 12 else "")
        return out


def selftest(seed: str | None = "auto") -> list[tuple[str, float]]:
    """Score every reference answer, including this batch's generated ones. All must be 100,
    otherwise the scorer (or a generator) is wrong."""
    bank = case_bank(seed)
    return [(case["id"], SCORERS[kind](case["reference"], case)[0])
            for kind in ("outline", "revise", "condense", "chart", "layout") for case in bank[kind]]


# --------------------------------------------------------------------------- routing
def contenders(dim: str, scored: list[tuple[dict, dict]]) -> list[tuple[dict, dict]]:
    """Models not clearly behind any other on `dim`: the same test the leaderboard uses, so the
    deck never goes to a model the leaderboard calls "behind"."""
    if len(scored) < 2:
        return scored
    if all(p.get(dim + "_cases") for _, p in scored):
        flags = stats.behind_flags({m["id"]: p[dim + "_cases"] for m, p in scored}, n=500)
        return [(m, p) for m, p in scored if not flags[m["id"]]]
    # profiles from older versions have no per-case scores: fall back to interval overlap
    best = max(scored, key=lambda t: t[1][dim])
    best_lo = best[1].get(dim + "_ci", [best[1][dim]] * 2)[0]
    return [(m, p) for m, p in scored if p.get(dim + "_ci", [p[dim]] * 2)[1] >= best_lo]


def route(dim: str, candidates: list[dict] | None = None, prefer: str = "balanced") -> dict | None:
    """Pick the model for a task.

    1. Drop models that failed, or went unscored (network / rate limits), on more than 20% of calls.
    2. Keep the models that are not clearly behind any other (see `contenders`).
    3. Among those, choose by preference: "quality" = highest score, "cheap" = fewest tokens
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
        if (p.get("errors") or 0) / calls > 0.2 or (p.get("unscored_rate") or 0) > UNSCORED_WARN:
            continue
        scored.append((m, p))
    if not scored:
        return models[0]
    tied = contenders(dim, scored) or scored
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
