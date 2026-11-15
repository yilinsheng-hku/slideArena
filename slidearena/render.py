"""Render a layout answer (element boxes + font sizes) into a slide-like PNG, so a vision model can
judge how the page actually looks, not just whether coordinates pass the rules.

Text is drawn at the requested point size and wrapped to the box width; overflow is drawn past the
box (in red), exactly as it would spill on a real slide. Visual elements become a placeholder chart.
"""
from __future__ import annotations

import base64
import io
import os

from PIL import Image, ImageDraw, ImageFont

from .cases import SLIDE_H, SLIDE_W
from .scoring import (
    TEXT_INNER_PADDING_IN,
    TEXT_LINE_HEIGHT_EM,
    TEXT_PARAGRAPH_GAP_EM,
    text_fit_ratio,
)

DPI = 72                      # 1 pt = 1 px, 13.333 x 7.5 in -> 960 x 540
BG, INK, ACCENT, MUTED = "#FFFFFF", "#1F2937", "#2563EB", "#CBD5E1"
_WIN_FONTS = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
_FONTS = [
    os.path.join(_WIN_FONTS, "msyh.ttc"),
    os.path.join(_WIN_FONTS, "simhei.ttf"),
    os.path.join(_WIN_FONTS, "simsun.ttc"),
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/Hiragino Sans GB W3.otf",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/arphic/ukai.ttc",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
]
_font_cache: dict[int, ImageFont.ImageFont] = {}
_using_default_font = False
_warned_missing_font = False


def _find_font(px: int):
    px = max(6, int(px))
    for path in _FONTS:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, px)
            except OSError:
                continue
    return None


def chinese_font(px: int, required: bool = False):
    """Return a font from the shared Chinese font search path.

    ``required=True`` is for generated public screenshots: emitting a bitmap with
    missing glyph boxes is worse than stopping and asking for a font to be installed.
    The renderer itself keeps its historical Pillow fallback when ``required`` is false.
    """
    font = _find_font(px)
    if font is None and required:
        raise RuntimeError("未找到中文字体，无法生成不会乱码的截图")
    return font or _font(px)


def _font(px: int):
    global _using_default_font, _warned_missing_font
    px = max(6, int(px))
    if px not in _font_cache:
        f = _find_font(px)
        if f is None:
            _using_default_font = True
            if not _warned_missing_font:
                print("警告：未找到中文字体，将使用 Pillow 默认字体。")
                _warned_missing_font = True
            f = ImageFont.load_default()
        _font_cache[px] = f
    return _font_cache[px]


def _wrap(draw, text: str, font, width: float) -> list[str]:
    lines, cur = [], ""
    for ch in str(text):
        if draw.textlength(cur + ch, font=font) <= width or not cur:
            cur += ch
        else:
            lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines or [""]


def _placeholder_chart(draw, x0, y0, x1, y1):
    draw.rectangle([x0, y0, x1, y1], fill="#F1F5F9", outline=MUTED)
    w, h = x1 - x0, y1 - y0
    n = 5
    bw = w / (n * 1.8)
    for i, frac in enumerate((0.35, 0.5, 0.45, 0.7, 0.85)):
        bx = x0 + w * 0.08 + i * bw * 1.8
        draw.rectangle([bx, y1 - h * 0.08 - h * 0.8 * frac, bx + bw, y1 - h * 0.08], fill=ACCENT)


def render_layout(data, case, scale: float = 1.0) -> bytes:
    """data = a model's {"elements": [...]} answer; case = the layout case it answered."""
    W, H = int(SLIDE_W * DPI * scale), int(SLIDE_H * DPI * scale)
    im = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(im)
    px = DPI * scale
    spec = case["elements"]
    for e in (data or {}).get("elements") or []:
        try:
            role = str(e["role"])
            x, y, w, h = (float(e[k]) * px for k in ("x", "y", "w", "h"))
        except (KeyError, TypeError, ValueError):
            continue
        if w <= 0 or h <= 0:
            continue
        paras = spec.get(role)
        if paras is None and role in spec:
            _placeholder_chart(draw, x, y, x + w, y + h)
            continue
        if paras is None:                       # an element the case did not ask for
            draw.rectangle([x, y, x + w, y + h], outline="#F59E0B", width=2)
            continue
        try:
            size = float(e.get("font_size") or 18)
        except (TypeError, ValueError):
            size = 18
        is_title = role == "title"
        is_card = role.startswith(("card", "step"))
        if is_card:
            draw.rounded_rectangle([x, y, x + w, y + h], radius=8 * scale, fill="#EFF6FF", outline="#BFDBFE")
        font = _font(size * scale * (1.0 if is_title else 1.0))
        pad = TEXT_INNER_PADDING_IN * px
        cy = y + pad
        line_h = size * TEXT_LINE_HEIGHT_EM * scale
        ratio = text_fit_ratio(paras, w / px, size, h / px)
        severe_overflow = ratio >= 1.5
        for i, p in enumerate(paras):
            bullet = "" if is_title or is_card or len(paras) == 1 else "• "
            colour = ACCENT if (is_card and i == 0) else INK
            text = bullet + p
            if _using_default_font:
                text = "".join(ch if ord(ch) < 128 else "?" for ch in text)
            for line in _wrap(draw, text, font, w - 2 * pad):
                line_colour = "#FCA5A5" if cy + line_h > y + h else colour
                draw.text((x + pad, cy), line, font=font, fill=line_colour)
                cy += line_h
            cy += size * TEXT_PARAGRAPH_GAP_EM * scale
        if ratio > 1.0:
            dash_y = y + h - 2 * scale
            dash = max(3, int(8 * scale))
            gap = max(2, int(5 * scale))
            xx = x + pad
            while xx < x + w - pad:
                draw.line([xx, dash_y, min(xx + dash, x + w - pad), dash_y], fill="#DC2626", width=max(1, int(2 * scale)))
                xx += dash + gap
        if severe_overflow:
            draw.rectangle([x, y, x + w, y + h], outline="#DC2626", width=max(1, int(2 * scale)))
        if is_title:
            draw.line([x + pad, y + h - 2, x + pad + 60 * scale, y + h - 2], fill=ACCENT, width=int(3 * scale))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def data_url(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode()
