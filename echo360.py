#!/usr/bin/env python3
"""
Echo360 Lecture Downloader

Automates downloading lectures from Echo360 using Playwright for
authentication and ffmpeg for video download.

Usage:
    python echo360.py login                             # SSO login (saves session)
    python echo360.py list --url <section_url>          # List lectures
    python echo360.py download [N|ALL] --url <url>      # Download lecture(s)

Examples:
    python echo360.py list --url "https://echo360.net.au/section/.../home"
    python echo360.py download ALL --url "https://echo360.net.au/section/.../home"
    python echo360.py download 1 --url "https://echo360.net.au/section/.../home"
"""

import asyncio, json, os, re, sys, time
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from playwright.async_api import async_playwright

BASE_DIR = Path.home() / "echo360-downloader"
STATE_FILE = BASE_DIR / "storage_state.json"
DOWNLOAD_DIR = BASE_DIR / "downloads"
COURSE_URL = None  # Set per command via --url

DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


def sanitize_filename(name: str) -> str:
    """Remove characters that are problematic in filenames."""
    safe = re.sub(r'[<>:"/\\|?*]', '', name)
    safe = re.sub(r'\s+', ' ', safe).strip()
    return safe[:200]


def parse_args():
    """Parse CLI args, returning (command, url, target)."""
    args = sys.argv[1:]
    command = None
    url = None
    target = None
    
    i = 0
    while i < len(args):
        a = args[i]
        if a == '--url' and i + 1 < len(args):
            url = args[i + 1]
            i += 2
        elif command is None:
            command = a
            i += 1
        else:
            target = a
            i += 1
    
    return command, url, target


async def do_login():
    """Open browser for SSO login, save storage_state.json."""
    print("Opening browser for Echo360 login...")
    print("(Complete the SSO login in the browser window that opens)")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context(viewport={"width": 1280, "height": 900})
        page = await ctx.new_page()
        
        await page.goto("https://echo360.net.au", timeout=60000)
        
        print(f"Current URL: {page.url}")
        print("Waiting for login to complete...")
        
        while True:
            await asyncio.sleep(2)
            url = page.url
            if '/section/' in url and '/home' in url:
                print(f"Login successful! URL: {url}")
                break
            if '/lesson/' in url:
                print(f"Login successful! (redirected to lesson) URL: {url}")
                break
        
        await asyncio.sleep(3)
        
        state = await ctx.storage_state()
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f)
        cookie_count = len(state.get('cookies', []))
        origin_count = len(state.get('origins', []))
        print(f"Saved {cookie_count} cookies and {origin_count} origins to {STATE_FILE}")
        
        await browser.close()


async def get_course_name(page) -> str:
    """Extract course name from the section page."""
    name = await page.evaluate("""
        () => {
            // Try common selectors for course/section name
            const selectors = [
                '.section-header h1',
                '.section-title',
                '.course-title',
                '.section-name',
                'h1',
                '.breadcrumb li:last-child',
                '.topbar-title',
                '[data-testid="section-name"]',
            ];
            for (const sel of selectors) {
                const el = document.querySelector(sel);
                if (el && el.textContent.trim()) {
                    return el.textContent.trim();
                }
            }
            // Fall back to page title
            return document.title || '';
        }
    """)
    # Clean up
    name = re.sub(r'\s+', ' ', name).strip()
    # Truncate if very long
    name = name[:100] if len(name) > 100 else name
    return name or "unknown-course"


async def get_lecture_list(page) -> list[dict]:
    """Extract lecture list from the course page."""
    lectures = await page.evaluate("""
        () => {
            const rows = document.querySelectorAll('.class-row');
            return Array.from(rows).map(row => {
                const lessonId = row.getAttribute('data-test-lessonid') || '';
                const ariaLabel = row.getAttribute('aria-label') || '';
                const text = row.textContent || '';
                return {
                    lessonId: lessonId,
                    ariaLabel: ariaLabel,
                    text: text.trim().substring(0, 200),
                };
            });
        }
    """)
    return lectures


