# Feature checklist sources

The repository keeps the extracted checklist originals under `docs/`. If the source DOCX files
are available, place the seventeen `[Validator Checklist] *.docx` documents in `originals/` and point
`MAINFLOW_FEATURE_CHECKLIST_SOURCE` at that directory.
Each repository Markdown checklist contains 30 criteria. The validation workflow never modifies
these source documents. For every generated game it copies
the originals into `workspace/<project_id>/validation/feature_checklists/original/` and writes
annotated copies plus machine-readable results into the sibling `checked/` directory.

For each concrete request, Gemma creates exactly one 30-item checklist for every final Feature,
including requirement-dependency Features. Qwen Coder creates one matching Unity PlayMode fixture
per checklist. Each set is saved under
`workspace/<project_id>/validation/feature_checklists/generated/<feature_id>/`; the C# fixtures are
also copied to `game/unity_project/Assets/Tests/PlayMode/GeneratedFeatureChecklist_DFC*.cs`.
Skipped or missing dynamic tests fail validation. The total required checks are therefore
`feature count × 30`. Game repair and recompilation continue until all checks pass or the existing
10-retry safety limit is reached.

The source directory can be overridden with `MAINFLOW_FEATURE_CHECKLIST_SOURCE`. This is useful
while the documents are supplied outside Git. `MAINFLOW_FEATURE_CHECKLIST_RETRIES` controls the
repair count and is strictly limited to 0–10; the default is 10.
