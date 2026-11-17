"""Benchmark question bank.

Every case carries a hand-checked reference answer. `slidearena selftest` (and the unit tests)
run the scorers on these references and require 100 points, which proves the scorer is not
silently penalising correct answers.

Cases are deliberately harder than "copy these numbers":
  - distractor numbers that must be ignored (last year's total, headcount, contest rank)
  - mixed units that must be converted (71,000 万元 -> 7.1 亿元)
  - values that must be computed (growth rates, the remaining share)
  - a request that cannot be answered from the material (must refuse instead of inventing)
  - layouts where text only fits if the font size and box size are chosen with care
"""
from __future__ import annotations

import copy

SLIDE_W, SLIDE_H, MARGIN = 13.333, 7.5, 0.4
BANK_VERSION = "2026.11-c"

# --------------------------------------------------------------------------- outline (text)
OUTLINE = [
    {
        "id": "outline-review", "n": 6,
        "brief": "给公司管理层做一份《2026 年第三季度经营复盘》，听众是 CEO 和各部门负责人。",
        "material": ("2026 年前三季度营收：Q1 12.5 亿元、Q2 14.8 亿元、Q3 17.2 亿元（去年 Q3 为 13.1 亿元）。"
                     "Q3 分区域：华东 7.1 亿元、华南 3.2 亿元、其他区域 6.9 亿元。"
                     "Q3 毛利率 38.5%，去年同期 41.2%，下滑主因是人力成本上涨：Q3 人力成本 4.6 亿元，同比增长 27%。"
                     "新产品线“灵犀”Q3 贡献营收 3.4 亿元。"
                     "下季度目标：营收 19 亿元，人力成本率控制在 25% 以内，华南新增 2 个城市办事处。"),
        "must_numbers": ["17.2亿", "38.5%", "4.6亿", "3.4亿", "19亿"],
        "must_terms": ["华东", "人力成本", "灵犀"],
        "check_numbers": True,
        "reference": {"slides": [
            {"title": "2026年Q3经营复盘", "bullets": ["汇报对象：CEO与各部门负责人"], "kind": "cover"},
            {"title": "Q3营收创年内新高", "kind": "chart", "bullets": [
                "Q3营收17.2亿元，环比增长16.2%", "同比去年Q3的13.1亿增长31.3%", "前三季度累计营收44.5亿元"]},
            {"title": "华东领跑区域增长", "kind": "chart", "bullets": [
                "华东7.1亿元，占Q3营收41.3%", "华南3.2亿元，仍有较大空间", "其他区域合计6.9亿元"]},
            {"title": "毛利率承压", "kind": "bullets", "bullets": [
                "Q3毛利率38.5%，同比降2.7个百分点", "人力成本4.6亿元，同比增长27%", "人力成本增速快于营收增速"]},
            {"title": "新产品线贡献增量", "kind": "bullets", "bullets": [
                "灵犀Q3营收3.4亿元", "占Q3营收19.8%", "成为第二增长引擎"]},
            {"title": "Q4目标与行动", "kind": "bullets", "bullets": [
                "营收目标19亿元", "人力成本率控制在25%以内", "华南新增2个城市办事处"]},
        ]},
    },
    {
        "id": "outline-pitch", "n": 8,
        "brief": "给天使投资人做一份融资路演 PPT，时间 10 分钟。",
        "material": ("我们是一款面向大学生的 AI 学习笔记 App“课记”。目前注册用户 42 万，月活跃用户 15.6 万，"
                     "付费转化率 3.8%，会员月费 18 元；主要竞品 A 月费 30 元，竞品 B 免费但有广告。"
                     "本轮计划融资 3000 万元，资金 50% 用于研发、30% 用于市场推广、20% 用于运营。"
                     "团队 26 人，其中研发 17 人。2025 年参加创业大赛获得第 2 名。"),
        "must_numbers": ["42万", "15.6万", "3.8%", "3000万"],
        "must_terms": ["课记", "竞品", "研发"],
        "check_numbers": True,
        "reference": {"slides": [
            {"title": "课记：大学生AI学习笔记", "bullets": ["天使轮融资路演"], "kind": "cover"},
            {"title": "大学生记笔记的痛点", "kind": "bullets", "bullets": [
                "课堂信息多，手写跟不上", "课后整理耗时，复习效率低", "现有工具不懂课程结构"]},
            {"title": "产品：AI整理课堂笔记", "kind": "image", "bullets": [
                "录音转写并生成结构化笔记", "自动提炼重点和复习卡片", "多端同步，一键分享"]},
            {"title": "用户增长", "kind": "chart", "bullets": [
                "注册用户42万", "月活跃用户15.6万", "月活占注册用户37.1%"]},
            {"title": "商业模式", "kind": "bullets", "bullets": [
                "会员月费18元", "付费转化率3.8%", "价格低于竞品A的30元"]},
            {"title": "竞争优势", "kind": "bullets", "bullets": [
                "竞品A月费30元，价格更高", "竞品B免费但广告干扰学习", "课记专注课堂场景，体验更好"]},
            {"title": "融资计划", "kind": "chart", "bullets": [
                "本轮融资3000万元", "50%用于研发", "30%市场推广，20%运营"]},
            {"title": "团队", "kind": "bullets", "bullets": [
                "团队26人，研发17人", "研发占团队65.4%", "期待与您同行"]},
        ]},
    },
    {
        "id": "outline-lesson", "n": 7,
        "brief": "给高一学生上一节《光合作用》的课，要有导入、原理、实验和小结。",
        "material": ("授课对象：高一学生，课时 40 分钟。教学目标：理解光合作用的原料、条件、场所和产物；"
                     "了解光反应和暗反应的区别；能设计验证“光是光合作用条件”的实验。"),
        "must_numbers": [],
        "must_terms": ["叶绿体", "光反应", "暗反应", "二氧化碳", "氧气", "实验"],
        "check_numbers": False,   # domain knowledge numbers are allowed in a science lesson
        "reference": {"slides": [
            {"title": "光合作用", "bullets": ["高一生物·40分钟"], "kind": "cover"},
            {"title": "导入：植物吃什么长大", "kind": "image", "bullets": [
                "种子长成大树，质量从哪来", "回顾海尔蒙特柳树实验", "提出问题：光起什么作用"]},
            {"title": "原料、条件与产物", "kind": "bullets", "bullets": [
                "原料：二氧化碳和水", "条件：光照，场所：叶绿体", "产物：有机物和氧气"]},
            {"title": "光反应", "kind": "bullets", "bullets": [
                "场所：叶绿体类囊体薄膜", "水分解释放氧气", "生成ATP和NADPH"]},
            {"title": "暗反应", "kind": "bullets", "bullets": [
                "场所：叶绿体基质", "固定二氧化碳", "利用ATP合成有机物"]},
            {"title": "实验：光是必要条件", "kind": "image", "bullets": [
                "暗处理后部分遮光", "光照后脱色并滴加碘液", "见光部分变蓝，说明产生淀粉"]},
            {"title": "小结", "kind": "bullets", "bullets": [
                "光反应为暗反应提供能量", "暗反应把二氧化碳变成糖", "课后思考：大棚如何增产"]},
        ]},
    },
    {
        # hard: a corrected figure (the draft number is still in the text), a rumour that must be left
        # out, and a growth rate that has to be computed from the corrected figure
        "id": "outline-correction", "n": 6,
        "brief": ("给销售团队做一份《2026 年 10 月销售月报》，听众是一线销售经理，要讲清楚同比增速。"
                  "报告里只用财务复核后的数字，不写未经核实的信息。"),
        "material": ("10 月销售额初稿统计为 8.6 亿元，经财务复核更正为 8.2 亿元（初稿重复计入了一笔 0.4 亿元的退货订单）。"
                     "去年 10 月销售额 6.4 亿元。新签客户 312 家，其中企业客户 87 家，客单价 26.3 万元。"
                     "退货率 2.1%，比 9 月上升 0.6 个百分点。重点产品“云账本”销售额 2.9 亿元。"
                     "11 月目标：销售额 9 亿元，退货率降到 1.5% 以下。"
                     "另：市场部转述的“行业增速 40%”是未经核实的传闻。"),
        "must_numbers": ["8.2亿", "28.1%", "312", "2.1%", "2.9亿", "9亿"],
        "must_terms": ["云账本", "退货率"],
        "check_numbers": True,
        # draft figure, growth computed from the draft (8.6 / 6.4 - 1), the rumour
        "wrong_patterns": [[r"8\.6\s*亿", "用了更正前的 8.6 亿", r"初稿|更正|复核|重复|修正|调整"],
                           [r"34\.\d\s*%", "按初稿算的增速 34.4%", r"初稿|更正|修正"],
                           [r"(?<![\d.])40\s*%", "写入了未经核实的传闻 40%"]],
        "reference": {"slides": [
            {"title": "2026年10月销售月报", "bullets": ["面向一线销售经理"], "kind": "cover"},
            {"title": "10月销售额8.2亿元", "kind": "chart", "bullets": [
                "销售额8.2亿元（财务复核口径）", "去年同期6.4亿元", "同比增长28.1%"]},
            {"title": "新客户拓展", "kind": "bullets", "bullets": [
                "新签客户312家", "其中企业客户87家", "客单价26.3万元"]},
            {"title": "重点产品云账本", "kind": "bullets", "bullets": [
                "云账本销售额2.9亿元", "占当月销售额35.4%", "继续作为主推产品"]},
            {"title": "退货率需要关注", "kind": "bullets", "bullets": [
                "退货率2.1%", "比9月上升0.6个百分点", "需要排查退货原因"]},
            {"title": "11月目标", "kind": "bullets", "bullets": [
                "销售额目标9亿元", "比10月增长9.8%", "退货率降到1.5%以下"]},
        ]},
    },
]

