"""MCP stdio server exposing fullshot to any MCP-capable agent.

Run: ``fullshot-mcp`` (or ``uv run --directory <plugin root> fullshot-mcp``).
Nothing but MCP protocol messages may be written to stdout.
"""

from __future__ import annotations

import io
import json
import logging
import sys
from typing import Annotated, Literal

from pydantic import Field

try:  # mcp >= 2: FastMCP was renamed to MCPServer
    from mcp.server.mcpserver import Image as MCPImage
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP  # type: ignore[no-redef]
    from mcp.server.fastmcp import Image as MCPImage  # type: ignore[no-redef]

from .api import ExportOptions, capture_and_export
from .api import image_to_pdf as _image_to_pdf
from .capture import CaptureOptions

logging.basicConfig(stream=sys.stderr, level=logging.WARNING)

mcp = FastMCP(
    "fullshot",
    instructions=(
        "Full-page web screenshots. Use capture_page to save a whole web page (not just the visible "
        "viewport) as PNG/JPEG/PDF, optionally stamped with its URL and capture time and split into "
        "printable pages without cutting text lines. Files are written to disk; the result lists their "
        "paths, sizes and SHA-256 hashes, plus a small preview image of the top of the page."
    ),
)

Paper = Literal[
    "letter", "legal", "tabloid", "a3", "a4", "a5",
    "letter-landscape", "legal-landscape", "tabloid-landscape",
    "a3-landscape", "a4-landscape", "a5-landscape", "full",
]


def _preview(img, max_w: int = 900, max_h: int = 1400) -> MCPImage:
    top = img.crop((0, 0, img.width, min(img.height, int(max_h * img.width / max_w))))
    top.thumbnail((max_w, max_h))
    buf = io.BytesIO()
    top.convert("RGB").save(buf, "JPEG", quality=70)
    return MCPImage(data=buf.getvalue(), format="jpeg")


@mcp.tool()
async def capture_page(
    url: Annotated[str, Field(description="Page to capture. http(s) only unless FULLSHOT_ALLOW_FILE=1.")],
    formats: Annotated[list[Literal["png", "jpeg", "pdf"]], Field(description="One or more output formats.")] = ["png"],  # noqa: B006
    stamp: Annotated[
        Literal["none", "top", "bottom", "browser"],
        Field(description="Add the URL and capture date/time: bar on top, bar on bottom, or a browser-window frame."),
    ] = "none",
    date_format: Annotated[
        str, Field(description="date | datetime | iso | none, or a strftime pattern like '%d/%m/%Y %H:%M'.")
    ] = "datetime",
    utc: Annotated[bool, Field(description="Stamp the time in UTC instead of local time.")] = False,
    paper: Annotated[Paper, Field(description="PDF paper size; 'full' = one long page per 200 in.")] = "letter",
    smart_split: Annotated[
        bool, Field(description="Cut PDF pages / oversized images only between text lines and images.")
    ] = True,
    width: Annotated[int, Field(ge=320, le=3840, description="Viewport width in CSS px.")] = 1280,
    scale: Annotated[float, Field(ge=0.5, le=3, description="Device pixel ratio (2 = retina).")] = 1.0,
    selector: Annotated[str | None, Field(description="Capture only the element matching this CSS selector.")] = None,
    hide_selectors: Annotated[
        list[str], Field(description="CSS selectors to hide, e.g. cookie banners or chat widgets.")
    ] = [],  # noqa: B006
    wait_for_selector: Annotated[str | None, Field(description="Wait for this selector before capturing.")] = None,
    delay_ms: Annotated[int, Field(ge=0, le=30000, description="Extra wait before capture.")] = 800,
    freeze_fixed: Annotated[bool, Field(description="Make fixed/sticky headers scroll with the page.")] = False,
    dark_mode: Annotated[bool, Field(description="Emulate prefers-color-scheme: dark.")] = False,
    output_dir: Annotated[
        str | None, Field(description="Folder for the files (default $FULLSHOT_OUTPUT_DIR or ~/fullshot-captures).")
    ] = None,
    name: Annotated[str | None, Field(description="Base file name without extension.")] = None,
    cdp_url: Annotated[
        str | None,
        Field(description="Use an already running Chrome (with the user's logins), e.g. http://127.0.0.1:9222."),
    ] = None,
    preview: Annotated[bool, Field(description="Return a small JPEG preview of the top of the page.")] = True,
):
    """Capture a full web page (entire scroll height) to PNG, JPEG and/or PDF."""
    cap = CaptureOptions(
        url=url,
        width=width,
        scale=scale,
        selector=selector,
        hide_selectors=list(hide_selectors),
        wait_for_selector=wait_for_selector,
        delay_ms=delay_ms,
        freeze_fixed=freeze_fixed,
        color_scheme="dark" if dark_mode else None,
        cdp_url=cdp_url,
    )
    ex = ExportOptions(
        formats=list(dict.fromkeys(formats)) or ["png"],
        output_dir=output_dir,
        basename=name,
        stamp=stamp,
        date_format=date_format,
        timezone="utc" if utc else "local",
        smart_split=smart_split,
        paper=paper,
    )
    summary, result = await capture_and_export(cap, ex)
    out: list = [json.dumps(summary, indent=2, ensure_ascii=False)]
    if preview:
        out.append(_preview(result.image))
    return out


@mcp.tool()
def image_to_pdf(
    image_path: Annotated[str, Field(description="Path of an existing tall image (PNG/JPEG).")],
    paper: Annotated[Paper, Field(description="PDF paper size.")] = "letter",
    url: Annotated[str, Field(description="Optional source URL to stamp on each page.")] = "",
    stamp: Annotated[Literal["none", "top", "bottom", "browser"], Field(description="Stamp style.")] = "none",
    date_format: Annotated[str, Field(description="date | datetime | iso | none | strftime pattern")] = "datetime",
    smart_split: Annotated[bool, Field(description="Avoid cutting through content (pixel-based).")] = True,
) -> str:
    """Paginate an existing long screenshot into a PDF, cutting at clean rows."""
    ex = ExportOptions(stamp=stamp if url else "none", date_format=date_format, paper=paper, smart_split=smart_split)
    return json.dumps(_image_to_pdf(image_path, ex, url=url), indent=2, ensure_ascii=False)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
