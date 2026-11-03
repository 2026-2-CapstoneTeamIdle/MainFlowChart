from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from game_pipeline.pipeline_error_log import append_pipeline_error
from mainflow.ArtifactManager import ArtifactManager


class PipelineErrorLogTests(unittest.TestCase):
    def test_appends_failure_and_recovery_rows_to_project_validation_log(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory) / "workspace"
            with patch.dict(os.environ, {"MAINFLOW_WORKSPACE": str(workspace)}):
                project_id = ArtifactManager().create_project()

                self.assertTrue(
                    append_pipeline_error(
                        "condition_feature_analysis",
                        "MAX_OUTPUT_TOKEN_EXCEEDED",
                        "model=gemma|attempt=1\noutput was truncated",
                        project_id=project_id,
                    )
                )
                self.assertTrue(
                    append_pipeline_error(
                        "condition_feature_analysis",
                        "STRUCTURED_OUTPUT_RECOVERED",
                        "recovered on attempt 2/3",
                        project_id=project_id,
                    )
                )

                log_path = workspace / project_id / "validation/errorlog.md"
                content = log_path.read_text(encoding="utf-8")

        self.assertIn("날짜|시점|이유|상세", content)
        self.assertIn("condition_feature_analysis", content)
        self.assertIn("MAX_OUTPUT_TOKEN_EXCEEDED", content)
        self.assertIn("STRUCTURED_OUTPUT_RECOVERED", content)
        self.assertIn(r"model=gemma\|attempt=1<br>output was truncated", content)
        self.assertIn("+09:00", content)


if __name__ == "__main__":
    unittest.main()
