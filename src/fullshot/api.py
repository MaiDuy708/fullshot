"""High-level API shared by the CLI and the MCP server."""

from __future__ import annotations

import json
from datetime import timezone as _tz
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

from . import __version__
from .capture import CaptureOptions, CaptureResult, capture, default_basename, resolve_output_dir
from .export import PAPERS, SplitInfo, StampInfo, sha256, write_images, write_pdf
from .splitter import LayoutMasks
from .stamp import DATE_FORMATS, STYLES, format_time

FORMATS = ("png", "jpeg", "pdf")


@dataclass
class ExportOptions:
    formats: list[str] = field(default_factory=lambda: ["png"])
    output_dir: str | None = None
    basename: str | None = None
    # URL + date/time stamp
    stamp: str = "none"  # none | top | bottom | browser
    date_format: str = "datetime"  # date | datetime | iso | none | strftime pattern
    timezone: str = "local"  # local | utc
    # splitting
    smart_split: bool = True
    max_back: float = 0.25
    max_image_height: int = 30000  # image px; taller PNG/JPEG are split into parts
    # pdf
    paper: str = "letter"
    margin_pt: float = 28.0
    page_numbers: bool = True
    pdf_image_format: str = "png"  # png (lossless) | jpeg (smaller)
    jpeg_quality: int = 92
    write_metadata: bool = True  # sidecar <name>.json with hashes etc.

    def validate(self) -> None:
        bad = [f for f in self.formats if f not in FORMATS]
        if bad:
            raise ValueError(f"unknown format(s) {bad}; use {FORMATS}")
        if self.stamp not in STYLES:
            raise ValueError(f"stamp must be one of {STYLES}")
        if self.date_format not in DATE_FORMATS and "%" not in self.date_format:
            raise ValueError(f"date_format must be one of {DATE_FORMATS} or a strftime pattern")
        if self.paper not in PAPERS:
            raise ValueError(f"paper must be one of {PAPERS}")
        if not 0.05 <= self.max_back <= 0.6:
            raise ValueError("max_back must be between 0.05 and 0.6")
        if self.max_image_height < 1000:
            raise ValueError("max_image_height must be >= 1000")


def export(result: CaptureResult, ex: ExportOptions) -> dict[str, Any]:
    ex.validate()
    out_dir = resolve_output_dir(ex.output_dir)
    when = result.captured_at if ex.timezone == "local" else result.captured_at.astimezone(_tz.utc)
    base = out_dir / (ex.basename or default_basename(result.final_url or result.url, when))
    stamp_url = result.final_url or result.url
    stamp = StampInfo(stamp_url, format_time(when, ex.date_format), ex.stamp)
    split = SplitInfo(result.masks, ex.smart_split, ex.max_back)
    meta = {
        "URL": stamp_url,
        "Title": result.title,
        "CaptureTime": when.isoformat(timespec="seconds"),
        "Software": f"fullshot {__version__}",
    }

    files: list[dict[str, Any]] = []
    for fmt in ex.formats:
        if fmt in ("png", "jpeg"):
            paths = write_images(
                result.image, base, fmt, result.scale, stamp, split, ex.max_image_height, ex.jpeg_quality, meta
            )
            for p in paths:
                with Image.open(p) as im:
                    size = im.size
                files.append({"path": str(p), "format": fmt, "width": size[0], "height": size[1]})
        elif fmt == "pdf":
            path, pages, _ = write_pdf(
                result.image,
                base.with_suffix(".pdf"),
                result.scale,
                stamp,
                split,
                paper=ex.paper,
                margin_pt=ex.margin_pt,
                title=result.title,
                page_numbers=ex.page_numbers,
                image_format=ex.pdf_image_format,
                quality=ex.jpeg_quality,
            )
            files.append({"path": str(path), "format": "pdf", "pages": pages, "paper": ex.paper})

    for f in files:
        f["sha256"] = sha256(Path(f["path"]))
        f["bytes"] = Path(f["path"]).stat().st_size

    summary: dict[str, Any] = {
        "url": result.url,
        "final_url": result.final_url,
        "title": result.title,
        "captured_at": when.isoformat(timespec="seconds"),
        "page_css_size": [result.css_width, result.css_height],
        "device_scale": result.scale,
        "image_size": list(result.image.size),
        "truncated": result.truncated,
        "files": files,
        "notes": result.notes,
        "options": {k: v for k, v in asdict(ex).items() if k not in ("output_dir", "basename")},
        "software": f"fullshot {__version__}",
    }
    if ex.write_metadata:
        meta_path = base.with_suffix(".json")
        meta_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        summary["metadata_file"] = str(meta_path)
    return summary


async def capture_and_export(cap: CaptureOptions, ex: ExportOptions) -> tuple[dict[str, Any], CaptureResult]:
    ex.validate()  # fail fast, before opening a browser
    result = await capture(cap)
    return export(result, ex), result


def image_to_pdf(image_path: str, ex: ExportOptions, url: str = "", scale: float = 1.0) -> dict[str, Any]:
    """Paginate an existing (tall) image into a PDF with pixel-based smart splitting."""
    from datetime import datetime

    img = Image.open(image_path).convert("RGB")
    ex.formats = ["pdf"]
    result = CaptureResult(
        image=img,
        masks=LayoutMasks.empty(img.height),  # no DOM: pixels only
        url=url or Path(image_path).name,
        final_url=url or Path(image_path).name,
        title=Path(image_path).stem,
        captured_at=datetime.now().astimezone(),
        css_width=int(img.width / scale),
        css_height=int(img.height / scale),
        scale=scale,
        truncated=False,
        notes=["pixel-only smart split (no DOM layout available)"],
    )
    if not ex.basename:
        ex.basename = Path(image_path).stem
    if not ex.output_dir:
        ex.output_dir = str(Path(image_path).resolve().parent)
    return export(result, ex)
