"""Local web app (standard library only). Binds to 127.0.0.1 so keys never leave the machine."""
from __future__ import annotations

import json
import re
import threading
import time
import traceback
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import benchmark, config, deck, llm

STATIC = Path(__file__).parent / "static"
JOBS: dict[str, dict] = {}
MAX_BODY_BYTES = 1024 * 1024


class PayloadTooLargeError(ValueError):
    """Raised before reading a request body larger than the server limit."""


def _start_job(kind: str, fn) -> str:
    jid = uuid.uuid4().hex[:10]
    job = {"id": jid, "kind": kind, "status": "running", "log": [], "result": None, "error": None,
           "started": time.time()}
    JOBS[jid] = job

    def progress(msg):
        job["log"].append(f"[{time.strftime('%H:%M:%S')}] {msg}")

    def target():
        try:
            job["result"] = fn(progress)
            job["status"] = "done"
        except Exception as e:
            job["error"] = str(e)
            job["status"] = "error"
            progress("出错：" + str(e))
            traceback.print_exc()

    threading.Thread(target=target, daemon=True).start()
    return jid


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # keep the console quiet
        pass

    def _json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        raw_length = self.headers.get("Content-Length")
        try:
            n = int(raw_length or 0)
        except (TypeError, ValueError):
            raise ValueError("invalid Content-Length") from None
        if n < 0:
            raise ValueError("invalid Content-Length")
        if n > MAX_BODY_BYTES:
            raise PayloadTooLargeError
        if not n:
            return {}
        return json.loads(self.rfile.read(n).decode("utf-8"))

    def _valid_host(self) -> bool:
        host = self.headers.get("Host", "")
        port = self.server.server_port
        return bool(re.fullmatch(rf"(?:127\.0\.0\.1|localhost):{port}", host, re.IGNORECASE))

    def _valid_origin(self, origin: str) -> bool:
        port = self.server.server_port
        return bool(re.fullmatch(rf"http://(?:127\.0\.0\.1|localhost):{port}", origin, re.IGNORECASE))

    def _reject_untrusted(self) -> bool:
        if not self._valid_host():
            self._json({"error": "invalid Host header"}, 403)
            return True
        origin = self.headers.get("Origin")
        if origin is not None and not self._valid_origin(origin):
            self._json({"error": "invalid Origin header"}, 403)
            return True
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if self.command == "POST" and content_type != "application/json":
            self._json({"error": "Content-Type must be application/json"}, 403)
            return True
        return False

    def _file(self, path: Path, ctype: str, download_name: str | None = None):
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if download_name:
            from urllib.parse import quote
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(download_name)}")
        self.end_headers()
        self.wfile.write(data)

    # ---------------- GET
    def _do_GET(self):
        if self._reject_untrusted():
            return
        p = urlparse(self.path).path
        if p in ("/", "/index.html"):
            return self._file(STATIC / "index.html", "text/html; charset=utf-8")
        if p == "/api/presets":
            return self._json(llm.PRESETS)
        if p == "/api/models":
            return self._json([config.public_model(m) for m in config.list_models()])
        if p == "/api/profiles":
            return self._json({"profiles": config.load("profiles.json", {}), "dimensions": benchmark.DIMENSIONS})
        if p == "/api/route":
            return self._json({d: benchmark.explain_route(d) if benchmark.route(d) else "（无可用模型）"
                               for d in ("text", "chart", "layout", "image")})
        if p == "/api/benchmarks/latest":
            h = config.load("benchmarks.json", [])
            return self._json(h[-1] if h else None)
        if p.startswith("/api/jobs/"):
            job = JOBS.get(p.rsplit("/", 1)[-1])
            return self._json(job or {"error": "not found"}, 200 if job else 404)
        if p.startswith("/download/"):
            name = Path(unquote(p[len("/download/"):])).name
            f = config.home() / "output" / name
            if f.is_file():
                return self._file(f, "application/vnd.openxmlformats-officedocument.presentationml.presentation", name)
        self._json({"error": "not found"}, 404)

    def do_GET(self):
        try:
            self._do_GET()
        except Exception:
            traceback.print_exc()
            try:
                self._json({"error": "internal server error"}, 500)
            except Exception:
                pass

    # ---------------- POST
    def _do_POST(self):
        if self._reject_untrusted():
            return
        p = urlparse(self.path).path
        try:
            body = self._body()
        except PayloadTooLargeError:
            return self._json({"error": "request body too large"}, 413)
        except ValueError as exc:
            return self._json({"error": str(exc)}, 400)
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)

        if p == "/api/models":
            if not body.get("name") or not body.get("protocol"):
                return self._json({"error": "需要 name 和 protocol"}, 400)
            if body["protocol"] != "mock" and not body.get("model"):
                return self._json({"error": "需要填写模型名称（model）"}, 400)
            allowed = {"id", "name", "protocol", "base_url", "model", "api_key", "can_image", "image_model", "mock_skill"}
            entry = config.upsert_model({k: v for k, v in body.items() if k in allowed})
            return self._json(config.public_model(entry))
        if p == "/api/models/delete":
            return self._json({"ok": config.delete_model(body.get("id", ""))})
        if p == "/api/models/test":
            m = config.get_model(body.get("id", ""))
            return self._json(benchmark.ping(m) if m else {"ok": False, "error": "模型不存在"})
        if p in ("/api/benchmark", "/api/benchmark/plan"):
            ids = body.get("model_ids") or [m["id"] for m in config.list_models()]
            try:
                reps = self._number(body, "repeats", 1, 1, 5)
            except ValueError as exc:
                return self._json({"error": str(exc)}, 400)
            dims = body.get("dims")
            if dims is not None and (not isinstance(dims, list)
                                     or any(d not in ("text", "layout", "chart", "image") for d in dims)):
                return self._json({"error": "dims must contain text, layout, chart, or image"}, 400)
            visual = body.get("visual", True)
            if not isinstance(visual, bool):
                return self._json({"error": "visual must be a boolean"}, 400)
            seed = body.get("seed", "auto")
            if seed is not None and (not isinstance(seed, str) or not re.fullmatch(r"[\w.-]{1,40}", seed)):
                return self._json({"error": "seed must be a short string, or null for the hand-checked bank only"}, 400)
            if p == "/api/benchmark/plan":
                return self._json(benchmark.plan(ids, repeats=reps, dims=dims, visual=visual, seed=seed))
            return self._json({"job": _start_job(
                "benchmark", lambda pr: benchmark.run(ids, progress=pr, repeats=reps, dims=dims, visual=visual,
                                                      seed=seed))})
        if p == "/api/deck":
            brief = (body.get("brief") or "").strip()
            if not brief:
                return self._json({"error": "请填写需求"}, 400)
            try:
                n = self._number(body, "n_slides", 6, 3, 20)
            except ValueError as exc:
                return self._json({"error": str(exc)}, 400)

            def make(pr):
                r = deck.build(brief, n, body.get("model_ids"), pr)
                from urllib.parse import quote
                r["download"] = "/download/" + quote(Path(r["path"]).name)
                return r
            if p == "/api/benchmark/plan":
                return self._json(benchmark.plan(ids, repeats=reps, dims=dims, visual=visual))
            return self._json({"job": _start_job("deck", make)})
        if p == "/api/demo":
            return self._json({"added": add_demo_models()})
        self._json({"error": "not found"}, 404)

    @staticmethod
    def _number(body: dict, name: str, default: int, low: int, high: int) -> int:
        raw = body.get(name)
        if raw is None or raw == "":
            return default
        try:
            value = int(raw)
        except (TypeError, ValueError):
            raise ValueError(f"{name} must be an integer") from None
        return max(low, min(high, value))

    def do_POST(self):
        try:
            self._do_POST()
        except Exception:
            traceback.print_exc()
            try:
                self._json({"error": "internal server error"}, 500)
            except Exception:
                pass


