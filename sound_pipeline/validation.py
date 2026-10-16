"""Deterministic sound QC used by the validate_sound node.

Implements stage 1-2 of ``SoundValidationPlan.md``: G1 technical checks, G2 DSP
fixes (always tried before regeneration), set-level duplicate detection and the
PASS / FIX / REGENERATE / REVIEW decision. Model-based content checks (G3),
candidate selection and the regeneration loop are not implemented yet.
"""

from __future__ import annotations

import hashlib
import io
import shutil
import subprocess
import tempfile
import wave
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from sound_pipeline.planner import SoundPlan

# (criterion_id, description, required) — the defaults written to sound_criteria.
SOUND_CRITERIA: tuple[tuple[str, str, bool], ...] = (
    ("sound-file-valid", "MP3/WAV 디코딩 성공, 무음이 아님", True),
    ("sound-duration-match", "실측 길이가 요청 길이의 ±20% (최소 0.1 s) 이내", True),
    ("sound-true-peak", "피크 ≤ -1 dBFS, 클리핑(평평한 피크) 없음", True),
    ("sound-onset-latency", "첫 유효 소리까지 효과음 ≤ 10 ms, UI ≤ 5 ms, 폭발 ≤ 20 ms", True),
    ("sound-tail-decay", "비루프 에셋의 끝이 -60 dBFS까지 감쇠, 마지막 샘플 불연속 없음", True),
    ("sound-dc-offset", "채널별 평균 샘플값 |DC| < 0.005", True),
    ("sound-loop-seam", "루프 에셋의 끝→처음 이음매에 튐·음량 급변 없음", True),
    ("sound-channel-layout", "stereo의 좌우 상관계수 > 0 (mono 합산 시 상쇄 없음)", False),
    ("sound-set-duplicate", "서로 다른 에셋이 같은 파일이 아님", True),
    ("sound-not-placeholder", "절차적 합성 대체물이 아님 (대체물은 사람 리뷰)", False),
)

ONSET_LIMIT_MS = {"ui": 5.0, "explosion": 20.0}  # other sfx: 10 ms, BGM/ambience: not checked
PEAK_LIMIT_DBFS = -1.0
SILENCE_DBFS = -50.0
TAIL_DBFS = -60.0
FADE_MS = 20.0


class SoundDecodeError(ValueError):
    """Audio bytes could not be decoded into samples."""


@dataclass
class AssetQC:
    asset_id: str
    category: str
    required: bool
    decision: str = "PASS"
    metrics: dict[str, float] = field(default_factory=dict)
    failed: list[str] = field(default_factory=list)
    applied_fixes: list[str] = field(default_factory=list)
    processed_wav: bytes | None = None
    error: str | None = None


def _db(value: float) -> float:
    return round(20 * float(np.log10(max(value, 1e-9))), 2)


def decode(audio: bytes, file_format: str) -> tuple[np.ndarray, int]:
    """Return float32 samples shaped (frames, channels) in [-1, 1] and the sample rate."""
    if file_format == "mp3":
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise SoundDecodeError("MP3 디코딩에 ffmpeg가 필요합니다")
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder, "in.mp3"), Path(folder, "out.wav")
            source.write_bytes(audio)
            done = subprocess.run(
                [ffmpeg, "-v", "error", "-y", "-i", str(source), "-c:a", "pcm_s16le", str(target)],
                capture_output=True,
                timeout=120,
                check=False,
            )
            if done.returncode != 0:
                raise SoundDecodeError(done.stderr.decode("utf-8", "replace")[:200])
            audio = target.read_bytes()
    try:
        with wave.open(io.BytesIO(audio), "rb") as wav_file:
            width, channels = wav_file.getsampwidth(), wav_file.getnchannels()
            rate, raw = wav_file.getframerate(), wav_file.readframes(wav_file.getnframes())
    except (wave.Error, EOFError) as error:
        raise SoundDecodeError(f"WAV 디코딩 실패: {error}") from error
    if width != 2:
        raise SoundDecodeError(f"지원하지 않는 WAV 샘플 폭: {width * 8} bit")
    samples = np.frombuffer(raw, "<i2").astype(np.float32) / 32768.0
    return samples.reshape(-1, channels), rate


