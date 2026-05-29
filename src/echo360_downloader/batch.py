"""Batch download from a YAML course list — reads URLs, downloads, writes status."""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any

import yaml

from echo360_downloader.ui import (
    console,
    divider,
    error,
    heading,
    info,
    subheading,
    success,
    warning,
)
from echo360_downloader.utils import sanitize_folder_name

# ---------------------------------------------------------------------------
# YAML schema helpers
# ---------------------------------------------------------------------------

_INITIAL_BATCH = """\
# echo360-dl batch file
# Add course section URLs under `courses`.
# Run: echo360-dl batch <this-file>
#
# After download the file is updated with per-lecture status.
courses:
  # - url: https://echo360.net.au/section/<your-section-uuid>
"""


def _default_course_entry(url: str) -> dict:
    """Return a minimal course dict for a new URL."""
    return {"url": url}


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------


def read_batch(path: Path) -> list[dict]:
    """Load a batch YAML file and return the list of course entries.

    Supports both string entries (just a URL) and dict entries with a
    ``url`` key.  All entries are normalised to dict form.

    If the file doesn't exist a template is written and the user is told
    to edit it.
    """
    if not path.exists():
        heading("New batch file")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_INITIAL_BATCH)
        info(f"Created template at [underline]{path}[/]")
        warning("Add course URLs to the file, then re-run this command.")
        return []

    raw = yaml.safe_load(path.read_text())
    if not raw or "courses" not in raw:
        warning("No 'courses' list found in the batch file.")
        return []

    courses = raw["courses"]
    if not isinstance(courses, list):
        warning("'courses' must be a list.")
        return []

    # Normalise: string → dict with url key
    normalised: list[dict] = []
    for entry in courses:
        if isinstance(entry, str):
            normalised.append({"url": entry})
        elif isinstance(entry, dict):
            normalised.append(entry)
    return normalised


def write_batch(path: Path, courses: list[dict]) -> None:
    """Write course entries (with status) back to the YAML file."""
    # Build a clean top-level document
    doc: dict[str, Any] = {
        # A short comment is hard to preserve via pyyaml, so we rely on
        # the file already existing.  The auto-generated comment above
        # will be lost on rewrite — that's acceptable.
        "courses": courses,
    }
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False))


# ---------------------------------------------------------------------------
# Download logic
# ---------------------------------------------------------------------------


