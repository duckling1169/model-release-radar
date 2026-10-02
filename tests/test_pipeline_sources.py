from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
import argparse
from datetime import UTC, datetime
from email.message import Message
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "pipeline" / "sources.py"
SPEC = importlib.util.spec_from_file_location("sources", MODULE_PATH)
assert SPEC and SPEC.loader
collector = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = collector
SPEC.loader.exec_module(collector)

WINDOW = collector.RunWindow(
    datetime(2026, 7, 29, 0, 0, tzinfo=UTC),
    datetime(2026, 7, 30, 0, 0, tzinfo=UTC),
)
NOW = datetime(2026, 7, 30, 0, 1, tzinfo=UTC)
HUGGINGFACE_FIRST = b'[{"modelId":"org/first","createdAt":"2026-07-29T18:00:00Z"},{"modelId":"org/second","createdAt":"2026-07-29T01:00:00Z"}]'
HUGGINGFACE_SECOND = b'[{"modelId":"org/older","createdAt":"2026-07-28T23:00:00Z"}]'
ARXIV_PAGE = b'''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom" xmlns:dc="http://purl.org/dc/elements/1.1/"><entry><id>oai:arXiv.org:2607.00001v1</id><title> Paper 1 </title><summary>arXiv:2607.00001v1 Announce Type: new Abstract: Summary 1</summary><category term="cs.AI"/><published>2026-07-29T00:00:00-04:00</published><arxiv:announce_type>new</arxiv:announce_type><dc:creator>Ada Lovelace, Alan Turing</dc:creator></entry><entry><id>oai:arXiv.org:2607.00002v1</id><title> Paper 2 </title><summary>arXiv:2607.00002v1 Announce Type: cross Abstract: Summary 2</summary><category term="cs.CL"/><published>2026-07-29T00:00:00-04:00</published><arxiv:announce_type>cross</arxiv:announce_type><dc:creator>Ada Lovelace, Alan Turing</dc:creator></entry><entry><id>oai:arXiv.org:2607.00003v1</id><title> Paper 3 </title><summary>arXiv:2607.00003v1 Announce Type: replace Abstract: Summary 3</summary><category term="cs.LG"/><published>2026-07-29T00:00:00-04:00</published><arxiv:announce_type>replace</arxiv:announce_type><dc:creator>Ada Lovelace, Alan Turing</dc:creator></entry><entry><id>oai:arXiv.org:2607.00004v1</id><title> Paper 4 </title><summary>arXiv:2607.00004v1 Announce Type: new Abstract: Summary 4</summary><category term="cs.LG"/><published>2026-07-28T00:00:00-04:00</published><arxiv:announce_type>new</arxiv:announce_type><dc:creator>Ada Lovelace, Alan Turing</dc:creator></entry></feed>'''


def headers(**values: str) -> Message:
    message = Message()
    for key, value in values.items():
        message[key] = value
    return message


def response(url: str, body: bytes, **header_values: str) -> collector.HttpResponse:
    return collector.HttpResponse(
        url=url,
        status=200,
        headers=headers(**{"Content-Type": "application/json", **header_values}),
        body=body,
    )


