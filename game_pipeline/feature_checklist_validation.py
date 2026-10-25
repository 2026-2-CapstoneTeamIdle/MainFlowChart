"""Unity Test Framework checklist validation and bounded AI repair loop."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, cast

from MCP.llm_config import LLMSettings
from MCP.llm_providers import create_llm_provider
from MCP.llm_types import LLMConversationMessage, LLMProvider

ChecklistStatus = Literal["passed", "failed", "skipped", "error"]


@dataclass(frozen=True)
class ChecklistResult:
    feature_id: str
    feature_name: str
    status: ChecklistStatus
    message: str
    test_name: str


@dataclass
class FeatureChecklistOutcome:
    status: Literal["passed", "failed"]
    attempts: int
    results: list[ChecklistResult] = field(default_factory=list)
    issues: list[dict[str, str]] = field(default_factory=list)
    log: str = ""


@dataclass(frozen=True)
class RepairPlan:
    target_files: tuple[str, ...]
    rationale: str
    required_changes: tuple[str, ...]


FEATURES = {
    "FC01": "8방향 공격",
    "FC02": "8방향 이동",
    "FC03": "자동 공격",
    "FC04": "공격",
    "FC05": "점프",
    "FC06": "성장",
    "FC07": "카드 덱 구성",
    "FC08": "대화 선택",
    "FC09": "타워 배치",
}


class FeatureChecklistRepairAI:
    """Two-stage, provider-swappable checklist diagnosis and source repair."""

    ALLOWED_SUFFIXES = frozenset({".cs", ".json", ".asset", ".unity"})
    PROTECTED_PREFIXES = (
        "Assets/Tests/",
        "Packages/",
        "ProjectSettings/",
        "Assets/GameTemplate/Editor/RuntimeSmokeValidator.cs",
    )

    def __init__(self, provider: LLMProvider, *, max_files: int = 8) -> None:
        if not 1 <= max_files <= 12:
            raise ValueError("Checklist repair max files must be between 1 and 12")
        self.provider = provider
        self.max_files = max_files

    @classmethod
    def from_environment(cls) -> FeatureChecklistRepairAI:
        configured = os.environ.get("LLM_FEATURE_CHECKLIST_REPAIR_PROVIDER")
        fallback = os.environ.get("MAINFLOW_FEATURE_PROVIDER", "local")
        settings = LLMSettings.from_environment(
            node_name="feature_checklist_repair",
            provider=configured or fallback,
        )
        return cls(
            create_llm_provider(settings),
            max_files=int(os.environ.get("MAINFLOW_FEATURE_CHECKLIST_MAX_FILES", "8")),
        )

    def repair(
        self,
        project_root: Path,
        failures: list[ChecklistResult],
        compile_log: str,
    ) -> RepairPlan:
        return asyncio.run(self._repair(project_root, failures, compile_log))

    async def _repair(
        self,
        project_root: Path,
        failures: list[ChecklistResult],
        compile_log: str,
    ) -> RepairPlan:
        try:
            inventory = self._inventory(project_root)
            plan_response = await self.provider.complete(
                [
                    LLMConversationMessage(
                        role="user",
                        content=self._plan_prompt(failures, compile_log, inventory),
                    )
                ],
                [],
                system_prompt=(
                    "You are a Unity 2D debugging lead. Select the smallest source-file set "
                    "that can fix the failed acceptance checks. Never select host tests, package "
                    "manifests, or ProjectSettings. Return strict JSON only."
                ),
                temperature=0.0,
                require_tool=False,
            )
            plan = self._parse_plan(plan_response.text, project_root)
            sources = {
                path: (project_root / path).read_text(encoding="utf-8")
                for path in plan.target_files
            }
            repair_response = await self.provider.complete(
                [
                    LLMConversationMessage(
                        role="user",
                        content=self._repair_prompt(failures, plan, sources),
                    )
                ],
                [],
                system_prompt=(
                    "You repair Unity 2D project source. Preserve public contracts and make only "
                    "the changes required by the failed checklist. Return full replacement files "
                    "as strict JSON; do not use markdown."
                ),
                temperature=0.0,
                require_tool=False,
            )
            replacements = self._parse_replacements(
                repair_response.text,
                allowed_paths=set(plan.target_files),
            )
            for relative_path, content in replacements.items():
                (project_root / relative_path).write_text(content, encoding="utf-8")
            return plan
        finally:
            await self.provider.aclose()

    def _inventory(self, root: Path) -> list[str]:
        paths: list[str] = []
        for path in sorted((root / "Assets").rglob("*")):
            if not path.is_file() or path.suffix.lower() not in self.ALLOWED_SUFFIXES:
                continue
            relative = path.relative_to(root).as_posix()
            if any(relative.startswith(prefix) for prefix in self.PROTECTED_PREFIXES):
                continue
            paths.append(relative)
        return paths[:600]

    @staticmethod
    def _plan_prompt(
        failures: list[ChecklistResult], compile_log: str, inventory: list[str]
    ) -> str:
        failure_payload = [result.__dict__ for result in failures]
        diagnostics = "\n".join(
            line
            for line in compile_log.splitlines()
            if "error CS" in line or "Exception" in line or "FAILED" in line
        )[-5000:]
        return f"""Choose files to fix these Unity feature-checklist failures.

