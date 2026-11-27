"""LLM-assisted decomposition of a user condition into atomic game features."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from game_pipeline.gemini_feature_generator import (
    GeminiApiClient,
    LocalAIJsonClient,
    OpenAIJsonClient,
    StructuredJsonClient,
    resolve_feature_provider_from_environment,
)
from game_pipeline.codex_cli.structured_json_client import CodexStructuredJsonClient
from mainflow.contracts import FeatureRequirement, GameGenre, Viewpoint

DEFAULT_CONDITION_FEATURE_MODEL = "gemma4-12b-it-qat-q4-0"
MAX_EXPLICIT_FEATURES = 20
MAX_FEATURES_PER_REQUEST = 4
CODEX_MAX_EXPLICIT_FEATURES = 60
CODEX_SEGMENTS_PER_REQUEST = 4
CODEX_MAX_FEATURES_PER_REQUEST = 4

CONDITION_FEATURE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["features", "project_name"],
    "properties": {
        "project_name": {"type": "string"},
        "features": {
            "type": "array",
            "minItems": 1,
            "maxItems": MAX_FEATURES_PER_REQUEST,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "name",
                    "description",
                    "source_text",
                    "acceptance_criteria",
                    "acceptance_items",
                    "implementation_kind",
                ],
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "source_text": {"type": "string"},
                    "acceptance_criteria": {"type": "string"},
                    "acceptance_items": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 24,
                        "items": {"type": "string"},
                    },
                    "implementation_kind": {
                        "type": "string",
                        "enum": [
                            "reuse_module",
                            "configure_existing",
                            "scene_binding",
                            "design_constraint",
                            "generate_code",
                        ],
                    },
                },
            },
        },
    },
}


@dataclass(frozen=True)
class ConditionFeatureAnalysis:
    features: list[FeatureRequirement]
    report: dict[str, Any]


class ConditionFeatureAnalyzer:
    """Split every explicit user request into an implementable atomic feature."""

    def __init__(self, client: StructuredJsonClient, provider: str) -> None:
        self.client = client
        self.provider = provider

    def analyze(
        self,
        *,
        genre: GameGenre,
        viewpoint: Viewpoint,
        condition: str,
        detected_features: list[FeatureRequirement],
    ) -> ConditionFeatureAnalysis:
        known_features = [
            dict(feature) for feature in detected_features if feature["name"] != "사용자 지정 조건"
        ]
        accepted: list[FeatureRequirement] = []
        merged_feature_count = 0
        rejected: list[dict[str, str]] = []
        failed_segments: list[dict[str, object]] = []
        truncated_segments: list[dict[str, object]] = []
        condition_segments = _split_condition(condition)
        project_name = ""
        if self.provider == "codex_cli":
            request_segments = [
                "\n".join(condition_segments[index : index + CODEX_SEGMENTS_PER_REQUEST])
                for index in range(0, len(condition_segments), CODEX_SEGMENTS_PER_REQUEST)
            ]
            feature_limit = CODEX_MAX_EXPLICIT_FEATURES
            request_feature_limit = CODEX_MAX_FEATURES_PER_REQUEST
            schema = {
                **CONDITION_FEATURE_SCHEMA,
                "properties": {
                    **CONDITION_FEATURE_SCHEMA["properties"],
                    "features": {
                        **CONDITION_FEATURE_SCHEMA["properties"]["features"],
                        "maxItems": request_feature_limit,
                    },
                },
            }
        else:
            request_segments = condition_segments
            feature_limit = MAX_EXPLICIT_FEATURES
            request_feature_limit = MAX_FEATURES_PER_REQUEST
            schema = CONDITION_FEATURE_SCHEMA
        for segment_index, segment in enumerate(request_segments, start=1):
            if len(accepted) >= feature_limit:
                truncated_segments.append({"segment_index": segment_index, "segment": segment})
                continue
            try:
                response = self.client.generate_json(
                    self._prompt(
                        genre,
                        viewpoint,
                        condition,
                        segment,
                        segment_index,
                        len(request_segments),
                        detected_features,
                        request_feature_limit,
                    ),
                    schema,
                )
            except (RuntimeError, TypeError, ValueError) as error:
                failed_segments.append(
                    {
                        "segment_index": segment_index,
                        "segment": segment,
                        "error": f"{type(error).__name__}: {error}",
                    }
                )
                continue
            proposed_name = response.get("project_name")
            if not project_name and isinstance(proposed_name, str):
                project_name = " ".join(proposed_name.split())[:50]
            raw_features = response.get("features")
            if not isinstance(raw_features, list):
                raise TypeError("Condition feature analysis must return a features array")
            if raw_features and all(
                isinstance(item, Mapping) and isinstance(item.get("acceptance_items"), list)
                for item in raw_features
            ):
                item_count = sum(len(item["acceptance_items"]) for item in raw_features)
                if item_count < len(_split_condition(segment)):
                    failed_segments.append(
                        {
                            "segment_index": segment_index,
                            "segment": segment,
                            "error": "Grouped features have fewer acceptance items than source clauses",
                        }
                    )
                    continue
            for item in raw_features[:request_feature_limit]:
                if len(accepted) >= feature_limit:
                    truncated_segments.append({"segment_index": segment_index, "segment": segment})
                    break
                if not isinstance(item, Mapping):
                    continue
                try:
                    validated = _validate_feature(item, segment)
                except ValueError as error:
                    rejected.append({"reason": str(error), "value": str(dict(item))[:500]})
                    continue
                acceptance_items = _acceptance_items(item, validated)
                fingerprint = _fingerprint(validated["name"], validated["description"])
                match = next(
                    (
                        feature
                        for feature in [*known_features, *accepted]
                        if _fingerprint(feature["name"], feature["description"]) == fingerprint
                        or _overlaps(validated, feature)
                    ),
                    None,
                )
                if match is not None:
                    merged_items = list(
                        dict.fromkeys([*match.get("acceptance_items", []), *acceptance_items])
                    )
                    if len(merged_items) > 24:
                        match = None
                if match is not None:
                    match["acceptance_items"] = merged_items
                    if len(acceptance_items) > 1 and match in known_features:
                        match["name"] = validated["name"]
                        match["description"] = validated["description"]
                        match["acceptance_criteria"] = validated["acceptance_criteria"]
                    merged_feature_count += 1
                    continue
                accepted.append(
                    {
                        "feature_id": f"user-feature-{len(accepted) + 1:02d}",
                        "name": validated["name"],
                        "description": validated["description"],
                        "source_text": validated["source_text"],
                        "origin": "user",
                        "rationale": "사용자 Condition에서 명시적으로 추출한 기능",
                        "acceptance_criteria": validated["acceptance_criteria"],
                        "acceptance_items": acceptance_items,
                        "implementation_kind": validated["implementation_kind"],
                    }
                )

        fallback_segments = [
            str(item["segment"]) for item in [*failed_segments, *truncated_segments]
        ]
        fallback_features = _fallback_custom_features(detected_features, fallback_segments)
        features = [*known_features, *accepted, *fallback_features]
        if not features:
            raise ValueError("Condition feature analysis produced no usable feature")
        return ConditionFeatureAnalysis(
            features=features,
            report={
                "provider": self.provider,
                "project_name": project_name,
                "model_role": "condition_feature_analysis",
                "detected_feature_count": len(detected_features),
                "explicit_feature_count": len(features),
                "added_feature_count": len(accepted),
                "merged_feature_count": merged_feature_count,
                "acceptance_item_count": sum(
                    len(feature.get("acceptance_items") or [feature["description"]])
                    for feature in features
                ),
                "request_count": len(request_segments),
                "successful_request_count": (
                    len(request_segments) - len(failed_segments) - len(truncated_segments)
                ),
                "failed_request_count": len(failed_segments),
                "failed_segments": failed_segments,
                "truncated_segment_count": len(truncated_segments),
                "truncated_segments": truncated_segments,
                "retained_fallback_feature_count": len(fallback_features),
                "request_segments": request_segments,
                "features": [
                    {
                        "feature_id": feature["feature_id"],
                        "name": feature["name"],
                        "acceptance_criteria": feature.get("acceptance_criteria", ""),
                    }
                    for feature in features
                ],
                "rejected": rejected,
            },
        )

    @staticmethod
    def _prompt(
        genre: GameGenre,
        viewpoint: Viewpoint,
        full_condition: str,
        condition_segment: str,
        segment_index: int,
        segment_count: int,
        detected_features: list[FeatureRequirement],
        request_feature_limit: int = MAX_FEATURES_PER_REQUEST,
    ) -> str:
        payload = {
            "genre": genre,
            "viewpoint": viewpoint,
            "full_condition": full_condition,
            "condition_segment": condition_segment,
            "segment_index": segment_index,
            "segment_count": segment_count,
            "deterministically_detected_features": detected_features,
        }
        return (
            "You are the requirements parser for a Unity game generator. Analyze only "
            "the current segment for features, and also propose a short memorable Korean game "
            "title (2–20 characters) in project_name using the ENTIRE full_condition. "
            "Return the title alongside features; do not add naming as a gameplay feature. Analyze only "
            "condition_segment while using full_condition for context. Decompose EVERY "
            "explicitly requested behavior, object, interaction, rule, success condition, and "
            "failure condition in the user's condition. Group clauses that share one runtime "
            "system into a coherent implementable feature, and put EVERY observable rule, "
            "numeric threshold, and exclusion in that feature's acceptance_items array. "
            "Explicit exclusions and negative capabilities are binding requirements. Never emit "
            "the positive opposite of phrases such as 'cannot attack', 'has no attack', or 'must "
            "not use'. Do "
            "not add prerequisites or genre defaults in this stage; a separate closure stage "
            "does that. Do not merge unrelated systems or replace specific rules with a vague "
            "custom feature. Preserve every clause even when there are more clauses than features. "
            "Each feature must name a connected runtime system and have a short summary in "
            "acceptance_criteria; acceptance_items contain its distinct observable Unity Play "
            "Mode checks. Keep name under 30 characters and description, source_text, and "
            "acceptance_criteria under 160 characters each. Preserve concrete "
            "qualifiers such as all items, patrol, "
            "checkpoint, unlock-on-button, destination, input key, direction count, and resource "
            f"cost. Return no more than {request_feature_limit} grouped features for this "
            "segment. Choose generate_code only when the behavior is not represented by a detected "
            "feature; use scene_binding/configure_existing when wiring or data is sufficient. "
            "Return strict JSON only.\n\n"
            f"INPUT={json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"
        )


def _split_condition(condition: str) -> list[str]:
    """Split long user input into bounded semantic requests without losing original text."""

    sentences = [
        value.strip(" \t\r\n.,!?。！？")
        for value in re.split(r"(?<=[.!?。！？])\s+|[\r\n]+", condition)
        if value.strip(" \t\r\n.,!?。！？")
    ]
    if not sentences:
        return [condition.strip()]
    segments: list[str] = []
    for sentence in sentences:
        if len(sentence) <= 240:
            segments.append(sentence)
            continue
        clauses = [
            clause.strip() for clause in re.split(r"\s*[,;；]\s*", sentence) if clause.strip()
        ]
        if len(clauses) == 1:
            segments.extend(sentence[index : index + 240] for index in range(0, len(sentence), 240))
            continue
        current = ""
        for clause in clauses:
            candidate = f"{current}, {clause}" if current else clause
            if current and len(candidate) > 240:
                segments.append(current)
                current = clause
            else:
                current = candidate
        if current:
            segments.append(current)
    return segments


def create_condition_feature_analyzer_from_environment(
    project_root: Path | None = None,
) -> ConditionFeatureAnalyzer | None:
    configured = os.environ.get("MAINFLOW_CONDITION_FEATURE_PROVIDER", "").strip().lower()
    if configured in {"off", "none", "disabled", "deterministic"}:
        return None
    inherited = (
        os.environ.get("MAINFLOW_GENRE_FEATURE_PROVIDER", "").strip().lower()
        or os.environ.get("MAINFLOW_FEATURE_PROVIDER", "").strip().lower()
    )
    if not configured and not inherited and not os.environ.get("OPENAI_API_KEY", "").strip():
        return None
    provider = configured or inherited or resolve_feature_provider_from_environment()
    if provider in {"codex", "codex_cli"}:
        if project_root is None:
            raise ValueError("Codex Condition analysis requires a project root")
        return ConditionFeatureAnalyzer(
            CodexStructuredJsonClient(
                project_root, "condition_feature_analysis", "LLM_CONDITION_FEATURE_ANALYSIS_MODEL"
            ),
            "codex_cli",
        )
    if provider == "local":
        client = LocalAIJsonClient.from_environment(
            node_name="condition_feature_analysis",
            default_model=DEFAULT_CONDITION_FEATURE_MODEL,
        )
        return ConditionFeatureAnalyzer(client, provider)
    if provider == "openai":
        return ConditionFeatureAnalyzer(
            OpenAIJsonClient.from_environment(
                node_name="condition_feature_analysis",
            ),
            provider,
        )
    if provider == "gemini":
        return ConditionFeatureAnalyzer(
            GeminiApiClient.from_environment(
                node_name="condition_feature_analysis",
            ),
            provider,
        )
    raise ValueError(
        "MAINFLOW_CONDITION_FEATURE_PROVIDER must be 'codex_cli', 'openai', 'local', 'gemini', or 'off'"
    )


def _fallback_custom_features(
    detected_features: list[FeatureRequirement], segments: list[str]
) -> list[FeatureRequirement]:
    """Retain original clauses that the bounded AI pass could not finish."""

    fallback: list[FeatureRequirement] = []
    for segment in segments:
        normalized_segment = _normalize(segment)
        matches = [
            feature
            for feature in detected_features
            if feature["name"] == "사용자 지정 조건"
            and (
                _normalize(feature["description"]) in normalized_segment
                or normalized_segment in _normalize(feature["description"])
            )
        ]
        if matches:
            fallback.extend(feature for feature in matches if feature not in fallback)
            continue
        fallback.append(
            {
                "feature_id": f"user-fallback-{len(fallback) + 1:02d}",
                "name": "사용자 지정 조건",
                "description": segment,
                "source_text": segment,
            }
        )
    return fallback


def _validate_feature(item: Mapping[str, object], condition: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, minimum, maximum in (
        ("name", 2, 60),
        ("description", 8, 320),
        ("source_text", 2, 320),
        ("acceptance_criteria", 8, 420),
    ):
        value = str(item.get(key, "")).strip()
        if not minimum <= len(value) <= maximum:
            raise ValueError(f"Condition feature {key} length is invalid")
        result[key] = value
    if _normalize(result["source_text"]) not in _normalize(condition):
        result["source_text"] = condition[:320]
    implementation_kind = str(item.get("implementation_kind", "")).strip()
    if implementation_kind not in {
        "reuse_module",
        "configure_existing",
        "scene_binding",
        "design_constraint",
        "generate_code",
    }:
        raise ValueError("Condition feature implementation_kind is invalid")
    result["implementation_kind"] = implementation_kind
    return result


def _acceptance_items(item: Mapping[str, object], validated: Mapping[str, str]) -> list[str]:
    raw_items = item.get("acceptance_items")
    if not isinstance(raw_items, list) or not raw_items:
        return [validated["acceptance_criteria"]]
    items = list(
        dict.fromkeys(
            value.strip() for value in raw_items if isinstance(value, str) and value.strip()
        )
    )
    if not items or len(items) > 24 or any(len(value) > 320 for value in items):
        raise ValueError("Condition feature acceptance_items are invalid")
    return items


def _normalize(value: str) -> str:
    return re.sub(r"[^0-9a-zA-Z가-힣]+", "", value).casefold()


def _fingerprint(name: str, description: str) -> str:
    return f"{_normalize(name)}:{_normalize(description)}"


def _overlaps(candidate: Mapping[str, str], existing: FeatureRequirement) -> bool:
    candidate_name = _normalize(candidate["name"])
    existing_name = _normalize(existing["name"])
    if candidate_name == existing_name:
        return True
    left = _normalize(candidate["description"])
    right = _normalize(existing["description"])
    shorter, longer = sorted((left, right), key=len)
    return len(shorter) >= 12 and shorter in longer