class FetchSourcesTests(unittest.TestCase):
    def test_parse_utc_requires_z(self) -> None:
        self.assertEqual(collector.parse_utc("2026-07-29T00:00:00Z"), WINDOW.start)
        with self.assertRaises(argparse.ArgumentTypeError):
            collector.parse_utc("2026-07-29T00:00:00+00:00")

    def test_window_is_start_inclusive_and_end_exclusive(self) -> None:
        self.assertTrue(collector.in_window(WINDOW.start, WINDOW))
        self.assertFalse(collector.in_window(WINDOW.end, WINDOW))

    def test_huggingface_stats_and_cursor_pagination(self) -> None:
        first_url = "https://huggingface.co/api/models?first"
        next_url = "https://huggingface.co/api/models?cursor=next"
        calls: list[str] = []

        def fetcher(url: str) -> collector.HttpResponse:
            calls.append(url)
            if len(calls) == 1:
                return response(first_url, HUGGINGFACE_FIRST, Link=f'<{next_url}>; rel="next"')
            return response(next_url, HUGGINGFACE_SECOND)

        with tempfile.TemporaryDirectory() as temp_dir:
            source_dir = Path(temp_dir) / "huggingface"
            manifest = collector.collect_huggingface(source_dir, WINDOW, 10, fetcher, lambda _: None, lambda: NOW)
            self.assertEqual(manifest["response_record_count"], 3)
            self.assertEqual(manifest["window_record_count"], 2)
            self.assertEqual(len(manifest["pages"]), 2)
            self.assertEqual((source_dir / "pages/0001.json").read_bytes(), HUGGINGFACE_FIRST)
            self.assertEqual(calls, [calls[0], next_url])

    def test_arxiv_counts_first_announcements_in_window_from_one_request(self) -> None:
        calls: list[str] = []

        def fetcher(url: str) -> collector.HttpResponse:
            calls.append(url)
            return collector.HttpResponse(
                url=url,
                status=200,
                headers=headers(**{"Content-Type": "application/atom+xml"}),
                body=ARXIV_PAGE,
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            source_dir = Path(temp_dir) / "arxiv"
            manifest = collector.collect_arxiv(source_dir, WINDOW, 10, fetcher, lambda _: None, lambda: NOW)
            self.assertEqual(manifest["response_record_count"], 4)
            self.assertEqual(manifest["window_record_count"], 2)
            self.assertEqual(len(calls), 1)
            self.assertEqual((source_dir / "pages/0001.xml").read_bytes(), ARXIV_PAGE)

    def test_partial_failure_keeps_successful_source_and_marks_run_incomplete(self) -> None:
        def fetcher(url: str) -> collector.HttpResponse:
            if "huggingface" in url:
                return response(url, HUGGINGFACE_SECOND)
            raise collector.CollectionError("arXiv unavailable")

        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir, manifest = collector.collect_run(
                Path(temp_dir), WINDOW, ("huggingface", "arxiv"), 10, fetcher, lambda _: None, lambda: NOW, "test-run"
            )
            self.assertEqual(manifest["status"], "incomplete")
            self.assertEqual(manifest["sources"]["huggingface"]["status"], "succeeded")
            self.assertEqual(manifest["sources"]["arxiv"]["status"], "failed")
            self.assertTrue((run_dir / "huggingface/pages/0001.json").exists())
            self.assertTrue((run_dir / "arxiv/manifest.json").exists())

    def test_safety_limit_is_reported_as_source_failure(self) -> None:
        def fetcher(url: str) -> collector.HttpResponse:
            return response(url, HUGGINGFACE_FIRST, Link='<https://next>; rel="next"')

        with tempfile.TemporaryDirectory() as temp_dir:
            _, manifest = collector.collect_run(
                Path(temp_dir), WINDOW, ("huggingface",), 1, fetcher, lambda _: None, lambda: NOW, "limit-run"
            )
            self.assertEqual(manifest["status"], "incomplete")
            self.assertIn("max-pages=1", str(manifest["sources"]["huggingface"]["error"]))

    def test_transient_response_retries_with_backoff(self) -> None:
        calls = 0
        delays: list[float] = []

        def fetcher(url: str) -> collector.HttpResponse:
            nonlocal calls
            calls += 1
            if calls == 1:
                return collector.HttpResponse(url, 503, headers(), b"temporarily unavailable")
            return response(url, HUGGINGFACE_SECOND)

        result = collector.fetch_with_retry("https://example.test", fetcher, delays.append)
        self.assertEqual(result.status, 200)
        self.assertEqual(calls, 2)
        self.assertEqual(delays, [collector.RETRY_BASE_SECONDS])

    def test_manifest_is_valid_json(self) -> None:
        def fetcher(url: str) -> collector.HttpResponse:
            return response(url, HUGGINGFACE_SECOND)

        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir, _ = collector.collect_run(
                Path(temp_dir), WINDOW, ("huggingface",), 10, fetcher, lambda _: None, lambda: NOW, "manifest-run"
            )
            manifest = json.loads((run_dir / "run_manifest.json").read_text())
            self.assertEqual(manifest["window"], {"end": "2026-07-30T00:00:00Z", "start": "2026-07-29T00:00:00Z"})


if __name__ == "__main__":
    unittest.main()