async def get_available_streams(page, existing_m3u8_urls=None):
    """
    From the current lecture page, extract available M3U8 stream URLs.

    Stream layout:
      s0 = audio (room microphone)
      s1 = camera video (presenter) — video only
      s2 = combined video (PIP) — video only, audio via EXT-X-MEDIA from s0

    Returns dict with keys 'combined', 'camera', 'audio' for best quality.
    """
    m3u8_urls = existing_m3u8_urls or set()
    mp4_urls = set()
    
    def on_request(req):
        url = req.url
        if '.m3u8' in url and 'content.echo360' in url:
            m3u8_urls.add(url)
        if '.mp4' in url and 'content.echo360' in url:
            mp4_urls.add(url)
    
    page.on("request", on_request)
    
    # Wait for stream requests to come in
    await asyncio.sleep(8)
    
    streams = {}
    
    # Combined: s2_av.m3u8 (master with audio) > s2q1 > s2q0
    for url in sorted(m3u8_urls):
        if '/s2_av.' in url:
            streams['combined'] = url
            break
    if 'combined' not in streams:
        for url in m3u8_urls:
            if '/s2q1.' in url:
                streams['combined'] = url
                break
    if 'combined' not in streams:
        for url in m3u8_urls:
            if '/s2q0.' in url:
                streams['combined'] = url
                break
    
    # Camera: s1_v.m3u8 (master) > s1q1 > s1q0
    for url in sorted(m3u8_urls):
        if '/s1_v.' in url:
            streams['camera'] = url
            break
    if 'camera' not in streams:
        for url in m3u8_urls:
            if '/s1q1.' in url:
                streams['camera'] = url
                break
    if 'camera' not in streams:
        for url in m3u8_urls:
            if '/s1q0.' in url:
                streams['camera'] = url
                break
    
    # Audio-only: s0q1 > s0q0
    for url in m3u8_urls:
        if '/s0q1.' in url:
            streams['audio'] = url
            break
    if 'audio' not in streams:
        for url in m3u8_urls:
            if '/s0q0.' in url:
                streams['audio'] = url
                break
    
    return streams, m3u8_urls


async def download_stream(stream_url: str, output_path: Path, cookies: list, audio_url: str = None) -> bool:
    """
    Download a single M3U8 stream using ffmpeg with cookie authentication.
    
    If audio_url is provided (e.g. for camera video), muxes video with audio.
    """
    cookie_str = "; ".join([
        f"{c['name']}={c['value']}" 
        for c in cookies 
        if any(d in c.get('domain', '') for d in ['echo360'])
    ])
    headers = f"Cookie: {cookie_str}\r\nReferer: https://echo360.net.au/\r\nOrigin: https://echo360.net.au\r\n"
    
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
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=3600)
        if process.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
            size_mb = output_path.stat().st_size / 1024 / 1024
            print(f"    Downloaded: {output_path.name} ({size_mb:.1f} MB)")
            return True
        else:
            err = stderr.decode()[-300:]
            print(f"    FAILED (exit {process.returncode}): {err}")
            return False
    except asyncio.TimeoutError:
        print(f"    TIMEOUT after 3600s")
        process.kill()
        return False


async def download_single_lecture(ctx, lesson_id: str, lecture_title: str,
                                  course_dir: Path, idx: int = None) -> dict:
    """
    Download all streams for a single lecture into course_dir.
    Returns dict of {stream_type: success_bool}.
    """
    prefix = f"[{idx}] " if idx else ""
    print(f"\n{prefix}Processing: {lecture_title}")
    
    page = await ctx.new_page()
    
    try:
        m3u8_urls = set()
        page.on("request", lambda req: m3u8_urls.add(req.url) 
                if '.m3u8' in req.url and 'content.echo360' in req.url else None)
        
        # Navigate to the course page, then click the lecture
        await page.goto(ctx.course_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)
        
        clicked = await page.evaluate(f"""
            (lessonId) => {{
                const rows = document.querySelectorAll('.class-row');
                for (const row of rows) {{
                    if (row.getAttribute('data-test-lessonid') === lessonId) {{
                        row.scrollIntoView({{block: 'center'}});
                        return true;
                    }}
                }}
                return false;
            }}
        """, lesson_id)
        
        if not clicked:
            print(f"    Could not find lecture row with lessonId: {lesson_id[:60]}")
            await page.close()
            return {}
        
        rows = await page.query_selector_all(f'[data-test-lessonid="{lesson_id}"]')
        if not rows:
            print(f"    Row not found via selector")
            await page.close()
            return {}
        
        await rows[0].click()
        await asyncio.sleep(10)
        
        streams, _ = await get_available_streams(page, m3u8_urls)
        
        if not streams:
            print(f"    No streams found for this lecture")
            await page.close()
            return {}
        
        print(f"    Streams available: {', '.join(streams.keys())}")
        
        # Create lecture-specific subdirectory within course directory
        date_match = re.search(r'(\w+ \d+,? \d{4})', lecture_title)
        date_part = date_match.group(1) if date_match else ""
        lecture_dir_name = sanitize_filename(f"{date_part} - {lecture_title}".strip(' -'))
        lecture_dir = course_dir / lecture_dir_name
        lecture_dir.mkdir(parents=True, exist_ok=True)
        
        cookies = await ctx.cookies()
        
        results = {}
        audio_url = streams.get('audio')
        for stream_type, stream_url in streams.items():
            output_path = lecture_dir / f"{sanitize_filename(lecture_title)} - {stream_type}.mp4"
            
            if len(str(output_path)) > 240:
                output_path = lecture_dir / f"{stream_type}.mp4"
            
            print(f"    Downloading {stream_type} stream...")
            if stream_type == 'camera' and audio_url:
                success = await download_stream(stream_url, output_path, cookies, audio_url=audio_url)
            else:
                success = await download_stream(stream_url, output_path, cookies)
            results[stream_type] = success
        
        await page.close()
        return results
    
    except Exception as e:
        print(f"    ERROR: {e}")
        await page.close()
        return {}


