# Agent File System Rules

이 문서는 Agent가 생성한 실제 파일을 저장하고 다른 Agent에 전달하는 공통 규약이다. Python 구현의 기준은 [`mainflow/ArtifactManager.py`](../mainflow/ArtifactManager.py), 데이터 타입의 기준은 [`mainflow/contracts.py`](../mainflow/contracts.py)다.

## 1. Workspace 구조

`workspace`는 실행 중 생성되는 파일을 보관하는 로컬 작업 공간이며 Git에 커밋하지 않는다. 각 워크플로 실행은 하나의 `project_id`를 사용한다.

```text
workspace/                         # workspace/.gitignore로 내용 제외
└─ {project_id}/                   # 예: 20260926_03
   ├─ generated/
   │  ├─ images/                   # 이미지 파일과 image_draft.json
   │  └─ sounds/                   # 사운드 파일과 sound_draft.json
   ├─ game/                        # 게임 코드, asset_requests, Unity 프로젝트, 통합 결과
   ├─ data/                        # 요청/중간 데이터와 artifact_manifest.json
   └─ validation/                  # 검증 기준서와 검증 결과
```

`project_id` 형식은 `YYYYMMDD_NN`이다. `NN`은 해당 날짜에 생성된 프로젝트의 순번이며 두 자리 이상으로 표현한다. 예를 들어 2026년 9월 26일의 세 번째 프로젝트는 `20260926_03`이다. `ArtifactManager.create_project()`가 기존 폴더를 조회하고 다음 번호를 원자적으로 확보한다.

## 2. 폴더별 책임

| Category | 실제 경로 | 주요 생산자 | 주요 소비자 |
|---|---|---|---|
| `image` | `generated/images/` | `parse_input`(Custom 참고 이미지), `generate_image` | `generate_image`, `validate_image`, `apply_assets_to_game` |
| `sound` | `generated/sounds/` | `generate_sound` | `validate_sound`, `apply_assets_to_game` |
| `game` | `game/` | `design_game_logic`, `apply_assets_to_game` | 이미지·사운드 생성, `validate_game`, `final_validation` |
| `data` | `data/` | `parse_input`, `analysis`, `logic_analysis` 및 공통 시스템 | 요구사항을 읽는 모든 Agent |
| `validation` | `validation/` | 검증서/검증 Agent | 후속 검증 및 최종 검증 Agent |

`data/artifact_manifest.json`은 `ArtifactManager`가 관리한다. Agent가 직접 편집하면 안 된다.

## 3. Agent 간 파일 전달 방식

State에는 파일 내용이나 임의의 절대 경로 대신 `ArtifactReference`만 전달한다.

1. 생산 Agent가 `write_json`, `write_text`, `write_bytes` 또는 `import_file`을 호출한다.
2. `ArtifactManager`가 category에 맞는 폴더에 파일을 원자적으로 저장한다.
3. 파일의 ID, 상대 경로, 크기, SHA-256, 생산자 정보를 manifest에 기록한다.
4. 생산 Agent는 반환받은 `ArtifactReference`를 자신의 Output State 키에 넣는다.
5. 소비 Agent는 State의 참조를 `read_json`, `read_text`, `read_bytes`에 전달한다.
6. 관리자가 프로젝트 경계, 파일 크기, SHA-256을 확인한 뒤 내용을 반환한다.

```python
from mainflow.ArtifactManager import ArtifactManager

manager = ArtifactManager()
project_id = manager.create_project()

request_ref = manager.write_json(
    project_id,
    "data",
    "parsed_request.json",
    {
        "contract_version": "3.4.0",
        "genre": "플랫포머",
        "viewpoint": "사이드뷰",
        "mood_style": "Fantasy",
    },
    producer="parse_input",
)

# State에는 request_ref만 전달한다.
parsed_request = manager.read_json(request_ref)
```

이미지 생성기처럼 외부 경로에 결과를 만드는 도구는 `import_file()`로 파일을 workspace 안에 복사한 다음 반환된 참조를 전달한다. Unity/Godot 등 외부 도구가 별도 경로를 요구하면 `materialize()`로 검증된 복사본을 만든다.

## 4. `ArtifactReference` 규격

```json
{
  "contract_version": "3.4.0",
  "artifact_id": "image-<uuid>",
  "project_id": "20260926_03",
  "category": "image",
  "relative_path": "generated/images/player.png",
  "media_type": "image/png",
  "size_bytes": 12345,
  "sha256": "<64자리 SHA-256>",
  "created_at": "2026-09-26T10:00:00+00:00",
  "producer": "generate_image"
}
```

## Custom 이미지 전달

`image_style=Custom`이면 `parse_input`이 외부 PNG/JPG를 다음 위치로 가져온다.

