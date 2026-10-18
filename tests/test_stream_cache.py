import asyncio
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from echo360_downloader.batch import (
    _cached_stream_urls,
    _capture_lecture,
    _download_lecture_streams,
    read_status,
    write_status,
)


class CachedLectureReuseTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_cached_urls_without_calling_browser_capture(self):
        cached_urls = {"combined": "https://cdn.example/lecture.m3u8?sig=cached"}
        with patch(
            "echo360_downloader.capture.capture_lecture_streams",
            new=AsyncMock(),
        ) as capture:
            result = await _capture_lecture(
                ctx=None,
                section_url="https://echo360.net.au/section/example",
                lecture={
                    "lessonId": "lesson-1",
                    "ariaLabel": "Lecture 1",
                    "date": "2026-10-18",
                    "startTime": "11:00",
                },
                idx=1,
                course_root=Path("course"),
                cached_streams=cached_urls,
                cached_cookies=[],
            )

        capture.assert_not_awaited()
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["streams"], cached_urls)
        self.assertTrue(result["cached"])


class CachedStreamUrlTests(unittest.TestCase):
    def test_status_round_trip_persists_stream_urls_with_private_permissions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            status_path = Path(temp_dir) / "course_status.yaml"
            stream_url = "https://cdn.example/combined.m3u8?sig=private"
            courses = [
                {
                    "url": "https://echo360.net.au/section/example",
                    "lectures": [
                        {
                            "lesson_id": "lesson-1",
                            "stream_urls": {"combined": stream_url},
                        }
                    ],
                }
            ]

            write_status(status_path, courses, parallel=1)
            loaded = read_status(status_path)

            self.assertEqual(
                loaded[courses[0]["url"]]["lectures"][0]["stream_urls"]["combined"],
                stream_url,
            )
            self.assertEqual(stat.S_IMODE(status_path.stat().st_mode), 0o600)

    def test_reads_cached_stream_urls_from_status_entry(self):
        previous = {
            "lesson_id": "lesson-1",
            "stream_urls": {
                "combined": "https://cdn.example/combined.m3u8?sig=abc",
                "camera": "https://cdn.example/camera.m3u8?sig=def",
            },
        }

        self.assertEqual(
            _cached_stream_urls(previous),
            previous["stream_urls"],
        )

    def test_ignores_missing_or_invalid_cache_data(self):
        self.assertEqual(_cached_stream_urls(None), {})
        self.assertEqual(_cached_stream_urls({"stream_urls": {"combined": None}}), {})


class CachedStreamRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_recaptures_and_retries_a_failed_cached_stream_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            lecture = {
                "title": "Lecture 1",
                "lesson_id": "lesson-1",
                "streams": {"combined": "https://cdn.example/old.m3u8?sig=old"},
                "cookies": [],
                "lecture_dir": Path(temp_dir),
                "cached": True,
            }
            refresh_streams = AsyncMock(
                return_value={
                    "streams": {"combined": "https://cdn.example/new.m3u8?sig=new"},
                    "cookies": [],
                }
            )

            with patch(
                "echo360_downloader.download.download_stream",
                new=AsyncMock(side_effect=[False, True]),
            ) as download_stream:
                result = await _download_lecture_streams(
                    lecture,
                    asyncio.Semaphore(1),
                    refresh_streams=refresh_streams,
                )

        self.assertEqual(
            [entry.args[0] for entry in download_stream.await_args_list],
            [
                "https://cdn.example/old.m3u8?sig=old",
                "https://cdn.example/new.m3u8?sig=new",
            ],
        )
        refresh_streams.assert_awaited_once()
        self.assertEqual(result["outcome"], "success")
        self.assertEqual(
            result["stream_urls"],
            {"combined": "https://cdn.example/new.m3u8?sig=new"},
        )

    async def test_drops_failed_cached_url_when_refresh_omits_that_stream(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            lecture = {
                "title": "Lecture 1",
                "lesson_id": "lesson-1",
                "streams": {"combined": "https://cdn.example/old.m3u8?sig=old"},
                "cookies": [],
                "lecture_dir": Path(temp_dir),
                "cached": True,
            }
            refresh_streams = AsyncMock(
                return_value={
                    "streams": {"camera": "https://cdn.example/camera.m3u8"},
                    "cookies": [],
                }
            )

            with patch(
                "echo360_downloader.download.download_stream",
                new=AsyncMock(return_value=False),
            ):
                result = await _download_lecture_streams(
                    lecture,
                    asyncio.Semaphore(1),
                    refresh_streams=refresh_streams,
                )

        self.assertNotIn("combined", result["stream_urls"])
        self.assertEqual(result["streams"]["combined"], "failed")


if __name__ == "__main__":
    unittest.main()
