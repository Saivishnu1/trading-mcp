from __future__ import annotations

import base64
import io
import matplotlib.pyplot as plt


def fig_to_base64(fig: plt.Figure) -> str:
    """Save matplotlib figure to a bytes buffer and encode it in base64."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=fig.dpi, facecolor=fig.get_facecolor())
    buf.seek(0)
    img_bytes = buf.read()
    return base64.b64encode(img_bytes).decode("utf-8")


def validate_png(b64_str: str) -> bool:
    """Verify if a base64 encoded string represents a valid PNG image."""
    try:
        decoded = base64.b64decode(b64_str)
        # PNG magic bytes header: 89 50 4E 47 0D 0A 1A 0A
        return decoded.startswith(b"\x89PNG\r\n\x1a\n")
    except Exception:
        return False


def get_pixel_dimensions(figsize: tuple[float, float], dpi: int) -> tuple[int, int]:
    """Calculate exact width and height of chart in pixels."""
    return int(figsize[0] * dpi), int(figsize[1] * dpi)
