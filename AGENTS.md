# Repository agent instructions

These instructions apply to the entire repository.

## Formatting

- Python is formatted with Ruff using `ruff.toml`.
- C# is formatted with CSharpier using the repository-local tool manifest.
- Do not apply a competing formatter or hand-format code against those tools.
- Before completing a change that touches Python or C#, run:

  ```text
  python tools/format_repo.py --write
  python tools/format_repo.py --check
  ```

- If Ruff is unavailable, install the pinned formatter dependency with:

  ```text
  python -m pip install -r tools/format-requirements.txt
  ```

- Keep generated files and Unity build output out of formatting changes.