async def cmd_list(url: str):
    """List all lectures for a course section."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            storage_state=str(STATE_FILE),
            viewport={"width": 1280, "height": 900},
        )
        ctx.course_url = url
        page = await ctx.new_page()
        
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        
        course_name = await get_course_name(page)
        print(f"\nCourse: {course_name}")
        
        lectures = await get_lecture_list(page)
        
        if not lectures:
            print("No lectures found. Check if session is still valid.")
            await browser.close()
            return
        
        print(f"Found {len(lectures)} lectures:\n")
        for i, lec in enumerate(lectures, 1):
            lesson_id = lec['lessonId']
            aria = lec['ariaLabel']
            short_id = lesson_id[:60] + "..." if len(lesson_id) > 60 else lesson_id
            print(f"  {i:2d}. {aria}")
            print(f"       lessonId: {short_id}")
        
        await browser.close()


async def cmd_download(url: str, target=None):
    """
    Download lectures from a course section.
    target: None or 'ALL' -> all lectures
            int -> lecture index (1-indexed)
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            storage_state=str(STATE_FILE),
            viewport={"width": 1280, "height": 900},
        )
        ctx.course_url = url
        page = await ctx.new_page()
        
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        
        course_name = await get_course_name(page)
        # Use course name for subfolder, fallback to section ID
        section_match = re.search(r'/section/([^/]+)', url)
        section_id = section_match.group(1) if section_match else "unknown"
        if course_name and course_name != "unknown-course":
            course_dir_name = sanitize_filename(course_name)
        else:
            course_dir_name = section_id[:30]
        course_dir = DOWNLOAD_DIR / course_dir_name
        course_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"\nCourse: {course_name}")
        print(f"Output: {course_dir}/\n")
        
        lectures = await get_lecture_list(page)
        
        if not lectures:
            print("No lectures found. Check if session is still valid. Run 'login' first.")
            await browser.close()
            return
        
        if target is None:
            indices = list(range(len(lectures)))
        elif target == 'ALL':
            indices = list(range(len(lectures)))
        else:
            indices = [target - 1]
        
        print(f"Downloading {len(indices)} lecture(s) out of {len(lectures)} total")
        
        total_streams = 0
        successful = 0
        
        for idx in indices:
            lec = lectures[idx]
            lesson_id = lec['lessonId']
            info = lec.get('ariaLabel', lec.get('text', f'Lecture {idx+1}').strip()[:80])
            
            results = await download_single_lecture(ctx, lesson_id, info, course_dir, idx + 1)
            
            for stream_type, success in results.items():
                total_streams += 1
                if success:
                    successful += 1
        
        print(f"\n{'='*50}")
        print(f"Done! {successful}/{total_streams} streams downloaded successfully.")
        print(f"Output directory: {course_dir}")
        
        await browser.close()


async def main():
    command, url, target = parse_args()
    
    if not command or command in ('-h', '--help'):
        print(__doc__)
        return
    
    if command != 'login' and not STATE_FILE.exists():
        print("No saved session found. Run 'login' first to authenticate.")
        return
    
    if command == 'login':
        await do_login()
    elif command == 'list':
        if not url:
            print("Error: --url <section_url> is required for 'list'")
            return
        await cmd_list(url)
    elif command == 'download':
        if not url:
            print("Error: --url <section_url> is required for 'download'")
            return
        if target == 'ALL':
            await cmd_download(url)
        elif target is not None:
            try:
                n = int(target)
                await cmd_download(url, n)
            except ValueError:
                print(f"Invalid target: {target}. Use a number, 'ALL', or omit.")
                return
        else:
            await cmd_download(url)
    else:
        print(f"Unknown command: {command}")
        print(__doc__)


if __name__ == "__main__":
    asyncio.run(main())
