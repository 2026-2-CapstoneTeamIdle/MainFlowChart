import json
from pathlib import Path

import pytest

from mainflow.nodes.design_game_logic import _synchronize_agent_asset_contracts
from game_pipeline.unity_project_generator import UnityProjectGenerator


def test_agent_discovered_assets_update_host_owned_manifest(tmp_path: Path):
    project = tmp_path / "unity_project"
    project.mkdir()
    manifest_path = project / UnityProjectGenerator.MANIFEST_PATH
    manifest_path.write_text(json.dumps({"design_id": "example", "asset_requirements": []}))
    image = {"asset_id": "visual_enemy_fast", "asset_type": "image"}
    sound = {"asset_id": "enemy_defeated_sfx", "asset_type": "sound"}
    design = {"game_spec": {"asset_requirements": [image, sound]}}
    image_request = {"assets": [image]}
    sound_request = {"assets": [sound]}

    _synchronize_agent_asset_contracts(project, design, image_request, sound_request)

    manifest = json.loads(manifest_path.read_text())
    assert manifest["design_id"] == "example"
    assert manifest["asset_requirements"] == [image, sound]
    assert json.loads((project / UnityProjectGenerator.DESIGN_PATH).read_text()) == design
    assert (
        json.loads((project / UnityProjectGenerator.IMAGE_ASSET_REQUEST_PATH).read_text())
        == image_request
    )


def test_asset_contract_sync_rejects_missing_request(tmp_path: Path):
    project = tmp_path / "unity_project"
    project.mkdir()
    (project / UnityProjectGenerator.MANIFEST_PATH).write_text("{}")
    design = {"game_spec": {"asset_requirements": [{"asset_id": "weapon", "asset_type": "image"}]}}

    with pytest.raises(ValueError, match="design_only"):
        _synchronize_agent_asset_contracts(project, design, {"assets": []}, {"assets": []})
