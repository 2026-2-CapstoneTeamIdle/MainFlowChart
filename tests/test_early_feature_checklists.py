from pathlib import Path
from unittest.mock import Mock, patch

from game_pipeline.dynamic_feature_checklist import (
    DynamicFeatureChecklistGenerator,
    create_checklist_generator_from_environment,
    load_generated_checklist,
    persist_generated_checklist,
)
from mainflow.nodes.logic_analysis import logic_analysis_node
from game_pipeline.feature_checklist_validation import FeatureChecklistWorkflow
from tests.test_dynamic_feature_checklist import FakeStructuredClient, _logic_analysis


def test_approved_web_features_publish_checklists_before_implementation(tmp_path, monkeypatch):
    logic = _logic_analysis()
    manager = Mock()
    manager.ensure_project.return_value = tmp_path
    manager.read_json.side_effect = [
        {
            "condition": "플레이어가 점프한다",
            "genre": logic["genre"],
            "viewpoint": logic["viewpoint"],
            "mood_style": "Fantasy",
            "image_style": "Pixel Art",
        },
        {"features": logic["features"]},
    ]
    report = tmp_path / "project_id.txt"
    monkeypatch.setenv("MAINFLOW_EARLY_FEATURE_CHECKLISTS", "1")
    monkeypatch.setenv("MAINFLOW_FEATURE_CHECKLIST_PROJECT_REPORT", str(report))
    generated = Mock()
    generated.feature_checklists = [Mock(feature_id="feature-01", feature_name="점프")]

    def generate(**kwargs):
        assert report.read_text() == "20261118_01"
        kwargs["on_feature_ready"](generated)
        return generated

    generator = Mock()
    generator.generate.side_effect = generate
    with (
        patch("mainflow.nodes.logic_analysis.ArtifactManager", return_value=manager),
        patch("mainflow.nodes.logic_analysis._load_approved_logic_analysis", return_value=logic),
        patch(
            "game_pipeline.dynamic_feature_checklist.create_checklist_generator_from_environment",
            return_value=generator,
        ),
        patch("game_pipeline.dynamic_feature_checklist.persist_generated_checklist") as persist,
    ):
        logic_analysis_node({"project_id": "20261118_01", "parsed_request": {}, "analysis": {}})
    persist.assert_called_once_with(generated, workspace_root=tmp_path)
    assert generator.generate.call_args.kwargs["logic_analysis"]["features"] == logic["features"]


def test_checklists_publish_progress_without_creating_unity_project(tmp_path):
    criteria = [
        {
            "feature_ids": ["feature-01", "requirement-dependency-01"],
            "title": f"Check {i}",
            "category": "runtime",
            "setup": "prepare",
            "action": "jump",
            "expected": "moves upward",
            "evidence": "position",
        }
        for i in range(30)
    ]
    published = []

    def publish(checklist):
        persist_generated_checklist(checklist, workspace_root=tmp_path)
        published.append(len(load_generated_checklist(tmp_path).feature_checklists))

    DynamicFeatureChecklistGenerator(FakeStructuredClient({"criteria": criteria}), "test").generate(
        project_id="20261118_01",
        logic_analysis=_logic_analysis(),
        source_root=Path("missing"),
        on_feature_ready=publish,
    )
    assert published == [1, 2]
    assert not (tmp_path / "Assets").exists()

    original = (tmp_path / "validation/feature_checklists/generated/checklist.json").read_bytes()
    checklist_factory = Mock(side_effect=AssertionError("Checklist must not be regenerated"))
    test_factory = Mock()
    test_factory.return_value.generate.return_value = "// generated test"
    workflow = FeatureChecklistWorkflow(
        unity_editor=tmp_path / "Unity",
        timeout_seconds=10,
        checklist_generator_factory=checklist_factory,
        test_generator_factory=test_factory,
    )
    checklist, _ = workflow._generate_dynamic_tests(
        project_id="20261118_01",
        logic_analysis=_logic_analysis(),
        project_root=tmp_path / "game",
        workspace_root=tmp_path,
        source_root=Path("missing"),
        compile_validation=Mock(return_value=Mock(status="passed", unity_log="ok")),
    )
    checklist_factory.assert_not_called()
    assert len(checklist.feature_checklists) == 2
    assert test_factory.return_value.generate.call_count == 2
    assert (
        tmp_path / "validation/feature_checklists/generated/checklist.json"
    ).read_bytes() == original


def test_codex_checklists_use_builder_model_instead_of_local_model(tmp_path, monkeypatch):
    monkeypatch.setenv("MAINFLOW_GAME_BUILDER", "codex_cli")
    monkeypatch.setenv("LLM_FEATURE_CHECKLIST_GENERATION_MODEL", "gemma4-12b-it-qat-q4-0")
    generator = create_checklist_generator_from_environment(tmp_path)
    assert generator.provider == "codex_cli"
    assert generator.client.model_environment == "MAINFLOW_CODEX_MODEL"
