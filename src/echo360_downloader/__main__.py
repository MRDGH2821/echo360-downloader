"""Console entry point — dispatches to login / list / download."""

import asyncio
import re
import sys
from pathlib import Path

from playwright.async_api import async_playwright

from echo360_downloader.auth import do_login, ensure_session
from echo360_downloader.cli import parse_args
from echo360_downloader.download import download_stream
from echo360_downloader.scraper import get_course_name, get_lecture_list
from echo360_downloader.streams import capture_m3u8_urls, resolve_streams
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
        print(f"Invalid target: {target}. Use a number, 'ALL', or omit.")
        sys.exit(1)


def _lecture_course_dir(
    download_root: Path,
    course_dir_name: str,
    lecture_title: str,
) -> Path:
    """Build the per-lecture subdirectory within a course folder."""
    date_match = re.search(r"(\w+ \d+,? \d{4})", lecture_title)
    date_part = date_match.group(1) if date_match else ""
    folder_name = sanitize_folder_name(f"{date_part} - {lecture_title}".strip(" -"))
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
        print(f"\nCourse: {course_name}")

        lectures = await get_lecture_list(page)
        if not lectures:
            print("No lectures found.")
            await browser.close()
            return

        print(f"Found {len(lectures)} lectures:\n")
        for i, lec in enumerate(lectures, 1):
            lesson_id = lec["lessonId"]
            aria = lec.get("ariaLabel", "")
            short = (lesson_id[:60] + "...") if len(lesson_id) > 60 else lesson_id
            print(f"  {i:2d}. {aria}")
            print(f"       lessonId: {short}")
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
    print(f"\n{prefix}Processing: {lecture_title}")

    page = await ctx.new_page()
    results: dict[str, bool] = {}

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
            print(f"    Row not found for lessonId: {lesson_id[:60]}")
            await page.close()
            return {}

        rows = await page.query_selector_all(f'[data-test-lessonid="{lesson_id}"]')
        if not rows:
            print("    Row not found via selector")
            await page.close()
            return {}

        await rows[0].click()
        await page.wait_for_timeout(12_000)

        m3u8_urls = await capture_m3u8_urls(page)
        streams = resolve_streams(m3u8_urls)

        if not streams:
            print("    No streams found for this lecture")
            await page.close()
            return {}

        print(f"    Streams available: {', '.join(streams.keys())}")

        # Save each stream
        lecture_dir.mkdir(parents=True, exist_ok=True)
        cookies = await ctx.cookies()
        audio_url = streams.get("audio")

        safe_title = sanitize_folder_name(lecture_title)
        for stream_type, stream_url in streams.items():
            output = lecture_dir / f"{safe_title} - {stream_type}.mp4"
            if len(str(output)) > 240:
                output = lecture_dir / f"{stream_type}.mp4"
            print(f"    Downloading {stream_type} stream...")

            if stream_type == "camera" and audio_url:
                ok = await download_stream(
                    stream_url, output, cookies, audio_url=audio_url
                )
            else:
                ok = await download_stream(stream_url, output, cookies)
            results[stream_type] = ok

    except Exception as exc:
        print(f"    ERROR: {exc}")
    finally:
        await page.close()

    return results


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

        print(f"\nCourse: {course_name}")
        print(f"Output: {course_root}/\n")

        lectures = await get_lecture_list(page)
        if not lectures:
            print("No lectures found.")
            await browser.close()
            return

        indices = _resolve_target(target, len(lectures))
        print(f"Downloading {len(indices)} lecture(s) out of {len(lectures)} total")

        total_streams = 0
        successful = 0

        for idx in indices:
            lec = lectures[idx]
            title = lec.get("ariaLabel") or lec.get("text", f"Lecture {idx + 1}")
            lesson_id = lec["lessonId"]
            lecture_dir = _lecture_course_dir(output_dir, course_dir_name, title)

            results = await _download_lecture(
                section_url, ctx, lesson_id, title, lecture_dir, idx + 1
            )
            for ok in results.values():
                total_streams += 1
                if ok:
                    successful += 1

        print(f"\n{'=' * 50}")
        print(f"Done! {successful}/{total_streams} streams downloaded successfully.")
        print(f"Output directory: {course_root}")
        await browser.close()


# ---------------------------------------------------------------------------
# Main dispatch
# ---------------------------------------------------------------------------


def _auto_login(state_path: Path) -> None:
    """Prompt user, perform interactive login, then continue."""
    print(f"No saved session found at {state_path}")
    asyncio.run(do_login(state_path))
    print("Login complete, continuing...\n")


def main(argv: list[str] | None = None) -> None:
    """Parse args and dispatch to the appropriate command."""
    args = parse_args(argv)
    state_path = args.state

    if args.command == "login":
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


if __name__ == "__main__":
    main()
