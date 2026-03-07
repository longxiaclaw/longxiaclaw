"""Colors and styles for the TUI."""

from __future__ import annotations

BRAND_COLOR = "bright_cyan"
PROMPT_COLOR = "bold bright_cyan"
RESPONSE_COLOR = "white"
THINKING_COLOR = "dim italic"
ERROR_COLOR = "bold red"
PROCESSING_COLOR = "bold bright_yellow"
MUTED_COLOR = "dim"

# Gradient stops: gold → deep orange (7 stops)
GRADIENT_COLORS: list[tuple[int, int, int]] = [
    (255, 200, 0),
    (255, 180, 0),
    (255, 160, 0),
    (255, 140, 0),
    (255, 120, 0),
    (255, 100, 0),
    (255, 80, 0),
]

# Style dictionary for Rich Console
STYLES = {
    "brand": BRAND_COLOR,
    "prompt": PROMPT_COLOR,
    "response": RESPONSE_COLOR,
    "thinking": THINKING_COLOR,
    "error": ERROR_COLOR,
    "processing": PROCESSING_COLOR,
    "muted": MUTED_COLOR,
    "header.name": f"bold {BRAND_COLOR}",
    "header.info": MUTED_COLOR,
    "header.status": "white",
    "header.hint": "dim italic",
    "separator": "dim",
    "status.info": MUTED_COLOR,
    "status.highlight": BRAND_COLOR,
}
