"""Utility helpers: path sanitization, cookie handling, platform detection."""

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
    raise RuntimeError(msg)
