"""Infer genre-essential gameplay features before detailed game design begins."""

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

MAX_INFERRED_FEATURES = 30
MAX_INFERRED_FEATURES_PER_REQUEST = 5
FEATURES_PER_DEPENDENCY_REQUEST = 3
DEFAULT_CONDITION_FEATURE_MODEL = "gemma4-12b-it-qat-q4-0"

GENRE_FEATURE_ENRICHMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["features"],
    "properties": {
        "features": {
            "type": "array",
            "maxItems": MAX_INFERRED_FEATURES_PER_REQUEST,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "name",
                    "description",
                    "rationale",
                    "acceptance_criteria",
                    "checklist",
                    "closure_kind",
                    "supports_feature_ids",
                    "dependency_role",
                    "implementation_kind",
                    "target_mechanics",
                ],
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "rationale": {"type": "string"},
                    "acceptance_criteria": {"type": "string"},
                    "checklist": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "preconditions",
                            "steps",
                            "expected_results",
                            "failure_signals",
                        ],
                        "properties": {
                            "preconditions": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 3,
                                "items": {"type": "string"},
                            },
                            "steps": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 3,
                                "items": {"type": "string"},
                            },
                            "expected_results": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 3,
                                "items": {"type": "string"},
                            },
                            "failure_signals": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 3,
                                "items": {"type": "string"},
                            },
                        },
                    },
                    "closure_kind": {
                        "type": "string",
                        "enum": [
                            "user_requirement_dependency",
                            "genre_core_requirement",
                        ],
                    },
                    "supports_feature_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 8,
                    },
                    "dependency_role": {
                        "type": "string",
                        "enum": [
                            "prerequisite_state",
                            "required_actor",
                            "runtime_binding",
                            "interaction_consequence",
                            "player_feedback",
                            "failure_recovery",
                            "genre_core",
                        ],
                    },
                    "implementation_kind": {
                        "type": "string",
                        "enum": [
                            "reuse_module",
                            "configure_existing",
                            "scene_binding",
                            "design_constraint",
                            "generate_code",
                            "validation_only",
                        ],
                    },
                    "target_mechanics": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 8,
                    },
                },
            },
        }
    },
}


@dataclass(frozen=True)
class GenreFeatureEnrichment:
    features: list[FeatureRequirement]
    report: dict[str, Any]