# Additional hard outline cases deliberately contain reconciliation and unit traps.
OUTLINE.extend([
    {
        "id": "outline-hard-reconciliation", "level": "hard", "n": 6,
        "brief": "给经营委员会做一份经过财务复核的年度经营复盘，突出单位换算和已更正数字。",
        "material": ("2026 年全年营收初报 9.8 亿元，财务复核后为 9.6 亿元；2025 年全年营收 8.1 亿元。"
                     "华东营收 4.2 亿元，华南营收 2.4 亿元，海外营收 1.6 亿元，其余为其他区域。"
                     "研发投入 6,800 万元，研发人员 126 人；产品线 A 贡献营收 1.9 亿元。"
                     "2027 年目标营收 11 亿元，研发投入率保持在 8% 以上。初报数字未经复核，不应直接使用。"),
        "must_numbers": ["9.6亿", "8.1亿", "2.4亿", "6800万", "1.9亿", "11亿", "8%"],
        "must_terms": ["财务复核", "华南", "研发投入", "产品线"], "check_numbers": True,
        "wrong_patterns": [[r"9\.8\s*亿", "用了未经复核的 9.8 亿初报数字", r"初报|复核|更正"],
                           [r"(?<![\d.])10\.5\s*亿", "把区域数字加错后写成 10.5 亿"]],
        "reference": {"slides": [
            {"title": "2026年度经营复盘", "bullets": ["经营委员会汇报"], "kind": "cover"},
            {"title": "全年营收9.6亿元", "kind": "bullets", "bullets": ["财务复核后营收9.6亿元", "2025年营收8.1亿元", "复核数字作为正式口径"]},
            {"title": "区域结构", "kind": "chart", "bullets": ["华东营收4.2亿元", "华南营收2.4亿元", "海外营收1.6亿元"]},
            {"title": "研发投入与产品线", "kind": "bullets", "bullets": ["研发投入6800万元", "研发人员126人", "产品线A贡献营收1.9亿元"]},
            {"title": "明年经营目标", "kind": "bullets", "bullets": ["2027年目标营收11亿元", "研发投入率保持8%以上", "以复核数据作为目标基线"]},
            {"title": "复盘结论", "kind": "bullets", "bullets": ["正式营收以财务复核数字为准", "华南是重点增长区域", "研发投入支撑产品线A"]},
        ]},
    },
    {
        "id": "outline-hard-contradictions", "level": "hard", "n": 7,
        "brief": "给董事会做一份多地区业务复盘，区分初步估算、已确认数字和外部传闻。",
        "material": ("截至 2026 年 9 月，确认营收 27.4 亿元，其中华东 11.8 亿元、华南 6.3 亿元、华北 4.1 亿元，"
                     "海外 3.2 亿元，其余区域 2.0 亿元。上半年报告曾写 26.9 亿元，已被审计更正。"
                     "活跃客户 8,400 家，续约率 76.5%；重点行业客户贡献 5.7 亿元。"
                     "市场部称行业平均增速 35%，但该数字尚未核实。四季度目标营收 10.2 亿元，续约率目标 80%。"),
        "must_numbers": ["27.4亿", "11.8亿", "6.3亿", "4.1亿", "3.2亿", "8400", "76.5%", "5.7亿", "10.2亿", "80%"],
        "must_terms": ["审计更正", "华东", "续约率", "四季度"], "check_numbers": True,
        "wrong_patterns": [[r"26\.9\s*亿", "用了已被审计更正的 26.9 亿", r"更正"],
                           [r"(?<![\d.])35\s*%", "写入尚未核实的行业增速 35%", r"尚未核实"]],
        "reference": {"slides": [
            {"title": "截至9月业务复盘", "bullets": ["董事会汇报"], "kind": "cover"},
            {"title": "确认营收27.4亿元", "kind": "chart", "bullets": ["截至9月确认营收27.4亿元", "上半年26.9亿元为已更正数字", "审计更正后只采用确认值"]},
            {"title": "多地区贡献", "kind": "chart", "bullets": ["华东11.8亿元，华南6.3亿元", "华北4.1亿元，海外3.2亿元", "其余区域2.0亿元"]},
            {"title": "客户经营质量", "kind": "bullets", "bullets": ["活跃客户8400家", "续约率76.5%", "重点行业客户贡献5.7亿元"]},
            {"title": "外部数据谨慎使用", "kind": "bullets", "bullets": ["行业平均增速35%尚未核实", "经营判断只使用内部确认数据", "避免把传闻写入结论"]},
            {"title": "四季度目标", "kind": "bullets", "bullets": ["目标营收10.2亿元", "续约率目标80%", "围绕重点行业客户制定计划"]},
            {"title": "董事会决策要点", "kind": "bullets", "bullets": ["保持华东领先并扩大华南", "提升续约率和客户质量", "四季度目标以确认数据为基线"]},
        ]},
    },
])

