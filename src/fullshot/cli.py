"""Command line interface: ``fullshot <url> [options]``."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from . import __version__
from .api import FORMATS, ExportOptions, capture_and_export, image_to_pdf
from .capture import CaptureError, CaptureOptions
from .export import PAPERS
from .stamp import STYLES


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fullshot",
        description="Full-page screenshots with smart page splitting and URL/date stamps.",
    )
    p.add_argument("url", nargs="?", help="page to capture (https:// is added if missing)")
    p.add_argument("--version", action="version", version=f"fullshot {__version__}")
    p.add_argument("-f", "--format", action="append", choices=FORMATS, help="output format (repeatable; default png)")
    p.add_argument("-o", "--output-dir", help="output folder (default $FULLSHOT_OUTPUT_DIR or ~/fullshot-captures)")
    p.add_argument("-n", "--name", help="base file name without extension")

    g = p.add_argument_group("page")
    g.add_argument("--width", type=int, default=1280, help="viewport width in CSS px (default 1280)")
    g.add_argument("--height", type=int, default=800, help="viewport height in CSS px (default 800)")
    g.add_argument("--scale", type=float, default=1.0, help="device pixel ratio, e.g. 2 for retina (default 1)")
    g.add_argument("--wait-until", default="load", choices=["load", "domcontentloaded", "networkidle", "commit"])
    g.add_argument("--delay", type=int, default=800, help="extra wait in ms before capture (default 800)")
    g.add_argument("--wait-for", help="CSS selector to wait for before capture")
    g.add_argument("--selector", help="capture only this element")
    g.add_argument("--hide", action="append", default=[], help="CSS selector to hide (repeatable), e.g. cookie banners")
    g.add_argument("--freeze-fixed", action="store_true", help="make fixed/sticky headers scroll with the page")
    g.add_argument("--no-lazy-scroll", action="store_true", help="don't pre-scroll to load lazy content")
    g.add_argument("--no-expand", action="store_true", help="don't expand inner scroll containers / iframes")
    g.add_argument("--dark", action="store_true", help="emulate prefers-color-scheme: dark")
    g.add_argument("--user-agent")
    g.add_argument("--cdp", metavar="URL", help="use your running Chrome, e.g. http://127.0.0.1:9222")
    g.add_argument("--timeout", type=int, default=45000, help="navigation timeout in ms")
    g.add_argument("--max-height", type=int, default=60000, help="cap page height in CSS px (default 60000)")
    g.add_argument("--allow-file", action="store_true", help="allow file:// URLs")
    g.add_argument("--block-private", action="store_true", help="refuse loopback/private/link-local hosts (SSRF guard)")

    s = p.add_argument_group("URL and date/time stamp")
    s.add_argument("--stamp", choices=STYLES, default="none", help="add URL + capture time (default none)")
    s.add_argument("--date-format", default="datetime", help="date | datetime | iso | none | strftime pattern")
    s.add_argument("--utc", action="store_true", help="stamp time in UTC instead of local time")

    sp = p.add_argument_group("splitting / PDF")
    sp.add_argument("--no-smart-split", action="store_true", help="cut at fixed heights (may slice text)")
    sp.add_argument("--max-back", type=float, default=0.25, help="how far up (fraction of a page) to look for a clean cut")
    sp.add_argument("--max-image-height", type=int, default=30000, help="split PNG/JPEG taller than this (image px)")
    sp.add_argument("--paper", choices=PAPERS, default="letter", help="PDF paper size (default letter)")
    sp.add_argument("--margin", type=float, default=28.0, help="PDF margin in points (default 28 = ~1cm)")
    sp.add_argument("--no-page-numbers", action="store_true")
    sp.add_argument("--pdf-jpeg", action="store_true", help="embed JPEG in PDF (smaller, lossy)")
    sp.add_argument("--quality", type=int, default=92, help="JPEG quality (default 92)")
    sp.add_argument("--no-metadata", action="store_true", help="don't write the .json sidecar")
    sp.add_argument("--from-image", metavar="PATH", help="paginate an existing image into a PDF instead of capturing")
    p.add_argument("--json", action="store_true", help="print the full result as JSON")
    return p


def export_options(a: argparse.Namespace) -> ExportOptions:
    return ExportOptions(
        formats=a.format or ["png"],
        output_dir=a.output_dir,
        basename=a.name,
        stamp=a.stamp,
        date_format=a.date_format,
        timezone="utc" if a.utc else "local",
        smart_split=not a.no_smart_split,
        max_back=a.max_back,
        max_image_height=a.max_image_height,
        paper=a.paper,
        margin_pt=a.margin,
        page_numbers=not a.no_page_numbers,
        pdf_image_format="jpeg" if a.pdf_jpeg else "png",
        jpeg_quality=a.quality,
        write_metadata=not a.no_metadata,
    )


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    ex = export_options(a)
    try:
        if a.from_image:
            summary = image_to_pdf(a.from_image, ex, url=a.url or "", scale=a.scale)
        else:
            if not a.url:
                print("fullshot: a URL is required (or --from-image)", file=sys.stderr)
                return 2
            cap = CaptureOptions(
                url=a.url,
                width=a.width,
                height=a.height,
                scale=a.scale,
                wait_until=a.wait_until,
                delay_ms=a.delay,
                wait_for_selector=a.wait_for,
                selector=a.selector,
                hide_selectors=a.hide,
                scroll_lazy=not a.no_lazy_scroll,
                expand_scrollers=not a.no_expand,
                expand_iframes=not a.no_expand,
                freeze_fixed=a.freeze_fixed,
                color_scheme="dark" if a.dark else None,
                user_agent=a.user_agent,
                cdp_url=a.cdp,
                timeout_ms=a.timeout,
                max_height_css=a.max_height,
                allow_file=a.allow_file,
                block_private=a.block_private,
            )
            summary, _ = asyncio.run(capture_and_export(cap, ex))
    except (CaptureError, ValueError) as exc:
        print(f"fullshot: {exc}", file=sys.stderr)
        return 1

    if a.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        for f in summary["files"]:
            extra = f"{f['pages']} page(s)" if f["format"] == "pdf" else f"{f['width']}x{f['height']}"
            print(f"{f['path']}  ({extra})")
        for note in summary["notes"]:
            print(f"note: {note}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
