"""Generate one 30-item checklist and one Unity test fixture for every feature."""

from __future__ import annotations

import json
import os
import re
import shutil
import textwrap
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from game_pipeline.gemini_feature_generator import (
    GeminiApiClient,
    LocalAIJsonClient,
    OpenAIJsonClient,
    StructuredJsonClient,
    resolve_feature_provider_from_environment,
)
from game_pipeline.project_context_index import (
    build_project_context_index,
    retrieve_prompt_api_contract,
)
from mainflow.contracts import FeatureRequirement, LogicAnalysis

CHECKLIST_ITEM_COUNT = 30
CHECKLIST_BATCH_SIZE = 10
CHECKLIST_BATCH_COUNT = CHECKLIST_ITEM_COUNT // CHECKLIST_BATCH_SIZE
TEST_METHOD_BATCH_SIZE = 10
TEST_METHOD_BATCH_COUNT = CHECKLIST_ITEM_COUNT // TEST_METHOD_BATCH_SIZE
DEFAULT_CHECKLIST_MODEL = "gemma4-12b-it-qat-q4-0"
DEFAULT_TEST_CODE_MODEL = "qwen2.5-coder-7b-q5-k-m"
GENERATED_TEST_DIRECTORY = Path("Assets/Tests/PlayMode")

CHECKLIST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["criteria"],
    "properties": {
        "criteria": {
            "type": "array",
            "minItems": CHECKLIST_BATCH_SIZE,
            "maxItems": CHECKLIST_BATCH_SIZE,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "feature_ids",
                    "title",
                    "category",
                    "setup",
                    "action",
                    "expected",
                    "evidence",
                ],
                "properties": {
                    "feature_ids": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 6,
                        "items": {"type": "string"},
                    },
                    "title": {"type": "string"},
                    "category": {
                        "type": "string",
                        "enum": [
                            "structure",
                            "binding",
                            "runtime",
                            "state",
                            "interaction",
                            "edge_case",
                            "integration",
                            "feedback",
                            "recovery",
                            "regression",
                        ],
                    },
                    "setup": {"type": "string"},
                    "action": {"type": "string"},
                    "expected": {"type": "string"},
                    "evidence": {"type": "string"},
                },
            },
        }
    },
}

TEST_METHOD_BATCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["methods"],
    "properties": {
        "methods": {
            "type": "array",
            "minItems": TEST_METHOD_BATCH_SIZE,
            "maxItems": TEST_METHOD_BATCH_SIZE,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["criterion_id", "source_code"],
                "properties": {
                    "criterion_id": {"type": "string"},
                    "source_code": {"type": "string"},
                },
            },
        }
    },
}


@dataclass(frozen=True)
class ChecklistCriterion:
    criterion_id: str
    feature_ids: tuple[str, ...]
    title: str
    category: str
    setup: str
    action: str
    expected: str
    evidence: str


@dataclass(frozen=True)
class FeatureChecklist:
    checklist_version: str
    checklist_id: str
    project_id: str
    feature_id: str
    feature_name: str
    feature_description: str
    feature_origin: str
    model_role: str
    criteria: tuple[ChecklistCriterion, ...]

    @property
    def criterion_prefix(self) -> str:
        return self.criteria[0].criterion_id.rsplit("_", 1)[0]

    @property
    def test_class_name(self) -> str:
        return f"GeneratedFeatureChecklist_{self.criterion_prefix}"

    @property
    def test_filename(self) -> str:
        return self.test_class_name + ".cs"

    def to_dict(self) -> dict[str, Any]:
        return {
            "checklist_version": self.checklist_version,
            "checklist_id": self.checklist_id,
            "project_id": self.project_id,
            "feature_id": self.feature_id,
            "feature_name": self.feature_name,
            "feature_description": self.feature_description,
            "feature_origin": self.feature_origin,
            "model_role": self.model_role,
            "item_count": len(self.criteria),
            "criteria": [
                {**asdict(item), "feature_ids": list(item.feature_ids)} for item in self.criteria
            ],
        }