# --------------------------------------------------------------------------- condense (text)
CONDENSE = [
    {
        "id": "condense-service", "max_bullets": 4, "max_len": 24,
        "material": ("公司 2026 年 Q3 客服中心共处理工单 18.6 万张，同比增长 24%；平均首次响应时间从 4.2 小时缩短到 1.5 小时；"
                     "客户满意度为 92.3%，比上季度提升 3.1 个百分点；但夜间时段的投诉占比升至 37%，主要集中在退款流程。"),
        "must_numbers": ["18.6万", "1.5", "92.3%", "37%"],
        "reference": {"title": "Q3客服中心运营概况", "bullets": [
            "处理工单18.6万张，同比增长24%", "首次响应从4.2小时降至1.5小时",
            "满意度92.3%，提升3.1个百分点", "夜间投诉占比37%，集中在退款"]},
    },
    {
        "id": "condense-launch", "max_bullets": 4, "max_len": 24,
        "material": ("新版 App 上线 30 天，累计下载 52 万次，其中 iOS 占 58%；日活跃用户峰值 8.7 万；"
                     "崩溃率从 0.9% 降到 0.21%；最常用的功能是语音笔记，使用率达到 64%。"),
        "must_numbers": ["52万", "58%", "8.7万", "0.21%", "64%"],
        "reference": {"title": "新版App上线30天", "bullets": [
            "下载52万次，iOS占58%", "日活峰值8.7万", "崩溃率从0.9%降至0.21%", "语音笔记使用率64%"]},
    },
    {
        # hard: 环比/同比 must survive, and "个百分点" must not become "%" (0.4 pp != 0.4 %)
        "id": "condense-qualifier", "max_bullets": 4, "max_len": 22,
        "material": ("11 月 App 付费转化率为 4.6%，环比下降 0.4 个百分点，但同比仍上升 1.2 个百分点；"
                     "下降主要来自新用户，老用户转化率持平在 7.9%。安卓端退款申请 1,320 笔，比上月减少 15%。"),
        "must_numbers": ["4.6%", "0.4个百分点", "1.2个百分点", "7.9%", "1,320"],
        "must_terms": ["环比", "同比"],
        "wrong_patterns": [[r"(?<![\d.])0\.4\s*%", "把 0.4 个百分点写成了 0.4%"],
                           [r"(?<![\d.])1\.2\s*%", "把 1.2 个百分点写成了 1.2%"]],
        "reference": {"title": "11月付费转化概况", "bullets": [
            "转化率4.6%，环比降0.4个百分点", "同比仍上升1.2个百分点",
            "降幅来自新用户，老用户持平7.9%", "安卓退款1,320笔，环比减少15%"]},
    },
]

