"""Offline, deterministic sound synthesis (standard library only).

Used when no generation API is configured or the API call fails, so the
workflow always produces playable placeholder WAV files. Mood picks the scale,
tempo and timbre; the SFX category picks the envelope and noise shape.
"""

from __future__ import annotations

import io
import math
import random
import wave
import zlib
from array import array

SAMPLE_RATE = 22050

# mood -> (tempo bpm, scale semitones, root Hz, waveform, brightness 0..1)
MOOD_SYNTH = {
    "Cyberpunk": (122, (0, 3, 5, 7, 10), 110.0, "square", 0.9),
    "Medieval": (96, (0, 2, 3, 5, 7, 9, 10), 146.8, "triangle", 0.5),
    "Modern": (110, (0, 2, 4, 7, 9), 130.8, "sine", 0.6),
    "Fantasy": (100, (0, 2, 4, 5, 7, 9, 11), 146.8, "triangle", 0.6),
    "Horror": (68, (0, 1, 3, 6, 7, 10), 98.0, "sine", 0.3),
    "Cozy": (84, (0, 2, 4, 7, 9), 174.6, "sine", 0.4),
}
GENRE_DRIVE = {
    "SurvivorLike": 1.0,
    "Platformer": 0.8,
    "TowerDefense": 0.6,
    "CardGame": 0.4,
    "RaisingSimulation": 0.4,
    "VisualNovel": 0.2,
}


def _osc(kind: str, phase: float) -> float:
    if kind == "square":
        return 0.6 if math.sin(phase) >= 0 else -0.6
    if kind == "triangle":
        return 2 / math.pi * math.asin(math.sin(phase))
    return math.sin(phase)


def _encode(samples: array) -> bytes:
    peak = max((abs(value) for value in samples), default=0.0) or 1.0
    scale = 0.8 * 32767 / peak
    pcm = array("h", (int(value * scale) for value in samples))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(pcm.tobytes())
    return buffer.getvalue()


def _rng(seed_text: str) -> random.Random:
    return random.Random(zlib.crc32(seed_text.encode("utf-8")))


def _lowpass(values: list[float], amount: float) -> list[float]:
    out, state = [], 0.0
    for value in values:
        state += amount * (value - state)
        out.append(state)
    return out


def _loop_crossfade(values: list[float], fade: int) -> list[float]:
    """Blend the overhang into the start so the last sample flows into the first."""
    body, tail = values[:-fade], values[-fade:]
    for index in range(fade):
        weight = index / fade
        body[index] = body[index] * weight + tail[index] * (1 - weight)
    return body


def render_bgm(mood: str, genre: str, seconds: float, loop: bool, seed: str) -> bytes:
    tempo, scale, root, waveform, brightness = MOOD_SYNTH.get(mood, MOOD_SYNTH["Fantasy"])
    drive = GENRE_DRIVE.get(genre, 0.6)
    rng = _rng(seed)
    beat = 60.0 / tempo
    bar = beat * 4
    bars = max(2, round(seconds / bar))
    fade = int(SAMPLE_RATE * 0.25) if loop else 0
    total = int(bars * bar * SAMPLE_RATE) + fade

    progression = [0, 5, 3, 4] if 3 in scale[:3] else [0, 4, 5, 3]
    degrees = [scale[i % len(scale)] + 12 * (i // len(scale)) for i in range(len(scale) * 2)]
    melody = [rng.choice(degrees[: len(scale) + 3]) for _ in range(bars * 4)]
    harmonic = 0.35 * brightness

    out = [0.0] * total
    two_pi = 2 * math.pi
    for n in range(total):
        t = n / SAMPLE_RATE
        bar_index = int(t / bar) % bars
        beat_index = int(t / beat) % (bars * 4)
        in_bar, in_beat = t % bar, t % beat
        chord_root = root * 2 ** (scale[progression[bar_index % 4] % len(scale)] / 12)
        pad = 0.0
        for interval in (0, 4 if 4 in scale else 3, 7):
            freq = chord_root * 2 ** (interval / 12)
            pad += _osc(waveform, two_pi * freq * t) + harmonic * math.sin(two_pi * 2 * freq * t)
        pad *= 0.12 * (0.6 + 0.4 * math.exp(-in_bar * 1.5))
        note = root * 2 * 2 ** (melody[beat_index] / 12)
        lead = 0.22 * math.sin(two_pi * note * t) * math.exp(-in_beat * 4)
        bass = 0.25 * math.sin(two_pi * chord_root / 2 * t)
        drums = 0.0
        if drive > 0.3:
            drums += 0.5 * drive * math.sin(two_pi * 55 * in_beat) * math.exp(-in_beat * 22)
            half = in_beat % (beat / 2)
            drums += 0.08 * drive * (rng.random() * 2 - 1) * math.exp(-half * 90)
        out[n] = pad + lead + bass + drums

    if loop:
        out = _loop_crossfade(out, fade)
    else:
        fade_out = int(SAMPLE_RATE * 1.5)
        for index in range(fade_out):
            out[-fade_out + index] *= 1 - index / fade_out
    return _encode(array("f", out))


def render_sfx(category: str, mood: str, seconds: float, loop: bool, seed: str) -> bytes:
    _, _, root, waveform, brightness = MOOD_SYNTH.get(mood, MOOD_SYNTH["Fantasy"])
    rng = _rng(seed)
    count = max(1, int(seconds * SAMPLE_RATE))
    two_pi = 2 * math.pi
    out: list[float]

    if category == "ui":
        freq = root * 8
        out = [
            (_osc(waveform, two_pi * freq * t) + 0.4 * math.sin(two_pi * freq * 2 * t))
            * math.exp(-t * 25)
            * min(1.0, t / 0.002)
            for t in (n / SAMPLE_RATE for n in range(count))
        ]
    elif category == "impact":
        noise = _lowpass([rng.random() * 2 - 1 for _ in range(count)], 0.3 + 0.5 * brightness)
        out = [
            (0.7 * noise[n] + 0.6 * math.sin(two_pi * (180 - 120 * t / seconds) * t))
            * math.exp(-t * 9)
            * min(1.0, t / 0.003)
            for n, t in ((n, n / SAMPLE_RATE) for n in range(count))
        ]
    elif category == "explosion":
        noise = _lowpass(_lowpass([rng.random() * 2 - 1 for _ in range(count)], 0.08), 0.15)
        out = [
            (3.0 * noise[n] + 0.4 * math.sin(two_pi * 50 * t))
            * math.exp(-t * 2.0)
            * min(1.0, t / 0.01)
            for n, t in ((n, n / SAMPLE_RATE) for n in range(count))
        ]
    elif category == "ambience":
        fade = int(SAMPLE_RATE * 0.5) if loop else 0
        noise = _lowpass(
            [rng.random() * 2 - 1 for _ in range(count + fade)], 0.05 + 0.1 * brightness
        )
        out = [
            noise[n] * (0.75 + 0.25 * math.sin(two_pi * 0.2 * n / SAMPLE_RATE))
            for n in range(count + fade)
        ]
        out = _loop_crossfade(out, fade) if loop else out
    else:  # generic gameplay action: short rising chirp
        out = [
            _osc(waveform, two_pi * (root * 4 + root * 6 * t / seconds) * t)
            * math.exp(-t * 6)
            * min(1.0, t / 0.004)
            for t in (n / SAMPLE_RATE for n in range(count))
        ]
    return _encode(array("f", out))
