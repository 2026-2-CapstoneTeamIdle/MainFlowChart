"""Run repeatable headless game-generation trials and record validation rates."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import signal
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from tools.unity_player_build import run_player_build

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PRICING = ROOT / "tools" / "experiment_pricing_20261122.json"
FIELDS = (
    "trial_id",
    "request",
    "request_sha256",
    "mode",
    "builder",
    "model",
    "reasoning_effort",
    "fast_mode",
    "project_id",
    "compile_passed",
    "play_mode_passed",
    "final_validation_passed",
    "quality_review_passed",
    "approved_feature_count",
    "checklist_generated_feature_count",
    "unity_test_generated_feature_count",
    "dynamic_test_planned_item_count",
    "dynamic_test_executed_item_count",
    "dynamic_test_verdict",
    "elapsed_seconds",
    "player_build_status",
    "player_build_seconds",
    "player_build_exit_code",
    "player_build_log_file",
    "player_build_output",
    "player_build_error",
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
    "token_usage_status",
    "codex_event_files",
    "image_api_requests",
    "image_input_tokens",
    "image_input_text_tokens",
    "image_input_image_tokens",
    "image_output_tokens",
    "image_output_text_tokens",
    "image_output_image_tokens",
    "image_total_tokens",
    "image_usage_status",
    "image_breakdown_status",
    "image_estimated_usd",
    "image_cost_status",
    "elevenlabs_api_requests",
    "elevenlabs_sfx_character_cost",
    "elevenlabs_music_character_cost",
    "elevenlabs_character_cost",
    "elevenlabs_sfx_generated_count",
    "elevenlabs_music_generated_count",
    "elevenlabs_sfx_requested_seconds",
    "elevenlabs_music_requested_seconds",
    "elevenlabs_usage_status",
    "elevenlabs_estimated_usd",
    "elevenlabs_cost_status",
    "exit_code",
    "timed_out",
    "failure_codes",
    "result_file",
    "log_file",
)
TOKEN_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--request-file", type=Path, action="append", required=True)
    result.add_argument("--repeats", type=int, default=1)
    result.add_argument("--mode", choices=("game-test", "full"), default="game-test")
    result.add_argument(
        "--builder", choices=("codex-cli", "claude-code", "pipeline"), default="codex-cli"
    )
    result.add_argument(
        "--model", help="CLI agent model; defaults to the selected builder's default"
    )
    result.add_argument(
        "--reasoning-effort", choices=("low", "medium", "high", "xhigh", "max"), default="medium"
    )
    result.add_argument("--fast-mode", action="store_true", help="Codex fast service tier")
    result.add_argument("--output-dir", type=Path, required=True)
    result.add_argument(
        "--pricing-file", type=Path, default=DEFAULT_PRICING, help="Dated USD rate snapshot"
    )
    result.add_argument("--timeout-minutes", type=float, default=120)
    result.add_argument("--build-timeout-minutes", type=float, default=45)
    result.add_argument(
        "--unity-editor", help="Unity.exe path; defaults to UNITY_EDITOR_PATH or project version"
    )
    result.add_argument(
        "--resume", action="store_true", help="Skip completed trials in this output directory"
    )
    result.add_argument(
        "--dry-run", action="store_true", help="Print planned trials without launching them"
    )
    return result


def extract_metrics(payload: dict[str, Any], mode: str) -> dict[str, Any]:
    game = payload.get("game_validation") or {}
    checks = {
        item.get("criterion_id"): item.get("passed") is True
        for item in game.get("checks", [])
        if isinstance(item, dict)
    }
    issues = [
        issue.get("code")
        for section in (game, payload.get("final_validation") or {})
        for issue in section.get("issues", [])
        if isinstance(issue, dict) and isinstance(issue.get("code"), str)
    ]
    return {
        "project_id": payload.get("project_id") or "",
        "compile_passed": checks.get("unity.batchmode") is True,
        "play_mode_passed": checks.get("unity.runtime_smoke") is True,
        "final_validation_passed": (
            (payload.get("final_validation") or {}).get("status") == "passed"
            if mode == "full"
            else None
        ),
        "quality_review_passed": (
            (payload.get("game_validator_ai") or {}).get("status") == "passed"
            if mode == "full"
            else None
        ),
        "failure_codes": ";".join(dict.fromkeys(issues)),
    }


def summarize(rows: list[dict[str, str]], mode: str) -> dict[str, Any]:
    def rates(subset: list[dict[str, str]]) -> dict[str, Any]:
        count = len(subset)
        result: dict[str, Any] = {"runs": count}
        built = sum(row.get("player_build_status") == "passed" for row in subset)
        attempted = sum(
            row.get("player_build_status") in {"passed", "failed", "timed_out"} for row in subset
        )
        result["build_success"] = {
            "passed": built,
            "rate": built / count if count else None,
            "attempted": attempted,
            "attempted_rate": built / attempted if attempted else None,
        }
        result["build_statuses"] = dict(
            sorted(
                (status, sum(row.get("player_build_status") == status for row in subset))
                for status in {row.get("player_build_status", "not_attempted") for row in subset}
            )
        )
        result["dynamic_test_stages"] = dict(
            sorted(
                (stage, sum(row.get("dynamic_test_verdict") == stage for row in subset))
                for stage in {row.get("dynamic_test_verdict", "not_reached") for row in subset}
            )
        )
        for field in (
            "compile_passed",
            "play_mode_passed",
            "final_validation_passed",
            "quality_review_passed",
        ):
            if mode == "game-test" and field in {
                "final_validation_passed",
                "quality_review_passed",
            }:
                continue
            passed = sum(row.get(field) == "True" for row in subset)
            result[field] = {"passed": passed, "rate": passed / count if count else None}
        times = [float(row["elapsed_seconds"]) for row in subset if row.get("elapsed_seconds")]
        result["elapsed_seconds"] = {
            "measured": len(times),
            "mean": statistics.mean(times) if times else None,
            "median": statistics.median(times) if times else None,
        }
        build_times = [
            float(row["player_build_seconds"]) for row in subset if row.get("player_build_seconds")
        ]
        result["player_build_seconds"] = {
            "measured": len(build_times),
            "mean": statistics.mean(build_times) if build_times else None,
            "median": statistics.median(build_times) if build_times else None,
        }
        token_values = [
            int(row["total_tokens"])
            for row in subset
            if row.get("token_usage_status") == "complete" and row.get("total_tokens")
        ]
        result["total_tokens"] = {
            "measured": len(token_values),
            "mean": statistics.mean(token_values) if token_values else None,
            "median": statistics.median(token_values) if token_values else None,
        }
        for value_field, status_field in (
            ("image_total_tokens", "image_usage_status"),
            ("elevenlabs_character_cost", "elevenlabs_usage_status"),
            ("image_estimated_usd", "image_cost_status"),
            ("elevenlabs_estimated_usd", "elevenlabs_cost_status"),
        ):
            values = [
                Decimal(row[value_field])
                for row in subset
                if row.get(status_field) in {"complete", "estimated"} and row.get(value_field)
            ]
            result[value_field] = {
                "measured": len(values),
                "mean": float(statistics.mean(values)) if values else None,
                "median": float(statistics.median(values)) if values else None,
            }
        return result

    by_request: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_request[row["request"]].append(row)
    return {
        "build_success_definition": "Unity StandaloneWindows64 BuildPipeline player build produced an executable; attempted_rate excludes missing projects and infrastructure errors",
        "overall": rates(rows),
        "by_request": {request: rates(group) for request, group in by_request.items()},
    }


def collect_codex_token_usage(project_root: Path | None) -> dict[str, Any]:
    """Sum final CLI usage records without counting cached or reasoning subsets twice."""

    empty = {field: "" for field in TOKEN_FIELDS}
    if project_root is None or not project_root.is_dir():
        return {
            **empty,
            "total_tokens": "",
            "token_usage_status": "missing",
            "codex_event_files": 0,
        }
    event_root = project_root / "validation"
    event_files = sorted(event_root.rglob("events.jsonl")) if event_root.is_dir() else []
    if not event_files:
        return {
            **empty,
            "total_tokens": "",
            "token_usage_status": "missing",
            "codex_event_files": 0,
        }

    totals = dict.fromkeys(TOKEN_FIELDS, 0)
    incomplete = False
    completed = 0
    for event_file in event_files:
        file_completed = False
        try:
            lines = event_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            incomplete = True
            continue
        for line in lines:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                incomplete = True
                continue
            if not isinstance(event, dict):
                incomplete = True
                continue
            if event.get("type") == "turn.failed":
                incomplete = True
            if event.get("type") != "turn.completed":
                continue
            usage = event.get("usage")
            if not isinstance(usage, dict) or not all(
                isinstance(usage.get(field), int) and usage[field] >= 0
                for field in ("input_tokens", "output_tokens")
            ):
                incomplete = True
                continue
            for field in TOKEN_FIELDS:
                value = usage.get(field, 0)
                if isinstance(value, int) and value >= 0:
                    totals[field] += value
                else:
                    incomplete = True
            file_completed = True
            completed += 1
        if not file_completed:
            incomplete = True
    if not completed:
        return {
            **empty,
            "total_tokens": "",
            "token_usage_status": "missing",
            "codex_event_files": len(event_files),
        }
    return {
        **totals,
        "total_tokens": totals["input_tokens"] + totals["output_tokens"],
        "token_usage_status": "partial" if incomplete else "complete",
        "codex_event_files": len(event_files),
    }


def collect_provider_usage(
    project_root: Path | None,
    *,
    assets_skipped: bool = False,
    pricing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Sum observed per-request API usage; missing provider metadata stays unknown."""

    result: dict[str, Any] = {
        "image_api_requests": 0,
        "image_input_tokens": "",
        "image_input_text_tokens": "",
        "image_input_image_tokens": "",
        "image_output_tokens": "",
        "image_output_text_tokens": "",
        "image_output_image_tokens": "",
        "image_total_tokens": "",
        "image_usage_status": "missing",
        "image_breakdown_status": "missing",
        "image_estimated_usd": "",
        "image_cost_status": "missing",
        "elevenlabs_api_requests": 0,
        "elevenlabs_sfx_character_cost": "",
        "elevenlabs_music_character_cost": "",
        "elevenlabs_character_cost": "",
        "elevenlabs_sfx_generated_count": 0,
        "elevenlabs_music_generated_count": 0,
        "elevenlabs_sfx_requested_seconds": "",
        "elevenlabs_music_requested_seconds": "",
        "elevenlabs_usage_status": "missing",
        "elevenlabs_estimated_usd": "",
        "elevenlabs_cost_status": "missing",
    }
    if assets_skipped:
        result["image_usage_status"] = "not_used"
        result["image_breakdown_status"] = "not_used"
        result["image_cost_status"] = "not_used"
        result["elevenlabs_usage_status"] = "not_used"
        result["elevenlabs_cost_status"] = "not_used"
        for field in (
            "image_input_tokens",
            "image_input_text_tokens",
            "image_input_image_tokens",
            "image_output_tokens",
            "image_output_text_tokens",
            "image_output_image_tokens",
            "image_total_tokens",
            "elevenlabs_sfx_character_cost",
            "elevenlabs_music_character_cost",
            "elevenlabs_character_cost",
            "image_estimated_usd",
            "elevenlabs_estimated_usd",
        ):
            result[field] = 0
        return result
    if project_root is None or not project_root.is_dir():
        return result
    root = project_root / "validation" / "api_usage"
    image_fields = (
        "input_tokens",
        "input_text_tokens",
        "input_image_tokens",
        "output_tokens",
        "output_text_tokens",
        "output_image_tokens",
        "total_tokens",
    )
    image_events, image_invalid = _read_usage_events(root / "openai_image.jsonl")
    image_requests = [event for event in image_events if "event" not in event]
    if not image_requests and not image_invalid:
        if image_events:
            result["image_usage_status"] = "not_used"
            result["image_breakdown_status"] = "not_used"
            result["image_cost_status"] = "not_used"
            for field in image_fields:
                result[f"image_{field}"] = 0
            result["image_estimated_usd"] = 0
    else:
        image_totals = dict.fromkeys(image_fields, 0)
        present = dict.fromkeys(image_fields, 0)
        incomplete = image_invalid
        breakdown_incomplete = image_invalid
        image_cost = Decimal(0)
        image_cost_incomplete = image_invalid
        image_cost_observed = 0
        for event in image_requests:
            result["image_api_requests"] += 1
            usage = event.get("usage")
            if event.get("status") != "success" or not isinstance(usage, dict):
                incomplete = True
                breakdown_incomplete = True
                image_cost_incomplete = True
                continue
            for field in image_fields:
                value = usage.get(field)
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    image_totals[field] += value
                    present[field] += 1
                else:
                    if field in {"input_tokens", "output_tokens", "total_tokens"}:
                        incomplete = True
                    breakdown_incomplete = True
            rates = (pricing or {}).get("openai_image_standard_per_million_tokens", {})
            model = str(event.get("model") or "")
            model = re.sub(r"-20\d{2}-\d{2}-\d{2}$", "", model)
            model_rates = rates.get(model) if isinstance(rates, dict) else None
            try:
                if not isinstance(model_rates, dict):
                    raise InvalidOperation
                text_input = Decimal(usage["input_text_tokens"])
                image_input = Decimal(usage["input_image_tokens"])
                image_output = Decimal(usage["output_image_tokens"])
                if min(text_input, image_input, image_output) < 0:
                    raise InvalidOperation
                if usage.get("output_text_tokens") not in (None, 0):
                    raise InvalidOperation
                image_cost += (
                    text_input * Decimal(str(model_rates["input_text"]))
                    + image_input * Decimal(str(model_rates["input_image"]))
                    + image_output * Decimal(str(model_rates["output_image"]))
                ) / Decimal(1_000_000)
                image_cost_observed += 1
            except (InvalidOperation, KeyError, TypeError, ValueError):
                image_cost_incomplete = True
        for field in image_fields:
            if present[field]:
                result[f"image_{field}"] = image_totals[field]
        result["image_usage_status"] = "partial" if incomplete else "complete"
        result["image_breakdown_status"] = (
            "partial" if incomplete or breakdown_incomplete else "complete"
        )
        if image_cost_observed:
            result["image_estimated_usd"] = str(image_cost)
        result["image_cost_status"] = "partial_estimate" if image_cost_incomplete else "estimated"

    sound_events, sound_invalid = _read_usage_events(root / "elevenlabs.jsonl")
    sound_requests = [event for event in sound_events if "event" not in event]
    if not sound_requests and not sound_invalid:
        if sound_events:
            result["elevenlabs_usage_status"] = "not_used"
            result["elevenlabs_cost_status"] = "not_used"
            for field in (
                "elevenlabs_sfx_character_cost",
                "elevenlabs_music_character_cost",
                "elevenlabs_character_cost",
            ):
                result[field] = 0
            result["elevenlabs_estimated_usd"] = 0
    else:
        totals = {"sfx": Decimal(0), "music": Decimal(0)}
        durations = {"sfx": Decimal(0), "music": Decimal(0)}
        observed = {"sfx": 0, "music": 0}
        incomplete = sound_invalid
        sound_cost = Decimal(0)
        sound_cost_incomplete = sound_invalid
        sound_cost_observed = 0
        for event in sound_requests:
            result["elevenlabs_api_requests"] += 1
            kind = "music" if event.get("endpoint") == "/v1/music" else "sfx"
            if event.get("status") == "success":
                result[f"elevenlabs_{kind}_generated_count"] += 1
                try:
                    duration = Decimal(str(event.get("requested_duration_seconds")))
                    if duration.is_finite() and duration >= 0:
                        durations[kind] += duration
                        rates = (pricing or {}).get("elevenlabs_api_usd_per_minute", {})
                        if not isinstance(rates, dict) or kind not in rates:
                            raise InvalidOperation
                        sound_cost += duration * Decimal(str(rates[kind])) / Decimal(60)
                        sound_cost_observed += 1
                    else:
                        sound_cost_incomplete = True
                except (InvalidOperation, ValueError):
                    sound_cost_incomplete = True
            else:
                sound_cost_incomplete = True
            raw_cost = event.get("character_cost")
            try:
                cost = Decimal(str(raw_cost))
                if not cost.is_finite() or cost < 0:
                    raise InvalidOperation
            except (InvalidOperation, ValueError):
                incomplete = True
                continue
            totals[kind] += cost
            observed[kind] += 1
        if observed["sfx"]:
            result["elevenlabs_sfx_character_cost"] = str(totals["sfx"])
        if observed["music"]:
            result["elevenlabs_music_character_cost"] = str(totals["music"])
        if any(observed.values()):
            result["elevenlabs_character_cost"] = str(sum(totals.values()))
        for kind in ("sfx", "music"):
            if result[f"elevenlabs_{kind}_generated_count"]:
                result[f"elevenlabs_{kind}_requested_seconds"] = str(durations[kind])
        result["elevenlabs_usage_status"] = "partial" if incomplete else "complete"
        if sound_cost_observed:
            result["elevenlabs_estimated_usd"] = str(sound_cost)
        result["elevenlabs_cost_status"] = (
            "partial_estimate" if sound_cost_incomplete else "estimated"
        )
    return result


