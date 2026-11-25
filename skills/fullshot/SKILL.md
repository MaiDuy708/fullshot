---
name: fullshot
description: Capture an entire web page (the whole scroll height, not just the visible viewport) as PNG, JPEG or a paginated PDF, optionally stamped with the page URL and capture date/time and split into pages without cutting text lines. Use when the user asks for a full-page screenshot, to archive or save a page as evidence, to print or export a page to PDF, or to show what a long page looks like.
version: 0.1.0
metadata:
  hermes:
    tags: [screenshot, web, pdf, archive]
    category: productivity
---

# fullshot: full-page screenshots

Use the `capture_page` tool from the `fullshot` MCP server. In Hermes the tool is
registered as `mcp_fullshot_capture_page`. Files are written to disk. The tool
result lists each file's path, pixel size or page count, and SHA-256 hash. It
also returns a small preview of the top of the page so you can check the
capture.

## Choosing options

| User wants | Arguments |
|---|---|
| "screenshot the whole page" | `formats: ["png"]` (default) |
| a PDF to read or print | `formats: ["pdf"]`, `paper: "a4"` or `"letter"` (add `-landscape` for wide pages) |
| proof of what a page showed, and when | `stamp: "browser"` or `"top"`, `date_format: "iso"`, keep the `.json` sidecar |
| one long PDF page instead of paper pages | `paper: "full"` |
| only one part of the page | `selector: "<css selector>"` |
| no cookie banner or chat bubble | `hide_selectors: ["#cookie-banner", ".intercom-launcher"]` |
| a header that repeats or covers content | `freeze_fixed: true` |
| retina or very sharp output | `scale: 2` |
| a mobile layout | `width: 390` |
| a page that needs the user's login | ask the user to start Chrome with `--remote-debugging-port=9222`, then pass `cdp_url: "http://127.0.0.1:9222"` |

Smart splitting is on by default. When a PDF is paginated, or a very tall image
(over 30,000 px) is cut into parts, the cut lines are moved up to a gap between
text lines and outside images, tables and code blocks. Turn it off
(`smart_split: false`) only if the user asks for fixed-height pages.

Stamp styles:
- `none`: no stamp.
- `top` / `bottom`: a thin bar with the URL and the time.
- `browser`: a neutral browser-window frame with an address bar.

In a PDF the stamp becomes a header (or footer), and the URL in it is a
clickable link.

Date formats: `date`, `datetime` (local time with UTC offset), `iso`, `none`,
or any strftime pattern such as `%d/%m/%Y %H:%M`. Pass `utc: true` for UTC
times.

## After capturing

- Tell the user where the files are: give the paths from the result.
- If `truncated` is true, the page was taller than 60,000 CSS px (often infinite
  scroll) and only the top part was captured. Say so.
- Report any `notes`, such as "expanded 1 inner scroll container". These explain
  how the page was handled.
- To turn an existing tall image into a PDF, use the `image_to_pdf` tool.

## Limits

- Only http and https URLs are allowed. file:// URLs work only when the server
  runs with `FULLSHOT_ALLOW_FILE=1`.
- Pages behind a login need `cdp_url`, which connects to the user's own Chrome.
  Use it only when the user asks.
- Infinite-scroll feeds are capped at 60,000 CSS px.
