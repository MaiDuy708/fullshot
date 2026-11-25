# fullshot

Full-page web screenshots for AI agents and for people.

fullshot captures the whole scroll height of a page, not just the viewport. It
writes PNG, JPEG or a paginated PDF. It ships three ways:

- an **MCP server** (`fullshot-mcp`) for any MCP-capable agent, such as Hermes
  Agent, Claude Code or Cursor
- a **skill** (`skills/fullshot/SKILL.md`) that tells the agent when and how to
  use the server
- a **CLI** (`fullshot`) you can run yourself

One repository is both a portable **Agent Plugins v1** package (`plugin.json` +
`mcp.json`, used by Hermes) and a **Claude Code plugin** (`.claude-plugin/` +
`.mcp.json`).

## Features

| | |
|---|---|
| Full page | Captured in 4000 px tiles with `captureBeyondViewport` and stitched. This avoids Chromium's ~16k px single-capture limit and repeated sticky headers. |
| Lazy content | Scrolls through the page first so lazy images and infinite lists load. Capped at 60,000 CSS px. |
| Inner scrollers | Detects SPA layouts where `<body>` never scrolls and a big `<div>` does, then expands it. |
| iframes | Grows each iframe to its content height. |
| **Smart page splitting** | Cuts PDF pages, and images over 30,000 px, only between text lines and outside images, tables and code. It uses the live DOM layout, with a pixel scan as fallback. |
| **URL + date/time stamp** | `top` / `bottom` bar, or a neutral `browser` frame. Date formats: `date`, `datetime`, `iso`, `none`, or any strftime pattern. Local time or UTC. In a PDF the URL is a clickable link. |
| PDF | Paper: letter, legal, tabloid, A3, A4, A5, each with a `-landscape` variant, plus `full` (one long page, split at the 200 in PDF limit). Page numbers. Lossless or JPEG images. |
| Evidence | URL, title and capture time embedded in PNG/JPEG/PDF metadata. A `.json` sidecar holds SHA-256 hashes of every file. |
| No overwrites | If any output exists, the entire capture or `image_to_pdf` export gets a shared `-1`, `-2`, … basename suffix, including all image parts and the `.json` sidecar. |
| Extras | `selector` (one element), `hide_selectors` (cookie banners), `freeze_fixed`, `scale` (retina), mobile `width`, dark mode, and `cdp_url` to use your logged-in Chrome. |

Smart splitting on real pages (A4, 1280 px wide), counting cuts that slice
through a text line:

| page | pages | fixed cut | pixel only | fullshot (DOM + pixel) |
|---|---|---|---|---|
| docs.python.org/3/tutorial/classes.html | 10 | 7 | 2 | **0** |
| en.wikipedia.org/wiki/Screenshot | 3 | 1 | 2 | **0** |

Run it yourself with `uv run python tests/bench_split.py <url>...`.

## Requirements

- [uv](https://docs.astral.sh/uv/). The plugin starts the server with
  `uvx --from <plugin root> fullshot-mcp`, and uv installs Python dependencies
  on first run.
- Chromium. fullshot tries Playwright's bundled Chromium first, then an
  installed Chrome, then Edge. If none is found it runs
  `playwright install chromium` once. Set `FULLSHOT_NO_AUTO_INSTALL=1` to turn
  that off.

## Install

Replace `MaiDuy708/fullshot` with the GitHub repository you publish this to.

### Hermes Agent

```bash
hermes plugins install MaiDuy708/fullshot --enable
# or pin a commit:
hermes plugins install MaiDuy708/fullshot --ref <40-char-sha> --enable
hermes mcp test fullshot
```

Tools show up as `mcp_fullshot_capture_page` and `mcp_fullshot_image_to_pdf`.
The skill shows up as `fullshot:fullshot`.

To add only the MCP server, put this in `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  fullshot:
    command: "uvx"
    args: ["--from", "git+https://github.com/MaiDuy708/fullshot", "fullshot-mcp"]
```

### Claude Code

```
/plugin marketplace add MaiDuy708/fullshot
/plugin install fullshot@fullshot
```

### Any other MCP client

```json
{ "mcpServers": { "fullshot": { "command": "uvx", "args": ["--from", "git+https://github.com/MaiDuy708/fullshot", "fullshot-mcp"] } } }
```

### CLI for yourself

```bash
uv tool install git+https://github.com/MaiDuy708/fullshot
fullshot https://example.com -f png -f pdf --stamp browser --paper a4
fullshot example.com --selector main --hide "#cookie-banner" --scale 2
fullshot --from-image long.png --paper letter      # paginate an existing screenshot
fullshot --help
```

## Configuration (environment)

| variable | effect |
|---|---|
| `FULLSHOT_OUTPUT_DIR` | default output folder (otherwise `~/fullshot-captures`) |
| `FULLSHOT_BLOCK_PRIVATE=1` | refuse loopback, private and link-local hosts, including redirects and sub-requests (SSRF guard). Recommended for agents that read untrusted content. |
| `FULLSHOT_ALLOW_FILE=1` | allow `file://` URLs |
| `FULLSHOT_ALLOW_REMOTE_CDP=1` | allow `cdp_url` to point at another machine (off by default) |
| `FULLSHOT_BROWSER_CHANNEL` | force `chrome`, `msedge` or `chromium` |
| `FULLSHOT_FONT` | TTF used for image stamps |

## Pages behind a login

Start your own Chrome with remote debugging, then pass its address:

```bash
chrome --remote-debugging-port=9222 --user-data-dir=%LOCALAPPDATA%\fullshot-chrome
fullshot https://app.example.com/report --cdp http://127.0.0.1:9222
```

fullshot opens a new tab, captures it and closes the tab. Your browser keeps
running.

## Development

```bash
uv sync
uv run pytest
uv run python tests/mcp_smoke.py https://example.com ./out        # MCP round trip
SMOKE_UVX=1 uv run python tests/mcp_smoke.py https://example.com ./out   # exactly as the plugin launches it
```

On Windows, if the checkout path is very long, set `UV_PROJECT_ENVIRONMENT` to
a short folder. Some dependency files exceed the 260-character path limit.

## Credits

The capture approach is inspired by the MIT-licensed
[full-page-screen-capture-chrome-extension](https://github.com/mrcoles/full-page-screen-capture-chrome-extension)
by Peter Coles. fullshot shares no code with it and is not affiliated with
GoFullPage.

MIT License.
