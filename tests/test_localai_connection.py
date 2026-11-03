from __future__ import annotations

import unittest
from unittest.mock import patch

from LocalAI.check_connection import run_check


class LocalAIConnectionTest(unittest.TestCase):
    def test_passes_when_model_and_effective_context_match(self) -> None:
        payload = {
            "data": [
                {
                    "id": "qwen2.5-coder-7b-q5-k-m",
                    "context_size": 16384,
                }
            ]
        }
        with patch("LocalAI.check_connection._get_json", return_value=payload) as get_json:
            report = run_check(
                "http://127.0.0.1:8080/v1",
                "qwen2.5-coder-7b-q5-k-m",
                16384,
            )

        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["actual_context_tokens"], 16384)
        get_json.assert_called_once_with("http://127.0.0.1:8080/v1/models/capabilities")

    def test_fails_when_server_context_is_smaller_than_mainflow_context(self) -> None:
        payload = {
            "data": [
                {
                    "id": "qwen2.5-coder-7b-q5-k-m",
                    "capabilities": {"context_size": 8192},
                }
            ]
        }
        with patch("LocalAI.check_connection._get_json", return_value=payload):
            report = run_check(
                "http://127.0.0.1:8080/v1",
                "qwen2.5-coder-7b-q5-k-m",
                16384,
            )

        self.assertEqual(report["status"], "context_mismatch")
        self.assertEqual(report["actual_context_tokens"], 8192)

    def test_reports_missing_context_instead_of_silently_passing(self) -> None:
        payload = {"data": [{"id": "qwen2.5-coder-7b-q5-k-m"}]}
        with patch("LocalAI.check_connection._get_json", return_value=payload):
            report = run_check(
                "http://127.0.0.1:8080/v1",
                "qwen2.5-coder-7b-q5-k-m",
                16384,
            )

        self.assertEqual(report["status"], "context_unavailable")


if __name__ == "__main__":
    unittest.main()
