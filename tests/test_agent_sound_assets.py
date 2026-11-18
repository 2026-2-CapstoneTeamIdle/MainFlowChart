from __future__ import annotations

from typing import cast

from game_pipeline.agent_sound_assets import with_agent_sound_assets
from mainflow.contracts import AssetGenerationRequest


def _request() -> AssetGenerationRequest:
    return cast(
        AssetGenerationRequest,
        {
            "asset_type": "sound",
            "assets": [
                {
                    "asset_id": "tower_attack_sfx",
                    "asset_type": "sound",
                    "purpose": "타워 공격",
                    "description": "기존 공격 효과음",
                    "generation_spec": {"audio_cue": "tower_attack"},
                }
            ],
        },
    )


def test_agent_sounds_add_condition_event_with_exact_cue() -> None:
    request, added = with_agent_sound_assets(
        _request(),
        [
            {
                "sound_events": [
                    {
                        "asset_id": "clockwork_gate_open_sfx",
                        "cue_id": "clockwork_gate_open",
                        "purpose": "시간의 문 개방",
                        "description": "시계 장치의 문이 실제로 열릴 때 울리는 금속음",
                        "kind": "sfx",
                    }
                ]
            }
        ],
    )

    assert added == ["clockwork_gate_open_sfx"]
    item = request["assets"][-1]
    assert item["required"] is False
    assert item["generation_spec"]["audio_cue"] == "clockwork_gate_open"
    assert item["generation_spec"]["kind"] == "sfx"
    assert item["unity_binding_key"] == "asset_registry:clockwork_gate_open_sfx"


def test_agent_sounds_deduplicate_existing_ids_and_cues() -> None:
    request, added = with_agent_sound_assets(
        _request(),
        [
            {
                "sound_events": [
                    {
                        "asset_id": "tower_attack_sfx",
                        "cue_id": "another_tower_attack",
                        "purpose": "중복 ID",
                        "description": "같은 에셋 ID",
                        "kind": "sfx",
                    },
                    {
                        "asset_id": "tower_attack_variant_sfx",
                        "cue_id": "tower_attack",
                        "purpose": "중복 cue",
                        "description": "같은 타워 공격 이벤트",
                        "kind": "sfx",
                    },
                    {
                        "asset_id": "../invalid",
                        "cue_id": "valid_cue",
                        "purpose": "잘못된 ID",
                        "description": "경로 문자 포함",
                        "kind": "sfx",
                    },
                ]
            }
        ],
    )

    assert added == []
    assert len(request["assets"]) == 1


def test_agent_sounds_honor_music_cue_override() -> None:
    request, added = with_agent_sound_assets(
        _request(),
        [
            {
                "sound_events": [
                    {
                        "asset_id": "boss_phase_bgm",
                        "cue_id": "boss_phase_started",
                        "purpose": "보스 전투 배경 음악",
                        "description": "보스 페이즈가 실제 시작하면 전환할 음악",
                        "kind": "bgm",
                    }
                ]
            }
        ],
    )

    assert added == ["boss_phase_bgm"]
    spec = request["assets"][-1]["generation_spec"]
    assert spec["kind"] == "bgm"
    assert spec["audio_cue"] == "boss_phase_started"
    assert spec["loop"] is True
