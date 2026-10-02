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
    def test_arxiv_uses_first_submission_identity_and_published_window(self) -> None:
        pages = [
            {
                "run_id": "run-1", "page_number": 2, "fetched_at": "2026-07-29T12:01:00Z",
                "window_start": "2026-07-29T00:00:00Z", "window_end": "2026-07-30T00:00:00Z",
                "raw_body": '''<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/2607.00001v2</id><published>2026-07-29T11:00:00Z</published><updated>2026-07-30T01:00:00Z</updated><title> A Paper </title><summary> Summary text </summary><author><name>Ada</name></author><category term="cs.AI" /></entry><entry><id>http://arxiv.org/abs/2607.00002v1</id><published>2026-07-28T23:59:59Z</published><updated>2026-07-28T23:59:59Z</updated><category term="cs.CL" /></entry></feed>''',
            }
        ]
        rows = transform.arxiv_rows(pages, "2026-07-29T14:00:00Z")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_id"], "2607.00001")
        self.assertEqual(rows[0]["arxiv_version"], "v2")
        self.assertEqual(rows[0]["canonical_url"], "https://arxiv.org/abs/2607.00001")
        self.assertEqual(rows[0]["title"], "A Paper")


if __name__ == "__main__":
    unittest.main()
