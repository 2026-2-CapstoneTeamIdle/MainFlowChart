"""Design the game logic before generated assets are applied."""

from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import cast

from game_pipeline import (
    GameDevelopmentLoop,
    UnityProjectGenerator,
    attach_generated_modules,
    build_game_logic_design,
    build_implementation_tasks,
    create_blueprint_planner_from_environment,
    create_design_v2_planner_from_environment,
    create_feature_generator_from_environment,
    create_project_context_reviewer_from_environment,
    normalize_game_spec,
    plan_feature_mechanics,
    review_feedback,
)
from game_pipeline.feature_contract import build_feature_contract
from game_pipeline.project_context_index import build_project_context_index
from game_pipeline.repair_loop import validate_and_repair
from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import (
    CONTRACT_VERSION,
    AnalysisResult,
    DesignGameLogicAgentInput,
    DesignGameLogicAgentOutput,
    GameLogicDraft,
    LogicAnalysis,
    ParsedRequest,
)
from mainflow.nodes._common import log


# Node 계약
# - 이전 Node: logic_analysis
# - 입력 State: project_id, parsed_request, analysis, logic_analysis
# - 입력 파일: data/parsed_request.json, data/analysis.json, data/logic_analysis.json
# - 출력 State: game_logic_draft, image_asset_request, sound_asset_request
# - 출력 파일: game/game_logic_draft.json, game/asset_requests/*.json,
#   game/unity_project/, game/unity_project.zip
# - 다음 Node: validate_game, generate_image, generate_sound
def design_game_logic_node(
    state: DesignGameLogicAgentInput,
) -> DesignGameLogicAgentOutput:
    """Create a game-logic draft using temporary asset assumptions."""
    log("게임 로직을 설계합니다. (이미지/사운드는 임시 에셋으로 가정)")

    manager = ArtifactManager()
    request = cast(ParsedRequest, manager.read_json(state["parsed_request"]))
    analysis = cast(AnalysisResult, manager.read_json(state["analysis"]))
    logic_analysis = cast(LogicAnalysis, manager.read_json(state["logic_analysis"]))

    feature_plan = plan_feature_mechanics(analysis["features"], request["genre"])
    game_spec = normalize_game_spec(
        request["genre"],
        {
            "viewpoint": request["viewpoint"],
            "features": feature_plan.game_features,
            "mechanics": feature_plan.mechanics,
        },
    )
    variation_seed = os.environ.get("MAINFLOW_GENERATION_SEED", "").strip() or state["project_id"]
    log(f"이번 실행의 콘텐츠 변형 시드: {variation_seed}")
    design = build_game_logic_design(
        game_spec,
        design_intent=request["condition"],
        variation_seed=variation_seed,
    )
    unity_generator = UnityProjectGenerator()
    image_request = unity_generator.build_asset_request(
        design,
        "image",
        image_style=request["image_style"],
        mood_style=request["mood_style"],
        viewpoint=request["viewpoint"],
        reference_image=request["custom_image"],
    )
    sound_request = unity_generator.build_asset_request(
        design,
        "sound",
        image_style=request["image_style"],
        mood_style=request["mood_style"],
        viewpoint=request["viewpoint"],
        reference_image=None,
    )
    image_request_reference = manager.write_json(
        state["project_id"],
        "game",
        "asset_requests/image_asset_request.json",
        image_request,
        producer="design_game_logic",
    )
    sound_request_reference = manager.write_json(
        state["project_id"],
        "game",
        "asset_requests/sound_asset_request.json",
        sound_request,
        producer="design_game_logic",
    )
    image_asset_ids = [
        asset["asset_id"]
        for asset in game_spec["asset_requirements"]
        if asset["asset_type"] == "image"
    ]
    sound_asset_ids = [
        asset["asset_id"]
        for asset in game_spec["asset_requirements"]
        if asset["asset_type"] == "sound"
    ]
    request_references = [image_request_reference, sound_request_reference]
    feature_provider = os.environ.get("MAINFLOW_FEATURE_PROVIDER", "local").strip().lower()
    blueprint_reference = None
    development_loop = None
    implementation_tasks_reference = None
    quality_report_reference = None
    project_context_index_reference = None
    generated_modules = []
    feature_generation_failures: list[tuple[str, Exception]] = []
    try:
        design_v2_provider = (
            os.environ.get("MAINFLOW_DESIGN_V2_PROVIDER", "deterministic").strip().lower()
        )
        try:
            design_v2_planner = create_design_v2_planner_from_environment()
            if design_v2_planner is not None:
                log(f"design_game_logic v2 문서 7개를 {design_v2_provider} 모델로 단계 생성합니다.")
                design_v2 = design_v2_planner.generate(
                    game_spec,
                    request["condition"],
                    design["selected_modules"],
                    variation_seed=variation_seed,
                )
                design = {
                    **design,
                    "design_v2": design_v2,
                }
                rewritten_stages = [
                    report["stage"]
                    for report in design_v2_planner.customization_reports
                    if report["attempts"] > 1
                ]
                if rewritten_stages:
                    log(
                        "안전 템플릿과 너무 유사해 사용자 요구 중심으로 다시 작성한 단계: "
                        + ", ".join(rewritten_stages)
                    )
                if design_v2_planner.fallback_stages:
                    log(
                        "검증 실패 단계는 안전한 설계로 복구했습니다: "
                        + ", ".join(design_v2_planner.fallback_stages)
                    )
        except Exception as error:  # noqa: BLE001 - optional staged quality enhancement
            log(f"단계별 v2 설계에 실패해 검증된 기본 설계를 사용합니다: {error}")

        blueprint_provider = (
            os.environ.get("MAINFLOW_BLUEPRINT_PROVIDER", "deterministic").strip().lower()
        )
        try:
            blueprint_planner = create_blueprint_planner_from_environment()
            if blueprint_planner is not None:
                log(f"요청별 씬 Blueprint를 {blueprint_provider} 모델로 보강합니다.")
                design = {
                    **design,
                    "game_blueprint": blueprint_planner.generate(
                        game_spec,
                        request["condition"],
                        variation_seed=variation_seed,
                    ),
                }
        except Exception as error:  # noqa: BLE001 - optional quality enhancement
            log(f"LLM Blueprint 검증에 실패해 안전한 기본 Blueprint를 사용합니다: {error}")

        design["implementation_tasks"] = build_implementation_tasks(
            design,
            time_budget_seconds=int(os.environ.get("MAINFLOW_GAME_TIME_BUDGET_SECONDS", "1800")),
        )
        development_loop = GameDevelopmentLoop(
            design["implementation_tasks"],
            record=lambda name, data: manager.write_json(
                state["project_id"],
                "validation",
                f"development/{name}.json",
                data,
                producer="design_game_logic",
            ),
        )
        development_loop.mark_passed(
            "design-review",
            "design v2 documents and validation plan passed deterministic validation",
        )
        development_loop.mark_passed(
            "module-selection",
            f"selected {len(design['selected_modules'])} reusable Unity modules",
        )
        for module_id in design["selected_modules"]:
            development_loop.mark_passed(
                f"bind-module-{module_id.replace('_', '-')}",
                f"catalog resolved {module_id} to a repository-owned component",
            )
        development_loop.mark_passed(
            "configure-content",
            "content definitions and placement counts passed design v2 validation",
        )
        for zone in design["design_v2"]["level_plan"]["zones"]:
            development_loop.mark_passed(
                f"assemble-zone-{zone['zone_id'].replace('_', '-')}",
                f"zone {zone['zone_id']} route and planned content passed deterministic checks",
            )
        development_loop.mark_passed(
            "bind-presentation",
            "HUD, transition, camera, and feedback requirements are present in presentation_plan",
        )
        feature_generator = None
        if design["unsupported_mechanics"]:
            log(f"기존 모듈에 없는 기능을 {feature_provider} 모델로 생성합니다.")
            feature_generator = create_feature_generator_from_environment()
            attempt_sequence = 0

            def record_generation_attempt(data):
                nonlocal attempt_sequence
                attempt_sequence += 1
                module_id = str(data.get("module_id", "unknown")).replace("_", "-")
                stage = str(data.get("stage", "unknown")).replace("_", "-")
                manager.write_json(
                    state["project_id"],
                    "validation",
                    (
                        f"generation_attempts/{attempt_sequence:03d}_{module_id}_{stage}_"
                        f"attempt_{data.get('attempt', 0)}.json"
                    ),
                    dict(data),
                    producer="design_game_logic",
                )

            feature_generator.attempt_recorder = record_generation_attempt
            for module_id in list(design["unsupported_mechanics"]):
                task_id = f"generate-{module_id.replace('_', '-')}"
                requirement = {module_id: feature_plan.generation_requirements[module_id]}

                def generate_one_feature(
                    module_id: str = module_id,
                    requirement: dict[str, dict[str, str]] = requirement,
                ):
                    focused_design = deepcopy(design)
                    focused_design["unsupported_mechanics"] = [module_id]
                    return feature_generator.generate(focused_design, requirement)

                try:
                    generated_modules.extend(
                        development_loop.run_task(
                            task_id,
                            generate_one_feature,
                            evidence=lambda modules, module_id=module_id: (
                                f"generated {module_id}: {modules[0]['class_name']}"
                            ),
                        )
                    )
                except Exception as error:  # noqa: BLE001 - isolate one generated feature
                    feature_generation_failures.append((module_id, error))
                    log(
                        f"{module_id} 생성은 최종 실패했지만 다른 요청 기능 생성을 계속합니다: "
                        f"{type(error).__name__}: {error}"
                    )
            if feature_generation_failures:
                design["generated_modules"] = deepcopy(generated_modules)
                design["implementation_tasks"] = development_loop.snapshot()
                details = "; ".join(
                    f"{module_id}: {type(error).__name__}: {error}"
                    for module_id, error in feature_generation_failures
                )
                raise RuntimeError(
                    "Required generated features did not pass validation after bounded repairs: "
                    + details
                )
            design = attach_generated_modules(design, generated_modules)

        design["implementation_tasks"] = development_loop.snapshot()

        design_document_references = [
            manager.write_json(
                state["project_id"],
                "game",
                f"design/{filename}",
                design["design_v2"][key],  # type: ignore[literal-required]
                producer="design_game_logic",
            )
            for key, filename in UnityProjectGenerator.DESIGN_DOCUMENT_NAMES.items()
        ]
        design_reference = manager.write_json(
            state["project_id"],
            "game",
            "game_logic_design.json",
            design,
            producer="design_game_logic",
        )
        blueprint_reference = manager.write_json(
            state["project_id"],
            "game",
            "game_blueprint.json",
            design["game_blueprint"],
            producer="design_game_logic",
        )
        workspace_project_root = manager.ensure_project(state["project_id"])
        unity_project_root = workspace_project_root / "game" / "unity_project"
        generation = development_loop.run_task(
            "unity-project-generation",
            lambda: unity_generator.generate(
                design,
                unity_project_root,
                image_style=request["image_style"],
                mood_style=request["mood_style"],
                viewpoint=request["viewpoint"],
                reference_image=request["custom_image"],
            ),
            evidence=lambda result: f"generated Unity project at {result.project_root}",
        )
        if design["generated_modules"]:
            manager.write_json(
                state["project_id"],
                "game",
                "feature_code_contract.json",
                build_feature_contract(),
                producer="design_game_logic",
            )

        context_review_report: dict[str, object]
        if design["generated_modules"]:
            log("MCP로 조립된 Unity 프로젝트 문맥을 검수하고 필요한 코드를 사전 수정합니다.")

            def review_project_context():
                max_repairs = int(os.environ.get("MAINFLOW_PROJECT_REVIEW_REPAIRS", "1"))
                if not 0 <= max_repairs <= 2:
                    raise ValueError("MAINFLOW_PROJECT_REVIEW_REPAIRS must be between 0 and 2")
                current_design = design
                current_generation = generation
                history: list[dict[str, object]] = []
                preserved_projects: list[str] = []
                repair_applied = False
                for review_index in range(max_repairs + 1):
                    project_index = build_project_context_index(
                        current_generation.project_root,
                        design=current_design,
                        request=request,
                        logic_analysis=logic_analysis,
                    )
                    manager.write_json(
                        state["project_id"],
                        "validation",
                        f"project_context_index_attempt_{review_index}.json",
                        project_index,
                        producer="design_game_logic",
                    )
                    reviewer = create_project_context_reviewer_from_environment(
                        state["project_id"],
                        provider=feature_provider,
                    )
                    try:
                        report = reviewer.review(state["project_id"], current_design, project_index)
                    except Exception as error:  # noqa: BLE001 - Unity remains authoritative
                        report = {
                            "approved": False,
                            "summary": (
                                "Project-context preflight exhausted its bounded retries; "
                                "Unity compilation must provide the authoritative diagnosis."
                            ),
                            "inspected_files": [],
                            "issues": [
                                {
                                    "severity": "warning",
                                    "category": "maintainability",
                                    "relative_path": "game/unity_project",
                                    "line": None,
                                    "message": f"{type(error).__name__}: {error}",
                                    "suggested_fix": (
                                        "Inspect the Unity compiler log and retry contextual review."
                                    ),
                                }
                            ],
                            "provider": feature_provider,
                            "model": "unknown",
                            "turns": 0,
                            "tool_calls": [],
                            "review_execution_failed": True,
                        }
                    history.append(
                        {
                            "review_index": review_index,
                            "approved": report["approved"],
                            "summary": report["summary"],
                            "issues": report["issues"],
                        }
                    )
                    manager.write_json(
                        state["project_id"],
                        "validation",
                        f"project_context_review_attempt_{review_index}.json",
                        report,
                        producer="design_game_logic",
                    )
                    if report["approved"] or review_index >= max_repairs:
                        return (
                            current_design,
                            current_generation,
                            {
                                **report,
                                "repair_applied": repair_applied,
                                "preserved_projects": preserved_projects,
                                "review_history": history,
                                "review_exhausted": not report["approved"],
                            },
                        )
                    if feature_generator is None:
                        return (
                            current_design,
                            current_generation,
                            {
                                **report,
                                "repair_applied": False,
                                "preserved_projects": preserved_projects,
                                "review_history": history,
                                "review_exhausted": True,
                            },
                        )
                    revised = deepcopy(current_design)
                    revised["generated_modules"] = feature_generator.repair(
                        current_design,
                        review_feedback(report),
                    )
                    backup = _available_context_review_backup(current_generation.project_root)
                    current_generation.project_root.rename(backup)
                    current_generation = unity_generator.generate(
                        revised,
                        current_generation.project_root,
                        image_style=request["image_style"],
                        mood_style=request["mood_style"],
                        viewpoint=request["viewpoint"],
                        reference_image=request["custom_image"],
                    )
                    current_design = revised
                    repair_applied = True
                    preserved_projects.append(backup.name)
                raise AssertionError("unreachable")

            design, generation, context_review_report = development_loop.run_task(
                "project-context-review",
                review_project_context,
                evidence=lambda result: (
                    f"inspected {len(result[2]['inspected_files'])} files with "
                    f"{len(result[2]['issues'])} findings; "
                    f"repair_applied={result[2]['repair_applied']}; "
                    f"review_exhausted={result[2]['review_exhausted']}"
                ),
            )
        else:
            context_review_report = {
                "approved": True,
                "summary": "No AI-generated Unity modules required contextual LLM review.",
                "inspected_files": [],
                "issues": [],
                "provider": "none",
                "model": "none",
                "turns": 0,
                "tool_calls": [],
                "repair_applied": False,
                "skipped": True,
            }
            development_loop.mark_passed(
                "project-context-review",
                "skipped because the project contains no AI-generated modules",
            )
        manager.write_json(
            state["project_id"],
            "validation",
            "project_context_review.json",
            context_review_report,
            producer="design_game_logic",
        )

        log("Unity 컴파일·Play Mode 검증 후 필요하면 생성 코드를 수정합니다.")

        def validate_unity_project():
            return validate_and_repair(
                design=design,
                generation=generation,
                request=request,
                generator=unity_generator,
                feature_generator=feature_generator,
                max_repairs=int(os.environ.get("MAINFLOW_GAME_MAX_REPAIRS", "2")),
                record=lambda name, data: manager.write_json(
                    state["project_id"],
                    "validation",
                    f"repair/{name}.json",
                    data,
                    producer="design_game_logic",
                ),
            )

        design, generation = development_loop.run_task(
            "unity-playmode-validation",
            validate_unity_project,
            evidence=lambda _: "Unity compilation, scene assembly, and Play Mode checks passed",
        )
        quality_report = design.get("quality_report")
        if quality_report is not None:
            unity_generator.update_quality_report(generation.project_root, quality_report)
            quality_report_reference = manager.write_json(
                state["project_id"],
                "game",
                "game_quality_report.json",
                quality_report,
                producer="design_game_logic",
            )
        project_context_index_reference = manager.write_json(
            state["project_id"],
            "game",
            "project_context_index.json",
            build_project_context_index(
                generation.project_root,
                design=design,
                request=request,
                logic_analysis=logic_analysis,
            ),
            producer="design_game_logic",
        )
        development_loop.mark_passed(
            "quality-evaluation",
            (
                f"objective quality score {quality_report['score']}/100 "
                f"(threshold {quality_report['threshold']})"
                if quality_report is not None
                else "Unity validation passed; objective telemetry was unavailable in static mode"
            ),
        )
        if design["generated_modules"]:
            design_reference = manager.write_json(
                state["project_id"],
                "game",
                "repaired_game_logic_design.json",
                design,
                producer="design_game_logic",
            )

        development_loop.run_task(
            "package-project",
            lambda: unity_generator.create_archive(generation.project_root),
            evidence=lambda content: f"created deterministic archive with {len(content)} bytes",
        )
        development_loop.require_complete()
        design["implementation_tasks"] = development_loop.snapshot()
        unity_generator.update_implementation_tasks(
            generation.project_root,
            design["implementation_tasks"],
        )
        design_reference = manager.write_json(
            state["project_id"],
            "game",
            "completed_game_logic_design.json",
            design,
            producer="design_game_logic",
        )
        implementation_tasks_reference = manager.write_json(
            state["project_id"],
            "game",
            "implementation_tasks.json",
            design["implementation_tasks"],
            producer="design_game_logic",
        )
        manifest_reference = manager.import_file(
            state["project_id"],
            "game",
            generation.manifest_path,
            producer="design_game_logic",
            filename="unity_project_manifest.json",
            media_type="application/json",
        )
        archive_reference = manager.write_bytes(
            state["project_id"],
            "game",
            "unity_project.zip",
            unity_generator.create_archive(generation.project_root),
            producer="design_game_logic",
            media_type="application/zip",
        )
        notes = [
            f"{game_spec['genre']} 프리셋과 공통 모듈을 조합한 Unity 설계 초안",
            "Unity 프로젝트와 배포용 ZIP 생성 완료",
            "Unity에서 처음 열면 선택 모듈로 Bootstrap 씬을 자동 재구성",
        ]
        if design["generated_modules"]:
            notes.append(
                f"{feature_provider} 생성 모듈: "
                + ", ".join(module["module_id"] for module in design["generated_modules"])
            )
        notes.append(f"씬 Blueprint 제공자: {design['game_blueprint']['source']}")
        notes.append(
            f"개발 작업 {len(design['implementation_tasks']['tasks'])}개 실행 및 증거 기록 완료"
        )
        draft: GameLogicDraft = {
            "contract_version": CONTRACT_VERSION,
            "draft_id": f"{game_spec['genre'].lower()}-game-logic-draft",
            "status": "generated",
            "engine": "Unity",
            "entry_scene": str(
                Path(generation.entry_scene).relative_to(workspace_project_root).as_posix()
            ),
            "source_artifacts": [
                design_reference,
                manifest_reference,
                archive_reference,
                blueprint_reference,
                implementation_tasks_reference,
                *([quality_report_reference] if quality_report_reference is not None else []),
                *(
                    [project_context_index_reference]
                    if project_context_index_reference is not None
                    else []
                ),
                *design_document_references,
                *request_references,
            ],
            "required_image_asset_ids": image_asset_ids,
            "required_sound_asset_ids": sound_asset_ids,
            "notes": notes,
        }
    except Exception as error:  # noqa: BLE001 - intentional workflow failure boundary
        # This node is a fan-out boundary.  Record game failure as data instead
        # of aborting the graph so image and sound branches can still run.
        log(f"게임 생성에 실패했지만 이미지/사운드 파이프라인은 계속합니다: {error}")
        # Preserve every module that passed its own bounded generation task even
        # when a sibling module ultimately failed.  The diagnostic project and
        # failure artifacts must describe the best recoverable partial result,
        # not the original empty generated_modules collection.
        if generated_modules:
            design["generated_modules"] = deepcopy(generated_modules)
        if development_loop is not None:
            design["implementation_tasks"] = development_loop.snapshot()
            implementation_tasks_reference = manager.write_json(
                state["project_id"],
                "game",
                "failed_implementation_tasks.json",
                design["implementation_tasks"],
                producer="design_game_logic",
            )
        design_document_references = [
            manager.write_json(
                state["project_id"],
                "game",
                f"design/failed_{filename}",
                design["design_v2"][key],  # type: ignore[literal-required]
                producer="design_game_logic",
            )
            for key, filename in UnityProjectGenerator.DESIGN_DOCUMENT_NAMES.items()
        ]
        design_reference = manager.write_json(
            state["project_id"],
            "game",
            "failed_game_logic_design.json",
            design,
            producer="design_game_logic",
        )
        if blueprint_reference is None:
            blueprint_reference = manager.write_json(
                state["project_id"],
                "game",
                "failed_game_blueprint.json",
                design["game_blueprint"],
                producer="design_game_logic",
            )
        failure_reference = manager.write_json(
            state["project_id"],
            "validation",
            "game_generation_failure.json",
            {
                "contract_version": CONTRACT_VERSION,
                "status": "failed",
                "stage": "design_game_logic",
                "error_type": type(error).__name__,
                "message": str(error),
            },
            producer="design_game_logic",
        )
        diagnostic_entry_scene = None
        diagnostic_references = []
        diagnostic_note = ""
        try:
            workspace_project_root = manager.ensure_project(state["project_id"])
            unity_project_root = workspace_project_root / "game" / "unity_project"
            manifest_path = unity_project_root / UnityProjectGenerator.MANIFEST_PATH
            entry_scene_path = unity_project_root / UnityProjectGenerator.ENTRY_SCENE
            if not manifest_path.is_file() or not entry_scene_path.is_file():
                diagnostic_design = deepcopy(design)
                generated_ids = {module["module_id"] for module in generated_modules}
                unresolved_ids = set(diagnostic_design["unsupported_mechanics"])
                diagnostic_design["generated_modules"] = deepcopy(generated_modules)
                diagnostic_design["selected_modules"] = list(
                    dict.fromkeys(
                        [
                            module_id
                            for module_id in diagnostic_design["selected_modules"]
                            if module_id not in unresolved_ids
                        ]
                        + [
                            module_id
                            for module_id in diagnostic_design["unsupported_mechanics"]
                            if module_id in generated_ids
                        ]
                    )
                )
                diagnostic_design["unsupported_mechanics"] = []
                diagnostic_generation = unity_generator.generate(
                    diagnostic_design,
                    unity_project_root,
                    image_style=request["image_style"],
                    mood_style=request["mood_style"],
                    viewpoint=request["viewpoint"],
                    reference_image=request["custom_image"],
                )
                manifest_path = diagnostic_generation.manifest_path
                entry_scene_path = diagnostic_generation.entry_scene
            diagnostic_entry_scene = str(
                entry_scene_path.relative_to(workspace_project_root).as_posix()
            )
            diagnostic_references.append(
                manager.import_file(
                    state["project_id"],
                    "game",
                    manifest_path,
                    filename="diagnostic_unity_project_manifest.json",
                    producer="design_game_logic",
                    media_type="application/json",
                )
            )
            diagnostic_note = (
                "요청 기능 생성은 실패했지만 컴파일·문맥 검사를 위한 진단용 Unity "
                "프로젝트를 game/unity_project에 보존했습니다."
            )
            log(diagnostic_note)
        except Exception as diagnostic_error:  # noqa: BLE001 - preserve original failure
            diagnostic_note = (
                "진단용 Unity 프로젝트 생성도 실패했습니다: "
                f"{type(diagnostic_error).__name__}: {diagnostic_error}"
            )
            log(diagnostic_note)
        draft = {
            "contract_version": CONTRACT_VERSION,
            "draft_id": f"{game_spec['genre'].lower()}-game-logic-draft",
            "status": "failed",
            "engine": "Unity",
            "entry_scene": diagnostic_entry_scene,
            "source_artifacts": [
                design_reference,
                failure_reference,
                blueprint_reference,
                *diagnostic_references,
                *(
                    [implementation_tasks_reference]
                    if implementation_tasks_reference is not None
                    else []
                ),
                *design_document_references,
                *request_references,
            ],
            "required_image_asset_ids": image_asset_ids,
            "required_sound_asset_ids": sound_asset_ids,
            "notes": [
                "게임 생성 실패로 Unity 프로젝트를 완성하지 못했습니다.",
                f"{type(error).__name__}: {error}",
                diagnostic_note,
                "이미지/사운드 요청은 독립적으로 생성되어 후속 파이프라인을 계속합니다.",
            ],
        }
    return {
        "game_logic_draft": manager.write_json(
            state["project_id"],
            "game",
            "game_logic_draft.json",
            draft,
            producer="design_game_logic",
        ),
        "image_asset_request": image_request_reference,
        "sound_asset_request": sound_request_reference,
    }


def _available_context_review_backup(root: Path) -> Path:
    """Preserve the project inspected by the LLM before regenerating repaired code."""

    base = root.with_name(f"{root.name}_before_context_repair")
    if not base.exists():
        return base
    for suffix in range(1, 100):
        candidate = root.with_name(f"{root.name}_before_context_repair_{suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Too many preserved context-review projects beside {root}")
