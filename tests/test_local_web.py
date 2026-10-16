"""Local web API tests with a stub graph (no LLM, Unity or MCP server needed)."""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient
except ImportError:  # the "web" dependency group is not installed
    TestClient = None  # type: ignore[assignment,misc]

from mainflow.ArtifactManager import ArtifactManager

LOCAL_WEB = Path(__file__).resolve().parents[1] / "CI" / "CD" / "LocalWeb"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


class StubGraph:
    """Two nodes that behave like the real ones: create a project and write artifacts."""

    def __init__(self, calls: list[dict]) -> None:
        self.calls = calls

    def get_graph(self):
        return type(
            "G", (), {"nodes": {"__start__": 0, "parse_input": 1, "validate_game": 2, "__end__": 3}}
        )()

    def stream(self, state, stream_mode):
        assert stream_mode == "updates"
        self.calls.append(dict(state))
        manager = ArtifactManager()
        project_id = manager.create_project()
        yield {"parse_input": {"project_id": project_id}}
        reference = manager.write_json(
            project_id,
            "validation",
            "game_validation_result.json",
            {"status": "passed", "issues": []},
            producer="validate_game",
        )
        yield {"validate_game": {"game_validation_result": reference}}


class FailingGraph(StubGraph):
    def stream(self, state, stream_mode):
        yield {"parse_input": {}}
        raise RuntimeError("node exploded")


@unittest.skipIf(TestClient is None, "install the web group: uv sync --group web")
class LocalWebTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.previous_workspace = os.environ.get("MAINFLOW_WORKSPACE")
        os.environ["MAINFLOW_WORKSPACE"] = self.tmp.name
        sys.path.insert(0, str(LOCAL_WEB))
        self.app_module = importlib.import_module("app")
        runner_module = importlib.import_module("workflow_runner")
        self.calls: list[dict] = []
        self.app_module.runner = runner_module.WorkflowRunner(lambda: StubGraph(self.calls))
        self.client = TestClient(self.app_module.app)
        self.form = {
            "image_style": "Pixel Art",
            "mood_style": "Fantasy",
            "genre": "플랫포머",
            "viewpoint": "사이드뷰",
            "condition": "공격과 8방향 이동이 가능한 게임",
        }

    def tearDown(self) -> None:
        sys.path.remove(str(LOCAL_WEB))
        if self.previous_workspace is None:
            os.environ.pop("MAINFLOW_WORKSPACE", None)
        else:
            os.environ["MAINFLOW_WORKSPACE"] = self.previous_workspace
        self.tmp.cleanup()

    def wait(self, run_id: str) -> dict:
        for _ in range(100):
            run = self.client.get(f"/api/runs/{run_id}").json()
            if run["status"] in ("succeeded", "failed"):
                return run
            time.sleep(0.02)
        self.fail("run did not finish")

    def test_health_reports_connected_workflow(self) -> None:
        health = self.client.get("/api/health").json()
        self.assertEqual(health["workflow"], "connected")
        workflow = self.client.get("/api/workflow").json()
        self.assertEqual(workflow["nodes"], ["parse_input", "validate_game"])
        self.assertIn("Custom", workflow["options"]["image_style"])

    def test_run_streams_nodes_and_exposes_artifacts(self) -> None:
        response = self.client.post("/api/runs", data=self.form)
        self.assertEqual(response.status_code, 202)
        run = self.wait(response.json()["run_id"])
        self.assertEqual(run["status"], "succeeded")
        self.assertEqual(run["outcome"], "passed")
        self.assertEqual([e["node"] for e in run["events"]], ["parse_input", "validate_game"])
        self.assertEqual(self.calls[0]["genre"], "플랫포머")

        artifacts = self.client.get(f"/api/runs/{run['run_id']}/artifacts").json()
        self.assertEqual(artifacts[0]["relative_path"], "validation/game_validation_result.json")
        download = self.client.get(
            f"/api/runs/{run['run_id']}/artifacts/{artifacts[0]['artifact_id']}"
        )
        self.assertEqual(download.status_code, 200)
        self.assertIn(b'"passed"', download.content)
        self.assertEqual(
            self.client.get(f"/api/runs/{run['run_id']}/artifacts/nope").status_code, 404
        )

    def test_invalid_requests_are_rejected_before_running(self) -> None:
        bad_genre = self.client.post("/api/runs", data={**self.form, "genre": "레이싱"})
        self.assertEqual(bad_genre.status_code, 422)
        empty = self.client.post("/api/runs", data={**self.form, "condition": "   "})
        self.assertEqual(empty.status_code, 422)
        custom_without_file = self.client.post(
            "/api/runs", data={**self.form, "image_style": "Custom"}
        )
        self.assertEqual(custom_without_file.status_code, 422)
        fake_png = self.client.post(
            "/api/runs",
            data={**self.form, "image_style": "Custom"},
            files={"custom_image": ("ref.png", b"not an image", "image/png")},
        )
        self.assertEqual(fake_png.status_code, 422)
        self.assertEqual(self.calls, [])

    def test_custom_image_is_saved_and_passed_to_the_graph(self) -> None:
        response = self.client.post(
            "/api/runs",
            data={**self.form, "image_style": "Custom"},
            files={"custom_image": ("ref.png", PNG, "image/png")},
        )
        self.assertEqual(response.status_code, 202)
        self.wait(response.json()["run_id"])
        saved = Path(self.calls[0]["custom_image_path"])
        self.assertTrue(saved.is_file())
        self.assertTrue(saved.is_relative_to(Path(self.tmp.name)))
        self.assertEqual(saved.read_bytes(), PNG)

    def test_node_failure_is_reported(self) -> None:
        runner_module = importlib.import_module("workflow_runner")
        self.app_module.runner = runner_module.WorkflowRunner(lambda: FailingGraph(self.calls))
        run = self.wait(self.client.post("/api/runs", data=self.form).json()["run_id"])
        self.assertEqual(run["status"], "failed")
        self.assertIn("node exploded", run["error"])


if __name__ == "__main__":
    unittest.main()
