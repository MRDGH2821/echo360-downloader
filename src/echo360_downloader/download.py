"""ffmpeg-based downloading of HLS streams."""

import asyncio
from pathlib import Path

from echo360_downloader.utils import build_cookie_string


def _ffmpeg_headers(cookie_str: str) -> str:
    """Build the ``-headers`` string passed to ffmpeg."""
    return (
        f"Cookie: {cookie_str}\r\n"
        f"Referer: https://echo360.net.au/\r\n"
        f"Origin: https://echo360.net.au\r\n"
    )


async def download_stream(
    stream_url: str,
    output_path: Path,
    cookies: list[dict],
    audio_url: str | None = None,
) -> bool:
    """Download an HLS stream with ffmpeg.

    When *audio_url* is provided (e.g. for the camera stream which is
    video-only) it is passed as a second input and the audio track is
    mapped into the output, producing a file with both video and audio.
    """
    cookie_str = build_cookie_string(cookies)
    headers = _ffmpeg_headers(cookie_str)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if audio_url:
        cmd = [
            "ffmpeg", "-y",
            "-headers", headers,
            "-i", stream_url,
            "-headers", headers,
            "-i", audio_url,
            "-c", "copy",
            "-map", "0:v",
            "-map", "1:a",
            "-shortest",
            "-movflags", "+faststart",
            str(output_path),
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-headers", headers,
            "-i", stream_url,
            "-c", "copy",
            "-bsf:a", "aac_adtstoasc",
            "-movflags", "+faststart",
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
        print(f"    TIMEOUT after 3600s")
        process.kill()
        return False

    if process.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
        size_mb = output_path.stat().st_size / 1024 / 1024
        print(f"    Downloaded: {output_path.name} ({size_mb:.1f} MB)")
        return True

    err = (stderr or b"").decode()[-300:]
    print(f"    FAILED (exit {process.returncode}): {err}")
    return False
