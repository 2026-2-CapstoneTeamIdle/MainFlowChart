"""Generate narrowly scoped Unity modules for mechanics missing from the template."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, cast

from mainflow.contracts import GameLogicDesign, GeneratedGameModule

DEFAULT_GEMINI_MODEL = "gemini-3-flash-preview"
MODULE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
CLASS_NAME_PATTERN = re.compile(r"^[A-Z][A-Za-z0-9]*Module$")

GENERATED_MODULE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["generated_modules"],
    "properties": {
        "generated_modules": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "module_id",
                    "feature_id",
                    "feature_description",
                    "class_name",
                    "source_code",
                ],
                "properties": {
                    "module_id": {"type": "string"},
                    "feature_id": {"type": "string"},
                    "feature_description": {"type": "string"},
                    "class_name": {"type": "string"},
                    "source_code": {"type": "string"},
                },
            },
        }
    },
}


class StructuredJsonClient(Protocol):
    def generate_json(self, prompt: str, schema: Mapping[str, Any]) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class GeminiApiClient:
    """Small dependency-free Gemini generateContent client."""

    api_key: str
    model: str = DEFAULT_GEMINI_MODEL
    timeout_seconds: int = 90
    max_attempts: int = 2
    thinking_level: str = "low"
    max_output_tokens: int = 8192

    @classmethod
    def from_environment(cls) -> GeminiApiClient:
        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError(
                "A new game mechanic requires Gemini generation, but GEMINI_API_KEY is not set"
            )
        model = os.environ.get("MAINFLOW_GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip()
        if not re.fullmatch(r"[A-Za-z0-9._-]+", model):
            raise ValueError("MAINFLOW_GEMINI_MODEL contains unsupported characters")
        timeout = int(os.environ.get("MAINFLOW_GEMINI_TIMEOUT_SECONDS", "90"))
        thinking_level = os.environ.get("MAINFLOW_GEMINI_THINKING_LEVEL", "low").strip()
        if thinking_level not in {"minimal", "low", "medium", "high"}:
            raise ValueError("MAINFLOW_GEMINI_THINKING_LEVEL is invalid")
        max_output_tokens = int(os.environ.get("MAINFLOW_GEMINI_MAX_OUTPUT_TOKENS", "8192"))
        if max_output_tokens < 1024:
            raise ValueError("MAINFLOW_GEMINI_MAX_OUTPUT_TOKENS must be at least 1024")
        return cls(
            api_key=api_key,
            model=model,
            timeout_seconds=timeout,
            thinking_level=thinking_level,
            max_output_tokens=max_output_tokens,
        )

    def generate_json(self, prompt: str, schema: Mapping[str, Any]) -> Mapping[str, Any]:
        model = urllib.parse.quote(self.model, safe="._-")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": self.max_output_tokens,
                "thinkingConfig": {"thinkingLevel": self.thinking_level},
                "responseMimeType": "application/json",
                "responseJsonSchema": schema,
            },
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
            },
            method="POST",
        )
        response_body = ""
        for attempt in range(self.max_attempts):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    response_body = response.read().decode("utf-8")
                break
            except urllib.error.HTTPError as error:
                retryable = error.code == 429 or 500 <= error.code < 600
                if not retryable or attempt + 1 >= self.max_attempts:
                    detail = error.read().decode("utf-8", errors="replace")[:500]
                    raise RuntimeError(
                        f"Gemini API request failed with HTTP {error.code}: {detail}"
                    ) from error
                time.sleep(0.5 * (attempt + 1))
            except TimeoutError as error:
                if attempt + 1 >= self.max_attempts:
                    raise RuntimeError(
                        "Gemini API response timed out after "
                        f"{self.timeout_seconds} seconds. Increase "
                        "MAINFLOW_GEMINI_TIMEOUT_SECONDS and try again."
                    ) from error
                time.sleep(0.5 * (attempt + 1))
            except urllib.error.URLError as error:
                if attempt + 1 >= self.max_attempts:
                    raise RuntimeError(f"Gemini API request failed: {error.reason}") from error
                time.sleep(0.5 * (attempt + 1))

        try:
            response_payload = json.loads(response_body)
            parts = response_payload["candidates"][0]["content"]["parts"]
            text = "".join(part.get("text", "") for part in parts)
            result = json.loads(text)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
            raise RuntimeError("Gemini API returned no valid structured output") from error
        if not isinstance(result, dict):
            raise RuntimeError("Gemini structured output must be a JSON object")
        return cast(Mapping[str, Any], result)


class GeminiFeatureGenerator:
    """Ask Gemini only for unsupported mechanics, then validate every source file."""

    BANNED_SOURCE_FRAGMENTS = (
        "```",
        "UnityEditor",
        "System.IO",
        "System.Net",
        "HttpClient",
        "WebRequest",
        "System.Diagnostics",
        "System.Environment",
        "System.Reflection",
        "DllImport",
        "Application.OpenURL",
        "CharacterController",
        "Physics.",
        "new Ray(",
        "RaycastHit ",
        "Rigidbody ",
        "Collider ",
        "File.",
        "Directory.",
        "Process.",
        "Environment.",
        "unsafe ",
    )

    def __init__(self, client: StructuredJsonClient) -> None:
        self.client = client

    @classmethod
    def from_environment(cls) -> GeminiFeatureGenerator:
        return cls(GeminiApiClient.from_environment())

    def generate(
        self,
        design: GameLogicDesign,
        requirements: Mapping[str, Mapping[str, str]],
    ) -> list[GeneratedGameModule]:
        unsupported = design["unsupported_mechanics"]
        if not unsupported:
            return []
        if set(unsupported) != set(requirements):
            raise ValueError("Every unsupported mechanic needs one generation requirement")

        generated: list[GeneratedGameModule] = []
        # Generate one feature per request. This keeps structured code responses small and makes
        # a failure repairable without regenerating unrelated mechanics.
        for module_id in unsupported:
            module_requirements = {module_id: requirements[module_id]}
            prompt = self._build_prompt(design, module_requirements)
            for attempt in range(3):
                raw = self.client.generate_json(prompt, GENERATED_MODULE_SCHEMA)
                try:
                    generated.extend(self._parse_response(raw, [module_id], module_requirements))
                    break
                except ValueError as error:
                    if attempt == 2:
                        raise
                    prompt += (
                        "\n\nYour previous structured output failed local validation. "
                        f"Correct every issue and return the complete response again. Error: {error}. "
                        "Copy all identifiers and descriptions exactly from the context."
                    )
        return generated

    def _parse_response(
        self,
        raw: Mapping[str, Any],
        unsupported: list[str],
        requirements: Mapping[str, Mapping[str, str]],
    ) -> list[GeneratedGameModule]:
        raw_modules = raw.get("generated_modules")
        if not isinstance(raw_modules, list):
            raise ValueError("Gemini output requires generated_modules")
        modules = [
            self._validate_module(item, requirements)
            for item in raw_modules
            if isinstance(item, Mapping)
        ]
        if len(modules) != len(raw_modules):
            raise ValueError("Every generated_modules item must be an object")
        generated_ids = [module["module_id"] for module in modules]
        if len(generated_ids) != len(set(generated_ids)):
            raise ValueError("Gemini returned duplicate module IDs")
        if set(generated_ids) != set(unsupported):
            raise ValueError("Gemini must generate exactly one module per unsupported mechanic")
        return modules

    @staticmethod
    def _build_prompt(
        design: GameLogicDesign,
        requirements: Mapping[str, Mapping[str, str]],
    ) -> str:
        context = {
            "game_title": design["game_spec"]["title"],
            "genre": design["game_spec"]["genre"],
            "viewpoint": design["game_spec"]["viewpoint"],
            "selected_existing_modules": design["selected_modules"],
            "implementation_context": {
                "core_loop_phases": design["implementation_plan"]["core_loop_phases"],
                "systems": design["implementation_plan"]["systems"],
            },
            "missing_requirements": requirements,
        }
        return f"""You generate small, compilable Unity 6 C# runtime modules.
