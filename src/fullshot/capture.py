"""Full-page capture engine (Playwright / Chromium).

Pipeline
  1. open the page (own headless Chromium, or the user's Chrome over CDP)
  2. hide/freeze things that break stitched shots (scrollbars, animations,
     user-supplied selectors, optionally fixed/sticky elements)
  3. scroll through the page to trigger lazy-loaded content
  4. expand the main inner scroll container (SPA layouts) and iframes so the
     whole content is part of the document height
  5. measure, collect text-line / object boxes for smart splitting
  6. capture in tiles with ``captureBeyondViewport`` and stitch with Pillow
     (avoids Chromium's ~16k px single-capture limit)
"""

from __future__ import annotations

import asyncio
import io
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
import ipaddress
import socket
from urllib.parse import urlparse

from PIL import Image

from .splitter import LayoutMasks

Image.MAX_IMAGE_PIXELS = None  # we create the big images ourselves

TILE_CSS_PX = 4000  # height of one capture tile in CSS px


@dataclass
class CaptureOptions:
    url: str
    width: int = 1280
    height: int = 800
    scale: float = 1.0
    wait_until: str = "load"  # load | domcontentloaded | networkidle | commit
    delay_ms: int = 800
    wait_for_selector: str | None = None
    selector: str | None = None  # capture only this element
    hide_selectors: list[str] = field(default_factory=list)
    scroll_lazy: bool = True
    expand_scrollers: bool = True
    expand_iframes: bool = True
    freeze_fixed: bool = False  # make fixed/sticky elements static
    color_scheme: str | None = None  # light | dark
    user_agent: str | None = None
    cdp_url: str | None = None  # e.g. http://127.0.0.1:9222 (user's Chrome)
    timeout_ms: int = 45000
    max_height_css: int = 60000  # guard against infinite scroll
    allow_file: bool = False
    collect_layout: bool = True
    block_private: bool = False  # refuse loopback/private/link-local hosts (SSRF guard)


@dataclass
class CaptureResult:
    image: Image.Image
    masks: LayoutMasks
    url: str
    final_url: str
    title: str
    captured_at: datetime
    css_width: int
    css_height: int
    scale: float
    truncated: bool
    notes: list[str]


class CaptureError(RuntimeError):
    pass


def validate_url(url: str, allow_file: bool) -> str:
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", url):
        url = "https://" + url
    scheme = urlparse(url).scheme.lower()
    if scheme in ("http", "https"):
        return url
    if scheme == "file":
        if allow_file or os.environ.get("FULLSHOT_ALLOW_FILE") == "1":
            return url
        raise CaptureError("file:// URLs are disabled (set FULLSHOT_ALLOW_FILE=1 or pass allow_file).")
    raise CaptureError(f"unsupported URL scheme {scheme!r}: only http, https (and opt-in file) are allowed")


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").lower() in ("1", "true", "yes")


_HOST_CACHE: dict[str, bool] = {}


def is_private_host(host: str) -> bool:
    """True if ``host`` is, or resolves to, a loopback/private/link-local/reserved address."""
    host = (host or "").strip("[]").lower()
    if not host:
        return True
    if host in _HOST_CACHE:
        return _HOST_CACHE[host]
    try:
        infos = socket.getaddrinfo(host, None)
        addrs = {ipaddress.ip_address(i[4][0].split("%")[0]) for i in infos}
    except (OSError, ValueError):
        addrs = set()
    private = (not addrs) or any(
        a.is_private or a.is_loopback or a.is_link_local or a.is_reserved or a.is_multicast or a.is_unspecified
        for a in addrs
    )
    _HOST_CACHE[host] = private
    return private


def check_cdp_url(cdp_url: str) -> None:
    host = urlparse(cdp_url).hostname or ""
    if host in ("127.0.0.1", "localhost", "::1") or _env_flag("FULLSHOT_ALLOW_REMOTE_CDP"):
        return
    raise CaptureError("cdp_url must point at this machine (127.0.0.1/localhost); set FULLSHOT_ALLOW_REMOTE_CDP=1 to override")


# --------------------------------------------------------------------------
# In-page scripts
# --------------------------------------------------------------------------

PREP_CSS = """
html::-webkit-scrollbar, body::-webkit-scrollbar { display: none !important; }
html { scrollbar-width: none !important; scroll-behavior: auto !important; }
*, *::before, *::after { caret-color: transparent !important; }
"""

