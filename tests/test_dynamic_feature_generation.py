from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping
from unittest.mock import MagicMock, patch

from game_pipeline import (
    GeminiApiClient,
    GeminiFeatureGenerator,
    LocalAIJsonClient,
    UnityProjectGenerator,
    UnityProjectValidator,
    attach_generated_modules,
    build_game_logic_design,
    create_feature_generator_from_environment,
    normalize_game_spec,
    plan_feature_mechanics,
)
from mainflow.contracts import CONTRACT_VERSION, FeatureRequirement, GameLogicDraft, ParsedRequest


GENERATED_SOURCE = """using System;
using TeamIdle.GameTemplate.Core;
using TeamIdle.GameTemplate.Common;
using UnityEngine;

namespace TeamIdle.GameTemplate.Generated
{
    [GeneratedGameModule(\"generated_feature_01\")]
    public sealed class WallClimbModule : GameModuleBehaviour, IGeneratedFeatureModule
    {
        public override string ModuleId => \"generated_feature_01\";

        public bool IsFeatureBound { get; private set; }

        public float ClimbSpeed { get; private set; } = 4f;

        private Rigidbody2D playerBody;
        private InputAdapterModule input;
        private GeneratedFeatureBindingContext bindingContext;

        protected override void OnInitialize(GameContext context)
        {
            context.Register(this);
        }

        public void BindGeneratedFeature(GeneratedFeatureBindingContext context)
        {
            bindingContext = context;
            input = context.GetModule<InputAdapterModule>();
            playerBody = context.Player == null ? null : context.Player.GetComponent<Rigidbody2D>();
            if (playerBody == null || input == null)
            {
                throw new InvalidOperationException("Wall climb requires a Rigidbody2D player.");
            }

            IsFeatureBound = true;
        }

        private void FixedUpdate()
        {
            if (!IsInitialized || !IsFeatureBound || Mathf.Abs(input.Movement.x) < 0.1f)
            {
                return;
            }

            var direction = Vector2.right * Mathf.Sign(input.Movement.x);
            var wall = Physics2D.Raycast(playerBody.position, direction, 0.7f);
            if (wall.collider != null && wall.collider.gameObject != playerBody.gameObject)
            {
                playerBody.linearVelocity = new Vector2(
                    playerBody.linearVelocity.x,
                    input.Movement.y * ClimbSpeed
                );
            }
        }
    }
}
"""