Generate exactly one module for every missing requirement in the JSON context below.
Do not regenerate, replace, or duplicate an existing module.
Copy module_id, feature_id, and feature_description exactly from missing_requirements.

Each source file must:
- use namespace TeamIdle.GameTemplate.Generated;
- import TeamIdle.GameTemplate.Common when using InputAdapterModule, HealthComponent, or other
  common runtime types;
- import TeamIdle.GameTemplate.Platformer when using PlatformerMovementModule or another
  platformer runtime type;
- be a public sealed class whose name ends with Module;
- derive from TeamIdle.GameTemplate.Core.GameModuleBehaviour and implement IGeneratedFeatureModule;
- have [GeneratedGameModule(\"module_id\")];
- override ModuleId with the exact module_id;
- implement protected override void OnInitialize(GameContext context) and call context.Register(this);
- expose public bool IsFeatureBound and set it to true in
  public void BindGeneratedFeature(GeneratedFeatureBindingContext context);
- resolve every player component and module dependency inside BindGeneratedFeature via context;
  do not wait for OnInitialize because build validation binds features before Play Mode starts;
- obtain the target player from context.Player when the requested feature affects the player;
- actively execute the requested behavior from Update or FixedUpdate after binding; do not only
  expose a helper method that nothing calls;
- this is a strictly 2D project: use Rigidbody2D, Collider2D, Physics2D, and RaycastHit2D only;
  never use CharacterController, Rigidbody, Collider, Physics.Raycast, Ray, or RaycastHit;
- use only deterministic local Unity runtime APIs and existing TeamIdle.GameTemplate runtime types;
- contain no UnityEditor, file/network/process/reflection/native/unsafe API;
- contain raw C# only, without Markdown fences.

GeneratedFeatureBindingContext provides Player, Modules, Environment, Entities, Ui, and
GetModule<T>(). InputAdapterModule provides Movement and ConfirmPressed. Keep each module focused
on its requested behavior and do not invent assets or external packages.

Context:
{json.dumps(context, ensure_ascii=False, indent=2)}
"""

    def _validate_module(
        self,
        raw: Mapping[str, Any],
        requirements: Mapping[str, Mapping[str, str]],
    ) -> GeneratedGameModule:
        fields = {
            name: raw.get(name)
            for name in (
                "module_id",
                "feature_id",
                "feature_description",
                "class_name",
                "source_code",
            )
        }
        if not all(isinstance(value, str) and value.strip() for value in fields.values()):
            raise ValueError("Generated module fields must be non-empty strings")
        module_id = cast(str, fields["module_id"]).strip()
        feature_id = cast(str, fields["feature_id"]).strip()
        description = cast(str, fields["feature_description"]).strip()
        class_name = cast(str, fields["class_name"]).strip()
        source = cast(str, fields["source_code"]).replace("\r\n", "\n").strip() + "\n"

        if module_id not in requirements or not MODULE_ID_PATTERN.fullmatch(module_id):
            raise ValueError(f"Unexpected generated module ID: {module_id}")
        requirement = requirements[module_id]
        if feature_id != requirement["feature_id"]:
            raise ValueError(f"Feature ID mismatch for {module_id}")
        if description != requirement["feature_description"]:
            raise ValueError(f"Feature description mismatch for {module_id}")
        if not CLASS_NAME_PATTERN.fullmatch(class_name):
            raise ValueError(f"Invalid generated C# class name: {class_name}")
        if len(source) > 20_000:
            raise ValueError(f"Generated source is too large for {module_id}")
        banned = [fragment for fragment in self.BANNED_SOURCE_FRAGMENTS if fragment in source]
        if banned:
            raise ValueError(f"Generated source for {module_id} uses banned APIs: {banned}")

        namespace_requirements = {
            "InputAdapterModule": "TeamIdle.GameTemplate.Common",
            "HealthComponent": "TeamIdle.GameTemplate.Common",
            "PlatformerMovementModule": "TeamIdle.GameTemplate.Platformer",
        }
        missing_namespaces = [
            namespace
            for type_name, namespace in namespace_requirements.items()
            if type_name in source
            and re.search(rf"using\s+{re.escape(namespace)}\s*;", source) is None
            and f"{namespace}.{type_name}" not in source
        ]
        if missing_namespaces:
            raise ValueError(
                f"Generated source for {module_id} is missing namespace imports: "
                f"{sorted(set(missing_namespaces))}"
            )

        binding_requirements = {
            "InputAdapterModule": r"context\s*\.\s*GetModule\s*<\s*InputAdapterModule\s*>",
            "PlatformerMovementModule": (
                r"context\s*\.\s*GetModule\s*<\s*PlatformerMovementModule\s*>"
            ),
        }
        missing_bindings = [
            type_name
            for type_name, pattern in binding_requirements.items()
            if type_name in source and re.search(pattern, source) is None
        ]
        if missing_bindings:
            raise ValueError(
                f"Generated source for {module_id} must bind module dependencies from context: "
                f"{missing_bindings}"
            )

        required_patterns = {
            "namespace": r"namespace\s+TeamIdle\.GameTemplate\.Generated",
            "class": (
                rf"public\s+sealed\s+class\s+{re.escape(class_name)}\s*:\s*"
                r"GameModuleBehaviour\s*,\s*IGeneratedFeatureModule"
            ),
            "attribute": (rf"\[GeneratedGameModule\s*\(\s*\"{re.escape(module_id)}\"\s*\)\s*\]"),
            "module ID": (
                rf"public\s+override\s+string\s+ModuleId\s*=>\s*\"{re.escape(module_id)}\"\s*;"
            ),
            "initializer": (
                r"protected\s+override\s+void\s+OnInitialize\s*\(\s*GameContext\s+context\s*\)"
            ),
            "registration": r"context\s*\.\s*Register\s*\(\s*this\s*\)\s*;",
            "binding state": r"public\s+bool\s+IsFeatureBound\b",
            "binding method": (
                r"public\s+void\s+BindGeneratedFeature\s*\(\s*"
                r"GeneratedFeatureBindingContext\s+context\s*\)"
            ),
            "active update loop": r"private\s+void\s+(?:Update|FixedUpdate)\s*\(\s*\)",
        }
        missing = [
            name
            for name, pattern in required_patterns.items()
            if re.search(pattern, source) is None
        ]
        if missing:
            raise ValueError(f"Generated source for {module_id} is missing: {missing}")
        if not self._has_valid_binding_completion(source):
            raise ValueError(f"Generated source for {module_id} is missing: ['binding completion']")
        return {
            "module_id": module_id,
            "feature_id": feature_id,
            "feature_description": description,
            "class_name": class_name,
            "source_code": source,
            "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        }

    @staticmethod
    def _has_valid_binding_completion(source: str) -> bool:
        property_assignment = re.search(r"\bIsFeatureBound\s*=\s*([^;]+)\s*;", source)
        if property_assignment:
            expression = property_assignment.group(1).strip().strip("() ")
            return expression not in {"false", "default", "default(bool)", "null"}

        backing_property = re.search(
            r"public\s+bool\s+IsFeatureBound\s*=>\s*([A-Za-z_][A-Za-z0-9_]*)\s*;",
            source,
        )
        if backing_property:
            field_name = backing_property.group(1)
            return re.search(rf"\b{re.escape(field_name)}\s*=\s*true\s*;", source) is not None

        expression_property = re.search(
            r"public\s+bool\s+IsFeatureBound\s*=>\s*([^;]+)\s*;",
            source,
        )
        if expression_property:
            expression = expression_property.group(1).strip()
            return expression not in {"false", "default", "default(bool)"}

        getter_property = re.search(
            r"public\s+bool\s+IsFeatureBound\s*\{.*?"
            r"return\s+([^;]+)\s*;.*?\}",
            source,
            re.DOTALL,
        )
        if getter_property:
            expression = getter_property.group(1).strip()
            return expression not in {"false", "default", "default(bool)"}
        return False


def attach_generated_modules(
    design: GameLogicDesign,
    generated_modules: list[GeneratedGameModule],
) -> GameLogicDesign:
    """Return a resolved design where generated modules satisfy unsupported mechanics."""

    resolved = deepcopy(design)
    unsupported = set(resolved["unsupported_mechanics"])
    generated_ids = {module["module_id"] for module in generated_modules}
    if unsupported != generated_ids:
        raise ValueError("Generated modules do not resolve every unsupported mechanic")
    resolved["generated_modules"] = deepcopy(generated_modules)
    resolved["selected_modules"] = list(
        dict.fromkeys(
            resolved["selected_modules"] + [module["module_id"] for module in generated_modules]
        )
    )
    resolved["unsupported_mechanics"] = []
    return resolved
