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


# Stream-type indicators in Echo360 HLS URLs:
#   s0  – audio-only (room microphone)
#   s1  – camera / presenter (video-only)
#   s2  – combined PIP (video-only in variants; _av.m3u8 master includes audio)
#   _av – master playlist that declares EXT-X-MEDIA audio references
#   _v  – master playlist for video-only streams
#   q0/q1 – individual quality variants


def resolve_streams(m3u8_urls: set[str]) -> dict[str, str]:
    """Categorise raw M3U8 URLs into named streams.

    Returns a dict with keys ``combined``, ``camera``, ``audio`` mapped to
    the best-quality playlist URL for each.
    """
    sorted_urls = sorted(m3u8_urls)
    streams: dict[str, str] = {}

    # Combined (PIP): prefer master s2_av.m3u8 (which links audio track)
    for url in sorted_urls:
        if "/s2_av." in url:
            streams["combined"] = url
            break
    if "combined" not in streams:
        for url in m3u8_urls:
            if "/s2q1." in url:
                streams["combined"] = url
                break
    if "combined" not in streams:
        for url in m3u8_urls:
            if "/s2q0." in url:
                streams["combined"] = url
                break

    # Camera (presenter): prefer master s1_v.m3u8
    for url in sorted_urls:
        if "/s1_v." in url:
            streams["camera"] = url
            break
    if "camera" not in streams:
        for url in m3u8_urls:
            if "/s1q1." in url:
                streams["camera"] = url
                break
    if "camera" not in streams:
        for url in m3u8_urls:
            if "/s1q0." in url:
                streams["camera"] = url
                break

    # Audio-only: s0q1 > s0q0
    for url in m3u8_urls:
        if "/s0q1." in url:
            streams["audio"] = url
            break
    if "audio" not in streams:
        for url in m3u8_urls:
            if "/s0q0." in url:
                streams["audio"] = url
                break

    return streams
