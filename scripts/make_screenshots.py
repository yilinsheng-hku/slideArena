"""Create README images from local benchmark and deck data.

Only ``~/.slidearena/benchmarks.json`` (the last record) and the newest PPTX in
``~/.slidearena/output`` are read. ``models.json`` is never opened. The PPT is rendered with
PowerPoint COM when available, then LibreOffice as a fallback; no fake image is created.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
USER_HOME = Path.home() / ".slidearena"
sys.path.insert(0, str(ROOT))


def _safe_copy(value):
    if isinstance(value, dict):
        return {k: _safe_copy(v) for k, v in value.items()
                if k.lower() not in {"api_key", "api_key_masked"} and k.lower() != "base_url"}
    if isinstance(value, list):
        return [_safe_copy(v) for v in value]
    return value


def _assert_public_json(value) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if "api_key" in key.lower():
                raise RuntimeError("benchmarks.json contains a credential field")
            _assert_public_json(child)
    elif isinstance(value, list):
        for child in value:
            _assert_public_json(child)


def _check_image(path: Path) -> None:
    raw = path.read_bytes()
    if any(token in raw for token in (b"C:\\Users\\", b"sk-", b"AIza", b"api_key", b"https://", b"http://")):
        path.unlink(missing_ok=True)
        raise RuntimeError(f"screenshot contains sensitive text: {path.name}")
    with Image.open(path) as image:
        if image.width < 10 or image.height < 10:
            raise RuntimeError(f"invalid screenshot: {path.name}")
        if all(low == high for low, high in image.convert("RGB").getextrema()):
            raise RuntimeError(f"blank screenshot: {path.name}")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _child_env(home: Path) -> dict[str, str]:
    """Start the temporary screenshot server without inheriting provider keys."""
    env = {
        name: os.environ[name]
        for name in ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE")
        if name in os.environ
    }
    env.update({"SLIDEARENA_HOME": str(home), "PYTHONUTF8": "1"})
    return env


def _start_server(home: Path):
    port = _free_port()
    env = _child_env(home)
    process = subprocess.Popen(
        [sys.executable, "-m", "slidearena", "serve", "--port", str(port), "--no-browser"],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return process, f"http://127.0.0.1:{port}/"


def _leaderboard(record: dict, profiles: dict) -> Path:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("未安装 Playwright，无法生成排行榜截图") from exc
    with tempfile.TemporaryDirectory(prefix="slidearena_screenshot_data_") as temp_name:
        temp = Path(temp_name)
        (temp / "benchmarks.json").write_text(json.dumps([_safe_copy(record)], ensure_ascii=False), encoding="utf-8")
        (temp / "profiles.json").write_text(json.dumps(_safe_copy(profiles), ensure_ascii=False), encoding="utf-8")
        process, url = _start_server(temp)
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                for attempt in range(60):
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=2_000)
                        break
                    except Exception:
                        if attempt == 59:
                            raise
                        time.sleep(0.2)
                page.locator('button[data-tab="bench"]').click()
                page.locator("#board table").nth(0).wait_for(timeout=30_000)
                DOCS.mkdir(exist_ok=True)
                output = DOCS / "screenshot-leaderboard.png"
                page.locator("#board").screenshot(path=str(output))
                browser.close()
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
    _check_image(output)
    return output


def _powershell_render(pptx: Path, output: Path) -> list[Path]:
    if os.name != "nt":
        return []
    script = r'''
param([string]$Pptx, [string]$OutDir)
$ErrorActionPreference = "Stop"
$app = $null
$pres = $null
try {
  $app = New-Object -ComObject PowerPoint.Application
  $pres = $app.Presentations.Open($Pptx, $true, $true, $false)
  $prefix = Join-Path $OutDir "slide"
  $pres.SaveAs($prefix, 18)
  $files = @(Get-ChildItem -LiteralPath $OutDir -Filter "slide*.png" -File)
  if ($files.Count -eq 0) { $pres.Export($OutDir, "PNG", 1280, 720) }
} finally {
  if ($pres) { $pres.Close() }
  if ($app) { $app.Quit() }
}
'''
    with tempfile.NamedTemporaryFile("w", suffix=".ps1", encoding="utf-8", delete=False) as handle:
        handle.write(script)
        script_path = Path(handle.name)
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script_path),
             "-Pptx", str(pptx), "-OutDir", str(output)],
            capture_output=True, text=True, timeout=180,
        )
        if result.returncode:
            return []
    except (OSError, subprocess.SubprocessError):
        return []
    finally:
        script_path.unlink(missing_ok=True)
    return sorted(output.rglob("*.png"))


def _libreoffice_render(pptx: Path, output: Path) -> list[Path]:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return []
    result = subprocess.run(
        [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(output), str(pptx)],
        capture_output=True, text=True, timeout=180,
    )
    pdf = output / (pptx.stem + ".pdf")
    if result.returncode or not pdf.is_file():
        return []
    try:
        import fitz
        document = fitz.open(pdf)
        images = []
        for index, page in enumerate(document, 1):
            pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
            image_path = output / f"slide{index}.png"
            pixmap.save(str(image_path))
            images.append(image_path)
        document.close()
        return images
    except ImportError:
        pdftoppm = shutil.which("pdftoppm")
        if not pdftoppm:
            return []
        subprocess.run([pdftoppm, "-png", "-r", "108", str(pdf), str(output / "slide")],
                       capture_output=True, timeout=180)
        return sorted(output.glob("slide-*.png"))


def _deck_wall(pptx: Path) -> Path:
    from slidearena import render

    with tempfile.TemporaryDirectory(prefix="slidearena_ppt_render_") as temp_name:
        temp = Path(temp_name)
        images = _powershell_render(pptx, temp)
        renderer = "PowerPoint COM"
        if not images:
            images = _libreoffice_render(pptx, temp)
            renderer = "LibreOffice"
        if not images:
            raise RuntimeError("没有找到 PowerPoint 或 LibreOffice，未伪造 PPT 截图")
        images = images[:6]
        if len(images) < 6:
            raise RuntimeError(f"PPT 只有 {len(images)} 页，无法组成 2×3 缩略图墙")
        label_font = render.chinese_font(18, required=True)
        thumbnails = []
        for image_path in images:
            with Image.open(image_path).convert("RGB") as image:
                image.thumbnail((600, 338))
                thumbnails.append(image.copy())
        canvas = Image.new("RGB", (1260, 1184), "#E5E7EB")
        draw = ImageDraw.Draw(canvas)
        for index, image in enumerate(thumbnails):
            x = 20 + (index % 2) * 620
            y = 20 + (index // 2) * 388
            canvas.paste(image, (x, y))
            draw.text((x, y + 342), f"第 {index + 1} 页", fill="#1F2937", font=label_font)
        output = DOCS / "screenshot-deck.png"
        canvas.save(output, "PNG")
    _check_image(output)
    print(f"PPT 缩略图使用 {renderer} 渲染")
    return output


def _visual_judge(record: dict) -> Path:
    from slidearena import cases, llm, render
    layout_records = [r for r in record["records"] if r.get("kind") == "layout" and r.get("answer")]
    by_task: dict[str, list[dict]] = {}
    for item in layout_records:
        by_task.setdefault(item["task"], []).append(item)
    task, records = next((item for item in by_task.items() if len(item[1]) >= 3), (None, []))
    if task is None:
        raise RuntimeError("最后一次 benchmark 没有同一道排版题的三个模型答案")
    case = next(case for case in cases.LAYOUT if case["id"] == task)
    names = {model["id"]: model.get("name", model["id"]) for model in record["models"]}
    scores = record["scores"]
    selected = sorted(records, key=lambda item: item.get("model_id", ""))[:3]
    cell_w, cell_h = 420, 236
    canvas = Image.new("RGB", (cell_w * 3, cell_h + 76), "#FFFFFF")
    draw = ImageDraw.Draw(canvas)
    font = render.chinese_font(18, required=True)
    for index, item in enumerate(selected):
        data = llm.extract_json(item["answer"])
        image = Image.open(io.BytesIO(render.render_layout(data, case, scale=0.44))).convert("RGB")
        canvas.paste(image.resize((cell_w, cell_h)), (index * cell_w, 0))
        image.close()
        score = scores.get(item["model_id"], {}).get("dims", {}).get("layout", {}).get("cases", {}).get(task)
        final_score = score if score is not None else item.get("score", 0)
        label = f"{names.get(item['model_id'], item['model_id'])} · 排版 {final_score:.1f} 分"
        draw.text((index * cell_w + 8, cell_h + 20), label, fill="#1F2937", font=font)
    output = DOCS / "visual-judge.png"
    canvas.save(output, "PNG")
    _check_image(output)
    return output


def main() -> int:
    benchmark_path = USER_HOME / "benchmarks.json"
    output_dir = USER_HOME / "output"
    if not benchmark_path.is_file():
        print(f"找不到 {benchmark_path}，无法生成真实结果截图。")
        return 1
    pptx_files = sorted(output_dir.glob("*.pptx"), key=lambda path: path.stat().st_mtime)
    history = json.loads(benchmark_path.read_text(encoding="utf-8"))
    if not isinstance(history, list) or not history:
        print("benchmarks.json 没有可用记录。")
        return 1
    record = history[-1]
    safe_record = _safe_copy(record)
    _assert_public_json(safe_record)
    profiles_path = USER_HOME / "profiles.json"
    profiles = json.loads(profiles_path.read_text(encoding="utf-8")) if profiles_path.is_file() else {}
    safe_profiles = _safe_copy(profiles)
    _assert_public_json(safe_profiles)
    DOCS.mkdir(exist_ok=True)
    _leaderboard(safe_record, safe_profiles)
    _visual_judge(safe_record)
    deck_image = DOCS / "screenshot-deck.png"
    if pptx_files and (not deck_image.exists() or pptx_files[-1].stat().st_mtime > deck_image.stat().st_mtime):
        _deck_wall(pptx_files[-1])
    elif deck_image.exists():
        print("没有比现有截图更新的 PPTX，保留 docs/screenshot-deck.png")
    else:
        print("没有 PPTX 或现有 PPT 截图，排行榜和视觉评审图已更新")
        return 1
    print("已更新排行榜和视觉评审截图；PPT 截图仅在有更新文件时生成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
