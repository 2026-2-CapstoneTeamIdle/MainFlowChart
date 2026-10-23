"""Deterministic Unity C# and requirement index for small-model context retrieval."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

INDEX_VERSION = "1.0.0"
_TYPE_PATTERN = re.compile(
    r"(?P<attributes>(?:\s*\[[^\]]+\]\s*)*)"
    r"(?P<modifiers>(?:(?:public|internal|protected|private|abstract|sealed|static|partial)\s+)*)"
    r"(?P<kind>class|interface|struct|enum)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?:\s*<[^>{}]+>)?"
    r"(?:\s*:\s*(?P<bases>[^\{]+))?\s*\{",
    re.MULTILINE,
)
_NAMESPACE_PATTERN = re.compile(r"\bnamespace\s+([A-Za-z_][A-Za-z0-9_.]*)")
_METHOD_PATTERN = re.compile(
    r"(?ms)^\s*(?P<access>public|protected|internal)\s+"
    r"(?P<modifiers>(?:(?:static|virtual|override|abstract|sealed|async|new)\s+)*)"
    r"(?P<return>[A-Za-z_][A-Za-z0-9_.?]*(?:\s*<[^;>{}]+>)?(?:\[\])?)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?P<generic><[^>]+>)?\s*"
    r"\((?P<parameters>[^)]*)\)\s*(?:where\s+[^\{;=>]+\s*)?(?:\{|=>|;)",
)
_PROPERTY_PATTERN = re.compile(
    r"(?m)^\s*(?P<access>public|protected|internal)\s+"
    r"(?P<modifiers>(?:(?:static|virtual|override|abstract|sealed|new)\s+)*)"
    r"(?P<type>[A-Za-z_][A-Za-z0-9_.?]*(?:\s*<[^;>{}]+>)?(?:\[\])?)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?P<body>=>[^;]+;|\{[^\n]*\})",
)
_EVENT_PATTERN = re.compile(
    r"(?m)^\s*(?P<access>public|protected|internal)\s+event\s+"
    r"(?P<type>[A-Za-z_][A-Za-z0-9_.?]*(?:\s*<[^;>{}]+>)?(?:\[\])?)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*;"
)
_FIELD_PATTERN = re.compile(
    r"(?m)^\s*(?P<access>public|protected|internal)\s+"
    r"(?P<modifiers>(?:(?:static|readonly|const|volatile|new)\s+)*)"
    r"(?P<type>[A-Za-z_][A-Za-z0-9_.?]*(?:\s*<[^;>{}]+>)?(?:\[\])?)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?:=[^;]*)?;"
)
_MODULE_ID_PATTERN = re.compile(r'\boverride\s+string\s+ModuleId\s*=>\s*"(?P<module_id>[^"]+)"')
_EVENT_EMIT_PATTERN = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\?\.Invoke\s*\(")
_EVENT_SUBSCRIBE_PATTERN = re.compile(
    r"\b([A-Za-z_][A-Za-z0-9_.]*)\s*\+=\s*([A-Za-z_][A-Za-z0-9_]*)"
)
_UNITY_MESSAGES = {
    "Awake",
    "Start",
    "Update",
    "FixedUpdate",
    "LateUpdate",
    "OnEnable",
    "OnDisable",
    "OnDestroy",
    "OnTriggerEnter2D",
    "OnTriggerExit2D",
    "OnCollisionEnter2D",
    "OnCollisionExit2D",
}
_COMMON_MODULE_IDS = {
    "game_bootstrap",
    "game_state_store",
    "event_rule_engine",
    "scene_flow_manager",
    "input_adapter",
    "save_system",
    "asset_registry",
    "audio_manager",
    "ui_router",
    "validation_probe",
}
_RETRIEVAL_HINTS = {
    "wave_spawner": ("wave", "웨이브", "라운드", "적 생성"),
    "tower_targeting_system": ("tower", "타워", "target", "사거리", "공격속도"),
    "projectile_system": ("projectile", "투사체", "발사", "화살", "마법", "공격"),
    "base_defense_system": ("base", "기지", "패배", "승리", "마지막 웨이브"),
    "health_damage_system": ("health", "체력", "피해", "damage", "죽", "공격"),
    "economy_system": ("gold", "골드", "경제", "비용", "구매", "강화", "보상"),
    "input_adapter": ("input", "입력", "조작", "이동", "점프", "대시"),
    "platformer_movement": ("platform", "이동", "점프", "벽", "대시", "movement"),
    "turn_system": ("turn", "턴", "차례"),
    "deck_system": ("card", "카드", "덱", "드로우", "hand"),
    "dialogue_system": ("dialogue", "대화", "선택지", "텍스트"),
    "stat_growth_system": ("stat", "능력치", "육성", "성장", "훈련"),
    "enemy_spawn_system": ("enemy", "적", "spawn", "생성"),
    "upgrade_choice_system": ("upgrade", "업그레이드", "특전", "레벨업"),
}


def build_project_context_index(
    project_root: str | Path,
    *,
    design: Mapping[str, Any] | None = None,
    request: Mapping[str, Any] | None = None,
    logic_analysis: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Index source APIs and stable requirement IDs without asking an LLM to summarize them."""

    root = Path(project_root).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Project index root does not exist: {root}")
    source_paths = sorted(
        (
            path
            for path in root.rglob("*.cs")
            if not {"Library", "Temp", "Logs", "obj"}.intersection(path.relative_to(root).parts)
        ),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    files: list[dict[str, Any]] = []
    types: list[dict[str, Any]] = []
    type_bodies: dict[str, str] = {}
    for path in source_paths:
        content = path.read_text(encoding="utf-8")
        relative_path = path.relative_to(root).as_posix()
        files.append(
            {
                "path": relative_path,
                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "line_count": len(content.splitlines()),
            }
        )
        parsed = _parse_types(content, relative_path)
        for item, body in parsed:
            types.append(item)
            type_bodies[item["full_name"]] = body

    known_names = {item["name"] for item in types}
    for item in types:
        body = type_bodies[item["full_name"]]
        item["dependencies"] = sorted(
            name for name in known_names if name != item["name"] and re.search(rf"\b{name}\b", body)
        )

    modules = {
        item["module_id"]: item["full_name"]
        for item in types
        if isinstance(item.get("module_id"), str)
    }
    return {
        "index_version": INDEX_VERSION,
        "source": "deterministic-csharp-and-contract-scan",
        "project_root_name": root.name,
        "file_count": len(files),
        "type_count": len(types),
        "files": files,
        "types": types,
        "module_types": modules,
        "requirements": _requirements(design, request, logic_analysis),
    }


def compact_api_contract(
    index: Mapping[str, Any],
    *,
    selected_module_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Return a bounded exact API contract suitable for a small code model prompt."""

    module_types = index.get("module_types", {})
    selected_names = {
        str(module_types[module_id]).rsplit(".", 1)[-1]
        for module_id in selected_module_ids or []
        if isinstance(module_types, Mapping) and module_id in module_types
    }
    always_include = {
        "GameModuleBehaviour",
        "IGeneratedFeatureModule",
        "GeneratedFeatureBindingContext",
        "GameContext",
        "InputAdapterModule",
        "HealthComponent",
    }
    for item in index.get("types", []):
        if isinstance(item, Mapping) and item.get("name") in selected_names | always_include:
            selected_names.update(
                dependency
                for dependency in item.get("dependencies", [])
                if isinstance(dependency, str)
            )
    project_types: dict[str, Any] = {}
    for item in index.get("types", []):
        if not isinstance(item, Mapping):
            continue
        name = item.get("name")
        if not isinstance(name, str):
            continue
        if selected_names and name not in selected_names | always_include:
            continue
        project_types[name] = {
            "namespace": item.get("namespace", ""),
            "kind": item.get("kind", "class"),
            "bases": item.get("bases", []),
            "module_id": item.get("module_id"),
            "public_api": item.get("members", []),
            "events": item.get("events", []),
            "unity_messages": item.get("unity_messages", []),
        }
    return {
        "index_version": index.get("index_version", INDEX_VERSION),
        "project_types": project_types,
        "selected_module_ids": selected_module_ids or [],
        "rule": "A member absent from public_api must be treated as nonexistent.",
    }


def retrieve_prompt_api_contract(
    index: Mapping[str, Any],
    *,
    selected_module_ids: list[str] | None = None,
    requirement_text: str = "",
    max_module_types: int = 6,
    max_dependency_types: int = 6,
) -> dict[str, Any]:
    """Retrieve a small exact signature index instead of serializing every selected API."""

    if max_module_types < 1 or max_dependency_types < 0:
        raise ValueError("Prompt API retrieval limits are invalid")
    module_types = index.get("module_types", {})
    if not isinstance(module_types, Mapping):
        module_types = {}
    selected_ids = [
        module_id
        for module_id in selected_module_ids or []
        if isinstance(module_id, str) and module_id in module_types
    ]
    normalized_query = requirement_text.casefold()
    scored = sorted(
        selected_ids,
        key=lambda module_id: (
            -_module_relevance(module_id, normalized_query),
            module_id in _COMMON_MODULE_IDS,
            selected_ids.index(module_id),
        ),
    )
    matched = [module_id for module_id in scored if _module_relevance(module_id, normalized_query)]
    if matched:
        retrieved_ids = matched[:max_module_types]
    else:
        genre_ids = [module_id for module_id in selected_ids if module_id not in _COMMON_MODULE_IDS]
        retrieved_ids = (genre_ids or selected_ids)[:max_module_types]

    required_names = {
        "GameModuleBehaviour",
        "IGeneratedFeatureModule",
        "GeneratedFeatureBindingContext",
        "GameContext",
    }
    required_names.update(
        str(module_types[module_id]).rsplit(".", 1)[-1] for module_id in retrieved_ids
    )
    type_items = {
        str(item.get("name")): item
        for item in index.get("types", [])
        if isinstance(item, Mapping) and isinstance(item.get("name"), str)
    }
    dependency_names: list[str] = []
    for name in sorted(required_names):
        item = type_items.get(name)
        if item is None:
            continue
        for dependency in item.get("dependencies", []):
            if (
                isinstance(dependency, str)
                and dependency not in required_names
                and dependency not in dependency_names
            ):
                dependency_names.append(dependency)
    required_names.update(dependency_names[:max_dependency_types])

    prompt_types: dict[str, Any] = {}
    for name in sorted(required_names):
        item = type_items.get(name)
        if item is None:
            continue
        signatures = [
            str(member.get("signature"))
            for member in item.get("members", [])
            if isinstance(member, Mapping)
            and isinstance(member.get("signature"), str)
            and not str(member.get("name", "")).startswith("Test")
        ]
        prompt_types[name] = {
            "namespace": item.get("namespace", ""),
            "bases": item.get("bases", []),
            "module_id": item.get("module_id"),
            "api": signatures,
        }
    return {
        "index_version": index.get("index_version", INDEX_VERSION),
        "available_modules": {
            module_id: str(module_types[module_id]).rsplit(".", 1)[-1] for module_id in selected_ids
        },
        "retrieved_module_ids": retrieved_ids,
        "project_types": prompt_types,
        "rules": [
            "A member absent from project_types[type].api is nonexistent.",
            "available_modules lists capabilities, not permission to invent unlisted APIs.",
        ],
    }


def _module_relevance(module_id: str, normalized_query: str) -> int:
    if not normalized_query:
        return 0
    hints = (*module_id.split("_"), *_RETRIEVAL_HINTS.get(module_id, ()))
    return sum(
        3 if hint in _RETRIEVAL_HINTS.get(module_id, ()) else 1
        for hint in hints
        if hint and hint.casefold() in normalized_query
    )


def _parse_types(content: str, relative_path: str) -> list[tuple[dict[str, Any], str]]:
    namespace_match = _NAMESPACE_PATTERN.search(content)
    namespace = namespace_match.group(1) if namespace_match else ""
    result: list[tuple[dict[str, Any], str]] = []
    for match in _TYPE_PATTERN.finditer(content):
        body_start = match.end() - 1
        body_end = _matching_brace(content, body_start)
        if body_end is None:
            continue
        body = content[body_start + 1 : body_end]
        name = match.group("name")
        bases = [part.strip() for part in (match.group("bases") or "").split(",") if part.strip()]
        methods = [_method(match) for match in _METHOD_PATTERN.finditer(body)]
        properties = [_property(match) for match in _PROPERTY_PATTERN.finditer(body)]
        events = [_event(match) for match in _EVENT_PATTERN.finditer(body)]
        fields = [_field(match) for match in _FIELD_PATTERN.finditer(body)]
        members = _unique_members([*properties, *fields, *methods, *events])
        module_match = _MODULE_ID_PATTERN.search(body)
        event_names = {item["name"] for item in events}
        result.append(
            (
                {
                    "name": name,
                    "full_name": f"{namespace}.{name}" if namespace else name,
                    "namespace": namespace,
                    "kind": match.group("kind"),
                    "access": _access(match.group("modifiers")),
                    "modifiers": match.group("modifiers").split(),
                    "bases": bases,
                    "file": relative_path,
                    "line": content.count("\n", 0, match.start()) + 1,
                    "component": any(
                        base.rsplit(".", 1)[-1]
                        in {"MonoBehaviour", "GameModuleBehaviour", "ScriptableObject"}
                        for base in bases
                    ),
                    "module_id": module_match.group("module_id") if module_match else None,
                    "members": members,
                    "events": events,
                    "event_emissions": sorted(set(_EVENT_EMIT_PATTERN.findall(body)) & event_names),
                    "event_subscriptions": [
                        {"event": event, "handler": handler}
                        for event, handler in _EVENT_SUBSCRIBE_PATTERN.findall(body)
                    ],
                    "unity_messages": sorted(
                        {item["name"] for item in methods if item["name"] in _UNITY_MESSAGES}
                    ),
                    "dependencies": [],
                },
                body,
            )
        )
    return result


def _method(match: re.Match[str]) -> dict[str, Any]:
    parameters = " ".join(match.group("parameters").split())
    modifiers = match.group("modifiers").split()
    return {
        "kind": "method",
        "name": match.group("name"),
        "signature": (
            f"{match.group('access')} {' '.join(modifiers)} {match.group('return')} "
            f"{match.group('name')}{match.group('generic') or ''}({parameters})"
        ).replace("  ", " "),
        "access": match.group("access"),
        "return_type": match.group("return"),
        "parameters": parameters,
        "writable": False,
    }


def _property(match: re.Match[str]) -> dict[str, Any]:
    body = match.group("body")
    return {
        "kind": "property",
        "name": match.group("name"),
        "signature": (
            f"{match.group('access')} {match.group('type')} {match.group('name')} {body}"
        ),
        "access": match.group("access"),
        "type": match.group("type"),
        "writable": " set;" in body and "private set;" not in body and "protected set;" not in body,
    }


def _event(match: re.Match[str]) -> dict[str, Any]:
    return {
        "kind": "event",
        "name": match.group("name"),
        "signature": (f"{match.group('access')} event {match.group('type')} {match.group('name')}"),
        "access": match.group("access"),
        "type": match.group("type"),
        "writable": False,
    }


def _field(match: re.Match[str]) -> dict[str, Any]:
    modifiers = match.group("modifiers").split()
    return {
        "kind": "field",
        "name": match.group("name"),
        "signature": (
            f"{match.group('access')} {' '.join(modifiers)} "
            f"{match.group('type')} {match.group('name')}"
        ).replace("  ", " "),
        "access": match.group("access"),
        "type": match.group("type"),
        "writable": "readonly" not in modifiers and "const" not in modifiers,
    }


def _requirements(
    design: Mapping[str, Any] | None,
    request: Mapping[str, Any] | None,
    logic_analysis: Mapping[str, Any] | None,
) -> dict[str, Any]:
    game_spec = design.get("game_spec", {}) if design else {}
    design_v2 = design.get("design_v2", {}) if design else {}
    system_design = design_v2.get("system_design", {}) if isinstance(design_v2, Mapping) else {}
    validation_plan = design_v2.get("validation_plan", {}) if isinstance(design_v2, Mapping) else {}
    return {
        "user_condition": request.get("condition", "") if request else "",
        "genre": game_spec.get("genre"),
        "features": game_spec.get("features", []),
        "mechanics": game_spec.get("mechanics", []),
        "win_conditions": game_spec.get("win_conditions", []),
        "lose_conditions": game_spec.get("lose_conditions", []),
        "selected_modules": design.get("selected_modules", []) if design else [],
        "unsupported_mechanics": design.get("unsupported_mechanics", []) if design else [],
        "criteria": logic_analysis.get("criteria", []) if logic_analysis else [],
        "system_events": system_design.get("event_connections", []),
        "required_feature_bindings": validation_plan.get("required_feature_bindings", []),
        "playtest_scenarios": validation_plan.get("scenarios", []),
        "asset_requirements": game_spec.get("asset_requirements", []),
    }


def _matching_brace(content: str, opening: int) -> int | None:
    depth = 0
    for index in range(opening, len(content)):
        if content[index] == "{":
            depth += 1
        elif content[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    return None


def _access(modifiers: str) -> str:
    for access in ("public", "protected", "internal", "private"):
        if access in modifiers.split():
            return access
    return "internal"


def _unique_members(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for member in members:
        key = (member["kind"], member["signature"])
        if key not in seen:
            seen.add(key)
            unique.append(member)
    return unique
