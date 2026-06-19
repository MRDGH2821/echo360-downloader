"""Browser session lifecycle — launch, context creation, session checks."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    ViewportSize,
    async_playwright,
)

from echo360_downloader.auth import ensure_session

_VIEWPORT: ViewportSize = {"width": 1280, "height": 900}


@asynccontextmanager
async def create_session(
    state_path: Path,
    section_url: str,
    headed: bool = False,
) -> AsyncIterator[tuple[Browser, BrowserContext, Page]]:
    """Launch a browser, create an authenticated context, and yield a page.

    The yielded page has already been navigated to *section_url* and
    passed the session check (auto-re-login if stale).  On exit the
    browser is closed.

    Usage::

        async with create_session(state, url) as (browser, ctx, page):
            # page is ready — call get_course_name(page), etc.
            ...
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not headed)
        ctx = await browser.new_context(
            storage_state=str(state_path),
            viewport=_VIEWPORT,
        )
        page = await ctx.new_page()
        await ensure_session(state_path, page, section_url)
        try:
            yield browser, ctx, page
        finally:
            await browser.close()


@asynccontextmanager
async def create_browser_context(
    state_path: Path,
    headed: bool = False,
) -> AsyncIterator[tuple[Browser, BrowserContext]]:
    """Launch a browser with an authenticated context, without navigating.

    Yields ``(browser, ctx)`` — callers create their own pages and
    handle navigation.  Used by batch mode which manages multiple course
    URLs on a single context.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not headed)
        ctx = await browser.new_context(
            storage_state=str(state_path),
            viewport=_VIEWPORT,
        )
        try:
            yield browser, ctx
        finally:
            await browser.close()
