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
    """Extract lecture rows from the course page DOM."""
    return await page.evaluate("""
        () => {
            const rows = document.querySelectorAll('.class-row');
            return Array.from(rows).map(row => ({
                lessonId: row.getAttribute('data-test-lessonid') || '',
                ariaLabel: row.getAttribute('aria-label') || '',
                text: (row.textContent || '').trim().substring(0, 200),
            }));
        }
    """)


def guess_lecture_folder_name(title: str) -> str:
    """Determine the folder name that will be used for a lecture."""
    m = re.search(r"(\w+ \d+,? \d{4})", title)
    date_part = m.group(1) if m else ""
    raw = f"{date_part} - {title}".strip(" -")
    safe = re.sub(r'[<>:"/\\|?*]', "", raw)
    safe = re.sub(r"\s+", " ", safe).strip()
    return safe[:200]
