"""Sound validation tests (G1 checks, G2 fixes, decisions, validate_sound node)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from mainflow.ArtifactManager import ArtifactManager
from mainflow.nodes.validate_sound import validate_sound_node
from sound_pipeline.planner import SoundPlan
from sound_pipeline.validation import (
    SoundDecoderUnavailable,
    check_asset,
    decode,
    encode_wav,
)
from tests.test_sound_generation import PARSED, item, request

RATE = 22050
CRITERIA = {
    "sound-file-valid": True,
    "sound-duration-match": True,
    "sound-true-peak": True,
    "sound-onset-latency": True,
    "sound-tail-decay": True,
    "sound-dc-offset": True,
    "sound-loop-seam": True,
    "sound-channel-layout": False,
    "sound-set-duplicate": True,
    "sound-not-placeholder": False,
}


def impact(seconds=0.7, gain=0.7, pad=0.0, dc=0.0, seed=1) -> np.ndarray:
    """Decaying noise burst: a well-formed hit sound unless distorted by the arguments."""
    t = np.arange(int(seconds * RATE)) / RATE
    body = gain * np.random.default_rng(seed).uniform(-1, 1, t.size) * np.exp(-t * 18)
    samples = np.concatenate([np.zeros(int(pad * RATE)), body]) + dc
    return samples.astype(np.float32)[:, None]


def plan(asset_id="hit", category="impact", seconds=0.7, loop=False, kind="sfx", required=True):
    return SoundPlan(
        asset_id, asset_id, asset_id, kind, category, "x", seconds, loop, "Horror", "x", required
    )


def qc_of(samples, sound_plan=None, placeholder=False):
    return check_asset(
        encode_wav(samples, RATE), "wav", sound_plan or plan(), CRITERIA, placeholder
    )


class AssetCheckTest(unittest.TestCase):
    def test_clean_sound_passes_without_fixes(self):
        qc = qc_of(impact())
        self.assertEqual((qc.decision, qc.failed, qc.applied_fixes), ("PASS", [], []))
        self.assertIsNone(qc.processed_wav)

    def test_padding_peak_and_dc_are_fixed_by_dsp(self):
        qc = qc_of(impact(seconds=0.6, gain=0.99, pad=0.1, dc=0.02))
        self.assertEqual(qc.decision, "FIX")
        self.assertEqual(qc.failed, [])
        self.assertEqual(
            qc.applied_fixes,
            # DC on the padding hides it until the first pass removes the DC.
            ["remove_dc", "fade_out_20ms", "normalize_peak_-1dbfs", "trim_leading_silence"],
        )
        fixed, _ = decode(qc.processed_wav, "wav")
        self.assertLessEqual(np.abs(fixed).max(), 10 ** (-1 / 20))
        self.assertLess(qc.metrics["onset_ms"], 10)

    def test_clipping_cannot_be_fixed(self):
        qc = qc_of(np.clip(impact(gain=3.0), -1, 1))
        self.assertEqual(qc.decision, "REGENERATE")
        self.assertIn("sound-true-peak", qc.failed)

    def test_wrong_duration_is_regenerated(self):
        qc = qc_of(impact(seconds=2.0))
        self.assertEqual(qc.decision, "REGENERATE")
        self.assertEqual(qc.failed, ["sound-duration-match"])

    def test_cut_off_tail_gets_fade(self):
        samples = impact()
        samples[-200:, 0] = np.random.default_rng(3).uniform(-0.5, 0.5, 200)  # cut mid-sound
        qc = qc_of(samples)
        self.assertEqual(qc.decision, "FIX")
        self.assertIn("fade_out_20ms", qc.applied_fixes)

    def test_loop_seam_click_is_crossfaded(self):
        t = np.arange(4 * RATE) / RATE
        ramp = (0.5 * np.sin(2 * np.pi * 110 * t) + 0.4 * (t / t[-1])).astype(np.float32)
        qc = qc_of(ramp[:, None], plan("amb", "ambience", 4.0, loop=True))
        self.assertEqual(qc.decision, "FIX")
        self.assertIn("loop_crossfade_20ms", qc.applied_fixes)

    def test_placeholder_goes_to_review_not_pass(self):
        qc = qc_of(impact(), placeholder=True)
        self.assertEqual(qc.decision, "REVIEW")
        self.assertEqual(qc.failed, ["sound-not-placeholder"])

    def test_garbage_bytes_are_regenerated(self):
        qc = check_asset(b"not audio", "wav", plan(), CRITERIA, False)
        self.assertEqual((qc.decision, qc.failed), ("REGENERATE", ["sound-file-valid"]))

    def test_missing_ffmpeg_is_review_not_regenerate(self):
        with mock.patch("shutil.which", return_value=None):
            qc = check_asset(b"ID3 mp3 bytes", "mp3", plan(), CRITERIA, False)
        self.assertEqual((qc.decision, qc.failed), ("REVIEW", ["sound-validator-unavailable"]))

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
    def test_mp3_is_decoded_with_ffmpeg(self):
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder, "a.wav"), Path(folder, "a.mp3")
            source.write_bytes(encode_wav(impact(), RATE))
            subprocess.run(["ffmpeg", "-v", "error", "-i", str(source), str(target)], check=True)
            samples, rate = decode(target.read_bytes(), "mp3")
        self.assertEqual(rate, RATE)
        self.assertAlmostEqual(len(samples) / rate, 0.7, delta=0.1)


class ValidateSoundNodeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"MAINFLOW_WORKSPACE": self.tmp.name})
        self.env.start()
        self.manager = ArtifactManager()
        self.project = self.manager.create_project()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def run_node(self, assets, items, spec_criteria=()):
        def write(name, payload):
            return self.manager.write_json(self.project, "data", name, payload, producer="test")

        draft_assets = []
        for asset_id, samples, provider in assets:
            reference = self.manager.write_bytes(
                self.project, "sound", f"{asset_id}.wav", encode_wav(samples, RATE), producer="t"
            )
            draft_assets.append(
                {
                    "asset_id": asset_id,
                    "unity_binding_key": next(
                        i["unity_binding_key"] for i in items if i["asset_id"] == asset_id
                    ),
                    "name": asset_id,
                    "artifact": reference,
                    "file_format": "wav",
                    "duration_seconds": len(samples) / RATE,
                    "prompt": "x",
                    "provider": provider,
                }
            )
        state = {
            "project_id": self.project,
            "parsed_request": write("parsed.json", PARSED),
            "sound_asset_request": write("request.json", request(*items)),
            "sound_draft": write("draft.json", {"assets": draft_assets, "notes": []}),
            "asset_validation_spec": write(
                "spec.json", {"sound_criteria": list(spec_criteria), "image_criteria": []}
            ),
        }
        result = self.manager.read_json(validate_sound_node(state)["sound_validation_result"])
        profile = json.loads(
            (Path(self.tmp.name) / self.project / "validation/sound_profile.json").read_text(
                encoding="utf-8"
            )
        )
        return result, profile

    def test_clean_set_passes_and_fixed_copy_is_stored(self):
        result, profile = self.run_node(
            [("hit", impact(), "elevenlabs"), ("shot", impact(pad=0.05, seed=2), "elevenlabs")],
            [item("hit", "공격 효과음", "타격음"), item("shot", "발사 효과음", "발사")],
        )
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["validated_asset_ids"], ["hit", "shot"])
        self.assertEqual([a["decision"] for a in profile["assets"]], ["PASS", "FIX"])
        self.assertEqual(
            profile["assets"][1]["processed_path"], "generated/sounds/processed/shot.wav"
        )
        selected = {asset["asset_id"]: asset for asset in result["validated_assets"]["assets"]}
        self.assertEqual(selected["hit"]["artifact"]["relative_path"], "generated/sounds/hit.wav")
        self.assertEqual(
            selected["shot"]["artifact"]["relative_path"], profile["assets"][1]["processed_path"]
        )
        self.assertEqual(selected["shot"]["file_format"], "wav")
        self.assertNotEqual(
            self.manager.read_bytes(selected["shot"]["artifact"]),
            encode_wav(impact(pad=0.05, seed=2), RATE),
        )
        self.assertTrue(all(check["passed"] for check in result["checks"]))

    def test_missing_required_asset_fails(self):
        result, _ = self.run_node(
            [("hit", impact(), "elevenlabs")],
            [item("hit", "공격 효과음", "타격음"), item("lost", "발사 효과음", "발사")],
        )
        self.assertEqual(result["status"], "failed")
        self.assertIn(
            ("sound-missing-asset", "error", "lost"),
            [(i["code"], i["severity"], i.get("target_id")) for i in result["issues"]],
        )

    def test_duplicate_and_placeholder_need_revision(self):
        same = impact()
        result, profile = self.run_node(
            [
                ("hit", same, "elevenlabs"),
                ("shot", same, "elevenlabs"),
                ("bgm", same, "procedural"),
            ],
            [
                item("hit", "공격 효과음", "타격음"),
                item("shot", "발사 효과음", "발사"),
                item("bgm", "공격 효과음", "타격음"),
            ],
        )
        self.assertEqual(result["status"], "needs_revision")
        decisions = {a["asset_id"]: a["decision"] for a in profile["assets"]}
        self.assertEqual(decisions, {"hit": "PASS", "shot": "REGENERATE", "bgm": "REGENERATE"})
        self.assertEqual(result["validated_asset_ids"], ["hit"])

    def test_unavailable_decoder_is_reported_as_warning(self):
        unavailable = SoundDecoderUnavailable("MP3 디코딩에 ffmpeg가 필요합니다")
        with mock.patch("sound_pipeline.validation.decode", side_effect=unavailable):
            result, profile = self.run_node(
                [("hit", impact(), "elevenlabs")], [item("hit", "공격 효과음", "타격음")]
            )
        self.assertEqual(result["status"], "needs_revision")
        self.assertEqual(profile["assets"][0]["decision"], "REVIEW")
        self.assertIn(
            ("sound-validator-unavailable", "warning"),
            [(i["code"], i["severity"]) for i in result["issues"]],
        )

    def test_spec_criteria_limit_what_is_checked(self):
        only_file = [
            {
                "criterion_id": "sound-file-valid",
                "target": "sound",
                "description": "",
                "required": True,
            }
        ]
        result, _ = self.run_node(
            [("hit", impact(seconds=2.0), "elevenlabs")],
            [item("hit", "공격 효과음", "타격음")],
            only_file,
        )
        self.assertEqual(result["status"], "passed")
        self.assertEqual([c["criterion_id"] for c in result["checks"]], ["sound-file-valid"])


if __name__ == "__main__":
    unittest.main()
