"""Console entry point — dispatches to login / list / download."""

from __future__ import annotations

import asyncio
import datetime
import re
import sys
from pathlib import Path

from playwright.async_api import async_playwright

from echo360_downloader.auth import do_login, ensure_session
from echo360_downloader.cli import parse_args
from echo360_downloader.download import download_stream
from echo360_downloader.scraper import get_course_name, get_lecture_list
from echo360_downloader.streams import capture_m3u8_urls, resolve_streams
from echo360_downloader.ui import (
    console,
    divider,
    error,
    heading,
    info,
    lecture_list_table,
    success,
    warning,
)
from echo360_downloader.utils import sanitize_folder_name


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _resolve_target(target: str | None, total: int) -> list[int]:
    """Convert a user-supplied target into a list of zero-based indices."""
    if target is None or target.upper() == "ALL":
        return list(range(total))
    try:
        n = int(target)
        return [n - 1]  # 1-indexed → 0-indexed
    except ValueError:
        error(f"Invalid target: {target}. Use a number, 'ALL', or omit.")
        sys.exit(1)


def _parse_date_to_iso(raw: str) -> str:
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


def _lecture_course_dir(
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
        date_iso = _parse_date_to_iso(lecture_title)
    prefix = f"{date_iso}_{start_time}" if start_time else date_iso
    folder_name = sanitize_folder_name(f"{prefix} - {lecture_title}".strip(" -"))
    return download_root / course_dir_name / folder_name


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


async def _cmd_list(state_path: Path, section_url: str) -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            storage_state=str(state_path),
            viewport={"width": 1280, "height": 900},
        )
        page = await ctx.new_page()

        # Auto-handle stale / missing session
        await ensure_session(state_path, page, section_url)

        course_name = await get_course_name(page)
        heading(f"Course: {course_name}")

        lectures = await get_lecture_list(page)
        if not lectures:
            warning("No lectures found.")
            await browser.close()
            return

        lecture_list_table(lectures, course_name)
        await browser.close()


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


