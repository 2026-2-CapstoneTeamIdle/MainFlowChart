from game_pipeline.condition_visual_assets import with_condition_visual_assets
from game_pipeline.design_catalog import normalize_game_spec
from game_pipeline.design_catalog import build_game_logic_design
from game_pipeline.unity_project_generator import UnityProjectGenerator


def test_survivor_orbiting_sword_is_described_as_weapon_only():
    spec = normalize_game_spec("뱀서류", {"viewpoint": "탑다운"})
    updated = with_condition_visual_assets(
        spec, "플레이어 주변을 검 한 자루가 회전하며 적에게 피해를 준다. 투사체로 대체하면 안 된다."
    )
    weapon = next(
        item
        for item in updated["asset_requirements"]
        if item["asset_id"] == "primary_attack_visual"
    )

    assert "검 한 자루" in weapon["description"]
    assert "플레이어" in weapon["description"]
    assert "그리지 않는다" in weapon["description"]
    assert "회전하는 검" in weapon["purpose"]
    assert updated is not spec

    design = build_game_logic_design(updated, design_intent="플레이어 주변에서 검이 회전한다")
    request = UnityProjectGenerator().build_asset_request(
        design,
        "image",
        image_style="Pixel Art",
        mood_style="Fantasy",
        viewpoint="탑다운",
        reference_image=None,
    )
    generated_weapon = next(
        item for item in request["assets"] if item["asset_id"] == "primary_attack_visual"
    )
    assert generated_weapon["generation_spec"]["kind"] == "sprite"
    assert generated_weapon["generation_spec"]["transparent"] is True