class GenreFeatureEnricher:
    """Ask an LLM for the minimum missing feature closure of a playable genre game."""

    def __init__(self, client: StructuredJsonClient, provider: str) -> None:
        self.client = client
        self.provider = provider

    def enrich(
        self,
        *,
        genre: GameGenre,
        viewpoint: Viewpoint,
        user_condition: str,
        core_loop: str,
        existing_features: list[FeatureRequirement],
        baseline_contract: Mapping[str, object] | None = None,
    ) -> GenreFeatureEnrichment:
        baseline_contract = baseline_contract or {}
        requests: list[tuple[str, set[str], list[FeatureRequirement]]] = []
        for index in range(0, len(existing_features), FEATURES_PER_DEPENDENCY_REQUEST):
            target_features = existing_features[index : index + FEATURES_PER_DEPENDENCY_REQUEST]
            requests.append(
                (
                    "user_requirement_dependency",
                    {feature["feature_id"] for feature in target_features},
                    target_features,
                )
            )
        requests.append(("genre_core_requirement", set(), existing_features))

        known = {
            _feature_fingerprint(feature["name"], feature["description"])
            for feature in existing_features
        }
        inferred: list[FeatureRequirement] = []
        existing_feature_ids = {feature["feature_id"] for feature in existing_features}
        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        failed_requests: list[dict[str, object]] = []
        successful_request_count = 0
        for request_index, (scope, target_feature_ids, target_features) in enumerate(
            requests, start=1
        ):
            try:
                response = self.client.generate_json(
                    self._prompt(
                        genre=genre,
                        viewpoint=viewpoint,
                        user_condition=user_condition,
                        core_loop=core_loop,
                        existing_features=existing_features,
                        target_features=target_features,
                        closure_scope=scope,
                        baseline_contract=baseline_contract,
                    ),
                    GENRE_FEATURE_ENRICHMENT_SCHEMA,
                )
            except (RuntimeError, TypeError, ValueError) as error:
                failed_requests.append(
                    {
                        "request_index": request_index,
                        "scope": scope,
                        "target_feature_ids": sorted(target_feature_ids),
                        "error": f"{type(error).__name__}: {error}",
                    }
                )
                continue
            successful_request_count += 1
            raw_features = response.get("features")
            if not isinstance(raw_features, list):
                raise TypeError("Genre feature enrichment must return a features array")
            for item in raw_features[:MAX_INFERRED_FEATURES_PER_REQUEST]:
                if len(inferred) >= MAX_INFERRED_FEATURES:
                    break
                if not isinstance(item, Mapping):
                    continue
                try:
                    suggestion = _validated_suggestion(item, existing_feature_ids)
                except ValueError as error:
                    rejected.append(
                        {
                            "name": str(item.get("name", "invalid"))[:60],
                            "description": str(item.get("description", ""))[:320],
                            "rationale": str(item.get("rationale", ""))[:320],
                            "acceptance_criteria": str(item.get("acceptance_criteria", ""))[:420],
                            "rejection": str(error),
                        }
                    )
                    continue
                if suggestion["closure_kind"] != scope or (
                    scope == "user_requirement_dependency"
                    and not set(suggestion["supports_feature_ids"]) & target_feature_ids
                ):
                    rejected.append({**suggestion, "rejection": "wrong_request_scope"})
                    continue
                if suggestion["implementation_kind"] != "generate_code":
                    available_mechanics = {
                        str(value)
                        for value in baseline_contract.get("mechanics", [])
                        if isinstance(value, str)
                    }
                    suggestion["target_mechanics"] = [
                        mechanic
                        for mechanic in suggestion["target_mechanics"]
                        if mechanic in available_mechanics
                    ]
                fingerprint = _feature_fingerprint(suggestion["name"], suggestion["description"])
                if (
                    fingerprint in known
                    or any(
                        _semantically_overlaps(suggestion, feature)
                        for feature in [*existing_features, *inferred]
                    )
                    or (
                        suggestion["closure_kind"] == "genre_core_requirement"
                        and _covered_by_baseline(suggestion, baseline_contract)
                    )
                ):
                    rejected.append({**suggestion, "rejection": "duplicate_or_already_covered"})
                    continue
                known.add(fingerprint)
                inferred_index = len(inferred) + 1
                is_dependency = suggestion["closure_kind"] == "user_requirement_dependency"
                id_prefix = "requirement-dependency" if is_dependency else "genre-required"
                inferred.append(
                    {
                        "feature_id": f"{id_prefix}-{inferred_index:02d}",
                        "name": suggestion["name"],
                        "description": suggestion["description"],
                        "source_text": (
                            f"{'사용자 요구 의존 기능' if is_dependency else '장르 필수 기능'} 추론: "
                            f"{suggestion['rationale']} "
                            f"검증 기준: {suggestion['acceptance_criteria']}"
                        ),
                        "origin": ("requirement_dependency" if is_dependency else "genre_inferred"),
                        "rationale": suggestion["rationale"],
                        "acceptance_criteria": suggestion["acceptance_criteria"],
                        "checklist": suggestion["checklist"],
                        "supports_feature_ids": suggestion["supports_feature_ids"],
                        "dependency_role": suggestion["dependency_role"],
                        "implementation_kind": suggestion["implementation_kind"],
                        "target_mechanics": suggestion["target_mechanics"],
                    }
                )
                accepted.append(suggestion)

        return GenreFeatureEnrichment(
            features=[*existing_features, *inferred],
            report={
                "provider": self.provider,
                "genre": genre,
                "viewpoint": viewpoint,
                "input_feature_count": len(existing_features),
                "input_features": [
                    {
                        "feature_id": feature["feature_id"],
                        "name": feature["name"],
                        "description": feature["description"],
                    }
                    for feature in existing_features
                ],
                "added_feature_count": len(inferred),
                "request_count": len(requests),
                "successful_request_count": successful_request_count,
                "failed_request_count": len(failed_requests),
                "failed_requests": failed_requests,
                "dependency_feature_count": sum(
                    feature.get("origin") == "requirement_dependency" for feature in inferred
                ),
                "genre_feature_count": sum(
                    feature.get("origin") == "genre_inferred" for feature in inferred
                ),
                "added_features": accepted,
                "rejected_features": rejected,
            },
        )

    @staticmethod
    def _prompt(
        *,
        genre: GameGenre,
        viewpoint: Viewpoint,
        user_condition: str,
        core_loop: str,
        existing_features: list[FeatureRequirement],
        target_features: list[FeatureRequirement],
        closure_scope: str,
        baseline_contract: Mapping[str, object],
    ) -> str:
        payload = {
            "genre": genre,
            "viewpoint": viewpoint,
            "user_condition": user_condition,
            "core_loop": core_loop,
            "already_required_features": [
                {
                    "feature_id": feature["feature_id"],
                    "name": feature["name"],
                    "description": feature["description"],
                    "origin": feature.get("origin", "user"),
                }
                for feature in existing_features
            ],
            "target_features_for_this_request": [
                {
                    "feature_id": feature["feature_id"],
                    "name": feature["name"],
                    "description": feature["description"],
                }
                for feature in target_features
            ],
            "closure_scope": closure_scope,
            "already_implemented_genre_baseline": baseline_contract,
        }
        scope_instruction = (
            "Inspect each target feature independently and derive only the minimum functional "
            "closure needed to make that exact feature work end to end. Mark every result as "
            "user_requirement_dependency and reference at least one target feature id. Reason "
            "through prerequisite state, required actors or data, runtime binding and trigger, "
            "observable consequence, player feedback, and failure or recovery flow."
            if closure_scope == "user_requirement_dependency"
            else "Infer only the additional features this genre unconditionally needs to become "
            "a playable game rather than a disconnected simulation. Mark every result as "
            "genre_core_requirement, use dependency_role genre_core, and leave "
            "supports_feature_ids empty. Cover missing control, valid initial state, challenge, "
            "survival or resource feedback, progression, and reachable win/loss/restart flow."
        )
        return (
            "You are a senior game systems designer performing requirement closure before "
            "detailed Unity design. This is one bounded request in a multi-request analysis. "
            "Produce only the closure_kind named by closure_scope and return no more than "
            f"{MAX_INFERRED_FEATURES_PER_REQUEST} features. {scope_instruction} "
            "Do not merely paraphrase the requested behavior. For example, an "
            "orbiting weapon request needs a damageable enemy, collision-to-damage connection, "
            "enemy death consequence, visible hit feedback, and any promised reward delivery; an "
            "upgrade request needs selectable choices wired to the actual runtime stat plus an "
            "observable before/after change. A requested mechanic must have every prerequisite "
            "and observable consequence needed to work. "
            "Explicit user exclusions override genre conventions and baseline capabilities. "
            "Never infer, require, or restore a capability the user prohibited; preserve the "
            "negative requirement as a design constraint instead. "
            "The implemented genre baseline is existing capability, not a wishlist: do not "
            "regenerate it. Add only behavioral closure absent from both the explicit "
            "requirements and that baseline. Do not repeat or paraphrase an existing feature. "
            "Do not add optional polish, lore, "
            "monetization, networking, achievements, or unrelated scope. Each description must be "
            "one concrete executable behavior, and each acceptance criterion must be observable in "
            "Unity Play Mode. Keep name under 30 characters and description, rationale, and "
            "acceptance_criteria under 180 characters each. Do not explain reasoning outside "
            "those fields. For every inferred feature, write a concrete checklist that can be "
            "followed after Unity compilation. Use at most three short entries in each checklist "
            "array: preconditions establish the actor and initial state, "
            "steps describe input or elapsed-time actions, expected_results contain observable "
            "state/UI/scene changes, and failure_signals identify disconnected or no-op behavior. "
            "Do not use vague entries such as 'works correctly'. Classify implementation_kind "
            "carefully: reuse_module selects a "
            "listed baseline mechanic, configure_existing changes its data/tuning, scene_binding "
            "connects existing systems to scene or UI, design_constraint belongs in design data, "
            "validation_only is an invariant/test, and generate_code is reserved for genuinely "
            "absent runtime behavior. Put applicable baseline mechanic ids in target_mechanics; "
            "do not request new code merely to express a value, HUD binding, reset rule, or test. "
            "dependency_role must describe the primary role and genre-only additions must use "
            "genre_core with an empty supports_feature_ids array. A user dependency must reference "
            "at least one supplied feature_id and must not use genre_core. Return an empty array "
            "only if every explicit feature has complete functional closure and the listed "
            "requirements already close a "
            "complete genre core loop. Return only the JSON object required by the schema.\n\n"
            f"REQUIREMENT_INPUT={json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"
        )


