"""Parametric questions: fresh numbers, names and wording every batch.

Why: a fixed, public question bank can be memorised or tuned against, and a handful of cases
gives wide confidence intervals. These generators build chart, condense and layout cases from
templates with random values, distractors and lengths, and compute the reference answer in
code. Every generated case is checked with the real scorer before it is used: if its reference
answer would not get 100, the generator draws again. So a generated case is as trustworthy as a
hand-checked one, and `slidearena selftest` / the unit tests verify this over many seeds.

The same seed always gives the same cases. The default seed changes every ISO week, so
everyone who tests in the same week answers the same questions (results are comparable),
while next week's batch cannot be memorised in advance.
"""
from __future__ import annotations

import datetime
import hashlib
import random

from . import scoring
from .cases import MARGIN, SLIDE_H, SLIDE_W

# every generated case, by id, so the offline demo model can find the case behind a prompt
REGISTRY: dict[str, dict] = {}


def default_seed(today: datetime.date | None = None) -> str:
    y, w, _ = (today or datetime.date.today()).isocalendar()
    return f"{y}-W{w:02d}"


def _rng(seed: str, name: str, attempt: int) -> random.Random:
    digest = hashlib.sha256(f"{seed}|{name}|{attempt}".encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def _fmt(x: float, decimals: int = 1) -> str:
    return f"{x:.{decimals}f}"


def _wan(x: int) -> str:
    return f"{x:,}"


REGIONS = ["华东", "华南", "华北", "华中", "西南", "西北", "东北", "海外"]
PRODUCTS = ["智能客服", "云账本", "数据中台", "智能硬件", "专业服务", "协同办公", "安全网关", "营销云"]
PLATFORMS = ["iOS", "安卓", "网页端", "小程序", "桌面端", "平板端"]
CHANNELS = ["线上商城", "直营门店", "经销商", "大客户", "海外电商"]


def _distinct(rng: random.Random, lo: int, hi: int, n: int, gap: int = 1) -> list[int]:
    """n integers in [lo, hi] that differ pairwise by at least `gap` (avoids ties)."""
    while True:
        vals = rng.sample(range(lo, hi + 1), n)
        if all(abs(a - b) >= gap for i, a in enumerate(vals) for b in vals[i + 1:]):
            return vals


# --------------------------------------------------------------------------- charts
def chart_units(rng: random.Random) -> dict:
    """Mixed 亿元 / 万元 amounts that must be converted, plus distractor figures."""
    names = rng.sample(REGIONS, 4)
    tenths = _distinct(rng, 12, 95, 4, gap=3)                  # 1.2 .. 9.5 亿
    parts, values = [], []
    for name, t in zip(names, tenths):
        if rng.random() < 0.5:                                  # write it in 万元
            wan = t * 1000 + rng.choice([0, 0, 500])
            parts.append(f"{name} {_wan(wan)} 万元")
            values.append(wan / 10000)
        else:
            parts.append(f"{name} {_fmt(t / 10)} 亿元")
            values.append(t / 10)
    total_last_year = round(sum(values) * rng.uniform(2.6, 3.4), 1)
    material = (f"各区域 Q{rng.randint(1, 4)} 营收：" + "，".join(parts) + "。"
                f"去年全年营收 {_fmt(total_last_year)} 亿元，员工 {_wan(rng.randint(800, 3000))} 人。")
    top = names[values.index(max(values))]
    return {"material": material, "ask": f"对比这{len(names)}个区域的营收，单位统一为亿元",
            "categories": names, "values": values, "good_types": ["bar", "column"],
            "reference": {"chart_type": "bar", "title": "各区域营收", "unit": "亿元", "categories": names,
                          "series": [{"name": "营收", "values": [round(v, 2) for v in values]}],
                          "takeaway": f"{top}营收最高"}}


def chart_share(rng: random.Random) -> dict:
    """Shares that must be computed from counts; the total is not given."""
    names = rng.sample(PLATFORMS, rng.choice([3, 4]))
    counts = _distinct(rng, 40, 600, len(names), gap=15)       # 4.0 .. 60.0 万
    total = sum(counts)
    shares = [100 * c / total for c in counts]
    material = (f"截至 {rng.randint(3, 11)} 月底各端注册用户：" +
                "，".join(f"{n} {_fmt(c / 10)} 万" for n, c in zip(names, counts)) + "。")
    top = names[counts.index(max(counts))]
    return {"material": material, "ask": "展示各端用户的占比，单位：%",
            "categories": names, "values": shares, "good_types": ["pie", "doughnut", "bar", "column"],
            "reference": {"chart_type": "pie", "title": "各端用户占比", "unit": "%", "categories": names,
                          "series": [{"name": "占比", "values": [round(s, 1) for s in shares]}],
                          "takeaway": f"{top}用户占比最高"}}


def chart_growth(rng: random.Random) -> dict:
    """Year-over-year growth rates computed from absolute values."""
    start = rng.randint(2019, 2022)
    years = list(range(start, start + 4))
    rev = [rng.randint(40, 120) / 10]
    for _ in range(3):
        rev.append(round(rev[-1] * rng.uniform(1.05, 1.45), 1))
    growth = [100 * (rev[i] / rev[i - 1] - 1) for i in range(1, 4)]
    if len({round(g, 1) for g in growth}) < 3:
        raise ValueError("tied growth rates")
    material = "公司年营收：" + "，".join(f"{y} 年 {_fmt(r)} 亿元" for y, r in zip(years, rev)) + "。"
    best = years[1 + growth.index(max(growth))]
    return {"material": material,
            "ask": f"展示 {years[1]}—{years[3]} 年每一年营收的同比增长率，单位：%",
            "categories": [str(y) for y in years[1:]], "values": growth, "good_types": ["line", "column", "bar"],
            "reference": {"chart_type": "line", "title": "营收同比增长率", "unit": "%",
                          "categories": [f"{y}年" for y in years[1:]],
                          "series": [{"name": "同比增长率", "values": [round(g, 1) for g in growth]}],
                          "takeaway": f"{best}年增速最快"}}


def chart_filter_sort(rng: random.Random) -> dict:
    """Pick a sub-range of a monthly series, leave out the forecast, sort descending."""
    vals = [v / 10 for v in _distinct(rng, 20, 99, 12, gap=1)]
    a = rng.randint(2, 6)
    b = a + rng.randint(3, 4)
    picked = [(f"{m}月", vals[m - 1]) for m in range(a, b + 1)]
    picked.sort(key=lambda t: -t[1])
    material = (f"{rng.randint(2024, 2026)} 年每月新增用户（万人）：" +
                "，".join(f"{m} 月 {_fmt(vals[m - 1])}" for m in range(1, 12)) +
                f"，12 月预计 {_fmt(vals[11])}。")
    return {"material": material,
            "ask": f"只展示 {a}—{b} 月实际的每月新增用户，并按数值从高到低排列，单位：万人",
            "categories": [c for c, _ in picked], "values": [v for _, v in picked],
            "good_types": ["bar", "column"],
            "reference": {"chart_type": "bar", "title": f"{a}—{b}月新增用户排序", "unit": "万人",
                          "categories": [c for c, _ in picked],
                          "series": [{"name": "新增用户", "values": [v for _, v in picked]}],
                          "takeaway": f"{picked[0][0]}新增用户最多"}}


def chart_margin(rng: random.Random) -> dict:
    """Hard: margin = (revenue - cost) / revenue, mixed units, a distractor total, sorted."""
    names = rng.sample(PRODUCTS, 3)
    margins = _distinct(rng, 15, 55, 3, gap=3)
    rows, values = [], []
    for i, (name, mg) in enumerate(zip(names, margins)):
        rev_tenths = rng.randint(12, 80)
        cost = round(rev_tenths / 10 * (1 - mg / 100), 2)
        rev = rev_tenths / 10
        if i == 2:                                              # one line written in 万元
            rows.append(f"{name}营收 {_wan(int(rev * 10000))} 万元、成本 {_wan(int(round(cost * 10000)))} 万元")
        else:
            rows.append(f"{name}营收 {_fmt(rev)} 亿元、成本 {cost:g} 亿元")
        values.append(100 * (rev - cost) / rev)
    order = sorted(range(3), key=lambda i: -values[i])
    material = f"Q{rng.randint(1, 4)} 各产品线：" + "；".join(rows) + f"。公司总营收 {_fmt(rng.uniform(15, 40))} 亿元。"
    return {"level": "hard", "material": material,
            "ask": "对比三条产品线的毛利率（（营收－成本）/营收），单位：%，按毛利率从高到低排列",
            "categories": [names[i] for i in order], "values": [values[i] for i in order],
            "good_types": ["bar", "column"],
            "reference": {"chart_type": "bar", "title": "各产品线毛利率", "unit": "%",
                          "categories": [names[i] for i in order],
                          "series": [{"name": "毛利率", "values": [round(values[i], 1) for i in order]}],
                          "takeaway": f"{names[order[0]]}毛利率最高"}}


# --------------------------------------------------------------------------- condense
DOMAINS = [
    {"subject": "客服中心", "m1": ("处理工单", "万张"), "m2": ("首次响应时间", "小时"), "m3": "客户满意度", "m3_range": (850, 980),
     "issue": "夜间投诉", "areas": ["退款流程", "物流查询", "账号找回"]},
    {"subject": "App", "m1": ("累计下载", "万次"), "m2": ("平均加载时间", "秒"), "m3": "次日留存率", "m3_range": (250, 600),
     "issue": "差评", "areas": ["登录问题", "支付失败", "推送打扰"]},
    {"subject": "门店", "m1": ("到店客流", "万人次"), "m2": ("平均排队时间", "分钟"), "m3": "会员复购率", "m3_range": (200, 550),
     "issue": "退货", "areas": ["尺码问题", "色差问题", "售后服务"]},
    {"subject": "物流", "m1": ("发货量", "万单"), "m2": ("平均配送时长", "小时"), "m3": "准时送达率", "m3_range": (880, 990),
     "issue": "破损投诉", "areas": ["生鲜品类", "大件商品", "偏远地区"]},
]


def _condense(rng: random.Random, max_bullets: int, max_len: int, hard: bool) -> dict:
    d = rng.choice(DOMAINS)
    period = rng.choice(["Q1", "Q2", "Q3", "Q4", "上半年", "10 月", "11 月"])
    v1 = rng.randint(30, 400) / 10
    g1 = rng.randint(5, 45)
    a2 = rng.randint(30, 90) / 10
    b2 = round(a2 * rng.uniform(0.3, 0.7), 1)
    v3 = rng.randint(*d["m3_range"]) / 10
    pp = rng.randint(3, 49) / 10
    up = rng.random() < 0.5
    v4 = rng.randint(15, 45)
    area = rng.choice(d["areas"])
    numbers = {_fmt(v1), str(g1), _fmt(a2), _fmt(b2), _fmt(v3), _fmt(pp), str(v4)}
    if len(numbers) < 7:
        raise ValueError("numbers collide")
    (m1, u1), (m2, u2), m3 = d["m1"], d["m2"], d["m3"]
    word = "提升" if up else "下降"
    material = (f"{period}{d['subject']}{m1} {_fmt(v1)} {u1}，同比增长 {g1}%；"
                f"{m2}从 {_fmt(a2)} {u2}缩短到 {_fmt(b2)} {u2}；"
                f"{m3}为 {_fmt(v3)}%，环比{word} {_fmt(pp)} 个百分点；"
                f"{d['issue']}占比升至 {v4}%，主要集中在{area}。")
    short = "升" if up else "降"
    if hard:
        bullets = [f"{m1}{_fmt(v1)}{u1}，增{g1}%", f"{m2}降至{_fmt(b2)}{u2}",
                   f"{m3}{_fmt(v3)}%，环比{short}{_fmt(pp)}个百分点", f"{d['issue']}占比{v4}%"]
        bullets = [bullets[0], bullets[2], bullets[3]] if max_bullets == 3 else bullets
        must = [_fmt(v1) + "万", _fmt(v3) + "%", _fmt(pp) + "个百分点", f"{v4}%"]
    else:
        bullets = [f"{m1}{_fmt(v1)}{u1}，同比增长{g1}%", f"{m2}从{_fmt(a2)}{u2}降至{_fmt(b2)}{u2}",
                   f"{m3}{_fmt(v3)}%，环比{word}{_fmt(pp)}个百分点", f"{d['issue']}占比{v4}%，集中在{area}"]
        must = [_fmt(v1) + "万", _fmt(b2), _fmt(v3) + "%", _fmt(pp) + "个百分点", f"{v4}%"]
    pp_re = _fmt(pp).replace(".", r"\.")
    return {"material": material, "max_bullets": max_bullets, "max_len": max_len,
            "must_numbers": must, "must_terms": ["环比"],
            "wrong_patterns": [[rf"(?<![\d.]){pp_re}\s*[%％]", f"把 {_fmt(pp)} 个百分点写成了 {_fmt(pp)}%"]],
            "reference": {"title": f"{period.replace(' ', '')}{d['subject']}概况", "bullets": bullets},
            **({"level": "hard"} if hard else {})}


def condense_standard(rng: random.Random) -> dict:
    return _condense(rng, 4, 24, hard=False)


def condense_tight(rng: random.Random) -> dict:
    return _condense(rng, 3, 18, hard=True)


# --------------------------------------------------------------------------- layout
CARD_TEXTS = [("智能大纲", "一句话生成结构清晰的大纲"), ("数据图表", "自动识别数字并生成原生图表"),
              ("多模型分工", "每页交给最擅长的模型完成"), ("事实核查", "自动拦截资料里没有的数字"),
              ("统一主题", "不同模型做的页面风格一致"), ("一键导出", "生成可编辑的 PowerPoint 文件"),
              ("本地运行", "密钥只保存在你自己的电脑上"), ("限流排队", "自动识别额度并排队重试"),
              ("视觉评审", "把排版渲染成截图交给模型比较"), ("成本优先", "分数并列时选更省更快的模型")]
EVENTS = ["公司成立", "推出首款产品", "用户突破 10 万", "完成 A 轮融资", "进入华南市场", "上线企业版",
          "营收突破 5 亿元", "开设海外办事处", "用户突破 100 万", "完成 B 轮融资", "发布 AI 助手"]
ISSUES = ["人力成本同比增长 27%，明显快于营收增速", "华南区渠道覆盖不足，新客户获取成本偏高",
          "夜间客服投诉占比升至 37%，集中在退款流程", "新产品交付周期偏长，部分大客户续约存在风险",
          "跨部门协作依赖线下会议，决策平均耗时超过两周", "核心研发人员流失率上升，关键模块缺少备份",
          "各部门数据口径不一致，经营报表反复返工", "库存周转天数增加到 46 天，占用较多现金",
          "老客户续约率下降到 76%，主要因为价格调整", "海外业务汇率波动大，利润预测难度增加"]


def _fit_font(paras: list[str], w: float, h: float, lo: int, hi: int) -> int | None:
    for fs in range(hi, lo - 1, -1):
        if scoring.text_fit_ratio(paras, w, fs, h) <= 0.97:   # a little headroom
            return fs
    return None


def _title(text: str) -> tuple[dict, dict]:
    w = SLIDE_W - 2 * MARGIN - 0.4
    fs = _fit_font([text], w, 1.0, 28, 40)
    if fs is None:
        raise ValueError("title does not fit")
    return {"title": [text]}, {"role": "title", "x": round(MARGIN + 0.2, 2), "y": 0.5, "w": round(w, 2), "h": 1.0, "font_size": fs}


def _grid(roles: list[str], texts: list[list[str]], rows: int, cols: int, top: float = 1.8,
          gap: float = 0.3) -> list[dict]:
    left, right, bottom = MARGIN + 0.2, SLIDE_W - MARGIN - 0.2, SLIDE_H - MARGIN - 0.1
    w = round((right - left - gap * (cols - 1)) / cols, 2)
    h = round((bottom - top - gap * (rows - 1)) / rows, 2)
    fs = min(_fit_font(t, w, h, 14, 24) or 0 for t in texts)
    if not fs:
        raise ValueError("cards too small for their text")
    return [{"role": r, "x": round(left + (i % cols) * (w + gap), 2), "y": round(top + (i // cols) * (h + gap), 2),
             "w": w, "h": h, "font_size": fs} for i, r in enumerate(roles)]


def layout_cards(rng: random.Random) -> dict:
    k = rng.choice([3, 4, 6])
    rows, cols = {3: (1, 3), 4: (2, 2), 6: (2, 3)}[k]
    picked = rng.sample(CARD_TEXTS, k)
    spec, title_el = _title(rng.choice(["核心能力", "产品亮点", "我们能做什么", "核心优势"]))
    roles = [f"card{i + 1}" for i in range(k)]
    texts = [[a, b] for a, b in picked]
    spec.update(dict(zip(roles, texts)))
    els = [title_el] + _grid(roles, texts, rows, cols)
    return {"desc": f"标题下面 {k} 张大小一致的卡片，排成 {rows} 行 {cols} 列", "elements": spec, "uniform": roles,
            "reference": {"elements": els}}


def layout_timeline(rng: random.Random) -> dict:
    k = rng.randint(4, 6)
    start = rng.randint(2014, 2020)
    events = rng.sample(EVENTS, k)
    spec, title_el = _title(rng.choice(["发展历程", "公司大事记", "成长之路"]))
    roles = [f"step{i + 1}" for i in range(k)]
    texts = [[str(start + i), e] for i, e in enumerate(events)]
    spec.update(dict(zip(roles, texts)))
    els = [title_el] + _grid(roles, texts, 1, k, top=2.4, gap=0.2)
    for e in els[1:]:
        e["h"] = min(e["h"], 2.4)
        fs = _fit_font(spec[e["role"]], e["w"], e["h"], 14, 24)
        if fs is None:
            raise ValueError("timeline step too small")
        e["font_size"] = min(e["font_size"], fs)
    return {"desc": f"发展历程时间轴：{k} 个里程碑在同一行从左到右排列，大小一致", "elements": spec,
            "uniform": roles, "row": roles, "reference": {"elements": els}}


def layout_text_visual(rng: random.Random) -> dict:
    n = rng.randint(3, 6)
    frac = rng.choice([0.25, 0.3, 0.35])
    spec, title_el = _title(rng.choice(["经营问题清单", "本季度风险", "需要关注的问题"]))
    spec["body"] = rng.sample(ISSUES, n)
    spec["visual"] = None
    top, bottom = 1.8, SLIDE_H - MARGIN - 0.1
    h = round(bottom - top, 2)
    vis_w = round(frac * SLIDE_W * SLIDE_H / h + 0.15, 2)
    right = SLIDE_W - MARGIN - 0.2
    body_w = round(right - vis_w - 0.3 - (MARGIN + 0.2), 2)
    fs = _fit_font(spec["body"], body_w, h, 14, 24)
    if fs is None:
        raise ValueError("body text does not fit")
    side = rng.random() < 0.5                                  # visual on the right or the left
    left = round(MARGIN + 0.2, 2)
    body_x, vis_x = (left, round(right - vis_w, 2)) if side else (round(left + vis_w + 0.3, 2), left)
    els = [title_el, {"role": "body", "x": body_x, "y": top, "w": body_w, "h": h, "font_size": fs},
           {"role": "visual", "x": vis_x, "y": top, "w": vis_w, "h": h}]
    return {"desc": f"{'左' if side else '右'}侧是文字要点，{'右' if side else '左'}侧放一张配图（至少占画面 {frac:.0%}）",
            "elements": spec, "min_area": {"visual": frac}, "reference": {"elements": els}}


# --------------------------------------------------------------------------- assembly
GENERATORS = {
    "chart": [("units", chart_units), ("share", chart_share), ("growth", chart_growth),
              ("filter", chart_filter_sort), ("margin", chart_margin)],
    "condense": [("standard", condense_standard), ("tight", condense_tight)],
    "layout": [("cards", layout_cards), ("timeline", layout_timeline), ("textvisual", layout_text_visual)],
}
SCORER = {"chart": scoring.score_chart, "condense": scoring.score_condense, "layout": scoring.score_layout}


def make(kind: str, name: str, fn, seed: str) -> dict:
    """One case. Draw again until the computed reference scores 100 with the real scorer."""
    for attempt in range(200):
        try:
            case = fn(_rng(seed, f"{kind}-{name}", attempt))
        except ValueError:
            continue
        case["id"] = f"gen-{kind}-{name}-{seed}"
        case["generated"] = {"seed": seed, "generator": f"{kind}-{name}"}
        if SCORER[kind](case["reference"], case)[0] == 100:
            REGISTRY[case["id"]] = case
            return case
    raise RuntimeError(f"generator {kind}-{name} could not build a valid case for seed {seed}")


def bank(seed: str | None = None) -> dict[str, list[dict]]:
    """Generated cases for one batch: {"chart": [...], "condense": [...], "layout": [...]}."""
    seed = seed or default_seed()
    return {kind: [make(kind, name, fn, seed) for name, fn in gens] for kind, gens in GENERATORS.items()}
