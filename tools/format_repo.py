"""Format or verify all Python and C# source code in this repository."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def repository_files(pattern: str) -> list[str]:
    result = subprocess.run(
        [
            "git",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            pattern,
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return [line for line in result.stdout.splitlines() if line]


def run(command: list[str]) -> None:
    print(f"+ {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def format_python(check: bool) -> None:
    python_files = repository_files("*.py")
    if not python_files:
        print("Python: no files found; skipping.")
        return

    probe = subprocess.run(
        [sys.executable, "-m", "ruff", "--version"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        raise RuntimeError(
            "Ruff is not installed. Run: "
            f"{sys.executable} -m pip install -r tools/format-requirements.txt"
        )

    command = [sys.executable, "-m", "ruff", "format"]
    if check:
        command.append("--check")

    argument_file: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".txt",
            delete=False,
        ) as file:
            argument_file = Path(file.name)
            file.write("\n".join(python_files))
            file.write("\n")
        command.append(f"@{argument_file}")
        run(command)
    finally:
        if argument_file is not None:
            argument_file.unlink(missing_ok=True)


def format_csharp(check: bool) -> None:
    if not repository_files("*.cs") and not repository_files("*.csx"):
        print("C#: no files found; skipping.")
        return

    if shutil.which("dotnet") is None:
        raise RuntimeError("The .NET SDK is required to format C# files.")

    run(["dotnet", "tool", "restore"])
    command = ["dotnet", "csharpier", "check" if check else "format", "."]
    run(command)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply or verify repository-wide Python and C# formatting."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="Rewrite files in canonical format.")
    mode.add_argument("--check", action="store_true", help="Fail if formatting changes are needed.")
    args = parser.parse_args()

    try:
        format_python(args.check)
        format_csharp(args.check)
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Formatting failed: {error}", file=sys.stderr)
        return 1

    print("Repository formatting passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
