from __future__ import annotations

import unittest

from game_pipeline import normalize_game_spec
from game_pipeline.design_v2 import build_design_v2
from game_pipeline.presentation_sound_assets import with_presentation_sound_assets


class PresentationSoundAssetsTest(unittest.TestCase):
    def test_feedback_cues_receive_distinct_bindable_sound_assets(self) -> None:
        spec = normalize_game_spec("타워 디펜스", {})
        baseline = build_design_v2(spec, "기지를 방어한다")
        expanded = with_presentation_sound_assets(spec, baseline["presentation_plan"])
        rebuilt = build_design_v2(expanded, "기지를 방어한다")

        requested = {
            item["asset_id"]
            for item in expanded["asset_requirements"]
            if item["asset_type"] == "sound"
        }
        cue_assets = {
            cue["audio_asset_id"] for cue in rebuilt["presentation_plan"]["feedback_cues"]
        }
        self.assertTrue(cue_assets)
        self.assertTrue(cue_assets <= requested)
        self.assertEqual(len(cue_assets), len(rebuilt["presentation_plan"]["feedback_cues"]))

    def test_expansion_is_idempotent(self) -> None:
        spec = normalize_game_spec("뱀서류", {})
        baseline = build_design_v2(spec, "생존한다")
        once = with_presentation_sound_assets(spec, baseline["presentation_plan"])
        twice = with_presentation_sound_assets(once, baseline["presentation_plan"])

        self.assertEqual(once, twice)


if __name__ == "__main__":
    unittest.main()
