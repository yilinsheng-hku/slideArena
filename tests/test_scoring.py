"""Unit tests for the scoring methodology. Run:  python tests/test_scoring.py

These guard the two properties that make the benchmark trustworthy:
  1. a correct answer always gets full marks (no false penalties), and
  2. each typical mistake is detected and costs points.
"""
from __future__ import annotations

import contextlib
import copy
import io
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image  # noqa: E402

from slidearena import benchmark, llm, render  # noqa: E402
from slidearena import cases as C  # noqa: E402
from slidearena import facts as F  # noqa: E402
from slidearena import scoring as S  # noqa: E402
from slidearena import stats as T  # noqa: E402

FAILED = []


def check(cond, msg):
    print(("PASS  " if cond else "FAIL  ") + msg)
    if not cond:
        FAILED.append(msg)


# ---------------------------------------------------------------- 1. references score 100
for cid, s in benchmark.selftest():
    check(s == 100, f"参考答案满分：{cid}（{s}）")

revise_cases = {case["id"]: case for case in C.REVISE}
for revise_case in C.REVISE:
    score, _, _ = S.score_revise(revise_case["reference"], revise_case)
    check(score == 100, f"大纲改错参考答案满分：{revise_case['id']}（{score}）")
    flawed_score = S.score_revise(revise_case["flawed"], revise_case)[0]
    check(flawed_score <= 40, f"未修正错误的大纲得分不超过 40：{revise_case['id']}（{flawed_score}）")

review_fix_one = copy.deepcopy(revise_cases["revise-review"]["flawed"])
review_fix_one["slides"][1]["bullets"][0] = review_fix_one["slides"][1]["bullets"][0].replace("18.5", "17.2")
fix_one_score, fix_one_parts, _ = S.score_revise(review_fix_one, revise_cases["revise-review"])
check(abs(fix_one_parts["错误修正"] - 50 / 3) < 0.1,
      f"只修正错误 1 时获得约 50/3 修正分（{fix_one_parts['错误修正']}，总分 {fix_one_score}）")

# ---------------------------------------------------------------- 2. fact checking
SRC = F.Source(C.OUTLINE[0]["material"])
for t in ["Q2环比增长18.4%", "前三季度累计44.5亿元", "华东占Q3营收41.3%", "毛利率下降2.7个百分点",
          "同比增长31.3%", "71,000万元", "灵犀占Q3营收19.8%", "Q3比Q1多4.7亿"]:
    check(not SRC.unsupported(t), f"正确推算不误报：{t}")
for t in ["人力成本5.3亿元", "净利润率12.734567%", "员工规模1,580人"]:
    check(bool(SRC.unsupported(t)), f"编造数字被发现：{t}")
check(SRC.classify(F.q("41%")) in ("supported", "unverifiable"), "粗精度数字不会被误判为编造")
far_case = next(c for c in C.OUTLINE if c["id"] == "outline-hard-reconciliation")
far_source = F.Source(far_case["material"])
check(far_source.classify(F.q("7.1%")) == "unverifiable" and
      not far_source.unsupported("研发投入占营收约7.1%"),
      "相距较远且单位不同的6800万/9.6亿比例标为无法严格核实，不误扣分")
check(S.faithfulness("研发投入占营收约7.1%", far_case["material"], 30, 12)[0] == 30,
      "合理的远距离百分比推算保留数字可信满分")
check(SRC.classify(F.q("12.7%")) in ("unsupported", "unverifiable"),
      "随机编造的比例不能被标为已核实 supported")
check(far_source.classify(F.q("54万元")) == "unsupported",
      "百分比放宽不适用于编造的绝对金额")
