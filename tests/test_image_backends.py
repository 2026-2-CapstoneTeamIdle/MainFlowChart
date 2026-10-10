from __future__ import annotations

import base64
import io
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

from PIL import Image, ImageDraw

from ArtifactManager import ArtifactManager
from contracts import CONTRACT_VERSION
from image_backends import (
    OpenAIImageGenerator,
    create_image_generator,
    postprocess,
    remove_flat_background,
)
from image_generation import (
    ImageRequest,
    PlaceholderImageGenerator,
    asset_size,
    build_prompt,
    image_criteria,
    inspect_png,
    plan_assets,
)
from langgraph_game_flow_skeleton import generate_image_node, validate_image_node


def sprite_png(size: int = 1024, transparent: bool = True) -> bytes:
    """A gradient-filled circle, like a typical API sprite result."""

    background = (0, 0, 0, 0) if transparent else (255, 255, 255, 255)
    image = Image.new("RGBA", (size, size), background)
    draw = ImageDraw.Draw(image)
    for step in range(64):
        inset = size // 4 + step * size // 512
        draw.ellipse(
            (inset, inset, size - inset, size - inset),
            fill=(200 - step * 2, step * 3, 60 + step, 255),
        )
    return _encode(image)


def scene_png(width: int = 1536, height: int = 1024) -> bytes:
    image = Image.new("RGBA", (width, height), (40, 120, 220, 255))
    ImageDraw.Draw(image).rectangle((0, height * 2 // 3, width, height), fill=(30, 160, 60, 255))
    return _encode(image)


def _encode(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class FakeImagesClient:
    """Records ``images.generate`` calls and returns canned PNGs."""

    def __init__(self, transparent_sprites: bool = True) -> None:
        self.calls: list[dict[str, Any]] = []
        self.transparent_sprites = transparent_sprites
        self.images = self

    def generate(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        if kwargs["size"] == "1536x1024":
            content = scene_png()
        else:
            content = sprite_png(transparent=self.transparent_sprites)
        encoded = base64.b64encode(content).decode("ascii")
        return SimpleNamespace(data=[SimpleNamespace(b64_json=encoded)])


def make_request(key: str, style: str = "Cartoon", quality: str = "Medium") -> ImageRequest:
    plan = next(plan for plan in plan_assets("RPG") if plan.key == key)
    width, height = asset_size(plan, quality)  # type: ignore[arg-type]
    return ImageRequest(
        plan=plan,
        style=style,  # type: ignore[arg-type]
        genre="RPG",
        width=width,
        height=height,
        prompt=build_prompt(plan, style, "RPG"),  # type: ignore[arg-type]
        quality=quality,  # type: ignore[arg-type]
    )


class OpenAIImageGeneratorTest(unittest.TestCase):
    def test_request_parameters_follow_asset_role_and_quality(self) -> None:
        client = FakeImagesClient()
        generator = OpenAIImageGenerator("test-model", client=client)

        generator.generate(make_request("player", quality="High"))
        generator.generate(make_request("background", quality="Low"))

        sprite_call, scene_call = client.calls
        self.assertEqual(sprite_call["model"], "test-model")
        self.assertEqual(sprite_call["background"], "transparent")
        self.assertEqual(sprite_call["size"], "1024x1024")
        self.assertEqual(sprite_call["quality"], "high")
        self.assertEqual(sprite_call["output_format"], "png")
        self.assertIn("adventurer hero", sprite_call["prompt"])
        self.assertEqual(scene_call["background"], "opaque")
        self.assertEqual(scene_call["size"], "1536x1024")
        self.assertEqual(scene_call["quality"], "low")

    def test_model_can_be_set_by_environment(self) -> None:
        with mock.patch.dict(os.environ, {"MAINFLOW_OPENAI_IMAGE_MODEL": "gpt-image-2"}):
            generator = OpenAIImageGenerator(client=FakeImagesClient())
        self.assertEqual(generator.model, "gpt-image-2")

    def test_empty_response_raises(self) -> None:
        client = mock.Mock()
        client.images.generate.return_value = SimpleNamespace(data=[])
        with self.assertRaises(RuntimeError):
            OpenAIImageGenerator("m", client=client).generate(make_request("player"))


class ModerationError(Exception):
    """Mimics openai.BadRequestError for a moderation_blocked response."""

    code = "moderation_blocked"


class BlockingImagesClient(FakeImagesClient):
    def __init__(self, blocked_attempts: int) -> None:
        super().__init__()
        self.blocked_attempts = blocked_attempts

    def generate(self, **kwargs: Any) -> SimpleNamespace:
        if len(self.calls) < self.blocked_attempts:
            self.calls.append(kwargs)
            raise ModerationError("Your request was rejected by the safety system.")
        return super().generate(**kwargs)


class ModerationRetryTest(unittest.TestCase):
    def test_prompt_asks_for_original_design(self) -> None:
        self.assertIn("not based on any existing", make_request("player").prompt)

    def test_blocked_output_is_retried_with_a_changed_prompt(self) -> None:
        client = BlockingImagesClient(blocked_attempts=1)
        request = make_request("player")

        content = OpenAIImageGenerator("m", client=client).generate(request)

        self.assertEqual(len(client.calls), 2)
        self.assertEqual(client.calls[0]["prompt"], request.prompt)
        self.assertNotEqual(client.calls[1]["prompt"], request.prompt)
        self.assertTrue(client.calls[1]["prompt"].startswith(request.prompt))
        self.assertTrue(inspect_png(content).has_transparent_pixel)

    def test_gives_up_after_all_prompt_variants(self) -> None:
        client = BlockingImagesClient(blocked_attempts=99)
        with self.assertRaisesRegex(RuntimeError, "safety system"):
            OpenAIImageGenerator("m", client=client).generate(make_request("player"))
        self.assertEqual(len(client.calls), 3)

    def test_other_errors_are_not_retried(self) -> None:
        client = mock.Mock()
        client.images.generate.side_effect = ValueError("invalid size")
        with self.assertRaises(ValueError):
            OpenAIImageGenerator("m", client=client).generate(make_request("player"))
        self.assertEqual(client.images.generate.call_count, 1)


class PostprocessTest(unittest.TestCase):
    def test_sprite_is_resized_and_keeps_transparency(self) -> None:
        request = make_request("player")
        info = inspect_png(postprocess(sprite_png(), request))
        self.assertEqual((info.width, info.height), (request.width, request.height))
        self.assertTrue(info.has_transparent_pixel)

    def test_background_is_center_cropped_and_opaque(self) -> None:
        request = make_request("background")
        content = postprocess(scene_png(), request)
        info = inspect_png(content)
        self.assertEqual((info.width, info.height), (request.width, request.height))
        self.assertFalse(info.has_transparent_pixel)

    def test_opaque_sprite_falls_back_to_background_removal(self) -> None:
        request = make_request("player")
        info = inspect_png(postprocess(sprite_png(transparent=False), request))
        self.assertTrue(info.has_transparent_pixel)

    def test_background_removal_keeps_interior(self) -> None:
        image = Image.open(io.BytesIO(sprite_png(256, transparent=False))).convert("RGBA")
        result = remove_flat_background(image)
        self.assertEqual(result.getpixel((0, 0))[3], 0)
        self.assertEqual(result.getpixel((128, 128))[3], 255)

    def test_pixel_art_limits_palette_and_snaps_alpha(self) -> None:
        request = make_request("player", style="Pixel Art", quality="High")
        with Image.open(io.BytesIO(postprocess(sprite_png(), request))) as image:
            image = image.convert("RGBA")
            opaque_colors = {pixel[:3] for pixel in image.get_flattened_data() if pixel[3]}
            alphas = {pixel[3] for pixel in image.get_flattened_data()}
        self.assertLessEqual(len(opaque_colors), 32)
        self.assertLessEqual(alphas, {0, 255})


class BackendSelectionTest(unittest.TestCase):
    def test_default_backend_is_placeholder(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsInstance(create_image_generator(), PlaceholderImageGenerator)

    def test_unknown_backend_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            create_image_generator("midjourney")


class OpenAIGraphNodeTest(unittest.TestCase):
    """generate_image -> validate_image with the OpenAI backend and a fake client."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        workspace = Path(self.temporary_directory.name) / "workspace"
        self.environment = mock.patch.dict(os.environ, {"MAINFLOW_WORKSPACE": str(workspace)})
        self.environment.start()
        self.manager = ArtifactManager()
        self.project_id = self.manager.create_project()

    def tearDown(self) -> None:
        self.environment.stop()
        self.temporary_directory.cleanup()

    def _write(self, category, filename, payload):
        return self.manager.write_json(
            self.project_id, category, filename, payload, producer="test"
        )

    def test_generated_assets_pass_validation(self) -> None:
        parsed_request = self._write(
            "data",
            "parsed_request.json",
            {
                "contract_version": CONTRACT_VERSION,
                "image_style": "Anime",
                "genre": "RPG",
                "quality": "Medium",
            },
        )
        final_spec = self._write(
            "validation",
            "initial_final_validation_spec.json",
            {"contract_version": CONTRACT_VERSION, "spec_id": "s", "criteria": []},
        )
        asset_spec = self._write(
            "validation",
            "asset_validation_spec.json",
            {
                "contract_version": CONTRACT_VERSION,
                "spec_id": "a",
                "image_criteria": image_criteria(),
                "sound_criteria": [],
            },
        )
        client = FakeImagesClient(transparent_sprites=False)
        image_draft = generate_image_node(
            {
                "project_id": self.project_id,
                "parsed_request": parsed_request,
                "initial_final_validation_spec": final_spec,
            },
            OpenAIImageGenerator("test-model", client=client),
        )["image_draft"]

        draft = self.manager.read_json(image_draft)
        self.assertEqual(draft["notes"], ["generator=openai"])
        self.assertEqual(len(client.calls), len(plan_assets("RPG")))

        result = self.manager.read_json(
            validate_image_node(
                {
                    "project_id": self.project_id,
                    "parsed_request": parsed_request,
                    "image_draft": image_draft,
                    "asset_validation_spec": asset_spec,
                }
            )["image_validation_result"]
        )
        self.assertEqual(result["status"], "passed", result["issues"])


if __name__ == "__main__":
    unittest.main()
