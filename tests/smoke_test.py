"""End-to-end smoke test without real API keys.

Starts a fake OpenAI-compatible server and a fake Anthropic server on localhost, registers them as
models, then exercises: ping -> benchmark -> deck build -> web API. Run:  python tests/smoke_test.py
"""
from __future__ import annotations

import base64
import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ["SLIDEARENA_HOME"] = tempfile.mkdtemp(prefix="sa_smoke_")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from slidearena import benchmark, config, deck, server  # noqa: E402

SEEN = {"openai_auth": None, "anthropic_key": None, "anthropic_version": None}


def _case_for(prompt: str):
    from slidearena import cases as C
    from slidearena.generate import REGISTRY
    for bank in (C.REVISE, C.OUTLINE, C.CONDENSE, C.CHART, C.LAYOUT, list(REGISTRY.values())):
        for c in bank:
            if C.matches_prompt(c, prompt):
                return c
    return None


def fake_answer(prompt: str) -> str:
    """A perfect model: answers benchmark questions with the reference answer."""
    if "[task:ping]" in prompt:
        return "pong"
    # judge prompts quote the case material, so answer them before the case lookup below
    if "[task:pairwise]" in prompt:
        # an honest outline judge: the outline with fewer invented numbers wins
        from slidearena import facts
        m = re.search(r"需求与资料：\s*(.*?)【大纲 A】(.*?)【大纲 B】(.*?)只输出", prompt, re.S)
        src = facts.Source(m.group(1))
        a, b = len(src.unsupported(m.group(2))), len(src.unsupported(m.group(3)))
        return '{"winner": "%s", "reason": "数字更可靠"}' % ("tie" if a == b else "A" if a < b else "B")
    if "[task:visual_pairwise]" in prompt:
        SEEN["visual_judge_images"] = SEEN.get("visual_judge_images", 0) + 1
        return '{"winner": "B", "reason": "留白更均衡"}'
    case = _case_for(prompt)
    if case is not None and "[task:" in prompt:
        return "好的：\n```json\n" + json.dumps(case["reference"], ensure_ascii=False) + "\n```"
    if "[task:outline]" in prompt:       # deck building from a free brief
        n = int(re.search(r"N=(\d+)", prompt).group(1))
        slides = [{"title": "季度复盘", "bullets": ["管理层汇报"], "kind": "cover"}]
        for i in range(1, n):
            slides.append({"title": f"要点{i}", "bullets": ["营收增长", "成本下降", "下季计划"],
                           "kind": "chart" if i == 2 else "bullets"})
        slides[3]["bullets"][0] = "人力成本5.3亿元"   # invented number: deck builder must catch it
        return json.dumps({"slides": slides}, ensure_ascii=False)
    if "[task:fix]" in prompt:
        return json.dumps({"bullets": ["人力成本上涨较快", "成本下降", "下季计划"]}, ensure_ascii=False)
    if "[task:chart]" in prompt:
        nums = re.findall(r"(\d+(?:\.\d+)?)\s*亿", prompt)
        cats = re.findall(r"Q\d", prompt)[:len(nums)]
        vals = [float(x) for x in nums][:len(cats)]
        return json.dumps({"chart_type": "column", "title": "营收", "categories": cats,
                           "series": [{"name": "营收", "values": vals}], "takeaway": "持续增长"}, ensure_ascii=False)
    return "ok"


def tiny_png() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 40), (40, 90, 200)).save(buf, "PNG")
    return buf.getvalue() * 20  # >1000 bytes is all the benchmark checks


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path.endswith("/chat/completions"):
            SEEN["openai_auth"] = self.headers.get("Authorization")
            msg = body["messages"][-1]["content"]
            text = msg if isinstance(msg, str) else " ".join(p.get("text", "") for p in msg)
            if not isinstance(msg, str) and sum(p.get("type") == "image_url" for p in msg) == 2:
                SEEN["saw_image_parts"] = True
            out = {"choices": [{"message": {"content": fake_answer(text)}}], "usage": {"prompt_tokens": 10, "completion_tokens": 20}}
        elif self.path.endswith("/v1/messages"):
            SEEN["anthropic_key"] = self.headers.get("x-api-key")
            SEEN["anthropic_version"] = self.headers.get("anthropic-version")
            assert "system" in body or True
            msg = body["messages"][-1]["content"]
            text = msg if isinstance(msg, str) else " ".join(p.get("text", "") for p in msg)
            if not isinstance(msg, str) and sum(p.get("type") == "image" for p in msg) == 2:
                SEEN["saw_image_parts"] = True
            out = {"content": [{"type": "text", "text": fake_answer(text)}], "usage": {"input_tokens": 10, "output_tokens": 20}}
        elif self.path.endswith("/images/generations"):
            out = {"data": [{"b64_json": base64.b64encode(tiny_png()).decode()}]}
        else:
            self.send_response(404)
            self.end_headers()
            return
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def http(url, body=None, headers=None):
    request_headers = {"Content-Type": "application/json"} if body is not None else {}
    request_headers.update(headers or {})
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(),
                                 headers=request_headers, method="GET" if body is None else "POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        SEEN["last_cors_header"] = r.headers.get("Access-Control-Allow-Origin")
        return r.status, r.read()


