from __future__ import annotations

from typing import cast

from game_pipeline.agent_visual_assets import with_agent_visual_assets
from mainflow.contracts import AssetGenerationRequest


def _request() -> AssetGenerationRequest:
    return cast(
        AssetGenerationRequest,
        {
            "asset_type": "image",
            "assets": [
                {
                    "asset_id": "stage_background",
                    "asset_type": "image",
                    "purpose": "배경",
                    "description": "기존 배경",
                    "required": False,
                    "suggested_filename": "stage_background.png",
                    "unity_binding_key": "asset_registry:stage_background",
                    "generation_spec": {"kind": "background"},
                }
            ],
        },
    )


def test_agent_visuals_add_novel_condition_objects_without_repeating_instances() -> None:
    request, added = with_agent_visual_assets(
        _request(),
        [
            {
                "visual_objects": [
                    {
                        "asset_id": "visual_clockwork_drone",
                        "scene_object_prefix": "ClockworkDrone_",
                        "purpose": "적 드론",
                        "description": "톱니바퀴 날개를 가진 적 하나",
                        "kind": "sprite",
                    },
                    {
                        "asset_id": "visual_clockwork_drone",
                        "scene_object_prefix": "ClockworkDrone_",
                        "purpose": "적 드론",
                        "description": "동일한 적의 두 번째 인스턴스",
                        "kind": "sprite",
                    },
                    {
                        "asset_id": "visual_time_gate",
                        "scene_object_prefix": "TimeGate_",
                        "purpose": "시간의 문",
                        "description": "시간을 되돌리면 열리는 문",
                        "kind": "sprite",
                    },
                ]
            }
        ],
    )

    assert added == ["visual_clockwork_drone", "visual_time_gate"]
    assert [item["asset_id"] for item in request["assets"]] == [
        "stage_background",
        "visual_clockwork_drone",
        "visual_time_gate",
    ]
    assert request["assets"][1]["unity_binding_key"] == "scene_object_prefix:ClockworkDrone_"
    assert request["assets"][1]["generation_spec"]["kind"] == "sprite"


def test_agent_visuals_reject_invalid_binding_and_honor_explicit_kind() -> None:
    request, added = with_agent_visual_assets(
        _request(),
        [
            {
                "visual_objects": [
                    {
                        "asset_id": "visual_bad",
                        "scene_object_prefix": "../Other",
                        "purpose": "임의 경로",
                        "description": "잘못된 바인딩",
                        "kind": "sprite",
                    },
                    {
                        "asset_id": "visual_hud_badge",
                        "scene_object_prefix": "HudBadge_",
                        "purpose": "상태 표시",
                        "description": "진행 상황을 표시하는 작은 배경 없는 표식",
                        "kind": "ui",
                    },
                ]
            }
        ],
    )

    assert added == ["visual_hud_badge"]
    assert request["assets"][-1]["generation_spec"]["kind"] == "ui"
    assert request["assets"][-1]["unity_binding_key"] == "ui_object_prefix:HudBadge_"
