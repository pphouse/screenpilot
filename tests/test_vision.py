"""Tests for vision module (unit tests that don't require display)."""

from unittest.mock import MagicMock, patch

from PIL import Image

from screenpilot.vision.analyzer import ScreenState, UIElement
from screenpilot.vision.capture import Screenshot


def test_screenshot_creation():
    img = Image.new("RGB", (1920, 1080), color="red")
    ss = Screenshot(image=img, timestamp=1000.0, monitor_index=0, width=1920, height=1080)
    assert ss.width == 1920
    assert ss.height == 1080


def test_screenshot_to_base64():
    img = Image.new("RGB", (100, 100), color="blue")
    ss = Screenshot(image=img, timestamp=1000.0, monitor_index=0, width=100, height=100)
    b64 = ss.to_base64()
    assert isinstance(b64, str)
    assert len(b64) > 0


def test_screenshot_resize():
    img = Image.new("RGB", (3840, 2160), color="green")
    ss = Screenshot(image=img, timestamp=1000.0, monitor_index=0, width=3840, height=2160)
    resized = ss.resize(1920, 1080)
    assert resized.width == 1920
    assert resized.height == 1080


def test_screenshot_resize_no_change():
    img = Image.new("RGB", (800, 600), color="white")
    ss = Screenshot(image=img, timestamp=1000.0, monitor_index=0, width=800, height=600)
    resized = ss.resize(1920, 1080)
    assert resized.width == 800  # Should not upscale


def test_ui_element_center():
    el = UIElement(label="button", element_type="button", x=100, y=200, width=50, height=30)
    cx, cy = el.center
    assert cx == 125
    assert cy == 215


def test_screen_state_find_element():
    state = ScreenState(
        elements=[
            UIElement(label="Search Bar", element_type="text_field", x=100, y=50),
            UIElement(label="Submit Button", element_type="button", x=200, y=100, text="Submit"),
        ]
    )
    el = state.find_element("search")
    assert el is not None
    assert el.label == "Search Bar"

    el = state.find_element("submit")
    assert el is not None
    assert el.element_type == "button"

    el = state.find_element("nonexistent")
    assert el is None


def test_screen_state_find_by_type():
    state = ScreenState(
        elements=[
            UIElement(label="btn1", element_type="button", x=0, y=0),
            UIElement(label="input1", element_type="text_field", x=0, y=0),
            UIElement(label="btn2", element_type="button", x=0, y=0),
        ]
    )
    buttons = state.find_elements_by_type("button")
    assert len(buttons) == 2
