"""
Stubbed recent_scanner.

The real recent scanner is disabled for now because scanning huge
download trees was causing performance issues. This stub keeps the
Python module importable and compilable so the container can start.
"""

def start_recent_scanner(app):
    """
    No-op stub.

    Kept for backwards compatibility with older app.py versions
    that might still call start_recent_scanner(app).
    """
    # Use logger if available, but don't crash if not
    logger = getattr(app, "logger", None)
    if logger:
        logger.warning("Recent scanner is disabled (stub). Doing nothing.")