FREEZE_FIXED_JS = """
() => {
  let n = 0;
  for (const el of document.querySelectorAll('body *')) {
    const p = getComputedStyle(el).position;
    if (p === 'fixed' || p === 'sticky') {
      el.style.setProperty('position', p === 'fixed' ? 'absolute' : 'relative', 'important');
      n++;
    }
  }
  return n;
}
"""

LAZY_SCROLL_JS = """
async ({maxHeight}) => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const step = Math.max(200, Math.floor(innerHeight * 0.85));
  let y = 0, lastH = 0, stable = 0;
  const t0 = Date.now();
  while (Date.now() - t0 < 20000) {
    const h = Math.min(document.documentElement.scrollHeight, maxHeight);
    if (y >= h - innerHeight) {
      if (h === lastH && ++stable >= 2) break;
      lastH = h;
      await sleep(250);
      continue;
    }
    y += step;
    window.scrollTo(0, y);
    await sleep(120);
  }
  // force lazy images to load even if their observer missed them
  for (const img of document.querySelectorAll('img[loading="lazy"]')) img.loading = 'eager';
  window.scrollTo(0, 0);
  await sleep(150);
  return document.documentElement.scrollHeight;
}
"""

# Find big inner scroll containers (typical of SPA / dashboard layouts where
# <body> itself never scrolls) and let them grow to their full content.
EXPAND_SCROLLERS_JS = """
() => {
  const vw = innerWidth, vh = innerHeight;
  const se = document.scrollingElement || document.documentElement;
  const docScrolls = se.scrollHeight > vh + 4;
  const found = [];
  for (const el of document.querySelectorAll('body *')) {
    if (el.scrollHeight <= el.clientHeight + 4) continue;
    const cs = getComputedStyle(el);
    if (!/(auto|scroll|overlay)/.test(cs.overflowY)) continue;
    const r = el.getBoundingClientRect();
    if (r.width < vw * 0.5 || r.height < vh * 0.35) continue;
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    found.push(el);
  }
  // skip containers nested in another found container: the outer one wins
  const roots = found.filter(el => !found.some(o => o !== el && o.contains(el)));
  if (!roots.length) return 0;
  const force = (el, prop, val) => el.style.setProperty(prop, val, 'important');
  for (const el of roots) {
    force(el, 'overflow', 'visible');
    force(el, 'height', 'auto');
    force(el, 'max-height', 'none');
    let p = el.parentElement;
    while (p) {
      const cs = getComputedStyle(p);
      if (cs.overflowY !== 'visible' || cs.overflow !== 'visible') force(p, 'overflow', 'visible');
      if (p.clientHeight <= vh + 2 || cs.maxHeight !== 'none') {
        force(p, 'height', 'auto');
        force(p, 'max-height', 'none');
      }
      if (cs.position === 'fixed') force(p, 'position', 'absolute');
      p = p.parentElement;
    }
  }
  force(document.documentElement, 'height', 'auto');
  force(document.body, 'height', 'auto');
  return roots.length;
}
"""

MEASURE_JS = """
() => {
  const d = document.documentElement, b = document.body || d;
  return {
    width: Math.max(d.clientWidth, d.scrollWidth, b.scrollWidth, d.offsetWidth, b.offsetWidth),
    height: Math.max(d.clientHeight, d.scrollHeight, b.scrollHeight, d.offsetHeight, b.offsetHeight),
    viewportWidth: d.clientWidth || innerWidth,
    title: document.title || '',
  };
}
"""

# Boxes of rendered text lines and atomic elements, in document CSS px.
LAYOUT_JS = """
({limit}) => {
  const out = [];
  const sy = window.scrollY;
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
    acceptNode: n => n.nodeValue.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT,
  });
  const range = document.createRange();
  let n;
  while ((n = walker.nextNode()) && out.length < limit) {
    range.selectNodeContents(n);
    for (const r of range.getClientRects()) {
      if (r.width > 0 && r.height > 0 && r.height < 400) out.push([r.top + sy, r.bottom + sy, 2]);
    }
  }
  const atomic = 'img,svg,video,canvas,picture,iframe,embed,object,pre,tr,button,input,textarea,select,' +
                 'figure,blockquote,code,math,[role=img]';
  for (const el of document.querySelectorAll(atomic)) {
    if (out.length >= limit * 1.2) break;
    const r = el.getBoundingClientRect();
    if (r.width > 4 && r.height > 0) out.push([r.top + sy, r.bottom + sy, 1]);
  }
  return out;
}
"""


