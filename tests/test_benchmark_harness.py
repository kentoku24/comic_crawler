from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


class BenchmarkHarnessTests(unittest.TestCase):
    def test_run_benchmarks_outputs_expected_metric_shape(self):
        repo_root = Path(__file__).resolve().parents[1]

        result = subprocess.run(
            [sys.executable, "scripts/run_benchmarks.py", "--sample-count", "1"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(
            {"runner_100_works", "latest_ack", "fetch_ack", "latest_full_response"},
            {metric["name"] for metric in payload["metrics"]},
        )
        for metric in payload["metrics"]:
            self.assertEqual(1, len(metric["samples_ms"]))
            self.assertIn("target_ms", metric)
            self.assertIn("average_ms", metric)
            self.assertIn("p95_ms", metric)
            self.assertIn("max_ms", metric)
