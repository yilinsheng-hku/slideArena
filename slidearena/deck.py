"""Build a real deck using the benchmark results: each sub-task goes to the model that scored best on it.

  outline (text)   -> best "text" model
  chart data       -> best "chart" model, for slides whose kind is "chart"
  cover image      -> best "image" model (skipped if none is image-capable)

Rendering is done locally with python-pptx using one shared theme, so slides made by
different models still look like one deck, and every text box and chart stays editable.
"""
from __future__ import annotations

import io
import json
import re
import time
from pathlib import Path

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR
from pptx.util import Inches, Pt

from . import benchmark, config, facts, llm

THEME = {"bg": RGBColor(0xFF, 0xFF, 0xFF), "ink": RGBColor(0x1F, 0x29, 0x37),
         "muted": RGBColor(0x6B, 0x72, 0x80), "accent": RGBColor(0x25, 0x63, 0xEB),
         "cover_bg": RGBColor(0x0F, 0x17, 0x2A), "font": "Microsoft YaHei"}

CHART_TYPES = {"bar": XL_CHART_TYPE.BAR_CLUSTERED, "column": XL_CHART_TYPE.COLUMN_CLUSTERED,
               "line": XL_CHART_TYPE.LINE_MARKERS, "pie": XL_CHART_TYPE.PIE,
               "doughnut": XL_CHART_TYPE.DOUGHNUT}
PALETTE = [THEME["accent"], RGBColor(0xF5, 0x9E, 0x0B), RGBColor(0x10, 0xB9, 0x81), RGBColor(0x8B, 0x5C, 0xF6)]

DECK_CHART_PROMPT = """[task:chart]
这是 PPT 中的一页，可能适合做成图表。请根据用户资料给出图表数据。
用户资料：{brief}
页面标题：{title}
页面要点：{bullets}

严格要求：图表里的每一个数字都必须来自用户资料，或由资料中的数字直接计算得到（如增长率、占比），禁止编造或估算。请尽量提供 unit 字段；没有明确单位时可以省略。
如果用户资料里没有足够的数字支撑这一页的图表，只输出 {{"skip": true}}。
chart_type 从 bar / column / line / pie / doughnut 中选。takeaway 是一句不超过 30 字的结论。
输出格式：{{"chart_type": "column", "title": "...", "unit": "...", "categories": ["..."], "series": [{{"name": "...", "values": [1.0]}}], "takeaway": "..."}}"""

FIX_PROMPT = """[task:fix]
下面这页 PPT 的要点里有资料中找不到依据的数字：{bad}
请改写这些要点：删掉或替换为资料中有的数字，其他内容尽量保持不变，条数不变，每条不超过 28 个字。每条要点都必须是一句完整、通顺的话。
用户资料：{brief}
原要点：{bullets}
只输出 JSON：{{"bullets": ["..."]}}"""

_NUMBER_TEXT = re.compile(r"(?<![A-Za-z0-9.])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s*(亿元|亿|千万|百万元|万元|万|元|%|％|个百分点)?")
_FORBIDDEN_CALCULATION = re.compile(r"[×÷=]|口径")


def _source_decimal_limit(src: facts.Source) -> int:
    quantities = src.qtys
    return max((q.decimals for q in quantities), default=0)


def _precision_issues(text: str, src: facts.Source) -> list[str]:
    """Find derived-looking values written two or more decimals beyond the source."""
    limit = _source_decimal_limit(src)
    raw = src.qtys
    issues = []
    for q in facts.facts(text):
        if q.decimals <= limit + 1:
            continue
        direct = any(q.family == s.family and abs(q.norm - s.norm) <= max(q.tol, s.tol)
                     for s in raw)
        if not direct:
            issues.append(q.text)
    return issues


def _round_precision(text: str, src: facts.Source) -> str:
    limit = _source_decimal_limit(src)

    def repl(match):
        frac = match.group(2) or ""
        if len(frac) - 1 <= limit + 1:
            return match.group(0)
        value = round(float(match.group(1).replace(",", "") + frac), limit)
        if limit:
            number = f"{value:.{limit}f}"
        else:
            number = str(int(round(value)))
        return number + (match.group(3) or "")

    return _NUMBER_TEXT.sub(repl, str(text))


