"""Sound generation tests (offline; the ElevenLabs HTTP call is mocked)."""

from __future__ import annotations

import http.client
import io
import json
import os
import tempfile
import unittest
import urllib.error
import wave
from typing import ClassVar
from unittest import mock

from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import CONTRACT_VERSION
from mainflow.nodes.generate_sound import generate_sound_node
from sound_pipeline import (
    ElevenLabsSoundProvider,
    ProceduralSoundProvider,
    SoundProviderError,
    classify,
    mp3_duration,
    plan_sound_assets,
    primary_provider,
    wav_duration,
)

PARSED = {
    "contract_version": CONTRACT_VERSION,
    "image_style": "Pixel Art",
    "mood_style": "Horror",
    "genre": "뱀서류",
    "viewpoint": "탑다운",
    "condition": "자동 공격과 8방향 이동이 가능한 게임",
    "custom_image": None,
}


def item(asset_id, purpose, description, filename=None):
    return {
        "asset_id": asset_id,
        "asset_type": "sound",
        "purpose": purpose,
        "description": description,
        "required": True,
        "suggested_filename": filename or f"{asset_id}.wav",
        "unity_binding_key": f"asset_registry:{asset_id}",
    }


def request(*items, mood="Horror"):
    return {
        "contract_version": CONTRACT_VERSION,
        "request_id": "test-sound-assets",
        "source_design_id": "test-design",
        "game_title": "Test Game",
        "genre": "SurvivorLike",
        "asset_type": "sound",
        "image_style": "Pixel Art",
        "mood_style": mood,
        "viewpoint": "탑다운",
        "reference_image": None,
        "output_directory": "generated/sounds",
        "assets": list(items),
    }


class FakeResponse(io.BytesIO):
    headers: ClassVar[dict[str, str]] = {"request-id": "req-123"}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def fake_mp3(seconds: float) -> bytes:
    """MPEG-1 Layer III, 128 kbps, 44.1 kHz frames (header FF FB 90 00, 417 bytes each)."""
    frames = round(seconds * 44100 / 1152)
    return b"ID3\x03\x00\x00\x00\x00\x00\x00" + (b"\xff\xfb\x90\x00" + b"\x00" * 413) * frames


def lame_info_frame(delay: int, padding: int) -> bytes:
    """Xing/Info tag frame (no audio) carrying the LAME encoder delay and end padding."""
    tag = b"Info" + b"\x00\x00\x00\x0f" + b"\x00" * 112 + b"LAME3.100" + b"\x00" * 12
    tag += bytes([delay >> 4, (delay & 0x0F) << 4 | padding >> 8, padding & 0xFF])
    return (b"\xff\xfb\x90\x00" + b"\x00" * 32 + tag).ljust(417, b"\x00")


def http_error(code: int, body: bytes, headers=None):
    return urllib.error.HTTPError("u", code, "x", headers or {}, io.BytesIO(body))


def open_wav(audio: bytes):
    return wave.open(io.BytesIO(audio), "rb")


class PlannerTest(unittest.TestCase):
    def test_classification_uses_purpose_and_description_not_ids(self):
        self.assertEqual(
            classify(item("x1", "배경음악", "반복 가능한 전투 배경음악")), ("bgm", "bgm")
        )
        self.assertEqual(classify(item("x2", "UI", "선택지 결정 효과음")), ("sfx", "ui"))
        self.assertEqual(
            classify(item("x3", "공격 효과음", "짧은 깃털 발사 효과음")), ("sfx", "impact")
        )
        self.assertEqual(
            classify(item("bgm_like_id", "수확", "짧은 수확 효과음")), ("sfx", "action")
        )

    def test_english_keywords_match_whole_words_only(self):
        # "white" contains "hit", "ghost" contains "ost", "descending" contains "ending".
        self.assertEqual(classify(item("w", "white flash", "glow")), ("sfx", "action"))
        self.assertEqual(classify(item("g", "ghost", "whisper")), ("sfx", "action"))
        self.assertEqual(classify(item("h", "Hits", "sword hits")), ("sfx", "impact"))
        self.assertEqual(classify(item("k", "공격음", "")), ("sfx", "impact"))
        (plan,) = plan_sound_assets(request(item("d", "music", "descending theme")), PARSED)
        self.assertTrue(plan.loop)

    def test_prompt_reflects_user_input(self):
        bgm, sfx = plan_sound_assets(
            request(
                item("b", "배경음악", "반복 가능한 전투 배경음악"),
                item("s", "공격 효과음", "깃털 발사"),
            ),
            PARSED,
        )
        self.assertTrue(bgm.loop)
        self.assertIn("eerie dark ambient", bgm.prompt)
        self.assertIn("8-bit chiptune", bgm.prompt)
        self.assertIn(PARSED["condition"], bgm.prompt)
        self.assertIn("No vocals", bgm.prompt)
        self.assertEqual(sfx.kind, "sfx")
        self.assertIn("탑다운", sfx.prompt)

    def test_ending_music_does_not_loop(self):
        (plan,) = plan_sound_assets(request(item("e", "배경음악", "엔딩 음악")), PARSED)
        self.assertFalse(plan.loop)