# A strict-length hard condensation case.
CONDENSE.append({
    "id": "condense-hard-tight", "level": "hard", "max_bullets": 3, "max_len": 16,
    "material": ("Q4 客服中心处理工单 21.4 万张，同比增长 18%；平均首次响应时间降至 1.2 小时；"
                 "客户满意度 94.1%，提升 2.8 个百分点；夜间投诉占比 31%，主要集中在退款和物流查询。"),
    "must_numbers": ["21.4万", "1.2", "94.1%", "31%"],
    "must_terms": ["客服", "夜间投诉"],
    "reference": {"title": "Q4客服运营", "bullets": ["工单21.4万张，增18%", "响应1.2小时，满意度94.1%", "夜间投诉占比31%"]},
})

# --------------------------------------------------------------------------- chart (data)
CHART = [
    {
        "id": "chart-quarter",
        "material": "公司 2026 年各季度营收：Q1 12.5 亿元，Q2 14.8 亿元，Q3 17.2 亿元，Q4 预计 19.6 亿元。去年全年营收 48.3 亿元，员工 1,260 人。",
        "ask": "做一张展示 2026 年各季度营收趋势的图，单位：亿元",
        "categories": ["Q1", "Q2", "Q3", "Q4"], "values": [12.5, 14.8, 17.2, 19.6],
        "good_types": ["column", "line", "bar"],
        "reference": {"chart_type": "column", "title": "2026年各季度营收", "unit": "亿元",
                      "categories": ["Q1", "Q2", "Q3", "Q4（预计）"],
                      "series": [{"name": "营收", "values": [12.5, 14.8, 17.2, 19.6]}], "takeaway": "营收逐季增长"},
    },
    {
        "id": "chart-units",
        "material": "各区域 Q3 营收：华东 71,000 万元，华南 3.2 亿元，华北 28,500 万元，西部 1.9 亿元。",
        "ask": "对比四个区域的 Q3 营收，单位统一为亿元",
        "categories": ["华东", "华南", "华北", "西部"], "values": [7.1, 3.2, 2.85, 1.9],
        "good_types": ["bar", "column"],
        "reference": {"chart_type": "bar", "title": "各区域Q3营收", "unit": "亿元",
                      "categories": ["华东", "华南", "华北", "西部"],
                      "series": [{"name": "Q3营收", "values": [7.1, 3.2, 2.85, 1.9]}], "takeaway": "华东遥遥领先"},
    },
    {
        "id": "chart-growth",
        "material": "公司年营收：2023 年 8 亿元，2024 年 10 亿元，2025 年 13 亿元，2026 年 16.9 亿元。",
        "ask": "展示 2024—2026 年每一年营收的同比增长率，单位：%",
        "categories": ["2024", "2025", "2026"], "values": [25, 30, 30], "tol": 0.5,
        "good_types": ["line", "column", "bar"],
        "reference": {"chart_type": "line", "title": "营收同比增长率", "unit": "%",
                      "categories": ["2024年", "2025年", "2026年"],
                      "series": [{"name": "同比增长率", "values": [25.0, 30.0, 30.0]}], "takeaway": "增速保持在30%"},
    },
    {
        "id": "chart-share",
        "material": "Q3 销售额按渠道划分：线上占 48%，门店占 29%，其余全部来自经销商。",
        "ask": "展示 Q3 各渠道销售额的占比，单位：%",
        "categories": ["线上", "门店", "经销"], "values": [48, 29, 23],
        "good_types": ["pie", "doughnut", "bar", "column"],
        "reference": {"chart_type": "pie", "title": "Q3渠道占比", "unit": "%",
                      "categories": ["线上", "门店", "经销商"],
                      "series": [{"name": "占比", "values": [48, 29, 23]}], "takeaway": "线上接近一半"},
    },
    {
        "id": "chart-nodata",
        "material": "今年团队氛围很好，客户评价普遍不错，大家都很努力。明年希望继续扩大市场。",
        "ask": "把团队今年的业绩做成一张柱状图",
        "skip": True,
        "reference": {"skip": True},
    },
    {
        # hard: two-step calculation (margin = (revenue - cost) / revenue), mixed units, a distractor
        # total, and the result must be sorted
        "id": "chart-margin",
        "material": ("Q3 各产品线：智能客服营收 1.8 亿元、成本 1.35 亿元；云账本营收 5.0 亿元、成本 3.1 亿元；"
                     "数据中台营收 2,400 万元、成本 1,560 万元。公司 Q3 总营收 17.2 亿元。"),
        "ask": "对比三条产品线的 Q3 毛利率，单位：%，按毛利率从高到低排列",
        "categories": ["云账本", "数据中台", "智能客服"], "values": [38, 35, 25], "tol": 0.5,
        "good_types": ["bar", "column"],
        "reference": {"chart_type": "bar", "title": "各产品线Q3毛利率", "unit": "%",
                      "categories": ["云账本", "数据中台", "智能客服"],
                      "series": [{"name": "毛利率", "values": [38.0, 35.0, 25.0]}], "takeaway": "云账本毛利率最高"},
    },
    {
        # hard: pick a sub-range out of a long series and leave out the forecast
        "id": "chart-filter",
        "material": ("2026 年每月新增用户（万人）：1 月 3.2，2 月 2.8，3 月 4.1，4 月 4.5，5 月 5.0，6 月 5.6，"
                     "7 月 6.3，8 月 6.9，9 月 6.1，10 月 7.4，11 月 8.0，12 月预计 8.8。"),
        "ask": "只展示 7—11 月实际的每月新增用户，单位：万人",
        "categories": ["7月", "8月", "9月", "10月", "11月"], "values": [6.3, 6.9, 6.1, 7.4, 8.0],
        "good_types": ["column", "line", "bar"],
        "reference": {"chart_type": "line", "title": "7—11月新增用户", "unit": "万人",
                      "categories": ["7月", "8月", "9月", "10月", "11月"],
                      "series": [{"name": "新增用户", "values": [6.3, 6.9, 6.1, 7.4, 8.0]}],
                      "takeaway": "9月回落后继续增长"},
    },
    {
        # hard: shares have to be computed from counts, the total is not given
        "id": "chart-convert",
        "material": "截至 11 月底各端注册用户：iOS 31.2 万，安卓 46.8 万，网页端 12 万。",
        "ask": "展示各端用户的占比，单位：%",
        "categories": ["iOS", "安卓", "网页端"], "values": [34.7, 52.0, 13.3], "tol": 0.1,
        "good_types": ["pie", "doughnut", "bar", "column"],
        "reference": {"chart_type": "pie", "title": "各端用户占比", "unit": "%",
                      "categories": ["iOS", "安卓", "网页端"],
                      "series": [{"name": "占比", "values": [34.7, 52.0, 13.3]}], "takeaway": "安卓用户过半"},
    },
    {
        # hard: data exists but one required point is only described vaguely -> must refuse, not guess
        "id": "chart-partial",
        "material": "2026 年 Q1 营收 12.5 亿元；Q2 营收较 Q1 有所增长，具体数字待财务确认；Q3 营收 17.2 亿元。",
        "ask": "做一张 2026 年 Q1、Q2、Q3 三个季度营收的柱状图，单位：亿元",
        "skip": True,
        "reference": {"skip": True},
    },
]