def unsupported_values(chart: dict, brief: str) -> list[float]:
    """Chart values that are neither in the user's material nor directly derivable from it."""
    src = facts.Source(brief)
    return src.unsupported_values([v for s in chart["series"] for v in s["values"]])


def verify_outline(slides: list[dict], brief: str, fixer: dict | None, progress) -> dict:
    """Fact-check every number in the outline. Rewrite offending bullets once with `fixer`;
    if numbers are still unsupported, drop those bullets. Returns a small report."""
    src = facts.Source(brief)
    report = {"checked": 0, "fixed": [], "removed": []}
    for s in slides:
        original = [str(b) for b in s.get("bullets") or []]
        blocked = [b for b in original if _FORBIDDEN_CALCULATION.search(b)]
        bullets = [b for b in original if not _FORBIDDEN_CALCULATION.search(b)]
        if blocked:
            s["bullets"] = bullets
            report["removed"].append({"slide": s.get("title"), "numbers": [], "bullets": blocked})
            progress(f"核查：「{s.get('title')}」含算式或口径说明，已删去相关要点")
        report["checked"] += sum(len(facts.facts(b)) for b in bullets) + len(facts.facts(str(s.get("title", ""))))
        bad = [x for b in bullets for x in src.unsupported(b)]
        precision = [x for b in bullets for x in _precision_issues(b, src)]
        if not bad and not precision:
            continue
        if fixer:
            try:
                problem = bad + [f"{x}（小数位过多）" for x in precision]
                r = llm.chat(fixer, FIX_PROMPT.format(bad="、".join(problem), brief=brief, bullets=json.dumps(bullets, ensure_ascii=False)),
                             system=benchmark.SYS, max_tokens=1500, temperature=0)
                new = [str(b) for b in (llm.extract_json(r.text).get("bullets") or [])]
                if new and not any(src.unsupported(b) or _precision_issues(b, src) or _FORBIDDEN_CALCULATION.search(b)
                                   for b in new):
                    s["bullets"] = new
                    report["fixed"].append({"slide": s.get("title"), "numbers": problem})
                    progress(f"核查：「{s.get('title')}」里 {problem} 需要修正，已改写")
                    continue
            except Exception:
                pass
        rounded = [_round_precision(b, src) for b in bullets]
        if not any(src.unsupported(b) for b in rounded) and not any(_FORBIDDEN_CALCULATION.search(b) for b in rounded):
            s["bullets"] = rounded
            report["fixed"].append({"slide": s.get("title"), "numbers": bad + precision})
            progress(f"核查：「{s.get('title')}」里的数字已按资料精度四舍五入")
            continue
        kept = [b for b in rounded if not src.unsupported(b) and not _FORBIDDEN_CALCULATION.search(b)]
        s["bullets"] = kept or [re.sub(r"\d+(?:\.\d+)?\s*(?:亿元|亿|万元|万|元|%|个百分点)?", "", bullets[0])]
        report["removed"].append({"slide": s.get("title"), "numbers": bad + precision})
        progress(f"核查：「{s.get('title')}」里 {bad} 无法修正，已删去相关要点")
    return report


def _east_asian(font, name=THEME["font"]):
    """python-pptx only sets the Latin font; CJK text needs the <a:ea> font too, or PowerPoint falls back to SimSun."""
    from pptx.oxml.ns import qn
    rpr = font._rPr if hasattr(font, "_rPr") else font._element
    for tag in ("a:latin", "a:ea", "a:cs"):
        el = rpr.find(qn(tag))
        if el is None:
            el = rpr.makeelement(qn(tag), {})
            rpr.append(el)
        el.set("typeface", name)


def _text(frame, text, size, color, bold=False):
    frame.word_wrap = True
    p = frame.paragraphs[0]
    p.text = text
    for r in p.runs:
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.color.rgb = color
        _east_asian(r.font)


def _bullets(frame, items, size=20, distribute=False):
    frame.word_wrap = True
    if distribute:
        frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    for i, b in enumerate(items):
        p = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        p.text = "•  " + str(b)
        p.space_after = Pt(16 if len(items) <= 3 else 11)
        p.line_spacing = 1.12
        for r in p.runs:
            r.font.size = Pt(size)
            r.font.color.rgb = THEME["ink"]
            _east_asian(r.font)