def create_genre_feature_enricher_from_environment() -> GenreFeatureEnricher | None:
    """Use the code-generation provider unless this optional stage is disabled."""

    configured = os.environ.get("MAINFLOW_GENRE_FEATURE_PROVIDER", "").strip().lower()
    if configured in {"off", "none", "disabled", "deterministic"}:
        return None
    inherited = os.environ.get("MAINFLOW_FEATURE_PROVIDER", "").strip().lower()
    if not configured and not inherited and not os.environ.get("OPENAI_API_KEY", "").strip():
        # Offline/default test runs must not unexpectedly connect to a local server. An
        # explicitly selected LocalAI/Gemini provider still enables this stage.
        return None
    provider = configured or resolve_feature_provider_from_environment()
    if provider == "openai":
        return GenreFeatureEnricher(
            OpenAIJsonClient.from_environment(
                node_name="genre_feature_enrichment",
            ),
            provider,
        )
    if provider == "local":
        return GenreFeatureEnricher(
            LocalAIJsonClient.from_environment(
                node_name="genre_feature_enrichment",
                default_model=DEFAULT_CONDITION_FEATURE_MODEL,
            ),
            provider,
        )
    if provider == "gemini":
        return GenreFeatureEnricher(
            GeminiApiClient.from_environment(
                node_name="genre_feature_enrichment",
            ),
            provider,
        )
    raise ValueError(
        "MAINFLOW_GENRE_FEATURE_PROVIDER must be 'openai', 'local', 'gemini', or 'off'"
    )