async def _download_lecture(
    course_url: str,
    ctx,
    lesson_id: str,
    lecture_title: str,
    lecture_dir: Path,
    idx: int | None = None,
) -> dict[str, bool]:
    """Download all available streams for a single lecture."""
    prefix = f"[{idx}] " if idx else ""
    console.print(f"\n{prefix}[bold]{lecture_title}[/]")

    page = await ctx.new_page()
    all_m3u8: set[str] = set()
    await capture_m3u8_urls(page, all_m3u8)
    streams_result: dict[str, bool] = {}

    # Keep request listener for late M3U8 requests after click
    def _capture(req):
        url = req.url
        if ".m3u8" in url and "content.echo360" in url:
            all_m3u8.add(url)

    page.on("request", _capture)

    try:
        await page.goto(course_url, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(2_000)

        # Click the target lecture row
        clicked = await page.evaluate(
            """(lessonId) => {
                const rows = document.querySelectorAll('.class-row');
                for (const row of rows) {
                    if (row.getAttribute('data-test-lessonid') === lessonId) {
                        row.scrollIntoView({block: 'center'});
                        return true;
                    }
                }
                return false;
            }""",
            lesson_id,
        )
        if not clicked:
            warning(f"Row not found for lessonId: {lesson_id[:60]}")
            await page.close()
            return {}

        rows = await page.query_selector_all(f'[data-test-lessonid="{lesson_id}"]')
        if not rows:
            warning("Row not found via selector")
            await page.close()
            return {}

        await rows[0].click()
        await page.wait_for_timeout(12_000)
        # Listen a bit more for any late M3U8 requests
        await page.wait_for_timeout(10_000)

        streams = resolve_streams(all_m3u8)

        if not streams:
            warning("No streams found for this lecture")
            await page.close()
            return {}

        info(f"Streams: {', '.join(streams.keys())}")

        # Save each stream
        lecture_dir.mkdir(parents=True, exist_ok=True)
        cookies = await ctx.cookies()
        audio_url = streams.get("audio")

        safe_title = sanitize_folder_name(lecture_title)
        for stream_type, stream_url in streams.items():
            output = lecture_dir / f"{stream_type} - {safe_title}.mp4"
            if len(str(output)) > 240:
                output = lecture_dir / f"{stream_type}.mp4"

            if stream_type in ("combined", "camera") and audio_url:
                ok = await download_stream(
                    stream_url, output, cookies, audio_url=audio_url
                )
            else:
                ok = await download_stream(stream_url, output, cookies)
            streams_result[stream_type] = ok

    except Exception as exc:
        error(f"Download error: {exc}")
    finally:
        await page.close()

    return streams_result


async def _cmd_download(
    state_path: Path,
    section_url: str,
    target: str | None,
    output_dir: Path,
    headed: bool,
) -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not headed)
        ctx = await browser.new_context(
            storage_state=str(state_path),
            viewport={"width": 1280, "height": 900},
        )
        page = await ctx.new_page()

        # Auto-handle stale / missing session
        await ensure_session(state_path, page, section_url)

        course_name = await get_course_name(page)
        course_dir_name = sanitize_folder_name(course_name)
        course_root = output_dir / course_dir_name
        course_root.mkdir(parents=True, exist_ok=True)

        heading(f"Course: {course_name}")
        info(f"Output: [underline]{course_root}/[/]")
        console.print()

        lectures = await get_lecture_list(page)
        if not lectures:
            warning("No lectures found.")
            await browser.close()
            return

        indices = _resolve_target(target, len(lectures))
        console.print(
            f"[dim]Downloading {len(indices)} lecture(s) out of "
            f"{len(lectures)} total[/dim]"
        )

        total_streams = 0
        successful = 0

        for idx in indices:
            lec = lectures[idx]
            title = lec.get("ariaLabel") or lec.get("text", f"Lecture {idx + 1}")
            lesson_id = lec["lessonId"]
            lecture_dir = _lecture_course_dir(
                output_dir,
                course_dir_name,
                title,
                lec.get("date", ""),
                lec.get("startTime", ""),
            )

            results = await _download_lecture(
                section_url, ctx, lesson_id, title, lecture_dir, idx + 1
            )
            for ok in results.values():
                total_streams += 1
                if ok:
                    successful += 1

        divider()
        if successful == total_streams:
            success(f"All {successful}/{total_streams} streams downloaded successfully")
        else:
            warning(
                f"{successful}/{total_streams} streams downloaded "
                f"({total_streams - successful} failed)"
            )
        info(f"Output: [underline]{course_root}/[/]")
        await browser.close()


# ---------------------------------------------------------------------------
# Main dispatch
# ---------------------------------------------------------------------------


def _auto_login(state_path: Path) -> None:
    """Prompt user, perform interactive login, then continue."""
    info(f"No saved session found at [underline]{state_path}[/]")
    asyncio.run(do_login(state_path))
    success("Login complete, continuing...")


def main(argv: list[str] | None = None) -> None:
    """Parse args and dispatch to the appropriate command."""
    args = parse_args(argv)
    state_path = args.state

    if args.command == "login":
        heading("Echo360 Login")
        asyncio.run(do_login(state_path))
        return

    # Auto-login if no session exists yet
    if not state_path.exists():
        _auto_login(state_path)

    if args.command == "list":
        asyncio.run(_cmd_list(state_path, args.section_url))
    elif args.command == "download":
        from echo360_downloader.utils import check_ffmpeg

        check_ffmpeg()
        asyncio.run(
            _cmd_download(
                state_path,
                args.section_url,
                args.target,
                args.output_dir,
                args.headed,
            )
        )
    elif args.command == "batch":
        from echo360_downloader.batch import run_batch

        asyncio.run(
            run_batch(
                args.batch_file,
                state_path,
                args.output_dir,
                args.headed,
            )
        )


if __name__ == "__main__":
    main()
