"""Opt-in verification of imported assets through the real Unity Editor."""

from __future__ import annotations

import io
import json
import math
import os
import struct
import tempfile
import unittest
import wave
from unittest.mock import patch

from game_pipeline import UnityProjectGenerator, build_game_logic_design, normalize_game_spec
from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import CONTRACT_VERSION
from mainflow.image_generation import encode_png
from mainflow.nodes.apply_assets import apply_assets_to_game_node
from mainflow.nodes.final_validation import final_validation_node


@unittest.skipUnless(
    os.environ.get("MAINFLOW_RUN_UNITY_INTEGRATION_TESTS") == "1",
    "Unity integration test is opt-in",
)
class FinalUnityIntegrationTest(unittest.TestCase):
    def test_validated_assets_import_bind_compile_and_play(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = ArtifactManager(temporary)
            project = manager.create_project()
            state = {"project_id": project}

            def put(key, payload):
                state[key] = manager.write_json(
                    project,
                    "data",
                    key + ".json",
                    {"contract_version": CONTRACT_VERSION, **payload},
                    producer="test",
                )

            design = build_game_logic_design(
                normalize_game_spec("플랫포머", {"viewpoint": "사이드뷰"})
            )
            root = manager.resolve_project_path(project, "game/unity_project")
            UnityProjectGenerator().generate(design, root)
            put(
                "parsed_request",
                {
                    "image_style": "Pixel Art",
                    "mood_style": "Fantasy",
                    "genre": "플랫포머",
                    "viewpoint": "사이드뷰",
                    "condition": "점프로 목표에 도달한다.",
                    "custom_image": None,
                },
            )
            # This fixture verifies import/binding/runtime only; it makes no semantic style/mood claims.
            put("logic_analysis", {"genre": "플랫포머", "criteria": [], "features": []})
            required = {}
            for target in ("image", "sound"):
                request = json.loads(
                    manager.read_project_file(
                        project,
                        f"game/unity_project/Assets/GameTemplate/Generated/AssetRequests/{target}_asset_request.json",
                    )
                )
                put(target + "_asset_request", request)
                required[target] = [item["asset_id"] for item in request["assets"]]
                selected = []
                for item in request["assets"]:
                    spec = item["generation_spec"]
                    if target == "image":
                        content = encode_png(
                            [[(100, 200, 150, 255)] * spec["width"] for _ in range(spec["height"])]
                        )
                        extension = "png"
                    else:
                        audio = io.BytesIO()
                        with wave.open(audio, "wb") as stream:
                            stream.setnchannels(1)
                            stream.setsampwidth(2)
                            stream.setframerate(22050)
                            stream.writeframes(
                                b"".join(
                                    struct.pack(
                                        "<h",
                                        int(5000 * math.sin(index * 2 * math.pi * 220 / 22050)),
                                    )
                                    for index in range(22050)
                                )
                            )
                        content = audio.getvalue()
                        extension = "wav"
                    artifact = manager.write_bytes(
                        project,
                        target,
                        item["asset_id"] + "." + extension,
                        content,
                        producer="test",
                    )
                    selected.append(
                        {
                            "asset_id": item["asset_id"],
                            "asset_type": target,
                            "unity_binding_key": item["unity_binding_key"],
                            "artifact": artifact,
                            "file_format": extension,
                        }
                    )
                put(target + "_draft", {"assets": []})
                put(
                    target + "_validation_result",
                    {
                        "status": "passed",
                        "checks": [],
                        "issues": [],
                        "validated_asset_ids": required[target],
                        "validated_assets": {
                            "manifest_version": "1.0.0",
                            "contract_version": CONTRACT_VERSION,
                            "assets": selected,
                        },
                    },
                )
            put(
                "game_logic_draft",
                {
                    "draft_id": "integration",
                    "status": "generated",
                    "engine": "Unity",
                    "entry_scene": "game/unity_project/Assets/Scenes/Bootstrap.unity",
                    "source_artifacts": [],
                    "required_image_asset_ids": required["image"],
                    "required_sound_asset_ids": required["sound"],
                    "notes": [],
                },
            )
            put("game_validation_result", {"status": "passed", "checks": [], "issues": []})
            with (
                patch("mainflow.nodes.apply_assets.ArtifactManager", return_value=manager),
                patch("mainflow.nodes.final_validation.ArtifactManager", return_value=manager),
                patch.dict(os.environ, {"MAINFLOW_UNITY_RUNTIME_TESTS": "1"}),
            ):
                state.update(apply_assets_to_game_node(state))
                result = manager.read_json(final_validation_node(state)["final_validation_result"])
            logs = "\n".join(
                manager.read_text(ref)
                for ref in result["evidence"]
                if ref["media_type"].startswith("text/")
            )
            self.assertEqual(
                result["status"], "passed", json.dumps(result["issues"]) + "\n" + logs[-8000:]
            )
            self.assertIsNotNone(result["entry_artifact"])


if __name__ == "__main__":
    unittest.main()