rng = random.Random(3)
fake = [f"{rng.randint(10, 999) / 10}%" for _ in range(2000)]
rate = sum(1 for x in fake if SRC.classify(F.q(x)) == "supported") / len(fake)
check(rate < 0.15, f"随机编造的一位小数百分比，误放行率 {rate:.1%} < 15%")
fake = [f"{rng.randint(10, 300) / 10}亿" for _ in range(2000)]
rate = sum(1 for x in fake if SRC.classify(F.q(x)) == "supported") / len(fake)
check(rate < 0.15, f"随机编造的一位小数金额，误放行率 {rate:.1%} < 15%")

# ---------------------------------------------------------------- 3. mistakes cost points
oc = C.OUTLINE[0]
r = copy.deepcopy(oc["reference"])
r["slides"][3]["bullets"][1] = "人力成本5.3亿元，同比增长41.5%"
s, parts, _ = S.score_outline(r, oc)
check(parts["数字可信"] < 30 and s < 90, f"大纲编造数字扣分（{s}）")
r = copy.deepcopy(oc["reference"])
r["slides"][4]["bullets"] = ["新产品表现不错", "占比提升", "成为增长引擎"]
s, parts, _ = S.score_outline(r, oc)
check(parts["关键信息覆盖"] < 35, f"大纲漏掉关键信息扣分（{s}）")
r = copy.deepcopy(oc["reference"])
r["slides"].append({"title": "谢谢", "bullets": ["欢迎提问"], "kind": "bullets"})
check(S.score_outline(r, oc)[1]["格式"] < 35, "大纲页数不对扣分")

cc = C.CONDENSE[0]
s, parts, _ = S.score_condense({"title": "客服情况", "bullets": ["工单很多", "响应变快", "满意度提升"]}, cc)
check(parts["关键数字保留"] == 0, f"压缩时丢掉全部数字，覆盖分为 0（{s}）")

ch = {c["id"]: c for c in C.CHART}
check(S.score_chart({"chart_type": "bar", "categories": ["华东", "华南", "华北", "西部"],
                     "series": [{"values": [71000, 3.2, 28500, 1.9]}]}, ch["chart-units"])[0] < 80, "单位没换算扣分")
check(S.score_chart({"chart_type": "column", "categories": ["Q1", "Q2", "Q3", "Q4", "去年"],
                     "series": [{"values": [12.5, 14.8, 17.2, 19.6, 48.3]}]}, ch["chart-quarter"])[0] < 100, "混入干扰数字扣分")
check(S.score_chart({"chart_type": "pie", "categories": ["线上", "门店", "经销"],
                     "series": [{"values": [48, 29, 33]}]}, ch["chart-share"])[0] < 100, "剩余占比算错扣分")
check(S.score_chart({"chart_type": "line", "categories": ["2024", "2025", "2026"],
                     "series": [{"values": [10, 13, 16.9]}]}, ch["chart-growth"])[0] <= 40, "该算增长率却直接抄营收，扣分")
check(S.score_chart({"chart_type": "column", "categories": ["上半年"], "series": [{"values": [80]}]},
                    ch["chart-nodata"])[0] == 0, "资料里没数据却画图，0 分")
check(S.score_chart({"chart_type": "column", "categories": ["Q1（实际）", "Q2", "Q3", "Q4（预计）"],
                     "series": [{"values": [12.5, 14.8, 17.2, 19.6]}],
                     "takeaway": ch["chart-quarter"]["reference"]["takeaway"]}, ch["chart-quarter"])[0] == 100,
      "标签里的括号说明不扣分")
check(S.score_chart({"chart_type": "bar", "categories": ["华东区", "华南区", "华北区", "西部地区"],
                     "series": [{"values": [7.1, 3.2, 2.85, 1.9]}],
                     "takeaway": ch["chart-units"]["reference"]["takeaway"]}, ch["chart-units"])[0] == 100,
      "“华东区”与“华东”视为同一分类")

for chart_case in C.CHART:
    if not chart_case.get("skip"):
        take_score, _ = S._check_takeaway(chart_case["reference"].get("takeaway"),
                                          [series["values"] for series in chart_case["reference"]["series"]],
                                          chart_case["reference"].get("unit", ""))
        check(take_score == 10, f"正确图表结论得 10 分：{chart_case['id']}")

