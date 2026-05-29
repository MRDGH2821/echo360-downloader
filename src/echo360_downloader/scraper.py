"""Course-page scraping — lecture list, course name, navigation."""

import re

from playwright.async_api import Page


async def get_course_name(page: Page) -> str:
    """Extract the human-readable course/section name from the page."""
    name = await page.evaluate("""
        () => {
            const selectors = [
                '.section-header h1', '.section-title', '.course-title',
                '.section-name', 'h1', '.breadcrumb li:last-child',
                '.topbar-title', '[data-testid="section-name"]',
            ];
            for (const sel of selectors) {
                const el = document.querySelector(sel);
                if (el && el.textContent.trim()) return el.textContent.trim();
            }
            return document.title || '';
        }
    """)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:100] or "unknown-course"


async def get_lecture_list(page: Page) -> list[dict]:
    """Extract lecture rows from the course page DOM.

    Each dict returned contains:

    * ``lessonId``       — Echo360 lesson identifier (contains embedded ISO timestamps)
    * ``ariaLabel``      — row aria-label attribute
    * ``text``           — row text content (truncated)
    * ``date``           — ISO 8601 date (*YYYY-MM-DD*) extracted from the lesson ID
    """
    return await page.evaluate("""
        () => {
            const rows = document.querySelectorAll('.class-row');
            return Array.from(rows).map(row => {
                const lessonId = row.getAttribute('data-test-lessonid') || '';
                // lessonId format: G_<uuid>_<section>_<startISO>_<endISO>
                const parts = lessonId.split('_');
                const startTime = parts.length >= 4 ? parts[parts.length - 2] : '';
                const date = startTime ? startTime.substring(0, 10) : '';
                return {
                    lessonId,
                    ariaLabel: row.getAttribute('aria-label') || '',
                    text: (row.textContent || '').trim().substring(0, 200),
                    date,
                };
            });
        }
    """)
