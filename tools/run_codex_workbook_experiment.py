"""Measure one-shot Codex Unity generation from exact workbook inputs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import signal
import statistics
import subprocess
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from tools.export_experiment_requests import extract_requests
from tools.unity_player_build import run_player_build

FIELDS = (
    "trial_id",
    "prompt_id",
    "repeat",
    "genre",
    "viewpoint",
    "image_style",
    "mood_style",
    "condition",
    "request_sha256",
    "model",
    "reasoning_effort",
    "fast_mode",
    "unity_editor",
    "unity_project",
    "setup_status",
    "setup_seconds",
    "codex_status",
    "generation_seconds",
    "build_status",
    "build_seconds",
    "total_seconds",
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
    "token_usage_status",
    "codex_exit_code",
    "build_exit_code",
    "build_error",
    "execution_error",
    "prompt_file",
    "codex_events_file",
    "codex_stderr_file",
    "unity_create_log_file",
    "unity_build_log_file",
    "unity_build_output",
)


def create_prompt(request: dict[str, str]) -> str:
    """Keep the five workbook values verbatim inside one Codex instruction."""
    return (
        "아래 입력으로 이 빈 Unity 프로젝트에 플레이 가능한 게임을 만들어줘.\n\n"
        f"장르: {request['genre']}\n"
        f"시점: {request['viewpoint']}\n"
        f"이미지 스타일: {request['image_style']}\n"
        f"분위기: {request['mood_style']}\n"
        f"Condition:\n{request['condition']}\n"
    )


def resolve_unity_editor(configured: Path | None) -> Path | None:
    if configured is not None:
        return configured.expanduser().resolve() if configured.is_file() else None
    env_path = os.environ.get("UNITY_EDITOR_PATH", "").strip()
    if env_path:
        editor = Path(env_path).expanduser().resolve()
        return editor if editor.is_file() else None
    editors = list(Path("C:/Program Files/Unity/Hub/Editor").glob("*/Editor/Unity.exe"))
    return max(editors, key=lambda item: item.parent.parent.name).resolve() if editors else None


def resolve_codex(configured: Path | None) -> Path | None:
    if configured is not None:
        return configured.expanduser().resolve() if configured.is_file() else None
    found = shutil.which("codex.cmd") or shutil.which("codex.exe") or shutil.which("codex")
    return Path(found).resolve() if found else None


def _stop_tree(process: subprocess.Popen[Any]) -> None:
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


def run_command(
    command: list[str],
    *,
    cwd: Path,
    stdout_file: Path,
    stderr_file: Path | None = None,
    prompt: str | None = None,
    timeout_minutes: float,
    environment: dict[str, str] | None = None,
) -> tuple[int, float, bool]:
    started = time.monotonic()
    stdout_file.parent.mkdir(parents=True, exist_ok=True)
    with (
        stdout_file.open("w", encoding="utf-8") as output,
        stderr_file.open("w", encoding="utf-8") if stderr_file else output as errors,
    ):
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=environment,
            stdin=subprocess.PIPE if prompt is not None else subprocess.DEVNULL,
            stdout=output,
            stderr=errors,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
        )
        timed_out = False
        try:
            process.communicate(
                input=prompt.encode("utf-8") if prompt is not None else None,
                timeout=timeout_minutes * 60,
            )
        except subprocess.TimeoutExpired:
            timed_out = True
            _stop_tree(process)
        except KeyboardInterrupt:
            _stop_tree(process)
            raise
    return process.returncode or 0, round(time.monotonic() - started, 1), timed_out


def collect_codex_usage(events_file: Path) -> dict[str, Any]:
    totals = {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
    }
    completed = 0
    invalid = False
    try:
        lines = events_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            invalid = True
            continue
        if not isinstance(event, dict):
            invalid = True
            continue
        if event.get("type") == "turn.failed":
            invalid = True
        if event.get("type") != "turn.completed":
            continue
        usage = event.get("usage")
        if not isinstance(usage, dict) or any(
            not isinstance(usage.get(field), int) or usage[field] < 0
            for field in ("input_tokens", "output_tokens")
        ):
            invalid = True
            continue
        for field in totals:
            value = usage.get(field, 0)
            if isinstance(value, int) and value >= 0:
                totals[field] += value
            else:
                invalid = True
        completed += 1
    if not completed:
        return {
            **{field: "" for field in totals},
            "total_tokens": "",
            "token_usage_status": "missing",
        }
    return {
        **totals,
        "total_tokens": totals["input_tokens"] + totals["output_tokens"],
        "token_usage_status": "partial" if invalid else "complete",
    }


def summarize(rows: list[dict[str, str]]) -> dict[str, Any]:
    def metrics(group: list[dict[str, str]]) -> dict[str, Any]:
        count = len(group)
        passed = sum(
            row.get("codex_status") == "completed" and row.get("build_status") == "passed"
            for row in group
        )
        attempted = sum(
            row.get("build_status") in {"passed", "failed", "timed_out"} for row in group
        )

        def numbers(field: str, *, status_field: str | None = None) -> dict[str, Any]:
            values = [
                float(row[field])
                for row in group
                if row.get(field) and (status_field is None or row.get(status_field) == "complete")
            ]
            return {
                "measured": len(values),
                "mean": statistics.mean(values) if values else None,
                "median": statistics.median(values) if values else None,
            }

        return {
            "runs": count,
            "codex_completed": sum(row.get("codex_status") == "completed" for row in group),
            "build_success": {
                "passed": passed,
                "rate": passed / count if count else None,
                "attempted": attempted,
                "attempted_rate": passed / attempted if attempted else None,
            },
            "generation_seconds": numbers("generation_seconds"),
            "setup_seconds": numbers("setup_seconds"),
            "build_seconds": numbers("build_seconds"),
            "input_tokens": numbers("input_tokens", status_field="token_usage_status"),
            "cached_input_tokens": numbers(
                "cached_input_tokens", status_field="token_usage_status"
            ),
            "output_tokens": numbers("output_tokens", status_field="token_usage_status"),
            "reasoning_output_tokens": numbers(
                "reasoning_output_tokens", status_field="token_usage_status"
            ),
            "total_tokens": numbers("total_tokens", status_field="token_usage_status"),
        }

    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        groups[row["prompt_id"]].append(row)
    return {
        "definition": "One Codex exec request per trial in a fresh Unity project; success requires Codex exit 0 and a built Windows executable.",
        "overall": metrics(rows),
        "by_prompt": {key: metrics(value) for key, value in groups.items()},
    }


def write_reports(output_dir: Path, rows: list[dict[str, str]]) -> None:
    summary = summarize(rows)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    fields = (
        "prompt_id",
        "runs",
        "codex_completed",
        "build_passed",
        "build_success_rate",
        "build_attempted",
        "attempted_build_success_rate",
        "generation_seconds_mean",
        "generation_seconds_median",
        "setup_seconds_mean",
        "build_seconds_mean",
        "input_tokens_mean",
        "cached_input_tokens_mean",
        "output_tokens_mean",
        "reasoning_output_tokens_mean",
        "total_tokens_mean",
        "token_runs_measured",
    )

    def flatten(prompt_id: str, data: dict[str, Any]) -> dict[str, Any]:
        build = data["build_success"]
        return {
            "prompt_id": prompt_id,
            "runs": data["runs"],
            "codex_completed": data["codex_completed"],
            "build_passed": build["passed"],
            "build_success_rate": build["rate"],
            "build_attempted": build["attempted"],
            "attempted_build_success_rate": build["attempted_rate"],
            "generation_seconds_mean": data["generation_seconds"]["mean"],
            "generation_seconds_median": data["generation_seconds"]["median"],
            "setup_seconds_mean": data["setup_seconds"]["mean"],
            "build_seconds_mean": data["build_seconds"]["mean"],
            "input_tokens_mean": data["input_tokens"]["mean"],
            "cached_input_tokens_mean": data["cached_input_tokens"]["mean"],
            "output_tokens_mean": data["output_tokens"]["mean"],
            "reasoning_output_tokens_mean": data["reasoning_output_tokens"]["mean"],
            "total_tokens_mean": data["total_tokens"]["mean"],
            "token_runs_measured": data["total_tokens"]["measured"],
        }

    for filename, data in (
        ("overall.csv", [flatten("ALL", summary["overall"])]),
        (
            "by_prompt.csv",
            [flatten(prompt_id, value) for prompt_id, value in summary["by_prompt"].items()],
        ),
    ):
        with (output_dir / filename).open("w", encoding="utf-8-sig", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=fields)
            writer.writeheader()
            writer.writerows(data)


def _codex_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith("CODEX_APP_") or name in {
            "CODEX_INTERNAL_ORIGINATOR_OVERRIDE",
            "CODEX_PERMISSION_PROFILE",
            "CODEX_SANDBOX_NETWORK_DISABLED",
            "CODEX_SESSION_ID",
            "CODEX_THREAD_ID",
            "CODEX_TOOL_CALL_ID",
        }:
            environment.pop(name, None)
    return environment


def _attempt_directory(output_dir: Path, trial_id: str) -> Path:
    base = output_dir / "trials" / trial_id
    if not base.exists():
        return base
    attempt = 2
    while (output_dir / "trials" / f"{trial_id}-attempt{attempt:02d}").exists():
        attempt += 1
    return output_dir / "trials" / f"{trial_id}-attempt{attempt:02d}"


def run_trial(
    *,
    trial_id: str,
    prompt_id: str,
    repeat: int,
    request: dict[str, str],
    editor: Path,
    codex: Path,
    model: str,
    reasoning_effort: str,
    fast_mode: bool,
    trial_dir: Path,
    create_timeout_minutes: float,
    generation_timeout_minutes: float,
    build_timeout_minutes: float,
) -> dict[str, str]:
    trial_dir.mkdir(parents=True)
    project = trial_dir / "unity_project"
    prompt_text = create_prompt(request)
    prompt_file = trial_dir / "prompt.txt"
    prompt_file.write_text(prompt_text, encoding="utf-8")
    create_log = trial_dir / "unity_create.log"
    create_stdout = trial_dir / "unity_create_stdout.log"
    events_file = trial_dir / "codex_events.jsonl"
    stderr_file = trial_dir / "codex_stderr.log"
    output_file = trial_dir / "codex_final.txt"
    started = time.monotonic()
    row = {
        "trial_id": trial_id,
        "prompt_id": prompt_id,
        "repeat": str(repeat),
        **request,
        "request_sha256": hashlib.sha256(
            json.dumps(request, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "model": model,
        "reasoning_effort": reasoning_effort,
        "fast_mode": str(fast_mode),
        "unity_editor": str(editor),
        "unity_project": str(project),
        "setup_status": "failed",
        "setup_seconds": "",
        "codex_status": "not_started",
        "generation_seconds": "",
        "build_status": "not_attempted",
        "build_seconds": "",
        "total_seconds": "",
        "input_tokens": "",
        "cached_input_tokens": "",
        "output_tokens": "",
        "reasoning_output_tokens": "",
        "total_tokens": "",
        "token_usage_status": "missing",
        "codex_exit_code": "",
        "build_exit_code": "",
        "build_error": "",
        "execution_error": "",
        "prompt_file": str(prompt_file),
        "codex_events_file": str(events_file),
        "codex_stderr_file": str(stderr_file),
        "unity_create_log_file": str(create_log),
        "unity_build_log_file": "",
        "unity_build_output": "",
    }
    create_command = [
        str(editor),
        "-batchmode",
        "-nographics",
        "-quit",
        "-createProject",
        str(project),
        "-logFile",
        str(create_log),
    ]
    try:
        create_exit, create_seconds, create_timed_out = run_command(
            create_command,
            cwd=trial_dir,
            stdout_file=create_stdout,
            timeout_minutes=create_timeout_minutes,
        )
    except OSError as error:
        row["setup_status"] = "infrastructure_error"
        row["execution_error"] = str(error)
        row["total_seconds"] = str(round(time.monotonic() - started, 1))
        return row
    row["setup_seconds"] = str(create_seconds)
    if (
        create_timed_out
        or create_exit != 0
        or not (project / "ProjectSettings" / "ProjectVersion.txt").is_file()
    ):
        row["setup_status"] = "timed_out" if create_timed_out else "failed"
        row["total_seconds"] = str(round(time.monotonic() - started, 1))
        return row
    row["setup_status"] = "completed"
    subprocess.run(
        ["git", "init", "-q", str(project)],
        cwd=trial_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    command = [
        str(codex),
        "exec",
        "--cd",
        str(project),
        "--sandbox",
        "workspace-write",
        "--skip-git-repo-check",
        "--ignore-rules",
        "--json",
        "--model",
        model,
        "--config",
        f"model_reasoning_effort={reasoning_effort}",
        "--output-last-message",
        str(output_file),
    ]
    if fast_mode:
        command.extend(("--config", 'service_tier="fast"'))
    command.append("-")
    try:
        codex_exit, generation_seconds, codex_timed_out = run_command(
            command,
            cwd=project,
            stdout_file=events_file,
            stderr_file=stderr_file,
            prompt=prompt_text,
            timeout_minutes=generation_timeout_minutes,
            environment=_codex_environment(),
        )
    except OSError as error:
        row["codex_status"] = "infrastructure_error"
        row["execution_error"] = str(error)
        row["total_seconds"] = str(round(time.monotonic() - started, 1))
        return row
    row["codex_exit_code"] = str(codex_exit)
    row["generation_seconds"] = str(generation_seconds)
    row["codex_status"] = (
        "timed_out" if codex_timed_out else "completed" if codex_exit == 0 else "failed"
    )
    row.update({key: str(value) for key, value in collect_codex_usage(events_file).items()})
    if row["codex_status"] != "completed" and row["token_usage_status"] == "complete":
        row["token_usage_status"] = "partial"
    build = run_player_build(
        project,
        trial_dir / "build",
        editor_path=str(editor),
        timeout_minutes=build_timeout_minutes,
    )
    row["build_status"] = str(build["player_build_status"])
    row["build_seconds"] = str(build["player_build_seconds"])
    row["build_exit_code"] = str(build["player_build_exit_code"])
    row["build_error"] = str(build["player_build_error"])
    row["unity_build_log_file"] = str(build["player_build_log_file"])
    row["unity_build_output"] = str(build["player_build_output"])
    row["total_seconds"] = str(round(time.monotonic() - started, 1))
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument(
        "--reasoning-effort", choices=("low", "medium", "high", "xhigh", "max"), default="medium"
    )
    parser.add_argument("--fast-mode", action="store_true")
    parser.add_argument("--unity-editor", type=Path)
    parser.add_argument("--codex-cli", type=Path)
    parser.add_argument("--create-timeout-minutes", type=float, default=20)
    parser.add_argument("--generation-timeout-minutes", type=float, default=120)
    parser.add_argument("--build-timeout-minutes", type=float, default=45)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if (
        args.repeats < 1
        or min(
            args.create_timeout_minutes,
            args.generation_timeout_minutes,
            args.build_timeout_minutes,
        )
        <= 0
    ):
        parser.error("repeats and all timeouts must be positive")
    workbook = args.workbook.resolve()
    try:
        requests = extract_requests(workbook)
        workbook_sha = hashlib.sha256(workbook.read_bytes()).hexdigest()
    except (OSError, ValueError, KeyError) as error:
        parser.error(f"cannot read workbook: {error}")
    if args.dry_run:
        for prompt_id, request in requests.items():
            for repeat in range(1, args.repeats + 1):
                print(f"{prompt_id}-{repeat:02d}: {request['genre']}")
        return 0

    editor = resolve_unity_editor(args.unity_editor)
    codex = resolve_codex(args.codex_cli)
    if editor is None:
        parser.error("Unity Editor not found; set UNITY_EDITOR_PATH or --unity-editor")
    if codex is None:
        parser.error("Codex CLI not found; install codex or pass --codex-cli")
    output_dir = args.output_dir.resolve()
    manifest = {
        "experiment": "one-shot-codex-unity",
        "workbook_sha256": workbook_sha,
        "model": args.model,
        "reasoning_effort": args.reasoning_effort,
        "fast_mode": args.fast_mode,
        "repeats": args.repeats,
        "unity_editor": str(editor),
        "codex_cli": str(codex),
        "create_timeout_minutes": args.create_timeout_minutes,
        "generation_timeout_minutes": args.generation_timeout_minutes,
        "build_timeout_minutes": args.build_timeout_minutes,
    }
    manifest_file = output_dir / "manifest.json"
    if output_dir.exists() and any(output_dir.iterdir()):
        if not args.resume or not manifest_file.is_file():
            parser.error("output directory is not empty; choose a new directory or --resume")
        if json.loads(manifest_file.read_text(encoding="utf-8")) != manifest:
            parser.error("experiment settings differ from the existing manifest")
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_file.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    results_file = output_dir / "results.csv"
    rows: list[dict[str, str]] = []
    if results_file.is_file():
        with results_file.open("r", encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            if tuple(reader.fieldnames or ()) != FIELDS:
                parser.error("results.csv uses another schema")
            rows = list(reader)
    completed = {row["trial_id"] for row in rows}
    total = len(requests) * args.repeats
    for prompt_id, request in requests.items():
        for repeat in range(1, args.repeats + 1):
            trial_id = f"{prompt_id}-{repeat:02d}"
            if trial_id in completed:
                continue
            print(f"Starting {trial_id} ({len(rows) + 1}/{total})", flush=True)
            row = run_trial(
                trial_id=trial_id,
                prompt_id=prompt_id,
                repeat=repeat,
                request=request,
                editor=editor,
                codex=codex,
                model=args.model,
                reasoning_effort=args.reasoning_effort,
                fast_mode=args.fast_mode,
                trial_dir=_attempt_directory(output_dir, trial_id),
                create_timeout_minutes=args.create_timeout_minutes,
                generation_timeout_minutes=args.generation_timeout_minutes,
                build_timeout_minutes=args.build_timeout_minutes,
            )
            with results_file.open(
                "a", encoding="utf-8-sig" if not rows else "utf-8", newline=""
            ) as target:
                writer = csv.DictWriter(target, fieldnames=FIELDS)
                if not rows:
                    writer.writeheader()
                writer.writerow(row)
                target.flush()
                os.fsync(target.fileno())
            rows.append(row)
            write_reports(output_dir, rows)
            print(
                f"Finished {trial_id}: codex={row['codex_status']} "
                f"build={row['build_status']} generation={row['generation_seconds']}s "
                f"tokens={row['total_tokens'] or row['token_usage_status']}",
                flush=True,
            )
            if row["setup_status"] != "completed":
                print("Stopping batch: blank Unity project creation failed.", flush=True)
                return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
