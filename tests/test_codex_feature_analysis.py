"""Codex-backed Feature analysis uses the selected builder model and bounded requests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from game_pipeline.codex_cli.config import CodexHarnessSettings
from game_pipeline.codex_cli.structured_json_client import CodexStructuredJsonClient
from game_pipeline.condition_feature_analysis import (
    ConditionFeatureAnalyzer,
    create_condition_feature_analyzer_from_environment,
)
from game_pipeline.genre_feature_enricher import (
    GenreFeatureEnricher,
    create_genre_feature_enricher_from_environment,
)


def test_codex_client_uses_builder_model_and_read_only_project(tmp_path: Path) -> None:
    settings = CodexHarnessSettings(
        executable=tmp_path / "codex.exe",
        model="gpt-5.6-luna",
        reasoning_effort="medium",
        invocation_timeout_seconds=600,
        total_timeout_seconds=1200,
        max_repairs=0,
    )
    client = CodexStructuredJsonClient(tmp_path, "condition_feature_analysis", "ROLE_MODEL")
    with (
        patch.dict("os.environ", {"ROLE_MODEL": "builder"}),
        patch.object(CodexHarnessSettings, "from_environment", return_value=settings),
        patch("game_pipeline.codex_cli.structured_json_client.CodexCliRunner") as runner,
    ):
        runner.return_value.run.return_value = SimpleNamespace(final_response={"features": []})
        assert client.generate_json("condition", {"type": "object"}) == {"features": []}
    assert runner.call_args.args[0].model == "gpt-5.6-luna"
    assert runner.return_value.run.call_args.kwargs["sandbox"] == "read-only"
    assert runner.return_value.run.call_args.kwargs["project_root"] == tmp_path


def test_codex_feature_factories_do_not_require_localai(tmp_path: Path) -> None:
    with patch.dict(
        "os.environ",
        {
            "MAINFLOW_CONDITION_FEATURE_PROVIDER": "codex_cli",
            "MAINFLOW_GENRE_FEATURE_PROVIDER": "codex_cli",
        },
    ):
        condition = create_condition_feature_analyzer_from_environment(tmp_path)
        genre = create_genre_feature_enricher_from_environment(tmp_path)
    assert isinstance(condition.client, CodexStructuredJsonClient)
    assert isinstance(genre.client, CodexStructuredJsonClient)


def test_codex_condition_groups_long_prompt() -> None:
    class EmptyClient:
        def generate_json(self, prompt, schema):  # noqa: ANN001, ANN201
            return {"features": []}

    condition = "\n".join(f"기능 {index}을 제공한다." for index in range(1, 10))
    result = ConditionFeatureAnalyzer(EmptyClient(), "codex_cli").analyze(
        genre="뱀서류",
        viewpoint="탑다운",
        condition=condition,
        detected_features=[
            {
                "feature_id": "base-01",
                "name": "이동",
                "description": "플레이어가 움직인다.",
                "source_text": "플레이어 이동",
            }
        ],
    )
    assert result.report["request_count"] == 3


def test_codex_genre_groups_dependencies() -> None:
    class EmptyClient:
        def generate_json(self, prompt, schema):  # noqa: ANN001, ANN201
            return {"features": []}

    features = [
        {
            "feature_id": f"feature-{index:02d}",
            "name": f"기능 {index}",
            "description": f"기능 {index} 동작",
            "source_text": f"기능 {index}",
        }
        for index in range(17)
    ]
    result = GenreFeatureEnricher(EmptyClient(), "codex_cli").enrich(
        genre="뱀서류",
        viewpoint="탑다운",
        user_condition="플레이어가 생존한다.",
        core_loop="생존",
        existing_features=features,
    )
    assert result.report["request_count"] == 4