def _credit(slide, text):
    box = slide.shapes.add_textbox(Inches(0.6), Inches(7.0), Inches(12), Inches(0.3))
    _text(box.text_frame, text, 9, THEME["muted"])


def _fill_bg(slide, color):
    bg = slide.background.fill
    bg.solid()
    bg.fore_color.rgb = color


_METRIC = re.compile(r"(?<![\d.])\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*(?:亿元|亿|千万|万元|万|元|%|％|个百分点|万人|家|人|小时|天|月)")


def _metric_values(bullets: list[str]) -> list[tuple[str, str]]:
    seen = set()
    metrics = []
    for bullet in bullets:
        for match in _METRIC.finditer(str(bullet)):
            value = match.group(0).strip()
            if value in seen:
                continue
            seen.add(value)
            label = str(bullet).replace(match.group(0), "", 1).strip(" ，,:：") or "关键指标"
            metrics.append((value, label[:18]))
            if len(metrics) == 3:
                return metrics
    return metrics


def _metric_cards(slide, bullets: list[str]) -> None:
    for i, (value, label) in enumerate(_metric_values(bullets)):
        y = 1.75 + i * 1.65
        shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(9.15), Inches(y), Inches(3.4), Inches(1.25))
        shape.fill.solid()
        shape.fill.fore_color.rgb = RGBColor(0xEF, 0xF6, 0xFF)
        shape.line.color.rgb = RGBColor(0xBF, 0xDB, 0xFE)
        value_box = slide.shapes.add_textbox(Inches(9.4), Inches(y + 0.12), Inches(2.9), Inches(0.55))
        _text(value_box.text_frame, value, 25, THEME["accent"], bold=True)
        label_box = slide.shapes.add_textbox(Inches(9.4), Inches(y + 0.72), Inches(2.9), Inches(0.35))
        _text(label_box.text_frame, label, 12, THEME["muted"])


def _add_data_labels(plot):
    plot.has_data_labels = True
    labels = plot.data_labels
    labels.show_value = True
    labels.show_category_name = False
    labels.font.size = Pt(11)
    labels.font.color.rgb = THEME["ink"]
    _east_asian(labels.font)


def _set_value_axis_unit(chart, unit: str | None) -> None:
    if not unit:
        return
    try:
        chart.value_axis.has_title = True
        frame = chart.value_axis.axis_title.text_frame
        frame.text = str(unit)
        for paragraph in frame.paragraphs:
            for run in paragraph.runs:
                run.font.size = Pt(11)
                run.font.color.rgb = THEME["muted"]
                _east_asian(run.font)
    except (AttributeError, ValueError):
        pass


def _chart_key(chart: dict) -> tuple:
    return (tuple(str(x) for x in chart.get("categories", [])),
            tuple(tuple(round(float(v), 8) for v in s.get("values", []))
                  for s in chart.get("series", [])))


def _register_chart(chart: dict, seen: set[tuple]) -> bool:
    """Remember a chart's categories and values and reject exact duplicates."""
    key = _chart_key(chart)
    if key in seen:
        return False
    seen.add(key)
    return True


