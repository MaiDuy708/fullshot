"""Compare smart vs naive page breaks on real pages: how many cuts slice a text line."""
import asyncio, sys
from fullshot.capture import CaptureOptions, capture
from fullshot.splitter import PixelRows, choose_breaks

async def main(urls):
    for url in urls:
        r = await capture(CaptureOptions(url=url, delay_ms=500))
        page_h = int(r.image.width * (785.89 - 38) / 539.28)  # A4 content box ~ page height in px
        naive = choose_breaks(r.image.height, page_h, smart=False)
        dom = choose_breaks(r.image.height, page_h, r.masks)
        pix = choose_breaks(r.image.height, page_h, None, PixelRows(r.image))
        bad = lambda br: sum(1 for y in br if r.masks.text[y])
        print(f"{url}\n  size={r.image.size} notes={r.notes}\n  pages={len(naive)+1}  text-cuts: naive={bad(naive)}  pixel-only={bad(pix)}  dom+pixel={bad(dom)}")

asyncio.run(main(sys.argv[1:]))