FAILURES:
{json.dumps(failure_payload, ensure_ascii=False, indent=2)}

RECENT_DIAGNOSTICS:
{diagnostics}

EDITABLE_FILE_INVENTORY:
{json.dumps(inventory, ensure_ascii=False)}

Return exactly:
{{
  "target_files": ["Assets/..."],
  "rationale": "why these files own the behavior",
  "required_changes": ["specific behavior change"]
}}
"""

    @staticmethod
    def _repair_prompt(
        failures: list[ChecklistResult], plan: RepairPlan, sources: dict[str, str]
    ) -> str:
        return f"""Repair the selected Unity files so every failed checklist passes.

FAILURES:
{json.dumps([item.__dict__ for item in failures], ensure_ascii=False, indent=2)}

PLAN:
{json.dumps({"target_files": plan.target_files, "rationale": plan.rationale, "required_changes": plan.required_changes}, ensure_ascii=False, indent=2)}

CURRENT_FILES:
{json.dumps(sources, ensure_ascii=False)}

Return exactly one JSON object. Include a full UTF-8 replacement for every changed file:
{{"files": [{{"relative_path": "Assets/...", "content": "complete file text"}}]}}
"""

    def _parse_plan(self, text: str, root: Path) -> RepairPlan:
        payload = self._json_object(text)
        raw_paths = payload.get("target_files")
        rationale = payload.get("rationale")
        raw_changes = payload.get("required_changes")
        if not isinstance(raw_paths, list) or not 1 <= len(raw_paths) <= self.max_files:
            raise ValueError("Repair plan must select a bounded, non-empty target_files list")
        if not isinstance(rationale, str) or not rationale.strip():
            raise ValueError("Repair plan requires a rationale")
        if not isinstance(raw_changes, list) or not raw_changes:
            raise ValueError("Repair plan requires concrete required_changes")
        paths: list[str] = []
        for value in raw_paths:
            if not isinstance(value, str):
                raise TypeError("Repair target paths must be strings")
            relative = Path(value).as_posix().lstrip("/")
            if (
                relative.startswith("../")
                or Path(relative).suffix.lower() not in self.ALLOWED_SUFFIXES
                or any(relative.startswith(prefix) for prefix in self.PROTECTED_PREFIXES)
                or not (root / relative).is_file()
            ):
                raise ValueError(f"Unsafe or missing repair target: {value}")
            if relative not in paths:
                paths.append(relative)
        changes = tuple(str(item).strip() for item in raw_changes if str(item).strip())
        if not changes:
            raise ValueError("Repair plan required_changes are empty")
        return RepairPlan(tuple(paths), rationale.strip(), changes)

    @classmethod
    def _parse_replacements(cls, text: str, *, allowed_paths: set[str]) -> dict[str, str]:
        payload = cls._json_object(text)
        raw_files = payload.get("files")
        if not isinstance(raw_files, list) or not raw_files:
            raise ValueError("Repair response must contain at least one replacement file")
        replacements: dict[str, str] = {}
        for item in raw_files:
            if not isinstance(item, dict):
                raise TypeError("Repair file entries must be objects")
            path = item.get("relative_path")
            content = item.get("content")
            if path not in allowed_paths:
                raise ValueError(f"Repair attempted an unapproved file: {path}")
            if not isinstance(content, str) or not content.strip():
                raise ValueError(f"Repair returned empty content for {path}")
            replacements[cast(str, path)] = content
        return replacements

    @staticmethod
    def _json_object(text: str) -> dict[str, Any]:
        normalized = text.strip()
        if normalized.startswith("```"):
            lines = normalized.splitlines()
            normalized = "\n".join(lines[1:-1])
            if normalized.lstrip().startswith("json"):
                normalized = normalized.lstrip()[4:].lstrip()
        payload = json.loads(normalized)
        if not isinstance(payload, dict):
            raise TypeError("AI response must be a JSON object")
        return payload


class FeatureChecklistWorkflow:
    """Run feature PlayMode checks after compile and repair failures at most ten times."""

    TEST_FILTER = "TeamIdle.GameTemplate.FeatureTests.FeatureChecklistTests"

    def __init__(
        self,
        *,
        unity_editor: str | Path,
        timeout_seconds: int,
        max_retries: int = 10,
        repair_ai_factory: Any = FeatureChecklistRepairAI.from_environment,
    ) -> None:
        if not 0 <= max_retries <= 10:
            raise ValueError("Feature checklist retries must be between 0 and 10")
        self.editor = Path(unity_editor).resolve()
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.repair_ai_factory = repair_ai_factory

    def run(
        self,
        *,
        project_root: Path,
        workspace_root: Path,
        source_root: Path,
        compile_validation: Callable[[Path], Any],
    ) -> FeatureChecklistOutcome:
        self._copy_checklist_sources(source_root, workspace_root)
        history: list[dict[str, Any]] = []
        combined_log = ""
        final_results: list[ChecklistResult] = []
        for attempt in range(self.max_retries + 1):
            results, run_log = self._run_tests(project_root)
            combined_log += f"\n--- FEATURE CHECKLIST ATTEMPT {attempt} ---\n{run_log}"
            final_results = results
            failures = [item for item in results if item.status in {"failed", "error"}]
            history.append(
                {
                    "attempt": attempt,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "results": [item.__dict__ for item in results],
                    "failed_features": sorted({item.feature_name for item in failures}),
                }
            )
            self._write_records(workspace_root, history, source_root)
            if not failures:
                return FeatureChecklistOutcome("passed", attempt + 1, results, log=combined_log)
            if attempt == self.max_retries:
                break

            try:
                repair_ai = self.repair_ai_factory()
                plan = repair_ai.repair(project_root, failures, combined_log)
            except Exception as error:  # noqa: BLE001 - persisted workflow boundary
                history[-1]["repair_error"] = f"{type(error).__name__}: {error}"
                self._write_records(workspace_root, history, source_root)
                final_results = [
                    *failures,
                    ChecklistResult(
                        "AI_REPAIR",
                        "AI 체크리스트 수정",
                        "error",
                        f"{type(error).__name__}: {error}",
                        "feature_checklist_repair",
                    ),
                ]
                break
            history[-1]["repair_plan"] = {
                "target_files": list(plan.target_files),
                "rationale": plan.rationale,
                "required_changes": list(plan.required_changes),
            }
            self._write_records(workspace_root, history, source_root)

            compile_outcome = compile_validation(project_root)
            combined_log += "\n--- POST-REPAIR COMPILE ---\n" + compile_outcome.unity_log
            if compile_outcome.status != "passed":
                compile_failures = [
                    ChecklistResult(
                        "COMPILE",
                        "Unity 컴파일",
                        "error",
                        issue["message"],
                        "unity.batchmode",
                    )
                    for issue in compile_outcome.issues
                    if issue["severity"] == "error"
                ]
                final_results = compile_failures or [
                    ChecklistResult(
                        "COMPILE",
                        "Unity 컴파일",
                        "error",
                        "AI repair introduced a compilation failure.",
                        "unity.batchmode",
                    )
                ]
                history.append(
                    {
                        "attempt": attempt,
                        "phase": "post_repair_compile",
                        "results": [item.__dict__ for item in final_results],
                    }
                )
                self._write_records(workspace_root, history, source_root)

        issues = [
            {
                "code": "FEATURE_CHECKLIST_FAILED",
                "severity": "error",
                "message": f"{item.feature_id} {item.feature_name}: {item.message}",
            }
            for item in final_results
            if item.status in {"failed", "error"}
        ]
        return FeatureChecklistOutcome(
            "failed",
            self.max_retries + 1,
            final_results,
            issues,
            combined_log,
        )

    def _run_tests(self, root: Path) -> tuple[list[ChecklistResult], str]:
        temporary = Path(tempfile.mkdtemp(prefix="mainflow-feature-tests-"))
        results_path = temporary / "feature-checklists.xml"
        log_path = temporary / "feature-checklists.log"
        try:
            command = [
                str(self.editor),
                "-batchmode",
                "-nographics",
                "-projectPath",
                str(root),
                "-runTests",
                "-testPlatform",
                "PlayMode",
                "-testFilter",
                self.TEST_FILTER,
                "-testResults",
                str(results_path),
                "-logFile",
                str(log_path),
            ]
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                check=False,
            )
            log = (completed.stdout or "") + (completed.stderr or "")
            if log_path.is_file():
                log += log_path.read_text(encoding="utf-8", errors="replace")
            if not results_path.is_file():
                return (
                    [
                        ChecklistResult(
                            "FRAMEWORK",
                            "Unity Test Framework",
                            "error",
                            f"Unity produced no NUnit result (exit={completed.returncode}).",
                            self.TEST_FILTER,
                        )
                    ],
                    log,
                )
            return self._parse_nunit(results_path), log
        except (OSError, subprocess.TimeoutExpired) as error:
            return (
                [
                    ChecklistResult(
                        "FRAMEWORK",
                        "Unity Test Framework",
                        "error",
                        str(error),
                        self.TEST_FILTER,
                    )
                ],
                str(error),
            )
        finally:
            shutil.rmtree(temporary, ignore_errors=True)

    @staticmethod
    def _parse_nunit(path: Path) -> list[ChecklistResult]:
        root = ET.parse(path).getroot()
        results: list[ChecklistResult] = []
        for case in root.iter("test-case"):
            full_name = case.attrib.get("fullname") or case.attrib.get("name", "")
            feature_id = next((key for key in FEATURES if key in full_name), None)
            if feature_id is None:
                continue
            result = case.attrib.get("result", "Failed")
            label = case.attrib.get("label", "")
            if result == "Passed":
                status: ChecklistStatus = "passed"
            elif result == "Skipped" or label in {"Ignored", "Explicit"}:
                status = "skipped"
            else:
                status = "failed"
            message_node = case.find("./failure/message")
            if message_node is None:
                message_node = case.find("./reason/message")
            message = (
                message_node.text.strip()
                if message_node is not None and message_node.text
                else result
            )
            results.append(
                ChecklistResult(feature_id, FEATURES[feature_id], status, message, full_name)
            )
        if not results:
            return [
                ChecklistResult(
                    "FRAMEWORK",
                    "Unity Test Framework",
                    "error",
                    "NUnit report contained no feature checklist tests.",
                    FeatureChecklistWorkflow.TEST_FILTER,
                )
            ]
        return results

    @staticmethod
    def _copy_checklist_sources(source_root: Path, workspace_root: Path) -> None:
        originals = workspace_root / "validation" / "feature_checklists" / "original"
        originals.mkdir(parents=True, exist_ok=True)
        if source_root.is_dir():
            sources = [*source_root.glob("*Validator Checklist*.docx")]
            sources.extend(source_root.glob("*Validator Checklist*.md"))
            for source in sorted(sources):
                target = originals / source.name
                if not target.exists():
                    shutil.copy2(source, target)

    @staticmethod
    def _write_records(
        workspace_root: Path,
        history: list[dict[str, Any]],
        source_root: Path,
    ) -> None:
        validation_root = workspace_root / "validation" / "feature_checklists"
        checked_root = validation_root / "checked"
        checked_root.mkdir(parents=True, exist_ok=True)
        (checked_root / "results.json").write_text(
            json.dumps({"attempts": history}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if source_root.is_dir():
            latest = history[-1].get("results", []) if history else []
            for source in sorted(source_root.glob("*Validator Checklist*.docx")):
                FeatureChecklistWorkflow._write_checked_docx(source, checked_root, latest)
            for source in sorted(source_root.glob("*Validator Checklist*.md")):
                FeatureChecklistWorkflow._write_checked_markdown(source, checked_root, latest)
        lines = ["# Feature 검증 기록", ""]
        has_sources = source_root.is_dir() and (
            bool(list(source_root.glob("*Validator Checklist*.docx")))
            or bool(list(source_root.glob("*Validator Checklist*.md")))
        )
        if not has_sources:
            lines.extend(
                [
                    "> 원본 DOCX를 찾지 못했습니다. 원본을 다시 첨부한 뒤 체크리스트 원본 경로를 설정해야 합니다.",
                    "",
                ]
            )
        for attempt in history:
            lines.extend([f"## Retry {attempt.get('attempt', 0)}", ""])
            for item in attempt.get("results", []):
                mark = "x" if item["status"] == "passed" else " "
                lines.append(
                    f"- [{mark}] {item['feature_id']} {item['feature_name']} — "
                    f"{item['status']}: {item['message']}"
                )
            plan = attempt.get("repair_plan")
            if plan:
                lines.extend(["", "수정 대상 파일:"])
                lines.extend(f"- `{path}`" for path in plan["target_files"])
            lines.append("")
        content = "\n".join(lines).rstrip() + "\n"
        (workspace_root / "Feature검증기록.md").write_text(content, encoding="utf-8")
        (checked_root / "체크리스트_체크본.md").write_text(content, encoding="utf-8")

    @staticmethod
    def _write_checked_docx(
        source: Path, checked_root: Path, results: list[dict[str, Any]]
    ) -> None:
        """Append machine results to a copied DOCX without touching the original."""

        feature_id = None
        for candidate in FEATURES:
            numeric = candidate.removeprefix("FC")
            if numeric in source.stem:
                feature_id = candidate
                break
        relevant = [item for item in results if item.get("feature_id") == feature_id]
        target = checked_root / f"{source.stem}_체크본.docx"
        temporary = target.with_suffix(".tmp")
        namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        ET.register_namespace("w", namespace)
        with (
            zipfile.ZipFile(source, "r") as input_archive,
            zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as output_archive,
        ):
            for info in input_archive.infolist():
                content = input_archive.read(info.filename)
                if info.filename == "word/document.xml":
                    document = ET.fromstring(content)
                    body = document.find(f"{{{namespace}}}body")
                    if body is not None:
                        section = body.find(f"{{{namespace}}}sectPr")
                        insert_at = list(body).index(section) if section is not None else len(body)
                        lines = ["자동 Feature 검증 결과"]
                        if relevant:
                            lines.extend(
                                (
                                    f"{'☒' if item['status'] == 'passed' else '☐'} "
                                    f"{item['feature_id']} {item['feature_name']} — "
                                    f"{item['status']}: {item['message']}"
                                )
                                for item in relevant
                            )
                        else:
                            lines.append("☐ 해당 Feature는 이번 게임 요청에 포함되지 않았습니다.")
                        for offset, line in enumerate(lines):
                            paragraph = ET.Element(f"{{{namespace}}}p")
                            run = ET.SubElement(paragraph, f"{{{namespace}}}r")
                            text = ET.SubElement(run, f"{{{namespace}}}t")
                            text.text = line
                            body.insert(insert_at + offset, paragraph)
                    content = ET.tostring(document, encoding="utf-8", xml_declaration=True)
                output_archive.writestr(info, content)
        temporary.replace(target)

    @staticmethod
    def _write_checked_markdown(
        source: Path, checked_root: Path, results: list[dict[str, Any]]
    ) -> None:
        feature_id = None
        for candidate in FEATURES:
            if candidate.removeprefix("FC") in source.stem:
                feature_id = candidate
                break
        relevant = [item for item in results if item.get("feature_id") == feature_id]
        status = relevant[0]["status"] if relevant else "skipped"
        content = source.read_text(encoding="utf-8")
        detail = relevant[0]["message"] if relevant else "이번 요청에 포함되지 않은 기능"
        content += f"\n\n## 자동 검증 결과\n\n- 상태: {status}\n- 근거: {detail}\n"
        (checked_root / f"{source.stem}_체크본.md").write_text(content, encoding="utf-8")
