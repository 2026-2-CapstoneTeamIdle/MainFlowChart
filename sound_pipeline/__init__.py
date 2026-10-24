"""Sound generation used by the generate_sound node."""

from sound_pipeline.planner import SoundPlan, classify, plan_sound_assets
from sound_pipeline.providers import (
    ElevenLabsSoundProvider,
    ProceduralSoundProvider,
    ProviderResult,
    SoundProvider,
    SoundProviderError,
    audio_duration,
    fallback_provider,
    mp3_duration,
    primary_provider,
    wav_duration,
)

__all__ = [
    "ElevenLabsSoundProvider",
    "ProceduralSoundProvider",
    "ProviderResult",
    "SoundPlan",
    "SoundProvider",
    "SoundProviderError",
    "audio_duration",
    "classify",
    "fallback_provider",
    "mp3_duration",
    "plan_sound_assets",
    "primary_provider",
    "wav_duration",
]
