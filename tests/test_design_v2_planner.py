from __future__ import annotations

import copy
import os
import unittest
from collections.abc import Mapping
from typing import Any
from unittest.mock import patch

from game_pipeline.design_catalog import normalize_game_spec
from game_pipeline.design_v2 import build_design_v2, validate_design_v2
from game_pipeline.design_v2_planner import (
    REVISION_STAGE,
    STAGE_ORDER,
    StagedDesignV2Planner,
    _coerce_to_baseline_shape,
    _schema_for,
    create_design_v2_planner_from_environment,
)
from game_pipeline.gemini_feature_generator import LocalAIJsonClient


class QueuedStructuredClient:
    def __init__(self, payloads: list[Mapping[str, Any]]) -> None:
        self.payloads = payloads
        self.prompts: list[str] = []

    def generate_json(
        self,
        prompt: str,
        schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        self.prompts.append(prompt)
        return self.payloads[len(self.prompts) - 1]


class StagedDesignV2PlannerTest(unittest.TestCase):
    def test_coerces_numeric_strings_without_changing_text_fields(self) -> None:
        result = _coerce_to_baseline_shape(
            {"height": "1.25", "count": "3", "title": "3"},
            {"height": 1.0, "count": 1, "title": "baseline"},
        )

        self.assertEqual(result, {"height": 1.25, "count": 3, "title": "3"})

    def test_schema_uses_later_sibling_to_type_initially_empty_hazard_array(self) -> None:
        level_plan = build_design_v2(
            normalize_game_spec("플랫포머"),
            "적과 가시를 피해 보석을 모은다.",
        )["level_plan"]

        schema = _schema_for(level_plan)
        hazard_items = schema["properties"]["zones"]["items"]["properties"]["hazards"]["items"]

        self.assertEqual(hazard_items["type"], "object")
        self.assertIn("placement_id", hazard_items["properties"])

    def test_schema_gives_globally_empty_array_an_explicit_item_type(self) -> None:
        schema = _schema_for({"values": []})

        values = schema["properties"]["values"]
        self.assertEqual(values["maxItems"], 0)
        self.assertEqual(values["items"], {"type": "string"})

    def setUp(self) -> None:
        self.spec = normalize_game_spec("플랫포머")
        self.intent = "벽을 타고 공중 대시로 세 구역을 돌파한다."
        self.baseline = build_design_v2(self.spec, self.intent)

    def customized_stage(self, stage: str) -> dict[str, Any]:
        response = copy.deepcopy(self.baseline[stage])  # type: ignore[literal-required]
        if stage == "game_design":
            response["title"] = "바람 절벽의 대시"
            response["differentiators"][0] = "벽 타기로 상승 기류를 만들고 공중 대시로 연결"
        elif stage == "system_design":
            response["resources"][0] = "air dash charge"
            response["progression"][0] = "wall route mastery"
        elif stage == "content_plan":
            response["enemies"][0]["role"] = "벽 타기 경로를 차단해 공중 대시 전환 유도"
            response["final_goal"] = "세 구역의 상승 기류를 활성화하고 절벽 정상에 도달"
        elif stage == "level_plan":
            response["zones"][0]["title"] = "상승 기류 훈련장"
            response["zones"][0]["challenge"] = "낮은 벽을 타고 첫 공중 대시 지점에 착지"
        elif stage == "balance_plan":
            response["formulas"][0] = "dash_distance = move_speed * 0.45"
            response["difficulty_curve"][0] = "zone 1: wall climb and one safe air dash"
        elif stage == "presentation_plan":
            response["camera_effects"][0] = "vertical lead while wall climbing"
            response["particle_requests"][0] = "air dash wind trail"
        elif stage == "validation_plan":
            response["scenarios"][0]["title"] = "벽 타기와 공중 대시로 완주"
            response["scenarios"][0]["steps"][0] = "spawn beside tutorial wall"
        else:
            self.fail(f"unsupported test stage: {stage}")
        return response

    def test_local_provider_uses_gemma_role_model(self) -> None:
        with patch.dict(
            os.environ,
            {
                "MAINFLOW_DESIGN_V2_PROVIDER": "local",
                "LOCAL_LLM_BASE_URL": "http://local-ai:8080/v1",
                "LOCAL_LLM_MODEL": "qwen-coder",
                "LLM_DESIGN_V2_MODEL": "gemma4-12b-it-qat-q4-0",
            },
            clear=True,
        ):
            planner = create_design_v2_planner_from_environment()

        self.assertIsNotNone(planner)
        self.assertIsInstance(planner.client, LocalAIJsonClient)  # type: ignore[union-attr]
        self.assertEqual(planner.client.model, "gemma4-12b-it-qat-q4-0")  # type: ignore[union-attr]

    def test_generates_seven_documents_then_revises_platformer_level(self) -> None:
        payloads = [self.customized_stage(stage) for stage in STAGE_ORDER]
        payloads.append(self.customized_stage("level_plan"))
        client = QueuedStructuredClient(payloads)
        planner = StagedDesignV2Planner(client, "local")

        result = planner.generate(
            self.spec,
            self.intent,
            ["platformer_movement", "goal_system"],
        )

        self.assertNotEqual(result, self.baseline)
        self.assertEqual(len(client.prompts), 8)
        self.assertIn("game director", client.prompts[0])
        self.assertIn("critical playtest lead", client.prompts[-2])
        self.assertIn("UPSTREAM", client.prompts[-2])
        self.assertIn("IMPLEMENTATION_INDEX", client.prompts[0])
        self.assertIn("RUNTIME_INVARIANTS", client.prompts[0])
        self.assertIn("PlatformerMovementModule", client.prompts[0])
        self.assertIn("GoalSystemModule", client.prompts[0])
        self.assertIn("senior 2D platformer director", client.prompts[-1])
        self.assertIn("validation_plan", client.prompts[-1])
        self.assertIn("constraint example, not an answer to copy", client.prompts[0])
        self.assertNotIn("SAFE_BASELINE", client.prompts[0])
        self.assertTrue(
            all(report["changed_leaf_count"] >= 2 for report in planner.customization_reports)
        )
        self.assertTrue(
            all(not report["used_fallback"] for report in planner.customization_reports)
        )

    def test_rejects_zero_starting_player_health(self) -> None:
        invalid = copy.deepcopy(self.baseline)
        player_health = next(
            item for item in invalid["balance_plan"]["stats"] if item["stat_id"] == "player_health"
        )
        player_health["initial"] = 0

        with self.assertRaisesRegex(ValueError, "player_health must start positive"):
            validate_design_v2(invalid)

    def test_survivor_fallback_is_a_complete_survival_loop(self) -> None:
        survivor = build_design_v2(
            normalize_game_spec("뱀서류"),
            "적을 처치해 경험치 보석을 모으고 보스를 처치한다.",
        )

        validate_design_v2(survivor)
        stats = {item["stat_id"]: item for item in survivor["balance_plan"]["stats"]}
        scenario_ids = {
            scenario["scenario_id"] for scenario in survivor["validation_plan"]["scenarios"]
        }
        self.assertGreater(stats["player_health"]["initial"], 0)
        self.assertEqual(len(survivor["level_plan"]["zones"]), 3)
        self.assertGreaterEqual(len(survivor["content_plan"]["enemies"]), 3)
        self.assertIn("survivor_spawn_chase_attack_progression", scenario_ids)
        self.assertIn("level_up_choice", survivor["presentation_plan"]["ui_screens"])

    def test_exact_baseline_copy_is_rewritten_once(self) -> None:
        payloads = [copy.deepcopy(self.baseline["game_design"])]
        payloads.extend(self.customized_stage(stage) for stage in STAGE_ORDER)
        payloads.append(self.customized_stage("level_plan"))
        client = QueuedStructuredClient(payloads)
        planner = StagedDesignV2Planner(client, "local")

        with patch.dict(os.environ, {"MAINFLOW_DESIGN_V2_CUSTOMIZATION_RETRIES": "1"}):
            result = planner.generate(self.spec, self.intent)

        self.assertEqual(result["game_design"]["title"], "바람 절벽의 대시")
        self.assertEqual(len(client.prompts), 9)
        self.assertIn("copied the safety example too closely", client.prompts[1])
        self.assertIn("REJECTED_COPY", client.prompts[1])
        self.assertEqual(planner.customization_reports[0]["attempts"], 2)
        self.assertFalse(planner.customization_reports[0]["used_fallback"])

    def test_repeated_baseline_copy_uses_safe_fallback(self) -> None:
        payloads = [
            copy.deepcopy(self.baseline["game_design"]),
            copy.deepcopy(self.baseline["game_design"]),
        ]
        payloads.extend(self.customized_stage(stage) for stage in STAGE_ORDER[1:])
        payloads.append(self.customized_stage("level_plan"))
        planner = StagedDesignV2Planner(QueuedStructuredClient(payloads), "local")

        with patch.dict(os.environ, {"MAINFLOW_DESIGN_V2_CUSTOMIZATION_RETRIES": "1"}):
            result = planner.generate(self.spec, self.intent)

        self.assertEqual(result["game_design"], self.baseline["game_design"])
        self.assertEqual(planner.fallback_stages, ["game_design"])
        self.assertTrue(planner.customization_reports[0]["used_fallback"])

    def test_invalid_level_stage_falls_back_without_discarding_other_stages(self) -> None:
        payloads = [self.customized_stage(stage) for stage in STAGE_ORDER]
        payloads.append(copy.deepcopy(self.baseline["level_plan"]))
        level_index = STAGE_ORDER.index("level_plan")
        payloads[level_index]["zones"] = payloads[level_index]["zones"][:1]  # type: ignore[index]
        planner = StagedDesignV2Planner(QueuedStructuredClient(payloads), "local")

        result = planner.generate(self.spec, self.intent)

        self.assertEqual(result["level_plan"], self.baseline["level_plan"])
        self.assertEqual(planner.fallback_stages, ["level_plan"])

    def test_invalid_balance_stage_falls_back_without_discarding_other_stages(self) -> None:
        payloads = [self.customized_stage(stage) for stage in STAGE_ORDER]
        balance_index = STAGE_ORDER.index("balance_plan")
        player_health = next(
            item
            for item in payloads[balance_index]["stats"]  # type: ignore[index]
            if item["stat_id"] == "player_health"
        )
        player_health["initial"] = 0
        payloads.append(self.customized_stage("level_plan"))
        planner = StagedDesignV2Planner(QueuedStructuredClient(payloads), "local")

        result = planner.generate(self.spec, self.intent)

        self.assertEqual(result["balance_plan"], self.baseline["balance_plan"])
        self.assertEqual(result["game_design"]["title"], "바람 절벽의 대시")
        self.assertIn("balance_plan", planner.fallback_stages)

    def test_openai_stage_retries_semantic_validation_error_once(self) -> None:
        payloads = [self.customized_stage(stage) for stage in STAGE_ORDER]
        balance_index = STAGE_ORDER.index("balance_plan")
        invalid_balance = payloads[balance_index]
        player_health = next(
            item
            for item in invalid_balance["stats"]  # type: ignore[index]
            if item["stat_id"] == "player_health"
        )
        player_health["initial"] = 0
        payloads.insert(balance_index + 1, self.customized_stage("balance_plan"))
        payloads.append(self.customized_stage("level_plan"))
        client = QueuedStructuredClient(payloads)
        planner = StagedDesignV2Planner(client, "openai")

        result = planner.generate(self.spec, self.intent)

        repaired_health = next(
            item for item in result["balance_plan"]["stats"] if item["stat_id"] == "player_health"
        )
        self.assertGreater(repaired_health["initial"], 0)
        repair_prompt = client.prompts[balance_index + 1]
        self.assertIn("VALIDATION_ERROR=player_health must start positive", repair_prompt)
        self.assertIn("REJECTED_RESPONSE", repair_prompt)
        self.assertNotIn("balance_plan", planner.fallback_stages)

    def test_invalid_revision_keeps_the_last_validated_level(self) -> None:
        payloads = [self.customized_stage(stage) for stage in STAGE_ORDER]
        invalid_revision = copy.deepcopy(self.baseline["level_plan"])
        invalid_revision["zones"] = invalid_revision["zones"][:1]
        payloads.append(invalid_revision)
        planner = StagedDesignV2Planner(QueuedStructuredClient(payloads), "local")

        result = planner.generate(self.spec, self.intent)

        self.assertEqual(result["level_plan"], self.customized_stage("level_plan"))
        self.assertEqual(planner.fallback_stages, [REVISION_STAGE])

    def test_validation_plan_rejects_non_executable_scenario_ids(self) -> None:
        invalid = copy.deepcopy(self.baseline)
        invalid["validation_plan"]["scenarios"][0]["scenario_id"] = "free_form_test"

        with self.assertRaisesRegex(ValueError, "executable platformer scenarios"):
            validate_design_v2(invalid)

    def test_non_platformer_level_rejects_incomplete_generated_zone(self) -> None:
        survivor_spec = normalize_game_spec("뱀서류")
        invalid = build_design_v2(survivor_spec, "적 무리에서 생존한다.")
        invalid["level_plan"]["zones"] = [{}]  # type: ignore[list-item]

        with self.assertRaisesRegex(ValueError, "zone 0 is missing fields"):
            validate_design_v2(invalid)


if __name__ == "__main__":
    unittest.main()