# Hard chart cases require multiple series and a two-step calculation.
CHART.extend([
    {
        "id": "chart-hard-multiseries", "level": "hard",
        "material": ("三大区域 2025 年营收：华东 6.0 亿元、华南 2.5 亿元、海外 1.2 亿元；"
                     "2026 年营收：华东 7.2 亿元、华南 3.4 亿元、海外 1.8 亿元。"),
        "ask": "用两条系列对比三大区域 2025 和 2026 年营收，单位：亿元",
        "categories": ["华东", "华南", "海外"], "values": [6.0, 2.5, 1.2],
        "series_values": [[6.0, 2.5, 1.2], [7.2, 3.4, 1.8]], "good_types": ["bar", "column"],
        "reference": {"chart_type": "column", "title": "区域营收对比", "unit": "亿元",
                      "categories": ["华东", "华南", "海外"],
                      "series": [{"name": "2025年", "values": [6.0, 2.5, 1.2]},
                                  {"name": "2026年", "values": [7.2, 3.4, 1.8]}],
                      "takeaway": "三大区域均增长"},
    },
    {
        "id": "chart-hard-twostep", "level": "hard",
        "material": ("三条产品线收入和成本：智能硬件收入 4.8 亿元、成本 3.1 亿元；"
                     "云服务收入 2.6 亿元、成本 1.82 亿元；专业服务收入 1.2 亿元、成本 0.9 亿元。"),
        "ask": "先用（收入－成本）/收入计算毛利率，再按毛利率从高到低对比，单位：%",
        "categories": ["智能硬件", "云服务", "专业服务"], "values": [35.4, 30.0, 25.0], "tol": 0.1,
        "good_types": ["bar", "column"],
        "reference": {"chart_type": "bar", "title": "产品线毛利率", "unit": "%",
                      "categories": ["智能硬件", "云服务", "专业服务"],
                      "series": [{"name": "毛利率", "values": [35.4, 30.0, 25.0]}],
                      "takeaway": "智能硬件毛利率最高"},
    },
])