```text
workspace/{project_id}/generated/images/references/custom_style.{png|jpg|jpeg}
```

확장자뿐 아니라 PNG/JPEG 파일 signature를 검사한다. `parsed_request.json`에는 원본 절대 경로를
남기지 않고 해당 파일의 `ArtifactReference`를 `custom_image` 필드에 기록한다. 게임 설계가
만드는 `image_asset_request.json`에도 같은 참조를 `reference_image`로 전달한다. 이미지 Agent는
이 참조를 `ArtifactManager.read_bytes()`로 읽어 생성 참고 자료로 사용한다.

분석 중간 산출물은 다음 위치에 보관한다.

```text
workspace/{project_id}/data/analysis.json
workspace/{project_id}/data/logic_analysis.json
workspace/{project_id}/game/asset_requests/image_asset_request.json
workspace/{project_id}/game/asset_requests/sound_asset_request.json
workspace/{project_id}/game/game_blueprint.json
workspace/{project_id}/game/implementation_tasks.json
workspace/{project_id}/game/game_quality_report.json
workspace/{project_id}/validation/development/*.json
```

`implementation_tasks.json`은 게임 구현의 작업 DAG와 최종 시도 횟수·상태·증거를 담는다.
`validation/development/`의 번호가 붙은 스냅샷은 각 작업의 실행·재시도·성공 또는 실패 직후
상태를 보존한다. 따라서 긴 생성 과정이 중단돼도 어느 단계에서 왜 멈췄는지 확인할 수 있다.

에셋 요청 JSON은 생성된 Unity 프로젝트의
`Assets/GameTemplate/Generated/AssetRequests/`에도 같은 내용으로 포함된다. 이미지·사운드 Flow는
State로 받은 `ArtifactReference`를 통해 workspace 사본을 읽으며 Unity 프로젝트 내부 경로에 직접
의존하지 않는다.

이미지 Flow는 `image_asset_request` State 참조를, 사운드 Flow는 `sound_asset_request` State 참조를
`ArtifactManager.read_json()`에 넘긴다. 두 요청에는 공통 `image_style`, `genre`와 게임 설계가
유지한 `viewpoint`가 포함되고, 각 에셋의 `asset_id`, `unity_binding_key`, `generation_spec`은
결과 draft 및 Unity 적용 단계까지 변경하지 않는다. 이미지 draft는 `kind`와 바인딩 키를 에셋별로,
생성 실패한 필수 ID를 `missing_required_asset_ids`로 전달한다. 사운드 요청은 목표 길이, 반복 여부,
채널, sample rate, Unity load type, mixer group, spatial blend를 구조화해 전달한다.

`apply_assets_to_game`은 이미지·사운드 검증 결과의 `validated_asset_ids`에 포함된 파일만
`game/unity_project/Assets/GameTemplate/Generated/AppliedAssets/`로 복사한다. 동시에
`AssetBindingManifest.json`을 Unity 프로젝트와 `game/asset_binding_manifest.json`에 기록하고,
에셋이 포함된 최종 결과를 `game/integrated_unity_project.zip`으로 만든다. 필수 에셋 중 검증을
통과하지 못한 ID는 manifest의 `missing_required_asset_ids`에 남으므로 일부 에셋 실패가 다른
에셋의 적용을 막지 않는다.

참조의 `relative_path`를 직접 이어 붙여 읽지 않는다. 항상 `ArtifactManager`의 읽기 메서드를 사용한다.

## MCP 작업 파일

LLM이 MCP로 Unity 소스 등 생성 중인 작업 파일을 수정할 때도 `ArtifactManager`의 프로젝트 경계를
사용한다. `resolve_project_path`, `list_project_files`, `read_project_file`, `write_project_file`,
`write_project_text`가 이 용도다.

- 작업 파일은 반드시 `workspace/{project_id}/` 내부에 둔다.
- 기존 파일 수정에는 직전 읽기에서 얻은 SHA-256이 필요하다.
- manifest와 등록된 Artifact는 MCP 작업 파일 API로 덮어쓸 수 없다.
- 수정 가능한 작업 파일을 최종 산출물로 확정할 때 새 Artifact로 등록한다.
- 세부 도구 사용법과 Node별 권한은 [`MCPManager.md`](MCPManager.md)를 따른다.

## 5. 파일명과 수정 규칙

- 파일명은 영문 소문자 `snake_case`를 기본으로 하고 확장자를 명시한다.
- 동일한 논리 결과는 고정된 의미의 이름을 쓴다. 예: `image_validation_result.json`.
- 이미 등록된 산출물은 불변으로 취급한다. 수정본은 새 파일명으로 저장해 새 `artifact_id`를 발급한다.
- `overwrite=True`는 manifest 같은 시스템 파일이나 명시적으로 교체가 필요한 경우에만 사용한다.
- Agent가 `workspace` 외부 경로를 직접 State에 전달하지 않는다.
- `..`, 절대 경로 또는 category 폴더 밖으로 벗어나는 경로는 금지한다.
- JSON은 UTF-8, 들여쓰기 2칸, 마지막 줄바꿈을 사용한다.

