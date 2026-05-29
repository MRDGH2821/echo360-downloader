"""SSO login and session persistence for Echo360."""

import json
from pathlib import Path

from playwright.async_api import async_playwright

from echo360_downloader.utils import default_state_path


async def do_login(state_path: Path | None = None) -> None:
    """Open an interactive browser, let the user complete SSO, save session.

    The user must log in via their institution's SSO in the browser window.
    After successful login (detected by reaching a section/home or lesson URL),
    the Playwright storage state (cookies + localStorage) is persisted to
    ``state_path``.
    """
    state_path = state_path or default_state_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)

    print("Opening browser for Echo360 login...")
    print("(Complete the SSO login in the browser window that opens)")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context(viewport={"width": 1280, "height": 900})
        page = await ctx.new_page()

        await page.goto("https://echo360.net.au", timeout=60_000)
        print(f"Current URL: {page.url}")
        print("Waiting for login to complete...")

        while True:
            await page.wait_for_timeout(2_000)
            url = page.url
            if "/section/" in url and "/home" in url:
                print(f"Login successful! URL: {url}")
                break
            if "/lesson/" in url:
                print(f"Login successful! (redirected to lesson) URL: {url}")
                break

        await page.wait_for_timeout(3_000)

        state = await ctx.storage_state()
        with open(state_path, "w") as f:
            json.dump(state, f)
        print(
            f"Saved {len(state.get('cookies', []))} cookies "
            f"and {len(state.get('origins', []))} origins to {state_path}"
        )

        await browser.close()