# --------------------------------------------------------------------------- layout
# Text elements list their paragraphs; "visual" elements have no text.
LAYOUT = [
    {
        "id": "layout-chart", "desc": "左边是要点，右边是一张柱状图",
        "elements": {"title": ["营收同比增长 32%"],
                     "body": ["华东区贡献最大", "新产品线占比 18%", "毛利率提升 3 个点"],
                     "visual": None},
        "reference": {"elements": [
            {"role": "title", "x": 0.6, "y": 0.5, "w": 12.13, "h": 1.0, "font_size": 36},
            {"role": "body", "x": 0.6, "y": 1.8, "w": 5.2, "h": 5.0, "font_size": 20},
            {"role": "visual", "x": 6.2, "y": 1.8, "w": 6.53, "h": 5.0}]},
    },
    {
        "id": "layout-hero", "desc": "大幅配图页，配图至少占画面的 35%",
        "elements": {"title": ["我们的愿景"], "body": ["让每个人十分钟做出专业汇报"], "visual": None},
        "min_area": {"visual": 0.35},
        "reference": {"elements": [
            {"role": "title", "x": 0.6, "y": 0.6, "w": 5.4, "h": 1.0, "font_size": 40},
            {"role": "body", "x": 0.6, "y": 1.9, "w": 5.4, "h": 1.6, "font_size": 22},
            {"role": "visual", "x": 6.4, "y": 0.6, "w": 6.5, "h": 6.3}]},
    },
    {
        "id": "layout-cards", "desc": "标题下面四张大小一致的能力卡片",
        "elements": {"title": ["四大核心能力"],
                     "card1": ["智能大纲", "一句话生成结构清晰的大纲"],
                     "card2": ["数据图表", "自动识别数字并生成原生图表"],
                     "card3": ["多模型分工", "每页交给最擅长的模型完成"],
                     "card4": ["事实核查", "自动拦截资料里没有的数字"]},
        "uniform": ["card1", "card2", "card3", "card4"],
        "reference": {"elements": [
            {"role": "title", "x": 0.6, "y": 0.5, "w": 12.13, "h": 1.0, "font_size": 36},
            {"role": "card1", "x": 0.6, "y": 1.8, "w": 5.85, "h": 2.4, "font_size": 20},
            {"role": "card2", "x": 6.85, "y": 1.8, "w": 5.85, "h": 2.4, "font_size": 20},
            {"role": "card3", "x": 0.6, "y": 4.6, "w": 5.85, "h": 2.4, "font_size": 20},
            {"role": "card4", "x": 6.85, "y": 4.6, "w": 5.85, "h": 2.4, "font_size": 20}]},
    },
    {
        "id": "layout-dense", "desc": "左侧是较多的文字要点，右侧放一张配图（至少占画面 25%）",
        "elements": {"title": ["Q3 经营问题清单"],
                     "body": ["人力成本同比增长 27%，明显快于营收增速，持续压缩利润空间，需要尽快制定控制方案",
                              "华南区营收仅 3.2 亿元，渠道覆盖不足，新客户获取成本偏高，增长明显乏力",
                              "夜间客服投诉占比升至 37%，主要集中在退款处理流程，客户等待时间过长",
                              "新产品线灵犀交付周期偏长，部分大客户续约存在风险，需要增加交付人手",
                              "跨部门协作依赖线下会议，重要决策平均耗时超过两周，影响市场响应速度",
                              "核心研发人员流失率上升，关键模块缺少备份负责人，存在较大的交付隐患",
                              "数据口径在各部门之间不一致，经营分析报表反复返工，管理层难以及时决策"],
                     "visual": None},
        "min_area": {"visual": 0.25},
        "reference": {"elements": [
            {"role": "title", "x": 0.6, "y": 0.5, "w": 12.13, "h": 0.9, "font_size": 32},
            {"role": "body", "x": 0.6, "y": 1.6, "w": 6.6, "h": 5.4, "font_size": 16},
            {"role": "visual", "x": 7.5, "y": 1.6, "w": 5.4, "h": 5.4}]},
    },
    {
        # hard: each caption must sit directly under its own chart; both charts the same size
        "id": "layout-captions", "desc": "两张并排的对比图表，每张图下方紧贴一行说明文字",
        "elements": {"title": ["两年区域营收对比"],
                     "chart1": None, "caption1": ["2025 年各区域营收"],
                     "chart2": None, "caption2": ["2026 年各区域营收"]},
        "uniform": ["chart1", "chart2"],
        "below": {"caption1": "chart1", "caption2": "chart2"},
        "reference": {"elements": [
            {"role": "title", "x": 0.6, "y": 0.5, "w": 12.13, "h": 1.0, "font_size": 36},
            {"role": "chart1", "x": 0.6, "y": 1.8, "w": 5.9, "h": 4.2},
            {"role": "caption1", "x": 0.6, "y": 6.1, "w": 5.9, "h": 0.6, "font_size": 16},
            {"role": "chart2", "x": 6.83, "y": 1.8, "w": 5.9, "h": 4.2},
            {"role": "caption2", "x": 6.83, "y": 6.1, "w": 5.9, "h": 0.6, "font_size": 16}]},
    },
    {
        # hard: five equal boxes in one row, left to right in time order, and the text must still fit
        "id": "layout-timeline", "desc": "发展历程时间轴：五个里程碑在同一行从左到右排列，大小一致",
        "elements": {"title": ["发展历程"],
                     "step1": ["2022", "公司成立，推出首款产品"],
                     "step2": ["2023", "用户突破 10 万"],
                     "step3": ["2024", "完成 A 轮融资"],
                     "step4": ["2025", "进入华南市场"],
                     "step5": ["2026", "营收突破 60 亿元"]},
        "uniform": ["step1", "step2", "step3", "step4", "step5"],
        "row": ["step1", "step2", "step3", "step4", "step5"],
        "reference": {"elements": [
            {"role": "title", "x": 0.6, "y": 0.5, "w": 12.13, "h": 1.0, "font_size": 36},
            {"role": "step1", "x": 0.5, "y": 2.6, "w": 2.3, "h": 2.0, "font_size": 16},
            {"role": "step2", "x": 3.0, "y": 2.6, "w": 2.3, "h": 2.0, "font_size": 16},
            {"role": "step3", "x": 5.5, "y": 2.6, "w": 2.3, "h": 2.0, "font_size": 16},
            {"role": "step4", "x": 8.0, "y": 2.6, "w": 2.3, "h": 2.0, "font_size": 16},
            {"role": "step5", "x": 10.5, "y": 2.6, "w": 2.3, "h": 2.0, "font_size": 16}]},
    },
]

