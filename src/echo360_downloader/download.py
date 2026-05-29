"""ffmpeg-based downloading of HLS streams with best-quality variant selection."""

import asyncio
import re
from pathlib import Path
from urllib.parse import urljoin

from echo360_downloader.utils import build_cookie_string


async def _best_variant_url(stream_url: str, cookie_str: str) -> str:
    """Download an HLS master playlist and return the highest-resolution variant.

    Parses the ``#EXT-X-STREAM-INF`` entries for ``RESOLUTION`` and picks the
    variant with the greatest height (px).  Returns the original *stream_url*
    unchanged if the URL isn't a master playlist or can't be parsed.
    """
    cmd = [
        "curl",
        "-s",
        "--max-time",
        "10",
        "--http1.1",
        "-H",
        f"Cookie: {cookie_str}",
        "-H",
        "Referer: https://echo360.net.au/",
        "-H",
        "Origin: https://echo360.net.au",
        "-H",
        "User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        stream_url,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
    except asyncio.TimeoutError:
        proc.kill()
        return stream_url

    if proc.returncode != 0:
        return stream_url

    content = stdout.decode()
    if not content.startswith("#EXTM3U") or "#EXT-X-STREAM-INF:" not in content:
        return stream_url  # single-variant playlist or not a master

    best_url = stream_url
    best_height = 0
    lines = content.splitlines()

    for i, line in enumerate(lines):
        if not line.startswith("#EXT-X-STREAM-INF:"):
            continue

        # Extract resolution
        m = re.search(r"RESOLUTION=(\d+)x(\d+)", line)
        if not m:
            continue
        height = int(m.group(2))

        # Find the variant URL on the next non-comment line
        j = i + 1
        while j < len(lines) and lines[j].startswith("#"):
            j += 1
        if j >= len(lines):
            break

        variant_url = lines[j].strip()
        if height > best_height:
            best_height = height
            if variant_url.startswith("http"):
                best_url = variant_url
            else:
                best_url = urljoin(stream_url, variant_url)

    if best_url != stream_url:
        print(f"    Selected {best_height}p variant from master playlist")
    return best_url


def _ffmpeg_headers(cookie_str: str) -> str:
    """Build the ``-headers`` string passed to ffmpeg."""
    crlf = "\r\n"
    return (
        f"Cookie: {cookie_str}{crlf}"
        f"Referer: https://echo360.net.au/{crlf}"
        f"Origin: https://echo360.net.au{crlf}"
    )


async def download_stream(
    stream_url: str,
    output_path: Path,
    cookies: list[dict],
    audio_url: str | None = None,
) -> bool:
    """Download an HLS stream with ffmpeg, preferring the highest-resolution variant.

    When *audio_url* is provided (e.g. for the camera stream which is
    video-only) it is passed as a second input and the audio track is
    mapped into the output, producing a file with both video and audio.
    """
    cookie_str = build_cookie_string(cookies)
    headers = _ffmpeg_headers(cookie_str)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Resolve best quality variant from master playlist for video streams
    resolved_url = await _best_variant_url(stream_url, cookie_str)

    if audio_url:
        cmd = [
            "ffmpeg",
            "-y",
            "-headers",
            headers,
            "-i",
            resolved_url,
            "-headers",
            headers,
            "-i",
            audio_url,
            "-c",
            "copy",
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-shortest",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    else:
        cmd = [
            "ffmpeg",
            "-y",
            "-headers",
            headers,
            "-i",
            resolved_url,
            "-c",
            "copy",
            "-bsf:a",
            "aac_adtstoasc",
            "-movflags",
            "+faststart",
            str(output_path),
        ]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=3600)
    except asyncio.TimeoutError:
        print("    TIMEOUT after 3600s")
        process.kill()
        return False

    if (
        process.returncode == 0
        and output_path.exists()
        and output_path.stat().st_size > 0
    ):
        size_mb = output_path.stat().st_size / 1024 / 1024
        print(f"    Downloaded: {output_path.name} ({size_mb:.1f} MB)")
        return True

    err = (stderr or b"").decode()[-300:]
    print(f"    FAILED (exit {process.returncode}): {err}")
    return False
