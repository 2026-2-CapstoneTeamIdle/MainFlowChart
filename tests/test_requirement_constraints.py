from __future__ import annotations

import unittest

from game_pipeline.requirement_constraints import (
    explicit_exclusions,
    feature_conflict_reason,
    filter_conflicting_features,
    filter_genre_conflicting_features,
)


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


if __name__ == "__main__":
    unittest.main()