# Hard layout case: seven elements in a tight two-row grid.
LAYOUT.append({
    "id": "layout-hard-tight", "level": "hard", "desc": "六个信息块在标题下方两行三列紧凑排布，所有文字清晰可读",
    "elements": {"title": ["经营重点"],
                 "block1": ["营收同比增长24%", "保持增长"],
                 "block2": ["毛利率38.5%", "利润承压"],
                 "block3": ["客户8400家", "规模扩大"],
                 "block4": ["续约率76.5%", "需要提升"],
                 "block5": ["研发投入6800万元", "支撑产品"],
                 "block6": ["Q4目标10.2亿元", "聚焦执行"]},
    "uniform": ["block1", "block2", "block3", "block4", "block5", "block6"],
    "reference": {"elements": [
        {"role": "title", "x": 0.6, "y": 0.45, "w": 12.13, "h": 0.8, "font_size": 32},
        {"role": "block1", "x": 0.6, "y": 1.7, "w": 3.85, "h": 2.1, "font_size": 18},
        {"role": "block2", "x": 4.74, "y": 1.7, "w": 3.85, "h": 2.1, "font_size": 18},
        {"role": "block3", "x": 8.88, "y": 1.7, "w": 3.85, "h": 2.1, "font_size": 18},
        {"role": "block4", "x": 0.6, "y": 4.2, "w": 3.85, "h": 2.1, "font_size": 18},
        {"role": "block5", "x": 4.74, "y": 4.2, "w": 3.85, "h": 2.1, "font_size": 18},
        {"role": "block6", "x": 8.88, "y": 4.2, "w": 3.85, "h": 2.1, "font_size": 18},
    ]},
})

IMAGE = [
    {"id": "image-cover", "prompt": "简洁的科技感 PPT 封面插画，蓝色调，抽象的数据流线条，没有文字，16:9"},
]


def _revise_wrong_number_removed(ctx):
    return "18.5" not in ctx["text"]


def _revise_wrong_number_fixed(ctx):
    return "17.2" in ctx["text"]


def _revise_long_title_fixed(ctx):
    return ctx["titles_within_16"]


def _revise_fabrication_removed(ctx):
    return "5个城市" not in ctx["text"] and "5 个城市" not in ctx["text"]


def _revise_fabrication_fixed(ctx):
    return "2个城市" in ctx["text"] or "2 个城市" in ctx["text"]


def _revise_slide_count_fixed(ctx):
    return len(ctx["slides"]) == 8


def _revise_pitch_number_removed(ctx):
    return "43万" not in ctx["text"] and "43 万" not in ctx["text"]


def _revise_pitch_number_fixed(ctx):
    return "42万" in ctx["text"] or "42 万" in ctx["text"]


def _revise_long_bullet_fixed(ctx):
    return ctx["bullets_within_28"]


_REVIEW_REFERENCE = next(c["reference"] for c in OUTLINE if c["id"] == "outline-review")
_PITCH_REFERENCE = next(c["reference"] for c in OUTLINE if c["id"] == "outline-pitch")
_REVIEW_FLAWED = copy.deepcopy(_REVIEW_REFERENCE)
_REVIEW_FLAWED["slides"][1]["bullets"][0] = "Q3营收18.5亿元，环比增长16.2%"
_REVIEW_FLAWED["slides"][2]["title"] = "华东是本季度最重要的营收来源区域分析"
_REVIEW_FLAWED["slides"][5]["bullets"].append("华南新增5个城市办事处")
_PITCH_FLAWED = copy.deepcopy(_PITCH_REFERENCE)
_PITCH_FLAWED["slides"][3]["bullets"][0] = "注册用户43万"
_PITCH_FLAWED["slides"][6]["bullets"][0] = "本轮计划在天使轮融资人民币三千万元以支撑研发和市场推广方向投入"
_PITCH_FLAWED["slides"].insert(7, {"title": "补充说明", "bullets": ["详见附件"], "kind": "bullets"})

REVISE = [
    {
        "id": "revise-review",
        "brief": "给公司管理层做一份《2026年第三季度经营复盘》，听众是 CEO 和各部门负责人。",
        "material": next(c["material"] for c in OUTLINE if c["id"] == "outline-review"),
        "n": 6,
        "flawed": _REVIEW_FLAWED,
        "errors": [
            {"id": "wrong_number", "desc": "营收数字 18.5 亿应改为 17.2 亿",
             "check_removed": _revise_wrong_number_removed, "check_fixed": _revise_wrong_number_fixed},
            {"id": "long_title", "desc": "某页标题超过 16 字，应改短",
             "check_fixed": _revise_long_title_fixed},
            {"id": "fabrication", "desc": "5个城市办事处是编造的，资料只说新增2个",
             "check_removed": _revise_fabrication_removed, "check_fixed": _revise_fabrication_fixed},
        ],
        "must_numbers": ["17.2亿", "38.5%", "4.6亿", "3.4亿", "19亿"],
        "must_terms": ["华东", "人力成本", "灵犀"],
        "check_numbers": True,
        "reference": copy.deepcopy(_REVIEW_REFERENCE),
    },
    {
        "id": "revise-pitch",
        "brief": "给天使投资人做一份融资路演 PPT，时间 10 分钟。",
        "material": next(c["material"] for c in OUTLINE if c["id"] == "outline-pitch"),
        "n": 8,
        "flawed": _PITCH_FLAWED,
        "errors": [
            {"id": "wrong_slide_count", "desc": "共9页，应为8页",
             "check_fixed": _revise_slide_count_fixed},
            {"id": "wrong_number", "desc": "注册用户 43 万应改为 42 万",
             "check_removed": _revise_pitch_number_removed, "check_fixed": _revise_pitch_number_fixed},
            {"id": "long_bullet", "desc": "某条要点超过 28 字，应改短",
             "check_fixed": _revise_long_bullet_fixed},
        ],
        "must_numbers": ["42万", "15.6万", "3.8%", "3000万"],
        "must_terms": ["课记", "竞品", "研发"],
        "check_numbers": True,
        "reference": copy.deepcopy(_PITCH_REFERENCE),
    },
]


# --------------------------------------------------------------------------- prompts
SYS = "你是一名专业的演示文稿设计师。只输出 JSON，不要输出任何解释。"