trend_case = {"values": [20, 15, 10], "categories": ["Q1", "错项", "Q3"], "good_types": ["line"]}
trend_answer = {"chart_type": "line", "categories": ["Q1", "Q2", "Q3"],
                "series": [{"values": [20, 15, 10]}], "takeaway": "营收持续增长"}
trend_score, _, trend_notes = S.score_chart(trend_answer, trend_case)
check(S._check_takeaway("营收持续增长", [[20, 15, 10]], "")[0] == 5 and trend_score < 90
      and any("整体下降" in note for note in trend_notes), "下降数据却称持续增长，结论趋势分为 0")
unsupported_take, _ = S._check_takeaway("Q3营收17.2亿", [[12.5, 14.8, 16.9]], "亿元")
check(unsupported_take <= 5, "结论编造图表中不存在的数字，数字依据分为 0")
check(S._check_takeaway("", [[12.5, 14.8, 16.9]], "亿元")[0] == 0, "空 takeaway 的结论准确分为 0")

lc = {c["id"]: c for c in C.LAYOUT}


def has_overflow_red(png):
    with Image.open(io.BytesIO(png)) as image:
        return any(r > 180 and g < 90 and b < 90 for r, g, b in image.convert("RGB").getdata())


for case in C.LAYOUT:
    png = render.render_layout(case["reference"], case)
    check(not has_overflow_red(png), f"参考排版渲染没有文字溢出：{case['id']}")

short_title = copy.deepcopy(lc["layout-chart"]["reference"])
title = next(e for e in short_title["elements"] if e["role"] == "title")
title["h"] = 0.1
_, parts, notes = S.score_layout(short_title, lc["layout-chart"])
check(parts["文字放得下"] < 25 and any("title 文字超出" in n for n in notes), "规则判定过矮标题框溢出")
check(has_overflow_red(render.render_layout(short_title, lc["layout-chart"])), "渲染将过矮标题标红")

# Text-fit points now decline with the amount of overflow instead of dropping to zero.
for overflow, expected in ((0.05, 23.0), (0.30, 10.0), (0.60, 0.0)):
    sample = copy.deepcopy(lc["layout-chart"]["reference"])
    for element in sample["elements"]:
        if element["role"] not in ("title", "body"):
            continue
        paras = lc["layout-chart"]["elements"][element["role"]]
        need = S.text_height(paras, element["w"], element["font_size"])
        element["h"] = need / (1 + overflow) - S.TEXT_FIT_TOLERANCE_IN
    fit_score = S.score_layout(sample, lc["layout-chart"])[1]["文字放得下"]
    check((fit_score <= expected + 1.0 and fit_score >= expected - 1.0),
          f"文字超出 {overflow:.0%} 时按比例扣分（{fit_score:.1f}）")

saved_fonts = render._FONTS
saved_font_cache = render._font_cache.copy()
saved_default_flag, saved_warning_flag = render._using_default_font, render._warned_missing_font
render._FONTS = []
render._font_cache.clear()
render._using_default_font = False
render._warned_missing_font = False
font_warning = io.StringIO()
with contextlib.redirect_stdout(font_warning):
    render.render_layout(lc["layout-chart"]["reference"], lc["layout-chart"])
    render.render_layout(lc["layout-chart"]["reference"], lc["layout-chart"])
check(font_warning.getvalue().count("警告：") == 1, "缺少中文字体时回退成功且只警告一次")
render._FONTS = saved_fonts
render._font_cache.clear()
render._font_cache.update(saved_font_cache)
render._using_default_font, render._warned_missing_font = saved_default_flag, saved_warning_flag

