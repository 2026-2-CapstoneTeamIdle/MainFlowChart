from __future__ import annotations

import copy
import unittest
from collections.abc import Mapping
from typing import Any

from game_pipeline.design_catalog import normalize_game_spec
from game_pipeline.design_v2 import build_design_v2, validate_design_v2
from game_pipeline.design_v2_planner import REVISION_STAGE, STAGE_ORDER, StagedDesignV2Planner


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
    def setUp(self) -> None:
        self.spec = normalize_game_spec("플랫포머")
        self.intent = "벽을 타고 공중 대시로 세 구역을 돌파한다."
        self.baseline = build_design_v2(self.spec, self.intent)

    def test_generates_seven_documents_then_revises_platformer_level(self) -> None:
        payloads = [copy.deepcopy(self.baseline[stage]) for stage in STAGE_ORDER]
        payloads.append(copy.deepcopy(self.baseline["level_plan"]))
        client = QueuedStructuredClient(payloads)

        result = StagedDesignV2Planner(client, "local").generate(self.spec, self.intent)

        self.assertEqual(result, self.baseline)
        self.assertEqual(len(client.prompts), 8)
        self.assertIn("game director", client.prompts[0])
        self.assertIn("critical playtest lead", client.prompts[-2])
        self.assertIn("UPSTREAM", client.prompts[-2])
        self.assertIn("senior 2D platformer director", client.prompts[-1])
        self.assertIn("validation_plan", client.prompts[-1])

    def test_invalid_level_stage_falls_back_without_discarding_other_stages(self) -> None:
        payloads = [copy.deepcopy(self.baseline[stage]) for stage in STAGE_ORDER]
        payloads.append(copy.deepcopy(self.baseline["level_plan"]))
        level_index = STAGE_ORDER.index("level_plan")
        payloads[level_index]["zones"] = payloads[level_index]["zones"][:1]  # type: ignore[index]
        planner = StagedDesignV2Planner(QueuedStructuredClient(payloads), "local")

        result = planner.generate(self.spec, self.intent)

        self.assertEqual(result["level_plan"], self.baseline["level_plan"])
        self.assertEqual(planner.fallback_stages, ["level_plan"])

    def test_invalid_revision_keeps_the_last_validated_level(self) -> None:
        payloads = [copy.deepcopy(self.baseline[stage]) for stage in STAGE_ORDER]
        invalid_revision = copy.deepcopy(self.baseline["level_plan"])
        invalid_revision["zones"] = invalid_revision["zones"][:1]
        payloads.append(invalid_revision)
        planner = StagedDesignV2Planner(QueuedStructuredClient(payloads), "local")

        result = planner.generate(self.spec, self.intent)

        self.assertEqual(result["level_plan"], self.baseline["level_plan"])
        self.assertEqual(planner.fallback_stages, [REVISION_STAGE])

    def test_validation_plan_rejects_non_executable_scenario_ids(self) -> None:
        invalid = copy.deepcopy(self.baseline)
        invalid["validation_plan"]["scenarios"][0]["scenario_id"] = "free_form_test"

        with self.assertRaisesRegex(ValueError, "executable platformer scenarios"):
            validate_design_v2(invalid)


if __name__ == "__main__":
    unittest.main()
