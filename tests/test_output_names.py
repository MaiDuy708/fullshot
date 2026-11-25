"""Output collision tests with in-memory images instead of a browser."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from threading import Barrier

import pytest
from PIL import Image

from fullshot.api import ExportOptions, export, image_to_pdf
from fullshot.capture import CaptureResult
from fullshot.splitter import LayoutMasks


def make_capture(height):
    return CaptureResult(
        image=Image.new("RGB", (400, height), "white"),
        masks=LayoutMasks.empty(height),
        url="https://example.com/",
        final_url="https://example.com/",
        title="Example",
        captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        css_width=400,
        css_height=height,
        scale=1,
        truncated=False,
        notes=[],
    )


def test_export_retries_whole_group_after_part_or_sidecar_collision(tmp_path):
    existing = {"shot-part2.jpg": b"old image", "shot-1.json": b"old metadata"}
    for name, contents in existing.items():
        (tmp_path / name).write_bytes(contents)

    summary = export(make_capture(1200), ExportOptions(
        basename="shot", output_dir=str(tmp_path), formats=["png", "jpeg", "pdf"],
        max_image_height=1000, smart_split=False,
    ))

    for name, contents in existing.items():
        assert (tmp_path / name).read_bytes() == contents
    paths = [Path(f["path"]) for f in summary["files"]]
    sidecar = Path(summary["metadata_file"])
    assert [p.name for p in paths] == [
        "shot-2-part1.png", "shot-2-part2.png", "shot-2-part1.jpg", "shot-2-part2.jpg", "shot-2.pdf",
    ]
    assert sidecar.name == "shot-2.json"
    assert json.loads(sidecar.read_text(encoding="utf-8"))["files"] == summary["files"]
    for entry, path in zip(summary["files"], paths, strict=True):
        contents = path.read_bytes()
        assert entry["bytes"] == len(contents)
        assert entry["sha256"] == sha256(contents).hexdigest()
    assert set(tmp_path.resolve().iterdir()) == {*paths, sidecar, *(tmp_path.resolve() / name for name in existing)}


@pytest.mark.parametrize("suffix", [None, ".pdf", ".json"])
def test_image_to_pdf_keeps_existing_outputs_next_to_source(tmp_path, suffix):
    source = tmp_path / "scan.v1.png"
    Image.new("RGB", (400, 1200), "white").save(source)
    source_bytes = source.read_bytes()
    existing = None if suffix is None else tmp_path / f"scan{suffix}"
    if existing is not None:
        existing.write_bytes(b"keep me")

    summary = image_to_pdf(str(source), ExportOptions(smart_split=False))

    expected_base = "scan" if existing is None else "scan-1"
    pdf = tmp_path.resolve() / f"{expected_base}.pdf"
    sidecar = pdf.with_suffix(".json")
    expected_names = {source.name, pdf.name, sidecar.name}
    if existing is not None:
        assert existing.read_bytes() == b"keep me"
        expected_names.add(existing.name)
    assert source.read_bytes() == source_bytes
    assert summary["files"][0]["path"] == str(pdf)
    assert summary["files"][0]["pages"] > 1
    assert pdf.read_bytes().startswith(b"%PDF-")
    assert summary["metadata_file"] == str(sidecar)
    assert {p.name for p in tmp_path.iterdir()} == expected_names


def test_concurrent_exports_get_distinct_names(tmp_path):
    start = Barrier(2)

    def run(_):
        result = make_capture(100)
        ex = ExportOptions(basename="shot", output_dir=str(tmp_path))
        start.wait(timeout=5)
        return export(result, ex)

    with ThreadPoolExecutor(max_workers=2) as pool:
        summaries = list(pool.map(run, range(2)))

    groups = {(Path(s["files"][0]["path"]).name, Path(s["metadata_file"]).name) for s in summaries}
    assert groups == {("shot.png", "shot.json"), ("shot-1.png", "shot-1.json")}


def test_dotted_basename_keeps_parts_distinct(tmp_path):
    summary = export(make_capture(1200), ExportOptions(
        basename="release.2026.v1", output_dir=str(tmp_path), max_image_height=1000, smart_split=False,
    ))

    assert [Path(f["path"]).name for f in summary["files"]] == ["release.2026-part1.png", "release.2026-part2.png"]
    assert [f["height"] for f in summary["files"]] == [1000, 200]
    assert Path(summary["metadata_file"]).name == "release.2026.json"


def test_duplicate_formats_keep_summary_order(tmp_path):
    summary = export(make_capture(100), ExportOptions(
        basename="shot", output_dir=str(tmp_path), formats=["png", "pdf", "png"],
    ))

    assert [f["format"] for f in summary["files"]] == ["png", "pdf", "png"]
    assert summary["files"][0] == summary["files"][2]
    assert {p.name for p in tmp_path.iterdir()} == {"shot.png", "shot.pdf", "shot.json"}