r = copy.deepcopy(lc["layout-dense"]["reference"])
r["elements"][1]["font_size"] = 20
check(S.score_layout(r, lc["layout-dense"])[1]["文字放得下"] < 25, "字号太大导致文字放不下，扣分")
r = copy.deepcopy(lc["layout-chart"]["reference"])
r["elements"][2]["x"] = 5.0
check(S.score_layout(r, lc["layout-chart"])[1]["不重叠"] < 20, "元素重叠扣分")
r = copy.deepcopy(lc["layout-chart"]["reference"])
r["elements"][2]["w"] = 7.5
check(S.score_layout(r, lc["layout-chart"])[1]["不越界"] < 15, "超出边距扣分")
r = copy.deepcopy(lc["layout-cards"]["reference"])
r["elements"][4]["w"] = 4
check(S.score_layout(r, lc["layout-cards"])[1]["版式要求"] < 15, "卡片大小不一致扣分")
r = copy.deepcopy(lc["layout-hero"]["reference"])
r["elements"][2].update(w=3, h=3)
check(S.score_layout(r, lc["layout-hero"])[1]["版式要求"] < 15, "配图面积不够扣分")
r = copy.deepcopy(lc["layout-captions"]["reference"])
r["elements"][2]["y"] = 1.3                       # caption1 moved above its chart
check(S.score_layout(r, lc["layout-captions"])[1]["版式要求"] < 15, "说明文字没贴在图下方，扣分")
r = copy.deepcopy(lc["layout-timeline"]["reference"])
r["elements"][1], r["elements"][2] = ({**r["elements"][1], "x": 3.0}, {**r["elements"][2], "x": 0.5})
check(S.score_layout(r, lc["layout-timeline"])[1]["版式要求"] < 15, "时间轴顺序颠倒，扣分")

# ---------------------------------------------------------------- 3b. traps: wrong numbers that are in the source
oc2 = {c["id"]: c for c in C.OUTLINE}["outline-correction"]
r = copy.deepcopy(oc2["reference"])
r["slides"][1]["bullets"] = ["销售额8.6亿元", "去年同期6.4亿元", "同比增长34.4%"]
s, parts, notes = S.score_outline(r, oc2)
check(parts["数字可信"] <= 6 and s < 80, f"用了更正前的数字和按初稿算的增速，扣分（{s}）")
r = copy.deepcopy(oc2["reference"])
r["slides"][2]["bullets"].append("行业增速40%，我们跑赢行业")
check(S.score_outline(r, oc2)[1]["数字可信"] < 30, "写入未经核实的传闻，扣分")
r = copy.deepcopy(oc2["reference"])
r["slides"][1]["bullets"].append("初稿8.6亿元含重复计入的退货，已更正")
check(S.score_outline(r, oc2)[0] == 100, "说明“初稿 8.6 亿已更正”不算用错数字")
cq = {c["id"]: c for c in C.CONDENSE}["condense-qualifier"]
r = copy.deepcopy(cq["reference"])
r["bullets"][0] = "转化率4.6%，环比降0.4%"
s, parts, _ = S.score_condense(r, cq)
check(parts["数字可信"] < 20 and s < 95, f"把个百分点写成 %，扣分（{s}）")
r = copy.deepcopy(cq["reference"])
r["bullets"] = [b.replace("环比", "").replace("同比", "") for b in r["bullets"]]
check(S.score_condense(r, cq)[1]["关键数字保留"] < 40, "丢掉环比/同比，扣分")
ch = {c["id"]: c for c in C.CHART}
check(S.score_chart({"chart_type": "bar", "categories": ["智能客服", "云账本", "数据中台"],
                     "series": [{"values": [25, 38, 35]}]}, ch["chart-margin"])[0] < 70, "没按要求排序，扣分")
check(S.score_chart({"chart_type": "column", "categories": ["7月", "8月", "9月", "10月", "11月", "12月"],
                     "series": [{"values": [6.3, 6.9, 6.1, 7.4, 8.0, 8.8]}]}, ch["chart-filter"])[0] < 100,
      "混入 12 月预测，扣分")
