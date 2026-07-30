from __future__ import annotations

import ast
import unittest
from pathlib import Path


JOB = Path(__file__).parents[1] / "pipeline" / "run_job.py"


class M4JobContractTests(unittest.TestCase):
    def test_job_requires_explicit_utc_window_and_has_both_guards(self) -> None:
        source = JOB.read_text(encoding="utf-8")
        self.assertIn('parser.add_argument("--start", required=True)', source)
        self.assertIn('parser.add_argument("--end", required=True)', source)
        self.assertIn("MAX_STORAGE_BYTES = 5 * 1024**3", source)
        self.assertIn("MAX_MONTHLY_QUERY_BYTES = 900 * 1024**3", source)
        ast.parse(source)

    def test_incomplete_capture_is_retained_and_never_invokes_dataform(self) -> None:
        source = JOB.read_text(encoding="utf-8")
        load_index = source.index("manifest = load_bronze")
        failure_index = source.index("if exit_code != 0", load_index)
        call_index = source.index("invoke_dataform(", failure_index)
        self.assertLess(load_index, failure_index)
        self.assertLess(failure_index, call_index)

    def test_job_keeps_its_temporary_capture_path_dependency(self) -> None:
        source = JOB.read_text(encoding="utf-8")
        self.assertIn("from pathlib import Path", source)
        self.assertIn('Path(directory) / "raw"', source)


if __name__ == "__main__":
    unittest.main()