def _read_usage_events(path: Path) -> tuple[list[dict[str, Any]], bool]:
    if not path.is_file():
        return [], False
    events: list[dict[str, Any]] = []
    invalid = False
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return [], True
    if not lines:
        return [], True
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            invalid = True
            continue
        if isinstance(event, dict):
            events.append(event)
        else:
            invalid = True
    return events, invalid


def collect_checklist_progress(project_root: Path | None) -> dict[str, Any]:
    """Record each observable stage; an absent NUnit result is never a pass."""
    progress = {
        "approved_feature_count": 0,
        "checklist_generated_feature_count": 0,
        "unity_test_generated_feature_count": 0,
        "dynamic_test_planned_item_count": 0,
        "dynamic_test_executed_item_count": 0,
        "dynamic_test_verdict": "not_reached",
    }
    if project_root is None:
        return progress

    def read_json(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    analysis = read_json(project_root / "data" / "logic_analysis.json")
    approved = analysis.get("features")
    if isinstance(approved, list):
        progress["approved_feature_count"] = len(approved)
    generated = project_root / "validation" / "feature_checklists" / "generated"
    checklist = read_json(generated / "checklist.json")
    feature_checklists = checklist.get("feature_checklists")
    if not isinstance(feature_checklists, list):
        return progress
    valid_features = [
        item
        for item in feature_checklists
        if isinstance(item, dict) and isinstance(item.get("criteria"), list)
    ]
    progress["checklist_generated_feature_count"] = len(valid_features)
    planned_ids = {
        criterion["criterion_id"]
        for feature in valid_features
        for criterion in feature["criteria"]
        if isinstance(criterion, dict) and isinstance(criterion.get("criterion_id"), str)
    }
    progress["dynamic_test_planned_item_count"] = len(planned_ids)
    progress["dynamic_test_verdict"] = "checklist_created"
    for feature in valid_features:
        feature_id = feature.get("feature_id")
        criteria = feature.get("criteria")
        if not isinstance(feature_id, str) or not isinstance(criteria, list) or not criteria:
            continue
        first_id = criteria[0].get("criterion_id") if isinstance(criteria[0], dict) else None
        if not isinstance(first_id, str) or "_" not in first_id:
            continue
        filename = f"GeneratedFeatureChecklist_{first_id.rsplit('_', 1)[0]}.cs"
        safe_id = re.sub(r"[^A-Za-z0-9_-]+", "_", feature_id)
        source = generated / safe_id / filename
        if source.is_file():
            progress["unity_test_generated_feature_count"] += 1
    if progress["unity_test_generated_feature_count"]:
        progress["dynamic_test_verdict"] = "test_code_created"
    checked = read_json(
        project_root / "validation" / "feature_checklists" / "checked" / "results.json"
    )
    attempts = checked.get("attempts")
    if not isinstance(attempts, list):
        return progress
    executed: dict[str, str] = {}
    for attempt in attempts:
        if not isinstance(attempt, dict):
            continue
        for item in attempt.get("results", []):
            if not isinstance(item, dict):
                continue
            criterion_id = item.get("feature_id")
            status = item.get("status")
            kind = item.get("failure_kind", "game")
            if criterion_id in planned_ids and status in {"passed", "failed"} and kind == "game":
                executed[criterion_id] = status
    progress["dynamic_test_executed_item_count"] = len(executed)
    if executed:
        complete = len(executed) == len(planned_ids)
        passed = all(status == "passed" for status in executed.values())
        progress["dynamic_test_verdict"] = (
            "executed_complete_passed"
            if complete and passed
            else "executed_complete_failed"
            if complete
            else "executed_partial"
        )
    return progress


def initial_source_preflight_failed(project_root: Path | None) -> bool:
    """Stop a batch when a fresh project cannot compile before agent implementation."""

    if project_root is None:
        return False
    failure_file = project_root / "validation" / "game_generation_failure.json"
    try:
        failure = json.loads(failure_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return "UNITY_INITIAL_SOURCE_INVALID" in str(failure.get("message", ""))


def _stop_process_tree(process: subprocess.Popen[Any]) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        os.killpg(process.pid, signal.SIGKILL)
    process.wait()


def _write_summary(output_dir: Path, rows: list[dict[str, str]], mode: str) -> None:
    (output_dir / "summary.json").write_text(
        json.dumps(summarize(rows, mode), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parser().parse_args()
    if args.repeats < 1 or args.timeout_minutes <= 0 or args.build_timeout_minutes <= 0:
        parser().error("--repeats, --timeout-minutes and --build-timeout-minutes must be positive")
    if args.fast_mode and args.builder != "codex-cli":
        parser().error("--fast-mode is supported only by codex-cli")
    try:
        pricing_bytes = args.pricing_file.read_bytes()
        pricing = json.loads(pricing_bytes)
    except (OSError, ValueError) as error:
        parser().error(f"cannot read pricing file: {error}")
    if not isinstance(pricing, dict) or pricing.get("currency") != "USD":
        parser().error("pricing file must be a USD rate snapshot")

    requests = [path.resolve() for path in args.request_file]
    for path in requests:
        if not path.is_file():
            parser().error(f"request file not found: {path}")
        request = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(request, dict) or not all(
            request.get(key)
            for key in ("image_style", "mood_style", "genre", "viewpoint", "condition")
        ):
            parser().error(f"invalid request file: {path}")

    model = args.model or {"codex-cli": "gpt-5.6-luna", "claude-code": "sonnet"}.get(
        args.builder, ""
    )
    config = {
        "mode": args.mode,
        "builder": args.builder,
        "model": model,
        "reasoning_effort": args.reasoning_effort,
        "fast_mode": args.fast_mode,
        "repeats": args.repeats,
        "timeout_minutes": args.timeout_minutes,
        "build_timeout_minutes": args.build_timeout_minutes,
        "unity_editor": args.unity_editor or "",
        "pricing_sha256": hashlib.sha256(pricing_bytes).hexdigest(),
        "requests": [
            {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in requests
        ],
    }
    output_dir = args.output_dir.resolve()
    trials = [
        (
            path,
            repeat,
            f"{re.sub(r'[^A-Za-z0-9_-]', '_', path.stem)}-{hashlib.sha256(path.read_bytes()).hexdigest()[:8]}-{repeat:02d}",
        )
        for path in requests
        for repeat in range(1, args.repeats + 1)
    ]
    if args.dry_run:
        for path, _, trial_id in trials:
            print(f"{trial_id}: {path}")
        return 0

    config_file = output_dir / "config.json"
    if config_file.exists():
        if not args.resume or json.loads(config_file.read_text(encoding="utf-8")) != config:
            parser().error(
                "output directory already contains a different experiment; use --resume or a new directory"
            )
    elif output_dir.is_dir() and any(output_dir.iterdir()):
        parser().error("output directory is not empty")
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "pricing_snapshot.json").write_bytes(pricing_bytes)
    config_file.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "projects").mkdir(exist_ok=True)
    (output_dir / "runs").mkdir(exist_ok=True)
    csv_file = output_dir / "results.csv"
    rows: list[dict[str, str]] = []
    if csv_file.exists():
        with csv_file.open("r", encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            if tuple(reader.fieldnames or ()) != FIELDS:
                parser().error(
                    "existing results.csv uses a different schema; use a new output directory"
                )
            rows = list(reader)
    completed = {row["trial_id"] for row in rows}

    for path, _, trial_id in trials:
        if trial_id in completed:
            continue
        result_file = output_dir / "runs" / f"{trial_id}.json"
        log_file = output_dir / "runs" / f"{trial_id}.log"
        result_file.unlink(missing_ok=True)
        projects_root = output_dir / "projects"
        existing_projects = {item.name for item in projects_root.iterdir() if item.is_dir()}
        command = [
            sys.executable,
            "-m",
            "mainflow.run_flow",
            "--request-file",
            str(path),
            "--game-builder",
            args.builder,
            "--workspace",
            str(projects_root),
            "--result-file",
            str(result_file),
            "--quiet-result",
            "--game-test" if args.mode == "game-test" else "--skip-visual-validation",
        ]
        environment = os.environ.copy()
        environment["MAINFLOW_OPEN_UNITY_EDITOR"] = "0"
        if args.builder == "codex-cli":
            environment["MAINFLOW_CODEX_MODEL"] = model
            environment["MAINFLOW_CODEX_REASONING_EFFORT"] = args.reasoning_effort
            if args.fast_mode:
                environment["MAINFLOW_CODEX_SERVICE_TIER"] = "fast"
            else:
                environment.pop("MAINFLOW_CODEX_SERVICE_TIER", None)
        elif args.builder == "claude-code":
            environment["MAINFLOW_CLAUDE_MODEL"] = model
            environment["MAINFLOW_CLAUDE_REASONING_EFFORT"] = args.reasoning_effort
        print(f"Starting {trial_id} ({len(rows) + 1}/{len(trials)})", flush=True)
        started = time.monotonic()
        timed_out = False
        with log_file.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
                start_new_session=os.name != "nt",
            )
            try:
                exit_code = process.wait(timeout=args.timeout_minutes * 60)
            except subprocess.TimeoutExpired:
                timed_out = True
                _stop_process_tree(process)
                exit_code = process.returncode or -1
            except KeyboardInterrupt:
                _stop_process_tree(process)
                raise
        elapsed = round(time.monotonic() - started, 1)
        payload: dict[str, Any] = {}
        try:
            payload = json.loads(result_file.read_text(encoding="utf-8"))
            metrics = extract_metrics(payload, args.mode)
        except (OSError, ValueError, TypeError):
            metrics = extract_metrics({}, args.mode)
            metrics["failure_codes"] = "RESULT_MISSING_OR_INVALID"
        if timed_out:
            metrics["failure_codes"] = ";".join(filter(None, (metrics["failure_codes"], "TIMEOUT")))
        if exit_code != 0 and not metrics["failure_codes"]:
            metrics["failure_codes"] = f"PROCESS_EXIT_{exit_code}"
        project_root = projects_root / str(metrics["project_id"]) if metrics["project_id"] else None
        if project_root is None or not project_root.is_dir():
            new_projects = [
                item
                for item in projects_root.iterdir()
                if item.is_dir() and item.name not in existing_projects
            ]
            if len(new_projects) == 1:
                project_root = new_projects[0]
                metrics["project_id"] = project_root.name
        token_metrics = (
            collect_codex_token_usage(project_root)
            if args.builder == "codex-cli"
            else {
                **{field: "" for field in TOKEN_FIELDS},
                "total_tokens": "",
                "token_usage_status": "unsupported",
                "codex_event_files": 0,
            }
        )
        provider_metrics = collect_provider_usage(
            project_root, assets_skipped=args.mode == "game-test", pricing=pricing
        )
        checklist_progress = collect_checklist_progress(project_root)
        build_metrics = run_player_build(
            project_root / "game" / "unity_project" if project_root is not None else None,
            output_dir / "runs" / f"{trial_id}-build",
            editor_path=args.unity_editor,
            timeout_minutes=args.build_timeout_minutes,
        )
        row = {
            "trial_id": trial_id,
            "request": str(path),
            "request_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "mode": args.mode,
            "builder": args.builder,
            "model": model,
            "reasoning_effort": args.reasoning_effort,
            "fast_mode": str(args.fast_mode),
            **{key: str(value) if value is not None else "" for key, value in metrics.items()},
            "elapsed_seconds": str(elapsed),
            **{key: str(value) for key, value in build_metrics.items()},
            **{key: str(value) for key, value in token_metrics.items()},
            **{key: str(value) for key, value in provider_metrics.items()},
            **{key: str(value) for key, value in checklist_progress.items()},
            "exit_code": str(exit_code),
            "timed_out": str(timed_out),
            "result_file": str(result_file),
            "log_file": str(log_file),
        }
        with csv_file.open("a", encoding="utf-8", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=FIELDS)
            if not rows:
                writer.writeheader()
            writer.writerow(row)
            target.flush()
            os.fsync(target.fileno())
        rows.append(row)
        _write_summary(output_dir, rows, args.mode)
        print(
            f"Finished {trial_id}: compile={row['compile_passed']} "
            f"play={row['play_mode_passed']} build={row['player_build_status']} "
            f"elapsed={elapsed}s "
            f"tokens={row['total_tokens'] or row['token_usage_status']}",
            flush=True,
        )
        if initial_source_preflight_failed(project_root):
            print(
                "Stopping experiment: initial Unity source failed compilation before the agent "
                "started. Repair the shared template or generator before resuming.",
                flush=True,
            )
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
