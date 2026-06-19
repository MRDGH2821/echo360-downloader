"""Utility helpers: path sanitization, cookie handling, platform detection."""

from __future__ import annotations

import datetime
import os
import re
from pathlib import Path


def sanitize_filename(name: str, max_length: int = 200) -> str:
    """Remove characters problematic for filenames across platforms."""
    safe = re.sub(r'[<>:"/\\|?*]', "", name)
    safe = re.sub(r"\s+", " ", safe).strip()
    return safe[:max_length]


def build_cookie_string(cookies: list[dict], domain_hint: str = "echo360") -> str:
    """Build a ``Cookie`` header value from a list of cookie dicts."""
    pairs = [
        f"{c['name']}={c['value']}"
        for c in cookies
        if domain_hint in c.get("domain", "")
    ]
    return "; ".join(pairs)


def extract_section_id(url: str) -> str | None:
    """Extract the section UUID from an Echo360 section URL."""
    m = re.search(r"/section/([a-f0-9-]+)", url)
    return m.group(1) if m else None


def sanitize_folder_name(name: str) -> str:
    """Sanitize and truncate a folder name."""
    safe = re.sub(r'[<>:"/\\|?*]', "", name)
    safe = re.sub(r"\s+", " ", safe).strip()
    return safe[:100]


def default_state_path() -> Path:
    """Path for the Playwright storage state file, platform-aware.

    Linux / macOS:  $XDG_STATE_HOME/echo360/state.json
                    (~/.local/state/echo360/state.json by default)

    Windows:        %LOCALAPPDATA%\\echo360\\state.json
                    (~\\AppData\\Local\\echo360\\state.json by default)
    """
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        xdg = os.environ.get("XDG_STATE_HOME")
        base = Path(xdg) if xdg else Path.home() / ".local" / "state"
    return base / "echo360" / "state.json"


def check_ffmpeg() -> None:
    """Verify ffmpeg is available on PATH, with a platform-specific hint if not."""
    import shutil

    if shutil.which("ffmpeg"):
        return

    from echo360_downloader.ui import error

    if os.name == "nt":
        msg = (
            "ffmpeg not found on PATH.\n"
            "  Install via:  winget install ffmpeg\n"
            "  Or download:  https://ffmpeg.org/download.html#build-windows\n"
            "  Then add the bin\\ folder to your PATH."
        )
    else:
        msg = (
            "ffmpeg not found on PATH.\n"
            "  Debian/Ubuntu:  sudo apt install ffmpeg\n"
            "  macOS:          brew install ffmpeg\n"
            "  Arch:           sudo pacman -S ffmpeg"
        )
    error(msg)
    raise RuntimeError(msg)


# ---------------------------------------------------------------------------
# Date parsing & folder construction
# ---------------------------------------------------------------------------


def parse_date_to_iso(raw: str) -> str:
    """Extract a date from a lecture title and convert to YYYY-MM-DD.

    Handles formats like ``March 4, 2026`` or ``March 4 2026``.
    Returns the ISO string, or an empty string if no date is found.
    """
    m = re.search(r"(\w+ \d+,? \d{4})", raw)
    if not m:
        return ""
    cleaned = m.group(1).replace(",", "")
    for fmt in ("%B %d %Y", "%b %d %Y"):
        try:
            return datetime.datetime.strptime(cleaned, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return ""


def lecture_course_dir(
    download_root: Path,
    course_dir_name: str,
    lecture_title: str,
    date_iso: str = "",
    start_time: str = "",
) -> Path:
    """Build the per-lecture subdirectory within a course folder.

    *date_iso* is an ISO 8601 date (YYYY-MM-DD) and *start_time* is the
    24-hour start time (HH:mm) extracted from the Echo360 lesson ID.
    When *start_time* is provided the folder name becomes
    ``YYYY-MM-DD_HH:mm - Title/``, ensuring proper chronological sort
    even with multiple lectures on the same day.
    """
    if not date_iso:
        date_iso = parse_date_to_iso(lecture_title)
    prefix = f"{date_iso}_{start_time}" if start_time else date_iso
    folder_name = sanitize_folder_name(f"{prefix} - {lecture_title}".strip(" -"))
    return download_root / course_dir_name / folder_name