check(S.score_chart({"chart_type": "column", "categories": ["2026年7月", "8月", "9月", "10月", "11月"],
                     "series": [{"values": [6.3, 6.9, 6.1, 7.4, 8.0]}],
                     "takeaway": ch["chart-filter"]["reference"]["takeaway"]}, ch["chart-filter"])[0] == 100,
      "“2026年7月”和“7月”视为同一分类")
check(S.score_chart({"chart_type": "column", "categories": ["Q1", "Q2", "Q3"],
                     "series": [{"values": [12.5, 14.0, 17.2]}]}, ch["chart-partial"])[0] == 0,
      "缺一个数据点时猜一个数，判 0 分")
hard_multi = next(c for c in C.CHART if c["id"] == "chart-hard-multiseries")
check(S.score_chart(hard_multi["reference"], hard_multi)[0] == 100, "多系列 hard 图表参考答案满分")
hard_recs = [{"model_id": "a", "task": "hard", "dimension": "chart", "score": 100},
             {"model_id": "b", "task": "hard", "dimension": "chart", "score": 96}]
case_spread = benchmark.summarize_cases(hard_recs, [{"id": "a"}, {"id": "b"}])
check(case_spread[0]["range"] == 4 and case_spread[0]["stdev"] == 2 and not case_spread[0]["saturated"],
      "题目区分度包含极差、标准差和饱和标记")

# ---------------------------------------------------------------- 4. statistics
check(T.separable([90, 95, 92, 94, 96], [70, 72, 75, 71, 73]) == 1, "明显差距被判定为有差别")
check(T.separable([90, 60, 100, 80], [85, 70, 95, 90]) == 0, "噪声范围内的差距判定为并列")
elo = T.bradley_terry(["A", "B", "C"], {("A", "B"): 7, ("B", "A"): 3, ("A", "C"): 9, ("C", "A"): 1,
                                        ("B", "C"): 6, ("C", "B"): 4})
check(elo["A"] > elo["B"] > elo["C"], f"Bradley-Terry 排序正确 {elo}")
check(abs(sum(T.win_rate_to_points(elo).values()) / 3 - 50) < 1, "两两评审换算后平均 50 分，不整体抬高或压低")
check(benchmark._parse_winner('{"winner": "B", "reason": "更具体，数字准') == "B", "评审回复被截断时仍能读出胜者")

# ---------------------------------------------------------------- 4b. rate limits are not model failures

g = llm._Gate()
g.learn('request reached organization max RPM: 3, please try again after 1 seconds')
check(g.rpm == 3 and g.until > 0, "从 429 提示里读出 RPM 上限和等待时间")
g.active = 3
g.learn('request reached max organization concurrency')
check(g.conc == 2, "并发超限时自动降低并发")
recs = [{"model_id": "m", "task": t, "dimension": "chart", "kind": "chart", "rep": 0, "score": 100.0,
         "error": None, "latency": 2.0, "in_tokens": 1, "out_tokens": 1} for t in ("a", "b")]
recs.append({**recs[0], "task": "c", "score": 0.0, "skipped": True})
row = benchmark.summarize(recs, [{"id": "m"}])["m"]
check(row["dims"]["chart"]["score"] == 100 and row["skipped"] == 1 and row["errors"] == 0,
      "限流跳过的题不计 0 分，也不算模型失败")

# ---------------------------------------------------------------- 5. speed is log scale
check(S.speed_score([3]) == 100 and S.speed_score([60]) == 0, "速度：3 秒满分，60 秒 0 分")
check(abs((S.speed_score([6]) - S.speed_score([12])) - (S.speed_score([12]) - S.speed_score([24]))) < 0.5,
      "速度：耗时每翻一倍扣分相同")

print("\n全部通过" if not FAILED else f"\n{len(FAILED)} 项失败")
sys.exit(1 if FAILED else 0)
