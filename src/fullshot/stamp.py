"""URL + date/time stamping for image exports.

Styles:
  none    - no stamp
  top     - thin info bar above the screenshot (URL left, time right)
  bottom  - same bar below the screenshot
  browser - a neutral browser-window frame (dots + address field) above the
            screenshot, with the time on the right
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

STYLES = ("none", "top", "bottom", "browser")
DATE_FORMATS = ("date", "datetime", "iso", "none")

_FONT_CANDIDATES = {
    "win32": ["segoeui.ttf", "arial.ttf", "tahoma.ttf"],
    "darwin": [
        "/System/Library/Fonts/SFNS.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
    ],
    "linux": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/noto/NotoSans-Regular.ttf",
    ],
}


@lru_cache(maxsize=16)
def load_font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    custom = os.environ.get("FULLSHOT_FONT")
    candidates = ([custom] if custom else []) + _FONT_CANDIDATES.get(
        "linux" if sys.platform.startswith("linux") else sys.platform, []
    )
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def format_time(moment: datetime, fmt: str) -> str:
    """Format the capture time. ``fmt`` is a preset name or a strftime string."""
    if fmt == "none":
        return ""
    if fmt == "date":
        return moment.strftime("%Y-%m-%d")
    if fmt == "datetime":
        # Windows %Z gives long names ("SE Asia Standard Time"); an offset is
        # shorter and unambiguous everywhere.
        off = moment.strftime("%z")  # +0700
        tz = "UTC" if off in ("+0000", "") else f"UTC{off[:3]}:{off[3:]}"
        return moment.strftime("%Y-%m-%d %H:%M:%S ") + tz
    if fmt == "iso":
        return moment.isoformat(timespec="seconds")
    if "%" in fmt:
        return moment.strftime(fmt)
    raise ValueError(f"unknown date format {fmt!r}; use one of {DATE_FORMATS} or a strftime pattern")


def now(tz: str = "local") -> datetime:
    if tz == "utc":
        return datetime.now(timezone.utc)
    return datetime.now().astimezone()


def _ellipsize(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    ell = "…"
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if draw.textlength(text[:mid] + ell, font=font) <= max_width:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + ell


def bar_height(style: str, scale: float) -> int:
    if style == "none":
        return 0
    return int(round((44 if style == "browser" else 32) * scale))


def render_bar(width: int, url: str, time_text: str, style: str, scale: float = 1.0) -> Image.Image:
    """Render the stamp bar as its own RGB image (``width`` x ``bar_height``)."""
    h = bar_height(style, scale)
    bar = Image.new("RGB", (width, h), (241, 243, 244) if style == "browser" else (248, 249, 250))
    d = ImageDraw.Draw(bar)
    font = load_font(max(8, int(13 * scale)))
    pad = int(12 * scale)
    text_color = (60, 64, 67)

    time_w = int(d.textlength(time_text, font=font)) if time_text else 0
    right_edge = width - pad - (time_w + pad if time_text else 0)

    if style == "browser":
        # Window dots
        r = int(6 * scale)
        cy = h // 2
        x = pad
        for color in ((237, 106, 94), (245, 191, 79), (98, 197, 84)):
            d.ellipse((x, cy - r, x + 2 * r, cy + r), fill=color)
            x += 2 * r + int(8 * scale)
        # Address field
        fx0 = x + pad
        fy0 = int(8 * scale)
        fx1 = max(fx0 + int(40 * scale), right_edge)
        fy1 = h - int(8 * scale)
        d.rounded_rectangle((fx0, fy0, fx1, fy1), radius=(fy1 - fy0) // 2, fill=(255, 255, 255), outline=(218, 220, 224))
        tx = fx0 + int(14 * scale)
        url_text = _ellipsize(d, url, font, fx1 - tx - int(10 * scale))
        d.text((tx, cy), url_text, font=font, fill=text_color, anchor="lm")
    else:
        url_text = _ellipsize(d, url, font, right_edge - pad)
        d.text((pad, h // 2), url_text, font=font, fill=text_color, anchor="lm")
        line_y = h - 1 if style == "top" else 0
        d.line((0, line_y, width, line_y), fill=(218, 220, 224), width=max(1, int(scale)))

    if time_text:
        d.text((width - pad, h // 2), time_text, font=font, fill=(95, 99, 104), anchor="rm")
    return bar


def apply_stamp(img: Image.Image, url: str, time_text: str, style: str, scale: float = 1.0) -> Image.Image:
    if style == "none":
        return img
    if style not in STYLES:
        raise ValueError(f"unknown stamp style {style!r}; use one of {STYLES}")
    bar = render_bar(img.width, url, time_text, style, scale)
    out = Image.new("RGB", (img.width, img.height + bar.height), (255, 255, 255))
    if style == "bottom":
        out.paste(img.convert("RGB"), (0, 0))
        out.paste(bar, (0, img.height))
    else:
        out.paste(bar, (0, 0))
        out.paste(img.convert("RGB"), (0, bar.height))
    return out
