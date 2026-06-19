"""Lecture stream capture — opens a lecture page, intercepts M3U8 URLs."""

from __future__ import annotations

from playwright.async_api import BrowserContext

from echo360_downloader.streams import resolve_streams
from echo360_downloader.ui import warning


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
