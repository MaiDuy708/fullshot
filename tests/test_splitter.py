"""Unit tests for smart page splitting (no browser needed)."""
from PIL import Image, ImageDraw

from fullshot.splitter import KIND_OBJECT, KIND_TEXT, LayoutMasks, PixelRows, choose_breaks, slices


def make_text_image(lines=200, line_h=24, gap=8, width=400):
    h = lines * (line_h + gap)
    img = Image.new("RGB", (width, h), "white")
    d = ImageDraw.Draw(img)
    boxes = []
    y = 0
    for _ in range(lines):
        d.rectangle((10, y + 4, width - 10, y + line_h - 4), fill="black")
        boxes.append([y, y + line_h, KIND_TEXT])
        y += line_h + gap
    return img, boxes


def test_naive_split_cuts_text():
    img, boxes = make_text_image()
    masks = LayoutMasks.from_boxes(boxes, img.height)
    br = choose_breaks(img.height, 1000, smart=False)
    assert any(masks.text[y] for y in br)


def test_dom_split_never_cuts_text():
    img, boxes = make_text_image()
    masks = LayoutMasks.from_boxes(boxes, img.height)
    br = choose_breaks(img.height, 1000, masks=masks)
    assert br and not any(masks.text[y] for y in br)
    assert all(b - a <= 1000 for a, b in slices(img.height, br))


def test_pixel_only_split_finds_gaps():
    img, boxes = make_text_image()
    ink = [[t + 4, b - 4, k] for t, b, k in boxes]  # rows that actually hold pixels
    truth = LayoutMasks.from_boxes(ink, img.height)
    br = choose_breaks(img.height, 1000, masks=None, pixels=PixelRows(img))
    assert not any(truth.text[y] for y in br)


def test_object_avoided_when_possible():
    h = 3000
    masks = LayoutMasks.from_boxes([[850, 1050, KIND_OBJECT]], h)
    br = choose_breaks(h, 1000, masks=masks)
    assert br[0] <= 850


def test_object_taller_than_window_still_cut():
    h = 5000
    masks = LayoutMasks.from_boxes([[0, 5000, KIND_OBJECT]], h)
    br = choose_breaks(h, 1000, masks=masks)
    assert br[0] == 1000  # nowhere clean: keep the page full


def test_scale_applied():
    masks = LayoutMasks.from_boxes([[100, 120, KIND_TEXT]], 400, scale=2.0)
    assert masks.text[220] and not masks.text[260]


def test_slices_cover_everything():
    s = slices(2500, [1000, 2000])
    assert s == [(0, 1000), (1000, 2000), (2000, 2500)]