@dataclass(frozen=True)
class ProjectFeatureChecklist:
    checklist_version: str
    project_id: str
    model_role: str
    feature_checklists: tuple[FeatureChecklist, ...]

    @property
    def criteria(self) -> tuple[ChecklistCriterion, ...]:
        return tuple(
            criterion for checklist in self.feature_checklists for criterion in checklist.criteria
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "checklist_version": self.checklist_version,
            "project_id": self.project_id,
            "model_role": self.model_role,
            "checklist_count": len(self.feature_checklists),
            "item_count_per_checklist": CHECKLIST_ITEM_COUNT,
            "total_item_count": len(self.criteria),
            "feature_checklists": [checklist.to_dict() for checklist in self.feature_checklists],
        }


class DynamicFeatureChecklistGenerator:
    """Create each feature checklist through bounded ten-item structured requests."""

    def __init__(self, client: StructuredJsonClient, provider: str) -> None:
        self.client = client
        self.provider = provider

    def generate(
        self,
        *,
        project_id: str,
        logic_analysis: LogicAnalysis,
        source_root: Path,
    ) -> ProjectFeatureChecklist:
        features = logic_analysis["features"]
        if not features:
            raise ValueError("At least one feature is required to generate checklists")
        known_feature_ids = {feature["feature_id"] for feature in features}
        feature_checklists: list[FeatureChecklist] = []
        for feature_index, feature in enumerate(features, start=1):
            criteria: list[ChecklistCriterion] = []
            criterion_fingerprints: set[str] = set()
            for batch_index in range(CHECKLIST_BATCH_COUNT):
                response = self.client.generate_json(
                    self._prompt(
                        logic_analysis,
                        feature,
                        source_root,
                        batch_index=batch_index,
                        previous_criteria=criteria,
                    ),
                    CHECKLIST_SCHEMA,
                )
                raw_criteria = response.get("criteria")
                if not isinstance(raw_criteria, list) or len(raw_criteria) != CHECKLIST_BATCH_SIZE:
                    raise ValueError(
                        f"Feature {feature['feature_id']} checklist batch {batch_index + 1} "
                        f"must contain exactly {CHECKLIST_BATCH_SIZE} items"
                    )
                for local_index, item in enumerate(raw_criteria, start=1):
                    if not isinstance(item, Mapping):
                        raise TypeError("Generated checklist items must be objects")
                    criterion_index = batch_index * CHECKLIST_BATCH_SIZE + local_index
                    criterion = _validate_criterion(
                        feature_index,
                        criterion_index,
                        item,
                        known_feature_ids,
                        feature["feature_id"],
                    )
                    fingerprint = _criterion_fingerprint(criterion)
                    if fingerprint in criterion_fingerprints:
                        raise ValueError(
                            f"Feature {feature['feature_id']} checklist contains a duplicate "
                            f"criterion in batch {batch_index + 1}"
                        )
                    criterion_fingerprints.add(fingerprint)
                    criteria.append(criterion)
            if len(criteria) != CHECKLIST_ITEM_COUNT:
                raise ValueError(
                    f"Feature {feature['feature_id']} checklist must contain exactly "
                    f"{CHECKLIST_ITEM_COUNT} items after batching"
                )
            feature_checklists.append(
                FeatureChecklist(
                    checklist_version="1.2.0",
                    checklist_id=f"checklist-{feature['feature_id']}",
                    project_id=project_id,
                    feature_id=feature["feature_id"],
                    feature_name=feature["name"],
                    feature_description=feature["description"],
                    feature_origin=feature.get("origin", "user"),
                    model_role=f"feature_checklist_generation:{self.provider}",
                    criteria=tuple(criteria),
                )
            )
        return ProjectFeatureChecklist(
            checklist_version="1.2.0",
            project_id=project_id,
            model_role=f"feature_checklist_generation:{self.provider}",
            feature_checklists=tuple(feature_checklists),
        )

    @staticmethod
    def _prompt(
        logic_analysis: LogicAnalysis,
        target_feature: FeatureRequirement,
        source_root: Path,
        *,
        batch_index: int,
        previous_criteria: list[ChecklistCriterion],
    ) -> str:
        features = [
            {
                "feature_id": feature["feature_id"],
                "name": feature["name"],
                "description": feature["description"],
                "origin": feature.get("origin", "user"),
                "acceptance_criteria": feature.get("acceptance_criteria", ""),
                "supports_feature_ids": feature.get("supports_feature_ids", []),
                "dependency_role": feature.get("dependency_role", ""),
            }
            for feature in logic_analysis["features"]
        ]
        payload = {
            "genre": logic_analysis["genre"],
            "viewpoint": logic_analysis["viewpoint"],
            "core_loop": logic_analysis["core_loop"],
            "target_feature": next(
                item for item in features if item["feature_id"] == target_feature["feature_id"]
            ),
            "related_features": features,
            "existing_checklist_catalog": _existing_checklist_catalog(source_root),
            "batch": {
                "index": batch_index + 1,
                "count": CHECKLIST_BATCH_COUNT,
                "item_count": CHECKLIST_BATCH_SIZE,
                "focus": _checklist_batch_focus(batch_index),
            },
            "previous_criteria": [
                {
                    "title": criterion.title,
                    "category": criterion.category,
                    "expected": criterion.expected,
                }
                for criterion in previous_criteria
            ],
        }
        return (
            f"You are a Unity QA lead. Create batch {batch_index + 1} of "
            f"{CHECKLIST_BATCH_COUNT} containing EXACTLY {CHECKLIST_BATCH_SIZE} concise, "
            "non-overlapping automated PlayMode acceptance checks for target_feature only. The "
            f"host will combine all batches into one {CHECKLIST_ITEM_COUNT}-item checklist. Every "
            "criterion must include target_feature.feature_id in feature_ids. Related feature ids "
            "may additionally appear only when checking a real dependency or integration. Cover "
            "the target feature's initialization, required objects/data, runtime binding, trigger, "
            "state transitions, observable consequence, player feedback, boundary values, repeated "
            "execution, pause/restart/recovery, dependency integration, and regression behavior. "
            "Adapt relevant patterns from existing_checklist_catalog. Every check must be "
            "executable by Unity Test Framework without a human, screenshot judgment, network "
            "request, external service, or arbitrary delay. State exact setup, action, expected "
            "result, and machine-readable evidence. Do not test unrelated features merely to fill "
            "the count. Do not repeat any previous_criteria title, expected behavior, or equivalent "
            "scenario. Follow batch.focus and use only supplied feature ids. Return strict JSON "
            "only.\n\n"
            f"INPUT={json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"
        )


