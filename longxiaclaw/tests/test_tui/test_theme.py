"""Tests for TUI theme."""

from __future__ import annotations

from longxiaclaw.tui.theme import (
    BRAND_COLOR, PROMPT_COLOR, RESPONSE_COLOR,
    THINKING_COLOR, ERROR_COLOR, PROCESSING_COLOR, MUTED_COLOR,
    GRADIENT_COLORS, STYLES,
)


class TestTheme:
    def test_brand_color_defined(self):
        assert BRAND_COLOR == "bright_cyan"

    def test_all_colors_are_strings(self):
        for color in (BRAND_COLOR, PROMPT_COLOR, RESPONSE_COLOR,
                      THINKING_COLOR, ERROR_COLOR, PROCESSING_COLOR,
                      MUTED_COLOR):
            assert isinstance(color, str)
            assert len(color) > 0

    def test_styles_dict_has_expected_keys(self):
        expected_keys = {"brand", "prompt", "response", "thinking", "error",
                         "processing", "muted", "header.status", "header.hint",
                         "separator"}
        assert expected_keys.issubset(set(STYLES.keys()))

    def test_styles_values_are_strings(self):
        for key, value in STYLES.items():
            assert isinstance(value, str)


class TestGradientColors:
    def test_gradient_is_list_of_7_tuples(self):
        assert isinstance(GRADIENT_COLORS, list)
        assert len(GRADIENT_COLORS) == 7

    def test_each_stop_is_rgb_tuple(self):
        for stop in GRADIENT_COLORS:
            assert isinstance(stop, tuple)
            assert len(stop) == 3
            for val in stop:
                assert isinstance(val, int)
                assert 0 <= val <= 255
