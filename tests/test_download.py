import tempfile
import unittest
from pathlib import Path

from echo360_downloader.batch import _should_skip_course
from echo360_downloader.download import (
    _ffmpeg_error_summary,
    _ffmpeg_headers,
    _rewrite_local_playlist_refs,
)


class LocalPlaylistReferenceTests(unittest.TestCase):
    def test_rewrites_local_playlist_references_but_keeps_remote_segments(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            master = directory / "master.m3u8"
            variant = directory / "variant.m3u8"
            segment_url = "https://content.echo360.net.au/segment.m4s?x-uid=abc"
            master.write_text(f'#EXTM3U\n#EXT-X-MEDIA:URI="{variant}"\n{variant}\n')
            variant.write_text(f"#EXTM3U\n{segment_url}\n")

            _rewrite_local_playlist_refs(directory)

            master_content = master.read_text()
            self.assertIn('URI="variant.m3u8"', master_content)
            self.assertIn("\nvariant.m3u8\n", master_content)
            self.assertNotIn(str(variant), master_content)
            self.assertIn(segment_url, variant.read_text())


class BatchResumeTests(unittest.TestCase):
    def test_skips_completed_course_with_summary(self):
        self.assertTrue(_should_skip_course({"status": "completed", "summary": {}}))

    def test_retries_partial_course(self):
        self.assertFalse(_should_skip_course({"status": "partial", "summary": {}}))


class FFmpegHeadersTests(unittest.TestCase):
    def test_includes_echo360_request_headers_and_cookies(self):
        headers = _ffmpeg_headers("session=abc; auth=xyz")

        self.assertIn("User-Agent: Mozilla/5.0", headers)
        self.assertIn("Referer: https://echo360.net.au/", headers)
        self.assertIn("Origin: https://echo360.net.au", headers)
        self.assertIn("Cookie: session=abc; auth=xyz", headers)
        self.assertTrue(headers.endswith("\r\n"))

    def test_omits_cookie_header_when_empty(self):
        headers = _ffmpeg_headers("")

        self.assertNotIn("Cookie:", headers)
        self.assertIn("Referer: https://echo360.net.au/", headers)

    def test_error_summary_excludes_configuration_and_reports_http_403(self):
        stderr = (
            "configuration: --prefix=/usr -Werror=format-security\n"
            "[https] HTTP error 403 Forbidden\n"
            "Error when loading first segment"
        )

        summary = _ffmpeg_error_summary(stderr)

        self.assertNotIn("configuration:", summary)
        self.assertIn("HTTP error 403 Forbidden", summary)
        self.assertIn("Error when loading first segment", summary)


if __name__ == "__main__":
    unittest.main()
