# Feature checklist sources

The repository keeps the extracted checklist originals under `docs/`. If the source DOCX files
are available, place the seventeen `[Validator Checklist] *.docx` documents in `originals/` and point
`MAINFLOW_FEATURE_CHECKLIST_SOURCE` at that directory.
The validation workflow never modifies these source documents. For every generated game it copies
the originals into `workspace/<project_id>/validation/feature_checklists/original/` and writes
annotated copies plus machine-readable results into the sibling `checked/` directory.

The source directory can be overridden with `MAINFLOW_FEATURE_CHECKLIST_SOURCE`. This is useful
while the documents are supplied outside Git. `MAINFLOW_FEATURE_CHECKLIST_RETRIES` controls the
repair count and is strictly limited to 0–10; the default is 10.
