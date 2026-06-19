"""Lecture selection parsing and interactive prompting."""

from __future__ import annotations

import sys

from echo360_downloader.ui import console, error, info, lecture_list_table


def parse_selection(raw: str, total: int) -> list[int]:
    """Parse a user selection string into zero-based lecture indices.

    Accepts:
        "all" / "a"       — every lecture
        "1,3,5"           — explicit numbers
        "1-5"             — range (inclusive)
        "1,3,5-8,12"      — mixed commas and ranges

    Returns sorted unique 0-based indices.  Exits on invalid input.
    """
    if raw.strip().lower() in ("all", "a", ""):
        return list(range(total))

    indices: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            edges = part.split("-", 1)
            try:
                lo, hi = int(edges[0]), int(edges[1])
            except ValueError:
                error(f"Invalid range: '{part}'. Use numbers like 1-5.")
                sys.exit(1)
            if lo < 1 or hi > total or lo > hi:
                error(f"Range {lo}-{hi} out of bounds (1–{total}).")
                sys.exit(1)
            indices.update(range(lo - 1, hi))
        else:
            try:
                n = int(part)
            except ValueError:
                error(f"Invalid number: '{part}'. Use numbers, ranges, or 'all'.")
                sys.exit(1)
            if n < 1 or n > total:
                error(f"Lecture {n} out of bounds (1–{total}).")
                sys.exit(1)
            indices.add(n - 1)

    if not indices:
        error("No valid lectures selected.")
        sys.exit(1)
    return sorted(indices)


def prompt_lecture_selection(lectures: list[dict], course_name: str) -> list[int]:
    """Display the lecture table and prompt the user to pick which to download.

    Returns a list of zero-based indices for the selected lectures.
    """
    lecture_list_table(lectures, course_name)
    console.print()
    hint = (
        f"[bold cyan]Select lectures[/] to download "
        f"[dim](1–{len(lectures)}, comma-separated, ranges like 1-5, "
        f"or 'all')[/dim]"
    )
    console.print(hint)
    try:
        raw = input("▶ ").strip()
    except (EOFError, KeyboardInterrupt):
        console.print()
        info("Aborted.")
        sys.exit(0)
    return parse_selection(raw, len(lectures))


def resolve_target(target: str | None, total: int) -> list[int]:
    """Convert a user-supplied target into a list of zero-based indices."""
    if target is None or target.upper() == "ALL":
        return list(range(total))
    try:
        n = int(target)
        return [n - 1]  # 1-indexed → 0-indexed
    except ValueError:
        error(f"Invalid target: {target}. Use a number, 'ALL', or omit.")
        sys.exit(1)
