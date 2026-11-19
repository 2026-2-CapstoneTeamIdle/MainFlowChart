from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from game_pipeline.requirement_constraints import (
    explicit_exclusions,
    feature_conflict_reason,
    filter_conflicting_features,
    filter_genre_conflicting_features,
    forbids_player_projectiles,
)
from game_pipeline.unity_project_validator import UnityProjectValidator, UnityValidationOutcome


class RequirementConstraintsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.condition = (
            "근접 적은 플레이어를 공격하고 원거리 적은 투사체를 발사한다. "
            "플레이어는 대시 중 적을 통과할 수 있지만 공격 능력은 없다. "
            "적을 직접 처치하기보다 피하거나 함정으로 유인해야 한다."
        )

    def test_detects_explicit_player_attack_exclusion(self) -> None:
        self.assertEqual(explicit_exclusions(self.condition), {"player_attack"})

    def test_rejects_positive_player_attack_but_keeps_enemy_attack_and_constraint(self) -> None:
        features = [
            {
                "feature_id": "player-attack",
                "name": "공격",
                "description": "플레이어가 적 또는 목표를 공격할 수 있다.",
                "source_text": self.condition,
            },
            {
                "feature_id": "enemy-attack",
                "name": "근접 적 공격",
                "description": "플레이어를 발견하면 근접 적이 플레이어에게 공격을 가한다.",
                "source_text": self.condition,
            },
            {
                "feature_id": "no-attack",
                "name": "플레이어 공격 금지",
                "description": "플레이어는 공격 능력이 없다.",
                "source_text": self.condition,
            },
        ]

        accepted, rejected = filter_conflicting_features(features, self.condition)

        self.assertEqual(
            [feature["feature_id"] for feature in accepted],
            ["enemy-attack", "no-attack"],
        )
        self.assertEqual([feature["feature_id"] for feature in rejected], ["player-attack"])
        self.assertIsNone(feature_conflict_reason(features[1], self.condition))
        self.assertIsNone(feature_conflict_reason(features[2], self.condition))

    def test_tower_attack_does_not_become_player_attack(self) -> None:
        condition = "플레이어는 골드로 타워를 배치하고 타워가 사거리 안의 적을 자동으로 공격한다."
        features = [
            {
                "feature_id": "player-attack",
                "name": "공격",
                "description": "플레이어가 적 또는 목표를 공격할 수 있다.",
                "source_text": condition,
            },
            {
                "feature_id": "tower-attack",
                "name": "타워 공격",
                "description": "타워가 사거리 안의 적을 자동으로 공격한다.",
                "source_text": condition,
            },
        ]

        accepted, rejected = filter_genre_conflicting_features(features, condition, "타워 디펜스")

        self.assertEqual([feature["feature_id"] for feature in accepted], ["tower-attack"])
        self.assertEqual([feature["feature_id"] for feature in rejected], ["player-attack"])

    def test_orbiting_sword_excludes_player_projectiles_but_not_enemy_shots(self) -> None:
        condition = (
            "검이 자동으로 회전하며 적에게 피해를 준다. 검은 투사체로 대체하면 안 된다. "
            "원거리 적은 투사체를 발사한다."
        )
        self.assertTrue(forbids_player_projectiles(condition))
        self.assertIn("player_projectile_attack", explicit_exclusions(condition))
        self.assertFalse(forbids_player_projectiles("원거리 적이 투사체를 발사한다."))

    def test_preflight_rejects_player_projectile_module_for_orbiting_sword(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = root / UnityProjectValidator.REQUIRED_FILE_PATHS["config"]
            config.parent.mkdir(parents=True)
            config.write_text(
                "  selectedModules:\n  - auto_target_system\n  - projectile_system\n",
                encoding="utf-8",
            )
            outcome = UnityValidationOutcome()
            UnityProjectValidator(mode="static")._check_attack_delivery(
                outcome,
                root,
                {
                    "condition": "검이 자동으로 회전한다. 검은 투사체로 대체하면 안 된다. 원거리 적은 투사체를 발사한다."
                },
            )
        self.assertEqual(outcome.status, "failed")
        self.assertEqual(outcome.issues[0]["code"], "UNITY_PLAYER_ATTACK_DELIVERY_CONFLICT")


if __name__ == "__main__":
    unittest.main()