class UnityChecklistTestGenerator:
    """Generate bounded method batches and assemble one guarded PlayMode fixture."""

    def __init__(self, client: StructuredJsonClient, provider: str) -> None:
        self.client = client
        self.provider = provider

    def generate(
        self,
        *,
        checklist: FeatureChecklist,
        project_root: Path,
        feedback: str = "",
    ) -> str:
        api_contract = _runtime_api_context(project_root, checklist)
        generated_methods: list[str] = []
        for batch_index in range(TEST_METHOD_BATCH_COUNT):
            start = batch_index * TEST_METHOD_BATCH_SIZE
            batch_criteria = checklist.criteria[start : start + TEST_METHOD_BATCH_SIZE]
            response = self.client.generate_json(
                self._prompt(
                    checklist,
                    batch_criteria,
                    api_contract,
                    feedback,
                    batch_index=batch_index,
                ),
                TEST_METHOD_BATCH_SCHEMA,
            )
            raw_methods = response.get("methods")
            if not isinstance(raw_methods, list) or len(raw_methods) != TEST_METHOD_BATCH_SIZE:
                raise ValueError(
                    f"Unity checklist test batch {batch_index + 1} must contain exactly "
                    f"{TEST_METHOD_BATCH_SIZE} methods"
                )
            expected_ids = [criterion.criterion_id for criterion in batch_criteria]
            for expected_id, item in zip(expected_ids, raw_methods, strict=True):
                if not isinstance(item, Mapping):
                    raise TypeError("Unity checklist test methods must be objects")
                criterion_id = str(item.get("criterion_id", "")).strip()
                source = item.get("source_code")
                if criterion_id != expected_id:
                    raise ValueError(
                        f"Unity checklist test batch returned {criterion_id!r}; "
                        f"expected {expected_id!r}"
                    )
                if not isinstance(source, str):
                    raise TypeError("Unity checklist test method has no source_code")
                generated_methods.append(_validate_test_method_source(source, expected_id))

        source = _assemble_test_source(checklist, generated_methods)
        return _validate_test_source(source, checklist)

    @staticmethod
    def _prompt(
        checklist: FeatureChecklist,
        batch_criteria: tuple[ChecklistCriterion, ...],
        api_contract: Mapping[str, Any],
        feedback: str,
        *,
        batch_index: int,
    ) -> str:
        payload = {
            "feature": {
                "feature_id": checklist.feature_id,
                "name": checklist.feature_name,
                "description": checklist.feature_description,
                "origin": checklist.feature_origin,
            },
            "criteria": [
                {**asdict(criterion), "feature_ids": list(criterion.feature_ids)}
                for criterion in batch_criteria
            ],
            "required_class_name": checklist.test_class_name,
            "runtime_api_contract": api_contract,
            "previous_generation_error": feedback[-3000:],
            "batch": {
                "index": batch_index + 1,
                "count": TEST_METHOD_BATCH_COUNT,
                "item_count": TEST_METHOD_BATCH_SIZE,
            },
        }
        expected_ids = [criterion.criterion_id for criterion in batch_criteria]
        return (
            f"You are a senior Unity Test Framework engineer. Create batch {batch_index + 1} of "
            f"{TEST_METHOD_BATCH_COUNT} with EXACTLY {TEST_METHOD_BATCH_SIZE} self-contained "
            "PlayMode [UnityTest] methods. Return a methods array in the required structured "
            "format. Each source_code value must contain one complete method only: no using "
            "directives, namespace, class, fields, properties, or helper methods. The host will "
            f"assemble all batches into class {checklist.test_class_name}. Each method name must "
            "start with its exact criterion_id, and every expected id must appear exactly once. "
            "Use only public APIs listed in runtime_api_contract; a missing member is nonexistent. "
            "Create the minimum deterministic objects inside each method and clean them up. Tests must "
            "assert runtime behavior, not source text. Do not use UnityEditor, file/network/process "
            "APIs, reflection to private fields, ignored tests, Assert.Pass-only tests, or waits "
            "longer than one frame. Keep setup and assertions concise to remain within the output "
            "budget. Return only the structured JSON object and no markdown.\n\n"
            f"EXPECTED_IDS={json.dumps(expected_ids, ensure_ascii=False)}\n"
            f"INPUT={json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"
        )


