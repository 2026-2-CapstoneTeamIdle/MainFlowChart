"""LLM-assisted decomposition of a user condition into atomic game features."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from game_pipeline.gemini_feature_generator import (
    GeminiApiClient,
    LocalAIJsonClient,
    OpenAIJsonClient,
    StructuredJsonClient,
    resolve_feature_provider_from_environment,
)
from mainflow.contracts import FeatureRequirement, GameGenre, Viewpoint

DEFAULT_CONDITION_FEATURE_MODEL = "gemma4-12b-it-qat-q4-0"
MAX_EXPLICIT_FEATURES = 20
MAX_FEATURES_PER_REQUEST = 6

CONDITION_FEATURE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["features"],
    "properties": {
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
                    "implementation_kind",
                ],
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "source_text": {"type": "string"},
                    "acceptance_criteria": {"type": "string"},
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
        }
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
            feature for feature in detected_features if feature["name"] != "사용자 지정 조건"
        ]
        fingerprints = {
            _fingerprint(feature["name"], feature["description"]) for feature in known_features
        }
        accepted: list[FeatureRequirement] = []
        rejected: list[dict[str, str]] = []
        condition_segments = _split_condition(condition)
        for segment_index, segment in enumerate(condition_segments, start=1):
            response = self.client.generate_json(
                self._prompt(
                    genre,
                    viewpoint,
                    condition,
                    segment,
                    segment_index,
                    len(condition_segments),
                    detected_features,
                ),
                CONDITION_FEATURE_SCHEMA,
            )
            raw_features = response.get("features")
            if not isinstance(raw_features, list):
                raise TypeError("Condition feature analysis must return a features array")
            for item in raw_features[:MAX_FEATURES_PER_REQUEST]:
                if len(accepted) >= MAX_EXPLICIT_FEATURES:
                    break
                if not isinstance(item, Mapping):
                    continue
                try:
                    validated = _validate_feature(item, condition)
                except ValueError as error:
                    rejected.append({"reason": str(error), "value": str(dict(item))[:500]})
                    continue
                fingerprint = _fingerprint(validated["name"], validated["description"])
                if fingerprint in fingerprints or any(
                    _overlaps(validated, feature) for feature in [*known_features, *accepted]
                ):
                    rejected.append({"reason": "duplicate", "value": validated["name"]})
                    continue
                fingerprints.add(fingerprint)
                accepted.append(
                    {
                        "feature_id": f"user-feature-{len(accepted) + 1:02d}",
                        "name": validated["name"],
                        "description": validated["description"],
                        "source_text": validated["source_text"],
                        "origin": "user",
                        "rationale": "사용자 Condition에서 명시적으로 추출한 기능",
                        "acceptance_criteria": validated["acceptance_criteria"],
                        "implementation_kind": validated["implementation_kind"],
                    }
                )

        features = [*known_features, *accepted]
        if not features:
            raise ValueError("Condition feature analysis produced no usable feature")
        return ConditionFeatureAnalysis(
            features=features,
            report={
                "provider": self.provider,
                "model_role": "condition_feature_analysis",
                "detected_feature_count": len(detected_features),
                "explicit_feature_count": len(features),
                "added_feature_count": len(accepted),
                "request_count": len(condition_segments),
                "request_segments": condition_segments,
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
            "condition_segment while using full_condition for context. Decompose EVERY "
            "explicitly requested behavior, object, interaction, rule, success condition, and "
            "failure condition in the user's condition into atomic implementable features. Do "
            "not add prerequisites or genre defaults in this stage; a separate closure stage "
            "does that. Do not collapse a compound sentence into one vague custom feature. Each "
            "feature must describe one runtime behavior and have an observable Unity Play Mode "
            "acceptance criterion. Preserve concrete qualifiers such as all items, patrol, "
            "checkpoint, unlock-on-button, destination, input key, direction count, and resource "
            f"cost. Return no more than {MAX_FEATURES_PER_REQUEST} atomic features for this "
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


def create_condition_feature_analyzer_from_environment() -> ConditionFeatureAnalyzer | None:
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
        "MAINFLOW_CONDITION_FEATURE_PROVIDER must be 'openai', 'local', 'gemini', or 'off'"
    )


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
        result["source_text"] = condition
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