class ProviderTest(unittest.TestCase):
    def test_procedural_output_is_valid_and_mood_dependent(self):
        plans = plan_sound_assets(request(item("s", "UI", "선택 효과음")), PARSED)
        horror = ProceduralSoundProvider().generate(plans[0]).audio
        cozy_plan = plan_sound_assets(request(item("s", "UI", "선택 효과음"), mood="Cozy"), PARSED)[
            0
        ]
        cozy = ProceduralSoundProvider().generate(cozy_plan).audio
        with open_wav(horror) as wav_file:
            self.assertEqual((wav_file.getnchannels(), wav_file.getsampwidth()), (1, 2))
        self.assertAlmostEqual(wav_duration(horror), plans[0].duration_seconds, places=2)
        self.assertNotEqual(horror, cozy)

    def test_mp3_duration_reads_rate_from_frames(self):
        self.assertAlmostEqual(mp3_duration(fake_mp3(0.9)), 0.9, delta=0.03)
        with self.assertRaises(SoundProviderError):
            mp3_duration(b"\x00" * 1000)

    def test_mp3_duration_skips_info_frame_and_encoder_padding(self):
        # Measured on ffmpeg/libmp3lame output of a 0.5 s tone: 21 audio frames, delay 576, pad 1566.
        audio = lame_info_frame(576, 1566) + (b"\xff\xfb\x90\x00" + b"\x00" * 413) * 21
        self.assertEqual(mp3_duration(audio), 0.5)

    def test_sound_effects_use_endpoint_default_model_and_mp3(self):
        calls = []

        def fake_urlopen(req, timeout):
            calls.append((req.full_url, json.loads(req.data), req.get_header("Xi-api-key")))
            return FakeResponse(fake_mp3(0.9))

        (sfx,) = plan_sound_assets(request(item("s", "점프", "짧은 점프 효과음")), PARSED)
        with mock.patch.dict(os.environ, {}, clear=False):
            for key in ("ELEVENLABS_SFX_MODEL", "ELEVENLABS_OUTPUT_FORMAT"):
                os.environ.pop(key, None)
            with mock.patch("urllib.request.urlopen", fake_urlopen):
                result = ElevenLabsSoundProvider(api_key="test-key").generate(sfx)
        url, body, key = calls[0]
        self.assertIn("/v1/sound-generation?output_format=mp3_44100_128", url)
        self.assertNotIn("model_id", body)
        self.assertEqual(body["duration_seconds"], 0.9)
        self.assertEqual(key, "test-key")
        self.assertEqual((result.file_format, result.media_type), ("mp3", "audio/mpeg"))
        self.assertEqual(result.model_id, "sound_effects_api_default")
        self.assertEqual(result.request_id, "req-123")

    def test_pinned_sfx_model_is_sent(self):
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data)
            return FakeResponse(fake_mp3(0.5))

        (sfx,) = plan_sound_assets(request(item("s", "UI", "클릭")), PARSED)
        with (
            mock.patch.dict(os.environ, {"ELEVENLABS_SFX_MODEL": "my_sfx_model"}),
            mock.patch("urllib.request.urlopen", fake_urlopen),
        ):
            result = ElevenLabsSoundProvider(api_key="k").generate(sfx)
        self.assertEqual(captured["body"]["model_id"], "my_sfx_model")
        self.assertEqual(result.model_id, "my_sfx_model")

    def test_bgm_falls_back_to_sound_effects_when_music_needs_paid_plan(self):
        calls = []

        def fake_urlopen(req, timeout):
            calls.append(req.full_url)
            if "/v1/music" in req.full_url:
                raise urllib.error.HTTPError(
                    req.full_url, 402, "Payment Required", {}, io.BytesIO(b"paid_plan_required")
                )
            return FakeResponse(fake_mp3(30))

        (bgm,) = plan_sound_assets(request(item("b", "배경음악", "반복 전투 배경음악")), PARSED)
        with (
            mock.patch.dict(os.environ, {"ELEVENLABS_BGM_ENDPOINT": "auto"}),
            mock.patch("urllib.request.urlopen", fake_urlopen),
        ):
            result = ElevenLabsSoundProvider(api_key="k").generate(bgm)
        self.assertIn("/v1/music", calls[0])
        self.assertIn("/v1/sound-generation", calls[1])
        self.assertEqual(result.endpoint, "sound-generation")
        self.assertAlmostEqual(mp3_duration(result.audio), 30, delta=0.1)

        with (
            mock.patch.dict(os.environ, {"ELEVENLABS_BGM_ENDPOINT": "music"}),
            mock.patch("urllib.request.urlopen", fake_urlopen),
            self.assertRaises(SoundProviderError),
        ):
            ElevenLabsSoundProvider(api_key="k").generate(bgm)

    def test_pcm_output_is_wrapped_with_the_requested_rate(self):
        (sfx,) = plan_sound_assets(request(item("s", "UI", "클릭")), PARSED)
        pcm = FakeResponse(b"\x00\x01" * 4800)
        with (
            mock.patch.dict(os.environ, {"ELEVENLABS_OUTPUT_FORMAT": "pcm_48000"}),
            mock.patch("urllib.request.urlopen", lambda req, timeout: pcm),
        ):
            result = ElevenLabsSoundProvider(api_key="k").generate(sfx)
        self.assertEqual(result.file_format, "wav")
        with open_wav(result.audio) as wav_file:
            self.assertEqual(wav_file.getframerate(), 48000)
        self.assertAlmostEqual(wav_duration(result.audio), 0.1, places=2)

    def test_transient_429_waits_and_retries_once(self):
        (sfx,) = plan_sound_assets(request(item("s", "UI", "클릭")), PARSED)
        busy = b'{"detail": {"status": "too_many_concurrent_requests"}}'
        responses = [http_error(429, busy, {"Retry-After": "2"}), FakeResponse(fake_mp3(0.5))]
        with (
            mock.patch("urllib.request.urlopen", side_effect=responses) as urlopen,
            mock.patch("time.sleep") as sleep,
        ):
            ElevenLabsSoundProvider(api_key="k").generate(sfx)
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(2.0)

        with (
            mock.patch("urllib.request.urlopen", side_effect=lambda *a, **k: http_error(429, busy)),
            mock.patch("time.sleep"),
            self.assertRaises(SoundProviderError) as caught,
        ):
            ElevenLabsSoundProvider(api_key="k").generate(sfx)
        self.assertFalse(caught.exception.fatal)

    def test_quota_exceeded_is_fatal_without_retry(self):
        (sfx,) = plan_sound_assets(request(item("s", "UI", "클릭")), PARSED)
        quota = http_error(429, b'{"detail": {"status": "quota_exceeded", "message": "x"}}')
        with (
            mock.patch("urllib.request.urlopen", side_effect=quota) as urlopen,
            self.assertRaises(SoundProviderError) as caught,
        ):
            ElevenLabsSoundProvider(api_key="k").generate(sfx)
        self.assertEqual(urlopen.call_count, 1)
        self.assertTrue(caught.exception.fatal)

    def test_broken_response_is_a_fatal_provider_error(self):
        sfx = plan_sound_assets(request(item("a", "UI", "클릭")), PARSED)[0]
        for error in (http.client.IncompleteRead(b"ab", 10), http.client.BadStatusLine("x")):
            with (
                mock.patch("urllib.request.urlopen", side_effect=error),
                self.assertRaises(SoundProviderError) as caught,
            ):
                ElevenLabsSoundProvider(api_key="k").generate(sfx)
            self.assertTrue(caught.exception.fatal)

    def test_provider_selection(self):
        with mock.patch.dict(os.environ, {"SOUND_PROVIDER": "auto"}, clear=False):
            os.environ.pop("ELEVENLABS_API_KEY", None)
            self.assertEqual(primary_provider().name, "procedural")
            os.environ["ELEVENLABS_API_KEY"] = "k"
            self.assertEqual(primary_provider().name, "elevenlabs")
        with mock.patch.dict(os.environ, {"SOUND_PROVIDER": "nope"}), self.assertRaises(ValueError):
            primary_provider()


class GenerateSoundNodeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(
            os.environ,
            {
                "MAINFLOW_WORKSPACE": self.tmp.name,
                "SOUND_BGM_SECONDS": "4",
                "SOUND_PROVIDER": "auto",
            },
        )
        self.env.start()
        os.environ.pop("ELEVENLABS_API_KEY", None)
        os.environ.pop("SOUND_FALLBACK", None)
        self.manager = ArtifactManager()
        self.project = self.manager.create_project()
        write = lambda name, payload: self.manager.write_json(
            self.project, "data", name, payload, producer="test"
        )
        self.state = {
            "project_id": self.project,
            "parsed_request": write("parsed_request.json", PARSED),
            "analysis": write("analysis.json", {}),
            "logic_analysis": write("logic_analysis.json", {}),
            "sound_asset_request": write(
                "sound_asset_request.json",
                request(
                    item("battle_bgm", "배경음악", "반복 전투 음악"),
                    item("hit_sfx", "공격 효과음", "타격음"),
                ),
            ),
        }

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_node_writes_wav_artifacts_and_draft(self):
        output = generate_sound_node(self.state)
        draft = self.manager.read_json(output["sound_draft"])
        self.assertEqual(draft["status"], "generated")
        self.assertEqual([a["asset_id"] for a in draft["assets"]], ["battle_bgm", "hit_sfx"])
        for asset in draft["assets"]:
            self.assertEqual(asset["artifact"]["media_type"], "audio/wav")
            self.assertTrue(asset["artifact"]["relative_path"].startswith("generated/sounds/"))
            audio = self.manager.read_bytes(asset["artifact"])
            self.assertAlmostEqual(wav_duration(audio), asset["duration_seconds"], places=2)
        self.assertIn("provider=procedural", draft["notes"])

    def test_elevenlabs_mp3_is_stored_as_mp3(self):
        os.environ["ELEVENLABS_API_KEY"] = "k"
        with mock.patch("urllib.request.urlopen", lambda req, timeout: FakeResponse(fake_mp3(2.0))):
            draft = self.manager.read_json(generate_sound_node(self.state)["sound_draft"])
        self.assertEqual(draft["status"], "generated")
        for asset in draft["assets"]:
            self.assertEqual(asset["file_format"], "mp3")
            self.assertEqual(asset["artifact"]["media_type"], "audio/mpeg")
            self.assertTrue(asset["artifact"]["relative_path"].endswith(".mp3"))
            self.assertAlmostEqual(asset["duration_seconds"], 2.0, delta=0.05)
        self.assertTrue(any("actual=" in note and "format=mp3" in note for note in draft["notes"]))

    def test_api_failure_falls_back_to_procedural(self):
        os.environ["ELEVENLABS_API_KEY"] = "k"
        error = urllib.error.HTTPError("u", 401, "Unauthorized", {}, io.BytesIO(b"bad key"))
        with mock.patch("urllib.request.urlopen", side_effect=error) as urlopen:
            draft = self.manager.read_json(generate_sound_node(self.state)["sound_draft"])
        self.assertEqual(urlopen.call_count, 1)  # a bad key is not retried for the next asset
        self.assertEqual(draft["status"], "generated")
        self.assertTrue(
            any("procedural 대체" in note and "HTTP 401" in note for note in draft["notes"])
        )

    def test_network_timeout_falls_back_to_procedural(self):
        os.environ["ELEVENLABS_API_KEY"] = "k"
        with mock.patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")) as urlopen:
            draft = self.manager.read_json(generate_sound_node(self.state)["sound_draft"])
        # BGM: music times out, SFX endpoint times out too (fatal) -> hit_sfx skips the API.
        self.assertEqual(urlopen.call_count, 2)
        self.assertEqual(draft["status"], "generated")
        self.assertEqual([a["provider"] for a in draft["assets"]], ["procedural"] * 2)
        self.assertTrue(
            any("procedural 대체" in note and "TimeoutError" in note for note in draft["notes"])
        )
        self.assertTrue(any("호출 생략" in note for note in draft["notes"]))

    def test_per_asset_http_error_does_not_trip_breaker(self):
        os.environ["ELEVENLABS_API_KEY"] = "k"
        error = urllib.error.HTTPError("u", 422, "Unprocessable", {}, io.BytesIO(b"bad prompt"))
        with mock.patch("urllib.request.urlopen", side_effect=error) as urlopen:
            generate_sound_node(self.state)
        self.assertEqual(urlopen.call_count, 3)  # music, SFX fallback for BGM, hit_sfx

    def test_slow_music_api_does_not_trip_breaker(self):
        os.environ["ELEVENLABS_API_KEY"] = "k"
        calls = []

        def fake_urlopen(req, timeout):
            calls.append(req.full_url.split("?")[0].removeprefix("https://api.elevenlabs.io"))
            if "/v1/music" in req.full_url:
                raise TimeoutError("timed out")
            return FakeResponse(fake_mp3(2.0))

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            draft = self.manager.read_json(generate_sound_node(self.state)["sound_draft"])
        self.assertEqual(calls, ["/v1/music", "/v1/sound-generation", "/v1/sound-generation"])
        self.assertEqual([a["provider"] for a in draft["assets"]], ["elevenlabs"] * 2)

    def test_api_failure_without_fallback_marks_draft_failed(self):
        os.environ["ELEVENLABS_API_KEY"] = "k"
        os.environ["SOUND_FALLBACK"] = "none"
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
            draft = self.manager.read_json(generate_sound_node(self.state)["sound_draft"])
        self.assertEqual(draft["status"], "failed")
        self.assertEqual(draft["assets"], [])
        with self.assertRaises(SoundProviderError):
            ElevenLabsSoundProvider(api_key="").generate(
                plan_sound_assets(request(item("a", "UI", "클릭")), PARSED)[0]
            )


if __name__ == "__main__":
    unittest.main()