def create_checklist_generator_from_environment() -> DynamicFeatureChecklistGenerator:
    provider = _role_provider("feature_checklist_generation")
    client = _structured_client(
        provider,
        node_name="feature_checklist_generation",
        default_model=DEFAULT_CHECKLIST_MODEL,
    )
    return DynamicFeatureChecklistGenerator(client, provider)


def create_unity_test_generator_from_environment() -> UnityChecklistTestGenerator:
    provider = _role_provider("unity_checklist_test_generation")
    client = _structured_client(
        provider,
        node_name="unity_checklist_test_generation",
        default_model=DEFAULT_TEST_CODE_MODEL,
    )
    return UnityChecklistTestGenerator(client, provider)


def persist_generated_checklist(
    checklist: ProjectFeatureChecklist,
    *,
    workspace_root: Path,
    project_root: Path,
) -> None:
    generated_root = workspace_root / "validation" / "feature_checklists" / "generated"
    generated_root.mkdir(parents=True, exist_ok=True)
    (generated_root / "checklist.json").write_text(
        json.dumps(checklist.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (generated_root / "Checklist.md").write_text(
        _project_checklist_markdown(checklist), encoding="utf-8"
    )
    for feature_checklist in checklist.feature_checklists:
        feature_root = generated_root / _safe_path_segment(feature_checklist.feature_id)
        feature_root.mkdir(parents=True, exist_ok=True)
        (feature_root / "checklist.json").write_text(
            json.dumps(feature_checklist.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (feature_root / "Checklist.md").write_text(
            _feature_checklist_markdown(feature_checklist), encoding="utf-8"
        )

    test_root = project_root / GENERATED_TEST_DIRECTORY
    test_root.mkdir(parents=True, exist_ok=True)
    for stale in test_root.glob("GeneratedFeatureChecklist_DFC*.cs"):
        stale.unlink()
    legacy = test_root / "GeneratedFeatureChecklistTests.cs"
    if legacy.is_file():
        legacy.unlink()


def persist_generated_feature_test(
    checklist: FeatureChecklist,
    *,
    workspace_root: Path,
    project_root: Path,
    source_code: str,
) -> None:
    generated_root = workspace_root / "validation" / "feature_checklists" / "generated"
    feature_root = generated_root / _safe_path_segment(checklist.feature_id)
    feature_root.mkdir(parents=True, exist_ok=True)
    source_path = feature_root / checklist.test_filename
    source_path.write_text(source_code, encoding="utf-8")
    test_path = project_root / GENERATED_TEST_DIRECTORY / checklist.test_filename
    test_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, test_path)


def load_generated_checklist(workspace_root: Path) -> ProjectFeatureChecklist | None:
    path = workspace_root / "validation" / "feature_checklists" / "generated" / "checklist.json"
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_checklists = payload.get("feature_checklists")
    if not isinstance(raw_checklists, list):
        raise TypeError("Stored generated checklist has no feature_checklists")
    feature_checklists = tuple(
        _feature_checklist_from_dict(item, workspace_root.name) for item in raw_checklists
    )
    if not feature_checklists:
        raise ValueError("Stored generated checklist contains no feature checklists")
    return ProjectFeatureChecklist(
        checklist_version=str(payload.get("checklist_version", "1.2.0")),
        project_id=str(payload.get("project_id", workspace_root.name)),
        model_role=str(payload.get("model_role", "stored")),
        feature_checklists=feature_checklists,
    )


def _feature_checklist_from_dict(payload: object, default_project_id: str) -> FeatureChecklist:
    if not isinstance(payload, Mapping):
        raise TypeError("Stored feature checklist must be an object")
    raw_criteria = payload.get("criteria")
    if not isinstance(raw_criteria, list) or len(raw_criteria) != CHECKLIST_ITEM_COUNT:
        raise ValueError(f"Stored feature checklist must contain {CHECKLIST_ITEM_COUNT} criteria")
    criteria = tuple(
        ChecklistCriterion(
            criterion_id=str(item["criterion_id"]),
            feature_ids=tuple(str(value) for value in item["feature_ids"]),
            title=str(item["title"]),
            category=str(item["category"]),
            setup=str(item["setup"]),
            action=str(item["action"]),
            expected=str(item["expected"]),
            evidence=str(item["evidence"]),
        )
        for item in raw_criteria
        if isinstance(item, Mapping)
    )
    if len(criteria) != CHECKLIST_ITEM_COUNT:
        raise ValueError("Stored feature checklist contains invalid criteria")
    return FeatureChecklist(
        checklist_version=str(payload.get("checklist_version", "1.2.0")),
        checklist_id=str(payload["checklist_id"]),
        project_id=str(payload.get("project_id", default_project_id)),
        feature_id=str(payload["feature_id"]),
        feature_name=str(payload["feature_name"]),
        feature_description=str(payload["feature_description"]),
        feature_origin=str(payload.get("feature_origin", "user")),
        model_role=str(payload.get("model_role", "stored")),
        criteria=criteria,
    )


def _role_provider(node_name: str) -> str:
    env_name = "LLM_" + node_name.upper() + "_PROVIDER"
    configured = os.environ.get(env_name, "").strip().lower()
    return configured or resolve_feature_provider_from_environment()


def _structured_client(
    provider: str, *, node_name: str, default_model: str
) -> StructuredJsonClient:
    if provider == "local":
        return LocalAIJsonClient.from_environment(node_name=node_name, default_model=default_model)
    if provider == "openai":
        return OpenAIJsonClient.from_environment()
    if provider == "gemini":
        return GeminiApiClient.from_environment()
    raise ValueError(f"Unsupported structured checklist provider: {provider}")


def _checklist_batch_focus(batch_index: int) -> list[str]:
    focuses = (
        ["structure", "binding", "initialization", "runtime trigger", "state transition"],
        ["interaction", "edge cases", "integration", "feedback", "boundary values"],
        ["recovery", "restart", "repetition", "regression", "end-to-end consequence"],
    )
    if not 0 <= batch_index < len(focuses):
        raise ValueError("Checklist batch index is out of range")
    return focuses[batch_index]


def _criterion_fingerprint(criterion: ChecklistCriterion) -> str:
    value = f"{criterion.title} {criterion.action} {criterion.expected}".casefold()
    return re.sub(r"[^0-9a-z가-힣]+", "", value)


def _validate_criterion(
    feature_index: int,
    criterion_index: int,
    item: Mapping[str, object],
    known_feature_ids: set[str],
    target_feature_id: str,
) -> ChecklistCriterion:
    raw_ids = item.get("feature_ids")
    if not isinstance(raw_ids, list) or not raw_ids:
        raise ValueError("Checklist criterion requires feature_ids")
    feature_ids = tuple(
        dict.fromkeys(str(value).strip() for value in raw_ids if str(value).strip())
    )
    if not feature_ids or set(feature_ids) - known_feature_ids:
        raise ValueError("Checklist criterion references unknown feature ids")
    if target_feature_id not in feature_ids:
        raise ValueError(
            f"Every criterion in {target_feature_id} checklist must reference that feature"
        )
    values: dict[str, str] = {}
    for key in ("title", "category", "setup", "action", "expected", "evidence"):
        value = str(item.get(key, "")).strip()
        if not value:
            raise ValueError(f"Checklist criterion {key} must not be empty")
        values[key] = value[:600]
    if values["category"] not in {
        "structure",
        "binding",
        "runtime",
        "state",
        "interaction",
        "edge_case",
        "integration",
        "feedback",
        "recovery",
        "regression",
    }:
        raise ValueError("Checklist criterion category is invalid")
    return ChecklistCriterion(
        criterion_id=f"DFC{feature_index:03d}_{criterion_index:02d}",
        feature_ids=feature_ids,
        **values,
    )


def _validate_test_source(source: str, checklist: FeatureChecklist) -> str:
    normalized = source.strip()
    if normalized.startswith("```"):
        raise ValueError("Generated Unity test source must not contain markdown fences")
    required_tokens = (
        "namespace TeamIdle.GameTemplate.DynamicFeatureTests",
        f"class {checklist.test_class_name}",
        '[Category("FeatureChecklist")]',
        "[UnityTest]",
    )
    if any(token not in normalized for token in required_tokens):
        raise ValueError("Generated Unity test source is missing its required fixture contract")
    forbidden = (
        "UnityEditor",
        "System.IO",
        "System.Net",
        "System.Diagnostics",
        "[Ignore",
        "Assert.Pass",
        "BindingFlags.NonPublic",
    )
    if any(token in normalized for token in forbidden):
        raise ValueError("Generated Unity test source uses a forbidden API or bypass")
    method_ids = re.findall(
        r"\[UnityTest\]\s*public\s+IEnumerator\s+(DFC\d{3}_\d{2})[_A-Za-z0-9]*\s*\(",
        normalized,
    )
    expected_ids = [criterion.criterion_id for criterion in checklist.criteria]
    if method_ids != expected_ids:
        raise ValueError(
            "Generated Unity test methods must implement the feature checklist ids in order"
        )
    return normalized + "\n"


def _validate_test_method_source(source: str, criterion_id: str) -> str:
    normalized = source.strip()
    if normalized.startswith("```"):
        raise ValueError("Generated Unity test method must not contain markdown fences")
    forbidden = (
        "UnityEditor",
        "System.IO",
        "System.Net",
        "System.Diagnostics",
        "[Ignore",
        "Assert.Pass",
        "BindingFlags.NonPublic",
        "namespace ",
        " class ",
        "using ",
    )
    padded = f" {normalized} "
    if any(token in padded for token in forbidden):
        raise ValueError("Generated Unity test method uses a forbidden API or declaration")
    method_ids = re.findall(
        r"\[UnityTest\]\s*public\s+IEnumerator\s+(DFC\d{3}_\d{2})[_A-Za-z0-9]*\s*\(",
        normalized,
    )
    if method_ids != [criterion_id]:
        raise ValueError(
            f"Generated Unity test method must implement only {criterion_id}; got {method_ids}"
        )
    return normalized


def _assemble_test_source(checklist: FeatureChecklist, methods: list[str]) -> str:
    if len(methods) != CHECKLIST_ITEM_COUNT:
        raise ValueError(
            f"Unity checklist fixture requires {CHECKLIST_ITEM_COUNT} generated methods"
        )
    members = "\n\n".join(textwrap.indent(method, "        ") for method in methods)
    return (
        "using NUnit.Framework;\n"
        "using System.Collections;\n"
        "using UnityEngine;\n"
        "using UnityEngine.TestTools;\n\n"
        "namespace TeamIdle.GameTemplate.DynamicFeatureTests\n"
        "{\n"
        '    [Category("FeatureChecklist")]\n'
        f"    public class {checklist.test_class_name}\n"
        "    {\n"
        f"{members}\n"
        "    }\n"
        "}\n"
    )


def _existing_checklist_catalog(source_root: Path) -> list[dict[str, object]]:
    catalog: list[dict[str, object]] = []
    if not source_root.is_dir():
        return catalog
    for path in sorted(source_root.glob("*Validator Checklist*.md")):
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        items = [line.strip()[6:].strip() for line in lines if line.strip().startswith("- [ ]")]
        catalog.append({"name": path.stem, "sample_items": items[:6]})
    return catalog


def _runtime_api_context(project_root: Path, checklist: FeatureChecklist) -> dict[str, Any]:
    """Retrieve exact public signatures instead of serializing tens of thousands of source chars."""

    assets_root = project_root / "Assets"
    if not assets_root.is_dir():
        return {
            "index_version": "unavailable",
            "available_modules": {},
            "retrieved_module_ids": [],
            "project_types": {},
            "rules": ["Use only standard Unity 2D and NUnit public APIs."],
        }
    index = build_project_context_index(assets_root)
    module_types = index.get("module_types", {})
    selected_module_ids = (
        [str(module_id) for module_id in module_types] if isinstance(module_types, Mapping) else []
    )
    requirement_text = " ".join(
        [
            checklist.feature_name,
            checklist.feature_description,
            *(
                f"{criterion.title} {criterion.action} {criterion.expected}"
                for criterion in checklist.criteria
            ),
        ]
    )
    return retrieve_prompt_api_contract(
        index,
        selected_module_ids=selected_module_ids,
        requirement_text=requirement_text,
        max_module_types=8,
        max_dependency_types=8,
    )


def _safe_path_segment(value: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z._-]+", "_", value).strip("._")
    if not normalized:
        raise ValueError("Feature id cannot be converted to a safe path")
    return normalized


def _feature_checklist_markdown(checklist: FeatureChecklist) -> str:
    lines = [
        f"# {checklist.feature_name} | 동적 Feature Checklist",
        "",
        f"- 프로젝트 ID: `{checklist.project_id}`",
        f"- Feature ID: `{checklist.feature_id}`",
        f"- Feature 설명: {checklist.feature_description}",
        f"- 항목 수: {len(checklist.criteria)}",
        "",
    ]
    for item in checklist.criteria:
        lines.extend(
            [
                f"- [ ] **{item.criterion_id} {item.title}**",
                f"  - 관련 Feature: {', '.join(item.feature_ids)}",
                f"  - 준비: {item.setup}",
                f"  - 실행: {item.action}",
                f"  - 기대: {item.expected}",
                f"  - 증거: {item.evidence}",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _project_checklist_markdown(checklist: ProjectFeatureChecklist) -> str:
    lines = [
        "# 프로젝트 Feature Checklist 목록",
        "",
        f"- 프로젝트 ID: `{checklist.project_id}`",
        f"- Feature Checklist 수: {len(checklist.feature_checklists)}",
        f"- Checklist당 항목 수: {CHECKLIST_ITEM_COUNT}",
        f"- 전체 검증 항목 수: {len(checklist.criteria)}",
        "",
    ]
    lines.extend(
        f"- `{item.feature_id}` {item.feature_name}: "
        f"`{_safe_path_segment(item.feature_id)}/Checklist.md`"
        for item in checklist.feature_checklists
    )
    return "\n".join(lines).rstrip() + "\n"