## 6. 병렬 실행과 안전성

- 게임 설계가 두 에셋 요청을 만든 뒤 이미지 생성, 게임 검증, 사운드 생성은 병렬 실행될 수
  있으므로 서로 다른 category/파일을 쓴다.
- manifest 갱신은 `.artifact_manifest.lock`을 이용해 직렬화하며 완료 후 잠금 파일은 삭제된다.
- 실제 파일과 manifest는 임시 파일에 먼저 쓴 뒤 원자적으로 게시한다.
- 읽을 때 크기나 SHA-256이 다르면 손상 또는 외부 수정을 의미하므로 즉시 실패한다.
- 비밀키, API 토큰, 사용자 인증 정보는 workspace와 manifest에 저장하지 않는다.

## 7. Git 및 정리 정책

- `workspace/.gitignore`는 `.gitignore` 자신을 제외한 모든 런타임 프로젝트를 무시한다.
- 코드 리뷰에는 실제 생성물 대신 계약, fixture 또는 작은 테스트 데이터만 별도 테스트 폴더에 추가한다.
- 프로젝트 삭제는 실행 중인 Agent가 없고 결과 보존 여부를 확인한 뒤 수행한다.
- 자동 정리 기능을 추가할 경우 보존 기간과 복구 정책을 팀 합의로 먼저 정한다.

## 8. 변경 체크리스트

- [ ] 새 파일 종류에 맞는 `ArtifactCategory` 또는 기존 category를 선택했다.
- [ ] 생산 Agent가 `ArtifactManager`로 저장하고 참조만 반환한다.
- [ ] 소비 Agent가 `ArtifactManager`로 읽으며 직접 경로 접근을 하지 않는다.
- [ ] `mainflow/contracts.py`의 Input/Output 및 payload 타입을 갱신했다.
- [ ] `ContractRule.md`와 이 문서를 같은 커밋에서 갱신했다.
- [ ] Graph의 핵심 노드와 Edge가 의도치 않게 바뀌지 않았는지 확인했다.
- [ ] 병렬 실행 시 파일명 충돌과 manifest 갱신을 검증했다.

## 최종 검증 증거와 패키지

- `validation/image_validation_result.json`, `sound_validation_result.json`의 `validated_assets`는 최종 선택 파일 참조를 포함한다.
- `generated/sounds/processed/*.wav`는 DSP 보정본이며 Unity 적용기는 선택된 참조의 실제 확장자를 사용한다.
- `game/asset_binding_manifest.json`은 통합 게임의 `asset_binding_manifest` 참조로 전달한다.
- `validation/final_unity_validation.log`: 에셋 적용 후 Unity 컴파일·Play Mode 실행 로그.
- `validation/final_asset_binding_report.json`: 이번 실행의 import·registry·씬 바인딩 보고서 snapshot.
- `validation/final_validation_result.json`: 기준별 판정, 실패 원인, `evidence` 참조와 최종 패키지 참조.
- `validation/visual_validation_result.json`: 시각 검증 모드, 회차별 점수·finding·수정 파일과
  Unity 재검증 결과. 비활성 실행도 `skipped` 기록을 남긴다.
- `validation/visual/target.png`, `attempt_N.png`: 목표 화면과 회차별 실제 Unity 캡처.
- `validation/game_validator_ai_result.json`: 완성된 게임에 대한 독립 Validator AI의 요구사항
  충족도, 품질 점수, 근거, 수정 권고.
- `validation/project_context_review_attempt_N.json`: Unity 실행 전 문맥 검수의 제한된 재시도별
  결과와 발견 사항.
- `game/project_context_index.json`: 완성된 Unity 프로젝트의 C# 파일 해시, 클래스, 상속 관계,
  실제 공개 메서드·속성·필드·이벤트, 모듈 ID와 원본 기능·검증 기준·이벤트 연결을 보존한
  결정적 인덱스. LLM 자연어 요약의 대체물이므로 생성 코드와 Validator가 정확한 식별자를
  조회할 때 사용한다.
- `game/validated_unity_project.zip`: 최종 통과한 경우에만 생성되는 Unity 실행 이후의 프로젝트 ZIP.

기존 `game/integrated_unity_project.zip`은 에셋 복사 직후 패키지다. 최종 검증된 결과를 받을 때는
`FinalValidationResult.entry_artifact`를 사용한다.
