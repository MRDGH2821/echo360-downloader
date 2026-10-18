import unittest

from echo360_downloader.batch import _should_skip_course
from echo360_downloader.download import _ffmpeg_error_summary, _ffmpeg_headers


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
