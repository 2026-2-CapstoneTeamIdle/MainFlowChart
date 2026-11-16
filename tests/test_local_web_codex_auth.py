from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPOSITORY_ROOT / "CI" / "CD" / "LocalWeb" / "codex_auth.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("mainflow_local_web_codex_auth", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


codex_auth = _load_module()


class CodexAuthManagerTests(unittest.TestCase):
    def test_missing_cli_is_reported_without_starting_login(self) -> None:
        with patch.object(codex_auth, "_find_codex_executable", return_value=None):
            snapshot = codex_auth.CodexAuthManager().snapshot()

        self.assertFalse(snapshot["installed"])
        self.assertFalse(snapshot["authenticated"])
        self.assertEqual(snapshot["phase"], "unavailable")

    def test_successful_login_status_is_reported(self) -> None:
        version = subprocess.CompletedProcess(["codex", "--version"], 0, "codex-cli 1.0\n", "")
        login = subprocess.CompletedProcess(
            ["codex", "login", "status"],
            0,
            "Logged in using ChatGPT\n",
            "",
        )
        manager = codex_auth.CodexAuthManager("codex")

        with patch.object(codex_auth, "_run_codex", side_effect=[version, login]):
            snapshot = manager.snapshot()

        self.assertTrue(snapshot["installed"])
        self.assertTrue(snapshot["authenticated"])
        self.assertEqual(snapshot["phase"], "authenticated")
        self.assertIn("codex-cli 1.0", snapshot["version"])

    def test_signed_out_status_requests_device_login(self) -> None:
        version = subprocess.CompletedProcess(["codex", "--version"], 0, "codex-cli 1.0\n", "")
        login = subprocess.CompletedProcess(["codex", "login", "status"], 1, "", "Not logged in")
        manager = codex_auth.CodexAuthManager("codex")

        with patch.object(codex_auth, "_run_codex", side_effect=[version, login]):
            snapshot = manager.snapshot()

        self.assertTrue(snapshot["installed"])
        self.assertFalse(snapshot["authenticated"])
        self.assertEqual(snapshot["phase"], "signed_out")
        self.assertIn("Device Code", snapshot["message"])

    def test_logout_removes_credentials_and_reports_signed_out(self) -> None:
        logout = subprocess.CompletedProcess(["codex", "logout"], 0, "Logged out\n", "")
        version = subprocess.CompletedProcess(["codex", "--version"], 0, "codex-cli 1.0\n", "")
        status = subprocess.CompletedProcess(["codex", "login", "status"], 1, "", "Not logged in")
        manager = codex_auth.CodexAuthManager("codex")

        with patch.object(codex_auth, "_run_codex", side_effect=[logout, version, status]) as run:
            snapshot = manager.logout()

        self.assertEqual(run.call_args_list[0].args[1], ["logout"])
        self.assertFalse(snapshot["authenticated"])
        self.assertEqual(snapshot["phase"], "signed_out")

    def test_logout_failure_does_not_report_success(self) -> None:
        logout = subprocess.CompletedProcess(
            ["codex", "logout"],
            1,
            "",
            "credential store is unavailable",
        )
        manager = codex_auth.CodexAuthManager("codex")

        with patch.object(codex_auth, "_run_codex", return_value=logout):
            with self.assertRaisesRegex(RuntimeError, "credential store is unavailable"):
                manager.logout()

    def test_terminal_escape_sequences_are_removed(self) -> None:
        self.assertEqual(codex_auth._clean_output("\x1b[32mREADY\x1b[0m\n"), "READY")


if __name__ == "__main__":
    unittest.main()