def render(slides: list[dict], path: Path, title: str) -> Path:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    blank = prs.slide_layouts[6]
    for i, s in enumerate(slides):
        slide = prs.slides.add_slide(blank)
        credit = "  ·  ".join(f"{k}: {v}" for k, v in s.get("made_by", {}).items())
        if i == 0:  # only the first slide is a cover, whatever "kind" the model wrote
            _fill_bg(slide, THEME["cover_bg"])
            if s.get("image"):
                slide.shapes.add_picture(io.BytesIO(s["image"]), Inches(6.9), Inches(0), height=Inches(7.5))
            box = slide.shapes.add_textbox(Inches(0.8), Inches(2.4), Inches(6.0), Inches(1.6))
            _text(box.text_frame, s.get("title") or title, 40, RGBColor(0xFF, 0xFF, 0xFF), bold=True)
            if s.get("bullets"):
                sub = slide.shapes.add_textbox(Inches(0.8), Inches(4.1), Inches(6.0), Inches(1.2))
                _text(sub.text_frame, str(s["bullets"][0]), 18, RGBColor(0xCB, 0xD5, 0xE1))
            if credit:
                box = slide.shapes.add_textbox(Inches(0.8), Inches(6.8), Inches(6), Inches(0.4))
                _text(box.text_frame, credit, 9, RGBColor(0x94, 0xA3, 0xB8))
            continue

        _fill_bg(slide, THEME["bg"])
        bar = slide.shapes.add_shape(1, Inches(0.6), Inches(0.55), Inches(0.12), Inches(0.75))
        bar.fill.solid()
        bar.fill.fore_color.rgb = THEME["accent"]
        bar.line.fill.background()
        tb = slide.shapes.add_textbox(Inches(0.9), Inches(0.45), Inches(11.8), Inches(1.0))
        _text(tb.text_frame, str(s.get("title", "")), 32, THEME["ink"], bold=True)

        chart = s.get("chart")
        if chart:
            body = slide.shapes.add_textbox(Inches(0.9), Inches(1.8), Inches(4.4), Inches(4.8))
            _bullets(body.text_frame, s.get("bullets", [])[:5], 18)
            if chart.get("takeaway"):
                cap = slide.shapes.add_textbox(Inches(5.6), Inches(1.45), Inches(7.1), Inches(0.5))
                _text(cap.text_frame, str(chart["takeaway"])[:40], 15, THEME["accent"], bold=True)
            ctype = CHART_TYPES.get(str(chart.get("chart_type")).lower(), XL_CHART_TYPE.COLUMN_CLUSTERED)
            cats, series = list(chart["categories"]), chart["series"]
            if ctype == XL_CHART_TYPE.BAR_CLUSTERED:
                # horizontal bars draw bottom-up; reverse the data so the first category ends up on top
                cats = cats[::-1]
                series = [{**ser, "values": list(ser["values"])[::-1]} for ser in series]
            data = CategoryChartData()
            data.categories = cats
            for ser in series:
                data.add_series(ser.get("name", ""), [float(v) for v in ser["values"]])
            gf = slide.shapes.add_chart(ctype, Inches(5.6), Inches(2.0), Inches(7.1), Inches(4.8), data)
            ch = gf.chart
            _east_asian(ch.font)
            ch.font.size = Pt(14)
            ch.font.color.rgb = THEME["ink"]
            ch.has_title = False
            is_round = ctype in (XL_CHART_TYPE.PIE, XL_CHART_TYPE.DOUGHNUT)
            if not is_round:
                plot = ch.plots[0]
                plot.vary_by_categories = False
                for k, ser in enumerate(plot.series):
                    color = PALETTE[k % len(PALETTE)]
                    if ctype == XL_CHART_TYPE.LINE_MARKERS:
                        ser.format.line.color.rgb = color
                    else:
                        ser.format.fill.solid()
                        ser.format.fill.fore_color.rgb = color
                ch.value_axis.major_gridlines.format.line.color.rgb = RGBColor(0xE5, 0xE7, 0xEB)
                ch.value_axis.format.line.fill.background()
                _add_data_labels(plot)
                _set_value_axis_unit(ch, chart.get("unit"))
            ch.has_legend = is_round or len(chart["series"]) > 1
            if is_round:
                _add_data_labels(ch.plots[0])
                for k, point in enumerate(ch.plots[0].series[0].points):
                    point.format.fill.solid()
                    point.format.fill.fore_color.rgb = PALETTE[k % len(PALETTE)]
                    point.format.line.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
            if ch.has_legend:
                ch.legend.position = XL_LEGEND_POSITION.BOTTOM
                ch.legend.include_in_layout = False
                _east_asian(ch.legend.font)
                ch.legend.font.size = Pt(14)
        else:
            bullets = list(s.get("bullets", []))
            metrics = _metric_values(bullets)
            body_w = 7.7 if metrics else 11.6
            body = slide.shapes.add_textbox(Inches(0.9), Inches(1.8), Inches(body_w), Inches(4.8))
            size = 24 if len(bullets) <= 3 else 22 if len(bullets) == 4 else 20
            _bullets(body.text_frame, bullets, size, distribute=True)
            if metrics:
                _metric_cards(slide, bullets)
        if credit:
            _credit(slide, credit)
    path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(path)
    return path