OUTLINE_PROMPT = """[task:outline]
请为下面的需求写一份 PPT 大纲，正好 N={n} 页。
需求与资料：
{brief}

要求：
- 第一页是封面；
- 每页标题不超过 16 个字；除封面外每页 3-5 条要点，每条不超过 28 个字；
- 用上资料里的关键数字；所有数字必须来自资料，或由资料里的数字直接算出，不能编造；
- 推算数字保留的小数位数不能多于原始资料，禁止输出多余精度（例如 17.2 × 38.5% 应写 6.6 亿元，不写 6.622 亿元）；
- 不要在要点中写算式、乘除等号或“测算口径”说明；每条要点都要是一句完整、通顺的话；
- kind 从 cover / bullets / chart / image / quote 中选一个，表示这页最适合的形式。
输出格式：{{"slides": [{{"title": "...", "bullets": ["..."], "kind": "bullets"}}]}}"""

REVISE_PROMPT = """[task:revise]
下面这份大纲有若干问题，请找出并修正，输出修正后的完整大纲。
需求：{brief}
资料：{material}
要求：共 {n} 页，每页标题不超过 16 字，除封面外每页 3–5 条要点，每条不超过 28 字，所有数字必须来自资料或可由资料数字直接算出。
只改有问题的部分，不要改动正确的内容。

有问题的大纲：
{flawed_json}

输出格式：{{"slides": [{{"title": "...", "bullets": ["..."], "kind": "bullets"}}]}}"""

CONDENSE_PROMPT = """[task:condense]
把下面这段文字压缩成一页 PPT：一个不超过 16 字的标题，3-{max_bullets} 条要点，每条不超过 {max_len} 个字。
必须保留其中的关键数字，不能编造资料里没有的数字。
资料：{material}
输出格式：{{"title": "...", "bullets": ["..."]}}"""

CHART_PROMPT = """[task:chart]
把资料中的数据整理成一张 PPT 图表。
资料：{material}
要求：{ask}

规则：
- values 只填数字，单位按要求统一换算；
- 只放与要求相关的数据，不要放无关的数字；
- 需要计算的请算准确，保留 1 位小数；
- 推算结果的小数位数不能多于原始数据；不要把计算过程、×、÷、= 或“测算口径”写进图表标题、结论或标签；
- takeaway 必须是一句简短结论；其中的数字必须能在图表数据中找到或由图表数据直接推算，增长/下降等方向必须与数据一致；
- 如果资料里没有足够的数据画这张图，只输出 {{"skip": true}}，不要编造。
chart_type 从 bar / column / line / pie / doughnut 中选。
输出格式：{{"chart_type": "column", "title": "...", "unit": "...", "categories": ["..."], "series": [{{"name": "...", "values": [1.0]}}], "takeaway": "一句话结论"}}"""

LAYOUT_PROMPT = """[task:layout]
画布宽 13.333 英寸、高 7.5 英寸，原点在左上角，四周至少留 0.4 英寸边距。
请为这一页安排元素的位置和字号：{desc}
元素列表（冒号前是元素名，冒号后是它的文字内容）：
{elements}

要求：
- 每个元素输出一项，role 必须原样使用上面的元素名（如 title、body、visual），不要改名或合并；
- 元素不能超出边距，彼此不能重叠；
- 文字必须完整放得下：中文每个字宽约等于字号，英文和数字约为字号的一半，行高约 1.25 倍字号，72 磅 = 1 英寸，文本框内边距约 0.1 英寸；
- 标题字号 28-44 磅，其他文字 14-24 磅；visual 不需要字号。
输出格式：{{"elements": [{{"role": "title", "x": 0.6, "y": 0.5, "w": 12, "h": 1, "font_size": 36}}]}}"""

PAIRWISE_PROMPT = """[task:pairwise]
你是严格的演示文稿评审。下面是针对同一需求的两份 PPT 大纲（A 和 B）。请只比较内容质量：
1. 是否用上了资料里最重要的信息和数字，且数字准确；
2. 结构是否清楚、是否适合听众；
3. 要点是否具体、能讲出内容。
不要因为篇幅长短或排列先后而偏向任何一方；出现资料里没有的数字的大纲应判负。

需求与资料：
{brief}

【大纲 A】
{a}

【大纲 B】
{b}

只输出 JSON：{{"winner": "A" 或 "B" 或 "tie", "reason": "不超过 40 字"}}"""

VISUAL_PAIRWISE_PROMPT = """[task:visual_pairwise]
你是严格的演示文稿视觉设计评审。附上的两张图是同一页 PPT 的两种排版：第 1 张是 A，第 2 张是 B。
两版的文字内容完全相同，只是位置、大小和字号不同。灰底蓝色柱子是图表或图片的占位；红色文字表示溢出了文本框。
这一页的要求：{desc}

请只比较视觉效果：
1. 文字是否清晰易读、没有溢出；
2. 对齐是否整齐，留白是否均衡，画面有没有大片空着或挤成一团；
3. 标题、正文、图片的主次是否清楚，是否满足这一页的要求。
不要因为图片的先后顺序偏向任何一方。

只输出 JSON：{{"winner": "A" 或 "B" 或 "tie", "reason": "不超过 40 字"}}"""


def layout_elements_text(case: dict) -> str:
    lines = []
    for role, paras in case["elements"].items():
        if paras is None:
            lines.append(f"- {role}：图片或图表（无文字）")
        else:
            lines.append(f"- {role}：" + " / ".join(paras))
    return "\n".join(lines)


def outline_brief(case: dict) -> str:
    return f"{case['brief']}\n资料：{case['material']}"