def encode_wav(samples: np.ndarray, rate: int) -> bytes:
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(samples.shape[1])
        wav_file.setsampwidth(2)
        wav_file.setframerate(rate)
        wav_file.writeframes(pcm.tobytes())
    return buffer.getvalue()


def _onset_index(mono: np.ndarray) -> int:
    loud = np.flatnonzero(np.abs(mono) > 10 ** (SILENCE_DBFS / 20))
    return int(loud[0]) if loud.size else len(mono)


def measure(samples: np.ndarray, rate: int) -> dict[str, float]:
    mono = samples.mean(axis=1)
    magnitude = np.abs(samples)
    peak = float(magnitude.max()) if samples.size else 0.0
    # Clipping = 3+ identical samples at the peak; level-independent, so it survives normalisation.
    hot = magnitude[1:-1] >= 0.99 * peak
    flat = (samples[1:-1] == samples[:-2]) & (samples[1:-1] == samples[2:]) & hot
    edge = max(1, int(rate * 0.01))
    diffs = np.abs(np.diff(mono))
    metrics = {
        "duration_s": round(len(samples) / rate, 3),
        "channels": float(samples.shape[1]),
        "sample_rate": float(rate),
        # shortcut: sample peak, not 4x-oversampled true peak; upgrade when MP3 overs show up in review.
        "peak_dbfs": _db(peak),
        "clipped_runs": float(flat.sum()) if peak > 0.5 else 0.0,
        "onset_ms": round(_onset_index(mono) / rate * 1000, 2),
        # Tail = RMS of the last 2 ms, i.e. what is still sounding when the file stops.
        "tail_dbfs": _db(float(np.sqrt(np.mean(mono[-max(1, edge // 5) :] ** 2))))
        if mono.size
        else -180.0,
        "last_sample": round(float(np.abs(mono[-1])) if mono.size else 0.0, 4),
        "dc_offset": round(float(np.abs(samples.mean(axis=0)).max()) if samples.size else 0.0, 5),
        # Loop seam: wrap-around jump vs the file's own 99th-percentile step, and edge RMS ratio.
        "seam_jump_ratio": round(
            float(abs(mono[-1] - mono[0]) / (np.percentile(diffs, 99) + 1e-6)) if diffs.size else 0,
            3,
        ),
        "seam_level_db": round(
            abs(
                _db(float(np.sqrt(np.mean(mono[-edge * 5 :] ** 2))))
                - _db(float(np.sqrt(np.mean(mono[: edge * 5] ** 2))))
            ),
            2,
        ),
    }
    if samples.shape[1] == 2 and np.std(samples[:, 0]) > 1e-4 and np.std(samples[:, 1]) > 1e-4:
        metrics["lr_correlation"] = round(float(np.corrcoef(samples[:, 0], samples[:, 1])[0, 1]), 3)
    return metrics


def failed_checks(metrics: dict[str, float], plan: SoundPlan) -> list[str]:
    failed: list[str] = []
    if metrics["peak_dbfs"] <= SILENCE_DBFS:
        return ["sound-file-valid"]
    requested = plan.duration_seconds
    if abs(metrics["duration_s"] - requested) > max(0.2 * requested, 0.1):
        failed.append("sound-duration-match")
    if metrics["peak_dbfs"] > PEAK_LIMIT_DBFS or metrics["clipped_runs"] > 0:
        failed.append("sound-true-peak")
    if plan.kind == "sfx" and not plan.loop:
        if metrics["onset_ms"] > ONSET_LIMIT_MS.get(plan.category, 10.0):
            failed.append("sound-onset-latency")
        if metrics["tail_dbfs"] > TAIL_DBFS or metrics["last_sample"] > 0.01:
            failed.append("sound-tail-decay")
    if metrics["dc_offset"] >= 0.005:
        failed.append("sound-dc-offset")
    if plan.loop and (metrics["seam_jump_ratio"] > 1.0 or metrics["seam_level_db"] > 6.0):
        failed.append("sound-loop-seam")
    if metrics.get("lr_correlation", 1.0) <= 0:
        failed.append("sound-channel-layout")
    return failed


def apply_fixes(
    samples: np.ndarray, rate: int, failed: list[str], loop: bool
) -> tuple[np.ndarray, list[str]]:
    """G2: zero-cost DSP repairs for the G1 failures that editing can fix."""
    fixes: list[str] = []
    fade = int(rate * FADE_MS / 1000)
    if "sound-dc-offset" in failed:
        samples = samples - samples.mean(axis=0)
        fixes.append("remove_dc")
    if "sound-onset-latency" in failed:
        start = max(0, _onset_index(samples.mean(axis=1)) - int(rate * 0.002))
        samples = samples[start:]
        fixes.append("trim_leading_silence")
    if "sound-tail-decay" in failed and len(samples) > fade:
        samples = samples.copy()
        samples[-fade:] *= (np.linspace(1.0, 0.0, fade, dtype=np.float32) ** 3)[:, None]
        fixes.append(f"fade_out_{FADE_MS:g}ms")
    if "sound-loop-seam" in failed and loop and len(samples) > 2 * fade:
        ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)[:, None]
        head = samples[:fade] * ramp + samples[-fade:] * (1 - ramp)
        samples = np.concatenate([head, samples[fade:-fade]])
        fixes.append(f"loop_crossfade_{FADE_MS:g}ms")
    peak = float(np.abs(samples).max()) if samples.size else 0.0
    if "sound-true-peak" in failed and peak > 0:
        samples = samples * (10 ** ((PEAK_LIMIT_DBFS - 0.1) / 20) / peak)
        fixes.append("normalize_peak_-1dbfs")
    return samples.astype(np.float32), fixes


def _decide(qc: AssetQC, criteria: dict[str, bool], placeholder: bool) -> None:
    qc.failed = [criterion for criterion in qc.failed if criterion in criteria]
    if any(criteria[criterion] for criterion in qc.failed):
        qc.decision = "REGENERATE"
    elif placeholder or qc.failed:  # placeholder or optional-criterion warnings: a human decides
        qc.decision = "REVIEW"
    else:
        qc.decision = "FIX" if qc.applied_fixes else "PASS"


def check_asset(
    audio: bytes, file_format: str, plan: SoundPlan, criteria: dict[str, bool], placeholder: bool
) -> AssetQC:
    """Run G1, then G2 + G1 again, and decide PASS / FIX / REGENERATE / REVIEW.

    ``criteria`` maps the active criterion_id to whether it is required.
    """
    qc = AssetQC(plan.asset_id, plan.category, plan.required)
    try:
        samples, rate = decode(audio, file_format)
        if not samples.size:
            raise SoundDecodeError("빈 오디오")
    except SoundDecodeError as error:
        qc.failed, qc.error = ["sound-file-valid"], str(error)
        _decide(qc, criteria, placeholder)
        return qc

    # Two G2 passes: one repair can expose another (DC removal reveals padded silence).
    for _ in range(2):
        failed = [c for c in failed_checks(measure(samples, rate), plan) if c in criteria]
        if not failed or failed == ["sound-file-valid"]:
            break
        samples, fixes = apply_fixes(samples, rate, failed, plan.loop)
        if not fixes:
            break
        qc.applied_fixes += fixes
    if qc.applied_fixes:
        qc.processed_wav = encode_wav(samples, rate)
    qc.metrics = measure(samples, rate)
    qc.failed = failed_checks(qc.metrics, plan) + (["sound-not-placeholder"] if placeholder else [])
    _decide(qc, criteria, placeholder)
    return qc


def mark_duplicates(
    results: list[AssetQC], audio_by_id: dict[str, bytes], criteria: dict[str, bool]
) -> None:
    """G4 (partial): identical files for different assets — the later one must be regenerated."""
    if "sound-set-duplicate" not in criteria:
        return
    seen: dict[str, str] = {}
    for qc in results:
        digest = hashlib.sha256(audio_by_id[qc.asset_id]).hexdigest()
        if digest in seen:
            qc.failed.append("sound-set-duplicate")
            qc.error = f"{seen[digest]}와 같은 파일"
            if criteria["sound-set-duplicate"]:
                qc.decision = "REGENERATE"
            elif qc.decision in ("PASS", "FIX"):
                qc.decision = "REVIEW"
        else:
            seen[digest] = qc.asset_id