# --------------------------------------------------------------------------
# Browser handling
# --------------------------------------------------------------------------


def _install_chromium() -> None:
    subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        check=True,
        stdout=sys.stderr,  # never pollute an MCP stdio channel
        stderr=sys.stderr,
    )


async def _launch(pw) -> Any:
    """Launch Chromium: bundled build, then installed Chrome/Edge, then install."""
    channel = os.environ.get("FULLSHOT_BROWSER_CHANNEL")
    attempts = [channel] if channel else [None, "chrome", "msedge"]
    errors = []
    for ch in attempts:
        try:
            return await pw.chromium.launch(headless=True, channel=ch) if ch else await pw.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001 - try the next option
            errors.append(f"{ch or 'bundled chromium'}: {str(exc).splitlines()[0]}")
    if os.environ.get("FULLSHOT_NO_AUTO_INSTALL") != "1":
        await asyncio.to_thread(_install_chromium)
        return await pw.chromium.launch(headless=True)
    raise CaptureError("no Chromium available:\n  " + "\n  ".join(errors))


async def _expand_iframes(page, notes: list[str]) -> None:
    for frame in page.frames[1:]:
        try:
            el = await frame.frame_element()
            box = await el.bounding_box()
            if not box or box["width"] < 50 or box["height"] < 50:
                continue
            inner = await frame.evaluate(
                "() => Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0)"
            )
            if inner > box["height"] + 4:
                await el.evaluate(
                    "(el, h) => { el.style.setProperty('height', h + 'px', 'important');"
                    " el.style.setProperty('max-height', 'none', 'important'); }",
                    min(int(inner), 20000),
                )
                notes.append(f"expanded iframe {frame.url[:80]} to {int(inner)}px")
        except Exception:  # cross-process / detached frames: leave as rendered
            continue


async def _capture_tiles(page, x: int, y: int, width: int, height: int, scale: float) -> Image.Image:
    out = Image.new("RGB", (int(round(width * scale)), int(round(height * scale))), (255, 255, 255))
    top = 0
    while top < height:
        h = min(TILE_CSS_PX, height - top)
        png = await page.screenshot(
            type="png",
            full_page=True,
            clip={"x": x, "y": y + top, "width": width, "height": h},
            animations="disabled",
            caret="hide",
            timeout=60000,
        )
        tile = Image.open(io.BytesIO(png)).convert("RGB")
        out.paste(tile, (0, int(round(top * scale))))
        top += h
    return out