async def _download_course(
    ctx,
    section_url: str,
    state_path: Path,
    output_dir: Path,
    output_root: Path,
) -> dict:
    """Download all lectures for one course URL, reusing an existing context.

    Returns a result dict with keys:
        ``status``, ``course_name``, ``lectures``, ``summary``, (``error``)
    """
    from echo360_downloader.download import download_stream
    from echo360_downloader.scraper import get_course_name, get_lecture_list
    from echo360_downloader.streams import resolve_streams
    from echo360_downloader.auth import ensure_session

    result: dict = {
        "url": section_url,
        "status": "running",
        "lectures": [],
        "summary": {},
    }

    page = await ctx.new_page()

    try:
        # Navigate and ensure we're logged in
        await ensure_session(state_path, page, section_url)

        course_name = await get_course_name(page)
        course_dir_name = sanitize_folder_name(course_name)
        course_root = output_root / course_dir_name
        course_root.mkdir(parents=True, exist_ok=True)

        result["course_name"] = course_name

        lectures = await get_lecture_list(page)
        if not lectures:
            result["status"] = "completed"  # empty course
            result["summary"] = {
                "total": 0,
                "successful": 0,
                "failed": 0,
                "downloaded_at": datetime.datetime.now().isoformat(timespec="seconds"),
            }
            await page.close()
            return result

        # Build lecture dirs and download
        total = len(lectures)
        successful = 0
        failed = 0
        lecture_results: list[dict] = []

        for idx, lec in enumerate(lectures, 1):
            title = lec.get("ariaLabel") or lec.get("text", f"Lecture {idx}")
            lesson_id = lec["lessonId"]

            # Build the same lecture_dir as single-course download
            date_iso = lec.get("date", "")
            start_time = lec.get("startTime", "")
            date_prefix = f"{date_iso}_{start_time}" if start_time else date_iso
            folder_name = sanitize_folder_name(f"{date_prefix} - {title}".strip(" -"))
            lecture_dir = course_root / folder_name

            console.print(f"\n[bold][{idx}/{total}] {title}[/]")

            # Open a new page for this lecture, attach M3U8 listener
            lec_page = await ctx.new_page()
            all_m3u8: set[str] = set()

            def _capture(req):
                url = req.url
                if ".m3u8" in url and "content.echo360" in url:
                    all_m3u8.add(url)

            lec_page.on("request", _capture)

            try:
                await lec_page.goto(
                    section_url, wait_until="domcontentloaded", timeout=30_000
                )
                await lec_page.wait_for_timeout(2_000)

                # Click the lecture row
                clicked = await lec_page.evaluate(
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
                    warning(f"Row not found: {title}")
                    failed += 1
                    lecture_results.append(
                        {"title": title, "outcome": "failed", "error": "row not found"}
                    )
                    continue

                rows = await lec_page.query_selector_all(
                    f'[data-test-lessonid="{lesson_id}"]'
                )
                if not rows:
                    warning(f"Selector not found: {title}")
                    failed += 1
                    continue

                await rows[0].click()
                await lec_page.wait_for_timeout(12_000)
                await lec_page.wait_for_timeout(10_000)

                streams = resolve_streams(all_m3u8)
                if not streams:
                    warning(f"No streams for: {title}")
                    failed += 1
                    lecture_results.append(
                        {"title": title, "outcome": "failed", "error": "no streams"}
                    )
                    continue

                info(f"Streams: {', '.join(streams.keys())}")
                lecture_dir.mkdir(parents=True, exist_ok=True)
                cookies = await ctx.cookies()
                audio_url = streams.get("audio")

                safe_title = sanitize_folder_name(title)
                stream_results: dict[str, str] = {}
                lecture_ok = True

                for stream_type, stream_url in streams.items():
                    output = lecture_dir / f"{safe_title} - {stream_type}.mp4"
                    if len(str(output)) > 240:
                        output = lecture_dir / f"{stream_type}.mp4"

                    if stream_type in ("combined", "camera") and audio_url:
                        ok = await download_stream(
                            stream_url, output, cookies, audio_url=audio_url
                        )
                    else:
                        ok = await download_stream(stream_url, output, cookies)

                    stream_results[stream_type] = "success" if ok else "failed"
                    if not ok:
                        lecture_ok = False

                lec_entry = {
                    "title": title,
                    "outcome": "success" if lecture_ok else "partial",
                    "streams": stream_results,
                }
                if date_iso:
                    lec_entry["date"] = date_iso
                if start_time:
                    lec_entry["start_time"] = start_time
                lecture_results.append(lec_entry)

                if lecture_ok:
                    successful += 1
                else:
                    failed += 1

            except Exception as exc:
                error(f"Download error: {exc}")
                failed += 1
                lecture_results.append(
                    {"title": title, "outcome": "failed", "error": str(exc)}
                )
            finally:
                await lec_page.close()

        result["lectures"] = lecture_results
        result["status"] = "completed" if failed == 0 else "partial"
        result["summary"] = {
            "total": total,
            "successful": successful,
            "failed": failed,
            "downloaded_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }

    except Exception as exc:
        result["status"] = "failed"
        result["error"] = str(exc)
    finally:
        await page.close()

    return result


async def run_batch(
    batch_path: Path,
    state_path: Path,
    output_dir: Path,
    headed: bool,
) -> None:
    """Read the batch YAML, download all courses, write status back."""
    courses = read_batch(batch_path)
    if not courses:
        return

    heading("Batch download")
    info(f"File: [underline]{batch_path}[/]")
    info(f"Courses: {len(courses)}")
    divider()

    from echo360_downloader.utils import check_ffmpeg

    check_ffmpeg()

    from playwright.async_api import async_playwright
    from echo360_downloader.auth import do_login

    # Ensure we have a session first
    if not state_path.exists():
        heading("Login required")
        info("No saved session found — starting login.")
        await do_login(state_path)

    output_root = output_dir.resolve()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not headed)
        ctx = await browser.new_context(
            storage_state=str(state_path),
            viewport={"width": 1280, "height": 900},
        )

        updated_courses: list[dict] = []
        for i, course in enumerate(courses, 1):
            url = course.get("url", "")
            if not url:
                continue

            # Skip already-completed courses unless they have no summary
            existing_status = course.get("status", "")
            if existing_status in ("completed", "partial") and "summary" in course:
                info(
                    f"[{i}/{len(courses)}] Skipping [underline]{url}[/] (already done)"
                )
                updated_courses.append(course)
                continue

            subheading(f"[{i}/{len(courses)}] {url}")
            result = await _download_course(
                ctx, url, state_path, output_dir, output_root
            )
            updated_courses.append(result)

            # Print per-course summary
            summary = result.get("summary", {})
            if result["status"] == "failed":
                error(f"Courses failed: {result.get('error', 'unknown error')}")
            elif summary:
                s, f = summary.get("successful", 0), summary.get("failed", 0)
                if f == 0:
                    success(f"{s}/{s} lectures downloaded")
                else:
                    warning(f"{s}/{s + f} lectures downloaded ({f} failed)")
            divider()

        await browser.close()

    # Write results back to the YAML
    write_batch(batch_path, updated_courses)
    success(f"Batch status written to [underline]{batch_path}[/]")
