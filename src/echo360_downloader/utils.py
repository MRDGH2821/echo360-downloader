"""Utility helpers for path sanitization and cookie handling."""

import os
import re
from pathlib import Path


def sanitize_filename(name: str, max_length: int = 200) -> str:
    """Remove characters problematic for filenames across platforms."""
    safe = re.sub(r'[<>:"/\\|?*]', "", name)
    safe = re.sub(r"\s+", " ", safe).strip()
    return safe[:max_length]


def build_cookie_string(cookies: list[dict], domain_hint: str = "echo360") -> str:
    """Build a `Cookie` header value from a list of cookie dicts."""
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
    """Default path for the Playwright storage state file.

    Uses XDG_STATE_HOME (default: ~/.local/state) / echo360 / state.json.
    """
    xdg_state_home = os.environ.get("XDG_STATE_HOME")
    if xdg_state_home:
        base = Path(xdg_state_home)
    else:
        base = Path.home() / ".local" / "state"
    return base / "echo360" / "state.json"
