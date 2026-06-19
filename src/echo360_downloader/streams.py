"""M3U8 stream detection from Echo360 lecture pages."""

from playwright.async_api import Page


async def capture_m3u8_urls(page: Page, existing: set[str] | None = None) -> set[str]:
    """Listen for network requests and collect Echo360 M3U8 URLs.

    Installs a one-shot request listener on *page*, waits a fixed interval
    for the video player to start requesting HLS segments, and returns
    the set of unique M3U8 URLs observed.
    """
    urls = existing or set()

    def _on_request(req):
        url = req.url
        if ".m3u8" in url and "content.echo360" in url:
            urls.add(url)

    page.on("request", _on_request)
    await page.wait_for_timeout(10_000)  # Allow player to initialise
    return urls


# ---------------------------------------------------------------------------
# Stream naming conventions
# ---------------------------------------------------------------------------
#
# Section pages (course view) — streams have independent track IDs:
#   s0  – audio-only (room microphone)
#   s1  – camera / presenter (video-only)
#   s2  – combined PIP (video-only in variants; _av.m3u8 master has audio)
#   _av – master playlist declaring EXT-X-MEDIA audio references
#   _v  – master playlist for video-only streams
#   q0/q1 – quality variants
#
# Media pages (direct /media/<uuid>/public) — streams share track IDs 0/1:
#   s0q0 / s0q1 – camera quality variants (video-only)
#   s1q0 / s1q1 – screen quality variants (video-only)
#   s1_av       – combined audio+video master playlist
#
# The master playlist (s1_av.m3u8 or s2_av.m3u8) declares sub-playlists
# via EXT-X-STREAM-INF and EXT-X-MEDIA audio references.  The audio track
# is always embedded in the _av master — there is no separate audio URL
# for media pages.

# Patterns to try, in priority order, for each canonical stream type.
# First match wins; we try section-page patterns first, then media-page.
#
# NOTE: there is NO separate "audio" stream for media pages — audio is
# embedded in the _av master.  For section pages, audio is s0q0/s0q1.
# When a combined (_av) master exists, audio is handled by ffmpeg
# automatically (no separate audio_url needed).
_PATTERNS: dict[str, list[str]] = {
    "combined": ["s2_av.m3u8", "s1_av.m3u8"],
    "screen": ["s3q1.m3u8", "s3q0.m3u8", "s1q1.m3u8", "s1q0.m3u8"],
    "camera": ["s0q1.m3u8", "s0q0.m3u8"],
}


def _extract_filename(url: str) -> str:
    """Return the M3U8 filename without query string."""
    return url.split("/")[-1].split("?")[0]


def resolve_streams(m3u8_urls: set[str]) -> dict[str, str]:
    """Categorise raw M3U8 URLs into named streams.

    Returns a dict with keys ``combined``, ``camera``, ``audio`` mapped to
    the best-quality playlist URL for each.  ``screen`` is also returned
    when available.

    When a ``combined`` master exists, ``audio`` is omitted — ffmpeg handles
    the embedded audio track automatically.  ``audio`` is only set for
    section pages that have a separate audio-only stream.
    """
    url_map = {_extract_filename(u): u for u in m3u8_urls}

    def find(patterns: list[str]) -> str | None:
        for p in patterns:
            if p in url_map:
                return url_map[p]
        return None

    streams: dict[str, str] = {}
    for key, patterns in _PATTERNS.items():
        url = find(patterns)
        if url:
            streams[key] = url

    # For section pages (no combined master), look for standalone audio
    if "combined" not in streams:
        audio = find(["s0q1.m3u8", "s0q0.m3u8"])
        if audio:
            streams["audio"] = audio

    return streams
