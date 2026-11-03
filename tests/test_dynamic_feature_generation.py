from __future__ import annotations

import json
import os
import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from game_pipeline import (
    GeminiApiClient,
    GeminiFeatureGenerator,
    LocalAIJsonClient,
    OpenAIJsonClient,
    UnityProjectGenerator,
    UnityProjectValidator,
    attach_generated_modules,
    build_game_logic_design,
    create_feature_generator_from_environment,
    normalize_game_spec,
    plan_feature_mechanics,
)
from game_pipeline.gemini_feature_generator import (
    FEATURE_IMPLEMENTATION_PLAN_SCHEMA,
    GENERATED_MODULE_SCHEMA,
    _estimate_tokens,
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


class PlanningStructuredJsonClient:
    supports_feature_planning = True

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate_json(
        self,
        prompt: str,
        schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        self.prompts.append(prompt)
        if "implementation_plan" in schema.get("properties", {}):
            return {
                "implementation_plan": {
                    "module_id": "generated_feature_01",
                    "feature_id": "feature_01",
                    "behavior_summary": "Create a switch that opens a blocking gate.",
                    "binding_steps": ["resolve the player", "create the switch and gate"],
                    "scene_objects": [
                        {
                            "object_id": "gate_switch",
                            "parent": "entities",
                            "purpose": "player trigger",
                            "components": ["SpriteRenderer", "BoxCollider2D"],
                        },
                        {
                            "object_id": "blocking_gate",
                            "parent": "environment",
                            "purpose": "blocks the route until triggered",
                            "components": ["SpriteRenderer", "BoxCollider2D"],
                        },
                    ],
                    "runtime_flow": ["player touches switch", "gate is disabled"],
                    "acceptance_checks": ["gate blocks before trigger", "gate opens after trigger"],
                }
            }
        source = GENERATED_SOURCE.replace(
            "private GeneratedFeatureBindingContext bindingContext;",
            "private GeneratedFeatureBindingContext bindingContext;\n"
            "        private GameObject gateSwitch;\n"
            "        private GameObject blockingGate;",
        ).replace(
            "bindingContext = context;",
            "bindingContext = context;\n"
            '            gateSwitch = new GameObject("gate_switch");\n'
            '            blockingGate = new GameObject("blocking_gate");',
        )
        return {
            "generated_modules": [
                {
                    "module_id": "generated_feature_01",
                    "feature_id": "feature_01",
                    "feature_description": "버튼에 닿으면 문이 열린다.",
                    "class_name": "GeneratedFeature01Module",
                    "source_code": source.replace("WallClimbModule", "GeneratedFeature01Module"),
                }
            ]
        }


class PerFeatureStructuredJsonClient:
    def __init__(self) -> None:
        self.calls = 0

    def generate_json(
        self,
        prompt: str,
        schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        self.calls += 1
        if '"generated_feature_01"' in prompt:
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

    def test_generated_source_rejects_invented_unity_members(self) -> None:
        requirement = {"feature_id": "feature_01", "feature_description": "문을 연다."}
        invalid_source = GENERATED_SOURCE.replace(
            "var direction = Vector2.right * Mathf.Sign(input.Movement.x);",
            'var gate = bindingContext.Environment.CreateGameObject("Gate");',
        )
        module = {
            "module_id": "generated_feature_01",
            **requirement,
            "class_name": "WallClimbModule",
            "source_code": invalid_source,
        }

        with self.assertRaisesRegex(ValueError, "Transform.CreateGameObject"):
            GeminiFeatureGenerator(FakeStructuredJsonClient({}))._validate_module(
                module,
                {"generated_feature_01": requirement},
            )

    def test_generated_source_rejects_unknown_get_module_type(self) -> None:
        requirement = {"feature_id": "feature_01", "feature_description": "보스를 생성한다."}
        invalid_source = GENERATED_SOURCE.replace(
            "input = context.GetModule<InputAdapterModule>();",
            "input = context.GetModule<Environment>();",
        )
        module = {
            "module_id": "generated_feature_01",
            **requirement,
            "class_name": "WallClimbModule",
            "source_code": invalid_source,
        }

        with self.assertRaisesRegex(ValueError, "unknown module type Environment"):
            GeminiFeatureGenerator(FakeStructuredJsonClient({}))._validate_module(
                module,
                {"generated_feature_01": requirement},
            )

    def test_generated_source_accepts_public_api_from_prior_generated_module(self) -> None:
        prior_source = """namespace TeamIdle.GameTemplate.Generated
{
    public sealed class GeneratedFeature02Module
    {
        public string ModuleId => "generated_feature_02";
        public void ConfigureSword(int count, float size, float rotationSpeed) { }
    }
}
"""
        design = {
            "generated_modules": [
                {
                    "class_name": "GeneratedFeature02Module",
                    "source_code": prior_source,
                }
            ]
        }
        generated_apis = GeminiFeatureGenerator._prior_generated_type_apis(design)
        dependent_source = """private GeneratedFeature02Module swords;
public void BindGeneratedFeature(GeneratedFeatureBindingContext context)
{
    swords = context.GetModule<GeneratedFeature02Module>();
    swords.ConfigureSword(2, 0.5f, 180f);
}
"""

        GeminiFeatureGenerator._validate_project_api_members(
            dependent_source,
            "generated_feature_06",
            additional_type_apis=generated_apis,
        )

        self.assertEqual(
            generated_apis["GeneratedFeature02Module"],
            {"ConfigureSword", "ModuleId"},
        )

    def test_generated_source_rejects_button_is_pressed(self) -> None:
        requirement = {"feature_id": "feature_01", "feature_description": "버튼 강화"}
        invalid_source = GENERATED_SOURCE.replace(
            "var direction = Vector2.right * Mathf.Sign(input.Movement.x);",
            "var pressed = bindingContext.Ui.GetComponent<Button>().isPressed;",
        ).replace(
            "using UnityEngine;",
            "using UnityEngine;\nusing UnityEngine.UI;",
        )
        module = {
            "module_id": "generated_feature_01",
            **requirement,
            "class_name": "WallClimbModule",
            "source_code": invalid_source,
        }

        with self.assertRaisesRegex(ValueError, "Button.isPressed"):
            GeminiFeatureGenerator(FakeStructuredJsonClient({}))._validate_module(
                module,
                {"generated_feature_01": requirement},
            )

    def test_generated_source_rejects_binding_context_in_initializer(self) -> None:
        requirement = {"feature_id": "feature_01", "feature_description": "보스를 생성한다."}
        invalid_source = GENERATED_SOURCE.replace(
            "context.Register(this);",
            'context.Register(this);\n            bindingContext.Environment.Find("Boss");',
        )
        module = {
            "module_id": "generated_feature_01",
            **requirement,
            "class_name": "WallClimbModule",
            "source_code": invalid_source,
        }

        with self.assertRaisesRegex(ValueError, "bindingContext in OnInitialize"):
            GeminiFeatureGenerator(FakeStructuredJsonClient({}))._validate_module(
                module,
                {"generated_feature_01": requirement},
            )

    def test_generated_source_rejects_direct_particle_main_mutation(self) -> None:
        requirement = {"feature_id": "feature_01", "feature_description": "파티클 생성"}
        invalid_source = GENERATED_SOURCE.replace(
            "var direction = Vector2.right * Mathf.Sign(input.Movement.x);",
            "bindingContext.Player.AddComponent<ParticleSystem>().main.startLifetime = 1f;",
        )
        module = {
            "module_id": "generated_feature_01",
            **requirement,
            "class_name": "WallClimbModule",
            "source_code": invalid_source,
        }

        with self.assertRaisesRegex(ValueError, "mutates ParticleSystem.main directly"):
            GeminiFeatureGenerator(FakeStructuredJsonClient({}))._validate_module(
                module,
                {"generated_feature_01": requirement},
            )

    def test_generated_source_rejects_additional_helper_class(self) -> None:
        requirement = {"feature_id": "feature_01", "feature_description": "문을 연다."}
        invalid_source = GENERATED_SOURCE.rstrip().removesuffix("}")
        invalid_source += "\n    public class InventedEnemy : MonoBehaviour {}\n}\n"
        module = {
            "module_id": "generated_feature_01",
            **requirement,
            "class_name": "WallClimbModule",
            "source_code": invalid_source,
        }

        with self.assertRaisesRegex(ValueError, "must declare only WallClimbModule"):
            GeminiFeatureGenerator(FakeStructuredJsonClient({}))._validate_module(
                module,
                {"generated_feature_01": requirement},
            )

    def test_generated_source_rejects_runtime_delegation_to_empty_method(self) -> None:
        requirement = {"feature_id": "feature_01", "feature_description": "문을 연다."}
        invalid_source = GENERATED_SOURCE.replace(
            "var direction = Vector2.right * Mathf.Sign(input.Movement.x);",
            "ApplyUpgrade();",
        )
        namespace_end = invalid_source.rfind("}\n")
        class_end = invalid_source.rfind("}\n", 0, namespace_end)
        invalid_source = (
            invalid_source[:class_end]
            + "        private void ApplyUpgrade()\n"
            + "        {\n"
            + "            // TODO: implement later\n"
            + "        }\n"
            + invalid_source[class_end:]
        )
        module = {
            "module_id": "generated_feature_01",
            **requirement,
            "class_name": "WallClimbModule",
            "source_code": invalid_source,
        }

        with self.assertRaisesRegex(ValueError, "empty methods.*ApplyUpgrade"):
            GeminiFeatureGenerator(FakeStructuredJsonClient({}))._validate_module(
                module,
                {"generated_feature_01": requirement},
            )

    def test_default_feature_provider_is_local_qwen(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            generator = create_feature_generator_from_environment()
        self.assertIsInstance(generator.client, LocalAIJsonClient)
        self.assertEqual(generator.client.model, "qwen2.5-coder-7b-q5-k-m")
        self.assertEqual(generator.client.timeout_seconds, 180)
        self.assertEqual(generator.client.structured_attempts, 1)
        self.assertEqual(generator.client.max_attempts, 1)
        self.assertEqual(generator.plan_attempts, 2)
        self.assertEqual(generator.source_attempts, 2)

    def test_openai_key_selects_openai_feature_provider(self) -> None:
        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "test-openai-key", "OPENAI_MODEL": "gpt-4.1"},
            clear=True,
        ):
            generator = create_feature_generator_from_environment()

        self.assertIsInstance(generator.client, OpenAIJsonClient)
        self.assertEqual(generator.client.model, "gpt-4.1")

    def test_explicit_local_provider_overrides_openai_key(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "test-openai-key",
                "MAINFLOW_FEATURE_PROVIDER": "local",
            },
            clear=True,
        ):
            generator = create_feature_generator_from_environment()

        self.assertIsInstance(generator.client, LocalAIJsonClient)

    def test_openai_request_uses_strict_json_schema(self) -> None:
        api_response = {
            "id": "resp_test",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps({"generated_modules": []}),
                        }
                    ],
                }
            ],
        }
        response = MagicMock()
        response.read.return_value = json.dumps(api_response).encode("utf-8")
        response_context = MagicMock()
        response_context.__enter__.return_value = response

        with patch(
            "game_pipeline.gemini_feature_generator.urllib.request.urlopen",
            return_value=response_context,
        ) as urlopen:
            result = OpenAIJsonClient(api_key="test-key").generate_json(
                "generate",
                GENERATED_MODULE_SCHEMA,
            )

        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, "https://api.openai.com/v1/responses")
        self.assertEqual(request.headers["Authorization"], "Bearer test-key")
        self.assertEqual(payload["model"], "gpt-6.1-terra")
        self.assertEqual(payload["max_output_tokens"], 8192)
        self.assertFalse(payload["store"])
        self.assertTrue(payload["text"]["format"]["strict"])
        self.assertEqual(
            payload["text"]["format"]["schema"],
            GENERATED_MODULE_SCHEMA,
        )
        self.assertEqual(result, {"generated_modules": []})

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
        self.assertEqual(payload["max_tokens"], 8192)
        self.assertEqual(payload["response_format"]["type"], "json_schema")
        self.assertEqual(
            payload["response_format"]["json_schema"]["schema"],
            {"type": "object"},
        )
        self.assertEqual(result, {"generated_modules": []})

    def test_gemma_uses_json_object_mode_with_schema_in_prompt(self) -> None:
        api_response = {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": '{"generated_modules":[]}'},
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
            LocalAIJsonClient(model="gemma4-12b-it-qat-q4-0").generate_json(
                "generate", {"type": "object"}
            )

        payload = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertIn("JSON_SCHEMA=", payload["messages"][0]["content"])

    def test_localai_retries_malformed_structured_response(self) -> None:
        invalid = {"choices": [{"finish_reason": "stop", "message": {"content": "{broken"}}]}
        valid = {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": 'Result: {"generated_modules": []}'},
                }
            ]
        }
        contexts = []
        for payload in (invalid, valid):
            response = MagicMock()
            response.read.return_value = json.dumps(payload).encode("utf-8")
            context = MagicMock()
            context.__enter__.return_value = response
            contexts.append(context)

        with (
            patch(
                "game_pipeline.gemini_feature_generator.urllib.request.urlopen",
                side_effect=contexts,
            ) as urlopen,
            patch("game_pipeline.gemini_feature_generator.append_pipeline_error") as error_log,
        ):
            result = LocalAIJsonClient().generate_json("generate", {"type": "object"})

        self.assertEqual(urlopen.call_count, 2)
        self.assertEqual(result, {"generated_modules": []})
        retry_payload = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(len(retry_payload["messages"]), 2)
        reasons = [call.args[1] for call in error_log.call_args_list]
        self.assertIn("STRUCTURED_OUTPUT_INVALID", reasons)
        self.assertIn("STRUCTURED_OUTPUT_RECOVERED", reasons)

    def test_localai_salvages_complete_json_before_length_cutoff(self) -> None:
        api_response = {
            "choices": [
                {
                    "finish_reason": "length",
                    "message": {
                        "content": '{"generated_modules":[]} trailing unfinished {"extra":'
                    },
                }
            ]
        }
        response = MagicMock()
        response.read.return_value = json.dumps(api_response).encode("utf-8")
        response_context = MagicMock()
        response_context.__enter__.return_value = response

        with (
            patch(
                "game_pipeline.gemini_feature_generator.urllib.request.urlopen",
                return_value=response_context,
            ) as urlopen,
            patch("game_pipeline.gemini_feature_generator.append_pipeline_error") as error_log,
        ):
            result = LocalAIJsonClient(structured_attempts=1).generate_json(
                "generate", {"type": "object"}
            )

        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(result, {"generated_modules": []})
        reasons = [call.args[1] for call in error_log.call_args_list]
        self.assertEqual(reasons, ["MAX_OUTPUT_TOKEN_REACHED", "TOKEN_OUTPUT_RECOVERED"])

    def test_localai_request_includes_configured_reasoning_effort(self) -> None:
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

        with (
            patch.dict(os.environ, {"LOCAL_LLM_REASONING_EFFORT": "none"}, clear=True),
            patch(
                "game_pipeline.gemini_feature_generator.urllib.request.urlopen",
                return_value=response_context,
            ) as urlopen,
        ):
            LocalAIJsonClient.from_environment().generate_json(
                "generate",
                {"type": "object"},
            )

        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["reasoning_effort"], "none")

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

    def test_localai_rejects_oversized_prompt_before_http_request(self) -> None:
        client = LocalAIJsonClient(context_window_tokens=4096, max_output_tokens=2048)
        with (
            patch("game_pipeline.gemini_feature_generator.urllib.request.urlopen") as urlopen,
            patch("game_pipeline.gemini_feature_generator.append_pipeline_error") as error_log,
        ):
            with self.assertRaisesRegex(RuntimeError, "input budget before request"):
                client.generate_json("x" * 20_000, {"type": "object"})
        urlopen.assert_not_called()
        self.assertEqual(error_log.call_args.args[1], "INPUT_CONTEXT_TOKEN_OVERFLOW")

    def test_localai_logs_server_side_token_rejection(self) -> None:
        client = LocalAIJsonClient(structured_attempts=1)
        with (
            patch.object(
                LocalAIJsonClient,
                "_request_with_retry",
                side_effect=RuntimeError("HTTP 400: max_tokens exceeds context length"),
            ),
            patch("game_pipeline.gemini_feature_generator.append_pipeline_error") as error_log,
        ):
            with self.assertRaisesRegex(RuntimeError, "max_tokens exceeds context length"):
                client.generate_json("generate", {"type": "object"})

        self.assertEqual(error_log.call_args.args[1], "TOKEN_REQUEST_REJECTED")
        self.assertIn("estimated_input=", error_log.call_args.args[2])

    def test_localai_adapts_output_budget_to_fit_feature_prompt(self) -> None:
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
        client = LocalAIJsonClient(context_window_tokens=8192, max_output_tokens=4096)

        with patch(
            "game_pipeline.gemini_feature_generator.urllib.request.urlopen",
            return_value=response_context,
        ) as urlopen:
            client.generate_json("x" * 16_000, GENERATED_MODULE_SCHEMA)

        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertGreaterEqual(payload["max_tokens"], 1536)
        self.assertLess(payload["max_tokens"], 4096)

    def test_localai_planning_reserves_less_output_and_accepts_larger_input(self) -> None:
        api_response = {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": json.dumps({"implementation_plan": {}})},
                }
            ]
        }
        response = MagicMock()
        response.read.return_value = json.dumps(api_response).encode("utf-8")
        response_context = MagicMock()
        response_context.__enter__.return_value = response
        client = LocalAIJsonClient(context_window_tokens=8192, max_output_tokens=2048)

        with patch(
            "game_pipeline.gemini_feature_generator.urllib.request.urlopen",
            return_value=response_context,
        ) as urlopen:
            client.generate_json(
                "x" * 16_000,
                FEATURE_IMPLEMENTATION_PLAN_SCHEMA,
            )

        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["max_tokens"], 1024)

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

    def test_localai_planning_roles_use_bounded_defaults(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            condition = LocalAIJsonClient.from_environment(node_name="condition_feature_analysis")
            genre = LocalAIJsonClient.from_environment(node_name="genre_feature_enrichment")
            design = LocalAIJsonClient.from_environment(node_name="design_v2")
            blueprint = LocalAIJsonClient.from_environment(node_name="blueprint")
            feature_code = LocalAIJsonClient.from_environment(node_name="feature_code_generation")

        self.assertEqual(
            (condition.max_output_tokens, condition.structured_attempts, condition.max_attempts),
            (1024, 1, 1),
        )
        self.assertEqual((genre.max_output_tokens, genre.structured_attempts), (2048, 1))
        self.assertEqual((design.max_output_tokens, design.structured_attempts), (4096, 1))
        self.assertEqual((blueprint.max_output_tokens, blueprint.structured_attempts), (2048, 1))
        self.assertEqual(
            (
                feature_code.timeout_seconds,
                feature_code.max_output_tokens,
                feature_code.structured_attempts,
                feature_code.max_attempts,
            ),
            (180, 8192, 1, 1),
        )
        checklist = LocalAIJsonClient.from_environment(node_name="feature_checklist_generation")
        self.assertEqual((checklist.max_output_tokens, checklist.structured_attempts), (3072, 1))

    def test_localai_role_limits_can_be_overridden(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LLM_DESIGN_V2_MAX_OUTPUT_TOKENS": "3072",
                "LLM_DESIGN_V2_STRUCTURED_ATTEMPTS": "2",
                "LLM_DESIGN_V2_TIMEOUT_SECONDS": "90",
            },
            clear=True,
        ):
            client = LocalAIJsonClient.from_environment(node_name="design_v2")

        self.assertEqual(client.max_output_tokens, 3072)
        self.assertEqual(client.structured_attempts, 2)
        self.assertEqual(client.timeout_seconds, 90)

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

    def test_inferred_binding_requirement_does_not_generate_a_new_csharp_module(self) -> None:
        features: list[FeatureRequirement] = [
            {
                "feature_id": "genre-required-01",
                "name": "상시 체력 HUD",
                "description": "현재 체력과 최대 체력을 항상 표시한다.",
                "source_text": "장르 필수 기능 추론",
                "origin": "genre_inferred",
                "implementation_kind": "scene_binding",
                "target_mechanics": ["health_damage"],
            }
        ]

        plan = plan_feature_mechanics(features, "뱀서류")

        self.assertEqual(plan.mechanics, ["health_damage"])
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

    def test_unseen_feature_is_planned_before_code_and_preserves_scene_plan(self) -> None:
        features: list[FeatureRequirement] = [
            {
                "feature_id": "feature-01",
                "name": "사용자 지정 조건",
                "description": "버튼에 닿으면 문이 열린다.",
                "source_text": "버튼에 닿으면 문이 열린다.",
            }
        ]
        plan = plan_feature_mechanics(features, "플랫포머")
        design = build_game_logic_design(
            normalize_game_spec(
                "플랫포머",
                {"features": plan.game_features, "mechanics": plan.mechanics},
            )
        )
        client = PlanningStructuredJsonClient()

        modules = GeminiFeatureGenerator(client).generate(
            design,
            plan.generation_requirements,
        )

        self.assertEqual(len(client.prompts), 2)
        self.assertIn("Do not write C# yet", client.prompts[0])
        self.assertIn("feature_implementation_plan", client.prompts[1])
        self.assertEqual(
            [item["object_id"] for item in modules[0]["implementation_plan"]["scene_objects"]],
            ["gate_switch", "blocking_gate"],
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

    def test_new_common_features_reuse_catalogued_modules(self) -> None:
        names = [
            "체력 및 피해",
            "옵션",
            "아이템 수집",
            "타워 업그레이드",
            "플레이어 스탯",
            "점수 기록",
            "게임 타이머",
            "저장 및 불러오기",
        ]
        features: list[FeatureRequirement] = [
            {
                "feature_id": f"feature-{index:02d}",
                "name": name,
                "description": name,
                "source_text": name,
            }
            for index, name in enumerate(names, start=1)
        ]

        plan = plan_feature_mechanics(features, "타워 디펜스")

        self.assertEqual(
            plan.mechanics,
            [
                "health_damage",
                "options",
                "item_collect",
                "tower_upgrade",
                "player_stats",
                "score",
                "game_timer",
                "save_load",
            ],
        )
        self.assertFalse(plan.generation_requirements)

    def test_survivor_level_up_choices_reuse_existing_modules(self) -> None:
        description = "경험치를 모아 레벨이 오르면 무작위 특전 3개 중 하나를 선택한다"
        features: list[FeatureRequirement] = [
            {
                "feature_id": "feature-03",
                "name": "사용자 지정 조건",
                "description": description,
                "source_text": description,
            }
        ]

        plan = plan_feature_mechanics(features, "뱀서류")

        self.assertEqual(plan.mechanics, ["experience", "rarity", "upgrade_selection"])
        self.assertFalse(plan.generation_requirements)

    def test_explicit_survivor_request_does_not_inherit_preset_attack(self) -> None:
        features: list[FeatureRequirement] = [
            {
                "feature_id": "feature-01",
                "name": "사용자 지정 조건",
                "description": "플레이어 주변을 회전하는 검이 적에게 피해를 준다.",
                "source_text": "플레이어 주변을 회전하는 검이 적에게 피해를 준다.",
            }
        ]

        plan = plan_feature_mechanics(features, "뱀서류")
        spec = normalize_game_spec(
            "뱀서류",
            {"features": plan.game_features, "mechanics": plan.mechanics},
        )

        self.assertNotIn("auto_target", spec["mechanics"])
        self.assertNotIn("projectile", spec["mechanics"])
        self.assertEqual([item["feature_id"] for item in spec["features"]], ["feature_01"])
        requirement = plan.generation_requirements["generated_feature_01"]
        self.assertEqual(requirement["must_preserve"], features[0]["description"])
        self.assertEqual(requirement["source_text"], features[0]["source_text"])

    def test_specific_attack_requirement_supersedes_generic_keyword_match(self) -> None:
        source_text = "적을 자동 공격한다. 플레이어 주변을 회전하는 검이 적에게 피해를 준다."
        features: list[FeatureRequirement] = [
            {
                "feature_id": "feature-01",
                "name": "자동 공격",
                "description": "조건을 만족하면 공격이 자동으로 실행된다.",
                "source_text": source_text,
            },
            {
                "feature_id": "feature-02",
                "name": "사용자 지정 조건",
                "description": "플레이어 주변을 회전하는 검이 적에게 피해를 준다.",
                "source_text": source_text,
            },
        ]

        plan = plan_feature_mechanics(features, "뱀서류")

        self.assertEqual([item["feature_id"] for item in plan.game_features], ["feature_02"])
        self.assertEqual(list(plan.generation_requirements), ["generated_feature_02"])

    def test_semantic_validation_rejects_compilable_but_missing_damage(self) -> None:
        requirement = {
            "feature_id": "feature_01",
            "feature_description": "플레이어 주변을 회전하는 검이 적에게 피해를 준다.",
            "must_preserve": "플레이어 주변을 회전하는 검이 적에게 피해를 준다.",
            "acceptance_criteria": "검의 충돌로 적 체력이 감소한다.",
        }
        module = {
            "module_id": "generated_feature_01",
            "feature_id": "feature_01",
            "feature_description": requirement["feature_description"],
            "class_name": "WallClimbModule",
            "source_code": GENERATED_SOURCE,
        }

        with self.assertRaisesRegex(ValueError, "does not realize required behavior"):
            GeminiFeatureGenerator(FakeStructuredJsonClient({}))._validate_module(
                module,
                {"generated_feature_01": requirement},
            )

    def test_semantic_validation_does_not_make_game_over_apply_damage(self) -> None:
        requirement = {
            "feature_id": "feature_03",
            "feature_description": "플레이어는 체력이 모두 닳을 경우 게임 오버",
            "must_preserve": (
                "플레이어가 피해를 받을 때 체력 변화를 표시하고, 체력이 0이면 게임 오버"
            ),
            "acceptance_criteria": "체력이 0이 되면 게임 오버 화면이 표시된다.",
        }

        GeminiFeatureGenerator._validate_requirement_semantics(
            GENERATED_SOURCE,
            "generated_feature_03",
            requirement,
        )

    def test_semantic_validation_accepts_rotation_configuration_delegation(self) -> None:
        requirement = {
            "feature_id": "feature_06",
            "feature_description": "특전으로 검의 개수, 크기, 회전속도를 강화한다",
            "must_preserve": "선택한 특전이 실제 회전 검에 적용된다.",
            "acceptance_criteria": "검의 회전 속도 변경을 플레이 중 확인할 수 있다.",
        }
        delegated_source = (
            GENERATED_SOURCE
            + "\n// sibling integration\n"
            + "swords.ConfigureSword(swordCount, swordSize, swordRotationSpeed);\n"
        )

        GeminiFeatureGenerator._validate_requirement_semantics(
            delegated_source,
            "generated_feature_06",
            requirement,
        )

    def test_semantic_validation_rejects_disabled_behavior_placeholder(self) -> None:
        requirement = {
            "feature_id": "feature_01",
            "feature_description": "벽을 타고 오른다.",
        }
        module = {
            "module_id": "generated_feature_01",
            "feature_id": "feature_01",
            "feature_description": requirement["feature_description"],
            "class_name": "WallClimbModule",
            "source_code": GENERATED_SOURCE.replace(
                "IsFeatureBound = true;",
                'Debug.LogWarning("bindings unavailable; affected behaviors are disabled");\n'
                "            IsFeatureBound = true;",
            ),
        }

        with self.assertRaisesRegex(ValueError, "disables required behavior"):
            GeminiFeatureGenerator(FakeStructuredJsonClient({}))._validate_module(
                module,
                {"generated_feature_01": requirement},
            )

    def test_generated_source_accepts_event_driven_runtime_behavior(self) -> None:
        requirement = {"feature_id": "feature_01", "feature_description": "문을 연다."}
        event_source = GENERATED_SOURCE.replace(
            "var direction = Vector2.right * Mathf.Sign(input.Movement.x);",
            "// event-driven feature",
        ).replace(
            "        }\n    }\n}",
            "        }\n\n"
            "        private void OnTriggerEnter2D(Collider2D other)\n"
            "        {\n"
            "            playerBody.gravityScale = Mathf.Max(0f, playerBody.gravityScale);\n"
            "        }\n"
            "    }\n}",
        )
        module = {
            "module_id": "generated_feature_01",
            **requirement,
            "class_name": "WallClimbModule",
            "source_code": event_source,
        }

        validated = GeminiFeatureGenerator(FakeStructuredJsonClient({}))._validate_module(
            module,
            {"generated_feature_01": requirement},
        )

        self.assertEqual(validated["module_id"], "generated_feature_01")

    def test_generated_source_recovers_double_encoded_csharp(self) -> None:
        requirement = {
            "feature_id": "feature_01",
            "feature_description": "문을 연다.",
        }
        encoded_source = GENERATED_SOURCE.replace("\n", "\\n").replace('"', '\\"')
        encoded_source += '"}]} '
        module = {
            "module_id": "generated_feature_01",
            **requirement,
            "class_name": "WallClimbModule",
            "source_code": encoded_source,
        }

        validated = GeminiFeatureGenerator(FakeStructuredJsonClient({}))._validate_module(
            module,
            {"generated_feature_01": requirement},
        )

        self.assertIn("\nnamespace TeamIdle.GameTemplate.Generated\n", validated["source_code"])
        self.assertFalse(validated["source_code"].rstrip().endswith('"}]}'))

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
        self.assertEqual(client.calls, 2)

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
        self.assertEqual(client.calls, 2)

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

    def test_generated_source_normalizes_known_enemy_tag_lookup(self) -> None:
        requirement = {"feature_id": "feature_01", "feature_description": "벽을 탄다."}
        invalid_source = GENERATED_SOURCE.replace(
            "var direction = Vector2.right * Mathf.Sign(input.Movement.x);",
            'var direction = gameObject.CompareTag("Enemy") ? Vector2.up : Vector2.right;',
        )
        module = {
            "module_id": "generated_feature_01",
            **requirement,
            "class_name": "WallClimbModule",
            "source_code": invalid_source,
        }

        validated = GeminiFeatureGenerator(FakeStructuredJsonClient({}))._validate_module(
            module,
            {"generated_feature_01": requirement},
        )

        self.assertNotIn("CompareTag", validated["source_code"])
        self.assertIn("gameObject.layer == 8", validated["source_code"])

    def test_generated_source_normalizes_undeclared_custom_tag_lookup(self) -> None:
        requirement = {"feature_id": "feature_01", "feature_description": "벽을 탄다."}
        invalid_source = GENERATED_SOURCE.replace(
            "var direction = Vector2.right * Mathf.Sign(input.Movement.x);",
            'var direction = gameObject.CompareTag("Tower") ? Vector2.up : Vector2.right;',
        )
        module = {
            "module_id": "generated_feature_01",
            **requirement,
            "class_name": "WallClimbModule",
            "source_code": invalid_source,
        }

        validated = GeminiFeatureGenerator(FakeStructuredJsonClient({}))._validate_module(
            module,
            {"generated_feature_01": requirement},
        )

        self.assertNotIn("CompareTag", validated["source_code"])
        self.assertIn('gameObject.name == "Tower"', validated["source_code"])

    def test_generated_source_normalizes_asset_registry_get_prefab_hallucination(self) -> None:
        requirement = {"feature_id": "feature_01", "feature_description": "벽을 탄다."}
        source = GENERATED_SOURCE.replace(
            "private GeneratedFeatureBindingContext bindingContext;",
            "private GeneratedFeatureBindingContext bindingContext;\n"
            "        private GameObject wallPrefab;",
        ).replace(
            "bindingContext = context;",
            "bindingContext = context;\n"
            '            wallPrefab = context.GetModule<AssetRegistryModule>().GetPrefab("wall");',
        )
        module = {
            "module_id": "generated_feature_01",
            **requirement,
            "class_name": "WallClimbModule",
            "source_code": source,
        }

        validated = GeminiFeatureGenerator(FakeStructuredJsonClient({}))._validate_module(
            module,
            {"generated_feature_01": requirement},
        )

        self.assertNotIn("GetPrefab", validated["source_code"])

    def test_generated_source_falls_back_when_registry_prefab_is_missing(self) -> None:
        requirement = {"feature_id": "feature_01", "feature_description": "벽을 탄다."}
        source = GENERATED_SOURCE.replace(
            "private GeneratedFeatureBindingContext bindingContext;",
            "private GeneratedFeatureBindingContext bindingContext;\n"
            "        private GameObject wallPrefab;",
        ).replace(
            "bindingContext = context;",
            "bindingContext = context;\n"
            "            context.GetModule<AssetRegistryModule>()"
            '.TryGet<GameObject>("wall", out wallPrefab);\n'
            "            GameObject wall = Instantiate("
            "wallPrefab, context.Environment.position, Quaternion.identity);",
        )
        module = {
            "module_id": "generated_feature_01",
            **requirement,
            "class_name": "WallClimbModule",
            "source_code": source,
        }

        validated = GeminiFeatureGenerator(FakeStructuredJsonClient({}))._validate_module(
            module,
            {"generated_feature_01": requirement},
        )

        self.assertIn(
            'wallPrefab == null ? new GameObject("wall") : Instantiate(',
            validated["source_code"],
        )
        self.assertIn(
            'TryGet<GameObject>("wall", out wallPrefab);',
            validated["source_code"],
        )

    def test_generated_source_maps_lives_owner_to_base_defense_module(self) -> None:
        requirement = {"feature_id": "feature_01", "feature_description": "기지가 파괴되면 패배"}
        source = (
            GENERATED_SOURCE.replace(
                "private GeneratedFeatureBindingContext bindingContext;",
                "private GeneratedFeatureBindingContext bindingContext;\n"
                "        private HealthDamageSystem healthSystem;",
            )
            .replace(
                "bindingContext = context;",
                "bindingContext = context;\n"
                "            healthSystem = context.GetModule<HealthDamageSystem>();",
            )
            .replace(
                "var direction = Vector2.right * Mathf.Sign(input.Movement.x);",
                "var direction = healthSystem.Lives <= 0 ? Vector2.zero : Vector2.right;",
            )
        )
        module = {
            "module_id": "generated_feature_01",
            **requirement,
            "class_name": "WallClimbModule",
            "source_code": source,
        }

        validated = GeminiFeatureGenerator(FakeStructuredJsonClient({}))._validate_module(
            module,
            {"generated_feature_01": requirement},
        )

        self.assertNotIn("HealthDamageSystem ", validated["source_code"])
        self.assertIn("BaseDefenseSystemModule healthSystem", validated["source_code"])
        self.assertIn(
            "context.GetModule<BaseDefenseSystemModule>()",
            validated["source_code"],
        )

    def test_generated_source_restores_project_module_suffix_from_index(self) -> None:
        requirement = {"feature_id": "feature_01", "feature_description": "승패 이벤트를 처리"}
        source = GENERATED_SOURCE.replace(
            "private GeneratedFeatureBindingContext bindingContext;",
            "private GeneratedFeatureBindingContext bindingContext;\n"
            "        private EventRuleEngine rules;",
        ).replace(
            "bindingContext = context;",
            "bindingContext = context;\n            rules = context.GetModule<EventRuleEngine>();",
        )
        module = {
            "module_id": "generated_feature_01",
            **requirement,
            "class_name": "WallClimbModule",
            "source_code": source,
        }

        validated = GeminiFeatureGenerator(FakeStructuredJsonClient({}))._validate_module(
            module,
            {"generated_feature_01": requirement},
        )

        self.assertIn("EventRuleEngineModule rules", validated["source_code"])
        self.assertIn(
            "context.GetModule<EventRuleEngineModule>()",
            validated["source_code"],
        )
        self.assertIn(
            "using TeamIdle.GameTemplate.Common;",
            validated["source_code"],
        )

    def test_generated_source_rejects_members_missing_from_project_index(self) -> None:
        requirement = {"feature_id": "feature_01", "feature_description": "승패 이벤트를 처리"}
        source = (
            GENERATED_SOURCE.replace(
                "private GeneratedFeatureBindingContext bindingContext;",
                "private GeneratedFeatureBindingContext bindingContext;\n"
                "        private EventRuleEngineModule rules;",
            )
            .replace(
                "input = context.GetModule<InputAdapterModule>();",
                "input = context.GetModule<InputAdapterModule>();\n"
                "            rules = context.GetModule<EventRuleEngineModule>();",
            )
            .replace(
                "var direction = Vector2.right * Mathf.Sign(input.Movement.x);",
                'rules.TriggerEvent("GameWon");\n            var direction = Vector2.right;',
            )
        )
        module = {
            "module_id": "generated_feature_01",
            **requirement,
            "class_name": "WallClimbModule",
            "source_code": source,
        }

        with self.assertRaisesRegex(ValueError, "EventRuleEngineModule.TriggerEvent"):
            GeminiFeatureGenerator(FakeStructuredJsonClient({}))._validate_module(
                module,
                {"generated_feature_01": requirement},
            )

    def test_generated_source_rejects_invented_binding_context_member(self) -> None:
        requirement = {"feature_id": "feature_01", "feature_description": "웨이브를 확인"}
        source = GENERATED_SOURCE.replace(
            "var direction = Vector2.right * Mathf.Sign(input.Movement.x);",
            "var direction = bindingContext.WaveSpawnerModule == null "
            "? Vector2.zero : Vector2.right;",
        )
        module = {
            "module_id": "generated_feature_01",
            **requirement,
            "class_name": "WallClimbModule",
            "source_code": source,
        }

        with self.assertRaisesRegex(
            ValueError,
            "GeneratedFeatureBindingContext.WaveSpawnerModule",
        ):
            GeminiFeatureGenerator(FakeStructuredJsonClient({}))._validate_module(
                module,
                {"generated_feature_01": requirement},
            )

    def test_generated_source_does_not_mistake_collider_variable_for_3d_type(self) -> None:
        requirement = {"feature_id": "feature_01", "feature_description": "벽을 탄다."}
        source = GENERATED_SOURCE.replace(
            "var direction = Vector2.right * Mathf.Sign(input.Movement.x);",
            "var swordCollider = playerBody.GetComponent<Collider2D>();\n"
            "            var direction = swordCollider == null ? Vector2.right : Vector2.up;",
        )
        module = {
            "module_id": "generated_feature_01",
            **requirement,
            "class_name": "WallClimbModule",
            "source_code": source,
        }

        validated = GeminiFeatureGenerator(FakeStructuredJsonClient({}))._validate_module(
            module,
            {"generated_feature_01": requirement},
        )

        self.assertIn("swordCollider", validated["source_code"])

    def test_generated_source_repairs_malformed_identity_attribute(self) -> None:
        requirement = {"feature_id": "feature_01", "feature_description": "벽을 탄다."}
        source = GENERATED_SOURCE.replace(
            '[GeneratedGameModule("generated_feature_01")]',
            '[GeneratedGameModule("generated_feature_01")',
        )
        module = {
            "module_id": "generated_feature_01",
            **requirement,
            "class_name": "WallClimbModule",
            "source_code": source,
        }

        validated = GeminiFeatureGenerator(FakeStructuredJsonClient({}))._validate_module(
            module,
            {"generated_feature_01": requirement},
        )

        self.assertIn(
            '[GeneratedGameModule("generated_feature_01")]',
            validated["source_code"],
        )

    def test_implementation_plan_drops_conceptual_non_unity_components(self) -> None:
        requirement = {"feature_id": "feature_01", "feature_description": "기지 체력 감시"}
        raw = {
            "implementation_plan": {
                "module_id": "generated_feature_01",
                "feature_id": "feature_01",
                "behavior_summary": "기지 체력이 0이면 패배한다.",
                "binding_steps": ["기지를 연결한다"],
                "scene_objects": [
                    {
                        "object_id": "base_health_monitor",
                        "parent": "entities",
                        "purpose": "기지 체력 상태를 감시한다",
                        "components": ["GameObject", "HealthDamageSystem", "Timer"],
                    }
                ],
                "runtime_flow": ["체력을 감시한다"],
                "acceptance_checks": ["체력 0에서 패배한다"],
            }
        }

        plan = GeminiFeatureGenerator._validate_implementation_plan(
            raw,
            "generated_feature_01",
            requirement,
        )

        self.assertEqual(plan["scene_objects"][0]["components"], ["GameObject"])

    def test_implementation_plan_bounds_scene_objects_to_feature_scope(self) -> None:
        requirement = {"feature_id": "feature_01", "feature_description": "두 타워를 설치한다"}
        scene_objects = [
            {
                "object_id": object_id,
                "parent": "entities",
                "purpose": object_id,
                "components": ["GameObject"],
            }
            for object_id in (
                "arrow_tower",
                "magic_tower",
                "projectile",
                "enemy",
                "base",
                "global_hud",
            )
        ]
        raw = {
            "implementation_plan": {
                "module_id": "generated_feature_01",
                "feature_id": "feature_01",
                "behavior_summary": "서로 다른 타워를 설치한다.",
                "binding_steps": ["타워를 생성한다"],
                "scene_objects": scene_objects,
                "runtime_flow": ["타워를 선택하고 설치한다"],
                "acceptance_checks": ["두 타워가 설치된다"],
            }
        }

        plan = GeminiFeatureGenerator._validate_implementation_plan(
            raw,
            "generated_feature_01",
            requirement,
        )

        self.assertEqual(
            [item["object_id"] for item in plan["scene_objects"]],
            ["arrow_tower", "magic_tower", "projectile"],
        )

    def test_generated_source_accepts_binding_context_environment_root(self) -> None:
        requirement = {"feature_id": "feature_01", "feature_description": "벽을 탄다."}
        source = GENERATED_SOURCE.replace(
            "input = context.GetModule<InputAdapterModule>();",
            "var environmentRoot = context.Environment;\n"
            "            input = context.GetModule<InputAdapterModule>();",
        )
        module = {
            "module_id": "generated_feature_01",
            **requirement,
            "class_name": "WallClimbModule",
            "source_code": source,
        }

        validated = GeminiFeatureGenerator(FakeStructuredJsonClient({}))._validate_module(
            module,
            {"generated_feature_01": requirement},
        )

        self.assertIn("context.Environment", validated["source_code"])

    def test_generated_source_repairs_host_owned_binding_completion(self) -> None:
        requirement = {"feature_id": "feature_01", "feature_description": "벽을 탄다."}
        source = GENERATED_SOURCE.replace("            IsFeatureBound = true;\n", "")
        module = {
            "module_id": "generated_feature_01",
            **requirement,
            "class_name": "WallClimbModule",
            "source_code": source,
        }

        validated = GeminiFeatureGenerator(FakeStructuredJsonClient({}))._validate_module(
            module,
            {"generated_feature_01": requirement},
        )

        self.assertIn("IsFeatureBound = true;", validated["source_code"])

    def test_generated_source_normalizes_transform_find_for_game_object_field(self) -> None:
        requirement = {"feature_id": "feature_01", "feature_description": "벽을 탄다."}
        source = GENERATED_SOURCE.replace(
            "private GeneratedFeatureBindingContext bindingContext;",
            "private GeneratedFeatureBindingContext bindingContext;\n"
            "        private GameObject blockedArea;",
        ).replace(
            "bindingContext = context;",
            "bindingContext = context;\n"
            '            blockedArea = context.Environment.Find("blocked");',
        )
        module = {
            "module_id": "generated_feature_01",
            **requirement,
            "class_name": "WallClimbModule",
            "source_code": source,
        }

        validated = GeminiFeatureGenerator(FakeStructuredJsonClient({}))._validate_module(
            module,
            {"generated_feature_01": requirement},
        )

        self.assertIn(
            'blockedArea = context.Environment.Find("blocked")?.gameObject '
            '?? new GameObject("blockedArea");',
            validated["source_code"],
        )

    def test_generated_source_makes_existing_transform_find_game_object_null_safe(self) -> None:
        requirement = {"feature_id": "feature_01", "feature_description": "벽을 탄다."}
        source = GENERATED_SOURCE.replace(
            "private GeneratedFeatureBindingContext bindingContext;",
            "private GeneratedFeatureBindingContext bindingContext;\n"
            "        private GameObject blockedArea;",
        ).replace(
            "bindingContext = context;",
            "bindingContext = context;\n"
            '            blockedArea = context.Environment.Find("blocked").gameObject;',
        )
        module = {
            "module_id": "generated_feature_01",
            **requirement,
            "class_name": "WallClimbModule",
            "source_code": source,
        }

        validated = GeminiFeatureGenerator(FakeStructuredJsonClient({}))._validate_module(
            module,
            {"generated_feature_01": requirement},
        )

        self.assertIn(
            'blockedArea = context.Environment.Find("blocked")?.gameObject '
            '?? new GameObject("blockedArea");',
            validated["source_code"],
        )

    def test_generated_source_removes_game_object_from_transform_find_assignment(self) -> None:
        requirement = {"feature_id": "feature_01", "feature_description": "벽을 탄다."}
        source = GENERATED_SOURCE.replace(
            "private GeneratedFeatureBindingContext bindingContext;",
            "private GeneratedFeatureBindingContext bindingContext;\n"
            "        private Transform blockedArea;",
        ).replace(
            "bindingContext = context;",
            "bindingContext = context;\n"
            '            blockedArea = context.Environment.Find("blocked").gameObject;',
        )
        module = {
            "module_id": "generated_feature_01",
            **requirement,
            "class_name": "WallClimbModule",
            "source_code": source,
        }

        validated = GeminiFeatureGenerator(FakeStructuredJsonClient({}))._validate_module(
            module,
            {"generated_feature_01": requirement},
        )

        self.assertIn(
            'blockedArea = context.Environment.Find("blocked");',
            validated["source_code"],
        )
        self.assertNotIn(
            'blockedArea = context.Environment.Find("blocked").gameObject;',
            validated["source_code"],
        )

    def test_generated_source_rejects_unity_event_get_invocation_list(self) -> None:
        requirement = {"feature_id": "feature_01", "feature_description": "벽을 탄다."}
        source = GENERATED_SOURCE.replace(
            "var direction = Vector2.right * Mathf.Sign(input.Movement.x);",
            "var listeners = button.onClick.GetInvocationList();\n"
            "            var direction = Vector2.right * Mathf.Sign(input.Movement.x);",
        ).replace(
            "private GeneratedFeatureBindingContext bindingContext;",
            "private GeneratedFeatureBindingContext bindingContext;\n"
            "        private UnityEngine.UI.Button button;",
        )
        module = {
            "module_id": "generated_feature_01",
            **requirement,
            "class_name": "WallClimbModule",
            "source_code": source,
        }

        with self.assertRaisesRegex(ValueError, "GetInvocationList"):
            GeminiFeatureGenerator(FakeStructuredJsonClient({}))._validate_module(
                module,
                {"generated_feature_01": requirement},
            )

    def test_generated_source_adds_unity_ui_namespace_for_button(self) -> None:
        requirement = {"feature_id": "feature_01", "feature_description": "벽을 탄다."}
        source = GENERATED_SOURCE.replace(
            "private GeneratedFeatureBindingContext bindingContext;",
            "private GeneratedFeatureBindingContext bindingContext;\n"
            "        private Button button;",
        )
        module = {
            "module_id": "generated_feature_01",
            **requirement,
            "class_name": "WallClimbModule",
            "source_code": source,
        }

        validated = GeminiFeatureGenerator(FakeStructuredJsonClient({}))._validate_module(
            module,
            {"generated_feature_01": requirement},
        )

        self.assertIn("using UnityEngine.UI;", validated["source_code"])

    def test_generated_source_does_not_treat_texture2d_as_ui_text(self) -> None:
        requirement = {"feature_id": "feature_01", "feature_description": "벽을 탄다."}
        source = GENERATED_SOURCE.replace(
            "private GeneratedFeatureBindingContext bindingContext;",
            "private GeneratedFeatureBindingContext bindingContext;\n"
            "        private Texture2D debugTexture;",
        )
        module = {
            "module_id": "generated_feature_01",
            **requirement,
            "class_name": "WallClimbModule",
            "source_code": source,
        }

        validated = GeminiFeatureGenerator(FakeStructuredJsonClient({}))._validate_module(
            module,
            {"generated_feature_01": requirement},
        )

        self.assertNotIn("using UnityEngine.UI;", validated["source_code"])

    def test_generation_attempt_recorder_preserves_complete_failed_candidate(self) -> None:
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

        records: list[Mapping[str, Any]] = []
        generator = GeminiFeatureGenerator(
            SequenceStructuredJsonClient([payload(invalid_source), payload(GENERATED_SOURCE)]),
            attempt_recorder=records.append,
        )

        generator.generate(design, plan.generation_requirements)

        self.assertEqual([record["status"] for record in records], ["failed", "passed"])
        failed_source = records[0]["candidate"]["generated_modules"][0]["source_code"]
        self.assertEqual(failed_source, invalid_source)

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

        with self.assertRaisesRegex(ValueError, "PlatformerMovementModule.moveSpeed"):
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
        client.context_window_tokens = 8192
        modules = GeminiFeatureGenerator(client).generate(
            design,
            plan.generation_requirements,
        )

        self.assertEqual(len(modules), 1)
        self.assertEqual(len(client.prompts), 2)
        self.assertIn("previous_source_code", client.prompts[1])
        self.assertIn("referenced_project_apis", client.prompts[1])
        self.assertIn("required_source_skeleton", client.prompts[1])
        self.assertIn(
            '[GeneratedGameModule(\\"generated_feature_01\\")]',
            client.prompts[1],
        )
        self.assertIn("GENERATED_SOURCE_VALIDATION_FAILED", client.prompts[1])
        self.assertIn("method-local context", client.prompts[1])
        self.assertIn("context.Player.transform.localScale.x", client.prompts[1])
        self.assertLess(_estimate_tokens(client.prompts[1]), 5632)

    def test_repeated_identical_invalid_candidate_stops_early(self) -> None:
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
            "playerBody.position",
            "context.Player.transform.position",
        )
        payload = {
            "generated_modules": [
                {
                    "module_id": "generated_feature_01",
                    "feature_id": "feature_01",
                    "feature_description": "벽을 탄다.",
                    "class_name": "WallClimbModule",
                    "source_code": invalid_source,
                }
            ]
        }
        client = FakeStructuredJsonClient(payload)

        with self.assertRaisesRegex(ValueError, "method-local context"):
            GeminiFeatureGenerator(client, source_attempts=3).generate(
                design,
                plan.generation_requirements,
            )

        self.assertEqual(client.calls, 2)

    def test_identical_duplicate_modules_are_collapsed(self) -> None:
        requirement = {
            "feature_id": "feature_01",
            "feature_description": "벽을 탄다.",
        }
        module = {
            "module_id": "generated_feature_01",
            **requirement,
            "class_name": "WallClimbModule",
            "source_code": GENERATED_SOURCE,
        }

        modules = GeminiFeatureGenerator(FakeStructuredJsonClient({}))._parse_response(
            {"generated_modules": [module, module]},
            ["generated_feature_01"],
            {"generated_feature_01": requirement},
        )

        self.assertEqual(len(modules), 1)

    def test_known_player_game_object_position_is_normalized(self) -> None:
        requirement = {
            "feature_id": "feature_01",
            "feature_description": "벽을 탄다.",
        }
        source = GENERATED_SOURCE.replace(
            "playerBody.position",
            "bindingContext.Player.position",
        )
        module = {
            "module_id": "generated_feature_01",
            **requirement,
            "class_name": "WallClimbModule",
            "source_code": source,
        }

        validated = GeminiFeatureGenerator(FakeStructuredJsonClient({}))._validate_module(
            module,
            {"generated_feature_01": requirement},
        )

        self.assertIn("bindingContext.Player.transform.position", validated["source_code"])

    def test_feature_deadline_caps_transport_timeout(self) -> None:
        api_response = {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": json.dumps({"value": "ok"})},
                }
            ]
        }
        response = MagicMock()
        response.read.return_value = json.dumps(api_response).encode("utf-8")
        response_context = MagicMock()
        response_context.__enter__.return_value = response
        generator = GeminiFeatureGenerator(LocalAIJsonClient(timeout_seconds=300, max_attempts=2))
        generator.set_deadline(105.0)

        with (
            patch(
                "game_pipeline.gemini_feature_generator.time.monotonic",
                return_value=100.0,
            ),
            patch(
                "game_pipeline.gemini_feature_generator.urllib.request.urlopen",
                return_value=response_context,
            ) as urlopen,
        ):
            result = generator._generate_json("generate", {"type": "object"})

        self.assertEqual(result, {"value": "ok"})
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 5)

    def test_context_repair_retrieves_api_named_only_by_review_feedback(self) -> None:
        design = build_game_logic_design(normalize_game_spec("뱀서류"))
        module = {
            "module_id": "generated_feature_02",
            "feature_id": "feature_02",
            "feature_description": "경험치 보석을 수집하면 경험치가 증가한다.",
            "class_name": "GeneratedFeature02Module",
            "source_code": (
                "using TeamIdle.GameTemplate.Core;\n"
                "public sealed class Placeholder { private void Update() {} }"
            ),
        }
        requirement = {
            "feature_id": "feature_02",
            "feature_description": "경험치 보석을 수집하면 경험치가 증가한다.",
            "acceptance_criteria": "보석이 제거되고 경험치가 증가한다.",
        }
        feedback = {
            "issues": [
                {
                    "relative_path": "game/unity_project/GeneratedFeature02Module.cs",
                    "message": "ExperienceSystemModule is available but not connected.",
                    "suggested_fix": "Resolve ExperienceSystemModule and call Add on collection.",
                }
            ]
        }

        prompt = GeminiFeatureGenerator._build_repair_prompt(
            design,
            module,
            requirement,
            feedback,
            implementation_plan=None,
        )

        self.assertIn('"experience_system"', prompt)
        self.assertIn('"ExperienceSystemModule"', prompt)
        self.assertIn("public void Add(int amount)", prompt)
        self.assertIn("TeamIdle.GameTemplate.SurvivorLike", prompt)

    def test_context_repair_routes_each_review_finding_to_its_generated_module(self) -> None:
        feedback = {
            "summary": "multiple integration failures",
            "issues": [
                {
                    "relative_path": "game/unity_project/GeneratedFeature02Module.cs",
                    "message": "connect ExperienceSystemModule",
                    "suggested_fix": "call Add",
                },
                {
                    "relative_path": "game/unity_project/GeneratedFeature07Module.cs",
                    "message": "boss timer is missing",
                    "suggested_fix": "connect GameTimerModule",
                },
            ],
        }

        routed = GeminiFeatureGenerator._repair_feedback_for_module(
            feedback,
            {
                "module_id": "generated_feature_07",
                "class_name": "GeneratedFeature07Module",
            },
        )

        self.assertEqual(len(routed["issues"]), 1)
        self.assertIn("boss timer", routed["issues"][0]["message"])

    def test_unity_repair_compacts_duplicate_diagnostics_within_local_context(self) -> None:
        features: list[FeatureRequirement] = [
            {
                "feature_id": "feature-01",
                "name": "사용자 지정 조건",
                "description": "벽을 탄다.",
                "source_text": "벽을 탄다.",
            }
        ]
        plan = plan_feature_mechanics(features, "플랫포머")
        design = attach_generated_modules(
            build_game_logic_design(normalize_game_spec("플랫포머", {"mechanics": plan.mechanics})),
            [
                {
                    "module_id": "generated_feature_01",
                    "feature_id": "feature_01",
                    "feature_description": "벽을 탄다.",
                    "class_name": "WallClimbModule",
                    "source_code": GENERATED_SOURCE,
                }
            ],
        )
        client = SequenceStructuredJsonClient(
            [
                {
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
            ]
        )
        client.context_window_tokens = 8192
        repeated_error = "Assets/Generated.cs(15,17): error CS0246: Type could not be found\n" * 100

        modules = GeminiFeatureGenerator(client).repair(
            design,
            {
                "attempt": 0,
                "repair_target": "code",
                "failure_signature": "signature",
                "issues": [
                    {
                        "code": "UNITY_BATCH_VALIDATION_FAILED",
                        "severity": "error",
                        "message": repeated_error,
                    }
                ],
                "failed_checks": [
                    {"criterion_id": "unity.batchmode", "message": repeated_error, "passed": False}
                ],
                "diagnostics": repeated_error,
                "unity_log": "unused full log" * 10_000,
            },
        )

        self.assertEqual(len(modules), 1)
        self.assertLess(client.prompts[0].count("error CS0246"), 25)
        self.assertNotIn("unused full log", client.prompts[0])
        self.assertLess(_estimate_tokens(client.prompts[0]), 5632)

    def test_unity_repair_retries_when_cs0103_identifier_remains_undeclared(self) -> None:
        requirement = {"feature_id": "feature_01", "feature_description": "벽을 탄다."}
        invalid_source = GENERATED_SOURCE.replace(
            "var direction = Vector2.right * Mathf.Sign(input.Movement.x);",
            "if (baseHealth <= 0) { return; }\n"
            "            var direction = Vector2.right * Mathf.Sign(input.Movement.x);",
        )
        repaired_source = invalid_source.replace(
            "if (baseHealth <= 0) { return; }\n            ",
            "",
        )
        module = {
            "module_id": "generated_feature_01",
            **requirement,
            "class_name": "WallClimbModule",
            "source_code": invalid_source,
        }
        design = build_game_logic_design(normalize_game_spec("플랫포머", {"mechanics": []}))
        design["generated_modules"] = [module]
        client = SequenceStructuredJsonClient(
            [
                {"generated_modules": [module]},
                {"generated_modules": [{**module, "source_code": repaired_source}]},
            ]
        )

        repaired = GeminiFeatureGenerator(client).repair(
            design,
            {
                "diagnostics": (
                    "GeneratedFeature01Module.cs(12,17): error CS0103: "
                    "The name 'baseHealth' does not exist in the current context"
                )
            },
        )

        self.assertEqual(len(client.prompts), 2)
        self.assertNotIn("baseHealth", repaired[0]["source_code"])

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
