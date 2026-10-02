from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


PIPELINE = Path(__file__).parents[1] / "pipeline"
sys.path.insert(0, str(PIPELINE))
SPEC = importlib.util.spec_from_file_location("arxiv_normalize", PIPELINE / "arxiv_normalize.py")
assert SPEC and SPEC.loader
transform = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = transform
SPEC.loader.exec_module(transform)


class ArxivNormalizeTests(unittest.TestCase):
    def test_keeps_first_announcements_in_window(self) -> None:
        pages = [
            {
                "run_id": "run-1", "page_number": 1, "fetched_at": "2026-07-30T07:21:00Z",
                "window_start": "2026-07-29T00:00:00Z", "window_end": "2026-07-30T00:00:00Z",
                "raw_body": '''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom" xmlns:dc="http://purl.org/dc/elements/1.1/"><entry><id>oai:arXiv.org:2607.00001v1</id><title> Paper 1 </title><summary>arXiv:2607.00001v1 Announce Type: new Abstract: Summary 1</summary><category term="cs.AI"/><published>2026-07-29T00:00:00-04:00</published><arxiv:announce_type>new</arxiv:announce_type><dc:creator>Ada Lovelace, Alan Turing</dc:creator></entry><entry><id>oai:arXiv.org:2607.00002v1</id><title> Paper 2 </title><summary>arXiv:2607.00002v1 Announce Type: cross Abstract: Summary 2</summary><category term="cs.CL"/><published>2026-07-29T00:00:00-04:00</published><arxiv:announce_type>cross</arxiv:announce_type><dc:creator>Ada Lovelace, Alan Turing</dc:creator></entry><entry><id>oai:arXiv.org:2607.00003v1</id><title> Paper 3 </title><summary>arXiv:2607.00003v1 Announce Type: replace Abstract: Summary 3</summary><category term="cs.LG"/><published>2026-07-29T00:00:00-04:00</published><arxiv:announce_type>replace</arxiv:announce_type><dc:creator>Ada Lovelace, Alan Turing</dc:creator></entry><entry><id>oai:arXiv.org:2607.00004v1</id><title> Paper 4 </title><summary>arXiv:2607.00004v1 Announce Type: new Abstract: Summary 4</summary><category term="cs.LG"/><published>2026-07-28T00:00:00-04:00</published><arxiv:announce_type>new</arxiv:announce_type><dc:creator>Ada Lovelace, Alan Turing</dc:creator></entry></feed>''',
            }
        ]
        rows = transform.arxiv_rows(pages, "2026-07-30T07:22:00Z")
        self.assertEqual([row["source_id"] for row in rows], ["2607.00001", "2607.00002"])
        self.assertEqual(rows[0]["canonical_url"], "https://arxiv.org/abs/2607.00001")
        self.assertEqual(rows[0]["title"], "Paper 1")
        self.assertEqual(rows[0]["summary"], "Summary 1")
        self.assertEqual(rows[0]["authors_json"], '["Ada Lovelace", "Alan Turing"]')
        self.assertEqual(rows[0]["source_published_at"], "2026-07-29T04:00:00+00:00")

if __name__ == "__main__":
    unittest.main()
