"""Tests for Set-of-Mark visual prompting."""

from PIL import Image

from screenpilot.vision.som import (
    MarkedRegion,
    SoMResult,
    annotate_with_marks,
    create_grid_marks,
)


def test_create_grid_marks():
    img = Image.new("RGB", (800, 600), color="white")
    result = create_grid_marks(img, grid_size=(4, 3))
    assert isinstance(result, SoMResult)
    assert result.annotated_image.size == (800, 600)
    assert len(result.regions) == 12  # 4x3 grid
    assert result.regions[0].mark_id == 1
    assert result.regions[-1].mark_id == 12


def test_grid_marks_dimensions():
    img = Image.new("RGB", (1920, 1080), color="black")
    result = create_grid_marks(img, grid_size=(8, 6))
    assert len(result.regions) == 48

    # Check first region
    r = result.regions[0]
    assert r.x == 0
    assert r.y == 0
    assert r.width == 1920 // 8
    assert r.height == 1080 // 6


def test_annotate_with_marks():
    img = Image.new("RGB", (800, 600), color="white")
    regions = [
        (100, 100, 50, 30),
        (200, 200, 80, 40),
        (400, 300, 60, 35),
    ]
    labels = ["Button", "Input", "Link"]

    result = annotate_with_marks(img, regions, labels)
    assert len(result.regions) == 3
    assert result.regions[0].label == "Button"
    assert result.regions[1].label == "Input"
    assert result.regions[2].label == "Link"


def test_marked_region_center():
    region = MarkedRegion(mark_id=1, x=100, y=200, width=50, height=30)
    cx, cy = region.center
    assert cx == 125
    assert cy == 215


def test_marked_region_bbox():
    region = MarkedRegion(mark_id=1, x=100, y=200, width=50, height=30)
    left, top, right, bottom = region.bbox
    assert left == 100
    assert top == 200
    assert right == 150
    assert bottom == 230


def test_som_result_get_region():
    regions = [
        MarkedRegion(mark_id=1, x=0, y=0, width=100, height=100),
        MarkedRegion(mark_id=2, x=100, y=0, width=100, height=100),
        MarkedRegion(mark_id=3, x=200, y=0, width=100, height=100),
    ]
    img = Image.new("RGB", (300, 100), color="white")
    result = SoMResult(annotated_image=img, regions=regions)

    r = result.get_region(2)
    assert r is not None
    assert r.x == 100

    r = result.get_region(99)
    assert r is None


def test_grid_small_image():
    """Grid should adapt to small images."""
    img = Image.new("RGB", (100, 80), color="white")
    result = create_grid_marks(img, grid_size=(8, 6), min_region_size=30)
    # Should reduce grid to fit
    assert len(result.regions) > 0
    for region in result.regions:
        assert region.width >= 30 or region.height >= 30
