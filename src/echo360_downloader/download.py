"""ffmpeg-based downloading of HLS streams with best-quality variant selection."""

from __future__ import annotations

import asyncio
import re
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from echo360_downloader.ui import dim, error, success
from echo360_downloader.utils import build_cookie_string


# ---------------------------------------------------------------------------
# M3U8 helpers
# ---------------------------------------------------------------------------


async def _fetch_m3u8(url: str, cookie_str: str = "") -> str:
    """Fetch an M3U8 playlist content via curl."""
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
        url,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
    except asyncio.TimeoutError:
        proc.kill()
        return ""
    if proc.returncode != 0:
        return ""
    return stdout.decode(errors="replace")


def _abs_url(ref: str, base_abs: str, query: str) -> str:
    """Turn a relative reference into an absolute URL with query string."""
    if ref.startswith("http"):
        return ref
    return f"{base_abs}{ref}{query}"


def _rewrite_m3u8_segments(m3u8_content: str, playlist_url: str) -> str:
    """Rewrite relative segment/playlist URLs in M3U8 content to absolute URLs.

    CloudFront-signed HLS streams use relative URLs for segments (e.g.,
    ``s1q1.m4s``) and sub-playlists.  When ffmpeg resolves these, it strips
    the CloudFront signature, causing 403 errors.  This function rewrites
    all relative URLs to absolute ones with the signature preserved.
    """
    parsed = urlparse(playlist_url)
    base_path = parsed.path.rsplit("/", 1)[0] + "/"
    query = f"?{parsed.query}" if parsed.query else ""
    base_abs = f"{parsed.scheme}://{parsed.netloc}{base_path}"

    lines = m3u8_content.splitlines()
    rewritten = []
    for line in lines:
        # Rewrite URI="..." attributes (in #EXT-X-MAP, #EXT-X-MEDIA, etc.)
        line = re.sub(
            r'(URI=")([^"]+)(")',
            lambda m: m.group(1) + _abs_url(m.group(2), base_abs, query) + m.group(3),
            line,
        )
        # Rewrite bare segment/playlist filenames (lines that aren't comments
        # or tags and look like relative URLs)
        stripped = line.strip()
        if (
            stripped
            and not stripped.startswith("#")
            and not stripped.startswith("http")
            and ("." in stripped or "@" in stripped)
        ):
            line = _abs_url(stripped, base_abs, query)
        rewritten.append(line)
    return "\n".join(rewritten)


# ---------------------------------------------------------------------------
# Master playlist rewriting — makes ALL URLs local-file-safe for ffmpeg
# ---------------------------------------------------------------------------


def _extract_sub_playlist_refs(master_content: str) -> list[str]:
    """Extract relative sub-playlist references from a master M3U8.

    Returns the raw reference strings (e.g., ``s1q1.m3u8`` or ``s0q1.m3u8``)
    from both ``#EXT-X-STREAM-INF`` entries and ``#EXT-X-MEDIA`` URI
    attributes.
    """
    refs: list[str] = []
    for line in master_content.splitlines():
        # #EXT-X-STREAM-INF:... followed by a bare filename on the next line
        # (handled by caller looking at pairs)
        # #EXT-X-MEDIA:...URI="filename"...
        uri_match = re.search(r'URI="([^"]+)"', line)
        if uri_match:
            refs.append(uri_match.group(1))
    # Also scan for bare filenames after EXT-X-STREAM-INF
    lines = master_content.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("#EXT-X-STREAM-INF:") and i + 1 < len(lines):
            ref = lines[i + 1].strip()
            if ref and not ref.startswith("#") and not ref.startswith("http"):
                refs.append(ref)
    return refs