async def capture(opts: CaptureOptions) -> CaptureResult:
    from playwright.async_api import async_playwright

    url = validate_url(opts.url, opts.allow_file)
    block_private = opts.block_private or _env_flag("FULLSHOT_BLOCK_PRIVATE")
    if block_private and urlparse(url).scheme in ("http", "https") and is_private_host(urlparse(url).hostname or ""):
        raise CaptureError("refusing to capture a private/loopback address (FULLSHOT_BLOCK_PRIVATE is on)")
    if opts.cdp_url:
        check_cdp_url(opts.cdp_url)
    notes: list[str] = []
    async with async_playwright() as pw:
        browser = None
        context = None
        owns_context = False
        if opts.cdp_url:
            browser = await pw.chromium.connect_over_cdp(opts.cdp_url)
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = await context.new_page()
            await page.set_viewport_size({"width": opts.width, "height": opts.height})
            if opts.scale != 1.0:
                notes.append("scale is ignored over CDP (uses the browser's own device pixel ratio)")
        else:
            browser = await _launch(pw)
            context = await browser.new_context(
                viewport={"width": opts.width, "height": opts.height},
                device_scale_factor=opts.scale,
                color_scheme=opts.color_scheme,  # type: ignore[arg-type]
                user_agent=opts.user_agent,
            )
            owns_context = True
            page = await context.new_page()
        try:
            if block_private:
                blocked: list[str] = []

                async def _guard(route):
                    host = urlparse(route.request.url).hostname or ""
                    if route.request.url.startswith(("http:", "https:")) and await asyncio.to_thread(is_private_host, host):
                        blocked.append(host)
                        await route.abort("blockedbyclient")
                    else:
                        await route.continue_()

                await page.route("**/*", _guard)
            if opts.color_scheme and opts.cdp_url:
                await page.emulate_media(color_scheme=opts.color_scheme)  # type: ignore[arg-type]
            page.set_default_timeout(opts.timeout_ms)
            try:
                await page.goto(url, wait_until=opts.wait_until, timeout=opts.timeout_ms)  # type: ignore[arg-type]
            except Exception as exc:
                if "Timeout" not in type(exc).__name__ and "Timeout" not in str(exc):
                    raise
                notes.append(f"navigation hit the {opts.timeout_ms} ms timeout; capturing what loaded")
            if opts.wait_for_selector:
                await page.wait_for_selector(opts.wait_for_selector, timeout=opts.timeout_ms)

            await page.add_style_tag(content=PREP_CSS)
            if opts.hide_selectors:
                css = ",".join(opts.hide_selectors) + "{visibility:hidden !important;}"
                await page.add_style_tag(content=css)

            if opts.scroll_lazy and not opts.selector:
                await page.evaluate(LAZY_SCROLL_JS, {"maxHeight": opts.max_height_css})
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
            if opts.delay_ms:
                await page.wait_for_timeout(opts.delay_ms)

            if opts.freeze_fixed:
                n = await page.evaluate(FREEZE_FIXED_JS)
                if n:
                    notes.append(f"froze {n} fixed/sticky elements")
            if opts.expand_scrollers and not opts.selector:
                n = await page.evaluate(EXPAND_SCROLLERS_JS)
                if n:
                    notes.append(f"expanded {n} inner scroll container(s)")
            if opts.expand_iframes:
                await _expand_iframes(page, notes)
            await page.evaluate("() => window.scrollTo(0, 0)")
            await page.wait_for_timeout(150)

            m = await page.evaluate(MEASURE_JS)
            title = m["title"]
            truncated = False
            if opts.selector:
                el = await page.wait_for_selector(opts.selector, state="visible")
                assert el is not None
                await el.scroll_into_view_if_needed()
                box = await el.evaluate(
                    "e => { const r = e.getBoundingClientRect();"
                    " return {x: r.left + scrollX, y: r.top + scrollY, w: r.width, h: r.height}; }"
                )
                await page.evaluate("() => window.scrollTo(0, 0)")
                cx, cy = max(0, int(box["x"])), max(0, int(box["y"]))
                cw, ch = max(1, int(round(box["w"]))), max(1, int(round(box["h"])))
            else:
                cx, cy = 0, 0
                # Don't let a single overflowing element make the page super wide.
                cw = int(m["width"]) if m["width"] <= m["viewportWidth"] * 1.5 else int(m["viewportWidth"])
                ch = int(m["height"])
            if ch > opts.max_height_css:
                truncated = True
                notes.append(f"page is {ch}px tall; truncated to {opts.max_height_css}px (max_height_css)")
                ch = opts.max_height_css

            if block_private and blocked:
                notes.append(f"blocked {len(blocked)} request(s) to private hosts: {sorted(set(blocked))[:5]}")
            actual_scale = await page.evaluate("() => window.devicePixelRatio") if opts.cdp_url else opts.scale
            image = await _capture_tiles(page, cx, cy, cw, ch, actual_scale)

            if opts.collect_layout:
                boxes = await page.evaluate(LAYOUT_JS, {"limit": 150000})
                masks = LayoutMasks.from_boxes(boxes, image.height, actual_scale, offset_css=cy)
            else:
                masks = LayoutMasks.empty(image.height)

            return CaptureResult(
                image=image,
                masks=masks,
                url=url,
                final_url=page.url,
                title=title,
                captured_at=datetime.now().astimezone(),
                css_width=cw,
                css_height=ch,
                scale=actual_scale,
                truncated=truncated,
                notes=notes,
            )
        finally:
            await page.close()
            if owns_context:
                await context.close()
                await browser.close()
            # over CDP we leave the user's browser running


def default_basename(url: str, when: datetime) -> str:
    p = urlparse(url)
    slug = (p.netloc + p.path).strip("/") or "page"
    slug = re.sub(r"[^A-Za-z0-9]+", "-", slug).strip("-")[:80] or "page"
    return f"{slug}-{when.strftime('%Y%m%d-%H%M%S')}"


def resolve_output_dir(output_dir: str | None) -> Path:
    d = Path(output_dir or os.environ.get("FULLSHOT_OUTPUT_DIR") or Path.home() / "fullshot-captures")
    d = d.expanduser().resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d
