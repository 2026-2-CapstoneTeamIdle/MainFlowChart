from __future__ import annotations

import io
import unittest
from unittest.mock import MagicMock, patch

from mainflow.run_flow import configure_console_encoding, main


class ReconfigurableTextStream(io.TextIOWrapper):
    def close_without_closing_buffer(self):
        self.flush()
        self.detach()


class RunFlowExitTest(unittest.TestCase):
    def run_cli(self, status, ai_status="passed"):
        state = {
            key: key
            for key in (
                "project_id",
                "game_validation_result",
                "image_draft",
                "sound_draft",
                "final_validation_result",
                "game_validator_ai_result",
            )
        }
        manager = MagicMock()
        manager.read_json.side_effect = [
            {"status": "passed"},
            {},
            {},
            {"status": status},
            {"status": ai_status},
        ]
        with (
            patch("mainflow.run_flow.load_request", return_value={}),
            patch("mainflow.run_flow.build_graph") as graph,
            patch("mainflow.run_flow.ArtifactManager", return_value=manager),
            patch("sys.argv", ["mainflow"]),
            patch("sys.stdout", new_callable=io.StringIO),
            patch("sys.stderr", new_callable=io.StringIO),
        ):
            graph.return_value.invoke.return_value = state
            manager.ensure_project.return_value = "workspace/test"
            return main()

    def test_final_failure_sets_nonzero_exit_even_if_game_passed(self):
        self.assertEqual(self.run_cli("failed"), 1)

    def test_final_success_sets_zero_exit(self):
        self.assertEqual(self.run_cli("passed"), 0)

    def test_validator_ai_revision_sets_nonzero_exit(self):
        self.assertEqual(self.run_cli("passed", "needs_revision"), 1)

    def test_game_test_uses_asset_free_graph_and_both_validation_results(self):
        state = {
            "project_id": "20261031_01",
            "game_validation_result": "game-validation",
            "visual_validation_result": "visual-validation",
        }
        manager = MagicMock()
        manager.read_json.side_effect = [
            {"status": "passed"},
            {"status": "passed"},
        ]
        with (
            patch("mainflow.run_flow.load_request", return_value={}),
            patch("mainflow.run_flow.build_graph") as production_graph,
            patch("mainflow.run_flow.build_game_test_graph") as game_test_graph,
            patch("mainflow.run_flow.ArtifactManager", return_value=manager),
            patch("sys.argv", ["mainflow", "--game-test"]),
            patch("sys.stdout", new_callable=io.StringIO),
            patch("sys.stderr", new_callable=io.StringIO),
            patch.dict("os.environ", {}, clear=True),
        ):
            game_test_graph.return_value.invoke.return_value = state
            manager.ensure_project.return_value = "workspace/test"
            result = main()

        self.assertEqual(result, 0)
        game_test_graph.assert_called_once_with()
        production_graph.assert_not_called()

    def test_console_encoding_is_reconfigured_for_unicode_output(self):
        buffer = io.BytesIO()
        stream = ReconfigurableTextStream(buffer, encoding="cp949")
        try:
            with patch("sys.stdout", stream), patch("sys.stderr", io.StringIO()):
                configure_console_encoding()
                print("한글 — Unicode")
                stream.flush()

            self.assertEqual(buffer.getvalue().decode("utf-8").splitlines(), ["한글 — Unicode"])
        finally:
            stream.close_without_closing_buffer()


if __name__ == "__main__":
    unittest.main()
