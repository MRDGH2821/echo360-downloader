"""Compress oversized videos in the downloads/ folder.

Uses ffmpeg 2-pass VBR encoding (libx264) to hit a target file size
(~190 MB, giving headroom under 200 MB). The original video is moved
into an ``original/`` subfolder alongside the compressed version.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from echo360_downloader.ui import (
    console,
    divider,
    error,
    heading,
    info,
    success,
    warning,
)
from echo360_downloader.utils import check_ffmpeg

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
SIZE_LIMIT_MB = 200
TARGET_SIZE_MB = 190  # aim slightly under so we stay < SIZE_LIMIT_MB
AUDIO_BITRATE = "128k"
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".ts"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt_mb(size_bytes: int) -> str:
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def _get_duration_s(filepath: Path) -> float | None:
    """Return video duration (seconds) via ffprobe, or *None* on failure."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                str(filepath),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        return float(result.stdout.strip())
    except (ValueError, subprocess.TimeoutExpired, OSError):
        return None


def find_oversized_videos(
    root: Path,
    size_limit_mb: int,
    extensions: set[str],
) -> list[Path]:
    """Return all video files under *root* whose size exceeds *size_limit_mb*.

    Skips files already inside an ``original/`` subfolder — those are
    preserved backups from a previous run.
    """
    oversized: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in extensions:
            continue
        if "original" in path.parts:
            continue
        size = path.stat().st_size
        if size > size_limit_mb * 1024 * 1024:
            oversized.append(path)
    return oversized


def _run_2pass_encoding(
    input_path: Path,
    output_path: Path,
    target_bitrate: int,  # bits per second
) -> bool:
    """Run 2-pass libx264 VBR encoding.  Returns *True* on success."""
    logfile = str(output_path.with_suffix(".log"))

    pass1_cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-c:v",
        "libx264",
        "-b:v",
        str(target_bitrate),
        "-preset",
        "medium",
        "-pass",
        "1",
        "-passlogfile",
        logfile,
        "-an",
        "-f",
        "null",
        os.devnull,
    ]

    pass2_cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-c:v",
        "libx264",
        "-b:v",
        str(target_bitrate),
        "-preset",
        "medium",
        "-pass",
        "2",
        "-passlogfile",
        logfile,
        "-c:a",
        "aac",
        "-b:a",
        AUDIO_BITRATE,
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    try:
        console.print("    [dim]Pass 1/2 (analysis) …[/dim]")
        r1 = subprocess.run(pass1_cmd, capture_output=True, text=True, timeout=7200)
        if r1.returncode != 0:
            console.print(f"    [red]Pass 1 failed:\n{r1.stderr.strip()[-500:]}[/red]")
            return False

        console.print("    [dim]Pass 2/2 (encoding) …[/dim]")
        r2 = subprocess.run(pass2_cmd, capture_output=True, text=True, timeout=7200)
        if r2.returncode != 0:
            console.print(f"    [red]Pass 2 failed:\n{r2.stderr.strip()[-500:]}[/red]")
            return False

        return True
    except subprocess.TimeoutExpired:
        console.print("    [red]Encoding timed out (2-hour limit reached).[/red]")
        return False
    except OSError as exc:
        console.print(f"    [red]ffmpeg error: {exc}[/red]")
        return False
    finally:
        for suffix in ("-0.log", "-0.log.mbtree"):
            p = Path(logfile + suffix)
            if p.exists():
                p.unlink()