async def _rewrite_hls_for_ffmpeg(
    stream_url: str,
    cookie_str: str,
    tmpdir: str,
) -> str | None:
    """Rewrite an HLS master playlist so ALL sub-playlists use local temp files.

    Fetches the master, then for each sub-playlist reference (variant + audio),
    fetches and rewrites segment URLs to absolute (signed).  Writes each
    sub-playlist to a temp file and rewrites the master to reference the local
    files.  Returns the path to the rewritten master file, or ``None`` on
    failure.

    For non-master (single-variant) playlists, rewrites segments to absolute
    and returns a temp file path.
    """
    content = await _fetch_m3u8(stream_url, cookie_str)
    if not content or "#EXT" not in content:
        return None

    # Single-variant playlist (no sub-playlists) — just rewrite segments
    if "#EXT-X-STREAM-INF:" not in content and "#EXT-X-MEDIA:" not in content:
        rewritten = _rewrite_m3u8_segments(content, stream_url)
        master_path = Path(tmpdir) / "playlist.m3u8"
        master_path.write_text(rewritten)
        return str(master_path)

    # Master playlist — rewrite all referenced sub-playlists
    parsed = urlparse(stream_url)
    base_path = parsed.path.rsplit("/", 1)[0] + "/"
    query = f"?{parsed.query}" if parsed.query else ""
    base_abs = f"{parsed.scheme}://{parsed.netloc}{base_path}"

    refs = _extract_sub_playlist_refs(content)
    unique_refs = list(dict.fromkeys(refs))  # dedupe preserving order

    # Map original ref → local temp file path
    local_map: dict[str, str] = {}
    for ref in unique_refs:
        sub_url = _abs_url(ref, base_abs, query)
        sub_content = await _fetch_m3u8(sub_url, cookie_str)
        if sub_content and "#EXT" in sub_content:
            sub_rewritten = _rewrite_m3u8_segments(sub_content, sub_url)
            safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", ref)
            sub_path = Path(tmpdir) / safe_name
            sub_path.write_text(sub_rewritten)
            local_map[ref] = str(sub_path)

    # Rewrite the master: replace all refs with local paths
    rewritten_lines = []
    for line in content.splitlines():
        # URI="..." in #EXT-X-MEDIA etc.
        new_line = re.sub(
            r'(URI=")([^"]+)(")',
            lambda m: m.group(1) + local_map.get(m.group(2), m.group(2)) + m.group(3),
            line,
        )
        # Bare filenames (variant refs after #EXT-X-STREAM-INF)
        stripped = new_line.strip()
        if stripped in local_map and not new_line.strip().startswith("#"):
            new_line = local_map[stripped]
        rewritten_lines.append(new_line)

    master_path = Path(tmpdir) / "master.m3u8"
    master_path.write_text("\n".join(rewritten_lines))
    return str(master_path)


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


async def download_stream(
    stream_url: str,
    output_path: Path,
    cookies: list[dict],
    audio_url: str | None = None,
) -> bool:
    """Download an HLS stream using ffmpeg.

    The flow:
      1. For combined/master playlists, rewrite ALL sub-playlists to local
         temp files with absolute signed segment URLs.
      2. For single-variant playlists, rewrite segments to absolute URLs.
      3. Write everything to temp files.
      4. Pass the local master/playlist file to ffmpeg.
    """
    cookie_str = build_cookie_string(cookies)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        # Check if stream_url is a master playlist (has _av or EXT-X-STREAM-INF)
        probe = await _fetch_m3u8(stream_url, cookie_str)
        is_master = probe and (
            "#EXT-X-STREAM-INF:" in probe or "#EXT-X-MEDIA:" in probe
        )

        if is_master:
            # Master playlist: rewrite everything to local files
            dim("Rewriting HLS master playlist for ffmpeg…")
            local_master = await _rewrite_hls_for_ffmpeg(stream_url, cookie_str, tmpdir)
            if not local_master:
                error("Failed to rewrite master playlist")
                return False
            video_input = local_master
        else:
            # Single-variant: rewrite segments to absolute
            rewritten = _rewrite_m3u8_segments(probe or "", stream_url)
            video_file = Path(tmpdir) / "video.m3u8"
            video_file.write_text(rewritten)
            video_input = str(video_file)

        # If explicit separate audio URL, also rewrite that
        audio_input = None
        if audio_url:
            audio_content = await _fetch_m3u8(audio_url, cookie_str)
            if audio_content and "#EXT" in audio_content:
                audio_rewritten = _rewrite_m3u8_segments(audio_content, audio_url)
                audio_file = Path(tmpdir) / "audio.m3u8"
                audio_file.write_text(audio_rewritten)
                audio_input = str(audio_file)

        # Build ffmpeg command
        # -protocol_whitelist must be format-level (before any -i)
        cmd = [
            "ffmpeg",
            "-y",
            "-protocol_whitelist",
            "file,http,https,tcp,tls,crypto",
            "-i",
            video_input,
        ]

        if audio_input:
            cmd += ["-i", audio_input]

        cmd += [
            "-c:v",
            "copy",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            str(output_path),
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)
        except asyncio.TimeoutError:
            proc.kill()
            error(f"Timeout downloading {output_path.name}")
            return False

        if proc.returncode != 0:
            stderr_text = stderr.decode(errors="replace")
            err_lines = [
                ln.strip()
                for ln in stderr_text.splitlines()
                if "error" in ln.lower() or "403" in ln or "forbidden" in ln.lower()
            ]
            error_msg = "; ".join(err_lines[:3]) if err_lines else "unknown error"
            error(f"Download failed: {error_msg}")
            return False

    success(f"Saved: {output_path.name}")
    return True
