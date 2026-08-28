"""
backend/utils/formatting.py — Human-readable display helpers.

Previously format_bytes() was defined inline inside api_system_info()
in routes/admin.py — making it untestable and invisible to other callers.
"""


def format_bytes(b: int) -> str:
    """Convert a byte count to a human-readable string (KB / MB / GB / TB)."""
    if not b or b <= 0:
        return "0 GB"
    tb = b / (1024 ** 4)
    if tb >= 1.0:
        return f"{tb:.2f} TB" if tb < 10 else f"{tb:.1f} TB"
    gb = b / (1024 ** 3)
    if gb >= 1.0:
        return f"{gb:.2f} GB" if gb < 10 else f"{gb:.1f} GB"
    mb = b / (1024 ** 2)
    if mb >= 1.0:
        return f"{mb:.1f} MB"
    return f"{b / 1024:.0f} KB"