def _validated_suggestion(
    item: Mapping[str, object], existing_feature_ids: set[str]
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, minimum, maximum in (
        ("name", 2, 60),
        ("description", 8, 320),
        ("rationale", 8, 320),
        ("acceptance_criteria", 8, 420),
    ):
        value = str(item.get(key, "")).strip()
        if not minimum <= len(value) <= maximum:
            raise ValueError(f"Inferred genre feature {key} length is invalid")
        result[key] = value
    implementation_kind = str(item.get("implementation_kind", "")).strip()
    allowed = {
        "reuse_module",
        "configure_existing",
        "scene_binding",
        "design_constraint",
        "generate_code",
        "validation_only",
    }
    if implementation_kind not in allowed:
        raise ValueError("Inferred genre feature implementation_kind is invalid")
    raw_targets = item.get("target_mechanics", [])
    if not isinstance(raw_targets, list) or any(
        not isinstance(value, str) for value in raw_targets
    ):
        raise ValueError("Inferred genre feature target_mechanics must be a string array")
    result["implementation_kind"] = implementation_kind
    raw_checklist = item.get("checklist")
    if not isinstance(raw_checklist, Mapping):
        raise ValueError("Inferred feature checklist must be an object")
    checklist: dict[str, list[str]] = {}
    for key in ("preconditions", "steps", "expected_results", "failure_signals"):
        values = raw_checklist.get(key)
        if (
            not isinstance(values, list)
            or not values
            or any(not isinstance(value, str) or not value.strip() for value in values)
        ):
            raise ValueError(f"Inferred feature checklist {key} must be a non-empty string array")
        checklist[key] = list(dict.fromkeys(value.strip() for value in values))
    result["checklist"] = checklist
    result["target_mechanics"] = list(
        dict.fromkeys(value.strip() for value in raw_targets if value.strip())
    )
    closure_kind = str(item.get("closure_kind", "")).strip()
    if closure_kind not in {"user_requirement_dependency", "genre_core_requirement"}:
        raise ValueError("Inferred feature closure_kind is invalid")
    raw_supports = item.get("supports_feature_ids", [])
    if not isinstance(raw_supports, list) or any(
        not isinstance(value, str) for value in raw_supports
    ):
        raise ValueError("Inferred feature supports_feature_ids must be a string array")
    supports = list(dict.fromkeys(value.strip() for value in raw_supports if value.strip()))
    unknown_supports = set(supports) - existing_feature_ids
    if unknown_supports:
        raise ValueError("Inferred feature references unknown user feature ids")
    dependency_role = str(item.get("dependency_role", "")).strip()
    allowed_roles = {
        "prerequisite_state",
        "required_actor",
        "runtime_binding",
        "interaction_consequence",
        "player_feedback",
        "failure_recovery",
        "genre_core",
    }
    if dependency_role not in allowed_roles:
        raise ValueError("Inferred feature dependency_role is invalid")
    if closure_kind == "user_requirement_dependency":
        if not supports or dependency_role == "genre_core":
            raise ValueError("User requirement dependencies need supported ids and a concrete role")
    elif supports or dependency_role != "genre_core":
        raise ValueError("Genre core requirements must use genre_core without supported ids")
    result["closure_kind"] = closure_kind
    result["supports_feature_ids"] = supports
    result["dependency_role"] = dependency_role
    return result


def _feature_fingerprint(name: str, description: str) -> str:
    return _normalize_feature_text(name) + ":" + _normalize_feature_text(description)


def _normalize_feature_text(value: str) -> str:
    return re.sub(r"[^0-9a-zA-Z가-힣]+", "", value).casefold()


def _semantically_overlaps(suggestion: Mapping[str, str], existing: FeatureRequirement) -> bool:
    suggestion_name = _normalize_feature_text(suggestion["name"])
    existing_name = _normalize_feature_text(existing["name"])
    if suggestion_name == existing_name:
        return True
    suggestion_description = _normalize_feature_text(suggestion["description"])
    existing_description = _normalize_feature_text(existing["description"])
    if not suggestion_description or not existing_description:
        return False
    shorter, longer = sorted((suggestion_description, existing_description), key=len)
    return len(shorter) >= 12 and shorter in longer


def _covered_by_baseline(
    suggestion: Mapping[str, str], baseline_contract: Mapping[str, object]
) -> bool:
    suggestion_text = _normalize_feature_text(suggestion["name"] + suggestion["description"])
    for value in _flatten_strings(baseline_contract):
        baseline_text = _normalize_feature_text(value)
        if not baseline_text:
            continue
        shorter, longer = sorted((suggestion_text, baseline_text), key=len)
        if len(shorter) >= 12 and shorter in longer:
            return True
    return False


def _flatten_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return [item for child in value.values() for item in _flatten_strings(child)]
    if isinstance(value, list):
        return [item for child in value for item in _flatten_strings(child)]
    return []
