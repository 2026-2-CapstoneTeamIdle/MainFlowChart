"""Sound generation providers.

``SOUND_PROVIDER`` selects the primary provider:

- ``auto`` (default): ElevenLabs when ``ELEVENLABS_API_KEY`` is set, otherwise procedural
- ``elevenlabs``: always call ElevenLabs
- ``procedural``: offline synthesis only

When ElevenLabs fails for an asset, the procedural provider is used instead
unless ``SOUND_FALLBACK=none``; the fallback is recorded in the sound draft.
"""

from __future__ import annotations

import io
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import wave
from dataclasses import dataclass
from typing import Protocol

from sound_pipeline import procedural
from sound_pipeline.planner import SoundPlan

ELEVENLABS_URL = "https://api.elevenlabs.io"
SOUND_EFFECTS_MAX_SECONDS = 30.0


class SoundProviderError(RuntimeError):
    """A provider could not produce audio for one asset."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class ProviderResult:
    audio: bytes
    model_id: str
    request_id: str | None
    file_format: str = "wav"  # "wav" or "mp3"
    endpoint: str = "local"

    @property
    def media_type(self) -> str:
        return "audio/mpeg" if self.file_format == "mp3" else "audio/wav"


class SoundProvider(Protocol):
    name: str

    def generate(self, plan: SoundPlan) -> ProviderResult: ...


def wav_duration(audio: bytes) -> float:
    with wave.open(io.BytesIO(audio), "rb") as wav_file:
        return round(wav_file.getnframes() / wav_file.getframerate(), 3)


# MPEG audio frame header tables (Layer III only).
_MP3_BITRATES = {
    1: [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320],  # MPEG-1
    2: [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],  # MPEG-2/2.5
}
_MP3_SAMPLE_RATES = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000], 0: [11025, 12000, 8000]}


def mp3_duration(audio: bytes) -> float:
    """Duration from MP3 frame headers; the sample rate comes from the file itself."""

    position = 0
    if audio[:3] == b"ID3" and len(audio) >= 10:
        size = (audio[6] << 21) | (audio[7] << 14) | (audio[8] << 7) | audio[9]
        position = 10 + size
    seconds, frames = 0.0, 0
    while position + 4 <= len(audio):
        header = audio[position : position + 4]
        if header[0] != 0xFF or (header[1] & 0xE0) != 0xE0:
            position += 1
            continue
        version_bits = (header[1] >> 3) & 0x03  # 3=MPEG1, 2=MPEG2, 0=MPEG2.5
        layer_bits = (header[1] >> 1) & 0x03  # 1=Layer III
        bitrate_index = header[2] >> 4
        rate_index = (header[2] >> 2) & 0x03
        padding = (header[2] >> 1) & 0x01
        if version_bits == 1 or layer_bits != 1 or bitrate_index in (0, 15) or rate_index == 3:
            position += 1
            continue
        mpeg1 = version_bits == 3
        bitrate = _MP3_BITRATES[1 if mpeg1 else 2][bitrate_index] * 1000
        sample_rate = _MP3_SAMPLE_RATES[version_bits][rate_index]
        samples = 1152 if mpeg1 else 576
        length = (144 if mpeg1 else 72) * bitrate // sample_rate + padding
        seconds += samples / sample_rate
        frames += 1
        position += length
    if not frames:
        raise SoundProviderError("Response is not a decodable MP3 stream")
    return round(seconds, 3)


def audio_duration(audio: bytes, file_format: str) -> float:
    return mp3_duration(audio) if file_format == "mp3" else wav_duration(audio)


def pcm_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm[: len(pcm) - len(pcm) % 2])
    return buffer.getvalue()


class ProceduralSoundProvider:
    name = "procedural"

    def generate(self, plan: SoundPlan) -> ProviderResult:
        seed = f"{plan.asset_id}:{plan.mood_style}:{plan.genre}"
        if plan.kind == "bgm":
            audio = procedural.render_bgm(
                plan.mood_style, plan.genre, plan.duration_seconds, plan.loop, seed
            )
        else:
            audio = procedural.render_sfx(
                plan.category, plan.mood_style, plan.duration_seconds, plan.loop, seed
            )
        return ProviderResult(audio, "procedural_synth_v1", None)


class ElevenLabsSoundProvider:
    """SFX via the Sound Effects endpoint; BGM via the Music endpoint.

    - ``ELEVENLABS_OUTPUT_FORMAT`` (default ``mp3_44100_128``): MP3 is stored as
      returned, so the sample rate is read from the file instead of assumed.
      ``pcm_<rate>`` is still accepted and wrapped as WAV.
    - ``ELEVENLABS_SFX_MODEL``: empty (default) lets ``/v1/sound-generation``
      use its own sound-effects model; set an ID only to pin a specific model.
    - ``ELEVENLABS_BGM_ENDPOINT``: ``auto`` (default) tries ``/v1/music`` and,
      when the plan does not include the Music API (HTTP 402), generates a
      looping bed of up to 30 s with the Sound Effects endpoint; ``music`` or
      ``sound_effects`` forces one endpoint.
    """

    name = "elevenlabs"

    def __init__(self, api_key: str | None = None, timeout: float | None = None) -> None:
        self.api_key = api_key or os.environ.get("ELEVENLABS_API_KEY", "")
        self.output_format = os.environ.get("ELEVENLABS_OUTPUT_FORMAT", "mp3_44100_128")
        self.sfx_model = os.environ.get("ELEVENLABS_SFX_MODEL", "")
        self.music_model = os.environ.get("ELEVENLABS_MUSIC_MODEL", "")
        self.bgm_endpoint = os.environ.get("ELEVENLABS_BGM_ENDPOINT", "auto").lower()
        self.timeout = timeout or float(os.environ.get("SOUND_TIMEOUT_SECONDS", "300"))
        if not (self.output_format.startswith("mp3_") or self.output_format.startswith("pcm_")):
            raise ValueError("ELEVENLABS_OUTPUT_FORMAT must be an mp3_* or pcm_* format")

    def _post(self, path: str, body: dict[str, object]) -> tuple[bytes, str | None]:
        if not self.api_key:
            raise SoundProviderError("ELEVENLABS_API_KEY is not set")
        query = urllib.parse.urlencode({"output_format": self.output_format})
        request = urllib.request.Request(
            f"{ELEVENLABS_URL}{path}?{query}",
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={"xi-api-key": self.api_key, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                headers = {key.lower(): value for key, value in response.headers.items()}
                return response.read(), headers.get("request-id") or headers.get("x-request-id")
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:300]
            raise SoundProviderError(
                f"ElevenLabs HTTP {error.code} ({path}): {detail}", error.code
            ) from error
        except urllib.error.URLError as error:
            raise SoundProviderError(f"Cannot reach ElevenLabs: {error.reason}") from error
        except OSError as error:  # TimeoutError/socket.timeout, connection reset during read
            raise SoundProviderError(f"ElevenLabs connection failed: {error!r}") from error

    def _result(
        self, payload: bytes, model: str, request_id: str | None, endpoint: str
    ) -> ProviderResult:
        if len(payload) < 4:
            raise SoundProviderError("ElevenLabs returned no audio")
        if self.output_format.startswith("pcm_"):
            rate = int(self.output_format.split("_")[1])
            return ProviderResult(pcm_to_wav(payload, rate), model, request_id, "wav", endpoint)
        mp3_duration(payload)  # validates the stream before it is stored
        return ProviderResult(payload, model, request_id, "mp3", endpoint)

    def _sound_effects(self, prompt: str, seconds: float, loop: bool) -> ProviderResult:
        body: dict[str, object] = {
            "text": prompt,
            "duration_seconds": min(max(seconds, 0.5), SOUND_EFFECTS_MAX_SECONDS),
            "prompt_influence": 0.5,
        }
        if self.sfx_model:
            body["model_id"] = self.sfx_model
        if loop:
            body["loop"] = True
        payload, request_id = self._post("/v1/sound-generation", body)
        model = self.sfx_model or "sound_effects_api_default"
        return self._result(payload, model, request_id, "sound-generation")

    def _music(self, plan: SoundPlan) -> ProviderResult:
        body: dict[str, object] = {
            "prompt": plan.prompt,
            "music_length_ms": int(min(max(plan.duration_seconds, 3.0), 600.0) * 1000),
        }
        if self.music_model:
            body["model_id"] = self.music_model
        payload, request_id = self._post("/v1/music", body)
        return self._result(payload, self.music_model or "music_api_default", request_id, "music")

    def generate(self, plan: SoundPlan) -> ProviderResult:
        if plan.kind != "bgm":
            return self._sound_effects(plan.prompt, plan.duration_seconds, plan.loop)
        if self.bgm_endpoint == "sound_effects":
            return self._sound_effects(plan.prompt, plan.duration_seconds, plan.loop)
        try:
            return self._music(plan)
        except SoundProviderError as error:
            if self.bgm_endpoint != "auto" or error.status != 402:
                raise
            return self._sound_effects(plan.prompt, plan.duration_seconds, plan.loop)


def primary_provider() -> SoundProvider:
    choice = os.environ.get("SOUND_PROVIDER", "auto").lower()
    if choice == "procedural":
        return ProceduralSoundProvider()
    if choice == "elevenlabs" or (choice == "auto" and os.environ.get("ELEVENLABS_API_KEY")):
        return ElevenLabsSoundProvider()
    if choice != "auto":
        raise ValueError(f"Unsupported SOUND_PROVIDER: {choice}")
    return ProceduralSoundProvider()


def fallback_provider() -> SoundProvider | None:
    if os.environ.get("SOUND_FALLBACK", "procedural").lower() == "none":
        return None
    return ProceduralSoundProvider()
