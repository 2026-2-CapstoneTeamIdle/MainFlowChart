from __future__ import annotations

import copy
import os
import unittest
from collections.abc import Mapping
from typing import Any
from unittest.mock import patch

from game_pipeline.blueprint_planner import (
    GameBlueprintPlanner,
    create_blueprint_planner_from_environment,
)
from game_pipeline.game_blueprint import build_game_blueprint
from game_pipeline.gemini_feature_generator import LocalAIJsonClient
from game_pipeline.design_catalog import normalize_game_spec


class FakeStructuredJsonClient:
    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.payload = payload
        self.calls = 0

    def generate_json(
        self,
        prompt: str,
        schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        self.calls += 1
        self.prompt = prompt
        self.schema = schema
        return self.payload


class BlueprintPlannerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = normalize_game_spec("플랫포머")
        self.intent = "용암 동굴에서 공중 대시로 탈출한다."
        self.fallback = build_game_blueprint(self.spec, self.intent)

    def test_valid_llm_blueprint_is_normalized_and_tagged_with_provider(self) -> None:
        payload = copy.deepcopy(self.fallback)
        for field in ("blueprint_version", "blueprint_id", "source", "title"):
            del payload[field]
        payload["summary"] = "용암 동굴의 분기형 플랫폼 스테이지를 돌파한다."
        payload["background_color_hex"] = "#ff4411"
        payload["entities"].append(
            {
                "entity_id": "lava_fall",
                "display_name": "용암 폭포",
                "archetype": "landmark",
                "position_x": 7,
                "position_y": 2,
                "scale_x": 1.5,
                "scale_y": 2.5,
                "color_hex": "#EE3311",
                "behavior_tags": ["decorative"],
            }
        )
        client = FakeStructuredJsonClient(payload)

        result = GameBlueprintPlanner(client, "local").generate(self.spec, self.intent)

        self.assertEqual(client.calls, 1)
        self.assertEqual(result["source"], "local")
        self.assertEqual(result["title"], self.spec["title"])
        self.assertEqual(result["background_color_hex"], "#FF4411")
        self.assertIn("lava_fall", [item["entity_id"] for item in result["entities"]])
        self.assertIn("player_anchor", [item["archetype"] for item in result["entities"]])
        self.assertIn("fallback_blueprint", client.prompt)

    def test_missing_required_archetype_is_rejected(self) -> None:
        payload = copy.deepcopy(self.fallback)
        for field in ("blueprint_version", "blueprint_id", "source", "title"):
            del payload[field]
        payload["content"] = payload["content"][1:]
        client = FakeStructuredJsonClient(payload)

        with self.assertRaisesRegex(ValueError, "required content archetype"):
            GameBlueprintPlanner(client, "local").generate(self.spec, self.intent)

    def test_default_provider_is_offline_deterministic(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(create_blueprint_planner_from_environment())

    def test_local_provider_uses_existing_localai_configuration(self) -> None:
        with patch.dict(
            os.environ,
            {
                "MAINFLOW_BLUEPRINT_PROVIDER": "local",
                "LOCAL_LLM_BASE_URL": "http://local-ai:8080/v1",
                "LOCAL_LLM_MODEL": "planner-test-model",
            },
            clear=True,
        ):
            planner = create_blueprint_planner_from_environment()

        self.assertIsNotNone(planner)
        self.assertIsInstance(planner.client, LocalAIJsonClient)
        self.assertEqual(planner.client.model, "planner-test-model")


if __name__ == "__main__":
    unittest.main()
