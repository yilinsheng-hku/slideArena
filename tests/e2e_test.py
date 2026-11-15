"""Browser end-to-end test for the offline demo workflow.

Run locally after installing the development extra and Chromium:
    python -m pip install -e ".[dev]"
    python -m playwright install chromium
    python tests/e2e_test.py

The test intentionally uses only the three built-in mock models. If Playwright is not installed,
it prints a skip message and exits successfully so the core test suite remains usable.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("跳过浏览器端到端测试：未安装 Playwright。请运行 pip install -e \".[dev]\"。")
    raise SystemExit(0)


ROOT = Path(__file__).resolve().parents[1]


def child_env(home: Path) -> dict[str, str]:
    """Pass only process settings needed by the local test server.

    In particular, do not inherit the caller's provider credentials.
    """
    env = {
        name: os.environ[name]
        for name in ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE")
        if name in os.environ
    }
    env.update({"SLIDEARENA_HOME": str(home), "PYTHONUTF8": "1"})
    return env


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main() -> int:
    home = Path(tempfile.mkdtemp(prefix="slidearena_e2e_"))
    port = free_port()
    env = child_env(home)
    server = subprocess.Popen(
        [sys.executable, "-m", "slidearena", "serve", "--port", str(port), "--no-browser"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    browser_errors: list[str] = []
    downloaded: Path | None = None
    collecting_errors = False
    expecting_download = False
    try:
        url = f"http://127.0.0.1:{port}/"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            def record(message: str) -> None:
                if collecting_errors:
                    browser_errors.append(message)

            def on_request_failed(request) -> None:
                if expecting_download and "/download/" in request.url and request.failure == "net::ERR_ABORTED":
                    return
                record(f"requestfailed {request.method} {request.url}: {request.failure}")

            page.on("console", lambda msg: record(f"console {msg.type}: {msg.text}") if msg.type == "error" else None)
            page.on("pageerror", lambda exc: record(f"pageerror: {exc}"))
            page.on("requestfailed", on_request_failed)

            for attempt in range(60):
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=2_000)
                    break
                except Exception:
                    if attempt == 59:
                        raise
                    time.sleep(0.2)
            collecting_errors = True
            page.locator("#demo").click()
            page.locator("#model-list tr").nth(2).wait_for(timeout=30_000)
            assert page.locator("#model-list tr").count() == 3, "演示模型列表不是 3 个"

            page.locator('button[data-tab="bench"]').click()
            for checkbox in page.locator(".dim-pick").all():
                if not checkbox.is_checked():
                    checkbox.check()
            page.locator("#run-bench").click()
            leaderboard_rows = page.locator("#board table").nth(0).locator("tbody tr")
            leaderboard_rows.nth(2).wait_for(timeout=120_000)
            assert leaderboard_rows.count() == 3, "排行榜不是 3 行"
            board = page.locator("#board").inner_text()
            assert "区间" in board, "排行榜缺少置信区间"
            assert "大纲两两评审" in board, "排行榜缺少大纲评审记录"
            assert "排版视觉评审" in board, "排行榜缺少排版视觉评审记录"

            page.locator('button[data-tab="deck"]').click()
            page.locator("#brief").fill("给管理层做一份离线演示季度复盘，说明营收趋势、问题和下一步计划")
            page.locator("#n").fill("4")
            page.locator("#make").click()
            page.locator("#deck-result a[href^='/download/']").wait_for(timeout=60_000)
            expecting_download = True
            with page.expect_download(timeout=30_000) as download_info:
                page.locator("#deck-result a[href^='/download/']").click()
            expecting_download = False
            download = download_info.value
            downloaded = home / "downloaded.pptx"
            download.save_as(downloaded)
            from pptx import Presentation

            assert len(Presentation(downloaded).slides) == 4, "下载的 PPT 页数不是 4"
            browser.close()
        if browser_errors:
            raise AssertionError("浏览器报告错误：" + "；".join(browser_errors))
        print("浏览器端到端测试通过：演示模型、能力测试、排行榜、PPT 下载均正常。")
        return 0
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=10)
        if downloaded and downloaded.exists():
            downloaded.unlink()
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
