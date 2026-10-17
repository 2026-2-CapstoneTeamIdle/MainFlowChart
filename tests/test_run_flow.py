from __future__ import annotations

import io
import unittest
from unittest.mock import MagicMock, patch

from mainflow.run_flow import main


class RunFlowExitTest(unittest.TestCase):
    def run_cli(self, status):
        state = {
            key: key
            for key in (
                "project_id",
                "game_validation_result",
                "image_draft",
                "sound_draft",
                "final_validation_result",
            )
        }
        manager = MagicMock()
        manager.read_json.side_effect = [{"status": "passed"}, {}, {}, {"status": status}]
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


if __name__ == "__main__":
    unittest.main()
