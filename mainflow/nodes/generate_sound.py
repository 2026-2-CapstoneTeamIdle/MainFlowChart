"""Generate sound assets for the requested game."""

from __future__ import annotations

from typing import cast

from mainflow.ArtifactManager import ArtifactManager
from mainflow.contracts import (
    CONTRACT_VERSION,
    AnalysisResult,
    AssetGenerationRequest,
    GenerateSoundAgentInput,
    GenerateSoundAgentOutput,
    LogicAnalysis,
    ParsedRequest,
    SoundAsset,
    SoundDraft,
)
from mainflow.nodes._common import log
from sound_pipeline import (
    SoundProviderError,
    audio_duration,
    fallback_provider,
    plan_sound_assets,
    primary_provider,
)


# Node 계약
# - 이전 Node: design_game_logic
# - 입력 State: project_id, parsed_request, analysis, logic_analysis, sound_asset_request
# - 입력 파일: data/*.json, game/asset_requests/sound_asset_request.json
# - 출력 State: sound_draft(ArtifactReference)
# - 출력 파일: generated/sounds/sound_draft.json, generated/sounds/<asset>.wav
# - 다음 Node: validate_sound (asset_validation_spec과 합류)
def generate_sound_node(
    state: GenerateSoundAgentInput,
) -> GenerateSoundAgentOutput:
    """Generate one WAV per requested sound asset and return the draft reference."""
    manager = ArtifactManager()
    parsed = cast(ParsedRequest, manager.read_json(state["parsed_request"]))
    cast(AnalysisResult, manager.read_json(state["analysis"]))
    cast(LogicAnalysis, manager.read_json(state["logic_analysis"]))
    asset_request = cast(
        AssetGenerationRequest,
        manager.read_json(state["sound_asset_request"]),
    )

    plans = plan_sound_assets(asset_request, parsed)
    provider = primary_provider()
    fallback = fallback_provider()
    log(f"사운드 에셋 {len(plans)}개를 생성합니다. (provider={provider.name})")

    assets: list[SoundAsset] = []
    notes: list[str] = [
        f"provider={provider.name}",
        f"mood={parsed['mood_style']} genre={parsed['genre']}",
    ]
    missing_required: list[str] = []
    tripped: SoundProviderError | None = None
    for plan in plans:
        used = provider
        try:
            if tripped is not None:  # circuit breaker: don't wait out the same failure per asset
                raise SoundProviderError(f"이전 에셋 오류로 호출 생략 - {tripped}")
            result = provider.generate(plan)
        except SoundProviderError as error:
            if error.fatal:
                tripped = error
            if fallback is None or fallback.name == provider.name:
                notes.append(f"{plan.asset_id}: 생성 실패 - {error}")
                if plan.required:
                    missing_required.append(plan.asset_id)
                continue
            notes.append(f"{plan.asset_id}: {provider.name} 실패로 {fallback.name} 대체 - {error}")
            used, result = fallback, fallback.generate(plan)

        reference = manager.write_bytes(
            state["project_id"],
            "sound",
            f"{plan.file_stem}.{result.file_format}",
            result.audio,
            producer="generate_sound",
            media_type=result.media_type,
        )
        duration = audio_duration(result.audio, result.file_format)
        assets.append(
            {
                "asset_id": plan.asset_id,
                "name": plan.name,
                "kind": plan.kind,
                "unity_binding_key": plan.unity_binding_key,
                "artifact": reference,
                "file_format": result.file_format,
                "duration_seconds": duration,
                "loop": plan.loop,
                "mixer_group": plan.mixer_group,
                "prompt": plan.prompt,
                "provider": used.name,
            }
        )
        notes.append(
            f"{plan.asset_id}: kind={plan.kind} category={plan.category} loop={plan.loop} "
            f"provider={used.name} endpoint={result.endpoint} model={result.model_id} "
            f"format={result.file_format} requested={plan.duration_seconds}s actual={duration}s "
            f"request_id={result.request_id}"
        )
        log(f"  - {plan.asset_id} ({plan.kind}/{plan.category}) → {reference['relative_path']}")

    draft: SoundDraft = {
        "contract_version": CONTRACT_VERSION,
        "draft_id": f"{asset_request['request_id']}-draft",
        "status": "failed" if missing_required else "generated",
        "assets": assets,
        "missing_required_asset_ids": missing_required,
        "notes": notes,
    }
    return {
        "sound_draft": manager.write_json(
            state["project_id"],
            "sound",
            "sound_draft.json",
            draft,
            producer="generate_sound",
        )
    }