def add_demo_models() -> int:
    """Three offline fake models with different strengths, so new users can see the full flow."""
    demos = [
        {"id": "demo-writer", "name": "演示·文案强", "protocol": "mock", "model": "mock",
         "mock_skill": {"outline": 0.95, "condense": 0.95, "layout": 0.45, "chart": 0.6, "default": 0.7, "slowness": 2}},
        {"id": "demo-designer", "name": "演示·排版强", "protocol": "mock", "model": "mock", "can_image": True,
         "mock_skill": {"outline": 0.6, "condense": 0.6, "layout": 0.97, "chart": 0.7, "default": 0.7, "slowness": 1}},
        {"id": "demo-analyst", "name": "演示·数据强", "protocol": "mock", "model": "mock",
         "mock_skill": {"outline": 0.65, "condense": 0.7, "layout": 0.6, "chart": 0.98, "default": 0.7, "slowness": 0.5}},
    ]
    existing = {m["id"] for m in config.list_models()}
    n = 0
    for d in demos:
        if d["id"] not in existing:
            config.upsert_model(d)
            n += 1
    return n


def _open_browser(url: str) -> None:
    try:
        if not webbrowser.open(url):
            print(f"无法自动打开浏览器，请手动访问：{url}")
    except Exception as exc:
        print(f"无法自动打开浏览器（{exc}），请手动访问：{url}")


def serve(port: int = 8765, open_browser: bool = True) -> None:
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}"
    print(f"SlideArena 已启动：{url}  （数据目录：{config.home()}）  按 Ctrl+C 退出")
    if open_browser:
        threading.Timer(0.6, _open_browser, args=(url,)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")
