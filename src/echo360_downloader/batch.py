"""Batch download from a YAML course list — reads URLs, downloads, writes status."""

from __future__ import annotations

import asyncio
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
# Number of concurrent downloads (default: 1 for sequential)
parallel: 1
# Add course section URLs under `courses`.
# Run: echo360-dl batch <this-file>
#
# Results are written to <this-file-stem>_status.yaml after download.
courses:
  # - url: https://echo360.net.au/section/<your-section-uuid>
"""


def _default_course_entry(url: str) -> dict:
    """Return a minimal course dict for a new URL."""
    return {"url": url}


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------


def read_batch(path: Path) -> tuple[int, list[dict]]:
    """Load a batch YAML file and return (*parallel*, *course_entries*).

    *parallel* is the number of concurrent stream downloads (default 1).
    Course entries are normalised to dict form with a ``url`` key.

    If the file doesn't exist a template is written and the user is told
    to edit it — returns ``(1, [])``.
    """
    if not path.exists():
        heading("New batch file")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_INITIAL_BATCH)
        info(f"Created template at [underline]{path}[/]")
        warning("Add course URLs to the file, then re-run this command.")
        return 1, []

    raw = yaml.safe_load(path.read_text())
    if not raw or "courses" not in raw:
        warning("No 'courses' list found in the batch file.")
        return 1, []

    parallel = raw.get("parallel", 1)
    if not isinstance(parallel, int) or parallel < 1:
        parallel = 1

    courses = raw["courses"]
    if not isinstance(courses, list):
        warning("'courses' must be a list.")
        return 1, []

    # Normalise: string → dict with url key
    normalised: list[dict] = []
    for entry in courses:
        if isinstance(entry, str):
            normalised.append({"url": entry})
        elif isinstance(entry, dict):
            normalised.append(entry)

    return parallel, normalised


def write_batch(path: Path, courses: list[dict], parallel: int = 1) -> None:
    """Write course entries (with status) back to the YAML file.

    *parallel* is preserved so the setting survives round-trips.

    .. note::
       ``run_batch`` now writes results to a separate ``_status.yaml``
       file instead of overwriting the config.  This function is kept
       for backward compatibility / manual use.
    """
    doc: dict[str, Any] = {
        "parallel": parallel,
        "courses": courses,
    }
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False))


# ---------------------------------------------------------------------------
# Status file I/O (separate from the config YAML)
# ---------------------------------------------------------------------------


def _status_path(batch_path: Path) -> Path:
    """Derive the status file path from the batch config path.

    e.g., ``courses.yaml`` → ``courses_status.yaml``
    """
    return batch_path.with_stem(batch_path.stem + "_status")


def read_status(path: Path) -> dict[str, dict]:
    """Read existing status file, return *url → entry* mapping.

    Returns an empty dict when the file doesn't exist or can't be parsed.
    """
    if not path.exists():
        return {}
    try:
        raw = yaml.safe_load(path.read_text())
    except Exception:
        return {}
    if not raw or "courses" not in raw:
        return {}
    courses = raw["courses"]
    if not isinstance(courses, list):
        return {}
    return {c["url"]: c for c in courses if isinstance(c, dict) and c.get("url")}


def write_status(path: Path, courses: list[dict], parallel: int) -> None:
    """Write course results to the status file."""
    doc: dict[str, Any] = {
        "parallel": parallel,
        "courses": courses,
    }
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False))


# ---------------------------------------------------------------------------
# Capture phase (serial – requires Playwright)
# ---------------------------------------------------------------------------


async def _capture_lecture(
    ctx,
    section_url: str,
    lecture: dict,
    idx: int,
    course_root: Path,
) -> dict | None:
    """Open a lecture row, capture M3U8 URLs, return metadata dict.

    Returns ``None`` on any failure (row not found, no streams, timeout)
    so the caller can track it as a failed lecture.
    """
    from echo360_downloader.capture import capture_lecture_streams

    title = lecture.get("ariaLabel") or lecture.get("text", f"Lecture {idx}")
    lesson_id = lecture["lessonId"]

    captured = await capture_lecture_streams(ctx, section_url, lesson_id, title)
    if not captured:
        return None

    streams = captured["streams"]
    cookies = captured["cookies"]
    date_iso = lecture.get("date", "")
    start_time = lecture.get("startTime", "")

    # batch caller already has course_root = output_root / course_dir_name,
    # so build lecture_dir directly inside it.
    from echo360_downloader.utils import sanitize_folder_name

    date_prefix = f"{date_iso}_{start_time}" if start_time else date_iso
    folder_name = sanitize_folder_name(f"{date_prefix} - {title}".strip(" -"))
    lecture_dir = course_root / folder_name

    info(f"Captured: {title} ({', '.join(streams.keys())})")

    return {
        "title": title,
        "lesson_id": lesson_id,
        "date_iso": date_iso,
        "start_time": start_time,
        "streams": streams,
        "cookies": cookies,
        "lecture_dir": lecture_dir,
    }


# ---------------------------------------------------------------------------
# Download phase (parallel – no Playwright, just ffmpeg)
# ---------------------------------------------------------------------------


async def _download_lecture_streams(
    lec_info: dict,
    sem: asyncio.Semaphore,
) -> dict:
    """Download all streams for one captured lecture under a semaphore.

    The semaphore is acquired *per stream* rather than per lecture, so
    ``parallel`` directly controls the maximum number of concurrent ffmpeg
    processes regardless of how many lectures are in the queue.  Within a
    lecture the three streams (combined, camera, audio) compete for
    semaphore slots alongside streams from other lectures.
    """
    from echo360_downloader.download import download_stream

    title = lec_info["title"]
    streams = lec_info["streams"]
    cookies = lec_info["cookies"]
    lecture_dir = lec_info["lecture_dir"]
    audio_url = streams.get("audio")

    lecture_dir.mkdir(parents=True, exist_ok=True)

    stream_results: dict[str, str] = {}
    lecture_ok = True

    async def _dl(stream_type: str, stream_url: str) -> None:
        nonlocal lecture_ok
        # Semaphore acquired per stream — parallel controls total concurrent
        # ffmpeg processes, not whole-lecture slots.
        async with sem:
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

    tasks = [_dl(st, su) for st, su in streams.items()]
    await asyncio.gather(*tasks)

    entry: dict[str, Any] = {
        "title": title,
        "outcome": "success" if lecture_ok else "partial",
        "streams": stream_results,
    }
    date_iso = lec_info.get("date_iso", "")
    start_time = lec_info.get("start_time", "")
    if date_iso:
        entry["date"] = date_iso
    if start_time:
        entry["start_time"] = start_time

    return entry


# ---------------------------------------------------------------------------
# Course download (two-phase: capture serially → download in parallel)
# ---------------------------------------------------------------------------


async def _download_course(
    ctx,
    section_url: str,
    state_path: Path,
    output_dir: Path,
    output_root: Path,
    parallel: int = 1,
) -> dict:
    """Download all lectures for one course URL.

    Two-phase approach to allow safe parallelism:

    **Phase 1** (serial, with Playwright)
        Capture M3U8 URLs for every lecture by clicking each row and
        listening to network requests.  Only one Echo360 video can play
        at a time, so this must be sequential.

    **Phase 2** (parallel, via ffmpeg)
        Download all captured streams concurrently.  The *parallel*
        parameter controls how many ffmpeg subprocesses run at once.
        Browser interaction is no longer needed — every ffmpeg call is
        an independent subprocess.
    """
    from echo360_downloader.scraper import get_course_name, get_lecture_list
    from echo360_downloader.auth import ensure_session

    result: dict = {
        "url": section_url,
        "status": "running",
        "lectures": [],
        "summary": {},
    }

    page = await ctx.new_page()

    try:
        await ensure_session(state_path, page, section_url)

        course_name = await get_course_name(page)
        course_dir_name = sanitize_folder_name(course_name)
        course_root = output_root / course_dir_name
        course_root.mkdir(parents=True, exist_ok=True)

        result["course_name"] = course_name

        lectures = await get_lecture_list(page)
        if not lectures:
            result["status"] = "completed"
            result["summary"] = {
                "total": 0,
                "successful": 0,
                "failed": 0,
                "downloaded_at": datetime.datetime.now().isoformat(timespec="seconds"),
            }
            await page.close()
            return result

        await page.close()

        total = len(lectures)
        console.print(f"\n[bold]Capturing {total} lectures…[/]")

        # ── Phase 1: capture M3U8 URLs (serial, needs browser) ─────
        captured: list[dict] = []
        capture_failed = 0

        for idx, lec in enumerate(lectures, 1):
            title = lec.get("ariaLabel") or lec.get("text", f"Lecture {idx}")
            console.print(f"\n[bold][{idx}/{total}] {title}[/]")
            lec_info = await _capture_lecture(ctx, section_url, lec, idx, course_root)
            if lec_info is not None:
                captured.append(lec_info)
            else:
                capture_failed += 1

        if not captured:
            result["status"] = "completed"
            result["summary"] = {
                "total": total,
                "successful": 0,
                "failed": total,
                "downloaded_at": datetime.datetime.now().isoformat(timespec="seconds"),
            }
            return result

        # ── Phase 2: download all captured streams (parallel via ffmpeg) ──
        console.print(
            f"\n[bold]Downloading {len(captured)} lectures (parallel={parallel})…[/]"
        )
        sem = asyncio.Semaphore(parallel)

        download_tasks = [_download_lecture_streams(ci, sem) for ci in captured]
        completed = await asyncio.gather(*download_tasks)

        # Aggregate results
        successful = 0
        dl_failed = 0
        lecture_results: list[dict] = []

        for entry in completed:
            lecture_results.append(entry)
            if entry["outcome"] == "success":
                successful += 1
            else:
                dl_failed += 1

        total_failed = capture_failed + dl_failed

        result["lectures"] = lecture_results
        result["status"] = "completed" if total_failed == 0 else "partial"
        result["summary"] = {
            "total": total,
            "successful": successful,
            "failed": total_failed,
            "downloaded_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }

    except Exception as exc:
        result["status"] = "failed"
        result["error"] = str(exc)
    finally:
        if not page.is_closed():
            await page.close()

    return result


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------


async def run_batch(
    batch_path: Path,
    state_path: Path,
    output_dir: Path,
    headed: bool,
) -> None:
    """Read the batch config YAML, download all courses, write status to ``_status.yaml``."""
    parallel, courses = read_batch(batch_path)
    if not courses:
        return

    status_path = _status_path(batch_path)

    heading("Batch download")
    info(f"Config: [underline]{batch_path}[/]")
    info(f"Status: [underline]{status_path}[/]")
    info(f"Courses: {len(courses)}, parallel downloads: {parallel}")
    divider()

    from echo360_downloader.utils import check_ffmpeg

    check_ffmpeg()

    from echo360_downloader.auth import do_login
    from echo360_downloader.session import create_browser_context

    if not state_path.exists():
        heading("Login required")
        info("No saved session found — starting login.")
        await do_login(state_path)

    # Load existing status to skip already-completed courses
    existing_by_url = read_status(status_path)

    output_root = output_dir.resolve()

    async with create_browser_context(state_path, headed) as (_browser, ctx):
        # Build results in config order, reusing existing status when possible
        updated_courses: list[dict] = []
        for i, course in enumerate(courses, 1):
            url = course.get("url", "")
            if not url:
                continue

            # Skip if already completed in status file
            if url in existing_by_url:
                prev = existing_by_url[url]
                if prev.get("status") in ("completed", "partial") and "summary" in prev:
                    info(
                        f"[{i}/{len(courses)}] Skipping [underline]{url}[/] "
                        f"(already done — see {status_path.name})"
                    )
                    updated_courses.append(prev)
                    continue

            subheading(f"[{i}/{len(courses)}] {url}")
            result = await _download_course(
                ctx,
                url,
                state_path,
                output_dir,
                output_root,
                parallel=parallel,
            )
            updated_courses.append(result)

            # Per-course summary
            summary = result.get("summary", {})
            if result["status"] == "failed":
                error(f"Course failed: {result.get('error', 'unknown error')}")
            elif summary:
                s, f = summary.get("successful", 0), summary.get("failed", 0)
                if f == 0:
                    success(f"{s}/{s} lectures downloaded")
                else:
                    warning(f"{s}/{s + f} lectures downloaded ({f} failed)")
            divider()

    write_status(status_path, updated_courses, parallel=parallel)
    success(f"Batch status written to [underline]{status_path}[/]")
