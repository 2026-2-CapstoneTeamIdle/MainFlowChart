from __future__ import annotations

import base64
import io
import os
import re
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

from PIL import Image, ImageDraw

from mainflow.ArtifactManager import ArtifactManager
from mainflow.image_backends import (
    FLAT_BACKGROUND_PROMPT,
    LOCAL_FLAT_BACKGROUND_PROMPT,
    LocalImageGenerator,
    OpenAIImageGenerator,
    create_image_generator,
    postprocess,
    remove_flat_background,
)
from mainflow.image_generation import (
    ImageRequest,
    PlaceholderImageGenerator,
    ReferenceImage,
    build_prompt,
    inspect_png,
    plan_assets,
)
from mainflow.nodes import generate_image_node, validate_image_node
from tests.image_fixtures import asset_item, image_asset_request, write_image_inputs

ASSETS = [
    asset_item("hero", "플레이어", "날개를 가진 플레이어 스프라이트"),
    asset_item("hero_portrait", "캐릭터", "표정 변형이 가능한 캐릭터 초상화"),
    asset_item("stage", "배경", "주요 장면 배경 이미지"),
]


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
    """Records ``images.generate``/``images.edit`` calls and returns canned PNGs."""

    def __init__(self, transparent_sprites: bool = True) -> None:
        self.calls: list[dict[str, Any]] = []
        self.transparent_sprites = transparent_sprites
        self.images = self

    def generate(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append({"endpoint": "generate", **kwargs})
        return self._respond(kwargs)

    def edit(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append({"endpoint": "edit", **kwargs})
        return self._respond(kwargs)

    def _respond(self, kwargs: dict[str, Any]) -> SimpleNamespace:
        if kwargs["background"] == "opaque":
            content = scene_png()
        else:
            content = sprite_png(transparent=self.transparent_sprites)
        encoded = base64.b64encode(content).decode("ascii")
        return SimpleNamespace(data=[SimpleNamespace(b64_json=encoded)])


def make_request(
    asset_id: str = "hero",
    style: str = "Cartoon",
    reference: ReferenceImage | None = None,
) -> ImageRequest:
    request = image_asset_request(ASSETS, image_style=style)
    plan = next(plan for plan in plan_assets(request) if plan.asset_id == asset_id)
    width, height = plan.size
    return ImageRequest(
        plan=plan,
        style=request["image_style"],
        mood_style=request["mood_style"],
        viewpoint=request["viewpoint"],
        genre=request["genre"],
        width=width,
        height=height,
        prompt=build_prompt(plan, request),
        reference=reference,
    )


class OpenAIImageGeneratorTest(unittest.TestCase):
    def test_request_parameters_follow_asset_kind(self) -> None:
        client = FakeImagesClient()
        generator = OpenAIImageGenerator("test-model", client=client, quality="high")

        generator.generate(make_request("hero"))
        generator.generate(make_request("hero_portrait"))
        generator.generate(make_request("stage"))

        sprite_call, portrait_call, scene_call = client.calls
        self.assertEqual(sprite_call["endpoint"], "generate")
        self.assertEqual(sprite_call["model"], "test-model")
        self.assertEqual(sprite_call["background"], "transparent")
        self.assertEqual(sprite_call["size"], "1024x1024")
        self.assertEqual(sprite_call["quality"], "high")
        self.assertEqual(sprite_call["output_format"], "png")
        self.assertIn("날개를 가진", sprite_call["prompt"])
        self.assertEqual(portrait_call["size"], "1024x1536")
        self.assertEqual(scene_call["background"], "opaque")
        self.assertEqual(scene_call["size"], "1536x1024")

    def test_reference_image_uses_edit_endpoint(self) -> None:
        client = FakeImagesClient()
        reference = ReferenceImage(sprite_png(64), "image/png")
        OpenAIImageGenerator("m", client=client).generate(
            make_request(style="Custom", reference=reference)
        )
        (call,) = client.calls
        self.assertEqual(call["endpoint"], "edit")
        self.assertEqual(call["image"], ("reference.png", reference.content, "image/png"))
        self.assertIn("reference image", call["prompt"])

    def test_model_and_quality_can_be_set_by_environment(self) -> None:
        environment = {
            "MAINFLOW_OPENAI_IMAGE_MODEL": "gpt-image-2",
            "MAINFLOW_OPENAI_IMAGE_QUALITY": "LOW",
        }
        with mock.patch.dict(os.environ, environment):
            generator = OpenAIImageGenerator(client=FakeImagesClient())
        self.assertEqual((generator.model, generator.quality), ("gpt-image-2", "low"))

    def test_default_model_is_not_the_retired_gpt_image_1(self) -> None:
        with mock.patch.dict(os.environ, {"MAINFLOW_OPENAI_IMAGE_MODEL": ""}):
            generator = OpenAIImageGenerator(client=FakeImagesClient())
        self.assertEqual(generator.model, "gpt-image-2.5-sunburst")

    def test_unknown_model_error_names_the_setting(self) -> None:
        class ModelError(Exception):
            param = "model"

        client = mock.Mock()
        client.images.generate.side_effect = ModelError("The model 'gpt-image-1' does not exist.")
        client.images.edit.side_effect = ModelError("The model 'gpt-image-1' does not exist.")
        generator = OpenAIImageGenerator("gpt-image-1", client=client)
        with self.assertRaisesRegex(RuntimeError, "MAINFLOW_OPENAI_IMAGE_MODEL"):
            generator.generate(make_request())
        with self.assertRaisesRegex(RuntimeError, "MAINFLOW_OPENAI_IMAGE_MODEL"):
            generator.generate_animation_strip(make_request(), b"png", "run", 6, "a run")

    def test_invalid_quality_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            OpenAIImageGenerator("m", client=FakeImagesClient(), quality="ultra")

    def test_empty_response_raises(self) -> None:
        client = mock.Mock()
        client.images.generate.return_value = SimpleNamespace(data=[])
        with self.assertRaises(RuntimeError):
            OpenAIImageGenerator("m", client=client).generate(make_request())


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
    def test_blocked_output_is_retried_with_a_changed_prompt(self) -> None:
        client = BlockingImagesClient(blocked_attempts=1)
        request = make_request()

        content = OpenAIImageGenerator("m", client=client).generate(request)

        self.assertEqual(len(client.calls), 2)
        self.assertEqual(client.calls[0]["prompt"], request.prompt)
        self.assertNotEqual(client.calls[1]["prompt"], request.prompt)
        self.assertTrue(client.calls[1]["prompt"].startswith(request.prompt))
        self.assertTrue(inspect_png(content).has_transparent_pixel)

    def test_gives_up_after_all_prompt_variants(self) -> None:
        client = BlockingImagesClient(blocked_attempts=99)
        with self.assertRaisesRegex(RuntimeError, "safety system"):
            OpenAIImageGenerator("m", client=client).generate(make_request())
        self.assertEqual(len(client.calls), 3)

    def test_other_errors_are_not_retried(self) -> None:
        client = mock.Mock()
        client.images.generate.side_effect = ValueError("invalid size")
        with self.assertRaises(ValueError):
            OpenAIImageGenerator("m", client=client).generate(make_request())
        self.assertEqual(client.images.generate.call_count, 1)


class PostprocessTest(unittest.TestCase):
    def test_sprite_is_resized_and_keeps_transparency(self) -> None:
        request = make_request("hero")
        info = inspect_png(postprocess(sprite_png(), request))
        self.assertEqual((info.width, info.height), (request.width, request.height))
        self.assertTrue(info.has_transparent_pixel)

    def test_background_is_center_cropped_and_opaque(self) -> None:
        request = make_request("stage")
        info = inspect_png(postprocess(scene_png(), request))
        self.assertEqual((info.width, info.height), (request.width, request.height))
        self.assertFalse(info.has_transparent_pixel)

    def test_opaque_sprite_falls_back_to_background_removal(self) -> None:
        info = inspect_png(postprocess(sprite_png(transparent=False), make_request("hero")))
        self.assertTrue(info.has_transparent_pixel)

    def test_large_background_removal_keeps_interior_and_is_fast(self) -> None:
        image = Image.open(io.BytesIO(sprite_png(1024, transparent=False))).convert("RGBA")
        # A white patch inside the character must survive: it is not connected
        # to the background.
        ImageDraw.Draw(image).rectangle((500, 500, 520, 520), fill=(255, 255, 255, 255))
        started = time.perf_counter()
        result = remove_flat_background(image)
        self.assertLess(time.perf_counter() - started, 2.0)
        self.assertEqual(result.getpixel((0, 0))[3], 0)
        self.assertEqual(result.getpixel((1023, 1023))[3], 0)
        self.assertEqual(result.getpixel((510, 510))[3], 255)
        self.assertEqual(result.getpixel((300, 512))[3], 255)

    def test_background_removal_keeps_interior(self) -> None:
        image = Image.open(io.BytesIO(sprite_png(256, transparent=False))).convert("RGBA")
        result = remove_flat_background(image)
        self.assertEqual(result.getpixel((0, 0))[3], 0)
        self.assertEqual(result.getpixel((128, 128))[3], 255)

    def test_pixel_art_limits_palette_and_snaps_alpha(self) -> None:
        request = make_request("hero_portrait", style="Pixel Art")
        with Image.open(io.BytesIO(postprocess(sprite_png(), request))) as image:
            pixels = list(image.convert("RGBA").get_flattened_data())
        self.assertLessEqual(len({pixel[:3] for pixel in pixels if pixel[3]}), 32)
        self.assertLessEqual({pixel[3] for pixel in pixels}, {0, 255})


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
        # Animation strips are covered in test_image_spritesheet; keep one
        # API call per asset here.
        self.environment = mock.patch.dict(
            os.environ,
            {
                "MAINFLOW_WORKSPACE": str(workspace),
                "MAINFLOW_IMAGE_SPRITE_SHEET_MODE": "transform",
            },
        )
        self.environment.start()
        self.manager = ArtifactManager()
        self.project_id = self.manager.create_project()

    def tearDown(self) -> None:
        self.environment.stop()
        self.temporary_directory.cleanup()

    def test_generated_assets_pass_validation(self) -> None:
        state = write_image_inputs(
            self.manager, self.project_id, image_asset_request(ASSETS, image_style="Anime")
        )
        client = FakeImagesClient(transparent_sprites=False)
        state["image_draft"] = generate_image_node(
            state, OpenAIImageGenerator("test-model", client=client)
        )["image_draft"]

        self.assertEqual(len(client.calls), len(ASSETS))
        result = self.manager.read_json(validate_image_node(state)["image_validation_result"])
        self.assertEqual(result["status"], "passed", result["issues"])
        self.assertEqual(result["validated_asset_ids"], [item["asset_id"] for item in ASSETS])

    def test_custom_reference_image_is_read_from_the_request(self) -> None:
        reference = self.manager.write_bytes(
            self.project_id,
            "image",
            "references/custom_style.png",
            sprite_png(64),
            producer="parse_input",
            media_type="image/png",
        )
        request = image_asset_request(ASSETS[:1], image_style="Custom", reference_image=reference)
        state = write_image_inputs(self.manager, self.project_id, request)
        client = FakeImagesClient()
        generate_image_node(state, OpenAIImageGenerator("m", client=client))

        (call,) = client.calls
        self.assertEqual(call["endpoint"], "edit")
        self.assertEqual(call["image"][1], self.manager.read_bytes(reference))


class FakeLocalImagesClient:
    """Mimics a LocalAI-style server: no alpha output, b64_json or URL replies."""

    def __init__(self, reply_with_url: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.reply_with_url = reply_with_url
        self.images = self

    def generate(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        if self.reply_with_url:
            return SimpleNamespace(
                data=[SimpleNamespace(b64_json=None, url="http://localai:8080/generated/a.png")]
            )
        encoded = base64.b64encode(sprite_png(512, transparent=False)).decode("ascii")
        return SimpleNamespace(data=[SimpleNamespace(b64_json=encoded, url=None)])


LOCAL_ENVIRONMENT_KEYS = (
    "MAINFLOW_LOCAL_IMAGE_MODEL",
    "MAINFLOW_LOCAL_IMAGE_BASE_URL",
    "LOCAL_LLM_BASE_URL",
    "MAINFLOW_LOCAL_IMAGE_SIZE",
    "MAINFLOW_LOCAL_IMAGE_STEPS",
)


class LocalImageGeneratorTest(unittest.TestCase):
    def setUp(self) -> None:
        cleared = {key: "" for key in LOCAL_ENVIRONMENT_KEYS}
        self.environment = mock.patch.dict(os.environ, cleared)
        self.environment.start()

    def tearDown(self) -> None:
        self.environment.stop()

    def test_model_is_required(self) -> None:
        with self.assertRaisesRegex(ValueError, "MAINFLOW_LOCAL_IMAGE_MODEL"):
            LocalImageGenerator(client=FakeLocalImagesClient())

    def test_base_url_falls_back_to_team_local_llm_url(self) -> None:
        self.assertEqual(
            LocalImageGenerator("m", client=FakeLocalImagesClient()).base_url,
            "http://127.0.0.1:8080/v1",
        )
        os.environ["LOCAL_LLM_BASE_URL"] = "http://Local-AIModel:8080/v1"
        self.assertEqual(
            LocalImageGenerator("m", client=FakeLocalImagesClient()).base_url,
            "http://Local-AIModel:8080/v1",
        )
        os.environ["MAINFLOW_LOCAL_IMAGE_BASE_URL"] = "http://image-server:9000/v1"
        self.assertEqual(
            LocalImageGenerator("m", client=FakeLocalImagesClient()).base_url,
            "http://image-server:9000/v1",
        )

    def test_request_uses_local_settings_and_flat_background(self) -> None:
        os.environ.update(
            {"MAINFLOW_LOCAL_IMAGE_SIZE": "768x768", "MAINFLOW_LOCAL_IMAGE_STEPS": "20"}
        )
        client = FakeLocalImagesClient()
        generator = LocalImageGenerator("flux.1-dev-ggml", client=client)

        sprite = generator.generate(make_request("hero"))
        generator.generate(make_request("stage"))

        sprite_call, scene_call = client.calls
        self.assertEqual(sprite_call["model"], "flux.1-dev-ggml")
        self.assertEqual(sprite_call["size"], "768x768")
        self.assertEqual(sprite_call["response_format"], "b64_json")
        self.assertEqual(sprite_call["extra_body"], {"step": 20})
        self.assertNotIn("background", sprite_call)
        self.assertTrue(sprite_call["prompt"].endswith(LOCAL_FLAT_BACKGROUND_PROMPT))
        self.assertFalse(scene_call["prompt"].endswith(LOCAL_FLAT_BACKGROUND_PROMPT))
        # The white background is removed by post-processing.
        self.assertTrue(inspect_png(sprite).has_transparent_pixel)

    def test_url_response_is_downloaded(self) -> None:
        generator = LocalImageGenerator("m", client=FakeLocalImagesClient(reply_with_url=True))
        with mock.patch(
            "mainflow.image_backends._download", return_value=sprite_png(256)
        ) as download:
            content = generator.generate(make_request("hero"))
        download.assert_called_once_with("http://localai:8080/generated/a.png")
        self.assertTrue(inspect_png(content).has_transparent_pixel)

    def test_invalid_settings_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            LocalImageGenerator("m", client=FakeLocalImagesClient(), size="big")
        with self.assertRaises(ValueError):
            LocalImageGenerator("m", client=FakeLocalImagesClient(), steps=0)

    def test_factory_selects_local_backend(self) -> None:
        os.environ["MAINFLOW_LOCAL_IMAGE_MODEL"] = "flux.1-dev-ggml"
        generator = create_image_generator("local")
        self.assertIsInstance(generator, LocalImageGenerator)

    def test_local_assets_pass_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            os.environ["MAINFLOW_WORKSPACE"] = str(Path(directory) / "workspace")
            manager = ArtifactManager()
            project_id = manager.create_project()
            state = write_image_inputs(manager, project_id, image_asset_request(ASSETS))
            client = FakeLocalImagesClient()
            state["image_draft"] = generate_image_node(
                state, LocalImageGenerator("m", client=client)
            )["image_draft"]

            self.assertEqual(len(client.calls), len(ASSETS))
            draft = manager.read_json(state["image_draft"])
            self.assertIn("generator=local", draft["notes"])
            result = manager.read_json(validate_image_node(state)["image_validation_result"])
            self.assertEqual(result["status"], "passed", result["issues"])


class TransparencyRejectedError(Exception):
    """Mimics gpt-image-2 rejecting background="transparent"."""

    param = "background"


class NoAlphaImagesClient(FakeImagesClient):
    """A model without transparency: rejects it and draws on white instead."""

    def _respond(self, kwargs: dict[str, Any]) -> SimpleNamespace:
        if kwargs["background"] == "transparent":
            raise TransparencyRejectedError(
                "Transparent background is not supported for this model."
            )
        if kwargs["size"] == "1536x1024" and "Sprite sheet" not in kwargs["prompt"]:
            content = scene_png()
        else:
            content = sprite_png(transparent=False)
        encoded = base64.b64encode(content).decode("ascii")
        return SimpleNamespace(data=[SimpleNamespace(b64_json=encoded)])


class TransparencyFallbackTest(unittest.TestCase):
    def test_rejected_transparency_retries_on_a_flat_background(self) -> None:
        client = NoAlphaImagesClient()
        generator = OpenAIImageGenerator("gpt-image-2", client=client)

        sprite = generator.generate(make_request("hero"))

        rejected, retried = client.calls
        self.assertEqual(rejected["background"], "transparent")
        self.assertEqual(retried["background"], "opaque")
        self.assertTrue(retried["prompt"].endswith(FLAT_BACKGROUND_PROMPT))
        self.assertFalse(generator.transparent_supported)
        # The white background is removed by post-processing.
        self.assertTrue(inspect_png(sprite).has_transparent_pixel)

    def test_after_one_rejection_transparency_is_not_requested_again(self) -> None:
        client = NoAlphaImagesClient()
        generator = OpenAIImageGenerator("gpt-image-2", client=client)
        generator.generate(make_request("hero"))
        generator.generate(make_request("hero_portrait"))
        generator.generate_animation_strip(make_request(), sprite_png(), "run", 6, "a run")
        self.assertEqual(
            [call["background"] for call in client.calls],
            ["transparent", "opaque", "opaque", "opaque"],
        )
        self.assertNotIn("Transparent background", client.calls[-1]["prompt"])
        self.assertIn(FLAT_BACKGROUND_PROMPT.strip(), client.calls[-1]["prompt"])

    def test_opaque_assets_never_ask_for_transparency(self) -> None:
        client = NoAlphaImagesClient()
        OpenAIImageGenerator("m", client=client).generate(make_request("stage"))
        self.assertEqual([call["background"] for call in client.calls], ["opaque"])

    def test_other_background_errors_on_opaque_requests_are_raised(self) -> None:
        client = mock.Mock()
        client.images.generate.side_effect = TransparencyRejectedError("bad background")
        with self.assertRaises(TransparencyRejectedError):
            OpenAIImageGenerator("m", client=client).generate(make_request("stage"))

    def test_node_notes_the_flat_background_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = {
                "MAINFLOW_WORKSPACE": str(Path(directory) / "workspace"),
                "MAINFLOW_IMAGE_SPRITE_SHEET_MODE": "transform",
            }
            with mock.patch.dict(os.environ, environment):
                manager = ArtifactManager()
                project_id = manager.create_project()
                state = write_image_inputs(manager, project_id, image_asset_request(ASSETS))
                state["image_draft"] = generate_image_node(
                    state, OpenAIImageGenerator("gpt-image-2", client=NoAlphaImagesClient())
                )["image_draft"]
                draft = manager.read_json(state["image_draft"])
                self.assertEqual(draft["status"], "generated", draft["notes"])
                self.assertTrue(any("흰 단색 배경" in note for note in draft["notes"]))
                result = manager.read_json(validate_image_node(state)["image_validation_result"])
                self.assertEqual(result["status"], "passed", result["issues"])


class AnimationStripRequestTest(unittest.TestCase):
    def test_strip_uses_edit_with_reference_image(self) -> None:
        client = FakeImagesClient()
        generator = OpenAIImageGenerator("gpt-image-2", client=client, quality="low")
        reference = sprite_png(512)

        generator.generate_animation_strip(
            make_request("hero", style="Pixel Art"), reference, "run", 6, "a running cycle"
        )

        (call,) = client.calls
        self.assertEqual(call["endpoint"], "edit")
        self.assertEqual(call["image"], ("character.png", reference, "image/png"))
        # gpt-image-2 always uses high input fidelity; the parameter must be omitted.
        self.assertNotIn("input_fidelity", call)
        self.assertEqual(call["size"], "1536x1024")
        self.assertEqual(call["background"], "transparent")
        self.assertEqual(call["quality"], "low")
        for expected in ("6 frames", "a running cycle", "single row", "pixel art"):
            self.assertIn(expected, call["prompt"])

    def test_input_fidelity_is_sent_only_to_the_gpt_image_1_family(self) -> None:
        for model, expected in (
            ("gpt-image-2", None),
            ("gpt-image-2.5-sunburst", None),
            ("gpt-image-1.5", "high"),
            ("gpt-image-1-mini", "high"),
        ):
            with self.subTest(model=model):
                client = FakeImagesClient()
                OpenAIImageGenerator(model, client=client).generate_animation_strip(
                    make_request(), sprite_png(), "run", 6, "a run"
                )
                self.assertEqual(client.calls[0].get("input_fidelity"), expected)

    def test_strip_retries_on_moderation(self) -> None:
        client = BlockingImagesClient(blocked_attempts=1)
        client.edit = client.generate  # type: ignore[method-assign]
        generator = OpenAIImageGenerator("m", client=client)
        generator.generate_animation_strip(make_request(), sprite_png(), "jump", 3, "a jump")
        self.assertEqual(len(client.calls), 2)

    def test_raw_output_is_kept_as_strip_reference(self) -> None:
        generator = OpenAIImageGenerator("m", client=FakeImagesClient())
        generator.generate(make_request("hero"))
        with Image.open(io.BytesIO(generator.raw_outputs["hero"])) as raw:
            self.assertEqual(raw.size, (1024, 1024))


class InputFidelityRejectedError(Exception):
    param = "input_fidelity"


class StrictGptImage2Client(FakeImagesClient):
    """Behaves like gpt-image-2: rejects input_fidelity and returns real strips."""

    def _respond(self, kwargs: dict[str, Any]) -> SimpleNamespace:
        if "input_fidelity" in kwargs:
            raise InputFidelityRejectedError("input_fidelity is not supported for gpt-image-2")
        frames = re.search(r"(\d+) frames", kwargs["prompt"])
        if frames is None:
            content = sprite_png()
        else:
            # An animation strip: evenly spaced poses on a transparent canvas.
            count = int(frames.group(1))
            strip = Image.new("RGBA", (1536, 1024))
            slot = 1536 // count
            for index in range(count):
                pose = Image.open(io.BytesIO(sprite_png(200 + 10 * (index % 2)))).convert("RGBA")
                pose = pose.crop(pose.getchannel("A").getbbox())
                strip.alpha_composite(
                    pose, (index * slot + (slot - pose.width) // 2, 900 - pose.height)
                )
            content = _encode(strip)
        encoded = base64.b64encode(content).decode("ascii")
        return SimpleNamespace(data=[SimpleNamespace(b64_json=encoded)])


class GptImage2AiSheetTest(unittest.TestCase):
    def test_ai_sheet_is_built_without_falling_back(self) -> None:
        client = StrictGptImage2Client()
        with tempfile.TemporaryDirectory() as directory:
            environment = {
                "MAINFLOW_WORKSPACE": str(Path(directory) / "workspace"),
                "MAINFLOW_IMAGE_SPRITE_SHEETS": "on",
                "MAINFLOW_IMAGE_SPRITE_SHEET_MODE": "auto",
            }
            with mock.patch.dict(os.environ, environment):
                manager = ArtifactManager()
                project_id = manager.create_project()
                state = write_image_inputs(manager, project_id, image_asset_request(ASSETS))
                state["image_draft"] = generate_image_node(
                    state, OpenAIImageGenerator("gpt-image-2", client=client)
                )["image_draft"]

                draft = manager.read_json(state["image_draft"])
                (note,) = [n for n in draft["notes"] if n.startswith("sprite_sheet:hero=")]
                metadata_id = note.split("=")[1].split(",")[1]
                metadata = manager.read_json(manager.get_artifact(project_id, metadata_id))
                self.assertEqual(
                    {name: a["source"] for name, a in metadata["animations"].items()},
                    {"idle": "ai", "run": "ai", "jump": "ai"},
                )
                self.assertNotIn("fallbacks", metadata)
                self.assertFalse(any("transform으로 대체" in note for note in draft["notes"]))
                edits = [call for call in client.calls if call["endpoint"] == "edit"]
                self.assertEqual(len(edits), 3)
                self.assertTrue(all("input_fidelity" not in call for call in edits))
                result = manager.read_json(validate_image_node(state)["image_validation_result"])
                self.assertEqual(result["status"], "passed", result["issues"])


if __name__ == "__main__":
    unittest.main()
