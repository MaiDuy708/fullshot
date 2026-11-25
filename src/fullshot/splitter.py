"""Smart page splitting.

Picks cut lines for a tall image so that text lines, images and other
"atomic" elements are not sliced in half.

Two signals are combined:

1. DOM layout (preferred): rectangles of every rendered text line and of
   replaced/atomic elements (img, svg, video, canvas, pre, tr, ...), collected
   from the live page in CSS pixels.
2. Pixels (fallback / tie-breaker): a row whose pixels are nearly uniform is a
   gap between content - the same idea GoFullPage uses ("scan upwards for a
   cleaner point to cut").

For each page the splitter looks backwards from the ideal break line, inside a
window of ``max_back`` of the page height, and picks the row with the lowest
cost. Cost: inside a text line (high) > inside an object (medium) >
non-uniform pixel row (low) > clean row (0), plus a small penalty that grows
with the distance from the ideal break, so pages stay as full as possible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

from PIL import Image

TEXT_COST = 100.0
OBJECT_COST = 40.0
BUSY_PIXEL_COST = 10.0
DISTANCE_COST = 5.0  # cost of moving the cut back by a whole page

# Kinds of layout boxes reported by the page script.
KIND_OBJECT = 1
KIND_TEXT = 2


@dataclass
class LayoutMasks:
    """Per-row masks in *image* pixels (already multiplied by device scale)."""

    height: int
    text: bytearray = field(default_factory=bytearray)
    objects: bytearray = field(default_factory=bytearray)

    @classmethod
    def empty(cls, height: int) -> "LayoutMasks":
        return cls(height, bytearray(height), bytearray(height))

    @classmethod
    def from_boxes(
        cls,
        boxes: Iterable[Sequence[float]],
        height: int,
        scale: float = 1.0,
        offset_css: float = 0.0,
    ) -> "LayoutMasks":
        """Build masks from ``[top, bottom, kind]`` boxes in CSS px.

        ``offset_css`` is subtracted from every box (used when the capture
        starts below the top of the document, e.g. a selector capture).
        Only rows strictly inside a box are marked, so the boundary between two
        touching lines stays a legal cut.
        """
        masks = cls.empty(height)
        for box in boxes:
            if len(box) < 3:
                continue
            top, bottom, kind = box[0], box[1], int(box[2])
            a = int((top - offset_css) * scale) + 1
            b = int((bottom - offset_css) * scale)
            a = max(a, 0)
            b = min(b, height)
            if b <= a:
                continue
            target = masks.text if kind == KIND_TEXT else masks.objects
            target[a:b] = b"\x01" * (b - a)
        return masks


class PixelRows:
    """Lazy, cached "is this row visually busy?" test on an image."""

    def __init__(self, image: Image.Image, threshold: int = 14, sample_width: int = 800):
        # Downsample horizontally for speed; keep every row.
        gray = image.convert("L")
        if gray.width > sample_width:
            gray = gray.resize((sample_width, gray.height), Image.Resampling.BOX)
        self._img = gray
        self._threshold = threshold
        self._cache: dict[int, bool] = {}

    def busy(self, y: int) -> bool:
        hit = self._cache.get(y)
        if hit is not None:
            return hit
        lo, hi = self._img.crop((0, y, self._img.width, y + 1)).getextrema()
        result = (hi - lo) > self._threshold
        self._cache[y] = result
        return result


def choose_breaks(
    total_height: int,
    page_height: int,
    masks: LayoutMasks | None = None,
    pixels: PixelRows | None = None,
    max_back: float = 0.25,
    smart: bool = True,
) -> list[int]:
    """Return the y coordinates (image px) where the image should be cut.

    The result does not include 0 or ``total_height``. Every slice is at most
    ``page_height`` tall and at least ``(1 - max_back) * page_height`` tall
    (except the last one).
    """
    if page_height <= 0:
        raise ValueError("page_height must be positive")
    breaks: list[int] = []
    start = 0
    while total_height - start > page_height:
        target = start + page_height
        if not smart:
            best = target
        else:
            lo = start + max(1, int(page_height * (1.0 - max_back)))
            best = target
            best_cost = float("inf")
            for y in range(target, lo - 1, -1):
                cost = (target - y) / page_height * DISTANCE_COST
                if masks is not None and y < masks.height:
                    if masks.text[y]:
                        cost += TEXT_COST
                    if masks.objects[y]:
                        cost += OBJECT_COST
                # Pixel check only matters when the DOM says the row is free
                # (or we have no DOM info at all).
                if cost < OBJECT_COST and pixels is not None and pixels.busy(y):
                    cost += BUSY_PIXEL_COST
                if cost < best_cost:
                    best, best_cost = y, cost
                    if cost == 0.0:
                        break  # clean row right at the target: can't do better
        breaks.append(best)
        start = best
    return breaks


def slices(total_height: int, breaks: Sequence[int]) -> list[tuple[int, int]]:
    """Turn break lines into ``(top, bottom)`` slices."""
    edges = [0, *breaks, total_height]
    return [(edges[i], edges[i + 1]) for i in range(len(edges) - 1)]