def compress_one(
    filepath: Path,
    size_limit_mb: int,
    target_size_mb: int,
) -> bool:
    """Compress *filepath* so it stays under *size_limit_mb*.

    Returns *True* if the file is now under the limit (either it was already
    small enough, or compression succeeded).
    """
    current_mb = filepath.stat().st_size / (1024 * 1024)
    if current_mb <= size_limit_mb:
        return True

    console.print(
        f"  [bold]{filepath.name}[/]  [dim]({_fmt_mb(filepath.stat().st_size)})[/dim]"
    )

    duration = _get_duration_s(filepath)
    if duration is None or duration <= 0:
        warning("Cannot determine duration — skipping.")
        return False

    # Calculate target total bitrate to hit target_size_mb
    total_bitrate = int((target_size_mb * 1024 * 1024 * 8) / duration)

    audio_bitrate_bps = 128_000
    video_bitrate = total_bitrate - audio_bitrate_bps

    if video_bitrate < 50_000:
        warning(
            f"Video would need {video_bitrate // 1000} kbps "
            f"(below 50 kbps minimum). Skipping."
        )
        return False

    console.print(
        f"    Duration : {duration:.0f}s ({duration / 60:.1f} min)  "
        f"Target bit: {video_bitrate // 1000} kbps video + "
        f"{audio_bitrate_bps // 1000} kbps audio"
    )

    out_dir = filepath.parent
    tmp_path = out_dir / f".{filepath.name}.compress-tmp.mp4"

    original_dir = out_dir / "original"
    original_path = original_dir / filepath.name

    try:
        ok = _run_2pass_encoding(filepath, tmp_path, video_bitrate)
        if not ok or not tmp_path.exists():
            warning("Encoding did not produce output.")
            if tmp_path.exists():
                tmp_path.unlink()
            return False

        compressed_mb = tmp_path.stat().st_size / (1024 * 1024)
        console.print(f"    Compressed : {compressed_mb:.1f} MB")

        if compressed_mb >= size_limit_mb:
            warning(
                f"Output still {compressed_mb:.1f} MB "
                f"(\u2265 {size_limit_mb} MB) — undoing."
            )
            tmp_path.unlink()
            return False

        # Move original into original/ subfolder, install compressed
        original_dir.mkdir(exist_ok=True)
        if original_path.exists():
            original_path.unlink()

        filepath.rename(original_path)
        tmp_path.rename(filepath)

        saved_pct = (1 - compressed_mb / current_mb) * 100
        success(
            f"{filepath.name}: {current_mb:.1f} MB \u2192 {compressed_mb:.1f} MB "
            f"({saved_pct:.0f}% reduction)"
        )
        return True

    except (OSError, subprocess.SubprocessError) as exc:
        error(str(exc))
        if tmp_path.exists():
            tmp_path.unlink()
        return False


def run(
    scan_dir: Path,
    size_limit_mb: int = SIZE_LIMIT_MB,
    target_size_mb: int = TARGET_SIZE_MB,
    dry_run: bool = False,
) -> None:
    """Scan *scan_dir* and compress oversized videos."""
    if target_size_mb >= size_limit_mb:
        error(
            f"Target size ({target_size_mb} MB) must be less than "
            f"size limit ({size_limit_mb} MB)."
        )
        sys.exit(1)

    root = scan_dir.resolve()
    if not root.is_dir():
        error(f"{root} is not a directory.")
        sys.exit(1)

    check_ffmpeg()

    oversized = find_oversized_videos(root, size_limit_mb, VIDEO_EXTENSIONS)

    if not oversized:
        info(f"No videos over {size_limit_mb} MB found in {root}.")
        return

    total_before = sum(p.stat().st_size for p in oversized)

    heading("Compressing oversized videos")
    info(
        f"Found {len(oversized)} file(s) over {size_limit_mb} MB ({_fmt_mb(total_before)})"
    )

    if dry_run:
        console.print()
        for p in oversized:
            console.print(f"  {_fmt_mb(p.stat().st_size)}  {p}")
        return

    compressed_ok = 0
    compressed_fail = 0
    console.print()
    for path in oversized:
        ok = compress_one(path, size_limit_mb, target_size_mb)
        if ok:
            compressed_ok += 1
        else:
            compressed_fail += 1

    remaining = find_oversized_videos(root, size_limit_mb, VIDEO_EXTENSIONS)
    total_after = sum(p.stat().st_size for p in remaining)

    divider()
    console.print(f"[green]Compressed : {compressed_ok} files[/green]")
    if compressed_fail:
        console.print(f"[yellow]Skipped    : {compressed_fail} files[/yellow]")
    console.print(f"Saved      : {_fmt_mb(total_before - total_after)}")
    if remaining:
        console.print(
            f"[yellow]Still over : {len(remaining)} file(s) — "
            f"{_fmt_mb(total_after)} total[/yellow]"
        )
    else:
        success(f"All files are now under {size_limit_mb} MB.")