class FakeStructuredJsonClient:
    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.payload = payload
        self.calls = 0

    def generate_json(
        self,
        prompt: str,
        schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        self.calls += 1
        self.last_prompt = prompt
        self.last_schema = schema
        return self.payload


class PerFeatureStructuredJsonClient:
    def __init__(self) -> None:
        self.calls = 0

    def generate_json(
        self,
        prompt: str,
        schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        self.calls += 1
        if '"generated_feature_01": {' in prompt:
            return {
                "generated_modules": [
                    {
                        "module_id": "generated_feature_01",
                        "feature_id": "feature_01",
                        "feature_description": "벽을 탄다.",
                        "class_name": "WallClimbModule",
                        "source_code": GENERATED_SOURCE,
                    }
                ]
            }
        source = GENERATED_SOURCE.replace("generated_feature_01", "generated_feature_02").replace(
            "WallClimbModule", "AirDashModule"
        )
        return {
            "generated_modules": [
                {
                    "module_id": "generated_feature_02",
                    "feature_id": "feature_02",
                    "feature_description": "공중 대시를 한다.",
                    "class_name": "AirDashModule",
                    "source_code": source,
                }
            ]
        }


class SequenceStructuredJsonClient:
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


class DynamicFeatureGenerationTest(unittest.TestCase):
    def test_generated_source_rejects_3d_force_mode(self) -> None:
        requirement = {"feature_id": "feature_01", "feature_description": "벽 타기"}
        module = {
            "module_id": "generated_feature_01",
            **requirement,
            "class_name": "WallClimbModule",
            "source_code": GENERATED_SOURCE + "\n// ForceMode.Acceleration",
        }
        generator = GeminiFeatureGenerator(FakeStructuredJsonClient({}))
        with self.assertRaisesRegex(ValueError, "banned APIs"):
            generator._validate_module(module, {"generated_feature_01": requirement})

    def test_default_feature_provider_is_local_qwen(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            generator = create_feature_generator_from_environment()
        self.assertIsInstance(generator.client, LocalAIJsonClient)
        self.assertEqual(generator.client.model, "qwen2.5-coder-7b-q5-k-m")
        self.assertEqual(generator.client.timeout_seconds, 300)

    def test_localai_request_uses_openai_json_schema_fields(self) -> None:
        api_response = {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": json.dumps({"generated_modules": []})},
                }
            ]
        }
        response = MagicMock()
        response.read.return_value = json.dumps(api_response).encode("utf-8")
        response_context = MagicMock()
        response_context.__enter__.return_value = response

        with patch(
            "game_pipeline.gemini_feature_generator.urllib.request.urlopen",
            return_value=response_context,
        ) as urlopen:
            result = LocalAIJsonClient().generate_json(
                "generate",
                {"type": "object"},
            )

        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["model"], "qwen2.5-coder-7b-q5-k-m")
        self.assertEqual(payload["max_tokens"], 2048)
        self.assertEqual(payload["response_format"]["type"], "json_schema")
        self.assertEqual(
            payload["response_format"]["json_schema"]["schema"],
            {"type": "object"},
        )
        self.assertEqual(result, {"generated_modules": []})

    def test_localai_invalid_response_reports_structured_output_error(self) -> None:
        response = MagicMock()
        response.read.return_value = b"not-json"
        response_context = MagicMock()
        response_context.__enter__.return_value = response

        with patch(
            "game_pipeline.gemini_feature_generator.urllib.request.urlopen",
            return_value=response_context,
        ):
            with self.assertRaisesRegex(RuntimeError, "invalid structured JSON"):
                LocalAIJsonClient().generate_json("generate", {"type": "object"})

    def test_feature_generator_selects_localai_from_environment(self) -> None:
        with patch.dict(
            os.environ,
            {
                "MAINFLOW_FEATURE_PROVIDER": "local",
                "LOCAL_LLM_BASE_URL": "http://local-ai:8080/v1",
                "LOCAL_LLM_MODEL": "local-test-model",
            },
            clear=True,
        ):
            generator = create_feature_generator_from_environment()

        self.assertIsInstance(generator.client, LocalAIJsonClient)
        self.assertEqual(generator.client.base_url, "http://local-ai:8080/v1")
        self.assertEqual(generator.client.model, "local-test-model")

    def test_gemini_request_uses_generate_content_json_schema_fields(self) -> None:
        api_response = {
            "candidates": [
                {"content": {"parts": [{"text": json.dumps({"generated_modules": []})}]}}
            ]
        }
        response = MagicMock()
        response.read.return_value = json.dumps(api_response).encode("utf-8")
        response_context = MagicMock()
        response_context.__enter__.return_value = response

        with patch(
            "game_pipeline.gemini_feature_generator.urllib.request.urlopen",
            return_value=response_context,
        ) as urlopen:
            result = GeminiApiClient(api_key="test-key").generate_json(
                "generate",
                {"type": "object"},
            )

        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        generation_config = payload["generationConfig"]
        self.assertEqual(generation_config["responseMimeType"], "application/json")
        self.assertEqual(generation_config["responseJsonSchema"], {"type": "object"})
        self.assertEqual(generation_config["thinkingConfig"]["thinkingLevel"], "low")
        self.assertEqual(generation_config["maxOutputTokens"], 8192)
        self.assertNotIn("responseFormat", generation_config)
        self.assertEqual(result, {"generated_modules": []})

    def test_gemini_timeout_is_retried_and_reports_configuration_hint(self) -> None:
        with patch(
            "game_pipeline.gemini_feature_generator.urllib.request.urlopen",
            side_effect=TimeoutError("timed out"),
        ) as urlopen:
            with self.assertRaisesRegex(
                RuntimeError,
                "MAINFLOW_GEMINI_TIMEOUT_SECONDS",
            ):
                GeminiApiClient(
                    api_key="test-key",
                    timeout_seconds=1,
                    max_attempts=2,
                ).generate_json("generate", {"type": "object"})

        self.assertEqual(urlopen.call_count, 2)

    def test_known_feature_reuses_existing_module_without_generation(self) -> None:
        features: list[FeatureRequirement] = [
            {
                "feature_id": "feature-01",
                "name": "점프",
                "description": "플레이어가 점프할 수 있다.",
                "source_text": "점프가 가능한 게임",
            }
        ]

        plan = plan_feature_mechanics(features, "플랫포머")

        self.assertEqual(plan.mechanics, ["platformer_movement"])
        self.assertFalse(plan.generation_requirements)

    def test_horizontal_movement_reuses_platformer_module(self) -> None:
        features: list[FeatureRequirement] = [
            {
                "feature_id": "feature-01",
                "name": "좌우 이동",
                "description": "플레이어가 좌우로 이동할 수 있다.",
                "source_text": "플레이어가 좌우로 이동한다.",
            }
        ]

        plan = plan_feature_mechanics(features, "플랫포머")

        self.assertEqual(plan.mechanics, ["platformer_movement"])
        self.assertFalse(plan.generation_requirements)

    def test_multiple_unknown_features_are_generated_in_separate_requests(self) -> None:
        features: list[FeatureRequirement] = [
            {
                "feature_id": "feature-01",
                "name": "사용자 지정 조건",
                "description": "벽을 탄다.",
                "source_text": "벽을 탄다.",
            },
            {
                "feature_id": "feature-02",
                "name": "사용자 지정 조건",
                "description": "공중 대시를 한다.",
                "source_text": "공중 대시를 한다.",
            },
        ]
        plan = plan_feature_mechanics(features, "플랫포머")
        design = build_game_logic_design(
            normalize_game_spec(
                "플랫포머",
                {"features": plan.game_features, "mechanics": plan.mechanics},
            )
        )
        client = PerFeatureStructuredJsonClient()

        modules = GeminiFeatureGenerator(client).generate(
            design,
            plan.generation_requirements,
        )

        self.assertEqual(client.calls, 2)
        self.assertEqual(
            [module["module_id"] for module in modules],
            ["generated_feature_01", "generated_feature_02"],
        )

    def test_supported_platformer_features_reuse_verified_modules(self) -> None:
        features: list[FeatureRequirement] = [
            {
                "feature_id": "feature-01",
                "name": "벽 타기",
                "description": "벽을 오른다.",
                "source_text": "벽을 오르고 공중 대시를 한다.",
            },
            {
                "feature_id": "feature-02",
                "name": "공중 대시",
                "description": "공중에서 대시한다.",
                "source_text": "벽을 오르고 공중 대시를 한다.",
            },
        ]

        plan = plan_feature_mechanics(features, "플랫포머")

        self.assertEqual(plan.mechanics, ["wall_climb", "air_dash"])
        self.assertFalse(plan.generation_requirements)

    def test_platformer_destination_and_hazards_reuse_existing_modules(self) -> None:
        features: list[FeatureRequirement] = [
            {
                "feature_id": "feature-03",
                "name": "사용자 지정 조건",
                "description": "적과 장애물을 피해 목적지에 도달하는 게임",
                "source_text": "적과 장애물을 피해 목적지에 도달한다.",
            }
        ]

        plan = plan_feature_mechanics(features, "플랫포머")

        self.assertEqual(plan.mechanics, ["health_damage", "goal"])
        self.assertFalse(plan.generation_requirements)

    def test_platformer_stage_content_reuses_existing_modules(self) -> None:
        descriptions = [
            "가시 함정",
            "수집 가능한 보석",
            "체크포인트가 있으",
            "보석을 모두 모은 뒤 목적지에 도달하면 스테이지를 클리어한다.",
        ]
        features: list[FeatureRequirement] = [
            {
                "feature_id": f"feature-{index:02d}",
                "name": "사용자 지정 조건",
                "description": description,
                "source_text": description,
            }
            for index, description in enumerate(descriptions, start=1)
        ]

        plan = plan_feature_mechanics(features, "플랫포머")

        self.assertEqual(plan.mechanics, ["health_damage", "collectible", "goal"])
        self.assertFalse(plan.generation_requirements)

    def test_unknown_feature_is_generated_and_written_to_unity_project(self) -> None:
        features: list[FeatureRequirement] = [
            {
                "feature_id": "feature-01",
                "name": "사용자 지정 조건",
                "description": "벽을 타고 올라갈 수 있다.",
                "source_text": "벽을 타고 올라갈 수 있다.",
            }
        ]
        plan = plan_feature_mechanics(features, "플랫포머")
        spec = normalize_game_spec(
            "플랫포머",
            {
                "features": plan.game_features,
                "mechanics": plan.mechanics,
            },
        )
        design = build_game_logic_design(spec)
        client = FakeStructuredJsonClient(
            {
                "generated_modules": [
                    {
                        "module_id": "generated_feature_01",
                        "feature_id": "feature_01",
                        "feature_description": "벽을 타고 올라갈 수 있다.",
                        "class_name": "WallClimbModule",
                        "source_code": GENERATED_SOURCE,
                    }
                ]
            }
        )

        modules = GeminiFeatureGenerator(client).generate(
            design,
            plan.generation_requirements,
        )
        resolved = attach_generated_modules(design, modules)

        self.assertEqual(client.calls, 1)
        self.assertFalse(resolved["unsupported_mechanics"])
        self.assertIn("generated_feature_01", resolved["selected_modules"])
        with tempfile.TemporaryDirectory() as temporary_directory:
            result = UnityProjectGenerator().generate(
                resolved,
                Path(temporary_directory) / "GeneratedGame",
            )
            source_path = (
                result.project_root / "Assets/GameTemplate/Generated/Scripts/WallClimbModule.cs"
            )
            self.assertEqual(source_path.read_text(encoding="utf-8"), GENERATED_SOURCE)
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(
                manifest["generated_modules"][0]["module_id"],
                "generated_feature_01",
            )

    def test_generated_source_rejects_file_and_network_apis(self) -> None:
        features: list[FeatureRequirement] = [
            {
                "feature_id": "feature-01",
                "name": "사용자 지정 조건",
                "description": "외부 파일을 읽는다.",
                "source_text": "외부 파일을 읽는다.",
            }
        ]
        plan = plan_feature_mechanics(features, "플랫포머")
        design = build_game_logic_design(
            normalize_game_spec("플랫포머", {"mechanics": plan.mechanics})
        )
        unsafe_source = GENERATED_SOURCE.replace(
            "using UnityEngine;",
            "using UnityEngine;\nusing System.IO;",
        )
        client = FakeStructuredJsonClient(
            {
                "generated_modules": [
                    {
                        "module_id": "generated_feature_01",
                        "feature_id": "feature_01",
                        "feature_description": "외부 파일을 읽는다.",
                        "class_name": "WallClimbModule",
                        "source_code": unsafe_source,
                    }
                ]
            }
        )

        with self.assertRaisesRegex(ValueError, "banned APIs"):
            GeminiFeatureGenerator(client).generate(
                design,
                plan.generation_requirements,
            )
        self.assertEqual(client.calls, 3)

    def test_generated_source_rejects_3d_physics_api(self) -> None:
        features: list[FeatureRequirement] = [
            {
                "feature_id": "feature-01",
                "name": "사용자 지정 조건",
                "description": "벽을 타고 올라갈 수 있다.",
                "source_text": "벽을 타고 올라갈 수 있다.",
            }
        ]
        plan = plan_feature_mechanics(features, "플랫포머")
        design = build_game_logic_design(
            normalize_game_spec("플랫포머", {"mechanics": plan.mechanics})
        )
        invalid_source = GENERATED_SOURCE.replace("Rigidbody2D", "CharacterController")
        client = FakeStructuredJsonClient(
            {
                "generated_modules": [
                    {
                        "module_id": "generated_feature_01",
                        "feature_id": "feature_01",
                        "feature_description": "벽을 타고 올라갈 수 있다.",
                        "class_name": "WallClimbModule",
                        "source_code": invalid_source,
                    }
                ]
            }
        )

        with self.assertRaisesRegex(ValueError, "banned APIs"):
            GeminiFeatureGenerator(client).generate(
                design,
                plan.generation_requirements,
            )

    def test_generated_source_rejects_comment_only_update_behavior(self) -> None:
        features: list[FeatureRequirement] = [
            {
                "feature_id": "feature-01",
                "name": "사용자 지정 조건",
                "description": "벽을 탄다.",
                "source_text": "벽을 탄다.",
            }
        ]
        plan = plan_feature_mechanics(features, "플랫포머")
        design = build_game_logic_design(
            normalize_game_spec("플랫포머", {"mechanics": plan.mechanics})
        )
        method_start = GENERATED_SOURCE.index("        private void FixedUpdate()")
        comment_only_source = (
            GENERATED_SOURCE[:method_start]
            + """        private void Update()
        {
            if (!IsInitialized || !IsFeatureBound)
            {
                return;
            }

            // Behavior intentionally omitted.
        }
    }
}
"""
        )
        client = FakeStructuredJsonClient(
            {
                "generated_modules": [
                    {
                        "module_id": "generated_feature_01",
                        "feature_id": "feature_01",
                        "feature_description": "벽을 탄다.",
                        "class_name": "WallClimbModule",
                        "source_code": comment_only_source,
                    }
                ]
            }
        )

        with self.assertRaisesRegex(ValueError, "no executable feature behavior"):
            GeminiFeatureGenerator(client).generate(
                design,
                plan.generation_requirements,
            )
        self.assertEqual(client.calls, 3)

    def test_generated_source_rejects_binding_context_used_from_update(self) -> None:
        requirement = {"feature_id": "feature_01", "feature_description": "벽을 탄다."}
        invalid_source = GENERATED_SOURCE.replace(
            "var direction = Vector2.right * Mathf.Sign(input.Movement.x);",
            "var direction = Vector2.right * context.Player.transform.localScale.x;",
        )
        module = {
            "module_id": "generated_feature_01",
            **requirement,
            "class_name": "WallClimbModule",
            "source_code": invalid_source,
        }

        with self.assertRaisesRegex(ValueError, "method-local context"):
            GeminiFeatureGenerator(FakeStructuredJsonClient({}))._validate_module(
                module,
                {"generated_feature_01": requirement},
            )

    def test_generated_source_rejects_custom_tag_lookup(self) -> None:
        requirement = {"feature_id": "feature_01", "feature_description": "벽을 탄다."}
        invalid_source = GENERATED_SOURCE.replace(
            "var direction = Vector2.right * Mathf.Sign(input.Movement.x);",
            'var direction = gameObject.CompareTag("Wall") ? Vector2.up : Vector2.right;',
        )
        module = {
            "module_id": "generated_feature_01",
            **requirement,
            "class_name": "WallClimbModule",
            "source_code": invalid_source,
        }

        with self.assertRaisesRegex(ValueError, "banned APIs"):
            GeminiFeatureGenerator(FakeStructuredJsonClient({}))._validate_module(
                module,
                {"generated_feature_01": requirement},
            )

    def test_generated_source_rejects_invented_platformer_module_api(self) -> None:
        requirement = {"feature_id": "feature_01", "feature_description": "벽을 탄다."}
        invalid_source = (
            GENERATED_SOURCE.replace(
                "private InputAdapterModule input;",
                "private InputAdapterModule input;\n        private PlatformerMovementModule movement;",
            )
            .replace(
                "input = context.GetModule<InputAdapterModule>();",
                "input = context.GetModule<InputAdapterModule>();\n"
                "            movement = context.GetModule<PlatformerMovementModule>();",
            )
            .replace(
                "var direction = Vector2.right * Mathf.Sign(input.Movement.x);",
                "var direction = Vector2.right * movement.moveSpeed;",
            )
        )
        invalid_source = invalid_source.replace(
            "using TeamIdle.GameTemplate.Common;",
            "using TeamIdle.GameTemplate.Common;\nusing TeamIdle.GameTemplate.Platformer;",
        )
        module = {
            "module_id": "generated_feature_01",
            **requirement,
            "class_name": "WallClimbModule",
            "source_code": invalid_source,
        }

        with self.assertRaisesRegex(ValueError, "invents PlatformerMovementModule APIs"):
            GeminiFeatureGenerator(FakeStructuredJsonClient({}))._validate_module(
                module,
                {"generated_feature_01": requirement},
            )

    def test_retry_includes_previous_candidate_and_validation_error(self) -> None:
        features: list[FeatureRequirement] = [
            {
                "feature_id": "feature-01",
                "name": "사용자 지정 조건",
                "description": "벽을 탄다.",
                "source_text": "벽을 탄다.",
            }
        ]
        plan = plan_feature_mechanics(features, "플랫포머")
        design = build_game_logic_design(
            normalize_game_spec("플랫포머", {"mechanics": plan.mechanics})
        )
        invalid_source = GENERATED_SOURCE.replace(
            "var direction = Vector2.right * Mathf.Sign(input.Movement.x);",
            "var direction = Vector2.right * context.Player.transform.localScale.x;",
        )

        def payload(source: str) -> Mapping[str, Any]:
            return {
                "generated_modules": [
                    {
                        "module_id": "generated_feature_01",
                        "feature_id": "feature_01",
                        "feature_description": "벽을 탄다.",
                        "class_name": "WallClimbModule",
                        "source_code": source,
                    }
                ]
            }

        client = SequenceStructuredJsonClient([payload(invalid_source), payload(GENERATED_SOURCE)])
        modules = GeminiFeatureGenerator(client).generate(
            design,
            plan.generation_requirements,
        )

        self.assertEqual(len(modules), 1)
        self.assertEqual(len(client.prompts), 2)
        self.assertIn("previous_candidate", client.prompts[1])
        self.assertIn("method-local context", client.prompts[1])
        self.assertIn("context.Player.transform.localScale.x", client.prompts[1])

    def test_generated_source_accepts_computed_binding_state(self) -> None:
        features: list[FeatureRequirement] = [
            {
                "feature_id": "feature-01",
                "name": "사용자 지정 조건",
                "description": "벽을 타고 올라갈 수 있다.",
                "source_text": "벽을 타고 올라갈 수 있다.",
            }
        ]
        plan = plan_feature_mechanics(features, "플랫포머")
        design = build_game_logic_design(
            normalize_game_spec("플랫포머", {"mechanics": plan.mechanics})
        )
        computed_source = GENERATED_SOURCE.replace(
            "public bool IsFeatureBound { get; private set; }",
            "public bool IsFeatureBound => playerBody != null;",
        ).replace("            IsFeatureBound = true;\n", "")
        client = FakeStructuredJsonClient(
            {
                "generated_modules": [
                    {
                        "module_id": "generated_feature_01",
                        "feature_id": "feature_01",
                        "feature_description": "벽을 타고 올라갈 수 있다.",
                        "class_name": "WallClimbModule",
                        "source_code": computed_source,
                    }
                ]
            }
        )

        modules = GeminiFeatureGenerator(client).generate(
            design,
            plan.generation_requirements,
        )

        self.assertEqual(len(modules), 1)

    @unittest.skipUnless(
        os.environ.get("MAINFLOW_RUN_UNITY_INTEGRATION_TESTS") == "1",
        "Unity integration test is opt-in",
    )
    def test_generated_module_compiles_and_is_discovered_by_unity(self) -> None:
        features: list[FeatureRequirement] = [
            {
                "feature_id": "feature-01",
                "name": "사용자 지정 조건",
                "description": "벽을 타고 올라갈 수 있다.",
                "source_text": "벽을 타고 올라갈 수 있다.",
            }
        ]
        plan = plan_feature_mechanics(features, "플랫포머")
        design = build_game_logic_design(
            normalize_game_spec(
                "플랫포머",
                {"features": plan.game_features, "mechanics": plan.mechanics},
            )
        )
        client = FakeStructuredJsonClient(
            {
                "generated_modules": [
                    {
                        "module_id": "generated_feature_01",
                        "feature_id": "feature_01",
                        "feature_description": "벽을 타고 올라갈 수 있다.",
                        "class_name": "WallClimbModule",
                        "source_code": GENERATED_SOURCE,
                    }
                ]
            }
        )
        resolved = attach_generated_modules(
            design,
            GeminiFeatureGenerator(client).generate(
                design,
                plan.generation_requirements,
            ),
        )
        request: ParsedRequest = {
            "contract_version": CONTRACT_VERSION,
            "image_style": "Pixel Art",
            "mood_style": "Fantasy",
            "genre": "플랫포머",
            "viewpoint": "사이드뷰",
            "condition": "벽을 타고 올라갈 수 있다.",
            "custom_image": None,
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "project" / "game" / "unity_project"
            result = UnityProjectGenerator().generate(resolved, root)
            draft: GameLogicDraft = {
                "contract_version": CONTRACT_VERSION,
                "draft_id": "dynamic-platformer-draft",
                "status": "generated",
                "engine": "Unity",
                "entry_scene": "game/unity_project/Assets/Scenes/Bootstrap.unity",
                "source_artifacts": [],
                "required_image_asset_ids": [
                    item["asset_id"]
                    for item in resolved["game_spec"]["asset_requirements"]
                    if item["asset_type"] == "image"
                ],
                "required_sound_asset_ids": [
                    item["asset_id"]
                    for item in resolved["game_spec"]["asset_requirements"]
                    if item["asset_type"] == "sound"
                ],
                "notes": [],
            }

            outcome = UnityProjectValidator(mode="required").validate(
                result.project_root,
                draft,
                request,
            )

            self.assertEqual(outcome.status, "passed", outcome.unity_log[-4000:])


if __name__ == "__main__":
    unittest.main()
