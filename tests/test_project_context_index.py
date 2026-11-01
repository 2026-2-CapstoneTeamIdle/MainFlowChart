from __future__ import annotations

import json
import unittest
from pathlib import Path

from game_pipeline.feature_contract import build_generation_contract
from game_pipeline.project_context_index import (
    build_project_context_index,
    compact_api_contract,
)


class ProjectContextIndexTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime = (
            Path(__file__).resolve().parent.parent
            / "unity_template"
            / "Assets"
            / "GameTemplate"
            / "Runtime"
        )

    def test_indexes_exact_classes_apis_events_and_modules(self) -> None:
        index = build_project_context_index(self.runtime)
        contract = compact_api_contract(index, selected_module_ids=["wave_spawner"])
        types = contract["project_types"]

        binding_members = {
            member["name"] for member in types["GeneratedFeatureBindingContext"]["public_api"]
        }
        self.assertTrue({"Player", "Modules", "GetModule"}.issubset(binding_members))

        health = types["HealthComponent"]
        health_members = {member["name"]: member for member in health["public_api"]}
        self.assertIn("Current", health_members)
        self.assertFalse(health_members["Current"]["writable"])
        self.assertIn("Damage", health_members)
        self.assertNotIn("CurrentHealth", health_members)
        self.assertEqual(
            {event["name"] for event in health["events"]},
            {"Changed", "Died"},
        )

        wave = types["WaveSpawnerModule"]
        self.assertEqual(wave["module_id"], "wave_spawner")
        self.assertIn("WaveNumber", {member["name"] for member in wave["public_api"]})
        self.assertNotIn("WaveProgress", {member["name"] for member in wave["public_api"]})
        self.assertEqual(
            index["module_types"]["wave_spawner"],
            "TeamIdle.GameTemplate.TowerDefense.WaveSpawnerModule",
        )

    def test_preserves_requirement_ids_and_original_request(self) -> None:
        index = build_project_context_index(
            self.runtime,
            request={"condition": "벽을 타고 목표에 도달", "genre": "플랫포머"},
            design={
                "game_spec": {
                    "genre": "platformer",
                    "features": [{"feature_id": "wall_climb", "description": "벽 타기"}],
                    "mechanics": [{"mechanic_id": "wall_climb", "description": "벽 타기"}],
                    "win_conditions": ["goal_reached"],
                    "lose_conditions": ["health_zero"],
                    "asset_requirements": [{"asset_id": "player", "asset_type": "image"}],
                },
                "selected_modules": ["platformer_movement"],
                "unsupported_mechanics": ["wall_climb"],
                "design_v2": {
                    "system_design": {
                        "event_connections": [
                            {
                                "event_id": "wall_contact",
                                "producer": "wall_sensor",
                                "consumers": ["wall_climb"],
                            }
                        ]
                    },
                    "validation_plan": {
                        "required_feature_bindings": [
                            {"feature_id": "wall_climb", "target": "player"}
                        ],
                        "scenarios": [{"scenario_id": "reach_goal"}],
                    },
                },
            },
            logic_analysis={"criteria": [{"criterion_id": "feature.wall_climb"}]},
        )

        requirements = index["requirements"]
        self.assertEqual(requirements["user_condition"], "벽을 타고 목표에 도달")
        self.assertEqual(requirements["features"][0]["feature_id"], "wall_climb")
        self.assertEqual(requirements["criteria"][0]["criterion_id"], "feature.wall_climb")
        self.assertEqual(requirements["system_events"][0]["event_id"], "wall_contact")
        self.assertEqual(requirements["required_feature_bindings"][0]["feature_id"], "wall_climb")
        self.assertEqual(requirements["playtest_scenarios"][0]["scenario_id"], "reach_goal")

    def test_tower_defense_prompt_contract_retrieves_only_relevant_signatures(self) -> None:
        selected = [
            "game_bootstrap",
            "game_state_store",
            "event_rule_engine",
            "scene_flow_manager",
            "input_adapter",
            "save_system",
            "asset_registry",
            "audio_manager",
            "ui_router",
            "validation_probe",
            "wave_spawner",
            "projectile_system",
            "tower_targeting_system",
            "health_damage_system",
            "economy_system",
            "base_defense_system",
        ]
        contract = build_generation_contract(
            selected,
            requirement_text=(
                "웨이브가 진행될수록 적 체력과 이동속도가 증가하고 기지 체력이 0이면 패배"
            ),
        )
        serialized = json.dumps(contract, ensure_ascii=False)

        self.assertLess(len(serialized), 12_000)
        self.assertIn("wave_spawner", contract["retrieved_module_ids"])
        self.assertIn("base_defense_system", contract["retrieved_module_ids"])
        self.assertIn("WaveSpawnerModule", contract["project_types"])
        self.assertNotIn("AudioManagerModule", contract["project_types"])

    def test_survivor_korean_requirement_retrieves_progression_apis(self) -> None:
        selected = [
            "top_down_movement",
            "health_damage_system",
            "enemy_spawn_system",
            "game_timer",
            "experience_system",
            "upgrade_selection_system",
            "item_collection_system",
        ]

        contract = build_generation_contract(
            selected,
            requirement_text=(
                "적이 떨어뜨린 경험치 보석을 수집해 레벨업하고 특전 하나를 선택한다."
            ),
            max_module_types=6,
        )

        self.assertIn("experience_system", contract["retrieved_module_ids"])
        self.assertIn("upgrade_selection_system", contract["retrieved_module_ids"])
        self.assertIn("item_collection_system", contract["retrieved_module_ids"])
        self.assertIn("ExperienceSystemModule", contract["project_types"])

    def test_disabled_compatibility_shell_does_not_replace_active_survivor_apis(self) -> None:
        index = build_project_context_index(self.runtime)
        enemy_types = [item for item in index["types"] if item["name"] == "EnemySpawnSystemModule"]
        movement_types = [
            item for item in index["types"] if item["name"] == "TopDownMovementModule"
        ]

        self.assertEqual(len(enemy_types), 1)
        self.assertEqual(len(movement_types), 1)
        self.assertIn(
            "SpawnAt",
            {member["name"] for member in enemy_types[0]["members"]},
        )
        self.assertIn(
            "ConfigureDifficulty",
            {member["name"] for member in enemy_types[0]["members"]},
        )
        self.assertIn(
            "MoveSpeed",
            {member["name"] for member in movement_types[0]["members"]},
        )

        contract = build_generation_contract(
            ["enemy_spawn_system", "game_timer", "health_damage_system"],
            requirement_text="시간에 따라 적 체력이 증가하고 보스를 생성한다.",
        )
        enemy_api = contract["project_types"]["EnemySpawnSystemModule"]["api"]
        self.assertTrue(any("SpawnAt" in signature for signature in enemy_api))
        self.assertTrue(any("ConfigureDifficulty" in signature for signature in enemy_api))


if __name__ == "__main__":
    unittest.main()
