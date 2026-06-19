"""Console entry point — dispatches to login / list / download."""

from __future__ import annotations

import asyncio
from pathlib import Path

from echo360_downloader.auth import do_login
from echo360_downloader.capture import capture_lecture_streams, capture_media_streams
from echo360_downloader.cli import parse_args
from echo360_downloader.download import download_stream
from echo360_downloader.scraper import get_course_name, get_lecture_list
from echo360_downloader.selection import (
    prompt_lecture_selection,
    resolve_target,
)
from echo360_downloader.session import create_session
from echo360_downloader.ui import (
    console,
    divider,
    heading,
    info,
    lecture_list_table,
    success,
    warning,
)
from echo360_downloader.utils import (
    is_media_url,
    lecture_course_dir,
    sanitize_folder_name,
)


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


async def _cmd_list(state_path: Path, section_url: str) -> None:
    async with create_session(state_path, section_url) as (_browser, _ctx, page):
        course_name = await get_course_name(page)
        heading(f"Course: {course_name}")

        lectures = await get_lecture_list(page)
        if not lectures:
            warning("No lectures found.")
            return

        lecture_list_table(lectures, course_name)


# ---------------------------------------------------------------------------
# Download — section (course page with lecture list)
# ---------------------------------------------------------------------------


async def _download_lecture(
    section_url: str,
    ctx,
    lesson_id: str,
    lecture_title: str,
    lecture_dir: Path,
    idx: int | None = None,
) -> dict[str, bool]:
    """Download all available streams for a single lecture."""
    prefix = f"[{idx}] " if idx else ""
    console.print(f"\n{prefix}[bold]{lecture_title}[/]")

    captured = await capture_lecture_streams(ctx, section_url, lesson_id, lecture_title)
    if not captured:
        return {}

    streams = captured["streams"]
    cookies = captured["cookies"]
    streams_result: dict[str, bool] = {}
    audio_url = streams.get("audio")

    lecture_dir.mkdir(parents=True, exist_ok=True)

    for stream_type, stream_url in streams.items():
        output = lecture_dir / f"{stream_type}.mp4"
        # Combined master playlists (_av.m3u8) already contain audio —
        # pass the master URL directly, no separate audio_url needed.
        # Camera streams on section pages may need a separate audio track.
        ok = await download_stream(
            stream_url,
            output,
            cookies,
            audio_url=audio_url if stream_type == "camera" else None,
        )
        streams_result[stream_type] = ok

    return streams_result


async def _cmd_download(
    state_path: Path,
    section_url: str,
    target: str | None,
    output_dir: Path,
    headed: bool,
) -> None:
    async with create_session(state_path, section_url, headed) as (
        _browser,
        _ctx,
        page,
    ):
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
            return

        # Interactive selection when no target was specified on the CLI
        if target is None:
            indices = prompt_lecture_selection(lectures, course_name)
        else:
            indices = resolve_target(target, len(lectures))
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
            lecture_dir = lecture_course_dir(
                output_dir,
                course_dir_name,
                title,
                lec.get("date", ""),
                lec.get("startTime", ""),
            )

            results = await _download_lecture(
                section_url, _ctx, lesson_id, title, lecture_dir, idx + 1
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


# ---------------------------------------------------------------------------
# Download — one-off media URL (direct video page)
# ---------------------------------------------------------------------------


async def _cmd_download_media(
    state_path: Path,
    media_url: str,
    output_dir: Path,
    headed: bool,
    name_override: str | None = None,
) -> None:
    """Download a single video from a direct Echo360 media URL.

    Media URLs (``/media/<uuid>/public``) are public links that require
    no authentication.  The page loads a player that fetches signed M3U8
    stream playlists on init — we intercept those from network requests.
    """
    from echo360_downloader.session import create_browser_context

    async with create_browser_context(state_path, headed) as (_browser, ctx):
        # Capture streams (also loads the page, so we get the title for free)
        console.print("[dim]Loading media page…[/dim]")
        captured = await capture_media_streams(ctx, media_url, name_override or "video")

        if not captured:
            warning("Failed to capture streams.")
            return

        streams = captured["streams"]
        cookies = captured["cookies"]
        title = captured.get("title") or name_override or "video"
        audio_url = streams.get("audio")

        # Derive a sensible folder name from the title
        dir_name = sanitize_folder_name(title)
        out = output_dir / dir_name
        out.mkdir(parents=True, exist_ok=True)

        heading(f"Video: {title}")
        info(f"Output: [underline]{out}/[/]")
        console.print(
            f"[dim]Found {len(streams)} stream(s): {', '.join(streams)}[/dim]"
        )

        total = len(streams)
        ok_count = 0

        for stream_type, stream_url in streams.items():
            output = out / f"{stream_type}.mp4"
            # Combined master playlists already contain audio — pass the
            # master URL directly.  Camera streams may need a separate track.
            ok = await download_stream(
                stream_url,
                output,
                cookies,
                audio_url=audio_url if stream_type == "camera" else None,
            )
            if ok:
                ok_count += 1

        divider()
        if ok_count == total:
            success(f"All {ok_count}/{total} streams downloaded successfully")
        else:
            warning(
                f"{ok_count}/{total} streams downloaded ({total - ok_count} failed)"
            )
        info(f"Output: [underline]{out}/[/]")


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

        if is_media_url(args.url):
            asyncio.run(
                _cmd_download_media(
                    state_path, args.url, args.output_dir, args.headed, args.name
                )
            )
        else:
            asyncio.run(
                _cmd_download(
                    state_path,
                    args.url,
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
    elif args.command == "compress":
        from echo360_downloader.compress import run as compress_run

        compress_run(
            scan_dir=args.dir,
            size_limit_mb=args.size_limit,
            target_size_mb=args.target,
            dry_run=args.dry_run,
        )


if __name__ == "__main__":
    main()
