"""Model adapters. Pure standard library (urllib), so installation stays light.

Supported protocols:
  openai     - any OpenAI-compatible /chat/completions endpoint (OpenAI, DeepSeek, Kimi, Qwen,
               Doubao, GLM, SiliconFlow, OpenRouter, Gemini's OpenAI endpoint, Ollama, LM Studio ...)
  anthropic  - Anthropic Messages API
  mock       - offline fake model for demos and tests (no network)
Image generation uses the OpenAI-compatible /images/generations endpoint.
"""
from __future__ import annotations

import base64
import hashlib
import json
import random
import re
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass, field

from . import config

# Presets shown in the UI. Users can still type any base_url.
PRESETS = [
    {"key": "openai", "label": "OpenAI", "protocol": "openai", "base_url": "https://api.openai.com/v1", "model": "gpt-5-mini"},
    {"key": "anthropic", "label": "Anthropic Claude", "protocol": "anthropic", "base_url": "https://api.anthropic.com", "model": "claude-sonnet-5-5"},
    {"key": "gemini", "label": "Google Gemini (OpenAI 兼容)", "protocol": "openai", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "model": "gemini-2.5-flash"},
    {"key": "deepseek", "label": "DeepSeek", "protocol": "openai", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
    {"key": "moonshot", "label": "Kimi / Moonshot", "protocol": "openai", "base_url": "https://api.moonshot.cn/v1", "model": "kimi-k2-turbo-preview"},
    {"key": "dashscope", "label": "通义千问 DashScope", "protocol": "openai", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus"},
    {"key": "ark", "label": "豆包 火山方舟", "protocol": "openai", "base_url": "https://ark.cn-beijing.volces.com/api/v3", "model": ""},
    {"key": "zhipu", "label": "智谱 GLM", "protocol": "openai", "base_url": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-4.6"},
    {"key": "siliconflow", "label": "SiliconFlow 硅基流动", "protocol": "openai", "base_url": "https://api.siliconflow.cn/v1", "model": ""},
    {"key": "openrouter", "label": "OpenRouter", "protocol": "openai", "base_url": "https://openrouter.ai/api/v1", "model": ""},
    {"key": "ollama", "label": "Ollama（本地）", "protocol": "openai", "base_url": "http://127.0.0.1:11434/v1", "model": "qwen3:14b"},
    {"key": "custom", "label": "自定义 OpenAI 兼容接口", "protocol": "openai", "base_url": "", "model": ""},
    {"key": "mock", "label": "演示模型（离线，不花钱）", "protocol": "mock", "base_url": "", "model": "mock"},
]


class ModelError(Exception):
    """The call did not produce a usable answer."""


class ServiceError(ModelError):
    """The provider or the network failed (timeout, dropped connection, HTTP error, malformed
    envelope), after retries. This says nothing about the model's ability, so the benchmark
    leaves such calls out of the score and reports them, instead of counting 0."""


@dataclass
class Reply:
    text: str
    latency: float
    input_tokens: int = 0
    output_tokens: int = 0
    raw: dict = field(default_factory=dict)


RETRY_HTTP = {408, 409, 425, 429, 500, 502, 503, 504, 520, 522, 524}


class RateLimited(ServiceError):
    """The provider kept refusing because of the account's rate limit. This says nothing about the
    model's ability, so the benchmark leaves such calls out of the score instead of counting 0."""


class _Gate:
    """Per-endpoint throttle shared by all threads: a concurrency cap, a requests-per-minute cap and
    a cool-down. Limits start from the model config ("max_concurrency", "rpm") and tighten
    automatically when a 429 message reveals the account's real limit."""

    def __init__(self):
        self.cv = threading.Condition()
        self.active = 0
        self.conc: int | None = None
        self.rpm: int | None = None
        self.sent: deque[float] = deque()
        self.until = 0.0

    def acquire(self):
        with self.cv:
            while True:
                now = time.time()
                while self.sent and now - self.sent[0] > 60:
                    self.sent.popleft()
                wait = self.until - now
                if self.rpm and len(self.sent) >= self.rpm:
                    wait = max(wait, 60 - (now - self.sent[0]) + 0.2)
                if self.conc and self.active >= self.conc:
                    wait = max(wait, 1.0)
                if wait <= 0:
                    self.active += 1
                    self.sent.append(now)
                    return
                self.cv.wait(timeout=min(wait, 5))

    def release(self):
        with self.cv:
            self.active -= 1
            self.cv.notify_all()

    def learn(self, msg: str):
        """Read the provider's 429 text: "max RPM: 3", "max organization concurrency", "after 1 seconds"."""
        with self.cv:
            m = re.search(r"RPM[:：]?\s*(\d+)", msg, re.I)
            if m:
                self.rpm = max(1, int(m.group(1)))
            if re.search(r"concurren", msg, re.I):
                self.conc = max(1, (self.conc or max(1, self.active)) - 1)
            m = re.search(r"after\s+(\d+(?:\.\d+)?)\s*s", msg, re.I)
            self.until = max(self.until, time.time() + (float(m.group(1)) if m else 2.0))
            self.cv.notify_all()


_GATES: dict[str, _Gate] = {}
_GATES_LOCK = threading.Lock()
_TL = threading.local()       # duration of the last successful request in this thread (excludes waiting)


def gate_for(model: dict) -> _Gate:
    key = (model.get("base_url") or "").rstrip("/") + "|" + str(model.get("api_key", ""))
    with _GATES_LOCK:
        g = _GATES.setdefault(key, _Gate())
    for field_, attr in (("max_concurrency", "conc"), ("rpm", "rpm")):
        v = model.get(field_)
        if v and getattr(g, attr) is None:
            setattr(g, attr, int(v))
    return g


# (base_url, model) -> the only temperature the provider accepts (None = do not send one)
_FIXED_TEMP: dict[tuple[str, str], float | None] = {}


def _post(url: str, headers: dict, body: dict, timeout: float, retries: int = 3,
          gate: _Gate | None = None, rate_retries: int = 10) -> dict:
    """POST JSON. Transient failures (network blips, 5xx) are retried with backoff, so one flaky
    request does not count as the model failing a benchmark task. Rate-limit refusals (429) get
    their own, larger retry budget and tighten the endpoint's gate."""
    data = json.dumps(body).encode("utf-8")
    gate = gate or _Gate()
    last = None
    attempt = limited = 0
    while attempt < retries and limited <= rate_retries:
        req = urllib.request.Request(url, data=data, method="POST",
                                     headers={"Content-Type": "application/json", **headers})
        gate.acquire()
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                out = json.loads(r.read().decode("utf-8"))
            _TL.elapsed = time.time() - t0
            return out
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:500]
            if e.code == 429:
                gate.learn(detail)
                limited += 1
                last = RateLimited(f"HTTP 429（账号限流，已重试 {limited} 次）: {detail}")
                continue
            last = ServiceError(f"HTTP {e.code}: {detail}")
            if e.code not in RETRY_HTTP:
                raise last from None
        except urllib.error.URLError as e:
            last = ServiceError(f"连接失败: {e.reason}")
        except (TimeoutError, ConnectionError, OSError) as e:
            last = ServiceError(f"请求超时或连接中断: {e}")
        except json.JSONDecodeError:
            raise ServiceError("返回内容不是 JSON") from None
        finally:
            gate.release()
        attempt += 1
        if attempt < retries:
            time.sleep(1.5 * 2 ** (attempt - 1))
    raise last


def _content_parts(text: str, images: list[str] | None, protocol: str):
    """images: list of data URLs (data:image/png;base64,...)."""
    if not images:
        return text
    if protocol == "anthropic":
        parts = []
        for url in images:
            media, b64 = url[5:].split(";base64,", 1)
            parts.append({"type": "image", "source": {"type": "base64", "media_type": media, "data": b64}})
        parts.append({"type": "text", "text": text})
        return parts
    return [{"type": "text", "text": text}] + [{"type": "image_url", "image_url": {"url": u}} for u in images]


def chat(model: dict, prompt: str, system: str = "", images: list[str] | None = None,
         max_tokens: int = 2000, temperature: float = 0.4, timeout: float = 120) -> Reply:
    protocol = model.get("protocol", "openai")
    t0 = time.time()
    if protocol == "mock":
        return _mock_chat(model, prompt, system, t0, images)

    key = config.resolve_key(model.get("api_key"))
    base = (model.get("base_url") or "").rstrip("/")
    if not base:
        raise ServiceError("没有填写 base_url")

    if protocol == "anthropic":
        body = {"model": model["model"], "max_tokens": max_tokens, "temperature": temperature,
                "messages": [{"role": "user", "content": _content_parts(prompt, images, protocol)}]}
        if system:
            body["system"] = system
        url = base + ("/messages" if base.endswith("/v1") else "/v1/messages")
        data = _post(url, {"x-api-key": key, "anthropic-version": "2023-06-01"}, body, timeout,
                     gate=gate_for(model))
        text = "".join(p.get("text", "") for p in data.get("content", []) if p.get("type") == "text")
        usage = data.get("usage", {})
        return Reply(text, getattr(_TL, "elapsed", time.time() - t0), usage.get("input_tokens", 0),
                     usage.get("output_tokens", 0), data)

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": _content_parts(prompt, images, protocol)})
    ckey = (base, model["model"])
    temp = model.get("temperature", _FIXED_TEMP.get(ckey, temperature))
    body = {"model": model["model"], "messages": messages, "max_tokens": max_tokens}
    if temp is not None:
        body["temperature"] = temp
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    gate = gate_for(model)
    try:
        data = _post(base + "/chat/completions", headers, body, timeout, gate=gate)
    except ModelError as e:
        # some reasoning models accept only one temperature ("only 1 is allowed"); retry with what the
        # provider allows, or without the field, and remember it for later calls
        msg = str(e)
        if not (msg.startswith("HTTP 400") and "temperature" in msg.lower()):
            raise
        m = re.search(r"only\s+(\d+(?:\.\d+)?)\s+is allowed", msg)
        _FIXED_TEMP[ckey] = float(m.group(1)) if m else None
        body.pop("temperature", None)
        if _FIXED_TEMP[ckey] is not None:
            body["temperature"] = _FIXED_TEMP[ckey]
        data = _post(base + "/chat/completions", headers, body, timeout, gate=gate)
    try:
        text = data["choices"][0]["message"].get("content") or ""
    except (KeyError, IndexError):
        raise ServiceError(f"返回格式异常: {json.dumps(data, ensure_ascii=False)[:300]}") from None
    if isinstance(text, list):  # some providers return content parts
        text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
    usage = data.get("usage") or {}
    return Reply(text, getattr(_TL, "elapsed", time.time() - t0), usage.get("prompt_tokens", 0),
                 usage.get("completion_tokens", 0), data)


def generate_image(model: dict, prompt: str, size: str = "1536x1024", timeout: float = 180) -> tuple[bytes, float]:
    t0 = time.time()
    if model.get("protocol") == "mock":
        return _mock_image(prompt), time.time() - t0
    key = config.resolve_key(model.get("api_key"))
    base = (model.get("base_url") or "").rstrip("/")
    body = {"model": model.get("image_model") or model["model"], "prompt": prompt, "size": size, "n": 1}
    data = _post(base + "/images/generations", {"Authorization": f"Bearer {key}"}, body, timeout)
    try:
        item = data["data"][0]
    except (KeyError, IndexError):
        raise ModelError(f"图片接口返回异常: {json.dumps(data, ensure_ascii=False)[:300]}") from None
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"]), time.time() - t0
    if item.get("url"):
        try:
            with urllib.request.urlopen(item["url"], timeout=timeout) as r:
                return r.read(), time.time() - t0
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            raise ServiceError(f"下载生成的图片失败: {e}") from None
    raise ModelError("图片接口没有返回图片")


def extract_json(text: str):
    """Pull the first JSON object/array out of a model reply (handles ```json fences and chatter)."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for open_c, close_c in (("{", "}"), ("[", "]")):
        start = text.find(open_c)
        end = text.rfind(close_c)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
    raise ModelError("回复里找不到合法 JSON")


# ---------------------------------------------------------------- mock model
# Deterministic fake answers whose quality depends on the model's "skill" settings,
# so the whole pipeline (benchmark -> ranking -> routing) can be demoed offline.

def _rng(model: dict, prompt: str) -> random.Random:
    seed = hashlib.md5((model.get("id", "") + model.get("name", "") + prompt).encode()).hexdigest()
    return random.Random(int(seed[:8], 16))


def _mock_case(prompt: str):
    """Find which benchmark case a prompt belongs to (demo models answer from the reference)."""
    from . import cases as C
    from .generate import REGISTRY
    for bank in (C.REVISE, C.OUTLINE, C.CONDENSE, C.CHART, C.LAYOUT, list(REGISTRY.values())):
        for c in bank:
            if C.matches_prompt(c, prompt):
                return c
    return None


def _red_pixels(data_url: str) -> int:
    """Overflowing text is drawn in red by render.py; count it."""
    import io

    from PIL import Image
    img = Image.open(io.BytesIO(base64.b64decode(data_url.split(",", 1)[1]))).convert("RGB")
    pixels = img.get_flattened_data() if hasattr(img, "get_flattened_data") else img.getdata()
    return sum(1 for r, g, b in pixels if r > 180 and r - g > 60 and r - b > 60)


def _mock_verdict(task: str, prompt: str, images, rng: random.Random, accuracy: float) -> str:
    """A demo judge with real (if simple) judgement: fewer invented numbers wins for outlines,
    less overflowing text wins for layouts. With probability 1 - accuracy it guesses."""
    if rng.random() > accuracy:
        return rng.choice(["A", "B", "tie"])
    if task == "visual_pairwise" and images and len(images) == 2:
        bad = [_red_pixels(u) for u in images]
    else:
        from . import facts
        m = re.search(r"需求与资料：\s*(.*?)【大纲 A】(.*?)【大纲 B】(.*?)只输出", prompt, re.S)
        if not m:
            return "tie"
        src = facts.Source(m.group(1))
        bad = [len(src.unsupported(m.group(2))), len(src.unsupported(m.group(3)))]
    if abs(bad[0] - bad[1]) <= (20 if task == "visual_pairwise" else 0):
        return "tie"
    return "A" if bad[0] < bad[1] else "B"


def _mock_chat(model: dict, prompt: str, system: str, t0: float, images=None) -> Reply:
    """A fake model that starts from the reference answer and makes realistic mistakes.
    mock_skill[task] (0-1) is the chance of getting each part right."""
    import copy
    skill = model.get("mock_skill") or {}
    rng = _rng(model, prompt)
    task = re.search(r"\[task:(\w+)\]", system + prompt)
    task = task.group(1) if task else "chat"
    s = float(skill.get(task, skill.get("default", 0.7)))
    good = lambda: rng.random() < s  # noqa: E731
    case = _mock_case(prompt)

    if task == "ping":
        out = "pong"
    elif task == "revise" and case:
        out = json.dumps(copy.deepcopy(case["reference"]), ensure_ascii=False)
    elif task in ("outline", "condense") and case:
        ans = copy.deepcopy(case["reference"])
        slides = ans["slides"] if task == "outline" else [ans]
        for sl in slides[1:] if task == "outline" else slides:
            bl = sl.get("bullets") or []
            if bl and not good():
                bl[rng.randrange(len(bl))] = "资料显示该项指标同比大幅增长 23.7%，并带动整体表现持续改善"  # invented + too long
            if bl and not good():
                bl.pop(rng.randrange(len(bl)))                                                      # drops key info
        if task == "outline" and not good():
            slides.append({"title": "附录：补充说明与常见问题解答", "bullets": ["谢谢"], "kind": "bullets"})
        out = json.dumps(ans, ensure_ascii=False)
    elif task == "chart" and case:
        ans = copy.deepcopy(case["reference"])
        if case.get("skip"):
            if not good():
                ans = {"chart_type": "column", "title": "团队业绩", "categories": ["上半年", "下半年"],
                       "series": [{"name": "业绩", "values": [80, 95]}]}
        else:
            vals = ans["series"][0]["values"]
            if not good():                                   # unit not converted / miscalculated
                i = rng.randrange(len(vals))
                vals[i] = round(vals[i] * rng.choice([10000, 1.1, 0.9]), 2)
            if not good():                                   # distractor mixed in
                ans["categories"].append("其他")
                vals.append(48.3)
            if not good():
                ans["chart_type"] = "doughnut" if ans["chart_type"] != "doughnut" else "line"
        out = json.dumps(ans, ensure_ascii=False)
    elif task == "layout" and case:
        ans = copy.deepcopy(case["reference"])
        for e in ans["elements"]:
            if not good():
                e["h"] = round(e["h"] * 0.6, 2)              # text will not fit
            if not good():
                e["x"] = round(e["x"] + rng.uniform(1, 3), 2)  # overlaps / runs off the page
            if not good() and "font_size" in e:
                e["font_size"] = rng.choice([10, 48])
        out = json.dumps(ans, ensure_ascii=False)
    elif task in ("pairwise", "visual_pairwise"):
        out = json.dumps({"winner": _mock_verdict(task, prompt, images, rng, float(skill.get("judge", 0.9))),
                          "reason": "演示评审"})
    elif task == "fix":
        out = json.dumps({"bullets": ["详见资料"]}, ensure_ascii=False)
    elif task == "chart":                                    # deck building: use numbers in the brief
        nums = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*亿", prompt)][:4]
        labels = re.findall(r"(Q\d)", prompt)[:len(nums)]
        out = json.dumps({"chart_type": "column", "title": "营收", "unit": "亿元",
                          "categories": labels or [f"项{i + 1}" for i in range(len(nums))],
                          "series": [{"name": "营收", "values": nums}], "takeaway": "持续增长"}
                         if nums and len(labels) == len(nums) else {"skip": True}, ensure_ascii=False)
    elif task == "outline":                                  # deck building from a free brief
        n = int(re.search(r"N=(\d+)", prompt).group(1)) if re.search(r"N=(\d+)", prompt) else 6
        slides = [{"title": "演示文稿", "bullets": ["演示模型生成"], "kind": "cover"}]
        slides += [{"title": f"第{i}部分", "bullets": ["要点一", "要点二", "要点三"],
                    "kind": "chart" if i == 1 else "bullets"} for i in range(1, n)]
        out = json.dumps({"slides": slides}, ensure_ascii=False)
    else:
        out = "（演示模型的回答）"
    time.sleep(0.05 + rng.random() * 0.15 * float(skill.get("slowness", 1)))
    return Reply(out, time.time() - t0, len(prompt) // 2, len(out) // 2)


def _mock_image(prompt: str) -> bytes:
    from PIL import Image, ImageDraw
    h = hashlib.md5(prompt.encode()).digest()
    img = Image.new("RGB", (768, 512), (h[0], h[1], h[2]))
    d = ImageDraw.Draw(img)
    for i in range(6):
        c = (h[3 + i] , h[9 + i], 200)
        d.ellipse([60 + i * 100, 120 + (h[i] % 120), 220 + i * 100, 280 + (h[i] % 120)], fill=c)
    import io
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()