def _valid_chart(c) -> bool:
    try:
        return (isinstance(c, dict) and c["categories"] and c["series"]
                and all(len(s["values"]) == len(c["categories"]) for s in c["series"])
                and all(float(v) == float(v) for s in c["series"] for v in s["values"]))
    except (KeyError, TypeError, ValueError):
        return False


def build(brief: str, n_slides: int = 6, model_ids: list[str] | None = None, progress=print,
          show_credits: bool = True) -> dict:
    models = [m for m in config.list_models() if not model_ids or m["id"] in model_ids]
    if not models:
        raise llm.ModelError("还没有接入任何模型")
    text_m = benchmark.route("text", models)
    chart_m = benchmark.route("chart", models)
    image_m = benchmark.route("image", models)
    plan = {"大纲文字": benchmark.explain_route("text", models), "数据图表": benchmark.explain_route("chart", models),
            "封面配图": benchmark.explain_route("image", models) if image_m else "（无可用图片模型）"}
    progress("任务分配：" + "；".join(f"{k} → {v}" for k, v in plan.items()))

    reply = llm.chat(text_m, benchmark.OUTLINE_PROMPT.format(n=n_slides, brief=brief),
                     system=benchmark.SYS, max_tokens=4000)
    slides = llm.extract_json(reply.text).get("slides") or []
    if not slides:
        raise llm.ModelError("大纲为空")
    for s in slides:
        s["made_by"] = {"文字": text_m["name"]} if show_credits else {}
    progress(f"大纲完成：{len(slides)} 页（{text_m['name']}）")
    check = verify_outline(slides, brief, chart_m, progress)
    progress(f"数字核查：共 {check['checked']} 个数字，改写 {len(check['fixed'])} 页，删减 {len(check['removed'])} 页")

    seen_charts = set()
    for s in slides[1:]:
        if s.get("kind") != "chart":
            continue
        try:
            r = llm.chat(chart_m, DECK_CHART_PROMPT.format(brief=brief, title=s.get("title"),
                                                           bullets="；".join(map(str, s.get("bullets", [])))),
                         system=benchmark.SYS, max_tokens=1200, temperature=0.1)
            c = llm.extract_json(r.text)
            if isinstance(c, dict) and c.get("skip"):
                progress(f"资料里没有这页需要的数字，保持文字页：{s.get('title')}")
                continue
            if not _valid_chart(c):
                progress(f"图表数据不完整，这页改用文字：{s.get('title')}")
                continue
            fake = unsupported_values(c, brief)
            if fake:
                progress(f"拦截编造数据 {fake}（资料中没有），这页改用文字：{s.get('title')}")
                continue
            if not _register_chart(c, seen_charts):
                s["kind"] = "bullets"
                progress(f"图表与前页分类和数值完全重复，这页改用文字：{s.get('title')}")
                continue
            s["chart"] = c
            if show_credits:
                s["made_by"]["图表"] = chart_m["name"]
            progress(f"图表完成：{s.get('title')}（{chart_m['name']}）")
        except Exception as e:
            progress(f"图表失败，这页改用文字：{e}")

    if image_m:
        try:
            img, _ = llm.generate_image(image_m, f"PPT 封面插画，主题：{slides[0].get('title') or brief[:40]}。简洁、现代、留白、没有文字。")
            slides[0]["image"] = img
            if show_credits:
                slides[0]["made_by"]["配图"] = image_m["name"]
            progress(f"封面配图完成（{image_m['name']}）")
        except Exception as e:
            progress(f"配图失败，封面不放图：{e}")

    safe = re.sub(r"[^\w一-鿿]+", "_", (slides[0].get("title") or "deck"))[:30]
    out = config.home() / "output" / f"{time.strftime('%Y%m%d-%H%M%S')}_{safe}.pptx"
    render(slides, out, slides[0].get("title") or "演示文稿")
    progress(f"已生成：{out}")
    return {"path": str(out), "plan": plan, "slides": len(slides), "fact_check": check}
