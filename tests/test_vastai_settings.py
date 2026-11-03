from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from game_pipeline.gemini_feature_generator import LocalAIJsonClient
from LocalAI.profiles import resolve_ai_settings
from MCP.llm_config import LLMSettings
from VastAI.settings import load_vastai_settings


class VastAISettingsTest(unittest.TestCase):
    def test_role_settings_use_inference_key_not_vast_account_key(self) -> None:
        with patch.dict(
            os.environ,
            {
                "VAST_API_KEY": "must-not-leak",
                "VASTAI_INFERENCE_API_KEY": "inference-secret",
                "VASTAI_CODER_BASE_URL": "https://coder.example/v1",
                "VASTAI_CODER_MODEL": "team-coder",
                "VASTAI_CODER_CONTEXT_TOKENS": "65536",
                "VASTAI_CODER_MAX_OUTPUT_TOKENS": "12288",
            },
            clear=True,
        ):
            settings = load_vastai_settings("coder")

        self.assertEqual(settings.api_key, "inference-secret")
        self.assertNotEqual(settings.api_key, "must-not-leak")
        self.assertEqual(settings.context_tokens, 65536)
        self.assertEqual(settings.max_output_tokens, 12288)

    def test_structured_json_client_can_select_vastai_coder(self) -> None:
        with patch.dict(
            os.environ,
            {
                "VASTAI_CODER_BASE_URL": "http://127.0.0.1:18000/v1",
                "VASTAI_CODER_MODEL": "mainflow-coder",
            },
            clear=True,
        ):
            client = LocalAIJsonClient.from_environment("vastai")

        self.assertEqual(client.base_url, "http://127.0.0.1:18000/v1")
        self.assertEqual(client.model, "mainflow-coder")
        self.assertEqual(client.context_window_tokens, 32768)

    def test_node_profiles_route_vlm_and_image_independently(self) -> None:
        with patch.dict(
            os.environ,
            {
                "VASTAI_INFERENCE_API_KEY": "secret",
                "VASTAI_VLM_BASE_URL": "https://vlm.example/v1",
                "VASTAI_VLM_MODEL": "team-vlm",
                "VASTAI_IMAGE_BASE_URL": "https://image.example/v1",
                "VASTAI_IMAGE_MODEL": "team-image",
            },
            clear=True,
        ):
            vlm = resolve_ai_settings("vast_vlm", "visual_validation")
            image = resolve_ai_settings(
                "vast_image",
                "visual_validation",
                capability="image",
            )

        self.assertEqual(
            (vlm.provider, vlm.base_url, vlm.model),
            ("vastai", "https://vlm.example/v1", "team-vlm"),
        )
        self.assertEqual(
            (image.provider, image.base_url, image.model),
            ("vastai", "https://image.example/v1", "team-image"),
        )

    def test_direct_vastai_provider_uses_coder_endpoint(self) -> None:
        with patch.dict(
            os.environ,
            {
                "VASTAI_CODER_BASE_URL": "https://coder.example/v1",
                "VASTAI_CODER_MODEL": "team-coder",
                "VASTAI_INFERENCE_API_KEY": "secret",
            },
            clear=True,
        ):
            settings = LLMSettings.from_environment(
                node_name="analysis",
                provider="vastai",
            )

        self.assertEqual(settings.provider, "vastai")
        self.assertEqual(settings.base_url, "https://coder.example/v1")
        self.assertEqual(settings.model, "team-coder")


if __name__ == "__main__":
    unittest.main()