def check(cond, msg):
    print(("PASS  " if cond else "FAIL  ") + msg)
    if not cond:
        global FAILED
        FAILED = True


FAILED = False


def main():
    version = subprocess.run([sys.executable, "-m", "slidearena", "--version"], capture_output=True,
                             text=True, check=False)
    check(version.returncode == 0 and version.stdout.strip().endswith("0.1.0"), "CLI --version 显示 0.1.0")

    fake = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=fake.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{fake.server_port}"

    os.environ["SA_TEST_KEY"] = "sk-from-env"
    oa = config.upsert_model({"name": "假OpenAI", "protocol": "openai", "base_url": base + "/v1",
                              "model": "fake-gpt", "api_key": "env:SA_TEST_KEY", "can_image": True})
    an = config.upsert_model({"name": "假Claude", "protocol": "anthropic", "base_url": base,
                              "model": "fake-claude", "api_key": "sk-ant-secret-1234"})
    bad = config.upsert_model({"name": "连不上", "protocol": "openai", "base_url": "http://127.0.0.1:1/v1",
                               "model": "x", "api_key": "k"})

    p1, p2, p3 = benchmark.ping(oa), benchmark.ping(an), benchmark.ping(bad)
    check(p1["ok"] and p1["reply"] == "pong", f"OpenAI 协议连通 {p1}")
    check(p2["ok"] and p2["reply"] == "pong", f"Anthropic 协议连通 {p2}")
    check(not p3["ok"], f"错误地址返回失败而不是崩溃: {p3.get('error', '')[:60]}")
    check(SEEN["openai_auth"] == "Bearer sk-from-env", "env: 形式的 Key 被正确读取并发送")
    check(SEEN["anthropic_key"] == "sk-ant-secret-1234" and SEEN["anthropic_version"], "Anthropic 请求头正确")

    judge = config.upsert_model({"name": "假裁判", "protocol": "openai", "base_url": base + "/v1",
                                 "model": "fake-judge", "api_key": "env:SA_TEST_KEY"})
    r = benchmark.run([oa["id"], an["id"], bad["id"]], judge_ids=[oa["id"], an["id"], judge["id"]],
                      progress=lambda m: None)
    revise_records = [record for record in r["records"] if record.get("kind") == "revise"]
    revise_tasks = {record.get("task") for record in revise_records}
    check(r["bank_version"] == "2026.11-c" and r["question_count"] == 41 and r["generated_count"] == 10 and
          r["seed"] and
          revise_tasks == {"revise-review", "revise-pitch"} and
          isinstance(r["case_stats"], list) and all("range" in item and "stdev" in item for item in r["case_stats"]),
          f"benchmark 结果包含题库版本、出题批次、两道大纲改错题和逐题区分度（题数 {r['question_count']}：31 道人工题 + 10 道生成题，改错题 {sorted(revise_tasks)}）")
    s = r["scores"]
    d_oa = s[oa["id"]]["dims"]
    check(all(d_oa[k]["score"] == 100 for k in ("text", "chart", "layout")),
          f"满分模型经 HTTP 全链路后三项都是 100 分 {[(k, d_oa[k]['score']) for k in ('text', 'chart', 'layout')]}")
    check(d_oa.get("image", {}).get("score") == 100 and "image" not in s[an["id"]]["dims"], "只有可出图模型参与配图测试")
    check(bad["id"] not in s and [x["id"] for x in r["excluded"]] == [bad["id"]],
          "连不上的模型在开测前被排除，不影响其他模型")
    jd = r["judging"]
    check(all(p["judge"] != p["model"] for p in jd["log"]), "对比参考答案评审里模型不会评自己的答案")
    by = jd.get("by_dim", {})
    cal = jd.get("calibration", {})
    check(by.get("text", 0) > 0 and cal.get("text") and all(c["passed"] for c in cal["text"].values()),
          f"诚实的大纲裁判通过对照题校验并完成评审 {by}")
    check(SEEN.get("visual_judge_images", 0) > 0 and SEEN.get("saw_image_parts"), "排版截图以图片形式发给了评审模型")
    # the fake visual judge always picks the second picture: it cannot tell the reference from a broken
    # copy, so calibration must keep it out of layout judging
    check(cal.get("layout") and not any(c["passed"] for c in cal["layout"].values())
          and not by.get("layout") and jd["modes"].get("layout") == "none",
          "总选同一位置的视觉裁判没通过对照题校验，不参与排版评审")
    check("sk-ant-secret" not in json.dumps(r, ensure_ascii=False), "测试结果里不包含明文 Key")
    check(benchmark.route("text", [oa, an]) is not None, "路由能在已测模型中选出执行者")

    out = deck.build("营收 Q1 12.5 亿、Q2 14.8 亿、Q3 17.2 亿，做经营复盘", 5, [oa["id"], an["id"]], progress=lambda m: None)
    from pptx import Presentation
    prs = Presentation(out["path"])
    charts = [sh for sl in prs.slides for sh in sl.shapes if sh.has_chart]
    pics = [sh for sl in prs.slides for sh in sl.shapes if sh.shape_type == 13]
    all_text = "\n".join(sh.text_frame.text for sl in prs.slides for sh in sl.shapes if sh.has_text_frame)
    check(len(prs.slides) == 5, f"生成 PPT 共 {len(prs.slides)} 页")
    check(len(charts) == 1 and list(charts[0].chart.plots[0].categories) == ["Q1", "Q2", "Q3"],
          "图表页是原生可编辑图表，数据与原文一致")
    check(len(pics) == 1, "封面插入了配图")
    check("5.3" not in all_text and out["fact_check"]["fixed"], f"大纲里编造的数字被核查并改写 {out['fact_check']}")

    # Deck quality guards: text pages use larger, vertically centered text and
    # preserve source numbers in the metric cards; chart labels and units stay editable.
    quality_path = Path(tempfile.mkdtemp(prefix="sa_quality_")) / "quality.pptx"
    deck.render([{"title": "封面", "bullets": ["演示"], "made_by": {}},
                 {"title": "关键经营指标", "bullets": ["营收17.2亿元", "毛利率38.5%", "人力成本4.6亿元"],
                  "made_by": {}}], quality_path, "关键经营指标")
    quality_prs = Presentation(quality_path)
    quality_text = "\n".join(sh.text for sh in quality_prs.slides[1].shapes if sh.has_text_frame)
    body_sizes = [run.font.size.pt for sh in quality_prs.slides[1].shapes
                  if sh.has_text_frame and "营收17.2亿元" in sh.text
                  for paragraph in sh.text_frame.paragraphs for run in paragraph.runs if run.font.size]
    check("17.2亿元" in quality_text and "38.5%" in quality_text and len(body_sizes) > 0 and max(body_sizes) >= 24,
          "纯文字页保留关键数字并使用大字号")
    chart_slide = [{"title": "封面", "bullets": ["演示"], "made_by": {}}, {"title": "营收趋势", "bullets": ["营收持续增长"], "chart": {
        "chart_type": "column", "unit": "亿元", "categories": ["Q1", "Q2"],
        "series": [{"name": "营收", "values": [12.5, 14.8]}], "takeaway": "逐季增长"}, "made_by": {}}]
    chart_path = quality_path.parent / "chart.pptx"
    deck.render(chart_slide, chart_path, "营收趋势")
    chart_prs = Presentation(chart_path)
    chart_obj = next(sh.chart for sh in chart_prs.slides[1].shapes if sh.has_chart)
    check(chart_obj.plots[0].has_data_labels and chart_obj.value_axis.has_title and
          chart_obj.value_axis.axis_title.text_frame.text == "亿元", "图表显示数据标签和数值轴单位")
    outline = [{"title": "精度检查", "bullets": ["测算口径：17.2×38.5%=6.622亿元", "营收17.2亿元"]}]
    deck.verify_outline(outline, "营收17.2亿元，毛利率38.5%", None, lambda _msg: None)
    check(outline[0]["bullets"] == ["营收17.2亿元"], "算式和口径说明会被删除")
    precise = [{"title": "精度检查", "bullets": ["推算结果为6.622亿元"]}]
    deck.verify_outline(precise, "营收17.2亿元，毛利率38.5%", None, lambda _msg: None)
    check(precise[0]["bullets"] == ["推算结果为6.6亿元"], "推算数字按资料精度四舍五入")

    fake_chart = {"categories": ["Q1", "Q2"], "series": [{"name": "成本", "values": [3.2, 4.1]}]}
    real_chart = {"categories": ["Q1", "Q2"], "series": [{"name": "营收", "values": [12.5, 14.8]}]}
    brief = "营收 Q1 12.5 亿、Q2 14.8 亿"
    check(deck.unsupported_values(fake_chart, brief) == [3.2, 4.1] and not deck.unsupported_values(real_chart, brief),
          "资料里没有的数字会被识别为编造数据")
    seen_charts = set()
    check(deck._register_chart(real_chart, seen_charts) and not deck._register_chart(real_chart, seen_charts),
          "分类和数值完全重复的图表会被改成文字页")

    srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    web = f"http://127.0.0.1:{srv.server_port}"
    original_open = server.webbrowser.open

    def fail_to_open(_url):
        raise OSError("headless environment")

    server.webbrowser.open = fail_to_open
    browser_log = io.StringIO()
    with contextlib.redirect_stdout(browser_log):
        server._open_browser(web)
    server.webbrowser.open = original_open
    check("请手动访问" in browser_log.getvalue(), "无图形环境下浏览器失败不会使服务退出")
    code, html = http(web + "/")
    check(code == 200 and b"SlideArena" in html, "网页首页可以打开")
    wrong_port = str(srv.server_port + 1)
    try:
        http(web + "/api/models", headers={"Host": f"127.0.0.1:{wrong_port}"})
        check(False, "错误端口的 Host 被拒绝")
    except urllib.error.HTTPError as e:
        check(e.code == 403 and json.loads(e.read()).get("error"), "错误端口的 Host 返回 JSON 403")
    try:
        http(web + "/api/demo", {}, {"Origin": "http://evil.example"})
        check(False, "伪造 Origin 的 POST 被拒绝")
    except urllib.error.HTTPError as e:
        data = json.loads(e.read())
        check(e.code == 403 and "error" in data, "伪造 Origin 的 POST 返回 JSON 403")
    try:
        http(web + "/api/models", headers={"Host": "evil.example"})
        check(False, "伪造 Host 的 GET 被拒绝")
    except urllib.error.HTTPError as e:
        data = json.loads(e.read())
        check(e.code == 403 and "error" in data, "伪造 Host 的 GET 返回 JSON 403")
    normal_post, normal_body = http(web + "/api/demo", {}, {"Origin": web})
    check(normal_post == 200 and "added" in json.loads(normal_body), "正常 JSON POST 仍可用")
    check(SEEN.get("last_cors_header") is None, "API 响应没有 CORS 允许头")
    try:
        oversized = urllib.request.Request(web + "/api/demo", data=None,
                                            headers={"Content-Type": "application/json", "Origin": web,
                                                     "Content-Length": str(1024 * 1024 + 1)}, method="POST")
        with urllib.request.urlopen(oversized, timeout=30) as response:
            response.read()
        check(False, "超大请求体被拒绝")
    except urllib.error.HTTPError as e:
        check(e.code == 413 and json.loads(e.read()).get("error"), "超大请求体返回 JSON 413")
    try:
        http(web + "/api/benchmark", {"model_ids": [oa["id"]], "repeats": "abc"}, {"Origin": web})
        check(False, "repeats 非数字被拒绝")
    except urllib.error.HTTPError as e:
        check(e.code == 400 and json.loads(e.read()).get("error"), "repeats=abc 返回 JSON 400")
    layout_job = json.loads(http(web + "/api/benchmark", {
        "model_ids": [oa["id"]], "dims": ["layout"], "visual": False
    })[1])["job"]
    for _ in range(100):
        layout_result = json.loads(http(web + f"/api/jobs/{layout_job}")[1])
        if layout_result["status"] != "running":
            break
        time.sleep(0.1)
    layout_records = (layout_result.get("result") or {}).get("records", [])
    check(layout_result["status"] == "done" and layout_records
          and all(record["dimension"] == "layout" for record in layout_records),
          "网页接口 dims=[layout] 只运行排版题")
    models = json.loads(http(web + "/api/models")[1])
    check(all("api_key" not in m for m in models) and any(m["api_key_masked"] == "sk-…1234" for m in models),
          "模型列表接口只返回脱敏 Key")
    job = json.loads(http(web + "/api/deck", {"brief": "测试", "n_slides": 4, "model_ids": [oa["id"]]})[1])["job"]
    for _ in range(100):
        j = json.loads(http(web + f"/api/jobs/{job}")[1])
        if j["status"] != "running":
            break
        time.sleep(0.1)
    check(j["status"] == "done", f"网页接口制作 PPT：{j['status']} {j.get('error') or ''}")
    if j["status"] == "done":
        code, data = http(web + j["result"]["download"])
        check(code == 200 and data[:2] == b"PK", "可以下载 .pptx 文件")
    try:
        http(web + "/download/..%2F..%2Fmodels.json")
        check(False, "路径穿越被拦截")
    except urllib.error.HTTPError as e:
        check(e.code == 404, "路径穿越被拦截")

    print("\n全部通过" if not FAILED else "\n有失败项")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
