"""Write captures to PNG / JPEG / PDF, with smart splitting and stamps."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, PngImagePlugin
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as pdf_canvas

from . import stamp as stamp_mod
from .splitter import LayoutMasks, PixelRows, choose_breaks, slices

# Page sizes in PDF points (1/72 in), portrait.
PAPER_SIZES: dict[str, tuple[float, float]] = {
    "letter": (612.0, 792.0),
    "legal": (612.0, 1008.0),
    "tabloid": (792.0, 1224.0),
    "a3": (841.89, 1190.55),
    "a4": (595.28, 841.89),
    "a5": (419.53, 595.28),
}
PAPERS = tuple(PAPER_SIZES) + tuple(f"{p}-landscape" for p in PAPER_SIZES) + ("full",)

# Acrobat refuses pages larger than 200 in (14400 pt) on a side.
MAX_PDF_SIDE_PT = 14400.0
CSS_PX_TO_PT = 0.75  # 96 CSS px per inch


@dataclass
class StampInfo:
    url: str
    time_text: str
    style: str = "none"  # none | top | bottom | browser


@dataclass
class SplitInfo:
    masks: LayoutMasks | None
    smart: bool = True
    max_back: float = 0.25


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _part_path(base: Path, index: int, total: int, ext: str) -> Path:
    if total <= 1:
        return base.with_suffix(ext)
    return base.with_name(f"{base.name}-part{index}").with_suffix(ext)


def _png_info(meta: dict[str, str]) -> PngImagePlugin.PngInfo:
    info = PngImagePlugin.PngInfo()
    for k, v in meta.items():
        if v:
            info.add_itxt(k, str(v))
    return info


def write_images(
    img: Image.Image,
    base: Path,
    fmt: str,
    scale: float,
    stamp: StampInfo,
    split: SplitInfo,
    max_height: int,
    quality: int = 92,
    meta: dict[str, str] | None = None,
) -> list[Path]:
    """Save ``img`` as one or more PNG/JPEG files.

    Images taller than ``max_height`` (image px) are cut into parts at smart
    break lines. The stamp bar is added to every part.
    """
    meta = meta or {}
    bar_h = stamp_mod.bar_height(stamp.style, scale)
    page_h = max(256, max_height - bar_h)
    pixels = PixelRows(img) if split.smart else None
    breaks = choose_breaks(img.height, page_h, split.masks, pixels, split.max_back, split.smart)
    parts = slices(img.height, breaks)
    ext = ".png" if fmt == "png" else ".jpg"
    paths: list[Path] = []
    for i, (top, bottom) in enumerate(parts, start=1):
        piece = img.crop((0, top, img.width, bottom))
        piece = stamp_mod.apply_stamp(piece, stamp.url, stamp.time_text, stamp.style, scale)
        path = _part_path(base, i, len(parts), ext)
        part_meta = dict(meta, Part=f"{i}/{len(parts)}") if len(parts) > 1 else meta
        if fmt == "png":
            piece.save(path, "PNG", pnginfo=_png_info(part_meta), optimize=False)
        else:
            exif = Image.Exif()
            exif[0x010E] = meta.get("URL", "")  # ImageDescription
            exif[0x0131] = "fullshot"  # Software
            if meta.get("CaptureTime"):
                exif[0x0132] = meta["CaptureTime"]
            piece.convert("RGB").save(path, "JPEG", quality=quality, optimize=True, exif=exif)
        paths.append(path)
    return paths


def paper_size(paper: str) -> tuple[float, float]:
    landscape = paper.endswith("-landscape")
    key = paper.removesuffix("-landscape")
    if key not in PAPER_SIZES:
        raise ValueError(f"unknown paper {paper!r}; use one of {PAPERS}")
    w, h = PAPER_SIZES[key]
    return (h, w) if landscape else (w, h)


def write_pdf(
    img: Image.Image,
    path: Path,
    scale: float,
    stamp: StampInfo,
    split: SplitInfo,
    paper: str = "letter",
    margin_pt: float = 28.0,
    title: str = "",
    page_numbers: bool = True,
    image_format: str = "png",
    quality: int = 92,
) -> tuple[Path, int, list[int]]:
    """Write a paginated PDF. Returns (path, page_count, break_lines)."""
    show_stamp = stamp.style != "none"
    stamp_on_bottom = stamp.style == "bottom"
    header_h = 20.0 if show_stamp and not stamp_on_bottom else 0.0
    footer_h = 0.0
    if page_numbers:
        footer_h += 18.0
    if show_stamp and stamp_on_bottom:
        footer_h += 16.0

    if paper == "full":
        # Page width follows the screenshot at 96 dpi; height grows with each
        # slice, capped by the PDF page-size limit (taller pages are split).
        content_w = img.width / scale * CSS_PX_TO_PT
        page_w = content_w + 2 * margin_pt
        max_content_h = MAX_PDF_SIDE_PT - 2 * margin_pt - header_h - footer_h
        slice_px = int(max_content_h / content_w * img.width)
    else:
        page_w, page_h = paper_size(paper)
        content_w = page_w - 2 * margin_pt
        content_h = page_h - 2 * margin_pt - header_h - footer_h
        slice_px = int(content_h / content_w * img.width)

    pixels = PixelRows(img) if split.smart else None
    breaks = choose_breaks(img.height, slice_px, split.masks, pixels, split.max_back, split.smart)
    parts = slices(img.height, breaks)

    pt_per_px = content_w / img.width
    c = pdf_canvas.Canvas(str(path), pageCompression=1)
    c.setTitle(title or stamp.url)
    c.setSubject(stamp.url)
    c.setCreator("fullshot")
    c.setKeywords(f"captured {stamp.time_text}" if stamp.time_text else "")
    total = len(parts)
    for i, (top, bottom) in enumerate(parts, start=1):
        slice_h_pt = (bottom - top) * pt_per_px
        if paper == "full":
            page_h = slice_h_pt + 2 * margin_pt + header_h + footer_h
        c.setPageSize((page_w, page_h))

        piece = img.crop((0, top, img.width, bottom)).convert("RGB")
        if image_format == "jpeg":
            from io import BytesIO

            buf = BytesIO()
            piece.save(buf, "JPEG", quality=quality)
            buf.seek(0)
            reader = ImageReader(buf)
        else:
            reader = ImageReader(piece)
        img_top = page_h - margin_pt - header_h
        c.drawImage(reader, margin_pt, img_top - slice_h_pt, width=content_w, height=slice_h_pt)

        c.setFont("Helvetica", 8.5)
        if show_stamp:
            if not stamp_on_bottom:
                y = page_h - margin_pt - 12
            else:
                y = margin_pt + 4 + (16 if page_numbers and total > 1 else 0)
            url_text = stamp.url
            max_url_w = content_w - (c.stringWidth(stamp.time_text, "Helvetica", 8.5) + 16)
            while url_text and c.stringWidth(url_text, "Helvetica", 8.5) > max_url_w:
                url_text = url_text[:-2]
            if url_text != stamp.url:
                url_text = url_text[:-1] + "..."
            c.setFillColorRGB(0.10, 0.35, 0.80)
            c.drawString(margin_pt, y, url_text)
            w = c.stringWidth(url_text, "Helvetica", 8.5)
            c.linkURL(stamp.url, (margin_pt, y - 2, margin_pt + w, y + 9), relative=0, thickness=0)
            c.setFillColorRGB(0.35, 0.37, 0.40)
            if stamp.time_text:
                c.drawRightString(page_w - margin_pt, y, stamp.time_text)
        if page_numbers and total > 1:
            c.setFillColorRGB(0.45, 0.45, 0.45)
            c.drawCentredString(page_w / 2, margin_pt + 4, f"{i} / {total}")
        c.showPage()
    c.save()
    return path, total, breaks
