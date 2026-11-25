"""Smoke test: start the MCP server over stdio, list tools, call capture_page."""
import asyncio, json, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main(url, out):
    import os, shutil
    if os.environ.get("SMOKE_UVX"):  # exactly what the plugin manifests run
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        params = StdioServerParameters(command=shutil.which("uvx"), args=["--from", root, "fullshot-mcp"])
    else:
        params = StdioServerParameters(command=sys.executable, args=["-m", "fullshot.server"])
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = await s.list_tools()
            print("tools:", [t.name for t in tools.tools])
            res = await s.call_tool("capture_page", {"url": url, "formats": ["png", "pdf"], "stamp": "bottom",
                                                     "date_format": "iso", "paper": "letter", "output_dir": out})
            print("isError:", getattr(res, "is_error", getattr(res, "isError", None)))
            for c in res.content:
                if c.type == "text":
                    try:
                        d = json.loads(c.text)
                    except ValueError:
                        print("text:", c.text[:500]); continue
                    print("files:", [(f["format"], f.get("pages") or f"{f['width']}x{f['height']}") for f in d["files"]])
                else:
                    print("content:", c.type, getattr(c, "mime_type", getattr(c, "mimeType", "")), len(getattr(c, "data", "")))

asyncio.run(main(sys.argv[1], sys.argv[2]))
