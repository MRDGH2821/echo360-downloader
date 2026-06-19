"""Lecture stream capture — opens a lecture page, intercepts M3U8 URLs."""

from __future__ import annotations

import json
import re

from playwright.async_api import BrowserContext

from echo360_downloader.streams import resolve_streams
from echo360_downloader.ui import dim, warning


async def capture_lecture_streams(
    ctx: BrowserContext,
    section_url: str,
    lesson_id: str,
    title: str,
) -> dict | None:
    """Open a lecture row, capture M3U8 URLs, return stream metadata.

    Creates a new browser page, attaches a network-request listener for
    M3U8 URLs, navigates to *section_url*, clicks the row matching
    *lesson_id*, and waits for the video player to start streaming.

    Returns a dict with ``streams`` (resolved M3U8 URLs by type) and
    ``cookies`` (for ffmpeg auth), or ``None`` on any failure (row not
    found, no streams, timeout).  The page is always closed.
    """
    page = await ctx.new_page()
    all_m3u8: set[str] = set()

    def _capture(req):
        url = req.url
        if ".m3u8" in url and "content.echo360" in url:
            all_m3u8.add(url)

    page.on("request", _capture)

    try:
        await page.goto(section_url, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(2_000)

        # Click the lecture row
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
            warning(f"Row not found: {title}")
            return None

        rows = await page.query_selector_all(f'[data-test-lessonid="{lesson_id}"]')
        if not rows:
            warning(f"Selector not found: {title}")
            return None

        await rows[0].click()
        # Allow the player to initialise and request stream playlists
        await page.wait_for_timeout(12_000)
        await page.wait_for_timeout(10_000)

        streams = resolve_streams(all_m3u8)
        if not streams:
            warning(f"No streams for: {title}")
            return None

        cookies = await ctx.cookies()
        return {"streams": streams, "cookies": cookies}

    except Exception as exc:
        warning(f"Capture error ({title}): {exc}")
        return None
    finally:
        await page.close()


# ---------------------------------------------------------------------------
# Media page helpers
# ---------------------------------------------------------------------------

_MEDIA_ID_RE = re.compile(r'"mediaId"\s*:\s*"([0-9a-f-]+)"')
_PUBLIC_LINK_RE = re.compile(r'"publicLinkId"\s*:\s*"([0-9a-f-]+)"')


def _extract_player_config(html: str) -> dict[str, str] | None:
    """Pull ``mediaId`` and ``publicLinkId`` from the inline player script."""
    m_id = _MEDIA_ID_RE.search(html)
    pl_id = _PUBLIC_LINK_RE.search(html)
    if m_id:
        return {
            "mediaId": m_id.group(1),
            "publicLinkId": pl_id.group(1) if pl_id else "",
        }
    return None


async def _try_player_properties_api(
    ctx: BrowserContext,
    publicLinkId: str,
    mediaId: str,
) -> set[str] | None:
    """Try the player-properties API to get M3U8 URLs directly.

    Returns a set of M3U8 URLs if successful, ``None`` otherwise.
    """
    page = await ctx.new_page()
    try:
        api_url = (
            f"https://echo360.net.au/api/ui/echoplayer"
            f"/public-links/{publicLinkId}/media/{mediaId}/player-properties"
        )
        resp = await page.goto(api_url, wait_until="load", timeout=15_000)
        if resp and resp.status == 200:
            body = await resp.text()
            data = json.loads(body)
            # The response may contain stream URLs in various shapes;
            # look for any string that looks like an M3U8 URL.
            urls: set[str] = set()

            def _find_m3u8(obj):
                if isinstance(obj, str) and ".m3u8" in obj and "content.echo360" in obj:
                    urls.add(obj)
                elif isinstance(obj, dict):
                    for v in obj.values():
                        _find_m3u8(v)
                elif isinstance(obj, list):
                    for v in obj:
                        _find_m3u8(v)

            _find_m3u8(data)
            if urls:
                return urls
    except Exception:
        pass
    finally:
        await page.close()
    return None


async def capture_media_streams(
    ctx: BrowserContext,
    media_url: str,
    title: str,
) -> dict | None:
    """Navigate directly to a media page and capture M3U8 URLs.

    Unlike :func:`capture_lecture_streams`, this function targets a
    direct media URL (``/media/<uuid>/public``) where the video player
    loads immediately — no row-clicking required.

    Strategy:
      1. Load the page and extract ``mediaId`` from the inline script.
      2. Try the ``player-properties`` API for a direct list of streams.
      3. Fall back to intercepting network requests from the player.

    Returns a dict with ``streams`` and ``cookies``, or ``None`` on
    failure.
    """
    page = await ctx.new_page()
    all_m3u8: set[str] = set()

    def _capture(req):
        url = req.url
        if ".m3u8" in url and "content.echo360" in url:
            all_m3u8.add(url)

    page.on("request", _capture)

    try:
        await page.goto(media_url, wait_until="domcontentloaded", timeout=30_000)

        # Check for login redirect (stale session)
        from echo360_downloader.auth import is_login_redirect

        if await is_login_redirect(page):
            warning("Session expired — media page requires re-login.")
            return None

        # Extract player config from inline <script>
        html = await page.content()
        config = _extract_player_config(html)

        # Wait for the player to initialise and request stream playlists
        await page.wait_for_timeout(15_000)

        # Extract title from <title> tag or player config
        page_title = await page.title()
        if not page_title or page_title == "Echo360":
            page_title = title  # fall back to caller-provided title

        # --- Strategy 1: network interception (already populated above) ---
        streams = resolve_streams(all_m3u8)

        # --- Strategy 2: player-properties API ---
        if not streams and config:
            dim("Trying player-properties API…")
            api_streams = await _try_player_properties_api(
                ctx, config["publicLinkId"], config["mediaId"]
            )
            if api_streams:
                streams = resolve_streams(api_streams)

        if not streams:
            warning(f"No streams for: {title}")
            return None

        cookies = await ctx.cookies()
        return {"streams": streams, "cookies": cookies, "title": page_title}

    except Exception as exc:
        warning(f"Capture error ({title}): {exc}")
        return None
    finally:
        await page.close()
